"""Preparation binding and cache bypass without invoking live bridge services."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as prep
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord, TrainingConfig, _JOB_LOCK
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import load_target_snapshot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


@pytest.fixture
def context(monkeypatch, tmp_path):
    package = tmp_path / "package"
    module = package / "optimizers" / "logic_theorem_optimizer" / "preparation.py"
    module.parent.mkdir(parents=True)
    module.write_text("original")
    monkeypatch.setattr(prep, "__file__", str(module))
    monkeypatch.setattr(prep, "_PROCESS_CONTEXT", None)
    monkeypatch.setattr(prep.importlib.metadata, "distributions", lambda: [SimpleNamespace(metadata={"Name": "fixture"}, version="1")])
    return package, module


def _records():
    return [SampleRecord("5", "fixture", "The agency shall not disclose records.")]


def _fake_generation(calls):
    def generate(callback, **kwargs):
        calls.append(kwargs)
        assert kwargs["cache"] is False
        assert kwargs["evaluate_provers"] is False
        doc = LegalIRDocument(kwargs["document_id"], kwargs["text"], kwargs["text"],
                              source=kwargs["source"], citation=kwargs["citation"], metadata={"exact_timestamp": "2026-09-25Z"})
        target = LegalIRTrainingTarget(kwargs["bridge_names"], doc, {"fixture_loss": 0.5}, view_distribution={"deontic.ir": 1.0})
        return SimpleNamespace(training_target=lambda: target, bridge_names=kwargs["bridge_names"],
                               reports={}, failures={}, accepted=target.accepted)
    return generate


def test_preparation_bypasses_metric_and_multiview_caches_and_seals_union(context, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", _fake_generation(calls))
    def forbidden(*args, **kwargs):
        raise AssertionError("metric cache path used")
    monkeypatch.setattr(modal, "_legal_ir_target_items", forbidden)
    monkeypatch.setattr(modal, "_read_legal_ir_target_disk_cache", forbidden)
    train = _records()
    validation = [*train, SampleRecord("5", "other", "The officer shall retain the file for at least 20 days.")]
    receipt = prep.prepare_training_targets(train, tmp_path / "targets.json", validation_records=validation)
    assert len(calls) == receipt["sample_count"] == receipt["legal_ir_target_count"] == 2
    assert receipt["metric_process_cache_used"] is False
    assert receipt["multiview_process_cache_used"] is False
    assert receipt["admitted"] is False
    snapshot = load_target_snapshot(receipt["artifact"]["path"], expected_sha256=receipt["artifact"]["sha256"])
    assert snapshot.snapshot_id == receipt["target_snapshot_id"]
    assert all(status == "ready" for status in snapshot.statuses.values())
    with pytest.raises(FileExistsError):
        prep.prepare_training_targets(train, tmp_path / "targets.json")


def test_timeout_is_preserved_as_explicit_target_not_positive_status(context, monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise modal._LegalIRTargetTimeout("fixture")
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", timeout)
    receipt = prep.prepare_training_targets(_records(), tmp_path / "timeout.json")
    snapshot = load_target_snapshot(receipt["artifact"]["path"], expected_sha256=receipt["artifact"]["sha256"])
    assert set(snapshot.statuses.values()) == {"timeout"}
    assert receipt["admitted"] is False
    samples = [build_us_code_sample(title="5", section="fixture", text="The agency shall not disclose records.")]
    target = snapshot.targets_for(samples, config=snapshot.config)[samples[0].sample_id]
    assert target.accepted is False
    assert "legal_ir_target_timeout_loss" in target.losses
    telemetry = receipt["bridge_report_telemetry"][samples[0].sample_id]
    assert telemetry["report_received"] is False
    assert telemetry["report_accepted"] is None
    assert telemetry["failures"] == {}
    assert telemetry["outer_timeout"] == {"exception_type": "_LegalIRTargetTimeout", "message": "fixture"}
    for kind in ("attempted", "implemented", "failed", "accepted"):
        assert telemetry[f"{kind}_bridge_count"] is None
        assert telemetry[f"{kind}_bridge_names"] is None


@pytest.mark.parametrize("artifact_format", ["json", "bundle"])
def test_partial_bridge_report_telemetry_preserves_target_bytes(context, monkeypatch, tmp_path, artifact_format):
    from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
    from ipfs_datasets_py.logic.bridge.types import BridgeEvaluationReport, GraphProjectionResult, ProofGateResult, RoundTripMetrics
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_artifact, write_target_bundle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import build_target_snapshot

    sample = build_us_code_sample(**_records()[0].__dict__)
    names = ("modal_frame_logic", "deontic_norms", "cec_dcec")
    config = TrainingConfig(legal_ir_bridge_names=names)
    document = LegalIRDocument(sample.sample_id, sample.text, sample.text, source=sample.source,
        citation=sample.citation, frame_logic_triples=({"subject": "agency", "predicate": "modality", "object": "obligation"},),
        metadata={"retained_nested_metadata": {"values": ["exact\nUnicode: é", 2]}})
    accepted = BridgeEvaluationReport(names[0], "fixture", document, RoundTripMetrics(cosine_similarity=0.75),
        proof_gate=ProofGateResult.disabled(), status="ok",
        graph_projection=GraphProjectionResult(neo4j_compatible=True, node_count=2, relationship_count=1))
    failure = "RuntimeError: exact failure\nUnicode: é; no inferred exception fields"
    report = MultiViewLegalIRReport(names, document,
        reports={names[0]: accepted, names[1]: replace(accepted, adapter_name=names[1], status="partial")},
        failures={names[2]: failure})
    target = report.training_target()
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", lambda *args, **kwargs: report)
    receipt = prep.prepare_training_targets(_records(), tmp_path / "actual", training_config=config,
                                            artifact_format=artifact_format)
    assert receipt["statuses"] == {sample.sample_id: "ready"}
    assert "does not imply bridge acceptance or admission" in receipt["status_definitions"]["ready"]
    assert receipt["bridge_report_telemetry"] == {sample.sample_id: {
        "report_received": True, "report_accepted": False,
        "attempted_bridge_count": 3, "implemented_bridge_count": 2,
        "failed_bridge_count": 1, "accepted_bridge_count": 1,
        "attempted_bridge_names": list(names), "implemented_bridge_names": sorted(names[:2]),
        "failed_bridge_names": [names[2]], "accepted_bridge_names": [names[0]],
        "failures": {names[2]: failure}, "outer_timeout": None,
    }}
    snapshot = load_target_artifact(receipt["artifact"]["path"], expected_sha256=receipt["artifact"]["sha256"])
    try:
        assert snapshot.targets_for([sample], config=snapshot.config)[sample.sample_id] == target
        baseline_path = tmp_path / "without-telemetry"
        if artifact_format == "bundle":
            saved = write_target_bundle(baseline_path, [(sample, target, "ready")], config=snapshot.config)
        else:
            saved = build_target_snapshot([sample], {sample.sample_id: target}, config=snapshot.config,
                                          statuses={sample.sample_id: "ready"}).save(baseline_path)
        assert saved["sha256"] == receipt["artifact"]["sha256"]
        assert baseline_path.read_bytes() == Path(receipt["artifact"]["path"]).read_bytes()
    finally:
        if hasattr(snapshot, "close"):
            snapshot.close()


def test_real_timeout_handler_reaches_owner_and_records_timeout(context, monkeypatch, tmp_path):
    import signal
    from ipfs_datasets_py.logic.bridge import multiview

    if not modal._legal_ir_target_timeout_enabled(15.0):
        pytest.skip("requires the existing main-thread SIGALRM timeout implementation")
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS", "15")
    original_handler = signal.getsignal(signal.SIGALRM)
    calls = []

    def interrupted_adapter(*args, **kwargs):
        # Invoke the real installed handler deterministically. Owned cancellation
        # must cross the adapter's ordinary Exception handler and reach the
        # preparation owner. No sleep or timer race is used.
        handler = signal.getsignal(signal.SIGALRM)
        assert callable(handler) and handler is not original_handler
        calls.append(kwargs)
        handler(signal.SIGALRM, None)

    monkeypatch.setattr(multiview, "load_logic_bridge_adapter", lambda name: object())
    monkeypatch.setattr(multiview, "_evaluate_adapter", interrupted_adapter)
    receipt = prep.prepare_training_targets(_records(), tmp_path / "nested-timeout.json",
        training_config=TrainingConfig(legal_ir_bridge_names=("modal_frame_logic",)))
    assert len(calls) == 1 and calls[0]["evaluate_provers"] is False
    assert signal.getsignal(signal.SIGALRM) is original_handler
    sample_id, status = next(iter(receipt["statuses"].items()))
    assert status == "timeout" and receipt["admitted"] is False
    telemetry = receipt["bridge_report_telemetry"][sample_id]
    assert telemetry["report_received"] is False and telemetry["report_accepted"] is None
    assert telemetry["outer_timeout"] == {
        "exception_type": "_LegalIRTargetTimeout",
        "message": "LegalIR target construction exceeded 15.000s",
    }
    assert telemetry["failures"] == {}
    for kind in ("attempted", "implemented", "failed", "accepted"):
        assert telemetry[f"{kind}_bridge_count"] is None
        assert telemetry[f"{kind}_bridge_names"] is None
    snapshot = load_target_snapshot(receipt["artifact"]["path"], expected_sha256=receipt["artifact"]["sha256"])
    sample = build_us_code_sample(**_records()[0].__dict__)
    target = snapshot.targets_for([sample], config=snapshot.config)[sample_id]
    assert target.accepted is False
    assert target.losses["legal_ir_target_timeout_loss"] == 1.0


@pytest.mark.parametrize("change", ["contents", "dependency", "environment"])
def test_resident_context_rejects_changed_contents_or_runtime(context, monkeypatch, change):
    package, module = context
    first = prep.target_snapshot_config(TrainingConfig())
    if change == "contents":
        stat = module.stat()
        module.write_text("modified")  # same byte length; mtime is restored below
        import os
        os.utime(module, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change == "dependency":
        monkeypatch.setattr(prep.importlib.metadata, "distributions", lambda: [SimpleNamespace(metadata={"Name": "fixture"}, version="2")])
    else:
        monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "2")
    with pytest.raises(ValueError, match="resident process"):
        prep.target_snapshot_config(TrainingConfig())
    assert first.code_sha256


def test_source_symlink_is_rejected(context, tmp_path):
    package, module = context
    outside = tmp_path / "outside.py"
    outside.write_text("external")
    (package / "alias.py").symlink_to(outside)
    with pytest.raises(ValueError, match="alias another tree"):
        prep.target_snapshot_config(TrainingConfig())


def test_source_manifest_handles_fixture_directory_named_dot_py(context):
    package, module = context
    directory = package / "fixture.py"
    directory.mkdir()
    (directory / "actual.py").write_text("retained source")
    config = prep.target_snapshot_config(TrainingConfig())
    assert "fixture.py" not in config.code_sha256
    assert "fixture.py/actual.py" in config.code_sha256


def test_repeated_distribution_discovery_does_not_change_runtime_identity(context, monkeypatch):
    first = prep.target_snapshot_config(TrainingConfig())
    duplicate = SimpleNamespace(metadata={"Name": "fixture"}, version="1")
    monkeypatch.setattr(prep.importlib.metadata, "distributions", lambda: [duplicate, duplicate])
    assert prep.target_snapshot_config(TrainingConfig()) == first


def test_union_rejects_same_id_with_different_precise_embedding():
    sample = build_us_code_sample(title="5", section="fixture", text="The agency shall not disclose records.")
    changed = replace(sample, embedding_vector=[sample.embedding_vector[0] + 1e-12, *sample.embedding_vector[1:]])
    assert prep.unique_training_samples([sample], [sample]) == [sample]
    with pytest.raises(ValueError, match="aliases"):
        prep.unique_training_samples([sample], [changed])


def test_preparation_reports_parallel_timeout_limit(context, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", _fake_generation(calls))
    receipt = prep.prepare_training_targets(_records(), tmp_path / "parallel.json", training_config=TrainingConfig(legal_ir_parallel_workers=2))
    assert receipt["target_timeout_enforcement"] == "none_in_parallel_target_threads_or_without_signal_support"


def test_preparation_releases_job_lock_on_failure(context, monkeypatch, tmp_path):
    def failed(*args, **kwargs):
        raise RuntimeError("fixture failure")
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", failed)
    with pytest.raises(RuntimeError, match="fixture failure"):
        prep.prepare_training_targets(_records(), tmp_path / "failed.json")
    assert not (tmp_path / "failed.json").exists()
    assert _JOB_LOCK.acquire(blocking=False)
    _JOB_LOCK.release()


@pytest.mark.parametrize("artifact_format", ["json", "bundle"])
def test_preparation_format_retains_full_targets_and_reports_pipeline(context, monkeypatch, tmp_path, artifact_format):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_artifact
    calls = []
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", _fake_generation(calls))
    receipt = prep.prepare_training_targets(_records(), tmp_path / "targets", artifact_format=artifact_format)
    snapshot = load_target_artifact(receipt["artifact"]["path"], expected_sha256=receipt["artifact"]["sha256"])
    try:
        sample = build_us_code_sample(**_records()[0].__dict__)
        target = snapshot.targets_for([sample], config=snapshot.config)[sample.sample_id]
        assert target.document.metadata["exact_timestamp"] == "2026-09-25Z"
        assert receipt["artifact_format"] == artifact_format
        assert receipt["artifact_builder_retains_all_targets"] is (artifact_format == "json")
        assert receipt["maximum_pending_generation_results"] == 1
        assert receipt["target_generation_and_artifact_seconds"] >= receipt["target_generation_seconds"] > 0
        assert receipt["target_generate_call_seconds"] == receipt["target_generation_seconds"]
    finally:
        if hasattr(snapshot, "close"):
            snapshot.close()


def test_bundle_preparation_encodes_before_generating_next_target(context, monkeypatch, tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle
    calls = []
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", _fake_generation(calls))
    original = bundle.write_target_bundle

    def writer(path, records, **kwargs):
        def checked_records():
            for index, record in enumerate(records, start=1):
                # An eager list of all bridge targets would fail at the first
                # record. The real codec consumes this iterator incrementally.
                assert len(calls) == index
                yield record
        return original(path, checked_records(), **kwargs)

    monkeypatch.setattr(bundle, "write_target_bundle", writer)
    records = [SampleRecord("5", str(index), "The agency shall not disclose records.") for index in range(4)]
    receipt = prep.prepare_training_targets(records, tmp_path / "targets.bundle", artifact_format="bundle")
    assert receipt["legal_ir_target_count"] == len(calls) == 4


def test_parallel_generator_bounds_completed_results_until_writer_advances():
    import threading
    completed = []
    ready = threading.Event()
    def generate(sample):
        completed.append(sample)
        if len(completed) == 2:
            ready.set()
        return sample

    results = prep._bounded_target_results(generate, list(range(20)), workers=2)
    assert next(results) == (0, 0)
    assert ready.wait(timeout=2)
    assert sorted(completed) == [0, 1]
    results.close()


def test_bundle_source_change_refuses_publication(context, monkeypatch, tmp_path):
    calls = []
    underlying = _fake_generation(calls)
    def changed(callback, **kwargs):
        result = underlying(callback, **kwargs)
        context[1].write_text("modified")
        return result
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", changed)
    destination = tmp_path / "changed.bundle"
    with pytest.raises(ValueError, match="resident process"):
        prep.prepare_training_targets(_records(), destination, artifact_format="bundle")
    assert not destination.exists()
    assert _JOB_LOCK.acquire(blocking=False)
    _JOB_LOCK.release()


@pytest.mark.parametrize("artifact_format", ["unknown", None, []])
def test_invalid_target_format_does_not_generate_or_acquire_lock(context, monkeypatch, tmp_path, artifact_format):
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", lambda *a, **k: pytest.fail("generated"))
    with pytest.raises(ValueError, match="artifact_format"):
        prep.prepare_training_targets(_records(), tmp_path / "unknown", artifact_format=artifact_format)
    assert _JOB_LOCK.acquire(blocking=False)
    _JOB_LOCK.release()
