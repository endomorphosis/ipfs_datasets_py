"""PCPR-040 Datasets binding to the shared-contract catalog."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.assurance.shared_contracts import (
    CONTRACT_SCHEMA_IDS,
    DATASETS_OWNED_CONTRACTS,
    DatasetsSharedContractError,
    INTERFACE,
    NORMATIVE_SOURCE,
    OWNER_SCHEMAS,
    PCPR_040_TASK_ID,
    SCHEMA,
    datasets_binding_mapping,
    refuse_remint,
)


def test_datasets_binding_pins_fourteen_identities_without_remint() -> None:
    assert PCPR_040_TASK_ID == "PCPR-040"
    assert INTERFACE == "DatasetsSharedContractBinding@1"
    assert SCHEMA == "ipfs_datasets_py/assurance/shared-contract-binding@1"
    assert NORMATIVE_SOURCE == (
        "ipfs_accelerate_py/assurance/shared-contracts-catalog@1"
    )
    assert len(CONTRACT_SCHEMA_IDS) == 14
    assert DATASETS_OWNED_CONTRACTS == (
        "SupervisorContextPack",
        "SemanticArtifactIdentity",
    )
    assert OWNER_SCHEMAS["SupervisorContextPack"] == (
        "ipfs_datasets_py/datasets-context-pack@1"
    )
    assert (
        CONTRACT_SCHEMA_IDS["SupervisorContextPack"]
        != OWNER_SCHEMAS["SupervisorContextPack"]
    )
    assert refuse_remint(
        "SupervisorContextPack",
        CONTRACT_SCHEMA_IDS["SupervisorContextPack"],
    ) == CONTRACT_SCHEMA_IDS["SupervisorContextPack"]
    with pytest.raises(DatasetsSharedContractError, match="remints"):
        refuse_remint("SupervisorContextPack", "not_yet_normative")
    payload = datasets_binding_mapping()
    assert payload["frozen"] is False
    assert payload["remint"] is False
    assert payload["sibling_import"] is False
    assert payload["duckdb_or_quack_state_written"] is False
