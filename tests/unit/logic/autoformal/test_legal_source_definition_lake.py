from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_definition_lake as gate
from ipfs_datasets_py.logic.backends import process
from tests.unit.logic.autoformal.test_legal_source_definition_bridge import request


@pytest.mark.parametrize("failure", [None, "missing_nonfirst", "empty_module", "wrong_target", "truncated", "no_process", "binary_changed"])
def test_build_receipt_requires_actual_complete_pinned_execution(monkeypatch, tmp_path, failure):
    executable = tmp_path / "lake"
    executable.write_bytes(b"explicitly-stubbed-unit-test-binary")
    expected = gate.shared._sha(executable.read_bytes())
    monkeypatch.setattr(gate.shared, "_installed_toolchain", lambda *_: (executable, {str(executable): expected}, {}))
    def run(self, req):
        assert req.argv[-2:] == ("build", "legal")
        outputs = {name: b"stubbed-compiled-output" for name in req.output_paths}
        if failure == "missing_nonfirst": outputs.pop(req.output_paths[-2])
        if failure == "empty_module": outputs[req.output_paths[-2]] = b""
        if failure == "binary_changed": executable.write_bytes(b"changed binary")
        return process.ToolRunResult(interface_version="test", runtime=process.ToolRuntime.NATIVE,
            command=(*req.argv[:-1], "Legal") if failure == "wrong_target" else req.argv,
            returncode=0, stdout="", stderr="", elapsed_seconds=.01, pid=None if failure == "no_process" else 123,
            output_files=outputs, output_truncated=failure == "truncated")
    monkeypatch.setattr(process.BoundedToolRunner, "run", run)
    result = gate.build([request("fol"), request("tdfol")], toolchain="leanprover/lean4:v4.34.1",
                        lake_executable=str(executable), output_directory=tmp_path / "result")
    assert result["build_passed"] is (failure is None)
    assert result["source_semantics_verified"] is False
