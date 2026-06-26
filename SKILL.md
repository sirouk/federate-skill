---
name: federate
description: "Run an explicit cross-agent federation loop between two or more tmux-backed peer agents: Claude, Codex, and Hermes when available. Use when the user says \"federate\", \"fed-synth\", or \"federation\", or explicitly asks for independent cross-agent review, mandatory cross-pollination, convergence confidence, confidence polling, test-first build role assignment, human-in-the-loop synthesis, or delegated project-owner progression."
---

# Federate - Federation & Synthesis of Intelligence

## Overview

Run a complete federation iteration across independent peer agents, then
synthesize convergence for the operator. One iteration is one to three complete
rounds. Every round includes independent peer responses, confidence scoring,
verbatim cross-pollination, revised confidence after crossing, and coordinator
synthesis. The coordinator is the agent using this skill; the operator is the
user unless the user explicitly delegates project-owner judgment to the
coordinator. The peer set is any two or more available tmux-backed agents among
Claude, Codex, and Hermes.

Skill installation controls which agent hosts can act as coordinator. It does not control which agents can participate as peers. Peer agents do not need this skill installed; they only need their CLI installed, authenticated, and reachable through tmux.

Treat every coordinator finding as an input to route through the loop, not as a
solo verdict. Relay peer responses verbatim when crossing them to the other
peers. Put summaries, scoring, and advice only in the coordinator synthesis.
Do not ask whether to cross-pollinate; it is part of the default federation
contract.

## Invoke

Invoke when the user says "federate", "fed-synth", or "federation", or
explicitly asks for independent cross-agent review. If a consequential plan,
audit result, build milestone, fix set, irreversible action, or verdict would
benefit from federation but the user did not ask for it, ask for confirmation
first and include the peer set, data scope, read-only/build mode, permission
mode, and expected extra cost/time.

One invocation means one complete federation iteration:

1. Check whether the installed skill is current.
2. Check and load the managed coordinator operating profile.
3. Create a relay workspace and thread-scoped `FED_NS`.
4. Bootstrap peer tmux sessions inside that namespace.
5. Frame the object and rails.
6. Send to all peers independently before reading any peer.
7. Record the sent nonces in a round manifest, then read replies with
   receipt sidecars.
8. Generate and verify tamper-evident cross briefs, then run the round
   accountability check.
9. Cross-pollinate each peer with the other peers' verified verbatim replies.
10. Collect cross-pollinated replies, including revised confidence.
11. Judge convergence confidence adaptively from the peer intelligence and
   synthesize the barycenter of the result.
12. If convergence is not high enough for the current bounded decision, run
   another complete round without asking, up to three rounds total for the
   iteration.
13. Return the synthesis with a short convergence note, or advance one bounded
   step if the user delegated project-owner judgment.

## Modes

- **Operator-HITL mode**: Default. The coordinator federates internally until
  convergence is high enough for the current bounded decision or the
  three-round cap is reached, then returns the synthesis to the user for
  discussion and decision.
- **Delegated project-owner mode**: Use only after the human confirms the
  delegation handshake below. The coordinator emulates the human in the loop as
  a project-owner proxy, using the user's stated goals, preferences, risk
  tolerance, style, and prior thread context as steering evidence. The
  coordinator still advances step by step: run a full federation iteration,
  choose the barycenter of the converged plan, execute only the next small
  reversible step, then federate the result before moving again. Do not stop for
  ordinary project-owner choices once the user has delegated. Stop only for hard
  gates, unavailable peers, or unresolved blocking divergence after the
  three-round cap.

### Delegation Handshake

Before acting as delegated project-owner, get explicit human confirmation of
one mode. Ask once, keep it A/B, record the answer in `relay_log.md`, and do not
hassle the human again for ordinary project-owner choices:

- **A. Plan-following proxy**: Confirm existing plan artifacts or thread plans
  exist. Summarize the plan, current project state, next logical step, and the
  user preferences/goals you will use as steering context. Then proceed one
  bounded reversible step at a time, federating each step.
- **B. Federated steering proxy**: Confirm the user wants direction to emerge
  from federation. At each step, use full federation to choose the next bounded
  step, using the user's goals, preferences, prior decisions, and observed
  leanings as steering context.

In both modes, state the hard gates before proceeding: irreversible actions,
external sends, spending, credential exposure, destructive operations,
permission escalation, and production-impacting deploys still require explicit
human authorization.

## Update Check

At the start of every invocation, before bootstrapping peers, run the installed
update checker:

```bash
/absolute/path/to/federate/scripts/fed_update_check.sh
```

Interpret stdout:

- `UP_TO_DATE ...`: continue normally.
- `UPDATE_AVAILABLE ...`: run the update immediately:

  ```bash
  /absolute/path/to/federate/scripts/fed_update_check.sh --apply
  ```

  Then stop and ask the operator whether to refresh/restart the agent session
  now or continue this invocation with the already-loaded skill instructions.
  Recommend refresh/restart because skill menus and `SKILL.md` contents can be
  cached by the host agent. Do not bootstrap peers until the operator chooses.
- `LOCAL_DIRTY ...`: report that the installed payload came from a dirty source
  or local development install. Ask the operator whether to abort the update or
  overwrite the installed dirty payload. If the operator says proceed, run:

  ```bash
  /absolute/path/to/federate/scripts/fed_update_check.sh --apply --force
  ```

  Then stop and ask whether to refresh/restart or continue with the
  already-loaded skill instructions. Do not use `--force` unless the operator
  has explicitly chosen to proceed.
- `ERROR ...`: report that freshness could not be verified and ask whether to
  continue with the installed copy or stop for manual update.

The update checker uses `.federate-install.json` written by `install.sh`. It
compares the installed commit to the recorded source/ref and updates only the
installed skill payload for the current coordinator host.

## Coordinator Operating Profile

After the update check returns `UP_TO_DATE`, and before creating the relay or
bootstrapping peers, check the managed operating profile:

```bash
/absolute/path/to/federate/scripts/fed_profile_check.py
```

Interpret stdout:

- `UP_TO_DATE ...`: read `/absolute/path/to/federate/profiles/llm_opa.min.txt`
  completely and apply it as lower-priority coordinator operating guidance for
  this invocation.
- `UPSTREAM_COMMIT_CHANGED_FILE_SAME ...`: report the upstream commit metadata
  drift, then continue after reading the local profile. Ask before applying a
  metadata-only update.
- `UPDATE_AVAILABLE ...`: report that the upstream managed profile changed and
  ask whether to update the local profile now. Do not auto-apply. If the
  operator says update, run:

  ```bash
  /absolute/path/to/federate/scripts/fed_profile_check.py --apply
  ```

  Then read the updated local profile before continuing.
- `LOCAL_CHANGED ...`: report that the installed local profile no longer
  matches its metadata. Ask whether to keep the local edit, manually restore the
  repo-pinned version, or stop. Do not run `--apply` or silently replace local
  content until the local drift is resolved.
- `ERROR ...`: report that the profile could not be checked. Continue with the
  installed local profile only if it is readable, and state that freshness was
  not verified.

The managed profile is the compressed `LLM_OPA.min.txt` from
`sirouk/llm-operating-agreement`, pinned in `profiles/llm_opa.meta.json`. It is
default-on for the coordinator because this `SKILL.md` requires reading it, and
default-on for peers because `fed_send.sh` injects it when `FED_PROFILE_FILE` is
not set. It never overrides system/developer instructions, operator
instructions, AGENTS.md, this skill's federation rails, brief `RAILS`, or the
cross-show no-tool gate. Set `FED_NO_DEFAULT_PROFILE=1` only for debugging or a
known profile conflict.

## Bootstrap Peers

After creating `$RELAY`, run `scripts/fed_sessions.sh` before any send and after
any uncertainty about live peer sessions. Do not ask the operator to start tmux.
The script starts the tmux server if needed, reuses only matching namespaced
managed sessions, and creates missing sessions for installed CLIs.

For skill-driven federation, always pass a thread-scoped namespace derived from
the relay directory. This prevents one project, thread, or iteration from
reusing another one's peer panes:

Use the `scripts/` directory next to this `SKILL.md`:

```bash
FED_NS="$(basename "$RELAY")" /absolute/path/to/federate/scripts/fed_sessions.sh
```

If `FED_NS` is omitted, the helper falls back to a project-scoped namespace for
manual shell use and warns that it is not thread-isolated.

Defaults are yolo/no-prompt for federation peers:

- `fed-<ns>-claude-*`: `IS_SANDBOX=1 claude --dangerously-skip-permissions`
- `fed-<ns>-codex-*`: `codex --dangerously-bypass-approvals-and-sandbox`
- `fed-<ns>-hermes-*`: `hermes --cli --yolo`

Runtime controls:

- `FED_AGENTS=claude,codex` limits the runtime peer set; positional args work too: `fed_sessions.sh claude codex`. This is independent of where the skill is installed.
- `FED_NS` sets the federation/thread namespace. Skill-driven runs must set it
  from `$RELAY`; manual runs fall back to project scope.
- `FED_NS_ROOT` overrides the canonical project root. By default the script
  uses `git rev-parse --show-toplevel`, else `pwd -P`.
- `FED_CLAUDE_CMD`, `FED_CODEX_CMD`, and `FED_HERMES_CMD` override launch commands.
- `FED_PROFILE_FILE` must be an absolute path when set. It overrides the managed
  default peer profile for that send path. Missing, unreadable, relative-path,
  or private-key-looking profile files fail before paste. The profile never
  overrides operator instructions or brief rails.
- `FED_NO_DEFAULT_PROFILE=1` disables the managed default peer profile injection
  for debugging or a known profile conflict. Do not use it for normal
  federation.
- Use explicit `FED_*_CMD` overrides only when you intentionally want prompt mode
  or a custom model/profile. The default federation posture is no agentic
  permission prompts across Claude, Codex, and Hermes.
- Legacy global `claude-*`, `codex-*`, or `hermes-*` sessions are skipped by
  default. `FED_REUSE_LEGACY=1` allows adopting old federate-managed sessions
  after you verify they are safe.
- `FED_REUSE_UNMANAGED=1` allows adopting pre-existing untagged sessions after
  you verify they are the intended peers.
- Legacy/unmanaged adoption refuses attached or busy sessions unless
  `FED_REUSE_ATTACHED=1` or `FED_REUSE_BUSY=1` is set.
- `FED_REUSE_FOREIGN_ROOT=1` allows explicit-namespace reuse across different
  roots. Do not use it unless you intentionally share peers across projects.
- `FED_TMUX_WIDTH` and `FED_TMUX_HEIGHT` override the default wide panes.

The script prints `FEDERATE_DIR=...`, `FED_NS=...`, `FED_NS_ROOT=...`, one
session variable per available peer such as
`CLAUDE_SESSION=fed-<ns>-claude-0`, and one eval-safe attach command variable
such as `CLAUDE_ATTACH_CMD='tmux attach-session -r -t fed-<ns>-claude-0'`. It
also prints a read-only watch block on stderr. Record
the printed namespace, root, literal session names, and attach commands in
`relay_log.md`, and surface the attach commands to the operator after
initialization so they can watch the peers in another terminal. The coordinator
must not attach to peer panes during a federation round. Use the literal session
names in later commands; shell variables do not persist between tool calls. If
fewer than two peers are available, stop and report the missing
CLI/authentication requirement.

Preflight every session, new or reused. Confirm live composer, idle state, expected project/cwd, account/model, permission mode, and no pending prompt. If the script prints `CREATED`, the CLI is still booting. Wait about 10 seconds, then run the readiness preflight before first send:

```bash
/absolute/path/to/federate/scripts/fed_ready.sh "<printed-codex-session>" "<printed-hermes-session>"
```

Proceed only when each session prints `READY`. `fed_ready.sh` refuses unmanaged or foreign sessions, treats busy panes as `NOT_READY`, and safely clears the known Codex update menu by moving from "Update now" to plain "Skip" before pressing Enter. Set `FED_NO_AUTO_SKIP=1` to report that prompt without touching it. If `fed_send.sh` reports `ERROR: paste not detected`, the peer is not ready or is busy; wait and retry.

## Relay Workspace

Create one relay directory outside the project under review and reuse it for the
whole iteration. Do this immediately after the update check and before
bootstrapping peers because the relay name becomes the thread namespace:

```bash
umask 077
mkdir -p -m 700 "$HOME/relay"
RELAY="$(mktemp -d "$HOME/relay/$(date +%Y%m%d_%H%M%S).XXXXXX")"
chmod 700 "$RELAY"
```

Keep `relay_log.md` at `$RELAY`. For each round, create a distinct artifact
directory such as `$ROUND="$RELAY/round_1"` for that round's briefs, nonce
files, verbatim reads, receipts, manifests, hashes, and cross-show files. This
keeps round 2/3 from overwriting round 1 custody artifacts while preserving the
same thread namespace. Relay files can contain proprietary code, prompts, peer
output, and secrets accidentally included by peers; keep permissions
restrictive and clean them up when retention is no longer needed. Never write
relay artifacts into the project under audit.

## Iteration Budget

An iteration contains one to three complete rounds. A complete round is:
independent sends, independent reads, verbatim cross-pollination, cross reads,
and synthesis. Partial rounds are not federation.

Do not ask the operator whether another internal round is necessary. Judge it:

- Run round 2 when independent replies have material disagreement, weak
  receipts, different assumptions, or non-overlapping plans that need
  reconciliation.
- Run round 3 when round 2 improves convergence but leaves a blocking delta or
  when useful orthogonal tension needs one more reconcile pass.
- Stop after round 1, 2, or 3 only when the synthesis is high confidence enough
  for the current step, or after round 3 with the best high-confidence synthesis
  plus explicit residual tension.

There is no fixed numeric threshold for "high enough." The coordinator has to
judge sufficiency from the intelligence the peers produced. A result is high
enough for the current bounded decision when the coordinator can defend all of
these claims from the independent and cross-pollinated replies:

- the peers converge on the same verdict, plan spine, or next small action;
- each material objection has been accepted, answered, or narrowed to
  non-blocking useful tension;
- receipts and assumptions are shared enough that one peer's result is not
  resting on a private fact the others rejected;
- no peer has an unresolved blocker that would change the next bounded step;
- confidence is stable or rising after cross-pollination, or any drop is
  explained and non-blocking for the current step.

For delegated project-owner mode, require absolute high convergence before
moving: the next action must be small, reversible, within the A/B delegation,
outside every hard gate, supported by verified receipts, and have an obvious
undo or rollback path. If that is not true after three rounds, stop with the
residual blocker instead of pretending to be confident.

Measure convergence confidence from the substance, not the politeness:

- agreement on the core verdict, next action, or plan spine;
- independently derived receipts and whether peers accept them after crossing;
- whether residual disagreements are blocking, orthogonal, or useful tension;
- whether proposed next steps collapse to the same barycenter;
- whether confidence rose, stayed flat, or fell across rounds.

Every federation result, including each delegated step result, must include a
short convergence note. Do not force a rigid response template, but always
include: confidence level or score, rounds in this iteration, why that
confidence is high enough or not high enough for the bounded decision, trend
when more than one round ran, and the main residual delta if any. Preserve peer
numeric scores when peers provide them, but do not force a universal numeric
scale.

## Confidence Poll

Every round includes a confidence poll. Do not treat confidence as a private
coordinator impression; collect it from each peer, cross-pollinate it, and ask
for revised confidence before deciding.

In every independent brief, ask each peer for:

- proposed next bounded step or verdict;
- confidence score or level, with the reason for that score;
- assumptions, receipts, and risks that drive confidence;
- blockers or facts that would change the answer;
- if build work is possible, role confidence for `test/spec owner`,
  `implementation owner`, `reviewer/verifier`, or `none`.

In every cross-pollination brief, include the other peers' confidence statements
verbatim with their arguments. Ask the receiving peer to revise or reaffirm:

- confidence score or level;
- accepted/disputed assumptions;
- role confidence, if build work is in scope;
- whether the group is ready for the next bounded step.

Coordinator synthesis must report confidence as a cross-agent measurement, not
as a simple average. Weight receipt quality, assumption agreement, blocker
severity, role confidence, and whether confidence rose or fell after crossing.
The coordinator decides "high enough" by applying the sufficiency gate above to
the current bounded step, not by averaging peer scores.

## Round Procedure

### 0. Frame

Decide the object: decision, plan, audit finding, fix set, build milestone, or verdict. Set the current round artifact directory, such as `ROUND="$RELAY/round_1"`, before writing briefs. Write one brief per peer in `$ROUND/brief_<agent>.md`; keep them byte-identical except for salutation/name when possible.

Every brief must include:

- `FRAME`: current state and the exact object under review.
- `RAILS`: read-only vs build; frozen artifacts; gated actions; any standing constraint as a literal line, such as `Still NO code`.
- `GROUNDING`: receipts you personally re-derived, with file refs, commands, hashes, or observed facts.
- `ASK`: two or three tight questions; include the confidence poll fields above
  and end with the biggest question for the other peers or operator.
- `ROUND`: round number, prior convergence note if any, and the exact residual
  delta this round should resolve.

Crossing a reversible phase boundary such as plan to code or design to build
requires operator authorization or standing delegated project-owner
authorization recorded in `relay_log.md`. Crossing into an irreversible action
always requires explicit operator authorization.

### 1. Independent Send

Send to every available peer before reading any peer. Capture a fresh nonce for each send; never reuse a nonce.

```bash
ROUND="$RELAY/round_1"
mkdir -p "$ROUND"
/absolute/path/to/federate/scripts/fed_send.sh "<printed-claude-session>" "$ROUND/brief_claude.md" > "$ROUND/nonce_claude"
/absolute/path/to/federate/scripts/fed_send.sh "<printed-codex-session>" "$ROUND/brief_codex.md" > "$ROUND/nonce_codex"
# only if HERMES_SESSION was printed:
/absolute/path/to/federate/scripts/fed_send.sh "<printed-hermes-session>" "$ROUND/brief_hermes.md" > "$ROUND/nonce_hermes"
```

Immediately write `$ROUND/round_manifest.json` for the independent phase,
before any read or cross generation. It must use schema
`federate.round_manifest.v1` and map every sent nonce to its peer agent,
session, and send time:

```json
{
  "schema": "federate.round_manifest.v1",
  "round": 1,
  "phase": "independent",
  "created_at": "2026-06-25T14:22:01Z",
  "expected": {
    "FED-...": {
      "agent": "claude",
      "session": "fed-<ns>-claude-0",
      "sent_at": "2026-06-25T14:22:03Z"
    }
  }
}
```

Wait for the sessions you actually sent to:

```bash
/absolute/path/to/federate/scripts/fed_wait.sh "<printed-claude-session>" "<printed-codex-session>"
# include the printed Hermes session only if you sent to it
```

Then read by nonce from transcripts/state, not tmux scrollback. For the
independent phase, mint receipt sidecars into `$ROUND`; `fed_read.py` owns the
canonical `reply_<agent>.txt` bytes, so do not create those files with stdout
redirection:

```bash
/absolute/path/to/federate/scripts/fed_read.py claude --nonce "$(cat "$ROUND/nonce_claude")" --receipt-dir "$ROUND"
/absolute/path/to/federate/scripts/fed_read.py codex  --nonce "$(cat "$ROUND/nonce_codex")"  --receipt-dir "$ROUND"
# only if you sent to Hermes:
/absolute/path/to/federate/scripts/fed_read.py hermes --nonce "$(cat "$ROUND/nonce_hermes")" --receipt-dir "$ROUND"
```

Sanity-check each read before using it:

- The stderr `[fed_read ...] <path>` line must point at the expected agent transcript or Hermes `state.db`.
- The answer must be a real response, not a placeholder like "I'll run..." or a copy of your brief.
- A matched nonce with an empty turn means the peer is still working; wait again and read with the same nonce.
- `nonce NOT FOUND` means the answer has not landed or the send failed; wait/retry the read, do not fall back.

### 2. Cross-Pollinate

This is the load-bearing hop and is mandatory by default. For each peer, create
`$ROUND/cross_<agent>.md` with `fed_cross.py`, not by hand. First write a
single coordinator framing file, such as `$ROUND/cross_framing.md`, containing
your separate coordinator framing plus the tight confirm/dispute/reconcile ask
and revised confidence poll.

Then generate and verify the cross briefs from the receipt-bound independent
replies:

```bash
/absolute/path/to/federate/scripts/fed_cross.py generate --relay "$RELAY" --round 1 --peers "claude,codex,hermes" --framing "$ROUND/cross_framing.md"
/absolute/path/to/federate/scripts/fed_cross.py verify --relay "$RELAY" --round 1
/absolute/path/to/federate/scripts/fed_round_check.py --relay "$RELAY" --round 1
```

The coordinator framing must require the receiving peer to start its cross-reply
with this exact first non-empty line:

```text
NO_TOOL_AUDIT: no tools used
```

This is a detective hard gate for yolo-preserving cross-show turns. It does not
prevent a malicious tool call from firing before detection, but it makes any
observed tool use or missing audit line fail the round before synthesis.

Use only the peers that produced valid independent receipts in `--peers`. If a
sent peer is unavailable, omit it from `--peers`, save non-empty evidence such
as a `fed_wait` timeout log or `fed_read` NOT FOUND stderr, add a top-level
`unavailable` entry to `cross_manifest.json` with `nonce`, `agent`, `reason`,
and `evidence_path`, then run `fed_round_check.py`. If fewer than two peers
remain available, stop and report the unavailable peer instead of synthesizing.

Do not summarize another peer into a cross brief. `fed_cross.py` embeds the
actual peer reply bytes in length-prefixed untrusted blocks and verifies them
against the `fed_read.py` receipts. If a peer reply contains secrets that cannot
be crossed verbatim, stop for operator direction; do not hand-edit generated
cross files to redact, because post-generation edits must make `fed_cross.py
verify` fail. With three peers, each peer sees the other two peers' verbatim
replies. With two peers, mirror the two replies.

Send all cross briefs before reading any cross reply:

```bash
/absolute/path/to/federate/scripts/fed_send.sh "<printed-claude-session>" "$ROUND/cross_claude.md" > "$ROUND/nonce_cross_claude"
/absolute/path/to/federate/scripts/fed_send.sh "<printed-codex-session>" "$ROUND/cross_codex.md" > "$ROUND/nonce_cross_codex"
# only if Hermes produced a valid independent receipt and was included in --peers:
/absolute/path/to/federate/scripts/fed_send.sh "<printed-hermes-session>" "$ROUND/cross_hermes.md" > "$ROUND/nonce_cross_hermes"
```

Then wait and read by the new nonces with the cross-show gates enabled:

```bash
/absolute/path/to/federate/scripts/fed_read.py claude --nonce "$(cat "$ROUND/nonce_cross_claude")" --no-tool-window --require-no-tool-audit
/absolute/path/to/federate/scripts/fed_read.py codex  --nonce "$(cat "$ROUND/nonce_cross_codex")"  --no-tool-window --require-no-tool-audit
/absolute/path/to/federate/scripts/fed_read.py hermes --nonce "$(cat "$ROUND/nonce_cross_hermes")" --no-tool-window --require-no-tool-audit
```

Store cross-reply reads in distinct files or a distinct receipt directory such
as `$ROUND/cross_reads`; do not overwrite the independent `reply_<agent>.txt`
and `receipt_<agent>.json` files that back the verified `cross_manifest.json`.
If `fed_read.py` reports a structured tool event or missing `NO_TOOL_AUDIT`
line, stop synthesis and report the failed cross-show gate.

Do not skip cross-pollination because the independent replies seem similar,
because the coordinator is confident, or because it costs another peer turn.
Only skip the cross-show when all independent replies are byte-identical and
there are no cross-checkable artifacts. If skipped, tell the operator exactly
why in the convergence note.

### 3. Synthesize

Digest the independent and cross-show replies for the operator:

- Convergence confidence score or level, with trend if this is a later round,
  such as `8.5 -> 9.2`.
- Per-peer confidence before and after cross-pollination when it affected the
  decision.
- Rounds completed in this iteration.
- Agreements that form the spine of the decision.
- Residual deltas that still matter.
- Questions only the operator can answer, preserving each peer's distinct operator-facing question.
- Coordinator advice grounded in convergence and verified receipts.
- The barycenter: the smallest next plan or action that preserves the
  converged commitments while keeping useful orthogonal tension visible.

`LOCK` is the strongest label, not the normal stopping requirement. Use it only
when every peer accepts the other peers' positions with no genuine disagreement
and states the same one-line verdict or next action. Flat or falling
convergence, unresolved blocking deltas, or conflicting operator questions means
run another complete round until the three-round cap. After the cap, return the
best synthesis, preserve healthy orthogonal disagreement, and identify any
blocking choice that truly cannot be made by the coordinator.

### 4. Operator Decides

In Operator-HITL mode, bring the synthesis to the operator and stop. The next
iteration starts from the operator's decision.

In delegated project-owner mode, do not stop after an absolute
high-convergence synthesis. Choose the barycenter, execute the next bounded
reversible step, then run a new federation iteration over the result before
advancing again. Preserve the user's standing constraints and the hard gates
below.

## Build Rails

For build, fix, or milestone work, add these rails to the normal federation loop:

- The coordinator is the orchestrator and verifier by default, not the primary
  code editor. The coordinator may read code, run commands, run tests, inspect
  outputs, assert behavior, and maintain the relay. Prefer peer-owned edits for
  code changes. The coordinator edits code only when fewer than two capable
  peers are available, the change is tiny/mechanical, a peer is blocked, or the
  human explicitly authorizes coordinator implementation.
- Treat each bounded project step as its own federation iteration. Do not jump
  from plan to broad implementation to final sign-off in one move. Federate the
  plan, assign roles from cross-pollinated confidence, execute the next
  reversible step, federate the result, then proceed.
- Before any code edit, poll every peer independently for role confidence, then
  cross-pollinate those confidence statements verbatim. Assign roles only after
  the revised confidence replies return.
- Always assign a `test/spec owner` first. That owner writes or seals the
  failing test, fixture, oracle, assertion, or precise expected behavior before
  implementation begins. If all peers agree no executable test/spec artifact is
  appropriate for the step, seal the expectation in `relay_log.md` before code
  edits.
- Assign an `implementation owner` only after the test/spec expectation is
  sealed.
- Assign a separate `reviewer/verifier` when a third peer is available. With
  two peers, the coordinator acts as reviewer/verifier while avoiding
  implementation edits. With more than three peers, rotate review and
  implementation roles across bounded steps when confidence permits.
- Put cross-checking artifacts on different owners, such as spec vs
  implementation or oracle vs engine.
- Have the non-implementer seal expected values to the coordinator before the
  builder writes code.
- Keep neutral SHA-256 custody: recompute hashes yourself after every frozen-artifact change and record them in `relay_log.md`.
- Gate trust behind fixture or Gate-1 cross-check plus pre-agreed adversarial review. A clean test pass is not sign-off.
- Route review findings back through a full federation round so each owner verifies findings against their own artifact and owns their bugs.
- Gate irreversible actions such as deploys, external sends, destructive
  migrations, one-shot holdout evaluations, credential exposure, spending, or
  permission escalation behind explicit operator authorization even in delegated
  project-owner mode.

For result-bearing evaluations, pre-register methodology, thresholds, and verdict taxonomy before looking at sealed results. Underpowered sealed evidence is `INCONCLUSIVE`, not a silent kill.

## Mechanics

- Use transcripts/state as the clean source. Tmux scrollback is only for liveness because TUI redraws and wrapping corrupt the text.
- Use nonces for every read. Claude transcript search can otherwise select the coordinator's own Claude session; Codex and Hermes can also have multiple active sessions.
- `fed_read.py codex` returns Codex `final_answer` blocks when phase tags exist; commentary is not the cross-show source.
- `fed_read.py` requires a nonce and matches the exact `[[FED...]]` marker inserted by `fed_send.sh`. If the nonce is found but no assistant/final answer is available yet, it exits nonzero; wait and re-read. `--unsafe-latest` exists only for manual debugging.
- `fed_read.py --receipt-dir DIR` writes canonical `reply_<agent>.txt` and
  `receipt_<agent>.json` sidecars only for successful non-empty nonce reads.
  These sidecars are the source for `fed_cross.py`; do not synthesize them by
  redirecting stdout.
- `fed_read.py --no-tool-window` fails if the nonce-anchored transcript window
  contains structured tool events. `--require-no-tool-audit` requires the first
  non-empty reply line to be exactly `NO_TOOL_AUDIT: no tools used`. Use both
  for cross-show reply reads.
- `fed_cross.py generate [--round N]` creates length-prefixed cross briefs from receipt-bound replies; `fed_cross.py verify [--round N]` re-extracts each reply from the recorded transcript/source and reconstructs each cross brief byte-for-byte.
- `fed_round_check.py` compares `round_manifest.json` to `cross_manifest.json`
  so every sent nonce is accounted by a source receipt or an explicit
  unavailable entry with evidence.
- `fed_read.py hermes` searches `${HERMES_HOME:-~/.hermes}/state.db` and profile `state.db` files for the nonce marker in an active user message, then returns assistant messages from that same session until the next user turn.
- For a Hermes peer launched on another host, set `FED_HERMES_REMOTE_READ=ssh`,
  `FED_HERMES_SSH_CMD`, and optionally `FED_HERMES_REMOTE_STATE_DB`. Remote
  reads use the same top-and-bottom nonce, window-hash, and tool-event semantics
  as local Hermes reads. Receipts use a `hermes+ssh://cmd-<sha256>/<db>` source
  path that binds the expanded SSH argv. Re-extraction from that source path
  selects remote mode even without `FED_HERMES_REMOTE_READ=ssh`, and succeeds
  only when `FED_HERMES_SSH_CMD` expands to the same argv.
- `fed_send.sh` uses bracketed paste, places the nonce at the top and bottom of
  the brief for reliable composer verification, and sends Enter separately. If
  verification fails, it clears the staged buffer and exits nonzero.
- `fed_send.sh` refuses to paste into sessions that are not namespaced
  federate-managed peers unless `FED_SKIP_OWNER_CHECK=1` is set for manual
  debugging.
- `fed_send.sh` injects `FED_PROFILE_FILE` when set as a delimited FEDERATION
  PROFILE section after the top nonce. When `FED_PROFILE_FILE` is unset,
  `fed_send.sh` injects the managed default profile from
  `profiles/llm_opa.min.txt` unless `FED_NO_DEFAULT_PROFILE=1` is set. Bad
  profile paths and private-key-looking content fail before any tmux paste.
- `fed_wait.sh` is a liveness hint, not proof of completion. Some agents go pane-idle while sub-work is still running; the nonce read decides whether a real answer has landed.
- `FED_BUSY_RE` overrides the shared busy-marker regex used by `fed_ready.sh`,
  `fed_sessions.sh`, and `fed_wait.sh`. The default is limited to active-turn
  and interrupt markers for Claude, Codex, and Hermes. Use the override when an
  agent TUI changes or a specialized environment needs additional busy markers.
- `fed_update_check.sh` compares `.federate-install.json` to the recorded
  source/ref and can stage then replace the installed payload with `--apply`.
  Dirty installed payloads report `LOCAL_DIRTY` and require operator-approved
  `--apply --force`.

## Ledger

Keep `$RELAY/relay_log.md` current:

- peer sessions and nonces;
- `round_manifest.json`, `cross_manifest.json`, `fed_cross.py verify`, and
  `fed_round_check.py` results for every cross-show phase;
- `FED_NS`, `FED_NS_ROOT`, and peer session names printed by `fed_sessions.sh`;
- phase constraints and operator authorizations;
- delegated project-owner mode, if any, including plan-following vs federated
  steering confirmation and the user preferences used as steering context;
- file refs and hashes you recomputed;
- per-peer confidence before and after cross-pollination;
- convergence score and residual deltas each round;
- decisions, owners, role assignments, sealed test/spec expectations, and gates.

The ledger is the round memory. If a fact is load-bearing and not in the ledger or a linked relay artifact, treat it as not yet established.

## Files

- `scripts/fed_sessions.sh`: start/reuse namespaced tmux peer sessions for Claude, Codex, and Hermes; prints namespace, root, session names, and read-only attach commands.
- `scripts/fed_send.sh <session> <msgfile>`: nonce-tag, bracketed-paste, verify, and submit; stdout is the bare nonce.
- `scripts/fed_read.py <claude|codex|hermes> --nonce N [--receipt-dir DIR]`: return the peer's verbatim answer anchored by nonce and optionally mint receipt sidecars.
- `scripts/fed_cross.py generate|verify [--round N]`: create and verify receipt-bound, tamper-evident cross briefs.
- `scripts/fed_round_check.py --relay DIR [--round N]`: fail the round if any sent nonce is omitted or lacks unavailable evidence.
- `scripts/fed_ready.sh <session...>`: drive managed peer panes to a live composer; safely clear known startup interstitials or report a blocker.
- `scripts/fed_wait.sh <session...>`: wait until all listed sessions appear idle.
- `scripts/fed_update_check.sh [--apply]`: check/apply installed skill updates by recorded commit.
- `scripts/fed_profile_check.py [--apply]`: check/apply the managed default operating-profile metadata and upstream hash.
- `profiles/llm_opa.min.txt`, `profiles/llm_opa.meta.json`: managed default coordinator and peer operating profile plus source metadata.
- `scripts/SPEC_fed_cross.md`, `scripts/SPEC_fed_round_check.md`: human-readable sealed contracts for the receipt-bound cross and round-accountability gates.
- `scripts/tests/`: hermetic regression tests for the federation scripts and install/update hardening.
- `agents/openai.yaml`: Codex UI metadata; disables implicit invocation.
