"""Synthetic fixtures for matched source-copy dimensional experiments."""
from copy import deepcopy
import json

import pytest

from scripts.ops.legal_ir import run_legal_open_vocabulary_experiment as experiment


def data(dimension=768):
    sources, contexts = [], []
    for index, family in enumerate(("a", "a", "b", "b")):
        text = f"The synthetic officer {index} must file the record."
        source_hash = experiment.hashlib.sha256(text.encode()).hexdigest()
        vector = [float(index + 1)] * dimension
        row = {"id": f"synthetic-{index}", "source_text": text, "source_sha256": source_hash,
               "family_group": family, "canonical_ir": {"rules": []}, "embedding": [0.] * 384}
        receipt = {"schema": "synthetic-native-stage/v1", "id": row["id"], "source_sha256": source_hash,
                   "dimension": dimension, "vector_sha256": experiment.digest(vector), "target_access": False,
                   "admitted": False, "qualified": False, "source_semantics_verified": False}
        receipt["receipt_sha256"] = experiment.digest(receipt)
        sources.append(row)
        contexts.append({"id": row["id"], "source_sha256": source_hash, "context": vector,
                         "context_sha256": experiment.digest(vector), "native_stage_receipt": receipt})
    return sources, contexts


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_context_validation_is_dimensional_source_bound_and_target_free(dimension):
    sources, contexts = data(dimension)
    experiment.verify_context_rows(sources, contexts, dimension=dimension)
    assert contexts[0]["native_stage_receipt"]["target_access"] is False


@pytest.mark.parametrize("edit,match", [
    (lambda rows: rows.reverse(), "identity/order"),
    (lambda rows: rows[0].update(source_sha256="0" * 64), "identity/order"),
    (lambda rows: rows[0].update(canonical_ir={}), "target-free"),
    (lambda rows: rows[0]["context"].pop(), "finite dimensional"),
    (lambda rows: rows[0]["context"].__setitem__(0, float("inf")), "finite dimensional"),
    (lambda rows: rows[0]["native_stage_receipt"].update(source_sha256="0" * 64), "receipt source"),
    (lambda rows: rows[0]["native_stage_receipt"].update(target_access=True), "receipt source"),
    (lambda rows: rows[0]["native_stage_receipt"].update(qualified=True), "grant authority"),
    (lambda rows: rows[0]["native_stage_receipt"].update(receipt_sha256="0" * 64), "receipt digest"),
])
def test_invalid_receipt_or_vector_bindings_fail(edit, match):
    sources, contexts = data()
    edit(contexts)
    with pytest.raises(ValueError, match=match):
        experiment.verify_context_rows(sources, contexts, dimension=768)


def test_source_only_training_has_no_latent_field():
    sources, _ = data()
    trained = experiment.training_rows(sources)
    assert all(set(row) == {"id", "source_text", "canonical_ir"} for row in trained)


def test_native_training_keeps_exact_context_dimension():
    sources, contexts = data()
    trained = experiment.training_rows(sources, contexts)
    assert all(len(row["latent"]) == 768 for row in trained)
    contexts.reverse()
    with pytest.raises(ValueError, match="source-context"):
        experiment.training_rows(sources, contexts)


def test_swap_is_bijection_crosses_families_and_preserves_donor_provenance():
    sources, contexts = data()
    before = deepcopy(contexts)
    swapped = experiment.cross_family_contexts(sources, contexts)
    assert {row["donor_id"] for row in swapped} == {row["id"] for row in sources}
    assert all(row["receiving_family_group"] != row["donor_family_group"] for row in swapped)
    assert all(row["source_sha256"] != row["donor_source_sha256"] for row in swapped)
    assert all(row["donor_native_stage_receipt"]["source_sha256"] == row["donor_source_sha256"] for row in swapped)
    assert all("native_stage_receipt" not in row for row in swapped)
    assert contexts == before


def test_swap_fails_if_all_sources_have_same_family():
    sources, contexts = data()
    for row in sources:
        row["family_group"] = "one"
    with pytest.raises(ValueError, match="no source-disjoint"):
        experiment.cross_family_contexts(sources, contexts)


class RecordingDecoder:
    def __init__(self):
        self.calls = []

    def decode_formal_logic(self, texts, latents, *, latent_ablation):
        self.calls.append((texts, latents, latent_ablation))
        return {"target_access": False, "teacher_forcing": False,
                "rows": [{"source_sha256": experiment.hashlib.sha256(text.encode()).hexdigest(), "status": "abstained"} for text in texts]}


def test_zero_dimensional_generation_passes_only_text_and_none():
    sources, _ = data()
    decoder = RecordingDecoder()
    result = experiment.generate(decoder, sources)
    assert decoder.calls == [([row["source_text"] for row in sources], None, "none")]
    assert result["control_receipts"] == []
    assert result["generation_inputs_contained_references"] is False


@pytest.mark.parametrize("control,ablation", [("source", "none"), ("zero", "zero"), ("disabled", "disabled")])
def test_generations_bind_zero_and_disabled_controls_without_384_padding(control, ablation):
    sources, contexts = data()
    decoder = RecordingDecoder()
    result = experiment.generate(decoder, sources, contexts, dimension=768, control=control)
    assert all(len(vector) == 768 for vector in decoder.calls[0][1])
    assert decoder.calls[0][2] == ablation
    assert all(row["context_disabled"] == (control == "disabled") for row in result["control_receipts"])
    if control == "zero":
        assert all(row["effective_context_sha256"] == experiment.digest([0.] * 768) for row in result["control_receipts"])


def test_mismatched_dimension_never_reaches_decoder():
    sources, contexts = data()
    with pytest.raises(ValueError, match="source/context"):
        experiment.generate(RecordingDecoder(), sources, contexts, dimension=384)


def test_tuning_selector_uses_earliest_tie_without_seed_selection():
    early = {"new_optimizer_steps": 400, "tuning_exact": 90}
    late = {"new_optimizer_steps": 800, "tuning_exact": 90}
    assert experiment.select_stage([late, early]) == early


def test_artifact_reference_enforces_real_bytes(tmp_path):
    path = tmp_path / "fixture.json"; path.write_text('{"synthetic": true}')
    ref = experiment.file_ref(path)
    assert experiment.read_ref(ref) == {"synthetic": True}
    path.write_text('{"synthetic": false}')
    with pytest.raises(ValueError, match="reference differs"):
        experiment.read_ref(ref)


def test_duplicate_keys_and_nonfinite_values_fail(tmp_path):
    path = tmp_path / "fixture.json"
    for raw in ('{"x":1,"x":2}', '{"x":NaN}'):
        path.write_text(raw)
        with pytest.raises(ValueError):
            experiment.read(path)
