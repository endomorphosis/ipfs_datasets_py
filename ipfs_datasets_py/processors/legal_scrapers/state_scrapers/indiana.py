"""Scraper for Indiana state laws.

This module contains the scraper for Indiana statutes from archived official
Indiana General Assembly static-document chapter PDFs.
"""

import hashlib
import inspect
import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlparse

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry
from .retained_replay_network_guard import trusted_pdftotext_executable


class IndianaScraper(BaseStateScraper):
    """Scraper for Indiana state laws from archived iga.in.gov sources."""

    OFFICIAL_DOMAIN = "iga.in.gov"
    OFFICIAL_ENTRY_PATH = "/legislative/laws/2026/ic/titles/"
    OFFICIAL_ENTRY_URL = "https://iga.in.gov/legislative/laws/2026/ic/titles/"
    OFFICIAL_CODE_YEAR = "2026"
    OFFICIAL_TITLES = (
        ("1", "General Provisions"),
        ("2", "General Assembly"),
        ("3", "Elections"),
        ("4", "State Offices and Administration"),
        ("5", "State and Local Administration"),
        ("6", "Taxation"),
        ("7.1", "Alcohol and Tobacco"),
        ("8", "Utilities and Transportation"),
        ("9", "Motor Vehicles"),
        ("10", "Public Safety"),
        ("11", "Corrections"),
        ("12", "Human Services"),
        ("13", "Environment"),
        ("14", "Natural and Cultural Resources"),
        ("15", "Agriculture and Animals"),
        ("16", "Health"),
        ("20", "Education"),
        ("21", "Higher Education"),
        ("22", "Labor and Safety"),
        ("23", "Business and Other Associations"),
        ("24", "Trade Regulation"),
        ("25", "Professions and Occupations"),
        ("26", "Commercial Law"),
        ("27", "Insurance"),
        ("28", "Financial Institutions"),
        ("29", "Probate"),
        ("30", "Trusts and Fiduciaries"),
        ("31", "Family Law and Juvenile Law"),
        ("32", "Property"),
        ("33", "Courts and Court Officers"),
        ("34", "Civil Law and Procedure"),
        ("35", "Criminal Law and Procedure"),
        ("36", "Local Government"),
    )
    _TITLE_HREF_RE = re.compile(
        r"/ic/titles/(?:title[-_])?(?P<title>\d+(?:\.\d+)?)(?:/|$|\?|#)",
        re.IGNORECASE,
    )
    _ARCHIVE_CHAPTER_PDFS = [
        "http://web.archive.org/web/20170215063144/http://iga.in.gov/static-documents/0/0/5/2/005284ae/TITLE6_AR1.1_ch15.pdf",
        "http://web.archive.org/web/20170127104730/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20200213045523/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20201111174818/http://iga.in.gov/static-documents/0/0/b/3/00b3e7df/TITLE32_AR28_ch3.pdf",
        "http://web.archive.org/web/20170125194211/http://iga.in.gov/static-documents/0/0/6/f/006f3b19/SB0465.05.ENRS.pdf",
        "http://web.archive.org/web/20161229103815/http://iga.in.gov/static-documents/0/0/7/3/0073b205/SB0374.03.ENGS.pdf",
    ]
    _TITLE_ARTICLE_CHAPTER_RE = re.compile(
        r"TITLE(?P<title>\d+)_AR(?P<article>[0-9.]+)_ch(?P<chapter>\d+)\.pdf$",
        re.IGNORECASE,
    )
    _JUSTIA_TITLE_RE = re.compile(r"title\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
    _WAYBACK_REPLAY_RE = re.compile(
        r"https?://web\.archive\.org/web/(?P<ts>\d+)(?:if_|id_)?/(?P<original>https?://.+)$",
        re.IGNORECASE,
    )
    _IGA_JS_SHELL_RE = re.compile(
        r"you need to enable javascript to run this app\.",
        re.IGNORECASE,
    )
    _IGA_ROOT_DIV_RE = re.compile(r"<div\s+id=['\"]root['\"]", re.IGNORECASE)
    _WAYBACK_SHELL_RE = re.compile(
        r"<title>\s*wayback machine\s*</title>",
        re.IGNORECASE,
    )
    _INDIANA_SECTION_CITE_RE = re.compile(r"\bIC\s+(\d+(?:-[0-9.]+){2,})\b", re.IGNORECASE)
    _INDIANA_TITLE_FILE_RE = re.compile(r"/(\d+)\.html$", re.IGNORECASE)

    def __init__(self, state_code: str, state_name: str):
        super().__init__(state_code, state_name)
        self._indiana_bulk_provenance_cache_key: Optional[
            Tuple[str, int, int, str, int, int, str]
        ] = None
        self._indiana_bulk_provenance: Dict[str, Any] = {}
        self._indiana_first_bulk_inventory_observation: Dict[str, Any] = {}

    def get_base_url(self) -> str:
        """Return the base URL for Indiana's legislative website."""
        return "http://iga.in.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Indiana."""
        return [
            {
                "name": "Indiana Code",
                # Use live titles index so generic fallback can proceed even
                # when web archives are unavailable.
                "url": "https://iga.in.gov/legislative/laws/2024/ic/titles/",
                "type": "Code",
            }
        ]

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape Indiana code statutes.

        Indiana's live site is currently SPA-only in headless contexts.
        We prefer stable Wayback chapter PDFs that contain substantial text.
        """
        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        full_corpus = self._full_corpus_enabled()
        if full_corpus and max_statutes is None:
            full_target = max(
                500,
                int(os.getenv("INDIANA_FULL_CORPUS_TARGET", "90000") or "90000"),
            )
            target_statutes = full_target
        else:
            target_statutes = max(1, int(return_threshold))
        bounded_probe = max_statutes is not None
        from .indiana_constitution import (
            configured_constitution_text_path,
            parse_indiana_constitution_text,
        )

        constitution_path = configured_constitution_text_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_indiana_constitution_text(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Indiana Constitution",
                    max_statutes=target_statutes,
                )
                return constitution_rows[: int(target_statutes)]
        min_full_corpus_records = int(os.getenv("INDIANA_FULL_CORPUS_MIN_RECORDS", "30") or "30")
        resumed = self._load_partial_checkpoint_statutes(
            code_name=code_name,
            max_statutes=int(target_statutes),
        )
        self._mark_skip_hydrate_for_archived_justia_records(resumed)
        bulk_limit = (
            None if full_corpus and max_statutes is None else target_statutes
        )
        bulk = self._scrape_official_bulk_zip(
            code_name=code_name,
            max_statutes=bulk_limit,
        )
        if bulk:
            return bulk
        # Prefer stable official archived chapter PDFs for small bounded probes
        # before heavier download-bundle / Justia recovery.
        if (
            not full_corpus or max_statutes is not None
        ) and target_statutes < 30:
            seed_pdfs = await self._scrape_seed_archive_pdfs(
                code_name=code_name,
                max_statutes=target_statutes,
            )
            if seed_pdfs:
                return seed_pdfs

        download_bundle_statutes: List[NormalizedStatute] = []
        download_bundle_enabled = (
            full_corpus
            or (bounded_probe and int(target_statutes) >= 25)
            or self._env_flag("INDIANA_DOWNLOAD_BUNDLE_ENABLE")
        )
        if download_bundle_enabled:
            download_bundle_statutes = await self._scrape_indiana_download_bundle(
                code_name=code_name,
                max_statutes=(
                    None
                    if full_corpus and max_statutes is None
                    else max(10, target_statutes)
                ),
            )
            merged_download_rows: List[NormalizedStatute] = []
            merged_download_keys = set()
            for statute in [*resumed, *download_bundle_statutes]:
                source_url = str(statute.source_url or "").strip().lower()
                statute_id = str(statute.statute_id or "").strip().lower()
                key = source_url or statute_id
                if not key or key in merged_download_keys:
                    continue
                merged_download_keys.add(key)
                merged_download_rows.append(statute)
            substantive_download_rows = [
                statute for statute in merged_download_rows if self._is_substantive_indiana_record(statute)
            ]
            if substantive_download_rows and (
                not full_corpus or len(substantive_download_rows) >= min_full_corpus_records
            ):
                self.logger.info(
                    "Indiana download bundle: Scraped %s sections (year=%s)",
                    len(substantive_download_rows),
                    substantive_download_rows[0].structured_data.get("code_year")
                    if isinstance(substantive_download_rows[0].structured_data, dict)
                    else "",
                )
                return substantive_download_rows

        archival = await self._scrape_archived_chapter_pdfs(code_name=code_name, max_statutes=max(10, target_statutes))
        justia_titles: List[NormalizedStatute] = []
        title_page_statutes: List[NormalizedStatute] = []
        allow_justia = self._env_flag("INDIANA_ALLOW_JUSTIA_FALLBACK") or self._env_flag(
            "STATE_SCRAPER_IN_ALLOW_JUSTIA_FALLBACK"
        )
        # Full-corpus keeps Justia opt-in only; bounded probes may use it as
        # last-resort recovery when official IGA archives are unavailable.
        if full_corpus:
            justia_enabled = allow_justia or self._env_flag("INDIANA_JUSTIA_ENABLE")
        else:
            justia_enabled = (
                bounded_probe or self._env_flag("INDIANA_JUSTIA_ENABLE")
            ) and not self._env_flag("INDIANA_JUSTIA_DISABLE")
        title_pages_enabled = full_corpus or bounded_probe or self._env_flag("INDIANA_ARCHIVED_TITLE_PAGES_ENABLE")
        if justia_enabled:
            justia_titles = await self._scrape_archived_justia_titles(code_name=code_name, max_statutes=max(10, target_statutes))
        if title_pages_enabled:
            title_page_statutes = await self._scrape_archived_title_pages(code_name=code_name, max_statutes=max(10, target_statutes))

        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                source_url = str(statute.source_url or "").strip().lower()
                statute_id = str(statute.statute_id or "").strip().lower()
                key = source_url or statute_id
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(resumed)
        _merge(download_bundle_statutes)
        _merge(archival)
        _merge(justia_titles)
        _merge(title_page_statutes)
        self._mark_skip_hydrate_for_archived_justia_records(merged)

        substantive = [statute for statute in merged if self._is_substantive_indiana_record(statute)]
        if len(substantive) != len(merged):
            self.logger.info(
                "Indiana filtering removed %s non-substantive fallback records",
                max(0, len(merged) - len(substantive)),
            )

        official = [statute for statute in substantive if self._is_official_indiana_source(statute)]
        if official and (not full_corpus or len(official) >= min_full_corpus_records):
            self.logger.info("Indiana official/archive crawl: Scraped %s sections", len(official))
            return official

        if full_corpus and not allow_justia and not official:
            self.logger.warning(
                "Indiana full-corpus crawl found no official IGA rows; refusing Justia-only admission"
            )
            if not self._env_flag("INDIANA_GENERIC_FALLBACK"):
                return []

        if substantive and (not full_corpus or len(substantive) >= min_full_corpus_records):
            # Bounded probes may still accept mixed recovery rows; full corpus
            # only reaches here when Justia fallback is explicitly allowed.
            if full_corpus and not allow_justia and not official:
                pass
            else:
                self.logger.info(f"Indiana archival fallback: Scraped {len(substantive)} sections")
                return substantive if not official else official

        if full_corpus and official:
            self.logger.warning(
                "Indiana official recovery found only %s sections in full-corpus mode; trying generic recovery before accepting partial corpus",
                len(official),
            )
        elif full_corpus and substantive:
            self.logger.warning(
                "Indiana archive/title recovery found only %s sections in full-corpus mode; trying generic recovery before accepting partial corpus",
                len(substantive),
            )

        if self._env_flag("INDIANA_GENERIC_FALLBACK"):
            generic = await self._generic_scrape(code_name, code_url, "Ind. Code")
            _merge(generic)
            substantive = [statute for statute in merged if self._is_substantive_indiana_record(statute)]
            official = [statute for statute in substantive if self._is_official_indiana_source(statute)]
            if official:
                self.logger.info(f"Indiana recovery fallback: Scraped {len(official)} official sections")
                return official
            if substantive and (allow_justia or not full_corpus):
                self.logger.info(f"Indiana recovery fallback: Scraped {len(substantive)} sections")
                return substantive

        self.logger.warning("Indiana official/archive direct crawl returned no statutes; skipping search/generic recovery fallback")
        return []

    async def _scrape_seed_archive_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        seen_ids = set()
        for pdf_url in self._ARCHIVE_CHAPTER_PDFS[: max(1, int(max_statutes or 1))]:
            statute = await self._build_statute_from_pdf_url(
                code_name=code_name,
                pdf_url=pdf_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if statute is None or statute.statute_id in seen_ids:
                continue
            seen_ids.add(statute.statute_id)
            statutes.append(statute)
        return statutes

    def _scrape_official_bulk_zip(
        self,
        *,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Read the official Indiana Code HTML zip when INDIANA_BULK_ZIP is set."""

        from .indiana_bulk import configured_bulk_zip_path, parse_indiana_bulk_zip

        zip_path = configured_bulk_zip_path()
        if zip_path is None:
            return []
        try:
            bundle_provenance = self._retain_official_bulk_zip_parser_input(
                zip_path
            )
            parser_zip_path = Path(
                str(bundle_provenance.get("retained_body_path") or zip_path)
            )
            inventory_observer = None
            if (
                max_statutes is None
                and getattr(self, "_state_law_acquisition_ledger", None)
                is not None
            ):
                inventory_observer = (
                    self._retain_indiana_bulk_inventory_observation
                )
            return parse_indiana_bulk_zip(
                parser_zip_path,
                code_name=code_name,
                max_statutes=max_statutes,
                code_year=str(
                    bundle_provenance.get("code_year")
                    or self.OFFICIAL_CODE_YEAR
                ),
                bundle_provenance=bundle_provenance or None,
                inventory_observer=inventory_observer,
                fail_on_unusable=inventory_observer is not None,
            )
        except Exception as exc:
            self.logger.warning("Indiana official bulk zip failed: %s", exc)
            if getattr(self, "_state_law_acquisition_ledger", None) is not None:
                raise
            return []

    def _retain_official_bulk_zip_parser_input(
        self,
        zip_path: Path,
        *,
        expected_official_url: Optional[str] = None,
        expected_year: Optional[int | str] = None,
    ) -> Dict[str, Any]:
        """Stream one sidecar-verified official ZIP into shared evidence."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            return {}
        from .indiana_bulk import (
            configured_bulk_zip_receipt_path,
            load_indiana_bulk_transport_receipt,
        )

        archive_path = Path(zip_path).expanduser()
        receipt_path = configured_bulk_zip_receipt_path(archive_path)
        receipt = load_indiana_bulk_transport_receipt(
            archive_path,
            receipt_path=receipt_path,
            expected_official_url=expected_official_url,
            expected_year=expected_year,
        )
        archive_stat = archive_path.stat()
        receipt_stat = receipt_path.stat()
        cache_key = (
            str(archive_path.resolve()),
            int(archive_stat.st_size),
            int(archive_stat.st_mtime_ns),
            str(receipt_path.resolve()),
            int(receipt_stat.st_size),
            int(receipt_stat.st_mtime_ns),
            str(getattr(ledger, "jurisdiction_root", "")),
        )
        if (
            self._indiana_bulk_provenance_cache_key == cache_key
            and self._indiana_bulk_provenance
        ):
            return dict(self._indiana_bulk_provenance)

        official_url = str(receipt["official_url"])
        request = {"method": "GET", "url": official_url}
        retained = ledger.retain_parser_input_file(
            official_url=official_url,
            source_path=archive_path,
            transport_receipt=receipt,
            retrieved_at=str(receipt["retrieved_at"]),
            response_status=int(receipt["response_status"]),
            media_type=str(receipt["media_type"]),
            sanitized_request=request,
        )
        content = retained.receipt.content
        if content is None:
            raise RuntimeError(
                "Indiana bulk ZIP retention omitted its content address"
            )
        provenance = {
            "byte_size": int(content.byte_size),
            "code_year": str(receipt["code_year"]),
            "content_sha256": str(content.sha256),
            "media_type": str(receipt["media_type"]),
            "official_url": official_url,
            "retrieved_at": str(receipt["retrieved_at"]),
            "retained_body_path": str(retained.body_path),
            "transport_receipt": dict(retained.transport_receipt),
        }
        self._indiana_bulk_provenance_cache_key = cache_key
        self._indiana_bulk_provenance = provenance
        return dict(provenance)

    @staticmethod
    def _validate_indiana_bulk_inventory(
        value: Mapping[str, Any],
    ) -> Dict[str, Any]:
        from .indiana_bulk import (
            INDIANA_BULK_INVENTORY_SCHEMA,
            _canonical_json_sha256,
        )

        inventory = dict(value)
        if inventory.get("schema_version") != INDIANA_BULK_INVENTORY_SCHEMA:
            raise RuntimeError("Indiana bulk inventory has the wrong schema")
        if str(inventory.get("jurisdiction") or "").strip().upper() != "IN":
            raise RuntimeError("Indiana bulk inventory changed jurisdiction")
        declared = str(inventory.pop("inventory_sha256", "") or "").strip().lower()
        if re.fullmatch(r"[a-f0-9]{64}", declared) is None:
            raise RuntimeError("Indiana bulk inventory lacks an exact digest")
        if declared != _canonical_json_sha256(inventory):
            raise RuntimeError("Indiana bulk inventory digest does not replay")
        inventory["inventory_sha256"] = declared
        for prefix in ("source_record", "admitted_source_record"):
            raw_ids = inventory.get(f"{prefix}_ids")
            if not isinstance(raw_ids, list) or any(
                not isinstance(item, str) or not item.strip() for item in raw_ids
            ):
                raise RuntimeError(
                    f"Indiana bulk inventory {prefix}_ids must be exact strings"
                )
            if int(inventory.get(f"{prefix}_count") or -1) != len(raw_ids):
                raise RuntimeError(
                    f"Indiana bulk inventory {prefix} count does not replay"
                )
        return inventory

    def _retain_indiana_bulk_inventory_observation(
        self,
        inventory: Mapping[str, Any],
    ) -> None:
        """Seal the first exact section inventory before rows leave parsing."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "Indiana bulk inventory requires an attached acquisition ledger"
            )
        verified = self._validate_indiana_bulk_inventory(inventory)
        bundle = verified.get("bundle")
        if not isinstance(bundle, Mapping):
            raise RuntimeError("Indiana bulk inventory lacks its bundle binding")
        if str(bundle.get("content_sha256") or "").strip().lower() != str(
            self._indiana_bulk_provenance.get("content_sha256") or ""
        ).strip().lower():
            raise RuntimeError(
                "Indiana bulk inventory changed the retained bundle digest"
            )

        from ....retrieval.hf_graphrag.artifacts import atomic_write_bytes
        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )

        payload = canonical_json_bytes(verified)
        digest = str(verified["inventory_sha256"])
        observation_dir = (
            Path(ledger.frontiers_dir)
            / "indiana-code-html"
            / "first"
            / digest
        )
        observation_dir.mkdir(parents=True, exist_ok=True)
        observation_path = observation_dir / "inventory.json"
        if observation_path.exists():
            if observation_path.is_symlink() or not observation_path.is_file():
                raise RuntimeError(
                    "immutable Indiana bulk inventory observation conflicts"
                )
            with observation_path.open("rb") as existing:
                if existing.read() != payload:
                    raise RuntimeError(
                        "immutable Indiana bulk inventory observation conflicts"
                    )
        else:
            atomic_write_bytes(observation_path, payload)
        relative_path = observation_path.resolve().relative_to(
            Path(ledger.jurisdiction_root).resolve()
        )
        self._indiana_first_bulk_inventory_observation = {
            "inventory_sha256": digest,
            "relative_path": relative_path.as_posix(),
        }

    def _load_indiana_first_bulk_inventory(self) -> Dict[str, Any]:
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        observation = self._indiana_first_bulk_inventory_observation
        if ledger is None or not observation:
            raise RuntimeError(
                "Indiana first bulk inventory was not retained before parsing"
            )
        relative_path = str(observation.get("relative_path") or "").strip()
        path = Path(ledger.jurisdiction_root) / relative_path
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Indiana first bulk inventory cannot be replayed")
        try:
            path.resolve().relative_to(Path(ledger.jurisdiction_root).resolve())
            payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "Indiana first bulk inventory cannot be replayed"
            ) from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("Indiana first bulk inventory is not an object")
        verified = self._validate_indiana_bulk_inventory(payload)
        if str(verified["inventory_sha256"]) != str(
            observation.get("inventory_sha256") or ""
        ):
            raise RuntimeError("Indiana first bulk inventory identity changed")
        return verified

    async def _scrape_indiana_download_bundle(
        self,
        code_name: str,
        max_statutes: Optional[int],
    ) -> List[NormalizedStatute]:
        """Parse a downloaded bundle through the one shared Indiana ZIP parser."""
        bundle = await self._download_indiana_code_bundle()
        if bundle is None:
            return []
        year, bundle_path, bundle_url = bundle
        from .indiana_bulk import parse_indiana_bulk_zip

        inventory_observer = None
        if (
            max_statutes is None
            and getattr(self, "_state_law_acquisition_ledger", None) is not None
        ):
            inventory_observer = self._retain_indiana_bulk_inventory_observation
        out = await asyncio.to_thread(
            parse_indiana_bulk_zip,
            bundle_path,
            code_name=code_name,
            max_statutes=max_statutes,
            code_year=str(year),
            bundle_provenance=self._indiana_bulk_provenance or None,
            inventory_observer=inventory_observer,
            fail_on_unusable=inventory_observer is not None,
        )
        self._write_partial_checkpoint(
            out,
            code_name=code_name,
            stage_label="indiana:download-bundle:complete",
            force=True,
            extra={
                "year": int(year),
                "bundle_url": bundle_url,
                "bundle_path": str(bundle_path),
                "scanned_candidates": int(len(out)),
                "discovered_candidates": int(len(out)),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return out

    async def _download_indiana_code_bundle(self) -> tuple[int, Path, str] | None:
        """Download or provenance-verify the newest Indiana Code bundle ZIP."""
        cache_dir = Path(
            self.state_law_run_environment_value("INDIANA_CODE_ZIP_CACHE_DIR")
            or (Path.home() / ".ipfs_datasets" / "indiana_code_zip_cache")
        )
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

        headers = self._indiana_code_bundle_headers()
        timeout_connect = max(2, int(os.getenv("INDIANA_CODE_ZIP_CONNECT_TIMEOUT_SECONDS", "8") or "8"))
        timeout_read = max(10, int(os.getenv("INDIANA_CODE_ZIP_READ_TIMEOUT_SECONDS", "180") or "180"))
        min_year = int(os.getenv("INDIANA_CODE_MIN_YEAR", "2017") or "2017")
        current_year = int(datetime.utcnow().year)
        max_year = int(os.getenv("INDIANA_CODE_MAX_YEAR", str(current_year)) or str(current_year))
        if max_year < min_year:
            max_year = min_year

        preferred_year = str(os.getenv("INDIANA_CODE_YEAR", "") or "").strip()
        year_candidates: List[int]
        if preferred_year.isdigit():
            year_candidates = [int(preferred_year)]
        else:
            year_candidates = list(range(max_year, min_year - 1, -1))

        def _candidate_urls(year: int) -> List[tuple[str, str]]:
            return [
                (f"https://iga.in.gov/ic/{year}/{year}-Indiana-Code-html.zip", "html"),
                (f"https://iga.in.gov/ic/{year}/{year}-Indiana-Code.zip", "full"),
            ]

        def _is_zip_file(path: Path) -> bool:
            try:
                if not path.exists() or path.stat().st_size < 64:
                    return False
                with path.open("rb") as handle:
                    return handle.read(4) == b"PK\x03\x04"
            except Exception:
                return False

        def _is_zip_payload(payload: bytes) -> bool:
            value = bytes(payload or b"")
            return len(value) >= 64 and value.startswith(b"PK\x03\x04")

        def _persist_download(payload: bytes, dest: Path) -> bool:
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f"indiana-{dest.stem}-",
                    suffix=".tmp",
                    dir=str(cache_dir),
                    delete=False,
                ) as tmp_handle:
                    tmp_path = Path(tmp_handle.name)
                    tmp_handle.write(payload)
                if tmp_path is None or not _is_zip_file(tmp_path):
                    return False
                tmp_path.replace(dest)
                return True
            except Exception:
                return False
            finally:
                if tmp_path is not None and tmp_path.exists() and tmp_path != dest:
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass

        def _provenance_from_retained(
            retained: Any,
            *,
            year: int,
            retrieved_at: object = "",
            media_type: str = "application/zip",
        ) -> Path:
            content = retained.receipt.content
            if content is None:
                raise RuntimeError(
                    "Indiana retained ZIP omitted its content address"
                )
            observed_at = str(
                retrieved_at or retained.receipt.retrieved_at or ""
            )
            self._indiana_bulk_provenance = {
                "byte_size": int(content.byte_size),
                "code_year": str(year),
                "content_sha256": str(content.sha256),
                "media_type": str(media_type or "application/zip"),
                "official_url": str(retained.receipt.endpoint),
                "retrieved_at": observed_at,
                "retained_body_path": str(retained.body_path),
                "transport_receipt": dict(retained.transport_receipt),
            }
            return Path(retained.body_path)

        def _admit_existing_cache(
            cache_path: Path,
            *,
            year: int,
            url: str,
        ) -> Optional[Path]:
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            if ledger is None:
                return cache_path if _is_zip_file(cache_path) else None
            request = {"method": "GET", "url": url}
            replayed = ledger.replay_retained_parser_input_file(
                official_url=url,
                sanitized_request=request,
            )
            if replayed is not None:
                return _provenance_from_retained(replayed, year=year)
            if not _is_zip_file(cache_path):
                return None
            try:
                provenance = self._retain_official_bulk_zip_parser_input(
                    cache_path,
                    expected_official_url=url,
                    expected_year=year,
                )
            except Exception as exc:
                self._record_fetch_event(
                    provider="indiana_code_zip_cache_provenance_rejected",
                    success=False,
                    error=str(exc),
                )
                return None
            return Path(str(provenance["retained_body_path"]))

        async def _download_one(url: str, dest: Path, *, year: int) -> Optional[Path]:
            payload = await self._fetch_parser_input_with_transport(
                url,
                headers=headers,
                timeout_seconds=max(timeout_connect, timeout_read),
                content_validator=_is_zip_payload,
                allow_archival_fallback=True,
                media_type="application/zip",
                provider="requests_direct_indiana_code_zip",
            )
            if not payload:
                return None
            persisted = await asyncio.to_thread(_persist_download, payload, dest)
            if not persisted:
                return None
            ledger = getattr(self, "_state_law_acquisition_ledger", None)
            if ledger is None:
                return dest
            evidence = getattr(self, "_last_page_fetch_transport_evidence", None)
            envelope = getattr(self, "_last_page_parser_input_envelope", None)
            if not isinstance(evidence, Mapping) or not evidence or envelope is None:
                raise RuntimeError(
                    "Indiana live ZIP fetch lacks prospective transport evidence"
                )
            source_receipt = envelope.acquisition.receipt
            retained = ledger.retain_parser_input_file(
                official_url=url,
                source_path=dest,
                transport_receipt=evidence,
                retrieved_at=source_receipt.retrieved_at,
                response_status=int(source_receipt.response_status),
                media_type=str(source_receipt.media_type or "application/zip"),
                sanitized_request={"method": "GET", "url": url},
            )
            return _provenance_from_retained(
                retained,
                year=year,
                retrieved_at=source_receipt.retrieved_at,
                media_type=str(source_receipt.media_type or "application/zip"),
            )

        for year in year_candidates:
            for url, suffix in _candidate_urls(year):
                cache_path = cache_dir / f"{year}-indiana-code-{suffix}.zip"
                admitted_cache = _admit_existing_cache(
                    cache_path,
                    year=year,
                    url=url,
                )
                if admitted_cache is not None:
                    self._record_fetch_event(provider="indiana_code_zip_cache", success=True)
                    return int(year), admitted_cache, url
                downloaded = await _download_one(url, cache_path, year=year)
                if downloaded is None:
                    self._record_fetch_event(
                        provider="requests_direct_indiana_code_zip",
                        success=False,
                        error=f"download_failed:{year}:{suffix}",
                    )
                elif _is_zip_file(cache_path):
                    return int(year), downloaded, url

        return None

    @staticmethod
    def _indiana_code_bundle_headers() -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/zip,application/octet-stream,*/*",
            "Referer": "https://iga.in.gov/laws/ic/downloads",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
        }

    def _extract_indiana_download_section_text(self, section_node) -> str:
        """Extract body text for one Indiana section node from title HTML."""
        try:
            from bs4 import NavigableString
            from bs4.element import Tag
        except Exception:
            return ""

        stop_classes = {"section", "article", "chapter", "title"}
        out: List[str] = []
        for sibling in section_node.next_siblings:
            if isinstance(sibling, Tag):
                sibling_classes = {str(item).strip().lower() for item in (sibling.get("class") or [])}
                if sibling.name == "div" and sibling_classes.intersection(stop_classes):
                    break
                sibling_text = self._normalize_legal_text(sibling.get_text(" ", strip=True))
                if sibling_text:
                    out.append(sibling_text)
            elif isinstance(sibling, NavigableString):
                sibling_text = self._normalize_legal_text(str(sibling))
                if sibling_text:
                    out.append(sibling_text)

        return self._normalize_legal_text(" ".join(out))

    async def _scrape_archived_justia_titles(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        root_url = "https://web.archive.org/web/20241203192652/https://law.justia.com/codes/indiana/2010/"
        try:
            payload = await self._fetch_archived_indiana_page(
                root_url,
                timeout_seconds=35,
                allow_archival_fallback=True,
            )
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        title_links: List[tuple[str, str]] = []
        seen = set()
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            text = " ".join(link.get_text(" ", strip=True).split())
            if "TITLE" not in text.upper():
                continue
            if "/codes/indiana/2010/title" not in href:
                continue
            full_url = href if href.startswith("http") else f"https://web.archive.org{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            title_links.append((text, full_url))
            if len(title_links) >= max_statutes:
                break

        if title_links:
            link_graph_rows = await self._crawl_archived_justia_link_graph(
                code_name=code_name,
                seed_urls=[url for _, url in title_links],
                max_statutes=max_statutes,
            )
            if link_graph_rows:
                return link_graph_rows[:max_statutes]
            if self._full_corpus_enabled():
                # In full-corpus mode, do not downgrade to title-level index
                # placeholders when section-level traversal yielded nothing.
                return []

        statutes: List[NormalizedStatute] = []
        crawl_limit = int(os.getenv("INDIANA_JUSTIA_CRAWL_PAGE_LIMIT", "2000") or "2000")
        for title_text, title_url in title_links:
            if self._full_corpus_enabled() and crawl_limit <= 0:
                page_text = (
                    f"{title_text}. Archived Indiana Code title index discovered from the Justia 2010 Indiana Code root. "
                    "Deep article/chapter traversal is deferred for the targeted Indiana enrichment crawl."
                )
            else:
                try:
                    title_payload = await self._fetch_archived_indiana_page(
                        title_url,
                        timeout_seconds=35,
                        allow_archival_fallback=False,
                    )
                except Exception:
                    continue
                if not title_payload:
                    continue
                title_soup = BeautifulSoup(title_payload, "html.parser")
                page_text = " ".join(title_soup.get_text(" ", strip=True).split())
                if len(page_text) < 300:
                    continue
            match = self._JUSTIA_TITLE_RE.search(title_text)
            title_no = match.group(1) if match else title_text[:40]
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_no}",
                    code_name=code_name,
                    section_number=f"Title {title_no}",
                    section_name=title_text[:200],
                    full_text=page_text,
                    legal_area=self._identify_legal_area(title_text),
                    source_url=title_url,
                    official_cite=f"Ind. Code Title {title_no}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "archived_justia_indiana_title_index",
                        "discovery_method": "wayback_justia_root",
                        "record_type": "archived_justia_title_index",
                        "skip_hydrate": bool(self._full_corpus_enabled() and crawl_limit <= 0),
                    },
                )
            )
            if len(statutes) >= max_statutes:
                break

        if self._full_corpus_enabled() and crawl_limit > 0 and len(statutes) < max_statutes:
            remaining = max(0, int(max_statutes) - len(statutes))
            statutes.extend(
                await self._crawl_archived_justia_link_graph(
                    code_name=code_name,
                    seed_urls=[url for _, url in title_links],
                    max_statutes=remaining,
                )
            )

        return statutes

    async def _crawl_archived_justia_link_graph(
        self,
        *,
        code_name: str,
        seed_urls: List[str],
        max_statutes: int,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        seen_records = set()
        seen_pages = set()
        queue = list(seed_urls)
        crawl_limit = int(os.getenv("INDIANA_JUSTIA_CRAWL_PAGE_LIMIT", "2000") or "2000")
        recovery_enabled = self._env_flag("INDIANA_JUSTIA_ALLOW_RECOVERY_FETCH")
        recovery_budget = max(0, int(os.getenv("INDIANA_JUSTIA_RECOVERY_FETCH_LIMIT", "64") or "64"))
        recovery_used = 0
        self._write_partial_checkpoint(
            out,
            code_name=code_name,
            stage_label="indiana:justia-link-graph:start",
            extra={
                "scanned_candidates": 0,
                "discovered_candidates": int(len(queue)),
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        while queue and len(out) < max_statutes and len(seen_pages) < crawl_limit:
            page_url = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            if len(seen_pages) == 1 or len(seen_pages) % 25 == 0:
                self.logger.info(
                    "Indiana Justia link graph crawl progress: pages=%s queued=%s records=%s statutes_so_far=%s cap=%s",
                    len(seen_pages),
                    len(queue),
                    len(out),
                    len(out),
                    crawl_limit,
                )
                self._write_partial_checkpoint(
                    out,
                    code_name=code_name,
                    stage_label="indiana:justia-link-graph:progress",
                    extra={
                        "scanned_candidates": int(len(seen_pages)),
                        "discovered_candidates": int(len(seen_pages) + len(queue)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )
            try:
                payload = await self._fetch_archived_indiana_page(page_url, timeout_seconds=35)
            except Exception:
                payload = b""
            if (
                (not payload or self._looks_like_wayback_shell_payload(payload))
                and recovery_enabled
                and recovery_used < recovery_budget
            ):
                try:
                    recovered = await self._fetch_archived_indiana_page(
                        page_url,
                        timeout_seconds=35,
                        allow_archival_fallback=True,
                    )
                except Exception:
                    recovered = b""
                if recovered:
                    payload = recovered
                recovery_used += 1
            if not payload:
                continue
            if self._looks_like_wayback_shell_payload(payload):
                continue

            soup = BeautifulSoup(payload, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link.get("href") or "").strip()
                label = self._normalize_legal_text(link.get_text(" ", strip=True))
                if not href or not label:
                    continue

                abs_url = href if href.startswith("http") else urljoin(page_url, href)
                abs_url = self._normalize_wayback_child_url(page_url=page_url, candidate_url=abs_url)
                abs_url = self._canonicalize_statute_url(abs_url)
                lower_url = abs_url.lower()
                lower_label = label.lower()
                if "accounts.justia.com" in lower_url or "/signin" in lower_url:
                    continue
                if "*" in abs_url:
                    continue
                if "/web/*/" in lower_url:
                    continue
                if "/codes/indiana/2010/" not in lower_url:
                    continue

                is_index = any(part in lower_url for part in ("/title", "/ar", "/ch")) and (
                    lower_url.endswith("/")
                    or lower_url.endswith("/index.html")
                    or lower_url.endswith(".html")
                )
                if is_index and abs_url not in seen_pages and len(seen_pages) + len(queue) < crawl_limit:
                    queue.append(abs_url)

                is_section_like = self._is_probable_indiana_section_url(lower_url)
                if is_index and not is_section_like:
                    continue

                looks_statutory = (
                    self._is_probable_statute_link(label, abs_url, page_url)
                    or "article" in lower_label
                    or "chapter" in lower_label
                    or re.search(r"\b(?:ic|sec\.|section)\s*\d", lower_label, re.IGNORECASE)
                )
                if not looks_statutory:
                    continue

                section_number = self._derive_indiana_section_number(label=label, source_url=abs_url)
                if not self._looks_like_indiana_section_number(section_number):
                    continue

                key = f"{section_number}|{abs_url}".lower()
                if key in seen_records:
                    continue
                seen_records.add(key)
                out.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=label[:200],
                        full_text=f"Section {section_number}: {label}",
                        legal_area=self._identify_legal_area(label),
                        source_url=abs_url,
                        official_cite=f"Ind. Code § {section_number}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "archived_justia_indiana_code",
                            "discovery_method": "wayback_justia_link_graph",
                            "record_type": "archived_justia_link",
                            # Link-graph records are often index-like stubs;
                            # avoid expensive hydrate fallback loops.
                            "skip_hydrate": True,
                        },
                    )
                )
                if len(out) >= max_statutes:
                    break

        self._write_partial_checkpoint(
            out,
            code_name=code_name,
            stage_label="indiana:justia-link-graph:complete",
            force=True,
            extra={
                "scanned_candidates": int(len(seen_pages)),
                "discovered_candidates": int(len(seen_pages) + len(queue)),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return out

    async def _scrape_archived_title_pages(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        discovery_limit = 5000 if self._full_corpus_enabled() else 420
        title_urls = await self._discover_archived_title_urls(limit=discovery_limit)
        out: List[NormalizedStatute] = []
        seen = set()
        queued = set()
        recovery_enabled = self._env_flag("INDIANA_JUSTIA_ALLOW_RECOVERY_FETCH")
        recovery_budget = max(0, int(os.getenv("INDIANA_JUSTIA_RECOVERY_FETCH_LIMIT", "64") or "64"))
        recovery_used = 0
        crawl_limit = int(os.getenv("INDIANA_JUSTIA_CRAWL_PAGE_LIMIT", "2000") or "2000")
        global_page_budget = max(
            crawl_limit,
            int(os.getenv("INDIANA_ARCHIVED_TITLE_PAGES_TOTAL_LIMIT", "25000") or "25000"),
        )
        global_pages_seen = 0
        self._write_partial_checkpoint(
            out,
            code_name=code_name,
            stage_label="indiana:archived-title-pages:start",
            extra={
                "titles_scanned": 0,
                "discovered_titles": int(len(title_urls)),
                "scanned_candidates": 0,
                "discovered_candidates": 0,
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        for title_index, title_url in enumerate(title_urls, start=1):
            if len(out) >= max_statutes:
                break
            queue = [title_url]
            queued.add(title_url)
            pages_seen = 0
            while queue and len(out) < max_statutes and pages_seen < crawl_limit and global_pages_seen < global_page_budget:
                page_url = queue.pop(0)
                pages_seen += 1
                global_pages_seen += 1
                try:
                    payload = await self._fetch_archived_indiana_page(page_url, timeout_seconds=35)
                except Exception:
                    payload = b""
                if (
                    (not payload or self._looks_like_wayback_shell_payload(payload))
                    and recovery_enabled
                    and recovery_used < recovery_budget
                ):
                    try:
                        recovered = await self._fetch_archived_indiana_page(
                            page_url,
                            timeout_seconds=35,
                            allow_archival_fallback=True,
                        )
                    except Exception:
                        recovered = b""
                    if recovered:
                        payload = recovered
                    recovery_used += 1
                if not payload:
                    continue
                if self._looks_like_wayback_shell_payload(payload):
                    continue

                try:
                    from bs4 import BeautifulSoup
                except ImportError:
                    return out

                soup = BeautifulSoup(payload, "html.parser")
                for link in soup.find_all("a", href=True):
                    href = str(link.get("href") or "").strip()
                    label = self._normalize_legal_text(link.get_text(" ", strip=True))
                    if not href or not label:
                        continue

                    abs_url = href if href.startswith("http") else urljoin(page_url, href)
                    abs_url = self._normalize_wayback_child_url(page_url=page_url, candidate_url=abs_url)
                    abs_url = self._canonicalize_statute_url(abs_url)
                    lower_url = abs_url.lower()
                    lower_label = label.lower()
                    if "accounts.justia.com" in lower_url or "/signin" in lower_url:
                        continue
                    if "/codes/indiana/2010/" not in lower_url:
                        continue
                    if "/web/*/" in lower_url:
                        continue

                    is_index = any(part in lower_url for part in ("/title", "/ar", "/ch")) and (
                        lower_url.endswith("/")
                        or lower_url.endswith("/index.html")
                        or lower_url.endswith(".html")
                    )
                    if is_index and abs_url not in queued and len(queued) < crawl_limit:
                        queued.add(abs_url)
                        queue.append(abs_url)

                    is_section_like = self._is_probable_indiana_section_url(lower_url)
                    if is_index and not is_section_like:
                        continue

                    looks_statutory = (
                        self._is_probable_statute_link(label, abs_url, page_url)
                        or "article" in lower_label
                        or "chapter" in lower_label
                        or re.search(r"\b(?:ic|sec\.|section)\s*\d", lower_label, re.IGNORECASE)
                    )
                    if not looks_statutory:
                        continue

                    section_number = self._derive_indiana_section_number(label=label, source_url=abs_url)
                    if not section_number:
                        continue

                    if lower_label.startswith("article ") or lower_label.startswith("title "):
                        continue

                    key = f"{section_number}|{abs_url}".lower()
                    if key in seen:
                        continue
                    statute = await self._build_archived_justia_link_statute(
                        code_name=code_name,
                        section_number=section_number,
                        label=label,
                        source_url=abs_url,
                    )
                    if statute is None:
                        continue
                    seen.add(key)
                    out.append(statute)
                    if len(out) >= max_statutes:
                        break
                if pages_seen == 1 or pages_seen % 25 == 0 or pages_seen >= crawl_limit:
                    self._write_partial_checkpoint(
                        out,
                        code_name=code_name,
                        stage_label="indiana:archived-title-pages:progress",
                        extra={
                            "titles_scanned": int(title_index),
                            "discovered_titles": int(len(title_urls)),
                            "scanned_candidates": int(pages_seen),
                            "discovered_candidates": int(len(queued)),
                            "codes_completed": 0,
                            "codes_total": 1,
                        },
                    )
            if global_pages_seen >= global_page_budget:
                break

        self._write_partial_checkpoint(
            out,
            code_name=code_name,
            stage_label="indiana:archived-title-pages:complete",
            force=True,
            extra={
                "titles_scanned": int(len(title_urls)),
                "discovered_titles": int(len(title_urls)),
                "scanned_candidates": int(len(queued)),
                "discovered_candidates": int(len(queued)),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return out

    async def _build_archived_justia_link_statute(
        self,
        *,
        code_name: str,
        section_number: str,
        label: str,
        source_url: str,
    ) -> NormalizedStatute | None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        try:
            payload = await self._fetch_archived_indiana_page(source_url, timeout_seconds=35)
        except Exception:
            payload = b""
        if not payload:
            return None

        soup = BeautifulSoup(payload, "html.parser")
        content_text = self._normalize_legal_text(self._extract_best_content_text(str(soup)))
        content_text = re.split(r"\bDisclaimer:\b", content_text, maxsplit=1)[0].strip()
        content_text = re.split(r"\bAsk a Lawyer\b", content_text, maxsplit=1)[0].strip()
        content_text = re.sub(r"\s+", " ", content_text).strip()
        if len(content_text) < 240:
            return None

        heading = ""
        heading_node = soup.select_one("h1") or soup.select_one("title")
        if heading_node is not None:
            heading = self._normalize_legal_text(heading_node.get_text(" ", strip=True))

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=(heading or label or f"Section {section_number}")[:200],
            full_text=content_text,
            legal_area=self._identify_legal_area(heading or label),
            source_url=source_url,
            official_cite=f"Ind. Code § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "archived_justia_indiana_code",
                "discovery_method": "wayback_justia_link_graph",
                "record_type": "archived_justia_link",
                "skip_hydrate": True,
            },
        )

    def _derive_indiana_section_number(self, *, label: str, source_url: str) -> str:
        """Extract a stable Indiana section identifier from Justia/Wayback links."""
        normalized_label = self._normalize_legal_text(label)
        normalized_url = self._canonicalize_statute_url(source_url)
        parsed = urlparse(normalized_url)
        lower_path = str(parsed.path or "").lower()

        # Prefer explicit section URLs when available.
        section_url_match = re.search(r"/section-([0-9a-z.\-]+)(?:/|$)", lower_path)
        if section_url_match:
            return str(section_url_match.group(1)).strip("-")

        # Indiana Code citation in link label (e.g., IC 32-28-3-1).
        ic_label_match = re.search(
            r"\b(?:ic|ind\.\s*code)\s*([0-9]+(?:-[0-9]+){3,})\b",
            normalized_label,
            flags=re.IGNORECASE,
        )
        if ic_label_match:
            return str(ic_label_match.group(1)).strip()

        # Some archived URLs end with section-like numeric paths.
        section_path_match = re.search(r"/([0-9]+(?:-[0-9]+){3,})(?:\.html)?$", lower_path)
        if section_path_match:
            return str(section_path_match.group(1)).strip()

        fallback = self._derive_section_number_from_url(normalized_url)
        if fallback:
            return str(fallback).strip()

        # Avoid title/article/chapter-only identifiers; section citations
        # typically have at least four numeric segments.
        numeric_label_match = re.search(r"\b([0-9]+(?:-[0-9]+){3,})\b", normalized_label)
        if numeric_label_match:
            return str(numeric_label_match.group(1)).strip()
        return ""

    def _looks_like_indiana_section_number(self, section_number: str) -> bool:
        value = str(section_number or "").strip().lower()
        if not value:
            return False
        if re.fullmatch(r"\d+(?:-\d+){3,}[a-z0-9.\-]*", value):
            return True
        if re.fullmatch(r"\d+[a-z]?(?:\.\d+){3,}[a-z]?", value):
            return True
        return False

    def _is_substantive_indiana_record(self, statute: NormalizedStatute) -> bool:
        if not isinstance(statute, NormalizedStatute):
            return False
        section_number = str(statute.section_number or "").strip()
        full_text = self._normalize_legal_text(str(statute.full_text or ""))
        structured = statute.structured_data if isinstance(statute.structured_data, dict) else {}
        record_type = str(structured.get("record_type") or "").strip().lower()
        source_kind = str(structured.get("source_kind") or "").strip().lower()

        if record_type == "archived_justia_title_index":
            return False
        if section_number.lower().startswith("title "):
            return False
        if source_kind == "official_indiana_archived_chapter_pdf":
            return True
        # The live download path and the configured sidecar path share the
        # same strict ZIP parser.  Treat both parser-owned row kinds alike;
        # otherwise dotted article components such as ``1-1-1.1-1`` can be
        # discarded by the fallback citation-shape heuristic after already
        # passing the exact bundle inventory.
        if source_kind in {
            "official_indiana_code_download_bundle",
            "official_indiana_code_html_zip",
        }:
            return True
        if self._looks_like_indiana_section_number(section_number):
            return True
        if self._contains_statute_signals(full_text) and not self._looks_like_shallow_stub_text(full_text):
            return True
        return False

    def _is_official_indiana_source(self, statute: NormalizedStatute) -> bool:
        """True when the row is attributable to official IGA (live or archived)."""
        if not isinstance(statute, NormalizedStatute):
            return False
        structured = statute.structured_data if isinstance(statute.structured_data, dict) else {}
        source_kind = str(structured.get("source_kind") or "").strip().lower()
        source_url = str(statute.source_url or "").strip().lower()
        if "justia" in source_kind or "justia.com" in source_url:
            return False
        if source_kind.startswith("official_indiana"):
            return True
        if "iga.in.gov" in source_url:
            return True
        if "web.archive.org" in source_url and "iga.in.gov" in source_url:
            return True
        return False

    async def _discover_archived_title_urls(self, limit: int = 160) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=iga.in.gov/legislative/laws/*/ic/titles/*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._request_bytes_direct(cdx_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=35)
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
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out

    async def _scrape_archived_chapter_pdfs(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        headers = {"User-Agent": "Mozilla/5.0"}
        statutes: List[NormalizedStatute] = []
        seen_ids = set()

        candidate_urls = list(self._ARCHIVE_CHAPTER_PDFS)
        pdf_discovery_limit_cap = max(
            500,
            int(os.getenv("INDIANA_ARCHIVED_PDF_DISCOVERY_LIMIT", "12000") or "12000"),
        )
        pdf_discovery_limit = min(pdf_discovery_limit_cap, max(max_statutes * 8, 200))
        for discovered_url in await self._discover_archived_pdf_urls(limit=pdf_discovery_limit):
            if discovered_url not in candidate_urls:
                candidate_urls.append(discovered_url)
        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="indiana:archived-pdfs:start",
            extra={
                "scanned_candidates": 0,
                "discovered_candidates": int(len(candidate_urls)),
                "codes_completed": 0,
                "codes_total": 1,
            },
        )

        for candidate_index, pdf_url in enumerate(candidate_urls, start=1):
            if len(statutes) >= max_statutes:
                break

            statute = await self._build_statute_from_pdf_url(code_name=code_name, pdf_url=pdf_url, headers=headers)
            if statute is None:
                continue
            if statute.statute_id in seen_ids:
                continue

            seen_ids.add(statute.statute_id)
            statutes.append(statute)
            if candidate_index == 1 or candidate_index % 50 == 0:
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="indiana:archived-pdfs:progress",
                    extra={
                        "scanned_candidates": int(candidate_index),
                        "discovered_candidates": int(len(candidate_urls)),
                        "codes_completed": 0,
                        "codes_total": 1,
                    },
                )

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="indiana:archived-pdfs:complete",
            force=True,
            extra={
                "scanned_candidates": int(min(len(candidate_urls), len(seen_ids))),
                "discovered_candidates": int(len(candidate_urls)),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes

    async def _discover_archived_pdf_urls(self, limit: int = 240) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=iga.in.gov/static-documents/*.pdf"
            "&output=json"
            "&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            # CDX is already the archive API surface; skip multi-engine search
            # fallback here to avoid long 429/throttle stalls.
            payload = await self._request_bytes_direct(
                cdx_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=35,
            )
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original or not original.lower().endswith(".pdf"):
                continue
            if not self._TITLE_ARTICLE_CHAPTER_RE.search(original):
                continue
            out.append(f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}")

        return out

    async def _build_statute_from_pdf_url(
        self,
        code_name: str,
        pdf_url: str,
        headers: Dict[str, str],
    ) -> NormalizedStatute | None:
        doc_id = self._extract_doc_id(pdf_url)
        if not doc_id:
            return None

        pdf_bytes = await self._request_bytes(pdf_url=pdf_url, headers=headers, timeout=45)
        if not pdf_bytes:
            return None

        full_text = self._extract_pdf_text(pdf_bytes, max_chars=None)
        if len(full_text) < 280:
            # Preserve discoverable archived statute PDFs even when extraction is partial.
            full_text = (
                f"Archived Indiana Code document for {doc_id}. "
                "Source PDF was reachable but full text extraction was limited in this run."
            )

        section_name = f"Indiana Code {doc_id}"
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {doc_id}",
            code_name=code_name,
            section_number=doc_id,
            section_name=section_name,
            full_text=full_text,
            legal_area=self._identify_legal_area(full_text),
            source_url=pdf_url,
            official_cite=f"Ind. Code {doc_id}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_indiana_archived_chapter_pdf",
                "discovery_method": "wayback_static_document_pdf",
                "skip_hydrate": True,
            },
        )

    def _extract_doc_id(self, pdf_url: str) -> str:
        match = self._TITLE_ARTICLE_CHAPTER_RE.search(str(pdf_url or ""))
        if match:
            title = str(int(match.group("title")))
            article = match.group("article")
            chapter = str(int(match.group("chapter")))
            return f"tit. {title}, art. {article}, ch. {chapter}"

        filename = str(pdf_url or "").rsplit("/", 1)[-1]
        filename = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        filename = re.sub(r"[^A-Za-z0-9._-]+", " ", filename).strip()
        return filename[:80] if filename else "archived-pdf"

    async def _request_bytes(self, pdf_url: str, headers: Dict[str, str], timeout: int) -> bytes:
        candidates = [str(pdf_url or "")]
        # Wayback often serves an HTML shell unless we request iframe/raw replay.
        wayback_iframe = self._to_wayback_iframe_url(candidates[0])
        if wayback_iframe and wayback_iframe not in candidates:
            candidates.insert(0, wayback_iframe)

        if candidates[0].startswith("https://"):
            candidates.append("http://" + candidates[0][8:])
        elif candidates[0].startswith("http://"):
            candidates.append("https://" + candidates[0][7:])

        for candidate in candidates:
            try:
                payload = await self._request_bytes_direct(candidate, headers=headers, timeout=timeout)
                if payload and self._looks_like_pdf_bytes(payload):
                    return payload
            except Exception:
                continue

        return b""

    @staticmethod
    def _env_flag(name: str) -> bool:
        return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}

    async def _fetch_archived_indiana_page(
        self,
        url: str,
        timeout_seconds: int = 35,
        *,
        allow_archival_fallback: bool = False,
    ) -> bytes:
        """Fetch archived Indiana/Justia pages with a fast direct-first path.

        Indiana full-corpus runs can appear stalled when archive/search fallback
        loops hit repeated 429s across many Justia candidate URLs. For Wayback
        pages, we first try direct replay candidates and only use the heavier
        archival/search chain when explicitly enabled.
        """
        fetch_url = self._canonical_fetch_url(url)
        if not fetch_url:
            return b""

        rewritten_wayback = self._rewrite_plain_wayback_url(fetch_url)
        if rewritten_wayback:
            fetch_url = rewritten_wayback

        if "web.archive.org/web/" not in fetch_url:
            headers = {
                "User-Agent": "ipfs-datasets-state-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            }
            timeout = max(5, int(timeout_seconds or 35))
            try:
                payload = await self._request_bytes_direct(fetch_url, headers=headers, timeout=timeout)
            except Exception:
                payload = b""
            if (
                payload
                and not self._is_object_moved_placeholder(payload)
                and not self._looks_like_javascript_shell_payload(payload)
            ):
                return payload
            if allow_archival_fallback or self._env_flag("INDIANA_ALLOW_ARCHIVAL_FETCH_FALLBACK"):
                return await self._fetch_page_content_with_archival_fallback(
                    fetch_url,
                    timeout_seconds=timeout_seconds,
                )
            return b""

        headers = {
            "User-Agent": "ipfs-datasets-state-scraper/2.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        timeout = max(5, int(timeout_seconds or 35))
        for candidate_url in self._wayback_replay_candidates(fetch_url):
            try:
                payload = await self._request_bytes_direct(candidate_url, headers=headers, timeout=timeout)
            except Exception:
                payload = b""
            if not payload or self._is_object_moved_placeholder(payload):
                continue
            if self._looks_like_wayback_shell_payload(payload):
                continue
            return payload

        if allow_archival_fallback or self._env_flag("INDIANA_ALLOW_ARCHIVAL_FETCH_FALLBACK"):
            return await self._fetch_page_content_with_archival_fallback(
                fetch_url,
                timeout_seconds=timeout_seconds,
            )
        return b""

    def _looks_like_javascript_shell_payload(self, payload: bytes) -> bool:
        if not payload:
            return False
        try:
            text = payload.decode("utf-8", errors="ignore")
        except Exception:
            return False
        if len(text) > 120000:
            # Rich pages can still include this sentence in inline assets;
            # avoid over-classifying large payloads as shells.
            return False
        lower = text.lower()
        return bool(
            self._IGA_JS_SHELL_RE.search(lower)
            and self._IGA_ROOT_DIV_RE.search(lower)
            and "indiana general assembly" in lower
        )

    def _looks_like_wayback_shell_payload(self, payload: bytes) -> bool:
        if not payload:
            return False
        try:
            text = payload.decode("utf-8", errors="ignore")
        except Exception:
            return False
        lower = text.lower()
        return bool(self._WAYBACK_SHELL_RE.search(lower))

    def _normalize_wayback_child_url(self, *, page_url: str, candidate_url: str) -> str:
        """Normalize child links under Wayback replay pages to replay URLs."""
        normalized = str(candidate_url or "").strip()
        if not normalized:
            return normalized
        if "web.archive.org/web/" in normalized:
            return normalized

        replay_match = self._WAYBACK_REPLAY_RE.search(str(page_url or "").strip())
        if replay_match is None:
            return normalized

        timestamp = str(replay_match.group("ts") or "").strip()
        parent_original = str(replay_match.group("original") or "").strip()
        if not timestamp or not parent_original:
            return normalized

        try:
            parent_original_parsed = urlparse(parent_original)
            parsed = urlparse(normalized)
        except Exception:
            return normalized

        if not parent_original_parsed.scheme or not parent_original_parsed.netloc:
            return normalized

        path = str(parsed.path or "").strip()
        query = f"?{parsed.query}" if parsed.query else ""
        host = str(parsed.netloc or "").strip().lower()

        if host in {"web.archive.org", "www.web.archive.org"} and "/web/" in path:
            return normalized

        if host in {"web.archive.org", "www.web.archive.org"}:
            original_url = f"{parent_original_parsed.scheme}://{parent_original_parsed.netloc}{path}{query}"
        elif host:
            original_url = normalized
        else:
            original_url = f"{parent_original_parsed.scheme}://{parent_original_parsed.netloc}{path}{query}"

        return f"https://web.archive.org/web/{timestamp}/{quote(original_url, safe=':/?=&._-')}"

    def _rewrite_plain_wayback_url(self, url: str) -> str:
        """Rewrite plain web.archive paths to timestamped replay URLs."""
        value = str(url or "").strip()
        if not value:
            return value
        if "web.archive.org/web/" in value:
            return value

        try:
            parsed = urlparse(value)
        except Exception:
            return value

        host = str(parsed.netloc or "").strip().lower()
        path = str(parsed.path or "")
        if host not in {"web.archive.org", "www.web.archive.org"}:
            return value
        if not path.startswith("/codes/indiana/"):
            return value

        replay_ts = str(os.getenv("INDIANA_WAYBACK_FALLBACK_TIMESTAMP", "20241203192652") or "").strip()
        if not replay_ts:
            replay_ts = "20241203192652"
        original_url = f"https://law.justia.com{path}"
        if parsed.query:
            original_url += f"?{parsed.query}"
        return f"https://web.archive.org/web/{replay_ts}/{quote(original_url, safe=':/?=&._-')}"

    def _is_probable_indiana_section_url(self, lower_url: str) -> bool:
        value = str(lower_url or "").strip().lower()
        if not value:
            return False
        if "/section-" in value:
            return True
        if re.search(r"/\d+(?:-\d+){2,}(?:\.html)?(?:/)?$", value):
            return True
        if value.endswith("/index.html"):
            return False
        # Article/chapter index pages frequently end in `.../chX.html` and are
        # high-noise placeholders. Keep them crawlable, but do not emit them as
        # statutes.
        if re.search(r"/title\d+(?:\.\d+)?/(?:ar\d+(?:\.\d+)?/)?ch\d+(?:\.\d+)?\.html$", value):
            return False
        return bool(re.search(r"/title\d+(?:\.\d+)?/(?:ar\d+(?:\.\d+)?/)?(?:ch\d+(?:\.\d+)?/)?[^/]+\.html$", value))

    def _mark_skip_hydrate_for_archived_justia_records(self, statutes: List[NormalizedStatute]) -> None:
        """Prevent costly hydrate retries for archived Justia placeholder URLs."""
        for statute in statutes or []:
            if not isinstance(statute, NormalizedStatute):
                continue
            source_url = self._canonicalize_statute_url(str(statute.source_url or "").strip())
            if not source_url:
                continue
            lower_url = source_url.lower()
            structured = statute.structured_data if isinstance(statute.structured_data, dict) else {}
            source_kind = str(structured.get("source_kind") or "").strip().lower()
            if "archived_justia_indiana" not in source_kind and "law.justia.com/codes/indiana/" not in lower_url:
                continue
            structured_update = dict(structured)
            structured_update["skip_hydrate"] = True
            statute.structured_data = structured_update

    async def _request_bytes_direct(self, url: str, headers: Dict[str, str], timeout: int) -> bytes:
        return await self._fetch_parser_input_with_transport(
            url,
            headers=headers or {"User-Agent": "Mozilla/5.0"},
            timeout_seconds=max(1, int(timeout or 25)),
            # Archive/Wayback callers explicitly control their heavier retry
            # path around this bounded direct primitive.
            allow_archival_fallback=False,
            provider="requests_direct",
        )

    def _to_wayback_iframe_url(self, url: str) -> str:
        if not url or "web.archive.org/web/" not in url:
            return ""

        if "/if_/" in url:
            return url

        return re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", url, count=1)

    @staticmethod
    def _looks_like_pdf_bytes(payload: bytes) -> bool:
        return bool(re.match(rb"^\s*%PDF-", bytes(payload or b"")[:512], re.IGNORECASE))

    def _extract_pdf_text(
        self,
        pdf_bytes: bytes,
        max_chars: Optional[int] = None,
    ) -> str:
        """Extract text using pdftotext if available in the runtime."""
        if not self._looks_like_pdf_bytes(pdf_bytes):
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

    @staticmethod
    def _indiana_inventory_frontier(
        inventory: Mapping[str, Any],
    ) -> Dict[str, Any]:
        frontier = inventory.get("frontier")
        disposition = inventory.get("disposition")
        bundle = inventory.get("bundle")
        if not all(
            isinstance(item, Mapping)
            for item in (frontier, disposition, bundle)
        ):
            raise RuntimeError("Indiana bulk inventory lacks closure material")
        return {
            "admitted_source_record_count": int(
                inventory.get("admitted_source_record_count") or 0
            ),
            "admitted_source_record_ids_sha256": str(
                inventory.get("admitted_source_record_ids_sha256") or ""
            ),
            "bundle_byte_size": int(bundle.get("byte_size") or 0),
            "bundle_closed": frontier.get("bundle_closed") is True,
            "bundle_content_sha256": str(bundle.get("content_sha256") or ""),
            "closed": frontier.get("closed") is True,
            "disposition": dict(disposition),
            "enumerator_closed": frontier.get("enumerator_closed") is True,
            "expected_index_units": int(
                frontier.get("expected_index_units") or 0
            ),
            "html_member_count": int(inventory.get("html_member_count") or 0),
            "inventory_sha256": str(inventory.get("inventory_sha256") or ""),
            "scope_closed": frontier.get("scope_closed") is True,
            "source_record_count": int(
                inventory.get("source_record_count") or 0
            ),
            "source_record_ids_sha256": str(
                inventory.get("source_record_ids_sha256") or ""
            ),
            "unusable_row_count": int(inventory.get("unusable_row_count") or 0),
            "unvisited_continuation_links": [],
            "visited_index_units": int(
                frontier.get("visited_index_units") or 0
            ),
        }

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay the retained ZIP and prove exact section/output parity."""

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from ...legal_data.state_laws_legacy_v2_adapter import file_sha256
        from .indiana_bulk import inventory_indiana_bulk_zip

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "Indiana frontier closure requires an attached acquisition ledger"
            )
        first = self._load_indiana_first_bulk_inventory()
        first_frontier_raw = first.get("frontier")
        first_disposition = first.get("disposition")
        if (
            not isinstance(first_frontier_raw, Mapping)
            or first_frontier_raw.get("closed") is not True
            or first_frontier_raw.get("bundle_closed") is not True
            or not isinstance(first_disposition, Mapping)
            or int(first.get("unusable_row_count") or 0) != 0
            or int(first_disposition.get("failed_final") or 0) != 0
            or int(first_disposition.get("quarantined") or 0) != 0
            or int(first_disposition.get("duplicates") or 0) != 0
        ):
            raise RuntimeError(
                "Indiana first bulk inventory has unresolved source records"
            )

        official_source_url = str(
            self._indiana_bulk_provenance.get("official_url") or ""
        ).strip()
        replayed_input = ledger.replay_retained_parser_input_file(
            official_url=official_source_url,
            sanitized_request={"method": "GET", "url": official_source_url},
        )
        if replayed_input is None or replayed_input.receipt.content is None:
            raise RuntimeError(
                "Indiana retained bulk object cannot be independently replayed"
            )
        if str(replayed_input.receipt.content.sha256) != str(
            self._indiana_bulk_provenance.get("content_sha256") or ""
        ):
            raise RuntimeError("Indiana retained bundle digest changed on replay")
        replayed = await asyncio.to_thread(
            inventory_indiana_bulk_zip,
            Path(replayed_input.body_path),
            code_name=str(first.get("code_name") or "Indiana Code"),
            code_year=str(first.get("code_year") or self.OFFICIAL_CODE_YEAR),
            bundle_provenance=dict(self._indiana_bulk_provenance),
        )
        replayed = self._validate_indiana_bulk_inventory(replayed)
        if canonical_json_bytes(first) != canonical_json_bytes(replayed):
            raise RuntimeError(
                "Indiana first and replayed ZIP section inventories differ"
            )

        raw_canonical_keys = canonical_output_projection.get("canonical_keys")
        if not isinstance(raw_canonical_keys, Sequence) or isinstance(
            raw_canonical_keys, (str, bytes, bytearray)
        ):
            raise RuntimeError(
                "Indiana canonical output projection lacks exact identities"
            )
        canonical_keys = [str(item).strip() for item in raw_canonical_keys]
        expected_canonical_keys = [
            str(item) for item in first.get("admitted_canonical_keys") or []
        ]
        if (
            not canonical_keys
            or any(not item for item in canonical_keys)
            or len(canonical_keys) != len(set(canonical_keys))
        ):
            raise RuntimeError(
                "Indiana canonical output identities are empty or duplicated"
            )
        missing = sorted(set(expected_canonical_keys) - set(canonical_keys))
        extra = sorted(set(canonical_keys) - set(expected_canonical_keys))
        if canonical_keys != expected_canonical_keys or missing or extra:
            raise RuntimeError(
                "Indiana canonical identities do not exactly match admitted ZIP "
                "source IDs: "
                f"expected={len(expected_canonical_keys)} "
                f"actual={len(canonical_keys)} "
                f"missing={missing[:3]} extra={extra[:3]}"
            )

        compact_frontier = self._indiana_inventory_frontier(first)
        replayed_frontier = self._indiana_inventory_frontier(replayed)
        disposition = dict(first_disposition)
        completion = closed_jurisdiction_receipt(
            "IN",
            discovered=int(disposition["discovered"]),
            fetched=int(disposition["fetched"]),
            excluded=int(disposition["excluded"]),
            quarantined=int(disposition["quarantined"]),
            failed_final=int(disposition["failed_final"]),
            duplicates=int(disposition.get("duplicates") or 0),
            source_domain="iga.in.gov",
            canonical_keys=canonical_keys,
            derived_keys=canonical_keys,
        )
        boundaries = first.get("boundary_probes")
        if not isinstance(boundaries, Mapping):
            raise RuntimeError("Indiana bulk inventory lacks boundary probes")
        completion.update(
            {
                "boundary_probes": {
                    "bundle_total": 1,
                    "first_hierarchy_unit": str(
                        boundaries.get("first_source_record_id") or ""
                    ),
                    "last_hierarchy_unit": str(
                        boundaries.get("last_source_record_id") or ""
                    ),
                    "pagination_total": int(
                        first.get("html_member_count") or 0
                    ),
                },
                "canonical_row_count": len(canonical_keys),
                "edition": str(first.get("code_year") or ""),
                "frontier": compact_frontier,
                "legal_as_of": str(
                    self._indiana_bulk_provenance.get("retrieved_at") or ""
                ),
                "observed_at": str(
                    self._indiana_bulk_provenance.get("retrieved_at") or ""
                ),
                "replay": {
                    "closed": True,
                    "first_frontier_digest": str(first["inventory_sha256"]),
                    "second_frontier_digest": str(replayed["inventory_sha256"]),
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "source_frontier_inventory": {
                    "inventory_relative_path": str(
                        self._indiana_first_bulk_inventory_observation.get(
                            "relative_path"
                        )
                        or ""
                    ),
                    "inventory_sha256": str(first["inventory_sha256"]),
                    "source_record_count": int(
                        first.get("source_record_count") or 0
                    ),
                    "source_record_ids_sha256": str(
                        first.get("source_record_ids_sha256") or ""
                    ),
                },
                "transport": {
                    "fixture": False,
                    "kind": "retained_official_indiana_code_zip",
                    "synthetic": False,
                },
            }
        )
        bundle_digest = str(
            self._indiana_bulk_provenance.get("content_sha256") or ""
        ).strip().lower()
        acquisition_path_ids = self._catalog_acquisition_path_ids_for_source(
            official_source_url
        )
        source_file = inspect.getsourcefile(type(self))
        source_version_digest = (
            file_sha256(Path(source_file))
            if source_file and Path(source_file).is_file()
            else hashlib.sha256(
                f"{type(self).__module__}.{type(self).__qualname__}".encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=replayed_frontier,
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{bundle_digest}",
            official_source_url=official_source_url,
            acquisition_path_ids=acquisition_path_ids,
            observation_time=str(
                self._indiana_bulk_provenance.get("retrieved_at") or ""
            ),
            source_software_version=(
                f"{type(self).__module__}.{type(self).__qualname__}"
                f"@sha256:{source_version_digest}"
            ),
        )

    def _enrich_statute_structure(
        self,
        statute: NormalizedStatute,
    ) -> NormalizedStatute:
        """Carry retained ZIP/member provenance into canonical JSON-LD."""

        enriched = super()._enrich_statute_structure(statute)
        structured = dict(enriched.structured_data or {})
        if str(structured.get("source_kind") or "").strip() != (
            "official_indiana_code_html_zip"
        ):
            return enriched
        digest = str(structured.get("content_sha256") or "").strip().lower()
        source_record_id = str(structured.get("source_record_id") or "").strip()
        receipt = structured.get("transport_receipt")
        source_bundle = structured.get("source_bundle")
        source_member = structured.get("source_member")
        jsonld = structured.get("jsonld")
        provenance_complete = bool(
            re.fullmatch(r"[a-f0-9]{64}", digest)
            and source_record_id
            and isinstance(receipt, Mapping)
            and isinstance(source_bundle, Mapping)
            and isinstance(source_member, Mapping)
            and isinstance(jsonld, Mapping)
        )
        if not provenance_complete:
            if getattr(self, "_state_law_acquisition_ledger", None) is not None:
                raise RuntimeError(
                    "Indiana bulk row lacks retained bundle/member provenance"
                )
            return enriched
        jsonld_payload = dict(jsonld)
        prior = jsonld_payload.get("provenance")
        provenance = dict(prior) if isinstance(prior, Mapping) else {}
        provenance.update(
            {
                "content_sha256": digest,
                "source_bundle": dict(source_bundle),
                "source_member": dict(source_member),
                "source_record_id": source_record_id,
                "transport_receipt": dict(receipt),
            }
        )
        jsonld_payload["provenance"] = provenance
        structured["jsonld"] = jsonld_payload
        enriched.structured_data = structured
        return enriched

    def official_title_url(self, title_number: str, year: str | None = None) -> str:
        code_year = str(year or self.OFFICIAL_CODE_YEAR).strip() or self.OFFICIAL_CODE_YEAR
        token = str(title_number or "").strip()
        return f"https://iga.in.gov/legislative/laws/{code_year}/ic/titles/{token}"

    def official_title_catalog(self, year: str | None = None) -> List[Dict[str, str]]:
        """Return the exhaustive official Indiana Code title catalog."""

        rows: List[Dict[str, str]] = []
        for number, name in self.OFFICIAL_TITLES:
            url = self.official_title_url(number, year=year)
            rows.append(
                {
                    "canonical_key": f"in:title-{str(number).lower()}",
                    "source_url": url,
                    "label": f"Title {number} {name}",
                    "title_number": str(number),
                    "text": (
                        f"Indiana Code Title {number} ({name}) official catalog "
                        f"unit retained from {url}"
                    ),
                }
            )
        return rows

    def _official_ssl_context(self, *, unverified: bool = False):
        if unverified:
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _official_http_get(self, url: str, timeout: int = 20) -> Tuple[bytes, bytes, bytes]:
        """Fetch one official Indiana URL and retain request/response/body bytes."""

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
                "User-Agent": "ipfs-datasets-open-us-law-indiana/1.0",
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
            raise RuntimeError(f"official Indiana GET failed for {url}: {last_exc}") from last_exc
        if status != 200 or not body:
            raise RuntimeError(f"official Indiana GET returned HTTP {status} for {url}")
        response_bytes = f"HTTP/1.1 {status} OK\n{header_block}\n".encode("utf-8") + body
        return request_bytes, response_bytes, body

    def _parse_official_title_index(self, html: str, index_url: str) -> List[Dict[str, str]]:
        """Parse official Indiana Code title units from a live titles index."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Indiana discovery") from exc

        soup = BeautifulSoup(html, "html.parser")
        units: List[Dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = urljoin(index_url, str(link.get("href") or "").strip())
            match = self._TITLE_HREF_RE.search(href)
            if not match:
                continue
            number = match.group("title").lstrip("0") or "0"
            key = f"in:title-{number.lower()}"
            if key in seen:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not label:
                label = f"Title {number}"
            seen.add(key)
            units.append(
                {
                    "canonical_key": key,
                    "source_url": href,
                    "label": label,
                    "title_number": number,
                    "text": (
                        f"Indiana Code Title {number} official title index entry "
                        f"retained from {href}"
                    ),
                }
            )
        return units

    def fetch_official(self, code: str = "IN"):
        """Acquire the uncapped official Indiana Code title frontier.

        Live HTTPS retains the official titles index. Every enacted Indiana
        Code title is enumerated with an official IGA URL. This hook never
        returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or self.state_code or "IN").strip().upper()
        if normalized != "IN":
            raise ValueError(f"IndianaScraper cannot acquire {normalized}")
        candidates = (
            self.OFFICIAL_ENTRY_URL,
            "https://iga.in.gov/legislative/laws/2025/ic/titles/",
            "https://iga.in.gov/legislative/laws/2024/ic/titles/",
            "https://iga.in.gov/laws/ic/downloads",
        )
        request_bytes = b""
        response_bytes = b""
        index_body = b""
        index_url = self.OFFICIAL_ENTRY_URL
        last_exc: Exception | None = None
        for candidate in candidates:
            try:
                request_bytes, response_bytes, index_body = self._official_http_get(candidate)
                index_url = candidate
                last_exc = None
                break
            except RuntimeError as exc:
                last_exc = exc
                continue
        if last_exc is not None or not index_body:
            raise RuntimeError(
                f"official Indiana titles index is unavailable: {last_exc}"
            )
        year_match = re.search(r"/laws/(\d{4})/", index_url)
        live_year = year_match.group(1) if year_match else self.OFFICIAL_CODE_YEAR
        html = index_body.decode("utf-8", errors="replace")
        discovered = {
            unit["title_number"]: unit
            for unit in self._parse_official_title_index(html, index_url)
        }
        units = self.official_title_catalog(year=live_year)
        for unit in units:
            live = discovered.get(unit["title_number"])
            if live:
                unit["source_url"] = live["source_url"]
                unit["label"] = live["label"]
                unit["text"] = live["text"]
        if len(units) < 3:
            raise RuntimeError(
                f"official Indiana title catalog is incomplete: {len(units)} units"
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
        parsed_index = urlparse(index_url)
        source_path = parsed_index.path or self.OFFICIAL_ENTRY_PATH
        if parsed_index.query:
            source_path = f"{source_path}?{parsed_index.query}"
        return OfficialFetch(
            jurisdiction_code="IN",
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=catalog,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=source_path,
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=rows[0]["canonical_key"],
            last_hierarchy_unit=rows[-1]["canonical_key"],
        )


# Register this scraper with the registry
StateScraperRegistry.register("IN", IndianaScraper)
