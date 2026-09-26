"""Full-report lifecycle fixtures; synthetic provenance is not qualification."""

from dataclasses import replace
import os
from pathlib import Path
import threading
import weakref

import pytest

from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, GraphProjectionResult, LegalIRDocument, LogicIRView,
    ProofGateResult, RoundTripMetrics,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_report_session as sessions
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    TargetSnapshotConfig, TargetSnapshotError, _encode, _json,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import LegalSample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    samples = []
    for index in range(3):
        text = f"The agency shall retain synthetic record {index}."
        sample_id = f"synthetic-report-session-{index}"
        samples.append(LegalSample(
            sample_id, "us_code", "5", str(index), f"5 U.S.C. {index}", text, text,
            "mock:synthetic-report", [0.25, -0.0, 0.5, -0.25],
            ModalIRDocument(sample_id, "us_code", text),
        ))
    config = TargetSnapshotConfig(("deontic_norms",), False, 1, {"synthetic_fixture": "a" * 64})
    config_calls = []

    def current(settings):
        config_calls.append(settings)
        return replace(config, bridge_names=settings.legal_ir_bridge_names,
                       evaluate_provers=settings.legal_ir_evaluate_provers,
                       parallel_workers=settings.legal_ir_parallel_workers)

    monkeypatch.setattr(sessions, "target_snapshot_config", current)

    def report(sample, *, partial=False):
        shared = [{"modality": "obligation", "subject": "agency", "action": "retain", "value": -0.0}]
        document = LegalIRDocument(
            sample.sample_id, sample.text, sample.normalized_text, source=sample.source,
            citation=sample.citation,
            views={"deontic.ir": LogicIRView("deontic.ir", {"rules": shared, "alias": shared},
                                           source_component="deontic.ir")},
            metadata={"created_at": "fixed-synthetic-time"},
        )
        adapter = BridgeEvaluationReport(
            "deontic_norms", "deontic.ir", document,
            RoundTripMetrics(cosine_similarity=0.75, cosine_loss=0.25,
                             extra_losses={"synthetic_loss": -0.0}),
            proof_gate=ProofGateResult.disabled(), graph_projection=GraphProjectionResult(),
            decoded_text=sample.text, status="partial", metadata={"synthetic": True},
        )
        return MultiViewLegalIRReport(
            ("deontic_norms",), document,
            {} if partial else {"deontic_norms": adapter},
            {"deontic_norms": "synthetic caught TimeoutError: exact failure text\nretained"} if partial else {},
        )

    def write(*, rows=None, reports=None, statuses=None, bound_config=None, name="synthetic.reports"):
        rows = samples if rows is None else rows
        reports = [report(row) for row in rows] if reports is None else reports
        statuses = [None] * len(rows) if statuses is None else statuses
        saved = codec.write_report_bundle(
            tmp_path / name, list(zip(rows, reports, statuses)), config=bound_config or config)
        return sessions.DaemonReportDescriptor.from_options(
            saved["path"], saved["sha256"], saved["bytes"], saved["snapshot_id"])

    descriptor = write()
    return samples, config, config_calls, report, write, descriptor


def open_session(fixture, descriptor=None, **kwargs):
    return sessions.VerifiedDaemonReportSession(
        descriptor or fixture[-1], bridge_names=kwargs.pop("bridge_names", ("deontic_norms",)),
        evaluate_provers=kwargs.pop("evaluate_provers", False),
        parallel_workers=kwargs.pop("parallel_workers", 1), **kwargs)


def test_descriptor_preserves_existing_strict_four_value_validation():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_target_session import DaemonTargetDescriptor

    assert sessions.DaemonReportDescriptor is DaemonTargetDescriptor
    assert sessions.DaemonReportDescriptor.from_options() is None
    values = ("/tmp/synthetic.reports", "a" * 64, 123, "sha256:" + "b" * 64)
    for index in range(4):
        partial = list(values)
        partial[index] = None
        with pytest.raises(TargetSnapshotError, match="all four"):
            sessions.DaemonReportDescriptor.from_options(*partial)
    with pytest.raises(TargetSnapshotError):
        sessions.DaemonReportDescriptor(values[0], values[1], True, values[3])


@pytest.mark.parametrize("settings", [
    {"evaluate_provers": None}, {"evaluate_provers": 0}, {"parallel_workers": True},
    {"parallel_workers": 0}, {"bridge_names": "deontic_norms"},
    {"bridge_names": ("deontic_norms", "deontic_norms")}, {"max_expanded_bytes": True},
])
def test_runtime_settings_are_never_silently_coerced(fixture, settings):
    with pytest.raises(TargetSnapshotError):
        open_session(fixture, **settings)


def test_one_hydration_supplies_exact_shared_reports_and_targets_and_reordered_reuse(fixture, monkeypatch):
    samples, _, _, report, _, _ = fixture
    with open_session(fixture) as session:
        assert session.reports_for_cycle is None
        observed = []
        original = session._bundle.selection_for

        def select(*args, **kwargs):
            result = original(*args, **kwargs)
            observed.append(result)
            return result

        monkeypatch.setattr(session._bundle, "selection_for", select)
        first = session.begin_cycle([samples[0]], [samples[1], samples[0]])
        reports = session.reports_for_cycle
        assert len(observed) == 1
        assert first is observed[0].targets and reports is observed[0].reports
        assert list(first) == [samples[0].sample_id, samples[1].sample_id]
        for sample in samples[:2]:
            native = report(sample)
            hydrated = reports[sample.sample_id]
            target = first[sample.sample_id]
            assert hydrated.to_dict() == native.to_dict()
            assert _json(_encode(target)) == _json(_encode(native.training_target()))
            assert target.document is hydrated.document
            assert hydrated.document is hydrated.reports["deontic_norms"].ir_document
            payload = hydrated.document.views["deontic.ir"].payload
            assert payload["rules"] is payload["alias"]
        with pytest.raises(TypeError):
            first["extra"] = object()
        with pytest.raises(TypeError):
            reports["extra"] = object()
        lineage = session.lineage_identity
        assert lineage["artifact_kind"] == "full_report_bundle"
        lineage["snapshot_id"] = "tampered"
        assert session.lineage_identity["snapshot_id"] != "tampered"
        session.finish_cycle()
        assert session.reports_for_cycle is None
        second = session.begin_cycle([samples[1], samples[0]], [])
        assert second is first and session.reports_for_cycle is reports
        assert len(observed) == 1
        assert session.finish_cycle()["cache_hit"] is True
        summary = session.verify_shutdown()
        assert summary["counts"] == {"cycles_started": 2, "cycles_completed": 2,
                                     "hydrations": 1, "cache_hits": 1, "skipped_cycles": 0}
        summary["counts"]["hydrations"] = 999
        assert session.summary()["counts"]["hydrations"] == 1
    assert session.reports_for_cycle is None and session.summary()["bundle_statistics"]["closed"]


def test_selection_change_releases_both_cached_graph_maps_before_hydration(fixture, monkeypatch):
    samples = fixture[0]
    with open_session(fixture) as session:
        targets = session.begin_cycle([samples[0]], [])
        target_ref = weakref.ref(targets[samples[0].sample_id])
        report_ref = weakref.ref(session.reports_for_cycle[samples[0].sample_id])
        del targets
        session.finish_cycle()
        original = session._bundle.selection_for

        def select(*args, **kwargs):
            assert target_ref() is None and report_ref() is None
            return original(*args, **kwargs)

        monkeypatch.setattr(session._bundle, "selection_for", select)
        session.begin_cycle([samples[1]], [])
        session.finish_cycle()
        assert session.summary()["counts"]["hydrations"] == 2


@pytest.mark.parametrize("reason", ["bounded_clones", "non_native_consumer", "diagnostic_bridge_mismatch"])
def test_whole_cycle_skip_discards_both_warm_maps_without_inspecting_samples(fixture, reason):
    with open_session(fixture) as session:
        session.begin_cycle([fixture[0][0]], [])
        session.finish_cycle()
        assert session.begin_cycle([object()], [], skip_reason=reason) is None
        assert session.reports_for_cycle is None and session.lineage_identity is None
        assert session._selection_result is None
        assert session.finish_cycle()["skip_reason"] == reason
        session.begin_cycle([fixture[0][0]], [])
        session.finish_cycle()
        assert session.summary()["counts"]["hydrations"] == 2


def test_bridge_off_never_opens_artifact_or_checks_producer(fixture, monkeypatch):
    descriptor = replace(fixture[-1], path="/missing/unused.reports")

    def forbidden(*args, **kwargs):
        raise AssertionError("bridge-off must not open or validate reports")

    monkeypatch.setattr(sessions, "target_snapshot_config", forbidden)
    monkeypatch.setattr(codec, "load_report_bundle", forbidden)
    with open_session(fixture, descriptor, bridge_names=()) as session:
        assert session.begin_cycle([object()], []) is None
        assert session.reports_for_cycle is None
        assert session.finish_cycle()["skip_reason"] == "bridge_off"
        assert session.verify_shutdown()["bundle_statistics"] is None


def test_exact_true_prover_and_parallel_settings_reach_current_config(fixture):
    samples, config, calls, _, write, _ = fixture
    descriptor = write(bound_config=replace(config, evaluate_provers=True, parallel_workers=3),
                       name="configured.reports")
    with open_session(fixture, descriptor, evaluate_provers=True, parallel_workers=3) as session:
        session.begin_cycle([samples[0]], [])
        session.finish_cycle()
        session.verify_shutdown()
    assert calls and all(value.legal_ir_evaluate_provers is True and value.legal_ir_parallel_workers == 3
                         for value in calls)


def test_existing_artifact_rejects_mismatched_runtime_config(fixture):
    with pytest.raises(TargetSnapshotError, match="configuration|provenance"):
        open_session(fixture, parallel_workers=2)


def test_changed_returned_config_is_rejected_without_relying_on_provider_exception(fixture, monkeypatch):
    with open_session(fixture) as session:
        session.begin_cycle([fixture[0][0]], [])
        changed = replace(fixture[1], code_sha256={"changed_synthetic_fixture": "b" * 64})
        monkeypatch.setattr(sessions, "target_snapshot_config", lambda settings: changed)
        with pytest.raises(TargetSnapshotError, match="producer configuration changed"):
            session.finish_cycle()
        assert session.summary()["poisoned"]


def test_partial_report_retains_exact_failures_penalties_and_full_document(fixture):
    samples, _, _, report, write, _ = fixture
    partial = report(samples[0], partial=True)
    descriptor = write(rows=[samples[0]], reports=[partial], name="partial.reports")
    with open_session(fixture, descriptor) as session:
        targets = session.begin_cycle([samples[0]], [])
        hydrated = session.reports_for_cycle[samples[0].sample_id]
        assert hydrated.to_dict() == partial.to_dict()
        assert hydrated.failures == partial.failures
        assert hydrated.accepted is False and targets[samples[0].sample_id].accepted is False
        assert hydrated.proof_failure_ratio == 1.0
        assert _json(_encode(targets[samples[0].sample_id])) == _json(_encode(partial.training_target()))
        completed = session.finish_cycle()
        assert completed["report_statuses"][samples[0].sample_id] == "partial"
        assert completed["applied"] is True and completed["status"] == "completed"


@pytest.mark.parametrize("status", ["timeout", "failed", "unavailable", "unsupported"])
def test_unavailable_member_fails_before_hydration_without_partial_injection(fixture, monkeypatch, status):
    samples, _, _, report, write, _ = fixture
    descriptor = write(rows=samples[:2], reports=[report(samples[0]), None],
                       statuses=[None, status], name=f"{status}.reports")
    with open_session(fixture, descriptor) as session:
        monkeypatch.setattr(session._bundle, "selection_for", lambda *args, **kwargs:
                            pytest.fail("unavailable member must fail in selection preflight"))
        with pytest.raises(codec.ReportUnavailableError):
            session.begin_cycle(samples[:2], [])
        assert session.reports_for_cycle is None and session.lineage_identity is None
        assert session.summary()["poisoned"] and session.summary()["counts"]["hydrations"] == 0


@pytest.mark.parametrize("change", ["missing", "text", "embedding", "conflicting_duplicate"])
def test_missing_or_changed_sample_binding_fails_before_hydration(fixture, monkeypatch, change):
    sample = fixture[0][0]
    train, validation = [sample], []
    if change == "missing":
        train = [replace(sample, sample_id="missing-synthetic")]
    elif change == "text":
        train = [replace(sample, text=sample.text + " changed")]
    elif change == "embedding":
        train = [replace(sample, embedding_vector=[0.0] * 4)]
    else:
        validation = [replace(sample, text=sample.text + " conflicting")]
    with open_session(fixture) as session:
        monkeypatch.setattr(session._bundle, "selection_for", lambda *args, **kwargs:
                            pytest.fail("invalid sample binding must fail before hydration"))
        with pytest.raises(TargetSnapshotError):
            session.begin_cycle(train, validation)
        assert session.summary()["poisoned"]


def test_expanded_report_bound_precedes_hydration(fixture, monkeypatch):
    with open_session(fixture, max_expanded_bytes=1) as session:
        monkeypatch.setattr(session._bundle, "selection_for", lambda *args, **kwargs:
                            pytest.fail("expanded bound must fail before hydration"))
        with pytest.raises(TargetSnapshotError, match="expanded"):
            session.begin_cycle([fixture[0][0]], [])


@pytest.mark.parametrize("duplicate", [False, True])
def test_mutating_any_original_input_prevents_cycle_completion(fixture, duplicate):
    sample = fixture[0][0]
    other = replace(sample, parser_trace=dict(sample.parser_trace)) if duplicate else sample
    with open_session(fixture) as session:
        targets = session.begin_cycle([sample], [other] if duplicate else [])
        assert len(targets) == 1
        other.parser_trace["synthetic_mutation"] = {"nested": 1}
        with pytest.raises(TargetSnapshotError, match="aliases|changed during"):
            session.finish_cycle()
        assert session.reports_for_cycle is None
        assert session.summary()["poisoned"] and session.summary()["counts"]["cycles_completed"] == 0


@pytest.mark.parametrize("boundary", ["begin", "finish", "shutdown"])
def test_source_change_poisons_session_at_every_boundary(fixture, monkeypatch, boundary):
    with open_session(fixture) as session:
        if boundary != "begin":
            session.begin_cycle([fixture[0][0]], [])
        if boundary == "shutdown":
            session.finish_cycle()

        def changed(settings):
            raise ValueError("synthetic producer changed; start a fresh process")

        monkeypatch.setattr(sessions, "target_snapshot_config", changed)
        with pytest.raises(ValueError, match="fresh process"):
            {"begin": lambda: session.begin_cycle([fixture[0][0]], []),
             "finish": session.finish_cycle, "shutdown": session.verify_shutdown}[boundary]()
        assert session.summary()["poisoned"] and session.reports_for_cycle is None


@pytest.mark.parametrize("mutation", ["same_inode", "replacement"])
def test_file_mutation_rejected_at_finish_and_codec_handle_closed(fixture, mutation):
    path = Path(fixture[-1].path)
    session = open_session(fixture)
    session.begin_cycle([fixture[0][0]], [])
    if mutation == "same_inode":
        with path.open("r+b") as handle:
            handle.seek(-1, os.SEEK_END)
            value = handle.read(1)
            handle.seek(-1, os.SEEK_END)
            handle.write(bytes([value[0] ^ 1]))
    else:
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    try:
        with pytest.raises(TargetSnapshotError):
            session.finish_cycle()
    finally:
        session.close()
    assert session.summary()["poisoned"] and session.summary()["bundle_statistics"]["closed"]


def test_provisional_shutdown_abort_and_owning_thread_contract(fixture):
    with open_session(fixture) as session:
        errors = []

        def wrong_thread():
            try:
                session.begin_cycle([fixture[0][0]], [])
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=wrong_thread)
        thread.start()
        thread.join()
        assert len(errors) == 1 and "owning thread" in str(errors[0])
        assert session.summary()["counts"]["cycles_started"] == 0
        session.begin_cycle([fixture[0][0]], [])
        with pytest.raises(TargetSnapshotError, match="provisional"):
            session.verify_shutdown()
        session.abort_cycle(RuntimeError("synthetic original"))
        assert session.summary()["failure"] == {"exception_type": "RuntimeError"}
        assert session.reports_for_cycle is None
        with pytest.raises(TargetSnapshotError, match="poisoned"):
            session.begin_cycle([fixture[0][0]], [])


def test_snapshot_identity_mismatch_closes_the_newly_loaded_codec_handle(fixture, monkeypatch):
    opened = []
    original = codec.load_report_bundle

    def load(*args, **kwargs):
        value = original(*args, **kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(codec, "load_report_bundle", load)
    with pytest.raises(TargetSnapshotError, match="snapshot identity"):
        open_session(fixture, replace(fixture[-1], snapshot_id="sha256:" + "f" * 64))
    assert opened[0].statistics["closed"] is True
