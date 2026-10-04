"""Leakage, gradient and ordinary-JSON checkpoint checks for projection heads."""
import hashlib
import importlib.util
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_projection.py"
spec = importlib.util.spec_from_file_location("alignment_projection_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def target(actor="agency", action="file", object_="notice", modality="O", **qualifiers):
    return {"rules": [{"modality": modality, "actor": actor, "action": action,
        "object": object_, "conditions": qualifiers.get("conditions", []),
        "exceptions": qualifiers.get("exceptions", []), "temporal": qualifiers.get("temporal", [])}]}


@pytest.fixture
def codec():
    return subject.fit_legal_feature_codec([
        target(conditions=["work_begins"], temporal=["within_10_days"]),
        target("inspector", "review", "records", "P", exceptions=["emergency"]),
    ])


@pytest.fixture
def torch():
    return pytest.importorskip("torch")


def binding():
    return [{"path": "authored/train.json", "sha256": "a" * 64, "split": "train"}]


def checkpoint(codec):
    model = subject.create_projection_heads(384, codec["feature_dimension"], 384, 1729)
    return subject.create_projection_checkpoint(model, codec, train_bindings=binding(),
        generation_id="authored-projection-1729", training_recipe={"optimizer": "SGD", "optimizer_steps": 0})


def reseal(value):
    value["content_sha256"] = subject._digest({name: part for name, part in value.items() if name != "content_sha256"})
    return value


def test_import_does_not_require_torch_or_execute_a_model():
    code = """
import importlib.abc
import importlib.util
import sys
class RejectTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'torch' or name.startswith('torch.'):
            raise AssertionError('torch imported at module import')
sys.meta_path.insert(0, RejectTorch())
spec = importlib.util.spec_from_file_location('lazy_projection', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert 'torch' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code, str(MODULE)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_source_space_matches_existing_baseline_identity():
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_baseline import VECTOR_SPACE_ID
    assert subject.SOURCE_SPACE_ID == VECTOR_SPACE_ID


def test_codec_fits_training_targets_only_and_preserves_unknown_counts(codec):
    before = subject._raw(codec)
    development = target("new_actor", "new_action", "new_object", "F",
        conditions=["new_condition_1", "new_condition_2"], exceptions=["new_exception"], temporal=["new_time"])
    vector = subject.encode_legal_target(development, codec)
    assert subject._raw(codec) == before
    assert "new_actor" not in codec["blocks"][1]["vocabulary"]
    assert vector[codec["blocks"][0]["unknown_index"]] == 1.0
    assert vector[codec["blocks"][4]["unknown_index"]] == 2.0
    assert all(vector[block["unknown_index"]] > 0 for block in codec["blocks"])
    assert codec["development_fit"] is False and codec["qualified"] is False
    assert len(vector) == codec["feature_dimension"]


def test_separate_qualifier_blocks_and_categorical_values_have_distinct_coordinates(codec):
    rule = target(conditions=["work_begins"], exceptions=["work_begins"], temporal=["work_begins"])
    vector = subject.encode_legal_target(rule, codec)
    condition, exception, temporal = codec["blocks"][4:]
    known = condition["offset"] + condition["vocabulary"].index("work_begins")
    assert vector[known] == 1.0 and vector[condition["unknown_index"]] == 0.0
    assert vector[exception["unknown_index"]] == vector[temporal["unknown_index"]] == 1.0
    assert len({known, exception["unknown_index"], temporal["unknown_index"]}) == 3


def test_codec_is_deterministic_with_an_ordered_training_manifest():
    values = [target(), target("inspector")]
    first = subject.fit_legal_feature_codec(values)
    assert first == subject.fit_legal_feature_codec(values)
    second = subject.fit_legal_feature_codec(list(reversed(values)))
    assert first["blocks"] == second["blocks"]
    assert first["training_target_manifest_sha256"] != second["training_target_manifest_sha256"]
    assert first["feature_space_id"] != second["feature_space_id"]


@pytest.mark.parametrize("mutation", [
    lambda value: value["rules"][0].update(conditions=["z", "a"]),
    lambda value: value["rules"][0].update(exceptions=["x", "x"]),
    lambda value: value.update(extra="unowned"),
    lambda value: value["rules"].append(deepcopy(value["rules"][0])),
])
def test_noncanonical_or_out_of_scope_targets_reject(mutation):
    value = target()
    mutation(value)
    with pytest.raises(ValueError):
        subject.fit_legal_feature_codec([value])


def test_codec_tampering_is_not_a_vocabulary_extension(codec):
    value = deepcopy(codec)
    value["blocks"][1]["vocabulary"].append("secret-development-word")
    with pytest.raises(ValueError):
        subject.encode_legal_target(target(), value)


@pytest.mark.parametrize("shared", [384, 512])
def test_heads_are_cpu_normalized_deterministic_and_preserve_rng(codec, torch, shared):
    before = torch.random.get_rng_state().clone()
    model = subject.create_projection_heads(384, codec["feature_dimension"], shared, 1729)
    assert torch.equal(before, torch.random.get_rng_state())
    other = subject.create_projection_heads(384, codec["feature_dimension"], shared, 1729)
    assert all(torch.equal(model.state_dict()[name], other.state_dict()[name]) for name in model.state_dict())
    source = torch.arange(384, dtype=torch.float32).reshape(1, -1) / 384
    formal = torch.tensor([subject.encode_legal_target(target(), codec)], dtype=torch.float32)
    for output in (model.source(source), model.formal(formal)):
        assert output.shape == (1, shared) and output.dtype == torch.float32 and output.device.type == "cpu"
        assert torch.allclose(torch.linalg.vector_norm(output, dim=1), torch.ones(1), atol=1e-6)


def test_gradients_reach_both_trainable_heads_without_changing_input_vectors(codec, torch):
    model = subject.create_projection_heads(384, codec["feature_dimension"], 384, 27)
    sources = torch.stack((torch.arange(384, dtype=torch.float32) / 384, torch.arange(384, dtype=torch.float32).flip(0) / 384))
    original = sources.clone()
    features = torch.tensor([subject.encode_legal_target(target(), codec),
                             subject.encode_legal_target(target("inspector", "review", "records", "P"), codec)])
    loss = subject.multi_positive_contrastive_loss(model.source(sources), model.formal(features), ["a", "b"])
    loss.backward()
    assert torch.equal(original, sources)
    for parameter in model.parameters():
        assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
        assert torch.count_nonzero(parameter.grad) > 0


def test_duplicate_targets_are_multi_positives_in_both_directions(torch):
    sources = torch.tensor([[1., 0.], [0., 1.], [-1., 0.]], dtype=torch.float64, requires_grad=True)
    formals = torch.tensor([[1., 0.], [0.5, 0.5], [-1., 0.]], dtype=torch.float64, requires_grad=True)
    ids = ["same", "same", "other"]
    temperature = 0.3
    logits = sources @ formals.T / temperature
    mask = torch.tensor([[a == b for b in ids] for a in ids])
    expected = ((torch.logsumexp(logits, 1) - torch.logsumexp(logits.masked_fill(~mask, -torch.inf), 1)).mean()
                + (torch.logsumexp(logits, 0) - torch.logsumexp(logits.masked_fill(~mask, -torch.inf), 0)).mean()) / 2
    actual = subject.multi_positive_contrastive_loss(sources, formals, ids, temperature)
    assert torch.equal(expected, actual)
    diagonal_only = subject.multi_positive_contrastive_loss(sources, formals, ["a", "b", "c"], temperature)
    assert actual < diagonal_only
    actual.backward()
    assert torch.count_nonzero(sources.grad) and torch.count_nonzero(formals.grad)


def test_negative_weighting_ignores_positive_entries_and_never_downweights_negatives(torch):
    sources = torch.tensor([[1., 0.], [0., 1.], [-1., 0.]])
    formals = sources.clone()
    ids = ["same", "same", "other"]
    mask = torch.tensor([[a == b for b in ids] for a in ids])
    weights = torch.full((3, 3), 2.)
    weights[mask] = torch.nan
    weighted = subject.multi_positive_contrastive_loss(sources, formals, ids, 0.2, weights)
    base = subject.multi_positive_contrastive_loss(sources, formals, ids, 0.2)
    assert weighted >= base and torch.isfinite(weighted)
    unit = torch.ones((3, 3))
    unit[mask] = 0.
    assert torch.equal(base, subject.multi_positive_contrastive_loss(sources, formals, ids, 0.2, unit))
    weights[0, 2] = 0.5
    with pytest.raises(ValueError, match="at least one"):
        subject.multi_positive_contrastive_loss(sources, formals, ids, 0.2, weights)


def test_all_same_target_batch_has_zero_loss_without_false_negatives(torch):
    source = torch.eye(3, dtype=torch.float64, requires_grad=True)
    formal = torch.eye(3, dtype=torch.float64, requires_grad=True)
    loss = subject.multi_positive_contrastive_loss(source, formal, ["same"] * 3)
    assert loss.item() == 0.0
    loss.backward()
    assert torch.count_nonzero(source.grad) == torch.count_nonzero(formal.grad) == 0


def test_projection_rejects_boolean_or_nonfinite_inputs_and_zero_vectors(codec, torch):
    model = subject.create_projection_heads(384, codec["feature_dimension"], 384, 1)
    with pytest.raises(ValueError, match="float32"):
        model.source(torch.ones((1, 384), dtype=torch.bool))
    with pytest.raises(ValueError, match="finite"):
        model.source(torch.full((1, 384), torch.nan))
    with torch.no_grad():
        model.source_projection.weight.zero_()
        model.source_projection.bias.zero_()
    with pytest.raises(ValueError, match="zero"):
        model.source(torch.ones((1, 384)))


def test_checkpoint_exact_json_reload_and_no_authority(codec, torch, tmp_path):
    value = checkpoint(codec)
    artifact = subject.save_projection_checkpoint(value, tmp_path / "projection.json")
    loaded = subject.load_projection_checkpoint(artifact["path"], expected_sha256=artifact["sha256"])
    assert loaded["checkpoint"] == value and loaded["codec"] == codec
    assert loaded["sha256"] == artifact["sha256"]
    assert value["source_space_id"] != value["formal_space_id"]
    assert value["development_fit"] is False and value["qualified"] is False
    assert value["optimizer_resume_supported"] is False
    source = torch.arange(384, dtype=torch.float32).reshape(1, -1)
    original = subject.create_projection_heads(384, codec["feature_dimension"], 384, 1729)
    assert torch.equal(original.source(source), loaded["model"].source(source))
    with pytest.raises(FileExistsError):
        subject.save_projection_checkpoint(value, artifact["path"])
    with pytest.raises(ValueError, match="file SHA256"):
        subject.load_projection_checkpoint(artifact["path"], expected_sha256="0" * 64)


@pytest.mark.parametrize("mutation,match", [
    (lambda value: value.update(source_space_id="foreign:384"), "source vector-space"),
    (lambda value: value.update(shared_dimension=768), "shared dimension"),
    (lambda value: value.update(state_dtype="float64"), "scope differs"),
    (lambda value: value.update(output_kind="vocabulary_logits"), "scope differs"),
    (lambda value: value.update(qualified=True), "scope differs"),
    (lambda value: value.update(development_fit=True), "scope differs"),
    (lambda value: value["train_bindings"][0].update(split="validation"), "training split"),
    (lambda value: value["model_state"]["source_projection.weight"][0].pop(), "shape differs"),
    (lambda value: value["model_state"]["source_projection.bias"].__setitem__(0, True), "bool is forbidden"),
    (lambda value: value["model_state"]["source_projection.bias"].__setitem__(0, 1e100), "float32-range"),
    (lambda value: value.update(formal_space_id="foreign:features"), "formal feature-space"),
    (lambda value: value.update(implementation_profile="foreign/v1"), "implementation identity"),
])
def test_resealed_checkpoint_corruption_still_fails_structural_checks(codec, torch, tmp_path, mutation, match):
    value = checkpoint(codec)
    mutation(value)
    reseal(value)
    raw = subject._raw(value)
    path = tmp_path / "malformed.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match=match):
        subject.load_projection_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_digest_tampering_and_foreign_expected_source_space_reject(codec, torch, tmp_path):
    value = checkpoint(codec)
    value["generation_id"] = "tampered"
    with pytest.raises(ValueError, match="content digest"):
        subject.save_projection_checkpoint(value, tmp_path / "bad.json")
    value = checkpoint(codec)
    artifact = subject.save_projection_checkpoint(value, tmp_path / "good.json")
    with pytest.raises(ValueError, match="source vector-space"):
        subject.load_projection_checkpoint(artifact["path"], expected_sha256=artifact["sha256"],
                                           expected_source_space_id="foreign:384")


def test_checkpoint_symlink_parent_and_size_limit_reject(codec, torch, tmp_path, monkeypatch):
    value = checkpoint(codec)
    actual = tmp_path / "actual"
    actual.mkdir()
    (tmp_path / "linked").symlink_to(actual, target_is_directory=True)
    with pytest.raises(OSError):
        subject.save_projection_checkpoint(value, tmp_path / "linked/checkpoint.json")
    artifact = subject.save_projection_checkpoint(value, actual / "checkpoint.json")
    link = tmp_path / "linked-checkpoint.json"
    link.symlink_to(artifact["path"])
    with pytest.raises(OSError):
        subject.load_projection_checkpoint(link, expected_sha256=artifact["sha256"])
    monkeypatch.setattr(subject, "MAX_CHECKPOINT_BYTES", 16)
    with pytest.raises(ValueError, match="bounded regular"):
        subject.load_projection_checkpoint(artifact["path"], expected_sha256=artifact["sha256"])


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"state":NaN}', b'[]', b'\xff'])
def test_strict_checkpoint_json_rejects_malformed_content(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        subject.load_projection_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest())
