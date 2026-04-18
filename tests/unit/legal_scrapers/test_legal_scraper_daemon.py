import json

import pytest

from ipfs_datasets_py.processors.legal_scrapers.legal_scraper_daemon import (
    AgenticCorpusDaemonConfig,
    BluebookDaemonConfig,
    CacheDaemonConfig,
    LegalScraperDaemon,
    LegalScraperDaemonConfig,
    StateRefreshDaemonConfig,
    _normalize_corpora,
    _normalize_states,
    config_from_args,
    build_arg_parser,
)


@pytest.mark.asyncio
async def test_legal_scraper_daemon_dry_run_writes_plan(tmp_path):
    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            states=["MN", "OR"],
            output_dir=str(tmp_path),
            dry_run=True,
        )
    )

    result = await daemon.run()

    assert result["status"] == "completed"
    latest = json.loads((tmp_path / "latest_cycle.json").read_text(encoding="utf-8"))
    assert latest["status"] == "dry_run"
    assert latest["plan"]["state_count"] == 2
    assert latest["plan"]["phases"]["bluebook"]["enabled"] is True


@pytest.mark.asyncio
async def test_legal_scraper_daemon_runs_bluebook_and_refresh_with_safe_publish_defaults(tmp_path):
    calls = {"bluebook": None, "refresh": None}

    class _FakeBluebookRun:
        def to_dict(self):
            return {"summary": {"recovery_count": 2, "recovery_publication": {"published_count": 0}}}

    async def _fake_bluebook_runner(**kwargs):
        calls["bluebook"] = kwargs
        return _FakeBluebookRun()

    async def _fake_refresh_runner(args):
        calls["refresh"] = args
        return {
            "status": "success",
            "build": {"combined_row_count": 10, "missing_jsonld_states": []},
            "publish": None,
        }

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            states=["MN"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(samples=3, seed_only=True),
            state_refresh=StateRefreshDaemonConfig(scrape=False, publish_to_hf=False, parallel_workers=7),
            agentic_corpora=AgenticCorpusDaemonConfig(enabled=False),
        ),
        bluebook_runner=_fake_bluebook_runner,
        state_refresh_runner=_fake_refresh_runner,
    )

    result = await daemon.run()
    latest = json.loads((tmp_path / "latest_cycle.json").read_text(encoding="utf-8"))

    assert latest["status"] == "success"
    assert latest["phases"]["bluebook"]["summary"]["recovery_count"] == 2
    assert calls["bluebook"]["sample_count"] == 3
    assert calls["bluebook"]["state_codes"] == ["MN"]
    assert calls["bluebook"]["publish_to_hf"] is False
    assert calls["bluebook"]["prefer_hf_corpora"] is False
    assert calls["bluebook"]["publish_merged_parquet_to_hf"] is False
    assert calls["refresh"].publish_to_hf is False
    assert calls["refresh"].parallel_workers == 7
    assert result["cycles"][0]["phases"]["state_refresh"]["build"]["combined_row_count"] == 10


@pytest.mark.asyncio
async def test_legal_scraper_daemon_passes_bluebook_hf_seeded_merge_controls(tmp_path):
    calls = {}

    class _FakeBluebookRun:
        def to_dict(self):
            return {
                "summary": {
                    "recovery_count": 3,
                    "merged_recovery_count": 3,
                    "recovery_merge": {"published_merged_count": 1},
                }
            }

    async def _fake_bluebook_runner(**kwargs):
        calls.update(kwargs)
        return _FakeBluebookRun()

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            states=["RI"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(
                samples=20,
                corpora=["state_admin_rules"],
                seed_from_corpora=True,
                seed_only=True,
                seed_examples_per_corpus=20,
                max_seed_examples_per_state=20,
                max_seed_examples_per_source=8,
                sampling_shuffle_seed=211,
                prefer_hf_corpora=True,
                primary_corpora_only=True,
                exact_state_partitions_only=True,
                merge_recovered_rows=True,
                publish_merged_parquet_to_hf=True,
            ),
            state_refresh=StateRefreshDaemonConfig(enabled=False),
            agentic_corpora=AgenticCorpusDaemonConfig(enabled=False),
        ),
        bluebook_runner=_fake_bluebook_runner,
    )

    await daemon.run()

    assert calls["corpus_keys"] == ["state_admin_rules"]
    assert calls["state_codes"] == ["RI"]
    assert calls["seed_from_corpora"] is True
    assert calls["seed_only"] is True
    assert calls["seed_examples_per_corpus"] == 20
    assert calls["max_seed_examples_per_state"] == 20
    assert calls["max_seed_examples_per_source"] == 8
    assert calls["sampling_shuffle_seed"] == 211
    assert calls["prefer_hf_corpora"] is True
    assert calls["primary_corpora_only"] is True
    assert calls["exact_state_partitions_only"] is True
    assert calls["merge_recovered_rows"] is True
    assert calls["hydrate_merge_from_hf"] is True
    assert calls["publish_merged_parquet_to_hf"] is True


@pytest.mark.asyncio
async def test_legal_scraper_daemon_writes_running_phase_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGAL_SCRAPER_DAEMON_HEARTBEAT_SECONDS", "0")
    observed = {}

    class _FakeBluebookRun:
        def to_dict(self):
            return {"summary": {"recovery_count": 0}}

    async def _fake_bluebook_runner(**kwargs):
        phase_path = tmp_path / "cycles" / "cycle_0001" / "bluebook_phase.json"
        observed["checkpoint"] = json.loads(phase_path.read_text(encoding="utf-8"))
        return _FakeBluebookRun()

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            states=["MN"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(samples=1),
            state_refresh=StateRefreshDaemonConfig(enabled=False),
            agentic_corpora=AgenticCorpusDaemonConfig(enabled=False),
        ),
        bluebook_runner=_fake_bluebook_runner,
    )

    await daemon.run()

    assert observed["checkpoint"]["status"] == "running"
    assert observed["checkpoint"]["phase"] == "bluebook"
    assert observed["checkpoint"]["heartbeat_count"] == 0


@pytest.mark.asyncio
async def test_legal_scraper_daemon_resumes_completed_phase(tmp_path):
    calls = {"bluebook": 0, "refresh": 0}

    class _FakeBluebookRun:
        def to_dict(self):
            return {"summary": {"recovery_count": 1}}

    async def _fake_bluebook_runner(**kwargs):
        calls["bluebook"] += 1
        return _FakeBluebookRun()

    async def _fake_refresh_runner(args):
        calls["refresh"] += 1
        return {"status": "success", "build": {"combined_row_count": 3}}

    config = LegalScraperDaemonConfig(
        states=["MN"],
        output_dir=str(tmp_path),
        bluebook=BluebookDaemonConfig(samples=1),
        state_refresh=StateRefreshDaemonConfig(scrape=False),
        agentic_corpora=AgenticCorpusDaemonConfig(enabled=False),
    )
    first = LegalScraperDaemon(
        config,
        bluebook_runner=_fake_bluebook_runner,
        state_refresh_runner=_fake_refresh_runner,
    )
    await first.run()

    second = LegalScraperDaemon(
        config,
        bluebook_runner=_fake_bluebook_runner,
        state_refresh_runner=_fake_refresh_runner,
    )
    result = await second.run()

    assert calls == {"bluebook": 1, "refresh": 1}
    assert result["cycles"][0]["phases"]["bluebook"]["resumed_from"].endswith("bluebook_phase.json")
    assert result["cycles"][0]["phases"]["state_refresh"]["resumed_from"].endswith("state_refresh_phase.json")


def test_legal_scraper_daemon_configures_fetch_and_search_cache_env(tmp_path, monkeypatch):
    monkeypatch.delenv("IPFS_DATASETS_SEARCH_CACHE_ENABLED", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_LEGAL_FETCH_CACHE_ENABLED", raising=False)

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            states=["MN"],
            output_dir=str(tmp_path / "daemon"),
            cache=CacheDaemonConfig(cache_dir=str(tmp_path / "cache"), mirror_to_ipfs=True),
        )
    )

    env = daemon.configure_cache_environment()

    assert env["IPFS_DATASETS_SEARCH_CACHE_ENABLED"] == "1"
    assert env["IPFS_DATASETS_LEGAL_FETCH_CACHE_ENABLED"] == "1"
    assert env["IPFS_DATASETS_SEARCH_CACHE_IPFS_MIRROR"] == "1"
    assert (tmp_path / "cache" / "search").exists()
    assert (tmp_path / "cache" / "fetch").exists()


@pytest.mark.asyncio
async def test_legal_scraper_daemon_runs_agentic_corpus_phase(tmp_path):
    calls = []

    async def _fake_agentic_runner(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "summary": {"corpus": kwargs["corpus"]}}

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            states=["CA"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(enabled=False),
            state_refresh=StateRefreshDaemonConfig(enabled=False),
            agentic_corpora=AgenticCorpusDaemonConfig(
                enabled=True,
                corpora=["state_laws", "state_admin_rules"],
            ),
        ),
        agentic_runner=_fake_agentic_runner,
    )

    result = await daemon.run()

    assert result["cycles"][0]["status"] == "success"
    assert [call["corpus"] for call in calls] == ["state_laws", "state_admin_rules"]
    assert calls[0]["states"] == ["CA"]


def test_legal_scraper_daemon_arg_config_keeps_publish_opt_in(tmp_path):
    args = build_arg_parser().parse_args(
        [
            "--states",
            "MN,OR",
            "--output-dir",
            str(tmp_path),
            "--bluebook-samples",
            "7",
            "--bluebook-seed-from-corpora",
            "--bluebook-seed-only",
            "--bluebook-seed-examples-per-corpus",
            "17",
            "--bluebook-max-seed-examples-per-state",
            "5",
            "--bluebook-max-seed-examples-per-source",
            "9",
            "--bluebook-sampling-shuffle-seed",
            "123",
            "--bluebook-prefer-hf-corpora",
            "--bluebook-primary-corpora-only",
            "--bluebook-exact-state-partitions-only",
            "--bluebook-merge-recovered-rows",
            "--bluebook-publish-merged-parquet-to-hf",
            "--state-refresh-scrape",
            "--parallel-workers",
            "8",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--cache-to-ipfs",
            "--enable-agentic-corpora",
            "--agentic-corpora",
            "laws,admin",
        ]
    )

    config = config_from_args(args)

    assert config.states == ["MN", "OR"]
    assert config.bluebook.samples == 7
    assert config.bluebook.seed_from_corpora is True
    assert config.bluebook.seed_only is True
    assert config.bluebook.seed_examples_per_corpus == 17
    assert config.bluebook.max_seed_examples_per_state == 5
    assert config.bluebook.max_seed_examples_per_source == 9
    assert config.bluebook.sampling_shuffle_seed == 123
    assert config.bluebook.prefer_hf_corpora is True
    assert config.bluebook.primary_corpora_only is True
    assert config.bluebook.exact_state_partitions_only is True
    assert config.bluebook.merge_recovered_rows is True
    assert config.bluebook.hydrate_merge_from_hf is True
    assert config.bluebook.publish_merged_parquet_to_hf is True
    assert config.bluebook.publish_to_hf is False
    assert config.state_refresh.scrape is True
    assert config.state_refresh.parallel_workers == 8
    assert config.state_refresh.publish_to_hf is False
    assert config.state_refresh.hydrate_statute_text is True
    assert config.state_refresh.hydrate_timeout_seconds == 25.0
    assert config.cache.cache_dir == str(tmp_path / "cache")
    assert config.cache.mirror_to_ipfs is True
    assert config.agentic_corpora.enabled is True
    assert config.agentic_corpora.corpora == ["state_laws", "state_admin_rules"]


def test_legal_scraper_daemon_arg_config_allows_state_hydration_controls(tmp_path):
    args = build_arg_parser().parse_args(
        [
            "--states",
            "KY",
            "--output-dir",
            str(tmp_path),
            "--state-refresh-scrape",
            "--no-hydrate-state-text",
            "--state-refresh-hydrate-timeout-seconds",
            "3",
        ]
    )

    config = config_from_args(args)

    assert config.state_refresh.scrape is True
    assert config.state_refresh.hydrate_statute_text is False
    assert config.state_refresh.hydrate_timeout_seconds == 3.0


def test_legal_scraper_daemon_arg_config_full_corpus_preset(tmp_path):
    args = build_arg_parser().parse_args(
        [
            "--states",
            "MN",
            "--output-dir",
            str(tmp_path),
            "--full-corpus",
            "--bluebook-samples",
            "9",
        ]
    )

    config = config_from_args(args)

    assert config.full_corpus is True
    assert config.states[0] == "AL"
    assert config.states[-2:] == ["WY", "DC"]
    assert "DC" in config.states
    assert len(config.states) == 51
    assert config.bluebook.samples == 9
    assert config.bluebook.corpora == ["state_laws", "state_admin_rules", "state_court_rules"]
    assert config.bluebook.seed_from_corpora is True
    assert config.bluebook.prefer_hf_corpora is True
    assert config.bluebook.primary_corpora_only is True
    assert config.bluebook.exact_state_partitions_only is True
    assert config.bluebook.materialize_hf_corpora is True
    assert config.bluebook.publish_to_hf is False
    assert config.state_refresh.scrape is True
    assert config.state_refresh.merge_hf_existing is True
    assert config.state_refresh.max_statutes == 0
    assert config.state_refresh.per_state_timeout_seconds == 86400.0
    assert config.state_refresh.per_state_retry_attempts == 2
    assert config.state_refresh.hydrate_timeout_seconds == 60.0
    assert config.state_refresh.publish_to_hf is False
    assert config.agentic_corpora.enabled is True
    assert config.agentic_corpora.corpora == ["state_laws", "state_admin_rules", "state_court_rules"]
    assert config.agentic_corpora.max_statutes == 0

    daemon = LegalScraperDaemon(config)
    preflight = daemon.build_plan()["preflight"]
    assert preflight["status"] == "ready"
    assert preflight["target_state_count"] == 51
    assert preflight["missing_state_scrapers"] == []
    assert preflight["invariants"]["state_refresh_unbounded"] is True
    assert preflight["invariants"]["state_refresh_hf_merge_enabled"] is True
    assert preflight["invariants"]["publication_opt_in"] is True


@pytest.mark.asyncio
async def test_legal_scraper_daemon_scopes_bluebook_skip_live_search_env(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH", raising=False)
    observed = {}

    class _FakeBluebookRun:
        def to_dict(self):
            return {"summary": {"recovery_count": 0}}

    async def _fake_bluebook_runner(**kwargs):
        observed["skip_live_search_env"] = os.environ.get("LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH")
        return _FakeBluebookRun()

    import os

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            states=["MN"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(samples=1, skip_live_search=True),
            state_refresh=StateRefreshDaemonConfig(enabled=False),
            agentic_corpora=AgenticCorpusDaemonConfig(enabled=False),
        ),
        bluebook_runner=_fake_bluebook_runner,
    )

    await daemon.run()

    assert observed["skip_live_search_env"] == "1"
    assert "LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH" not in os.environ


@pytest.mark.asyncio
async def test_legal_scraper_daemon_full_corpus_completeness_audit(tmp_path):
    class _FakeBluebookRun:
        def to_dict(self):
            return {"summary": {"recovery_count": 0}}

    async def _fake_bluebook_runner(**kwargs):
        return _FakeBluebookRun()

    async def _fake_refresh_runner(args):
        states = str(args.states).split(",")
        return {
            "status": "success",
            "build": {
                "states": states,
                "missing_jsonld_states": [],
                "combined_row_count": 100,
            },
            "scrape_gap_states": [],
            "build_gap_states": [],
        }

    async def _fake_agentic_runner(**kwargs):
        return {
            "status": "success",
            "summary": {
                "corpus": kwargs["corpus"],
                "states": list(kwargs["states"]),
                "latest_cycle": {
                    "diagnostics": {
                        "coverage": {
                            "coverage_gap_states": [],
                        },
                    },
                },
            },
        }

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            full_corpus=True,
            states=["MN", "OR"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(samples=1),
            state_refresh=StateRefreshDaemonConfig(scrape=True),
            agentic_corpora=AgenticCorpusDaemonConfig(
                enabled=True,
                corpora=["state_laws", "state_admin_rules", "state_court_rules"],
            ),
        ),
        bluebook_runner=_fake_bluebook_runner,
        state_refresh_runner=_fake_refresh_runner,
        agentic_runner=_fake_agentic_runner,
    )

    result = await daemon.run()
    completeness = result["cycles"][0]["corpus_completeness"]

    assert result["cycles"][0]["status"] == "success"
    assert completeness["status"] == "complete"
    assert completeness["required_state_count"] == 2
    assert completeness["missing_state_refresh_states"] == []
    assert completeness["missing_agentic_corpora"] == []
    assert completeness["missing_agentic_states_by_corpus"] == {}


@pytest.mark.asyncio
async def test_legal_scraper_daemon_full_corpus_marks_missing_states_partial(tmp_path):
    async def _fake_refresh_runner(args):
        return {
            "status": "partial_success",
            "build": {
                "states": ["MN"],
                "missing_jsonld_states": ["OR"],
                "combined_row_count": 10,
            },
            "scrape_gap_states": [],
            "build_gap_states": ["OR"],
        }

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            full_corpus=True,
            states=["MN", "OR"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(enabled=False),
            state_refresh=StateRefreshDaemonConfig(scrape=True),
            agentic_corpora=AgenticCorpusDaemonConfig(enabled=False),
        ),
        state_refresh_runner=_fake_refresh_runner,
    )

    result = await daemon.run()
    completeness = result["cycles"][0]["corpus_completeness"]

    assert result["cycles"][0]["status"] == "partial_success"
    assert completeness["status"] == "incomplete"
    assert completeness["missing_state_refresh_states"] == ["OR"]
    assert completeness["missing_agentic_corpora"] == [
        "state_laws",
        "state_admin_rules",
        "state_court_rules",
    ]


@pytest.mark.asyncio
async def test_legal_scraper_daemon_full_corpus_marks_agentic_state_gaps_partial(tmp_path):
    async def _fake_refresh_runner(args):
        states = str(args.states).split(",")
        return {
            "status": "success",
            "build": {
                "states": states,
                "missing_jsonld_states": [],
                "combined_row_count": 10,
            },
            "scrape_gap_states": [],
            "build_gap_states": [],
        }

    async def _fake_agentic_runner(**kwargs):
        return {
            "status": "success",
            "summary": {
                "corpus": kwargs["corpus"],
                "states": ["MN"],
                "latest_cycle": {
                    "diagnostics": {
                        "coverage": {
                            "coverage_gap_states": ["OR"],
                        },
                    },
                },
            },
        }

    daemon = LegalScraperDaemon(
        LegalScraperDaemonConfig(
            full_corpus=True,
            states=["MN", "OR"],
            output_dir=str(tmp_path),
            bluebook=BluebookDaemonConfig(enabled=False),
            state_refresh=StateRefreshDaemonConfig(scrape=True),
            agentic_corpora=AgenticCorpusDaemonConfig(
                enabled=True,
                corpora=["state_laws", "state_admin_rules", "state_court_rules"],
            ),
        ),
        state_refresh_runner=_fake_refresh_runner,
        agentic_runner=_fake_agentic_runner,
    )

    result = await daemon.run()
    completeness = result["cycles"][0]["corpus_completeness"]

    assert result["cycles"][0]["status"] == "partial_success"
    assert completeness["status"] == "incomplete"
    assert completeness["missing_agentic_states_by_corpus"] == {
        "state_admin_rules": ["OR"],
        "state_court_rules": ["OR"],
        "state_laws": ["OR"],
    }


def test_legal_scraper_daemon_normalizers():
    assert _normalize_states("MN,or") == ["MN", "OR"]
    assert _normalize_states("all")[0] == "AL"
    assert _normalize_corpora("laws,admin,court") == [
        "state_laws",
        "state_admin_rules",
        "state_court_rules",
    ]
