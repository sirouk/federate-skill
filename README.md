# federate

Federate runs a lockstep review loop across two or more peer agents in tmux:
Claude, Codex, and Hermes when installed. The coordinator asks peers
independently, cross-pollinates their verbatim replies, scores convergence, and
brings a synthesis back to the operator for the decision.

The helper scripts handle the fragile parts: creating/reusing tmux sessions,
safe bracketed paste, nonce-based transcript reads, Codex final-answer
extraction, Hermes `state.db` reads, and idle waiting.

## Why

Federate exists because I wanted a Ralph-style loop with a human throttle.

The same loop can run lockstep with a human in the chair, or be paired with a
host goal mode such as `/goal` when the work is ready for autopilot.

The point is not model democracy. The point is forcing independent Claude,
Codex, and Hermes passes, then making them read each other's arguments and show
where they actually converge. Convergence is the useful signal. The
disagreements are the work queue.

## Requirements

- `tmux`
- At least two installed and authenticated CLIs among:
  - `claude`
  - `codex`
  - `hermes`
- `bash`, `python3`, and standard Unix tools

You do not need to start tmux yourself. `fed_sessions.sh` starts the tmux server
and creates missing namespaced peer sessions automatically.

## Install

There are two separate scopes:

- **Coordinator install scope**: where the skill can be invoked by the
  coordinator. Codex uses `$federate` or `/skills`; some hosts expose skills in
  slash menus. Install the skill into every agent host you want to use as the
  coordinator later, such as Claude Code and Codex.
- **Federation peer scope**: which tmux-backed peer CLIs participate in a
  round. Peers do not need this skill installed; they only need their CLI
  installed and authenticated. The coordinator controls peers with
  `FED_AGENTS`, defaulting to all available peers.

The installer updates all supported coordinator homes it can write:
Claude Code, Codex, and Hermes. It also writes `.federate-install.json` with the
source, ref, installed commit, dirty flag, and timestamp so the skill can check
for updates at runtime.

### Agent handoff

Paste this into the agent you want to teach:

```text
Install or update the Federate skill from https://github.com/sirouk/federate-skill.

Run exactly:
`curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash`

Verify that the installed directory contains SKILL.md, agents/openai.yaml,
.federate-install.json, and executable scripts/fed_sessions.sh,
scripts/fed_send.sh, scripts/fed_read.py, scripts/fed_cross.py,
scripts/fed_round_check.py, scripts/fed_ready.sh, scripts/fed_wait.sh, and
scripts/fed_update_check.sh.
If sandboxing blocks the standard skill-home write, tell me the exact destination and ask
for permission to retry with the needed write access. Do not pick another destination.

Tell me to refresh or restart the agent session before using the skill. In Codex,
use `$federate` or select it through `/skills`; do not assume `/federate` is a
Codex command. Slash-command and skill menus may be cached until refresh.
Mention the two operating modes: by default the user remains the human in the
loop; if I ask the coordinator to emulate the human in the loop, it must first
confirm whether it should follow an existing plan or use federation to steer one
bounded reversible step at a time. Do not start federation yet.
```

### Shell

```bash
curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash
```

Default target paths:

- Claude Code: `~/.claude/skills/federate`
- Codex: `${CODEX_SKILLS_HOME:-~/.agents/skills}/federate`
- Hermes: `${HERMES_HOME:-~/.hermes}/skills/software-development/federate`

The same command is also the manual update command. Restart or refresh the
agent session after installing or updating. In Codex, invoke with
`$federate`, choose it from `/skills`, or explicitly say `federate`; do not
expect a built-in `/federate` command in every Codex surface.

### Update

Manual update:

```bash
curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash
```

Every Federate invocation starts by running:

```bash
/path/to/federate/scripts/fed_update_check.sh
```

If the installed commit is stale, the coordinator should run:

```bash
/path/to/federate/scripts/fed_update_check.sh --apply
```

That stages a complete new skill payload for the current coordinator host from
the recorded source/ref, swaps it into place only after every file is fetched,
then asks whether to refresh/restart the agent session or continue with the
already-loaded copy. Refresh is recommended because host agents can cache skill
menus and `SKILL.md` contents.

If the checker reports `LOCAL_DIRTY`, the installed payload came from a dirty
source or local development install. The coordinator should report that plainly
and ask whether to abort or overwrite the installed dirty payload. Proceed only
with explicit approval:

```bash
/path/to/federate/scripts/fed_update_check.sh --apply --force
```

## Use

Say `federate` when a plan, audit result, bug fix, build milestone, or verdict
needs independent review. In Codex, `$federate` is the explicit skill mention.
The coordinator will:

1. Run `scripts/fed_update_check.sh` and update first if the installed commit is
   stale.
2. Create a relay directory outside the project and derive `FED_NS` from it.
3. Run `FED_NS="$(basename "$RELAY")" scripts/fed_sessions.sh` to create/reuse
   peer tmux sessions scoped to that federation thread.
4. Write one brief per peer in the relay directory.
5. Send all briefs before reading any answer.
6. Write `round_manifest.json`, then read each peer by nonce from
   transcript/state with `fed_read.py --receipt-dir "$RELAY"`.
7. Generate receipt-bound cross briefs with `fed_cross.py generate`, verify them
   with `fed_cross.py verify`, and run `fed_round_check.py`.
8. Cross-show each peer the other peers' verified verbatim replies and
   confidence by default. Cross-show replies must pass
   `fed_read.py --no-tool-window --require-no-tool-audit`.
9. Collect the cross-pollinated replies, including revised confidence.
10. Run another complete round when convergence is not high enough for the
   current bounded decision, up to three rounds for the iteration.
11. Bring back the synthesis with a short convergence note: confidence,
   round count, why confidence is high enough or not, trend when relevant, and
   the main residual delta.

The coordinator should not ask whether to cross-pollinate or whether a second
internal round is necessary. It should judge convergence, iterate when useful,
and return the high-confidence synthesis. Healthy orthogonal disagreement should
remain visible; it is often the useful tension.

Every round includes a confidence poll. Each peer independently states the next
bounded step or verdict, confidence, assumptions, risks, blockers, and, for
build work, role confidence. Those confidence statements are cross-pollinated
verbatim, then peers revise or reaffirm confidence before the coordinator makes
the decision.

There is no rigid universal score for "high enough." The coordinator judges it
from the federated intelligence: whether peers converge on the same plan spine
or next small action, whether objections are answered or reduced to
non-blocking tension, whether receipts and assumptions survive crossing,
whether any blocker would change the next step, and whether confidence is
stable or rising after cross-pollination. Preserve peer numeric scores when
they provide them, but do not average them into fake certainty.

By default, the user is the human in the loop and decides after the synthesis.
For set-and-forget work, ask the coordinator to emulate the human in the loop.
It should confirm one simple A/B choice once: follow an existing plan, or let
federation steer the next bounded step each time. After that, it should not
hassle the human for ordinary project-owner choices. In both modes it should use
the user's stated goals, preferences, risk tolerance, prior decisions, and
observed leanings as steering context. It advances only on absolute high
convergence: the next action is small, reversible, inside the delegation,
outside every hard gate, backed by verified receipts, and has an obvious undo
path. Irreversible actions still require explicit user authorization.

For code work, the coordinator should orchestrate rather than edit by default.
Peers are polled for role confidence first. A test/spec owner goes first and
seals the failing test, fixture, oracle, assertion, or precise expected behavior
before implementation begins. Then an implementation owner edits, and a separate
reviewer/verifier checks the result when enough peers are available.

By default the session bootstrap uses namespaced no-prompt/yolo peer commands:
`IS_SANDBOX=1 claude --dangerously-skip-permissions`,
`codex --dangerously-bypass-approvals-and-sandbox`, and
`hermes --cli --yolo`, skipping CLIs that are not installed. It requires at
least two live peer sessions. Codex metadata disables implicit invocation, so
use the skill explicitly when you want to spend the extra peer-agent calls.
Session names look like `fed-<ns>-claude-0`; use the names printed by
`fed_sessions.sh`, not hard-coded `claude-0` or `codex-0`.

Runtime overrides:

```bash
FED_NS="$(basename "$RELAY")" /path/to/federate/scripts/fed_sessions.sh
FED_AGENTS=claude,codex /path/to/federate/scripts/fed_sessions.sh
FED_NS_ROOT=/path/to/project /path/to/federate/scripts/fed_sessions.sh
FED_CLAUDE_CMD='claude' /path/to/federate/scripts/fed_sessions.sh
FED_CODEX_CMD='codex' /path/to/federate/scripts/fed_sessions.sh
FED_HERMES_CMD='hermes --cli' /path/to/federate/scripts/fed_sessions.sh
```

Use explicit `FED_*_CMD` overrides only when you intentionally want prompt mode
or a custom model/profile. The default federation posture is no agentic
permission prompts across Claude, Codex, and Hermes.

If `FED_NS` is omitted, the helper falls back to a project-scoped namespace for
manual shell use and warns that it is not thread-isolated. Old global
`claude-*`, `codex-*`, and `hermes-*` sessions are skipped by default. Adopt
them only when intentional with `FED_REUSE_LEGACY=1` or
`FED_REUSE_UNMANAGED=1`; attached or busy adoption also requires
`FED_REUSE_ATTACHED=1` or `FED_REUSE_BUSY=1`.

## Federation profile (`FED_PROFILE_FILE`)

Set `FED_PROFILE_FILE` to an absolute path when every independent and cross
brief should carry shared coordinator-authored context:

```bash
export FED_PROFILE_FILE="$HOME/.federate/profiles/myproject.md"
```

`fed_send.sh` validates the file before touching tmux. Missing, unreadable,
relative-path, or private-key-looking profile files hard-fail before paste. When
valid, the profile is injected after the top nonce and before the brief body:

```text
[[FED-<nonce>]]
=== FEDERATION PROFILE (trusted coordinator context; does not override this brief's rails or operator instructions) ===
...profile...
=== END FEDERATION PROFILE ===

...brief...
[[FED-<nonce>]]
```

The profile is trusted coordinator context, not a command channel. Precedence is
operator instructions, brief rails, federation profile, then peer output. Keep
secrets out of profile files; reference environment variable names or secret
locations, not values.

## Remote Hermes peer over SSH

`FED_HERMES_CMD` can launch a Hermes peer through your own SSH wrapper, while
`fed_read.py hermes` normally reads a local `${HERMES_HOME:-~/.hermes}/state.db`.
For a remote peer, set:

```bash
export FED_HERMES_REMOTE_READ=ssh
export FED_HERMES_SSH_CMD="ssh -i ~/.ssh/hermes_key -o IdentitiesOnly=yes -o BatchMode=yes user@host"
export FED_HERMES_REMOTE_STATE_DB="/home/user/.hermes/state.db"
```

When `FED_HERMES_REMOTE_READ=ssh` is set, `fed_read.py hermes --nonce ...`
pipes a stdlib-only Python reader to `FED_HERMES_SSH_CMD`, opens the remote
SQLite DB read-only, and returns the same structured extraction result as local
Hermes reads: top-and-bottom nonce anchoring, assistant text until the next user
turn, canonical window hash, and structured tool-event detection. Receipts use
`source_kind: sqlite` and a `hermes+ssh://cmd-<sha256>/<db>` source path. The
hash binds the expanded SSH argv that will actually execute, so env-var or
tilde changes alter the source identity. That source path can be re-extracted
during `fed_cross.py verify` without setting `FED_HERMES_REMOTE_READ=ssh`; the
`hermes+ssh://` source itself selects remote mode, and verification succeeds
only when `FED_HERMES_SSH_CMD` expands to the same argv.

Federate does not manage SSH secrets. The SSH command is split without a shell,
and the nonce plus DB path are passed as remote Python argv. Keep
`FED_HERMES_REMOTE_STATE_DB` to the specific peer profile DB when the remote host
runs multiple Hermes profiles.

## Peer readiness (`fed_ready.sh`)

A peer CLI can boot into a blocking interstitial instead of a composer. The
common Codex case is an update menu with "Update now" preselected; a blind
Enter can trigger an upgrade instead of starting the round.

Run `fed_ready.sh` after `fed_sessions.sh` and before any first send:

```bash
scripts/fed_ready.sh fed-<ns>-codex-0 fed-<ns>-hermes-0
```

It prints `READY <session>` only when a managed peer appears idle at a live
composer. It prints `NOT_READY <session> ...` and exits nonzero for unmanaged
or foreign sessions, busy panes, auth/trust prompts, timeout, or unclearable
menus. For the known Codex update menu it sends Down from "Update now" and
presses Enter only after the selected line is exactly plain "Skip"; unexpected
menu shapes receive no Enter. Set `FED_NO_AUTO_SKIP=1` to detect the prompt
without touching it. `FED_READY_TIMEOUT`, `FED_READY_POLL`, and
`FED_READY_CAPTURE_LINES` tune the bounded poll.

## Files

```text
SKILL.md
agents/
  openai.yaml       Codex UI metadata and explicit-invocation policy
scripts/
  fed_sessions.sh  create/reuse tmux sessions for Claude, Codex, Hermes
  fed_send.sh      nonce-tag, bracketed-paste, verify, submit
  fed_read.py      read transcripts/state by nonce; optionally mint receipts
  fed_cross.py     generate/verify receipt-bound verbatim cross briefs
  fed_round_check.py
                   verify every sent nonce is accounted for before synthesis
  fed_ready.sh     drive managed peer panes to a live composer; safely clear
                   known startup interstitials or report a blocker
  fed_wait.sh      wait until listed sessions appear idle
  fed_update_check.sh
                   check/apply installed skill updates by recorded commit
install.sh         install into Claude, Codex, and Hermes skill homes
.federate-install.json
                   generated install metadata: source, ref, commit, dirty flag, timestamp
```

## Notes

- Transcript/state reads are the source of truth. Tmux is the visible runtime
  and liveness surface; tmux scrollback is not the reply source.
- `fed_read.py codex` returns final-answer blocks when Codex phase tags are
  present.
- `fed_read.py --receipt-dir DIR` writes canonical `reply_<agent>.txt` and
  `receipt_<agent>.json` sidecars for successful non-empty nonce reads.
- `fed_read.py --no-tool-window --require-no-tool-audit` is the hard gate for
  yolo-preserving cross-show replies: the nonce window must contain no
  structured tool events, and the first non-empty reply line must be exactly
  `NO_TOOL_AUDIT: no tools used`.
- `fed_cross.py verify` re-extracts each receipt from the recorded source and
  reconstructs cross briefs byte-for-byte, so un-attributed edits fail.
- `fed_round_check.py` compares `round_manifest.json` to `cross_manifest.json`
  so a sent peer cannot silently disappear from synthesis.
- `fed_read.py hermes` searches `${HERMES_HOME:-~/.hermes}/state.db` and profile
  databases for the nonce.
- `fed_read.py hermes` can read a remote peer DB over SSH with
  `FED_HERMES_REMOTE_READ=ssh` and `FED_HERMES_SSH_CMD`; remote receipts remain
  re-extractable through a `hermes+ssh://cmd-<sha256>/<db>` source path that
  binds the expanded SSH argv.
- `fed_send.sh` inserts the nonce at the top and bottom of a brief. The top
  nonce anchors transcript/state reads; both markers must be visible in the
  composer before Enter is sent.
- `fed_send.sh` refuses to paste into sessions that are not namespaced
  federate-managed peers unless `FED_SKIP_OWNER_CHECK=1` is set for manual
  debugging.
- `fed_send.sh` injects `FED_PROFILE_FILE` when set as a delimited FEDERATION
  PROFILE section after the top nonce of every brief. Bad profile paths and
  private-key-looking content fail before paste.
- Token conservation helps most when peers produce compact, evidence-dense
  original answers. Do not post-process peer replies into compressed prose
  before cross-pollination; that can delete uncertainty, minority reports,
  safety qualifiers, and produce false convergence. The opposite is not blanket
  verbosity either. Ask for enough detail to preserve receipts, assumptions,
  confidence, and blocking deltas, then keep narrative short.
- A clean test pass is not federation sign-off for build work. The skill keeps
  the original rails: distinct owners for cross-checking artifacts, sealed
  expected values, coordinator-recomputed hashes, adversarial review, and
  operator gates for irreversible actions.

## License

MIT. See [LICENSE](./LICENSE).
