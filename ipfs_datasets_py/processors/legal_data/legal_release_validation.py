"""Shared, record-agnostic validation for bounded legal GraphRAG releases.

Dataset schemas retain their public record classes and exception hierarchies.
This module owns only policies that are identical across legal releases and
accepts dataset callbacks where validation must raise the adapter's errors.
Physical constants and primitive capacity checks remain authoritative in
``retrieval.hf_graphrag.schema``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Set
from enum import Enum
from typing import Any, Final, Optional

from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POINTERS_PER_ROW,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_TERM_ROWS_PER_SHARD,
    MAX_VECTOR_SHARDS_PER_CENTROID,
)


class BoundKind(str, Enum):
    """Disambiguate physical storage bounds from model-token ceilings."""

    PHYSICAL_ROWS = "physical_rows"
    PHYSICAL_POINTERS = "physical_pointers"
    MODEL_TOKENS = "model_tokens"
    CENTROID_ROWS = "centroid_rows"
    CENTROID_SHARDS = "centroid_shards"


PHYSICAL_BOUND_FIELD_NAMES: Final = frozenset(
    {
        "max_rows_per_physical_shard",
        "maximum_rows_per_physical_shard",
        "max_posting_pointers_per_row",
        "maximum_posting_pointers_per_row",
        "max_adjacency_pointers_per_row",
        "maximum_adjacency_pointers_per_row",
        "max_term_rows_per_shard",
        "maximum_term_rows_per_shard",
        "max_routing_rows_per_index",
        "maximum_routing_rows_per_index",
        "max_rows_per_vector_centroid",
        "maximum_rows_per_vector_centroid",
        "max_vector_shards_per_centroid",
        "maximum_vector_shards_per_centroid",
        "rows_per_shard",
        "pointers_per_row",
        "physical_row_bound",
        "physical_pointer_bound",
    }
)

AMBIGUOUS_4096_FIELD_NAMES: Final = frozenset(
    {
        "chunk_size",
        "chunks",
        "max_chunks",
        "max_tokens",
        "max_token_window",
        "model_token_ceiling",
        "token_limit",
        "token_window",
        "window_size",
        "context_window",
        "max_context",
        "embedding_window",
        "text_window",
        "n_ctx",
        "seq_len",
        "sequence_length",
    }
)

StringValidator = Callable[..., str]
IntegerValidator = Callable[[Any, str], int]
DigestValidator = Callable[..., str]
FamilyCoercer = Callable[[Any], Any]
ErrorType = type[Exception]


def validate_bound_declaration(
    *,
    field_name: Any,
    value: Any,
    bound_kind: Any = None,
    require_non_empty_str: StringValidator,
    require_non_negative_int: IntegerValidator,
    ambiguous_error: ErrorType,
    physical_error: ErrorType,
) -> tuple[str, int, BoundKind]:
    """Validate a named bound without conflating 4,096 and token windows."""

    name = require_non_empty_str(field_name, "field_name", maximum=128).lower()
    number = require_non_negative_int(value, name)

    kind: Optional[BoundKind]
    if bound_kind is None:
        kind = None
    elif isinstance(bound_kind, BoundKind):
        kind = bound_kind
    else:
        kind = BoundKind(str(bound_kind).strip().lower())

    if name in AMBIGUOUS_4096_FIELD_NAMES:
        if number == MAX_ROWS_PER_PHYSICAL_SHARD and kind is not BoundKind.MODEL_TOKENS:
            raise ambiguous_error(
                f"field {name!r} with value {number} is ambiguous: "
                f"4,096 is the physical row/pointer bound. Use an explicit "
                f"physical field name or declare bound_kind="
                f"{BoundKind.MODEL_TOKENS.value!r}."
            )
        if kind is None:
            raise ambiguous_error(
                f"field {name!r} is ambiguous without bound_kind; "
                f"declare model_tokens vs physical_rows explicitly"
            )
        if kind is not BoundKind.MODEL_TOKENS:
            raise ambiguous_error(
                f"field {name!r} names a token/window concept but bound_kind "
                f"is {kind.value!r}"
            )
        return name, number, kind

    if name in PHYSICAL_BOUND_FIELD_NAMES:
        if kind is None:
            if "centroid" in name and "shard" in name:
                kind = BoundKind.CENTROID_SHARDS
            elif "centroid" in name:
                kind = BoundKind.CENTROID_ROWS
            elif "pointer" in name:
                kind = BoundKind.PHYSICAL_POINTERS
            else:
                kind = BoundKind.PHYSICAL_ROWS
        resolved = kind
        if resolved is BoundKind.MODEL_TOKENS:
            raise ambiguous_error(
                f"field {name!r} is a physical bound and cannot use "
                f"bound_kind={BoundKind.MODEL_TOKENS.value!r}"
            )
        if resolved is BoundKind.PHYSICAL_POINTERS:
            if number > MAX_POINTERS_PER_ROW:
                raise physical_error(
                    f"{name}={number} exceeds pointer bound {MAX_POINTERS_PER_ROW}"
                )
        elif resolved is BoundKind.CENTROID_ROWS:
            if number > MAX_ROWS_PER_VECTOR_CENTROID:
                raise physical_error(
                    f"{name}={number} exceeds centroid row bound "
                    f"{MAX_ROWS_PER_VECTOR_CENTROID}"
                )
        elif resolved is BoundKind.CENTROID_SHARDS:
            if number > MAX_VECTOR_SHARDS_PER_CENTROID:
                raise physical_error(
                    f"{name}={number} exceeds centroid shard bound "
                    f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
                )
        elif number > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise physical_error(
                f"{name}={number} exceeds physical row bound "
                f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        return name, number, resolved

    if number == MAX_ROWS_PER_PHYSICAL_SHARD and kind is None:
        raise ambiguous_error(
            f"field {name!r} with value 4096 is ambiguous without bound_kind; "
            f"name a physical bound field or declare model_tokens"
        )
    if kind is None:
        kind = BoundKind.PHYSICAL_ROWS
    return name, number, kind


def coerce_family_set(
    values: Iterable[Any],
    *,
    family_coerce: FamilyCoercer,
) -> frozenset[Any]:
    """Coerce legal artifact-family values without owning their vocabulary."""

    return frozenset(family_coerce(item) for item in values)


def validate_semantic_family_closure(
    present_families: Iterable[Any],
    *,
    family_coerce: FamilyCoercer,
    required_families: Set[Any],
    closure_error: ErrorType,
    required: Optional[Iterable[Any]] = None,
) -> dict[str, Any]:
    """Require a dataset-provided semantic-family set to be closed."""

    present = coerce_family_set(present_families, family_coerce=family_coerce)
    need = (
        coerce_family_set(required, family_coerce=family_coerce)
        if required is not None
        else frozenset(required_families)
    )
    missing = sorted(family.value for family in (need - present))
    if missing:
        raise closure_error(f"release missing required semantic families: {missing}")
    return {
        "closed": True,
        "present": sorted(family.value for family in present),
        "required": sorted(family.value for family in need),
        "missing": [],
    }


def require_source_rights_binding(
    manifest: Mapping[str, Any],
    *,
    receipt_digest: str,
    expected_receipt_path: str,
    validate_digest: DigestValidator,
    binding_error: ErrorType,
    catalog_digest: str = "",
    dataset_card_text: str = "",
) -> None:
    """Fail closed unless release metadata binds current source-rights evidence."""

    bound = str(manifest.get("source_rights_receipt_digest") or "").strip()
    expected = validate_digest(receipt_digest, name="source_rights_receipt_digest")
    if not bound:
        raise binding_error(
            "candidate manifest does not bind source_rights_receipt_digest"
        )
    if validate_digest(bound, name="manifest.source_rights_receipt_digest") != expected:
        raise binding_error(
            "candidate manifest source-rights digest does not match the receipt"
        )
    path = str(manifest.get("source_rights_receipt_path") or "").strip()
    if path and path != expected_receipt_path:
        raise binding_error(
            f"source-rights receipt path must be {expected_receipt_path}"
        )
    catalog_bound = str(manifest.get("source_rights_catalog_digest") or "").strip()
    if catalog_digest and catalog_bound and catalog_bound != catalog_digest:
        raise binding_error(
            "candidate catalog digest does not match the source-rights receipt"
        )
    if dataset_card_text and expected not in dataset_card_text:
        raise binding_error(
            "dataset card does not bind the source-rights receipt digest"
        )


def physical_bounds_policy() -> dict[str, int]:
    """Return the sealed legal-release view of shared retrieval capacities."""

    return {
        "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "max_posting_pointers_per_row": MAX_POINTERS_PER_ROW,
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_routing_rows_per_index": MAX_ROUTING_ROWS_PER_INDEX,
        "max_term_rows_per_shard": MAX_TERM_ROWS_PER_SHARD,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "default_candidate_centroids": DEFAULT_CANDIDATE_CENTROIDS,
    }


__all__ = [
    "AMBIGUOUS_4096_FIELD_NAMES",
    "BoundKind",
    "PHYSICAL_BOUND_FIELD_NAMES",
    "coerce_family_set",
    "physical_bounds_policy",
    "require_source_rights_binding",
    "validate_bound_declaration",
    "validate_semantic_family_closure",
]
