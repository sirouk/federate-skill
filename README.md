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
and creates missing peer sessions automatically.

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
scripts/fed_send.sh, scripts/fed_read.py, scripts/fed_wait.sh, and
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

That updates the installed skill payload for the current coordinator host from
the recorded source/ref, then asks whether to refresh/restart the agent session
or continue with the already-loaded copy. Refresh is recommended because host
agents can cache skill menus and `SKILL.md` contents.

## Use

Say `federate` when a plan, audit result, bug fix, build milestone, or verdict
needs independent review. In Codex, `$federate` is the explicit skill mention.
The coordinator will:

1. Run `scripts/fed_update_check.sh` and update first if the installed commit is
   stale.
2. Run `scripts/fed_sessions.sh` to create/reuse peer tmux sessions.
3. Write one brief per peer in a relay directory outside the project.
4. Send all briefs before reading any answer.
5. Read each peer by nonce from transcript/state, not tmux scrollback.
6. Cross-show each peer the other peers' verbatim replies and confidence by
   default.
7. Collect the cross-pollinated replies, including revised confidence.
8. Run another complete round when convergence is not high enough, up to three
   rounds for the iteration.
9. Bring back the synthesis with a short convergence note: confidence,
   round count, trend when relevant, and the main residual delta.

The coordinator should not ask whether to cross-pollinate or whether a second
internal round is necessary. It should judge convergence, iterate when useful,
and return the high-confidence synthesis. Healthy orthogonal disagreement should
remain visible; it is often the useful tension.

Every round includes a confidence poll. Each peer independently states the next
bounded step or verdict, confidence, assumptions, risks, blockers, and, for
build work, role confidence. Those confidence statements are cross-pollinated
verbatim, then peers revise or reaffirm confidence before the coordinator makes
the decision.

By default, the user is the human in the loop and decides after the synthesis.
For set-and-forget work, ask the coordinator to emulate the human in the loop.
It should first confirm one of two modes: follow an existing plan, or let
federation steer the next bounded step each time. In both modes it should use
the user's stated goals, preferences, risk tolerance, prior decisions, and
observed leanings as steering context. Irreversible actions still require
explicit user authorization.

For code work, the coordinator should orchestrate rather than edit by default.
Peers are polled for role confidence first. A test/spec owner goes first and
seals the failing test, fixture, oracle, assertion, or precise expected behavior
before implementation begins. Then an implementation owner edits, and a separate
reviewer/verifier checks the result when enough peers are available.

By default the session bootstrap tries `claude`, `codex`, and
`hermes --cli --yolo`, skipping CLIs that are not installed. It requires at
least two live peer
sessions. Codex metadata disables implicit invocation, so use the skill
explicitly when you want to spend the extra peer-agent calls.

Runtime overrides:

```bash
FED_AGENTS=claude,codex /path/to/federate/scripts/fed_sessions.sh
FED_CLAUDE_CMD='claude --dangerously-skip-permissions' /path/to/federate/scripts/fed_sessions.sh
FED_CODEX_CMD='codex --dangerously-bypass-approvals-and-sandbox' /path/to/federate/scripts/fed_sessions.sh
FED_HERMES_CMD='hermes --cli' /path/to/federate/scripts/fed_sessions.sh
FEDERATE_UNSAFE=1 /path/to/federate/scripts/fed_sessions.sh
```

Hermes defaults to `--yolo` for federation. Use `FED_HERMES_CMD='hermes --cli'`
when you want Hermes approval prompts. Use Claude/Codex bypass modes only inside
an external sandbox with no secrets or irreversible access.

## Files

```text
SKILL.md
agents/
  openai.yaml       Codex UI metadata and explicit-invocation policy
scripts/
  fed_sessions.sh  create/reuse tmux sessions for Claude, Codex, Hermes
  fed_send.sh      nonce-tag, bracketed-paste, verify, submit
  fed_read.py      read Claude/Codex transcripts or Hermes state.db by nonce
  fed_wait.sh      wait until listed sessions appear idle
  fed_update_check.sh
                   check/apply installed skill updates by recorded commit
install.sh         install into Claude, Codex, and Hermes skill homes
.federate-install.json
                   generated install metadata: source, ref, commit, dirty flag, timestamp
```

## Notes

- Transcript/state reads are the source of truth. Tmux scrollback is only for
  liveness checks.
- `fed_read.py codex` returns final-answer blocks when Codex phase tags are
  present.
- `fed_read.py hermes` searches `${HERMES_HOME:-~/.hermes}/state.db` and profile
  databases for the nonce.
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
