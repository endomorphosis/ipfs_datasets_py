"""LCR-092: Missouri strict v13 OneSection residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, v4 wholesale seeding, and an inferred
§ 70.655 locator.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawRetainedReplayOnlyError,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri import (
    MissouriScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.missouri_chapter import (
    section_body_identity,
    section_page_identity,
    section_url,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    IsolatedRetainedReplayWorkerError,
    build_host_retained_replay_command,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.strict_frontier_closure import (
    retain_exact_state_frontier_closure,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "missouri_residual_closure_v1.md"
)

RESIDUAL_COUNT = 26587
V13_UNIQUE_INPUTS = 4056
CURRENT_OPERATIVE_IDENTITIES = 30170
RESIDUAL_SHA256_PREFIX = "49187bc62944"
FIRST_SECTION = "70.655"
LAST_SECTION = "701.550"
FIRST_RESIDUAL_URL = (
    "https://revisor.mo.gov/main/OneSection.aspx?section=70.655"
)
LAST_RESIDUAL_URL = (
    "https://revisor.mo.gov/main/OneSection.aspx?section=701.550"
)
PAGE_SELECT_70_655 = (
    "https://revisor.mo.gov/main/PageSelect.aspx?section=70.655&bid=57378&hl="
)
RESIDUAL_WAVE_NAME = "source-ordered-one-section-residuals"


def _receipt_sha256(url: str, content_sha256: str, retrieved_at: str) -> str:
    return hashlib.sha256(
        f"{url}\n{content_sha256}\n{retrieved_at}".encode()
    ).hexdigest()


def _canonical_residual_sha256(urls: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(urls, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _section_html(section: str) -> bytes:
    return (
        "<html><body><div id='TOP'></div><div><div><div class='norm'>"
        f"<p class='norm'>{section}. "
        + ("Official Missouri statutory text. " * 12)
        + "</p><div class='foot'>---- (L. 2025 H.B. 1)</div>"
        "</div></div></div><div id='BOTTOM'></div></body></html>"
    ).encode()


def _page_select_identity_mismatch_html(
    requested_section: str,
    bid: str,
    observed_section: str,
) -> bytes:
    source_bound_head = (
        "<html><head><title>Missouri Revisor of Statutes - Revised Statutes "
        f"of Missouri, RSMo Section {requested_section}</title>"
        f"<meta property='og:title' content='{requested_section}'>"
        "<meta property='og:url' content='https://revisor.mo.gov/main/"
        f"OneSection.aspx?section={requested_section}&amp;bid={bid}'></head><body>"
    ).encode()
    return _section_html(observed_section).replace(
        b"<html><body>",
        source_bound_head,
        1,
    )


def _chapter_html(chapter: str, rows: list[tuple[str, str, str, str]]) -> bytes:
    table_rows = "".join(
        "<tr>"
        "<td><a href='/main/PageSelect.aspx?section="
        f"{section}&amp;bid={bid}&amp;hl='>{section}</a></td>"
        f"<td>{title} ({effective})</td>"
        "</tr>"
        for section, bid, title, effective in rows
    )
    return (
        "<html><head><title>Missouri Revisor of Statutes - Revised Statutes "
        f"of Missouri, RSMo Chapter {chapter}</title></head><body>"
        f"<div class='lr-font-norm'>Chapter {chapter} Official title</div>"
        f"<table>{table_rows}</table></body></html>"
    ).encode()


def _frontier_result(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    receipts = []
    envelopes = []
    retrieved_at = "2026-08-25T12:00:00Z"
    for url, payload in zip(urls, payloads, strict=True):
        content_sha256 = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": content_sha256,
            "official_url": url,
            "source_transport": "direct",
        }
        receipts.append(dict(transport))
        envelopes.append(
            {
                "acquisition": {
                    "receipt": {
                        "endpoint": url,
                        "content": {"sha256": content_sha256},
                        "metadata": {"transport_receipt": dict(transport)},
                        "receipt_sha256": _receipt_sha256(
                            url, content_sha256, retrieved_at
                        ),
                        "retrieved_at": retrieved_at,
                    }
                }
            }
        )
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=[None] * len(urls),
        transport_receipts=receipts,
        parser_input_envelopes=envelopes,
        stats={"network_requested_pages": 0, "per_page_archive_fallback_disabled": True},
    )


class _MissouriRetainedLedger:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = dict(pages)
        self.refresh_calls = 0
        self.requests: list[str] = []

    def refresh_existing_entries(self) -> None:
        self.refresh_calls += 1

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        assert dict(sanitized_request) == {"method": "GET", "url": official_url}
        self.requests.append(official_url)
        payload = self.pages.get(official_url)
        if payload is None:
            return None
        digest = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": digest,
            "official_url": official_url,
            "source_transport": "direct",
        }
        receipt_mapping = {
            "content": {"sha256": digest},
            "endpoint": official_url,
            "metadata": {"transport_receipt": dict(transport)},
            "receipt_sha256": _receipt_sha256(
                official_url,
                digest,
                "2026-08-25T12:00:00Z",
            ),
            "retrieved_at": "2026-08-25T12:00:00Z",
        }
        envelope_mapping = {"acquisition": {"receipt": receipt_mapping}}
        envelope = SimpleNamespace(
            body=payload,
            to_dict=lambda: envelope_mapping,
        )
        return SimpleNamespace(
            envelope=envelope,
            receipt=SimpleNamespace(content=SimpleNamespace(sha256=digest)),
            transport_receipt=transport,
        )


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Missouri residual closure report is empty")
    return payload


def _report_table(report: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        field, value = cells
        if field in {"Field", "---"} or set(field) == {"-"}:
            continue
        rows[field] = value.strip("`")
    return rows


def test_missouri_residual_closure_report_records_exact_onesection_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "MO"
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["seed"] == "strict v13 only"
    assert table["v4_wholesale_seed"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["inferred_section_70_655_locator"] == "forbidden"
    assert table["v13_unique_inputs"] == str(V13_UNIQUE_INPUTS)
    assert table["v13_home_pages"] == "1"
    assert table["v13_chapter_catalogs"] == "468"
    assert table["v13_pageselect_pages"] == "3584"
    assert table["v13_onesection_fallbacks"] == "3"
    assert table["current_operative_identities"] == str(
        CURRENT_OPERATIVE_IDENTITIES
    )
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == "unique ordered OneSection URLs"
    assert table["residual_first_section"] == FIRST_SECTION
    assert table["residual_last_section"] == LAST_SECTION
    assert table["residual_first_url"] == FIRST_RESIDUAL_URL
    assert table["residual_last_url"] == LAST_RESIDUAL_URL
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["one_section_plural_wave_count"] == "1"
    assert table["per_page_archive_loop"] == "false"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )

    assert int(table["v13_home_pages"]) + int(table["v13_chapter_catalogs"]) + int(
        table["v13_pageselect_pages"]
    ) + int(table["v13_onesection_fallbacks"]) == V13_UNIQUE_INPUTS
    assert 3580 + 3 + RESIDUAL_COUNT == CURRENT_OPERATIVE_IDENTITIES

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "seed only strict v13" in lowered
    assert "do not seed v4 wholesale" in lowered
    assert "hub mutation" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert FIRST_RESIDUAL_URL in report
    assert LAST_RESIDUAL_URL in report
    assert RESIDUAL_SHA256_PREFIX in report
    assert "26,587" in report
    assert report.count("https://revisor.mo.gov/main/OneSection.aspx?section=") < 12


def test_missouri_onesection_locator_is_exact_and_not_inferred() -> None:
    assert section_url(FIRST_SECTION) == FIRST_RESIDUAL_URL
    assert section_url(LAST_SECTION) == LAST_RESIDUAL_URL
    assert section_url("70.631") != FIRST_RESIDUAL_URL

    mismatch = _page_select_identity_mismatch_html(
        FIRST_SECTION,
        "57378",
        "70.631",
    ).decode()
    assert section_page_identity(mismatch) == FIRST_SECTION
    assert section_body_identity(mismatch) == "70.631"

    unbounded = inspect.getsource(MissouriScraper._scrape_unbounded_missouri_frontier)
    assert "section_url(section_number)" in unbounded
    assert "official_page_select_body_identity_mismatch" in unbounded
    assert PAGE_SELECT_70_655 not in unbounded
    assert "70.631" not in unbounded
    assert re.search(
        r"OneSection\.aspx\?section=\{[^}]+\}",
        inspect.getsource(section_url),
    )


def test_missouri_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    unbounded = inspect.getsource(MissouriScraper._scrape_unbounded_missouri_frontier)
    assert '"residual_one_section_sha256"' in unbounded
    assert "json.dumps(" in unbounded
    assert 'ensure_ascii=False' in unbounded
    assert 'separators=(",", ":")' in unbounded
    assert "Missouri OneSection residual frontier repeated a URL" in unbounded
    assert '"source_ordered": True' in unbounded
    assert '"per_page_archive_loop": False' in unbounded
    assert f'frontier_name="{RESIDUAL_WAVE_NAME}"' in unbounded

    compact = [FIRST_RESIDUAL_URL, LAST_RESIDUAL_URL]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://revisor.mo.gov/main/OneSection.aspx?section=70.655",'
        b'"https://revisor.mo.gov/main/OneSection.aspx?section=701.550"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert not compact_digest.startswith(RESIDUAL_SHA256_PREFIX)


def test_missouri_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(MissouriScraper)
    unbounded = inspect.getsource(MissouriScraper._scrape_unbounded_missouri_frontier)
    scrape = inspect.getsource(MissouriScraper._custom_scrape_missouri)
    assert "OFFICIAL_NUMERIC_CHAPTERS" not in unbounded
    assert "official_chapter_catalog" not in unbounded
    assert "_missouri_home_chapter_urls" in scrape
    assert "chapter_urls = self._missouri_home_chapter_urls(home_bytes)" in scrape
    assert adapter.count("https://revisor.mo.gov/main/OneSection.aspx?section=") <= 3
    assert str(RESIDUAL_COUNT) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    onesection_literals = set(
        re.findall(
            r"OneSection\.aspx\?section=([0-9A-Za-z.\-]+)",
            adapter,
        )
    )
    assert FIRST_SECTION not in onesection_literals
    assert LAST_SECTION not in onesection_literals
    assert "70.631" not in onesection_literals


def test_missouri_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(MissouriScraper._fetch_missouri_frontier_batch)
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,)" in fetch_source
    assert 'common_crawl_url_terms=("/main/",)' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "repeat_grouped_archive_inventory_on_residual" not in fetch_source
    assert "archive.is" not in fetch_source.casefold()

    retry_source = inspect.getsource(
        MissouriScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        MissouriScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"residual_only_retries": True' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"wayback_prefix_inventory": True' in closure_source
    assert '"residual_one_section_sha256"' in closure_source


def test_missouri_seed_and_host_replay_forbid_hub_docker_and_v4_wholesale(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "MO",
            "--scrape",
            "--retained-replay-only",
            "--strict-acquisition-evidence",
            "--no-incremental-state-publish",
        ],
        workdir=tmp_path,
    )
    joined = " ".join(command)
    assert "docker" not in command
    assert "--network" not in command
    assert "--publish-to-hf" not in command
    assert "--retained-replay-only" in command
    assert "--no-incremental-state-publish" in command
    assert "docker" not in joined.casefold()

    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="must not invoke docker",
    ):
        build_host_retained_replay_command(
            argv=["docker", "run", "--network", "none"],
            workdir=tmp_path,
        )

    report = " ".join(_report_text().casefold().split())
    assert "hub mutation" in report
    assert "do not seed v4 wholesale" in report
    assert "docker-copying" in report or "docker-copy" in report


def test_missouri_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    missouri_source = inspect.getsource(
        MissouriScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in missouri_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in missouri_source
    assert missouri_source.index('"retained_replay_network_requests": 0') > 0


def test_missouri_compact_70_655_mismatch_emits_exact_onesection_residual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = MissouriScraper.OFFICIAL_ENTRY_URL
    chapter_url = MissouriScraper("MO", "Missouri").official_chapter_url("70")
    batch_calls: list[tuple[str, list[str], bool]] = []

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        assert url == home_url
        return b"<a href='/main/OneChapter.aspx?chapter=70'>Chapter 70</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested, allow_residuals))
        if frontier_name == "chapter-index":
            return _frontier_result(
                requested,
                [
                    _chapter_html(
                        "70",
                        [
                            (
                                FIRST_SECTION,
                                "57378",
                                "Official current provision",
                                "8/28/2025",
                            )
                        ],
                    )
                ],
            )
        assert frontier_name == RESIDUAL_WAVE_NAME
        assert requested == [FIRST_RESIDUAL_URL]
        assert allow_residuals is False
        return _frontier_result(requested, [_section_html(FIRST_SECTION)])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )

    scraper = MissouriScraper("MO", "Missouri")
    scraper._state_law_acquisition_ledger = _MissouriRetainedLedger(
        {
            PAGE_SELECT_70_655: _page_select_identity_mismatch_html(
                FIRST_SECTION,
                "57378",
                "70.631",
            )
        }
    )
    rows = asyncio.run(
        scraper._custom_scrape_missouri(
            "Missouri Revised Statutes",
            home_url,
            "Mo. Rev. Stat.",
            max_sections=None,
        )
    )

    plan = scraper._last_missouri_section_acquisition_plan
    assert batch_calls == [
        ("chapter-index", [chapter_url], False),
        (RESIDUAL_WAVE_NAME, [FIRST_RESIDUAL_URL], False),
    ]
    assert [row.section_number for row in rows] == [FIRST_SECTION]
    assert rows[0].source_url == FIRST_RESIDUAL_URL
    assert rows[0].structured_data["source_frontier_record_url"] == PAGE_SELECT_70_655
    assert rows[0].structured_data["source_identity_fallback_reason"] == (
        "official_page_select_body_identity_mismatch"
    )
    assert plan["residual_one_section_count"] == 1
    assert plan["one_section_plural_wave_count"] == 1
    assert plan["per_page_archive_loop"] is False
    assert plan["source_ordered"] is True
    assert plan["residual_urls_unique"] is True
    assert plan["residual_one_section_sha256"] == _canonical_residual_sha256(
        [FIRST_RESIDUAL_URL]
    )
    assert plan["residual_one_section_sha256"].startswith(RESIDUAL_SHA256_PREFIX) is False


def test_missouri_retained_replay_only_miss_does_not_invent_pageselect_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_url = MissouriScraper.OFFICIAL_ENTRY_URL
    chapter_url = MissouriScraper("MO", "Missouri").official_chapter_url("701")
    batch_calls: list[tuple[str, list[str]]] = []

    class _ReplayOnly(_MissouriRetainedLedger):
        retained_replay_only = True

        def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
            retained = super().replay_retained_parser_input(
                official_url=official_url,
                sanitized_request=sanitized_request,
            )
            if retained is None:
                raise StateLawRetainedReplayOnlyError(
                    f"retained-replay-only ledger miss: {official_url}"
                )
            return retained

    async def _single(self, url: str, timeout_seconds: int = 25) -> bytes:
        return b"<a href='/main/OneChapter.aspx?chapter=701'>Chapter 701</a>"

    async def _batch(
        self,
        urls,
        *,
        frontier_name: str,
        allow_residuals: bool = False,
    ):
        requested = list(urls)
        batch_calls.append((frontier_name, requested))
        if frontier_name == "chapter-index":
            return _frontier_result(
                requested,
                [
                    _chapter_html(
                        "701",
                        [
                            (
                                LAST_SECTION,
                                "9001",
                                "Last official current provision",
                                "8/28/2025",
                            )
                        ],
                    )
                ],
            )
        assert frontier_name == RESIDUAL_WAVE_NAME
        assert requested == [LAST_RESIDUAL_URL]
        return _frontier_result(requested, [_section_html(LAST_SECTION)])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        MissouriScraper,
        "_fetch_page_content_with_archival_fallback",
        _single,
    )
    monkeypatch.setattr(MissouriScraper, "_fetch_missouri_frontier_batch", _batch)
    monkeypatch.setattr(
        MissouriScraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: True,
    )

    scraper = MissouriScraper("MO", "Missouri")
    scraper._state_law_acquisition_ledger = _ReplayOnly({})
    rows = asyncio.run(
        scraper._custom_scrape_missouri(
            "Missouri Revised Statutes",
            home_url,
            "Mo. Rev. Stat.",
            max_sections=None,
        )
    )

    assert batch_calls == [
        ("chapter-index", [chapter_url]),
        (RESIDUAL_WAVE_NAME, [LAST_RESIDUAL_URL]),
    ]
    assert [row.source_url for row in rows] == [LAST_RESIDUAL_URL]
    plan = scraper._last_missouri_section_acquisition_plan
    assert plan["retained_page_select_count"] == 0
    assert plan["residual_one_section_count"] == 1
    assert scraper._last_missouri_full_frontier["section_acquisition_plan"][
        "residual_one_section_sha256"
    ] == _canonical_residual_sha256([LAST_RESIDUAL_URL])
