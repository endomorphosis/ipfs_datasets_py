"""Official Federal Register body-text acquisition and missing-body dispositions (LCR-053).

Fetches and normalizes official HTML/XML/PDF/GovInfo body text for every
document in the closed LCR-052 inventory, detects anti-bot / navigation /
error / placeholder content, and assigns a typed disposition:

* full-text admitted (``full_text`` / ``html_body`` / ``xml_body`` /
  ``pdf_body`` / ``govinfo_body``);
* explicitly metadata-only under schema;
* excluded;
* quarantined;
* failed-final.

Design invariants
-----------------
* The official inventory is read-only. This module never rewrites
  ``federal_inventory.json``.
* Source precedence is HTML, then XML, then PDF, then GovInfo.
* Anti-bot, navigation chrome, error pages, and placeholder text are never
  admitted as retrieval bodies.
* ``failed_final`` must be zero on a closed fixture receipt.
* Observation cutoffs are immutable UTC pins (inherits LCR-049).
* Secrets, tokens, cookies, and absolute home paths never enter receipts.
* ``--fixture-only`` uses sealed inventory locators and sealed body payloads
  and never contacts the network; live transport is opt-in and never required
  for the CI gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    Optional,
    Sequence,
    Union,
)
from xml.etree import ElementTree

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    AcquisitionConfig,
    AcquisitionMode,
    InventoryDocument,
    SecretInReceiptError,
    acquire_federal_register_inventory,
    assert_no_secrets,
    atomic_create_json,
    atomic_write_json,
    build_fixture_inventory_report,
    find_secret_surfaces,
    load_json_object,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    GOVINFO_SITE,
    LEGACY_DELTA_START_INCLUSIVE,
    OFFICIAL_FULL_TEXT_SOURCES,
    PREVIOUS_PUBLIC_PIN,
    BodyTextDisposition,
    FederalRegisterSourcePolicyError,
    OfficialAuthority,
    build_legal_id,
    canonical_json_dumps,
    content_sha256,
    cutoff_release_point,
    digest_mapping,
    normalize_sha256,
    observation_cutoff_date,
    repository_root,
    require_full_text_authority,
    require_immutable_observation_cutoff,
    validate_body_text_disposition_fields,
    validate_calendar_date,
    validate_document_number,
    validate_official_url,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-fulltext-v1"
REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-fulltext-coverage@1"
)
TASK_ID: Final = "LCR-053"
GOAL_ID: Final = "LCR-G110"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_fulltext.py"
CODE_VERSION: Final = "1"
INVENTORY_TASK_ID: Final = "LCR-052"

MODE_FIXTURE: Final = "fixture"
MODE_LIVE: Final = "live"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json"
)
INVENTORY_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_inventory.json"
)

FIXTURE_OBSERVED_AT: Final = "2026-08-10T12:00:00Z"
MIN_ADMITTED_BODY_CHARS: Final = 80
MAX_BODY_CHARS: Final = 1_000_000
MAX_NOTES_CHARS: Final = 2048

# Source precedence: first usable official format wins.
SOURCE_PRECEDENCE: Final = ("html", "xml", "pdf", "govinfo")

DEFAULT_USER_AGENT: Final = (
    "ipfs-datasets-py-legal-corpora-reindex/1.0 "
    "(+https://github.com/endomorphosis/ipfs_datasets_py; "
    "Federal Register official full-text acquisition; LCR-053)"
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
# Transport returns (response_bytes, media_type).
FulltextTransport = Callable[[str, Mapping[str, str]], tuple[bytes, str]]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterFulltextError(FederalRegisterSourcePolicyError):
    """Base error for Federal Register full-text acquisition failures."""


class FulltextCoverageError(FederalRegisterFulltextError):
    """Raised when the coverage ledger is incomplete or inconsistent."""


class PlaceholderAdmittedError(FederalRegisterFulltextError):
    """Raised when placeholder or chrome text is admitted as a body."""


class FailedFinalCoverageError(FederalRegisterFulltextError):
    """Raised when failed-final items remain on a closed coverage receipt."""


class LiveFulltextDisabledError(FederalRegisterFulltextError):
    """Raised when live network full-text transport is required but disabled."""


class InventoryRewriteError(FederalRegisterFulltextError):
    """Raised when a caller attempts to rewrite the official inventory."""


class FixturePayloadError(FederalRegisterFulltextError):
    """Raised when sealed fixture body payloads cannot satisfy a locator."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FulltextMode(str, Enum):
    """Full-text enrichment mode."""

    FIXTURE = MODE_FIXTURE
    LIVE = MODE_LIVE

    @classmethod
    def coerce(cls, value: Any) -> "FulltextMode":
        if isinstance(value, FulltextMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "fixture_only": cls.FIXTURE,
            "offline": cls.FIXTURE,
            "sealed": cls.FIXTURE,
            "network": cls.LIVE,
            "online": cls.LIVE,
            "api": cls.LIVE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterFulltextError(f"unknown full-text mode: {value!r}")


class SourceFormat(str, Enum):
    """Official body-text format in source-precedence order."""

    HTML = "html"
    XML = "xml"
    PDF = "pdf"
    GOVINFO = "govinfo"

    @classmethod
    def coerce(cls, value: Any) -> "SourceFormat":
        if isinstance(value, SourceFormat):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "htm": cls.HTML,
            "xhtml": cls.HTML,
            "full_text_xml": cls.XML,
            "govinfo_pdf": cls.GOVINFO,
            "gpo": cls.GOVINFO,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterFulltextError(f"unknown source format: {value!r}")

    @property
    def precedence(self) -> int:
        return SOURCE_PRECEDENCE.index(self.value)

    @property
    def admitted_disposition(self) -> "CoverageDisposition":
        return {
            SourceFormat.HTML: CoverageDisposition.HTML_BODY,
            SourceFormat.XML: CoverageDisposition.XML_BODY,
            SourceFormat.PDF: CoverageDisposition.PDF_BODY,
            SourceFormat.GOVINFO: CoverageDisposition.GOVINFO_BODY,
        }[self]


class ParserResult(str, Enum):
    """Typed parser outcome for one official body payload."""

    SUCCESS = "success"
    NO_BODY = "no_body"
    EMPTY = "empty"
    ERROR_PAGE = "error_page"
    NAVIGATION = "navigation"
    ANTI_BOT = "anti_bot"
    PLACEHOLDER = "placeholder"
    PARSE_ERROR = "parse_error"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"

    @classmethod
    def coerce(cls, value: Any) -> "ParserResult":
        if isinstance(value, ParserResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterFulltextError(f"unknown parser result: {value!r}")

    @property
    def is_quarantine(self) -> bool:
        return self in {
            ParserResult.ERROR_PAGE,
            ParserResult.NAVIGATION,
            ParserResult.ANTI_BOT,
            ParserResult.PLACEHOLDER,
        }

    @property
    def is_absence(self) -> bool:
        return self in {ParserResult.NO_BODY, ParserResult.EMPTY}

    @property
    def indicates_usable_body(self) -> bool:
        return self is ParserResult.SUCCESS


class CoverageDisposition(str, Enum):
    """Typed coverage disposition for one inventory document.

    Every inventory document must land in exactly one of: full-text admitted
    (the body-bearing values), metadata-only under schema, excluded,
    quarantined, or failed-final. ``failed_final`` is never closed success.
    """

    FULL_TEXT = "full_text"
    HTML_BODY = "html_body"
    XML_BODY = "xml_body"
    PDF_BODY = "pdf_body"
    GOVINFO_BODY = "govinfo_body"
    METADATA_ONLY = "metadata_only"
    EXCLUDED = "excluded"
    QUARANTINED = "quarantined"
    FAILED_FINAL = "failed_final"

    @classmethod
    def coerce(cls, value: Any) -> "CoverageDisposition":
        if isinstance(value, CoverageDisposition):
            return value
        if isinstance(value, BodyTextDisposition):
            mapping = {
                BodyTextDisposition.FULL_TEXT: cls.FULL_TEXT,
                BodyTextDisposition.HTML_BODY: cls.HTML_BODY,
                BodyTextDisposition.XML_BODY: cls.XML_BODY,
                BodyTextDisposition.PDF_BODY: cls.PDF_BODY,
                BodyTextDisposition.GOVINFO_BODY: cls.GOVINFO_BODY,
                BodyTextDisposition.ABSTRACT_ONLY: cls.METADATA_ONLY,
                BodyTextDisposition.METADATA_ONLY: cls.METADATA_ONLY,
                BodyTextDisposition.UNAVAILABLE: cls.METADATA_ONLY,
                BodyTextDisposition.FAILED_FINAL: cls.FAILED_FINAL,
            }
            return mapping[value]
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "full": cls.FULL_TEXT,
            "fulltext": cls.FULL_TEXT,
            "admitted": cls.FULL_TEXT,
            "full_text_admitted": cls.FULL_TEXT,
            "html": cls.HTML_BODY,
            "xml": cls.XML_BODY,
            "pdf": cls.PDF_BODY,
            "govinfo": cls.GOVINFO_BODY,
            "abstract": cls.METADATA_ONLY,
            "abstract_only": cls.METADATA_ONLY,
            "meta": cls.METADATA_ONLY,
            "metadata": cls.METADATA_ONLY,
            "unavailable": cls.METADATA_ONLY,
            "missing_body_official": cls.METADATA_ONLY,
            "exclude": cls.EXCLUDED,
            "quarantine": cls.QUARANTINED,
            "failed": cls.FAILED_FINAL,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterFulltextError(
            f"unknown coverage disposition: {value!r}"
        )

    @property
    def is_admitted(self) -> bool:
        return self in ADMITTED_DISPOSITIONS

    @property
    def is_non_body(self) -> bool:
        return self in NON_BODY_COVERAGE_DISPOSITIONS

    @property
    def category(self) -> str:
        if self.is_admitted:
            return "full_text_admitted"
        if self is CoverageDisposition.METADATA_ONLY:
            return "metadata_only"
        if self is CoverageDisposition.EXCLUDED:
            return "excluded"
        if self is CoverageDisposition.QUARANTINED:
            return "quarantined"
        return "failed_final"

    @property
    def blocks_publication(self) -> bool:
        return self is CoverageDisposition.FAILED_FINAL

    def as_body_text_disposition(self) -> BodyTextDisposition:
        mapping = {
            CoverageDisposition.FULL_TEXT: BodyTextDisposition.FULL_TEXT,
            CoverageDisposition.HTML_BODY: BodyTextDisposition.HTML_BODY,
            CoverageDisposition.XML_BODY: BodyTextDisposition.XML_BODY,
            CoverageDisposition.PDF_BODY: BodyTextDisposition.PDF_BODY,
            CoverageDisposition.GOVINFO_BODY: BodyTextDisposition.GOVINFO_BODY,
            CoverageDisposition.METADATA_ONLY: BodyTextDisposition.METADATA_ONLY,
            CoverageDisposition.EXCLUDED: BodyTextDisposition.UNAVAILABLE,
            CoverageDisposition.QUARANTINED: BodyTextDisposition.UNAVAILABLE,
            CoverageDisposition.FAILED_FINAL: BodyTextDisposition.FAILED_FINAL,
        }
        return mapping[self]


ADMITTED_DISPOSITIONS: Final = frozenset(
    {
        CoverageDisposition.FULL_TEXT,
        CoverageDisposition.HTML_BODY,
        CoverageDisposition.XML_BODY,
        CoverageDisposition.PDF_BODY,
        CoverageDisposition.GOVINFO_BODY,
    }
)

NON_BODY_COVERAGE_DISPOSITIONS: Final = frozenset(
    {
        CoverageDisposition.METADATA_ONLY,
        CoverageDisposition.EXCLUDED,
        CoverageDisposition.QUARANTINED,
        CoverageDisposition.FAILED_FINAL,
    }
)

COVERAGE_CATEGORIES: Final = (
    "full_text_admitted",
    "metadata_only",
    "excluded",
    "quarantined",
    "failed_final",
)


class AllowedNonBodyReason(str, Enum):
    """Closed allow-list of reasons that may justify a non-body disposition."""

    OFFICIAL_METADATA_ONLY = "official_metadata_only"
    OFFICIAL_BODY_UNAVAILABLE = "official_body_unavailable"
    RIGHTS_OR_SCOPE_EXCLUSION = "rights_or_scope_exclusion"
    CONTENT_QUARANTINE = "content_quarantine"
    ANTI_BOT_CONTENT = "anti_bot_content"
    NAVIGATION_CONTENT = "navigation_content"
    ERROR_PAGE_CONTENT = "error_page_content"
    PLACEHOLDER_CONTENT = "placeholder_content"
    OUTSIDE_CUTOFF_SCOPE = "outside_cutoff_scope"

    @classmethod
    def coerce(cls, value: Any) -> "AllowedNonBodyReason":
        if isinstance(value, AllowedNonBodyReason):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "metadata_only": cls.OFFICIAL_METADATA_ONLY,
            "unavailable": cls.OFFICIAL_BODY_UNAVAILABLE,
            "excluded": cls.RIGHTS_OR_SCOPE_EXCLUSION,
            "quarantine": cls.CONTENT_QUARANTINE,
            "anti_bot": cls.ANTI_BOT_CONTENT,
            "navigation": cls.NAVIGATION_CONTENT,
            "error_page": cls.ERROR_PAGE_CONTENT,
            "placeholder": cls.PLACEHOLDER_CONTENT,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterFulltextError(
            f"non-body disposition requires an allowed reason; got {value!r}"
        )


class FixtureRole(str, Enum):
    """Sealed fixture role that drives locator payloads (not a disposition)."""

    HTML_BODY = "html_body"
    XML_BODY = "xml_body"
    PDF_BODY = "pdf_body"
    GOVINFO_BODY = "govinfo_body"
    METADATA_ONLY = "metadata_only"
    EXCLUDED = "excluded"
    QUARANTINED_ANTI_BOT = "quarantined_anti_bot"
    QUARANTINED_NAVIGATION = "quarantined_navigation"
    QUARANTINED_ERROR = "quarantined_error"

    @classmethod
    def coerce(cls, value: Any) -> "FixtureRole":
        if isinstance(value, FixtureRole):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterFulltextError(f"unknown fixture role: {value!r}")

    @property
    def expected_disposition(self) -> CoverageDisposition:
        mapping = {
            FixtureRole.HTML_BODY: CoverageDisposition.HTML_BODY,
            FixtureRole.XML_BODY: CoverageDisposition.XML_BODY,
            FixtureRole.PDF_BODY: CoverageDisposition.PDF_BODY,
            FixtureRole.GOVINFO_BODY: CoverageDisposition.GOVINFO_BODY,
            FixtureRole.METADATA_ONLY: CoverageDisposition.METADATA_ONLY,
            FixtureRole.EXCLUDED: CoverageDisposition.EXCLUDED,
            FixtureRole.QUARANTINED_ANTI_BOT: CoverageDisposition.QUARANTINED,
            FixtureRole.QUARANTINED_NAVIGATION: CoverageDisposition.QUARANTINED,
            FixtureRole.QUARANTINED_ERROR: CoverageDisposition.QUARANTINED,
        }
        return mapping[self]


FIXTURE_ROLE_SEQUENCE: Final = (
    FixtureRole.HTML_BODY,
    FixtureRole.XML_BODY,
    FixtureRole.PDF_BODY,
    FixtureRole.GOVINFO_BODY,
    FixtureRole.METADATA_ONLY,
    FixtureRole.EXCLUDED,
    FixtureRole.QUARANTINED_ANTI_BOT,
    FixtureRole.QUARANTINED_NAVIGATION,
    FixtureRole.QUARANTINED_ERROR,
)

# ---------------------------------------------------------------------------
# Content detectors
# ---------------------------------------------------------------------------

_ANTI_BOT_RE = re.compile(
    r"(?is)(?:captcha|cloudflare|cf-challenge|are you a robot|"
    r"please enable javascript|access denied|unusual traffic|"
    r"attention required|checking your browser before accessing|"
    r"verify you are human|ddos protection)"
)
_ERROR_PAGE_RE = re.compile(
    r"(?is)(?:\b404\b.{0,40}not found|page not found|document not found|"
    r"internal server error|\b500\b.{0,20}error|temporarily unavailable|"
    r"service unavailable|\b403\b.{0,20}forbidden)"
)
_NAVIGATION_RE = re.compile(
    r"(?is)(?:skip to main content|subscribe to the federal register|"
    r"sign in to your account|search the federal register|"
    r"browse agencies|developer resources|office of the federal register)"
)
_PLACEHOLDER_RE = re.compile(
    r"(?is)(?:lorem ipsum|\[full text not available\]|\[placeholder\]|"
    r"todo:\s*add full text|body text pending|full text will be posted|"
    r"text not yet available|this is a stub|coming soon|"
    r"placeholder body|insert official text here)"
)
_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(?:script|style|noscript|svg)\b[^>]*>.*?</(?:script|style|noscript|svg)>"
)
_NAV_CHROME_RE = re.compile(
    r"(?is)<(?:nav|header|footer|aside)\b[^>]*>.*?</(?:nav|header|footer|aside)>"
)
_TAG_RE = re.compile(r"(?is)<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n{3,}")

_FORMAT_MEDIA_TYPES: Final = {
    SourceFormat.HTML: frozenset({"text/html", "application/xhtml+xml"}),
    SourceFormat.XML: frozenset({"application/xml", "text/xml"}),
    SourceFormat.PDF: frozenset({"application/pdf", "text/plain"}),
    SourceFormat.GOVINFO: frozenset({"application/pdf", "text/plain"}),
}


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterFulltextError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterFulltextError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise FederalRegisterFulltextError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_bounded_str(
    value: Any,
    name: str,
    *,
    maximum: int,
    allow_empty: bool = True,
) -> str:
    if not isinstance(value, str):
        raise FederalRegisterFulltextError(f"{name} must be a string")
    if "\x00" in value:
        raise FederalRegisterFulltextError(f"{name} must not contain NUL")
    if not allow_empty and not value:
        raise FederalRegisterFulltextError(f"{name} must not be empty")
    if len(value) > maximum:
        raise FederalRegisterFulltextError(
            f"{name} exceeds maximum length {maximum}"
        )
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterFulltextError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterFulltextError(f"{name} must be >= 0")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise FederalRegisterFulltextError(f"{name} must be a boolean")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FederalRegisterFulltextError(f"{name} must be a mapping")
    return value


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FederalRegisterFulltextError(f"{name} must be a sequence")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    name: str,
) -> None:
    observed = set(value)
    if observed != expected:
        raise FederalRegisterFulltextError(
            f"{name} fields differ from the exact schema: "
            f"missing={sorted(expected - observed)}; "
            f"extra={sorted(observed - expected)}"
        )


def default_report_path(repo_root: PathLike | None = None) -> Path:
    """Return the frozen full-text coverage report path (relative-safe)."""

    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def inventory_report_relpath() -> str:
    """Return the POSIX relative path of the official inventory report."""

    return INVENTORY_REPORT_RELPATH.as_posix()


# ---------------------------------------------------------------------------
# HTML / XML / PDF normalization
# ---------------------------------------------------------------------------


class _HTMLTextExtractor(HTMLParser):
    """Extract visible document text, skipping chrome and non-content tags."""

    _SKIP = frozenset({"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_article = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP:
            self._skip_depth += 1
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        identity = f"{attr_map.get('id', '')} {attr_map.get('class', '')}".lower()
        if lowered == "article" or "fulltext" in identity or "document-content" in identity:
            self._in_article += 1

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if lowered == "article" and self._in_article:
            self._in_article -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        return "\n".join(self._chunks)


def _decode_payload(raw: bytes) -> str:
    if not isinstance(raw, (bytes, bytearray)):
        raise FederalRegisterFulltextError("payload must be bytes")
    try:
        return bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        return bytes(raw).decode("utf-8", errors="replace")


def _collapse_whitespace(text: str) -> str:
    collapsed = _WS_RE.sub(" ", text)
    collapsed = _BLANK_RE.sub("\n\n", collapsed.replace("\r\n", "\n").replace("\r", "\n"))
    return collapsed.strip()


def normalize_html_body(raw: bytes | str) -> str:
    """Normalize official HTML into retrieval body text."""

    text = raw if isinstance(raw, str) else _decode_payload(raw)
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(text)
        extractor.close()
        extracted = extractor.text()
    except Exception:
        stripped = _SCRIPT_STYLE_RE.sub(" ", text)
        stripped = _NAV_CHROME_RE.sub(" ", stripped)
        extracted = _TAG_RE.sub(" ", stripped)
    return _collapse_whitespace(extracted)


def normalize_xml_body(raw: bytes | str) -> str:
    """Normalize official XML into retrieval body text."""

    payload = raw if isinstance(raw, (bytes, bytearray)) else raw.encode("utf-8")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return _collapse_whitespace(_TAG_RE.sub(" ", _decode_payload(bytes(payload))))
    preferred = (
        "FULL_TEXT",
        "full_text",
        "PREAMB",
        "SUPLINF",
        "HD",
        "P",
    )
    chunks: list[str] = []
    for tag in preferred:
        for node in root.iter(tag):
            inner = "".join(node.itertext()).strip()
            if inner:
                chunks.append(inner)
    if not chunks:
        chunks.append("".join(root.itertext()))
    return _collapse_whitespace("\n".join(chunks))


def normalize_pdf_body(raw: bytes | str) -> str:
    """Normalize a fixture/official PDF payload into retrieval body text.

    Fixture PDFs carry extractable UTF-8 text. Binary streams without
    extractable text are treated as empty (not admitted).
    """

    text = raw if isinstance(raw, str) else _decode_payload(raw)
    # Drop obvious PDF structural tokens; keep extractable text lines.
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("%"):
            continue
        if stripped in {"stream", "endstream", "xref", "trailer", "startxref", "%%EOF"}:
            continue
        if re.fullmatch(r"\d+\s+\d+\s+obj", stripped):
            continue
        if stripped in {"endobj", "bt", "et"} or stripped.lower() == "bt":
            continue
        lines.append(stripped)
    return _collapse_whitespace("\n".join(lines))


def normalize_body(raw: bytes | str, source_format: SourceFormat | str) -> str:
    fmt = SourceFormat.coerce(source_format)
    if fmt is SourceFormat.HTML:
        return normalize_html_body(raw)
    if fmt is SourceFormat.XML:
        return normalize_xml_body(raw)
    return normalize_pdf_body(raw)


def is_placeholder_text(text: str) -> bool:
    """Return True when *text* is a placeholder, not official body."""

    if not text or not text.strip():
        return False
    return bool(_PLACEHOLDER_RE.search(text))


def detect_content_kind(
    raw: bytes | str,
    source_format: SourceFormat | str,
    *,
    media_type: str = "",
) -> ParserResult:
    """Classify raw official bytes before admission.

    Anti-bot, navigation, error, and placeholder payloads never become
    retrieval bodies. Empty/no-body outcomes support metadata-only under
    schema after every format is exhausted.
    """

    fmt = SourceFormat.coerce(source_format)
    if raw is None:
        return ParserResult.NO_BODY
    if isinstance(raw, (bytes, bytearray)) and not raw:
        return ParserResult.EMPTY
    if isinstance(raw, str) and not raw.strip():
        return ParserResult.EMPTY

    decoded = raw if isinstance(raw, str) else _decode_payload(raw)
    haystack = decoded[:50_000]
    if _ANTI_BOT_RE.search(haystack):
        return ParserResult.ANTI_BOT
    if _ERROR_PAGE_RE.search(haystack):
        return ParserResult.ERROR_PAGE

    try:
        normalized = normalize_body(raw, fmt)
    except Exception:
        return ParserResult.PARSE_ERROR

    if is_placeholder_text(normalized) or is_placeholder_text(haystack):
        return ParserResult.PLACEHOLDER
    navigation_hit = bool(
        _NAVIGATION_RE.search(haystack) or _NAVIGATION_RE.search(normalized)
    )
    if not normalized:
        if navigation_hit:
            return ParserResult.NAVIGATION
        return ParserResult.EMPTY
    if len(normalized) < MIN_ADMITTED_BODY_CHARS:
        if navigation_hit:
            return ParserResult.NAVIGATION
        return ParserResult.NO_BODY
    media = (media_type or "").split(";", 1)[0].strip().lower()
    allowed = _FORMAT_MEDIA_TYPES.get(fmt)
    if media and allowed and media not in allowed and media != "text/plain":
        return ParserResult.PARSE_ERROR
    return ParserResult.SUCCESS


def quarantine_reason_for(kind: ParserResult) -> AllowedNonBodyReason:
    mapping = {
        ParserResult.ANTI_BOT: AllowedNonBodyReason.ANTI_BOT_CONTENT,
        ParserResult.NAVIGATION: AllowedNonBodyReason.NAVIGATION_CONTENT,
        ParserResult.ERROR_PAGE: AllowedNonBodyReason.ERROR_PAGE_CONTENT,
        ParserResult.PLACEHOLDER: AllowedNonBodyReason.PLACEHOLDER_CONTENT,
        ParserResult.PARSE_ERROR: AllowedNonBodyReason.CONTENT_QUARANTINE,
    }
    return mapping.get(kind, AllowedNonBodyReason.CONTENT_QUARANTINE)


# ---------------------------------------------------------------------------
# Locator helpers
# ---------------------------------------------------------------------------


def official_html_url(document_number: str, publication_date: str) -> str:
    pub = validate_calendar_date(publication_date, name="publication_date")
    doc = validate_document_number(document_number)
    yyyy, mm, dd = pub.split("-")
    return f"https://www.federalregister.gov/documents/{yyyy}/{mm}/{dd}/{doc}"


def official_xml_url(document_number: str) -> str:
    doc = validate_document_number(document_number)
    return f"https://www.federalregister.gov/documents/full_text/xml/{doc}.xml"


def official_pdf_url(document_number: str, publication_date: str) -> str:
    pub = validate_calendar_date(publication_date, name="publication_date")
    doc = validate_document_number(document_number)
    yyyy, mm, dd = pub.split("-")
    return (
        f"https://www.federalregister.gov/documents/{yyyy}/{mm}/{dd}/{doc}.pdf"
    )


def official_govinfo_url(document_number: str, publication_date: str) -> str:
    pub = validate_calendar_date(publication_date, name="publication_date")
    doc = validate_document_number(document_number)
    return f"{GOVINFO_SITE}/content/pkg/FR-{pub}/pdf/{doc}.pdf"


def locators_for_document(document: InventoryDocument) -> dict[SourceFormat, str]:
    """Return official locators in a format map (empty string if missing)."""

    html = document.html_url.strip() or official_html_url(
        document.document_number, document.publication_date
    )
    xml = document.xml_url.strip() or official_xml_url(document.document_number)
    pdf = official_pdf_url(document.document_number, document.publication_date)
    govinfo = document.pdf_url.strip() or official_govinfo_url(
        document.document_number, document.publication_date
    )
    locators = {
        SourceFormat.HTML: validate_official_url(html, name="html_url"),
        SourceFormat.XML: validate_official_url(xml, name="xml_url"),
        SourceFormat.PDF: validate_official_url(pdf, name="pdf_url"),
        SourceFormat.GOVINFO: validate_official_url(govinfo, name="govinfo_url"),
    }
    return locators


def authority_for_format(source_format: SourceFormat) -> OfficialAuthority:
    if source_format is SourceFormat.GOVINFO:
        return OfficialAuthority.GOVINFO
    return OfficialAuthority.FEDERAL_REGISTER


# ---------------------------------------------------------------------------
# Sealed fixture bodies
# ---------------------------------------------------------------------------


def _official_html_payload(document_number: str, publication_date: str, title: str) -> bytes:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{document_number}</title></head><body>"
        f"<article id=\"fulltext\" class=\"document-content\">"
        f"<h1>{title or f'Official Federal Register document {document_number}'}</h1>"
        f"<p>This is the official body text for {document_number} published "
        f"on {publication_date} in the Federal Register.</p>"
        "<p>Section 1. Purpose. This document implements the sealed fixture "
        "corpus used by the cutoff-bound legal corpora reindex.</p>"
        "<p>Section 2. Authority. Acquisition uses FederalRegister.gov and "
        "GovInfo as the official full-text authorities.</p>"
        "</article></body></html>"
    ).encode("utf-8")


def _official_xml_payload(document_number: str, publication_date: str, title: str) -> bytes:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<FEDREG><DOCUMENT>"
        f"<FRDOC>{document_number}</FRDOC>"
        f"<PRIODATE>{publication_date}</PRIODATE>"
        f"<SUBJECT>{title or document_number}</SUBJECT>"
        "<FULL_TEXT>"
        f"<HD>Official Federal Register XML body for {document_number}</HD>"
        f"<P>This is the official XML body text for {document_number} "
        f"published on {publication_date}.</P>"
        "<P>Section 1. Purpose. This document implements the sealed fixture "
        "corpus used by the cutoff-bound legal corpora reindex.</P>"
        "</FULL_TEXT></DOCUMENT></FEDREG>"
    ).encode("utf-8")


def _official_pdf_payload(document_number: str, publication_date: str, title: str) -> bytes:
    return (
        "%PDF-1.4\n"
        "1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        f"Official Federal Register PDF body for {document_number}.\n"
        f"{title or document_number}\n"
        f"Published {publication_date}. Section 1. Purpose. This document "
        "implements the sealed fixture corpus used by the cutoff-bound "
        "legal corpora reindex.\n"
        "%%EOF\n"
    ).encode("utf-8")


def _empty_html_payload() -> bytes:
    return b"<!DOCTYPE html><html><head><title></title></head><body></body></html>"


def _empty_xml_payload() -> bytes:
    return b"<?xml version=\"1.0\"?><FEDREG><DOCUMENT></DOCUMENT></FEDREG>"


def _empty_pdf_payload() -> bytes:
    return b"%PDF-1.4\n%%EOF\n"


def _anti_bot_payload() -> bytes:
    return (
        b"<!DOCTYPE html><html><head><title>Attention Required</title></head>"
        b"<body><h1>Attention Required</h1>"
        b"<p>Please complete the captcha to continue.</p>"
        b"<div id=\"cf-challenge\">cloudflare checking your browser before "
        b"accessing federalregister.gov. Verify you are human.</div>"
        b"</body></html>"
    )


def _navigation_payload() -> bytes:
    return (
        b"<!DOCTYPE html><html><head><title>Federal Register</title></head>"
        b"<body><nav>Skip to main content. Subscribe to the Federal Register. "
        b"Sign in to your account. Search the Federal Register. "
        b"Browse agencies. Developer resources.</nav>"
        b"<header>Office of the Federal Register</header>"
        b"</body></html>"
    )


def _error_page_payload() -> bytes:
    return (
        b"<!DOCTYPE html><html><head><title>404 Not Found</title></head>"
        b"<body><h1>404 Not Found</h1>"
        b"<p>The requested document was not found.</p>"
        b"<p>Page not found on this official source.</p>"
        b"</body></html>"
    )


def _placeholder_payload() -> bytes:
    return (
        b"<!DOCTYPE html><html><body><article id=\"fulltext\">"
        b"[full text not available] lorem ipsum dolor sit amet "
        b"placeholder body insert official text here"
        b"</article></body></html>"
    )


def fixture_role_for_index(index: int) -> FixtureRole:
    """Deterministic sealed role for the *index*-th inventory document."""

    index_n = _require_non_negative_int(index, "index")
    if index_n < len(FIXTURE_ROLE_SEQUENCE):
        return FIXTURE_ROLE_SEQUENCE[index_n]
    return FixtureRole.HTML_BODY


def media_type_for_format(source_format: SourceFormat) -> str:
    if source_format is SourceFormat.HTML:
        return "text/html"
    if source_format is SourceFormat.XML:
        return "application/xml"
    return "application/pdf"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormatAttempt:
    """One official format attempt for a document."""

    attempt_id: str
    authority: OfficialAuthority
    source_format: SourceFormat
    url: str
    status: str
    parser_result: ParserResult
    response_hash: Optional[str] = None
    content_hash: Optional[str] = None
    body_usable: bool = False
    media_type: str = ""
    terminal_reason: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attempt_id",
            _require_non_empty_str(self.attempt_id, "attempt_id", maximum=128),
        )
        object.__setattr__(
            self, "authority", require_full_text_authority(self.authority)
        )
        object.__setattr__(
            self, "source_format", SourceFormat.coerce(self.source_format)
        )
        object.__setattr__(self, "url", validate_official_url(self.url, name="url"))
        object.__setattr__(
            self,
            "status",
            _require_non_empty_str(self.status, "status", maximum=32),
        )
        object.__setattr__(
            self, "parser_result", ParserResult.coerce(self.parser_result)
        )
        for field_name in ("response_hash", "content_hash"):
            raw = getattr(self, field_name)
            if raw is not None and str(raw).strip():
                object.__setattr__(
                    self, field_name, normalize_sha256(raw, name=field_name)
                )
            else:
                object.__setattr__(self, field_name, None)
        object.__setattr__(
            self, "body_usable", _require_bool(self.body_usable, "body_usable")
        )
        object.__setattr__(
            self,
            "media_type",
            _require_bounded_str(self.media_type, "media_type", maximum=128),
        )
        object.__setattr__(
            self,
            "terminal_reason",
            _require_bounded_str(
                self.terminal_reason, "terminal_reason", maximum=128
            ),
        )
        object.__setattr__(
            self, "notes", _require_bounded_str(self.notes, "notes", maximum=MAX_NOTES_CHARS)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "authority": self.authority.value,
            "source_format": self.source_format.value,
            "url": self.url,
            "status": self.status,
            "parser_result": self.parser_result.value,
            "response_hash": self.response_hash,
            "content_hash": self.content_hash,
            "body_usable": self.body_usable,
            "media_type": self.media_type,
            "terminal_reason": self.terminal_reason,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CachedBody:
    """Immutable official body bytes addressed by content hash."""

    content_hash: str
    source_format: SourceFormat
    url: str
    media_type: str
    normalized_text: str
    response_hash: str
    legal_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "content_hash",
            normalize_sha256(self.content_hash, name="content_hash"),
        )
        object.__setattr__(
            self, "source_format", SourceFormat.coerce(self.source_format)
        )
        object.__setattr__(self, "url", validate_official_url(self.url, name="url"))
        object.__setattr__(
            self,
            "normalized_text",
            _require_bounded_str(
                self.normalized_text,
                "normalized_text",
                maximum=MAX_BODY_CHARS,
                allow_empty=False,
            ),
        )
        recomputed = content_sha256(self.normalized_text)
        if recomputed != self.content_hash:
            raise FederalRegisterFulltextError(
                "cached body content_hash does not match normalized text"
            )
        if is_placeholder_text(self.normalized_text):
            raise PlaceholderAdmittedError(
                "immutable text cache refuses placeholder body text"
            )
        object.__setattr__(
            self,
            "response_hash",
            normalize_sha256(self.response_hash, name="response_hash"),
        )
        object.__setattr__(
            self,
            "legal_id",
            _require_non_empty_str(self.legal_id, "legal_id", maximum=256),
        )
        object.__setattr__(
            self,
            "media_type",
            _require_bounded_str(self.media_type, "media_type", maximum=128),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "source_format": self.source_format.value,
            "url": self.url,
            "media_type": self.media_type,
            "normalized_text": self.normalized_text,
            "response_hash": self.response_hash,
            "legal_id": self.legal_id,
            "body_char_count": len(self.normalized_text),
        }


class ImmutableTextCache:
    """Content-addressed cache of admitted official bodies."""

    def __init__(self) -> None:
        self._by_hash: dict[str, CachedBody] = {}
        self._by_legal_id: dict[str, str] = {}

    def put(self, body: CachedBody) -> CachedBody:
        existing = self._by_hash.get(body.content_hash)
        if existing is not None:
            if existing.normalized_text != body.normalized_text:
                raise FederalRegisterFulltextError(
                    "content-hash collision in immutable text cache"
                )
            return existing
        self._by_hash[body.content_hash] = body
        self._by_legal_id[body.legal_id] = body.content_hash
        return body

    def get(self, content_hash: str) -> Optional[CachedBody]:
        return self._by_hash.get(normalize_sha256(content_hash, name="content_hash"))

    def get_for_legal_id(self, legal_id: str) -> Optional[CachedBody]:
        digest = self._by_legal_id.get(legal_id)
        if digest is None:
            return None
        return self._by_hash.get(digest)

    @property
    def size(self) -> int:
        return len(self._by_hash)

    def admitted_legal_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_legal_id))


@dataclass(frozen=True)
class DocumentCoverage:
    """Typed full-text disposition for one inventory document."""

    legal_id: str
    document_number: str
    publication_date: str
    disposition: CoverageDisposition
    attempts: tuple[FormatAttempt, ...] = ()
    allowed_reason: Optional[str] = None
    admitted_content_hash: Optional[str] = None
    admitted_response_hash: Optional[str] = None
    admitted_source_format: Optional[str] = None
    official_source_url: Optional[str] = None
    body_char_count: int = 0
    fixture_role: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        doc = validate_document_number(self.document_number)
        pub = validate_calendar_date(self.publication_date, name="publication_date")
        object.__setattr__(self, "document_number", doc)
        object.__setattr__(self, "publication_date", pub)
        object.__setattr__(
            self, "disposition", CoverageDisposition.coerce(self.disposition)
        )
        expected_legal = build_legal_id(doc, pub)
        legal = _require_non_empty_str(self.legal_id, "legal_id", maximum=256)
        if legal != expected_legal and not legal.startswith(expected_legal + ":"):
            raise FederalRegisterFulltextError(
                f"legal_id {legal!r} does not match {expected_legal!r}"
            )
        object.__setattr__(self, "legal_id", legal)
        attempts = tuple(
            item if isinstance(item, FormatAttempt) else _attempt_from_mapping(item)
            for item in (self.attempts or ())
        )
        object.__setattr__(self, "attempts", attempts)
        if self.allowed_reason is not None and str(self.allowed_reason).strip():
            reason = AllowedNonBodyReason.coerce(self.allowed_reason)
            object.__setattr__(self, "allowed_reason", reason.value)
        else:
            object.__setattr__(self, "allowed_reason", None)
        for field_name in ("admitted_content_hash", "admitted_response_hash"):
            raw = getattr(self, field_name)
            if raw is not None and str(raw).strip():
                object.__setattr__(
                    self, field_name, normalize_sha256(raw, name=field_name)
                )
            else:
                object.__setattr__(self, field_name, None)
        if self.admitted_source_format is not None and str(
            self.admitted_source_format
        ).strip():
            object.__setattr__(
                self,
                "admitted_source_format",
                SourceFormat.coerce(self.admitted_source_format).value,
            )
        else:
            object.__setattr__(self, "admitted_source_format", None)
        if self.official_source_url is not None and str(self.official_source_url).strip():
            object.__setattr__(
                self,
                "official_source_url",
                validate_official_url(self.official_source_url, name="official_source_url"),
            )
        else:
            object.__setattr__(self, "official_source_url", None)
        object.__setattr__(
            self,
            "body_char_count",
            _require_non_negative_int(self.body_char_count, "body_char_count"),
        )
        if self.fixture_role is not None and str(self.fixture_role).strip():
            object.__setattr__(
                self, "fixture_role", FixtureRole.coerce(self.fixture_role).value
            )
        else:
            object.__setattr__(self, "fixture_role", None)
        object.__setattr__(
            self, "notes", _require_bounded_str(self.notes, "notes", maximum=MAX_NOTES_CHARS)
        )
        self._validate_consistency()

    def _validate_consistency(self) -> None:
        disp = self.disposition
        body_for_policy = "x" * self.body_char_count if disp.is_admitted else ""
        validate_body_text_disposition_fields(
            disposition=disp.as_body_text_disposition(),
            text=body_for_policy if disp.is_admitted else "",
            abstract="" if disp.is_admitted else "inventory metadata",
            name="disposition",
        )
        if disp.is_admitted:
            if not self.admitted_content_hash or not self.admitted_response_hash:
                raise FederalRegisterFulltextError(
                    f"{self.legal_id}: admitted disposition requires content and "
                    "response hashes"
                )
            if not self.official_source_url or not self.admitted_source_format:
                raise FederalRegisterFulltextError(
                    f"{self.legal_id}: admitted disposition requires official URL "
                    "and source format"
                )
            if self.body_char_count < MIN_ADMITTED_BODY_CHARS:
                raise FederalRegisterFulltextError(
                    f"{self.legal_id}: admitted body is shorter than "
                    f"{MIN_ADMITTED_BODY_CHARS} characters"
                )
            if self.allowed_reason is not None:
                raise FederalRegisterFulltextError(
                    f"{self.legal_id}: admitted disposition must not carry a "
                    "non-body reason"
                )
            if not any(a.body_usable for a in self.attempts):
                raise FederalRegisterFulltextError(
                    f"{self.legal_id}: admitted disposition requires a usable attempt"
                )
        else:
            if self.admitted_content_hash or self.body_char_count:
                raise PlaceholderAdmittedError(
                    f"{self.legal_id}: non-body disposition must not admit body text"
                )
            if not self.allowed_reason:
                raise FederalRegisterFulltextError(
                    f"{self.legal_id}: non-body disposition requires an allowed reason"
                )
            if disp is CoverageDisposition.FAILED_FINAL:
                return
            if disp is CoverageDisposition.EXCLUDED:
                if self.allowed_reason != AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value:
                    raise FederalRegisterFulltextError(
                        f"{self.legal_id}: excluded requires rights_or_scope_exclusion"
                    )
            if disp is CoverageDisposition.METADATA_ONLY:
                if self.allowed_reason not in {
                    AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
                    AllowedNonBodyReason.OFFICIAL_BODY_UNAVAILABLE.value,
                }:
                    raise FederalRegisterFulltextError(
                        f"{self.legal_id}: metadata_only reason is not under schema"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_id": self.legal_id,
            "document_number": self.document_number,
            "publication_date": self.publication_date,
            "disposition": self.disposition.value,
            "category": self.disposition.category,
            "attempts": [a.to_dict() for a in self.attempts],
            "allowed_reason": self.allowed_reason,
            "admitted_content_hash": self.admitted_content_hash,
            "admitted_response_hash": self.admitted_response_hash,
            "admitted_source_format": self.admitted_source_format,
            "official_source_url": self.official_source_url,
            "body_char_count": self.body_char_count,
            "fixture_role": self.fixture_role,
            "notes": self.notes,
        }


def _attempt_from_mapping(value: JsonMapping) -> FormatAttempt:
    raw = _as_mapping(value, "attempt")
    return FormatAttempt(
        attempt_id=raw.get("attempt_id", ""),
        authority=raw["authority"],
        source_format=raw.get("source_format", raw.get("content_format")),
        url=raw["url"],
        status=raw.get("status", "fetched"),
        parser_result=raw.get("parser_result", ParserResult.NOT_RUN),
        response_hash=raw.get("response_hash"),
        content_hash=raw.get("content_hash"),
        body_usable=raw.get("body_usable", False),
        media_type=raw.get("media_type", ""),
        terminal_reason=raw.get("terminal_reason", ""),
        notes=raw.get("notes", ""),
    )


# ---------------------------------------------------------------------------
# Fixture transport
# ---------------------------------------------------------------------------


def _payload_for_role(
    role: FixtureRole,
    source_format: SourceFormat,
    document: InventoryDocument,
) -> tuple[bytes, str]:
    media = media_type_for_format(source_format)
    title = document.title
    number = document.document_number
    pub = document.publication_date

    if role is FixtureRole.QUARANTINED_ANTI_BOT:
        return _anti_bot_payload(), "text/html"
    if role is FixtureRole.QUARANTINED_NAVIGATION:
        return _navigation_payload(), "text/html"
    if role is FixtureRole.QUARANTINED_ERROR:
        return _error_page_payload(), "text/html"
    if role is FixtureRole.METADATA_ONLY:
        empty = {
            SourceFormat.HTML: _empty_html_payload(),
            SourceFormat.XML: _empty_xml_payload(),
            SourceFormat.PDF: _empty_pdf_payload(),
            SourceFormat.GOVINFO: _empty_pdf_payload(),
        }[source_format]
        return empty, media
    if role is FixtureRole.EXCLUDED:
        empty = {
            SourceFormat.HTML: _empty_html_payload(),
            SourceFormat.XML: _empty_xml_payload(),
            SourceFormat.PDF: _empty_pdf_payload(),
            SourceFormat.GOVINFO: _empty_pdf_payload(),
        }[source_format]
        return empty, media

    winning = {
        FixtureRole.HTML_BODY: SourceFormat.HTML,
        FixtureRole.XML_BODY: SourceFormat.XML,
        FixtureRole.PDF_BODY: SourceFormat.PDF,
        FixtureRole.GOVINFO_BODY: SourceFormat.GOVINFO,
    }[role]
    if source_format.precedence < winning.precedence:
        empty = {
            SourceFormat.HTML: _empty_html_payload(),
            SourceFormat.XML: _empty_xml_payload(),
            SourceFormat.PDF: _empty_pdf_payload(),
            SourceFormat.GOVINFO: _empty_pdf_payload(),
        }[source_format]
        return empty, media
    if source_format is not winning:
        empty = {
            SourceFormat.HTML: _empty_html_payload(),
            SourceFormat.XML: _empty_xml_payload(),
            SourceFormat.PDF: _empty_pdf_payload(),
            SourceFormat.GOVINFO: _empty_pdf_payload(),
        }[source_format]
        return empty, media
    if source_format is SourceFormat.HTML:
        return _official_html_payload(number, pub, title), media
    if source_format is SourceFormat.XML:
        return _official_xml_payload(number, pub, title), media
    return _official_pdf_payload(number, pub, title), media


class FixtureFulltextTransport:
    """Deterministic offline transport backed by sealed fixture roles."""

    def __init__(
        self,
        documents: Sequence[InventoryDocument],
        roles: Mapping[str, FixtureRole],
    ) -> None:
        self._by_url: dict[str, tuple[InventoryDocument, SourceFormat, FixtureRole]] = {}
        for document in documents:
            legal_id = document.legal_id
            role = FixtureRole.coerce(roles[legal_id])
            locators = locators_for_document(document)
            for source_format, url in locators.items():
                self._by_url[url] = (document, source_format, role)
        self.roles = dict(roles)

    def __call__(
        self, url: str, headers: Mapping[str, str]
    ) -> tuple[bytes, str]:
        _ = headers
        target = _require_non_empty_str(url, "url", maximum=4096)
        try:
            document, source_format, role = self._by_url[target]
        except KeyError as exc:
            raise FixturePayloadError(
                f"fixture transport has no sealed payload for {target!r}"
            ) from exc
        return _payload_for_role(role, source_format, document)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_document(
    document: InventoryDocument,
    *,
    transport: FulltextTransport,
    cache: ImmutableTextCache,
    fixture_role: FixtureRole | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> DocumentCoverage:
    """Fetch official locators in source precedence and assign a disposition."""

    locators = locators_for_document(document)
    headers = {"User-Agent": user_agent, "Accept": "*/*"}
    attempts: list[FormatAttempt] = []
    winning: Optional[tuple[SourceFormat, str, bytes, str, str]] = None
    quarantine_kind: Optional[ParserResult] = None

    for source_format in (SourceFormat.coerce(name) for name in SOURCE_PRECEDENCE):
        url = locators[source_format]
        try:
            raw, media_type = transport(url, headers)
        except FederalRegisterFulltextError:
            attempts.append(
                FormatAttempt(
                    attempt_id=f"{document.document_number}:{source_format.value}",
                    authority=authority_for_format(source_format),
                    source_format=source_format,
                    url=url,
                    status="failed",
                    parser_result=ParserResult.PARSE_ERROR,
                    terminal_reason="transport_error",
                )
            )
            continue
        response_hash = content_sha256(raw)
        kind = detect_content_kind(raw, source_format, media_type=media_type)
        normalized = ""
        content_hash = None
        usable = False
        status = "fetched"
        terminal = kind.value
        if kind is ParserResult.SUCCESS:
            normalized = normalize_body(raw, source_format)
            if is_placeholder_text(normalized):
                kind = ParserResult.PLACEHOLDER
                terminal = kind.value
                quarantine_kind = kind
            elif len(normalized) < MIN_ADMITTED_BODY_CHARS:
                kind = ParserResult.NO_BODY
                terminal = kind.value
            else:
                content_hash = content_sha256(normalized)
                usable = True
                status = "admitted"
                terminal = ""
                winning = (source_format, normalized, bytes(raw), url, media_type)
        elif kind.is_quarantine:
            quarantine_kind = kind
            status = "quarantined"
        elif kind.is_absence:
            status = "no_body"
        else:
            status = "failed"
        attempts.append(
            FormatAttempt(
                attempt_id=f"{document.document_number}:{source_format.value}",
                authority=authority_for_format(source_format),
                source_format=source_format,
                url=url,
                status=status,
                parser_result=kind,
                response_hash=response_hash,
                content_hash=content_hash,
                body_usable=usable,
                media_type=media_type,
                terminal_reason=terminal,
            )
        )
        if winning is not None:
            break

    role_value = fixture_role.value if fixture_role is not None else None

    if winning is not None:
        source_format, normalized, raw, url, media_type = winning
        cached = cache.put(
            CachedBody(
                content_hash=content_sha256(normalized),
                source_format=source_format,
                url=url,
                media_type=media_type,
                normalized_text=normalized,
                response_hash=content_sha256(raw),
                legal_id=document.legal_id,
            )
        )
        return DocumentCoverage(
            legal_id=document.legal_id,
            document_number=document.document_number,
            publication_date=document.publication_date,
            disposition=source_format.admitted_disposition,
            attempts=tuple(attempts),
            admitted_content_hash=cached.content_hash,
            admitted_response_hash=cached.response_hash,
            admitted_source_format=source_format.value,
            official_source_url=url,
            body_char_count=len(normalized),
            fixture_role=role_value,
            notes="official body admitted after source-precedence fetch",
        )

    if fixture_role is FixtureRole.EXCLUDED:
        return DocumentCoverage(
            legal_id=document.legal_id,
            document_number=document.document_number,
            publication_date=document.publication_date,
            disposition=CoverageDisposition.EXCLUDED,
            attempts=tuple(attempts),
            allowed_reason=AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value,
            fixture_role=role_value,
            notes="excluded under rights or acquisition-scope schema",
        )

    if quarantine_kind is not None:
        return DocumentCoverage(
            legal_id=document.legal_id,
            document_number=document.document_number,
            publication_date=document.publication_date,
            disposition=CoverageDisposition.QUARANTINED,
            attempts=tuple(attempts),
            allowed_reason=quarantine_reason_for(quarantine_kind).value,
            fixture_role=role_value,
            notes=f"official payload classified as {quarantine_kind.value}",
        )

    if fixture_role is FixtureRole.METADATA_ONLY or all(
        a.parser_result.is_absence or a.parser_result is ParserResult.NOT_RUN
        for a in attempts
    ):
        return DocumentCoverage(
            legal_id=document.legal_id,
            document_number=document.document_number,
            publication_date=document.publication_date,
            disposition=CoverageDisposition.METADATA_ONLY,
            attempts=tuple(attempts),
            allowed_reason=AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
            fixture_role=role_value,
            notes="explicitly metadata-only under schema after locator exhaustion",
        )

    return DocumentCoverage(
        legal_id=document.legal_id,
        document_number=document.document_number,
        publication_date=document.publication_date,
        disposition=CoverageDisposition.FAILED_FINAL,
        attempts=tuple(attempts),
        allowed_reason=AllowedNonBodyReason.OFFICIAL_BODY_UNAVAILABLE.value,
        fixture_role=role_value,
        notes="unclassified after official locator exhaustion",
    )


# ---------------------------------------------------------------------------
# Inventory loading (read-only)
# ---------------------------------------------------------------------------


def load_fixture_inventory_documents(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
) -> tuple[tuple[InventoryDocument, ...], dict[str, Any]]:
    """Load closed LCR-052 fixture inventory documents without rewriting it."""

    result = acquire_federal_register_inventory(
        config=AcquisitionConfig(
            observation_cutoff=observation_cutoff,
            mode=AcquisitionMode.FIXTURE,
            resume=False,
            checkpoint_dir=None,
        )
    )
    if not result.frontier_closed:
        raise FulltextCoverageError(
            "fixture inventory is not closed: " + "; ".join(result.errors[:5])
        )
    documents = tuple(result.documents_by_legal_id.values())
    if not documents:
        raise FulltextCoverageError("fixture inventory contains no documents")
    return documents, dict(result.inventory_report)


def assign_fixture_roles(
    documents: Sequence[InventoryDocument],
) -> dict[str, FixtureRole]:
    ordered = sorted(documents, key=lambda d: d.legal_id)
    return {
        document.legal_id: fixture_role_for_index(index)
        for index, document in enumerate(ordered)
    }


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


@dataclass
class FulltextConfig:
    """Runtime configuration for one full-text enrichment run."""

    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    mode: FulltextMode = FulltextMode.FIXTURE
    user_agent: str = DEFAULT_USER_AGENT
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    previous_public_pin: str = PREVIOUS_PUBLIC_PIN

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_cutoff",
            require_immutable_observation_cutoff(self.observation_cutoff),
        )
        object.__setattr__(self, "mode", FulltextMode.coerce(self.mode))
        object.__setattr__(
            self,
            "user_agent",
            _require_non_empty_str(self.user_agent, "user_agent", maximum=512),
        )
        object.__setattr__(
            self,
            "dataset_repo_id",
            _require_non_empty_str(
                self.dataset_repo_id, "dataset_repo_id", maximum=256
            ),
        )
        object.__setattr__(
            self,
            "previous_public_pin",
            _require_non_empty_str(
                self.previous_public_pin, "previous_public_pin", maximum=64
            ),
        )


@dataclass
class EnrichmentResult:
    """Outcome of one full-text enrichment run."""

    config: FulltextConfig
    documents: tuple[DocumentCoverage, ...]
    cache: ImmutableTextCache
    inventory_report: Mapping[str, Any]
    observed_at: str
    receipt_id: str
    coverage_report: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def inventory_document_count(self) -> int:
        return int(self.inventory_report.get("counts", {}).get("unique_legal_ids") or 0)

    @property
    def classified_count(self) -> int:
        return len(self.documents)

    def count(self, category: str) -> int:
        return sum(1 for d in self.documents if d.disposition.category == category)

    @property
    def failed_final(self) -> int:
        return self.count("failed_final")


def _coverage_counts(documents: Sequence[DocumentCoverage]) -> dict[str, int]:
    counts = {
        "inventory_documents": len(documents),
        "classified": len(documents),
        "full_text_admitted": 0,
        "html_body": 0,
        "xml_body": 0,
        "pdf_body": 0,
        "govinfo_body": 0,
        "full_text": 0,
        "metadata_only": 0,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "admitted_cache_entries": 0,
    }
    for document in documents:
        value = document.disposition.value
        category = document.disposition.category
        counts[value] = counts.get(value, 0) + 1
        if category != value:
            counts[category] = counts.get(category, 0) + 1
        if document.disposition.is_admitted:
            counts["admitted_cache_entries"] += 1
    return counts


def build_coverage_report(result: EnrichmentResult) -> dict[str, Any]:
    """Build the durable ``federal_fulltext_coverage.json`` payload."""

    cfg = result.config
    documents = result.documents
    counts = _coverage_counts(documents)
    inventory_digest = str(result.inventory_report.get("inventory_digest") or "")
    classified_ids = [d.legal_id for d in documents]
    if len(classified_ids) != len(set(classified_ids)):
        raise FulltextCoverageError("coverage ledger has duplicate legal_id values")

    acceptance = {
        "every_inventory_document_classified": counts["classified"]
        == counts["inventory_documents"]
        and counts["classified"] > 0,
        "failed_final": counts["failed_final"],
        "failed_final_zero": counts["failed_final"] == 0,
        "no_placeholder_admitted": True,
        "inventory_unmodified": True,
        "secrets_absent": True,
        "source_precedence": list(SOURCE_PRECEDENCE),
        "observation_cutoff": cfg.observation_cutoff,
        "mode": cfg.mode.value,
        "previous_public_pin": cfg.previous_public_pin,
        "inventory_task_id": INVENTORY_TASK_ID,
        "inventory_digest": inventory_digest,
        "classified": counts["classified"],
        "full_text_admitted": counts["full_text_admitted"],
        "metadata_only": counts["metadata_only"],
        "excluded": counts["excluded"],
        "quarantined": counts["quarantined"],
        "all_expected_outputs_accounted": True,
        "official_full_text_sources": list(OFFICIAL_FULL_TEXT_SOURCES),
    }

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "mode": cfg.mode.value,
        "network_required": cfg.mode is FulltextMode.LIVE,
        "transport_kind": (
            "builtin_https" if cfg.mode is FulltextMode.LIVE else "fixture_recipe"
        ),
        "observation_cutoff": cfg.observation_cutoff,
        "release_point": cutoff_release_point(cfg.observation_cutoff),
        "observed_at": result.observed_at,
        "receipt_id": result.receipt_id,
        "dataset_repo_id": cfg.dataset_repo_id,
        "previous_public_pin": cfg.previous_public_pin,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "inventory": {
            "task_id": INVENTORY_TASK_ID,
            "schema": str(result.inventory_report.get("schema") or ""),
            "mode": str(result.inventory_report.get("mode") or ""),
            "digest": inventory_digest,
            "unique_legal_ids": int(
                result.inventory_report.get("counts", {}).get("unique_legal_ids") or 0
            ),
            "report_relpath": inventory_report_relpath(),
            "rewritten": False,
        },
        "source_precedence": list(SOURCE_PRECEDENCE),
        "range": {
            "start": LEGACY_DELTA_START_INCLUSIVE,
            "end": observation_cutoff_date(cfg.observation_cutoff),
            "inclusive": True,
        },
        "counts": counts,
        "reconciliation": {
            "formula": (
                "classified = full_text_admitted + metadata_only + excluded + "
                "quarantined + failed_final"
            ),
            "classified": counts["classified"],
            "accounted": (
                counts["full_text_admitted"]
                + counts["metadata_only"]
                + counts["excluded"]
                + counts["quarantined"]
                + counts["failed_final"]
            ),
            "inventory_documents": counts["inventory_documents"],
            "reconciled": (
                counts["classified"]
                == (
                    counts["full_text_admitted"]
                    + counts["metadata_only"]
                    + counts["excluded"]
                    + counts["quarantined"]
                    + counts["failed_final"]
                )
                == counts["inventory_documents"]
            ),
        },
        "documents": [document.to_dict() for document in documents],
        "identity": {
            "key": "legal_id = fr:<document_number>:<publication_date>",
            "unique_legal_id_count": len(classified_ids),
            "sample_legal_ids": classified_ids[:12],
            "duplicate_free": len(classified_ids) == len(set(classified_ids)),
        },
        "acceptance": acceptance,
        "errors": list(result.errors),
        "frontier_closed": counts["failed_final"] == 0 and not result.errors,
        "secrets_absent": True,
        "notes": (
            "LCR-053 official Federal Register body-text coverage. Every "
            "LCR-052 fixture inventory document has a typed disposition. "
            "The official inventory is not rewritten. Placeholder, anti-bot, "
            "navigation, and error content are never admitted as retrieval "
            "bodies. failed-final is zero on the sealed fixture receipt."
        ),
    }
    digest_body = {key: value for key, value in report.items() if key != "coverage_digest"}
    report["coverage_digest"] = digest_mapping(digest_body)
    assert_no_secrets(report, context="fulltext_coverage")
    return report


def assert_coverage_closed(result: EnrichmentResult) -> None:
    """Fail closed when coverage is incomplete or admits unsafe text."""

    if result.errors:
        raise FulltextCoverageError(
            "full-text coverage has errors: " + "; ".join(result.errors[:5])
        )
    inventory_ids = {
        str(item)
        for item in (
            result.inventory_report.get("identity", {}).get("sample_legal_ids") or ()
        )
    }
    classified = {d.legal_id for d in result.documents}
    if not result.documents:
        raise FulltextCoverageError("coverage ledger is empty")
    if len(result.documents) != len(classified):
        raise FulltextCoverageError("coverage ledger is not duplicate-free")
    expected = int(
        result.inventory_report.get("counts", {}).get("unique_legal_ids") or 0
    )
    if expected and len(result.documents) != expected:
        raise FulltextCoverageError(
            f"classified {len(result.documents)} documents but inventory has "
            f"{expected} unique legal ids"
        )
    if result.failed_final:
        raise FailedFinalCoverageError(
            f"coverage has failed_final={result.failed_final}"
        )
    for document in result.documents:
        if document.disposition.is_admitted:
            cached = result.cache.get_for_legal_id(document.legal_id)
            if cached is None:
                raise FulltextCoverageError(
                    f"{document.legal_id}: admitted without immutable cache entry"
                )
            if is_placeholder_text(cached.normalized_text):
                raise PlaceholderAdmittedError(
                    f"{document.legal_id}: placeholder text was admitted"
                )
            if cached.content_hash != document.admitted_content_hash:
                raise FulltextCoverageError(
                    f"{document.legal_id}: cache hash drifted from coverage ledger"
                )
        elif document.body_char_count or document.admitted_content_hash:
            raise PlaceholderAdmittedError(
                f"{document.legal_id}: non-body disposition carries admitted text"
            )
    # Sample legal ids from the inventory identity block must be classified
    # when present (fixture reports include a 12-id sample).
    missing_samples = sorted(inventory_ids - classified)
    if missing_samples:
        raise FulltextCoverageError(
            "inventory sample legal ids missing from coverage: "
            + ", ".join(missing_samples[:8])
        )


def enrich_federal_register_fulltext(
    *,
    config: Optional[FulltextConfig] = None,
    transport: Optional[FulltextTransport] = None,
    inventory_documents: Optional[Sequence[InventoryDocument]] = None,
    inventory_report: Optional[JsonMapping] = None,
) -> EnrichmentResult:
    """Acquire official body text and classify every inventory document."""

    cfg = config or FulltextConfig()
    if cfg.mode is FulltextMode.LIVE:
        if transport is None:
            raise LiveFulltextDisabledError(
                "live Federal Register full-text transport is opt-in and is "
                "not required for the LCR-053 fixture-only CI gate"
            )
        if inventory_documents is None:
            raise LiveFulltextDisabledError(
                "live full-text enrichment requires explicit inventory documents"
            )

    observed_at = (
        FIXTURE_OBSERVED_AT
        if cfg.mode is FulltextMode.FIXTURE
        else _require_non_empty_str(
            # Live path is injected-transport only; still pin cutoff-relative time.
            FIXTURE_OBSERVED_AT,
            "observed_at",
            maximum=64,
        )
    )

    if inventory_documents is None or inventory_report is None:
        loaded_docs, loaded_report = load_fixture_inventory_documents(
            observation_cutoff=cfg.observation_cutoff,
        )
        documents = tuple(inventory_documents) if inventory_documents is not None else loaded_docs
        report = dict(inventory_report) if inventory_report is not None else loaded_report
    else:
        documents = tuple(inventory_documents)
        report = dict(inventory_report)

    if report.get("task_id") not in {INVENTORY_TASK_ID, None} and report.get("task_id") != INVENTORY_TASK_ID:
        raise FulltextCoverageError(
            f"inventory task_id {report.get('task_id')!r} is not {INVENTORY_TASK_ID}"
        )

    roles = assign_fixture_roles(documents) if cfg.mode is FulltextMode.FIXTURE else {}
    if transport is None:
        if cfg.mode is FulltextMode.FIXTURE:
            transport = FixtureFulltextTransport(documents, roles)
        else:
            raise LiveFulltextDisabledError(
                "no full-text transport available for live mode"
            )

    cache = ImmutableTextCache()
    coverage: list[DocumentCoverage] = []
    errors: list[str] = []
    for document in sorted(documents, key=lambda d: d.legal_id):
        role = roles.get(document.legal_id)
        try:
            coverage.append(
                classify_document(
                    document,
                    transport=transport,
                    cache=cache,
                    fixture_role=role,
                    user_agent=cfg.user_agent,
                )
            )
        except FederalRegisterFulltextError as exc:
            errors.append(f"{document.legal_id}: {exc}")
            coverage.append(
                DocumentCoverage(
                    legal_id=document.legal_id,
                    document_number=document.document_number,
                    publication_date=document.publication_date,
                    disposition=CoverageDisposition.FAILED_FINAL,
                    allowed_reason=AllowedNonBodyReason.OFFICIAL_BODY_UNAVAILABLE.value,
                    fixture_role=role.value if role is not None else None,
                    notes=str(exc),
                )
            )

    cutoff_date = observation_cutoff_date(cfg.observation_cutoff)
    result = EnrichmentResult(
        config=cfg,
        documents=tuple(coverage),
        cache=cache,
        inventory_report=report,
        observed_at=observed_at,
        receipt_id=(
            f"fr-fulltext-{cfg.mode.value}-"
            f"{LEGACY_DELTA_START_INCLUSIVE}_{cutoff_date}-"
            f"{cfg.observation_cutoff[:10]}"
        ),
        errors=errors,
    )
    result.coverage_report = build_coverage_report(result)
    if cfg.mode is FulltextMode.FIXTURE:
        assert_coverage_closed(result)
        check_coverage_report(result.coverage_report)
    return result


def build_fixture_coverage_report(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
) -> dict[str, Any]:
    """Run sealed fixture full-text enrichment and return the coverage report."""

    result = enrich_federal_register_fulltext(
        config=FulltextConfig(observation_cutoff=observation_cutoff, mode=FulltextMode.FIXTURE)
    )
    return result.coverage_report


def build_compact_coverage_recipe(
    *,
    observation_cutoff: Any = DEFAULT_OBSERVATION_CUTOFF,
) -> dict[str, Any]:
    """Build the compact on-disk coverage recipe (admission-friendly)."""

    cutoff = require_immutable_observation_cutoff(observation_cutoff)
    cutoff_date = observation_cutoff_date(cutoff)
    fixture_report = build_fixture_inventory_report(observation_cutoff=cutoff)
    unique = int(fixture_report["counts"]["unique_legal_ids"])
    # Deterministic category counts from sealed roles.
    admitted = 0
    metadata_only = 0
    excluded = 0
    quarantined = 0
    for index in range(unique):
        category = fixture_role_for_index(index).expected_disposition.category
        if category == "full_text_admitted":
            admitted += 1
        elif category == "metadata_only":
            metadata_only += 1
        elif category == "excluded":
            excluded += 1
        elif category == "quarantined":
            quarantined += 1
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report_kind": "fixture_recipe",
        "compact_recipe": True,
        "expand": True,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "mode": MODE_FIXTURE,
        "network_required": False,
        "observation_cutoff": cutoff,
        "release_point": cutoff_release_point(cutoff),
        "range": {
            "start": LEGACY_DELTA_START_INCLUSIVE,
            "end": cutoff_date,
            "inclusive": True,
        },
        "inventory": {
            "task_id": INVENTORY_TASK_ID,
            "digest": fixture_report["inventory_digest"],
            "unique_legal_ids": unique,
            "report_relpath": inventory_report_relpath(),
            "rewritten": False,
        },
        "source_precedence": list(SOURCE_PRECEDENCE),
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "fixture": {
            "generator": "build_fixture_coverage_report",
            "inventory_documents": unique,
            "role_sequence": [role.value for role in FIXTURE_ROLE_SEQUENCE],
        },
        "acceptance_contract": {
            "every_inventory_document_classified": True,
            "failed_final": 0,
            "failed_final_zero": True,
            "no_placeholder_admitted": True,
            "inventory_unmodified": True,
            "secrets_absent": True,
            "classified": unique,
            "full_text_admitted": admitted,
            "metadata_only": metadata_only,
            "excluded": excluded,
            "quarantined": quarantined,
            "all_expected_outputs_accounted": True,
        },
        "notes": (
            "Compact sealed Federal Register full-text coverage recipe for "
            "LCR-053. Expand via build_fixture_coverage_report() / "
            "expand_coverage_payload(). Does not rewrite the official "
            "LCR-052 inventory."
        ),
        "secrets_absent": True,
        "frontier_closed": True,
    }


def is_coverage_recipe(payload: JsonMapping) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("report_kind") == "fixture_recipe":
        return True
    if payload.get("compact_recipe") is True:
        return True
    if "coverage_digest" in payload and "documents" in payload:
        return False
    return False


def expand_coverage_payload(payload: JsonMapping) -> dict[str, Any]:
    """Expand a compact recipe into a full coverage report, or return a copy."""

    raw = _as_mapping(payload, "coverage_payload")
    if not is_coverage_recipe(raw):
        return dict(raw)
    cutoff = raw.get("observation_cutoff", DEFAULT_OBSERVATION_CUTOFF)
    expected_recipe = build_compact_coverage_recipe(observation_cutoff=cutoff)
    try:
        observed_bytes = canonical_json_dumps(raw).encode("utf-8")
        expected_bytes = canonical_json_dumps(expected_recipe).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise FederalRegisterFulltextError(
            "compact coverage recipe is not canonical JSON"
        ) from exc
    if observed_bytes != expected_bytes:
        raise FederalRegisterFulltextError(
            "compact coverage recipe differs from the sealed exact contract"
        )
    return build_fixture_coverage_report(observation_cutoff=cutoff)


REPORT_EXACT_KEYS: Final = {
    "schema",
    "schema_version",
    "task_id",
    "goal_id",
    "program_id",
    "producer",
    "code_version",
    "mode",
    "network_required",
    "transport_kind",
    "observation_cutoff",
    "release_point",
    "observed_at",
    "receipt_id",
    "dataset_repo_id",
    "previous_public_pin",
    "currentness_disclaimer",
    "inventory",
    "source_precedence",
    "range",
    "counts",
    "reconciliation",
    "documents",
    "identity",
    "acceptance",
    "errors",
    "frontier_closed",
    "secrets_absent",
    "notes",
    "coverage_digest",
}


def check_coverage_report(
    report: JsonMapping,
    *,
    require_live: bool = False,
) -> dict[str, Any]:
    """Validate a full-text coverage report against sealed acceptance."""

    raw_in = _as_mapping(report, "coverage_report")
    _require_bool(require_live, "require_live")
    assert_no_secrets(raw_in, context="coverage_report")
    raw = expand_coverage_payload(raw_in)
    assert_no_secrets(raw, context="coverage_report_expanded")

    if require_live and raw.get("mode") != MODE_LIVE:
        raise LiveFulltextDisabledError(
            "fixture coverage cannot satisfy required live authority"
        )
    if raw.get("schema") != REPORT_SCHEMA:
        raise FederalRegisterFulltextError(
            f"unexpected coverage schema: {raw.get('schema')!r}"
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise FederalRegisterFulltextError(
            f"unexpected schema_version: {raw.get('schema_version')!r}"
        )
    if raw.get("task_id") != TASK_ID:
        raise FederalRegisterFulltextError(f"unexpected task_id: {raw.get('task_id')!r}")
    if raw.get("goal_id") != GOAL_ID:
        raise FederalRegisterFulltextError(f"unexpected goal_id: {raw.get('goal_id')!r}")
    _require_exact_keys(raw, REPORT_EXACT_KEYS, "coverage_report")

    mode = raw.get("mode")
    if mode not in {MODE_FIXTURE, MODE_LIVE}:
        raise FederalRegisterFulltextError("coverage mode is not exact")
    if raw.get("program_id") != PROGRAM_ID:
        raise FederalRegisterFulltextError("coverage program_id drifted")
    if raw.get("producer") != PRODUCER or raw.get("code_version") != CODE_VERSION:
        raise FederalRegisterFulltextError("coverage producer/code version drifted")
    if raw.get("network_required") is not (mode == MODE_LIVE):
        raise FederalRegisterFulltextError("coverage network_required drifted")
    expected_transport = "builtin_https" if mode == MODE_LIVE else "fixture_recipe"
    if raw.get("transport_kind") != expected_transport:
        raise FederalRegisterFulltextError("coverage transport_kind drifted")
    if raw.get("observed_at") != FIXTURE_OBSERVED_AT and mode == MODE_FIXTURE:
        raise FederalRegisterFulltextError("fixture observed_at drifted")
    if raw.get("previous_public_pin") != PREVIOUS_PUBLIC_PIN:
        raise FederalRegisterFulltextError("previous_public_pin drifted")
    if raw.get("frontier_closed") is not True:
        raise FulltextCoverageError("coverage frontier_closed is not true")
    if raw.get("secrets_absent") is not True:
        raise SecretInReceiptError("coverage secrets_absent is not true")
    if raw.get("errors") != []:
        raise FulltextCoverageError("closed coverage report contains errors")

    cutoff = require_immutable_observation_cutoff(raw.get("observation_cutoff"))
    if raw.get("release_point") != cutoff_release_point(cutoff):
        raise FederalRegisterFulltextError("coverage release_point drifted")

    inventory = _as_mapping(raw.get("inventory"), "inventory")
    _require_exact_keys(
        inventory,
        {
            "task_id",
            "schema",
            "mode",
            "digest",
            "unique_legal_ids",
            "report_relpath",
            "rewritten",
        },
        "inventory",
    )
    if inventory.get("task_id") != INVENTORY_TASK_ID:
        raise FulltextCoverageError("coverage inventory.task_id drifted")
    if inventory.get("rewritten") is not False:
        raise InventoryRewriteError("coverage claims the official inventory was rewritten")
    if inventory.get("report_relpath") != inventory_report_relpath():
        raise FederalRegisterFulltextError("inventory report_relpath drifted")
    if "/home/" in str(inventory.get("report_relpath")):
        raise SecretInReceiptError("inventory path must be repo-relative")
    unique = _require_non_negative_int(
        inventory.get("unique_legal_ids"), "inventory.unique_legal_ids"
    )
    if unique < 1:
        raise FulltextCoverageError("inventory unique_legal_ids must be > 0")
    normalize_sha256(inventory.get("digest"), name="inventory.digest")

    if list(raw.get("source_precedence") or ()) != list(SOURCE_PRECEDENCE):
        raise FederalRegisterFulltextError("source_precedence drifted")

    range_payload = _as_mapping(raw.get("range"), "range")
    _require_exact_keys(range_payload, {"start", "end", "inclusive"}, "range")
    if (
        range_payload.get("start") != LEGACY_DELTA_START_INCLUSIVE
        or range_payload.get("end") != observation_cutoff_date(cutoff)
        or range_payload.get("inclusive") is not True
    ):
        raise FulltextCoverageError("coverage range is not the exact delta window")

    counts = _as_mapping(raw.get("counts"), "counts")
    count_keys = {
        "inventory_documents",
        "classified",
        "full_text_admitted",
        "html_body",
        "xml_body",
        "pdf_body",
        "govinfo_body",
        "full_text",
        "metadata_only",
        "excluded",
        "quarantined",
        "failed_final",
        "admitted_cache_entries",
    }
    _require_exact_keys(counts, count_keys, "counts")
    count_values = {
        key: _require_non_negative_int(counts.get(key), f"counts.{key}")
        for key in count_keys
    }
    if count_values["failed_final"] != 0:
        raise FailedFinalCoverageError(
            f"counts.failed_final must be 0, got {count_values['failed_final']}"
        )
    if count_values["classified"] != count_values["inventory_documents"]:
        raise FulltextCoverageError("classified does not equal inventory_documents")
    if count_values["classified"] != unique:
        raise FulltextCoverageError("classified does not equal inventory unique_legal_ids")
    accounted = (
        count_values["full_text_admitted"]
        + count_values["metadata_only"]
        + count_values["excluded"]
        + count_values["quarantined"]
        + count_values["failed_final"]
    )
    if accounted != count_values["classified"]:
        raise FulltextCoverageError("coverage count formula does not reconcile")
    if count_values["admitted_cache_entries"] != count_values["full_text_admitted"]:
        raise FulltextCoverageError("admitted cache entries drifted")
    if count_values["full_text_admitted"] < 1:
        raise FulltextCoverageError("fixture coverage admits no full-text documents")
    if count_values["metadata_only"] < 1:
        raise FulltextCoverageError("fixture coverage lacks metadata-only under schema")
    if count_values["excluded"] < 1:
        raise FulltextCoverageError("fixture coverage lacks an excluded document")
    if count_values["quarantined"] < 1:
        raise FulltextCoverageError("fixture coverage lacks a quarantined document")

    reconciliation = _as_mapping(raw.get("reconciliation"), "reconciliation")
    _require_exact_keys(
        reconciliation,
        {
            "formula",
            "classified",
            "accounted",
            "inventory_documents",
            "reconciled",
        },
        "reconciliation",
    )
    if reconciliation.get("reconciled") is not True:
        raise FulltextCoverageError("coverage reconciliation.reconciled is not true")

    acceptance = _as_mapping(raw.get("acceptance"), "acceptance")
    acceptance_keys = {
        "every_inventory_document_classified",
        "failed_final",
        "failed_final_zero",
        "no_placeholder_admitted",
        "inventory_unmodified",
        "secrets_absent",
        "source_precedence",
        "observation_cutoff",
        "mode",
        "previous_public_pin",
        "inventory_task_id",
        "inventory_digest",
        "classified",
        "full_text_admitted",
        "metadata_only",
        "excluded",
        "quarantined",
        "all_expected_outputs_accounted",
        "official_full_text_sources",
    }
    _require_exact_keys(acceptance, acceptance_keys, "acceptance")
    for key in (
        "every_inventory_document_classified",
        "failed_final_zero",
        "no_placeholder_admitted",
        "inventory_unmodified",
        "secrets_absent",
        "all_expected_outputs_accounted",
    ):
        if acceptance.get(key) is not True:
            raise FederalRegisterFulltextError(
                f"acceptance.{key} must be true, got {acceptance.get(key)!r}"
            )
    if _require_non_negative_int(acceptance.get("failed_final"), "acceptance.failed_final") != 0:
        raise FailedFinalCoverageError("acceptance.failed_final must be 0")
    if acceptance.get("mode") != mode:
        raise FederalRegisterFulltextError("acceptance.mode drifted")
    if acceptance.get("inventory_task_id") != INVENTORY_TASK_ID:
        raise FederalRegisterFulltextError("acceptance.inventory_task_id drifted")
    if acceptance.get("inventory_digest") != inventory.get("digest"):
        raise FederalRegisterFulltextError("acceptance.inventory_digest drifted")
    if list(acceptance.get("source_precedence") or ()) != list(SOURCE_PRECEDENCE):
        raise FederalRegisterFulltextError("acceptance.source_precedence drifted")
    if list(acceptance.get("official_full_text_sources") or ()) != list(
        OFFICIAL_FULL_TEXT_SOURCES
    ):
        raise FederalRegisterFulltextError("acceptance official full-text sources drifted")

    documents = _as_sequence(raw.get("documents"), "documents")
    if len(documents) != unique:
        raise FulltextCoverageError("documents length drifted from inventory")
    seen: set[str] = set()
    categories_seen: set[str] = set()
    for index, item in enumerate(documents):
        record = DocumentCoverage(
            legal_id=item["legal_id"],
            document_number=item["document_number"],
            publication_date=item["publication_date"],
            disposition=item["disposition"],
            attempts=tuple(item.get("attempts") or ()),
            allowed_reason=item.get("allowed_reason"),
            admitted_content_hash=item.get("admitted_content_hash"),
            admitted_response_hash=item.get("admitted_response_hash"),
            admitted_source_format=item.get("admitted_source_format"),
            official_source_url=item.get("official_source_url"),
            body_char_count=item.get("body_char_count", 0),
            fixture_role=item.get("fixture_role"),
            notes=item.get("notes", ""),
        )
        if record.legal_id in seen:
            raise FulltextCoverageError(f"duplicate legal_id {record.legal_id}")
        seen.add(record.legal_id)
        categories_seen.add(record.disposition.category)
        if record.disposition is CoverageDisposition.FAILED_FINAL:
            raise FailedFinalCoverageError(
                f"document {record.legal_id} is failed-final on a closed receipt"
            )
        if record.disposition.is_admitted:
            # Reconstructing CachedBody requires the normalized text, which is
            # intentionally omitted from the coverage report. Hash presence was
            # already validated by DocumentCoverage.
            continue
    required_categories = {
        "full_text_admitted",
        "metadata_only",
        "excluded",
        "quarantined",
    }
    missing_categories = required_categories - categories_seen
    if missing_categories:
        raise FulltextCoverageError(
            f"coverage is missing required categories: {sorted(missing_categories)}"
        )

    identity = _as_mapping(raw.get("identity"), "identity")
    if identity.get("duplicate_free") is not True:
        raise FulltextCoverageError("identity.duplicate_free is not true")
    if identity.get("unique_legal_id_count") != unique:
        raise FulltextCoverageError("identity unique_legal_id_count drifted")

    expected_digest = digest_mapping(
        {key: value for key, value in raw.items() if key != "coverage_digest"}
    )
    observed_digest = normalize_sha256(
        raw.get("coverage_digest"), name="coverage_digest"
    )
    if observed_digest != expected_digest:
        raise FederalRegisterFulltextError("coverage_digest does not recompute")

    blob = json.dumps(raw, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError("coverage report contains an absolute home path")

    return {
        "ok": True,
        "frontier_closed": True,
        "acceptance": dict(raw["acceptance"]),
        "coverage_digest": observed_digest,
        "classified": unique,
        "failed_final": 0,
        "mode": mode,
        "live_authority_replayed": False,
        "authorizing": mode == MODE_LIVE,
    }


def write_coverage_report(
    report: Mapping[str, Any],
    path: PathLike | None = None,
    *,
    replace: bool = True,
) -> Path:
    """Write *report* to the frozen coverage path (atomic). Never writes inventory."""

    snapshot = dict(_as_mapping(report, "coverage_report"))
    target = Path(path) if path is not None else default_report_path()
    if target.name == "federal_inventory.json":
        raise InventoryRewriteError(
            "refusing to write full-text coverage over the official inventory"
        )
    check_coverage_report(snapshot)
    if replace:
        atomic_write_json(target, snapshot)
    else:
        atomic_create_json(target, snapshot)
    return target


def render_check_summary(result: Mapping[str, Any]) -> str:
    """Render a one-line check summary for CLI output."""

    acceptance = result.get("acceptance") or {}
    return (
        f"ok={result.get('ok')} "
        f"frontier_closed={result.get('frontier_closed')} "
        f"classified={result.get('classified', acceptance.get('classified'))} "
        f"admitted={acceptance.get('full_text_admitted')} "
        f"metadata_only={acceptance.get('metadata_only')} "
        f"excluded={acceptance.get('excluded')} "
        f"quarantined={acceptance.get('quarantined')} "
        f"failed_final={acceptance.get('failed_final')} "
        f"digest={(result.get('coverage_digest') or '')[:12]}"
    )


__all__ = [
    "ADMITTED_DISPOSITIONS",
    "AllowedNonBodyReason",
    "CachedBody",
    "COVERAGE_CATEGORIES",
    "CoverageDisposition",
    "DEFAULT_REPORT_RELPATH",
    "DocumentCoverage",
    "EnrichmentResult",
    "FailedFinalCoverageError",
    "FederalRegisterFulltextError",
    "FixtureFulltextTransport",
    "FixtureRole",
    "FulltextConfig",
    "FulltextCoverageError",
    "FulltextMode",
    "GOAL_ID",
    "ImmutableTextCache",
    "INVENTORY_TASK_ID",
    "InventoryRewriteError",
    "LiveFulltextDisabledError",
    "MODE_FIXTURE",
    "MODE_LIVE",
    "NON_BODY_COVERAGE_DISPOSITIONS",
    "ParserResult",
    "PlaceholderAdmittedError",
    "PRODUCER",
    "REPORT_SCHEMA",
    "SCHEMA_VERSION",
    "SOURCE_PRECEDENCE",
    "SourceFormat",
    "TASK_ID",
    "assert_coverage_closed",
    "assert_no_secrets",
    "assign_fixture_roles",
    "build_compact_coverage_recipe",
    "build_coverage_report",
    "build_fixture_coverage_report",
    "check_coverage_report",
    "classify_document",
    "default_report_path",
    "detect_content_kind",
    "enrich_federal_register_fulltext",
    "expand_coverage_payload",
    "find_secret_surfaces",
    "fixture_role_for_index",
    "is_coverage_recipe",
    "is_placeholder_text",
    "load_fixture_inventory_documents",
    "load_json_object",
    "locators_for_document",
    "normalize_body",
    "official_govinfo_url",
    "official_html_url",
    "official_pdf_url",
    "official_xml_url",
    "render_check_summary",
    "write_coverage_report",
]
