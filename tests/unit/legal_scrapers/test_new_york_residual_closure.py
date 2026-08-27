"""LCR-103: New York exact residual proofs and URLs.

The child task either seals a current-bundle pair after host zero-network
replay or records the exact remaining URL/proof residual. This module pins
the recorded 30-URL Senate wave plus 214 unresolved proof decisions and the
production contracts that forbid Hub mutation, static lists, per-page
archive loops, the legacy Senate section path, and converting unresolved
decisions into current law.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
    seed_retained_evidence_union,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    new_york_law_pdf as ny_pdf,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import (
    NewYorkScraper,
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
    / "new_york_residual_closure_v1.md"
)

OFFICIAL_DOMAIN = "www.nysenate.gov"
OFFICIAL_PDF_DOMAIN = "legislation.nysenate.gov"
OFFICIAL_ENTRY = "https://www.nysenate.gov/legislation/laws"
OFFICIAL_CONSOLIDATED = "https://www.nysenate.gov/legislation/laws/CONSOLIDATED"
AGM28_URL = (
    "https://agriculture.ny.gov/system/files/documents/2023/02/"
    "urbanruralconsumeraccessreport.pdf"
)
AGM28_SHA256 = "6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d"
AGM28_SELECTOR_KEY = "AGM:28"
CATALOG_LAW_COUNT = 94
SOURCE_SECTIONS = 37441
OPERATIVE_SECTIONS = 36475
TERMINAL_BEFORE_AGM = 751
TERMINAL_AFTER_AGM = 752
UNRESOLVED_BEFORE_AGM = 215
UNRESOLVED_AFTER_AGM = 214
CLOSED_LAWS_BEFORE_AGM = 68
CLOSED_LAWS_AFTER_AGM = 69
EVENT_ROWS_BEFORE_AGM = 183
EVENT_ROWS_AFTER_AGM = 182
MISSING_NOTE_ROWS = 4
TOC_BODY_ROWS = 28
SUPPLEMENTAL_RESIDUAL_ROWS = 32
EXTRA_TOC_VARIANTS = 7
ENUMERABLE_URL_RESIDUAL = 30
SEED_V20_DIRECT = 95
SEED_V21_AGM = 1
SEED_SELECTED = 96
SEED_PROJECTION_SHA256 = (
    "46dce4a3aecf32f3fe21dd743da8f958b1bec8bbc84f5ec680e49f2c13807f76"
)
V20_VERIFIED_BYTES = 75151982
CATALOG_CODE_SHA256 = (
    "792d08fe5168ff6b429d13076fa843a8e5987c4b670339e1a2c6ca70420d590c"
)
UNRESOLVED_SHA_BEFORE_AGM = (
    "4e8865cc8dbfe4706e0fbe931e31df60a4e4f7e20e88ee9f628507c354b22dc3"
)
UNRESOLVED_SHA_AFTER_AGM_PREFIX = "d6b209ac65ab"
RESIDUAL_SHA256 = (
    "30fb7bd969c80f3747b3ff0eae6685f11e61bdd82193b4abf35864a2c32a1ec2"
)
RESIDUAL_SHA256_PREFIX = "30fb7bd969c8"
SOURCE_BUNDLE = (
    "f68d2672e24092c93810dd0f168a098a855d7879bea746faa63f676ef3ccdd75"
)
SOURCE_BUNDLE_PREFIX = "f68d2672e240"
RESIDUAL_WAVE_NAME = "source-derived-supplemental-sections-1-30"
AGM28_WAVE_NAME = "agm-28-lifecycle-selector"
CATALOG_WAVE_NAME = "consolidated-catalog"
PDF_WAVE_PREFIX = "full-law-pdfs-"
FIRST_RESIDUAL_URL = "https://www.nysenate.gov/legislation/laws/EPT/3-6.5"
INVENTED_SENATE_URL = "https://www.nysenate.gov/legislation/laws/ZZZ/999.99"
PUBLIC_LAW_URL = "https://newyork.public.law/laws/n.y._penal_law_section_125.25"
INVENTED_AGENCY_PROOF_URL = (
    "https://dos.ny.gov/system/files/documents/2026/08/gmu-856-ceased.csv"
)
VARIANT_IDENTITIES = (
    ("EDN", "2023-b", "*2"),
    ("GMU", "371-a", "*2"),
    ("TAX", "1262-l", "*2"),
    ("VAT", "235", "*2"),
    ("VAT", "235", "*3"),
    ("VAT", "1180-i", "*5"),
    ("VAT", "1180-i", "*6"),
)


def _newline_residual_sha256(urls: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(urls).encode("utf-8")).hexdigest()


def _derived_supplemental_urls() -> list[str]:
    derived: list[str] = []
    for law_code, section, _variant, _reason in (
        NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS
    ):
        url = ny_pdf.public_section_url(str(law_code), str(section))
        if url not in derived:
            derived.append(url)
    return derived


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
) -> StateLawPageMultiFetchResult:
    requested = list(urls)
    bodies = list(payloads)
    aligned_errors = list(errors or [None] * len(requested))
    return StateLawPageMultiFetchResult(
        urls=requested,
        payloads=bodies,
        errors=aligned_errors,
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(body).hexdigest() if body else "",
                "source_transport": "direct",
            }
            for url, body in zip(requested, bodies, strict=True)
        ],
        parser_input_envelopes=[None] * len(requested),
        stats={
            "requested_pages": len(requested),
            "common_crawl": {
                "range_fetch_calls": 1 if len(requested) > 1 else 0,
                "range_fetches_avoided": max(0, len(requested) - 1),
            },
        },
    )


def _ordered_code_sha256(*codes: str) -> str:
    return hashlib.sha256(
        json.dumps(list(codes), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("New York residual closure report is empty")
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
        if field in {"Field", "---", "Step"} or set(field) == {"-"}:
            continue
        rows[field] = value.strip("`")
    return rows


def test_new_york_residual_closure_report_records_exact_thirty_url_and_proof_residual() -> None:
    report = _report_text()
    table = _report_table(report)
    supplemental_urls = list(NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)

    assert table["jurisdiction"] == "NY"
    assert table["official domain"] == OFFICIAL_DOMAIN
    assert table["official_pdf_domain"] == OFFICIAL_PDF_DOMAIN
    assert table["agm28_domain"] == "agriculture.ny.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_consolidated_url"] == OFFICIAL_CONSOLIDATED
    assert table["agm28_lifecycle_report_url"] == AGM28_URL
    assert table["agm28_lifecycle_report_sha256"] == AGM28_SHA256
    assert table["agm28_selector_key"] == AGM28_SELECTOR_KEY
    assert table["closure_status"] == "residual_recorded"
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["parser"] == (
        "official full-law PDF plus reviewed supplemental proof resolvers"
    )
    assert table["same_target_parser_for_live_and_replay"] == "true"
    assert table["seed"] == (
        "96-input v20-plus-AGM union; 95 v20 direct plus one v21 AGM Wayback"
    )
    assert table["seed_v20_direct_inputs"] == str(SEED_V20_DIRECT)
    assert table["seed_v21_agm_wayback_inputs"] == str(SEED_V21_AGM)
    assert table["seed_selected_input_count"] == str(SEED_SELECTED)
    assert table["seed_selected_projection_sha256"] == SEED_PROJECTION_SHA256
    assert table["seed_copied_file_count"] == "0"
    assert table["convert_unresolved_decisions_into_current_law"] == "forbidden"
    assert table["dynamic_resolver_registration"] == "forbidden"
    assert table["public_law_justia_fallback_in_strict"] == "forbidden"
    assert table["legacy_per_page_senate_section_path"] == "forbidden"
    assert table["invent_later_senate_section_urls"] == "forbidden"
    assert table["unbounded_locator_hunt"] == "forbidden"
    assert table["static_residual_list"] == "forbidden"
    assert table["v20_catalog_plus_pdf_inputs"] == str(SEED_V20_DIRECT)
    assert table["v20_verified_bytes"] == str(V20_VERIFIED_BYTES)
    assert table["catalog_law_count"] == str(CATALOG_LAW_COUNT)
    assert table["catalog_ordered_code_sha256"] == CATALOG_CODE_SHA256
    assert table["source_sections"] == str(SOURCE_SECTIONS)
    assert table["operative_sections"] == str(OPERATIVE_SECTIONS)
    assert table["terminal_sections_before_agm"] == str(TERMINAL_BEFORE_AGM)
    assert table["terminal_sections_after_agm"] == str(TERMINAL_AFTER_AGM)
    assert table["unresolved_before_agm"] == str(UNRESOLVED_BEFORE_AGM)
    assert table["unresolved_after_agm"] == str(UNRESOLVED_AFTER_AGM)
    assert table["closed_laws_before_agm"] == str(CLOSED_LAWS_BEFORE_AGM)
    assert table["closed_laws_after_agm"] == str(CLOSED_LAWS_AFTER_AGM)
    assert table["event_conditioned_rows_before_agm"] == str(EVENT_ROWS_BEFORE_AGM)
    assert table["event_conditioned_rows_after_agm"] == str(EVENT_ROWS_AFTER_AGM)
    assert table["missing_lifecycle_note_rows"] == str(MISSING_NOTE_ROWS)
    assert table["toc_body_rows"] == str(TOC_BODY_ROWS)
    assert table["supplemental_residual_rows"] == str(SUPPLEMENTAL_RESIDUAL_ROWS)
    assert table["extra_toc_variant_identities"] == str(EXTRA_TOC_VARIANTS)
    assert table["enumerable_url_residual_count"] == str(ENUMERABLE_URL_RESIDUAL)
    assert table["unresolved_decision_count"] == str(UNRESOLVED_AFTER_AGM)
    assert table["residual_count"] == str(ENUMERABLE_URL_RESIDUAL)
    assert table["residual_kind"] == (
        "exact 30-URL www.nysenate.gov wave plus 214 unresolved proof decisions"
    )
    assert table["residual_first_url"] == FIRST_RESIDUAL_URL
    assert table["residual_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["agm28_wave_name"] == AGM28_WAVE_NAME
    assert table["catalog_wave_name"] == CATALOG_WAVE_NAME
    assert table["pdf_wave_name_prefix"] == PDF_WAVE_PREFIX
    assert table["catalog_acquisition_wave_count"] == "1"
    assert table["agm28_acquisition_wave_count"] == (
        "0 remaining; already retained"
    )
    assert table["supplemental_acquisition_wave_count"] == "1"
    assert table["implemented_event_resolvers"] == "1"
    assert table["unimplemented_event_resolvers"] == str(EVENT_ROWS_AFTER_AGM)
    assert table["per_page_archive_loop"] == "false"
    assert table["grouped_warc_recovery"] == "true"
    assert table["wayback_prefix_inventory"] == "true"
    assert table["residual_only_retries"] == "true"
    assert table["archive_is"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0"
    assert table["rights_basis"] == "public_law_no_state_copyright"
    assert table["residual_sha_method"] == 'sha256("\\n".join(urls))'
    assert table["residual_ordered_sha256"] == RESIDUAL_SHA256
    assert table["residual_ordered_sha256_prefix"] == RESIDUAL_SHA256_PREFIX
    assert table["unresolved_projection_sha256_before_agm"] == (
        UNRESOLVED_SHA_BEFORE_AGM
    )
    assert table["unresolved_projection_sha256_after_agm_prefix"] == (
        UNRESOLVED_SHA_AFTER_AGM_PREFIX
    )
    assert table["diagnostic_hashes_authorizing"] == "false"
    assert table["source_bundle"] == SOURCE_BUNDLE
    assert table["source_bundle_prefix"] == SOURCE_BUNDLE_PREFIX

    assert SEED_V20_DIRECT + SEED_V21_AGM == SEED_SELECTED
    assert TERMINAL_BEFORE_AGM + 1 == TERMINAL_AFTER_AGM
    assert UNRESOLVED_BEFORE_AGM - 1 == UNRESOLVED_AFTER_AGM
    assert CLOSED_LAWS_BEFORE_AGM + 1 == CLOSED_LAWS_AFTER_AGM
    assert EVENT_ROWS_BEFORE_AGM - 1 == EVENT_ROWS_AFTER_AGM
    assert (
        MISSING_NOTE_ROWS + TOC_BODY_ROWS == SUPPLEMENTAL_RESIDUAL_ROWS
    )
    assert (
        EVENT_ROWS_AFTER_AGM + MISSING_NOTE_ROWS + TOC_BODY_ROWS
        == UNRESOLVED_AFTER_AGM
    )
    assert OPERATIVE_SECTIONS + TERMINAL_AFTER_AGM + UNRESOLVED_AFTER_AGM == (
        SOURCE_SECTIONS
    )
    assert SUPPLEMENTAL_RESIDUAL_ROWS - 2 == ENUMERABLE_URL_RESIDUAL
    assert len(supplemental_urls) == ENUMERABLE_URL_RESIDUAL
    assert supplemental_urls[0] == FIRST_RESIDUAL_URL
    assert _newline_residual_sha256(supplemental_urls) == RESIDUAL_SHA256
    assert RESIDUAL_SHA256.startswith(RESIDUAL_SHA256_PREFIX)
    assert SOURCE_BUNDLE.startswith(SOURCE_BUNDLE_PREFIX)

    lowered = " ".join(report.casefold().split())
    assert "typed residual recorded" in lowered
    assert "not a sealed current-bundle pair" in lowered.replace("*", "")
    assert "not a publication authorization" in lowered.replace("*", "")
    assert "hub mutation" in lowered
    assert "per-page archive" in lowered
    assert "static residual" in lowered
    assert "unresolved" in lowered and "current law" in lowered
    assert "docker-copying" in lowered or "docker-copy" in lowered
    assert "--publish-to-hf" in report
    assert "--no-incremental-state-publish" in report
    assert "--retained-replay-only" in report
    assert "seed_retained_evidence_union" in report
    assert "_fetch_new_york_frontier_batch" in report
    assert "_build_official_senate_section" in report
    assert "30-URL" in report or "30-url" in lowered
    assert "214" in report
    assert "37,441" in report
    assert FIRST_RESIDUAL_URL in report
    assert AGM28_URL in report
    assert OFFICIAL_CONSOLIDATED in report
    assert RESIDUAL_SHA256 in report
    assert SEED_PROJECTION_SHA256 in report
    assert INVENTED_SENATE_URL not in report
    assert PUBLIC_LAW_URL not in report
    assert INVENTED_AGENCY_PROOF_URL not in report
    for url in supplemental_urls:
        assert url in report
    senate_url_mentions = report.count("https://www.nysenate.gov/legislation/laws/")
    assert ENUMERABLE_URL_RESIDUAL <= senate_url_mentions <= ENUMERABLE_URL_RESIDUAL + 6


def test_new_york_supplemental_wave_is_source_derived_from_pinned_residual_rows() -> None:
    scraper = NewYorkScraper("NY", "New York")
    rows = list(scraper.STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS)
    pinned = list(scraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)
    derived = _derived_supplemental_urls()

    assert scraper.OFFICIAL_DOMAIN == OFFICIAL_DOMAIN
    assert scraper.OFFICIAL_PDF_DOMAIN == OFFICIAL_PDF_DOMAIN
    assert scraper.OFFICIAL_ENTRY_URL == OFFICIAL_ENTRY
    assert scraper.OFFICIAL_CONSOLIDATED_URL == OFFICIAL_CONSOLIDATED
    assert scraper.STRICT_MINIMUM_CONSOLIDATED_LAWS == CATALOG_LAW_COUNT
    assert scraper.STRICT_CURRENT_CONSOLIDATED_CODE_SHA256 == CATALOG_CODE_SHA256
    assert ny_pdf.AGM28_LIFECYCLE_REPORT_URL == AGM28_URL
    assert ny_pdf.AGM28_LIFECYCLE_REPORT_SHA256 == AGM28_SHA256
    assert ny_pdf.AGM28_LIFECYCLE_SELECTOR_KEY == AGM28_SELECTOR_KEY
    assert len(rows) == SUPPLEMENTAL_RESIDUAL_ROWS
    assert len(pinned) == ENUMERABLE_URL_RESIDUAL == len(set(pinned))
    assert derived == pinned
    assert pinned[0] == FIRST_RESIDUAL_URL
    assert INVENTED_SENATE_URL not in pinned
    assert PUBLIC_LAW_URL not in pinned
    assert all(urlparse(url).hostname == OFFICIAL_DOMAIN for url in pinned)
    assert all("/legislation/laws/" in url for url in pinned)
    note_rows = [row for row in rows if row[3] == "missing_lifecycle_note"]
    toc_rows = [row for row in rows if row[3] == "toc_section_missing_body_identity"]
    assert len(note_rows) == MISSING_NOTE_ROWS
    assert len(toc_rows) == TOC_BODY_ROWS
    extra = [(row[0], row[1], row[2]) for row in rows if row[2]]
    assert extra == list(VARIANT_IDENTITIES)
    assert len(extra) == EXTRA_TOC_VARIANTS
    assert scraper.STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256 == RESIDUAL_SHA256
    assert _newline_residual_sha256(pinned) == RESIDUAL_SHA256
    assert NewYorkScraper._new_york_exact_supplemental_urls(
        [
            SimpleNamespace(
                law_code=law_code,
                unclassified_sections=[
                    {
                        "section_number": section,
                        "toc_variant": variant,
                        "reason": (
                            "ambiguous_lifecycle_status"
                            if reason == "missing_lifecycle_note"
                            else reason
                        ),
                        "detail": (
                            "missing_lifecycle_note:"
                            if reason == "missing_lifecycle_note"
                            else "toc_offset=1"
                        ),
                    }
                ],
            )
            for law_code, section, variant, reason in rows
        ]
    ) == pinned


def test_new_york_adapter_does_not_dump_event_proof_urls_or_use_per_page_senate_loop() -> None:
    adapter = inspect.getsource(NewYorkScraper)
    pdf_frontier = inspect.getsource(
        NewYorkScraper._scrape_official_senate_pdf_frontier
    )
    scrape_source = inspect.getsource(NewYorkScraper.scrape_code)
    registry_source = inspect.getsource(ny_pdf.NewYorkSupplementalProofRegistry)
    resolve_source = inspect.getsource(
        ny_pdf.NewYorkSupplementalProofRegistry.resolve_residual
    )

    assert INVENTED_SENATE_URL not in adapter
    assert PUBLIC_LAW_URL not in adapter
    assert INVENTED_AGENCY_PROOF_URL not in adapter
    assert str(SOURCE_SECTIONS) not in adapter
    assert str(UNRESOLVED_AFTER_AGM) not in adapter
    assert UNRESOLVED_SHA_BEFORE_AGM not in adapter
    assert SEED_PROJECTION_SHA256 not in adapter
    assert "_new_york_exact_supplemental_urls" in pdf_frontier
    assert RESIDUAL_WAVE_NAME in pdf_frontier
    assert "_fetch_new_york_frontier_batch" in pdf_frontier
    assert "_build_official_senate_section" not in pdf_frontier
    assert "public.law" in scrape_source.casefold()
    assert "refusing public.law/Justia sole-admission fallback" in scrape_source
    assert "register_resolver" not in registry_source
    assert "source_bound_resolver_not_implemented" in resolve_source
    assert "decision_action" in resolve_source
    assert '"status": "unknown"' in resolve_source
    senate_url_literals = adapter.count("https://www.nysenate.gov/legislation/laws/")
    assert senate_url_literals >= ENUMERABLE_URL_RESIDUAL
    assert senate_url_literals < 40


def test_new_york_residual_sha256_uses_newline_join_of_ordered_senate_urls() -> None:
    pinned = list(NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)
    digest = _newline_residual_sha256(pinned)
    assert digest == RESIDUAL_SHA256
    assert digest == hashlib.sha256("\n".join(pinned).encode("utf-8")).hexdigest()
    json_digest = hashlib.sha256(
        json.dumps(pinned, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert json_digest != digest
    assert len(digest) == 64
    report = _report_text()
    assert '"\\n".join(urls)' in report
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert AGM28_WAVE_NAME in report
    assert CATALOG_WAVE_NAME in report
    assert PDF_WAVE_PREFIX in report


def test_new_york_one_domain_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(NewYorkScraper._fetch_new_york_frontier_batch)
    pdf_frontier = inspect.getsource(
        NewYorkScraper._scrape_official_senate_pdf_frontier
    )
    retry_source = inspect.getsource(
        NewYorkScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )
    assert "repeated a Common Crawl domain inventory" in fetch_source
    assert "repeated archive discovery on a residual retry" in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "repeat_grouped_archive_inventory_on_residual=True" not in fetch_source
    assert RESIDUAL_WAVE_NAME in pdf_frontier
    assert 'common_crawl_domains=(self.OFFICIAL_DOMAIN,)' in pdf_frontier or (
        "common_crawl_domains=(self.OFFICIAL_DOMAIN,)" in fetch_source
    )
    assert 'common_crawl_url_terms=("/legislation/laws/",)' in pdf_frontier
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in (
        retry_source
    )
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        NewYorkScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"kind": "shared_archive_aware_plural_pdf"' in closure_source


def test_new_york_seed_and_host_replay_forbid_hub_docker_and_unresolved_as_current(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    union_source = inspect.getsource(seed_retained_evidence_union)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source
    assert "multi-source retained evidence seed" in union_source.casefold() or (
        "Atomically union exact retained inputs" in union_source
    )
    assert "network_io_performed" in union_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "NY",
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
    assert "unresolved" in report
    assert "current law" in report
    assert "96-input" in report


def test_new_york_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    york_source = inspect.getsource(
        NewYorkScraper.produce_state_law_frontier_closure
    )
    replay_source = inspect.getsource(NewYorkScraper._replay_new_york_retained_input)
    assert "public_law_no_state_copyright" in closure_source
    assert "retained_replay_network_requests" in york_source
    assert york_source.index('"retained_replay_network_requests": 0') > 0
    assert "New York retained replay requires an attached ledger" in replay_source
    assert "without permitting network I/O" in inspect.getdoc(
        NewYorkScraper._replay_new_york_retained_input
    )
    exact_frontier = inspect.getsource(NewYorkScraper._new_york_exact_frontier)
    assert "conditional_event_selectors" in exact_frontier
    assert "did not prove occurrence" in exact_frontier


def test_new_york_compact_recipe_emits_thirty_url_wave_not_invented_targets() -> None:
    derived = _derived_supplemental_urls()
    pinned = list(NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)
    assert derived == pinned
    assert derived[0] == FIRST_RESIDUAL_URL
    assert derived[-1] == "https://www.nysenate.gov/legislation/laws/VAT/1180-i"
    assert INVENTED_SENATE_URL not in derived
    assert PUBLIC_LAW_URL not in derived
    assert AGM28_URL not in derived
    assert OFFICIAL_CONSOLIDATED not in derived
    assert all(urlparse(url).query == "" for url in derived)
    assert all(urlparse(url).fragment == "" for url in derived)
    digest = _newline_residual_sha256(derived)
    assert digest == RESIDUAL_SHA256
    json_digest = hashlib.sha256(
        json.dumps(derived, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert not json_digest.startswith(RESIDUAL_SHA256_PREFIX)
    assert ny_pdf.public_section_url("EPT", "3-6.5") == FIRST_RESIDUAL_URL


def test_new_york_unimplemented_senate_page_resolver_stays_unknown_and_cannot_close_law(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    law_text = """
    ARTICLE 1
    UNPROVED EVENT
    Section 3-6.5. Conditional provision.
      * § 3-6.5. Conditional provision. This retained statutory body contains
      complete source text but depends upon an independently proved event.
      * NB Effective upon notification by the responsible state agency.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (law_text, 1),
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key="EPT:3-6.5:source-page",
        proof_kind="official_senate_section",
        official_url=FIRST_RESIDUAL_URL,
        media_type="text/html",
        payload=b"<html>" + (b"official section page " * 80) + b"</html>",
    )
    registry = ny_pdf.NewYorkSupplementalProofRegistry([proof])
    parsed = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-law",
        law_code="EPT",
        law_name="Estates, Powers and Trusts",
        supplemental_proof_registry=registry,
    )

    assert parsed.closed is False
    assert parsed.statutes == []
    assert parsed.terminal_sections == []
    assert len(parsed.unclassified_sections) == 1
    attempt = parsed.supplemental_proof_attempts[0]
    assert attempt["status"] == "unknown"
    assert attempt["proof_present"] is True
    assert attempt["decision_action"] is None
    assert attempt["reason"] == "source_bound_resolver_not_implemented"
    assert not hasattr(registry, "register_resolver")
    with pytest.raises(AttributeError):
        registry.register_resolver("EPT:3-6.5", lambda *_args, **_kwargs: None)  # type: ignore[attr-defined]


def test_new_york_compact_supplemental_wave_is_plural_and_stays_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        "<html><body>Consolidated Laws of New York"
        "<a href='/legislation/laws/AAA'>AAA First Law</a>"
        "<a href='/legislation/laws/BBB'>BBB Second Law</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    pdf_by_url = {
        ny_pdf.full_law_pdf_url("AAA"): b"%PDF-AAA" + (b"a" * 1_100),
        ny_pdf.full_law_pdf_url("BBB"): b"%PDF-BBB" + (b"b" * 1_100),
    }
    supplemental_urls = (
        "https://www.nysenate.gov/legislation/laws/AAA/1",
        "https://www.nysenate.gov/legislation/laws/BBB/2",
    )
    section_html = {
        url: (
            b"<html><body>New York State Senate /legislation/laws/ "
            + (url.encode() + b" ") * 40
            + b"</body></html>"
        )
        for url in supplemental_urls
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        payloads = []
        for url in requested:
            if url == self.OFFICIAL_CONSOLIDATED_URL:
                payloads.append(catalog)
            elif url in pdf_by_url:
                payloads.append(pdf_by_url[url])
            elif url in section_html:
                payloads.append(section_html[url])
            else:
                raise AssertionError(f"compact residual requested unknown URL {url}")
        assert all(kwargs["content_validator"](body) for body in payloads)
        return _aligned_result(requested, payloads)

    resolution_attempts: list[dict[str, Any]] = []

    def _fake_parse(
        _payload,
        *,
        law_code,
        law_name,
        supplemental_proof_registry,
        **_kwargs,
    ):
        row = (
            {
                "section_number": "1",
                "toc_variant": "",
                "reason": "ambiguous_lifecycle_status",
                "detail": "missing_lifecycle_note:",
            }
            if law_code == "AAA"
            else {
                "section_number": "2",
                "toc_variant": "*2",
                "reason": "toc_section_missing_body_identity",
                "detail": "toc_offset=1",
            }
        )
        resolution_attempts.append(
            supplemental_proof_registry.resolve_residual(
                law_code=law_code,
                residual=row,
            )
        )
        return SimpleNamespace(
            closed=False,
            law_code=law_code,
            law_name=law_name,
            source_section_count=1,
            statutes=[],
            terminal_sections=[],
            unclassified_sections=[row],
        )

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict New York must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 2)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("AAA", "BBB"),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS",
        (
            ("AAA", "1", "", "missing_lifecycle_note"),
            ("BBB", "2", "*2", "toc_section_missing_body_identity"),
        ),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS",
        supplemental_urls,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256",
        _newline_residual_sha256(supplemental_urls),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    monkeypatch.setattr(ny_pdf, "parse_new_york_law_pdf", _fake_parse)
    scraper = NewYorkScraper("NY", "New York")

    with pytest.raises(RuntimeError, match="law=AAA"):
        asyncio.run(
            scraper.scrape_code(
                "New York Consolidated Laws",
                NewYorkScraper.OFFICIAL_ENTRY_URL,
                max_statutes=None,
            )
        )

    requested_waves = [call[0] for call in calls]
    assert requested_waves[0] == [scraper.OFFICIAL_CONSOLIDATED_URL]
    assert requested_waves[1] == list(pdf_by_url)
    assert requested_waves[-1] == list(supplemental_urls)
    assert INVENTED_SENATE_URL not in [url for wave in requested_waves for url in wave]
    assert PUBLIC_LAW_URL not in [url for wave in requested_waves for url in wave]
    assert AGM28_URL not in [url for wave in requested_waves for url in wave]
    supplemental_kwargs = calls[-1][1]
    assert supplemental_kwargs["common_crawl_domain_terms"] == (OFFICIAL_DOMAIN,)
    assert supplemental_kwargs["common_crawl_url_terms"] == ("/legislation/laws/",)
    assert supplemental_kwargs["wayback_prefix_inventory"] is True
    assert supplemental_kwargs["prefer_direct"] is True
    assert all(row["status"] == "unknown" for row in resolution_attempts)
    assert all(row["decision_action"] is None for row in resolution_attempts)
    stats = list(getattr(scraper, "_new_york_frontier_batch_stats", []))
    assert [row["frontier_name"] for row in stats][-1] == RESIDUAL_WAVE_NAME
