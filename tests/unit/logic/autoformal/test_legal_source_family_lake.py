"""Independent request-regeneration and native receipt contracts."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_family_lake as gate
from ipfs_datasets_py.logic.backends import process

TOOLCHAIN = "leanprover/lean4:v4.34.1"


def request(family="deontic_fol", *, identity="audit", qualifiers=False):
    source = "agency must file record" + (" if registered unless exempt" if qualifiers else "") + "."
    rule = {"modality": "O", "actor": "agency", "action": "file", "object": "record",
            "conditions": ["if registered"] if qualifiers else [],
            "exceptions": ["unless exempt"] if qualifiers else [], "temporal": []}
    candidate = {"candidate_id": identity, "source_text": source,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "canonical_ir": {"rules": [rule]}}
    interpretation = bridge.interpretation_skeleton(candidate)
    interpretation.update(activation_scope="all_conditions_at_evaluation_time",
        exception_scope="any_exception_waives_at_evaluation_time")
    if qualifiers:
        for kind, name in (("conditions", "Registered"), ("exceptions", "Exempt")):
            interpretation["rules"][0][kind][0]["expression"] = {
                "op": "atom", "predicate": {"name": name, "arguments": ["agency"]}}
    def span(text, value=None):
        start = source.index(text)
        return {"start_char": start, "end_char": start + len(text),
                "source_text": text, "canonical_value": text if value is None else value}
    occurrence = {"occurrence_id": "occ-0", "rule_index": 0,
        "start_char": 0, "end_char": len(source), "source_text": source,
        "facets": {"modality": span("must", "O"), "actor": span("agency"), "action": span("file"),
            "object": span("record"), "conditions": [span(x) for x in rule["conditions"]],
            "exceptions": [span(x) for x in rule["exceptions"]], "temporal": []}}
    return {"candidate": candidate, "interpretation": interpretation,
            "occurrence_bindings": [occurrence], "family": family}


def test_same_candidate_can_be_checked_in_each_declared_family():
    requests = [request(family) for family in ("deontic_fol", "tdfol", "dcec")]
    prepared = gate.prepare_source_family_legal(requests, toolchain=TOOLCHAIN)
    assert prepared == gate.prepare_source_family_legal(requests, toolchain=TOOLCHAIN)
    gate.validate_preparation(prepared)
    manifest = prepared.to_dict()
    assert manifest["all_candidates_supported"], manifest["candidates"]
    assert [r["family"] for r in manifest["candidates"]] == [r["family"] for r in requests]
    assert dict(prepared.files)["LegalSourceFamily.lean"].splitlines() == [
        "import LegalSourceFamily.Candidate0000", "import LegalSourceFamily.Candidate0001",
        "import LegalSourceFamily.Candidate0002"]
    assert all(manifest[k] is False for k in ("admitted", "formalized", "proof_authority",
        "source_semantics_verified", "cross_family_equivalence_verified", "all_logic_families_supported"))


@pytest.mark.parametrize("replacement", [
    "def formula_0 : Prop := True\n",
    "theorem formula_0 : True := by exact (sorry)\n",
    "theorem formula_0 : False := by exact (sorryAx False true)\n",
    "axiom formula_0 : False\n",
    "def formula_0 : Prop := False\n",
])
def test_changed_generated_source_cannot_pass_with_recomputed_hashes(replacement):
    prepared = gate.prepare_source_family_legal([request()], toolchain=TOOLCHAIN)
    files = dict(prepared.files)
    filename = "LegalSourceFamily/Candidate0000.lean"
    files[filename] = "import LegalSourceFamily.Prelude\n" + replacement
    manifest = prepared.to_dict()
    manifest["file_sha256"][filename] = gate._sha(files[filename])
    manifest["candidates"][0]["lean_sha256"] = gate._sha(files[filename])
    forged = replace(prepared, files=tuple(sorted(files.items())), manifest_json=gate._json(manifest))
    with pytest.raises(ValueError, match="emitted source or import coverage changed"):
        gate.validate_preparation(forged)


def test_omitted_nonfirst_module_cannot_pass_with_recomputed_manifest():
    prepared = gate.prepare_source_family_legal([request(), request(identity="second")], toolchain=TOOLCHAIN)
    files = dict(prepared.files)
    files["LegalSourceFamily.lean"] = "import LegalSourceFamily.Candidate0000\n"
    manifest = prepared.to_dict()
    manifest["file_sha256"]["LegalSourceFamily.lean"] = gate._sha(files["LegalSourceFamily.lean"])
    with pytest.raises(ValueError, match="coverage changed"):
        gate.validate_preparation(replace(prepared, files=tuple(sorted(files.items())),
            manifest_json=gate._json(manifest)))


@pytest.mark.parametrize("mutation", ["duplicate", "extra_lean", "source_hash", "extra_candidate", "family_type"])
def test_untrusted_request_contract_rejects_before_backend(mutation):
    requests = [request()]
    if mutation == "duplicate": requests.append(deepcopy(requests[0]))
    if mutation == "extra_lean": requests[0]["lean_body"] = "def fake : Prop := True"
    if mutation == "source_hash": requests[0]["candidate"]["source_sha256"] = "0" * 64
    if mutation == "extra_candidate": requests[0]["candidate"]["training_qualified"] = True
    if mutation == "family_type": requests[0]["family"] = []
    with pytest.raises(ValueError):
        gate.build_source_family_legal(requests, toolchain=TOOLCHAIN, lake_executable="not-invoked")


def test_one_unsupported_entry_blocks_entire_project(tmp_path):
    receipt = gate.build_source_family_legal([request(), request("fol")], toolchain=TOOLCHAIN,
        lake_executable="not-invoked", output_directory=tmp_path / "blocked").to_dict()
    assert receipt["status"] == "blocked"
    assert [r["status"] for r in receipt["candidates"]] == ["supported", "unsupported"]
    assert receipt["backend_executed"] is receipt["build_passed"] is False
    assert not (tmp_path / "blocked" / "lakefile.toml").exists()


def fake_backend(monkeypatch, tmp_path, failure=None):
    executable = tmp_path / "lake"
    executable.write_bytes(b"independently stubbed test binary")
    pin = gate._sha(executable.read_bytes())
    monkeypatch.setattr(gate.shared, "_installed_toolchain", lambda *_: (executable, {str(executable): pin}, {}))
    def run(self, req):
        assert req.argv[-2:] == ("build", "legal")
        outputs = {path: b"test-compiled-module" for path in req.output_paths}
        if failure == "missing": outputs.pop(req.output_paths[-2])
        if failure == "empty": outputs[req.output_paths[-2]] = b""
        if failure == "extra": outputs["unexpected.olean"] = b"unexpected"
        if failure == "binary_changed": executable.write_bytes(b"changed")
        return process.ToolRunResult(interface_version="test", runtime=process.ToolRuntime.NATIVE,
            command=req.argv if failure != "wrong_command" else ("lake", "build", "Legal"),
            returncode=1 if failure == "failure" else 0,
            stdout="warning: declaration uses sorry" if failure == "sorry" else "Built legal",
            stderr="", elapsed_seconds=0.01, output_files=outputs,
            pid=None if failure == "no_process" else 123,
            output_truncated=failure == "truncated", timed_out=failure == "timeout")
    monkeypatch.setattr(process.BoundedToolRunner, "run", run)


@pytest.mark.parametrize("failure", ["missing", "empty", "extra", "binary_changed", "wrong_command",
    "failure", "sorry", "no_process", "truncated", "timeout"])
def test_execution_receipt_requires_full_real_process_contract(monkeypatch, tmp_path, failure):
    fake_backend(monkeypatch, tmp_path, failure)
    receipt = gate.build_source_family_legal([request()], toolchain=TOOLCHAIN,
        lake_executable="stubbed-only-in-test").to_dict()
    assert receipt["status"] == "failed"
    assert receipt["build_passed"] is False


def test_persisted_receipt_binds_exact_original_requests(monkeypatch, tmp_path):
    fake_backend(monkeypatch, tmp_path)
    output = tmp_path / "project"
    requests = [request(qualifiers=True)]
    frozen = gate.build_source_family_legal(requests, toolchain=TOOLCHAIN,
        lake_executable="stubbed-only-in-test", output_directory=output)
    receipt = frozen.to_dict()
    assert receipt["build_passed"]
    assert json.loads((output / "source-family-inputs.json").read_text()) == requests
    assert json.loads((output / "source-family-receipt.json").read_text()) == receipt
    digest = receipt.pop("receipt_sha256")
    assert gate._sha(gate._json(receipt)) == digest
    receipt["admitted"] = True
    assert frozen.to_dict()["admitted"] is False
    with pytest.raises(ValueError, match="fresh output_directory"):
        gate.build_source_family_legal(requests, toolchain=TOOLCHAIN,
            lake_executable="stubbed-only-in-test", output_directory=output)


@pytest.mark.parametrize("budget", [True, 0, 61, float("nan"), float("inf")])
def test_invalid_execution_budgets_fail_closed(budget):
    with pytest.raises(ValueError, match="timeout_seconds"):
        gate.build_source_family_legal([request()], toolchain=TOOLCHAIN,
            lake_executable="not-invoked", timeout_seconds=budget)


@pytest.mark.skipif(not os.environ.get("LEGAL_SOURCE_FAMILY_NATIVE_LAKE"), reason="explicit native pilot only")
def test_native_lowercase_target_builds_all_three_families_and_qualified_rule(tmp_path):
    executable = os.environ["LEGAL_SOURCE_FAMILY_NATIVE_LAKE"]
    requests = [request(family) for family in ("deontic_fol", "tdfol", "dcec")]
    requests.append(request("tdfol", identity="qualified", qualifiers=True))
    receipt = gate.build_source_family_legal(requests, toolchain=TOOLCHAIN,
        lake_executable=executable, output_directory=tmp_path / "native").to_dict()
    assert receipt["build_passed"], receipt.get("stdout", "") + receipt.get("stderr", "")
    assert receipt["backend_executed"] and receipt["binary_pins_match"]
    assert len(receipt["expected_modules"]) == len(receipt["compiled_modules"]) == 6
    assert receipt["command"][-2:] == ["build", "legal"]
    assert receipt["source_semantics_verified"] is False


@pytest.mark.skipif(not os.environ.get("LEGAL_SOURCE_FAMILY_NATIVE_LAKE"), reason="explicit native pilot only")
def test_native_lowercase_target_reaches_invalid_nonfirst_candidate():
    executable = os.environ["LEGAL_SOURCE_FAMILY_NATIVE_LAKE"]
    prepared = gate.prepare_source_family_legal([request(), request("tdfol")], toolchain=TOOLCHAIN)
    files = dict(prepared.files)
    files["LegalSourceFamily/Candidate0001.lean"] += "\ndef invalid_candidate : Nat := True\n"
    result = process.BoundedToolRunner().run(process.ToolRunRequest(
        argv=(executable, "build", "legal"), input_files=files,
        environment={"ELAN_TOOLCHAIN": TOOLCHAIN, "LEAN_NUM_THREADS": "2"},
        limits=process.ToolRunLimits(timeout_seconds=60, cpu_seconds=60,
            max_workspace_bytes=128 * 1024**2)))
    assert result.pid is not None and result.returncode != 0
    assert "Candidate0001" in result.stdout + result.stderr
