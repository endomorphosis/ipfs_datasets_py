from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.backends.protocol_v1_adapter import (
    classify_v1_operation,
)
from ipfs_datasets_py.logic.backends.protocol_v2 import (
    CapabilityRequestV2,
    ProveCheckRequestV2,
)
from ipfs_datasets_py.logic.ir_core.axes import (
    LOGIC_AXIS_SCHEMA_VERSION,
    LOGIC_OPERATION_STATUS_GENERATION,
    LogicOperationStatus,
)

DATASETS_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_PATH = DATASETS_ROOT / "docs/architecture/external_agent_fabric_reconciliation.json"
UI_IR_CONTRACT = DATASETS_ROOT / "docs/architecture/UI_UX_IR_CONTRACT.md"
LPC_AXES = DATASETS_ROOT / "ipfs_datasets_py/logic/ir_core/axes.py"
LPC_V2 = DATASETS_ROOT / "ipfs_datasets_py/logic/backends/protocol_v2.py"
LPC_V1_ADAPTER = DATASETS_ROOT / "ipfs_datasets_py/logic/backends/protocol_v1_adapter.py"


def _receipt() -> dict:
    payload = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == "ExternalAgentDatasetsReconciliation@1"
    return payload


def test_ui_ux_ir_merge_is_provenance_preserving_two_parent() -> None:
    receipt = _receipt()
    merge = receipt["ui_ux_ir_merge"]
    assert merge["classification"] == "content_integrated_without_ancestry"
    assert merge["two_parent_merge"] == receipt["integration_root"]["commit"]
    assert len(merge["parents"]) == 2
    assert merge["parents"][0] == "480a1666f144ad606fcb3cacb66e59775f28d0d1"
    assert merge["parents"][1] == "9d558ad706e83a944bbf3b66508f969041cc9518"
    assert merge["conflicting_code_paths"] == 2
    assert "current LPC API and registry semantics retained" in merge["disposition"]
    assert UI_IR_CONTRACT.is_file()
    contract = UI_IR_CONTRACT.read_text(encoding="utf-8")
    assert "UI" in contract and "IR" in contract


def test_current_lpc_api_semantics_are_retained() -> None:
    receipt = _receipt()
    surfaces = receipt["retained_lpc_surfaces"]
    assert surfaces["logic_axis_schema"] == "logic-axis/v1"
    assert surfaces["logic_provider_protocol"] == "LogicProviderProtocol@2"
    assert surfaces["v1_adapter"] == "LPC-051"
    assert LOGIC_AXIS_SCHEMA_VERSION == "logic-axis/v1"
    assert LOGIC_OPERATION_STATUS_GENERATION == "LogicOperationStatus@1"
    assert LogicOperationStatus is not None
    assert CapabilityRequestV2 is not None
    assert ProveCheckRequestV2 is not None
    assert callable(classify_v1_operation)
    for relative in surfaces["paths"]:
        assert (DATASETS_ROOT / relative).is_file()
    v2_text = LPC_V2.read_text(encoding="utf-8")
    adapter_text = LPC_V1_ADAPTER.read_text(encoding="utf-8")
    axes_text = LPC_AXES.read_text(encoding="utf-8")
    assert "LogicProviderProtocol@2" in v2_text
    assert "LPC-051" in adapter_text
    assert "must never be reused as" in axes_text


def test_proof_reuse_and_semantic_contract_residuals_are_classified() -> None:
    receipt = _receipt()
    proof = receipt["proof_reuse_residual"]
    assert proof["classification"] == "stale_proof_reuse_restoration"
    assert proof["safe_to_cherry_pick"] is False
    assert "never blind cherry-pick" in proof["disposition"]
    residuals = receipt["semantic_contract_residuals"]
    classes = {item["classification"] for item in residuals}
    assert "isolated_two_file_semantic_contract_candidate" in classes
    assert "alternate_conflict_heavy_snapshot" in classes
    wholesale = next(
        item
        for item in residuals
        if item["classification"] == "alternate_conflict_heavy_snapshot"
    )
    assert wholesale["add_add_conflicts"] == 23
    assert "do not merge wholesale" in wholesale["disposition"]


def test_wholesale_stale_snapshots_are_rejected() -> None:
    receipt = _receipt()
    rule = receipt["wholesale_stale_snapshots"]
    assert rule["rejected"] is True
    assert "never merge" in rule["rule"]
    assert "wholesale" in rule["rule"]
