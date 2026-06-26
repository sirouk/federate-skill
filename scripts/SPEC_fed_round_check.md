# SPEC — Fix D: round-accountability check

Status: SEALED CONTRACT (Fix D). The executable oracle is
`scripts/tests/test_fed_round_check.py`; this file is the human-readable
contract.

`fed_round_check.py --relay <DIR> [--round N]` verifies that every peer nonce
sent in a federation phase is accounted for before synthesis. It closes the
orchestrator-level omission gap where a coordinator could drop an inconvenient
peer from the cross-show and still claim convergence.

## Inputs

`$RELAY/round_manifest.json` is written once immediately after independent
sends and before reads/cross generation. If `--round N` is used, the artifact
directory is `$RELAY/round_N`, so the path is `$RELAY/round_N/round_manifest.json`:

```json
{
  "schema": "federate.round_manifest.v1",
  "round": 1,
  "phase": "independent",
  "created_at": "2026-06-25T14:22:01Z",
  "expected": {
    "FED-uuid1": {
      "agent": "claude",
      "session": "fed-ns-claude-0",
      "sent_at": "2026-06-25T14:22:03Z"
    }
  }
}
```

`$RELAY/cross_manifest.json` is produced by `fed_cross.py generate` and may
also include a top-level `unavailable` list. If `--round N` is used, the path
is `$RELAY/round_N/cross_manifest.json`:

```json
{
  "unavailable": [
    {
      "nonce": "FED-uuid3",
      "agent": "hermes",
      "reason": "timeout",
      "evidence_path": "logs/fed_wait_hermes_timeout.txt"
    }
  ]
}
```

`evidence_path` may be absolute or relative to the artifact directory. It must
exist and be non-empty.

## Check

For every nonce in `round_manifest.expected`, the cross manifest must contain
exactly one of:

- a source receipt under `cross_manifest.sources` whose `nonce` equals the
  expected nonce, whose `receipt_path` exists, and whose receipt JSON has
  matching `schema`, `agent`, and `nonce`;
- an `unavailable` entry with the same nonce, matching agent, non-empty reason,
  and non-empty evidence file.

Additionally:

- every source nonce must appear in `round_manifest.expected`;
- every unavailable nonce must appear in `round_manifest.expected`;
- `cross_manifest.peers` must match the set of source agents exactly;
- `cross_manifest.cross_files` must match the peer set exactly;
- each receiver must have exactly one block for every other source peer and no
  block for itself.

## Exit Codes

- `0`: round is accountable; prints `OK accounted=<n>`.
- `2`: usage or malformed/missing manifest.
- `3`: accountability failure; synthesis must stop.

## Residual

This check makes omission visible and machine-failing. It does not prove an
unavailable reason is truthful; that still requires operator review, stronger
peer-side signing, or out-of-band availability witnesses.
