"""Full-report aggregation parity and actual-run wiring; no performance claims."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic import bridge
from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport, GraphProjectionResult, LegalIRDocument, LogicIRView,
    ProofGateResult, RoundTripMetrics,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_shared_target_integration import actual_run, _sample


BRIDGES = ("deontic_norms", "fol_tdfol")


def _report(sample, *, partial=False):
    view = LogicIRView("deontic.ir", {"ordered": [2, 1]}, "deontic.ir", "deontic.ir",
                       {"number": 0.375, "flag": True})
    document = LegalIRDocument(sample.sample_id, sample.text, sample.normalized_text,
                               sample.source, sample.citation, {"deontic.ir": view},
                               ({"subject": "agency", "predicate": "shall", "object": "retain"},))
    reports = {}
    for name in BRIDGES[:1] if partial else BRIDGES:
        reports[name] = BridgeEvaluationReport(
            name, "deontic.ir", document,
            RoundTripMetrics(cosine_similarity=0.625, cosine_loss=0.375,
                             cross_entropy_loss=0.75, reconstruction_loss=0.25,
                             extra_losses={"extra_native_loss": 0.125}),
            ProofGateResult(5, 1, 1, 1, 2, ("native:test",), ({"ordered": [2, 1]},)),
            GraphProjectionResult("graph", True, 5, 7, ("z", "a"), ("b", "a")),
            decoded_text="The agency retains the record.", status="partial",
            metadata={"proof_gate_soft_pass": False},
        )
    return MultiViewLegalIRReport(BRIDGES, document, reports,
                                 {"fol_tdfol": "synthetic adapter timeout"} if partial else {})


def _forbidden(*args, **kwargs):
    raise AssertionError("explicit reports must bypass report generation and ordinary caches")


@pytest.mark.parametrize("workers", [1, 2])
def test_full_reports_preserve_all_diagnostic_metrics_and_failure_counts(monkeypatch, workers):
    samples = [_sample(0), _sample(1)]
    reports = {row.sample_id: _report(row, partial=index == 1) for index, row in enumerate(samples)}
    monkeypatch.setattr(runner, "_BRIDGE_IR_REPORT_CACHE", {})
    monkeypatch.setattr(runner, "_metric_disk_cache_enabled", lambda: False)
    monkeypatch.setattr(runner, "_read_metric_disk_cache", lambda *args: None)
    monkeypatch.setattr(modal, "_read_legal_ir_target_disk_cache", lambda *args: None)
    monkeypatch.setattr(modal, "_write_legal_ir_target_disk_cache", lambda *args: None)
    monkeypatch.setattr(bridge, "evaluate_legal_ir_multiview", lambda text, **kw: reports[kw["document_id"]])
    baseline = runner.bridge_ir_metric_block(samples, BRIDGES, evaluate_provers=False, parallel_workers=workers)
    cached_before = dict(runner._BRIDGE_IR_REPORT_CACHE)
    monkeypatch.setattr(bridge, "evaluate_legal_ir_multiview", _forbidden)
    monkeypatch.setattr(runner, "_read_metric_disk_cache", _forbidden)
    monkeypatch.setattr(runner, "_write_metric_disk_cache", _forbidden)
    monkeypatch.setattr(modal, "_read_legal_ir_target_disk_cache", _forbidden)
    monkeypatch.setattr(modal, "_write_legal_ir_target_disk_cache", _forbidden)
    # A configured disk cache must still be bypassed for the supplied graphs.
    monkeypatch.setattr(runner, "_metric_disk_cache_enabled", lambda: True)
    events = []
    explicit = runner.bridge_ir_metric_block(
        samples, BRIDGES, evaluate_provers=False, parallel_workers=workers,
        legal_ir_reports=reports, legal_ir_report_identity={"snapshot_id": "fixture"},
        progress_callback=events.append,
    )
    differing_telemetry = {"cache_hits", "cache_misses", "cache_size", "evaluation_seconds_max",
                          "persistent_cache_enabled", "legal_ir_target_cache_exports",
                          "supplied_report_count", "report_source", "persistent_cache_policy",
                          "verified_report_identity"}
    assert {k: v for k, v in baseline.items() if k not in differing_telemetry} == {
        k: v for k, v in explicit.items() if k not in differing_telemetry}
    assert explicit["metric_failures"] == 1
    assert explicit["adapters"]["fol_tdfol"]["metric_failures"] == 1
    assert explicit["adapters"]["deontic_norms"]["proof_failed_count"] == 2.0
    assert explicit["canonical_ir"]["document_hashes"] == baseline["canonical_ir"]["document_hashes"]
    assert explicit["supplied_report_count"] == 2
    assert explicit["cache_hits"] == explicit["cache_misses"] == explicit["legal_ir_target_cache_exports"] == 0
    assert runner._BRIDGE_IR_REPORT_CACHE == cached_before
    reused = [event for event in events if event.get("cache_source") == "explicit_report"]
    assert len(reused) == 2 and all(event["stage"] == "sample_done" for event in reused)


@pytest.mark.parametrize("failure", ["missing", "summary", "bridge_order", "text", "citation", "source", "document_id", "clones"])
def test_invalid_explicit_report_inventory_fails_before_cache_lookup(monkeypatch, failure):
    sample = _sample()
    report = _report(sample)
    if failure == "bridge_order":
        report = replace(report, bridge_names=tuple(reversed(BRIDGES)))
    if failure in {"text", "citation", "source", "document_id"}:
        field = "source_text" if failure == "text" else failure
        report = replace(report, document=replace(report.document, **{field: "changed"}))
    reports = {} if failure == "missing" else {sample.sample_id: SimpleNamespace() if failure == "summary" else report}
    monkeypatch.setattr(runner, "_read_metric_disk_cache", _forbidden)
    with pytest.raises(ValueError):
        runner.bridge_ir_metric_block([sample], BRIDGES, legal_ir_reports=reports,
                                      max_sample_text_chars=10 if failure == "clones" else 0)


def test_bridge_off_diagnostics_ignore_supplied_reports(monkeypatch):
    monkeypatch.setattr(runner, "_read_metric_disk_cache", lambda *args: None)
    class Unreadable(dict):
        def get(self, *args):
            raise AssertionError("bridge-off must not inspect supplied reports")
    result = runner.bridge_ir_metric_block([_sample()], (), legal_ir_reports=Unreadable())
    assert result["evaluated_count"] == 0 and "supplied_report_count" not in result


@pytest.mark.parametrize("custom", ["diagnostics", "aggregation", "bridges"])
def test_report_eligibility_requires_native_diagnostics_and_exact_order(monkeypatch, custom):
    model = modal.AdaptiveModalAutoencoder(compute_device="python")
    kwargs = {"max_bridge_sample_text_chars": 0, "metric_bridge_names": BRIDGES,
              "diagnostic_bridge_names": BRIDGES}
    assert runner._daemon_shared_report_skip_reason(model, [_sample()], **kwargs) is None
    if custom == "bridges":
        kwargs["diagnostic_bridge_names"] = tuple(reversed(BRIDGES))
        expected = "diagnostic_bridge_names_differ"
    else:
        monkeypatch.setattr(runner, "bridge_ir_metric_block" if custom == "diagnostics" else "_adapter_metrics_from_reports", _forbidden)
        expected = "non_native_diagnostic_consumer"
    assert runner._daemon_shared_report_skip_reason(model, [_sample()], **kwargs) == expected


def _report_case(case, monkeypatch):
    for suffix in ("bundle", "bundle_sha256", "bundle_bytes", "snapshot_id"):
        setattr(case.args, "autoencoder_report_" + suffix, getattr(case.args, "autoencoder_target_" + suffix))
        setattr(case.args, "autoencoder_target_" + suffix, None)
    reports = {}
    for sample in (*case.train, *case.validation):
        report = _report(sample)
        reports[sample.sample_id] = replace(
            report, bridge_names=("deontic_norms",),
            reports={"deontic_norms": report.reports["deontic_norms"]},
        )
    parent = runner.VerifiedDaemonTargetSession  # Synthetic fixture session.
    class Session(parent):
        @property
        def reports_for_cycle(self):
            assert self.active and self.current_skip is None
            return reports
    monkeypatch.setattr(runner, "VerifiedDaemonReportSession", Session)
    monkeypatch.setattr(runner, "_daemon_shared_report_skip_reason", lambda *args, **kwargs: case.seen.skip_reason)
    native_fixture_diagnostics = runner.bridge_ir_metric_block
    calls = []
    def diagnostics(rows, *args, **kwargs):
        calls.append((list(rows), kwargs))
        return native_fixture_diagnostics(rows, *args, **kwargs)
    monkeypatch.setattr(runner, "bridge_ir_metric_block", diagnostics)
    return reports, calls


def test_actual_daemon_supplies_same_selection_to_diagnostics_and_projection(actual_run, monkeypatch):
    case = actual_run
    reports, calls = _report_case(case, monkeypatch)
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    assert len(calls) == 2
    assert all(kwargs["legal_ir_reports"] is reports for _, kwargs in calls)
    assert all(kwargs["legal_ir_report_identity"] == case.seen.lineages[0][1]["target_bundle_identity"] for _, kwargs in calls)
    assert case.seen.projections[0][1]["legal_ir_targets"] is case.targets
    assert case.seen.sessions[0].closed
    assert case.summary()["final_state_persistence"]["durable"] is True


@pytest.mark.parametrize("reason", ["bounded_clones", "non_native_consumer", "diagnostic_bridge_names_differ", "non_native_diagnostic_consumer", "bridge_off"])
def test_actual_daemon_report_skips_keep_both_consumers_live(actual_run, monkeypatch, reason):
    case = actual_run
    _, calls = _report_case(case, monkeypatch)
    if reason == "bridge_off":
        case.args.autoencoder_metric_bridge_adapters = "none"
    else:
        case.seen.skip_reason = reason
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    assert all("legal_ir_reports" not in kwargs for _, kwargs in calls)
    assert all("legal_ir_targets" not in kwargs for _, kwargs in case.seen.projections)
    assert case.seen.sessions[0].closed


@pytest.mark.parametrize("failure", ["begin", "finish", "shutdown", "consumer"])
def test_report_failure_cannot_write_clean_shutdown_checkpoint(actual_run, monkeypatch, failure):
    case = actual_run
    _report_case(case, monkeypatch)
    if failure == "consumer":
        case.seen.projection_error = ValueError("synthetic report consumer failure")
    elif failure == "shutdown":
        case.seen.fail_shutdown = True
    else:
        setattr(case.seen, "fail_" + failure, 1)
    with pytest.raises(ValueError):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.sessions[0].closed and case.seen.sessions[0].poisoned
    assert all(row.get("metadata", {}).get("reason") != "clean_shutdown" for row in case.seen.checkpoint_writes)
    assert case.summary()["final_state_persistence"]["checkpoint_enqueued"] is False


def test_report_cli_forwarding_and_mutual_exclusion(tmp_path):
    parser = runner.build_uscode_modal_daemon_arg_parser()
    flags = ["--autoencoder-report-bundle", str(tmp_path / "reports.bundle"),
             "--autoencoder-report-bundle-sha256", "a" * 64,
             "--autoencoder-report-bundle-bytes", "123",
             "--autoencoder-report-snapshot-id", "sha256:" + "b" * 64]
    args = parser.parse_args(["--run-id", "reports", *flags])
    commands = runner.build_paired_daemon_commands(args, module_name=runner.__name__)
    for flag, value in zip(flags[::2], flags[1::2]):
        command = commands["autoencoder_command"]
        assert command[command.index(flag) + 1] == value
        assert flag not in commands["codex_command"]
    for suffix in ("bundle", "bundle_sha256", "bundle_bytes", "snapshot_id"):
        setattr(args, "autoencoder_target_" + suffix, getattr(args, "autoencoder_report_" + suffix))
    with pytest.raises(ValueError, match="either"):
        runner.build_paired_daemon_commands(args, module_name=runner.__name__)
    with pytest.raises(ValueError, match="either"):
        runner.run_guarded_uscode_modal_daemon(args)
