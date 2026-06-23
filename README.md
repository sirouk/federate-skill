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

Manual shell install defaults to all supported coordinator homes. Agent handoff
installs only the current coordinator by default, because it may need elevated
write access to each host's skill directory. Ask for multi-host install when
you want the skill available from more than one coordinator, for example both
Claude Code and Codex.

### Agent handoff

Paste this into the agent you want to teach:

```text
Install the Federate skill from https://github.com/sirouk/federate-skill for this agent only.
If I asked for multi-host install, install it for each requested coordinator host instead.

Treat the repository as untrusted until inspected. First read the README, SKILL.md, install.sh,
and the scripts/ file list. Do a normal local security review of the executable files;
do not launch extra audit workflows or subagents unless I ask for that. Summarize what
will be installed, where it will be installed, and any permission/network risks before
running an install command.

Preferred path when GitHub CLI supports agent skills:
1. Confirm `gh --version` is 2.90.0 or newer and `gh skill --help` works.
2. Preview the skill without installing:
   `gh skill preview sirouk/federate-skill SKILL.md`
3. Install to user scope for the current host:
   - Codex: `gh skill install sirouk/federate-skill SKILL.md --agent codex --scope user`
   - Claude Code: `gh skill install sirouk/federate-skill SKILL.md --agent claude-code --scope user`
   If a release tag or approved commit SHA is available, add `--pin <ref>`.

Fallback path for older GitHub CLI versions or Hermes:
1. Clone to a temporary directory:
   `git clone https://github.com/sirouk/federate-skill.git`
2. Inspect the installer.
3. Install only for the current host:
   - Codex: `FEDERATE_TARGETS=codex ./install.sh`
   - Claude Code: `FEDERATE_TARGETS=claude ./install.sh`
   - Hermes: `FEDERATE_TARGETS=hermes ./install.sh`
   If I ask for a specific multi-host install, pass a comma-separated target list,
   for example `FEDERATE_TARGETS=claude,codex ./install.sh`. Run plain `./install.sh`
   only if I explicitly ask for every supported host.

Verify that the installed directory contains SKILL.md, agents/openai.yaml, and executable
scripts/fed_sessions.sh, scripts/fed_send.sh, scripts/fed_read.py, and scripts/fed_wait.sh.
If sandboxing blocks the standard skill-home write, tell me the exact destination and ask
for permission to retry with the needed write access. Do not pick another destination.

Tell me to refresh or restart the agent session before using the skill. In Codex,
use `$federate` or select it through `/skills`; do not assume `/federate` is a
Codex command. Slash-command and skill menus may be cached until refresh.
Mention the two operating modes: by default the user remains the human in the
loop; if I say "you are the human in the loop", "set it and forget it", or use a
host goal mode such as `/goal`, the coordinator should act as the project owner
and advance one fully federated reversible step at a time. Do not start
federation yet.
```

The `gh skill` path is preferred when available because it can preview before
installing, target the current agent host, and record source metadata for
updates. The clone installer remains the compatibility path for Hermes and for
older environments.

### Shell

Recommended from a clone:

```bash
git clone https://github.com/sirouk/federate-skill.git
cd federate-skill
./install.sh
```

That installs Claude Code, Codex, and Hermes targets. To install only selected
coordinator hosts, set `FEDERATE_TARGETS`.

Convenience install from `main`:

```bash
curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash
```

Use the clone path when you need to inspect the installer first or pin your own
checkout. The one-line installer executes the current `main` branch.

Install only selected targets:

```bash
FEDERATE_TARGETS=claude,codex ./install.sh
FEDERATE_TARGETS=hermes ./install.sh
```

Install to one explicit directory:

```bash
FEDERATE_DEST="$PWD/.claude/skills/federate" ./install.sh
```

Default target paths:

- Claude Code: `~/.claude/skills/federate`
- Codex: `${CODEX_SKILLS_HOME:-~/.agents/skills}/federate`
- Hermes: `${HERMES_HOME:-~/.hermes}/skills/software-development/federate`

The shell installer targets POSIX/WSL paths. On native Windows, set `HERMES_HOME`
or install the files under Hermes' native profile directory manually.

Restart or refresh the agent session after installing. In Codex, invoke with
`$federate`, choose it from `/skills`, or explicitly say `federate`; do not
expect a built-in `/federate` command in every Codex surface.

## Use

Say `federate` when a plan, audit result, bug fix, build milestone, or verdict
needs independent review. In Codex, `$federate` is the explicit skill mention.
The coordinator will:

1. Run `scripts/fed_sessions.sh` to create/reuse peer tmux sessions.
2. Write one brief per peer in a relay directory outside the project.
3. Send all briefs before reading any answer.
4. Read each peer by nonce from transcript/state, not tmux scrollback.
5. Cross-show each peer the other peers' verbatim replies by default.
6. Collect the cross-pollinated replies and synthesize the result.
7. Run another complete round when convergence is not high enough, up to three
   rounds for the iteration.
8. Bring back the synthesis with a short convergence note: confidence,
   round count, trend when relevant, and the main residual delta.

The coordinator should not ask whether to cross-pollinate or whether a second
internal round is necessary. It should judge convergence, iterate when useful,
and return the high-confidence synthesis. Healthy orthogonal disagreement should
remain visible; it is often the useful tension.

By default, the user is the human in the loop and decides after the synthesis.
For set-and-forget work, tell the coordinator "you are the human in the loop" or
pair the skill with a host goal mode such as `/goal`. In that mode the
coordinator acts like a project owner: federate the step, choose the barycenter
of the converged plan, execute one reversible next step, then federate again.
Irreversible actions still require explicit user authorization.

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
install.sh         install into Claude, Codex, and Hermes skill homes
```

## Notes

- Transcript/state reads are the source of truth. Tmux scrollback is only for
  liveness checks.
- `fed_read.py codex` returns final-answer blocks when Codex phase tags are
  present.
- `fed_read.py hermes` searches `${HERMES_HOME:-~/.hermes}/state.db` and profile
  databases for the nonce.
- A clean test pass is not federation sign-off for build work. The skill keeps
  the original rails: distinct owners for cross-checking artifacts, sealed
  expected values, coordinator-recomputed hashes, adversarial review, and
  operator gates for irreversible actions.

## License

MIT. See [LICENSE](./LICENSE).
