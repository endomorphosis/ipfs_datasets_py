"""Tests for incremental and parallel LegalIR compilation."""

from __future__ import annotations

import threading
import time

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION,
    LegalIRIncrementalCompilationSnapshot,
    LegalIRIncrementalCompiler,
    LegalIRInvalidationRule,
    LegalIRPassKind,
    LegalIRPassSpec,
    compile_legal_ir_incremental,
)


def _passes() -> tuple[LegalIRPassSpec, ...]:
    return (
        LegalIRPassSpec(
            pass_id="ingest",
            title="Ingest source",
            kind=LegalIRPassKind.COMPILER,
            order=10,
            declared_inputs=("raw_document",),
            declared_outputs=("normalized_document",),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("citation_graph", "symbol_table", "temporal_context"),
                    when_outputs_change=("normalized_document",),
                    reason="source text feeds all frontend shards",
                ),
            ),
            metadata={"work_units": 2.0, "estimated_seconds": 0.02},
        ),
        LegalIRPassSpec(
            pass_id="citations",
            title="Resolve citations",
            kind=LegalIRPassKind.COMPILER,
            order=20,
            declared_inputs=("normalized_document", "citations"),
            declared_outputs=("citation_graph",),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("lowered_views",),
                    when_outputs_change=("citation_graph",),
                    reason="citation graph scopes lowering",
                ),
            ),
            metadata={"work_units": 3.0, "estimated_seconds": 0.04},
        ),
        LegalIRPassSpec(
            pass_id="symbols",
            title="Resolve symbols",
            kind=LegalIRPassKind.COMPILER,
            order=30,
            declared_inputs=("normalized_document", "symbols"),
            declared_outputs=("symbol_table",),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("lowered_views",),
                    when_outputs_change=("symbol_table",),
                    reason="symbol bindings scope lowering",
                ),
            ),
            metadata={"work_units": 3.0, "estimated_seconds": 0.04},
        ),
        LegalIRPassSpec(
            pass_id="temporal",
            title="Bind temporal authority",
            kind=LegalIRPassKind.COMPILER,
            order=40,
            declared_inputs=("normalized_document", "temporal"),
            declared_outputs=("temporal_context",),
            invalidation_rules=(
                LegalIRInvalidationRule(
                    invalidates=("lowered_views",),
                    when_outputs_change=("temporal_context",),
                    reason="temporal windows scope lowering",
                ),
            ),
            metadata={"work_units": 3.0, "estimated_seconds": 0.04},
        ),
        LegalIRPassSpec(
            pass_id="lower",
            title="Lower views",
            kind=LegalIRPassKind.COMPILER,
            order=50,
            declared_inputs=("citation_graph", "symbol_table", "temporal_context"),
            declared_outputs=("lowered_views",),
            metadata={"work_units": 5.0, "estimated_seconds": 0.03},
        ),
    )


def _functions(counters: dict[str, int], *, sleep: float = 0.0):
    active = counters.setdefault("active", 0)
    del active
    lock = threading.Lock()

    def bump(name: str) -> None:
        with lock:
            counters[name] = counters.get(name, 0) + 1

    def shard(name: str, producer):
        def run(state):
            bump(name)
            with lock:
                counters["active"] = counters.get("active", 0) + 1
                counters["max_active"] = max(
                    counters.get("max_active", 0),
                    counters["active"],
                )
            if sleep:
                time.sleep(sleep)
            try:
                return producer(state)
            finally:
                with lock:
                    counters["active"] -= 1

        return run

    return {
        "ingest": shard(
            "ingest",
            lambda state: {
                **state,
                "normalized_document": str(state["raw_document"]).strip().lower(),
            },
        ),
        "citations": shard(
            "citations",
            lambda state: {
                **state,
                "citation_graph": {
                    "text": state["normalized_document"],
                    "citations": tuple(state.get("citations", ())),
                },
            },
        ),
        "symbols": shard(
            "symbols",
            lambda state: {
                **state,
                "symbol_table": {
                    "text": state["normalized_document"],
                    "symbols": tuple(state.get("symbols", ())),
                },
            },
        ),
        "temporal": shard(
            "temporal",
            lambda state: {
                **state,
                "temporal_context": {
                    "text": state["normalized_document"],
                    "windows": tuple(state.get("temporal", ())),
                },
            },
        ),
        "lower": shard(
            "lower",
            lambda state: {
                **state,
                "lowered_views": {
                    "citation_count": len(state["citation_graph"]["citations"]),
                    "symbol_count": len(state["symbol_table"]["symbols"]),
                    "temporal_count": len(state["temporal_context"]["windows"]),
                },
            },
        ),
    }


def _state(
    *,
    text: str = "The agency shall disclose records.",
    citations: tuple[str, ...] = ("5 USC 552",),
    symbols: tuple[str, ...] = ("agency",),
    temporal: tuple[str, ...] = ("2026-01-01..2026-12-31",),
) -> dict[str, object]:
    return {
        "citations": citations,
        "raw_document": text,
        "symbols": symbols,
        "temporal": temporal,
    }


def test_initial_compile_materializes_snapshot_and_deterministic_order() -> None:
    counters: dict[str, int] = {}

    result = compile_legal_ir_incremental(
        _state(),
        _functions(counters),
        passes=_passes(),
        sources={"doc-1": _state()["raw_document"]},
        citations={"doc-1": _state()["citations"]},
        symbols={"doc-1": _state()["symbols"]},
        temporal={"doc-1": _state()["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )

    assert result.successful
    assert result.snapshot.schema_version == LEGAL_IR_INCREMENTAL_COMPILER_SCHEMA_VERSION
    assert result.deterministic_output_order == (
        "ingest",
        "citations",
        "symbols",
        "temporal",
        "lower",
    )
    assert result.output_state["lowered_views"] == {
        "citation_count": 1,
        "symbol_count": 1,
        "temporal_count": 1,
    }
    assert {node.removeprefix("pass:") for node in result.metrics.executed_nodes} == {
        "ingest",
        "citations",
        "symbols",
        "temporal",
        "lower",
    }
    assert result.metrics.avoided_nodes == ()
    assert counters["lower"] == 1


def test_recompile_only_changed_citation_subgraph_and_reports_avoided_work() -> None:
    first_counters: dict[str, int] = {}
    first = compile_legal_ir_incremental(
        _state(),
        _functions(first_counters),
        passes=_passes(),
        sources={"doc-1": _state()["raw_document"]},
        citations={"doc-1": _state()["citations"]},
        symbols={"doc-1": _state()["symbols"]},
        temporal={"doc-1": _state()["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )
    next_state = _state(citations=("5 USC 552", "ORS 192.311"))
    second_counters: dict[str, int] = {}

    second = compile_legal_ir_incremental(
        next_state,
        _functions(second_counters),
        passes=_passes(),
        previous=first.snapshot,
        sources={"doc-1": next_state["raw_document"]},
        citations={"doc-1": next_state["citations"]},
        symbols={"doc-1": next_state["symbols"]},
        temporal={"doc-1": next_state["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )

    assert second.output_state["lowered_views"]["citation_count"] == 2
    assert {node.removeprefix("pass:") for node in second.metrics.executed_nodes} == {
        "citations",
        "lower",
    }
    assert {node.removeprefix("pass:") for node in second.metrics.avoided_nodes} == {
        "ingest",
        "symbols",
        "temporal",
    }
    assert any(node.startswith("citation:") for node in second.metrics.invalidated_nodes)
    assert second.metrics.avoided_work_units == 8.0
    assert second.metrics.avoided_work_fraction >= 0.5
    assert second.metrics.p95_speedup > 1.0
    assert second_counters == {
        "active": 0,
        "citations": 1,
        "lower": 1,
        "max_active": 1,
    }


def test_source_symbol_temporal_and_pass_spec_changes_invalidate_their_subgraphs() -> None:
    base = compile_legal_ir_incremental(
        _state(),
        _functions({}),
        passes=_passes(),
        sources={"doc-1": _state()["raw_document"]},
        citations={"doc-1": _state()["citations"]},
        symbols={"doc-1": _state()["symbols"]},
        temporal={"doc-1": _state()["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )

    symbol_state = _state(symbols=("agency", "record"))
    symbol_counters: dict[str, int] = {}
    symbol_result = compile_legal_ir_incremental(
        symbol_state,
        _functions(symbol_counters),
        passes=_passes(),
        previous=base.snapshot,
        sources={"doc-1": symbol_state["raw_document"]},
        citations={"doc-1": symbol_state["citations"]},
        symbols={"doc-1": symbol_state["symbols"]},
        temporal={"doc-1": symbol_state["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )
    assert {node.removeprefix("pass:") for node in symbol_result.metrics.executed_nodes} == {
        "symbols",
        "lower",
    }

    temporal_state = _state(temporal=("2027-01-01..2027-12-31",))
    temporal_counters: dict[str, int] = {}
    temporal_result = compile_legal_ir_incremental(
        temporal_state,
        _functions(temporal_counters),
        passes=_passes(),
        previous=base.snapshot,
        sources={"doc-1": temporal_state["raw_document"]},
        citations={"doc-1": temporal_state["citations"]},
        symbols={"doc-1": temporal_state["symbols"]},
        temporal={"doc-1": temporal_state["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )
    assert {node.removeprefix("pass:") for node in temporal_result.metrics.executed_nodes} == {
        "temporal",
        "lower",
    }

    source_state = _state(text="The agency shall disclose records within 30 days.")
    source_counters: dict[str, int] = {}
    source_result = compile_legal_ir_incremental(
        source_state,
        _functions(source_counters),
        passes=_passes(),
        previous=base.snapshot,
        sources={"doc-1": source_state["raw_document"]},
        citations={"doc-1": source_state["citations"]},
        symbols={"doc-1": source_state["symbols"]},
        temporal={"doc-1": source_state["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )
    assert {node.removeprefix("pass:") for node in source_result.metrics.executed_nodes} == {
        "ingest",
        "citations",
        "symbols",
        "temporal",
        "lower",
    }

    changed_passes = list(_passes())
    changed_passes[-1] = LegalIRPassSpec(
        pass_id="lower",
        title="Lower views with changed implementation contract",
        kind=LegalIRPassKind.COMPILER,
        order=50,
        declared_inputs=("citation_graph", "symbol_table", "temporal_context"),
        declared_outputs=("lowered_views",),
        metadata={"work_units": 7.0, "estimated_seconds": 0.03},
    )
    spec_result = compile_legal_ir_incremental(
        _state(),
        _functions({}),
        passes=changed_passes,
        previous=base.snapshot,
        sources={"doc-1": _state()["raw_document"]},
        citations={"doc-1": _state()["citations"]},
        symbols={"doc-1": _state()["symbols"]},
        temporal={"doc-1": _state()["temporal"]},
        max_workers=2,
        resource_limits={"cpu": 2},
    )
    assert spec_result.metrics.executed_nodes == ("pass:lower",)
    assert "pass:lower" in spec_result.metrics.invalidated_nodes


def test_independent_shards_run_in_parallel_under_resource_leases() -> None:
    counters: dict[str, int] = {}
    compiler = LegalIRIncrementalCompiler(
        _passes(),
        _functions(counters, sleep=0.04),
        max_workers=4,
        resource_limits={"cpu": 2},
    )

    result = compiler.compile(
        _state(),
        sources={"doc-1": _state()["raw_document"]},
        citations={"doc-1": _state()["citations"]},
        symbols={"doc-1": _state()["symbols"]},
        temporal={"doc-1": _state()["temporal"]},
    )

    assert result.metrics.max_parallel_shards == 2
    assert result.metrics.resource_lease_max_active["cpu"] == 2
    assert counters["max_active"] == 2
    assert result.deterministic_output_order == (
        "ingest",
        "citations",
        "symbols",
        "temporal",
        "lower",
    )


def test_snapshot_round_trips_for_reuse() -> None:
    first = compile_legal_ir_incremental(
        _state(),
        _functions({}),
        passes=_passes(),
        sources={"doc-1": _state()["raw_document"]},
        citations={"doc-1": _state()["citations"]},
        symbols={"doc-1": _state()["symbols"]},
        temporal={"doc-1": _state()["temporal"]},
    )
    loaded = LegalIRIncrementalCompilationSnapshot.from_dict(first.snapshot.to_dict())
    counters: dict[str, int] = {}

    second = compile_legal_ir_incremental(
        _state(),
        _functions(counters),
        passes=_passes(),
        previous=loaded,
        sources={"doc-1": _state()["raw_document"]},
        citations={"doc-1": _state()["citations"]},
        symbols={"doc-1": _state()["symbols"]},
        temporal={"doc-1": _state()["temporal"]},
    )

    assert second.snapshot.compile_digest == first.snapshot.compile_digest
    assert second.metrics.executed_nodes == ()
    assert len(second.metrics.avoided_nodes) == len(_passes())
    assert counters == {"active": 0}
