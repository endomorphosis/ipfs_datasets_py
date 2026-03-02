from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_v2_blueprint import (
    build_v2_compiler_parity_report,
    compile_ir_to_dcec,
    compile_ir_to_temporal_deontic_fol,
    parse_cnl_to_ir,
)


def _load_cases() -> list[dict[str, Any]]:
    path = Path(__file__).with_name("fixtures") / "compiler_parity_v2_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_v2_compiler_parity_cases_are_semantically_aligned() -> None:
    for case in _load_cases():
        ir = parse_cnl_to_ir(case["sentence"], jurisdiction=case.get("jurisdiction", "us/federal"))
        report = build_v2_compiler_parity_report(ir)

        assert report["summary"]["has_inconsistencies"] is False, case["id"]
        assert report["summary"]["norm_count"] == 1, case["id"]

        entry = report["entries"][0]
        assert entry["checks"]["modal_consistent"] is True, case["id"]
        assert entry["checks"]["target_ref_consistent"] is True, case["id"]
        assert entry["checks"]["temporal_guard_consistent"] is True, case["id"]
        assert entry["checks"]["activation_consistent"] is True, case["id"]
        assert entry["dcec"]["operator"] == case["expected_operator"], case["id"]
        assert entry["tdfol"]["operator"] == case["expected_operator"], case["id"]
        assert entry["dcec"]["has_temporal_guard"] is case["expect_temporal_guard"], case["id"]
        assert entry["tdfol"]["has_temporal_guard"] is case["expect_temporal_guard"], case["id"]


def test_v2_compiler_parity_detects_temporal_guard_mismatch() -> None:
    ir = parse_cnl_to_ir(
        "Controller shall report breach within 24 hours.",
        jurisdiction="us/federal",
    )
    dcec = compile_ir_to_dcec(ir)
    tdfol = compile_ir_to_temporal_deontic_fol(ir)

    bad_tdfol = [tdfol[0].replace("Within(t,", "NoGuard(t,")]
    report = build_v2_compiler_parity_report(ir, dcec_formulas=dcec, tdfol_formulas=bad_tdfol)

    assert report["summary"]["has_inconsistencies"] is True
    assert report["summary"]["inconsistency_count"] >= 1
    assert any(
        isinstance(item, dict)
        and item.get("checks", {}).get("temporal_guard_consistent") is False
        for item in report["inconsistencies"]
    )


def test_v2_compiler_parity_detects_target_ref_mismatch() -> None:
    ir = parse_cnl_to_ir(
        "Agency may inspect records if complaint is filed.",
        jurisdiction="us/federal",
    )
    dcec = compile_ir_to_dcec(ir)
    tdfol = compile_ir_to_temporal_deontic_fol(ir)

    bad_dcec = [dcec[0].replace("frm:", "frm_bad:")]
    report = build_v2_compiler_parity_report(ir, dcec_formulas=bad_dcec, tdfol_formulas=tdfol)

    assert report["summary"]["has_inconsistencies"] is True
    assert any(
        isinstance(item, dict)
        and item.get("checks", {}).get("target_ref_consistent") is False
        for item in report["inconsistencies"]
    )
