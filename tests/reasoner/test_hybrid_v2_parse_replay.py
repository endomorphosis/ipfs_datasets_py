from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_v2_blueprint import (
    CNLParseError,
    LegalIRV2,
    generate_cnl_from_ir,
    parse_cnl_to_ir_with_diagnostics,
)


def _load_corpus() -> list[dict[str, Any]]:
    path = Path(__file__).with_name("fixtures") / "cnl_parse_replay_v2_corpus.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_paraphrase_equivalence_corpus() -> list[dict[str, Any]]:
    path = Path(__file__).with_name("fixtures") / "cnl_parse_paraphrase_equivalence_v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_signature(ir: LegalIRV2) -> Dict[str, Any]:
    norm = next(iter(ir.norms.values()))
    frame = ir.frames[norm.target_frame_ref]

    temporal_relation = None
    temporal_kind = None
    temporal_start = None
    temporal_end = None
    temporal_duration = None
    if norm.temporal_ref and norm.temporal_ref in ir.temporals:
        temporal = ir.temporals[norm.temporal_ref]
        temporal_relation = temporal.relation.value
        temporal_kind = temporal.expr.kind
        temporal_start = temporal.expr.start
        temporal_end = temporal.expr.end
        temporal_duration = temporal.expr.duration

    role_labels: Dict[str, str] = {}
    for role_name, ent_ref in sorted((frame.roles or {}).items()):
        ent = ir.entities.get(ent_ref)
        raw = str((ent.attrs or {}).get("label") if ent else ent_ref)
        role_labels[role_name] = " ".join(raw.lower().split())

    return {
        "norm_op": norm.op.value,
        "frame_predicate": frame.predicate,
        "frame_kind": frame.kind.value,
        "role_labels": role_labels,
        "temporal_relation": temporal_relation,
        "temporal_kind": temporal_kind,
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "temporal_duration": temporal_duration,
    }


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


def test_v2_replay_corpus_has_minimum_canonical_template_coverage() -> None:
    corpus = _load_corpus()
    assert len(corpus) >= 10

    seen_ids = set()
    for case in corpus:
        cid = str(case.get("id") or "")
        assert cid
        assert cid not in seen_ids
        seen_ids.add(cid)


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
    with pytest.raises(CNLParseError, match=expected_code) as exc:
        parse_cnl_to_ir_with_diagnostics(sentence, jurisdiction="us/federal")
    assert exc.value.error_code == "V2_CNL_PARSE_AMBIGUOUS_MARKERS"


def test_v2_parse_empty_sentence_has_stable_error_code() -> None:
    with pytest.raises(CNLParseError) as exc:
        parse_cnl_to_ir_with_diagnostics("   ", jurisdiction="us/federal")
    assert exc.value.error_code == "V2_CNL_PARSE_EMPTY_SENTENCE"


def test_v2_parse_supports_prefix_if_clause_template() -> None:
    ir, diagnostics = parse_cnl_to_ir_with_diagnostics(
        "If wages are due, employer shall pay wages by 2026-01-05.",
        jurisdiction="us/federal",
    )
    norm = next(iter(ir.norms.values()))

    assert diagnostics["activation_marker"] == "if"
    assert diagnostics["temporal_detected"] is True
    assert norm.activation.atom is not None
    assert norm.activation.atom.pred.startswith("if_")
    assert norm.temporal_ref is not None


def test_v2_parse_within_of_anchor_is_normalized() -> None:
    ir_a, _ = parse_cnl_to_ir_with_diagnostics(
        "Controller shall report breach within 24 hours of incident discovery.",
        jurisdiction="us/federal",
    )
    ir_b, _ = parse_cnl_to_ir_with_diagnostics(
        "controller shall report breach within 24 hours of   incident discovery",
        jurisdiction="us/federal",
    )

    norm_a = next(iter(ir_a.norms.values()))
    norm_b = next(iter(ir_b.norms.values()))
    assert norm_a.temporal_ref is not None
    assert norm_b.temporal_ref is not None

    tmp_a = ir_a.temporals[norm_a.temporal_ref]
    tmp_b = ir_b.temporals[norm_b.temporal_ref]
    assert tmp_a.relation.value == "within"
    assert tmp_b.relation.value == "within"
    assert tmp_a.expr.duration == "PT24H"
    assert tmp_b.expr.duration == "PT24H"
    assert tmp_a.expr.start == "incident_discovery"
    assert tmp_b.expr.start == "incident_discovery"


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


def test_v2_lexicon_overrides_affect_rendering_not_canonical_ids() -> None:
    ir, _ = parse_cnl_to_ir_with_diagnostics(
        "Controller shall report breach within 24 hours.",
        jurisdiction="us/federal",
    )
    norm = next(iter(ir.norms.values()))
    frame = ir.frames[norm.target_frame_ref]
    agent_ref = frame.roles.get("agent", "")
    predicate_key = frame.predicate

    baseline = generate_cnl_from_ir(norm.id.ref(), ir)
    custom = generate_cnl_from_ir(
        norm.id.ref(),
        ir,
        lexicon_overrides={
            "modal:shall": "must",
            f"predicate:{predicate_key}": "notify",
            "temporal:within": "inside",
            "entity:" + agent_ref: "Data Controller",
        },
    )

    assert baseline != custom
    assert " must " in custom
    assert " notify " in custom
    assert " inside " in custom
    assert custom.startswith("Data Controller")

    # Lexicon overrides must not mutate semantic IDs or references.
    assert norm.id.ref().startswith("nrm:")
    assert frame.id.ref() == norm.target_frame_ref


def test_v2_lexicon_overrides_rendering_is_deterministic() -> None:
    ir, _ = parse_cnl_to_ir_with_diagnostics(
        "Vendor shall not disclose personal data unless consent is recorded.",
        jurisdiction="us/federal",
    )
    norm_ref = next(iter(ir.norms.keys()))
    overrides = {
        "modal:shall not": "must not",
        "clause:unless": "except when",
    }

    first = generate_cnl_from_ir(norm_ref, ir, lexicon_overrides=overrides)
    for _ in range(4):
        assert generate_cnl_from_ir(norm_ref, ir, lexicon_overrides=overrides) == first


def test_v2_paraphrase_equivalence_corpus_semantics() -> None:
    for case in _load_paraphrase_equivalence_corpus():
        ir_a, _ = parse_cnl_to_ir_with_diagnostics(case["sentence_a"], jurisdiction="us/federal")
        ir_b, _ = parse_cnl_to_ir_with_diagnostics(case["sentence_b"], jurisdiction="us/federal")

        sig_a = _semantic_signature(ir_a)
        sig_b = _semantic_signature(ir_b)

        equivalent = bool(case.get("equivalent"))
        assert "equivalent" in case, case["id"]
        if equivalent:
            assert sig_a == sig_b, case["id"]
        else:
            assert sig_a != sig_b, case["id"]


def test_v2_definition_templates_map_to_explicit_definition_objects() -> None:
    means_ir, means_diag = parse_cnl_to_ir_with_diagnostics(
        "Personal data means information identifying a person.",
        jurisdiction="us/federal",
    )
    includes_ir, includes_diag = parse_cnl_to_ir_with_diagnostics(
        "Sensitive data includes health records and biometrics.",
        jurisdiction="us/federal",
    )

    assert means_diag["parse_mode"] == "definition"
    assert includes_diag["parse_mode"] == "definition"

    means_rule = next(iter(means_ir.rules.values()))
    assert means_rule.mode == "definition"
    assert means_rule.consequent.pred == "definition_of"

    include_preds = {rule.consequent.pred for rule in includes_ir.rules.values()}
    assert include_preds == {"includes_member"}


def test_v2_roundtrip_cnl_generation_preserves_semantics_for_norm_templates() -> None:
    for case in _load_corpus():
        ir, _ = parse_cnl_to_ir_with_diagnostics(
            case["sentence"],
            jurisdiction=case.get("jurisdiction", "us/federal"),
        )
        if not ir.norms:
            continue

        norm_ref = next(iter(ir.norms.keys()))
        regenerated = generate_cnl_from_ir(norm_ref, ir)
        ir_roundtrip, _ = parse_cnl_to_ir_with_diagnostics(
            regenerated,
            jurisdiction=case.get("jurisdiction", "us/federal"),
        )

        assert _semantic_signature(ir_roundtrip) == _semantic_signature(ir), (case["id"], regenerated)
