"""CLI publication checks with tiny synthetic donors; no real model assets."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

REPOSITORY = Path(__file__).resolve().parents[5]
PATH = REPOSITORY / "scripts/ops/autoencoder/prepare_gte_decoder_reuse.py"
SPEC = importlib.util.spec_from_file_location("gte_decoder_reuse_cli_test_subject", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def test_thread_bound():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


class TinyPrimary(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.input_adapter = torch.nn.Linear(768, 2)
        self.inherited = torch.nn.Linear(2, 3)
        self.inherited.requires_grad_(False)


class TinySyntheticDualStudent(torch.nn.Module):
    """Connectivity surrogate, never evidence for an actual historical donor."""
    def __init__(self):
        super().__init__()
        self.primary = TinyPrimary()
        self.auxiliary_connector = torch.nn.Linear(2, 8)
        self.legacy8 = torch.nn.Linear(8, 4)
        self.legacy8.requires_grad_(False)

    def forward(self, vectors, primary_prefix, auxiliary_prefix):
        shared = torch.tanh(self.primary.input_adapter(vectors))
        auxiliary = self.auxiliary_connector(shared)
        return {"primary_logits": self.primary.inherited(shared).unsqueeze(1),
                "auxiliary_logits": self.legacy8(auxiliary).unsqueeze(1),
                "shared_condition": shared, "auxiliary_latent": auxiliary}


def tiny_model():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(59)
        return TinySyntheticDualStudent().eval()


def digest(value):
    return hashlib.sha256(subject._raw(value).rstrip(b"\n")).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    teacher = tmp_path / "synthetic-teacher384.json"
    legacy = tmp_path / "synthetic-legacy8.json"
    teacher.write_bytes(subject._raw({"schema": "synthetic-cli-384-donor"}))
    legacy.write_bytes(subject._raw({"schema": "synthetic-cli-8-donor"}))
    roots = [tmp_path / "source384", tmp_path / "source8"]
    for root in roots:
        root.mkdir()
    source384 = roots[0] / "source.py"
    source8 = roots[1] / "source.py"
    for path in (source384, source8):
        path.write_bytes(b"raise AssertionError('synthetic source must not execute')\n")
    real_helper = subject._helper
    reader = real_helper("gte_worker_contract")
    original_read = reader._read_stable
    source_receipts = [subject._file(reader, path) for path in (source384, source8)]
    budget_calls = []
    def configure(resources):
        budget_calls.append(deepcopy(resources))
        return {"schema": "synthetic-cli-resource-stub", "scope": "unit_test_no_limits_applied"}
    monkeypatch.setattr(reader, "configure_cpu_process", configure)
    teacher_pin = hashlib.sha256(teacher.read_bytes()).hexdigest()
    legacy_pin = hashlib.sha256(legacy.read_bytes()).hexdigest()
    pins = {"teacher384_checkpoint_sha256": teacher_pin, "teacher384_weights_sha256": "1" * 64,
            "teacher384_codec_sha256": "2" * 64, "legacy8_checkpoint_sha256": legacy_pin,
            "legacy8_weights_sha256": "3" * 64, "legacy8_codec_sha256": "4" * 64}
    initial_bundle = {}
    def create(*args, **kwargs):
        assert len(budget_calls) == 1
        model = tiny_model()
        bundle = {"schema": "synthetic-cli-dual-bundle", "donor_pins": pins,
                  "representation_id": "synthetic_cli_identity",
                  "model_state": {name: value.tolist() for name, value in model.state_dict().items()}}
        initial_bundle.update(deepcopy(bundle))
        return model, bundle
    def load(bundle, *, expected_donor_pins):
        assert bundle["donor_pins"] == expected_donor_pins == pins
        restored = tiny_model()
        restored.load_state_dict({name: torch.tensor(value) for name, value in bundle["model_state"].items()})
        return restored
    inspection = {"primary_copied_tensor_count": 13, "legacy8_copied_tensor_count": 13,
        "copied_parameter_count": 49, "new_boundary_parameter_count": 1538,
        "new_auxiliary_connector_parameter_count": 24, "primary_max_target_tokens": 512,
        "auxiliary_max_target_tokens": 64}
    reuse = SimpleNamespace(digest=digest, create_dual_decoder=create, load_dual_decoder=load,
        inspect_dual_decoder=lambda *a, **k: dict(inspection),
        _PRIMARY=SimpleNamespace(_TEACHER=SimpleNamespace(inspect_teacher=lambda *a, **k:
            {"weights_sha256": pins["teacher384_weights_sha256"], "codec_sha256": pins["teacher384_codec_sha256"],
             "sources": [dict(source_receipts[0])]})),
        _LEGACY=SimpleNamespace(inspect_legacy8_decoder_donor=lambda *a, **k:
            {"model_state_sha256": pins["legacy8_weights_sha256"], "codec_sha256": pins["legacy8_codec_sha256"],
             "implementation_files": [{"name": "synthetic_source.py", **source_receipts[1]}],
             "implementation_files_verified": k.get("implementation_root") is not None}))
    monkeypatch.setattr(subject, "_helper", lambda name: reader if name == "gte_worker_contract" else
                        reuse if name == "gte_decoder_reuse" else real_helper(name))
    return SimpleNamespace(teacher=teacher, legacy=legacy, teacher_pin=teacher_pin, legacy_pin=legacy_pin,
        roots=roots, sources=(source384, source8), reader=reader, original_read=original_read, reuse=reuse,
        pins=pins, budget_calls=budget_calls, initial_bundle=initial_bundle, output=tmp_path / "output")


def run(fixture, **overrides):
    kwargs = dict(expected_teacher384_sha256=fixture.teacher_pin, expected_legacy8_sha256=fixture.legacy_pin,
                  output_directory=fixture.output, repository_root=fixture.roots[0],
                  legacy_implementation_root=fixture.roots[1])
    kwargs.update(overrides)
    return subject.prepare_decoder_reuse(fixture.teacher, fixture.legacy, **kwargs)


def test_cli_import_does_not_load_numerical_libraries():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','transformers','numpy'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def test_publishes_complete_authenticated_initialization_and_probe(fixture):
    result = run(fixture)
    assert result["status"] == "initialized_unaligned"
    assert result["synthetic_gradient_probe_passed"] and result["exact_saved_reload_passed"]
    assert result["decoder_parameters_random"] is False and result["boundary_alignment_required"] is True
    assert result["optimizer_steps"] == 0 and result["training_executed"] is False
    assert result["encoder_inference_executed"] is False and result["distillation_executed"] is False
    assert result["legacy8_source_closure_verified"] is True
    manifest_path = fixture.output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["schema"] == subject.MANIFEST_SCHEMA and manifest["completed"] is True
    assert len(manifest["outputs"]) == 6 and len(manifest["inputs"]) == 4
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result["manifest_sha256"]
    for receipt in manifest["outputs"]:
        raw = (fixture.output / receipt["path"]).read_bytes()
        assert len(raw) == receipt["bytes"] and hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    probe = json.loads((fixture.output / "gradient-probe.json").read_bytes())
    assert probe["probe_input_origin"] == "fixed_synthetic_unit_vector_not_encoder_output"
    assert probe["primary_prefix"] == probe["auxiliary_prefix"] == [[1]]
    assert abs(probe["input_l2_norm"] - 1.) < 1e-6
    assert all(value["nonzero"] and value["finite"] for value in probe["gradient_groups"].values())
    assert probe["auxiliary_loss_reaches_shared_primary_boundary"]
    assert all(probe["exact_saved_reload"][name] is True for name in (
        "saved_bytes_authenticated_before_load", "all_state_tensors_equal", "all_output_tensors_equal",
        "tensor_storage_independent", "freeze_mode_equal"))
    assert fixture.initial_bundle["model_state"] == json.loads((fixture.output / "student-initialization.json").read_bytes())["model_state"]
    assert fixture.budget_calls == [{"device": "cpu", "threads": 1, "max_rows": 1,
        "memory_limit_mib": 16384, "cpu_time_limit_seconds": 120}]


def test_missing_optional_legacy_source_archive_is_reported(fixture):
    result = run(fixture, legacy_implementation_root=None)
    assert result["legacy8_source_closure_verified"] is False
    assert result["source_fidelity_qualified"] is False


@pytest.mark.parametrize("overrides", [{"expected_teacher384_sha256": "a" * 64},
    {"expected_legacy8_sha256": "b" * 64}, {"seed": True}, {"seed": -1},
    {"bridge_checkpoint_path": "/missing/bridge"}, {"expected_bridge_sha256": "c" * 64}])
def test_bad_external_pins_or_arguments_fail_before_budgets(fixture, overrides):
    with pytest.raises(ValueError):
        run(fixture, **overrides)
    assert fixture.budget_calls == [] and not fixture.output.exists()


def test_existing_output_is_preserved(fixture):
    fixture.output.mkdir()
    sentinel = fixture.output / "retained.txt"
    sentinel.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh"):
        run(fixture)
    assert sentinel.read_bytes() == b"retained" and fixture.budget_calls == []


def test_output_cannot_write_into_selected_source_archive(fixture):
    with pytest.raises(ValueError, match="implementation namespace"):
        run(fixture, output_directory=fixture.roots[0] / "output")
    assert fixture.budget_calls == []


def test_symlink_output_parent_is_rejected(fixture, tmp_path):
    link = tmp_path / "alias"
    link.symlink_to(fixture.roots[0], target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        run(fixture, output_directory=link / "output")
    assert fixture.budget_calls == []


def test_concurrent_donor_source_drift_prevents_publication(fixture, monkeypatch):
    original = fixture.reuse.create_dual_decoder
    def drift(*args, **kwargs):
        model, bundle = original(*args, **kwargs)
        fixture.sources[0].write_bytes(b"changed fixture source")
        return model, bundle
    monkeypatch.setattr(fixture.reuse, "create_dual_decoder", drift)
    with pytest.raises(ValueError, match="SHA256"):
        run(fixture)
    assert not fixture.output.exists()


def test_corrupt_saved_initialization_is_not_loaded_or_marked_completed(fixture, monkeypatch):
    original = fixture.reader.write_fresh_output_json
    def corrupt(directory, filename, value):
        receipt = original(directory, filename, value)
        if filename == "student-initialization.json":
            with (Path(directory) / filename).open("ab") as stream:
                stream.write(b" ")
        return receipt
    monkeypatch.setattr(fixture.reader, "write_fresh_output_json", corrupt)
    with pytest.raises(ValueError, match="SHA256"):
        run(fixture)
    assert fixture.output.exists() and not (fixture.output / "manifest.json").exists()


def test_late_input_drift_leaves_no_completion_manifest(fixture, monkeypatch):
    original = subject._recheck
    calls = []
    def drift(reader, receipts):
        calls.append(1)
        if len(calls) == 2:
            fixture.teacher.write_bytes(b"{}")
        return original(reader, receipts)
    monkeypatch.setattr(subject, "_recheck", drift)
    with pytest.raises(ValueError, match="SHA256"):
        run(fixture)
    assert (fixture.output / "student-initialization.json").exists()
    assert not (fixture.output / "manifest.json").exists()


def test_primary_and_auxiliary_gradient_connectivity_preserves_state_and_rng():
    model = tiny_model()
    rng = torch.get_rng_state().clone()
    before = {name: value.clone() for name, value in model.state_dict().items()}
    probe, snapshot = subject._probe_model(model, SimpleNamespace(digest=digest))
    assert probe["status"] == "passed" and torch.equal(rng, torch.get_rng_state())
    assert set(probe["gradient_groups"]) == set(subject._INTERFACES)
    assert all(torch.equal(value, snapshot[name]) and torch.equal(value, model.state_dict()[name])
               for name, value in before.items())
    assert all(parameter.grad is None for parameter in model.parameters())


def test_probe_rejects_unfrozen_inherited_head():
    model = tiny_model()
    model.legacy8.weight.requires_grad_(True)
    with pytest.raises(ValueError, match="must be frozen"):
        subject._probe_model(model, SimpleNamespace(digest=digest))


def test_zero_gradient_boundary_is_explicit_failure():
    model = tiny_model()
    with torch.no_grad():
        model.legacy8.weight.zero_()
    with pytest.raises(ValueError, match="failed to reach"):
        subject._probe_model(model, SimpleNamespace(digest=digest))
    assert all(parameter.grad is None for parameter in model.parameters())


def test_reload_rejects_aliasing_weights_even_if_values_match():
    model = tiny_model()
    before = {name: value.clone() for name, value in model.state_dict().items()}
    with pytest.raises(ValueError, match="aliases"):
        subject._verify_reload(model, model, before, SimpleNamespace(digest=digest))


def test_main_error_is_json_and_returns_two(fixture, capsys):
    exit_code = subject.main(["--teacher384", str(fixture.teacher), "--teacher384-sha256", "e" * 64,
        "--legacy8", str(fixture.legacy), "--legacy8-sha256", fixture.legacy_pin, "--output", str(fixture.output)])
    result = capsys.readouterr()
    assert exit_code == 2 and result.out == ""
    assert json.loads(result.err)["status"] == "invalid"
