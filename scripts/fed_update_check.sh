#!/usr/bin/env bash
# fed_update_check.sh [--apply] — check/update the installed Federate skill.
#
# Default: print UP_TO_DATE or UPDATE_AVAILABLE and exit without changing files.
# --apply: fetch the latest payload for the recorded source/ref and update the
# installed skill directory in place. Restart/refresh the host agent afterwards.
set -euo pipefail

ACTION="check"
if [ "${1:-}" = "--apply" ]; then
  ACTION="apply"
  shift
fi
[ "$#" -eq 0 ] || { echo "usage: fed_update_check.sh [--apply]" >&2; exit 2; }

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

github_repo_from_source() {
  printf '%s' "$1" | sed -nE 's#^(https://github.com/|git@github.com:)([^/]+/[^/.]+)(\.git)?$#\2#p'
}

remote_commit() {
  source_url="$1"
  ref="$2"
  commit=""

  if command -v git >/dev/null 2>&1; then
    commit="$(git ls-remote "$source_url" "$ref" 2>/dev/null | awk 'NR == 1 {print $1}')"
  fi
  if [ -n "$commit" ]; then
    echo "$commit"
    return 0
  fi

  repo="$(github_repo_from_source "$source_url")"
  if [ -n "$repo" ] && command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://api.github.com/repos/$repo/commits/$ref" 2>/dev/null |
      sed -n 's/^[[:space:]]*"sha": "\([0-9a-f][0-9a-f]*\)",[[:space:]]*$/\1/p' |
      head -n 1
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

LATEST="$(remote_commit "$SOURCE" "$REF" || true)"
[ -n "$LATEST" ] || die "could not resolve latest commit for $SOURCE $REF"

if [ "$INSTALLED" = "$LATEST" ] && [ "$DIRTY" != "true" ]; then
  echo "UP_TO_DATE installed=$INSTALLED ref=$REF source=$SOURCE"
  exit 0
fi

echo "UPDATE_AVAILABLE installed=$INSTALLED latest=$LATEST ref=$REF source=$SOURCE dirty=$DIRTY"

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
