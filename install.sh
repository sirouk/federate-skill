#!/usr/bin/env bash
# install.sh — install the "federate" skill for Claude Code, Codex, and Hermes.
#
#   From a clone: ./install.sh
#   Remote:       curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash
#
# Env overrides:
#   FEDERATE_TARGETS comma-separated targets: claude,codex,hermes,all (default: all)
#   FEDERATE_DEST    explicit install target; overrides FEDERATE_TARGETS
#                    e.g. project-scoped: FEDERATE_DEST=$PWD/.claude/skills/federate
#   FEDERATE_RAW     raw base URL when fetching remotely
#                    (default: https://raw.githubusercontent.com/sirouk/federate-skill/main)
set -euo pipefail

RAW="${FEDERATE_RAW:-https://raw.githubusercontent.com/sirouk/federate-skill/main}"
FILES=(SKILL.md scripts/fed_sessions.sh scripts/fed_send.sh scripts/fed_read.py scripts/fed_wait.sh)

# Where am I running from? (a clone has the files next to this script)
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  if src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"; then
    SRC="$src_dir"
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
  echo "  -> $dest"
}

target_path() {
  case "$1" in
    claude) echo "${CLAUDE_HOME:-$HOME/.claude}/skills/federate" ;;
    codex) echo "${CODEX_HOME:-$HOME/.codex}/skills/federate" ;;
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
  echo "Installing from local clone: $SRC"
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
