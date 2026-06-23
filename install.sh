#!/usr/bin/env bash
# install.sh — install the "federate" skill for Claude Code, Codex, and Hermes.
#
#   curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash
#
# Env overrides:
#   FEDERATE_TARGETS comma-separated targets: claude,codex,hermes,all (default: all)
#   FEDERATE_DEST    explicit install target; overrides FEDERATE_TARGETS
#                    e.g. project-scoped: FEDERATE_DEST=$PWD/.claude/skills/federate
#   CODEX_SKILLS_HOME Codex user skills root (default: ~/.agents/skills)
#   FEDERATE_SOURCE  git source URL recorded for update checks
#                    (default: https://github.com/sirouk/federate-skill.git)
#   FEDERATE_REF     source ref recorded for update checks (default: main)
#   FEDERATE_COMMIT  explicit installed commit, useful for pinned/manual installs
#   FEDERATE_RAW     raw base URL when fetching remotely
#                    (default: https://raw.githubusercontent.com/sirouk/federate-skill/$FEDERATE_REF)
set -euo pipefail

SOURCE="${FEDERATE_SOURCE:-https://github.com/sirouk/federate-skill.git}"
REF="${FEDERATE_REF:-main}"
RAW="${FEDERATE_RAW:-https://raw.githubusercontent.com/sirouk/federate-skill/$REF}"
FILES=(SKILL.md agents/openai.yaml scripts/fed_sessions.sh scripts/fed_send.sh scripts/fed_read.py scripts/fed_wait.sh scripts/fed_update_check.sh)

# Where am I running from? (local development has files next to this script)
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  if src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"; then
    SRC="$src_dir"
  fi
fi

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
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

install_commit() {
  if [ -n "$SRC" ] && [ -d "$SRC/.git" ] && command -v git >/dev/null 2>&1; then
    git -C "$SRC" rev-parse HEAD 2>/dev/null || true
    return 0
  fi
  remote_commit "$SOURCE" "$REF" || true
}

install_ref() {
  if [ -n "$SRC" ] && [ -d "$SRC/.git" ] && command -v git >/dev/null 2>&1; then
    branch="$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    if [ -n "$branch" ] && [ "$branch" != "HEAD" ]; then
      echo "$branch"
      return 0
    fi
  fi
  echo "$REF"
}

install_source() {
  if [ -n "$SRC" ] && [ -d "$SRC/.git" ] && command -v git >/dev/null 2>&1; then
    remote="$(git -C "$SRC" remote get-url origin 2>/dev/null || true)"
    if [ -n "$remote" ]; then
      echo "$remote"
      return 0
    fi
  fi
  echo "$SOURCE"
}

install_dirty() {
  if [ -n "$SRC" ] && [ -d "$SRC/.git" ] && command -v git >/dev/null 2>&1; then
    if [ -n "$(git -C "$SRC" status --porcelain 2>/dev/null || true)" ]; then
      echo true
    else
      echo false
    fi
    return 0
  fi
  echo false
}

write_metadata() {
  dest="$1"
  source_url="$2"
  ref="$3"
  commit="$4"
  raw="$5"
  dirty="$6"
  installed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  cat > "$dest/.federate-install.json" <<EOF
{
  "source": "$(json_escape "$source_url")",
  "ref": "$(json_escape "$ref")",
  "commit": "$(json_escape "$commit")",
  "raw": "$(json_escape "$raw")",
  "dirty": $dirty,
  "installed_at": "$(json_escape "$installed_at")"
}
EOF
}

COMMIT="${FEDERATE_COMMIT:-$(install_commit)}"
INSTALL_REF="$(install_ref)"
INSTALL_SOURCE="$(install_source)"
DIRTY="$(install_dirty)"
if [ -z "$COMMIT" ]; then
  echo "ERROR: could not resolve the Federate source commit. Use the documented curl installer with network access, or set FEDERATE_COMMIT." >&2
  exit 1
fi
if [ -z "${FEDERATE_RAW:-}" ]; then
  repo="$(github_repo_from_source "$INSTALL_SOURCE")"
  if [ -n "$repo" ] && [ -n "$COMMIT" ]; then
    RAW="https://raw.githubusercontent.com/$repo/$COMMIT"
  fi
fi

copy_one() {
  dest="$1"
  mkdir -p "$dest/scripts"

  for f in "${FILES[@]}"; do
    mkdir -p "$dest/$(dirname "$f")"
    if [ -n "$SRC" ] && [ -f "$SRC/SKILL.md" ]; then
      cp "$SRC/$f" "$dest/$f"
    else
      curl -fsSL "$RAW/$f" -o "$dest/$f"
    fi
  done
  chmod +x "$dest"/scripts/*.sh "$dest"/scripts/*.py 2>/dev/null || true
  write_metadata "$dest" "$INSTALL_SOURCE" "$INSTALL_REF" "$COMMIT" "$RAW" "$DIRTY"
  echo "  -> $dest"
}

target_path() {
  case "$1" in
    claude) echo "${CLAUDE_HOME:-$HOME/.claude}/skills/federate" ;;
    codex) echo "${CODEX_SKILLS_HOME:-$HOME/.agents/skills}/federate" ;;
    hermes) echo "${HERMES_HOME:-$HOME/.hermes}/skills/software-development/federate" ;;
    *) echo "ERROR: unknown target '$1' (use claude,codex,hermes,all or FEDERATE_DEST)" >&2; exit 2 ;;
  esac
}

expand_targets() {
  raw="${FEDERATE_TARGETS:-all}"
  raw="$(printf '%s' "$raw" | tr ',' ' ')"
  out=""
  for t in $raw; do
    case "$t" in
      all) out="$out claude codex hermes" ;;
      claude|codex|hermes) out="$out $t" ;;
      *) echo "ERROR: unknown target '$t' (use claude,codex,hermes,all)" >&2; exit 2 ;;
    esac
  done
  printf '%s\n' "$out"
}

if [ -z "${SRC:-}" ] || [ ! -f "$SRC/SKILL.md" ]; then
  echo "Installing from raw URL: $RAW"
  command -v curl >/dev/null || { echo "ERROR: curl not found" >&2; exit 1; }
else
  echo "Installing from local source: $SRC"
fi

echo "Installed federate skill:"
if [ -n "${FEDERATE_DEST:-}" ]; then
  copy_one "$FEDERATE_DEST"
else
  seen=""
  for target in $(expand_targets); do
    dest="$(target_path "$target")"
    case " $seen " in
      *" $dest "*) continue ;;
    esac
    seen="$seen $dest"
    copy_one "$dest"
  done
fi

echo "Refresh/restart the agent session, then say \"federate\" to use it."
