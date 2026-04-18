import asyncio
import time

import pytest

from ipfs_datasets_py.processors.legal_scrapers import state_laws_scraper as scraper_module


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
        == "https://www.palegis.us/statutes/consolidated/view-statute?CHAPTER=053.&DIV=00.&SECTION=028.&SUBSCTN=000.&TTL=23"
    )
    assert (
        scraper_module.build_state_law_section_url("AZ", "13-1203", code_name="Ariz. Rev. Stat.")
        == "https://www.azleg.gov/ars/13/01203.htm"
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
        scraper_module.build_state_law_section_url("NC", "14-33", code_name="N.C. Gen. Stat.")
        == "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_14/GS_14-33.html"
    )
    assert (
        scraper_module.build_state_law_section_url("OH", "2903.13", code_name="Ohio Rev. Code")
        == "https://codes.ohio.gov/ohio-revised-code/section-2903.13"
    )
    assert (
        scraper_module.build_state_law_section_url("WA", "9A.36.041", code_name="Wash. Rev. Code")
        == "https://app.leg.wa.gov/RCW/default.aspx?cite=9A.36.041"
    )


def test_state_laws_scraper_recovery_section_url_edge_cases():
    assert scraper_module.build_state_law_section_url("", "518.17") == ""
    assert scraper_module.build_state_law_section_url("MN", "") == ""
    assert scraper_module.build_state_law_section_url("ZZ", "1.2") == ""
    assert scraper_module.build_state_law_section_url("FL", "abc", code_name="Fla. Stat.") == ""
    assert scraper_module.build_state_law_section_url("IL", "602.7", code_name="ILCS") == ""
    assert scraper_module.build_state_law_section_url("PA", "12", code_name="23 Pa.C.S.") == ""

    assert (
        scraper_module.build_state_law_section_url("TX", "153.002", code_name="Penal Code", preferred_host="statutes.capitol.texas.gov")
        == "https://statutes.capitol.texas.gov/Docs/PE/htm/PE.153.htm#153.002"
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

    assert result == {"state_code": "OR", "status": "ok"}
    assert captured["daemon"] is True
    assert captured["name"] == "state-scrape-or"


@pytest.mark.asyncio
async def test_state_laws_scraper_timeout_returns_without_waiting_for_blocked_worker(monkeypatch):
    def _fake_scrape_state_once_sync(**kwargs):
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

    await asyncio.sleep(0.25)
