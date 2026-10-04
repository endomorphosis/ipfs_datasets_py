"""Model-worker contract checks without importing optional model libraries."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[5]
spec = importlib.util.spec_from_file_location("gte_model_worker_test",
    ROOT / "scripts/ops/autoencoder/run_gte_model_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def profile():
    return {"lane_id": "source_384d", "dimension": 384, "domain_id": "legal_ir",
            "runtime_id": "legal_ir:source_training_v2", "representation_id": "declared:test384",
            "resources": {"max_rows": 2}}


def inputs():
    return {"schema": worker.INPUT_SCHEMA, "domain_id": "legal_ir",
            "representation_id": "declared:test384",
            "rows": [{"id": "one", "source_text": "The agency must publish notices.",
                      "embedding": [0.] * 384}]}


@pytest.mark.parametrize("extra", ["target", "reference_target", "candidate_ir", "group_id"])
def test_sidecars_and_reference_targets_never_enter_runtime(extra):
    payload = inputs()
    payload["rows"][0][extra] = {"secret": "reference"}
    with pytest.raises(ValueError, match="targets and sidecars"):
        worker._inputs(payload, profile())


def test_wrong_representation_and_duplicate_sources_fail():
    payload = inputs()
    payload["representation_id"] = "other"
    with pytest.raises(ValueError, match="profile differs"):
        worker._inputs(payload, profile())
    payload = inputs()
    payload["rows"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        worker._inputs(payload, profile())


@pytest.mark.parametrize("vector", [[0.]*8, [float("nan")]*384, [True]*384, [10**999]*384])
def test_wrong_width_and_nonfinite_outputs_are_not_clamped(vector):
    with pytest.raises((ValueError, OverflowError)):
        worker._vector(vector, 384)


def test_linguistic_sources_require_no_supplied_embedding():
    config = profile()
    config.update(lane_id="legacy_8d", dimension=8,
                  runtime_id="legal_ir:legacy_linguistic_historical_blank_en")
    payload = inputs()
    del payload["rows"][0]["embedding"]
    assert worker._inputs(payload, config) == payload["rows"]
    payload["rows"][0]["embedding"] = [0.]*8
    with pytest.raises(ValueError):
        worker._inputs(payload, config)


def setup_worker(tmp_path, monkeypatch):
    helper = worker._helper()
    config = profile()
    config.update(schema=helper.CONFIG_SCHEMA, mode="infer",
        resources={"device": "cpu", "threads": 1, "max_rows": 2,
                   "memory_limit_mib": 16384, "cpu_time_limit_seconds": 120})
    for kind, payload in (("checkpoint", {"checkpoint": "test-only"}), ("dataset", inputs())):
        path = tmp_path / (kind + ".json")
        raw = json.dumps(payload).encode()
        path.write_bytes(raw)
        config[kind] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    path = tmp_path / "config.json"
    raw = json.dumps(config).encode()
    path.write_bytes(raw)
    for suffix, value in (("LANE", config["lane_id"]), ("DIMENSION", "384"),
                          ("RUNTIME", config["runtime_id"]), ("REPRESENTATION", config["representation_id"]),
                          ("CHECKPOINT_SHA256", config["checkpoint"]["sha256"])):
        monkeypatch.setenv("GTE_PATH_" + suffix, value)
    for kind in ("state", "output"):
        directory = tmp_path / kind
        directory.mkdir()
        monkeypatch.setenv("GTE_PATH_" + kind.upper() + "_DIRECTORY", str(directory))
    monkeypatch.setattr(helper, "configure_cpu_process", lambda resources: {"test_only": True})
    monkeypatch.setattr(worker, "_helper", lambda: helper)
    monkeypatch.setattr(worker, "_affinity", lambda config: {"test_only": True})
    return path, hashlib.sha256(raw).hexdigest(), config


def test_changed_dataset_after_inference_withholds_output_and_releases_lease(tmp_path, monkeypatch):
    path, digest, config = setup_worker(tmp_path, monkeypatch)
    class Runtime:
        def infer(self, rows):
            Path(config["dataset"]["path"]).write_text("{}")
            return {"dimension": 384, "rows": [{"id": "one", "reconstructed_embedding": [0.]*384}]}
    monkeypatch.setattr(worker, "_backend", lambda *_: (Runtime(), {}, []))
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        worker.run_worker(path, expected_config_sha256=digest)
    assert not (tmp_path / "output/inference-report.json").exists()
    assert not (tmp_path / "state/worker.lock").exists()


def test_bad_runtime_outputs_are_retained_as_failure_without_completion_report(tmp_path, monkeypatch):
    path, digest, _ = setup_worker(tmp_path, monkeypatch)
    class Runtime:
        def infer(self, rows):
            return {"dimension": 384, "rows": [{"id": "one", "reconstructed_embedding": [float("inf")]*384}]}
    monkeypatch.setattr(worker, "_backend", lambda *_: (Runtime(), {}, []))
    with pytest.raises(ValueError, match="finite"):
        worker.run_worker(path, expected_config_sha256=digest)
    assert not (tmp_path / "output/inference-report.json").exists()
    assert not (tmp_path / "state/worker.lock").exists()


def test_legacy_report_discloses_input_target_projection():
    class Sample:
        embedding_vector = [1.]*8
    class Model:
        def encode(self, sample, **kwargs):
            assert kwargs["use_sample_memory"] is False
            return sample
        def decode(self, sample):
            return sample.embedding_vector
    report = worker._legacy_infer(Model(), [{"id": "one", "source_text": "A source."}], [Sample()])
    assert report["rows"][0]["reconstruction_target_access"] is True
    assert report["rows"][0]["reference_ir_target_access"] is False
    assert report["reconstruction_is_fidelity_evidence"] is False


def test_synchronized_start_crossing_deadline_does_not_sleep_negative(monkeypatch):
    samples = iter([100, 200])
    monkeypatch.setattr(worker.time, "monotonic_ns", lambda: next(samples))
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: pytest.fail("deadline already reached"))
    worker._wait_for_start(150)


def test_start_gate_requires_closed_schema_and_records_exact_receipt(tmp_path, monkeypatch):
    gate = tmp_path / "gate.json"
    payload = {"schema": "gte-parallel-inference-start/v1", "start_monotonic_ns": 150}
    raw = json.dumps(payload).encode()
    gate.write_bytes(raw)
    monkeypatch.setattr(worker, "_wait_for_start", lambda value: None if value == 150 else pytest.fail("bad deadline"))
    receipt = worker._start_gate(worker._helper(), gate)
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    payload["unsafe_extra"] = True
    gate.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid coordinated"):
        worker._start_gate(worker._helper(), gate)


def test_missing_start_gate_is_bounded(tmp_path, monkeypatch):
    times = iter([0., 121.])
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="timed out"):
        worker._start_gate(worker._helper(), tmp_path / "missing")
