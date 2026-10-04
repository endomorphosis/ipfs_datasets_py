"""Serialized inventory tests; fixtures are synthetic, never teacher evidence."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

# Load the dependency-free helper without importing the package's optional ML
# dependencies or running package bootstrap hooks.
_ROOT = Path(__file__).resolve().parents[5]
_FILE = _ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_migration_inventory.py"
_SPEC = importlib.util.spec_from_file_location("gte_migration_inventory_test_subject", _FILE)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def tensor(*shape):
    if not shape:
        return 0.25
    return [tensor(*shape[1:]) for _ in range(shape[0])]


def gru(hidden, width, name):
    return {name + ".weight_ih_l0": tensor(hidden * 3, width),
            name + ".weight_hh_l0": tensor(hidden * 3, hidden),
            name + ".bias_ih_l0": tensor(hidden * 3),
            name + ".bias_hh_l0": tensor(hidden * 3)}


def sequence(schema="shared-source-384-autoencoder/v2"):
    dimension, hidden, token_width, projection, count = 384, 2, 2, 2, 4
    state = {"projection_down.weight": tensor(projection, dimension),
             "projection_down.bias": tensor(projection),
             "projection_up.weight": tensor(dimension, projection),
             "projection_up.bias": tensor(dimension),
             "condition.weight": tensor(hidden, dimension), "condition.bias": tensor(hidden),
             "target_embedding.weight": tensor(count, token_width),
             "output.weight": tensor(count, hidden), "output.bias": tensor(count),
             **gru(hidden, token_width, "decoder")}
    checkpoint = {"schema": schema, "domain_id": "legal_ir", "dimension": dimension,
                  "architecture": "residual-projection-latent-formula-gru/v1",
                  "config": {"hidden_size": hidden, "token_embedding_dim": token_width,
                             "projection_width": projection, "strategy": "semantic_v2"},
                  "codec": {"schema": "typed-json-lexical/v1",
                            "target_vocabulary": ["<pad>", "<bos>", "<eos>", "{}é"]},
                  "input_transform": {"mode": "center_rms", "mean": [0.] * dimension,
                                      "scale": 0.125, "origin": "training_only"},
                  "model_state": state, "weights_sha256": digest(state),
                  "implementation": {"runtime_sha256": "a" * 64},
                  "parent_binding": {"dimension": 384, "runtime_profile": "fixture/v1"}}
    if schema == "modal-latent-formula-checkpoint/v1":
        checkpoint["binding"] = {"domain": "legal_ir", "dimension": 384,
                                  "lineage_id": "current_legal_v2", "runtime_profile": "fixture/v1"}
        checkpoint.pop("dimension")
        checkpoint.pop("domain_id")
        checkpoint.pop("input_transform")
        checkpoint["optimizer_state"] = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
    return checkpoint


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def write(tmp_path, value):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_source_inventory_uses_exact_bytes_and_declared_contract(tmp_path):
    checkpoint = sequence()
    path = write(tmp_path, checkpoint)
    before = path.read_bytes()
    report = subject.inspect_checkpoint(path)
    assert path.read_bytes() == before
    assert report["sha256"] == hashlib.sha256(before).hexdigest()
    assert report["bytes"] == len(before)
    assert report["checkpoint_schema"] == checkpoint["schema"]
    assert report["family"] == "source_sequence"
    assert report["domain"] == "legal_ir" and report["dimension"] == 384
    assert report["supported_for_transfer"] is True
    assert report["metadata"]["implementation"] == checkpoint["implementation"]
    assert report["metadata"]["input_transform"] == checkpoint["input_transform"]
    assert report["decoder_codec"]["target_vocabulary_count"] == 4
    assert report["decoder_codec"]["sha256"] == digest(checkpoint["codec"])
    tensors = {row["name"]: row for row in report["tensor_inventory"]}
    assert tensors["model_state.condition.weight"]["shape"] == [2, 384]
    assert tensors["model_state.condition.weight"]["transfer_category"] == "dimension_dependent"
    assert tensors["model_state.condition.bias"]["transfer_category"] == "architecture_compatible"
    assert tensors["model_state.output.weight"]["transfer_category"] == "token_identity_mapped"
    assert report["differentiability"]["differentiable"] is True
    assert report["differentiability"]["whole_source_pipeline_differentiable"] is None
    assert report["teacher_qualified"] is False and report["external_producer_verified"] is False
    assert report["optimizer_state"]["present"] is False


@pytest.mark.parametrize("mutation,match", [
    (lambda row: row["model_state"]["condition.weight"][0].pop(), "rectangular"),
    (lambda row: row["model_state"]["condition.weight"].pop(), "shape differs"),
    (lambda row: row["model_state"]["output.bias"].__setitem__(0, True), "bool is forbidden"),
    (lambda row: row.__setitem__("dimension", 768), "dimension differs"),
    (lambda row: row.__setitem__("dimension", True), "positive integer"),
    (lambda row: row["input_transform"].__setitem__("mean", [0.] * 383), "mean dimension"),
    (lambda row: row["input_transform"].__setitem__("scale", False), "bool is forbidden"),
    (lambda row: row.__setitem__("weights_sha256", "a" * 64), "differs from serialized tensors"),
    (lambda row: row["codec"]["target_vocabulary"].__setitem__(3, "<eos>"), "duplicate tokens"),
])
def test_corrupt_known_sequence_contract_fails(tmp_path, mutation, match):
    checkpoint = sequence()
    mutation(checkpoint)
    with pytest.raises(ValueError, match=match):
        subject.inspect_checkpoint(write(tmp_path, checkpoint))


@pytest.mark.parametrize("raw", [
    '{"schema":"x","weights":{"x":[NaN]}}',
    '{"schema":"x","weights":{"x":[Infinity]}}',
    '{"schema":"x","note":-Infinity}',
    '{"schema":"x","note":1e999}',
    '{"schema":"x","schema":"y"}',
    '{"schema":"x","weights":{"x":[1],"x":[2]}}',
    '[]',
])
def test_json_must_be_unique_finite_object(tmp_path, raw):
    path = tmp_path / "checkpoint.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        subject.inspect_checkpoint(path)


def test_bounds_are_enforced_before_json_loading(tmp_path):
    path = write(tmp_path, {"schema": "unknown"})
    with pytest.raises(ValueError, match="exceeds max_bytes"):
        subject.inspect_checkpoint(path, max_bytes=2)
    with pytest.raises(ValueError, match="positive integer"):
        subject.inspect_checkpoint(path, max_bytes=True)
    with pytest.raises(ValueError, match="regular file"):
        subject.inspect_checkpoint(tmp_path)


def test_unknown_schema_is_not_identified_by_384d_shape(tmp_path):
    report = subject.inspect_checkpoint(write(tmp_path, {
        "schema": "unrecognized-checkpoint/v9", "dimension": 384,
        "weights": {"condition.weight": tensor(2, 384)}}))
    assert report["dimension"] == 384
    assert report["family"] == "unknown"
    assert report["supported_for_transfer"] is False
    assert report["differentiability"]["differentiable"] is None
    assert report["tensor_inventory"][0]["transfer_category"] == "unclassified"


def test_bound_modal_head_reports_optimizer_presence_without_resume_guarantee(tmp_path):
    checkpoint = sequence("modal-latent-formula-checkpoint/v1")
    report = subject.inspect_checkpoint(write(tmp_path, checkpoint))
    assert report["family"] == "latent_formula_head"
    assert report["runtime"] == "fixture/v1"
    assert report["optimizer_state"]["declared_fields"] == ["optimizer_state"]
    assert report["optimizer_state"]["resume_compatibility_verified"] is False
    assert report["differentiability"]["scope"] == "latent_to_decoder_logits_only"
    checkpoint["binding"]["lineage_id"] = "legacy_hub_v1"
    with pytest.raises(ValueError, match="lineage and dimension"):
        subject.inspect_checkpoint(write(tmp_path, checkpoint))


def test_legal_package_inventories_head_and_sparse_vectors_without_claiming_autograd(tmp_path):
    checkpoint = {"schema": "legal-current-384-inference-package/v1",
                  "runtime": "legal_current_v2", "domain": "legal_ir", "dimension": 384,
                  "formula_checkpoint": sequence("modal-latent-formula-checkpoint/v1"),
                  "core_state": {"feature_embedding_weights": {"feature:x": tensor(384)}},
                  "embedding_contract": {"model_id": "thenlper/gte-small", "dimension": 384,
                                         "revision": "a" * 40}}
    report = subject.inspect_checkpoint(write(tmp_path, checkpoint))
    names = {row["name"]: row for row in report["tensor_inventory"]}
    assert names["core_state.feature_embedding_weights.feature:x"]["shape"] == [384]
    assert names["core_state.feature_embedding_weights.feature:x"]["transfer_category"] == "sparse_state_replay_required"
    assert names["formula_checkpoint.model_state.condition.weight"]["transfer_category"] == "dimension_dependent"
    assert report["differentiability"]["whole_source_pipeline_differentiable"] is False
    assert report["decoder_codec"]["target_vocabulary_count"] == 4
    assert report["optimizer_state"]["declared_fields"] == ["formula_checkpoint.optimizer_state"]
    checkpoint["core_state"]["feature_embedding_weights"]["feature:x"].pop()
    with pytest.raises(ValueError, match="sparse vector dimension"):
        subject.inspect_checkpoint(write(tmp_path, checkpoint))


def test_structured_source_reports_numpy_boundary_and_scalar_class_contract(tmp_path):
    parent = sequence()
    checkpoint = {"schema": "structured-source-384-autoencoder/v1", "domain_id": "security_ir",
                  "dimension": 384, "projection_width": 2,
                  "projection_state": {name: values for name, values in parent["model_state"].items()
                                       if name.startswith("projection_")},
                  "target_schema": {"schema": "fixed-typed-json-consensus/v1",
                                    "slots": [{"path": ["kind"], "classes": ["a", "b"]}]},
                  "head_state": {"weights": tensor(384, 2), "bias": tensor(2)},
                  "input_transform": {"mean": tensor(384), "scale": 0.25}}
    report = subject.inspect_checkpoint(write(tmp_path, checkpoint))
    assert report["differentiability"]["differentiable"] is False
    assert "NumPy" in report["actual_input_pipeline"]
    assert report["decoder_codec"]["scalar_class_count"] == 2
    assert report["decoder_codec"]["target_vocabulary_count"] is None
    names = {row["name"]: row for row in report["tensor_inventory"]}
    assert names["head_state.weights"]["transfer_category"] == "dimension_dependent"
    assert names["head_state.bias"]["transfer_category"] == "scalar_identity_mapped"


@pytest.mark.parametrize("schema", ["shared-paired-copy-autoencoder/v1",
                                    "shared-paired-copy-continuation/v1",
                                    "shared-paired-copy-aligned-continuation/v2"])
def test_paired_copy_widths_are_lexical_not_gte_dimensions(tmp_path, schema):
    checkpoint = {"schema": schema,
                  "config": {"hidden_size": 2, "embedding_dim": 3, "lexical_width": 2,
                             "vocabulary": ["<pad>", "x", "y"], "max_tokens": 192,
                             "implementation": {"copy_backend_sha256": "a" * 64}},
                  "weights": {"lexical": tensor(3, 2), "embedding.weight": tensor(3, 3),
                              "output.weight": tensor(3, 4), "output.bias": tensor(3),
                              "copy_gate.weight": tensor(1, 9), "copy_gate.bias": tensor(1),
                              **gru(2, 5, "encoder"), **gru(2, 5, "decoder")}}
    report = subject.inspect_checkpoint(write(tmp_path, checkpoint))
    assert report["family"] == "paired_copy"
    assert report["dimension"] is None
    assert report["metadata"]["config"]["embedding_dim"] == 3
    assert report["decoder_codec"]["target_vocabulary_count"] == 3
    assert "not GTE" in report["actual_input_pipeline"]
    assert report["optimizer_state"]["present"] is False
    names = {row["name"]: row for row in report["tensor_inventory"]}
    assert names["weights.lexical"]["transfer_category"] == "token_identity_mapped"
    checkpoint["weights"]["copy_gate.weight"][0].pop()
    with pytest.raises(ValueError, match="shape differs"):
        subject.inspect_checkpoint(write(tmp_path, checkpoint))


def test_native_feature_selected_and_latest_shapes_do_not_establish_source_teacher(tmp_path):
    parameters = {"encoder_weight": tensor(3, 2), "encoder_bias": tensor(2),
                  "decoder_weight": tensor(2, 3), "decoder_bias": tensor(3)}
    checkpoint = {"schema": "native-formula-checkpoint/v1", "domain_id": "intent_ir",
                  "runtime_version": "native_formula_v1", "config": {"input_width": 3, "latent_width": 2},
                  "latest": {"parameters": parameters, "adam": {}, "progress": {"optimizer_steps": 4}},
                  "selected": {"parameters": deepcopy(parameters)}}
    report = subject.inspect_checkpoint(write(tmp_path, {"schema": "registered-native-formula-candidate/v1",
                                                       "checkpoint": checkpoint, "report": {}}))
    assert report["envelope_schema"] == "registered-native-formula-candidate/v1"
    assert report["checkpoint_schema"] == "native-formula-checkpoint/v1"
    assert len(report["tensor_inventory"]) == 8
    assert report["dimension"] is None
    assert report["optimizer_state"]["declared_fields"] == ["latest.adam"]
    assert report["teacher_qualified"] is False
    assert all(row["transfer_category"] == "native_feature_contract_dependent"
               for row in report["tensor_inventory"])
    checkpoint["selected"]["parameters"]["decoder_weight"].pop()
    with pytest.raises(ValueError, match="shape differs"):
        subject.inspect_checkpoint(write(tmp_path, checkpoint))


def test_manifest_has_only_declared_external_checkpoint_support(tmp_path):
    report = subject.inspect_checkpoint(write(tmp_path, {"schema": "ir-384-hub-package/v1",
                                                       "dimension": 384, "runtime": "legal_current_v2",
                                                       "checkpoint_file": "checkpoint.json"}))
    assert report["family"] == "external_package_manifest"
    assert report["supported_for_transfer"] is False and report["tensor_inventory"] == []


def test_complete_native_family_list_parameters_bind_feature_columns_and_hash(tmp_path):
    parameters = [tensor(3, 2), tensor(2), tensor(2, 3), tensor(3)]
    checkpoint = {"schema": "native-family-complete-autoencoder/v1",
                  "space": {"schema": "native-family-complete-compositional-features/v1",
                            "domain_id": "legal_ir", "columns": [["x", "a"], ["x", "b"], ["y", "c"]],
                            "normalization": "log1p_l2_per_native_projection"},
                  "parameters": parameters,
                  "report": {"feature_count": 3, "latent_width": 2, "strategy": "ridge_path",
                             "selected_parameters_sha256": digest(parameters),
                             "source_text_decoder_trained": False}}
    report = subject.inspect_checkpoint(write(tmp_path, checkpoint))
    assert report["family"] == "native_feature_complete"
    assert report["domain"] == "legal_ir" and report["dimension"] is None
    assert report["metadata"]["feature_contract"]["column_count"] == 3
    assert report["metadata"]["feature_contract"]["latent_width"] == 2
    assert [row["shape"] for row in report["tensor_inventory"]] == [[3, 2], [2], [2, 3], [3]]
    assert report["differentiability"]["whole_source_pipeline_differentiable"] is False
    assert report["optimizer_state"]["present"] is False
    assert report["teacher_qualified"] is False
    bad = deepcopy(checkpoint)
    bad["report"]["feature_count"] = 384
    with pytest.raises(ValueError, match="feature count differs"):
        subject.inspect_checkpoint(write(tmp_path, bad))
    bad = deepcopy(checkpoint)
    bad["parameters"][2].pop()
    with pytest.raises(ValueError, match="shape differs"):
        subject.inspect_checkpoint(write(tmp_path, bad))
    checkpoint["report"]["selected_parameters_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="differs from serialized"):
        subject.inspect_checkpoint(write(tmp_path, checkpoint))


def test_snapshot_hashes_exact_named_files_and_does_not_scan(tmp_path):
    (tmp_path / "b.txt").write_bytes(b"b\n")
    (tmp_path / "a.txt").write_bytes(b"a\n")
    (tmp_path / "unlisted.txt").write_bytes(b"untouched")
    result = subject.snapshot_files(tmp_path, ["b.txt", "a.txt"])
    assert result == [{"path": "a.txt", "bytes": 2, "sha256": hashlib.sha256(b"a\n").hexdigest()},
                      {"path": "b.txt", "bytes": 2, "sha256": hashlib.sha256(b"b\n").hexdigest()}]


@pytest.mark.parametrize("name", ["/etc/passwd", "../escape", "a/../file", "./file",
                                "a//file", "a\\file", ""])
def test_snapshot_rejects_unsafe_names(tmp_path, name):
    with pytest.raises(ValueError):
        subject.snapshot_files(tmp_path, [name])


def test_snapshot_symlinks_cannot_escape_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("outside")
    (root / "escape").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(ValueError, match="escapes root"):
        subject.snapshot_files(root, ["escape"])
    (root / "file.txt").write_text("inside")
    (root / "inside").symlink_to(root / "file.txt")
    assert subject.snapshot_files(root, ["inside"])[0]["sha256"] == hashlib.sha256(b"inside").hexdigest()
    with pytest.raises(ValueError, match="duplicate"):
        subject.snapshot_files(root, ["file.txt", "file.txt"])


def test_snapshot_enforces_file_bound(tmp_path, monkeypatch):
    (tmp_path / "file.txt").write_text("too large")
    monkeypatch.setattr(subject, "MAX_BYTES", 2)
    with pytest.raises(ValueError, match="exceeds max_bytes"):
        subject.snapshot_files(tmp_path, ["file.txt"])
