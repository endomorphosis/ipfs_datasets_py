"""Synthetic serialized teacher binding checks; no numerical model executes."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_bridge_teacher.py"
SPEC = importlib.util.spec_from_file_location("gte_bridge_teacher_under_test", MODULE)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "repository"
    paths = {*subject._NATIVE_MODULE_PATHS.values(), *subject._NUMERICAL_PATHS.values(),
             "ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py",
             "ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py"}
    pins = {}
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = ("raise AssertionError('synthetic source must never execute: " + relative + "')\n").encode()
        path.write_bytes(content)
        pins[relative] = hashlib.sha256(content).hexdigest()
    vocabulary = ["<pad>", "<bos>", "<eos>", '"a"']
    config = dict(strategy="reference_ce", epochs=2, max_seconds=10., learning_rate=.003,
        batch_size=1, seed=1729, patience=0, max_optimizer_steps=2, reconstruction_weight=.1,
        max_target_tokens=512, validation_interval=1, semantic_weight=4., constant_weight=1.,
        structure_weight=.25, input_normalization="none", hidden_size=8, token_embedding_dim=8,
        projection_width=1, embedding_provenance={"model_id": "thenlper/gte-small",
            "revision": "17e1f347d17fe144873b1201da91788898c639cd", "dimension": 384,
            "dtype": "float32", "normalized": True, "truncated": False})
    codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}
    state = {}
    shapes = subject._INVENTORY._sequence_shapes({"config": config, "codec": codec}, 384)
    for name, shape in shapes.items():
        state[name] = ([[.125] * shape[1] for _ in range(shape[0])] if len(shape) == 2 else [.125] * shape[0])
    checkpoint = {"schema": subject.CHECKPOINT_SCHEMA, "domain_id": "legal_ir", "dimension": 384,
        "architecture": subject.ARCHITECTURE, "codec": codec, "config": config,
        "implementation": {
            "runtime_sha256": pins["ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py"],
            "native": {"runtime": pins["ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py"],
                "dependencies": {name: pins[path] for name, path in subject._NATIVE_MODULE_PATHS.items()},
                "scope": "listed_numerical_and_native_validator_modules_only"},
            "numerical": {"files": {name: pins[path] for name, path in subject._NUMERICAL_PATHS.items()},
                "scope": "listed_latent_decoder_and_grammar_sources_only"},
            "legal_codec_sha256": pins[subject._NUMERICAL_PATHS["legal_formula_codec.py"]]},
        "parent_sha256": "a" * 64, "parent_binding": {"dimension": 384}, "lineage": {},
        "model_state": state, "weights_sha256": digest(state),
        "input_transform": {"mode": "none", "mean": [0.] * 384, "scale": 1., "origin": "training_only"},
        "semantic_paths": [],
        "training_manifest": [{"id": "synthetic-train", "source_sha256": "1" * 64,
            "normalized_source_sha256": "2" * 64, "embedding_sha256": "3" * 64, "target_sha256": "4" * 64}],
        "validation_manifest": [{"id": "synthetic-tune", "source_sha256": "5" * 64,
            "normalized_source_sha256": "6" * 64, "embedding_sha256": "7" * 64, "target_sha256": "4" * 64}],
        "training": {"optimizer_steps": 2, "selected_epoch": 1, "selected_optimizer_steps": 1,
            "test_used_for_selection": False, "selected_validation": {"objective": .5,
                "token_cross_entropy": .4, "valid_candidates": 1, "exact_targets": 0, "count": 1,
                "semantic_leaf_correct": 1, "semantic_leaf_count": 2, "semantic_leaf_accuracy": .5}},
        **{name: False for name in subject._FLAGS}}
    path = tmp_path / "checkpoint.json"
    return {"path": path, "root": root, "checkpoint": checkpoint, "pins": pins}


def inspect(fixture, *, expected=None, domain="legal_ir"):
    fixture["path"].write_bytes(raw(fixture["checkpoint"]))
    return subject.inspect_teacher(fixture["path"],
        expected_sha256=expected or hashlib.sha256(fixture["path"].read_bytes()).hexdigest(),
        domain_id=domain, repository_root=fixture["root"])


def test_binds_exact_shapes_codec_transform_and_source_closure(fixture):
    before = deepcopy(fixture["checkpoint"])
    result = inspect(fixture)
    assert result["schema"] == subject.SCHEMA
    assert result["status"] == "bound"
    assert result["checkpoint_sha256"] == hashlib.sha256(fixture["path"].read_bytes()).hexdigest()
    assert result["weights_sha256"] == digest(before["model_state"])
    assert result["codec_sha256"] == digest(before["codec"])
    assert result["input_transform_sha256"] == digest(before["input_transform"])
    assert result["teacher_runtime_id"] == "legal_ir:source_training_v2"
    assert result["source_representation_id"] == subject.SOURCE_REPRESENTATION_ID
    assert result["source_representation_declared_only"] is True
    assert result["codec"]["special_token_ids"] == {"pad": 0, "bos": 1, "eos": 2}
    assert result["tensor_shapes"]["condition.weight"] == [8, 384]
    assert len(result["sources"]) == 14
    assert result["implementation_scope"] == "listed_files_only"
    assert result["decoding_contract"] == {"max_target_tokens": 512,
        "neural_input": "source_embedding_384_only", "source_text_is_neural_input": False,
        "gradient_api": "model.forward(data384,explicit_prefix)", "inference_target_access": False,
        "teacher_transform_order": "normalize_before_residual_projection"}
    assert result["selected_exposed_tuning"]["exact_targets"] == 0
    for key in ("teacher_qualified", "native_model_loaded", "target_source_fidelity_verified", "proof_authority", "training_executed"):
        assert result[key] is False
    assert fixture["checkpoint"] == before
    assert '"model_state"' not in json.dumps(result)


def test_center_rms_transform_is_bound_without_refitting(fixture):
    fixture["checkpoint"]["config"]["input_normalization"] = "center_rms"
    fixture["checkpoint"]["input_transform"].update(mode="center_rms", mean=[.1] * 384, scale=.05)
    result = inspect(fixture)
    assert result["input_transform"] == fixture["checkpoint"]["input_transform"]
    assert result["input_transform_sha256"] == digest(fixture["checkpoint"]["input_transform"])


@pytest.mark.parametrize("domain", ["legal_ir", "intent_ir", "security_ir", "ui_ux_ir"])
def test_supported_domain_is_explicitly_bound(fixture, domain):
    fixture["checkpoint"]["domain_id"] = domain
    assert inspect(fixture, domain=domain)["teacher_runtime_id"] == domain + ":source_training_v2"


@pytest.mark.parametrize("field", sorted(subject._FLAGS))
def test_declared_authority_cannot_qualify_teacher(fixture, field):
    fixture["checkpoint"][field] = True
    with pytest.raises(ValueError, match="cannot declare"):
        inspect(fixture)


@pytest.mark.parametrize("field,value", [("schema", "unknown"), ("architecture", "unknown"),
    ("domain_id", "intent_ir"), ("dimension", 768), ("dimension", True)])
def test_wrong_teacher_contract_fails(fixture, field, value):
    fixture["checkpoint"][field] = value
    with pytest.raises(ValueError):
        inspect(fixture)


def test_checkpoint_hash_is_external_and_required(fixture):
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        inspect(fixture, expected="0" * 64)
    with pytest.raises(ValueError, match="expected checkpoint SHA256"):
        subject.inspect_teacher(fixture["path"], expected_sha256=None, repository_root=fixture["root"])


@pytest.mark.parametrize("object_name", ["checkpoint", "config", "codec", "input_transform", "implementation"])
def test_unknown_closed_fields_fail(fixture, object_name):
    obj = fixture["checkpoint"] if object_name == "checkpoint" else fixture["checkpoint"][object_name]
    obj["unknown"] = True
    with pytest.raises(ValueError, match="closed"):
        inspect(fixture)


@pytest.mark.parametrize("key,value", [("model_id", "fake"), ("revision", "0" * 40),
    ("dimension", 768), ("dtype", "float16"), ("normalized", False), ("truncated", True), ("normalized", 1)])
def test_wrong_gte_small_declaration_fails(fixture, key, value):
    fixture["checkpoint"]["config"]["embedding_provenance"][key] = value
    with pytest.raises(ValueError, match="source representation differs"):
        inspect(fixture)


@pytest.mark.parametrize("key,value", [("mode", "center_rms"), ("origin", "validation"),
    ("mean", [0.] * 383), ("mean", [True] + [0.] * 383), ("mean", [1.] + [0.] * 383),
    ("scale", .009), ("scale", 2.), ("scale", True)])
def test_invalid_transform_geometry_fails(fixture, key, value):
    fixture["checkpoint"]["input_transform"][key] = value
    with pytest.raises(ValueError):
        inspect(fixture)


@pytest.mark.parametrize("vocabulary", [["<pad>", "<eos>", "<bos>", '"a"'],
    ["<pad>", "<bos>", "<eos>", '"a"', '"a"'],
    ["<pad>", "<bos>", "<eos>", '"b"', '"a"'],
    ["<pad>", "<bos>", "<eos>", "not-a-JSON-token"]])
def test_invalid_output_codec_fails(fixture, vocabulary):
    fixture["checkpoint"]["codec"]["target_vocabulary"] = vocabulary
    with pytest.raises(ValueError, match="vocabulary"):
        inspect(fixture)


def test_weights_digest_fails_before_tensor_use(fixture):
    fixture["checkpoint"]["weights_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="weights digest differs"):
        inspect(fixture)


@pytest.mark.parametrize("mutation", ["missing", "extra", "ragged", "boolean", "float32_overflow"])
def test_tensor_geometry_and_float32_admission_fail(fixture, mutation):
    state = fixture["checkpoint"]["model_state"]
    if mutation == "missing":
        del state["condition.bias"]
    elif mutation == "extra":
        state["extra.weight"] = [1.]
    elif mutation == "ragged":
        state["condition.weight"][0].pop()
    elif mutation == "boolean":
        state["condition.bias"][0] = True
    else:
        state["condition.bias"][0] = 1e100
    fixture["checkpoint"]["weights_sha256"] = digest(state)
    with pytest.raises(ValueError):
        inspect(fixture)


@pytest.mark.parametrize("mutation", ["missing", "changed", "symlink", "directory"])
def test_source_closure_requires_ordinary_matching_files(fixture, mutation):
    path = fixture["root"] / next(iter(fixture["pins"]))
    if mutation == "changed":
        path.write_bytes(b"changed")
    else:
        original = path.read_bytes()
        path.unlink()
        if mutation == "symlink":
            target = path.with_suffix(".fixture")
            target.write_bytes(original)
            path.symlink_to(target)
        elif mutation == "directory":
            path.mkdir()
    with pytest.raises(ValueError):
        inspect(fixture)


def test_source_dependency_names_cannot_escape_repository(fixture):
    dependencies = fixture["checkpoint"]["implementation"]["native"]["dependencies"]
    dependencies["../escape"] = "a" * 64
    with pytest.raises(ValueError, match="closed native dependencies"):
        inspect(fixture)


def test_duplicate_source_pins_must_agree(fixture):
    fixture["checkpoint"]["implementation"]["legal_codec_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="conflicting"):
        inspect(fixture)


@pytest.mark.parametrize("key,value", [("count", 0), ("count", True), ("valid_candidates", 2),
    ("exact_targets", 2), ("semantic_leaf_correct", 3), ("semantic_leaf_accuracy", .75),
    ("objective", -1.), ("token_cross_entropy", True)])
def test_archived_tuning_counts_and_metrics_must_be_consistent(fixture, key, value):
    fixture["checkpoint"]["training"]["selected_validation"][key] = value
    with pytest.raises(ValueError):
        inspect(fixture)


def test_low_or_perfect_archived_loss_never_qualifies_teacher(fixture):
    metrics = fixture["checkpoint"]["training"]["selected_validation"]
    metrics.update(objective=0., token_cross_entropy=0., exact_targets=1,
                   semantic_leaf_correct=2, semantic_leaf_accuracy=1.)
    result = inspect(fixture)
    assert result["selected_exposed_tuning"]["exact_targets"] == 1
    assert result["teacher_qualified"] is False
    assert result["target_source_fidelity_verified"] is False


def test_no_test_selection_and_bounded_selected_generation(fixture):
    fixture["checkpoint"]["training"]["test_used_for_selection"] = True
    with pytest.raises(ValueError, match="no test selection"):
        inspect(fixture)
    fixture["checkpoint"]["training"]["test_used_for_selection"] = False
    fixture["checkpoint"]["training"]["selected_optimizer_steps"] = 3
    with pytest.raises(ValueError, match="selected_optimizer_steps"):
        inspect(fixture)


@pytest.mark.parametrize("key", ["id", "source_sha256", "normalized_source_sha256", "embedding_sha256"])
def test_declared_teacher_training_tuning_overlap_fails(fixture, key):
    fixture["checkpoint"]["validation_manifest"][0][key] = fixture["checkpoint"]["training_manifest"][0][key]
    with pytest.raises(ValueError, match="split overlap"):
        inspect(fixture)


def test_archived_tuning_count_must_bind_manifest_size(fixture):
    fixture["checkpoint"]["training"]["selected_validation"]["count"] = 2
    with pytest.raises(ValueError, match="differs from validation manifest"):
        inspect(fixture)


def test_declared_parent_and_semantic_paths_are_bounded(fixture):
    fixture["checkpoint"]["parent_binding"]["dimension"] = 768
    with pytest.raises(ValueError, match="parent dimension"):
        inspect(fixture)
    fixture["checkpoint"]["parent_binding"]["dimension"] = 384
    fixture["checkpoint"]["semantic_paths"] = [["a"], ["a"]]
    with pytest.raises(ValueError, match="unique and sorted"):
        inspect(fixture)


def test_checkpoint_symlinks_are_rejected(fixture):
    inspect(fixture)
    destination = fixture["path"].with_suffix(".actual")
    fixture["path"].rename(destination)
    fixture["path"].symlink_to(destination)
    with pytest.raises(ValueError, match="symlink"):
        subject.inspect_teacher(fixture["path"], expected_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                                repository_root=fixture["root"])


def test_file_loading_does_not_import_package_hooks_or_model_libraries(fixture):
    result = inspect(fixture)
    code = """
import builtins, importlib.util, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'transformers', 'sentence_transformers', 'ipfs_datasets_py'}:
        raise AssertionError('forbidden import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
spec = importlib.util.spec_from_file_location('isolated_bridge_teacher', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
report = module.inspect_teacher(sys.argv[2], expected_sha256=sys.argv[3], repository_root=sys.argv[4])
assert report['native_model_loaded'] is False
assert len(report['sources']) == 14
print(report['status'])
"""
    completed = subprocess.run([sys.executable, "-B", "-c", code, str(MODULE), str(fixture["path"]),
        result["checkpoint_sha256"], str(fixture["root"])], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "bound"
