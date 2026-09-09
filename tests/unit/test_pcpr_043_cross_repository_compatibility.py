"""PCPR-043 Datasets binding to cross-repository compatibility."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.assurance.cross_repository_compatibility import (
    DATASETS_OWNED_CONTRACTS,
    DatasetsCrossRepositoryCompatibilityError,
    INCOMPATIBLE_CATEGORIES,
    INTERFACE,
    PINNED_041_VECTOR_DOCUMENT_CID,
    PINNED_042_NEGATIVE_DOCUMENT_CID,
    PINNED_CATALOG_CID,
    PINNED_COMPATIBILITY_DOCUMENT_CID,
    REQUIRED_REPOSITORIES,
    SCHEMA,
    SUPPORTED_COMBINATION_ID,
    SUPPORTED_LANGUAGES,
    datasets_compatibility_binding_mapping,
    refuse_compatibility_remint,
)


def test_datasets_compatibility_binding_pins_document_without_remint() -> None:
    assert INTERFACE == "DatasetsCrossRepositoryCompatibilityBinding@1"
    assert SCHEMA == (
        "ipfs_datasets_py/assurance/cross-repository-compatibility-binding@1"
    )
    assert DATASETS_OWNED_CONTRACTS == (
        "SupervisorContextPack",
        "SemanticArtifactIdentity",
    )
    assert REQUIRED_REPOSITORIES == (
        "ipfs_accelerate_py",
        "ipfs_datasets_py",
        "ipfs_kit_py",
    )
    assert INCOMPATIBLE_CATEGORIES == (
        "missing_repository",
        "reminted_identity",
        "sibling_import",
        "cross_version",
        "mixed_catalog_vectors",
        "partial_publication",
        "unsupported_python",
        "authority_boundary",
        "claimed_early",
    )
    assert SUPPORTED_LANGUAGES == ("Python", "JavaScript")
    assert PINNED_CATALOG_CID.startswith("baguqeera")
    assert PINNED_041_VECTOR_DOCUMENT_CID.startswith("baguqeera")
    assert PINNED_042_NEGATIVE_DOCUMENT_CID.startswith("baguqeera")
    assert (
        refuse_compatibility_remint(PINNED_COMPATIBILITY_DOCUMENT_CID)
        == PINNED_COMPATIBILITY_DOCUMENT_CID
    )
    with pytest.raises(DatasetsCrossRepositoryCompatibilityError, match="remints"):
        refuse_compatibility_remint(
            "baguqeeraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
    payload = datasets_compatibility_binding_mapping()
    assert payload["frozen"] is False
    assert payload["lock"] is False
    assert payload["remint"] is False
    assert payload["reencode"] is False
    assert payload["sibling_import"] is False
    assert payload["duckdb_or_quack_state_written"] is False
    assert payload["catalog_cid"] == PINNED_CATALOG_CID
    assert payload["vector_document_cid"] == PINNED_041_VECTOR_DOCUMENT_CID
    assert payload["negative_document_cid"] == PINNED_042_NEGATIVE_DOCUMENT_CID
    assert payload["compatibility_document_cid"] == PINNED_COMPATIBILITY_DOCUMENT_CID
    assert payload["supported_combination_id"] == SUPPORTED_COMBINATION_ID
    assert payload["python"] == "3.12"
    assert payload["typescript_compiler"] == "unavailable"
    assert payload["languages"] == ["Python", "JavaScript"]
    assert payload["lock_task"] == "PCPR-056"
