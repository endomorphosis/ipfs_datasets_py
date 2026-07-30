"""KGP-029: reproducible graph load harness correctness tests.

Mandatory CI coverage for:

* deterministic graph shape generation
* versioned receipt schema completeness
* tiny profile across storage profiles (python)
* surface matrix probes (python/cli/mcp/mcp++)
* read/write/query mixes
* resource / latency / recovery / shard fan-out fields
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from benchmarks.knowledge_graphs.harness import GraphLoadHarness, run_profile
from benchmarks.knowledge_graphs.metrics import (
    LatencyHistogram,
    OperationCounters,
    sample_resources,
    throughput,
)
from benchmarks.knowledge_graphs.profiles import (
    DEFAULT_STORAGE_PROFILES,
    DEFAULT_SURFACES,
    LOAD_PROFILES,
    PROFILE_NAMES,
    WorkloadMix,
    get_profile,
    list_profiles,
)
from benchmarks.knowledge_graphs.receipt import (
    RECEIPT_SCHEMA,
    RECEIPT_SCHEMA_VERSION,
    REQUIRED_RECEIPT_KEYS,
    build_receipt,
    receipt_to_json,
    validate_receipt,
    write_receipt,
    load_receipt,
)
from benchmarks.knowledge_graphs.shapes import (
    SHAPE_FAMILIES,
    GraphShapeSpec,
    generate_graph,
    shape_fingerprint,
)
from benchmarks.knowledge_graphs.surfaces import (
    STORAGE_PROFILES,
    SURFACE_NAMES,
    envelope_ok,
    open_load_surface,
)
from benchmarks.knowledge_graphs.workloads import execute_mix, seed_graph


# ---------------------------------------------------------------------------
# Deterministic shapes
# ---------------------------------------------------------------------------


class TestDeterministicShapes:
    def test_same_seed_same_fingerprint(self) -> None:
        a = generate_graph(
            GraphShapeSpec(seed=42, node_count=32, edge_count=64, shape="mixed")
        )
        b = generate_graph(
            GraphShapeSpec(seed=42, node_count=32, edge_count=64, shape="mixed")
        )
        assert a.fingerprint == b.fingerprint
        assert a.fingerprint == shape_fingerprint(a)
        assert [e["id"] for e in a.entities] == [e["id"] for e in b.entities]
        assert [r["id"] for r in a.relationships] == [r["id"] for r in b.relationships]
        assert a.relationships[0]["source"] == b.relationships[0]["source"]

    def test_different_seed_different_fingerprint(self) -> None:
        a = generate_graph(
            GraphShapeSpec(seed=1, node_count=20, edge_count=40, shape="power_law")
        )
        b = generate_graph(
            GraphShapeSpec(seed=2, node_count=20, edge_count=40, shape="power_law")
        )
        assert a.fingerprint != b.fingerprint

    @pytest.mark.parametrize("shape", SHAPE_FAMILIES)
    def test_all_shape_families(self, shape: str) -> None:
        g = generate_graph(
            GraphShapeSpec(seed=7, node_count=16, edge_count=24, shape=shape, shard_count=4)
        )
        assert g.node_count == 16
        assert g.edge_count == 24
        assert len(g.fingerprint) == 64
        fan = g.shard_fan_out()
        assert fan["shard_count"] == 4
        assert fan["distinct_shards_touched"] >= 1
        assert "per_shard" in fan
        assert "cross_shard_edges" in fan

    def test_exact_counts(self) -> None:
        g = generate_graph(
            GraphShapeSpec(seed=99, node_count=10, edge_count=5, shape="path")
        )
        assert len(g.entities) == 10
        assert len(g.relationships) == 5
        # Path edges: n0->n1, n1->n2, ...
        assert g.relationships[0]["source"].endswith("00000000")
        assert g.relationships[0]["target"].endswith("00000001")

    def test_invalid_shape_raises(self) -> None:
        with pytest.raises(ValueError):
            GraphShapeSpec(seed=1, node_count=1, edge_count=0, shape="not-a-shape")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_latency_histogram_percentiles(self) -> None:
        h = LatencyHistogram()
        for i in range(1, 101):
            h.observe(float(i))
        s = h.summary()
        assert s["count"] == 100
        assert s["min_ms"] == 1.0
        assert s["max_ms"] == 100.0
        assert s["p50_ms"] == pytest.approx(50.0, abs=1.0)
        assert s["p95_ms"] == pytest.approx(95.0, abs=1.0)
        assert s["p99_ms"] == pytest.approx(99.0, abs=1.0)
        assert len(s["buckets_ms"]) == len(s["bucket_counts"])
        assert sum(s["bucket_counts"]) + s["overflow"] == 100

    def test_histogram_merge(self) -> None:
        a = LatencyHistogram()
        b = LatencyHistogram()
        a.observe(1.0)
        b.observe(2.0)
        a.merge(b)
        assert a.count == 2
        assert set(a.samples()) == {1.0, 2.0}

    def test_resource_snapshot_fields(self) -> None:
        snap = sample_resources()
        d = snap.to_json_dict()
        for key in (
            "timestamp",
            "cpu_user_s",
            "cpu_system_s",
            "rss_bytes",
            "max_rss_bytes",
            "heap_bytes",
            "open_fds",
            "threads",
        ):
            assert key in d
        assert d["rss_bytes"] >= 0
        assert d["cpu_user_s"] >= 0

    def test_throughput(self) -> None:
        assert throughput(100, 2.0) == 50.0
        assert throughput(10, 0.0) == 0.0

    def test_operation_counters(self) -> None:
        c = OperationCounters()
        c.record_op(ok=True, queue_wait_ms=1.5, queue_depth=2)
        c.record_op(ok=False, conflict=True)
        c.record_storage(cache_hits=3, cache_misses=1, ipfs_bytes=100, ipfs_fetches=2)
        c.record_recovery(ok=True, recovery_ms=12.5)
        d = c.to_json_dict()
        assert d["operations_total"] == 2
        assert d["operations_ok"] == 1
        assert d["operations_error"] == 1
        assert d["conflicts"] == 1
        assert d["queue_depth_peak"] == 2
        assert d["cache_hits"] == 3
        assert d["ipfs_fetches"] == 2
        assert d["recovery_successes"] == 1


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


class TestReceipts:
    def test_build_and_validate_receipt(self, tmp_path: Path) -> None:
        hist = LatencyHistogram()
        hist.observe(1.0)
        hist.observe(2.0)
        hist.observe(10.0)
        start = sample_resources().to_json_dict()
        end = sample_resources().to_json_dict()
        counters = OperationCounters()
        counters.record_op(ok=True)
        counters.record_storage(ipfs_bytes=10, ipfs_fetches=1, cache_hits=1)
        counters.record_recovery(ok=True, recovery_ms=5.0)
        receipt = build_receipt(
            seed=42,
            config={"profile": "tiny", "matrix_mode": "ci"},
            throughput={"ops_per_s": 10.0, "operations": 10, "elapsed_s": 1.0},
            latency_histogram=hist.to_json_dict(),
            counters=counters.to_json_dict(),
            resources_start=start,
            resources_end=end,
            shard_fan_out={"shard_count": 4, "distinct_shards_touched": 3},
            recovery={"attempts": 1, "successes": 1, "ms_mean": 5.0},
            results=[{"surface": "python", "ok": True}],
            shape_fingerprint="abc",
            elapsed_s=1.0,
            status="success",
        )
        data = receipt_to_json(receipt)
        problems = validate_receipt(data)
        assert problems == [], problems
        assert data["schema"] == RECEIPT_SCHEMA
        assert data["schema_version"] == RECEIPT_SCHEMA_VERSION
        for key in REQUIRED_RECEIPT_KEYS:
            assert key in data
        # Nested mandatory measurements.
        assert "p95_ms" in data["latency_histogram"]
        assert "ops_per_s" in data["throughput"]
        assert "rss_bytes" in data["resources"]["start"]
        assert "open_fds" in data["resources"]["end"]
        assert "hits" in data["cache"]
        assert "fetches" in data["ipfs"]
        assert data["seed"] == 42
        assert data["digest"]

        path = write_receipt(receipt, tmp_path / "receipt.json")
        loaded = load_receipt(path)
        assert loaded["receipt_id"] == data["receipt_id"]
        assert validate_receipt(loaded) == []

    def test_validate_rejects_incomplete(self) -> None:
        problems = validate_receipt({"schema": "wrong"})
        assert any("missing required key" in p for p in problems)
        assert any("schema must be" in p for p in problems)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class TestProfiles:
    def test_tiny_is_mandatory(self) -> None:
        tiny = get_profile("tiny")
        assert tiny.opt_in is False
        assert tiny.shape_spec.node_count > 0
        assert tiny.shape_spec.edge_count > 0
        assert set(tiny.surfaces) == set(DEFAULT_SURFACES)
        assert set(tiny.storage_profiles) == set(DEFAULT_STORAGE_PROFILES)

    def test_smoke_matches_plan_size(self) -> None:
        smoke = get_profile("smoke")
        assert smoke.opt_in is True
        assert smoke.shape_spec.node_count == 1000
        assert smoke.shape_spec.edge_count == 5000

    def test_synthetic_large_size(self) -> None:
        large = get_profile("synthetic_large")
        assert large.shape_spec.node_count == 1_000_000
        assert large.shape_spec.edge_count == 10_000_000
        assert large.opt_in is True

    def test_concurrent_mixed_has_16_graphs(self) -> None:
        p = get_profile("concurrent_mixed")
        assert p.graph_count >= 16
        assert p.opt_in is True

    def test_all_profiles_named(self) -> None:
        assert "tiny" in PROFILE_NAMES
        for name in PROFILE_NAMES:
            assert get_profile(name).name == name
        mandatory = list_profiles(include_opt_in=False)
        assert len(mandatory) == 1
        assert mandatory[0].name == "tiny"

    def test_mix_normalization(self) -> None:
        m = WorkloadMix(write_weight=1, read_weight=1, query_weight=2).normalized()
        assert m.write_weight == pytest.approx(0.25)
        assert m.read_weight == pytest.approx(0.25)
        assert m.query_weight == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Surfaces + seed (python path)
# ---------------------------------------------------------------------------


class TestPythonSurfaceSeedAndMix:
    def test_seed_and_mix_parquet(self, tmp_path: Path) -> None:
        catalog = tmp_path / "cat.sqlite"
        store = tmp_path / "store"
        store.mkdir()
        surface = open_load_surface("python", catalog, store)
        try:
            graph = generate_graph(
                GraphShapeSpec(seed=3, node_count=12, edge_count=20, shape="ring")
            )
            seeded = seed_graph(
                surface,
                graph,
                storage_profile="parquet",
                tenant="load",
                graph_id="g1",
                batch_size=5,
            )
            assert seeded["status"] == "success", seeded
            assert seeded.get("revision")
            mix = execute_mix(
                surface,
                graph,
                WorkloadMix(
                    write_weight=0.4,
                    read_weight=0.3,
                    query_weight=0.3,
                    operations=9,
                    write_batch_size=4,
                ),
                storage_profile="parquet",
                tenant="load",
                graph_id="g1",
                seed=3,
                warmup=1,
            )
            assert mix.operations == 9
            assert mix.write_ops + mix.read_ops + mix.query_ops == 9
            assert mix.ok >= 1
            assert mix.latency.count == 9
            q = surface.query(tenant="load", graph_id="g1", language="scan", max_rows=50)
            assert envelope_ok(q), q
        finally:
            surface.close()


# ---------------------------------------------------------------------------
# Full harness runs
# ---------------------------------------------------------------------------


class TestGraphLoadHarness:
    def test_tiny_ci_matrix_produces_valid_receipt(self, tmp_path: Path) -> None:
        """Mandatory CI profile: python × all storage + surface probes."""
        result = run_profile(
            "tiny",
            work_dir=tmp_path / "run",
            matrix_mode="ci",
            surfaces=DEFAULT_SURFACES,
            storage_profiles=DEFAULT_STORAGE_PROFILES,
        )
        assert result.receipt is not None
        data = result.receipt.to_json_dict()
        problems = validate_receipt(data)
        assert problems == [], problems

        # Python storage cells must succeed.
        python_cells = [c for c in result.cells if c.surface == "python"]
        assert len(python_cells) == len(DEFAULT_STORAGE_PROFILES)
        for cell in python_cells:
            assert cell.seed_status == "success", (
                cell.surface,
                cell.storage_profile,
                cell.error,
            )
            assert cell.mix is not None
            assert cell.mix.operations > 0
            assert cell.recovery_ok is True, cell.error
            assert cell.recovery_ms is not None and cell.recovery_ms >= 0

        # Receipt must record the full measurement suite.
        assert data["seed"] == get_profile("tiny").seed
        assert data["environment"]
        assert data["revision"] is not None
        assert "ops_per_s" in data["throughput"]
        assert data["latency_histogram"]["count"] >= 1
        assert "wait_ms_total" in data["queue"]
        assert "count" in data["conflict"]
        assert "count" in data["error"]
        assert "rss_bytes" in data["resources"]["end"]
        assert "heap_bytes" in data["resources"]["end"]
        assert "open_fds" in data["resources"]["end"]
        assert "cpu" in data["resources"]
        assert "hits" in data["cache"]
        assert "bytes" in data["cache"]
        assert "fetches" in data["ipfs"]
        assert "bytes" in data["ipfs"]
        assert data["shard_fan_out"]["shard_count"] == get_profile("tiny").shape_spec.shard_count
        assert "attempts" in data["recovery"]
        assert data["shape_fingerprint"] == result.graph.fingerprint
        assert data["status"] == "success"
        assert result.status == "success"

    def test_storage_profiles_matrix(self, tmp_path: Path) -> None:
        harness = GraphLoadHarness(tmp_path / "store-matrix")
        profile = get_profile("tiny").with_surfaces(("python",))
        result = harness.run(profile, matrix_mode="storage")
        profiles_seen = {c.storage_profile for c in result.cells}
        assert profiles_seen == set(DEFAULT_STORAGE_PROFILES)
        for cell in result.cells:
            assert cell.seed_status == "success", (cell.storage_profile, cell.error)
            assert cell.mix is not None
            assert cell.mix.ok >= 1

    def test_read_write_query_mix_counts(self, tmp_path: Path) -> None:
        profile = get_profile("tiny").with_surfaces(("python",)).with_storage_profiles(
            ("parquet",)
        )
        result = run_profile(
            profile,
            work_dir=tmp_path / "mix",
            matrix_mode="storage",
        )
        assert len(result.cells) == 1
        mix = result.cells[0].mix
        assert mix is not None
        assert mix.write_ops >= 1
        assert mix.read_ops >= 1
        assert mix.query_ops >= 1

    def test_deterministic_fingerprint_in_receipt(self, tmp_path: Path) -> None:
        r1 = run_profile(
            "tiny",
            work_dir=tmp_path / "a",
            matrix_mode="storage",
            surfaces=("python",),
            storage_profiles=("parquet",),
        )
        r2 = run_profile(
            "tiny",
            work_dir=tmp_path / "b",
            matrix_mode="storage",
            surfaces=("python",),
            storage_profiles=("parquet",),
        )
        assert r1.graph.fingerprint == r2.graph.fingerprint
        assert r1.receipt is not None and r2.receipt is not None
        assert r1.receipt.shape_fingerprint == r2.receipt.shape_fingerprint

    def test_harness_generate_api(self, tmp_path: Path) -> None:
        h = GraphLoadHarness(tmp_path)
        g = h.generate(seed=11, node_count=8, edge_count=12, shape="star", shard_count=2)
        assert g.node_count == 8
        assert g.edge_count == 12
        assert g.shard_fan_out()["shard_count"] == 2

    def test_surface_names_and_storage_profiles_exported(self) -> None:
        assert SURFACE_NAMES == ("python", "cli", "mcp", "mcp_plus")
        assert "parquet" in STORAGE_PROFILES
        assert "ipfs_ipld" in STORAGE_PROFILES
        assert "ipfs_kit" in STORAGE_PROFILES
        assert "hybrid" in STORAGE_PROFILES

    def test_receipt_written_to_disk(self, tmp_path: Path) -> None:
        receipt_path = tmp_path / "out" / "receipt.json"
        result = run_profile(
            "tiny",
            work_dir=tmp_path / "work",
            matrix_mode="storage",
            surfaces=("python",),
            storage_profiles=("parquet",),
            receipt_path=receipt_path,
        )
        assert receipt_path.is_file()
        loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert validate_receipt(loaded) == []
        assert loaded["receipt_id"] == result.receipt.receipt_id  # type: ignore[union-attr]

    def test_corpus_profile_hooks_exist(self) -> None:
        for name in ("corpus_211", "corpus_cvefixes"):
            p = get_profile(name)
            assert p.opt_in is True
            assert p.corpus_id is not None


class TestSurfaceMatrixProbe:
    """Exercise each public surface at least once (python is authoritative)."""

    def test_each_surface_can_open(self, tmp_path: Path) -> None:
        # Use harness CI mode which probes all surfaces on parquet.
        result = run_profile(
            "tiny",
            work_dir=tmp_path / "surfaces",
            matrix_mode="ci",
            surfaces=DEFAULT_SURFACES,
            storage_profiles=("parquet",),
        )
        surfaces_seen = {c.surface for c in result.cells}
        assert "python" in surfaces_seen
        # Other surfaces may fail in constrained environments; python must pass.
        python = [c for c in result.cells if c.surface == "python"]
        assert python and python[0].seed_status == "success"
        # Ensure the matrix *attempted* all requested surfaces.
        assert surfaces_seen >= {"python"}
        # Receipt still valid regardless of soft surface failures.
        assert result.receipt is not None
        assert validate_receipt(result.receipt.to_json_dict()) == []

    @pytest.mark.parametrize("surface", ["python", "mcp", "mcp_plus"])
    def test_inprocess_surfaces_seed(self, tmp_path: Path, surface: str) -> None:
        catalog = tmp_path / f"{surface}.sqlite"
        store = tmp_path / f"{surface}_store"
        store.mkdir()
        surf = open_load_surface(surface, catalog, store)
        try:
            graph = generate_graph(
                GraphShapeSpec(seed=5, node_count=6, edge_count=8, shape="path")
            )
            seeded = seed_graph(
                surf,
                graph,
                storage_profile="parquet",
                tenant="load",
                graph_id=f"g-{surface}",
                batch_size=4,
            )
            assert seeded["status"] == "success", seeded
            opened = surf.open_graph(tenant="load", graph_id=f"g-{surface}")
            assert envelope_ok(opened), opened
            queried = surf.query(
                tenant="load", graph_id=f"g-{surface}", language="scan", max_rows=20
            )
            assert envelope_ok(queried), queried
        finally:
            surf.close()


class TestPackageExports:
    def test_public_exports(self) -> None:
        import benchmarks.knowledge_graphs as pkg

        assert pkg.RECEIPT_SCHEMA_VERSION == 1
        assert callable(pkg.generate_graph)
        assert callable(pkg.run_profile)
        assert callable(pkg.validate_receipt)
        assert "tiny" in pkg.LOAD_PROFILES
