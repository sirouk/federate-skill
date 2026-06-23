#!/usr/bin/env bash
# fed_wait.sh <session> [<session2> ...] — block until ALL given sessions are idle
# for 2 consecutive polls, then exit 0 (prints ALL_IDLE). Run via Bash run_in_background:true
# so the harness re-invokes you when it returns.
#
# Robust busy markers for Claude, Codex, and Hermes (incl. narrow-pane truncation):
#   esc to int   |  Working (  |  thinking with  |  to interrupt
#   background terminal runni
# NOTE: an agent that spawns its OWN background workflow can go pane-idle while still
# working — after this returns, re-read the transcript and confirm the answer actually
# arrived (changed from a "running…" placeholder) before trusting it.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: fed_wait.sh <session> [<session2> ...]" >&2; exit 2; }
command -v tmux >/dev/null 2>&1 || { echo "ERROR: tmux not found" >&2; exit 2; }
sessions=("$@")
busy_re='esc to int|Esc to int|to interrupt|Working \(|thinking with|background terminal runni'

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
    pane="$(tmux capture-pane -t "$s" -p -S -6 2>/dev/null)" || {
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
