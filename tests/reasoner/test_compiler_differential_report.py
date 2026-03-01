from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import (
    compile_differential_report,
    compile_to_dcec,
    compile_to_temporal_deontic_fol,
    parse_cnl_sentence,
)


def test_compile_differential_report_has_no_inconsistencies_for_baseline_case() -> None:
    ir = parse_cnl_sentence(
        "Company A shall submit backup report within 10 days unless emergency.",
        jurisdiction="us/federal",
    )

    report = compile_differential_report(ir)

    assert report["summary"]["norm_count"] == 1
    assert report["summary"]["has_inconsistencies"] is False
    assert report["summary"]["inconsistency_count"] == 0
    assert len(report["entries"]) == 1
    checks = report["entries"][0]["checks"]
    assert checks["modal_consistent"] is True
    assert checks["temporal_guard_consistent"] is True
    assert checks["activation_consistent"] is True


def test_compile_differential_report_detects_injected_temporal_mismatch() -> None:
    ir = parse_cnl_sentence(
        "Company A shall file report within 30 days.",
        jurisdiction="us/federal",
    )
    dcec = compile_to_dcec(ir)
    tdfol = compile_to_temporal_deontic_fol(ir)

    # Inject inconsistency by stripping temporal guard from TDFOL output.
    bad_tdfol = [tdfol[0].replace("TemporalGuard(tmp:d0f22920d2410c6f, t) and ", "")]

    report = compile_differential_report(ir, dcec_formulas=dcec, tdfol_formulas=bad_tdfol)

    assert report["summary"]["has_inconsistencies"] is True
    assert report["summary"]["inconsistency_count"] >= 1
    assert any(
        isinstance(item, dict)
        and item.get("checks", {}).get("temporal_guard_consistent") is False
        for item in report["inconsistencies"]
    )


def test_compile_differential_report_detects_count_mismatch() -> None:
    ir = parse_cnl_sentence(
        "Agency may disclose notice when authorized.",
        jurisdiction="us/federal",
    )

    report = compile_differential_report(ir, dcec_formulas=[], tdfol_formulas=[])

    assert report["summary"]["has_inconsistencies"] is True
    assert any(item.get("type") == "count_mismatch" for item in report["inconsistencies"])
