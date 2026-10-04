#!/usr/bin/env python3
"""Audit and revalidate historical compiler-guidance distillation reports."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_guidance_replay import (  # noqa: E402
    CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT,
    CANONICAL_HISTORICAL_REPORT_COUNT,
    GuidanceInventoryError,
    GuidanceReplayError,
    GuidanceReplayPolicy,
    LegalIRGuidanceReplay,
)


def _load_mapping(path: Path, *, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuidanceReplayError(f"{name} is not valid JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise GuidanceReplayError(f"{name} must contain a JSON object")
    return dict(value)


def _load_trust_store(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = _load_mapping(path, name="trust store")
    raw_signers = payload.get("trusted_signers", payload)
    if not isinstance(raw_signers, Mapping):
        raise GuidanceReplayError("trust store trusted_signers must be an object")
    signers: dict[str, str] = {}
    for signer_id, raw_secret in raw_signers.items():
        if isinstance(raw_secret, Mapping):
            secret = str(raw_secret.get("secret") or "")
        else:
            secret = str(raw_secret or "")
        if not secret:
            raise GuidanceReplayError(
                f"trust store secret is missing for signer {signer_id!r}"
            )
        signers[str(signer_id)] = secret
    return signers


def _receipt_lookup(path: Path | None) -> dict[str, Mapping[str, Any]]:
    if path is None:
        return {}
    payload = _load_mapping(path, name="revalidation receipt bundle")
    raw_receipts: Any = payload.get("receipts", payload)
    receipts: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_receipts, Mapping):
        items = raw_receipts.items()
    elif isinstance(raw_receipts, Sequence) and not isinstance(
        raw_receipts, (str, bytes, bytearray)
    ):
        items = (
            (
                str(
                    receipt.get("report_digest")
                    or receipt.get("candidate_digest")
                    or receipt.get("report_id")
                    or ""
                ),
                receipt,
            )
            for receipt in raw_receipts
            if isinstance(receipt, Mapping)
        )
    else:
        raise GuidanceReplayError(
            "revalidation receipt bundle must contain an object or list"
        )
    for raw_key, raw_receipt in items:
        if not isinstance(raw_receipt, Mapping):
            raise GuidanceReplayError("each revalidation receipt must be an object")
        key = str(raw_key or "").strip()
        if not key:
            raise GuidanceReplayError("revalidation receipt has no report binding")
        receipts[key] = dict(raw_receipt)
    return receipts


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    descriptor = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(descriptor.name)
    try:
        with descriptor:
            descriptor.write(encoded)
            descriptor.flush()
            os.fsync(descriptor.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        required=True,
        help=(
            "Historical report or directory. Directories are searched recursively; "
            "repeat for multiple roots."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination for the source-free, content-addressed replay report.",
    )
    parser.add_argument("--compiler-commit", required=True)
    parser.add_argument("--compiler-schema-version", required=True)
    parser.add_argument("--canonicalization-version", required=True)
    parser.add_argument("--fixed-holdout-id", required=True)
    parser.add_argument("--fixed-holdout-digest", required=True)
    parser.add_argument("--proof-policy-version", required=True)
    parser.add_argument("--provenance-policy-version", required=True)
    parser.add_argument("--source-copy-policy-version", required=True)
    parser.add_argument("--lineage-id", required=True)
    parser.add_argument("--base-state-digest", required=True)
    parser.add_argument(
        "--evaluation-time",
        default="",
        help="ISO-8601 replay time; defaults to the current UTC time.",
    )
    parser.add_argument(
        "--max-report-age-seconds",
        type=float,
        default=180 * 24 * 60 * 60,
    )
    parser.add_argument("--max-feature-deltas", type=int, default=32)
    parser.add_argument(
        "--trust-store",
        type=Path,
        help=(
            "JSON signer-to-secret mapping used to authenticate historical "
            "reports and fresh receipts. Secrets are never serialized."
        ),
    )
    parser.add_argument(
        "--revalidation-receipts",
        type=Path,
        help=(
            "Signed results produced by the current compiler/proof evaluation "
            "pipeline, keyed by historical report digest or ID."
        ),
    )
    parser.add_argument(
        "--expected-report-count",
        type=int,
        default=CANONICAL_HISTORICAL_REPORT_COUNT,
    )
    parser.add_argument(
        "--expected-candidate-count",
        type=int,
        default=CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT,
    )
    parser.add_argument(
        "--allow-noncanonical-counts",
        action="store_true",
        help="Permit fixture/subset inventories instead of enforcing 142/17.",
    )
    parser.add_argument(
        "--require-accepted",
        action="store_true",
        help="Exit nonzero when no candidate emits a bounded feature update.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite output: {output}")
    try:
        trusted_signers = _load_trust_store(args.trust_store)
        receipts = _receipt_lookup(args.revalidation_receipts)
        expected_reports = (
            None if args.allow_noncanonical_counts else args.expected_report_count
        )
        expected_candidates = (
            None if args.allow_noncanonical_counts else args.expected_candidate_count
        )
        policy = GuidanceReplayPolicy(
            compiler_commit=args.compiler_commit,
            compiler_schema_version=args.compiler_schema_version,
            canonicalization_version=args.canonicalization_version,
            fixed_holdout_id=args.fixed_holdout_id,
            fixed_holdout_digest=args.fixed_holdout_digest,
            proof_policy_version=args.proof_policy_version,
            provenance_policy_version=args.provenance_policy_version,
            source_copy_policy_version=args.source_copy_policy_version,
            lineage_id=args.lineage_id,
            base_state_digest=args.base_state_digest,
            trusted_signers=trusted_signers,
            expected_report_count=expected_reports,
            expected_candidate_count=expected_candidates,
            evaluation_time=(
                args.evaluation_time
                or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            ),
            max_report_age_seconds=args.max_report_age_seconds,
            max_feature_deltas=args.max_feature_deltas,
        )

        def revalidator(report, _context):
            receipt = receipts.get(report.content_digest) or receipts.get(
                report.report_id
            )
            if receipt is None:
                raise GuidanceReplayError("no current receipt for candidate")
            return receipt

        report = LegalIRGuidanceReplay(
            policy=policy,
            revalidator=revalidator if receipts else None,
        ).run(args.input)
        payload = report.to_dict()
        _write_json_atomic(output, payload)
    except (GuidanceInventoryError, GuidanceReplayError, OSError) as exc:
        raise SystemExit(f"compiler-guidance replay failed: {exc}") from exc

    print(
        f"audited_reports={report.audited_report_count} "
        f"replay_candidates={report.replay_candidate_count} "
        f"accepted={report.accepted_count} "
        f"rejected={report.rejected_candidate_count} "
        f"report_sha256={payload['report_sha256']} "
        f"output={output}"
    )
    if report.inventory_errors:
        return 2
    if args.require_accepted and report.accepted_count == 0:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
