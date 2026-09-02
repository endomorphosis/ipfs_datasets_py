"""PCPR-041 Datasets binding to canonical-byte and CID vectors."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.assurance.canonical_byte_cid_vectors import (
    DATASETS_OWNED_VECTORS,
    DatasetsCanonicalByteCidVectorError,
    INTERFACE,
    PINNED_CATALOG_CID,
    SCHEMA,
    VECTOR_CIDS,
    datasets_vector_binding_mapping,
    refuse_vector_remint,
)


def test_datasets_vector_binding_pins_fourteen_cids_without_remint() -> None:
    assert INTERFACE == "DatasetsCanonicalByteCidVectorBinding@1"
    assert SCHEMA == (
        "ipfs_datasets_py/assurance/canonical-byte-cid-vector-binding@1"
    )
    assert len(VECTOR_CIDS) == 14
    assert DATASETS_OWNED_VECTORS == (
        "SupervisorContextPack",
        "SemanticArtifactIdentity",
    )
    assert PINNED_CATALOG_CID.startswith("baguqeera")
    assert refuse_vector_remint(
        "SupervisorContextPack",
        VECTOR_CIDS["SupervisorContextPack"],
    ) == VECTOR_CIDS["SupervisorContextPack"]
    assert refuse_vector_remint(
        "SemanticArtifactIdentity",
        VECTOR_CIDS["SemanticArtifactIdentity"],
    ) == VECTOR_CIDS["SemanticArtifactIdentity"]
    with pytest.raises(DatasetsCanonicalByteCidVectorError, match="remints"):
        refuse_vector_remint(
            "SupervisorContextPack",
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
    payload = datasets_vector_binding_mapping()
    assert payload["frozen"] is False
    assert payload["remint"] is False
    assert payload["reencode"] is False
    assert payload["sibling_import"] is False
    assert payload["duckdb_or_quack_state_written"] is False
    assert payload["catalog_cid"] == PINNED_CATALOG_CID
    assert payload["negative_vector_task"] == "PCPR-042"
