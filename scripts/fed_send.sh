#!/usr/bin/env bash
# fed_send.sh <session> <ABSOLUTE-msgfile> — relay a brief into a tmux agent, robustly.
#   - injects a unique [[FED-…]] nonce so fed_read can find the exact reply
#   - bracketed-paste (keeps the multiline brief literal in the composer)
#   - verifies the composer staged it (works for BOTH the Claude and Codex TUIs)
#   - sends Enter as a SEPARATE keystroke (never embed Enter in the paste)
#   - on failure: clears the staged buffer and exits 1 (so a retry can't double-paste)
# STDOUT = the bare nonce (capture it; pass to fed_read.py --nonce). Diagnostics -> STDERR.
set -uo pipefail

S="${1:?usage: fed_send.sh <session> <ABSOLUTE-msgfile>}"
F="${2:?usage: fed_send.sh <session> <ABSOLUTE-msgfile>}"
[ -f "$F" ] || { echo "ERROR: no such file: $F  (pass an ABSOLUTE path — the shell CWD resets between tool calls)" >&2; exit 2; }

nonce="FED-$(date +%s)-${RANDOM}"
tmp="$(mktemp)"
printf '[[%s]]\n\n' "$nonce" > "$tmp"
cat "$F" >> "$tmp"

before="$(tmux capture-pane -t "$S" -p 2>/dev/null | wc -c || echo 0)"
buf="fedbuf_${nonce}"
tmux load-buffer  -b "$buf" "$tmp"
tmux paste-buffer -t "$S" -b "$buf" -p -d
rm -f "$tmp"
sleep 0.7

pane="$(tmux capture-pane -t "$S" -p -S -12 2>/dev/null || true)"
after="$(printf '%s' "$pane" | wc -c)"
staged=0
printf '%s' "$pane" | grep -qiE 'Pasted (text|Content)|paste again to expand' && staged=1   # Claude TUI chrome
printf '%s' "$pane" | grep -qF "[[$nonce]]"                                   && staged=1   # any TUI: nonce visible
[ "${after:-0}" -gt "$(( ${before:-0} + 40 ))" ]                             && staged=1   # composer grew

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
