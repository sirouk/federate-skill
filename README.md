# federate — Federation & Synthesis of Intelligence (a Claude Code skill)

> Make four minds think together on every consequential step. A **coordinator** agent relays a
> decision / plan / audit / bug-fix / build-milestone between a **tmux Claude** and a **tmux Codex** —
> asks both **independently**, then **cross-pollinates** (each sees the other), then **digests the
> convergence** and brings it to **you (the operator)**, who decides the next step.

```
                 ┌──────────── Coordinator (the agent running /federate) ───────────┐
   Operator  ◀──▶│   frame → send to BOTH independently → cross-pollinate            │
   (you, the     │        → score convergence → synthesize → advise                  │
    4th voice    └───────────┬───────────────────────────────────┬──────────────────┘
    & decider)               │ tmux (verbatim, via transcripts)   │
                       ┌──────▼──────┐                      ┌───────▼──────┐
                       │   Claude    │   ◀── cross-show ──▶ │    Codex     │
                       │  (claude-*) │                      │  (codex-*)   │
                       └─────────────┘                      └──────────────┘
```

No party rules alone. The coordinator bridges, judges, scores, and guides — and any finding it
makes is an **input routed through the loop, never a solo verdict**. Advice is grounded in
**convergence**; the operator always decides.

This skill is the distilled, battle-tested formalization of that loop: a `SKILL.md` plus four small,
robust helper scripts that encapsulate the mechanics that are *easy to get wrong* — pulling each
agent's reply verbatim from its **transcript** (never the garbled tmux scrollback), bracketed-paste +
a separate Enter, nonce-based disambiguation so a read can never return the coordinator's *own*
transcript, Codex `final_answer`-only extraction, and truncation-aware idle detection.

---

## Prerequisites
- **tmux**
- The **Claude Code** CLI (`claude`) and the **Codex** CLI (`codex`) installed and authenticated
- **python3** and standard coreutils
- A terminal where the coordinator agent can run `tmux` and `bash`

The skill bootstraps two long-lived sessions (reusing any existing `claude-*` / `codex-*`):
```bash
# created on demand if absent:
tmux new -s claude-0  →  IS_SANDBOX=1 claude --dangerously-skip-permissions
tmux new -s codex-0   →  codex --dangerously-bypass-approvals-and-sandbox
```

---

## Install

> Replace **`YOURUSER/federate-skill`** below with your GitHub `owner/repo` once you've pushed this.

### A) Tell your agent to install it (raw URL — the easy path)
Paste this to a Claude Code agent (or run it yourself):
```bash
curl -fsSL https://raw.githubusercontent.com/YOURUSER/federate-skill/main/install.sh | bash
```
That drops the skill into `~/.claude/skills/federate/`. Restart/refresh Claude Code and invoke it by
saying **“federate.”**

### B) Manual (explicit raw fetch)
```bash
D=~/.claude/skills/federate; mkdir -p "$D/scripts"
B=https://raw.githubusercontent.com/YOURUSER/federate-skill/main
curl -fsSL "$B/SKILL.md" -o "$D/SKILL.md"
for s in fed_sessions.sh fed_send.sh fed_read.py fed_wait.sh; do
  curl -fsSL "$B/scripts/$s" -o "$D/scripts/$s"
done
chmod +x "$D"/scripts/*
```

### C) From a clone
```bash
git clone https://github.com/YOURUSER/federate-skill.git
cd federate-skill && ./install.sh
```

**Project-scoped install** instead of personal? Put it under a repo's `.claude/skills/federate/`
(set `FEDERATE_DEST=$PWD/.claude/skills/federate` before running `install.sh`).

---

## Use
Just say **“federate”** at any decision, plan, audit, bug fix, build milestone, or verdict. The
coordinator runs one full round:

1. **Frame** the object + the rails (read-only vs build, what's frozen/gated).
2. **Independent** — send the same brief to both agents in parallel; read each verbatim.
3. **Cross-pollinate** — each agent sees the other's verbatim reply and reconciles.
4. **Synthesize** — convergence score, agreements vs deltas, the questions only you can answer.
5. **You decide** — and the next round starts there.

For **builds**, it adds the discipline that makes four minds coherent: one accountable owner per
artifact, cross-checking artifacts to *different* owners, the non-implementer **seals** the
oracle/expected-values to the coordinator before the build, neutral SHA-256 custody, adversarial
swarm review *before trusting built code* (a clean test pass is not sign-off), and irreversible steps
gated behind your explicit sign-off.

See [`SKILL.md`](./SKILL.md) for the full procedure and the rails.

---

## What's in here
```
SKILL.md              the skill: the 4-party loop, the rails, the cadence
scripts/
  fed_sessions.sh     detect/create the two tmux sessions (wide panes)
  fed_send.sh         nonce-tag + bracketed-paste + dual-TUI verify + SEPARATE Enter (STDOUT = nonce)
  fed_read.py         verbatim reply from the TRANSCRIPT, found by nonce (fails loud if unmatched)
  fed_wait.sh         background idle-monitor (truncation-aware busy patterns)
install.sh            installs into ~/.claude/skills/federate/ (local copy or raw fetch)
```

## Why the scripts exist (lessons paid for)
- **Read transcripts, not scrollback.** tmux scrollback is mangled by tool redraws and wrapping; the
  clean source is the JSONL transcript. One assistant *turn* spans many lines — concatenate them.
- **The nonce is essential.** Without it, a read falls back to the most-recent transcript — which for
  Claude is normally the *coordinator's own* session. `fed_read` matches the injected nonce and
  **fails loud** if it isn't found yet (the agent simply hasn't replied).
- **Codex tags blocks `phase ∈ {commentary, final_answer}`** — relaying its internal commentary would
  poison the cross-show; `fed_read` returns `final_answer` only.
- **Send = bracketed paste + a *separate* Enter.** Embedding the Enter submits early; the verify step
  handles both the Claude and Codex composer chrome and clears a staged-but-unsent buffer on failure.
- **Idle detection is truncation-aware** (`esc to interrupt` renders as `esc to int…` in a narrow
  pane) and tolerates an agent that spawns its *own* sub-workflow and goes pane-idle while still working.

The skill was itself built through this loop and hardened by an adversarial multi-agent review (52
findings; the critical ones folded in) and an end-to-end round-trip test against both live CLIs.

## License
MIT — see [`LICENSE`](./LICENSE).
