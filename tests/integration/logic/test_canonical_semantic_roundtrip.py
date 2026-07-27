"""Integration tests for SRT-018 canonical semantic round-trip parity."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.canonical_decision import (
    PARITY_REPORT_INTERFACE,
    PARITY_REPORT_SCHEMA,
    validate_parity_report,
)
from benchmarks.semantic_roundtrip.canonical_parity import (
    run_canonical_parity,
    write_parity_report,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    OperationStatus,
    load_parity_policy,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import (
    CanonicalSemanticRoundTrip,
    measured_parity_compiler_request,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalAtomVocabulary,
)


ROOT = Path(__file__).resolve().parents[3]
PILOT_CASES = ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"


def _vocab_from_case(case: object) -> CanonicalAtomVocabulary:
    allowed = case.allowed_atom_vocabulary
    return CanonicalAtomVocabulary(
        actors=list(allowed.actors),
        actions=list(allowed.actions),
        objects=list(allowed.objects),
        qualifiers=list(allowed.qualifiers),
    )


def test_pilot_cases_complete_with_measured_partial_disclosure() -> None:
    cases = load_matrix_cases(PILOT_CASES)
    orchestrator = CanonicalSemanticRoundTrip()
    for case in cases:
        request = measured_parity_compiler_request(
            case.source_text,
            request_id=f"integration:{case.case_id}",
            atom_vocabulary=_vocab_from_case(case),
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
        assert (
            result.l2_result.provenance["source_cid"]
            == result.t1_result.text_cid
        )


def test_canonical_parity_report_is_noninferior_and_self_validating() -> None:
    report = run_canonical_parity(repo_root=ROOT)
    assert report["interface"] == PARITY_REPORT_INTERFACE
    assert report["schema_version"] == PARITY_REPORT_SCHEMA
    assert report["parity_policy_cid"] == CANONICAL_PARITY_POLICY_CID
    assert report["selected_arm_id"] == IMPLEMENTATION_REPRESENTATIVE_ARM_ID
    assert report["comparison"]["within_tolerance"] is True
    assert report["comparison"]["estimate"] == 0.0
    assert all(
        case["source_copy_violation"] is False
        and case["polarity_hard_failure"] is False
        and case["full_nonempty_coverage"] is True
        for case in report["execution"]["case_results"]
    )

    policy = load_parity_policy().to_dict()
    # validate_parity_report expects the slim decision-validator policy view.
    parity_policy = {
        "policy_cid": policy["policy_cid"],
        "confidence_level": policy["confidence_level"],
        "bootstrap_samples": policy["bootstrap_samples"],
        "noninferiority_margin": policy["noninferiority_margin"],
        "document": {
            "bootstrap_method": policy["bootstrap_method"],
            "resampling_unit": policy["resampling_unit"],
        },
    }
    selected_per_case = {
        case["case_id"]: {
            "losses": {
                "end_to_end": case["selected_arm_end_to_end_loss"],
            }
        }
        for case in report["execution"]["case_results"]
    }
    validated = validate_parity_report(
        report,
        composition_report_cid=report["composition_report_cid"],
        selected_arm_id=report["selected_arm_id"],
        case_ids=[
            case["case_id"] for case in report["execution"]["case_results"]
        ],
        selected_per_case=selected_per_case,
        parity_policy=parity_policy,
    )
    assert validated["within_tolerance"] is True
    assert validated["report_cid"] == report["report_cid"]


def test_write_parity_report_round_trips_bytes(tmp_path: Path) -> None:
    report = run_canonical_parity(repo_root=ROOT)
    # Write under a temporary repository layout with implementation files.
    for name in ("ir_schema", "compiler", "decompiler", "roundtrip"):
        relative = Path(
            __import__(
                "benchmarks.semantic_roundtrip.canonical_decision",
                fromlist=["CANONICAL_ARTIFACT_PATHS"],
            ).CANONICAL_ARTIFACT_PATHS[name]
        )
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    # Rebuild lineage against the temp tree while keeping scores.
    from benchmarks.semantic_roundtrip.canonical_parity import (
        build_parity_report,
        implementation_raw_cids,
    )

    case_ids = [
        case["case_id"] for case in report["execution"]["case_results"]
    ]
    rebuilt = build_parity_report(
        [
            {
                **case,
                # score_roundtrip_case extras are not required by builder.
            }
            for case in report["execution"]["case_results"]
        ],
        composition_report_cid=report["composition_report_cid"],
        selected_arm_id=report["selected_arm_id"],
        case_ids=case_ids,
        repo_root=tmp_path,
    )
    path = write_parity_report(rebuilt, repo_root=tmp_path)
    assert path.is_file()
    assert implementation_raw_cids(tmp_path) == rebuilt["lineage"][
        "implementation_raw_cids"
    ]
