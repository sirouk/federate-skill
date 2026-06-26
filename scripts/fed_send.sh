#!/usr/bin/env bash
# fed_send.sh <session> <ABSOLUTE-msgfile> — relay a brief into a tmux agent, robustly.
#   - injects a unique [[FED-…]] nonce so fed_read can find the exact reply
#   - bracketed-paste (keeps the multiline brief literal in the composer)
#   - verifies the composer staged this exact prompt by seeing the fresh nonce marker
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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)"

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

profile_file="${FED_PROFILE_FILE:-}"
if [ -z "$profile_file" ] && [ "${FED_NO_DEFAULT_PROFILE:-0}" != "1" ]; then
  profile_file="$SKILL_DIR/profiles/llm_opa.min.txt"
fi
case "$profile_file" in
  "~") profile_file="$HOME" ;;
  "~/"*) profile_file="$HOME/${profile_file#~/}" ;;
esac

if [ -n "$profile_file" ]; then
  if [ "$profile_file" = "$SKILL_DIR/profiles/llm_opa.min.txt" ] && [ ! -f "$profile_file" ]; then
    echo "ERROR: managed default profile is missing: $profile_file; set FED_NO_DEFAULT_PROFILE=1 to bypass for debugging" >&2
    exit 2
  fi
  case "$profile_file" in
    /*) ;;
    *) echo "ERROR: FED_PROFILE_FILE must be an absolute path: $profile_file" >&2; exit 2 ;;
  esac
  [ -f "$profile_file" ] && [ -r "$profile_file" ] || {
    echo "ERROR: FED_PROFILE_FILE is not a readable file: $profile_file" >&2
    exit 2
  }
  if grep -qE -- '-----BEGIN[ A-Z]*PRIVATE KEY-----' "$profile_file"; then
    echo "ERROR: FED_PROFILE_FILE appears to contain a private key; refusing to inject: $profile_file" >&2
    exit 2
  fi
fi

printf '[[%s]]\n' "$nonce" > "$tmp"
if [ -n "$profile_file" ]; then
  {
    printf "=== FEDERATION PROFILE (trusted coordinator context; does not override this brief's rails or operator instructions) ===\n"
    cat "$profile_file"
    printf '\n=== END FEDERATION PROFILE ===\n\n'
  } >> "$tmp"
  echo "PROFILE injected from $profile_file" >&2
fi
cat "$F" >> "$tmp"
printf '\n[[%s]]\n' "$nonce" >> "$tmp"

tmux load-buffer -b "$buf" "$tmp"
tmux paste-buffer -t "$S" -b "$buf" -p -d

capture_lines="${FED_SEND_CAPTURE_LINES:-200}"
case "$capture_lines" in
  ''|*[!0-9]*) capture_lines=200 ;;
esac
payload_lines="$(wc -l < "$tmp" | tr -d '[:space:]')"
payload_bytes="$(wc -c < "$tmp" | tr -d '[:space:]')"
case "$payload_lines" in ''|*[!0-9]*) payload_lines=0 ;; esac
case "$payload_bytes" in ''|*[!0-9]*) payload_bytes=0 ;; esac
# Pane capture counts visual rows, not just logical prompt lines. The byte term
# gives wrapped long lines room while keeping compact prompts at the old default.
min_capture_lines=$((payload_lines + (payload_bytes / 80) + 20))
if [ "$capture_lines" -lt "$min_capture_lines" ]; then
  capture_lines="$min_capture_lines"
fi
verify_polls="${FED_SEND_VERIFY_POLLS:-20}"
case "$verify_polls" in
  ''|*[!0-9]*) verify_polls=20 ;;
esac
staged=0
marker="[[$nonce]]"
for ((i=1; i<=verify_polls; i++)); do
  pane="$(tmux capture-pane -J -t "$S" -p -S "-$capture_lines" 2>/dev/null || true)"
  marker_count="$( (printf '%s' "$pane" | grep -oF "$marker" || true) | wc -l | tr -d '[:space:]')"
  if [ "${marker_count:-0}" -ge 2 ] || printf '%s' "$pane" | grep -qiE 'Pasted (text|Content)|paste again to expand'; then
    staged=1
    break
  fi
  sleep 0.25
done

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
