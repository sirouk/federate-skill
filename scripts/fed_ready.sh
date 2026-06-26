#!/usr/bin/env bash
# fed_ready.sh <session> [<session>...] — drive managed peer panes to a live
# composer before a round starts, clearing only known-safe startup prompts.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: fed_ready.sh <session> [<session>...]" >&2; exit 2; }
command -v tmux >/dev/null 2>&1 || { echo "ERROR: tmux not found" >&2; exit 2; }

TIMEOUT="${FED_READY_TIMEOUT:-60}"
POLL="${FED_READY_POLL:-2}"
LINES="${FED_READY_CAPTURE_LINES:-60}"
BUSY_RE="${FED_BUSY_RE:-esc to interrupt|Esc to int|ctrl-c to stop|Ctrl\\+C cancel|msg=interrupt|Working \\(}"

case "$TIMEOUT" in ''|*[!0-9]*) TIMEOUT=60 ;; esac
case "$POLL" in ''|*[!0-9]*) POLL=2 ;; esac
case "$LINES" in ''|*[!0-9]*) LINES=60 ;; esac
[ "$POLL" -ge 1 ] || POLL=1

sanitize_ns() {
  ns="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g' | cut -c1-48)"
  if [ -n "$ns" ]; then
    printf '%s\n' "$ns"
  else
    printf 'fed\n'
  fi
}

canonical_root() {
  (cd "$1" 2>/dev/null && pwd -P) || printf '%s\n' "$1"
}

tmux_opt() {
  tmux show-options -qv -t "$1" "$2" 2>/dev/null || true
}

capture() {
  tmux capture-pane -J -t "$1" -p -S "-$LINES" 2>/dev/null | tr -d '\r'
}

bottom() {
  tail -n "${1:-20}"
}

selected_line() {
  grep -m1 -E '^[[:space:]]*[›❯>]' || true
}

plain_skip_selected() {
  grep -qiE '^[[:space:]]*[›❯>][[:space:]]*([0-9]+[.)][[:space:]]*)?Skip[[:space:]]*$'
}

update_now_selected() {
  grep -qiE '^[[:space:]]*[›❯>].*Update now'
}

active_codex_update_prompt() {
  local pane current sel
  pane="$(cat)"
  current="$(printf '%s\n' "$pane" | bottom 25)"
  printf '%s' "$current" | grep -qiE 'Update available|Update now' || return 1
  printf '%s' "$current" | grep -qi 'Press enter to continue' || return 1
  printf '%s' "$current" | grep -qiE '^[[:space:]]*([›❯>][[:space:]]*)?([0-9]+[.)][[:space:]]*)?Skip([[:space:]]|$)' || return 1
  sel="$(printf '%s\n' "$current" | selected_line)"
  [ -n "$sel" ] || return 1
  return 0
}

pane_busy() {
  local pane current
  pane="$(cat)"
  current="$(printf '%s\n' "$pane" | bottom 4)"
  printf '%s' "$current" | grep -qiE "$BUSY_RE"
}

composer_ready() {
  local agent pane current
  agent="$1"
  pane="$(cat)"
  current="$(printf '%s\n' "$pane" | bottom 25)"
  case "$agent" in
    hermes)
      printf '%s' "$current" | grep -qiE 'Welcome to Hermes|Type your message|/help for commands' && return 0
      ;;
    claude)
      printf '%s' "$current" | grep -qiE '\? for shortcuts|auto-accept|bypass(ing)? permissions|shift\+tab to cycle' && return 0
      ;;
    codex)
      printf '%s' "$current" | grep -qiE 'Ctrl\+J|newline|to send|/help' && return 0
      if printf '%s\n' "$current" | grep -qE '^[[:space:]]*[›❯>][[:space:]]+.+' &&
        ! printf '%s' "$current" | grep -qi 'Update now'; then
        return 0
      fi
      ;;
  esac
  printf '%s\n' "$current" | grep -qE '^[[:space:]]*([[:alnum:]_.:/~@ -]+[[:space:]])?[›❯>][[:space:]]*$'
}

known_blocker() {
  local pane current
  pane="$(cat)"
  current="$(printf '%s\n' "$pane" | bottom 25)"
  if printf '%s' "$current" | grep -qiE 'sign in|sign-in|log ?in|authenticate|enter your (api )?key|paste your token'; then
    echo "auth prompt needs manual action"
    return 0
  fi
  if printf '%s' "$current" | grep -qiE 'do you trust|trust this folder|trust the files|\(y/n\)|\[y/N\]'; then
    echo "trust/confirmation prompt needs manual action"
    return 0
  fi
  return 1
}

clear_codex_update() {
  local session pane current sel
  session="$1"

  pane="$(capture "$session")"
  active_codex_update_prompt <<<"$pane" || return 1
  current="$(printf '%s\n' "$pane" | bottom 25)"
  sel="$(printf '%s\n' "$current" | selected_line)"

  if printf '%s\n' "$sel" | plain_skip_selected; then
    tmux send-keys -t "$session" Enter
    echo "  [$session] selected plain Skip" >&2
    return 0
  fi

  if ! printf '%s\n' "$sel" | update_now_selected; then
    return 1
  fi

  tmux send-keys -t "$session" Down
  sleep 1
  pane="$(capture "$session")"
  active_codex_update_prompt <<<"$pane" || return 1
  current="$(printf '%s\n' "$pane" | bottom 25)"
  sel="$(printf '%s\n' "$current" | selected_line)"
  if printf '%s\n' "$sel" | plain_skip_selected; then
    tmux send-keys -t "$session" Enter
    echo "  [$session] selected plain Skip" >&2
    return 0
  fi
  return 1
}

owner_reason() {
  local session stored_agent stored_ns stored_root expected_ns_input expected_ns expected_root
  session="$1"
  stored_agent="$(tmux_opt "$session" @federate_agent)"
  stored_ns="$(tmux_opt "$session" @federate_ns)"
  stored_root="$(tmux_opt "$session" @federate_root)"

  [ -n "$stored_agent" ] && [ -n "$stored_ns" ] && [ -n "$stored_root" ] || {
    echo "unmanaged session; run fed_sessions.sh first"
    return 0
  }

  expected_ns_input="${FED_NS:-${FEDERATE_NS:-}}"
  if [ -n "$expected_ns_input" ]; then
    expected_ns="$(sanitize_ns "$expected_ns_input")"
    [ "$stored_ns" = "$expected_ns" ] || {
      echo "foreign namespace $stored_ns"
      return 0
    }
  fi

  if [ -n "${FED_NS_ROOT:-}" ]; then
    expected_root="$(canonical_root "$FED_NS_ROOT")"
    [ "$stored_root" = "$expected_root" ] || {
      echo "foreign root $stored_root"
      return 0
    }
  fi

  return 1
}

debug_tail() {
  [ "${FED_READY_DEBUG:-0}" = "1" ] || return 0
  {
    echo "  [$1] debug tail:"
    capture "$1" | sed '/^[[:space:]]*$/d' | tail -8
  } >&2
}

overall_rc=0

for session in "$@"; do
  if ! tmux has-session -t "$session" 2>/dev/null; then
    echo "NOT_READY $session agent=? reason=no such tmux session"
    overall_rc=1
    continue
  fi

  agent="$(tmux_opt "$session" @federate_agent)"
  [ -n "$agent" ] || agent="unknown"

  if [ "${FED_SKIP_OWNER_CHECK:-0}" != "1" ]; then
    if reason="$(owner_reason "$session")"; then
      echo "NOT_READY $session agent=$agent reason=$reason"
      overall_rc=1
      continue
    fi
  fi

  deadline=$(( $(date +%s) + TIMEOUT ))
  ready=0
  last_reason="composer not detected within ${TIMEOUT}s"

  while [ "$(date +%s)" -lt "$deadline" ]; do
    pane="$(capture "$session")"

    if active_codex_update_prompt <<<"$pane"; then
      if [ "$agent" != "codex" ]; then
        last_reason="codex update prompt seen in non-codex session"
        break
      fi
      if [ "${FED_NO_AUTO_SKIP:-0}" = "1" ]; then
        last_reason="codex update prompt; auto-skip disabled"
        break
      fi
      if clear_codex_update "$session"; then
        pane="$(capture "$session")"
        if reason="$(known_blocker <<<"$pane")"; then
          last_reason="$reason"
          break
        fi
        if ! active_codex_update_prompt <<<"$pane" && ! pane_busy <<<"$pane" && composer_ready "$agent" <<<"$pane"; then
          ready=1
          break
        fi
        sleep "$POLL"
        continue
      fi
      last_reason="codex update prompt could not be cleared safely"
      break
    fi

    if pane_busy <<<"$pane"; then
      last_reason="pane appears busy"
      break
    fi

    if reason="$(known_blocker <<<"$pane")"; then
      last_reason="$reason"
      break
    fi

    if composer_ready "$agent" <<<"$pane"; then
      ready=1
      break
    fi

    sleep "$POLL"
  done

  if [ "$ready" -eq 1 ]; then
    echo "READY $session"
  else
    echo "NOT_READY $session agent=$agent reason=$last_reason"
    debug_tail "$session"
    overall_rc=1
  fi
done

exit "$overall_rc"
