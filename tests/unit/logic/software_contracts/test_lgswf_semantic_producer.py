"""LGSWF-003 producer readiness: scan, contract bindings, no operational fields."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import (
    scan_repository_state,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state import capsules
from ipfs_datasets_py.logic.software_contracts.semantic_state import contract_bindings


def test_cold_and_incremental_roots_match(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "def answer(value: int) -> int:\n    return value\n",
        encoding="utf-8",
    )
    first = scan_repository_state(tmp_path, repository_id="repo:lgswf-003")
    second = scan_repository_state(
        tmp_path, repository_id="repo:lgswf-003", previous_state=first
    )
    assert first.state_cid == second.state_cid


def test_syntax_and_empty_namespace_fail_safely(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "empty.py").write_text("", encoding="utf-8")
    state = scan_repository_state(tmp_path, repository_id="repo:lgswf-003")
    kinds = {item.kind for item in state.artifacts}
    assert "python-analysis" in kinds


def test_contract_bindings_are_datasets_owned_and_non_operational() -> None:
    assert contract_bindings.OPERATIONAL_FIELDS_FORBIDDEN
    assert "lease_id" in contract_bindings.OPERATIONAL_FIELDS_FORBIDDEN
    assert hasattr(contract_bindings, "relevant_binding_projection_for_symbol")
    assert hasattr(capsules, "SEMANTIC_CAPSULE_COMPILER_INTERFACE")
    assert capsules.SEMANTIC_CAPSULE_COMPILER_INTERFACE == "SemanticCapsuleCompiler@1"


def test_adversarial_assurance_stays_unavailable() -> None:
    root = Path(__file__).resolve().parents[4]
    missing = (
        root
        / "ipfs_datasets_py"
        / "logic"
        / "software_contracts"
        / "adversarial_assurance"
    )
    assert not missing.exists()
