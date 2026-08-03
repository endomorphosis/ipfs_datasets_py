"""KGP-020: exact cross-surface conformance vectors.

Execute the same lifecycle, mutation, Cypher, traversal, hybrid, pagination,
transaction, conflict, restart, invalid-input, unavailable-backend, and limit
vectors over Python, CLI, MCP, and MCP++.

Require exact rows / revision / error codes and normalized metadata.
No surface-specific exception waiver.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from .harness import (
    close_all,
    corrupt_payloads,
    open_all_surfaces,
    run_conflict_per_surface,
    run_cypher,
    run_hybrid,
    run_invalid_bad_cypher,
    run_invalid_missing_target,
    run_lifecycle,
    run_limit,
    run_mutation,
    run_pagination,
    run_restart,
    run_transaction_per_surface,
    run_traversal,
    run_unavailable_backend,
    seed_catalog,
)
from .normalize import (
    assert_json_safe,
    dumps_canonical,
    extract_error_code,
    normalize_envelope,
)
from .surfaces import all_surface_names, fixture_path, load_vector_catalog


SURFACES = all_surface_names()


# ---------------------------------------------------------------------------
# Fixture / catalog integrity
# ---------------------------------------------------------------------------


class TestVectorCatalogFixtures:
    def test_catalog_lists_all_required_categories(self) -> None:
        catalog = load_vector_catalog()
        assert catalog["catalog_version"] == "kg-conformance-vectors/v1"
        assert catalog["surfaces"] == list(SURFACES)
        categories = {v["category"] for v in catalog["vectors"]}
        required = {
            "lifecycle",
            "mutation",
            "cypher",
            "traversal",
            "hybrid",
            "pagination",
            "transaction",
            "conflict",
            "restart",
            "invalid-input",
            "unavailable-backend",
            "limit",
        }
        assert required <= categories, required - categories

    def test_seed_graph_fixture_shape(self) -> None:
        seed = json.loads(
            fixture_path("seed_graph.json").read_text(encoding="utf-8")
        )
        assert seed["fixture_version"] == "kg-conformance-seed/v1"
        assert len(seed["entities"]) == 5
        assert len(seed["relationships"]) == 4
        assert_json_safe(seed)


# ---------------------------------------------------------------------------
# Normalization unit checks
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_strips_transport_metadata_keeps_rows_revision(self) -> None:
        left = {
            "contract_version": "kg-service-contract/v1",
            "status": "success",
            "operation": "query",
            "request_id": "req-aaa",
            "authorization_receipt_ref": "auth-1",
            "result": {
                "revision": "kg-rev-1",
                "row_count": 1,
                "rows": [["a", "T", "A", {}]],
                "columns": ["id", "type", "name", "properties"],
                "statistics": {"elapsed_ms": 1.23, "nodes_visited": 1},
                "truncated": False,
            },
            "error": None,
            "warnings": [],
        }
        right = {
            "contract_version": "kg-service-contract/v1",
            "status": "success",
            "operation": "query",
            "request_id": "req-bbb",
            "result": {
                "revision": "kg-rev-1",
                "row_count": 1,
                "rows": [["a", "T", "A", {}]],
                "columns": ["id", "type", "name", "properties"],
                "statistics": {"elapsed_ms": 9.99, "nodes_visited": 1},
                "truncated": False,
            },
            "error": None,
            "warnings": [],
            "search_type": "hybrid",
            "results": [["a", "T", "A", {}]],
            "count": 1,
        }
        assert dumps_canonical(normalize_envelope(left)) == dumps_canonical(
            normalize_envelope(right)
        )

    def test_error_code_preserved_message_stripped(self) -> None:
        env = {
            "status": "error",
            "operation": "query",
            "error": {
                "code": "CONFLICT",
                "message": "branch head moved",
                "retryable": True,
                "details": {"error_type": "CatalogError"},
            },
        }
        norm = normalize_envelope(env)
        assert norm["error"]["code"] == "CONFLICT"
        assert "message" not in norm["error"]
        assert "error_type" not in (norm["error"].get("details") or {})


# ---------------------------------------------------------------------------
# Shared-catalog vectors (exact revision + rows across surfaces)
# ---------------------------------------------------------------------------


class TestLifecycleVector:
    def test_create_list_describe_open_all_surfaces(
        self, kg_paths: tuple[Path, Path]
    ) -> None:
        catalog, store = kg_paths
        surfaces = open_all_surfaces(catalog, store)
        try:
            summary = run_lifecycle(surfaces)
            assert summary["create_revision"].startswith("kg-bootstrap-")
            for name in SURFACES:
                assert name in summary["surfaces"]
        finally:
            close_all(surfaces)


class TestMutationVector:
    def test_scan_rows_and_revision_match(
        self, seeded_catalog: dict, seeded_surfaces: dict
    ) -> None:
        summary = run_mutation(seeded_surfaces, meta=seeded_catalog)
        assert summary["row_count"] == 5
        assert summary["revision"] == seeded_catalog["revision"]
        assert summary["status"] == "success"


class TestCypherVector:
    def test_match_person_exact_row_count(
        self, seeded_catalog: dict, seeded_surfaces: dict
    ) -> None:
        summary = run_cypher(seeded_surfaces, meta=seeded_catalog)
        assert summary["row_count"] == 3
        assert summary["revision"] == seeded_catalog["revision"]


class TestTraversalVector:
    def test_count_entities_and_relationships(
        self, seeded_catalog: dict, seeded_surfaces: dict
    ) -> None:
        summary = run_traversal(seeded_surfaces, meta=seeded_catalog)
        # rows compared inside runner; revision must match seed write.
        assert summary["revision"] == seeded_catalog["revision"]


class TestHybridVector:
    def test_hybrid_scan_envelope_parity(
        self, seeded_catalog: dict, seeded_surfaces: dict
    ) -> None:
        summary = run_hybrid(seeded_surfaces, meta=seeded_catalog)
        assert summary["row_count"] == 5
        assert summary["revision"] == seeded_catalog["revision"]


class TestPaginationVector:
    def test_stream_pages_exact_total(
        self, seeded_catalog: dict, seeded_surfaces: dict
    ) -> None:
        summary = run_pagination(seeded_surfaces, meta=seeded_catalog)
        for name in SURFACES:
            assert summary[name]["total_rows"] == 5
            assert summary[name]["page_count"] == 3


class TestRestartVector:
    def test_reopen_exact_revision_and_rows(
        self, kg_paths: tuple[Path, Path]
    ) -> None:
        catalog, store = kg_paths
        meta = seed_catalog(catalog, store, idem_prefix="restart")
        meta["catalog"] = catalog
        meta["store"] = store
        surfaces = open_all_surfaces(catalog, store)
        try:
            summary = run_restart(catalog, store, surfaces, meta=meta)
            assert summary["revision"] == meta["revision"]
            assert summary["row_count"] == 5
        finally:
            close_all(surfaces)


class TestInvalidInputVectors:
    def test_missing_target_typed_error_all_surfaces(
        self, kg_paths: tuple[Path, Path]
    ) -> None:
        catalog, store = kg_paths
        surfaces = open_all_surfaces(catalog, store)
        try:
            results = run_invalid_missing_target(surfaces)
            assert set(results) == set(SURFACES)
            for name, env in results.items():
                assert env["status"] == "error"
                assert extract_error_code(env) in {
                    "INVALID_TARGET",
                    "INVALID_REQUEST",
                }
                assert_json_safe(env)
        finally:
            close_all(surfaces)

    def test_bad_cypher_typed_error_all_surfaces(
        self, seeded_catalog: dict, seeded_surfaces: dict
    ) -> None:
        results = run_invalid_bad_cypher(
            seeded_surfaces, meta=seeded_catalog
        )
        for name, env in results.items():
            assert env["status"] == "error", name
            assert extract_error_code(env) == "INTERNAL", name
            assert env["error"]["retryable"] is False, name


class TestUnavailableBackendVector:
    def test_corrupt_payload_internal_all_surfaces(
        self, kg_paths: tuple[Path, Path]
    ) -> None:
        catalog, store = kg_paths
        meta = seed_catalog(catalog, store, idem_prefix="unavail")
        n = corrupt_payloads(store)
        assert n >= 1
        surfaces = open_all_surfaces(catalog, store)
        try:
            results = run_unavailable_backend(surfaces, meta=meta)
            codes = {n: extract_error_code(e) for n, e in results.items()}
            assert set(codes.values()) == {"INTERNAL"}
            for env in results.values():
                assert env["error"]["retryable"] is False
                assert_json_safe(env)
        finally:
            close_all(surfaces)


class TestLimitVector:
    def test_max_rows_truncation_exact(
        self, seeded_catalog: dict, seeded_surfaces: dict
    ) -> None:
        summary = run_limit(seeded_surfaces, meta=seeded_catalog)
        assert summary["row_count"] == 2
        assert summary["truncated"] is True
        assert summary["revision"] == seeded_catalog["revision"]


# ---------------------------------------------------------------------------
# Per-surface vectors (transaction / conflict) with cross-surface code parity
# ---------------------------------------------------------------------------


class TestTransactionVector:
    @pytest.mark.parametrize("surface_name", SURFACES)
    def test_begin_stage_commit_visible(
        self, kg_paths: tuple[Path, Path], surface_name: str
    ) -> None:
        catalog, store = kg_paths
        post = run_transaction_per_surface(catalog, store, surface_name)
        assert post["status"] == "success"
        assert post["result"]["row_count"] == 1

    def test_transaction_row_parity_across_surfaces(
        self, tmp_path: Path
    ) -> None:
        """Each surface commits one node; independent readers agree on count."""
        # Use isolated stores per surface to avoid graph_id collisions, then
        # compare structural outcomes (row_count / name), not shared revision.
        outcomes: Dict[str, Any] = {}
        for name in SURFACES:
            cat = tmp_path / name / "catalog.sqlite"
            store = tmp_path / name / "payloads"
            cat.parent.mkdir(parents=True, exist_ok=True)
            post = run_transaction_per_surface(cat, store, name)
            outcomes[name] = {
                "row_count": post["result"]["row_count"],
                "names": sorted(
                    r[2] for r in post["result"]["rows"] if isinstance(r, list)
                ),
            }
        assert all(o["row_count"] == 1 for o in outcomes.values()), outcomes
        assert all(o["names"] == ["tx-node"] for o in outcomes.values()), outcomes


class TestConflictVector:
    @pytest.mark.parametrize("surface_name", SURFACES)
    def test_commit_conflict_code(
        self, kg_paths: tuple[Path, Path], surface_name: str
    ) -> None:
        catalog, store = kg_paths
        commit = run_conflict_per_surface(catalog, store, surface_name)
        assert commit["status"] == "error"
        assert extract_error_code(commit) == "CONFLICT"
        assert commit["error"]["retryable"] is True
        assert_json_safe(commit)

    def test_conflict_code_identical_all_surfaces(self, tmp_path: Path) -> None:
        codes = {}
        for name in SURFACES:
            cat = tmp_path / name / "catalog.sqlite"
            store = tmp_path / name / "payloads"
            cat.parent.mkdir(parents=True, exist_ok=True)
            commit = run_conflict_per_surface(cat, store, name)
            codes[name] = extract_error_code(commit)
        assert set(codes.values()) == {"CONFLICT"}, codes


# ---------------------------------------------------------------------------
# Matrix: every catalog vector id is covered
# ---------------------------------------------------------------------------


class TestCatalogCoverage:
    def test_every_vector_id_has_executable_runner(self) -> None:
        catalog = load_vector_catalog()
        # Map vector ids to the test methods that cover them (documentation lock).
        covered = {
            "lifecycle.create_list_describe_open",
            "mutation.write_entities_relationships",
            "cypher.match_person_return",
            "traversal.count_entities_relationships",
            "hybrid.scan_search",
            "pagination.stream_pages",
            "transaction.begin_stage_commit",
            "conflict.commit_after_head_move",
            "restart.reopen_committed",
            "invalid_input.missing_target",
            "invalid_input.bad_cypher",
            "unavailable_backend.corrupt_payload",
            "limit.max_rows_truncation",
        }
        ids = {v["id"] for v in catalog["vectors"]}
        assert ids == covered, (ids - covered, covered - ids)
