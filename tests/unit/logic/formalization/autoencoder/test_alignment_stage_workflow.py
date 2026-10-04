"""Bounded file publication, reference ordering and raw-only subprocess checks."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_stage_declarations as core
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_stage_workflow as subject


def fixtures(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("workflow_fixture_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


raw_fixture = fixtures("test_alignment_raw_ranking")
stage_fixture = fixtures("test_alignment_stage_declarations")


def write(path, value=None, *, data=None):
    data = core._raw(value) + b"\n" if data is None else data
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def inputs(tmp_path, stage="fit", *, case=None):
    extra = {}
    if stage == "rank":
        declaration, query, bank, selected = case or raw_fixture.case(query_statuses=("available", "unavailable"))
        expected = selected["expected_bindings"]
        extra["lane_bundle_selections"] = {
            "query_bundle": write(tmp_path / "query-bundle.json", query),
            "bank_bundle": write(tmp_path / "bank-bundle.json", bank),
            "expected_query_lane": write(tmp_path / "query-pins.json", selected["expected_query_lane"]),
            "expected_bank_lane": write(tmp_path / "bank-pins.json", selected["expected_bank_lane"])}
    elif stage == "score":
        declaration = stage_fixture.score_declaration(not_executed=True)
        expected = stage_fixture.pins(declaration)
        extra["saved_rankings_binding"] = write(tmp_path / "durable-saved.json", declaration["saved_rankings"])
        extra["reference_bundle_binding"] = write(tmp_path / "references.json", declaration["references"])
    else:
        declaration = stage_fixture.fit_declaration()
        expected = stage_fixture.pins(declaration)
    declaration_binding = write(tmp_path / "declaration.json", declaration)
    expected_binding = write(tmp_path / "expected.json", expected)
    return declaration, expected, (stage, declaration_binding, expected_binding, tmp_path / "output"), extra


@pytest.mark.parametrize("stage", ["fit", "rank", "score"])
def test_actual_subprocess_publishes_private_inactive_diagnostics(tmp_path, stage):
    declaration, expected, args, extra = inputs(tmp_path, stage)
    original = deepcopy((declaration, expected, extra))
    result = subject.run_alignment_stage(*args, **extra)
    assert (declaration, expected, extra) == original
    directory = args[-1]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert result["os_sandbox"] is False
    assert result["child_isolation"] == "trusted_resource_bounded_subprocess"
    assert result["selected_file_bindings_verified"] is True
    assert result["masks"] == dict.fromkeys(core.MASKS, 0)
    assert result["model_calls"] == result["encoder_calls"] == result["prover_calls"] == result["optimizer_updates"] == 0
    assert result["source_fidelity_established"] is result["accepted"] is result["qualified"] is False
    assert result["training_executed"] is result["scoring_executed"] is False
    assert result["ranking_operation_executed"] is (stage == "rank")
    assert result["worker_usage"]["cpu_seconds"] >= 0
    assert 0 < result["worker_usage"]["peak_rss_kib"] < subject.MEMORY_BYTES // 1024
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads((directory / "report.json").read_text()) == result
    for binding in result["artifacts"].values():
        assert hashlib.sha256(Path(binding["path"]).read_bytes()).hexdigest() == binding["sha256"]
    if stage == "rank":
        saved = json.loads((directory / "saved_rankings.json").read_text())
        assert saved["rank_declaration"] == declaration
        assert saved["rows"][1]["status"] == "unavailable" and saved["rows"][1]["hits"] == []
        assert result["status"] == "completed_diagnostic_raw_ranking"
    if stage == "score":
        assert result["pre_reference_saved_integrity_checked"] is True
        order = result["read_order"]
        assert order.index(extra["saved_rankings_binding"]["path"]) < order.index(args[1]["path"])
        assert order.index(extra["saved_rankings_binding"]["path"]) < order.index(extra["reference_bundle_binding"]["path"])


def test_fresh_directory_rejects_overwrite(tmp_path):
    _, _, args, extra = inputs(tmp_path)
    subject.run_alignment_stage(*args, **extra)
    before = (args[-1] / "report.json").read_bytes()
    with pytest.raises(ValueError, match="fresh"):
        subject.run_alignment_stage(*args, **extra)
    assert (args[-1] / "report.json").read_bytes() == before


@pytest.mark.parametrize("changed", ["sha256", "bytes"])
def test_wrong_external_file_selection_fails_without_publication(tmp_path, changed):
    _, _, args, extra = inputs(tmp_path)
    args = list(args)
    args[1] = {**args[1], changed: "a" * 64 if changed == "sha256" else args[1]["bytes"] + 1}
    with pytest.raises(ValueError):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


@pytest.mark.parametrize("data", [b'{"x":1,"x":2}', b'{"x":NaN}', '{"x":"é"}'.encode("utf-16"), b'\xff'])
def test_strict_json_rejects_ambiguous_or_nonutf8_inputs(tmp_path, data):
    _, _, args, extra = inputs(tmp_path)
    args = list(args)
    args[2] = write(tmp_path / "bad.json", data=data)
    with pytest.raises(ValueError):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


@pytest.mark.parametrize("component", ["leaf", "parent"])
def test_symlink_components_are_rejected_before_child(tmp_path, component):
    _, _, args, extra = inputs(tmp_path)
    args = list(args)
    if component == "leaf":
        target = tmp_path / "linked.json"
        target.symlink_to(args[1]["path"])
        args[1] = {**args[1], "path": str(target)}
    else:
        target = tmp_path / "linked-parent"
        target.symlink_to(tmp_path, target_is_directory=True)
        args[1] = {**args[1], "path": str(target / "declaration.json")}
    with pytest.raises(ValueError, match="symlink"):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


def test_nonregular_input_is_nonblocking_and_rejected(tmp_path):
    _, _, args, extra = inputs(tmp_path)
    args = list(args)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    args[1] = {"path": str(fifo), "sha256": "a" * 64, "bytes": 1}
    with pytest.raises(ValueError):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


@pytest.mark.parametrize("timeout", [True, 0, 61, 1.0])
def test_timeout_requires_bounded_exact_integer(tmp_path, timeout):
    _, _, args, extra = inputs(tmp_path)
    with pytest.raises(ValueError, match="worker timeout"):
        subject.run_alignment_stage(*args, **extra, worker_timeout_seconds=timeout)


def test_selected_file_aggregate_budget_is_checked_before_worker(tmp_path, monkeypatch):
    _, _, args, extra = inputs(tmp_path)
    oversized = {"path": str(tmp_path / "not-read.json"), "sha256": "a" * 64, "bytes": subject.MAX_FILE_BYTES}
    monkeypatch.setattr(subject, "_child", lambda *args: pytest.fail("worker started"))
    with pytest.raises(ValueError, match="aggregate"):
        subject.run_alignment_stage(*args, **extra, role_file_selections={"one": oversized,
            "two": {**oversized, "path": str(tmp_path / "two.json")},
            "three": {**oversized, "path": str(tmp_path / "three.json")}})


def test_nonnull_role_file_requires_explicit_detached_payload_and_checks_content(tmp_path):
    declaration, _, args, extra = inputs(tmp_path)
    manifest = declaration["train_manifest"]
    payload = {key: value for key, value in manifest.items() if key not in {"file_binding", "content_sha256"}}
    selection = write(tmp_path / "detached-train.json", payload)
    manifest["file_binding"] = selection
    stage_fixture.refresh(declaration)
    args = list(args)
    args[1] = write(tmp_path / "declaration.json", declaration)
    args[2] = write(tmp_path / "expected.json", stage_fixture.pins(declaration))
    with pytest.raises(ValueError):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()
    result = subject.run_alignment_stage(*args, **extra, role_file_selections={"train_manifest": selection})
    assert selection in result["selected_file_bindings"]


def test_resealed_declaration_does_not_replace_independently_selected_expected_values(tmp_path):
    declaration, _, args, extra = inputs(tmp_path)
    declaration["train_manifest"]["rows"][0]["formal_view_sha256"] = "a" * 64
    stage_fixture.refresh(declaration)
    args = list(args)
    args[1] = write(tmp_path / "declaration.json", declaration)
    with pytest.raises(ValueError):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


def test_raw_rank_prohibits_overlap_and_projection_modes(tmp_path):
    case = raw_fixture.case()
    declaration, query, bank, selected = case
    query["rows"][0]["id"] = bank["rows"][0]["id"]
    raw_fixture.sync_bundle(query)
    declaration = raw_fixture.declaration(query, bank)
    selected = {"expected_bindings": raw_fixture.stage_pins(declaration),
                "expected_query_lane": raw_fixture.lane_pins(query), "expected_bank_lane": raw_fixture.lane_pins(bank)}
    _, _, args, extra = inputs(tmp_path, "rank", case=(declaration, query, bank, selected))
    with pytest.raises(ValueError):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


def test_score_rejects_bad_saved_generation_before_opening_reference_declaration(tmp_path, monkeypatch):
    declaration, expected, args, extra = inputs(tmp_path, "score")
    saved = deepcopy(declaration["saved_rankings"])
    saved["query_manifest_sha256"] = "a" * 64
    stage_fixture.seal(saved)
    expected["saved_rankings"] = {"value_sha256": core._digest(saved), "rows_sha256": core._digest(saved["rows"])}
    expected_binding = write(tmp_path / "expected.json", expected)
    saved_binding = write(tmp_path / "durable-saved.json", saved)
    reads = []
    def read(selection):
        reads.append(selection["path"])
        if selection == expected_binding:
            return expected
        if selection == saved_binding:
            return saved
        pytest.fail("reference-bearing declaration was opened before saved integrity passed")
    monkeypatch.setattr(subject, "_read", read)
    request = {"stage": "score", "expected_bindings_binding": expected_binding,
               "saved_rankings_binding": saved_binding, "declaration_binding": args[1],
               "reference_bundle_binding": extra["reference_bundle_binding"], "role_file_selections": {}}
    with pytest.raises(ValueError, match="query manifest"):
        subject._worker_execute(request)
    assert reads == [expected_binding["path"], saved_binding["path"]]


def test_postworker_input_drift_blocks_publication(tmp_path, monkeypatch):
    _, _, args, extra = inputs(tmp_path)
    original = subject._child
    def drifting(*values):
        result = original(*values)
        Path(args[1]["path"]).write_bytes(b"changed after child")
        return result
    monkeypatch.setattr(subject, "_child", drifting)
    with pytest.raises(ValueError):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


def test_child_timeout_is_killed_and_report_is_not_created(tmp_path, monkeypatch):
    _, _, args, extra = inputs(tmp_path)
    class Timeout:
        returncode = None
        killed = False
        pid = 999999
        def communicate(self, *args, **kwargs):
            if not self.killed:
                raise subprocess.TimeoutExpired("trusted-worker", 1)
        def kill(self):
            self.killed = True
    process = Timeout()
    monkeypatch.setattr(subject.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(subject.os, "killpg", lambda *args: process.kill())
    with pytest.raises(ValueError, match="deadline"):
        subject.run_alignment_stage(*args, **extra)
    assert process.killed is True
    assert not args[-1].exists()


@pytest.mark.parametrize("field,value", [("accepted", True), ("similarity_evaluation_count", 999),
                                         ("saved_rankings_sha256", "a" * 64), ("query_bundle_sha256", "a" * 64)])
def test_resealed_helper_scope_or_count_tampering_is_rejected(field, value):
    declaration, query, bank, selected = raw_fixture.case()
    result = raw_fixture.subject.rank_raw_source_bundles(declaration, query, bank, **selected)
    result["diagnostic_receipt"][field] = value
    raw_fixture.seal(result["diagnostic_receipt"])
    validation = core.validate_rank_declaration(declaration, expected_bindings=selected["expected_bindings"])
    with pytest.raises(ValueError):
        subject._check_arithmetic(result, declaration, validation, query, bank)


def test_resealed_saved_generation_cannot_replace_selected_rank_declaration():
    declaration, query, bank, selected = raw_fixture.case()
    result = raw_fixture.subject.rank_raw_source_bundles(declaration, query, bank, **selected)
    saved = result["saved_rankings"]
    changed = deepcopy(declaration)
    changed["queries"]["file_binding"] = {"path": "other.json", "bytes": 1, "sha256": "a" * 64}
    raw_fixture.seal(changed["queries"])
    raw_fixture.seal(changed)
    saved["rank_declaration"] = changed
    saved["query_manifest_sha256"] = core._digest(changed["queries"])
    raw_fixture.seal(saved)
    validation = core.validate_rank_declaration(declaration, expected_bindings=selected["expected_bindings"])
    with pytest.raises(ValueError, match="selected declaration"):
        subject._check_arithmetic(result, declaration, validation, query, bank)


def test_malformed_worker_authority_is_rejected_before_publication(tmp_path, monkeypatch):
    _, _, args, extra = inputs(tmp_path)
    original = subject._child
    def bad(*values):
        result, wall = original(*values)
        result["validation"]["accepted"] = True
        stage_fixture.seal(result["validation"])
        return result, wall
    monkeypatch.setattr(subject, "_child", bad)
    with pytest.raises(ValueError, match="authority"):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


def test_parent_rejects_resealed_raw_diagnostic_authority(tmp_path, monkeypatch):
    _, _, args, extra = inputs(tmp_path, "rank")
    original = subject._child
    def bad(*values):
        result, wall = original(*values)
        result["raw_ranking_diagnostic"]["accepted"] = True
        stage_fixture.seal(result["raw_ranking_diagnostic"])
        return result, wall
    monkeypatch.setattr(subject, "_child", bad)
    with pytest.raises(ValueError, match="authority"):
        subject.run_alignment_stage(*args, **extra)
    assert not args[-1].exists()


def test_oversized_request_rejects_before_subprocess_start(monkeypatch):
    monkeypatch.setattr(subject.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("worker started"))
    with pytest.raises(ValueError, match="bounded worker request"):
        subject._child({"oversized": "x" * 65537}, Path.cwd())


def test_cli_uses_explicit_byte_pins_and_publishes_blocked_fit(tmp_path):
    _, _, args, _ = inputs(tmp_path)
    repository = Path(subject.__file__).resolve().parents[4]
    command = [sys.executable, str(repository / "scripts/ops/autoencoder/run_alignment_stage.py"), "fit",
               "--declaration", args[1]["path"], "--declaration-sha256", args[1]["sha256"], "--declaration-bytes", str(args[1]["bytes"]),
               "--expected-bindings", args[2]["path"], "--expected-bindings-sha256", args[2]["sha256"],
               "--expected-bindings-bytes", str(args[2]["bytes"]), "--output-directory", str(args[-1])]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "blocked_no_contrastive_admission" and report["optimizer_updates"] == 0


def test_cli_help_requires_no_optional_stack_or_package_initializers():
    repository = Path(subject.__file__).resolve().parents[4]
    cli = repository / "scripts/ops/autoencoder/run_alignment_stage.py"
    code = """
import importlib.abc,runpy,sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name.split('.')[0] in {'torch','numpy','spacy','transformers','sentence_transformers'}:
            raise AssertionError('optional stack imported')
sys.meta_path.insert(0,Guard())
sys.argv=[sys.argv[1],'--help']
runpy.run_path(sys.argv[0],run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(cli)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "--declaration-sha256" in result.stdout
