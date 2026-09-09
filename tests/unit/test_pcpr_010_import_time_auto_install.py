"""PCPR-010: Datasets import-time auto-install removal."""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.assurance.import_time_auto_install import (
    CLOSED_RELEASE_OUTCOMES,
    CURRENT_HEAD_NON_PROMOTION_VERDICT_CID,
    HERMETIC_CANDIDATE_SUITES,
    INTERFACE,
    ImportTimeAutoInstallError,
    PCPR_010_GOAL_ID,
    PCPR_010_TASK_ID,
    current_head_static_probes,
    discover_datasets_root,
    pcpr_010_receipt_promotion,
    probe_cold_import,
    qualify_current_head_import_time_auto_install,
    qualify_import_time_auto_install_removal,
)
from ipfs_datasets_py.ipfs_backend_router import _auto_install_enabled


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_closed_vocabularies_match_pcpr_010_requirements() -> None:
    assert PCPR_010_TASK_ID == "PCPR-010"
    assert PCPR_010_GOAL_ID == "PCPR-G210"
    assert INTERFACE == "DatasetsImportTimeAutoInstallRemoval@1"
    assert "release_candidate_qualified" in CLOSED_RELEASE_OUTCOMES
    assert "rnd_non_promoted" not in CLOSED_RELEASE_OUTCOMES
    assert HERMETIC_CANDIDATE_SUITES[-1].endswith(
        "test_pcpr_010_import_time_auto_install.py"
    )


def test_current_head_is_rnd_non_promoted_and_not_a_release() -> None:
    verdict = qualify_current_head_import_time_auto_install()
    assert verdict.promotion_status == "rnd_non_promoted"
    assert verdict.supervisor_disposition == "supervisor_non_promoted"
    assert verdict.closed_release_outcome is None
    assert verdict.release_claim is False
    assert verdict.completion_authoritative is False
    assert verdict.contracts_frozen is False
    assert verdict.duckdb_or_quack_state_written is False
    assert verdict.import_sets_auto_install_env is False
    assert verdict.import_constructs_installer is False
    assert verdict.import_invokes_repo_installer is False
    assert verdict.router_defaults_auto_install_on is False
    assert verdict.simulated_results_represented_as_live is False
    assert verdict.live_solver_qualified is False
    assert verdict.live_solver_evidence_kind == "unavailable"
    assert verdict.this_task_created_competing_authority is False
    assert verdict.promotion_status not in CLOSED_RELEASE_OUTCOMES
    assert verdict.verdict_cid.startswith("baguqeera")
    assert verdict.verdict_cid == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID
    assert verdict.blockers == ()
    section = pcpr_010_receipt_promotion(verdict)
    assert section["promotion_status"] == "rnd_non_promoted"
    assert section["closed_release_outcome"] is None
    assert section["release_claim"] is False
    assert section["live_solver_qualified"] is False
    assert section["verdict_cid"] == CURRENT_HEAD_NON_PROMOTION_VERDICT_CID


def test_static_probes_show_import_time_auto_install_removed() -> None:
    probes = {item.probe_id: item for item in current_head_static_probes()}
    assert probes["package_init_enable_default_auto_install_call"].present is False
    assert probes["package_init_enable_default_auto_install_env_write"].present is False
    assert probes["package_init_get_installer_call"].present is False
    assert probes["package_init_ensure_repo_installer_current_call"].present is False
    assert probes["router_auto_install_default"].present is False
    assert probes["auto_installer_module_level_construction"].present is False
    assert probes["live_solver_qualification"].evidence_kind == "unavailable"
    assert probes["live_solver_qualification"].present is None
    assert probes["live_solver_qualification"].live is False


def test_package_init_source_has_no_module_level_installer_construction() -> None:
    source = (_PACKAGE_ROOT / "ipfs_datasets_py" / "__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    forbidden = {"get_installer", "ensure_repo_installer_current"}
    found: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._function_depth = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self._function_depth += 1
            self.generic_visit(node)
            self._function_depth -= 1

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self._function_depth += 1
            self.generic_visit(node)
            self._function_depth -= 1

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            self._function_depth += 1
            self.generic_visit(node)
            self._function_depth -= 1

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            if self._function_depth == 0:
                func = node.func
                name = func.id if isinstance(func, ast.Name) else None
                if name in forbidden:
                    found.add(name)
            self.generic_visit(node)

    _Visitor().visit(tree)
    assert found == set()
    assert "IPFS_DATASETS_AUTO_INSTALL\"] = \"true\"" not in source
    assert "IPFS_KIT_AUTO_INSTALL_DEPS\"] = \"1\"" not in source


def test_router_auto_install_is_fail_closed_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_AUTO_INSTALL", raising=False)
    monkeypatch.delenv("IPFS_AUTO_INSTALL", raising=False)
    assert _auto_install_enabled() is False
    monkeypatch.setenv("IPFS_DATASETS_AUTO_INSTALL", "true")
    assert _auto_install_enabled() is True


def test_cold_import_is_inert_without_fan_in() -> None:
    observation = probe_cold_import(datasets_root=_PACKAGE_ROOT)
    assert observation["status"] == "observed", observation
    assert observation["evidence_kind"] == "measured"
    assert observation["live"] is False
    assert observation["simulated_represented_as_live"] is False
    assert observation["inert"] is True, observation
    assert observation["auto_install"] is False
    assert observation["env_mutated"] is False
    assert observation["after_env"]["IPFS_DATASETS_AUTO_INSTALL"] is None
    assert observation["after_env"]["IPFS_KIT_AUTO_INSTALL_DEPS"] is None
    assert observation["path_delta"] == []
    assert observation["network_effects"] == []
    assert observation["subprocess_effects"] == []
    assert observation["installer_mkdir"] == []
    assert observation["missing_optional_module"] is None
    assert observation["inert_installer"] == "_InertInstaller"


def test_package_root_ensure_module_does_not_install() -> None:
    root = discover_datasets_root()
    assert root is not None
    # Import in this process after tests may already have loaded the package.
    import ipfs_datasets_py

    missing = ipfs_datasets_py.ensure_module(
        "pcpr010_definitely_missing_module", required=False
    )
    assert missing is None
    present = ipfs_datasets_py.ensure_module("json", required=False)
    assert present is sys.modules["json"]
    with pytest.raises(ImportError, match="explicit CLI or operator action"):
        ipfs_datasets_py.ensure_module(
            "pcpr010_definitely_missing_module", required=True
        )
    installer = ipfs_datasets_py.installer
    assert installer.auto_install is False
    assert type(installer).__name__ == "_InertInstaller"


def test_simulated_live_probe_is_rejected() -> None:
    from ipfs_datasets_py.assurance.import_time_auto_install import ImportProbe

    with pytest.raises(ImportTimeAutoInstallError, match="simulated"):
        qualify_import_time_auto_install_removal(
            (
                ImportProbe(
                    probe_id="bogus",
                    present=False,
                    evidence_kind="simulated",
                    live=False,
                    simulated_represented_as_live=True,
                    reason="must fail",
                ),
            )
        )


def test_enable_default_auto_install_is_noop(monkeypatch) -> None:
    import ipfs_datasets_py

    monkeypatch.delenv("IPFS_DATASETS_AUTO_INSTALL", raising=False)
    monkeypatch.delenv("IPFS_KIT_AUTO_INSTALL_DEPS", raising=False)
    ipfs_datasets_py._enable_default_auto_install()
    assert os.environ.get("IPFS_DATASETS_AUTO_INSTALL") is None
    assert os.environ.get("IPFS_KIT_AUTO_INSTALL_DEPS") is None
