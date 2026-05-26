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
        max_statutes=1,
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


def test_refresh_state_laws_corpus_skips_final_publish_when_incomplete(tmp_path):
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

    assert result["status"] == "partial_success"
    assert result["publish"]["status"] == "skipped"
    assert result["publish"]["reason"] == "final_combined_publish_waits_for_complete_corpus"
    assert result["build_gap_states"] == ["MN"]


def test_refresh_state_laws_corpus_uses_shared_hf_token_resolver(tmp_path, monkeypatch):
    observed = {}

    def _fake_build_state_laws_parquet_artifacts(**kwargs):
        observed["build_token"] = kwargs.get("token")
        return {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 1,
        }

    def _fake_publish_parquet_dir(**kwargs):
        observed["publish_token"] = kwargs.get("token")
        return {"upload_commit": "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/keyring"}

    monkeypatch.setattr(refresh_state_laws_corpus, "_resolve_hf_token", lambda token=None: "keyring-refresh-token")
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        _fake_build_state_laws_parquet_artifacts,
    )
    monkeypatch.setattr(refresh_state_laws_corpus, "_publish_parquet_dir", _fake_publish_parquet_dir)

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
        merge_hf_existing=True,
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

    assert result["status"] == "success"
    assert observed == {
        "build_token": "keyring-refresh-token",
        "publish_token": "keyring-refresh-token",
    }


def test_refresh_state_laws_corpus_sets_full_corpus_env_for_uncapped_scrape(tmp_path, monkeypatch):
    observed = {}

    async def _fake_scrape_state_laws(**kwargs):
        observed["full_corpus_env"] = __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS")
        observed["max_statutes"] = kwargs.get("max_statutes")
        return {"status": "success", "data": [], "metadata": {"coverage_summary": {}}}

    def _fake_audit(*, states):
        observed["audit_states"] = list(states)
        return {"status": "pass", "states_checked": len(states), "missing_states": [], "error_count": 0, "warning_count": 0, "findings": []}

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    monkeypatch.setattr(refresh_state_laws_corpus, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(refresh_state_laws_corpus, "_run_full_corpus_guard_audit", _fake_audit)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 0,
        },
    )

    args = argparse.Namespace(
        states="MN",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=True,
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
        dry_run=False,
        json=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "success"
    assert observed == {"audit_states": ["MN"], "full_corpus_env": "1", "max_statutes": None}
    assert result["full_corpus_guard_audit"]["status"] == "pass"
    assert __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS") is None


def test_refresh_state_laws_corpus_blocks_uncapped_scrape_when_guard_audit_fails(tmp_path, monkeypatch):
    observed = {"scrape_called": False, "build_called": False}

    async def _fake_scrape_state_laws(**kwargs):
        observed["scrape_called"] = True
        return {"status": "success", "data": [], "metadata": {"coverage_summary": {}}}

    def _fake_build(**kwargs):
        observed["build_called"] = True
        return {"status": "success", "missing_jsonld_states": []}

    def _fake_audit(*, states):
        return {
            "status": "fail",
            "states_checked": len(states),
            "missing_states": [],
            "error_count": 1,
            "warning_count": 0,
            "findings": [{"state": "MN", "severity": "error", "detail": "return seed_rows"}],
        }

    monkeypatch.setattr(refresh_state_laws_corpus, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(refresh_state_laws_corpus, "build_state_laws_parquet_artifacts", _fake_build)
    monkeypatch.setattr(refresh_state_laws_corpus, "_run_full_corpus_guard_audit", _fake_audit)

    args = argparse.Namespace(
        states="MN",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=True,
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
        dry_run=False,
        json=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "failed_preflight"
    assert result["reason"] == "full_corpus_guard_audit_failed"
    assert observed == {"scrape_called": False, "build_called": False}


def test_refresh_state_laws_corpus_preserves_bounded_scrape_env(tmp_path, monkeypatch):
    observed = {}

    async def _fake_scrape_state_laws(**kwargs):
        observed["full_corpus_env"] = __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS")
        observed["max_statutes"] = kwargs.get("max_statutes")
        return {"status": "success", "data": [], "metadata": {"coverage_summary": {}}}

    def _fail_audit(*, states):
        raise AssertionError("bounded refresh should not run full-corpus guard audit")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "0")
    monkeypatch.setattr(refresh_state_laws_corpus, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(refresh_state_laws_corpus, "_run_full_corpus_guard_audit", _fail_audit)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 0,
        },
    )

    args = argparse.Namespace(
        states="MN",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=True,
        max_statutes=3,
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
        dry_run=False,
        json=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "success"
    assert observed == {"full_corpus_env": "0", "max_statutes": 3}
    assert __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS") == "0"


def test_refresh_state_laws_corpus_dry_run_skips_completed_states_from_registry(tmp_path):
    registry_path = tmp_path / "state_laws_completed_states.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "ipfs_datasets_py.state_laws_refresh.completed_states.v1",
                "updated_at": "2026-05-19T00:00:00+00:00",
                "states": {
                    "MN": {
                        "status": "success",
                        "statutes_count": 100,
                        "completed_at": "2026-05-18T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        states="MN,WI",
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
        completed_states_registry=str(registry_path),
        skip_completed_states=True,
        persist_completed_states_registry=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "dry_run"
    assert result["plan"]["requested_states"] == ["MN", "WI"]
    assert result["plan"]["states"] == ["WI"]
    assert result["plan"]["skipped_completed_states"] == ["MN"]


def test_refresh_state_laws_corpus_persists_completed_states_registry(tmp_path, monkeypatch):
    registry_path = tmp_path / "state_laws_completed_states.json"

    async def _fake_scrape_state_laws(**kwargs):
        callback = kwargs["state_completion_callback"]
        await callback(
            {
                "state_code": "WI",
                "state_name": "Wisconsin",
                "statutes_count": 1,
                "statute_data": {"state_name": "Wisconsin", "statutes": [{"id": "WI-1"}]},
            }
        )
        return {"status": "success", "data": [], "metadata": {"coverage_summary": {"coverage_gap_states": []}}}

    monkeypatch.setattr(refresh_state_laws_corpus, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["WI"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 1,
        },
    )

    args = argparse.Namespace(
        states="WI",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=True,
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
        dry_run=False,
        json=True,
        completed_states_registry=str(registry_path),
        skip_completed_states=True,
        persist_completed_states_registry=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "success"
    assert registry_path.exists()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    wi_entry = registry.get("states", {}).get("WI", {})
    assert wi_entry.get("status") == "success"
    assert int(wi_entry.get("statutes_count") or 0) == 1


def test_refresh_state_laws_corpus_promotes_timeout_without_remaining_work_to_success(tmp_path, monkeypatch):
    registry_path = tmp_path / "state_laws_completed_states.json"

    async def _fake_scrape_state_laws(**kwargs):
        callback = kwargs["state_completion_callback"]
        await callback(
            {
                "state_code": "RI",
                "state_name": "Rhode Island",
                "statutes_count": 1,
                "error": "Failed to scrape Rhode Island: timed out after 900 seconds",
                "timeout_diagnostics": {
                    "timed_out": True,
                    "classification": "timeout_with_no_detectable_remaining_work",
                    "signal_found": True,
                    "signal_kind": "codes_progress",
                    "work_remaining": False,
                    "progress_scanned": 1,
                    "progress_discovered": 1,
                    "coverage_ratio": 1.0,
                },
                "statute_data": {"state_name": "Rhode Island", "statutes": [{"id": "RI-1"}]},
            }
        )
        return {"status": "success", "data": [], "metadata": {"coverage_summary": {"coverage_gap_states": []}}}

    monkeypatch.setattr(refresh_state_laws_corpus, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["RI"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 1,
        },
    )

    args = argparse.Namespace(
        states="RI",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=True,
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
        dry_run=False,
        json=True,
        completed_states_registry=str(registry_path),
        skip_completed_states=True,
        persist_completed_states_registry=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "success"
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    ri_progress = progress.get("state_results", {}).get("RI", {})
    assert ri_progress.get("status") == "success"
    assert ri_progress.get("completion_mode") == "timeout_no_remaining_work"
    assert ri_progress.get("timeout_promoted_to_success") is True
    assert ri_progress.get("timeout_classification") == "timeout_with_no_detectable_remaining_work"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    ri_registry = registry.get("states", {}).get("RI", {})
    assert ri_registry.get("status") == "success"
    assert ri_registry.get("completion_mode") == "timeout_no_remaining_work"
    assert ri_registry.get("timeout_promoted_to_success") is True
    assert ri_registry.get("timeout_classification") == "timeout_with_no_detectable_remaining_work"


def test_refresh_state_laws_corpus_does_not_promote_timeout_success_for_bounded_probe(tmp_path, monkeypatch):
    registry_path = tmp_path / "state_laws_completed_states.json"

    async def _fake_scrape_state_laws(**kwargs):
        callback = kwargs["state_completion_callback"]
        await callback(
            {
                "state_code": "MS",
                "state_name": "Mississippi",
                "statutes_count": 10,
                "error": "Failed to scrape Mississippi: timed out after 900 seconds",
                "timeout_diagnostics": {
                    "timed_out": True,
                    "classification": "timeout_with_no_detectable_remaining_work",
                    "signal_found": True,
                    "signal_kind": "codes_progress",
                    "work_remaining": False,
                    "progress_scanned": 10,
                    "progress_discovered": 10,
                    "coverage_ratio": 1.0,
                },
                "statute_data": {"state_name": "Mississippi", "statutes": [{"id": "MS-1"}]},
            }
        )
        return {"status": "success", "data": [], "metadata": {"coverage_summary": {"coverage_gap_states": []}}}

    monkeypatch.setattr(refresh_state_laws_corpus, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MS"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 1,
        },
    )

    args = argparse.Namespace(
        states="MS",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir="",
        parquet_dir="",
        scrape=True,
        max_statutes=1,
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
        dry_run=False,
        json=True,
        completed_states_registry=str(registry_path),
        skip_completed_states=True,
        persist_completed_states_registry=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "success"
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    ms_progress = progress.get("state_results", {}).get("MS", {})
    assert ms_progress.get("status") == "error"
    assert ms_progress.get("timeout_promoted_to_success") is not True
    assert ms_progress.get("timeout_classification") == "timeout_with_no_detectable_remaining_work"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    ms_registry = registry.get("states", {}).get("MS", {})
    assert ms_registry == {}


def test_refresh_state_laws_corpus_dry_run_zero_statutes_not_skipped_by_default(tmp_path):
    registry_path = tmp_path / "state_laws_completed_states.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "ipfs_datasets_py.state_laws_refresh.completed_states.v1",
                "updated_at": "2026-05-19T00:00:00+00:00",
                "states": {
                    "MN": {
                        "status": "success",
                        "statutes_count": 100,
                        "completed_at": "2026-05-18T00:00:00+00:00",
                    },
                    "NH": {
                        "status": "zero_statutes",
                        "statutes_count": 0,
                        "completed_at": "2026-05-18T01:00:00+00:00",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        states="MN,NH",
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
        completed_states_registry=str(registry_path),
        skip_completed_states=True,
        persist_completed_states_registry=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "dry_run"
    assert result["plan"]["requested_states"] == ["MN", "NH"]
    assert result["plan"]["states"] == ["NH"]
    assert result["plan"]["skipped_completed_states"] == ["MN"]


def test_refresh_state_laws_corpus_dry_run_zero_statutes_skipped_when_enabled(tmp_path, monkeypatch):
    registry_path = tmp_path / "state_laws_completed_states.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "ipfs_datasets_py.state_laws_refresh.completed_states.v1",
                "updated_at": "2026-05-19T00:00:00+00:00",
                "states": {
                    "NH": {
                        "status": "zero_statutes",
                        "statutes_count": 0,
                        "completed_at": "2026-05-18T01:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_LAWS_REGISTRY_TREAT_ZERO_AS_COMPLETE", "1")

    args = argparse.Namespace(
        states="NH",
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
        completed_states_registry=str(registry_path),
        skip_completed_states=True,
        persist_completed_states_registry=True,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "dry_run"
    assert result["plan"]["states"] == []
    assert result["plan"]["skipped_completed_states"] == ["NH"]


def test_all_state_jurisdictions_have_registered_scrapers():
    registered = set(StateScraperRegistry.get_all_registered_states())

    assert set(US_STATES) - registered == set()
    assert len(registered) == len(US_STATES)
