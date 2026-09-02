"""Fail-closed PCPR-042 Datasets binding to negative/cross-language vectors.

Datasets owns SupervisorContextPack and SemanticArtifactIdentity. This
module binds the PCPR-042 negative and cross-language document CID
published by the Accelerate-owned encoder and refuses reminting. It does
not import sibling Accelerate or Kit packages and does not re-encode.

This module is not a freeze, not cross-repository compatibility, not a
closed PCPR release, and it never writes DuckDB or Quack state. Live
solvers stay typed unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

INTERFACE: Final = "DatasetsNegativeCrossLanguageVectorBinding@1"
SCHEMA: Final = (
    "ipfs_datasets_py/assurance/negative-cross-language-vector-binding@1"
)
NORMATIVE_SOURCE: Final = (
    "ipfs_accelerate_py/assurance/negative-cross-language-vectors@1"
)
NORMATIVE_INTERFACE: Final = "NegativeCrossLanguageVectors@1"
PCPR_042_TASK_ID: Final = "PCPR-042"
PCPR_042_GOAL_ID: Final = "PCPR-G520"
PCPR_041_TASK_ID: Final = "PCPR-041"
PCPR_040_TASK_ID: Final = "PCPR-040"
PCPR_002_TASK_ID: Final = "PCPR-002"
PCPR_043_TASK_ID: Final = "PCPR-043"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"

DATASETS_OWNED_VECTORS: Final[tuple[str, ...]] = (
    "SupervisorContextPack",
    "SemanticArtifactIdentity",
)

NEGATIVE_CATEGORIES: Final[tuple[str, ...]] = (
    "invalid",
    "stale",
    "unknown",
    "out_of_bound",
    "reordered",
    "reminted",
    "cross_version",
)
SUPPORTED_LANGUAGES: Final[tuple[str, ...]] = ("Python", "JavaScript")

PINNED_CATALOG_CID: Final = (
    "baguqeeraqpptps2gf55wmthv3sm5nzlxqqdjfyg2ggkbl5ovfzuvvvsxap4a"
)
PINNED_VECTOR_DOCUMENT_CID: Final = (
    "baguqeeraior5lq3fvefhgwsm3cjjaxozffmdmqmszwxy4ozfb37mnqx6lfca"
)

NEGATIVE_REJECT_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "invalid.non_mapping": "invalid",
        "invalid.empty_language": "invalid",
        "invalid.bool_as_int64": "invalid",
        "stale.zero_tree": "stale",
        "stale.catalog_cid": "stale",
        "unknown.extra_field": "unknown",
        "unknown.extra_field_reordered": "unknown",
        "out_of_bound.int64": "out_of_bound",
        "out_of_bound.float": "out_of_bound",
        "out_of_bound.string": "out_of_bound",
        "out_of_bound.array": "out_of_bound",
        "out_of_bound.cidv0": "invalid",
        "reordered.nfc_key_collision": "reordered",
        "reminted.schema": "reminted",
        "reminted.interface": "reminted",
        "reminted.vector_cid": "reminted",
        "cross_version.schema_v2": "cross_version",
        "cross_version.interface_v2": "cross_version",
    }
)


class DatasetsNegativeCrossLanguageVectorError(ValueError):
    """Datasets attempted to remint a negative/cross-language vector."""


def refuse_negative_remint(cid: str) -> str:
    if cid != PINNED_VECTOR_DOCUMENT_CID:
        raise DatasetsNegativeCrossLanguageVectorError(
            f"negative/cross-language document CID {cid} remints {PINNED_VECTOR_DOCUMENT_CID}"
        )
    return cid


def datasets_negative_vector_binding_mapping() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "interface": INTERFACE,
        "normative_source": NORMATIVE_SOURCE,
        "normative_interface": NORMATIVE_INTERFACE,
        "task_id": PCPR_042_TASK_ID,
        "goal_id": PCPR_042_GOAL_ID,
        "positive_vector_task": PCPR_041_TASK_ID,
        "normative_task": PCPR_040_TASK_ID,
        "owner_repository": OWNER_REPOSITORY,
        "frozen": False,
        "freeze_task": PCPR_002_TASK_ID,
        "compatibility_task": PCPR_043_TASK_ID,
        "catalog_cid": PINNED_CATALOG_CID,
        "vector_document_cid": PINNED_VECTOR_DOCUMENT_CID,
        "owned_vectors": list(DATASETS_OWNED_VECTORS),
        "negative_categories": list(NEGATIVE_CATEGORIES),
        "languages": list(SUPPORTED_LANGUAGES),
        "typescript_compiler": "unavailable",
        "negative_reject_kinds": dict(NEGATIVE_REJECT_KINDS),
        "remint": False,
        "sibling_import": False,
        "reencode": False,
        "duckdb_or_quack_state_written": False,
    }


__all__ = (
    "DATASETS_OWNED_VECTORS",
    "DatasetsNegativeCrossLanguageVectorError",
    "INTERFACE",
    "NEGATIVE_CATEGORIES",
    "PINNED_CATALOG_CID",
    "PINNED_VECTOR_DOCUMENT_CID",
    "SCHEMA",
    "SUPPORTED_LANGUAGES",
    "datasets_negative_vector_binding_mapping",
    "refuse_negative_remint",
)
