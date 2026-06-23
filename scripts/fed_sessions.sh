#!/usr/bin/env bash
# fed_sessions.sh — ensure tmux peer-agent sessions exist.
#
# By default this reuses or creates every installed peer among:
#   claude-*  -> IS_SANDBOX=1 claude --dangerously-skip-permissions
#   codex-*   -> codex --dangerously-bypass-approvals-and-sandbox
#   hermes-*  -> hermes --cli --yolo
#
# Override peers with FED_AGENTS=claude,codex or positional args:
#   fed_sessions.sh claude codex
#
# Override launch commands with FED_CLAUDE_CMD, FED_CODEX_CMD, FED_HERMES_CMD.
# Prints FEDERATE_DIR=... plus <AGENT>_SESSION=... for the caller to consume.
set -uo pipefail

W="${FED_TMUX_WIDTH:-230}"
H="${FED_TMUX_HEIGHT:-50}"
SCRIPT_DIR=""
if script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"; then
  SCRIPT_DIR="$script_dir"
fi
SKILL_DIR=""
if [ -n "$SCRIPT_DIR" ] && skill_dir="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)"; then
  SKILL_DIR="$skill_dir"
fi

die() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v tmux >/dev/null 2>&1 || die "tmux not found. Install tmux, then rerun fed_sessions.sh."
tmux start-server >/dev/null 2>&1 || true

csv_to_words() {
  printf '%s' "$1" | tr ',' ' '
}

agent_bin() {
  case "$1" in
    claude) echo "claude" ;;
    codex) echo "codex" ;;
    hermes) echo "hermes" ;;
    *) return 1 ;;
  esac
}

agent_cmd() {
  case "$1" in
    claude) echo "${FED_CLAUDE_CMD:-IS_SANDBOX=1 claude --dangerously-skip-permissions}" ;;
    codex) echo "${FED_CODEX_CMD:-codex --dangerously-bypass-approvals-and-sandbox}" ;;
    hermes) echo "${FED_HERMES_CMD:-hermes --cli --yolo}" ;;
    *) return 1 ;;
  esac
}

next_name() {
  prefix="$1"
  i=0
  while tmux has-session -t "${prefix}-${i}" 2>/dev/null; do
    i=$((i + 1))
  done
  echo "${prefix}-${i}"
}

find_existing() {
  prefix="$1"
  tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -m1 "^${prefix}-" || true
}

ensure_agent() {
  agent="$1"
  bin="$(agent_bin "$agent")" || {
    echo "SKIPPED unknown agent '$agent'" >&2
    return 0
  }

  existing="$(find_existing "$agent")"
  if [ -n "$existing" ]; then
    tmux resize-window -t "$existing" -x "$W" -y "$H" 2>/dev/null || true
    printf '%s_SESSION=%s\n' "$(printf '%s' "$agent" | tr '[:lower:]' '[:upper:]')" "$existing"
    return 0
  fi

  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "SKIPPED $agent: '$bin' not found on PATH" >&2
    return 0
  fi

  name="$(next_name "$agent")"
  cmd="$(agent_cmd "$agent")"
  tmux new-session -d -s "$name" -x "$W" -y "$H" || die "failed to create tmux session $name"
  tmux send-keys -t "$name" "$cmd" Enter
  echo "CREATED $name with: $cmd (booting; wait for a live composer before first send)" >&2
  printf '%s_SESSION=%s\n' "$(printf '%s' "$agent" | tr '[:lower:]' '[:upper:]')" "$name"
}

if [ "$#" -gt 0 ]; then
  agents="$*"
else
  agents="$(csv_to_words "${FED_AGENTS:-claude,codex,hermes}")"
fi

available_count=0
echo "FEDERATE_DIR=$SKILL_DIR"
for agent in $agents; do
  out="$(ensure_agent "$agent")" || exit $?
  if [ -n "$out" ]; then
    echo "$out"
    available_count=$((available_count + 1))
  fi
done

if [ "$available_count" -lt 2 ]; then
  die "federation needs at least two available peer sessions; got $available_count. Install/authenticate at least two of: claude, codex, hermes."
fi
