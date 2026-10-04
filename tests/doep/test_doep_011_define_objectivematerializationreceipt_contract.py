"""Independent current-tree checks for DOEP-011 materialization receipts."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

DATASETS_ROOT = Path(__file__).resolve().parents[2]
if str(DATASETS_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASETS_ROOT))

from ipfs_datasets_py.logic.intent_ir.schema import (  # noqa: E402
    OBJECTIVE_MATERIALIZATION_RECEIPT_FORBIDDEN_FIELDS,
    OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA,
    OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION,
    IntentIRValidationError,
    ObjectiveMaterializationReceipt,
    validate_objective_materialization_receipt,
)

SCHEMA_PATH = DATASETS_ROOT / "ipfs_datasets_py" / "logic" / "intent_ir" / "schema.py"
OUTPUT_PATH = DATASETS_ROOT / "artifacts" / "agent_supervisor_direct_objective_event_driven_planning" / "outputs" / "DOEP-011.json"
RECEIPT_PATH = DATASETS_ROOT / "artifacts" / "agent_supervisor_direct_objective_event_driven_planning" / "receipts" / "DOEP-011.json"
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/intent_ir/schema.py",
    "tests/doep/test_doep_011_define_objectivematerializationreceipt_contract.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-011.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-011.json",
)
TASK_CID = "sha256:b0c8a8584f596e06818fcaa1c625f117334b19930a5d8a620590eecd29f099c0"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"
BASE_REPOSITORIES = {
    "ipfs_accelerate_py": {"commit": "87715e9295626e7918f7fc8a7b1a1531ab04208f", "tree": "1c9a399cc7a599d5904e5be2ae58c6be3650cff7"},
    "ipfs_datasets_py": {"commit": "3668b8857a9aa7b1a3c847be12725b5cd057d2e7", "tree": "456e09b51d6a07a3a5873436df24054768195320"},
    "ipfs_kit_py": {"commit": "b6c65ba732733d7e33852713ba18aa3b12235668", "tree": "14da7d92e130b7ba3523d0d6741a3ef7ef1e1bc2"},
    "lift_coding": {"commit": "bb8869ed72eb7002434345d9969efee729c4f7f6", "tree": "99e85bfe584b7688ffbeff86da1e612dd6893a42"},
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt(**overrides: Any) -> ObjectiveMaterializationReceipt:
    values: dict[str, Any] = {
        "receipt_id": "doep.objective.materialization.example",
        "intent_id": "doep.objective.intent.example",
        "intent_sha256": hashlib.sha256(b"canonical intent").hexdigest(),
        "objective_id": "doep.objective.example",
        "objective_cid": "bafybeigdyrztx4exampleobjective",
        "objective_revision_cid": "bafybeigdyrztx4exampleobjective-revision",
    }
    values.update(overrides)
    return ObjectiveMaterializationReceipt(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_closed_semantic_receipt_contract() -> None:
    receipt = _receipt()
    assert receipt.schema == OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA
    assert receipt.is_completion_authority is False
    assert OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA == (
        "ipfs_datasets_py/logic/intent-ir/objective-materialization-receipt@1"
    )
    assert OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION == "objective-materialization-receipt/v1"
    assert validate_objective_materialization_receipt(receipt) is receipt
    payload = receipt.to_dict()
    assert ObjectiveMaterializationReceipt.from_dict(payload).to_dict() == payload


def test_contract_rejects_authority_and_invalid_references() -> None:
    with pytest.raises(IntentIRValidationError):
        ObjectiveMaterializationReceipt.from_dict({**_receipt().to_dict(), "policy_id": "policy:x"})
    with pytest.raises(IntentIRValidationError):
        ObjectiveMaterializationReceipt.from_dict({**_receipt().to_dict(), "unknown": "x"})
    with pytest.raises(IntentIRValidationError):
        validate_objective_materialization_receipt(_receipt(intent_sha256="not-a-digest"))
    with pytest.raises(IntentIRValidationError):
        validate_objective_materialization_receipt(_receipt(objective_cid=""))
    fields = {field.name for field in dataclasses.fields(ObjectiveMaterializationReceipt)}
    assert fields.isdisjoint(OBJECTIVE_MATERIALIZATION_RECEIPT_FORBIDDEN_FIELDS)
    assert {"policy_id", "lease_id", "terminalize", "duckdb"} <= OBJECTIVE_MATERIALIZATION_RECEIPT_FORBIDDEN_FIELDS


def test_manifest_and_candidate_receipt_bind_current_tree() -> None:
    manifest = _load(OUTPUT_PATH)
    candidate = _load(RECEIPT_PATH)
    assert manifest["task_id"] == candidate["task_id"] == "DOEP-011"
    assert manifest["task_cid"] == candidate["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == candidate["plan_cid"] == PLAN_CID
    assert manifest["declared_outputs"] == candidate["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    contract = manifest["objective_materialization_receipt_contract"]
    assert contract == {
        "class_name": "ObjectiveMaterializationReceipt",
        "completion_authority": False,
        "module": "ipfs_datasets_py.logic.intent_ir.schema",
        "operational_admission_owner": "ipfs_accelerate_py",
        "schema": OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA,
        "schema_version": OBJECTIVE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION,
        "semantic_identity_owner": "ipfs_datasets_py",
    }
    digests = {relative: _sha256_file(DATASETS_ROOT / relative) for relative in OWNER_RELATIVE_OUTPUTS[:-1]}
    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert candidate["path_digests"] == digests
    assert candidate["required_evidence"]["changed_path_digest"] == "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert candidate["required_evidence"]["test_proof_results"]["validation_command"] == ["python3", "-m", "pytest", "tests/doep/test_doep_011_define_objectivematerializationreceipt_contract.py", "-q"]
    assert candidate["completion_authoritative"] is False
    assert candidate["worker_completion_insufficient"] is True
    assert candidate["no_competing_subsystem_created"] is True
    assert manifest["base_repositories"] == BASE_REPOSITORIES
    assert candidate["required_evidence"]["source_commit_tree_gitlinks"] == BASE_REPOSITORIES
    assert candidate["required_evidence"]["receipt_cid"]["status"] == "unavailable"
    assert manifest["cross_repository_ownership"]["exact_bytes_cid_storage"] == "ipfs_kit_py"
    assert candidate["authority"]["operational_admission"] == "ipfs_accelerate_py"
