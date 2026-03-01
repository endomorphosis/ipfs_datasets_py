from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import LegalIR, parse_cnl_sentence


def _load_corpus() -> list[dict[str, Any]]:
    path = Path(__file__).with_name("fixtures") / "cnl_parse_replay_corpus.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_ir(ir: LegalIR) -> Dict[str, Any]:
    norm = next(iter(ir.norms.values()))
    frame = ir.frames[norm.target_frame_ref]

    return {
        "ir_version": ir.version,
        "jurisdiction": ir.jurisdiction,
        "norm_op": norm.op.value,
        "norm_id": norm.id.ref(),
        "frame_id": frame.id.ref(),
        "frame_verb": getattr(frame, "verb", ""),
        "temporal_refs": sorted(ir.temporal.keys()),
        "activation": {
            "op": norm.activation.op,
            "pred": norm.activation.atom.pred if norm.activation.atom else None,
            "args": norm.activation.atom.args if norm.activation.atom else [],
        },
        "exceptions": [
            {
                "op": exc.op,
                "pred": exc.atom.pred if exc.atom else None,
                "args": exc.atom.args if exc.atom else [],
            }
            for exc in norm.exceptions
        ],
        "parse_confidence": norm.attrs.get("parse_confidence"),
        "parse_alternatives": norm.attrs.get("parse_alternatives"),
        "ambiguity_flags": sorted(norm.attrs.get("ambiguity_flags", [])),
    }


def test_parse_replay_is_deterministic_across_fixed_corpus() -> None:
    corpus = _load_corpus()

    for case in corpus:
        first = parse_cnl_sentence(
            case["sentence"],
            jurisdiction=case.get("jurisdiction", "default"),
            fail_on_ambiguity=bool(case.get("fail_on_ambiguity", False)),
        )
        expected = _snapshot_ir(first)

        for _ in range(4):
            replay = parse_cnl_sentence(
                case["sentence"],
                jurisdiction=case.get("jurisdiction", "default"),
                fail_on_ambiguity=bool(case.get("fail_on_ambiguity", False)),
            )
            assert _snapshot_ir(replay) == expected


def test_parse_replay_strict_mode_is_deterministically_rejected_for_ambiguous_case() -> None:
    sentence = "Company A may and shall file report."

    with pytest.raises(ValueError, match="Ambiguous CNL parse: multiple_modal_operators"):
        parse_cnl_sentence(sentence, jurisdiction="us/federal", fail_on_ambiguity=True)

    # Replay strict rejection twice to ensure stable fail-closed behavior.
    with pytest.raises(ValueError, match="Ambiguous CNL parse: multiple_modal_operators"):
        parse_cnl_sentence(sentence, jurisdiction="us/federal", fail_on_ambiguity=True)
