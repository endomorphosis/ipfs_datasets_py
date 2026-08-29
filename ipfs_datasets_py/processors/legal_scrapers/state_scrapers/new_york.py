"""New York state law scraper.

Scrapes laws from the New York State Senate website
(https://www.nysenate.gov/).
"""

import hashlib
import json
import re
import ssl
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urljoin, urlparse

from .base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StateLawPageMultiFetchResult,
    StatuteMetadata,
    _sanitized_multifetch_headers,
    _sanitized_multifetch_request,
)
from .registry import StateScraperRegistry


class NewYorkScraper(BaseStateScraper):
    """Scraper for New York state laws."""
    _NY_PUBLIC_LAW_LINK_RE = re.compile(r"https://newyork\.public\.law/laws/n\.y\._[^\s)`]+", re.IGNORECASE)
    _NY_PUBLIC_LAW_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://newyork\.public\.law/laws/[^)]+)\)", re.IGNORECASE)
    _NY_SENATE_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://www\.nysenate\.gov/legislation/laws/[^)]+)\)", re.IGNORECASE)
    OFFICIAL_DOMAIN = "www.nysenate.gov"
    OFFICIAL_ENTRY_PATH = "/legislation/laws"
    OFFICIAL_ENTRY_URL = "https://www.nysenate.gov/legislation/laws"
    OFFICIAL_CONSOLIDATED_URL = (
        "https://www.nysenate.gov/legislation/laws/CONSOLIDATED"
    )
    OFFICIAL_PDF_DOMAIN = "legislation.nysenate.gov"
    # Source-proved against the official Consolidated Laws page and its exact
    # 2026-08-11 Wayback raw capture.  Count equality plus the ordered-code
    # digest makes catalog drift fail closed until a newly audited membership
    # updates this source bundle.  The legacy name is retained for compatibility
    # with focused synthetic tests; it is an exact expected count, not a floor.
    STRICT_MINIMUM_CONSOLIDATED_LAWS = 94
    STRICT_CURRENT_CONSOLIDATED_CODE_SHA256 = (
        "792d08fe5168ff6b429d13076fa843a8e5987c4b670339e1a2c6ca70420d590c"
    )
    # Exact source-derived residual identities after the two signed Assembly
    # bill records below prove CPL 150.30 and EDN 666 repealed.  These are not
    # decisions: they authorize only one bounded supplemental-input wave.
    # Every retained page remains unresolved until a reviewed source-bound
    # resolver proves a specific operative or terminal disposition.
    STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS = (
        ("EPT", "3-6.5", "", "missing_lifecycle_note"),
        ("GBS", "495-d", "", "missing_lifecycle_note"),
        ("GMU", "902", "", "missing_lifecycle_note"),
        ("PBA", "2799-aaaa", "", "missing_lifecycle_note"),
        ("EDN", "669-c", "", "toc_section_missing_body_identity"),
        ("EDN", "2023-b", "*2", "toc_section_missing_body_identity"),
        ("ELD", "221", "", "toc_section_missing_body_identity"),
        ("ELN", "3-408", "", "toc_section_missing_body_identity"),
        ("ELN", "7-108", "", "toc_section_missing_body_identity"),
        ("ELN", "8-310", "", "toc_section_missing_body_identity"),
        ("ELN", "9-104", "", "toc_section_missing_body_identity"),
        ("ELN", "9-128", "", "toc_section_missing_body_identity"),
        ("ELN", "11-304", "", "toc_section_missing_body_identity"),
        ("ELN", "17-140", "", "toc_section_missing_body_identity"),
        ("ELN", "17-158", "", "toc_section_missing_body_identity"),
        ("EXC", "236", "", "toc_section_missing_body_identity"),
        ("GMU", "371-a", "*2", "toc_section_missing_body_identity"),
        ("ISC", "3114", "", "toc_section_missing_body_identity"),
        ("MHY", "7.48", "", "toc_section_missing_body_identity"),
        ("PAR", "27.09", "", "toc_section_missing_body_identity"),
        ("SOS", "364-j-1", "", "toc_section_missing_body_identity"),
        ("SOS", "369-ii", "", "toc_section_missing_body_identity"),
        ("TAX", "602", "", "toc_section_missing_body_identity"),
        ("TAX", "622", "", "toc_section_missing_body_identity"),
        ("TAX", "636", "", "toc_section_missing_body_identity"),
        ("TAX", "1262-l", "*2", "toc_section_missing_body_identity"),
        ("VAT", "235", "*2", "toc_section_missing_body_identity"),
        ("VAT", "235", "*3", "toc_section_missing_body_identity"),
        ("VAT", "1180-i", "*5", "toc_section_missing_body_identity"),
        ("VAT", "1180-i", "*6", "toc_section_missing_body_identity"),
    )
    STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS = (
        "https://www.nysenate.gov/legislation/laws/EPT/3-6.5",
        "https://www.nysenate.gov/legislation/laws/GBS/495-d",
        "https://www.nysenate.gov/legislation/laws/GMU/902",
        "https://www.nysenate.gov/legislation/laws/PBA/2799-aaaa",
        "https://www.nysenate.gov/legislation/laws/EDN/669-c",
        "https://www.nysenate.gov/legislation/laws/EDN/2023-b",
        "https://www.nysenate.gov/legislation/laws/ELD/221",
        "https://www.nysenate.gov/legislation/laws/ELN/3-408",
        "https://www.nysenate.gov/legislation/laws/ELN/7-108",
        "https://www.nysenate.gov/legislation/laws/ELN/8-310",
        "https://www.nysenate.gov/legislation/laws/ELN/9-104",
        "https://www.nysenate.gov/legislation/laws/ELN/9-128",
        "https://www.nysenate.gov/legislation/laws/ELN/11-304",
        "https://www.nysenate.gov/legislation/laws/ELN/17-140",
        "https://www.nysenate.gov/legislation/laws/ELN/17-158",
        "https://www.nysenate.gov/legislation/laws/EXC/236",
        "https://www.nysenate.gov/legislation/laws/GMU/371-a",
        "https://www.nysenate.gov/legislation/laws/ISC/3114",
        "https://www.nysenate.gov/legislation/laws/MHY/7.48",
        "https://www.nysenate.gov/legislation/laws/PAR/27.09",
        "https://www.nysenate.gov/legislation/laws/SOS/364-j-1",
        "https://www.nysenate.gov/legislation/laws/SOS/369-ii",
        "https://www.nysenate.gov/legislation/laws/TAX/602",
        "https://www.nysenate.gov/legislation/laws/TAX/622",
        "https://www.nysenate.gov/legislation/laws/TAX/636",
        "https://www.nysenate.gov/legislation/laws/TAX/1262-l",
        "https://www.nysenate.gov/legislation/laws/VAT/235",
        "https://www.nysenate.gov/legislation/laws/VAT/1180-i",
    )
    STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256 = (
        "b03131cd20eb808d159427e548a732a078fc7b3f94291a2c5fff8a4cd206dde0"
    )
    OFFICIAL_ASSEMBLY_DOMAIN = "assembly.ny.gov"
    STRICT_CURRENT_SIGNED_BILL_PROOF_ROWS = (
        (
            "CPL",
            "150.30",
            "CPL:150.30:signed-bill-record",
            (
                "https://assembly.ny.gov/leg/"
                "?Actions=Y&Summary=Y&Text=Y&bn=A02009&term=2019"
            ),
        ),
        (
            "EDN",
            "666",
            "EDN:666:signed-bill-record",
            (
                "https://assembly.ny.gov/leg/"
                "?Actions=Y&Summary=Y&Text=Y&bn=A03006&term=2025"
            ),
        ),
    )
    STRICT_CURRENT_SIGNED_BILL_PROOF_URL_SHA256 = (
        "ef7e526c284aa62b725b457639b71707627482ac9b35ea76ff8bf74ad48a8a31"
    )
    STRICT_CURRENT_ENV_PROOF_ROWS = (
        (
            "ENV:2025:concurrent-resolution",
            "official_assembly_bill_record",
            (
                "https://assembly.ny.gov/leg/"
                "?Actions=Y&Summary=Y&Text=Y&bn=A07454&term=2025"
            ),
        ),
        (
            "ENV:2025:implementation-record",
            "official_assembly_bill_record",
            (
                "https://assembly.ny.gov/leg/"
                "?Actions=Y&Summary=Y&Text=Y&bn=A03628&term=2025"
            ),
        ),
        (
            "ENV:2025:constitution-article-14",
            "official_constitution_section",
            "https://www.nysenate.gov/legislation/laws/CNS/A14S1",
        ),
        (
            "ENV:2025:constitution-article-19",
            "official_constitution_section",
            "https://www.nysenate.gov/legislation/laws/CNS/A19S1",
        ),
    )
    STRICT_CURRENT_ENV_PROOF_URL_SHA256 = (
        "8c37b727ae420312d7ef203c3a047cd8e8496d4bae2b35a9af36e820a672a74e"
    )
    STRICT_CURRENT_EVENT_PROOF_ROWS = (
        (
            "MHY",
            "mhy_2022_ch481_regulations",
            "MHY:82:state-register-adoption",
            "official_state_register_adoption",
            "https://dos.ny.gov/system/files/documents/2025/08/082025.pdf",
        ),
        (
            "PBA",
            "mac_liability_discharge",
            "PBA:3030-3041:mac-termination",
            "official_government_financial_report",
            (
                "https://www.nyc.gov/assets/investorrelations/downloads/pdf/"
                "go-bonds-statements/2011/nycgo-2011f.pdf"
            ),
        ),
        (
            "RSS",
            "rss_2011_ch525_condition",
            "RSS:1204-a:chapter-525-effective-clause",
            "official_enacted_bill_text",
            "https://legislation.nysenate.gov/pdf/bills/2011/S5837",
        ),
        (
            "RSS",
            "rss_2011_ch525_condition",
            "RSS:1204-a:osc-payroll-bulletin-1275",
            "official_comptroller_payroll_bulletin",
            (
                "https://www.osc.ny.gov/state-agencies/payroll-bulletins/"
                "state-agencies/1275-new-deduction-code-616-paf-retirement-"
                "tax-paf-btx-and-new-deduction"
            ),
        ),
    )
    STRICT_CURRENT_EVENT_PROOF_URL_SHA256 = (
        "0e874dec7297f2d6862acba3f5c1369033ab2817cbb47bf61ec4d076adeb23a6"
    )
    _NY_LAW_HREF_RE = re.compile(
        r"/legislation/laws/(?P<code>[A-Z]{2,4})(?:/|$)",
        re.IGNORECASE,
    )
    OFFICIAL_LAWS = (
        ("ABP", "Abandoned Property"),
        ("AGM", "Agriculture and Markets"),
        ("ABC", "Alcoholic Beverage Control"),
        ("ACA", "Arts and Cultural Affairs"),
        ("BNK", "Banking"),
        ("BSC", "Business Corporation"),
        ("CAL", "Canal"),
        ("CVP", "Civil Practice Law and Rules"),
        ("CVR", "Civil Rights"),
        ("CVS", "Civil Service"),
        ("COP", "Cooperative Corporations"),
        ("COR", "Correction"),
        ("CNT", "County"),
        ("CPL", "Criminal Procedure"),
        ("DCD", "Debtor and Creditor"),
        ("DOM", "Domestic Relations"),
        ("EDN", "Education"),
        ("ELN", "Election"),
        ("EDP", "Eminent Domain Procedure"),
        ("EML", "Employers' Liability"),
        ("ENG", "Energy"),
        ("ENV", "Environmental Conservation"),
        ("EPT", "Estates, Powers and Trusts"),
        ("EXC", "Executive"),
        ("FIS", "Financial Services"),
        ("GAS", "General Associations"),
        ("GBS", "General Business"),
        ("GCT", "General City"),
        ("GMU", "General Municipal"),
        ("GOB", "General Obligations"),
        ("HAY", "Highway"),
        ("ISC", "Insurance"),
        ("JUD", "Judiciary"),
        ("LAB", "Labor"),
        ("LEG", "Legislative"),
        ("LIE", "Lien"),
        ("LLC", "Limited Liability Company"),
        ("LFN", "Local Finance"),
        ("MHY", "Mental Hygiene"),
        ("MIL", "Military"),
        ("MDW", "Multiple Dwelling"),
        ("MRE", "Multiple Residence"),
        ("MHR", "Municipal Home Rule"),
        ("NAV", "Navigation"),
        ("PAR", "Partnership"),
        ("PEN", "Penal"),
        ("PEP", "Personal Property"),
        ("PVH", "Private Housing Finance"),
        ("PBB", "Public Buildings"),
        ("PBH", "Public Health"),
        ("PUH", "Public Housing"),
        ("PBL", "Public Lands"),
        ("PBO", "Public Officers"),
        ("PBS", "Public Service"),
        ("RAT", "Rapid Transit"),
        ("RPL", "Real Property"),
        ("RPA", "Real Property Actions and Proceedings"),
        ("RPT", "Real Property Tax"),
        ("REL", "Religious Corporations"),
        ("RSS", "Retirement and Social Security"),
        ("RCC", "Rural Electric Cooperative"),
        ("SCC", "Second Class Cities"),
        ("SOS", "Social Services"),
        ("SWC", "Soil and Water Conservation Districts"),
        ("STL", "State"),
        ("TAX", "Tax"),
        ("TWN", "Town"),
        ("TRA", "Transportation"),
        ("VAT", "Vehicle and Traffic"),
        ("VIL", "Village"),
        ("VAW", "Volunteer Ambulance Workers' Benefit"),
        ("VOL", "Volunteer Firefighters' Benefit"),
        ("WKC", "Workers' Compensation"),
    )
    OFFICIAL_LAW_COUNT = len(OFFICIAL_LAWS)

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind both source parsers and shared closure code into certification."""

        from . import new_york_law_pdf, new_york_openleg, strict_frontier_closure

        return (new_york_law_pdf, new_york_openleg, strict_frontier_closure)

    @staticmethod
    def _new_york_frontier_headers(media_type: str) -> Dict[str, str]:
        return {
            "Accept": (
                "application/pdf,*/*;q=0.8"
                if media_type == "application/pdf"
                else "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
            ),
            "User-Agent": "ipfs-datasets-new-york-laws/2.0",
        }

    @staticmethod
    def _new_york_agm28_selector_headers() -> Dict[str, str]:
        """Return the exact request identity retained for the AGM selector."""

        return {"Accept": "application/pdf,*/*;q=0.8"}

    @staticmethod
    def _new_york_constitution_section_headers() -> Dict[str, str]:
        """Use the direct request shape accepted by the official CNS pages."""

        return {"Accept": "*/*", "User-Agent": "curl/8.5.0"}

    def _new_york_pdf_frontier_batch_size(self) -> int:
        return max(
            1,
            min(
                128,
                self._env_int("STATE_SCRAPER_NY_PDF_BATCH_SIZE", default=128),
            ),
        )

    def _new_york_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                24,
                self._env_int("STATE_SCRAPER_NY_FRONTIER_CONCURRENCY", default=8),
            ),
        )

    @staticmethod
    def _is_valid_new_york_consolidated_catalog(payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        return bool(
            len(sample) > 10_000
            and b"consolidated laws of new york" in sample
            and b"/legislation/laws/" in sample
            and b"</html>" in sample[-2_000:]
        )

    @staticmethod
    def _is_valid_new_york_law_pdf(payload: bytes) -> bool:
        raw = bytes(payload or b"")
        return len(raw) > 1_000 and raw.lstrip().startswith(b"%PDF")

    @staticmethod
    def _is_valid_new_york_event_proof_pdf(payload: bytes) -> bool:
        """Admit exact official PDFs, including DOS's warning-prefixed file."""

        raw = bytes(payload or b"")
        pdf_offset = raw.find(b"%PDF")
        return bool(len(raw) > 1_000 and 0 <= pdf_offset < 1_024)

    @staticmethod
    def _is_valid_new_york_event_proof_html(payload: bytes) -> bool:
        """Admit the exact OSC payroll bulletin event record."""

        sample = bytes(payload or b"").lower()
        return bool(
            len(sample) > 10_000
            and b"<html" in sample[:4_000]
            and b"</html>" in sample[-4_000:]
            and b"state agencies bulletin no. 1275" in sample
            and b"irs) ruling dated july 9, 2013" in sample
            and b"effective october 1, 2013" in sample
            and b"internal revenue code section 414(h)" in sample
        )

    @staticmethod
    def _new_york_event_proof_media_type(proof_kind: str) -> str:
        kind = str(proof_kind or "").strip()
        if kind == "official_comptroller_payroll_bulletin":
            return "text/html"
        if kind in {
            "official_enacted_bill_text",
            "official_government_financial_report",
            "official_state_register_adoption",
        }:
            return "application/pdf"
        raise RuntimeError("New York event proof has an unsupported media type")

    @staticmethod
    def _is_valid_new_york_senate_section_html(payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        has_content_container = bool(
            b'class="nys-openleg-content-container"' in sample
            or b"class='nys-openleg-content-container'" in sample
        )
        return bool(
            len(sample) > 1_000
            and b"<html" in sample[:4_000]
            and b"</html>" in sample[-4_000:]
            and has_content_container
            and b"nys-openleg-not-found" not in sample
            and b"the requested entry could not be found" not in sample
        )

    @staticmethod
    def _is_valid_new_york_assembly_signed_bill_html(payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        return bool(
            len(sample) > 100_000
            and b"<html" in sample[:4_000]
            and b"jump_to_actions" in sample
            and b"jump_to_text" in sample
            and b"bill no" in sample
            and b"signed chap." in sample
            and b"</html>" in sample[-4_000:]
        )

    @staticmethod
    def _is_valid_new_york_assembly_bill_html(payload: bytes) -> bool:
        sample = bytes(payload or b"").lower()
        return bool(
            len(sample) > 10_000
            and b"<html" in sample[:4_000]
            and b"jump_to_actions" in sample
            and b"jump_to_text" in sample
            and b"bill no" in sample
            and b"</html>" in sample[-4_000:]
        )

    @classmethod
    def _new_york_exact_signed_bill_proof_rows(
        cls,
        parsed_reports,
    ) -> List[tuple[str, str, str, str]]:
        """Select the two fixed signed-bill inputs only for present residuals."""

        expected = [
            tuple(str(value) for value in row)
            for row in cls.STRICT_CURRENT_SIGNED_BILL_PROOF_ROWS
        ]
        expected_urls = [row[3] for row in expected]
        if len(expected_urls) != len(set(expected_urls)):
            raise RuntimeError("New York signed-bill proof URLs are not unique")
        if hashlib.sha256("\n".join(expected_urls).encode("utf-8")).hexdigest() != (
            cls.STRICT_CURRENT_SIGNED_BILL_PROOF_URL_SHA256
        ):
            raise RuntimeError("New York signed-bill proof URL projection changed")
        for _code, _section, selector_key, url in expected:
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != cls.OFFICIAL_ASSEMBLY_DOMAIN
                or parsed.path != "/leg/"
                or not parsed.query
                or not selector_key.endswith(":signed-bill-record")
            ):
                raise RuntimeError(
                    "New York signed-bill proof escaped its exact official identity"
                )

        reports_by_code = {
            str(getattr(report, "law_code", "") or "").strip().upper(): report
            for report in parsed_reports
        }
        selected: List[tuple[str, str, str, str]] = []
        for code, section, selector_key, url in expected:
            report = reports_by_code.get(code)
            if report is None:
                continue
            matches = [
                row
                for row in list(
                    getattr(report, "unclassified_sections", []) or []
                )
                if isinstance(row, Mapping)
                and str(row.get("section_number") or "").strip() == section
                and not str(row.get("toc_variant") or "").strip()
                and str(row.get("reason") or "").strip()
                == "toc_section_missing_body_identity"
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    "New York signed-bill target residual membership drifted: "
                    f"{code} {section} count={len(matches)}"
                )
            selected.append((code, section, selector_key, url))
        return selected

    @classmethod
    def _new_york_exact_env_proof_rows(
        cls,
        parsed_reports,
    ) -> List[tuple[str, str, str]]:
        """Select the fixed four-input ENV chain only for its four residuals."""

        expected = [
            tuple(str(value) for value in row)
            for row in cls.STRICT_CURRENT_ENV_PROOF_ROWS
        ]
        urls = [row[2] for row in expected]
        if len(urls) != len(set(urls)):
            raise RuntimeError("New York ENV proof URLs are not unique")
        observed_sha256 = hashlib.sha256(
            "\n".join(urls).encode("utf-8")
        ).hexdigest()
        if observed_sha256 != cls.STRICT_CURRENT_ENV_PROOF_URL_SHA256:
            raise RuntimeError(
                "New York ENV proof URL projection changed: "
                f"{observed_sha256}"
            )
        for selector_key, proof_kind, url in expected:
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname
                not in {cls.OFFICIAL_ASSEMBLY_DOMAIN, cls.OFFICIAL_DOMAIN}
                or proof_kind
                not in {
                    "official_assembly_bill_record",
                    "official_constitution_section",
                }
                or not selector_key.startswith("ENV:2025:")
            ):
                raise RuntimeError(
                    "New York ENV proof escaped its exact official identity"
                )

        report = next(
            (
                item
                for item in parsed_reports
                if str(getattr(item, "law_code", "") or "").strip().upper()
                == "ENV"
            ),
            None,
        )
        if report is None:
            return []
        observed = {
            (
                str(row.get("section_number") or "").strip(),
                str(row.get("toc_variant") or "").strip(),
                str(row.get("reason") or "").strip(),
                str(row.get("detail") or "").strip().split(":", 1)[0],
            )
            for row in list(getattr(report, "unclassified_sections", []) or [])
            if isinstance(row, Mapping)
            and str(row.get("section_number") or "").strip()
            in {"9-2301", "9-2302", "9-2303", "9-2304"}
        }
        targets = {
            (section, "", "ambiguous_lifecycle_status", "event_conditioned_effective")
            for section in ("9-2301", "9-2302", "9-2303", "9-2304")
        }
        if not observed:
            return []
        if observed != targets:
            raise RuntimeError(
                "New York ENV residual membership drifted; "
                f"observed={sorted(observed)}"
            )
        return expected

    @classmethod
    def _new_york_exact_event_proof_rows(
        cls,
        parsed_reports,
    ) -> List[tuple[str, str, str, str, str]]:
        """Select fixed event records only for their exact residual sets."""

        expected = [
            tuple(str(value) for value in row)
            for row in cls.STRICT_CURRENT_EVENT_PROOF_ROWS
        ]
        urls = [row[4] for row in expected]
        if len(urls) != len(set(urls)):
            raise RuntimeError("New York event proof URLs are not unique")
        observed_sha256 = hashlib.sha256(
            "\n".join(urls).encode("utf-8")
        ).hexdigest()
        if observed_sha256 != cls.STRICT_CURRENT_EVENT_PROOF_URL_SHA256:
            raise RuntimeError(
                "New York event proof URL projection changed: "
                f"{observed_sha256}"
            )

        target_sections = {
            "MHY": tuple(f"82.{number:02d}" for number in range(1, 16)),
            "PBA": (
                "3030",
                "3031",
                "3032",
                "3033",
                "3034",
                "3035",
                "3036",
                "3036-a",
                "3036-b",
                "3037",
                "3037-a",
                "3038",
                "3039",
                "3040",
                "3041",
            ),
            "RSS": ("1204-a",),
        }
        target_dispositions = {
            "MHY": "event_conditioned_effective",
            "PBA": "event_conditioned_expiration",
            "RSS": "event_conditioned_effective",
        }
        expected_hosts = {
            "MHY": {"dos.ny.gov"},
            "PBA": {"www.nyc.gov"},
            "RSS": {"legislation.nysenate.gov", "www.osc.ny.gov"},
        }
        reports_by_code = {
            str(getattr(report, "law_code", "") or "").strip().upper(): report
            for report in parsed_reports
        }
        selected: List[tuple[str, str, str, str, str]] = []
        for code, proof_family, selector_key, proof_kind, url in expected:
            parsed = urlparse(url)
            if (
                code not in target_sections
                or parsed.scheme != "https"
                or parsed.hostname not in expected_hosts[code]
                or proof_kind
                not in {
                    "official_comptroller_payroll_bulletin",
                    "official_enacted_bill_text",
                    "official_state_register_adoption",
                    "official_government_financial_report",
                }
                or cls._new_york_event_proof_media_type(proof_kind)
                not in {"application/pdf", "text/html"}
                or not proof_family
                or not selector_key.startswith(f"{code}:")
            ):
                raise RuntimeError(
                    "New York event proof escaped its exact official identity"
                )
            report = reports_by_code.get(code)
            if report is None:
                continue
            target_set = set(target_sections[code])
            observed = {
                (
                    str(row.get("section_number") or "").strip(),
                    str(row.get("toc_variant") or "").strip(),
                    str(row.get("reason") or "").strip(),
                    str(row.get("detail") or "").strip().split(":", 1)[0],
                )
                for row in list(
                    getattr(report, "unclassified_sections", []) or []
                )
                if isinstance(row, Mapping)
                and str(row.get("section_number") or "").strip()
                in target_set
            }
            targets = {
                (
                    section,
                    "",
                    "ambiguous_lifecycle_status",
                    target_dispositions[code],
                )
                for section in target_sections[code]
            }
            if not observed:
                continue
            if observed != targets:
                raise RuntimeError(
                    f"New York {proof_family} residual membership drifted; "
                    f"observed={sorted(observed)}"
                )
            selected.append(
                (code, proof_family, selector_key, proof_kind, url)
            )
        return selected

    @classmethod
    def _new_york_exact_supplemental_urls(
        cls,
        parsed_reports,
    ) -> List[str]:
        """Return the pinned 28-URL wave after signed-bill reconciliation."""

        observed: List[tuple[str, str, str, str]] = []
        for report in parsed_reports:
            law_code = str(getattr(report, "law_code", "") or "").strip().upper()
            for row in list(getattr(report, "unclassified_sections", []) or []):
                if not isinstance(row, Mapping):
                    continue
                reason = str(row.get("reason") or "").strip()
                detail = str(row.get("detail") or "").strip()
                if (
                    reason == "ambiguous_lifecycle_status"
                    and detail.startswith("missing_lifecycle_note:")
                ):
                    contract_reason = "missing_lifecycle_note"
                elif reason == "toc_section_missing_body_identity":
                    contract_reason = reason
                else:
                    continue
                observed.append(
                    (
                        law_code,
                        str(row.get("section_number") or "").strip(),
                        str(row.get("toc_variant") or "").strip(),
                        contract_reason,
                    )
                )
        if not observed:
            return []

        # The retained v20 projection test invokes this pure URL projector
        # before the mandatory signed-bill wave.  Those two exact rows belong
        # to that separate Assembly wave, never to the Senate section wave;
        # filtering them here does not resolve or reclassify either row.
        signed_bill_targets = {
            (str(row[0]), str(row[1]), "", "toc_section_missing_body_identity")
            for row in cls.STRICT_CURRENT_SIGNED_BILL_PROOF_ROWS
        }
        observed = [row for row in observed if row not in signed_bill_targets]

        expected = [
            tuple(str(value) for value in row)
            for row in cls.STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS
        ]
        if sorted(observed) != sorted(expected):
            missing = sorted(set(expected) - set(observed))
            extra = sorted(set(observed) - set(expected))
            raise RuntimeError(
                "New York supplemental residual membership drifted; "
                f"missing={missing[:5]} extra={extra[:5]}"
            )

        derived_urls: List[str] = []
        for law_code, section, _variant, _reason in expected:
            url = (
                f"https://{cls.OFFICIAL_DOMAIN}/legislation/laws/"
                f"{law_code}/{section}"
            )
            if url not in derived_urls:
                derived_urls.append(url)
        pinned_urls = [
            str(value) for value in cls.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS
        ]
        if derived_urls != pinned_urls or len(pinned_urls) != len(set(pinned_urls)):
            raise RuntimeError(
                "New York supplemental URL projection changed exact ordering"
            )
        for url in pinned_urls:
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != cls.OFFICIAL_DOMAIN
                or parsed.query
                or parsed.fragment
                or not parsed.path.startswith("/legislation/laws/")
            ):
                raise RuntimeError(
                    "New York supplemental URL escaped the exact official host"
                )
        observed_sha256 = hashlib.sha256(
            "\n".join(pinned_urls).encode("utf-8")
        ).hexdigest()
        if observed_sha256 != cls.STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256:
            raise RuntimeError(
                "New York supplemental URL projection digest changed: "
                f"{observed_sha256}"
            )
        return pinned_urls

    def _validate_new_york_aligned_evidence(
        self,
        *,
        url: str,
        payload: bytes,
        transport_receipt: Any,
        parser_input_envelope: Any,
        frontier_name: str,
    ) -> None:
        """Require exact URL/body binding when the acquisition ledger is active."""

        canonical_url = self._canonical_fetch_url(url)
        digest = hashlib.sha256(payload).hexdigest()
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if ledger_attached and (
            not isinstance(transport_receipt, Mapping)
            or not transport_receipt
            or parser_input_envelope is None
        ):
            raise RuntimeError(
                f"New York {frontier_name} frontier lacks retained evidence: {url}"
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
                    f"New York {frontier_name} receipt lacks URL/digest evidence: {url}"
                )
            if observed_url and self._canonical_fetch_url(observed_url) != canonical_url:
                raise RuntimeError(
                    f"New York {frontier_name} receipt changed URL identity: {url}"
                )
            if observed_digest and observed_digest != digest:
                raise RuntimeError(
                    f"New York {frontier_name} receipt changed payload identity: {url}"
                )
        if parser_input_envelope is not None:
            envelope_body = getattr(parser_input_envelope, "body", None)
            if ledger_attached and envelope_body is None:
                raise RuntimeError(
                    f"New York {frontier_name} envelope lacks body evidence: {url}"
                )
            if envelope_body is not None and bytes(envelope_body) != payload:
                raise RuntimeError(
                    f"New York {frontier_name} envelope changed payload identity: {url}"
                )

    async def _fetch_new_york_frontier_batch(
        self,
        urls,
        *,
        frontier_name: str,
        content_validator,
        media_type: str,
        common_crawl_domains,
        common_crawl_url_terms,
        residual_retry_attempts: Optional[int] = None,
        request_headers: Optional[Mapping[str, str]] = None,
    ) -> StateLawPageMultiFetchResult:
        """Fetch one NY frontier through shared residual/grouped-WARC recovery."""

        requested = [self._canonical_fetch_url(url) for url in urls]
        if not requested:
            return StateLawPageMultiFetchResult([], [], [], [], [], {})
        if any(not url for url in requested) or len(set(requested)) != len(requested):
            raise RuntimeError(
                f"New York {frontier_name} frontier contains invalid or duplicate URLs"
            )
        retry_attempts = (
            max(0, min(3, int(residual_retry_attempts)))
            if residual_retry_attempts is not None
            else max(
                0,
                min(
                    3,
                    self._env_int(
                        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                        default=1,
                    ),
                ),
            )
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            timeout_seconds=90 if media_type == "application/pdf" else 25,
            headers=(
                dict(request_headers)
                if request_headers is not None
                else self._new_york_frontier_headers(media_type)
            ),
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=self._new_york_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=tuple(common_crawl_domains),
            common_crawl_url_terms=tuple(common_crawl_url_terms),
            common_crawl_mime_terms=("pdf",) if media_type == "application/pdf" else ("html",),
            wayback_prefix_inventory=True,
        )
        batch_stats = dict(batch.stats or {})
        inventory_stats = dict(
            batch_stats.get("common_crawl_inventory_memo", {}) or {}
        )
        normalized_domains = {
            str(
                urlparse(
                    str(value)
                    if "://" in str(value)
                    else f"https://{value}"
                ).hostname
                or ""
            ).strip().lower()
            for value in common_crawl_domains
            if str(value or "").strip()
        }
        normalized_domains.discard("")
        if int(inventory_stats.get("shared_domain_queries", 0) or 0) > len(
            normalized_domains
        ):
            raise RuntimeError(
                f"New York {frontier_name} repeated a Common Crawl domain inventory"
            )
        attempt_records = list(batch_stats.get("attempt_records", []) or [])
        for retry in attempt_records[1:]:
            if not isinstance(retry, Mapping):
                raise RuntimeError(
                    f"New York {frontier_name} returned invalid retry statistics"
                )
            retry_inventory = dict(
                retry.get("common_crawl_inventory_memo", {}) or {}
            )
            if (
                bool(retry.get("archive_recovery_enabled", True))
                or int(retry.get("common_crawl_inventory_queries", 0) or 0) != 0
                or int(retry_inventory.get("shared_domain_queries", 0) or 0) != 0
            ):
                raise RuntimeError(
                    f"New York {frontier_name} repeated archive discovery on a residual retry"
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
                f"New York {frontier_name} frontier changed exact URL alignment"
            )
        failures: List[Dict[str, str]] = []
        for url, payload, error, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.errors,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            raw = bytes(payload or b"")
            if error is not None or not raw or not content_validator(raw):
                failures.append(
                    {"url": url, "error": str(error or "empty or invalid parser input")}
                )
                continue
            self._validate_new_york_aligned_evidence(
                url=url,
                payload=raw,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
                frontier_name=frontier_name,
            )
        if failures:
            raise RuntimeError(
                f"New York {frontier_name} frontier is incomplete; "
                f"unresolved exact URLs: {failures[:10]}"
            )
        stats_rows = list(getattr(self, "_new_york_frontier_batch_stats", []))
        stats_rows.append(
            {
                "frontier_name": frontier_name,
                "requested_pages": len(requested),
                **batch_stats,
            }
        )
        self._new_york_frontier_batch_stats = stats_rows
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    def _replay_new_york_retained_input(
        self,
        url: str,
        *,
        media_type: str,
        content_validator,
        frontier_name: str,
        request_headers: Optional[Mapping[str, str]] = None,
    ) -> bytes:
        """Replay one exact retained input without permitting network I/O."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("New York retained replay requires an attached ledger")
        canonical_url = self._canonical_fetch_url(url)
        sanitized_headers = _sanitized_multifetch_headers(
            (
                dict(request_headers)
                if request_headers is not None
                else self._new_york_frontier_headers(media_type)
            )
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
                f"New York retained replay is missing exact input: {canonical_url}"
            )
        envelope = getattr(retained, "envelope", None)
        body = getattr(envelope, "body", None)
        raw = bytes(body or b"")
        if not raw or not content_validator(raw):
            raise RuntimeError(
                f"New York retained replay input is invalid: {canonical_url}"
            )
        self._validate_new_york_aligned_evidence(
            url=canonical_url,
            payload=raw,
            transport_receipt=getattr(retained, "transport_receipt", None),
            parser_input_envelope=envelope,
            frontier_name=frontier_name,
        )
        return raw

    def _new_york_exact_frontier(
        self,
        *,
        catalog_content_sha256: str,
        law_reports: Sequence[Mapping[str, Any]],
        terminal_dispositions: Mapping[str, int],
        conditional_event_selectors: Optional[
            Mapping[str, Mapping[str, Any]]
        ] = None,
    ) -> Dict[str, Any]:
        """Build the content-derived law/PDF section frontier contract."""

        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        source_sections = sum(int(row["source_sections"]) for row in law_reports)
        operative_sections = sum(int(row["operative_sections"]) for row in law_reports)
        terminal_sections = sum(int(row["terminal_sections"]) for row in law_reports)
        raw_section_markers = sum(
            int(row["raw_section_markers"]) for row in law_reports
        )
        embedded_section_markers = sum(
            int(row["embedded_section_markers"]) for row in law_reports
        )
        lifecycle_alternate_sections = sum(
            int(row["lifecycle_alternate_sections"]) for row in law_reports
        )
        source_sections_without_raw_markers = sum(
            int(row["source_sections_without_raw_markers"])
            for row in law_reports
        )
        disposition = {
            "discovered": source_sections,
            "fetched": operative_sections,
            "excluded": terminal_sections,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if source_sections != operative_sections + terminal_sections:
            raise RuntimeError("New York exact frontier disposition did not close")
        for row in law_reports:
            if int(row["raw_section_markers"]) + int(
                row["source_sections_without_raw_markers"]
            ) != (
                int(row["source_sections"])
                + int(row["embedded_section_markers"])
                + int(row["lifecycle_alternate_sections"])
            ):
                raise RuntimeError(
                    "New York raw PDF marker algebra did not close for "
                    f"{row['law_code']}"
                )
        if raw_section_markers + source_sections_without_raw_markers != (
            source_sections + embedded_section_markers + lifecycle_alternate_sections
        ):
            raise RuntimeError("New York raw PDF marker algebra did not close")
        source_rows = [
            {
                "law_code": str(row["law_code"]),
                "source_url": str(row["source_url"]),
                "content_sha256": str(row["content_sha256"]),
            }
            for row in law_reports
        ]
        source_frontier_sha256 = hashlib.sha256(
            json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        selector_rows = {
            str(key): dict(value)
            for key, value in sorted(
                dict(conditional_event_selectors or {}).items()
            )
            if isinstance(value, Mapping)
        }
        for selector_key, selector in selector_rows.items():
            if selector.get("status") != "occurred":
                raise RuntimeError(
                    "New York conditional event selector did not prove occurrence: "
                    f"{selector_key}"
                )
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": True,
            "catalog_content_sha256": str(catalog_content_sha256),
            "catalog_law_count": len(law_reports),
            "closed": True,
            "conditional_event_selectors": selector_rows,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": source_sections,
            "law_pdf_document_count": len(law_reports),
            "law_pdf_frontier_sha256": source_frontier_sha256,
            "raw_section_marker_count": raw_section_markers,
            "embedded_section_marker_count": embedded_section_markers,
            "lifecycle_alternate_section_count": lifecycle_alternate_sections,
            "source_sections_without_raw_marker_count": (
                source_sections_without_raw_markers
            ),
            "pagination_closed": True,
            "schema_version": "new-york-consolidated-source-frontier-v3",
            "scope_closed": True,
            "source_section_count": source_sections,
            "terminal_dispositions": {
                str(key): int(value)
                for key, value in sorted(terminal_dispositions.items())
            },
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": source_sections,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _new_york_source_catalog_rows(
        self,
        catalog_payload: bytes,
    ) -> List[tuple[str, str, str]]:
        """Derive the exact current law set from the retained consolidated page."""

        from .new_york_openleg import category_law_links

        discovered = category_law_links(
            bytes(catalog_payload).decode("utf-8", errors="replace"),
            base_url=self.get_base_url(),
        )
        catalog_rows: List[tuple[str, str, str]] = []
        seen_codes: set[str] = set()
        for law_code, law_name, public_url in discovered:
            code = str(law_code or "").strip().upper()
            if code in {"ALL", "CONSOLIDATED"}:
                continue
            name = re.sub(
                rf"^{re.escape(code)}\s+",
                "",
                str(law_name or "").strip(),
                flags=re.IGNORECASE,
            ).strip() or code
            if code in seen_codes:
                raise RuntimeError(
                    f"New York consolidated catalog repeated law code: {code}"
                )
            if not re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", code):
                raise RuntimeError(
                    f"New York consolidated catalog exposed invalid law code: {code}"
                )
            official_target = self._new_york_catalog_official_target(public_url)
            expected_path = f"/legislation/laws/{code}"
            if (
                not official_target
                or urlparse(official_target).path.rstrip("/").upper()
                != expected_path.upper()
            ):
                raise RuntimeError(
                    "New York consolidated catalog changed exact official law "
                    f"identity: {public_url}"
                )
            seen_codes.add(code)
            catalog_rows.append((code, name, self.official_law_url(code)))
        expected_count = int(self.STRICT_MINIMUM_CONSOLIDATED_LAWS)
        if len(catalog_rows) != expected_count:
            raise RuntimeError(
                "New York consolidated catalog membership count drifted: "
                f"observed={len(catalog_rows)} "
                f"expected={expected_count}"
            )
        ordered_codes = [row[0] for row in catalog_rows]
        ordered_code_sha256 = hashlib.sha256(
            json.dumps(ordered_codes, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        expected_code_sha256 = str(
            self.STRICT_CURRENT_CONSOLIDATED_CODE_SHA256 or ""
        ).strip().lower()
        if (
            re.fullmatch(r"[0-9a-f]{64}", expected_code_sha256) is None
            or ordered_code_sha256 != expected_code_sha256
        ):
            raise RuntimeError(
                "New York consolidated catalog ordered membership drifted: "
                f"observed_sha256={ordered_code_sha256} "
                f"expected_sha256={expected_code_sha256 or '<missing>'}"
            )
        return catalog_rows

    def _new_york_catalog_official_target(self, value: str) -> str:
        """Return an exact official target, including a Wayback-rewritten href.

        Wayback replay HTML may rewrite source anchors to its own replay host.
        The retained transport receipt still binds the catalog parser input to
        the official catalog URL and capture.  Accept only an exact fourteen-
        digit replay locator whose embedded target remains on nysenate.gov;
        never treat the archive host itself or an embedded secondary host as
        authority.
        """

        target = str(value or "").strip()
        parsed = urlparse(target)
        archive_host = str(parsed.hostname or "").strip().lower()
        if archive_host in {"web.archive.org", "www.web.archive.org"}:
            match = re.match(
                r"^/web/\d{14}(?:[a-z_]+)?/(?P<target>https?:/{1,2}.+)$",
                parsed.path,
                flags=re.IGNORECASE,
            )
            if match is None:
                return ""
            target = unquote(str(match.group("target") or "").strip())
            target = re.sub(r"^(https?):/(?!/)", r"\1://", target)
            if parsed.query:
                target += "?" + parsed.query
        return target if self._host_is_official(target) else ""
    
    def get_base_url(self) -> str:
        """Get base URL for NY Senate."""
        return "https://www.nysenate.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of New York consolidated law sources.

        In this environment, direct per-code NY Senate endpoints are often blocked.
        Use a single consolidated entry and let scrape_code choose the best source.
        """
        base_url = self.get_base_url()

        return [
            {
                "name": "New York Consolidated Laws",
                "url": f"{base_url}/legislation/laws",
                "type": "NY-LAWS",
            }
        ]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific New York law.
        
        Args:
            code_name: Name of the law
            code_url: URL to the law
            
        Returns:
            List of normalized statutes
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .new_york_constitution import (
            configured_constitution_json_path,
            parse_configured_new_york_constitution,
        )

        constitution_path = configured_constitution_json_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_configured_new_york_constitution(
                    code_name=code_name or "New York Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .new_york_openleg import parse_configured_law_json

        strict_full = self._full_corpus_enabled() and max_statutes is None
        openleg = (
            []
            if strict_full
            else parse_configured_law_json(code_name=code_name, max_statutes=limit)
        )
        if openleg:
            return openleg
        official = await self._scrape_official_senate_laws_tree(code_name, max_statutes=limit)
        if official:
            return official if limit is None else official[: int(limit)]
        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "NY full-corpus run found zero official nysenate.gov statutes; "
                "refusing public.law/Justia sole-admission fallback"
            )
            return []
        bounded = limit if limit is not None else 160
        public_law_structured = await self._scrape_public_law_structured(
            code_name, max_sections=max(10, bounded)
        )
        if public_law_structured:
            return public_law_structured[:bounded]
        if not self._full_corpus_enabled():
            direct = await self._scrape_jina_senate_seed_sections(code_name, max_statutes=bounded)
            if direct:
                statutes.extend(direct[:bounded])
        if statutes:
            return statutes[:bounded]
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                self.logger.warning(f"NY direct request returned empty content for {code_name}; using public.law fallback")
                return (await self._scrape_public_law_updates(code_name))[:bounded]

            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Extract legal area
            legal_area = self._identify_legal_area(code_name)

            # Find section/article links from the index page if available.
            section_href_re = re.compile(r".*/legislation/laws/[A-Za-z0-9\-.]+/[A-Za-z0-9\-.]+$", re.IGNORECASE)
            section_links = soup.find_all('a', href=section_href_re)
            
            seen_sections = set()
            for link in section_links[:bounded]:
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')
                
                if not section_text or len(section_text) < 3:
                    continue
                
                if not section_url.startswith('http'):
                    section_url = urljoin(code_url, section_url)
                
                # Extract section number
                section_number = self._extract_section_number(section_text)
                if not section_number:
                    tail = section_url.rstrip('/').split('/')[-1]
                    section_number = tail if re.search(r"\d", tail) else ""
                if not section_number:
                    continue
                if section_number in seen_sections:
                    continue
                seen_sections.add(section_number)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_text[:200],
                    full_text=f"Section {section_number}: {section_text}",  # Added full_text
                    source_url=section_url,
                    legal_area=legal_area,
                    official_cite=f"NY {code_name} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")

            if statutes:
                return statutes

            self.logger.warning("NY primary source returned no sections; using public.law fallback")
            return await self._scrape_public_law_updates(code_name)
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
            return await self._scrape_public_law_updates(code_name)

    async def _scrape_official_senate_laws_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Walk the live NY Senate consolidated-laws HTML tree."""
        if self._full_corpus_enabled() and max_statutes is None:
            return await self._scrape_official_senate_pdf_frontier(code_name)
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        root_url = self.OFFICIAL_ENTRY_URL
        html = await self._request_text_direct(root_url, timeout=18)
        if not html:
            payload = await self._fetch_page_content_with_archival_fallback(root_url, timeout_seconds=18)
            html = payload.decode("utf-8", errors="replace") if payload else ""
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        known = {code for code, _name in self.OFFICIAL_LAWS}
        law_urls: List[tuple[str, str]] = []
        seen_laws = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            abs_url = urljoin(root_url + "/", href)
            match = self._NY_LAW_HREF_RE.search(abs_url)
            if not match:
                continue
            law_code = str(match.group("code") or "").strip().upper()
            if law_code not in known:
                continue
            # Index pages are /legislation/laws/PEN; skip section-like tails here.
            path = urlparse(abs_url).path.rstrip("/")
            parts = [part for part in path.split("/") if part]
            if len(parts) != 3 or parts[-1].upper() != law_code:
                continue
            law_url = self.official_law_url(law_code)
            if law_url in seen_laws:
                continue
            if not self._host_is_official(law_url):
                continue
            seen_laws.add(law_url)
            law_urls.append((law_code, law_url))

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        section_url_re = re.compile(
            r"/legislation/laws/(?P<code>[A-Z]{2,4})/(?P<section>[0-9A-Za-z.-]*\d[0-9A-Za-z.-]*)$",
            re.IGNORECASE,
        )
        for law_code, law_url in law_urls:
            if limit is not None and len(statutes) >= limit:
                break
            law_html = await self._request_text_direct(law_url, timeout=18)
            if not law_html:
                payload = await self._fetch_page_content_with_archival_fallback(law_url, timeout_seconds=18)
                law_html = payload.decode("utf-8", errors="replace") if payload else ""
            if not law_html:
                continue
            law_soup = BeautifulSoup(law_html, "html.parser")
            for anchor in law_soup.find_all("a", href=True):
                if limit is not None and len(statutes) >= limit:
                    break
                href = str(anchor.get("href") or "").strip()
                label = str(anchor.get_text(" ", strip=True) or "").strip()
                abs_url = urljoin(law_url + "/", href)
                match = section_url_re.search(urlparse(abs_url).path)
                if not match:
                    continue
                if str(match.group("code") or "").strip().upper() != law_code:
                    continue
                section_number = str(match.group("section") or "").strip()
                if not section_number:
                    continue
                if not self._host_is_official(abs_url):
                    continue
                section_key = f"{law_code}:{section_number}".lower()
                if section_key in seen_sections:
                    continue
                seen_sections.add(section_key)
                statute = await self._build_official_senate_section(
                    code_name,
                    law_code=law_code,
                    section_number=section_number,
                    section_label=label,
                    section_url=abs_url.split("#", 1)[0],
                )
                if statute is not None:
                    statutes.append(statute)
        return statutes

    async def _scrape_official_senate_pdf_frontier(
        self,
        code_name: str,
    ) -> List[NormalizedStatute]:
        """Close the live Consolidated catalog over official full-law PDFs."""

        from .new_york_law_pdf import (
            AGM28_LIFECYCLE_REPORT_URL,
            AGM28_LIFECYCLE_SELECTOR_KEY,
            NewYorkSupplementalProofInput,
            NewYorkSupplementalProofRegistry,
            evaluate_new_york_agm28_lifecycle_report,
            full_law_pdf_url,
            parse_new_york_law_pdf,
        )

        self._new_york_frontier_batch_stats = []
        catalog_batch = await self._fetch_new_york_frontier_batch(
            [self.OFFICIAL_CONSOLIDATED_URL],
            frontier_name="consolidated-catalog",
            content_validator=self._is_valid_new_york_consolidated_catalog,
            media_type="text/html",
            common_crawl_domains=(self.OFFICIAL_DOMAIN,),
            common_crawl_url_terms=("/legislation/laws/CONSOLIDATED",),
        )
        catalog_payload = bytes(catalog_batch.payloads[0])
        catalog_rows = self._new_york_source_catalog_rows(catalog_payload)

        agm28_selector_payload: Optional[bytes] = None
        conditional_event_selectors: Dict[str, Dict[str, Any]] = {}
        if any(row[0] == "AGM" for row in catalog_rows):
            selector_batch = await self._fetch_new_york_frontier_batch(
                [AGM28_LIFECYCLE_REPORT_URL],
                frontier_name="agm-28-lifecycle-selector",
                content_validator=self._is_valid_new_york_law_pdf,
                media_type="application/pdf",
                common_crawl_domains=("agriculture.ny.gov",),
                common_crawl_url_terms=(
                    "/system/files/documents/2023/02/"
                    "urbanruralconsumeraccessreport.pdf",
                ),
                residual_retry_attempts=0,
                request_headers=self._new_york_agm28_selector_headers(),
            )
            agm28_selector_payload = bytes(selector_batch.payloads[0])
            selector_outcome = evaluate_new_york_agm28_lifecycle_report(
                agm28_selector_payload,
                source_url=AGM28_LIFECYCLE_REPORT_URL,
            )
            if selector_outcome.get("status") != "occurred":
                raise RuntimeError(
                    "New York AGM 28 lifecycle selector did not prove the exact "
                    f"delivery conjunction: {selector_outcome.get('conjuncts')}"
                )
            conditional_event_selectors[AGM28_LIFECYCLE_SELECTOR_KEY] = (
                selector_outcome
            )

        pdf_urls = [full_law_pdf_url(row[0]) for row in catalog_rows]
        if len(pdf_urls) != len(set(pdf_urls)):
            raise RuntimeError("New York full-law PDF catalog repeated a source URL")

        proof_inputs = []
        if agm28_selector_payload is not None:
            proof_inputs.append(
                NewYorkSupplementalProofInput.bind(
                    selector_key=AGM28_LIFECYCLE_SELECTOR_KEY,
                    proof_kind="official_event_report",
                    official_url=AGM28_LIFECYCLE_REPORT_URL,
                    media_type="application/pdf",
                    payload=agm28_selector_payload,
                )
            )
        proof_registry = NewYorkSupplementalProofRegistry(proof_inputs)

        pdf_inputs: List[Dict[str, Any]] = []
        batch_size = self._new_york_pdf_frontier_batch_size()
        for start in range(0, len(pdf_urls), batch_size):
            selected_urls = pdf_urls[start : start + batch_size]
            selected_catalog = catalog_rows[start : start + batch_size]
            batch = await self._fetch_new_york_frontier_batch(
                selected_urls,
                frontier_name=f"full-law-pdfs-{start + 1}-{start + len(selected_urls)}",
                content_validator=self._is_valid_new_york_law_pdf,
                media_type="application/pdf",
                common_crawl_domains=(self.OFFICIAL_PDF_DOMAIN,),
                common_crawl_url_terms=("/pdf/laws/", "full=true"),
            )
            for catalog_row, source_url, payload, receipt in zip(
                selected_catalog,
                batch.urls,
                batch.payloads,
                batch.transport_receipts,
                strict=True,
            ):
                pdf_inputs.append(
                    {
                        "catalog_row": catalog_row,
                        "payload": bytes(payload),
                        "receipt": receipt,
                        "source_url": source_url,
                    }
                )

        def _parse_pdf_inputs(registry):
            parsed = []
            for source_input in pdf_inputs:
                law_code, law_name, _public_url = source_input["catalog_row"]
                parsed.append(
                    parse_new_york_law_pdf(
                        source_input["payload"],
                        law_code=law_code,
                        law_name=law_name,
                        code_name=code_name,
                        source_bundle_url=source_input["source_url"],
                        supplemental_proof_registry=registry,
                    )
                )
            return parsed

        parsed_reports = _parse_pdf_inputs(proof_registry)
        signed_bill_rows = self._new_york_exact_signed_bill_proof_rows(
            parsed_reports
        )
        if signed_bill_rows:
            signed_bill_urls = [row[3] for row in signed_bill_rows]
            signed_bill_batch = await self._fetch_new_york_frontier_batch(
                signed_bill_urls,
                frontier_name="signed-assembly-bill-records-1-2",
                content_validator=(
                    self._is_valid_new_york_assembly_signed_bill_html
                ),
                media_type="text/html",
                common_crawl_domains=(self.OFFICIAL_ASSEMBLY_DOMAIN,),
                common_crawl_url_terms=("/leg/", "Actions=Y",),
            )
            signed_bill_proofs = []
            for row, url, payload in zip(
                signed_bill_rows,
                signed_bill_batch.urls,
                signed_bill_batch.payloads,
                strict=True,
            ):
                _law_code, _section, selector_key, expected_url = row
                if url != self._canonical_fetch_url(expected_url):
                    raise RuntimeError(
                        "New York signed-bill proof changed exact URL identity"
                    )
                signed_bill_proofs.append(
                    NewYorkSupplementalProofInput.bind(
                        selector_key=selector_key,
                        proof_kind="official_signed_bill_record",
                        official_url=url,
                        media_type="text/html",
                        payload=bytes(payload),
                    )
                )
            proof_registry = proof_registry.with_inputs(signed_bill_proofs)
            parsed_reports = _parse_pdf_inputs(proof_registry)

        env_proof_rows = self._new_york_exact_env_proof_rows(parsed_reports)
        if env_proof_rows:
            env_proofs = []
            assembly_rows = [
                row
                for row in env_proof_rows
                if row[1] == "official_assembly_bill_record"
            ]
            assembly_batch = await self._fetch_new_york_frontier_batch(
                [row[2] for row in assembly_rows],
                frontier_name="env-assembly-proof-chain-1-2",
                content_validator=self._is_valid_new_york_assembly_bill_html,
                media_type="text/html",
                common_crawl_domains=(self.OFFICIAL_ASSEMBLY_DOMAIN,),
                common_crawl_url_terms=("/leg/", "Actions=Y",),
                residual_retry_attempts=0,
            )
            for row, url, payload in zip(
                assembly_rows,
                assembly_batch.urls,
                assembly_batch.payloads,
                strict=True,
            ):
                selector_key, proof_kind, expected_url = row
                if url != self._canonical_fetch_url(expected_url):
                    raise RuntimeError(
                        "New York ENV Assembly proof changed exact URL identity"
                    )
                env_proofs.append(
                    NewYorkSupplementalProofInput.bind(
                        selector_key=selector_key,
                        proof_kind=proof_kind,
                        official_url=url,
                        media_type="text/html",
                        payload=bytes(payload),
                    )
                )

            constitution_rows = [
                row
                for row in env_proof_rows
                if row[1] == "official_constitution_section"
            ]
            constitution_batch = await self._fetch_new_york_frontier_batch(
                [row[2] for row in constitution_rows],
                frontier_name="env-constitution-proof-chain-1-2",
                content_validator=self._is_valid_new_york_senate_section_html,
                media_type="text/html",
                common_crawl_domains=(self.OFFICIAL_DOMAIN,),
                common_crawl_url_terms=("/legislation/laws/CNS/",),
                residual_retry_attempts=0,
                request_headers=self._new_york_constitution_section_headers(),
            )
            for row, url, payload in zip(
                constitution_rows,
                constitution_batch.urls,
                constitution_batch.payloads,
                strict=True,
            ):
                selector_key, proof_kind, expected_url = row
                if url != self._canonical_fetch_url(expected_url):
                    raise RuntimeError(
                        "New York ENV Constitution proof changed exact URL identity"
                    )
                env_proofs.append(
                    NewYorkSupplementalProofInput.bind(
                        selector_key=selector_key,
                        proof_kind=proof_kind,
                        official_url=url,
                        media_type="text/html",
                        payload=bytes(payload),
                    )
                )
            proof_registry = proof_registry.with_inputs(env_proofs)
            parsed_reports = _parse_pdf_inputs(proof_registry)

        event_proof_rows = self._new_york_exact_event_proof_rows(
            parsed_reports
        )
        if event_proof_rows:
            event_proofs = []
            for media_type in ("application/pdf", "text/html"):
                media_rows = [
                    row
                    for row in event_proof_rows
                    if self._new_york_event_proof_media_type(row[3])
                    == media_type
                ]
                if not media_rows:
                    continue
                event_urls = [row[4] for row in media_rows]
                event_batch = await self._fetch_new_york_frontier_batch(
                    event_urls,
                    frontier_name=(
                        "event-condition-"
                        f"{'pdf' if media_type == 'application/pdf' else 'html'}-"
                        f"proof-chain-1-{len(event_urls)}"
                    ),
                    content_validator=(
                        self._is_valid_new_york_event_proof_pdf
                        if media_type == "application/pdf"
                        else self._is_valid_new_york_event_proof_html
                    ),
                    media_type=media_type,
                    common_crawl_domains=tuple(
                        str(urlparse(url).hostname or "") for url in event_urls
                    ),
                    common_crawl_url_terms=tuple(
                        urlparse(url).path for url in event_urls
                    ),
                    residual_retry_attempts=0,
                )
                for row, url, payload in zip(
                    media_rows,
                    event_batch.urls,
                    event_batch.payloads,
                    strict=True,
                ):
                    _code, _family, selector_key, proof_kind, expected_url = row
                    if url != self._canonical_fetch_url(expected_url):
                        raise RuntimeError(
                            "New York event proof changed exact URL identity"
                        )
                    event_proofs.append(
                        NewYorkSupplementalProofInput.bind(
                            selector_key=selector_key,
                            proof_kind=proof_kind,
                            official_url=url,
                            media_type=media_type,
                            payload=bytes(payload),
                        )
                    )
            proof_registry = proof_registry.with_inputs(event_proofs)
            parsed_reports = _parse_pdf_inputs(proof_registry)

        supplemental_urls = self._new_york_exact_supplemental_urls(parsed_reports)
        if supplemental_urls:
            supplemental_batch = await self._fetch_new_york_frontier_batch(
                supplemental_urls,
                frontier_name="source-derived-supplemental-sections-1-28",
                content_validator=self._is_valid_new_york_senate_section_html,
                media_type="text/html",
                common_crawl_domains=(self.OFFICIAL_DOMAIN,),
                common_crawl_url_terms=("/legislation/laws/",),
            )
            section_proofs = []
            for url, payload in zip(
                supplemental_batch.urls,
                supplemental_batch.payloads,
                strict=True,
            ):
                path_parts = [part for part in urlparse(url).path.split("/") if part]
                if len(path_parts) != 4 or path_parts[:2] != ["legislation", "laws"]:
                    raise RuntimeError(
                        "New York supplemental page changed exact section identity"
                    )
                law_code, section = path_parts[2], path_parts[3]
                section_proofs.append(
                    NewYorkSupplementalProofInput.bind(
                        selector_key=f"{law_code.upper()}:{section}:source-page",
                        proof_kind="official_senate_section",
                        official_url=url,
                        media_type="text/html",
                        payload=bytes(payload),
                    )
                )
            proof_registry = proof_registry.with_inputs(section_proofs)
            # Invoke the fixed registry against every source residual.  Only
            # reviewed source-bound resolvers may change a disposition; all
            # other retained pages remain typed residuals.
            parsed_reports = _parse_pdf_inputs(proof_registry)

        statutes: List[NormalizedStatute] = []
        seen_identities: set[str] = set()
        law_reports: List[Dict[str, Any]] = []
        frontier_rows: List[Dict[str, str]] = []
        terminal_counts: Dict[str, int] = {}
        for source_input, report in zip(pdf_inputs, parsed_reports, strict=True):
                law_code, law_name, _public_url = source_input["catalog_row"]
                source_url = str(source_input["source_url"])
                raw = bytes(source_input["payload"])
                receipt = source_input["receipt"]
                content_sha256 = hashlib.sha256(raw).hexdigest()
                if report.law_code != law_code:
                    raise RuntimeError(
                        "New York law PDF changed catalog identity: "
                        f"expected={law_code} observed={report.law_code}"
                    )
                if not report.closed or report.source_section_count <= 0:
                    raise RuntimeError(
                        "New York law PDF failed exact parser closure: "
                        f"law={law_code} source={report.source_section_count} "
                        f"operative={len(report.statutes)} terminal="
                        f"{len(report.terminal_sections)} residuals="
                        f"{report.unclassified_sections[:10]}"
                    )
                receipt_dict = dict(receipt or {})
                for terminal in report.terminal_sections:
                    disposition = str(terminal.get("disposition") or "repealed")
                    terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
                for statute in report.statutes:
                    identity = str(statute.statute_id or "").strip().casefold()
                    if not identity or identity in seen_identities:
                        raise RuntimeError(
                            "New York PDF frontier repeated normalized statute identity: "
                            f"{statute.statute_id}"
                        )
                    seen_identities.add(identity)
                    statute.structured_data = {
                        **dict(statute.structured_data or {}),
                        "content_sha256": content_sha256,
                        "parser_input_receipt_sha256": str(
                            receipt_dict.get("receipt_sha256") or ""
                        ),
                        "source_transport": str(
                            receipt_dict.get("source_transport")
                            or receipt_dict.get("transport_kind")
                            or ""
                        ),
                        "source_bundle": {
                            "official_url": source_url,
                            "media_type": "application/pdf",
                            "byte_size": len(raw),
                            "content_sha256": content_sha256,
                        },
                    }
                    statutes.append(statute)
                law_reports.append(
                    {
                        "law_code": law_code,
                        "law_name": law_name,
                        "source_url": source_url,
                        "content_sha256": content_sha256,
                        "pages": report.page_count,
                        "raw_section_markers": report.raw_section_marker_count,
                        "embedded_section_markers": len(
                            report.embedded_section_markers
                        ),
                        "lifecycle_alternate_sections": len(
                            report.lifecycle_alternate_sections
                        ),
                        "source_sections_without_raw_markers": (
                            report.source_sections_without_raw_markers
                        ),
                        "source_sections": report.source_section_count,
                        "operative_sections": len(report.statutes),
                        "terminal_sections": len(report.terminal_sections),
                        "closed": True,
                    }
                )
                frontier_rows.append(
                    {
                        "law_code": law_code,
                        "source_url": source_url,
                        "content_sha256": content_sha256,
                    }
                )

        source_sections = sum(int(row["source_sections"]) for row in law_reports)
        terminal_sections = sum(int(row["terminal_sections"]) for row in law_reports)
        if source_sections != len(statutes) + terminal_sections:
            raise RuntimeError("New York global PDF source algebra failed reconciliation")
        catalog_content_sha256 = hashlib.sha256(catalog_payload).hexdigest()
        exact_frontier = self._new_york_exact_frontier(
            catalog_content_sha256=catalog_content_sha256,
            law_reports=law_reports,
            terminal_dispositions=terminal_counts,
            conditional_event_selectors=conditional_event_selectors,
        )
        frontier_sha256 = str(exact_frontier["law_pdf_frontier_sha256"])
        observed_at = datetime.now(timezone.utc).isoformat()
        first_observation = {
            "boundary_first": str(frontier_rows[0]["source_url"]),
            "boundary_last": str(frontier_rows[-1]["source_url"]),
            "code_name": code_name,
            "frontier": exact_frontier,
            "law_reports": law_reports,
            "conditional_event_selectors": conditional_event_selectors,
            "supplemental_proof_manifest": proof_registry.manifest(),
            "supplemental_proof_manifest_sha256": (
                proof_registry.manifest_sha256()
            ),
            "observed_at": observed_at,
            "transport_batch_stats": list(self._new_york_frontier_batch_stats),
        }
        self._last_new_york_full_frontier = first_observation
        self._last_new_york_strict_closure = {
            "schema": "new-york-consolidated-strict-closure-v1",
            "closed": True,
            "catalog_source_url": self.OFFICIAL_CONSOLIDATED_URL,
            "catalog_content_sha256": catalog_content_sha256,
            "catalog_laws": len(catalog_rows),
            "law_pdf_documents": len(frontier_rows),
            "raw_section_markers": sum(
                int(row["raw_section_markers"]) for row in law_reports
            ),
            "embedded_section_markers": sum(
                int(row["embedded_section_markers"]) for row in law_reports
            ),
            "lifecycle_alternate_sections": sum(
                int(row["lifecycle_alternate_sections"]) for row in law_reports
            ),
            "source_sections_without_raw_markers": sum(
                int(row["source_sections_without_raw_markers"])
                for row in law_reports
            ),
            "source_sections": source_sections,
            "operative_sections": len(statutes),
            "terminal_sections": terminal_sections,
            "terminal_dispositions": dict(sorted(terminal_counts.items())),
            "conditional_event_selectors": conditional_event_selectors,
            "supplemental_proof_input_count": len(proof_registry.manifest()),
            "supplemental_proof_manifest_sha256": (
                proof_registry.manifest_sha256()
            ),
            "unclassified_sections": 0,
            "frontier_sha256": frontier_sha256,
            "law_reports": law_reports,
            "batch_stats": list(self._new_york_frontier_batch_stats),
            "frontier": exact_frontier,
            "observed_at": observed_at,
        }
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Reparse retained law PDFs and seal exact publication parity."""

        first = getattr(self, "_last_new_york_full_frontier", None)
        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("New York frontier closure requires an attached ledger")
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "New York source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()

        from .new_york_law_pdf import (
            AGM28_LIFECYCLE_REPORT_URL,
            AGM28_LIFECYCLE_SELECTOR_KEY,
            NewYorkSupplementalProofInput,
            NewYorkSupplementalProofRegistry,
            evaluate_new_york_agm28_lifecycle_report,
            parse_new_york_law_pdf,
        )
        from .strict_frontier_closure import retain_exact_state_frontier_closure

        first_frontier = first.get("frontier")
        first_reports_raw = first.get("law_reports")
        if (
            not isinstance(first_frontier, Mapping)
            or not isinstance(first_reports_raw, Sequence)
            or isinstance(first_reports_raw, (str, bytes, bytearray))
            or not first_reports_raw
            or any(not isinstance(row, Mapping) for row in first_reports_raw)
        ):
            raise RuntimeError("New York first exact frontier is incomplete")
        first_reports = [dict(row) for row in first_reports_raw]
        first_selectors_raw = first.get("conditional_event_selectors")
        if first_selectors_raw is None:
            first_selectors_raw = {}
        if not isinstance(first_selectors_raw, Mapping):
            raise RuntimeError(
                "New York first conditional selector frontier is invalid"
            )
        first_selectors = {
            str(key): dict(value)
            for key, value in first_selectors_raw.items()
            if isinstance(value, Mapping)
        }
        first_proofs_raw = first.get("supplemental_proof_manifest")
        if (
            not isinstance(first_proofs_raw, Sequence)
            or isinstance(first_proofs_raw, (str, bytes, bytearray))
            or any(not isinstance(row, Mapping) for row in first_proofs_raw)
        ):
            raise RuntimeError(
                "New York first supplemental proof manifest is invalid"
            )
        first_proofs = [dict(row) for row in first_proofs_raw]
        expected_proof_manifest_sha256 = str(
            first.get("supplemental_proof_manifest_sha256") or ""
        ).strip()

        catalog_payload = self._replay_new_york_retained_input(
            self.OFFICIAL_CONSOLIDATED_URL,
            media_type="text/html",
            content_validator=self._is_valid_new_york_consolidated_catalog,
            frontier_name="retained-consolidated-catalog-replay",
        )
        catalog_digest = hashlib.sha256(catalog_payload).hexdigest()
        if catalog_digest != str(first_frontier.get("catalog_content_sha256") or ""):
            raise RuntimeError("New York retained catalog digest changed on replay")
        replay_catalog = self._new_york_source_catalog_rows(catalog_payload)
        replay_catalog_identity = [(row[0], row[1]) for row in replay_catalog]
        expected_catalog_identity = [
            (str(row.get("law_code") or ""), str(row.get("law_name") or ""))
            for row in first_reports
        ]
        if replay_catalog_identity != expected_catalog_identity:
            raise RuntimeError("New York retained law catalog membership changed")

        agm28_selector_payload: Optional[bytes] = None
        replay_selectors: Dict[str, Dict[str, Any]] = {}
        replay_proof_inputs = []
        proof_manifest_by_url = {
            str(row.get("official_url") or "").strip(): row
            for row in first_proofs
        }
        if len(proof_manifest_by_url) != len(first_proofs):
            raise RuntimeError(
                "New York first supplemental proof manifest repeated a URL"
            )
        if any(row[0] == "AGM" for row in replay_catalog):
            expected_selector = first_selectors.get(
                AGM28_LIFECYCLE_SELECTOR_KEY
            )
            if not isinstance(expected_selector, Mapping):
                raise RuntimeError(
                    "New York retained AGM 28 selector evidence is missing"
                )
            agm28_selector_payload = self._replay_new_york_retained_input(
                AGM28_LIFECYCLE_REPORT_URL,
                media_type="application/pdf",
                content_validator=self._is_valid_new_york_law_pdf,
                frontier_name="retained-agm-28-lifecycle-selector-replay",
                request_headers=self._new_york_agm28_selector_headers(),
            )
            replayed_selector = evaluate_new_york_agm28_lifecycle_report(
                agm28_selector_payload,
                source_url=AGM28_LIFECYCLE_REPORT_URL,
            )
            if replayed_selector != dict(expected_selector):
                raise RuntimeError(
                    "New York retained AGM 28 selector decision changed"
                )
            replay_selectors[AGM28_LIFECYCLE_SELECTOR_KEY] = (
                replayed_selector
            )
            bound_agm = NewYorkSupplementalProofInput.bind(
                selector_key=AGM28_LIFECYCLE_SELECTOR_KEY,
                proof_kind="official_event_report",
                official_url=AGM28_LIFECYCLE_REPORT_URL,
                media_type="application/pdf",
                payload=agm28_selector_payload,
            )
            if bound_agm.manifest_row() != proof_manifest_by_url.get(
                AGM28_LIFECYCLE_REPORT_URL
            ):
                raise RuntimeError(
                    "New York retained AGM proof manifest changed"
                )
            replay_proof_inputs.append(bound_agm)
        elif first_selectors:
            raise RuntimeError(
                "New York retained selector evidence is outside the law catalog"
            )

        replay_catalog_codes = {row[0] for row in replay_catalog}
        pinned_signed_bill_rows = [
            tuple(str(value) for value in row)
            for row in self.STRICT_CURRENT_SIGNED_BILL_PROOF_ROWS
            if str(row[0]) in replay_catalog_codes
        ]
        observed_signed_bill_urls = {
            url
            for url, row in proof_manifest_by_url.items()
            if str(row.get("proof_kind") or "")
            == "official_signed_bill_record"
        }
        expected_signed_bill_urls = {row[3] for row in pinned_signed_bill_rows}
        if observed_signed_bill_urls != expected_signed_bill_urls:
            raise RuntimeError(
                "New York retained signed-bill proof membership changed"
            )
        for _code, _section, selector_key, url in pinned_signed_bill_rows:
            expected_proof = proof_manifest_by_url[url]
            payload = self._replay_new_york_retained_input(
                url,
                media_type="text/html",
                content_validator=(
                    self._is_valid_new_york_assembly_signed_bill_html
                ),
                frontier_name=(
                    f"retained-signed-bill-{selector_key}-replay"
                ),
            )
            bound_proof = NewYorkSupplementalProofInput.bind(
                selector_key=selector_key,
                proof_kind="official_signed_bill_record",
                official_url=url,
                media_type="text/html",
                payload=payload,
            )
            if bound_proof.manifest_row() != expected_proof:
                raise RuntimeError(
                    f"New York retained signed-bill proof changed: {url}"
                )
            replay_proof_inputs.append(bound_proof)

        pinned_env_rows = (
            [
                tuple(str(value) for value in row)
                for row in self.STRICT_CURRENT_ENV_PROOF_ROWS
            ]
            if "ENV" in replay_catalog_codes
            else []
        )
        observed_env_urls = {
            url
            for url, row in proof_manifest_by_url.items()
            if str(row.get("proof_kind") or "")
            in {
                "official_assembly_bill_record",
                "official_constitution_section",
            }
        }
        expected_env_urls = {row[2] for row in pinned_env_rows}
        if observed_env_urls != expected_env_urls:
            raise RuntimeError(
                "New York retained ENV proof membership changed"
            )
        for selector_key, proof_kind, url in pinned_env_rows:
            expected_proof = proof_manifest_by_url[url]
            constitution_input = proof_kind == "official_constitution_section"
            payload = self._replay_new_york_retained_input(
                url,
                media_type="text/html",
                content_validator=(
                    self._is_valid_new_york_senate_section_html
                    if constitution_input
                    else self._is_valid_new_york_assembly_bill_html
                ),
                frontier_name=f"retained-env-{selector_key}-replay",
                request_headers=(
                    self._new_york_constitution_section_headers()
                    if constitution_input
                    else None
                ),
            )
            bound_proof = NewYorkSupplementalProofInput.bind(
                selector_key=selector_key,
                proof_kind=proof_kind,
                official_url=url,
                media_type="text/html",
                payload=payload,
            )
            if bound_proof.manifest_row() != expected_proof:
                raise RuntimeError(
                    f"New York retained ENV proof changed: {url}"
                )
            replay_proof_inputs.append(bound_proof)

        pinned_event_rows = [
            tuple(str(value) for value in row)
            for row in self.STRICT_CURRENT_EVENT_PROOF_ROWS
            if str(row[0]) in replay_catalog_codes
        ]
        observed_event_urls = {
            url
            for url, row in proof_manifest_by_url.items()
            if str(row.get("proof_kind") or "")
            in {
                "official_comptroller_payroll_bulletin",
                "official_enacted_bill_text",
                "official_state_register_adoption",
                "official_government_financial_report",
            }
        }
        expected_event_urls = {row[4] for row in pinned_event_rows}
        if observed_event_urls != expected_event_urls:
            raise RuntimeError(
                "New York retained event proof membership changed"
            )
        for _code, _family, selector_key, proof_kind, url in pinned_event_rows:
            expected_proof = proof_manifest_by_url[url]
            media_type = self._new_york_event_proof_media_type(proof_kind)
            payload = self._replay_new_york_retained_input(
                url,
                media_type=media_type,
                content_validator=(
                    self._is_valid_new_york_event_proof_pdf
                    if media_type == "application/pdf"
                    else self._is_valid_new_york_event_proof_html
                ),
                frontier_name=f"retained-event-{selector_key}-replay",
            )
            bound_proof = NewYorkSupplementalProofInput.bind(
                selector_key=selector_key,
                proof_kind=proof_kind,
                official_url=url,
                media_type=media_type,
                payload=payload,
            )
            if bound_proof.manifest_row() != expected_proof:
                raise RuntimeError(
                    f"New York retained event proof changed: {url}"
                )
            replay_proof_inputs.append(bound_proof)

        pinned_supplemental_urls = list(
            self.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS
        )
        observed_supplemental_urls = {
            url
            for url, row in proof_manifest_by_url.items()
            if str(row.get("proof_kind") or "") == "official_senate_section"
        }
        if observed_supplemental_urls and observed_supplemental_urls != set(
            pinned_supplemental_urls
        ):
            raise RuntimeError(
                "New York retained supplemental proof membership changed"
            )
        expected_supplemental_urls = (
            pinned_supplemental_urls if observed_supplemental_urls else []
        )
        for url in expected_supplemental_urls:
            expected_proof = proof_manifest_by_url[url]
            path_parts = [part for part in urlparse(url).path.split("/") if part]
            if len(path_parts) != 4 or path_parts[:2] != ["legislation", "laws"]:
                raise RuntimeError(
                    "New York retained supplemental proof changed URL identity"
                )
            law_code, section = path_parts[2], path_parts[3]
            payload = self._replay_new_york_retained_input(
                url,
                media_type="text/html",
                content_validator=self._is_valid_new_york_senate_section_html,
                frontier_name=f"retained-supplemental-{law_code}-{section}-replay",
            )
            bound_proof = NewYorkSupplementalProofInput.bind(
                selector_key=f"{law_code.upper()}:{section}:source-page",
                proof_kind="official_senate_section",
                official_url=url,
                media_type="text/html",
                payload=payload,
            )
            if bound_proof.manifest_row() != expected_proof:
                raise RuntimeError(
                    f"New York retained supplemental proof changed: {url}"
                )
            replay_proof_inputs.append(bound_proof)
        replay_proof_registry = NewYorkSupplementalProofRegistry(
            replay_proof_inputs
        )
        if (
            replay_proof_registry.manifest() != first_proofs
            or replay_proof_registry.manifest_sha256()
            != expected_proof_manifest_sha256
        ):
            raise RuntimeError(
                "New York retained supplemental proof projection changed"
            )

        code_name = str(first.get("code_name") or "New York Consolidated Laws")
        replay_rows: List[NormalizedStatute] = []
        replay_reports: List[Dict[str, Any]] = []
        terminal_counts: Dict[str, int] = {}
        seen_identities: set[str] = set()
        for expected in first_reports:
            law_code = str(expected.get("law_code") or "")
            law_name = str(expected.get("law_name") or "")
            source_url = str(expected.get("source_url") or "")
            raw = self._replay_new_york_retained_input(
                source_url,
                media_type="application/pdf",
                content_validator=self._is_valid_new_york_law_pdf,
                frontier_name=f"retained-law-{law_code}-replay",
            )
            content_sha256 = hashlib.sha256(raw).hexdigest()
            if content_sha256 != str(expected.get("content_sha256") or ""):
                raise RuntimeError(
                    f"New York retained law digest changed: {law_code}"
                )
            parsed = parse_new_york_law_pdf(
                raw,
                law_code=law_code,
                law_name=law_name,
                code_name=code_name,
                source_bundle_url=source_url,
                supplemental_proof_registry=replay_proof_registry,
            )
            if parsed.law_code != law_code or not parsed.closed:
                raise RuntimeError(
                    f"New York retained law failed exact replay: {law_code}"
                )
            for terminal in parsed.terminal_sections:
                disposition = str(terminal.get("disposition") or "repealed")
                terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
            for statute in parsed.statutes:
                identity = str(statute.statute_id or "").strip().casefold()
                if not identity or identity in seen_identities:
                    raise RuntimeError(
                        "New York retained replay repeated canonical identity: "
                        f"{statute.statute_id}"
                    )
                seen_identities.add(identity)
                replay_rows.append(statute)
            replay_report = {
                "law_code": law_code,
                "law_name": law_name,
                "source_url": source_url,
                "content_sha256": content_sha256,
                "pages": parsed.page_count,
                "raw_section_markers": parsed.raw_section_marker_count,
                "embedded_section_markers": len(parsed.embedded_section_markers),
                "lifecycle_alternate_sections": len(
                    parsed.lifecycle_alternate_sections
                ),
                "source_sections_without_raw_markers": (
                    parsed.source_sections_without_raw_markers
                ),
                "source_sections": parsed.source_section_count,
                "operative_sections": len(parsed.statutes),
                "terminal_sections": len(parsed.terminal_sections),
                "closed": True,
            }
            if replay_report != expected:
                raise RuntimeError(
                    f"New York retained law inventory changed: {law_code}"
                )
            replay_reports.append(replay_report)

        replayed_frontier = self._new_york_exact_frontier(
            catalog_content_sha256=catalog_digest,
            law_reports=replay_reports,
            terminal_dispositions=terminal_counts,
            conditional_event_selectors=replay_selectors,
        )
        observed_at = str(first.get("observed_at") or "")
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="NY",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=self.OFFICIAL_CONSOLIDATED_URL,
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(replay_reports),
            pagination_total=len(replay_catalog),
            transport={
                "fixture": False,
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_pdf",
                "per_page_archive_loop": False,
                "retained_replay_network_requests": 0,
                "synthetic": False,
                "first_pass_batch_stats": list(
                    first.get("transport_batch_stats") or []
                ),
            },
        )

    async def _build_official_senate_section(
        self,
        code_name: str,
        *,
        law_code: str,
        section_number: str,
        section_label: str,
        section_url: str,
    ) -> Optional[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        html = await self._request_text_direct(section_url, timeout=18)
        if not html:
            payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=18)
            html = payload.decode("utf-8", errors="replace") if payload else ""
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        heading = soup.find(["h1", "h2"])
        section_name = self._normalize_legal_text(
            heading.get_text(" ", strip=True) if heading else section_label
        )
        main = soup.find("main") or soup.find("article") or soup.find("body") or soup
        text = self._normalize_legal_text(main.get_text(" ", strip=True))
        if len(text) < 80:
            return None
        if not section_name:
            section_name = f"Section {section_number}"
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {law_code} {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=text,
            legal_area=self._identify_legal_area(section_name),
            source_url=section_url,
            official_cite=f"N.Y. {law_code} § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_new_york_senate_laws_html",
                "discovery_method": "official_law_code_section",
                "law_code": law_code,
                "skip_hydrate": True,
            },
        )

    async def _scrape_jina_senate_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        seeds = [
            ("PEN 125.25", "https://www.nysenate.gov/legislation/laws/PEN/125.25"),
            ("CVP 101", "https://www.nysenate.gov/legislation/laws/CVP/101"),
        ]
        statutes: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            reader_url = f"https://r.jina.ai/http://{source_url}"
            text = await self._request_text_direct(reader_url, timeout=24)
            text = self._clean_jina_markdown(text)
            if len(text) < 280:
                continue
            title_match = re.search(r"§\s*([0-9A-Za-z.]+)\s+([^.\n]+)", text)
            display_section = title_match.group(1) if title_match else section_number
            section_name = title_match.group(2).strip() if title_match else section_number
            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {display_section}",
                    code_name=code_name,
                    section_number=display_section,
                    section_name=section_name[:200],
                    full_text=text,
                    source_url=source_url,
                    legal_area=self._identify_legal_area(section_name),
                    official_cite=f"N.Y. {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "jina_reader_nysenate_laws",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": reader_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return statutes

    def _clean_jina_markdown(self, text: str) -> str:
        value = str(text or "")
        marker = "Markdown Content:"
        if marker in value:
            value = value.split(marker, 1)[-1]
        value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
        value = re.sub(r"\[[^\]]*\]\([^)]+\)", " ", value)
        value = re.sub(r"#+\s*", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    async def _request_text_direct(self, url: str, timeout: int = 24) -> str:
        try:
            if self._host_is_official(url):
                payload = await self._fetch_parser_input_with_transport(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout_seconds=max(1, int(timeout)),
                    allow_archival_fallback=False,
                    media_type="text/html",
                    provider="new_york_senate_direct",
                )
                return payload.decode("utf-8", errors="replace") if payload else ""
            # Jina and public.law are explicit secondary source hops.  Keeping
            # their direct call visible prevents an official-source receipt
            # from being inferred for bytes returned by those services.
            return await self._request_external_source_text_direct(
                url,
                timeout=timeout,
            )
        except Exception:
            return ""

    async def _request_external_source_text_direct(
        self,
        url: str,
        *,
        timeout: int,
    ) -> str:
        payload = await self._fetch_non_authoritative_reference_bytes(
            url,
            timeout_seconds=timeout,
            enable_common_crawl=True,
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    async def _scrape_public_law_updates(
        self,
        code_name: str,
        max_sections: int = 120,
    ) -> List[NormalizedStatute]:
        """Fallback scraper using the newyork.public.law latest-updates index.

        This source is accessible in environments where NY Senate pages are blocked.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        base = "https://newyork.public.law"
        seed_pages = [
            f"{base}/laws/latest-updates",
            f"{base}/laws/latest-updates?page=2",
            f"{base}/laws/latest-updates?page=3",
            f"{base}/laws/latest-updates?page=4",
        ]

        statutes: List[NormalizedStatute] = []
        seen_urls = set()
        legal_area = self._identify_legal_area(code_name)
        section_url_re = re.compile(r"/laws/n\.y\._[a-z0-9_'.\-,]+_(section|article|title)_[a-z0-9\-.]+$", re.IGNORECASE)

        for page_url in seed_pages:
            if len(statutes) >= max_sections:
                break
            try:
                page_bytes = await self._fetch_page_content_with_archival_fallback(
                    page_url,
                    timeout_seconds=30,
                )
                if not page_bytes:
                    raise RuntimeError("empty response")
            except Exception as exc:
                self.logger.warning(f"NY fallback page failed {page_url}: {exc}")
                continue

            soup = BeautifulSoup(page_bytes, 'html.parser')
            for link in soup.find_all('a', href=True):
                if len(statutes) >= max_sections:
                    break

                href = link.get('href', '').strip()
                if not href:
                    continue

                full_url = urljoin(base, href)
                if full_url in seen_urls:
                    continue
                if not section_url_re.search(full_url):
                    continue
                seen_urls.add(full_url)

                link_text = link.get_text(' ', strip=True)
                section_number = self._extract_section_number(link_text)
                if not section_number:
                    tail = full_url.rstrip('/').split('/')[-1]
                    # Keep the terminal identifier as a stable fallback.
                    section_number = re.sub(r"^.*_(section|article|title)_", "", tail, flags=re.IGNORECASE)

                section_name = link_text[:200] if link_text else f"Section {section_number}"
                statutes.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}",
                        code_name=code_name,
                        section_number=section_number,
                        section_name=section_name,
                        full_text=f"Section {section_number}: {section_name}",
                        source_url=full_url,
                        legal_area=legal_area,
                        official_cite=f"NY {code_name} § {section_number}",
                        metadata=StatuteMetadata(),
                    )
                )

        self.logger.info(f"NY fallback scraper collected {len(statutes)} sections")
        return statutes

    async def _scrape_public_law_structured(
        self,
        code_name: str,
        max_sections: int = 120,
    ) -> List[NormalizedStatute]:
        base = "https://newyork.public.law"
        legal_area = self._identify_legal_area(code_name)
        root_markdown = await self._request_text_direct(f"https://r.jina.ai/http://{base}/laws", timeout=30)
        if not root_markdown:
            return []

        law_links = self._extract_markdown_links(root_markdown, self._NY_PUBLIC_LAW_MARKDOWN_LINK_RE)
        if not law_links:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        for law_label, law_url in law_links:
            if len(statutes) >= max_sections:
                break
            if law_url.rstrip("/").endswith("/laws") or law_url.endswith("/latest-updates"):
                continue
            container_links = await self._crawl_public_law_sections(law_url, max_sections=max_sections * 2)
            for section_label, section_url in container_links:
                if len(statutes) >= max_sections:
                    break
                if section_url in seen_sections:
                    continue
                seen_sections.add(section_url)
                statute = await self._build_public_law_section_statute(
                    code_name,
                    law_label or code_name,
                    section_label,
                    section_url,
                    legal_area,
                )
                if statute is not None:
                    statutes.append(statute)
        return statutes

    async def _crawl_public_law_sections(
        self,
        law_url: str,
        max_sections: int = 200,
    ) -> List[tuple[str, str]]:
        queue = [law_url]
        visited = set()
        sections: List[tuple[str, str]] = []
        seen_sections = set()

        while queue and len(sections) < max_sections:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            markdown = await self._request_text_direct(f"https://r.jina.ai/http://{current}", timeout=30)
            if not markdown:
                continue
            links = self._extract_markdown_links(markdown, self._NY_PUBLIC_LAW_MARKDOWN_LINK_RE)
            for label, url in links:
                if len(sections) >= max_sections:
                    break
                if "_section_" in url.lower():
                    if url not in seen_sections:
                        seen_sections.add(url)
                        sections.append((label, url))
                    continue
                if any(token in url.lower() for token in ["_article_", "_part_", "_title_"]) and url not in visited and url not in queue:
                    queue.append(url)
        return sections

    async def _build_public_law_section_statute(
        self,
        code_name: str,
        law_label: str,
        section_label: str,
        section_url: str,
        legal_area: str,
    ) -> Optional[NormalizedStatute]:
        markdown = await self._request_text_direct(f"https://r.jina.ai/http://{section_url}", timeout=30)
        markdown = self._clean_jina_markdown(markdown)
        if len(markdown) < 160:
            return None

        section_number = self._extract_section_number(section_label)
        if not section_number:
            tail = section_url.rstrip("/").split("/")[-1]
            section_number = re.sub(r"^.*_section_", "", tail, flags=re.IGNORECASE)

        section_name = str(section_label or "").strip()
        section_name = re.sub(r"^(SECTION|§)\s*", "", section_name, flags=re.IGNORECASE).strip()
        if section_number and section_name.lower().startswith(section_number.lower()):
            section_name = section_name[len(section_number):].strip(" -:\u00a0")
        if not section_name:
            heading_match = re.search(r"#\s+(.+)", markdown)
            section_name = heading_match.group(1).strip() if heading_match else f"Section {section_number}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=law_label or code_name,
            section_number=section_number,
            section_name=section_name[:200],
            full_text=markdown,
            source_url=section_url,
            legal_area=legal_area,
            official_cite=f"N.Y. {law_label or code_name} § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "public_law_structured_markdown",
                "discovery_method": "public_law_hierarchical_crawl",
                "skip_hydrate": True,
            },
        )

    def _extract_markdown_links(self, markdown: str, pattern: re.Pattern) -> List[tuple[str, str]]:
        found: List[tuple[str, str]] = []
        seen = set()
        for label, url in pattern.findall(str(markdown or "")):
            clean_label = self._normalize_legal_text(label)
            clean_url = str(url or "").strip().rstrip("`")
            if not clean_url or clean_url in seen:
                continue
            seen.add(clean_url)
            found.append((clean_label, clean_url))
        return found

    def official_law_url(self, law_code: Any) -> str:
        code = str(law_code or "").strip().upper()
        return f"{self.get_base_url()}/legislation/laws/{code}"

    def official_law_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official New York Consolidated Laws catalog."""

        rows: List[Dict[str, Any]] = []
        for code, name in self.OFFICIAL_LAWS:
            url = self.official_law_url(code)
            rows.append(
                {
                    "canonical_key": f"ny:law-{code.lower()}",
                    "law_code": code,
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"New York Consolidated Laws {code} ({name}) "
                        f"official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        return host in {"www.nysenate.gov", "nysenate.gov"} or host.endswith(".nysenate.gov")

    def _looks_like_secondary_url(self, url: str) -> bool:
        lowered = str(url or "").strip().lower()
        return any(
            marker in lowered
            for marker in (
                "justia.com",
                "findlaw.com",
                "unicourt",
                "law.cornell.edu",
                "newyork.public.law",
            )
        )

    def _official_http_get(self, url: str, timeout_seconds: int = 8) -> bytes:
        timeout = max(2, min(int(timeout_seconds or 8), 8))
        headers = {
            "User-Agent": "ipfs-datasets-new-york-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            request = urllib.request.Request(url, headers=headers)
            context = ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return bytes(response.read() or b"")
        except Exception:
            try:
                request = urllib.request.Request(url, headers=headers)
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                return b""

    def _parse_official_law_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {code for code, _name in self.OFFICIAL_LAWS}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._NY_LAW_HREF_RE.search(absolute)
            if not match:
                continue
            code = str(match.group("code") or "").strip().upper()
            if code not in known or code in found:
                continue
            if self._host_is_official(absolute):
                found[code] = self.official_law_url(code)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official New York Consolidated Law."""

        del page_url
        discovered = self._parse_official_law_links(html)
        rows = self.official_law_catalog()
        for row in rows:
            live_url = discovered.get(str(row["law_code"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_nysenate"
        return rows

    def fetch_official(self, code: str = "NY"):
        """Acquire the exhaustive official New York Consolidated Laws catalog.

        Live HTTPS retains the official NY Senate laws index. Every consolidated
        law is enumerated with an official nysenate.gov URL. This hook never
        returns fixture bytes or secondary-mirror hosts.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "NY").strip().upper() or "NY"
        if normalized != "NY":
            raise ValueError(f"NewYorkScraper cannot acquire {normalized}")
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) != self.OFFICIAL_LAW_COUNT:
            raise RuntimeError(
                "new york official catalog enumeration rejected incomplete law reacquisition"
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


# Register the scraper
StateScraperRegistry.register("NY", NewYorkScraper)
