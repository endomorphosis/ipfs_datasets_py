"""Vector harness: seed shared catalogs and execute KGP-020 scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .normalize import (
    assert_core_parity,
    extract_error_code,
    extract_revision,
    extract_rows,
    ids_from_scan_rows,
    names_from_scan_rows,
    normalize_envelope,
)
from .surfaces import (
    SurfaceAdapter,
    all_surface_names,
    load_seed_graph,
    load_vector_catalog,
    open_surface,
)

JSONDict = Dict[str, Any]

DEFAULT_TENANT = "conform"
DEFAULT_GRAPH = "vector"
DEFAULT_BRANCH = "main"


def seed_catalog(
    catalog: Path,
    store: Path,
    *,
    tenant: str = DEFAULT_TENANT,
    graph_id: str = DEFAULT_GRAPH,
    branch: str = DEFAULT_BRANCH,
    idem_prefix: str = "seed",
) -> JSONDict:
    """Create graph and write the canonical seed via Python (reference writer)."""
    seed = load_seed_graph()
    surface = open_surface("python", catalog, store)
    try:
        created = surface.create(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            idempotency_key=f"{idem_prefix}-create",
        )
        assert created["status"] == "success", created
        written = surface.write(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            idempotency_key=f"{idem_prefix}-write",
            entities=seed["entities"],
            relationships=seed["relationships"],
        )
        assert written["status"] == "success", written
        revision = written["result"]["revision"]
        return {
            "tenant": tenant,
            "graph_id": graph_id,
            "branch": branch,
            "revision": revision,
            "seed": seed,
            "create": created,
            "write": written,
        }
    finally:
        surface.close()


def corrupt_payloads(store: Path) -> int:
    """Overwrite every snapshot JSON under store with invalid bytes."""
    count = 0
    if not store.exists():
        return 0
    for path in store.rglob("*.json"):
        if path.is_file():
            path.write_bytes(b"{not-json-backend-unavailable")
            count += 1
    return count


def open_all_surfaces(
    catalog: Path, store: Path, names: Optional[Sequence[str]] = None
) -> Dict[str, SurfaceAdapter]:
    surfaces: Dict[str, SurfaceAdapter] = {}
    for name in names or all_surface_names():
        surfaces[name] = open_surface(name, catalog, store)
    return surfaces


def close_all(surfaces: Mapping[str, SurfaceAdapter]) -> None:
    for s in surfaces.values():
        try:
            s.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Vector runners
# ---------------------------------------------------------------------------


def run_lifecycle(surfaces: Mapping[str, SurfaceAdapter]) -> Dict[str, Any]:
    """Create once (python), then list/describe/open on every surface."""
    tenant, gid = "life", "g1"
    writer = surfaces["python"]
    created = writer.create(
        tenant=tenant, graph_id=gid, branch="main", idempotency_key="life-c"
    )
    assert created["status"] == "success", created
    rev = created["result"]["revision"]

    results: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        listed = surface.list_graphs(tenant=tenant)
        described = surface.describe(tenant=tenant, graph_id=gid, branch="main")
        opened = surface.open_graph(tenant=tenant, graph_id=gid, branch="main")
        results[name] = {
            "list": listed,
            "describe": described,
            "open": opened,
        }
        assert listed["status"] == "success", (name, listed)
        assert described["status"] == "success", (name, described)
        assert opened["status"] == "success", (name, opened)
        assert any(
            g.get("graph_id") == gid for g in (listed.get("result") or {}).get("graphs", [])
        ), name
        head = (described.get("result") or {}).get("head_revision")
        open_rev = (opened.get("result") or {}).get("revision")
        assert head == rev, (name, head, rev)
        assert open_rev == rev, (name, open_rev, rev)

    # Cross-surface parity on describe envelopes (normalized).
    describe_map = {n: r["describe"] for n, r in results.items()}
    assert_core_parity(describe_map, require_revision=True, sort_rows=False)
    open_map = {n: r["open"] for n, r in results.items()}
    # Open result.revision must match across surfaces.
    revs = {n: extract_revision(e) for n, e in open_map.items()}
    assert len(set(revs.values())) == 1, revs
    return {"create_revision": rev, "surfaces": results}


def run_mutation(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, Any]:
    tenant = meta["tenant"]
    gid = meta["graph_id"]
    branch = meta["branch"]
    expected_rev = meta["revision"]
    seed = meta["seed"]

    envelopes: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        q = surface.query(
            tenant=tenant, graph_id=gid, branch=branch, language="scan"
        )
        assert q["status"] == "success", (name, q)
        envelopes[name] = q
        result = q["result"]
        assert result["revision"] == expected_rev, (name, result["revision"], expected_rev)
        assert result["row_count"] == seed["expected"]["entity_count"], name
        names = names_from_scan_rows(result["rows"])
        ids = ids_from_scan_rows(result["rows"])
        assert names == sorted(seed["expected"]["scan_names"]), (name, names)
        assert ids == sorted(seed["expected"]["scan_ids"]), (name, ids)

    summary = assert_core_parity(envelopes, require_revision=True, sort_rows=True)
    assert summary["revision"] == expected_rev
    assert summary["row_count"] == seed["expected"]["entity_count"]
    return summary


def run_cypher(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, Any]:
    tenant, gid, branch = meta["tenant"], meta["graph_id"], meta["branch"]
    envelopes: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        q = surface.query(
            tenant=tenant,
            graph_id=gid,
            branch=branch,
            language="cypher",
            text="MATCH (n:Person) RETURN n",
        )
        assert q["status"] == "success", (name, q)
        assert q["result"]["row_count"] == 3, (name, q["result"]["row_count"])
        assert q["result"]["schema"] == "cypher-table/v1", name
        assert q["result"]["truncated"] is False, name
        assert q["result"]["revision"] == meta["revision"], name
        envelopes[name] = q
    return assert_core_parity(envelopes, require_revision=True, sort_rows=True)


def run_traversal(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, Any]:
    """Count language returns exact [entities, relationships] adjacency stats."""
    tenant, gid, branch = meta["tenant"], meta["graph_id"], meta["branch"]
    envelopes: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        q = surface.query(
            tenant=tenant, graph_id=gid, branch=branch, language="count"
        )
        assert q["status"] == "success", (name, q)
        assert q["result"]["rows"] == [[5, 4]], (name, q["result"]["rows"])
        assert q["result"]["schema"] == "stats/v1", name
        assert q["result"]["revision"] == meta["revision"], name
        envelopes[name] = q
    return assert_core_parity(envelopes, require_revision=True, sort_rows=False)


def run_hybrid(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, Any]:
    tenant, gid, branch = meta["tenant"], meta["graph_id"], meta["branch"]
    envelopes: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        q = surface.hybrid_search(
            tenant=tenant, graph_id=gid, branch=branch, limit=50
        )
        assert q["status"] == "success", (name, q)
        assert q["result"]["envelope_version"] == "kg-query-envelope/v1", name
        assert q["result"]["row_count"] == 5, name
        assert q["result"]["revision"] == meta["revision"], name
        envelopes[name] = q
    return assert_core_parity(envelopes, require_revision=True, sort_rows=True)


def run_pagination(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, Any]:
    tenant, gid, branch = meta["tenant"], meta["graph_id"], meta["branch"]
    page_size = 2
    summaries: Dict[str, Any] = {}
    for name, surface in surfaces.items():
        pages = surface.stream_query(
            tenant=tenant,
            graph_id=gid,
            branch=branch,
            language="scan",
            page_size=page_size,
        )
        assert pages, name
        # Stream pages may be StreamPage dicts or lifecycle envelopes with result.
        total = 0
        last = pages[-1]
        for page in pages:
            if "row_count" in page and "rows" in page:
                total += int(page["row_count"])
            elif isinstance(page.get("result"), Mapping):
                total += int(page["result"].get("row_count") or 0)
            else:
                raise AssertionError(f"{name}: unexpected page shape {page.keys()}")
        assert total == 5, (name, total, pages)
        # Exhausted flag
        if "exhausted" in last:
            assert last["exhausted"] is True, name
        elif isinstance(last.get("result"), Mapping):
            assert last["result"].get("exhausted") is True, name
        assert len(pages) == 3, (name, len(pages))
        summaries[name] = {"total_rows": total, "page_count": len(pages)}
    totals = {n: s["total_rows"] for n, s in summaries.items()}
    assert len(set(totals.values())) == 1, totals
    return summaries


def run_transaction_per_surface(catalog: Path, store: Path, surface_name: str) -> JSONDict:
    """Independent catalog per surface for begin/stage/commit visibility."""
    # Isolate by using distinct graph ids under the same durable paths.
    tenant = "tx"
    gid = f"tx-{surface_name.replace('_', '-')}"
    surface = open_surface(surface_name, catalog, store)
    try:
        created = surface.create(
            tenant=tenant,
            graph_id=gid,
            branch="main",
            idempotency_key=f"tx-c-{surface_name}",
        )
        assert created["status"] == "success", created
        begin = surface.begin_tx(tenant=tenant, graph_id=gid, branch="main")
        assert begin["status"] == "success", begin
        tx_id = (begin.get("result") or {}).get("transaction_id")
        assert tx_id, begin
        staged = surface.write(
            tenant=tenant,
            graph_id=gid,
            branch="main",
            idempotency_key=f"tx-stage-{surface_name}",
            entities=[{"id": "n1", "type": "Thing", "name": "tx-node"}],
            transaction_id=str(tx_id),
        )
        assert staged["status"] == "success", staged
        # Pre-commit scan must be empty.
        pre = surface.query(
            tenant=tenant, graph_id=gid, branch="main", language="scan"
        )
        assert pre["status"] == "success", pre
        assert pre["result"]["row_count"] == 0, pre
        commit = surface.commit_tx(
            tenant=tenant,
            graph_id=gid,
            branch="main",
            transaction_id=str(tx_id),
            idempotency_key=f"tx-commit-{surface_name}",
        )
        assert commit["status"] == "success", commit
        post = surface.query(
            tenant=tenant, graph_id=gid, branch="main", language="scan"
        )
        assert post["status"] == "success", post
        assert post["result"]["row_count"] == 1, post
        assert names_from_scan_rows(post["result"]["rows"]) == ["tx-node"]
        return post
    finally:
        surface.close()


def run_conflict_per_surface(catalog: Path, store: Path, surface_name: str) -> JSONDict:
    tenant = "cf"
    gid = f"cf-{surface_name.replace('_', '-')}"
    surface = open_surface(surface_name, catalog, store)
    try:
        assert (
            surface.create(
                tenant=tenant,
                graph_id=gid,
                branch="main",
                idempotency_key=f"cf-c-{surface_name}",
            )["status"]
            == "success"
        )
        begin = surface.begin_tx(tenant=tenant, graph_id=gid, branch="main")
        assert begin["status"] == "success", begin
        tx_id = begin["result"]["transaction_id"]
        # Concurrent auto-commit write moves the head.
        other = surface.write(
            tenant=tenant,
            graph_id=gid,
            branch="main",
            idempotency_key=f"cf-other-{surface_name}",
            entities=[{"id": "other", "type": "X", "name": "o"}],
        )
        assert other["status"] == "success", other
        surface.write(
            tenant=tenant,
            graph_id=gid,
            branch="main",
            idempotency_key=f"cf-stage-{surface_name}",
            entities=[{"id": "stale", "type": "X", "name": "s"}],
            transaction_id=str(tx_id),
        )
        commit = surface.commit_tx(
            tenant=tenant,
            graph_id=gid,
            branch="main",
            transaction_id=str(tx_id),
            idempotency_key=f"cf-commit-{surface_name}",
        )
        assert commit["status"] == "error", commit
        assert extract_error_code(commit) == "CONFLICT", commit
        err = commit.get("error") or {}
        assert err.get("retryable") is True, commit
        return commit
    finally:
        surface.close()


def run_restart(
    catalog: Path, store: Path, surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, Any]:
    """Close surfaces, reopen fresh adapters, verify exact revision/rows."""
    close_all(surfaces)
    fresh = open_all_surfaces(catalog, store)
    try:
        return run_mutation(fresh, meta=meta)
    finally:
        close_all(fresh)


def run_invalid_missing_target(
    surfaces: Mapping[str, SurfaceAdapter],
) -> Dict[str, JSONDict]:
    allowed = {"INVALID_TARGET", "INVALID_REQUEST"}
    out: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        env = surface.invalid_create_missing_target()
        assert env["status"] == "error", (name, env)
        code = extract_error_code(env)
        assert code in allowed, (name, code, env)
        # No surface-specific exception type leakage in envelope.
        assert isinstance(env.get("error"), Mapping), name
        assert "code" in env["error"], name
        out[name] = env
    codes = {n: extract_error_code(e) for n, e in out.items()}
    # Codes may be either of the two allowed, but each must be typed.
    assert all(c in allowed for c in codes.values()), codes
    return out


def run_invalid_bad_cypher(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, JSONDict]:
    """Malformed Cypher without RETURN fails on every surface with the same code.

    Service cypher-lite raises ``CatalogError("QUERY_PARSE", …)`` but the catalog
    vocabulary does not include ``QUERY_PARSE``, so the execute boundary maps the
    resulting ``ValueError`` to typed ``INTERNAL``. All four surfaces must share
    that exact code (no surface-specific waiver).
    """
    tenant, gid, branch = meta["tenant"], meta["graph_id"], meta["branch"]
    out: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        env = surface.query(
            tenant=tenant,
            graph_id=gid,
            branch=branch,
            language="cypher",
            text="MATCH (n:Person)",
        )
        assert env["status"] == "error", (name, env)
        code = extract_error_code(env)
        assert code == "INTERNAL", (name, code, env)
        assert (env.get("error") or {}).get("retryable") is False, name
        out[name] = env
    codes = {n: extract_error_code(e) for n, e in out.items()}
    assert set(codes.values()) == {"INTERNAL"}, codes
    return out


def run_unavailable_backend(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, JSONDict]:
    tenant, gid, branch = meta["tenant"], meta["graph_id"], meta["branch"]
    out: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        env = surface.query(
            tenant=tenant, graph_id=gid, branch=branch, language="scan"
        )
        assert env["status"] == "error", (name, env)
        assert extract_error_code(env) == "INTERNAL", (name, env)
        err = env.get("error") or {}
        assert err.get("retryable") is False, (name, env)
        out[name] = env
    # Exact code parity (no surface waiver).
    codes = {n: extract_error_code(e) for n, e in out.items()}
    assert set(codes.values()) == {"INTERNAL"}, codes
    return out


def run_limit(
    surfaces: Mapping[str, SurfaceAdapter], *, meta: Mapping[str, Any]
) -> Dict[str, Any]:
    tenant, gid, branch = meta["tenant"], meta["graph_id"], meta["branch"]
    envelopes: Dict[str, JSONDict] = {}
    for name, surface in surfaces.items():
        q = surface.query(
            tenant=tenant,
            graph_id=gid,
            branch=branch,
            language="scan",
            max_rows=2,
        )
        assert q["status"] == "success", (name, q)
        assert q["result"]["row_count"] == 2, (name, q["result"]["row_count"])
        assert q["result"]["truncated"] is True, name
        assert q["result"]["revision"] == meta["revision"], name
        envelopes[name] = q
    return assert_core_parity(envelopes, require_revision=True, sort_rows=True)


def catalog_vectors() -> List[JSONDict]:
    return list(load_vector_catalog()["vectors"])
