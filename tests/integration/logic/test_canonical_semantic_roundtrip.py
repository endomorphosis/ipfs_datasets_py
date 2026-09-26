"""Integration tests for SRT-018 canonical semantic round-trip parity."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.contracts import CanonicalRuleIR
from benchmarks.semantic_roundtrip.matrix import (
    load_matrix_cases,
    polarity_diagnostics,
    source_copy_diagnostics,
)
from benchmarks.semantic_roundtrip.metrics import round_trip_losses
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    CanonicalAtomVocabulary,
    OperationStatus,
    load_parity_policy,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import (
    CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
    CanonicalSemanticRoundTrip,
    measured_parity_compiler_request,
)


ROOT = Path(__file__).resolve().parents[3]
PILOT_CASES = ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
REPLACEMENT_REPORT = (
    ROOT
    / "docs/performance_snapshots"
    / "2026-07-27_semantic_roundtrip_composition_replacement.json"
)
PARITY_SNAPSHOT = (
    ROOT / "docs/performance_snapshots" / "2026-07-26_canonical_semantic_roundtrip.json"
)
SELECTED_ARM = IMPLEMENTATION_REPRESENTATIVE_ARM_ID
HISTORICAL_IMPLEMENTATION_RAW_CIDS = {
    "ir_schema": "bafkreiblsy7nvw7bvribragellyzn74wjcezwmkzonye6jmugnwvrpy4e4",
    "compiler": "bafkreihkepmhrqadg7uldzbmnqdpvklwuyod55vui23dywqegj5diz4lci",
    "decompiler": "bafkreih2ju5hvcdwcni3wtxjy2dksmjp5qvo2ipofghkq73ygk2tnnkmke",
    "roundtrip": "bafkreid2wn2of5alfxwu6oqgcl7kanjsuqgnapkdpgfglbnc3wxeyu34ny",
}


def _vocab(case: object) -> CanonicalAtomVocabulary:
    allowed = case.allowed_atom_vocabulary
    return CanonicalAtomVocabulary(
        actors=list(allowed.actors),
        actions=list(allowed.actions),
        objects=list(allowed.objects),
        qualifiers=list(allowed.qualifiers),
    )


def _to_benchmark_ir(canonical_ir: object) -> CanonicalRuleIR:
    return CanonicalRuleIR.from_dict(canonical_ir.to_dict())


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = probability * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _selected_losses() -> tuple[str, list[str], dict[str, dict[str, float]]]:
    report = json.loads(REPLACEMENT_REPORT.read_text(encoding="utf-8"))
    report_cid = report["report_cid"]
    losses: dict[str, dict[str, float]] = {}
    order: list[str] = []
    for record in report["execution"]["deterministic"]["records"]:
        if record.get("arm_id") != SELECTED_ARM:
            continue
        case_id = record["case_id"]
        losses[case_id] = {
            metric: float(record["losses"][metric])
            for metric in ("forward", "cycle", "end_to_end")
        }
        order.append(case_id)
    return report_cid, order, losses


def test_pilot_cases_complete_with_measured_partial_disclosure() -> None:
    cases = load_matrix_cases(PILOT_CASES)
    orchestrator = CanonicalSemanticRoundTrip()
    for case in cases:
        request = measured_parity_compiler_request(
            case.source_text,
            request_id=f"integration:{case.case_id}",
            atom_vocabulary=_vocab(case),
        )
        assert request.allow_explicit_partial is True
        result = orchestrator.run(request)
        assert result.status is OperationStatus.SUCCESS, (
            case.case_id,
            result.terminal_stage,
            None if result.error is None else result.error.message,
        )
        assert result.l1_result is not None
        assert result.t1_result is not None
        assert result.l2_result is not None
        assert result.l1_result.provenance["source_cid"] == result.source_cid
        assert result.l2_result.provenance["source_cid"] == result.t1_result.text_cid


def test_pilot_parity_is_noninferior_to_selected_replacement_arm() -> None:
    composition_cid, case_order, selected = _selected_losses()
    cases = {case.case_id: case for case in load_matrix_cases(PILOT_CASES)}
    assert set(cases) == set(case_order)
    policy = load_parity_policy().to_dict()
    assert policy["policy_cid"] == CANONICAL_PARITY_POLICY_CID
    orchestrator = CanonicalSemanticRoundTrip()
    deltas: list[float] = []
    for case_id in case_order:
        case = cases[case_id]
        result = orchestrator.run(
            measured_parity_compiler_request(
                case.source_text,
                request_id=f"parity:{case_id}",
                atom_vocabulary=_vocab(case),
            )
        )
        assert result.status is OperationStatus.SUCCESS
        assert result.l1_result is not None
        assert result.t1_result is not None
        assert result.l2_result is not None
        l1 = _to_benchmark_ir(result.l1_result.canonical_ir)
        l2 = _to_benchmark_ir(result.l2_result.canonical_ir)
        text = result.t1_result.text
        losses = round_trip_losses(case.gold_ir, l1, text, l2)
        copy = source_copy_diagnostics(case.source_text, text)
        polarity = polarity_diagnostics(case.gold_ir, l2)
        assert bool(l1.rules) and bool(l2.rules) and bool(text and text.strip())
        assert copy["gate_passed"] is True
        assert polarity["gate_passed"] is True
        # No case or component may regress against its unchanged historical
        # record, even when another case gains a supported semantic atom.
        for metric in ("forward", "cycle", "end_to_end"):
            observed = float(getattr(losses, metric))
            assert observed <= selected[case_id][metric], (
                case_id, metric, observed, selected[case_id][metric]
            )
        deltas.append(float(losses.end_to_end) - selected[case_id]["end_to_end"])

    estimate = _mean(deltas)
    rng = random.Random(int(policy["bootstrap_seed"]))
    draws = [
        _mean([deltas[rng.randrange(len(deltas))] for _ in deltas])
        for _ in range(int(policy["bootstrap_samples"]))
    ]
    high = _quantile(draws, 1.0 - (1.0 - float(policy["confidence_level"])) / 2.0)
    margin = float(policy["noninferiority_margin"])
    assert estimate <= 0.0
    assert high <= margin
    assert composition_cid == policy["frozen_from_report_cid"]


def test_original_typed_deontic_pilot_keeps_forward_and_cycle_thresholds() -> None:
    # The original pilot uses the typed codec and its semantic-score metric;
    # the canonical selection comparison above has a distinct loss contract.
    from benchmarks.bench_semantic_logic_roundtrip import (
        _aggregate_standard_arm,
        run_deontic_codec,
    )

    cases = json.loads(PILOT_CASES.read_text(encoding="utf-8"))
    assert tuple(case["id"] for case in cases) == (
        "exception_with_window",
        "legal_doc_1",
        "exec_order_1",
        "corp_policy_1",
        "construction_contract",
    )
    records = [run_deontic_codec(case) for case in cases]
    for case, record in zip(cases, records):
        assert record["status"] == "success", case["id"]
        assert record["source_withheld_from_realizer"] is True
        assert record["l1"]["rules"] and record["l2"]["rules"]
        assert record["realization"].strip()
        assert record["cycle_l1_vs_l2"]["exact_ir_nonvacuous"] is True
        for metric in ("forward_vs_gold", "cycle_l1_vs_l2", "end_to_end_vs_gold"):
            score = float(record[metric]["semantic_score"])
            assert math.isfinite(score) and 0.0 < score <= 1.0, (case["id"], metric)
    aggregate = _aggregate_standard_arm(records)
    assert aggregate["case_count"] == aggregate["success_count"] == 5
    assert aggregate["full_roundtrip_coverage_count"] == 5
    assert aggregate["mean_forward_semantic_score"] >= 0.915
    assert aggregate["mean_cycle_semantic_score"] == 1.0


def test_checked_in_parity_snapshot_preserves_historical_integrity() -> None:
    snapshot = json.loads(PARITY_SNAPSHOT.read_text(encoding="utf-8"))
    # This receipt describes the historical selection, not current source
    # bytes.  The live pilot and its per-case gates are checked above.
    assert snapshot["report_cid"] == (
        "baguqeerajjr6p4mykd43jtjzcmre5ua3ldid72az4doqyfte5crw6dntahca"
    )
    assert snapshot["parity_policy_cid"] == CANONICAL_PARITY_POLICY_CID
    assert snapshot["selected_arm_id"] == SELECTED_ARM
    assert snapshot["comparison"]["within_tolerance"] is True
    assert snapshot["comparison"]["estimate"] == 0.0
    assert snapshot["lineage"]["configuration_cids"] == [CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID]
    assert snapshot["lineage"]["implementation_raw_cids"] == HISTORICAL_IMPLEMENTATION_RAW_CIDS
    payload = dict(snapshot)
    report_cid = payload.pop("report_cid")
    assert cid_for_dag_json(payload) == report_cid
    assert len(snapshot["execution"]["case_results"]) == 5
    for case in snapshot["execution"]["case_results"]:
        assert case["status"] == "success"
        assert case["full_nonempty_coverage"] is True
        assert case["polarity_hard_failure"] is False
        assert case["source_copy_violation"] is False
        assert case["canonical_minus_selected"] == 0.0
