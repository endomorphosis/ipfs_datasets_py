"""Temporal Deontic FOL compiler conformance tests (golden fixture based)."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import (
    compile_to_temporal_deontic_fol,
    parse_cnl_sentence,
)


def _load_cases() -> list[dict]:
    fixture_path = Path(__file__).parent / "fixtures" / "tdfol_conformance_cases.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_tdfol_conformance_cases_match_golden_outputs() -> None:
    """Compile representative CNL sentences and assert exact TDFOL outputs."""
    for case in _load_cases():
        ir = parse_cnl_sentence(
            case["sentence"],
            jurisdiction=case.get("jurisdiction", "us/federal"),
        )
        got = compile_to_temporal_deontic_fol(ir)
        assert got == case["expected_temporal_deontic_fol"], case["id"]
