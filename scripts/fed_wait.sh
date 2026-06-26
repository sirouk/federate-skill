#!/usr/bin/env bash
# fed_wait.sh <session> [<session2> ...] — block until ALL given sessions are idle
# for 2 consecutive polls, then exit 0 (prints ALL_IDLE). Run via Bash run_in_background:true
# so the harness re-invokes you when it returns.
#
# Active-turn markers for Claude, Codex, and Hermes. Keep this default in sync
# with fed_sessions.sh and fed_ready.sh; override FED_BUSY_RE when an agent TUI
# changes or a specialized environment needs extra busy markers.
# NOTE: an agent that spawns its OWN background workflow can go pane-idle while still
# working — after this returns, re-read the transcript and confirm the answer actually
# arrived (changed from a "running…" placeholder) before trusting it.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: fed_wait.sh <session> [<session2> ...]" >&2; exit 2; }
command -v tmux >/dev/null 2>&1 || { echo "ERROR: tmux not found" >&2; exit 2; }
sessions=("$@")
busy_re="${FED_BUSY_RE:-esc to interrupt|Esc to int|ctrl-c to stop|Ctrl\\+C cancel|msg=interrupt|Working \\(}"

for s in "${sessions[@]}"; do
  tmux has-session -t "$s" 2>/dev/null || { echo "ERROR: no such tmux session: $s" >&2; exit 2; }
done

POLL="${FED_POLL:-10}"      # seconds between polls
MAXIT="${FED_MAXIT:-360}"   # ~1h default ceiling

idle=0
for ((i=1; i<=MAXIT; i++)); do
  sleep "$POLL"
  anybusy=0
  for s in "${sessions[@]}"; do
    pane="$(tmux capture-pane -J -t "$s" -p -S -4 2>/dev/null | tail -4)" || {
      echo "ERROR: failed to capture tmux session: $s" >&2
      exit 2
    }
    if printf '%s' "$pane" | grep -qiE "$busy_re"; then anybusy=1; fi
  done
  if [ "$anybusy" -eq 0 ]; then
    idle=$((idle+1))
    if [ "$idle" -ge 2 ]; then echo "ALL_IDLE after ~$((i*POLL))s"; exit 0; fi
  else
    idle=0
  fi
done
echo "TIMEOUT after ~$((MAXIT*POLL))s — still busy" >&2
exit 1
