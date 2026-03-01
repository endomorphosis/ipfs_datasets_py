from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import (
    compile_to_dcec,
    compile_to_temporal_deontic_fol,
    parse_cnl_sentence,
)


def _load_cases() -> list[dict[str, Any]]:
    path = Path(__file__).with_name("fixtures") / "compiler_parity_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_compiler_parity_fixtures_match_expected_outputs() -> None:
    for case in _load_cases():
        ir = parse_cnl_sentence(
            case["sentence"],
            jurisdiction=case.get("jurisdiction", "us/federal"),
            fail_on_ambiguity=False,
        )
        assert compile_to_dcec(ir) == case["expected_dcec"], case["id"]
        assert compile_to_temporal_deontic_fol(ir) == case["expected_tdfol"], case["id"]


def test_compiler_parity_fixtures_are_replay_stable() -> None:
    for case in _load_cases():
        ir_a = parse_cnl_sentence(case["sentence"], jurisdiction=case.get("jurisdiction", "us/federal"))
        ir_b = parse_cnl_sentence(case["sentence"], jurisdiction=case.get("jurisdiction", "us/federal"))
        assert compile_to_dcec(ir_a) == compile_to_dcec(ir_b), case["id"]
        assert compile_to_temporal_deontic_fol(ir_a) == compile_to_temporal_deontic_fol(ir_b), case["id"]
