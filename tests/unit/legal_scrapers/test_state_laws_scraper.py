import asyncio
import hashlib
import inspect
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers import (
    state_laws_scraper as scraper_module,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
)


def test_default_full_text_policy_preserves_short_statutes():
    parameter = inspect.signature(scraper_module.scrape_state_laws).parameters[
        "min_full_text_chars"
    ]
    assert scraper_module.DEFAULT_MIN_FULL_TEXT_CHARS == 1
    assert parameter.default == scraper_module.DEFAULT_MIN_FULL_TEXT_CHARS


def test_state_laws_scraper_builds_recovery_section_urls():
    assert (
        scraper_module.build_state_law_section_url("MN", "518.17", code_name="Statutes")
        == "https://www.revisor.mn.gov/statutes/cite/518.17"
    )
    assert (
        scraper_module.build_state_law_section_url("OR", "801.545")
        == "https://oregon.public.law/statutes/ors_801.545"
    )
    assert (
        scraper_module.build_state_law_section_url("CA", "3011", code_name="Fam. Code")
        == "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=FAM&sectionNum=3011"
    )
    assert (
        scraper_module.build_state_law_section_url("NY", "651", code_name="Fam. Ct. Act")
        == "https://www.nysenate.gov/legislation/laws/FCT/651"
    )
    assert (
        scraper_module.build_state_law_section_url("TX", "153.002", code_name="Fam. Code")
        == "https://statutes.capitol.texas.gov/Docs/FA/htm/FA.153.htm#153.002"
    )
    assert (
        scraper_module.build_state_law_section_url("FL", "61.13", code_name="Fla. Stat.")
        == "https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0061/Sections/0061.13.html"
    )
    assert (
        scraper_module.build_state_law_section_url("IL", "602.7", code_name="750 ILCS 5")
        == "https://www.ilga.gov/documents/legislation/ilcs/documents/075000050K602.7.htm"
    )
    assert (
        scraper_module.build_state_law_section_url("PA", "5328", code_name="23 Pa.C.S.")
        == "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/23/00.053.028.000..HTM"
    )
    assert (
        scraper_module.build_state_law_section_url("AZ", "13-1203", code_name="Ariz. Rev. Stat.")
        == "https://www.azleg.gov/ars/13/01203.htm"
    )
    assert (
        scraper_module.build_state_law_section_url("IN", "35-42-2-1", code_name="Ind. Code")
        == "https://law.justia.com/codes/indiana/title-35/article-42/chapter-2/section-35-42-2-1/"
    )
    assert (
        scraper_module.build_state_law_section_url("KS", "21-5413", code_name="Kan. Stat.")
        == "https://www.ksrevisor.gov/statutes/chapters/ch21/021_054_0013.html"
    )
    assert (
        scraper_module.build_state_law_section_url("ME", "17-A:207", code_name="Me. Rev. Stat.")
        == "https://www.mainelegislature.org/legis/statutes/17-A/title17-Asec207.html"
    )
    assert (
        scraper_module.build_state_law_section_url("MT", "45-5-201", code_name="Mont. Code")
        == "https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0020/section_0010/0450-0050-0020-0010.html"
    )
    assert (
        scraper_module.build_state_law_section_url("NC", "14-33", code_name="N.C. Gen. Stat.")
        == "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_14/GS_14-33.html"
    )
    assert (
        scraper_module.build_state_law_section_url("OH", "2903.13", code_name="Ohio Rev. Code")
        == "https://codes.ohio.gov/ohio-revised-code/section-2903.13"
    )
    assert (
        scraper_module.build_state_law_section_url("SC", "16-3-600", code_name="S.C. Code")
        == "https://www.scstatehouse.gov/code/t16c003.php#16-3-600"
    )
    assert (
        scraper_module.build_state_law_section_url("VA", "18.2-57", code_name="Va. Code")
        == "https://law.lis.virginia.gov/vacode/title18.2/chapter4/section18.2-57/"
    )
    assert (
        scraper_module.build_state_law_section_url("VT", "13-1023", code_name="Vt. Stat.")
        == "https://legislature.vermont.gov/statutes/section/13/019/01023"
    )
    assert (
        scraper_module.build_state_law_section_url("WA", "9A.36.041", code_name="Wash. Rev. Code")
        == "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.36.041"
    )
    assert (
        scraper_module.build_state_law_section_url("MI", "750.81", code_name="Mich. Comp. Laws")
        == "https://legislature.mi.gov/Laws/MCL?objectName=mcl-750-81"
    )
    assert (
        scraper_module.build_state_law_section_url("WI", "940.19", code_name="Wis. Stat.")
        == "https://docs.legis.wisconsin.gov/statutes/statutes/940#940.19"
    )


def test_state_laws_scraper_recovery_section_url_edge_cases():
    assert scraper_module.build_state_law_section_url("", "518.17") == ""
    assert scraper_module.build_state_law_section_url("MN", "") == ""
    assert scraper_module.build_state_law_section_url("ZZ", "1.2") == ""
    assert scraper_module.build_state_law_section_url("FL", "abc", code_name="Fla. Stat.") == ""
    assert scraper_module.build_state_law_section_url("IL", "602.7", code_name="ILCS") == ""


_RUNNER_EVIDENCE_URL = "https://docs.legis.wisconsin.gov/document/statutes/1.01"


class _RunnerEvidenceScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://docs.legis.wisconsin.gov/statutes/statutes/1"

    def get_code_list(self):
        return []

    async def scrape_code(self, code_name, code_url):
        return []

    async def scrape_all(self, **kwargs):
        ledger = self._state_law_acquisition_ledger
        assert ledger is not None
        body = b"prospectively retained official Wisconsin statute"
        ledger.retain_parser_input(
            official_url=_RUNNER_EVIDENCE_URL,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": _RUNNER_EVIDENCE_URL,
                "source_transport": "direct",
            },
            retrieved_at="2026-08-24T07:00:00Z",
        )
        return [
            NormalizedStatute(
                state_code="WI",
                state_name="Wisconsin",
                statute_id="WI-1.01",
                section_number="1.01",
                full_text="A person shall comply with this section.",
                source_url=_RUNNER_EVIDENCE_URL,
            )
        ]

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection,
    ):
        from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )

        completion = closed_jurisdiction_receipt(
            "WI",
            discovered=1,
            fetched=1,
            excluded=0,
            quarantined=0,
            failed_final=0,
            duplicates=0,
            source_domain="docs.legis.wisconsin.gov",
            canonical_keys=["WI-1.01"],
            derived_keys=["WI-1.01"],
            row_count=1,
        )
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(completion["frontier"]),
            canonical_output_projection=canonical_output_projection,
            release_point=hashlib.sha256(b"wi-runner-release").hexdigest(),
            official_source_url=self.get_base_url(),
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T07:05:00Z",
            source_software_version="state-scraper/test-producer",
        )


class _RunnerMissingFrontierScraper(_RunnerEvidenceScraper):
    produce_state_law_frontier_closure = (
        BaseStateScraper.produce_state_law_frontier_closure
    )


class _RunnerFailingFrontierScraper(_RunnerEvidenceScraper):
    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection,
    ):
        del canonical_output_projection
        raise RuntimeError("independent replay failed")


class _RunnerFilteringFrontierScraper(_RunnerEvidenceScraper):
    def __init__(self, state_code, state_name):
        super().__init__(state_code, state_name)
        self.observed_output_projection = None

    async def scrape_all(self, **kwargs):
        del kwargs
        ledger = self._state_law_acquisition_ledger
        assert ledger is not None
        urls = [
            _RUNNER_EVIDENCE_URL,
            "https://docs.legis.wisconsin.gov/document/statutes/1.02",
        ]
        rows = []
        for index, url in enumerate(urls, start=1):
            body = f"prospectively retained statute {index}".encode("utf-8")
            ledger.retain_parser_input(
                official_url=url,
                body=body,
                transport_receipt={
                    "content_sha256": hashlib.sha256(body).hexdigest(),
                    "official_url": url,
                    "source_transport": "direct",
                },
                retrieved_at=f"2026-08-24T07:00:0{index}Z",
            )
            rows.append(
                NormalizedStatute(
                    state_code="WI",
                    state_name="Wisconsin",
                    statute_id=f"WI-1.0{index}",
                    section_number=f"1.0{index}",
                    full_text=(
                        "A person shall comply with this complete statute text."
                        if index == 1
                        else "x"
                    ),
                    source_url=url,
                )
            )
        return rows

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection,
    ):
        from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )

        self.observed_output_projection = dict(canonical_output_projection)
        keys = list(canonical_output_projection["canonical_keys"])
        completion = closed_jurisdiction_receipt(
            "WI",
            discovered=len(keys),
            fetched=len(keys),
            excluded=0,
            quarantined=0,
            failed_final=0,
            duplicates=0,
            source_domain="docs.legis.wisconsin.gov",
            canonical_keys=keys,
            derived_keys=keys,
            row_count=len(keys),
        )
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(completion["frontier"]),
            canonical_output_projection=canonical_output_projection,
            release_point=hashlib.sha256(b"wi-filtered-release").hexdigest(),
            official_source_url=self.get_base_url(),
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T07:06:00Z",
            source_software_version="state-scraper/test-filtered-producer",
        )


class _ParserTransportBypassScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.invalid/"

    def get_code_list(self):
        return []

    def _direct_get(self, code_url):
        import requests

        requests.get(code_url)

    async def scrape_code(self, code_name, code_url):
        await self._fetch_parser_input_with_transport(
            code_url,
            allow_archival_fallback=False,
        )
        self._direct_get(code_url)
        return []


class _SpoofedSharedAdapterScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.invalid/"

    def get_code_list(self):
        return []

    async def _fetch_parser_input_with_transport(self, url, **_kwargs):
        return str(url).encode("utf-8")

    async def scrape_code(self, code_name, code_url):
        await self._fetch_parser_input_with_transport(code_url)
        return []


def test_production_state_runner_attaches_multifetch_ledger_before_scrape_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    monkeypatch.setenv(
        scraper_module.MULTIFETCH_EVIDENCE_ROOT_ENV,
        str(tmp_path / "evidence"),
    )
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda state_code, state_name: _RunnerEvidenceScraper(state_code, state_name),
    )

    result = scraper_module._scrape_state_once_sync(
        state_code="WI",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=False,
        min_full_text_chars=1,
        hydrate_statute_text=False,
    )

    evidence = result["acquisition_evidence"]
    assert result["error"] is None
    assert evidence["attached_before_scrape_all"] is True
    assert evidence["retained_parser_input_count"] == 1
    assert evidence["parser_output_coverage"]["complete"] is True
    assert (
        evidence["source_frontier_lifecycle"]["status"]
        == "retained_and_verified"
    )
    assert evidence["aggregate"]["status"] == "pending_canonical_materialization"
    assert Path(evidence["jurisdiction_root"]).is_dir()


@pytest.mark.parametrize(
    ("strict", "expects_error"),
    ((False, False), (True, True)),
)
def test_missing_frontier_producer_is_diagnostic_or_strict_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    expects_error: bool,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    monkeypatch.setenv(
        scraper_module.MULTIFETCH_EVIDENCE_ROOT_ENV,
        str(tmp_path / "evidence"),
    )
    if strict:
        monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    else:
        monkeypatch.delenv(
            scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV,
            raising=False,
        )
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda state_code, state_name: _RunnerMissingFrontierScraper(
            state_code,
            state_name,
        ),
    )

    result = scraper_module._scrape_state_once_sync(
        state_code="WI",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=False,
        min_full_text_chars=1,
        hydrate_statute_text=False,
    )

    evidence = result["acquisition_evidence"]
    assert evidence["source_frontier_lifecycle"]["status"] == "missing"
    assert "source_frontier_producer_missing" in evidence["eligibility_blockers"]
    assert evidence["aggregate_eligible"] is False
    assert bool(result["error"]) is expects_error


def test_frontier_producer_failure_fails_closed_in_strict_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    monkeypatch.setenv(
        scraper_module.MULTIFETCH_EVIDENCE_ROOT_ENV,
        str(tmp_path / "evidence"),
    )
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda state_code, state_name: _RunnerFailingFrontierScraper(
            state_code,
            state_name,
        ),
    )

    result = scraper_module._scrape_state_once_sync(
        state_code="WI",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=False,
        min_full_text_chars=1,
        hydrate_statute_text=False,
    )

    lifecycle = result["acquisition_evidence"]["source_frontier_lifecycle"]
    assert lifecycle["status"] == "failed"
    assert "independent replay failed" in lifecycle["error"]
    assert "source_frontier_producer_failed" in result["error"]


def test_frontier_producer_sees_rows_after_strict_text_filtering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    instance = _RunnerFilteringFrontierScraper("WI", "Wisconsin")
    monkeypatch.setenv(
        scraper_module.MULTIFETCH_EVIDENCE_ROOT_ENV,
        str(tmp_path / "evidence"),
    )
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda _state_code, _state_name: instance,
    )

    result = scraper_module._scrape_state_once_sync(
        state_code="WI",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=True,
        min_full_text_chars=20,
        hydrate_statute_text=False,
    )

    assert result["error"] is None
    assert result["statutes_count"] == 1
    assert result["statute_data"]["strict_removed_count"] == 1
    assert instance.observed_output_projection is not None
    assert instance.observed_output_projection["canonical_row_count"] == 1
    assert instance.observed_output_projection["canonical_keys"] == ["WI-1.01"]


def test_strict_state_runner_cannot_run_without_evidence_root(monkeypatch):
    monkeypatch.delenv(scraper_module.MULTIFETCH_EVIDENCE_ROOT_ENV, raising=False)
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")

    with pytest.raises(RuntimeError, match="requires.*MULTIFETCH_EVIDENCE_ROOT"):
        scraper_module._scrape_state_once_sync(
            state_code="WI",
            legal_areas=None,
            rate_limit_delay=0.0,
            max_statutes=None,
            strict_full_text=False,
            min_full_text_chars=1,
            hydrate_statute_text=False,
        )


def test_parser_transport_bypass_inventory_is_machine_readable_and_blocking():
    inventory = scraper_module.inventory_state_scraper_transport_bypasses(
        _ParserTransportBypassScraper
    )

    assert inventory["schema_version"] == "state-laws-transport-bypass-inventory-v1"
    assert inventory["inventory_scope"] == "parser_reachable_static_call_graph"
    assert inventory["complete"] is False
    assert inventory["candidate_count"] == 1
    assert inventory["closure_projection_producer_present"] is False
    assert inventory["candidates"][0]["kind"] == "requests"
    assert inventory["candidates"][0]["parser_scope"] == "method:_direct_get"
    assert inventory["shared_custom_transport_adapter_call_count"] == 1


def test_parser_transport_inventory_rejects_state_local_adapter_shadowing():
    inventory = scraper_module.inventory_state_scraper_transport_bypasses(
        _SpoofedSharedAdapterScraper
    )

    assert inventory["complete"] is False
    assert inventory["candidate_count"] == 1
    assert inventory["shared_custom_transport_adapter_call_count"] == 0
    assert inventory["candidates"][0]["kind"] == "shared_base_fetch_overridden"


def test_representative_custom_transport_migrations_are_exactly_inventory_visible():
    inventory = scraper_module.inventory_registered_state_scraper_transport_bypasses(
        ["AL", "CT", "GA"]
    )

    assert inventory["candidate_count"] == 0
    assert inventory["gap_jurisdictions"] == []
    assert inventory["jurisdictions"]["AL"]["candidates"] == []
    assert (
        inventory["jurisdictions"]["AL"][
            "shared_custom_transport_adapter_call_count"
        ]
        == 1
    )
    assert inventory["jurisdictions"]["CT"]["candidates"] == []
    assert (
        inventory["jurisdictions"]["CT"][
            "shared_custom_transport_adapter_call_count"
        ]
        == 2
    )
    assert inventory["jurisdictions"]["GA"]["candidates"] == []
    assert (
        inventory["jurisdictions"]["GA"][
            "shared_custom_transport_adapter_call_count"
        ]
        == 2
    )


@pytest.mark.asyncio
async def test_alabama_graphql_post_uses_shared_exact_byte_adapter(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import (
        AlabamaScraper,
    )

    scraper = AlabamaScraper("AL", "Alabama")
    captured = {}

    async def _adapter(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return b'{"data":{"titles":[{"id":"title-1"}]}}'

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    observed = await scraper._graphql(
        "query Titles($active: Boolean!) { titles { id } }",
        {"active": True},
    )

    assert observed == {"titles": [{"id": "title-1"}]}
    assert captured["url"] == scraper.GRAPHQL_URL
    assert captured["method"] == "POST"
    assert captured["allow_archival_fallback"] is False
    assert captured["media_type"] == "application/json"
    assert captured["cache_url"].startswith(
        f"{scraper.GRAPHQL_URL}?state_law_graphql_sha256="
    )
    request_payload = json.loads(captured["request_body"].decode("utf-8"))
    assert request_payload == {
        "query": "query Titles($active: Boolean!) { titles { id } }",
        "variables": {"active": True},
    }


@pytest.mark.asyncio
async def test_connecticut_text_get_uses_shared_tls_compatible_adapter(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import (
        ConnecticutScraper,
    )

    scraper = ConnecticutScraper("CT", "Connecticut")
    captured = {}
    body = b"<html><body>Sec. 1-1. Official text.</body></html>"

    async def _adapter(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return body

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    observed = await scraper._fetch_connecticut_page(
        "https://www.cga.ct.gov/current/pub/chap_001.htm",
        timeout_seconds=9,
    )

    assert observed == body
    assert captured["verify_tls"] is False
    assert captured["allow_archival_fallback"] is True
    assert captured["media_type"] == "text/html"
    assert captured["timeout_seconds"] == 9


@pytest.mark.asyncio
async def test_georgia_binary_pdf_get_uses_shared_validated_adapter(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
        GeorgiaScraper,
    )

    scraper = GeorgiaScraper("GA", "Georgia")
    captured = {}
    body = b"%PDF-1.7\x00official-georgia-summary"

    async def _adapter(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return body

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _adapter)
    observed = await scraper._fetch_pdf_bytes_direct(
        "https://www.legis.ga.gov/api/document/docs/summary.pdf",
        timeout_seconds=11,
    )

    assert observed == body
    assert captured["allow_archival_fallback"] is True
    assert captured["media_type"] == "application/pdf"
    assert captured["timeout_seconds"] == 11
    validator = captured["content_validator"]
    assert validator(body) is True
    assert validator(b"<html>not a PDF</html>") is False


def test_registered_transport_and_closure_producer_inventory_is_exact_51():
    inventory = (
        scraper_module.inventory_registered_state_scraper_transport_bypasses()
    )

    assert inventory["jurisdiction_count"] == 51
    assert len(inventory["jurisdictions"]) == 51
    assert len(inventory["gap_jurisdictions"]) == 0
    assert inventory["candidate_count"] == 0
    assert inventory["publication_evidence_complete"] is True
    assert inventory["closure_projection_producer_count"] == 51
    assert inventory["closure_projection_missing_jurisdictions"] == []
    assert scraper_module.build_state_law_section_url("PA", "12", code_name="23 Pa.C.S.") == ""

    assert (
        scraper_module.build_state_law_section_url(
            "TX", "153.002", code_name="Penal Code", preferred_host="statutes.capitol.texas.gov"
        )
        == "https://statutes.capitol.texas.gov/Docs/PE/htm/PE.153.htm#153.002"
    )


def test_state_laws_scraper_builds_unknown_backlog_section_urls():
    expected_urls = {
        (
            "AL",
            "13A-6-2",
            "Ala. Code",
        ): "https://alison.legislature.state.al.us/code-of-alabama?section=13A-6-2",
        (
            "AR",
            "5-13-201",
            "Ark. Code",
        ): "https://law.justia.com/codes/arkansas/title-5/subtitle-2/chapter-13/subchapter-2/section-5-13-201/",
        ("CO", "18-3-204", "Colo. Rev. Stat."): "https://colorado.public.law/statutes/crs_18-3-204",
        (
            "CT",
            "53a-61",
            "Conn. Gen. Stat.",
        ): "https://www.cga.ct.gov/current/pub/chap_952.htm#sec_53a-61",
        (
            "DE",
            "11-601",
            "Del. Code",
        ): "https://delcode.delaware.gov/title11/c005/sc02/index.html#601",
        (
            "GA",
            "16-5-23",
            "Ga. Code",
        ): "https://law.justia.com/codes/georgia/title-16/chapter-5/article-2/section-16-5-23/",
        (
            "HI",
            "707-712",
            "Haw. Rev. Stat.",
        ): "https://www.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/HRS0707/HRS_0707-0712.htm",
        (
            "KY",
            "508.030",
            "Ky. Rev. Stat.",
        ): "https://law.justia.com/codes/kentucky/chapter-508/section-508-030/",
        ("LA", "14:35", "La. Rev. Stat."): "https://legis.la.gov/legis/Law.aspx?d=78452",
        (
            "MD",
            "3-203",
            "Md. Code",
        ): "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcr&section=3-203",
        (
            "MS",
            "97-3-7",
            "Miss. Code",
        ): "https://law.justia.com/codes/mississippi/2024/title-97/chapter-3/section-97-3-7/",
        ("NH", "631:2-a", "N.H. Rev. Stat."): "https://gc.nh.gov/rsa/html/LXII/631/631-2-a.htm",
        (
            "NJ",
            "2C:12-1",
            "N.J. Stat.",
        ): "https://law.justia.com/codes/new-jersey/title-2c/section-2c-12-1/",
        (
            "NM",
            "30-3-4",
            "N.M. Stat.",
        ): "https://law.justia.com/codes/new-mexico/chapter-30/article-3/section-30-3-4/",
        ("ND", "12.1-17-01", "N.D. Cent. Code"): "https://ndlegis.gov/cencode/t12-1c17.pdf",
        (
            "OK",
            "21-644",
            "Okla. Stat.",
        ): "https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os21.pdf",
        (
            "TN",
            "39-13-101",
            "Tenn. Code",
        ): "https://law.justia.com/codes/tennessee/title-39/chapter-13/part-1/section-39-13-101/",
        ("WY", "6-2-501", "Wyo. Stat."): "https://wyoleg.gov/statutes/compress/title06.pdf",
    }

    for (state, section, code_name), expected_url in expected_urls.items():
        assert (
            scraper_module.build_state_law_section_url(state, section, code_name=code_name)
            == expected_url
        )


def test_state_laws_scraper_trims_max_statutes_per_state() -> None:
    scraped, total = scraper_module._trim_scraped_statutes_to_max(
        [
            {"state_code": "MN", "statutes": [{"id": "mn-1"}, {"id": "mn-2"}, {"id": "mn-3"}]},
            {"state_code": "KY", "statutes": [{"id": "ky-1"}, {"id": "ky-2"}, {"id": "ky-3"}]},
        ],
        2,
    )

    assert [block["state_code"] for block in scraped] == ["MN", "KY"]
    assert [[row["id"] for row in block["statutes"]] for block in scraped] == [
        ["mn-1", "mn-2"],
        ["ky-1", "ky-2"],
    ]
    assert total == 4


def test_state_laws_scraper_compacts_streamed_state_result_for_retention() -> None:
    result = {
        "state_code": "KY",
        "statutes_count": 2,
        "statute_data": {
            "state_code": "KY",
            "statutes": [{"id": "ky-1"}, {"id": "ky-2"}],
        },
    }

    compact = scraper_module._compact_state_result_for_retention(result)

    assert compact["statute_data"]["statutes"] == []
    assert compact["statute_data"]["statutes_count"] == 2
    assert compact["statute_data"]["streamed_to_state_completion_callback"] is True
    assert (
        scraper_module._compute_coverage_summary(
            selected_states=["KY"],
            scraped_statutes=[compact["statute_data"]],
            errors=[],
        )["full_coverage"]
        is True
    )


@pytest.mark.asyncio
async def test_state_laws_scraper_timeout_uses_daemon_thread(monkeypatch):
    captured = {}

    class _FakeThread:
        def __init__(self, *, target, name=None, daemon=None):
            captured["name"] = name
            captured["daemon"] = daemon
            self._target = target

        def start(self):
            self._target()

    def _fake_scrape_state_once_sync(**kwargs):
        captured["code_timeout"] = os.environ.get("STATE_SCRAPER_CODE_TIMEOUT_SECONDS")
        captured["fetch_timeout"] = os.environ.get("STATE_SCRAPER_FETCH_TIMEOUT_SECONDS")
        captured["per_state_timeout_seconds"] = kwargs.get("per_state_timeout_seconds")
        return {"state_code": kwargs["state_code"], "status": "ok"}

    monkeypatch.setattr(scraper_module.threading, "Thread", _FakeThread)
    monkeypatch.setattr(scraper_module, "_scrape_state_once_sync", _fake_scrape_state_once_sync)

    result = await scraper_module._run_sync_scrape_on_daemon_thread(
        state_code="OR",
        legal_areas=["administrative"],
        rate_limit_delay=0.0,
        max_statutes=1,
        strict_full_text=True,
        min_full_text_chars=0,
        hydrate_statute_text=True,
        timeout_seconds=0.5,
    )

    assert result["state_code"] == "OR"
    assert result["status"] == "ok"
    assert result["worker_quiescence"]["attested"] is True
    assert result["worker_quiescence"]["quiescent"] is True
    assert captured["daemon"] is True
    assert captured["name"] == "state-scrape-or"
    assert captured["code_timeout"] == "0.400"
    assert captured["fetch_timeout"] == "0.133"
    assert captured["per_state_timeout_seconds"] == 0.5


@pytest.mark.asyncio
async def test_state_laws_scraper_timeout_returns_without_waiting_for_blocked_worker(
    tmp_path,
    monkeypatch,
):
    bounded_keys = {
        "STATE_SCRAPER_CODE_TIMEOUT_SECONDS": "prior-code",
        "STATE_SCRAPER_FETCH_TIMEOUT_SECONDS": "prior-fetch",
        "STATE_SCRAPER_MAX_STATUTES": "prior-max",
        "STATE_SCRAPER_BOUNDED_DIRECT_ONLY": "prior-direct",
    }
    for key, value in bounded_keys.items():
        monkeypatch.setenv(key, value)
    evidence_root = tmp_path / "immutable-evidence-root"
    monkeypatch.setenv(scraper_module.MULTIFETCH_EVIDENCE_ROOT_ENV, str(evidence_root))
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    monkeypatch.setenv(scraper_module.RETAINED_REPLAY_ONLY_ENV, "1")
    captured_bindings = {}

    def _fake_scrape_state_once_sync(**kwargs):
        captured_bindings.update(
            {
                "evidence_root": kwargs["bound_evidence_root"],
                "strict": kwargs["bound_strict_evidence"],
                "retained_replay_only": kwargs["bound_retained_replay_only"],
            }
        )
        time.sleep(0.2)
        return {"state_code": kwargs["state_code"], "status": "ok"}

    monkeypatch.setattr(scraper_module, "_scrape_state_once_sync", _fake_scrape_state_once_sync)

    started_at = time.perf_counter()
    result = await scraper_module._scrape_state_with_retries(
        state_code="OR",
        legal_areas=["administrative"],
        rate_limit_delay=0.0,
        max_statutes=1,
        strict_full_text=True,
        min_full_text_chars=0,
        hydrate_statute_text=True,
        retry_attempts=0,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=0.05,
    )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.15
    assert result["state_code"] == "OR"
    assert result["zero_statute"] is True
    assert "timed out" in str(result["error"])
    assert (
        result.get("timeout_diagnostics", {}).get("classification")
        == "timeout_nonquiescent_worker"
    )
    assert result["worker_quiescence"]["attested"] is True
    assert result["worker_quiescence"]["quiescent"] is False
    assert result["timeout_diagnostics"]["retry_authorized"] is False
    assert captured_bindings == {
        "evidence_root": str(evidence_root.resolve()),
        "strict": True,
        "retained_replay_only": True,
    }

    # Timeout revokes the worker's process-global environment lease before
    # returning, even though its daemon thread remains alive.
    assert {key: os.environ.get(key) for key in bounded_keys} == bounded_keys
    later_values = {key: f"later-{index}" for index, key in enumerate(bounded_keys)}
    for key, value in later_values.items():
        monkeypatch.setenv(key, value)

    await asyncio.sleep(0.25)

    # The late worker's finally block must not clobber a subsequent owner's
    # settings after its lease has been revoked.
    assert {key: os.environ.get(key) for key in bounded_keys} == later_values


@pytest.mark.asyncio
async def test_nonquiescent_worker_keeps_launch_time_state_evidence_paths(
    tmp_path,
    monkeypatch,
):
    launch_paths = {
        "ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT": tmp_path / "run-one-ar-proof",
        "ARKANSAS_LEXIS_INVENTORY_PATH": tmp_path / "run-one-ar-inventory.json",
        "INDIANA_CODE_ZIP_CACHE_DIR": tmp_path / "run-one-in-code-cache",
        "STATE_SCRAPER_MS_LEXIS_EVIDENCE_DIR": tmp_path / "run-one-ms-proof",
    }
    later_paths = {
        name: tmp_path / f"run-two-{index}"
        for index, name in enumerate(launch_paths)
    }
    for name, path in launch_paths.items():
        monkeypatch.setenv(name, str(path))

    worker_entered = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    captured = {}

    def _fake_scrape_state_once_sync(**kwargs):
        worker_entered.set()
        release_worker.wait(timeout=2)
        captured.update(dict(kwargs["bound_state_run_environment"]))
        worker_finished.set()
        return {"state_code": kwargs["state_code"], "status": "late"}

    monkeypatch.setattr(
        scraper_module,
        "_scrape_state_once_sync",
        _fake_scrape_state_once_sync,
    )

    result = await scraper_module._scrape_state_with_retries(
        state_code="AR",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=1,
        strict_full_text=True,
        min_full_text_chars=0,
        hydrate_statute_text=True,
        retry_attempts=0,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=0.05,
    )
    assert worker_entered.is_set()
    assert result["worker_quiescence"]["quiescent"] is False

    for name, path in later_paths.items():
        monkeypatch.setenv(name, str(path))
    release_worker.set()
    assert worker_finished.wait(timeout=2)

    for name, path in launch_paths.items():
        assert captured[name] == str(path.resolve())
    assert captured["STATE_SCRAPER_FULL_CORPUS"] == "0"


def test_state_specific_evidence_selectors_use_immutable_run_binding(
    tmp_path,
    monkeypatch,
):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
        ArkansasScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
        MississippiScraper,
    )

    launch = {
        "ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT": str(tmp_path / "ar-proof-one"),
        "ARKANSAS_LEXIS_INVENTORY_PATH": str(tmp_path / "ar-inventory-one"),
        "INDIANA_CODE_ZIP_CACHE_DIR": str(tmp_path / "in-code-cache-one"),
        "STATE_SCRAPER_MS_LEXIS_EVIDENCE_DIR": str(tmp_path / "ms-proof-one"),
    }
    arkansas = ArkansasScraper("AR", "Arkansas")
    mississippi = MississippiScraper("MS", "Mississippi")
    arkansas.bind_state_law_run_environment(launch)
    mississippi.bind_state_law_run_environment(launch)

    for name in launch:
        monkeypatch.setenv(name, str(tmp_path / f"later-{name.lower()}"))

    assert arkansas.state_law_run_environment_value(
        "ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT"
    ) == launch["ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT"]
    assert arkansas.state_law_run_environment_value(
        "ARKANSAS_LEXIS_INVENTORY_PATH"
    ) == launch["ARKANSAS_LEXIS_INVENTORY_PATH"]
    assert mississippi.state_law_run_environment_value(
        "STATE_SCRAPER_MS_LEXIS_EVIDENCE_DIR"
    ) == launch["STATE_SCRAPER_MS_LEXIS_EVIDENCE_DIR"]

    source_root = Path(scraper_module.__file__).resolve().parent / "state_scrapers"
    direct_reads = {
        "arkansas.py": (
            "ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT",
            "ARKANSAS_LEXIS_INVENTORY_PATH",
        ),
        "mississippi.py": ("STATE_SCRAPER_MS_LEXIS_EVIDENCE_DIR",),
        "indiana.py": ("INDIANA_CODE_ZIP_CACHE_DIR",),
    }
    for filename, names in direct_reads.items():
        source = (source_root / filename).read_text(encoding="utf-8")
        for name in names:
            assert f'os.getenv("{name}"' not in source
            assert f'os.environ.get("{name}"' not in source


@pytest.mark.asyncio
async def test_indiana_writable_cache_stays_bound_to_worker_launch(
    tmp_path,
    monkeypatch,
):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import (
        IndianaScraper,
    )

    launch_cache = tmp_path / "run-one-cache"
    later_cache = tmp_path / "run-two-cache"
    scraper = IndianaScraper("IN", "Indiana")
    scraper.bind_state_law_run_environment(
        {"INDIANA_CODE_ZIP_CACHE_DIR": str(launch_cache)}
    )

    async def _no_parser_input(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        scraper,
        "_fetch_parser_input_with_transport",
        _no_parser_input,
    )
    monkeypatch.setenv("INDIANA_CODE_ZIP_CACHE_DIR", str(later_cache))
    monkeypatch.setenv("INDIANA_CODE_YEAR", "2025")

    assert await scraper._download_indiana_code_bundle() is None
    assert launch_cache.is_dir()
    assert not later_cache.exists()


def test_full_corpus_behavior_stays_bound_after_ambient_restore(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
        MinnesotaScraper,
    )

    scraper = MinnesotaScraper("MN", "Minnesota")
    scraper.bind_state_law_run_environment({"STATE_SCRAPER_FULL_CORPUS": "1"})
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "0")

    assert scraper._full_corpus_enabled() is True
    assert scraper._bounded_return_threshold(100) == 1_000_000


def test_supported_module_selectors_and_secret_use_worker_binding(
    tmp_path,
    monkeypatch,
):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        arkansas_lexis,
        california_bulk,
        district_of_columbia_xml,
        georgia_archived_official,
        georgia_lexis,
        illinois_bulk,
        indiana_bulk,
        michigan_chapter_xml,
        mississippi_lexis,
        new_jersey_bulk,
        new_york_openleg,
        utah_title_xml,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        bind_state_law_worker_environment,
        restore_state_law_worker_environment,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
        NorthCarolinaScraper,
    )

    file_selectors = {
        "GEORGIA_ARCHIVED_OFFICIAL_MANIFEST": tmp_path / "ga-manifest.json",
        "CALIFORNIA_BULK_ZIP": tmp_path / "ca.zip",
        "CALIFORNIA_BULK_ZIP_RECEIPT": tmp_path / "ca.receipt.json",
        "ILLINOIS_BULK_ZIP": tmp_path / "il.zip",
        "ILLINOIS_MANIFEST_TEXT": tmp_path / "il-manifest.txt",
        "INDIANA_BULK_ZIP": tmp_path / "in.zip",
        "INDIANA_BULK_ZIP_RECEIPT": tmp_path / "in.receipt.json",
        "NEW_JERSEY_BULK_ZIP": tmp_path / "nj.zip",
        "DC_CODE_SECTION_XML": tmp_path / "dc.xml",
        "MICHIGAN_CHAPTER_XML": tmp_path / "mi.xml",
        "MICHIGAN_CHAPTER_INDEX_HTML": tmp_path / "mi.html",
        "NY_OPENLEG_LAW_JSON": tmp_path / "ny.json",
        "NY_CATEGORY_HTML": tmp_path / "ny.html",
        "UTAH_TITLE_XML": tmp_path / "ut.xml",
        "UTAH_TOC_HTML": tmp_path / "ut.html",
    }
    for path in file_selectors.values():
        path.write_bytes(b"bound")
    dc_dir = tmp_path / "dc-xml"
    dc_dir.mkdir()
    secret = "  opaque-secret-material-with-at-least-thirty-two-bytes  "
    binding = {
        name: str(path.resolve()) for name, path in file_selectors.items()
    } | {
        "DC_CODE_XML_DIR": str(dc_dir.resolve()),
        "ARKANSAS_LEXIS_PUBLIC_ACCESS_ENABLE": "1",
        "MISSISSIPPI_LEXIS_PUBLIC_ACCESS_ENABLE": "1",
        "GEORGIA_LEXIS_PUBLIC_ACCESS_ENABLE": "1",
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY": secret,
    }
    prior = bind_state_law_worker_environment(binding)
    try:
        for name in binding:
            monkeypatch.setenv(name, str(tmp_path / f"later-{name.lower()}"))

        assert georgia_archived_official.configured_georgia_archived_official_manifest_path() == file_selectors[
            "GEORGIA_ARCHIVED_OFFICIAL_MANIFEST"
        ].resolve()
        assert california_bulk.configured_bulk_zip_path() == file_selectors[
            "CALIFORNIA_BULK_ZIP"
        ].resolve()
        assert california_bulk.configured_bulk_zip_receipt_path(
            file_selectors["CALIFORNIA_BULK_ZIP"]
        ) == file_selectors["CALIFORNIA_BULK_ZIP_RECEIPT"].resolve()
        assert illinois_bulk.configured_bulk_zip_path() == file_selectors[
            "ILLINOIS_BULK_ZIP"
        ].resolve()
        assert illinois_bulk.configured_manifest_path() == file_selectors[
            "ILLINOIS_MANIFEST_TEXT"
        ].resolve()
        assert indiana_bulk.configured_bulk_zip_path() == file_selectors[
            "INDIANA_BULK_ZIP"
        ].resolve()
        assert indiana_bulk.configured_bulk_zip_receipt_path(
            file_selectors["INDIANA_BULK_ZIP"]
        ) == file_selectors["INDIANA_BULK_ZIP_RECEIPT"].resolve()
        assert new_jersey_bulk.configured_bulk_zip_path() == file_selectors[
            "NEW_JERSEY_BULK_ZIP"
        ].resolve()
        assert district_of_columbia_xml.configured_section_xml_path() == file_selectors[
            "DC_CODE_SECTION_XML"
        ].resolve()
        assert district_of_columbia_xml.configured_xml_dir() == dc_dir.resolve()
        assert michigan_chapter_xml.configured_chapter_xml_path() == file_selectors[
            "MICHIGAN_CHAPTER_XML"
        ].resolve()
        assert michigan_chapter_xml.configured_chapter_index_html_path() == file_selectors[
            "MICHIGAN_CHAPTER_INDEX_HTML"
        ].resolve()
        assert new_york_openleg.configured_law_json_path() == file_selectors[
            "NY_OPENLEG_LAW_JSON"
        ].resolve()
        assert new_york_openleg.configured_category_html_path() == file_selectors[
            "NY_CATEGORY_HTML"
        ].resolve()
        assert utah_title_xml.configured_title_xml_path() == file_selectors[
            "UTAH_TITLE_XML"
        ].resolve()
        assert utah_title_xml.configured_toc_html_path() == file_selectors[
            "UTAH_TOC_HTML"
        ].resolve()
        assert arkansas_lexis.enabled() is True
        assert mississippi_lexis.enabled() is True
        assert georgia_lexis._env_enabled(georgia_lexis.ENABLE_ENV) is True

        north_carolina = NorthCarolinaScraper("NC", "North Carolina")
        north_carolina.bind_state_law_run_environment(binding)
        assert north_carolina._bychapter_checkpoint_hmac_key() == secret.encode(
            "utf-8"
        )
    finally:
        restore_state_law_worker_environment(prior)


def test_strict_worker_disables_default_shared_caches_before_constructor(
    tmp_path,
    monkeypatch,
):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        bind_state_law_worker_environment,
        restore_state_law_worker_environment,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
        MinnesotaScraper,
    )

    configured_fetch = tmp_path / "configured-fetch-cache"
    configured_ipfs = tmp_path / "configured-ipfs-cache"
    synthetic_home = tmp_path / "synthetic-home"
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    monkeypatch.setenv("LEGAL_SCRAPER_FETCH_CACHE_ENABLED", "1")
    monkeypatch.setenv("LEGAL_SCRAPER_FETCH_CACHE_DIR", str(configured_fetch))
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED", "1")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN", "1")
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(configured_ipfs))
    monkeypatch.setattr(
        Path,
        "home",
        classmethod(lambda cls: synthetic_home),
    )

    binding = scraper_module._capture_state_law_run_environment()
    assert binding["LEGAL_SCRAPER_FETCH_CACHE_ENABLED"] == "0"
    assert binding["LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED"] == "0"
    assert binding["LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN"] == "0"
    assert binding["LEGAL_SCRAPER_FETCH_CACHE_DIR"] == ""
    assert binding["LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR"] == ""

    prior = bind_state_law_worker_environment(binding)
    try:
        scraper = MinnesotaScraper("MN", "Minnesota")
    finally:
        restore_state_law_worker_environment(prior)

    assert scraper._fetch_cache_enabled is False
    assert scraper._ipfs_page_cache_enabled is False
    assert scraper._ipfs_page_cache_pin is False
    assert not configured_fetch.exists()
    assert not configured_ipfs.exists()
    assert not (synthetic_home / ".ipfs_datasets").exists()


@pytest.mark.asyncio
async def test_scrape_run_captures_supported_selectors_once_for_all_states(
    tmp_path,
    monkeypatch,
):
    launch_cache = tmp_path / "run-one-indiana-cache"
    later_cache = tmp_path / "run-two-indiana-cache"
    monkeypatch.setenv("INDIANA_CODE_ZIP_CACHE_DIR", str(launch_cache))
    observed = []

    async def _fake_state_attempt(**kwargs):
        observed.append(
            kwargs["bound_state_run_environment"][
                "INDIANA_CODE_ZIP_CACHE_DIR"
            ]
        )
        monkeypatch.setenv("INDIANA_CODE_ZIP_CACHE_DIR", str(later_cache))
        state_code = kwargs["state_code"]
        return {
            "state_code": state_code,
            "state_name": scraper_module.US_STATES[state_code],
            "statutes_count": 0,
            "zero_statute": True,
            "low_quality": False,
            "quality_metrics": {"total": 0},
            "statute_data": {
                "state_code": state_code,
                "state_name": scraper_module.US_STATES[state_code],
                "statutes": [],
            },
        }

    monkeypatch.setattr(
        scraper_module,
        "_scrape_state_with_retries",
        _fake_state_attempt,
    )

    await scraper_module.scrape_state_laws(
        states=["AR", "IN"],
        rate_limit_delay=0.0,
        max_statutes=None,
        parallel_workers=1,
        per_state_retry_attempts=0,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=1.0,
        write_jsonld=False,
    )

    assert observed == [str(launch_cache.resolve()), str(launch_cache.resolve())]


@pytest.mark.asyncio
async def test_checkpoint_recovery_and_strict_policy_stay_bound_to_run_start(
    tmp_path,
    monkeypatch,
):
    original_root = tmp_path / "original-checkpoints"
    later_root = tmp_path / "later-checkpoints"
    original_root.mkdir()
    later_root.mkdir()

    def _checkpoint(section_number):
        return {
            "state_code": "AR",
            "progress": {"codes_completed": 1, "codes_total": 1},
            "updated_at": "2026-08-26T00:00:00+00:00",
            "statutes": [
                {
                    "statute_id": f"AR-{section_number}",
                    "section_number": section_number,
                    "section_name": "Bound checkpoint",
                    "full_text": "This row identifies the selected checkpoint root.",
                }
            ],
        }

    (original_root / "STATE-AR-partial.json").write_text(
        json.dumps(_checkpoint("ORIGINAL")),
        encoding="utf-8",
    )
    (later_root / "STATE-AR-partial.json").write_text(
        json.dumps(_checkpoint("LATER")),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(original_root))
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")

    worker_entered = threading.Event()
    environment_switched = threading.Event()
    observed_monitor_roots = []
    real_read_activity = scraper_module._read_partial_checkpoint_activity

    def _record_activity(state_code, **kwargs):
        observed_monitor_roots.append(kwargs.get("checkpoint_dir"))
        return real_read_activity(state_code, **kwargs)

    def _fake_scrape_state_once_sync(**_kwargs):
        worker_entered.set()
        assert environment_switched.wait(timeout=2)
        raise TimeoutError("synthetic worker timeout")

    def _switch_environment():
        assert worker_entered.wait(timeout=2)
        os.environ["STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR"] = str(later_root)
        os.environ[scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV] = "0"
        environment_switched.set()

    monkeypatch.setattr(
        scraper_module,
        "_read_partial_checkpoint_activity",
        _record_activity,
    )
    monkeypatch.setattr(
        scraper_module,
        "_scrape_state_once_sync",
        _fake_scrape_state_once_sync,
    )
    switcher = threading.Thread(target=_switch_environment, daemon=True)
    switcher.start()

    result = await scraper_module._scrape_state_with_retries(
        state_code="AR",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=1,
        strict_full_text=True,
        min_full_text_chars=0,
        hydrate_statute_text=True,
        retry_attempts=0,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=1.0,
    )
    switcher.join(timeout=2)

    assert result["error"]
    assert result["statute_data"]["partial_checkpoint_path"] == str(
        original_root.resolve() / "STATE-AR-partial.json"
    )
    assert result["statute_data"]["statutes"][0]["section_number"] == "ORIGINAL"
    assert observed_monitor_roots
    assert set(observed_monitor_roots) == {str(original_root.resolve())}


@pytest.mark.asyncio
async def test_timed_out_worker_suppresses_overlapping_retry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    later_checkpoint_dir = tmp_path / "later-checkpoints"
    checkpoint_path = checkpoint_dir / "STATE-WI-partial.json"
    first_started = threading.Event()
    release_worker = threading.Event()
    older_finished = threading.Event()
    call_lock = threading.Lock()
    call_count = 0
    older_write_results: list[bool] = []

    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_POLL_SECONDS", "0.01")
    monkeypatch.setenv("STATE_SCRAPER_HARD_TIMEOUT_SECONDS", "0.04")
    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)

    def _fake_scrape_state_once_sync(**kwargs):
        nonlocal call_count
        with call_lock:
            call_count += 1
            attempt = call_count
        worker_scraper = _RunnerEvidenceScraper("WI", "Wisconsin")
        worker_scraper.bind_partial_checkpoint_generation(
            key=kwargs["checkpoint_generation_key"],
            generation=kwargs["checkpoint_generation"],
        )
        statute = NormalizedStatute(
            state_code="WI",
            state_name="Wisconsin",
            statute_id=f"WI-{attempt}",
            section_number=str(attempt),
            full_text=f"attempt {attempt}",
            source_url=f"https://codes.example.gov/{attempt}",
        )
        first_started.set()
        assert release_worker.wait(timeout=2.0)
        older_write_results.append(
            worker_scraper._write_partial_checkpoint(
                [statute],
                code_name="Wisconsin Statutes",
                stage_label="late-nonquiescent-attempt",
                force=True,
                replace_existing_rows=True,
            )
        )
        older_finished.set()
        return {
            "state_code": "WI",
            "error": None,
            "statutes_count": 1,
            "zero_statute": False,
            "low_quality": False,
            "quality_metrics": {"total": 1},
        }

    monkeypatch.setattr(
        scraper_module,
        "_scrape_state_once_sync",
        _fake_scrape_state_once_sync,
    )

    result = await scraper_module._scrape_state_with_retries(
        state_code="WI",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=False,
        min_full_text_chars=1,
        hydrate_statute_text=False,
        retry_attempts=1,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=0.02,
    )

    assert first_started.is_set()
    assert call_count == 1
    assert "nonquiescent" in str(result["error"])
    assert result["worker_quiescence"]["quiescent"] is False
    monkeypatch.setenv(
        "STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR",
        str(later_checkpoint_dir),
    )
    release_worker.set()
    assert older_finished.wait(timeout=1.0)
    assert older_write_results == [True]
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["stage_label"] == "late-nonquiescent-attempt"
    assert [row["statute_id"] for row in payload["statutes"]] == ["WI-1"]
    assert not (later_checkpoint_dir / "STATE-WI-partial.json").exists()


def test_state_scrapers_have_no_direct_checkpoint_environment_reads() -> None:
    state_scraper_dir = (
        Path(scraper_module.__file__).resolve().parent / "state_scrapers"
    )
    offenders = []
    direct_read = 'os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR")'
    for source_path in sorted(state_scraper_dir.glob("*.py")):
        if source_path.name == "base_scraper.py":
            continue
        if direct_read in source_path.read_text(encoding="utf-8"):
            offenders.append(source_path.name)

    assert offenders == []


def test_state_laws_scraper_checkpoint_activity_uses_quick_meta_for_large_files(
    tmp_path, monkeypatch
):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-WA-partial.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "state_code": "WA",
                "updated_at": "2026-05-28T00:00:00+00:00",
                "stage_label": "scrape_all:complete",
                "statutes_count": 123,
                "padding": "x" * 10000,
                "statutes": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_CHECKPOINT_PARSE_MAX_BYTES", "1024")
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_CHECKPOINT_META_READ_BYTES", "4096")

    activity = scraper_module._read_partial_checkpoint_activity("WA")

    assert activity["stage_complete"] is True
    assert activity["statutes_count"] == 123
    assert activity["signature"]
    assert activity["updated_ts"] > 0


@pytest.mark.asyncio
async def test_state_laws_scraper_live_worker_cannot_promote_complete_checkpoint(monkeypatch, tmp_path):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-NH-partial.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "state_code": "NH",
                "updated_at": "2026-05-28T00:00:00+00:00",
                "stage_label": "complete",
                "statutes_count": 1,
                "progress": {"codes_completed": 1, "codes_total": 1},
                "statutes": [
                    {
                        "state_code": "NH",
                        "state_name": "New Hampshire",
                        "statute_id": "NH RSA 1",
                        "code_name": "New Hampshire Revised Statutes",
                        "section_number": "1",
                        "section_name": "Section 1",
                        "full_text": "Section 1 text",
                        "source_url": "https://example.invalid/nh/rsa/1",
                        "scraped_at": "2026-05-28T00:00:00+00:00",
                        "scraper_version": "1.0",
                        "structured_data": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_POLL_SECONDS", "0.01")
    monkeypatch.setenv("STATE_SCRAPER_PROGRESS_GRACE_SECONDS", "0")
    monkeypatch.setenv("STATE_SCRAPER_CHECKPOINT_COMPLETE_SETTLE_SECONDS", "1")

    def _fake_scrape_state_once_sync(**kwargs):
        time.sleep(0.4)
        return {"state_code": kwargs["state_code"], "status": "ok"}

    monkeypatch.setattr(scraper_module, "_scrape_state_once_sync", _fake_scrape_state_once_sync)

    started_at = time.perf_counter()
    with pytest.raises(scraper_module.StateScraperNonQuiescentTimeout):
        await scraper_module._run_sync_scrape_on_daemon_thread(
            state_code="NH",
            legal_areas=None,
            rate_limit_delay=0.0,
            max_statutes=1,
            strict_full_text=False,
            min_full_text_chars=0,
            hydrate_statute_text=False,
            timeout_seconds=0.05,
        )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_state_laws_scraper_live_worker_cannot_promote_signal_complete_checkpoint(
    monkeypatch, tmp_path
):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-MS-partial.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "state_code": "MS",
                "updated_at": "2026-05-28T00:00:00+00:00",
                "stage_label": "mississippi:scrape_code:start",
                "statutes_count": 2,
                "progress": {
                    "codes_completed": 0,
                    "codes_total": 1,
                    "discovered_history_urls": 2,
                    "scanned_history_urls": 2,
                },
                "statutes": [
                    {
                        "state_code": "MS",
                        "state_name": "Mississippi",
                        "statute_id": "MS 1",
                        "code_name": "Mississippi Code",
                        "section_number": "1",
                        "section_name": "Section 1",
                        "full_text": "Section 1 text",
                        "source_url": "https://example.invalid/ms/1",
                        "scraped_at": "2026-05-28T00:00:00+00:00",
                        "scraper_version": "1.0",
                        "structured_data": {},
                    },
                    {
                        "state_code": "MS",
                        "state_name": "Mississippi",
                        "statute_id": "MS 2",
                        "code_name": "Mississippi Code",
                        "section_number": "2",
                        "section_name": "Section 2",
                        "full_text": "Section 2 text",
                        "source_url": "https://example.invalid/ms/2",
                        "scraped_at": "2026-05-28T00:00:00+00:00",
                        "scraper_version": "1.0",
                        "structured_data": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_POLL_SECONDS", "0.01")
    monkeypatch.setenv("STATE_SCRAPER_PROGRESS_GRACE_SECONDS", "0")
    monkeypatch.setenv("STATE_SCRAPER_CHECKPOINT_COMPLETE_SETTLE_SECONDS", "1")

    def _fake_scrape_state_once_sync(**kwargs):
        time.sleep(0.4)
        return {"state_code": kwargs["state_code"], "status": "ok"}

    monkeypatch.setattr(scraper_module, "_scrape_state_once_sync", _fake_scrape_state_once_sync)

    started_at = time.perf_counter()
    with pytest.raises(scraper_module.StateScraperNonQuiescentTimeout):
        await scraper_module._run_sync_scrape_on_daemon_thread(
            state_code="MS",
            legal_areas=None,
            rate_limit_delay=0.0,
            max_statutes=1,
            strict_full_text=False,
            min_full_text_chars=0,
            hydrate_statute_text=False,
            timeout_seconds=0.05,
        )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_state_laws_scraper_live_worker_churn_cannot_promote_checkpoint(
    monkeypatch,
    tmp_path,
):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-MS-partial.json"
    checkpoint_payload = {
        "state_code": "MS",
        "updated_at": "2026-05-28T00:00:00+00:00",
        "stage_label": "mississippi:scrape_code:start",
        "statutes_count": 1,
        "progress": {
            "codes_completed": 0,
            "codes_total": 1,
            "discovered_history_urls": 1,
            "scanned_history_urls": 1,
        },
        "statutes": [
            {
                "state_code": "MS",
                "state_name": "Mississippi",
                "statute_id": "MS 1",
                "code_name": "Mississippi Code",
                "section_number": "1",
                "section_name": "Section 1",
                "full_text": "Section 1 text",
                "source_url": "https://example.invalid/ms/1",
                "scraped_at": "2026-05-28T00:00:00+00:00",
                "scraper_version": "1.0",
                "structured_data": {},
            }
        ],
    }
    checkpoint_path.write_text(json.dumps(checkpoint_payload), encoding="utf-8")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_POLL_SECONDS", "0.01")
    monkeypatch.setenv("STATE_SCRAPER_PROGRESS_GRACE_SECONDS", "0")
    monkeypatch.setenv("STATE_SCRAPER_CHECKPOINT_COMPLETE_SETTLE_SECONDS", "0.05")

    def _fake_scrape_state_once_sync(**kwargs):
        # Rewrite checkpoint heartbeat timestamps without changing counters.
        for _ in range(30):
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")
            time.sleep(0.02)
        return {"state_code": kwargs["state_code"], "status": "ok"}

    monkeypatch.setattr(scraper_module, "_scrape_state_once_sync", _fake_scrape_state_once_sync)

    started_at = time.perf_counter()
    with pytest.raises(scraper_module.StateScraperNonQuiescentTimeout):
        await scraper_module._run_sync_scrape_on_daemon_thread(
            state_code="MS",
            legal_areas=None,
            rate_limit_delay=0.0,
            max_statutes=1,
            strict_full_text=False,
            min_full_text_chars=0,
            hydrate_statute_text=False,
            timeout_seconds=0.15,
        )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.35


@pytest.mark.asyncio
async def test_state_laws_scraper_timeout_checkpoint_never_authorizes_live_worker(
    monkeypatch, tmp_path
):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-MS-partial.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "state_code": "MS",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "stage_label": "mississippi:scrape_code:start",
                "statutes_count": 1,
                "progress": {
                    "codes_completed": 0,
                    "codes_total": 1,
                    "discovered_history_urls": 1,
                    "scanned_history_urls": 1,
                },
                "statutes": [
                    {
                        "state_code": "MS",
                        "state_name": "Mississippi",
                        "statute_id": "MS 1",
                        "code_name": "Mississippi Code",
                        "section_number": "1",
                        "section_name": "Section 1",
                        "full_text": "Section 1 text",
                        "source_url": "https://example.invalid/ms/1",
                        "scraped_at": "2026-05-28T00:00:00+00:00",
                        "scraper_version": "1.0",
                        "structured_data": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_POLL_SECONDS", "0.01")
    monkeypatch.setenv("STATE_SCRAPER_PROGRESS_GRACE_SECONDS", "0")
    # Prevent in-loop promotion so we exercise the timeout recovery branch.
    monkeypatch.setenv("STATE_SCRAPER_CHECKPOINT_COMPLETE_SETTLE_SECONDS", "999")

    def _fake_scrape_state_once_sync(**kwargs):
        time.sleep(0.3)
        return {"state_code": kwargs["state_code"], "status": "ok"}

    monkeypatch.setattr(scraper_module, "_scrape_state_once_sync", _fake_scrape_state_once_sync)

    result = await scraper_module._scrape_state_with_retries(
        state_code="MS",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=1,
        strict_full_text=False,
        min_full_text_chars=0,
        hydrate_statute_text=False,
        retry_attempts=0,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=0.05,
    )

    assert result["state_code"] == "MS"
    assert "nonquiescent" in str(result["error"])
    assert result["statutes_count"] == 1
    diag = result.get("timeout_diagnostics") or {}
    assert diag.get("classification") == "timeout_nonquiescent_worker"
    assert diag.get("retry_authorized") is False
    assert result["worker_quiescence"]["quiescent"] is False


@pytest.mark.asyncio
async def test_strict_acquisition_keeps_checkpoint_complete_closure_error(
    monkeypatch, tmp_path
):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "STATE-TX-partial.json").write_text(
        json.dumps(
            {
                "state_code": "TX",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "stage_label": "scrape_all:complete",
                "statutes_count": 1,
                "progress": {"codes_completed": 30, "codes_total": 30},
                "statutes": [
                    {
                        "state_code": "TX",
                        "state_name": "Texas",
                        "statute_id": "Texas Code § 1",
                        "code_name": "Texas Code",
                        "section_number": "1",
                        "section_name": "Section 1",
                        "full_text": "Section 1 text",
                        "source_url": "https://example.invalid/tx/1",
                        "structured_data": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")

    def _fake_scrape_state_once_sync(**_kwargs):
        raise RuntimeError("TX exact closure failed")

    monkeypatch.setattr(
        scraper_module,
        "_scrape_state_once_sync",
        _fake_scrape_state_once_sync,
    )

    result = await scraper_module._scrape_state_with_retries(
        state_code="TX",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=True,
        min_full_text_chars=1,
        hydrate_statute_text=False,
        retry_attempts=0,
        retry_zero_statute_states=False,
        per_state_timeout_seconds=1.0,
    )

    assert "TX exact closure failed" in str(result.get("error") or "")
    assert result.get("acquisition_evidence") is None
    diagnostics = result.get("timeout_diagnostics") or {}
    assert diagnostics.get("classification") == "error_with_no_detectable_remaining_work"
    assert diagnostics.get("classification") != "checkpoint_complete_promotion"


@pytest.mark.asyncio
async def test_strict_acquisition_waits_past_checkpoint_settle_for_worker_lifecycle(
    monkeypatch, tmp_path
):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "STATE-TX-partial.json").write_text(
        json.dumps(
            {
                "state_code": "TX",
                "updated_at": "2026-05-28T00:00:00+00:00",
                "stage_label": "texas:strict-statute-zip-complete",
                "statutes_count": 1,
                "progress": {"codes_completed": 30, "codes_total": 30},
                "statutes": [{"statute_id": "Texas Code § 1"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))
    monkeypatch.setenv("STATE_SCRAPER_TIMEOUT_POLL_SECONDS", "0.01")
    monkeypatch.setenv("STATE_SCRAPER_CHECKPOINT_COMPLETE_SETTLE_SECONDS", "0.01")
    monkeypatch.setenv(scraper_module.STRICT_MULTIFETCH_EVIDENCE_ENV, "true")

    expected = {
        "state_code": "TX",
        "status": "lifecycle-complete",
        "acquisition_evidence": {"enabled": True},
    }

    def _fake_scrape_state_once_sync(**_kwargs):
        time.sleep(0.08)
        return expected

    monkeypatch.setattr(
        scraper_module,
        "_scrape_state_once_sync",
        _fake_scrape_state_once_sync,
    )

    started_at = time.perf_counter()
    result = await scraper_module._run_sync_scrape_on_daemon_thread(
        state_code="TX",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=True,
        min_full_text_chars=1,
        hydrate_statute_text=False,
        timeout_seconds=0.5,
    )

    assert {
        key: result[key]
        for key in expected
    } == expected
    assert result["worker_quiescence"] == {
        "attested": True,
        "quiescent": True,
        "completion_mode": "worker_returned",
        "worker_name": "state-scrape-tx",
    }
    assert time.perf_counter() - started_at >= 0.05


def test_state_laws_scraper_timeout_checkpoint_diagnostics_work_remaining(tmp_path, monkeypatch):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-OK-partial.json"
    checkpoint_path.write_text(
        '{"state_code":"OK","scanned_candidates":100,"discovered_candidates":1000,'
        '"updated_at":1716210000.0,'
        '"statutes":[{"statute_id":"ok-1","section_number":"1","section_name":"S1","full_text":"§ 1 text"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))

    result = scraper_module._load_partial_checkpoint_state_result(
        "OK",
        "Failed to scrape Oklahoma: timed out after 900 seconds",
    )

    assert result is not None
    diag = result.get("timeout_diagnostics") or {}
    assert diag.get("timed_out") is True
    assert diag.get("classification") == "timeout_while_work_remaining"
    assert diag.get("work_remaining") is True
    assert diag.get("signal_kind") == "candidate_scan"
    assert diag.get("progress_scanned") == 100
    assert diag.get("progress_discovered") == 1000


def test_state_laws_scraper_timeout_checkpoint_diagnostics_no_work_remaining(tmp_path, monkeypatch):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-RI-partial.json"
    checkpoint_path.write_text(
        '{"state_code":"RI","progress":{"codes_completed":1,"codes_total":1},'
        '"updated_at":"2026-05-20T15:00:00+00:00",'
        '"statutes":[{"statute_id":"ri-1","section_number":"1","section_name":"S1","full_text":"§ 1 text"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))

    result = scraper_module._load_partial_checkpoint_state_result(
        "RI",
        "Failed to scrape Rhode Island: timed out after 900 seconds",
    )

    assert result is not None
    diag = result.get("timeout_diagnostics") or {}
    assert diag.get("timed_out") is True
    assert diag.get("classification") == "timeout_with_no_detectable_remaining_work"
    assert diag.get("work_remaining") is False
    assert diag.get("signal_kind") == "codes_progress"


@pytest.mark.parametrize(
    "explicit_noncompletion",
    (
        {"stage_label": "scrape_all:incomplete"},
        {"progress": {"bychapter_completion_status": "incomplete"}},
        {"progress": {"bychapter_unresolved_count": 101}},
        {
            "progress": {
                "code_failures": [
                    "North Carolina General Statutes: exhaustive harvest incomplete"
                ]
            }
        },
    ),
)
def test_checkpoint_promotion_fails_closed_on_explicit_nc_noncompletion(
    tmp_path,
    monkeypatch,
    explicit_noncompletion,
):
    """NC's reconciled frontier failure outranks equal chapter counters."""

    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-NC-partial.json"
    progress = {
        "bychapter_attempted_count": 322,
        "bychapter_resolved_count": 221,
        "chapters_scanned": 322,
        "codes_completed": 0,
        "codes_total": 1,
        "discovered_chapters": 322,
    }
    progress.update(explicit_noncompletion.get("progress", {}))
    checkpoint_path.write_text(
        json.dumps(
            {
                "state_code": "NC",
                "stage_label": explicit_noncompletion.get(
                    "stage_label", "north-carolina:bychapter"
                ),
                "updated_at": "2026-08-25T09:23:48+00:00",
                "progress": progress,
                "statutes": [
                    {
                        "statute_id": "North Carolina General Statutes § 1A-1",
                        "section_number": "1A-1",
                        "section_name": "Scope of rules",
                        "full_text": "These rules govern civil procedure.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))

    recovered = scraper_module._load_partial_checkpoint_state_result(
        "NC",
        "Failed to scrape North Carolina: full-corpus frontier is incomplete",
    )

    assert recovered is not None
    diagnostics = recovered.get("timeout_diagnostics") or {}
    assert diagnostics.get("signal_kind") == "chapter_scan"
    assert diagnostics.get("progress_scanned") == 322
    assert diagnostics.get("progress_discovered") == 322
    assert diagnostics.get("work_remaining") is True
    assert diagnostics.get("classification") == "error_while_work_remaining"
    not_promoted = scraper_module._promote_timeout_checkpoint_result_if_no_remaining_work(
        "NC",
        recovered,
        reason="checkpoint_error_no_remaining_work",
    )
    assert not_promoted is recovered
    assert not_promoted["error"]
    assert (
        not_promoted["timeout_diagnostics"]["classification"]
        == "error_while_work_remaining"
    )


def test_timeout_checkpoint_keeps_nested_parent_frontier_open(
    tmp_path,
    monkeypatch,
):
    """A complete child scan cannot mask unvisited parent frontier units."""

    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-HI-partial.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "state_code": "HI",
                "progress": {
                    "titles_scanned": 2,
                    "discovered_titles": 14,
                    "chapters_scanned": 70,
                    "discovered_chapters": 145,
                    "sections_scanned": 1668,
                    "discovered_sections": 1668,
                },
                "updated_at": "2026-08-24T17:53:40+00:00",
                "statutes": [
                    {
                        "statute_id": "HI-1-1",
                        "section_number": "1-1",
                        "section_name": "Definitions",
                        "full_text": "The definitions in this section apply.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))

    result = scraper_module._load_partial_checkpoint_state_result(
        "HI",
        "Failed to scrape Hawaii: timed out after 900 seconds",
    )

    assert result is not None
    diag = result.get("timeout_diagnostics") or {}
    # Retain the high-cardinality section dimension as the primary progress
    # diagnostic while deriving completion from all populated dimensions.
    assert diag.get("signal_kind") == "section_scan"
    assert diag.get("progress_scanned") == 1668
    assert diag.get("progress_discovered") == 1668
    assert diag.get("coverage_ratio") == 1.0
    assert diag.get("work_remaining") is True
    assert diag.get("classification") == "timeout_while_work_remaining"


def test_state_laws_scraper_timeout_checkpoint_prefers_section_signal_over_unscanned_title(
    tmp_path, monkeypatch
):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "STATE-WA-partial.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "state_code": "WA",
                "progress": {
                    "titles_scanned": 0,
                    "discovered_titles": 105,
                    "sections_scanned": 91,
                    "discovered_sections": 110,
                    "codes_completed": 0,
                    "codes_total": 1,
                },
                "updated_at": "2026-05-26T07:56:26+00:00",
                "statutes": [
                    {
                        "statute_id": "wa-1",
                        "section_number": "1.01.001",
                        "section_name": "S1",
                        "full_text": "Section text",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(checkpoint_dir))

    result = scraper_module._load_partial_checkpoint_state_result(
        "WA",
        "Failed to scrape Washington: timed out after 900 seconds",
    )

    assert result is not None
    diag = result.get("timeout_diagnostics") or {}
    assert diag.get("timed_out") is True
    assert diag.get("signal_kind") == "section_scan"
    assert diag.get("work_remaining") is True
    assert diag.get("progress_scanned") == 91
    assert diag.get("progress_discovered") == 110
    assert diag.get("classification") == "timeout_while_work_remaining"


def test_state_laws_scraper_quality_accepts_compound_legal_section_numbers():
    section_numbers = (
        "5/0.01",
        "20/1a",
        "404/10",
        "5/507LLL",
        "1210/11-a",
        "5/513b1.1",
        "3435/.01",
        "14/4.5",
        "1/1(Art.III)",
        "5/42-o",
    )
    statutes = [
        {
            "section_number": section_number,
            "section_name": "Short title",
            "source_url": "https://legislature.example/statutes/details",
            "full_text": "Official enacted legal text establishing a duty.",
        }
        for section_number in section_numbers
    ]

    metrics = scraper_module._compute_state_quality_metrics(statutes)

    assert metrics["numeric_section_name_ratio"] == 1.0
    assert metrics["scaffold_ratio"] == 0.0
    assert scraper_module._should_flag_quality(metrics) is False


def test_state_laws_scraper_quality_rejects_malformed_compound_labels():
    section_numbers = (
        "Section-1",
        "404/home",
        "404/history",
        "404/",
        "/10",
        "404//10",
        "404/../10",
        "404/10?x=1",
        "cash/payments",
        "404 / 10",
    )
    statutes = [
        {
            "section_number": section_number,
            "section_name": "Navigation",
            "source_url": "https://legislature.example/calendar",
            "full_text": "Skip navigation and return to the calendar.",
        }
        for section_number in section_numbers
    ]

    metrics = scraper_module._compute_state_quality_metrics(statutes)

    assert metrics["numeric_section_name_ratio"] == 0.0
    assert metrics["nav_like_ratio"] == 1.0
    assert metrics["scaffold_ratio"] == 1.0
    assert scraper_module._should_flag_quality(metrics) is True


def test_state_laws_scraper_quality_flags_bill_history_noise():
    statutes = [
        {
            "section_number": "25-3-33",
            "section_name": "Commissioner of Public Safety; remove from omnibus pay section.",
            "source_url": "https://web.archive.org/web/19980110154920/http://billstatus.ls.state.ms.us/1997/history/HB/HB0006.htm",
            "full_text": (
                "HB 6 - History of Actions/Background Mississippi Legislature 1997 Regular Session "
                "House Bill 6 [Introduced] History of Actions: ..."
            ),
        },
        {
            "section_number": "27-33-77",
            "section_name": "Homestead exemption; reimburse cities.",
            "source_url": "https://web.archive.org/web/19980110154920/http://billstatus.ls.state.ms.us/1997/history/HB/HB0378.htm",
            "full_text": (
                "HB 378 - History of Actions/Background Mississippi Legislature 1997 Regular Session "
                "House Bill 378 [Introduced] History of Actions: ..."
            ),
        },
    ]
    metrics = scraper_module._compute_state_quality_metrics(statutes)
    assert metrics["bill_history_ratio"] >= 0.5
    assert scraper_module._should_flag_quality(metrics) is True


@pytest.mark.asyncio
async def test_state_laws_scraper_full_corpus_low_quality_is_promoted_to_error(monkeypatch):
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    async def _fake_run_sync_scrape_on_daemon_thread(**_kwargs):
        return {
            "state_code": "MS",
            "state_name": "Mississippi",
            "error": None,
            "statutes_count": 10,
            "zero_statute": False,
            "low_quality": True,
            "quality_metrics": {
                "total": 10,
                "nav_like_ratio": 0.0,
                "fallback_section_ratio": 0.0,
                "numeric_section_name_ratio": 0.9,
                "scaffold_ratio": 0.0,
                "bill_history_ratio": 0.8,
            },
            "warnings": [],
            "statute_data": {
                "state_code": "MS",
                "state_name": "Mississippi",
                "title": "Mississippi Laws",
                "source": "Official State Legislative Website",
                "scraped_at": "2026-05-26T00:00:00",
                "statutes": [{"statute_id": "MS-1"}],
            },
        }

    monkeypatch.setattr(
        scraper_module, "_run_sync_scrape_on_daemon_thread", _fake_run_sync_scrape_on_daemon_thread
    )

    result = await scraper_module._scrape_state_with_retries(
        state_code="MS",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=None,
        strict_full_text=False,
        min_full_text_chars=0,
        hydrate_statute_text=True,
        retry_attempts=0,
        retry_zero_statute_states=True,
        per_state_timeout_seconds=0.0,
    )

    assert result.get("error")
    assert "full-corpus quality gate failed" in str(result.get("error"))
