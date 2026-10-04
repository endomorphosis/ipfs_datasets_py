from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import (
    compile_with_provenance_index,
    parse_cnl_sentence,
)


def test_compile_with_provenance_index_dcec_shape_and_refs() -> None:
    ir = parse_cnl_sentence(
        "Company A shall submit backup report within 10 days unless emergency.",
        jurisdiction="us/federal",
    )

    compiled = compile_with_provenance_index(ir, backend="dcec")

    assert compiled["backend"] == "dcec"
    assert len(compiled["formulas"]) == 1
    assert len(compiled["provenance_index"]) == 1

    entry = next(iter(compiled["provenance_index"].values()))
    assert entry["formula"] == compiled["formulas"][0]
    assert entry["ir_refs"]["norm_ref"].startswith("nrm:")
    assert entry["ir_refs"]["frame_ref"].startswith("frm:")
    assert entry["ir_refs"]["temporal_ref"].startswith("tmp:")
    assert entry["ir_refs"]["entity_refs"]
    assert "company a" in entry["ir_refs"]["source"]
    assert any("unless emergency" in s for s in entry["ir_refs"]["source"])


def test_compile_with_provenance_index_tdfol_is_deterministic() -> None:
    sentence = "Agency may disclose notice when authorized."
    ir_a = parse_cnl_sentence(sentence, jurisdiction="us/federal")
    ir_b = parse_cnl_sentence(sentence, jurisdiction="us/federal")

    out_a = compile_with_provenance_index(ir_a, backend="tdfol")
    out_b = compile_with_provenance_index(ir_b, backend="tdfol")

    assert out_a == out_b
    assert out_a["backend"] == "tdfol"
    assert len(out_a["provenance_index"]) == len(out_a["formulas"])
