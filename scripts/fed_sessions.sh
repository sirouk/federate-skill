#!/usr/bin/env bash
# fed_sessions.sh — ensure a claude-* and a codex-* tmux session exist.
# Reuses any existing one; otherwise creates claude-0 / codex-0 with WIDE panes
# (wide panes avoid the "esc to interrupt" -> "esc to int…" truncation gotcha).
# Prints CLAUDE_SESSION=… and CODEX_SESSION=… for the caller to consume.
set -uo pipefail

W=230; H=50

claude_s="$(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -m1 '^claude-' || true)"
codex_s="$(tmux list-sessions  -F '#{session_name}' 2>/dev/null | grep -m1 '^codex-'  || true)"

if [ -z "$claude_s" ]; then
  tmux new-session -d -s claude-0 -x "$W" -y "$H"
  tmux send-keys -t claude-0 'IS_SANDBOX=1 claude --dangerously-skip-permissions' Enter
  claude_s="claude-0"
  echo "CREATED claude-0 (booting — wait for idle before first send)" >&2
fi

if [ -z "$codex_s" ]; then
  tmux new-session -d -s codex-0 -x "$W" -y "$H"
  tmux send-keys -t codex-0 'codex --dangerously-bypass-approvals-and-sandbox' Enter
  codex_s="codex-0"
  echo "CREATED codex-0 (booting — wait for idle before first send)" >&2
fi

# widen existing panes too (best-effort; reduces truncation)
tmux resize-window -t "$claude_s" -x "$W" -y "$H" 2>/dev/null || true
tmux resize-window -t "$codex_s"  -x "$W" -y "$H" 2>/dev/null || true

echo "CLAUDE_SESSION=$claude_s"
echo "CODEX_SESSION=$codex_s"
