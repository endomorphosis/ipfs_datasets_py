"""Scraper for Kansas state laws from the official legislature website."""

import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class KansasScraper(BaseStateScraper):
    """Scraper for Kansas state laws from https://www.kslegislature.gov."""

    OFFICIAL_DOMAIN = "www.kslegislature.gov"
    OFFICIAL_ENTRY_PATH = "/laws/"
    OFFICIAL_ENTRY_URL = "https://www.kslegislature.gov/laws/"
    _OFFICIAL_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
    _OFFICIAL_USER_AGENT = "ipfs-datasets-kansas-statutes-scraper/2.0"
    _CHAPTER_RE = re.compile(r"/laws/[0-9a-z]{3,4}_000_0000_chapter/?$", re.IGNORECASE)
    _CHAPTER_TOKEN_RE = re.compile(
        r"/laws/(?P<token>[0-9a-z]{3,4})_000_0000_chapter/?$",
        re.IGNORECASE,
    )
    _ARTICLE_RE = re.compile(
        r"/[0-9a-z]{3,4}_000_0000_chapter/[0-9a-z]{3,4}_[0-9a-z]{3,4}_0000_article/?$",
        re.IGNORECASE,
    )
    _SECTION_RE = re.compile(
        r"/[0-9a-z]{3,4}_000_0000_chapter/[0-9a-z]{3,4}_[0-9a-z]{3,4}_0000_article/"
        r"[0-9a-z]{3,4}_[0-9a-z]{3,4}_[0-9a-z]{4,5}_section/"
        r"[0-9a-z]{3,4}_[0-9a-z]{3,4}_[0-9a-z]{4,5}_k/?$",
        re.IGNORECASE,
    )
    _CATALOG_FRONT_MATTER_META_EXCEPTIONS: ClassVar[
        dict[str, tuple[str, str]]
    ] = {
        "94-00": (
            "94-100",
            (
                "/094_000_0000_chapter/094_000_0000_article/"
                "094_000_0000_section/094_000_0000_k/"
            ),
        ),
        "94-9000": (
            "",
            (
                "/094_000_0000_chapter/094_090_0000_article/"
                "094_090_0000_section/094_090_0000_k/"
            ),
        ),
        "95-00": (
            "95-001",
            (
                "/095_000_0000_chapter/095_000_0000_article/"
                "095_000_0000_section/095_000_0000_k/"
            ),
        ),
    }

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind the official HTML parser and exact closure seam to receipts."""

        from . import kansas_section, strict_frontier_closure

        return (kansas_section, strict_frontier_closure)

    def get_base_url(self) -> str:
        """Return the base URL for Kansas's legislative website."""
        return "https://www.kslegislature.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Kansas."""
        return [
            {
                "name": "Kansas Statutes",
                "url": f"{self.get_base_url()}/laws/",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Kansas statutes directly from official chapter/article/section pages."""
        limit = max(1, int(max_statutes)) if max_statutes else None
        from .kansas_constitution import (
            configured_constitution_html_path,
            parse_kansas_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if (
            constitution_path is not None
            or "constitution" in str(code_name or "").lower()
        ):
            if constitution_path is not None:
                constitution_rows = parse_kansas_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Kansas Constitution",
                    max_statutes=limit,
                )
                return (
                    constitution_rows
                    if limit is None
                    else constitution_rows[: int(limit)]
                )
        from .kansas_section import (
            configured_section_html_path,
            parse_kansas_section_html,
        )

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_kansas_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.kslegislature.gov/b2025_26/laws/",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        statutes: List[NormalizedStatute] = []
        chapter_links = await self._discover_chapter_links(code_url)
        self.logger.info(
            "Kansas official index: discovered %s chapter links", len(chapter_links)
        )

        if limit is None:
            if not chapter_links:
                raise RuntimeError(
                    "Kansas official root index returned no chapter frontier"
                )
            return await self._scrape_official_frontier(
                code_name=code_name,
                chapter_links=chapter_links,
            )

        for chapter_index, (chapter_url, chapter_label) in enumerate(
            chapter_links, start=1
        ):
            if limit is not None and len(statutes) >= limit:
                break
            article_links = await self._discover_article_links(chapter_url)
            self.logger.info(
                "Kansas official index: chapter=%s index=%s/%s articles=%s statutes_so_far=%s",
                chapter_label,
                chapter_index,
                len(chapter_links),
                len(article_links),
                len(statutes),
            )
            for article_url, article_label in article_links:
                if limit is not None and len(statutes) >= limit:
                    break
                section_links = await self._discover_section_links(article_url)
                for section_url, section_label in section_links:
                    if limit is not None and len(statutes) >= limit:
                        break
                    statute = await self._parse_section_page(
                        code_name=code_name,
                        section_url=section_url,
                        section_label=section_label,
                        chapter_label=chapter_label,
                        article_label=article_label,
                    )
                    if statute is not None:
                        statutes.append(statute)

        if not statutes:
            self.logger.warning(
                "Kansas official direct crawl returned no statutes; skipping generic recovery fallback"
            )
        return statutes[:limit] if limit is not None else statutes

    async def _fetch_official_ks_html(self, url: str, timeout_seconds: int = 18) -> str:
        timeout = max(1, int(timeout_seconds or 18))
        payload = await self._fetch_parser_input_with_transport(
            url,
            headers=self._official_request_headers(),
            timeout_seconds=timeout,
            allow_archival_fallback=True,
            media_type="text/html",
            provider="requests_direct",
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    @classmethod
    def _official_request_headers(cls) -> Dict[str, str]:
        return {
            "User-Agent": cls._OFFICIAL_USER_AGENT,
            "Accept": cls._OFFICIAL_ACCEPT,
        }

    @classmethod
    def _official_sanitized_request(cls, url: str) -> Dict[str, object]:
        return {
            "headers": {"Accept": cls._OFFICIAL_ACCEPT},
            "method": "GET",
            "url": url,
        }

    async def _discover_chapter_links(self, code_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(code_url, self._CHAPTER_RE)

    async def _discover_article_links(self, chapter_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(chapter_url, self._ARTICLE_RE)

    async def _discover_section_links(self, article_url: str) -> List[Tuple[str, str]]:
        return await self._discover_links(article_url, self._SECTION_RE)

    async def _discover_links(
        self, page_url: str, pattern: re.Pattern[str]
    ) -> List[Tuple[str, str]]:
        html = await self._fetch_official_ks_html(page_url)
        if pattern is self._CHAPTER_RE:
            self._last_kansas_catalog_input = {
                "content_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                "payload": html.encode("utf-8"),
                "source_url": self._canonical_fetch_url(page_url),
            }
        return self._links_from_html(html, page_url=page_url, pattern=pattern)

    def _links_from_html(
        self,
        html: str,
        *,
        page_url: str,
        pattern: re.Pattern[str],
    ) -> List[Tuple[str, str]]:
        """Parse one already-retained Kansas hierarchy page."""

        if not html:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        from .kansas_section import article_rows, chapter_rows, section_rows

        if pattern is self._CHAPTER_RE:
            listed = chapter_rows(html, base_url=page_url)
        elif pattern is self._ARTICLE_RE:
            listed = article_rows(html, base_url=page_url)
        elif pattern is self._SECTION_RE:
            listed = section_rows(html, base_url=page_url)
        else:
            listed = []
        if listed:
            return [
                (url.rstrip("/") + "/", name or number) for number, name, url in listed
            ]
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, str(anchor.get("href") or "").strip())
            normalized = href.rstrip("/") + "/"
            if not pattern.search(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            out.append((normalized, label or normalized.rstrip("/").rsplit("/", 1)[-1]))
        return out

    def _kansas_frontier_batch_size(self) -> int:
        return max(
            1,
            min(
                512,
                int(
                    self._env_int(
                        "STATE_SCRAPER_KS_FRONTIER_BATCH_SIZE",
                        default=64,
                    )
                    or 64
                ),
            ),
        )

    def _kansas_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                int(
                    self._env_int(
                        "STATE_SCRAPER_KS_FRONTIER_CONCURRENCY",
                        default=8,
                    )
                    or 8
                ),
            ),
        )

    async def _fetch_kansas_frontier_batch(
        self,
        urls: List[str],
        *,
        frontier_name: str,
    ) -> List[bytes]:
        """Fetch one aligned Kansas frontier through the shared WARC seam."""

        if not urls:
            return []
        requested = list(urls)
        if len(set(requested)) != len(requested):
            raise RuntimeError(
                f"Kansas {frontier_name} frontier contains duplicate URLs"
            )

        canonical_urls, retained_headerless_urls = (
            self._kansas_frontier_identity_partitions(requested)
        )
        payload_by_url: Dict[str, bytes] = {}
        if canonical_urls:
            payload_by_url.update(
                await self._fetch_kansas_identity_partition(
                    canonical_urls,
                    frontier_name=frontier_name,
                    headers=self._official_request_headers(),
                    require_retained_only=False,
                )
            )
        if retained_headerless_urls:
            payload_by_url.update(
                await self._fetch_kansas_identity_partition(
                    retained_headerless_urls,
                    frontier_name=frontier_name,
                    headers=None,
                    require_retained_only=True,
                )
            )
        if set(payload_by_url) != set(requested):
            raise RuntimeError(
                f"Kansas {frontier_name} frontier lost an exact request partition"
            )
        return [payload_by_url[url] for url in requested]

    def _kansas_frontier_identity_partitions(
        self,
        requested: List[str],
    ) -> Tuple[List[str], List[str]]:
        """Choose one actually retained request identity for every Kansas URL.

        The stopped v6 crawl retained some hierarchy pages under the shared
        plural fetcher's historical headerless identity.  Prefer the canonical
        singleton identity whenever it exists; use headerless replay only for
        URLs that have no canonical receipt.  Unseen URLs always use canonical
        headers, so the two request hashes are never treated as equivalent.
        """

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            return list(requested), []
        cache_key = id(ledger)
        cached = getattr(self, "_kansas_retained_request_identities", None)
        if not isinstance(cached, tuple) or len(cached) != 3 or cached[0] != cache_key:
            ledger.refresh_existing_entries()
            canonical_retained: set[str] = set()
            headerless_retained: set[str] = set()
            for retained in ledger.entries:
                receipt = retained.receipt
                url = self._canonical_fetch_url(str(receipt.endpoint or ""))
                request = receipt.sanitized_request
                if not url or not isinstance(request, Mapping):
                    continue
                if dict(request) == self._official_sanitized_request(url):
                    canonical_retained.add(url)
                elif dict(request) == {"method": "GET", "url": url}:
                    headerless_retained.add(url)
            cached = (cache_key, canonical_retained, headerless_retained)
            self._kansas_retained_request_identities = cached
        canonical_retained = cached[1]
        headerless_retained = cached[2]
        canonical_urls: List[str] = []
        retained_headerless_urls: List[str] = []
        for url in requested:
            if url in canonical_retained:
                canonical_urls.append(url)
                continue
            if url in headerless_retained:
                retained_headerless_urls.append(url)
            else:
                canonical_urls.append(url)
        return canonical_urls, retained_headerless_urls

    async def _fetch_kansas_identity_partition(
        self,
        requested: List[str],
        *,
        frontier_name: str,
        headers: Optional[Dict[str, str]],
        require_retained_only: bool,
    ) -> Dict[str, bytes]:
        fetch_kwargs = {
            "timeout_seconds": 18,
            "media_type": "text/html",
            "max_concurrency": self._kansas_frontier_concurrency(),
            "prefer_direct": True,
            "common_crawl_domain_terms": (self.OFFICIAL_DOMAIN,),
            "common_crawl_url_terms": (self.OFFICIAL_ENTRY_PATH,),
            "common_crawl_mime_terms": ("html",),
        }
        if headers is not None:
            fetch_kwargs["headers"] = dict(headers)
        batch = await self._fetch_page_contents_with_archival_fallback(
            requested,
            **fetch_kwargs,
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
                f"Kansas {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Kansas {frontier_name} frontier changed URL order or identity"
            )
        if (
            require_retained_only
            and int(batch.stats.get("network_requested_pages", -1)) != 0
        ):
            raise RuntimeError(
                f"Kansas {frontier_name} headerless partition was not exact retained replay"
            )

        failures: List[Dict[str, str]] = []
        evidence_by_url = dict(getattr(self, "_kansas_input_evidence_by_url", {}))
        for url, payload, error, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            if error is not None:
                failures.append({"url": url, "error": str(error) or "worker error"})
            elif not isinstance(payload, (bytes, bytearray, memoryview)):
                failures.append(
                    {
                        "url": url,
                        "error": f"invalid parser input type: {type(payload).__name__}",
                    }
                )
            elif not payload:
                failures.append({"url": url, "error": "empty parser input"})
            else:
                raw = bytes(payload)
                receipt_dict = dict(receipt or {})
                envelope_body = getattr(envelope, "body", None)
                if envelope_body is not None and bytes(envelope_body) != raw:
                    failures.append(
                        {"url": url, "error": "parser-input envelope body drift"}
                    )
                    continue
                observed_digest = (
                    str(receipt_dict.get("content_sha256") or "").strip().lower()
                )
                content_sha256 = hashlib.sha256(raw).hexdigest()
                if observed_digest and observed_digest != content_sha256:
                    failures.append(
                        {"url": url, "error": "transport receipt digest drift"}
                    )
                    continue
                evidence_by_url[url] = {
                    "content_sha256": content_sha256,
                    "parser_input_receipt_sha256": str(
                        receipt_dict.get("receipt_sha256") or ""
                    ),
                    "source_transport": str(
                        receipt_dict.get("source_transport")
                        or receipt_dict.get("transport_kind")
                        or ""
                    ),
                }
        if failures:
            raise RuntimeError(
                f"Kansas {frontier_name} frontier is incomplete: {failures[:5]}"
            )
        self._kansas_input_evidence_by_url = evidence_by_url
        stats_rows = list(getattr(self, "_kansas_frontier_batch_stats", []))
        stats_rows.append(
            {
                "frontier_name": frontier_name,
                "requested_pages": len(requested),
                "request_identity": (
                    "canonical_headers"
                    if headers is not None
                    else "retained_headerless"
                ),
                **dict(batch.stats or {}),
            }
        )
        self._kansas_frontier_batch_stats = stats_rows
        return {
            url: bytes(payload)
            for url, payload in zip(batch.urls, batch.payloads, strict=True)
        }

    async def _fetch_kansas_frontier_in_chunks(
        self,
        urls: List[str],
        *,
        frontier_name: str,
    ) -> List[bytes]:
        payloads: List[bytes] = []
        batch_size = self._kansas_frontier_batch_size()
        for batch_start in range(0, len(urls), batch_size):
            payloads.extend(
                await self._fetch_kansas_frontier_batch(
                    urls[batch_start : batch_start + batch_size],
                    frontier_name=frontier_name,
                )
            )
        return payloads

    @staticmethod
    def _kansas_report_digest(rows: Sequence[Mapping[str, Any]]) -> str:
        """Digest an ordered, source-derived Kansas frontier inventory."""

        return hashlib.sha256(
            json.dumps(
                [dict(row) for row in rows],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _kansas_exact_frontier(
        self,
        *,
        catalog_content_sha256: str,
        chapter_reports: Sequence[Mapping[str, Any]],
        article_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Build the exact root/chapter/article/section closure contract."""

        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        if not chapter_reports or not article_reports or not section_reports:
            raise RuntimeError("Kansas exact frontier has an empty hierarchy level")
        for label, reports in (
            ("chapter", chapter_reports),
            ("article", article_reports),
            ("section", section_reports),
        ):
            urls = [str(row.get("source_url") or "") for row in reports]
            if any(not url for url in urls) or len(urls) != len(set(urls)):
                raise RuntimeError(
                    f"Kansas exact {label} frontier repeated or lost source URLs"
                )

        operative = sum(
            str(row.get("disposition") or "") == "operative" for row in section_reports
        )
        terminal_rows = [
            row
            for row in section_reports
            if str(row.get("disposition") or "") != "operative"
        ]
        terminal_dispositions: Dict[str, int] = {}
        for row in terminal_rows:
            disposition = str(row.get("disposition") or "unclassified")
            terminal_dispositions[disposition] = (
                terminal_dispositions.get(disposition, 0) + 1
            )
        covered_identity_keys: set[Tuple[str, ...]] = set()
        aggregate_source_documents = 0
        for row in section_reports:
            canonical_identity = str(row.get("canonical_identity") or "")
            additional = row.get("additional_covered_identities") or []
            if not isinstance(additional, Sequence) or isinstance(
                additional,
                (str, bytes, bytearray),
            ):
                raise RuntimeError(
                    "Kansas exact section frontier has malformed covered identities"
                )
            identities = ([canonical_identity] if canonical_identity else []) + [
                str(value) for value in additional
            ]
            if additional:
                aggregate_source_documents += 1
            for identity in identities:
                identity_key = self._kansas_identity_key(identity)
                if not identity_key or identity_key in covered_identity_keys:
                    raise RuntimeError(
                        "Kansas exact section frontier repeated a covered identity: "
                        f"{identity}"
                    )
                covered_identity_keys.add(identity_key)
        disposition = {
            "discovered": len(section_reports),
            "fetched": operative,
            "excluded": len(terminal_rows),
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if (
            disposition["discovered"]
            != disposition["fetched"] + disposition["excluded"]
        ):
            raise RuntimeError("Kansas exact section disposition did not close")
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "article_document_count": len(article_reports),
            "article_frontier_sha256": self._kansas_report_digest(article_reports),
            "aggregate_source_document_count": aggregate_source_documents,
            "bundle_closed": False,
            "catalog_content_sha256": str(catalog_content_sha256),
            "chapter_document_count": len(chapter_reports),
            "chapter_frontier_sha256": self._kansas_report_digest(chapter_reports),
            "closed": True,
            "covered_section_identity_count": len(covered_identity_keys),
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": len(section_reports),
            "pagination_closed": True,
            "schema_version": "kansas-source-derived-html-frontier-v1",
            "scope_closed": True,
            "section_input_frontier_sha256": self._kansas_report_digest(
                section_reports
            ),
            "source_section_count": len(section_reports),
            "terminal_dispositions": dict(sorted(terminal_dispositions.items())),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(section_reports),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _replay_kansas_retained_inputs(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
    ) -> List[bytes]:
        """Replay exact Kansas inputs locally, never entering a network path."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Kansas retained replay requires an attached ledger")
        payloads: List[bytes] = []
        for source_url in urls:
            url = self._canonical_fetch_url(source_url)
            retained = ledger.replay_retained_parser_input(
                official_url=url,
                sanitized_request=self._official_sanitized_request(url),
            )
            if retained is None:
                retained = ledger.replay_retained_parser_input(
                    official_url=url,
                    sanitized_request={"method": "GET", "url": url},
                )
            if retained is None:
                raise RuntimeError(
                    f"Kansas {frontier_name} retained replay is missing: {url}"
                )
            envelope = getattr(retained, "envelope", None)
            body = getattr(envelope, "body", None)
            raw = bytes(body or b"")
            if not raw:
                raise RuntimeError(
                    f"Kansas {frontier_name} retained replay is empty: {url}"
                )
            receipt = getattr(retained, "transport_receipt", None)
            if isinstance(receipt, Mapping):
                observed_url = str(
                    receipt.get("official_url") or receipt.get("endpoint") or ""
                ).strip()
                observed_digest = str(receipt.get("content_sha256") or "").strip()
                if observed_url and self._canonical_fetch_url(observed_url) != url:
                    raise RuntimeError(
                        f"Kansas {frontier_name} retained URL identity changed: {url}"
                    )
                if (
                    observed_digest
                    and observed_digest != hashlib.sha256(raw).hexdigest()
                ):
                    raise RuntimeError(
                        f"Kansas {frontier_name} retained digest changed: {url}"
                    )
            payloads.append(raw)
        return payloads

    async def _scrape_official_frontier(
        self,
        *,
        code_name: str,
        chapter_links: List[Tuple[str, str]],
    ) -> List[NormalizedStatute]:
        """Breadth-first acquisition of the uncapped official Kansas tree."""

        self._kansas_frontier_batch_stats = []
        self._kansas_input_evidence_by_url = {}
        chapter_urls = [url for url, _label in chapter_links]
        chapter_payloads = await self._fetch_kansas_frontier_in_chunks(
            chapter_urls,
            frontier_name="chapter-index",
        )

        article_frontier: List[Tuple[str, str, str]] = []
        seen_articles: set[str] = set()
        chapter_reports: List[Dict[str, Any]] = []
        for (chapter_url, chapter_label), raw in zip(
            chapter_links,
            chapter_payloads,
            strict=True,
        ):
            article_links = self._links_from_html(
                raw.decode("utf-8", errors="replace"),
                page_url=chapter_url,
                pattern=self._ARTICLE_RE,
            )
            if not article_links:
                raise RuntimeError(
                    "Kansas official chapter page returned no article links: "
                    f"{chapter_url}"
                )
            chapter_reports.append(
                {
                    "article_count": len(article_links),
                    "chapter_label": chapter_label,
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_url": chapter_url,
                }
            )
            for article_url, article_label in article_links:
                if article_url in seen_articles:
                    raise RuntimeError(
                        "Kansas official chapter frontier repeated an article URL: "
                        f"{article_url}"
                    )
                seen_articles.add(article_url)
                article_frontier.append((article_url, article_label, chapter_label))
        if not article_frontier:
            raise RuntimeError(
                "Kansas official chapter frontier returned no article links"
            )

        article_urls = [url for url, _article_label, _chapter_label in article_frontier]
        article_payloads = await self._fetch_kansas_frontier_in_chunks(
            article_urls,
            frontier_name="article-index",
        )

        section_frontier: List[Tuple[str, str, str, str]] = []
        seen_sections: set[str] = set()
        article_reports: List[Dict[str, Any]] = []
        for (article_url, article_label, chapter_label), raw in zip(
            article_frontier,
            article_payloads,
            strict=True,
        ):
            section_links = self._links_from_html(
                raw.decode("utf-8", errors="replace"),
                page_url=article_url,
                pattern=self._SECTION_RE,
            )
            if not section_links:
                raise RuntimeError(
                    "Kansas official article page returned no section links: "
                    f"{article_url}"
                )
            article_reports.append(
                {
                    "article_label": article_label,
                    "chapter_label": chapter_label,
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "section_count": len(section_links),
                    "source_url": article_url,
                }
            )
            for section_url, section_label in section_links:
                if section_url in seen_sections:
                    raise RuntimeError(
                        "Kansas official article frontier repeated a section URL: "
                        f"{section_url}"
                    )
                seen_sections.add(section_url)
                section_frontier.append(
                    (section_url, section_label, chapter_label, article_label)
                )
        if not section_frontier:
            raise RuntimeError(
                "Kansas official article frontier returned no section links"
            )
        catalog_identity_keys: set[Tuple[str, ...]] = set()
        for section_url, section_label, _chapter_label, _article_label in section_frontier:
            catalog_identity = self._section_number_from_label(section_label)
            catalog_key = self._kansas_identity_key(catalog_identity)
            if not catalog_identity or not catalog_key:
                raise RuntimeError(
                    "Kansas official article frontier has an unnumbered section: "
                    f"{section_url}"
                )
            if catalog_key in catalog_identity_keys:
                raise RuntimeError(
                    "Kansas official article frontier repeated a catalog identity: "
                    f"{catalog_identity}"
                )
            catalog_identity_keys.add(catalog_key)

        statutes: List[NormalizedStatute] = []
        section_reports: List[Dict[str, Any]] = []
        residual_sections: List[Dict[str, str]] = []
        seen_identities: set[str] = set()
        sections_scanned = 0
        batch_size = self._kansas_frontier_batch_size()
        from .kansas_section import classify_kansas_terminal_section_html

        for batch_start in range(0, len(section_frontier), batch_size):
            batch_links = section_frontier[batch_start : batch_start + batch_size]
            batch_urls = [url for url, _section, _chapter, _article in batch_links]
            batch_payloads = await self._fetch_kansas_frontier_batch(
                batch_urls,
                frontier_name="section",
            )
            for (
                section_url,
                section_label,
                chapter_label,
                article_label,
            ), raw in zip(batch_links, batch_payloads, strict=True):
                sections_scanned += 1
                decoded = raw.decode("utf-8", errors="replace")
                statute = self._parse_section_html(
                    code_name=code_name,
                    section_url=section_url,
                    section_label=section_label,
                    chapter_label=chapter_label,
                    article_label=article_label,
                    html=decoded,
                )
                if statute is not None:
                    expected_identity = self._section_number_from_label(section_label)
                    if expected_identity:
                        statute = self._reconcile_kansas_catalog_identity(
                            statute,
                            expected_identity=expected_identity,
                            source_url=section_url,
                            catalog_identity_keys=catalog_identity_keys,
                        )
                    identity = str(statute.section_number or "").strip().casefold()
                    if not identity or identity in seen_identities:
                        raise RuntimeError(
                            "Kansas normalized frontier repeated or lost a section "
                            f"identity: {statute.section_number}"
                        )
                    seen_identities.add(identity)
                    evidence = dict(
                        getattr(self, "_kansas_input_evidence_by_url", {}).get(
                            section_url, {}
                        )
                    )
                    statute.structured_data = {
                        **dict(statute.structured_data or {}),
                        "content_sha256": hashlib.sha256(raw).hexdigest(),
                        "parser_input_receipt_sha256": str(
                            evidence.get("parser_input_receipt_sha256") or ""
                        ),
                        "source_transport": str(evidence.get("source_transport") or ""),
                    }
                    statutes.append(statute)
                    report: Dict[str, Any] = {
                        "canonical_identity": identity,
                        "content_sha256": hashlib.sha256(raw).hexdigest(),
                        "disposition": "operative",
                        "section_label": section_label,
                        "source_url": section_url,
                    }
                    covered = statute.structured_data.get(
                        "source_covered_section_numbers"
                    )
                    if (
                        isinstance(covered, Sequence)
                        and not isinstance(covered, (str, bytes, bytearray))
                        and len(covered) > 1
                    ):
                        report["additional_covered_identities"] = [
                            str(value) for value in covered[1:]
                        ]
                    section_reports.append(report)
                else:
                    terminal = classify_kansas_terminal_section_html(decoded)
                    if terminal:
                        section_reports.append(
                            {
                                "canonical_identity": "",
                                "content_sha256": hashlib.sha256(raw).hexdigest(),
                                "disposition": terminal,
                                "section_label": section_label,
                                "source_url": section_url,
                            }
                        )
                    else:
                        residual_sections.append(
                            {
                                "section_label": section_label,
                                "source_url": section_url,
                            }
                        )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="kansas:section-progress",
                extra={
                    "chapters_scanned": int(len(chapter_links)),
                    "discovered_chapters": int(len(chapter_links)),
                    "articles_scanned": int(len(article_frontier)),
                    "discovered_articles": int(len(article_frontier)),
                    "sections_scanned": int(sections_scanned),
                    "discovered_sections": int(len(section_frontier)),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        if residual_sections:
            raise RuntimeError(
                "Kansas official section frontier has unclassified residuals: "
                f"{residual_sections[:10]}"
            )
        if not statutes:
            raise RuntimeError(
                "Kansas official section frontier produced no normalized statutes"
            )

        catalog_input = getattr(self, "_last_kansas_catalog_input", None)
        if not isinstance(catalog_input, Mapping):
            raise RuntimeError(
                "Kansas official root catalog input was not retained before closure"
            )
        catalog_url = self._canonical_fetch_url(
            str(catalog_input.get("source_url") or "")
        )
        if catalog_url != self._canonical_fetch_url(self.OFFICIAL_ENTRY_URL):
            raise RuntimeError("Kansas official root catalog identity changed")
        catalog_digest = str(catalog_input.get("content_sha256") or "")
        if len(catalog_digest) != 64:
            raise RuntimeError("Kansas official root catalog lacks a content digest")
        exact_frontier = self._kansas_exact_frontier(
            catalog_content_sha256=catalog_digest,
            chapter_reports=chapter_reports,
            article_reports=article_reports,
            section_reports=section_reports,
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        self._last_kansas_full_frontier = {
            "article_reports": article_reports,
            "boundary_first": section_frontier[0][0],
            "boundary_last": section_frontier[-1][0],
            "catalog_url": catalog_url,
            "chapter_reports": chapter_reports,
            "code_name": code_name,
            "frontier": exact_frontier,
            "observed_at": observed_at,
            "section_reports": section_reports,
            "transport_batch_stats": list(self._kansas_frontier_batch_stats),
        }
        self._last_kansas_strict_closure = {
            "article_documents": len(article_reports),
            "chapter_documents": len(chapter_reports),
            "closed": True,
            "frontier": exact_frontier,
            "observed_at": observed_at,
            "operative_sections": len(statutes),
            "schema": "kansas-source-derived-strict-closure-v1",
            "source_sections": len(section_reports),
            "terminal_sections": len(section_reports) - len(statutes),
            "unclassified_sections": 0,
        }

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="kansas:complete",
            force=True,
            extra={
                "chapters_scanned": int(len(chapter_links)),
                "discovered_chapters": int(len(chapter_links)),
                "articles_scanned": int(len(article_frontier)),
                "discovered_articles": int(len(article_frontier)),
                "sections_scanned": int(sections_scanned),
                "discovered_sections": int(len(section_frontier)),
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
        """Reparse every retained Kansas hierarchy input and seal parity."""

        first = getattr(self, "_last_kansas_full_frontier", None)
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Kansas frontier closure requires an attached ledger")
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Kansas source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        first_frontier = first.get("frontier")
        chapter_reports_raw = first.get("chapter_reports")
        article_reports_raw = first.get("article_reports")
        section_reports_raw = first.get("section_reports")
        for label, reports in (
            ("chapter", chapter_reports_raw),
            ("article", article_reports_raw),
            ("section", section_reports_raw),
        ):
            if (
                not isinstance(reports, Sequence)
                or isinstance(reports, (str, bytes, bytearray))
                or not reports
                or any(not isinstance(row, Mapping) for row in reports)
            ):
                raise RuntimeError(f"Kansas first exact {label} frontier is incomplete")
        if not isinstance(first_frontier, Mapping):
            raise RuntimeError("Kansas first exact frontier is incomplete")
        chapter_reports = [dict(row) for row in chapter_reports_raw]
        article_reports = [dict(row) for row in article_reports_raw]
        section_reports = [dict(row) for row in section_reports_raw]

        catalog_url = self._canonical_fetch_url(
            str(first.get("catalog_url") or self.OFFICIAL_ENTRY_URL)
        )
        catalog_raw = self._replay_kansas_retained_inputs(
            [catalog_url],
            frontier_name="root-catalog",
        )[0]
        catalog_html = catalog_raw.decode("utf-8", errors="replace")
        catalog_digest = hashlib.sha256(catalog_html.encode("utf-8")).hexdigest()
        if catalog_digest != str(first_frontier.get("catalog_content_sha256") or ""):
            raise RuntimeError("Kansas retained root catalog digest changed")
        replay_chapter_links = self._links_from_html(
            catalog_html,
            page_url=catalog_url,
            pattern=self._CHAPTER_RE,
        )
        expected_chapter_links = [
            (str(row.get("source_url") or ""), str(row.get("chapter_label") or ""))
            for row in chapter_reports
        ]
        if replay_chapter_links != expected_chapter_links:
            raise RuntimeError("Kansas retained chapter catalog membership changed")

        chapter_payloads = self._replay_kansas_retained_inputs(
            [url for url, _label in replay_chapter_links],
            frontier_name="chapter-pages",
        )
        replay_chapter_reports: List[Dict[str, Any]] = []
        replay_article_frontier: List[Tuple[str, str, str]] = []
        seen_articles: set[str] = set()
        for (chapter_url, chapter_label), raw in zip(
            replay_chapter_links,
            chapter_payloads,
            strict=True,
        ):
            article_links = self._links_from_html(
                raw.decode("utf-8", errors="replace"),
                page_url=chapter_url,
                pattern=self._ARTICLE_RE,
            )
            replay_chapter_reports.append(
                {
                    "article_count": len(article_links),
                    "chapter_label": chapter_label,
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_url": chapter_url,
                }
            )
            for article_url, article_label in article_links:
                if article_url in seen_articles:
                    raise RuntimeError(
                        f"Kansas retained replay repeated an article URL: {article_url}"
                    )
                seen_articles.add(article_url)
                replay_article_frontier.append(
                    (article_url, article_label, chapter_label)
                )
        if replay_chapter_reports != chapter_reports:
            raise RuntimeError("Kansas retained chapter inventories changed")

        expected_article_frontier = [
            (
                str(row.get("source_url") or ""),
                str(row.get("article_label") or ""),
                str(row.get("chapter_label") or ""),
            )
            for row in article_reports
        ]
        if replay_article_frontier != expected_article_frontier:
            raise RuntimeError("Kansas retained article membership changed")
        article_payloads = self._replay_kansas_retained_inputs(
            [url for url, _article, _chapter in replay_article_frontier],
            frontier_name="article-pages",
        )
        replay_article_reports: List[Dict[str, Any]] = []
        replay_section_frontier: List[Tuple[str, str, str, str]] = []
        seen_sections: set[str] = set()
        for (article_url, article_label, chapter_label), raw in zip(
            replay_article_frontier,
            article_payloads,
            strict=True,
        ):
            section_links = self._links_from_html(
                raw.decode("utf-8", errors="replace"),
                page_url=article_url,
                pattern=self._SECTION_RE,
            )
            replay_article_reports.append(
                {
                    "article_label": article_label,
                    "chapter_label": chapter_label,
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "section_count": len(section_links),
                    "source_url": article_url,
                }
            )
            for section_url, section_label in section_links:
                if section_url in seen_sections:
                    raise RuntimeError(
                        f"Kansas retained replay repeated a section URL: {section_url}"
                    )
                seen_sections.add(section_url)
                replay_section_frontier.append(
                    (section_url, section_label, chapter_label, article_label)
                )
        if replay_article_reports != article_reports:
            raise RuntimeError("Kansas retained article inventories changed")

        expected_section_frontier = [
            (
                str(row.get("source_url") or ""),
                str(row.get("section_label") or ""),
            )
            for row in section_reports
        ]
        if [
            (url, section_label)
            for url, section_label, _chapter, _article in replay_section_frontier
        ] != expected_section_frontier:
            raise RuntimeError("Kansas retained section membership changed")
        catalog_identity_keys: set[Tuple[str, ...]] = set()
        for section_url, section_label, _chapter, _article in replay_section_frontier:
            catalog_identity = self._section_number_from_label(section_label)
            catalog_key = self._kansas_identity_key(catalog_identity)
            if not catalog_identity or not catalog_key:
                raise RuntimeError(
                    "Kansas retained article frontier has an unnumbered section: "
                    f"{section_url}"
                )
            if catalog_key in catalog_identity_keys:
                raise RuntimeError(
                    "Kansas retained article frontier repeated a catalog identity: "
                    f"{catalog_identity}"
                )
            catalog_identity_keys.add(catalog_key)

        from .kansas_section import classify_kansas_terminal_section_html

        code_name = str(first.get("code_name") or "Kansas Statutes")
        replay_rows: List[NormalizedStatute] = []
        replay_section_reports: List[Dict[str, Any]] = []
        seen_identities: set[str] = set()
        batch_size = self._kansas_frontier_batch_size()
        for start in range(0, len(replay_section_frontier), batch_size):
            selected = replay_section_frontier[start : start + batch_size]
            payloads = self._replay_kansas_retained_inputs(
                [url for url, _section, _chapter, _article in selected],
                frontier_name=f"section-pages-{start + 1}-{start + len(selected)}",
            )
            for (
                section_url,
                section_label,
                chapter_label,
                article_label,
            ), raw in zip(selected, payloads, strict=True):
                decoded = raw.decode("utf-8", errors="replace")
                statute = self._parse_section_html(
                    code_name=code_name,
                    section_url=section_url,
                    section_label=section_label,
                    chapter_label=chapter_label,
                    article_label=article_label,
                    html=decoded,
                )
                if statute is not None:
                    expected_identity = self._section_number_from_label(section_label)
                    if expected_identity:
                        statute = self._reconcile_kansas_catalog_identity(
                            statute,
                            expected_identity=expected_identity,
                            source_url=section_url,
                            catalog_identity_keys=catalog_identity_keys,
                        )
                    identity = str(statute.section_number or "").strip().casefold()
                    if not identity or identity in seen_identities:
                        raise RuntimeError(
                            "Kansas retained replay repeated or lost a canonical "
                            f"identity: {statute.section_number}"
                        )
                    seen_identities.add(identity)
                    disposition = "operative"
                    replay_rows.append(statute)
                else:
                    identity = ""
                    disposition = classify_kansas_terminal_section_html(decoded)
                    if not disposition:
                        raise RuntimeError(
                            "Kansas retained replay produced an unclassified section: "
                            f"{section_url}"
                        )
                report = {
                    "canonical_identity": identity,
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "disposition": disposition,
                    "section_label": section_label,
                    "source_url": section_url,
                }
                if statute is not None:
                    covered = statute.structured_data.get(
                        "source_covered_section_numbers"
                    )
                    if (
                        isinstance(covered, Sequence)
                        and not isinstance(covered, (str, bytes, bytearray))
                        and len(covered) > 1
                    ):
                        report["additional_covered_identities"] = [
                            str(value) for value in covered[1:]
                        ]
                expected = section_reports[len(replay_section_reports)]
                if report != expected:
                    raise RuntimeError(
                        f"Kansas retained section inventory changed: {section_url}"
                    )
                replay_section_reports.append(report)

        replayed_frontier = self._kansas_exact_frontier(
            catalog_content_sha256=catalog_digest,
            chapter_reports=replay_chapter_reports,
            article_reports=replay_article_reports,
            section_reports=replay_section_reports,
        )
        from .strict_frontier_closure import retain_exact_state_frontier_closure

        batch_stats = list(first.get("transport_batch_stats") or [])
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="KS",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_ENTRY_URL,
            observed_at=str(first.get("observed_at") or ""),
            legal_as_of=str(first.get("observed_at") or "")[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(section_reports),
            pagination_total=len(chapter_reports) + len(article_reports),
            transport={
                "fixture": False,
                "first_pass_request_batches": len(batch_stats),
                "first_pass_requested_pages": sum(
                    int(row.get("requested_pages") or 0)
                    for row in batch_stats
                    if isinstance(row, Mapping)
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html",
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "synthetic": False,
            },
        )

    async def _parse_section_page(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        chapter_label: str,
        article_label: str,
    ) -> Optional[NormalizedStatute]:
        html = await self._fetch_official_ks_html(section_url)
        return self._parse_section_html(
            code_name=code_name,
            section_url=section_url,
            section_label=section_label,
            chapter_label=chapter_label,
            article_label=article_label,
            html=html,
        )

    def _parse_section_html(
        self,
        *,
        code_name: str,
        section_url: str,
        section_label: str,
        chapter_label: str,
        article_label: str,
        html: str,
    ) -> Optional[NormalizedStatute]:
        """Parse a retained Kansas section body without fetching it again."""

        if not html:
            return None
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        from .kansas_section import (
            classify_kansas_terminal_section_html,
            parse_kansas_section_html,
        )

        if classify_kansas_terminal_section_html(html):
            return None

        catalog_number = self._section_number_from_label(section_label)

        parsed = parse_kansas_section_html(
            html,
            source_url=section_url,
            section_number=catalog_number,
            code_name=code_name,
        )
        if parsed is not None:
            chapter_number = (
                self._chapter_number_from_label(chapter_label)
                or catalog_number.split("-", 1)[0]
            )
            parsed.title_number = chapter_number
            parsed.title_name = chapter_label or None
            parsed.chapter_number = chapter_number
            parsed.chapter_name = chapter_label or None
            parsed.structured_data = {
                **dict(parsed.structured_data or {}),
                "article_label": article_label,
                "article_number": self._article_number_from_label(article_label),
                "source_catalog_section_label": section_label,
            }
            return parsed
        soup = BeautifulSoup(html, "html.parser")
        # Kansas renders the statute body in paragraph nodes outside an often-empty
        # #main container, so anchor parsing on the statute-specific classes.
        number = "".join(
            self._text_or_empty(node)
            for node in soup.select(".statute-body .stat_5f_number")
            if node.select_one(".stat_5f_number") is None
        ).rstrip(".")
        caption = self._text_or_empty(soup.select_one(".stat_5f_caption"))
        statute_paragraphs = [
            self._text_or_empty(node)
            for node in soup.select("p.p_pt")
            if self._text_or_empty(node)
        ]
        if statute_paragraphs:
            body = self._normalize_legal_text(" ".join(statute_paragraphs))
        else:
            main = soup.select_one("#main")
            main_text = self._text_or_empty(main) if main is not None else ""
            body = self._normalize_legal_text(
                main_text or soup.get_text(" ", strip=True)
            )
        if not number:
            number = catalog_number
        if not number or len(body) < 80:
            return None

        chapter_number = (
            self._chapter_number_from_label(chapter_label) or number.split("-", 1)[0]
        )
        article_number = self._article_number_from_label(article_label)
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"KS-{number}",
            code_name=code_name,
            title_number=chapter_number,
            title_name=chapter_label or None,
            chapter_number=chapter_number,
            chapter_name=chapter_label or None,
            section_number=number,
            section_name=caption or section_label or f"Section {number}",
            short_title=caption or None,
            full_text=body,
            legal_area=self._identify_legal_area(
                " ".join([caption, chapter_label, article_label])
            ),
            source_url=section_url,
            official_cite=f"K.S.A. {number}",
            structured_data={
                "source_kind": "official_kansas_statutes_html",
                "discovery_method": "official_chapter_article_section_index",
                "article_number": article_number,
                "article_label": article_label,
                "source_body_section_number": "",
                "source_catalog_section_label": section_label,
                "source_page_section_number": "",
                "source_page_section_number_present": False,
                "skip_hydrate": True,
            },
        )

    @staticmethod
    def _text_or_empty(node: object) -> str:
        if node is None:
            return ""
        try:
            return re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _chapter_number_from_label(label: str) -> str:
        match = re.search(
            r"\bChapter\s+([0-9a-z]+)", str(label or ""), flags=re.IGNORECASE
        )
        return match.group(1) if match else ""

    @staticmethod
    def _article_number_from_label(label: str) -> str:
        match = re.search(
            r"\bArticle\s+([0-9a-z]+)", str(label or ""), flags=re.IGNORECASE
        )
        return match.group(1) if match else ""

    @staticmethod
    def _section_number_from_label(label: str) -> str:
        match = re.match(
            r"\s*([0-9a-z]+-[0-9a-z,]+(?:-[0-9a-z,]+)*)",
            str(label or ""),
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else ""

    @staticmethod
    def _kansas_identity_key(value: str) -> Tuple[str, ...]:
        """Compare Kansas cite forms without conflating numeric components."""

        out: List[str] = []
        for token in re.findall(r"[0-9]+|[a-z]+", str(value or "").casefold()):
            out.append(str(int(token)) if token.isdigit() else token)
        return tuple(out)

    @classmethod
    def _kansas_identity_relation(cls, expected: str, observed: str) -> str:
        expected_text = str(expected or "").strip()
        observed_text = str(observed or "").strip()
        if not expected_text or not observed_text:
            return ""
        if expected_text.casefold() == observed_text.casefold():
            return "exact"
        identity_chars = re.compile(r"[^0-9a-z]+", re.IGNORECASE)
        if (
            identity_chars.sub("", expected_text).casefold()
            == identity_chars.sub("", observed_text).casefold()
        ):
            return "separator_only"
        if cls._kansas_identity_key(expected_text) == cls._kansas_identity_key(
            observed_text
        ):
            return "format_only"
        return ""

    @staticmethod
    def _kansas_aggregate_identities(
        page_number: str,
    ) -> tuple[str, list[str]] | None:
        """Expand an explicit official comma-list or bounded numeric range."""

        identity = (
            r"[0-9a-z]+-[0-9a-z]+(?:,[0-9a-z]+)*"
            r"(?:-[0-9a-z]+(?:,[0-9a-z]+)*)*"
        )
        text = str(page_number or "").strip().rstrip(".")
        range_match = re.fullmatch(
            rf"(?P<first>{identity})\s+(?:to|through)\s+"
            rf"(?P<last>{identity})",
            text,
            flags=re.IGNORECASE,
        )
        if range_match is not None:
            first = range_match.group("first")
            last = range_match.group("last")
            first_match = re.fullmatch(r"(?P<prefix>.*?)(?P<number>\d+)", first)
            last_match = re.fullmatch(r"(?P<prefix>.*?)(?P<number>\d+)", last)
            if first_match is not None and last_match is not None:
                if first_match.group("prefix").casefold() != last_match.group(
                    "prefix"
                ).casefold():
                    return None
                start = int(first_match.group("number"))
                stop = int(last_match.group("number"))
                if stop < start or stop - start > 1_000:
                    return None
                prefix = first_match.group("prefix")
                width = max(
                    len(first_match.group("number")),
                    len(last_match.group("number")),
                )
                return (
                    "inclusive_range",
                    [
                        f"{prefix}{number:0{width}d}"
                        for number in range(start, stop + 1)
                    ],
                )

            first_suffix = re.fullmatch(
                r"(?P<prefix>.*\d)(?P<suffix>[a-z])", first, flags=re.IGNORECASE
            )
            last_suffix = re.fullmatch(
                r"(?P<prefix>.*\d)(?P<suffix>[a-z])", last, flags=re.IGNORECASE
            )
            if first_suffix is None or last_suffix is None:
                return None
            if first_suffix.group("prefix").casefold() != last_suffix.group(
                "prefix"
            ).casefold():
                return None
            start = ord(first_suffix.group("suffix").casefold())
            stop = ord(last_suffix.group("suffix").casefold())
            if stop < start or stop - start > 25:
                return None
            prefix = first_suffix.group("prefix")
            return (
                "inclusive_alpha_suffix_range",
                [f"{prefix}{chr(value)}" for value in range(start, stop + 1)],
            )

        members = re.split(r",\s+(?=[0-9a-z]+-)", text, flags=re.IGNORECASE)
        if len(members) > 1 and all(
            re.fullmatch(identity, member, flags=re.IGNORECASE)
            for member in members
        ):
            return "explicit_list", members
        return None

    @classmethod
    def _reconcile_kansas_catalog_identity(
        cls,
        statute: NormalizedStatute,
        *,
        expected_identity: str,
        source_url: str,
        catalog_identity_keys: set[tuple[str, ...]] | None = None,
    ) -> NormalizedStatute:
        """Bind one body to its unique catalog cite using independent evidence.

        Kansas has punctuation variants, contextual ``§ n`` markers in its
        official appendices, and three source pages that cover an explicit
        list/range of sections in one body.  The article-catalog identity stays
        canonical; body and page-meta forms remain provenance.  A covered
        identity may not also have its own catalog locator, preventing shared
        bodies from becoming duplicate normalized rows.
        """

        expected = str(expected_identity or "").strip()
        structured = dict(statute.structured_data or {})
        observed = str(
            structured.get("source_body_section_number")
            if "source_body_section_number" in structured
            else statute.section_number
        ).strip()
        page_number_present = bool(
            structured.get("source_page_section_number_present", False)
        )
        page_number = str(structured.get("source_page_section_number") or "").strip()
        if not expected:
            raise RuntimeError(
                "Kansas section identity reconciliation lacks a source identity: "
                f"expected={expected!r} observed={observed!r} source={source_url}"
            )

        body_relation = cls._kansas_identity_relation(expected, observed)
        page_relation = cls._kansas_identity_relation(expected, page_number)
        reconciliation = body_relation
        covered_identities = [expected]
        aggregate_kind = ""

        aggregate = cls._kansas_aggregate_identities(page_number)
        if page_number_present and not page_relation and aggregate is not None:
            aggregate_kind, covered_identities = aggregate
            if not cls._kansas_identity_relation(expected, covered_identities[0]):
                aggregate_kind = ""
                covered_identities = [expected]
            else:
                observed_aggregate = re.sub(
                    r"through",
                    "to",
                    observed,
                    flags=re.IGNORECASE,
                )
                page_aggregate = re.sub(
                    r"through",
                    "to",
                    page_number,
                    flags=re.IGNORECASE,
                )
                aggregate_chars = re.compile(r"[^0-9a-z]+", re.IGNORECASE)
                if observed and (
                    aggregate_chars.sub("", observed_aggregate).casefold()
                    != aggregate_chars.sub("", page_aggregate).casefold()
                ):
                    raise RuntimeError(
                        "Kansas aggregate page metadata changed its body identity: "
                        f"expected={expected} page={page_number} observed={observed} "
                        f"source={source_url}"
                    )
                extra_keys = {
                    cls._kansas_identity_key(identity)
                    for identity in covered_identities[1:]
                }
                if catalog_identity_keys and extra_keys.intersection(
                    catalog_identity_keys
                ):
                    raise RuntimeError(
                        "Kansas aggregate body duplicates a separately cataloged "
                        f"section identity: source={source_url}"
                    )
                reconciliation = "aggregate_catalog_entry"

        exception = cls._CATALOG_FRONT_MATTER_META_EXCEPTIONS.get(expected)
        exception_matches = bool(
            exception is not None
            and page_number_present
            and page_number.casefold() == exception[0].casefold()
            and urlparse(source_url).path.endswith(exception[1])
        )
        if page_number_present and not page_relation and not aggregate_kind:
            if exception_matches:
                reconciliation = "catalog_front_matter_meta_exception"
            elif page_number:
                raise RuntimeError(
                    "Kansas page metadata changed catalog identity: "
                    f"expected={expected} page={page_number} source={source_url}"
                )

        if not reconciliation:
            if page_relation:
                reconciliation = "page_metadata_confirms_catalog"
            elif exception_matches:
                reconciliation = "catalog_front_matter_meta_exception"
            else:
                raise RuntimeError(
                    "Kansas normalized section changed catalog identity: "
                    f"expected={expected} observed={observed} source={source_url}"
                )

        if (
            page_number_present
            and not page_number
            and not body_relation
            and not exception_matches
        ):
            raise RuntimeError(
                "Kansas section lacks body and page identity evidence: "
                f"expected={expected} source={source_url}"
            )
        if not page_number_present and not body_relation:
            raise RuntimeError(
                "Kansas normalized section changed catalog identity: "
                f"expected={expected} observed={observed} source={source_url}"
            )

        statute.section_number = expected
        statute.statute_id = f"{statute.code_name} § {expected}"
        statute.official_cite = f"K.S.A. § {expected}"
        chapter_number = expected.split("-", 1)[0]
        statute.title_number = chapter_number
        statute.chapter_number = chapter_number
        statute.structured_data = {
            **structured,
            "source_body_section_number": observed,
            "source_catalog_section_number": expected,
            "source_identity_reconciliation": reconciliation,
        }
        if aggregate_kind:
            statute.structured_data.update(
                {
                    "source_aggregate_kind": aggregate_kind,
                    "source_covered_section_numbers": covered_identities,
                }
            )
        return statute

    def _official_ssl_context(self, *, unverified: bool = False):
        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(
        self, url: str, timeout: int = 20
    ) -> Tuple[bytes, bytes, bytes]:
        """Fetch one official Kansas URL and retain request/response/body bytes."""

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
                "User-Agent": "ipfs-datasets-open-us-law-kansas/1.0",
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
            raise RuntimeError(
                f"official Kansas GET failed for {url}: {last_exc}"
            ) from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Kansas GET returned HTTP {status} for {url}")
        response_bytes = (
            f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        )
        return request_bytes, response_bytes, body

    def _parse_official_chapter_index(
        self, html: str, index_url: str
    ) -> List[Dict[str, str]]:
        """Parse every official Kansas Statutes chapter unit from the live laws index."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "BeautifulSoup is required for official Kansas discovery"
            ) from exc

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = urljoin(index_url, str(link.get("href") or "").strip())
            normalized = href.rstrip("/") + "/"
            token_match = self._CHAPTER_TOKEN_RE.search(normalized)
            if not token_match:
                token_match = re.search(
                    r"(?P<token>[0-9a-z]{3,4})_000_0000_chapter/?",
                    normalized,
                    flags=re.IGNORECASE,
                )
            if not token_match:
                continue
            if normalized in seen:
                continue
            token = token_match.group("token")
            chapter_number = token.lstrip("0") or "0"
            label = self._normalize_legal_text(link.get_text(" ", strip=True))
            if not label:
                label = f"Chapter {chapter_number}"
            seen.add(normalized)
            units.append(
                {
                    "canonical_key": f"ks:chapter-{chapter_number.lower()}",
                    "source_url": normalized,
                    "label": label,
                    "chapter_number": chapter_number,
                    "text": (
                        f"Kansas Statutes {label} official chapter index entry "
                        f"retained from {normalized}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "KS"):
        """Acquire the uncapped official Kansas Statutes chapter frontier.

        Returns an ``OfficialFetch`` whose rows enumerate every official
        chapter unit discovered from ``www.kslegislature.gov``. The
        retained body is the compact official catalog derived from the
        live index.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "KS").strip().upper()
        if normalized != "KS":
            raise ValueError(f"KansasScraper cannot acquire {normalized}")
        index_url = self.OFFICIAL_ENTRY_URL
        request_bytes, response_bytes, index_body = self._official_http_get(index_url)
        html = index_body.decode("utf-8", errors="replace")
        units = self._parse_official_chapter_index(html, index_url)
        if len(units) < 3:
            raise RuntimeError(
                f"official Kansas chapter index is incomplete: {len(units)} units"
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
            jurisdiction_code="KS",
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
StateScraperRegistry.register("KS", KansasScraper)
