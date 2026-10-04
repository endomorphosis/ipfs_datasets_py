"""Synthetic donor admission/port tests; no teacher quality or KD is asserted."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_legacy8_decoder_donor.py"
spec = importlib.util.spec_from_file_location("gte_legacy8_decoder_donor_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)


def filled(shape, value):
    return [filled(shape[1:], value) for _ in range(shape[0])] if shape else value


def float32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def checkpoint():
    structural = ["<pad>", "<bos>", "<eos>"]
    for field in subject._FIELDS:
        structural.append(json.dumps(["field", field], separators=(",", ":")))
        if field in subject._FIELDS[4:]:
            structural.append(json.dumps(["end", field], separators=(",", ":")))
    atoms = sorted(json.dumps(["atom", field, value], separators=(",", ":")) for field, value in
                   (("modality", "O"), ("actor", "agency"), ("action", "submit"), ("object", "reports")))
    codec = {"schema": "legal-source-formula-codec/v1", "source_vocabulary": ["<pad>", "<unk>", "latent"],
             "target_vocabulary": structural + atoms, "policy": copy.deepcopy(subject._POLICY)}
    config = {"architecture": subject.ARCHITECTURE, "device": "cpu", "dtype": "float32", "temperature": 0,
              "max_target_tokens": 64, "source_input": "provenance_only_not_neural_input", "torch_version": "synthetic",
              "learning_rate": .01, "batch_size": 2, "seed": 1729, "hidden_size": 8, "token_embedding_dim": 8,
              "projection_width": 2, "formula_weight": 1., "reconstruction_weight": 1.}
    shapes = subject._shapes(config, len(codec["target_vocabulary"]))
    weights = {name: filled(shape, float32(.01 + index / 1000.)) for index, (name, shape) in enumerate(shapes.items())}
    moments = {name: {"step": 1, "exp_avg": filled(shape, 0.), "exp_avg_sq": filled(shape, .001)}
               for name, shape in shapes.items()}
    return {"schema": subject.CHECKPOINT_SCHEMA,
            "binding": {"domain": "legal_ir", "lineage_id": "legacy_hub_v1", "dimension": 8,
                        "runtime_profile": "modal-latent-joint-formula/v1", "core_sha256": "a" * 64},
            "projection_id": "typed_deontic_rule_v1", "config": config, "codec": codec,
            "implementation": {"scope": "listed_latent_decoder_and_grammar_sources_only",
                               "files": {name: "b" * 64 for name in subject._SOURCE_PATHS}},
            "training_manifest_sha256": "c" * 64, "tuning_manifest_sha256": "d" * 64,
            "training_count": 2, "tuning_count": 2, "model_state": weights,
            "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": moments},
            "progress": {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1},
            "parent_checkpoint_sha256": "e" * 64, **{name: False for name in subject._AUTHORITY}}


def write(tmp_path, value):
    path = tmp_path / "formula.json"
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def inspect(path, pin, **kwargs):
    return subject.inspect_legacy8_decoder_donor(path, expected_sha256=pin, **kwargs)


def test_import_is_stdlib_only():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_donor',sys.argv[1])
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(MODULE)], check=True)


def test_complete_tensor_inventory_and_honest_authority(tmp_path):
    value = checkpoint()
    path, pin = write(tmp_path, value)
    receipt = inspect(path, pin)
    assert receipt["checkpoint_sha256"] == pin and receipt["checkpoint_bytes"] == path.stat().st_size
    assert len(receipt["tensor_inventory"]) == 13
    assert {item["name"]: item["shape"] for item in receipt["tensor_inventory"]} == subject._shapes(value["config"], 17)
    assert receipt["model_state_sha256"] == subject._digest(value["model_state"])
    assert receipt["codec_sha256"] == subject._digest(value["codec"])
    assert receipt["optimizer_moments_validated"] and not receipt["optimizer_moments_copied"]
    assert not receipt["source_only"] and receipt["parser_features_in_input"]
    assert not receipt["source_text_is_neural_input"]
    assert not any(receipt[key] for key in ("qualified", "admitted", "proof_authority", "semantic_correctness_verified",
                                          "original_runtime_replay_verified", "source_runtime_compatible", "distillation_completed",
                                          "weights_copied", "legacy_target_aware_reconstruction_is_fidelity_evidence"))
    assert not receipt["implementation_files_verified"] and receipt["implementation_files"] == []


def test_fresh_receipts_and_read_checkpoint_copies(tmp_path):
    path, pin = write(tmp_path, checkpoint())
    first = subject.read_legacy8_decoder_donor(path, expected_sha256=pin)
    first["receipt"]["config"]["hidden_size"] = 64
    first["checkpoint"]["model_state"]["condition.bias"][0] = 3
    second = subject.read_legacy8_decoder_donor(path, expected_sha256=pin)
    assert second["receipt"]["config"]["hidden_size"] == 8
    assert second["checkpoint"]["model_state"]["condition.bias"][0] != 3


@pytest.mark.parametrize("pin", [None, "a" * 63, "Z" * 64, "A" * 64, True])
def test_external_pin_is_required(tmp_path, pin):
    path, _ = write(tmp_path, checkpoint())
    with pytest.raises(ValueError):
        inspect(path, pin)


def test_pin_mismatch_and_symlink_rejected(tmp_path):
    path, pin = write(tmp_path, checkpoint())
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        inspect(path, "f" * 64)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="nonsymlink"):
        inspect(link, pin)


def test_duplicate_nonfinite_and_oversize_json_rejected(tmp_path, monkeypatch):
    path = tmp_path / "invalid.json"
    for raw in (b'{"schema":1,"schema":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]'):
        path.write_bytes(raw)
        with pytest.raises(ValueError):
            inspect(path, hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(subject, "MAX_BYTES", 10)
    # _read's default is its declared constant, so exercise its explicit bound.
    raw = b'{"long_value":true}'
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="byte bound"):
        subject._read(path, hashlib.sha256(raw).hexdigest(), max_bytes=10)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra=True),
    lambda d: d.update(schema="legacy-linguistic-training-checkpoint/v1"),
    lambda d: d["binding"].update(dimension=384),
    lambda d: d["binding"].update(dimension=True),
    lambda d: d["binding"].update(lineage_id="current_legal_v2"),
    lambda d: d["binding"].update(runtime_profile="legacy_v1"),
    lambda d: d["binding"].update(core_sha256="x"),
    lambda d: d.update(projection_id="fol"),
    lambda d: d.update(qualified=True),
    lambda d: d.update(admitted=0),
    lambda d: d["config"].update(device="cuda"),
    lambda d: d["config"].update(temperature=False),
    lambda d: d["config"].update(dtype="float16"),
    lambda d: d["config"].update(source_input="source_tokens"),
    lambda d: d["config"].update(hidden_size=7),
    lambda d: d["config"].update(hidden_size=True),
    lambda d: d["config"].update(learning_rate=0),
    lambda d: d["config"].update(learning_rate=10**500),
    lambda d: d["config"].update(extra=1),
    lambda d: d.update(training_count=True),
    lambda d: d["progress"].update(optimizer_steps=2),
    lambda d: d["progress"].update(row_cursor=2),
    lambda d: d["progress"].update(epochs_completed=0, optimizer_steps=0),
    lambda d: d["implementation"]["files"].pop("modal_latent_formula.py"),
    lambda d: d["implementation"]["files"].update(foo="a" * 64),
    lambda d: d["implementation"]["files"].update(**{"modal_latent_formula.py": "invalid"}),
    lambda d: d["model_state"].pop("projection_down.bias"),
    lambda d: d["model_state"].update(extra=[1]),
    lambda d: d["model_state"]["condition.weight"].pop(),
    lambda d: d["model_state"]["condition.weight"][0].pop(),
    lambda d: d["model_state"]["condition.bias"].__setitem__(0, True),
    lambda d: d["model_state"]["condition.bias"].__setitem__(0, 1e9),
    lambda d: d["optimizer_state"]["parameters"].pop("output.bias"),
    lambda d: d["optimizer_state"]["parameters"]["output.bias"].update(step=2),
    lambda d: d["optimizer_state"]["parameters"]["output.bias"]["exp_avg_sq"].__setitem__(0, -.01),
    lambda d: d["codec"]["policy"].update(truncation="truncate"),
    lambda d: d["codec"]["policy"].update(rule_count=True),
    lambda d: d["codec"].update(source_vocabulary=["<pad>", "<unk>", "real", "source"]),
    lambda d: d["codec"]["target_vocabulary"].__setitem__(1, "wrong_bos"),
    lambda d: d["codec"]["target_vocabulary"].__setitem__(-1, '["atom","modality","X"]'),
    lambda d: d["codec"]["target_vocabulary"].__setitem__(-1, '["atom", "object", "reports"]'),
])
def test_closed_schema_full_tensor_and_provenance_rejections(tmp_path, mutate):
    value = checkpoint()
    mutate(value)
    path, pin = write(tmp_path, value)
    with pytest.raises(ValueError):
        inspect(path, pin)


def test_implementation_closure_is_exact_and_optional(tmp_path):
    value = checkpoint()
    root = tmp_path / "archive"
    for name, relative in subject._SOURCE_PATHS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = ("# Synthetic archive: " + name + "\n").encode()
        path.write_bytes(raw)
        value["implementation"]["files"][name] = hashlib.sha256(raw).hexdigest()
    path, pin = write(tmp_path, value)
    receipt = inspect(path, pin, implementation_root=root)
    assert receipt["implementation_files_verified"] and len(receipt["implementation_files"]) == 5
    assert not receipt["source_runtime_compatible"] and not receipt["original_runtime_replay_verified"]
    source = root / subject._SOURCE_PATHS["modal_latent_formula.py"]
    source.write_text("# changed\n")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        inspect(path, pin, implementation_root=root)


def test_lazy_port_copies_all_tensors_and_preserves_input_gradient(tmp_path):
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        value = checkpoint()
        path, pin = write(tmp_path, value)
        before = torch.get_rng_state().clone()
        first = subject.load_private_legacy8_decoder(path, expected_sha256=pin)
        second = subject.load_private_legacy8_decoder(path, expected_sha256=pin)
        assert torch.equal(torch.get_rng_state(), before)
        model = first["model"]
        assert first["receipt"]["weights_copied"] and first["receipt"]["tensor_copy_verified"]
        assert not first["receipt"]["distillation_completed"]
        assert not model.training and not any(parameter.requires_grad for parameter in model.parameters())
        for name, tensor in model.state_dict().items():
            assert tensor.device.type == "cpu" and tensor.dtype == torch.float32
            assert torch.equal(tensor, torch.tensor(value["model_state"][name], dtype=torch.float32))
            assert tensor.data_ptr() != second["model"].state_dict()[name].data_ptr()
        latents = torch.linspace(-.4, .6, 16, dtype=torch.float32).reshape(2, 8).requires_grad_()
        tokens = torch.tensor([[1, 3], [1, 4]])
        projected, logits = model(latents, tokens)
        assert projected.shape == (2, 8) and logits.shape == (2, 2, 17)
        assert torch.isfinite(logits).all()
        expected_projection = latents + torch.nn.functional.linear(torch.tanh(torch.nn.functional.linear(
            latents, model.projection_down.weight, model.projection_down.bias)), model.projection_up.weight, model.projection_up.bias)
        assert torch.equal(projected, expected_projection)
        expected_logits, _ = model.next_logits(tokens, model.start(model.project(latents)))
        assert torch.equal(logits, expected_logits)
        logits.square().mean().backward()
        assert latents.grad is not None and torch.isfinite(latents.grad).all() and bool((latents.grad != 0).any())
        assert all(parameter.grad is None for parameter in model.parameters())
        assert path.read_bytes() == json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        first["codec"]["target_vocabulary"][0] = "changed"
        assert second["codec"]["target_vocabulary"][0] == "<pad>"
    finally:
        torch.set_num_threads(previous)


def test_port_requires_caller_cpu_thread_reservation(tmp_path):
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        path, pin = write(tmp_path, checkpoint())
        with pytest.raises(ValueError, match="reserve CPU"):
            subject.load_private_legacy8_decoder(path, expected_sha256=pin)
    finally:
        torch.set_num_threads(previous)


def test_snapshot_is_exact_self_contained_and_does_not_copy_optimizer(tmp_path):
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        value = checkpoint()
        path, pin = write(tmp_path, value)
        loaded = subject.load_private_legacy8_decoder(path, expected_sha256=pin)
        snapshot = loaded["snapshot"]
        assert snapshot["schema"] == subject.SNAPSHOT_SCHEMA
        assert "optimizer_state" not in snapshot and "progress" not in snapshot
        assert snapshot["model_state"] == value["model_state"] and snapshot["codec"] == value["codec"]
        assert not snapshot["optimizer_moments_copied"]
        path.unlink()
        restored = subject.load_private_legacy8_decoder_snapshot(snapshot,
            expected_source_checkpoint_sha256=pin, expected_source_model_state_sha256=loaded["receipt"]["model_state_sha256"])
        assert restored["receipt"]["snapshot_sha256"] == loaded["receipt"]["snapshot_sha256"]
        assert not restored["receipt"]["original_donor_file_revalidated"]
        latent = torch.linspace(-.3, .6, 8).reshape(1, 8)
        tokens = torch.tensor([[1, 3, 4]])
        assert torch.equal(loaded["model"](latent, tokens)[1], restored["model"](latent, tokens)[1])
        for name, tensor in loaded["model"].state_dict().items():
            restored_tensor = restored["model"].state_dict()[name]
            assert torch.equal(tensor, restored_tensor) and tensor.data_ptr() != restored_tensor.data_ptr()
        restored["snapshot"]["model_state"]["condition.bias"][0] = 5
        assert snapshot["model_state"]["condition.bias"][0] != 5
    finally:
        torch.set_num_threads(previous)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema="other"),
    lambda d: d.update(optimizer_state={}),
    lambda d: d.update(qualified=True),
    lambda d: d.update(parser_features_in_input=1),
    lambda d: d.update(source_only=True),
    lambda d: d.update(source_checkpoint_sha256="f" * 64),
    lambda d: d.update(source_model_state_sha256="f" * 64),
    lambda d: d.update(source_codec_sha256="f" * 64),
    lambda d: d.update(donor_identity_sha256="f" * 64),
    lambda d: d["binding"].update(dimension=768),
    lambda d: d["model_state"].pop("target_embedding.weight"),
    lambda d: d["model_state"]["condition.bias"].__setitem__(0, 2.),
    lambda d: d["config"].update(hidden_size=16),
    lambda d: d["codec"]["policy"].update(max_target_tokens=8192),
    lambda d: d["source_implementation"]["files"].pop("tree_pin.py"),
])
def test_snapshot_rejects_drift_or_authority_before_torch_load(mutate):
    snapshot = subject.normalize_legacy8_decoder_donor(checkpoint(), source_checkpoint_sha256="a" * 64)
    mutate(snapshot)
    with pytest.raises(ValueError):
        subject.load_private_legacy8_decoder_snapshot(snapshot, expected_source_checkpoint_sha256="a" * 64)


def test_external_model_state_pin_rejects_self_consistent_replacement():
    snapshot = subject.normalize_legacy8_decoder_donor(checkpoint(), source_checkpoint_sha256="a" * 64)
    original = snapshot["source_model_state_sha256"]
    snapshot["model_state"]["condition.bias"][0] = 2.
    snapshot["source_model_state_sha256"] = subject._digest(snapshot["model_state"])
    identity = {"checkpoint_sha256": snapshot["source_checkpoint_sha256"], "binding": snapshot["binding"],
                "config": snapshot["config"], "codec_sha256": snapshot["source_codec_sha256"],
                "model_state_sha256": snapshot["source_model_state_sha256"], "implementation": snapshot["source_implementation"]}
    snapshot["donor_identity_sha256"] = subject._digest(identity)
    with pytest.raises(ValueError, match="external model state"):
        subject.load_private_legacy8_decoder_snapshot(snapshot, expected_source_checkpoint_sha256="a" * 64,
                                                       expected_source_model_state_sha256=original)


def test_snapshot_inventory_remains_stdlib_only(tmp_path):
    snapshot = subject.normalize_legacy8_decoder_donor(checkpoint(), source_checkpoint_sha256="a" * 64)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_donor',sys.argv[1])
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)
with open(sys.argv[2]) as stream:snapshot=json.load(stream)
receipt=subject.inspect_legacy8_decoder_snapshot(snapshot,expected_source_checkpoint_sha256='a'*64)
assert receipt['tensor_count']==13 and receipt['parameter_count']>0
assert not receipt['qualified'] and not receipt['source_only']
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(MODULE), str(path)], check=True)


def test_numerical_port_rejects_rounding_of_declared_float32_state(tmp_path):
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        value = checkpoint()
        value["model_state"]["condition.bias"][0] = .123456789012345
        path, pin = write(tmp_path, value)
        assert inspect(path, pin)["status"] == "inspected"
        with pytest.raises(ValueError, match="exact float32 serialization"):
            subject.load_private_legacy8_decoder(path, expected_sha256=pin)
    finally:
        torch.set_num_threads(previous)
