import importlib.util
import json
from pathlib import Path

import pyarrow.parquet as pq


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ops"
    / "legal_data"
    / "merge_state_admin_recovered_rows.py"
)
_SPEC = importlib.util.spec_from_file_location("merge_state_admin_recovered_rows", _SCRIPT_PATH)
merge_state_admin_recovered_rows = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(merge_state_admin_recovered_rows)


def _write_recovered_artifact(root: Path, state: str = "NY") -> Path:
    cycle_dir = root / "recovered_rows" / "cycle_0001"
    cycle_dir.mkdir(parents=True)
    jsonl_path = cycle_dir / "state_admin_rules_statutes.jsonl"
    row = {
        "state_code": state,
        "section_number": "A1",
        "title": "Unofficial New York Codes, Rules and Regulations",
        "full_text": "Recovered administrative rule text.",
        "source_url": "https://govt.westlaw.com/nycrr/Document/I9a267131212611e1b7120000845b8d3e",
        "method_used": "beautifulsoup",
        "recovered_by": "state_laws_agentic_daemon",
        "structured_data": {"@type": "Legislation", "identifier": "A1"},
    }
    jsonl_path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    manifest_path = cycle_dir / "state_admin_rules_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "status": "success",
                "row_count": 2,
                "statutes_jsonl_path": str(jsonl_path),
                "target_hf_dataset_id": "justicedao/ipfs_state_admin_rules",
                "target_parquet_paths_by_state": {
                    state: f"US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}.parquet"
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_recovered_admin_row_to_canonical_row_adds_stable_cid():
    row = {
        "state_code": "NY",
        "section_number": "A1",
        "title": "Document title",
        "full_text": "Recovered rule text",
        "source_url": "https://example.test/rule",
    }

    first = merge_state_admin_recovered_rows.recovered_admin_row_to_canonical_row(row)
    second = merge_state_admin_recovered_rows.recovered_admin_row_to_canonical_row(row)

    assert first["ipfs_cid"] == second["ipfs_cid"]
    assert first["state_code"] == "NY"
    assert first["identifier"] == "A1"
    assert first["name"] == "Document title"
    assert first["text"] == "Recovered rule text"
    assert first["source_url"] == "https://example.test/rule"
    assert first["legislation_type"] == "AdministrativeRule"


def test_build_state_admin_recovered_parquets_from_daemon_manifest(tmp_path):
    daemon_root = tmp_path / "daemon"
    _write_recovered_artifact(daemon_root, state="NY")
    output_root = tmp_path / "upload"
    parquet_dir = output_root / "US_ADMINISTRATIVE_RULES" / "parsed" / "parquet" / "state_admin_rules_cid"

    result = merge_state_admin_recovered_rows.build_state_admin_recovered_parquet_artifacts(
        input_paths=[daemon_root],
        parquet_dir=parquet_dir,
        merge_existing_local=True,
        merge_hf_existing=False,
    )

    state_path = parquet_dir / "STATE-NY.parquet"
    combined_path = parquet_dir / "state_admin_rules_all_states.parquet"
    rows = pq.read_table(state_path).to_pylist()
    combined_rows = pq.read_table(combined_path).to_pylist()

    assert result["status"] == "success"
    assert result["recovered_row_count"] == 2
    assert result["combined_row_count"] == 1
    assert result["state_reports"][0]["deduplicated_recovered_row_count"] == 1
    assert rows[0]["state_code"] == "NY"
    assert rows[0]["identifier"] == "A1"
    assert rows[0]["source_url"].startswith("https://govt.westlaw.com/nycrr/Document/")
    assert len(combined_rows) == 1
    assert Path(result["manifest_path"]).exists()


def test_build_state_admin_recovered_parquets_merges_existing_local_rows(tmp_path):
    daemon_root = tmp_path / "daemon"
    _write_recovered_artifact(daemon_root, state="CT")
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    existing_path = parquet_dir / "STATE-CT.parquet"
    merge_state_admin_recovered_rows._write_parquet_rows(
        [
            {
                "ipfs_cid": "legacy-cid",
                "state_code": "CT",
                "source_id": "legacy-rule",
                "identifier": "Sec. 1",
                "name": "Legacy Connecticut rule",
                "text": "Existing rule text.",
                "source_url": "https://example.test/ct/legacy",
            }
        ],
        existing_path,
    )

    result = merge_state_admin_recovered_rows.build_state_admin_recovered_parquet_artifacts(
        input_paths=[daemon_root],
        parquet_dir=parquet_dir,
        merge_existing_local=True,
        merge_hf_existing=False,
    )

    rows = pq.read_table(existing_path).to_pylist()

    assert result["combined_row_count"] == 2
    assert result["state_reports"][0]["existing_row_count"] == 1
    assert {row["identifier"] for row in rows} == {"Sec. 1", "A1"}
