from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import duckdb


def _load_history_index_cli_module():
    module_path = Path(__file__).resolve().parents[2] / "ipfs_datasets_py" / "cli" / "history_index_cli.py"
    spec = importlib.util.spec_from_file_location("history_index_cli_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_history_index(tmp_path: Path) -> Path:
    db_path = tmp_path / "evidence_index.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE documents (
                doc_id VARCHAR,
                relative_path VARCHAR,
                absolute_path VARCHAR,
                status VARCHAR,
                text_length BIGINT,
                chunk_count BIGINT,
                metadata_json VARCHAR
            )
            """
        )
        con.execute(
            """
            CREATE TABLE chunks (
                chunk_id VARCHAR,
                doc_id VARCHAR,
                chunk_index BIGINT,
                text VARCHAR,
                metadata_json VARCHAR
            )
            """
        )
        con.execute(
            """
            CREATE TABLE entities (
                entity_id VARCHAR,
                entity_type VARCHAR,
                name VARCHAR,
                confidence DOUBLE,
                attributes_json VARCHAR,
                raw_json VARCHAR
            )
            """
        )
        con.execute(
            """
            CREATE TABLE relationships (
                relationship_id VARCHAR,
                source_id VARCHAR,
                target_id VARCHAR,
                relation_type VARCHAR,
                confidence DOUBLE,
                attributes_json VARCHAR,
                raw_json VARCHAR
            )
            """
        )
        con.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                "doc:1",
                "email_imports/voice/event.json",
                "/tmp/email_imports/voice/event.json",
                "success",
                100,
                1,
                json.dumps({"source_type": "google_voice"}),
            ],
        )
        con.execute(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?)",
            [
                "doc:1:chunk:0",
                "doc:1",
                0,
                "Tenant requested an inspection notice by text.",
                json.dumps({"source_type": "google_voice"}),
            ],
        )
        con.execute(
            "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?)",
            [
                "entity:tenant",
                "Person",
                "Tenant",
                0.9,
                json.dumps({"channel": "google_voice"}),
                json.dumps({"entity_id": "entity:tenant", "name": "Tenant"}),
            ],
        )
    finally:
        con.close()
    return db_path


def test_history_index_cli_search_duckdb_chunks(tmp_path: Path) -> None:
    module = _load_history_index_cli_module()
    db_path = _build_history_index(tmp_path)

    payload = module.search_duckdb(
        db_path=db_path,
        query="inspection notice",
        table="chunks",
        limit=5,
        source_like="google_voice",
    )

    assert payload["result_count"] == 1
    assert payload["results"][0]["chunk_id"] == "doc:1:chunk:0"


def test_history_index_cli_main_json_output(tmp_path: Path) -> None:
    module = _load_history_index_cli_module()
    db_path = _build_history_index(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output):
        result = module.main(
            ["--index-path", str(db_path), "--table", "entities", "--json", "tenant"]
        )

    assert result == 0
    payload = json.loads(output.getvalue())
    assert payload["result_count"] == 1
    assert payload["results"][0]["entity_id"] == "entity:tenant"


def test_ipfs_datasets_cli_dispatches_history_index(tmp_path: Path, monkeypatch) -> None:
    db_path = _build_history_index(tmp_path)
    module_path = Path(__file__).resolve().parents[2] / "ipfs_datasets_cli.py"
    spec = importlib.util.spec_from_file_location("ipfs_datasets_cli_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            monkeypatch.setattr(
                module.sys,
                "argv",
                ["ipfs-datasets", "history-index", "--index-path", str(db_path), "--json", "inspection"],
            )
            module.main()
        except SystemExit as exc:
            assert exc.code == 0

    payload = json.loads(output.getvalue())
    assert payload["result_count"] == 1
