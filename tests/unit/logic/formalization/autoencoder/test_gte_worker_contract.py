"""Worker preflight/resources are tested with stdlib subprocesses, never models."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/gte_worker_contract.py"
SPEC = importlib.util.spec_from_file_location("gte_worker_contract_under_test", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def write_json(path, payload):
    raw = json.dumps(payload).encode() + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def resources():
    return {"device": "cpu", "threads": 2, "max_rows": 10,
            "memory_limit_mib": 16384, "cpu_time_limit_seconds": 120}


@pytest.fixture
def inputs(tmp_path):
    state, output = tmp_path / "state", tmp_path / "output"
    state.mkdir()
    output.mkdir()
    checkpoint = write_json(tmp_path / "checkpoint.json", {"schema": "fixture-only/v1"})
    dataset = write_json(tmp_path / "dataset.json", {"rows": []})
    config = {"schema": subject.CONFIG_SCHEMA, "lane_id": "source_384d", "dimension": 384,
              "runtime_id": "legal_ir:source_training_v2", "representation_id": "declared-fixture:384d",
              "checkpoint": {"path": "checkpoint.json", "sha256": checkpoint},
              "dataset": {"path": "dataset.json", "sha256": dataset},
              "domain_id": "legal_ir", "resources": resources(), "mode": "infer"}
    environment = {"GTE_PATH_LANE": config["lane_id"], "GTE_PATH_DIMENSION": "384",
                   "GTE_PATH_RUNTIME": config["runtime_id"], "GTE_PATH_REPRESENTATION": config["representation_id"],
                   "GTE_PATH_CHECKPOINT_SHA256": checkpoint,
                   "GTE_PATH_STATE_DIRECTORY": str(state), "GTE_PATH_OUTPUT_DIRECTORY": str(output)}
    path = tmp_path / "worker.json"
    pin = write_json(path, config)
    return path, pin, config, environment


def test_preflight_matches_environment_and_resolves_but_does_not_verify_references(inputs):
    path, pin, _, environment = inputs
    result = subject.load_worker_contract(path, expected_sha256=pin, environment=environment)
    assert result["config_receipt"]["sha256"] == pin
    assert result["config"]["checkpoint"]["path"] == str(path.parent / "checkpoint.json")
    assert result["environment_receipt"]["identities_match"] is True
    assert result["environment_receipt"]["checkpoint_file_verified"] is False
    assert result["environment_receipt"]["representation_authenticated"] is False
    config = result["config"]
    _, checkpoint = subject.read_pinned_json(config["checkpoint"]["path"], expected_sha256=config["checkpoint"]["sha256"])
    assert checkpoint["sha256"] == config["checkpoint"]["sha256"]


@pytest.mark.parametrize("field", ["GTE_PATH_LANE", "GTE_PATH_DIMENSION", "GTE_PATH_RUNTIME", "GTE_PATH_REPRESENTATION", "GTE_PATH_CHECKPOINT_SHA256"])
def test_dispatch_identity_drift_is_rejected(inputs, field):
    path, _, _, environment = inputs
    environment[field] = "different"
    with pytest.raises(ValueError, match="identity mismatch"):
        subject.load_worker_contract(path, environment=environment)


def test_state_output_alias_and_relative_directory_are_rejected(inputs):
    path, _, _, environment = inputs
    environment["GTE_PATH_OUTPUT_DIRECTORY"] = environment["GTE_PATH_STATE_DIRECTORY"]
    with pytest.raises(ValueError, match="distinct"):
        subject.load_worker_contract(path, environment=environment)
    environment["GTE_PATH_OUTPUT_DIRECTORY"] = "relative-output"
    with pytest.raises(ValueError, match="absolute"):
        subject.load_worker_contract(path, environment=environment)


@pytest.mark.parametrize("runtime", sorted(subject.LEGACY_RUNTIMES))
def test_legacy_bindings_are_explicit_legal_only(inputs, runtime):
    path, _, config, environment = inputs
    config.update(lane_id="legacy_8d", dimension=8, runtime_id=runtime)
    environment.update(GTE_PATH_LANE="legacy_8d", GTE_PATH_DIMENSION="8", GTE_PATH_RUNTIME=runtime)
    write_json(path, config)
    assert subject.load_worker_contract(path, environment=environment)["config"]["dimension"] == 8
    config["domain_id"] = "intent_ir"
    write_json(path, config)
    with pytest.raises(ValueError, match="Legal runtime"):
        subject.load_worker_contract(path, environment=environment)


@pytest.mark.parametrize("change", ["dimension", "runtime", "mode", "extra", "gpu", "768_backend"])
def test_closed_contract_rejects_wrong_lineage_or_unsupported_work(inputs, change):
    path, _, config, environment = inputs
    if change == "dimension": config["dimension"] = 786
    elif change == "runtime": config["runtime_id"] = "security_ir:source_training_v2"
    elif change == "mode": config["mode"] = "train"
    elif change == "extra": config["teacher_ready"] = True
    elif change == "gpu": config["resources"]["device"] = "cuda"
    else: config.update(lane_id="multilingual_768d", dimension=768, runtime_id="legal_ir:gte_multilingual_768_v1")
    write_json(path, config)
    with pytest.raises(ValueError):
        subject.load_worker_contract(path, environment=environment)


@pytest.mark.parametrize("raw", [b'{"duplicate":1,"duplicate":2}', b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e999}'])
def test_strict_json_rejects_duplicate_and_nonfinite_values(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        subject.read_pinned_json(path)


def test_pinned_file_checks_byte_bound_and_digest(tmp_path):
    path = tmp_path / "data.json"
    pin = write_json(path, {"value": "original"})
    with pytest.raises(ValueError, match="byte limit"):
        subject.read_pinned_json(path, max_bytes=2)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        subject.read_pinned_json(path, expected_sha256=pin)


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO diagnostic")
def test_regular_file_requirement_rejects_fifo_without_open_block(tmp_path):
    path = tmp_path / "fifo"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular file"):
        subject.read_pinned_json(path)


def test_stable_reader_rejects_file_mutation_during_read(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    write_json(path, {"value": "original"})
    original = subject.os.fstat
    calls = []
    def mutate_after_read(descriptor):
        calls.append(descriptor)
        if len(calls) == 2:
            path.write_bytes(path.read_bytes() + b" ")
        return original(descriptor)
    monkeypatch.setattr(subject.os, "fstat", mutate_after_read)
    with pytest.raises(ValueError, match="changed"):
        subject.read_pinned_json(path)


def test_state_lease_is_exclusive_and_releases_its_own_token(tmp_path):
    with subject.state_lease(tmp_path) as lease:
        token = json.loads((tmp_path / "worker.lock").read_text())
        assert token["pid"] == os.getpid() and token["nonce"] == lease["nonce"]
        with pytest.raises(FileExistsError):
            with subject.state_lease(tmp_path):
                pytest.fail("second owner acquired state")
    assert lease["released"] is True
    assert not (tmp_path / "worker.lock").exists()


def test_state_lease_releases_after_worker_exception(tmp_path):
    with pytest.raises(RuntimeError):
        with subject.state_lease(tmp_path):
            raise RuntimeError("worker failed")
    assert not (tmp_path / "worker.lock").exists()


@pytest.mark.parametrize("replacement", ["token", "inode"])
def test_state_lease_never_unlinks_a_changed_or_replaced_token(tmp_path, replacement):
    with subject.state_lease(tmp_path) as lease:
        path = tmp_path / "worker.lock"
        if replacement == "inode":
            path.unlink()
        write_json(path, {"schema": "gte-worker-state-lease/v1", "pid": 123, "nonce": "other-owner"})
    assert lease["released"] is False
    assert path.exists()
    assert json.loads(path.read_text())["nonce"] == "other-owner"


def test_fresh_outputs_cannot_overwrite_logs_or_existing_reports(tmp_path):
    receipt = subject.write_fresh_output_json(tmp_path, "result.json", {"status": "fixture"})
    assert receipt["sha256"] == hashlib.sha256((tmp_path / "result.json").read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        subject.write_fresh_output_json(tmp_path, "result.json", {"status": "replacement"})
    assert json.loads((tmp_path / "result.json").read_text())["status"] == "fixture"
    with pytest.raises(ValueError):
        subject.write_fresh_output_json(tmp_path, "../outside.json", {})
    with pytest.raises(ValueError):
        subject.write_fresh_output_json(tmp_path, "nonfinite.json", {"value": float("nan")})
    assert not (tmp_path / "nonfinite.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process budgets")
def test_cpu_resource_limits_and_offline_flags_in_isolated_process():
    code = """import importlib.util,json,os
spec=importlib.util.spec_from_file_location('worker_budget',PATH)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
receipt=module.configure_cpu_process(RESOURCES)
assert os.environ['HF_HUB_OFFLINE']=='1'
assert os.environ['TRANSFORMERS_OFFLINE']=='1'
assert os.environ['HF_DATASETS_OFFLINE']=='1'
assert os.environ['CUDA_VISIBLE_DEVICES']==''
assert os.environ['OMP_NUM_THREADS']==os.environ['MKL_NUM_THREADS']==os.environ['OPENBLAS_NUM_THREADS']==os.environ['NUMEXPR_NUM_THREADS']=='2'
print(json.dumps(receipt))
""".replace("PATH", repr(str(PATH))).replace("RESOURCES", repr(resources()))
    process = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stderr
    receipt = json.loads(process.stdout)
    assert receipt["limits"]["address_space"]["effective"]["hard"] <= 16384 * 1024 * 1024
    assert receipt["limits"]["cpu_time"]["effective"]["hard"] <= 120
    assert receipt["network_isolation_enforced"] is False
    assert receipt["dataset_row_limit_enforced"] is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX existing process budgets")
def test_existing_stricter_resource_limits_are_not_relaxed():
    code = """import importlib.util,json,resource
resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,1024*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU,(20,30))
spec=importlib.util.spec_from_file_location('worker_budget',PATH)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
receipt=module.configure_cpu_process(RESOURCES)
print(json.dumps(receipt))
""".replace("PATH", repr(str(PATH))).replace("RESOURCES", repr(resources()))
    process = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stderr
    receipt = json.loads(process.stdout)
    assert receipt["limits"]["address_space"]["effective"] == {"soft": 512 * 1024 * 1024, "hard": 1024 * 1024 * 1024}
    assert receipt["limits"]["cpu_time"]["effective"] == {"soft": 20, "hard": 30}


def test_budgets_reject_model_imports_before_mutating_limits(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", object())
    with pytest.raises(ValueError, match="before model-library imports"):
        subject.configure_cpu_process(resources())
