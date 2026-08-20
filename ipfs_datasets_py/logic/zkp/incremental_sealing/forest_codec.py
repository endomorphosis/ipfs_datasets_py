"""Deterministic proof-forest commitment codec and known vectors (IPS-011).

Datasets semantic authority for domain-separated Merkle forest commitments.
Leaves are sorted by canonical proof-unit ID bytes within a closed category.
Empty, leaf, unary, and binary nodes have exact encodings.  Category roots
and the repository proof root bind every normative field from the plan.

Rules:

* repeated runs produce identical roots for identical inputs;
* one-bit (single-field) changes propagate to category and repository roots;
* duplicate unit IDs, duplicate leaf positions, unknown categories, and
  caller-provided non-canonical order fail closed (never silently rewritten);
* parent seal, revision, environment, and schema fields all affect the
  final repository root.

Interfaces: ``ProofForestLeaf``, ``CategoryRoot``, ``RepositoryProofRoot``,
``compute_category_root``, ``compute_repository_root``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .identity import (
    ABSENCE_TOKEN,
    CANONICALIZATION_VERSION,
    IdentityError,
    canonical_cid,
    validate_profile_cid,
)

FOREST_CODEC_SUBSET: Final[str] = "ips/forest-codec@1"
FOREST_CODEC_VECTORS_SUBSET: Final[str] = "ips/forest-codec-vectors@1"
FOREST_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/forest_codec"
)
SCHEMA_MAJOR: Final[int] = 1
PROOF_SCHEMA_VERSION: Final[str] = str(SCHEMA_MAJOR)
TYPED_ABSENCE: Final[str] = "typed_absence"
MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_LEAVES_PER_CATEGORY: Final[int] = 1 << 20

# Domain separators bind node kinds so empty/leaf/unary/binary cannot collide.
DOMAIN_EMPTY: Final[str] = "ips.forest.empty.v1"
DOMAIN_LEAF: Final[str] = "ips.forest.leaf.v1"
DOMAIN_UNARY: Final[str] = "ips.forest.unary.v1"
DOMAIN_BINARY: Final[str] = "ips.forest.binary.v1"
DOMAIN_CATEGORY: Final[str] = "ips.forest.category.v1"
DOMAIN_REPOSITORY: Final[str] = "ips.forest.repository.v1"

# Canonical genesis parent when no accepted parent seal exists.
GENESIS_PARENT_SEAL: Final[str] = "ips.forest.genesis@1"

PROOF_FOREST_LEAF_SCHEMA: Final[str] = (
    f"{FOREST_NAMESPACE}/proof-forest-leaf@{SCHEMA_MAJOR}"
)
CATEGORY_ROOT_SCHEMA: Final[str] = (
    f"{FOREST_NAMESPACE}/category-root@{SCHEMA_MAJOR}"
)
REPOSITORY_PROOF_ROOT_SCHEMA: Final[str] = (
    f"{FOREST_NAMESPACE}/repository-proof-root@{SCHEMA_MAJOR}"
)

# Closed ordered category names (plan §7 RepositoryProofForest).
FOREST_CATEGORIES: Final[tuple[str, ...]] = (
    "source_integrity",
    "static_analysis",
    "type_check",
    "unit_test",
    "integration_test",
    "property_test",
    "formal_obligation",
    "direct_zk",
    "receipt_aggregation",
    "release_invariant",
)

# Map ProofUnitKind values onto forest categories where names differ.
_KIND_TO_CATEGORY: Final[dict[str, str]] = {
    "static_analysis": "static_analysis",
    "type_check": "type_check",
    "unit_test": "unit_test",
    "integration_test": "integration_test",
    "property_test": "property_test",
    "formal_obligation": "formal_obligation",
    "direct_zk_computation": "direct_zk",
    "direct_zk": "direct_zk",
    "receipt_aggregation": "receipt_aggregation",
    "release_invariant": "release_invariant",
    "source_integrity": "source_integrity",
}

REPOSITORY_ROOT_FIELDS: Final[tuple[str, ...]] = (
    "repository_id",
    "revision",
    "source_root_cid",
    "manifest_root_cid",
    "environment_cid",
    "policy_cid",
    "proof_schema_version",
    "canonicalization_version",
    "dependency_graph_schema_version",
    "parent_seal_cid",
    "parent_revision_ids",
    "category_roots",
)


class ForestCodecError(ValueError):
    """Proof-forest commitment contract violation."""


class ForestCategory(str, Enum):
    SOURCE_INTEGRITY = "source_integrity"
    STATIC_ANALYSIS = "static_analysis"
    TYPE_CHECK = "type_check"
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    PROPERTY_TEST = "property_test"
    FORMAL_OBLIGATION = "formal_obligation"
    DIRECT_ZK = "direct_zk"
    RECEIPT_AGGREGATION = "receipt_aggregation"
    RELEASE_INVARIANT = "release_invariant"


def closed_forest_categories() -> frozenset[str]:
    return frozenset(FOREST_CATEGORIES)


def parse_forest_category(value: Any) -> str:
    """Parse a closed forest category; map known proof-unit kinds."""

    if isinstance(value, ForestCategory):
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise ForestCodecError("category must be a non-empty closed string")
    text = value.strip()
    if text in FOREST_CATEGORIES:
        return text
    mapped = _KIND_TO_CATEGORY.get(text)
    if mapped is not None:
        return mapped
    raise ForestCodecError(
        f"unknown forest category {value!r}; closed set is {list(FOREST_CATEGORIES)}"
    )


def category_root_field_name(category: str) -> str:
    """Return the repository-payload field name for a category root."""

    return f"{parse_forest_category(category)}_root"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise ForestCodecError(f"{field} must be a non-empty string")
    text = value.strip()
    if text != value:
        raise ForestCodecError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise ForestCodecError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_cid(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    text = _require_text(value, field, allow_absence=False)
    if text == GENESIS_PARENT_SEAL:
        return GENESIS_PARENT_SEAL
    try:
        return validate_profile_cid(text, domain="any")
    except IdentityError as exc:
        raise ForestCodecError(f"{field}: {exc}") from exc


def _require_nonneg_int(value: Any, field: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise ForestCodecError(f"{field} must be a finite int")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise ForestCodecError(f"{field} is out of bounds")
    return value


def _require_sorted_unique_strings(
    value: Any, field: str, *, allow_absence: bool = True
) -> tuple[str, ...]:
    if allow_absence and value == ABSENCE_TOKEN:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ForestCodecError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(_require_text(item, field, allow_absence=False) for item in value)
    if list(items) != sorted(items):
        raise ForestCodecError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise ForestCodecError(f"{field} must not contain duplicates")
    return items


def _unit_id_sort_key(unit_id: str) -> bytes:
    """Canonical sort key: UTF-8 bytes of the proof-unit ID."""

    return unit_id.encode("utf-8")


def _node_cid(payload: Mapping[str, Any]) -> str:
    try:
        return canonical_cid(dict(payload))
    except IdentityError as exc:
        raise ForestCodecError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Domain-separated node encodings
# ---------------------------------------------------------------------------


def encode_empty_node(*, category: str) -> str:
    """Exact empty-node commitment for one closed category."""

    cat = parse_forest_category(category)
    return _node_cid(
        {
            "domain": DOMAIN_EMPTY,
            "kind": "empty",
            "category": cat,
            "schema": f"{FOREST_NAMESPACE}/empty@{SCHEMA_MAJOR}",
        }
    )


def encode_leaf_node(
    *,
    category: str,
    proof_unit_id: str,
    proof_object_cid: str,
    position: int,
) -> str:
    """Exact leaf-node commitment."""

    cat = parse_forest_category(category)
    unit_id = _require_text(proof_unit_id, "proof_unit_id")
    object_cid = _require_cid(proof_object_cid, "proof_object_cid")
    pos = _require_nonneg_int(position, "position")
    return _node_cid(
        {
            "domain": DOMAIN_LEAF,
            "kind": "leaf",
            "category": cat,
            "proof_unit_id": unit_id,
            "proof_object_cid": object_cid,
            "position": pos,
            "schema": PROOF_FOREST_LEAF_SCHEMA,
        }
    )


def encode_unary_node(*, child_cid: str) -> str:
    """Exact unary internal node (odd leftover at a level)."""

    child = _require_cid(child_cid, "child_cid")
    return _node_cid(
        {
            "domain": DOMAIN_UNARY,
            "kind": "unary",
            "child_cid": child,
            "schema": f"{FOREST_NAMESPACE}/unary@{SCHEMA_MAJOR}",
        }
    )


def encode_binary_node(*, left_cid: str, right_cid: str) -> str:
    """Exact binary internal node over ordered left/right children."""

    left = _require_cid(left_cid, "left_cid")
    right = _require_cid(right_cid, "right_cid")
    return _node_cid(
        {
            "domain": DOMAIN_BINARY,
            "kind": "binary",
            "left_cid": left,
            "right_cid": right,
            "schema": f"{FOREST_NAMESPACE}/binary@{SCHEMA_MAJOR}",
        }
    )


def _merkle_root_from_leaf_cids(leaf_cids: Sequence[str], *, category: str) -> str:
    """Fold leaf digests with explicit empty/unary/binary encodings."""

    if not leaf_cids:
        return encode_empty_node(category=category)
    level: list[str] = list(leaf_cids)
    while len(level) > 1:
        next_level: list[str] = []
        index = 0
        while index < len(level):
            if index + 1 < len(level):
                next_level.append(
                    encode_binary_node(
                        left_cid=level[index], right_cid=level[index + 1]
                    )
                )
                index += 2
            else:
                next_level.append(encode_unary_node(child_cid=level[index]))
                index += 1
        level = next_level
    return level[0]


# ---------------------------------------------------------------------------
# ProofForestLeaf
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofForestLeaf:
    """One proof-unit leaf inside a closed forest category."""

    proof_unit_id: str
    proof_object_cid: str
    category: str
    position: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proof_unit_id",
            _require_text(self.proof_unit_id, "proof_unit_id"),
        )
        object.__setattr__(
            self,
            "proof_object_cid",
            _require_cid(self.proof_object_cid, "proof_object_cid"),
        )
        object.__setattr__(
            self, "category", parse_forest_category(self.category)
        )
        object.__setattr__(
            self, "position", _require_nonneg_int(self.position, "position")
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": PROOF_FOREST_LEAF_SCHEMA,
            "proof_unit_id": self.proof_unit_id,
            "proof_object_cid": self.proof_object_cid,
            "category": self.category,
            "position": self.position,
        }

    def leaf_cid(self) -> str:
        return encode_leaf_node(
            category=self.category,
            proof_unit_id=self.proof_unit_id,
            proof_object_cid=self.proof_object_cid,
            position=self.position,
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ProofForestLeaf:
        if not isinstance(payload, Mapping):
            raise ForestCodecError("ProofForestLeaf payload must be a mapping")
        return cls(
            proof_unit_id=str(payload.get("proof_unit_id") or ""),
            proof_object_cid=str(payload.get("proof_object_cid") or ""),
            category=str(payload.get("category") or ""),
            position=payload.get("position", 0),  # type: ignore[arg-type]
        )


def _coerce_leaf(value: Any, *, expected_category: str | None = None) -> ProofForestLeaf:
    if isinstance(value, ProofForestLeaf):
        leaf = value
    elif isinstance(value, Mapping):
        leaf = ProofForestLeaf.from_canonical(value)
    else:
        raise ForestCodecError("leaf must be ProofForestLeaf or mapping")
    if expected_category is not None and leaf.category != expected_category:
        raise ForestCodecError(
            f"leaf category {leaf.category!r} does not match "
            f"expected {expected_category!r}"
        )
    return leaf


def _normalize_category_leaves(
    leaves: Sequence[Any],
    *,
    category: str,
) -> tuple[ProofForestLeaf, ...]:
    """Validate caller order and positions; never silently re-sort or rewrite."""

    cat = parse_forest_category(category)
    if not isinstance(leaves, Sequence) or isinstance(leaves, (str, bytes)):
        raise ForestCodecError("leaves must be a sequence")
    if len(leaves) > MAX_LEAVES_PER_CATEGORY:
        raise ForestCodecError(
            f"category {cat!r} exceeds {MAX_LEAVES_PER_CATEGORY} leaves"
        )

    coerced = [_coerce_leaf(item, expected_category=cat) for item in leaves]

    # Reject non-canonical (non-increasing by unit-id bytes) caller order.
    unit_ids = [leaf.proof_unit_id for leaf in coerced]
    if unit_ids != sorted(unit_ids, key=_unit_id_sort_key):
        raise ForestCodecError(
            "leaves must be provided in canonical proof-unit ID byte order"
        )
    if len(set(unit_ids)) != len(unit_ids):
        raise ForestCodecError("duplicate proof_unit_id in category leaves")

    positions = [leaf.position for leaf in coerced]
    if len(set(positions)) != len(positions):
        raise ForestCodecError("duplicate leaf positions")
    expected_positions = list(range(len(coerced)))
    if positions != expected_positions:
        raise ForestCodecError(
            "leaf positions must be contiguous 0..n-1 matching sorted order"
        )

    return tuple(coerced)


# ---------------------------------------------------------------------------
# CategoryRoot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CategoryRoot:
    """Merkle commitment for one closed forest category."""

    category: str
    leaves: tuple[ProofForestLeaf, ...]
    merkle_root: str
    root_cid: str
    leaf_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", parse_forest_category(self.category))
        if not isinstance(self.leaves, tuple):
            object.__setattr__(self, "leaves", tuple(self.leaves))
        object.__setattr__(
            self, "leaf_count", _require_nonneg_int(self.leaf_count, "leaf_count")
        )
        if self.leaf_count != len(self.leaves):
            raise ForestCodecError("leaf_count must equal len(leaves)")
        object.__setattr__(
            self, "merkle_root", _require_cid(self.merkle_root, "merkle_root")
        )
        object.__setattr__(self, "root_cid", _require_cid(self.root_cid, "root_cid"))

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": CATEGORY_ROOT_SCHEMA,
            "forest_codec_subset": FOREST_CODEC_SUBSET,
            "category": self.category,
            "leaf_count": self.leaf_count,
            "leaf_ids": [leaf.proof_unit_id for leaf in self.leaves],
            "leaves": [leaf.to_canonical() for leaf in self.leaves],
            "merkle_root": self.merkle_root,
            "root_cid": self.root_cid,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> CategoryRoot:
        if not isinstance(payload, Mapping):
            raise ForestCodecError("CategoryRoot payload must be a mapping")
        raw_leaves = payload.get("leaves", ())
        if not isinstance(raw_leaves, Sequence) or isinstance(raw_leaves, (str, bytes)):
            raise ForestCodecError("leaves must be a sequence")
        leaves = tuple(ProofForestLeaf.from_canonical(item) for item in raw_leaves)  # type: ignore[arg-type]
        return cls(
            category=str(payload.get("category") or ""),
            leaves=leaves,
            merkle_root=str(payload.get("merkle_root") or ""),
            root_cid=str(payload.get("root_cid") or ""),
            leaf_count=payload.get("leaf_count", len(leaves)),  # type: ignore[arg-type]
        )


def compute_category_root(
    category: str,
    leaves: Sequence[Any] = (),
) -> CategoryRoot:
    """Compute the exact category root for sorted leaves.

    Caller-provided leaf order must already be canonical proof-unit ID byte
    order with contiguous positions ``0..n-1``.  Empty input yields the
    domain-separated empty node for the category.
    """

    cat = parse_forest_category(category)
    normalized = _normalize_category_leaves(leaves, category=cat)
    leaf_cids = [leaf.leaf_cid() for leaf in normalized]
    merkle = _merkle_root_from_leaf_cids(leaf_cids, category=cat)
    root_cid = _node_cid(
        {
            "domain": DOMAIN_CATEGORY,
            "kind": "category",
            "category": cat,
            "leaf_count": len(normalized),
            "leaf_ids": [leaf.proof_unit_id for leaf in normalized],
            "merkle_root": merkle,
            "schema": CATEGORY_ROOT_SCHEMA,
            "forest_codec_subset": FOREST_CODEC_SUBSET,
        }
    )
    return CategoryRoot(
        category=cat,
        leaves=normalized,
        merkle_root=merkle,
        root_cid=root_cid,
        leaf_count=len(normalized),
    )


# ---------------------------------------------------------------------------
# RepositoryProofRoot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RepositoryProofRoot:
    """Repository-wide proof-forest root binding every category and context."""

    repository_id: str
    revision: str
    source_root_cid: str
    manifest_root_cid: str
    environment_cid: str
    policy_cid: str
    proof_schema_version: str
    canonicalization_version: str
    dependency_graph_schema_version: str
    parent_seal_cid: str
    parent_revision_ids: tuple[str, ...]
    category_roots: Mapping[str, str]
    root_cid: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_text(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "revision", _require_text(self.revision, "revision")
        )
        object.__setattr__(
            self,
            "source_root_cid",
            _require_cid(self.source_root_cid, "source_root_cid"),
        )
        object.__setattr__(
            self,
            "manifest_root_cid",
            _require_cid(self.manifest_root_cid, "manifest_root_cid"),
        )
        object.__setattr__(
            self,
            "environment_cid",
            _require_cid(self.environment_cid, "environment_cid"),
        )
        object.__setattr__(
            self, "policy_cid", _require_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(
            self,
            "proof_schema_version",
            _require_text(self.proof_schema_version, "proof_schema_version"),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_text(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        object.__setattr__(
            self,
            "dependency_graph_schema_version",
            _require_text(
                self.dependency_graph_schema_version,
                "dependency_graph_schema_version",
            ),
        )
        object.__setattr__(
            self,
            "parent_seal_cid",
            _require_cid(
                self.parent_seal_cid, "parent_seal_cid", allow_absence=False
            ),
        )
        object.__setattr__(
            self,
            "parent_revision_ids",
            _require_sorted_unique_strings(
                self.parent_revision_ids, "parent_revision_ids"
            ),
        )
        roots = _validate_category_roots_map(self.category_roots)
        object.__setattr__(self, "category_roots", roots)
        object.__setattr__(self, "root_cid", _require_cid(self.root_cid, "root_cid"))

    def to_canonical(self) -> dict[str, Any]:
        category_payload = {
            category_root_field_name(cat): self.category_roots[cat]
            for cat in FOREST_CATEGORIES
        }
        return {
            "schema": REPOSITORY_PROOF_ROOT_SCHEMA,
            "forest_codec_subset": FOREST_CODEC_SUBSET,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "source_root_cid": self.source_root_cid,
            "manifest_root_cid": self.manifest_root_cid,
            "environment_cid": self.environment_cid,
            "policy_cid": self.policy_cid,
            "proof_schema_version": self.proof_schema_version,
            "canonicalization_version": self.canonicalization_version,
            "dependency_graph_schema_version": self.dependency_graph_schema_version,
            "parent_seal_cid": self.parent_seal_cid,
            "parent_revision_ids": (
                list(self.parent_revision_ids)
                if self.parent_revision_ids
                else ABSENCE_TOKEN
            ),
            "category_roots": {
                cat: self.category_roots[cat] for cat in FOREST_CATEGORIES
            },
            **category_payload,
            "root_cid": self.root_cid,
            "typed_absence": TYPED_ABSENCE,
            "genesis_parent_seal": GENESIS_PARENT_SEAL,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def repository_root(self) -> str:
        return self.root_cid

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> RepositoryProofRoot:
        if not isinstance(payload, Mapping):
            raise ForestCodecError("RepositoryProofRoot payload must be a mapping")
        parents = payload.get("parent_revision_ids", ABSENCE_TOKEN)
        raw_roots = payload.get("category_roots")
        if raw_roots is None:
            # Accept plan-style flat ``*_root`` fields.
            raw_roots = {
                cat: payload.get(category_root_field_name(cat), "")
                for cat in FOREST_CATEGORIES
            }
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            revision=str(payload.get("revision") or ""),
            source_root_cid=str(payload.get("source_root_cid") or ""),
            manifest_root_cid=str(payload.get("manifest_root_cid") or ""),
            environment_cid=str(payload.get("environment_cid") or ""),
            policy_cid=str(payload.get("policy_cid") or ""),
            proof_schema_version=str(
                payload.get("proof_schema_version") or PROOF_SCHEMA_VERSION
            ),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
            dependency_graph_schema_version=str(
                payload.get("dependency_graph_schema_version") or "graph@1"
            ),
            parent_seal_cid=str(
                payload.get("parent_seal_cid") or GENESIS_PARENT_SEAL
            ),
            parent_revision_ids=(
                ()
                if parents == ABSENCE_TOKEN
                else tuple(str(item) for item in parents)  # type: ignore[arg-type]
            ),
            category_roots=raw_roots,  # type: ignore[arg-type]
            root_cid=str(payload.get("root_cid") or ""),
        )


def _validate_category_roots_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ForestCodecError("category_roots must be a mapping")
    # Reject unknown categories; require every closed category.
    unknown = sorted(set(value) - set(FOREST_CATEGORIES))
    if unknown:
        raise ForestCodecError(f"unknown forest category in roots: {unknown}")
    missing = [cat for cat in FOREST_CATEGORIES if cat not in value]
    if missing:
        raise ForestCodecError(f"missing category roots: {missing}")
    return {
        cat: _require_cid(value[cat], category_root_field_name(cat))
        for cat in FOREST_CATEGORIES
    }


def _repository_commitment_payload(
    *,
    repository_id: str,
    revision: str,
    source_root_cid: str,
    manifest_root_cid: str,
    environment_cid: str,
    policy_cid: str,
    proof_schema_version: str,
    canonicalization_version: str,
    dependency_graph_schema_version: str,
    parent_seal_cid: str,
    parent_revision_ids: tuple[str, ...],
    category_roots: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "domain": DOMAIN_REPOSITORY,
        "kind": "repository",
        "schema": REPOSITORY_PROOF_ROOT_SCHEMA,
        "forest_codec_subset": FOREST_CODEC_SUBSET,
        "repository_id": repository_id,
        "revision": revision,
        "source_root_cid": source_root_cid,
        "manifest_root_cid": manifest_root_cid,
        "environment_cid": environment_cid,
        "policy_cid": policy_cid,
        "proof_schema_version": proof_schema_version,
        "canonicalization_version": canonicalization_version,
        "dependency_graph_schema_version": dependency_graph_schema_version,
        "parent_seal_cid": parent_seal_cid,
        "parent_revision_ids": (
            list(parent_revision_ids) if parent_revision_ids else ABSENCE_TOKEN
        ),
        "category_roots": {cat: category_roots[cat] for cat in FOREST_CATEGORIES},
        **{
            category_root_field_name(cat): category_roots[cat]
            for cat in FOREST_CATEGORIES
        },
    }


def compute_repository_root(
    *,
    repository_id: str,
    revision: str,
    source_root_cid: str,
    manifest_root_cid: str,
    environment_cid: str,
    policy_cid: str,
    category_roots: Mapping[str, Any] | None = None,
    category_leaves: Mapping[str, Sequence[Any]] | None = None,
    proof_schema_version: str = PROOF_SCHEMA_VERSION,
    canonicalization_version: str = CANONICALIZATION_VERSION,
    dependency_graph_schema_version: str = "graph@1",
    parent_seal_cid: str = GENESIS_PARENT_SEAL,
    parent_revision_ids: Sequence[str] | str = (),
) -> RepositoryProofRoot:
    """Compute the repository proof root from category roots or leaf sets.

    Every closed category is required.  Missing categories default to empty
    roots when ``category_leaves`` is used; when only ``category_roots`` is
    supplied every category must be present.  Unknown categories fail closed.
    """

    repo_id = _require_text(repository_id, "repository_id")
    rev = _require_text(revision, "revision")
    source = _require_cid(source_root_cid, "source_root_cid")
    manifest = _require_cid(manifest_root_cid, "manifest_root_cid")
    environment = _require_cid(environment_cid, "environment_cid")
    policy = _require_cid(policy_cid, "policy_cid")
    schema_v = _require_text(proof_schema_version, "proof_schema_version")
    canon_v = _require_text(canonicalization_version, "canonicalization_version")
    graph_v = _require_text(
        dependency_graph_schema_version, "dependency_graph_schema_version"
    )
    parent_seal = _require_cid(parent_seal_cid, "parent_seal_cid")
    parents = _require_sorted_unique_strings(
        parent_revision_ids, "parent_revision_ids"
    )

    resolved: dict[str, str] = {}
    if category_leaves is not None:
        if not isinstance(category_leaves, Mapping):
            raise ForestCodecError("category_leaves must be a mapping")
        leaves_by_category: dict[str, Sequence[Any]] = {}
        for key, value in category_leaves.items():
            cat = parse_forest_category(key)
            if cat in leaves_by_category:
                raise ForestCodecError(
                    f"duplicate leaf sets for category {cat!r}"
                )
            leaves_by_category[cat] = value
        for cat in FOREST_CATEGORIES:
            leaves_for_cat = leaves_by_category.get(cat, ())
            resolved[cat] = compute_category_root(cat, leaves_for_cat).root_cid
    elif category_roots is not None:
        if not isinstance(category_roots, Mapping):
            raise ForestCodecError("category_roots must be a mapping")
        # Normalize keys (accept kind aliases and *_root field names).
        normalized_map: dict[str, Any] = {}
        for key, value in category_roots.items():
            key_text = str(key)
            if key_text.endswith("_root"):
                key_text = key_text[: -len("_root")]
            cat = parse_forest_category(key_text)
            if cat in normalized_map and normalized_map[cat] != value:
                raise ForestCodecError(f"conflicting roots for category {cat!r}")
            normalized_map[cat] = value
        missing = [cat for cat in FOREST_CATEGORIES if cat not in normalized_map]
        if missing:
            raise ForestCodecError(f"missing category roots: {missing}")
        resolved = {
            cat: _require_cid(normalized_map[cat], category_root_field_name(cat))
            for cat in FOREST_CATEGORIES
        }
    else:
        # All-empty forest.
        resolved = {
            cat: compute_category_root(cat, ()).root_cid for cat in FOREST_CATEGORIES
        }

    commitment = _repository_commitment_payload(
        repository_id=repo_id,
        revision=rev,
        source_root_cid=source,
        manifest_root_cid=manifest,
        environment_cid=environment,
        policy_cid=policy,
        proof_schema_version=schema_v,
        canonicalization_version=canon_v,
        dependency_graph_schema_version=graph_v,
        parent_seal_cid=parent_seal,
        parent_revision_ids=parents,
        category_roots=resolved,
    )
    root_cid = _node_cid(commitment)
    return RepositoryProofRoot(
        repository_id=repo_id,
        revision=rev,
        source_root_cid=source,
        manifest_root_cid=manifest,
        environment_cid=environment,
        policy_cid=policy,
        proof_schema_version=schema_v,
        canonicalization_version=canon_v,
        dependency_graph_schema_version=graph_v,
        parent_seal_cid=parent_seal,
        parent_revision_ids=parents,
        category_roots=resolved,
        root_cid=root_cid,
    )


# ---------------------------------------------------------------------------
# Samples and known vectors
# ---------------------------------------------------------------------------


def _sample_cid(label: str) -> str:
    return canonical_cid(
        {"ips_forest_codec_sample": label, "v": SCHEMA_MAJOR}
    )


def sample_leaf(
    *,
    proof_unit_id: str = "unit/a",
    category: str = "unit_test",
    position: int = 0,
    proof_object_cid: str | None = None,
) -> ProofForestLeaf:
    return ProofForestLeaf(
        proof_unit_id=proof_unit_id,
        proof_object_cid=proof_object_cid or _sample_cid(f"proof:{proof_unit_id}"),
        category=category,
        position=position,
    )


def sample_category_leaves(category: str = "unit_test") -> tuple[ProofForestLeaf, ...]:
    """Two sorted leaves for hermetic category-root vectors."""

    cat = parse_forest_category(category)
    return (
        sample_leaf(proof_unit_id="unit/a", category=cat, position=0),
        sample_leaf(proof_unit_id="unit/b", category=cat, position=1),
    )


def sample_repository_proof_root(**overrides: Any) -> RepositoryProofRoot:
    """Minimal valid repository forest root for tests and vectors."""

    unit_leaves = sample_category_leaves("unit_test")
    category_leaves: dict[str, Sequence[ProofForestLeaf]] = {
        "unit_test": unit_leaves,
        "static_analysis": (
            sample_leaf(
                proof_unit_id="unit/static-a",
                category="static_analysis",
                position=0,
            ),
        ),
    }
    payload = {
        "repository_id": "repo/datasets",
        "revision": "rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_root_cid": _sample_cid("source-root"),
        "manifest_root_cid": _sample_cid("manifest-root"),
        "environment_cid": _sample_cid("environment"),
        "policy_cid": _sample_cid("policy"),
        "category_leaves": category_leaves,
        "proof_schema_version": PROOF_SCHEMA_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "dependency_graph_schema_version": "graph@1",
        "parent_seal_cid": GENESIS_PARENT_SEAL,
        "parent_revision_ids": (),
    }
    payload.update(overrides)
    return compute_repository_root(**payload)


def known_vectors() -> dict[str, Any]:
    """Versioned portable known vectors for every category and root field."""

    # Empty roots for every closed category.
    empty_roots = {
        cat: compute_category_root(cat, ()).to_canonical() for cat in FOREST_CATEGORIES
    }

    # Unary (1 leaf) and binary (2 leaves) plus 3-leaf (binary+unary) shapes.
    one_leaf = (
        sample_leaf(proof_unit_id="unit/a", category="unit_test", position=0),
    )
    two_leaves = sample_category_leaves("unit_test")
    three_leaves = (
        sample_leaf(proof_unit_id="unit/a", category="unit_test", position=0),
        sample_leaf(proof_unit_id="unit/b", category="unit_test", position=1),
        sample_leaf(proof_unit_id="unit/c", category="unit_test", position=2),
    )
    unary_category = compute_category_root("unit_test", one_leaf)
    binary_category = compute_category_root("unit_test", two_leaves)
    mixed_category = compute_category_root("unit_test", three_leaves)

    base = sample_repository_proof_root()
    base_root = base.root_cid

    # One-bit leaf change must propagate.
    flipped_leaves = (
        sample_leaf(proof_unit_id="unit/a", category="unit_test", position=0),
        sample_leaf(
            proof_unit_id="unit/b",
            category="unit_test",
            position=1,
            proof_object_cid=_sample_cid("proof:unit/b-flipped"),
        ),
    )
    flipped_repo = sample_repository_proof_root(
        category_leaves={
            "unit_test": flipped_leaves,
            "static_analysis": (
                sample_leaf(
                    proof_unit_id="unit/static-a",
                    category="static_analysis",
                    position=0,
                ),
            ),
        }
    )
    if flipped_repo.root_cid == base_root:
        raise ForestCodecError("one-bit leaf change did not propagate to repository root")

    # Context mutations that must change the repository root.
    context_mutations: dict[str, str] = {}
    for field, value in (
        ("parent_seal_cid", _sample_cid("parent-seal-mutated")),
        ("revision", "rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        ("environment_cid", _sample_cid("environment-mutated")),
        ("proof_schema_version", "2"),
        ("canonicalization_version", "ips/canonicalization@2"),
        ("dependency_graph_schema_version", "graph@2"),
        ("policy_cid", _sample_cid("policy-mutated")),
        ("source_root_cid", _sample_cid("source-root-mutated")),
        ("manifest_root_cid", _sample_cid("manifest-root-mutated")),
        ("repository_id", "repo/datasets-mutated"),
        (
            "parent_revision_ids",
            ("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
        ),
    ):
        mutated = sample_repository_proof_root(**{field: value})
        if mutated.root_cid == base_root:
            raise ForestCodecError(
                f"context mutation of {field} did not change repository root"
            )
        context_mutations[field] = mutated.root_cid

    # Empty-category diversity: empty roots differ by category domain binding.
    empty_root_cids = {
        cat: empty_roots[cat]["root_cid"] for cat in FOREST_CATEGORIES
    }
    if len(set(empty_root_cids.values())) != len(FOREST_CATEGORIES):
        raise ForestCodecError("empty category roots must be domain-separated")

    return {
        "schema": f"{FOREST_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "forest_codec_subset": FOREST_CODEC_SUBSET,
        "forest_codec_vectors_subset": FOREST_CODEC_VECTORS_SUBSET,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "proof_schema_version": PROOF_SCHEMA_VERSION,
        "genesis_parent_seal": GENESIS_PARENT_SEAL,
        "domains": {
            "empty": DOMAIN_EMPTY,
            "leaf": DOMAIN_LEAF,
            "unary": DOMAIN_UNARY,
            "binary": DOMAIN_BINARY,
            "category": DOMAIN_CATEGORY,
            "repository": DOMAIN_REPOSITORY,
        },
        "categories": list(FOREST_CATEGORIES),
        "empty_category_roots": empty_roots,
        "node_shapes": {
            "empty": {
                "category": "property_test",
                "merkle_root": encode_empty_node(category="property_test"),
                "root_cid": empty_roots["property_test"]["root_cid"],
            },
            "unary": {
                "leaves": [leaf.to_canonical() for leaf in one_leaf],
                "merkle_root": unary_category.merkle_root,
                "root_cid": unary_category.root_cid,
            },
            "binary": {
                "leaves": [leaf.to_canonical() for leaf in two_leaves],
                "merkle_root": binary_category.merkle_root,
                "root_cid": binary_category.root_cid,
            },
            "binary_plus_unary": {
                "leaves": [leaf.to_canonical() for leaf in three_leaves],
                "merkle_root": mixed_category.merkle_root,
                "root_cid": mixed_category.root_cid,
            },
        },
        "base": {
            "payload": base.to_canonical(),
            "root_cid": base_root,
            "category_roots": dict(base.category_roots),
        },
        "one_bit_leaf_mutation": {
            "payload": flipped_repo.to_canonical(),
            "root_cid": flipped_repo.root_cid,
            "base_root_cid": base_root,
        },
        "context_mutations": context_mutations,
        "fail_closed": {
            "duplicate_unit_ids": [
                sample_leaf(
                    proof_unit_id="unit/a", category="unit_test", position=0
                ).to_canonical(),
                sample_leaf(
                    proof_unit_id="unit/a", category="unit_test", position=1
                ).to_canonical(),
            ],
            "reordered_leaves": [
                sample_leaf(
                    proof_unit_id="unit/b", category="unit_test", position=0
                ).to_canonical(),
                sample_leaf(
                    proof_unit_id="unit/a", category="unit_test", position=1
                ).to_canonical(),
            ],
            "duplicate_positions": [
                sample_leaf(
                    proof_unit_id="unit/a", category="unit_test", position=0
                ).to_canonical(),
                sample_leaf(
                    proof_unit_id="unit/b", category="unit_test", position=0
                ).to_canonical(),
            ],
            "unknown_category": "mystery_category",
        },
    }


def render_forest_vectors_json() -> str:
    """Render compact known vectors JSON for the portable fixture."""

    return json.dumps(
        known_vectors(),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


__all__ = (
    "ABSENCE_TOKEN",
    "CANONICALIZATION_VERSION",
    "CATEGORY_ROOT_SCHEMA",
    "DOMAIN_BINARY",
    "DOMAIN_CATEGORY",
    "DOMAIN_EMPTY",
    "DOMAIN_LEAF",
    "DOMAIN_REPOSITORY",
    "DOMAIN_UNARY",
    "FOREST_CATEGORIES",
    "FOREST_CODEC_SUBSET",
    "FOREST_CODEC_VECTORS_SUBSET",
    "GENESIS_PARENT_SEAL",
    "PROOF_FOREST_LEAF_SCHEMA",
    "PROOF_SCHEMA_VERSION",
    "REPOSITORY_PROOF_ROOT_SCHEMA",
    "REPOSITORY_ROOT_FIELDS",
    "TYPED_ABSENCE",
    "CategoryRoot",
    "ForestCategory",
    "ForestCodecError",
    "ProofForestLeaf",
    "RepositoryProofRoot",
    "category_root_field_name",
    "closed_forest_categories",
    "compute_category_root",
    "compute_repository_root",
    "encode_binary_node",
    "encode_empty_node",
    "encode_leaf_node",
    "encode_unary_node",
    "known_vectors",
    "parse_forest_category",
    "render_forest_vectors_json",
    "sample_category_leaves",
    "sample_leaf",
    "sample_repository_proof_root",
)
