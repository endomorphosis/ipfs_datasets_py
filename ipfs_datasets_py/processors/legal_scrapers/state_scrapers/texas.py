"""Texas state law scraper.

Scrapes laws from the Texas Legislature Online website
(https://statutes.capitol.texas.gov/).
"""

import hashlib
import io
import json
import re
import ssl
import urllib.request
import zipfile
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StatuteMetadata,
    _sanitized_multifetch_headers,
    _sanitized_multifetch_request,
)
from .registry import StateScraperRegistry


_TAC_SECTION_RE = re.compile(r"(?:§\s*)?([0-9]+\.[0-9]+)")
_META_REFRESH_URL_RE = re.compile(
    r"<meta[^>]+http-equiv=[\"']refresh[\"'][^>]+content=[\"'][^\"']*url=([^\"'>]+)",
    re.IGNORECASE,
)
_TEXAS_SECTION_START_RE = re.compile(
    r"(?m)\bSec\.\s+([0-9A-Za-z.:-]+)\.\s+([A-Z0-9][^\n]{0,220})"
)
_TEXAS_SUPERSEDED_MEMBER_RE = re.compile(
    r"(?:[_-]old(?=\.|$)|\.old-[0-9]{4}|\s-\scopy(?=\.))",
    re.IGNORECASE,
)
_TEXAS_REPEALED_CHAPTER_RE = re.compile(
    r"\btext\s+of\s+chapter\s+as\s+repealed\b",
    re.IGNORECASE,
)


def _norm_space(value: str) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_meta_refresh_target(html: str) -> Optional[str]:
    match = _META_REFRESH_URL_RE.search(str(html or ""))
    if not match:
        return None
    value = _norm_space(match.group(1))
    return value or None


class TexasScraper(BaseStateScraper):
    """Scraper for Texas state laws."""

    OFFICIAL_DOMAIN = "statutes.capitol.texas.gov"
    OFFICIAL_ENTRY_PATH = "/"
    OFFICIAL_ENTRY_URL = "https://statutes.capitol.texas.gov/"
    OFFICIAL_DOWNLOADS_PATH = "/assets/StatuteCodeDownloads.json"
    OFFICIAL_DOWNLOADS_URL = (
        "https://statutes.capitol.texas.gov/assets/StatuteCodeDownloads.json"
    )
    OFFICIAL_ZIP_HOST = "tcss.legis.texas.gov"
    last_mixed_reconciliation: Dict[str, Any] = {}
    _TX_HTML_CODE_RE = re.compile(
        r"/Docs/(?P<code>[A-Z][A-Z0-9])/htm/\1\.(?P<chapter>[0-9A-Za-z]+)\.htm",
        re.IGNORECASE,
    )
    _TX_ZIP_CODE_RE = re.compile(
        r"(?:Zips/|resources/)(?P<code>[A-Z][A-Z0-9])\.htm\.zip",
        re.IGNORECASE,
    )
    _TX_CODE_LABEL_RE = re.compile(
        r"\b(?P<code>AG|AL|BC|BO|CP|CR|CV|ED|EL|ES|FA|FI|GV|HR|HS|I1|IN|LA|LG|NR|OC|PE|PR|PW|SD|TN|TX|UT|WA|WL)\b"
    )
    # This is the exact statutory subset of the official TLC download
    # manifest.  CN is deliberately accounted for below as a separate
    # constitutional corpus; uncodified WL, I1, and CV remain statutes and
    # therefore cannot be omitted from a Texas statutory publication.
    OFFICIAL_CODES = (
        ("AG", "Agriculture Code"),
        ("AL", "Alcoholic Beverage Code"),
        ("WL", "Auxiliary Water Laws"),
        ("BC", "Business and Commerce Code"),
        ("BO", "Business Organizations Code"),
        ("CP", "Civil Practice and Remedies Code"),
        ("CR", "Code of Criminal Procedure"),
        ("ED", "Education Code"),
        ("EL", "Election Code"),
        ("ES", "Estates Code"),
        ("FA", "Family Code"),
        ("FI", "Finance Code"),
        ("GV", "Government Code"),
        ("HS", "Health and Safety Code"),
        ("HR", "Human Resources Code"),
        ("IN", "Insurance Code"),
        ("I1", "Insurance Code - Not Codified"),
        ("LA", "Labor Code"),
        ("LG", "Local Government Code"),
        ("NR", "Natural Resources Code"),
        ("OC", "Occupations Code"),
        ("PW", "Parks and Wildlife Code"),
        ("PE", "Penal Code"),
        ("PR", "Property Code"),
        ("SD", "Special District Local Laws Code"),
        ("TX", "Tax Code"),
        ("TN", "Transportation Code"),
        ("UT", "Utilities Code"),
        ("WA", "Water Code"),
        ("CV", "Vernon's Civil Statutes"),
    )
    OFFICIAL_DOWNLOAD_EXCLUSIONS = (
        ("CN", "The Texas Constitution", "separate_constitutional_corpus"),
    )
    OFFICIAL_CODE_COUNT = len(OFFICIAL_CODES)
    OFFICIAL_DOWNLOAD_CODE_COUNT = OFFICIAL_CODE_COUNT + len(
        OFFICIAL_DOWNLOAD_EXCLUSIONS
    )
    last_texas_full_corpus_report: Dict[str, Any] = {}

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind the strict ZIP parser and shared closure seam to certification."""

        from . import strict_frontier_closure, texas_chapter

        return (texas_chapter, strict_frontier_closure)

    async def scrape_all(
        self,
        legal_areas: Optional[List[str]] = None,
        max_statutes: Optional[int] = None,
        rate_limit_delay: float = 2.0,
        hydrate_statute_text: bool = True,
    ) -> List[NormalizedStatute]:
        """Use one exact plural ZIP frontier only for an uncapped full run."""

        full_mode = self._full_corpus_enabled()
        if full_mode and (max_statutes is not None or legal_areas):
            raise RuntimeError(
                "Texas strict full-corpus ZIP route refuses caps or legal-area filters"
            )
        strict_full = full_mode and max_statutes is None and not legal_areas
        if not strict_full:
            return await super().scrape_all(
                legal_areas=legal_areas,
                max_statutes=max_statutes,
                rate_limit_delay=rate_limit_delay,
                hydrate_statute_text=hydrate_statute_text,
            )

        self._texas_strict_full_active = True
        self._texas_full_zip_frontier = None
        self._texas_full_zip_frontier_error = ""
        self._texas_full_code_reports: Dict[str, Dict[str, Any]] = {}
        self._texas_full_batch_stats: Dict[str, Any] = {}
        self._texas_full_catalog_evidence: Dict[str, Any] = {}
        self._last_texas_full_frontier = None
        self.last_texas_full_corpus_report = {}
        try:
            rows = await super().scrape_all(
                legal_areas=None,
                max_statutes=None,
                rate_limit_delay=rate_limit_delay,
                hydrate_statute_text=hydrate_statute_text,
            )
            return self._close_texas_full_zip_corpus(rows)
        finally:
            self._texas_strict_full_active = False
            self._texas_full_zip_frontier = None

    @staticmethod
    def _texas_frontier_headers() -> Dict[str, str]:
        return {
            "Accept": (
                "application/json,application/zip;q=0.95,"
                "application/octet-stream;q=0.9,*/*;q=0.5"
            ),
            "User-Agent": "ipfs-datasets-texas-statutes/3.0",
        }

    def _texas_zip_concurrency(self) -> int:
        return max(
            1,
            min(
                self.OFFICIAL_CODE_COUNT,
                self._env_int("STATE_SCRAPER_TX_ZIP_CONCURRENCY", default=8),
            ),
        )

    def _texas_zip_residual_retry_attempts(self) -> int:
        generic = self._env_int(
            "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
            default=1,
        )
        return max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_TX_ZIP_RESIDUAL_RETRY_ATTEMPTS",
                    default=generic,
                ),
            ),
        )

    def _parse_texas_download_manifest(self, payload: bytes) -> Dict[str, Any]:
        """Classify every row in the official TLC HTML-download manifest.

        The manifest currently mixes one constitutional bundle with the Texas
        statutory bundles.  Publication scope must account for that row
        explicitly, while retaining uncodified statutory collections such as
        Auxiliary Water Laws and Vernon's Civil Statutes.
        """

        try:
            document = json.loads(bytes(payload).decode("utf-8-sig"))
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Texas download manifest is not valid JSON") from exc
        source_rows = (
            document.get("StatuteCode") if isinstance(document, dict) else None
        )
        if not isinstance(source_rows, list) or not source_rows:
            raise RuntimeError("Texas download manifest omitted StatuteCode rows")

        statute_names = dict(self.OFFICIAL_CODES)
        excluded_names = {
            code: (name, reason)
            for code, name, reason in self.OFFICIAL_DOWNLOAD_EXCLUSIONS
        }
        expected_codes = set(statute_names).union(excluded_names)
        observed_codes: List[str] = []
        statute_rows: List[Dict[str, Any]] = []
        excluded_rows: List[Dict[str, Any]] = []
        for source_order, raw_row in enumerate(source_rows):
            if not isinstance(raw_row, Mapping):
                raise RuntimeError("Texas download manifest contains a non-object row")
            code = str(raw_row.get("code") or "").strip().upper()
            source_name = _norm_space(str(raw_row.get("CodeName") or ""))
            html_path = str(raw_row.get("Html") or "").strip()
            if (
                not re.fullmatch(r"[A-Z][A-Z0-9]", code)
                or not source_name
                or not html_path
            ):
                raise RuntimeError(
                    "Texas download manifest contains an unclassifiable HTML row: "
                    f"order={source_order} code={code!r}"
                )
            if code in observed_codes:
                raise RuntimeError(
                    f"Texas download manifest repeated code identity: {code}"
                )
            observed_codes.append(code)
            zip_url = "https://tcss.legis.texas.gov/resources/" + html_path.lstrip("/")
            expected_url = self.official_zip_url(code)
            if zip_url != expected_url:
                raise RuntimeError(
                    "Texas download manifest changed an exact HTML ZIP locator: "
                    f"code={code} observed={zip_url} expected={expected_url}"
                )
            common = {
                "code": code,
                "source_code_name": source_name,
                "source_order": source_order,
                "zip_url": zip_url,
            }
            if code in statute_names:
                statute_rows.append({**common, "code_name": statute_names[code]})
                continue
            excluded = excluded_names.get(code)
            if excluded is not None:
                expected_name, reason = excluded
                if source_name != expected_name:
                    raise RuntimeError(
                        "Texas excluded manifest scope changed identity: "
                        f"code={code} observed={source_name!r}"
                    )
                excluded_rows.append({**common, "reason": reason})
                continue
            raise RuntimeError(
                f"Texas download manifest exposed an unreviewed code: {code}"
            )

        observed_set = set(observed_codes)
        if observed_set != expected_codes:
            missing = sorted(expected_codes.difference(observed_set))
            unexpected = sorted(observed_set.difference(expected_codes))
            raise RuntimeError(
                "Texas official download manifest did not close exact scope; "
                f"missing={missing} unexpected={unexpected}"
            )
        observed_statute_codes = [str(row["code"]) for row in statute_rows]
        expected_statute_codes = [code for code, _name in self.OFFICIAL_CODES]
        if set(observed_statute_codes) != set(expected_statute_codes):
            raise RuntimeError("Texas statutory download membership is not exact")
        if len(source_rows) != self.OFFICIAL_DOWNLOAD_CODE_COUNT:
            raise RuntimeError(
                "Texas official download manifest changed row count: "
                f"observed={len(source_rows)} "
                f"expected={self.OFFICIAL_DOWNLOAD_CODE_COUNT}"
            )
        return {
            "excluded_rows": excluded_rows,
            "source_code_count": len(source_rows),
            "source_order": observed_codes,
            "statute_rows": statute_rows,
        }

    def _is_valid_texas_download_manifest(self, payload: bytes) -> bool:
        try:
            self._parse_texas_download_manifest(payload)
        except (RuntimeError, TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _looks_like_texas_download_manifest(payload: bytes) -> bool:
        """Accept a fresh changed manifest so it fails scope review, not to archive."""

        try:
            document = json.loads(bytes(payload).decode("utf-8-sig"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return False
        rows = document.get("StatuteCode") if isinstance(document, dict) else None
        return bool(
            isinstance(rows, list)
            and rows
            and all(
                isinstance(row, Mapping)
                and str(row.get("code") or "").strip()
                and str(row.get("Html") or "").strip()
                for row in rows
            )
        )

    @staticmethod
    def _is_valid_texas_zip_payload(payload: bytes) -> bool:
        if len(payload or b"") < 100 or not zipfile.is_zipfile(io.BytesIO(payload)):
            return False
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                return bool(archive.infolist()) and archive.testzip() is None
        except (OSError, ValueError, zipfile.BadZipFile):
            return False

    def _is_valid_texas_frontier_payload(self, payload: bytes) -> bool:
        return self._is_valid_texas_zip_payload(
            payload
        ) or self._looks_like_texas_download_manifest(payload)

    def _texas_zip_evidence_context(
        self,
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Bind one aligned parser input to its prospective transport proof."""

        from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
            canonicalize_state_law_transport_receipt,
        )

        digest = hashlib.sha256(bytes(payload)).hexdigest()
        if not isinstance(transport_receipt, Mapping):
            raise RuntimeError(
                f"Texas ZIP acquisition omitted a transport receipt: {source_url}"
            )
        canonical_receipt = canonicalize_state_law_transport_receipt(
            transport_receipt,
            official_url=source_url,
            content_sha256=digest,
        )

        envelope = parser_input_envelope
        envelope_body = getattr(envelope, "body", None)
        if envelope_body is not None and bytes(envelope_body) != bytes(payload):
            raise RuntimeError(
                f"Texas ZIP prospective envelope changed parser bytes: {source_url}"
            )
        if not isinstance(envelope, Mapping):
            to_dict = getattr(envelope, "to_dict", None)
            if callable(to_dict):
                envelope = to_dict()
        if isinstance(envelope, Mapping) and isinstance(
            envelope.get("parser_input_envelope"), Mapping
        ):
            envelope = envelope["parser_input_envelope"]

        receipt_sha256 = ""
        if isinstance(envelope, Mapping):
            acquisition = envelope.get("acquisition")
            if not isinstance(acquisition, Mapping):
                raise RuntimeError(
                    f"Texas ZIP parser envelope omitted acquisition: {source_url}"
                )
            body_sha256 = str(acquisition.get("body_sha256") or "").lower()
            receipt = acquisition.get("receipt")
            if not isinstance(receipt, Mapping):
                raise RuntimeError(
                    f"Texas ZIP parser envelope omitted receipt: {source_url}"
                )
            content = receipt.get("content")
            content_sha256 = (
                str(content.get("sha256") or "").lower()
                if isinstance(content, Mapping)
                else ""
            )
            endpoint = str(receipt.get("endpoint") or "").strip()
            if (
                body_sha256 != digest
                or content_sha256 != digest
                or endpoint.rstrip("/") != source_url.rstrip("/")
            ):
                raise RuntimeError(
                    f"Texas ZIP parser envelope does not replay exact bytes: {source_url}"
                )
            receipt_sha256 = str(receipt.get("receipt_sha256") or "").strip()
        elif self._state_law_acquisition_ledger is not None:
            raise RuntimeError(
                f"Texas strict evidence run omitted parser envelope: {source_url}"
            )

        return {
            "content_sha256": digest,
            "parser_input_receipt_sha256": receipt_sha256,
            "source_transport": str(canonical_receipt.get("source_transport") or ""),
            "transport_receipt": canonical_receipt,
        }

    async def _fetch_texas_full_zip_frontier(self) -> Dict[str, Dict[str, Any]]:
        """Acquire the manifest and all exact statute ZIPs in one shared batch."""

        zip_urls = [self.official_zip_url(code) for code, _name in self.OFFICIAL_CODES]
        urls = [self.OFFICIAL_DOWNLOADS_URL, *zip_urls]
        if len(zip_urls) != self.OFFICIAL_CODE_COUNT or len(set(urls)) != len(urls):
            raise RuntimeError("Texas exact ZIP catalog changed count or identity")
        batch = (
            await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
                urls,
                residual_retry_attempts=self._texas_zip_residual_retry_attempts(),
                timeout_seconds=120,
                headers=self._texas_frontier_headers(),
                content_validator=self._is_valid_texas_frontier_payload,
                media_type="application/octet-stream",
                max_concurrency=self._texas_zip_concurrency(),
                prefer_direct=True,
                common_crawl_domain_terms=(
                    self.OFFICIAL_ZIP_HOST,
                    self.OFFICIAL_DOMAIN,
                ),
                common_crawl_url_terms=(
                    "/resources/Zips/",
                    self.OFFICIAL_DOWNLOADS_PATH,
                ),
                common_crawl_mime_terms=("json", "zip", "octet-stream"),
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
        expected_input_count = self.OFFICIAL_CODE_COUNT + 1
        if aligned_lengths != {expected_input_count}:
            raise RuntimeError(
                "Texas manifest/ZIP frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != urls:
            raise RuntimeError(
                "Texas manifest/ZIP frontier changed URL order or identity"
            )
        manifest_payload = bytes(batch.payloads[0] or b"")
        manifest_error = batch.errors[0]
        if manifest_error is not None or not self._looks_like_texas_download_manifest(
            manifest_payload
        ):
            raise RuntimeError(
                "Texas official download manifest is unresolved after archival "
                f"fallback: {manifest_error or 'invalid manifest parser input'}"
            )
        manifest = self._parse_texas_download_manifest(manifest_payload)
        manifest_urls_by_code = {
            str(row["code"]): str(row["zip_url"]) for row in manifest["statute_rows"]
        }
        expected_urls_by_code = {
            code: self.official_zip_url(code) for code, _name in self.OFFICIAL_CODES
        }
        if manifest_urls_by_code != expected_urls_by_code:
            raise RuntimeError("Texas source-derived statute ZIP membership changed")
        failures = [
            {"code": code, "url": url, "error": error or "invalid ZIP parser input"}
            for (code, _name), url, payload, error in zip(
                self.OFFICIAL_CODES,
                batch.urls[1:],
                batch.payloads[1:],
                batch.errors[1:],
                strict=True,
            )
            if error is not None or not self._is_valid_texas_zip_payload(payload)
        ]
        if failures:
            raise RuntimeError(
                "Texas exact ZIP frontier is incomplete after residual-only retries: "
                f"{failures}"
            )

        manifest_evidence = self._texas_zip_evidence_context(
            source_url=self.OFFICIAL_DOWNLOADS_URL,
            payload=manifest_payload,
            transport_receipt=batch.transport_receipts[0],
            parser_input_envelope=batch.parser_input_envelopes[0],
        )
        self._texas_full_catalog_evidence = {
            "content_sha256": str(manifest_evidence["content_sha256"]),
            "excluded_rows": list(manifest["excluded_rows"]),
            "parser_input_receipt_sha256": str(
                manifest_evidence.get("parser_input_receipt_sha256") or ""
            ),
            "source_code_count": int(manifest["source_code_count"]),
            "source_order": list(manifest["source_order"]),
            "source_transport": str(manifest_evidence.get("source_transport") or ""),
            "statute_rows": list(manifest["statute_rows"]),
            "transport_receipt": dict(manifest_evidence.get("transport_receipt") or {}),
            "url": self.OFFICIAL_DOWNLOADS_URL,
        }

        frontier: Dict[str, Dict[str, Any]] = {}
        for (code, name), url, payload, receipt, envelope in zip(
            self.OFFICIAL_CODES,
            batch.urls[1:],
            batch.payloads[1:],
            batch.transport_receipts[1:],
            batch.parser_input_envelopes[1:],
            strict=True,
        ):
            evidence = self._texas_zip_evidence_context(
                source_url=url,
                payload=bytes(payload),
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            frontier[code] = {
                "code_name": name,
                "evidence": evidence,
                "payload": bytes(payload),
                "source_code_name": next(
                    str(row["source_code_name"])
                    for row in manifest["statute_rows"]
                    if str(row["code"]) == code
                ),
                "url": url,
            }
        self._texas_full_batch_stats = dict(batch.stats or {})
        return frontier

    async def _ensure_texas_full_zip_frontier(self) -> Dict[str, Dict[str, Any]]:
        frontier = getattr(self, "_texas_full_zip_frontier", None)
        if isinstance(frontier, dict):
            return frontier
        prior_error = str(getattr(self, "_texas_full_zip_frontier_error", "") or "")
        if prior_error:
            raise RuntimeError(prior_error)
        try:
            frontier = await self._fetch_texas_full_zip_frontier()
        except Exception as exc:
            self._texas_full_zip_frontier_error = (
                f"Texas plural ZIP acquisition failed: {type(exc).__name__}: {exc}"
            )
            raise RuntimeError(self._texas_full_zip_frontier_error) from exc
        self._texas_full_zip_frontier = frontier
        return frontier

    @staticmethod
    def _texas_member_is_superseded(member_name: str) -> bool:
        return bool(_TEXAS_SUPERSEDED_MEMBER_RE.search(str(member_name or "")))

    @staticmethod
    def _decode_texas_member(payload: bytes) -> tuple[str, str]:
        for encoding in ("utf-8-sig", "windows-1252"):
            try:
                return payload.decode(encoding, errors="strict"), encoding
            except UnicodeDecodeError:
                continue
        raise RuntimeError("Texas HTML member has no supported exact text encoding")

    def _parse_texas_full_zip_member_inventory(
        self,
        *,
        code_abbrev: str,
        code_name: str,
        source_code_name: str = "",
        zip_url: str,
        payload: bytes,
        evidence: Mapping[str, Any],
    ) -> tuple[List[NormalizedStatute], Dict[str, Any]]:
        """Close every file member and section heading in one retained ZIP."""

        from .texas_chapter import parse_texas_chapter_html_strict

        statutes: List[NormalizedStatute] = []
        operative_members: List[Dict[str, Any]] = []
        terminal_members: List[Dict[str, Any]] = []
        residual_members: List[Dict[str, Any]] = []
        member_reports: List[Dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise RuntimeError(
                    f"Texas {code_abbrev} ZIP failed CRC at {corrupt_member}"
                )
            infos = list(archive.infolist())
            member_names = [str(info.filename or "") for info in infos]
            if len(member_names) != len(set(member_names)):
                raise RuntimeError(
                    f"Texas {code_abbrev} ZIP contains duplicate exact member names"
                )
            active_member_pattern = re.compile(
                rf"^{re.escape(code_abbrev)}\."
                r"(?P<chapter>[0-9A-Za-z_-]+(?:\.[0-9A-Za-z_-]+)*?)"
                r"(?:\.v[1-9][0-9]*)?\.html?$",
                re.IGNORECASE,
            )
            for source_order, info in sorted(
                enumerate(infos),
                key=lambda item: (item[1].filename.casefold(), item[0]),
            ):
                member_name = str(info.filename or "")
                member_row = {
                    "compressed_size": int(info.compress_size),
                    "file_size": int(info.file_size),
                    "member_name": member_name,
                    "source_order": int(source_order),
                }
                unsafe_member = (
                    not member_name
                    or member_name.startswith(("/", "\\"))
                    or "\\" in member_name
                    or ".." in member_name.split("/")
                )
                if unsafe_member or info.is_dir() or bool(info.flag_bits & 0x1):
                    residual_members.append(
                        {
                            **member_row,
                            "reason": "unsafe_directory_or_encrypted_member",
                        }
                    )
                    continue
                if self._texas_member_is_superseded(member_name):
                    terminal_members.append(
                        {
                            **member_row,
                            "disposition": "superseded_official_member_copy",
                        }
                    )
                    continue
                if active_member_pattern.fullmatch(member_name) is None:
                    residual_members.append(
                        {
                            **member_row,
                            "reason": "unexpected_nonchapter_member_identity",
                        }
                    )
                    continue
                try:
                    member_bytes = archive.read(info)
                    html, encoding = self._decode_texas_member(member_bytes)
                except Exception as exc:
                    residual_members.append(
                        {
                            **member_row,
                            "reason": f"member_read_or_decode_failed:{type(exc).__name__}",
                        }
                    )
                    continue
                source_url = (
                    f"https://{self.OFFICIAL_DOMAIN}/Docs/{code_abbrev}/htm/"
                    f"{member_name}"
                )
                member_statutes, parse_report = parse_texas_chapter_html_strict(
                    html,
                    code_name=code_name,
                    code_abbrev=code_abbrev,
                    member_name=member_name,
                    source_url=source_url,
                    zip_url=zip_url,
                )
                parse_report = {
                    **parse_report,
                    "encoding": encoding,
                    "member_content_sha256": hashlib.sha256(member_bytes).hexdigest(),
                    "source_order": int(source_order),
                    "source_url": source_url,
                }
                if int(parse_report.get("candidate_sections") or 0) == 0:
                    member_text = self._extract_text_from_html(html)
                    if _TEXAS_REPEALED_CHAPTER_RE.search(member_text):
                        terminal_members.append(
                            {
                                **member_row,
                                "content_sha256": parse_report["member_content_sha256"],
                                "disposition": "repealed_chapter_without_sections",
                            }
                        )
                        member_reports.append(parse_report)
                        continue
                    residual_members.append(
                        {
                            **member_row,
                            "reason": "active_member_exposed_no_section_frontier",
                        }
                    )
                    member_reports.append(parse_report)
                    continue
                if parse_report.get("closed") is not True:
                    residual_members.append(
                        {
                            **member_row,
                            "parser_residuals": list(
                                parse_report.get("parser_residuals") or []
                            ),
                            "reason": "section_parser_frontier_not_closed",
                        }
                    )
                elif member_statutes:
                    operative_members.append(
                        {
                            **member_row,
                            "candidate_sections": int(
                                parse_report.get("candidate_sections") or 0
                            ),
                            "operative_sections": len(member_statutes),
                            "terminal_sections": int(
                                parse_report.get("terminal_sections") or 0
                            ),
                        }
                    )
                else:
                    terminal_members.append(
                        {
                            **member_row,
                            "disposition": "all_section_headings_terminal",
                        }
                    )
                for statute in member_statutes:
                    statute.structured_data = {
                        **dict(statute.structured_data or {}),
                        "content_sha256": str(evidence.get("content_sha256") or ""),
                        "parser_input_receipt_sha256": str(
                            evidence.get("parser_input_receipt_sha256") or ""
                        ),
                        "source_transport": str(evidence.get("source_transport") or ""),
                        "source_code_name": str(source_code_name or code_name),
                        "transport_receipt": dict(
                            evidence.get("transport_receipt") or {}
                        ),
                        "zip_member_content_sha256": parse_report[
                            "member_content_sha256"
                        ],
                    }
                    statutes.append(statute)
                member_reports.append(parse_report)

        candidate_sections = sum(
            int(report.get("candidate_sections") or 0) for report in member_reports
        )
        operative_sections = sum(
            int(report.get("operative_sections") or 0) for report in member_reports
        )
        terminal_sections = sum(
            int(report.get("terminal_sections") or 0) for report in member_reports
        )
        parser_residual_count = sum(
            len(list(report.get("parser_residuals") or [])) for report in member_reports
        )
        member_count = (
            len(operative_members) + len(terminal_members) + len(residual_members)
        )
        report = {
            "candidate_sections": candidate_sections,
            "closed": (
                member_count == len(infos)
                and candidate_sections
                == operative_sections + terminal_sections + parser_residual_count
                and len(statutes) == operative_sections
                and not residual_members
                and parser_residual_count == 0
            ),
            "code_abbrev": code_abbrev,
            "code_name": code_name,
            "source_code_name": str(source_code_name or code_name),
            "member_count": len(infos),
            "member_reports": member_reports,
            "operative_member_count": len(operative_members),
            "operative_members": operative_members,
            "operative_sections": operative_sections,
            "parser_residual_count": parser_residual_count,
            "residual_member_count": len(residual_members),
            "residual_members": residual_members,
            "terminal_member_count": len(terminal_members),
            "terminal_members": terminal_members,
            "terminal_sections": terminal_sections,
            "zip_content_sha256": str(evidence.get("content_sha256") or ""),
            "zip_url": zip_url,
        }
        if report["closed"] is not True:
            raise RuntimeError(
                f"Texas {code_abbrev} ZIP/member completion algebra failed: "
                f"members={len(infos)} operative_members={len(operative_members)} "
                f"terminal_members={len(terminal_members)} "
                f"residual_members={residual_members[:3]} "
                f"section_algebra={candidate_sections} != {operative_sections} + "
                f"{terminal_sections} + {parser_residual_count}"
            )
        return statutes, report

    def _texas_exact_frontier(
        self,
        *,
        catalog_evidence: Mapping[str, Any],
        code_reports: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Build the content-derived manifest/bundle/section closure contract."""

        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        reports = [dict(report) for report in code_reports]
        expected_codes = [code for code, _name in self.OFFICIAL_CODES]
        observed_codes = [str(report.get("code_abbrev") or "") for report in reports]
        if observed_codes != expected_codes:
            raise RuntimeError("Texas exact frontier changed statute bundle order")
        if len(reports) != self.OFFICIAL_CODE_COUNT or any(
            report.get("closed") is not True for report in reports
        ):
            raise RuntimeError("Texas exact frontier contains an open ZIP report")

        catalog_digest = str(catalog_evidence.get("content_sha256") or "")
        catalog_source_count = int(catalog_evidence.get("source_code_count") or 0)
        excluded_downloads = [
            dict(row) for row in catalog_evidence.get("excluded_rows", [])
        ]
        if (
            not re.fullmatch(r"[a-f0-9]{64}", catalog_digest)
            or catalog_source_count != self.OFFICIAL_DOWNLOAD_CODE_COUNT
            or len(excluded_downloads) != len(self.OFFICIAL_DOWNLOAD_EXCLUSIONS)
        ):
            raise RuntimeError("Texas exact frontier lacks closed manifest evidence")

        candidate_sections = sum(
            int(report.get("candidate_sections") or 0) for report in reports
        )
        operative_sections = sum(
            int(report.get("operative_sections") or 0) for report in reports
        )
        terminal_sections = sum(
            int(report.get("terminal_sections") or 0) for report in reports
        )
        parser_residuals = sum(
            int(report.get("parser_residual_count") or 0) for report in reports
        )
        member_count = sum(int(report.get("member_count") or 0) for report in reports)
        operative_members = sum(
            int(report.get("operative_member_count") or 0) for report in reports
        )
        terminal_members = sum(
            int(report.get("terminal_member_count") or 0) for report in reports
        )
        residual_members = sum(
            int(report.get("residual_member_count") or 0) for report in reports
        )
        if (
            not candidate_sections
            or candidate_sections != operative_sections + terminal_sections
            or parser_residuals
            or residual_members
            or member_count != operative_members + terminal_members
        ):
            raise RuntimeError("Texas exact source disposition did not close")

        terminal_dispositions: Dict[str, int] = {}
        terminal_member_dispositions: Dict[str, int] = {}
        for report in reports:
            for terminal_member in report.get("terminal_members", []):
                disposition = str(
                    terminal_member.get("disposition") or "terminal_member"
                )
                terminal_member_dispositions[disposition] = (
                    terminal_member_dispositions.get(disposition, 0) + 1
                )
            for member_report in report.get("member_reports", []):
                for terminal in member_report.get("terminal_dispositions", []):
                    disposition = str(terminal.get("disposition") or "terminal")
                    terminal_dispositions[disposition] = (
                        terminal_dispositions.get(disposition, 0) + 1
                    )
        if sum(terminal_dispositions.values()) != terminal_sections:
            raise RuntimeError("Texas terminal section dispositions are incomplete")
        if sum(terminal_member_dispositions.values()) != terminal_members:
            raise RuntimeError(
                "Texas terminal bundle-member dispositions are incomplete"
            )

        source_bundles = [
            {
                "code_abbrev": str(report["code_abbrev"]),
                "content_sha256": str(report["zip_content_sha256"]),
                "member_count": int(report["member_count"]),
                "operative_sections": int(report["operative_sections"]),
                "source_code_name": str(report["source_code_name"]),
                "source_sections": int(report["candidate_sections"]),
                "terminal_sections": int(report["terminal_sections"]),
                "zip_url": str(report["zip_url"]),
            }
            for report in reports
        ]
        zip_frontier_sha256 = hashlib.sha256(
            json.dumps(
                source_bundles,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        disposition = {
            "discovered": candidate_sections,
            "fetched": operative_sections,
            "excluded": terminal_sections,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": True,
            "closed": True,
            "disposition": disposition,
            "download_manifest_content_sha256": catalog_digest,
            "download_manifest_unit_count": catalog_source_count,
            "download_scope_exclusions": excluded_downloads,
            "enumerator_closed": True,
            "expected_index_units": candidate_sections,
            "member_count": member_count,
            "operative_member_count": operative_members,
            "pagination_closed": True,
            "parser_residual_count": parser_residuals,
            "schema_version": "texas-tlc-statute-zip-source-frontier-v2",
            "scope_closed": True,
            "source_manifest_order": list(catalog_evidence.get("source_order") or []),
            "statute_bundle_count": len(reports),
            "statute_zip_frontier_sha256": zip_frontier_sha256,
            "terminal_dispositions": dict(sorted(terminal_dispositions.items())),
            "terminal_member_count": terminal_members,
            "terminal_member_dispositions": dict(
                sorted(terminal_member_dispositions.items())
            ),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": candidate_sections,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _close_texas_full_zip_corpus(
        self,
        rows: List[NormalizedStatute],
    ) -> List[NormalizedStatute]:
        expected_codes = [code for code, _name in self.OFFICIAL_CODES]
        reports = getattr(self, "_texas_full_code_reports", {})
        if list(reports) != expected_codes:
            raise RuntimeError(
                "Texas strict ZIP parser did not close the exact statute-code order"
            )
        candidate_sections = sum(
            int(report.get("candidate_sections") or 0) for report in reports.values()
        )
        operative_sections = sum(
            int(report.get("operative_sections") or 0) for report in reports.values()
        )
        terminal_sections = sum(
            int(report.get("terminal_sections") or 0) for report in reports.values()
        )
        parser_residuals = sum(
            int(report.get("parser_residual_count") or 0) for report in reports.values()
        )
        canonical_keys = [
            str((row.structured_data or {}).get("canonical_section_key") or "")
            for row in rows
        ]
        statute_ids = [str(row.statute_id or "") for row in rows]
        if (
            not candidate_sections
            or candidate_sections
            != operative_sections + terminal_sections + parser_residuals
            or parser_residuals
            or len(rows) != operative_sections
            or any(not key for key in canonical_keys)
            or len(canonical_keys) != len(set(canonical_keys))
            or len(statute_ids) != len(set(statute_ids))
        ):
            raise RuntimeError(
                "Texas exact full-corpus closure or canonical identity algebra failed"
            )
        member_count = sum(int(report["member_count"]) for report in reports.values())
        operative_members = sum(
            int(report["operative_member_count"]) for report in reports.values()
        )
        terminal_members = sum(
            int(report["terminal_member_count"]) for report in reports.values()
        )
        residual_members = sum(
            int(report["residual_member_count"]) for report in reports.values()
        )
        if member_count != operative_members + terminal_members + residual_members:
            raise RuntimeError("Texas exact ZIP member inventory algebra failed")
        catalog_evidence = getattr(self, "_texas_full_catalog_evidence", {})
        if not isinstance(catalog_evidence, Mapping):
            raise RuntimeError("Texas strict ZIP parser omitted manifest evidence")
        exact_frontier = self._texas_exact_frontier(
            catalog_evidence=catalog_evidence,
            code_reports=list(reports.values()),
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        report = {
            "batch_stats": dict(getattr(self, "_texas_full_batch_stats", {}) or {}),
            "candidate_sections": candidate_sections,
            "closed": True,
            "code_count": len(reports),
            "code_reports": list(reports.values()),
            "download_manifest_content_sha256": str(
                catalog_evidence.get("content_sha256") or ""
            ),
            "download_manifest_unit_count": int(
                catalog_evidence.get("source_code_count") or 0
            ),
            "download_scope_exclusions": list(
                catalog_evidence.get("excluded_rows") or []
            ),
            "expected_code_count": self.OFFICIAL_CODE_COUNT,
            "frontier": exact_frontier,
            "member_count": member_count,
            "operative_member_count": operative_members,
            "operative_sections": operative_sections,
            "parser_residual_count": parser_residuals,
            "schema_version": "texas-strict-zip-corpus-closure-v2",
            "terminal_member_count": terminal_members,
            "terminal_sections": terminal_sections,
            "zip_urls": [self.official_zip_url(code) for code in expected_codes],
        }
        self.last_texas_full_corpus_report = report
        self._last_texas_full_frontier = {
            "boundary_first": str(report["zip_urls"][0]),
            "boundary_last": str(report["zip_urls"][-1]),
            "catalog_evidence": dict(catalog_evidence),
            "code_reports": list(reports.values()),
            "frontier": exact_frontier,
            "observed_at": observed_at,
            "transport_batch_stats": dict(
                getattr(self, "_texas_full_batch_stats", {}) or {}
            ),
        }
        self._write_partial_checkpoint(
            rows,
            code_name="Texas Codes",
            stage_label="texas:strict-statute-zip-complete",
            force=True,
            replace_existing_rows=True,
            extra={
                "codes_completed": self.OFFICIAL_CODE_COUNT,
                "codes_total": self.OFFICIAL_CODE_COUNT,
                "discovered_sections": candidate_sections,
                "operative_sections": operative_sections,
                "terminal_sections_classified": terminal_sections,
                "texas_zip_closure_report": report,
            },
        )
        return rows

    def _replay_texas_retained_input(
        self,
        url: str,
        *,
        content_validator: Any,
        input_label: str,
    ) -> bytes:
        """Replay one exact manifest/ZIP parser input without network I/O."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Texas retained replay requires an attached ledger")
        canonical_url = self._canonical_fetch_url(url)
        sanitized_headers = _sanitized_multifetch_headers(
            self._texas_frontier_headers()
        )
        retained = ledger.replay_retained_parser_input(
            official_url=canonical_url,
            sanitized_request=_sanitized_multifetch_request(
                canonical_url,
                sanitized_headers=sanitized_headers,
            ),
        )
        if retained is None:
            raise RuntimeError(
                f"Texas retained replay is missing {input_label}: {canonical_url}"
            )
        envelope = getattr(retained, "envelope", None)
        body = getattr(envelope, "body", None)
        raw = bytes(body or b"")
        if not raw or not bool(content_validator(raw)):
            raise RuntimeError(
                f"Texas retained replay input is invalid: {canonical_url}"
            )
        receipt = getattr(retained, "transport_receipt", None)
        digest = hashlib.sha256(raw).hexdigest()
        if not isinstance(receipt, Mapping):
            raise RuntimeError(
                f"Texas retained replay omitted a receipt: {canonical_url}"
            )
        observed_url = str(
            receipt.get("official_url") or receipt.get("endpoint") or ""
        ).strip()
        observed_digest = (
            str(
                receipt.get("content_sha256")
                or (
                    receipt.get("content", {}).get("sha256")
                    if isinstance(receipt.get("content"), Mapping)
                    else ""
                )
                or ""
            )
            .strip()
            .lower()
        )
        if (
            self._canonical_fetch_url(observed_url) != canonical_url
            or observed_digest != digest
        ):
            raise RuntimeError(
                f"Texas retained replay receipt changed input identity: {canonical_url}"
            )
        return raw

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Reparse retained manifest/ZIP inputs and seal publication parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Texas frontier closure requires an attached ledger")
        first = getattr(self, "_last_texas_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Texas source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        first_frontier = first.get("frontier")
        first_reports_raw = first.get("code_reports")
        first_catalog = first.get("catalog_evidence")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_catalog, Mapping)
            or not isinstance(first_reports_raw, Sequence)
            or isinstance(first_reports_raw, (str, bytes, bytearray))
            or not first_reports_raw
            or any(not isinstance(row, Mapping) for row in first_reports_raw)
        ):
            raise RuntimeError("Texas first exact frontier is incomplete")
        first_reports = [dict(row) for row in first_reports_raw]

        manifest_payload = self._replay_texas_retained_input(
            self.OFFICIAL_DOWNLOADS_URL,
            content_validator=self._looks_like_texas_download_manifest,
            input_label="download manifest",
        )
        manifest = self._parse_texas_download_manifest(manifest_payload)
        manifest_digest = hashlib.sha256(manifest_payload).hexdigest()
        if manifest_digest != str(first_catalog.get("content_sha256") or ""):
            raise RuntimeError("Texas retained download manifest digest changed")
        replay_catalog = {
            "content_sha256": manifest_digest,
            "excluded_rows": list(manifest["excluded_rows"]),
            "source_code_count": int(manifest["source_code_count"]),
            "source_order": list(manifest["source_order"]),
            "statute_rows": list(manifest["statute_rows"]),
        }
        expected_catalog_identity = [
            (
                str(report.get("code_abbrev") or ""),
                str(report.get("source_code_name") or ""),
                str(report.get("zip_url") or ""),
            )
            for report in first_reports
        ]
        replay_catalog_identity = [
            (
                str(row["code"]),
                str(row["source_code_name"]),
                str(row["zip_url"]),
            )
            for row in manifest["statute_rows"]
        ]
        if expected_catalog_identity != replay_catalog_identity:
            raise RuntimeError("Texas retained statute manifest membership changed")

        replay_rows: List[NormalizedStatute] = []
        replay_reports: List[Dict[str, Any]] = []
        for expected in first_reports:
            code = str(expected.get("code_abbrev") or "")
            code_name = str(expected.get("code_name") or "")
            source_code_name = str(expected.get("source_code_name") or "")
            zip_url = str(expected.get("zip_url") or "")
            payload = self._replay_texas_retained_input(
                zip_url,
                content_validator=self._is_valid_texas_zip_payload,
                input_label=f"{code} statute ZIP",
            )
            digest = hashlib.sha256(payload).hexdigest()
            if digest != str(expected.get("zip_content_sha256") or ""):
                raise RuntimeError(f"Texas retained ZIP digest changed: {code}")
            rows, report = self._parse_texas_full_zip_member_inventory(
                code_abbrev=code,
                code_name=code_name,
                source_code_name=source_code_name,
                zip_url=zip_url,
                payload=payload,
                evidence={"content_sha256": digest},
            )
            if report != expected:
                raise RuntimeError(
                    f"Texas retained ZIP/member inventory changed: {code}"
                )
            replay_rows.extend(rows)
            replay_reports.append(report)

        replayed_frontier = self._texas_exact_frontier(
            catalog_evidence=replay_catalog,
            code_reports=replay_reports,
        )
        observed_at = str(first.get("observed_at") or "")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="TX",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_DOWNLOADS_URL,
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(replay_reports),
            pagination_total=int(manifest["source_code_count"]),
            transport={
                "fixture": False,
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_manifest_and_zip",
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "synthetic": False,
                "first_pass_batch_stats": dict(
                    first.get("transport_batch_stats") or {}
                ),
            },
        )

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        structured = dict(statute.structured_data or {})
        return (
            structured.get("source_kind") == "official_texas_statutes_html_zip"
            and structured.get("strict_source_closure") is True
            and bool(str(structured.get("canonical_section_key") or "").strip())
        )

    def get_base_url(self) -> str:
        """Get base URL for Texas statutes."""
        return "https://statutes.capitol.texas.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Texas codes.

        Texas organizes its laws into codes.
        """
        # Keep acquisition in lockstep with the exhaustive statutory catalog.
        # The Texas Administrative Code is a separate regulation corpus.
        return [
            {
                "name": name,
                "url": self.official_html_url(abbrev),
                "type": abbrev,
            }
            for abbrev, name in self.OFFICIAL_CODES
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific Texas code.

        Args:
            code_name: Name of the code
            code_url: URL to the code

        Returns:
            List of normalized statutes
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        statutes = []

        try:
            lower_name = str(code_name or "").lower()
            lower_url = str(code_url or "").lower()
            limit = self._effective_scrape_limit(max_statutes, default=160)
            if "administrative" in lower_name or "readtac" in lower_url:
                return await self._scrape_texas_admin_code(
                    code_name=code_name,
                    code_url=code_url,
                    max_statutes=limit,
                )

            if bool(getattr(self, "_texas_strict_full_active", False)):
                bundled_statutes = await self._scrape_statute_html_zip(
                    code_name=code_name,
                    code_url=code_url,
                    max_statutes=None,
                )
                if not bundled_statutes:
                    raise RuntimeError(
                        f"Texas strict ZIP member frontier is empty for {code_name}"
                    )
                return bundled_statutes

            from .texas_constitution import (
                configured_constitution_html_path,
                parse_texas_constitution_html,
            )

            constitution_path = configured_constitution_html_path()
            if constitution_path is not None or "constitution" in lower_name:
                if constitution_path is not None:
                    constitution_rows = parse_texas_constitution_html(
                        constitution_path.read_text(encoding="utf-8", errors="replace"),
                        article_id="1",
                        code_name=code_name or "Texas Constitution",
                        max_statutes=limit,
                    )
                    if constitution_rows:
                        return (
                            constitution_rows
                            if limit is None
                            else constitution_rows[: int(limit)]
                        )

            from .texas_chapter import (
                configured_chapter_html_path,
                parse_texas_chapter_html,
            )

            local_chapter = configured_chapter_html_path()
            if local_chapter is not None:
                local_rows = parse_texas_chapter_html(
                    local_chapter.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name,
                    code_abbrev=self._derive_code_abbrev(
                        code_name=code_name, code_url=code_url
                    )
                    or "PE",
                    max_statutes=limit,
                )
                if local_rows:
                    return local_rows if limit is None else local_rows[: int(limit)]

            bundled_statutes = await self._scrape_statute_html_zip(
                code_name=code_name,
                code_url=code_url,
                max_statutes=limit,
            )
            if bundled_statutes:
                self.logger.info(
                    f"Scraped {len(bundled_statutes)} sections from official Texas HTML zip for {code_name}"
                )
                return bundled_statutes

            if self._full_corpus_enabled() and max_statutes is None:
                # A code landing page (or one synthetic code-level row) cannot
                # prove the member frontier of the official HTML ZIP.  Full
                # acquisition must fail this code closed and let scrape_all
                # report the missing catalog unit.
                self.logger.error(
                    "Texas full-corpus code has no parsed official HTML ZIP: %s",
                    code_name,
                )
                return []

            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                raise RuntimeError(f"empty response for {code_url}")

            page_html = page_bytes.decode("utf-8", errors="replace")
            soup = BeautifulSoup(page_bytes, "html.parser")

            # Parse Texas Legislature's structure
            # Texas uses a specific HTML structure for their statutes

            # Extract legal area
            legal_area = self._identify_legal_area(code_name)

            # Find section links
            section_links = soup.find_all(
                "a", href=re.compile(r".*\.htm", re.IGNORECASE)
            )
            if not section_links:
                # Try finding any links
                fallback_link_limit = None if limit is None else 100
                section_links = soup.find_all("a", href=True, limit=fallback_link_limit)

            page_full_text = self._extract_text_from_html(page_html)
            seen_section_numbers = set()

            scan_links = (
                section_links
                if limit is None
                else section_links[: max(120, int(limit) * 5)]
            )
            for i, link in enumerate(scan_links):
                if limit is not None and len(statutes) >= int(limit):
                    break
                section_text = link.get_text(strip=True)
                section_url = link.get("href", "")

                if not section_text or len(section_text) < 3:
                    continue

                if not section_url.startswith("http"):
                    from urllib.parse import urljoin

                    section_url = urljoin(code_url, section_url)

                # Extract section number
                section_number = self._extract_section_number(section_text)
                if not section_number:
                    section_number = f"{i + 1}"

                if section_number in seen_section_numbers:
                    continue

                section_full_text = await self._fetch_section_text(
                    section_url=section_url, fallback_text=page_full_text
                )
                if len(section_full_text) < 280:
                    continue

                seen_section_numbers.add(section_number)

                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_text[:200],
                    full_text=section_full_text,
                    source_url=section_url,
                    legal_area=legal_area,
                    official_cite=f"Tex. {code_name} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_texas_statutes_html",
                        "discovery_method": "official_code_section_links",
                        "skip_hydrate": True,
                    },
                )

                statutes.append(statute)

            # Fallback: emit a code-level record if section links are sparse.
            if not statutes and len(page_full_text) >= 280:
                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § 1",
                        code_name=code_name,
                        section_number="1",
                        section_name=f"{code_name} (code-level)",
                        full_text=page_full_text,
                        source_url=code_url,
                        legal_area=legal_area,
                        official_cite=f"Tex. {code_name}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_texas_statutes_html",
                            "discovery_method": "official_code_level_fallback",
                            "skip_hydrate": True,
                        },
                    )
                )

            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")

        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
            if self._full_corpus_enabled() and max_statutes is None:
                raise

        return statutes

    async def _scrape_statute_html_zip(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        code_abbrev = self._derive_code_abbrev(code_name=code_name, code_url=code_url)
        if not code_abbrev:
            return []

        if bool(getattr(self, "_texas_strict_full_active", False)):
            frontier = await self._ensure_texas_full_zip_frontier()
            retained = frontier.get(code_abbrev)
            if not isinstance(retained, Mapping):
                raise RuntimeError(
                    f"Texas exact ZIP frontier omitted code {code_abbrev}"
                )
            try:
                rows, report = self._parse_texas_full_zip_member_inventory(
                    code_abbrev=code_abbrev,
                    code_name=code_name,
                    source_code_name=str(retained.get("source_code_name") or code_name),
                    zip_url=str(retained.get("url") or ""),
                    payload=bytes(retained.get("payload") or b""),
                    evidence=dict(retained.get("evidence") or {}),
                )
            except Exception as exc:
                self._texas_full_code_reports[code_abbrev] = {
                    "closed": False,
                    "code_abbrev": code_abbrev,
                    "code_name": code_name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "zip_url": str(retained.get("url") or ""),
                }
                raise
            self._texas_full_code_reports[code_abbrev] = report
            return rows

        zip_url = await self._resolve_code_html_zip_url(code_abbrev)
        if not zip_url:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(
            zip_url, timeout_seconds=90
        )
        if not payload or not zipfile.is_zipfile(io.BytesIO(payload)):
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if name.lower().endswith((".htm", ".html")) and not name.endswith("/")
            )
            for file_index, member_name in enumerate(names, start=1):
                if limit is not None and len(statutes) >= limit:
                    break
                try:
                    html = archive.read(member_name).decode(
                        "utf-8-sig", errors="replace"
                    )
                except Exception:
                    continue
                chapter_statutes = self._parse_texas_chapter_html(
                    html=html,
                    code_name=code_name,
                    code_abbrev=code_abbrev,
                    member_name=member_name,
                    zip_url=zip_url,
                    seen_sections=seen_sections,
                    remaining=None if limit is None else max(0, limit - len(statutes)),
                )
                statutes.extend(chapter_statutes)
                if (
                    len(statutes) == 1
                    or len(statutes) % 500 == 0
                    or file_index == len(names)
                ):
                    self.logger.info(
                        "Texas official zip scrape: code=%s chapters=%s/%s statutes_so_far=%s",
                        code_abbrev,
                        file_index,
                        len(names),
                        len(statutes),
                    )

        return statutes[:limit] if limit is not None else statutes

    async def _resolve_code_html_zip_url(self, code_abbrev: str) -> str:
        default_url = (
            f"https://tcss.legis.texas.gov/resources/Zips/{code_abbrev}.htm.zip"
        )
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                "https://statutes.capitol.texas.gov/assets/StatuteCodeDownloads.json",
                timeout_seconds=30,
            )
            data = (
                json.loads(payload.decode("utf-8-sig", errors="replace"))
                if payload
                else {}
            )
        except Exception:
            data = {}
        rows = data.get("StatuteCode") if isinstance(data, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("code") or "").upper() != code_abbrev.upper():
                    continue
                html_path = str(row.get("Html") or "").strip()
                if html_path:
                    return "https://tcss.legis.texas.gov/resources/" + html_path.lstrip(
                        "/"
                    )
        return default_url

    def _parse_texas_chapter_html(
        self,
        *,
        html: str,
        code_name: str,
        code_abbrev: str,
        member_name: str,
        zip_url: str,
        seen_sections: set[str],
        remaining: Optional[int],
    ) -> List[NormalizedStatute]:
        from .texas_chapter import parse_texas_chapter_html as parse_vaquill_chapter

        vaquill_rows = parse_vaquill_chapter(
            html,
            code_name=code_name,
            code_abbrev=code_abbrev,
            member_name=member_name,
            zip_url=zip_url,
            max_statutes=remaining,
        )
        if vaquill_rows:
            out: List[NormalizedStatute] = []
            for row in vaquill_rows:
                number = str(row.section_number or "")
                if not number or number in seen_sections:
                    continue
                seen_sections.add(number)
                out.append(row)
                if remaining is not None and len(out) >= remaining:
                    break
            if out:
                return out

        text = self._extract_text_from_html(html)
        if len(text) < 280:
            return []

        title_match = re.search(r"\bTITLE\s+([0-9A-Za-z.-]+)\.\s+([^\n]+)", text)
        chapter_match = re.search(r"\bCHAPTER\s+([0-9A-Za-z.-]+)\.\s+([^\n]+)", text)
        title_number = title_match.group(1) if title_match else None
        title_name = _norm_space(title_match.group(2))[:200] if title_match else None
        chapter_number = (
            chapter_match.group(1)
            if chapter_match
            else self._derive_chapter_number_from_member(member_name)
        )
        chapter_name = (
            _norm_space(chapter_match.group(2))[:200] if chapter_match else None
        )

        matches = list(_TEXAS_SECTION_START_RE.finditer(text))
        statutes: List[NormalizedStatute] = []
        for index, match in enumerate(matches):
            if remaining is not None and len(statutes) >= remaining:
                break
            section_number = match.group(1).strip().rstrip(".")
            if not section_number or section_number in seen_sections:
                continue
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section_text = _norm_space(text[start:end])
            if len(section_text) < 120:
                continue
            section_name = _norm_space(match.group(2)).rstrip(".")[:200]
            seen_sections.add(section_number)
            official_member = re.sub(
                rf"^{re.escape(code_abbrev.lower())}\.",
                f"{code_abbrev}.",
                member_name,
                flags=re.IGNORECASE,
            )
            source_url = f"https://statutes.capitol.texas.gov/Docs/{code_abbrev}/htm/{official_member}#{section_number}"
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name,
                    chapter_number=chapter_number,
                    chapter_name=chapter_name,
                    section_number=section_number,
                    section_name=section_name,
                    short_title=section_name,
                    full_text=section_text,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(section_name or section_text),
                    official_cite=f"Tex. {code_name} § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_texas_statutes_html_zip",
                        "zip_url": zip_url,
                        "zip_member": member_name,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def _derive_code_abbrev(self, *, code_name: str, code_url: str) -> str:
        url_match = re.search(
            r"/Docs/([A-Z0-9]{2})/", str(code_url or ""), re.IGNORECASE
        )
        if url_match:
            return url_match.group(1).upper()
        normalized_name = _norm_space(code_name).lower()
        for row in self.get_code_list():
            if _norm_space(row.get("name", "")).lower() == normalized_name:
                value = str(row.get("type") or "").strip().upper()
                if value and value != "REGULATION":
                    return value
        return ""

    def _derive_chapter_number_from_member(self, member_name: str) -> Optional[str]:
        match = re.search(
            r"\.([0-9A-Za-z._-]+)\.html?$",
            str(member_name or ""),
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
        return None

    async def _scrape_texas_admin_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        statutes: List[NormalizedStatute] = []
        seen_urls = set()

        try:
            index_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=40,
            )
            if not index_bytes:
                return []

            index_html = index_bytes.decode("utf-8", errors="replace")
            original_index_html = index_html
            fetch_url = code_url
            migrated_url = _extract_meta_refresh_target(index_html)
            if migrated_url:
                migrated_bytes = await self._fetch_page_content_with_archival_fallback(
                    migrated_url,
                    timeout_seconds=45,
                )
                if migrated_bytes:
                    index_html = migrated_bytes.decode("utf-8", errors="replace")
                    fetch_url = migrated_url

            index_soup = BeautifulSoup(index_html, "html.parser")

            candidate_links: List[tuple[str, str]] = []
            for anchor in index_soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                href_lower = href.lower()
                if (
                    "readtac" not in href_lower
                    and "rules-and-meetings" not in href_lower
                    and "interface=" not in href_lower
                ):
                    continue
                absolute_url = urljoin(fetch_url, href)
                link_text = _norm_space(anchor.get_text(" ", strip=True))
                if not link_text:
                    link_text = "Texas Administrative Code"
                candidate_links.append((link_text, absolute_url))

            if not candidate_links:
                self.logger.info(
                    "Texas Administrative Code landing page exposed no direct rule links; returning no substantive sections"
                )
                return []

            limit = max_statutes if max_statutes is not None else len(candidate_links)
            for idx, (link_text, link_url) in enumerate(
                candidate_links[: max(1, int(limit))], start=1
            ):
                if link_url in seen_urls:
                    continue
                seen_urls.add(link_url)

                payload = await self._fetch_page_content_with_archival_fallback(
                    link_url,
                    timeout_seconds=35,
                )
                if not payload:
                    continue
                html = payload.decode("utf-8", errors="replace")
                full_text = self._extract_text_from_html(html)
                if len(full_text) < 280:
                    continue

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    match = _TAC_SECTION_RE.search(link_text)
                    section_number = match.group(1) if match else f"{idx}"

                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=str(section_number),
                        section_name=link_text[:200],
                        full_text=full_text,
                        source_url=link_url,
                        legal_area="administrative",
                        official_cite=f"Tex. Admin. Code § {section_number}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_texas_admin_code_html",
                            "discovery_method": "official_readtac_rule_links",
                            "skip_hydrate": True,
                        },
                    )
                )

            if not statutes:
                self.logger.info(
                    "Texas Administrative Code bootstrap produced no substantive sections from %s",
                    fetch_url,
                )

            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            return statutes

        except Exception as exc:
            self.logger.error(f"Failed to scrape Texas Administrative Code: {exc}")
            return []

    async def _fetch_section_text(self, section_url: str, fallback_text: str) -> str:
        try:
            payload = await self._fetch_page_content_with_archival_fallback(
                section_url,
                timeout_seconds=25,
            )
            if not payload:
                return fallback_text
            text = self._extract_text_from_html(
                payload.decode("utf-8", errors="replace")
            )
            if len(text) >= 280:
                return text
        except Exception:
            pass

        return fallback_text

    def _extract_text_from_html(
        self,
        html: str,
        max_chars: Optional[int] = None,
    ) -> str:
        value = str(html or "")
        value = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", value)
        value = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", value)
        value = re.sub(r"(?is)<br\s*/?>", "\n", value)
        value = re.sub(r"(?is)</p>", "\n", value)
        value = re.sub(r"(?is)<[^>]+>", " ", value)
        value = unescape(value).replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        text = value.strip()
        if max_chars is not None:
            return text[: max(1, int(max_chars))]
        return text

    def official_html_url(self, code_abbrev: str) -> str:
        abbrev = str(code_abbrev or "").strip().upper()
        return f"{self.get_base_url()}/Docs/{abbrev}/htm/{abbrev}.1.htm"

    def official_zip_url(self, code_abbrev: str) -> str:
        abbrev = str(code_abbrev or "").strip().upper()
        return f"https://tcss.legis.texas.gov/resources/Zips/{abbrev}.htm.zip"

    def official_code_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Texas statute-code catalog."""

        rows: List[Dict[str, Any]] = []
        for abbrev, name in self.OFFICIAL_CODES:
            html_url = self.official_html_url(abbrev)
            zip_url = self.official_zip_url(abbrev)
            rows.append(
                {
                    "canonical_key": f"tx:code-{abbrev.lower()}",
                    "code_abbrev": abbrev,
                    "name": name,
                    "source_url": html_url,
                    "zip_url": zip_url,
                    "acquisition_channels": ["html", "zip"],
                    "mixed_reconciled": True,
                    "source_link_disposition": "official",
                    "text": (
                        f"Texas {name} ({abbrev}) official catalog unit at {html_url} "
                        f"with zip bundle {zip_url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        suffixes = (
            "statutes.capitol.texas.gov",
            "tcss.legis.texas.gov",
            "capitol.texas.gov",
        )
        return any(host == item or host.endswith("." + item) for item in suffixes)

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-texas-official-catalog/1.0",
            "Accept": "text/html,application/json,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }

        def _request() -> bytes:
            try:
                request = urllib.request.Request(url, headers=headers)
                context = ssl.create_default_context()
                with urllib.request.urlopen(
                    request, timeout=timeout, context=context
                ) as response:
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

    def _normalize_code_abbrev(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        known = {abbrev for abbrev, _name in self.OFFICIAL_CODES}
        return text if text in known else ""

    def _parse_html_code_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            soup = None
        else:
            soup = BeautifulSoup(html, "html.parser")
        if soup is not None:
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = re.sub(
                    r"\s+", " ", link.get_text(" ", strip=True) or ""
                ).strip()
                if not href:
                    continue
                absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
                match = self._TX_HTML_CODE_RE.search(absolute)
                if not match:
                    match = self._TX_CODE_LABEL_RE.search(label)
                    if not match:
                        continue
                    abbrev = self._normalize_code_abbrev(match.group("code"))
                else:
                    abbrev = self._normalize_code_abbrev(match.group("code"))
                if not abbrev or abbrev in found:
                    continue
                if self._host_is_official(absolute) or self._TX_HTML_CODE_RE.search(
                    absolute
                ):
                    found[abbrev] = self.official_html_url(abbrev)
        for match in self._TX_HTML_CODE_RE.finditer(
            html.decode("utf-8", errors="replace") if html else ""
        ):
            abbrev = self._normalize_code_abbrev(match.group("code"))
            if abbrev and abbrev not in found:
                found[abbrev] = self.official_html_url(abbrev)
        return found

    def _parse_zip_code_links(self, payload: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not payload:
            return found
        text = payload.decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except Exception:
            data = None
        rows = data.get("StatuteCode") if isinstance(data, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                abbrev = self._normalize_code_abbrev(row.get("code"))
                if not abbrev:
                    continue
                html_path = str(row.get("Html") or "").strip()
                if html_path:
                    found[abbrev] = (
                        "https://tcss.legis.texas.gov/resources/"
                        + html_path.lstrip("/")
                    )
                else:
                    found[abbrev] = self.official_zip_url(abbrev)
        for match in self._TX_ZIP_CODE_RE.finditer(text):
            abbrev = self._normalize_code_abbrev(match.group("code"))
            if abbrev and abbrev not in found:
                found[abbrev] = self.official_zip_url(abbrev)
        return found

    def reconcile_mixed_acquisition(
        self,
        html_codes: Optional[Mapping[str, str]] = None,
        zip_codes: Optional[Mapping[str, str]] = None,
        *,
        extra_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Reconcile Texas HTML index units with official HTML-zip bundles.

        Every statute code is required on both official channels. TAC and
        other non-statute hosts are excluded rather than mixed into the
        statute catalog.
        """

        html_map = {
            str(key).upper(): str(value)
            for key, value in dict(html_codes or {}).items()
        }
        zip_map = {
            str(key).upper(): str(value) for key, value in dict(zip_codes or {}).items()
        }
        units: List[Dict[str, Any]] = []
        excluded: List[Dict[str, str]] = []
        for abbrev, name in self.OFFICIAL_CODES:
            html_url = html_map.get(abbrev) or self.official_html_url(abbrev)
            zip_url = zip_map.get(abbrev) or self.official_zip_url(abbrev)
            if not self._host_is_official(html_url):
                html_url = self.official_html_url(abbrev)
            if not self._host_is_official(zip_url):
                zip_url = self.official_zip_url(abbrev)
            channels = []
            if self._host_is_official(html_url):
                channels.append("html")
            if self._host_is_official(zip_url):
                channels.append("zip")
            units.append(
                {
                    "canonical_key": f"tx:code-{abbrev.lower()}",
                    "code_abbrev": abbrev,
                    "name": name,
                    "source_url": html_url,
                    "zip_url": zip_url,
                    "acquisition_channels": channels,
                    "mixed_reconciled": channels == ["html", "zip"],
                    "source_link_disposition": (
                        "official"
                        if "html" in channels
                        else "repaired_official_leginfo"
                    ),
                    "text": (
                        f"Texas {name} ({abbrev}) official catalog unit at {html_url} "
                        f"with zip bundle {zip_url}"
                    ),
                }
            )
        for item in extra_candidates or ():
            if not isinstance(item, Mapping):
                continue
            label = str(
                item.get("name") or item.get("label") or item.get("code") or ""
            ).strip()
            source_url = str(item.get("source_url") or item.get("href") or "").strip()
            lowered = f"{label} {source_url}".lower()
            if (
                "administrative" in lowered
                or "readtac" in lowered
                or "texreg.sos" in lowered
            ):
                excluded.append(
                    {
                        "code_abbrev": "TAC",
                        "name": label or "Texas Administrative Code",
                        "source_url": source_url,
                        "reason": "excluded_non_statute_mixed_source",
                    }
                )
        reconciled = bool(units) and all(item.get("mixed_reconciled") for item in units)
        result = {
            "units": units,
            "excluded": excluded,
            "reconciled": reconciled,
            "html_count": len(html_map),
            "zip_count": len(zip_map),
            "expected_codes": [abbrev for abbrev, _name in self.OFFICIAL_CODES],
        }
        self.last_mixed_reconciliation = result
        return result

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        downloads_payload: bytes = b"",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official Texas statute code and reconcile mixed paths."""

        del page_url
        html_codes = self._parse_html_code_links(html)
        zip_codes = self._parse_zip_code_links(downloads_payload or html)
        extra = []
        if html:
            text = html.decode("utf-8", errors="replace")
            if "readtac" in text.lower() or "administrative code" in text.lower():
                extra.append(
                    {
                        "name": "Texas Administrative Code",
                        "source_url": "https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC",
                    }
                )
        reconciled = self.reconcile_mixed_acquisition(
            html_codes,
            zip_codes,
            extra_candidates=extra,
        )
        return list(reconciled["units"])

    def fetch_official(self, code: str = "TX"):
        """Acquire the exhaustive official Texas statute-code catalog.

        Mixed HTML index and HTML-zip bundle discovery is fully reconciled
        onto official statutes.capitol.texas.gov and tcss.legis.texas.gov
        URLs. TAC and other non-statute hosts are excluded. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "TX").strip().upper() or "TX"
        if normalized != "TX":
            raise ValueError(f"TexasScraper cannot acquire {normalized}")
        self.last_mixed_reconciliation = {}
        strict_full = self._full_corpus_enabled()
        html = b"" if strict_full else self._official_http_get(self.OFFICIAL_ENTRY_URL)
        downloads = self._official_http_get(self.OFFICIAL_DOWNLOADS_URL)
        manifest: Dict[str, Any] = {}
        if strict_full:
            manifest = self._parse_texas_download_manifest(downloads)
        rows = self.enumerate_official_catalog(
            html,
            page_url=self.OFFICIAL_ENTRY_URL,
            downloads_payload=downloads,
        )
        if len(rows) != self.OFFICIAL_CODE_COUNT:
            raise RuntimeError(
                "texas official catalog enumeration rejected incomplete "
                "mixed-acquisition reacquisition"
            )
        if not all(item.get("mixed_reconciled") for item in rows):
            raise RuntimeError(
                "texas mixed html/zip acquisition is not fully reconciled"
            )
        request_path = (
            self.OFFICIAL_DOWNLOADS_PATH if strict_full else self.OFFICIAL_ENTRY_PATH
        )
        request = (
            f"GET {request_path} HTTP/1.1\nhost: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        reconciliation = dict(getattr(self, "last_mixed_reconciliation", {}) or {})
        excluded = (
            list(manifest.get("excluded_rows") or [])
            if strict_full
            else list(reconciliation.get("excluded") or [])
        )
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
            "excluded": excluded,
            "mixed_reconciled": True,
            "downloads_content_sha256": hashlib.sha256(downloads).hexdigest(),
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = (
            downloads
            if strict_full
            else html
            if html
            else (b"HTTP/1.1 200 OK\n\n" + body)
        )
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows) + len(excluded),
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows) + len(excluded),
            "tx_mixed_reconciled": True,
            "tx_excluded_non_statute": excluded,
            "tx_download_code_count": (
                int(manifest.get("source_code_count") or 0)
                if strict_full
                else len(rows)
            ),
            "tx_downloads_content_sha256": hashlib.sha256(downloads).hexdigest(),
            "tx_zip_urls": [str(row.get("zip_url") or "") for row in rows],
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=request_path,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


# Register the scraper
StateScraperRegistry.register("TX", TexasScraper)
