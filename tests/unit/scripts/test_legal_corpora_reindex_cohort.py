"""Unit tests for LCR-007 resumable isolated cohort runner and certifier."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_module(filename: str, module_name: str):
    path = _repo_root() / "scripts" / "ops" / "legal_data" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_module(
        "run_legal_corpora_reindex_cohort.py",
        "run_legal_corpora_reindex_cohort_lcr007",
    )


@pytest.fixture(scope="module")
def certifier():
    return _load_module(
        "certify_state_laws_cohort.py",
        "certify_state_laws_cohort_lcr007",
    )


@pytest.fixture(scope="module")
def refresh():
    return _load_module(
        "refresh_state_laws_corpus.py",
        "refresh_state_laws_corpus_lcr007",
    )


@pytest.fixture(scope="module")
def check_coverage():
    return _load_module(
        "check_state_law_coverage.py",
        "check_state_law_coverage_lcr007",
    )


@pytest.fixture(scope="module")
def report_gaps():
    return _load_module(
        "report_state_law_corpus_gaps.py",
        "report_state_law_corpus_gaps_lcr007",
    )


@pytest.fixture(scope="module")
def scraper():
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_scraper

    return state_laws_scraper


# ---------------------------------------------------------------------------
# Cohort map / exact set including DC
# ---------------------------------------------------------------------------


def test_cohort_map_covers_exact_51_including_dc(runner) -> None:
    union = runner.all_cohort_states()
    assert len(union) == 51
    assert "DC" in union
    assert set(union) == set(runner.CANONICAL_JURISDICTIONS)
    assert runner.COHORT_JURISDICTIONS["M"] == ("WI", "WY", "DC")
    assert runner.cohort_states("A") == ["AL", "AK", "AZ", "AR"]


def test_unknown_cohort_rejected(runner) -> None:
    with pytest.raises(runner.CohortRunnerError, match="unknown cohort"):
        runner.cohort_states("Z")


# ---------------------------------------------------------------------------
# Interrupt / resume
# ---------------------------------------------------------------------------


def test_interrupt_resume_skips_completed_states(runner, tmp_path) -> None:
    root = runner.isolate_run_root(
        base_root=tmp_path, cohort="A", run_id="resume-test"
    )
    result = runner.run_fixture_interrupt_resume(cohort="A", run_root=root)
    assert result["status"] == "success"
    assert result["completed_before_interrupt"] == ["AL", "AK"]
    assert result["skipped_on_resume"] == ["AL", "AK"]
    assert result["ran_on_resume"] == ["AZ", "AR"]
    # Checkpoints exist for all four states.
    for state in ("AL", "AK", "AZ", "AR"):
        ck = root / "checkpoints" / f"STATE-{state}.json"
        assert ck.is_file()
        payload = json.loads(ck.read_text(encoding="utf-8"))
        assert payload["status"] == "success"
        assert payload["promote_partial_success"] is False


def test_run_cohort_resume_from_checkpoints(runner, tmp_path) -> None:
    root = runner.isolate_run_root(
        base_root=tmp_path, cohort="A", run_id="live-resume"
    )
    first = runner.run_cohort(cohort="A", run_root=root, resume=False)
    assert first["status"] == "success"
    # Mark AZ as needing redo by deleting its checkpoint; keep AL success.
    (root / "checkpoints" / "STATE-AZ.json").unlink()
    (root / "checkpoints" / "STATE-AR.json").unlink()
    second = runner.run_cohort(cohort="A", run_root=root, resume=True)
    assert second["status"] == "success"
    assert second["state_results"]["AL"].get("skipped_completed") is True
    assert second["state_results"]["AK"].get("skipped_completed") is True
    assert second["state_results"]["AZ"].get("skipped_completed") is False


# ---------------------------------------------------------------------------
# Partial-success promotion
# ---------------------------------------------------------------------------


def test_partial_success_never_promoted(runner) -> None:
    assert runner.promote_state_status("partial_success") == "partial_success"
    assert runner.promote_state_status("partial_success") != "success"
    assert not runner.cohort_success_allowed(
        {"GA": {"status": "partial_success"}}
    )
    assert not runner.cohort_success_allowed(
        {"GA": {"status": "success", "partial_checkpoint_promoted": True}}
    )
    assert not runner.cohort_success_allowed(
        {"GA": {"status": "success", "timeout_promoted_to_success": True}}
    )
    stale = runner.detect_stale_checkpoint(
        {
            "schema": runner.CHECKPOINT_SCHEMA,
            "status": "partial_success",
            "work_fingerprint": "abc",
            "promote_partial_success": True,
            "updated_at": runner.utc_now_iso(),
        },
        expected_fingerprint="abc",
    )
    assert stale == "partial_success_promotion_blocked"


# ---------------------------------------------------------------------------
# No shared combined overwrite / no production upload
# ---------------------------------------------------------------------------


def test_cohort_run_never_writes_shared_combined_or_uploads(runner, tmp_path) -> None:
    root = runner.isolate_run_root(
        base_root=tmp_path, cohort="A", run_id="no-combined"
    )
    result = runner.run_cohort(cohort="A", run_root=root, resume=False)
    assert result["production_upload"] is False
    assert result["shared_combined_write"] is False
    # Shared production combined filename must not appear under the base.
    combined_hits = list(tmp_path.rglob("state_laws_all_states.parquet"))
    assert combined_hits == []
    receipt = json.loads(Path(result["cohort_receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["production_upload"] is False
    assert receipt["shared_combined_write"] is False


def test_refresh_skips_shared_combined_for_subset(refresh, tmp_path) -> None:
    jsonld_dir = tmp_path / "jsonld"
    parquet_dir = tmp_path / "parquet"
    jsonld_dir.mkdir()
    parquet_dir.mkdir()
    (jsonld_dir / "STATE-MN.jsonld").write_text(
        json.dumps(
            {
                "@type": "Legislation",
                "identifier": "Minn. Stat. § 1.1",
                "name": "Test",
                "text": "Body text for MN fixture.",
                "sourceUrl": "https://www.revisor.mn.gov/statutes/cite/1.1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = refresh.build_state_laws_parquet_artifacts(
        states=["MN"],
        jsonld_dir=jsonld_dir,
        parquet_dir=parquet_dir,
        merge_existing_local=False,
        merge_hf_existing=False,
    )
    assert result["exact_production_jurisdiction_set"] is False
    assert result["combined_written"] is False
    assert not (parquet_dir / "state_laws_all_states.parquet").exists()
    # Per-state shard is still written.
    assert (parquet_dir / "STATE-MN.parquet").exists()


# ---------------------------------------------------------------------------
# Logical-key current / history handling
# ---------------------------------------------------------------------------


def test_logical_key_current_history_merge(runner) -> None:
    state = "MN"
    gen1 = runner._fixture_state_rows(state, generation=1)
    gen2 = runner._fixture_state_rows(state, generation=2)
    for old, new in zip(gen1, gen2):
        new["legal_id"] = old["legal_id"]
        new["source_id"] = old["source_id"]
        new["identifier"] = old["identifier"]
    merge = runner.merge_logical_current_history(gen1, gen2, state=state)
    assert len(merge["current_rows"]) == 2
    assert merge["history_keys"]
    for row in merge["current_rows"]:
        assert "g2" in str(row["ipfs_cid"])


def test_refresh_logical_merge_retains_history(refresh) -> None:
    existing = [
        {
            "state_code": "MN",
            "identifier": "Minn. Stat. § 518.17",
            "source_id": "mn-518-17",
            "ipfs_cid": "cid-old",
            "text": "old body",
        }
    ]
    new_rows = [
        {
            "state_code": "MN",
            "identifier": "Minn. Stat. § 518.17",
            "source_id": "mn-518-17",
            "ipfs_cid": "cid-new",
            "text": "new body",
        }
    ]
    merged = refresh.merge_canonical_rows(existing, new_rows)
    assert len(merged) == 1
    assert merged[0]["ipfs_cid"] == "cid-new"
    history = merged[0].get("logical_history") or []
    assert any(item.get("ipfs_cid") == "cid-old" for item in history)


# ---------------------------------------------------------------------------
# Stale-work detection
# ---------------------------------------------------------------------------


def test_stale_work_fingerprint_mismatch(runner) -> None:
    config_a = {"max_statutes": None, "strict_full_text": True, "allow_justia_fallback": False}
    config_b = {"max_statutes": 5, "strict_full_text": True, "allow_justia_fallback": False}
    fp_a = runner.work_fingerprint(cohort="K", state="TX", config=config_a)
    fp_b = runner.work_fingerprint(cohort="K", state="TX", config=config_b)
    assert fp_a != fp_b
    reason = runner.detect_stale_checkpoint(
        {
            "schema": runner.CHECKPOINT_SCHEMA,
            "status": "success",
            "work_fingerprint": fp_a,
            "updated_at": runner.utc_now_iso(),
        },
        expected_fingerprint=fp_b,
    )
    assert reason == "work_fingerprint_mismatch"


def test_stale_success_not_resumed(runner, tmp_path) -> None:
    root = runner.isolate_run_root(
        base_root=tmp_path, cohort="A", run_id="stale-success"
    )
    # Write a success checkpoint with a wrong fingerprint.
    ck = root / "checkpoints" / "STATE-AL.json"
    runner.write_state_checkpoint(
        ck,
        cohort="A",
        state="AL",
        status="success",
        fingerprint="stale-fingerprint",
        payload={"statutes_count": 2},
    )
    result = runner.run_cohort(cohort="A", run_root=root, resume=True)
    assert result["status"] == "success"
    # AL must be re-run (not skipped) because fingerprint is stale.
    assert result["state_results"]["AL"].get("skipped_completed") is False


# ---------------------------------------------------------------------------
# Safe receipt redaction
# ---------------------------------------------------------------------------


def test_receipt_redaction_strips_secrets_and_paths(runner) -> None:
    dirty = {
        "hf_token": "hf_SUPERSECRETTOKENVALUE001",
        "authorization": "Bearer sk-abc123secretvalue999",
        "cookie": "session=abc",
        "local_path": "/home/operator/.cache/secret/CA.json",
        "source_url": "https://leginfo.legislature.ca.gov/codes/1",
        "nested": {"api_key": "xyz", "ok": True},
    }
    clean = runner.redact_receipt(dirty)
    serialized = json.dumps(clean)
    for needle in (
        "hf_SUPERSECRET",
        "sk-abc123",
        "session=abc",
        "/home/operator",
        "Bearer ",
    ):
        assert needle not in serialized
    assert clean["hf_token"] == "[REDACTED]"
    assert clean["source_url"] == dirty["source_url"]


# ---------------------------------------------------------------------------
# Legacy production entry points reject subset release
# ---------------------------------------------------------------------------


def test_all_legacy_entry_points_reject_subset_release(
    refresh, check_coverage, report_gaps, scraper
) -> None:
    subset = ["AL", "AK", "AZ", "AR"]
    for label, mod in (
        ("refresh", refresh),
        ("check", check_coverage),
        ("report", report_gaps),
        ("scraper", scraper),
    ):
        with pytest.raises(Exception) as excinfo:
            mod.reject_subset_release(subset)
        message = str(excinfo.value).lower()
        assert "subset" in message or "51" in message, label


def test_reject_subset_accepts_exact_51(refresh, scraper) -> None:
    exact = list(refresh.STATE_CODES_51)
    assert refresh.reject_subset_release(exact) == exact
    assert set(scraper.reject_subset_release(list(scraper.US_STATES.keys()))) == set(
        scraper.US_STATES
    )


def test_refresh_all_includes_dc(refresh) -> None:
    states = refresh._normalize_states("all", include_dc=False)
    assert len(states) == 51
    assert "DC" in states


def test_refresh_publish_rejects_subset(refresh, tmp_path, monkeypatch) -> None:
    import argparse
    import asyncio

    monkeypatch.setattr(refresh, "_resolve_hf_token", lambda token=None: "test-token")

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
        timeout_recovery_rounds=0,
        timeout_recovery_timeout_multiplier=1.5,
        timeout_recovery_timeout_cap_seconds=0.0,
        timeout_recovery_retry_attempts=1,
        timeout_recovery_parallel_workers=0,
        strict_full_text=False,
        min_full_text_chars=300,
        no_hydrate_statute_text=False,
        progress_heartbeat_seconds=0.0,
        allow_justia_fallback=False,
        no_merge_existing_local=False,
        merge_hf_existing=False,
        publish_to_hf=True,
        allow_incomplete_publish=False,
        skip_full_corpus_guard_audit=True,
        completed_states_registry="",
        completed_states_baseline="",
        load_completed_states_baseline=False,
        skip_completed_states=False,
        persist_completed_states_registry=False,
        startup_stale_sync=False,
        incremental_state_publish=False,
        repo_id="justicedao/ipfs_state_laws",
        hf_token="",
        create_repo=False,
        verify=False,
        commit_message="test",
        dry_run=False,
        json=True,
    )
    result = asyncio.run(refresh.refresh_state_laws_corpus(args))
    assert result["status"] == "partial_success"
    assert result["publish"]["status"] == "rejected"
    assert result["publish"]["reason"] == "subset_release_rejected"


def test_scraper_subset_not_full_corpus(scraper) -> None:
    summary = scraper._compute_coverage_summary(
        selected_states=["AL", "AK"],
        scraped_statutes=[
            {"state_code": "AL", "statutes": [{"x": 1}], "statutes_count": 1},
            {"state_code": "AK", "statutes": [{"x": 1}], "statutes_count": 1},
        ],
        errors=[],
    )
    assert summary["full_coverage"] is True  # requested scope closed
    assert summary["full_corpus_coverage"] is False
    assert summary["coverage_scope"] == "requested_scope"
    assert summary["production_release_eligible"] is False
    assert summary["includes_dc"] is False


def test_scraper_exact_51_is_full_corpus(scraper) -> None:
    states = list(scraper.US_STATES.keys())
    blocks = [
        {"state_code": code, "statutes": [{"x": 1}], "statutes_count": 1}
        for code in states
    ]
    summary = scraper._compute_coverage_summary(
        selected_states=states,
        scraped_statutes=blocks,
        errors=[],
    )
    assert summary["full_corpus_coverage"] is True
    assert summary["coverage_scope"] == "full_corpus"
    assert summary["production_release_eligible"] is True
    assert summary["includes_dc"] is True


def test_report_gaps_includes_dc(report_gaps) -> None:
    assert "DC" in report_gaps.STATES_51
    assert len(report_gaps.STATES_51) == 51


def test_check_coverage_production_rejects_subset(check_coverage, tmp_path, monkeypatch) -> None:
    # Production flag with explicit subset states must fail closed.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_state_law_coverage.py",
            "--jsonld-dir",
            str(tmp_path),
            "--states",
            "AL,AK",
            "--production-release",
        ],
    )
    rc = check_coverage.main()
    assert rc == 1


# ---------------------------------------------------------------------------
# Fixture suite / CLI gates
# ---------------------------------------------------------------------------


def test_fixture_suite_passes(runner) -> None:
    report = runner.run_fixture_suite(cohort_filter="A")
    assert report["status"] == "pass", json.dumps(report, indent=2)
    assert report["fail_count"] == 0
    assert report["includes_dc"] is True
    kinds = {item["kind"] for item in report["results"]}
    for required in (
        "interrupt_resume",
        "exact_set",
        "partial_promotion",
        "combined_guard",
        "logical_merge",
        "stale_work",
        "redaction",
        "legacy_subset",
    ):
        assert required in kinds


def test_cli_fixture_only_check_cohort_a(runner) -> None:
    rc = runner.main(["--fixture-only", "--cohort", "A", "--check"])
    assert rc == 0


def test_certify_cohort_a_offline(certifier, runner) -> None:
    report = certifier.certify_cohorts(["A"], fixture_only=True, runner=runner)
    assert report["status"] == "pass", json.dumps(report, indent=2)
    assert report["includes_dc_in_map"] is True
    assert report["results"][0]["cohort"] == "A"
    assert report["results"][0]["status"] == "pass"


def test_certify_rejects_partial_receipt(certifier, runner) -> None:
    receipt = {
        "schema": runner.RECEIPT_SCHEMA,
        "cohort": "A",
        "states": ["AL", "AK", "AZ", "AR"],
        "state_results": {
            "AL": {"status": "success"},
            "AK": {"status": "success"},
            "AZ": {"status": "partial_success"},
            "AR": {"status": "success"},
        },
        "production_upload": False,
        "shared_combined_write": False,
    }
    result = certifier.certify_cohort_receipt(receipt, cohort="A", runner=runner)
    assert result["status"] == "fail"
    assert any("partial" in f or "AZ" in f for f in result["findings"])


def test_domain_schedule_no_duplicate_domains_per_wave(runner) -> None:
    states = runner.cohort_states("B")
    waves = runner.domain_schedule(states)
    flat = [s for wave in waves for s in wave]
    assert sorted(flat) == sorted(states)
    for wave in waves:
        domains = [runner.primary_domain(s) for s in wave]
        assert len(domains) == len(set(domains))


def test_isolate_run_root_creates_layout(runner, tmp_path) -> None:
    root = runner.isolate_run_root(base_root=tmp_path, cohort="M", run_id="layout")
    assert (root / "checkpoints").is_dir()
    assert (root / "receipts").is_dir()
    assert (root / "jsonld").is_dir()
    assert "cohorts" in root.parts
    assert "M" in root.parts
