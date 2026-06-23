#!/usr/bin/env python3
"""fed_read.py — extract a tmux agent's VERBATIM answer from its transcript.

Clean source = the transcript JSONL, NEVER the garbled tmux scrollback.
  Claude: ~/.claude/projects/<encoded-cwd>/<uuid>.jsonl  (a turn = many text blocks; concatenate)
  Codex : ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl    (assistant blocks tagged payload.phase
            in {commentary, final_answer}; we return final_answer only — commentary is internal narration)

Disambiguate WHICH transcript + WHICH turn with the nonce fed_send injected ([[FED-…]]).
  --nonce is REQUIRED for a correct read. Without it the picker falls back to the most-recently
  modified transcript — which for Claude is normally the COORDINATOR's OWN session (same projects dir).
  A supplied-but-UNMATCHED nonce FAILS LOUD (agent has not replied yet) and never silently falls back.

Usage:
  fed_read.py claude --nonce FED-123-456
  fed_read.py codex  --nonce FED-123-456
"""
import sys, os, json, glob, argparse


def load(path):
    rows = []
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") in ("text", "output_text", "input_text") and b.get("text")
        )
    return ""


def norm(s):
    return " ".join((s or "").split())


# ---- Claude transcript: units = (idx, role, text) ----
def c_role(o):
    return (o.get("message") or {}).get("role") or o.get("type")

def claude_units(rows):
    out = []
    for i, o in enumerate(rows):
        r = c_role(o)
        if r in ("user", "assistant"):
            out.append((i, r, text_of((o.get("message") or {}).get("content"))))
    return out

def claude_turn(units, j):
    # all assistant text after anchor j; stop at the NEXT real (non-empty) user message.
    # tool-result user rows have empty text -> they do NOT terminate the turn.
    parts = []
    for k in range(j + 1, len(units)):
        _, role, t = units[k]
        if role == "user" and norm(t):
            break
        if role == "assistant" and t.strip():
            parts.append(t)
    return "\n\n".join(parts)


# ---- Codex rollout: units = (role, text, phase) ----
def codex_units(rows):
    out = []
    for o in rows:
        if o.get("type") == "response_item":
            p = o.get("payload", {})
            if isinstance(p, dict) and p.get("role") in ("user", "assistant"):
                out.append((p.get("role"), text_of(p.get("content")), p.get("phase")))
    return out

def codex_turn(units, j):
    asst = []
    for k in range(j + 1, len(units)):
        role, t, phase = units[k]
        if role == "user" and norm(t):
            break
        if role == "assistant" and t.strip():
            asst.append((t, phase))
    finals = [t for t, ph in asst if ph == "final_answer"]
    if finals:
        return "\n\n".join(finals)
    if any(ph for _, ph in asst):     # phases present but no final_answer yet = still narrating
        return "\n\n".join(t for t, _ in asst)
    return asst[-1][0] if asst else ""  # legacy rollout (no phase tags): last assistant item


def role_text(units, k, agent):
    return (units[k][1], units[k][2]) if agent == "claude" else (units[k][0], units[k][1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", choices=["claude", "codex"])
    ap.add_argument("--nonce")
    ap.add_argument("--match-file")
    a = ap.parse_args()

    key = a.nonce
    if not key and a.match_file and os.path.exists(a.match_file):
        key = norm(open(a.match_file, errors="replace").read())[:80]

    if a.agent == "claude":
        paths = sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")), key=os.path.getmtime, reverse=True)
    else:
        paths = sorted(glob.glob(os.path.expanduser("~/.codex/sessions/**/rollout-*.jsonl"), recursive=True), key=os.path.getmtime, reverse=True)
    if not paths:
        sys.stderr.write(f"ERROR: no {a.agent} transcript found\n"); sys.exit(2)

    units_of = claude_units if a.agent == "claude" else codex_units
    turn_of = claude_turn if a.agent == "claude" else codex_turn

    if key:
        for p in paths:
            units = units_of(load(p))
            # latest user message matching the nonce
            j = None
            for k in range(len(units) - 1, -1, -1):
                role, t = role_text(units, k, a.agent)
                if role == "user" and key in norm(t):
                    j = k; break
            if j is not None:
                sys.stderr.write(f"[fed_read {a.agent}] {p}\n")
                turn = turn_of(units, j)
                if not turn.strip():
                    sys.stderr.write("[fed_read] WARNING: matched nonce but the turn is EMPTY — agent may still be working.\n")
                print(turn); return
        sys.stderr.write(
            f"ERROR: nonce {key!r} NOT FOUND in any {a.agent} transcript — the agent has not replied yet "
            f"(or the send failed). Refusing to fall back to most-recent (would read the wrong / coordinator's own "
            f"transcript). Wait for fed_wait ALL_IDLE, then re-read.\n"
        )
        sys.exit(3)

    # No key: DISCOURAGED fallback (for claude this is usually the coordinator's OWN session).
    sys.stderr.write("[fed_read] WARNING: no --nonce; falling back to most-recent transcript. Pass the nonce fed_send printed.\n")
    units = units_of(load(paths[0]))
    j = None
    for k in range(len(units) - 1, -1, -1):
        role, t = role_text(units, k, a.agent)
        if role == "user" and norm(t):
            j = k; break
    sys.stderr.write(f"[fed_read {a.agent}] {paths[0]}\n")
    print(turn_of(units, j) if j is not None else "")


if __name__ == "__main__":
    main()
