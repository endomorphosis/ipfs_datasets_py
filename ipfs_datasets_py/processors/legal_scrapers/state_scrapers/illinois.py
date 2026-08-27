"""Scraper for Illinois state laws.

This module contains the scraper for Illinois statutes from the official
Illinois General Assembly website.
"""

from html import unescape
import hashlib
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class IllinoisScraper(BaseStateScraper):
    """Scraper for Illinois state laws from https://www.ilga.gov."""

    OFFICIAL_DOMAIN = "www.ilga.gov"
    OFFICIAL_ENTRY_PATH = "/Legislation/ILCS/Chapters"
    OFFICIAL_ENTRY_URL = "https://www.ilga.gov/Legislation/ILCS/Chapters"
    _CHAPTER_LINK_RE = re.compile(r"/Legislation/ILCS/Acts\?", re.IGNORECASE)
    _OFFICIAL_CHAPTER_LINK_RE = re.compile(
        r"(?:/Legislation/ILCS/Acts\?|ilcs2\.asp\?|ilcs3\.asp\?)",
        re.IGNORECASE,
    )
    _ACT_LINK_RE = re.compile(r"/Legislation/ILCS/Articles\?", re.IGNORECASE)
    _FULL_ACT_LINK_RE = re.compile(r"/legislation/ILCS/details\?.*ChapAct=FullText", re.IGNORECASE)
    # A small number of official ILCS section identifiers contain their own
    # parenthetical qualifier (for example ``1(Art.III)``).  Keep that one
    # balanced level inside the outer official-citation marker.
    _CITE_RE = re.compile(
        r"\((?P<cite>\d+\s+ILCS\s+(?:[^()]|\([^()]*\))+?)\)"
    )
    _SECTION_CITE_RE = re.compile(
        r"^(?P<chapter>\d+)\s+ILCS\s+"
        r"(?P<act>[^/\s]+(?:/[^/\s]+)*)/"
        r"(?P<section>[^()\s]+(?:\([^()]+\)[^()\s]*)?)$"
    )
    _CHAPTER_LABEL_RE = re.compile(r"CHAPTER\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)
    _CHAPTER_ID_RE = re.compile(r"(?:ChapterID|ChapNum|ChapterNumber)=(\d+[A-Za-z]?)", re.IGNORECASE)
    _REPEALED_ACT_LABEL_RE = re.compile(
        r"\(\s*Repealed\s+by\s+"
        r"(?P<authority>[^()]*(?:\([^()]{1,200}\)[^()]*)*)\s*\)\s*$",
        re.IGNORECASE,
    )
    _MOVED_ACT_LABEL_RE = re.compile(
        r"\(\s*Moved\s+to\s+"
        r"(?P<destination>\d+\s+ILCS\s+[^();]+/)"
        r"(?:\s*;\s*see\s+(?P<authority>[^()]{3,200}))?\s*\)\s*$",
        re.IGNORECASE,
    )
    # ILGA can add a newly enacted Act to the ILCS catalog before its ILCS
    # FullText page has been compiled.  These exact, official mappings are
    # evidence-bound bridges to the enacted Public Act, never generic guesses.
    _PENDING_ILCS_PUBLIC_ACTS: Dict[Tuple[str, str], Dict[str, Any]] = {
        ("18", "4702"): {
            "chapter_number": "110",
            "chap_act": "110 ILCS 193/",
            "act_name": (
                "Higher Education Student Support and Academic Freedom Act."
            ),
            "public_act_number": "104-0768",
            "bill_number": "HB4304",
            "effective_date": "2027-01-01",
            "section_numbers": ("1", "5", "10", "15"),
            "public_act_section_numbers": ("1", "5", "10", "15"),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0768"
            ),
        },
        ("24", "4698"): {
            "chapter_number": "225",
            "chap_act": "225 ILCS 66/",
            "act_name": "Kidney Disease Treatment Delegation Act.",
            "public_act_number": "104-0728",
            "bill_number": "SB3445",
            "effective_date": "2026-07-31",
            "section_numbers": ("1", "2", "5", "10", "15"),
            "public_act_section_numbers": (
                "1",
                "2",
                "5",
                "10",
                "15",
                "20",
                "99",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0728"
            ),
        },
        ("32", "4695"): {
            "chapter_number": "325",
            "chap_act": "325 ILCS 43/",
            "act_name": (
                "Language Equality Acquisition for Deaf, Hard of Hearing, "
                "or DeafBlind Children Act."
            ),
            "public_act_number": "104-0658",
            "bill_number": "HB1783",
            "effective_date": "2026-07-30",
            "section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "30",
                "35",
                "40",
                "90",
            ),
            "public_act_section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "30",
                "35",
                "40",
                "90",
                "99",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0658"
            ),
        },
        ("32", "4696"): {
            "chapter_number": "325",
            "chap_act": "325 ILCS 66/",
            "act_name": "Children's Online Social Media Safety Act.",
            "public_act_number": "104-0664",
            "bill_number": "HB5511",
            "effective_date": "2028-01-01",
            "section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "97",
            ),
            "public_act_section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "97",
                "99",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0664"
            ),
        },
        ("35", "4700"): {
            "chapter_number": "410",
            "chap_act": "410 ILCS 660/",
            "act_name": "Patient Access to Pharmacy Protection Act.",
            "public_act_number": "104-0758",
            "bill_number": "HB2371",
            "effective_date": "2026-08-07",
            "section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "30",
                "35",
                "40",
                "45",
                "97",
            ),
            "public_act_section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "30",
                "35",
                "40",
                "45",
                "97",
                "99",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0758"
            ),
        },
        ("35", "4701"): {
            "chapter_number": "410",
            "chap_act": "410 ILCS 665/",
            "act_name": (
                "340B Transparency, Reporting, and Accountability Act."
            ),
            "public_act_number": "104-0769",
            "bill_number": "HB4327",
            "effective_date": "2026-08-07",
            "section_numbers": ("1", "5", "10", "15", "20", "95"),
            "public_act_section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "95",
                "900",
                "905",
                "999",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0769"
            ),
        },
        ("55", "4699"): {
            "chapter_number": "730",
            "chap_act": "730 ILCS 230/",
            "act_name": (
                "Equitable Access to Education, Employment, and Training for "
                "Incarcerated Individuals with Disabilities Act."
            ),
            "public_act_number": "104-0757",
            "bill_number": "HB1810",
            "effective_date": "2026-08-07",
            "section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "30",
                "35",
            ),
            "public_act_section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "30",
                "35",
                "99",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0757"
            ),
        },
        ("59", "4703"): {
            "chapter_number": "750",
            "chap_act": "750 ILCS 63/",
            "act_name": "Family Justice Centers Act.",
            "public_act_number": "104-0780",
            "bill_number": "HB4949",
            "effective_date": "2027-01-01",
            "section_numbers": ("1", "5", "10", "15"),
            "public_act_section_numbers": ("1", "5", "10", "15"),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0780"
            ),
        },
        ("67", "4697"): {
            "chapter_number": "815",
            "chap_act": "815 ILCS 404/",
            "act_name": "Retail Cash Payment Act.",
            "public_act_number": "104-0665",
            "bill_number": "HB4592",
            "effective_date": "2028-01-01",
            "section_numbers": ("1", "5", "10", "15", "20", "25"),
            "public_act_section_numbers": (
                "1",
                "5",
                "10",
                "15",
                "20",
                "25",
                "99",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0665"
            ),
        },
        ("67", "4694"): {
            "chapter_number": "815",
            "chap_act": "815 ILCS 450/",
            "act_name": "Service Appointment Fairness Act.",
            "public_act_number": "104-0656",
            "bill_number": "SB3066",
            "effective_date": "2027-01-01",
            "section_numbers": ("1", "5", "10", "15"),
            "public_act_section_numbers": ("1", "5", "10", "15", "90"),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0656"
            ),
        },
        ("68", "4704"): {
            "chapter_number": "820",
            "chap_act": "820 ILCS 14/",
            "act_name": "Transportation Network Driver Labor Relations Act.",
            "public_act_number": "104-0788",
            "bill_number": "HB5090",
            "effective_date": "2026-08-07",
            "section_numbers": (
                "1",
                "2",
                "3",
                "4",
                "4.5",
                "5",
                "6",
                "7",
                "8",
                "9",
                "10",
                "11",
                "12",
                "13",
                "14",
                "15",
                "16",
                "17",
                "18",
            ),
            "public_act_section_numbers": (
                "1",
                "2",
                "3",
                "4",
                "4.5",
                "5",
                "6",
                "7",
                "8",
                "9",
                "10",
                "11",
                "12",
                "13",
                "14",
                "15",
                "16",
                "17",
                "18",
                "900",
                "905",
                "908",
                "910",
                "995",
                "997",
                "999",
            ),
            "url": (
                "https://www.ilga.gov/Legislation/PublicActs/View/104-0788"
            ),
            "document_url": (
                "https://www.ilga.gov/documents/legislation/PublicActs/104/"
                "104-0788.htm"
            ),
        },
    }

    def get_base_url(self) -> str:
        """Return the base URL for Illinois's legislative website."""
        return "https://www.ilga.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Illinois."""
        return [
            {
                "name": "Illinois Compiled Statutes",
                "url": f"{self.get_base_url()}/Legislation/ILCS/Chapters",
                "type": "Code",
            }
        ]

    def _scrape_official_bulk_zip(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Read the official ILCS FTP zip when ILLINOIS_BULK_ZIP is set."""

        from .illinois_bulk import configured_bulk_zip_path, parse_illinois_bulk_zip

        zip_path = configured_bulk_zip_path()
        if zip_path is None:
            return []
        try:
            return parse_illinois_bulk_zip(
                zip_path,
                code_name=code_name,
                max_statutes=max_statutes,
            )
        except Exception as exc:
            self.logger.warning("Illinois official bulk zip failed: %s", exc)
            return []

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Illinois statutes through official Chapters -> Acts -> FullText pages."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        from .illinois_constitution import (
            configured_constitution_html_dir,
            configured_constitution_html_path,
            parse_configured_illinois_constitution,
        )

        constitution_path = configured_constitution_html_path()
        constitution_dir = configured_constitution_html_dir()
        if (
            constitution_path is not None
            or constitution_dir is not None
            or "constitution" in str(code_name or "").lower()
        ):
            if constitution_path is not None or constitution_dir is not None:
                constitution_rows = parse_configured_illinois_constitution(
                    code_name=code_name or "Illinois Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        bulk = self._scrape_official_bulk_zip(code_name=code_name, max_statutes=limit)
        if bulk:
            return bulk
        if self._full_corpus_enabled() and limit is None:
            return await self._scrape_strict_full_code(
                code_name=code_name,
                code_url=code_url,
            )
        statutes: List[NormalizedStatute] = []

        chapter_links = await self._discover_chapter_links(code_url)
        self.logger.info("Illinois official index: discovered %s chapter links", len(chapter_links))

        for chapter_index, chapter in enumerate(chapter_links, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            act_links = await self._discover_act_links(chapter["url"])
            self.logger.info(
                "Illinois official index: chapter=%s index=%s/%s acts=%s statutes_so_far=%s",
                chapter.get("chapter_number") or chapter.get("label") or chapter["url"],
                chapter_index,
                len(chapter_links),
                len(act_links),
                len(statutes),
            )

            for act_index, act in enumerate(act_links, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                remaining = None if limit is None else max(0, limit - len(statutes))
                parsed = await self._parse_full_act(
                    code_name=code_name,
                    chapter=chapter,
                    act=act,
                    max_statutes=remaining,
                )
                statutes.extend(parsed)
                if act_index % 50 == 0:
                    self.logger.info(
                        "Illinois official index: chapter=%s acts_processed=%s/%s statutes_so_far=%s",
                        chapter.get("chapter_number") or chapter.get("label") or chapter["url"],
                        act_index,
                        len(act_links),
                        len(statutes),
                    )

        if not statutes:
            self.logger.warning("Illinois official direct crawl returned no statutes; skipping generic recovery fallback")
        return statutes[:limit] if limit is not None else statutes

    async def _fetch_official_il_html(self, url: str, timeout_seconds: int = 20) -> str:
        timeout = max(1, int(timeout_seconds or 20))
        payload = await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-illinois-statutes-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout_seconds=timeout,
            allow_archival_fallback=True,
            media_type="text/html",
            provider="requests_direct",
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    async def _discover_chapter_links(self, code_url: str) -> List[Dict[str, str]]:
        index_url = code_url or f"{self.get_base_url()}/Legislation/ILCS/Chapters"
        html = await self._fetch_official_il_html(index_url)
        if not html:
            return []

        return self._parse_chapter_links_html(html, index_url=index_url)

    def _parse_chapter_links_html(
        self,
        html: str,
        *,
        index_url: str,
    ) -> List[Dict[str, str]]:
        """Parse the ordered chapter frontier from one retained index body."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not self._CHAPTER_LINK_RE.search(href):
                continue
            full_url = self._canonical_ilga_url(urljoin(index_url, href))
            if full_url in seen:
                continue
            seen.add(full_url)
            label = self._clean_label(anchor.get_text(" ", strip=True))
            query = parse_qs(urlparse(full_url).query)
            out.append(
                {
                    "url": full_url,
                    "label": label,
                    "chapter_id": self._first_query(query, "ChapterID"),
                    "chapter_number": self._first_query(query, "ChapterNumber"),
                    "chapter_name": self._first_query(query, "Chapter") or self._chapter_name_from_label(label),
                    "major_topic": self._first_query(query, "MajorTopic"),
                }
            )
        return out

    async def _discover_act_links(self, chapter_url: str) -> List[Dict[str, str]]:
        html = await self._fetch_official_il_html(chapter_url)
        if not html:
            return []

        return self._parse_act_links_html(html, chapter_url=chapter_url)

    def _parse_act_links_html(
        self,
        html: str,
        *,
        chapter_url: str,
        strict: bool = False,
    ) -> List[Dict[str, str]]:
        """Parse the ordered act frontier from one retained chapter body."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            if strict:
                raise RuntimeError(
                    "BeautifulSoup is required for strict Illinois act discovery"
                )
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not self._ACT_LINK_RE.search(href):
                continue
            full_url = self._canonical_ilga_url(urljoin(chapter_url, href))
            if full_url in seen:
                if strict:
                    raise RuntimeError(
                        "official Illinois chapter repeats an act locator: "
                        f"{full_url}"
                    )
                continue
            seen.add(full_url)
            label = self._clean_label(anchor.get_text(" ", strip=True))
            query = parse_qs(urlparse(full_url).query)
            chap_act, act_name = self._split_act_label(label)
            out.append(
                {
                    "url": full_url,
                    "label": label,
                    "act_id": self._first_query(query, "ActID"),
                    "chapter_id": self._first_query(query, "ChapterID"),
                    "chap_act": chap_act,
                    "act_name": act_name,
                }
            )
        return out

    def _fail_illinois_full_frontier(
        self,
        message: str,
        **evidence: Any,
    ) -> None:
        frontier = dict(
            getattr(self, "_last_illinois_full_frontier", {}) or {}
        )
        frontier.update(evidence)
        frontier["closed"] = False
        errors = list(frontier.get("errors") or [])
        errors.append(str(message))
        frontier["errors"] = errors
        self._last_illinois_full_frontier = frontier
        self._last_full_corpus_frontier = frontier
        details = " ".join(
            f"{key}={value}" for key, value in sorted(evidence.items())
        )
        raise RuntimeError(f"{message}{': ' + details if details else ''}")

    @staticmethod
    def _strict_illinois_url(
        url: str,
        *,
        expected_path: str,
        required_query: Sequence[str],
    ) -> Dict[str, List[str]]:
        parsed = urlparse(str(url or "").strip())
        if (
            parsed.scheme.lower() != "https"
            or str(parsed.hostname or "").lower() != "www.ilga.gov"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.fragment
            or parsed.path.casefold() != expected_path.casefold()
        ):
            raise RuntimeError(f"invalid official Illinois locator: {url}")
        query = parse_qs(parsed.query, keep_blank_values=True)
        for key in required_query:
            values = query.get(key) or []
            if len(values) != 1 or not str(values[0]).strip():
                raise RuntimeError(
                    f"official Illinois locator requires one {key}: {url}"
                )
        return query

    def _deterministic_full_act_url(
        self,
        act: Mapping[str, Any],
        *,
        chapter: Optional[Mapping[str, Any]] = None,
        strict: bool = False,
    ) -> str:
        """Derive the FullText locator without fetching the Article page."""

        try:
            article_query = self._strict_illinois_url(
                str(act.get("url") or ""),
                expected_path="/Legislation/ILCS/Articles",
                required_query=("ActID", "ChapterID"),
            )
            act_id = self._first_query(article_query, "ActID")
            chapter_id = self._first_query(article_query, "ChapterID")
            if (
                not re.fullmatch(r"\d+", act_id)
                or not re.fullmatch(r"\d+", chapter_id)
                or str(act.get("act_id") or "").strip() != act_id
                or str(act.get("chapter_id") or "").strip() != chapter_id
            ):
                raise RuntimeError("Article locator identity does not replay")
            if chapter is not None:
                expected_chapter_id = str(
                    chapter.get("chapter_id") or ""
                ).strip()
                if expected_chapter_id != chapter_id:
                    raise RuntimeError(
                        "Article ChapterID does not match its discovered chapter"
                    )
                chapter_number = str(
                    chapter.get("chapter_number") or ""
                ).strip()
                chap_act = self._normalize_legal_text(
                    str(act.get("chap_act") or "")
                ).rstrip("/")
                if (
                    not chapter_number
                    or not chap_act.casefold().startswith(
                        f"{chapter_number} ilcs ".casefold()
                    )
                ):
                    raise RuntimeError(
                        "act citation prefix does not match its discovered chapter"
                    )
        except RuntimeError:
            if strict:
                raise
            return ""

        params = {
            "ActID": act_id,
            "ChapterID": chapter_id,
            "SeqStart": "",
            "ChapAct": "FullText",
        }
        return f"{self.get_base_url()}/legislation/ILCS/details?{urlencode(params)}"

    def _canonical_illinois_transport_receipt(
        self,
        *,
        official_url: str,
        payload: bytes,
        receipt: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        from ...legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            canonicalize_state_law_transport_receipt,
        )

        if not isinstance(receipt, Mapping):
            raise RuntimeError("aligned Illinois transport receipt is missing")
        digest = hashlib.sha256(payload).hexdigest()
        try:
            return canonicalize_state_law_transport_receipt(
                receipt,
                official_url=official_url,
                content_sha256=digest,
            )
        except StateLawTransportReceiptError as exc:
            raise RuntimeError(
                f"aligned Illinois transport receipt was rejected: {exc.code}"
            ) from exc

    async def _fetch_illinois_page_batch(
        self,
        urls: Sequence[str],
        *,
        purpose: str,
        timeout_seconds: int,
        max_concurrency: int,
    ) -> List[Dict[str, Any]]:
        """Fetch one ordered page batch through the shared archive-aware seam."""

        requested = [str(url or "").strip() for url in urls]
        if not requested:
            return []
        if len(set(requested)) != len(requested):
            raise RuntimeError(
                f"Illinois {purpose} batch contains duplicate locators"
            )
        batch = await self._fetch_page_contents_with_archival_fallback(
            requested,
            timeout_seconds=timeout_seconds,
            media_type="text/html",
            max_concurrency=max(1, min(int(max_concurrency), len(requested))),
            prefer_direct=True,
            common_crawl_domain_terms=[self.OFFICIAL_DOMAIN],
            common_crawl_mime_terms=["html"],
        )
        vectors = (
            list(batch.urls),
            list(batch.payloads),
            list(batch.errors),
            list(batch.transport_receipts),
            list(batch.parser_input_envelopes),
        )
        if any(len(vector) != len(requested) for vector in vectors):
            raise RuntimeError(
                f"Illinois {purpose} batch returned unaligned acquisition rows"
            )
        expected_urls = [self._canonical_fetch_url(url) for url in requested]
        observed_urls = [self._canonical_fetch_url(url) for url in vectors[0]]
        if observed_urls != expected_urls:
            raise RuntimeError(
                f"Illinois {purpose} batch changed URL identity or order"
            )

        records: List[Dict[str, Any]] = []
        for position, (url, payload, error, receipt, envelope) in enumerate(
            zip(*vectors, strict=True)
        ):
            body = bytes(payload or b"")
            if error or not body:
                raise RuntimeError(
                    f"Illinois {purpose} page missing at batch position "
                    f"{position}: {url}: {error or 'empty payload'}"
                )
            canonical_receipt = self._canonical_illinois_transport_receipt(
                official_url=expected_urls[position],
                payload=body,
                receipt=receipt,
            )
            records.append(
                {
                    "url": expected_urls[position],
                    "payload": body,
                    "transport_receipt": canonical_receipt,
                    "parser_input_envelope": envelope,
                }
            )

        stats_by_purpose = dict(
            getattr(self, "_last_illinois_batch_stats", {}) or {}
        )
        purpose_stats = list(stats_by_purpose.get(purpose) or [])
        purpose_stats.append(dict(batch.stats or {}))
        stats_by_purpose[purpose] = purpose_stats
        self._last_illinois_batch_stats = stats_by_purpose
        return records

    def _nonoperative_act_disposition(
        self,
        act: Mapping[str, Any],
    ) -> Optional[Dict[str, str]]:
        """Type only exact terminal labels supplied by the official Acts page."""

        label = self._clean_label(
            str(act.get("act_name") or act.get("label") or "")
        )
        repealed = self._REPEALED_ACT_LABEL_RE.search(label)
        if repealed:
            authority = self._clean_label(repealed.group("authority"))
            if not 3 <= len(authority) <= 500:
                return None
            return {
                "disposition": "repealed",
                "authority": authority,
                "source_label": label,
            }
        moved = self._MOVED_ACT_LABEL_RE.search(label)
        if moved:
            disposition = {
                "disposition": "moved",
                "destination": self._clean_label(moved.group("destination")),
                "source_label": label,
            }
            authority = self._clean_label(moved.group("authority") or "")
            if authority:
                disposition["authority"] = authority
            return disposition
        return None

    def _pending_ilcs_public_act_spec(
        self,
        *,
        chapter: Mapping[str, Any],
        act: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Return one exact enacted-law bridge for an uncompiled ILCS Act."""

        chapter_id = str(chapter.get("chapter_id") or "").strip()
        act_id = str(act.get("act_id") or "").strip()
        raw_spec = self._PENDING_ILCS_PUBLIC_ACTS.get((chapter_id, act_id))
        if raw_spec is None:
            return None
        spec = dict(raw_spec)
        section_numbers = tuple(
            str(value) for value in (spec.get("section_numbers") or ())
        )
        public_act_section_numbers = tuple(
            str(value)
            for value in (spec.get("public_act_section_numbers") or ())
        )
        public_act_number = str(spec.get("public_act_number") or "").strip()
        public_act_url = str(spec.get("url") or "").strip()
        parsed_url = urlparse(public_act_url)
        document_url = str(spec.get("document_url") or "").strip()
        parsed_document_url = urlparse(document_url) if document_url else None
        expected = {
            "chapter_number": str(chapter.get("chapter_number") or "").strip(),
            "chap_act": self._clean_label(str(act.get("chap_act") or "")),
            "act_name": self._clean_label(str(act.get("act_name") or "")),
        }
        observed = {
            key: self._clean_label(str(spec.get(key) or ""))
            for key in expected
        }
        if (
            expected != observed
            or str(act.get("chapter_id") or "").strip() != chapter_id
            or not re.fullmatch(r"\d{3}-\d{4}", public_act_number)
            or not re.fullmatch(r"(?:HB|SB)\d{4}", str(spec.get("bill_number") or ""))
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(spec.get("effective_date") or ""))
            or not section_numbers
            or len(set(section_numbers)) != len(section_numbers)
            or any(not re.fullmatch(r"\d+(?:[.-]\d+)*[A-Za-z]?", str(value)) for value in section_numbers)
            or not public_act_section_numbers
            or len(set(public_act_section_numbers))
            != len(public_act_section_numbers)
            or any(
                not re.fullmatch(r"\d+(?:[.-]\d+)*[A-Za-z]?", value)
                for value in public_act_section_numbers
            )
            or public_act_section_numbers[: len(section_numbers)]
            != section_numbers
            or parsed_url.scheme.lower() != "https"
            or str(parsed_url.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.port not in (None, 443)
            or parsed_url.query
            or parsed_url.fragment
            or parsed_url.path.casefold()
            != f"/Legislation/PublicActs/View/{public_act_number}".casefold()
            or (
                parsed_document_url is not None
                and (
                    parsed_document_url.scheme.lower() != "https"
                    or str(parsed_document_url.hostname or "").lower()
                    != self.OFFICIAL_DOMAIN
                    or parsed_document_url.username is not None
                    or parsed_document_url.password is not None
                    or parsed_document_url.port not in (None, 443)
                    or parsed_document_url.query
                    or parsed_document_url.fragment
                    or parsed_document_url.path.casefold()
                    != (
                        "/documents/legislation/PublicActs/"
                        f"{public_act_number.split('-', 1)[0]}/"
                        f"{public_act_number}.htm"
                    ).casefold()
                )
            )
        ):
            raise RuntimeError(
                "pending ILCS Public Act mapping identity drift: "
                f"chapter_id={chapter_id} act_id={act_id}"
            )
        spec["section_numbers"] = section_numbers
        spec["public_act_section_numbers"] = public_act_section_numbers
        spec["url"] = self._canonical_ilga_url(public_act_url)
        if document_url:
            spec["document_url"] = self._canonical_ilga_url(document_url)
        return spec

    def _validate_discovered_chapters(
        self,
        chapters: Sequence[Mapping[str, Any]],
    ) -> List[str]:
        urls: List[str] = []
        identities: set[Tuple[str, str]] = set()
        for position, chapter in enumerate(chapters):
            url = str(chapter.get("url") or "").strip()
            query = self._strict_illinois_url(
                url,
                expected_path="/Legislation/ILCS/Acts",
                required_query=("ChapterID", "ChapterNumber"),
            )
            chapter_id = self._first_query(query, "ChapterID")
            chapter_number = self._first_query(query, "ChapterNumber")
            if (
                not re.fullmatch(r"\d+", chapter_id)
                or not re.fullmatch(r"\d+[A-Za-z]?", chapter_number)
                or str(chapter.get("chapter_id") or "").strip() != chapter_id
                or str(chapter.get("chapter_number") or "").strip()
                != chapter_number
            ):
                raise RuntimeError(
                    f"Illinois chapter identity drift at position {position}"
                )
            identity = (chapter_id, chapter_number.casefold())
            if url in urls or identity in identities:
                raise RuntimeError(
                    f"Illinois chapter frontier contains a duplicate at position {position}"
                )
            urls.append(url)
            identities.add(identity)

        first_observation = getattr(
            self,
            "_state_law_first_official_frontier_observation",
            None,
        )
        if isinstance(first_observation, Mapping):
            fetch = first_observation.get("fetch")
            rows = getattr(fetch, "rows", ()) if fetch is not None else ()
            observed_urls = [
                self._canonical_ilga_url(
                    str(row.get("source_url") or "").strip()
                )
                for row in rows
                if isinstance(row, Mapping)
            ]
            if observed_urls and observed_urls != urls:
                raise RuntimeError(
                    "Illinois parser chapter frontier does not match the retained "
                    "official catalog observation"
                )
        return urls

    @staticmethod
    def _illinois_batch_totals(
        stats_by_purpose: Mapping[str, Any],
    ) -> Dict[str, int]:
        totals = {
            "common_crawl_inventory_queries": 0,
            "common_crawl_shared_domain_cache_hits": 0,
            "direct_initial_successes": 0,
            "warc_naive_range_fetches": 0,
            "warc_range_fetch_calls": 0,
            "warc_range_fetches_avoided": 0,
        }
        for batches in stats_by_purpose.values():
            for raw_stats in list(batches or []):
                stats = dict(raw_stats or {})
                common_crawl = dict(stats.get("common_crawl") or {})
                inventory = dict(stats.get("common_crawl_inventory_memo") or {})
                totals["common_crawl_inventory_queries"] += int(
                    stats.get("common_crawl_inventory_queries") or 0
                )
                totals["common_crawl_shared_domain_cache_hits"] += int(
                    inventory.get("shared_domain_cache_hits") or 0
                )
                totals["direct_initial_successes"] += int(
                    stats.get("direct_initial_successes") or 0
                )
                totals["warc_naive_range_fetches"] += int(
                    common_crawl.get("naive_range_fetches") or 0
                )
                totals["warc_range_fetch_calls"] += int(
                    common_crawl.get("range_fetch_calls") or 0
                )
                totals["warc_range_fetches_avoided"] += int(
                    common_crawl.get("range_fetches_avoided") or 0
                )
        return totals

    async def _scrape_strict_full_code(
        self,
        *,
        code_name: str,
        code_url: str,
    ) -> List[NormalizedStatute]:
        """Close the three-stage ILCS chapter/act/FullText frontier."""

        frontier: Dict[str, Any] = {
            "closed": False,
            "source_kind": "official_illinois_ilga_full_act_html",
            "discovery_method": "official_chapter_act_fulltext_index",
            "chapters_discovered": 0,
            "chapter_pages_requested": 0,
            "chapter_pages_fetched": 0,
            "chapter_pages_parsed": 0,
            "acts_discovered": 0,
            "article_page_requests_avoided": 0,
            "full_act_pages_requested": 0,
            "full_act_pages_fetched": 0,
            "full_act_pages_classified": 0,
            "pending_public_act_pages_requested": 0,
            "pending_public_act_pages_fetched": 0,
            "pending_public_act_pages_classified": 0,
            "pending_public_acts": [],
            "statute_bearing_acts": 0,
            "terminal_acts_excluded": 0,
            "terminal_dispositions": [],
            "statutes_emitted": 0,
            "errors": [],
        }
        self._last_illinois_batch_stats = {}
        self._last_illinois_full_frontier = frontier
        self._last_full_corpus_frontier = frontier

        chapters = await self._discover_chapter_links(code_url)
        if not chapters:
            self._fail_illinois_full_frontier(
                "Illinois strict chapter frontier is empty"
            )
        try:
            chapter_urls = self._validate_discovered_chapters(chapters)
        except RuntimeError as exc:
            self._fail_illinois_full_frontier(
                "Illinois strict chapter frontier is invalid",
                chapter_error=str(exc),
            )
        frontier["chapters_discovered"] = len(chapter_urls)

        try:
            chapter_records = await self._fetch_illinois_page_batch(
                chapter_urls,
                purpose="chapter_pages",
                timeout_seconds=35,
                max_concurrency=max(
                    1,
                    min(
                        32,
                        int(
                            self._env_int(
                                "STATE_SCRAPER_IL_CHAPTER_CONCURRENCY",
                                default=12,
                            )
                        ),
                    ),
                ),
            )
        except Exception as exc:
            self._fail_illinois_full_frontier(
                "Illinois strict chapter-page batch failed",
                chapter_batch_error=f"{type(exc).__name__}: {exc}",
            )
        frontier["chapter_pages_requested"] = len(chapter_urls)
        frontier["chapter_pages_fetched"] = len(chapter_records)

        act_plan: List[Tuple[Dict[str, str], Dict[str, str], str]] = []
        seen_article_urls: set[str] = set()
        seen_full_urls: set[str] = set()
        seen_act_identities: set[Tuple[str, str]] = set()
        for chapter_position, (chapter, record) in enumerate(
            zip(chapters, chapter_records, strict=True),
            start=1,
        ):
            html = bytes(record["payload"]).decode("utf-8", errors="replace")
            try:
                acts = self._parse_act_links_html(
                    html,
                    chapter_url=str(chapter["url"]),
                    strict=True,
                )
            except RuntimeError as exc:
                self._fail_illinois_full_frontier(
                    "Illinois strict chapter-page parser failed",
                    chapter_position=chapter_position,
                    chapter_url=chapter["url"],
                    chapter_parser_error=str(exc),
                )
            if not acts:
                self._fail_illinois_full_frontier(
                    "Illinois discovered chapter has no admissible act locators",
                    chapter_position=chapter_position,
                    chapter_url=chapter["url"],
                )
            for act_position, act in enumerate(acts, start=1):
                try:
                    full_url = self._deterministic_full_act_url(
                        act,
                        chapter=chapter,
                        strict=True,
                    )
                    self._strict_illinois_url(
                        full_url,
                        expected_path="/legislation/ILCS/details",
                        required_query=("ActID", "ChapterID", "ChapAct"),
                    )
                except RuntimeError as exc:
                    self._fail_illinois_full_frontier(
                        "Illinois act locator cannot derive an exact FullText URL",
                        act_error=str(exc),
                        act_position=act_position,
                        chapter_position=chapter_position,
                        article_url=act.get("url"),
                    )
                article_url = str(act["url"])
                act_identity = (
                    str(act.get("chapter_id") or ""),
                    str(act.get("act_id") or ""),
                )
                if (
                    article_url in seen_article_urls
                    or full_url in seen_full_urls
                    or act_identity in seen_act_identities
                ):
                    self._fail_illinois_full_frontier(
                        "Illinois strict act frontier contains duplicate locators",
                        act_identity=act_identity,
                        article_url=article_url,
                        full_url=full_url,
                    )
                seen_article_urls.add(article_url)
                seen_full_urls.add(full_url)
                seen_act_identities.add(act_identity)
                act_plan.append((dict(chapter), dict(act), full_url))
            frontier["chapter_pages_parsed"] = chapter_position

        if not act_plan:
            self._fail_illinois_full_frontier(
                "Illinois strict act frontier is empty"
            )
        frontier["acts_discovered"] = len(act_plan)
        frontier["article_page_requests_avoided"] = len(act_plan)

        full_batch_size = max(
            2,
            min(
                512,
                int(
                    self._env_int(
                        "STATE_SCRAPER_IL_FULL_ACT_BATCH_SIZE",
                        default=512,
                    )
                ),
            ),
        )
        full_concurrency = max(
            1,
            min(
                32,
                int(
                    self._env_int(
                        "STATE_SCRAPER_IL_FULL_ACT_CONCURRENCY",
                        default=12,
                    )
                ),
            ),
        )
        statutes: List[NormalizedStatute] = []
        terminal_dispositions: List[Dict[str, Any]] = []
        seen_statute_ids: set[str] = set()
        seen_official_cites: set[str] = set()
        classified_acts = 0
        statute_bearing_acts = 0

        for batch_start in range(0, len(act_plan), full_batch_size):
            plan_batch = act_plan[batch_start : batch_start + full_batch_size]
            full_urls = [item[2] for item in plan_batch]
            try:
                full_records = await self._fetch_illinois_page_batch(
                    full_urls,
                    purpose="full_act_pages",
                    timeout_seconds=45,
                    max_concurrency=full_concurrency,
                )
            except Exception as exc:
                self._fail_illinois_full_frontier(
                    "Illinois strict FullText batch failed",
                    full_batch_error=f"{type(exc).__name__}: {exc}",
                    full_batch_start=batch_start,
                    full_batch_size=len(plan_batch),
                )
            frontier["full_act_pages_requested"] = int(
                frontier["full_act_pages_requested"]
            ) + len(plan_batch)
            frontier["full_act_pages_fetched"] = int(
                frontier["full_act_pages_fetched"]
            ) + len(full_records)

            parsed_batch: List[List[NormalizedStatute]] = []
            disposition_batch: List[Optional[Dict[str, str]]] = []
            pending_plan: List[Tuple[int, Dict[str, Any]]] = []
            for batch_index, ((chapter, act, full_url), record) in enumerate(
                zip(plan_batch, full_records, strict=True)
            ):
                html = bytes(record["payload"]).decode(
                    "utf-8", errors="replace"
                )
                try:
                    parsed = self._parse_full_act_html(
                        code_name=code_name,
                        chapter=chapter,
                        act=act,
                        full_url=full_url,
                        html=html,
                        transport_receipt=record["transport_receipt"],
                        strict=True,
                    )
                except RuntimeError as exc:
                    self._fail_illinois_full_frontier(
                        "Illinois strict FullText parser failed",
                        act_id=act.get("act_id"),
                        full_url=full_url,
                        parser_error=str(exc),
                    )
                disposition: Optional[Dict[str, str]] = None
                if not parsed:
                    disposition = self._nonoperative_act_disposition(act)
                    if disposition is None:
                        try:
                            pending_spec = self._pending_ilcs_public_act_spec(
                                chapter=chapter,
                                act=act,
                            )
                        except RuntimeError as exc:
                            self._fail_illinois_full_frontier(
                                "Illinois pending ILCS Public Act mapping failed",
                                act_id=act.get("act_id"),
                                mapping_error=str(exc),
                            )
                        if pending_spec is None:
                            self._fail_illinois_full_frontier(
                                "Illinois official act has no owned sections and no "
                                "exact nonoperative disposition",
                                act_id=act.get("act_id"),
                                act_label=act.get("act_name"),
                                full_url=full_url,
                            )
                        pending_plan.append((batch_index, pending_spec))
                parsed_batch.append(parsed)
                disposition_batch.append(disposition)

            if pending_plan:
                pending_source_plan: List[Tuple[int, str, str]] = []
                for batch_index, spec in pending_plan:
                    pending_source_plan.append(
                        (batch_index, "landing", str(spec["url"]))
                    )
                    document_url = str(spec.get("document_url") or "")
                    if document_url:
                        pending_source_plan.append(
                            (batch_index, "document", document_url)
                        )
                pending_urls = [
                    url for _batch_index, _role, url in pending_source_plan
                ]
                try:
                    pending_records = await self._fetch_illinois_page_batch(
                        pending_urls,
                        purpose="pending_ilcs_public_act_pages",
                        timeout_seconds=45,
                        max_concurrency=full_concurrency,
                    )
                except Exception as exc:
                    self._fail_illinois_full_frontier(
                        "Illinois pending ILCS Public Act batch failed",
                        pending_batch_error=f"{type(exc).__name__}: {exc}",
                        full_batch_start=batch_start,
                        pending_batch_size=len(pending_plan),
                    )
                frontier["pending_public_act_pages_requested"] = int(
                    frontier["pending_public_act_pages_requested"]
                ) + len(pending_source_plan)
                frontier["pending_public_act_pages_fetched"] = int(
                    frontier["pending_public_act_pages_fetched"]
                ) + len(pending_records)
                pending_records_by_act: Dict[
                    int, Dict[str, Dict[str, Any]]
                ] = {}
                for (batch_index, role, expected_url), pending_record in zip(
                    pending_source_plan,
                    pending_records,
                    strict=True,
                ):
                    if str(pending_record.get("url") or "") != expected_url:
                        self._fail_illinois_full_frontier(
                            "Illinois pending ILCS Public Act source alignment failed",
                            act_id=plan_batch[batch_index][1].get("act_id"),
                            expected_url=expected_url,
                            observed_url=pending_record.get("url"),
                        )
                    sources = pending_records_by_act.setdefault(
                        batch_index, {}
                    )
                    if role in sources:
                        self._fail_illinois_full_frontier(
                            "Illinois pending ILCS Public Act source role repeated",
                            act_id=plan_batch[batch_index][1].get("act_id"),
                            source_role=role,
                        )
                    sources[role] = pending_record
                pending_summaries = list(
                    frontier.get("pending_public_acts") or []
                )
                for batch_index, spec in pending_plan:
                    chapter, act, full_url = plan_batch[batch_index]
                    full_record = full_records[batch_index]
                    pending_sources = pending_records_by_act.get(
                        batch_index, {}
                    )
                    landing_record = pending_sources.get("landing")
                    document_record = pending_sources.get("document")
                    if landing_record is None or (
                        spec.get("document_url") and document_record is None
                    ):
                        self._fail_illinois_full_frontier(
                            "Illinois pending ILCS Public Act source set is incomplete",
                            act_id=act.get("act_id"),
                        )
                    public_act_record = document_record or landing_record
                    public_act_url = str(
                        spec.get("document_url") or spec["url"]
                    )
                    try:
                        pending_rows = self._parse_pending_ilcs_public_act_html(
                            code_name=code_name,
                            chapter=chapter,
                            act=act,
                            full_url=full_url,
                            full_text_payload=bytes(full_record["payload"]),
                            full_text_receipt=full_record["transport_receipt"],
                            spec=spec,
                            public_act_url=public_act_url,
                            public_act_payload=bytes(
                                public_act_record["payload"]
                            ),
                            public_act_receipt=(
                                public_act_record["transport_receipt"]
                            ),
                            public_act_landing_url=(
                                str(spec["url"])
                                if document_record is not None
                                else None
                            ),
                            public_act_landing_payload=(
                                bytes(landing_record["payload"])
                                if document_record is not None
                                else None
                            ),
                            public_act_landing_receipt=(
                                landing_record["transport_receipt"]
                                if document_record is not None
                                else None
                            ),
                        )
                    except RuntimeError as exc:
                        self._fail_illinois_full_frontier(
                            "Illinois pending ILCS Public Act parser failed",
                            act_id=act.get("act_id"),
                            public_act_url=public_act_url,
                            parser_error=str(exc),
                        )
                    if not pending_rows:
                        self._fail_illinois_full_frontier(
                            "Illinois pending ILCS Public Act emitted no sections",
                            act_id=act.get("act_id"),
                            public_act_url=public_act_url,
                        )
                    parsed_batch[batch_index] = pending_rows
                    pending_summaries.append(
                        {
                            "act_id": str(act.get("act_id") or ""),
                            "chap_act": str(act.get("chap_act") or ""),
                            "effective_date": str(spec["effective_date"]),
                            "full_url": full_url,
                            "public_act_number": str(
                                spec["public_act_number"]
                            ),
                            "public_act_url": public_act_url,
                            "public_act_landing_url": (
                                str(spec["url"])
                                if document_record is not None
                                else public_act_url
                            ),
                            "source_pages": (
                                2 if document_record is not None else 1
                            ),
                            "sections_emitted": len(pending_rows),
                        }
                    )
                frontier["pending_public_act_pages_classified"] = int(
                    frontier["pending_public_act_pages_classified"]
                ) + len(pending_plan)
                frontier["pending_public_acts"] = pending_summaries

            for batch_offset, (
                (chapter, act, full_url),
                record,
                parsed,
                disposition,
            ) in enumerate(
                zip(
                    plan_batch,
                    full_records,
                    parsed_batch,
                    disposition_batch,
                    strict=True,
                ),
                start=1,
            ):
                classified_acts += 1
                if not parsed:
                    if disposition is None:
                        self._fail_illinois_full_frontier(
                            "Illinois pending ILCS act remained unclassified",
                            act_id=act.get("act_id"),
                            full_url=full_url,
                        )
                    terminal_dispositions.append(
                        {
                            **disposition,
                            "act_id": str(act.get("act_id") or ""),
                            "chap_act": str(act.get("chap_act") or ""),
                            "content_sha256": hashlib.sha256(
                                bytes(record["payload"])
                            ).hexdigest(),
                            "full_url": full_url,
                            "transport_receipt": dict(
                                record["transport_receipt"]
                            ),
                        }
                    )
                    continue

                statute_bearing_acts += 1
                for section_position, statute in enumerate(parsed, start=1):
                    if (
                        statute.statute_id in seen_statute_ids
                        or statute.official_cite in seen_official_cites
                    ):
                        self._fail_illinois_full_frontier(
                            "Illinois strict canonical statute identities are not unique",
                            duplicate_official_cite=statute.official_cite,
                            duplicate_statute_id=statute.statute_id,
                            full_url=full_url,
                        )
                    seen_statute_ids.add(statute.statute_id)
                    seen_official_cites.add(statute.official_cite)
                    structured_data = dict(statute.structured_data or {})
                    structured_data.update(
                        {
                            "act_frontier_index": batch_start + batch_offset,
                            "section_frontier_index": section_position,
                        }
                    )
                    statute.structured_data = structured_data
                    statutes.append(statute)

            frontier["full_act_pages_classified"] = classified_acts
            frontier["statute_bearing_acts"] = statute_bearing_acts
            frontier["terminal_acts_excluded"] = len(terminal_dispositions)
            frontier["terminal_dispositions"] = terminal_dispositions
            frontier["statutes_emitted"] = len(statutes)
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="illinois:full-act-scan",
                extra={
                    "chapters_scanned": len(chapters),
                    "discovered_chapters": len(chapters),
                    "scanned_laws": classified_acts,
                    "discovered_laws": len(act_plan),
                    "sections_scanned": len(statutes),
                    "discovered_sections": len(statutes),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        reconciled = bool(
            statutes
            and len(chapters)
            == int(frontier["chapter_pages_requested"])
            == int(frontier["chapter_pages_fetched"])
            == int(frontier["chapter_pages_parsed"])
            and len(act_plan)
            == int(frontier["full_act_pages_requested"])
            == int(frontier["full_act_pages_fetched"])
            == classified_acts
            == statute_bearing_acts + len(terminal_dispositions)
            and int(frontier["pending_public_act_pages_requested"])
            == int(frontier["pending_public_act_pages_fetched"])
            and int(frontier["pending_public_act_pages_classified"])
            == len(list(frontier.get("pending_public_acts") or []))
        )
        if not reconciled:
            self._fail_illinois_full_frontier(
                "Illinois strict three-stage frontier did not reconcile",
                chapter_count=len(chapters),
                act_count=len(act_plan),
                classified_acts=classified_acts,
                statute_bearing_acts=statute_bearing_acts,
                terminal_acts=len(terminal_dispositions),
                statute_count=len(statutes),
            )

        batch_stats = dict(
            getattr(self, "_last_illinois_batch_stats", {}) or {}
        )
        frontier.update(self._illinois_batch_totals(batch_stats))
        frontier["batch_stats"] = batch_stats
        frontier["closed"] = True
        self._last_illinois_full_frontier = frontier
        self._last_full_corpus_frontier = frontier
        for statute in statutes:
            structured_data = dict(statute.structured_data or {})
            structured_data.update(
                {
                    "official_frontier_closed": True,
                    "official_chapters_discovered": len(chapters),
                    "official_acts_discovered": len(act_plan),
                    "official_terminal_acts_excluded": len(
                        terminal_dispositions
                    ),
                    "official_pending_public_acts": int(
                        frontier["pending_public_act_pages_classified"]
                    ),
                }
            )
            statute.structured_data = structured_data
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="illinois:complete",
            force=True,
            extra={
                "chapters_scanned": len(chapters),
                "discovered_chapters": len(chapters),
                "scanned_laws": len(act_plan),
                "discovered_laws": len(act_plan),
                "sections_scanned": len(statutes),
                "discovered_sections": len(statutes),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes

    async def _parse_full_act(
        self,
        *,
        code_name: str,
        chapter: Dict[str, str],
        act: Dict[str, str],
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        full_url = await self._full_act_url(act["url"])
        if not full_url:
            return []
        html = await self._fetch_official_il_html(full_url, timeout_seconds=35)
        if not html:
            return []

        provenance = self._last_parser_input_row_provenance()
        receipt = provenance.get("transport_receipt")
        return self._parse_full_act_html(
            code_name=code_name,
            chapter=chapter,
            act=act,
            full_url=full_url,
            html=html,
            transport_receipt=(
                receipt if isinstance(receipt, Mapping) else None
            ),
            max_statutes=max_statutes,
            strict=False,
        )

    def _parse_full_act_html(
        self,
        *,
        code_name: str,
        chapter: Mapping[str, Any],
        act: Mapping[str, Any],
        full_url: str,
        html: str,
        transport_receipt: Optional[Mapping[str, Any]] = None,
        max_statutes: Optional[int] = None,
        strict: bool = False,
    ) -> List[NormalizedStatute]:
        """Parse one already retained Illinois FullText response."""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            if strict:
                raise RuntimeError(
                    "BeautifulSoup is required for strict Illinois FullText parsing"
                )
            return []

        # Some official FullText responses (notably the Election Code) exceed
        # 17 MiB.  lxml is a project dependency and keeps this source-bound
        # parse linear enough for the uncapped strict crawl.
        soup = BeautifulSoup(html, "lxml")
        for node in soup(["script", "style", "noscript", "form", "nav", "footer", "header"]):
            node.decompose()
        text = self._normalize_legal_text(unescape(soup.get_text("\n", strip=True)))
        if not text:
            return []

        expected_act_prefix = self._normalize_legal_text(
            str(act.get("chap_act") or "")
        ).rstrip("/")
        if not expected_act_prefix:
            if strict:
                raise RuntimeError(
                    "official act omitted its authoritative ILCS citation prefix"
                )
            self.logger.warning(
                "Illinois official act omitted its ILCS citation prefix: act_id=%s url=%s",
                act.get("act_id"),
                act.get("url"),
            )
            return []

        # Current ILGA FullText HTML places each operative section in its own
        # ``div align=justify`` block, with the official citation at the start
        # of that block.  The same parenthesized citations also occur inline in
        # statutory forms and cross-references.  Retain a normalized prefix of
        # every source-delimited section block so those inline occurrences can
        # never become segmentation boundaries.  A prefix long enough to pass
        # the heading and enter the section body also distinguishes concurrent
        # variants that reuse an official marker.
        official_heading_prefixes: Dict[str, List[str]] = {}
        for block in soup.find_all("div"):
            if str(block.get("align") or "").strip().casefold() != "justify":
                continue
            block_text = self._normalize_legal_text(
                unescape(block.get_text("\n", strip=True))
            )
            block_marker = self._CITE_RE.match(block_text)
            if block_marker is None:
                continue
            block_cite = self._normalize_legal_text(block_marker.group("cite"))
            prefix_length = min(
                len(block_text),
                max(block_marker.end() + 1, 512),
            )
            official_heading_prefixes.setdefault(
                block_cite.casefold(), []
            ).append(block_text[:prefix_length])

        # The Acts index supplies the authoritative ``chapter ILCS act/``
        # prefix.  Both ownership and the retained ILGA block boundary are
        # required in strict production parsing.  Bounded legacy callers keep
        # their prior flat-text behavior when older fixture/archive HTML has no
        # current ILGA section blocks.
        matches: List[Tuple[re.Match[str], re.Match[str]]] = []
        for candidate in self._CITE_RE.finditer(text):
            cite = self._normalize_legal_text(candidate.group("cite"))
            if " heading" in cite.lower():
                continue
            cite_match = self._SECTION_CITE_RE.match(cite)
            if not cite_match:
                continue
            candidate_prefix = self._normalize_legal_text(
                f"{cite_match.group('chapter')} ILCS {cite_match.group('act')}"
            )
            if candidate_prefix.casefold() != expected_act_prefix.casefold():
                continue
            if official_heading_prefixes:
                source_prefixes = official_heading_prefixes.get(
                    cite.casefold(), []
                )
                if not any(
                    text.startswith(prefix, candidate.start())
                    for prefix in source_prefixes
                ):
                    continue
            elif strict:
                raise RuntimeError(
                    "official FullText page has an owned ILCS citation but "
                    "no source-delimited section block"
                )
            matches.append((candidate, cite_match))

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for idx, (match, cite_match) in enumerate(matches):
            if max_statutes is not None and len(statutes) >= max_statutes:
                break

            start = match.start()
            end = matches[idx + 1][0].start() if idx + 1 < len(matches) else len(text)
            section_text = self._normalize_legal_text(text[start:end])
            if len(section_text) < 60 and not strict:
                continue

            chapter_number = cite_match.group("chapter")
            act_number = cite_match.group("act")
            section_number = cite_match.group("section")
            section_key = f"{chapter_number} ILCS {act_number}/{section_number}"
            citation_identity_correction: Dict[str, str] = {}
            if section_key in seen_sections:
                heading_section = self._adjacent_section_heading_number(
                    section_text
                )
                corrected_key = (
                    f"{chapter_number} ILCS {act_number}/{heading_section}"
                    if heading_section
                    else ""
                )
                if (
                    not heading_section
                    or heading_section.casefold() == section_number.casefold()
                    or corrected_key in seen_sections
                ):
                    if strict:
                        raise RuntimeError(
                            "official FullText page repeats section identity "
                            f"{section_key}"
                        )
                    continue
                citation_identity_correction = {
                    "official_citation_marker": section_key,
                    "adjacent_section_heading": heading_section,
                    "reason": (
                        "duplicate_official_citation_marker_with_distinct_"
                        "adjacent_section_heading"
                    ),
                }
                section_number = heading_section
                section_key = corrected_key
            seen_sections.add(section_key)

            section_name = self._section_name_from_text(section_text, section_number)
            row_provenance: Dict[str, Any] = {}
            if isinstance(transport_receipt, Mapping):
                digest = str(
                    transport_receipt.get("content_sha256") or ""
                ).strip().lower()
                if strict and not re.fullmatch(r"[a-f0-9]{64}", digest):
                    raise RuntimeError(
                        "official FullText receipt lacks a canonical content digest"
                    )
                if digest:
                    row_provenance = {
                        "content_sha256": digest,
                        "transport_receipt": dict(transport_receipt),
                    }
            elif strict:
                raise RuntimeError(
                    "official FullText row lacks an exact transport receipt"
                )
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"IL-{chapter_number}-{act_number}-{section_number}".replace("/", "-"),
                    code_name=code_name,
                    title_number=chapter_number,
                    title_name=chapter.get("major_topic") or None,
                    chapter_number=chapter_number,
                    chapter_name=chapter.get("chapter_name") or None,
                    section_number=f"{act_number}/{section_number}",
                    section_name=section_name or f"Section {section_number}",
                    short_title=section_name or None,
                    full_text=section_text,
                    legal_area=self._identify_legal_area(
                        " ".join(
                            part
                            for part in [
                                section_name,
                                act.get("act_name"),
                                chapter.get("chapter_name"),
                                chapter.get("major_topic"),
                            ]
                            if part
                        )
                    ),
                    source_url=full_url,
                    official_cite=f"{chapter_number} ILCS {act_number}/{section_number}",
                    structured_data={
                        "source_kind": "official_illinois_ilga_full_act_html",
                        "discovery_method": "official_chapter_act_fulltext_index",
                        "chapter_url": chapter.get("url"),
                        "act_url": act.get("url"),
                        "act_id": act.get("act_id"),
                        "act_name": act.get("act_name"),
                        "chap_act": act.get("chap_act") or f"{chapter_number} ILCS {act_number}/",
                        "skip_hydrate": True,
                        **(
                            {
                                "citation_identity_correction": (
                                    citation_identity_correction
                                )
                            }
                            if citation_identity_correction
                            else {}
                        ),
                        **row_provenance,
                    },
                )
            )
        return statutes

    def _parse_pending_ilcs_public_act_html(
        self,
        *,
        code_name: str,
        chapter: Mapping[str, Any],
        act: Mapping[str, Any],
        full_url: str,
        full_text_payload: bytes,
        full_text_receipt: Mapping[str, Any],
        spec: Mapping[str, Any],
        public_act_url: str,
        public_act_payload: bytes,
        public_act_receipt: Mapping[str, Any],
        public_act_landing_url: Optional[str] = None,
        public_act_landing_payload: Optional[bytes] = None,
        public_act_landing_receipt: Optional[Mapping[str, Any]] = None,
    ) -> List[NormalizedStatute]:
        """Parse an exact enacted Public Act pending ILCS compilation."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "BeautifulSoup is required for pending Illinois Public Acts"
            ) from exc

        expected_spec = self._pending_ilcs_public_act_spec(
            chapter=chapter,
            act=act,
        )
        if expected_spec is None or dict(expected_spec) != dict(spec):
            raise RuntimeError(
                "pending ILCS Public Act parser received an unbound mapping"
            )
        expected_public_act_url = str(
            spec.get("document_url") or spec.get("url") or ""
        )
        if public_act_url != expected_public_act_url:
            raise RuntimeError(
                "pending ILCS Public Act URL does not match its exact mapping"
            )
        expected_landing_url = (
            str(spec.get("url") or "") if spec.get("document_url") else None
        )
        if public_act_landing_url != expected_landing_url:
            raise RuntimeError(
                "pending ILCS Public Act landing URL does not match its exact mapping"
            )

        receipt_inputs = (
            (
                "ILCS FullText",
                full_url,
                bytes(full_text_payload),
                full_text_receipt,
            ),
            (
                "Public Act",
                public_act_url,
                bytes(public_act_payload),
                public_act_receipt,
            ),
        )
        canonical_receipts: Dict[str, Dict[str, Any]] = {}
        for label, expected_url, payload, receipt in receipt_inputs:
            if not payload:
                raise RuntimeError(
                    f"pending ILCS {label} receipt identity drift"
                )
            try:
                canonical_receipts[label] = (
                    self._canonical_illinois_transport_receipt(
                        official_url=expected_url,
                        payload=payload,
                        receipt=receipt,
                    )
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"pending ILCS {label} receipt identity drift"
                ) from exc

        if expected_landing_url is not None:
            landing_payload = bytes(public_act_landing_payload or b"")
            if not landing_payload:
                raise RuntimeError(
                    "pending ILCS Public Act landing receipt identity drift"
                )
            try:
                canonical_receipts["Public Act landing"] = (
                    self._canonical_illinois_transport_receipt(
                        official_url=expected_landing_url,
                        payload=landing_payload,
                        receipt=public_act_landing_receipt,
                    )
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    "pending ILCS Public Act landing receipt identity drift"
                ) from exc

        full_text_receipt = canonical_receipts["ILCS FullText"]
        public_act_receipt = canonical_receipts["Public Act"]
        html = bytes(public_act_payload).decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "lxml")
        uses_external_document = bool(spec.get("document_url"))
        host = soup.body if uses_external_document else soup.select_one(
            "#billtextanchor"
        )
        if host is None:
            raise RuntimeError(
                "pending ILCS Public Act omitted its official bill-text block"
            )
        public_act_number = str(spec["public_act_number"])
        bill_number = str(spec["bill_number"])
        host_text = self._normalize_legal_text(
            unescape(host.get_text("\n", strip=True))
        )
        if not re.search(
            rf"\bPublic\s+Act\s+{re.escape(public_act_number)}\b",
            host_text,
            flags=re.IGNORECASE,
        ) or not re.search(
                rf"\b{re.escape(bill_number)}\s+Enrolled\b",
                host_text,
                flags=re.IGNORECASE,
        ):
            raise RuntimeError(
                "pending ILCS Public Act header identity drift"
            )

        code_nodes = list(host.find_all("code"))
        code_parts = [
            self._normalize_legal_text(unescape(node.get_text(" ", strip=True)))
            for node in code_nodes
        ]
        markers: List[Tuple[int, str]] = []
        for position, (node, part) in enumerate(zip(code_nodes, code_parts)):
            marker = re.fullmatch(
                r"Section\s+(?P<section>\d+(?:[.-]\d+)*[A-Za-z]?)\.",
                part,
                flags=re.IGNORECASE,
            )
            if marker and uses_external_document:
                indentation = node.find_previous_sibling("code")
                if indentation is None or self._normalize_legal_text(
                    unescape(indentation.get_text(" ", strip=True))
                ):
                    marker = None
            if marker:
                markers.append((position, marker.group("section")))
        observed_sections = tuple(section for _position, section in markers)
        public_act_sections = tuple(
            str(value) for value in spec["public_act_section_numbers"]
        )
        if observed_sections != public_act_sections:
            raise RuntimeError(
                "pending ILCS Public Act section frontier drift: "
                f"expected={public_act_sections} observed={observed_sections}"
            )
        expected_sections = tuple(
            str(value) for value in spec["section_numbers"]
        )
        if (
            not expected_sections
            or len(expected_sections) > len(observed_sections)
            or observed_sections[: len(expected_sections)]
            != expected_sections
        ):
            raise RuntimeError(
                "pending ILCS Public Act owned section frontier drift: "
                f"owned={expected_sections} observed={observed_sections}"
            )

        effective_date_soup = soup
        if expected_landing_url is not None:
            landing_soup = BeautifulSoup(
                bytes(public_act_landing_payload or b"").decode(
                    "utf-8", errors="replace"
                ),
                "lxml",
            )
            landing_text = self._normalize_legal_text(
                unescape(landing_soup.get_text("\n", strip=True))
            )
            linked_documents = {
                self._canonical_ilga_url(
                    urljoin(expected_landing_url, str(anchor.get("href") or ""))
                )
                for anchor in landing_soup.find_all("a", href=True)
            }
            if (
                not re.search(
                    rf"\bPublic\s+Act\s+{re.escape(public_act_number)}\b",
                    landing_text,
                    flags=re.IGNORECASE,
                )
                or public_act_url not in linked_documents
            ):
                raise RuntimeError(
                    "pending ILCS Public Act landing identity drift"
                )
            effective_date_soup = landing_soup
        page_text = self._normalize_legal_text(
            unescape(effective_date_soup.get_text("\n", strip=True))
        )
        effective_dates = re.findall(
            r"\bEffective\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})\b",
            page_text,
            flags=re.IGNORECASE,
        )
        if len(effective_dates) != 1:
            raise RuntimeError(
                "pending ILCS Public Act effective-date identity drift"
            )
        try:
            effective_date = datetime.strptime(
                effective_dates[0], "%m/%d/%Y"
            ).date().isoformat()
        except ValueError as exc:
            raise RuntimeError(
                "pending ILCS Public Act effective date is invalid"
            ) from exc
        if effective_date != str(spec["effective_date"]):
            raise RuntimeError(
                "pending ILCS Public Act effective-date identity drift"
            )

        act_name = self._clean_label(str(act.get("act_name") or ""))
        short_title = act_name.rstrip(".")
        first_start = markers[0][0]
        first_end = markers[1][0] if len(markers) > 1 else len(code_parts)
        first_section = self._normalize_legal_text(
            " ".join(code_parts[first_start:first_end])
        )
        if (
            f"This Act may be cited as the {short_title}." not in first_section
        ):
            raise RuntimeError(
                "pending ILCS Public Act short-title identity drift"
            )

        chap_act = self._clean_label(str(act.get("chap_act") or ""))
        citation_prefix = re.fullmatch(
            r"(?P<chapter>\d+)\s+ILCS\s+(?P<act>[^/\s]+)/",
            chap_act,
            flags=re.IGNORECASE,
        )
        if citation_prefix is None:
            raise RuntimeError(
                "pending ILCS Public Act citation prefix is invalid"
            )
        chapter_number = citation_prefix.group("chapter")
        act_number = citation_prefix.group("act")
        public_act_digest = str(public_act_receipt["content_sha256"])
        full_text_digest = str(full_text_receipt["content_sha256"])
        landing_receipt = canonical_receipts.get("Public Act landing")
        statutes: List[NormalizedStatute] = []
        for marker_index, (start, section_number) in enumerate(
            markers[: len(expected_sections)]
        ):
            end = (
                markers[marker_index + 1][0]
                if marker_index + 1 < len(markers)
                else len(code_parts)
            )
            section_text = self._normalize_legal_text(
                " ".join(code_parts[start:end])
            )
            name_match = re.match(
                rf"Section\s+{re.escape(section_number)}\.\s*"
                r"(?P<name>[^.]{2,180})\.",
                section_text,
                flags=re.IGNORECASE,
            )
            section_name = (
                self._normalize_legal_text(name_match.group("name"))
                if name_match
                else f"Section {section_number}"
            )
            official_cite = (
                f"{chapter_number} ILCS {act_number}/{section_number}"
            )
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=(
                        f"IL-{chapter_number}-{act_number}-{section_number}"
                    ).replace("/", "-"),
                    code_name=code_name,
                    title_number=chapter_number,
                    title_name=chapter.get("major_topic") or None,
                    chapter_number=chapter_number,
                    chapter_name=chapter.get("chapter_name") or None,
                    section_number=f"{act_number}/{section_number}",
                    section_name=section_name,
                    short_title=section_name,
                    full_text=section_text,
                    legal_area=self._identify_legal_area(
                        " ".join(
                            str(value)
                            for value in (
                                section_name,
                                act_name,
                                chapter.get("chapter_name"),
                                chapter.get("major_topic"),
                            )
                            if value
                        )
                    ),
                    source_url=public_act_url,
                    official_cite=official_cite,
                    structured_data={
                        "source_kind": (
                            "official_illinois_public_act_pending_ilcs_compilation"
                        ),
                        "discovery_method": (
                            "exact_pending_ilcs_public_act_fallback"
                        ),
                        "chapter_url": chapter.get("url"),
                        "act_url": act.get("url"),
                        "act_id": act.get("act_id"),
                        "act_name": act_name,
                        "chap_act": chap_act,
                        "pending_ilcs_compilation": True,
                        "public_act_number": public_act_number,
                        "bill_number": bill_number,
                        "effective_date": effective_date,
                        "public_act_section_frontier": list(
                            public_act_sections
                        ),
                        "ilcs_fulltext_url": full_url,
                        "ilcs_fulltext_content_sha256": full_text_digest,
                        "ilcs_fulltext_transport_receipt": dict(
                            full_text_receipt
                        ),
                        "public_act_url": public_act_url,
                        "content_sha256": public_act_digest,
                        "transport_receipt": dict(public_act_receipt),
                        **(
                            {
                                "public_act_landing_url": (
                                    public_act_landing_url
                                ),
                                "public_act_landing_content_sha256": str(
                                    landing_receipt["content_sha256"]
                                ),
                                "public_act_landing_transport_receipt": dict(
                                    landing_receipt
                                ),
                            }
                            if landing_receipt is not None
                            else {}
                        ),
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    async def _full_act_url(self, act_url: str) -> str:
        html = await self._fetch_official_il_html(act_url)
        if not html:
            return ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if self._FULL_ACT_LINK_RE.search(href):
                return self._canonical_ilga_url(urljoin(act_url, href))
        query = parse_qs(urlparse(act_url).query)
        act_id = self._first_query(query, "ActID")
        chapter_id = self._first_query(query, "ChapterID")
        if not act_id or not chapter_id:
            return ""
        params = {
            "ActID": act_id,
            "ChapterID": chapter_id,
            "SeqStart": "",
            "ChapAct": "FullText",
        }
        return f"{self.get_base_url()}/legislation/ILCS/details?{urlencode(params)}"

    @staticmethod
    def _first_query(query: Dict[str, List[str]], key: str) -> str:
        values = query.get(key) or []
        return unescape(values[0]).strip() if values else ""

    @staticmethod
    def _clean_label(value: str) -> str:
        return re.sub(r"\s+", " ", unescape(str(value or "").replace("\xa0", " "))).strip()

    @staticmethod
    def _chapter_name_from_label(label: str) -> str:
        match = re.match(r"CHAPTER\s+\d+\s+(.+)$", label, flags=re.IGNORECASE)
        return match.group(1).strip() if match else label

    @classmethod
    def _split_act_label(cls, label: str) -> Tuple[str, str]:
        cleaned = cls._clean_label(label)
        match = re.match(r"(?P<chap_act>\d+\s+ILCS\s+[^/]+/)\s*(?P<name>.*)$", cleaned, flags=re.IGNORECASE)
        if match:
            return cls._clean_label(match.group("chap_act")), cls._clean_label(match.group("name"))
        return "", cleaned

    def _section_name_from_text(self, section_text: str, section_number: str) -> str:
        pattern = re.compile(
            rf"\bSec\.\s*{re.escape(section_number)}\.\s*(?P<name>.*?)(?:\s+\([a-z0-9]+\)|\s+\(Source:|\s+[A-Z][a-z]+ actions|\s+The\s|\s+This\s|$)",
            re.IGNORECASE,
        )
        match = pattern.search(section_text)
        if match:
            name = self._normalize_legal_text(match.group("name"))
            if name and len(name) <= 180:
                return name.rstrip(".")
        generic = re.search(r"\bSec\.\s*[\w.-]+\.\s*(?P<name>[^.]{3,160})\.", section_text, flags=re.IGNORECASE)
        if generic:
            return self._normalize_legal_text(generic.group("name")).rstrip(".")
        return ""

    @staticmethod
    def _adjacent_section_heading_number(section_text: str) -> str:
        """Return only an exact ``Sec.`` heading adjacent to a citation marker."""

        marker = IllinoisScraper._CITE_RE.match(str(section_text or ""))
        if marker is None:
            return ""
        match = re.match(
            r"\s*Sec\.\s*"
            r"(?P<section>\.?[A-Za-z0-9]"
            r"[A-Za-z0-9.-]*(?:\([A-Za-z0-9.-]+\)[A-Za-z0-9.-]*)*)\.",
            str(section_text)[marker.end() :],
            flags=re.IGNORECASE,
        )
        return match.group("section") if match else ""

    @staticmethod
    def _canonical_ilga_url(url: str) -> str:
        parsed = urlparse(url)
        scheme = "https"
        netloc = "www.ilga.gov"
        path = quote(
            parsed.path,
            safe="/%:@!$&'()*+,;=-._~",
        )
        query = quote(
            parsed.query,
            safe="=&%:@!$'()*+,;/?-._~",
        )
        return urlunparse((scheme, netloc, path, "", query, ""))

    def _official_ssl_context(self, *, unverified: bool = False):
        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> Tuple[bytes, bytes, bytes]:
        """Fetch one official Illinois URL and retain request/response/body bytes."""

        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request_bytes = (
            f"GET {path} HTTP/1.1\n"
            f"host: {host}\n"
            "accept: text/html,application/xhtml+xml;q=0.9,*/*;q=0.8\n"
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ipfs-datasets-open-us-law-illinois/1.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        last_exc: Exception | None = None
        body = b""
        status = 0
        header_block = ""
        for unverified in (True, False):
            try:
                with urllib.request.urlopen(
                    req,
                    timeout=max(5, int(timeout)),
                    context=self._official_ssl_context(unverified=unverified),
                ) as resp:
                    body = bytes(resp.read() or b"")
                    status = int(getattr(resp, "status", 200) or 200)
                    header_block = "".join(
                        f"{key}: {value}\n" for key, value in resp.headers.items()
                    )
                last_exc = None
                break
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise RuntimeError(f"official Illinois GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Illinois GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_chapter_index(self, html: str, index_url: str) -> List[Dict[str, str]]:
        """Parse every official ILCS chapter unit from the live chapters index."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Illinois discovery") from exc

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "")
            label = self._clean_label(link.get_text(" ", strip=True))
            full_url = self._canonical_ilga_url(urljoin(index_url, href))
            query = parse_qs(urlparse(full_url).query)
            chapter_number = self._first_query(query, "ChapterNumber")
            if not chapter_number:
                label_match = self._CHAPTER_LABEL_RE.search(label)
                if not label_match:
                    continue
                chapter_number = label_match.group(1)
            if not (
                self._OFFICIAL_CHAPTER_LINK_RE.search(href)
                or self._OFFICIAL_CHAPTER_LINK_RE.search(full_url)
                or "ChapterNumber=" in full_url
            ):
                continue
            if full_url in seen:
                continue
            seen.add(full_url)
            units.append(
                {
                    "canonical_key": f"il:chapter-{chapter_number.lower()}",
                    "source_url": full_url,
                    "label": label or f"CHAPTER {chapter_number}",
                    "chapter_number": chapter_number,
                    "text": (
                        f"Illinois Compiled Statutes {label or ('CHAPTER ' + chapter_number)} "
                        f"official chapter index entry retained from {full_url}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "IL"):
        """Acquire the uncapped official ILCS chapter frontier.

        Returns an ``OfficialFetch`` whose rows enumerate every official
        chapter unit discovered from ``www.ilga.gov``. The retained body
        is the compact official catalog derived from the live index.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "IL").strip().upper()
        if normalized != "IL":
            raise ValueError(f"IllinoisScraper cannot acquire {normalized}")
        candidates = (
            self.OFFICIAL_ENTRY_URL,
            "https://www.ilga.gov/legislation/ilcs/ilcs.asp",
            "https://ilga.gov/Legislation/ILCS/Chapters",
        )
        request_bytes = b""
        response_bytes = b""
        index_body = b""
        index_url = self.OFFICIAL_ENTRY_URL
        units: List[Dict[str, str]] = []
        last_exc: Exception | None = None
        for candidate in candidates:
            try:
                request_bytes, response_bytes, index_body = self._official_http_get(candidate)
            except RuntimeError as exc:
                last_exc = exc
                continue
            html = index_body.decode("utf-8", errors="replace")
            units = self._parse_official_chapter_index(html, candidate)
            if len(units) >= 3:
                index_url = candidate
                last_exc = None
                break
            last_exc = RuntimeError(
                f"official Illinois chapter index is incomplete at {candidate}: {len(units)} units"
            )
        if len(units) < 3:
            raise RuntimeError(
                f"official Illinois chapter index is incomplete: {len(units)} units"
                + (f" ({last_exc})" if last_exc else "")
            )
        rows = tuple(
            {
                "canonical_key": unit["canonical_key"],
                "source_url": unit["source_url"],
                "text": unit["text"],
            }
            for unit in units
        )
        catalog = "\n".join(
            f"{unit['canonical_key']}\t{unit['source_url']}\t{unit['label']}"
            for unit in units
        ).encode("utf-8")
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
            jurisdiction_code="IL",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("IL", IllinoisScraper)
