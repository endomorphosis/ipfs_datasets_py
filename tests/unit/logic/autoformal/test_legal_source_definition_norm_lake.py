import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_lake as gate
from ipfs_datasets_py.logic.backends import process
from scripts.ops.legal_ir.check_legal_definition_norm_binding import fixture_request


@pytest.mark.parametrize("failure", [None, "missing_nonfirst", "empty_module", "wrong_target", "truncated",
    "no_process", "binary_changed", "error_exit", "sorry_warning"])
def test_native_receipt_requires_complete_actual_pinned_execution(monkeypatch, tmp_path, failure):
    executable = tmp_path / "lake"; executable.write_bytes(b"unit-test-stub-not-real-compiler")
    digest = gate.shared._sha(executable.read_bytes())
    monkeypatch.setattr(gate.shared, "_installed_toolchain", lambda *_: (executable, {str(executable): digest}, {}))
    def run(self, request):
        assert request.argv[-2:] == ("build", "legal")
        outputs = {name: b"explicitly-stubbed-artifact" for name in request.output_paths}
        if failure == "missing_nonfirst": outputs.pop(request.output_paths[-2])
        if failure == "empty_module": outputs[request.output_paths[-2]] = b""
        if failure == "binary_changed": executable.write_bytes(b"different")
        return process.ToolRunResult(interface_version="test", runtime=process.ToolRuntime.NATIVE,
            command=(*request.argv[:-1], "Legal") if failure == "wrong_target" else request.argv,
            returncode=1 if failure == "error_exit" else 0, stdout="warning: sorryAx" if failure == "sorry_warning" else "",
            stderr="", elapsed_seconds=.01, pid=None if failure == "no_process" else 123,
            output_files=outputs, output_truncated=failure == "truncated")
    monkeypatch.setattr(process.BoundedToolRunner, "run", run)
    result = gate.build([fixture_request("O", f) for f in gate.bridge.FAMILIES],
        toolchain="leanprover/lean4:v4.34.1", lake_executable=str(executable), output_directory=tmp_path / "result")
    assert result["build_passed"] is (failure is None)
    assert result["source_semantics_verified"] is result["source_authenticity_verified"] is False
    assert len(result["expected_modules"]) == 4
