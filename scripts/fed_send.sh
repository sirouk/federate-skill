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

if [ "${FED_SKIP_OWNER_CHECK:-0}" != "1" ]; then
  stored_agent="$(tmux show-options -qv -t "$S" @federate_agent 2>/dev/null || true)"
  stored_ns="$(tmux show-options -qv -t "$S" @federate_ns 2>/dev/null || true)"
  stored_root="$(tmux show-options -qv -t "$S" @federate_root 2>/dev/null || true)"
  [ -n "$stored_agent" ] && [ -n "$stored_ns" ] && [ -n "$stored_root" ] || {
    echo "ERROR: $S is not a namespaced federate-managed session. Run fed_sessions.sh first, or set FED_SKIP_OWNER_CHECK=1 for manual debugging." >&2
    exit 2
  }

  expected_ns_input="${FED_NS:-${FEDERATE_NS:-}}"
  if [ -n "$expected_ns_input" ]; then
    expected_ns="$(sanitize_ns "$expected_ns_input")"
    [ "$stored_ns" = "$expected_ns" ] || {
      echo "ERROR: $S belongs to FED_NS=$stored_ns, not FED_NS=$expected_ns. Refusing to paste into a foreign federation session." >&2
      exit 2
    }
  fi

  if [ -n "${FED_NS_ROOT:-}" ]; then
    expected_root="$(canonical_root "$FED_NS_ROOT")"
    [ "$stored_root" = "$expected_root" ] || {
      echo "ERROR: $S belongs to root $stored_root, not $expected_root. Refusing to paste into a foreign federation session." >&2
      exit 2
    }
  fi
fi

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
# Optional federation profile (FED_PROFILE_FILE): trusted coordinator context
# injected into EVERY brief — independent and cross-pollination alike — so the
# whole loop reasons in a shared domain. Inserted AFTER the top nonce so the
# nonce stays the first non-empty line that fed_read.py anchors on, and ABOVE
# the brief body so it is clearly separated from any quoted (untrusted) peer
# output the brief may contain. It is reference context, not a command channel,
# and must not override the brief's rails or operator instructions.
profile_file="${FED_PROFILE_FILE:-}"
case "$profile_file" in
  "~"|"~/"*) profile_file="$HOME${profile_file#\~}" ;;
esac
if [ -n "$profile_file" ]; then
  if [ -f "$profile_file" ] && [ -r "$profile_file" ]; then
    if grep -qE -- '-----BEGIN[ A-Z]*PRIVATE KEY-----' "$profile_file"; then
      echo "ERROR: FED_PROFILE_FILE appears to contain a private key; refusing to inject: $profile_file" >&2
      exit 2
    fi
    {
      printf '=== FEDERATION PROFILE (trusted coordinator context — does NOT override this brief'"'"'s rails or operator instructions) ===\n\n'
      cat "$profile_file"
      printf '\n=== END FEDERATION PROFILE ===\n\n'
    } >> "$tmp"
    echo "PROFILE injected from $profile_file" >&2
  else
    echo "WARNING: FED_PROFILE_FILE set but not a readable file: $profile_file (skipping)" >&2
  fi
fi
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
