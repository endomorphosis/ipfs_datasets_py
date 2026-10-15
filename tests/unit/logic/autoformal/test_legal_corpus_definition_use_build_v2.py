"""Authored runner receipts exercise V2 engineering builds, never a compiler."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def fixture_module(filename, name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PREP = fixture_module(
    "test_legal_corpus_definition_use_lake_v2.py", "v2_preparation_for_authored_build"
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_build_v2

    return legal_corpus_definition_use_build_v2


def prepared_case(family="fol"):
    from ipfs_datasets_py.logic.autoformal import (
        legal_corpus_definition_use_lake_v2 as preparation,
    )

    data = _PREP.assessment_data(family)
    return {"data": data, "preparation": _PREP.prepare(preparation, data)}


@pytest.fixture(scope="module")
def base():
    return prepared_case()


@pytest.fixture
def case(base):
    return deepcopy(base)


def binary_fixture(tmp_path):
    directory = tmp_path / "authored-toolchain" / "bin"
    directory.mkdir(parents=True)
    files = {name: directory / name for name in ("lake", "lean")}
    for name, path in files.items():
        path.write_bytes(
            b"\x7fELF-AUTHORED-UNIT-TEST-STUB-NOT-A-COMPILER:" + name.encode()
        )
        path.chmod(0o700)
    return files, {str(path): sha(path.read_bytes()) for path in files.values()}


def install_runner(
    owner,
    monkeypatch,
    tmp_path,
    case,
    failure=None,
    *,
    runtime=process.ToolRuntime.NATIVE,
):
    helper, runner, _ = owner._owners()
    files, pins = binary_fixture(tmp_path)
    manifest = case["preparation"].to_dict()
    captured = {"probe_calls": [], "run_calls": [], "files": files, "pins": pins}

    def fake_probe(executable, toolchain):
        captured["probe_calls"].append((executable, toolchain))
        assert Path(executable) == files["lake"]
        assert toolchain == _PREP.TOOLCHAIN
        probes = {
            name: {
                "command": [str(path), "--version"],
                "stdout": "Lean (version 4.34.1, authored synthetic version observation)",
                "stderr": "",
                "returncode": 0,
            }
            for name, path in files.items()
        }
        if failure == "probe_version":
            probes["lean"]["stdout"] = "Lean (version 4.1.0, foreign version)"
        elif failure == "probe_command":
            probes["lake"]["command"] = [str(files["lean"]), "--version"]
        elif failure == "probe_review_change":
            observations = case["data"]["review_inputs"]["observed_artifact_sha256s"]
            observations[next(iter(observations))] = "0" * 64
        return files["lake"], dict(pins), probes

    def fake_run(self, request, **kwargs):
        captured["run_calls"].append((request, kwargs))
        assert request.argv == (
            str(files["lake"]),
            "--offline",
            "--no-cache",
            "build",
            "legal",
        )
        assert request.input_files == dict(case["preparation"].files)
        assert request.environment == {
            "ELAN_TOOLCHAIN": _PREP.TOOLCHAIN,
            "LEAN_NUM_THREADS": "1",
        }
        assert request.output_paths == tuple(
            ".lake/build/lib/lean/" + module.replace(".", "/") + ".olean"
            for module in manifest["expected_modules"]
        )
        assert 0 < request.limits.timeout_seconds <= 60
        assert 0 < request.limits.cpu_seconds <= 60
        assert request.limits.resident_memory_bytes == 2 * 1024**3
        assert request.limits.max_output_bytes == 262144
        assert request.limits.max_workspace_bytes == 128 * 1024**2
        assert request.limits.max_output_files == 6
        outputs = {
            path: b"AUTHORED-FAKE-OLEAN-NOT-COMPILER-OUTPUT:" + path.encode()
            for path in request.output_paths
        }
        theorems = manifest["conditional_theorems"]
        lines = [
            "'" + theorem + "' does not depend on any axioms" for theorem in theorems
        ]
        if runtime is process.ToolRuntime.KERNEL:
            lines = [
                "info: "
                + theorem.rsplit(".", 1)[0].replace(".", "/")
                + ".lean:42:0: "
                + line
                for theorem, line in zip(theorems, lines, strict=True)
            ]
        result = {
            "interface_version": process.BOUNDED_TOOL_RUNNER_VERSION,
            "runtime": runtime,
            "command": request.argv,
            "returncode": 0,
            "stdout": "\n".join(lines),
            "stderr": "",
            "elapsed_seconds": 0.01,
            "pid": 12345,
            "output_files": outputs,
            "workspace_cleaned": True,
            "process_tree_terminated": False,
            "termination_reason": "completed",
        }
        if failure == "missing_output":
            outputs.pop(request.output_paths[-3])
        elif failure == "empty_output":
            outputs[request.output_paths[-2]] = b""
        elif failure == "missing_axiom":
            result["stdout"] = "\n".join(lines[:-1])
        elif failure == "duplicate_axiom":
            result["stdout"] += "\n" + lines[0]
        elif failure == "nonempty_axiom":
            result["stdout"] = "\n".join(
                lines[:-1]
                + ["'" + theorems[-1] + "' depends on axioms: [Classical.choice]"]
            )
        elif failure == "unknown_axiom":
            result["stdout"] += "\n'Foreign.injected' does not depend on any axioms"
        elif failure == "contradictory_axiom":
            result["stdout"] += "\n'" + theorems[0] + "' depends on axioms: [sorryAx]"
        elif failure == "sorry":
            result["stderr"] = "warning: declaration uses sorryAx"
        elif failure == "wrong_target":
            result["command"] = (*request.argv[:-1], "Legal")
        elif failure == "wrong_runtime":
            result["runtime"] = process.ToolRuntime.WASM
        elif failure == "unsupported_interface":
            result["interface_version"] = "unsupported-fixture-runner/v0"
        elif failure == "contradictory_termination":
            result["termination_reason"] = "timeout"
        elif failure == "no_pid":
            result["pid"] = None
        elif failure == "error_exit":
            result["returncode"] = 1
        elif failure in {
            "timed_out",
            "cancelled",
            "unavailable",
            "resource_exhausted",
            "output_truncated",
            "workspace_limit_exceeded",
        }:
            result[failure] = True
        elif failure == "unclean":
            result["workspace_cleaned"] = False
        elif failure == "execution_error":
            result["error"] = "authored runner diagnostic despite exit zero"
        elif failure == "truncated_unicode_capture":
            result["stdout"] = "x" * 262143 + "\ufffd"
            result["output_truncated"] = True
        elif failure == "changed_lake":
            files["lake"].write_bytes(b"\x7fELF-changed-lake-after-probe")
        elif failure == "changed_lean":
            files["lean"].write_bytes(b"\x7fELF-changed-lean-after-probe")
        elif failure == "deleted_binary":
            files["lean"].unlink()
        elif failure == "postrun_review_change":
            observations = case["data"]["review_inputs"]["observed_artifact_sha256s"]
            observations[next(iter(observations))] = "0" * 64
        elif failure == "unexpected_output":
            outputs[".lake/build/lib/lean/Foreign.olean"] = b"unexpected"
        elif failure == "unsafe_output":
            outputs["../../outside.olean"] = b"unsafe"
        elif failure == "oversized_artifact":
            outputs[request.output_paths[0]] = b"x" * 262145
        elif failure == "oversized_stream":
            result["stdout"] = "x" * 262145
        elif failure == "nonbyte_artifact":
            outputs[request.output_paths[0]] = "not ordinary bytes"
        captured["outputs"] = deepcopy(outputs)
        captured["result"] = dict(result)
        return process.ToolRunResult(**result)

    monkeypatch.setattr(helper, "_installed_toolchain", fake_probe)
    monkeypatch.setattr(runner.BoundedToolRunner, "run", fake_run)
    return captured


def build(owner, case, captured, directory, **overrides):
    kwargs = {
        **_PREP.arguments(case["data"]),
        "lake_executable": str(captured["files"]["lake"]),
        "expected_binary_sha256": captured["pins"],
        "output_directory": directory,
    }
    kwargs.update(overrides)
    return owner.build_definition_use_corpus_v2(case["preparation"], **kwargs)


def load(owner, case, captured, directory, expected_receipt_sha256=None):
    expected = expected_receipt_sha256 or sha(
        (directory / "build-receipt.json").read_bytes()
    )
    return owner.load_definition_use_build_v2(
        directory,
        case["preparation"],
        expected_receipt_sha256=expected,
        expected_binary_sha256=captured["pins"],
        **_PREP.arguments(case["data"]),
    )


def assert_false_authority(owner, receipt):
    for key in owner.FALSE_FLAGS:
        assert receipt[key] is False
    assert receipt["accepted_view_eligible"] is False
    assert receipt["source_semantics_verified"] is False
    assert receipt["human_identity_verified"] is False
    assert receipt["training_qualified"] is False


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_complete_engineering_build_replays_exact_sources_and_all_modules_without_legal_admission(
    owner, monkeypatch, tmp_path, family
):
    case = prepared_case(family)
    original = deepcopy(case["preparation"])
    captured = install_runner(
        owner,
        monkeypatch,
        tmp_path,
        case,
        runtime=(
            process.ToolRuntime.KERNEL
            if family == "tdfol"
            else process.ToolRuntime.NATIVE
        ),
    )
    directory = tmp_path / "build"
    receipt = build(owner, case, captured, directory)
    manifest = case["preparation"].to_dict()
    assert receipt["build_passed"] is True
    assert receipt["lean_compilation_verified"] is True
    assert receipt["conditional_proofs_verified"] is True
    assert receipt["kernel_proofs_checked"] is True
    assert receipt["backend_executed"] is True
    assert receipt["expected_modules"] == manifest["expected_modules"]
    assert receipt["binary_sha256"] == captured["pins"]
    assert receipt["theorem_axiom_dependencies"] == {
        theorem: [] for theorem in manifest["conditional_theorems"]
    }
    assert receipt["artifact_sha256"] == {
        name: sha(raw) for name, raw in captured["outputs"].items()
    }
    assert case["preparation"] == original
    assert original.to_dict()["build_eligible"] is False
    assert_false_authority(owner, receipt)
    assert len(captured["probe_calls"]) == len(captured["run_calls"]) == 1
    assert load(owner, case, captured, directory) == receipt
    for name, body in original.files:
        assert (directory / "project" / name).read_bytes() == body.encode()
    assert (
        directory / "project" / "corpus-manifest.json"
    ).read_bytes() == original.manifest_json.encode()
    for path, raw in captured["outputs"].items():
        assert (directory / receipt["artifact_files"][path]).read_bytes() == raw
    assert (directory / "build-receipt.json").read_bytes() == canonical_dag_json_bytes(
        receipt
    )


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_valid_pending_or_rejected_reviews_do_not_become_legal_build_admission(
    owner, monkeypatch, tmp_path, case, status
):
    from ipfs_datasets_py.logic.autoformal import (
        legal_corpus_definition_use_lake_v2 as preparation,
    )

    signed = case["data"]["signed"]
    if status == "pending":
        signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
        signed["registry"]["keys"] = []
        signed["reviews"] = []
        _PREP._COMBINED._REVIEW.refresh(signed)
    else:
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned change"
    case["data"] = _PREP.refresh_assessment(signed)
    case["preparation"] = _PREP.prepare(preparation, case["data"])
    original = deepcopy(case["preparation"])
    captured = install_runner(owner, monkeypatch, tmp_path, case)
    receipt = build(owner, case, captured, tmp_path / "build")
    assert receipt["build_passed"] is True
    assert (
        receipt["review_evidence_status"]
        == case["data"]["assessment"]["evidence_assessment_status"]
    )
    assert receipt["review_blockers"] == case["data"]["assessment"]["blockers"]
    assert receipt["review_prerequisites_satisfied_under_selected_trust"] is False
    assert receipt["admission_build_eligible"] is False
    assert receipt["toolchain_library_closure_verified"] is False
    assert case["preparation"] == original
    assert original.to_dict()["build_eligible"] is False
    assert_false_authority(owner, receipt)


@pytest.mark.parametrize(
    "failure", ["probe_version", "probe_command", "probe_review_change"]
)
def test_version_probe_observations_and_intake_are_revalidated_before_build(
    owner, monkeypatch, tmp_path, case, failure
):
    captured = install_runner(owner, monkeypatch, tmp_path, case, failure)
    directory = tmp_path / "build"
    with pytest.raises(ValueError):
        build(owner, case, captured, directory)
    assert len(captured["probe_calls"]) == 1
    assert captured["run_calls"] == []
    assert not directory.exists()


@pytest.mark.parametrize(
    "failure",
    [
        "missing_output",
        "empty_output",
        "missing_axiom",
        "duplicate_axiom",
        "nonempty_axiom",
        "unknown_axiom",
        "contradictory_axiom",
        "sorry",
        "wrong_target",
        "wrong_runtime",
        "unsupported_interface",
        "contradictory_termination",
        "no_pid",
        "error_exit",
        "timed_out",
        "cancelled",
        "unavailable",
        "resource_exhausted",
        "output_truncated",
        "workspace_limit_exceeded",
        "unclean",
        "execution_error",
        "truncated_unicode_capture",
        "changed_lake",
        "changed_lean",
        "deleted_binary",
        "postrun_review_change",
    ],
)
def test_incomplete_or_unqualified_execution_preserves_failed_receipt_and_frozen_project(
    owner, monkeypatch, tmp_path, case, failure
):
    replay_case = deepcopy(case)
    captured = install_runner(owner, monkeypatch, tmp_path, case, failure)
    directory = tmp_path / "build"
    receipt = build(owner, case, captured, directory)
    assert receipt["build_passed"] is False
    assert receipt["lean_compilation_verified"] is False
    assert receipt["conditional_proofs_verified"] is False
    assert receipt["kernel_proofs_checked"] is False
    assert_false_authority(owner, receipt)
    assert (directory / "project" / "corpus-manifest.json").read_bytes() == replay_case[
        "preparation"
    ].manifest_json.encode()
    assert load(owner, replay_case, captured, directory) == receipt


@pytest.mark.parametrize(
    "failure",
    [
        "unexpected_output",
        "unsafe_output",
        "oversized_artifact",
        "oversized_stream",
        "nonbyte_artifact",
    ],
)
def test_malformed_runner_results_refuse_without_persisting_output_bundle(
    owner, monkeypatch, tmp_path, case, failure
):
    captured = install_runner(owner, monkeypatch, tmp_path, case, failure)
    directory = tmp_path / "build"
    with pytest.raises((ValueError, TypeError)):
        build(owner, case, captured, directory)
    assert not directory.exists()
    assert not (tmp_path.parent / "outside.olean").exists()


@pytest.mark.parametrize(
    "damage",
    [
        "assessment",
        "source",
        "preparation_file",
        "preparation_authority",
        "binary_pin",
        "relative_binary",
    ],
)
def test_intake_and_independent_binary_pins_refuse_before_any_probe_or_runner(
    owner, monkeypatch, tmp_path, case, damage
):
    captured = install_runner(owner, monkeypatch, tmp_path, case)
    overrides = {}
    if damage == "assessment":
        case["data"]["expected_assessment_file_sha256"] = "0" * 64
    elif damage == "source":
        evidence = case["data"]["review_inputs"]["use_inputs"]["donor_evidence_inputs"]
        evidence["candidate_inputs"]["raw_html"] += b" changed source"
    elif damage == "preparation_file":
        files = dict(case["preparation"].files)
        files["LegalCorpusV2.lean"] += "\n-- changed source\n"
        case["preparation"] = replace(
            case["preparation"], files=tuple(sorted(files.items()))
        )
    elif damage == "preparation_authority":
        manifest = case["preparation"].to_dict()
        manifest["build_eligible"] = True
        case["preparation"] = _PREP.modified_manifest(case["preparation"], manifest)
    elif damage == "binary_pin":
        captured["pins"][str(captured["files"]["lean"])] = "0" * 64
    else:
        overrides["lake_executable"] = "relative/lake"
    with pytest.raises((ValueError, OSError)):
        build(owner, case, captured, tmp_path / "build", **overrides)
    assert captured["probe_calls"] == captured["run_calls"] == []
    assert not (tmp_path / "build").exists()


@pytest.mark.parametrize("timeout", [True, float("nan"), 61])
def test_invalid_execution_timeouts_refuse_before_toolchain_access(
    owner, monkeypatch, tmp_path, case, timeout
):
    captured = install_runner(owner, monkeypatch, tmp_path, case)
    with pytest.raises(ValueError):
        build(owner, case, captured, tmp_path / "build", timeout_seconds=timeout)
    assert captured["probe_calls"] == captured["run_calls"] == []


def test_pre_cancelled_build_refuses_before_any_toolchain_probe_or_build_runner(
    owner, monkeypatch, tmp_path, case
):
    captured = install_runner(owner, monkeypatch, tmp_path, case)
    cancellation = process.CancellationToken()
    cancellation.cancel()
    directory = tmp_path / "build"
    with pytest.raises(ValueError):
        build(owner, case, captured, directory, cancellation=cancellation)
    assert captured["probe_calls"] == captured["run_calls"] == []
    assert not directory.exists()


def test_saved_build_loader_never_reprobes_or_requires_live_binaries(
    owner, monkeypatch, tmp_path, case
):
    captured = install_runner(owner, monkeypatch, tmp_path, case)
    directory = tmp_path / "build"
    receipt = build(owner, case, captured, directory)
    for path in captured["files"].values():
        path.unlink()
    helper, runner, _ = owner._owners()

    def forbidden(*args, **kwargs):
        raise AssertionError("historical load cannot execute or probe a live toolchain")

    monkeypatch.setattr(helper, "_installed_toolchain", forbidden)
    monkeypatch.setattr(runner.BoundedToolRunner, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert load(owner, case, captured, directory) == receipt


@pytest.mark.parametrize(
    "damage", ["compiled", "project", "missing", "extra", "symlink", "authority"]
)
def test_loader_refuses_changed_closed_bundle_or_resealed_legal_authority(
    owner, monkeypatch, tmp_path, case, damage
):
    captured = install_runner(owner, monkeypatch, tmp_path, case)
    directory = tmp_path / "build"
    receipt = build(owner, case, captured, directory)
    expected = sha((directory / "build-receipt.json").read_bytes())
    compiled = directory / next(iter(receipt["artifact_files"].values()))
    if damage == "compiled":
        compiled.write_bytes(b"changed compiled artifact")
    elif damage == "project":
        (directory / "project" / "LegalCorpusV2.lean").write_text("-- changed source\n")
    elif damage == "missing":
        compiled.unlink()
    elif damage == "extra":
        (directory / "extra.bin").write_bytes(b"foreign")
    elif damage == "symlink":
        outside = tmp_path / "external.olean"
        outside.write_bytes(compiled.read_bytes())
        compiled.unlink()
        compiled.symlink_to(outside)
    else:
        receipt["accepted_view_eligible"] = True
        receipt = contracts.seal_record(
            {
                key: value
                for key, value in receipt.items()
                if key not in {"record_cid", "cid_scope"}
            }
        )
        (directory / "build-receipt.json").write_bytes(
            canonical_dag_json_bytes(receipt)
        )
        expected = sha((directory / "build-receipt.json").read_bytes())
    with pytest.raises((ValueError, OSError)):
        load(owner, case, captured, directory, expected)


def test_loader_recomputes_saved_failure_instead_of_trusting_promoted_engineering_flags(
    owner, monkeypatch, tmp_path, case
):
    captured = install_runner(owner, monkeypatch, tmp_path, case, "missing_axiom")
    directory = tmp_path / "build"
    receipt = build(owner, case, captured, directory)
    for key in (
        "build_passed",
        "lean_compilation_verified",
        "conditional_proofs_verified",
        "kernel_proofs_checked",
    ):
        receipt[key] = True
    receipt = contracts.seal_record(
        {
            key: value
            for key, value in receipt.items()
            if key not in {"record_cid", "cid_scope"}
        }
    )
    raw = canonical_dag_json_bytes(receipt)
    (directory / "build-receipt.json").write_bytes(raw)
    with pytest.raises(ValueError):
        load(owner, case, captured, directory, sha(raw))


def test_build_loader_requires_external_receipt_pin_and_fresh_output_directory(
    owner, monkeypatch, tmp_path, case
):
    captured = install_runner(owner, monkeypatch, tmp_path, case)
    directory = tmp_path / "build"
    build(owner, case, captured, directory)
    with pytest.raises(ValueError):
        load(owner, case, captured, directory, "0" * 64)
    before = (directory / "build-receipt.json").read_bytes()
    with pytest.raises((ValueError, OSError)):
        build(owner, case, captured, directory)
    assert (directory / "build-receipt.json").read_bytes() == before
    assert len(captured["probe_calls"]) == len(captured["run_calls"]) == 1


def test_public_build_import_loads_no_execution_or_model_owners(tmp_path):
    script = """
import subprocess,sys
def forbidden(*args,**kwargs): raise AssertionError('process executed at public import')
subprocess.Popen=forbidden
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_build_v2 as module
for name in ('legal_pilot_lake','legal_graph_review','legal_family_routes','legal_corpus_lake'):
    assert 'ipfs_datasets_py.logic.autoformal.'+name not in sys.modules,name
assert not any(name in sys.modules for name in ('torch','transformers','tensorflow'))
assert callable(module.build_definition_use_corpus_v2)
"""
    env = dict(
        os.environ, PYTHONDONTWRITEBYTECODE="1", IPFS_DATASETS_PY_MINIMAL_IMPORTS="1"
    )
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[4])
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())
