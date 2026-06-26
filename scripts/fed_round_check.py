#!/usr/bin/env python3
"""fed_round_check.py — verify that every sent federation nonce is accountable."""
import argparse
import json
import sys
from pathlib import Path


class UsageError(Exception):
    pass


class CheckError(Exception):
    pass


def read_json(path, err_cls=UsageError):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise err_cls(f"failed to read JSON {path}: {e}")


def resolve_relay_path(relay, value):
    if not isinstance(value, str) or not value:
        raise CheckError("evidence/receipt path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = relay / path
    return path


def load_manifests(relay):
    round_path = relay / "round_manifest.json"
    cross_path = relay / "cross_manifest.json"
    if not round_path.is_file():
        raise UsageError(f"missing round manifest: {round_path}")
    if not cross_path.is_file():
        raise UsageError(f"missing cross manifest: {cross_path}")
    round_manifest = read_json(round_path)
    cross_manifest = read_json(cross_path)
    if round_manifest.get("schema") != "federate.round_manifest.v1":
        raise UsageError("unsupported round manifest schema")
    if cross_manifest.get("schema") != "federate.cross_manifest.v1":
        raise UsageError("unsupported cross manifest schema")
    return round_manifest, cross_manifest


def expected_map(round_manifest):
    expected = round_manifest.get("expected")
    if not isinstance(expected, dict) or not expected:
        raise UsageError("round_manifest.expected must be a non-empty object keyed by nonce")
    by_agent = {}
    for nonce, info in expected.items():
        if not isinstance(nonce, str) or not nonce.startswith("FED-"):
            raise UsageError(f"invalid expected nonce: {nonce!r}")
        if not isinstance(info, dict):
            raise UsageError(f"expected entry for {nonce} must be an object")
        agent = info.get("agent")
        if not isinstance(agent, str) or not agent:
            raise UsageError(f"expected entry for {nonce} missing agent")
        if agent in by_agent:
            raise UsageError(f"duplicate expected agent: {agent}")
        by_agent[agent] = nonce
    return expected, by_agent


def validate_receipt(relay, agent, source):
    receipt_path = resolve_relay_path(relay, source.get("receipt_path"))
    if not receipt_path.is_file():
        raise CheckError(f"source receipt missing for {agent}: {receipt_path}")
    receipt = read_json(receipt_path, CheckError)
    if receipt.get("schema") != "federate.read_receipt.v1":
        raise CheckError(f"receipt schema invalid for {agent}")
    if receipt.get("agent") != agent:
        raise CheckError(f"receipt agent mismatch for {agent}: {receipt.get('agent')!r}")
    if receipt.get("nonce") != source.get("nonce"):
        raise CheckError(f"receipt nonce mismatch for {agent}")
    return receipt


def account_sources(relay, cross_manifest, expected):
    sources = cross_manifest.get("sources")
    if not isinstance(sources, dict):
        raise CheckError("cross_manifest.sources must be an object")
    accounted = {}
    for agent, source in sources.items():
        if not isinstance(source, dict):
            raise CheckError(f"source entry for {agent} must be an object")
        nonce = source.get("nonce")
        if nonce not in expected:
            raise CheckError(f"unknown source nonce {nonce!r} for {agent}")
        expected_agent = expected[nonce].get("agent")
        if expected_agent != agent:
            raise CheckError(
                f"source agent mismatch for nonce {nonce}: expected {expected_agent}, got {agent}"
            )
        validate_receipt(relay, agent, source)
        if nonce in accounted:
            raise CheckError(f"nonce accounted more than once: {nonce}")
        accounted[nonce] = f"source:{agent}"
    return sources, accounted


def account_unavailable(relay, cross_manifest, expected, accounted):
    unavailable = cross_manifest.get("unavailable", [])
    if unavailable is None:
        unavailable = []
    if not isinstance(unavailable, list):
        raise CheckError("cross_manifest.unavailable must be a list")
    for entry in unavailable:
        if not isinstance(entry, dict):
            raise CheckError("unavailable entries must be objects")
        nonce = entry.get("nonce")
        if nonce not in expected:
            raise CheckError(f"unknown unavailable nonce {nonce!r}")
        expected_agent = expected[nonce].get("agent")
        if entry.get("agent") != expected_agent:
            raise CheckError(
                f"unavailable agent mismatch for nonce {nonce}: expected {expected_agent}"
            )
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise CheckError(f"unavailable nonce {nonce} missing reason")
        evidence_path = resolve_relay_path(relay, entry.get("evidence_path"))
        if not evidence_path.is_file() or evidence_path.stat().st_size == 0:
            raise CheckError(f"unavailable nonce {nonce} evidence missing or empty: {evidence_path}")
        if nonce in accounted:
            raise CheckError(f"nonce accounted more than once: {nonce}")
        accounted[nonce] = f"unavailable:{expected_agent}"


def validate_cross_blocks(cross_manifest, sources, expected):
    peers = cross_manifest.get("peers")
    if not isinstance(peers, list) or not all(isinstance(p, str) for p in peers):
        raise CheckError("cross_manifest.peers must be a list of source agents")
    if set(peers) != set(sources):
        raise CheckError("cross_manifest sources must match peers")
    cross_files = cross_manifest.get("cross_files")
    if not isinstance(cross_files, dict):
        raise CheckError("cross_manifest.cross_files must be an object")
    if set(cross_files) != set(peers):
        raise CheckError("cross_manifest cross_files must match peers")
    for receiver, cf in cross_files.items():
        if not isinstance(cf, dict):
            raise CheckError(f"cross file entry for {receiver} must be an object")
        if cf.get("receiver", receiver) != receiver:
            raise CheckError(f"cross file receiver mismatch for {receiver}")
        blocks = cf.get("blocks")
        if not isinstance(blocks, list):
            raise CheckError(f"cross file blocks missing for {receiver}")
        seen = set()
        for block in blocks:
            if not isinstance(block, dict):
                raise CheckError(f"block entry for {receiver} must be an object")
            source = block.get("source")
            if source == receiver:
                raise CheckError(f"receiving agent {receiver} has its own source block")
            if source not in sources:
                raise CheckError(f"block source {source!r} for {receiver} is not in sources")
            source_nonce = sources[source].get("nonce")
            if source_nonce not in expected:
                raise CheckError(f"unknown source nonce {source_nonce!r} in block {source}->{receiver}")
            if source in seen:
                raise CheckError(f"duplicate source block {source}->{receiver}")
            seen.add(source)
        expected_sources = set(peers) - {receiver}
        missing = sorted(expected_sources - seen)
        if missing:
            raise CheckError(f"missing source block(s) for {receiver}: {', '.join(missing)}")
        extra = sorted(seen - expected_sources)
        if extra:
            raise CheckError(f"unexpected source block(s) for {receiver}: {', '.join(extra)}")


def check_round(relay):
    round_manifest, cross_manifest = load_manifests(relay)
    expected, _ = expected_map(round_manifest)
    sources, accounted = account_sources(relay, cross_manifest, expected)
    account_unavailable(relay, cross_manifest, expected, accounted)
    validate_cross_blocks(cross_manifest, sources, expected)
    for nonce, info in expected.items():
        if nonce not in accounted:
            raise CheckError(f"expected nonce {nonce} ({info.get('agent')}) not accounted")
    return accounted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay", required=True)
    args = ap.parse_args()
    relay = Path(args.relay).expanduser()
    if not relay.is_dir():
        sys.stderr.write(f"ERROR: relay directory not found: {relay}\n")
        sys.exit(2)
    try:
        accounted = check_round(relay)
    except UsageError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(2)
    except CheckError as e:
        sys.stderr.write(f"ROUND CHECK FAILED: {e}\n")
        sys.exit(3)
    print(f"OK accounted={len(accounted)}")


if __name__ == "__main__":
    main()
