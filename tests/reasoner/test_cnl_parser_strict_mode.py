from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import DeonticOp, parse_cnl_sentence


def test_parse_cnl_sentence_includes_ranked_alternatives_and_confidence() -> None:
    ir = parse_cnl_sentence("Company A shall file report.", jurisdiction="us/federal")
    norm = next(iter(ir.norms.values()))

    assert norm.op == DeonticOp.O
    assert isinstance(norm.attrs.get("parse_confidence"), float)
    assert norm.attrs["parse_confidence"] >= 0.9
    assert isinstance(norm.attrs.get("parse_alternatives"), list)
    assert norm.attrs["parse_alternatives"][0]["operator"] == "O"


def test_parse_cnl_sentence_non_strict_keeps_best_candidate_on_ambiguous_modality() -> None:
    ir = parse_cnl_sentence(
        "Company A may and shall file report.",
        jurisdiction="us/federal",
        fail_on_ambiguity=False,
    )
    norm = next(iter(ir.norms.values()))

    assert norm.op == DeonticOp.O
    assert "multiple_modal_operators" in norm.attrs.get("ambiguity_flags", [])


def test_parse_cnl_sentence_strict_raises_on_ambiguous_modality() -> None:
    with pytest.raises(ValueError, match="Ambiguous CNL parse"):
        parse_cnl_sentence(
            "Company A may and shall file report.",
            jurisdiction="us/federal",
            fail_on_ambiguity=True,
        )


def test_parse_cnl_sentence_strict_raises_on_multiple_activation_markers() -> None:
    with pytest.raises(ValueError, match="multiple_activation_markers"):
        parse_cnl_sentence(
            "Company A shall file report when contract starts if notified.",
            jurisdiction="us/federal",
            fail_on_ambiguity=True,
        )


def test_parse_cnl_sentence_template_means_emits_definition_rule() -> None:
    ir = parse_cnl_sentence("Personal data means information identifying a person.")

    assert len(ir.rules) == 1
    rule = next(iter(ir.rules.values()))
    assert rule.mode == "definition"
    assert rule.consequent.pred == "definition_of"
    assert rule.consequent.args[0] == "Personal data"


def test_parse_cnl_sentence_template_includes_emits_member_rules() -> None:
    ir = parse_cnl_sentence("Sensitive data includes health records, financial records, and biometrics.")

    members = sorted(r.consequent.args[1] for r in ir.rules.values() if r.consequent.pred == "includes_member")
    assert members == ["biometrics", "financial records", "health records"]
