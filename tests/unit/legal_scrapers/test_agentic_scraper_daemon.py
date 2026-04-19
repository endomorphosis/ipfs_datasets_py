import asyncio
import json
import sys
import time
import types
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"

from ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon import (
    StateLawsAgenticDaemon,
    StateLawsAgenticDaemonConfig,
)
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI
from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
    ScraperMethod,
    UnifiedWebScraper,
)


def test_state_laws_agentic_daemon_config_admin_rules_defaults_are_high_cap():
    config = StateLawsAgenticDaemonConfig(corpus_key="state_admin_rules")

    assert config.per_state_timeout_seconds == 86400.0
    assert config.admin_parallel_assist_timeout_seconds == 86400.0
    assert config.admin_agentic_max_candidates_per_state == 1000
    assert config.admin_agentic_max_fetch_per_state == 1000
    assert config.admin_agentic_max_results_per_domain == 1000
    assert config.admin_agentic_max_hops == 4
    assert config.admin_agentic_max_pages == 1000


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


def test_unified_web_scraper_applies_cloudflare_crawl_env_overrides(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_CLOUDFLARE_CRAWL_DEPTH", "2")
    monkeypatch.setenv("IPFS_DATASETS_CLOUDFLARE_CRAWL_RENDER", "1")
    monkeypatch.setenv("IPFS_DATASETS_CLOUDFLARE_CRAWL_INCLUDE_EXTERNAL_LINKS", "1")
    monkeypatch.setenv("IPFS_DATASETS_CLOUDFLARE_CRAWL_INCLUDE_SUBDOMAINS", "1")
    monkeypatch.setenv("IPFS_DATASETS_CLOUDFLARE_CRAWL_FORMATS", "markdown,html")

    scraper = UnifiedWebScraper()

    assert scraper.config.cloudflare_depth == 2
    assert scraper.config.cloudflare_render is True
    assert scraper.config.cloudflare_include_external_links is True
    assert scraper.config.cloudflare_include_subdomains is True
    assert scraper.config.cloudflare_formats == ["markdown", "html"]


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


def test_state_admin_rules_daemon_clears_generic_method_order_overrides(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    monkeypatch.setenv("IPFS_DATASETS_SCRAPER_METHOD_ORDER", "playwright,requests_only")
    monkeypatch.setenv("LEGAL_SCRAPER_METHOD_ORDER", "playwright,requests_only")

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
        )
    )

    tactic = daemon.config.tactic_profiles["archival_first"]

    with daemon._tactic_env(tactic):
        assert "IPFS_DATASETS_SCRAPER_METHOD_ORDER" not in daemon_module.os.environ
        assert "LEGAL_SCRAPER_METHOD_ORDER" not in daemon_module.os.environ


def test_state_laws_daemon_injects_cloudflare_method_into_env_order(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN", "token")

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_laws",
            states=["AZ"],
            output_dir=str(tmp_path),
        )
    )

    tactic = daemon.config.tactic_profiles["document_first"]
    with daemon._tactic_env(tactic):
        configured = daemon_module.os.environ.get("IPFS_DATASETS_SCRAPER_METHOD_ORDER") or ""
        configured_list = [item.strip() for item in configured.split(",") if item.strip()]
        assert "cloudflare_browser_rendering" in configured_list
        assert configured_list.index("cloudflare_browser_rendering") <= configured_list.index("playwright")


def test_state_laws_daemon_document_recovery_ratio_gate_blocks_success_when_enabled(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_laws",
            states=["AZ"],
            output_dir=str(tmp_path),
            min_document_recovery_ratio=0.75,
        )
    )

    diagnostics = {
        "coverage": {"coverage_gap_states": []},
        "fetch": {"no_attempt_states": []},
        "etl_readiness": {
            "ready_for_kg_etl": True,
            "full_text_ratio": 0.9,
            "jsonld_ratio": 0.9,
            "jsonld_legislation_ratio": 0.9,
            "kg_payload_ratio": 0.9,
            "statute_signal_ratio": 0.9,
            "non_scaffold_ratio": 0.9,
        },
        "documents": {
            "candidate_document_urls": 10,
            "processed_document_urls": 3,
            "states_with_candidate_document_gaps": [],
        },
    }

    annotated = daemon._annotate_document_recovery_gate(diagnostics)
    assert annotated["documents"]["document_recovery_ratio"] == 0.3
    assert annotated["documents"]["required_document_recovery_ratio"] == 0.75
    assert annotated["documents"]["document_recovery_ratio_ok"] is False
    assert daemon._is_success(annotated, score=0.99) is False


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
    assert len(preview["commands"]) == 3
    assert preview["commands"][0]["stage"] == "merge_recovered_rows"
    assert "merge_state_admin_recovered_rows.py" in preview["commands"][0]["command"]
    assert f'"{tmp_path}"' in preview["commands"][0]["command"]
    assert "--parquet-dir" in preview["commands"][0]["command"]
    assert preview["commands"][1]["stage"] == "embeddings"
    assert "build_state_admin_embeddings_parquet_with_cid.py" in preview["commands"][1]["command"]
    assert preview["commands"][2]["stage"] == "publish"
    assert "release state_admin_rules" in preview["commands"][2]["command"]
    assert preview["artifacts"]["clean_output_dir"].endswith("_cleaned")


def test_preview_runtime_readiness_reports_cloudflare_and_router(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ", "CA"],
            output_dir=str(tmp_path),
        )
    )

    monkeypatch.setattr(
        daemon,
        "_cloudflare_browser_rendering_availability",
        lambda: {"available": False, "status": "missing_credentials"},
    )
    monkeypatch.setattr(
        daemon,
        "_router_availability_snapshot",
        lambda: {"llm_router": True, "embeddings_router": True, "ipfs_backend": "KuboCLIBackend"},
    )

    preview = daemon.preview_runtime_readiness()

    assert preview["preview"] is True
    assert preview["corpus"] == "state_admin_rules"
    assert preview["state_count"] == 2
    assert preview["cloudflare_browser_rendering"]["status"] == "missing_credentials"
    assert preview["router"]["ipfs_backend"] == "KuboCLIBackend"
    assert "cloudflare_explore" in preview["recommended_boot_tactics"]
    assert "router_assisted" in preview["recommended_boot_tactics"]


def test_cloudflare_runtime_readiness_detects_vault_credentials(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    class _Vault:
        def get(self, name):
            mapping = {
                "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID": "vault-acct",
                "IPFS_DATASETS_CLOUDFLARE_API_TOKEN": "vault-token",
            }
            return mapping.get(name)

    monkeypatch.delenv("IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_CLOUDFLARE_API_TOKEN", raising=False)
    fake_vault_module = types.SimpleNamespace(get_secrets_vault=lambda: _Vault())
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.mcp_server.secrets_vault", fake_vault_module)

    readiness = daemon_module.StateLawsAgenticDaemon._cloudflare_browser_rendering_availability()

    assert readiness["available"] is True
    assert readiness["account_id_env"] == "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID"
    assert readiness["api_token_env"] == "IPFS_DATASETS_CLOUDFLARE_API_TOKEN"
    assert readiness["account_id_source_kind"] == "vault"
    assert readiness["api_token_source_kind"] == "vault"


def test_tactic_env_injects_cloudflare_credentials_from_vault(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    class _Vault:
        def get(self, name):
            mapping = {
                "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID": "vault-acct",
                "IPFS_DATASETS_CLOUDFLARE_API_TOKEN": "vault-token",
            }
            return mapping.get(name)

    fake_vault_module = types.SimpleNamespace(get_secrets_vault=lambda: _Vault())
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.mcp_server.secrets_vault", fake_vault_module)
    monkeypatch.delenv("IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN", raising=False)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
        )
    )
    tactic = daemon.config.tactic_profiles["cloudflare_explore"]

    with daemon._tactic_env(tactic):
        assert daemon_module.os.environ["IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID"] == "vault-acct"
        assert daemon_module.os.environ["IPFS_DATASETS_CLOUDFLARE_API_TOKEN"] == "vault-token"


@pytest.mark.anyio
async def test_probe_cloudflare_browser_rendering_returns_missing_credentials(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
        )
    )
    daemon._cloudflare_browser_rendering_availability = lambda: {  # type: ignore[method-assign]
        "available": False,
        "status": "missing_credentials",
    }

    result = await daemon.probe_cloudflare_browser_rendering(url="https://example.com")

    assert result["status"] == "missing_credentials"
    assert result["submitted_url"] == "https://example.com"


def test_state_admin_rules_release_plan_routes_parquet_through_clean_bundle(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ", "CA"],
            output_dir=str(tmp_path),
            post_cycle_release=daemon_module.PostCycleReleaseConfig(
                enabled=True,
                dry_run=True,
                workspace_root=str(tmp_path),
                python_bin="/usr/bin/python3",
            ),
        )
    )

    plan = daemon.preview_post_cycle_release_plan(cycle_index=3, critic_score=0.95)

    assert plan["commands"][0]["stage"] == "merge"
    assert "--include-corpus-jsonl" in plan["commands"][0]["command"]
    assert "--state AZ --state CA" in plan["commands"][0]["command"]
    assert plan["commands"][1]["stage"] == "clean"
    assert '--input-dir "' in plan["commands"][1]["command"]
    assert plan["artifacts"]["clean_output_dir"].endswith("_cleaned")
    assert plan["artifacts"]["jsonld_dir"].startswith(plan["artifacts"]["clean_output_dir"])
    assert plan["artifacts"]["parquet_dir"].startswith(plan["artifacts"]["clean_output_dir"])


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


def test_state_admin_rules_agentic_daemon_untried_selection_honors_priority_action_plan(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            explore_probability=0.0,
            random_seed=7,
        )
    )

    daemon._state["recommended_tactics"] = [
        "archival_first",
        "discovery_first",
        "render_first",
        "precision_first",
        "document_first",
        "router_assisted",
    ]
    daemon._state["priority_states"] = ["AZ"]
    daemon._state["state_action_plan"] = {
        "AZ": {
            "priority_score": 17,
            "reasons": [
                "document_candidate_gap",
                "document_recovery_stalled",
                "document_prefetch_underperforming",
            ],
            "recommended_tactics": [
                "document_first",
                "render_first",
                "router_assisted",
                "archival_first",
                "discovery_first",
            ],
            "query_hints": ["AZ administrative code pdf"],
        }
    }
    daemon._state["tactics"] = {
        "archival_first": {"trials": 1, "total_score": 0.1, "best_score": 0.1},
        "document_first": {"trials": 0, "total_score": 0.0, "best_score": 0.0},
        "render_first": {"trials": 0, "total_score": 0.0, "best_score": 0.0},
        "router_assisted": {"trials": 0, "total_score": 0.0, "best_score": 0.0},
        "discovery_first": {"trials": 0, "total_score": 0.0, "best_score": 0.0},
        "precision_first": {"trials": 0, "total_score": 0.0, "best_score": 0.0},
    }

    selection = daemon._select_tactic_with_context()

    assert selection["profile"].name == "document_first"
    assert selection["details"]["mode"] == "priority_untried"
    assert selection["details"]["priority_recommended_tactics"][0] == "document_first"


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
        "cloudflare_explore": {"trials": 3, "total_score": 1.08, "best_score": 0.39},
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


def test_state_admin_rules_agentic_daemon_selection_context_escalates_cloudflare_browser_challenges(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            explore_probability=0.0,
            random_seed=37,
        )
    )

    daemon._state["recommended_tactics"] = []
    daemon._state["priority_states"] = ["AZ"]
    daemon._state["state_action_plan"] = {
        "AZ": {
            "priority_score": 7,
            "recommended_tactics": ["cloudflare_explore", "document_first", "router_assisted"],
            "query_hints": ["AZ administrative rules site:apps.azsos.gov"],
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
            "score": 0.46,
            "passed": False,
            "issues": ["cloudflare-browser-challenge:AZ", "document-candidate-gaps:AZ"],
        }
    ]

    selection = daemon._select_tactic_with_context()

    assert selection["profile"].name == "cloudflare_explore"
    assert selection["details"]["score_breakdown"]["cloudflare_explore"]["issue_pressure_bonus"] > 0.0


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_detects_cloudflare_browser_challenge_and_recommends_cloudflare_explore(monkeypatch, tmp_path):
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
                            "providers": {"playwright": 2, "cloudflare_browser_rendering": 1},
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 5,
                            "inspected_urls": 3,
                            "expanded_urls": 2,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "domains_seen": ["apps.azsos.gov"],
                            "parallel_prefetch": {"attempted": 1, "successful": 0, "rule_hits": 0},
                            "source_breakdown": {"playwright": 1, "candidate_document": 1, "cloudflare_browser_rendering": 1},
                            "cloudflare_status": "browser_challenge",
                            "cloudflare_http_status": 403,
                            "cloudflare_browser_challenge_detected": True,
                            "cloudflare_error_excerpt": "Just a moment... Enable JavaScript and cookies to continue",
                            "cloudflare_record_status": "errored",
                            "cloudflare_job_status": "completed",
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
            random_seed=41,
        )
    )

    summary = await daemon.run()

    critic = summary["latest_cycle"]["critic"]
    action_plan = critic["state_action_plan"]["AZ"]
    document_gap_report = summary["latest_cycle"]["document_gap_report"]
    directives = document_gap_report["states"]["AZ"]["recovery_directives"]

    assert any(item.startswith("cloudflare-browser-challenge:AZ") for item in critic["issues"])
    assert "cloudflare_explore" in critic["recommended_next_tactics"]
    assert "cloudflare_browser_challenge" in action_plan["reasons"]
    assert "cloudflare_explore" in action_plan["recommended_tactics"]
    assert summary["latest_cycle"]["diagnostics"]["documents"]["per_state_recovery"]["AZ"]["cloudflare_status"] == "browser_challenge"
    assert directives["cloudflare_status"] == "browser_challenge"
    assert directives["cloudflare_browser_challenge_detected"] is True
    assert "cloudflare_browser_rendering" in directives["download_methods"]
    assert "pdf_processor" in directives["processor_modes"]
    assert "cloudflare_explore" in directives["recommended_tactics"]


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
async def test_state_admin_rules_agentic_daemon_runs_parallel_admin_assist(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    captured: dict = {}

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {"state_code": "AZ", "statutes": []},
                {"state_code": "CA", "statutes": []},
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {"attempted": 1, "success": 0, "success_ratio": 0.0, "fallback_count": 1, "providers": {}},
                        "CA": {"attempted": 1, "success": 0, "success_ratio": 0.0, "fallback_count": 1, "providers": {}},
                    }
                },
                "agentic_report": {
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 5,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://azsos.gov/rules/title-18.pdf",
                                "https://apps.azsos.gov/public_services/title_18/1-18.rtf",
                            ],
                            "domains_seen": ["azsos.gov", "apps.azsos.gov"],
                            "source_breakdown": {"search": 2},
                            "gap_summary": {
                                "missing_seed_hosts": ["apps.azsos.gov"],
                                "candidate_hosts_without_rules": ["azsos.gov"],
                            },
                        }
                    }
                },
                "phase_timings": {"agentic_discovery_seconds": 12.0, "total_seconds": 20.0},
            },
        }

    class FakeParallelStateAdminOrchestrator:
        def __init__(self, config=None, parallel_archiver=None, pdf_processor=None, scrape_optimizer=None):
            captured["config"] = config

        async def discover_state_rules_parallel(self, states, seed_urls_by_state, candidate_domains=None):
            captured["states"] = list(states)
            captured["seed_urls_by_state"] = dict(seed_urls_by_state)
            captured["candidate_domains"] = dict(candidate_domains or {})
            return {
                "AZ": SimpleNamespace(
                    status="success",
                    rules=[
                        {
                            "url": "https://azsos.gov/rules/title-18.pdf",
                            "source_url": "https://azsos.gov/rules/title-18.pdf",
                        }
                    ],
                    urls_discovered=8,
                    urls_fetched=4,
                    fetch_errors=0,
                    methods_used={"pdf_processor_playwright_download": 1, "common_crawl": 1},
                    domains_visited={"azsos.gov", "apps.azsos.gov"},
                    gap_analysis={"gap_analysis_status": "completed", "weak_coverage": False},
                )
            }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.enhanced_state_admin_orchestrator.ParallelStateAdminOrchestrator",
        FakeParallelStateAdminOrchestrator,
    )

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ", "CA"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=23,
            admin_parallel_assist_enabled=True,
            admin_parallel_assist_state_limit=2,
            admin_parallel_assist_timeout_seconds=45.0,
        )
    )

    summary = await daemon.run()

    assist = summary["latest_cycle"]["parallel_admin_assist"]
    assert captured["states"][0] == "AZ"
    assert set(captured["states"]).issubset({"AZ", "CA"})
    assert "https://azsos.gov/rules/title-18.pdf" in captured["seed_urls_by_state"]["AZ"]
    assert "https://apps.azsos.gov/public_services/title_18/1-18.rtf" in captured["seed_urls_by_state"]["AZ"]
    assert "AZ" in assist["targeted_states"]
    assert assist["status"] == "completed"
    assert assist["discovered_rules_total"] == 1
    assert assist["states_with_rules"] == ["AZ"]
    assert "document_first" in assist["recommended_next_tactics"]
    assert "archival_first" in assist["recommended_next_tactics"]
    assert summary["latest_cycle"]["critic"]["parallel_admin_assist"]["discovered_rules_total"] == 1
    assert (tmp_path / "latest_parallel_admin_assist.json").exists()


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_skips_parallel_admin_assist_when_disabled(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [{"state_code": "AZ", "statutes": []}],
            "metadata": {
                "base_metadata": {"fetch_analytics_by_state": {"AZ": {"attempted": 1, "success": 0, "success_ratio": 0.0, "fallback_count": 1, "providers": {}}}},
                "agentic_report": {"per_state": {"AZ": {"candidate_urls": 2, "fetched_rules": 0, "top_candidate_urls": ["https://azsos.gov/rules/title-18.pdf"]}}},
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
            random_seed=29,
            admin_parallel_assist_enabled=False,
        )
    )

    summary = await daemon.run()

    assert summary["latest_cycle"]["parallel_admin_assist"]["status"] == "skipped"
    assert summary["latest_cycle"]["parallel_admin_assist"]["reason"] == "parallel-assist-disabled"


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

    artifacts = summary["latest_cycle"]["recovered_row_artifacts"]
    assert artifacts["status"] == "success"
    assert artifacts["row_count"] == 1
    assert artifacts["state_counts"] == {"OR": 1}
    assert artifacts["target_hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert artifacts["target_parquet_paths_by_state"]["OR"] == "state_laws_parquet_cid/STATE-OR.parquet"
    rows_path = tmp_path / "recovered_rows" / "cycle_0001" / "state_laws_statutes.jsonl"
    assert artifacts["statutes_jsonl_path"] == str(rows_path)
    recovered_rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    assert recovered_rows[0]["state_code"] == "OR"
    assert recovered_rows[0]["corpus_key"] == "state_laws"
    assert recovered_rows[0]["source_url"] == "https://example.org/oregon/statute-1"


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
async def test_state_laws_agentic_daemon_updates_scrape_heartbeat_checkpoint(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_laws(**kwargs):
        await asyncio.sleep(0.03)
        return {
            "status": "success",
            "data": [],
            "metadata": {
                "coverage_summary": {
                    "states_targeted": 1,
                    "states_returned": 1,
                    "states_with_nonzero_statutes": 0,
                    "coverage_gap_states": ["OR"],
                },
                "fetch_analytics": {
                    "attempted": 0,
                    "success": 0,
                    "success_ratio": 0.0,
                    "fallback_count": 0,
                    "providers": {},
                },
                "fetch_analytics_by_state": {"OR": {"attempted": 0, "success": 0, "fallback_count": 0, "providers": {}}},
                "etl_readiness": {
                    "ready_for_kg_etl": False,
                    "total_statutes": 0,
                    "full_text_ratio": 0.0,
                    "jsonld_ratio": 0.0,
                    "jsonld_legislation_ratio": 0.0,
                    "kg_payload_ratio": 0.0,
                    "citation_ratio": 0.0,
                    "statute_signal_ratio": 0.0,
                    "non_scaffold_ratio": 0.0,
                    "states_with_zero_statutes": 1,
                },
                "quality_by_state": {"OR": {"total": 0}},
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _fake_scrape_state_laws)

    heartbeat_payloads = []
    original_write = daemon_module.StateLawsAgenticDaemon._write_cycle_checkpoint

    def _recording_write(self, *, cycle_index, payload):
        heartbeat_payloads.append(dict(payload))
        return original_write(self, cycle_index=cycle_index, payload=payload)

    monkeypatch.setattr(
        daemon_module.StateLawsAgenticDaemon,
        "_write_cycle_checkpoint",
        _recording_write,
    )

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            scrape_heartbeat_seconds=0.01,
            random_seed=7,
        )
    )

    await daemon.run()

    assert any("scrape_heartbeat" in payload for payload in heartbeat_payloads)

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


def test_state_laws_agentic_daemon_promotes_latest_checkpoint_to_summary(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=7,
        )
    )

    checkpoint_payload = {
        "cycle": 3,
        "timestamp": "2026-03-22T04:00:00+00:00",
        "corpus": "state_laws",
        "states": ["OR"],
        "cycle_state_order": ["OR"],
        "status": "running",
        "stage": "archive_warmup",
        "tactic": {"name": "archival_first"},
    }
    daemon._write_cycle_checkpoint(cycle_index=3, payload=checkpoint_payload)

    promoted_path = daemon.promote_latest_checkpoint_to_summary(reason="signal:SIGTERM")

    assert promoted_path == tmp_path / "latest_summary.json"
    assert (tmp_path / "latest_in_progress.json").exists()
    assert (tmp_path / "cycles" / "cycle_0003.recovered.json").exists()

    latest_summary_payload = json.loads((tmp_path / "latest_summary.json").read_text(encoding="utf-8"))
    recovered_payload = json.loads((tmp_path / "cycles" / "cycle_0003.recovered.json").read_text(encoding="utf-8"))

    assert latest_summary_payload["status"] == "running"
    assert latest_summary_payload["stage"] == "archive_warmup"
    assert latest_summary_payload["checkpoint_promoted"] is True
    assert latest_summary_payload["checkpoint_promotion_reason"] == "signal:SIGTERM"
    assert "checkpoint_promoted_at" in latest_summary_payload
    assert recovered_payload == latest_summary_payload


def test_state_laws_agentic_daemon_main_promotes_checkpoint_on_nonzero_system_exit(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    promoted_reasons = []
    installed_handlers = {}

    class _FakeDaemon:
        def __init__(self, config):
            self.config = config

        def run(self):
            return object()

        def promote_latest_checkpoint_to_summary(self, *, reason):
            promoted_reasons.append(reason)
            return tmp_path / "latest_summary.json"

    def _fake_getsignal(sig):
        return f"prev:{sig}"

    def _fake_signal(sig, handler):
        installed_handlers[sig] = handler
        return handler

    def _fake_asyncio_run(_coro):
        raise SystemExit(143)

    monkeypatch.setattr(daemon_module, "StateLawsAgenticDaemon", _FakeDaemon)
    monkeypatch.setattr(daemon_module.asyncio, "run", _fake_asyncio_run)
    monkeypatch.setattr(daemon_module.signal, "getsignal", _fake_getsignal)
    monkeypatch.setattr(daemon_module.signal, "signal", _fake_signal)

    with pytest.raises(SystemExit) as exc_info:
        daemon_module.main([
            "--corpus",
            "state_laws",
            "--states",
            "OR",
            "--output-dir",
            str(tmp_path),
        ])

    assert exc_info.value.code == 143
    assert promoted_reasons == ["system_exit:143"]
    assert daemon_module.signal.SIGTERM in installed_handlers
    assert daemon_module.signal.SIGINT in installed_handlers


def test_main_print_runtime_readiness_skips_scrape(monkeypatch, tmp_path, capsys):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    run_called = False

    class _FakeDaemon:
        def __init__(self, config):
            self.config = config

        def preview_runtime_readiness(self):
            return {
                "status": "partial",
                "preview": True,
                "corpus": self.config.corpus_key,
                "state_count": len(self.config.states),
            }

        async def run(self):
            nonlocal run_called
            run_called = True
            return {"status": "should-not-run"}

        def promote_latest_checkpoint_to_summary(self, *, reason):
            return tmp_path / "latest_summary.json"

    monkeypatch.setattr(daemon_module, "StateLawsAgenticDaemon", _FakeDaemon)

    exit_code = daemon_module.main([
        "--corpus",
        "state_admin_rules",
        "--states",
        "AZ,CA",
        "--output-dir",
        str(tmp_path),
        "--print-runtime-readiness",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert run_called is False
    assert payload["preview"] is True
    assert payload["corpus"] == "state_admin_rules"
    assert payload["state_count"] == 2


def test_main_probe_cloudflare_browser_rendering_skips_scrape(monkeypatch, tmp_path, capsys):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    run_called = False

    class _FakeDaemon:
        def __init__(self, config):
            self.config = config

        async def probe_cloudflare_browser_rendering(self, *, url="https://example.com", **kwargs):
            return {
                "status": "error",
                "provider": "cloudflare_browser_rendering",
                "submitted_url": url,
            }

        async def run(self):
            nonlocal run_called
            run_called = True
            return {"status": "should-not-run"}

        def promote_latest_checkpoint_to_summary(self, *, reason):
            return tmp_path / "latest_summary.json"

    monkeypatch.setattr(daemon_module, "StateLawsAgenticDaemon", _FakeDaemon)

    exit_code = daemon_module.main([
        "--corpus",
        "state_admin_rules",
        "--states",
        "AZ",
        "--output-dir",
        str(tmp_path),
        "--probe-cloudflare-browser-rendering",
        "--probe-cloudflare-url",
        "https://example.com",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert run_called is False
    assert payload["status"] == "error"
    assert payload["submitted_url"] == "https://example.com"


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
async def test_state_laws_agentic_daemon_hard_timeout_survives_cancellation_swallow(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _stubborn_scrape_state_laws(**kwargs):
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)
            return {"status": "success", "data": [{"state_code": "OR", "statutes": []}], "metadata": {}}

    monkeypatch.setattr(daemon_module, "scrape_state_laws", _stubborn_scrape_state_laws)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            scrape_timeout_seconds=0.05,
            scrape_heartbeat_seconds=0.01,
            random_seed=11,
        )
    )
    tactic = daemon._select_tactic()

    started_at = time.perf_counter()
    scrape_result = await daemon._run_scrape_with_tactic(tactic)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.25
    assert scrape_result["status"] == "error"
    assert scrape_result["metadata"]["scrape_timed_out"] is True
    await asyncio.sleep(0.25)


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_timeout_preserves_cloudflare_availability(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _slow_scrape_state_admin_rules(**kwargs):
        await asyncio.sleep(0.2)
        return {"status": "success", "data": [], "metadata": {}}

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _slow_scrape_state_admin_rules)
    for env_name in (
        "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
        "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_ACCOUNT_ID",
        "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
        "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_API_TOKEN",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID", "acct-test")
    monkeypatch.setenv("LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN", "token-test")

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["OR"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            scrape_timeout_seconds=0.05,
            random_seed=7,
        )
    )
    tactic = daemon._select_tactic()

    scrape_result = await daemon._run_scrape_with_tactic(tactic)

    assert scrape_result["status"] == "error"
    assert scrape_result["metadata"]["scrape_timed_out"] is True
    assert scrape_result["metadata"]["cloudflare_browser_rendering"]["available"] is True
    assert scrape_result["metadata"]["cloudflare_browser_rendering"]["status"] == "configured"
    assert scrape_result["metadata"]["cloudflare_browser_rendering"]["account_id_env"] in {
        "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
        "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
    }
    assert scrape_result["metadata"]["cloudflare_browser_rendering"]["api_token_env"] in {
        "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
        "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
    }


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
async def test_state_admin_rules_agentic_daemon_ignores_candidate_surplus_without_real_gap(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["AZ"]
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "statutes": [
                        {
                            "state_code": "AZ",
                            "section_number": "A1",
                            "section_name": "Arizona Administrative Code",
                            "full_text": "Arizona Administrative Code substantive rule text with section R1-1-101.",
                            "structured_data": {
                                "type": "regulation",
                                "jsonld": {
                                    "@type": "Legislation",
                                    "identifier": "AZ-AGENTIC-A1",
                                    "sectionNumber": "A1",
                                    "name": "Arizona Administrative Code",
                                    "text": "Arizona Administrative Code substantive rule text with section R1-1-101.",
                                },
                            },
                        }
                    ],
                    "rules_count": 1,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {"attempted": 0, "success": 0, "fallback_count": 0, "providers": {}}
                    }
                },
                "agentic_report": {
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 7,
                            "inspected_urls": 1,
                            "expanded_urls": 0,
                            "fetched_rules": 1,
                            "gap_summary": {
                                "missing_seed_hosts": [],
                                "candidate_hosts_without_rules": [],
                            },
                        }
                    }
                },
                "phase_timings": {
                    "agentic_discovery_seconds": 5.0,
                    "total_seconds": 5.5,
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
            random_seed=11,
        )
    )

    summary = await daemon.run()

    latest_cycle = summary["latest_cycle"]
    assert latest_cycle["diagnostics"]["gap_analysis"]["weak_states"] == []
    assert "state-gap-analysis:AZ" not in latest_cycle["critic"]["issues"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_normalizes_fetch_success_without_attempts(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["CA"]
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "CA",
                    "state_name": "California",
                    "statutes": [
                        {
                            "state_code": "CA",
                            "section_number": "1",
                            "section_name": "California Administrative Rule",
                            "full_text": "California administrative rule text with section 100 and authority citations.",
                            "structured_data": {
                                "type": "regulation",
                                "jsonld": {
                                    "@type": "Legislation",
                                    "identifier": "CA-1",
                                    "sectionNumber": "1",
                                    "name": "California Administrative Rule",
                                    "text": "California administrative rule text with section 100 and authority citations.",
                                },
                                "citations": {"official": ["1 CCR 100"]},
                            },
                        },
                        {
                            "state_code": "CA",
                            "section_number": "2",
                            "section_name": "California Administrative Rule 2",
                            "full_text": "California administrative rule text with section 200 and authority citations.",
                            "structured_data": {
                                "type": "regulation",
                                "jsonld": {
                                    "@type": "Legislation",
                                    "identifier": "CA-2",
                                    "sectionNumber": "2",
                                    "name": "California Administrative Rule 2",
                                    "text": "California administrative rule text with section 200 and authority citations.",
                                },
                                "citations": {"official": ["2 CCR 200"]},
                            },
                        },
                    ],
                    "rules_count": 2,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "CA": {"attempted": 0, "success": 2, "fallback_count": 0, "providers": {}}
                    }
                },
                "agentic_report": {
                    "per_state": {
                        "CA": {
                            "candidate_urls": 2,
                            "inspected_urls": 0,
                            "expanded_urls": 0,
                            "fetched_rules": 0,
                            "gap_summary": {
                                "missing_seed_hosts": [],
                                "candidate_hosts_without_rules": [],
                            },
                        }
                    }
                },
                "phase_timings": {
                    "agentic_discovery_seconds": 3.0,
                    "total_seconds": 3.5,
                },
            },
        }

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["CA"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=11,
        )
    )

    summary = await daemon.run()

    latest_cycle = summary["latest_cycle"]
    fetch = latest_cycle["diagnostics"]["fetch"]
    assert fetch["attempted"] == 2
    assert fetch["success"] == 2
    assert fetch["success_ratio"] == 1.0
    assert fetch["no_attempt_states"] == []
    assert "no-attempt-states:CA" not in latest_cycle["critic"]["issues"]
    assert "fetch-success-low" not in latest_cycle["critic"]["issues"]


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
async def test_state_admin_rules_agentic_daemon_surfaces_browser_challenge_recovery_details(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["AZ"]
        return {
            "status": "partial_success",
            "data": [{"state_code": "AZ", "statutes": [], "rules_count": 0}],
            "metadata": {
                "agentic_report": {
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 2,
                            "inspected_urls": 1,
                            "expanded_urls": 0,
                            "source_breakdown": {"agentic_discovery": 1},
                            "domains_seen": ["azsos.gov"],
                            "parallel_prefetch": {},
                            "timed_out": False,
                            "cloudflare_status": "browser_challenge",
                            "cloudflare_http_status": 403,
                            "cloudflare_browser_challenge_detected": True,
                            "cloudflare_error_excerpt": "Just a moment... Enable JavaScript and cookies to continue",
                            "cloudflare_record_status": "errored",
                            "cloudflare_job_status": "completed",
                        }
                    }
                },
                "cloudflare_status": "browser_challenge",
                "cloudflare_http_status": 403,
                "cloudflare_browser_challenge_detected": True,
                "browser_challenge_states": ["AZ"],
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
            random_seed=11,
        )
    )

    summary = await daemon.run()

    recovery = summary["latest_cycle"]["diagnostics"]["documents"]["per_state_recovery"]["AZ"]
    assert summary["latest_cycle"]["diagnostics"]["cloudflare"]["cloudflare_status"] == "browser_challenge"
    assert recovery["cloudflare_status"] == "browser_challenge"
    assert recovery["cloudflare_http_status"] == 403
    assert recovery["cloudflare_browser_challenge_detected"] is True
    assert recovery["cloudflare_record_status"] == "errored"
    assert recovery["cloudflare_job_status"] == "completed"


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_credits_agentic_fetch_analytics(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        assert kwargs["states"] == ["AZ"]
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "AZ",
                    "state_name": "Arizona",
                    "statutes": [
                        {
                            "state_code": "AZ",
                            "section_number": "A1",
                            "section_name": "Arizona Administrative Code",
                            "full_text": "Arizona Administrative Code substantive rule text with section R1-1-101.",
                            "structured_data": {
                                "type": "regulation",
                                "jsonld": {
                                    "@type": "Legislation",
                                    "identifier": "AZ-AGENTIC-A1",
                                    "sectionNumber": "A1",
                                    "name": "Arizona Administrative Code",
                                    "text": "Arizona Administrative Code substantive rule text with section R1-1-101.",
                                },
                                "citations": {"official": ["AZ Admin Rule A1"]},
                            },
                        }
                    ],
                    "rules_count": 1,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 0,
                            "success": 0,
                            "fallback_count": 0,
                            "providers": {},
                        }
                    }
                },
                "agentic_report": {
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 4,
                            "inspected_urls": 1,
                            "expanded_urls": 0,
                            "fetched_rules": 1,
                            "parallel_prefetch": {"attempted": 4, "successful": 2, "rule_hits": 1},
                            "gap_summary": {
                                "missing_seed_hosts": ["azsos.gov"],
                                "candidate_hosts_without_rules": ["azsos.gov"],
                            },
                        }
                    }
                },
                "phase_timings": {
                    "agentic_discovery_seconds": 4.0,
                    "total_seconds": 4.5,
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
            random_seed=11,
        )
    )

    summary = await daemon.run()

    latest_cycle = summary["latest_cycle"]
    fetch = latest_cycle["diagnostics"]["fetch"]
    assert fetch["attempted"] == 1
    assert fetch["success"] == 1
    assert fetch["success_ratio"] == 1.0
    assert fetch["no_attempt_states"] == []
    assert "fetch-success-low" not in latest_cycle["critic"]["issues"]
    assert "no-attempt-states:AZ" not in latest_cycle["critic"]["issues"]


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
        assert kwargs["rate_limit_delay"] == 0.2
        assert kwargs["strict_full_text"] is False
        assert kwargs["min_full_text_chars"] == 200
        assert kwargs["parallel_workers"] == 1
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

    tactic = summary["latest_cycle"]["tactic"]
    assert tactic["rate_limit_delay"] == 0.2
    assert tactic["strict_full_text"] is False
    assert tactic["min_full_text_chars"] == 200
    assert tactic["parallel_workers"] == 1
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
        "cloudflare_status": None,
        "cloudflare_http_status": None,
        "cloudflare_browser_challenge_detected": False,
        "cloudflare_error_excerpt": None,
        "cloudflare_record_status": None,
        "cloudflare_job_status": None,
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
    assert "AZ administrative code pdf" in critic["state_action_plan"]["AZ"]["query_hints"]
    assert "AZ administrative code rtf" in critic["state_action_plan"]["AZ"]["query_hints"]
    assert "AZ administrative rules site:apps.azsos.gov" in critic["state_action_plan"]["AZ"]["query_hints"]
    assert "AZ site:apps.azsos.gov filetype:pdf" in critic["state_action_plan"]["AZ"]["query_hints"]
    assert "AZ site:apps.azsos.gov filetype:rtf" in critic["state_action_plan"]["AZ"]["query_hints"]
    assert document_gap_report["states_with_candidate_document_gaps"] == ["AZ"]
    assert document_gap_report["states_with_artifact_candidates"] == ["AZ"]
    assert document_gap_report["states"]["AZ"]["candidate_document_format_counts"] == {"pdf": 1, "rtf": 1}
    assert document_gap_report["states"]["AZ"]["top_candidate_urls"] == [
        "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    ]
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
    assert document_gap_report["states"]["AZ"]["recovery_directives"]["candidate_urls"] == [
        "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    ]
    assert summary["latest_cycle"]["document_gap_report_path"] == str(document_gap_report_path)
    persisted_report = json.loads(document_gap_report_path.read_text(encoding="utf-8"))
    assert persisted_report["cycle"] == 1
    assert persisted_report["states_with_candidate_document_gaps"] == ["AZ"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_persists_document_artifacts(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py.processors.web_archiving import unified_web_scraper as scraper_module

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
                            "providers": {"playwright": 1},
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 2,
                            "inspected_urls": 2,
                            "expanded_urls": 1,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "domains_seen": ["apps.azsos.gov"],
                            "parallel_prefetch": {"attempted": 1, "successful": 0, "rule_hits": 0},
                            "source_breakdown": {"candidate_document": 1},
                            "gap_summary": {
                                "missing_seed_hosts": ["apps.azsos.gov"],
                                "candidate_hosts_without_rules": ["apps.azsos.gov"],
                            },
                        }
                    },
                },
            },
        }

    async def _fake_scrape(self, url, method=None, **kwargs):
        assert url.endswith("18-04.pdf")
        return scraper_module.ScraperResult(
            url=url,
            title="18-04.pdf",
            text="Arizona Title 18 extracted text",
            content="Arizona Title 18 extracted text",
            method_used=ScraperMethod.PLAYWRIGHT,
            success=True,
            metadata={
                "method": "playwright_binary_fetch",
                "content_type": "application/pdf",
                "content_length": 17,
                "raw_bytes": b"%PDF-fake-content",
                "binary_document": True,
            },
        )

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(scraper_module.UnifiedWebScraper, "scrape", _fake_scrape)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=43,
            document_artifact_capture_enabled=True,
            document_artifact_state_limit=1,
            document_artifact_urls_per_state=1,
            document_artifact_max_total=1,
        )
    )

    summary = await daemon.run()

    artifact_summary = summary["latest_cycle"]["document_artifacts"]
    documents_summary = summary["latest_cycle"]["diagnostics"]["documents"]
    manifest_path = tmp_path / "cycles" / "cycle_0001_document_artifacts.json"
    artifact_dir = tmp_path / "document_artifacts" / "cycle_0001"
    binary_path = artifact_dir / "AZ_01_18-04.pdf"
    text_path = artifact_dir / "AZ_01_18-04.txt"

    assert artifact_summary["status"] == "completed"
    assert artifact_summary["target_count"] == 1
    assert artifact_summary["successful_count"] == 1
    assert artifact_summary["artifact_path"] == str(manifest_path)
    assert documents_summary["processed_document_urls"] == 1
    assert documents_summary["states_with_document_rules"] == ["AZ"]
    assert documents_summary["states_with_candidate_document_gaps"] == []
    assert documents_summary["artifact_recovery"]["successful_document_urls"] == 1
    assert binary_path.exists()
    assert text_path.exists()
    assert binary_path.read_bytes() == b"%PDF-fake-content"
    assert "Arizona Title 18 extracted text" in text_path.read_text(encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["successful_count"] == 1
    assert manifest["entries"][0]["method_used"] == "playwright"
    assert manifest["entries"][0]["binary_document"] is True
    assert manifest["entries"][0]["preferred_methods"][0] == "playwright"
    assert str(binary_path) in manifest["entries"][0]["saved_files"]
    assert str(text_path) in manifest["entries"][0]["saved_files"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_recovers_rtf_text_with_processor(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py.processors.web_archiving import unified_web_scraper as scraper_module

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [{"state_code": "AZ", "statutes": [], "rules_count": 0}],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "AZ": {
                            "attempted": 2,
                            "success": 0,
                            "success_ratio": 0.0,
                            "fallback_count": 1,
                            "providers": {"playwright": 1},
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "AZ": {
                            "candidate_urls": 1,
                            "inspected_urls": 1,
                            "expanded_urls": 0,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "domains_seen": ["apps.azsos.gov"],
                            "parallel_prefetch": {"attempted": 1, "successful": 0, "rule_hits": 0},
                            "source_breakdown": {"candidate_document": 1},
                            "gap_summary": {
                                "missing_seed_hosts": ["apps.azsos.gov"],
                                "candidate_hosts_without_rules": ["apps.azsos.gov"],
                            },
                        }
                    },
                },
            },
        }

    async def _fake_scrape(self, url, method=None, **kwargs):
        return scraper_module.ScraperResult(
            url=url,
            title="18-04.rtf",
            text="",
            content="",
            method_used=ScraperMethod.PLAYWRIGHT,
            success=True,
            metadata={
                "method": "playwright_binary_fetch",
                "content_type": "application/rtf",
                "content_length": 24,
                "raw_bytes": b"{\\rtf1\\ansi Arizona rule}",
                "binary_document": True,
            },
        )

    async def _fake_extract_rtf_text(rtf_bytes):
        assert rtf_bytes.startswith(b"{\\rtf1")
        return "Arizona RTF recovered text"

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(scraper_module.UnifiedWebScraper, "scrape", _fake_scrape)
    monkeypatch.setattr(scraper_module.UnifiedWebScraper, "_extract_rtf_text", staticmethod(_fake_extract_rtf_text))

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=44,
            document_artifact_capture_enabled=True,
            document_artifact_state_limit=1,
            document_artifact_urls_per_state=1,
            document_artifact_max_total=1,
        )
    )

    summary = await daemon.run()

    artifact_summary = summary["latest_cycle"]["document_artifacts"]
    documents_summary = summary["latest_cycle"]["diagnostics"]["documents"]
    manifest_path = tmp_path / "cycles" / "cycle_0001_document_artifacts.json"
    artifact_dir = tmp_path / "document_artifacts" / "cycle_0001"
    binary_path = artifact_dir / "AZ_01_18-04.rtf"
    text_path = artifact_dir / "AZ_01_18-04.txt"

    assert artifact_summary["successful_count"] == 1
    assert documents_summary["processed_document_urls"] == 1
    assert documents_summary["states_with_document_rules"] == ["AZ"]
    assert documents_summary["artifact_recovery"]["by_processor"]["rtf_processor"] == 1
    assert binary_path.exists()
    assert text_path.exists()
    assert "Arizona RTF recovered text" in text_path.read_text(encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["entries"][0]["document_processor_method"] == "rtf_processor"
    assert manifest["entries"][0]["document_processor_error"] is None
    assert manifest["entries"][0]["preferred_methods"][0] == "playwright"


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_persists_html_artifacts_for_weak_states(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py.processors.web_archiving import unified_web_scraper as scraper_module

    called_urls = []

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "IN",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "IN": {
                            "attempted": 2,
                            "success": 0,
                            "success_ratio": 0.0,
                            "fallback_count": 0,
                            "providers": {"agentic_discovery": 2},
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "IN": {
                            "candidate_urls": 4,
                            "inspected_urls": 2,
                            "expanded_urls": 0,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://legislature.in.gov/regulations",
                                "https://legislature.in.gov/administrative-code",
                                "https://iar.iga.in.gov/code/current",
                                "https://iar.iga.in.gov/code/2024",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "domains_seen": ["iar.iga.in.gov"],
                            "parallel_prefetch": {"attempted": 2, "successful": 0, "rule_hits": 0},
                            "source_breakdown": {},
                            "gap_summary": {
                                "missing_seed_hosts": ["iar.iga.in.gov"],
                                "candidate_hosts_without_rules": ["iar.iga.in.gov"],
                            },
                            "timed_out": True,
                        }
                    },
                },
            },
        }

    async def _fake_scrape(self, url, method=None, **kwargs):
        called_urls.append(url)
        if "iar.iga.in.gov" not in url:
            raise AssertionError(f"artifact capture selected non-responsive candidate first: {url}")
        return scraper_module.ScraperResult(
            url=url,
            title="Indiana Administrative Code",
            text="Indiana administrative code rendered text",
            html="<html><body>Indiana administrative code rendered text</body></html>",
            content="Indiana administrative code rendered text",
            method_used=ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
            success=True,
            metadata={
                "method": "cloudflare_browser_rendering",
                "content_type": "text/html",
                "content_length": 64,
                "binary_document": False,
                "cloudflare_status": "success",
            },
        )

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(scraper_module.UnifiedWebScraper, "scrape", _fake_scrape)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["IN"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=47,
            document_artifact_capture_enabled=True,
            document_artifact_state_limit=1,
            document_artifact_urls_per_state=1,
            document_artifact_max_total=1,
        )
    )

    summary = await daemon.run()

    document_gap_report = summary["latest_cycle"]["document_gap_report"]
    artifact_summary = summary["latest_cycle"]["document_artifacts"]
    manifest_path = tmp_path / "cycles" / "cycle_0001_document_artifacts.json"
    artifact_dir = tmp_path / "document_artifacts" / "cycle_0001"
    text_path = artifact_dir / "IN_01_current.txt"
    html_path = artifact_dir / "IN_01_current.html"

    assert document_gap_report["states_with_candidate_document_gaps"] == []
    assert document_gap_report["states_with_artifact_candidates"] == ["IN"]
    assert document_gap_report["states"]["IN"]["top_candidate_urls"] == [
        "https://legislature.in.gov/regulations",
        "https://legislature.in.gov/administrative-code",
        "https://iar.iga.in.gov/code/current",
        "https://iar.iga.in.gov/code/2024",
    ]
    assert artifact_summary["status"] == "completed"
    assert artifact_summary["target_count"] == 1
    assert artifact_summary["successful_count"] == 1
    assert called_urls == ["https://iar.iga.in.gov/code/current"]
    assert text_path.exists()
    assert html_path.exists()
    assert "Indiana administrative code rendered text" in text_path.read_text(encoding="utf-8")
    assert "Indiana administrative code rendered text" in html_path.read_text(encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["entries"][0]["method_used"] == "cloudflare_browser_rendering"
    assert manifest["entries"][0]["binary_document"] is False
    assert str(text_path) in manifest["entries"][0]["saved_files"]
    assert str(html_path) in manifest["entries"][0]["saved_files"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_retries_html_artifacts_past_failed_candidates(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py.processors.web_archiving import unified_web_scraper as scraper_module

    called_urls = []

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [
                {
                    "state_code": "IN",
                    "statutes": [],
                    "rules_count": 0,
                }
            ],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "IN": {
                            "attempted": 2,
                            "success": 0,
                            "success_ratio": 0.0,
                            "fallback_count": 0,
                            "providers": {"agentic_discovery": 2},
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "IN": {
                            "candidate_urls": 2,
                            "inspected_urls": 2,
                            "expanded_urls": 0,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://legislature.in.gov/regulations",
                                "https://iar.iga.in.gov/code/current",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "domains_seen": [],
                            "parallel_prefetch": {"attempted": 2, "successful": 0, "rule_hits": 0},
                            "source_breakdown": {},
                            "gap_summary": {
                                "missing_seed_hosts": ["iar.iga.in.gov"],
                                "candidate_hosts_without_rules": ["iar.iga.in.gov", "legislature.in.gov"],
                            },
                            "timed_out": True,
                        }
                    },
                },
            },
        }

    async def _fake_scrape(self, url, method=None, **kwargs):
        called_urls.append(url)
        if "legislature.in.gov" in url:
            return scraper_module.ScraperResult(
                url=url,
                success=False,
                method_used=scraper_module.ScraperMethod.PLAYWRIGHT,
                metadata={"content_type": "text/html", "content_length": 0, "binary_document": False},
                errors=["dns failure"],
            )
        return scraper_module.ScraperResult(
            url=url,
            title="Indiana Administrative Code",
            text="Indiana administrative code rendered text",
            html="<html><body>Indiana administrative code rendered text</body></html>",
            content="Indiana administrative code rendered text",
            method_used=scraper_module.ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
            success=True,
            metadata={
                "method": "cloudflare_browser_rendering",
                "content_type": "text/html",
                "content_length": 64,
                "binary_document": False,
                "cloudflare_status": "success",
            },
        )

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(scraper_module.UnifiedWebScraper, "scrape", _fake_scrape)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["IN"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=53,
            document_artifact_capture_enabled=True,
            document_artifact_state_limit=1,
            document_artifact_urls_per_state=1,
            document_artifact_max_total=1,
        )
    )

    summary = await daemon.run()

    artifact_summary = summary["latest_cycle"]["document_artifacts"]
    manifest_path = tmp_path / "cycles" / "cycle_0001_document_artifacts.json"
    artifact_dir = tmp_path / "document_artifacts" / "cycle_0001"
    text_path = artifact_dir / "IN_02_current.txt"
    html_path = artifact_dir / "IN_02_current.html"

    assert artifact_summary["status"] == "completed"
    assert artifact_summary["target_count"] == 2
    assert artifact_summary["successful_count"] == 1
    assert called_urls == [
        "https://legislature.in.gov/regulations",
        "https://iar.iga.in.gov/code/current",
    ]
    assert text_path.exists()
    assert html_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["target_count"] == 2
    assert manifest["successful_count"] == 1
    assert manifest["entries"][0]["success"] is False
    assert manifest["entries"][1]["success"] is True
    assert manifest["entries"][1]["method_used"] == "cloudflare_browser_rendering"
    assert str(text_path) in manifest["entries"][1]["saved_files"]
    assert str(html_path) in manifest["entries"][1]["saved_files"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_uses_recovery_directives_to_prioritize_cloudflare(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py.processors.web_archiving import unified_web_scraper as scraper_module

    seen_method_orders = []

    async def _fake_scrape_state_admin_rules(**kwargs):
        return {
            "status": "partial_success",
            "data": [{"state_code": "IN", "statutes": [], "rules_count": 0}],
            "metadata": {
                "base_metadata": {
                    "fetch_analytics_by_state": {
                        "IN": {
                            "attempted": 2,
                            "success": 0,
                            "success_ratio": 0.0,
                            "fallback_count": 0,
                            "providers": {"agentic_discovery": 2},
                        }
                    }
                },
                "agentic_report": {
                    "status": "success",
                    "per_state": {
                        "IN": {
                            "candidate_urls": 1,
                            "inspected_urls": 1,
                            "expanded_urls": 0,
                            "fetched_rules": 0,
                            "top_candidate_urls": [
                                "https://iar.iga.in.gov/code/current",
                            ],
                            "format_counts": {"html": 0, "pdf": 0, "rtf": 0},
                            "domains_seen": ["iar.iga.in.gov"],
                            "parallel_prefetch": {"attempted": 1, "successful": 0, "rule_hits": 0},
                            "source_breakdown": {},
                            "gap_summary": {
                                "missing_seed_hosts": ["iar.iga.in.gov"],
                                "candidate_hosts_without_rules": ["iar.iga.in.gov"],
                            },
                            "cloudflare_status": "browser_challenge",
                            "cloudflare_browser_challenge_detected": True,
                            "cloudflare_http_status": 403,
                            "cloudflare_record_status": "errored",
                        }
                    },
                },
            },
        }

    async def _fake_scrape(self, url, method=None, **kwargs):
        seen_method_orders.append([item.value for item in self.config.preferred_methods])
        return scraper_module.ScraperResult(
            url=url,
            title="Indiana Administrative Code",
            text="Indiana administrative code rendered text",
            html="<html><body>Indiana administrative code rendered text</body></html>",
            content="Indiana administrative code rendered text",
            method_used=ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
            success=True,
            metadata={
                "method": "cloudflare_browser_rendering",
                "content_type": "text/html",
                "content_length": 64,
                "binary_document": False,
                "cloudflare_status": "success",
            },
        )

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(scraper_module.UnifiedWebScraper, "scrape", _fake_scrape)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["IN"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=54,
            document_artifact_capture_enabled=True,
            document_artifact_state_limit=1,
            document_artifact_urls_per_state=1,
            document_artifact_max_total=1,
        )
    )

    summary = await daemon.run()

    artifact_summary = summary["latest_cycle"]["document_artifacts"]

    assert artifact_summary["successful_count"] == 1
    assert seen_method_orders
    assert seen_method_orders[0][0] == "cloudflare_browser_rendering"
    assert "playwright" in seen_method_orders[0]


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

    def _fake_preflight(self):
        return {"available": True, "backend": "KuboCLIBackend", "command": "ipfs"}

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_run_llm_router_review", _fake_router_review)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_rank_tactics_with_embeddings", _fake_embeddings_ranking)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_router_ipfs_persist_preflight", _fake_preflight)
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
    assert "Arizona administrative code pdf title 18" in critic["query_hints"]
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
    assert summary["latest_cycle"]["router_assist"]["llm_review"]["status"] == "unavailable"
    assert "timed out" in summary["latest_cycle"]["router_assist"]["llm_review"]["error"]
    assert (tmp_path / "cycles" / "cycle_0001.json").exists()


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_router_ipfs_timeout_does_not_block_cycle(monkeypatch, tmp_path):
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

    async def _slow_ipfs_persist(self, *, cycle_index, report, corpus_key):
        _ = (self, cycle_index, report, corpus_key)
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)
            return {"status": "success", "cid": "late-router-review"}
        return {"status": "success", "cid": "late-router-review"}

    def _preflight(self):
        return {"available": True, "backend": "KuboCLIBackend", "command": "ipfs"}

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_persist_router_assist_to_ipfs", _slow_ipfs_persist)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_router_ipfs_persist_preflight", _preflight)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            router_ipfs_timeout_seconds=0.01,
            random_seed=43,
        )
    )

    summary = await daemon.run()

    assert summary["status"] == "success"
    assert summary["latest_cycle"]["router_assist"]["status"] == "completed"
    assert summary["latest_cycle"]["router_assist"]["ipfs_persist"]["status"] == "error"
    assert "timed out" in summary["latest_cycle"]["router_assist"]["ipfs_persist"]["error"]
    assert (tmp_path / "cycles" / "cycle_0001.json").exists()
    await asyncio.sleep(0.25)


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_skips_unpinned_embeddings_ranking(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py import embeddings_router as embeddings_router_module

    def _should_not_run(*args, **kwargs):
        raise AssertionError("unconfigured embeddings ranking should be skipped")

    monkeypatch.delenv("LEGAL_DAEMON_ROUTER_EMBEDDINGS_PROVIDER", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_EMBEDDINGS_PROVIDER", raising=False)
    monkeypatch.delenv("LEGAL_DAEMON_ROUTER_EMBEDDINGS_ALLOW_UNPINNED", raising=False)
    monkeypatch.setattr(embeddings_router_module, "embed_texts_batched", _should_not_run)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
        )
    )

    result = daemon._rank_tactics_with_embeddings(
        daemon.config.tactic_profiles["router_assisted"],
        diagnostics={},
        critic={"summary": "coverage gaps"},
    )

    assert result is None


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_router_llm_empty_accelerate_response_is_unavailable(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py import llm_router as llm_router_module

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

    def _fake_generate_text(prompt, **kwargs):
        raise RuntimeError("ipfs_accelerate_py provider did not return generated text")

    def _fake_embeddings_ranking(self, tactic, diagnostics, critic):
        return [{"tactic": "router_assisted", "score": 0.88}]

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(llm_router_module, "generate_text", _fake_generate_text)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_rank_tactics_with_embeddings", _fake_embeddings_ranking)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=59,
            router_llm_timeout_seconds=0.0,
        )
    )

    summary = await daemon.run()

    router_assist = summary["latest_cycle"]["router_assist"]
    assert router_assist["status"] == "completed"
    assert router_assist["llm_review"]["status"] == "unavailable"
    assert router_assist["llm_review"]["reason"] == "accelerate-empty-response"
    assert router_assist["embeddings_ranking"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_router_llm_accelerate_no_remote_fallback_is_unavailable(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py import llm_router as llm_router_module

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

    def _fake_generate_text(prompt, **kwargs):
        raise RuntimeError("Accelerate not available, using local fallback")

    def _fake_embeddings_ranking(self, tactic, diagnostics, critic):
        return [{"tactic": "router_assisted", "score": 0.88}]

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(llm_router_module, "generate_text", _fake_generate_text)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_rank_tactics_with_embeddings", _fake_embeddings_ranking)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=59,
            router_llm_timeout_seconds=0.0,
        )
    )

    summary = await daemon.run()

    router_assist = summary["latest_cycle"]["router_assist"]
    assert router_assist["status"] == "completed"
    assert router_assist["llm_review"]["status"] == "unavailable"
    assert router_assist["llm_review"]["reason"] == "accelerate-no-remote-fallback"
    assert router_assist["embeddings_ranking"]


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_router_llm_timeout_is_unavailable(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    async def _fake_review(self, *, tactic, diagnostics, critic):
        _ = (self, tactic, diagnostics, critic)
        await asyncio.sleep(0.05)
        return {"status": "success"}

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            router_llm_timeout_seconds=0.01,
        )
    )

    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_run_llm_router_review", _fake_review)

    result = await daemon._run_router_llm_review_with_timeout(
        tactic=daemon.config.tactic_profiles["router_assisted"],
        diagnostics={},
        critic={},
    )

    assert result == {
        "status": "unavailable",
        "error": "timed out after 0.0 seconds",
        "reason": "timed-out",
    }


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_router_llm_env_overrides_forward_to_router(monkeypatch, tmp_path):
    from ipfs_datasets_py import llm_router as llm_router_module
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module

    captured: dict[str, object] = {}

    def _fake_generate_text(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = dict(kwargs)
        return json.dumps(
            {
                "recommended_next_tactics": ["router_assisted"],
                "priority_states": ["AZ"],
                "query_hints": ["arizona admin code"],
                "rationale": "ok",
            }
        )

    monkeypatch.setattr(llm_router_module, "generate_text", _fake_generate_text)
    monkeypatch.setenv("LEGAL_DAEMON_ROUTER_LLM_PROVIDER", "hf_inference_api")
    monkeypatch.setenv("LEGAL_DAEMON_ROUTER_LLM_MODEL", "deepseek-ai/DeepSeek-R1:preferred")
    monkeypatch.setenv("LEGAL_DAEMON_ROUTER_LLM_HF_PROVIDER", "auto")
    monkeypatch.setenv("LEGAL_DAEMON_ROUTER_LLM_HF_BILL_TO", "Publicus")

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            router_llm_timeout_seconds=0.0,
        )
    )

    result = await daemon._run_llm_router_review(
        tactic=daemon.config.tactic_profiles["router_assisted"],
        diagnostics={},
        critic={},
    )

    assert result["status"] == "success"
    assert result["provider"] == "hf_inference_api"
    assert result["model_name"] == "deepseek-ai/DeepSeek-R1:preferred"
    assert result["hf_provider"] == "auto"
    assert result["hf_bill_to"] == "Publicus"
    assert captured["kwargs"] == {
        "provider": "hf_inference_api",
        "model_name": "deepseek-ai/DeepSeek-R1:preferred",
        "hf_provider": "auto",
        "hf_bill_to": "Publicus",
        "hf_use_chat_completions": True,
        "temperature": 0.2,
        "max_tokens": 350,
        "allow_local_fallback": True,
    }


@pytest.mark.asyncio
async def test_state_admin_rules_agentic_daemon_skips_router_ipfs_persist_when_cli_missing(monkeypatch, tmp_path):
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

    async def _fake_router_review(self, *, tactic, diagnostics, critic):
        return {
            "status": "success",
            "recommended_next_tactics": ["router_assisted", "document_first"],
            "priority_states": ["AZ"],
            "query_hints": ["Arizona administrative code pdf title 18"],
            "rationale": "Document candidates remain unresolved.",
        }

    def _fake_embeddings_ranking(self, tactic, diagnostics, critic):
        return [{"tactic": "router_assisted", "score": 0.9}]

    def _fake_preflight(self):
        return {
            "available": False,
            "reason": "ipfs-cli-missing",
            "backend": "KuboCLIBackend",
            "command": "ipfs",
        }

    async def _should_not_run(self, *, cycle_index, report, corpus_key):
        raise AssertionError("router IPFS persist should be skipped when preflight fails")

    monkeypatch.setattr(daemon_module, "scrape_state_admin_rules", _fake_scrape_state_admin_rules)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_run_llm_router_review", _fake_router_review)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_rank_tactics_with_embeddings", _fake_embeddings_ranking)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_router_ipfs_persist_preflight", _fake_preflight)
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_persist_router_assist_to_ipfs", _should_not_run)

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
            random_seed=61,
        )
    )

    summary = await daemon.run()

    router_assist = summary["latest_cycle"]["router_assist"]
    assert router_assist["status"] == "completed"
    assert router_assist["ipfs_persist"]["status"] == "skipped"
    assert router_assist["ipfs_persist"]["reason"] == "ipfs-cli-missing"
    assert router_assist["ipfs_persist"]["backend"] == "KuboCLIBackend"


def test_router_ipfs_persist_preflight_bootstraps_ipfs_kit_when_cli_missing(monkeypatch, tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers import state_laws_agentic_daemon as daemon_module
    from ipfs_datasets_py import ipfs_backend_router

    KuboCLIBackend = type("KuboCLIBackend", (), {"_cmd": "ipfs"})

    def _fake_bootstrap(self):
        return {
            "available": True,
            "backend": "_IPFSKitBackend",
            "command": None,
            "install_attempted": True,
            "installer": "/tmp/fake-install.py",
        }

    monkeypatch.setattr(daemon_module.shutil, "which", lambda cmd: None if cmd == "ipfs" else "/usr/bin/true")
    monkeypatch.setattr(ipfs_backend_router, "get_ipfs_backend", lambda *args, **kwargs: KuboCLIBackend())
    monkeypatch.setattr(daemon_module.StateLawsAgenticDaemon, "_attempt_router_ipfs_kit_bootstrap", _fake_bootstrap)
    monkeypatch.setenv("LEGAL_DAEMON_ROUTER_IPFS_AUTO_BOOTSTRAP", "1")

    daemon = daemon_module.StateLawsAgenticDaemon(
        daemon_module.StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=["AZ"],
            output_dir=str(tmp_path),
            max_cycles=1,
            archive_warmup_urls=0,
        )
    )

    result = daemon._router_ipfs_persist_preflight()

    assert result["available"] is True
    assert result["backend"] == "_IPFSKitBackend"
    assert result["install_attempted"] is True



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
