#!/usr/bin/env bash
# fed_sessions.sh — ensure tmux peer-agent sessions exist.
#
# By default this reuses or creates namespaced peer sessions among:
#   fed-<ns>-claude-*  -> IS_SANDBOX=1 claude --dangerously-skip-permissions
#   fed-<ns>-codex-*   -> codex --dangerously-bypass-approvals-and-sandbox
#   fed-<ns>-hermes-*  -> hermes --cli --yolo
#
# Override peers with FED_AGENTS=claude,codex or positional args:
#   fed_sessions.sh claude codex
#
# Set FED_NS for thread/federation isolation. Without it, the script falls back
# to a stable project namespace for manual use.
#
# Override launch commands with FED_CLAUDE_CMD, FED_CODEX_CMD, FED_HERMES_CMD.
# Prints FEDERATE_DIR=..., FED_NS=..., FED_NS_ROOT=..., plus <AGENT>_SESSION=....
set -euo pipefail

W="${FED_TMUX_WIDTH:-230}"
H="${FED_TMUX_HEIGHT:-50}"
FED_NS_INPUT="${FED_NS:-${FEDERATE_NS:-}}"
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

hash8() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print substr($1, 1, 8)}'
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | awk '{print substr($1, 1, 8)}'
  else
    printf '%s' "$1" | cksum | awk '{printf "%08x", $1}'
  fi
}

sanitize_ns() {
  ns="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g' | cut -c1-48)"
  if [ -n "$ns" ]; then
    printf '%s\n' "$ns"
  else
    printf 'fed\n'
  fi
}

resolve_root() {
  if [ -n "${FED_NS_ROOT:-}" ]; then
    (cd "$FED_NS_ROOT" 2>/dev/null && pwd -P) || printf '%s\n' "$FED_NS_ROOT"
    return
  fi
  if command -v git >/dev/null 2>&1; then
    root="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
    if [ -n "$root" ]; then
      (cd "$root" 2>/dev/null && pwd -P) || printf '%s\n' "$root"
      return
    fi
  fi
  pwd -P
}

ROOT="$(resolve_root)"
ROOT_HASH="$(hash8 "$ROOT")"
if [ -n "$FED_NS_INPUT" ]; then
  NS="$(sanitize_ns "$FED_NS_INPUT")"
  NS_EXPLICIT=1
else
  root_base="$(basename "$ROOT")"
  NS="$(sanitize_ns "${root_base}-${ROOT_HASH}")"
  NS_EXPLICIT=0
  echo "WARN: FED_NS not set; using project-scoped namespace '$NS'. Set FED_NS for thread-isolated federation." >&2
fi

csv_to_words() {
  printf '%s' "$1" | tr ',' ' '
}

agent_cmd() {
  case "$1" in
    claude)
      if [ -n "${FED_CLAUDE_CMD:-}" ]; then echo "$FED_CLAUDE_CMD"
      else echo "IS_SANDBOX=1 claude --dangerously-skip-permissions"; fi ;;
    codex)
      if [ -n "${FED_CODEX_CMD:-}" ]; then echo "$FED_CODEX_CMD"
      else echo "codex --dangerously-bypass-approvals-and-sandbox"; fi ;;
    hermes)
      if [ -n "${FED_HERMES_CMD:-}" ]; then echo "$FED_HERMES_CMD"
      else echo "hermes --cli --yolo"; fi ;;
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

session_attached() {
  attached="$(tmux display-message -p -t "$1" '#{session_attached}' 2>/dev/null || echo 0)"
  case "$attached" in
    ''|*[!0-9]*) attached=0 ;;
  esac
  [ "$attached" -gt 0 ]
}

session_busy() {
  pane="$(tmux capture-pane -t "$1" -p -S -8 2>/dev/null || true)"
  printf '%s' "$pane" | grep -qiE 'esc to interrupt|ctrl-c to stop|running|thinking|working|executing|processing|waiting for|tool use|bash|python|npm|pnpm|cargo|pytest|pytest|uv run'
}

allow_session_reuse() {
  session="$1"
  source="$2"
  if session_attached "$session" && [ "${FED_REUSE_ATTACHED:-0}" != "1" ]; then
    echo "SKIPPED $session: $source session is attached; set FED_REUSE_ATTACHED=1 to adopt it" >&2
    return 1
  fi
  if session_busy "$session" && [ "${FED_REUSE_BUSY:-0}" != "1" ]; then
    echo "SKIPPED $session: $source session appears busy; set FED_REUSE_BUSY=1 to adopt it" >&2
    return 1
  fi
  return 0
}

warn_reused_state() {
  session="$1"
  notes=""
  if session_attached "$session"; then notes="$notes attached"; fi
  if session_busy "$session"; then notes="$notes busy"; fi
  if [ -n "$notes" ]; then
    echo "REUSED $session (${notes# }); verify it is the intended peer before sending" >&2
  fi
}

tag_session() {
  session="$1"
  agent="$2"
  cmd="$3"
  tmux set-option -q -t "$session" @federate_agent "$agent" || true
  tmux set-option -q -t "$session" @federate_cmd "$cmd" || true
  tmux set-option -q -t "$session" @federate_ns "$NS" || true
  tmux set-option -q -t "$session" @federate_root "$ROOT" || true
}

find_existing() {
  agent="$1"
  expected_cmd="$2"
  prefix="fed-${NS}-${agent}"
  for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep "^${prefix}-" || true); do
    tag="$(tmux show-options -qv -t "$s" @federate_agent 2>/dev/null || true)"
    stored_ns="$(tmux show-options -qv -t "$s" @federate_ns 2>/dev/null || true)"
    stored_root="$(tmux show-options -qv -t "$s" @federate_root 2>/dev/null || true)"
    stored_cmd="$(tmux show-options -qv -t "$s" @federate_cmd 2>/dev/null || true)"
    [ "$tag" = "$agent" ] || continue
    [ "$stored_ns" = "$NS" ] || continue
    if [ "$stored_root" != "$ROOT" ] && [ "${FED_REUSE_FOREIGN_ROOT:-0}" != "1" ]; then
      if [ "$NS_EXPLICIT" -eq 1 ]; then
        die "namespace '$NS' is already bound to root '$stored_root' for $s; current root is '$ROOT'. Choose another FED_NS or set FED_REUSE_FOREIGN_ROOT=1."
      fi
      echo "IGNORED $s: managed session root changed; creating a fresh $agent session" >&2
      continue
    fi
    if [ "$stored_cmd" = "$expected_cmd" ]; then
      warn_reused_state "$s"
      echo "$s"
      return 0
    fi
    echo "IGNORED $s: managed session command changed; creating a fresh $agent session" >&2
  done

  if [ "${FED_REUSE_LEGACY:-0}" = "1" ]; then
    for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep "^${agent}-" || true); do
      tag="$(tmux show-options -qv -t "$s" @federate_agent 2>/dev/null || true)"
      stored_ns="$(tmux show-options -qv -t "$s" @federate_ns 2>/dev/null || true)"
      stored_cmd="$(tmux show-options -qv -t "$s" @federate_cmd 2>/dev/null || true)"
      [ "$tag" = "$agent" ] || continue
      [ -z "$stored_ns" ] || continue
      [ -z "$stored_cmd" ] || [ "$stored_cmd" = "$expected_cmd" ] || continue
      allow_session_reuse "$s" "legacy managed" || continue
      tag_session "$s" "$agent" "$expected_cmd"
      echo "ADOPTED legacy managed session $s into namespace $NS" >&2
      echo "$s"
      return 0
    done
  fi

  if [ "${FED_REUSE_UNMANAGED:-0}" = "1" ]; then
    for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep "^${agent}-" || true); do
      tag="$(tmux show-options -qv -t "$s" @federate_agent 2>/dev/null || true)"
      [ -z "$tag" ] || continue
      allow_session_reuse "$s" "unmanaged" || continue
      tag_session "$s" "$agent" "$expected_cmd"
      echo "ADOPTED unmanaged session $s into namespace $NS" >&2
      echo "$s"
      return 0
    done
  fi
}

ensure_agent() {
  agent="$1"

  cmd="$(agent_cmd "$agent")" || {
    echo "SKIPPED unknown agent '$agent'" >&2
    return 0
  }

  existing="$(find_existing "$agent" "$cmd")"
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
  prefix="fed-${NS}-${agent}"
  for _attempt in 1 2 3 4 5; do
    candidate="$(next_name "$prefix")"
    if tmux new-session -d -s "$candidate" -x "$W" -y "$H" -c "$ROOT" 2>/dev/null; then
      name="$candidate"
      break
    fi
    sleep 0.1
  done
  [ -n "$name" ] || die "failed to create tmux session for $agent"
  tag_session "$name" "$agent" "$cmd"
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
printf 'FED_NS=%q\n' "$NS"
printf 'FED_NS_ROOT=%q\n' "$ROOT"
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
