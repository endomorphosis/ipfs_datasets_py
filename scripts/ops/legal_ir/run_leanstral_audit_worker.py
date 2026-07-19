#!/usr/bin/env python3
"""Run the bounded asynchronous Leanstral audit worker over JSONL packets."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
ACCELERATE_ROOT = REPO_ROOT.parent / "ipfs_accelerate_py"
for import_root in (ACCELERATE_ROOT, REPO_ROOT):
    if import_root.exists():
        import_root_text = str(import_root)
        if import_root_text not in sys.path:
            sys.path.insert(0, import_root_text)

from ipfs_datasets_py.utils import anyio_compat
from ipfs_datasets_py.logic.modal import (
    LeanstralAuditVerifier,
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralVerifierConfig,
    aggregate_verified_audits,
    build_leanstral_audit_work_items,
    leanstral_rule_gap_report_to_json,
    load_leanstral_audit_disagreements,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LEANSTRAL_EVIDENCE_REFRESH_POLICIES,
    canonical_sha256,
)


DEFAULT_CHECKPOINT_PATH = Path("workspace/leanstral-audit-worker/checkpoint.json")
DEFAULT_CACHE_DIR = Path("workspace/leanstral-audit-worker/cache")
DEFAULT_LEAN_TIMEOUT_SECONDS = 30.0
SNAPSHOT_SELECTION_POLICIES = ("latest_canonical_snapshot", "none")


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
    parser.add_argument("--validation-repair-retries", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.25)
    parser.add_argument("--expected-state-hash", default="")
    parser.add_argument("--expected-compiler-commit", default="")
    parser.add_argument(
        "--snapshot-selection",
        choices=SNAPSHOT_SELECTION_POLICIES,
        default="latest_canonical_snapshot",
        help=(
            "Select one coherent state_hash/compiler_commit snapshot from "
            "append-only exports before auditing."
        ),
    )
    parser.add_argument(
        "--min-snapshot-records",
        type=int,
        default=1,
        help=(
            "Diagnostic minimum for the selected snapshot. The worker still "
            "audits the latest snapshot when it is below this threshold."
        ),
    )
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--max-work-items", type=int, default=0)
    parser.add_argument("--max-evidence-packets-per-item", type=int, default=6)
    parser.add_argument(
        "--evidence-refresh-policy",
        choices=LEANSTRAL_EVIDENCE_REFRESH_POLICIES,
        default="full_manifest",
        help=(
            "Use full_manifest for complete append-only attestation or "
            "latest_compiler_snapshot to avoid re-auditing unchanged compiler gaps."
        ),
    )
    parser.add_argument("--provider", default="leanstral_local")
    parser.add_argument(
        "--provider-fallbacks",
        default="llama_cpp_native,mistral_vibe",
        help=(
            "Comma- or colon-separated fallback providers that are explicitly "
            "allowed to serve the same Leanstral audit model."
        ),
    )
    parser.add_argument("--model", default="Leanstral")
    parser.add_argument("--vibe-agent", default="lean")
    parser.add_argument("--max-new-tokens", type=int, default=1800)
    parser.add_argument(
        "--prompt-payload-mode",
        choices=("full", "compact", "daemon"),
        default="full",
        help=(
            "Use full prompts for offline audits or compact/daemon prompts for "
            "low-latency supervised guidance."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Number of Leanstral audit prompts to submit in each batch.",
    )
    parser.add_argument(
        "--batch-max-workers",
        type=int,
        default=2,
        help="Optional router/provider worker cap for batched Leanstral prompts.",
    )
    parser.add_argument(
        "--batch-use-mesh",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Submit batched prompts through the ipfs_accelerate_py mesh router "
            "first; use --no-batch-use-mesh to force direct local/provider calls."
        ),
    )
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
    parser.add_argument(
        "--publish-rule-gap-report-output",
        default="",
        help=(
            "Atomically publish a non-empty verified report for daemon consumption. "
            "An empty audit result never replaces an existing useful report."
        ),
    )
    parser.add_argument(
        "--reference-example-path",
        action="append",
        default=[],
        help=(
            "JSON/JSONL source containing trusted sample_id/text holdout payloads; "
            "repeatable and used only by the local verifier."
        ),
    )
    parser.add_argument("--lean-executable", default="")
    parser.add_argument(
        "--canonical-recompile-backend",
        default="packet_canonical",
        choices=("packet_canonical", "legal_modal_parser", "codec"),
        help="Compiler lane used to reproduce the canonical IR recorded in evidence.",
    )
    parser.add_argument(
        "--require-complete-source-span-evidence",
        action="store_true",
        help="Reject packets whose intentionally capped span attestations omit formulas.",
    )
    parser.add_argument(
        "--lean-timeout-seconds",
        type=float,
        default=DEFAULT_LEAN_TIMEOUT_SECONDS,
    )
    parser.add_argument("--lean-max-formulas", type=int, default=0)
    parser.add_argument("--lean-parallel-workers", type=int, default=1)
    parser.add_argument("--lean-slice-size", type=int, default=0)
    parser.add_argument("--lean-proof-cache-path", default="")
    parser.add_argument("--lean-proof-cache-max-entries", type=int, default=4096)
    parser.add_argument("--lean-proof-cache-ttl-seconds", type=int, default=2_592_000)
    parser.add_argument("--prover-timeout-seconds", type=float, default=5.0)
    parser.add_argument(
        "--require-modal-bridge-proof",
        action="store_true",
        help=(
            "Require each asserted legal formula to be a theorem; by default the "
            "modal bridge validates bounded compilation and reports proof validity."
        ),
    )
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
    load_max_records = 0 if args.snapshot_selection != "none" else args.max_records
    records, schema_failures, source_digest = load_leanstral_audit_disagreements(
        args.input,
        max_records=load_max_records,
    )
    snapshot_selection: Dict[str, Any] = {
        "selection_policy": args.snapshot_selection,
        "source_valid_packet_count": len(records),
    }
    if args.snapshot_selection != "none":
        records, snapshot_selection = select_canonical_snapshot_records(
            records,
            expected_compiler_commit=args.expected_compiler_commit,
            expected_state_hash=args.expected_state_hash,
            max_records=args.max_records,
            min_records=args.min_snapshot_records,
            selection_policy=args.snapshot_selection,
        )
        source_digest = canonical_sha256(
            {
                "original_source_digest": source_digest,
                "schema_failure_count": len(schema_failures),
                "selected_record_hashes": [canonical_sha256(record) for record in records],
                "snapshot_selection": snapshot_selection,
            }
        )
    config = LeanstralAuditWorkerConfig(
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        validation_repair_retries=args.validation_repair_retries,
        request_timeout_seconds=args.timeout_seconds,
        retry_backoff_seconds=args.retry_backoff_seconds,
        cache_dir=args.cache_dir,
        checkpoint_path=args.checkpoint_path,
        expected_state_hash=args.expected_state_hash,
        max_records=args.max_records,
        max_work_items=args.max_work_items,
        max_evidence_packets_per_item=args.max_evidence_packets_per_item,
        evidence_refresh_policy=args.evidence_refresh_policy,
        provider_enabled=not args.cache_only,
        provider=args.provider,
        provider_fallbacks=args.provider_fallbacks,
        model=args.model,
        vibe_agent=args.vibe_agent,
        require_leanstral_model=not args.allow_non_leanstral_model,
        max_new_tokens=args.max_new_tokens,
        prompt_payload_mode=args.prompt_payload_mode,
        batch_size=args.batch_size,
        batch_max_workers=args.batch_max_workers,
        batch_use_mesh=args.batch_use_mesh,
    )
    worker = LeanstralAuditWorker(config)
    summary = await worker.run_records(
        records,
        schema_failures=schema_failures,
        source_digest=source_digest,
    )
    publication: Dict[str, Any] = {"status": "not_requested"}
    if (
        args.verification_output
        or args.rule_gap_report_output
        or args.publish_rule_gap_report_output
    ):
        reference_examples = load_reference_examples(args.reference_example_path)
        verification_records, report = verify_worker_audit_outputs(
            args.input,
            worker=worker,
            worker_config=config,
            reference_examples=reference_examples,
            records=records,
            verifier_config=LeanstralVerifierConfig(
                allow_partial_source_span_evidence=(
                    not args.require_complete_source_span_evidence
                ),
                canonical_recompile_backend=args.canonical_recompile_backend,
                lean_executable=args.lean_executable or None,
                lean_max_formulas=max(0, args.lean_max_formulas),
                lean_parallel_workers=max(1, args.lean_parallel_workers),
                lean_proof_cache_max_entries=max(1, args.lean_proof_cache_max_entries),
                lean_proof_cache_path=args.lean_proof_cache_path or None,
                lean_proof_cache_ttl_seconds=max(
                    1,
                    args.lean_proof_cache_ttl_seconds,
                ),
                lean_slice_size=max(0, args.lean_slice_size),
                lean_timeout_seconds=args.lean_timeout_seconds,
                modal_bridge_require_proof=args.require_modal_bridge_proof,
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
        if args.publish_rule_gap_report_output:
            publication = publish_verified_rule_gap_report(
                Path(args.publish_rule_gap_report_output),
                report,
            )
    summary_payload = summary.to_dict()
    summary_payload["snapshot_selection"] = snapshot_selection
    summary_payload["verified_report_publication"] = publication
    print(json.dumps(summary_payload, ensure_ascii=True, sort_keys=True))
    return 1 if summary.failed_count or summary.unavailable_count else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return anyio_compat.run_with_backend(async_main(argv), backend="trio")


def select_canonical_snapshot_records(
    records: Sequence[Mapping[str, Any]],
    *,
    expected_compiler_commit: str = "",
    expected_state_hash: str = "",
    max_records: int = 0,
    min_records: int = 1,
    selection_policy: str = "latest_canonical_snapshot",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Select one coherent canonical state/commit snapshot from append-only input."""

    if selection_policy == "none":
        selected = [dict(record) for record in records]
        limit = max(0, int(max_records or 0))
        if limit:
            selected = selected[:limit]
        return selected, {
            "max_records_applied": limit,
            "selected_packet_count": len(selected),
            "selection_policy": "none",
            "selection_reason": "disabled",
            "source_valid_packet_count": len(records),
        }

    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for record in records:
        root = dict(record)
        groups.setdefault(_snapshot_key(root), []).append(root)
    expected_filters: Dict[str, str] = {}
    if expected_state_hash:
        expected_filters["state_hash"] = expected_state_hash
    if expected_compiler_commit:
        expected_filters["compiler_commit"] = expected_compiler_commit
    pool = groups
    if expected_filters:
        expected_pool = {
            key: group
            for key, group in groups.items()
            if (not expected_state_hash or key[0] == expected_state_hash)
            and (not expected_compiler_commit or key[1] == expected_compiler_commit)
        }
        if expected_pool:
            pool = expected_pool
    if not pool:
        return [], {
            "candidate_snapshot_count": len(groups),
            "expected_filters": expected_filters,
            "max_records_applied": 0,
            "meets_min_snapshot_records": False,
            "min_snapshot_records": max(1, int(min_records or 1)),
            "selected_group_packet_count": 0,
            "selected_packet_count": 0,
            "selection_policy": selection_policy,
            "selection_reason": "no_matching_snapshot",
            "source_valid_packet_count": len(records),
        }

    selected_key = max(pool, key=lambda key: _snapshot_rank(pool[key]))
    selected_group = sorted(pool[selected_key], key=_record_rank)
    limit = max(0, int(max_records or 0))
    selected = selected_group[-limit:] if limit else selected_group
    minimum = max(1, int(min_records or 1))
    meets_minimum = len(selected_group) >= minimum
    reason_parts = []
    if expected_filters and pool is not groups:
        reason_parts.append("expected")
    reason_parts.extend(
        [
            "newest",
            "min_satisfying" if meets_minimum else "available",
            "snapshot",
        ]
    )
    candidates = [
        _snapshot_candidate_summary(key, group)
        for key, group in sorted(
            groups.items(),
            key=lambda item: _snapshot_rank(item[1]),
            reverse=True,
        )[:10]
    ]
    return selected, {
        "candidate_snapshot_count": len(groups),
        "dropped_valid_packet_count": max(0, len(records) - len(selected)),
        "expected_filters": expected_filters,
        "max_records_applied": limit,
        "meets_min_snapshot_records": meets_minimum,
        "min_snapshot_records": minimum,
        "selected_compiler_commit": selected_key[1],
        "selected_group_packet_count": len(selected_group),
        "selected_packet_count": len(selected),
        "selected_state_hash": selected_key[0],
        "selection_policy": selection_policy,
        "selection_reason": "_".join(reason_parts),
        "snapshot_candidates": candidates,
        "source_valid_packet_count": len(records),
    }


def _snapshot_key(record: Mapping[str, Any]) -> Tuple[str, str]:
    context = _mapping(record.get("run_context"))
    evidence_hashes = _mapping(record.get("evidence_hashes"))
    return (
        str(context.get("state_hash") or evidence_hashes.get("state_hash") or ""),
        str(context.get("compiler_commit") or ""),
    )


def _snapshot_rank(records: Sequence[Mapping[str, Any]]) -> Tuple[float, float, int]:
    if not records:
        return (0.0, 0.0, 0)
    return max(_record_rank(record) for record in records)


def _record_rank(record: Mapping[str, Any]) -> Tuple[float, float, int]:
    context = _mapping(record.get("run_context"))
    exported_at = _timestamp_rank(context.get("exported_at", record.get("exported_at")))
    cycle = _finite_float(context.get("cycle"), 0.0)
    frozen_canary = _mapping(context.get("frozen_canary"))
    canary_index = int(_finite_float(frozen_canary.get("index"), 0.0))
    return (exported_at, cycle, canary_index)


def _snapshot_candidate_summary(
    key: Tuple[str, str],
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    cycles = sorted(
        {
            int(_finite_float(_mapping(record.get("run_context")).get("cycle"), 0.0))
            for record in records
        }
    )
    return {
        "compiler_commit": key[1],
        "cycle_max": max(cycles) if cycles else None,
        "cycle_min": min(cycles) if cycles else None,
        "packet_count": len(records),
        "state_hash": key[0],
    }


def _timestamp_rank(value: Any) -> float:
    number = _finite_float(value, float("nan"))
    if math.isfinite(number):
        return number
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except ValueError:
                return 0.0
    return 0.0


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def verify_worker_audit_outputs(
    paths: Sequence[str | Path],
    *,
    worker: LeanstralAuditWorker,
    worker_config: LeanstralAuditWorkerConfig,
    reference_examples: Optional[Mapping[str, Mapping[str, Any]]] = None,
    records: Optional[Sequence[Mapping[str, Any]]] = None,
    verifier_config: Optional[LeanstralVerifierConfig] = None,
) -> Tuple[List[Dict[str, Any]], Any]:
    """Verify cached real audit responses and build a deterministic gap report."""

    loaded_records = [dict(record) for record in records] if records is not None else None
    if loaded_records is None:
        loaded_records, _, _ = load_leanstral_audit_disagreements(
            paths,
            max_records=worker_config.max_records,
        )
    items, _ = build_leanstral_audit_work_items(loaded_records, config=worker_config)
    verifier = LeanstralAuditVerifier(verifier_config)
    verification_records: List[Dict[str, Any]] = []
    report_inputs: List[Mapping[str, Any]] = []
    for item in items:
        entry = worker.runner.cache.get_entry(item.request)
        if entry is None:
            continue
        response = entry.response
        verification = verifier.verify(
            item.request,
            response,
            examples=_reference_examples_for_item(
                item,
                response=response,
                reference_examples=reference_examples or {},
            ),
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
                "request": item.request.to_dict(),
                "request_id": item.request.request_id,
                "response": response,
                "verification": verification,
            }
        )
    report = aggregate_verified_audits(report_inputs)
    return verification_records, report


def load_reference_examples(
    paths: Sequence[str | Path],
) -> Dict[str, Dict[str, Any]]:
    """Index trusted holdout payloads without copying them into model evidence."""

    examples: Dict[str, Dict[str, Any]] = {}
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))
        files = (
            sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl"))
            if path.is_dir()
            else [path]
        )
        for file_path in files:
            for value in _reference_json_values(file_path):
                for candidate in _iter_reference_example_mappings(value):
                    sample_id = str(candidate.get("sample_id") or "").strip()
                    examples.setdefault(sample_id, dict(candidate))
    return examples


def _reference_examples_for_item(
    item: Any,
    *,
    response: Any,
    reference_examples: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    referenced_evidence_ids = _response_evidence_ids(response)
    packets = [
        packet
        for packet in item.request.evidence.get("evidence_packets", [])
        if isinstance(packet, Mapping)
    ]
    if referenced_evidence_ids:
        referenced_packets = [
            packet
            for packet in packets
            if str(packet.get("evidence_id") or "").strip() in referenced_evidence_ids
        ]
        if referenced_packets:
            packets = referenced_packets

    examples: List[Dict[str, Any]] = []
    seen_sample_ids: set[str] = set()
    request_examples = {
        str(
            candidate.get("sample_id")
            or candidate.get("example_id")
            or candidate.get("evidence_id")
            or ""
        ).strip(): dict(candidate)
        for candidate in item.request.evidence.get("referenced_examples", []) or []
        if isinstance(candidate, Mapping)
        and str(
            candidate.get("sample_id")
            or candidate.get("example_id")
            or candidate.get("evidence_id")
            or ""
        ).strip()
    }
    for packet in packets:
        sample_hashes = packet.get("sample_hashes")
        if not isinstance(sample_hashes, Mapping):
            continue
        sample_id = str(sample_hashes.get("sample_id") or "").strip()
        request_example = request_examples.get(sample_id) or request_examples.get(
            str(packet.get("evidence_id") or "").strip()
        )
        reference = reference_examples.get(sample_id)
        if not isinstance(reference, Mapping):
            if isinstance(request_example, Mapping) and _reference_example_has_text(
                request_example
            ):
                reference = request_example
            else:
                reference = None
        if not sample_id or sample_id in seen_sample_ids or not isinstance(reference, Mapping):
            continue
        example = dict(reference)
        if isinstance(request_example, Mapping):
            for key in (
                "compiler_decompiler_metrics",
                "evidence_id",
                "expected_modal_ir_hash",
                "source_text_hash",
            ):
                if key in request_example and key not in example:
                    example[key] = request_example[key]
        example["example_id"] = sample_id
        example["sample_id"] = sample_id
        expected_hash = str(sample_hashes.get("modal_ir_hash") or "").strip()
        if expected_hash:
            example["expected_modal_ir_hash"] = expected_hash
        source_span_hashes = sample_hashes.get("source_span_hashes")
        if isinstance(source_span_hashes, Mapping) and source_span_hashes:
            example["source_span_hashes"] = dict(source_span_hashes)
            example["source_span_hash_format"] = "introspection_packet_v1"
        examples.append(example)
        seen_sample_ids.add(sample_id)
    return examples


def _response_evidence_ids(response: Any) -> set[str]:
    values: set[str] = set()
    for payload in (
        getattr(response, "counterexample", None),
        getattr(response, "witness", None),
    ):
        _collect_evidence_ids(payload, values)
    return values


def _collect_evidence_ids(payload: Any, values: set[str]) -> None:
    if isinstance(payload, Mapping):
        value = str(payload.get("evidence_id") or "").strip()
        if value:
            values.add(value)
        for child in payload.values():
            _collect_evidence_ids(child, values)
    elif isinstance(payload, (list, tuple)):
        for child in payload:
            _collect_evidence_ids(child, values)


def _reference_example_has_text(example: Mapping[str, Any]) -> bool:
    return bool(
        str(
            example.get("source_text")
            or example.get("text")
            or example.get("source")
            or example.get("source_span")
            or ""
        ).strip()
    )


def _reference_json_values(path: Path) -> Sequence[Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def _iter_reference_example_mappings(value: Any):
    if isinstance(value, Mapping):
        sample_id = str(value.get("sample_id") or "").strip()
        text = value.get("source_text", value.get("text"))
        if sample_id and isinstance(text, str) and text.strip():
            yield value
        for child in value.values():
            if isinstance(child, (Mapping, list, tuple)):
                yield from _iter_reference_example_mappings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_reference_example_mappings(child)


def _write_jsonl_atomic(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    text = "".join(
        json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
        for record in records
    )
    _write_text_atomic(path, text)


def publish_verified_rule_gap_report(path: Path, report: Any) -> Dict[str, Any]:
    """Publish verified compiler evidence without erasing a useful prior report."""

    payload = report.to_dict() if hasattr(report, "to_dict") else dict(report or {})
    accepted_count = int(payload.get("accepted_supporting_audit_count", 0) or 0)
    gap_count = len(payload.get("gaps", []) or [])
    rejected_audits = [
        item for item in payload.get("rejected_audits", []) or [] if isinstance(item, Mapping)
    ]
    rejected_reason_counts = _rejected_audit_reason_counts(rejected_audits)
    latest_source_count = int(payload.get("source_audit_count", 0) or 0)
    destination = path.expanduser()
    existing_accepted_count = 0
    if destination.is_file():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
            existing_accepted_count = int(
                existing.get("accepted_supporting_audit_count", 0) or 0
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            existing_accepted_count = 0
    if accepted_count <= 0 or gap_count <= 0:
        return {
            "accepted_supporting_audit_count": accepted_count,
            "existing_accepted_supporting_audit_count": existing_accepted_count,
            "gap_count": gap_count,
            "latest_rejected_audit_count": len(rejected_audits),
            "latest_rejected_reason_counts": rejected_reason_counts,
            "latest_source_audit_count": latest_source_count,
            "path": str(destination),
            "status": (
                "preserved_existing_nonempty_report"
                if existing_accepted_count > 0
                else "skipped_empty_report"
            ),
        }
    payload["report_generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["publication_mode"] = "atomic_nonempty_verified"
    _write_text_atomic(
        destination,
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
    )
    return {
        "accepted_supporting_audit_count": accepted_count,
        "existing_accepted_supporting_audit_count": existing_accepted_count,
        "gap_count": gap_count,
        "latest_rejected_audit_count": len(rejected_audits),
        "latest_rejected_reason_counts": rejected_reason_counts,
        "latest_source_audit_count": latest_source_count,
        "path": str(destination),
        "status": "published",
    }


def _rejected_audit_reason_counts(
    rejected_audits: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for audit in rejected_audits:
        reasons = audit.get("reasons")
        if isinstance(reasons, str):
            values = [reasons]
        elif isinstance(reasons, (list, tuple, set)):
            values = list(reasons)
        else:
            values = [audit.get("verification_outcome") or audit.get("status") or "unknown"]
        for reason in values:
            key = str(reason or "unknown").strip() or "unknown"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


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
