"""Canonical state-law corpus materialization and recovery quarantine (LCR-024).

This module owns the legal corpus projection and admission ledger for the
``state-laws-ir-graphrag/v2`` release. It streams verified per-jurisdiction
outputs, assigns durable identity and official provenance, deduplicates
logical/current-versus-history records, and isolates recovery/quarantine
material from default retrieval counts.

Design invariants
-----------------
* Every source item and every corpus row receives **exactly one** disposition.
* Admitted rows must satisfy the durable identity + official provenance
  contract from :mod:`state_laws_release_schema` and carry non-placeholder
  statutory text.
* Combined admitted count equals the deduped union of the 51 admitted shards.
  In the compact fixture world that is the 51-jurisdiction cohort receipts
  (two statutes each unless a receipt says otherwise).
* History versions, logical duplicates, secondary sources, placeholder text,
  and recovery/workflow rows cannot enter corpus/BM25/vector/graph counts.
* No network I/O, no Hub upload, and no token materialization. Unit tests use
  sealed compact receipts only. Physical Parquet encoding belongs to later
  tasks.

Depends on LCR-004 (release schema), LCR-006 (identity), and LCR-023
(acquisition-gap closure / passing 51 receipts).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Iterator, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
    SECONDARY_SOURCE_DOMAIN_MARKERS,
    reconcile_disposition,
    validate_jurisdiction_set,
)
from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    IdentityDisposition,
    LegalIdentity,
    identity_from_row,
    normalize_jurisdiction,
    resolve_version_dispositions,
    validate_primary_keys,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    RELEASE_PROFILE,
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
    AdmissionStatus,
    CorpusRecord,
    MissingAdmissionProvenanceError,
    RecoveryRecord,
    SourceAuthorityClass,
    VerificationResult,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    normalize_relative_artifact_path,
    normalize_sha256,
    validate_admission_provenance_fields,
    validate_durable_identity_fields,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER,
    OfficialSourceCatalog,
    get_official_source_catalog,
)

# ---------------------------------------------------------------------------
# Schema / task pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-corpus-v1"
FIXTURE_SCHEMA_VERSION: Final = "state-laws-admission-ledger-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-admission@1"
TASK_ID: Final = "LCR-024"
GOAL_ID: Final = "LCR-G030"
PRODUCER: Final = "state_laws_corpus.py"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "canonical-corpus"
PARSER_VERSION: Final = "state-laws-parser/v2"
TRANSFORMATION_VERSION: Final = "state-laws-corpus-transform-v1"
DEFAULT_ACQUISITION_TIME: Final = "2026-08-10T12:00:00Z"
DEFAULT_RELEASE_POINT: Final = content_sha256("lcr-024-canonical-corpus-v1")
MIN_USABLE_CHARS: Final = 64
COHORT_LETTERS: Final = tuple("ABCDEFGHIJKLM")
DEFAULT_STATUTES_PER_SHARD: Final = 2

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
AUTHORIZES_RELEASE: Final = False

REPORT_RELATIVE_PATH: Final = "docs/reports/legal_corpora_reindex/admission.json"
COHORT_REPORT_DIR_RELPATH: Final = "docs/reports/legal_corpora_reindex"
ACCEPTANCE_RELATIVE_PATH: Final = (
    "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH: Final = _REPO_ROOT / REPORT_RELATIVE_PATH

CANONICAL_COUNT_FAMILIES: Final = frozenset(
    {
        "corpus",
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

SOURCE_DISPOSITION_BUCKETS: Final = (
    "fetched",
    "excluded",
    "quarantined",
    "failed_final",
    "duplicates",
)

# ---------------------------------------------------------------------------
# Text / path patterns
# ---------------------------------------------------------------------------

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
    r"text not available|lorem-ipsum|sample statute text only",
    re.IGNORECASE,
)
_STATUTORY_SIGNAL_RE = re.compile(
    r"\b(?:shall|must|may not|section|subsection|chapter|title|article|"
    r"provided that|offense|penalty|licensed)\b|§",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HIERARCHY_SEGMENT_RE = re.compile(
    r"^(?P<key>title|chapter|part|article|section)[-_](?P<value>.+)$",
    re.IGNORECASE,
)
_ABSOLUTE_POSIX_RE = re.compile(
    r"(?:(?:/home|/Users|/tmp|/var|/opt|/usr/local|/mnt|/media|/data|"
    r"/workspace|/root)/\S+)"
)
_ABSOLUTE_WINDOWS_RE = re.compile(r"(?:[A-Za-z]:\\[^\s\"']+|\\\\[^\s\"']+)")
_FILE_URI_RE = re.compile(r"file:///[^\s\"']+", re.IGNORECASE)
_HOME_TILDE_RE = re.compile(r"(?:~(?:/[^\s\"']+)?)")
_HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{8,}")
_BEARER_RE = re.compile(r"Bearer\s+\S+")
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

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsCorpusError(ValueError):
    """Base error for state-law corpus materialization."""

    code: str = "state_laws_corpus_error"


class DispositionError(StateLawsCorpusError):
    """Raised when a source item or row lacks a unique valid disposition."""

    code = "disposition_invalid"


class AdmissionLedgerError(StateLawsCorpusError):
    """Raised when the admission ledger is incomplete or inconsistent."""

    code = "admission_ledger_invalid"


class IncompleteIdentityError(StateLawsCorpusError):
    """Raised when an admitted row is missing durable identity or provenance."""

    code = "incomplete_identity"


class PlaceholderTextError(StateLawsCorpusError):
    """Raised when placeholder/navigation text is treated as admitted law."""

    code = "placeholder_text"


class RecoveryContaminationError(StateLawsCorpusError):
    """Raised when recovery/quarantine rows leak into canonical counts."""

    code = "recovery_contamination"


class CombinedCountError(StateLawsCorpusError):
    """Raised when the combined corpus count is not the 51-shard deduped union."""

    code = "combined_count_mismatch"


class CorpusFixtureError(StateLawsCorpusError):
    """Raised when compact cohort receipts cannot be expanded."""

    code = "corpus_fixture_invalid"


class PathScrubError(StateLawsCorpusError):
    """Raised when an absolute local path cannot be scrubbed safely."""

    code = "path_scrub_invalid"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceItemDisposition(str, Enum):
    """Exactly-one scrape-level disposition for a discovered source unit."""

    FETCHED = "fetched"
    DUPLICATE = "duplicate"
    EXCLUDED = "excluded"
    QUARANTINED = "quarantined"
    FAILED_FINAL = "failed_final"

    @classmethod
    def coerce(cls, value: Any) -> "SourceItemDisposition":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "dup": cls.DUPLICATE,
            "duplicates": cls.DUPLICATE,
            "exclude": cls.EXCLUDED,
            "quarantine": cls.QUARANTINED,
            "failed": cls.FAILED_FINAL,
            "failed_final_item": cls.FAILED_FINAL,
            "fetch": cls.FETCHED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DispositionError(f"unknown source-item disposition: {value!r}")


class RowDisposition(str, Enum):
    """Exactly-one corpus disposition assigned to every materialized row."""

    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    HISTORY = "history"
    EXCLUDED = "excluded"
    QUARANTINED = "quarantined"
    RECOVERY = "recovery"
    FAILED_FINAL = "failed_final"

    @classmethod
    def coerce(cls, value: Any) -> "RowDisposition":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "admit": cls.ADMITTED,
            "include": cls.ADMITTED,
            "included": cls.ADMITTED,
            "dup": cls.DUPLICATE,
            "duplicate_logical": cls.DUPLICATE,
            "archive_history": cls.HISTORY,
            "changed_text_version": cls.HISTORY,
            "historical": cls.HISTORY,
            "exclude": cls.EXCLUDED,
            "reject": cls.EXCLUDED,
            "rejected": cls.EXCLUDED,
            "quarantine": cls.QUARANTINED,
            "recover": cls.RECOVERY,
            "failed": cls.FAILED_FINAL,
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
        if self is RowDisposition.RECOVERY or self is RowDisposition.HISTORY:
            return AdmissionStatus.RECOVERY
        if self is RowDisposition.QUARANTINED or self is RowDisposition.FAILED_FINAL:
            return AdmissionStatus.QUARANTINED
        return AdmissionStatus.EXCLUDED


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def repository_root(repo_root: PathLike | None = None) -> Path:
    if repo_root is None:
        return _REPO_ROOT
    return Path(repo_root).resolve()


def default_report_path(repo_root: PathLike | None = None) -> Path:
    return repository_root(repo_root) / REPORT_RELATIVE_PATH


def default_cohort_dir(repo_root: PathLike | None = None) -> Path:
    return repository_root(repo_root) / COHORT_REPORT_DIR_RELPATH


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsCorpusError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise StateLawsCorpusError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise StateLawsCorpusError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateLawsCorpusError(f"{name} must be an integer")
    if value < 0:
        raise StateLawsCorpusError(f"{name} must be >= 0")
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


def relative_repo_path(path: PathLike, *, repo_root: PathLike | None = None) -> str:
    root = repository_root(repo_root)
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix().lstrip("/")


def _is_absolute_local_path(text: str) -> bool:
    if not text:
        return False
    if text.startswith("file:///") or text.startswith("~"):
        return True
    if text.startswith("/") and not text.startswith("//"):
        return True
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        return True
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    return False


def scrub_local_path(value: Any, *, field_name: str = "path") -> Optional[str]:
    """Scrub one path-like string to a release-relative form or ``None``."""

    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise PathScrubError(
            f"{field_name} must be a string or null, got {type(value).__name__}"
        )
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.lower().startswith("file:///"):
        candidate = candidate[7:]
    elif candidate.lower().startswith("file://"):
        candidate = candidate[7:]
    if not _is_absolute_local_path(candidate) and not _is_absolute_local_path(text):
        cleaned = candidate.replace("\\", "/").lstrip("./")
        if ".." in PurePosixPath(cleaned).parts:
            return None
        if cleaned and not _is_absolute_local_path(cleaned):
            try:
                return normalize_relative_artifact_path(cleaned, name=field_name)
            except Exception:
                return cleaned
        return None
    normalized = candidate.replace("\\", "/")
    lower = normalized.lower()
    for marker in ("/recovery/", "/reports/", "/data/corpus/", "/receipts/"):
        idx = lower.find(marker)
        if idx >= 0:
            relative = normalized[idx + 1 :]
            try:
                return normalize_relative_artifact_path(relative, name=field_name)
            except Exception:
                return relative.lstrip("/")
    base = PurePosixPath(normalized).name
    if base and "." in base and base not in {".", ".."}:
        return f"recovery/scrubbed/{base}"
    return None


def scrub_local_paths_in_text(text: str) -> str:
    if not isinstance(text, str):
        raise PathScrubError("text must be a string")
    cleaned = _FILE_URI_RE.sub("[scrubbed-local-uri]", text)
    cleaned = _ABSOLUTE_WINDOWS_RE.sub("[scrubbed-local-path]", cleaned)
    cleaned = _ABSOLUTE_POSIX_RE.sub("[scrubbed-local-path]", cleaned)
    cleaned = _HOME_TILDE_RE.sub("[scrubbed-local-path]", cleaned)
    return cleaned


def scrub_mapping_paths(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise PathScrubError("payload must be a mapping")

    def _walk(value: Any, *, key: Optional[str] = None) -> Any:
        if isinstance(value, Mapping):
            return {str(k): _walk(v, key=str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(item, key=key) for item in value]
        if isinstance(value, str):
            if key is not None and key.lower() in _PATH_FIELD_NAMES:
                return scrub_local_path(value, field_name=key)
            if (
                _is_absolute_local_path(value)
                or _ABSOLUTE_POSIX_RE.search(value)
                or _ABSOLUTE_WINDOWS_RE.search(value)
                or _FILE_URI_RE.search(value)
            ):
                return scrub_local_paths_in_text(value)
            return value
        return value

    return _walk(dict(payload))


def assert_no_secrets_or_home_paths(payload: Mapping[str, Any]) -> None:
    dumped = canonical_json_dumps(payload)
    if "/home/" in dumped or "/Users/" in dumped:
        raise AdmissionLedgerError("admission payload must not contain absolute home paths")
    if _HF_TOKEN_RE.search(dumped) or _BEARER_RE.search(dumped):
        raise AdmissionLedgerError("admission payload must not contain token material")


# ---------------------------------------------------------------------------
# Text quality
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
        raise StateLawsCorpusError("text must be a string or null")
    else:
        raw = unicodedata.normalize("NFC", text)
    stripped = _HTML_TAG_RE.sub(" ", raw)
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
    return TextQuality(
        usable_chars=usable,
        navigation_detected=navigation,
        footer_detected=footer,
        placeholder_detected=placeholder,
        statutory_signal=statutory,
        contaminated=contaminated,
        reasons=tuple(reasons),
    )


def looks_placeholder(text: Any) -> bool:
    return assess_text_quality(text).contaminated


def fixture_statute_text(
    jurisdiction: str,
    section: str,
    *,
    min_chars: int = 0,
    variant: str = "current",
) -> str:
    """Deterministic non-placeholder official-style text for compact fixtures."""

    body = (
        f"{jurisdiction} official statutes section {section} shall apply to every "
        f"person subject to this title. The provisions of this section must be "
        f"construed together with the remainder of the chapter. A licensee shall "
        f"keep records of every licensed activity and may not treat this text as "
        f"a summary or placeholder ({variant})."
    )
    if min_chars and len(body) < min_chars:
        pad = " Additional official codified text."
        repeats = (min_chars - len(body)) // max(len(pad), 1) + 1
        body = body + (pad * repeats)
        if len(body) < min_chars:
            body = body + (" x" * (min_chars - len(body)))
        body = body[: max(min_chars, len(body))]
    return body


# ---------------------------------------------------------------------------
# Receipt loading / expansion
# ---------------------------------------------------------------------------


def cohort_receipt_path(letter: str, *, repo_root: PathLike | None = None) -> Path:
    code = _require_non_empty_str(letter, "cohort").upper()
    if code not in COHORT_LETTERS:
        raise CorpusFixtureError(f"unknown cohort letter: {letter!r}")
    return default_cohort_dir(repo_root) / f"cohort_{code.lower()}.json"


def load_json_mapping(path: PathLike) -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CorpusFixtureError(f"cannot read {target}") from exc
    except json.JSONDecodeError as exc:
        raise CorpusFixtureError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CorpusFixtureError(f"{target} root must be a JSON object")
    return payload


def load_cohort_receipts(*, repo_root: PathLike | None = None) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for letter in COHORT_LETTERS:
        path = cohort_receipt_path(letter, repo_root=repo_root)
        if not path.is_file():
            raise CorpusFixtureError(f"missing cohort receipt: {relative_repo_path(path, repo_root=repo_root)}")
        receipts[letter] = load_json_mapping(path)
    return receipts


def iter_jurisdiction_receipts(
    *,
    repo_root: PathLike | None = None,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    loaded = receipts if receipts is not None else load_cohort_receipts(repo_root=repo_root)
    seen: set[str] = set()
    for letter in COHORT_LETTERS:
        payload = loaded.get(letter)
        if not isinstance(payload, Mapping):
            raise CorpusFixtureError(f"cohort {letter} receipt missing")
        block = payload.get("jurisdiction_receipts") or {}
        if not isinstance(block, Mapping) or not block:
            raise CorpusFixtureError(f"cohort {letter} has no jurisdiction_receipts")
        for raw_code, raw_receipt in block.items():
            code = str(raw_code).strip().upper()
            if code in seen:
                raise CorpusFixtureError(f"jurisdiction {code} appears in multiple cohort receipts")
            seen.add(code)
            if not isinstance(raw_receipt, Mapping):
                raise CorpusFixtureError(f"{code} receipt must be a mapping")
            yield letter, code, dict(raw_receipt)
    validate_jurisdiction_set(seen)


def parse_hierarchy_unit(unit: Any) -> dict[str, str]:
    if unit is None or unit == "":
        return {}
    text = str(unit).strip().strip("/")
    parts: dict[str, str] = {}
    for segment in text.split("/"):
        match = _HIERARCHY_SEGMENT_RE.match(segment.strip())
        if match:
            parts[match.group("key").lower()] = match.group("value")
    return parts


def parse_canonical_section(key: Any, *, jurisdiction: str) -> str:
    text = _require_non_empty_str(str(key), "canonical_key")
    prefix = f"{jurisdiction.lower()}:"
    if text.lower().startswith(prefix):
        return text[len(prefix) :]
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def code_family_for(
    jurisdiction: str,
    receipt: Mapping[str, Any] | None = None,
    *,
    catalog: OfficialSourceCatalog | None = None,
) -> str:
    if receipt is not None:
        explicit = receipt.get("code_family") or receipt.get("code_family_id")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        families = receipt.get("code_family_ids") or receipt.get("code_families")
        if isinstance(families, Sequence) and not isinstance(families, (str, bytes)) and families:
            first = families[0]
            if isinstance(first, Mapping):
                ident = first.get("code_family_id") or first.get("id")
                if ident:
                    return str(ident)
            return str(first)
    source = catalog if catalog is not None else get_official_source_catalog()
    record = source.get(jurisdiction)
    if not record.code_families:
        raise CorpusFixtureError(f"catalog has no code family for {jurisdiction}")
    return record.code_families[0].code_family_id


def _host_is_secondary(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().strip().strip(".")
    if not host:
        return False
    for marker in SECONDARY_SOURCE_DOMAIN_MARKERS:
        if host == marker or host.endswith("." + marker):
            return True
    return False


def _default_reason(disposition: RowDisposition) -> str:
    return {
        RowDisposition.ADMITTED: "canonical official-source row with complete identity and provenance",
        RowDisposition.DUPLICATE: "logical duplicate of an admitted current record",
        RowDisposition.HISTORY: "prior content version archived as history",
        RowDisposition.EXCLUDED: "excluded from default search by source disposition or policy",
        RowDisposition.QUARANTINED: "quarantined: secondary, placeholder, or incomplete provenance",
        RowDisposition.RECOVERY: "recovery/workflow row isolated from canonical counts",
        RowDisposition.FAILED_FINAL: "failed-final source unit cannot be admitted",
    }[disposition]


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceItem:
    """One discovered source unit with exactly one scrape disposition."""

    item_id: str
    jurisdiction: str
    disposition: SourceItemDisposition
    reason: str
    canonical_key: Optional[str] = None
    official_source_url: Optional[str] = None
    cohort: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _require_non_empty_str(self.item_id, "item_id"))
        object.__setattr__(
            self, "jurisdiction", str(self.jurisdiction).strip().upper()
        )
        object.__setattr__(self, "disposition", SourceItemDisposition.coerce(self.disposition))
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        if not isinstance(self.payload, Mapping):
            raise StateLawsCorpusError("source item payload must be a mapping")
        object.__setattr__(self, "payload", dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "cohort": self.cohort,
            "disposition": self.disposition.value,
            "item_id": self.item_id,
            "jurisdiction": self.jurisdiction,
            "official_source_url": self.official_source_url,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One corpus-row disposition with identity links when present."""

    row_id: str
    disposition: RowDisposition
    reason: str
    jurisdiction: Optional[str] = None
    entry_cid: Optional[str] = None
    legal_id: Optional[str] = None
    source_cid: Optional[str] = None
    recovery_id: Optional[str] = None
    source_item_id: Optional[str] = None
    document_index: Optional[int] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _require_non_empty_str(self.row_id, "row_id"))
        object.__setattr__(self, "disposition", RowDisposition.coerce(self.disposition))
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "jurisdiction": self.jurisdiction,
            "legal_id": self.legal_id,
            "reason": self.reason,
            "recovery_id": self.recovery_id,
            "row_id": self.row_id,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "source_item_id": self.source_item_id,
        }


@dataclass(frozen=True, slots=True)
class FamilyCounts:
    corpus: int = 0
    bm25: int = 0
    vector: int = 0
    graph: int = 0
    recovery: int = 0
    quarantine: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "bm25": self.bm25,
            "corpus": self.corpus,
            "graph": self.graph,
            "quarantine": self.quarantine,
            "recovery": self.recovery,
            "vector": self.vector,
        }


@dataclass(frozen=True, slots=True)
class JurisdictionShard:
    jurisdiction: str
    cohort: str
    source_items: tuple[SourceItem, ...]
    candidate_rows: tuple[dict[str, Any], ...]
    statutes_count: int
    content_digest: Optional[str] = None
    receipt_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_row_count": len(self.candidate_rows),
            "cohort": self.cohort,
            "content_digest": self.content_digest,
            "jurisdiction": self.jurisdiction,
            "receipt_path": self.receipt_path,
            "source_item_count": len(self.source_items),
            "statutes_count": self.statutes_count,
        }


@dataclass(frozen=True, slots=True)
class MaterializedCorpus:
    """Result of streaming 51 shards into a canonical corpus + quarantine."""

    ledger: tuple[LedgerEntry, ...]
    source_items: tuple[SourceItem, ...]
    admitted_rows: tuple[dict[str, Any], ...]
    history_rows: tuple[dict[str, Any], ...]
    duplicate_rows: tuple[dict[str, Any], ...]
    excluded_rows: tuple[dict[str, Any], ...]
    quarantine_rows: tuple[dict[str, Any], ...]
    recovery_rows: tuple[dict[str, Any], ...]
    family_counts: FamilyCounts
    shard_admitted_counts: Mapping[str, int]
    release_point: str
    schema_version: str = SCHEMA_VERSION
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER
    notes: str = ""
    input_receipts: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        seen_rows: dict[str, str] = {}
        for entry in self.ledger:
            prior = seen_rows.get(entry.row_id)
            if prior is not None:
                raise DispositionError(
                    f"row_id {entry.row_id!r} has multiple dispositions: "
                    f"{prior!r} and {entry.disposition.value!r}"
                )
            seen_rows[entry.row_id] = entry.disposition.value
        seen_items: dict[str, str] = {}
        for item in self.source_items:
            prior = seen_items.get(item.item_id)
            if prior is not None:
                raise DispositionError(
                    f"source item {item.item_id!r} has multiple dispositions: "
                    f"{prior!r} and {item.disposition.value!r}"
                )
            seen_items[item.item_id] = item.disposition.value
        if len(self.ledger) != (
            len(self.admitted_rows)
            + len(self.history_rows)
            + len(self.duplicate_rows)
            + len(self.excluded_rows)
            + len(self.quarantine_rows)
            + len(self.recovery_rows)
        ):
            raise AdmissionLedgerError("ledger length does not match partitioned rows")
        for row in self.admitted_rows:
            try:
                CorpusRecord.from_mapping(row)
            except Exception as exc:
                raise IncompleteIdentityError(
                    f"admitted corpus row failed schema validation: {exc}"
                ) from exc
            quality = assess_text_quality(row.get("text") or "")
            if quality.contaminated:
                raise PlaceholderTextError(
                    f"admitted row {row.get('legal_id')!r} has placeholder/non-usable text"
                )
        if self.family_counts.corpus != len(self.admitted_rows):
            raise RecoveryContaminationError(
                "corpus family count must equal admitted row count"
            )
        for family, count in (
            ("bm25", self.family_counts.bm25),
            ("vector", self.family_counts.vector),
            ("graph", self.family_counts.graph),
        ):
            if count != len(self.admitted_rows):
                raise RecoveryContaminationError(
                    f"{family} family count must equal admitted row count"
                )
        isolated = len(self.history_rows) + len(self.recovery_rows)
        if self.family_counts.recovery != isolated:
            raise RecoveryContaminationError(
                "recovery family count must equal history+recovery rows"
            )
        if self.family_counts.quarantine != len(self.quarantine_rows):
            raise RecoveryContaminationError(
                "quarantine family count must equal quarantine rows"
            )

    @property
    def disposition_counts(self) -> dict[str, int]:
        counts = {item.value: 0 for item in RowDisposition}
        for entry in self.ledger:
            counts[entry.disposition.value] += 1
        return counts

    @property
    def source_disposition_counts(self) -> dict[str, int]:
        counts = {item.value: 0 for item in SourceItemDisposition}
        for item in self.source_items:
            counts[item.disposition.value] += 1
        return counts

    def default_jurisdiction_codes(self) -> tuple[str, ...]:
        present = {str(row["jurisdiction"]).upper() for row in self.admitted_rows}
        return tuple(code for code in CANONICAL_JURISDICTION_ORDER if code in present)

    def combined_admitted_count(self) -> int:
        return len(self.admitted_rows)

    def shard_sum_before_dedup(self) -> int:
        return int(sum(self.shard_admitted_counts.values()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_count": len(self.admitted_rows),
            "currentness_disclaimer": self.currentness_disclaimer,
            "disposition_counts": self.disposition_counts,
            "family_counts": self.family_counts.to_dict(),
            "input_receipts": [dict(item) for item in self.input_receipts],
            "ledger": [entry.to_dict() for entry in self.ledger],
            "notes": self.notes,
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "shard_admitted_counts": dict(self.shard_admitted_counts),
            "source_disposition_counts": self.source_disposition_counts,
            "source_item_count": len(self.source_items),
        }

    def admission_report(self) -> dict[str, Any]:
        jurisdictions = self.default_jurisdiction_codes()
        per_jurisdiction: list[dict[str, Any]] = []
        by_code: dict[str, list[dict[str, Any]]] = {}
        for row in self.admitted_rows:
            by_code.setdefault(str(row["jurisdiction"]).upper(), []).append(row)
        for code in CANONICAL_JURISDICTION_ORDER:
            rows = by_code.get(code, [])
            per_jurisdiction.append(
                {
                    "admitted_count": len(rows),
                    "jurisdiction": code,
                    "legal_ids": [row["legal_id"] for row in rows],
                    "shard_count_before_dedup": int(self.shard_admitted_counts.get(code, 0)),
                }
            )
        expected_union = len(
            {
                row["legal_id"]
                for row in self.admitted_rows
            }
        )
        payload = {
            "acceptance": {
                "admitted_rows_have_complete_official_provenance": True,
                "admitted_rows_non_placeholder_text": True,
                "authorizes_hub_upload": AUTHORIZES_HUB_UPLOAD,
                "authorizes_publication": AUTHORIZES_PUBLICATION,
                "combined_count_equals_deduped_union": True,
                "every_row_has_one_disposition": True,
                "every_source_item_has_one_disposition": True,
                "exact_51": len(jurisdictions) == EXPECTED_JURISDICTION_COUNT,
                "includes_dc": "DC" in jurisdictions,
                "no_absolute_home_paths": True,
                "no_hub_upload": True,
                "no_token_material": True,
                "recovery_quarantine_isolated": True,
            },
            "adr_path": ADR_PATH,
            "combined": {
                "admitted_row_count": len(self.admitted_rows),
                "deduped_union": expected_union,
                "duplicate_row_count": len(self.duplicate_rows),
                "excluded_row_count": len(self.excluded_rows),
                "history_row_count": len(self.history_rows),
                "jurisdiction_count": len(jurisdictions),
                "quarantine_row_count": len(self.quarantine_rows),
                "recovery_row_count": len(self.recovery_rows),
                "shard_sum_before_dedup": self.shard_sum_before_dedup(),
                "source_item_count": len(self.source_items),
            },
            "currentness_disclaimer": self.currentness_disclaimer,
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "disposition_counts": self.disposition_counts,
            "family_counts": self.family_counts.to_dict(),
            "goal_id": GOAL_ID,
            "includes_dc": "DC" in jurisdictions,
            "inputs": {
                "cohort_receipts": [dict(item) for item in self.input_receipts],
            },
            "jurisdictions": list(jurisdictions),
            "notes": self.notes,
            "parser_version": PARSER_VERSION,
            "per_jurisdiction": per_jurisdiction,
            "producer": PRODUCER,
            "program_id": PROGRAM_ID,
            "recovery_excluded_from_families": sorted(CANONICAL_COUNT_FAMILIES),
            "release_point": self.release_point,
            "release_profile": RELEASE_PROFILE,
            "release_schema_version": RELEASE_SCHEMA_VERSION,
            "schema": REPORT_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "source_disposition_counts": self.source_disposition_counts,
            "status": "pass",
            "task_id": TASK_ID,
            "transformation_version": TRANSFORMATION_VERSION,
        }
        assert_no_secrets_or_home_paths(payload)
        return payload


# ---------------------------------------------------------------------------
# Expansion of compact receipts
# ---------------------------------------------------------------------------


def expand_jurisdiction_receipt(
    jurisdiction: str,
    receipt: Mapping[str, Any],
    *,
    cohort: str,
    catalog: OfficialSourceCatalog | None = None,
    receipt_path: str | None = None,
) -> JurisdictionShard:
    """Expand one compact jurisdiction receipt into source items + candidate rows."""

    code = str(jurisdiction).strip().upper()
    content = receipt.get("content") if isinstance(receipt.get("content"), Mapping) else {}
    index_keys = receipt.get("index_keys") if isinstance(receipt.get("index_keys"), Mapping) else {}
    disposition = receipt.get("disposition") if isinstance(receipt.get("disposition"), Mapping) else {}
    probes = receipt.get("boundary_probes") if isinstance(receipt.get("boundary_probes"), Mapping) else {}

    canonical_keys = [str(item) for item in (index_keys.get("canonical_keys") or ())]
    official_urls = [str(item) for item in (content.get("official_urls") or ())]
    statutes_count = int(receipt.get("statutes_count") or receipt.get("row_count") or len(canonical_keys) or DEFAULT_STATUTES_PER_SHARD)
    min_chars = int(content.get("min_full_text_chars") or MIN_USABLE_CHARS)
    content_digest = content.get("content_digest") or receipt.get("content_digest")
    if isinstance(content_digest, str) and content_digest.startswith("sha256:"):
        digest_hex = content_digest[7:]
    elif isinstance(content_digest, str):
        digest_hex = content_digest
    else:
        digest_hex = content_sha256(f"{code}:{cohort}:compact")
        content_digest = f"sha256:{digest_hex}"
    authority = str(
        receipt.get("source_authority_class") or SourceAuthorityClass.OFFICIAL.value
    )
    family = code_family_for(code, receipt, catalog=catalog)
    first_unit = parse_hierarchy_unit(probes.get("first_hierarchy_unit"))
    last_unit = parse_hierarchy_unit(probes.get("last_hierarchy_unit"))
    receipt_id = f"cohort-{cohort}-{code}"

    fetched = int(disposition.get("fetched") or len(canonical_keys) or 0)
    duplicates = int(disposition.get("duplicates") or 0)
    excluded = int(disposition.get("excluded") or 0)
    quarantined = int(disposition.get("quarantined") or 0)
    failed_final = int(disposition.get("failed_final") or receipt.get("failed_final") or 0)
    discovered = int(disposition.get("discovered") or (fetched + excluded + quarantined + failed_final))
    ok, detail = reconcile_disposition(
        {
            "discovered": discovered,
            "fetched": fetched,
            "excluded": excluded,
            "quarantined": quarantined,
            "failed_final": failed_final,
            "duplicates": duplicates,
        }
    )
    if not ok:
        raise CorpusFixtureError(f"{code} disposition arithmetic failed: {detail}")

    if not canonical_keys and fetched:
        raise CorpusFixtureError(f"{code} fetched={fetched} but canonical_keys are empty")
    if fetched and len(canonical_keys) != fetched:
        # Compact receipts should name every fetched unit.
        if len(canonical_keys) < fetched:
            raise CorpusFixtureError(
                f"{code} canonical_keys ({len(canonical_keys)}) < fetched ({fetched})"
            )

    source_items: list[SourceItem] = []
    candidates: list[dict[str, Any]] = []

    for index, key in enumerate(canonical_keys[:fetched]):
        section = parse_canonical_section(key, jurisdiction=code)
        hierarchy = first_unit if index == 0 else (last_unit if index == len(canonical_keys) - 1 else dict(first_unit))
        url = official_urls[index] if index < len(official_urls) else (
            official_urls[-1] if official_urls else f"https://example.invalid/official/{code.lower()}/{section}"
        )
        item_id = f"{code}-source-fetched-{index:02d}"
        source_items.append(
            SourceItem(
                item_id=item_id,
                jurisdiction=code,
                disposition=SourceItemDisposition.FETCHED,
                reason="fetched official source unit from closed-frontier compact receipt",
                canonical_key=key,
                official_source_url=url,
                cohort=cohort,
                payload={"statutes_count": statutes_count},
            )
        )
        text = fixture_statute_text(code, section, min_chars=min_chars, variant="current")
        row = {
            "row_id": f"{code}-row-{index:02d}",
            "source_item_id": item_id,
            "jurisdiction": code,
            "code_family": family,
            "section": hierarchy.get("section") or section,
            "title": hierarchy.get("title"),
            "chapter": hierarchy.get("chapter"),
            "part": hierarchy.get("part"),
            "article": hierarchy.get("article"),
            "kind": "section",
            "text": text,
            "official_source_url": url,
            "source_authority_class": authority,
            "source_checksum": digest_hex,
            "release_point": content_digest,
            "acquisition_time": DEFAULT_ACQUISITION_TIME,
            "acquisition_receipt_id": receipt_id,
            "parser_version": PARSER_VERSION,
            "verification_result": VerificationResult.VERIFIED.value,
            "canonical_key": key,
            "cohort": cohort,
            "content_digest": content_digest,
        }
        candidates.append(row)

    def _bucket(kind: SourceItemDisposition, count: int, reason: str) -> None:
        for index in range(count):
            source_items.append(
                SourceItem(
                    item_id=f"{code}-source-{kind.value}-{index:02d}",
                    jurisdiction=code,
                    disposition=kind,
                    reason=reason,
                    cohort=cohort,
                )
            )

    _bucket(SourceItemDisposition.DUPLICATE, duplicates, "scrape-level duplicate unit")
    _bucket(SourceItemDisposition.EXCLUDED, excluded, "source unit excluded by receipt")
    _bucket(SourceItemDisposition.QUARANTINED, quarantined, "source unit quarantined by receipt")
    _bucket(SourceItemDisposition.FAILED_FINAL, failed_final, "source unit failed-final")

    return JurisdictionShard(
        jurisdiction=code,
        cohort=cohort,
        source_items=tuple(source_items),
        candidate_rows=tuple(candidates),
        statutes_count=statutes_count,
        content_digest=str(content_digest),
        receipt_path=receipt_path,
    )


def stream_verified_state_outputs(
    *,
    repo_root: PathLike | None = None,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
    catalog: OfficialSourceCatalog | None = None,
) -> Iterator[JurisdictionShard]:
    """Stream compact 51-jurisdiction receipts as verified shards."""

    source = catalog if catalog is not None else get_official_source_catalog()
    loaded = receipts if receipts is not None else load_cohort_receipts(repo_root=repo_root)
    for letter, code, receipt in iter_jurisdiction_receipts(repo_root=repo_root, receipts=loaded):
        path = cohort_receipt_path(letter, repo_root=repo_root)
        yield expand_jurisdiction_receipt(
            code,
            receipt,
            cohort=letter,
            catalog=source,
            receipt_path=relative_repo_path(path, repo_root=repo_root),
        )


# ---------------------------------------------------------------------------
# Classification / row construction
# ---------------------------------------------------------------------------


def _safe_jurisdiction(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        return normalize_jurisdiction(value)
    except Exception:
        return None


def classify_source_row(row: Mapping[str, Any]) -> RowDisposition:
    """Determine the corpus disposition for one source/candidate row."""

    if not isinstance(row, Mapping):
        raise StateLawsCorpusError("source row must be a mapping")

    explicit = row.get("row_disposition") or row.get("disposition")
    if explicit not in (None, "", "fetched"):
        coerced = RowDisposition.coerce(explicit)
        if coerced is not RowDisposition.ADMITTED:
            return coerced

    if bool(row.get("is_recovery") or row.get("recovery")):
        return RowDisposition.RECOVERY
    raw_jurisdiction = row.get("jurisdiction") or row.get("state_code") or row.get("state")
    if raw_jurisdiction not in (None, "") and _safe_jurisdiction(raw_jurisdiction) is None:
        return RowDisposition.QUARANTINED
    kind = str(row.get("kind") or "").strip().lower()
    if kind in {"history", "historical", "hist"}:
        return RowDisposition.HISTORY
    status = str(row.get("admission_status") or "").strip().lower()
    if status in {"excluded", "exclude", "rejected", "reject"}:
        return RowDisposition.EXCLUDED
    if status in {"quarantined", "quarantine"}:
        return RowDisposition.QUARANTINED
    if status in {"recovery"}:
        return RowDisposition.RECOVERY
    if status in {"history", "historical"}:
        return RowDisposition.HISTORY
    if status in {"failed_final", "failed"}:
        return RowDisposition.FAILED_FINAL

    authority = str(row.get("source_authority_class") or "").strip().lower()
    if authority in {"secondary"}:
        return RowDisposition.QUARANTINED
    url = str(row.get("official_source_url") or row.get("source_url") or "")
    if url and _host_is_secondary(url):
        return RowDisposition.QUARANTINED
    text = row.get("text") or row.get("body") or ""
    if looks_placeholder(text):
        return RowDisposition.QUARANTINED
    if bool(row.get("contaminated") or row.get("placeholder")):
        return RowDisposition.QUARANTINED
    return RowDisposition.ADMITTED


def _build_identity(row: Mapping[str, Any]) -> LegalIdentity:
    try:
        return identity_from_row(row)
    except Exception as exc:
        raise IncompleteIdentityError(f"cannot build legal identity: {exc}") from exc


def _synthetic_digest(label: str) -> str:
    return content_sha256(label)


def _build_admitted_corpus_row(
    row: Mapping[str, Any],
    *,
    document_index: int,
    release_point: str,
    reason: str,
) -> dict[str, Any]:
    scrubbed = scrub_mapping_paths(row)
    identity = _build_identity(scrubbed)
    text = scrub_local_paths_in_text(
        unicodedata.normalize("NFC", str(scrubbed.get("text") or scrubbed.get("body") or ""))
    )
    quality = assess_text_quality(text)
    if quality.contaminated:
        raise PlaceholderTextError(
            f"cannot admit placeholder/non-usable text for {identity.legal_id}"
        )
    url = _require_non_empty_str(
        scrubbed.get("official_source_url") or scrubbed.get("source_url"),
        "official_source_url",
        maximum=2048,
    )
    if not url.lower().startswith(("http://", "https://")):
        raise IncompleteIdentityError("official_source_url must be an absolute http(s) URL")
    checksum_raw = scrubbed.get("source_checksum") or scrubbed.get("content_digest")
    if checksum_raw:
        source_checksum = normalize_sha256(str(checksum_raw), name="source_checksum")
    else:
        source_checksum = _synthetic_digest(f"checksum|{identity.legal_id}|{url}")
    source_cid = scrubbed.get("source_cid") or f"sha256:{_synthetic_digest(f'source|{url}|{identity.legal_id}|{source_checksum}')}"
    entry_cid = scrubbed.get("entry_cid") or f"sha256:{_synthetic_digest(f'entry|{identity.legal_id}|{text}|{url}')}"
    row_release = scrubbed.get("release_point") or release_point
    payload = {
        "acquisition_receipt_id": scrubbed.get("acquisition_receipt_id")
        or f"scrape-{identity.jurisdiction.lower()}",
        "acquisition_time": scrubbed.get("acquisition_time") or DEFAULT_ACQUISITION_TIME,
        "admission_reason": reason,
        "admission_status": AdmissionStatus.ADMITTED.value,
        "chapter": identity.chapter or scrubbed.get("chapter"),
        "code_family": identity.code_family,
        "document_index": scrubbed.get("document_index", document_index),
        "edition_as_of": scrubbed.get("edition_as_of") or identity.edition,
        "entry_cid": entry_cid,
        "jurisdiction": identity.jurisdiction,
        "legal_id": identity.legal_id,
        "observed_at": scrubbed.get("observed_at") or scrubbed.get("acquisition_time"),
        "official_source_url": url,
        "parent_path": identity.path,
        "parser_version": scrubbed.get("parser_version") or PARSER_VERSION,
        "release_point": row_release,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "section": identity.section,
        "source_authority_class": scrubbed.get("source_authority_class")
        or SourceAuthorityClass.OFFICIAL.value,
        "source_checksum": source_checksum,
        "source_cid": source_cid,
        "subsection": identity.subsection,
        "text": text,
        "title": identity.title,
        "verification_result": scrubbed.get("verification_result")
        or VerificationResult.VERIFIED.value,
    }
    try:
        record = CorpusRecord.from_mapping(payload)
        validate_durable_identity_fields(record.to_dict())
        validate_admission_provenance_fields(record.to_dict())
    except Exception as exc:
        raise IncompleteIdentityError(
            f"admitted corpus row failed schema validation: {exc}"
        ) from exc
    return record.to_dict()


def _build_recovery_row(
    row: Mapping[str, Any],
    *,
    recovery_index: int,
    reason: str,
    status: AdmissionStatus = AdmissionStatus.RECOVERY,
    jurisdiction: Optional[str] = None,
) -> dict[str, Any]:
    scrubbed = scrub_mapping_paths(row)
    recovery_id = (
        scrubbed.get("recovery_id")
        or f"recovery-{str(jurisdiction or scrubbed.get('jurisdiction') or 'xx').lower()}-{recovery_index:04d}"
    )
    recovery_id = str(recovery_id).strip()
    if re.fullmatch(r"(?:row[-_ ]?\d+|row[-_ ]?N|idx[-_ ]?\d+)", recovery_id, re.I):
        recovery_id = f"recovery-{recovery_index:04d}"
    source_path = scrub_local_path(
        scrubbed.get("source_path") or scrubbed.get("local_path") or scrubbed.get("path"),
        field_name="source_path",
    )
    if source_path is None:
        source_path = f"recovery/raw-{recovery_index:04d}.json"
    raw_digest = scrubbed.get("raw_digest") or _synthetic_digest(
        json.dumps(
            {k: v for k, v in scrubbed.items() if k not in {"text", "body"}},
            sort_keys=True,
            default=str,
        )
    )
    payload_body = {
        k: v
        for k, v in scrubbed.items()
        if k
        not in {
            "text",
            "body",
            "source_path",
            "local_path",
            "path",
            "absolute_path",
        }
    }
    record = RecoveryRecord(
        recovery_id=recovery_id,
        reason=reason,
        source_path=source_path,
        raw_digest=raw_digest if str(raw_digest).startswith("sha256:") else f"sha256:{normalize_sha256(str(raw_digest))}",
        admission_status=status,
        jurisdiction=jurisdiction or _safe_jurisdiction(scrubbed.get("jurisdiction")),
        payload=payload_body,
        schema_version=RELEASE_SCHEMA_VERSION,
    )
    return record.to_dict()


def _non_admitted_projection(
    row: Mapping[str, Any],
    *,
    disposition: RowDisposition,
    reason: str,
    document_index: int,
) -> dict[str, Any]:
    scrubbed = scrub_mapping_paths(row)
    legal_id = scrubbed.get("legal_id")
    section = scrubbed.get("section")
    jurisdiction = scrubbed.get("jurisdiction")
    try:
        identity = _build_identity(scrubbed)
        legal_id = identity.legal_id
        section = identity.section
        jurisdiction = identity.jurisdiction
    except Exception:
        pass
    return {
        "admission_reason": reason,
        "admission_status": disposition.to_admission_status().value,
        "disposition": disposition.value,
        "document_index": document_index,
        "entry_cid": scrubbed.get("entry_cid"),
        "jurisdiction": jurisdiction,
        "legal_id": legal_id,
        "row_id": scrubbed.get("row_id") or f"{disposition.value}-{document_index:05d}",
        "schema_version": SCHEMA_VERSION,
        "section": section,
        "source_item_id": scrubbed.get("source_item_id"),
    }


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


class StateLawsCorpusMaterializer:
    """Materialize canonical corpus rows and a recovery/quarantine ledger."""

    def __init__(
        self,
        *,
        release_point: str = DEFAULT_RELEASE_POINT,
        acquisition_time: str = DEFAULT_ACQUISITION_TIME,
        repo_root: PathLike | None = None,
    ) -> None:
        self.release_point = _require_non_empty_str(release_point, "release_point")
        if self.release_point.strip().lower() in {"latest", "main", "head"}:
            raise StateLawsCorpusError(
                f"release_point must be an exact pin, not {release_point!r}"
            )
        self.acquisition_time = _require_non_empty_str(
            acquisition_time, "acquisition_time"
        )
        self.repo_root = repository_root(repo_root)

    def materialize_from_receipts(
        self,
        *,
        extra_rows: Sequence[Mapping[str, Any]] = (),
        notes: str = "",
    ) -> MaterializedCorpus:
        shards = list(stream_verified_state_outputs(repo_root=self.repo_root))
        if len(shards) != EXPECTED_JURISDICTION_COUNT:
            raise CombinedCountError(
                f"expected {EXPECTED_JURISDICTION_COUNT} shards, got {len(shards)}"
            )
        source_items: list[SourceItem] = []
        candidates: list[dict[str, Any]] = []
        shard_fetched: dict[str, int] = {}
        input_receipts: list[dict[str, Any]] = []
        seen_inputs: set[str] = set()
        for shard in shards:
            source_items.extend(shard.source_items)
            for row in shard.candidate_rows:
                candidates.append(dict(row))
            shard_fetched[shard.jurisdiction] = len(shard.candidate_rows)
            if shard.receipt_path and shard.receipt_path not in seen_inputs:
                seen_inputs.add(shard.receipt_path)
                path = self.repo_root / shard.receipt_path
                input_receipts.append(
                    {
                        "cohort": shard.cohort,
                        "content_id": f"sha256:{file_sha256(path)}" if path.is_file() else shard.content_digest,
                        "path": shard.receipt_path,
                        "source": "file",
                    }
                )
        extra_source_offset = 0
        for extra in extra_rows:
            if not isinstance(extra, Mapping):
                raise StateLawsCorpusError("extra_rows entries must be mappings")
            row = dict(extra)
            extra_source_offset += 1
            item_id = str(
                row.get("source_item_id") or row.get("row_id") or f"extra-source-{extra_source_offset:04d}"
            )
            jurisdiction = str(row.get("jurisdiction") or "AL").upper()
            classified = classify_source_row(row)
            source_disp = {
                RowDisposition.EXCLUDED: SourceItemDisposition.EXCLUDED,
                RowDisposition.QUARANTINED: SourceItemDisposition.QUARANTINED,
                RowDisposition.FAILED_FINAL: SourceItemDisposition.FAILED_FINAL,
                RowDisposition.DUPLICATE: SourceItemDisposition.DUPLICATE,
            }.get(classified, SourceItemDisposition.FETCHED)
            source_items.append(
                SourceItem(
                    item_id=item_id,
                    jurisdiction=jurisdiction,
                    disposition=source_disp,
                    reason="explicit extra source row",
                    canonical_key=row.get("canonical_key"),
                    official_source_url=row.get("official_source_url"),
                )
            )
            row.setdefault("source_item_id", item_id)
            row.setdefault("row_id", f"extra-row-{extra_source_offset:04d}")
            if source_disp is SourceItemDisposition.FETCHED or classified in {
                RowDisposition.ADMITTED,
                RowDisposition.HISTORY,
                RowDisposition.DUPLICATE,
                RowDisposition.RECOVERY,
            }:
                candidates.append(row)
            else:
                # Non-fetched extras still become rows via the candidate path so
                # every extra is accounted; classify_source_row decides later.
                candidates.append(row)
        return self.materialize(
            candidates,
            source_items=source_items,
            shard_fetched=shard_fetched,
            input_receipts=input_receipts,
            notes=notes,
        )

    def materialize(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        source_items: Sequence[SourceItem] = (),
        shard_fetched: Mapping[str, int] | None = None,
        input_receipts: Sequence[Mapping[str, Any]] = (),
        notes: str = "",
    ) -> MaterializedCorpus:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise StateLawsCorpusError("rows must be a sequence of mappings")

        pre_classified: list[tuple[dict[str, Any], RowDisposition]] = []
        merge_pool: list[dict[str, Any]] = []
        merge_indexes: list[int] = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                raise StateLawsCorpusError(f"rows[{index}] must be a mapping")
            row = scrub_mapping_paths(raw)
            row.setdefault("row_id", f"corpus-row-{index:05d}")
            row.setdefault("acquisition_time", self.acquisition_time)
            disposition = classify_source_row(row)
            pre_classified.append((row, disposition))
            if disposition in {RowDisposition.ADMITTED, RowDisposition.DUPLICATE, RowDisposition.HISTORY}:
                try:
                    identity_from_row(row)
                except Exception:
                    # Incomplete identity is quarantined later, not merged.
                    pass
                else:
                    merge_pool.append(row)
                    merge_indexes.append(index)

        versioned = resolve_version_dispositions(merge_pool) if merge_pool else {
            "dispositions": [],
            "current_rows": [],
            "history_by_key": {},
        }
        merge_by_index: dict[int, str] = {}
        for event in versioned.get("dispositions") or ():
            pool_index = int(event["row_index"])
            source_index = merge_indexes[pool_index]
            merge_by_index[source_index] = str(event["disposition"])

        ledger: list[LedgerEntry] = []
        admitted: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        quarantine: list[dict[str, Any]] = []
        recovery: list[dict[str, Any]] = []
        seen_row_ids: set[str] = set()
        admitted_index = 0
        recovery_index = 0
        per_jurisdiction_unique: dict[str, set[str]] = {}

        for index, (row, classified) in enumerate(pre_classified):
            row_id = str(row.get("row_id"))
            if row_id in seen_row_ids:
                raise DispositionError(f"duplicate row_id in source batch: {row_id!r}")
            seen_row_ids.add(row_id)
            merge_disp = merge_by_index.get(index)
            disposition = classified
            reason = _optional_str(row.get("admission_reason") or row.get("reason")) or _default_reason(
                disposition
            )
            if classified is RowDisposition.ADMITTED and merge_disp:
                if merge_disp == IdentityDisposition.DUPLICATE.value:
                    disposition = RowDisposition.DUPLICATE
                    reason = _default_reason(disposition)
                elif merge_disp in {
                    IdentityDisposition.CHANGED_TEXT_VERSION.value,
                    IdentityDisposition.ARCHIVE_HISTORY.value,
                }:
                    disposition = RowDisposition.HISTORY
                    reason = _default_reason(disposition)
                elif merge_disp == IdentityDisposition.KEEP_CURRENT.value:
                    disposition = RowDisposition.ADMITTED

            if disposition is RowDisposition.ADMITTED:
                try:
                    corpus_row = _build_admitted_corpus_row(
                        row,
                        document_index=admitted_index,
                        release_point=row.get("release_point") or self.release_point,
                        reason=reason,
                    )
                except (IncompleteIdentityError, PlaceholderTextError, MissingAdmissionProvenanceError) as exc:
                    disposition = RowDisposition.QUARANTINED
                    reason = f"admission failed closed: {exc}"
                    recovery_index += 1
                    qrow = _build_recovery_row(
                        row,
                        recovery_index=recovery_index,
                        reason=reason,
                        status=AdmissionStatus.QUARANTINED,
                        jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                    )
                    quarantine.append(qrow)
                    ledger.append(
                        LedgerEntry(
                            row_id=row_id,
                            disposition=RowDisposition.QUARANTINED,
                            reason=reason,
                            jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                            recovery_id=qrow.get("recovery_id"),
                            source_item_id=_optional_str(row.get("source_item_id")),
                            document_index=index,
                        )
                    )
                    continue
                admitted.append(corpus_row)
                per_jurisdiction_unique.setdefault(corpus_row["jurisdiction"], set()).add(
                    corpus_row["legal_id"]
                )
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.ADMITTED,
                        reason=reason,
                        jurisdiction=corpus_row["jurisdiction"],
                        entry_cid=corpus_row["entry_cid"],
                        legal_id=corpus_row["legal_id"],
                        source_cid=corpus_row["source_cid"],
                        source_item_id=_optional_str(row.get("source_item_id")),
                        document_index=corpus_row.get("document_index"),
                    )
                )
                admitted_index += 1
            elif disposition is RowDisposition.HISTORY:
                recovery_index += 1
                hist = _build_recovery_row(
                    row,
                    recovery_index=recovery_index,
                    reason=reason,
                    status=AdmissionStatus.RECOVERY,
                    jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                )
                history.append(hist)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.HISTORY,
                        reason=reason,
                        jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                        legal_id=_optional_str(row.get("legal_id")),
                        recovery_id=hist.get("recovery_id"),
                        source_item_id=_optional_str(row.get("source_item_id")),
                        document_index=index,
                    )
                )
            elif disposition is RowDisposition.RECOVERY:
                recovery_index += 1
                rec = _build_recovery_row(
                    row,
                    recovery_index=recovery_index,
                    reason=reason,
                    status=AdmissionStatus.RECOVERY,
                    jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                )
                recovery.append(rec)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.RECOVERY,
                        reason=reason,
                        jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                        recovery_id=rec.get("recovery_id"),
                        source_item_id=_optional_str(row.get("source_item_id")),
                        document_index=index,
                    )
                )
            elif disposition is RowDisposition.QUARANTINED:
                recovery_index += 1
                qrow = _build_recovery_row(
                    row,
                    recovery_index=recovery_index,
                    reason=reason,
                    status=AdmissionStatus.QUARANTINED,
                    jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                )
                quarantine.append(qrow)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.QUARANTINED,
                        reason=reason,
                        jurisdiction=_safe_jurisdiction(row.get("jurisdiction")),
                        recovery_id=qrow.get("recovery_id"),
                        source_item_id=_optional_str(row.get("source_item_id")),
                        document_index=index,
                    )
                )
            elif disposition is RowDisposition.DUPLICATE:
                proj = _non_admitted_projection(
                    row, disposition=disposition, reason=reason, document_index=index
                )
                duplicates.append(proj)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.DUPLICATE,
                        reason=reason,
                        jurisdiction=_optional_str(proj.get("jurisdiction")),
                        legal_id=_optional_str(proj.get("legal_id")),
                        source_item_id=_optional_str(row.get("source_item_id")),
                        document_index=index,
                    )
                )
            elif disposition is RowDisposition.FAILED_FINAL:
                proj = _non_admitted_projection(
                    row, disposition=disposition, reason=reason, document_index=index
                )
                excluded.append(proj)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.FAILED_FINAL,
                        reason=reason,
                        jurisdiction=_optional_str(proj.get("jurisdiction")),
                        source_item_id=_optional_str(row.get("source_item_id")),
                        document_index=index,
                    )
                )
            else:
                proj = _non_admitted_projection(
                    row, disposition=RowDisposition.EXCLUDED, reason=reason, document_index=index
                )
                excluded.append(proj)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.EXCLUDED,
                        reason=reason,
                        jurisdiction=_optional_str(proj.get("jurisdiction")),
                        source_item_id=_optional_str(row.get("source_item_id")),
                        document_index=index,
                    )
                )

        if admitted:
            validate_primary_keys(admitted, key_field="entry_cid")

        shard_counts = {
            code: len(ids) for code, ids in sorted(per_jurisdiction_unique.items())
        }
        if shard_fetched:
            # Deduped union uses unique legal_ids after merge; per-shard unique
            # counts are the post-admission unique keys in that jurisdiction.
            for code, fetched in shard_fetched.items():
                shard_counts.setdefault(code, 0)
                _ = fetched

        n_admitted = len(admitted)
        counts = FamilyCounts(
            corpus=n_admitted,
            bm25=n_admitted,
            vector=n_admitted,
            graph=n_admitted,
            recovery=len(history) + len(recovery),
            quarantine=len(quarantine),
        )
        items = tuple(source_items) if source_items else tuple(
            SourceItem(
                item_id=entry.row_id,
                jurisdiction=entry.jurisdiction or "AL",
                disposition={
                    RowDisposition.ADMITTED: SourceItemDisposition.FETCHED,
                    RowDisposition.DUPLICATE: SourceItemDisposition.DUPLICATE,
                    RowDisposition.HISTORY: SourceItemDisposition.FETCHED,
                    RowDisposition.EXCLUDED: SourceItemDisposition.EXCLUDED,
                    RowDisposition.QUARANTINED: SourceItemDisposition.QUARANTINED,
                    RowDisposition.RECOVERY: SourceItemDisposition.QUARANTINED,
                    RowDisposition.FAILED_FINAL: SourceItemDisposition.FAILED_FINAL,
                }[entry.disposition],
                reason=entry.reason,
            )
            for entry in ledger
        )
        return MaterializedCorpus(
            ledger=tuple(ledger),
            source_items=items,
            admitted_rows=tuple(admitted),
            history_rows=tuple(history),
            duplicate_rows=tuple(duplicates),
            excluded_rows=tuple(excluded),
            quarantine_rows=tuple(quarantine),
            recovery_rows=tuple(recovery),
            family_counts=counts,
            shard_admitted_counts=shard_counts,
            release_point=self.release_point,
            notes=notes
            or (
                "Canonical 51-jurisdiction corpus projection from compact cohort "
                "receipts. History, duplicates, recovery, and quarantine are "
                "isolated from default retrieval counts. Fixture materialization "
                "does not authorize Hub upload or publication."
            ),
            input_receipts=tuple(dict(item) for item in input_receipts),
        )


def materialize_state_laws_corpus(
    rows: Sequence[Mapping[str, Any]] | None = None,
    *,
    extra_rows: Sequence[Mapping[str, Any]] = (),
    from_cohort_receipts: bool = True,
    repo_root: PathLike | None = None,
    release_point: str = DEFAULT_RELEASE_POINT,
    notes: str = "",
) -> MaterializedCorpus:
    """Functional entry point for corpus materialization."""

    materializer = StateLawsCorpusMaterializer(
        release_point=release_point,
        repo_root=repo_root,
    )
    if from_cohort_receipts and rows is None:
        return materializer.materialize_from_receipts(extra_rows=extra_rows, notes=notes)
    if rows is None:
        raise StateLawsCorpusError("rows are required when from_cohort_receipts is false")
    combined = list(rows)
    combined.extend(list(extra_rows))
    return materializer.materialize(combined, notes=notes)


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


def assert_every_source_item_has_exactly_one_disposition(
    items: Sequence[SourceItem | Mapping[str, Any]],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in items:
        if isinstance(item, SourceItem):
            item_id = item.item_id
            disposition = item.disposition.value
        else:
            item_id = str(item.get("item_id") or "")
            disposition = SourceItemDisposition.coerce(item.get("disposition")).value
        if not item_id:
            raise DispositionError("source item missing item_id")
        if item_id in mapping:
            raise DispositionError(
                f"source item {item_id!r} has multiple dispositions: "
                f"{mapping[item_id]!r} and {disposition!r}"
            )
        mapping[item_id] = disposition
    if not mapping:
        raise DispositionError("source item ledger is empty")
    return mapping


def assert_admitted_rows_complete(rows: Sequence[Mapping[str, Any]]) -> None:
    for index, row in enumerate(rows):
        try:
            record = CorpusRecord.from_mapping(row)
        except Exception as exc:
            raise IncompleteIdentityError(f"admitted_rows[{index}] incomplete: {exc}") from exc
        if record.admission_status is not AdmissionStatus.ADMITTED:
            raise IncompleteIdentityError(
                f"admitted_rows[{index}] status is {record.admission_status.value}"
            )
        if record.source_authority_class is SourceAuthorityClass.SECONDARY:
            raise IncompleteIdentityError(
                f"admitted_rows[{index}] has secondary provenance"
            )
        quality = assess_text_quality(record.text)
        if quality.contaminated or not quality.statutory_signal:
            raise PlaceholderTextError(
                f"admitted_rows[{index}] lacks non-placeholder statutory text"
            )


def assert_combined_count_equals_deduped_union(corpus: MaterializedCorpus) -> None:
    legal_ids = [row["legal_id"] for row in corpus.admitted_rows]
    if len(legal_ids) != len(set(legal_ids)):
        raise CombinedCountError("admitted legal_id values are not unique")
    union = len(set(legal_ids))
    if corpus.combined_admitted_count() != union:
        raise CombinedCountError(
            f"combined count {corpus.combined_admitted_count()} != deduped union {union}"
        )
    shard_sum = int(sum(corpus.shard_admitted_counts.values()))
    if corpus.combined_admitted_count() != shard_sum:
        raise CombinedCountError(
            f"combined count {corpus.combined_admitted_count()} != "
            f"sum of shard unique keys {shard_sum}"
        )


def assert_recovery_quarantine_excluded_from_canonical_counts(
    corpus: MaterializedCorpus,
) -> None:
    admitted = len(corpus.admitted_rows)
    recovery = len(corpus.history_rows) + len(corpus.recovery_rows)
    quarantine = len(corpus.quarantine_rows)
    counts = corpus.family_counts.to_dict()
    for family in ("corpus", "bm25", "vector", "graph"):
        if counts[family] != admitted:
            raise RecoveryContaminationError(
                f"{family} count includes non-admitted rows"
            )
        if recovery and counts[family] == admitted + recovery:
            raise RecoveryContaminationError(
                f"{family} count appears to include recovery rows"
            )
        if quarantine and counts[family] == admitted + quarantine:
            raise RecoveryContaminationError(
                f"{family} count appears to include quarantine rows"
            )
    if counts["recovery"] != recovery or counts["quarantine"] != quarantine:
        raise RecoveryContaminationError("recovery/quarantine counts are inconsistent")


def expected_compact_admitted_count(
    *,
    repo_root: PathLike | None = None,
    receipts: Mapping[str, Mapping[str, Any]] | None = None,
) -> int:
    """Return the expected combined count from compact 51-jurisdiction receipts."""

    total = 0
    for _letter, _code, receipt in iter_jurisdiction_receipts(
        repo_root=repo_root, receipts=receipts
    ):
        keys = ((receipt.get("index_keys") or {}).get("canonical_keys")) or ()
        statutes = int(receipt.get("statutes_count") or len(keys) or DEFAULT_STATUTES_PER_SHARD)
        total += statutes
    return total


# ---------------------------------------------------------------------------
# Report I/O
# ---------------------------------------------------------------------------


def build_corpus_admission_report(
    corpus: MaterializedCorpus | None = None,
    *,
    repo_root: PathLike | None = None,
) -> dict[str, Any]:
    materialized = corpus or materialize_state_laws_corpus(repo_root=repo_root)
    assert_every_row_has_exactly_one_disposition(materialized.ledger)
    assert_every_source_item_has_exactly_one_disposition(materialized.source_items)
    assert_admitted_rows_complete(materialized.admitted_rows)
    assert_combined_count_equals_deduped_union(materialized)
    assert_recovery_quarantine_excluded_from_canonical_counts(materialized)
    codes = materialized.default_jurisdiction_codes()
    if len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise CombinedCountError(
            f"admitted jurisdictions {len(codes)} != {EXPECTED_JURISDICTION_COUNT}"
        )
    if "DC" not in codes:
        raise CombinedCountError("admitted set omits DC")
    expected = expected_compact_admitted_count(repo_root=repo_root)
    if materialized.combined_admitted_count() != expected:
        raise CombinedCountError(
            f"combined admitted {materialized.combined_admitted_count()} != "
            f"compact receipt union {expected}"
        )
    report = materialized.admission_report()
    report["content_id"] = f"sha256:{digest_mapping(report)}"
    return report


def write_admission_report(
    path: PathLike | None = None,
    *,
    corpus: MaterializedCorpus | None = None,
    repo_root: PathLike | None = None,
) -> Path:
    """Write the compact admission ledger. Never contacts the Hub."""

    target = Path(path) if path is not None else default_report_path(repo_root)
    report = build_corpus_admission_report(corpus, repo_root=repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def load_admission_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_report_path()
    payload = load_json_mapping(target)
    assert_no_secrets_or_home_paths(payload)
    return payload


def build_explicit_statute_row(
    jurisdiction: str,
    section: str,
    *,
    title: str | None = "1",
    chapter: str | None = "1",
    text: str | None = None,
    kind: str = "section",
    official_source_url: str | None = None,
    row_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Helper used by unit tests to inject extra rows hermetically."""

    code = str(jurisdiction).strip().upper()
    family = kwargs.pop("code_family", None) or code_family_for(code)
    body = text if text is not None else fixture_statute_text(code, section)
    url = official_source_url or f"https://legislature.example.gov/{code.lower()}/{section}"
    payload = {
        "row_id": row_id or f"{code}-{section}-{kind}",
        "jurisdiction": code,
        "code_family": family,
        "section": section,
        "title": title,
        "chapter": chapter,
        "kind": kind,
        "text": body,
        "official_source_url": url,
        "source_authority_class": kwargs.pop(
            "source_authority_class", SourceAuthorityClass.OFFICIAL.value
        ),
        "parser_version": PARSER_VERSION,
        "acquisition_time": DEFAULT_ACQUISITION_TIME,
        "acquisition_receipt_id": f"test-{code.lower()}",
        "verification_result": VerificationResult.VERIFIED.value,
        "release_point": DEFAULT_RELEASE_POINT,
        "source_checksum": content_sha256(f"{code}:{section}:{body}"),
    }
    payload.update(kwargs)
    return payload
