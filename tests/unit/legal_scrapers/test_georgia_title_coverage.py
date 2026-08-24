"""Fail-closed coverage checks for configured Georgia OCGA title dumps."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia import (
    GeorgiaFullCorpusIncompleteError,
    GeorgiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_title import (
    GeorgiaTitleCoverageError,
    configured_title_coverage,
    parse_configured_georgia_title,
    require_complete_configured_title_coverage,
)
from ipfs_datasets_py.utils import anyio_compat as asyncio


def _title_text(title: int, *, section_title: int | None = None) -> str:
    number = int(section_title if section_title is not None else title)
    return (
        f"{number}-1-1. Test provision for Title {number}.\n"
        "This official configured title dump contains a substantive statutory body "
        "long enough to be admitted by the Georgia title parser for coverage testing.\n"
    )


def _write_frontier(directory: Path, *, stop: int = 53) -> None:
    directory.mkdir()
    for number in range(1, stop + 1):
        (directory / f"title-{number}.txt").write_text(
            _title_text(number),
            encoding="utf-8",
        )


def _configure_text_dir(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    for name in (
        "GEORGIA_TITLE_TEXT",
        "GEORGIA_TITLE_PDF",
        "GEORGIA_TITLE_PDF_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEORGIA_TITLE_TEXT_DIR", str(directory))


def _scrape(scraper: GeorgiaScraper, *, max_statutes: int | None):
    return asyncio.run(
        scraper.scrape_code(
            "Official Code of Georgia Annotated",
            "https://www.legis.ga.gov/legislation/georgia-code",
            max_statutes=max_statutes,
        )
    )


def test_exact_53_configured_titles_are_inventory_not_live_full_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dumps = tmp_path / "ga"
    _write_frontier(dumps)
    _configure_text_dir(monkeypatch, dumps)
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    coverage = configured_title_coverage()
    assert coverage["complete"] is True
    assert coverage["expected"] == [str(number) for number in range(1, 54)]
    assert coverage["present"] == coverage["expected"]

    rows = parse_configured_georgia_title(
        paths=sorted(dumps.iterdir()),
        require_complete_inventory=True,
    )
    assert len(rows) == 53
    assert {row.title_number for row in rows} == {
        str(number) for number in range(1, 54)
    }
    assert all(
        row.structured_data["configured_title_inventory_complete"] is True
        for row in rows
    )
    assert all(
        row.structured_data["configured_title_inventory_count"] == 53 for row in rows
    )
    assert all(row.structured_data["fresh_live_frontier_verified"] is False for row in rows)
    assert all(row.structured_data["full_corpus_admissible"] is False for row in rows)
    assert all(
        len(row.structured_data["configured_title_dump_sha256"]) == 64 for row in rows
    )

    with pytest.raises(GeorgiaFullCorpusIncompleteError) as exc_info:
        _scrape(GeorgiaScraper("GA", "Georgia"), max_statutes=None)

    assert exc_info.value.evidence["configured_title_inventory_complete"] is True
    assert exc_info.value.evidence["configured_title_inventory_count"] == 53
    assert exc_info.value.evidence["fresh_live_frontier_verified"] is False
    assert exc_info.value.evidence["full_corpus_admissible"] is False


def test_uncapped_full_mode_missing_title_fails_before_archive_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dumps = tmp_path / "ga"
    _write_frontier(dumps, stop=52)
    _configure_text_dir(monkeypatch, dumps)
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    archive_called = False

    def _archive_fallback(**_kwargs):
        nonlocal archive_called
        archive_called = True
        return []

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_archive."
        "parse_configured_georgia_archive",
        _archive_fallback,
    )

    with pytest.raises(GeorgiaTitleCoverageError) as exc_info:
        _scrape(GeorgiaScraper("GA", "Georgia"), max_statutes=None)

    assert exc_info.value.coverage["missing"] == ["53"]
    assert archive_called is False


@pytest.mark.parametrize(
    ("defect", "field"),
    (
        ("duplicate", "duplicates"),
        ("extra", "extra"),
        ("unparseable", "unparseable"),
    ),
)
def test_complete_coverage_rejects_filename_frontier_defects(
    tmp_path: Path,
    defect: str,
    field: str,
) -> None:
    dumps = tmp_path / "ga"
    _write_frontier(dumps)
    if defect == "duplicate":
        (dumps / "ocga_16.txt").write_text(_title_text(16), encoding="utf-8")
    elif defect == "extra":
        (dumps / "title-54.txt").write_text(_title_text(54), encoding="utf-8")
    else:
        (dumps / "georgia-code.txt").write_text(_title_text(16), encoding="utf-8")

    with pytest.raises(GeorgiaTitleCoverageError) as exc_info:
        require_complete_configured_title_coverage(sorted(dumps.iterdir()))

    assert exc_info.value.coverage[field]


@pytest.mark.parametrize(
    ("defect", "field"), (("empty", "empty"), ("mismatch", "mismatched"))
)
def test_uncapped_full_mode_rejects_empty_or_mismatched_title_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
    field: str,
) -> None:
    dumps = tmp_path / "ga"
    _write_frontier(dumps)
    if defect == "empty":
        (dumps / "title-16.txt").write_text("", encoding="utf-8")
    else:
        (dumps / "title-16.txt").write_text(
            _title_text(16, section_title=17), encoding="utf-8"
        )
    _configure_text_dir(monkeypatch, dumps)
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    with pytest.raises(GeorgiaTitleCoverageError) as exc_info:
        _scrape(GeorgiaScraper("GA", "Georgia"), max_statutes=None)

    assert exc_info.value.coverage[field]


def test_bounded_mode_keeps_single_nonstandard_dump_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dump = tmp_path / "operator-export.txt"
    dump.write_text(_title_text(16), encoding="utf-8")
    monkeypatch.setenv("GEORGIA_TITLE_TEXT", str(dump))
    monkeypatch.delenv("GEORGIA_TITLE_TEXT_DIR", raising=False)
    monkeypatch.delenv("GEORGIA_TITLE_PDF", raising=False)
    monkeypatch.delenv("GEORGIA_TITLE_PDF_DIR", raising=False)
    # A caller-provided bound keeps this a probe even if a parent process left
    # the full-corpus environment flag set.
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    rows = _scrape(GeorgiaScraper("GA", "Georgia"), max_statutes=1)

    assert len(rows) == 1
    assert rows[0].title_number == "16"
    assert rows[0].structured_data["configured_title_number"] is None
    assert "configured_title_inventory_complete" not in rows[0].structured_data
    assert "legis.ga.gov" in rows[0].source_url
