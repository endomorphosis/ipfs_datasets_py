from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any, Iterable

from .backend import GraphBackend
from .budgets import ExecutionBudgets, ExecutionCounters
from .errors import BudgetExceededError, QueryRejectedError
from .ir import Expand, ExecutionResult, Limit, Project, QueryIR, ScanType, SeedEntities


class GraphQueryExecutor:
    """Executes QueryIR against a GraphBackend with strict budgets."""

    def __init__(self, backend: GraphBackend):
        self._backend = backend

    def execute(self, ir: QueryIR, *, budgets: ExecutionBudgets | None = None) -> ExecutionResult:
        budgets = budgets or ExecutionBudgets()
        counters = ExecutionCounters()
        seen_shards: set[str] = set()
        started = time.monotonic()

        def check_timeout() -> None:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms > budgets.timeout_ms:
                raise BudgetExceededError.exceeded(
                    "timeout_ms", actual=elapsed_ms, limit=budgets.timeout_ms, unit="ms"
                )

        def check_budgets() -> None:
            if counters.nodes_visited > budgets.max_nodes_visited:
                raise BudgetExceededError.exceeded(
                    "max_nodes_visited",
                    actual=counters.nodes_visited,
                    limit=budgets.max_nodes_visited,
                )
            if counters.edges_scanned > budgets.max_edges_scanned:
                raise BudgetExceededError.exceeded(
                    "max_edges_scanned",
                    actual=counters.edges_scanned,
                    limit=budgets.max_edges_scanned,
                )
            if counters.depth > budgets.max_depth:
                raise BudgetExceededError.exceeded(
                    "max_depth", actual=counters.depth, limit=budgets.max_depth
                )
            if counters.shards_touched > budgets.max_shards_touched:
                raise BudgetExceededError.exceeded(
                    "max_shards_touched",
                    actual=counters.shards_touched,
                    limit=budgets.max_shards_touched,
                )

        def check_working_set(phase: str) -> None:
            max_ws = getattr(budgets, "max_working_set_entities", 0) or 0
            if max_ws > 0 and len(working_ids) > max_ws:
                raise BudgetExceededError.exceeded(
                    "max_working_set_entities",
                    actual=len(working_ids),
                    limit=max_ws,
                    detail=phase,
                )

        if not ir.ops:
            return ExecutionResult(items=[], stats={"empty": True})

        # Working set represented as entity IDs.
        working_ids: list[str] = []
        projection: Project | None = None
        scan_pages = 0
        neighbor_pages = 0
        backend_calls = 0
        backend_scan_calls = 0
        backend_neighbor_calls = 0
        backend_header_calls = 0

        def count_backend_call(kind: str) -> None:
            nonlocal backend_calls, backend_scan_calls, backend_neighbor_calls, backend_header_calls
            backend_calls += 1
            if kind == "scan":
                backend_scan_calls += 1
            elif kind == "neighbors":
                backend_neighbor_calls += 1
            elif kind == "headers":
                backend_header_calls += 1

            if getattr(budgets, "max_backend_calls", 0) and budgets.max_backend_calls > 0:
                if backend_calls > budgets.max_backend_calls:
                    raise BudgetExceededError.exceeded(
                        "max_backend_calls",
                        actual=backend_calls,
                        limit=budgets.max_backend_calls,
                        detail=f"kind={kind}",
                    )

        def check_phase_limits() -> None:
            if getattr(budgets, "max_scan_pages", 0) and budgets.max_scan_pages > 0:
                if scan_pages > budgets.max_scan_pages:
                    raise BudgetExceededError.exceeded(
                        "max_scan_pages", actual=scan_pages, limit=budgets.max_scan_pages
                    )
            if getattr(budgets, "max_neighbor_pages", 0) and budgets.max_neighbor_pages > 0:
                if neighbor_pages > budgets.max_neighbor_pages:
                    raise BudgetExceededError.exceeded(
                        "max_neighbor_pages",
                        actual=neighbor_pages,
                        limit=budgets.max_neighbor_pages,
                    )

        for i, op in enumerate(ir.ops):
            check_timeout()

            # Peek next op for safe local pushdowns.
            next_op = ir.ops[i + 1] if i + 1 < len(ir.ops) else None

            if isinstance(op, Project):
                projection = op
                continue

            if isinstance(op, Limit):
                # Limit is a pipeline operator: it truncates the current working set.
                n = max(0, int(op.n))
                if working_ids:
                    working_ids = working_ids[:n]
                continue

            if isinstance(op, SeedEntities):
                ids = [eid for eid in op.entity_ids if self._backend.seed_exists(eid)]
                counters.nodes_visited += len(ids)
                working_ids = list(dict.fromkeys(ids))
                check_working_set("seed")
                check_budgets()
                continue

            if isinstance(op, ScanType):
                # Policy: reject unanchored scans unless explicitly allowed.
                if not budgets.allow_unanchored_scan and not op.scope:
                    raise QueryRejectedError(
                        "Unanchored type scan rejected: provide scope/FROM constraint, "
                        "or enable allow_unanchored_scan for small graphs."
                    )

                # Scan only needs to collect up to max_results, but if the next
                # op is an immediate Limit, we can safely scan less.
                target = int(budgets.max_results)
                if isinstance(next_op, Limit):
                    target = min(target, max(0, int(next_op.n)))
                target = max(0, target)

                collected: list[str] = []
                cursor: str | None = None
                seen_cursors: set[str | None] = {None}
                while len(collected) < target:
                    check_timeout()
                    request_n = target - len(collected)
                    if getattr(budgets, "page_size_scan_type", 0) and budgets.page_size_scan_type > 0:
                        request_n = min(request_n, int(budgets.page_size_scan_type))
                    page = self._backend.scan_type(
                        op.entity_type,
                        scope=op.scope,
                        limit=request_n,
                        cursor=cursor,
                    )
                    count_backend_call("scan")
                    scan_pages += 1
                    check_phase_limits()
                    page_shards = getattr(page, "shards_touched_ids", None)
                    if page_shards:
                        seen_shards.update(page_shards)
                        counters.shards_touched = len(seen_shards)
                    else:
                        counters.shards_touched += int(page.shards_touched or 0)
                    counters.nodes_visited += len(page.entity_ids)
                    collected.extend(page.entity_ids)
                    check_budgets()

                    if not page.next_cursor:
                        break

                    # Safety: prevent cursor loops from causing infinite scans.
                    if page.next_cursor in seen_cursors or page.next_cursor == cursor:
                        raise BudgetExceededError(
                            "cursor_loop detected (scan_type pagination)",
                            budget="cursor_loop",
                            detail="scan_type",
                        )
                    seen_cursors.add(page.next_cursor)
                    cursor = page.next_cursor

                working_ids = list(dict.fromkeys(collected))
                check_working_set("scan_type")
                check_budgets()
                continue

            if isinstance(op, Expand):
                counters.depth += 1
                check_budgets()
                # Expand from current working set.
                max_per_node = op.max_per_node or budgets.max_degree_per_node
                max_per_node = min(max_per_node, budgets.max_degree_per_node)

                max_ws = getattr(budgets, "max_working_set_entities", 0) or 0
                limit_after_expand: int | None = None
                if isinstance(next_op, Limit):
                    limit_after_expand = max(0, int(next_op.n))

                next_ids: list[str] = []
                next_seen: set[str] = set()
                stop_early = False

                for eid in working_ids:
                    check_timeout()

                    if limit_after_expand is not None and len(next_ids) >= limit_after_expand:
                        stop_early = True
                        break

                    remaining = max(0, int(max_per_node))
                    cursor: str | None = None
                    seen_neighbor_cursors: set[str | None] = {None}
                    while remaining > 0:
                        check_timeout()

                        if limit_after_expand is not None and len(next_ids) >= limit_after_expand:
                            stop_early = True
                            break

                        request_n = remaining
                        if getattr(budgets, "page_size_neighbors", 0) and budgets.page_size_neighbors > 0:
                            request_n = min(request_n, int(budgets.page_size_neighbors))
                        page = self._backend.neighbors(
                            eid,
                            relationship_types=op.relationship_types,
                            direction=op.direction,
                            limit=request_n,
                            cursor=cursor,
                        )
                        count_backend_call("neighbors")
                        neighbor_pages += 1
                        check_phase_limits()
                        counters.edges_scanned += len(page.edges)
                        page_shards = getattr(page, "shards_touched_ids", None)
                        if page_shards:
                            seen_shards.update(page_shards)
                            counters.shards_touched = len(seen_shards)
                        else:
                            counters.shards_touched += int(getattr(page, "shards_touched", 0) or 0)

                        for edge in page.edges:
                            target = edge.target_id if edge.source_id == eid else edge.source_id
                            if target in next_seen:
                                continue
                            next_seen.add(target)
                            next_ids.append(target)

                            if max_ws > 0 and len(next_ids) > max_ws:
                                raise BudgetExceededError.exceeded(
                                    "max_working_set_entities",
                                    actual=len(next_ids),
                                    limit=max_ws,
                                    detail="expand",
                                )
                            if limit_after_expand is not None and len(next_ids) >= limit_after_expand:
                                stop_early = True
                                break

                        if stop_early:
                            break

                        remaining -= len(page.edges)
                        check_budgets()

                        if not page.next_cursor or len(page.edges) == 0:
                            break

                        # Safety: prevent cursor loops from causing infinite neighbor scans.
                        if page.next_cursor in seen_neighbor_cursors or page.next_cursor == cursor:
                            raise BudgetExceededError(
                                "cursor_loop detected (neighbors pagination)",
                                budget="cursor_loop",
                                detail="neighbors",
                            )
                        seen_neighbor_cursors.add(page.next_cursor)
                        cursor = page.next_cursor

                        if stop_early:
                            break

                    counters.nodes_visited += len(next_ids)
                    working_ids = next_ids
                    check_working_set("expand")
                check_budgets()
                continue

            raise NotImplementedError(f"Unsupported op: {type(op).__name__}")

        entity_id_list = list(working_ids)
        max_header_entities = getattr(budgets, "max_header_entities", 0) or 0
        if max_header_entities > 0 and len(entity_id_list) > max_header_entities:
            raise BudgetExceededError.exceeded(
                "max_header_entities",
                actual=len(entity_id_list),
                limit=max_header_entities,
            )

        def _batched(items: list[str], batch_size: int) -> Iterable[list[str]]:
            if batch_size <= 0:
                yield items
                return
            for i in range(0, len(items), batch_size):
                yield items[i : i + batch_size]

        header_batch_size = getattr(budgets, "page_size_headers", 0) or 0
        if header_batch_size <= 0:
            header_batch_size = min(2048, len(entity_id_list)) if entity_id_list else 0

        headers: dict[str, Any] = {}
        header_batches = 0
        header_ids_requested = 0
        header_headers_returned = 0
        for batch in _batched(entity_id_list, header_batch_size):
            if not batch:
                continue
            header_batches += 1
            if getattr(budgets, "max_header_batches", 0) and budgets.max_header_batches > 0:
                if header_batches > budgets.max_header_batches:
                    raise BudgetExceededError.exceeded(
                        "max_header_batches",
                        actual=header_batches,
                        limit=budgets.max_header_batches,
                    )
            header_ids_requested += len(batch)
            batch_headers = self._backend.get_entity_headers(batch)
            count_backend_call("headers")
            # Merge; backend may return subset.
            headers.update(batch_headers)
            header_headers_returned += len(batch_headers)

        fields = tuple(projection.fields) if projection else ("id", "type", "name")
        items: list[dict[str, Any]] = []
        output_bytes = 0
        for eid in working_ids:
            header = headers.get(eid)
            if header is None:
                continue
            record = asdict(header)
            item = {k: record.get(k) for k in fields if k in record}
            items.append(item)
            if budgets.max_output_bytes and budgets.max_output_bytes > 0:
                output_bytes += len(
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                )
                if output_bytes > budgets.max_output_bytes:
                    raise BudgetExceededError.exceeded(
                        "max_output_bytes",
                        actual=output_bytes,
                        limit=budgets.max_output_bytes,
                    )
            if len(items) >= budgets.max_results:
                break

        elapsed_ms = int((time.monotonic() - started) * 1000)
        stats = {
            "elapsed_ms": elapsed_ms,
            "nodes_visited": counters.nodes_visited,
            "edges_scanned": counters.edges_scanned,
            "shards_touched": counters.shards_touched,
            "scan_pages": scan_pages,
            "neighbor_pages": neighbor_pages,
            "backend_calls": backend_calls,
            "backend_scan_calls": backend_scan_calls,
            "backend_neighbor_calls": backend_neighbor_calls,
            "backend_header_calls": backend_header_calls,
            "header_batches": header_batches,
            "header_ids_requested": header_ids_requested,
            "header_headers_returned": header_headers_returned,
            "output_bytes": output_bytes,
            "returned": len(items),
        }
        if seen_shards:
            stats["shards_touched_ids"] = sorted(seen_shards)
        return ExecutionResult(items=items, stats=stats)
