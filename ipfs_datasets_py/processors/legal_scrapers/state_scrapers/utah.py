"""Scraper for Utah state laws.

This module contains the scraper for Utah statutes from the official state legislative website.
"""

import hashlib
import json
import os
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, quote, urljoin, urlparse
from xml.etree import ElementTree as ET

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class UtahScraper(BaseStateScraper):
    """Scraper for Utah state laws from https://le.utah.gov"""

    OFFICIAL_DOMAIN = "le.utah.gov"
    OFFICIAL_ENTRY_PATH = "/xcode/code.html"
    OFFICIAL_ENTRY_URL = "https://le.utah.gov/xcode/code.html"
    _UT_TITLE_HREF_RE = re.compile(
        r"/xcode/Title(?P<title>\d{1,2}[A-Z]?)\b",
        re.IGNORECASE,
    )
    _UT_TITLE_LABEL_RE = re.compile(
        r"\bTitle\s+(?P<title>\d{1,2}[A-Z]?)\b",
        re.IGNORECASE,
    )
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "Aeronautics"),
        ("3", "Uniform Agricultural Cooperative Association Act"),
        ("4", "Utah Agricultural Code"),
        ("7", "Financial Institutions Act"),
        ("8", "Cemeteries"),
        ("9", "Cultural and Community Engagement"),
        ("10", "Utah Municipal Code"),
        ("11", "Cities, Counties, and Local Taxing Units"),
        ("12", "Collection Agencies"),
        ("13", "Commerce and Trade"),
        ("14", "Contractors' Bonds"),
        ("15", "Contracts and Obligations in General"),
        ("15A", "State Construction and Fire Codes Act"),
        ("16", "Corporations"),
        ("17", "Counties"),
        ("17B", "Limited Purpose Local Government Entities - Special Districts"),
        ("17C", "Limited Purpose Local Government Entities - Community Reinvestment Agency Act"),
        ("17D", "Limited Purpose Local Government Entities - Other Entities"),
        ("18", "Dogs"),
        ("19", "Environmental Quality Code"),
        ("20A", "Election Code"),
        ("21", "Fees"),
        ("22", "Fiduciaries and Trusts"),
        ("23A", "Wildlife Resources Act"),
        ("24", "Forfeiture and Disposition of Property Act"),
        ("25", "Fraud"),
        ("26A", "Local Health Authorities"),
        ("26B", "Utah Health and Human Services Code"),
        ("31A", "Insurance Code"),
        ("32B", "Alcoholic Beverage Control Act"),
        ("34", "Labor in General"),
        ("34A", "Utah Labor Code"),
        ("35A", "Utah Workforce Services Code"),
        ("36", "Legislature"),
        ("39A", "National Guard and Militia Act"),
        ("40", "Mines and Mining"),
        ("41", "Motor Vehicles"),
        ("42", "Names"),
        ("43", "Negotiable Certificates"),
        ("45", "Newspapers and Radio Broadcasting"),
        ("46", "Notarization and Authentication of Documents, Electronic Signatures, and Legal Material"),
        ("47", "Nuisances"),
        ("48", "Partnership"),
        ("49", "Utah State Retirement and Insurance Benefit Act"),
        ("51", "Public Funds and Accounts"),
        ("52", "Public Officers"),
        ("53", "Public Safety Code"),
        ("53B", "State System of Higher Education"),
        ("53C", "School and Institutional Trust Lands Management Act"),
        ("53D", "School and Institutional Trust Fund Management and Insurance Act"),
        ("53E", "Public Education System -- State Administration"),
        ("53F", "Public Education System -- Funding"),
        ("53G", "Public Education System -- Local Administration"),
        ("54", "Public Utilities"),
        ("55", "Public Welfare"),
        ("56", "Railroads"),
        ("57", "Real Estate"),
        ("58", "Occupations and Professions"),
        ("59", "Revenue and Taxation"),
        ("61", "Securities Division - Real Estate Division"),
        ("63A", "Utah Government Operations Code"),
        ("63B", "Bonds"),
        ("63C", "State Commissions and Councils Code"),
        ("63G", "General Government"),
        ("63H", "Independent State Entities"),
        ("63I", "Oversight"),
        ("63J", "Budgeting"),
        ("63L", "Lands"),
        ("63M", "Governor's Programs"),
        ("63N", "Economic Opportunity Act"),
        ("64", "State Institutions"),
        ("65A", "Forestry, Fire, and State Lands"),
        ("67", "State Officers and Employees"),
        ("68", "Utah Revised Nonprofit Corporation Act"),
        ("69", "Telegraphic and Telephonic Transactions"),
        ("70A", "Uniform Commercial Code"),
        ("70C", "Utah Consumer Credit Code"),
        ("70D", "Financial Institution Mortgage Financing Regulation Act"),
        ("71A", "Veterans and Military Affairs"),
        ("72", "Transportation Code"),
        ("73", "Water and Irrigation"),
        ("75", "Utah Uniform Probate Code"),
        ("75A", "Fiduciaries"),
        ("76", "Utah Criminal Code"),
        ("77", "Utah Code of Criminal Procedure"),
        ("78A", "Judiciary and Judicial Administration"),
        ("78B", "Judicial Code"),
        ("79", "Natural Resources"),
        ("80", "Utah Juvenile Code"),
        ("81", "Utah Uniform Probate Code"),
    )
    OFFICIAL_TITLE_COUNT = len(OFFICIAL_TITLES)

    _UT_VERSION_DEFAULT_RE = re.compile(r"var\s+versionDefault\s*=\s*['\"]([^'\"]*)['\"]", re.IGNORECASE)
    _UT_TITLE_WRAPPER_RE = re.compile(r"/xcode/title[0-9a-z]+/[0-9a-z]+\.html$", re.IGNORECASE)
    _UT_SECTION_LINK_RE = re.compile(r"/xcode/title[0-9a-z]+/chapter[0-9a-z]+/[0-9a-z-]+-s[0-9a-z.]+\.html", re.IGNORECASE)
    _UT_PART_LINK_RE = re.compile(r"/xcode/title[0-9a-z]+/chapter[0-9a-z]+/[0-9a-z-]+-p[0-9a-z.]+\.html", re.IGNORECASE)
    _UT_CHAPTER_LINK_RE = re.compile(r"/xcode/title[0-9a-z]+/chapter[0-9a-z]+/[0-9a-z-]+\.html", re.IGNORECASE)
    _UT_CHAPTER_RE = re.compile(
        r"Chapter\s+([0-9]+[A-Za-z]?)\s+(.+?)(?=\s+Chapter\s+[0-9]+[A-Za-z]?\s+|\s+<< Previous Title|\s+Download Options|$)",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Utah's legislative website."""
        return "https://le.utah.gov"

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind strict closure to the source-derived title XML parser."""

        from . import utah_title_xml

        return (utah_title_xml,)
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Utah."""
        return [{
            "name": "Utah Code",
            "url": f"{self.get_base_url()}/xcode/code.html",
            "type": "Code"
        }]

    def _justia_fallback_allowed(self) -> bool:
        return str(
            os.getenv("STATE_SCRAPER_UT_ALLOW_JUSTIA_FALLBACK", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

    def _is_justia_url(self, url: str) -> bool:
        return "justia.com" in str(url or "").lower()

    def _filter_official_only(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        """Drop secondary/Justia rows when full-corpus admission is sealed."""
        if not self._full_corpus_enabled() or self._justia_fallback_allowed():
            return statutes
        return [
            s
            for s in statutes
            if not self._is_justia_url(str(s.source_url or ""))
            and "justia" not in str((s.structured_data or {}).get("source_kind") or "").lower()
            and "le.utah.gov" in str(s.source_url or "").lower()
        ]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Utah's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Honor explicit max_statutes / full-corpus uncapped mode the same way
        # other sealed official adapters do (sample default remains 160).
        if max_statutes is not None:
            return_threshold = max(1, int(max_statutes))
            unbounded_full = False
        elif self._full_corpus_enabled():
            return_threshold = 1000000
            unbounded_full = True
        else:
            return_threshold = self._bounded_return_threshold(160)
            unbounded_full = False

        if unbounded_full:
            return await self._scrape_strict_official_title_xml_frontier(
                code_name=code_name or "Utah Code",
            )

        xml_budget = return_threshold if not unbounded_full else 1000000
        from .utah_constitution import (
            configured_constitution_html_path,
            parse_utah_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_utah_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Utah Constitution",
                    source_url="https://le.utah.gov/xcode/constitution.html",
                    max_statutes=None if unbounded_full else return_threshold,
                )
                return constitution_rows if unbounded_full else constitution_rows[:return_threshold]
        local_xml = self._scrape_configured_title_xml(
            code_name,
            max_statutes=None if unbounded_full else max(10, int(xml_budget)),
        )
        if local_xml:
            return local_xml if unbounded_full else local_xml[:return_threshold]

        xml_sections = await self._scrape_official_xml_code_tree(
            code_name,
            max_statutes=max(10, int(xml_budget)),
        )
        if xml_sections:
            return xml_sections if unbounded_full else xml_sections[:return_threshold]

        official_sections = await self._scrape_official_versioned_tree(
            code_name,
            max_statutes=max(10, int(xml_budget)),
        )
        if official_sections:
            return official_sections if unbounded_full else official_sections[:return_threshold]

        # Seed/direct recovery is for bounded probes only — never sole full-corpus path.
        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]

        if self._full_corpus_enabled() and max_statutes is None and not self._justia_fallback_allowed():
            self.logger.warning(
                "Utah full-corpus run found zero official le.utah.gov statutes; "
                "refusing secondary Justia sole-admission fallback"
            )
            return []

        live_title_stubs = await self._scrape_live_title_stubs(code_name, max_statutes=max(10, return_threshold))
        live_chapter_stubs = await self._scrape_live_chapter_stubs(
            code_name,
            title_limit=max(1, min(12, return_threshold)),
            per_title_limit=max(1, min(10, return_threshold)),
        )

        allow_justia = self._justia_fallback_allowed() or not self._full_corpus_enabled()
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/xcode/code.html",
            f"{self.get_base_url()}/xcode/",
            f"{self.get_base_url()}/xcode/Title01/",
        ]
        if allow_justia:
            candidate_urls.extend(
                [
                    "https://law.justia.com/codes/utah/",
                    "https://web.archive.org/web/20250101000000/https://law.justia.com/codes/utah/",
                ]
            )
        for archived in await self._discover_archived_title_urls(limit=max(10, return_threshold)):
            if archived not in candidate_urls:
                candidate_urls.append(archived)

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in self._filter_official_only(items):
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(live_title_stubs)
        _merge(live_chapter_stubs)
        if len(merged) >= return_threshold:
            return merged[:return_threshold]

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            if self._is_justia_url(candidate) and not allow_justia:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Utah Code Ann.", max_sections=return_threshold)
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged[:return_threshold]

        return merged

    @staticmethod
    def _utah_frontier_digest(rows: Sequence[tuple[str, bytes]]) -> str:
        digest = hashlib.sha256()
        for official_url, payload in rows:
            digest.update(str(official_url).encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(bytes(payload)).digest())
        return digest.hexdigest()

    def _utah_input_evidence_context(
        self,
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Verify one aligned retained parser input when a ledger is attached."""

        body = bytes(payload)
        content_sha256 = hashlib.sha256(body).hexdigest()
        envelope = parser_input_envelope
        if not isinstance(envelope, Mapping):
            to_dict = getattr(envelope, "to_dict", None)
            if callable(to_dict):
                envelope = to_dict()
        if isinstance(envelope, Mapping) and isinstance(
            envelope.get("parser_input_envelope"), Mapping
        ):
            envelope = envelope["parser_input_envelope"]
        acquisition = (
            envelope.get("acquisition", {})
            if isinstance(envelope, Mapping)
            else {}
        )
        receipt = (
            acquisition.get("receipt", {})
            if isinstance(acquisition, Mapping)
            else {}
        )
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if not isinstance(receipt, Mapping) or not receipt:
            if ledger_attached:
                raise RuntimeError(
                    "Utah strict parser input lacks retained acquisition evidence: "
                    f"{source_url}"
                )
            return {
                "content_sha256": content_sha256,
                "parser_input_receipt_sha256": "",
                "source_retrieved_at": "",
                "source_transport": "",
                "source_transport_chain": [],
                "transport_receipt": {},
            }
        retained_sha256 = str(
            (receipt.get("content") or {}).get("sha256")
            if isinstance(receipt.get("content"), Mapping)
            else ""
        ).strip().lower()
        if (
            str(receipt.get("endpoint") or "").strip().rstrip("/")
            != source_url.rstrip("/")
            or retained_sha256 != content_sha256
            or str(acquisition.get("body_sha256") or "").strip().lower()
            != content_sha256
        ):
            raise RuntimeError(
                "Utah retained acquisition evidence changed parser identity: "
                f"{source_url}"
            )
        retained_transport = (
            (receipt.get("metadata") or {}).get("transport_receipt", {})
            if isinstance(receipt.get("metadata"), Mapping)
            else {}
        )
        if not isinstance(retained_transport, Mapping) or not retained_transport:
            raise RuntimeError(
                f"Utah retained parser input lacks transport evidence: {source_url}"
            )
        from ...legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            verify_state_law_transport_receipt,
        )

        try:
            verified = verify_state_law_transport_receipt(
                retained_transport,
                official_url=source_url,
                content_sha256=content_sha256,
            )
            if isinstance(transport_receipt, Mapping) and transport_receipt:
                aligned = verify_state_law_transport_receipt(
                    transport_receipt,
                    official_url=source_url,
                    content_sha256=content_sha256,
                )
                if aligned != verified:
                    raise StateLawTransportReceiptError(
                        "unaligned_transport_receipt",
                        "retained and aligned Utah receipts disagree",
                    )
        except StateLawTransportReceiptError as exc:
            raise RuntimeError(
                f"Utah parser input transport identity is incomplete: {source_url}"
            ) from exc
        receipt_sha256 = str(receipt.get("receipt_sha256") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", receipt_sha256) is None:
            raise RuntimeError(
                f"Utah retained parser input lacks an exact receipt digest: {source_url}"
            )
        return {
            "content_sha256": content_sha256,
            "parser_input_receipt_sha256": receipt_sha256,
            "source_retrieved_at": str(receipt.get("retrieved_at") or "").strip(),
            "source_transport": verified.leaf_transport,
            "source_transport_chain": list(verified.transport_chain),
            "transport_receipt": verified.to_dict(),
        }

    async def _fetch_utah_plural_frontier(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
        media_type: str,
        accept: str,
        common_crawl_url_terms: Sequence[str],
        common_crawl_mime_terms: Sequence[str],
    ) -> Any:
        """Fetch one exact official frontier with grouped-WARC residual retry."""

        requested = list(urls)
        if not requested or len(requested) != len(set(requested)):
            raise RuntimeError(
                f"Utah {frontier_name} frontier is empty or repeats URLs"
            )
        retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_UT_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=3,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            timeout_seconds=90,
            headers={
                "Accept": accept,
                "User-Agent": "ipfs-datasets-utah-code/2.0",
            },
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=max(
                1,
                min(
                    32,
                    self._env_int(
                        "STATE_SCRAPER_UT_FRONTIER_CONCURRENCY",
                        default=8,
                    ),
                ),
            ),
            prefer_direct=True,
            common_crawl_domain_terms=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=tuple(common_crawl_url_terms),
            common_crawl_mime_terms=tuple(common_crawl_mime_terms),
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
                f"Utah {frontier_name} frontier returned unaligned identities"
            )
        failures = [
            {"url": url, "error": error or "invalid or empty parser input"}
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None
            or not payload
            or not content_validator(bytes(payload))
        ]
        if failures:
            raise RuntimeError(
                f"Utah {frontier_name} frontier is incomplete after residual-only "
                f"retries: {failures}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    async def _scrape_strict_official_title_xml_frontier(
        self,
        *,
        code_name: str,
        record_primary: bool = True,
        as_of_date: str = "",
    ) -> List[NormalizedStatute]:
        """Close the current root-derived Utah Code title XML frontier."""

        from .utah_title_xml import (
            parse_utah_title_xml_frontier_document,
            root_versioned_html_url,
            title_xml_frontier_from_root_html,
        )

        observed_at = datetime.now(timezone.utc).isoformat()
        observed_date = as_of_date or observed_at[:10]

        def _decode(payload: bytes) -> str:
            try:
                return bytes(payload).decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError("Utah official HTML is not valid UTF-8") from exc

        def _valid_wrapper(payload: bytes) -> bool:
            try:
                return bool(
                    root_versioned_html_url(
                        _decode(payload),
                        wrapper_url=self.OFFICIAL_ENTRY_URL,
                    )
                )
            except Exception:
                return False

        wrapper_batch = await self._fetch_utah_plural_frontier(
            [self.OFFICIAL_ENTRY_URL],
            frontier_name="xcode-wrapper",
            content_validator=_valid_wrapper,
            media_type="text/html",
            accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            common_crawl_url_terms=(self.OFFICIAL_ENTRY_PATH,),
            common_crawl_mime_terms=("html", "text"),
        )
        wrapper_payload = wrapper_batch.payloads[0]
        wrapper_evidence = self._utah_input_evidence_context(
            source_url=self.OFFICIAL_ENTRY_URL,
            payload=wrapper_payload,
            transport_receipt=wrapper_batch.transport_receipts[0],
            parser_input_envelope=wrapper_batch.parser_input_envelopes[0],
        )
        root_url = root_versioned_html_url(
            _decode(wrapper_payload),
            wrapper_url=self.OFFICIAL_ENTRY_URL,
        )

        def _valid_root(payload: bytes) -> bool:
            try:
                return bool(
                    title_xml_frontier_from_root_html(
                        _decode(payload),
                        root_url=root_url,
                        as_of_date=observed_date,
                    )
                )
            except Exception:
                return False

        root_batch = await self._fetch_utah_plural_frontier(
            [root_url],
            frontier_name="xcode-root",
            content_validator=_valid_root,
            media_type="text/html",
            accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            common_crawl_url_terms=("/xcode/C_",),
            common_crawl_mime_terms=("html", "text"),
        )
        root_payload = root_batch.payloads[0]
        root_evidence = self._utah_input_evidence_context(
            source_url=root_url,
            payload=root_payload,
            transport_receipt=root_batch.transport_receipts[0],
            parser_input_envelope=root_batch.parser_input_envelopes[0],
        )
        locators = title_xml_frontier_from_root_html(
            _decode(root_payload),
            root_url=root_url,
            as_of_date=observed_date,
        )
        xml_urls = [row.xml_url for row in locators]
        if len(xml_urls) != len(set(xml_urls)):
            raise RuntimeError("Utah source-derived XML frontier repeats URLs")

        def _valid_title_xml(payload: bytes) -> bool:
            try:
                root = ET.fromstring(bytes(payload))
            except ET.ParseError:
                return False
            return (
                str(root.tag or "").split("}", 1)[-1].casefold() == "title"
                and bool(str(root.attrib.get("number") or "").strip())
            )

        xml_batch = await self._fetch_utah_plural_frontier(
            xml_urls,
            frontier_name="title-xml",
            content_validator=_valid_title_xml,
            media_type="application/xml",
            accept="application/xml,text/xml;q=0.9,*/*;q=0.5",
            common_crawl_url_terms=("/xcode/Title",),
            common_crawl_mime_terms=("xml", "text"),
        )
        statutes: List[NormalizedStatute] = []
        terminal_sections: List[Dict[str, Any]] = []
        excluded_sections: List[Dict[str, Any]] = []
        duplicate_sections: List[Dict[str, Any]] = []
        residual_sections: List[Dict[str, Any]] = []
        terminal_titles: List[Dict[str, Any]] = []
        active_title_count = 0
        discovered_section_count = 0
        seen_identities: Dict[str, str] = {}
        xml_frontier_rows: List[tuple[str, bytes]] = []
        for locator, xml_url, payload, receipt, envelope in zip(
            locators,
            xml_batch.urls,
            xml_batch.payloads,
            xml_batch.transport_receipts,
            xml_batch.parser_input_envelopes,
            strict=True,
        ):
            if xml_url != locator.xml_url:
                raise RuntimeError("Utah title XML URL/locator alignment changed")
            evidence = self._utah_input_evidence_context(
                source_url=xml_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            parsed = parse_utah_title_xml_frontier_document(
                payload,
                expected_title_number=locator.title_number,
                expected_title_name=locator.title_name,
                source_url=xml_url,
                as_of_date=observed_date,
                code_name=code_name,
            )
            discovered_section_count += parsed.discovered_section_count
            disposition_evidence = {
                "content_sha256": evidence["content_sha256"],
                "parser_input_receipt_sha256": evidence[
                    "parser_input_receipt_sha256"
                ],
                "source_retrieved_at": evidence["source_retrieved_at"],
                "source_transport": evidence["source_transport"],
                "source_transport_chain": evidence["source_transport_chain"],
            }
            for collection, values in (
                (terminal_sections, parsed.terminal_sections),
                (excluded_sections, parsed.excluded_sections),
                (duplicate_sections, parsed.duplicate_sections),
                (residual_sections, parsed.residual_sections),
            ):
                collection.extend(
                    {
                        **dict(value),
                        "title_number": locator.title_number,
                        "title_xml_url": xml_url,
                        **disposition_evidence,
                    }
                    for value in values
                )
            if locator.disposition != "active":
                terminal_titles.append(
                    {
                        "title_number": locator.title_number,
                        "title_name": locator.title_name,
                        "title_xml_url": xml_url,
                        "disposition": locator.disposition,
                        "effective_date": locator.effective_date,
                        "superseded_date": locator.superseded_date,
                        **disposition_evidence,
                    }
                )
                terminal_sections.extend(
                    {
                        "section_number": str(row.section_number or ""),
                        "source_url": xml_url,
                        "title_number": locator.title_number,
                        "title_xml_url": xml_url,
                        "disposition": f"terminal_title_{locator.disposition}",
                        **disposition_evidence,
                    }
                    for row in parsed.rows
                )
                xml_frontier_rows.append((xml_url, payload))
                continue

            active_title_count += 1
            if not parsed.rows:
                raise RuntimeError(
                    "Utah active title XML emitted no operative sections: "
                    f"Title {locator.title_number}"
                )
            for row in parsed.rows:
                base_url = str(row.source_url or "").split("#", 1)[0]
                identity = str(row.statute_id or "").strip().casefold()
                if base_url != xml_url or not identity:
                    raise RuntimeError(
                        "Utah normalized section changed source identity: "
                        f"{xml_url}"
                    )
                prior_url = seen_identities.get(identity)
                if prior_url is not None:
                    raise RuntimeError(
                        "Utah repeated an active canonical section identity: "
                        f"{row.statute_id} first={prior_url} second={xml_url}"
                    )
                seen_identities[identity] = xml_url
                data = dict(row.structured_data or {})
                data.update(
                    {
                        "catalog_locator": {
                            "position": locator.position,
                            "title_number": locator.title_number,
                            "source_label": locator.source_label,
                            "declared_wrapper_url": locator.declared_wrapper_url,
                            "version_token": locator.version_token,
                            "xml_url": locator.xml_url,
                            "disposition": locator.disposition,
                            "effective_date": locator.effective_date,
                            "superseded_date": locator.superseded_date,
                        },
                        "content_sha256": evidence["content_sha256"],
                        "parser_input_receipt_sha256": evidence[
                            "parser_input_receipt_sha256"
                        ],
                        "source_retrieved_at": evidence["source_retrieved_at"],
                        "source_transport": evidence["source_transport"],
                        "source_transport_chain": evidence[
                            "source_transport_chain"
                        ],
                        "transport_receipt": evidence["transport_receipt"],
                    }
                )
                row.structured_data = data
                statutes.append(row)
            xml_frontier_rows.append((xml_url, payload))

        if residual_sections:
            raise RuntimeError(
                "Utah title XML frontier has unclassified residual sections: "
                f"{residual_sections[:5]}"
            )
        document_disposition = {
            "discovered": len(locators),
            "fetched": active_title_count,
            "excluded": len(terminal_titles),
            "failed_final": 0,
            "duplicates": 0,
            "quarantined": 0,
        }
        section_disposition = {
            "discovered": discovered_section_count,
            "fetched": len(statutes),
            "excluded": len(terminal_sections) + len(excluded_sections),
            "failed_final": 0,
            "duplicates": len(duplicate_sections),
            "quarantined": 0,
        }
        algebra_keys = (
            "fetched",
            "excluded",
            "failed_final",
            "duplicates",
            "quarantined",
        )
        if document_disposition["discovered"] != sum(
            document_disposition[key] for key in algebra_keys
        ):
            raise RuntimeError("Utah title document disposition algebra did not close")
        if section_disposition["discovered"] != sum(
            section_disposition[key] for key in algebra_keys
        ):
            raise RuntimeError("Utah section disposition algebra did not close")
        closure = {
            "closed": True,
            "as_of_date": observed_date,
            "wrapper_url": self.OFFICIAL_ENTRY_URL,
            "wrapper_content_sha256": wrapper_evidence["content_sha256"],
            "root_url": root_url,
            "root_content_sha256": root_evidence["content_sha256"],
            "source_title_row_count": len(locators),
            "active_title_count": active_title_count,
            "terminal_title_count": len(terminal_titles),
            "title_xml_transport_count": len(xml_frontier_rows),
            "title_xml_frontier_sha256": self._utah_frontier_digest(
                xml_frontier_rows
            ),
            "source_section_count": discovered_section_count,
            "operative_section_count": len(statutes),
            "terminal_section_count": len(terminal_sections),
            "excluded_section_count": len(excluded_sections),
            "duplicate_section_count": len(duplicate_sections),
            "residual_section_count": 0,
            "unique_canonical_identity_count": len(seen_identities),
            "document_disposition": document_disposition,
            "section_disposition": section_disposition,
            "terminal_titles": terminal_titles,
        }
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        frontier = {
            "algebra_closed": True,
            "bundle_closed": False,
            "closed": True,
            "disposition": section_disposition,
            "document_disposition": document_disposition,
            "enumerator_closed": True,
            "expected_index_units": discovered_section_count,
            "pagination_closed": True,
            "root_content_sha256": root_evidence["content_sha256"],
            "root_url": root_url,
            "schema_version": "utah-source-derived-title-xml-frontier-v1",
            "scope_closed": True,
            "source_title_row_count": len(locators),
            "title_xml_frontier_sha256": closure[
                "title_xml_frontier_sha256"
            ],
            "title_xml_transport_count": len(xml_frontier_rows),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": discovered_section_count,
            "wrapper_content_sha256": wrapper_evidence["content_sha256"],
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        observation = {
            "as_of_date": observed_date,
            "boundary_first": xml_urls[0],
            "boundary_last": xml_urls[-1],
            "closure": closure,
            "frontier": frontier,
            "observed_at": observed_at,
            "transport_batch_stats": {
                "wrapper": dict(wrapper_batch.stats or {}),
                "root": dict(root_batch.stats or {}),
                "title_xml": dict(xml_batch.stats or {}),
            },
        }
        setattr(
            self,
            (
                "_last_utah_full_frontier"
                if record_primary
                else "_last_utah_replayed_frontier"
            ),
            observation,
        )
        self._last_utah_strict_closure = closure
        self._last_utah_wrapper_batch_stats = dict(wrapper_batch.stats or {})
        self._last_utah_root_batch_stats = dict(root_batch.stats or {})
        self._last_utah_xml_batch_stats = dict(xml_batch.stats or {})
        self._last_utah_terminal_titles = terminal_titles
        self._last_utah_terminal_sections = terminal_sections
        self._last_utah_excluded_sections = excluded_sections
        self._last_utah_duplicate_sections = duplicate_sections
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Independently replay retained Utah XML and bind final identities."""

        if getattr(self, "_state_law_acquisition_ledger", None) is None:
            raise RuntimeError(
                "Utah frontier closure requires an attached acquisition ledger"
            )
        first = getattr(self, "_last_utah_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Utah strict title XML frontier was not retained before output"
            )
        replay_rows = await self._scrape_strict_official_title_xml_frontier(
            code_name="Utah Code",
            record_primary=False,
            as_of_date=str(first.get("as_of_date") or ""),
        )
        replay = getattr(self, "_last_utah_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Utah strict title XML replay was not retained")

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from ...legal_data.state_laws_multifetch_acquisition import (
            build_canonical_state_law_output_projection,
        )

        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Utah strict frontier observations are incomplete")
        if canonical_json_bytes(first_frontier) != canonical_json_bytes(
            replayed_frontier
        ):
            raise RuntimeError("Utah first and replayed exact frontiers differ")
        first_transport = first.get("transport_batch_stats")
        replay_transport = replay.get("transport_batch_stats")
        batch_names = ("wrapper", "root", "title_xml")
        if (
            not isinstance(first_transport, Mapping)
            or not isinstance(replay_transport, Mapping)
            or any(
                not isinstance(first_transport.get(name), Mapping)
                or not isinstance(replay_transport.get(name), Mapping)
                for name in batch_names
            )
        ):
            raise RuntimeError("Utah strict frontier lacks aligned batch metadata")
        expected_replay_pages = 2 + int(
            first_frontier.get("source_title_row_count") or 0
        )
        replay_requested_pages = sum(
            int(replay_transport[name].get("requested_pages") or 0)
            for name in batch_names
        )
        replay_network_requested_pages = sum(
            int(replay_transport[name].get("network_requested_pages") or 0)
            for name in batch_names
        )
        replay_retained_pages = sum(
            int(replay_transport[name].get("retained_replay_pages") or 0)
            for name in batch_names
        )
        if (
            expected_replay_pages <= 2
            or replay_requested_pages != expected_replay_pages
            or replay_network_requested_pages != 0
            or replay_retained_pages != expected_replay_pages
        ):
            raise RuntimeError(
                "Utah exact replay was not zero-network retained input parity: "
                f"expected={expected_replay_pages} "
                f"requested={replay_requested_pages} "
                f"retained={replay_retained_pages} "
                f"network={replay_network_requested_pages}"
            )
        replay_projection = build_canonical_state_law_output_projection(
            [self._enrich_statute_structure(row).to_dict() for row in replay_rows],
            jurisdiction="UT",
        )
        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw, (str, bytes, bytearray)
        ):
            raise RuntimeError("Utah canonical output lacks exact identities")
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
            missing = sorted(set(replay_keys) - set(output_keys))
            extra = sorted(set(output_keys) - set(replay_keys))
            raise RuntimeError(
                "Utah final canonical identities do not exactly match retained "
                f"XML replay: expected={len(replay_keys)} actual={len(output_keys)} "
                f"missing={missing[:3]} extra={extra[:3]}"
            )
        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("Utah strict frontier lacks section disposition")
        if int(disposition.get("fetched") or -1) != len(output_keys):
            raise RuntimeError(
                "Utah strict fetched count changed after final output filtering"
            )
        completion = closed_jurisdiction_receipt(
            "UT",
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
                    "pagination_total": int(
                        first_frontier.get("source_title_row_count") or 0
                    ),
                },
                "canonical_row_count": len(output_keys),
                "frontier": dict(first_frontier),
                "legal_as_of": (
                    "official Utah Code xcode title XML root as of "
                    f"{str(first.get('as_of_date') or '')}"
                ),
                "observed_at": str(first.get("observed_at") or ""),
                "replay": {
                    "closed": True,
                    "first_frontier_digest": str(
                        first_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "second_frontier_digest": str(
                        replayed_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "network_requests": replay_network_requested_pages,
                    "retained_parser_inputs": replay_retained_pages,
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "transport": {
                    "fixture": False,
                    "grouped_warc_recovery": True,
                    "kind": "shared_archive_aware_plural_html_and_xml",
                    "per_page_archive_loop": False,
                    "first_pass_batch_stats": {
                        name: dict(first_transport[name]) for name in batch_names
                    },
                    "replay_batch_stats": {
                        name: dict(replay_transport[name]) for name in batch_names
                    },
                    "retained_replay_network_requests": (
                        replay_network_requested_pages
                    ),
                    "retained_replay_pages": replay_retained_pages,
                    "synthetic": False,
                },
            }
        )
        frontier_digest = str(
            first_frontier.get("frontier_digest_sha256") or ""
        )
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(replayed_frontier),
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{frontier_digest}",
            official_source_url=self.OFFICIAL_ENTRY_URL,
            acquisition_path_ids=self._catalog_acquisition_path_ids_for_source(
                self.OFFICIAL_ENTRY_URL
            ),
            observation_time=str(first.get("observed_at") or ""),
            source_software_version=self._state_law_frontier_source_software_version(),
        )

    def _scrape_configured_title_xml(
        self,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Read a local official title XML when ``UTAH_TITLE_XML`` is set."""

        from .utah_title_xml import configured_title_xml_path, parse_utah_xml_document

        path = configured_title_xml_path()
        if path is None:
            return []
        try:
            return parse_utah_xml_document(
                path.read_bytes(),
                code_name=code_name,
                source_url=f"{self.get_base_url()}/xcode/",
                max_statutes=max_statutes,
            )
        except Exception as exc:
            self.logger.warning("Utah official title XML failed: %s", exc)
            return []

    async def _scrape_official_xml_code_tree(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        from .utah_title_xml import (
            discover_title_xml_urls_from_html,
            parse_utah_xml_document,
            title_xml_url,
            version_default_from_html,
        )

        wrapper_url = f"{self.get_base_url()}/xcode/code.html"
        wrapper_html = await self._fetch_text_with_archival(wrapper_url, timeout=25)
        title_xml_urls = discover_title_xml_urls_from_html(wrapper_html or "", base=self.get_base_url())

        # Title wrappers expose versionDefault without Playwright when the TOC
        # is JS-only. Bound the probe so sampling stays cheap.
        if not title_xml_urls:
            title_budget = len(self.OFFICIAL_TITLES) if self._full_corpus_enabled() else min(6, len(self.OFFICIAL_TITLES))
            for title_num, _name in self.OFFICIAL_TITLES[:title_budget]:
                title_wrapper = f"{self.get_base_url()}/xcode/Title{title_num}/{title_num}.html"
                title_html = await self._fetch_text_with_archival(title_wrapper, timeout=15)
                versioned = self._resolve_versioned_content_url(title_wrapper, title_html or "")
                if versioned and versioned.lower().endswith(".html"):
                    title_xml_urls[str(title_num)] = versioned[:-5] + ".xml"
                    continue
                version = version_default_from_html(title_html or "")
                if version:
                    title_xml_urls[str(title_num)] = title_xml_url(str(title_num), version)

        strict_full = self._full_corpus_enabled() and int(max_statutes) >= 1_000_000
        expected_titles = [str(title_num) for title_num, _name in self.OFFICIAL_TITLES]
        if strict_full and set(title_xml_urls) != set(expected_titles):
            missing = sorted(set(expected_titles) - set(title_xml_urls))
            unexpected = sorted(set(title_xml_urls) - set(expected_titles))
            raise RuntimeError(
                "Utah official XML discovery did not close the exact title catalog; "
                f"missing={missing} unexpected={unexpected}"
            )
        title_items = (
            [(title_num, title_xml_urls[title_num]) for title_num in expected_titles]
            if strict_full
            else list(title_xml_urls.items())
        )

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for requested_title, xml_url in title_items:
            if len(statutes) >= max_statutes:
                return statutes[:max_statutes]
            xml_text = await self._fetch_text_with_archival(xml_url, timeout=35)
            if not xml_text:
                if strict_full:
                    raise RuntimeError(
                        "Utah official XML title frontier has an unresolved URL: "
                        f"{xml_url}"
                    )
                continue
            remaining = max(0, int(max_statutes) - len(statutes))
            title_rows = parse_utah_xml_document(
                xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text,
                code_name=code_name,
                source_url=xml_url,
                max_statutes=remaining,
            )
            if strict_full and not title_rows:
                raise RuntimeError(
                    f"Utah official XML title parsed no operative rows: {requested_title}"
                )
            for row in title_rows:
                observed_title = str(row.title_number or "")
                section_key = str(row.section_number or "").casefold()
                if strict_full and observed_title.casefold() != requested_title.casefold():
                    raise RuntimeError(
                        "Utah title XML changed requested title identity: "
                        f"requested={requested_title} observed={observed_title}"
                    )
                if section_key in seen_sections:
                    raise RuntimeError(
                        "Utah title XML repeated section identity across title files: "
                        f"{row.section_number}"
                    )
                seen_sections.add(section_key)
                statutes.append(row)
        if statutes:
            return statutes[:max_statutes]

        root_xml_url = await self._resolve_root_versioned_xml_url()
        if not root_xml_url:
            return []

        xml_text = await self._fetch_text_with_archival(root_xml_url, timeout=35)
        if not xml_text:
            return []

        parsed = parse_utah_xml_document(
            xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text,
            code_name=code_name,
            source_url=root_xml_url,
            max_statutes=max_statutes,
        )
        if parsed:
            for row in parsed:
                row.structured_data = {
                    **dict(row.structured_data or {}),
                    "source_kind": "official_utah_code_xml",
                    "discovery_method": "official_root_xml_title_chapter_section",
                }
            return parsed

        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []

        for title_node in root.findall(".//title") if root.tag != "title" else [root]:
            title_number = str(title_node.attrib.get("number") or "").strip()
            title_name = self._normalize_legal_text(title_node.findtext("catchline", default=""))
            for chapter_node in title_node.findall(".//chapter"):
                chapter_number = str(chapter_node.attrib.get("number") or "").strip()
                chapter_name = self._normalize_legal_text(chapter_node.findtext("catchline", default=""))
                for section_node in chapter_node.findall(".//section"):
                    if len(statutes) >= max_statutes:
                        return statutes
                    statute = self._build_official_section_from_xml_node(
                        code_name=code_name,
                        root_xml_url=root_xml_url,
                        title_number=title_number,
                        title_name=title_name,
                        chapter_number=chapter_number,
                        chapter_name=chapter_name,
                        section_node=section_node,
                    )
                    if statute is not None:
                        statutes.append(statute)
        return statutes

    async def _resolve_root_versioned_xml_url(self) -> Optional[str]:
        wrapper_url = f"{self.get_base_url()}/xcode/code.html"
        wrapper_html = await self._fetch_text_with_archival(wrapper_url, timeout=25)
        if not wrapper_html:
            return None
        versioned_html_url = self._resolve_versioned_content_url(wrapper_url, wrapper_html)
        if not versioned_html_url:
            return None
        if versioned_html_url.lower().endswith(".html"):
            return versioned_html_url[:-5] + ".xml"
        return None

    def _build_official_section_from_xml_node(
        self,
        *,
        code_name: str,
        root_xml_url: str,
        title_number: str,
        title_name: str,
        chapter_number: str,
        chapter_name: str,
        section_node: ET.Element,
    ) -> Optional[NormalizedStatute]:
        section_number = str(section_node.attrib.get("number") or "").strip()
        if not section_number:
            return None

        section_name = self._normalize_legal_text(section_node.findtext("catchline", default=""))
        from .utah_title_xml import _elem_text

        body = self._normalize_legal_text(_elem_text(section_node))
        if len(body) < 80:
            return None

        source_url = root_xml_url
        version_hint = urlparse(root_xml_url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if title_number and version_hint:
            source_url = f"{self.get_base_url()}/xcode/Title{title_number}/{version_hint}.xml"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=title_number or None,
            title_name=title_name or None,
            chapter_number=chapter_number or None,
            chapter_name=chapter_name or None,
            section_number=section_number,
            section_name=section_name[:220] or f"Section {section_number}",
            full_text=body,
            source_url=source_url,
            legal_area=self._identify_legal_area(f"{title_name} {chapter_name} {section_name} {body[:1200]}"),
            official_cite=f"Utah Code § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_utah_code_xml",
                "discovery_method": "official_root_xml_title_chapter_section",
                "skip_hydrate": True,
            },
        )

    async def _scrape_official_versioned_tree(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        statutes: List[NormalizedStatute] = []
        seen_titles = set()
        seen_sections = set()
        title_queue = [f"{self.get_base_url()}/xcode/Title1/1.html"]

        while title_queue and len(statutes) < max_statutes:
            title_wrapper_url = title_queue.pop(0)
            if title_wrapper_url in seen_titles:
                continue
            seen_titles.add(title_wrapper_url)

            title_wrapper_html = await self._fetch_text_with_archival(title_wrapper_url, timeout=25)
            if not title_wrapper_html:
                continue
            title_versioned_url = self._resolve_versioned_content_url(title_wrapper_url, title_wrapper_html)
            if not title_versioned_url:
                continue
            title_content_html = await self._fetch_text_with_archival(title_versioned_url, timeout=25)
            if not title_content_html:
                continue
            title_soup = BeautifulSoup(title_content_html, "html.parser")

            for link in title_soup.find_all("a", href=True):
                if len(statutes) >= max_statutes:
                    break
                href = str(link.get("href") or "").strip()
                abs_url = urljoin(title_versioned_url, href)
                lower = abs_url.lower()

                if self._UT_TITLE_WRAPPER_RE.search(lower):
                    if abs_url not in seen_titles and abs_url not in title_queue:
                        title_queue.append(abs_url)
                    continue

                if not self._UT_CHAPTER_LINK_RE.search(lower):
                    continue

                chapter_versioned_url = self._resolve_versioned_link(abs_url)
                if not chapter_versioned_url:
                    chapter_wrapper_html = await self._fetch_text_with_archival(abs_url, timeout=25)
                    chapter_versioned_url = self._resolve_versioned_content_url(abs_url, chapter_wrapper_html)
                if not chapter_versioned_url:
                    continue
                section_urls = await self._discover_section_urls_from_versioned_container(chapter_versioned_url)
                for section_url in section_urls:
                    if len(statutes) >= max_statutes:
                        break
                    if section_url in seen_sections:
                        continue
                    seen_sections.add(section_url)
                    statute = await self._build_official_section_from_versioned_url(code_name, section_url)
                    if statute is not None:
                        statutes.append(statute)

        if statutes:
            return statutes

        # Utah's live title wrappers are inconsistent: some titles publish a versioned
        # container tree, while others leave the wrapper empty. When the global title
        # crawl cannot bootstrap, fall back to known current official containers that
        # still produce real section-level rows.
        seed_containers = [
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-P2_1800010118000101.html",
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-P1_1800010118000101.html",
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5_2022050420220504.html",
        ]
        for container_url in seed_containers:
            if len(statutes) >= max_statutes:
                break
            section_urls = await self._discover_section_urls_from_versioned_container(container_url)
            for section_url in section_urls:
                if len(statutes) >= max_statutes:
                    break
                if section_url in seen_sections:
                    continue
                seen_sections.add(section_url)
                statute = await self._build_official_section_from_versioned_url(code_name, section_url)
                if statute is not None:
                    statutes.append(statute)

        return statutes

    async def _discover_section_urls_from_versioned_container(self, versioned_url: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._fetch_text_with_archival(versioned_url, timeout=25)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            abs_url = urljoin(versioned_url, href)
            lower = abs_url.lower()
            candidate = self._resolve_versioned_link(abs_url)

            if self._UT_SECTION_LINK_RE.search(lower):
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    urls.append(candidate)
                continue

            if self._UT_PART_LINK_RE.search(lower):
                part_versioned_url = candidate
                if not part_versioned_url:
                    part_wrapper_html = await self._fetch_text_with_archival(abs_url, timeout=25)
                    part_versioned_url = self._resolve_versioned_content_url(abs_url, part_wrapper_html)
                if not part_versioned_url:
                    continue
                part_html = await self._fetch_text_with_archival(part_versioned_url, timeout=25)
                if not part_html:
                    continue
                part_soup = BeautifulSoup(part_html, "html.parser")
                for part_link in part_soup.find_all("a", href=True):
                    part_href = str(part_link.get("href") or "").strip()
                    abs_part_href = urljoin(part_versioned_url, part_href)
                    if not self._UT_SECTION_LINK_RE.search(abs_part_href.lower()):
                        continue
                    section_versioned_url = self._resolve_versioned_link(abs_part_href)
                    if section_versioned_url and section_versioned_url not in seen:
                        seen.add(section_versioned_url)
                        urls.append(section_versioned_url)

        return urls

    def _resolve_versioned_link(self, href: str) -> Optional[str]:
        parsed = urlparse(str(href or ""))
        query = parse_qs(parsed.query or "")
        version = str((query.get("v") or [""])[0] or "").strip()
        if not version:
            return None
        base_path = parsed.path.rsplit("/", 1)[0]
        return urljoin(f"{parsed.scheme}://{parsed.netloc}", f"{base_path}/{version}.html")

    def _resolve_versioned_content_url(self, wrapper_url: str, wrapper_html: str) -> Optional[str]:
        if not wrapper_html:
            return None
        match = self._UT_VERSION_DEFAULT_RE.search(wrapper_html)
        if not match:
            return None
        version = str(match.group(1) or "").strip()
        if not version:
            return None
        parsed = urlparse(wrapper_url)
        base_path = parsed.path.rsplit("/", 1)[0]
        return urljoin(f"{parsed.scheme}://{parsed.netloc}", f"{base_path}/{version}.html")

    async def _build_official_section_from_versioned_url(
        self,
        code_name: str,
        versioned_url: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._fetch_text_with_archival(versioned_url, timeout=25)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one("#content") or soup.find("body") or soup
        text = self._normalize_legal_text(content.get_text(" ", strip=True))
        match = re.search(r"\b(\d{1,3}-\d{1,3}-\d+[A-Za-z0-9.-]*)\b", text)
        if not match or len(text) < 240:
            return None
        section_number = match.group(1)
        heading = soup.select_one("h3.heading")
        heading_text = self._normalize_legal_text(heading.get_text(" ", strip=True) if heading else "")
        section_name = heading_text
        if "Section " in heading_text:
            section_name = heading_text.split("Section ", 1)[-1]
        start_idx = text.find(f"{section_number}.")
        body = self._normalize_legal_text(text[start_idx:] if start_idx >= 0 else text)
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=section_number.split("-", 1)[0],
            section_number=section_number,
            section_name=section_name[:220] or f"Section {section_number}",
            full_text=body,
            source_url=versioned_url,
            legal_area=self._identify_legal_area(body[:1200]),
            official_cite=f"Utah Code § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_utah_code_versioned_html",
                "discovery_method": "official_title_chapter_part_section",
                "skip_hydrate": True,
            },
        )

    async def _fetch_text_with_archival(self, url: str, timeout: int = 25) -> str:
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout)
        except Exception:
            payload = b""
        if not payload:
            return ""
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload)

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-S203_2025050720250507.html",
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-S202_2025050720250507.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            except Exception:
                payload = b""
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            content = soup.select_one("#content") or soup.find("body")
            text = self._normalize_legal_text(content.get_text(" ", strip=True) if content else "")
            match = re.search(r"\b(\d{1,3}-\d{1,3}-\d+[A-Za-z-]*)\.\s+(.+)", text)
            if not match or len(text) < 280:
                continue
            section_number = match.group(1)
            section_name = self._normalize_legal_text(match.group(2))[:220]
            # Drop the global breadcrumb/nav prefix so records start at the section.
            start_idx = text.find(f"{section_number}.")
            body = self._normalize_legal_text(text[start_idx:] if start_idx >= 0 else text)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body,
                    source_url=url,
                    legal_area=self._identify_legal_area(body[:1200]),
                    official_cite=f"Utah Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_utah_code_section_html",
                        "discovery_method": "official_seed_current_version",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_live_chapter_stubs(
        self,
        code_name: str,
        title_limit: int = 10,
        per_title_limit: int = 8,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        title_rows = await self._scrape_live_title_stubs(code_name, max_statutes=max(1, int(title_limit)))
        out: List[NormalizedStatute] = []
        seen = set()
        for title_row in title_rows[:title_limit]:
            title_url = str(title_row.source_url or "").strip()
            if not title_url:
                continue
            try:
                payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
                if not payload:
                    continue
            except Exception:
                continue

            soup = BeautifulSoup(payload, "html.parser")
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if not text:
                continue

            title_number = self._extract_title_number(str(title_row.section_number or ""))
            count = 0
            for match in self._UT_CHAPTER_RE.finditer(text):
                if count >= per_title_limit:
                    break
                chapter_no = match.group(1).strip()
                chapter_name = self._normalize_legal_text(match.group(2))[:220]
                if not chapter_name:
                    continue
                key = f"{title_number}:{chapter_no}:{chapter_name}".lower()
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                out.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § Title {title_number} Chapter {chapter_no}",
                        code_name=code_name,
                        section_number=f"Title {title_number} Chapter {chapter_no}",
                        section_name=f"Chapter {chapter_no} {chapter_name}"[:220],
                        full_text=f"Utah Code Title {title_number} Chapter {chapter_no} {chapter_name}",
                        source_url=title_url,
                        legal_area=self._identify_legal_area(chapter_name),
                        official_cite=f"Utah Code Title {title_number} Chapter {chapter_no}",
                        metadata=StatuteMetadata(),
                    )
                )
        return out

    def _extract_title_number(self, value: str) -> str:
        match = re.search(r"title\s+([0-9]+[A-Z]?)", str(value or ""), re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return self._normalize_legal_text(value) or "UNKNOWN"

    async def _scrape_live_title_stubs(self, code_name: str, max_statutes: int = 60) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        url = f"{self.get_base_url()}/xcode/code.html"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[NormalizedStatute] = []
        seen = set()
        title_re = re.compile(r"title\s+([0-9]+[A-Z]?)", re.IGNORECASE)

        for a in soup.find_all("a", href=True):
            if len(out) >= max_statutes:
                break
            href = str(a.get("href") or "").strip()
            text = str(a.get_text(" ", strip=True) or "").strip()
            full_url = urljoin(url, href)
            if "/xcode/title" not in full_url.lower():
                continue

            match = title_re.search(text) or title_re.search(full_url)
            if not match:
                continue
            title_number = match.group(1).upper()
            key = title_number.lower()
            if key in seen:
                continue
            seen.add(key)

            title_name = text[:200] if text else f"Title {title_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_number}",
                    code_name=code_name,
                    section_number=f"Title {title_number}",
                    section_name=title_name,
                    full_text=f"Utah Code {title_name}: {full_url}",
                    source_url=full_url,
                    legal_area=self._identify_legal_area(title_name),
                    official_cite=f"Utah Code Title {title_number}",
                    metadata=StatuteMetadata(),
                )
            )

        return out

    async def _discover_archived_title_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=le.utah.gov/xcode/Title*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            lower_original = original.lower()
            if "/xcode/title" not in lower_original:
                continue
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out


    def official_title_url(self, title_number: Any) -> str:
        number = str(title_number or "").strip()
        return f"{self.get_base_url()}/xcode/Title{number}/"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Utah Code title catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"ut:title-{number.lower()}",
                    "title_number": str(number),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Utah Code Title {number} ({name}) official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host == "le.utah.gov" or host.endswith(".le.utah.gov")

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-utah-official-catalog/1.0",
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

    def _normalize_title_number(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        match = re.match(r"0*(\d{1,2}[A-Z]?)$", text)
        return match.group(1) if match else ""

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        known = {number for number, _name in self.OFFICIAL_TITLES}
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._UT_TITLE_HREF_RE.search(absolute) or self._UT_TITLE_LABEL_RE.search(label)
            if not match:
                continue
            number = self._normalize_title_number(match.group("title"))
            if number not in known or number in found:
                continue
            if self._host_is_official(absolute):
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Utah Code title."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        return rows

    def fetch_official(self, code: str = "UT"):
        """Acquire the exhaustive official Utah Code title catalog.

        Live HTTPS retains the official le.utah.gov xcode index. Every
        known Utah Code title is enumerated with an official URL. This
        hook never returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "UT").strip().upper() or "UT"
        if normalized != "UT":
            raise ValueError(f"UtahScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_TITLE_COUNT:
            raise RuntimeError(
                "utah official catalog enumeration rejected incomplete "
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
StateScraperRegistry.register("UT", UtahScraper)
