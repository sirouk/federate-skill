---
name: federate
description: "Run a cross-agent federation loop between two or more tmux-backed peer agents: Claude, Codex, and Hermes when available. Use when the user says \"federate\", \"fed-synth\", or \"federation\", or when a consequential decision, plan, audit, bug fix, build milestone, or verdict needs independent review, cross-pollination, convergence scoring, and an operator decision."
---

# Federate - Federation & Synthesis of Intelligence

## Overview

Run one lockstep review round across independent peer agents, then synthesize the convergence for the operator. The coordinator is the agent using this skill; the operator is the user and remains the decider. The peer set is any two or more available tmux-backed agents among Claude, Codex, and Hermes.

Treat every coordinator finding as an input to route through the loop, not as a solo verdict. Relay peer responses verbatim when crossing them to the other peers. Put summaries, scoring, and advice only in the coordinator synthesis.

## Invoke

Invoke when the user says "federate", "fed-synth", or "federation", or when a consequential plan, audit result, build milestone, fix set, irreversible action, or verdict would benefit from independent review.

One invocation means one complete round:

1. Bootstrap peer tmux sessions.
2. Frame the object and rails.
3. Send to all peers independently before reading any peer.
4. Cross-pollinate each peer with the other peers' verbatim replies.
5. Synthesize convergence and open deltas for the operator.
6. Stop for the operator decision unless they already authorized the next round/action.

## Bootstrap Peers

Always run `scripts/fed_sessions.sh` first in a thread or after any uncertainty about live peer sessions. Do not ask the operator to start tmux. The script starts the tmux server if needed, reuses existing `claude-*`, `codex-*`, and `hermes-*` sessions, and creates missing sessions for installed CLIs.

Use the `scripts/` directory next to this `SKILL.md`:

```bash
/absolute/path/to/federate/scripts/fed_sessions.sh
```

Defaults:

- `claude-*`: `IS_SANDBOX=1 claude --dangerously-skip-permissions`
- `codex-*`: `codex --dangerously-bypass-approvals-and-sandbox`
- `hermes-*`: `hermes --cli --yolo`

Runtime controls:

- `FED_AGENTS=claude,codex` limits the peer set; positional args work too: `fed_sessions.sh claude codex`.
- `FED_CLAUDE_CMD`, `FED_CODEX_CMD`, and `FED_HERMES_CMD` override launch commands.
- `FED_TMUX_WIDTH` and `FED_TMUX_HEIGHT` override the default wide panes.

The script prints `FEDERATE_DIR=...` and one variable per available peer, such as `CLAUDE_SESSION=claude-0`, `CODEX_SESSION=codex-0`, and `HERMES_SESSION=hermes-0`. Use those literal session names in later commands; shell variables do not persist between tool calls. If fewer than two peers are available, stop and report the missing CLI/authentication requirement.

If the script prints `CREATED`, the CLI is still booting. Wait about 10 seconds, then inspect the pane before first send:

```bash
tmux capture-pane -t claude-0 -p | tail -5
```

Proceed only when the composer is live. If `fed_send.sh` reports `ERROR: paste not detected`, the peer is not ready or is busy; wait and retry.

## Relay Workspace

Create one relay directory outside the project under review and reuse it for the whole round:

```bash
RELAY=~/relay/$(date +%Y%m%d_%H%M%S); mkdir -p "$RELAY"
```

Write briefs, verbatim reads, cross-show files, hashes, and `relay_log.md` there. Never write relay artifacts into the project under audit.

## Round Procedure

### 0. Frame

Decide the object: decision, plan, audit finding, fix set, build milestone, or verdict. Write one brief per peer in `$RELAY/brief_<agent>.md`; keep them byte-identical except for salutation/name when possible.

Every brief must include:

- `FRAME`: current state and the exact object under review.
- `RAILS`: read-only vs build; frozen artifacts; gated actions; any standing constraint as a literal line, such as `Still NO code`.
- `GROUNDING`: receipts you personally re-derived, with file refs, commands, hashes, or observed facts.
- `ASK`: two or three tight questions; end with the biggest question for the other peers or operator.

Crossing a phase boundary such as plan to code, design to build, or build to irreversible run requires explicit operator authorization recorded in `relay_log.md`.

### 1. Independent Send

Send to every available peer before reading any peer. Capture a fresh nonce for each send; never reuse a nonce.

```bash
NC=$(/absolute/path/to/federate/scripts/fed_send.sh claude-0 "$RELAY/brief_claude.md")
NX=$(/absolute/path/to/federate/scripts/fed_send.sh codex-0 "$RELAY/brief_codex.md")
NH=$(/absolute/path/to/federate/scripts/fed_send.sh hermes-0 "$RELAY/brief_hermes.md")  # only if HERMES_SESSION was printed
```

Wait for the sessions you actually sent to:

```bash
/absolute/path/to/federate/scripts/fed_wait.sh claude-0 codex-0 hermes-0
```

Then read by nonce from transcripts/state, not tmux scrollback:

```bash
/absolute/path/to/federate/scripts/fed_read.py claude --nonce "$NC"
/absolute/path/to/federate/scripts/fed_read.py codex  --nonce "$NX"
/absolute/path/to/federate/scripts/fed_read.py hermes --nonce "$NH"
```

Sanity-check each read before using it:

- The stderr `[fed_read ...] <path>` line must point at the expected agent transcript or Hermes `state.db`.
- The answer must be a real response, not a placeholder like "I'll run..." or a copy of your brief.
- A matched nonce with an empty turn means the peer is still working; wait again and read with the same nonce.
- `nonce NOT FOUND` means the answer has not landed or the send failed; wait/retry the read, do not fall back.

### 2. Cross-Pollinate

This is the load-bearing hop. For each peer, create `$RELAY/cross_<agent>.md` containing:

1. The other peer replies as labelled verbatim blocks, for example `=== CODEX (verbatim) ===`.
2. Your framing in a separate coordinator section.
3. A tight confirm/dispute/reconcile ask.

Do not summarize another peer into a cross brief. Use the actual words. With three peers, each peer sees the other two peers' verbatim replies. With two peers, mirror the two replies.

Send all cross briefs before reading any cross reply, wait, and read by the new nonces.

Only skip the cross-show when all independent replies are byte-identical and there are no cross-checkable artifacts. If skipped, tell the operator exactly why.

### 3. Synthesize

Digest the independent and cross-show replies for the operator:

- Convergence score with trend if this is a later round, such as `8.5 -> 9.2`.
- Agreements that form the spine of the decision.
- Residual deltas that still matter.
- Questions only the operator can answer, preserving each peer's distinct operator-facing question.
- Coordinator advice grounded in the convergence and verified receipts.

`LOCK` requires every peer to accept the other peers' positions with no genuine disagreement and to state the same one-line verdict. Flat or falling convergence, unresolved deltas, or conflicting operator questions means run another bridging hop or ask the operator to choose.

### 4. Operator Decides

Bring the synthesis to the operator and stop. The next round starts from the operator's decision.

## Build Rails

For build, fix, or milestone work, add these rails to the normal federation loop:

- Assign one accountable owner per work package.
- Put cross-checking artifacts on different owners, such as spec vs implementation or oracle vs engine.
- Have the non-implementer seal expected values to the coordinator before the builder writes code.
- Keep neutral SHA-256 custody: recompute hashes yourself after every frozen-artifact change and record them in `relay_log.md`.
- Gate trust behind fixture or Gate-1 cross-check plus pre-agreed adversarial review. A clean test pass is not sign-off.
- Route review findings back through a full federation round so each owner verifies findings against their own artifact and owns their bugs.
- Gate irreversible actions such as deploys, external sends, destructive migrations, or one-shot holdout evaluations behind explicit operator authorization.

For result-bearing evaluations, pre-register methodology, thresholds, and verdict taxonomy before looking at sealed results. Underpowered sealed evidence is `INCONCLUSIVE`, not a silent kill.

## Mechanics

- Use transcripts/state as the clean source. Tmux scrollback is only for liveness because TUI redraws and wrapping corrupt the text.
- Use nonces for every read. Claude transcript search can otherwise select the coordinator's own Claude session; Codex and Hermes can also have multiple active sessions.
- `fed_read.py codex` returns Codex `final_answer` blocks when phase tags exist; commentary is not the cross-show source.
- `fed_read.py hermes` searches `${HERMES_HOME:-~/.hermes}/state.db` and profile `state.db` files for the nonce in a user message, then returns assistant messages from that same session until the next user turn.
- `fed_send.sh` uses bracketed paste, verifies that text reached the composer, and sends Enter separately. If verification fails, it clears the staged buffer and exits nonzero.
- `fed_wait.sh` is a liveness hint, not proof of completion. Some agents go pane-idle while sub-work is still running; the nonce read decides whether a real answer has landed.

## Ledger

Keep `$RELAY/relay_log.md` current:

- peer sessions and nonces;
- phase constraints and operator authorizations;
- file refs and hashes you recomputed;
- convergence score and residual deltas each round;
- decisions, owners, and gates.

The ledger is the round memory. If a fact is load-bearing and not in the ledger or a linked relay artifact, treat it as not yet established.

## Files

- `scripts/fed_sessions.sh`: start/reuse tmux peer sessions for Claude, Codex, and Hermes; prints session names.
- `scripts/fed_send.sh <session> <msgfile>`: nonce-tag, bracketed-paste, verify, and submit; stdout is the bare nonce.
- `scripts/fed_read.py <claude|codex|hermes> --nonce N`: return the peer's verbatim answer anchored by nonce.
- `scripts/fed_wait.sh <session...>`: wait until all listed sessions appear idle.
