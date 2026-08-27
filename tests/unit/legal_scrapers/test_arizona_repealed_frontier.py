"""Arizona's repealed-title coverage receipt is not a synthetic statute."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arizona import (
    ArizonaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)

TITLE_2_URL = "https://www.azleg.gov/arsDetail/?title=2"
REPEALED_HTML = b"""
<!doctype html><html><body>
  <h1 class="topTitle">Title 2 - THIS TITLE HAS BEEN REPEALED</h1>
  <p>Click on the Section Number to open/view the document.</p>
</body></html>
"""


def _receipt(
    body: bytes = REPEALED_HTML,
    *,
    requested_url: str = TITLE_2_URL,
    final_url: str = TITLE_2_URL,
) -> dict[str, object]:
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "status_code": 200,
        "observed_at": datetime.now(UTC).isoformat(),
        "body": body,
        "content_sha256": hashlib.sha256(body).hexdigest(),
    }


def test_exact_official_repealed_heading_creates_zero_unit_frontier() -> None:
    scraper = ArizonaScraper("AZ", "Arizona")

    exclusion = scraper._official_repealed_title_exclusion(
        code_name="Arizona Revised Statutes Title 2",
        code_url=TITLE_2_URL,
        receipt=_receipt(),
    )

    assert exclusion is not None
    assert exclusion["disposition"] == "repealed"
    assert exclusion["frontier_closed"] is True
    assert exclusion["expected_statute_count"] == 0
    assert exclusion["official_heading"] == "Title 2 - THIS TITLE HAS BEEN REPEALED"
    assert exclusion["content_sha256"] == hashlib.sha256(REPEALED_HTML).hexdigest()


def test_repealed_frontier_rejects_redirect_wrong_title_and_hidden_section() -> None:
    scraper = ArizonaScraper("AZ", "Arizona")
    wrong_title = REPEALED_HTML.replace(b"Title 2", b"Title 3")
    section_present = REPEALED_HTML.replace(
        b"</body>",
        (
            b'<a class="stat" href="/ars/02/00001.htm">2-1</a>'
            b'<li class="colright">A surviving section</li></body>'
        ),
    )

    for receipt in (
        _receipt(final_url="https://example.invalid/arsDetail/?title=2"),
        _receipt(wrong_title),
        _receipt(section_present),
    ):
        assert (
            scraper._official_repealed_title_exclusion(
                code_name="Arizona Revised Statutes Title 2",
                code_url=TITLE_2_URL,
                receipt=receipt,
            )
            is None
        )


def test_full_scrape_counts_repealed_title_without_indexing_a_tombstone(
    monkeypatch,
) -> None:
    scraper = ArizonaScraper("AZ", "Arizona")
    title_1_url = "https://www.azleg.gov/arsDetail/?title=1"
    checkpoints: list[tuple[list[NormalizedStatute], dict[str, object]]] = []

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "get_code_list",
        lambda: [
            {"name": "Arizona Revised Statutes Title 1", "url": title_1_url},
            {"name": "Arizona Revised Statutes Title 2", "url": TITLE_2_URL},
        ],
    )

    async def _links(url: str):
        return (
            [("https://www.azleg.gov/ars/01/00101.htm", "1-101", "Definitions")]
            if url == title_1_url
            else []
        )

    async def _build(**_kwargs):
        return NormalizedStatute(
            state_code="AZ",
            state_name="Arizona",
            statute_id="AZ-1-101",
            section_number="1-101",
            section_name="Definitions",
            full_text="1-101. Definitions. This is current enacted statutory text.",
            source_url="https://www.azleg.gov/ars/01/00101.htm",
        )

    async def _fresh(url: str, timeout_seconds: int = 12):
        assert url == TITLE_2_URL
        assert timeout_seconds == 12
        return _receipt()

    monkeypatch.setattr(scraper, "_discover_section_links", _links)
    monkeypatch.setattr(scraper, "_build_statute_from_section_page", _build)
    monkeypatch.setattr(scraper, "_fetch_fresh_official_title_receipt", _fresh)
    monkeypatch.setattr(scraper, "_is_low_quality_statute_record", lambda _row: False)
    monkeypatch.setattr(scraper, "_enrich_statute_structure", lambda row: row)
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda rows, **kwargs: checkpoints.append((list(rows), kwargs)) or True,
    )

    rows = asyncio.run(
        scraper.scrape_all(rate_limit_delay=0.0, hydrate_statute_text=False)
    )

    assert [row.statute_id for row in rows] == ["AZ-1-101"]
    assert not any(row.statute_id == "AZ-TITLE-2-REPEALED" for row in rows)
    assert any(item[1]["stage_label"] == "scrape_all:excluded:2" for item in checkpoints)
    complete = checkpoints[-1][1]
    assert complete["stage_label"] == "scrape_all:complete"
    assert complete["extra"]["codes_completed"] == 2
    assert complete["extra"]["closed_code_exclusions"][0]["title_number"] == "2"
