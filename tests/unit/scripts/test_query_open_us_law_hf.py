"""Unit tests for the Open US Law HF query API and CLI (OUL-035).

Acceptance:

* Package and CLI expose BM25, vector, hybrid, graph, and semantic-graph
  modes.
* Jurisdiction and status filters, immutable pins, fetch traces, and
  resource budgets are first-class.
* Queries do not download the full index.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data import open_us_law_sparse_graphrag as api

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "query_open_us_law_hf.py"
PINNED_REVISION = api.DEFAULT_REVISION


def _load_cli():
    assert SCRIPT.is_file()
    spec = importlib.util.spec_from_file_location(
        "query_open_us_law_hf_oul035", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


@pytest.fixture
def mini_release(tmp_path: Path) -> Path:
    from tests.unit.processors.legal_data.test_open_us_law_query import (
        build_mini_release,
    )

    release = tmp_path / "release"
    release.mkdir()
    build_mini_release(release)
    return release


def _common_cli_args(release: Path) -> list[str]:
    return [
        "--local-root",
        str(release),
        "--revision",
        PINNED_REVISION,
        "--fixture-mode",
        "--json",
        "--trace",
    ]


def argparse_ns(**kwargs):
    return type("NS", (), kwargs)()


# ---------------------------------------------------------------------------
# Package surface (no I/O)
# ---------------------------------------------------------------------------


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_import_is_optional_dependency_safe() -> None:
    receipt = api.import_is_optional_dependency_safe()
    assert receipt["optional_dependency_safe"] is True
    assert receipt["stdlib_only_at_import"] is True
    assert receipt["heavy_backends_imported"] is False


def test_package_exposes_five_modes() -> None:
    assert api.list_query_modes() == (
        "bm25",
        "vector",
        "hybrid",
        "graph",
        "semantic-graph",
    )
    assert set(api.QUERY_MODES) == {
        "bm25",
        "vector",
        "hybrid",
        "graph",
        "semantic-graph",
    }
    surface = api.query_surface()
    assert surface["modes"] == list(api.QUERY_MODES)
    assert "jurisdiction" in surface["filter_fields"]
    assert "status" in surface["filter_fields"]
    assert surface["fetch_traces"] is True
    assert surface["resource_budgets"] is True
    assert surface["full_index_download"] is False
    assert surface["pins"]["mutable_rejected"] is True
    assert surface["task_id"] == "OUL-035"


def test_open_api_package_identity() -> None:
    facade = api.open_api()
    identity = facade.package_identity()
    assert identity["task_id"] == "OUL-035"
    assert identity["goal_id"] == "OUL-G050"
    assert identity["primary_key"] == "entry_cid"
    assert identity["corpus_id"] == "open-us-law"
    assert identity["dataset_repo_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert identity["full_index_download"] is False
    assert set(identity["modes"]) == set(api.QUERY_MODES)


def test_normalize_query_mode_aliases() -> None:
    assert api.normalize_query_mode("graph-walk") == "graph"
    assert api.normalize_query_mode("graph_walk") == "graph"
    assert api.normalize_query_mode("neighbors") == "graph"
    assert api.normalize_query_mode("semantic-graph-walk") == "semantic-graph"
    with pytest.raises(api.QueryModeError):
        api.normalize_query_mode("full-scan")


def test_immutable_pins_reject_mutable_and_empty() -> None:
    with pytest.raises(api.ImmutablePinError):
        api.require_immutable_pin("main")
    with pytest.raises(api.ImmutablePinError):
        api.require_immutable_pin("latest")
    with pytest.raises(api.ImmutablePinError):
        api.require_immutable_pin("")
    with pytest.raises(api.ImmutablePinError):
        api.require_immutable_pin("HEAD")
    with pytest.raises(api.ImmutablePinError):
        api.require_immutable_pin("not-a-sha")
    pin = api.require_immutable_pin(PINNED_REVISION)
    assert pin == PINNED_REVISION
    dataset = api.ImmutableQueryPin.dataset(PINNED_REVISION)
    assert dataset.transport == "dataset"
    assert dataset.revision == PINNED_REVISION
    digest = "a" * 64
    bucket = api.ImmutableQueryPin.bucket(f"releases/{digest}/")
    assert bucket.transport == "bucket"
    assert bucket.manifest_sha256 == digest


def test_resource_budgets_round_trip() -> None:
    budgets = api.ResourceBudgets(
        max_bytes=1_000_000,
        max_shards=8,
        max_rows=100,
        max_nodes=16,
        max_edges=32,
        max_depth=2,
        max_time_ms=5_000,
    )
    payload = budgets.to_dict()
    assert payload["max_bytes"] == 1_000_000
    assert payload["max_shards"] == 8
    assert set(payload) >= {
        "max_bytes",
        "max_shards",
        "max_rows",
        "max_nodes",
        "max_edges",
        "max_depth",
        "max_time_ms",
    }
    limits = budgets.to_query_limits()
    assert limits.max_bytes == 1_000_000
    assert limits.max_nodes == 16
    with pytest.raises(api.ResourceBudgetError):
        api.ResourceBudgets(max_bytes=0)


def test_lazy_export_resolution_for_query_client_symbol() -> None:
    name = "OpenUsLawQueryClient"
    assert name in api.available_lazy_exports()
    resolved = api.resolve_export(name)
    assert resolved is not None
    assert getattr(resolved, "__name__", "") == "OpenUsLawQueryClient"


# ---------------------------------------------------------------------------
# CLI help / fail-closed pins / secrets
# ---------------------------------------------------------------------------


def test_help_exits_zero(cli) -> None:
    assert cli.main(["--help"]) == 0
    for command in cli.SUBCOMMANDS:
        assert cli.main([command, "--help"]) == 0


def test_help_documents_acceptance_surface(cli, capsys) -> None:
    assert cli.main(["--help"]) == 0
    text = capsys.readouterr().out.lower()
    for mode in api.QUERY_MODES:
        assert mode in text
    assert "jurisdiction" in text
    assert "status" in text
    assert "revision" in text
    assert "max-bytes" in text
    assert "trace" in text
    parser = cli.build_parser()
    help_text = parser.format_help().lower()
    for mode in api.QUERY_MODES:
        assert mode in help_text
    actions = {action.dest for action in parser._actions}
    assert "jurisdiction" in actions
    assert "status" in actions
    assert "revision" in actions
    assert "max_bytes" in actions
    assert "trace" in actions


def test_subcommand_list_covers_public_modes(cli) -> None:
    assert set(api.QUERY_MODES).issubset(set(cli.SUBCOMMANDS))
    assert set(cli.SUBCOMMANDS) == {
        "bm25",
        "vector",
        "hybrid",
        "graph",
        "semantic-graph",
        "neighbors",
    }


def test_mutable_revision_rejected_for_live_hub(cli) -> None:
    with pytest.raises(cli.CliError):
        cli._build_client(
            argparse_ns(
                repo_id="justicedao/open-us-law-sparse-graphrag",
                revision="main",
                cache_dir=None,
                local_root=None,
                fixture_mode=False,
                command="bm25",
                embedding=None,
                embedding_dim=2,
                transport="dataset",
                bucket_prefix=None,
                max_bytes=1_000_000,
                max_shards=8,
                max_rows=100,
                max_nodes=16,
                max_edges=32,
                max_depth=2,
                max_time_ms=5_000,
            )
        )


def test_secret_argv_rejected(cli) -> None:
    with pytest.raises(cli.CliError):
        cli._reject_secrets_in_argv(["--hf_token=abc123", "bm25", "x"])


# ---------------------------------------------------------------------------
# Offline package + CLI queries
# ---------------------------------------------------------------------------


def test_package_offline_bm25_filters_and_sparse_io(mini_release: Path) -> None:
    client = api.open_query_client(
        revision=PINNED_REVISION,
        local_root=mini_release,
        budgets=api.ResourceBudgets(max_bytes=10_000_000, max_shards=32),
    )
    result = client.bm25_search(
        "foia",
        top_k=3,
        hydrate=True,
        jurisdiction="OR",
        status="current",
    )
    assert result.mode == "bm25"
    assert result.result_count >= 1
    assert result.results[0]["entry_cid"] == "entry-a"
    for hit in result.results:
        assert str(hit.get("jurisdiction")).upper() == "OR"
        assert str(hit.get("status")).lower() == "current"
    assert result.fetch_trace
    assert result.limits["max_bytes"] == 10_000_000
    assert result.limits["max_shards"] == 32
    paths = api.fetched_relative_paths(result)
    assert any(path.endswith("data/bm25/postings/part-000000.parquet") for path in paths)
    assert not any(
        path.endswith("data/bm25/postings/part-000001.parquet") for path in paths
    )
    assert api.proves_sparse_io(result) is True
    packaged = api.package_query_result(result, pin=client.pin, include_trace=True)
    assert packaged["full_index_downloaded"] is False
    assert packaged["pin"]["revision"] == PINNED_REVISION
    assert "fetch_trace" in packaged


def test_package_all_five_modes(mini_release: Path) -> None:
    client = api.open_query_client(
        revision=PINNED_REVISION,
        local_root=mini_release,
        query_embedder=lambda text: [1.0, 0.0],
    )
    bm25 = client.query("bm25", query="agency", top_k=2)
    assert bm25.mode == "bm25"
    assert bm25.fetch_trace

    vector = client.query(
        "vector",
        query="agency",
        query_vector=[1.0, 0.0],
        top_k=2,
    )
    assert vector.mode == "vector"
    assert vector.fetch_trace

    hybrid = client.query(
        "hybrid",
        query="agency",
        query_vector=[1.0, 0.0],
        top_k=2,
        jurisdiction="OR",
    )
    assert hybrid.mode == "hybrid"
    assert hybrid.fetch_trace
    for hit in hybrid.results:
        assert str(hit.get("jurisdiction")).upper() == "OR"

    graph = client.query("graph", start_node_cid="entry-a", max_depth=1, max_nodes=4)
    assert graph.mode == "graph_walk"
    assert graph.fetch_trace
    assert graph.limits["max_nodes"] >= 1

    semantic = client.query(
        "semantic-graph",
        start_node_cid="entry-a",
        query="agency",
        query_vector=[1.0, 0.0],
        max_depth=1,
        max_nodes=4,
    )
    assert semantic.mode == "semantic_graph_walk"
    assert semantic.fetch_trace
    packaged = api.package_query_result(semantic, include_trace=True)
    assert packaged["mode"] == "semantic-graph"
    assert packaged["full_index_downloaded"] is False


def test_offline_bm25_against_mini_release(cli, mini_release: Path, capsys) -> None:
    rc = cli.main(
        [
            *_common_cli_args(mini_release),
            "--jurisdiction",
            "OR",
            "--status",
            "current",
            "--max-bytes",
            "10000000",
            "--max-shards",
            "32",
            "bm25",
            "foia agency",
            "--top-k",
            "2",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "bm25"
    assert "results" in payload
    assert "fetch_trace" in payload
    assert payload["full_index_downloaded"] is False
    assert payload["filters"]["jurisdiction"] == "OR"
    assert payload["filters"]["status"] == "current"
    assert payload["limits"]["max_bytes"] == 10_000_000
    assert payload["pin"]["revision"] == PINNED_REVISION
    rendered = json.dumps(payload)
    secret = os.environ.get("HF_TOKEN")
    if secret:
        assert secret not in rendered


def test_offline_vector_hybrid_graph_and_semantic(
    cli, mini_release: Path, capsys
) -> None:
    common = _common_cli_args(mini_release)

    assert (
        cli.main(
            [
                *common,
                "vector",
                "agency",
                "--embedding",
                "1.0,0.0",
                "--top-k",
                "2",
            ]
        )
        == 0
    )
    vector = json.loads(capsys.readouterr().out)
    assert vector["mode"] == "vector"
    assert "fetch_trace" in vector
    assert vector["full_index_downloaded"] is False

    assert (
        cli.main(
            [
                *common,
                "--jurisdiction",
                "OR",
                "hybrid",
                "agency",
                "--embedding",
                "1.0,0.0",
                "--top-k",
                "2",
            ]
        )
        == 0
    )
    hybrid = json.loads(capsys.readouterr().out)
    assert hybrid["mode"] == "hybrid"
    assert hybrid["filters"]["jurisdiction"] == "OR"
    assert "fetch_trace" in hybrid

    assert (
        cli.main(
            [
                *common,
                "graph",
                "entry-a",
                "--walk-depth",
                "1",
                "--walk-nodes",
                "4",
                "--walk-edges",
                "8",
            ]
        )
        == 0
    )
    walk = json.loads(capsys.readouterr().out)
    assert walk["mode"] == "graph"
    assert "results" in walk
    assert "fetch_trace" in walk
    assert walk["limits"]["max_nodes"] >= 1

    assert (
        cli.main(
            [
                *common,
                "semantic-graph",
                "entry-a",
                "--query",
                "agency",
                "--embedding",
                "1.0,0.0",
                "--walk-depth",
                "1",
                "--walk-nodes",
                "4",
                "--walk-edges",
                "8",
            ]
        )
        == 0
    )
    semantic = json.loads(capsys.readouterr().out)
    assert semantic["mode"] == "semantic-graph"
    assert "fetch_trace" in semantic
    assert semantic["full_index_downloaded"] is False


def test_offline_neighbors_via_graph_alias(cli, mini_release: Path, capsys) -> None:
    common = _common_cli_args(mini_release)
    assert cli.main([*common, "neighbors", "entry-a", "--limit", "4"]) == 0
    neighbors = json.loads(capsys.readouterr().out)
    assert neighbors["mode"] == "graph"
    assert "results" in neighbors

    assert (
        cli.main(
            [*common, "graph", "entry-a", "--neighbors-only", "--limit", "4"]
        )
        == 0
    )
    via_graph = json.loads(capsys.readouterr().out)
    assert via_graph["mode"] == "graph"


def test_cli_maps_exactly_to_package_api(cli, mini_release: Path, capsys) -> None:
    rc = cli.main(
        [*_common_cli_args(mini_release), "bm25", "privacy", "--top-k", "3"]
    )
    assert rc == 0
    cli_payload = json.loads(capsys.readouterr().out)

    client = api.open_query_client(
        revision=PINNED_REVISION, local_root=mini_release
    )
    api_result = client.bm25_search("privacy", top_k=3)
    assert cli_payload["mode"] == "bm25"
    assert api_result.mode == "bm25"
    assert cli_payload["result_count"] == api_result.result_count
    assert [hit.get("entry_cid") for hit in cli_payload["results"]] == [
        hit.get("entry_cid") for hit in api_result.results
    ]


def test_package_query_result_strips_trace_when_requested(
    mini_release: Path,
) -> None:
    client = api.open_query_client(
        revision=PINNED_REVISION, local_root=mini_release
    )
    result = client.bm25_search("foia", top_k=1)
    stripped = api.package_query_result(result, include_trace=False)
    assert "fetch_trace" not in stripped
    assert stripped["full_index_downloaded"] is False
