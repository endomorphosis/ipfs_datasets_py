"""KGP-016: Enforce query budgets, cursors, cancellation, and streaming.

Acceptance coverage:
* row, byte, time, depth, fan-out, memory, and shard-fetch limits
* cooperative cancellation propagation
* bounded streaming pages
* opaque cursors bound to target revision / query / authorization
* reject cursor replay against another graph or revision
* serialize statistics and typed limit errors
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

import pytest

from ipfs_datasets_py.knowledge_graphs.query.runtime import (
    RUNTIME_API_VERSION,
    BudgetExceededError,
    CancellationError,
    CancellationToken,
    CursorBinding,
    CursorCodec,
    InvalidCursorError,
    QueryBudgets,
    QueryPage,
    QueryRuntime,
    QueryRuntimeError,
    QuerySession,
    QueryStatistics,
    digest_authorization,
    digest_query,
    estimate_row_bytes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rows(n: int, *, prefix: str = "r", payload: str = "x") -> List[Dict[str, Any]]:
    return [{"id": f"{prefix}{i}", "payload": payload} for i in range(n)]


def _runtime(**kwargs: Any) -> QueryRuntime:
    return QueryRuntime(
        default_budgets=QueryBudgets(
            time_ms=5_000,
            max_rows=1_000,
            max_bytes=0,
            max_depth=8,
            max_fanout=1_000,
            max_memory_bytes=0,
            max_shard_fetches=0,
            page_size=10,
        ),
        cursor_secret=b"test-cursor-secret-kgp-016",
        **kwargs,
    )


def _session(
    rt: QueryRuntime | None = None,
    *,
    tenant: str = "acme",
    graph_id: str = "skills",
    revision: str = "rev-001",
    language: str = "scan",
    text: str = "MATCH (n) RETURN n",
    params: Dict[str, Any] | None = None,
    auth: Dict[str, Any] | None = None,
    budgets: Dict[str, Any] | QueryBudgets | None = None,
    cancel: CancellationToken | None = None,
    columns: List[str] | None = None,
    truncate_on_budget: bool | None = None,
) -> QuerySession:
    runtime = rt or _runtime()
    return runtime.open_session(
        tenant=tenant,
        graph_id=graph_id,
        revision=revision,
        language=language,
        text=text,
        params=params or {},
        auth=auth or {"principal": "alice", "ability": "graph/query"},
        budgets=budgets,
        cancel=cancel,
        columns=columns or ["id", "payload"],
        truncate_on_budget=truncate_on_budget,
    )


def _assert_json_safe(value: Any) -> None:
    encoded = json.dumps(value, allow_nan=False, sort_keys=True)
    assert isinstance(encoded, str)
    json.loads(encoded)


# ---------------------------------------------------------------------------
# API surface / budgets
# ---------------------------------------------------------------------------


def test_runtime_api_version() -> None:
    rt = _runtime()
    assert rt.api_version == RUNTIME_API_VERSION
    assert RUNTIME_API_VERSION.startswith("kg-query-runtime/")


def test_budgets_defaults_and_serialization() -> None:
    b = QueryBudgets()
    d = b.to_json_dict()
    assert d["time_ms"] == 10_000
    assert d["max_rows"] == 1_000
    assert d["max_depth"] == 8
    assert d["max_fanout"] == 10_000
    _assert_json_safe(d)


def test_budgets_reject_negatives() -> None:
    with pytest.raises(QueryRuntimeError) as ei:
        QueryBudgets(max_rows=-1)
    assert ei.value.code == "INVALID_REQUEST"


def test_budgets_narrow_only() -> None:
    base = QueryBudgets(time_ms=10_000, max_rows=500, max_depth=6, max_fanout=100)
    narrowed = base.narrow({"time_ms": 2_000, "max_rows": 9999, "max_depth": 3})
    assert narrowed.time_ms == 2_000
    assert narrowed.max_rows == 500  # cannot widen
    assert narrowed.max_depth == 3
    assert narrowed.max_fanout == 100


def test_budgets_from_mapping_timeout_alias() -> None:
    b = QueryBudgets.from_mapping({"timeout_ms": 1234, "max_rows": 50})
    assert b.time_ms == 1234
    assert b.max_rows == 50


def test_zero_unlimited_fields_narrow() -> None:
    base = QueryBudgets(max_bytes=0, max_memory_bytes=0, max_shard_fetches=0)
    narrowed = base.narrow({"max_bytes": 100, "max_memory_bytes": 200, "max_shard_fetches": 3})
    assert narrowed.max_bytes == 100
    assert narrowed.max_memory_bytes == 200
    assert narrowed.max_shard_fetches == 3
    # Further narrow.
    tighter = narrowed.narrow({"max_bytes": 50, "max_bytes_ignored": 1})
    assert tighter.max_bytes == 50


# ---------------------------------------------------------------------------
# Row / page streaming limits
# ---------------------------------------------------------------------------


def test_stream_bounded_pages() -> None:
    session = _session(budgets={"page_size": 3, "max_rows": 100})
    pages = list(session.stream_pages(_rows(10)))
    assert len(pages) == 4  # 3+3+3+1
    assert all(isinstance(p, QueryPage) for p in pages)
    assert all(p.row_count <= 3 for p in pages)
    assert sum(p.row_count for p in pages) == 10
    # Intermediate pages carry cursors; last is exhausted.
    assert pages[-1].cursor is None
    assert pages[0].cursor is not None
    for p in pages:
        _assert_json_safe(p.to_json_dict())


def test_max_rows_soft_truncate() -> None:
    session = _session(budgets={"max_rows": 5, "page_size": 10}, truncate_on_budget=True)
    pages = list(session.stream_pages(_rows(20)))
    assert len(pages) == 1
    assert pages[0].row_count == 5
    assert pages[0].truncated is True
    assert pages[0].cursor is None
    assert session.usage.truncated_budget == "max_rows"
    assert pages[0].statistics.truncated is True


def test_max_rows_hard_error_when_not_truncating() -> None:
    session = _session(budgets={"max_rows": 2, "page_size": 10}, truncate_on_budget=False)
    with pytest.raises(BudgetExceededError) as ei:
        list(session.stream_pages(_rows(5)))
    assert ei.value.code == "BUDGET_EXCEEDED"
    assert ei.value.budget == "max_rows"
    assert ei.value.details["limit"] == 2
    _assert_json_safe(ei.value.to_json_dict())


def test_page_from_sequence_returns_first_page_with_cursor() -> None:
    session = _session(budgets={"page_size": 2, "max_rows": 100})
    page = session.page_from_sequence(_rows(5))
    assert page.row_count == 2
    assert page.cursor is not None
    # Continue with cursor.
    page2 = session.page_from_sequence(_rows(5), cursor=page.cursor)
    assert page2.row_count == 2
    assert [r["id"] for r in page2.rows] == ["r2", "r3"]


# ---------------------------------------------------------------------------
# Byte budget
# ---------------------------------------------------------------------------


def test_max_bytes_splits_pages() -> None:
    # Each row is large enough that only one fits under max_bytes.
    big = "Z" * 200
    rows = _rows(3, payload=big)
    one = estimate_row_bytes(rows[0])
    session = _session(
        budgets={"max_bytes": one + 10, "page_size": 50, "max_rows": 100},
        truncate_on_budget=True,
    )
    pages = list(session.stream_pages(rows))
    assert len(pages) >= 2
    assert all(p.row_count == 1 for p in pages[:-1] or pages)
    assert sum(p.row_count for p in pages) == 3


def test_single_row_exceeding_max_bytes_errors() -> None:
    row = {"id": "huge", "payload": "Q" * 5000}
    size = estimate_row_bytes(row)
    session = _session(budgets={"max_bytes": max(8, size // 4), "page_size": 10})
    with pytest.raises(BudgetExceededError) as ei:
        list(session.stream_pages([row]))
    assert ei.value.budget == "max_bytes"
    assert ei.value.code == "BUDGET_EXCEEDED"
    err = ei.value.to_typed_dict()
    assert err["retryable"] is True
    assert "actual" in err["details"]
    _assert_json_safe(err)


# ---------------------------------------------------------------------------
# Time budget
# ---------------------------------------------------------------------------


def test_time_budget_exceeded() -> None:
    # Controlled clock: freeze then jump past limit.
    ticks = {"t": 100.0}

    def clock() -> float:
        return ticks["t"]

    rt = QueryRuntime(
        default_budgets=QueryBudgets(time_ms=50, max_rows=100, page_size=10),
        cursor_secret=b"t",
        clock=clock,
    )
    session = _session(rt, budgets={"time_ms": 50})

    def slow_rows():
        yield {"id": "a"}
        ticks["t"] += 1.0  # +1000 ms
        yield {"id": "b"}

    with pytest.raises(BudgetExceededError) as ei:
        list(session.stream_pages(slow_rows()))
    assert ei.value.budget == "time_ms"
    assert ei.value.unit == "ms"
    assert ei.value.code == "BUDGET_EXCEEDED"


# ---------------------------------------------------------------------------
# Depth / fan-out / memory / shard-fetch
# ---------------------------------------------------------------------------


def test_depth_limit() -> None:
    session = _session(budgets={"max_depth": 2})
    session.record_depth(1)
    session.record_depth(2)
    with pytest.raises(BudgetExceededError) as ei:
        session.record_depth(3)
    assert ei.value.budget == "max_depth"
    assert ei.value.details["limit"] == 2


def test_fanout_limit() -> None:
    session = _session(budgets={"max_fanout": 5})
    session.record_fanout(3)
    session.record_fanout(5)
    assert session.usage.fanout == 5
    with pytest.raises(BudgetExceededError) as ei:
        session.record_fanout(6)
    assert ei.value.budget == "max_fanout"


def test_memory_limit() -> None:
    session = _session(budgets={"max_memory_bytes": 100})
    session.record_memory(50)
    with pytest.raises(BudgetExceededError) as ei:
        session.record_memory(101)
    assert ei.value.budget == "max_memory_bytes"
    assert ei.value.unit == "B"


def test_shard_fetch_limit() -> None:
    session = _session(budgets={"max_shard_fetches": 2})
    session.record_shard_fetch(1)
    session.record_shard_fetch(1)
    with pytest.raises(BudgetExceededError) as ei:
        session.record_shard_fetch(1)
    assert ei.value.budget == "max_shard_fetches"
    assert session.usage.shard_fetches == 3


def test_check_all_hard_aggregates() -> None:
    session = _session(budgets={"max_depth": 1, "max_fanout": 1, "max_shard_fetches": 1})
    session.usage.depth = 2
    with pytest.raises(BudgetExceededError) as ei:
        session.check_all_hard()
    assert ei.value.budget == "max_depth"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancellation_before_stream() -> None:
    token = CancellationToken()
    token.cancel("client disconnect")
    session = _session(cancel=token)
    with pytest.raises(CancellationError) as ei:
        list(session.stream_pages(_rows(5)))
    assert ei.value.code == "CANCELLED"
    assert "disconnect" in ei.value.message
    assert session.usage.cancelled is True
    _assert_json_safe(ei.value.to_json_dict())


def test_cancellation_mid_stream() -> None:
    token = CancellationToken()
    session = _session(cancel=token, budgets={"page_size": 1})

    def rows():
        yield {"id": "1"}
        token.cancel("stop")
        yield {"id": "2"}
        yield {"id": "3"}

    pages: List[QueryPage] = []
    with pytest.raises(CancellationError):
        for page in session.stream_pages(rows()):
            pages.append(page)
    assert len(pages) >= 1
    assert session.usage.cancelled is True


def test_cancellation_token_is_sticky() -> None:
    token = CancellationToken()
    assert token.is_cancelled is False
    token.cancel("once")
    token.cancel("twice")
    assert token.is_cancelled is True
    assert token.reason == "once"
    with pytest.raises(CancellationError):
        token.check()


# ---------------------------------------------------------------------------
# Opaque cursors bound to revision / query / authorization
# ---------------------------------------------------------------------------


def test_cursor_roundtrip_and_continuation() -> None:
    rt = _runtime()
    session = _session(rt, budgets={"page_size": 2, "max_rows": 100})
    pages = list(session.stream_pages(_rows(5)))
    assert pages[0].cursor is not None
    # New session with same binding can open the cursor.
    session2 = _session(rt, budgets={"page_size": 2, "max_rows": 100})
    state = session2.open_cursor(pages[0].cursor)
    assert state.offset == 2
    page2 = session2.page_from_sequence(_rows(5), cursor=pages[0].cursor)
    assert [r["id"] for r in page2.rows] == ["r2", "r3"]


def test_cursor_rejects_different_revision() -> None:
    rt = _runtime()
    session = _session(rt, revision="rev-001", budgets={"page_size": 1})
    page = session.page_from_sequence(_rows(3))
    assert page.cursor is not None

    other = _session(rt, revision="rev-002", budgets={"page_size": 1})
    with pytest.raises(InvalidCursorError) as ei:
        other.open_cursor(page.cursor)
    assert ei.value.code == "INVALID_REQUEST"
    assert "mismatches" in ei.value.details
    assert "revision" in ei.value.details["mismatches"]
    _assert_json_safe(ei.value.to_json_dict())


def test_cursor_rejects_different_graph() -> None:
    rt = _runtime()
    session = _session(rt, graph_id="skills", budgets={"page_size": 1})
    page = session.page_from_sequence(_rows(3))
    other = _session(rt, graph_id="othergraph", budgets={"page_size": 1})
    with pytest.raises(InvalidCursorError) as ei:
        other.open_cursor(page.cursor)
    assert ei.value.code == "INVALID_REQUEST"
    assert "graph_id" in ei.value.details["mismatches"]


def test_cursor_rejects_different_tenant() -> None:
    rt = _runtime()
    session = _session(rt, tenant="acme", budgets={"page_size": 1})
    page = session.page_from_sequence(_rows(2))
    other = _session(rt, tenant="other", budgets={"page_size": 1})
    with pytest.raises(InvalidCursorError) as ei:
        other.open_cursor(page.cursor)
    assert "tenant" in ei.value.details["mismatches"]


def test_cursor_rejects_different_query() -> None:
    rt = _runtime()
    session = _session(rt, text="MATCH (n) RETURN n", budgets={"page_size": 1})
    page = session.page_from_sequence(_rows(2))
    other = _session(rt, text="MATCH (m) RETURN m", budgets={"page_size": 1})
    with pytest.raises(InvalidCursorError) as ei:
        other.open_cursor(page.cursor)
    assert "query_digest" in ei.value.details["mismatches"]


def test_cursor_rejects_different_authorization() -> None:
    rt = _runtime()
    session = _session(
        rt,
        auth={"principal": "alice", "ability": "graph/query"},
        budgets={"page_size": 1},
    )
    page = session.page_from_sequence(_rows(2))
    other = _session(
        rt,
        auth={"principal": "bob", "ability": "graph/query"},
        budgets={"page_size": 1},
    )
    with pytest.raises(InvalidCursorError) as ei:
        other.open_cursor(page.cursor)
    assert "authorization_digest" in ei.value.details["mismatches"]


def test_cursor_rejects_tampered_token() -> None:
    rt = _runtime()
    session = _session(rt, budgets={"page_size": 1})
    page = session.page_from_sequence(_rows(2))
    assert page.cursor is not None
    # Flip a character in the MAC portion.
    bad = page.cursor[:-2] + ("A" if page.cursor[-2] != "A" else "B") + page.cursor[-1]
    with pytest.raises(InvalidCursorError) as ei:
        session.open_cursor(bad)
    assert ei.value.code == "INVALID_REQUEST"


def test_cursor_rejects_malformed() -> None:
    session = _session()
    with pytest.raises(InvalidCursorError):
        session.open_cursor("not-a-cursor")
    with pytest.raises(InvalidCursorError):
        session.open_cursor("kgc1.@@@.@@@")


def test_cursor_codec_state_roundtrip() -> None:
    codec = CursorCodec(b"secret")
    binding = CursorBinding.from_target(
        tenant="acme",
        graph_id="skills",
        revision="rev-1",
        query_digest=digest_query("scan", "q"),
        authorization_digest=digest_authorization({"principal": "p"}),
    )
    token = codec.encode(binding, offset=7, state={"shard": "s1", "page": 2})
    state = codec.decode(token, expected=binding)
    assert state.offset == 7
    assert state.state == {"shard": "s1", "page": 2}


def test_empty_cursor_starts_at_zero() -> None:
    session = _session()
    assert session.open_cursor(None).offset == 0
    assert session.open_cursor("").offset == 0


# ---------------------------------------------------------------------------
# Statistics serialization
# ---------------------------------------------------------------------------


def test_statistics_are_json_safe_and_complete() -> None:
    session = _session(budgets={"page_size": 2, "max_rows": 10})
    session.record_nodes(4)
    session.record_edges(3)
    session.record_depth(1)
    session.record_fanout(2)
    session.record_shard_fetch(1)
    list(session.stream_pages(_rows(5)))
    stats = session.statistics(extra={"plan_hash": "abc"})
    payload = stats.to_json_dict()
    _assert_json_safe(payload)
    assert payload["rows_emitted"] == 5
    assert payload["nodes_visited"] == 4
    assert payload["edges_visited"] == 3
    assert payload["depth"] == 1
    assert payload["fanout"] == 2
    assert payload["shard_fetches"] == 1
    assert payload["pages_emitted"] == 3
    assert "elapsed_ms" in payload
    assert payload["budgets"]["max_rows"] == 10
    assert payload["plan_hash"] == "abc"
    # Finite numbers only
    assert isinstance(payload["elapsed_ms"], (int, float))


def test_query_page_envelope_shape() -> None:
    session = _session(budgets={"page_size": 2})
    page = session.page_from_sequence(_rows(3))
    env = page.to_json_dict()
    assert env["row_count"] == 2
    assert env["columns"] == ["id", "payload"]
    assert "statistics" in env
    assert "cursor" in env
    assert env["truncated"] is False
    _assert_json_safe(env)


# ---------------------------------------------------------------------------
# Typed limit errors
# ---------------------------------------------------------------------------


def test_budget_error_typed_fields() -> None:
    err = BudgetExceededError.exceeded("max_fanout", actual=11, limit=10)
    d = err.to_typed_dict()
    assert d == {
        "code": "BUDGET_EXCEEDED",
        "message": "max_fanout exceeded (11 > 10)",
        "retryable": True,
        "details": {"budget": "max_fanout", "actual": 11, "limit": 10},
        "cause_code": None,
    }
    _assert_json_safe(d)


def test_invalid_cursor_error_not_retryable() -> None:
    err = InvalidCursorError("bad", details={"reason": "x"})
    d = err.to_json_dict()
    assert d["code"] == "INVALID_REQUEST"
    assert d["retryable"] is False


def test_runtime_stream_generator() -> None:
    rt = _runtime()
    gen = rt.stream(
        _rows(4),
        tenant="acme",
        graph_id="skills",
        revision="rev-001",
        language="scan",
        text="all",
        budgets={"page_size": 2, "max_rows": 100},
        columns=["id", "payload"],
    )
    pages = list(gen)
    assert len(pages) == 2
    assert sum(p.row_count for p in pages) == 4


def test_digests_are_stable() -> None:
    a = digest_query("cypher", "MATCH (n) RETURN n", {"k": 1, "z": 2})
    b = digest_query("cypher", "MATCH (n) RETURN n", {"z": 2, "k": 1})
    assert a == b
    assert len(a) == 64
    assert digest_authorization(None) == "0" * 64
    assert digest_authorization({}) == "0" * 64
    assert digest_authorization({"principal": "a"}) != digest_authorization(
        {"principal": "b"}
    )


def test_session_context_manager_closes() -> None:
    with _session(budgets={"page_size": 10}) as session:
        list(session.stream_pages(_rows(2)))
    assert session.usage.finished_mono is not None


def test_nodes_edges_counters_do_not_hard_fail() -> None:
    """nodes/edges are tracked for statistics; hard caps use depth/fanout/etc."""
    session = _session()
    session.record_nodes(10_000)
    session.record_edges(10_000)
    assert session.usage.nodes_visited == 10_000
    stats = session.statistics().to_json_dict()
    assert stats["nodes_visited"] == 10_000
    assert stats["edges_visited"] == 10_000
