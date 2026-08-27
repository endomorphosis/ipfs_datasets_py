"""LCR-094: Louisiana exact Law.aspx leaf residual closure.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded residual and the production contracts that forbid Hub mutation,
static lists, per-page archive loops, and invented later Law.aspx targets.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    canonical_json_bytes,
)
from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawRetainedReplayOnlyError,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import (
    LouisianaScraper,
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
    / "louisiana_residual_closure_v1.md"
)

TOC_INPUTS = 55
TOC_ROOT_GETS = 1
TOC_TITLE_POSTBACKS = 54
RAW_LAW_ANCHORS = 92726
UNIQUE_LEAVES = 46363
RETAINED_LEAVES = 24832
RETAINED_OPERATIVE = 20681
RETAINED_TYPED_TERMINALS = 4151
RESIDUAL_COUNT = 21531
RESIDUAL_WAVE_NAME = "source-ordered-law-aspx-residuals"
RESIDUAL_SHA256_PREFIX = "source_derived_after_aspnet_toc_replay"
OFFICIAL_ENTRY = (
    "https://legis.la.gov/legis/Laws_Toc.aspx?folder=75&level=Parent"
)
OFFICIAL_LAW_LOCATOR = "https://legis.la.gov/legis/Law.aspx?d="
INVENTED_LAW_URL = "https://legis.la.gov/legis/Law.aspx?d=999999"
BOUNDED_LIVE_SEED_IDS = ("100114", "100115")
DIAGNOSTIC_PRODUCER_PREFIX = "LouisianaScraper@sha256:51663b23"


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


def _source_ordered_law_aspx_residual(
    unique_toc_urls: list[str],
    retained_leaf_urls: set[str],
) -> list[str]:
    residual: list[str] = []
    seen: set[str] = set()
    for url in unique_toc_urls:
        if url in retained_leaf_urls:
            continue
        if url in seen:
            raise AssertionError(
                "Louisiana Law.aspx residual frontier repeated a URL"
            )
        seen.add(url)
        residual.append(url)
    return residual


def _law_payload(url: str, *, terminal: bool = False) -> bytes:
    document_id = url.rsplit("=", 1)[-1]
    section_number = f"1:{document_id}"
    if terminal:
        body = f"<p>&sect;{section_number}. Repealed.</p>"
    else:
        text = (
            "Official Louisiana statutory text for this public-law provision. "
            * 12
        )
        body = (
            f"<div id='WPMainDoc'><p>&sect;{section_number}. Official "
            f"provision.</p><p>{text}</p></div>"
        )
    return (
        f"<form id='aspnetForm' action='./Law.aspx?d={document_id}'>"
        "<input id='ctl00_PageBody_ButtonPrevious' />"
        f"<span id='ctl00_PageBody_LabelName'>RS {section_number}</span>"
        "<input id='ctl00_PageBody_ButtonNext' />"
        f"<a id='ctl00_PageBody_linkPrint' href='LawPrint.aspx?d={document_id}'>"
        "Print</a>"
        f"<input id='ctl00_PageBody_HiddenDocId' value='{document_id}' />"
        f"<span id='ctl00_PageBody_LabelDocument'>{body}</span>"
        "</form>"
    ).encode()


def _toc_root_html(targets: list[str]) -> bytes:
    anchors = "".join(
        f"<a href=\"javascript:__doPostBack(&#39;{target}&#39;,&#39;&#39;)\">"
        f"Title {index}</a>"
        for index, target in enumerate(targets, start=1)
    )
    return (
        "<input name='__VIEWSTATE' value='retained-view-state' />" + anchors
    ).encode()


def _toc_title_html(document_ids: list[str], *, duplicate_block: bool) -> bytes:
    anchors = "".join(
        f"<a href='Law.aspx?d={document_id}'>RS 1:{document_id}</a>"
        for document_id in document_ids
    )
    duplicate = (
        "<div class='parallel-presentation'>" + anchors + "</div>"
        if duplicate_block
        else ""
    )
    return (anchors + duplicate).encode()


def _frontier_result(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    receipts = []
    envelopes = []
    retrieved_at = "2026-08-27T12:00:00Z"
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
        stats={
            "network_requested_pages": 0,
            "direct_initial_successes": len(urls),
            "per_page_archive_fallback_disabled": True,
            "common_crawl": {
                "range_fetch_calls": 1,
                "naive_range_fetches": len(urls),
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


class _LouisianaRetainedLedger:
    def __init__(
        self,
        inputs: list[tuple[str, Mapping[str, Any], bytes, Mapping[str, Any]]],
    ) -> None:
        self.refresh_calls = 0
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self._retained: dict[tuple[str, bytes], Any] = {}
        self.entries: list[Any] = []
        for endpoint, request, body, pagination in inputs:
            content = SimpleNamespace(sha256=hashlib.sha256(body).hexdigest())
            receipt = SimpleNamespace(
                content=content,
                endpoint=endpoint,
                pagination=dict(pagination),
                sanitized_request=dict(request),
            )
            retained = SimpleNamespace(
                envelope=SimpleNamespace(body=body),
                receipt=receipt,
                transport_receipt={
                    "content_sha256": content.sha256,
                    "official_url": endpoint,
                    "source_transport": "direct",
                },
            )
            key = (endpoint, canonical_json_bytes(dict(request)))
            self._retained[key] = retained
            self.entries.append(retained)

    def refresh_existing_entries(self) -> int:
        self.refresh_calls += 1
        return 0

    def replay_retained_parser_input(
        self,
        *,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> Any:
        request = dict(sanitized_request)
        self.requests.append((official_url, request))
        return self._retained.get(
            (official_url, canonical_json_bytes(request))
        )


def _compact_toc_ledger(
    *,
    document_ids: list[str],
    retained_leaf_ids: set[str],
    include_invented_leaf: bool = False,
) -> tuple[_LouisianaRetainedLedger, list[str], set[str]]:
    toc_url = OFFICIAL_ENTRY
    target = "ctl00$PageBody$ListViewTOC1$ctrl0$LinkButton1a"
    unique_urls = [f"{OFFICIAL_LAW_LOCATOR}{document_id}" for document_id in document_ids]
    retained_leaf_urls = {
        f"{OFFICIAL_LAW_LOCATOR}{document_id}" for document_id in retained_leaf_ids
    }
    get_request = {"method": "GET", "url": toc_url}
    post_request = {
        "method": "POST",
        "request_body_sha256": "b" * 64,
        "url": toc_url,
    }
    inputs: list[tuple[str, Mapping[str, Any], bytes, Mapping[str, Any]]] = [
        (
            toc_url,
            get_request,
            _toc_root_html([target]),
            {"kind": "aspnet_toc", "step": "root"},
        ),
        (
            toc_url,
            post_request,
            _toc_title_html(document_ids, duplicate_block=True),
            {"kind": "aspnet_postback", "page_count": 1, "page_index": 1},
        ),
    ]
    for url in unique_urls:
        document_id = url.rsplit("=", 1)[-1]
        if document_id not in retained_leaf_ids:
            continue
        inputs.append(
            (
                url,
                {"method": "GET", "url": url},
                _law_payload(url),
                {},
            )
        )
    if include_invented_leaf:
        inputs.append(
            (
                INVENTED_LAW_URL,
                {"method": "GET", "url": INVENTED_LAW_URL},
                _law_payload(INVENTED_LAW_URL),
                {},
            )
        )
    return _LouisianaRetainedLedger(inputs), unique_urls, retained_leaf_urls


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("Louisiana residual closure report is empty")
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


def test_louisiana_residual_closure_report_records_exact_leaf_residual() -> None:
    report = _report_text()
    table = _report_table(report)

    assert table["jurisdiction"] == "LA"
    assert table["official domain"] == "legis.la.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_law_locator"] == OFFICIAL_LAW_LOCATOR
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == "ASP.NET retained parser"
    assert table["same_target_parser_for_live_and_replay"] == "true"
    assert table["invent_later_law_aspx_targets"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["toc_inputs"] == str(TOC_INPUTS)
    assert table["toc_root_gets"] == str(TOC_ROOT_GETS)
    assert table["toc_title_postbacks"] == str(TOC_TITLE_POSTBACKS)
    assert table["raw_law_anchors"] == str(RAW_LAW_ANCHORS)
    assert table["unique_leaves"] == str(UNIQUE_LEAVES)
    assert table["retained_leaves"] == str(RETAINED_LEAVES)
    assert table["retained_operative"] == str(RETAINED_OPERATIVE)
    assert table["retained_typed_terminals"] == str(RETAINED_TYPED_TERMINALS)
    assert table["residual_count"] == str(RESIDUAL_COUNT)
    assert table["residual_kind"] == "unique ordered Law.aspx leaves"
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["leaf_acquisition_wave_count"] == "1"
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert (
        table["residual_sha_method"]
        == 'sha256(json.dumps(urls, ensure_ascii=False, separators=(",", ":")))'
    )
    assert table["diagnostic_producer"].startswith(DIAGNOSTIC_PRODUCER_PREFIX)
    assert int(table["toc_root_gets"]) + int(table["toc_title_postbacks"]) == TOC_INPUTS
    assert RETAINED_OPERATIVE + RETAINED_TYPED_TERMINALS == RETAINED_LEAVES
    assert RETAINED_LEAVES + RESIDUAL_COUNT == UNIQUE_LEAVES

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "asp.net" in lowered
    assert "invent" in lowered and "law.aspx" in lowered
    assert "hub mutation" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "21,531" in report
    assert "46,363" in report
    assert "24,832" in report
    assert "92,726" in report
    assert OFFICIAL_ENTRY in report
    assert report.count("Law.aspx?d=") < 12
    assert INVENTED_LAW_URL not in report
    assert not re.search(r"residual_ordered_sha256_prefix.*[0-9a-f]{12}", report)


def test_louisiana_aspnet_parser_is_the_only_leaf_source() -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    assert scraper.get_base_url() == "https://legis.la.gov"
    assert scraper._official_law_url("1001") == (
        "https://legis.la.gov/Legis/Law.aspx?d=1001"
    )
    assert scraper._LAW_LINK_RE.search("Law.aspx?d=1001")
    assert not scraper._LAW_LINK_RE.search("Laws_Toc.aspx?folder=75")

    live_source = inspect.getsource(LouisianaScraper._discover_live_toc_title_pages)
    retained_source = inspect.getsource(
        LouisianaScraper._retained_louisiana_toc_reports
    )
    fetch_source = inspect.getsource(LouisianaScraper._fetch_louisiana_law_frontier)
    assert "_title_postback_targets" in live_source
    assert "_title_postback_targets" in retained_source
    assert "first source-order occurrence" in retained_source
    assert "_LAW_LINK_RE.search" in live_source
    assert "_LAW_LINK_RE.search" in retained_source
    assert "Acquire the complete ordered Law.aspx frontier as one plural wave" in (
        fetch_source
    )
    assert not re.search(r"\binvent(?:ed|ing|s)?\b", fetch_source, flags=re.I)

    postback_source = inspect.getsource(LouisianaScraper)
    assert "_TOC_TITLE_POSTBACK_RE" in inspect.getsource(
        LouisianaScraper._title_postback_targets
    )
    assert "javascript:" in postback_source
    assert "LinkButton1a" in postback_source


def test_louisiana_adapter_has_no_static_residual_url_list() -> None:
    adapter = inspect.getsource(LouisianaScraper)
    fetch_source = inspect.getsource(LouisianaScraper._fetch_louisiana_law_frontier)
    scrape_source = inspect.getsource(LouisianaScraper.scrape_code)
    assert str(RESIDUAL_COUNT) not in adapter
    assert str(UNIQUE_LEAVES) not in adapter
    assert str(RETAINED_LEAVES) not in adapter
    assert RESIDUAL_SHA256_PREFIX not in adapter
    assert INVENTED_LAW_URL not in adapter
    assert "_ARCHIVE_LAW_URLS" not in fetch_source
    assert "_discover_archived_law_urls" not in fetch_source
    assert "return []" in scrape_source
    literal_ids = set(re.findall(r"Law\.aspx\?d=(\d+)", adapter, flags=re.I))
    assert literal_ids <= set(BOUNDED_LIVE_SEED_IDS) | {
        "100117",
        "100122",
        "100124",
        "100148",
    }
    assert "999999" not in literal_ids
    assert adapter.count("https://legis.la.gov") < 20


def test_louisiana_residual_sha256_uses_canonical_json_of_ordered_urls() -> None:
    compact = [
        f"{OFFICIAL_LAW_LOCATOR}1002",
        f"{OFFICIAL_LAW_LOCATOR}1003",
    ]
    compact_digest = _canonical_residual_sha256(compact)
    assert compact_digest == hashlib.sha256(
        b'["https://legis.la.gov/legis/Law.aspx?d=1002",'
        b'"https://legis.la.gov/legis/Law.aspx?d=1003"]'
    ).hexdigest()
    assert len(compact_digest) == 64
    assert compact_digest != RESIDUAL_SHA256_PREFIX
    report = _report_text()
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report


def test_louisiana_one_global_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(LouisianaScraper._fetch_louisiana_law_frontier)
    assert "repeat_grouped_archive_inventory_on_residual=False" in fetch_source
    assert 'common_crawl_domain_terms=("legis.la.gov",)' in fetch_source
    assert 'common_crawl_url_terms=("/legis/Law.aspx",)' in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "archive.is" not in fetch_source.casefold()

    retry_source = inspect.getsource(
        LouisianaScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in retry_source
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        LouisianaScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"residual_only_retries": True' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"wayback_prefix_inventory": True' in closure_source
    assert '"repeat_grouped_archive_inventory_on_residual": False' in closure_source
    assert '"leaf_acquisition_wave_count"' in closure_source


def test_louisiana_seed_and_host_replay_forbid_hub_docker_and_invented_targets(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "LA",
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
    assert "docker-copying" in report or "docker-copy" in report
    assert "invent" in report and "law.aspx" in report


def test_louisiana_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    louisiana_source = inspect.getsource(
        LouisianaScraper.produce_state_law_frontier_closure
    )
    assert "public_law_no_state_copyright" in louisiana_source or (
        "rights" in closure_source.casefold()
    )
    assert "retained_replay_network_requests" in louisiana_source
    assert louisiana_source.index('"retained_replay_network_requests": 0') > 0
    assert "Louisiana retained TOC law membership changed on replay" in (
        louisiana_source
    )


def test_louisiana_compact_toc_recipe_emits_source_derived_residual_not_invented_targets() -> None:
    ledger, unique_urls, retained_leaf_urls = _compact_toc_ledger(
        document_ids=["1001", "1002", "1003"],
        retained_leaf_ids={"1001"},
    )
    scraper = LouisianaScraper("LA", "Louisiana")
    scraper._state_law_acquisition_ledger = ledger

    toc_reports, toc_urls = scraper._retained_louisiana_toc_reports()
    assert toc_urls == unique_urls
    assert [row["page_index"] for row in toc_reports] == [0, 1]
    assert toc_reports[0]["method"] == "GET"
    assert toc_reports[1]["method"] == "POST"
    assert toc_reports[1]["law_member_count"] == 3

    residual = _source_ordered_law_aspx_residual(toc_urls, retained_leaf_urls)
    assert residual == [
        f"{OFFICIAL_LAW_LOCATOR}1002",
        f"{OFFICIAL_LAW_LOCATOR}1003",
    ]
    assert INVENTED_LAW_URL not in residual
    assert f"{OFFICIAL_LAW_LOCATOR}1001" not in residual
    assert len(toc_urls) == len(retained_leaf_urls) + len(residual)
    digest = _canonical_residual_sha256(residual)
    assert digest.startswith(RESIDUAL_SHA256_PREFIX) is False
    assert scraper._LAW_LINK_RE.search(residual[0])
    assert scraper._official_law_url("999999") != residual[0]


def test_louisiana_invented_later_law_aspx_target_fails_closed_on_toc_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, unique_urls, _retained = _compact_toc_ledger(
        document_ids=["1001", "1002"],
        retained_leaf_ids={"1001"},
    )
    scraper = LouisianaScraper("LA", "Louisiana")
    scraper._state_law_acquisition_ledger = ledger
    invented_union = [*unique_urls, INVENTED_LAW_URL]
    payloads = {
        unique_urls[0]: _law_payload(unique_urls[0]),
        unique_urls[1]: _law_payload(unique_urls[1]),
        INVENTED_LAW_URL: _law_payload(INVENTED_LAW_URL),
    }

    async def _batch(urls, *, max_concurrency: int):
        requested = list(urls)
        assert INVENTED_LAW_URL in requested
        return _frontier_result(
            requested, [payloads[url] for url in requested]
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_louisiana_law_frontier", _batch)
    monkeypatch.setattr(
        scraper, "_write_partial_checkpoint", lambda *args, **kwargs: True
    )

    with pytest.raises(
        RuntimeError,
        match="Louisiana retained TOC membership changed before closure",
    ):
        asyncio.run(
            scraper._scrape_law_page_urls(
                code_name="Louisiana Revised Statutes",
                law_urls=invented_union,
                max_statutes=None,
            )
        )


def test_louisiana_complete_unique_union_is_one_plural_wave_with_residual_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, unique_urls, retained_leaf_urls = _compact_toc_ledger(
        document_ids=["1001", "1002", "1003"],
        retained_leaf_ids={"1001"},
    )
    residual = _source_ordered_law_aspx_residual(unique_urls, retained_leaf_urls)
    scraper = LouisianaScraper("LA", "Louisiana")
    scraper._state_law_acquisition_ledger = ledger
    batch_calls: list[list[str]] = []
    payloads = {url: _law_payload(url) for url in unique_urls}

    async def _batch(urls, *, max_concurrency: int):
        requested = list(urls)
        batch_calls.append(requested)
        return _frontier_result(
            requested, [payloads[url] for url in requested]
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_fetch_louisiana_law_frontier", _batch)
    monkeypatch.setattr(
        scraper, "_write_partial_checkpoint", lambda *args, **kwargs: True
    )

    rows = asyncio.run(
        scraper._scrape_law_page_urls(
            code_name="Louisiana Revised Statutes",
            law_urls=unique_urls,
            max_statutes=None,
        )
    )

    assert batch_calls == [unique_urls]
    assert INVENTED_LAW_URL not in batch_calls[0]
    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["leaf_acquisition_wave_count"] == 1
    assert frontier["frontier_batches"] == 1
    assert frontier["law_pages_requested"] == len(unique_urls)
    assert [row.source_url for row in rows] == unique_urls
    assert residual == unique_urls[1:]
    assert frontier["boundary_first"] == unique_urls[0]
    assert frontier["boundary_last"] == unique_urls[-1]


def test_louisiana_retained_replay_only_miss_does_not_invent_law_aspx_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ReplayOnly(_LouisianaRetainedLedger):
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

    toc_url = OFFICIAL_ENTRY
    unique_urls = [
        f"{OFFICIAL_LAW_LOCATOR}1001",
        f"{OFFICIAL_LAW_LOCATOR}1002",
    ]
    target = "ctl00$PageBody$ListViewTOC1$ctrl0$LinkButton1a"
    ledger = _ReplayOnly(
        [
            (
                toc_url,
                {"method": "GET", "url": toc_url},
                _toc_root_html([target]),
                {"kind": "aspnet_toc", "step": "root"},
            ),
            (
                toc_url,
                {
                    "method": "POST",
                    "request_body_sha256": "b" * 64,
                    "url": toc_url,
                },
                _toc_title_html(["1001", "1002"], duplicate_block=True),
                {"kind": "aspnet_postback", "page_count": 1, "page_index": 1},
            ),
            (
                unique_urls[0],
                {"method": "GET", "url": unique_urls[0]},
                _law_payload(unique_urls[0]),
                {},
            ),
        ]
    )
    scraper = LouisianaScraper("LA", "Louisiana")
    scraper._state_law_acquisition_ledger = ledger
    fetch_calls: list[list[str]] = []

    async def _batch(self, urls, *, max_concurrency: int):
        requested = list(urls)
        fetch_calls.append(requested)
        assert requested == unique_urls
        assert INVENTED_LAW_URL not in requested
        return _frontier_result(
            requested, [_law_payload(url) for url in requested]
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(LouisianaScraper, "_fetch_louisiana_law_frontier", _batch)
    monkeypatch.setattr(
        scraper, "_write_partial_checkpoint", lambda *args, **kwargs: True
    )

    rows = asyncio.run(
        scraper._scrape_law_page_urls(
            code_name="Louisiana Revised Statutes",
            law_urls=unique_urls,
            max_statutes=None,
        )
    )

    assert fetch_calls == [unique_urls]
    assert [row.source_url for row in rows] == unique_urls
    _, toc_urls = scraper._retained_louisiana_toc_reports()
    residual = _source_ordered_law_aspx_residual(toc_urls, {unique_urls[0]})
    assert residual == [unique_urls[1]]
    assert INVENTED_LAW_URL not in residual
    assert scraper._last_louisiana_full_frontier["leaf_acquisition_wave_count"] == 1
