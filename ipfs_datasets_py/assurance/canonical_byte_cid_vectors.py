"""Fail-closed PCPR-041 Datasets binding to canonical-byte and CID vectors.

Datasets owns SupervisorContextPack and SemanticArtifactIdentity. This
module binds the PCPR-041 vector CIDs published by the Accelerate-owned
catalog encoder and refuses reminting. It does not import sibling
Accelerate or Kit packages and does not re-encode canonical bytes.

This module is not a freeze, not negative or cross-language vectors, not
a closed PCPR release, and it never writes DuckDB or Quack state. Live
solvers stay typed unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

INTERFACE: Final = "DatasetsCanonicalByteCidVectorBinding@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/canonical-byte-cid-vector-binding@1"
NORMATIVE_SOURCE: Final = (
    "ipfs_accelerate_py/assurance/canonical-byte-cid-vectors@1"
)
NORMATIVE_INTERFACE: Final = "CanonicalByteCidVectors@1"
PCPR_041_TASK_ID: Final = "PCPR-041"
PCPR_041_GOAL_ID: Final = "PCPR-G510"
PCPR_040_TASK_ID: Final = "PCPR-040"
PCPR_002_TASK_ID: Final = "PCPR-002"
PCPR_042_TASK_ID: Final = "PCPR-042"
OWNER_REPOSITORY: Final = "ipfs_datasets_py"

DATASETS_OWNED_VECTORS: Final[tuple[str, ...]] = (
    "SupervisorContextPack",
    "SemanticArtifactIdentity",
)

PINNED_CATALOG_CID: Final = (
    "baguqeeraqpptps2gf55wmthv3sm5nzlxqqdjfyg2ggkbl5ovfzuvvvsxap4a"
)

VECTOR_CIDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "SupervisorObjectiveIntent": (
            "baguqeerak5dpgbfqb3y3lzidrzhctptq4czihlmihlrozcysqrwtk57luzya"
        ),
        "ObjectiveMaterializationReceipt": (
            "baguqeerafg73iznwh3di4uegoplcn6wvdleocvqw2ga76jlvfhqhwn2pe4oa"
        ),
        "SupervisorContextPack": (
            "baguqeerajw2hkfnenwv44trg6yova47zknqj73ja5nv4foyunaidtmr3jzoq"
        ),
        "SemanticArtifactIdentity": (
            "baguqeeragx2oegrxxqeeofl7lyggiwyifk4wcd7mitlvqidaqfz6eabnpurq"
        ),
        "DurableArtifactReceipt": (
            "baguqeeraigyma7xmhsrux6ofu6huqkmbahjclnwnnqs7qgvfiviifnzidz5a"
        ),
        "ProofObligation": (
            "baguqeerawigphbus6bfz36rx3sym2rx4glfe3h6ocbkiabhpmmi5kfxyf2zq"
        ),
        "ProofResult": (
            "baguqeerao55s4irzaieuijpqsnsw7hdpi3szochjkbluemjqrloswjj5bbqa"
        ),
        "ProofAdmissionDecision": (
            "baguqeerapfeauyf46dsobfradbbj3dp7m5v2ndr7ewb2lmuijd4gntt2vkea"
        ),
        "ExecutionInvocation": (
            "baguqeeral4cusw4s6vlidwgvfvndfcnikryjncau7gb7b43o2uwx3nfljpkq"
        ),
        "ExecutionReceipt": (
            "baguqeera6dmatb2hueqarvr44465a4lddoj6l7puyqckr444phr43nxe6w6a"
        ),
        "SupervisorEvent": (
            "baguqeera5mn57ji2oa56fjzgujogtlryqpzbho4yiedspdgst6bgyulliloq"
        ),
        "TaskStateTransition": (
            "baguqeeraupifx5zwkjhsfxuktg7dnkdfzva3i3bsd4mmfri4bjgwyix37tpa"
        ),
        "ReleaseComponentManifest": (
            "baguqeeraauz252uyxbcpkpggjbohdpyvdy5vpms77vlp44vw5ek56rgo6ela"
        ),
        "PortfolioCompatibilityManifest": (
            "baguqeerazqmgj3lbt6sxeuzdpu5npsk73o4dulmbfvalct4q4atjobhrd2ma"
        ),
    }
)


class DatasetsCanonicalByteCidVectorError(ValueError):
    """Datasets attempted to remint a canonical-byte or CID vector."""


def refuse_vector_remint(name: str, cid: str) -> str:
    expected = VECTOR_CIDS.get(name)
    if expected is None:
        raise DatasetsCanonicalByteCidVectorError(
            f"{name} is not a PCPR canonical-byte/CID vector"
        )
    if cid != expected:
        raise DatasetsCanonicalByteCidVectorError(
            f"{name} vector CID {cid} remints {expected}"
        )
    return expected


def datasets_vector_binding_mapping() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "interface": INTERFACE,
        "normative_source": NORMATIVE_SOURCE,
        "normative_interface": NORMATIVE_INTERFACE,
        "task_id": PCPR_041_TASK_ID,
        "goal_id": PCPR_041_GOAL_ID,
        "normative_task": PCPR_040_TASK_ID,
        "owner_repository": OWNER_REPOSITORY,
        "frozen": False,
        "freeze_task": PCPR_002_TASK_ID,
        "negative_vector_task": PCPR_042_TASK_ID,
        "catalog_cid": PINNED_CATALOG_CID,
        "owned_vectors": list(DATASETS_OWNED_VECTORS),
        "vector_cids": dict(VECTOR_CIDS),
        "remint": False,
        "sibling_import": False,
        "reencode": False,
        "duckdb_or_quack_state_written": False,
    }


__all__ = (
    "DATASETS_OWNED_VECTORS",
    "DatasetsCanonicalByteCidVectorError",
    "INTERFACE",
    "PINNED_CATALOG_CID",
    "SCHEMA",
    "VECTOR_CIDS",
    "datasets_vector_binding_mapping",
    "refuse_vector_remint",
)
