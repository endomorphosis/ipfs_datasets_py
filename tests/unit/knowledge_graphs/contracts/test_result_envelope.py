"""
KGP-003: JSON-safe query / lifecycle result envelope regressions.

Normative reference:
  docs/architecture/knowledge_graphs_service_contract.md (§5, §6)
  docs/architecture/knowledge_graphs_compatibility.md (tiers + one-service)
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pytest

# Reuse GraphTarget validators from sibling module (same contract package tests).
from tests.unit.knowledge_graphs.contracts.test_graph_target import (
    COMPAT_ADR,
    CONTRACT_VERSION,
    GraphTarget,
    LifecycleResult,
    SERVICE_CONTRACT,
    TYPED_ERROR_CODES,
    TypedError,
    _read,
)

ENVELOPE_VERSION = "kg-query-envelope/v1"
JSONLeaf = Union[None, bool, int, float, str]
JSONValue = Union[JSONLeaf, List["JSONValue"], Dict[str, "JSONValue"]]


class EnvelopeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def assert_json_safe(value: Any, *, path: str = "$") -> None:
    """Reject values that cannot round-trip through strict JSON."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise EnvelopeError(
                "NON_JSON_VALUE",
                f"non-finite float at {path}",
            )
        return
    if isinstance(value, str):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            assert_json_safe(item, path=f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EnvelopeError(
                    "NON_JSON_VALUE",
                    f"non-string dict key at {path}: {key!r}",
                )
            assert_json_safe(item, path=f"{path}.{key}")
        return
    raise EnvelopeError(
        "NON_JSON_VALUE",
        f"disallowed type {type(value).__name__} at {path}",
    )


def dumps_strict(value: Any) -> str:
    assert_json_safe(value)
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


@dataclass
class QueryResultEnvelope:
    """Versioned JSON-safe query envelope (kg-query-envelope/v1)."""

    schema: str
    target: GraphTarget
    revision: str
    columns: List[str]
    rows: List[Any]
    statistics: Dict[str, Any]
    query: Dict[str, Any]
    envelope_version: str = ENVELOPE_VERSION
    cursor: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    provenance: Optional[Dict[str, Any]] = None
    authorization_receipt_ref: Optional[str] = None
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.envelope_version != ENVELOPE_VERSION:
            raise EnvelopeError("INVALID_REQUEST", "unsupported envelope_version")
        if not self.schema:
            raise EnvelopeError("INVALID_REQUEST", "schema is required")
        if not self.revision:
            raise EnvelopeError("INVALID_REQUEST", "revision is required")
        # Target must be revision-pinned for query snapshots when revision set on envelope.
        if self.target.revision is not None and self.target.revision != self.revision:
            raise EnvelopeError(
                "INVALID_TARGET",
                "target.revision must match envelope.revision",
            )
        if self.target.branch is not None and self.target.revision is not None:
            raise EnvelopeError("INVALID_TARGET", "target must not dual-select")
        if not isinstance(self.columns, list) or not all(
            isinstance(c, str) for c in self.columns
        ):
            raise EnvelopeError("INVALID_REQUEST", "columns must be list[str]")
        if not isinstance(self.rows, list):
            raise EnvelopeError("INVALID_REQUEST", "rows must be a list")
        if "elapsed_ms" not in self.statistics:
            raise EnvelopeError("INVALID_REQUEST", "statistics.elapsed_ms is required")
        if not isinstance(self.query, dict) or "language" not in self.query:
            raise EnvelopeError("INVALID_REQUEST", "query.language is required")
        # Validate row shapes when columns are non-empty and rows are sequences.
        for idx, row in enumerate(self.rows):
            if isinstance(row, list) and self.columns:
                if len(row) != len(self.columns):
                    raise EnvelopeError(
                        "INVALID_REQUEST",
                        f"row {idx} length {len(row)} != columns {len(self.columns)}",
                    )
            elif not isinstance(row, (list, dict)):
                raise EnvelopeError(
                    "INVALID_REQUEST",
                    f"row {idx} must be list or object",
                )
        assert_json_safe(self.to_json_dict())

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_json_dict(self) -> Dict[str, Any]:
        # Prefer revision-pinned target URI in the envelope.
        target = self.target
        if target.revision is None and self.revision:
            target = GraphTarget(
                tenant=target.tenant,
                graph_id=target.graph_id,
                revision=self.revision,
                storage_profile=target.storage_profile,
            )
        return {
            "envelope_version": self.envelope_version,
            "schema": self.schema,
            "target": target.to_json_dict(),
            "revision": self.revision,
            "columns": list(self.columns),
            "rows": self.rows,
            "row_count": self.row_count,
            "cursor": self.cursor,
            "statistics": dict(self.statistics),
            "warnings": list(self.warnings),
            "provenance": self.provenance,
            "authorization_receipt_ref": self.authorization_receipt_ref,
            "truncated": self.truncated,
            "query": dict(self.query),
        }


def make_sample_envelope(**overrides: Any) -> QueryResultEnvelope:
    base = dict(
        schema="cypher-table/v1",
        target=GraphTarget(
            tenant="acme",
            graph_id="skills",
            revision="bafyreib2example000000000000000000000001",
            storage_profile="hybrid",
        ),
        revision="bafyreib2example000000000000000000000001",
        columns=["name", "score"],
        rows=[["alice", 0.91], ["bob", 0.77]],
        statistics={"elapsed_ms": 12.5, "nodes_visited": 40},
        query={
            "language": "cypher",
            "text": "MATCH (n:Person) RETURN n.name AS name, n.score AS score LIMIT 2",
            "params": {},
        },
        warnings=[],
        truncated=False,
    )
    base.update(overrides)
    return QueryResultEnvelope(**base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_service_contract_defines_query_envelope_fields() -> None:
    text = _read(SERVICE_CONTRACT)
    for field_name in (
        "envelope_version",
        "schema",
        "columns",
        "rows",
        "row_count",
        "cursor",
        "statistics",
        "warnings",
        "provenance",
        "authorization_receipt_ref",
        "truncated",
        "kg-query-envelope/v1",
    ):
        assert field_name in text, f"missing envelope field docs for {field_name}"


def test_query_envelope_round_trips_strict_json() -> None:
    env = make_sample_envelope()
    payload = env.to_json_dict()
    encoded = dumps_strict(payload)
    decoded = json.loads(encoded)
    assert decoded["envelope_version"] == ENVELOPE_VERSION
    assert decoded["row_count"] == 2
    assert decoded["target"]["uri"].startswith("kg://acme/skills/revisions/")
    assert decoded["truncated"] is False
    # Re-validate after JSON round trip
    assert_json_safe(decoded)


def test_query_envelope_rejects_non_json_row_values() -> None:
    class Node:  # neo4j-compat style object — forbidden
        pass

    with pytest.raises(EnvelopeError) as excinfo:
        make_sample_envelope(rows=[[Node(), 1]])
    assert excinfo.value.code == "NON_JSON_VALUE"

    with pytest.raises(EnvelopeError):
        make_sample_envelope(rows=[[{"nested": {1, 2}}]])  # set is forbidden

    with pytest.raises(EnvelopeError):
        make_sample_envelope(statistics={"elapsed_ms": float("nan")})

    with pytest.raises(EnvelopeError):
        make_sample_envelope(statistics={"elapsed_ms": float("inf")})


def test_query_envelope_rejects_row_column_mismatch() -> None:
    with pytest.raises(EnvelopeError) as excinfo:
        make_sample_envelope(rows=[["only_one"]])
    assert "length" in excinfo.value.message


def test_query_envelope_object_rows_allowed() -> None:
    env = make_sample_envelope(
        columns=[],
        rows=[{"name": "alice", "score": 0.91}, {"name": "bob", "score": 0.77}],
    )
    payload = env.to_json_dict()
    assert payload["row_count"] == 2
    dumps_strict(payload)


def test_query_envelope_cursor_and_truncation() -> None:
    env = make_sample_envelope(
        cursor="opaque-cursor-rev-bound-001",
        truncated=True,
        warnings=["BUDGET max_rows reached"],
        statistics={"elapsed_ms": 5.0, "bytes_read": 2048},
    )
    payload = env.to_json_dict()
    assert payload["truncated"] is True
    assert payload["cursor"] == "opaque-cursor-rev-bound-001"
    assert payload["warnings"]


def test_query_envelope_requires_elapsed_ms_and_language() -> None:
    with pytest.raises(EnvelopeError):
        make_sample_envelope(statistics={"nodes_visited": 1})
    with pytest.raises(EnvelopeError):
        make_sample_envelope(query={"text": "RETURN 1"})


def test_lifecycle_result_may_nest_query_envelope() -> None:
    env = make_sample_envelope()
    target = env.target
    result = LifecycleResult(
        status="success",
        operation="query",
        target=target,
        result=env.to_json_dict(),
        request_id="req-123",
    )
    payload = result.to_json_dict()
    dumps_strict(payload)
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["result"]["envelope_version"] == ENVELOPE_VERSION
    assert payload["result"]["rows"][0][0] == "alice"


def test_lifecycle_error_is_json_safe_with_typed_code() -> None:
    err = LifecycleResult(
        status="error",
        operation="query",
        target=None,
        error=TypedError(
            code="QUERY_PARSE",
            message="syntax error near RETURN",
            retryable=False,
            details={"line": 1, "column": 12},
        ),
        warnings=("legacy Result objects are not accepted",),
    )
    payload = err.to_json_dict()
    dumps_strict(payload)
    assert payload["error"]["code"] in TYPED_ERROR_CODES
    assert payload["status"] == "error"


@pytest.mark.parametrize(
    "code,retryable",
    [
        ("CONFLICT", True),
        ("BUDGET_EXCEEDED", True),
        ("STORAGE", True),
        ("FORBIDDEN", False),
        ("INTEGRITY", False),
        ("INVALID_TARGET", False),
    ],
)
def test_typed_error_retryable_flags_are_documented(code: str, retryable: bool) -> None:
    text = _read(SERVICE_CONTRACT)
    # Each code appears with its retryable posture in the catalog table.
    assert code in text
    err = TypedError(
        code=code,
        message="test",
        retryable=retryable,
        details={},
    )
    dumps_strict(err.to_json_dict())


def test_forbidden_python_result_object_cannot_be_envelope_row() -> None:
    """Regression for KGP-001-QUERY-JSON: neo4j Result is not JSON-safe."""

    class Result:
        def __init__(self) -> None:
            self.records = []

        def __repr__(self) -> str:
            return "Result(records=0)"

    with pytest.raises(EnvelopeError):
        make_sample_envelope(rows=[Result()])  # type: ignore[list-item]

    # Even wrapping in a success-shaped dict must fail when dumped strictly.
    bad = {
        "status": "success",
        "results": Result(),
    }
    with pytest.raises(EnvelopeError):
        assert_json_safe(bad)


def test_compatibility_tiers_and_legacy_dispositions_in_envelope_suite() -> None:
    """Envelope suite also locks the compatibility policy JSON (shared gate)."""
    text = _read(COMPAT_ADR)
    marker = '"policy_version": "kg-compatibility/v1"'
    assert marker in text
    json_start = text.rfind("```json", 0, text.index(marker))
    json_end = text.index("```", text.index(marker))
    policy = json.loads(text[text.index("{", json_start) : json_end])

    assert set(policy["tiers"]) == {"T0", "T1", "T2", "T3"}
    assert set(policy["dispositions"]) == {"adopt", "adapt", "deprecate"}
    assert policy["one_service_rule"] is True

    legacy = policy["legacy_map"]
    assert legacy["graph_engine"]["disposition"] == "adapt"
    assert legacy["extraction_knowledge_graph"]["disposition"] == "adapt"
    assert legacy["data_transformation_ipld_graph"]["disposition"] == "adapt"
    assert legacy["data_transformation_ipld_graph"]["secondary_disposition"] == "deprecate"
    assert legacy["search_graph_data_sharded_car"]["disposition"] == "adopt"
    assert legacy["search_graph_data_sharded_car"]["secondary_disposition"] == "adapt"
    assert legacy["knowledge_graph_manager"]["disposition"] == "deprecate"
    assert legacy["knowledge_graph_manager"]["replacement"]


def test_envelope_target_revision_consistency() -> None:
    with pytest.raises(EnvelopeError) as excinfo:
        make_sample_envelope(
            target=GraphTarget(
                tenant="acme",
                graph_id="skills",
                revision="bafyreib2example000000000000000000000099",
            ),
            revision="bafyreib2example000000000000000000000001",
        )
    assert excinfo.value.code == "INVALID_TARGET"


def test_bytes_and_datetime_are_rejected() -> None:
    from datetime import datetime, timezone

    with pytest.raises(EnvelopeError):
        make_sample_envelope(rows=[["x", b"raw"]])
    # ISO-8601 strings are JSON-safe; raw datetime objects are not.
    ok = make_sample_envelope(
        rows=[["x", datetime.now(timezone.utc).isoformat()]],
    )
    dumps_strict(ok.to_json_dict())
    with pytest.raises(EnvelopeError):
        assert_json_safe({"ts": datetime.now(timezone.utc)})
    with pytest.raises(EnvelopeError):
        make_sample_envelope(rows=[["x", datetime.now(timezone.utc)]])

def test_nested_params_must_be_json_safe() -> None:
    env = make_sample_envelope(
        query={
            "language": "cypher",
            "text": "RETURN $ids",
            "params": {"ids": ["a", "b"], "limit": 10, "flag": True, "n": None},
        }
    )
    dumps_strict(env.to_json_dict())

    with pytest.raises(EnvelopeError):
        make_sample_envelope(
            query={
                "language": "cypher",
                "text": "RETURN $blob",
                "params": {"blob": b"nope"},
            }
        )


def test_canonical_dumps_is_byte_stable() -> None:
    env = make_sample_envelope()
    a = dumps_strict(env.to_json_dict())
    b = dumps_strict(json.loads(a))
    assert a == b


def test_empty_result_page_is_valid() -> None:
    env = make_sample_envelope(rows=[], warnings=["no matches"])
    payload = env.to_json_dict()
    assert payload["row_count"] == 0
    assert payload["rows"] == []
    dumps_strict(payload)
