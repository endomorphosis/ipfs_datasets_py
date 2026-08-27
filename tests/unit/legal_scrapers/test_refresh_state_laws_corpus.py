import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    ACTION_REUSE,
    coordinate_jurisdictions,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    closed_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import US_STATES
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    StateScraperRegistry,
)

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
_REAL_RUNNER_SOURCE_SOFTWARE_VERSION = (
    refresh_state_laws_corpus.runner_source_software_version
)

_TEST_WORKER_QUIESCENCE = {
    "attested": True,
    "quiescent": True,
    "completion_mode": "test_worker_returned",
    "worker_name": "test-state-worker",
}
_TEST_RUNNER_SOURCE_SOFTWARE_IDENTITY = (
    "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
    + hashlib.sha256(b"test-refresh-runner").hexdigest()
)


@pytest.fixture(autouse=True)
def _stable_refresh_runner_identity(monkeypatch):
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "runner_source_software_version",
        lambda **kwargs: _TEST_RUNNER_SOURCE_SOFTWARE_IDENTITY,
    )


def _quiescent_state_result(payload: dict) -> dict:
    result = dict(payload)
    result.setdefault(
        "worker_quiescence",
        dict(_TEST_WORKER_QUIESCENCE),
    )
    return result


def _receipt_bound_to_local_output(
    state: str,
    body: bytes,
    *,
    frontier_closed: bool = True,
) -> dict:
    receipt = closed_jurisdiction_receipt(
        state,
        discovered=8,
        fetched=8,
        excluded=0,
        quarantined=0,
        frontier_closed=frontier_closed,
    )
    digest = hashlib.sha256(body).hexdigest()
    receipt["hashes"]["admitted_body_sha256"] = digest
    receipt["replay"]["admitted_body_sha256"] = digest
    return receipt


def _coordinator_test_jsonld_body(state: str, *, rows: int = 8) -> bytes:
    return b"".join(
        (
            json.dumps(
                {
                    "@type": "Legislation",
                    "identifier": f"{state}-{index}",
                    "legislationJurisdiction": f"US-{state}",
                    "stateCode": state,
                    "text": f"official {state} statute {index}",
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        for index in range(1, rows + 1)
    )


def test_cli_defaults_to_preserving_short_statutes(monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT_PATH)])
    args = refresh_state_laws_corpus.parse_args()
    assert args.min_full_text_chars == 1
    assert args.incremental_state_materialize is True
    assert args.acquisition_evidence_root == ""
    assert args.strict_acquisition_evidence is False


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    (
        ("success", 0),
        ("partial_success", 0),
        ("dry_run", 0),
        ("failed_source_software_immutability", 1),
        ("error", 1),
        ("unexpected_terminal_status", 1),
    ),
)
def test_cli_main_returns_nonzero_for_nonauthorizing_terminal_statuses(
    monkeypatch,
    capsys,
    status,
    expected_exit,
):
    async def _result(_args):
        return {"status": status, "authorizing_for_publication": False}

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "parse_args",
        lambda: argparse.Namespace(json=True),
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "refresh_state_laws_corpus",
        _result,
    )

    assert refresh_state_laws_corpus.main() == expected_exit
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_refresh_cli_exposes_strict_acquisition_evidence_root(monkeypatch, tmp_path):
    root = tmp_path / "evidence"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT_PATH),
            "--scrape",
            "--acquisition-evidence-root",
            str(root),
            "--strict-acquisition-evidence",
        ],
    )

    args = refresh_state_laws_corpus.parse_args()

    assert args.acquisition_evidence_root == str(root)
    assert args.strict_acquisition_evidence is True


def test_refresh_dry_run_records_evidence_root_and_machine_inventory(
    monkeypatch,
    tmp_path,
):
    root = (tmp_path / "evidence").resolve()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT_PATH),
            "--states",
            "WI",
            "--output-root",
            str(tmp_path / "output"),
            "--acquisition-evidence-root",
            str(root),
            "--dry-run",
        ],
    )
    args = refresh_state_laws_corpus.parse_args()

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(args)
    )

    assert result["status"] == "dry_run"
    assert result["plan"]["acquisition_evidence_root"] == str(root)
    assert result["plan"]["strict_acquisition_evidence"] is False
    inventory = result["plan"]["transport_bypass_inventory"]
    assert inventory["jurisdiction_count"] == 1
    assert list(inventory["jurisdictions"]) == ["WI"]


def test_refresh_strict_evidence_missing_root_fails_preflight(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT_PATH),
            "--states",
            "WI",
            "--output-root",
            str(tmp_path / "output"),
            "--scrape",
            "--strict-acquisition-evidence",
            "--dry-run",
        ],
    )
    args = refresh_state_laws_corpus.parse_args()

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(args)
    )

    assert result["status"] == "failed_preflight"
    assert result["reason"] == "strict_acquisition_evidence_preflight_failed"
    assert "acquisition_evidence_root_required" in result["errors"]


def test_state_scraper_environment_threads_and_restores_acquisition_evidence(
    monkeypatch,
    tmp_path,
):
    root = (tmp_path / "evidence").resolve()
    root_env = "STATE_LAWS_MULTIFETCH_EVIDENCE_ROOT"
    strict_env = "STATE_LAWS_STRICT_MULTIFETCH_EVIDENCE"
    monkeypatch.setenv(root_env, "prior-root")
    monkeypatch.setenv(strict_env, "prior-strict")

    with refresh_state_laws_corpus._state_scraper_run_environment(
        output_root=tmp_path,
        full_corpus=True,
        acquisition_evidence_root=root,
        strict_acquisition_evidence=True,
    ):
        assert os.environ[root_env] == str(root)
        assert os.environ[strict_env] == "1"

    assert os.environ[root_env] == "prior-root"
    assert os.environ[strict_env] == "prior-strict"


def test_incremental_completion_requires_and_consumes_frontier_projection(tmp_path):
    from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
        closed_jurisdiction_receipt,
    )
    from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
        CLOSURE_INPUT_SCHEMA,
        StateLawMultiFetchAcquisitionLedger,
        build_canonical_state_law_jsonld_output_projection,
    )

    evidence_root = tmp_path / "evidence"
    parser_name = "WisconsinProspectiveParser"
    source_url = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
    body = b"official Wisconsin response retained before parsing"
    ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name=parser_name,
    )
    ledger.retain_parser_input(
        official_url=source_url,
        body=body,
        transport_receipt={
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "official_url": source_url,
            "source_transport": "direct",
        },
        retrieved_at="2026-08-24T07:00:00Z",
    )
    canonical_path = tmp_path / "STATE-WI.jsonld"
    canonical_path.write_text(
        json.dumps(
            {
                "@id": "urn:state:wi:statute:1.01",
                "@type": "Legislation",
                "sectionNumber": "1.01",
                "sourceUrl": source_url,
                "stateCode": "WI",
                "text": "A person shall comply with this section.",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    state_result = {
        "state_code": "WI",
        "acquisition_evidence": {
            "aggregate": {"status": "pending_canonical_materialization"},
            "aggregate_eligible": True,
            "enabled": True,
            "parser_name": parser_name,
        },
    }
    materialization = {"jsonld_path": str(canonical_path)}

    pending, pending_error = (
        refresh_state_laws_corpus._close_incremental_state_acquisition_aggregate(
            state_code="WI",
            state_result=state_result,
            materialization_result=materialization,
            acquisition_evidence_root=evidence_root,
            strict=True,
        )
    )
    assert pending["aggregate"]["status"] == "pending_source_frontier_replay"
    assert pending["aggregate"]["authorizing_for_publication"] is False
    assert "closure input is missing" in pending_error

    completion = closed_jurisdiction_receipt(
        "WI",
        discovered=1,
        fetched=1,
        excluded=0,
        quarantined=0,
        failed_final=0,
        duplicates=0,
        source_domain="docs.legis.wisconsin.gov",
        canonical_keys=["urn:state:wi:statute:1.01"],
        derived_keys=["urn:state:wi:statute:1.01"],
    )
    assert CLOSURE_INPUT_SCHEMA == "state-laws-multifetch-closure-input-v1"
    closure_path = ledger.retain_frontier_closure_projection(
        completion,
        replayed_frontier=dict(completion["frontier"]),
        canonical_output_projection=(
            build_canonical_state_law_jsonld_output_projection(
                canonical_path,
                jurisdiction="WI",
            )
        ),
        release_point=hashlib.sha256(b"wi-release").hexdigest(),
        official_source_url=(
            "https://docs.legis.wisconsin.gov/statutes/statutes/1"
        ),
        acquisition_path_ids=["wi-docs-statutes"],
        observation_time="2026-08-24T07:10:00Z",
        source_software_version="state-scraper/prospective-multifetch",
    )
    assert closure_path.parent == ledger.closure_inputs_dir
    state_result["acquisition_evidence"]["closure_input_path"] = str(
        closure_path
    )

    closed, close_error = (
        refresh_state_laws_corpus._close_incremental_state_acquisition_aggregate(
            state_code="WI",
            state_result=state_result,
            materialization_result=materialization,
            acquisition_evidence_root=evidence_root,
            strict=True,
        )
    )
    assert close_error == ""
    assert closed["aggregate"]["status"] == "closed_and_normalized"
    assert closed["aggregate"]["authorizing_for_publication"] is True
    assert Path(closed["aggregate"]["normalized_source_receipt_path"]).is_file()


def test_disabling_incremental_publish_keeps_local_materialization_enabled(
    monkeypatch,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [str(_SCRIPT_PATH), "--no-incremental-state-publish"],
    )
    args = refresh_state_laws_corpus.parse_args()
    assert args.incremental_state_publish is False
    assert args.incremental_state_materialize is True


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


def test_logical_merge_keeps_same_section_number_across_titles():
    payloads = [
        {
            "@id": "urn:state:de:statute:title-1:chapter-1:section-101",
            "@type": "Legislation",
            "sectionNumber": "101",
            "titleNumber": "1",
            "chapterNumber": "1",
            "text": "The first title provision remains in force.",
            "sourceUrl": "https://delcode.delaware.gov/title1/c001/sc01/index.html#101",
        },
        {
            "@id": "urn:state:de:statute:title-2:chapter-1:section-101",
            "@type": "Legislation",
            "sectionNumber": "101",
            "titleNumber": "2",
            "chapterNumber": "1",
            "text": "The second title provision remains in force.",
            "sourceUrl": "https://delcode.delaware.gov/title2/c001/sc01/index.html#101",
        },
    ]
    rows = [
        refresh_state_laws_corpus.jsonld_payload_to_canonical_row(
            payload, state_code="DE"
        )
        for payload in payloads
    ]

    merged = refresh_state_laws_corpus.merge_canonical_rows([], rows)

    assert len(merged) == 2
    assert {row["identifier"] for row in merged} == {"101"}
    assert {row["source_id"] for row in merged} == {
        payload["@id"] for payload in payloads
    }
    assert all("logical_history" not in row for row in merged)


def test_logical_merge_keeps_concurrent_source_records_at_same_section():
    payloads = [
        {
            "@id": "urn:state:de:statute:qualified:current",
            "@type": "Legislation",
            "sectionNumber": "6927",
            "titleNumber": "9",
            "chapterNumber": "69",
            "text": "The current official provision remains in force.",
            "sourceUrl": "https://delcode.delaware.gov/title9/c069/sc01/index.html#6927",
            "structuredData": {"source_record_id": "DE-9-69-6927-current"},
        },
        {
            "@id": "urn:state:de:statute:qualified:future",
            "@type": "Legislation",
            "sectionNumber": "6927",
            "titleNumber": "9",
            "chapterNumber": "69",
            "text": "The future-effective official provision takes effect later.",
            "sourceUrl": "https://delcode.delaware.gov/title9/c069/sc01/index.html#6927",
            "structuredData": {"source_record_id": "DE-9-69-6927-future"},
        },
    ]
    rows = [
        refresh_state_laws_corpus.jsonld_payload_to_canonical_row(
            payload, state_code="DE"
        )
        for payload in payloads
    ]

    merged = refresh_state_laws_corpus.merge_canonical_rows([], rows)

    assert len(merged) == 2
    assert {row["source_id"] for row in merged} == {
        payload["@id"] for payload in payloads
    }
    assert {
        json.loads(row["jsonld"])["structuredData"]["source_record_id"]
        for row in merged
    } == {"DE-9-69-6927-current", "DE-9-69-6927-future"}


def test_logical_merge_still_replaces_same_source_identity_with_history():
    base = {
        "state_code": "DE",
        "source_id": "urn:state:de:statute:title-9:chapter-69:section-6927",
    }

    merged = refresh_state_laws_corpus.merge_canonical_rows(
        [
            {
                **base,
                "identifier": "Del. Code tit. 9, § 6927 (prior edition)",
                "ipfs_cid": "cid-old",
                "text": "Prior official text.",
            }
        ],
        [
            {
                **base,
                "identifier": "6927",
                "ipfs_cid": "cid-new",
                "text": "Current official text.",
            }
        ],
    )

    assert len(merged) == 1
    assert merged[0]["ipfs_cid"] == "cid-new"
    assert merged[0]["logical_history"] == [
        {"ipfs_cid": "cid-old", "replaced": True}
    ]
    assert merged[0]["logical_key"].startswith("logical:DE:source_id:")


def test_logical_merge_keeps_explicit_legal_id_as_strongest_identity():
    merged = refresh_state_laws_corpus.merge_canonical_rows(
        [
            {
                "state_code": "DE",
                "legal_id": "state:DE:delaware-code:9:69:6927",
                "source_id": "urn:state:de:statute:old-source",
                "identifier": "6927",
                "ipfs_cid": "cid-old",
            }
        ],
        [
            {
                "state_code": "DE",
                "legal_id": "state:DE:delaware-code:9:69:6927",
                "source_id": "urn:state:de:statute:new-source",
                "identifier": "6927",
                "ipfs_cid": "cid-new",
            }
        ],
    )

    assert len(merged) == 1
    assert merged[0]["ipfs_cid"] == "cid-new"
    assert merged[0]["logical_key"].startswith("logical:DE:legal_id:")


def test_logical_merge_legacy_rows_without_source_id_keep_identifier_fallback():
    merged = refresh_state_laws_corpus.merge_canonical_rows(
        [
            {
                "state_code": "DE",
                "identifier": "Del. Code tit. 9, § 6927",
                "ipfs_cid": "cid-old",
            }
        ],
        [
            {
                "state_code": "DE",
                "identifier": "Del. Code tit. 9, § 6927",
                "ipfs_cid": "cid-new",
            }
        ],
    )

    assert len(merged) == 1
    assert merged[0]["ipfs_cid"] == "cid-new"
    assert merged[0]["logical_key"].startswith("logical:DE:identifier:")


def test_parquet_builder_preserves_same_section_across_titles_and_variants(tmp_path):
    jsonld_dir = tmp_path / "jsonld"
    parquet_dir = tmp_path / "parquet"
    jsonld_dir.mkdir()
    payloads = [
        {
            "@id": "urn:state:de:statute:title-1:section-101",
            "@type": "Legislation",
            "sectionNumber": "101",
            "titleNumber": "1",
            "text": "The title one provision remains in force.",
            "sourceUrl": "https://delcode.delaware.gov/title1/c001/index.html#101",
        },
        {
            "@id": "urn:state:de:statute:title-2:section-101:current",
            "@type": "Legislation",
            "sectionNumber": "101",
            "titleNumber": "2",
            "text": "The current title two provision remains in force.",
            "sourceUrl": "https://delcode.delaware.gov/title2/c001/index.html#101",
            "structuredData": {"source_record_id": "DE-2-101-current"},
        },
        {
            "@id": "urn:state:de:statute:title-2:section-101:future",
            "@type": "Legislation",
            "sectionNumber": "101",
            "titleNumber": "2",
            "text": "The future title two provision takes effect later.",
            "sourceUrl": "https://delcode.delaware.gov/title2/c001/index.html#101",
            "structuredData": {"source_record_id": "DE-2-101-future"},
        },
    ]
    (jsonld_dir / "STATE-DE.jsonld").write_text(
        "".join(json.dumps(payload) + "\n" for payload in payloads),
        encoding="utf-8",
    )

    result = refresh_state_laws_corpus.build_state_laws_parquet_artifacts(
        states=["DE"],
        jsonld_dir=jsonld_dir,
        parquet_dir=parquet_dir,
        merge_existing_local=False,
        merge_hf_existing=False,
    )
    rows = pq.read_table(parquet_dir / "STATE-DE.parquet").to_pylist()

    assert result["state_reports"][0]["scraped_row_count"] == 3
    assert result["state_reports"][0]["merged_row_count"] == 3
    assert len(rows) == 3
    assert {row["identifier"] for row in rows} == {"101"}
    assert {row["source_id"] for row in rows} == {
        payload["@id"] for payload in payloads
    }


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

    assert result["combined_row_count"] == 0
    assert result["combined_written"] is False
    assert result["exact_production_jurisdiction_set"] is False
    assert len(rows) == 2
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
    assert result["plan"]["state_count"] == 51
    assert result["plan"]["states"][0] == "AL"
    assert result["plan"]["states"][-1] == "DC"


def test_no_scrape_publish_is_rejected_before_any_hf_call(tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_publish_parquet_dir",
        lambda **_kwargs: observed.append("publish"),
    )
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

    assert result["status"] == "failed_preflight"
    assert (
        result["reason"]
        == "refresh_external_mutation_requires_sealed_production_runner"
    )
    assert result["authorizing_for_publication"] is False
    assert observed == []


def test_no_scrape_exact51_publish_does_not_resolve_token_or_upload(
    tmp_path,
    monkeypatch,
):
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
        return {
            "upload_commit": "https://huggingface.co/datasets/justicedao/ipfs_state_laws/commit/keyring"
        }

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_resolve_hf_token",
        lambda token=None: observed.setdefault("token", token),
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        _fake_build_state_laws_parquet_artifacts,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus, "_publish_parquet_dir", _fake_publish_parquet_dir
    )

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

    assert result["status"] == "failed_preflight"
    assert (
        result["reason"]
        == "refresh_external_mutation_requires_sealed_production_runner"
    )
    assert observed == {}


def test_exact51_mixed_reuse_publish_is_rejected_before_scrape_or_hf(
    tmp_path,
    monkeypatch,
):
    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    body = _coordinator_test_jsonld_body("MN")
    (jsonld_dir / "STATE-MN.jsonld").write_bytes(body)
    receipt = _receipt_bound_to_local_output("MN", body)
    observed = {"scrape": False, "publish": False, "token": False}

    def _coordinate(**kwargs):
        return coordinate_jurisdictions(
            receipts={"MN": receipt},
            body_bytes=kwargs["body_bytes"],
        )

    async def _unexpected_scrape(**_kwargs):
        observed["scrape"] = True
        return {}

    def _unexpected_publish(**_kwargs):
        observed["publish"] = True
        return {}

    def _unexpected_token(_token=None):
        observed["token"] = True
        return "unexpected"

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "coordinate_default_prior_evidence",
        _coordinate,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_capture_registered_state_source_software_versions",
        lambda states: (
            {
                state: _test_source_software_identity("a")
                for state in states
            },
            {},
        ),
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _unexpected_scrape,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_publish_parquet_dir",
        _unexpected_publish,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_resolve_hf_token",
        _unexpected_token,
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(
                tmp_path,
                states="all",
                jsonld_dir=str(jsonld_dir),
                publish_to_hf=True,
                skip_completed_states=True,
            )
        )
    )

    assert result["status"] == "failed_preflight"
    assert (
        result["reason"]
        == "refresh_external_mutation_requires_sealed_production_runner"
    )
    assert observed == {"scrape": False, "publish": False, "token": False}


def test_exact51_fresh_scrape_publish_is_rejected_before_build_scrape_or_hf(
    tmp_path,
    monkeypatch,
):
    observed = {
        "build": False,
        "scrape": False,
        "publish": False,
        "token": False,
    }

    async def _unexpected_scrape(**_kwargs):
        observed["scrape"] = True
        return {}

    def _unexpected_build(**_kwargs):
        observed["build"] = True
        return {}

    def _unexpected_publish(**_kwargs):
        observed["publish"] = True
        return {}

    def _unexpected_token(_token=None):
        observed["token"] = True
        return "unexpected"

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _unexpected_scrape,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        _unexpected_build,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_publish_parquet_dir",
        _unexpected_publish,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_resolve_hf_token",
        _unexpected_token,
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(
                tmp_path,
                states="all",
                publish_to_hf=True,
                skip_completed_states=False,
            )
        )
    )

    assert result["status"] == "failed_preflight"
    assert (
        result["reason"]
        == "refresh_external_mutation_requires_sealed_production_runner"
    )
    assert result["authorizing_for_publication"] is False
    assert observed == {
        "build": False,
        "scrape": False,
        "publish": False,
        "token": False,
    }


def test_strict_preflight_rejects_legacy_shared_and_unrecognized_selectors(
    tmp_path,
    monkeypatch,
):
    observed = {"scrape": False}

    async def _unexpected_scrape(**_kwargs):
        observed["scrape"] = True
        return {}

    monkeypatch.setenv("MINNESOTA_SECTION_HTML", str(tmp_path / "fixture.html"))
    monkeypatch.setenv("CCINDEX_MASTER_DB", str(tmp_path / "ccindex.db"))
    monkeypatch.setenv("INDIANA_WAYBACK_FALLBACK_TIMESTAMP", "20200101000000")
    monkeypatch.setenv("STATE_SCRAPER_MS_ENABLE_UNICOURT_FALLBACK", "1")
    monkeypatch.setenv("STATE_SCRAPER_MAX_STATUTES", "1")
    monkeypatch.setenv("MINNESOTA_UNRECOGNIZED_XML", str(tmp_path / "unknown.xml"))
    monkeypatch.setenv("NY_UNRECOGNIZED_JSON", str(tmp_path / "unknown-ny.json"))
    monkeypatch.setenv("DC_UNRECOGNIZED_XML", str(tmp_path / "unknown-dc.xml"))
    monkeypatch.setenv("CALIFORNIA_BULK_ZIP", str(tmp_path / "supported.zip"))
    monkeypatch.setenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        "opaque secret value that is never reported",
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _unexpected_scrape,
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(
                tmp_path,
                acquisition_evidence_root=str(tmp_path / "evidence"),
                strict_acquisition_evidence=True,
            )
        )
    )

    assert result["status"] == "failed_preflight"
    assert result["reason"] == "strict_acquisition_evidence_preflight_failed"
    assert (
        "strict_evidence_forbids_ambient_selector:MINNESOTA_SECTION_HTML"
        in result["errors"]
    )
    assert (
        "strict_evidence_forbids_ambient_selector:CCINDEX_MASTER_DB"
        in result["errors"]
    )
    assert (
        "strict_evidence_forbids_ambient_selector:"
        "INDIANA_WAYBACK_FALLBACK_TIMESTAMP"
        in result["errors"]
    )
    assert (
        "strict_evidence_forbids_ambient_selector:"
        "STATE_SCRAPER_MS_ENABLE_UNICOURT_FALLBACK"
        in result["errors"]
    )
    assert (
        "strict_evidence_forbids_ambient_selector:STATE_SCRAPER_MAX_STATUTES"
        in result["errors"]
    )
    assert (
        "strict_evidence_forbids_unrecognized_selector:"
        "MINNESOTA_UNRECOGNIZED_XML"
        in result["errors"]
    )
    assert (
        "strict_evidence_forbids_unrecognized_selector:NY_UNRECOGNIZED_JSON"
        in result["errors"]
    )
    assert (
        "strict_evidence_forbids_unrecognized_selector:DC_UNRECOGNIZED_XML"
        in result["errors"]
    )
    serialized = json.dumps(result, sort_keys=True)
    assert "CALIFORNIA_BULK_ZIP" not in serialized
    assert "opaque secret value" not in serialized
    assert observed == {"scrape": False}


def test_strict_preflight_validates_bound_digest_without_disclosing_value(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("NEW_JERSEY_BULK_RETAINED_SHA256", "not-a-digest")

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(
                tmp_path,
                acquisition_evidence_root=str(tmp_path / "evidence"),
                strict_acquisition_evidence=True,
            )
        )
    )

    assert result["status"] == "failed_preflight"
    assert (
        "strict_evidence_invalid_bound_selector:"
        "NEW_JERSEY_BULK_RETAINED_SHA256"
        in result["errors"]
    )
    assert "not-a-digest" not in json.dumps(result, sort_keys=True)


def test_refresh_state_laws_corpus_sets_full_corpus_env_for_uncapped_scrape(tmp_path, monkeypatch):
    observed = {}

    async def _fake_scrape_state_laws(**kwargs):
        observed["full_corpus_env"] = __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS")
        observed["max_statutes"] = kwargs.get("max_statutes")
        await kwargs["state_completion_callback"](
            _quiescent_state_result(
                {
                    "state_code": "MN",
                    "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                    "state_name": "Minnesota",
                    "statutes_count": 1,
                    "statute_data": {"state_name": "Minnesota", "statutes": []},
                }
            )
        )
        return {"status": "success", "data": [], "metadata": {"coverage_summary": {}}}

    def _fake_audit(*, states):
        observed["audit_states"] = list(states)
        return {
            "status": "pass",
            "states_checked": len(states),
            "missing_states": [],
            "error_count": 0,
            "warning_count": 0,
            "findings": [],
        }

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
        incremental_state_materialize=False,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "partial_success"
    assert observed == {"audit_states": ["MN"], "full_corpus_env": "1", "max_statutes": None}
    assert result["full_corpus_guard_audit"]["status"] == "pass"
    assert __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS") is None


def test_uncapped_timeout_recovery_keeps_full_corpus_scope(tmp_path, monkeypatch):
    observed = []

    async def _fake_scrape_state_laws(**kwargs):
        observed.append(
            {
                "states": list(kwargs["states"]),
                "full_corpus": __import__("os").environ.get(
                    "STATE_SCRAPER_FULL_CORPUS"
                ),
                "checkpoint_dir": __import__("os").environ.get(
                    "STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR"
                ),
            }
        )
        callback = kwargs["state_completion_callback"]
        if len(observed) == 1:
            await callback(
                {
                    "state_code": "MN",
                    "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                    "state_name": "Minnesota",
                    "statutes_count": 4,
                    "error": "timed out while frontier work remained",
                    "timeout_diagnostics": {
                        "timed_out": True,
                        "classification": "timeout_with_remaining_work",
                        "signal_kind": "frontier",
                        "work_remaining": True,
                    },
                }
            )
        else:
            await callback(
                {
                    "state_code": "MN",
                    "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                    "state_name": "Minnesota",
                    "statutes_count": 8,
                    "statute_data": {
                        "state_name": "Minnesota",
                        "statutes": [{"id": "MN-1"}],
                    },
                }
            )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    monkeypatch.delenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", raising=False)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_run_full_corpus_guard_audit",
        lambda *, states: {
            "status": "pass",
            "states_checked": len(states),
            "missing_states": [],
            "error_count": 0,
            "warning_count": 0,
            "findings": [],
        },
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 1,
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
        timeout_recovery_rounds=1,
        timeout_recovery_timeout_multiplier=2.0,
        timeout_recovery_timeout_cap_seconds=0.0,
        timeout_recovery_retry_attempts=1,
        timeout_recovery_parallel_workers=1,
        strict_full_text=False,
        min_full_text_chars=1,
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
        persist_completed_states_registry=False,
        incremental_state_materialize=False,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    checkpoint_dir = str(tmp_path / "partial_checkpoints")
    assert result["status"] == "partial_success"
    assert observed == [
        {"states": ["MN"], "full_corpus": "1", "checkpoint_dir": checkpoint_dir},
        {"states": ["MN"], "full_corpus": "1", "checkpoint_dir": checkpoint_dir},
    ]
    assert __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS") is None
    assert __import__("os").environ.get("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") is None


def test_refresh_state_laws_corpus_blocks_uncapped_scrape_when_guard_audit_fails(
    tmp_path, monkeypatch
):
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
    monkeypatch.setattr(
        refresh_state_laws_corpus, "build_state_laws_parquet_artifacts", _fake_build
    )
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
        await kwargs["state_completion_callback"](
            _quiescent_state_result(
                {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "statutes_count": 1,
                    "statute_data": {"state_name": "Minnesota", "statutes": []},
                }
            )
        )
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
        incremental_state_materialize=False,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["status"] == "partial_success"
    assert observed == {"full_corpus_env": "0", "max_statutes": 3}
    assert __import__("os").environ.get("STATE_SCRAPER_FULL_CORPUS") == "0"


def test_refresh_state_laws_corpus_dry_run_does_not_skip_registry_only_completion(
    tmp_path,
):
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
    assert result["plan"]["states"] == ["MN", "WI"]
    assert result["plan"]["skipped_completed_states"] == []
    assert result["plan"]["registry_completed_state_candidates"] == ["MN"]
    assert result["plan"]["registry_only_completion_states"] == ["MN"]


def test_refresh_reuses_only_coordinator_admitted_local_output(tmp_path, monkeypatch):
    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    body = _coordinator_test_jsonld_body("MN")
    (jsonld_dir / "STATE-MN.jsonld").write_bytes(body)
    receipt = _receipt_bound_to_local_output("MN", body)

    def _coordinate(**kwargs):
        assert kwargs["body_bytes"] == {"MN": body}
        return coordinate_jurisdictions(
            receipts={"MN": receipt},
            body_bytes=kwargs["body_bytes"],
        )

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "coordinate_default_prior_evidence",
        _coordinate,
    )
    args = argparse.Namespace(
        states="MN,WI",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir=str(jsonld_dir),
        parquet_dir="",
        scrape=False,
        max_statutes=0,
        rate_limit_delay=0.0,
        parallel_workers=1,
        per_state_retry_attempts=0,
        per_state_timeout_seconds=1.0,
        strict_full_text=False,
        min_full_text_chars=1,
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
        skip_completed_states=True,
        persist_completed_states_registry=False,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["plan"]["states"] == ["WI"]
    assert result["plan"]["skipped_completed_states"] == ["MN"]
    assert result["plan"]["verified_prior_receipt_states"] == ["MN"]
    assert result["plan"]["acquisition_lease_actions"]["MN"] == ACTION_REUSE
    assert result["plan"]["local_output_bytes_checked_states"] == ["MN"]


def test_restart_coordinator_checks_local_outputs_one_state_at_a_time(
    tmp_path,
    monkeypatch,
):
    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    bodies = {
        "MN": _coordinator_test_jsonld_body("MN"),
        "WI": _coordinator_test_jsonld_body("WI"),
    }
    for state, body in bodies.items():
        (jsonld_dir / f"STATE-{state}.jsonld").write_bytes(body)
    receipts = {
        state: _receipt_bound_to_local_output(state, body)
        for state, body in bodies.items()
    }
    observed_body_maps = []

    def _coordinate(**kwargs):
        supplied = dict(kwargs["body_bytes"])
        observed_body_maps.append(supplied)
        return coordinate_jurisdictions(
            receipts=receipts,
            body_bytes=supplied,
        )

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "coordinate_default_prior_evidence",
        _coordinate,
    )
    args = argparse.Namespace(
        states="MN,WI",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir=str(jsonld_dir),
        parquet_dir="",
        scrape=False,
        max_statutes=0,
        rate_limit_delay=0.0,
        parallel_workers=1,
        per_state_retry_attempts=0,
        per_state_timeout_seconds=1.0,
        strict_full_text=False,
        min_full_text_chars=1,
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
        skip_completed_states=True,
        persist_completed_states_registry=False,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert observed_body_maps == [{"MN": bodies["MN"]}, {"WI": bodies["WI"]}]
    assert result["plan"]["skipped_completed_states"] == ["MN", "WI"]
    assert (
        result["plan"]["local_output_byte_verification_mode"]
        == "one_state_at_a_time"
    )


def _incremental_materialization_args(tmp_path, **overrides):
    values = {
        "states": "MN",
        "include_dc": False,
        "output_root": str(tmp_path),
        "jsonld_dir": "",
        "parquet_dir": "",
        "scrape": True,
        "max_statutes": 0,
        "rate_limit_delay": 0.0,
        "parallel_workers": 1,
        "per_state_retry_attempts": 0,
        "per_state_timeout_seconds": 1.0,
        "timeout_recovery_rounds": 0,
        "strict_full_text": False,
        "min_full_text_chars": 1,
        "no_hydrate_statute_text": False,
        "progress_heartbeat_seconds": 10.0,
        "allow_justia_fallback": False,
        "no_merge_existing_local": True,
        "merge_hf_existing": False,
        "publish_to_hf": False,
        "incremental_state_materialize": True,
        "incremental_state_publish": False,
        "startup_stale_sync": False,
        "allow_incomplete_publish": False,
        "skip_full_corpus_guard_audit": True,
        "repo_id": "justicedao/ipfs_state_laws",
        "hf_token": "",
        "create_repo": False,
        "verify": False,
        "commit_message": "test",
        "dry_run": False,
        "json": True,
        "skip_completed_states": False,
        "persist_completed_states_registry": False,
        "load_completed_states_baseline": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _normalized_minnesota_statutes(count=8):
    return [
        {
            "state_code": "MN",
            "state_name": "Minnesota",
            "statute_id": f"MN-{index}",
            "code_name": "Minnesota Statutes",
            "section_number": f"1.{index:03d}",
            "section_name": f"Official provision {index}",
            "full_text": f"A person shall comply with official provision {index}.",
            "source_url": f"https://www.revisor.mn.gov/statutes/cite/1.{index:03d}",
        }
        for index in range(1, count + 1)
    ]


def _test_source_software_identity(digit: str) -> str:
    return f"tests.MinnesotaScraper@sha256:{digit * 64}"


def test_source_software_start_snapshot_error_fails_before_scrape_or_build(
    tmp_path,
    monkeypatch,
):
    observed = {"scrape": False, "build": False}

    def _fail_source_identity(state_code):
        raise OSError(f"cannot inspect {state_code} source")

    async def _unexpected_scrape(**kwargs):
        observed["scrape"] = True
        return {}

    def _unexpected_build(**kwargs):
        observed["build"] = True
        return {}

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_registered_state_source_software_version",
        _fail_source_identity,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _unexpected_scrape,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        _unexpected_build,
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(tmp_path)
        )
    )

    assert result["status"] == "failed_preflight"
    assert result["reason"] == "source_software_start_snapshot_failed"
    assert observed == {"scrape": False, "build": False}
    identity = result["source_software_immutability"]
    assert identity["status"] == "start_snapshot_failed"
    assert identity["authorizing_for_publication"] is False
    assert list(identity["verification_errors"]) == ["MN"]
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    assert progress["status"] == "failed_preflight"
    assert (
        progress["source_software_immutability"]["start_identities"] == {}
    )


def test_loaded_registered_scraper_edited_before_start_snapshot_fails_preflight(
    tmp_path,
    monkeypatch,
):
    """Stable post-import disk bytes cannot bless already-loaded older code."""

    module_path = tmp_path / "toy_registered_minnesota.py"
    original_source = """\
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import BaseStateScraper

class ToyMinnesotaScraper(BaseStateScraper):
    def get_base_url(self):
        return "https://old-loaded.example.test"

    def get_code_list(self):
        return []

    async def scrape_code(self, code_name, code_url):
        return []
"""
    module_path.write_text(original_source, encoding="utf-8")
    module_name = "toy_registered_minnesota"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    prior_class = StateScraperRegistry._scrapers["MN"]
    prior_attestation = dict(
        StateScraperRegistry._source_registration_attestations["MN"]
    )
    observed = {"scrape": False, "build": False}

    async def _unexpected_scrape(**kwargs):
        observed["scrape"] = True
        return {}

    def _unexpected_build(**kwargs):
        observed["build"] = True
        return {}

    try:
        StateScraperRegistry.register("MN", module.ToyMinnesotaScraper)
        module_path.write_text(
            original_source.replace(
                "https://old-loaded.example.test",
                "https://new-disk00.example.test",
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            refresh_state_laws_corpus,
            "scrape_state_laws",
            _unexpected_scrape,
        )
        monkeypatch.setattr(
            refresh_state_laws_corpus,
            "build_state_laws_parquet_artifacts",
            _unexpected_build,
        )

        result = asyncio.run(
            refresh_state_laws_corpus.refresh_state_laws_corpus(
                _incremental_materialization_args(tmp_path)
            )
        )
    finally:
        StateScraperRegistry._scrapers["MN"] = prior_class
        StateScraperRegistry._source_registration_attestations["MN"] = (
            prior_attestation
        )
        sys.modules.pop(module_name, None)

    assert result["status"] == "failed_preflight"
    assert result["reason"] == "source_software_start_snapshot_failed"
    assert observed == {"scrape": False, "build": False}
    error = result["source_software_immutability"]["verification_errors"]["MN"]
    assert "loaded frontier source bytes differ from current disk" in error


def test_loaded_refresh_runner_edited_before_start_snapshot_is_rejected(
    tmp_path,
    monkeypatch,
):
    imported_runner_copy = tmp_path / "refresh_state_laws_corpus.py"
    original_bytes = _SCRIPT_PATH.read_bytes()
    imported_runner_copy.write_bytes(original_bytes)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_RUNNER_SOURCE_PATH",
        imported_runner_copy.resolve(),
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "MODULE_IMPORT_SOURCE_SHA256",
        hashlib.sha256(original_bytes).hexdigest(),
    )
    imported_runner_copy.write_bytes(original_bytes + b"\n# post-import edit\n")

    with pytest.raises(
        RuntimeError,
        match="loaded refresh runner source bytes differ from current disk",
    ):
        _REAL_RUNNER_SOURCE_SOFTWARE_VERSION(
            require_loaded_source_correspondence=True
        )


def test_loaded_identity_binds_runner_global_callable_and_state_regex(
    monkeypatch,
):
    import re

    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        _loaded_executable_sha256,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import (
        KentuckyScraper,
    )

    runner_before = _loaded_executable_sha256(refresh_state_laws_corpus)
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        lambda **_kwargs: {"status": "forged"},
    )
    runner_after = _loaded_executable_sha256(refresh_state_laws_corpus)

    kentucky_before = _loaded_executable_sha256(KentuckyScraper)
    monkeypatch.setattr(KentuckyScraper, "_KY_SECTION_URL_RE", re.compile(".*"))
    kentucky_after = _loaded_executable_sha256(KentuckyScraper)

    assert runner_after != runner_before
    assert kentucky_after != kentucky_before


def test_loaded_identity_binds_decorator_wrapped_runner_and_lru_policy(
    monkeypatch,
):
    from ipfs_datasets_py.processors.legal_data import state_laws_source_policy
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        _loaded_executable_sha256,
    )

    runner_before = _loaded_executable_sha256(refresh_state_laws_corpus)
    runner_wrapped = refresh_state_laws_corpus._state_scraper_run_environment.__wrapped__

    def _replacement_runner_behavior():
        return "changed runner behavior"

    monkeypatch.setattr(
        runner_wrapped,
        "__code__",
        _replacement_runner_behavior.__code__,
    )
    runner_after = _loaded_executable_sha256(refresh_state_laws_corpus)

    policy_before = _loaded_executable_sha256(state_laws_source_policy)
    policy_wrapped = state_laws_source_policy._cached_default_catalog.__wrapped__

    def _replacement_policy_behavior():
        return "changed policy behavior"

    monkeypatch.setattr(
        policy_wrapped,
        "__code__",
        _replacement_policy_behavior.__code__,
    )
    policy_after = _loaded_executable_sha256(state_laws_source_policy)

    assert runner_after != runner_before
    assert policy_after != policy_before


def test_loaded_identity_binds_transitive_imported_callable_globals(
    monkeypatch,
):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        _loaded_executable_sha256,
    )

    nested_helper = refresh_state_laws_corpus.cid_for_obj.__globals__["cid_for_bytes"]
    runner_before = _loaded_executable_sha256(refresh_state_laws_corpus)

    def _replacement_cid_for_bytes(*_args, **_kwargs):
        return "changed nested helper behavior"

    monkeypatch.setattr(
        nested_helper,
        "__code__",
        _replacement_cid_for_bytes.__code__,
    )
    runner_after = _loaded_executable_sha256(refresh_state_laws_corpus)

    assert runner_after != runner_before


def test_loaded_identity_binds_imported_class_method_helper(
    monkeypatch,
):
    import types

    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        _loaded_executable_sha256,
    )

    dependency = types.ModuleType(
        "ipfs_datasets_py.identity_projection_dependency"
    )
    exec(
        "def helper():\n"
        "    return 'original'\n\n"
        "class ImportedWorker:\n"
        "    def run(self):\n"
        "        return helper()\n",
        dependency.__dict__,
    )
    target = types.ModuleType("ipfs_datasets_py.identity_projection_target")
    target.ImportedWorker = dependency.ImportedWorker
    exec(
        "def invoke():\n"
        "    return ImportedWorker().run()\n",
        target.__dict__,
    )

    before = _loaded_executable_sha256(target)

    def _replacement_helper():
        return "changed"

    monkeypatch.setattr(
        dependency.helper,
        "__code__",
        _replacement_helper.__code__,
    )
    after = _loaded_executable_sha256(target)

    assert after != before


def test_loaded_identity_binds_source_owned_module_qualified_helper(
    monkeypatch,
):
    import types

    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        _loaded_executable_sha256,
    )

    support = types.ModuleType("ipfs_datasets_py.identity_projection_support")
    exec("def helper():\n    return 'original'\n", support.__dict__)
    target = types.ModuleType(
        "ipfs_datasets_py.identity_projection_module_target"
    )
    target.support = support
    exec("def invoke():\n    return support.helper()\n", target.__dict__)

    before = _loaded_executable_sha256(target)

    def _replacement_helper():
        return "changed"

    monkeypatch.setattr(
        support.helper,
        "__code__",
        _replacement_helper.__code__,
    )
    after = _loaded_executable_sha256(target)

    assert after != before


def test_acquisition_in_progress_marker_is_exclusive_between_contenders(
    tmp_path,
):
    evidence_root = tmp_path / "evidence"
    barrier = threading.Barrier(2)

    def _contend(run_id):
        barrier.wait(timeout=5)
        try:
            path, digest = (
                refresh_state_laws_corpus._write_acquisition_in_progress_marker(
                    evidence_root,
                    run_id=run_id,
                    active_states=["MN"],
                )
            )
        except RuntimeError as exc:
            return {"status": "rejected", "run_id": run_id, "error": str(exc)}
        return {
            "status": "acquired",
            "run_id": run_id,
            "path": path,
            "digest": digest,
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(_contend, ("run-one", "run-two")))

    acquired = [item for item in outcomes if item["status"] == "acquired"]
    rejected = [item for item in outcomes if item["status"] == "rejected"]
    assert len(acquired) == 1
    assert len(rejected) == 1
    assert "already has an in-progress lease" in rejected[0]["error"]
    marker = json.loads(acquired[0]["path"].read_text(encoding="utf-8"))
    assert marker["run_id"] == acquired[0]["run_id"]
    refresh_state_laws_corpus._verify_acquisition_in_progress_marker(
        acquired[0]["path"],
        run_id=acquired[0]["run_id"],
        expected_sha256=acquired[0]["digest"],
    )


def test_runner_drift_after_pending_receipt_closure_prevents_run_seal(
    tmp_path,
    monkeypatch,
):
    evidence_root = tmp_path / "evidence"
    statutes = _normalized_minnesota_statutes(count=1)
    state_identity = _test_source_software_identity("f")
    runner_start = _TEST_RUNNER_SOURCE_SOFTWARE_IDENTITY
    runner_changed = (
        "scripts.ops.legal_data.refresh_state_laws_corpus@sha256:"
        + hashlib.sha256(b"changed-refresh-runner").hexdigest()
    )
    runner_observations = 0
    pending_path = evidence_root / "MN" / (
        "mn-runner-drift"
        + refresh_state_laws_corpus.PENDING_NORMALIZED_RECEIPT_SUFFIX
    )

    def _changing_runner_identity(**kwargs):
        nonlocal runner_observations
        runner_observations += 1
        return runner_start if runner_observations <= 2 else runner_changed

    async def _fake_scrape_state_laws(**kwargs):
        await kwargs["state_completion_callback"](
            _quiescent_state_result(
                {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "statutes_count": 1,
                    "statute_data": {
                        "state_code": "MN",
                        "state_name": "Minnesota",
                        "statutes": statutes,
                    },
                    "acquisition_evidence": {
                        "enabled": True,
                        "parser_name": "MinnesotaRunnerDriftTest",
                    },
                }
            )
        )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

    def _close_pending_receipt(**kwargs):
        assert kwargs["defer_normalized_receipt"] is True
        materialization = kwargs["materialization_result"]
        canonical_path = Path(materialization["jsonld_path"])
        canonical_sha256 = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(
            json.dumps(
                {
                    "jurisdiction": "MN",
                    "source_software_version": state_identity,
                    "payload": {
                        "requires_verified_transport_binding": False,
                        "verified_transport_receipts": [],
                        "verified_transport_receipts_trusted": False,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return (
            {
                "aggregate": {
                    "status": "closed_pending_run_seal",
                    "normalized_source_receipt_path": str(pending_path),
                    "canonical_jsonld_sha256": canonical_sha256,
                    "authorizing_for_publication": False,
                }
            },
            "",
        )

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "runner_source_software_version",
        _changing_runner_identity,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_registered_state_source_software_version",
        lambda state_code: state_identity,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_close_incremental_state_acquisition_aggregate",
        _close_pending_receipt,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 1,
        },
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(
                tmp_path,
                acquisition_evidence_root=str(evidence_root),
            )
        )
    )

    assert runner_observations == 3
    assert result["status"] == "failed_source_software_immutability"
    assert result["run_seal"]["status"] == "not_issued"
    assert result["run_seal"]["authorizing_for_publication"] is False
    assert pending_path.is_file()
    assert list(evidence_root.rglob("*.normalized.json")) == []
    assert list(evidence_root.rglob(f"*{refresh_state_laws_corpus.RUN_SEAL_SUFFIX}")) == []
    immutability = result["source_software_immutability"]
    assert immutability["runner_start_identity"] == runner_start
    assert immutability["runner_end_identity"] == runner_changed
    assert immutability["runner_identity_equal"] is False


@pytest.mark.parametrize(
    "attack",
    ("wrong_jurisdiction", "poison_after_seal_install"),
)
def test_run_seal_rejects_malformed_receipt_or_post_install_poison(
    tmp_path,
    monkeypatch,
    attack,
):
    evidence_root = tmp_path / "evidence"
    state_identity = _test_source_software_identity("9")
    pending_path = evidence_root / "MN" / (
        "mn-adversarial" + refresh_state_laws_corpus.PENDING_NORMALIZED_RECEIPT_SUFFIX
    )

    async def _fake_scrape_state_laws(**kwargs):
        await kwargs["state_completion_callback"](
            _quiescent_state_result(
                {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "statutes_count": 1,
                    "statute_data": {
                        "state_code": "MN",
                        "state_name": "Minnesota",
                        "statutes": _normalized_minnesota_statutes(count=1),
                    },
                    "acquisition_evidence": {
                        "enabled": True,
                        "parser_name": "MinnesotaAdversarialSealTest",
                    },
                }
            )
        )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

    def _close_pending_receipt(**kwargs):
        materialization = kwargs["materialization_result"]
        canonical_path = Path(materialization["jsonld_path"])
        canonical_sha256 = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(
            json.dumps(
                {
                    "jurisdiction": (
                        "XX" if attack == "wrong_jurisdiction" else "MN"
                    ),
                    "source_software_version": state_identity,
                    "payload": {
                        "requires_verified_transport_binding": False,
                        "verified_transport_receipts": [],
                        "verified_transport_receipts_trusted": False,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return (
            {
                "aggregate": {
                    "status": "closed_pending_run_seal",
                    "normalized_source_receipt_path": str(pending_path),
                    "canonical_jsonld_sha256": canonical_sha256,
                    "canonical_jsonld_row_count": 1,
                    "authorizing_for_publication": False,
                }
            },
            "",
        )

    class _TypedReceipt:
        @staticmethod
        def from_mapping(payload):
            return type(
                "Receipt",
                (),
                {
                    "jurisdiction": str(payload.get("jurisdiction") or ""),
                    "release_point": hashlib.sha256(b"release").hexdigest(),
                    "relative_path": "STATE-MN.jsonld",
                },
            )()

    def _normalize_receipt(_receipt, **kwargs):
        return type(
            "NormalizedReceipt",
            (),
            {
                "admission_eligible": True,
                "qualification_reasons": (),
                "input_sha256": hashlib.sha256(kwargs["input_bytes"]).hexdigest(),
                "input_row_count": 1,
            },
        )()

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_registered_state_source_software_version",
        lambda state_code: state_identity,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_close_incremental_state_acquisition_aggregate",
        _close_pending_receipt,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "SourceReceiptRecord",
        _TypedReceipt,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "normalize_source_receipt",
        _normalize_receipt,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": 1,
        },
    )
    if attack == "poison_after_seal_install":
        real_atomic_write_bytes = refresh_state_laws_corpus.atomic_write_bytes

        def _write_then_poison(path, payload):
            real_atomic_write_bytes(path, payload)
            if str(path).endswith(refresh_state_laws_corpus.RUN_SEAL_SUFFIX):
                poison = (
                    evidence_root
                    / refresh_state_laws_corpus.NONQUIESCENT_EVIDENCE_MARKER
                )
                poison.write_text(
                    json.dumps({"permanently_nonauthorizing": True}),
                    encoding="utf-8",
                )

        monkeypatch.setattr(
            refresh_state_laws_corpus,
            "atomic_write_bytes",
            _write_then_poison,
        )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(
                tmp_path,
                acquisition_evidence_root=str(evidence_root),
            )
        )
    )

    assert result["run_seal"]["authorizing_for_publication"] is False
    assert (
        result["acquisition_evidence"]["authorizing_for_publication"]
        is False
    )
    assert list(
        evidence_root.rglob(f"*{refresh_state_laws_corpus.RUN_SEAL_SUFFIX}")
    ) == []
    in_progress = evidence_root / refresh_state_laws_corpus.IN_PROGRESS_EVIDENCE_MARKER
    assert in_progress.is_file()
    if attack == "wrong_jurisdiction":
        assert result["run_seal"]["status"] == "not_issued"
        assert pending_path.is_file()
        assert "jurisdiction differs" in json.dumps(result)
    else:
        assert result["run_seal"]["status"] == "error"
        assert (
            evidence_root / refresh_state_laws_corpus.NONQUIESCENT_EVIDENCE_MARKER
        ).is_file()
        assert "poison appeared after seal install" in json.dumps(result)


def test_nonquiescent_worker_permanently_blocks_receipts_seal_and_root_reuse(
    tmp_path,
    monkeypatch,
):
    evidence_root = tmp_path / "evidence"
    scrape_calls = 0
    stable_identity = _test_source_software_identity("e")

    async def _fake_scrape_state_laws(**kwargs):
        nonlocal scrape_calls
        scrape_calls += 1
        await kwargs["state_completion_callback"](
            {
                "state_code": "MN",
                "state_name": "Minnesota",
                "statutes_count": 1,
                "error": "timed out while daemon remained live",
                "worker_quiescence": {
                    "attested": True,
                    "quiescent": False,
                    "completion_mode": "timeout_worker_still_live",
                    "worker_name": "state-scrape-MN-attempt-1",
                },
                "statute_data": {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "statutes": _normalized_minnesota_statutes(count=1),
                },
            }
        )
        return {
            "status": "partial_success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": ["MN"]}},
        }

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_registered_state_source_software_version",
        lambda state_code: stable_identity,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": [],
            "state_count": 0,
            "missing_jsonld_states": ["MN"],
            "combined_row_count": 0,
        },
    )
    args = _incremental_materialization_args(
        tmp_path,
        acquisition_evidence_root=str(evidence_root),
        timeout_recovery_rounds=3,
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(args)
    )

    assert result["status"] == "failed_worker_nonquiescence"
    assert scrape_calls == 1
    assert result["run_seal"]["status"] == "not_issued"
    assert result["run_seal"]["authorizing_for_publication"] is False
    marker_path = evidence_root / refresh_state_laws_corpus.NONQUIESCENT_EVIDENCE_MARKER
    assert marker_path.is_file()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["permanently_nonauthorizing"] is True
    assert marker["state_code"] == "MN"
    assert list(evidence_root.rglob("*.normalized.json")) == []
    assert list(evidence_root.rglob(f"*{refresh_state_laws_corpus.RUN_SEAL_SUFFIX}")) == []

    rejected = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(args)
    )
    assert rejected["status"] == "failed_preflight"
    assert rejected["reason"] == "permanently_nonauthorizing_evidence_root"
    assert scrape_calls == 1


def test_source_immutability_marker_is_first_writer_wins_and_nofollow(tmp_path):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()

    marker_path = (
        refresh_state_laws_corpus
        ._write_source_software_immutability_evidence_marker(
            evidence_root,
            run_id="first-run",
            failure_reasons={"PA": "first verified failure"},
        )
    )
    first_bytes = marker_path.read_bytes()

    returned_path = (
        refresh_state_laws_corpus
        ._write_source_software_immutability_evidence_marker(
            evidence_root,
            run_id="second-run",
            failure_reasons={"MN": "must not replace first evidence"},
        )
    )

    assert returned_path == marker_path
    assert marker_path.read_bytes() == first_bytes
    assert json.loads(first_bytes)["run_id"] == "first-run"

    unsafe_root = tmp_path / "unsafe-evidence"
    unsafe_root.mkdir()
    unsafe_target = tmp_path / "outside-marker"
    unsafe_marker = (
        unsafe_root / refresh_state_laws_corpus.NONQUIESCENT_EVIDENCE_MARKER
    )
    unsafe_marker.symlink_to(unsafe_target)
    with pytest.raises(RuntimeError, match="exists but is unsafe"):
        refresh_state_laws_corpus._write_source_software_immutability_evidence_marker(
            unsafe_root,
            run_id="unsafe-run",
            failure_reasons={"PA": "must not follow marker symlink"},
        )
    assert not unsafe_target.exists()


def test_source_software_drift_blocks_state_before_materialization(
    tmp_path,
    monkeypatch,
):
    statutes = _normalized_minnesota_statutes(count=1)
    start_identity = _test_source_software_identity("1")
    changed_identity = _test_source_software_identity("2")
    observations = 0

    def _changing_source_identity(state_code):
        nonlocal observations
        assert state_code == "MN"
        observations += 1
        return start_identity if observations == 1 else changed_identity

    async def _fake_scrape_state_laws(**kwargs):
        await kwargs["state_completion_callback"](
            {
                "state_code": "MN",
                "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                "state_name": "Minnesota",
                "statutes_count": len(statutes),
                "statute_data": {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "statutes": statutes,
                },
            }
        )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

    def _forbid_materialization(**kwargs):
        raise AssertionError("drifted source must be blocked before materialization")

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_registered_state_source_software_version",
        _changing_source_identity,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_materialize_completed_state_locally",
        _forbid_materialization,
    )
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

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(tmp_path)
        )
    )

    assert result["status"] == "failed_source_software_immutability"
    assert result["scrape_gap_states"] == ["MN"]
    assert result["incremental_state_materialization"]["success_count"] == 0
    assert result["incremental_state_materialization"]["error_count"] == 1
    identity = result["source_software_immutability"]
    assert identity["start_identities"] == {"MN": start_identity}
    assert identity["end_identities"] == {"MN": changed_identity}
    assert identity["identities_equal"] is False
    assert identity["failed_states"] == ["MN"]
    assert identity["authorizing_for_publication"] is False
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    state = progress["state_results"]["MN"]
    assert state["status"] == "error"
    assert state["authorizing_for_publication"] is False
    assert (
        state["acquisition_evidence"]["aggregate"]["status"]
        == "blocked_source_software_immutability"
    )
    assert not (tmp_path / "state_laws_jsonld" / "STATE-MN.jsonld").exists()


def test_late_source_software_drift_revokes_run_after_local_materialization(
    tmp_path,
    monkeypatch,
):
    statutes = _normalized_minnesota_statutes(count=1)
    start_identity = _test_source_software_identity("a")
    changed_identity = _test_source_software_identity("b")
    observations = 0

    def _late_changing_source_identity(state_code):
        nonlocal observations
        assert state_code == "MN"
        observations += 1
        return start_identity if observations <= 2 else changed_identity

    async def _fake_scrape_state_laws(**kwargs):
        await kwargs["state_completion_callback"](
            {
                "state_code": "MN",
                "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                "state_name": "Minnesota",
                "statutes_count": len(statutes),
                "statute_data": {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "statutes": statutes,
                },
            }
        )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_registered_state_source_software_version",
        _late_changing_source_identity,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": len(statutes),
        },
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(tmp_path)
        )
    )

    assert result["status"] == "failed_source_software_immutability"
    assert result["incremental_state_materialization"]["success_count"] == 1
    assert result["acquisition_evidence"]["authorizing_for_publication"] is False
    assert (
        result["acquisition_evidence"][
            "source_software_immutability_verified"
        ]
        is False
    )
    output_path = tmp_path / "state_laws_jsonld" / "STATE-MN.jsonld"
    assert output_path.is_file()
    local_receipt = json.loads(
        (
            tmp_path
            / "receipts"
            / "STATE-MN-incremental-local-materialization.json"
        ).read_text(encoding="utf-8")
    )
    assert local_receipt["authorizing_for_publication"] is False
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    assert progress["state_results"]["MN"]["status"] == "error"
    assert (
        progress["source_software_immutability"]["final_state_checks"]["MN"]
        ["identities_equal"]
        is False
    )


def test_source_drift_after_materialization_blocks_acquisition_authorization(
    tmp_path,
    monkeypatch,
):
    statutes = _normalized_minnesota_statutes(count=1)
    start_identity = _test_source_software_identity("c")
    changed_identity = _test_source_software_identity("d")
    observations = 0
    aggregate_close_called = False

    def _changing_after_materialization(state_code):
        nonlocal observations
        assert state_code == "MN"
        observations += 1
        return start_identity if observations <= 2 else changed_identity

    async def _fake_scrape_state_laws(**kwargs):
        await kwargs["state_completion_callback"](
            {
                "state_code": "MN",
                "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                "state_name": "Minnesota",
                "statutes_count": len(statutes),
                "statute_data": {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "statutes": statutes,
                },
                "acquisition_evidence": {
                    "enabled": True,
                    "parser_name": "MinnesotaTestParser",
                },
            }
        )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

    def _forbid_aggregate_close(**kwargs):
        nonlocal aggregate_close_called
        aggregate_close_called = True
        raise AssertionError("drifted source must not authorize aggregate closure")

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_registered_state_source_software_version",
        _changing_after_materialization,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_close_incremental_state_acquisition_aggregate",
        _forbid_aggregate_close,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": len(statutes),
        },
    )
    evidence_root = tmp_path / "evidence"
    args = _incremental_materialization_args(
        tmp_path,
        acquisition_evidence_root=str(evidence_root),
    )

    result = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(args)
    )

    assert result["status"] == "failed_source_software_immutability"
    assert aggregate_close_called is False
    assert result["incremental_state_materialization"]["success_count"] == 1
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    state_evidence = progress["state_results"]["MN"]["acquisition_evidence"]
    assert (
        state_evidence["aggregate"]["status"]
        == "blocked_source_software_immutability"
    )
    assert state_evidence["aggregate"]["authorizing_for_publication"] is False
    assert state_evidence["normalized_source_receipt_usable"] is False
    marker_path = (
        evidence_root / refresh_state_laws_corpus.NONQUIESCENT_EVIDENCE_MARKER
    )
    assert marker_path.is_file()
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["schema"] == (
        "ipfs_datasets_py.state_laws_refresh."
        "source_software_immutability_permanent_nonauthorization.v1"
    )
    assert marker["run_id"] == result["acquisition_run_id"]
    assert marker["failed_states"] == ["MN"]
    assert marker["authorizing_for_publication"] is False
    assert marker["permanently_nonauthorizing"] is True
    assert result["run_seal"]["status"] == "not_issued"
    assert list(
        evidence_root.rglob(f"*{refresh_state_laws_corpus.RUN_SEAL_SUFFIX}")
    ) == []

    rejected = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(args)
    )
    assert rejected["status"] == "failed_preflight"
    assert rejected["reason"] == "permanently_nonauthorizing_evidence_root"


def test_local_incremental_materialization_is_low_ram_nonpublishing_and_reusable(
    tmp_path,
    monkeypatch,
):
    statutes = _normalized_minnesota_statutes()
    observed = {}

    async def _fake_scrape_state_laws(**kwargs):
        observed["retain_state_data"] = kwargs["retain_state_data"]
        await kwargs["state_completion_callback"](
            {
                "state_code": "MN",
                "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                "state_name": "Minnesota",
                "statutes_count": len(statutes),
                "statute_data": {
                    "state_code": "MN",
                    "state_name": "Minnesota",
                    "normalized": True,
                    "statutes": statutes,
                },
            }
        )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

    def _forbid_network_publication(**kwargs):
        raise AssertionError("local materialization must not publish or synchronize")

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "scrape_state_laws",
        _fake_scrape_state_laws,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "build_state_laws_parquet_artifacts",
        lambda **kwargs: {
            "status": "success",
            "states": ["MN"],
            "state_count": 1,
            "missing_jsonld_states": [],
            "combined_row_count": len(statutes),
        },
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_publish_state_parquet_file",
        _forbid_network_publication,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_publish_parquet_dir",
        _forbid_network_publication,
    )
    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_build_and_sync_stale_local_state_shards_to_hf",
        _forbid_network_publication,
    )

    first = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(
            _incremental_materialization_args(tmp_path)
        )
    )

    assert observed["retain_state_data"] is False
    materialization = first["incremental_state_materialization"]
    assert materialization["enabled"] is True
    assert materialization["success_count"] == 1
    assert first["incremental_state_publish"]["enabled"] is False
    output_path = tmp_path / "state_laws_jsonld" / "STATE-MN.jsonld"
    body = output_path.read_bytes()
    assert len(body.splitlines()) == len(statutes)
    receipt_path = (
        tmp_path
        / "receipts"
        / "STATE-MN-incremental-local-materialization.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["output_artifact"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert receipt["output_artifact"]["row_count"] == len(statutes)
    assert receipt["network_access_during_materialization"] is False
    assert receipt["huggingface_access_during_materialization"] is False
    assert receipt["authorizing_for_publication"] is False
    assert receipt["authorizing_coordinator_reuse"] is False
    assert receipt["coordinator_reuse_requires_independent_receipt"] is True

    restart_args = _incremental_materialization_args(
        tmp_path,
        scrape=False,
        dry_run=True,
        skip_completed_states=True,
    )

    def _coordinate_without_independent_receipt(**kwargs):
        assert kwargs["body_bytes"] == {"MN": body}
        return coordinate_jurisdictions(
            receipts={},
            body_bytes=kwargs["body_bytes"],
        )

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "coordinate_default_prior_evidence",
        _coordinate_without_independent_receipt,
    )
    unverified_restart = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(restart_args)
    )
    assert unverified_restart["plan"]["skipped_completed_states"] == []
    assert unverified_restart["plan"]["states"] == ["MN"]

    independent_receipt = _receipt_bound_to_local_output("MN", body)

    def _coordinate(**kwargs):
        assert kwargs["body_bytes"] == {"MN": body}
        return coordinate_jurisdictions(
            receipts={"MN": independent_receipt},
            body_bytes=kwargs["body_bytes"],
        )

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "coordinate_default_prior_evidence",
        _coordinate,
    )
    restart = asyncio.run(
        refresh_state_laws_corpus.refresh_state_laws_corpus(restart_args)
    )
    assert restart["plan"]["skipped_completed_states"] == ["MN"]
    assert restart["plan"]["verified_prior_receipt_states"] == ["MN"]


def test_local_materialization_preserves_a_larger_valid_canonical_artifact(
    tmp_path,
):
    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    output_path = jsonld_dir / "STATE-MN.jsonld"
    prior = _coordinator_test_jsonld_body("MN", rows=5)
    output_path.write_bytes(prior)
    statutes = _normalized_minnesota_statutes(count=3)

    result = refresh_state_laws_corpus._materialize_completed_state_locally(
        state_code="MN",
        state_name="Minnesota",
        statute_data={
            "state_code": "MN",
            "state_name": "Minnesota",
            "statutes": statutes,
        },
        statutes_count=len(statutes),
        output_root=tmp_path,
        jsonld_dir=jsonld_dir,
        full_corpus_requested=False,
        max_statutes=len(statutes),
    )

    assert output_path.read_bytes() == prior
    assert result["artifact_disposition"] == "preserved_larger_prior_artifact"
    assert result["row_count"] == 5
    assert result["callback_row_count"] == 3
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["artifact_disposition"] == "preserved_larger_prior_artifact"
    assert receipt["callback_artifact"]["row_count"] == 3
    assert receipt["callback_artifact"]["installed_as_canonical"] is False
    assert receipt["output_artifact"]["row_count"] == 5
    assert receipt["output_artifact"]["sha256"] == hashlib.sha256(prior).hexdigest()
    assert receipt["authorizing_coordinator_reuse"] is False


def test_atomic_local_materialization_preserves_prior_output_on_writer_failure(
    tmp_path,
    monkeypatch,
):
    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    output_path = jsonld_dir / "STATE-MN.jsonld"
    prior = b'{"identifier":"MN-prior","text":"prior verified output"}\n'
    output_path.write_bytes(prior)

    def _failing_writer(_blocks, staged_dir):
        (staged_dir / "STATE-MN.jsonld").write_bytes(b"partial")
        raise OSError("simulated local write failure")

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "_write_state_jsonld_files",
        _failing_writer,
    )
    statutes = _normalized_minnesota_statutes(count=3)

    with pytest.raises(OSError, match="simulated local write failure"):
        refresh_state_laws_corpus._materialize_completed_state_locally(
            state_code="MN",
            state_name="Minnesota",
            statute_data={
                "state_code": "MN",
                "state_name": "Minnesota",
                "statutes": statutes,
            },
            statutes_count=len(statutes),
            output_root=tmp_path,
            jsonld_dir=jsonld_dir,
            full_corpus_requested=True,
            max_statutes=None,
        )

    assert output_path.read_bytes() == prior
    assert not list(jsonld_dir.glob(".state-laws-mn-incremental-*"))
    assert not (
        tmp_path
        / "receipts"
        / "STATE-MN-incremental-local-materialization.json"
    ).exists()


def test_refresh_rejects_receipt_when_local_output_bytes_drift(
    tmp_path,
    monkeypatch,
):
    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    admitted_body = b'{"identifier":"MN-1","text":"official statute"}\n'
    local_body = b'{"identifier":"MN-1","text":"tampered statute"}\n'
    (jsonld_dir / "STATE-MN.jsonld").write_bytes(local_body)
    receipt = _receipt_bound_to_local_output("MN", admitted_body)
    registry_path = tmp_path / "state_laws_completed_states.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": "ipfs_datasets_py.state_laws_refresh.completed_states.v1",
                "states": {"MN": {"status": "success", "statutes_count": 8}},
            }
        ),
        encoding="utf-8",
    )

    def _coordinate(**kwargs):
        return coordinate_jurisdictions(
            receipts={"MN": receipt},
            body_bytes=kwargs["body_bytes"],
        )

    monkeypatch.setattr(
        refresh_state_laws_corpus,
        "coordinate_default_prior_evidence",
        _coordinate,
    )
    args = argparse.Namespace(
        states="MN",
        include_dc=False,
        output_root=str(tmp_path),
        jsonld_dir=str(jsonld_dir),
        parquet_dir="",
        scrape=False,
        max_statutes=0,
        rate_limit_delay=0.0,
        parallel_workers=1,
        per_state_retry_attempts=0,
        per_state_timeout_seconds=1.0,
        strict_full_text=False,
        min_full_text_chars=1,
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
        persist_completed_states_registry=False,
    )

    result = asyncio.run(refresh_state_laws_corpus.refresh_state_laws_corpus(args))

    assert result["plan"]["states"] == ["MN"]
    assert result["plan"]["skipped_completed_states"] == []
    assert result["plan"]["verified_prior_receipt_states"] == []
    assert result["plan"]["registry_only_completion_states"] == ["MN"]
    assert result["plan"]["acquisition_lease_actions"]["MN"] != ACTION_REUSE


def test_refresh_state_laws_corpus_persists_completed_states_registry(tmp_path, monkeypatch):
    registry_path = tmp_path / "state_laws_completed_states.json"

    async def _fake_scrape_state_laws(**kwargs):
        callback = kwargs["state_completion_callback"]
        await callback(
            {
                "state_code": "WI",
                "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
                "state_name": "Wisconsin",
                "statutes_count": 1,
                "statute_data": {
                    "state_code": "WI",
                    "state_name": "Wisconsin",
                    "statutes": [
                        {
                            "statute_id": "WI-1",
                            "section_number": "1.01",
                            "section_name": "Official short provision",
                            "full_text": "A person shall comply with this section.",
                            "source_url": "https://docs.legis.wisconsin.gov/statutes/statutes/1/01",
                        }
                    ],
                },
            }
        )
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

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

    assert result["status"] == "partial_success"
    assert registry_path.exists()
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    wi_entry = registry.get("states", {}).get("WI", {})
    assert wi_entry.get("status") == "success"
    assert int(wi_entry.get("statutes_count") or 0) == 1


def test_refresh_state_laws_corpus_does_not_promote_unclosed_full_corpus_timeout(
    tmp_path, monkeypatch
):
    registry_path = tmp_path / "state_laws_completed_states.json"

    async def _fake_scrape_state_laws(**kwargs):
        callback = kwargs["state_completion_callback"]
        await callback(
            {
                "state_code": "RI",
                "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
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
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

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

    assert result["status"] == "failed_acquisition_run_finalization"
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    ri_progress = progress.get("state_results", {}).get("RI", {})
    assert ri_progress.get("status") == "error"
    assert ri_progress.get("completion_mode") is None
    assert ri_progress.get("timeout_promoted_to_success") is not True
    assert ri_progress.get("timeout_classification") == "timeout_with_no_detectable_remaining_work"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    ri_registry = registry.get("states", {}).get("RI", {})
    assert ri_registry == {}


def test_refresh_state_laws_corpus_does_not_promote_timeout_success_for_bounded_probe(
    tmp_path, monkeypatch
):
    registry_path = tmp_path / "state_laws_completed_states.json"

    async def _fake_scrape_state_laws(**kwargs):
        callback = kwargs["state_completion_callback"]
        await callback(
            {
                "state_code": "MS",
                "worker_quiescence": _quiescent_state_result({})["worker_quiescence"],
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
        return {
            "status": "success",
            "data": [],
            "metadata": {"coverage_summary": {"coverage_gap_states": []}},
        }

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

    assert result["status"] == "failed_acquisition_run_finalization"
    progress = json.loads(Path(result["progress_path"]).read_text(encoding="utf-8"))
    ms_progress = progress.get("state_results", {}).get("MS", {})
    assert ms_progress.get("status") == "error"
    assert ms_progress.get("timeout_promoted_to_success") is not True
    assert ms_progress.get("timeout_classification") == "timeout_with_no_detectable_remaining_work"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    ms_registry = registry.get("states", {}).get("MS", {})
    assert ms_registry == {}


def test_refresh_registry_success_and_zero_rows_do_not_skip_without_receipts(tmp_path):
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
    assert result["plan"]["states"] == ["MN", "NH"]
    assert result["plan"]["skipped_completed_states"] == []
    assert result["plan"]["registry_completed_state_candidates"] == ["MN"]
    assert result["plan"]["registry_only_completion_states"] == ["MN"]


def test_refresh_registry_zero_candidate_still_requires_verified_receipt(
    tmp_path, monkeypatch
):
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
    assert result["plan"]["states"] == ["NH"]
    assert result["plan"]["skipped_completed_states"] == []
    assert result["plan"]["registry_completed_state_candidates"] == ["NH"]
    assert result["plan"]["registry_only_completion_states"] == ["NH"]


def test_all_state_jurisdictions_have_registered_scrapers():
    registered = set(StateScraperRegistry.get_all_registered_states())

    assert set(US_STATES) - registered == set()
    assert len(registered) == len(US_STATES)


def test_strict_acquisition_does_not_reconcile_parser_checkpoint_to_success(tmp_path):
    checkpoint_dir = tmp_path / "partial_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "STATE-TX-partial.json").write_text(
        json.dumps(
            {
                "state_code": "TX",
                "updated_at": "2026-08-26T00:00:00+00:00",
                "stage_label": "scrape_all:complete",
                "statutes_count": 1,
                "progress": {"codes_completed": 30, "codes_total": 30},
                "statutes": [{"statute_id": "Texas Code § 1"}],
            }
        ),
        encoding="utf-8",
    )
    initial_progress = {
        "state_results": {
            "TX": {
                "state_code": "TX",
                "status": "error",
                "statutes_count": 1,
                "error": "TX exact closure failed",
            }
        }
    }
    strict_progress = json.loads(json.dumps(initial_progress))
    ordinary_progress = json.loads(json.dumps(initial_progress))

    strict_result = (
        refresh_state_laws_corpus._reconcile_state_results_from_partial_checkpoints(
            progress_state=strict_progress,
            checkpoint_dir=checkpoint_dir,
            strict_acquisition_evidence=True,
        )
    )
    ordinary_result = (
        refresh_state_laws_corpus._reconcile_state_results_from_partial_checkpoints(
            progress_state=ordinary_progress,
            checkpoint_dir=checkpoint_dir,
        )
    )

    assert strict_result == {
        "reconciled_states": [],
        "checked_state_count": 0,
        "reconciled_count": 0,
        "disabled_reason": "strict_acquisition_requires_lifecycle_completion",
    }
    assert strict_progress["state_results"]["TX"]["status"] == "error"
    assert strict_progress["state_results"]["TX"]["error"] == "TX exact closure failed"
    assert ordinary_result["reconciled_count"] == 0
    assert ordinary_result["rejected_states"] == {
        "TX": "missing_source_software_run_attestation"
    }
    assert ordinary_progress["state_results"]["TX"]["status"] == "error"
    assert ordinary_progress["state_results"]["TX"]["error"] == "TX exact closure failed"
