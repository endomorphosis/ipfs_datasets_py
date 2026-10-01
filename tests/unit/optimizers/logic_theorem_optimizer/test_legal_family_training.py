"""Legal native family integration; typed fixtures are not source-model scores."""
from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_family_training as legal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument, ModalIRFormula, ModalIROperator, ModalIRPredicate,
    ModalIRProvenance, ModalIRFrameLogic, ModalIRFrameLogicTriple,
)


def native_row(name, split):
    identity = "legal-fixture-" + name
    text = f"Agency must publish the {name} notice after receipt."
    provenance = ModalIRProvenance(identity, 0, len(text))
    document = ModalIRDocument(document_id=identity, source="authored_fixture",
        normalized_text=text, formulas=[
            ModalIRFormula(formula_id=identity + ":norm",
                operator=ModalIROperator("deontic", "D", "O", "obligation"),
                predicate=ModalIRPredicate("publish", ["agency", name + "_notice"], "clause"),
                provenance=provenance),
            ModalIRFormula(formula_id=identity + ":time",
                operator=ModalIROperator("temporal", "LTL", "F", "eventually"),
                predicate=ModalIRPredicate("publish", ["agency", name + "_notice"], "clause"),
                provenance=provenance, conditions=["after receipt"])],
        frame_logic=ModalIRFrameLogic(selected_frame="notice", graph_id=identity + ":graph",
            triples=[ModalIRFrameLogicTriple("agency", "publishes", name + "_notice")]))
    return {"document": document, "source_text": text, "source_id": identity,
            "group_id": identity, "split": split}


def test_legal_native_families_train_and_infer(tmp_path):
    training = [native_row(name, "train") for name in ("amber", "cobalt", "ivory")]
    validation = [native_row("violet", "validation")]
    result = legal.train_legal_family_batch(training, validation, output_dir=tmp_path / "first",
        epochs=3, latent_width=2)
    assert result["report"]["trained_logic_families"] == ["deontic", "frame_logic", "tdfol"]
    assert result["report"]["optimizer_steps"] == 3
    inferred = legal.infer_legal_family_batch(result["descriptor"],
        documents=[r["document"] for r in validation], source_texts=[r["source_text"] for r in validation])
    assert set(inferred["families"]) == {"deontic", "frame_logic", "tdfol"}
    assert inferred["formulas_generated"] is False
    assert inferred["objective"] == pytest.approx(result["report"]["after"]["objective"])
    original = Path(result["descriptor"]["path"]).read_bytes()
    child = legal.train_legal_family_batch([native_row("jade", "train")], validation,
        output_dir=tmp_path / "child", parent_descriptor=result["descriptor"], epochs=1, latent_width=2)
    assert Path(result["descriptor"]["path"]).read_bytes() == original
    assert legal._load(child["descriptor"])["training_groups"] == sorted(r["group_id"] for r in
        training + [native_row("jade", "train")])


def test_legal_group_and_test_roles_block_fit(tmp_path):
    training = [native_row("amber", "train")]
    validation = [native_row("violet", "validation")]
    validation[0]["group_id"] = training[0]["group_id"]
    with pytest.raises(ValueError, match="group split leakage"):
        legal.train_legal_family_batch(training, validation, output_dir=tmp_path / "leak")
    assert not (tmp_path / "leak").exists()
    training[0]["split"] = "test"
    with pytest.raises(ValueError, match="test/canary"):
        legal.train_legal_family_batch(training, validation, output_dir=tmp_path / "test")


def test_legal_mismatched_source_rejected(tmp_path):
    training = [native_row("amber", "train")]
    training[0]["source_text"] = "Different source."
    with pytest.raises(ValueError, match="exact source"):
        legal.train_legal_family_batch(training, [native_row("violet", "validation")],
            output_dir=tmp_path / "wrong-source")


def test_historical_legal_group_exclusion_survives_resume(tmp_path):
    training, validation = [native_row("amber", "train")], [native_row("violet", "validation")]
    first = legal.train_legal_family_batch(training, validation, output_dir=tmp_path / "first", epochs=1)
    new_validation = [native_row("violet", "validation")]
    new_validation[0]["group_id"] = training[0]["group_id"]
    with pytest.raises(ValueError, match="validation panel"):
        legal.train_legal_family_batch([native_row("jade", "train")], new_validation,
            output_dir=tmp_path / "bad", parent_descriptor=first["descriptor"], epochs=1)
