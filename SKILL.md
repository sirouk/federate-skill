---
name: federate
description: Run the 4-party "Federation & Synthesis of intelligence" loop. Relay a decision / plan / audit / bug-fix / build-milestone between a tmux Claude and a tmux Codex — ask both INDEPENDENTLY, then CROSS-POLLINATE (each sees the other), then digest the convergence and bring it to the operator to decide. Invoke whenever the user says "federate" (or "fed-synth" / "federation"), or at any consequential decision, plan, audit, bug fix, build milestone, or verdict where independent expert review + synthesis should drive the next step.
---

# Federate — Federation & Synthesis of Intelligence

Four minds think together on every consequential step; the best move emerges from their **convergence**:

1. **Claude** — a tmux session (`claude-*`).
2. **Codex** — a tmux session (`codex-*`).
3. **Coordinator** — YOU, the agent running this skill. You **bridge, judge, score, guide** — never rule alone.
4. **Operator** — the user. The **fourth voice and the decider**: they choose the next step, with your best advice.

You relay each party's **actual words** (verbatim; add your framing as a clearly separate layer, never distort or summarize *into* the relay). You score convergence and bring the synthesis to the operator. **Anything YOU discover is an input routed through the loop, never a solo verdict.** Move in **lockstep** every round: keep both agents on the **rails** (state the constraints each hop) and **informed** (always relay the other's real response). The two loaded sessions are a live pool of deep intelligence — not tools.

## When to invoke
The user says "federate," **or** you reach a decision / plan / audit / bug-fix / build-milestone / verdict that deserves independent review + synthesis. One invocation = **one full round** on the current state + the last results from both agents.

**Decision vs Build (pick the track in step 0):**
- **DECISION / PLAN / AUDIT / verdict** → run the 4-step loop, stop at the operator.
- **BUILD / fix / milestone** → run the loop **and** apply the build rails: score & split work-packages with one accountable owner each; route two *cross-checking* packages (spec↔impl, oracle↔engine) to **different** owners; the non-implementer **seals** the oracle/expected-values to YOU before the build; you hold neutral SHA-256 custody; trust is gated behind a fixture/Gate-1 cross-check **and** a pre-agreed adversarial code-review — *a clean test pass is not sign-off.* (See **Rails**.)

---

## Setup (once per thread)

```bash
~/.claude/skills/federate/scripts/fed_sessions.sh    # reuses claude-* / codex-*; else creates claude-0 / codex-0 (wide panes)
```
- It prints `CLAUDE_SESSION=…` and `CODEX_SESSION=…`. **Read those and substitute the LITERAL names** (e.g. `claude-0`, `codex-0`) into every command below — *shell variables do NOT persist between tool calls.* (Prefer the operator's existing tuned session, e.g. `codex-1`, over a fresh one.)
- New sessions launch with: claude-0 = `IS_SANDBOX=1 claude --dangerously-skip-permissions`; codex-0 = `codex --dangerously-bypass-approvals-and-sandbox`.
- **Boot-gate:** if it printed `CREATED`, the CLIs are still booting and a not-yet-started pane reads as *idle* (false). Wait ~10s, then confirm each composer is live: `tmux capture-pane -t claude-0 -p | tail -5` (a prompt box, not a boot screen) before the first send. If `fed_send` prints `ERROR: paste not detected`, the session isn't ready — wait and retry; treat an empty nonce as a **failed send** and do not proceed to read.
- **Workspace (absolute paths — the harness resets CWD between calls):**
```bash
RELAY=~/relay/$(date +%Y%m%d_%H%M%S); mkdir -p "$RELAY"   # do this ONCE; then use the literal path, e.g. /root/relay/20260622_201500
```
Write all briefs and the ledger here. **Never** write relay artifacts into the project under audit.

---

## A federation round (the core loop)

### 0 · Frame
Decide the **object** (decision / plan / audit-finding / fix-set / milestone / verdict) and write a brief **per recipient** (byte-identical except the salutation name) to `$RELAY/`. Every brief, in order:
- **(a) FRAME** — where we are + the exact object.
- **(b) RAILS** — read-only vs build, what is frozen/sealed/gated; re-stamp the standing constraint as a literal line (e.g. *"Still NO code"*). Crossing a phase boundary (plan→code, design→build, build→irreversible-run) needs an **explicit operator signature in the ledger**, never your inference.
- **(c) GROUNDING** — verified receipts / file refs (things you re-derived yourself).
- **(d) ASK** — tight 2–3 parts; the last part = the single biggest question for the other agent / operator.

If **you** discovered the object (a file, a bug, a reframe), it is still just an input: make it the brief and send it to **both**, do not pre-rule on it.

### 1 · Independent (send to BOTH before reading EITHER)
```bash
# substitute the real session names + the real $RELAY path
NC=$(~/.claude/skills/federate/scripts/fed_send.sh claude-0 /root/relay/STAMP/brief_claude.md)   # STDOUT = bare nonce
NX=$(~/.claude/skills/federate/scripts/fed_send.sh codex-0  /root/relay/STAMP/brief_codex.md)
echo "NC=$NC NX=$NX"   # record both; a FRESH nonce is minted per send — never reuse one
```
Then wait, **in the background**, and let the harness re-invoke you:
```bash
~/.claude/skills/federate/scripts/fed_wait.sh claude-0 codex-0   # run with run_in_background:true
```
On `ALL_IDLE`, read each **verbatim from the transcript** (not the pane) with that hop's nonce:
```bash
~/.claude/skills/federate/scripts/fed_read.py claude --nonce "$NC"
~/.claude/skills/federate/scripts/fed_read.py codex  --nonce "$NX"
```
**Sanity-check each read** before using it: it must be a real answer — not a placeholder ("running a workflow / let me…"), not your own brief echoed back, and the `[fed_read …] <path>` stderr line must point at the expected session. *If it's a placeholder, the agent spawned its own sub-task and went pane-idle while still working* — re-launch `fed_wait`, re-read with the **same** nonce after the next idle, repeat until it's a real answer. A `nonce NOT FOUND` error means it hasn't replied yet — wait, don't fall back.

### 2 · Cross-pollinate (the load-bearing hop — do not skip)
Write `$RELAY/cross_claude.md` = Codex's **verbatim** `fed_read` turn under a labelled block (`=== CODEX (verbatim) ===`) + your framing as a **separate** section + a tight "confirm / dispute / reconcile" ask. Mirror for Codex. **Never summarize the other's content into the brief** — your paraphrase is for the operator only (step 3). When the two artifacts cross-check each other (spec↔impl, oracle↔engine), this is where each reviews the other's **actual work**.
```bash
NC2=$(~/.claude/skills/federate/scripts/fed_send.sh claude-0 /root/relay/STAMP/cross_claude.md)   # FRESH nonce
NX2=$(~/.claude/skills/federate/scripts/fed_send.sh codex-0  /root/relay/STAMP/cross_codex.md)
# background fed_wait, then:
~/.claude/skills/federate/scripts/fed_read.py claude --nonce "$NC2"
~/.claude/skills/federate/scripts/fed_read.py codex  --nonce "$NX2"
```
**Only** note-and-skip the cross-show if the two independent replies are byte-identical AND there are no cross-checkable artifacts — and even then, tell the operator you skipped and why. (In the origin thread the cross-show produced the headline result — a beta-residualization GO criterion — even from ~9.8/10-convergent inputs; the one hop it was skipped had to be recovered later.)

### 3 · Synthesize
Digest both into a verdict for the operator:
- a **convergence score** tracked across rounds (e.g. 8.5 → 9 → 9.8) with an explicit **residual-deltas** list; weight *independent, pre-cross-show* agreement most;
- **agreements** (the spine) vs **deltas** (what still needs reconciling);
- the **questions only the operator can answer** (don't invent defaults for genuine operator decisions; carry each agent's operator-question distinctly);
- your **best advice**, grounded in the convergence.
**LOCK** is reached only when both agents accept each other with no genuine disagreement and state the **same** one-line verdict. Flat/falling score or open deltas → run another bridging hop.

### 4 · Operator decides
Bring the synthesis to the operator; they pick the next step. Then the next round starts there.

---

## Mechanics — use the scripts (every line below was learned the hard way)
- **Clean source = TRANSCRIPTS, never tmux scrollback** (scrollback is garbled by tool redraws/wrapping). `fed_read.py` pulls the verbatim turn from the active transcript, found by the **nonce** `fed_send` injects. The pane is **only** for liveness.
- **The nonce is essential for BOTH agents.** `fed_read` globs *all* Claude projects and *all* Codex sessions; without the nonce it falls back to the most-recent transcript — which for Claude is normally the **coordinator's OWN** session. A supplied-but-unmatched nonce **fails loud** (agent hasn't replied).
- **Codex tags assistant blocks `payload.phase ∈ {commentary, final_answer}`.** `fed_read` returns **final_answer only** — relaying Codex's internal `commentary` would corrupt the cross-show and the convergence score.
- **Send = bracketed paste + a SEPARATE Enter** (`fed_send.sh`): it stages the paste, **confirms it landed (the confirm chrome DIFFERS between the Claude and Codex TUIs — the script checks both, plus a composer-grew test)**, then sends Enter alone; on failure it **clears the staged buffer** and exits. Never embed Enter in the paste.
- **Liveness = `fed_wait.sh`** (run in background). Busy markers include the **truncated** `esc to int…`, `Working (`, `thinking with`, `background terminal runni`; ≥2 idle polls. **Gotcha:** an agent that spawns its OWN sub-workflow goes pane-idle while still working — don't trust pane-idle alone; confirm the transcript turn is a real answer (step 1 sanity-check).

## The rails (discipline that keeps four minds coherent)
- **Living ledger.** Keep `$RELAY/relay_log.md`: every hop, decision, hash, score, verdict. It is the project's memory and the convergence trail.
- **Neutral hash custody.** After EVERY change to a frozen artifact, `sha256sum` it **yourself**, confirm *coordinator-recomputed == author-claimed*, and re-finalize the registry. Never trust a printed hash. An object that changed without a re-hash has silently lost custody.
- **Independence + the transitive seal.** When two artifacts cross-check (spec↔impl, oracle↔engine): different authors; the non-implementer **seals expected-values to YOU before the builder writes a line**; the builder builds **blind** and **flags** (never silently matches) any disagreement. Verify `Gate-1[impl==EXPECTED] + seal[EXPECTED==oracle] ⇒ impl==oracle`. Their independent convergence IS the validation.
- **Verify, don't trust.** Re-derive load-bearing claims, hashes, and file/line refs yourself. (Origin thread: blind trust produced a false "18:40 UTC" and a false `None`; independent re-derivation caught both.)
- **Adversarial swarms (Workflow tool) at two moments — mandatory, not optional:** (a) **stress-test** a converged plan *before any code*; (b) **red-team built code before audit-scale trust, even if an automated gate already passed.** Line-ground every finding against the frozen contract and **classify by verdict-direction — a bug that biases toward the favorable/GO outcome is the dangerous class.** (Origin: an **11/11** fixture-gate pass hid **22** real bugs, several false-GO-biased; the **24/24** came only after the fix cycle.) Then **federate the swarm verdict** — run it back through a full independent→cross-show round so each agent verifies the findings against its OWN artifact and owns its own bugs. *Reserve swarms for review/stress — never to build a coherence-critical single-owner artifact.*
- **Fix-cycle (when a review finds bugs):** (1) the oracle author pins the decided rules in the frozen spec and authors NEW sealed fixtures per fix **without seeing the fixed code**; (2) you re-hash the amended spec + new sealed oracle; (3) the builder applies the fixes; (4) re-run the gate on the **full** fixture set (old + new — guards regression); (5) you re-hash impl + results, re-finalize the registry.
- **Work-package assignment by federation.** Enumerate packages; both agents independently **score fit**; lock a conflict-free assignment; cross-checking packages → different owners; you own the neutral packages (lock, registry, ledger); the operator signs.
- **Gate irreversible steps.** One-shot evaluations, deploys, external sends — behind explicit operator signature **and** a prior adversarial review.
- **Pre-register / freeze before results.** Lock methodology + thresholds, hash them, get operator sign-off, *then* look. Split any result-bearing data into a **discovery** region (look freely) and a **sealed holdout opened exactly once** for the final verdict. Pre-commit a **GO / NARROW / INCONCLUSIVE / KILL** taxonomy + a power floor (underpowered sealed evidence = **INCONCLUSIVE**, not KILL).

## Cadence
Lockstep, every round. Relay the other's actual words (not your paraphrase). Re-stamp the constraints each hop. Keep your findings as inputs, not rulings. The operator is the fourth voice and the decider — your job is to make the convergence *and the genuine disagreements* legible, and to advise.

## Files this skill provides
- `scripts/fed_sessions.sh` — detect/create the two tmux sessions (wide panes); prints `*_SESSION=`.
- `scripts/fed_send.sh <session> <ABSOLUTE-msgfile>` — nonce-tag + bracketed-paste + dual-TUI verify + separate Enter; STDOUT = bare nonce.
- `scripts/fed_read.py <claude|codex> --nonce N` — verbatim answer from the active transcript (Codex final_answer only; fails loud on unmatched nonce).
- `scripts/fed_wait.sh <session...>` — background monitor until all idle (robust truncation-aware busy patterns).
