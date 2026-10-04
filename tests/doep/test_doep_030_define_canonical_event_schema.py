"""Independent current-tree checks for DOEP-030 canonical event semantics."""

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

from ipfs_datasets_py.logic.ir_core.schema_registry import (  # noqa: E402
    CANONICAL_EVENT_FORBIDDEN_FIELDS,
    CANONICAL_EVENT_SCHEMA_ID,
    CANONICAL_EVENT_SCHEMA_VERSION,
    CanonicalEvent,
    CanonicalEventValidationError,
    DuplicateRegistrationError,
    IRSchemaRegistry,
    canonical_event_schema,
    register_canonical_event_schema,
)

SCHEMA_PATH = DATASETS_ROOT / "ipfs_datasets_py/logic/ir_core/schema_registry.py"
OUTPUT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-030.json"
RECEIPT_PATH = DATASETS_ROOT / "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-030.json"
OWNER_RELATIVE_OUTPUTS = (
    "ipfs_datasets_py/logic/ir_core/schema_registry.py",
    "tests/doep/test_doep_030_define_canonical_event_schema.py",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/outputs/DOEP-030.json",
    "artifacts/agent_supervisor_direct_objective_event_driven_planning/receipts/DOEP-030.json",
)
BASE_REPOSITORIES = {
    "ipfs_accelerate_py": {"commit": "87715e9295626e7918f7fc8a7b1a1531ab04208f", "tree": "1c9a399cc7a599d5904e5be2ae58c6be3650cff7"},
    "ipfs_datasets_py": {"commit": "3668b8857a9aa7b1a3c847be12725b5cd057d2e7", "tree": "456e09b51d6a07a3a5873436df24054768195320"},
    "ipfs_kit_py": {"commit": "b6c65ba732733d7e33852713ba18aa3b12235668", "tree": "14da7d92e130b7ba3523d0d6741a3ef7ef1e1bc2"},
    "lift_coding": {"commit": "bb8869ed72eb7002434345d9969efee729c4f7f6", "tree": "99e85bfe584b7688ffbeff86da1e612dd6893a42"},
}
TASK_CID = "sha256:b8cf8ce01eaa5a1ac744d169ba756d37146bfaaef5a52087f005d268b92410b7"
PLAN_CID = "sha256:6c197a4b92682b3b813656123e09956846dc4f5abadf417f37fb7cc0133ddba4"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _event(**overrides: Any) -> CanonicalEvent:
    values: dict[str, Any] = {
        "event_id": "event:example-001",
        "event_type": "task.validation.completed",
        "stream_id": "task:DOEP-030",
        "causal_parent_ids": ("event:parent-001",),
        "correlation_id": "correlation:attempt-001",
        "causation_id": "causation:validation-001",
        "payload": {"outcome": "passed", "attempt": 1},
    }
    values.update(overrides)
    return CanonicalEvent(**values)


def test_declared_outputs_exist() -> None:
    for relative in OWNER_RELATIVE_OUTPUTS:
        assert (DATASETS_ROOT / relative).is_file(), relative


def test_schema_reuses_the_existing_registry() -> None:
    assert CANONICAL_EVENT_SCHEMA_ID == "ipfs_datasets_py/logic/ir-core/canonical-event@1"
    assert CANONICAL_EVENT_SCHEMA_VERSION == "canonical-event/v1"
    registry = IRSchemaRegistry()
    register_canonical_event_schema(registry)
    assert registry[CANONICAL_EVENT_SCHEMA_ID] == canonical_event_schema()
    with pytest.raises(DuplicateRegistrationError):
        register_canonical_event_schema(registry)


def test_canonical_event_has_a_closed_deterministic_wire_form() -> None:
    event = _event()
    wire = event.to_dict()
    assert wire["schema"] == CANONICAL_EVENT_SCHEMA_ID
    assert wire["causal_parent_ids"] == ["event:parent-001"]
    assert CanonicalEvent.from_dict(wire).to_dict() == wire
    assert CanonicalEvent.from_dict(wire).payload_digest == event.payload_digest


def test_event_contract_rejects_malformed_and_operational_authority_fields() -> None:
    wire = _event().to_dict()
    with pytest.raises(CanonicalEventValidationError):
        CanonicalEvent.from_dict({**wire, "lease_id": "lease:forbidden"})
    with pytest.raises(CanonicalEventValidationError):
        CanonicalEvent.from_dict({**wire, "unknown": True})
    with pytest.raises(CanonicalEventValidationError):
        _event(causal_parent_ids=("event:parent-001", "event:parent-001"))
    with pytest.raises(CanonicalEventValidationError):
        _event(causal_parent_ids=("event:example-001",))
    assert {"policy_id", "lease_id", "fencing_epoch"} <= CANONICAL_EVENT_FORBIDDEN_FIELDS


def test_output_manifest_and_candidate_receipt_bind_current_outputs() -> None:
    manifest, receipt = _load(OUTPUT_PATH), _load(RECEIPT_PATH)
    assert manifest["task_id"] == receipt["task_id"] == "DOEP-030"
    assert manifest["task_cid"] == receipt["task_cid"] == TASK_CID
    assert manifest["plan_cid"] == receipt["plan_cid"] == PLAN_CID
    assert manifest["declared_outputs"] == receipt["expected_outputs"] == list(OWNER_RELATIVE_OUTPUTS)
    assert manifest["canonical_event_contract"]["schema"] == CANONICAL_EVENT_SCHEMA_ID
    assert manifest["canonical_event_contract"]["schema_version"] == CANONICAL_EVENT_SCHEMA_VERSION
    assert manifest["canonical_event_contract"]["existing_registry"] == "IRSchemaRegistry"
    assert manifest["no_competing_subsystem_created"] is True
    assert receipt["no_competing_subsystem_created"] is True
    assert receipt["required_evidence"]["source_commit_tree_gitlinks"] == BASE_REPOSITORIES
    assert receipt["required_evidence"]["test_proof_results"]["validation_command"] == [
        "python3", "-m", "pytest", "tests/doep/test_doep_030_define_canonical_event_schema.py", "-q"
    ]
    digests = {relative: _sha256_file(DATASETS_ROOT / relative) for relative in OWNER_RELATIVE_OUTPUTS[:-1]}
    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert receipt["path_digests"] == digests
    assert receipt["required_evidence"]["changed_path_digest"] == "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
