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
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import urllib.parse
from pathlib import Path


class ExtractError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def abs_path(path):
    return os.path.abspath(os.path.expanduser(str(path)))


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


def validate_nonce(key):
    return bool(re.fullmatch(r"FED-[A-Za-z0-9][A-Za-z0-9_.:-]{8,}", key or ""))


def nonce_marker(key):
    return f"[[{key}]]"


def has_nonce_marker(text, key):
    marker = nonce_marker(key)
    nonempty = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        nonempty.append(stripped)
    return len(nonempty) >= 2 and nonempty[0] == marker and nonempty[-1] == marker


def canonical_window_sha256(agent, nonce, rows):
    canonical = json.dumps(
        {"agent": agent, "nonce": nonce or "", "rows": rows},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return sha256_bytes(canonical.encode("utf-8"))


NO_TOOL_AUDIT_LINE = "NO_TOOL_AUDIT: no tools used"
TOOL_EVENT_TYPES = {
    "tool_use",
    "tool_result",
    "tool_call",
    "function_call",
    "function_call_output",
    "computer_call",
    "web_search_call",
    "local_shell_call",
}


def first_nonempty_line(text):
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def has_structured_tool_event(value):
    if isinstance(value, str) and value.startswith("\x00json:"):
        try:
            return has_structured_tool_event(json.loads(value[len("\x00json:"):]))
        except Exception:
            return False
    if isinstance(value, dict):
        typ = value.get("type")
        if isinstance(typ, str) and typ in TOOL_EVENT_TYPES:
            return True
        role = value.get("role")
        if isinstance(role, str) and role in ("tool", "tool_call"):
            return True
        if "tool_use_id" in value or "tool_call_id" in value:
            return True
        return any(has_structured_tool_event(v) for v in value.values())
    if isinstance(value, list):
        return any(has_structured_tool_event(v) for v in value)
    return False


def raw_window_from_units(rows, units, j):
    # Slice the original JSONL rows, not just parser units, so structured
    # tool/function-call rows filtered out of normal reply extraction still
    # remain visible to --no-tool-window.
    start = units[j][0]
    end = len(rows)
    for k in range(j + 1, len(units)):
        role, t = role_text(units, k, "claude")
        if role == "user" and norm(t):
            end = units[k][0]
            break
    return rows[start:end]


def require_no_tool_window(result):
    events = result.get("tool_events") or []
    if events:
        sample = ", ".join(events[:3])
        raise ExtractError(5, f"[fed_read] ERROR: structured tool event in nonce window: {sample}\n")


def require_no_tool_audit(result):
    got = first_nonempty_line(result.get("reply", ""))
    if got != NO_TOOL_AUDIT_LINE:
        raise ExtractError(
            5,
            f"[fed_read] ERROR: cross reply missing first-line {NO_TOOL_AUDIT_LINE!r}\n",
        )


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
    for i, o in enumerate(rows):
        if o.get("type") == "response_item":
            p = o.get("payload", {})
            if isinstance(p, dict) and p.get("role") in ("user", "assistant"):
                out.append((i, p.get("role"), text_of(p.get("content")), p.get("phase")))
    return out


def codex_turn(units, j):
    asst = []
    for k in range(j + 1, len(units)):
        _, role, t, phase = units[k]
        if role == "user" and norm(t):
            break
        if role == "assistant" and t.strip():
            asst.append((t, phase))
    finals = [t for t, ph in asst if ph in ("final_answer", "final")]
    if finals:
        return "\n\n".join(finals)
    if any(ph for _, ph in asst):     # phases present but no final_answer yet = still narrating
        return ""
    return asst[-1][0] if asst else ""  # legacy rollout (no phase tags): last assistant item


def role_text(units, k, agent):
    return (units[k][1], units[k][2]) if agent == "claude" else (units[k][1], units[k][2])


def window_rows_from_units(units, j, agent):
    rows = []
    for k in range(j, len(units)):
        role, t = role_text(units, k, agent)
        if k > j and role == "user" and norm(t):
            break
        rows.append({"role": role, "text": t})
    return rows


def jsonl_paths(agent, source_path=None):
    if source_path:
        p = Path(source_path).expanduser()
        if not p.exists():
            raise ExtractError(2, f"ERROR: source not found: {source_path}\n")
        return [abs_path(p)]
    if agent == "claude":
        return sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")), key=os.path.getmtime, reverse=True)
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return sorted(glob.glob(os.path.join(os.path.expanduser(codex_home), "sessions/**/rollout-*.jsonl"), recursive=True), key=os.path.getmtime, reverse=True)


def extract_jsonl(agent, key=None, source_path=None):
    paths = jsonl_paths(agent, source_path)
    if not paths:
        raise ExtractError(2, f"ERROR: no {agent} transcript found\n")

    units_of = claude_units if agent == "claude" else codex_units
    turn_of = claude_turn if agent == "claude" else codex_turn

    if key:
        for p in paths:
            rows_raw = load(p)
            units = units_of(rows_raw)
            # latest user message matching the nonce
            j = None
            for k in range(len(units) - 1, -1, -1):
                role, t = role_text(units, k, agent)
                if role == "user" and has_nonce_marker(t, key):
                    j = k
                    break
            if j is not None:
                turn = turn_of(units, j)
                if not turn.strip():
                    raise ExtractError(4, "[fed_read] ERROR: matched nonce but the turn is EMPTY — agent may still be working.\n")
                rows = window_rows_from_units(units, j, agent)
                raw_window = raw_window_from_units(rows_raw, units, j)
                return {
                    "agent": agent,
                    "nonce": key,
                    "reply": turn,
                    "source_path": abs_path(p),
                    "source_kind": "jsonl",
                    "window_sha256": canonical_window_sha256(agent, key, rows),
                    "source_file_sha256": file_sha256(p),
                    "tool_events": ["jsonl"] if has_structured_tool_event(raw_window) else [],
                }
        raise ExtractError(
            3,
            f"ERROR: nonce {key!r} NOT FOUND in any {agent} transcript — the agent has not replied yet "
            f"(or the send failed). Refusing to fall back to most-recent (would read the wrong / coordinator's own "
            f"transcript). Wait for fed_wait ALL_IDLE, then re-read.\n",
        )

    # No key: explicit unsafe fallback for manual debugging only.
    rows_raw = load(paths[0])
    units = units_of(rows_raw)
    j = None
    for k in range(len(units) - 1, -1, -1):
        role, t = role_text(units, k, agent)
        if role == "user" and norm(t):
            j = k
            break
    turn = turn_of(units, j) if j is not None else ""
    rows = window_rows_from_units(units, j, agent) if j is not None else []
    raw_window = raw_window_from_units(rows_raw, units, j) if j is not None else []
    return {
        "agent": agent,
        "nonce": "",
        "reply": turn,
        "source_path": abs_path(paths[0]),
        "source_kind": "jsonl",
        "window_sha256": canonical_window_sha256(agent, "", rows),
        "source_file_sha256": file_sha256(paths[0]),
        "tool_events": ["jsonl"] if has_structured_tool_event(raw_window) else [],
    }


# ---- Hermes state.db: rows = messages(id, session_id, role, content, active) ----
def hermes_state_paths(source_path=None):
    if source_path:
        p = Path(source_path).expanduser()
        if not p.exists():
            raise ExtractError(2, f"ERROR: source not found: {source_path}\n")
        return [Path(abs_path(p))]

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


def table_columns(con, table):
    try:
        return {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


REMOTE_HERMES_SOURCE_PREFIX = "hermes+ssh://"


REMOTE_HERMES_READ_CODE = r'''
import json
import os
import sqlite3
import sys
import urllib.parse

TOOL_EVENT_TYPES = {
    "tool_use",
    "tool_result",
    "tool_call",
    "function_call",
    "function_call_output",
    "computer_call",
    "web_search_call",
    "local_shell_call",
}

key = sys.argv[1]
db_path = os.path.expanduser(sys.argv[2])

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

def has_nonce_marker(text, key):
    marker = "[[" + key + "]]"
    nonempty = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            nonempty.append(stripped)
    return len(nonempty) >= 2 and nonempty[0] == marker and nonempty[-1] == marker

def has_structured_tool_event(value):
    if isinstance(value, str) and value.startswith("\x00json:"):
        try:
            return has_structured_tool_event(json.loads(value[len("\x00json:"):]))
        except Exception:
            return False
    if isinstance(value, dict):
        typ = value.get("type")
        if isinstance(typ, str) and typ in TOOL_EVENT_TYPES:
            return True
        role = value.get("role")
        if isinstance(role, str) and role in ("tool", "tool_call"):
            return True
        if "tool_use_id" in value or "tool_call_id" in value:
            return True
        return any(has_structured_tool_event(v) for v in value.values())
    if isinstance(value, list):
        return any(has_structured_tool_event(v) for v in value)
    return False

def table_columns(con, table):
    try:
        return {row["name"] for row in con.execute("PRAGMA table_info(" + table + ")")}
    except sqlite3.Error:
        return set()

con = None
try:
    db_uri = "file:" + urllib.parse.quote(db_path, safe="/:") + "?mode=ro"
    con = sqlite3.connect(db_uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    columns = table_columns(con, "messages")
    active_clause = "AND active = 1 " if "active" in columns else ""
    active_select = ", active" if "active" in columns else ""

    anchor = None
    if key:
        for row in con.execute(
            "SELECT id, session_id, role, content"
            + active_select
            + " FROM messages WHERE role = 'user' "
            + active_clause
            + "ORDER BY id DESC"
        ):
            if has_nonce_marker(text_of(row["content"]), key):
                anchor = row
                break
    else:
        anchor = con.execute(
            "SELECT id, session_id, role, content"
            + active_select
            + " FROM messages WHERE role = 'user' "
            + active_clause
            + "AND COALESCE(content, '') != '' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if not anchor:
        print(json.dumps({"found": False}))
        sys.exit(0)

    rows = con.execute(
        "SELECT id, role, content"
        + active_select
        + " FROM messages WHERE session_id = ? AND id > ? "
        + active_clause
        + "ORDER BY id",
        (anchor["session_id"], anchor["id"]),
    ).fetchall()

    parts = []
    window_rows = [{"role": anchor["role"], "text": text_of(anchor["content"])}]
    tool_events = []
    last_id = anchor["id"]
    for row in rows:
        role = row["role"]
        text = text_of(row["content"])
        if role == "user" and norm(text):
            break
        window_rows.append({"role": role, "text": text})
        if role not in ("user", "assistant"):
            tool_events.append("hermes:" + str(role))
        elif has_structured_tool_event(row["content"]):
            tool_events.append("hermes:" + str(role))
        last_id = row["id"]
        if role == "assistant" and text.strip():
            parts.append(text)

    turn = "\n\n".join(parts)
    print(json.dumps({
        "found": True,
        "session_id": anchor["session_id"],
        "anchor_id": anchor["id"],
        "last_id": last_id,
        "turn": turn,
        "empty": not bool(turn.strip()),
        "window_rows": window_rows,
        "tool_events": tool_events,
    }))
finally:
    if con is not None:
        con.close()
'''


def ssh_command_hash(tokens):
    canonical_argv = json.dumps(list(tokens), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical_argv.encode("utf-8")).hexdigest()


def remote_source_path(tokens, db_path):
    return (
        REMOTE_HERMES_SOURCE_PREFIX
        + "cmd-"
        + ssh_command_hash(tokens)
        + "/"
        + urllib.parse.quote(db_path, safe="")
    )


def parse_remote_source_path(source_path):
    source = str(source_path or "")
    if not source.startswith(REMOTE_HERMES_SOURCE_PREFIX):
        return None
    rest = source[len(REMOTE_HERMES_SOURCE_PREFIX):]
    if "/" not in rest:
        raise ExtractError(2, f"ERROR: invalid remote Hermes source path: {source}\n")
    cmd_id, encoded_db = rest.split("/", 1)
    if not re.fullmatch(r"cmd-[0-9a-f]{64}", cmd_id):
        raise ExtractError(2, f"ERROR: invalid remote Hermes source command id: {cmd_id}\n")
    return cmd_id[4:], urllib.parse.unquote(encoded_db)


def ssh_host_label(tokens):
    for token in reversed(tokens):
        if "@" in token and not token.startswith("-"):
            return token
    return "remote"


def remote_ssh_tokens():
    raw_cmd = os.environ.get("FED_HERMES_SSH_CMD", "")
    try:
        tokens = [os.path.expanduser(os.path.expandvars(t)) for t in shlex.split(raw_cmd)]
    except ValueError as e:
        raise ExtractError(2, f"ERROR: FED_HERMES_SSH_CMD could not be parsed: {e}\n")
    if not raw_cmd.strip() or not tokens:
        raise ExtractError(2, "ERROR: FED_HERMES_REMOTE_READ=ssh but FED_HERMES_SSH_CMD is empty/unset.\n")
    return raw_cmd, tokens


def hermes_query_turn_remote_ssh(key=None, source_path=None):
    raw_cmd, tokens = remote_ssh_tokens()
    parsed_source = parse_remote_source_path(source_path)
    if parsed_source:
        expected_hash, db_path = parsed_source
        actual_hash = ssh_command_hash(tokens)
        if actual_hash != expected_hash:
            raise ExtractError(
                2,
                "ERROR: remote Hermes source path was created for a different FED_HERMES_SSH_CMD expanded argv.\n",
            )
    else:
        db_path = os.environ.get("FED_HERMES_REMOTE_STATE_DB", "~/.hermes/state.db")

    timeout_raw = os.environ.get("FED_HERMES_SSH_TIMEOUT", "30")
    try:
        timeout = int(timeout_raw)
    except ValueError:
        timeout = 30
    argv = tokens + ["python3", "-", key or "", db_path]
    try:
        proc = subprocess.run(
            argv,
            input=REMOTE_HERMES_READ_CODE,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as e:
        raise ExtractError(2, f"ERROR: remote Hermes SSH read failed to execute: {e}\n")
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()
        raise ExtractError(2, f"ERROR: remote Hermes SSH read exited {proc.returncode}. {detail}\n")
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else {}
    except Exception as e:
        raise ExtractError(2, f"ERROR: could not parse remote Hermes read output: {e}\n")
    data["source_path"] = remote_source_path(tokens, db_path)
    data["source_label"] = f"{ssh_host_label(tokens)}:{db_path}"
    return data


def hermes_query_turn(db_path, key=None):
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    try:
        columns = table_columns(con, "messages")
        active_clause = "AND active = 1 " if "active" in columns else ""
        active_select = ", active" if "active" in columns else ""
        anchor = None
        if key:
            # Decode in Python and require the first non-empty line to be the
            # exact nonce marker. Substring matching can select later cross
            # briefs that quote an old nonce.
            for row in con.execute(
                "SELECT id, session_id, role, content"
                f"{active_select} FROM messages WHERE role = 'user' "
                f"{active_clause}ORDER BY id DESC"
            ):
                if has_nonce_marker(text_of(row["content"]), key):
                    anchor = row
                    break
        else:
            anchor = con.execute(
                "SELECT id, session_id, role, content"
                f"{active_select} FROM messages WHERE role = 'user' "
                f"{active_clause}AND COALESCE(content, '') != '' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not anchor:
            return None

        def rows_after(active=True):
            row_active_clause = "AND active = 1 " if active and "active" in columns else ""
            return con.execute(
                "SELECT id, role, content"
                f"{active_select} FROM messages "
                "WHERE session_id = ? AND id > ? "
                f"{row_active_clause}ORDER BY id",
                (anchor["session_id"], anchor["id"]),
            ).fetchall()

        try:
            rows = rows_after(active=True)
        except sqlite3.OperationalError:
            rows = rows_after(active=False)

        parts = []
        window_rows = [{"role": anchor["role"], "text": text_of(anchor["content"])}]
        tool_events = []
        last_id = anchor["id"]
        for row in rows:
            role = row["role"]
            text = text_of(row["content"])
            if role == "user" and norm(text):
                break
            window_rows.append({"role": role, "text": text})
            if role not in ("user", "assistant"):
                tool_events.append(f"hermes:{role}")
            elif has_structured_tool_event(row["content"]):
                tool_events.append(f"hermes:{role}")
            last_id = row["id"]
            if role == "assistant" and text.strip():
                parts.append(text)
        return {
            "session_id": anchor["session_id"],
            "anchor_id": anchor["id"],
            "last_id": last_id,
            "turn": "\n\n".join(parts),
            "window_rows": window_rows,
            "tool_events": tool_events,
        }
    finally:
        con.close()


def extract_hermes(key=None, source_path=None):
    remote_source = parse_remote_source_path(source_path)
    if remote_source or (source_path is None and os.environ.get("FED_HERMES_REMOTE_READ") == "ssh"):
        found = hermes_query_turn_remote_ssh(key, source_path)
        if not found.get("found"):
            raise ExtractError(
                3,
                f"ERROR: nonce {key!r} NOT FOUND in remote Hermes state.db — the agent has not replied yet "
                "(or the send failed). Wait for fed_wait ALL_IDLE, then re-read.\n",
            )
        turn = found.get("turn") or ""
        if found.get("empty") or not turn.strip():
            raise ExtractError(4, "[fed_read] ERROR: matched nonce but the turn is EMPTY — agent may still be working.\n")
        return {
            "agent": "hermes",
            "nonce": key or "",
            "reply": turn,
            "source_path": found["source_path"],
            "source_kind": "sqlite",
            "window_sha256": canonical_window_sha256("hermes", key or "", found.get("window_rows", [])),
            "source_file_sha256": None,
            "session_id": found.get("session_id"),
            "anchor_id": found.get("anchor_id"),
            "last_id": found.get("last_id"),
            "tool_events": found.get("tool_events", []),
            "source_label": found.get("source_label"),
        }

    paths = hermes_state_paths(source_path)
    if not paths:
        raise ExtractError(2, "ERROR: no Hermes state.db found under ${HERMES_HOME:-~/.hermes}\n")
    last_error = None
    for p in paths:
        try:
            found = hermes_query_turn(p, key)
        except sqlite3.Error as e:
            last_error = e
            continue
        if found:
            turn = found["turn"]
            if not turn.strip():
                raise ExtractError(4, "[fed_read] ERROR: matched nonce but the turn is EMPTY — agent may still be working.\n")
            return {
                "agent": "hermes",
                "nonce": key or "",
                "reply": turn,
                "source_path": abs_path(p),
                "source_kind": "sqlite",
                "window_sha256": canonical_window_sha256("hermes", key or "", found["window_rows"]),
                "source_file_sha256": file_sha256(p),
                "session_id": found["session_id"],
                "anchor_id": found["anchor_id"],
                "last_id": found["last_id"],
                "tool_events": found.get("tool_events", []),
            }
    if key:
        detail = f" Last SQLite error: {last_error}" if last_error else ""
        raise ExtractError(
            3,
            f"ERROR: nonce {key!r} NOT FOUND in any Hermes state.db — the agent has not replied yet "
            f"(or the send failed). Wait for fed_wait ALL_IDLE, then re-read.{detail}\n",
        )
    raise ExtractError(3, "[fed_read] WARNING: no --nonce and no Hermes user turn found.\n")


def hermes_read(key=None):
    try:
        result = extract_hermes(key)
    except ExtractError as e:
        sys.stderr.write(e.message)
        sys.exit(e.code)
    if str(result.get("source_path", "")).startswith(REMOTE_HERMES_SOURCE_PREFIX):
        label = result.get("source_label") or result["source_path"]
        sys.stderr.write(f"[fed_read hermes remote] {label} session={result.get('session_id', '')}\n")
    else:
        sys.stderr.write(f"[fed_read hermes] {result['source_path']} session={result.get('session_id', '')}\n")
    print(result["reply"])


def extract(agent, nonce=None, source_path=None, unsafe_latest=False):
    if agent not in ("claude", "codex", "hermes"):
        raise ExtractError(2, f"ERROR: unknown agent: {agent}\n")
    if nonce and not validate_nonce(nonce):
        raise ExtractError(2, f"ERROR: invalid nonce format: {nonce!r}\n")
    if not nonce and not unsafe_latest:
        raise ExtractError(2, "ERROR: --nonce is required. Use --unsafe-latest only for manual debugging.\n")
    if agent == "hermes":
        return extract_hermes(nonce, source_path)
    return extract_jsonl(agent, nonce, source_path)


def write_receipt(result, receipt_dir):
    if not result.get("nonce"):
        raise ExtractError(2, "ERROR: --receipt-dir requires --nonce; unsafe latest receipts are not supported.\n")
    out_dir = Path(receipt_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    agent = result["agent"]
    reply_bytes = result["reply"].encode("utf-8")
    reply_path = out_dir / f"reply_{agent}.txt"
    receipt_path = out_dir / f"receipt_{agent}.json"
    receipt = {
        "schema": "federate.read_receipt.v1",
        "agent": agent,
        "nonce": result["nonce"],
        "reply_path": reply_path.name,
        "reply_bytes": len(reply_bytes),
        "reply_sha256": sha256_bytes(reply_bytes),
        "source_path": result["source_path"],
        "source_kind": result["source_kind"],
        "window_sha256": result["window_sha256"],
        "source_file_sha256": result.get("source_file_sha256"),
        "extracted_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    try:
        reply_path.write_bytes(reply_bytes)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as e:
        raise ExtractError(2, f"ERROR: failed to write receipt files in {out_dir}: {e}\n")
    return reply_path, receipt_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", choices=["claude", "codex", "hermes"])
    ap.add_argument("--nonce")
    ap.add_argument("--match-file")
    ap.add_argument("--source")
    ap.add_argument("--receipt-dir")
    ap.add_argument("--no-tool-window", action="store_true",
                    help="cross-show gate: fail if the nonce window contains structured tool events")
    ap.add_argument("--require-no-tool-audit", action="store_true",
                    help="cross-show gate: first non-empty reply line must be 'NO_TOOL_AUDIT: no tools used'")
    ap.add_argument("--unsafe-latest", action="store_true", help="debug only: read the latest turn without a nonce")
    a = ap.parse_args()

    key = a.nonce
    if not key and a.match_file and os.path.exists(a.match_file):
        key = norm(open(a.match_file, errors="replace").read())[:80]

    if a.agent == "hermes" and a.unsafe_latest:
        sys.stderr.write("[fed_read] WARNING: --unsafe-latest; reading the most-recent Hermes user turn.\n")
    elif not key and a.unsafe_latest:
        sys.stderr.write("[fed_read] WARNING: --unsafe-latest; falling back to most-recent transcript.\n")

    try:
        result = extract(a.agent, key, source_path=a.source, unsafe_latest=a.unsafe_latest)
        if a.no_tool_window:
            require_no_tool_window(result)
        if a.require_no_tool_audit:
            require_no_tool_audit(result)
        if a.agent == "hermes":
            session = result.get("session_id", "")
            if str(result.get("source_path", "")).startswith(REMOTE_HERMES_SOURCE_PREFIX):
                label = result.get("source_label") or result["source_path"]
                sys.stderr.write(f"[fed_read hermes remote] {label} session={session}\n")
            else:
                sys.stderr.write(f"[fed_read hermes] {result['source_path']} session={session}\n")
        else:
            sys.stderr.write(f"[fed_read {a.agent}] {result['source_path']}\n")
        if a.receipt_dir:
            reply_path, receipt_path = write_receipt(result, a.receipt_dir)
            sys.stderr.write(f"[fed_read] wrote {reply_path} and {receipt_path}\n")
        print(result["reply"])
    except ExtractError as e:
        sys.stderr.write(e.message)
        sys.exit(e.code)


if __name__ == "__main__":
    main()
