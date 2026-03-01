from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import (
    ActionFrame,
    CanonicalId,
    compile_to_temporal_deontic_fol,
    FrameKind,
    LegalIR,
    TemporalConstraint,
    TemporalExpr,
    TemporalRelation,
    normalize_ir,
    parse_cnl_sentence,
)


def test_normalize_ir_role_aliases_and_verb_lexical_forms() -> None:
    ir = LegalIR(jurisdiction="us/federal")
    frame_id = CanonicalId("frm", "f1")
    frame = ActionFrame(
        id=frame_id,
        kind=FrameKind.ACTION,
        verb="  FILE-Report!! ",
        roles={
            "Subject": "ent:company",
            "OBJECT": "ent:report",
            "recipient": "ent:agency",
        },
        attrs={"action_text": "  FILE Report!!! "},
    )
    ir.frames[frame_id.ref()] = frame

    out = normalize_ir(ir)
    norm_frame = out.frames[frame_id.ref()]

    assert norm_frame.roles == {
        "agent": "ent:company",
        "patient": "ent:report",
        "beneficiary": "ent:agency",
    }
    assert getattr(norm_frame, "verb") == "file report"
    assert norm_frame.attrs["action_text"] == "file report"


def test_normalize_ir_temporal_duration_units_to_iso_forms() -> None:
    ir = LegalIR(jurisdiction="us/federal")
    t1 = CanonicalId("tmp", "d1")
    t2 = CanonicalId("tmp", "d2")

    ir.temporal[t1.ref()] = TemporalConstraint(
        id=t1,
        expr=TemporalExpr(kind="window", duration="30days"),
        relation=TemporalRelation.WITHIN,
    )
    ir.temporal[t2.ref()] = TemporalConstraint(
        id=t2,
        expr=TemporalExpr(kind="window", duration="48 hours"),
        relation=TemporalRelation.WITHIN,
    )

    out = normalize_ir(ir)

    assert out.temporal[t1.ref()].expr.duration == "P30D"
    assert out.temporal[t2.ref()].expr.duration == "PT48H"


def test_normalize_ir_jurisdiction_policy_for_federal_state_agency() -> None:
    ir = parse_cnl_sentence("Company A shall file report within 30 days.", jurisdiction="us/federal")
    norm = next(iter(ir.norms.values()))
    frame = ir.frames[norm.target_frame_ref]

    frame.jurisdiction = "ca"
    norm.jurisdiction = "agency:Department of Labor"

    out = normalize_ir(ir)

    assert out.jurisdiction == "Federal"
    assert out.frames[frame.id.ref()].jurisdiction == "State:CA"
    assert out.norms[norm.id.ref()].jurisdiction == "Agency:Department of Labor"


def test_canonical_predicate_mode_and_id_stability_across_replay() -> None:
    sentence = "Company A shall submit backup report within 10 days unless emergency."

    ir_a = normalize_ir(parse_cnl_sentence(sentence, jurisdiction="us/federal"))
    ir_b = normalize_ir(parse_cnl_sentence(sentence, jurisdiction="us/federal"))

    assert sorted(ir_a.frames.keys()) == sorted(ir_b.frames.keys())
    assert sorted(ir_a.norms.keys()) == sorted(ir_b.norms.keys())
    assert sorted(ir_a.temporal.keys()) == sorted(ir_b.temporal.keys())

    tdfol_canonical = compile_to_temporal_deontic_fol(ir_a, canonical_predicates=True)
    tdfol_lexical = compile_to_temporal_deontic_fol(ir_a, canonical_predicates=False)

    assert "Act_" in tdfol_canonical[0]
    assert "Act_" not in tdfol_lexical[0]
