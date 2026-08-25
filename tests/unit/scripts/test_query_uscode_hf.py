"""Unit tests for the US Code HF query CLI (USCIR-028)."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "query_uscode_hf.py"
GUIDE = REPO / "docs" / "guides" / "USCODE_SPARSE_QUERY_CLI.md"


def _load_cli():
    assert SCRIPT.is_file()
    spec = importlib.util.spec_from_file_location("query_uscode_hf_uscir028", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


def test_script_and_guide_exist() -> None:
    assert SCRIPT.is_file()
    assert GUIDE.is_file()
    text = GUIDE.read_text(encoding="utf-8")
    assert "bm25" in text
    assert "semantic-graph-walk" in text


def test_help_exits_zero(cli) -> None:
    assert cli.main(["--help"]) == 0
    for command in cli.SUBCOMMANDS:
        assert cli.main([command, "--help"]) == 0


def test_subcommand_list_is_exact(cli) -> None:
    assert set(cli.SUBCOMMANDS) == {
        "bm25",
        "vector",
        "hybrid",
        "neighbors",
        "graph-walk",
        "semantic-graph-walk",
    }


def test_mutable_revision_rejected_for_live_hub(cli) -> None:
    with pytest.raises(cli.CliError):
        cli._build_resolver(
            argparse_ns(
                repo_id="justicedao/ipfs_uscode",
                revision="main",
                cache_dir=None,
                local_root=None,
            )
        )


def test_secret_argv_rejected(cli) -> None:
    with pytest.raises(cli.CliError):
        cli._reject_secrets_in_argv(["--hf_token=abc123", "bm25", "x"])


def test_offline_bm25_against_mini_release(cli, tmp_path: Path, capsys) -> None:
    # Reuse the sealed mini-release builder from the query unit tests.
    sys.path.insert(0, str(REPO))
    from tests.unit.retrieval.hf_graphrag.test_query import build_mini_release

    release = tmp_path / "release"
    release.mkdir()
    build_mini_release(release)

    rc = cli.main(
        [
            "--local-root",
            str(release),
            "--revision",
            "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8",
            "--fixture-mode",
            "--json",
            "--trace",
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
    rendered = json.dumps(payload)
    assert "HF_TOKEN" not in rendered or os.environ.get("HF_TOKEN") not in rendered


def test_offline_neighbors_and_graph_walk(cli, tmp_path: Path, capsys) -> None:
    sys.path.insert(0, str(REPO))
    from tests.unit.retrieval.hf_graphrag.test_query import build_mini_release

    release = tmp_path / "release"
    release.mkdir()
    build_mini_release(release)
    common = [
        "--local-root",
        str(release),
        "--revision",
        "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8",
        "--fixture-mode",
        "--json",
    ]
    assert cli.main([*common, "neighbors", "node-a", "--limit", "4"]) == 0
    neighbors = json.loads(capsys.readouterr().out)
    assert "results" in neighbors

    assert (
        cli.main(
            [
                *common,
                "graph-walk",
                "node-a",
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
    assert "results" in walk


def argparse_ns(**kwargs):
    return type("NS", (), kwargs)()
