from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import (
    Condition,
    DeonticOp,
    LegalIR,
    Norm,
    deterministic_id,
    parse_cnl_sentence,
)
from ipfs_datasets_py.processors.legal_data.reasoner import HybridLawReasoner
from ipfs_datasets_py.processors.legal_data.reasoner.models import SourceProvenance


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


def _build_reasoner() -> tuple[
    HybridLawReasoner,
    str,
    Dict[str, str],
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, bool]],
]:
    ir_file = parse_cnl_sentence("Company A shall file report within 30 days.", jurisdiction="us/federal")
    ir_forbid = parse_cnl_sentence("Company A shall not dump waste.", jurisdiction="us/federal")
    ir_backup = parse_cnl_sentence(
        "Company A shall submit backup report within 10 days unless emergency.",
        jurisdiction="us/federal",
    )
    kb = _merge_irs([ir_file, ir_forbid, ir_backup])

    norm_to_frame: Dict[str, str] = {
        "file_report": next(iter(ir_file.norms.values())).target_frame_ref,
        "dump_waste": next(iter(ir_forbid.norms.values())).target_frame_ref,
        "submit_backup_report": next(iter(ir_backup.norms.values())).target_frame_ref,
    }

    actor_ref = next(iter(ir_file.frames.values())).roles.get("agent", "")

    # Inject explicit O/F conflict on the same target frame as the filing obligation.
    file_norm = next(iter(ir_file.norms.values()))
    conflict_norm = Norm(
        id=deterministic_id("nrm", ["conflict", file_norm.target_frame_ref]),
        op=DeonticOp.F,
        target_frame_ref=file_norm.target_frame_ref,
        activation=Condition.atom_pred("conflict_mode"),
        exceptions=[],
        temporal_ref=file_norm.temporal_ref,
        jurisdiction=file_norm.jurisdiction,
    )
    kb.norms[conflict_norm.id.ref()] = conflict_norm
    frame_by_ref = {fref: kb.frames[fref] for fref in kb.frames}
    for fref, frame in frame_by_ref.items():
        if getattr(frame, "attrs", {}).get("action_text", "").lower() == "file report":
            norm_to_frame["file_report"] = fref
            break

    provenance = {
        nid: SourceProvenance(
            source_path="data/federal_laws/us_constitution.jsonld",
            source_id=f"synthetic_source#{idx + 1}",
            source_span=f"chars:{100 + idx * 10}-{109 + idx * 10}",
        )
        for idx, nid in enumerate(kb.norms.keys())
    }

    reasoner = HybridLawReasoner(kb, provenance_by_norm=provenance)

    events_cases: Dict[str, Dict[str, Any]] = {
        "none": {"events": []},
        "report_on_time": {
            "events": [
                {
                    "frame_ref": norm_to_frame["file_report"],
                    "time": "2026-03-20T10:00:00Z",
                }
            ]
        },
        "dump_happened": {
            "events": [
                {
                    "frame_ref": norm_to_frame["dump_waste"],
                    "time": "2026-04-10T10:00:00Z",
                }
            ]
        },
        "mixed": {
            "events": [
                {
                    "frame_ref": norm_to_frame["file_report"],
                    "time": "2026-03-20T10:00:00Z",
                },
                {
                    "frame_ref": norm_to_frame["dump_waste"],
                    "time": "2026-04-10T10:00:00Z",
                },
            ]
        },
    }

    facts_cases: Dict[str, Dict[str, bool]] = {
        "default": {"true": True},
        "emergency": {"true": True, "exception_clause": True},
        "conflict": {"true": True, "conflict_mode": True},
    }

    return reasoner, actor_ref, norm_to_frame, events_cases, facts_cases


def _load_cases() -> list[dict[str, Any]]:
    p = Path(__file__).with_name("test_queries.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_reasoner_case_count_is_eight() -> None:
    assert len(_load_cases()) == 8


def test_reasoner_queries_and_proofs() -> None:
    reasoner, actor_ref, norm_to_frame, events_cases, facts_cases = _build_reasoner()
    cases = _load_cases()
    proof_by_case: Dict[str, str] = {}

    for case in cases:
        api = case["api"]
        if api == "check_compliance":
            q = case["query"]
            query = {
                "actor_ref": actor_ref,
                "frame_ref": norm_to_frame[q["frame_key"]],
                "events": events_cases[q["events_case"]]["events"],
                "facts": facts_cases[q["facts_case"]],
            }
            out = reasoner.check_compliance(query, case["time_context"])
            proof_by_case[case["id"]] = out["proof_id"]
            if "expected_status" in case:
                assert out["status"] == case["expected_status"]
            if case.get("expected_conflict"):
                assert len(out["conflicts"]) >= 1

        elif api == "find_violations":
            state = {
                "events": events_cases[case["state"]["events_case"]]["events"],
                "facts": facts_cases[case["state"]["facts_case"]],
            }
            out = reasoner.find_violations(state, tuple(case["time_range"]))
            proof_by_case[case["id"]] = out["proof_id"]
            assert len(out["violations"]) >= int(case.get("expected_min_violations", 0))

        elif api == "explain_proof":
            source_case = case["from_query_id"]
            proof_id = proof_by_case[source_case]
            out = reasoner.explain_proof(proof_id, format=case.get("format", "nl"))
            if case.get("expect_reconstructed_nl"):
                assert len(out["reconstructed_nl"]) >= 1
                assert any("shall" in s.lower() or "may" in s.lower() for s in out["reconstructed_nl"])
            if case.get("expect_ir_refs"):
                assert any(step.get("ir_refs") for step in out.get("steps", []))
            if case.get("expect_provenance"):
                assert any(step.get("provenance") for step in out.get("steps", []))
        else:
            raise AssertionError(f"unsupported api case: {api}")
