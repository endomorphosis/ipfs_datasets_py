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
    assert scraper_module.build_state_law_section_url("PA", "12", code_name="23 Pa.C.S.") == ""

    assert (
        scraper_module.build_state_law_section_url("TX", "153.002", code_name="Penal Code", preferred_host="statutes.capitol.texas.gov")
        == "https://statutes.capitol.texas.gov/Docs/PE/htm/PE.153.htm#153.002"
    )


def test_state_laws_scraper_builds_unknown_backlog_section_urls():
    expected_urls = {
        ("AL", "13A-6-2", "Ala. Code"): "https://alison.legislature.state.al.us/code-of-alabama?section=13A-6-2",
        ("AR", "5-13-201", "Ark. Code"): "https://law.justia.com/codes/arkansas/title-5/subtitle-2/chapter-13/subchapter-2/section-5-13-201/",
        ("CO", "18-3-204", "Colo. Rev. Stat."): "https://colorado.public.law/statutes/crs_18-3-204",
        ("CT", "53a-61", "Conn. Gen. Stat."): "https://www.cga.ct.gov/current/pub/chap_952.htm#sec_53a-61",
        ("DE", "11-601", "Del. Code"): "https://delcode.delaware.gov/title11/c005/sc02/index.html#601",
        ("GA", "16-5-23", "Ga. Code"): "https://law.justia.com/codes/georgia/title-16/chapter-5/article-2/section-16-5-23/",
        ("HI", "707-712", "Haw. Rev. Stat."): "https://www.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/HRS0707/HRS_0707-0712.htm",
        ("KY", "508.030", "Ky. Rev. Stat."): "https://law.justia.com/codes/kentucky/chapter-508/section-508-030/",
        ("LA", "14:35", "La. Rev. Stat."): "https://legis.la.gov/legis/Law.aspx?d=78452",
        ("MD", "3-203", "Md. Code"): "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcr&section=3-203",
        ("MS", "97-3-7", "Miss. Code"): "https://law.justia.com/codes/mississippi/2024/title-97/chapter-3/section-97-3-7/",
        ("NH", "631:2-a", "N.H. Rev. Stat."): "https://gc.nh.gov/rsa/html/LXII/631/631-2-a.htm",
        ("NJ", "2C:12-1", "N.J. Stat."): "https://law.justia.com/codes/new-jersey/title-2c/section-2c-12-1/",
        ("NM", "30-3-4", "N.M. Stat."): "https://law.justia.com/codes/new-mexico/chapter-30/article-3/section-30-3-4/",
        ("ND", "12.1-17-01", "N.D. Cent. Code"): "https://ndlegis.gov/cencode/t12-1c17.pdf",
        ("OK", "21-644", "Okla. Stat."): "https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os21.pdf",
        ("TN", "39-13-101", "Tenn. Code"): "https://law.justia.com/codes/tennessee/title-39/chapter-13/part-1/section-39-13-101/",
        ("WY", "6-2-501", "Wyo. Stat."): "https://wyoleg.gov/statutes/compress/title06.pdf",
    }

    for (state, section, code_name), expected_url in expected_urls.items():
        assert scraper_module.build_state_law_section_url(state, section, code_name=code_name) == expected_url


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
