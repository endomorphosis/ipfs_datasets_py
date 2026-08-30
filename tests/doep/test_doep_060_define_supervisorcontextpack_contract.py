"""Independent contract checks for the DOEP-060 supervisor ContextPack view."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

DATASETS_ROOT = Path(__file__).resolve().parents[2]
if str(DATASETS_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASETS_ROOT))

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes  # noqa: E402
from ipfs_datasets_py.proof_context.context_pack import (  # noqa: E402
    AUTHORITY,
    SUPERVISOR_CONTEXT_PACK_FORBIDDEN_FIELDS,
    SUPERVISOR_CONTEXT_PACK_OWNERSHIP,
    SUPERVISOR_CONTEXT_PACK_SCHEMA,
    SUPERVISOR_CONTEXT_PACK_SCHEMA_VERSION,
    ContextPackConstructionError,
    SupervisorContextPack,
    build_context_pack,
    build_supervisor_context_pack,
)
from ipfs_datasets_py.proof_context.contracts import StaleContextError  # noqa: E402

MODULE_PATH = DATASETS_ROOT / "ipfs_datasets_py" / "proof_context" / "context_pack.py"
OUTPUT_PATH = DATASETS_ROOT / "artifacts" / "agent_supervisor_direct_objective_event_driven_planning" / "outputs" / "DOEP-060.json"
RECEIPT_PATH = DATASETS_ROOT / "artifacts" / "agent_supervisor_direct_objective_event_driven_planning" / "receipts" / "DOEP-060.json"
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/proof_context/context_pack.py",
    "tests/doep/test_doep_060_define_supervisorcontextpack_contract.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-060.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-060.json",
)
BASE_REPOSITORIES = {
    "ipfs_accelerate_py": {"commit": "87715e9295626e7918f7fc8a7b1a1531ab04208f", "tree": "1c9a399cc7a599d5904e5be2ae58c6be3650cff7"},
    "ipfs_datasets_py": {"commit": "3668b8857a9aa7b1a3c847be12725b5cd057d2e7", "tree": "456e09b51d6a07a3a5873436df24054768195320"},
    "ipfs_kit_py": {"commit": "b6c65ba732733d7e33852713ba18aa3b12235668", "tree": "14da7d92e130b7ba3523d0d6741a3ef7ef1e1bc2"},
    "lift_coding": {"commit": "bb8869ed72eb7002434345d9969efee729c4f7f6", "tree": "99e85bfe584b7688ffbeff86da1e612dd6893a42"},
}
TASK_CID = "sha256:78152e7bcbcc6d26f39cb9774b073d418c96d12fc6f66fbd11b0c25d99150c80"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _kwargs(**overrides: Any) -> dict[str, Any]:
    values = {
        "repository_state_cid": _cid("repository-state"),
        "task_id": "DOEP-060",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surrounding"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "source_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "capsule_cids": (_cid("capsule"),),
    }
    values.update(overrides)
    return values


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_supervisor_pack_reuses_existing_canonical_identity() -> None:
    semantic = build_context_pack(**_kwargs())
    supervisor = build_supervisor_context_pack(**_kwargs())
    assert isinstance(supervisor, SupervisorContextPack)
    assert supervisor.pack_cid == semantic.pack_cid
    assert supervisor.semantic_pack_cid == semantic.pack_cid
    assert supervisor.repository_state_cid == semantic.repository_state_cid
    assert supervisor.required_source_cids == semantic.required_source_cids
    assert supervisor.capsule_cids == semantic.capsule_cids
    assert supervisor.expansion_required == semantic.expansion_required
    assert supervisor.producer == AUTHORITY


def test_closed_wire_contract_excludes_storage_and_admission_authority() -> None:
    payload = build_supervisor_context_pack(**_kwargs()).to_dict()
    assert payload["schema"] == SUPERVISOR_CONTEXT_PACK_SCHEMA
    assert payload["schema_version"] == SUPERVISOR_CONTEXT_PACK_SCHEMA_VERSION
    assert payload["task_id"] == "DOEP-060"
    assert set(payload).isdisjoint(SUPERVISOR_CONTEXT_PACK_FORBIDDEN_FIELDS)
    assert SUPERVISOR_CONTEXT_PACK_OWNERSHIP["canonical_semantic_identity"] == "ipfs_datasets_py"
    assert SUPERVISOR_CONTEXT_PACK_OWNERSHIP["exact_bytes_cid_storage"] == "ipfs_kit_py"
    assert SUPERVISOR_CONTEXT_PACK_OWNERSHIP["operational_admission"] == "ipfs_accelerate_py"


def test_adapter_preserves_fail_closed_freshness_checks() -> None:
    with pytest.raises(StaleContextError):
        build_supervisor_context_pack(**_kwargs(freshness="stale"))


def test_supervisor_contract_rejects_incomplete_semantic_references() -> None:
    valid = build_supervisor_context_pack(**_kwargs())
    with pytest.raises(ContextPackConstructionError):
        SupervisorContextPack(
            **{**valid.__dict__, "required_source_cids": {"target_source": _cid("x")}}
        )
    with pytest.raises(ContextPackConstructionError):
        SupervisorContextPack(**{**valid.__dict__, "task_id": ""})


def test_output_manifest_and_candidate_receipt_bind_current_outputs() -> None:
    manifest = _load(OUTPUT_PATH)
    receipt = _load(RECEIPT_PATH)
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-060"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert manifest["declared_outputs"] == receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["supervisor_context_pack_contract"]["class_name"] == "SupervisorContextPack"
    assert manifest["supervisor_context_pack_contract"]["schema"] == SUPERVISOR_CONTEXT_PACK_SCHEMA
    assert manifest["cross_repository_ownership"] == dict(SUPERVISOR_CONTEXT_PACK_OWNERSHIP)
    evidence = receipt["required_evidence"]
    assert evidence["source_commit_tree_gitlinks"] == BASE_REPOSITORIES
    assert evidence["test_proof_results"]["validation_command"] == ["python3", "-m", "pytest", "tests/doep/test_doep_060_define_supervisorcontextpack_contract.py", "-q"]
    digested = {relative: _sha256_file(DATASETS_ROOT / relative) for relative in OWNER_RELATIVE_OUTPUTS[:-1]}
    canonical = json.dumps(digested, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert evidence["changed_path_digest"] == "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert receipt["path_digests"] == digested
