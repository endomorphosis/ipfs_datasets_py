"""Dataset-neutral legal edge-authority packaging for query adapters.

The four legal query surfaces retain their public graph enums and exception
types.  This module owns only their shared classification, collision, and
result-packaging mechanics; dataset vocabulary and explanatory text arrive
through immutable bindings.

This module performs no I/O and authorizes no publication or upload.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False

SIMILARITY_NOTES_BM25_EMBEDDING_CORRECTION: Final = (
    "Similarity edges (BM25_NEIGHBOR_OF, SIMILAR_TO, "
    "EMBEDDING_NEIGHBOR_OF) are retrieval hints only. They must "
    "never be labeled as legal citation, authority, correction, or "
    "proof. BM25 neighbors are not legal authority."
)
SIMILARITY_NOTES_BM25_EMBEDDING_AMENDMENT: Final = (
    "Similarity edges (BM25_NEIGHBOR_OF, SIMILAR_TO, "
    "EMBEDDING_NEIGHBOR_OF) are retrieval hints only. They must "
    "never be labeled as legal citation, authority, amendment, or "
    "proof."
)
SIMILARITY_NOTES_BM25_AMENDMENT: Final = (
    "Similarity edges (BM25_NEIGHBOR_OF, SIMILAR_TO) are retrieval "
    "hints only. They must never be labeled as legal citation, "
    "authority, amendment, or proof."
)

_NO_OVERLAY: Final = object()
_LEGAL_AUTHORITY_CLAIMS: Final = frozenset(
    {"authoritative", "authority", "citation", "legal"}
)
_LEGAL_EDGE_CLASS_CLAIMS: Final = frozenset(
    {"authority", "citation", "provenance", "structural"}
)


@dataclass(frozen=True, slots=True)
class LegalQueryAuthorityBindings:
    """Dataset enum, error, and wording bindings for the shared mechanics."""

    edge_type: type
    edge_class: type
    default_edge_class: Mapping[Any, Any]
    legal_edge_types: frozenset[Any]
    similarity_edge_types: frozenset[Any]
    legal_edge_type_names: frozenset[str]
    similarity_edge_type_names: frozenset[str]
    input_error: type[Exception]
    collision_error: type[Exception]
    coerce_errors: tuple[type[BaseException], ...]
    authority_legal: str
    authority_non_authoritative: str
    similarity_proof_authority: bool
    similarity_notes: str
    overlay_edge_type: Any = _NO_OVERLAY

    def __post_init__(self) -> None:
        if not self.coerce_errors or not all(
            isinstance(item, type) and issubclass(item, BaseException)
            for item in self.coerce_errors
        ):
            raise TypeError("coerce_errors must contain exception types")
        if self.legal_edge_types & self.similarity_edge_types:
            raise ValueError("legal and similarity edge types must not overlap")

    @property
    def proof_edge_classes(self) -> frozenset[Any]:
        return frozenset(
            {
                self.edge_class.AUTHORITY,
                self.edge_class.CITATION,
                self.edge_class.STRUCTURAL,
            }
        )


def _normalized_edge_type_name(value: Any) -> str:
    return str(value).strip().upper().replace("-", "_")


def edge_class_for_type(
    edge_type: Any,
    *,
    bindings: LegalQueryAuthorityBindings,
) -> Any:
    """Return the dataset enum's sealed class, defaulting unknowns safely."""

    if isinstance(edge_type, bindings.edge_type):
        edge = edge_type
    else:
        text = _normalized_edge_type_name(edge_type or "")
        try:
            edge = bindings.edge_type.coerce(text)
        except bindings.coerce_errors:
            return bindings.edge_class.SIMILARITY
    return bindings.default_edge_class.get(edge, bindings.edge_class.SIMILARITY)


def is_similarity_edge_type(
    edge_type: Any,
    *,
    bindings: LegalQueryAuthorityBindings,
) -> bool:
    """Return whether the dataset type is a retrieval-only similarity edge."""

    if edge_type is None:
        return False
    if isinstance(edge_type, bindings.edge_type):
        return edge_type in bindings.similarity_edge_types
    text = _normalized_edge_type_name(edge_type)
    return text in bindings.similarity_edge_type_names or text in {
        item.name for item in bindings.similarity_edge_types
    }


def is_legal_edge_type(
    edge_type: Any,
    *,
    bindings: LegalQueryAuthorityBindings,
) -> bool:
    """Return whether the dataset type is a legal or provenance edge."""

    if edge_type is None:
        return False
    if isinstance(edge_type, bindings.edge_type):
        return edge_type in bindings.legal_edge_types
    text = _normalized_edge_type_name(edge_type)
    return text in bindings.legal_edge_type_names or text in {
        item.name for item in bindings.legal_edge_types
    }


def classify_edge_authority(
    edge_type: Any,
    *,
    bindings: LegalQueryAuthorityBindings,
) -> dict[str, Any]:
    """Package sealed authority fields; unknowns fail soft to retrieval-only."""

    if is_similarity_edge_type(edge_type, bindings=bindings):
        return {
            "authority": bindings.authority_non_authoritative,
            "edge_class": bindings.edge_class.SIMILARITY.value,
            "edge_type": (
                edge_type.value
                if isinstance(edge_type, bindings.edge_type)
                else str(edge_type or "")
            ),
            "legal_authority": False,
            "proof_authority": bool(bindings.similarity_proof_authority),
            "retrieval_hint": True,
        }
    if is_legal_edge_type(edge_type, bindings=bindings):
        edge_class = edge_class_for_type(edge_type, bindings=bindings)
        return {
            "authority": bindings.authority_legal,
            "edge_class": edge_class.value,
            "edge_type": (
                edge_type.value
                if isinstance(edge_type, bindings.edge_type)
                else str(edge_type or "")
            ),
            "legal_authority": True,
            "proof_authority": edge_class in bindings.proof_edge_classes,
            "retrieval_hint": False,
        }
    return {
        "authority": bindings.authority_non_authoritative,
        "edge_class": bindings.edge_class.SIMILARITY.value,
        "edge_type": str(edge_type or ""),
        "legal_authority": False,
        "proof_authority": False,
        "retrieval_hint": True,
    }


def annotate_edge_authority(
    edge: Mapping[str, Any],
    *,
    bindings: LegalQueryAuthorityBindings,
) -> dict[str, Any]:
    """Copy an edge, reject authority collisions, and seal its classification."""

    if not isinstance(edge, Mapping):
        raise bindings.input_error("edge must be a mapping")
    row = dict(edge)
    edge_type = row.get("edge_type") or row.get("relationship_type") or ""
    classification = classify_edge_authority(str(edge_type), bindings=bindings)
    if is_similarity_edge_type(str(edge_type), bindings=bindings):
        claimed_legal = row.get("legal_authority")
        claimed_authority = str(row.get("authority") or "").strip().lower()
        claimed_proof = row.get("proof_authority")
        if claimed_legal is True or claimed_proof is True:
            raise bindings.collision_error(
                f"similarity edge {edge_type!r} cannot claim legal/proof authority"
            )
        if claimed_authority in _LEGAL_AUTHORITY_CLAIMS:
            raise bindings.collision_error(
                f"similarity edge {edge_type!r} cannot use authority="
                f"{claimed_authority!r}"
            )
        claimed_edge_class = str(row.get("edge_class") or "").strip().lower()
        if claimed_edge_class in _LEGAL_EDGE_CLASS_CLAIMS:
            raise bindings.collision_error(
                f"similarity edge {edge_type!r} cannot use legal edge_class="
                f"{row.get('edge_class')!r}"
            )
    row.update(classification)
    return row


def assert_no_similarity_as_legal_authority(
    edges: Sequence[Mapping[str, Any]],
    *,
    bindings: LegalQueryAuthorityBindings,
) -> None:
    """Fail closed when any packaged similarity edge claims authority."""

    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        annotated = annotate_edge_authority(edge, bindings=bindings)
        if is_similarity_edge_type(
            str(annotated.get("edge_type") or ""),
            bindings=bindings,
        ):
            if annotated.get("legal_authority") is not False:
                raise bindings.collision_error(
                    "similarity edge presented as legal authority"
                )
            if annotated.get("proof_authority") is not False:
                raise bindings.collision_error(
                    "similarity edge presented as proof authority"
                )
            if (
                annotated.get("authority")
                != bindings.authority_non_authoritative
            ):
                raise bindings.collision_error(
                    "similarity edge must be non_authoritative"
                )


def similarity_edge_semantics(
    *,
    bindings: LegalQueryAuthorityBindings,
) -> dict[str, Any]:
    """Return the dataset's byte-stable retrieval-only semantics package."""

    payload = {
        "authority": bindings.authority_non_authoritative,
        "edge_class": bindings.edge_class.SIMILARITY.value,
        "edge_types": sorted(bindings.similarity_edge_type_names),
        "legal_authority": False,
        "notes": bindings.similarity_notes,
    }
    if bindings.overlay_edge_type is not _NO_OVERLAY:
        payload["overlay_edge_type"] = bindings.overlay_edge_type
    payload.update(
        {
            "proof_authority": False,
            "retrieval_hint": True,
        }
    )
    return payload


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "PERFORMS_NETWORK_IO",
    "SIMILARITY_NOTES_BM25_AMENDMENT",
    "SIMILARITY_NOTES_BM25_EMBEDDING_AMENDMENT",
    "SIMILARITY_NOTES_BM25_EMBEDDING_CORRECTION",
    "LegalQueryAuthorityBindings",
    "annotate_edge_authority",
    "assert_no_similarity_as_legal_authority",
    "classify_edge_authority",
    "edge_class_for_type",
    "is_legal_edge_type",
    "is_similarity_edge_type",
    "similarity_edge_semantics",
]
