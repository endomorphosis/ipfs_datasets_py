from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import Condition, DeonticOp, LegalIR, Norm, deterministic_id, parse_cnl_sentence
from ipfs_datasets_py.processors.legal_data.reasoner import HybridLawReasoner
from ipfs_datasets_py.processors.legal_data.reasoner.models import SourceProvenance


def _load_cases() -> list[dict[str, Any]]:
    p = Path(__file__).with_name("fixtures") / "query_matrix_phase_j_cases.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _merge_irs(irs: list[LegalIR]) -> LegalIR:
    kb = LegalIR(jurisdiction="us/federal")
    for ir in irs:
        kb.entities.update(ir.entities)
        kb.frames.update(ir.frames)
        kb.temporal.update(ir.temporal)
        kb.norms.update(ir.norms)
        kb.rules.update(ir.rules)
        kb.queries.update(ir.queries)
    return kb


def _build_reasoner() -> tuple[HybridLawReasoner, str, dict[str, str], dict[str, dict[str, Any]], dict[str, dict[str, bool]]]:
    ir_wages = parse_cnl_sentence("Employer shall pay wages within 14 days.", jurisdiction="us/federal")
    ir_disclose = parse_cnl_sentence(
        "Employer shall not disclose employee medical record unless court order.",
        jurisdiction="us/federal",
    )
    ir_breach = parse_cnl_sentence("Employer shall notify regulator of breach within 72 hours.", jurisdiction="us/federal")
    kb = _merge_irs([ir_wages, ir_disclose, ir_breach])

    frame_by_key = {
        "pay_wages": next(iter(ir_wages.norms.values())).target_frame_ref,
        "disclose_record": next(iter(ir_disclose.norms.values())).target_frame_ref,
        "notify_breach": next(iter(ir_breach.norms.values())).target_frame_ref,
    }
    actor_ref = next(iter(ir_wages.frames.values())).roles.get("agent", "")

    wages_norm = next(iter(ir_wages.norms.values()))
    conflict_norm = Norm(
        id=deterministic_id("nrm", ["phase_j_conflict", wages_norm.target_frame_ref]),
        op=DeonticOp.F,
        target_frame_ref=wages_norm.target_frame_ref,
        activation=Condition.atom_pred("conflict_mode"),
        exceptions=[],
        temporal_ref=wages_norm.temporal_ref,
        jurisdiction=wages_norm.jurisdiction,
    )
    kb.norms[conflict_norm.id.ref()] = conflict_norm

    provenance = {
        nid: SourceProvenance(
            source_path="data/federal_laws/us_constitution.jsonld",
            source_id=f"phase_j_source#{idx + 1}",
            source_span=f"chars:{300 + idx * 10}-{309 + idx * 10}",
        )
        for idx, nid in enumerate(kb.norms.keys())
    }

    reasoner = HybridLawReasoner(kb, provenance_by_norm=provenance)

    events_cases: dict[str, dict[str, Any]] = {
        "none": {"events": []},
        "wages_paid_on_time": {
            "events": [
                {"frame_ref": frame_by_key["pay_wages"], "time": "2026-05-10T10:00:00Z"}
            ]
        },
        "record_disclosed": {
            "events": [
                {"frame_ref": frame_by_key["disclose_record"], "time": "2026-06-01T10:00:00Z"}
            ]
        },
        "breach_notified_on_time": {
            "events": [
                {"frame_ref": frame_by_key["notify_breach"], "time": "2026-07-02T12:00:00Z"}
            ]
        },
        "all_required_on_time": {
            "events": [
                {"frame_ref": frame_by_key["pay_wages"], "time": "2026-07-02T09:00:00Z"},
                {"frame_ref": frame_by_key["notify_breach"], "time": "2026-07-02T12:00:00Z"},
            ]
        },
    }

    facts_cases: dict[str, dict[str, bool]] = {
        "default": {"true": True},
        "court_order": {"true": True, "exception_clause": True},
        "conflict_mode": {"true": True, "conflict_mode": True},
    }

    return reasoner, actor_ref, frame_by_key, events_cases, facts_cases


def test_phase_j_case_count_is_eight() -> None:
    assert len(_load_cases()) == 8


def test_phase_j_query_api_matrix_end_to_end() -> None:
    reasoner, actor_ref, frame_by_key, events_cases, facts_cases = _build_reasoner()
    proof_by_case: dict[str, str] = {}

    for case in _load_cases():
        api = case["api"]
        if api == "check_compliance":
            q = case["query"]
            out = reasoner.check_compliance(
                {
                    "actor_ref": actor_ref,
                    "frame_ref": frame_by_key[q["frame_key"]],
                    "events": events_cases[q["events_case"]]["events"],
                    "facts": facts_cases[q["facts_case"]],
                },
                case["time_context"],
            )
            proof_by_case[case["id"]] = out["proof_id"]
            if "expected_status" in case:
                assert out["status"] == case["expected_status"], case["id"]
            if case.get("expected_conflict"):
                assert len(out["conflicts"]) >= 1, case["id"]

        elif api == "find_violations":
            st = case["state"]
            out = reasoner.find_violations(
                {
                    "events": events_cases[st["events_case"]]["events"],
                    "facts": facts_cases[st["facts_case"]],
                },
                tuple(case["time_range"]),
            )
            proof_by_case[case["id"]] = out["proof_id"]
            types = [v.get("violation_type") for v in out.get("violations", [])]
            if "expected_violation_type" in case:
                assert case["expected_violation_type"] in types, case["id"]
            if "expected_absent_violation_type" in case:
                assert case["expected_absent_violation_type"] not in types, case["id"]

        elif api == "explain_proof":
            proof_id = proof_by_case[case["from_query_id"]]
            out = reasoner.explain_proof(proof_id, format=case.get("format", "nl"))
            if case.get("expect_reconstructed_nl"):
                assert len(out.get("reconstructed_nl") or []) >= 1, case["id"]
            if case.get("expect_ir_refs"):
                assert any(step.get("ir_refs") for step in out.get("steps", [])), case["id"]
            if case.get("expect_provenance"):
                assert any(step.get("provenance") for step in out.get("steps", [])), case["id"]

        else:
            raise AssertionError(f"Unsupported API: {api}")
