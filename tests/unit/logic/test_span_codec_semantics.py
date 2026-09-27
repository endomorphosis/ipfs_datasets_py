"""Source evidence must preserve clause semantics and historical target floors."""
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.modal.codec import (
    _modal_ir_semantic_family_distribution_with_floors,
    target_family_distribution_for_modal_ir,
)
from ipfs_datasets_py.logic.modal.ir_symbol_catalog import dedupe_modal_ir_formulas
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _formula(identifier="a", family="deontic", symbol="O"):
    return ModalIRFormula(
        formula_id=identifier,
        operator=ModalIROperator(family=family, system="SDL", symbol=symbol, label=family),
        predicate=ModalIRPredicate(name="retain", arguments=["actor:agency"], role="clause"),
        provenance=ModalIRProvenance(source_id="section", start_char=0, end_char=10),
    )


def _document(formulas):
    return ModalIRDocument(document_id="section", source="text", normalized_text="text", formulas=formulas)


@pytest.mark.parametrize("changed_field", [
    "conditions", "exceptions", "operator", "predicate", "provenance", "metadata",
])
def test_deduplication_preserves_semantic_and_source_differences(changed_field):
    first = _formula()
    changes = {
        "conditions": ["if eligible"],
        "exceptions": ["unless emergency"],
        "operator": replace(first.operator, system="different-system"),
        "predicate": replace(first.predicate, role="different-role"),
        "provenance": replace(first.provenance, start_char=20, end_char=30),
        "metadata": {"temporal_scope": "within 10 days"},
    }
    second = replace(first, formula_id="b", **{changed_field: changes[changed_field]})
    duplicate = replace(first, formula_id="c")
    output = dedupe_modal_ir_formulas(_document([first, second, duplicate]))
    assert output.formulas == [first, second]


def test_frame_target_does_not_reduce_the_historical_deontic_floor():
    formulas = [_formula(), _formula("frame", "frame", "Frame")]
    formulas.extend(_formula(str(index), "temporal", "G") for index in range(8))
    distribution = target_family_distribution_for_modal_ir(_document(formulas))
    assert distribution["deontic"] == pytest.approx(0.368)
    assert distribution["frame"] < 0.368
    assert sum(distribution.values()) == pytest.approx(1.0)


def test_frame_semantic_weight_preserves_deontic_and_conditional_floors():
    document = _document([
        _formula("conditional", "conditional_normative", "O|"),
        _formula("frame", "frame", "Frame"),
    ])
    distribution = _modal_ir_semantic_family_distribution_with_floors(
        {"deontic": 0.1, "conditional_normative": 0.1, "frame": 0.8}, document,
    )
    assert distribution["deontic"] == pytest.approx(0.368)
    assert distribution["conditional_normative"] == pytest.approx(0.368)
    assert distribution["frame"] == pytest.approx(0.264)
    assert sum(distribution.values()) == pytest.approx(1.0)
