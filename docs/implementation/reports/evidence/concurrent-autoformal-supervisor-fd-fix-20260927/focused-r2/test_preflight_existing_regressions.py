from pathlib import Path
import os,sys,subprocess,json,zipfile,zipimport
import pytest
from ipfs_accelerate_py.agent_supervisor.validation import project_dependency_preflight as preflight_module
from ipfs_accelerate_py.agent_supervisor.validation.project_dependency_preflight import _run_bounded_probe_process
REPO_ROOT=Path(__file__).resolve().parent.parent/'test-source'

def test_dependency_probe_output_is_bounded_while_child_is_running(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        preflight_module,
        "MAX_PROBE_OUTPUT_BYTES",
        128,
    )

    returncode, output, error = _run_bounded_probe_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 100000); sys.stdout.flush()",
        ],
        input_payload=b"",
        environment=os.environ,
    )

    assert returncode is not None
    assert len(output) <= 128
    assert error["reason"] == "dependency_probe_output_exceeded_bound"



def test_dependency_probe_uses_inherited_sealed_fd_when_parent_is_non_dumpable() -> None:
    script = """
import json
import os

os.environ["IPFS_ACCELERATE_AGENT_QUACK_TOKEN"] = "regression-fixture"

from ipfs_accelerate_py.agent_supervisor.runtime.process_security import (
    harden_state_authority_process,
)
from ipfs_accelerate_py.agent_supervisor.validation.project_dependency_preflight import (
    _run_dependency_probe,
)

assert harden_state_authority_process() is True
result = _run_dependency_probe({"projects": []})
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if result.get("passed") else 1)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["passed"] is True
    assert result["reason"] == "project_dependencies_satisfied"
    assert result["python_executable"]
    assert result["validation_python_launcher"]["sealed"] is True



@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "memfd_create"),
    reason="the LGCVF capsule regression requires Linux memfd support",
)
def test_dependency_probe_reads_source_from_sealed_memfd_zip(monkeypatch) -> None:
    import fcntl

    source = Path(preflight_module.__file__).read_bytes()
    member = (
        "ipfs_accelerate_py/agent_supervisor/validation/"
        "project_dependency_preflight.py"
    )
    capsule_fd = os.memfd_create(
        "dependency-preflight-capsule",
        os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
    )
    try:
        capsule_stream = os.fdopen(os.dup(capsule_fd), "w+b")
        with capsule_stream, zipfile.ZipFile(
            capsule_stream,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(member, source)
        required_seals = (
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(capsule_fd, fcntl.F_ADD_SEALS, required_seals)
        capsule_path = f"/proc/self/fd/{capsule_fd}"
        module_path = f"{capsule_path}/{member}"
        loader = zipimport.zipimporter(capsule_path)

        assert not Path(module_path).exists()
        assert loader.get_data(module_path) == source
        with monkeypatch.context() as patch:
            patch.setattr(preflight_module, "__file__", module_path)
            patch.setattr(preflight_module, "__loader__", loader)
            result = preflight_module._run_dependency_probe({"projects": []})
    finally:
        os.close(capsule_fd)

    assert result["passed"] is True
    assert result["reason"] == "project_dependencies_satisfied"
    assert result["python_executable"]
    assert result["validation_python_launcher"]["sealed"] is True
    assert result["preflight_source_delivery"]["mode"] == (
        "compressed_argv_copy"
    )
    assert result["probe_source_sha256"] == result[
        "preflight_source_delivery"
    ]["sha256"]

