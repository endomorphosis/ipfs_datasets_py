"""CPU-only protocol tests; no real checkpoint, CUDA, network, or training."""
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_cuda as module
PROFILE_EVALUATE = module._profile_evaluate


@pytest.fixture
def setup(tmp_path, monkeypatch):
    checkpoint = tmp_path / "state.json"
    checkpoint.write_bytes(b"fixture")
    monkeypatch.setattr(module, "LEGACY_BYTES", 7)
    monkeypatch.setattr(module, "LEGACY_SHA256", hashlib.sha256(b"fixture").hexdigest())
    source = {"package_root": "fixture", "python_file_count": 1, "sha256": "a" * 64}
    monkeypatch.setattr(module, "_source_snapshot", lambda: dict(source))
    state = SimpleNamespace(feature_embedding_weights={"fixture": [0.1] * 8},
                            architecture_version="fixture")
    calls = {"evaluate": [], "compile": [], "load": 0}

    class Model:
        backend = "torch_cuda"

        def __init__(self, *, state, compute_device="auto", feature_family_logit_scale=0.0):
            self.state = state
            self.compute_backend = self.backend
            self.compute_device = compute_device
            self.feature_family_logit_scale = feature_family_logit_scale
            self._sample_feature_cache = {}
            self._legal_ir_loss_target_cache = {}
            self._legal_ir_view_target_cache = {}

        def evaluate(self, samples, **kwargs):
            calls["evaluate"].append(kwargs)
            self._sample_feature_cache["sample"] = "temporary"
            result = {"sample_count": len(samples), "legal_ir_target_count": len(samples),
                      "decoded_embeddings": {s.sample_id: [0.2] * 8 for s in samples},
                      "legal_ir_losses": {"test": 0.1}}
            return SimpleNamespace(to_dict=lambda: result)

        def _decoded_for(self, sample, **kwargs):
            assert kwargs == {"use_sample_memory": False, "apply_reconstruction_projection": True}
            return [0.1] * 8

        def _embedding_metrics(self, target, decoded):
            return [0.9] * len(target), [0.1] * len(target)

        def compute_backend_metadata(self):
            return {"autoencoder_compute_backend": self.compute_backend}

    def load(path):
        calls["load"] += 1
        return state

    def sample(**kwargs):
        return SimpleNamespace(sample_id=kwargs["section"], embedding_vector=[0.1] * 8,
                               embedding_model=kwargs["embedding_model"])

    def compile_one(session, text, span_id):
        calls["compile"].append(span_id)
        return {"status": "compiled", "rule": {"actor": "agency"}, "admitted": True}

    cuda = SimpleNamespace(reset_peak_memory_stats=lambda: None, synchronize=lambda: None,
                           max_memory_allocated=lambda: 123, max_memory_reserved=lambda: 256)
    deps = SimpleNamespace(tree={"compiler": "fixture"}, state=SimpleNamespace(load_json=load),
        model=Model, sample=sample, session=lambda: None, compile=compile_one,
        torch=SimpleNamespace(cuda=cuda))
    monkeypatch.setattr(module, "_dependencies", lambda: deps)
    def profile(torch, callback):
        return callback(), {"profiled": True, "cuda_kernel_event_count": 2,
                            "cuda_device_time_us": 4.0}
    monkeypatch.setattr(module, "_profile_evaluate", profile)
    rows = [{"source_span_id": "one", "legal_id": "usc:1:1", "text": "Agency shall file."}]
    return SimpleNamespace(checkpoint=checkpoint, state=state, deps=deps, source=source, calls=calls,
                           rows=rows, Model=Model)


def test_exact_identity_rejected_before_loading(setup):
    setup.checkpoint.write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest mismatch"):
        module.LegacySpanCUDAWorker(setup.checkpoint)
    assert setup.calls["load"] == 0


def test_symlink_rejected(setup, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(setup.checkpoint)
    with pytest.raises(ValueError, match="regular"):
        module.LegacySpanCUDAWorker(link)


@pytest.mark.parametrize("backend", ["python", "python_cuda_unavailable", "torch_cpu"])
def test_cpu_fallback_refused(setup, backend):
    setup.Model.backend = backend
    with pytest.raises(RuntimeError, match="refuses CPU fallback"):
        module.LegacySpanCUDAWorker(setup.checkpoint)


def test_dimensions_and_mode_fail_closed(setup):
    with pytest.raises(ValueError, match="explicit legacy_mock"):
        module.LegacySpanCUDAWorker(setup.checkpoint, mode="semantic")
    setup.state.feature_embedding_weights["fixture"] = [0.1] * 384
    with pytest.raises(ValueError, match="incompatible embedding"):
        module.LegacySpanCUDAWorker(setup.checkpoint)


def test_receipt_records_real_requested_path_and_never_confers_authority(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    result = worker.evaluate_batch(setup.rows)
    assert result["bridges"]["target_count"] == 1
    assert result["bridges"]["evaluation_invoked"] == list(module.BRIDGE_NAMES)
    assert result["bridges"]["evaluate_provers"] is False
    assert result["bridges"]["disk_cache"] is False
    assert result["bridges"]["parallel_workers"] == 1
    assert result["cuda"]["cuda_kernel_event_count"] == 2
    assert result["model_config"]["feature_family_logit_scale"] == 0.0
    assert result["model_config"]["compute_device"] == "cuda"
    assert result["embedding_representation"]["semantic_embeddings"] is False
    row = result["rows"][0]
    for value in (result, row, row["compiler"]):
        assert value["admitted"] is False and value["formalized"] is False
    assert row["lake"]["status"] == "not_run"
    assert row["raw_decoder"]["safety_projection_used"] is False
    assert row["safety_projected_decoder"]["safety_projection_used"] is True
    assert setup.calls["evaluate"] == [{"legal_ir_bridge_names": module.BRIDGE_NAMES,
        "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": 1,
        "use_sample_memory": False, "profile_evaluation": True, "reconstruction_objective": "raw_decoder"}]
    assert not worker.model._sample_feature_cache


def test_supplied_compiler_observation_avoids_recompile_and_checks_source(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    row = setup.rows[0]
    observed = {"source_span_id": "one", "source_sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                "producer_source": setup.source, "compiler": {"status": "abstain", "reason": "fixture"}}
    result = worker.evaluate_batch(setup.rows, compiler_results={"one": observed})
    assert not setup.calls["compile"]
    assert result["rows"][0]["compiler"]["status"] == "abstain"
    observed["source_sha256"] = "bad"
    with pytest.raises(ValueError, match="source identity mismatch"):
        worker.evaluate_batch(setup.rows, compiler_results={"one": observed})


def test_source_changes_before_or_during_batch_reject_receipt(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    setup.source["sha256"] = "b" * 64
    with pytest.raises(RuntimeError, match="between batches"):
        worker.evaluate_batch(setup.rows)
    setup.source["sha256"] = "a" * 64
    original = worker.model.evaluate
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        setup.source["sha256"] = "c" * 64
        return result
    worker.model.evaluate = changed
    with pytest.raises(RuntimeError, match="during batch"):
        worker.evaluate_batch(setup.rows)
    assert not worker.model._sample_feature_cache


def test_no_targets_is_not_a_successful_ir_evaluation(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    worker.model.evaluate = lambda *args, **kwargs: SimpleNamespace(
        to_dict=lambda: {"sample_count": 1, "legal_ir_target_count": 0})
    with pytest.raises(RuntimeError, match="no legal IR targets"):
        worker.evaluate_batch(setup.rows)


def test_invalid_representation_is_not_silently_adapted(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    setup.deps.sample = lambda **kwargs: SimpleNamespace(embedding_vector=[0.1] * 384,
                                                        embedding_model="real-semantic")
    with pytest.raises(ValueError, match="representation mismatch"):
        worker.evaluate_batch(setup.rows)


def test_compiler_error_remains_per_span_evidence(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    def fail(*args):
        raise ValueError("private detail")
    setup.deps.compile = fail
    result = worker.evaluate_batch(setup.rows)
    assert result["rows"][0]["compiler"]["status"] == "error"
    assert result["rows"][0]["compiler"]["error_type"] == "ValueError"
    assert "private detail" not in str(result)


def test_constitution_is_never_roundtrip_ok(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    def forbidden(*args):
        raise AssertionError("Constitution must not enter compiler")
    setup.deps.compile = forbidden
    setup.rows[0]["legal_id"] = "constitution:article:1"
    result = worker.evaluate_batch(setup.rows)
    assert result["rows"][0]["compiler"]["roundtrip_ok"] is False
    assert result["rows"][0]["compiler"]["status"] == "not_supported_constitution"


def test_sample_error_is_per_span_and_not_a_zero_target_speed_success(setup):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    def failed_sample(**kwargs):
        raise ValueError("fixture parser error")
    setup.deps.sample = failed_sample
    result = worker.evaluate_batch(setup.rows)
    assert result["sample_count"] == 0
    assert result["sample_error_count"] == 1
    assert result["rows"][0]["status"] == "sample_preparation_error"
    assert result["bridges"]["evaluation_invoked"] == []
    assert result["cuda"]["status"] == "not_run_no_valid_samples"


def test_batch_bounds_and_cache_policy_enforced(setup, monkeypatch):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint, max_batch_size=1)
    with pytest.raises(ValueError, match="max_batch_size"):
        worker.evaluate_batch(setup.rows * 2)
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "1")
    with pytest.raises(RuntimeError, match="disk metric cache disabled"):
        worker.evaluate_batch(setup.rows)


def test_cuda_profile_requires_observed_kernels():
    class Profile:
        def __init__(self, events):
            self.recorded = events
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def events(self):
            return self.recorded
    events = []
    torch = SimpleNamespace(profiler=SimpleNamespace(
        ProfilerActivity=SimpleNamespace(CPU="CPU", CUDA="CUDA"),
        profile=lambda **kwargs: Profile(events)), cuda=SimpleNamespace(synchronize=lambda: None))
    with pytest.raises(RuntimeError, match="no CUDA kernel events"):
        PROFILE_EVALUATE(torch, lambda: 1)
    events.append(SimpleNamespace(device_type="DeviceType.CUDA", device_time_total=2.5))
    result, report = PROFILE_EVALUATE(torch, lambda: 3)
    assert result == 3 and report["cuda_kernel_event_count"] == 1
    assert report["cuda_device_time_us"] == 2.5


def test_persistent_compiler_rejects_new_source_before_reusing_imports(setup, monkeypatch):
    monkeypatch.setattr(module, "_CPU_PRODUCER_SOURCE", {**setup.source, "sha256": "changed"})
    with pytest.raises(RuntimeError, match="new producer generation"):
        module.compile_source_span(setup.rows[0])


def test_source_snapshot_skips_python_named_directories_but_hashes_nested_files(tmp_path, monkeypatch):
    package = tmp_path / "package"
    nested = package / "test_file.py"
    nested.mkdir(parents=True)
    (nested / "inside.py").write_text("value = 1\n")
    (package / "normal.py").write_text("value = 2\n")
    monkeypatch.setattr(module, "__file__", str(package / "optimizers" / "logic" / "legacy.py"))
    snapshot = module._source_snapshot()
    assert snapshot["python_file_count"] == 2
    (nested / "inside.py").write_text("value = 3\n")
    assert module._source_snapshot()["sha256"] != snapshot["sha256"]


def test_source_snapshot_still_rejects_python_symlinks(tmp_path, monkeypatch):
    package = tmp_path / "package"
    package.mkdir()
    (package / "normal.py").write_text("value = 1\n")
    (package / "alias.py").symlink_to(package / "normal.py")
    monkeypatch.setattr(module, "__file__", str(package / "optimizers" / "logic" / "legacy.py"))
    with pytest.raises(RuntimeError, match="canonical tree"):
        module._source_snapshot()


@pytest.mark.parametrize("workers", [0, 9, True, 1.5])
def test_bridge_worker_budget_rejects_invalid_values(setup, workers):
    with pytest.raises(ValueError, match="between one and eight"):
        module.LegacySpanCUDAWorker(setup.checkpoint, legal_ir_parallel_workers=workers)


def test_threaded_target_request_records_observed_workers_and_no_timeout(setup, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "5")
    worker = module.LegacySpanCUDAWorker(setup.checkpoint, legal_ir_parallel_workers=4)
    original = worker.model.evaluate
    def observed(samples, **kwargs):
        result = original(samples, **kwargs).to_dict()
        result["evaluation_profile"] = {"target_observation": {
            "parallel_workers_used": min(4, len(samples)), "timeout_fallback_count": 0}}
        return SimpleNamespace(to_dict=lambda: result)
    worker.model.evaluate = observed
    result = worker.evaluate_batch(setup.rows)
    assert setup.calls["evaluate"][0]["legal_ir_parallel_workers"] == 4
    assert result["bridges"]["parallel_workers"] == 4
    assert result["bridges"]["parallel_workers_used"] == 1
    assert result["bridges"]["adapter_workers"] == 1
    assert result["bridges"]["native_target_timeout_seconds"] == 0
    assert result["bridges"]["native_timeout_fallback_count"] == 0


@pytest.mark.parametrize("variable,value", [
    ("IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS", "15"),
    ("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "2"),
])
def test_changed_timeout_or_nested_parallelism_refused(setup, monkeypatch, variable, value):
    worker = module.LegacySpanCUDAWorker(setup.checkpoint)
    monkeypatch.setenv(variable, value)
    with pytest.raises(RuntimeError, match="policy changed"):
        worker.evaluate_batch(setup.rows)
