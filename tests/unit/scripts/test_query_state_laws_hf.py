"""Unit tests for the state-law HF query API and CLI (LCR-034).

Acceptance:

* Structured JSON and JSONL modes.
* Immutable repo/revision binding; no mutable-main default.
* Jurisdiction (including DC) / code / citation filters, budgets,
  JSON explanations, and redacted traces.
* Local fixture transport and explicit offline replay.
* API/CLI parity, deterministic ordering, exit codes, malformed-input
  rejection, and no import-time network/model load.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors import legal_data as legal_data_pkg
from ipfs_datasets_py.processors.legal_data import state_laws_sparse_graphrag as api
from ipfs_datasets_py.processors.legal_data.state_laws_sparse_graphrag import (
    StateLawsSparseGraphragClient,
    query_replay_fingerprint,
    require_immutable_pin,
)

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "query_state_laws_hf.py"
PINNED_REVISION = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
REPO_ID = "justicedao/ipfs_state_laws"


def _load_cli():
    assert SCRIPT.is_file()
    spec = importlib.util.spec_from_file_location(
        "query_state_laws_hf_lcr034", SCRIPT
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
    from tests.unit.processors.legal_data.test_state_laws_sparse_query import (
        build_mini_release,
    )

    release = tmp_path / "release"
    release.mkdir()
    build_mini_release(release)
    return release


def _common_cli_args(release: Path, cache: Path | None = None) -> list[str]:
    args = [
        "--local-root",
        str(release),
        "--revision",
        PINNED_REVISION,
        "--repo-id",
        REPO_ID,
        "--fixture-mode",
        "--json",
        "--trace",
    ]
    if cache is not None:
        args.extend(["--cache-dir", str(cache)])
    return args


def argparse_ns(**kwargs):
    return type("NS", (), kwargs)()


# ---------------------------------------------------------------------------
# Package surface / exports (no I/O)
# ---------------------------------------------------------------------------


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_package_exports_query_client_lazily() -> None:
    assert "StateLawsSparseGraphragClient" in legal_data_pkg.__all__
    assert "StateLawsSparseGraphragClient" in legal_data_pkg._LAZY_EXPORTS
    resolved = legal_data_pkg.StateLawsSparseGraphragClient
    assert resolved is StateLawsSparseGraphragClient
    assert resolved.__name__ == "StateLawsSparseGraphragClient"


def test_import_is_optional_dependency_safe() -> None:
    receipt = api.import_is_optional_dependency_safe()
    assert receipt["optional_dependency_safe"] is True
    assert receipt["stdlib_only_at_import"] is True
    assert receipt["heavy_backends_imported"] is False


def test_query_surface_documents_acceptance(cli) -> None:
    surface = cli.query_surface()
    assert surface["task_id"] == "LCR-034"
    assert surface["goal_id"] == "LCR-G050"
    assert surface["program_id"] == "legal-corpora-reindex-v1"
    assert surface["engine_task_id"] == "LCR-033"
    assert surface["mutable_main_default"] is False
    assert surface["offline_replay"] is True
    assert surface["full_index_download"] is False
    assert surface["jurisdiction_includes_dc"] is True
    assert surface["json_explanations"] is True
    assert surface["redacted_traces"] is True
    assert surface["formats"] == ["json", "jsonl", "text"]
    assert "jurisdiction" in surface["filter_fields"]
    assert "code" in surface["filter_fields"]
    assert "citation" in surface["filter_fields"]
    assert set(surface["modes"]) == {
        "bm25",
        "vector",
        "hybrid",
        "neighbors",
        "graph_walk",
        "semantic_graph_walk",
    }
    assert surface["pins"]["revision"] == PINNED_REVISION
    assert surface["pins"]["mutable_rejected"] is True


def test_open_api_package_identity() -> None:
    facade = api.open_api()
    identity = facade.package_identity()
    assert identity["task_id"] == "LCR-034"
    assert identity["goal_id"] == "LCR-G050"
    assert identity["primary_key"] == "entry_cid"
    assert identity["corpus_id"] == "state-laws"
    assert identity["dataset_repo_id"] == REPO_ID
    assert identity["full_index_download"] is False
    assert identity["jurisdiction_includes_dc"] is True
    assert set(identity["modes"]) == set(api.QUERY_MODES)


def test_default_revision_is_immutable_not_main(cli) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["bm25", "foia"])
    assert args.revision == cli.DEFAULT_REVISION
    assert args.revision.casefold() not in cli.MUTABLE_REFS
    assert args.repo_id == REPO_ID
    assert require_immutable_pin(args.revision) == PINNED_REVISION


def test_cli_import_does_not_contact_network(monkeypatch) -> None:
    def _blocked(*_args, **_kwargs):
        raise AssertionError("network access at import time")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    before = set(sys.modules)
    module = _load_cli()
    added = set(sys.modules) - before
    assert module.TASK_ID == "LCR-034"
    assert module.main(["--help"]) == 0
    for banned in ("sentence_transformers", "transformers", "torch"):
        assert banned not in added


def test_normalize_query_mode_aliases() -> None:
    assert api.normalize_query_mode("graph-walk") == "graph_walk"
    assert api.normalize_query_mode("graph_walk") == "graph_walk"
    assert api.normalize_query_mode("neighbors") == "neighbors"
    assert api.normalize_query_mode("semantic-graph-walk") == "semantic_graph_walk"
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
    limits = budgets.to_query_limits()
    assert limits.max_bytes == 1_000_000
    assert limits.max_nodes == 16
    with pytest.raises(api.ResourceBudgetError):
        api.ResourceBudgets(max_bytes=0)


def test_lazy_export_resolution_for_query_client_symbol() -> None:
    name = "StateLawsQueryClient"
    assert name in api.available_lazy_exports()
    resolved = api.resolve_export(name)
    assert resolved is not None
    assert getattr(resolved, "__name__", "") == "StateLawsQueryClient"


# ---------------------------------------------------------------------------
# CLI help / fail-closed pins / secrets / malformed input
# ---------------------------------------------------------------------------


def test_help_exits_zero(cli) -> None:
    assert cli.main(["--help"]) == 0
    for command in cli.SUBCOMMANDS:
        assert cli.main([command, "--help"]) == 0


def test_help_documents_acceptance_surface(cli, capsys) -> None:
    assert cli.main(["--help"]) == 0
    text = capsys.readouterr().out.lower()
    for token in (
        "bm25",
        "vector",
        "hybrid",
        "neighbors",
        "graph-walk",
        "semantic-graph-walk",
        "jsonl",
        "jurisdiction",
        "dc",
        "citation",
        "revision",
        "max-bytes",
        "cache-dir",
        "offline-replay",
        "fixture",
    ):
        assert token in text


def test_subcommand_list_covers_public_modes(cli) -> None:
    assert set(cli.SUBCOMMANDS) == {
        "bm25",
        "vector",
        "hybrid",
        "neighbors",
        "graph-walk",
        "semantic-graph-walk",
    }


def test_mutable_revision_rejected(cli) -> None:
    rc = cli.main(["--revision", "main", "bm25", "foia"])
    assert rc == 2
    with pytest.raises(cli.CliError):
        cli.open_query_client(revision="main")
    with pytest.raises(cli.CliError):
        cli.open_query_client(revision="latest")
    with pytest.raises(cli.CliError):
        cli.open_query_client(revision="")


def test_secret_argv_rejected(cli) -> None:
    with pytest.raises(cli.CliError):
        cli._reject_secrets_in_argv(["--hf_token=abc123", "bm25", "x"])
    assert cli.main(["--hf_token=abc123", "bm25", "x"]) == 2


def test_malformed_input_rejected(cli, mini_release: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    common = _common_cli_args(mini_release, cache)
    assert cli.main([*common, "bm25", ""]) == 2
    assert cli.main(["--max-bytes", "0", *common, "bm25", "foia"]) == 2
    assert cli.main([*common, "vector", "agency", "--embedding", "not-a-float"]) == 2
    assert cli.main(["--json", "--jsonl", *common[0:6], "bm25", "foia"]) == 2
    assert cli.main(["--offline-replay", "bm25", "foia"]) == 2
    assert cli.main(["--expected-fingerprint", "abc", "bm25", "foia"]) == 2
    missing = tmp_path / "missing-root"
    assert cli.main(["--local-root", str(missing), "bm25", "foia"]) == 2


# ---------------------------------------------------------------------------
# Offline package + CLI queries
# ---------------------------------------------------------------------------


def test_offline_bm25_structured_json(cli, mini_release: Path, tmp_path: Path, capsys) -> None:
    cache = tmp_path / "cache"
    rc = cli.main(
        [
            *_common_cli_args(mini_release, cache),
            "--jurisdiction",
            "OR",
            "--code",
            "ORS",
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
    assert payload["filters"]["code"] == "ORS"
    assert payload["pin"]["revision"] == PINNED_REVISION
    assert payload["pin"]["mutable_rejected"] is True
    assert payload["interface_task_id"] == "LCR-034"
    assert payload["engine_task_id"] == "LCR-033"
    assert payload["limits"]["max_bytes"] == 10_000_000
    assert payload["ordered_result_cids"]
    assert payload.get("explain") or payload.get("json_explanations") is not False
    assert payload.get("redacted_trace") is True
    secret = os.environ.get("HF_TOKEN")
    if secret:
        assert secret not in json.dumps(payload)


def test_jsonl_mode_emits_header_and_hits(
    cli, mini_release: Path, tmp_path: Path, capsys
) -> None:
    cache = tmp_path / "cache"
    args = _common_cli_args(mini_release, cache)
    args.remove("--json")
    args.append("--jsonl")
    rc = cli.main([*args, "--offline-replay", "bm25", "foia", "--top-k", "2"])
    assert rc == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines
    records = [json.loads(line) for line in lines]
    kinds = [record["kind"] for record in records]
    assert kinds[0] == "result"
    assert "hit" in kinds
    assert "replay" in kinds
    header = records[0]
    assert header["mode"] == "bm25"
    assert header["offline_replay"] is True
    assert header["replay_fingerprint"]
    hits = [record for record in records if record["kind"] == "hit"]
    assert hits
    assert [record["index"] for record in hits] == list(range(len(hits)))


def test_offline_vector_hybrid_graph_and_semantic(
    cli, mini_release: Path, tmp_path: Path, capsys
) -> None:
    common = _common_cli_args(mini_release, tmp_path / "cache")

    assert (
        cli.main(
            [*common, "vector", "agency", "--embedding", "1.0,0.0", "--top-k", "2"]
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
                "graph-walk",
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
    assert walk["mode"] == "graph_walk"
    assert "results" in walk
    assert "fetch_trace" in walk
    assert walk.get("explain")

    assert cli.main([*common, "neighbors", "entry-a", "--limit", "4"]) == 0
    neighbors = json.loads(capsys.readouterr().out)
    assert neighbors["mode"] == "neighbors"
    assert "results" in neighbors

    assert (
        cli.main(
            [
                *common,
                "semantic-graph-walk",
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
    assert semantic["mode"] == "semantic_graph_walk"
    assert "fetch_trace" in semantic
    assert semantic["full_index_downloaded"] is False


def test_dc_jurisdiction_code_and_citation_filters(
    cli, mini_release: Path, tmp_path: Path, capsys
) -> None:
    common = _common_cli_args(mini_release, tmp_path / "cache")

    assert (
        cli.main(
            [
                *common,
                "--jurisdiction",
                "DC",
                "--code",
                "DC",
                "vector",
                "public records",
                "--embedding=-0.8,0.2",
                "--top-k",
                "3",
            ]
        )
        == 0
    )
    vector = json.loads(capsys.readouterr().out)
    assert vector["mode"] == "vector"
    assert vector["filters"]["jurisdiction"] == "DC"
    assert vector["filters"]["code"] == "DC"
    assert vector["full_index_downloaded"] is False
    for hit in vector["results"]:
        assert str(hit.get("jurisdiction")).upper() == "DC"
        assert str(hit.get("code")).upper() == "DC"

    assert (
        cli.main(
            [
                *common,
                "--citation",
                "D.C. Code § 2-531",
                "vector",
                "inspection",
                "--embedding=-0.8,0.2",
                "--top-k",
                "3",
            ]
        )
        == 0
    )
    cited = json.loads(capsys.readouterr().out)
    assert cited["filters"]["citation"] == "D.C. Code § 2-531"
    for hit in cited["results"]:
        assert "2-531" in str(hit.get("citation"))
        assert str(hit.get("jurisdiction")).upper() == "DC"

    assert (
        cli.main(
            [
                *common,
                "graph-walk",
                "entry-b",
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
    node_ids = {
        str(hit.get("node_cid") or hit.get("entry_cid") or "")
        for hit in walk["results"]
    }
    assert "entry-c" in node_ids or any(
        str(edge.get("neighbor_cid")) == "entry-c"
        for edge in walk.get("edges") or ()
    )

    assert cli.main([*common, "neighbors", "entry-b", "--limit", "4"]) == 0
    neighbors = json.loads(capsys.readouterr().out)
    neighbor_ids = {
        str(hit.get("node_cid") or hit.get("entry_cid") or "")
        for hit in neighbors["results"]
    }
    assert "entry-c" in neighbor_ids


def test_package_all_modes_including_dc(mini_release: Path) -> None:
    client = api.open_query_client(
        revision=PINNED_REVISION,
        local_root=mini_release,
        query_embedder=lambda text: [1.0, 0.0],
        budgets=api.ResourceBudgets(max_bytes=10_000_000, max_shards=32),
    )
    bm25 = client.query("bm25", query="agency", top_k=2, jurisdiction="OR")
    assert bm25.mode == "bm25"
    assert bm25.fetch_trace
    for hit in bm25.results:
        assert str(hit.get("jurisdiction")).upper() == "OR"

    vector = client.query(
        "vector",
        query="records",
        query_vector=[-0.8, 0.2],
        top_k=3,
        jurisdiction="DC",
        code="DC",
    )
    assert vector.mode == "vector"
    assert vector.fetch_trace
    for hit in vector.results:
        assert str(hit.get("jurisdiction")).upper() == "DC"

    hybrid = client.query(
        "hybrid",
        query="agency",
        query_vector=[1.0, 0.0],
        top_k=2,
        jurisdiction="OR",
        code="ORS",
    )
    assert hybrid.mode == "hybrid"
    assert hybrid.fetch_trace

    neighbors = client.query("neighbors", node_cid="entry-b", limit=4)
    assert neighbors.mode == "neighbors"
    assert neighbors.fetch_trace

    graph = client.query("graph_walk", start_node_cid="entry-b", max_depth=1, max_nodes=4)
    assert graph.mode == "graph_walk"
    assert graph.fetch_trace

    semantic = client.query(
        "semantic-graph-walk",
        start_node_cid="entry-a",
        query="agency",
        query_vector=[1.0, 0.0],
        max_depth=1,
        max_nodes=4,
    )
    assert semantic.mode == "semantic_graph_walk"
    packaged = api.package_query_result(semantic, pin=client.pin, include_trace=True)
    assert packaged["mode"] == "semantic_graph_walk"
    assert packaged["full_index_downloaded"] is False
    assert packaged["redacted_trace"] is True
    assert packaged["pin"]["revision"] == PINNED_REVISION
    assert api.proves_sparse_io(semantic) is True


def test_cli_maps_exactly_to_package_api(
    cli, mini_release: Path, tmp_path: Path, capsys
) -> None:
    cache = tmp_path / "cache"
    rc = cli.main(
        [*_common_cli_args(mini_release, cache), "bm25", "privacy", "--top-k", "3"]
    )
    assert rc == 0
    cli_payload = json.loads(capsys.readouterr().out)

    client = cli.open_query_client(
        revision=PINNED_REVISION,
        repo_id=REPO_ID,
        local_root=mini_release,
        cache_dir=tmp_path / "api-cache",
    )
    assert isinstance(client, StateLawsSparseGraphragClient)
    api_result = client.bm25_search("privacy", top_k=3)
    packaged = cli.package_query_result(api_result, client=client, include_trace=True)
    assert cli_payload["mode"] == "bm25"
    assert api_result.mode == "bm25"
    assert cli_payload["result_count"] == api_result.result_count
    assert [hit.get("entry_cid") for hit in cli_payload["results"]] == [
        hit.get("entry_cid") for hit in api_result.results
    ]
    assert cli_payload["ordered_result_cids"] == packaged["ordered_result_cids"]
    assert packaged["pin"]["revision"] == PINNED_REVISION


def test_deterministic_ordering_and_offline_replay(
    cli, mini_release: Path, tmp_path: Path, capsys
) -> None:
    common = [
        *_common_cli_args(mini_release, tmp_path / "cache-a"),
        "--offline-replay",
        "bm25",
        "foia agency",
        "--top-k",
        "3",
    ]
    assert cli.main(common) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main(
        [
            *_common_cli_args(mini_release, tmp_path / "cache-b"),
            "--offline-replay",
            "bm25",
            "foia agency",
            "--top-k",
            "3",
        ]
    ) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["ordered_result_cids"] == second["ordered_result_cids"]
    assert first["replay_fingerprint"] == second["replay_fingerprint"]
    assert first["replay_fingerprint"] == query_replay_fingerprint(first)

    rc = cli.main(
        [
            *_common_cli_args(mini_release, tmp_path / "cache-c"),
            "--offline-replay",
            "--expected-fingerprint",
            first["replay_fingerprint"],
            "bm25",
            "foia agency",
            "--top-k",
            "3",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    mismatch = cli.main(
        [
            *_common_cli_args(mini_release, tmp_path / "cache-d"),
            "--offline-replay",
            "--expected-fingerprint",
            "0" * 64,
            "bm25",
            "foia agency",
            "--top-k",
            "3",
        ]
    )
    assert mismatch == 1


def test_cache_controls(cli, mini_release: Path, tmp_path: Path, capsys) -> None:
    cache = tmp_path / "explicit-cache"
    rc = cli.main(
        [
            *_common_cli_args(mini_release, cache),
            "--reset-cache",
            "bm25",
            "foia",
            "--top-k",
            "1",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "bm25"
    assert cache.exists()

    rc = cli.main(
        [
            "--local-root",
            str(mini_release),
            "--revision",
            PINNED_REVISION,
            "--no-cache",
            "--json",
            "bm25",
            "foia",
            "--top-k",
            "1",
        ]
    )
    assert rc == 0
    nocache = json.loads(capsys.readouterr().out)
    assert nocache["mode"] == "bm25"

    rc = cli.main(
        [
            "--local-root",
            str(mini_release),
            "--revision",
            PINNED_REVISION,
            "--cache-dir",
            str(cache),
            "--no-cache",
            "bm25",
            "foia",
        ]
    )
    assert rc == 2


def test_package_query_result_strips_trace_when_requested(
    cli, mini_release: Path, tmp_path: Path
) -> None:
    client = cli.open_query_client(
        revision=PINNED_REVISION,
        repo_id=REPO_ID,
        local_root=mini_release,
        cache_dir=tmp_path / "cache",
    )
    result = client.bm25_search("foia", top_k=1)
    stripped = cli.package_query_result(result, client=client, include_trace=False)
    assert "fetch_trace" not in stripped
    assert stripped["full_index_downloaded"] is False
    replayed = cli.package_query_result(
        result, client=client, include_trace=True, offline_replay=True
    )
    assert replayed["offline_replay"] is True
    assert replayed["replay_fingerprint"] == query_replay_fingerprint(result)
    assert replayed["redacted_trace"] is True
