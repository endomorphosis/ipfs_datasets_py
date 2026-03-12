import asyncio
import json
import time

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon import (
    StateLawsAgenticDaemon,
    StateLawsAgenticDaemonConfig,
)
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI
from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
    ScraperMethod,
    UnifiedWebScraper,
)


def test_unified_web_scraper_applies_env_tactic_overrides(monkeypatch):
    monkeypatch.setenv(
        "IPFS_DATASETS_SCRAPER_METHOD_ORDER",
        "playwright,common_crawl,archive_is,requests_only",
    )
    monkeypatch.setenv("IPFS_DATASETS_SCRAPER_FALLBACK_ENABLED", "0")
    monkeypatch.setenv("IPFS_DATASETS_ARCHIVE_IS_SUBMIT_ON_MISS", "0")

    scraper = UnifiedWebScraper()

    assert scraper.config.preferred_methods == [
        ScraperMethod.PLAYWRIGHT,
        ScraperMethod.COMMON_CRAWL,
        ScraperMethod.ARCHIVE_IS,
        ScraperMethod.REQUESTS_ONLY,
    ]
    assert scraper.config.fallback_enabled is False
    assert scraper.config.archive_is_submit_on_miss is False


def test_unified_api_applies_env_search_engine_overrides(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SEARCH_ENGINES", "google_cse,brave")
    monkeypatch.setenv("IPFS_DATASETS_SEARCH_FALLBACK_ENABLED", "0")
    monkeypatch.setenv("IPFS_DATASETS_SEARCH_PARALLEL_ENABLED", "0")

    api = UnifiedWebArchivingAPI()

    assert api.config.default_search_engines == ["google_cse", "brave"]
    assert api.config.fallback_enabled is False
    assert api.config.parallel_enabled is False


def test_state_admin_rules_query_hints_expand_agentic_query(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import state_admin_rules_scraper as scraper_module

    monkeypatch.setenv(
        "LEGAL_SCRAPER_QUERY_HINTS_JSON",
        json.dumps({"AZ": ["Arizona administrative code pdf title 18", "azsos title 18 rtf"]}),
    )

    query = scraper_module._agentic_query_for_state("AZ")
    target_terms = scraper_module._query_target_terms_for_state("AZ")

    assert "Arizona administrative code pdf title 18" in query
    assert "arizona" in target_terms
    assert "title" in target_terms
    assert "18" not in target_terms


def test_preview_post_cycle_release_plan_builds_without_scraping(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["CA"],
            output_dir=str(tmp_path),
            post_cycle_release=daemon_module.PostCycleReleaseConfig(
                enabled=True,
                dry_run=True,
                workspace_root=str(tmp_path),
                python_bin="/usr/bin/python3",
                publish_command="echo release {corpus_key} {combined_parquet}",
            ),
        )
    )

    preview = daemon.preview_post_cycle_release_plan(cycle_index=7, critic_score=0.975)

    assert preview["status"] == "planned"
    assert preview["preview"] is True
    assert preview["corpus"] == "state_admin_rules"
    assert preview["critic_score"] == 0.975
    assert len(preview["commands"]) == 4
    assert preview["commands"][0]["stage"] == "merge"
    assert "merge_state_admin_runs.py" in preview["commands"][0]["command"]
    assert "--state CA" in preview["commands"][0]["command"]
    assert preview["commands"][3]["stage"] == "publish"
    assert "release state_admin_rules" in preview["commands"][3]["command"]


def test_state_admin_rules_agentic_daemon_select_tactic_biases_priority_state_recommendations(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            explore_probability=0.0,
            random_seed=5,
        )
    )

    daemon._state["recommended_tactics"] = []
    daemon._state["priority_states"] = ["AZ"]
    daemon._state["state_action_plan"] = {
        "AZ": {
            "priority_score": 5,
            "recommended_tactics": ["document_first", "router_assisted"],
            "query_hints": ["AZ administrative code pdf"],
        }
    }
    daemon._state["tactics"] = {
        name: {"trials": 2, "total_score": 1.0, "best_score": 0.5}
        for name in daemon.config.tactic_profiles
    }
    daemon._state["tactics"]["archival_first"] = {"trials": 2, "total_score": 2.0, "best_score": 1.0}
    daemon._state["tactics"]["document_first"] = {"trials": 2, "total_score": 1.8, "best_score": 0.9}
    daemon._state["tactics"]["router_assisted"] = {"trials": 2, "total_score": 1.7, "best_score": 0.85}

    selected = daemon._select_tactic()

    assert selected.name == "document_first"


def test_state_admin_rules_agentic_daemon_select_tactic_escalates_after_repeated_document_gap_cycles(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ", "CA"],
            output_dir=str(tmp_path),
            explore_probability=0.0,
            random_seed=11,
        )
    )

    daemon._state["recommended_tactics"] = []
    daemon._state["priority_states"] = ["AZ"]
    daemon._state["state_action_plan"] = {
        "AZ": {
            "priority_score": 4,
            "recommended_tactics": ["document_first", "router_assisted"],
            "query_hints": ["AZ administrative code pdf"],
        }
    }
    daemon._state["tactics"] = {
        "archival_first": {"trials": 3, "total_score": 1.65, "best_score": 0.57},
        "document_first": {"trials": 3, "total_score": 1.44, "best_score": 0.50},
        "router_assisted": {"trials": 3, "total_score": 1.38, "best_score": 0.48},
        "render_first": {"trials": 3, "total_score": 1.20, "best_score": 0.43},
        "discovery_first": {"trials": 3, "total_score": 1.32, "best_score": 0.46},
        "precision_first": {"trials": 3, "total_score": 1.29, "best_score": 0.44},
    }
    daemon._state["recent_cycles"] = [
        {
            "cycle": 1,
            "tactic": "archival_first",
            "score": 0.55,
            "passed": False,
            "issues": ["document-candidate-gaps:AZ", "state-gap-analysis:AZ"],
        },
        {
            "cycle": 2,
            "tactic": "archival_first",
            "score": 0.56,
            "passed": False,
            "issues": ["document-candidate-gaps:AZ", "state-gap-analysis:AZ"],
        },
    ]

    selected = daemon._select_tactic()

    assert selected.name == "document_first"


def test_state_admin_rules_agentic_daemon_selection_context_reports_issue_pressure(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            explore_probability=0.0,
            random_seed=13,
        )
    )

    daemon._state["recommended_tactics"] = ["document_first"]
    daemon._state["priority_states"] = ["AZ"]
    daemon._state["state_action_plan"] = {
        "AZ": {
            "priority_score": 5,
            "recommended_tactics": ["document_first", "router_assisted"],
            "query_hints": ["AZ administrative code pdf"],
        }
    }
    daemon._state["tactics"] = {
        name: {"trials": 2, "total_score": 1.0, "best_score": 0.5}
        for name in daemon.config.tactic_profiles
    }
    daemon._state["recent_cycles"] = [
        {
            "cycle": 1,
            "tactic": "archival_first",
            "score": 0.50,
            "passed": False,
            "issues": ["document-candidate-gaps:AZ", "state-gap-analysis:AZ"],
        }
    ]

    selection = daemon._select_tactic_with_context()

    assert selection["details"]["selected_tactic"] == selection["profile"].name
    assert selection["details"]["mode"] == "exploit"
    assert selection["details"]["recent_issue_counts"]["document-candidate-gaps:AZ"] == 1
    assert selection["details"]["score_breakdown"]["document_first"]["issue_pressure_bonus"] > 0.0


def test_state_admin_rules_agentic_daemon_selection_context_escalates_document_recovery_stalls(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            explore_probability=0.0,
            random_seed=31,
        )
    )

    daemon._state["recommended_tactics"] = []
    daemon._state["priority_states"] = ["AZ"]
    daemon._state["state_action_plan"] = {
        "AZ": {
            "priority_score": 5,
            "recommended_tactics": ["render_first"],
            "query_hints": ["AZ site:apps.azsos.gov filetype:pdf"],
        }
    }
    daemon._state["tactics"] = {
        name: {"trials": 2, "total_score": 1.0, "best_score": 0.5}
        for name in daemon.config.tactic_profiles
    }
    daemon._state["recent_cycles"] = [
        {
            "cycle": 1,
            "tactic": "document_first",
            "score": 0.49,
            "passed": False,
            "issues": ["document-recovery-stalled:AZ"],
        }
    ]

    selection = daemon._select_tactic_with_context()

    assert selection["profile"].name == "render_first"
    assert selection["details"]["score_breakdown"]["render_first"]["issue_pressure_bonus"] > 0.0


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_runs_priority_states_first(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    captured_states = []

    async def _fake_scrape_state_admin_rules(**kwargs):
        captured_states.append(list(kwargs.get("states") or []))
        return {
            "status": "partial_success",
            "data": [
                {"state_code": "CA", "statutes": [], "rules_count": 0},
                {"state_code": "AZ", "statutes": [], "rules_count": 0},
                {"state_code": "WA", "statutes": [], "rules_count": 0},
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "CA": {"attempted": 1, "success": 0, "success_ratio": 0.0, "fallback_count": 1, "providers": {}},
                        "AZ": {"attempted": 1, "success": 0, "success_ratio": 0.0, "fallback_count": 1, "providers": {}},
                        "WA": {"attempted": 1, "success": 0, "success_ratio": 0.0, "fallback_count": 1, "providers": {}},
                    }
                }
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["CA", "AZ", "WA"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=17,
        )
    )
    daemon._state["priority_states"] = ["AZ", "WA"]

    summary = await daemon.run()

    assert captured_states == [["AZ", "WA", "CA"]]
    assert summary["latest_cycle"]["cycle_state_order"] == ["AZ", "WA", "CA"]
    assert summary["latest_cycle"]["tactic_selection"]["priority_states"] == ["AZ", "WA"]


@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_plans_post_cycle_release(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_laws(**kwargs):
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [
                        {
                            "source_url": "https://example.org/oregon/statute-1",
                            "full_text": "Section 1. " + ("Substantive legal text. " * 20),
                            "structured_data": {
                                "jsonld": {
                                    "@type": "Legislation",
                                    "identifier": "OR-1",
                                    "name": "Section 1",
                                    "sectionNumber": "1.010",
                                    "text": "Section 1. " + ("Substantive legal text. " * 20),
                                },
                                "citations": {"internal": ["1.010"]},
                            },
                        }
                    ],
                }
            ],
            "metadata": {
                "coverage_summary": {
                    "states_targeted": 1,
                    "states_returned": 1,
                    "states_with_nonzero_statutes": 1,
                    "coverage_gap_states": [],
                },
                "fetch_analytics": {
                    "attempted": 2,
                    "success": 2,
                    "success_ratio": 1.0,
                    "fallback_count": 0,
                    "providers": {"common_crawl": 1, "playwright": 1},
                },
                "fetch_analytics_by_state": {
                    "OR": {
                        "attempted": 2,
                        "success": 2,
                        "success_ratio": 1.0,
                        "fallback_count": 0,
                        "providers": {"common_crawl": 1, "playwright": 1},
                    }
                },
                "etl_readiness": {
                    "ready_for_kg_etl": True,
                    "total_statutes": 1,
                    "full_text_ratio": 1.0,
                    "jsonld_ratio": 1.0,
                    "jsonld_legislation_ratio": 1.0,
                    "kg_payload_ratio": 1.0,
                    "citation_ratio": 1.0,
                    "statute_signal_ratio": 1.0,
                    "non_scaffold_ratio": 1.0,
                    "states_with_zero_statutes": 0,
                },
                "quality_by_state": {
                    "OR": {
                        "total": 1,
                        "scaffold_ratio": 0.0,
                        "nav_like_ratio": 0.0,
                        "fallback_section_ratio": 0.0,
                        "numeric_section_name_ratio": 1.0,
                    }
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _fake_scrape_state_laws)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_laws",
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=3,
            post_cycle_release=daemon_module.PostCycleReleaseConfig(
                enabled=True,
                dry_run=True,
                min_score=0.90,
                workspace_root=str(tmp_path),
                python_bin="/usr/bin/python3",
                publish_command="echo publish {corpus_key} {critic_score}",
            ),
        )
    )

    summary = await daemon.run()

    release = summary["latest_cycle"]["post_cycle_release"]
    assert release["status"] == "planned"
    assert len(release["commands"]) == 4
    assert release["commands"][0]["stage"] == "merge"
    assert "merge_state_laws_runs.py" in release["commands"][0]["command"]
    assert "--state OR" in release["commands"][0]["command"]
    assert "build_state_laws_embeddings_parquet_with_cid.py" in release["commands"][2]["command"]
    assert release["commands"][3]["stage"] == "publish"
    assert "publish state_laws" in release["commands"][3]["command"]


@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_skips_post_cycle_release_below_threshold(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_laws(**kwargs):
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [
                        {
                            "source_url": "https://example.org/oregon/statute-1",
                            "full_text": "short text",
                        }
                    ],
                }
            ],
            "metadata": {
                "coverage_summary": {
                    "states_targeted": 1,
                    "states_returned": 1,
                    "states_with_nonzero_statutes": 1,
                    "coverage_gap_states": [],
                },
                "fetch_analytics": {
                    "attempted": 1,
                    "success": 1,
                    "success_ratio": 1.0,
                    "fallback_count": 0,
                    "providers": {"requests_only": 1},
                },
                "fetch_analytics_by_state": {
                    "OR": {
                        "attempted": 1,
                        "success": 1,
                        "success_ratio": 1.0,
                        "fallback_count": 0,
                        "providers": {"requests_only": 1},
                    }
                },
                "etl_readiness": {
                    "ready_for_kg_etl": False,
                    "total_statutes": 1,
                    "full_text_ratio": 0.2,
                    "jsonld_ratio": 0.0,
                    "jsonld_legislation_ratio": 0.0,
                    "kg_payload_ratio": 0.0,
                    "citation_ratio": 0.0,
                    "statute_signal_ratio": 0.5,
                    "non_scaffold_ratio": 1.0,
                    "states_with_zero_statutes": 0,
                },
                "quality_by_state": {
                    "OR": {
                        "total": 1,
                        "scaffold_ratio": 0.0,
                        "nav_like_ratio": 0.0,
                        "fallback_section_ratio": 0.0,
                        "numeric_section_name_ratio": 0.0,
                    }
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _fake_scrape_state_laws)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_laws",
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=3,
            post_cycle_release=daemon_module.PostCycleReleaseConfig(
                enabled=True,
                dry_run=True,
                min_score=0.95,
                require_passed=False,
                workspace_root=str(tmp_path),
                python_bin="/usr/bin/python3",
            ),
        )
    )

    summary = await daemon.run()

    release = summary["latest_cycle"]["post_cycle_release"]
    assert release["status"] == "skipped"
    assert release["reason"] == "score-below-threshold"
    assert release["required_score"] == 0.95


@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_runs_single_cycle(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_laws(**kwargs):
        assert kwargs["states"] == ["OR"]
        assert kwargs["per_state_timeout_seconds"] == 12.0
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [
                        {
                            "source_url": "https://example.org/oregon/statute-1",
                            "full_text": "Section 1. This is valid legal text.",
                        }
                    ],
                }
            ],
            "metadata": {
                "coverage_summary": {
                    "states_targeted": 1,
                    "states_returned": 1,
                    "states_with_nonzero_statutes": 1,
                    "coverage_gap_states": [],
                },
                "fetch_analytics": {
                    "attempted": 4,
                    "success": 4,
                    "success_ratio": 1.0,
                    "fallback_count": 1,
                    "providers": {"common_crawl": 2, "playwright": 2},
                },
                "fetch_analytics_by_state": {
                    "OR": {
                        "attempted": 4,
                        "success": 4,
                        "success_ratio": 1.0,
                        "fallback_count": 1,
                        "providers": {"common_crawl": 2, "playwright": 2},
                    }
                },
                "etl_readiness": {
                    "ready_for_kg_etl": True,
                    "total_statutes": 1,
                    "full_text_ratio": 1.0,
                    "jsonld_ratio": 1.0,
                    "jsonld_legislation_ratio": 1.0,
                    "kg_payload_ratio": 1.0,
                    "citation_ratio": 1.0,
                    "statute_signal_ratio": 1.0,
                    "non_scaffold_ratio": 1.0,
                    "states_with_zero_statutes": 0,
                },
                "quality_by_state": {
                    "OR": {
                        "total": 1,
                        "scaffold_ratio": 0.0,
                        "nav_like_ratio": 0.0,
                        "fallback_section_ratio": 0.0,
                        "numeric_section_name_ratio": 1.0,
                    }
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _fake_scrape_state_laws)

    daemon = StateLawsAgenticDaemon(
        StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            per_state_timeout_seconds=12.0,
            random_seed=7,
        )
    )

    summary = await daemon.run()

    assert summary["status"] == "success"
    assert summary["cycles_executed"] == 1
    assert summary["latest_cycle"]["passed"] is True
    assert summary["latest_cycle"]["critic_score"] >= 0.92
    assert summary["latest_cycle"]["tactic_selection"]["selected_tactic"] == summary["latest_cycle"]["tactic"]["name"]

    state_payload = json.loads((tmp_path / "daemon_state.json").read_text(encoding="utf-8"))
    assert state_payload["cycle_count"] == 1
    assert state_payload["best_tactic"]["score"] == summary["latest_cycle"]["critic_score"]
    assert state_payload["last_tactic_selection"]["selected_tactic"] == summary["latest_cycle"]["tactic"]["name"]


@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_schedules_deferred_retry_for_rate_limited_scrape(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_laws(**kwargs):
        assert kwargs["states"] == ["OR"]
        return {
            "status": "rate_limited",
            "data": [],
            "metadata": {
                "cloudflare_status": "rate_limited",
                "retryable": True,
                "retry_after_seconds": 90.0,
                "retry_at_utc": "2026-03-12T00:00:00+00:00",
                "wait_budget_exhausted": True,
                "rate_limit_diagnostics": {
                    "operation": "create_crawl",
                    "cf_ray": "test-ray",
                    "cf_auditlog_id": "audit-id",
                    "error_code": "2001",
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _fake_scrape_state_laws)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=7,
        )
    )

    summary = await daemon.run()

    latest_cycle = summary["latest_cycle"]
    assert summary["pending_retry"]["provider"] == "cloudflare_browser_rendering"
    assert summary["pending_retry"]["retry_after_seconds"] == 90.0
    assert latest_cycle["status"] == "rate_limited"
    assert latest_cycle["passed"] is False
    assert latest_cycle["critic_score"] == 0.0
    assert latest_cycle["deferred_retry"]["status"] == "scheduled"
    assert latest_cycle["deferred_retry"]["provider"] == "cloudflare_browser_rendering"
    assert latest_cycle["deferred_retry"]["retry_after_seconds"] == 90.0
    assert latest_cycle["diagnostics"]["rate_limit"]["rate_limit_diagnostics"]["cf_ray"] == "test-ray"
    assert latest_cycle["critic"]["issues"] == ["rate-limited-deferred-retry:cloudflare_browser_rendering"]
    assert latest_cycle["tactic_selection"]["selected_tactic"] == latest_cycle["tactic"]["name"]
    assert latest_cycle["router_assist"]["reason"] == "deferred-retry-scheduled"
    assert latest_cycle["archive_warmup"]["reason"] == "deferred-retry-scheduled"
    assert latest_cycle["post_cycle_release"]["reason"] == "deferred-retry-scheduled"

    state_payload = json.loads((tmp_path / "daemon_state.json").read_text(encoding="utf-8"))
    assert state_payload["cycle_count"] == 1
    assert state_payload["pending_retry"]["provider"] == "cloudflare_browser_rendering"
    assert state_payload["pending_retry"]["retry_after_seconds"] == 90.0
    assert state_payload["tactics"] == {}
    assert state_payload["best_tactic"] == {}

    latest_summary = json.loads((tmp_path / "latest_summary.json").read_text(encoding="utf-8"))
    assert latest_summary["pending_retry"]["provider"] == "cloudflare_browser_rendering"
    assert latest_summary["pending_retry"]["retry_after_seconds"] == 90.0

    latest_pending_retry = json.loads((tmp_path / "latest_pending_retry.json").read_text(encoding="utf-8"))
    assert latest_pending_retry["pending_retry"]["provider"] == "cloudflare_browser_rendering"
    assert latest_pending_retry["pending_retry"]["retry_after_seconds"] == 90.0
    assert (tmp_path / "cycles" / "cycle_0001_pending_retry.json").exists()


@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_waits_until_deferred_retry_window(monkeypatch, tmp_path):
    daemon = StateLawsAgenticDaemon(
        StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=2,
            archive_warmup_urls=0,
            cycle_interval_seconds=900.0,
            random_seed=7,
        )
    )

    cycles = [
        {
            "cycle": 1,
            "timestamp": "2026-03-11T00:00:00",
            "status": "rate_limited",
            "passed": False,
            "deferred_retry": {
                "status": "scheduled",
                "retry_after_seconds": 42.0,
                "provider": "cloudflare_browser_rendering",
            },
        },
        {
            "cycle": 2,
            "timestamp": "2026-03-11T00:01:00",
            "status": "success",
            "passed": False,
        },
    ]

    async def _fake_run_cycle():
        return cycles.pop(0)

    sleep_calls = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(daemon, "run_cycle", _fake_run_cycle)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    summary = await daemon.run()

    assert summary["cycles_executed"] == 2
    assert sleep_calls == [42.0]


@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_writes_and_clears_in_progress_checkpoint(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_laws(**kwargs):
        checkpoint_path = tmp_path / "cycles" / "cycle_0001.in_progress.json"
        latest_checkpoint_path = tmp_path / "latest_in_progress.json"
        assert checkpoint_path.exists()
        assert latest_checkpoint_path.exists()
        checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint_payload["status"] == "running"
        assert checkpoint_payload["stage"] == "scrape"
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [
                        {
                            "source_url": "https://example.org/oregon/statute-1",
                            "full_text": "Section 1. This is valid legal text.",
                        }
                    ],
                }
            ],
            "metadata": {
                "coverage_summary": {
                    "states_targeted": 1,
                    "states_returned": 1,
                    "states_with_nonzero_statutes": 1,
                    "coverage_gap_states": [],
                },
                "fetch_analytics": {
                    "attempted": 1,
                    "success": 1,
                    "success_ratio": 1.0,
                    "fallback_count": 0,
                    "providers": {"common_crawl": 1},
                },
                "fetch_analytics_by_state": {
                    "OR": {
                        "attempted": 1,
                        "success": 1,
                        "success_ratio": 1.0,
                        "fallback_count": 0,
                        "providers": {"common_crawl": 1},
                    }
                },
                "etl_readiness": {
                    "ready_for_kg_etl": True,
                    "total_statutes": 1,
                    "full_text_ratio": 1.0,
                    "jsonld_ratio": 1.0,
                    "jsonld_legislation_ratio": 1.0,
                    "kg_payload_ratio": 1.0,
                    "citation_ratio": 1.0,
                    "statute_signal_ratio": 1.0,
                    "non_scaffold_ratio": 1.0,
                    "states_with_zero_statutes": 0,
                },
                "quality_by_state": {
                    "OR": {
                        "total": 1,
                        "scaffold_ratio": 0.0,
                        "nav_like_ratio": 0.0,
                        "fallback_section_ratio": 0.0,
                        "numeric_section_name_ratio": 1.0,
                    }
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _fake_scrape_state_laws)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=7,
        )
    )

    summary = await daemon.run()

    assert summary["status"] == "success"
    assert not (tmp_path / "cycles" / "cycle_0001.in_progress.json").exists()
    assert not (tmp_path / "latest_in_progress.json").exists()
    assert (tmp_path / "cycles" / "cycle_0001.json").exists()

@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_checkpoint_advances_to_router_review(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_laws(**kwargs):
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [
                        {
                            "source_url": "https://example.org/oregon/statute-1",
                            "full_text": "Section 1. This is valid legal text.",
                        }
                    ],
                }
            ],
            "metadata": {
                "coverage_summary": {
                    "states_targeted": 1,
                    "states_returned": 1,
                    "states_with_nonzero_statutes": 1,
                    "coverage_gap_states": [],
                },
                "fetch_analytics": {
                    "attempted": 1,
                    "success": 1,
                    "success_ratio": 1.0,
                    "fallback_count": 0,
                    "providers": {"common_crawl": 1},
                },
                "fetch_analytics_by_state": {
                    "OR": {
                        "attempted": 1,
                        "success": 1,
                        "success_ratio": 1.0,
                        "fallback_count": 0,
                        "providers": {"common_crawl": 1},
                    }
                },
                "etl_readiness": {
                    "ready_for_kg_etl": True,
                    "total_statutes": 1,
                    "full_text_ratio": 1.0,
                    "jsonld_ratio": 1.0,
                    "jsonld_legislation_ratio": 1.0,
                    "kg_payload_ratio": 1.0,
                    "citation_ratio": 1.0,
                    "statute_signal_ratio": 1.0,
                    "non_scaffold_ratio": 1.0,
                    "states_with_zero_statutes": 0,
                },
                "quality_by_state": {
                    "OR": {
                        "total": 1,
                        "scaffold_ratio": 0.0,
                        "nav_like_ratio": 0.0,
                        "fallback_section_ratio": 0.0,
                        "numeric_section_name_ratio": 1.0,
                    }
                },
            },
        }

    async def _fake_router_assist_report(self, **kwargs):
        checkpoint_payload = json.loads((tmp_path / "latest_in_progress.json").read_text(encoding="utf-8"))
        assert checkpoint_payload["stage"] == "router_review"
        assert checkpoint_payload["status"] == "success"
        assert checkpoint_payload["critic_score"] >= 0.92
        return {"status": "skipped", "reason": "test"}

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _fake_scrape_state_laws)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_build_router_assist_report", _fake_router_assist_report)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=7,
        )
    )

    summary = await daemon.run()

    assert summary["status"] == "success"
    assert summary["latest_cycle"]["router_assist"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_state_laws_agentic_daemon_applies_outer_scrape_timeout(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _slow_scrape_state_laws(**kwargs):
        await asyncio.sleep(0.2)
        return {"status": "success", "data": [{"state_code": "OR", "statutes": []}], "metadata": {}}

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _slow_scrape_state_laws)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            scrape_timeout_seconds=0.05,
            random_seed=7,
        )
    )
    tactic = daemon._select_tactic()

    started_at = time.perf_counter()
    scrape_result = await daemon._run_scrape_with_tactic(tactic)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.15
    assert scrape_result["status"] == "error"
    assert scrape_result["metadata"]["scrape_timed_out"] is True
    assert scrape_result["metadata"]["scrape_timeout_seconds"] == 0.05


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_uses_filtered_corpus_diagnostics(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["OR"]
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "phase_timings": {
                    "base_scrape_seconds": 1.2,
                    "fallback_retry_seconds": 0.3,
                    "agentic_discovery_seconds": 4.8,
                    "jsonld_write_seconds": 0.1,
                    "total_seconds": 6.4,
                },
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "OR": {
                            "attempted": 3,
                            "success": 2,
                            "success_ratio": 0.667,
                            "fallback_count": 1,
                            "providers": {"common_crawl": 2, "playwright": 1},
                            "last_error": "empty-admin-results",
                        }
                    }
                }
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=11,
        )
    )

    summary = await daemon.run()

    assert summary["latest_cycle"]["corpus"] == "state_admin_rules"
    assert summary["latest_cycle"]["passed"] is False
    assert summary["latest_cycle"]["diagnostics"]["coverage"]["coverage_gap_states"] == ["OR"]
    assert summary["latest_cycle"]["diagnostics"]["timing"]["dominant_phase"] == "agentic_discovery_seconds"
    assert "agentic-discovery-dominant" in summary["latest_cycle"]["critic"]["issues"]
    assert "document_first" in summary["latest_cycle"]["critic"]["recommended_next_tactics"]
    assert summary["latest_cycle"]["critic"]["recommended_next_tactics"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_surfaces_cloudflare_availability_diagnostics(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["OR"]
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "phase_timings": {"total_seconds": 1.5},
                "cloudflare_browser_rendering": {
                    "available": False,
                    "status": "missing_credentials",
                    "provider": "cloudflare_browser_rendering",
                    "missing_credentials": ["account_id", "api_token"],
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=11,
        )
    )

    summary = await daemon.run()

    latest_cycle = summary["latest_cycle"]
    assert latest_cycle["metadata"]["cloudflare_browser_rendering"]["status"] == "missing_credentials"
    assert latest_cycle["diagnostics"]["cloudflare"]["available"] is False
    assert latest_cycle["diagnostics"]["documents"]["cloudflare_browser_rendering"]["provider"] == "cloudflare_browser_rendering"
    assert latest_cycle["diagnostics"]["documents"]["cloudflare_browser_rendering"]["missing_credentials"] == ["account_id", "api_token"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_schedules_deferred_retry_from_base_metadata(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["OR"]
        return {
            "status": "partial_success",
            "data": [],
            "metadata": {
                "phase_timings": {
                    "total_seconds": 1.0,
                },
                "base_metadata": {
                    "cloudflare_status": "rate_limited",
                    "retryable": True,
                    "retry_after_seconds": 120.0,
                    "retry_at_utc": "2026-03-12T00:10:00+00:00",
                    "wait_budget_exhausted": True,
                    "rate_limit_diagnostics": {
                        "operation": "get_crawl",
                        "cf_ray": "nested-ray",
                        "cf_auditlog_id": "nested-audit",
                    },
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=11,
        )
    )

    summary = await daemon.run()

    latest_cycle = summary["latest_cycle"]
    assert summary["pending_retry"]["retry_after_seconds"] == 120.0
    assert latest_cycle["status"] == "partial_success"
    assert latest_cycle["deferred_retry"]["status"] == "scheduled"
    assert latest_cycle["deferred_retry"]["provider"] == "cloudflare_browser_rendering"
    assert latest_cycle["deferred_retry"]["retry_after_seconds"] == 120.0
    assert latest_cycle["deferred_retry"]["wait_budget_exhausted"] is True
    assert latest_cycle["diagnostics"]["rate_limit"]["rate_limit_diagnostics"]["cf_ray"] == "nested-ray"

    state_payload = json.loads((tmp_path / "daemon_state.json").read_text(encoding="utf-8"))
    assert state_payload["pending_retry"]["retry_after_seconds"] == 120.0
    latest_pending_retry = json.loads((tmp_path / "latest_pending_retry.json").read_text(encoding="utf-8"))
    assert latest_pending_retry["pending_retry"]["retry_after_seconds"] == 120.0


def test_state_laws_agentic_daemon_clears_pending_retry_artifact_after_success(tmp_path):
    daemon = StateLawsAgenticDaemon(
        StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=7,
        )
    )

    pending_cycle = {
        "cycle": 1,
        "timestamp": "2026-03-12T00:00:00",
        "states": ["OR"],
        "status": "rate_limited",
        "deferred_retry": {
            "status": "scheduled",
            "provider": "cloudflare_browser_rendering",
            "retry_after_seconds": 15.0,
        },
        "critic": {"recommended_next_tactics": [], "priority_states": [], "state_action_plan": {}},
    }
    daemon._update_state(tactic=daemon._select_tactic(), cycle_payload=pending_cycle)
    assert (tmp_path / "latest_pending_retry.json").exists()

    success_cycle = {
        "cycle": 2,
        "timestamp": "2026-03-12T00:01:00",
        "states": ["OR"],
        "status": "success",
        "critic_score": 0.95,
        "passed": True,
        "critic": {"recommended_next_tactics": ["archival_first"], "priority_states": [], "state_action_plan": {}},
    }
    daemon._update_state(tactic=daemon._select_tactic(), cycle_payload=success_cycle)

    assert not (tmp_path / "latest_pending_retry.json").exists()


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_forwards_agentic_budget_knobs(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["AZ"]
        assert kwargs["agentic_max_candidates_per_state"] == 24
        assert kwargs["agentic_max_fetch_per_state"] == 8
        assert kwargs["agentic_max_results_per_domain"] == 30
        assert kwargs["agentic_max_hops"] == 2
        assert kwargs["agentic_max_pages"] == 10
        assert kwargs["agentic_fetch_concurrency"] == 4
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 1,
                            "success": 0,
                            "success_ratio": 0.0,
                            "fallback_count": 1,
                            "providers": {"common_crawl": 1},
                        }
                    }
                }
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            admin_agentic_max_candidates_per_state=24,
            admin_agentic_max_fetch_per_state=8,
            admin_agentic_max_results_per_domain=30,
            admin_agentic_max_hops=2,
            admin_agentic_max_pages=10,
            admin_agentic_fetch_concurrency=4,
        )
    )

    summary = await daemon.run()

    assert summary["latest_cycle"]["corpus"] == "state_admin_rules"
    assert summary["latest_cycle"]["diagnostics"]["coverage"]["coverage_gap_states"] == ["AZ"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_archive_warmup_uses_agentic_report_urls(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py.processors.legal_scrapers import parallel_web_archiver as archiver_module

    captured = {}

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 4,
                            "success": 1,
                            "success_ratio": 0.25,
                            "fallback_count": 2,
                            "providers": {"playwright": 1, "common_crawl": 3},
                            "last_error": "cloudflare-blocked",
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "seed_urls": ["https://apps.azsos.gov/public_services/CodeTOC.htm"],
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
                                "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
                            ],
                        }
                    },
                },
            },
        }

    class _FakeParallelWebArchiver:
        def __init__(self, max_concurrent=1):
            captured["max_concurrent"] = max_concurrent

        async def archive_urls_parallel(self, urls):
            captured["urls"] = list(urls)
            return [
                type("ArchiveResult", (), {"success": True, "source": "wayback"})(),
                type("ArchiveResult", (), {"success": True, "source": "common_crawl"})(),
            ]

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=3,
            archive_warmup_concurrency=2,
            random_seed=17,
        )
    )

    summary = await daemon.run()

    archive_warmup = summary["latest_cycle"]["archive_warmup"]
    assert archive_warmup["status"] == "success"
    assert archive_warmup["attempted"] == 3
    assert captured["max_concurrent"] == 2
    assert captured["urls"] == [
        "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
        "https://apps.azsos.gov/public_services/CodeTOC.htm",
    ]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_archive_warmup_prioritizes_priority_state_documents(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py.processors.legal_scrapers import parallel_web_archiver as archiver_module

    captured = {}

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {"state_code": "AZ", "statutes": [], "rules_count": 0},
                {"state_code": "UT", "statutes": [], "rules_count": 0},
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {"attempted": 3, "success": 1, "success_ratio": 0.333, "fallback_count": 1, "providers": {"playwright": 1}},
                        "UT": {"attempted": 3, "success": 1, "success_ratio": 0.333, "fallback_count": 1, "providers": {"common_crawl": 1}},
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "seed_urls": ["https://apps.azsos.gov/public_services/CodeTOC.htm"],
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
                                "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "gap_summary": {"missing_seed_hosts": ["apps.azsos.gov"], "candidate_hosts_without_rules": ["apps.azsos.gov"]},
                        },
                        "UT": {
                            "seed_urls": ["https://adminrules.utah.gov/public/home"],
                            "top_candidate_urls": [
                                "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "gap_summary": {"missing_seed_hosts": ["adminrules.utah.gov"], "candidate_hosts_without_rules": ["adminrules.utah.gov"]},
                        },
                    },
                },
            },
        }

    class _FakeParallelWebArchiver:
        def __init__(self, max_concurrent=1):
            captured["max_concurrent"] = max_concurrent

        async def archive_urls_parallel(self, urls):
            captured["urls"] = list(urls)
            return [type("ArchiveResult", (), {"success": True, "source": "wayback"})() for _ in urls]

    async def _fake_router_review(self, *, tactic, diagnostics, critic):
        return {
            "status": "success",
            "recommended_next_tactics": ["document_first", "router_assisted"],
            "priority_states": ["AZ"],
            "query_hints": ["Arizona administrative code pdf title 18"],
            "rationale": "Prioritize Arizona document recovery first.",
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_run_llm_router_review", _fake_router_review)
    monkeypatch.setattr(archiver_module, "ParallelWebArchiver", _FakeParallelWebArchiver)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ", "UT"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=4,
            archive_warmup_concurrency=2,
            random_seed=19,
        )
    )

    summary = await daemon.run()

    archive_warmup = summary["latest_cycle"]["archive_warmup"]
    assert archive_warmup["status"] == "success"
    assert archive_warmup["attempted"] == 4
    assert captured["urls"] == [
        "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
        "https://apps.azsos.gov/public_services/CodeTOC.htm",
        "https://adminrules.utah.gov/public/rule/R70-101/Current%20Rules",
    ]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_detects_document_gaps_and_recommends_document_first(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 5,
                            "success": 2,
                            "success_ratio": 0.4,
                            "fallback_count": 2,
                            "providers": {"playwright": 2, "common_crawl": 3},
                            "last_error": "document-links-unprocessed",
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 6,
                            "inspected_urls": 4,
                            "expanded_urls": 3,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
                                "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "domains_seen": ["apps.azsos.gov"],
                            "parallel_prefetch": {"attempted": 2, "successful": 1, "rule_hits": 0},
                            "source_breakdown": {"seed": 1, "playwright": 2, "candidate_document": 2},
                            "gap_summary": {
                                "missing_seed_hosts": ["apps.azsos.gov"],
                                "candidate_hosts_without_rules": ["apps.azsos.gov"],
                            },
                        }
                    },
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=23,
        )
    )

    summary = await daemon.run()

    diagnostics = summary["latest_cycle"]["diagnostics"]
    critic = summary["latest_cycle"]["critic"]
    document_gap_report = summary["latest_cycle"]["document_gap_report"]
    document_gap_report_path = tmp_path / "cycles" / "cycle_0001_document_gaps.json"
    assert diagnostics["documents"]["candidate_document_urls"] == 2
    assert diagnostics["documents"]["candidate_format_counts_by_state"] == {"AZ": {"pdf": 1, "rtf": 1}}
    assert diagnostics["documents"]["states_with_candidate_document_gaps"] == ["AZ"]
    assert diagnostics["documents"]["per_state_recovery"]["AZ"] == {
        "processed_method_counts": {},
        "source_breakdown": {"seed": 1, "playwright": 2, "candidate_document": 2},
        "domains_seen": ["apps.azsos.gov"],
        "parallel_prefetch": {"attempted": 2, "successful": 1, "rule_hits": 0},
        "timed_out": False,
        "candidate_urls": 6,
        "inspected_urls": 4,
        "expanded_urls": 3,
    }
    assert diagnostics["gap_analysis"]["weak_states"] == ["AZ"]
    assert any(item.startswith("document-candidate-gaps:AZ") for item in critic["issues"])
    assert any(item.startswith("document-recovery-stalled:AZ") for item in critic["issues"])
    assert "document_first" in critic["recommended_next_tactics"]
    assert "render_first" in critic["recommended_next_tactics"]
    assert "router_assisted" in critic["recommended_next_tactics"]
    assert critic["priority_states"] == ["AZ"]
    assert critic["state_action_plan"]["AZ"]["candidate_document_format_counts"] == {"pdf": 1, "rtf": 1}
    assert critic["state_action_plan"]["AZ"]["document_recovery_profile"] == {
        "processed_method_counts": {},
        "source_breakdown": {"seed": 1, "playwright": 2, "candidate_document": 2},
        "domains_seen": ["apps.azsos.gov"],
        "parallel_prefetch": {"attempted": 2, "successful": 1, "rule_hits": 0},
        "candidate_urls": 6,
        "inspected_urls": 4,
        "expanded_urls": 3,
        "timed_out": False,
    }
    assert "document_recovery_stalled" in critic["state_action_plan"]["AZ"]["reasons"]
    assert "AZ administrative code pdf" in critic["query_hints"]
    assert "AZ administrative code rtf" in critic["query_hints"]
    assert "AZ administrative rules site:apps.azsos.gov" in critic["query_hints"]
    assert "AZ site:apps.azsos.gov filetype:pdf" in critic["query_hints"]
    assert "AZ site:apps.azsos.gov filetype:rtf" in critic["query_hints"]
    assert document_gap_report["states_with_candidate_document_gaps"] == ["AZ"]
    assert document_gap_report["states"]["AZ"]["candidate_document_format_counts"] == {"pdf": 1, "rtf": 1}
    assert document_gap_report["states"]["AZ"]["processed_method_counts"] == {}
    assert document_gap_report["states"]["AZ"]["source_breakdown"] == {
        "seed": 1,
        "playwright": 2,
        "candidate_document": 2,
    }
    assert document_gap_report["states"]["AZ"]["domains_seen"] == ["apps.azsos.gov"]
    assert document_gap_report["states"]["AZ"]["parallel_prefetch"] == {"attempted": 2, "successful": 1, "rule_hits": 0}
    assert document_gap_report["states"]["AZ"]["inspected_urls"] == 4
    assert document_gap_report["states"]["AZ"]["expanded_urls"] == 3
    assert document_gap_report["states"]["AZ"]["top_candidate_document_urls"] == [
        "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    ]
    assert summary["latest_cycle"]["document_gap_report_path"] == str(document_gap_report_path)
    persisted_report = json.loads(document_gap_report_path.read_text(encoding="utf-8"))
    assert persisted_report["cycle"] == 1
    assert persisted_report["states_with_candidate_document_gaps"] == ["AZ"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_falls_back_to_critic_query_hints_without_router(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 3,
                            "success": 1,
                            "success_ratio": 0.333,
                            "fallback_count": 1,
                            "providers": {"playwright": 1, "common_crawl": 2},
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 4,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
                                "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "gap_summary": {
                                "missing_seed_hosts": ["apps.azsos.gov"],
                                "candidate_hosts_without_rules": ["apps.azsos.gov"],
                            },
                        }
                    },
                },
            },
        }

    async def _unavailable_router_review(self, *, tactic, diagnostics, critic):
        return {"status": "unavailable", "error": "llm-router-disabled"}

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_run_llm_router_review", _unavailable_router_review)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            router_llm_timeout_seconds=0.0,
            router_embeddings_timeout_seconds=0.0,
            router_ipfs_timeout_seconds=0.0,
            random_seed=29,
        )
    )

    summary = await daemon.run()

    critic = summary["latest_cycle"]["critic"]
    assert critic["priority_states"] == ["AZ"]
    assert "AZ administrative code pdf" in critic["query_hints"]
    assert "AZ administrative code rtf" in critic["query_hints"]

    state_payload = json.loads((tmp_path / "daemon_state.json").read_text(encoding="utf-8"))
    assert state_payload["state_query_hints"]["AZ"] == [
        "AZ administrative code pdf",
        "AZ administrative code rtf",
        "AZ administrative rules site:apps.azsos.gov",
        "AZ site:apps.azsos.gov filetype:pdf",
        "AZ site:apps.azsos.gov filetype:rtf",
    ]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_uses_router_assist_review(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 4,
                            "success": 1,
                            "success_ratio": 0.25,
                            "fallback_count": 2,
                            "providers": {"playwright": 1},
                            "last_error": "gap-review-needed",
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 3,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "gap_summary": {
                                "missing_seed_hosts": ["apps.azsos.gov"],
                                "candidate_hosts_without_rules": ["apps.azsos.gov"],
                            },
                        }
                    },
                },
            },
        }

    async def _fake_router_review(self, *, tactic, diagnostics, critic):
        return {
            "status": "success",
            "recommended_next_tactics": ["router_assisted", "document_first"],
            "priority_states": ["AZ"],
            "query_hints": ["Arizona administrative code pdf title 18"],
            "rationale": "Document candidates remain unresolved, so router-assisted recovery should prioritize PDF-heavy discovery.",
        }

    def _fake_embeddings_ranking(self, tactic, diagnostics, critic):
        return [
            {"tactic": "router_assisted", "score": 0.97},
            {"tactic": "document_first", "score": 0.95},
        ]

    async def _fake_ipfs_persist(self, *, cycle_index, report, corpus_key):
        return {"status": "success", "cid": "bafyrouterreview", "name": f"{corpus_key}-{cycle_index}"}

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_run_llm_router_review", _fake_router_review)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_rank_tactics_with_embeddings", _fake_embeddings_ranking)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_persist_router_assist_to_ipfs", _fake_ipfs_persist)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=31,
        )
    )

    summary = await daemon.run()

    router_assist = summary["latest_cycle"]["router_assist"]
    critic = summary["latest_cycle"]["critic"]
    router_artifact_path = tmp_path / "cycles" / "cycle_0001_router_assist.json"
    assert router_assist["status"] == "completed"
    assert router_assist["llm_review"]["recommended_next_tactics"] == ["router_assisted", "document_first"]
    assert router_assist["embeddings_ranking"][0]["tactic"] == "router_assisted"
    assert router_assist["ipfs_persist"]["cid"] == "bafyrouterreview"
    assert summary["latest_cycle"]["router_assist"]["artifact_path"] == str(router_artifact_path)
    assert "router_assisted" in critic["recommended_next_tactics"]
    assert "document_first" in critic["recommended_next_tactics"]
    assert "router-assisted-review" in critic["issues"]
    assert critic["query_hints"] == ["Arizona administrative code pdf title 18"]
    assert critic["router_rationale"].startswith("Document candidates remain unresolved")
    persisted = json.loads(router_artifact_path.read_text(encoding="utf-8"))
    assert persisted["cycle"] == 1
    assert persisted["llm_review"]["priority_states"] == ["AZ"]
    state_payload = json.loads((tmp_path / "daemon_state.json").read_text(encoding="utf-8"))
    assert state_payload["state_query_hints"] == {"AZ": ["Arizona administrative code pdf title 18"]}


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_llm_router_review_uses_generate_text(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py import embeddings_router as embeddings_router_module
    from ipfs_datasets_py import llm_router as llm_router_module

    def _fake_generate_text(prompt, **kwargs):
        assert 'recommended_next_tactics' in prompt
        assert kwargs["provider"] is None
        assert kwargs["allow_local_fallback"] is False
        return json.dumps(
            {
                "recommended_next_tactics": ["router_assisted", "document_first"],
                "priority_states": ["AZ"],
                "query_hints": ["Arizona administrative code pdf title 18"],
                "rationale": "Use document-oriented recovery first.",
            }
        )

    def _fake_embed_texts_batched(texts, **kwargs):
        return [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.2, 0.8],
            [0.1, 0.9],
            [0.0, 1.0],
            [0.5, 0.5],
        ]

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [{"state_code": "AZ", "statutes": [], "rules_count": 0}],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 1,
                            "success": 0,
                            "success_ratio": 0.0,
                            "fallback_count": 1,
                            "providers": {"playwright": 1},
                        }
                    }
                }
            },
        }

    async def _fake_ipfs_persist(self, *, cycle_index, report, corpus_key):
        return {"status": "success", "cid": "bafyrouterreview", "name": f"{corpus_key}-{cycle_index}"}

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(llm_router_module, "generate_text", _fake_generate_text)
    monkeypatch.setattr(llm_router_module, "get_accelerate_status", lambda: {"available": False})
    monkeypatch.setattr(embeddings_router_module, "embed_texts_batched", _fake_embed_texts_batched)
    monkeypatch.setattr(embeddings_router_module, "get_accelerate_status", lambda: {"available": False})
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_persist_router_assist_to_ipfs", _fake_ipfs_persist)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=41,
        )
    )

    summary = await daemon.run()

    router_assist = summary["latest_cycle"]["router_assist"]
    assert router_assist["status"] == "completed"
    assert router_assist["llm_review"]["status"] == "success"
    assert router_assist["llm_review"]["recommended_next_tactics"] == ["router_assisted", "document_first"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_router_timeout_does_not_block_cycle(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [{"state_code": "AZ", "statutes": [], "rules_count": 0}],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 1,
                            "success": 0,
                            "success_ratio": 0.0,
                            "fallback_count": 1,
                            "providers": {"playwright": 1},
                        }
                    }
                }
            },
        }

    async def _slow_router_review(self, *, tactic, diagnostics, critic):
        await asyncio.sleep(0.2)
        return {"status": "success", "recommended_next_tactics": ["router_assisted"]}

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_run_llm_router_review", _slow_router_review)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            router_llm_timeout_seconds=0.01,
            router_embeddings_timeout_seconds=0.01,
            router_ipfs_timeout_seconds=0.01,
        )
    )

    summary = await daemon.run()

    assert summary["status"] == "success"
    assert summary["latest_cycle"]["router_assist"]["status"] == "completed"
    assert summary["latest_cycle"]["router_assist"]["llm_review"]["status"] == "error"
    assert "timed out" in summary["latest_cycle"]["router_assist"]["llm_review"]["error"]
    assert (tmp_path / "cycles" / "cycle_0001.json").exists()



@pytest.mark.asyncio
async def test_state_court_rules_agentic_daemon_runs_single_cycle(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    long_rule_text = (
        "Rule 1.010 governs the scope and construction of these Oregon court rules. "
        "These rules apply to civil proceedings in circuit court, require liberal construction to secure the just, "
        "speedy, and inexpensive determination of every action, and authorize courts to manage procedure consistent "
        "with statutory directives, party notice, and due process protections."
    )

    async def _fake_scrape_state_procedure_rules(**kwargs):
        assert kwargs["states"] == ["OR"]
        return {
            "status": "success",
            "data": [
                {
                    "state_code": "OR",
                    "statutes": [
                        {
                            "source_url": "https://example.org/oregon/court-rule-1",
                            "full_text": long_rule_text,
                            "structured_data": {
                                "jsonld": {
                                    "@type": "Legislation",
                                    "identifier": "OR-RULE-1",
                                    "name": "Rule 1",
                                    "sectionNumber": "1.010",
                                    "text": long_rule_text,
                                },
                                "citations": {"internal": ["1.010"]},
                            },
                        }
                    ],
                    "rules_count": 1,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "OR": {
                            "attempted": 4,
                            "success": 4,
                            "success_ratio": 1.0,
                            "fallback_count": 1,
                            "providers": {"playwright": 2, "common_crawl": 2},
                        }
                    }
                }
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_procedure_rules", _fake_scrape_state_procedure_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_court_rules",
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=13,
        )
    )

    summary = await daemon.run()

    assert summary["latest_cycle"]["corpus"] == "state_court_rules"
    assert summary["latest_cycle"]["passed"] is True
    assert summary["latest_cycle"]["critic_score"] >= 0.92