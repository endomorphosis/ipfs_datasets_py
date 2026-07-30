"""
CLI tests for GraphService-backed graph commands (KGP-018).

Strict exit codes and JSON envelopes — no permissive success-or-failure checks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_MODULE = "ipfs_datasets_py.ipfs_datasets_cli"


def _env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def run_cli(
    args: Sequence[str],
    *,
    catalog: Optional[Path] = None,
    store: Optional[Path] = None,
    input_text: Optional[str] = None,
    timeout: float = 60,
) -> subprocess.CompletedProcess:
    cmd: List[str] = [sys.executable, "-m", _CLI_MODULE, *args]
    # Inject catalog/store if provided and not already present.
    joined = " ".join(args)
    if catalog is not None and "--catalog" not in joined:
        cmd.extend(["--catalog", str(catalog)])
    if store is not None and "--store" not in joined:
        cmd.extend(["--store", str(store)])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(),
        cwd=str(_REPO_ROOT),
        input=input_text,
    )


def parse_json_stdout(proc: subprocess.CompletedProcess) -> Dict[str, Any]:
    assert proc.stdout.strip(), f"empty stdout; stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


@pytest.fixture
def kg_paths(tmp_path: Path):
    return tmp_path / "kg_catalog.sqlite", tmp_path / "kg_payloads"


class TestGraphHelp:
    def test_graph_help(self) -> None:
        result = run_cli(["graph", "--help"])
        assert result.returncode == 0
        text = (result.stdout + result.stderr).lower()
        for name in (
            "create",
            "list",
            "describe",
            "write",
            "query",
            "transaction",
            "branch",
            "delete",
            "import",
            "export",
            "verify",
        ):
            assert name in text
        assert "graphservice" in text or "kg://" in text or "tenant" in text


class TestGraphCreateListDescribe:
    def test_graph_create_command(self, kg_paths) -> None:
        catalog, store = kg_paths
        create = run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "skills",
                "--branch",
                "main",
                "--idempotency-key",
                "cli-create-1",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert create.returncode == 0, create.stdout + create.stderr
        payload = parse_json_stdout(create)
        assert payload["status"] == "success"
        assert payload["operation"] == "create"
        assert payload["result"]["graph_id"] == "skills"
        assert payload["result"]["revision"]
        assert payload["target"]["uri"] == "kg://acme/skills/branches/main"
        # JSON-safe
        json.dumps(payload, allow_nan=False)

        listed = run_cli(
            [
                "graph",
                "list",
                "--tenant",
                "acme",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert listed.returncode == 0, listed.stdout + listed.stderr
        lp = parse_json_stdout(listed)
        assert lp["status"] == "success"
        assert any(g["graph_id"] == "skills" for g in lp["result"]["graphs"])

        described = run_cli(
            [
                "graph",
                "describe",
                "--tenant",
                "acme",
                "--graph",
                "skills",
                "--branch",
                "main",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert described.returncode == 0, described.stdout + described.stderr
        dp = parse_json_stdout(described)
        assert dp["status"] == "success"
        assert dp["result"]["uri"] == "kg://acme/skills"
        assert dp["result"]["head_revision"]

    def test_create_missing_catalog_is_usage(self) -> None:
        # No --catalog and no env → usage exit 2
        env = _env()
        env.pop("IPFS_DATASETS_KG_CATALOG", None)
        env.pop("IPFS_DATASETS_KG_STORE", None)
        result = subprocess.run(
            [
                sys.executable,
                "-m", _CLI_MODULE,
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "g1",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 2
        assert "catalog" in (result.stderr + result.stdout).lower()

    def test_create_missing_tenant_is_usage(self, kg_paths) -> None:
        catalog, store = kg_paths
        result = run_cli(
            ["graph", "create", "--graph", "g1", "--format", "json"],
            catalog=catalog,
            store=store,
        )
        assert result.returncode == 2


class TestGraphWriteQuery:
    def test_graph_query_command(self, kg_paths) -> None:
        catalog, store = kg_paths
        assert (
            run_cli(
                [
                    "graph",
                    "create",
                    "--target",
                    "kg://acme/g1/branches/main",
                    "--idempotency-key",
                    "c1",
                    "--format",
                    "json",
                ],
                catalog=catalog,
                store=store,
            ).returncode
            == 0
        )

        entities = json.dumps(
            [{"id": "e1", "type": "Person", "name": "Ada"}]
        )
        write = run_cli(
            [
                "graph",
                "write",
                "--tenant",
                "acme",
                "--graph",
                "g1",
                "--branch",
                "main",
                "--idempotency-key",
                "w1",
                "--entities",
                entities,
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert write.returncode == 0, write.stdout + write.stderr
        wp = parse_json_stdout(write)
        assert wp["status"] == "success"
        assert wp["operation"] == "write"
        assert wp["result"]["mutation_count"] == 1
        assert wp["result"]["revision"]
        rev = wp["result"]["revision"]

        query = run_cli(
            [
                "graph",
                "query",
                "--tenant",
                "acme",
                "--graph",
                "g1",
                "--branch",
                "main",
                "--language",
                "scan",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert query.returncode == 0, query.stdout + query.stderr
        qp = parse_json_stdout(query)
        assert qp["status"] == "success"
        assert qp["operation"] == "query"
        assert qp["result"]["row_count"] == 1
        assert qp["result"]["revision"] == rev
        assert qp["result"]["rows"][0][2] == "Ada"
        json.dumps(qp, allow_nan=False)

    def test_graph_add_entity_command(self, kg_paths) -> None:
        catalog, store = kg_paths
        run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "stdin",
                "--idempotency-key",
                "c-stdin",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        payload = json.dumps(
            {"entities": [{"id": "n1", "type": "T", "name": "from-stdin"}]}
        )
        write = run_cli(
            [
                "graph",
                "write",
                "--tenant",
                "acme",
                "--graph",
                "stdin",
                "--branch",
                "main",
                "--idempotency-key",
                "w-stdin",
                "--stdin",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
            input_text=payload,
        )
        assert write.returncode == 0, write.stdout + write.stderr
        assert parse_json_stdout(write)["result"]["mutation_count"] == 1

    def test_write_requires_idempotency_key(self, kg_paths) -> None:
        catalog, store = kg_paths
        run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "noidem",
                "--idempotency-key",
                "c",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        result = run_cli(
            [
                "graph",
                "write",
                "--tenant",
                "acme",
                "--graph",
                "noidem",
                "--branch",
                "main",
                "--entities",
                '[{"id":"x","type":"T","name":"n"}]',
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert result.returncode == 2


class TestGraphTransactionBranchDelete:
    def test_transaction_begin_stage_commit(self, kg_paths) -> None:
        catalog, store = kg_paths
        run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "txg",
                "--idempotency-key",
                "tx-c",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        begin = run_cli(
            [
                "graph",
                "transaction",
                "begin",
                "--tenant",
                "acme",
                "--graph",
                "txg",
                "--branch",
                "main",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert begin.returncode == 0, begin.stdout + begin.stderr
        bp = parse_json_stdout(begin)
        assert bp["status"] == "success"
        tx_id = bp["result"]["transaction_id"]
        assert tx_id

        stage = run_cli(
            [
                "graph",
                "write",
                "--tenant",
                "acme",
                "--graph",
                "txg",
                "--branch",
                "main",
                "--tx-id",
                tx_id,
                "--idempotency-key",
                "tx-stage",
                "--entities",
                '[{"id":"t1","type":"Thing","name":"staged"}]',
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert stage.returncode == 0, stage.stdout + stage.stderr
        assert parse_json_stdout(stage)["result"]["staged"] is True

        commit = run_cli(
            [
                "graph",
                "transaction",
                "commit",
                "--tenant",
                "acme",
                "--graph",
                "txg",
                "--branch",
                "main",
                "--tx-id",
                tx_id,
                "--idempotency-key",
                "tx-commit-1",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert commit.returncode == 0, commit.stdout + commit.stderr
        assert parse_json_stdout(commit)["status"] == "success"

        q = run_cli(
            [
                "graph",
                "query",
                "--tenant",
                "acme",
                "--graph",
                "txg",
                "--branch",
                "main",
                "--language",
                "scan",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert q.returncode == 0
        assert parse_json_stdout(q)["result"]["row_count"] == 1

    def test_transaction_rollback(self, kg_paths) -> None:
        catalog, store = kg_paths
        run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "txrb",
                "--idempotency-key",
                "txrb-c",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        begin = run_cli(
            [
                "graph",
                "tx-begin",
                "--tenant",
                "acme",
                "--graph",
                "txrb",
                "--branch",
                "main",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert begin.returncode == 0
        tx_id = parse_json_stdout(begin)["result"]["transaction_id"]
        run_cli(
            [
                "graph",
                "write",
                "--tenant",
                "acme",
                "--graph",
                "txrb",
                "--branch",
                "main",
                "--tx-id",
                tx_id,
                "--idempotency-key",
                "stage-rb",
                "--entities",
                '[{"id":"x","type":"T","name":"nope"}]',
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        rb = run_cli(
            [
                "graph",
                "transaction",
                "rollback",
                "--tenant",
                "acme",
                "--graph",
                "txrb",
                "--branch",
                "main",
                "--tx-id",
                tx_id,
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert rb.returncode == 0, rb.stdout + rb.stderr
        q = run_cli(
            [
                "graph",
                "query",
                "--tenant",
                "acme",
                "--graph",
                "txrb",
                "--branch",
                "main",
                "--language",
                "scan",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert parse_json_stdout(q)["result"]["row_count"] == 0

    def test_branch_and_delete(self, kg_paths) -> None:
        catalog, store = kg_paths
        run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "br",
                "--idempotency-key",
                "br-c",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        run_cli(
            [
                "graph",
                "write",
                "--tenant",
                "acme",
                "--graph",
                "br",
                "--branch",
                "main",
                "--idempotency-key",
                "br-w",
                "--entities",
                '[{"id":"e","type":"T","name":"n"}]',
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        branch = run_cli(
            [
                "graph",
                "branch",
                "--tenant",
                "acme",
                "--graph",
                "br",
                "--branch",
                "dev",
                "--from-branch",
                "main",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert branch.returncode == 0, branch.stdout + branch.stderr
        bp = parse_json_stdout(branch)
        assert bp["status"] == "success"
        assert bp["result"]["branch"] == "dev"

        delete = run_cli(
            [
                "graph",
                "delete",
                "--tenant",
                "acme",
                "--graph",
                "br",
                "--branch",
                "dev",
                "--reason",
                "test",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert delete.returncode == 0, delete.stdout + delete.stderr
        assert parse_json_stdout(delete)["status"] == "success"


class TestGraphImportExportVerify:
    def test_import_export_verify_roundtrip(self, kg_paths, tmp_path: Path) -> None:
        catalog, store = kg_paths
        import_payload = {
            "entities": [
                {"id": "i1", "type": "Person", "name": "Import"},
                {"id": "i2", "type": "Person", "name": "Two"},
            ],
            "relationships": [
                {"source": "i1", "target": "i2", "type": "KNOWS"},
            ],
        }
        imp = run_cli(
            [
                "graph",
                "import",
                "--tenant",
                "acme",
                "--graph",
                "imp",
                "--branch",
                "main",
                "--idempotency-key",
                "imp-1",
                "--format",
                "json",
                "--stdin",
            ],
            catalog=catalog,
            store=store,
            input_text=json.dumps(import_payload),
        )
        assert imp.returncode == 0, imp.stdout + imp.stderr
        ip = parse_json_stdout(imp)
        assert ip["status"] == "success"
        assert ip["result"]["mutation_count"] >= 1

        export_path = tmp_path / "export.json"
        exp = run_cli(
            [
                "graph",
                "export",
                "--tenant",
                "acme",
                "--graph",
                "imp",
                "--branch",
                "main",
                "--output",
                str(export_path),
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert exp.returncode == 0, exp.stdout + exp.stderr
        assert export_path.is_file()
        exported = json.loads(export_path.read_text(encoding="utf-8"))
        assert exported["entity_count"] == 2
        assert len(exported["entities"]) == 2
        assert exported.get("checksum")

        verify = run_cli(
            [
                "graph",
                "verify",
                "--tenant",
                "acme",
                "--graph",
                "imp",
                "--branch",
                "main",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert verify.returncode == 0, verify.stdout + verify.stderr
        vp = parse_json_stdout(verify)
        assert vp["status"] == "success"
        assert vp["result"]["ok"] is True
        assert vp["result"]["snapshot_present"] is True
        assert vp["result"]["entity_count"] == 2


class TestIndependentProcessPersistence:
    def test_second_process_reopens_committed_graph(self, kg_paths) -> None:
        catalog, store = kg_paths
        w = run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "mp",
                "--graph",
                "g1",
                "--idempotency-key",
                "mp-c",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert w.returncode == 0
        write = run_cli(
            [
                "graph",
                "write",
                "--tenant",
                "mp",
                "--graph",
                "g1",
                "--branch",
                "main",
                "--idempotency-key",
                "mp-w",
                "--entities",
                '[{"id":"n1","type":"T","name":"proc"}]',
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert write.returncode == 0
        rev = parse_json_stdout(write)["result"]["revision"]

        # Brand-new process (new subprocess) reopens via same paths.
        reader = run_cli(
            [
                "graph",
                "query",
                "--tenant",
                "mp",
                "--graph",
                "g1",
                "--branch",
                "main",
                "--language",
                "scan",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert reader.returncode == 0, reader.stdout + reader.stderr
        rp = parse_json_stdout(reader)
        assert rp["result"]["row_count"] == 1
        assert rp["result"]["rows"][0][2] == "proc"
        assert rp["result"]["revision"] == rev

        opened = run_cli(
            [
                "graph",
                "open",
                "--tenant",
                "mp",
                "--graph",
                "g1",
                "--branch",
                "main",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert opened.returncode == 0
        assert parse_json_stdout(opened)["result"]["revision"] == rev


class TestTypedErrorsAndExitCodes:
    def test_not_found_describe_exit_1_with_typed_error(self, kg_paths) -> None:
        catalog, store = kg_paths
        result = run_cli(
            [
                "graph",
                "describe",
                "--tenant",
                "acme",
                "--graph",
                "missing",
                "--format",
                "json",
            ],
            catalog=catalog,
            store=store,
        )
        assert result.returncode == 1
        payload = parse_json_stdout(result)
        assert payload["status"] == "error"
        assert payload["error"]["code"] in {
            "NOT_FOUND",
            "INVALID_TARGET",
            "INVALID_REQUEST",
        }
        assert isinstance(payload["error"]["retryable"], bool)
        json.dumps(payload, allow_nan=False)

    def test_unknown_subcommand_exit_2(self, kg_paths) -> None:
        catalog, store = kg_paths
        result = run_cli(
            ["graph", "not-a-real-command", "--format", "json"],
            catalog=catalog,
            store=store,
        )
        assert result.returncode == 2

    def test_table_format_success(self, kg_paths) -> None:
        catalog, store = kg_paths
        result = run_cli(
            [
                "graph",
                "create",
                "--tenant",
                "acme",
                "--graph",
                "tableg",
                "--idempotency-key",
                "tbl",
                "--format",
                "table",
            ],
            catalog=catalog,
            store=store,
        )
        assert result.returncode == 0
        assert "status: success" in result.stdout
        assert "operation: create" in result.stdout


class TestCLIRegression:
    def test_help_command(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", _CLI_MODULE, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_env(),
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0
        text = (result.stdout + result.stderr).lower()
        assert "usage" in text or "graph" in text
