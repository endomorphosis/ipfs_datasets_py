"""Current-tree checks for DOEP-064 incremental ContextPack expansion."""

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.proof_context.context_pack import (
    build_context_pack,
    expand_context_pack_incrementally,
)
from ipfs_datasets_py.proof_context.contracts import StaleContextError

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = (
    "ipfs_datasets_py/proof_context/context_pack.py",
    "tests/doep/test_doep_064_add_incremental_context_expansion.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-064.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-064.json",
)
TREE = "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def test_declared_outputs_exist():
    for rel in OUTPUTS:
        assert (ROOT / rel).is_file()


def test_incremental_expansion_adds_capsules_on_the_same_tree():
    base = build_context_pack(
        repository_state_cid=_cid("repo-state"),
        task_id="DOEP-064",
        target_source_cid=_cid("target"),
        surrounding_source_cid=_cid("surround"),
        test_source_cid=_cid("test"),
        scanned_tree_oid=TREE,
        source_tree_oid=TREE,
        capsule_cids=(_cid("capsule"),),
    )
    extra = _cid("capsule-2")
    expanded = expand_context_pack_incrementally(
        base,
        extra_capsule_cids=(extra,),
        scanned_tree_oid=TREE,
        prior_scanned_tree_oid=TREE,
        task_id="DOEP-064",
    )
    assert extra in expanded.capsule_cids


def test_changed_tree_is_rejected():
    base = build_context_pack(
        repository_state_cid=_cid("repo-state"),
        task_id="DOEP-064",
        target_source_cid=_cid("target"),
        surrounding_source_cid=_cid("surround"),
        test_source_cid=_cid("test"),
        scanned_tree_oid=TREE,
        source_tree_oid=TREE,
    )
    with pytest.raises(StaleContextError):
        expand_context_pack_incrementally(
            base,
            extra_capsule_cids=(_cid("capsule-2"),),
            scanned_tree_oid="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            prior_scanned_tree_oid=TREE,
            task_id="DOEP-064",
        )
