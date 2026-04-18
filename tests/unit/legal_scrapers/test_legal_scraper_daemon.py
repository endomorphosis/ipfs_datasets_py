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
    assert calls["refresh"].publish_to_hf is False
    assert calls["refresh"].parallel_workers == 7
    assert result["cycles"][0]["phases"]["state_refresh"]["build"]["combined_row_count"] == 10


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
    assert config.bluebook.publish_to_hf is False
    assert config.state_refresh.scrape is True
    assert config.state_refresh.parallel_workers == 8
    assert config.state_refresh.publish_to_hf is False
    assert config.cache.cache_dir == str(tmp_path / "cache")
    assert config.cache.mirror_to_ipfs is True
    assert config.agentic_corpora.enabled is True
    assert config.agentic_corpora.corpora == ["state_laws", "state_admin_rules"]


def test_legal_scraper_daemon_normalizers():
    assert _normalize_states("MN,or") == ["MN", "OR"]
    assert _normalize_states("all")[0] == "AL"
    assert _normalize_corpora("laws,admin,court") == [
        "state_laws",
        "state_admin_rules",
        "state_court_rules",
    ]
