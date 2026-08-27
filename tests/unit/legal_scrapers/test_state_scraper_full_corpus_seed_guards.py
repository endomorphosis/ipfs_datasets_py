"""Regressions for bounded seed/recovery paths in state full-corpus mode."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.district_of_columbia import (
    DistrictOfColumbiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
    GeorgiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.hawaii import (
    HawaiiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import (
    IndianaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.iowa import IowaScraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import (
    LouisianaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import (
    MarylandScraper,
)


def _row(
    code: str, section: str, *, source_kind: str = "official_test"
) -> NormalizedStatute:
    return NormalizedStatute(
        state_code=code,
        state_name=code,
        statute_id=f"{code}-{section}",
        code_name=f"{code} Code",
        section_number=section,
        section_name=section,
        full_text=(f"{code} official statute body text. " * 20),
        source_url=f"https://official.example/{code.lower()}/{section}",
        structured_data={"source_kind": source_kind, "skip_hydrate": True},
    )


def _load_guard_audit():
    repo_root = Path(__file__).resolve().parents[3]
    path = (
        repo_root
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_state_scraper_full_corpus_guards.py"
    )
    spec = importlib.util.spec_from_file_location(
        "full_corpus_guard_regression_audit", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_state_scrapers_pass_static_full_corpus_guard_audit() -> None:
    audit = _load_guard_audit()
    repo_root = Path(__file__).resolve().parents[3]
    scraper_root = audit._scraper_root(repo_root)

    findings = []
    for state, module_name in audit.STATE_MODULES.items():
        findings.extend(
            audit.audit_file(
                state=state,
                path=scraper_root / f"{module_name}.py",
                repo_root=repo_root,
            )
        )

    assert findings == []


@pytest.mark.anyio
async def test_dc_uncapped_full_mode_skips_seed_but_bounded_probe_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        district_of_columbia_constitution,
        district_of_columbia_xml,
    )

    monkeypatch.setattr(
        district_of_columbia_constitution,
        "configured_constitution_html_path",
        lambda: None,
    )
    monkeypatch.setattr(
        district_of_columbia_xml, "configured_section_xml_path", lambda: None
    )
    monkeypatch.setattr(district_of_columbia_xml, "configured_xml_dir", lambda: None)
    calls = {"seed": 0}
    seed = _row("DC", "seed")

    async def _empty_official(self, code_name: str, max_statutes=None):
        return []

    async def _seed(self, code_name: str, max_statutes: int):
        calls["seed"] += 1
        return [seed]

    async def _empty_generic(self, code_name, candidate, citation_format, max_sections):
        return []

    monkeypatch.setattr(
        DistrictOfColumbiaScraper, "_scrape_official_index", _empty_official
    )
    monkeypatch.setattr(
        DistrictOfColumbiaScraper, "_scrape_direct_seed_sections", _seed
    )
    monkeypatch.setattr(DistrictOfColumbiaScraper, "_generic_scrape", _empty_generic)
    monkeypatch.setattr(DistrictOfColumbiaScraper, "has_playwright", lambda self: False)

    scraper = DistrictOfColumbiaScraper("DC", "District of Columbia")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    with pytest.raises(RuntimeError, match="official hierarchy did not close"):
        await scraper.scrape_code("D.C. Code", "https://code.dccouncil.gov", None)
    assert calls["seed"] == 0

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS")
    assert await scraper.scrape_code("D.C. Code", "https://code.dccouncil.gov", 1) == [
        seed
    ]
    assert calls["seed"] == 1


@pytest.mark.anyio
async def test_hawaii_uncapped_full_mode_skips_bounded_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        hawaii_constitution,
        hawaii_section,
    )

    monkeypatch.setattr(
        hawaii_constitution, "configured_constitution_html_path", lambda: None
    )
    monkeypatch.setattr(hawaii_section, "configured_section_html_path", lambda: None)
    calls = {"seed": 0, "archive": 0}
    seed = _row("HI", "seed")
    archived = _row("HI", "archive", source_kind="recovery_wayback")

    async def _empty_official(
        self, *, code_name: str, code_url: str, max_statutes=None
    ):
        return []

    async def _seed(self, code_name: str, max_statutes: int):
        calls["seed"] += 1
        return [seed]

    async def _archive(self, code_name: str, max_statutes: int):
        calls["archive"] += 1
        return [archived]

    monkeypatch.setattr(HawaiiScraper, "_scrape_official_hrs_tree", _empty_official)
    monkeypatch.setattr(HawaiiScraper, "_scrape_seed_sections", _seed)
    monkeypatch.setattr(HawaiiScraper, "_scrape_archived_hrscurrent", _archive)

    scraper = HawaiiScraper("HI", "Hawaii")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    assert (
        await scraper.scrape_code("Hawaii Revised Statutes", "https://example.hi", None)
        == []
    )
    assert calls == {"seed": 0, "archive": 0}

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS")
    assert await scraper.scrape_code(
        "Hawaii Revised Statutes", "https://example.hi", 2
    ) == [archived]
    assert calls == {"seed": 1, "archive": 1}


@pytest.mark.anyio
async def test_indiana_uncapped_full_mode_never_returns_seed_pdfs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        indiana_constitution,
    )

    monkeypatch.setattr(
        indiana_constitution, "configured_constitution_text_path", lambda: None
    )
    calls = {"seed": 0}
    seed = _row("IN", "seed", source_kind="recovery_seed_pdf")

    async def _seed(self, code_name: str, max_statutes: int):
        calls["seed"] += 1
        return [seed]

    async def _empty_async(*args, **kwargs):
        return []

    monkeypatch.setattr(
        IndianaScraper, "_load_partial_checkpoint_statutes", lambda *a, **k: []
    )
    monkeypatch.setattr(IndianaScraper, "_scrape_official_bulk_zip", lambda *a, **k: [])
    monkeypatch.setattr(IndianaScraper, "_scrape_seed_archive_pdfs", _seed)
    monkeypatch.setattr(IndianaScraper, "_scrape_indiana_download_bundle", _empty_async)
    monkeypatch.setattr(IndianaScraper, "_scrape_archived_chapter_pdfs", _empty_async)
    monkeypatch.setattr(IndianaScraper, "_scrape_archived_justia_titles", _empty_async)
    monkeypatch.setattr(IndianaScraper, "_scrape_archived_title_pages", _empty_async)
    for name in (
        "INDIANA_ALLOW_JUSTIA_FALLBACK",
        "STATE_SCRAPER_IN_ALLOW_JUSTIA_FALLBACK",
        "INDIANA_JUSTIA_ENABLE",
        "INDIANA_GENERIC_FALLBACK",
    ):
        monkeypatch.delenv(name, raising=False)

    scraper = IndianaScraper("IN", "Indiana")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    assert await scraper.scrape_code("Indiana Code", "https://iga.in.gov", None) == []
    assert calls["seed"] == 0

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS")
    assert await scraper.scrape_code("Indiana Code", "https://iga.in.gov", 2) == [seed]
    assert calls["seed"] == 1


@pytest.mark.anyio
async def test_iowa_uncapped_full_mode_refuses_underfilled_official_and_capped_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        iowa_constitution,
    )

    monkeypatch.setattr(
        iowa_constitution, "configured_constitution_html_path", lambda: None
    )
    monkeypatch.setattr(
        IowaScraper, "_scrape_configured_chapter_xml", lambda *a, **k: []
    )
    direct = _row("IA", "seed", source_kind="official_seed_section")
    partial = _row("IA", "partial")
    calls = {"direct": 0, "recovery": 0}

    async def _partial_official(self, code_name: str):
        return [partial]

    async def _direct(self, code_name: str, max_statutes: int):
        calls["direct"] += 1
        return [direct]

    async def _recovery(*args, **kwargs):
        calls["recovery"] += 1
        return [partial]

    monkeypatch.setattr(
        IowaScraper, "_scrape_official_iowa_sections", _partial_official
    )
    monkeypatch.setattr(IowaScraper, "_scrape_direct_seed_sections", _direct)
    monkeypatch.setattr(IowaScraper, "_scrape_live_code_stubs", _recovery)
    monkeypatch.setattr(IowaScraper, "_scrape_archived_code_stubs", _recovery)

    scraper = IowaScraper("IA", "Iowa")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    assert (
        await scraper.scrape_code("Iowa Code", "https://www.legis.iowa.gov", None) == []
    )
    assert calls == {"direct": 0, "recovery": 0}

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS")
    assert await scraper.scrape_code("Iowa Code", "https://www.legis.iowa.gov", 1) == [
        direct
    ]
    assert calls == {"direct": 1, "recovery": 0}


@pytest.mark.anyio
async def test_louisiana_uncapped_full_mode_skips_live_seeds_and_archives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        louisiana_constitution,
        louisiana_law,
    )

    monkeypatch.setattr(
        louisiana_constitution, "configured_constitution_text_path", lambda: None
    )
    monkeypatch.setattr(
        louisiana_law, "parse_configured_louisiana_law", lambda **kwargs: []
    )
    live = _row("LA", "seed", source_kind="official_live_law_seed")
    calls = {"live": 0, "archive": 0}

    async def _live(self, code_name: str, max_statutes=None):
        calls["live"] += 1
        return [live]

    async def _archive(self, code_name: str, max_statutes: int):
        calls["archive"] += 1
        return [_row("LA", "archive", source_kind="recovery_wayback")]

    monkeypatch.setenv("STATE_SCRAPER_LA_SKIP_LIVE_TOC", "1")
    monkeypatch.setattr(LouisianaScraper, "_scrape_live_law_pages", _live)
    monkeypatch.setattr(LouisianaScraper, "_scrape_archived_law_pages", _archive)

    scraper = LouisianaScraper("LA", "Louisiana")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    assert (
        await scraper.scrape_code(
            "Louisiana Revised Statutes", "https://legis.la.gov", None
        )
        == []
    )
    assert calls == {"live": 0, "archive": 0}

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS")
    assert await scraper.scrape_code(
        "Louisiana Revised Statutes", "https://legis.la.gov", 1
    ) == [live]
    assert calls == {"live": 1, "archive": 0}


@pytest.mark.anyio
async def test_louisiana_uncapped_full_mode_defaults_to_complete_official_toc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        louisiana_constitution,
        louisiana_law,
    )

    monkeypatch.setattr(
        louisiana_constitution, "configured_constitution_text_path", lambda: None
    )
    monkeypatch.setattr(
        louisiana_law, "parse_configured_louisiana_law", lambda **kwargs: []
    )
    official = _row("LA", "1:1", source_kind="official_louisiana_toc_law_page")
    calls = {"toc": 0, "live": 0, "archive": 0}

    async def _toc(self, code_name: str, max_statutes=None):
        calls["toc"] += 1
        assert max_statutes is None
        return [official]

    async def _live(self, code_name: str, max_statutes=None):
        calls["live"] += 1
        return []

    async def _archive(self, code_name: str, max_statutes: int):
        calls["archive"] += 1
        return []

    monkeypatch.delenv("STATE_SCRAPER_LA_SKIP_LIVE_TOC", raising=False)
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(LouisianaScraper, "_scrape_live_toc_pages", _toc)
    monkeypatch.setattr(LouisianaScraper, "_scrape_live_law_pages", _live)
    monkeypatch.setattr(LouisianaScraper, "_scrape_archived_law_pages", _archive)

    scraper = LouisianaScraper("LA", "Louisiana")
    assert await scraper.scrape_code(
        "Louisiana Revised Statutes", "https://legis.la.gov", None
    ) == [official]
    assert calls == {"toc": 1, "live": 0, "archive": 0}


@pytest.mark.anyio
async def test_maryland_full_mode_returns_uncapped_official_api_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        maryland_constitution,
        maryland_section,
    )

    monkeypatch.setattr(
        maryland_constitution, "configured_constitution_html_path", lambda: None
    )
    monkeypatch.setattr(maryland_section, "configured_section_html_path", lambda: None)
    rows = [_row("MD", "1"), _row("MD", "2")]
    requested = []

    async def _api(self, code_name: str, max_statutes=None):
        requested.append(max_statutes)
        return list(rows)

    monkeypatch.setattr(MarylandScraper, "_scrape_api_sections", _api)
    scraper = MarylandScraper("MD", "Maryland")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    assert (
        await scraper.scrape_code("Maryland Code", "https://mgaleg.maryland.gov", None)
        == rows
    )
    assert requested == [None]

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS")
    assert (
        await scraper.scrape_code("Maryland Code", "https://mgaleg.maryland.gov", 1)
        == rows[:1]
    )
    assert requested == [None, 1]


@pytest.mark.anyio
async def test_georgia_section_parser_has_no_hidden_eight_row_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        georgia_archive,
    )

    requested = {}
    parsed = _row("GA", "16-1-1")

    async def _html(self, url: str, timeout_seconds: int = 18):
        return "<html><body>Official Georgia Code section</body></html>"

    def _parse(html, *, source_url: str, code_name: str, max_statutes=None):
        requested["max_statutes"] = max_statutes
        return [parsed]

    monkeypatch.setattr(GeorgiaScraper, "_fetch_official_ga_html", _html)
    monkeypatch.setattr(georgia_archive, "parse_georgia_archive_html", _parse)
    scraper = GeorgiaScraper("GA", "Georgia")

    result = await scraper._parse_section_page(
        code_name="Official Code of Georgia",
        section_url="https://www.legis.ga.gov/legislation/georgia-code/title-16/chapter-1/section-16-1-1/",
        section_label="16-1-1",
        title_label="Title 16",
        chapter_label="Chapter 1",
    )

    assert result is parsed
    assert requested["max_statutes"] is None
