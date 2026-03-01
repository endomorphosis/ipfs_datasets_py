from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import compile_to_dcec, parse_cnl_sentence


def _load_cases() -> list[dict[str, Any]]:
    path = Path(__file__).with_name("fixtures") / "dcec_conformance_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_compile_to_dcec_matches_golden_conformance_fixtures() -> None:
    for case in _load_cases():
        ir = parse_cnl_sentence(
            case["sentence"],
            jurisdiction=case.get("jurisdiction", "default"),
            fail_on_ambiguity=False,
        )
        formulas = compile_to_dcec(ir)
        assert formulas == case["expected_formulas"], case["id"]


def test_compile_to_dcec_is_replay_stable_for_fixed_inputs() -> None:
    for case in _load_cases():
        ir_a = parse_cnl_sentence(case["sentence"], jurisdiction=case.get("jurisdiction", "default"))
        ir_b = parse_cnl_sentence(case["sentence"], jurisdiction=case.get("jurisdiction", "default"))
        assert compile_to_dcec(ir_a) == compile_to_dcec(ir_b), case["id"]
