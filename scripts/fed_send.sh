#!/usr/bin/env bash
# fed_send.sh <session> <ABSOLUTE-msgfile> — relay a brief into a tmux agent, robustly.
#   - injects a unique [[FED-…]] nonce so fed_read can find the exact reply
#   - bracketed-paste (keeps the multiline brief literal in the composer)
#   - verifies the composer staged it by TUI paste chrome or a trailing nonce marker
#   - sends Enter as a SEPARATE keystroke (never embed Enter in the paste)
#   - on failure: clears the staged buffer and exits 1 (so a retry can't double-paste)
# STDOUT = the bare nonce (capture it; pass to fed_read.py --nonce). Diagnostics -> STDERR.
set -euo pipefail

S="${1:?usage: fed_send.sh <session> <ABSOLUTE-msgfile>}"
F="${2:?usage: fed_send.sh <session> <ABSOLUTE-msgfile>}"
[ -f "$F" ] || { echo "ERROR: no such file: $F  (pass an ABSOLUTE path; the shell CWD resets between tool calls)" >&2; exit 2; }
case "$F" in
  /*) ;;
  *) echo "ERROR: msgfile must be an absolute path: $F" >&2; exit 2 ;;
esac
command -v tmux >/dev/null 2>&1 || { echo "ERROR: tmux not found" >&2; exit 2; }
tmux has-session -t "$S" 2>/dev/null || { echo "ERROR: no such tmux session: $S" >&2; exit 2; }

if command -v uuidgen >/dev/null 2>&1; then
  nonce="FED-$(uuidgen | tr '[:upper:]' '[:lower:]')"
elif [ -r /proc/sys/kernel/random/uuid ]; then
  nonce="FED-$(tr '[:upper:]' '[:lower:]' < /proc/sys/kernel/random/uuid)"
else
  nonce="FED-$(date +%s)-$$-${RANDOM}-${RANDOM}"
fi
tmp="$(mktemp)"
buf="fedbuf_${nonce}"
cleanup() {
  rm -f "$tmp"
  tmux delete-buffer -b "$buf" 2>/dev/null || true
}
trap cleanup EXIT

printf '[[%s]]\n\n' "$nonce" > "$tmp"
cat "$F" >> "$tmp"
printf '\n\n[[%s]]\n' "$nonce" >> "$tmp"

tmux load-buffer -b "$buf" "$tmp"
tmux paste-buffer -t "$S" -b "$buf" -p -d
sleep 0.7

capture_lines="${FED_SEND_CAPTURE_LINES:-200}"
case "$capture_lines" in
  ''|*[!0-9]*) capture_lines=200 ;;
esac
pane="$(tmux capture-pane -t "$S" -p -S "-$capture_lines" 2>/dev/null)"
staged=0
printf '%s' "$pane" | grep -qiE 'Pasted (text|Content)|paste again to expand' && staged=1   # Claude TUI chrome
printf '%s' "$pane" | grep -qF "[[$nonce]]"                                   && staged=1   # any TUI: nonce visible

if [ "$staged" -eq 1 ]; then
  tmux send-keys -t "$S" Enter
  echo "$nonce"                                  # STDOUT = bare nonce
  echo "SENT to $S (nonce $nonce)" >&2
else
  tmux send-keys -t "$S" C-u 2>/dev/null || true   # clear a staged-but-unsent buffer
  tmux send-keys -t "$S" Escape 2>/dev/null || true
  echo "ERROR: paste not detected in $S — Enter NOT sent, composer cleared. Session may be booting/busy; wait and retry." >&2
  exit 1
fi
