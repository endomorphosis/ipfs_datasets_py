"""Full report preparation keeps native outcomes without live bridge services."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, GraphProjectionResult, LegalIRDocument,
    ProofGateResult, RoundTripMetrics,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_report_preparation as prep
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord, TrainingConfig, _JOB_LOCK
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


NAMES = ("modal_frame_logic", "deontic_norms")


@pytest.fixture
def bound(monkeypatch):
    value = TargetSnapshotConfig(bridge_names=NAMES, evaluate_provers=False, parallel_workers=1,
        code_sha256={"fixture.py": "a" * 64},
        dependency_provenance={"target_timeout_enforcement": "main_thread_sigalrm"},
        target_timeout_seconds=15.0)
    monkeypatch.setattr(prep, "target_snapshot_config", lambda config: value)
    return value


def record(section="fixture", vector=(0.25, -0.0)):
    return SampleRecord("5", section, "The agency shall not disclose records.",
                        embedding_model="fixture:supplied", embedding_vector=vector)


def report_for(kwargs, *, partial=False):
    shared = {"exact": ["Unicode é", -0.0, (1, 2)]}
    document = LegalIRDocument(kwargs["document_id"], kwargs["text"], kwargs["text"],
        source=kwargs["source"], citation=kwargs["citation"], metadata=shared,
        frame_logic_triples=({"subject": "agency", "predicate": "modality", "object": "prohibition"},))
    bridge = BridgeEvaluationReport(NAMES[0], "fixture", document, RoundTripMetrics(cosine_similarity=0.75),
        proof_gate=ProofGateResult.disabled(), status="ok", metadata=shared,
        graph_projection=GraphProjectionResult(neo4j_compatible=True, node_count=2, relationship_count=1))
    return MultiViewLegalIRReport(NAMES, document,
        reports={NAMES[0]: bridge} if partial else {NAMES[0]: bridge, NAMES[1]: replace(bridge, adapter_name=NAMES[1])},
        failures={NAMES[1]: "ValueError: exact failure\nUnicode é"} if partial else {})


def load(receipt, samples, bound):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_report_bundle import load_report_bundle
    return load_report_bundle(receipt["artifact"]["path"], expected_sha256=receipt["artifact"]["sha256"],
        expected_size_bytes=receipt["artifact"]["bytes"], config=bound)


def test_native_generation_once_default_guidance_and_cache_bypass(bound, monkeypatch, tmp_path):
    calls = []
    originals = {}
    def generate(callback, **kwargs):
        calls.append(kwargs)
        assert kwargs["cache"] is False and kwargs["compiler_guidance"] is None
        assert kwargs["evaluate_provers"] is False and kwargs["timeout_seconds"] == 15.0
        result = report_for(kwargs)
        originals[kwargs["document_id"]] = result
        return result
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", generate)
    monkeypatch.setattr(modal, "_legal_ir_target_items", lambda *a, **k: pytest.fail("target cache consulted"))
    monkeypatch.setattr(modal, "_read_legal_ir_target_disk_cache", lambda *a, **k: pytest.fail("disk cache consulted"))
    rows = [record(), record("second")]
    receipt = prep.prepare_legal_ir_reports(rows[:1], tmp_path / "reports.bundle",
        validation_records=rows, training_config=TrainingConfig(legal_ir_bridge_names=NAMES))
    assert len(calls) == receipt["sample_count"] == receipt["report_count"] == 2
    assert set(receipt["statuses"].values()) == {"ready"}
    assert receipt["compiler_guidance"] is None
    assert receipt["separate_target_artifact_written"] is False and receipt["admitted"] is False
    samples = [build_us_code_sample(**row.__dict__) for row in rows]
    bundle = load(receipt, samples, bound)
    try:
        selection = bundle.selection_for(samples, config=bound)
        for sample in samples:
            recovered = selection.reports[sample.sample_id]
            assert recovered == originals[sample.sample_id]
            assert recovered.document is recovered.reports[NAMES[0]].ir_document
            assert selection.targets[sample.sample_id].document is recovered.document
            assert selection.targets[sample.sample_id].to_dict() == originals[sample.sample_id].training_target().to_dict()
    finally:
        bundle.close()


def test_returned_partial_report_keeps_exact_failure(bound, monkeypatch, tmp_path):
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", lambda callback, **kw: report_for(kw, partial=True))
    receipt = prep.prepare_legal_ir_reports([record()], tmp_path / "partial", training_config=TrainingConfig(legal_ir_bridge_names=NAMES))
    assert set(receipt["statuses"].values()) == {"partial"}
    telemetry = next(iter(receipt["bridge_report_telemetry"].values()))
    assert telemetry["failed_bridge_names"] == [NAMES[1]]
    assert telemetry["failures"] == {NAMES[1]: "ValueError: exact failure\nUnicode é"}
    assert telemetry["report_received"] is True and telemetry["outer_timeout"] is None


def test_silent_missing_adapter_is_partial_without_fabricated_failure(bound, monkeypatch, tmp_path):
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout",
        lambda callback, **kw: replace(report_for(kw, partial=True), failures={}))
    receipt = prep.prepare_legal_ir_reports([record()], tmp_path / "missing-adapter",
        training_config=TrainingConfig(legal_ir_bridge_names=NAMES))
    assert set(receipt["statuses"].values()) == {"partial"}
    telemetry = next(iter(receipt["bridge_report_telemetry"].values()))
    assert telemetry["attempted_bridge_count"] == 2 and telemetry["implemented_bridge_count"] == 1
    assert telemetry["failed_bridge_count"] == 0 and telemetry["failures"] == {}


@pytest.mark.parametrize("outcome", ["timeout", "unavailable"])
def test_missing_report_has_no_invented_target(bound, monkeypatch, tmp_path, outcome):
    def generate(*args, **kwargs):
        if outcome == "timeout":
            raise modal._LegalIRTargetTimeout("exact timeout")
        return None
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", generate)
    receipt = prep.prepare_legal_ir_reports([record()], tmp_path / outcome, training_config=TrainingConfig(legal_ir_bridge_names=NAMES))
    assert receipt["report_count"] == 0 and set(receipt["statuses"].values()) == {outcome}
    telemetry = next(iter(receipt["bridge_report_telemetry"].values()))
    assert telemetry["report_received"] is False and telemetry["implemented_bridge_count"] is None
    sample = build_us_code_sample(**record().__dict__)
    bundle = load(receipt, [sample], bound)
    try:
        with pytest.raises(ValueError):
            bundle.selection_for([sample], config=bound)
    finally:
        bundle.close()


@pytest.mark.parametrize("exception", [ValueError("exact"), KeyboardInterrupt("exact")])
def test_unexpected_exception_identity_and_job_lock_restored(bound, monkeypatch, tmp_path, exception):
    def failed(*args, **kwargs):
        raise exception
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", failed)
    destination = tmp_path / "failure"
    with pytest.raises(type(exception)) as caught:
        prep.prepare_legal_ir_reports([record()], destination, training_config=TrainingConfig(legal_ir_bridge_names=NAMES))
    assert caught.value is exception and not destination.exists()
    assert _JOB_LOCK.acquire(blocking=False)
    _JOB_LOCK.release()


def test_final_source_drift_refuses_publication(bound, monkeypatch, tmp_path):
    checks = iter([bound, replace(bound, code_sha256={"fixture.py": "b" * 64})])
    monkeypatch.setattr(prep, "target_snapshot_config", lambda config: next(checks))
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", lambda callback, **kw: report_for(kw))
    destination = tmp_path / "drift"
    with pytest.raises(ValueError, match="producer changed"):
        prep.prepare_legal_ir_reports([record()], destination, training_config=TrainingConfig(legal_ir_bridge_names=NAMES))
    assert not destination.exists()


def test_non_native_report_not_inspected_or_published(bound, monkeypatch, tmp_path):
    class Hostile:
        def __getattribute__(self, key):
            raise AssertionError("custom report inspected")
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", lambda *a, **kw: Hostile())
    with pytest.raises(TypeError, match="non-native"):
        prep.prepare_legal_ir_reports([record()], tmp_path / "custom", training_config=TrainingConfig(legal_ir_bridge_names=NAMES))


def test_exact_inputs_and_exclusive_job_scope(bound, tmp_path):
    class CustomRecord(SampleRecord):
        pass
    with pytest.raises(ValueError, match="exact SampleRecord"):
        prep.prepare_legal_ir_reports([CustomRecord(**record().__dict__)], tmp_path / "custom")
    with pytest.raises(TypeError, match="exact TrainingConfig"):
        prep.prepare_legal_ir_reports([record()], tmp_path / "config", training_config=SimpleNamespace())
    assert _JOB_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="beside another job"):
            prep.prepare_legal_ir_reports([record()], tmp_path / "busy")
    finally:
        _JOB_LOCK.release()


def test_native_harness_graph_comparison_and_report_flags(monkeypatch):
    import copy
    from pathlib import Path
    from ipfs_datasets_py.logic.bridge.types import LogicIRView
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_report_bundle import report_from_bytes, report_to_bytes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir"))
    import benchmark_daemon_shared_reports as harness

    payload = {"metadata": {"created_at": "2026-09-25T00:00:00+00:00", "last_updated": "2026-09-25T00:00:01+00:00"},
               "nodes": [{"value": -0.0}]}
    document = LegalIRDocument("smoke", "The agency shall act.", "The agency shall act.",
        views={"deontic_norms.deontic_graph": LogicIRView("deontic_graph", payload)})
    bridge = BridgeEvaluationReport("deontic_norms", "fixture", document, RoundTripMetrics(cosine_similarity=0.25),
        proof_gate=ProofGateResult.disabled(), metadata={"shared": payload})
    original = MultiViewLegalIRReport(("deontic_norms",), document, reports={"deontic_norms": bridge})
    raw = report_to_bytes(original)
    restored = report_from_bytes(raw)
    assert harness.native_fingerprint(original) == harness.native_fingerprint(restored)
    assert harness.graph_differences(original, restored)["strict_native_graph_equal"]
    mutations = {
        "loss": lambda r: object.__setattr__(r.reports["deontic_norms"].round_trip, "cosine_loss", 0.2),
        "status": lambda r: object.__setattr__(r.reports["deontic_norms"], "status", "failed"),
        "failure": lambda r: r.failures.update({"deontic_norms": "exact failure"}),
        "signed_zero": lambda r: r.document.views["deontic_norms.deontic_graph"].payload["nodes"][0].update(value=0.0),
        "alias": lambda r: r.reports["deontic_norms"].metadata.update(shared=copy.deepcopy(r.document.views["deontic_norms.deontic_graph"].payload)),
        "unrelated_date": lambda r: r.reports["deontic_norms"].metadata.update(created_at="2026-09-25T01:00:00+00:00"),
    }
    for name, mutate in mutations.items():
        changed = report_from_bytes(raw)
        mutate(changed)
        diff = harness.graph_differences(original, changed)
        assert not diff["strict_native_graph_equal"], name
        assert not diff["only_observed_explicit_deontic_wall_timestamps"], name
    changed = report_from_bytes(raw)
    metadata = changed.document.views["deontic_norms.deontic_graph"].payload["metadata"]
    metadata["created_at"] = "2026-09-25T01:00:00+00:00"
    diff = harness.graph_differences(original, changed)
    assert diff["difference_count"] == 1 and diff["only_observed_explicit_deontic_wall_timestamps"]
    assert not diff["strict_native_graph_equal"]
    metadata["created_at"] = metadata.pop("created_at")
    assert not harness.graph_differences(original, changed)["only_observed_explicit_deontic_wall_timestamps"]
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(
        harness.base.daemon_argv("parser-smoke", 8192, {}, "cold") + [
        "--autoencoder-report-bundle", "/tmp/not-opened.bundle", "--autoencoder-report-bundle-sha256", "a" * 64,
        "--autoencoder-report-bundle-bytes", "123", "--autoencoder-report-snapshot-id", "sha256:" + "b" * 64])
    assert args.autoencoder_report_bundle_sha256 == "a" * 64 and args.autoencoder_report_bundle_bytes == 123
    assert args.autoencoder_target_bundle is None


@pytest.mark.parametrize("exception", [ValueError("serialization failed"), KeyboardInterrupt("cancelled")])
def test_harness_failed_fingerprint_attempt_is_charged_and_exception_preserved(monkeypatch, exception):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir"))
    import benchmark_daemon_shared_reports as harness
    def failed(report, *, attempt):
        attempt["phase"] = "report_to_bytes"
        raise exception
    monkeypatch.setattr(harness, "report_evidence", failed)
    observation = {"fingerprint_attempts": [], "fingerprint_seconds_outside_generation_intervals": 1.0}
    with pytest.raises(type(exception)) as caught:
        harness.observed_report_evidence(object(), "sample", observation)
    assert caught.value is exception
    attempt, = observation["fingerprint_attempts"]
    assert attempt["phase"] == "report_to_bytes" and attempt["status"] == "failed"
    assert attempt["error"] == {"type": "builtins." + type(exception).__name__, "message": str(exception)}
    assert attempt["elapsed_seconds"] >= 0
    assert observation["fingerprint_seconds_outside_generation_intervals"] == 1.0 + attempt["elapsed_seconds"]
    assert set(attempt) == {"sample_id", "phase", "status", "error", "elapsed_seconds"}


def test_harness_audit_bounds_and_scalar_value_memoization(monkeypatch):
    from pathlib import Path
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as codec
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir"))
    import benchmark_daemon_shared_reports as harness
    assert harness.MAX_REPORT_BYTES == codec.DEFAULT_MAX_SHARD_BYTES == 64 * 1024 * 1024
    assert harness.MAX_AUDIT_TOKEN_BYTES == codec.MAX_EXPANDED_GRAPH_BYTES == 256 * 1024 * 1024
    assert harness.MAX_NATIVE_COMPOUNDS == codec.MAX_NODES == 1_000_000
    assert harness.MAX_NATIVE_DEPTH == codec.MAX_DEPTH == 100
    assert harness.MAX_NATIVE_VALUES == codec.MAX_EXPANDED_GRAPH_BYTES
    text = "exact Unicode é, duplicates retained " * 1000
    left, right = [text, text], [text, text.encode().decode()]
    assert right[0] is not right[1]
    fingerprint = harness.native_fingerprint(left)
    assert fingerprint == harness.native_fingerprint(right)
    assert fingerprint["schema"] == "native-fields-order-alias-fingerprint-v2"
    assert fingerprint["unique_string_values"] == 1 and fingerprint["visited_values"] == 3
    assert fingerprint["charged_bytes"] < len(text.encode()) * 2
    assert harness.graph_differences(left, right)["strict_native_graph_equal"]
    # Repeated memoized scalar occurrences remain charged as traversal work.
    monkeypatch.setattr(harness, "MAX_NATIVE_VALUES", 2)
    with pytest.raises(ValueError, match="node/depth bound"):
        harness.native_fingerprint(left)
    with pytest.raises(ValueError, match="node/depth bound"):
        harness.graph_differences(left, right)
