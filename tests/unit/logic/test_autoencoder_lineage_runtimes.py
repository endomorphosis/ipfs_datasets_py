"""Side-by-side runtime isolation; synthetic vectors confer no qualification."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from dataclasses import replace

import pytest


PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"


@pytest.fixture(params=("legacy_v1", "current_v2"))
def lineage(request):
    return importlib.import_module(f"{PREFIX}.autoencoder_lineages.{request.param}")


def sample(lineage, suffix="reports", *, dimension=None):
    """Construct typed input directly, without parser or frame-ranker side effects."""
    ir = importlib.import_module(
        lineage.LegalSample.__module__.rsplit(".", 1)[0] + ".modal_ir"
    )
    text = f"The agency shall submit {suffix}."
    width = lineage.DIMENSION if dimension is None else dimension
    formula = ir.ModalIRFormula(
        formula_id=suffix,
        operator=ir.ModalIROperator(
            family="deontic", system="SDL", symbol="O", label="obligation"
        ),
        predicate=ir.ModalIRPredicate(name="submit", arguments=["agency", suffix]),
        provenance=ir.ModalIRProvenance(
            source_id=suffix, start_char=0, end_char=len(text)
        ),
    )
    result = lineage.LegalSample(
        sample_id=suffix,
        source="us_code",
        title="5",
        section="552",
        citation="5 U.S.C. 552",
        text=text,
        normalized_text=text,
        embedding_model="test:explicit-synthetic-vector-not-semantic",
        embedding_vector=[(i % 7 - 3) / 7 for i in range(width)],
        modal_ir=ir.ModalIRDocument(
            document_id=suffix,
            source="us_code",
            normalized_text=text,
            formulas=[formula],
        ),
    )
    result.validate()
    return result


def test_imports_coexist_without_replacing_current_modules():
    current = importlib.import_module(f"{PREFIX}.modal_autoencoder")
    canonical_parser = importlib.import_module(
        "ipfs_datasets_py.logic.deontic.utils.deontic_parser"
    )
    legacy = importlib.import_module(f"{PREFIX}.autoencoder_lineages.legacy_v1")
    student = importlib.import_module(f"{PREFIX}.autoencoder_lineages.current_v2")
    assert sys.modules[f"{PREFIX}.modal_autoencoder"] is current
    assert sys.modules[canonical_parser.__name__] is canonical_parser
    assert student.TrainingState is current.ModalAutoencoderTrainingState
    assert legacy.TrainingState is not student.TrainingState
    assert legacy.Autoencoder is not student.Autoencoder
    assert (legacy.DIMENSION, student.DIMENSION) == (8, 384)
    assert legacy.LINEAGE_ID != student.LINEAGE_ID


def test_encode_decode_and_bridge_off_evaluation_preserve_width(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    encoded = model.encode(row, use_sample_memory=False)
    decoded = model.decode(encoded)
    assert len(decoded) == lineage.DIMENSION
    assert all(math.isfinite(value) for value in decoded)
    metrics = model.evaluate(
        [row], legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
        use_sample_memory=False,
    )
    assert metrics.sample_count == 1
    assert metrics.legal_ir_target_count == 0  # Deliberately no legal-IR qualification.
    assert len(metrics.decoded_embeddings[row.sample_id]) == lineage.DIMENSION
    assert math.isfinite(metrics.reconstruction_loss)


@pytest.mark.parametrize("operation", ("encode", "evaluate", "train"))
def test_wrong_input_width_rejected_before_state_changes(lineage, operation):
    model = lineage.Autoencoder(compute_device="cpu")
    wrong = sample(lineage, dimension=384 if lineage.DIMENSION == 8 else 8)
    before = model.state.to_dict()
    with pytest.raises(ValueError):
        if operation == "encode":
            model.encode(wrong, use_sample_memory=False)
        elif operation == "evaluate":
            model.evaluate([wrong], use_sample_memory=False)
        else:
            model.train_generalizable_projection([wrong], epochs=1)
    assert model.state.to_dict() == before


def test_foreign_lineage_state_rejected(lineage):
    other_name = "current_v2" if lineage.DIMENSION == 8 else "legacy_v1"
    other = importlib.import_module(f"{PREFIX}.autoencoder_lineages.{other_name}")
    foreign = other.TrainingState()
    before = foreign.to_dict()
    with pytest.raises((TypeError, ValueError)):
        lineage.Autoencoder(state=foreign, compute_device="cpu")
    assert foreign.to_dict() == before


def test_decode_rejects_projection_from_other_input_space(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    encoded = model.encode(sample(lineage), use_sample_memory=False)
    encoded["embedding_projection"] = [0.1] * (384 if lineage.DIMENSION == 8 else 8)
    with pytest.raises(ValueError):
        model.decode(encoded)


def test_nonfinite_vectors_rejected_before_state_changes(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    row = sample(lineage)
    row = replace(row, embedding_vector=[float("nan")] * lineage.DIMENSION)
    before = model.state.to_dict()
    with pytest.raises(ValueError):
        model.encode(row, use_sample_memory=False)
    assert model.state.to_dict() == before


def test_wrong_validation_width_rejected_before_training(lineage):
    model = lineage.Autoencoder(compute_device="cpu")
    before = model.state.to_dict()
    with pytest.raises(ValueError):
        model.train_generalizable_projection(
            [sample(lineage)],
            validation_samples=[sample(lineage, "notices", dimension=12)],
            epochs=1,
        )
    assert model.state.to_dict() == before


def test_state_wrong_width_rejected_without_mutation(lineage):
    state = lineage.TrainingState(decoded_embeddings={"fixture": [0.1] * 12})
    before = state.to_dict()
    with pytest.raises(ValueError):
        lineage.Autoencoder(state=state, compute_device="cpu")
    assert state.to_dict() == before


def test_projection_updates_only_the_selected_lineage(lineage):
    """Real bounded training of synthetic features, never a semantics benchmark."""
    other_name = "current_v2" if lineage.DIMENSION == 8 else "legacy_v1"
    other = importlib.import_module(f"{PREFIX}.autoencoder_lineages.{other_name}")
    untouched = other.Autoencoder(compute_device="cpu")
    untouched_before = untouched.state.to_dict()
    model = lineage.Autoencoder(compute_device="cpu")
    before = model.state.to_dict()
    train, validation = sample(lineage), sample(lineage, "notices")
    options = dict(
        epochs=1, learning_rate=0.01, max_seconds=15,
        max_line_search_attempts=1, projection_update_backend="python_sparse_batch",
        projection_max_update_families=4 if lineage.DIMENSION == 8 else 1,
        legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
    )
    if lineage.DIMENSION == 384:
        options.update(
            projection_candidate_update_order=("decoded_embedding",),
            projection_reconstruction_objective="raw_decoder",
        )
    report = model.train_generalizable_projection(
        [train], validation_samples=[validation], **options
    )
    assert report["accepted_epochs"] == 1
    assert model.state.to_dict() != before
    assert untouched.state.to_dict() == untouched_before
    assert model.state.decoded_embeddings == {}  # Training must not memorize the rows.


def _checkpoint(lineage, tmp_path, *, width=None):
    path = tmp_path / "fixture.state.json"
    lineage.TrainingState(decoded_embeddings={
        "fixture": [0.1] * (lineage.DIMENSION if width is None else width)
    }).save_json(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def test_checkpoint_load_retains_own_state_class_and_original_bytes(lineage, tmp_path):
    path, digest = _checkpoint(lineage, tmp_path)
    original = path.read_bytes()
    loaded = lineage.load_checkpoint(path, expected_sha256=digest, compute_device="cpu")
    assert type(loaded.state) is lineage.TrainingState
    assert len(loaded.state.decoded_embeddings["fixture"]) == lineage.DIMENSION
    assert path.read_bytes() == original
    assert loaded.describe()["lineage_id"] == lineage.LINEAGE_ID
    for field in ("admitted", "semantic_qualification", "semantic_embedding_verified",
                  "independent_formula_decoder"):
        assert loaded.describe()[field] is False


def test_checkpoint_tamper_and_width_mismatch_rejected(lineage, tmp_path):
    path, digest = _checkpoint(lineage, tmp_path, width=12)
    with pytest.raises(ValueError):
        lineage.load_checkpoint(path, expected_sha256=digest, compute_device="cpu")
    path, digest = _checkpoint(lineage, tmp_path)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        lineage.load_checkpoint(path, expected_sha256=digest, compute_device="cpu")


def test_checkpoint_requires_hash_and_existing_file(lineage, tmp_path):
    path, _digest = _checkpoint(lineage, tmp_path)
    with pytest.raises((TypeError, ValueError)):
        lineage.load_checkpoint(path)
    with pytest.raises(FileNotFoundError):
        lineage.load_checkpoint(tmp_path / "missing.json", expected_sha256="0" * 64)


def test_explicit_sample_builder_rejects_missing_provenance_and_width_before_parser(
    lineage, monkeypatch,
):
    def must_not_parse(**kwargs):
        raise AssertionError("invalid input reached the parser-backed builder")

    monkeypatch.setattr(lineage, "_build_sample", must_not_parse)
    with pytest.raises(TypeError):
        lineage.build_sample(title="5", section="552", text="The agency shall submit reports.")
    with pytest.raises(ValueError):
        lineage.build_sample(
            embedding_vector=[0.1] * 12, embedding_model="test:explicit",
            title="5", section="552", text="The agency shall submit reports.",
        )


@pytest.mark.parametrize("raw_architecture", ("legacy_dense_v1", None))
def test_checkpoint_reports_compatibility_relabel_without_rewriting_source(
    lineage, tmp_path, raw_architecture,
):
    path, _digest = _checkpoint(lineage, tmp_path)
    raw = json.loads(path.read_text())
    if raw_architecture is None:
        raw.pop("architecture_version", None)
    else:
        raw["architecture_version"] = raw_architecture
    path.write_text(json.dumps(raw))
    original = path.read_bytes()
    loaded = lineage.load_checkpoint(
        path, expected_sha256=hashlib.sha256(original).hexdigest(), compute_device="cpu"
    )
    identity = loaded.describe()["checkpoint_identity"]
    assert identity["raw_declared_architecture_version"] == raw_architecture
    assert identity["loaded_architecture_version"] == loaded.state.architecture_version
    assert identity["compatibility_architecture_relabelled"] is True
    assert identity["exact_published_legacy_teacher"] is False
    assert path.read_bytes() == original


@pytest.mark.parametrize("value", ("0.1", float("nan")))
def test_checkpoint_rejects_invalid_values_before_numeric_coercion(lineage, tmp_path, value):
    path, _digest = _checkpoint(lineage, tmp_path)
    raw = json.loads(path.read_text())
    raw["decoded_embeddings"]["fixture"][0] = value
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="finite"):
        lineage.load_checkpoint(
            path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            compute_device="cpu",
        )


def test_convenience_loader_rejects_compact_binary_without_hidden_conversion(lineage, tmp_path):
    path = tmp_path / "compact.state"
    path.write_bytes(b"LIRMAECP" + b"not-a-json-state")
    with pytest.raises(ValueError, match="JSON only"):
        lineage.load_checkpoint(
            path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )


def test_current_profile_defaults_to_raw_training_with_disjoint_validation():
    current = importlib.import_module(f"{PREFIX}.autoencoder_lineages.current_v2")
    model = current.Autoencoder(compute_device="cpu")
    before = model.state.to_dict()
    with pytest.raises(ValueError, match="raw_decoder"):
        model.train_generalizable_projection([sample(current)], epochs=1)
    assert model.state.to_dict() == before
