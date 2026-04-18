import json

import pytest

from ipfs_datasets_py.processors.legal_scrapers.legal_scraper_daemon import (
    AgenticCorpusDaemonConfig,
    BluebookDaemonConfig,
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
            state_refresh=StateRefreshDaemonConfig(scrape=False, publish_to_hf=False),
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
    assert result["cycles"][0]["phases"]["state_refresh"]["build"]["combined_row_count"] == 10


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
    assert config.state_refresh.publish_to_hf is False
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
