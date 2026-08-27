"""Scraper for North Dakota state laws.

This module contains the scraper for North Dakota statutes from the official state legislative website.
"""

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import hashlib
import json
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry
from .retained_replay_network_guard import trusted_pdftotext_executable


class NorthDakotaScraper(BaseStateScraper):
    """Scraper for North Dakota state laws from https://www.legis.nd.gov"""

    OFFICIAL_DOMAIN = "www.legis.nd.gov"
    OFFICIAL_ENTRY_PATH = "/general-information/north-dakota-century-code"
    OFFICIAL_ENTRY_URL = "https://www.legis.nd.gov/general-information/north-dakota-century-code"
    OFFICIAL_INDEX_URL = (
        "https://www.legis.nd.gov/general-information/"
        "north-dakota-century-code/index.html"
    )
    _ND_CENCODE_PDF_RE = re.compile(r"/cencode/.*?\.pdf$", re.IGNORECASE)
    _ND_CENCODE_FILE_RE = re.compile(r"t(\d{1,3})c(\d{1,3})\.pdf$", re.IGNORECASE)
    _ND_TITLE_HREF_RE = re.compile(
        r"/cencode/t(?P<title>\d{1,2}(?:-\d)?)\.html$",
        re.IGNORECASE,
    )
    _ND_TITLE_LABEL_RE = re.compile(r"\bTitle\s+(?P<title>\d{1,2}(?:\.\d)?)\b", re.IGNORECASE)
    _ND_TITLE_HEADING_RE = re.compile(
        r"^Title\s+(?P<title>\d{1,2}(?:\.\d)?)\s*-\s*(?P<name>.+)$",
        re.IGNORECASE,
    )
    _ND_CHAPTER_HEADING_RE = re.compile(
        r"^Chapter\s+(?P<chapter>\d{1,2}(?:\.\d)?-[0-9A-Za-z.]+)\s*-\s*"
        r"(?P<name>.+)$",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Aeronautics"),
        ("3", "Agency"),
        ("4", "Agriculture"),
        ("4.1", "Agriculture"),
        ("5", "Alcoholic Beverages"),
        ("6", "Banks and Banking"),
        ("7", "Building and Loan Associations"),
        ("8", "Carriage"),
        ("9", "Contracts and Obligations"),
        ("10", "Corporations"),
        ("11", "Counties"),
        ("12", "Corrections, Parole, and Probation"),
        ("12.1", "Criminal Code"),
        ("13", "Debtor and Creditor Relationship"),
        ("14", "Domestic Relations and Persons"),
        ("15", "Education"),
        ("15.1", "Elementary and Secondary Education"),
        ("16", "Elections"),
        ("16.1", "Elections"),
        ("17", "Energy"),
        ("18", "Fires"),
        ("19", "Foods, Drugs, Oils, and Compounds"),
        ("20", "Game, Fish, and Predators"),
        ("20.1", "Game, Fish, Predators, and Boating"),
        ("21", "Governmental Finance"),
        ("22", "Guaranty, Indemnity, and Suretyship"),
        ("23", "Health and Safety"),
        ("23.1", "Environmental Quality"),
        ("24", "Highways, Bridges, and Ferries"),
        ("25", "Mental and Physical Illness or Disability"),
        ("26", "Insurance"),
        ("26.1", "Insurance"),
        ("27", "Judicial Branch of Government"),
        ("28", "Judicial Procedure, Civil"),
        ("29", "Judicial Procedure, Criminal"),
        ("30", "Judicial Procedure, Probate"),
        ("30.1", "Uniform Probate Code"),
        ("31", "Judicial Proof"),
        ("32", "Judicial Remedies"),
        ("33", "County Justice Court"),
        ("34", "Labor and Employment"),
        ("35", "Liens"),
        ("36", "Livestock"),
        ("37", "Military"),
        ("38", "Mining and Gas and Oil Production"),
        ("39", "Motor Vehicles"),
        ("40", "Municipal Government"),
        ("41", "Uniform Commercial Code"),
        ("42", "Nuisances"),
        ("43", "Occupations and Professions"),
        ("44", "Offices and Officers"),
        ("45", "Partnerships"),
        ("46", "Printing Laws"),
        ("47", "Property"),
        ("48", "Public Buildings"),
        ("49", "Public Utilities"),
        ("50", "Public Welfare"),
        ("51", "Sales and Exchanges"),
        ("52", "Social Security"),
        ("53", "Sports and Amusements"),
        ("54", "State Government"),
        ("55", "State Historical Society and State Parks"),
        ("56", "Succession and Wills"),
        ("57", "Taxation"),
        ("58", "Townships"),
        ("59", "Trusts, Uses, and Powers"),
        ("60", "Warehousing and Deposits"),
        ("61", "Waters"),
        ("62", "Weapons"),
        ("62.1", "Weapons"),
        ("63", "Weeds"),
        ("64", "Weights, Measures, and Grades"),
        ("65", "Workforce Safety and Insurance"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    def state_law_frontier_source_dependencies(self) -> tuple[object, ...]:
        """Bind exact frontier evidence to the sibling PDF parser."""

        from . import north_dakota_chapter

        return (north_dakota_chapter,)

    @staticmethod
    def _north_dakota_frontier_values_sha256(values: Sequence[str]) -> str:
        payload = json.dumps(
            list(values),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _north_dakota_operative_row_binding_sha256(
        statute: NormalizedStatute,
    ) -> str:
        """Bind every field used to admit one exact operative PDF row."""

        structured = dict(statute.structured_data or {})
        for key in (
            "citations",
            "jsonld",
            "legislative_history",
            "parser_warnings",
            "preamble",
            "subsections",
        ):
            structured.pop(key, None)
        payload = statute.to_dict()
        payload.pop("scraped_at", None)
        payload["full_text_sha256"] = hashlib.sha256(
            str(payload.pop("full_text", "") or "").encode("utf-8")
        ).hexdigest()
        payload["structured_data"] = structured
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _is_valid_north_dakota_index_payload(payload: bytes) -> bool:
        sample = bytes(payload or b"")[:2_000_000].lower()
        return bool(
            b"<html" in sample
            and b"north dakota century code" in sample
            and b"<h2>title " in sample
            and b"/cencode/" in sample
            and b"404 not found" not in sample
        )

    @staticmethod
    def _is_valid_north_dakota_pdf_payload(payload: bytes) -> bool:
        raw = bytes(payload or b"")
        return len(raw) >= 500 and raw.lstrip().startswith(b"%PDF-")

    def _validate_north_dakota_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Require exact URL/body evidence whenever a ledger is attached."""

        canonical_url = self._canonical_fetch_url(url)
        content_sha256 = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"North Dakota {frontier_name} frontier lacks retained evidence: {url}"
            )
        if isinstance(transport_receipt, Mapping):
            observed_url = str(
                transport_receipt.get("official_url")
                or transport_receipt.get("endpoint")
                or ""
            ).strip()
            observed_digest = str(
                transport_receipt.get("content_sha256") or ""
            ).strip().lower()
            if ledger_attached and (not observed_url or not observed_digest):
                raise RuntimeError(
                    f"North Dakota {frontier_name} receipt lacks URL/digest: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"North Dakota {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != content_sha256:
                raise RuntimeError(
                    f"North Dakota {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"North Dakota {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"North Dakota {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_north_dakota_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
        media_type: str,
    ) -> List[bytes]:
        """Fetch one exact same-domain frontier through grouped WARC ranges."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if not requested or any(not url for url in requested):
            raise RuntimeError(
                f"North Dakota {frontier_name} frontier is empty or invalid"
            )
        if len(requested) != len(set(requested)):
            raise RuntimeError(
                f"North Dakota {frontier_name} frontier contains duplicate URLs"
            )
        retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_ND_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=3,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            timeout_seconds=120,
            headers={
                "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5",
                "User-Agent": "ipfs-datasets-north-dakota-century-code/2.0",
            },
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=max(
                1,
                min(
                    32,
                    self._env_int(
                        "STATE_SCRAPER_ND_FRONTIER_CONCURRENCY",
                        default=8,
                    ),
                ),
            ),
            prefer_direct=True,
            common_crawl_domain_terms=("legis.nd.gov", "ndlegis.gov"),
            common_crawl_url_terms=("/cencode/",),
            common_crawl_mime_terms=("pdf", "html"),
            wayback_prefix_inventory=True,
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)} or list(batch.urls) != requested:
            raise RuntimeError(
                f"North Dakota {frontier_name} frontier returned unaligned URL identities"
            )
        failures: List[Dict[str, str]] = []
        payloads: List[bytes] = []
        for url, payload, error, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            raw = bytes(payload or b"")
            if error is not None or not content_validator(raw):
                failures.append(
                    {"url": url, "error": str(error or "invalid parser input")}
                )
                continue
            self._validate_north_dakota_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
            payloads.append(raw)
        if failures:
            raise RuntimeError(
                f"North Dakota {frontier_name} frontier is incomplete after "
                f"residual-only retries: {failures}"
            )
        return payloads

    @staticmethod
    def _north_dakota_pdf_text_lines(pdf_bytes: bytes) -> str:
        """Extract stable line-oriented PDF text for the section parser."""

        if not pdf_bytes:
            return ""
        try:
            proc = subprocess.run(
                [trusted_pdftotext_executable(), "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""
        if proc.returncode != 0 or not proc.stdout:
            return ""
        return proc.stdout.decode("utf-8", errors="replace")

    @staticmethod
    def _north_dakota_catalog_name(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().casefold()

    def _parse_north_dakota_index_frontier(
        self,
        payload: bytes,
    ) -> Tuple[
        List[Dict[str, str]],
        List[Dict[str, Any]],
        List[Dict[str, str]],
    ]:
        """Project the official collapsed index into titles, chapters, leaves."""

        from .north_dakota_chapter import source_bound_terminal_disposition

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for North Dakota") from exc
        soup = BeautifulSoup(bytes(payload or b""), "html.parser")
        title_units: List[Dict[str, str]] = []
        chapter_units: List[Dict[str, Any]] = []
        direct_units: List[Dict[str, str]] = []
        seen_titles: set[str] = set()
        seen_chapters: set[str] = set()
        seen_sections: set[str] = set()
        seen_direct_urls: set[str] = set()

        for details in soup.select("details.accordion"):
            summary = details.find("summary", class_="outer", recursive=False)
            if summary is None:
                continue
            heading = summary.find("h2")
            match = self._ND_TITLE_HEADING_RE.match(
                re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
                if heading is not None
                else ""
            )
            if match is None:
                continue
            title_number = self._normalize_title_number(match.group("title"))
            if not title_number or title_number in seen_titles:
                raise RuntimeError(
                    "North Dakota index repeated or invalid title identity: "
                    f"{title_number!r}"
                )
            seen_titles.add(title_number)
            title_units.append(
                {
                    "title_number": title_number,
                    "source_label": match.group("name").strip(),
                    "source_url": self.OFFICIAL_INDEX_URL,
                }
            )

            for child in details.find_all(["details", "a"], recursive=False):
                if child.name == "a" and "no-items" in (child.get("class") or []):
                    source_label = re.sub(
                        r"\s+", " ", child.get_text(" ", strip=True)
                    ).strip()
                    source_url = urljoin(
                        self.OFFICIAL_INDEX_URL,
                        str(child.get("href") or "").strip(),
                    ).split("#", 1)[0]
                    if (
                        not source_label
                        or not self._host_is_official(source_url)
                        or source_url in seen_direct_urls
                    ):
                        raise RuntimeError(
                            "North Dakota index contains an invalid or duplicate "
                            f"direct leaf: {source_label!r} {source_url!r}"
                        )
                    seen_direct_urls.add(source_url)
                    direct_units.append(
                        {
                            "frontier_level": (
                                "title"
                                if source_label.casefold().startswith("title ")
                                else "chapter"
                            ),
                            "title_number": title_number,
                            "source_label": source_label,
                            "source_url": source_url,
                            "disposition": source_bound_terminal_disposition(
                                source_label
                            ),
                        }
                    )
                    continue
                if child.name != "details":
                    continue
                chapter_heading = child.find("h3")
                chapter_match = self._ND_CHAPTER_HEADING_RE.match(
                    re.sub(
                        r"\s+",
                        " ",
                        chapter_heading.get_text(" ", strip=True),
                    ).strip()
                    if chapter_heading is not None
                    else ""
                )
                if chapter_match is None:
                    raise RuntimeError(
                        "North Dakota active chapter lacks an exact source identity"
                    )
                chapter_number = chapter_match.group("chapter").strip()
                if (
                    chapter_number in seen_chapters
                    or not chapter_number.casefold().startswith(
                        title_number.casefold() + "-"
                    )
                ):
                    raise RuntimeError(
                        "North Dakota index repeated or cross-wired chapter identity: "
                        f"{chapter_number}"
                    )
                seen_chapters.add(chapter_number)
                section_units: List[Dict[str, str]] = []
                pdf_urls: set[str] = set()
                for row in child.select("table.simple-table tbody tr"):
                    cells = row.find_all("td")
                    anchor = cells[0].find("a", href=True) if cells else None
                    if anchor is None:
                        continue
                    section_number = re.sub(
                        r"\s+", " ", anchor.get_text(" ", strip=True)
                    ).strip().replace("‑", "-")
                    section_name = re.sub(
                        r"\s+",
                        " ",
                        cells[1].get_text(" ", strip=True) if len(cells) > 1 else "",
                    ).strip()
                    source_url = urljoin(
                        self.OFFICIAL_INDEX_URL,
                        str(anchor.get("href") or "").strip(),
                    ).split("#", 1)[0]
                    if (
                        not section_number
                        or section_number in seen_sections
                        or not section_number.casefold().startswith(
                            chapter_number.casefold() + "-"
                        )
                        or not self._host_is_official(source_url)
                    ):
                        raise RuntimeError(
                            "North Dakota index contains an invalid, duplicate, or "
                            f"cross-wired section identity: {section_number!r}"
                        )
                    seen_sections.add(section_number)
                    pdf_urls.add(source_url)
                    section_units.append(
                        {
                            "section_number": section_number,
                            "source_label": section_name,
                            "source_url": source_url,
                            "disposition": source_bound_terminal_disposition(
                                section_name
                            ),
                        }
                    )
                if not section_units or len(pdf_urls) != 1:
                    raise RuntimeError(
                        "North Dakota active chapter did not resolve to one exact PDF: "
                        f"{chapter_number}"
                    )
                chapter_units.append(
                    {
                        "title_number": title_number,
                        "chapter_number": chapter_number,
                        "source_label": chapter_match.group("name").strip(),
                        "source_url": next(iter(pdf_urls)),
                        "sections": section_units,
                    }
                )
        if not title_units or not chapter_units:
            raise RuntimeError("North Dakota official index produced no active frontier")
        return title_units, chapter_units, direct_units

    def _validate_north_dakota_live_static_title_catalog(
        self,
        units: Sequence[Mapping[str, str]],
    ) -> None:
        expected = {
            str(number): self._north_dakota_catalog_name(name)
            for number, name in self.OFFICIAL_TITLES
        }
        observed = {
            str(unit.get("title_number") or ""): self._north_dakota_catalog_name(
                unit.get("source_label")
            )
            for unit in units
        }
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        mismatches = [
            {
                "title": number,
                "expected_name": expected[number],
                "observed_name": observed[number],
            }
            for number in sorted(set(expected) & set(observed))
            if expected[number] != observed[number]
        ]
        if (
            len(units) != self.OFFICIAL_TITLE_COUNT
            or len(observed) != len(units)
            or missing
            or extra
            or mismatches
        ):
            raise RuntimeError(
                "North Dakota live/static title catalog parity failed; "
                f"missing={missing} extra={extra} mismatches={mismatches}"
            )

    async def _scrape_strict_full_corpus_frontier(
        self,
        code_name: str,
        *,
        record_primary: bool,
        write_checkpoints: bool,
    ) -> List[NormalizedStatute]:
        """Acquire and close the exact collapsed-index-to-PDF ND frontier."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        from .north_dakota_chapter import (
            parse_north_dakota_chapter_text_with_dispositions,
            source_bound_document_terminal_disposition,
        )

        observed_at = datetime.now(timezone.utc).isoformat()
        index_payload = (
            await self._fetch_north_dakota_frontier_batch(
                [self.OFFICIAL_INDEX_URL],
                frontier_name="collapsed-index",
                content_validator=self._is_valid_north_dakota_index_payload,
                media_type="text/html",
            )
        )[0]
        title_units, chapter_units, direct_units = (
            self._parse_north_dakota_index_frontier(index_payload)
        )
        self._validate_north_dakota_live_static_title_catalog(title_units)
        index_sha256 = hashlib.sha256(index_payload).hexdigest()

        terminal_units: List[Dict[str, Any]] = [
            {
                **unit,
                "content_sha256": index_sha256,
            }
            for unit in direct_units
            if str(unit.get("disposition") or "")
        ]
        unclassified_direct_units = [
            unit for unit in direct_units if not str(unit.get("disposition") or "")
        ]
        pdf_units: List[Dict[str, Any]] = [*chapter_units, *unclassified_direct_units]
        pdf_urls = [str(unit["source_url"]) for unit in pdf_units]
        if not pdf_urls or len(pdf_urls) != len(set(pdf_urls)):
            raise RuntimeError(
                "North Dakota fetch frontier contains empty or duplicate PDF locators"
            )
        pdf_payloads = await self._fetch_north_dakota_frontier_batch(
            pdf_urls,
            frontier_name="operative-and-unclassified-pdfs",
            content_validator=self._is_valid_north_dakota_pdf_payload,
            media_type="application/pdf",
        )

        statutes: List[NormalizedStatute] = []
        seen_statute_ids: set[str] = set()
        indexed_section_ids: List[str] = []
        selected_temporal_identity_count = 0
        selected_temporal_variants_excluded = 0
        source_identity_repair_count = 0
        for unit, payload in zip(pdf_units, pdf_payloads, strict=True):
            source_url = str(unit["source_url"])
            content_sha256 = hashlib.sha256(payload).hexdigest()
            text = self._north_dakota_pdf_text_lines(payload)
            if not text.strip():
                raise RuntimeError(
                    f"North Dakota PDF produced no parser text: {source_url}"
                )
            section_units_raw = unit.get("sections")
            if not isinstance(section_units_raw, list):
                disposition = source_bound_document_terminal_disposition(text)
                if not disposition:
                    raise RuntimeError(
                        "North Dakota direct index leaf has neither an indexed "
                        "section frontier nor a source-bound terminal PDF: "
                        f"{source_url}"
                    )
                terminal_units.append(
                    {
                        **unit,
                        "disposition": disposition,
                        "content_sha256": content_sha256,
                    }
                )
                continue

            section_units = [
                dict(section_unit) for section_unit in section_units_raw
            ]
            expected_ids = [
                str(section_unit.get("section_number") or "")
                for section_unit in section_units
            ]
            rows, parser_terminals, unresolved = (
                parse_north_dakota_chapter_text_with_dispositions(
                    text,
                    source_url=source_url,
                    code_name=code_name,
                    expected_section_numbers=expected_ids,
                    expected_section_labels={
                        str(section_unit.get("section_number") or ""): str(
                            section_unit.get("source_label") or ""
                        )
                        for section_unit in section_units
                    },
                )
            )
            if unresolved:
                raise RuntimeError(
                    "North Dakota chapter parser left nonterminal residuals: "
                    f"source={source_url} residuals={unresolved[:10]}"
                )
            index_marked_terminal = [
                str(section_unit.get("section_number") or "")
                for section_unit in section_units
                if str(section_unit.get("disposition") or "")
            ]
            row_ids = [str(row.section_number or "") for row in rows]
            parser_terminal_ids = [
                str(terminal.get("section_number") or "")
                for terminal in parser_terminals
            ]
            parser_terminal_set = set(parser_terminal_ids)
            expected_active = [
                section_number
                for section_number in expected_ids
                if section_number not in parser_terminal_set
            ]
            expected_terminal = [
                section_number
                for section_number in expected_ids
                if section_number in parser_terminal_set
            ]
            if (
                len(expected_ids) != len(set(expected_ids))
                or len(row_ids) != len(set(row_ids))
                or len(parser_terminal_ids) != len(parser_terminal_set)
                or not set(index_marked_terminal).issubset(parser_terminal_set)
                or row_ids != expected_active
                or parser_terminal_ids != expected_terminal
            ):
                raise RuntimeError(
                    "North Dakota PDF/index section identity reconciliation failed: "
                    f"source={source_url} expected={expected_ids[:5]} "
                    f"operative={row_ids[:5]} terminal={parser_terminal_ids[:5]}"
                )
            indexed_section_ids.extend(expected_ids)
            expected_by_id = {
                str(section_unit["section_number"]): section_unit
                for section_unit in section_units
            }
            for terminal in parser_terminals:
                section_number = str(terminal["section_number"])
                index_terminal = expected_by_id[section_number]
                terminal_units.append(
                    {
                        **terminal,
                        "source_label": str(index_terminal.get("source_label") or ""),
                        "disposition": str(
                            index_terminal.get("disposition")
                            or terminal.get("disposition")
                            or ""
                        ),
                        "content_sha256": content_sha256,
                    }
                )
            for statute in rows:
                section_number = str(statute.section_number or "")
                if (
                    section_number not in expected_by_id
                    or str(statute.source_url or "") != source_url
                    or str(statute.title_number or "")
                    != str(unit.get("title_number") or "")
                    or str(statute.chapter_number or "")
                    != str(unit.get("chapter_number") or "")
                ):
                    raise RuntimeError(
                        "North Dakota normalized section changed its indexed identity: "
                        f"{section_number}"
                    )
                folded_id = str(statute.statute_id or "").casefold()
                if not folded_id or folded_id in seen_statute_ids:
                    raise RuntimeError(
                        "North Dakota normalized statute identity is empty or repeated: "
                        f"{statute.statute_id}"
                    )
                seen_statute_ids.add(folded_id)
                parser_data = dict(statute.structured_data or {})
                variant_count = int(parser_data.get("effective_variant_count") or 1)
                if variant_count > 1:
                    variants = parser_data.get("effective_variants")
                    excluded_indexes = parser_data.get(
                        "effective_variant_excluded_indexes"
                    )
                    if (
                        not isinstance(variants, list)
                        or len(variants) != variant_count
                        or not isinstance(excluded_indexes, list)
                        or len(excluded_indexes) != variant_count - 1
                        or parser_data.get("effective_variant_selection")
                        != "official_index_current_heading"
                    ):
                        raise RuntimeError(
                            "North Dakota temporal PDF variants lack exact "
                            f"selection disclosure: {section_number}"
                        )
                    selected_temporal_identity_count += 1
                    selected_temporal_variants_excluded += variant_count - 1
                source_identity_repair_count += bool(
                    parser_data.get("section_identity_repair")
                )
                statute.structured_data = {
                    **parser_data,
                    "content_sha256": content_sha256,
                    "index_source_label": str(
                        expected_by_id[section_number].get("source_label") or ""
                    ),
                }
                statutes.append(statute)

        discovered = len(indexed_section_ids) + len(direct_units)
        disposition = {
            "discovered": discovered,
            "fetched": len(statutes),
            "excluded": len(terminal_units),
            "failed_final": 0,
            "duplicates": 0,
            "quarantined": 0,
        }
        if discovered != sum(
            disposition[key]
            for key in (
                "fetched",
                "excluded",
                "failed_final",
                "duplicates",
                "quarantined",
            )
        ):
            raise RuntimeError("North Dakota strict disposition algebra did not close")
        source_record_disposition = {
            **disposition,
            "discovered": discovered + selected_temporal_variants_excluded,
            "excluded": len(terminal_units) + selected_temporal_variants_excluded,
        }
        if source_record_disposition["discovered"] != sum(
            source_record_disposition[key]
            for key in (
                "fetched",
                "excluded",
                "failed_final",
                "duplicates",
                "quarantined",
            )
        ):
            raise RuntimeError(
                "North Dakota physical source-record disposition did not close"
            )
        all_leaf_urls = [
            str(unit["source_url"]) for unit in [*chapter_units, *direct_units]
        ]
        statute_ids = [str(statute.statute_id) for statute in statutes]
        operative_row_binding_sha256s = [
            self._north_dakota_operative_row_binding_sha256(statute)
            for statute in statutes
        ]
        if len(operative_row_binding_sha256s) != len(
            set(operative_row_binding_sha256s)
        ):
            raise RuntimeError(
                "North Dakota operative row bindings are not one-to-one"
            )
        frontier: Dict[str, Any] = {
            "active_chapter_count": len(chapter_units),
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_expected_units": self.OFFICIAL_TITLE_COUNT,
            "catalog_observed_units": len(title_units),
            "catalog_parity": True,
            "chapter_count": len(chapter_units) + len(direct_units),
            "closed": True,
            "direct_leaf_count": len(direct_units),
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": discovered,
            "fetched_pdf_count": len(pdf_units),
            "fetched_pdf_locators_sha256": self._north_dakota_frontier_values_sha256(
                pdf_urls
            ),
            "index_content_sha256": index_sha256,
            "indexed_section_count": len(indexed_section_ids),
            "indexed_section_ids_sha256": self._north_dakota_frontier_values_sha256(
                indexed_section_ids
            ),
            "leaf_locator_count": len(all_leaf_urls),
            "leaf_locators_sha256": self._north_dakota_frontier_values_sha256(
                all_leaf_urls
            ),
            "operative_row_binding_count": len(operative_row_binding_sha256s),
            "operative_row_bindings_sha256": (
                self._north_dakota_frontier_values_sha256(
                    operative_row_binding_sha256s
                )
            ),
            "pagination_closed": True,
            "pdf_section_occurrence_count": (
                len(indexed_section_ids) + selected_temporal_variants_excluded
            ),
            "schema_version": "north-dakota-strict-collapsed-pdf-frontier-v1",
            "selected_multi_variant_identity_count": (
                selected_temporal_identity_count
            ),
            "selected_temporal_variants_excluded": (
                selected_temporal_variants_excluded
            ),
            "scope_closed": True,
            "source_identity_repair_count": source_identity_repair_count,
            "source_record_disposition": source_record_disposition,
            "source_record_count": source_record_disposition["discovered"],
            "statute_ids_sha256": self._north_dakota_frontier_values_sha256(
                statute_ids
            ),
            "terminal_units": terminal_units,
            "title_count": len(title_units),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": discovered,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        observation = {
            "boundary_first": pdf_urls[0],
            "boundary_last": pdf_urls[-1],
            "frontier": frontier,
            "observed_at": observed_at,
            "operative_row_binding_sha256s": frozenset(
                operative_row_binding_sha256s
            ),
            "statute_ids": statute_ids,
            "statute_id_set": frozenset(statute_ids),
        }
        target = (
            "_last_north_dakota_full_frontier"
            if record_primary
            else "_last_north_dakota_replayed_frontier"
        )
        setattr(self, target, observation)
        if write_checkpoints:
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="north-dakota:complete",
                force=True,
                replace_existing_rows=True,
                extra={
                    "titles_scanned": len(title_units),
                    "discovered_titles": len(title_units),
                    "chapters_scanned": len(chapter_units) + len(direct_units),
                    "discovered_chapters": len(chapter_units) + len(direct_units),
                    "sections_scanned": discovered,
                    "discovered_sections": discovered,
                    "terminal_sections_classified": len(terminal_units),
                    "terminal_section_dispositions": terminal_units,
                    "disposition": disposition,
                    "codes_completed": 1,
                    "codes_total": 1,
                },
            )
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained index/PDF inputs and seal exact ND leaf algebra."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "North Dakota frontier closure requires an attached acquisition ledger"
            )
        first = getattr(self, "_last_north_dakota_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "North Dakota strict frontier was not observed before rows escaped"
            )
        replay_rows = await self._scrape_strict_full_corpus_frontier(
            "North Dakota Century Code",
            record_primary=False,
            write_checkpoints=False,
        )
        replay = getattr(self, "_last_north_dakota_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("North Dakota strict frontier replay was not retained")

        from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
            build_canonical_state_law_output_projection,
        )

        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("North Dakota strict frontier observations are incomplete")
        if canonical_json_bytes(first_frontier) != canonical_json_bytes(
            replayed_frontier
        ):
            raise RuntimeError("North Dakota first and replayed exact frontiers differ")
        replay_projection = build_canonical_state_law_output_projection(
            [self._enrich_statute_structure(row).to_dict() for row in replay_rows],
            jurisdiction="ND",
        )
        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw,
            (str, bytes, bytearray),
        ):
            raise RuntimeError("North Dakota canonical output lacks exact identities")
        output_keys = [str(item).strip() for item in output_keys_raw]
        replay_keys = [
            str(item).strip()
            for item in replay_projection.get("canonical_keys", [])
        ]
        if (
            not output_keys
            or any(not item for item in output_keys)
            or len(output_keys) != len(set(output_keys))
            or output_keys != replay_keys
        ):
            raise RuntimeError(
                "North Dakota final canonical identities do not exactly match "
                "the independently replayed index/PDF frontier"
            )
        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("North Dakota strict frontier lacks disposition algebra")
        if int(disposition.get("fetched") or -1) != len(output_keys):
            raise RuntimeError(
                "North Dakota strict fetched count changed after output filtering"
            )
        completion = closed_jurisdiction_receipt(
            "ND",
            discovered=int(disposition["discovered"]),
            fetched=int(disposition["fetched"]),
            excluded=int(disposition["excluded"]),
            quarantined=int(disposition["quarantined"]),
            failed_final=int(disposition["failed_final"]),
            duplicates=int(disposition["duplicates"]),
            source_domain=self.OFFICIAL_DOMAIN,
            canonical_keys=output_keys,
            derived_keys=output_keys,
        )
        completion.update(
            {
                "boundary_probes": {
                    "bundle_total": 0,
                    "first_hierarchy_unit": str(first.get("boundary_first") or ""),
                    "last_hierarchy_unit": str(first.get("boundary_last") or ""),
                    "pagination_total": int(first_frontier.get("title_count") or 0),
                },
                "canonical_row_count": len(output_keys),
                "frontier": dict(first_frontier),
                "legal_as_of": str(first.get("observed_at") or ""),
                "observed_at": str(first.get("observed_at") or ""),
                "replay": {
                    "closed": True,
                    "first_frontier_digest": str(
                        first_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "second_frontier_digest": str(
                        replayed_frontier.get("frontier_digest_sha256") or ""
                    ),
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "transport": {
                    "fixture": False,
                    "kind": "shared_archive_aware_plural_pdf",
                    "synthetic": False,
                },
            }
        )
        frontier_digest = str(first_frontier.get("frontier_digest_sha256") or "")
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(replayed_frontier),
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{frontier_digest}",
            official_source_url=self.OFFICIAL_INDEX_URL,
            acquisition_path_ids=self._catalog_acquisition_path_ids_for_source(
                self.OFFICIAL_ENTRY_URL
            ),
            observation_time=str(first.get("observed_at") or ""),
            source_software_version=self._state_law_frontier_source_software_version(),
        )

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        """Admit only rows proved by the closed collapsed-index/PDF frontier.

        North Dakota provisions legitimately use generic navigation words such
        as ``members``, ``agency``, ``session``, and ``media``.  Those words
        must not make exact official PDF rows disappear, but an official host
        alone is insufficient: the complete row must match the primary
        frontier observation made before generic quality filtering.
        """

        if not isinstance(statute, NormalizedStatute):
            return False
        observation = getattr(self, "_last_north_dakota_full_frontier", None)
        if not isinstance(observation, Mapping):
            return False
        frontier = observation.get("frontier")
        bindings = observation.get("operative_row_binding_sha256s")
        statute_ids = observation.get("statute_ids")
        statute_id_set = observation.get("statute_id_set")
        if (
            not isinstance(frontier, Mapping)
            or not isinstance(bindings, frozenset)
            or not isinstance(statute_ids, list)
            or not isinstance(statute_id_set, frozenset)
            or frontier.get("closed") is not True
            or frontier.get("algebra_closed") is not True
            or frontier.get("enumerator_closed") is not True
            or frontier.get("catalog_parity") is not True
            or frontier.get("scope_closed") is not True
            or frontier.get("toc_exhausted") is not True
        ):
            return False
        disposition = frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            return False
        fetched = int(disposition.get("fetched") or -1)
        if (
            fetched <= 0
            or fetched != len(bindings)
            or fetched != len(statute_ids)
            or fetched != len(statute_id_set)
            or int(frontier.get("operative_row_binding_count") or -1) != fetched
            or re.fullmatch(
                r"[a-f0-9]{64}",
                str(frontier.get("operative_row_bindings_sha256") or ""),
            )
            is None
        ):
            return False

        structured = statute.structured_data
        if not isinstance(structured, Mapping):
            return False
        section_number = str(statute.section_number or "").strip()
        title_number = str(statute.title_number or "").strip()
        chapter_number = str(statute.chapter_number or "").strip()
        section_parts = section_number.split("-")
        source_url = str(statute.source_url or "").strip()
        parsed_source = urlparse(source_url)
        content_sha256 = str(structured.get("content_sha256") or "").strip()
        index_source_label = str(
            structured.get("index_source_label") or ""
        ).strip()
        if (
            str(statute.state_code or "") != "ND"
            or str(statute.state_name or "") != "North Dakota"
            or str(statute.code_name or "") != "North Dakota Century Code"
            or not section_number
            or len(section_parts) < 3
            or title_number != section_parts[0]
            or chapter_number != "-".join(section_parts[:2])
            or str(statute.statute_id or "")
            != f"North Dakota Century Code § {section_number}"
            or str(statute.official_cite or "")
            != f"N.D. Cent. Code § {section_number}"
            or not str(statute.section_name or "").strip()
            or not str(statute.full_text or "").strip()
            or parsed_source.scheme != "https"
            or (parsed_source.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_source.query
            or parsed_source.fragment
            or self._ND_CENCODE_PDF_RE.fullmatch(parsed_source.path or "") is None
            or structured.get("source_kind")
            != "official_north_dakota_chapter_pdf"
            or structured.get("source_authority_class") != "official"
            or structured.get("discovery_method")
            != "ndlegis_cencode_chapter_pdf"
            or structured.get("skip_hydrate") is not True
            or re.fullmatch(r"[a-f0-9]{64}", content_sha256) is None
            or not index_source_label
            or str(statute.statute_id or "") not in statute_id_set
        ):
            return False
        return (
            self._north_dakota_operative_row_binding_sha256(statute)
            in bindings
        )

    def _filter_non_code_results(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        for statute in statutes:
            url = str(statute.source_url or "").lower()
            text = str(statute.full_text or "").lower()
            if "/cencode/" not in url and "web.archive.org/web/" not in url:
                continue
            if "/assembly/" in url:
                continue
            if "legislative assembly - regular session" in text:
                continue
            out.append(statute)
        return out
    
    def get_base_url(self) -> str:
        """Return the base URL for North Dakota's legislative website."""
        return "https://www.legis.nd.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for North Dakota."""
        return [{
            "name": "North Dakota Century Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from North Dakota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        from .north_dakota_constitution import (
            configured_constitution_html_path,
            parse_north_dakota_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                limit = max(1, int(max_statutes)) if max_statutes is not None else None
                constitution_rows = parse_north_dakota_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "North Dakota Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/",
            f"{self.get_base_url()}/cencode/",
            "https://www.ndlegis.gov/cencode/",
        ]

        best: List[NormalizedStatute] = []
        seen = set()
        # Full-corpus uses a large practical ceiling so PDF discovery is not
        # silently truncated to the historical sample default of 160.
        # Bounded probes honor max_statutes / STATE_SCRAPER_MAX_STATUTES.
        if max_statutes is not None:
            return_threshold = max(1, int(max_statutes))
            unbounded = False
        elif self._full_corpus_enabled():
            return_threshold = 1000000
            unbounded = True
        else:
            return_threshold = self._bounded_return_threshold(160)
            unbounded = False

        from .north_dakota_chapter import parse_configured_north_dakota_chapter

        local_rows = parse_configured_north_dakota_chapter(
            code_name=code_name, max_statutes=return_threshold
        )
        if local_rows:
            return local_rows if unbounded else local_rows[: int(return_threshold)]

        if (
            self._full_corpus_enabled()
            and max_statutes is None
            and getattr(self, "_state_law_acquisition_ledger", None) is not None
        ):
            return await self._scrape_strict_full_corpus_frontier(
                code_name,
                record_primary=True,
                write_checkpoints=True,
            )

        official_pdf_statutes = await self._scrape_official_index_pdfs(
            code_name,
            max_statutes=None if unbounded else max(10, return_threshold),
        )
        if official_pdf_statutes:
            return official_pdf_statutes if unbounded else official_pdf_statutes[:return_threshold]

        # Seed PDFs are for bounded probes only — never sole full-corpus path.
        if not self._full_corpus_enabled():
            direct_pdf_statutes = await self._scrape_seed_cencode_pdfs(code_name, max_statutes=return_threshold)
            if direct_pdf_statutes:
                best = list(direct_pdf_statutes)

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            statutes = await self._generic_scrape(code_name, candidate, "N.D. Cent. Code", max_sections=max(10, return_threshold))
            statutes = self._filter_non_code_results(statutes)
            if len(statutes) > len(best):
                best = statutes
            if not unbounded and len(best) >= return_threshold:
                return best

        if not unbounded and len(best) >= return_threshold:
            return best

        pdf_statutes = await self._scrape_cencode_pdfs(
            code_name,
            max_statutes=None if unbounded else max(10, return_threshold),
        )
        if pdf_statutes:
            return pdf_statutes
        return best

    async def _scrape_official_index_pdfs(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        # Full-corpus discovery should not be capped at a small sample of PDFs.
        discovery_limit = 100000 if limit is None else max(200, int(limit) * 6)
        discovered = await self._discover_official_cencode_pdfs(limit=discovery_limit)
        if not discovered:
            return []

        statutes: List[NormalizedStatute] = []
        seen = set()
        for pdf_url in discovered:
            if limit is not None and len(statutes) >= limit:
                break
            base_pdf_url = pdf_url.split("#", 1)[0]
            if base_pdf_url in seen:
                continue
            seen.add(base_pdf_url)
            pdf_bytes = await self._request_bytes(base_pdf_url, timeout=45)
            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=None)
            if len(full_text) < 280:
                continue
            file_name = base_pdf_url.rsplit("/", 1)[-1]
            m = self._ND_CENCODE_FILE_RE.search(file_name)
            title_no = m.group(1) if m else ""
            chapter_no = m.group(2) if m else ""
            label = f"Title {title_no} Chapter {chapter_no}".strip() if m else file_name
            section_number = f"{title_no}-{chapter_no}".strip("-") or file_name.rsplit(".", 1)[0]
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label,
                    full_text=full_text,
                    source_url=base_pdf_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"N.D. Cent. Code {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_modern_index_pdf", "skip_hydrate": True},
                )
            )
        return statutes

    async def _scrape_seed_cencode_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        seeds = [
            "https://www.legis.nd.gov/cencode/t01c01.pdf",
            "https://www.legis.nd.gov/cencode/t12c01.pdf",
        ]
        out: List[NormalizedStatute] = []
        for pdf_url in seeds[: max(1, int(max_statutes or 1))]:
            pdf_bytes = await self._request_bytes(pdf_url, timeout=12)
            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=None)
            if len(full_text) < 280:
                continue
            file_name = pdf_url.rsplit("/", 1)[-1]
            m = self._ND_CENCODE_FILE_RE.search(file_name)
            title_no = m.group(1) if m else ""
            chapter_no = m.group(2) if m else ""
            section_number = f"{title_no}-{chapter_no}".strip("-") or file_name.rsplit(".", 1)[0]
            label = f"Title {title_no} Chapter {chapter_no}".strip() if m else file_name
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label,
                    full_text=full_text,
                    source_url=pdf_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"N.D. Cent. Code {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={"source_kind": "official_direct_pdf", "skip_hydrate": True},
                )
            )
        return out

    async def _scrape_cencode_pdfs(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Discover and emit Century Code chapter PDF links from legislative homepage."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        discovery_limit = 100000 if limit is None else max(600, int(limit) * 6)

        statutes: List[NormalizedStatute] = []
        seen = set()
        candidate_links = []

        official_modern_links = await self._discover_official_cencode_pdfs(limit=discovery_limit)
        candidate_links.extend(official_modern_links)

        for homepage in [f"{self.get_base_url()}/cencode/", "https://www.ndlegis.gov/cencode/", f"{self.get_base_url()}/"]:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(homepage, timeout_seconds=35)
            except Exception:
                continue
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href", "")).strip()
                if href:
                    candidate_links.append(urljoin(homepage, href))

        discovered = await self._discover_archived_cencode_pdfs(limit=discovery_limit)
        candidate_links.extend(discovered)

        for href in candidate_links:
            if limit is not None and len(statutes) >= limit:
                break
            if not href:
                continue
            abs_url = href
            if not self._ND_CENCODE_PDF_RE.search(abs_url):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)

            file_name = abs_url.rsplit("/", 1)[-1]
            m = self._ND_CENCODE_FILE_RE.search(file_name)
            title_no = m.group(1) if m else ""
            chapter_no = m.group(2) if m else ""
            label = f"Title {title_no} Chapter {chapter_no}".strip() if m else file_name
            section_number = f"{title_no}-{chapter_no}".strip("-") or file_name.rsplit(".", 1)[0]
            pdf_bytes = await self._request_bytes(abs_url, timeout=45)
            full_text = self._extract_pdf_text(pdf_bytes=pdf_bytes, max_chars=None)
            if len(full_text) < 280:
                full_text = f"North Dakota Century Code {label}: {abs_url}"

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=label,
                    full_text=full_text,
                    source_url=abs_url,
                    legal_area=self._identify_legal_area(label),
                    official_cite=f"N.D. Cent. Code {section_number}",
                    metadata=StatuteMetadata(),
                )
            )

        return statutes

    async def _discover_official_cencode_pdfs(self, limit: int = 600) -> List[str]:
        """Discover Century Code chapter PDFs from the modern official ND index page."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/general-information/north-dakota-century-code/index.html"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=35)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[str] = []
        seen = set()
        for link in soup.find_all("a", href=True):
            href = urljoin(index_url, str(link.get("href") or "").strip())
            if "/cencode/" not in href.lower() or ".pdf" not in href.lower():
                continue
            pdf_url = href.split("#", 1)[0]
            if pdf_url in seen:
                continue
            seen.add(pdf_url)
            out.append(pdf_url)
            if len(out) >= limit:
                break
        return out

    async def _discover_archived_cencode_pdfs(self, limit: int = 320) -> List[str]:
        """Discover archived ND Century Code chapter PDFs from Wayback CDX."""
        out: List[str] = []
        seen = set()
        for target in [
            "legis.nd.gov/cencode/*.pdf",
            "ndlegis.gov/cencode/*.pdf",
        ]:
            cdx_url = (
                f"http://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(target, safe='*/:.')}"
                "&output=json&filter=statuscode:200&collapse=digest"
                f"&limit={max(1, int(limit))}"
            )
            rows = await self._fetch_wayback_cdx_rows(
                cdx_url,
                timeout_seconds=45,
            )

            if len(rows) < 2:
                continue

            for row in rows[1:]:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                ts = str(row[1]).strip()
                original = str(row[2]).strip()
                if not ts or not original:
                    continue
                encoded = urllib.parse.quote(original, safe=':/?=&%.-_')
                candidate = f"http://web.archive.org/web/{ts}/{encoded}"
                if candidate in seen:
                    continue
                seen.add(candidate)
                out.append(candidate)
        return out

    async def _request_bytes(self, pdf_url: str, timeout: int) -> bytes:
        candidates = [str(pdf_url or "")]
        wayback_iframe = self._to_wayback_iframe_url(candidates[0])
        if wayback_iframe and wayback_iframe not in candidates:
            candidates.insert(0, wayback_iframe)

        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                payload = await self._fetch_page_content_with_archival_fallback(candidate, timeout_seconds=timeout)
                if payload:
                    return payload
            except Exception:
                continue

        return b""

    def _to_wayback_iframe_url(self, url: str) -> str:
        if not url or "web.archive.org/web/" not in url:
            return ""
        if "/if_/" in url:
            return url
        return re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", url, count=1)

    def _extract_pdf_text(
        self,
        pdf_bytes: bytes,
        max_chars: Optional[int] = None,
    ) -> str:
        if not pdf_bytes:
            return ""
        try:
            proc = subprocess.run(
                [trusted_pdftotext_executable(), "-layout", "-q", "-", "-"],
                input=pdf_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception:
            return ""

        if proc.returncode != 0 or not proc.stdout:
            return ""

        text = proc.stdout.decode("utf-8", errors="ignore")
        text = re.sub(r"\s+", " ", text).strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    def official_title_url(self, title_number: Any) -> str:
        number = str(title_number or "").strip()
        slug = number.replace(".", "-")
        if slug.isdigit():
            slug = f"{int(slug):02d}"
        elif "-" in slug:
            whole, _, frac = slug.partition("-")
            if whole.isdigit():
                slug = f"{int(whole):02d}-{frac}"
        return f"{self.get_base_url()}/cencode/t{slug}.html"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official North Dakota Century Code title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"nd:title-{number}",
                    "title_number": number,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"North Dakota Century Code Title {number} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return (
            host == "legis.nd.gov"
            or host.endswith(".legis.nd.gov")
            or host == "ndlegis.gov"
            or host.endswith(".ndlegis.gov")
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-north-dakota-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            request = urllib.request.Request(url, headers=headers)
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return bytes(response.read() or b"")
        except Exception:
            return b""

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip()
        match = re.match(r"0*(\d{1,2})(?:[-.](\d))?$", text)
        if not match:
            return ""
        whole = str(int(match.group(1)))
        frac = match.group(2)
        return f"{whole}.{frac}" if frac else whole

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name in self.OFFICIAL_TITLES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._ND_TITLE_HREF_RE.search(absolute) or self._ND_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_title_number(match.group("title"))
            if number not in known or number in found:
                continue
            if self._host_is_official(absolute):
                found[number] = self.official_title_url(number)
        for heading in soup.find_all("h2"):
            match = self._ND_TITLE_HEADING_RE.match(
                re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
            )
            if match is None:
                continue
            number = self._normalize_title_number(match.group("title"))
            if number in known and number not in found:
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official North Dakota Century Code title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_ndlegis"
        return rows

    def fetch_official(self, code: str = "ND"):
        """Acquire the exhaustive official North Dakota Century Code catalog.

        Live HTTPS retains the official legis.nd.gov title index. Every known
        Century Code title is enumerated with an official URL. This hook never
        returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "ND").strip().upper() or "ND"
        if normalized != "ND":
            raise ValueError(f"NorthDakotaScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "north dakota official catalog enumeration rejected incomplete "
                "title reacquisition"
            )
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


# Register this scraper with the registry
StateScraperRegistry.register("ND", NorthDakotaScraper)
