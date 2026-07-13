#!/usr/bin/env python3
"""Run the bounded asynchronous Leanstral audit worker over JSONL packets."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.logic.modal import (
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralVerifierConfig,
    aggregate_verified_audits,
    build_leanstral_audit_work_items,
    leanstral_rule_gap_report_to_json,
    load_leanstral_audit_disagreements,
    verify_leanstral_audit,
)


DEFAULT_CHECKPOINT_PATH = Path("workspace/leanstral-audit-worker/checkpoint.json")
DEFAULT_CACHE_DIR = Path("workspace/leanstral-audit-worker/cache")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Immutable disagreement packet JSON/JSONL file or directory.",
    )
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--checkpoint-path", default=str(DEFAULT_CHECKPOINT_PATH))
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.25)
    parser.add_argument("--expected-state-hash", default="")
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--provider", default="mistral_vibe")
    parser.add_argument("--model", default="Leanstral")
    parser.add_argument("--vibe-agent", default="lean")
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not call Leanstral for cache misses.",
    )
    parser.add_argument(
        "--allow-non-leanstral-model",
        action="store_true",
        help="Disable fail-closed protection against substituting another model.",
    )
    parser.add_argument(
        "--verification-output",
        default="",
        help="Write deterministic local audit verification records as JSONL.",
    )
    parser.add_argument(
        "--rule-gap-report-output",
        default="",
        help="Write the deterministic verified Leanstral rule-gap report as JSON.",
    )
    parser.add_argument("--lean-executable", default="")
    parser.add_argument("--lean-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--prover-timeout-seconds", type=float, default=5.0)
    parser.add_argument(
        "--prover",
        action="append",
        default=[],
        help="Local prover route to use for modal bridge checks; repeatable.",
    )
    parser.add_argument("--skip-lean", action="store_true")
    parser.add_argument("--skip-modal-bridge", action="store_true")
    parser.add_argument("--skip-syntax-check", action="store_true")
    parser.add_argument("--skip-graph-check", action="store_true")
    parser.add_argument("--skip-provenance-check", action="store_true")
    return parser.parse_args(argv)


async def async_main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not args.input:
        raise SystemExit("--input is required")
    config = LeanstralAuditWorkerConfig(
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        request_timeout_seconds=args.timeout_seconds,
        retry_backoff_seconds=args.retry_backoff_seconds,
        cache_dir=args.cache_dir,
        checkpoint_path=args.checkpoint_path,
        expected_state_hash=args.expected_state_hash,
        max_records=args.max_records,
        provider_enabled=not args.cache_only,
        provider=args.provider,
        model=args.model,
        vibe_agent=args.vibe_agent,
        require_leanstral_model=not args.allow_non_leanstral_model,
    )
    worker = LeanstralAuditWorker(config)
    summary = await worker.run_paths(args.input)
    if args.verification_output or args.rule_gap_report_output:
        verification_records, report = verify_worker_audit_outputs(
            args.input,
            worker=worker,
            worker_config=config,
            verifier_config=LeanstralVerifierConfig(
                lean_executable=args.lean_executable or None,
                lean_timeout_seconds=args.lean_timeout_seconds,
                prover_timeout_seconds=args.prover_timeout_seconds,
                use_provers=tuple(args.prover),
                run_lean=not args.skip_lean,
                run_modal_bridge=not args.skip_modal_bridge,
                run_syntax_check=not args.skip_syntax_check,
                run_graph_check=not args.skip_graph_check,
                run_provenance_check=not args.skip_provenance_check,
            ),
        )
        if args.verification_output:
            _write_jsonl_atomic(
                Path(args.verification_output),
                [record for record in verification_records],
            )
        if args.rule_gap_report_output:
            _write_text_atomic(
                Path(args.rule_gap_report_output),
                leanstral_rule_gap_report_to_json(report) + "\n",
            )
    print(json.dumps(summary.to_dict(), ensure_ascii=True, sort_keys=True))
    return 1 if summary.failed_count or summary.unavailable_count else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return asyncio.run(async_main(argv))


def verify_worker_audit_outputs(
    paths: Sequence[str | Path],
    *,
    worker: LeanstralAuditWorker,
    worker_config: LeanstralAuditWorkerConfig,
    verifier_config: Optional[LeanstralVerifierConfig] = None,
) -> Tuple[List[Dict[str, Any]], Any]:
    """Verify cached real audit responses and build a deterministic gap report."""

    records, _, _ = load_leanstral_audit_disagreements(
        paths,
        max_records=worker_config.max_records,
    )
    items, _ = build_leanstral_audit_work_items(records, config=worker_config)
    verification_records: List[Dict[str, Any]] = []
    report_inputs: List[Mapping[str, Any]] = []
    for item in items:
        entry = worker.runner.cache.get_entry(item.request)
        if entry is None:
            continue
        response = entry.response
        verification = verify_leanstral_audit(
            item.request,
            response,
            config=verifier_config,
        )
        record = {
            "request": item.request.to_dict(),
            "response": response.to_dict(),
            "verification": verification.to_dict(),
            "work_key": item.work_key,
        }
        verification_records.append(record)
        report_inputs.append(
            {
                "request_id": item.request.request_id,
                "response": response,
                "verification": verification,
            }
        )
    report = aggregate_verified_audits(report_inputs)
    return verification_records, report


def _write_jsonl_atomic(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    text = "".join(
        json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
        for record in records
    )
    _write_text_atomic(path, text)


def _write_text_atomic(path: Path, text: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


if __name__ == "__main__":
    raise SystemExit(main())
