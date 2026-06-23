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

One command installs the skill into the default user skill homes for Claude
Code, Codex, and Hermes:

```bash
curl -fsSL https://raw.githubusercontent.com/sirouk/federate-skill/main/install.sh | bash
```

From a clone:

```bash
git clone https://github.com/sirouk/federate-skill.git
cd federate-skill
./install.sh
```

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
- Codex: `${CODEX_HOME:-~/.codex}/skills/federate`
- Hermes: `${HERMES_HOME:-~/.hermes}/skills/software-development/federate`

Restart or refresh the agent session after installing, then say `federate`.

## Use

Say `federate` when a plan, audit result, bug fix, build milestone, or verdict
needs independent review. The coordinator will:

1. Run `scripts/fed_sessions.sh` to create/reuse peer tmux sessions.
2. Write one brief per peer in a relay directory outside the project.
3. Send all briefs before reading any answer.
4. Read each peer by nonce from transcript/state, not tmux scrollback.
5. Cross-show each peer the other peers' verbatim replies.
6. Score convergence and bring agreements, deltas, and advice to the operator.

By default the session bootstrap tries `claude`, `codex`, and `hermes`, skipping
CLIs that are not installed. It requires at least two live peer sessions.

Runtime overrides:

```bash
FED_AGENTS=claude,codex /path/to/federate/scripts/fed_sessions.sh
FED_CLAUDE_CMD='claude --dangerously-skip-permissions' /path/to/federate/scripts/fed_sessions.sh
FED_CODEX_CMD='codex --dangerously-bypass-approvals-and-sandbox' /path/to/federate/scripts/fed_sessions.sh
FED_HERMES_CMD='hermes --cli --yolo' /path/to/federate/scripts/fed_sessions.sh
```

## Files

```text
SKILL.md
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
