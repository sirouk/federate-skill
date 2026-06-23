#!/usr/bin/env bash
# install.sh — install the "federate" skill into Claude Code.
#
#   From a clone:   ./install.sh
#   Remote (raw):   curl -fsSL https://raw.githubusercontent.com/YOURUSER/federate-skill/main/install.sh | bash
#
# Env overrides:
#   FEDERATE_DEST   install target (default: ~/.claude/skills/federate)
#                   e.g. project-scoped:  FEDERATE_DEST=$PWD/.claude/skills/federate
#   FEDERATE_RAW    raw base URL when fetching remotely
#                   (default: https://raw.githubusercontent.com/YOURUSER/federate-skill/main)
set -euo pipefail

DEST="${FEDERATE_DEST:-$HOME/.claude/skills/federate}"
RAW="${FEDERATE_RAW:-https://raw.githubusercontent.com/YOURUSER/federate-skill/main}"
FILES=(SKILL.md scripts/fed_sessions.sh scripts/fed_send.sh scripts/fed_read.py scripts/fed_wait.sh)

# Where am I running from? (a clone has the files next to this script)
SRC=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
fi

mkdir -p "$DEST/scripts"

if [ -n "$SRC" ] && [ -f "$SRC/SKILL.md" ]; then
  echo "Installing from local clone: $SRC"
  for f in "${FILES[@]}"; do
    mkdir -p "$DEST/$(dirname "$f")"
    cp "$SRC/$f" "$DEST/$f"
  done
else
  echo "Installing from raw URL: $RAW"
  command -v curl >/dev/null || { echo "ERROR: curl not found" >&2; exit 1; }
  case "$RAW" in *YOURUSER/federate-skill*)
    echo "WARNING: FEDERATE_RAW still points at the placeholder YOURUSER/federate-skill." >&2
    echo "         Set FEDERATE_RAW to your repo's raw base, or run ./install.sh from a clone." >&2 ;;
  esac
  for f in "${FILES[@]}"; do
    mkdir -p "$DEST/$(dirname "$f")"
    curl -fsSL "$RAW/$f" -o "$DEST/$f"
  done
fi

chmod +x "$DEST"/scripts/*.sh "$DEST"/scripts/*.py 2>/dev/null || true

echo "✓ federate skill installed -> $DEST"
echo "  Refresh Claude Code and say \"federate\" to use it."
