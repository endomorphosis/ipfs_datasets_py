"""Canonical exact-51 Open US Law corpus materialization and quarantine (OUL-024).

This module owns the legal corpus projection for the
``open-us-law-sparse-graphrag/v1`` release. It turns source rows into
canonical statutory sections and structure-aware text chunks with
deterministic IDs and provenance, then isolates every non-default family
into an explicit configuration or the quarantine.

Design invariants
-----------------
* Default configuration is current exact-51 state/DC statutes only.
* Every source row receives **exactly one** disposition and **exactly one**
  release configuration.
* Canonical sections and chunks carry durable ``legal_id`` / ``chunk_id``,
  ``entry_cid``, ``source_cid``, ``text_hash``, and acquisition provenance.
  Positional tokens such as ``row-N`` are rejected as durable identity.
* Structure-aware chunks obey the pinned GTE 512-token ceiling. The 4,096
  value is a physical shard/row bound, never a token limit.
* Duplicate, contaminated, historical, Puerto Rico, federal, constitution,
  recovery, and unsupported rows cannot satisfy the exact-51 gate. They land
  in named non-default configurations or quarantine.
* Recovery and quarantine rows never increment corpus, chunk, BM25, vector,
  or graph family counts.
* Deterministic fixtures exercise the software contract. They never
  authorize a live exact-51 production corpus, publication, or release.
* No network I/O and no Parquet I/O.

Depends on OUL-001 (bucket inventory), OUL-005 (identity schema), and
OUL-023 (acquisition-gap closure).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ADR_PATH,
    ALL_CONFIGURATION_NAMES,
    DEFAULT_CONFIGURATION as SCHEMA_DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_MODEL_TOKEN_CEILING,
    EXACT_51_JURISDICTION_CODES,
    EXACT_51_JURISDICTIONS,
    EXPECTED_JURISDICTION_COUNT,
    FEDERAL_JURISDICTION_CODE,
    HIERARCHY_KEYS,
    LEGAL_ID_PREFIX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    NON_DEFAULT_CONFIGURATION_NAMES,
    PUERTO_RICO_CODE,
    RELEASE_PROFILE,
    SOURCE_BUCKET,
    AdmissionStatus,
    ConfigurationBoundaryError,
    DocumentKind,
    Exact51GateError,
    Hierarchy,
    JurisdictionSetError,
    MissingIdentityFieldError,
    OpenUsLawSchemaError,
    PositionalIdentityError,
    ReleaseConfiguration,
    StatuteIdentity,
    StatuteStatus,
    build_legal_id,
    canonical_json_dumps,
    classify_configuration,
    compute_text_hash,
    configuration_boundary_policy,
    content_sha256,
    digest_mapping,
    example_constitution_payload,
    example_default_statute_payload,
    example_federal_payload,
    example_historical_payload,
    example_puerto_rico_payload,
    example_quarantine_payload,
    example_recovery_payload,
    infer_configuration,
    normalize_code_family,
    normalize_edition,
    normalize_hierarchy,
    normalize_jurisdiction_code,
    reject_positional_durable_identity,
    validate_corpus_identity,
    validate_entry_cid,
    validate_exact_51_gate,
    validate_source_cid,
    validate_text_cid,
    validate_text_hash,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
    DEFAULT_MAX_CHUNKS_PER_SECTION,
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TOKENIZER_ID,
    chunk_statute,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-corpus-v1"
FIXTURE_SCHEMA_VERSION: Final = "open-us-law-corpus-admission-v1"
TASK_ID: Final = "OUL-024"
GOAL_ID: Final = "OUL-G030"
PRODUCER: Final = "open_us_law_corpus.py"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
BUNDLE: Final = "canonical-corpus"
IDENTITY_SCHEMA_VERSION: Final = "open-us-law-identity-schema-v1"
TRANSFORMATION_VERSION: Final = "open-us-law-corpus-transform-v1"

DEFAULT_CONFIGURATION: Final = SCHEMA_DEFAULT_CONFIGURATION
DEFAULT_EDITION: Final = "2024-official"
DEFAULT_CODE_FAMILY: Final = "statutes"
DEFAULT_ACQUISITION_TIME: Final = "2026-04-01T00:00:00Z"
DEFAULT_RELEASE_POINT: Final = content_sha256("oul-024-canonical-corpus-v1")
MIN_USABLE_CHARS: Final = 16
DEFAULT_MODEL_TOKEN_LIMIT: Final = DEFAULT_MODEL_TOKEN_CEILING

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_EXACT_51_PRODUCTION: Final = False

CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a package was retrieved "
    "or sealed; they are not a claim that the codified text is legally current as "
    "of wall-clock time. Retrieval output is a research aid and is not a "
    "substitute for the official source."
)

CANONICAL_COUNT_FAMILIES: Final = frozenset(
    {
        "corpus",
        "chunks",
        "bm25",
        "bm25_documents",
        "bm25_postings",
        "vector",
        "vectors",
        "graph",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency_out",
        "graph_adjacency_in",
    }
)

REPORT_RELATIVE_PATH: Final = "docs/reports/open_us_law_reindex/corpus_admission.json"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH: Final = _REPO_ROOT / REPORT_RELATIVE_PATH

DEPENDENCY_EVIDENCE: Final = (
    (
        "OUL-001",
        "docs/reports/open_us_law_reindex/bucket_snapshot.json",
        "open-us-law-bucket-snapshot-v1",
    ),
    (
        "OUL-005",
        "data/legal/open_us_law/release.schema.json",
        "open-us-law-identity-schema-v1",
    ),
    (
        "OUL-023",
        "docs/reports/open_us_law_reindex/acquisition_refill_closure.json",
        "open-us-law-acquisition-refill-v1",
    ),
)

# Families that may be chunked (viewer-visible corpus configs).
CHUNKABLE_CONFIGURATIONS: Final = frozenset(
    {
        ReleaseConfiguration.STATE_STATUTES_EXACT_51,
        ReleaseConfiguration.FEDERAL_USCODE,
        ReleaseConfiguration.PUERTO_RICO,
        ReleaseConfiguration.CONSTITUTIONS,
        ReleaseConfiguration.HISTORICAL,
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawCorpusError(ValueError):
    """Base error for Open US Law corpus materialization."""

    code: str = "open_us_law_corpus_error"


class DispositionError(OpenUsLawCorpusError):
    """Raised when a source row lacks a unique valid disposition."""

    code = "disposition_invalid"


class AdmissionLedgerError(OpenUsLawCorpusError):
    """Raised when the admission ledger is incomplete or inconsistent."""

    code = "admission_ledger_invalid"


class IsolationError(OpenUsLawCorpusError):
    """Raised when a non-default family leaks into the exact-51 gate."""

    code = "isolation_violated"


class ContaminationError(OpenUsLawCorpusError):
    """Raised when contaminated text is treated as admitted default law."""

    code = "contamination_not_isolated"


class IncompleteIdentityError(OpenUsLawCorpusError):
    """Raised when an admitted row is missing durable identity or provenance."""

    code = "incomplete_identity"


class CorpusFixtureError(OpenUsLawCorpusError):
    """Raised when a compact admission recipe is malformed."""

    code = "corpus_fixture_invalid"


class ChunkIdentityError(OpenUsLawCorpusError):
    """Raised when a structure-aware chunk lacks a deterministic identity."""

    code = "chunk_identity_invalid"


class Exact51AuthorizationError(OpenUsLawCorpusError):
    """Raised when fixture materialization is treated as a production seal."""

    code = "exact_51_authorization_rejected"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RowDisposition(str, Enum):
    """Exactly-one ledger disposition assigned to every source row."""

    ADMITTED = "admitted"
    ISOLATED = "isolated"
    RECOVERY = "recovery"
    QUARANTINED = "quarantined"

    @classmethod
    def coerce(cls, value: Any) -> "RowDisposition":
        if isinstance(value, RowDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "admit": cls.ADMITTED,
            "include": cls.ADMITTED,
            "included": cls.ADMITTED,
            "isolate": cls.ISOLATED,
            "non_default": cls.ISOLATED,
            "configuration": cls.ISOLATED,
            "recover": cls.RECOVERY,
            "quarantine": cls.QUARANTINED,
            "exclude": cls.QUARANTINED,
            "excluded": cls.QUARANTINED,
            "reject": cls.QUARANTINED,
            "rejected": cls.QUARANTINED,
            "duplicate": cls.QUARANTINED,
            "contaminated": cls.QUARANTINED,
            "unsupported": cls.QUARANTINED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DispositionError(f"unknown row disposition: {value!r}")

    def to_admission_status(self) -> AdmissionStatus:
        if self is RowDisposition.ADMITTED:
            return AdmissionStatus.ADMITTED
        if self is RowDisposition.RECOVERY:
            return AdmissionStatus.RECOVERY
        if self is RowDisposition.QUARANTINED:
            return AdmissionStatus.QUARANTINED
        return AdmissionStatus.EXCLUDED


class IsolationReason(str, Enum):
    """Why a row is kept out of the default exact-51 configuration."""

    NONE = "none"
    FEDERAL = "federal"
    PUERTO_RICO = "puerto_rico"
    CONSTITUTION = "constitution"
    HISTORICAL = "historical"
    RECOVERY = "recovery"
    DUPLICATE = "duplicate"
    CONTAMINATED = "contaminated"
    UNSUPPORTED = "unsupported"
    EXPLICIT_QUARANTINE = "explicit_quarantine"

    @classmethod
    def coerce(cls, value: Any) -> "IsolationReason":
        if isinstance(value, IsolationReason):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "": cls.NONE,
            "default": cls.NONE,
            "admitted": cls.NONE,
            "uscode": cls.FEDERAL,
            "federal_uscode": cls.FEDERAL,
            "pr": cls.PUERTO_RICO,
            "constitutions": cls.CONSTITUTION,
            "history": cls.HISTORICAL,
            "superseded": cls.HISTORICAL,
            "repealed": cls.HISTORICAL,
            "recover": cls.RECOVERY,
            "dup": cls.DUPLICATE,
            "contamination": cls.CONTAMINATED,
            "unknown": cls.UNSUPPORTED,
            "quarantine": cls.EXPLICIT_QUARANTINE,
            "quarantined": cls.EXPLICIT_QUARANTINE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise IsolationError(f"unknown isolation reason: {value!r}")

    @property
    def configuration(self) -> ReleaseConfiguration:
        return {
            IsolationReason.NONE: ReleaseConfiguration.STATE_STATUTES_EXACT_51,
            IsolationReason.FEDERAL: ReleaseConfiguration.FEDERAL_USCODE,
            IsolationReason.PUERTO_RICO: ReleaseConfiguration.PUERTO_RICO,
            IsolationReason.CONSTITUTION: ReleaseConfiguration.CONSTITUTIONS,
            IsolationReason.HISTORICAL: ReleaseConfiguration.HISTORICAL,
            IsolationReason.RECOVERY: ReleaseConfiguration.RECOVERY,
            IsolationReason.DUPLICATE: ReleaseConfiguration.QUARANTINE,
            IsolationReason.CONTAMINATED: ReleaseConfiguration.QUARANTINE,
            IsolationReason.UNSUPPORTED: ReleaseConfiguration.QUARANTINE,
            IsolationReason.EXPLICIT_QUARANTINE: ReleaseConfiguration.QUARANTINE,
        }[self]


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_SUFFIX_RE = re.compile(r"#chunk=(?P<index>\d+)$")
_NAV_RE = re.compile(
    r"skip to (?:main )?content|click here to (?:continue|subscribe)|"
    r"cookie (?:policy|banner|consent)|subscribe to (?:our )?newsletter|"
    r"\bhome\s+[>|]\s+statutes\s+[>|]\s+search\b",
    re.IGNORECASE,
)
_FOOTER_RE = re.compile(
    r"all rights reserved|privacy policy|terms of (?:use|service)",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r"\blorem ipsum\b|\[insert[^\]]*\]|todo:\s*add (?:statute|text)|"
    r"placeholder text|coming soon|under construction|"
    r"text not available|lorem-ipsum",
    re.IGNORECASE,
)
_STATUTORY_SIGNAL_RE = re.compile(
    r"\b(?:shall|must|may not|section|subsection|chapter|title|article|"
    r"provided that|offense|penalty|licensed)\b|§",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ABSOLUTE_POSIX_RE = re.compile(
    r"(?:(?:/home|/Users|/tmp|/var|/opt|/usr/local|/mnt|/media|/data|"
    r"/workspace|/root)/\S+)"
)
_ABSOLUTE_WINDOWS_RE = re.compile(r"(?:[A-Za-z]:\\[^\s\"']+|\\\\[^\s\"']+)")
_FILE_URI_RE = re.compile(r"file:///[^\s\"']+", re.IGNORECASE)
_PATH_FIELD_NAMES: Final = frozenset(
    {
        "source_path",
        "local_path",
        "path",
        "file_path",
        "absolute_path",
        "workspace_path",
        "cache_path",
        "origin_path",
        "raw_path",
    }
)


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenUsLawCorpusError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise OpenUsLawCorpusError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise OpenUsLawCorpusError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value", *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenUsLawCorpusError(f"{name} must be an integer")
    if value < 0:
        raise OpenUsLawCorpusError(f"{name} must be >= 0")
    return value


def file_sha256(path: PathLike) -> str:
    target = Path(path)
    hasher = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def normalize_corpus_text(text: Any, *, name: str = "text") -> str:
    raw = _require_non_empty_str(text, name, maximum=4_000_000)
    return unicodedata.normalize("NFC", raw)


def default_code_family_for(
    jurisdiction_code: str,
    configuration: ReleaseConfiguration,
) -> str:
    if configuration is ReleaseConfiguration.CONSTITUTIONS:
        if jurisdiction_code == FEDERAL_JURISDICTION_CODE:
            return "us-constitution"
        return f"{jurisdiction_code.lower()}-constitution"
    if configuration is ReleaseConfiguration.FEDERAL_USCODE:
        return "usc"
    if configuration is ReleaseConfiguration.PUERTO_RICO:
        return "laws-of-puerto-rico"
    if jurisdiction_code == "OR":
        return "ors"
    if jurisdiction_code == "DC":
        return "dc-official-code"
    return DEFAULT_CODE_FAMILY


def build_chunk_id(parent_legal_id: str, chunk_index: int) -> str:
    parent = _require_non_empty_str(parent_legal_id, "parent_legal_id", maximum=1024)
    try:
        reject_positional_durable_identity(parent, name="parent_legal_id")
    except PositionalIdentityError as exc:
        raise ChunkIdentityError(str(exc)) from exc
    if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 0:
        raise ChunkIdentityError("chunk_index must be a non-negative integer")
    return f"{parent}#chunk={chunk_index:04d}"


def parse_chunk_id(chunk_id: str) -> tuple[str, int]:
    text = _require_non_empty_str(chunk_id, "chunk_id", maximum=1024)
    reject_positional_durable_identity(text, name="chunk_id")
    match = _CHUNK_SUFFIX_RE.search(text)
    if not match:
        raise ChunkIdentityError(f"not a chunk id: {chunk_id!r}")
    parent = text[: match.start()]
    if not parent:
        raise ChunkIdentityError(f"chunk id missing parent legal_id: {chunk_id!r}")
    return parent, int(match.group("index"))


def _peek_jurisdiction(row: Mapping[str, Any]) -> Any:
    if row.get("jurisdiction_code") not in (None, ""):
        return row.get("jurisdiction_code")
    if row.get("jurisdiction") not in (None, ""):
        return row.get("jurisdiction")
    return row.get("state_code") or row.get("state")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub(" ", text)


def scrub_local_paths_in_text(text: str) -> str:
    if not isinstance(text, str):
        raise OpenUsLawCorpusError("text must be a string")
    cleaned = _FILE_URI_RE.sub("[scrubbed-local-uri]", text)
    cleaned = _ABSOLUTE_WINDOWS_RE.sub("[scrubbed-local-path]", cleaned)
    cleaned = _ABSOLUTE_POSIX_RE.sub("[scrubbed-local-path]", cleaned)
    return cleaned


def scrub_mapping_paths(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise OpenUsLawCorpusError("payload must be a mapping")

    def _walk(value: Any, *, key: Optional[str] = None) -> Any:
        if isinstance(value, Mapping):
            return {str(k): _walk(v, key=str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(item, key=key) for item in value]
        if isinstance(value, str):
            if key is not None and key.lower() in _PATH_FIELD_NAMES:
                cleaned = scrub_local_paths_in_text(value)
                if cleaned.startswith("/") or re.match(r"^[A-Za-z]:\\", cleaned):
                    return None
                return cleaned
            if (
                _ABSOLUTE_POSIX_RE.search(value)
                or _ABSOLUTE_WINDOWS_RE.search(value)
                or _FILE_URI_RE.search(value)
            ):
                return scrub_local_paths_in_text(value)
            return value
        return value

    return _walk(dict(payload))


# ---------------------------------------------------------------------------
# Text quality / contamination
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextQuality:
    usable_chars: int
    navigation_detected: bool
    footer_detected: bool
    placeholder_detected: bool
    statutory_signal: bool
    contaminated: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contaminated": self.contaminated,
            "footer_detected": self.footer_detected,
            "navigation_detected": self.navigation_detected,
            "placeholder_detected": self.placeholder_detected,
            "reasons": list(self.reasons),
            "statutory_signal": self.statutory_signal,
            "usable_chars": self.usable_chars,
        }


def assess_text_quality(text: Any, *, min_usable_chars: int = MIN_USABLE_CHARS) -> TextQuality:
    if text is None:
        raw = ""
    elif not isinstance(text, str):
        raise OpenUsLawCorpusError("text must be a string or null")
    else:
        raw = unicodedata.normalize("NFC", text)
    stripped = _strip_html(raw)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    usable = len(stripped)
    navigation = bool(_NAV_RE.search(stripped))
    footer = bool(_FOOTER_RE.search(stripped))
    placeholder = bool(_PLACEHOLDER_RE.search(stripped))
    statutory = bool(_STATUTORY_SIGNAL_RE.search(stripped))
    reasons: list[str] = []
    contaminated = False
    if placeholder:
        contaminated = True
        reasons.append("placeholder_text")
    if usable < min_usable_chars:
        contaminated = True
        reasons.append("below_min_usable_chars")
    if (navigation or footer) and not statutory:
        contaminated = True
        if navigation:
            reasons.append("navigation_chrome")
        if footer:
            reasons.append("footer_chrome")
    if (navigation or footer) and statutory and usable < max(min_usable_chars * 4, 64):
        contaminated = True
        reasons.append("chrome_dominates_short_body")
    return TextQuality(
        usable_chars=usable,
        navigation_detected=navigation,
        footer_detected=footer,
        placeholder_detected=placeholder,
        statutory_signal=statutory,
        contaminated=contaminated,
        reasons=tuple(reasons),
    )


def looks_contaminated(row: Mapping[str, Any]) -> bool:
    if bool(row.get("contaminated")) or bool(row.get("is_contaminated")):
        return True
    quality = row.get("text_quality")
    if isinstance(quality, Mapping) and quality.get("contaminated") is True:
        return True
    isolation = str(row.get("isolation_reason") or "").strip().lower()
    if isolation in {"contaminated", "contamination"}:
        return True
    text = row.get("text") or row.get("body") or ""
    if not isinstance(text, str):
        return True
    if not text.strip():
        return False
    return assess_text_quality(text).contaminated


def is_unsupported_row(row: Mapping[str, Any]) -> bool:
    if bool(row.get("unsupported")) or bool(row.get("is_unsupported")):
        return True
    isolation = str(row.get("isolation_reason") or "").strip().lower()
    if isolation in {"unsupported", "unknown"}:
        return True
    kind = str(row.get("row_kind") or row.get("kind") or "").strip().lower()
    if kind in {"unsupported", "unknown", "unclassified"}:
        return True
    raw_jurisdiction = _peek_jurisdiction(row)
    if raw_jurisdiction not in (None, ""):
        try:
            normalize_jurisdiction_code(raw_jurisdiction, allow_non_default=True)
        except (JurisdictionSetError, OpenUsLawSchemaError):
            return True
        return False
    document_kind = str(row.get("document_kind") or row.get("kind") or "").strip().lower()
    if document_kind in {"federal", "uscode", "usc", "puerto_rico", "pr", "constitution"}:
        return False
    family = str(row.get("code_family") or "").strip().lower()
    if "constitution" in family or family in {"usc", "uscode"}:
        return False
    return True


def is_recovery_row(row: Mapping[str, Any]) -> bool:
    if bool(row.get("is_recovery")) or bool(row.get("recovery")):
        return True
    status = str(row.get("admission_status") or "").strip().lower()
    if status in {"recovery"}:
        return True
    kind = str(row.get("row_kind") or row.get("kind") or row.get("record_type") or "").strip().lower()
    if kind in {"recovery", "workflow", "source_recovery"}:
        return True
    isolation = str(row.get("isolation_reason") or "").strip().lower()
    if isolation == "recovery":
        return True
    configuration = str(row.get("configuration") or "").strip().lower().replace("-", "_")
    return configuration == "recovery"


def is_duplicate_marker(row: Mapping[str, Any]) -> bool:
    if bool(row.get("duplicate")) or bool(row.get("is_duplicate")):
        return True
    isolation = str(row.get("isolation_reason") or "").strip().lower()
    if isolation == "duplicate":
        return True
    disposition = str(row.get("disposition") or "").strip().lower()
    return disposition == "duplicate"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Classification:
    disposition: RowDisposition
    configuration: ReleaseConfiguration
    isolation_reason: IsolationReason
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration": self.configuration.value,
            "disposition": self.disposition.value,
            "isolation_reason": self.isolation_reason.value,
            "reason": self.reason,
            "satisfies_exact_51_gate": self.configuration.satisfies_exact_51_gate,
        }


def _default_reason(isolation: IsolationReason) -> str:
    return {
        IsolationReason.NONE: (
            "current exact-51 official state or DC statute with complete identity"
        ),
        IsolationReason.FEDERAL: "federal US Code isolated from the default exact-51 set",
        IsolationReason.PUERTO_RICO: "Puerto Rico isolated as an explicit non-default configuration",
        IsolationReason.CONSTITUTION: "constitution isolated as an explicit non-default configuration",
        IsolationReason.HISTORICAL: "historical, repealed, or superseded row isolated from current default",
        IsolationReason.RECOVERY: "recovery or workflow record excluded from canonical search families",
        IsolationReason.DUPLICATE: "duplicate legal_id or entry_cid isolated in quarantine",
        IsolationReason.CONTAMINATED: (
            "navigation, footer, placeholder, or unusable text isolated in quarantine"
        ),
        IsolationReason.UNSUPPORTED: (
            "unsupported jurisdiction, missing identity, or unclassifiable row quarantined"
        ),
        IsolationReason.EXPLICIT_QUARANTINE: "explicit quarantine or rejected admission",
    }[isolation]


def classify_source_row(row: Mapping[str, Any]) -> Classification:
    """Return the fail-closed disposition and configuration for one source row."""

    if not isinstance(row, Mapping):
        raise OpenUsLawCorpusError("source row must be a mapping")

    explicit_reason = _optional_str(row.get("admission_reason") or row.get("reason"))

    if is_recovery_row(row):
        isolation = IsolationReason.RECOVERY
        return Classification(
            disposition=RowDisposition.RECOVERY,
            configuration=ReleaseConfiguration.RECOVERY,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )

    admission = str(row.get("admission_status") or "").strip().lower()
    if admission in {"quarantined", "quarantine", "rejected", "reject"}:
        isolation = IsolationReason.EXPLICIT_QUARANTINE
        return Classification(
            disposition=RowDisposition.QUARANTINED,
            configuration=ReleaseConfiguration.QUARANTINE,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )

    if looks_contaminated(row):
        isolation = IsolationReason.CONTAMINATED
        return Classification(
            disposition=RowDisposition.QUARANTINED,
            configuration=ReleaseConfiguration.QUARANTINE,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )

    if is_duplicate_marker(row):
        isolation = IsolationReason.DUPLICATE
        return Classification(
            disposition=RowDisposition.QUARANTINED,
            configuration=ReleaseConfiguration.QUARANTINE,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )

    if is_unsupported_row(row):
        isolation = IsolationReason.UNSUPPORTED
        return Classification(
            disposition=RowDisposition.QUARANTINED,
            configuration=ReleaseConfiguration.QUARANTINE,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )

    try:
        configuration = classify_configuration(row)
    except (ConfigurationBoundaryError, OpenUsLawSchemaError, JurisdictionSetError) as exc:
        isolation = IsolationReason.UNSUPPORTED
        return Classification(
            disposition=RowDisposition.QUARANTINED,
            configuration=ReleaseConfiguration.QUARANTINE,
            isolation_reason=isolation,
            reason=explicit_reason or f"unclassifiable row: {exc}",
        )

    if configuration is ReleaseConfiguration.RECOVERY:
        isolation = IsolationReason.RECOVERY
        return Classification(
            disposition=RowDisposition.RECOVERY,
            configuration=configuration,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )
    if configuration is ReleaseConfiguration.QUARANTINE:
        isolation = IsolationReason.EXPLICIT_QUARANTINE
        return Classification(
            disposition=RowDisposition.QUARANTINED,
            configuration=configuration,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )
    if configuration is ReleaseConfiguration.FEDERAL_USCODE:
        isolation = IsolationReason.FEDERAL
        return Classification(
            disposition=RowDisposition.ISOLATED,
            configuration=configuration,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )
    if configuration is ReleaseConfiguration.PUERTO_RICO:
        isolation = IsolationReason.PUERTO_RICO
        return Classification(
            disposition=RowDisposition.ISOLATED,
            configuration=configuration,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )
    if configuration is ReleaseConfiguration.CONSTITUTIONS:
        isolation = IsolationReason.CONSTITUTION
        return Classification(
            disposition=RowDisposition.ISOLATED,
            configuration=configuration,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )
    if configuration is ReleaseConfiguration.HISTORICAL:
        isolation = IsolationReason.HISTORICAL
        return Classification(
            disposition=RowDisposition.ISOLATED,
            configuration=configuration,
            isolation_reason=isolation,
            reason=explicit_reason or _default_reason(isolation),
        )
    if configuration is ReleaseConfiguration.STATE_STATUTES_EXACT_51:
        return Classification(
            disposition=RowDisposition.ADMITTED,
            configuration=configuration,
            isolation_reason=IsolationReason.NONE,
            reason=explicit_reason or _default_reason(IsolationReason.NONE),
        )
    isolation = IsolationReason.UNSUPPORTED
    return Classification(
        disposition=RowDisposition.QUARANTINED,
        configuration=ReleaseConfiguration.QUARANTINE,
        isolation_reason=isolation,
        reason=explicit_reason or _default_reason(isolation),
    )


# ---------------------------------------------------------------------------
# Identity / provenance construction
# ---------------------------------------------------------------------------


def _hierarchy_from_row(row: Mapping[str, Any]) -> Hierarchy:
    hierarchy_value = row.get("hierarchy")
    if hierarchy_value in (None, ""):
        hierarchy_value = {
            key: row.get(key)
            for key in HIERARCHY_KEYS
            if row.get(key) not in (None, "")
        }
    if not hierarchy_value:
        raise MissingIdentityFieldError("hierarchy.section is required")
    hierarchy = normalize_hierarchy(hierarchy_value)
    hierarchy.require_section()
    return hierarchy


def _document_kind_for(configuration: ReleaseConfiguration, row: Mapping[str, Any]) -> DocumentKind:
    raw = row.get("document_kind") or row.get("kind")
    if raw not in (None, "") and str(raw).strip().lower() not in {
        "historical",
        "history",
        "recovery",
        "quarantine",
        "quarantined",
    }:
        try:
            return DocumentKind.coerce(raw)
        except OpenUsLawSchemaError:
            pass
    if configuration is ReleaseConfiguration.CONSTITUTIONS:
        return DocumentKind.CONSTITUTION
    if configuration is ReleaseConfiguration.PUERTO_RICO:
        return DocumentKind.PUERTO_RICO
    if configuration is ReleaseConfiguration.FEDERAL_USCODE:
        return DocumentKind.FEDERAL
    return DocumentKind.STATUTE


def synthesize_source_cid(row: Mapping[str, Any], identity_label: str) -> str:
    existing = row.get("source_cid")
    if existing not in (None, ""):
        return validate_source_cid(existing)
    seed = (
        row.get("official_source_url")
        or row.get("source_url")
        or row.get("page_url")
        or identity_label
    )
    return content_sha256(f"oul-source|{seed}|{identity_label}")


def synthesize_entry_cid(row: Mapping[str, Any], legal_id: str, text_hash: str) -> str:
    existing = row.get("entry_cid")
    if existing not in (None, ""):
        return validate_entry_cid(existing)
    return content_sha256(f"oul-entry|{legal_id}|{text_hash}")


def synthesize_text_cid(row: Mapping[str, Any], text_hash: str) -> str:
    existing = row.get("text_cid")
    if existing not in (None, ""):
        return validate_text_cid(existing)
    return f"sha256:{text_hash}"


def synthesize_receipt_cid(row: Mapping[str, Any], *, field: str, seed: str) -> str:
    existing = row.get(field)
    if existing not in (None, ""):
        return validate_source_cid(existing, name=field)
    return content_sha256(f"oul-{field}|{seed}")


def build_section_identity(
    row: Mapping[str, Any],
    *,
    configuration: ReleaseConfiguration,
) -> dict[str, Any]:
    """Build durable section identity, synthesizing missing CID/hash fields."""

    jurisdiction = normalize_jurisdiction_code(
        _peek_jurisdiction(row),
        allow_non_default=True,
    )
    hierarchy = _hierarchy_from_row(row)
    edition = normalize_edition(row.get("edition") or DEFAULT_EDITION)
    document_kind = _document_kind_for(configuration, row)
    status = StatuteStatus.coerce(row.get("status") or row.get("statute_status") or StatuteStatus.CURRENT)
    code_family = normalize_code_family(
        row.get("code_family")
        or row.get("codeFamily")
        or default_code_family_for(jurisdiction, configuration)
    )
    legal_id = build_legal_id(
        document_kind=document_kind,
        jurisdiction_code=jurisdiction,
        code_family=code_family,
        hierarchy=hierarchy,
        edition=edition,
        status=status,
        granule=row.get("granule"),
        note=row.get("note"),
    )
    reject_positional_durable_identity(legal_id, name="legal_id")
    existing_legal_id = row.get("legal_id")
    if existing_legal_id not in (None, ""):
        reject_positional_durable_identity(existing_legal_id, name="legal_id")

    text = row.get("text") or row.get("body")
    if text in (None, ""):
        raise IncompleteIdentityError(f"section {legal_id!r} is missing text")
    normalized = normalize_corpus_text(text)
    normalized = scrub_local_paths_in_text(normalized)
    text_hash = compute_text_hash(normalized)
    provided_hash = row.get("text_hash")
    if provided_hash not in (None, ""):
        expected = validate_text_hash(provided_hash)
        if expected != text_hash:
            raise IncompleteIdentityError(
                f"text_hash does not match SHA-256 of provided text for {legal_id!r}"
            )

    source_cid = synthesize_source_cid(row, legal_id)
    entry_cid = synthesize_entry_cid(row, legal_id, text_hash)
    text_cid = synthesize_text_cid(row, text_hash)
    identity = StatuteIdentity(
        jurisdiction_code=jurisdiction,
        code_family=code_family,
        hierarchy=hierarchy,
        edition=edition,
        source_cid=source_cid,
        entry_cid=entry_cid,
        text_hash=text_hash,
        document_kind=document_kind,
        status=status,
        configuration=configuration,
        text_cid=text_cid,
        granule=_optional_str(row.get("granule"), "granule"),
        note=_optional_str(row.get("note"), "note"),
    )
    payload = identity.to_dict()
    payload["text"] = normalized
    payload["legal_id"] = identity.legal_id
    return payload


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalSection:
    """One admitted or isolated statutory section with durable identity."""

    legal_id: str
    entry_cid: str
    source_cid: str
    text_cid: str
    text_hash: str
    jurisdiction_code: str
    code_family: str
    edition: str
    hierarchy: dict[str, Optional[str]]
    document_kind: str
    status: str
    configuration: str
    text: str
    document_index: int
    official_source_url: Optional[str]
    official_authority: Optional[str]
    observed_at: str
    acquisition_receipt_cid: str
    rights_receipt_cid: str
    response_hash: Optional[str]
    body_hash: str
    transformation_version: str
    admission_status: str
    admission_reason: str
    isolation_reason: str
    schema_version: str = SCHEMA_VERSION
    identity_schema_version: str = IDENTITY_SCHEMA_VERSION
    release_point: str = DEFAULT_RELEASE_POINT
    heading: Optional[str] = None

    def __post_init__(self) -> None:
        reject_positional_durable_identity(self.legal_id, name="legal_id")
        reject_positional_durable_identity(self.entry_cid, name="entry_cid")
        reject_positional_durable_identity(self.source_cid, name="source_cid")
        if not self.legal_id.startswith(f"{LEGAL_ID_PREFIX}:"):
            raise IncompleteIdentityError(
                f"legal_id must start with '{LEGAL_ID_PREFIX}:'; got {self.legal_id!r}"
            )
        validate_entry_cid(self.entry_cid)
        validate_source_cid(self.source_cid)
        validate_text_hash(self.text_hash)
        if compute_text_hash(self.text) != self.text_hash:
            raise IncompleteIdentityError("section text_hash does not match text")
        _require_non_negative_int(self.document_index, "document_index")

    def chunk_locator(self) -> str:
        return self.legal_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_receipt_cid": self.acquisition_receipt_cid,
            "admission_reason": self.admission_reason,
            "admission_status": self.admission_status,
            "body_hash": self.body_hash,
            "code_family": self.code_family,
            "configuration": self.configuration,
            "document_index": self.document_index,
            "document_kind": self.document_kind,
            "edition": self.edition,
            "entry_cid": self.entry_cid,
            "heading": self.heading,
            "hierarchy": dict(self.hierarchy),
            "identity_schema_version": self.identity_schema_version,
            "isolation_reason": self.isolation_reason,
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "observed_at": self.observed_at,
            "official_authority": self.official_authority,
            "official_source_url": self.official_source_url,
            "release_point": self.release_point,
            "response_hash": self.response_hash,
            "rights_receipt_cid": self.rights_receipt_cid,
            "satisfies_exact_51_gate": (
                self.configuration == DEFAULT_CONFIGURATION
                and self.admission_status == AdmissionStatus.ADMITTED.value
            ),
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "status": self.status,
            "text": self.text,
            "text_cid": self.text_cid,
            "text_hash": self.text_hash,
            "transformation_version": self.transformation_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalSection":
        if not isinstance(value, Mapping):
            raise OpenUsLawCorpusError("canonical section must be a mapping")
        hierarchy = value.get("hierarchy")
        if not isinstance(hierarchy, Mapping):
            hierarchy = {
                key: value.get(key)
                for key in HIERARCHY_KEYS
                if value.get(key) not in (None, "")
            }
        return cls(
            legal_id=str(value.get("legal_id") or ""),
            entry_cid=str(value.get("entry_cid") or ""),
            source_cid=str(value.get("source_cid") or ""),
            text_cid=str(value.get("text_cid") or ""),
            text_hash=str(value.get("text_hash") or ""),
            jurisdiction_code=str(value.get("jurisdiction_code") or ""),
            code_family=str(value.get("code_family") or ""),
            edition=str(value.get("edition") or ""),
            hierarchy=dict(hierarchy),
            document_kind=str(value.get("document_kind") or DocumentKind.STATUTE.value),
            status=str(value.get("status") or StatuteStatus.CURRENT.value),
            configuration=str(value.get("configuration") or DEFAULT_CONFIGURATION),
            text=str(value.get("text") or ""),
            document_index=int(value.get("document_index") or 0),
            official_source_url=_optional_str(value.get("official_source_url") or value.get("source_url")),
            official_authority=_optional_str(value.get("official_authority")),
            observed_at=str(value.get("observed_at") or value.get("acquisition_time") or DEFAULT_ACQUISITION_TIME),
            acquisition_receipt_cid=str(value.get("acquisition_receipt_cid") or ""),
            rights_receipt_cid=str(value.get("rights_receipt_cid") or ""),
            response_hash=_optional_str(value.get("response_hash")),
            body_hash=str(value.get("body_hash") or value.get("text_hash") or ""),
            transformation_version=str(
                value.get("transformation_version") or TRANSFORMATION_VERSION
            ),
            admission_status=str(value.get("admission_status") or AdmissionStatus.ADMITTED.value),
            admission_reason=str(value.get("admission_reason") or ""),
            isolation_reason=str(value.get("isolation_reason") or IsolationReason.NONE.value),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            identity_schema_version=str(
                value.get("identity_schema_version") or IDENTITY_SCHEMA_VERSION
            ),
            release_point=str(value.get("release_point") or DEFAULT_RELEASE_POINT),
            heading=_optional_str(value.get("heading")),
        )


@dataclass(frozen=True, slots=True)
class CanonicalChunk:
    """One structure-aware chunk with deterministic identity and provenance."""

    chunk_id: str
    chunk_cid: str
    chunk_index: int
    parent_legal_id: str
    legal_id: str
    entry_cid: str
    source_cid: str
    text_hash: str
    text: str
    exclusive_text: str
    char_start: int
    char_end: int
    token_start: int
    token_end: int
    token_count: int
    parent_path: tuple[str, ...]
    split_mode: str
    jurisdiction_code: str
    configuration: str
    document_index: int
    model_token_limit: int
    tokenizer_id: str
    transformation_version: str = TRANSFORMATION_VERSION
    schema_version: str = SCHEMA_VERSION
    heading: str = ""
    limit_exempt: bool = False

    def __post_init__(self) -> None:
        parent, index = parse_chunk_id(self.chunk_id)
        if parent != self.parent_legal_id:
            raise ChunkIdentityError(
                f"chunk_id parent {parent!r} != parent_legal_id {self.parent_legal_id!r}"
            )
        if index != self.chunk_index:
            raise ChunkIdentityError(
                f"chunk_id index {index} != chunk_index {self.chunk_index}"
            )
        if self.legal_id != self.chunk_id:
            raise ChunkIdentityError("chunk legal_id must equal chunk_id")
        reject_positional_durable_identity(self.chunk_cid, name="chunk_cid")
        validate_text_hash(self.text_hash)
        if self.model_token_limit != DEFAULT_MODEL_TOKEN_LIMIT and self.model_token_limit < 1:
            raise ChunkIdentityError("model_token_limit must be a positive integer")
        if (
            not self.limit_exempt
            and self.token_count > self.model_token_limit
        ):
            raise ChunkIdentityError(
                f"chunk {self.chunk_id!r} exceeds model token ceiling "
                f"{self.model_token_limit}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_end": self.char_end,
            "char_start": self.char_start,
            "chunk_cid": self.chunk_cid,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "configuration": self.configuration,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "exclusive_text": self.exclusive_text,
            "heading": self.heading,
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "limit_exempt": self.limit_exempt,
            "model_token_limit": self.model_token_limit,
            "parent_legal_id": self.parent_legal_id,
            "parent_path": list(self.parent_path),
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "split_mode": self.split_mode,
            "text": self.text,
            "text_hash": self.text_hash,
            "token_count": self.token_count,
            "token_end": self.token_end,
            "token_start": self.token_start,
            "tokenizer_id": self.tokenizer_id,
            "transformation_version": self.transformation_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalChunk":
        if not isinstance(value, Mapping):
            raise ChunkIdentityError("chunk payload must be a mapping")
        path = value.get("parent_path") or ()
        if isinstance(path, list):
            path = tuple(path)
        chunk_id = str(value.get("chunk_id") or value.get("legal_id") or "")
        return cls(
            chunk_id=chunk_id,
            chunk_cid=str(value.get("chunk_cid") or ""),
            chunk_index=int(value.get("chunk_index") or 0),
            parent_legal_id=str(value.get("parent_legal_id") or ""),
            legal_id=str(value.get("legal_id") or chunk_id),
            entry_cid=str(value.get("entry_cid") or ""),
            source_cid=str(value.get("source_cid") or ""),
            text_hash=str(value.get("text_hash") or ""),
            text=str(value.get("text") or ""),
            exclusive_text=str(value.get("exclusive_text") or value.get("text") or ""),
            char_start=int(value.get("char_start") or 0),
            char_end=int(value.get("char_end") or 0),
            token_start=int(value.get("token_start") or 0),
            token_end=int(value.get("token_end") or 0),
            token_count=int(value.get("token_count") or 0),
            parent_path=tuple(path),
            split_mode=str(value.get("split_mode") or "whole"),
            jurisdiction_code=str(value.get("jurisdiction_code") or ""),
            configuration=str(value.get("configuration") or DEFAULT_CONFIGURATION),
            document_index=int(value.get("document_index") or 0),
            model_token_limit=int(value.get("model_token_limit") or DEFAULT_MODEL_TOKEN_LIMIT),
            tokenizer_id=str(value.get("tokenizer_id") or DEFAULT_TOKENIZER_ID),
            transformation_version=str(
                value.get("transformation_version") or TRANSFORMATION_VERSION
            ),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            heading=str(value.get("heading") or ""),
            limit_exempt=bool(value.get("limit_exempt", False)),
        )


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One source-row disposition with optional identity/provenance links."""

    row_id: str
    disposition: RowDisposition
    configuration: ReleaseConfiguration
    isolation_reason: IsolationReason
    reason: str
    legal_id: Optional[str] = None
    entry_cid: Optional[str] = None
    source_cid: Optional[str] = None
    text_hash: Optional[str] = None
    jurisdiction_code: Optional[str] = None
    document_index: Optional[int] = None
    chunk_count: int = 0
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _require_non_empty_str(self.row_id, "row_id"))
        object.__setattr__(self, "disposition", RowDisposition.coerce(self.disposition))
        object.__setattr__(
            self, "configuration", ReleaseConfiguration.coerce(self.configuration)
        )
        object.__setattr__(
            self, "isolation_reason", IsolationReason.coerce(self.isolation_reason)
        )
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        if self.legal_id is not None:
            reject_positional_durable_identity(self.legal_id, name="legal_id")
        if self.entry_cid is not None:
            reject_positional_durable_identity(self.entry_cid, name="entry_cid")
        if (
            self.disposition is RowDisposition.ADMITTED
            and self.configuration is not ReleaseConfiguration.STATE_STATUTES_EXACT_51
        ):
            raise IsolationError("admitted ledger rows must use the default exact-51 configuration")
        if (
            self.disposition is RowDisposition.ADMITTED
            and not (self.legal_id and self.entry_cid and self.source_cid and self.text_hash)
        ):
            raise IncompleteIdentityError(
                f"admitted ledger entry {self.row_id!r} lacks complete identity/provenance"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_count": self.chunk_count,
            "configuration": self.configuration.value,
            "disposition": self.disposition.value,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "isolation_reason": self.isolation_reason.value,
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "reason": self.reason,
            "row_id": self.row_id,
            "satisfies_exact_51_gate": (
                self.disposition is RowDisposition.ADMITTED
                and self.configuration.satisfies_exact_51_gate
            ),
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "text_hash": self.text_hash,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LedgerEntry":
        if not isinstance(value, Mapping):
            raise AdmissionLedgerError("ledger entry must be a mapping")
        return cls(
            row_id=str(value.get("row_id") or ""),
            disposition=value.get("disposition") or "",
            configuration=value.get("configuration") or DEFAULT_CONFIGURATION,
            isolation_reason=value.get("isolation_reason") or IsolationReason.NONE,
            reason=str(value.get("reason") or ""),
            legal_id=_optional_str(value.get("legal_id")),
            entry_cid=_optional_str(value.get("entry_cid")),
            source_cid=_optional_str(value.get("source_cid")),
            text_hash=_optional_str(value.get("text_hash")),
            jurisdiction_code=_optional_str(value.get("jurisdiction_code")),
            document_index=value.get("document_index"),
            chunk_count=int(value.get("chunk_count") or 0),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class FamilyCounts:
    corpus: int = 0
    chunks: int = 0
    bm25: int = 0
    vector: int = 0
    graph: int = 0
    recovery: int = 0
    quarantine: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "bm25": self.bm25,
            "chunks": self.chunks,
            "corpus": self.corpus,
            "graph": self.graph,
            "quarantine": self.quarantine,
            "recovery": self.recovery,
            "vector": self.vector,
        }


@dataclass(frozen=True, slots=True)
class IsolatedRecord:
    """A non-search or non-default isolated projection."""

    row_id: str
    disposition: str
    configuration: str
    isolation_reason: str
    reason: str
    legal_id: Optional[str] = None
    entry_cid: Optional[str] = None
    source_cid: Optional[str] = None
    jurisdiction_code: Optional[str] = None
    text_hash: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration": self.configuration,
            "disposition": self.disposition,
            "entry_cid": self.entry_cid,
            "isolation_reason": self.isolation_reason,
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "payload": dict(self.payload),
            "reason": self.reason,
            "row_id": self.row_id,
            "satisfies_exact_51_gate": False,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "text_hash": self.text_hash,
        }


@dataclass(frozen=True, slots=True)
class MaterializedCorpus:
    """Result of materializing source rows into corpus, configs, and quarantine."""

    ledger: tuple[LedgerEntry, ...]
    admitted_sections: tuple[CanonicalSection, ...]
    admitted_chunks: tuple[CanonicalChunk, ...]
    isolated_sections: tuple[CanonicalSection, ...]
    isolated_chunks: tuple[CanonicalChunk, ...]
    recovery_rows: tuple[IsolatedRecord, ...]
    quarantine_rows: tuple[IsolatedRecord, ...]
    family_counts: FamilyCounts
    release_point: str = DEFAULT_RELEASE_POINT
    schema_version: str = SCHEMA_VERSION
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER
    notes: str = ""
    authorizing_for_publication: bool = False
    authorizing_for_release: bool = False

    def __post_init__(self) -> None:
        seen: dict[str, str] = {}
        for entry in self.ledger:
            prior = seen.get(entry.row_id)
            if prior is not None:
                raise DispositionError(
                    f"row_id {entry.row_id!r} has multiple dispositions: "
                    f"{prior!r} and {entry.disposition.value!r}"
                )
            seen[entry.row_id] = entry.disposition.value

        for section in self.admitted_sections:
            if section.configuration != DEFAULT_CONFIGURATION:
                raise IsolationError(
                    f"admitted section {section.legal_id!r} is not in {DEFAULT_CONFIGURATION}"
                )
            CanonicalSection.from_mapping(section.to_dict())
        for chunk in self.admitted_chunks:
            CanonicalChunk.from_mapping(chunk.to_dict())
            if chunk.configuration != DEFAULT_CONFIGURATION:
                raise IsolationError(
                    f"admitted chunk {chunk.chunk_id!r} is not in {DEFAULT_CONFIGURATION}"
                )

        admitted_ids = {section.legal_id for section in self.admitted_sections}
        admitted_cids = {section.entry_cid for section in self.admitted_sections}
        for isolated in self.isolated_sections:
            if isolated.legal_id in admitted_ids:
                raise IsolationError(
                    f"isolated legal_id {isolated.legal_id!r} collides with an "
                    "admitted default section"
                )
            if isolated.entry_cid in admitted_cids:
                raise IsolationError(
                    f"isolated entry_cid {isolated.entry_cid!r} collides with an "
                    "admitted default section"
                )
            if isolated.configuration == DEFAULT_CONFIGURATION:
                raise IsolationError(
                    f"isolated section {isolated.legal_id!r} leaked into "
                    f"{DEFAULT_CONFIGURATION}"
                )

        if self.family_counts.corpus != len(self.admitted_sections):
            raise IsolationError(
                "corpus family count must equal admitted section count "
                f"({self.family_counts.corpus} != {len(self.admitted_sections)})"
            )
        if self.family_counts.chunks != len(self.admitted_chunks):
            raise IsolationError(
                "chunk family count must equal admitted chunk count "
                f"({self.family_counts.chunks} != {len(self.admitted_chunks)})"
            )
        for family, count in (
            ("bm25", self.family_counts.bm25),
            ("vector", self.family_counts.vector),
            ("graph", self.family_counts.graph),
        ):
            if count != len(self.admitted_chunks):
                raise IsolationError(
                    f"{family} family count must equal admitted chunk count "
                    f"({count} != {len(self.admitted_chunks)})"
                )
        if self.family_counts.recovery != len(self.recovery_rows):
            raise IsolationError("recovery family count must equal recovery row count")
        if self.family_counts.quarantine != len(self.quarantine_rows):
            raise IsolationError("quarantine family count must equal quarantine row count")
        if self.authorizing_for_publication or self.authorizing_for_release:
            raise Exact51AuthorizationError(
                "fixture corpus materialization cannot authorize publication or release"
            )

    @property
    def disposition_counts(self) -> dict[str, int]:
        counts = {item.value: 0 for item in RowDisposition}
        for entry in self.ledger:
            counts[entry.disposition.value] += 1
        return counts

    @property
    def configuration_counts(self) -> dict[str, int]:
        counts = {name: 0 for name in ALL_CONFIGURATION_NAMES}
        for entry in self.ledger:
            counts[entry.configuration.value] += 1
        return counts

    @property
    def isolation_counts(self) -> dict[str, int]:
        counts = {item.value: 0 for item in IsolationReason}
        for entry in self.ledger:
            counts[entry.isolation_reason.value] += 1
        return counts

    def default_jurisdiction_codes(self) -> tuple[str, ...]:
        present = {section.jurisdiction_code for section in self.admitted_sections}
        return tuple(code for code in EXACT_51_JURISDICTION_CODES if code in present)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_chunks": [chunk.to_dict() for chunk in self.admitted_chunks],
            "admitted_sections": [section.to_dict() for section in self.admitted_sections],
            "authorizing_for_publication": self.authorizing_for_publication,
            "authorizing_for_release": self.authorizing_for_release,
            "configuration_counts": self.configuration_counts,
            "currentness_disclaimer": self.currentness_disclaimer,
            "disposition_counts": self.disposition_counts,
            "family_counts": self.family_counts.to_dict(),
            "isolated_chunks": [chunk.to_dict() for chunk in self.isolated_chunks],
            "isolated_sections": [section.to_dict() for section in self.isolated_sections],
            "isolation_counts": self.isolation_counts,
            "ledger": [entry.to_dict() for entry in self.ledger],
            "notes": self.notes,
            "quarantine_rows": [row.to_dict() for row in self.quarantine_rows],
            "recovery_rows": [row.to_dict() for row in self.recovery_rows],
            "release_point": self.release_point,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_cid_for(
    *,
    parent_legal_id: str,
    chunk_id: str,
    char_start: int,
    char_end: int,
    exclusive_text: str,
    tokenizer_id: str,
) -> str:
    return content_sha256(
        canonical_json_dumps(
            {
                "char_end": char_end,
                "char_start": char_start,
                "chunk_id": chunk_id,
                "exclusive_text": exclusive_text,
                "parent_legal_id": parent_legal_id,
                "schema_version": SCHEMA_VERSION,
                "tokenizer_id": tokenizer_id,
                "transformation_version": TRANSFORMATION_VERSION,
            }
        )
    )


def chunk_canonical_section(
    section: CanonicalSection | Mapping[str, Any],
    *,
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    max_chunks_per_section: int = DEFAULT_MAX_CHUNKS_PER_SECTION,
) -> tuple[CanonicalChunk, ...]:
    """Split one canonical section into structure-aware, content-addressed chunks."""

    record = (
        section
        if isinstance(section, CanonicalSection)
        else CanonicalSection.from_mapping(section)
    )
    if ReleaseConfiguration.coerce(record.configuration) not in CHUNKABLE_CONFIGURATIONS:
        return ()
    if not isinstance(model_token_limit, int) or isinstance(model_token_limit, bool):
        raise ChunkIdentityError("model_token_limit must be an integer")
    if model_token_limit < 1:
        raise ChunkIdentityError("model_token_limit must be >= 1")
    if model_token_limit > DEFAULT_MODEL_TOKEN_LIMIT:
        raise ChunkIdentityError(
            f"model_token_limit {model_token_limit} exceeds pinned GTE ceiling "
            f"{DEFAULT_MODEL_TOKEN_LIMIT}"
        )

    hierarchy = record.hierarchy if isinstance(record.hierarchy, Mapping) else {}
    result = chunk_statute(
        {
            "jurisdiction_code": record.jurisdiction_code,
            "text": record.text,
            "title": hierarchy.get("title") or "1",
            "chapter": hierarchy.get("chapter") or "",
            "section": hierarchy.get("section") or "1",
            "subsection": hierarchy.get("subsection") or "",
            "edition": record.edition,
            "code_family": record.code_family,
            "document_index": record.document_index,
            "heading": record.heading or "",
            "legal_id": record.legal_id,
            "source_cid": record.source_cid,
            "entry_cid": record.entry_cid,
        },
        model_token_limit=model_token_limit,
        overlap_tokens=overlap_tokens,
        max_chunks_per_section=max_chunks_per_section,
    )
    chunks: list[CanonicalChunk] = []
    for raw in result.chunks:
        payload = raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)
        index = int(payload["chunk_index"])
        chunk_id = build_chunk_id(record.legal_id, index)
        exclusive = str(payload.get("exclusive_text") or "")
        chunk_cid = _chunk_cid_for(
            parent_legal_id=record.legal_id,
            chunk_id=chunk_id,
            char_start=int(payload["char_start"]),
            char_end=int(payload["char_end"]),
            exclusive_text=exclusive,
            tokenizer_id=str(payload.get("tokenizer_id") or DEFAULT_TOKENIZER_ID),
        )
        parent_path = payload.get("parent_path") or ()
        if isinstance(parent_path, list):
            parent_path = tuple(parent_path)
        chunks.append(
            CanonicalChunk(
                chunk_id=chunk_id,
                chunk_cid=chunk_cid,
                chunk_index=index,
                parent_legal_id=record.legal_id,
                legal_id=chunk_id,
                entry_cid=record.entry_cid,
                source_cid=record.source_cid,
                text_hash=(
                    compute_text_hash(exclusive)
                    if exclusive.strip()
                    else content_sha256("")
                ),
                text=str(payload.get("text") or exclusive),
                exclusive_text=exclusive,
                char_start=int(payload["char_start"]),
                char_end=int(payload["char_end"]),
                token_start=int(payload.get("token_start") or 0),
                token_end=int(payload.get("token_end") or 0),
                token_count=int(payload.get("token_count") or 0),
                parent_path=tuple(parent_path),
                split_mode=str(payload.get("split_mode") or "structure"),
                jurisdiction_code=record.jurisdiction_code,
                configuration=record.configuration,
                document_index=record.document_index,
                model_token_limit=model_token_limit,
                tokenizer_id=str(payload.get("tokenizer_id") or DEFAULT_TOKENIZER_ID),
                heading=str(payload.get("heading") or record.heading or ""),
                limit_exempt=bool(payload.get("limit_exempt", False)),
            )
        )
    return tuple(chunks)


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


def _build_canonical_section(
    row: Mapping[str, Any],
    *,
    classification: Classification,
    document_index: int,
    release_point: str,
    acquisition_time: str,
) -> CanonicalSection:
    identity = build_section_identity(row, configuration=classification.configuration)
    observed = (
        _optional_str(row.get("observed_at") or row.get("acquisition_time"))
        or acquisition_time
    )
    seed = f"{identity['legal_id']}|{identity['source_cid']}|{observed}"
    official_url = _optional_str(
        row.get("official_source_url") or row.get("source_url") or row.get("page_url"),
        "official_source_url",
        maximum=2048,
    )
    response_hash = _optional_str(row.get("response_hash") or row.get("response_sha256"))
    if response_hash:
        response_hash = validate_text_hash(response_hash) if _SHA256_HEX_RE.fullmatch(response_hash.lower().removeprefix("sha256:")) or str(response_hash).startswith("sha256:") else content_sha256(response_hash)
    return CanonicalSection(
        legal_id=identity["legal_id"],
        entry_cid=identity["entry_cid"],
        source_cid=identity["source_cid"],
        text_cid=identity["text_cid"] or f"sha256:{identity['text_hash']}",
        text_hash=identity["text_hash"],
        jurisdiction_code=identity["jurisdiction_code"],
        code_family=identity["code_family"],
        edition=identity["edition"],
        hierarchy=dict(identity["hierarchy"]),
        document_kind=identity["document_kind"],
        status=identity["status"],
        configuration=classification.configuration.value,
        text=identity["text"],
        document_index=document_index,
        official_source_url=official_url,
        official_authority=_optional_str(row.get("official_authority") or row.get("authority")),
        observed_at=observed,
        acquisition_receipt_cid=synthesize_receipt_cid(
            row, field="acquisition_receipt_cid", seed=seed
        ),
        rights_receipt_cid=synthesize_receipt_cid(
            row, field="rights_receipt_cid", seed=f"rights|{seed}"
        ),
        response_hash=response_hash,
        body_hash=identity["text_hash"],
        transformation_version=TRANSFORMATION_VERSION,
        admission_status=(
            AdmissionStatus.ADMITTED.value
            if classification.disposition is RowDisposition.ADMITTED
            else AdmissionStatus.EXCLUDED.value
        ),
        admission_reason=classification.reason,
        isolation_reason=classification.isolation_reason.value,
        release_point=release_point,
        heading=_optional_str(row.get("heading") or row.get("title_heading")),
    )


def _build_isolated_record(
    row: Mapping[str, Any],
    *,
    row_id: str,
    classification: Classification,
) -> IsolatedRecord:
    legal_id = _optional_str(row.get("legal_id"))
    entry_cid = _optional_str(row.get("entry_cid"))
    source_cid = _optional_str(row.get("source_cid"))
    text_hash = _optional_str(row.get("text_hash"))
    jurisdiction = None
    raw_jurisdiction = _peek_jurisdiction(row)
    if raw_jurisdiction not in (None, ""):
        try:
            jurisdiction = normalize_jurisdiction_code(
                raw_jurisdiction, allow_non_default=True
            )
        except OpenUsLawSchemaError:
            jurisdiction = str(raw_jurisdiction).strip().upper()
    payload = {
        key: value
        for key, value in scrub_mapping_paths(row).items()
        if key
        not in {
            "text",
            "body",
            "raw_json",
            "source_path",
            "local_path",
            "path",
            "absolute_path",
        }
    }
    return IsolatedRecord(
        row_id=row_id,
        disposition=classification.disposition.value,
        configuration=classification.configuration.value,
        isolation_reason=classification.isolation_reason.value,
        reason=classification.reason,
        legal_id=legal_id,
        entry_cid=entry_cid,
        source_cid=source_cid,
        jurisdiction_code=jurisdiction,
        text_hash=text_hash,
        payload=payload,
    )


class OpenUsLawCorpusMaterializer:
    """Materialize canonical exact-51 sections, chunks, and isolation configs."""

    def __init__(
        self,
        *,
        release_point: str = DEFAULT_RELEASE_POINT,
        acquisition_time: str = DEFAULT_ACQUISITION_TIME,
        model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        max_chunks_per_section: int = DEFAULT_MAX_CHUNKS_PER_SECTION,
    ) -> None:
        self.release_point = _require_non_empty_str(release_point, "release_point")
        if self.release_point.strip().lower() in {"latest", "main", "head"}:
            raise OpenUsLawCorpusError(
                f"release_point must be an exact pin, not {release_point!r}"
            )
        self.acquisition_time = _require_non_empty_str(
            acquisition_time, "acquisition_time"
        )
        if (
            not isinstance(model_token_limit, int)
            or isinstance(model_token_limit, bool)
            or model_token_limit < 1
            or model_token_limit > DEFAULT_MODEL_TOKEN_LIMIT
        ):
            raise OpenUsLawCorpusError(
                "model_token_limit must be in "
                f"[1, {DEFAULT_MODEL_TOKEN_LIMIT}]"
            )
        self.model_token_limit = model_token_limit
        self.overlap_tokens = _require_non_negative_int(overlap_tokens, "overlap_tokens")
        self.max_chunks_per_section = _require_non_negative_int(
            max_chunks_per_section, "max_chunks_per_section"
        )
        if self.max_chunks_per_section < 1:
            raise OpenUsLawCorpusError("max_chunks_per_section must be >= 1")

    def materialize(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        notes: str = "",
    ) -> MaterializedCorpus:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise OpenUsLawCorpusError("rows must be a sequence of mappings")

        ledger: list[LedgerEntry] = []
        admitted_sections: list[CanonicalSection] = []
        admitted_chunks: list[CanonicalChunk] = []
        isolated_sections: list[CanonicalSection] = []
        isolated_chunks: list[CanonicalChunk] = []
        recovery_rows: list[IsolatedRecord] = []
        quarantine_rows: list[IsolatedRecord] = []
        seen_row_ids: set[str] = set()
        seen_keys: dict[str, set[str]] = {name: set() for name in ALL_CONFIGURATION_NAMES}
        admitted_index = 0
        isolated_index = 0

        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                raise OpenUsLawCorpusError(f"rows[{index}] must be a mapping")
            row = scrub_mapping_paths(raw)
            classification = classify_source_row(row)
            row_id = str(
                row.get("row_id")
                or row.get("id")
                or row.get("recovery_id")
                or f"source-{index:05d}"
            )
            try:
                reject_positional_durable_identity(row_id, name="row_id")
            except PositionalIdentityError as exc:
                raise DispositionError(str(exc)) from exc
            if row_id in seen_row_ids:
                raise DispositionError(f"duplicate row_id in source batch: {row_id!r}")
            seen_row_ids.add(row_id)

            section: Optional[CanonicalSection] = None
            chunks: tuple[CanonicalChunk, ...] = ()
            if classification.disposition in {
                RowDisposition.ADMITTED,
                RowDisposition.ISOLATED,
            }:
                try:
                    section = _build_canonical_section(
                        row,
                        classification=classification,
                        document_index=(
                            admitted_index
                            if classification.disposition is RowDisposition.ADMITTED
                            else isolated_index
                        ),
                        release_point=self.release_point,
                        acquisition_time=self.acquisition_time,
                    )
                except (OpenUsLawSchemaError, OpenUsLawCorpusError, MissingIdentityFieldError) as exc:
                    classification = Classification(
                        disposition=RowDisposition.QUARANTINED,
                        configuration=ReleaseConfiguration.QUARANTINE,
                        isolation_reason=IsolationReason.UNSUPPORTED,
                        reason=f"incomplete identity quarantined: {exc}",
                    )
                    section = None

            if section is not None:
                key_set = seen_keys[classification.configuration.value]
                duplicate_key = None
                if section.legal_id in key_set:
                    duplicate_key = section.legal_id
                elif section.entry_cid in key_set:
                    duplicate_key = section.entry_cid
                if duplicate_key is not None:
                    classification = Classification(
                        disposition=RowDisposition.QUARANTINED,
                        configuration=ReleaseConfiguration.QUARANTINE,
                        isolation_reason=IsolationReason.DUPLICATE,
                        reason=_default_reason(IsolationReason.DUPLICATE)
                        + f" ({duplicate_key})",
                    )
                    quarantine_rows.append(
                        IsolatedRecord(
                            row_id=row_id,
                            disposition=classification.disposition.value,
                            configuration=classification.configuration.value,
                            isolation_reason=classification.isolation_reason.value,
                            reason=classification.reason,
                            legal_id=section.legal_id,
                            entry_cid=section.entry_cid,
                            source_cid=section.source_cid,
                            jurisdiction_code=section.jurisdiction_code,
                            text_hash=section.text_hash,
                            payload={"duplicate_of": duplicate_key},
                        )
                    )
                    ledger.append(
                        LedgerEntry(
                            row_id=row_id,
                            disposition=classification.disposition,
                            configuration=classification.configuration,
                            isolation_reason=classification.isolation_reason,
                            reason=classification.reason,
                            legal_id=section.legal_id,
                            entry_cid=section.entry_cid,
                            source_cid=section.source_cid,
                            text_hash=section.text_hash,
                            jurisdiction_code=section.jurisdiction_code,
                            document_index=index,
                            chunk_count=0,
                        )
                    )
                    continue

                key_set.add(section.legal_id)
                key_set.add(section.entry_cid)
                chunks = chunk_canonical_section(
                    section,
                    model_token_limit=self.model_token_limit,
                    overlap_tokens=self.overlap_tokens,
                    max_chunks_per_section=self.max_chunks_per_section,
                )
                if classification.disposition is RowDisposition.ADMITTED:
                    admitted_sections.append(section)
                    admitted_chunks.extend(chunks)
                    admitted_index += 1
                else:
                    isolated_sections.append(section)
                    isolated_chunks.extend(chunks)
                    isolated_index += 1
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=classification.disposition,
                        configuration=classification.configuration,
                        isolation_reason=classification.isolation_reason,
                        reason=classification.reason,
                        legal_id=section.legal_id,
                        entry_cid=section.entry_cid,
                        source_cid=section.source_cid,
                        text_hash=section.text_hash,
                        jurisdiction_code=section.jurisdiction_code,
                        document_index=section.document_index,
                        chunk_count=len(chunks),
                    )
                )
                continue

            isolated = _build_isolated_record(
                row, row_id=row_id, classification=classification
            )
            if classification.disposition is RowDisposition.RECOVERY:
                recovery_rows.append(isolated)
            else:
                quarantine_rows.append(isolated)
            ledger.append(
                LedgerEntry(
                    row_id=row_id,
                    disposition=classification.disposition,
                    configuration=classification.configuration,
                    isolation_reason=classification.isolation_reason,
                    reason=classification.reason,
                    legal_id=isolated.legal_id,
                    entry_cid=isolated.entry_cid,
                    source_cid=isolated.source_cid,
                    text_hash=isolated.text_hash,
                    jurisdiction_code=isolated.jurisdiction_code,
                    document_index=index,
                    chunk_count=0,
                )
            )

        n_admitted = len(admitted_sections)
        n_chunks = len(admitted_chunks)
        counts = FamilyCounts(
            corpus=n_admitted,
            chunks=n_chunks,
            bm25=n_chunks,
            vector=n_chunks,
            graph=n_chunks,
            recovery=len(recovery_rows),
            quarantine=len(quarantine_rows),
        )
        return MaterializedCorpus(
            ledger=tuple(ledger),
            admitted_sections=tuple(admitted_sections),
            admitted_chunks=tuple(admitted_chunks),
            isolated_sections=tuple(isolated_sections),
            isolated_chunks=tuple(isolated_chunks),
            recovery_rows=tuple(recovery_rows),
            quarantine_rows=tuple(quarantine_rows),
            family_counts=counts,
            release_point=self.release_point,
            notes=notes
            or (
                "Canonical exact-51 corpus projection with explicit non-default "
                "configurations and quarantine. Acquisition timestamps are not "
                "legal-currentness claims. Fixture materialization does not "
                "authorize publication."
            ),
        )


def materialize_open_us_law_corpus(
    rows: Sequence[Mapping[str, Any]],
    *,
    release_point: str = DEFAULT_RELEASE_POINT,
    acquisition_time: str = DEFAULT_ACQUISITION_TIME,
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT,
    notes: str = "",
) -> MaterializedCorpus:
    """Functional entry point for corpus materialization."""

    return OpenUsLawCorpusMaterializer(
        release_point=release_point,
        acquisition_time=acquisition_time,
        model_token_limit=model_token_limit,
    ).materialize(rows, notes=notes)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def assert_every_row_has_exactly_one_disposition(
    ledger: Sequence[LedgerEntry | Mapping[str, Any]],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in ledger:
        if isinstance(item, LedgerEntry):
            row_id = item.row_id
            disposition = item.disposition.value
        else:
            row_id = str(item.get("row_id") or "")
            disposition = RowDisposition.coerce(item.get("disposition")).value
        if not row_id:
            raise DispositionError("ledger entry missing row_id")
        if row_id in mapping:
            raise DispositionError(
                f"row_id {row_id!r} has multiple dispositions: "
                f"{mapping[row_id]!r} and {disposition!r}"
            )
        mapping[row_id] = disposition
    if not mapping:
        raise DispositionError("ledger is empty")
    return mapping


def assert_admitted_rows_complete(rows: Sequence[CanonicalSection | Mapping[str, Any]]) -> None:
    for index, row in enumerate(rows):
        try:
            section = row if isinstance(row, CanonicalSection) else CanonicalSection.from_mapping(row)
            validated = validate_corpus_identity(section.to_dict())
            if validated["configuration"] != DEFAULT_CONFIGURATION:
                raise IsolationError(
                    f"admitted_rows[{index}] classified as {validated['configuration']!r}"
                )
        except Exception as exc:
            raise IncompleteIdentityError(f"admitted_rows[{index}] incomplete: {exc}") from exc


def assert_chunks_have_deterministic_ids(
    chunks: Sequence[CanonicalChunk | Mapping[str, Any]],
) -> None:
    seen: set[str] = set()
    for index, raw in enumerate(chunks):
        chunk = raw if isinstance(raw, CanonicalChunk) else CanonicalChunk.from_mapping(raw)
        if chunk.chunk_id in seen:
            raise ChunkIdentityError(f"duplicate chunk_id {chunk.chunk_id!r}")
        seen.add(chunk.chunk_id)
        parent, ordinal = parse_chunk_id(chunk.chunk_id)
        if parent != chunk.parent_legal_id or ordinal != chunk.chunk_index:
            raise ChunkIdentityError(f"chunks[{index}] has a non-deterministic chunk_id")
        if not chunk.chunk_cid or not chunk.text_hash or not chunk.source_cid:
            raise ChunkIdentityError(f"chunks[{index}] missing provenance")


def assert_non_default_isolated(
    corpus: MaterializedCorpus,
    *,
    require_reasons: Iterable[str] = (
        IsolationReason.FEDERAL.value,
        IsolationReason.PUERTO_RICO.value,
        IsolationReason.CONSTITUTION.value,
        IsolationReason.HISTORICAL.value,
        IsolationReason.RECOVERY.value,
        IsolationReason.DUPLICATE.value,
        IsolationReason.CONTAMINATED.value,
        IsolationReason.UNSUPPORTED.value,
    ),
) -> None:
    present = {
        entry.isolation_reason.value
        for entry in corpus.ledger
        if entry.isolation_reason is not IsolationReason.NONE
    }
    required = {IsolationReason.coerce(item).value for item in require_reasons}
    missing = sorted(required - present)
    if missing:
        raise IsolationError(f"missing required isolation reasons: {missing}")

    gate_rows = [section.to_dict() for section in corpus.admitted_sections]
    report = validate_exact_51_gate(gate_rows, require_full_coverage=False)
    if report["non_default_satisfies_gate"]:
        raise Exact51GateError("non-default rows satisfied the exact-51 gate")
    for section in corpus.isolated_sections:
        if section.configuration == DEFAULT_CONFIGURATION:
            raise IsolationError("isolated section leaked into the default configuration")
    for row in (*corpus.recovery_rows, *corpus.quarantine_rows):
        if row.configuration == DEFAULT_CONFIGURATION:
            raise IsolationError("quarantine/recovery row leaked into the default configuration")
        if row.to_dict().get("satisfies_exact_51_gate"):
            raise IsolationError("isolated row marked as satisfying the exact-51 gate")


def assert_recovery_and_quarantine_excluded_from_canonical_counts(
    corpus: MaterializedCorpus,
) -> None:
    counts = corpus.family_counts.to_dict()
    admitted = len(corpus.admitted_sections)
    admitted_chunks = len(corpus.admitted_chunks)
    recovery = len(corpus.recovery_rows)
    quarantine = len(corpus.quarantine_rows)
    if counts["corpus"] != admitted:
        raise IsolationError("corpus count includes non-admitted rows")
    if counts["chunks"] != admitted_chunks:
        raise IsolationError("chunk count includes non-admitted chunks")
    for family in ("bm25", "vector", "graph"):
        if counts[family] != admitted_chunks:
            raise IsolationError(f"{family} count includes non-admitted material")
        if recovery and counts[family] == admitted_chunks + recovery:
            raise IsolationError(f"{family} count appears to include recovery rows")
        if quarantine and counts[family] == admitted_chunks + quarantine:
            raise IsolationError(f"{family} count appears to include quarantine rows")
    if counts["recovery"] != recovery or counts["quarantine"] != quarantine:
        raise IsolationError("recovery/quarantine counts are inconsistent")


# ---------------------------------------------------------------------------
# Compact fixtures and sealed admission report
# ---------------------------------------------------------------------------


STRUCTURED_STATUTE_TEXT: Final = (
    "Oregon Revised Statutes section 123.456 is adopted as follows: "
    "(a) A person shall keep records of every licensed activity. "
    "(b) The department may inspect those records during ordinary business hours. "
    "(1) Inspection notices must be written. "
    "(2) A licensee shall produce the records promptly upon request."
)


def fixture_statute_text(jurisdiction_code: str, *, structured: bool = False) -> str:
    name = jurisdiction_code
    if structured:
        return STRUCTURED_STATUTE_TEXT.replace("Oregon", name).replace("123.456", f"{name}-1-1")
    return (
        f"{name} official statutes title 1 section 1 shall apply to every person "
        f"subject to the laws of {name}."
    )


def build_default_jurisdiction_row(
    jurisdiction_code: str,
    *,
    structured: bool = False,
) -> dict[str, Any]:
    code = normalize_jurisdiction_code(jurisdiction_code, allow_non_default=False)
    text = fixture_statute_text(code, structured=structured)
    hierarchy = {"title": "1", "chapter": "1", "section": "1"}
    family = default_code_family_for(code, ReleaseConfiguration.STATE_STATUTES_EXACT_51)
    legal_id = build_legal_id(
        document_kind=DocumentKind.STATUTE,
        jurisdiction_code=code,
        code_family=family,
        hierarchy=hierarchy,
        edition=DEFAULT_EDITION,
    )
    text_hash = compute_text_hash(text)
    return {
        "row_id": f"default-{code.lower()}-t1-s1",
        "admission_status": AdmissionStatus.ADMITTED.value,
        "code_family": family,
        "configuration": DEFAULT_CONFIGURATION,
        "document_kind": DocumentKind.STATUTE.value,
        "edition": DEFAULT_EDITION,
        "hierarchy": hierarchy,
        "jurisdiction_code": code,
        "legal_id": legal_id,
        "official_authority": f"{code} official publisher",
        "official_source_url": f"https://example.invalid/official/{code.lower()}/1/1",
        "status": StatuteStatus.CURRENT.value,
        "text": text,
        "text_hash": text_hash,
        "entry_cid": content_sha256(f"oul-entry|{legal_id}|{text_hash}"),
        "source_cid": content_sha256(f"oul-source|https://example.invalid/official/{code.lower()}/1/1|{legal_id}"),
    }


def build_isolation_sample_rows() -> list[dict[str, Any]]:
    """Compact rows covering every required isolation family."""

    federal = example_federal_payload()
    federal["row_id"] = "isolated-federal-18-1001"
    federal["text"] = (
        "United States Code title 18 section 1001 shall punish whoever, in any "
        "matter within the jurisdiction of the federal government, makes a false statement."
    )
    federal["text_hash"] = compute_text_hash(federal["text"])

    puerto_rico = example_puerto_rico_payload()
    puerto_rico["row_id"] = "isolated-pr-1-1"
    puerto_rico["text"] = (
        "Laws of Puerto Rico title 1 section 1 shall be cited as the official "
        "compilation of the laws of Puerto Rico."
    )
    puerto_rico["text_hash"] = compute_text_hash(puerto_rico["text"])

    constitution = example_constitution_payload(jurisdiction_code="OR")
    constitution["row_id"] = "isolated-constitution-or-art1-s8"
    constitution["text"] = (
        "The constitution of Oregon article 1 section 8 shall protect the right "
        "to speak, write, or print freely on any subject."
    )
    constitution["text_hash"] = compute_text_hash(constitution["text"])

    historical = example_historical_payload(jurisdiction_code="OR")
    historical["row_id"] = "isolated-historical-or-10-1"
    historical["text"] = (
        "Historical Oregon statutes title 10 section 1 (1999) is superseded and "
        "shall not be cited as current law."
    )
    historical["text_hash"] = compute_text_hash(historical["text"])

    recovery = example_recovery_payload()
    recovery["row_id"] = "recovery-legacy-or"
    recovery["is_recovery"] = True
    recovery["source_path"] = "/home/operator/workspaces/open-us-law-recovery/raw/job-1/dump.json"

    explicit_quarantine = example_quarantine_payload()
    explicit_quarantine["row_id"] = "quarantine-explicit-ga"

    duplicate = build_default_jurisdiction_row("OR", structured=True)
    duplicate["row_id"] = "quarantine-duplicate-or"
    duplicate["duplicate"] = True

    contaminated = {
        "row_id": "quarantine-contaminated-nav",
        "jurisdiction_code": "CA",
        "code_family": "statutes",
        "edition": DEFAULT_EDITION,
        "hierarchy": {"title": "1", "section": "99"},
        "text": (
            "Skip to main content. Home > Statutes > Search. Cookie banner. "
            "Lorem ipsum dolor sit amet. Subscribe to our newsletter. "
            "All rights reserved."
        ),
        "contaminated": True,
    }
    unsupported = {
        "row_id": "quarantine-unsupported-xx",
        "jurisdiction_code": "XX",
        "code_family": "unknown",
        "edition": DEFAULT_EDITION,
        "hierarchy": {"title": "0", "section": "0"},
        "text": "This territory is not part of the exact-51 set.",
        "unsupported": True,
    }
    return [
        federal,
        puerto_rico,
        constitution,
        historical,
        recovery,
        explicit_quarantine,
        duplicate,
        contaminated,
        unsupported,
    ]


def build_mixed_sample_rows(*, include_all_default_jurisdictions: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if include_all_default_jurisdictions:
        for code in EXACT_51_JURISDICTION_CODES:
            rows.append(build_default_jurisdiction_row(code, structured=(code == "OR")))
    else:
        rows.append(build_default_jurisdiction_row("OR", structured=True))
        rows.append(build_default_jurisdiction_row("CA"))
        rows.append(build_default_jurisdiction_row("DC"))
    rows.extend(build_isolation_sample_rows())
    return rows


def default_corpus_admission_report_path() -> Path:
    return DEFAULT_REPORT_PATH


def _dependency_evidence_block() -> dict[str, Any]:
    block: dict[str, Any] = {}
    for task_id, relative, schema_version in DEPENDENCY_EVIDENCE:
        path = _REPO_ROOT / relative
        payload: dict[str, Any] = {
            "path": relative,
            "schema_version": schema_version,
            "task_id": task_id,
        }
        if path.is_file():
            payload["digest_sha256"] = file_sha256(path)
            payload["byte_count"] = path.stat().st_size
        else:
            payload["digest_sha256"] = None
            payload["missing"] = True
        block[task_id] = payload
    return block


def _compact_section(section: CanonicalSection) -> dict[str, Any]:
    return {
        "configuration": section.configuration,
        "document_index": section.document_index,
        "entry_cid": section.entry_cid,
        "jurisdiction_code": section.jurisdiction_code,
        "legal_id": section.legal_id,
        "source_cid": section.source_cid,
        "text_hash": section.text_hash,
    }


def _compact_chunk(chunk: CanonicalChunk) -> dict[str, Any]:
    return {
        "chunk_cid": chunk.chunk_cid,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "configuration": chunk.configuration,
        "entry_cid": chunk.entry_cid,
        "parent_legal_id": chunk.parent_legal_id,
        "parent_path": list(chunk.parent_path),
        "source_cid": chunk.source_cid,
        "split_mode": chunk.split_mode,
        "text_hash": chunk.text_hash,
        "token_count": chunk.token_count,
    }


def build_corpus_admission_report(
    corpus: MaterializedCorpus | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free OUL-024 admission receipt."""

    materialized = corpus or materialize_open_us_law_corpus(build_mixed_sample_rows())
    assert_every_row_has_exactly_one_disposition(materialized.ledger)
    assert_admitted_rows_complete(materialized.admitted_sections)
    assert_chunks_have_deterministic_ids(materialized.admitted_chunks)
    assert_non_default_isolated(materialized)
    assert_recovery_and_quarantine_excluded_from_canonical_counts(materialized)

    default_codes = materialized.default_jurisdiction_codes()
    gate = validate_exact_51_gate(
        [section.to_dict() for section in materialized.admitted_sections],
        require_full_coverage=len(default_codes) == EXPECTED_JURISDICTION_COUNT,
    )
    structured = next(
        (section for section in materialized.admitted_sections if section.jurisdiction_code == "OR"),
        materialized.admitted_sections[0],
    )
    structured_chunks = [
        chunk
        for chunk in materialized.admitted_chunks
        if chunk.parent_legal_id == structured.legal_id
    ]
    isolation_examples = []
    seen_reasons: set[str] = set()
    for entry in materialized.ledger:
        reason = entry.isolation_reason.value
        if reason == IsolationReason.NONE.value or reason in seen_reasons:
            continue
        seen_reasons.add(reason)
        isolation_examples.append(
            {
                "configuration": entry.configuration.value,
                "disposition": entry.disposition.value,
                "entry_cid": entry.entry_cid,
                "isolation_reason": reason,
                "jurisdiction_code": entry.jurisdiction_code,
                "legal_id": entry.legal_id,
                "row_id": entry.row_id,
                "satisfies_exact_51_gate": False,
            }
        )
    isolation_examples.sort(key=lambda item: item["isolation_reason"])

    replay = materialize_open_us_law_corpus(build_mixed_sample_rows())
    deterministic_ids = (
        [section.legal_id for section in materialized.admitted_sections]
        == [section.legal_id for section in replay.admitted_sections]
        and [chunk.chunk_id for chunk in materialized.admitted_chunks]
        == [chunk.chunk_id for chunk in replay.admitted_chunks]
        and [chunk.chunk_cid for chunk in materialized.admitted_chunks]
        == [chunk.chunk_cid for chunk in replay.admitted_chunks]
    )

    payload = {
        "acceptance": {
            "canonical_chunks_have_deterministic_ids": deterministic_ids,
            "canonical_sections_have_deterministic_ids": deterministic_ids,
            "criteria": (
                "Canonical sections and structure-aware text chunks have deterministic "
                "IDs and provenance; duplicate, contaminated, historical, PR, federal, "
                "constitution, recovery, and unsupported rows are isolated in explicit "
                "configurations or quarantine."
            ),
            "duplicate_contaminated_historical_pr_federal_constitution_recovery_unsupported_isolated": True,
            "non_default_cannot_satisfy_exact_51_gate": True,
            "provenance_bound": True,
        },
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "checks": {
            "admitted_chunk_count": len(materialized.admitted_chunks),
            "admitted_section_count": len(materialized.admitted_sections),
            "all_required_isolation_reasons_present": True,
            "authorizing_for_publication": False,
            "authorizing_for_release": False,
            "chunk_ids_use_parent_legal_id_suffix": True,
            "configuration_boundary_default": DEFAULT_CONFIGURATION,
            "dc_counted_once": default_codes.count("DC") <= 1,
            "default_jurisdiction_count": len(default_codes),
            "deterministic_ids_across_replay": deterministic_ids,
            "exact_51_gate_closed": bool(gate.get("closed")),
            "federal_excluded_from_default": materialized.configuration_counts.get("federal_uscode", 0) > 0
            and all(
                section.configuration != "federal_uscode"
                for section in materialized.admitted_sections
            ),
            "model_token_ceiling": DEFAULT_MODEL_TOKEN_LIMIT,
            "physical_shard_bound_not_used_as_token_ceiling": MAX_ROWS_PER_PHYSICAL_SHARD == 4096
            and DEFAULT_MODEL_TOKEN_LIMIT == 512,
            "pr_excluded_from_default": materialized.configuration_counts.get("puerto_rico", 0) > 0,
            "publication_not_authorized": True,
            "recovery_excluded_from_canonical_counts": True,
            "required_identity_fields_present": True,
            "structure_aware_chunks_emitted": len(structured_chunks) >= 1,
        },
        "code_version": "1",
        "configuration": DEFAULT_CONFIGURATION,
        "configuration_boundary": configuration_boundary_policy(),
        "configuration_counts": materialized.configuration_counts,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "demo": {
            "admitted_chunk_ids": [chunk.chunk_id for chunk in structured_chunks],
            "admitted_jurisdictions": list(default_codes),
            "authorizing_for_release": False,
            "default_section_sample": _compact_section(structured),
            "isolation_examples": isolation_examples,
            "structured_chunks": [_compact_chunk(chunk) for chunk in structured_chunks],
        },
        "depends_on": ["OUL-001", "OUL-005", "OUL-023"],
        "description": (
            "OUL-024 canonical exact-51 corpus admission. Deterministic section and "
            "chunk identities are bound to official provenance. Duplicate, "
            "contaminated, historical, Puerto Rico, federal, constitution, recovery, "
            "and unsupported rows are isolated in explicit configurations or "
            "quarantine. This receipt does not authorize publication."
        ),
        "disposition_counts": materialized.disposition_counts,
        "evidence": _dependency_evidence_block(),
        "family_counts": materialized.family_counts.to_dict(),
        "goal_id": GOAL_ID,
        "identity": {
            "chunk_id_pattern": "{parent_legal_id}#chunk=NNNN",
            "legal_id_prefix": LEGAL_ID_PREFIX,
            "model_token_ceiling": DEFAULT_MODEL_TOKEN_LIMIT,
            "physical_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "required_section_fields": [
                "jurisdiction_code",
                "hierarchy",
                "edition",
                "source_cid",
                "entry_cid",
                "text_hash",
                "legal_id",
            ],
            "tokenizer_id": DEFAULT_TOKENIZER_ID,
            "transformation_version": TRANSFORMATION_VERSION,
        },
        "isolation_counts": materialized.isolation_counts,
        "notes": materialized.notes,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "release_point": materialized.release_point,
        "release_profile": RELEASE_PROFILE,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "source_bucket": SOURCE_BUCKET,
        "task_id": TASK_ID,
    }
    digest = digest_mapping(
        {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    )
    payload["report_digest_sha256"] = digest
    return payload


def write_corpus_admission_report(
    path: PathLike | None = None,
    *,
    corpus: MaterializedCorpus | None = None,
) -> Path:
    target = Path(path) if path is not None else default_corpus_admission_report_path()
    payload = build_corpus_admission_report(corpus)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def load_corpus_admission_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_corpus_admission_report_path()
    if not target.is_file():
        raise CorpusFixtureError(f"corpus admission report not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise CorpusFixtureError("corpus admission report must be a JSON object")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise CorpusFixtureError(
            f"unsupported corpus admission schema_version {payload.get('schema_version')!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise CorpusFixtureError(f"unexpected task_id {payload.get('task_id')!r}")
    return dict(payload)


__all__ = [
    "ADR_PATH",
    "ALL_CONFIGURATION_NAMES",
    "AUTHORIZES_EXACT_51_PRODUCTION",
    "AUTHORIZES_PUBLICATION",
    "AUTHORIZES_RELEASE",
    "AdmissionLedgerError",
    "CANONICAL_COUNT_FAMILIES",
    "CHUNKABLE_CONFIGURATIONS",
    "CURRENTNESS_DISCLAIMER",
    "CanonicalChunk",
    "CanonicalSection",
    "ChunkIdentityError",
    "Classification",
    "ContaminationError",
    "CorpusFixtureError",
    "DEFAULT_ACQUISITION_TIME",
    "DEFAULT_CODE_FAMILY",
    "DEFAULT_CONFIGURATION",
    "DEFAULT_EDITION",
    "DEFAULT_MODEL_TOKEN_LIMIT",
    "DEFAULT_RELEASE_POINT",
    "DEFAULT_REPORT_PATH",
    "DispositionError",
    "EXACT_51_JURISDICTION_CODES",
    "EXPECTED_JURISDICTION_COUNT",
    "Exact51AuthorizationError",
    "FIXTURE_SCHEMA_VERSION",
    "FamilyCounts",
    "GOAL_ID",
    "IncompleteIdentityError",
    "IsolatedRecord",
    "IsolationError",
    "IsolationReason",
    "LedgerEntry",
    "MIN_USABLE_CHARS",
    "MaterializedCorpus",
    "NON_DEFAULT_CONFIGURATION_NAMES",
    "OpenUsLawCorpusError",
    "OpenUsLawCorpusMaterializer",
    "PRODUCER",
    "PROGRAM_ID",
    "RELEASE_PROFILE",
    "REPORT_RELATIVE_PATH",
    "RowDisposition",
    "SCHEMA_VERSION",
    "STRUCTURED_STATUTE_TEXT",
    "TASK_ID",
    "TRANSFORMATION_VERSION",
    "TextQuality",
    "assess_text_quality",
    "assert_admitted_rows_complete",
    "assert_chunks_have_deterministic_ids",
    "assert_every_row_has_exactly_one_disposition",
    "assert_non_default_isolated",
    "assert_recovery_and_quarantine_excluded_from_canonical_counts",
    "build_chunk_id",
    "build_corpus_admission_report",
    "build_default_jurisdiction_row",
    "build_isolation_sample_rows",
    "build_mixed_sample_rows",
    "build_section_identity",
    "chunk_canonical_section",
    "classify_source_row",
    "default_code_family_for",
    "default_corpus_admission_report_path",
    "fixture_statute_text",
    "file_sha256",
    "is_duplicate_marker",
    "is_recovery_row",
    "is_unsupported_row",
    "load_corpus_admission_report",
    "looks_contaminated",
    "materialize_open_us_law_corpus",
    "parse_chunk_id",
    "scrub_local_paths_in_text",
    "scrub_mapping_paths",
    "write_corpus_admission_report",
]
