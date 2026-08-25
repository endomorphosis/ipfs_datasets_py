"""Unit tests for the Federal Register HF query API and CLI (LCR-060).

Acceptance:

* Structured JSON and JSONL modes.
* Immutable repo/revision binding; no mutable-main default.
* Agency / date / document-type filters, budgets, cache controls.
* Explicit offline replay.
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
from ipfs_datasets_py.processors.legal_data.federal_register_sparse_query import (
    FederalRegisterQueryClient,
    query_replay_fingerprint,
    require_immutable_revision,
)

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "query_federal_register_hf.py"
PINNED_REVISION = "720668ae016cc400916dda884c9005e03618edfa"
REPO_ID = "justicedao/ipfs_federal_register"


def _load_cli():
    assert SCRIPT.is_file()
    spec = importlib.util.spec_from_file_location(
        "query_federal_register_hf_lcr060", SCRIPT
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
    from tests.unit.processors.legal_data.test_federal_register_sparse_query import (
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
    assert "FederalRegisterQueryClient" in legal_data_pkg.__all__
    assert "FederalRegisterQueryClient" in legal_data_pkg._LAZY_EXPORTS
    resolved = legal_data_pkg.FederalRegisterQueryClient
    assert resolved is FederalRegisterQueryClient
    assert resolved.__name__ == "FederalRegisterQueryClient"


def test_query_surface_documents_acceptance(cli) -> None:
    surface = cli.query_surface()
    assert surface["task_id"] == "LCR-060"
    assert surface["goal_id"] == "LCR-G120"
    assert surface["program_id"] == "legal-corpora-reindex-v1"
    assert surface["engine_task_id"] == "LCR-059"
    assert surface["mutable_main_default"] is False
    assert surface["offline_replay"] is True
    assert surface["full_index_download"] is False
    assert surface["formats"] == ["json", "jsonl", "text"]
    assert "agency" in surface["filter_fields"]
    assert "date" in surface["filter_fields"]
    assert "document_type" in surface["filter_fields"]
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


def test_default_revision_is_immutable_not_main(cli) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["bm25", "foia"])
    assert args.revision == cli.DEFAULT_REVISION
    assert args.revision.casefold() not in cli.MUTABLE_REFS
    assert args.repo_id == REPO_ID
    assert require_immutable_revision(args.revision) == PINNED_REVISION


def test_cli_import_does_not_contact_network(monkeypatch) -> None:
    def _blocked(*_args, **_kwargs):
        raise AssertionError("network access at import time")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    before = set(sys.modules)
    module = _load_cli()
    added = set(sys.modules) - before
    assert module.TASK_ID == "LCR-060"
    assert module.main(["--help"]) == 0
    for banned in ("sentence_transformers", "transformers", "torch"):
        assert banned not in added


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
        "agency",
        "document-type",
        "revision",
        "max-bytes",
        "cache-dir",
        "offline-replay",
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
            "--agency",
            "EPA",
            "--document-type",
            "rule",
            "--date",
            "2024-01-15",
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
    assert payload["filters"]["agency"] == "EPA"
    assert payload["filters"]["document_type"] == "rule"
    assert payload["pin"]["revision"] == PINNED_REVISION
    assert payload["pin"]["repo_id"] == REPO_ID
    assert payload["pin"]["mutable_rejected"] is True
    assert payload["interface_task_id"] == "LCR-060"
    assert payload["engine_task_id"] == "LCR-059"
    assert payload["limits"]["max_bytes"] == 10_000_000
    assert payload["ordered_result_cids"]
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
                "--agency",
                "EPA",
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
    assert hybrid["filters"]["agency"] == "EPA"
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
    assert isinstance(client, FederalRegisterQueryClient)
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
