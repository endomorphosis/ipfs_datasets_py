"""Tests for the ITP hammer environment/capability probe (HAMMER-002).

These tests cover:
- The probe never imports ``ipfs_datasets_py`` (it is loaded directly from
  its file path via ``importlib`` so no package import side effects can
  leak in).
- All 12 required surfaces (Lean, Coq/Rocq, Isabelle, Z3, CVC5, Vampire, E,
  TPTP, SMT-LIB, TDFOL, CEC, prover-installer) are present with the
  documented schema shape.
- Executable discovery never installs anything and, by default, only runs a
  single bounded ``--version`` probe for an executable that was already
  found; ``--no-version-probe`` / ``probe_version=False`` performs zero
  subprocess calls.
- Explicit ``unavailable_reason`` values are set whenever ``available`` is
  false, and never set when ``available`` is true.
- The CLI writes a well-formed JSON document to ``--out``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "logic" / "probe_itp_hammer_environment.py"

EXPECTED_SURFACE_IDS = {
    "lean",
    "coq",
    "isabelle",
    "z3",
    "cvc5",
    "vampire",
    "e",
    "tptp",
    "smtlib",
    "tdfol",
    "cec",
    "prover_installer",
}


def _load_probe_module():
    """Load the probe script directly from its file path.

    Using ``importlib.util.spec_from_file_location`` (rather than a dotted
    ``ipfs_datasets_py....`` import) proves the probe module is genuinely
    standalone: it does not rely on — and does not trigger — any
    ``ipfs_datasets_py`` package import machinery.
    """

    assert SCRIPT_PATH.is_file(), f"probe script missing at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("probe_itp_hammer_environment", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec so dataclasses (which look up
    # `sys.modules[cls.__module__]`) can resolve this standalone module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe_module():
    return _load_probe_module()


@pytest.fixture(scope="module")
def hermetic_report(probe_module):
    """A report built with zero subprocess calls (no version probing)."""

    return probe_module.build_environment_report(repo_root=REPO_ROOT, probe_version=False)


# ---------------------------------------------------------------------------
# Module-loading / no-side-effects
# ---------------------------------------------------------------------------


def test_probe_module_does_not_import_ipfs_datasets_py(probe_module):
    assert "ipfs_datasets_py" not in sys.modules or all(
        not name.startswith("ipfs_datasets_py") for name in getattr(probe_module, "__dict__", {})
    )
    # The module's own top-level imports must be stdlib only.
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "import ipfs_datasets_py" not in source
    assert "from ipfs_datasets_py" not in source


def test_probe_script_is_executable_as_a_module(probe_module):
    assert hasattr(probe_module, "build_environment_report")
    assert hasattr(probe_module, "main")
    assert hasattr(probe_module, "find_executable")
    assert hasattr(probe_module, "probe_executable")


# ---------------------------------------------------------------------------
# Top-level report shape
# ---------------------------------------------------------------------------


def test_report_has_expected_top_level_shape(hermetic_report):
    assert hermetic_report["schema_version"] == "itp-hammer-environment-probe/v1"
    assert isinstance(hermetic_report["generated_at"], str) and hermetic_report["generated_at"]
    assert hermetic_report["probe_options"]["install_attempted"] is False
    assert hermetic_report["probe_options"]["solver_invoked"] is False
    assert hermetic_report["probe_options"]["version_probe_enabled"] is False
    assert set(hermetic_report["surfaces"]) == EXPECTED_SURFACE_IDS


def test_summary_counts_are_consistent(hermetic_report):
    surfaces = hermetic_report["surfaces"]
    summary = hermetic_report["summary"]
    assert summary["surface_count"] == len(surfaces)
    available_count = sum(1 for s in surfaces.values() if s["available"])
    assert summary["available_count"] == available_count
    assert summary["unavailable_count"] == len(surfaces) - available_count
    assert set(summary["unavailable_surfaces"]) == {
        surface_id for surface_id, surface in surfaces.items() if not surface["available"]
    }
    assert summary["unavailable_surfaces"] == sorted(summary["unavailable_surfaces"])


# ---------------------------------------------------------------------------
# Per-surface schema and explicit unavailable-state invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface_id", sorted(EXPECTED_SURFACE_IDS))
def test_each_surface_has_required_fields(hermetic_report, surface_id):
    surface = hermetic_report["surfaces"][surface_id]
    for required_field in (
        "surface_id",
        "display_name",
        "category",
        "executables",
        "repo_modules",
        "native_proof_trace_support",
        "parser_support",
        "available",
        "unavailable_reason",
        "notes",
    ):
        assert required_field in surface, f"{surface_id} missing {required_field}"
    assert surface["surface_id"] == surface_id
    assert isinstance(surface["available"], bool)
    assert isinstance(surface["repo_modules"], list)

    for note_field in ("native_proof_trace_support", "parser_support"):
        note = surface[note_field]
        assert isinstance(note["supported"], bool)
        assert isinstance(note["mechanism"], str) and note["mechanism"]
        assert isinstance(note["evidence"], list)


@pytest.mark.parametrize("surface_id", sorted(EXPECTED_SURFACE_IDS))
def test_unavailable_reason_is_explicit_iff_unavailable(hermetic_report, surface_id):
    surface = hermetic_report["surfaces"][surface_id]
    if surface["available"]:
        assert surface["unavailable_reason"] is None
    else:
        assert isinstance(surface["unavailable_reason"], str) and surface["unavailable_reason"]


def test_isabelle_has_no_native_frontend_and_is_unavailable(hermetic_report):
    isabelle = hermetic_report["surfaces"]["isabelle"]
    assert isabelle["available"] is False
    assert "no_isabelle_bridge_or_frontend_module_in_repo" in isabelle["unavailable_reason"]
    assert isabelle["repo_modules"] == []
    assert isabelle["parser_support"]["supported"] is False


def test_repo_modules_reference_real_files_when_marked_existing(hermetic_report):
    for surface in hermetic_report["surfaces"].values():
        for module in surface["repo_modules"]:
            path = REPO_ROOT / module["path"]
            assert module["exists"] == path.is_file(), module["path"]


def test_smtlib_surface_reports_writer_only_gap(hermetic_report):
    smtlib = hermetic_report["surfaces"]["smtlib"]
    assert smtlib["parser_support"]["supported"] is False
    assert smtlib["executables"] == {}


def test_tdfol_and_cec_are_native_python_frameworks_with_no_executables(hermetic_report):
    for surface_id in ("tdfol", "cec"):
        surface = hermetic_report["surfaces"][surface_id]
        assert surface["executables"] == {}
        assert surface["available"] is True
        assert surface["native_proof_trace_support"]["supported"] is True


# ---------------------------------------------------------------------------
# Executable discovery: no install, bounded/opt-in version probing
# ---------------------------------------------------------------------------


def test_find_executable_never_installs(probe_module, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT", raising=False)
    result = probe_module.find_executable("definitely-not-a-real-prover-binary")
    assert result is None


def test_probe_executable_reports_not_found_without_subprocess_calls(probe_module, monkeypatch):
    calls = []
    monkeypatch.setattr(
        probe_module.subprocess,
        "run",
        lambda *a, **k: calls.append((a, k)) or pytest.fail("subprocess.run must not be called"),
    )
    report = probe_module.probe_executable(["definitely-not-a-real-prover-binary"])
    assert report.found is False
    assert report.version_probe_attempted is False
    assert report.version is None
    assert calls == []


def test_probe_executable_version_probe_is_bounded_and_opt_out(probe_module):
    # `python3` (or `sys.executable`) is always on PATH in the test runner
    # and safely supports `--version` with no side effects.
    executable_name = Path(sys.executable).name
    report = probe_module.probe_executable([executable_name], version_args=("--version",))
    assert report.found is True
    assert report.version_probe_attempted is True
    assert report.version_command[0] == report.resolved_path
    assert report.version

    no_probe_report = probe_module.probe_executable(
        [executable_name], version_args=("--version",), probe_version=False
    )
    assert no_probe_report.found is True
    assert no_probe_report.version_probe_attempted is False
    assert no_probe_report.version is None


def test_probe_executable_handles_timeout(probe_module, monkeypatch):
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=5)

    monkeypatch.setattr(probe_module.shutil, "which", lambda name: "/bin/true")
    monkeypatch.setattr(probe_module.subprocess, "run", _raise_timeout)
    report = probe_module.probe_executable(["true"])
    assert report.found is True
    assert report.version_probe_attempted is True
    assert report.version is None
    assert "timed out" in report.version_probe_error


def test_build_environment_report_default_probes_versions_for_found_executables(probe_module):
    report = probe_module.build_environment_report(repo_root=REPO_ROOT, probe_version=True)
    lean = report["surfaces"]["lean"]["executables"]["lean"]
    if lean["found"]:
        assert lean["version_probe_attempted"] is True
    else:
        assert lean["version_probe_attempted"] is False


# ---------------------------------------------------------------------------
# CLI behavior
# ---------------------------------------------------------------------------


def test_cli_writes_json_report(tmp_path):
    out_path = tmp_path / "environment.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--out",
            str(out_path),
            "--repo-root",
            str(REPO_ROOT),
            "--no-version-probe",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert out_path.is_file()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "itp-hammer-environment-probe/v1"
    assert set(payload["surfaces"]) == EXPECTED_SURFACE_IDS
    assert payload["probe_options"]["install_attempted"] is False
    assert payload["probe_options"]["solver_invoked"] is False

    cli_summary = json.loads(result.stdout.strip())
    assert cli_summary["surface_count"] == len(EXPECTED_SURFACE_IDS)


def test_cli_default_out_matches_taskboard_expected_output():
    # The taskboard's expected output path.
    default_out = REPO_ROOT / "data" / "logic" / "itp_hammer" / "environment.json"
    module = _load_probe_module()
    assert (module.DEFAULT_OUT).as_posix() == "data/logic/itp_hammer/environment.json"
    assert (REPO_ROOT / module.DEFAULT_OUT) == default_out
