# federate

Federate runs a lockstep review loop across two or more peer agents in tmux:
Claude, Codex, and Hermes when installed. The coordinator asks peers
independently, cross-pollinates their verbatim replies, scores convergence, and
brings a synthesis back to the operator for the decision.

The helper scripts handle the fragile parts: creating/reusing tmux sessions,
safe bracketed paste, nonce-based transcript reads, Codex final-answer
extraction, Hermes `state.db` reads, and idle waiting.

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
Codex command. Slash-command and skill menus may be cached until refresh. Do not
start federation yet.
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
5. Cross-show each peer the other peers' verbatim replies.
6. Score convergence and bring agreements, deltas, and advice to the operator.

By default the session bootstrap tries `claude`, `codex`, and `hermes --cli`,
skipping CLIs that are not installed. It requires at least two live peer
sessions. Codex metadata disables implicit invocation, so use the skill
explicitly when you want to spend the extra peer-agent calls.

Runtime overrides:

```bash
FED_AGENTS=claude,codex /path/to/federate/scripts/fed_sessions.sh
FED_CLAUDE_CMD='claude --dangerously-skip-permissions' /path/to/federate/scripts/fed_sessions.sh
FED_CODEX_CMD='codex --dangerously-bypass-approvals-and-sandbox' /path/to/federate/scripts/fed_sessions.sh
FED_HERMES_CMD='hermes --cli --yolo' /path/to/federate/scripts/fed_sessions.sh
FEDERATE_UNSAFE=1 /path/to/federate/scripts/fed_sessions.sh
```

Use bypass/yolo modes only inside an external sandbox with no secrets or
irreversible access.

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
