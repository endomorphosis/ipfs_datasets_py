import json
import asyncio
from pathlib import Path
import ipfs_datasets_py.ipfs_backend_router as ipfs_router

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StatuteMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
    FetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    _aggregate_fetch_analytics,
    _compute_state_quality_metrics,
    _compute_coverage_summary,
    _compute_etl_readiness_summary,
    _filter_strict_full_text_statutes,
    _trim_scraped_statutes_to_max,
    _write_state_jsonld_files,
)


class _DummyStateScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.gov"

    def get_code_list(self):
        return []

    async def scrape_code(self, code_name: str, code_url: str):
        return []


class _CountingStateScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.gov"

    def get_code_list(self):
        return [{"name": "Example Code", "url": "https://example.gov/code"}]

    async def scrape_code(self, code_name: str, code_url: str):
        return [
            NormalizedStatute(
                state_code="XY",
                state_name="Example State",
                statute_id=f"Code § {idx}",
                section_number=str(idx),
                section_name=f"Section {idx}",
                full_text=f"Section {idx}",
                source_url=f"https://example.gov/code/{idx}",
            )
            for idx in range(1, 4)
        ]


def test_enrich_statute_structure_includes_uscode_style_fields():
    scraper = _DummyStateScraper("XY", "Example State")

    statute = NormalizedStatute(
        state_code="XY",
        state_name="Example State",
        statute_id="Code § 10-1",
        code_name="Example Code",
        title_number="10",
        title_name="General Provisions",
        chapter_number="1",
        chapter_name="Definitions",
        section_number="10-1",
        section_name="Definitions",
        full_text=(
            "Section 10-1: General definitions and scope. "
            "(a) This chapter applies to all agencies. "
            "(1) Agency means any executive office. "
            "(A) Includes boards and commissions. "
            "See 42 U.S.C. 1983 and Pub. L. 117-58, 135 Stat. 429."
        ),
        source_url="https://example.gov/code/10-1",
        metadata=StatuteMetadata(enacted_year="2025"),
    )

    enriched = scraper._enrich_statute_structure(statute)
    structured = enriched.structured_data

    assert isinstance(structured.get("preamble"), str)
    assert structured.get("preamble")
    assert isinstance(structured.get("subsections"), list)
    assert len(structured.get("subsections")) > 0

    citations = structured.get("citations")
    assert isinstance(citations, dict)
    assert citations.get("usc_citations")
    assert citations.get("public_laws")
    assert citations.get("statutes_at_large")

    jsonld = structured.get("jsonld")
    assert isinstance(jsonld, dict)
    assert jsonld.get("@type") == "Legislation"
    assert jsonld.get("preamble") == structured.get("preamble")
    assert jsonld.get("subsections") == structured.get("subsections")
    assert isinstance(jsonld.get("chapter"), dict)


def test_scrape_all_limits_hydration_to_max_statutes(monkeypatch):
    scraper = _CountingStateScraper("XY", "Example State")
    hydrate_calls = []

    async def _fake_hydrate(statute):
        hydrate_calls.append(statute.statute_id)

    monkeypatch.setattr(scraper, "_hydrate_statute_text_if_needed", _fake_hydrate)
    monkeypatch.setattr(scraper, "_is_low_quality_statute_record", lambda _statute: False)
    monkeypatch.setattr(scraper, "_enrich_statute_structure", lambda statute: statute)

    rows = asyncio.run(scraper.scrape_all(max_statutes=1, hydrate_statute_text=True))

    assert len(rows) == 1
    assert hydrate_calls == ["Code § 1"]


def test_hydrate_statute_text_uses_pdf_processor(monkeypatch):
    scraper = _DummyStateScraper("XY", "Example State")

    statute = NormalizedStatute(
        state_code="XY",
        state_name="Example State",
        statute_id="Code § 12-1",
        section_number="12-1",
        section_name="Definitions",
        full_text="Section 12-1: Definitions",
        source_url="https://example.gov/statutes/12-1.pdf",
    )

    async def _fake_fetch(*_args, **_kwargs):
        return b"%PDF-1.4 fake-pdf-content"

    async def _fake_extract_pdf(_pdf_bytes):
        return "Section 12-1 Definitions. This section contains substantive legal text. " + ("x" * 220)

    monkeypatch.setattr(scraper, "_fetch_page_content_with_archival_fallback", _fake_fetch)
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.web_archiving.unified_web_scraper.UnifiedWebScraper._extract_pdf_text",
        _fake_extract_pdf,
    )

    asyncio.run(scraper._hydrate_statute_text_if_needed(statute))

    assert len(statute.full_text or "") >= 160
    assert statute.structured_data.get("method_used") == "pdf_processor"
    assert statute.structured_data.get("source_content_type") == "application/pdf"


def test_fetch_page_content_reuses_ipfs_page_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED", "1")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page_cache"))

    scraper = _DummyStateScraper("XY", "Example State")
    url = "https://example.gov/code/10-1"
    stored_payloads = {}
    call_counts = {"fetch": 0, "add": 0, "cat": 0}

    async def _fake_unified_fetch(*_args, **_kwargs):
        call_counts["fetch"] += 1
        return b"fresh-body"

    def _fake_add_bytes(data: bytes, *, pin: bool = True):
        call_counts["add"] += 1
        stored_payloads["cid-1"] = bytes(data)
        return "cid-1"

    def _fake_cat(cid: str):
        call_counts["cat"] += 1
        return stored_payloads[cid]

    monkeypatch.setattr(scraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr(ipfs_router, "add_bytes", _fake_add_bytes)
    monkeypatch.setattr(ipfs_router, "cat", _fake_cat)

    first = asyncio.run(scraper._fetch_page_content_with_archival_fallback(url))
    second = asyncio.run(scraper._fetch_page_content_with_archival_fallback(url))

    assert first == b"fresh-body"
    assert second == b"fresh-body"
    assert call_counts["fetch"] == 1
    assert call_counts["add"] == 1
    assert call_counts["cat"] == 1

    index_path = tmp_path / "page_cache" / "index.json"
    assert index_path.exists()
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index_payload) == 1


def test_fetch_page_content_uses_ipfs_page_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "page_cache"))
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED", "1")

    cache_store = {}

    def _fake_add_bytes(data, *, pin=True):
        cid = f"cid-{len(cache_store) + 1}"
        cache_store[cid] = bytes(data)
        return cid

    def _fake_cat(cid):
        return cache_store[cid]

    monkeypatch.setattr("ipfs_datasets_py.ipfs_backend_router.add_bytes", _fake_add_bytes)
    monkeypatch.setattr("ipfs_datasets_py.ipfs_backend_router.cat", _fake_cat)

    scraper = _DummyStateScraper("XY", "Example State")
    url = "https://example.gov/code/10-1"
    payload = b"cached legal text"

    asyncio.run(
        scraper._store_page_bytes_in_ipfs_cache(
            url=url,
            payload=payload,
            provider="unit_test",
        )
    )

    async def _unexpected_fetch(*_args, **_kwargs):
        raise AssertionError("live fetch should not run when cache entry exists")

    monkeypatch.setattr(scraper, "_fetch_page_content_with_unified_api", _unexpected_fetch)

    result = asyncio.run(scraper._fetch_page_content_with_archival_fallback(url))

    assert result == payload
    analytics = scraper.get_fetch_analytics_snapshot()
    assert analytics["cache_hits"] == 1
    assert analytics["cache_writes"] == 1
    assert analytics["providers"]["ipfs_page_cache"] == 1


def test_fetch_page_content_skips_object_moved_placeholder(monkeypatch):
    scraper = _DummyStateScraper("XY", "Example State")

    async def _fake_unified_fetch(*_args, **_kwargs):
        return (
            b"<head><title>Document Moved</title></head>"
            b"<body><h1>Object Moved</h1><a href='https://example.gov/old.pdf'>here</a></body>"
        )

    class _FakeResponse:
        status = 200

        def read(self):
            return b"<html><body><p>Actual legal page</p></body></html>"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeArchivalFetchClient:
        def __init__(self, *args, **kwargs):
            pass

        async def fetch_with_fallback(self, url):
            return type("_Fetched", (), {"content": b"", "source": "archival_fallback"})()

    async def _fake_store_page_bytes_in_ipfs_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scraper, "_fetch_page_content_with_unified_api", _fake_unified_fetch)
    monkeypatch.setattr(scraper, "_store_page_bytes_in_ipfs_cache", _fake_store_page_bytes_in_ipfs_cache)
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch.ArchivalFetchClient",
        _FakeArchivalFetchClient,
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(),
    )

    result = asyncio.run(scraper._fetch_page_content_with_archival_fallback("https://example.gov/code/10-1"))

    assert b"Actual legal page" in result
    analytics = scraper.get_fetch_analytics_snapshot()
    assert "unified_scraper" not in analytics["providers"] or analytics["providers"]["unified_scraper"] == 1
    assert any(name in analytics["providers"] for name in ("requests_direct", "direct", "archival_fallback"))


def test_archival_fetch_skips_common_crawl_unless_enabled(monkeypatch):
    client = ArchivalFetchClient(request_timeout_seconds=1)
    target_url = "https://example.gov/code/10-1"

    def _unexpected_common_crawl(_url):
        raise AssertionError("Common Crawl should be opt-in for state scraper archival fallback")

    def _direct_fetch(url):
        return FetchResult(
            url=url,
            content=b"<html><body>direct statute page</body></html>",
            source="direct",
            fetched_at="2026-04-19T00:00:00+00:00",
            status_code=200,
        )

    monkeypatch.delenv("LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL", raising=False)
    monkeypatch.setattr(client, "_fetch_from_common_crawl", _unexpected_common_crawl)
    monkeypatch.setattr(client, "_fetch_direct", _direct_fetch)

    result = asyncio.run(client.fetch_with_fallback(target_url))

    assert result.source == "direct"
    assert result.content == b"<html><body>direct statute page</body></html>"


def test_write_state_jsonld_files_emits_per_state_jsonld(tmp_path: Path):
    payload = {
        "@context": {"@vocab": "https://schema.org/"},
        "@type": "Legislation",
        "@id": "urn:state:xy:statute:Code-10-1",
        "name": "Definitions",
    }
    scraped_statutes = [
        {
            "state_code": "XY",
            "statutes": [
                {
                    "statute_id": "Code § 10-1",
                    "structured_data": {"jsonld": payload},
                }
            ],
        }
    ]

    files = _write_state_jsonld_files(scraped_statutes, tmp_path)

    assert len(files) == 1
    out_path = Path(files[0])
    assert out_path.exists()

    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc.get("@type") == "Legislation"
    assert doc.get("@id") == payload["@id"]


def test_filter_strict_full_text_statutes_removes_short_records():
    good = NormalizedStatute(
        state_code="XY",
        state_name="Example State",
        statute_id="Code § 11-1",
        full_text="A" * 500,
        source_url="https://example.gov/11-1",
    )
    bad = NormalizedStatute(
        state_code="XY",
        state_name="Example State",
        statute_id="Code § 11-2",
        full_text="Too short",
        source_url="https://example.gov/11-2",
    )

    kept, removed = _filter_strict_full_text_statutes([good, bad], min_full_text_chars=300)

    assert removed == 1
    assert len(kept) == 1
    assert kept[0].statute_id == "Code § 11-1"


def test_filter_strict_full_text_statutes_removes_scaffold_navigation_records():
    scaffold = {
        "section_number": "Section-23",
        "section_name": "POST AUDIT DIVISION",
        "full_text": "Section Section-23: POST AUDIT DIVISION",
        "source_url": "http://www.wvlegislature.gov/Joint/postaudit.cfm",
    }
    valid = {
        "section_number": "9A.32.030",
        "section_name": "Murder in the first degree",
        "full_text": "Section 9A.32.030. A person is guilty of murder in the first degree when... " + ("x" * 500),
        "source_url": "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.32.030",
    }

    kept, removed = _filter_strict_full_text_statutes([scaffold, valid], min_full_text_chars=280)

    assert removed == 1
    assert len(kept) == 1
    assert kept[0]["section_number"] == "9A.32.030"


def test_compute_state_quality_metrics_tracks_scaffold_ratio():
    statutes = [
        {
            "section_number": "Section-1",
            "section_name": "Home",
            "full_text": "Section Section-1: Home",
            "source_url": "https://example.gov/news",
        },
        {
            "section_number": "10-1",
            "section_name": "Definitions",
            "full_text": "Section 10-1. Definitions. " + ("valid body text " * 40),
            "source_url": "https://example.gov/code/10-1",
        },
    ]

    metrics = _compute_state_quality_metrics(statutes)

    assert metrics["total"] == 2
    assert metrics["scaffold_ratio"] == 0.5


def test_compute_state_quality_metrics_does_not_flag_short_rule_metadata_page_as_nav_like():
    statutes = [
        {
            "section_number": "A1",
            "section_name": "INTRODUCTION AND DEFINITIONS | Montana SOS",
            "full_text": (
                "Administrative Rules of Montana\n"
                "Back\n"
                "1.3.201 INTRODUCTION AND DEFINITIONS\n"
                "Rule Version 27282\n"
                "Active Version\n"
                "Effective 01/16/2009 - Present\n"
                "Rule History Eff. 12/31/72; AMD, 2009 MAR p. 7, Eff. 1/16/09.\n"
                "References 2-4-101, MCA Short Title -- Purpose -- Exception\n"
                "Referenced by 2025-195.1 Implementation of Senate Bill 315 (2025)\n"
                "View More\n"
                "Home"
            ),
            "source_url": "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/policies/51f36d4d-ca58-49bf-bf41-e1881edd4865",
        }
    ]

    metrics = _compute_state_quality_metrics(statutes)

    assert metrics["total"] == 1
    assert metrics["nav_like_ratio"] == 0.0
    assert metrics["scaffold_ratio"] == 0.0


def test_trim_scraped_statutes_to_max_truncates_in_state_order():
    scraped = [
        {
            "state_code": "AA",
            "statutes": [
                {"section_number": "1", "section_name": "Section 1", "full_text": "A" * 500},
                {"section_number": "2", "section_name": "Section 2", "full_text": "B" * 500},
            ],
        },
        {
            "state_code": "BB",
            "statutes": [
                {"section_number": "1", "section_name": "Section 1", "full_text": "C" * 500},
            ],
        },
    ]

    trimmed, total = _trim_scraped_statutes_to_max(scraped, max_statutes=2)

    assert total == 2
    assert len(trimmed) == 1
    assert trimmed[0]["state_code"] == "AA"
    assert len(trimmed[0]["statutes"]) == 2


def test_compute_coverage_summary_detects_zero_and_missing_states():
    selected_states = ["AA", "BB", "CC"]
    scraped_statutes = [
        {"state_code": "AA", "statutes": [{"section_number": "1"}]},
        {"state_code": "BB", "statutes": [], "error": "failed"},
    ]

    summary = _compute_coverage_summary(
        selected_states=selected_states,
        scraped_statutes=scraped_statutes,
        errors=["BB failed"],
    )

    assert summary["states_targeted"] == 3
    assert summary["states_returned"] == 2
    assert summary["states_with_nonzero_statutes"] == 1
    assert summary["zero_statute_states"] == ["BB"]
    assert summary["error_states"] == ["BB"]
    assert summary["missing_states"] == ["CC"]
    assert summary["coverage_gap_states"] == ["BB", "CC"]
    assert summary["full_coverage"] is False


def test_aggregate_fetch_analytics_combines_provider_counts():
    metrics = _aggregate_fetch_analytics(
        {
            "OK": {
                "attempted": 5,
                "success": 3,
                "fallback_count": 2,
                "providers": {"unified_scraper": 3, "requests_direct": 2},
            },
            "SC": {
                "attempted": 4,
                "success": 4,
                "fallback_count": 1,
                "providers": {"unified_scraper": 4},
            },
        }
    )

    assert metrics["states_with_fetch_analytics"] == 2
    assert metrics["attempted"] == 9
    assert metrics["success"] == 7
    assert metrics["fallback_count"] == 3
    assert metrics["success_ratio"] == 0.778
    assert metrics["providers"]["unified_scraper"] == 7
    assert metrics["providers"]["requests_direct"] == 2


def test_compute_etl_readiness_summary_reports_kg_thresholds():
    scraped_statutes = [
        {
            "state_code": "AA",
            "statutes": [
                {
                    "full_text": "Section 1. " + ("valid law text " * 40),
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "AA-1",
                            "name": "Section 1",
                            "sectionNumber": "1",
                            "text": "Section 1. " + ("valid law text " * 40),
                        },
                        "citations": {"usc_citations": ["18 U.S.C. 1001"]},
                    },
                },
                {
                    "full_text": "Section 2. " + ("valid law text " * 40),
                    "structured_data": {
                        "jsonld": {
                            "@type": "Legislation",
                            "identifier": "AA-2",
                            "name": "Section 2",
                            "sectionNumber": "2",
                            "text": "Section 2. " + ("valid law text " * 40),
                        },
                        "citations": {"public_laws": ["Pub. L. 117-58"]},
                    },
                },
            ],
        },
        {
            "state_code": "BB",
            "statutes": [],
        },
    ]

    summary = _compute_etl_readiness_summary(scraped_statutes)

    assert summary["states_processed"] == 2
    assert summary["states_with_zero_statutes"] == 1
    assert summary["states_with_jsonld"] == 1
    assert summary["total_statutes"] == 2
    assert summary["full_text_ratio"] == 1.0
    assert summary["jsonld_ratio"] == 1.0
    assert summary["citation_ratio"] == 1.0
    assert summary["ready_for_kg_etl"] is True
