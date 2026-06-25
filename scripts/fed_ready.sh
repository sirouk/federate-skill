#!/usr/bin/env bash
# fed_ready.sh <session> [<session>...] — drive peer panes to a live composer,
# clearing known startup interstitials so a round never silently hangs on one.
#
# The motivating case: a peer CLI boots into an "update available" menu (Codex
# shows `1. Update now / 2. Skip / 3. Skip until next version` with "Update now"
# preselected). From the coordinator's POV the composer never appears, so the
# loop just sits and stares — and a blind Enter would pick "Update now" and kick
# off an upgrade that hangs the pane. This preflight resolves that safely.
#
# Per session it polls the pane until one of:
#   READY      — a live composer is detected (stdout: `READY <session>`)
#   NOT_READY  — a blocking prompt could not be cleared, or it timed out
#                (stdout: `NOT_READY <session> agent=<a> reason=<r>`; rc=1)
#
# Codex update prompt handling (default ON; disable with FED_NO_AUTO_SKIP=1):
#   navigates the menu cursor DOWN onto a "Skip" line and only then presses
#   Enter. If a Skip line is never reached (unexpected menu), it presses nothing
#   and reports NOT_READY — it never risks selecting "Update now".
#
# Env:
#   FED_READY_TIMEOUT       per-session budget in seconds (default 60)
#   FED_READY_POLL          seconds between polls (default 2)
#   FED_READY_CAPTURE_LINES pane lines to inspect (default 60)
#   FED_NO_AUTO_SKIP=1      detect+report the Codex update prompt, don't touch it
#
# Exit 0 only if every session reached READY; otherwise exit 1.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: fed_ready.sh <session> [<session>...]" >&2; exit 2; }
command -v tmux >/dev/null 2>&1 || { echo "ERROR: tmux not found" >&2; exit 2; }

TIMEOUT="${FED_READY_TIMEOUT:-60}"
POLL="${FED_READY_POLL:-2}"
LINES="${FED_READY_CAPTURE_LINES:-60}"
case "$TIMEOUT" in ''|*[!0-9]*) TIMEOUT=60 ;; esac
case "$POLL" in ''|*[!0-9]*) POLL=2 ;; esac
case "$LINES" in ''|*[!0-9]*) LINES=60 ;; esac

agent_of() {
  tmux show-options -qv -t "$1" @federate_agent 2>/dev/null || true
}

capture() {
  tmux capture-pane -t "$1" -p -S "-$LINES" 2>/dev/null | tr -d '\r'
}

is_composer_ready() {
  # $1 = agent, stdin = pane text
  local agent="$1" pane; pane="$(cat)"
  case "$agent" in
    hermes) printf '%s' "$pane" | grep -qiE 'Welcome to Hermes|Type your message|/help for commands' && return 0 ;;
    claude) printf '%s' "$pane" | grep -qiE '\? for shortcuts|auto-accept|bypass(ing)? permissions|shift\+tab to cycle|esc to interrupt' && return 0 ;;
    codex)  printf '%s' "$pane" | grep -qiE 'Ctrl\+J|newline|to send|/help|esc to interrupt' && return 0 ;;
  esac
  # generic: a bare composer prompt line on any TUI
  printf '%s' "$pane" | grep -qE '^[[:space:]]*[❯▌][[:space:]]*$' && return 0
  return 1
}

is_codex_update_prompt() {
  # stdin = pane text. Signature: an update notice plus the menu.
  local pane; pane="$(cat)"
  printf '%s' "$pane" | grep -qiE 'Update available|Update now' || return 1
  printf '%s' "$pane" | grep -qiE 'Skip|Press enter to continue' || return 1
  return 0
}

other_blocker_reason() {
  # stdin = pane text -> echoes a reason if a known non-clearable prompt shows.
  local pane; pane="$(cat)"
  if printf '%s' "$pane" | grep -qiE 'sign in|sign-in|log ?in|authenticate|enter your (api )?key|paste your token'; then
    echo "looks like a login/auth prompt"; return 0
  fi
  if printf '%s' "$pane" | grep -qiE 'do you trust|trust this folder|trust the files|\(y/n\)|\[y/N\]'; then
    echo "looks like a trust/confirmation prompt"; return 0
  fi
  return 1
}

cursor_line() {
  # stdin = pane text -> the selected menu line (cursor markers: › ❯ >)
  grep -m1 -E '^[[:space:]]*[›❯>]' || true
}

# Navigate the Codex update menu onto a "Skip" line and press Enter there.
# Returns 0 if it pressed Enter on a Skip line, 1 otherwise (never touches
# "Update now"). Caller still re-verifies the composer afterward.
clear_codex_update() {
  local S="$1" i pane sel
  for i in $(seq 1 8); do
    pane="$(capture "$S")"
    is_codex_update_prompt <<<"$pane" || return 0   # menu already gone
    sel="$(cursor_line <<<"$pane")"
    if printf '%s' "$sel" | grep -qiE 'Skip'; then
      tmux send-keys -t "$S" Enter
      echo "  [$S] selected a Skip option (no update triggered)" >&2
      return 0
    fi
    # Cursor is on Update now / unknown line: move down, never press Enter here.
    tmux send-keys -t "$S" Down
    read -t 1 _ </dev/null 2>/dev/null || true
  done
  return 1
}

overall_rc=0

for S in "$@"; do
  if ! tmux has-session -t "$S" 2>/dev/null; then
    echo "NOT_READY $S agent=? reason=no such tmux session"
    echo "  [$S] no such tmux session" >&2
    overall_rc=1
    continue
  fi
  agent="$(agent_of "$S")"; [ -n "$agent" ] || agent="unknown"

  deadline=$(( $(date +%s) + TIMEOUT ))
  ready=0
  last_reason="still booting (no composer within ${TIMEOUT}s)"

  while [ "$(date +%s)" -lt "$deadline" ]; do
    pane="$(capture "$S")"

    if is_composer_ready "$agent" <<<"$pane"; then
      ready=1; break
    fi

    if is_codex_update_prompt <<<"$pane"; then
      if [ "${FED_NO_AUTO_SKIP:-0}" = "1" ]; then
        last_reason="codex update prompt (auto-skip disabled); run 'codex update' or dismiss it, then retry"
      else
        echo "  [$S] codex update prompt detected — clearing (selecting Skip, not Update)" >&2
        if clear_codex_update "$S"; then
          read -t "$POLL" _ </dev/null 2>/dev/null || true
          pane="$(capture "$S")"
          if is_composer_ready "$agent" <<<"$pane"; then ready=1; break; fi
          last_reason="cleared codex update prompt but composer not confirmed yet"
        else
          last_reason="codex update prompt could not be cleared safely (menu format unexpected); dismiss it manually, then retry"
        fi
      fi
    else
      if reason="$(other_blocker_reason <<<"$pane")"; then
        last_reason="$reason — needs manual action, then retry"
      fi
    fi

    read -t "$POLL" _ </dev/null 2>/dev/null || true
  done

  if [ "$ready" = 1 ]; then
    echo "READY $S"
    echo "  [$S] composer live (agent=$agent)" >&2
  else
    echo "NOT_READY $S agent=$agent reason=$last_reason"
    {
      echo "  [$S] NOT READY: $last_reason"
      echo "  --- last $LINES lines ---"
      capture "$S" | sed '/^[[:space:]]*$/d' | tail -8
    } >&2
    overall_rc=1
  fi
done

exit "$overall_rc"
