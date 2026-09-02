"""Fail-closed PCPR-043 Datasets binding to cross-repository compatibility.

Datasets owns SupervisorContextPack and SemanticArtifactIdentity. This
module binds the PCPR-043 compatibility document CID published by the
Accelerate-owned checker and refuses reminting. It does not import
sibling Accelerate or Kit packages and does not re-encode identities.

This module is not a freeze, not the signed portfolio lock (PCPR-056),
not a closed PCPR release, and it never writes DuckDB or Quack state.
Live solvers stay typed unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

INTERFACE: Final = "DatasetsCrossRepositoryCompatibilityBinding@1"
SCHEMA: Final = (
    "ipfs_datasets_py/assurance/cross-repository-compatibility-binding@1"
)
NORMATIVE_SOURCE: Final = (
    "ipfs_accelerate_py/assurance/cross-repository-compatibility@1"
)
NORMATIVE_INTERFACE: Final = "CrossRepositoryCompatibility@1"
PCPR_043_TASK_ID: Final = "PCPR-043"
PCPR_043_GOAL_ID: Final = "PCPR-G520"
PCPR_042_TASK_ID: Final = "PCPR-042"
PCPR_041_TASK_ID: Final = "PCPR-041"
PCPR_040_TASK_ID: Final = "PCPR-040"
PCPR_002_TASK_ID: Final = "PCPR-002"
PCPR_056_TASK_ID: Final = "PCPR-056"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"

DATASETS_OWNED_CONTRACTS: Final[tuple[str, ...]] = (
    "SupervisorContextPack",
    "SemanticArtifactIdentity",
)
REQUIRED_REPOSITORIES: Final[tuple[str, ...]] = (
    "ipfs_accelerate_py",
    "ipfs_datasets_py",
    "ipfs_kit_py",
)
INCOMPATIBLE_CATEGORIES: Final[tuple[str, ...]] = (
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
SUPPORTED_LANGUAGES: Final[tuple[str, ...]] = ("Python", "JavaScript")
SUPPORTED_COMBINATION_ID: Final = (
    "pcpr.v1.python312.accelerate-datasets-kit.shared-contracts-v1"
)
PYTHON_FLOOR: Final = "3.12"

PINNED_CATALOG_CID: Final = (
    "baguqeeraqpptps2gf55wmthv3sm5nzlxqqdjfyg2ggkbl5ovfzuvvvsxap4a"
)
PINNED_041_VECTOR_DOCUMENT_CID: Final = (
    "baguqeera6gwcyi3f7fkw5eufnhkovmqw7eevkeas4qxds5ws7b7rloic63da"
)
PINNED_042_NEGATIVE_DOCUMENT_CID: Final = (
    "baguqeeraior5lq3fvefhgwsm3cjjaxozffmdmqmszwxy4ozfb37mnqx6lfca"
)
PINNED_COMPATIBILITY_DOCUMENT_CID: Final = (
    "baguqeerafnibnbrsfaqvbxx444kqk3gi4sh244r7bl7usdxk2krg6njlquza"
)

OWNED_VECTOR_CIDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "SupervisorContextPack": (
            "baguqeerajw2hkfnenwv44trg6yova47zknqj73ja5nv4foyunaidtmr3jzoq"
        ),
        "SemanticArtifactIdentity": (
            "baguqeeragx2oegrxxqeeofl7lyggiwyifk4wcd7mitlvqidaqfz6eabnpurq"
        ),
    }
)


class DatasetsCrossRepositoryCompatibilityError(ValueError):
    """Datasets attempted to remint a compatibility identity."""


def refuse_compatibility_remint(cid: str) -> str:
    if cid != PINNED_COMPATIBILITY_DOCUMENT_CID:
        raise DatasetsCrossRepositoryCompatibilityError(
            f"compatibility document CID {cid} remints {PINNED_COMPATIBILITY_DOCUMENT_CID}"
        )
    return cid


def datasets_compatibility_binding_mapping() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "interface": INTERFACE,
        "normative_source": NORMATIVE_SOURCE,
        "normative_interface": NORMATIVE_INTERFACE,
        "task_id": PCPR_043_TASK_ID,
        "goal_id": PCPR_043_GOAL_ID,
        "negative_vector_task": PCPR_042_TASK_ID,
        "positive_vector_task": PCPR_041_TASK_ID,
        "normative_task": PCPR_040_TASK_ID,
        "owner_repository": OWNER_REPOSITORY,
        "frozen": False,
        "freeze_task": PCPR_002_TASK_ID,
        "lock_task": PCPR_056_TASK_ID,
        "lock": False,
        "catalog_cid": PINNED_CATALOG_CID,
        "vector_document_cid": PINNED_041_VECTOR_DOCUMENT_CID,
        "negative_document_cid": PINNED_042_NEGATIVE_DOCUMENT_CID,
        "compatibility_document_cid": PINNED_COMPATIBILITY_DOCUMENT_CID,
        "supported_combination_id": SUPPORTED_COMBINATION_ID,
        "owned_contracts": list(DATASETS_OWNED_CONTRACTS),
        "owned_vector_cids": dict(OWNED_VECTOR_CIDS),
        "required_repositories": list(REQUIRED_REPOSITORIES),
        "incompatible_categories": list(INCOMPATIBLE_CATEGORIES),
        "languages": list(SUPPORTED_LANGUAGES),
        "python": PYTHON_FLOOR,
        "typescript_compiler": "unavailable",
        "remint": False,
        "sibling_import": False,
        "reencode": False,
        "duckdb_or_quack_state_written": False,
    }


__all__ = (
    "DATASETS_OWNED_CONTRACTS",
    "DatasetsCrossRepositoryCompatibilityError",
    "INCOMPATIBLE_CATEGORIES",
    "INTERFACE",
    "PINNED_041_VECTOR_DOCUMENT_CID",
    "PINNED_042_NEGATIVE_DOCUMENT_CID",
    "PINNED_CATALOG_CID",
    "PINNED_COMPATIBILITY_DOCUMENT_CID",
    "REQUIRED_REPOSITORIES",
    "SCHEMA",
    "SUPPORTED_COMBINATION_ID",
    "SUPPORTED_LANGUAGES",
    "datasets_compatibility_binding_mapping",
    "refuse_compatibility_remint",
)
