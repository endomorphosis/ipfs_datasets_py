from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_v2_blueprint import (
    LegalIRV2,
    parse_cnl_to_ir_with_diagnostics,
)


def _load_corpus() -> list[dict[str, Any]]:
    path = Path(__file__).with_name("fixtures") / "cnl_parse_replay_v2_corpus.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_ir(ir: LegalIRV2) -> Dict[str, Any]:
    norm_count = len(ir.norms)
    rule_count = len(ir.rules)

    if norm_count > 0:
        norm = next(iter(ir.norms.values()))
        frame = ir.frames[norm.target_frame_ref]
        norm_snapshot: Dict[str, Any] = {
            "norm_op": norm.op.value,
            "norm_id": norm.id.ref(),
            "frame_id": frame.id.ref(),
            "frame_predicate": frame.predicate,
            "temporal_refs": sorted(ir.temporals.keys()),
            "activation_pred": norm.activation.atom.pred if norm.activation.atom else None,
            "exception_count": len(norm.exceptions),
            "parse_confidence": norm.attrs.get("parse_confidence"),
            "parse_alternatives": norm.attrs.get("parse_alternatives"),
            "ambiguity_flags": sorted(norm.attrs.get("ambiguity_flags", [])),
        }
    else:
        norm_snapshot = {
            "norm_op": None,
            "norm_id": None,
            "frame_id": None,
            "frame_predicate": None,
            "temporal_refs": sorted(ir.temporals.keys()),
            "activation_pred": None,
            "exception_count": 0,
            "parse_confidence": None,
            "parse_alternatives": None,
            "ambiguity_flags": [],
        }

    return {
        "ir_version": ir.ir_version,
        "cnl_version": ir.cnl_version,
        "jurisdiction": ir.jurisdiction,
        "norm_count": norm_count,
        "rule_count": rule_count,
        "provenance_keys": sorted(ir.provenance.keys()),
        **norm_snapshot,
    }


def test_v2_parse_replay_is_deterministic_across_fixed_corpus() -> None:
    for case in _load_corpus():
        first_ir, first_diag = parse_cnl_to_ir_with_diagnostics(
            case["sentence"],
            jurisdiction=case.get("jurisdiction", "default"),
        )
        expected_ir = _snapshot_ir(first_ir)

        for _ in range(4):
            replay_ir, replay_diag = parse_cnl_to_ir_with_diagnostics(
                case["sentence"],
                jurisdiction=case.get("jurisdiction", "default"),
            )
            assert _snapshot_ir(replay_ir) == expected_ir
            assert replay_diag == first_diag


@pytest.mark.parametrize(
    "sentence,expected_code",
    [
        (
            "Agency shall inspect records when notified if approved.",
            "multiple_activation_markers",
        ),
        (
            "Vendor shall not disclose data unless consent exists except court order exists.",
            "multiple_exception_markers",
        ),
    ],
)
def test_v2_parse_strict_ambiguity_codes_are_stable(sentence: str, expected_code: str) -> None:
    with pytest.raises(ValueError, match=expected_code):
        parse_cnl_to_ir_with_diagnostics(sentence, jurisdiction="us/federal")


def test_v2_parse_diagnostics_include_confidence_and_markers() -> None:
    ir, diagnostics = parse_cnl_to_ir_with_diagnostics(
        "Controller shall report breach within 24 hours.",
        jurisdiction="us/federal",
    )

    norm = next(iter(ir.norms.values()))
    assert diagnostics["parse_mode"] == "norm"
    assert isinstance(diagnostics["parse_confidence"], float)
    assert diagnostics["parse_confidence"] >= 0.9
    assert diagnostics["temporal_detected"] is True
    assert diagnostics["ambiguity_flags"] == []
    assert norm.attrs.get("parse_confidence") == diagnostics["parse_confidence"]
    assert isinstance(norm.attrs.get("parse_alternatives"), list)
