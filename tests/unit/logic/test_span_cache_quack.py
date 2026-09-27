"""Span gaps are read from the catalog owner over Quack."""
import threading
from pathlib import Path

from ipfs_datasets_py.duckdb_control.span_cache_quack import (
    SpanCacheQuackError,
    SpanCacheQuackGateway,
    read_span_gaps,
)
from ipfs_datasets_py.logic.autoformal.gap_compile_replay import replay_gaps
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache


def test_owner_serves_gaps_without_a_second_catalog_open(tmp_path: Path) -> None:
    cache_path = tmp_path / "span-cache.duckdb"
    cache = SpanCache(cache_path)
    cache.enqueue(
        [
            {"source_span_id": "gap-a", "text": "Whoever shall be imprisoned.", "legal_id": "usc:us:18:1001"},
            {"source_span_id": "gap-b", "text": "The agency shall imprison the person.", "legal_id": "usc:us:18:1001"},
        ]
    )
    cache._db.execute(
        "UPDATE span_cache SET status = 'gap', reason = 'CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty'"
    )
    gateway = SpanCacheQuackGateway()
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            gateway.serve(cache)
            stop.wait(0.01)

    try:
        gateway.start()
        published = gateway.publish(cache_path)
        assert published["endpoint"].startswith("quack:127.0.0.1:")
        thread = threading.Thread(target=serve, name="span-owner-serve")
        thread.start()
        page = read_span_gaps(cache_path, limit=16)
        assert page["admitted"] is False
        assert page["formalized"] is False
        assert page["wrote_compiler"] is False
        assert page["opens_catalog_file"] is False
        assert page["control_plane"]["control_plane"] == "duckdb+quack"
        assert page["control_plane"]["activation_held"] is True
        assert page["control_plane"]["production_mutation_enabled"] is False
        assert [row["source_span_id"] for row in page["gaps"]] == ["gap-a", "gap-b"]
        report = replay_gaps(
            page["gaps"],
            lambda text: text,
            lambda text: {
                "compiler_status": "abstain",
                "decompiled": "",
                "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:penalty",
            },
        )
        assert report["failure_classes"] == 1
        assert report["admitted"] is False
        assert report["wrote_compiler"] is False
        missing = tmp_path / "absent.duckdb"
        try:
            read_span_gaps(missing, limit=1)
        except SpanCacheQuackError as exc:
            assert "refusing to open the DuckDB file" in str(exc)
        else:
            raise AssertionError("missing owner handoff opened a catalog")
    finally:
        stop.set()
        gateway.close()
        cache.close()
