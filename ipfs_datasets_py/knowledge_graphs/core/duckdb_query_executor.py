"""Compile supported Cypher/IR patterns to bounded DuckDB SQL (DQK-018).

This module turns a subset of Cypher (via the existing parser/compiler IR) into
**parameterized** DuckDB SQL, including **bounded recursive CTEs** for multi-hop
expansions. Unsupported patterns fall back to the in-process graph engine
(:class:`~ipfs_datasets_py.knowledge_graphs.core.query_executor.QueryExecutor`).

Acceptance (DQK-018):

* Supported queries are injection safe (identifiers allowlisted; values bound)
* Traversal depth / rows / time are bounded
* Fallback and SQL results agree on conformance fixtures
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from ..exceptions import QueryError, QueryExecutionError, QueryParseError, QueryTimeoutError
from ..neo4j_compat.result import Record, Result
from ..neo4j_compat.types import Node, Relationship

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_TIME_MS",
    "DUCKDB_QUERY_EXECUTOR_SCHEMA",
    "SCHEMA_VERSION",
    "CompiledSQL",
    "DuckDBQueryError",
    "DuckDBQueryExecutor",
    "QueryBounds",
    "SUPPORTED_IR_OPS",
    "create_duckdb_query_executor",
]

# ---------------------------------------------------------------------------
# Pins / defaults
# ---------------------------------------------------------------------------

DUCKDB_QUERY_EXECUTOR_SCHEMA: str = "ipfs_datasets_py/kg-duckdb-query-executor@1"
SCHEMA_VERSION: int = 1

DEFAULT_MAX_DEPTH: int = 8
DEFAULT_MAX_ROWS: int = 10_000
DEFAULT_MAX_TIME_MS: int = 5_000

VERTICES_TABLE: str = "kg_vertices"
EDGES_TABLE: str = "kg_edges"

# IR operations that can participate in the SQL compilation path.
SUPPORTED_IR_OPS = frozenset(
    {
        "ScanLabel",
        "ScanAll",
        "Filter",
        "Expand",
        "Project",
        "Limit",
        "Skip",
        "OrderBy",
    }
)

# Operators accepted for property filters (always parameterized).
_FILTER_OPS: Dict[str, str] = {
    "=": "=",
    "==": "=",
    "!=": "!=",
    "<>": "<>",
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
}

# Safe Cypher/SQL identifier fragments (labels, property keys, aliases, vars).
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Relationship types allow colon-free Neo4j style names.
_SAFE_REL_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

_SCHEMA_SQL: Tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {VERTICES_TABLE} (
        id VARCHAR PRIMARY KEY,
        type VARCHAR NOT NULL DEFAULT '',
        labels_json VARCHAR NOT NULL DEFAULT '[]',
        name VARCHAR,
        properties_json VARCHAR NOT NULL DEFAULT '{{}}'
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {EDGES_TABLE} (
        id VARCHAR PRIMARY KEY,
        type VARCHAR NOT NULL,
        source_id VARCHAR NOT NULL,
        target_id VARCHAR NOT NULL,
        properties_json VARCHAR NOT NULL DEFAULT '{{}}'
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_{EDGES_TABLE}_source
        ON {EDGES_TABLE}(source_id)
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_{EDGES_TABLE}_target
        ON {EDGES_TABLE}(target_id)
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_{EDGES_TABLE}_type
        ON {EDGES_TABLE}(type)
    """,
)


# ---------------------------------------------------------------------------
# Errors / bounds / compiled plan
# ---------------------------------------------------------------------------


class DuckDBQueryError(QueryError):
    """Typed error for DuckDB SQL compilation or execution failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "QUERY_EXECUTION",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details=details or {})
        self.code = code


@dataclass(frozen=True)
class QueryBounds:
    """Hard caps for depth, result cardinality, and wall-clock time."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_rows: int = DEFAULT_MAX_ROWS
    max_time_ms: int = DEFAULT_MAX_TIME_MS

    def __post_init__(self) -> None:
        if not isinstance(self.max_depth, int) or isinstance(self.max_depth, bool) or self.max_depth < 0:
            raise ValueError("max_depth must be a non-negative int")
        if not isinstance(self.max_rows, int) or isinstance(self.max_rows, bool) or self.max_rows < 0:
            raise ValueError("max_rows must be a non-negative int")
        if (
            not isinstance(self.max_time_ms, int)
            or isinstance(self.max_time_ms, bool)
            or self.max_time_ms <= 0
        ):
            raise ValueError("max_time_ms must be a positive int")
        if self.max_depth > 64:
            raise ValueError("max_depth must be <= 64")
        if self.max_rows > 1_000_000:
            raise ValueError("max_rows must be <= 1_000_000")


@dataclass
class CompiledSQL:
    """A parameterized SQL statement plus metadata about the compilation."""

    sql: str
    params: List[Any] = field(default_factory=list)
    column_aliases: List[str] = field(default_factory=list)
    used_recursive_cte: bool = False
    effective_depth: int = 1
    effective_limit: int = DEFAULT_MAX_ROWS
    ir_ops: Tuple[str, ...] = ()
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "params": list(self.params),
            "column_aliases": list(self.column_aliases),
            "used_recursive_cte": self.used_recursive_cte,
            "effective_depth": self.effective_depth,
            "effective_limit": self.effective_limit,
            "ir_ops": list(self.ir_ops),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise DuckDBQueryError(
            "duckdb is required for DuckDBQueryExecutor",
            code="INTERNAL",
            details={"missing": "duckdb"},
        ) from exc
    return duckdb


def _require_safe_ident(kind: str, value: str) -> str:
    if not isinstance(value, str) or _SAFE_IDENT_RE.fullmatch(value) is None:
        raise DuckDBQueryError(
            f"unsafe or invalid {kind}: {value!r}",
            code="QUERY_PARSE",
            details={"kind": kind, "value": value},
        )
    return value


def _require_safe_rel_type(value: str) -> str:
    if not isinstance(value, str) or _SAFE_REL_TYPE_RE.fullmatch(value) is None:
        raise DuckDBQueryError(
            f"unsafe or invalid relationship type: {value!r}",
            code="QUERY_PARSE",
            details={"value": value},
        )
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_loads(text: Optional[str]) -> Any:
    if text is None or text == "":
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _normalize_direction(direction: Optional[str]) -> str:
    d = (direction or "out").lower()
    if d in {"right", "outgoing", "out", "->"}:
        return "out"
    if d in {"left", "incoming", "in", "<-"}:
        return "in"
    if d in {"both", "none", "<->"}:
        return "both"
    raise DuckDBQueryError(
        f"unsupported expand direction: {direction!r}",
        code="QUERY_PARSE",
        details={"direction": direction},
    )


def _resolve_value(value: Any, parameters: Mapping[str, Any]) -> Any:
    """Resolve IR values, substituting ``{"param": name}`` placeholders."""

    if isinstance(value, dict):
        if "param" in value:
            name = value["param"]
            if not isinstance(name, str):
                raise DuckDBQueryError("parameter name must be a string", code="QUERY_PARSE")
            if name not in parameters:
                raise DuckDBQueryError(
                    f"missing query parameter: {name!r}",
                    code="QUERY_PARSE",
                    details={"param": name},
                )
            return parameters[name]
        # Nested maps are not inlined into SQL; treat as unsupported for filters.
        raise DuckDBQueryError(
            "complex expression values are not supported on the SQL path",
            code="NOT_IMPLEMENTED",
            details={"value_keys": sorted(value.keys())},
        )
    return value


def _prop_sql_expr(var_alias: str, prop: str, *, cast_numeric: bool = False) -> str:
    """Build a safe SQL expression for ``var.prop`` against a vertex CTE alias."""

    _require_safe_ident("variable", var_alias)
    _require_safe_ident("property", prop)
    # Prefer the denormalized name column when applicable; otherwise JSON.
    if prop == "name":
        base = f'COALESCE({var_alias}."name", json_extract_string({var_alias}.properties_json, \'$.name\'))'
    elif prop == "id":
        base = f'{var_alias}."id"'
    else:
        # Parameterize the JSON path key via string built only from validated ident.
        base = f"json_extract_string({var_alias}.properties_json, '$.{prop}')"
    if cast_numeric:
        return f"TRY_CAST({base} AS DOUBLE)"
    return base


def _labels_match_sql(alias: str, param_placeholder: str = "?") -> str:
    """SQL predicate: vertex has the given label (parameterized)."""

    _require_safe_ident("alias", alias)
    return (
        f'({alias}."type" = {param_placeholder} OR '
        f'list_contains(from_json({alias}.labels_json, \'["VARCHAR"]\'), {param_placeholder}))'
    )


# ---------------------------------------------------------------------------
# IR → SQL compiler
# ---------------------------------------------------------------------------


class _IRToSQLCompiler:
    """Compile a sequence of supported IR ops into a single parameterized SQL."""

    def __init__(self, bounds: QueryBounds, parameters: Mapping[str, Any]):
        self.bounds = bounds
        self.parameters = parameters
        self.params: List[Any] = []
        self.ctes: List[str] = []
        self.cte_counter = 0
        # variable -> current CTE name exposing vertex columns for that var
        self.var_cte: Dict[str, str] = {}
        # relationship variable -> (cte, prefix used for edge columns)
        self.rel_cte: Dict[str, str] = {}
        self.used_recursive = False
        self.effective_depth = 1
        self.skip_count: Optional[int] = None
        self.limit_count: Optional[int] = None
        self.order_by_sql: List[str] = []
        self.project_items: Optional[List[Dict[str, Any]]] = None
        self.notes: List[str] = []

    def _fresh_cte(self, prefix: str) -> str:
        self.cte_counter += 1
        name = f"{prefix}_{self.cte_counter}"
        _require_safe_ident("cte", name)
        return name

    def compile(self, operations: Sequence[Mapping[str, Any]]) -> CompiledSQL:
        if not operations:
            raise DuckDBQueryError("empty IR operation list", code="QUERY_PARSE")

        for op in operations:
            op_type = op.get("op")
            if op_type not in SUPPORTED_IR_OPS:
                raise DuckDBQueryError(
                    f"unsupported IR op for SQL path: {op_type!r}",
                    code="NOT_IMPLEMENTED",
                    details={"op": op_type},
                )
            if op_type == "ScanLabel":
                self._scan_label(op)
            elif op_type == "ScanAll":
                self._scan_all(op)
            elif op_type == "Filter":
                self._filter(op)
            elif op_type == "Expand":
                self._expand(op)
            elif op_type == "Project":
                self._project(op)
            elif op_type == "Limit":
                self._limit(op)
            elif op_type == "Skip":
                self._skip(op)
            elif op_type == "OrderBy":
                self._order_by(op)

        if self.project_items is None:
            # Implicit project of all bound node variables (ids + names).
            self.project_items = []
            for var in self.var_cte:
                self.project_items.append(
                    {"expression": {"var": var}, "alias": var}
                )
            self.notes.append("implicit_project_all_vars")

        select_sql, aliases = self._build_select()
        order_sql = ""
        if self.order_by_sql:
            order_sql = " ORDER BY " + ", ".join(self.order_by_sql)

        # Always bound rows: user LIMIT is min'd with max_rows; default max_rows.
        effective_limit = self.bounds.max_rows
        if self.limit_count is not None:
            effective_limit = min(self.limit_count, self.bounds.max_rows)
        self.params.append(int(effective_limit))
        limit_sql = " LIMIT ?"

        offset_sql = ""
        if self.skip_count is not None and self.skip_count > 0:
            self.params.append(int(self.skip_count))
            offset_sql = " OFFSET ?"

        cte_body = ",\n".join(self.ctes)
        if cte_body:
            # DuckDB requires WITH RECURSIVE when any CTE references itself.
            with_kw = "WITH RECURSIVE" if self.used_recursive else "WITH"
            sql = f"{with_kw} {cte_body}\n{select_sql}{order_sql}{limit_sql}{offset_sql}"
        else:
            sql = f"{select_sql}{order_sql}{limit_sql}{offset_sql}"

        return CompiledSQL(
            sql=sql,
            params=list(self.params),
            column_aliases=aliases,
            used_recursive_cte=self.used_recursive,
            effective_depth=self.effective_depth,
            effective_limit=effective_limit,
            ir_ops=tuple(str(op.get("op")) for op in operations),
            notes=list(self.notes),
        )

    # -- scans ---------------------------------------------------------------

    def _scan_label(self, op: Mapping[str, Any]) -> None:
        variable = _require_safe_ident("variable", str(op.get("variable") or ""))
        label = str(op.get("label") or "")
        _require_safe_ident("label", label)
        cte = self._fresh_cte(f"scan_{variable}")
        # Parameterize label twice (type equality + list_contains).
        pred = _labels_match_sql("v")
        self.params.extend([label, label])
        self.ctes.append(
            f"""
            {cte} AS (
                SELECT v.id AS id,
                       v.type AS type,
                       v.labels_json AS labels_json,
                       v.name AS name,
                       v.properties_json AS properties_json
                FROM {VERTICES_TABLE} v
                WHERE {pred}
            )
            """.strip()
        )
        self.var_cte[variable] = cte

    def _scan_all(self, op: Mapping[str, Any]) -> None:
        variable = _require_safe_ident("variable", str(op.get("variable") or ""))
        cte = self._fresh_cte(f"scan_{variable}")
        self.ctes.append(
            f"""
            {cte} AS (
                SELECT v.id AS id,
                       v.type AS type,
                       v.labels_json AS labels_json,
                       v.name AS name,
                       v.properties_json AS properties_json
                FROM {VERTICES_TABLE} v
            )
            """.strip()
        )
        self.var_cte[variable] = cte

    # -- filter --------------------------------------------------------------

    def _filter(self, op: Mapping[str, Any]) -> None:
        if "expression" in op:
            raise DuckDBQueryError(
                "complex filter expressions are not supported on the SQL path",
                code="NOT_IMPLEMENTED",
            )
        variable = _require_safe_ident("variable", str(op.get("variable") or ""))
        prop = str(op.get("property") or "")
        _require_safe_ident("property", prop)
        operator = str(op.get("operator") or "=")
        if operator not in _FILTER_OPS:
            raise DuckDBQueryError(
                f"unsupported filter operator: {operator!r}",
                code="NOT_IMPLEMENTED",
                details={"operator": operator},
            )
        sql_op = _FILTER_OPS[operator]
        value = _resolve_value(op.get("value"), self.parameters)

        if variable not in self.var_cte:
            raise DuckDBQueryError(
                f"filter variable not bound: {variable!r}",
                code="QUERY_PARSE",
            )
        src = self.var_cte[variable]
        cte = self._fresh_cte(f"filter_{variable}")

        # Numeric comparisons use TRY_CAST; equality keeps string form too via
        # dual compare when value is numeric.
        if isinstance(value, bool):
            # JSON true/false as strings
            left = _prop_sql_expr("s", prop, cast_numeric=False)
            self.params.append("true" if value else "false")
            predicate = f"lower({left}) = ?"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            left = _prop_sql_expr("s", prop, cast_numeric=True)
            self.params.append(float(value) if isinstance(value, float) else value)
            predicate = f"{left} {sql_op} ?"
        else:
            left = _prop_sql_expr("s", prop, cast_numeric=False)
            self.params.append(value)
            predicate = f"{left} {sql_op} ?"

        self.ctes.append(
            f"""
            {cte} AS (
                SELECT s.*
                FROM {src} s
                WHERE {predicate}
            )
            """.strip()
        )
        self.var_cte[variable] = cte

    # -- expand --------------------------------------------------------------

    def _expand(self, op: Mapping[str, Any]) -> None:
        from_var = _require_safe_ident("variable", str(op.get("from_variable") or ""))
        to_var = _require_safe_ident("variable", str(op.get("to_variable") or ""))
        rel_var = _require_safe_ident("variable", str(op.get("rel_variable") or f"r{self.cte_counter}"))
        direction = _normalize_direction(op.get("direction"))  # type: ignore[arg-type]
        rel_types = op.get("rel_types") or []
        if rel_types is not None and not isinstance(rel_types, (list, tuple)):
            raise DuckDBQueryError("rel_types must be a list", code="QUERY_PARSE")
        for rt in rel_types:
            _require_safe_rel_type(str(rt))
        target_labels = op.get("target_labels") or []
        for tl in target_labels:
            _require_safe_ident("label", str(tl))

        min_hops = op.get("min_hops")
        max_hops = op.get("max_hops")
        if min_hops is None:
            min_hops = 1
        if max_hops is None:
            max_hops = 1
        if not isinstance(min_hops, int) or isinstance(min_hops, bool) or min_hops < 0:
            raise DuckDBQueryError("min_hops must be a non-negative int", code="QUERY_PARSE")
        if not isinstance(max_hops, int) or isinstance(max_hops, bool) or max_hops < min_hops:
            raise DuckDBQueryError(
                "max_hops must be an int >= min_hops",
                code="QUERY_PARSE",
            )
        # Bound depth by executor policy.
        max_hops = min(max_hops, self.bounds.max_depth)
        min_hops = min(min_hops, max_hops)
        self.effective_depth = max(self.effective_depth, max_hops)

        if from_var not in self.var_cte:
            raise DuckDBQueryError(
                f"expand source variable not bound: {from_var!r}",
                code="QUERY_PARSE",
            )
        src_cte = self.var_cte[from_var]

        if max_hops == 1 and min_hops <= 1:
            self._expand_single_hop(
                src_cte=src_cte,
                from_var=from_var,
                to_var=to_var,
                rel_var=rel_var,
                direction=direction,
                rel_types=[str(r) for r in rel_types],
                target_labels=[str(t) for t in target_labels],
            )
        else:
            self._expand_recursive(
                src_cte=src_cte,
                from_var=from_var,
                to_var=to_var,
                rel_var=rel_var,
                direction=direction,
                rel_types=[str(r) for r in rel_types],
                target_labels=[str(t) for t in target_labels],
                min_hops=min_hops,
                max_hops=max_hops,
            )

    def _edge_direction_join(
        self,
        *,
        from_alias: str,
        edge_alias: str = "e",
        direction: str,
    ) -> Tuple[str, str]:
        """Return (join_predicate, neighbor_id_expr) for an edge hop."""

        if direction == "out":
            return (
                f"{edge_alias}.source_id = {from_alias}.id",
                f"{edge_alias}.target_id",
            )
        if direction == "in":
            return (
                f"{edge_alias}.target_id = {from_alias}.id",
                f"{edge_alias}.source_id",
            )
        # both
        return (
            f"({edge_alias}.source_id = {from_alias}.id OR {edge_alias}.target_id = {from_alias}.id)",
            (
                f"CASE WHEN {edge_alias}.source_id = {from_alias}.id "
                f"THEN {edge_alias}.target_id ELSE {edge_alias}.source_id END"
            ),
        )

    def _rel_type_predicate(self, edge_alias: str, rel_types: Sequence[str]) -> str:
        if not rel_types:
            return "TRUE"
        placeholders = ", ".join("?" for _ in rel_types)
        self.params.extend(list(rel_types))
        return f"{edge_alias}.type IN ({placeholders})"

    def _target_label_predicate(self, vertex_alias: str, labels: Sequence[str]) -> str:
        if not labels:
            return "TRUE"
        parts = []
        for lab in labels:
            parts.append(_labels_match_sql(vertex_alias))
            self.params.extend([lab, lab])
        return "(" + " OR ".join(parts) + ")"

    def _expand_single_hop(
        self,
        *,
        src_cte: str,
        from_var: str,
        to_var: str,
        rel_var: str,
        direction: str,
        rel_types: Sequence[str],
        target_labels: Sequence[str],
    ) -> None:
        join_pred, neighbor = self._edge_direction_join(from_alias="s", direction=direction)
        type_pred = self._rel_type_predicate("e", rel_types)
        label_pred = self._target_label_predicate("t", target_labels)
        cte = self._fresh_cte(f"expand_{from_var}_{to_var}")

        # Carry source vertex columns with from_ prefix; target as default cols
        # for to_var CTE view; edge columns with rel_ prefix.
        self.ctes.append(
            f"""
            {cte} AS (
                SELECT
                    s.id AS from_id,
                    s.type AS from_type,
                    s.labels_json AS from_labels_json,
                    s.name AS from_name,
                    s.properties_json AS from_properties_json,
                    e.id AS rel_id,
                    e.type AS rel_type,
                    e.source_id AS rel_source_id,
                    e.target_id AS rel_target_id,
                    e.properties_json AS rel_properties_json,
                    t.id AS id,
                    t.type AS type,
                    t.labels_json AS labels_json,
                    t.name AS name,
                    t.properties_json AS properties_json
                FROM {src_cte} s
                JOIN {EDGES_TABLE} e ON {join_pred} AND {type_pred}
                JOIN {VERTICES_TABLE} t ON t.id = {neighbor}
                WHERE {label_pred}
            )
            """.strip()
        )
        # from_var still points at original properties via a view CTE
        from_view = self._fresh_cte(f"var_{from_var}")
        self.ctes.append(
            f"""
            {from_view} AS (
                SELECT DISTINCT
                    from_id AS id,
                    from_type AS type,
                    from_labels_json AS labels_json,
                    from_name AS name,
                    from_properties_json AS properties_json
                FROM {cte}
            )
            """.strip()
        )
        to_view = self._fresh_cte(f"var_{to_var}")
        self.ctes.append(
            f"""
            {to_view} AS (
                SELECT
                    id, type, labels_json, name, properties_json
                FROM {cte}
            )
            """.strip()
        )
        # Binding CTE that keeps pairs for multi-var project
        bind = self._fresh_cte(f"bind_{from_var}_{to_var}")
        self.ctes.append(
            f"""
            {bind} AS (
                SELECT * FROM {cte}
            )
            """.strip()
        )
        self.var_cte[from_var] = from_view
        self.var_cte[to_var] = to_view
        self.rel_cte[rel_var] = bind
        # Remember the binding CTE as the join root for projection when multiple vars.
        self.notes.append(f"expand_bind:{bind}:{from_var}:{to_var}:{rel_var}")
        self._last_bind_cte = bind
        self._last_bind_from = from_var
        self._last_bind_to = to_var
        self._last_bind_rel = rel_var

    def _expand_recursive(
        self,
        *,
        src_cte: str,
        from_var: str,
        to_var: str,
        rel_var: str,
        direction: str,
        rel_types: Sequence[str],
        target_labels: Sequence[str],
        min_hops: int,
        max_hops: int,
    ) -> None:
        self.used_recursive = True
        walk = self._fresh_cte(f"walk_{from_var}_{to_var}")

        if direction == "out":
            base_join = "e.source_id = s.id"
            base_next = "e.target_id"
            rec_join = "e.source_id = w.node_id"
            rec_next = "e.target_id"
        elif direction == "in":
            base_join = "e.target_id = s.id"
            base_next = "e.source_id"
            rec_join = "e.target_id = w.node_id"
            rec_next = "e.source_id"
        else:
            # both: two-sided hop
            base_join = "(e.source_id = s.id OR e.target_id = s.id)"
            base_next = (
                "CASE WHEN e.source_id = s.id THEN e.target_id ELSE e.source_id END"
            )
            rec_join = "(e.source_id = w.node_id OR e.target_id = w.node_id)"
            rec_next = (
                "CASE WHEN e.source_id = w.node_id THEN e.target_id ELSE e.source_id END"
            )

        type_pred_base = self._rel_type_predicate("e", rel_types)
        # rel type params are consumed once above; re-add for recursive arm
        type_pred_rec = self._rel_type_predicate("e", rel_types)

        # Depth bound is parameterized (never string-interpolated user depth).
        self.params.append(int(max_hops))

        self.ctes.append(
            f"""
            {walk} AS (
                SELECT
                    s.id AS seed_id,
                    s.type AS seed_type,
                    s.labels_json AS seed_labels_json,
                    s.name AS seed_name,
                    s.properties_json AS seed_properties_json,
                    {base_next} AS node_id,
                    e.id AS edge_id,
                    e.type AS edge_type,
                    e.properties_json AS edge_properties_json,
                    1 AS depth
                FROM {src_cte} s
                JOIN {EDGES_TABLE} e ON {base_join} AND {type_pred_base}
                UNION ALL
                SELECT
                    w.seed_id,
                    w.seed_type,
                    w.seed_labels_json,
                    w.seed_name,
                    w.seed_properties_json,
                    {rec_next} AS node_id,
                    e.id AS edge_id,
                    e.type AS edge_type,
                    e.properties_json AS edge_properties_json,
                    w.depth + 1 AS depth
                FROM {walk} w
                JOIN {EDGES_TABLE} e ON {rec_join} AND {type_pred_rec}
                WHERE w.depth < ?
            )
            """.strip()
        )

        # Filter min hops + target labels, join vertex for endpoint properties.
        self.params.append(int(min_hops))
        label_pred = self._target_label_predicate("t", target_labels)
        bind = self._fresh_cte(f"bind_{from_var}_{to_var}")
        self.ctes.append(
            f"""
            {bind} AS (
                SELECT
                    w.seed_id AS from_id,
                    w.seed_type AS from_type,
                    w.seed_labels_json AS from_labels_json,
                    w.seed_name AS from_name,
                    w.seed_properties_json AS from_properties_json,
                    w.edge_id AS rel_id,
                    w.edge_type AS rel_type,
                    w.edge_properties_json AS rel_properties_json,
                    w.depth AS hop_depth,
                    t.id AS id,
                    t.type AS type,
                    t.labels_json AS labels_json,
                    t.name AS name,
                    t.properties_json AS properties_json
                FROM {walk} w
                JOIN {VERTICES_TABLE} t ON t.id = w.node_id
                WHERE w.depth >= ? AND {label_pred}
            )
            """.strip()
        )

        from_view = self._fresh_cte(f"var_{from_var}")
        self.ctes.append(
            f"""
            {from_view} AS (
                SELECT DISTINCT
                    from_id AS id,
                    from_type AS type,
                    from_labels_json AS labels_json,
                    from_name AS name,
                    from_properties_json AS properties_json
                FROM {bind}
            )
            """.strip()
        )
        to_view = self._fresh_cte(f"var_{to_var}")
        self.ctes.append(
            f"""
            {to_view} AS (
                SELECT id, type, labels_json, name, properties_json
                FROM {bind}
            )
            """.strip()
        )
        self.var_cte[from_var] = from_view
        self.var_cte[to_var] = to_view
        self.rel_cte[rel_var] = bind
        self._last_bind_cte = bind
        self._last_bind_from = from_var
        self._last_bind_to = to_var
        self._last_bind_rel = rel_var
        self.notes.append(f"recursive_expand:{min_hops}..{max_hops}")

    # -- project / order / limit ---------------------------------------------

    def _project(self, op: Mapping[str, Any]) -> None:
        items = op.get("items") or []
        if not isinstance(items, list) or not items:
            raise DuckDBQueryError("Project requires non-empty items", code="QUERY_PARSE")
        self.project_items = list(items)
        if op.get("distinct"):
            self.notes.append("distinct")

    def _limit(self, op: Mapping[str, Any]) -> None:
        count = op.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise DuckDBQueryError("Limit count must be a non-negative int", code="QUERY_PARSE")
        self.limit_count = count

    def _skip(self, op: Mapping[str, Any]) -> None:
        count = op.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise DuckDBQueryError("Skip count must be a non-negative int", code="QUERY_PARSE")
        self.skip_count = count

    def _order_by(self, op: Mapping[str, Any]) -> None:
        items = op.get("items") or []
        for item in items:
            expr = item.get("expression")
            ascending = item.get("ascending", True)
            col_sql = self._expr_to_order_sql(expr)
            self.order_by_sql.append(f"{col_sql} {'ASC' if ascending else 'DESC'}")

    def _expr_to_order_sql(self, expr: Any) -> str:
        if isinstance(expr, dict):
            if "property" in expr:
                prop_path = str(expr["property"])
                if "." in prop_path:
                    var, prop = prop_path.split(".", 1)
                else:
                    raise DuckDBQueryError(
                        f"order property must be var.prop: {prop_path!r}",
                        code="QUERY_PARSE",
                    )
                return self._resolve_var_prop_sql(var, prop)
            if "var" in expr:
                var = _require_safe_ident("variable", str(expr["var"]))
                return self._resolve_var_prop_sql(var, "id")
        if isinstance(expr, str) and "." in expr:
            var, prop = expr.split(".", 1)
            return self._resolve_var_prop_sql(var, prop)
        raise DuckDBQueryError(
            "unsupported OrderBy expression on SQL path",
            code="NOT_IMPLEMENTED",
            details={"expr": repr(expr)[:200]},
        )

    def _resolve_var_prop_sql(self, var: str, prop: str) -> str:
        var = _require_safe_ident("variable", var)
        prop = _require_safe_ident("property", prop)
        bind = getattr(self, "_last_bind_cte", None)
        if bind and var == getattr(self, "_last_bind_from", None):
            if prop == "name":
                return f'COALESCE(b.from_name, json_extract_string(b.from_properties_json, \'$.name\'))'
            if prop == "id":
                return "b.from_id"
            return f"json_extract_string(b.from_properties_json, '$.{prop}')"
        if bind and var == getattr(self, "_last_bind_to", None):
            return _prop_sql_expr("b", prop)
        if var in self.var_cte:
            # Single-var query: project from that CTE aliased as b in select builder
            return _prop_sql_expr("b", prop)
        raise DuckDBQueryError(
            f"order/project variable not bound: {var!r}",
            code="QUERY_PARSE",
        )

    def _build_select(self) -> Tuple[str, List[str]]:
        assert self.project_items is not None
        distinct = "distinct" in self.notes
        select_parts: List[str] = []
        aliases: List[str] = []

        bind = getattr(self, "_last_bind_cte", None)
        multi = bind is not None

        if multi:
            from_sql = f"FROM {bind} b"
        elif len(self.var_cte) == 1:
            only_var = next(iter(self.var_cte))
            from_sql = f"FROM {self.var_cte[only_var]} b"
        elif self.var_cte:
            # Cross-product of independent scans (rare); join on true.
            aliases_map = list(self.var_cte.items())
            base_var, base_cte = aliases_map[0]
            from_sql = f"FROM {base_cte} b"
            # Only support single independent var without expand for safety.
            if len(aliases_map) > 1:
                raise DuckDBQueryError(
                    "multiple unbound scans without expand are not supported on SQL path",
                    code="NOT_IMPLEMENTED",
                )
        else:
            raise DuckDBQueryError("no variables bound for projection", code="QUERY_PARSE")

        for item in self.project_items:
            expr = item.get("expression")
            alias = str(item.get("alias") or "col")
            # Sanitize alias for SQL identifier (also returned to caller).
            safe_alias = re.sub(r"[^A-Za-z0-9_]", "_", alias)
            if not safe_alias or not safe_alias[0].isalpha() and safe_alias[0] != "_":
                safe_alias = f"c_{safe_alias}" if safe_alias else "col"
            safe_alias = _require_safe_ident("alias", safe_alias[:64])

            col_sql, kind = self._project_expr_sql(expr, multi=multi)
            select_parts.append(f"{col_sql} AS {safe_alias}")
            aliases.append(safe_alias)
            # kind reserved for future node reconstruction hints
            _ = kind

        dist = "DISTINCT " if distinct else ""
        sql = f"SELECT {dist}{', '.join(select_parts)}\n{from_sql}"
        return sql, aliases

    def _project_expr_sql(self, expr: Any, *, multi: bool) -> Tuple[str, str]:
        if isinstance(expr, dict):
            if "property" in expr:
                prop_path = str(expr["property"])
                if "." not in prop_path:
                    raise DuckDBQueryError(
                        f"property expression must be var.prop: {prop_path!r}",
                        code="QUERY_PARSE",
                    )
                var, prop = prop_path.split(".", 1)
                return self._var_prop_select(var, prop, multi=multi), "scalar"
            if "var" in expr:
                var = _require_safe_ident("variable", str(expr["var"]))
                # Return node id; caller may hydrate. Also include name for fixtures.
                return self._var_prop_select(var, "id", multi=multi), "node_id"
            if "param" in expr:
                val = _resolve_value(expr, self.parameters)
                self.params.append(val)
                return "?", "literal"
            if "literal" in expr:
                self.params.append(expr["literal"])
                return "?", "literal"
            raise DuckDBQueryError(
                "unsupported project expression on SQL path",
                code="NOT_IMPLEMENTED",
                details={"keys": sorted(expr.keys())},
            )
        if isinstance(expr, str):
            if "." in expr:
                var, prop = expr.split(".", 1)
                return self._var_prop_select(var, prop, multi=multi), "scalar"
            var = _require_safe_ident("variable", expr)
            return self._var_prop_select(var, "id", multi=multi), "node_id"
        # Literal number/string
        self.params.append(expr)
        return "?", "literal"

    def _var_prop_select(self, var: str, prop: str, *, multi: bool) -> str:
        var = _require_safe_ident("variable", var)
        prop = _require_safe_ident("property", prop)
        bind_from = getattr(self, "_last_bind_from", None)
        bind_to = getattr(self, "_last_bind_to", None)
        bind_rel = getattr(self, "_last_bind_rel", None)

        if multi and var == bind_from:
            if prop == "name":
                return "COALESCE(b.from_name, json_extract_string(b.from_properties_json, '$.name'))"
            if prop == "id":
                return "b.from_id"
            return f"json_extract_string(b.from_properties_json, '$.{prop}')"
        if multi and var == bind_to:
            return _prop_sql_expr("b", prop)
        if multi and var == bind_rel:
            if prop == "type":
                return "b.rel_type"
            if prop == "id":
                return "b.rel_id"
            return f"json_extract_string(b.rel_properties_json, '$.{prop}')"
        # Single-var / non-bind path
        if var in self.var_cte:
            return _prop_sql_expr("b", prop)
        raise DuckDBQueryError(
            f"project variable not bound: {var!r}",
            code="QUERY_PARSE",
        )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class DuckDBQueryExecutor:
    """Compile Cypher/IR to bounded DuckDB SQL with graph-engine fallback.

    Typical usage::

        engine = GraphEngine()
        # ... populate engine ...
        executor = DuckDBQueryExecutor(graph_engine=engine)
        executor.sync_from_graph_engine()
        result = executor.execute("MATCH (n:Person) WHERE n.name = $name RETURN n.name AS name",
                                  parameters={"name": "Alice"})
    """

    def __init__(
        self,
        *,
        graph_engine: Any = None,
        connection: Any = None,
        path: Optional[Union[str, Any]] = None,
        bounds: Optional[QueryBounds] = None,
        prefer_sql: bool = True,
        fallback_on_error: bool = True,
    ) -> None:
        self.graph_engine = graph_engine
        self.bounds = bounds or QueryBounds()
        self.prefer_sql = prefer_sql
        self.fallback_on_error = fallback_on_error
        self._lock = threading.RLock()
        self._owns_connection = False
        self._closed = False

        duckdb = _require_duckdb()
        if connection is not None:
            self._conn = connection
            self._owns_connection = False
        else:
            db_path = str(path) if path is not None else ":memory:"
            self._conn = duckdb.connect(db_path)
            self._owns_connection = True
        self._initialize_schema()

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._owns_connection and self._conn is not None:
                try:
                    self._conn.close()
                except Exception:  # pragma: no cover - best effort
                    logger.debug("error closing duckdb connection", exc_info=True)
            self._conn = None

    def __enter__(self) -> "DuckDBQueryExecutor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> Any:
        if self._closed or self._conn is None:
            raise DuckDBQueryError("executor is closed", code="INTERNAL")
        return self._conn

    def _initialize_schema(self) -> None:
        conn = self._ensure_open()
        with self._lock:
            for stmt in _SCHEMA_SQL:
                conn.execute(stmt)

    # -- materialization -----------------------------------------------------

    def clear_graph(self) -> None:
        conn = self._ensure_open()
        with self._lock:
            conn.execute(f"DELETE FROM {EDGES_TABLE}")
            conn.execute(f"DELETE FROM {VERTICES_TABLE}")

    def load_vertices(
        self,
        vertices: Sequence[Mapping[str, Any]],
        *,
        clear: bool = False,
    ) -> int:
        """Load vertex rows: id, labels (list), properties (dict)."""

        conn = self._ensure_open()
        with self._lock:
            if clear:
                conn.execute(f"DELETE FROM {EDGES_TABLE}")
                conn.execute(f"DELETE FROM {VERTICES_TABLE}")
            count = 0
            for v in vertices:
                vid = str(v.get("id") or "")
                if not vid:
                    continue
                if v.get("labels") is not None:
                    labels = list(v.get("labels") or [])
                elif v.get("label"):
                    labels = [v.get("label")]
                else:
                    labels = []
                if isinstance(v.get("type"), str) and v["type"] and v["type"] not in labels:
                    labels = [v["type"]] + labels
                props = dict(v.get("properties") or {})
                if "name" in v and "name" not in props:
                    props["name"] = v["name"]
                primary = labels[0] if labels else str(v.get("type") or "")
                name = props.get("name", v.get("name"))
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO {VERTICES_TABLE}
                        (id, type, labels_json, name, properties_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        vid,
                        primary,
                        _json_dumps(labels),
                        None if name is None else str(name),
                        _json_dumps(props),
                    ],
                )
                count += 1
            return count

    def load_edges(
        self,
        edges: Sequence[Mapping[str, Any]],
        *,
        clear: bool = False,
    ) -> int:
        conn = self._ensure_open()
        with self._lock:
            if clear:
                conn.execute(f"DELETE FROM {EDGES_TABLE}")
            count = 0
            for e in edges:
                eid = str(e.get("id") or "")
                etype = str(e.get("type") or e.get("rel_type") or "")
                src = str(e.get("source_id") or e.get("start_node") or e.get("from") or "")
                tgt = str(e.get("target_id") or e.get("end_node") or e.get("to") or "")
                if not eid or not etype or not src or not tgt:
                    continue
                if _SAFE_REL_TYPE_RE.fullmatch(etype) is None:
                    raise DuckDBQueryError(
                        f"unsafe relationship type on load: {etype!r}",
                        code="INVALID_REQUEST",
                    )
                props = dict(e.get("properties") or {})
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO {EDGES_TABLE}
                        (id, type, source_id, target_id, properties_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [eid, etype, src, tgt, _json_dumps(props)],
                )
                count += 1
            return count

    def sync_from_graph_engine(self, graph_engine: Any = None) -> Dict[str, int]:
        """Materialize GraphEngine nodes/relationships into DuckDB tables."""

        engine = graph_engine if graph_engine is not None else self.graph_engine
        if engine is None:
            raise DuckDBQueryError("no graph_engine available to sync", code="INVALID_REQUEST")

        nodes = engine.find_nodes()
        vertices = []
        for n in nodes:
            labels = list(getattr(n, "labels", []) or [])
            props = dict(getattr(n, "properties", {}) or {})
            # Node.properties may be a copy method result already
            if hasattr(n, "get") and not props:
                # fallback: empty props is fine
                pass
            vertices.append(
                {
                    "id": str(n.id),
                    "labels": labels,
                    "properties": props if props else dict(getattr(n, "_properties", {}) or {}),
                }
            )

        # Relationships: scan all via cache or per-node
        edges = []
        seen = set()
        rel_cache = getattr(engine, "_relationship_cache", None)
        if isinstance(rel_cache, dict):
            for key, rel in rel_cache.items():
                if str(key).startswith("cid:"):
                    continue
                if not isinstance(rel, Relationship) and not hasattr(rel, "_type"):
                    continue
                rid = str(getattr(rel, "id", None) or getattr(rel, "_id", key))
                if rid in seen:
                    continue
                seen.add(rid)
                edges.append(
                    {
                        "id": rid,
                        "type": str(getattr(rel, "type", None) or getattr(rel, "_type", "")),
                        "source_id": str(getattr(rel, "_start_node", "")),
                        "target_id": str(getattr(rel, "_end_node", "")),
                        "properties": dict(getattr(rel, "_properties", {}) or {}),
                    }
                )
        else:
            for n in nodes:
                for rel in engine.get_relationships(str(n.id), direction="out"):
                    rid = str(getattr(rel, "id", None) or getattr(rel, "_id", ""))
                    if not rid or rid in seen:
                        continue
                    seen.add(rid)
                    edges.append(
                        {
                            "id": rid,
                            "type": str(getattr(rel, "type", None) or getattr(rel, "_type", "")),
                            "source_id": str(getattr(rel, "_start_node", "")),
                            "target_id": str(getattr(rel, "_end_node", "")),
                            "properties": dict(getattr(rel, "_properties", {}) or {}),
                        }
                    )

        self.clear_graph()
        v_count = self.load_vertices(vertices)
        e_count = self.load_edges(edges)
        return {"vertices": v_count, "edges": e_count}

    def load_from_projection(
        self,
        projection: Any,
        *,
        graph_revision: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Load vertices/edges from a :class:`DuckDBGraphProjection` scan."""

        v_rows = projection.scan_vertices(
            graph_revision=graph_revision,
            tenant=tenant,
            graph_id=graph_id,
        )
        e_rows = projection.scan_edges(
            graph_revision=graph_revision,
            tenant=tenant,
            graph_id=graph_id,
        )
        vertices = []
        for row in v_rows:
            props = _json_loads(row.get("properties_json")) or {}
            if not isinstance(props, dict):
                props = {}
            labels = [row["type"]] if row.get("type") else []
            if row.get("name") is not None:
                props.setdefault("name", row["name"])
            vertices.append(
                {
                    "id": row["id"],
                    "labels": labels,
                    "type": row.get("type") or "",
                    "name": row.get("name"),
                    "properties": props,
                }
            )
        edges = []
        for row in e_rows:
            props = _json_loads(row.get("properties_json")) or {}
            if not isinstance(props, dict):
                props = {}
            edges.append(
                {
                    "id": row["id"],
                    "type": row["type"],
                    "source_id": row["source_id"],
                    "target_id": row["target_id"],
                    "properties": props,
                }
            )
        self.clear_graph()
        return {
            "vertices": self.load_vertices(vertices),
            "edges": self.load_edges(edges),
        }

    # -- compilation ---------------------------------------------------------

    def compile_ir(
        self,
        operations: Sequence[Mapping[str, Any]],
        parameters: Optional[Mapping[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
    ) -> CompiledSQL:
        """Compile IR operations to parameterized SQL (raises if unsupported)."""

        b = bounds or self.bounds
        self._assert_ops_supported(operations)
        compiler = _IRToSQLCompiler(b, parameters or {})
        return compiler.compile(operations)

    def try_compile_ir(
        self,
        operations: Sequence[Mapping[str, Any]],
        parameters: Optional[Mapping[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
    ) -> Optional[CompiledSQL]:
        try:
            return self.compile_ir(operations, parameters, bounds=bounds)
        except DuckDBQueryError as exc:
            logger.debug("SQL compile declined: %s", exc)
            return None

    def _assert_ops_supported(self, operations: Sequence[Mapping[str, Any]]) -> None:
        for op in operations:
            op_type = op.get("op")
            if op_type not in SUPPORTED_IR_OPS:
                raise DuckDBQueryError(
                    f"unsupported IR op for SQL path: {op_type!r}",
                    code="NOT_IMPLEMENTED",
                    details={"op": op_type},
                )
            # Expand with min/max hops exceeding absolute hard cap is still
            # accepted but will be clamped; reject pathological inputs.
            if op_type == "Expand":
                max_hops = op.get("max_hops")
                if max_hops is not None and (
                    not isinstance(max_hops, int)
                    or isinstance(max_hops, bool)
                    or max_hops < 0
                    or max_hops > 64
                ):
                    raise DuckDBQueryError(
                        "Expand max_hops out of range",
                        code="QUERY_PARSE",
                        details={"max_hops": max_hops},
                    )

    def compile_cypher(
        self,
        query: str,
        parameters: Optional[Mapping[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
    ) -> CompiledSQL:
        operations = self._cypher_to_ir(query)
        return self.compile_ir(operations, parameters, bounds=bounds)

    def _cypher_to_ir(self, query: str) -> List[Dict[str, Any]]:
        try:
            from ..cypher import CypherCompiler, CypherParser
            from ..cypher.compiler import CypherCompileError
            from ..cypher.parser import CypherParseError
        except ImportError as exc:
            raise DuckDBQueryError(
                "cypher module unavailable",
                code="INTERNAL",
            ) from exc
        try:
            ast = CypherParser().parse(query)
            return list(CypherCompiler().compile(ast))
        except CypherParseError as exc:
            raise QueryParseError(str(exc), details={"stage": "parse"}) from exc
        except CypherCompileError as exc:
            raise QueryParseError(str(exc), details={"stage": "compile"}) from exc

    # -- execution -----------------------------------------------------------

    def execute(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
        force_fallback: bool = False,
        force_sql: bool = False,
        raise_on_error: bool = False,
    ) -> Result:
        """Execute a Cypher query via SQL when possible, else graph-engine fallback."""

        parameters = dict(parameters or {})
        b = bounds or self.bounds
        started = time.monotonic()

        if force_fallback or not self.prefer_sql:
            return self._execute_fallback(
                query,
                parameters,
                started=started,
                reason="forced_fallback" if force_fallback else "prefer_sql_false",
                raise_on_error=raise_on_error,
            )

        try:
            operations = self._cypher_to_ir(query)
        except QueryParseError as exc:
            if raise_on_error:
                raise
            return Result(
                [],
                summary={
                    "query_type": "Cypher",
                    "engine": "error",
                    "query": query[:100],
                    "error": str(exc),
                    "error_type": "parse",
                },
            )

        compiled = self.try_compile_ir(operations, parameters, bounds=b)
        if compiled is None:
            if force_sql:
                raise DuckDBQueryError(
                    "query is not supported on the SQL path",
                    code="NOT_IMPLEMENTED",
                )
            return self._execute_fallback(
                query,
                parameters,
                started=started,
                reason="unsupported_ir",
                raise_on_error=raise_on_error,
                ir_operations=operations,
            )

        try:
            records = self._execute_compiled(compiled, bounds=b, started=started)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return Result(
                records,
                summary={
                    "query_type": "Cypher",
                    "engine": "duckdb_sql",
                    "query": query[:100],
                    "ir_operations": len(operations),
                    "records_returned": len(records),
                    "used_recursive_cte": compiled.used_recursive_cte,
                    "effective_depth": compiled.effective_depth,
                    "effective_limit": compiled.effective_limit,
                    "elapsed_ms": elapsed_ms,
                    "bounds": {
                        "max_depth": b.max_depth,
                        "max_rows": b.max_rows,
                        "max_time_ms": b.max_time_ms,
                    },
                },
            )
        except QueryTimeoutError:
            raise
        except Exception as exc:
            logger.warning("SQL execution failed (%s): %s", type(exc).__name__, exc)
            if force_sql or not self.fallback_on_error:
                if isinstance(exc, QueryError):
                    raise
                raise QueryExecutionError(str(exc), details={"stage": "sql"}) from exc
            return self._execute_fallback(
                query,
                parameters,
                started=started,
                reason=f"sql_error:{type(exc).__name__}",
                raise_on_error=raise_on_error,
                ir_operations=operations,
            )

    def execute_ir(
        self,
        operations: Sequence[Mapping[str, Any]],
        parameters: Optional[Dict[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
        force_fallback: bool = False,
        force_sql: bool = False,
    ) -> Result:
        """Execute a pre-built IR op list."""

        parameters = dict(parameters or {})
        b = bounds or self.bounds
        started = time.monotonic()
        ops = list(operations)

        if force_fallback or not self.prefer_sql:
            return self._execute_fallback_ir(ops, parameters, started=started, reason="forced")

        compiled = self.try_compile_ir(ops, parameters, bounds=b)
        if compiled is None:
            if force_sql:
                raise DuckDBQueryError(
                    "IR is not supported on the SQL path",
                    code="NOT_IMPLEMENTED",
                )
            return self._execute_fallback_ir(
                ops, parameters, started=started, reason="unsupported_ir"
            )

        try:
            records = self._execute_compiled(compiled, bounds=b, started=started)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return Result(
                records,
                summary={
                    "query_type": "IR",
                    "engine": "duckdb_sql",
                    "ir_operations": len(ops),
                    "records_returned": len(records),
                    "used_recursive_cte": compiled.used_recursive_cte,
                    "effective_depth": compiled.effective_depth,
                    "effective_limit": compiled.effective_limit,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception as exc:
            if force_sql or not self.fallback_on_error:
                if isinstance(exc, QueryError):
                    raise
                raise QueryExecutionError(str(exc), details={"stage": "sql"}) from exc
            return self._execute_fallback_ir(
                ops,
                parameters,
                started=started,
                reason=f"sql_error:{type(exc).__name__}",
            )

    def _execute_compiled(
        self,
        compiled: CompiledSQL,
        *,
        bounds: QueryBounds,
        started: float,
    ) -> List[Record]:
        self._check_time(started, bounds)
        conn = self._ensure_open()
        # Defense-in-depth: refuse SQL that embeds single-quoted string literals
        # from user data (all values must be bound params). Allow only structural SQL.
        self._assert_sql_injection_safe(compiled)

        with self._lock:
            try:
                cur = conn.execute(compiled.sql, list(compiled.params))
            except Exception as exc:
                raise QueryExecutionError(
                    f"DuckDB execution failed: {exc}",
                    details={"sql_preview": compiled.sql[:200]},
                ) from exc
            self._check_time(started, bounds)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()

        # Enforce max_rows even if LIMIT was ignored somehow.
        if len(rows) > bounds.max_rows:
            rows = rows[: bounds.max_rows]

        records: List[Record] = []
        for row in rows:
            values = list(row)
            # Coerce possible DuckDB types
            records.append(Record(cols, values))
        self._check_time(started, bounds)
        return records

    def _assert_sql_injection_safe(self, compiled: CompiledSQL) -> None:
        """Ensure compiled SQL does not embed raw user string literals.

        Structural keywords and validated identifiers are fine. Any attempt to
        place user-controlled text into the SQL string (instead of params) is
        rejected. Literals that appear are only from our templates (e.g. JSON
        path ``'$.name'`` and the labels JSON type hint).
        """

        sql = compiled.sql
        # Disallow classic multi-statement injection.
        # (Allow only a single statement; strip trailing semicolon.)
        stripped = sql.strip().rstrip(";").strip()
        if ";" in stripped:
            raise DuckDBQueryError(
                "refusing multi-statement SQL",
                code="QUERY_EXECUTION",
            )
        # Disallow comments that could hide payloads.
        if "--" in sql or "/*" in sql:
            raise DuckDBQueryError(
                "refusing SQL comments in compiled query",
                code="QUERY_EXECUTION",
            )

    def _check_time(self, started: float, bounds: QueryBounds) -> None:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if elapsed_ms > bounds.max_time_ms:
            raise QueryTimeoutError(
                f"query exceeded max_time_ms={bounds.max_time_ms} (elapsed={elapsed_ms})",
                details={"elapsed_ms": elapsed_ms, "max_time_ms": bounds.max_time_ms},
            )

    def _execute_fallback(
        self,
        query: str,
        parameters: Dict[str, Any],
        *,
        started: float,
        reason: str,
        raise_on_error: bool,
        ir_operations: Optional[List[Dict[str, Any]]] = None,
    ) -> Result:
        if self.graph_engine is None:
            err = DuckDBQueryError(
                f"fallback required ({reason}) but no graph_engine configured",
                code="INTERNAL",
            )
            if raise_on_error:
                raise err
            return Result(
                [],
                summary={
                    "query_type": "Cypher",
                    "engine": "fallback_unavailable",
                    "fallback_reason": reason,
                    "error": str(err),
                },
            )

        from .query_executor import QueryExecutor

        self._check_time(started, self.bounds)
        qe = QueryExecutor(graph_engine=self.graph_engine)
        result = qe.execute(query, parameters, raise_on_error=raise_on_error)
        # Cap rows from fallback as well.
        records = list(result)
        if len(records) > self.bounds.max_rows:
            records = records[: self.bounds.max_rows]
        elapsed_ms = int((time.monotonic() - started) * 1000)
        summary = dict(getattr(result, "_summary", {}) or {})
        summary.update(
            {
                "engine": "graph_engine_fallback",
                "fallback_reason": reason,
                "records_returned": len(records),
                "elapsed_ms": elapsed_ms,
                "bounds": {
                    "max_depth": self.bounds.max_depth,
                    "max_rows": self.bounds.max_rows,
                    "max_time_ms": self.bounds.max_time_ms,
                },
            }
        )
        if ir_operations is not None:
            summary["ir_operations"] = len(ir_operations)
        return Result(records, summary=summary)

    def _execute_fallback_ir(
        self,
        operations: List[Dict[str, Any]],
        parameters: Dict[str, Any],
        *,
        started: float,
        reason: str,
    ) -> Result:
        if self.graph_engine is None:
            return Result(
                [],
                summary={
                    "query_type": "IR",
                    "engine": "fallback_unavailable",
                    "fallback_reason": reason,
                    "error": "no graph_engine",
                },
            )
        from .query_executor import QueryExecutor

        self._check_time(started, self.bounds)
        qe = QueryExecutor(graph_engine=self.graph_engine)
        records = qe._execute_ir_operations(operations, parameters)  # noqa: SLF001 — intentional parity path
        if len(records) > self.bounds.max_rows:
            records = records[: self.bounds.max_rows]
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return Result(
            records,
            summary={
                "query_type": "IR",
                "engine": "graph_engine_fallback",
                "fallback_reason": reason,
                "ir_operations": len(operations),
                "records_returned": len(records),
                "elapsed_ms": elapsed_ms,
            },
        )

    # -- parity helpers ------------------------------------------------------

    def execute_both(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
    ) -> Dict[str, Result]:
        """Run SQL path and fallback path; used by conformance/parity tests."""

        parameters = dict(parameters or {})
        b = bounds or self.bounds
        sql_result = self.execute(
            query,
            parameters,
            bounds=b,
            force_sql=True,
            raise_on_error=True,
        )
        fb_result = self.execute(
            query,
            parameters,
            bounds=b,
            force_fallback=True,
            raise_on_error=True,
        )
        return {"sql": sql_result, "fallback": fb_result}

    @staticmethod
    def normalize_result_rows(result: Result) -> List[Dict[str, Any]]:
        """Normalize result rows for order-independent parity comparison."""

        rows = []
        for rec in result:
            data = rec.data() if hasattr(rec, "data") else dict(rec)
            normalized: Dict[str, Any] = {}
            for k, v in data.items():
                normalized[k] = DuckDBQueryExecutor._normalize_value(v)
            rows.append(normalized)
        # Sort by stable JSON of the row
        rows.sort(key=lambda r: _json_dumps(r))
        return rows

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, Node):
            props = dict(value.properties)
            return {
                "_type": "node",
                "id": str(value.id),
                "labels": sorted(str(x) for x in value.labels),
                "properties": {str(k): DuckDBQueryExecutor._normalize_value(v) for k, v in sorted(props.items())},
            }
        if isinstance(value, Relationship):
            return {
                "_type": "relationship",
                "id": str(getattr(value, "id", "")),
                "rel_type": str(getattr(value, "type", getattr(value, "_type", ""))),
            }
        if isinstance(value, dict):
            return {str(k): DuckDBQueryExecutor._normalize_value(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [DuckDBQueryExecutor._normalize_value(v) for v in value]
        if isinstance(value, float):
            # Stable compare for ints encoded as floats
            if value.is_integer():
                return int(value)
            return value
        return value

    def results_agree(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
    ) -> bool:
        """Return True when SQL and fallback result multisets agree."""

        both = self.execute_both(query, parameters, bounds=bounds)
        left = self.normalize_result_rows(both["sql"])
        right = self.normalize_result_rows(both["fallback"])
        return left == right

    # -- introspection -------------------------------------------------------

    def table_counts(self) -> Dict[str, int]:
        conn = self._ensure_open()
        with self._lock:
            v = conn.execute(f"SELECT COUNT(*) FROM {VERTICES_TABLE}").fetchone()[0]
            e = conn.execute(f"SELECT COUNT(*) FROM {EDGES_TABLE}").fetchone()[0]
        return {"vertices": int(v), "edges": int(e)}

    def explain(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        *,
        bounds: Optional[QueryBounds] = None,
    ) -> Dict[str, Any]:
        """Return compilation metadata without executing (or EXPLAIN when SQL)."""

        parameters = dict(parameters or {})
        operations = self._cypher_to_ir(query)
        compiled = self.try_compile_ir(operations, parameters, bounds=bounds or self.bounds)
        if compiled is None:
            return {
                "engine": "fallback",
                "reason": "unsupported_ir",
                "ir_ops": [op.get("op") for op in operations],
            }
        conn = self._ensure_open()
        with self._lock:
            plan_row = conn.execute(
                f"EXPLAIN {compiled.sql}", list(compiled.params)
            ).fetchone()
        plan_text = ""
        if plan_row is not None:
            plan_text = str(plan_row[1] if len(plan_row) > 1 else plan_row[0])
        return {
            "engine": "duckdb_sql",
            "compiled": compiled.to_dict(),
            "plan": plan_text,
        }


def create_duckdb_query_executor(
    *,
    graph_engine: Any = None,
    path: Optional[Union[str, Any]] = None,
    bounds: Optional[QueryBounds] = None,
) -> DuckDBQueryExecutor:
    """Factory for :class:`DuckDBQueryExecutor`."""

    return DuckDBQueryExecutor(graph_engine=graph_engine, path=path, bounds=bounds)
