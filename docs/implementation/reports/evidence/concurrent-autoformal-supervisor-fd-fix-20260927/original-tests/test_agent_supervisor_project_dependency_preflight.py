from __future__ import annotations

import importlib.metadata
import inspect
import json
import os
import subprocess
import sys
import zipfile
import zipimport
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_accelerate_py.agent_supervisor.runtime.artifact_store import (
    BoundedArtifactStore,
)
from ipfs_accelerate_py.agent_supervisor.validation import (
    project_dependency_preflight as preflight_module,
)
from ipfs_accelerate_py.agent_supervisor.validation.project_dependency_preflight import (
    MAX_DEPENDENCY_MANIFEST_FILES,
    MAX_DEPENDENCY_PREFLIGHT_PROJECTION_BYTES,
    MAX_DEPENDENCY_PREFLIGHT_PROJECTION_ISSUES,
    MAX_INSTALLED_VERSION_BYTES,
    MAX_PREFLIGHT_INLINE_RECEIPT_BYTES,
    MAX_PYPROJECT_BYTES,
    PROJECT_DEPENDENCY_PREFLIGHT_EVENT_PROJECTION_SCHEMA,
    PROJECT_DEPENDENCY_PREFLIGHT_PROJECTION_SCHEMA,
    PROJECT_DEPENDENCY_PREFLIGHT_SCHEMA,
    PROJECT_DEPENDENCY_PROBE_SCHEMA,
    _evaluate_dependency_payload,
    _run_bounded_probe_process,
    _run_dependency_probe,
    canonical_project_dependency_preflight_receipt_bytes,
    compact_project_dependency_preflight_receipt,
    preflight_validation_project_dependencies,
    project_dependency_preflight_backoff_seconds,
    project_dependency_preflight_error_receipt,
    project_dependency_preflight_for_event,
)
from ipfs_accelerate_py.agent_supervisor.validation.validation_runtime import (
    VALIDATION_PYTHON_ENV,
    validation_python_executable,
)
from ipfs_accelerate_py.agent_supervisor.validation.validation_commands import (
    ValidationDependencyScope,
    expand_cd_parent_return_validation_commands,
    split_validation_commands,
    validation_command_dependency_scope,
    validation_command_repository_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _reseal_dependency_preflight_receipt(
    receipt: dict[str, object],
) -> dict[str, object]:
    receipt.pop("receipt_id", None)
    receipt.pop("retry_fingerprint", None)
    receipt["receipt_id"] = preflight_module._content_sha256(receipt)
    receipt["retry_fingerprint"] = preflight_module._retry_fingerprint(receipt)
    return receipt


def _probe_payload(*requirements: str) -> dict[str, object]:
    return {
        "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
        "projects": [
            {
                "root": "ipfs_kit_py",
                "project_name_sha256": "b" * 64,
                "pyproject_sha256": "a" * 64,
                "requirements": list(requirements),
                "requirement_marker_extras": [""] * len(requirements),
                "requires_python": ">=3.10",
            }
        ],
    }


def test_dependency_probe_reads_exact_source_from_capsule_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capsule_path = (
        "/proc/self/fd/12/"
        "ipfs_accelerate_py/agent_supervisor/validation/"
        "project_dependency_preflight.py"
    )
    capsule_source = b"# exact accepted capsule source\n"
    loader_reads: list[str] = []

    class CapsuleLoader:
        def get_data(self, path: str) -> bytes:
            loader_reads.append(path)
            return capsule_source

    monkeypatch.setattr(preflight_module.__spec__, "loader", CapsuleLoader())
    monkeypatch.setattr(preflight_module, "__file__", capsule_path)

    assert preflight_module._read_dependency_probe_source() == capsule_source
    assert loader_reads == [capsule_path]


def test_dependency_probe_does_not_fallback_after_capsule_loader_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableCapsuleLoader:
        def get_data(self, _path: str) -> bytes:
            raise FileNotFoundError("accepted capsule source unavailable")

    # Keep the real, readable __file__. A filesystem fallback would therefore
    # conceal the loader-authority failure and make this assertion fail.
    monkeypatch.setattr(
        preflight_module.__spec__,
        "loader",
        UnavailableCapsuleLoader(),
    )

    with pytest.raises(FileNotFoundError, match="accepted capsule source unavailable"):
        preflight_module._read_dependency_probe_source()


def test_dependency_probe_detects_preprovisioning_hypercorn_drift() -> None:
    def missing_distribution(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    result = _evaluate_dependency_payload(
        _probe_payload("hypercorn>=0.16.0"),
        version_getter=missing_distribution,
    )

    assert result["passed"] is False
    assert result["reason"] == "project_dependency_drift_detected"
    assert result["projects"][0]["missing"][0]["name"] == "hypercorn"
    assert result["projects"][0]["missing"][0]["requirement"] == ("hypercorn>=0.16.0")
    assert result["projects"][0]["missing"][0]["requirement_sha256"]


def test_dependency_probe_accepts_provisioned_hypercorn_state() -> None:
    installed = {
        "hypercorn": "0.18.0",
        "priority": "2.0.0",
    }

    result = _evaluate_dependency_payload(
        _probe_payload(
            "hypercorn>=0.16.0",
            "priority>=2.0.0",
            "missing-only-on-python-one; python_version < '2'",
        ),
        version_getter=installed.__getitem__,
    )

    assert result["passed"] is True
    assert result["reason"] == "project_dependencies_satisfied"
    assert result["projects"][0]["missing"] == []
    assert result["projects"][0]["incompatible"] == []
    assert result["projects"][0]["marker_skipped"][0]["name"] == ("missing-only-on-python-one")
    assert "marker_sha256" in result["projects"][0]["marker_skipped"][0]


def test_preflight_fails_closed_on_unknown_dynamic_dependencies(
    tmp_path,
) -> None:
    project = tmp_path / "dynamic_project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "dynamic-project"
version = "1.0.0"
dynamic = ["dependencies"]
""".strip(),
        encoding="utf-8",
    )

    def forbidden_probe(*_args, **_kwargs):
        pytest.fail("dynamic dependencies must not trigger a distribution probe")

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd dynamic_project && python -m pytest -q"],
        probe_runner=forbidden_probe,
    )

    assert receipt["schema"] == PROJECT_DEPENDENCY_PREFLIGHT_SCHEMA
    assert receipt["passed"] is False
    assert receipt["applicable"] is False
    assert receipt["reason"] == ("project_dependency_contract_collection_failed")
    assert receipt["projects"][0]["reason"] == ("dynamic_dependencies_unresolved")
    assert receipt["automatic_install_attempted"] is False


def test_preflight_resolves_setuptools_file_backed_dynamic_dependencies(
    tmp_path,
) -> None:
    project = tmp_path / "dynamic_project"
    project.mkdir()
    (project / "requirements.txt").write_text(
        "# runtime\npackaging>=23.2\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        """
[project]
name = "dynamic-project"
version = "1.0.0"
dynamic = ["dependencies"]

[tool.setuptools.dynamic]
dependencies = {file = ["requirements.txt"]}
""".strip(),
        encoding="utf-8",
    )
    payloads: list[dict[str, object]] = []

    def passing_probe(payload, **_kwargs):
        payloads.append(payload)
        return {
            "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
            "passed": True,
            "reason": "project_dependencies_satisfied",
            "projects": [],
        }

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd dynamic_project && python -c 'pass'"],
        probe_runner=passing_probe,
    )

    assert receipt["passed"] is True
    assert receipt["projects"][0]["dependency_source"] == ("setuptools_dynamic_file")
    manifest = receipt["projects"][0]["dependency_manifests"][0]
    assert "path" not in manifest
    assert manifest["path_sha256"]
    assert manifest["content_sha256"]
    assert payloads[0]["projects"][0]["requirements"] == ["packaging>=23.2"]


def test_preflight_fails_closed_on_invalid_static_dependency_contract(
    tmp_path,
) -> None:
    project = tmp_path / "invalid_project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "invalid-project"
version = "1.0.0"
dependencies = "hypercorn>=0.16.0"
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd invalid_project && python -m pytest -q"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "invalid metadata must fail before probing"
        ),
    )

    assert receipt["passed"] is False
    assert receipt["reason"] == ("project_dependency_contract_collection_failed")
    assert receipt["projects"][0]["reason"] == ("pep621_dependencies_must_be_static_strings")


def test_literal_file_validation_is_dependency_neutral(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    artifact = project / "discovery.md"
    artifact.write_text("ready\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        """
[project]
name = "project"
version = "1.0.0"
dependencies = ["definitely-missing-validation-runtime==9.9.9"]
""".strip(),
        encoding="utf-8",
    )
    command = f"test -f {artifact}"

    receipt = preflight_validation_project_dependencies(
        project,
        [command],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "a literal file predicate must not probe Python metadata"
        ),
    )

    assert receipt["passed"] is True
    assert receipt["applicable"] is False
    assert receipt["reason"] == "validation_commands_dependency_neutral"
    assert receipt["automatic_install_attempted"] is False
    assert receipt["validation_roots"] == [""]
    assert receipt["project_roots"] == []
    assert receipt["projects"] == []
    assert receipt["dependency_neutral_command_count"] == 1
    neutral = receipt["dependency_neutral_commands"][0]
    assert neutral["command_index"] == 0
    assert neutral["root"] == ""
    assert neutral["scope"] == "dependency_neutral"
    assert neutral["command_sha256"]
    assert command not in json.dumps(receipt)


def test_dependency_neutral_and_python_commands_use_strongest_root_scope(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "artifact.txt").write_text("ready\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        """
[project]
name = "project"
version = "1.0.0"
dependencies = ["definitely-missing-validation-runtime==9.9.9"]
""".strip(),
        encoding="utf-8",
    )
    payloads: list[dict[str, object]] = []

    def passing_probe(payload, **_kwargs):
        payloads.append(payload)
        return {
            "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
            "passed": True,
            "reason": "project_dependencies_satisfied",
            "projects": [],
        }

    receipt = preflight_validation_project_dependencies(
        project,
        ["test -f artifact.txt", "python -c 'pass'"],
        probe_runner=passing_probe,
    )

    assert receipt["passed"] is True
    assert receipt["applicable"] is True
    assert receipt["project_roots"] == [""]
    assert receipt["dependency_neutral_command_count"] == 1
    assert payloads[0]["projects"][0]["requirements"] == [
        "definitely-missing-validation-runtime==9.9.9"
    ]


def test_preflight_fails_closed_when_approved_probe_is_unavailable(
    tmp_path,
) -> None:
    project = tmp_path / "static_project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "static-project"
version = "1.0.0"
dependencies = ["hypercorn>=0.16.0"]
""".strip(),
        encoding="utf-8",
    )

    def unavailable_probe(*_args, **_kwargs):
        raise RuntimeError("approved interpreter unavailable")

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd static_project && python -m pytest -q"],
        probe_runner=unavailable_probe,
    )

    assert receipt["passed"] is False
    assert receipt["reason"] == ("approved_validation_environment_dependency_probe_failed")
    assert receipt["probe"]["reason"] == "dependency_probe_infrastructure_error"
    assert receipt["remediation"]["kind"] == ("repair_approved_validation_dependency_probe")
    assert receipt["automatic_install_attempted"] is False


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "memfd_create"),
    reason="sealed launcher paths are Linux memfd addresses",
)
def test_preflight_repairs_inherited_procfs_validation_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fd = os.memfd_create(
        "validation Python launcher",
        os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
    )
    try:
        os.write(fd, b"#!/bin/sh\nexit 1\n")
        os.fchmod(fd, 0o500)
        monkeypatch.setenv(VALIDATION_PYTHON_ENV, f"/proc/self/fd/{fd}")
        admitted = validation_python_executable()
        assert admitted == str(Path(sys.executable).resolve())
        assert not admitted.startswith("/proc/")
        probe = _run_dependency_probe(
            {
                "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
                "projects": [],
            }
        )
        assert probe.get("passed") is True
        assert probe.get("reason") != "dependency_probe_infrastructure_error"
    finally:
        os.close(fd)


def test_preflight_unexpected_collection_error_returns_typed_receipt(
    tmp_path,
) -> None:
    missing_workspace = tmp_path / "missing"
    receipt = preflight_validation_project_dependencies(
        missing_workspace,
        ["python -m pytest -q"],
    )

    assert receipt["passed"] is False
    assert receipt["reason"] == ("project_dependency_preflight_infrastructure_error")
    assert receipt["error_type"] == "FileNotFoundError"
    assert receipt["retry_fingerprint"] != receipt["receipt_id"]
    assert "python -m pytest" not in json.dumps(receipt)


def test_dependency_retry_fingerprint_ignores_ephemeral_workspace_path(
    tmp_path,
) -> None:
    receipts = []
    for name in ("attempt-one", "attempt-two"):
        workspace = tmp_path / name
        project = workspace / "static_project"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(
            """
[project]
name = "static-project"
version = "1.0.0"
dependencies = ["packaging>=23.2"]
""".strip(),
            encoding="utf-8",
        )
        receipts.append(
            preflight_validation_project_dependencies(
                workspace,
                ["cd static_project && python -c 'pass'"],
                probe_runner=lambda *_args, **_kwargs: {
                    "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
                    "passed": False,
                    "reason": "project_dependency_drift_detected",
                    "projects": [
                        {
                            "passed": False,
                            "missing": [
                                {
                                    "name": "packaging",
                                    "requirement": "packaging>=23.2",
                                }
                            ],
                            "incompatible": [],
                            "invalid": [],
                        }
                    ],
                },
            )
        )

    assert receipts[0]["receipt_id"] != receipts[1]["receipt_id"]
    assert receipts[0]["retry_fingerprint"] == (receipts[1]["retry_fingerprint"])


def test_dependency_preflight_backoff_is_fingerprinted_and_bounded() -> None:
    fingerprint = "sha256:stable"

    assert (
        project_dependency_preflight_backoff_seconds(
            fingerprint,
            [],
        )
        == 300
    )
    assert (
        project_dependency_preflight_backoff_seconds(
            fingerprint,
            [fingerprint],
        )
        == 600
    )
    assert (
        project_dependency_preflight_backoff_seconds(
            fingerprint,
            [fingerprint, fingerprint],
        )
        == 1200
    )
    assert (
        project_dependency_preflight_backoff_seconds(
            fingerprint,
            [fingerprint] * 20,
        )
        == 1800
    )
    assert (
        project_dependency_preflight_backoff_seconds(
            fingerprint,
            ["sha256:changed", fingerprint],
        )
        == 300
    )


def test_dependency_preflight_compaction_binds_oversized_receipt() -> None:
    oversized = "x" * 80_000
    receipt = {
        "schema": PROJECT_DEPENDENCY_PREFLIGHT_SCHEMA,
        "receipt_id": "a" * 64,
        "retry_fingerprint": "b" * 64,
        "passed": False,
        "applicable": True,
        "reason": "approved_validation_environment_dependency_drift",
        "automatic_install_attempted": False,
        "probe_scope": "installed_distribution_metadata",
        "validation_command_count": 7,
        "validation_roots": ["."],
        "project_roots": ["."],
        "projects": [{"root": ".", "closure": oversized} for _ in range(16)],
        "dependency_neutral_commands": [],
        "missing_requirements": [],
        "incompatible_requirements": [
            {
                "name": "urllib3",
                "requirement": "urllib3<2",
                "installed_version": "2.7.0",
                "closure": oversized,
            }
        ],
        "invalid_requirements": [],
        "invalid_commands": [],
        "probe": {
            "reason": "project_dependency_drift_detected",
            "python_executable": "/usr/bin/python3.12",
            "python_version": "3.12.3",
            "projects": [{"closure": oversized} for _ in range(16)],
        },
        "remediation": {
            "kind": "provision_approved_validation_environment",
            "python_executable": "/usr/bin/python3.12",
            "requirements": ["urllib3<2"],
            "automatic_provisioning": False,
            "rerun_required": True,
        },
    }
    assert len(json.dumps(receipt).encode("utf-8")) > 1_048_576

    compact = compact_project_dependency_preflight_receipt(receipt)

    assert compact == compact_project_dependency_preflight_receipt(receipt)
    assert compact_project_dependency_preflight_receipt(compact) == compact
    assert compact["schema"] == PROJECT_DEPENDENCY_PREFLIGHT_PROJECTION_SCHEMA
    assert compact["source_receipt_id"] == receipt["receipt_id"]
    assert compact["retry_fingerprint"] == receipt["retry_fingerprint"]
    assert compact["incompatible_count"] == 1
    assert compact["incompatible_requirements"][0] == {
        "name": "urllib3",
        "requirement": "urllib3<2",
        "installed_version": "2.7.0",
        "issue_sha256": compact["incompatible_requirements"][0][
            "issue_sha256"
        ],
    }
    assert oversized not in json.dumps(compact)
    assert (
        len(json.dumps(compact).encode("utf-8"))
        <= MAX_DEPENDENCY_PREFLIGHT_PROJECTION_BYTES
    )


@pytest.mark.parametrize("long_text", ["x" * 4096, "\x00" * 4096])
def test_dependency_preflight_compaction_fits_worst_case_samples(
    long_text: str,
) -> None:
    issue = {
        "name": long_text,
        "requirement": long_text,
        "installed_version": long_text,
        "reason": long_text,
        "root": long_text,
    }
    issue_count = 32
    receipt = {
        "schema": PROJECT_DEPENDENCY_PREFLIGHT_SCHEMA,
        "receipt_id": "a" * 64,
        "retry_fingerprint": "b" * 64,
        "passed": False,
        "applicable": True,
        "reason": "approved_validation_environment_dependency_drift",
        "automatic_install_attempted": False,
        "probe_scope": "installed_distribution_metadata",
        "validation_command_count": 7,
        "validation_roots": ["."],
        "project_roots": ["."],
        "projects": [],
        "dependency_neutral_commands": [],
        "missing_requirements": [dict(issue) for _ in range(issue_count)],
        "incompatible_requirements": [dict(issue) for _ in range(issue_count)],
        "invalid_requirements": [dict(issue) for _ in range(issue_count)],
        "invalid_commands": [long_text for _ in range(issue_count)],
        "probe": {
            "reason": long_text,
            "python_executable": long_text,
            "python_version": long_text,
            "projects": [],
            "validation_python_launcher": {},
        },
        "remediation": {
            "kind": long_text,
            "python_executable": long_text,
            "requirements": [long_text for _ in range(issue_count)],
            "automatic_provisioning": False,
            "rerun_required": True,
        },
    }

    compact = compact_project_dependency_preflight_receipt(receipt)

    assert compact["missing_count"] == issue_count
    assert compact["incompatible_count"] == issue_count
    assert compact["invalid_requirement_count"] == issue_count
    assert compact["invalid_command_count"] == issue_count
    assert compact["issues_truncated"] is True
    assert all(
        len(compact[field]) == MAX_DEPENDENCY_PREFLIGHT_PROJECTION_ISSUES
        for field in (
            "missing_requirements",
            "incompatible_requirements",
            "invalid_requirements",
        )
    )
    assert (
        len(json.dumps(compact).encode("utf-8"))
        <= MAX_DEPENDENCY_PREFLIGHT_PROJECTION_BYTES
    )
    assert compact_project_dependency_preflight_receipt(compact) == compact


@pytest.mark.parametrize(
    "location",
    ["top", "probe", "launcher", "remediation", "issue"],
)
def test_dependency_preflight_projection_rejects_hidden_claim_fields(
    location: str,
) -> None:
    compact = compact_project_dependency_preflight_receipt(
        {
            "schema": PROJECT_DEPENDENCY_PREFLIGHT_SCHEMA,
            "receipt_id": "a" * 64,
            "retry_fingerprint": "b" * 64,
            "missing_requirements": [
                {"name": "missing", "requirement": "missing>=1"}
            ],
            "incompatible_requirements": [],
            "invalid_requirements": [],
            "invalid_commands": [],
            "projects": [],
            "project_roots": [],
            "validation_roots": [],
            "dependency_neutral_commands": [],
            "probe": {"validation_python_launcher": {}},
            "remediation": {"requirements": []},
        }
    )
    tampered = deepcopy(compact)
    targets = {
        "top": tampered,
        "probe": tampered["probe"],
        "launcher": tampered["probe"]["validation_python_launcher"],
        "remediation": tampered["remediation"],
        "issue": tampered["missing_requirements"][0],
    }
    targets[location]["hidden_model_authority"] = True
    unsigned = dict(tampered)
    unsigned.pop("projection_id")
    tampered["projection_id"] = preflight_module._content_sha256(unsigned)

    with pytest.raises(ValueError, match="not closed|unknown"):
        compact_project_dependency_preflight_receipt(tampered)


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


def test_pytest_command_selects_declared_test_extra_deterministically(
    tmp_path,
) -> None:
    project = tmp_path / "static_project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "static-project"
version = "1.0.0"
dependencies = ["packaging>=23.2"]

[project.optional-dependencies]
dev = ["dev-only>=1"]
testing = ["testing-only>=2"]
test = ["test-only>=3"]
""".strip(),
        encoding="utf-8",
    )
    payloads: list[dict[str, object]] = []

    def passing_probe(payload, **_kwargs):
        payloads.append(payload)
        return {
            "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
            "passed": True,
            "reason": "project_dependencies_satisfied",
            "projects": [],
        }

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd static_project && python -m pytest -q"],
        probe_runner=passing_probe,
    )

    assert receipt["passed"] is True
    assert receipt["projects"][0]["selected_validation_extras"] == ["test"]
    assert payloads[0]["projects"][0]["requirements"] == [
        "pytest",
        "test-only>=3",
    ]


def test_direct_reference_is_rejected_without_persisting_url_secrets(
    tmp_path,
) -> None:
    project = tmp_path / "static_project"
    project.mkdir()
    secret_url = "https://user:top-secret@example.invalid/pkg.whl?signature=do-not-persist"
    (project / "pyproject.toml").write_text(
        f"""
[project]
name = "static-project"
version = "1.0.0"
dependencies = ["private-pkg @ {secret_url}"]
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd static_project && python -c 'pass'"],
    )
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["passed"] is False
    assert receipt["invalid_requirements"][0]["kind"] == ("direct_reference_unverifiable")
    assert "direct_reference_sha256" in receipt["invalid_requirements"][0]
    assert "top-secret" not in serialized
    assert "do-not-persist" not in serialized
    assert secret_url not in serialized


def test_pyproject_symlink_cannot_escape_project_root(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    project.mkdir(parents=True)
    outside_secret = "outside-pyproject-secret-must-not-persist"
    outside = tmp_path / "outside.toml"
    outside.write_text(
        f'[project]\nname = "{outside_secret}"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    (project / "pyproject.toml").symlink_to(outside)

    receipt = preflight_validation_project_dependencies(
        workspace,
        ["cd project && python -c 'pass'"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "an escaping pyproject must fail before probing"
        ),
    )

    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == ("pyproject_path_or_snapshot_invalid")
    assert outside_secret not in json.dumps(receipt)


def test_dynamic_dependency_manifest_symlink_cannot_escape_project_root(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    project.mkdir(parents=True)
    outside_secret = "outside-manifest-secret-must-not-persist"
    outside = tmp_path / "outside-requirements.txt"
    outside.write_text(
        f"private-package @ https://{outside_secret}.invalid/pkg.whl\n",
        encoding="utf-8",
    )
    (project / "requirements.txt").symlink_to(outside)
    (project / "pyproject.toml").write_text(
        """
[project]
name = "project"
version = "1.0"
dynamic = ["dependencies"]

[tool.setuptools.dynamic]
dependencies = {file = ["requirements.txt"]}
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        workspace,
        ["cd project && python -c 'pass'"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "an escaping manifest must fail before probing"
        ),
    )

    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == ("dynamic_dependencies_unresolved")
    assert outside_secret not in json.dumps(receipt)


def test_oversized_sparse_pyproject_is_rejected_without_reading(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    project.mkdir(parents=True)
    pyproject = project / "pyproject.toml"
    pyproject.touch()
    os.truncate(pyproject, MAX_PYPROJECT_BYTES + 1)

    def forbidden_read(*_args, **_kwargs):
        pytest.fail("an oversized stat result must be rejected before os.read")

    monkeypatch.setattr(preflight_module.os, "read", forbidden_read)
    receipt = preflight_validation_project_dependencies(
        workspace,
        ["cd project && python -c 'pass'"],
    )

    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == ("pyproject_exceeds_preflight_bound")
    assert receipt["projects"][0]["pyproject_bytes"] == (MAX_PYPROJECT_BYTES + 1)


def test_pyproject_mutation_during_bounded_read_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "project"
version = "1.0"
dependencies = []
""".strip(),
        encoding="utf-8",
    )
    original_read = os.read
    mutated = False

    def racing_read(descriptor, maximum_bytes):
        nonlocal mutated
        chunk = original_read(descriptor, maximum_bytes)
        if chunk and not mutated:
            mutated = True
            with pyproject.open("ab") as stream:
                stream.write(b"\n# concurrent mutation\n")
        return chunk

    monkeypatch.setattr(preflight_module.os, "read", racing_read)
    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd project && python -c 'pass'"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "a raced snapshot must fail before probing"
        ),
    )

    assert mutated is True
    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == ("pyproject_path_or_snapshot_invalid")


def test_project_root_replacement_cannot_rebase_pyproject_containment(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    project.mkdir(parents=True)
    original_project = workspace / "project-original"
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "inside"\nversion = "1.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    outside_secret = "outside-root-race-secret"
    (outside / "pyproject.toml").write_text(
        (
            '[project]\nname = "outside"\nversion = "1.0"\n'
            f'dependencies = ["{outside_secret}>=1"]\n'
        ),
        encoding="utf-8",
    )
    original_lstat = Path.lstat
    replaced = False

    def racing_lstat(path):
        nonlocal replaced
        if path == project / "pyproject.toml" and not replaced:
            replaced = True
            project.rename(original_project)
            project.symlink_to(outside, target_is_directory=True)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", racing_lstat)
    receipt = preflight_validation_project_dependencies(
        workspace,
        ["cd project && python -c 'pass'"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "a replaced project root must fail before probing"
        ),
    )

    assert replaced is True
    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == (
        "pyproject_path_or_snapshot_invalid"
    )
    assert outside_secret not in json.dumps(receipt)


def test_bounded_metadata_reader_uses_python_38_compatible_stat_api() -> None:
    source = inspect.getsource(preflight_module._read_bounded_contained_regular_file)

    assert ".stat(follow_symlinks=False)" not in source
    assert source.count("os.stat(") == 2


def test_project_name_and_requires_python_are_hash_only_in_receipts(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    project_name_secret = "private-project-name-secret"
    python_secret = "invalid-python-contract-secret"
    (project / "pyproject.toml").write_text(
        f"""
[project]
name = "{project_name_secret}"
version = "1.0"
requires-python = "{python_secret}"
dependencies = []
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd project && python -c 'pass'"],
    )
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["passed"] is False
    assert receipt["projects"][0]["project_name_sha256"]
    assert receipt["projects"][0]["requires_python_sha256"]
    assert "requires_python" not in receipt["projects"][0]
    assert receipt["invalid_requirements"][0]["kind"] == ("requires-python")
    assert receipt["invalid_requirements"][0]["requirement_sha256"]
    assert project_name_secret not in serialized
    assert python_secret not in serialized


@pytest.mark.parametrize(
    ("installed_version", "error_type"),
    [
        ("invalid-installed-version-secret", "InvalidVersion"),
        (
            "x" * (MAX_INSTALLED_VERSION_BYTES + 1),
            "InstalledVersionExceedsBound",
        ),
    ],
    ids=("invalid", "oversized"),
)
def test_invalid_installed_versions_are_bounded_and_hash_only(
    installed_version,
    error_type,
) -> None:
    result = _evaluate_dependency_payload(
        _probe_payload("private-package>=1"),
        version_getter=lambda _name: installed_version,
    )
    serialized = json.dumps(result, sort_keys=True)
    invalid = result["projects"][0]["invalid"][0]

    assert result["passed"] is False
    assert invalid["kind"] == "installed_version"
    assert invalid["error_type"] == error_type
    assert invalid["installed_version_sha256"]
    assert installed_version not in serialized


def test_valid_installed_version_is_canonicalized_before_persistence() -> None:
    result = _evaluate_dependency_payload(
        _probe_payload("private-package>=1"),
        version_getter=lambda _name: "01.0",
    )

    assert result["passed"] is True
    assert result["projects"][0]["observed"][0]["installed_version"] == "1.0"
    assert result["projects"][0]["observed"][0]["installed_version_sha256"]


def test_setuptools_dynamic_test_extra_is_loaded_with_marker_provenance(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "requirements-test.txt").write_text(
        "selected-only>=1; extra == 'test'\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        """
[project]
name = "project"
version = "1.0"
dependencies = []
dynamic = ["optional-dependencies"]

[tool.setuptools.dynamic.optional-dependencies]
test = {file = ["requirements-test.txt"]}
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd project && python -m pytest -q"],
        probe_runner=lambda payload, **_kwargs: _evaluate_dependency_payload(
            payload,
            version_getter={
                "pytest": "9.0.3",
                "selected-only": "1.2.0",
            }.__getitem__,
        ),
    )

    assert receipt["passed"] is True
    assert receipt["projects"][0]["selected_validation_extras"] == ["test"]
    assert receipt["projects"][0]["validation_dependency_source"] == ("setuptools_dynamic_file")
    observed = receipt["probe"]["projects"][0]["observed"]
    assert any(
        item["name"] == "selected-only" and item["selected_extra"] == "test" for item in observed
    )


@pytest.mark.parametrize(
    "pyproject_optional_contract",
    [
        """
[project]
name = "project"
version = "1.0"
dynamic = ["optional-dependencies"]
""",
        """
[project]
name = "project"
version = "1.0"
dynamic = ["optional-dependencies"]

[project.optional-dependencies]
test = ["private-package>=1"]

[tool.setuptools.dynamic.optional-dependencies]
test = {file = ["requirements-test.txt"]}
""",
    ],
    ids=("unresolved", "static-and-dynamic"),
)
def test_dynamic_validation_extra_fails_closed_when_contract_is_ambiguous(
    tmp_path,
    pyproject_optional_contract,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "requirements-test.txt").write_text(
        "private-package>=1\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        pyproject_optional_contract.strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd project && python -m pytest -q"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "an ambiguous selected extra must fail before probing"
        ),
    )

    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == ("validation_dependencies_unresolved")


@pytest.mark.parametrize(
    ("requires_python_contract", "expected_reason"),
    [
        (
            'dynamic = ["requires-python"]',
            "pep621_requires_python_dynamic_unresolved",
        ),
        ('requires-python = 0', "pep621_requires_python_must_be_string"),
    ],
)
def test_unresolved_or_falsey_requires_python_fails_closed(
    tmp_path,
    requires_python_contract,
    expected_reason,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        f"""
[project]
name = "project"
version = "1.0"
dependencies = []
{requires_python_contract}
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd project && python -c 'pass'"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "an unresolved interpreter contract must fail before probing"
        ),
    )

    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == expected_reason


def test_dynamic_runtime_and_validation_manifests_share_one_file_bound(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime_files = [
        f"requirements-{index}.txt"
        for index in range(MAX_DEPENDENCY_MANIFEST_FILES)
    ]
    for path in runtime_files:
        (project / path).write_text("packaging>=23.2\n", encoding="utf-8")
    (project / "requirements-test.txt").write_text(
        "pytest>=8\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        f"""
[project]
name = "project"
version = "1.0"
dynamic = ["dependencies", "optional-dependencies"]

[tool.setuptools.dynamic]
dependencies = {{file = {json.dumps(runtime_files)}}}

[tool.setuptools.dynamic.optional-dependencies]
test = {{file = ["requirements-test.txt"]}}
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd project && python -m pytest -q"],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "an over-bounded manifest set must fail before probing"
        ),
    )

    assert receipt["passed"] is False
    assert receipt["projects"][0]["reason"] == "validation_dependencies_unresolved"


@pytest.mark.parametrize(
    "command",
    [
        "(cd child && python -m pytest -q)",
        "bash -c 'cd child && python -m pytest -q'",
        "bash -O extdebug -c 'cd child && python -m pytest -q'",
        "timeout 30 bash -c 'cd child && python -m pytest -q'",
        "env -S 'bash -c cd child && python -m pytest -q'",
        "exec -a nested env -S 'bash -c cd child && python -m pytest -q'",
        "pushd child && python -m pytest -q",
        "popd && python -m pytest -q",
        ". ./activate && python -m pytest -q",
        "source ./activate && python -m pytest -q",
        "eval 'cd child && python -m pytest -q'",
        "trap 'cd child' DEBUG && python -m pytest -q",
        "alias enter='cd child' && enter && python -m pytest -q",
        "unalias enter && python -m pytest -q",
        "shopt -s expand_aliases && python -m pytest -q",
        "echo setup\npython -m pytest -q",
        "if true; then cd child; fi; python -m pytest -q",
        "function enter { cd child; }; enter; python -m pytest -q",
        "{ cd child; python -m pytest -q; }",
    ],
)
def test_unrecognized_cwd_changing_validation_syntax_fails_closed(
    tmp_path,
    command,
) -> None:
    receipt = preflight_validation_project_dependencies(
        tmp_path,
        [command],
        probe_runner=lambda *_args, **_kwargs: pytest.fail(
            "an unsafe validation root must fail before probing"
        ),
    )

    assert receipt["passed"] is False
    assert receipt["reason"] == ("project_dependency_contract_collection_failed")
    assert receipt["invalid_commands"][0]["reason"] == ("validation_repository_root_is_unsafe")


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest .",
        "echo source",
        "echo bash -c",
    ],
)
def test_ordinary_shell_arguments_do_not_change_inferred_repository_root(
    command,
) -> None:
    assert validation_command_repository_root(command) == ""


def test_cd_parent_return_closeout_chain_is_not_reassociated() -> None:
    """A multi-root ``&&`` program remains one fail-closed command."""

    command = (
        "cd ipfs_kit_py && python -m pytest -q "
        "tests/runtime_readiness/release/test_joined_release_receipt.py "
        "&& cd .. && python scripts/validate_ipfs_kit_runtime_readiness_board.py "
        "--check-all"
    )
    assert validation_command_repository_root(command) is None
    assert expand_cd_parent_return_validation_commands(command) == [command]
    assert split_validation_commands(command) == [command]


def test_cd_parent_return_closeout_chain_fails_dependency_preflight(
    tmp_path: Path,
) -> None:
    """Legacy multi-root chains require explicit atomic board commands."""

    project = tmp_path / "ipfs_kit_py"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\n"
        'name = "ipfs-kit-py"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = []\n",
        encoding="utf-8",
    )
    command = (
        "cd ipfs_kit_py && python -m pytest -q "
        "tests/runtime_readiness/release/test_joined_release_receipt.py "
        "&& cd .. && python scripts/validate_ipfs_kit_runtime_readiness_board.py "
        "--check-all"
    )
    receipt = preflight_validation_project_dependencies(
        tmp_path,
        split_validation_commands(command),
        probe_runner=lambda *_args, **_kwargs: {
            "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
            "passed": True,
            "reason": "probe_stub_ok",
            "projects": [],
            "probe_source_sha256": "a" * 64,
        },
    )
    assert receipt["passed"] is False
    assert receipt["reason"] == "project_dependency_contract_collection_failed"
    assert receipt["invalid_commands"][0]["reason"] == (
        "validation_repository_root_is_unsafe"
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "PYTHONDONTWRITEBYTECODE=1 python3 -B "
            "scripts/ops/verified_gui_optimizer_vgo001_oracle.py --check-all "
            "; cd external/ipfs_datasets && python3 -m pytest "
            "tests/unit/logic/gui_optimizer/test_models.py -q",
            [
                "PYTHONDONTWRITEBYTECODE=1 python3 -B "
                "scripts/ops/verified_gui_optimizer_vgo001_oracle.py --check-all",
                "cd external/ipfs_datasets && python3 -m pytest "
                "tests/unit/logic/gui_optimizer/test_models.py -q",
            ],
        ),
        (
            "PYTHONDONTWRITEBYTECODE=1 python3 -B "
            "scripts/ops/verified_gui_optimizer_vgo009_oracle.py --check-all "
            "; cd external/ipfs_accelerate && PYTHONDONTWRITEBYTECODE=1 "
            "PYTHONPATH=.:../ipfs_datasets python3 -m pytest "
            "test/api/test_gui_optimizer_authority.py -q",
            [
                "PYTHONDONTWRITEBYTECODE=1 python3 -B "
                "scripts/ops/verified_gui_optimizer_vgo009_oracle.py --check-all",
                "cd external/ipfs_accelerate && PYTHONDONTWRITEBYTECODE=1 "
                "PYTHONPATH=.:../ipfs_datasets python3 -m pytest "
                "test/api/test_gui_optimizer_authority.py -q",
            ],
        ),
    ],
)
def test_atomic_multi_root_validation_commands_have_exact_safe_roots(
    command: str,
    expected: list[str],
) -> None:
    assert split_validation_commands(command) == expected
    assert validation_command_repository_root(expected[0]) == ""
    assert validation_command_repository_root(expected[1]) in {
        "external/ipfs_accelerate",
        "external/ipfs_datasets",
    }


@pytest.mark.parametrize(
    "command",
    [
        # Multiple parent returns remain fail-closed.
        "cd a && true && cd .. && true && cd .. && true",
        # Nested shell still fail-closed.
        "cd a && bash -c 'true' && cd .. && true",
        # Mid-chain pushd is not expanded.
        "cd a && pushd b && true && cd .. && true",
    ],
)
def test_unsafe_multi_cd_chains_are_not_expanded(command: str) -> None:
    expanded = expand_cd_parent_return_validation_commands(command)
    assert expanded == [command]
    assert validation_command_repository_root(command) is None


@pytest.mark.parametrize(
    "command",
    [
        'cd child && test -n "$VGO_SPLIT_SENTINEL" && cd .. && true',
        "cd child && echo '~' && cd .. && true",
        'cd child && echo "*" && cd .. && true',
        "cd child && echo `printf true` && cd .. && true",
        "cd child && ! true && cd .. && true",
        "cd child && true # ignored && cd .. && false",
        "cd child && export GIT_DIR=missing && cd .. && git status",
        "cd child && PATH=/missing && cd .. && git status",
        "cd child && unset PATH && cd .. && git status",
        "cd child && set -e && cd .. && false",
        "cd child && printf -v PATH /missing && cd .. && git status",
        "cd child && exec true && cd .. && false",
        "cd child && exit 0 && cd .. && false",
    ],
)
def test_noncanonical_parent_return_chains_are_not_expanded(command: str) -> None:
    assert expand_cd_parent_return_validation_commands(command) == [command]
    assert validation_command_repository_root(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "true && cd child && true ;; true",
        "true && cd child && true ; ; true",
        "true && cd child && true ;& true",
        "true && cd child && true ;| true",
        "; true && cd child && true",
        ";; true && cd child && true",
        ";& true && cd child && true",
        ";| true && cd child && true",
        "true && \\\ncd child && true",
        "cd child && true && \\\ncd .. && true",
    ],
)
def test_public_splitter_preserves_malformed_or_continued_shell_chains(
    command: str,
) -> None:
    assert split_validation_commands(command) == [command]
    assert validation_command_repository_root(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "test -f artifact.txt",
        "test -e /tmp/receipt.json",
        "test -d 'directory with spaces'",
        "[ -r artifact.txt ]",
        "cd child && test -s artifact.txt",
    ],
)
def test_literal_file_predicates_are_dependency_neutral(command) -> None:
    assert validation_command_dependency_scope(command) is (
        ValidationDependencyScope.DEPENDENCY_NEUTRAL
    )


@pytest.mark.parametrize(
    "command",
    [
        "python -c 'pass'",
        "python -m pytest -q",
        "test -f artifact.txt && python -c 'pass'",
        "test -f artifact.txt || true",
        "./test -f artifact.txt",
        "env MODE=check test -f artifact.txt",
        "command test -f artifact.txt",
        "test ! -f artifact.txt",
        "test -f '$ARTIFACT'",
        "test -f \"$(python -c 'print(1)')\"",
        "test -f artifact.txt &&",
        "test -f artifact.txt ||",
        "test -f artifact.txt ;",
        "test -f artifact.txt &",
        "bash -c 'test -f artifact.txt'",
        "cd child && test -f artifact.txt && python -c 'pass'",
        "cd child && test -f artifact.txt &&",
    ],
)
def test_dynamic_mixed_and_unknown_commands_remain_project_required(
    command,
) -> None:
    assert validation_command_dependency_scope(command) is (
        ValidationDependencyScope.PROJECT_REQUIRED
    )


def test_quoted_pytest_module_selects_validation_extra(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "project"
version = "1.0"
dependencies = []

[project.optional-dependencies]
test = ["selected-only>=1"]
""".strip(),
        encoding="utf-8",
    )
    payloads = []

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd project && python -m 'pytest' -q"],
        probe_runner=lambda payload, **_kwargs: (
            payloads.append(payload)
            or {
                "schema": PROJECT_DEPENDENCY_PROBE_SCHEMA,
                "passed": True,
                "reason": "project_dependencies_satisfied",
                "projects": [],
            }
        ),
    )

    assert receipt["passed"] is True
    assert receipt["projects"][0]["selected_validation_extras"] == ["test"]
    assert payloads[0]["projects"][0]["requirements"] == [
        "pytest",
        "selected-only>=1",
    ]
    assert payloads[0]["projects"][0]["requirement_marker_extras"] == ["", "test"]


def test_pytest_preflight_does_not_stall_on_runtime_or_dev_extra_drift(
    tmp_path,
) -> None:
    """ASEH-032: sealed overlays cannot grow kit runtime/dev extras."""

    project = tmp_path / "ipfs_kit_py"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "ipfs_kit_py"
version = "0.3.0"
dependencies = [
    "aiofiles>=23.1.0",
    "jsonpatch>=1.33",
    "hypercorn>=0.16.0",
    "protobuf>=5.26.0,<7.0.0",
    "watchdog>=3.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "paramiko>=3.4.0",
]
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd ipfs_kit_py && python3 -m pytest -q tests/test_context_pack_store.py"],
        probe_runner=lambda payload, **_kwargs: _evaluate_dependency_payload(
            payload,
            version_getter={"pytest": "9.0.3"}.__getitem__,
        ),
    )

    assert receipt["passed"] is True
    assert receipt["reason"] == (
        "approved_validation_environment_satisfies_project_dependencies"
    )
    assert receipt["projects"][0]["selected_validation_extras"] == []
    assert receipt["probe"]["projects"][0]["missing"] == []
    assert receipt["probe"]["projects"][0]["incompatible"] == []
    assert receipt["probe"]["projects"][0]["observed"][0]["name"] == "pytest"


def test_non_pytest_command_still_probes_runtime_dependencies(
    tmp_path,
) -> None:
    project = tmp_path / "ipfs_kit_py"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "ipfs_kit_py"
version = "0.3.0"
dependencies = ["hypercorn>=0.16.0"]
""".strip(),
        encoding="utf-8",
    )

    def missing_distribution(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd ipfs_kit_py && python3 -c 'import ipfs_kit_py'"],
        probe_runner=lambda payload, **_kwargs: _evaluate_dependency_payload(
            payload,
            version_getter=missing_distribution,
        ),
    )

    assert receipt["passed"] is False
    assert receipt["reason"] == "approved_validation_environment_dependency_drift"
    assert receipt["missing_requirements"][0]["name"] == "hypercorn"
    assert receipt["remediation"]["kind"] == (
        "provision_approved_validation_environment"
    )


def test_dependency_probe_runtime_is_declared_through_packaging_source_of_truth() -> None:
    requirements = {
        line.strip()
        for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    setup_source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")

    assert "packaging>=23.2" in requirements
    assert (
        'install_requires = _read_requirements(this_directory / "requirements.txt")' in setup_source
    )
    assert "install_requires=install_requires" in setup_source


@pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason="the fixture's static requires-python intentionally needs 3.10",
)
def test_preflight_uses_approved_interpreter_for_installed_metadata(
    tmp_path,
) -> None:
    project = tmp_path / "static_project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "static-project"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = ["packaging>=23.2"]
""".strip(),
        encoding="utf-8",
    )

    receipt = preflight_validation_project_dependencies(
        tmp_path,
        ["cd static_project && python -m pytest -q"],
    )

    assert receipt["passed"] is True
    assert receipt["applicable"] is True
    assert receipt["reason"] == ("approved_validation_environment_satisfies_project_dependencies")
    assert receipt["probe"]["python_executable"]
    assert receipt["probe"]["validation_python_launcher"]["sealed"] is (
        sys.platform.startswith("linux")
    )
    assert receipt["probe"]["preflight_source_delivery"]["mode"] == ("compressed_argv_copy")
    assert (
        receipt["probe"]["probe_source_sha256"]
        == (receipt["probe"]["preflight_source_delivery"]["sha256"])
    )
    assert receipt["probe"]["projects"][0]["observed"][0]["name"] == ("pytest")


def test_dependency_preflight_event_projection_binds_full_receipt_artifact(
    tmp_path,
) -> None:
    receipt = project_dependency_preflight_error_receipt(
        tmp_path,
        ["python -m pytest -q"],
        RuntimeError("fixture failure"),
    )
    canonical = canonical_project_dependency_preflight_receipt_bytes(receipt)

    with BoundedArtifactStore(tmp_path / "artifacts") as store:
        reference = store.put_blob(
            canonical,
            kind="validation_project_dependency_preflight_receipt",
            retention_class="checkpoint",
            media_type="application/json",
        )
        projection = project_dependency_preflight_for_event(
            receipt,
            full_receipt_reference=reference.to_dict(),
        )

        assert projection["schema"] == (
            PROJECT_DEPENDENCY_PREFLIGHT_EVENT_PROJECTION_SCHEMA
        )
        assert projection["receipt_schema"] == (
            PROJECT_DEPENDENCY_PREFLIGHT_SCHEMA
        )
        assert projection["receipt_id"] == receipt["receipt_id"]
        assert projection["retry_fingerprint"] == receipt["retry_fingerprint"]
        assert projection["completion_authority"] is False
        assert projection["full_receipt_artifact"] == reference.to_dict()
        assert "inline_receipt" not in projection
        assert store.read_blob(reference) == canonical


def test_dependency_preflight_event_projection_rejects_forged_identity_or_reference(
    tmp_path,
) -> None:
    receipt = project_dependency_preflight_error_receipt(
        tmp_path,
        ["python -m pytest -q"],
        RuntimeError("fixture failure"),
    )
    forged = dict(receipt)
    forged["receipt_id"] = "0" * 64

    with pytest.raises(ValueError, match="receipt identity mismatch"):
        canonical_project_dependency_preflight_receipt_bytes(forged)

    canonical = canonical_project_dependency_preflight_receipt_bytes(receipt)
    with BoundedArtifactStore(tmp_path / "artifacts") as store:
        reference = store.put_blob(
            canonical,
            kind="validation_project_dependency_preflight_receipt",
        ).to_dict()
        reference["size_bytes"] += 1
        with pytest.raises(ValueError, match="does not bind the receipt"):
            project_dependency_preflight_for_event(
                receipt,
                full_receipt_reference=reference,
            )


def test_dependency_preflight_event_projection_requires_artifact_for_oversized_receipt(
    tmp_path,
) -> None:
    receipt = project_dependency_preflight_error_receipt(
        tmp_path,
        ["python -m pytest -q"],
        RuntimeError("fixture failure"),
    )
    receipt["probe"] = {
        "projects": [
            {
                "marker_skipped": [
                    {
                        "name": f"distribution-{index}",
                        "marker": "x" * 512,
                    }
                    for index in range(256)
                ],
                "observed": [],
            }
        ]
    }
    _reseal_dependency_preflight_receipt(receipt)
    canonical = canonical_project_dependency_preflight_receipt_bytes(receipt)
    assert len(canonical) > MAX_PREFLIGHT_INLINE_RECEIPT_BYTES

    with pytest.raises(ValueError, match="requires an artifact reference"):
        project_dependency_preflight_for_event(
            receipt,
            full_receipt_reference=None,
        )

    with BoundedArtifactStore(tmp_path / "artifacts") as store:
        reference = store.put_blob(
            canonical,
            kind="validation_project_dependency_preflight_receipt",
        )
        projection = project_dependency_preflight_for_event(
            receipt,
            full_receipt_reference=reference.to_dict(),
        )

    assert projection["marker_skipped_count"] == 256
    assert "inline_receipt" not in projection
    assert len(
        json.dumps(projection, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ) < MAX_PREFLIGHT_INLINE_RECEIPT_BYTES


def test_dependency_preflight_module_cold_imports_without_artifact_or_provider_modules() -> None:
    script = """
import json
import sys
import ipfs_accelerate_py.agent_supervisor.validation.project_dependency_preflight

names = (
    "openai",
    "anthropic",
    "transformers",
    "ipfs_accelerate_py.agent_supervisor.runtime.artifact_store",
    "ipfs_accelerate_py.agent_supervisor.self_improvement.supervisor_v2_contracts",
)
print(json.dumps({name: name in sys.modules for name in names}, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert set(json.loads(completed.stdout).values()) == {False}
