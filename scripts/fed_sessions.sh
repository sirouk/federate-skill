#!/usr/bin/env bash
# fed_sessions.sh — ensure tmux peer-agent sessions exist.
#
# By default this reuses or creates every installed peer among:
#   claude-*  -> claude
#   codex-*   -> codex
#   hermes-*  -> hermes --cli
#
# Override peers with FED_AGENTS=claude,codex or positional args:
#   fed_sessions.sh claude codex
#
# Set FEDERATE_UNSAFE=1 to use bypass/yolo peer commands in an external sandbox.
# Override launch commands with FED_CLAUDE_CMD, FED_CODEX_CMD, FED_HERMES_CMD.
# Prints FEDERATE_DIR=... plus <AGENT>_SESSION=... for the caller to consume.
set -euo pipefail

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

agent_cmd() {
  case "$1" in
    claude)
      if [ -n "${FED_CLAUDE_CMD:-}" ]; then echo "$FED_CLAUDE_CMD"
      elif [ "${FEDERATE_UNSAFE:-0}" = "1" ]; then echo "IS_SANDBOX=1 claude --dangerously-skip-permissions"
      else echo "claude"; fi ;;
    codex)
      if [ -n "${FED_CODEX_CMD:-}" ]; then echo "$FED_CODEX_CMD"
      elif [ "${FEDERATE_UNSAFE:-0}" = "1" ]; then echo "codex --dangerously-bypass-approvals-and-sandbox"
      else echo "codex"; fi ;;
    hermes)
      if [ -n "${FED_HERMES_CMD:-}" ]; then echo "$FED_HERMES_CMD"
      elif [ "${FEDERATE_UNSAFE:-0}" = "1" ]; then echo "hermes --cli --yolo"
      else echo "hermes --cli"; fi ;;
    *) return 1 ;;
  esac
}

agent_default_exe() {
  case "$1" in
    claude) echo "claude" ;;
    codex) echo "codex" ;;
    hermes) echo "hermes" ;;
    *) return 1 ;;
  esac
}

agent_has_override() {
  case "$1" in
    claude) [ -n "${FED_CLAUDE_CMD:-}" ] ;;
    codex) [ -n "${FED_CODEX_CMD:-}" ] ;;
    hermes) [ -n "${FED_HERMES_CMD:-}" ] ;;
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
  for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep "^${prefix}-" || true); do
    tag="$(tmux show-options -qv -t "$s" @federate_agent 2>/dev/null || true)"
    if [ "$tag" = "$prefix" ]; then
      echo "$s"
      return 0
    fi
  done
  if [ "${FED_REUSE_UNMANAGED:-0}" = "1" ]; then
    tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -m1 "^${prefix}-" || true
  fi
}

ensure_agent() {
  agent="$1"

  cmd="$(agent_cmd "$agent")" || {
    echo "SKIPPED unknown agent '$agent'" >&2
    return 0
  }

  existing="$(find_existing "$agent")"
  if [ -n "$existing" ]; then
    tmux resize-window -t "$existing" -x "$W" -y "$H" 2>/dev/null || true
    printf '%s_SESSION=%s\n' "$(printf '%s' "$agent" | tr '[:lower:]' '[:upper:]')" "$existing"
    return 0
  fi

  if ! agent_has_override "$agent"; then
    exe="$(agent_default_exe "$agent")"
    if ! command -v "$exe" >/dev/null 2>&1 && [ ! -x "$exe" ]; then
      echo "SKIPPED $agent: '$exe' not found or not executable" >&2
      return 0
    fi
  fi

  name=""
  for _attempt in 1 2 3 4 5; do
    candidate="$(next_name "$agent")"
    if tmux new-session -d -s "$candidate" -x "$W" -y "$H" 2>/dev/null; then
      name="$candidate"
      break
    fi
    sleep 0.1
  done
  [ -n "$name" ] || die "failed to create tmux session for $agent"
  tmux set-option -q -t "$name" @federate_agent "$agent" || true
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
printf 'FEDERATE_DIR=%q\n' "$SKILL_DIR"
seen_agents=" "
for agent in $agents; do
  case "$seen_agents" in
    *" $agent "*) continue ;;
  esac
  seen_agents="$seen_agents$agent "
  out="$(ensure_agent "$agent")" || exit $?
  if [ -n "$out" ]; then
    echo "$out"
    available_count=$((available_count + 1))
  fi
done

if [ "$available_count" -lt 2 ]; then
  die "federation needs at least two available peer sessions; got $available_count. Install/authenticate at least two of: claude, codex, hermes."
fi
