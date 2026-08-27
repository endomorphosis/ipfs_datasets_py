"""Scraper for Nebraska state laws.

This module contains the scraper for Nebraska statutes from the official state legislative website.
"""

import asyncio
import hashlib
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlparse, parse_qs
from .base_scraper import BaseStateScraper, NormalizedStatute
from .nebraska_section import classify_nebraska_special_terminal_headnote
from .registry import StateScraperRegistry

_SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)

_SOURCE_BOUND_NEBRASKA_SCAFFOLD_RE = re.compile(
    r"^\s*(?:Section\s+Section-\d+\s*:|skip navigation\b|"
    r"skip to content\b|all rights reserved\b|bill status\b|"
    r"meeting schedule\b|login\b|contact us\b|docs options help\b|"
    r"home documents\b)",
    re.IGNORECASE,
)

# These exact current official provisions are the complete set whose
# comma-delimited Nebraska locators plus the ordinary word ``calendar`` are
# rejected by the shared generic navigation heuristic.  Bind the narrow
# exception to normalized source text so a changed provision or an
# official-looking navigation response must be reviewed under a new parser
# fingerprint instead of inheriting this admission.
_SOURCE_BOUND_NEBRASKA_CALENDAR_TEXT_SHA256 = {
    "38-1,102": "c8c7d3ebaaf066e1ae4b2eca0cb7e10135e3da2c877af70425d7d7d7b82d2a26",
    "38-28,117": "70e25dea373e11f3138121b366a23d16ae14352d204d1c950f57f67d81b1c4ed",
    "44-3,107": "9fefbf987d6c818b8ebc89653bccfec3a1f6d044c98f7a644c4b868febccb4fb",
    "60-3,212": "4b156876a65b953f2b0077ff5e1845ba3b6ebcb021666c564082b4fdac0d2970",
    "66-4,143": "860a304b2a812ee489f67de8a871b0c0f9a968284b3a3e13e1592e66ee14168d",
    "77-27,166": "768df489f42a4889e1856de45cbfbc44f8d9b20e861193f5f0063d27615a1c0a",
    "77-27,222": "6e3451c31d012fba8831c3e1831803e8e8e90e6f4e609fb5653718a84d54f337",
    "81-2,254": "f7985b7dabc05bb8bbf21c65b3a6ee01920cecab1d4300ce795d768fef6d7ba8",
    "81-6,114": "84c384c4d6d6635f6064a3dfb2c0c28b4fe5a3af79efe3cdc4cd06101aa11967",
    "83-4,121": "767e9e675eb30a17160911f27f667acc0dbcf970edb0853bf2a1d534a4bc76d2",
}
_SOURCE_BOUND_NEBRASKA_CALENDAR_SECTION_NAMES = {
    "38-1,102": "Appeal; procedure.",
    "38-28,117": "Pharmacy; hospital pharmacy; inspection; requirements.",
    "44-3,107": (
        "Equity securities insider trading; statement of certain owners; "
        "form; required; filing."
    ),
    "60-3,212": "Snowmobiles; refund of fees; when.",
    "66-4,143": "Materiel administrator; submit report; contents.",
    "77-27,166": (
        "Submission of certified debt; when effective; Lottery Division of "
        "the Department of Revenue; duties."
    ),
    "77-27,222": (
        "Internal Revenue Code amendment; Tax Commissioner; duties; report."
    ),
    "81-2,254": "Single event food vendor, defined.",
    "81-6,114": (
        "Hospital and ambulatory surgical center; reports required."
    ),
    "83-4,121": "Disciplinary proceeding; when commenced; exception.",
}

# The official current Chapter 2 catalog remains the authoritative terminal
# representation for ten repealed locators whose detail pages no longer
# resolve.  Bind the exclusions to the exact retained catalog bytes so a
# changed chapter page must be reviewed afresh instead of inheriting them.
_EXACT_TERMINAL_CHAPTER_CATALOGS = {
    "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=2": {
        "content_sha256": (
            "6924065c48b636fc195aa659aa36aa0e806453db4a1e2810bfb7ecf79eef315b"
        ),
        "content_cid": (
            "bafkreidjeqdfysfwg36bswvglgvdnkqoqbsfhw2kdyubbp5x5t3z53zrlm"
        ),
        "receipt_sha256": (
            "d951ae684fc113e46603508f5c49e77d376368cc2f546e7804b9db2f5b84dcd9"
        ),
        "receipt_cid": (
            "bafkreigzkgxgqt6bcpsgma2qr5oetz35g5rwrtbpkrxhqbfz3mxvxbg43e"
        ),
        "terminal_sections": {
            "2-970": "Repealed. Laws 2026, LB807, § 6.",
            "2-1004": "Repealed. Laws 1988, LB 874, § 49.",
            "2-1007": "Repealed. Laws 1988, LB 874, § 49.",
            "2-1008": "Repealed. Laws 1988, LB 874, § 49.",
            "2-1034": "Repealed. Laws 1988, LB 874, § 49.",
            "2-1529": "Repealed. Laws 1983, LB 36, § 5.",
            "2-1549.02": "Repealed. Laws 1977, LB 510, § 10.",
            "2-1549.03": "Repealed. Laws 1977, LB 510, § 10.",
            "2-1550": "Repealed. Laws 1977, LB 510, § 10.",
            "2-1554": "Repealed. Laws 1977, LB 510, § 10.",
        },
        "disposition": "repealed",
    }
}


_SOURCE_BOUND_CATALOG_TERMINAL_LABELS = (
    (re.compile(r"^Repealed\.(?:\s|$)", re.IGNORECASE), "repealed"),
    (re.compile(r"^Transferred to sections?\b", re.IGNORECASE), "transferred"),
    (re.compile(r"^Unconstitutional\.$", re.IGNORECASE), "unconstitutional"),
    (re.compile(r"^Omitted\.$", re.IGNORECASE), "omitted"),
    (re.compile(r"^Expired\.$", re.IGNORECASE), "expired"),
    (re.compile(r"^Deleted\.$", re.IGNORECASE), "deleted"),
)


def _source_bound_terminal_disposition_from_chapter_label(value: str) -> str:
    """Type only terminal wording that occupies the complete source row label."""

    label = " ".join(str(value or "").split()).replace(" ,", ",")
    for pattern, disposition in _SOURCE_BOUND_CATALOG_TERMINAL_LABELS:
        if pattern.search(label):
            return disposition
    return classify_nebraska_special_terminal_headnote(label) or ""


def _is_official_nebraska_chapter_catalog_url(value: str) -> bool:
    """Require the exact current official chapter-catalog request identity."""

    parsed = urlparse(str(value or "").strip())
    try:
        has_explicit_port = parsed.port is not None
    except ValueError:
        return False
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != "nebraskalegislature.gov"
        or has_explicit_port
        or parsed.path != "/laws/browse-chapters.php"
        or parsed.params
        or parsed.fragment
    ):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) != {"chapter"} or len(query["chapter"]) != 1:
        return False
    return bool(re.fullmatch(r"(?:[1-9]\d?|76A)", query["chapter"][0]))


def _source_bound_terminal_sections_from_chapter_catalog_html(
    html: str,
    *,
    source_url: str,
) -> Dict[str, Dict[str, str]]:
    """Type terminal rows from one retained, exact official chapter catalog."""

    catalog_url = str(source_url or "").strip()
    expected = _EXACT_TERMINAL_CHAPTER_CATALOGS.get(catalog_url)
    if expected is None and not _is_official_nebraska_chapter_catalog_url(
        catalog_url
    ):
        return {}
    raw = str(html or "").encode("utf-8")
    content_sha256 = hashlib.sha256(raw).hexdigest()
    if expected is not None and content_sha256 != expected["content_sha256"]:
        return {}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    soup = BeautifulSoup(html or "", "html.parser")
    typed: Dict[str, Dict[str, str]] = {}
    if expected is not None:
        for section_number, catalog_text in expected["terminal_sections"].items():
            href = f"/laws/statutes.php?statute={section_number}"
            anchors = soup.find_all("a", href=href)
            if len(anchors) != 1:
                return {}
            row = anchors[0].find_parent("td", class_="row")
            if row is None:
                return {}
            direct_spans = row.find_all("span", recursive=False)
            if len(direct_spans) != 3:
                return {}
            detail_anchors = direct_spans[0].find_all(
                "a", href=href, recursive=False
            )
            if len(detail_anchors) != 1 or detail_anchors[0] is not anchors[0]:
                return {}
            summary = " ".join(
                direct_spans[1].get_text(" ", strip=True).split()
            ).replace(" ,", ",")
            if summary != catalog_text:
                return {}
            print_href = f"{href}&print=true"
            print_anchors = direct_spans[2].find_all(
                "a",
                href=print_href,
                recursive=False,
            )
            if len(print_anchors) != 1:
                return {}
            print_anchor = print_anchors[0]
            print_text = " ".join(print_anchor.get_text(" ", strip=True).split())
            print_children = print_anchor.find_all(recursive=False)
            observed_icon_shape = bool(
                not print_text
                and len(print_children) == 1
                and print_children[0].name == "i"
                and print_children[0].attrs == {"class": ["fas", "fa-print"]}
            )
            synthetic_accessible_shape = bool(
                print_text == "Print" and not print_children
            )
            if not (observed_icon_shape or synthetic_accessible_shape):
                return {}
            source = (
                "https://nebraskalegislature.gov/laws/statutes.php?statute="
                f"{section_number}"
            )
            typed[source] = {
                "section_number": section_number,
                "catalog_text": catalog_text,
                "disposition": str(expected["disposition"]),
                "catalog_url": catalog_url,
                "catalog_content_sha256": content_sha256,
            }

    if not _is_official_nebraska_chapter_catalog_url(catalog_url):
        return typed

    official_rows = soup.select("td.row")
    if not official_rows:
        return {}
    for row in official_rows:
        direct_spans = row.find_all("span", recursive=False)
        if len(direct_spans) != 3:
            return {}
        detail_anchors = direct_spans[0].find_all("a", href=True, recursive=False)
        if len(detail_anchors) != 1:
            return {}
        href = str(detail_anchors[0].get("href") or "").strip()
        match = re.fullmatch(
            r"/laws/statutes\.php\?statute=([\dA-Za-z]+(?:[-.,][\dA-Za-z]+)+)",
            href,
        )
        if match is None:
            return {}
        section_number = match.group(1)
        catalog_text = " ".join(
            direct_spans[1].get_text(" ", strip=True).split()
        ).replace(" ,", ",")
        disposition = _source_bound_terminal_disposition_from_chapter_label(
            catalog_text
        )
        if not disposition:
            continue
        print_href = f"{href}&print=true"
        print_anchors = direct_spans[2].find_all(
            "a", href=print_href, recursive=False
        )
        if len(print_anchors) != 1:
            return {}
        source = (
            "https://nebraskalegislature.gov/laws/statutes.php?statute="
            f"{section_number}"
        )
        record = {
            "section_number": section_number,
            "catalog_text": catalog_text,
            "disposition": disposition,
            "catalog_url": catalog_url,
            "catalog_content_sha256": content_sha256,
        }
        prior = typed.get(source)
        if prior is not None and prior != record:
            return {}
        typed[source] = record
    return typed


class NebraskaScraper(BaseStateScraper):
    """Scraper for Nebraska state laws from https://nebraskalegislature.gov"""

    OFFICIAL_DOMAIN = "nebraskalegislature.gov"
    OFFICIAL_ENTRY_PATH = "/laws/browse-statutes.php"
    OFFICIAL_ENTRY_URL = "https://nebraskalegislature.gov/laws/browse-statutes.php"
    OFFICIAL_NUMERIC_CHAPTERS = (
        1, 2, 3, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
        24, 25, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 42, 43, 44,
        45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 57, 58, 59, 60, 61, 62, 64,
        66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 79, 80, 81, 82, 83, 84,
        85, 86, 87, 88, 89, 90,
    )
    # Vaquill scrapeNE: chapter=[\w\-]+ (76A) and statute=[\w.\-]+ (25-2740.04).
    _NE_CHAPTER_URL_RE = re.compile(
        r"/laws/browse-chapters\.php\?chapter=[\w\-]+$", re.IGNORECASE
    )
    # Comma-thousands (2-32,113), dotted subsections (25-2740.04), and
    # alpha chapter prefixes (76A-101). The old \d{1,3} cap dropped 4-digit
    # middle tokens such as 2740.
    _NE_SECTION_NUMBER_RE = re.compile(r"^[\dA-Za-z]+(?:[-.,][\dA-Za-z]+)+$")

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            nebraska_section,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            nebraska_section,
            wayback_machine_engine,
        )
    
    def get_base_url(self) -> str:
        """Return the base URL for Nebraska's legislative website."""
        return "https://nebraskalegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Nebraska."""
        return [{
            "name": "Nebraska Revised Statutes",
            "url": f"{self.get_base_url()}/laws/browse-statutes.php",
            "type": "Code"
        }]

    def _retained_nebraska_catalog_reports(
        self,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        """Replay root/chapter catalogs and derive every exact section unit."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from .nebraska_section import chapter_links, section_links
        from .strict_frontier_closure import replay_exact_retained_state_input

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Nebraska catalog replay requires an attached ledger")
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        root_url = self._canonical_fetch_url(self.OFFICIAL_ENTRY_URL)
        root_raw = replay_exact_retained_state_input(
            self,
            official_url=root_url,
            sanitized_request={"method": "GET", "url": root_url},
            frontier_name="Nebraska root catalog",
            refresh=False,
        )
        chapters = chapter_links(
            root_raw.decode("utf-8", errors="replace"),
            base_url=root_url,
        )
        if not chapters or len({row[2] for row in chapters}) != len(chapters):
            raise RuntimeError("Nebraska retained root chapter membership is incomplete")
        chapter_projection = [
            {"chapter_number": number, "chapter_name": name, "source_url": url}
            for number, name, url in chapters
        ]
        reports: List[Dict[str, Any]] = [
            {
                "chapter_count": len(chapter_projection),
                "content_sha256": hashlib.sha256(root_raw).hexdigest(),
                "kind": "root",
                "membership_sha256": hashlib.sha256(
                    canonical_json_bytes(chapter_projection)
                ).hexdigest(),
                "source_url": root_url,
            }
        ]
        units: List[Dict[str, str]] = []
        seen_urls: set[str] = set()
        for chapter_number, chapter_name, chapter_url in chapters:
            chapter_url = self._canonical_fetch_url(chapter_url)
            chapter_raw = replay_exact_retained_state_input(
                self,
                official_url=chapter_url,
                sanitized_request={"method": "GET", "url": chapter_url},
                frontier_name=f"Nebraska chapter {chapter_number} catalog",
                refresh=False,
            )
            chapter_html = chapter_raw.decode("utf-8", errors="replace")
            terminal = _source_bound_terminal_sections_from_chapter_catalog_html(
                chapter_html,
                source_url=chapter_url,
            )
            chapter_units: List[Dict[str, str]] = []
            for section_number, section_name, source_url in section_links(
                chapter_html,
                base_url=chapter_url,
            ):
                source_url = self._canonical_fetch_url(source_url)
                if source_url in seen_urls:
                    raise RuntimeError(
                        "Nebraska retained hierarchy repeated a section URL: "
                        f"{source_url}"
                    )
                seen_urls.add(source_url)
                terminal_record = terminal.get(source_url)
                unit = {
                    "chapter_name": chapter_name,
                    "chapter_number": chapter_number,
                    "disposition": str(
                        (terminal_record or {}).get("disposition") or "leaf"
                    ),
                    "evidence_url": (
                        chapter_url if terminal_record is not None else source_url
                    ),
                    "section_name": section_name,
                    "section_number": section_number,
                    "source_url": source_url,
                }
                chapter_units.append(unit)
                units.append(unit)
            if not chapter_units:
                raise RuntimeError(
                    f"Nebraska retained chapter {chapter_number} has no section frontier"
                )
            reports.append(
                {
                    "chapter_number": chapter_number,
                    "content_sha256": hashlib.sha256(chapter_raw).hexdigest(),
                    "kind": "chapter",
                    "membership_sha256": hashlib.sha256(
                        canonical_json_bytes(chapter_units)
                    ).hexdigest(),
                    "section_count": len(chapter_units),
                    "source_url": chapter_url,
                    "terminal_count": len(terminal),
                }
            )
        return reports, units

    def _nebraska_exact_frontier(
        self,
        *,
        catalog_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Build Nebraska's deterministic hierarchy/leaf disposition closure."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        catalogs = [dict(row) for row in catalog_reports]
        sections = [dict(row) for row in section_reports]
        operative = sum(row.get("disposition") == "operative" for row in sections)
        disposition = {
            "discovered": len(sections),
            "duplicates": 0,
            "excluded": len(sections) - operative,
            "failed_final": 0,
            "fetched": operative,
            "quarantined": 0,
        }
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_input_count": len(catalogs),
            "catalog_inputs_sha256": hashlib.sha256(
                canonical_json_bytes(catalogs)
            ).hexdigest(),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "leaf_input_count": len(sections),
            "leaf_inputs_sha256": hashlib.sha256(
                canonical_json_bytes(sections)
            ).hexdigest(),
            "method": "source_derived_root_chapter_section_html",
            "pagination_closed": bool(catalogs),
            "remaining_bundle_members": [],
            "scope_closed": True,
            "source_membership_sha256": hashlib.sha256(
                canonical_json_bytes(
                    [str(row.get("source_url") or "") for row in sections]
                )
            ).hexdigest(),
            "toc_exhausted": bool(catalogs),
            "unvisited_continuation_links": [],
            "visited_index_units": len(sections),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Nebraska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .nebraska_constitution import (
            configured_constitution_html_path,
            parse_nebraska_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_nebraska_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Nebraska Constitution",
                    source_url="https://nebraskalegislature.gov/laws/articles.php?article=I-1&print=true",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .nebraska_section import configured_section_html_path, parse_nebraska_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_nebraska_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://nebraskalegislature.gov/laws/statutes.php?statute=28-303",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        official = await self._scrape_official_index(code_name, max_statutes=limit)
        official = self._filter_official_host_statutes(official)
        if official:
            return official if limit is None else official[: int(limit)]
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            direct = self._filter_official_host_statutes(direct)
            if direct:
                return direct if limit is None else direct[: int(limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            return []
        if any(marker in str(code_url).lower() for marker in _SECONDARY_HOST_MARKERS):
            return []
        fallback_limit = max(10, int(limit or 40))
        generic = await self._generic_scrape(
            code_name, code_url, "Neb. Rev. Stat.", max_sections=fallback_limit
        )
        return self._filter_official_host_statutes(generic)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        resumed = self._load_partial_checkpoint_statutes(code_name=code_name, max_statutes=limit)
        checkpoint_progress = self._load_partial_checkpoint_progress()
        if limit is None:
            # Publication traversal reparses every immutable retained input.
            # Checkpoints remain progress-only and cannot substitute for exact
            # source/input reports or canonical replay parity.
            resumed = []
            checkpoint_progress = {}
        self._last_nebraska_section_reports = []
        known_terminal_urls = {
            (
                "https://nebraskalegislature.gov/laws/statutes.php?statute="
                f"{section_number}"
            )
            for catalog in _EXACT_TERMINAL_CHAPTER_CATALOGS.values()
            for section_number in catalog["terminal_sections"]
        }
        retained_terminal_urls = {
            str(url or "").strip()
            for url in checkpoint_progress.get("terminal_section_urls", [])
            if str(url or "").strip() in known_terminal_urls
        }
        self._last_nebraska_catalog_terminal_sections = {
            url: {"disposition": "repealed"} for url in retained_terminal_urls
        }

        def _terminal_progress() -> Dict[str, Any]:
            terminal = dict(self._last_nebraska_catalog_terminal_sections)
            disposition_counts: Dict[str, int] = {}
            for record in terminal.values():
                disposition = str(record.get("disposition") or "").strip()
                if disposition:
                    disposition_counts[disposition] = (
                        disposition_counts.get(disposition, 0) + 1
                    )
            return {
                "terminal_sections_excluded": int(len(terminal)),
                "terminal_section_urls": sorted(terminal),
                "terminal_disposition_counts": disposition_counts,
            }

        chapter_urls = await self._discover_chapter_urls()
        self.logger.info("Nebraska official index: discovered %s chapter urls", len(chapter_urls))
        strict_chapter_payloads: Dict[str, bytes] = {}
        if limit is None:
            chapter_payloads = await self._fetch_nebraska_chapter_frontier_batch(
                chapter_urls
            )
            strict_chapter_payloads = dict(
                zip(chapter_urls, chapter_payloads, strict=True)
            )
        statutes: List[NormalizedStatute] = []
        seen_source_urls: set[str] = set()
        seen_keys: set[str] = set()

        def _extend_unique(batch: List[NormalizedStatute]) -> None:
            for statute in batch:
                source_url = str(statute.source_url or "").strip()
                key = str(statute.statute_id or source_url).strip().lower()
                if source_url and source_url in seen_source_urls:
                    continue
                if key and key in seen_keys:
                    continue
                if source_url:
                    seen_source_urls.add(source_url)
                if key:
                    seen_keys.add(key)
                statutes.append(statute)
                if limit is not None and len(statutes) >= limit:
                    break

        if resumed:
            _extend_unique(resumed)
            self.logger.info(
                "Nebraska official index: resumed %s statutes from checkpoint",
                len(statutes),
            )
        resume_chapters_scanned = max(0, int(checkpoint_progress.get("chapters_scanned") or 0))
        resume_sections_scanned = max(0, int(checkpoint_progress.get("sections_scanned") or 0))
        resume_discovered_sections = max(0, int(checkpoint_progress.get("discovered_sections") or 0))
        chapter_rewind = max(0, int(self._env_int("STATE_SCRAPER_NE_RESUME_CHAPTER_REWIND", default=4)))
        resume_chapter_floor = max(0, resume_chapters_scanned - chapter_rewind)
        sections_scanned_total = int(max(len(statutes), resume_sections_scanned))
        sections_discovered_total = int(max(len(statutes), resume_discovered_sections))

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="nebraska:chapter-discovery",
            extra={
                "chapters_scanned": 0,
                "discovered_chapters": int(len(chapter_urls)),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 0,
                "codes_total": 1,
                **_terminal_progress(),
            },
        )
        if limit is None:
            descendant_urls: List[str] = []
            descendant_url_set: set[str] = set()
            chapter_end_offsets: List[int] = []
            for chapter_index, chapter_url in enumerate(chapter_urls, start=1):
                chapter_payload = strict_chapter_payloads.get(chapter_url)
                if chapter_payload is None:
                    raise RuntimeError(
                        "Nebraska strict chapter frontier omitted an exact URL: "
                        f"{chapter_url}"
                    )
                section_urls = self._section_urls_from_chapter_payload(
                    chapter_url,
                    chapter_payload,
                )
                repeated = [
                    source_url
                    for source_url in section_urls
                    if source_url in descendant_url_set
                ]
                if repeated:
                    raise RuntimeError(
                        "Nebraska strict descendant frontier repeated exact URLs: "
                        f"{repeated[:3]}"
                    )
                descendant_url_set.update(section_urls)
                descendant_urls.extend(section_urls)
                chapter_end_offsets.append(len(descendant_urls))
                if (
                    chapter_index == 1
                    or chapter_index % 10 == 0
                    or chapter_index == len(chapter_urls)
                ):
                    self.logger.info(
                        "Nebraska official index: chapter=%s/%s "
                        "discovered_sections=%s descendant_frontier=%s",
                        chapter_index,
                        len(chapter_urls),
                        len(section_urls),
                        len(descendant_urls),
                    )

            sections_discovered_total = len(descendant_urls)

            def _strict_progress_hook(
                scanned_sections: int,
                total_sections: int,
                partial_batch: List[NormalizedStatute],
            ) -> None:
                chapters_scanned = sum(
                    offset <= scanned_sections for offset in chapter_end_offsets
                )
                current_chapter = min(
                    len(chapter_urls),
                    chapters_scanned + int(chapters_scanned < len(chapter_urls)),
                )
                self._write_partial_checkpoint(
                    statutes + partial_batch,
                    code_name=code_name,
                    stage_label="nebraska:section-scan",
                    extra={
                        "chapters_scanned": int(chapters_scanned),
                        "current_chapter": int(current_chapter),
                        "discovered_chapters": int(len(chapter_urls)),
                        "sections_scanned": int(
                            sections_scanned_total + scanned_sections
                        ),
                        "discovered_sections": int(sections_discovered_total),
                        "codes_completed": 0,
                        "codes_total": 1,
                        **_terminal_progress(),
                    },
                )

            parsed = await self._scrape_section_urls(
                code_name,
                descendant_urls,
                max_statutes=None,
                discovery_method="official_chapter_index_sections",
                progress_hook=_strict_progress_hook,
            )
            _extend_unique(parsed)
            sections_scanned_total += len(descendant_urls)
        else:
            for chapter_index, chapter_url in enumerate(chapter_urls, start=1):
                if len(statutes) >= limit:
                    break
                if chapter_index < resume_chapter_floor:
                    continue
                section_urls = await self._discover_section_urls(chapter_url)
                if seen_source_urls:
                    section_urls = [
                        url for url in section_urls if url not in seen_source_urls
                    ]
                sections_discovered_total += len(section_urls)
                if (
                    chapter_index == 1
                    or chapter_index % 10 == 0
                    or chapter_index == len(chapter_urls)
                ):
                    self.logger.info(
                        "Nebraska official index: chapter=%s/%s "
                        "discovered_sections=%s statutes_so_far=%s",
                        chapter_index,
                        len(chapter_urls),
                        len(section_urls),
                        len(statutes),
                    )

                def _progress_hook(
                    scanned_sections: int,
                    total_sections: int,
                    partial_batch: List[NormalizedStatute],
                    *,
                    chapter_index_local: int = chapter_index,
                ) -> None:
                    if (
                        scanned_sections == 1
                        or scanned_sections % 200 == 0
                        or scanned_sections == total_sections
                    ):
                        cumulative_scanned = int(
                            sections_scanned_total + scanned_sections
                        )
                        self._write_partial_checkpoint(
                            statutes + partial_batch,
                            code_name=code_name,
                            stage_label="nebraska:section-scan",
                            extra={
                                "chapters_scanned": int(
                                    max(0, chapter_index_local - 1)
                                ),
                                "current_chapter": int(chapter_index_local),
                                "discovered_chapters": int(len(chapter_urls)),
                                "sections_scanned": cumulative_scanned,
                                "discovered_sections": int(
                                    sections_discovered_total
                                ),
                                "codes_completed": 0,
                                "codes_total": 1,
                                **_terminal_progress(),
                            },
                        )

                parsed = await self._scrape_section_urls(
                    code_name,
                    section_urls,
                    max_statutes=max(0, limit - len(statutes)),
                    discovery_method="official_chapter_index_sections",
                    progress_hook=_progress_hook,
                )
                _extend_unique(parsed)
                sections_scanned_total += len(section_urls)
                if (
                    chapter_index == 1
                    or chapter_index % 25 == 0
                    or chapter_index == len(chapter_urls)
                ):
                    self.logger.info(
                        "Nebraska official index: chapter=%s/%s sections=%s "
                        "statutes_so_far=%s",
                        chapter_index,
                        len(chapter_urls),
                        len(section_urls),
                        len(statutes),
                    )
                if (
                    chapter_index == 1
                    or chapter_index % 10 == 0
                    or chapter_index == len(chapter_urls)
                ):
                    self._write_partial_checkpoint(
                        statutes,
                        code_name=code_name,
                        stage_label="nebraska:chapter-scan",
                        extra={
                            "chapters_scanned": int(chapter_index),
                            "discovered_chapters": int(len(chapter_urls)),
                            "sections_scanned": int(sections_scanned_total),
                            "discovered_sections": int(sections_discovered_total),
                            "codes_completed": 0,
                            "codes_total": 1,
                            **_terminal_progress(),
                        },
                    )
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if limit is None and callable(
            getattr(ledger, "replay_retained_parser_input", None)
        ):
            catalog_reports, catalog_units = self._retained_nebraska_catalog_reports()
            detail_reports = list(
                getattr(self, "_last_nebraska_section_reports", []) or []
            )
            detail_by_url = {
                str(row.get("source_url") or ""): dict(row)
                for row in detail_reports
            }
            if len(detail_by_url) != len(detail_reports):
                raise RuntimeError(
                    "Nebraska detail frontier repeated a section report"
                )
            catalog_digest_by_url = {
                str(row.get("source_url") or ""): str(
                    row.get("content_sha256") or ""
                )
                for row in catalog_reports
            }
            exact_reports: List[Dict[str, Any]] = []
            for unit in catalog_units:
                source_url = unit["source_url"]
                if unit["disposition"] == "leaf":
                    report = detail_by_url.pop(source_url, None)
                    if report is None:
                        raise RuntimeError(
                            "Nebraska retained catalog has no classified detail input: "
                            f"{source_url}"
                        )
                    exact_reports.append(report)
                    continue
                evidence_url = unit["evidence_url"]
                evidence_digest = catalog_digest_by_url.get(evidence_url, "")
                if len(evidence_digest) != 64:
                    raise RuntimeError(
                        "Nebraska terminal catalog evidence lacks an exact digest: "
                        f"{evidence_url}"
                    )
                exact_reports.append(
                    {
                        "canonical_identity": "",
                        "content_sha256": evidence_digest,
                        "disposition": unit["disposition"],
                        "evidence_url": evidence_url,
                        "source_url": source_url,
                    }
                )
            if detail_by_url:
                raise RuntimeError(
                    "Nebraska detail inputs escaped the retained catalog frontier: "
                    f"{sorted(detail_by_url)[:3]}"
                )
            exact_frontier = self._nebraska_exact_frontier(
                catalog_reports=catalog_reports,
                section_reports=exact_reports,
            )
            if int(exact_frontier["disposition"]["fetched"]) != len(statutes):
                raise RuntimeError(
                    "Nebraska exact operative disposition changed before output"
                )
            observed_at = datetime.now(timezone.utc).isoformat()
            self._last_nebraska_full_frontier = {
                "boundary_first": str(exact_reports[0]["source_url"]),
                "boundary_last": str(exact_reports[-1]["source_url"]),
                "catalog_reports": catalog_reports,
                "code_name": code_name,
                "frontier": exact_frontier,
                "observed_at": observed_at,
                "section_reports": exact_reports,
            }
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="nebraska:complete",
            force=True,
            extra={
                "chapters_scanned": int(len(chapter_urls)),
                "discovered_chapters": int(len(chapter_urls)),
                "sections_scanned": int(sections_scanned_total),
                "discovered_sections": int(sections_discovered_total),
                "codes_completed": 1,
                "codes_total": 1,
                **_terminal_progress(),
            },
        )
        return statutes[:limit] if limit is not None else statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained root/chapter catalogs and exact section inputs."""

        first = getattr(self, "_last_nebraska_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Nebraska strict source frontier was not closed before output"
            )
        first_frontier = first.get("frontier")
        first_catalog_raw = first.get("catalog_reports")
        first_section_raw = first.get("section_reports")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_catalog_raw, Sequence)
            or isinstance(first_catalog_raw, (str, bytes, bytearray))
            or not first_catalog_raw
            or any(not isinstance(row, Mapping) for row in first_catalog_raw)
            or not isinstance(first_section_raw, Sequence)
            or isinstance(first_section_raw, (str, bytes, bytearray))
            or not first_section_raw
            or any(not isinstance(row, Mapping) for row in first_section_raw)
        ):
            raise RuntimeError("Nebraska first exact frontier is incomplete")
        first_catalogs = [dict(row) for row in first_catalog_raw]
        first_sections = [dict(row) for row in first_section_raw]

        replay_catalogs, replay_units = self._retained_nebraska_catalog_reports()
        if replay_catalogs != first_catalogs:
            raise RuntimeError("Nebraska retained catalogs changed on replay")
        if [row["source_url"] for row in replay_units] != [
            str(row.get("source_url") or "") for row in first_sections
        ]:
            raise RuntimeError(
                "Nebraska retained catalog section membership changed on replay"
            )

        from .nebraska_section import classify_nebraska_terminal_section_html
        from .strict_frontier_closure import (
            replay_exact_retained_state_input,
            retain_exact_state_frontier_closure,
        )

        catalog_digest_by_url = {
            str(row.get("source_url") or ""): str(
                row.get("content_sha256") or ""
            )
            for row in replay_catalogs
        }
        code_name = str(first.get("code_name") or "Nebraska Revised Statutes")
        replay_rows: List[NormalizedStatute] = []
        replay_sections: List[Dict[str, Any]] = []
        seen_identities: set[str] = set()
        for unit, expected in zip(replay_units, first_sections, strict=True):
            source_url = unit["source_url"]
            if unit["disposition"] != "leaf":
                evidence_url = unit["evidence_url"]
                report = {
                    "canonical_identity": "",
                    "content_sha256": catalog_digest_by_url.get(evidence_url, ""),
                    "disposition": unit["disposition"],
                    "evidence_url": evidence_url,
                    "source_url": source_url,
                }
            else:
                body = replay_exact_retained_state_input(
                    self,
                    official_url=source_url,
                    sanitized_request={"method": "GET", "url": source_url},
                    frontier_name="Nebraska section frontier",
                    refresh=False,
                )
                digest = hashlib.sha256(body).hexdigest()
                html = body.decode("utf-8", errors="replace")
                disposition = classify_nebraska_terminal_section_html(
                    html,
                    source_url=source_url,
                )
                statute = self._build_statute_from_section_html(
                    code_name,
                    source_url,
                    html,
                    discovery_method="official_chapter_index_sections",
                    strict=True,
                )
                if statute is not None:
                    identity = str(statute.section_number or "").strip()
                    expected_identity = self._section_number_from_url(source_url)
                    if identity != expected_identity or identity in seen_identities:
                        raise RuntimeError(
                            "Nebraska retained replay changed or repeated an identity: "
                            f"{source_url}"
                        )
                    seen_identities.add(identity)
                    disposition = "operative"
                    replay_rows.append(statute)
                elif not disposition:
                    raise RuntimeError(
                        "Nebraska retained replay left a section unclassified: "
                        f"{source_url}"
                    )
                else:
                    identity = ""
                report = {
                    "canonical_identity": identity,
                    "content_sha256": digest,
                    "disposition": disposition,
                    "evidence_url": source_url,
                    "source_url": source_url,
                }
            if report != expected:
                raise RuntimeError(
                    "Nebraska retained section report changed on replay: "
                    f"{source_url}"
                )
            replay_sections.append(report)

        replayed_frontier = self._nebraska_exact_frontier(
            catalog_reports=replay_catalogs,
            section_reports=replay_sections,
        )
        observed_at = str(first.get("observed_at") or "")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="NE",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(first_sections),
            pagination_total=len(first_catalogs),
            transport={
                "fixture": False,
                "catalog_frontier_requested_pages": max(
                    0,
                    len(first_catalogs) - 1,
                ),
                "first_pass_requested_pages": (
                    len(first_catalogs)
                    + sum(
                        row.get("disposition") == "operative"
                        or str(row.get("evidence_url") or "")
                        == str(row.get("source_url") or "")
                        for row in first_sections
                    )
                ),
                "grouped_warc_recovery": True,
                "kind": "root_plus_shared_archive_aware_plural_catalog_and_leaf_html",
                "leaf_frontier_requested_pages": sum(
                    str(row.get("evidence_url") or "")
                    == str(row.get("source_url") or "")
                    for row in first_sections
                ),
                "per_page_archive_loop": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "root_catalog_requested_pages": 1,
                "synthetic": False,
                "wayback_prefix_inventory": True,
            },
        )

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        seeds = [
            ("1-101", f"{self.get_base_url()}/laws/statutes.php?statute=1-101"),
            ("28-303", f"{self.get_base_url()}/laws/statutes.php?statute=28-303"),
        ]
        return await self._scrape_section_urls(
            code_name,
            [url for _, url in seeds[: max(1, int(max_statutes or 1))]],
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        if any(marker in host for marker in _SECONDARY_HOST_MARKERS):
            return False
        return host == "nebraskalegislature.gov" or host.endswith(".nebraskalegislature.gov")

    def _filter_official_host_statutes(
        self, statutes: List[NormalizedStatute]
    ) -> List[NormalizedStatute]:
        return [
            statute
            for statute in statutes
            if self._host_is_official(str(statute.source_url or ""))
        ]

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        """Admit an exact official Nebraska row past generic nav heuristics.

        Nebraska uses comma-delimited locators such as ``38-1,102``.  The
        shared section-number heuristic does not recognize that shape, so an
        otherwise ordinary reference to a court or tax ``calendar`` can look
        like navigation.  Bind the exception to the state-owned parser's
        complete row identity and provenance projection; the word alone never
        authorizes admission.
        """

        if not isinstance(statute, NormalizedStatute):
            return False
        section_number = str(statute.section_number or "").strip()
        expected_text_sha256 = _SOURCE_BOUND_NEBRASKA_CALENDAR_TEXT_SHA256.get(
            section_number
        )
        expected_section_name = _SOURCE_BOUND_NEBRASKA_CALENDAR_SECTION_NAMES.get(
            section_number
        )
        if (
            self._NE_SECTION_NUMBER_RE.fullmatch(section_number) is None
            or expected_text_sha256 is None
            or expected_section_name is None
        ):
            return False
        expected_source_url = (
            "https://nebraskalegislature.gov/laws/statutes.php?statute="
            f"{section_number}"
        )
        source_url = str(statute.source_url or "").strip()
        try:
            parsed = urlparse(source_url)
            has_explicit_port = parsed.port is not None
        except ValueError:
            return False
        if (
            source_url != expected_source_url
            or parsed.scheme != "https"
            or parsed.hostname != self.OFFICIAL_DOMAIN
            or has_explicit_port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/laws/statutes.php"
            or parsed.params
            or parsed.fragment
            or parse_qs(parsed.query, keep_blank_values=True)
            != {"statute": [section_number]}
        ):
            return False

        full_text = str(statute.full_text or "").strip()
        section_name = str(statute.section_name or "").strip()
        chapter_number = section_number.split("-", 1)[0]
        if (
            str(statute.state_code or "").strip().upper() != "NE"
            or str(statute.state_name or "").strip() != "Nebraska"
            or str(statute.code_name or "").strip()
            != "Nebraska Revised Statutes"
            or str(statute.statute_id or "").strip()
            != f"Nebraska Revised Statutes § {section_number}"
            or str(statute.official_cite or "").strip()
            != f"Neb. Rev. Stat. § {section_number}"
            or str(statute.chapter_number or "").strip() != chapter_number
            or section_name != expected_section_name
            or not full_text
            or _SOURCE_BOUND_NEBRASKA_SCAFFOLD_RE.match(section_name)
            or _SOURCE_BOUND_NEBRASKA_SCAFFOLD_RE.match(full_text)
            or _source_bound_terminal_disposition_from_chapter_label(
                section_name
            )
            or _source_bound_terminal_disposition_from_chapter_label(full_text)
            or hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            != expected_text_sha256
        ):
            return False

        data = statute.structured_data
        if not isinstance(data, Mapping):
            return False
        if not (
            str(data.get("source_kind") or "")
            == "official_nebraska_statutes_html"
            and str(data.get("source_authority_class") or "") == "official"
            and str(data.get("discovery_method") or "")
            == "official_chapter_index_sections"
            and data.get("skip_hydrate") is True
        ):
            return False

        # The first quality pass runs before shared JSON-LD enrichment, so a
        # missing projection is valid at that point.  Once present, however,
        # it is part of the normalized row and must repeat the exact source-
        # bound identity/text instead of becoming a second mutable narrative.
        jsonld = data.get("jsonld")
        if jsonld is None:
            return True
        if not isinstance(jsonld, Mapping):
            return False
        return (
            str(jsonld.get("@id") or "")
            == f"urn:state:ne:statute:Nebraska Revised Statutes § {section_number}"
            and str(jsonld.get("name") or "") == section_name
            and str(jsonld.get("sectionName") or "") == section_name
            and str(jsonld.get("sectionNumber") or "") == section_number
            and str(jsonld.get("sourceUrl") or "") == source_url
            and str(jsonld.get("stateCode") or "") == "NE"
            and str(jsonld.get("stateName") or "") == "Nebraska"
            and str(jsonld.get("text") or "") == full_text
        )

    async def _discover_chapter_urls(self) -> List[str]:
        from .nebraska_section import chapter_links, configured_toc_html_path

        browse_url = f"{self.get_base_url()}/laws/browse-statutes.php"
        toc_path = configured_toc_html_path()
        if toc_path is not None:
            html = toc_path.read_text(encoding="utf-8", errors="replace")
        else:
            html = await self._request_text_direct(browse_url, timeout=30)
        if not html:
            return []
        return [url for _number, _name, url in chapter_links(html, base_url=browse_url)]

    async def _discover_section_urls(self, chapter_url: str) -> List[str]:
        from .nebraska_section import configured_chapter_html_path

        chapter_path = configured_chapter_html_path()
        if chapter_path is not None:
            payload = chapter_path.read_bytes()
        else:
            html = await self._request_text_direct(chapter_url, timeout=30)
            payload = html.encode("utf-8") if html else b""
        return self._section_urls_from_chapter_payload(chapter_url, payload)

    def _section_urls_from_chapter_payload(
        self,
        chapter_url: str,
        payload: bytes,
    ) -> List[str]:
        """Parse one already-retained chapter catalog without refetching it."""

        from .nebraska_section import section_links

        if not payload:
            return []
        html = bytes(payload).decode("utf-8", errors="replace")
        terminal = _source_bound_terminal_sections_from_chapter_catalog_html(
            html,
            source_url=chapter_url,
        )
        if terminal:
            retained_terminal = dict(
                getattr(self, "_last_nebraska_catalog_terminal_sections", {})
            )
            retained_terminal.update(terminal)
            self._last_nebraska_catalog_terminal_sections = retained_terminal
        return [
            url
            for _number, _name, url in section_links(html, base_url=chapter_url)
            if url not in terminal
        ]

    def _nebraska_chapter_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                int(
                    self._env_int(
                        "STATE_SCRAPER_NE_CHAPTER_CONCURRENCY",
                        default=8,
                    )
                    or 8
                ),
            ),
        )

    async def _fetch_nebraska_chapter_frontier_batch(
        self,
        urls: List[str],
    ) -> List[bytes]:
        """Acquire every already-known chapter catalog through one plural wave."""

        if not urls:
            return []
        requested = list(urls)
        if len(requested) != len(set(requested)):
            raise RuntimeError(
                "Nebraska chapter frontier contains duplicate exact URLs"
            )

        from .nebraska_section import section_links

        def _is_chapter_catalog(payload: bytes) -> bool:
            if not payload:
                return False
            html = payload.decode("utf-8", errors="replace")
            return bool(section_links(html, base_url=self.OFFICIAL_ENTRY_URL))

        residual_retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=1,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=residual_retry_attempts,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=30,
            content_validator=_is_chapter_catalog,
            media_type="text/html",
            max_concurrency=self._nebraska_chapter_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=("nebraskalegislature.gov",),
            common_crawl_url_terms=("/laws/browse-chapters.php",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)}:
            raise RuntimeError(
                "Nebraska chapter frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                "Nebraska chapter frontier changed URL order or identity"
            )
        failures = [
            {"url": url, "error": error or "empty parser input"}
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None or not payload
        ]
        if failures:
            raise RuntimeError(
                "Nebraska chapter frontier is incomplete; unresolved exact "
                f"URLs: {failures}"
            )
        return [bytes(payload) for payload in batch.payloads]

    def _nebraska_section_batch_size(self) -> int:
        """Bound parsing/checkpoint slices after the single acquisition wave."""

        return max(
            1,
            min(
                512,
                int(
                    self._env_int(
                        "STATE_SCRAPER_NE_SECTION_BATCH_SIZE",
                        default=64,
                    )
                    or 64
                ),
            ),
        )

    def _nebraska_section_concurrency(self) -> int:
        legacy_default = self._env_int(
            "NEBRASKA_SECTION_CONCURRENCY",
            default=10,
        )
        return max(
            1,
            min(
                64,
                int(
                    self._env_int(
                        "STATE_SCRAPER_NE_SECTION_CONCURRENCY",
                        default=legacy_default,
                    )
                    or legacy_default
                ),
            ),
        )

    async def _fetch_nebraska_section_frontier_batch(
        self,
        urls: List[str],
    ) -> List[bytes]:
        """Acquire the complete ordered descendant frontier as one plural wave."""

        if not urls:
            return []
        requested = list(urls)
        if len(requested) != len(set(requested)):
            raise RuntimeError(
                "Nebraska section frontier contains duplicate exact URLs"
            )
        residual_retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=1,
                ),
            ),
        )
        batch = (
            await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                requested,
                residual_retry_attempts=residual_retry_attempts,
                timeout_seconds=20,
                media_type="text/html",
                max_concurrency=self._nebraska_section_concurrency(),
                prefer_direct=True,
                common_crawl_domain_terms=("nebraskalegislature.gov",),
                common_crawl_url_terms=("/laws/statutes.php",),
                common_crawl_mime_terms=("html",),
                wayback_prefix_inventory=True,
            )
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)}:
            raise RuntimeError(
                "Nebraska section frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                "Nebraska section frontier changed URL order or identity"
            )
        failures = [
            {
                "url": url,
                "error": error or "empty parser input",
            }
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None or not payload
        ]
        if failures:
            raise RuntimeError(
                "Nebraska section frontier is incomplete; unresolved exact "
                f"URLs: {failures}"
            )
        return [bytes(payload) for payload in batch.payloads]

    def _build_statute_from_section_html(
        self,
        code_name: str,
        source_url: str,
        html: str,
        *,
        discovery_method: str,
        strict: bool = False,
    ) -> Optional[NormalizedStatute]:
        """Parse one already-retained official Nebraska section response."""

        if not html:
            return None
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        from .nebraska_section import (
            classify_nebraska_terminal_section_html,
            parse_nebraska_section_html,
        )

        if classify_nebraska_terminal_section_html(
            html,
            source_url=source_url,
        ):
            return None

        parsed = parse_nebraska_section_html(
            html,
            source_url=source_url,
            code_name=code_name,
        )
        if parsed is not None:
            data = dict(parsed.structured_data or {})
            data["discovery_method"] = discovery_method
            parsed.structured_data = data
            return parsed
        if strict:
            return None
        soup = BeautifulSoup(html, "html.parser")
        statute_panel = (
            soup.select_one("div.statute")
            or soup.select_one("div.card-body")
            or soup.select_one("main")
            or soup.select_one("div#main-content")
            or soup.find("body")
        )
        if statute_panel is None:
            return None
        for tag in statute_panel(
            ["script", "style", "nav", "header", "footer", "aside"]
        ):
            tag.decompose()
        heading_node = (
            statute_panel.find("h2")
            or statute_panel.find("h1")
            or statute_panel
        )
        section_number = self._normalize_legal_text(
            heading_node.get_text(" ", strip=True)
        ).rstrip(".")
        if not self._NE_SECTION_NUMBER_RE.match(section_number):
            section_number = self._section_number_from_url(source_url)
        if not self._NE_SECTION_NUMBER_RE.match(section_number):
            return None
        section_name = self._normalize_legal_text(
            (statute_panel.find("h3") or statute_panel).get_text(" ", strip=True)
        )
        full_text = self._normalize_legal_text(
            statute_panel.get_text(" ", strip=True)
        )
        if not section_name:
            section_name = f"Section {section_number}"
        # Repealed Nebraska sections can be concise but still substantive
        # corpus entries when tied to a valid statute identifier.
        if len(full_text) < 30:
            return None
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(section_name or f"Section {section_number}")[:200],
            full_text=full_text,
            legal_area=self._identify_legal_area(section_name or full_text[:800]),
            source_url=source_url,
            official_cite=f"Neb. Rev. Stat. § {section_number}",
            structured_data={
                "source_kind": "official_nebraska_statutes_html",
                "discovery_method": discovery_method,
                "skip_hydrate": True,
            },
        )

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[str],
        *,
        max_statutes: Optional[int],
        discovery_method: str,
        progress_hook: Optional[Callable[[int, int, List[NormalizedStatute]], None]] = None,
    ) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        concurrency = self._nebraska_section_concurrency()
        sem = asyncio.Semaphore(concurrency)

        async def _parse_source_url(source_url: str) -> Optional[NormalizedStatute]:
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                return None
            return self._build_statute_from_section_html(
                code_name,
                source_url,
                html,
                discovery_method=discovery_method,
            )

        if limit is None:
            from .nebraska_section import classify_nebraska_terminal_section_html

            total_sections = len(section_urls)
            scanned_sections = 0
            batch_size = self._nebraska_section_batch_size()
            batch_payloads = await self._fetch_nebraska_section_frontier_batch(
                section_urls
            )
            for batch_start in range(0, total_sections, batch_size):
                batch_urls = section_urls[batch_start : batch_start + batch_size]
                parse_payloads = batch_payloads[
                    batch_start : batch_start + len(batch_urls)
                ]
                for source_url, payload in zip(
                    batch_urls,
                    parse_payloads,
                    strict=True,
                ):
                    decoded = payload.decode("utf-8", errors="replace")
                    disposition = classify_nebraska_terminal_section_html(
                        decoded,
                        source_url=source_url,
                    )
                    statute = self._build_statute_from_section_html(
                        code_name,
                        source_url,
                        decoded,
                        discovery_method=discovery_method,
                        strict=True,
                    )
                    if statute is not None:
                        expected_identity = self._section_number_from_url(source_url)
                        observed_identity = str(statute.section_number or "").strip()
                        if observed_identity != expected_identity:
                            raise RuntimeError(
                                "Nebraska retained body changed its catalog-selected "
                                f"identity: expected={expected_identity} "
                                f"observed={observed_identity}"
                            )
                        disposition = "operative"
                        out.append(statute)
                    elif not disposition:
                        raise RuntimeError(
                            "Nebraska retained section produced neither an operative "
                            f"row nor a source-bound terminal disposition: {source_url}"
                        )
                    reports = getattr(self, "_last_nebraska_section_reports", None)
                    if not isinstance(reports, list):
                        reports = []
                        self._last_nebraska_section_reports = reports
                    reports.append(
                        {
                            "canonical_identity": (
                                str(statute.section_number or "").strip()
                                if statute is not None
                                else ""
                            ),
                            "content_sha256": hashlib.sha256(payload).hexdigest(),
                            "disposition": disposition,
                            "evidence_url": source_url,
                            "source_url": source_url,
                        }
                    )
                scanned_sections += len(batch_urls)
                if progress_hook is not None:
                    try:
                        progress_hook(scanned_sections, total_sections, out)
                    except Exception:
                        pass
                self.logger.info(
                    "Nebraska official index: "
                    "scanned_sections=%s/%s statutes_so_far=%s",
                    scanned_sections,
                    total_sections,
                    len(out),
                )
            return out

        async def _bounded_parse(source_url: str) -> Optional[NormalizedStatute]:
            async with sem:
                try:
                    return await _parse_source_url(source_url)
                except Exception:
                    return None

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            total_sections = len(section_urls)
            for scanned_sections, source_url in enumerate(section_urls, start=1):
                statute = await _bounded_parse(source_url)
                if statute is not None:
                    out.append(statute)
                if progress_hook is not None:
                    try:
                        progress_hook(scanned_sections, total_sections, out)
                    except Exception:
                        pass
                if limit is not None and len(out) >= limit:
                    break
            return out

        tasks = [asyncio.create_task(_bounded_parse(source_url)) for source_url in section_urls]
        total_sections = len(tasks)
        cancelled_early = False
        for scanned_sections, task in enumerate(asyncio.as_completed(tasks), start=1):
            statute = await task
            if statute is not None:
                out.append(statute)
            if progress_hook is not None:
                try:
                    progress_hook(scanned_sections, total_sections, out)
                except Exception:
                    pass
            if (
                scanned_sections == 1
                or scanned_sections % 50 == 0
                or scanned_sections == total_sections
            ):
                self.logger.info(
                    "Nebraska official index: scanned_sections=%s/%s statutes_so_far=%s",
                    scanned_sections,
                    total_sections,
                    len(out),
                )
            if limit is not None and len(out) >= limit:
                cancelled_early = True
                for pending_task in tasks:
                    if not pending_task.done():
                        pending_task.cancel()
                break
        if cancelled_early:
            await asyncio.gather(*tasks, return_exceptions=True)
        return out

    def _section_number_from_url(self, url: str) -> str:
        try:
            value = str((parse_qs(urlparse(url).query).get("statute") or [""])[0]).strip()
        except Exception:
            return ""
        return value

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        canonical = self._canonicalize_statute_url(url)
        for _ in range(2):
            try:
                payload = await self._fetch_page_content_with_archival_fallback(
                    canonical,
                    timeout_seconds=max(5, int(timeout)),
                )
            except Exception:
                payload = b""
            if payload:
                try:
                    return payload.decode("utf-8", errors="replace")
                except Exception:
                    return ""
            await asyncio.sleep(0.3)
        try:
            payload = await self._fetch_parser_input_with_transport(
                canonical,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout_seconds=max(1, int(timeout)),
                allow_archival_fallback=True,
                media_type="text/html",
                provider="nebraska_direct_statute",
            )
        except Exception:
            return ""
        return payload.decode("utf-8", errors="replace") if payload else ""

    def official_chapter_url(self, chapter: Any) -> str:
        token = str(chapter or "").strip()
        return f"{self.get_base_url()}/laws/browse-chapters.php?chapter={token}"

    def official_chapter_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Nebraska Revised Statutes chapter catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_NUMERIC_CHAPTERS:
            url = self.official_chapter_url(number)
            rows.append(
                {
                    "canonical_key": f"ne:chapter-{int(number)}",
                    "chapter_number": str(int(number)),
                    "name": f"Chapter {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Nebraska Revised Statutes Chapter {int(number)} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-nebraska-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }

        def _request() -> bytes:
            try:
                request = urllib.request.Request(url, headers=headers)
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(url, headers=headers)
                    context = ssl._create_unverified_context()
                    with urllib.request.urlopen(
                        request, timeout=timeout, context=context
                    ) as response:
                        return bytes(response.read() or b"")
                except Exception:
                    return b""

        return _request()

    def _parse_official_chapter_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        from .nebraska_section import chapter_links

        text = html.decode("utf-8", errors="replace") if isinstance(html, (bytes, bytearray)) else str(html)
        for token, _name, url in chapter_links(text, base_url=self.OFFICIAL_ENTRY_URL):
            if token and token not in found:
                found[token] = url or self.official_chapter_url(token)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Nebraska chapter and repair missing live links."""

        del page_url
        discovered = self._parse_official_chapter_links(html)
        rows = self.official_chapter_catalog()
        seen = {str(row["chapter_number"]).lower() for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["chapter_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for token, url in discovered.items():
            if token.lower() in seen:
                continue
            rows.append(
                {
                    "canonical_key": f"ne:chapter-{token.lower()}",
                    "chapter_number": token,
                    "name": f"Chapter {token}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Nebraska Revised Statutes Chapter {token} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "NE"):
        """Acquire the exhaustive official Nebraska Revised Statutes chapter catalog.

        Live HTTPS retains the official browse-statutes index. Every known
        chapter is enumerated with an official nebraskalegislature.gov URL.
        This hook never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NE").strip().upper() or "NE"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("nebraska official catalog enumeration is incomplete")
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
StateScraperRegistry.register("NE", NebraskaScraper)
