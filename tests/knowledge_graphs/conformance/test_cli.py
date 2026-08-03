"""CLI surface conformance against the Python Client API (KGP-018).

Shared lifecycle vectors must yield the same status, result fields, and typed
error codes whether invoked via ``Client`` or
``python -m ipfs_datasets_py.ipfs_datasets_cli graph …``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CLI_MODULE = "ipfs_datasets_py.ipfs_datasets_cli"


def _env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def _paths(tmp_path: Path):
    return tmp_path / "kg_catalog.sqlite", tmp_path / "kg_payloads"


def run_graph(
    args: Sequence[str],
    *,
    catalog: Path,
    store: Path,
    input_text: Optional[str] = None,
    timeout: float = 60,
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-m", _CLI_MODULE,
        "graph",
        *args,
        "--catalog",
        str(catalog),
        "--store",
        str(store),
        "--format",
        "json",
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(),
        cwd=str(_REPO_ROOT),
        input=input_text,
    )


def cli_json(
    args: Sequence[str],
    *,
    catalog: Path,
    store: Path,
    input_text: Optional[str] = None,
) -> Dict[str, Any]:
    proc = run_graph(args, catalog=catalog, store=store, input_text=input_text)
    assert proc.returncode in (0, 1), proc.stdout + "\n" + proc.stderr
    assert proc.stdout.strip(), proc.stderr
    payload = json.loads(proc.stdout)
    return {"returncode": proc.returncode, "payload": payload}


# ---------------------------------------------------------------------------
# Parity: create / write / query / describe / list / errors
# ---------------------------------------------------------------------------


class TestCliPythonParity:
    def test_create_write_query_describe_match_python(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog, store = _paths(tmp_path)
        target = GraphTarget(tenant="acme", graph_id="parity", branch="main")

        with Client.open(catalog, storage_path=store) as client:
            py_create = client.create(target, idempotency_key="parity-create")
            assert py_create.ok, py_create.to_json_dict()
            py_write = client.write(
                target,
                idempotency_key="parity-write",
                params={
                    "entities": [{"id": "e1", "type": "Person", "name": "Ada"}],
                },
            )
            assert py_write.ok, py_write.to_json_dict()
            py_query = client.query(target, params={"language": "scan"})
            assert py_query.ok
            py_desc = client.describe(target)
            assert py_desc.ok
            py_list = client.list(GraphTarget(tenant="acme", graph_id="list"))
            assert py_list.ok

        # Fresh CLI process against the same durable paths.
        # Create would ALREADY_EXIST or succeed idempotently — use describe/query/list.
        cli_desc = cli_json(
            ["describe", "--tenant", "acme", "--graph", "parity", "--branch", "main"],
            catalog=catalog,
            store=store,
        )
        assert cli_desc["returncode"] == 0
        assert cli_desc["payload"]["status"] == "success"
        assert (
            cli_desc["payload"]["result"]["head_revision"]
            == py_desc.result["head_revision"]
        )
        assert cli_desc["payload"]["result"]["uri"] == py_desc.result["uri"]

        cli_query = cli_json(
            [
                "query",
                "--tenant",
                "acme",
                "--graph",
                "parity",
                "--branch",
                "main",
                "--language",
                "scan",
            ],
            catalog=catalog,
            store=store,
        )
        assert cli_query["returncode"] == 0
        cq = cli_query["payload"]["result"]
        pq = py_query.result
        assert cq["row_count"] == pq["row_count"] == 1
        assert cq["rows"][0][2] == pq["rows"][0][2] == "Ada"
        assert cq["revision"] == pq["revision"] == py_write.result["revision"]
        assert cq["columns"] == pq["columns"]
        assert cq["schema"] == pq["schema"]

        cli_list = cli_json(
            ["list", "--tenant", "acme"],
            catalog=catalog,
            store=store,
        )
        assert cli_list["returncode"] == 0
        cli_ids = {g["graph_id"] for g in cli_list["payload"]["result"]["graphs"]}
        py_ids = {g["graph_id"] for g in py_list.result["graphs"]}
        assert "parity" in cli_ids
        assert cli_ids == py_ids

    def test_cli_create_write_matches_python_fields(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog, store = _paths(tmp_path)

        # CLI creates and writes.
        created = cli_json(
            [
                "create",
                "--tenant",
                "acme",
                "--graph",
                "cli-first",
                "--branch",
                "main",
                "--idempotency-key",
                "cli-c1",
            ],
            catalog=catalog,
            store=store,
        )
        assert created["returncode"] == 0
        assert created["payload"]["status"] == "success"
        assert created["payload"]["operation"] == "create"
        assert created["payload"]["result"]["graph_id"] == "cli-first"

        written = cli_json(
            [
                "write",
                "--target",
                "kg://acme/cli-first/branches/main",
                "--idempotency-key",
                "cli-w1",
                "--entities",
                json.dumps([{"id": "n1", "type": "T", "name": "cli"}]),
            ],
            catalog=catalog,
            store=store,
        )
        assert written["returncode"] == 0
        rev = written["payload"]["result"]["revision"]

        # Python reopens and sees the same revision + rows.
        with Client.open(catalog, storage_path=store) as client:
            t = GraphTarget(tenant="acme", graph_id="cli-first", branch="main")
            desc = client.describe(t)
            assert desc.ok
            assert desc.result["head_revision"] == rev
            q = client.query(t, params={"language": "scan"})
            assert q.ok
            assert q.result["row_count"] == 1
            assert q.result["rows"][0][2] == "cli"
            assert q.result["revision"] == rev

    def test_not_found_error_code_matches_python(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog, store = _paths(tmp_path)
        with Client.open(catalog, storage_path=store) as client:
            py = client.describe(
                GraphTarget(tenant="acme", graph_id="missing", branch="main")
            )
            assert not py.ok
            py_code = py.error.code

        cli = cli_json(
            ["describe", "--tenant", "acme", "--graph", "missing", "--branch", "main"],
            catalog=catalog,
            store=store,
        )
        assert cli["returncode"] == 1
        assert cli["payload"]["status"] == "error"
        assert cli["payload"]["error"]["code"] == py_code
        assert cli["payload"]["error"]["retryable"] == py.error.retryable

    def test_invalid_target_usage_or_typed_error(self, tmp_path: Path) -> None:
        catalog, store = _paths(tmp_path)
        # Empty tenant slug is invalid.
        proc = run_graph(
            [
                "create",
                "--tenant",
                "",
                "--graph",
                "x",
                "--idempotency-key",
                "bad",
            ],
            catalog=catalog,
            store=store,
        )
        # Usage (2) or typed INVALID_TARGET (1) are both acceptable for empty tenant;
        # never success.
        assert proc.returncode in (1, 2)
        if proc.returncode == 1 and proc.stdout.strip():
            payload = json.loads(proc.stdout)
            assert payload["status"] == "error"
            assert payload["error"]["code"] in {
                "INVALID_TARGET",
                "INVALID_REQUEST",
            }


class TestCliTransactionParity:
    def test_transaction_commit_visible_to_python(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.knowledge_graphs import Client, GraphTarget

        catalog, store = _paths(tmp_path)
        # Seed graph via Python
        with Client.open(catalog, storage_path=store) as client:
            t = GraphTarget(tenant="acme", graph_id="txparity", branch="main")
            assert client.create(t, idempotency_key="txp-c").ok

        begin = cli_json(
            [
                "transaction",
                "begin",
                "--tenant",
                "acme",
                "--graph",
                "txparity",
                "--branch",
                "main",
            ],
            catalog=catalog,
            store=store,
        )
        assert begin["returncode"] == 0
        tx_id = begin["payload"]["result"]["transaction_id"]

        stage = cli_json(
            [
                "write",
                "--tenant",
                "acme",
                "--graph",
                "txparity",
                "--branch",
                "main",
                "--tx-id",
                tx_id,
                "--idempotency-key",
                "txp-stage",
                "--entities",
                json.dumps([{"id": "tx1", "type": "Thing", "name": "via-cli"}]),
            ],
            catalog=catalog,
            store=store,
        )
        assert stage["returncode"] == 0
        assert stage["payload"]["result"]["staged"] is True

        commit = cli_json(
            [
                "transaction",
                "commit",
                "--tenant",
                "acme",
                "--graph",
                "txparity",
                "--branch",
                "main",
                "--tx-id",
                tx_id,
                "--idempotency-key",
                "txp-commit",
            ],
            catalog=catalog,
            store=store,
        )
        assert commit["returncode"] == 0, commit

        with Client.open(catalog, storage_path=store) as client:
            t = GraphTarget(tenant="acme", graph_id="txparity", branch="main")
            q = client.query(t, params={"language": "scan"})
            assert q.ok
            assert q.result["row_count"] == 1
            assert q.result["rows"][0][2] == "via-cli"


class TestCliImportExportVerify:
    def test_import_export_verify_subprocess_isolation(self, tmp_path: Path) -> None:
        catalog, store = _paths(tmp_path)
        payload = {
            "entities": [{"id": "a", "type": "P", "name": "A"}],
            "relationships": [],
        }
        imp = cli_json(
            [
                "import",
                "--tenant",
                "acme",
                "--graph",
                "io",
                "--branch",
                "main",
                "--idempotency-key",
                "io-imp",
                "--stdin",
            ],
            catalog=catalog,
            store=store,
            input_text=json.dumps(payload),
        )
        assert imp["returncode"] == 0
        assert imp["payload"]["status"] == "success"

        out = tmp_path / "out.json"
        exp = cli_json(
            [
                "export",
                "--tenant",
                "acme",
                "--graph",
                "io",
                "--branch",
                "main",
                "--output",
                str(out),
            ],
            catalog=catalog,
            store=store,
        )
        assert exp["returncode"] == 0
        exported = json.loads(out.read_text(encoding="utf-8"))
        assert exported["entity_count"] == 1
        assert exported["entities"][0]["name"] == "A"

        ver = cli_json(
            ["verify", "--tenant", "acme", "--graph", "io", "--branch", "main"],
            catalog=catalog,
            store=store,
        )
        assert ver["returncode"] == 0
        assert ver["payload"]["result"]["ok"] is True
        assert ver["payload"]["result"]["entity_count"] == 1


class TestCliStreamingAndTable:
    def test_stream_query_ndjson(self, tmp_path: Path) -> None:
        catalog, store = _paths(tmp_path)
        assert (
            cli_json(
                [
                    "create",
                    "--tenant",
                    "acme",
                    "--graph",
                    "stream",
                    "--idempotency-key",
                    "s-c",
                ],
                catalog=catalog,
                store=store,
            )["returncode"]
            == 0
        )
        entities = [
            {"id": f"e{i}", "type": "P", "name": f"n{i}"} for i in range(5)
        ]
        assert (
            cli_json(
                [
                    "write",
                    "--tenant",
                    "acme",
                    "--graph",
                    "stream",
                    "--branch",
                    "main",
                    "--idempotency-key",
                    "s-w",
                    "--entities",
                    json.dumps(entities),
                ],
                catalog=catalog,
                store=store,
            )["returncode"]
            == 0
        )

        proc = run_graph(
            [
                "query",
                "--tenant",
                "acme",
                "--graph",
                "stream",
                "--branch",
                "main",
                "--language",
                "scan",
                "--stream",
                "--page-size",
                "2",
            ],
            catalog=catalog,
            store=store,
        )
        # run_graph always appends --format json
        assert proc.returncode == 0, proc.stdout + proc.stderr
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        pages = [json.loads(ln) for ln in lines]
        assert len(pages) == 3
        assert pages[-1]["exhausted"] is True
        total = sum(p["row_count"] for p in pages)
        assert total == 5

    def test_table_output_not_json(self, tmp_path: Path) -> None:
        catalog, store = _paths(tmp_path)
        proc = subprocess.run(
            [
                sys.executable,
                "-m", _CLI_MODULE,
                "graph",
                "create",
                "--catalog",
                str(catalog),
                "--store",
                str(store),
                "--tenant",
                "acme",
                "--graph",
                "tbl",
                "--idempotency-key",
                "t1",
                "--format",
                "table",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=_env(),
            cwd=str(_REPO_ROOT),
        )
        assert proc.returncode == 0
        assert "status: success" in proc.stdout
        with pytest.raises(json.JSONDecodeError):
            json.loads(proc.stdout)
