"""PCPR-042 Datasets binding to negative and cross-language vectors."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.assurance.negative_cross_language_vectors import (
    DATASETS_OWNED_VECTORS,
    DatasetsNegativeCrossLanguageVectorError,
    INTERFACE,
    NEGATIVE_CATEGORIES,
    PINNED_CATALOG_CID,
    PINNED_VECTOR_DOCUMENT_CID,
    SCHEMA,
    SUPPORTED_LANGUAGES,
    datasets_negative_vector_binding_mapping,
    refuse_negative_remint,
)


def test_datasets_negative_vector_binding_pins_document_without_remint() -> None:
    assert INTERFACE == "DatasetsNegativeCrossLanguageVectorBinding@1"
    assert SCHEMA == (
        "ipfs_datasets_py/assurance/negative-cross-language-vector-binding@1"
    )
    assert DATASETS_OWNED_VECTORS == (
        "SupervisorContextPack",
        "SemanticArtifactIdentity",
    )
    assert NEGATIVE_CATEGORIES == (
        "invalid",
        "stale",
        "unknown",
        "out_of_bound",
        "reordered",
        "reminted",
        "cross_version",
    )
    assert SUPPORTED_LANGUAGES == ("Python", "JavaScript")
    assert PINNED_CATALOG_CID.startswith("baguqeera")
    assert refuse_negative_remint(PINNED_VECTOR_DOCUMENT_CID) == PINNED_VECTOR_DOCUMENT_CID
    with pytest.raises(DatasetsNegativeCrossLanguageVectorError, match="remints"):
        refuse_negative_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
    payload = datasets_negative_vector_binding_mapping()
    assert payload["frozen"] is False
    assert payload["remint"] is False
    assert payload["reencode"] is False
    assert payload["sibling_import"] is False
    assert payload["duckdb_or_quack_state_written"] is False
    assert payload["catalog_cid"] == PINNED_CATALOG_CID
    assert payload["vector_document_cid"] == PINNED_VECTOR_DOCUMENT_CID
    assert payload["compatibility_task"] == "PCPR-043"
    assert payload["typescript_compiler"] == "unavailable"
    assert payload["languages"] == ["Python", "JavaScript"]
