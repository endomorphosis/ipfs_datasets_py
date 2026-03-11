import json

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

    state_payload = json.loads((tmp_path / "daemon_state.json").read_text(encoding="utf-8"))
    assert state_payload["cycle_count"] == 1
    assert state_payload["best_tactic"]["score"] == summary["latest_cycle"]["critic_score"]


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
    assert summary["latest_cycle"]["critic"]["recommended_next_tactics"]


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
    assert diagnostics["documents"]["states_with_candidate_document_gaps"] == ["AZ"]
    assert diagnostics["gap_analysis"]["weak_states"] == ["AZ"]
    assert any(item.startswith("document-candidate-gaps:AZ") for item in critic["issues"])
    assert "document_first" in critic["recommended_next_tactics"]
    assert document_gap_report["states_with_candidate_document_gaps"] == ["AZ"]
    assert document_gap_report["states"]["AZ"]["candidate_document_format_counts"] == {"pdf": 1, "rtf": 1}
    assert document_gap_report["states"]["AZ"]["top_candidate_document_urls"] == [
        "https://apps.azsos.gov/public_services/Title_18/18-04.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    ]
    assert summary["latest_cycle"]["document_gap_report_path"] == str(document_gap_report_path)
    persisted_report = json.loads(document_gap_report_path.read_text(encoding="utf-8"))
    assert persisted_report["cycle"] == 1
    assert persisted_report["states_with_candidate_document_gaps"] == ["AZ"]


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