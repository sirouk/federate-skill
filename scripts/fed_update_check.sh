#!/usr/bin/env bash
# fed_update_check.sh [--apply] [--force] — check/update the installed Federate skill.
#
# Default: print UP_TO_DATE, UPDATE_AVAILABLE, or LOCAL_DIRTY and exit without changing files.
# --apply: fetch the latest payload for the recorded source/ref, stage it, then
# replace the installed skill directory. Restart/refresh the host agent afterwards.
set -euo pipefail

ACTION="check"
FORCE="0"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) ACTION="apply" ;;
    --force) FORCE="1" ;;
    *) echo "usage: fed_update_check.sh [--apply] [--force]" >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)"
META="$SKILL_DIR/.federate-install.json"

die() {
  echo "ERROR: $*" >&2
  exit 2
}

json_value() {
  key="$1"
  python3 - "$META" "$key" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
value = data.get(key, "")
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

is_full_sha() {
  [[ "${1:-}" =~ ^[0-9a-fA-F]{40}$ ]]
}

normalize_sha() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

github_repo_from_source() {
  printf '%s' "$1" | sed -nE 's#^(https://github.com/|git@github.com:)([^/]+/[^/.]+)(\.git)?$#\2#p'
}

remote_commit() {
  source_url="$1"
  ref="$2"
  commit=""

  if is_full_sha "$ref"; then
    normalize_sha "$ref"
    return 0
  fi

  if command -v git >/dev/null 2>&1; then
    commit="$(git ls-remote "$source_url" "$ref" 2>/dev/null | awk 'NR == 1 {print $1}')"
  fi
  if is_full_sha "$commit"; then
    normalize_sha "$commit"
    return 0
  fi

  repo="$(github_repo_from_source "$source_url")"
  if [ -n "$repo" ] && command -v curl >/dev/null 2>&1; then
    commit="$(curl -fsSL "https://api.github.com/repos/$repo/commits/$ref" 2>/dev/null |
      sed -n 's/^[[:space:]]*"sha": "\([0-9a-f][0-9a-f]*\)",[[:space:]]*$/\1/p' |
      head -n 1)"
    if is_full_sha "$commit"; then
      normalize_sha "$commit"
    fi
  fi
}

raw_base_for_commit() {
  source_url="$1"
  commit="$2"
  repo="$(github_repo_from_source "$source_url")"
  [ -n "$repo" ] || return 1
  printf 'https://raw.githubusercontent.com/%s/%s\n' "$repo" "$commit"
}

[ -f "$META" ] || die "no install metadata at $META; run: curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash"
command -v python3 >/dev/null 2>&1 || die "python3 not found; cannot read install metadata."

SOURCE="$(json_value source)"
REF="$(json_value ref)"
INSTALLED="$(json_value commit)"
DIRTY="$(json_value dirty)"

[ -n "$SOURCE" ] || die "install metadata missing source"
[ -n "$REF" ] || die "install metadata missing ref"
[ -n "$INSTALLED" ] || die "install metadata missing commit"
INSTALLED="$(normalize_sha "$INSTALLED")"
is_full_sha "$INSTALLED" || die "install metadata commit is not a full 40-hex SHA: $INSTALLED"

LATEST="$(remote_commit "$SOURCE" "$REF" || true)"
[ -n "$LATEST" ] || die "could not resolve full 40-hex latest commit for $SOURCE $REF"
LATEST="$(normalize_sha "$LATEST")"
is_full_sha "$LATEST" || die "resolved latest commit is not a full 40-hex SHA: $LATEST"

if [ "$INSTALLED" = "$LATEST" ] && [ "$DIRTY" != "true" ]; then
  echo "UP_TO_DATE installed=$INSTALLED ref=$REF source=$SOURCE"
  exit 0
fi

if [ "$DIRTY" = "true" ]; then
  stale="false"
  [ "$INSTALLED" != "$LATEST" ] && stale="true"
  echo "LOCAL_DIRTY installed=$INSTALLED latest=$LATEST stale=$stale ref=$REF source=$SOURCE"
  if [ "$ACTION" != "apply" ]; then
    exit 0
  fi
  [ "$FORCE" = "1" ] || die "installed payload is marked dirty; ask the operator whether to proceed, then rerun with --apply --force to overwrite it."
  echo "OVERWRITING_DIRTY installed=$INSTALLED latest=$LATEST stale=$stale ref=$REF source=$SOURCE"
else
  echo "UPDATE_AVAILABLE installed=$INSTALLED latest=$LATEST ref=$REF source=$SOURCE dirty=$DIRTY"
fi

if [ "$ACTION" != "apply" ]; then
  exit 0
fi

command -v curl >/dev/null 2>&1 || die "curl not found; cannot download update payload."
RAW="$(raw_base_for_commit "$SOURCE" "$LATEST")" || die "cannot derive raw GitHub URL from source: $SOURCE"
TMP="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

curl -fsSL "$RAW/install.sh" -o "$TMP/install.sh"
chmod +x "$TMP/install.sh"
FEDERATE_DEST="$SKILL_DIR" \
FEDERATE_SOURCE="$SOURCE" \
FEDERATE_REF="$REF" \
FEDERATE_COMMIT="$LATEST" \
FEDERATE_RAW="$RAW" \
  bash "$TMP/install.sh"
echo "UPDATED installed=$LATEST ref=$REF source=$SOURCE"
