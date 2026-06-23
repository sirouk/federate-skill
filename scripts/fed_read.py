#!/usr/bin/env python3
"""fed_read.py — extract a tmux agent's VERBATIM answer from its transcript.

Clean source = the transcript JSONL, NEVER the garbled tmux scrollback.
  Claude: ~/.claude/projects/<encoded-cwd>/<uuid>.jsonl  (a turn = many text blocks; concatenate)
  Codex : ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl    (assistant blocks tagged payload.phase
            in {commentary, final_answer}; we return final_answer only — commentary is internal narration)
  Hermes: ${HERMES_HOME:-~/.hermes}/state.db               (SQLite messages table; profiles are searched too)

Disambiguate WHICH transcript + WHICH turn with the nonce fed_send injected ([[FED-…]]).
  --nonce is REQUIRED for a correct read. Without it the picker falls back to the most-recently
  modified transcript — which for Claude is normally the COORDINATOR's OWN session (same projects dir).
  A supplied-but-UNMATCHED nonce FAILS LOUD (agent has not replied yet) and never silently falls back.

Usage:
  fed_read.py claude --nonce FED-123-456
  fed_read.py codex  --nonce FED-123-456
  fed_read.py hermes --nonce FED-123-456
"""
import sys, os, json, glob, argparse, sqlite3
from pathlib import Path


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
        if content.startswith("\x00json:"):
            try:
                return text_of(json.loads(content[len("\x00json:"):]))
            except Exception:
                return content
        return content
    if isinstance(content, dict):
        if content.get("text"):
            return str(content.get("text"))
        if content.get("content"):
            return text_of(content.get("content"))
        return ""
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict)
            and (b.get("type") in ("text", "output_text", "input_text", None))
            and b.get("text")
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


# ---- Hermes state.db: rows = messages(id, session_id, role, content, active) ----
def hermes_state_paths():
    paths = []
    explicit = os.environ.get("FED_HERMES_STATE_DB")
    if explicit:
        paths.append(Path(explicit).expanduser())

    homes = []
    if os.environ.get("HERMES_HOME"):
        homes.append(Path(os.environ["HERMES_HOME"]).expanduser())
    homes.append(Path.home() / ".hermes")

    seen_homes = set()
    for home in homes:
        try:
            home = home.resolve()
        except Exception:
            pass
        if str(home) in seen_homes:
            continue
        seen_homes.add(str(home))
        paths.append(home / "state.db")
        paths.extend((home / "profiles").glob("*/state.db"))

    seen_paths = set()
    existing = []
    for p in paths:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if str(rp) in seen_paths or not p.exists():
            continue
        seen_paths.add(str(rp))
        existing.append(p)
    return sorted(existing, key=lambda p: p.stat().st_mtime, reverse=True)


def like_escape(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def hermes_query_turn(db_path, key=None):
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    try:
        anchor = None
        if key:
            anchor = con.execute(
                "SELECT id, session_id FROM messages "
                "WHERE role = 'user' AND COALESCE(content, '') LIKE ? ESCAPE '\\' "
                "ORDER BY id DESC LIMIT 1",
                (f"%{like_escape(key)}%",),
            ).fetchone()
            if not anchor:
                # Hermes stores multimodal/structured content as NUL-prefixed
                # JSON. SQLite LIKE does not reliably match past the NUL, so
                # decode user rows in Python as a correctness fallback.
                for row in con.execute(
                    "SELECT id, session_id, content FROM messages "
                    "WHERE role = 'user' ORDER BY id DESC"
                ):
                    if key in norm(text_of(row["content"])):
                        anchor = row
                        break
        else:
            anchor = con.execute(
                "SELECT id, session_id FROM messages "
                "WHERE role = 'user' AND COALESCE(content, '') != '' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not anchor:
            return None

        def rows_after(active=True):
            active_clause = "AND active = 1 " if active else ""
            return con.execute(
                "SELECT id, role, content FROM messages "
                "WHERE session_id = ? AND id > ? "
                f"{active_clause}ORDER BY id",
                (anchor["session_id"], anchor["id"]),
            ).fetchall()

        try:
            rows = rows_after(active=True)
        except sqlite3.OperationalError:
            rows = rows_after(active=False)

        parts = []
        for row in rows:
            role = row["role"]
            text = text_of(row["content"])
            if role == "user" and norm(text):
                break
            if role == "assistant" and text.strip():
                parts.append(text)
        return anchor["session_id"], "\n\n".join(parts)
    finally:
        con.close()


def hermes_read(key=None):
    paths = hermes_state_paths()
    if not paths:
        sys.stderr.write("ERROR: no Hermes state.db found under ${HERMES_HOME:-~/.hermes}\n")
        sys.exit(2)
    last_error = None
    for p in paths:
        try:
            found = hermes_query_turn(p, key)
        except sqlite3.Error as e:
            last_error = e
            continue
        if found:
            session_id, turn = found
            sys.stderr.write(f"[fed_read hermes] {p} session={session_id}\n")
            if not turn.strip():
                sys.stderr.write("[fed_read] WARNING: matched nonce but the turn is EMPTY — agent may still be working.\n")
            print(turn)
            return
    if key:
        detail = f" Last SQLite error: {last_error}" if last_error else ""
        sys.stderr.write(
            f"ERROR: nonce {key!r} NOT FOUND in any Hermes state.db — the agent has not replied yet "
            f"(or the send failed). Wait for fed_wait ALL_IDLE, then re-read.{detail}\n"
        )
        sys.exit(3)
    sys.stderr.write("[fed_read] WARNING: no --nonce and no Hermes user turn found.\n")
    print("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", choices=["claude", "codex", "hermes"])
    ap.add_argument("--nonce")
    ap.add_argument("--match-file")
    a = ap.parse_args()

    key = a.nonce
    if not key and a.match_file and os.path.exists(a.match_file):
        key = norm(open(a.match_file, errors="replace").read())[:80]

    if a.agent == "hermes":
        if not key:
            sys.stderr.write("[fed_read] WARNING: no --nonce; falling back to the most-recent Hermes user turn.\n")
        hermes_read(key)
        return

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
