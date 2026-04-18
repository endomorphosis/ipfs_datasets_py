import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import US_STATES
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import StateScraperRegistry


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ops"
    / "legal_data"
    / "refresh_state_laws_corpus.py"
)
_SPEC = importlib.util.spec_from_file_location("refresh_state_laws_corpus", _SCRIPT_PATH)
refresh_state_laws_corpus = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(refresh_state_laws_corpus)


def test_jsonld_payload_to_canonical_row_adds_stable_cid():
    payload = {
        "@type": "Legislation",
        "identifier": "Minn. Stat. § 518.17",
        "name": "Best interests of the child",
        "text": "The best interests of the child factors.",
        "sourceUrl": "https://www.revisor.mn.gov/statutes/cite/518.17",
    }

    first = refresh_state_laws_corpus.jsonld_payload_to_canonical_row(payload, state_code="MN")
    second = refresh_state_laws_corpus.jsonld_payload_to_canonical_row(payload, state_code="MN")

    assert first["ipfs_cid"] == second["ipfs_cid"]
    assert first["state_code"] == "MN"
    assert first["identifier"] == "Minn. Stat. § 518.17"
    assert first["source_url"] == "https://www.revisor.mn.gov/statutes/cite/518.17"
    assert json.loads(first["jsonld"])["identifier"] == "Minn. Stat. § 518.17"


def test_build_state_laws_parquet_artifacts_merges_existing_local_rows(tmp_path):
    jsonld_dir = tmp_path / "jsonld"
    parquet_dir = tmp_path / "parquet"
    jsonld_dir.mkdir()
    parquet_dir.mkdir()

    (jsonld_dir / "STATE-MN.jsonld").write_text(
        json.dumps(
            {
                "@type": "Legislation",
                "identifier": "Minn. Stat. § 518.17",
                "name": "Best interests",
                "text": "Refreshed statutory text.",
                "sourceUrl": "https://www.revisor.mn.gov/statutes/cite/518.17",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    existing_path = parquet_dir / "STATE-MN.parquet"
    refresh_state_laws_corpus._write_parquet_rows(
        [
            {
                "ipfs_cid": "legacy-cid",
                "state_code": "MN",
                "source_id": "legacy-source",
                "identifier": "Minn. Stat. § 999.99",
                "name": "Legacy row",
                "text": "Existing row from prior corpus.",
                "source_url": "https://example.test/legacy",
                "jsonld": "{}",
            }
        ],
        existing_path,
    )

    result = refresh_state_laws_corpus.build_state_laws_parquet_artifacts(
        states=["MN"],
        jsonld_dir=jsonld_dir,
        parquet_dir=parquet_dir,
        merge_existing_local=True,
        merge_hf_existing=False,
    )

    rows = pq.read_table(existing_path).to_pylist()
    combined_rows = pq.read_table(parquet_dir / "state_laws_all_states.parquet").to_pylist()

    assert result["combined_row_count"] == 2
    assert len(rows) == 2
    assert len(combined_rows) == 2
    assert {row["identifier"] for row in rows} == {"Minn. Stat. § 999.99", "Minn. Stat. § 518.17"}
    assert Path(result["manifest_path"]).exists()


def test_refresh_state_laws_corpus_dry_run_plans_all_states(tmp_path):
    args = argparse.Namespace(
        states="all",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=False,
        max_statutes=0,
        rate_limit_delay=0.0,
        parallel_workers=1,
        per_state_retry_attempts=0,
        per_state_timeout_seconds=1.0,
        strict_full_text=False,
        min_full_text_chars=300,
        no_hydrate_statute_text=False,
        allow_justia_fallback=False,
        no_merge_existing_local=False,
        merge_hf_existing=False,
        publish_to_hf=False,
        allow_incomplete_publish=False,
        repo_id="justicedao/ipfs_state_laws",
        hf_token="",
        create_repo=False,
        verify=False,
        commit_message="test",
        dry_run=True,
        json=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "dry_run"
    assert result["plan"]["state_count"] == 50
    assert result["plan"]["states"][0] == "AL"
    assert result["plan"]["states"][-1] == "WY"


def test_refresh_state_laws_corpus_refuses_incomplete_publish(tmp_path):
    args = argparse.Namespace(
        states="MN",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=False,
        max_statutes=0,
        rate_limit_delay=0.0,
        parallel_workers=1,
        per_state_retry_attempts=0,
        per_state_timeout_seconds=1.0,
        strict_full_text=False,
        min_full_text_chars=300,
        no_hydrate_statute_text=False,
        allow_justia_fallback=False,
        no_merge_existing_local=False,
        merge_hf_existing=False,
        publish_to_hf=True,
        allow_incomplete_publish=False,
        repo_id="justicedao/ipfs_state_laws",
        hf_token="",
        create_repo=False,
        verify=False,
        commit_message="test",
        dry_run=False,
        json=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "error"
    assert result["publish"] is None
    assert result["build_gap_states"] == ["MN"]


def test_all_state_jurisdictions_have_registered_scrapers():
    registered = set(StateScraperRegistry.get_all_registered_states())

    assert set(US_STATES) - registered == set()
    assert len(registered) == len(US_STATES)
