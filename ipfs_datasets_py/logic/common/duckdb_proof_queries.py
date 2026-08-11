"""Allowlisted proof, graph, and applicability query templates (DQK-030).

Exposes bounded, parameterized query templates over the proofs catalog (and
optional graph / AST join surfaces) for:

* proof hits / misses
* premises
* dependency closure (recursive premise traversal)
* graph entities
* source revisions
* applicability
* revocation
* counterexamples

Every result row always projects explicit **authority**, **freshness**,
**applicability**, and **revocation** columns.  Query evaluation never
promotes an untrusted cache hit: stored trust is retained as-is, and the
``promotable`` / ``usable`` flags stay false for non-trusted, revoked, stale,
or inapplicable rows.

Recursive premise traversal is hard-bounded by depth, row count, and wall
time.  Importing this module is inert (no DuckDB, network, or filesystem I/O).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ..backends.cache_protocol import (
    DEFAULT_NEGATIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    CachePolarity,
)
from .duckdb_proof_store import (
    PROOFS_CATALOG_NAME,
    PROOFS_CATALOG_TABLES,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    trust_rank,
)

# ---------------------------------------------------------------------------
# Pins / defaults
# ---------------------------------------------------------------------------

DUCKDB_PROOF_QUERIES_INTERFACE: Final = "DuckDBProofQueries@1"
DUCKDB_PROOF_QUERIES_SCHEMA_VERSION: Final = "duckdb-proof-queries/v1"
DUCKDB_PROOF_QUERIES_SCHEMA: Final = (
    "ipfs_datasets_py/logic-common-duckdb-proof-queries@1"
)

DEFAULT_MAX_DEPTH: Final = 8
DEFAULT_MAX_ROWS: Final = 10_000
DEFAULT_MAX_SECONDS: Final = 2.0
MAX_ALLOWED_DEPTH: Final = 64
MAX_ALLOWED_ROWS: Final = 100_000

# Trust levels that may ever be marked promotable.  NON_TRUSTED and NONE are
# deliberately excluded so queries cannot promote untrusted cache hits.
_PROMOTABLE_TRUST: Final[frozenset[ProofTrustLevel]] = frozenset(
    {
        ProofTrustLevel.BOUNDED,
        ProofTrustLevel.INDEPENDENTLY_CHECKABLE,
        ProofTrustLevel.AUTHORITATIVE,
    }
)

# Closed set of template names (allowlist).  Arbitrary SQL is rejected.
class ProofQueryKind(StrEnum):
    """Allowlisted proof query template identifiers."""

    PROOF_HIT_MISS = "proof_hit_miss"
    PREMISES = "premises"
    DEPENDENCY_CLOSURE = "dependency_closure"
    GRAPH_ENTITIES = "graph_entities"
    SOURCE_REVISIONS = "source_revisions"
    APPLICABILITY = "applicability"
    REVOCATION = "revocation"
    COUNTEREXAMPLES = "counterexamples"


# Columns that every template result must expose (acceptance: always visible).
AUTHORITY_COLUMNS: Final[tuple[str, ...]] = (
    "trust_level",
    "result_authority",
    "evidence_authority",
    "promotable",
)

FRESHNESS_COLUMNS: Final[tuple[str, ...]] = (
    "fresh",
    "age_seconds",
    "ttl_seconds",
    "expires_at",
    "created_at",
)

APPLICABILITY_COLUMNS: Final[tuple[str, ...]] = (
    "applicable",
    "applicability_reason",
)

REVOCATION_COLUMNS: Final[tuple[str, ...]] = (
    "is_revoked",
    "revocation_id",
    "revocation_reason",
    "revoked_at",
)

COMMON_PROJECTION_COLUMNS: Final[tuple[str, ...]] = (
    AUTHORITY_COLUMNS
    + FRESHNESS_COLUMNS
    + APPLICABILITY_COLUMNS
    + REVOCATION_COLUMNS
)


# ---------------------------------------------------------------------------
# Errors / budgets
# ---------------------------------------------------------------------------


class ProofQueryError(ValueError):
    """Raised when a proof query template or parameter is invalid."""


class ProofQueryBudgetExceeded(ProofQueryError):
    """Raised when a bounded traversal exhausts its budget fail-closed."""

    def __init__(self, kind: str, limit: int | float) -> None:
        super().__init__(f"proof query budget exceeded: {kind} limit={limit}")
        self.kind = kind
        self.limit = limit


@dataclass(frozen=True, slots=True)
class ProofQueryBudget:
    """Hard bounds for recursive premise dependency closure."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_rows: int = DEFAULT_MAX_ROWS
    max_seconds: float = DEFAULT_MAX_SECONDS

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_depth, int)
            or isinstance(self.max_depth, bool)
            or self.max_depth < 0
        ):
            raise ProofQueryError("max_depth must be a non-negative int")
        if self.max_depth > MAX_ALLOWED_DEPTH:
            raise ProofQueryError(f"max_depth must be <= {MAX_ALLOWED_DEPTH}")
        if (
            not isinstance(self.max_rows, int)
            or isinstance(self.max_rows, bool)
            or self.max_rows < 1
        ):
            raise ProofQueryError("max_rows must be an int >= 1")
        if self.max_rows > MAX_ALLOWED_ROWS:
            raise ProofQueryError(f"max_rows must be <= {MAX_ALLOWED_ROWS}")
        if not isinstance(self.max_seconds, (int, float)) or self.max_seconds <= 0:
            raise ProofQueryError("max_seconds must be a positive number")


# ---------------------------------------------------------------------------
# SQL templates (parameterized; values never interpolated)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofQueryTemplate:
    """One allowlisted, parameterized DuckDB SQL template."""

    kind: ProofQueryKind
    name: str
    description: str
    sql: str
    parameters: tuple[str, ...]
    result_columns: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "kind": self.kind.value,
            "name": self.name,
            "parameters": list(self.parameters),
            "result_columns": list(self.result_columns),
            "schema": DUCKDB_PROOF_QUERIES_SCHEMA,
            "schema_version": DUCKDB_PROOF_QUERIES_SCHEMA_VERSION,
            "sql": self.sql,
        }


# Shared SELECT fragment projecting authority / freshness / applicability /
# revocation.  Placeholders are filled by template-specific CTEs that define
# the alias ``entry_view``.
_AUTHORITY_FRESHNESS_SELECT: Final = """
    entry_view.trust_level AS trust_level,
    entry_view.result_authority AS result_authority,
    entry_view.evidence_authority AS evidence_authority,
    CASE
        WHEN entry_view.trust_level IN ('bounded', 'independently_checkable', 'authoritative')
             AND rev.revocation_id IS NULL
             AND (
                 CASE
                     WHEN entry_view.polarity = 'negative'
                         THEN (?::DOUBLE - entry_view.created_at) <= ?::DOUBLE
                     ELSE (?::DOUBLE - entry_view.created_at) <= ?::DOUBLE
                 END
             )
        THEN TRUE ELSE FALSE
    END AS promotable,
    CASE
        WHEN entry_view.polarity = 'negative'
            THEN (?::DOUBLE - entry_view.created_at) <= ?::DOUBLE
        ELSE (?::DOUBLE - entry_view.created_at) <= ?::DOUBLE
    END AS fresh,
    (?::DOUBLE - entry_view.created_at) AS age_seconds,
    CASE
        WHEN entry_view.polarity = 'negative' THEN ?::DOUBLE
        ELSE ?::DOUBLE
    END AS ttl_seconds,
    entry_view.created_at + CASE
        WHEN entry_view.polarity = 'negative' THEN ?::DOUBLE
        ELSE ?::DOUBLE
    END AS expires_at,
    entry_view.created_at AS created_at,
    CASE
        WHEN rev.revocation_id IS NOT NULL THEN FALSE
        WHEN entry_view.polarity = 'negative'
             AND (?::DOUBLE - entry_view.created_at) > ?::DOUBLE THEN FALSE
        WHEN entry_view.polarity <> 'negative'
             AND (?::DOUBLE - entry_view.created_at) > ?::DOUBLE THEN FALSE
        WHEN entry_view.trust_level IN ('non_trusted', 'none') THEN FALSE
        ELSE TRUE
    END AS applicable,
    CASE
        WHEN rev.revocation_id IS NOT NULL THEN 'revoked'
        WHEN entry_view.polarity = 'negative'
             AND (?::DOUBLE - entry_view.created_at) > ?::DOUBLE THEN 'stale'
        WHEN entry_view.polarity <> 'negative'
             AND (?::DOUBLE - entry_view.created_at) > ?::DOUBLE THEN 'stale'
        WHEN entry_view.trust_level IN ('non_trusted', 'none') THEN 'untrusted'
        ELSE 'applicable'
    END AS applicability_reason,
    rev.revocation_id IS NOT NULL AS is_revoked,
    rev.revocation_id AS revocation_id,
    rev.reason AS revocation_reason,
    rev.created_at AS revoked_at
""".strip()

_FRESHNESS_PARAM_NAMES: Final[tuple[str, ...]] = (
    # promotable: now, neg_ttl, now, pos_ttl
    "now",
    "negative_ttl_seconds",
    "now",
    "positive_ttl_seconds",
    # fresh: now, neg_ttl, now, pos_ttl
    "now",
    "negative_ttl_seconds",
    "now",
    "positive_ttl_seconds",
    # age: now
    "now",
    # ttl_seconds: neg, pos
    "negative_ttl_seconds",
    "positive_ttl_seconds",
    # expires_at: neg, pos
    "negative_ttl_seconds",
    "positive_ttl_seconds",
    # applicable stale checks: now, neg, now, pos
    "now",
    "negative_ttl_seconds",
    "now",
    "positive_ttl_seconds",
    # applicability_reason stale checks: now, neg, now, pos
    "now",
    "negative_ttl_seconds",
    "now",
    "positive_ttl_seconds",
)


def _hit_miss_sql() -> str:
    return f"""
SELECT
    pe.key_digest AS key_digest,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    CASE WHEN pe.entry_digest IS NULL THEN FALSE ELSE TRUE END AS hit,
    CASE
        WHEN pe.entry_digest IS NULL THEN FALSE
        WHEN rev.revocation_id IS NOT NULL THEN FALSE
        WHEN pe.trust_level IN ('non_trusted', 'none') THEN FALSE
        WHEN pe.polarity = 'negative'
             AND (?::DOUBLE - pe.created_at) > ?::DOUBLE THEN FALSE
        WHEN pe.polarity <> 'negative'
             AND (?::DOUBLE - pe.created_at) > ?::DOUBLE THEN FALSE
        ELSE TRUE
    END AS usable,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM (SELECT ?::VARCHAR AS requested_key_digest) req
LEFT JOIN proof_entries pe ON pe.key_digest = req.requested_key_digest
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
""".strip()


def _premises_sql() -> str:
    return f"""
SELECT
    p.key_digest AS key_digest,
    p.premise_digest AS premise_digest,
    p.premise_ordinal AS premise_ordinal,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM premises p
LEFT JOIN proof_entries pe ON pe.key_digest = p.key_digest
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
WHERE p.key_digest = ?
ORDER BY p.premise_ordinal ASC
LIMIT ?
""".strip()


def _dependency_closure_sql() -> str:
    # Bounded recursive CTE: depth < max_depth; outer LIMIT max_rows.
    return f"""
WITH RECURSIVE premise_closure AS (
    SELECT
        p.key_digest AS root_key_digest,
        p.key_digest AS parent_key_digest,
        p.premise_digest AS node_digest,
        p.premise_ordinal AS premise_ordinal,
        1 AS depth
    FROM premises p
    WHERE p.key_digest = ?
    UNION ALL
    SELECT
        c.root_key_digest,
        p2.key_digest AS parent_key_digest,
        p2.premise_digest AS node_digest,
        p2.premise_ordinal AS premise_ordinal,
        c.depth + 1 AS depth
    FROM premise_closure c
    JOIN premises p2 ON p2.key_digest = c.node_digest
    WHERE c.depth < ?
)
SELECT
    c.root_key_digest AS root_key_digest,
    c.parent_key_digest AS parent_key_digest,
    c.node_digest AS premise_digest,
    c.premise_ordinal AS premise_ordinal,
    c.depth AS depth,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM premise_closure c
LEFT JOIN proof_entries pe ON pe.key_digest = c.node_digest
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
ORDER BY c.depth ASC, c.premise_ordinal ASC
LIMIT ?
""".strip()


def _graph_entities_sql() -> str:
    return f"""
SELECT
    pe.key_digest AS key_digest,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    ge.entity_id AS entity_id,
    ge.entity_kind AS entity_kind,
    ge.graph_revision AS graph_revision,
    ge.source_cid AS source_cid,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM proof_entries pe
JOIN graph_entities ge
    ON ge.entity_id = pe.key_digest
    OR ge.tree_digest = pe.key_digest
    OR ge.entity_id = json_extract_string(pe.payload_json, '$.entity_id')
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
WHERE (?::VARCHAR IS NULL OR pe.key_digest = ?)
  AND (?::VARCHAR IS NULL OR ge.graph_revision = ?)
LIMIT ?
""".strip()


def _source_revisions_sql() -> str:
    return f"""
SELECT
    pe.key_digest AS key_digest,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    sr.revision_id AS revision_id,
    sr.repository_id AS repository_id,
    sr.revision AS revision,
    sr.repository_tree_cid AS repository_tree_cid,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM proof_entries pe
JOIN source_revisions sr
    ON sr.revision_id = pe.key_digest
    OR sr.repository_tree_cid = json_extract_string(pe.payload_json, '$.tree_digest')
    OR sr.revision = json_extract_string(pe.payload_json, '$.revision')
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
WHERE (?::VARCHAR IS NULL OR pe.key_digest = ?)
  AND (?::VARCHAR IS NULL OR sr.revision_id = ?)
LIMIT ?
""".strip()


def _applicability_sql() -> str:
    return f"""
SELECT
    pe.key_digest AS key_digest,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM proof_entries pe
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
WHERE pe.key_digest = ?
""".strip()


def _revocation_sql() -> str:
    return f"""
SELECT
    pe.key_digest AS key_digest,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM proof_entries pe
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
WHERE (?::VARCHAR IS NULL OR pe.key_digest = ?)
  AND (?::VARCHAR IS NULL OR pe.entry_digest = ?)
  AND (
      ?::BOOLEAN = FALSE
      OR rev.revocation_id IS NOT NULL
  )
LIMIT ?
""".strip()


def _counterexamples_sql() -> str:
    return f"""
SELECT
    pe.key_digest AS key_digest,
    pe.entry_digest AS entry_digest,
    pe.outcome AS outcome,
    pe.status AS status,
    pe.polarity AS polarity,
    {_AUTHORITY_FRESHNESS_SELECT.replace("entry_view.", "pe.")}
FROM proof_entries pe
LEFT JOIN (
    SELECT entry_digest, revocation_id, reason, created_at
    FROM revocations
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY entry_digest ORDER BY created_at DESC
    ) = 1
) rev ON rev.entry_digest = pe.entry_digest
WHERE pe.outcome = 'counterexample'
  AND (?::VARCHAR IS NULL OR pe.key_digest = ?)
LIMIT ?
""".strip()


def _build_templates() -> dict[ProofQueryKind, ProofQueryTemplate]:
    hit_miss_params = (
        # usable: now, neg, now, pos
        "now",
        "negative_ttl_seconds",
        "now",
        "positive_ttl_seconds",
    ) + _FRESHNESS_PARAM_NAMES + ("key_digest",)

    premises_params = _FRESHNESS_PARAM_NAMES + ("key_digest", "max_rows")
    closure_params = (
        "key_digest",
        "max_depth",
    ) + _FRESHNESS_PARAM_NAMES + ("max_rows",)
    graph_params = _FRESHNESS_PARAM_NAMES + (
        "key_digest",
        "key_digest",
        "graph_revision",
        "graph_revision",
        "max_rows",
    )
    source_params = _FRESHNESS_PARAM_NAMES + (
        "key_digest",
        "key_digest",
        "revision_id",
        "revision_id",
        "max_rows",
    )
    applicability_params = _FRESHNESS_PARAM_NAMES + ("key_digest",)
    revocation_params = _FRESHNESS_PARAM_NAMES + (
        "key_digest",
        "key_digest",
        "entry_digest",
        "entry_digest",
        "revoked_only",
        "max_rows",
    )
    counter_params = _FRESHNESS_PARAM_NAMES + (
        "key_digest",
        "key_digest",
        "max_rows",
    )

    common = COMMON_PROJECTION_COLUMNS

    return {
        ProofQueryKind.PROOF_HIT_MISS: ProofQueryTemplate(
            kind=ProofQueryKind.PROOF_HIT_MISS,
            name="proof_hit_miss",
            description=(
                "Lookup one proof key: hit/miss with authority, freshness, "
                "applicability, and revocation; untrusted hits are not usable."
            ),
            sql=_hit_miss_sql(),
            parameters=hit_miss_params,
            result_columns=(
                "key_digest",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
                "hit",
                "usable",
            )
            + common,
        ),
        ProofQueryKind.PREMISES: ProofQueryTemplate(
            kind=ProofQueryKind.PREMISES,
            name="premises",
            description="List premises for a proof key with authority/freshness.",
            sql=_premises_sql(),
            parameters=premises_params,
            result_columns=(
                "key_digest",
                "premise_digest",
                "premise_ordinal",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
            )
            + common,
        ),
        ProofQueryKind.DEPENDENCY_CLOSURE: ProofQueryTemplate(
            kind=ProofQueryKind.DEPENDENCY_CLOSURE,
            name="dependency_closure",
            description=(
                "Bounded recursive premise dependency closure "
                "(depth/row limited)."
            ),
            sql=_dependency_closure_sql(),
            parameters=closure_params,
            result_columns=(
                "root_key_digest",
                "parent_key_digest",
                "premise_digest",
                "premise_ordinal",
                "depth",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
            )
            + common,
        ),
        ProofQueryKind.GRAPH_ENTITIES: ProofQueryTemplate(
            kind=ProofQueryKind.GRAPH_ENTITIES,
            name="graph_entities",
            description=(
                "Join proof entries to graph entities with authority/freshness."
            ),
            sql=_graph_entities_sql(),
            parameters=graph_params,
            result_columns=(
                "key_digest",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
                "entity_id",
                "entity_kind",
                "graph_revision",
                "source_cid",
            )
            + common,
        ),
        ProofQueryKind.SOURCE_REVISIONS: ProofQueryTemplate(
            kind=ProofQueryKind.SOURCE_REVISIONS,
            name="source_revisions",
            description=(
                "Join proof entries to AST source revisions with "
                "authority/freshness."
            ),
            sql=_source_revisions_sql(),
            parameters=source_params,
            result_columns=(
                "key_digest",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
                "revision_id",
                "repository_id",
                "revision",
                "repository_tree_cid",
            )
            + common,
        ),
        ProofQueryKind.APPLICABILITY: ProofQueryTemplate(
            kind=ProofQueryKind.APPLICABILITY,
            name="applicability",
            description=(
                "Evaluate applicability for a proof entry "
                "(fresh + not revoked + trusted)."
            ),
            sql=_applicability_sql(),
            parameters=applicability_params,
            result_columns=(
                "key_digest",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
            )
            + common,
        ),
        ProofQueryKind.REVOCATION: ProofQueryTemplate(
            kind=ProofQueryKind.REVOCATION,
            name="revocation",
            description=(
                "List proof entries with revocation status always visible."
            ),
            sql=_revocation_sql(),
            parameters=revocation_params,
            result_columns=(
                "key_digest",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
            )
            + common,
        ),
        ProofQueryKind.COUNTEREXAMPLES: ProofQueryTemplate(
            kind=ProofQueryKind.COUNTEREXAMPLES,
            name="counterexamples",
            description=(
                "List counterexample outcomes with authority/freshness/"
                "revocation."
            ),
            sql=_counterexamples_sql(),
            parameters=counter_params,
            result_columns=(
                "key_digest",
                "entry_digest",
                "outcome",
                "status",
                "polarity",
            )
            + common,
        ),
    }


PROOF_QUERY_TEMPLATES: Final[Mapping[ProofQueryKind, ProofQueryTemplate]] = (
    MappingProxyType(_build_templates())
)


# ---------------------------------------------------------------------------
# Compile / parameter binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompiledProofQuery:
    """A bound, allowlisted SQL statement ready for execution."""

    kind: ProofQueryKind
    sql: str
    parameters: tuple[Any, ...]
    parameter_names: tuple[str, ...]
    result_columns: tuple[str, ...]
    budget: ProofQueryBudget | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": None
            if self.budget is None
            else {
                "max_depth": self.budget.max_depth,
                "max_rows": self.budget.max_rows,
                "max_seconds": self.budget.max_seconds,
            },
            "kind": self.kind.value,
            "parameter_names": list(self.parameter_names),
            "parameters": list(self.parameters),
            "result_columns": list(self.result_columns),
            "schema": DUCKDB_PROOF_QUERIES_SCHEMA,
            "schema_version": DUCKDB_PROOF_QUERIES_SCHEMA_VERSION,
            "sql": self.sql,
        }


def list_query_kinds() -> tuple[str, ...]:
    """Return the closed allowlist of query template names."""

    return tuple(kind.value for kind in ProofQueryKind)


def get_template(kind: ProofQueryKind | str) -> ProofQueryTemplate:
    """Resolve an allowlisted template; unknown names fail closed."""

    resolved = _resolve_kind(kind)
    return PROOF_QUERY_TEMPLATES[resolved]


def _resolve_kind(kind: ProofQueryKind | str) -> ProofQueryKind:
    if isinstance(kind, ProofQueryKind):
        return kind
    try:
        return ProofQueryKind(str(kind))
    except ValueError as error:
        raise ProofQueryError(
            f"unknown proof query kind {kind!r}; allowlist={list_query_kinds()}"
        ) from error


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProofQueryError(
            f"{field_name} must be a non-empty string without NUL"
        )
    return value.strip()


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ProofQueryError(f"{field_name} must be a string or None")
    text = value.strip()
    return text or None


def compile_query(
    kind: ProofQueryKind | str,
    *,
    key_digest: str | None = None,
    entry_digest: str | None = None,
    graph_revision: str | None = None,
    revision_id: str | None = None,
    revoked_only: bool = False,
    now: float | None = None,
    positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS,
    negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
    budget: ProofQueryBudget | None = None,
) -> CompiledProofQuery:
    """Compile an allowlisted template with bound parameters.

    Parameters are never interpolated into SQL text.  Trust is never raised.
    """

    resolved = _resolve_kind(kind)
    template = PROOF_QUERY_TEMPLATES[resolved]
    bud = budget or ProofQueryBudget()
    current = time.time() if now is None else float(now)
    if positive_ttl_seconds < 0 or negative_ttl_seconds < 0:
        raise ProofQueryError("TTL values must be non-negative")

    values: dict[str, Any] = {
        "now": current,
        "positive_ttl_seconds": float(positive_ttl_seconds),
        "negative_ttl_seconds": float(negative_ttl_seconds),
        "max_depth": bud.max_depth,
        "max_rows": bud.max_rows,
        "revoked_only": bool(revoked_only),
        "key_digest": _optional_text(key_digest, "key_digest"),
        "entry_digest": _optional_text(entry_digest, "entry_digest"),
        "graph_revision": _optional_text(graph_revision, "graph_revision"),
        "revision_id": _optional_text(revision_id, "revision_id"),
    }

    # Templates that require a key_digest fail closed when absent.
    if resolved in {
        ProofQueryKind.PROOF_HIT_MISS,
        ProofQueryKind.PREMISES,
        ProofQueryKind.DEPENDENCY_CLOSURE,
        ProofQueryKind.APPLICABILITY,
    }:
        if values["key_digest"] is None:
            raise ProofQueryError(f"{resolved.value} requires key_digest")
        values["key_digest"] = _require_digest(values["key_digest"], "key_digest")

    bound = tuple(values[name] for name in template.parameters)
    return CompiledProofQuery(
        kind=resolved,
        sql=template.sql,
        parameters=bound,
        parameter_names=template.parameters,
        result_columns=template.result_columns,
        budget=bud if resolved is ProofQueryKind.DEPENDENCY_CLOSURE else None,
    )


# ---------------------------------------------------------------------------
# Pure-Python projection helpers (hermetic; no DuckDB required)
# ---------------------------------------------------------------------------


def is_promotable_trust(trust_level: ProofTrustLevel | str) -> bool:
    """Return whether *trust_level* may ever be marked promotable.

    ``non_trusted`` and ``none`` are never promotable — queries cannot promote
    untrusted cache hits.
    """

    if isinstance(trust_level, ProofTrustLevel):
        resolved = trust_level
    else:
        try:
            resolved = ProofTrustLevel(str(trust_level))
        except ValueError:
            return False
    return resolved in _PROMOTABLE_TRUST


def ttl_for_polarity(
    polarity: CachePolarity | str,
    *,
    positive_ttl_seconds: float,
    negative_ttl_seconds: float,
) -> float:
    resolved = (
        polarity
        if isinstance(polarity, CachePolarity)
        else CachePolarity(str(polarity))
    )
    if resolved is CachePolarity.NEGATIVE:
        return float(negative_ttl_seconds)
    return float(positive_ttl_seconds)


def project_authority_freshness(
    *,
    trust_level: ProofTrustLevel | str,
    result_authority: str,
    evidence_authority: str,
    polarity: CachePolarity | str,
    created_at: float,
    now: float,
    positive_ttl_seconds: float,
    negative_ttl_seconds: float,
    revocation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the mandatory authority/freshness/applicability/revocation columns.

    Stored trust is never raised.  Untrusted, revoked, or stale rows are never
    marked ``promotable`` or ``applicable``.
    """

    trust = (
        trust_level
        if isinstance(trust_level, ProofTrustLevel)
        else ProofTrustLevel(str(trust_level))
    )
    age = max(0.0, float(now) - float(created_at))
    ttl = ttl_for_polarity(
        polarity,
        positive_ttl_seconds=positive_ttl_seconds,
        negative_ttl_seconds=negative_ttl_seconds,
    )
    fresh = True if ttl <= 0 else age <= ttl
    is_revoked = bool(revocation)
    revocation_id = None if not revocation else revocation.get("revocation_id")
    revocation_reason = None if not revocation else revocation.get("reason")
    revoked_at = None if not revocation else revocation.get("created_at")

    if is_revoked:
        applicable = False
        applicability_reason = "revoked"
    elif not fresh:
        applicable = False
        applicability_reason = "stale"
    elif trust in (ProofTrustLevel.NON_TRUSTED, ProofTrustLevel.NONE):
        applicable = False
        applicability_reason = "untrusted"
    else:
        applicable = True
        applicability_reason = "applicable"

    promotable = (
        is_promotable_trust(trust)
        and not is_revoked
        and fresh
        and applicable
    )

    return {
        "trust_level": trust.value,
        "result_authority": str(result_authority),
        "evidence_authority": str(evidence_authority),
        # Never rewrite stored trust upward; promotable is a separate gate.
        "promotable": bool(promotable),
        "fresh": bool(fresh),
        "age_seconds": float(age),
        "ttl_seconds": float(ttl),
        "expires_at": float(created_at) + float(ttl) if ttl > 0 else None,
        "created_at": float(created_at),
        "applicable": bool(applicable),
        "applicability_reason": applicability_reason,
        "is_revoked": bool(is_revoked),
        "revocation_id": revocation_id,
        "revocation_reason": revocation_reason,
        "revoked_at": revoked_at,
    }


def promote_untrusted_hit(
    row: Mapping[str, Any],
    *,
    target_trust: ProofTrustLevel | str = ProofTrustLevel.AUTHORITATIVE,
) -> dict[str, Any]:
    """Refuse to promote an untrusted hit — always fails closed.

    This is the explicit fail-closed API proving queries cannot promote
    untrusted cache hits.  Callers that need higher trust must go through
    evidence-gated authority upgrades outside this module.
    """

    trust_raw = row.get("trust_level")
    if not is_promotable_trust(str(trust_raw or "none")):
        raise ProofQueryError(
            "queries cannot promote an untrusted cache hit; "
            f"stored trust_level={trust_raw!r}"
        )
    if row.get("is_revoked"):
        raise ProofQueryError("queries cannot promote a revoked cache hit")
    if not row.get("fresh", False):
        raise ProofQueryError("queries cannot promote a stale cache hit")
    if not row.get("applicable", False):
        raise ProofQueryError(
            "queries cannot promote an inapplicable cache hit; "
            f"reason={row.get('applicability_reason')!r}"
        )
    # Even for trusted rows, this query surface never mutates trust — it only
    # confirms the row is already promotable.  Effective trust stays stored.
    target = (
        target_trust
        if isinstance(target_trust, ProofTrustLevel)
        else ProofTrustLevel(str(target_trust))
    )
    stored = ProofTrustLevel(str(trust_raw))
    if trust_rank(target) > trust_rank(stored):
        raise ProofQueryError(
            "queries cannot raise trust_level "
            f"from {stored.value!r} to {target.value!r}"
        )
    return dict(row)


# ---------------------------------------------------------------------------
# In-memory catalog + pure-Python evaluator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PremiseRow:
    key_digest: str
    premise_digest: str
    premise_ordinal: int


@dataclass(frozen=True, slots=True)
class RevocationRow:
    revocation_id: str
    entry_digest: str
    reason: str
    created_at: float
    actor_id: str = "unknown"


@dataclass(frozen=True, slots=True)
class GraphEntityRow:
    entity_id: str
    entity_kind: str
    graph_revision: str
    source_cid: str = ""
    tree_digest: str = ""


@dataclass(frozen=True, slots=True)
class SourceRevisionRow:
    revision_id: str
    repository_id: str
    revision: str
    repository_tree_cid: str = ""
    created_at: float = 0.0


@dataclass
class ProofQueryCatalog:
    """Hermetic in-memory projection of proof / graph / AST join tables.

    Used by the pure-Python evaluator so unit tests do not require DuckDB.
    Rows mirror the proofs catalog plus optional join surfaces declared by
    the control-plane plan (``graphs`` vertices-like entities and
    ``asts.source_revisions``).
    """

    entries: dict[str, UnifiedProofEntry] = field(default_factory=dict)
    # key_digest -> entry (latest); also indexed by entry_digest below
    entries_by_digest: dict[str, UnifiedProofEntry] = field(default_factory=dict)
    premises: list[PremiseRow] = field(default_factory=list)
    revocations: list[RevocationRow] = field(default_factory=list)
    graph_entities: list[GraphEntityRow] = field(default_factory=list)
    source_revisions: list[SourceRevisionRow] = field(default_factory=list)
    positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS
    negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS

    def put_entry(self, entry: UnifiedProofEntry) -> None:
        entry = entry.verify_integrity()
        self.entries[entry.key.digest] = entry
        self.entries_by_digest[entry.entry_digest] = entry
        # Materialize premises from the key when not already recorded.
        existing = {
            (p.key_digest, p.premise_digest) for p in self.premises
        }
        for ordinal, premise in enumerate(entry.key.selected_premise_digests):
            pair = (entry.key.digest, premise)
            if pair not in existing:
                self.premises.append(
                    PremiseRow(
                        key_digest=entry.key.digest,
                        premise_digest=premise,
                        premise_ordinal=ordinal,
                    )
                )
                existing.add(pair)

    def revoke(
        self,
        entry_digest: str,
        *,
        reason: str,
        revocation_id: str | None = None,
        created_at: float | None = None,
        actor_id: str = "query-catalog",
    ) -> RevocationRow:
        if not reason or not str(reason).strip():
            raise ProofQueryError("revocation reason is required")
        rid = revocation_id or f"revocation:{entry_digest}:{len(self.revocations)}"
        row = RevocationRow(
            revocation_id=rid,
            entry_digest=entry_digest,
            reason=str(reason).strip(),
            created_at=time.time() if created_at is None else float(created_at),
            actor_id=actor_id,
        )
        self.revocations.append(row)
        return row

    def latest_revocation(self, entry_digest: str) -> RevocationRow | None:
        matches = [
            r for r in self.revocations if r.entry_digest == entry_digest
        ]
        if not matches:
            return None
        return max(matches, key=lambda r: r.created_at)

    def premises_for(self, key_digest: str) -> list[PremiseRow]:
        rows = [p for p in self.premises if p.key_digest == key_digest]
        rows.sort(key=lambda p: p.premise_ordinal)
        return rows


def catalog_from_store(
    store: Any,
    *,
    graph_entities: Sequence[GraphEntityRow] = (),
    source_revisions: Sequence[SourceRevisionRow] = (),
    revocations: Sequence[RevocationRow] = (),
) -> ProofQueryCatalog:
    """Build a :class:`ProofQueryCatalog` from a :class:`DuckDBProofStore`.

    Uses the store's private entry map only when present (process-local store).
    """

    catalog = ProofQueryCatalog(
        positive_ttl_seconds=float(
            getattr(store, "positive_ttl_seconds", DEFAULT_POSITIVE_TTL_SECONDS)
        ),
        negative_ttl_seconds=float(
            getattr(store, "negative_ttl_seconds", DEFAULT_NEGATIVE_TTL_SECONDS)
        ),
    )
    entries = getattr(store, "_entries", None)
    if isinstance(entries, Mapping):
        for entry in entries.values():
            if isinstance(entry, UnifiedProofEntry):
                catalog.put_entry(entry)
    for entity in graph_entities:
        catalog.graph_entities.append(entity)
    for revision in source_revisions:
        catalog.source_revisions.append(revision)
    for revocation in revocations:
        catalog.revocations.append(revocation)
    return catalog


@dataclass(frozen=True, slots=True)
class ProofQueryResult:
    """Result set for one allowlisted proof query."""

    kind: ProofQueryKind
    rows: tuple[dict[str, Any], ...]
    truncated: bool = False
    depth_reached: int = 0
    now: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth_reached": self.depth_reached,
            "kind": self.kind.value,
            "now": self.now,
            "row_count": len(self.rows),
            "rows": [dict(row) for row in self.rows],
            "schema": DUCKDB_PROOF_QUERIES_SCHEMA,
            "schema_version": DUCKDB_PROOF_QUERIES_SCHEMA_VERSION,
            "truncated": self.truncated,
        }

    @property
    def columns_present(self) -> frozenset[str]:
        if not self.rows:
            return frozenset()
        keys: set[str] = set()
        for row in self.rows:
            keys.update(row.keys())
        return frozenset(keys)


def _entry_projection(
    entry: UnifiedProofEntry | None,
    catalog: ProofQueryCatalog,
    *,
    now: float,
) -> dict[str, Any]:
    if entry is None:
        return {
            "entry_digest": None,
            "outcome": None,
            "status": None,
            "polarity": None,
            "trust_level": ProofTrustLevel.NONE.value,
            "result_authority": "",
            "evidence_authority": "none",
            "promotable": False,
            "fresh": False,
            "age_seconds": 0.0,
            "ttl_seconds": 0.0,
            "expires_at": None,
            "created_at": 0.0,
            "applicable": False,
            "applicability_reason": "miss",
            "is_revoked": False,
            "revocation_id": None,
            "revocation_reason": None,
            "revoked_at": None,
        }
    rev = catalog.latest_revocation(entry.entry_digest)
    rev_map = None if rev is None else {
        "revocation_id": rev.revocation_id,
        "reason": rev.reason,
        "created_at": rev.created_at,
    }
    projected = project_authority_freshness(
        trust_level=entry.trust_level,
        result_authority=entry.result_authority.value,
        evidence_authority=entry.evidence_authority.value,
        polarity=entry.polarity,
        created_at=entry.created_at,
        now=now,
        positive_ttl_seconds=catalog.positive_ttl_seconds,
        negative_ttl_seconds=catalog.negative_ttl_seconds,
        revocation=rev_map,
    )
    return {
        "entry_digest": entry.entry_digest,
        "outcome": entry.outcome.value,
        "status": entry.status.value,
        "polarity": entry.polarity.value,
        **projected,
    }


def _usable_from_projection(hit: bool, projected: Mapping[str, Any]) -> bool:
    if not hit:
        return False
    if projected.get("is_revoked"):
        return False
    if not projected.get("fresh"):
        return False
    trust = str(projected.get("trust_level") or "")
    if trust in {
        ProofTrustLevel.NON_TRUSTED.value,
        ProofTrustLevel.NONE.value,
    }:
        return False
    return bool(projected.get("applicable"))


def evaluate_query(
    catalog: ProofQueryCatalog,
    kind: ProofQueryKind | str,
    *,
    key_digest: str | None = None,
    entry_digest: str | None = None,
    graph_revision: str | None = None,
    revision_id: str | None = None,
    revoked_only: bool = False,
    now: float | None = None,
    budget: ProofQueryBudget | None = None,
) -> ProofQueryResult:
    """Evaluate an allowlisted query against an in-memory catalog.

    Semantics mirror the SQL templates: authority/freshness/applicability/
    revocation are always present; recursive premise traversal is bounded;
    untrusted hits are never promotable or usable.
    """

    resolved = _resolve_kind(kind)
    current = time.time() if now is None else float(now)
    bud = budget or ProofQueryBudget()

    if resolved is ProofQueryKind.PROOF_HIT_MISS:
        return _eval_hit_miss(catalog, key_digest=key_digest, now=current)
    if resolved is ProofQueryKind.PREMISES:
        return _eval_premises(
            catalog, key_digest=key_digest, now=current, budget=bud
        )
    if resolved is ProofQueryKind.DEPENDENCY_CLOSURE:
        return _eval_dependency_closure(
            catalog, key_digest=key_digest, now=current, budget=bud
        )
    if resolved is ProofQueryKind.GRAPH_ENTITIES:
        return _eval_graph_entities(
            catalog,
            key_digest=key_digest,
            graph_revision=graph_revision,
            now=current,
            budget=bud,
        )
    if resolved is ProofQueryKind.SOURCE_REVISIONS:
        return _eval_source_revisions(
            catalog,
            key_digest=key_digest,
            revision_id=revision_id,
            now=current,
            budget=bud,
        )
    if resolved is ProofQueryKind.APPLICABILITY:
        return _eval_applicability(catalog, key_digest=key_digest, now=current)
    if resolved is ProofQueryKind.REVOCATION:
        return _eval_revocation(
            catalog,
            key_digest=key_digest,
            entry_digest=entry_digest,
            revoked_only=revoked_only,
            now=current,
            budget=bud,
        )
    if resolved is ProofQueryKind.COUNTEREXAMPLES:
        return _eval_counterexamples(
            catalog, key_digest=key_digest, now=current, budget=bud
        )
    raise ProofQueryError(f"unevaluable query kind {resolved!r}")


def _eval_hit_miss(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    now: float,
) -> ProofQueryResult:
    if not key_digest:
        raise ProofQueryError("proof_hit_miss requires key_digest")
    key = _require_digest(key_digest, "key_digest")
    entry = catalog.entries.get(key)
    hit = entry is not None
    projected = _entry_projection(entry, catalog, now=now)
    row = {
        "key_digest": key if entry is None else entry.key.digest,
        "hit": hit,
        "usable": _usable_from_projection(hit, projected),
        **projected,
    }
    # Hard invariant: untrusted hits cannot be usable or promotable.
    if hit and projected["trust_level"] in {
        ProofTrustLevel.NON_TRUSTED.value,
        ProofTrustLevel.NONE.value,
    }:
        row["usable"] = False
        row["promotable"] = False
        row["applicable"] = False
        if row["applicability_reason"] not in {"revoked", "stale"}:
            row["applicability_reason"] = "untrusted"
    return ProofQueryResult(
        kind=ProofQueryKind.PROOF_HIT_MISS,
        rows=(row,),
        now=now,
    )


def _eval_premises(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    now: float,
    budget: ProofQueryBudget,
) -> ProofQueryResult:
    if not key_digest:
        raise ProofQueryError("premises requires key_digest")
    key = _require_digest(key_digest, "key_digest")
    entry = catalog.entries.get(key)
    projected_base = _entry_projection(entry, catalog, now=now)
    rows: list[dict[str, Any]] = []
    truncated = False
    for premise in catalog.premises_for(key):
        if len(rows) >= budget.max_rows:
            truncated = True
            break
        rows.append(
            {
                "key_digest": key,
                "premise_digest": premise.premise_digest,
                "premise_ordinal": premise.premise_ordinal,
                **projected_base,
            }
        )
    return ProofQueryResult(
        kind=ProofQueryKind.PREMISES,
        rows=tuple(rows),
        truncated=truncated,
        now=now,
    )


def _eval_dependency_closure(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    now: float,
    budget: ProofQueryBudget,
) -> ProofQueryResult:
    if not key_digest:
        raise ProofQueryError("dependency_closure requires key_digest")
    root = _require_digest(key_digest, "key_digest")
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    # frontier: (parent_key_digest, depth)
    frontier: list[tuple[str, int]] = [(root, 0)]
    depth_reached = 0
    truncated = False

    while frontier:
        if time.monotonic() - started > budget.max_seconds:
            raise ProofQueryBudgetExceeded("time", budget.max_seconds)
        parent, depth = frontier.pop(0)
        if depth >= budget.max_depth:
            # Do not expand further; depth bound is hard.
            continue
        for premise in catalog.premises_for(parent):
            if time.monotonic() - started > budget.max_seconds:
                raise ProofQueryBudgetExceeded("time", budget.max_seconds)
            edge = (parent, premise.premise_digest)
            if edge in seen:
                continue
            if len(rows) >= budget.max_rows:
                truncated = True
                break
            seen.add(edge)
            child_depth = depth + 1
            depth_reached = max(depth_reached, child_depth)
            child_entry = catalog.entries.get(premise.premise_digest)
            projected = _entry_projection(child_entry, catalog, now=now)
            rows.append(
                {
                    "root_key_digest": root,
                    "parent_key_digest": parent,
                    "premise_digest": premise.premise_digest,
                    "premise_ordinal": premise.premise_ordinal,
                    "depth": child_depth,
                    **projected,
                }
            )
            # Recurse only when the premise digest is itself a proof key.
            if premise.premise_digest in catalog.entries or any(
                p.key_digest == premise.premise_digest for p in catalog.premises
            ):
                if child_depth < budget.max_depth:
                    frontier.append((premise.premise_digest, child_depth))
        if truncated:
            break

    return ProofQueryResult(
        kind=ProofQueryKind.DEPENDENCY_CLOSURE,
        rows=tuple(rows),
        truncated=truncated,
        depth_reached=depth_reached,
        now=now,
    )


def _eval_graph_entities(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    graph_revision: str | None,
    now: float,
    budget: ProofQueryBudget,
) -> ProofQueryResult:
    key_filter = _optional_text(key_digest, "key_digest")
    rev_filter = _optional_text(graph_revision, "graph_revision")
    rows: list[dict[str, Any]] = []
    truncated = False
    for entry in catalog.entries.values():
        if key_filter is not None and entry.key.digest != key_filter:
            continue
        payload = entry.result_payload.to_dict()
        entity_id_from_payload = str(payload.get("entity_id") or "")
        for entity in catalog.graph_entities:
            if rev_filter is not None and entity.graph_revision != rev_filter:
                continue
            matched = (
                entity.entity_id == entry.key.digest
                or (
                    entity.tree_digest
                    and entity.tree_digest == entry.key.tree_digest
                )
                or (
                    entity_id_from_payload
                    and entity.entity_id == entity_id_from_payload
                )
            )
            if not matched:
                continue
            if len(rows) >= budget.max_rows:
                truncated = True
                break
            projected = _entry_projection(entry, catalog, now=now)
            rows.append(
                {
                    "key_digest": entry.key.digest,
                    "entity_id": entity.entity_id,
                    "entity_kind": entity.entity_kind,
                    "graph_revision": entity.graph_revision,
                    "source_cid": entity.source_cid,
                    **projected,
                }
            )
        if truncated:
            break
    return ProofQueryResult(
        kind=ProofQueryKind.GRAPH_ENTITIES,
        rows=tuple(rows),
        truncated=truncated,
        now=now,
    )


def _eval_source_revisions(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    revision_id: str | None,
    now: float,
    budget: ProofQueryBudget,
) -> ProofQueryResult:
    key_filter = _optional_text(key_digest, "key_digest")
    rev_filter = _optional_text(revision_id, "revision_id")
    rows: list[dict[str, Any]] = []
    truncated = False
    for entry in catalog.entries.values():
        if key_filter is not None and entry.key.digest != key_filter:
            continue
        payload = entry.result_payload.to_dict()
        tree_from_payload = str(payload.get("tree_digest") or "")
        revision_from_payload = str(payload.get("revision") or "")
        for source in catalog.source_revisions:
            if rev_filter is not None and source.revision_id != rev_filter:
                continue
            matched = (
                source.revision_id == entry.key.digest
                or (
                    source.repository_tree_cid
                    and (
                        source.repository_tree_cid == entry.key.tree_digest
                        or source.repository_tree_cid == tree_from_payload
                    )
                )
                or (
                    revision_from_payload
                    and source.revision == revision_from_payload
                )
            )
            if not matched:
                continue
            if len(rows) >= budget.max_rows:
                truncated = True
                break
            projected = _entry_projection(entry, catalog, now=now)
            rows.append(
                {
                    "key_digest": entry.key.digest,
                    "revision_id": source.revision_id,
                    "repository_id": source.repository_id,
                    "revision": source.revision,
                    "repository_tree_cid": source.repository_tree_cid,
                    **projected,
                }
            )
        if truncated:
            break
    return ProofQueryResult(
        kind=ProofQueryKind.SOURCE_REVISIONS,
        rows=tuple(rows),
        truncated=truncated,
        now=now,
    )


def _eval_applicability(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    now: float,
) -> ProofQueryResult:
    if not key_digest:
        raise ProofQueryError("applicability requires key_digest")
    key = _require_digest(key_digest, "key_digest")
    entry = catalog.entries.get(key)
    projected = _entry_projection(entry, catalog, now=now)
    row = {"key_digest": key, **projected}
    return ProofQueryResult(
        kind=ProofQueryKind.APPLICABILITY,
        rows=(row,),
        now=now,
    )


def _eval_revocation(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    entry_digest: str | None,
    revoked_only: bool,
    now: float,
    budget: ProofQueryBudget,
) -> ProofQueryResult:
    key_filter = _optional_text(key_digest, "key_digest")
    entry_filter = _optional_text(entry_digest, "entry_digest")
    rows: list[dict[str, Any]] = []
    truncated = False
    for entry in catalog.entries.values():
        if key_filter is not None and entry.key.digest != key_filter:
            continue
        if entry_filter is not None and entry.entry_digest != entry_filter:
            continue
        projected = _entry_projection(entry, catalog, now=now)
        if revoked_only and not projected["is_revoked"]:
            continue
        if len(rows) >= budget.max_rows:
            truncated = True
            break
        rows.append({"key_digest": entry.key.digest, **projected})
    return ProofQueryResult(
        kind=ProofQueryKind.REVOCATION,
        rows=tuple(rows),
        truncated=truncated,
        now=now,
    )


def _eval_counterexamples(
    catalog: ProofQueryCatalog,
    *,
    key_digest: str | None,
    now: float,
    budget: ProofQueryBudget,
) -> ProofQueryResult:
    key_filter = _optional_text(key_digest, "key_digest")
    rows: list[dict[str, Any]] = []
    truncated = False
    for entry in catalog.entries.values():
        if entry.outcome is not ProofOutcomeKind.COUNTEREXAMPLE:
            continue
        if key_filter is not None and entry.key.digest != key_filter:
            continue
        if len(rows) >= budget.max_rows:
            truncated = True
            break
        projected = _entry_projection(entry, catalog, now=now)
        rows.append({"key_digest": entry.key.digest, **projected})
    return ProofQueryResult(
        kind=ProofQueryKind.COUNTEREXAMPLES,
        rows=tuple(rows),
        truncated=truncated,
        now=now,
    )


# ---------------------------------------------------------------------------
# Optional DuckDB execution (connection injected)
# ---------------------------------------------------------------------------


def execute_compiled(
    connection: Any,
    compiled: CompiledProofQuery,
) -> list[dict[str, Any]]:
    """Execute a compiled template on an injected DuckDB-like connection.

    The connection must already expose the proofs catalog tables (and join
    surfaces for graph/source queries).  Results are returned as mappings
    keyed by the template's declared result columns when available.
    """

    if connection is None:
        raise ProofQueryError("connection is required for execute_compiled")
    cursor = connection.execute(compiled.sql, list(compiled.parameters))
    description = getattr(cursor, "description", None)
    raw_rows = cursor.fetchall()
    if description:
        names = [col[0] for col in description]
    else:
        names = list(compiled.result_columns)
    results: list[dict[str, Any]] = []
    for raw in raw_rows:
        if isinstance(raw, Mapping):
            results.append(dict(raw))
        else:
            results.append(
                {
                    names[i]: raw[i]
                    for i in range(min(len(names), len(raw)))
                }
            )
    return results


def required_projection_columns() -> tuple[str, ...]:
    """Columns that every template result must always surface."""

    return COMMON_PROJECTION_COLUMNS


def templates_cover_catalog_tables() -> frozenset[str]:
    """Proof-catalog tables referenced by at least one template SQL body."""

    bodies = " ".join(t.sql for t in PROOF_QUERY_TEMPLATES.values())
    present = {name for name in PROOFS_CATALOG_TABLES if name in bodies}
    return frozenset(present)


def assert_rows_expose_authority_freshness(
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Fail closed if any row omits mandatory visibility columns."""

    required = set(COMMON_PROJECTION_COLUMNS)
    for index, row in enumerate(rows):
        missing = required - set(row.keys())
        if missing:
            raise ProofQueryError(
                f"row {index} missing mandatory columns: "
                f"{sorted(missing)}"
            )


__all__ = [
    "AUTHORITY_COLUMNS",
    "APPLICABILITY_COLUMNS",
    "COMMON_PROJECTION_COLUMNS",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_SECONDS",
    "DUCKDB_PROOF_QUERIES_INTERFACE",
    "DUCKDB_PROOF_QUERIES_SCHEMA",
    "DUCKDB_PROOF_QUERIES_SCHEMA_VERSION",
    "FRESHNESS_COLUMNS",
    "PROOF_QUERY_TEMPLATES",
    "PROOFS_CATALOG_NAME",
    "ProofQueryBudget",
    "ProofQueryBudgetExceeded",
    "ProofQueryCatalog",
    "ProofQueryError",
    "ProofQueryKind",
    "ProofQueryResult",
    "ProofQueryTemplate",
    "REVOCATION_COLUMNS",
    "CompiledProofQuery",
    "GraphEntityRow",
    "PremiseRow",
    "RevocationRow",
    "SourceRevisionRow",
    "assert_rows_expose_authority_freshness",
    "catalog_from_store",
    "compile_query",
    "evaluate_query",
    "execute_compiled",
    "get_template",
    "is_promotable_trust",
    "list_query_kinds",
    "project_authority_freshness",
    "promote_untrusted_hit",
    "required_projection_columns",
    "templates_cover_catalog_tables",
    "ttl_for_polarity",
]
