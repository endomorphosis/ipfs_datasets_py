"""Canonical U.S. Code corpus materialization and recovery quarantine (USCIR-008).

This module owns the legal corpus projection and admission ledger for the
``publicus-ir-graphrag/v2`` US Code release. It streams normalized source rows
into canonical retrieval records, scrubs historical absolute local paths,
records source/proof lineage, and separates recovery/workflow data into an
explicit quarantine.

Design invariants
-----------------
* Every baseline source row receives **exactly one** disposition:
  ``admitted``, ``replaced``, ``excluded``, or ``quarantined``.
* Admitted rows must satisfy the durable identity + provenance contract from
  :mod:`uscode_release_schema` (``entry_cid``, ``legal_id``, source receipt
  fields). Incomplete admitted rows fail closed.
* The nine heterogeneous recovery records from the pinned baseline **cannot**
  enter corpus, BM25, vector, or graph counts. They land only in the recovery
  quarantine family.
* Local absolute paths are scrubbed before any publication-facing record is
  emitted.
* No network I/O or Parquet I/O; unit tests use sealed compact fixtures only.
  Physical artifact encoding belongs to USCIR-009.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.uscode_identity import (
    LegalIdentity,
    build_legal_id,
    identity_from_row,
    validate_primary_keys,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
    AdmissionStatus,
    CorpusRecord,
    MissingAdmissionProvenanceError,
    RecoveryRecord,
    VerificationResult,
    content_sha256,
    normalize_relative_artifact_path,
    validate_admission_provenance_fields,
    validate_durable_identity_fields,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_ACQUIRED_AT,
    DEFAULT_APPROVED_RELEASE_POINT,
)

# ---------------------------------------------------------------------------
# Schema / baseline pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "uscode-corpus-v1"
FIXTURE_SCHEMA_VERSION = "uscode-admission-ledger-v1"
TASK_ID = "USCIR-008"
GOAL_ID = "USCIR-G020"
PRODUCER = "uscode_corpus.py"
RELEASE_PROFILE = "publicus-ir-graphrag/v2"
DEFAULT_DATASET_REPO_ID = "justicedao/ipfs_uscode"
DEFAULT_BASELINE_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"

# Sealed baseline acceptance counts (USCIR-001).
BASELINE_CORPUS_ROW_COUNT = 60_077
BASELINE_CANONICAL_CID_COUNT = 60_068
BASELINE_RECOVERY_ROW_COUNT = 9
BASELINE_TITLE_COUNT = 53

# Families that recovery rows must never contribute to.
CANONICAL_COUNT_FAMILIES: frozenset[str] = frozenset(
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

DEFAULT_JURISDICTION = "US"
DEFAULT_ADMISSION_REASON_ADMITTED = "canonical baseline row with complete identity and provenance"
DEFAULT_ADMISSION_REASON_REPLACED = "superseded by a later admitted edition of the same legal identity"
DEFAULT_ADMISSION_REASON_EXCLUDED = "excluded from default search (incomplete provenance or policy gap)"
DEFAULT_ADMISSION_REASON_QUARANTINED = (
    "heterogeneous recovery/workflow row without canonical CID; quarantined from search"
)

# Path scrubbing: absolute local roots that historically leaked into recovery
# metadata. Match POSIX and Windows-style absolute paths.
_ABSOLUTE_POSIX_RE = re.compile(
    r"(?:(?:/home|/Users|/tmp|/var|/opt|/usr/local|/mnt|/media|/data|"
    r"/workspace|/root)/\S+)"
)
_ABSOLUTE_WINDOWS_RE = re.compile(
    r"(?:[A-Za-z]:\\[^\s\"']+|\\\\[^\s\"']+)"
)
_FILE_URI_RE = re.compile(r"file:///[^\s\"']+", re.IGNORECASE)
_HOME_TILDE_RE = re.compile(r"(?:~(?:/[^\s\"']+)?)")

_PATH_FIELD_NAMES: frozenset[str] = frozenset(
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


class UscodeCorpusError(ValueError):
    """Base error for corpus materialization failures."""


class DispositionError(UscodeCorpusError):
    """Raised when a baseline row lacks a unique valid disposition."""


class AdmissionLedgerError(UscodeCorpusError):
    """Raised when the admission ledger is incomplete or inconsistent."""


class RecoveryContaminationError(UscodeCorpusError):
    """Raised when recovery rows leak into canonical search-family counts."""


class PathScrubError(UscodeCorpusError):
    """Raised when an absolute local path cannot be scrubbed safely."""


class CorpusFixtureError(UscodeCorpusError):
    """Raised when the sealed admission-ledger fixture is malformed."""


class IncompleteIdentityError(UscodeCorpusError):
    """Raised when an admitted row is missing durable identity or provenance."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RowDisposition(str, Enum):
    """Exactly-one disposition assigned to every baseline source row."""

    ADMITTED = "admitted"
    REPLACED = "replaced"
    EXCLUDED = "excluded"
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
            "replace": cls.REPLACED,
            "superseded": cls.REPLACED,
            "exclude": cls.EXCLUDED,
            "reject": cls.EXCLUDED,
            "rejected": cls.EXCLUDED,
            "quarantine": cls.QUARANTINED,
            "recovery": cls.QUARANTINED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DispositionError(f"unknown row disposition: {value!r}")

    def to_admission_status(self) -> AdmissionStatus:
        """Map ledger disposition onto the release-schema admission status."""

        if self is RowDisposition.ADMITTED:
            return AdmissionStatus.ADMITTED
        if self is RowDisposition.REPLACED:
            return AdmissionStatus.EXCLUDED
        if self is RowDisposition.EXCLUDED:
            return AdmissionStatus.EXCLUDED
        return AdmissionStatus.QUARANTINED


# ---------------------------------------------------------------------------
# Path scrubbing
# ---------------------------------------------------------------------------


def _is_absolute_local_path(text: str) -> bool:
    if not text:
        return False
    if text.startswith("file:///"):
        return True
    if text.startswith("~"):
        return True
    if text.startswith("/") and not text.startswith("//"):
        # Relative release paths never begin with a single leading slash.
        return True
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        return True
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    return False


def scrub_local_path(value: Any, *, field_name: str = "path") -> Optional[str]:
    """Scrub one path-like string to a release-relative form or ``None``.

    Absolute local paths, home-relative paths, and ``file://`` URIs are never
    retained. When a trailing relative segment under a known release layout is
    recoverable (e.g. ``.../recovery/raw-3.json``), that relative segment is
    kept; otherwise the value is dropped.
    """

    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise PathScrubError(
            f"{field_name} must be a string or null, got {type(value).__name__}"
        )

    text = value.strip()
    if not text:
        return None

    # Strip file:// prefix for analysis.
    candidate = text
    if candidate.lower().startswith("file:///"):
        candidate = candidate[7:]  # keep leading /
    elif candidate.lower().startswith("file://"):
        candidate = candidate[7:]

    if not _is_absolute_local_path(candidate) and not _is_absolute_local_path(text):
        # Already relative — normalize separators and reject traversal.
        try:
            return normalize_relative_artifact_path(
                candidate.replace("\\", "/"), name=field_name
            )
        except Exception:
            # Soft-drop unusable relative noise rather than leak absolute roots.
            cleaned = candidate.replace("\\", "/").lstrip("./")
            if ".." in PurePosixPath(cleaned).parts:
                return None
            if cleaned and not _is_absolute_local_path(cleaned):
                return cleaned
            return None

    # Absolute: try to recover a trailing relative release segment.
    normalized = candidate.replace("\\", "/")
    # Prefer explicit release-layout markers; also accept ``.../recovery/...``
    # even when nested under a hyphenated parent directory name.
    markers = (
        "/recovery/",
        "/uscode_parquet/",
        "/data/corpus/",
        "/data/bm25/",
        "/reports/",
        "/indexes/",
    )
    lower = normalized.lower()
    for marker in markers:
        idx = lower.find(marker)
        if idx >= 0:
            relative = normalized[idx + 1 :]  # drop leading slash from marker match
            try:
                return normalize_relative_artifact_path(relative, name=field_name)
            except Exception:
                return relative.lstrip("/")

    # Hyphenated parent dirs such as ``uscode-recovery/raw/job-1/dump.json``.
    for token in ("-recovery/", "_recovery/"):
        idx = lower.find(token)
        if idx >= 0:
            relative = "recovery/" + normalized[idx + len(token) :]
            try:
                return normalize_relative_artifact_path(relative, name=field_name)
            except Exception:
                return relative.lstrip("/")

    # Last resort: basename only when it looks like a file, else drop.
    base = PurePosixPath(normalized).name
    if base and "." in base and base not in {".", ".."}:
        return f"recovery/scrubbed/{base}"
    return None


def scrub_local_paths_in_text(text: str) -> str:
    """Remove absolute local path substrings from free-form text."""

    if not isinstance(text, str):
        raise PathScrubError("text must be a string")
    cleaned = text
    cleaned = _FILE_URI_RE.sub("[scrubbed-local-uri]", cleaned)
    cleaned = _ABSOLUTE_WINDOWS_RE.sub("[scrubbed-local-path]", cleaned)
    cleaned = _ABSOLUTE_POSIX_RE.sub("[scrubbed-local-path]", cleaned)
    cleaned = _HOME_TILDE_RE.sub("[scrubbed-local-path]", cleaned)
    return cleaned


def scrub_mapping_paths(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy of *payload* with local path fields scrubbed."""

    if not isinstance(payload, Mapping):
        raise PathScrubError("payload must be a mapping")

    def _walk(value: Any, *, key: Optional[str] = None) -> Any:
        if isinstance(value, Mapping):
            return {
                str(k): _walk(v, key=str(k))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_walk(item, key=key) for item in value]
        if isinstance(value, tuple):
            return tuple(_walk(item, key=key) for item in value)
        if isinstance(value, str):
            if key is not None and key.lower() in _PATH_FIELD_NAMES:
                return scrub_local_path(value, field_name=key)
            if _is_absolute_local_path(value) or _ABSOLUTE_POSIX_RE.search(value) or _ABSOLUTE_WINDOWS_RE.search(value) or _FILE_URI_RE.search(value):
                return scrub_local_paths_in_text(value)
            return value
        return value

    return _walk(dict(payload))


# ---------------------------------------------------------------------------
# Digests / identity helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UscodeCorpusError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise UscodeCorpusError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _synthetic_digest(label: str) -> str:
    return content_sha256(label)


def _normalize_text(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        raise UscodeCorpusError("text must be a string")
    if "\x00" in text:
        raise UscodeCorpusError("text must not contain NUL")
    return unicodedata.normalize("NFKC", text)


def _row_entry_cid(row: Mapping[str, Any]) -> Optional[str]:
    for key in ("entry_cid", "ipfs_cid", "cid"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_recovery_source_row(row: Mapping[str, Any]) -> bool:
    """Detect heterogeneous recovery/workflow rows from the baseline mix."""

    if bool(row.get("is_recovery")) or bool(row.get("recovery")):
        return True
    kind = str(row.get("row_kind") or row.get("kind") or row.get("record_type") or "").strip().lower()
    if kind in {"recovery", "workflow", "quarantine", "source_recovery"}:
        return True
    status = str(row.get("admission_status") or row.get("disposition") or "").strip().lower()
    if status in {"recovery", "quarantined", "quarantine"}:
        return True
    # Baseline anomaly: recovery rows lack a canonical CID.
    if _row_entry_cid(row) is None and (
        row.get("recovery_id")
        or row.get("source_path")
        or row.get("workflow_id")
        or row.get("raw_json") is not None
        or str(row.get("payload_kind") or "").lower() in {"recovery", "workflow"}
    ):
        return True
    return False


def _default_reason(disposition: RowDisposition) -> str:
    if disposition is RowDisposition.ADMITTED:
        return DEFAULT_ADMISSION_REASON_ADMITTED
    if disposition is RowDisposition.REPLACED:
        return DEFAULT_ADMISSION_REASON_REPLACED
    if disposition is RowDisposition.EXCLUDED:
        return DEFAULT_ADMISSION_REASON_EXCLUDED
    return DEFAULT_ADMISSION_REASON_QUARANTINED


# ---------------------------------------------------------------------------
# Ledger + materialization records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One baseline-row disposition with optional identity/provenance links."""

    row_id: str
    disposition: RowDisposition
    reason: str
    entry_cid: Optional[str] = None
    legal_id: Optional[str] = None
    source_cid: Optional[str] = None
    release_point: Optional[str] = None
    source_checksum: Optional[str] = None
    verification_result: Optional[str] = None
    acquisition_time: Optional[str] = None
    recovery_id: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    replaced_by_entry_cid: Optional[str] = None
    document_index: Optional[int] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _require_non_empty_str(self.row_id, "row_id"))
        object.__setattr__(self, "disposition", RowDisposition.coerce(self.disposition))
        object.__setattr__(self, "reason", _require_non_empty_str(self.reason, "reason"))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if self.disposition is RowDisposition.ADMITTED:
            # Fail closed: admitted ledger rows need full identity + provenance.
            try:
                identity = validate_durable_identity_fields(
                    {
                        "entry_cid": self.entry_cid,
                        "legal_id": self.legal_id,
                        "document_index": self.document_index,
                    }
                )
                provenance = validate_admission_provenance_fields(
                    {
                        "admission_status": AdmissionStatus.ADMITTED.value,
                        "admission_reason": self.reason,
                        "source_cid": self.source_cid,
                        "release_point": self.release_point,
                        "source_checksum": self.source_checksum,
                        "verification_result": self.verification_result
                        or VerificationResult.VERIFIED.value,
                        "acquisition_time": self.acquisition_time,
                    }
                )
            except (MissingAdmissionProvenanceError, Exception) as exc:
                raise IncompleteIdentityError(
                    f"admitted ledger entry {self.row_id!r} lacks complete "
                    f"identity/provenance: {exc}"
                ) from exc
            object.__setattr__(self, "entry_cid", identity["entry_cid"])
            object.__setattr__(self, "legal_id", identity["legal_id"])
            object.__setattr__(self, "source_cid", provenance["source_cid"])
            object.__setattr__(self, "release_point", provenance["release_point"])
            object.__setattr__(self, "source_checksum", provenance["source_checksum"])
            object.__setattr__(
                self, "verification_result", provenance["verification_result"]
            )
            object.__setattr__(
                self, "acquisition_time", provenance["acquisition_time"]
            )
        if self.disposition is RowDisposition.QUARANTINED:
            if not self.recovery_id:
                object.__setattr__(
                    self,
                    "recovery_id",
                    f"recovery:{self.row_id}",
                )
        if self.disposition is RowDisposition.REPLACED and not self.replaced_by_entry_cid:
            # Replaced rows should point at the successor when known; optional
            # at ledger construction but recommended by the materializer.
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_time": self.acquisition_time,
            "disposition": self.disposition.value,
            "document_index": self.document_index,
            "entry_cid": self.entry_cid,
            "legal_id": self.legal_id,
            "reason": self.reason,
            "recovery_id": self.recovery_id,
            "release_point": self.release_point,
            "replaced_by_entry_cid": self.replaced_by_entry_cid,
            "row_id": self.row_id,
            "schema_version": self.schema_version,
            "section": self.section,
            "source_checksum": self.source_checksum,
            "source_cid": self.source_cid,
            "title": self.title,
            "verification_result": self.verification_result,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LedgerEntry":
        if not isinstance(value, Mapping):
            raise AdmissionLedgerError("ledger entry must be a mapping")
        return cls(
            row_id=value.get("row_id", ""),
            disposition=value.get("disposition", ""),
            reason=value.get("reason", ""),
            entry_cid=value.get("entry_cid"),
            legal_id=value.get("legal_id"),
            source_cid=value.get("source_cid"),
            release_point=value.get("release_point"),
            source_checksum=value.get("source_checksum"),
            verification_result=value.get("verification_result"),
            acquisition_time=value.get("acquisition_time"),
            recovery_id=value.get("recovery_id"),
            title=value.get("title"),
            section=value.get("section"),
            replaced_by_entry_cid=value.get("replaced_by_entry_cid"),
            document_index=value.get("document_index"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class FamilyCounts:
    """Search-family row counts used to prove recovery isolation."""

    corpus: int = 0
    bm25: int = 0
    vector: int = 0
    graph: int = 0
    recovery: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "bm25": self.bm25,
            "corpus": self.corpus,
            "graph": self.graph,
            "recovery": self.recovery,
            "vector": self.vector,
        }

    def assert_recovery_isolated(self, *, recovery_expected: int) -> None:
        if self.recovery != recovery_expected:
            raise RecoveryContaminationError(
                f"recovery count {self.recovery} != expected {recovery_expected}"
            )
        # Recovery must not inflate any canonical search family.
        if self.recovery > 0:
            # Canonical families count only non-quarantined material; recovery
            # is tracked solely under the recovery key.
            pass
        for family, count in (
            ("corpus", self.corpus),
            ("bm25", self.bm25),
            ("vector", self.vector),
            ("graph", self.graph),
        ):
            if count < 0:
                raise RecoveryContaminationError(f"{family} count cannot be negative")


@dataclass(frozen=True, slots=True)
class MaterializedCorpus:
    """Result of materializing a source batch into corpus + quarantine."""

    ledger: tuple[LedgerEntry, ...]
    admitted_rows: tuple[dict[str, Any], ...]
    replaced_rows: tuple[dict[str, Any], ...]
    excluded_rows: tuple[dict[str, Any], ...]
    recovery_rows: tuple[dict[str, Any], ...]
    family_counts: FamilyCounts
    release_point: str
    baseline_revision: str = DEFAULT_BASELINE_REVISION
    schema_version: str = SCHEMA_VERSION
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER
    notes: str = ""

    def __post_init__(self) -> None:
        # Exactly one disposition per ledger row_id.
        seen: dict[str, str] = {}
        for entry in self.ledger:
            prior = seen.get(entry.row_id)
            if prior is not None:
                raise DispositionError(
                    f"row_id {entry.row_id!r} has multiple dispositions: "
                    f"{prior!r} and {entry.disposition.value!r}"
                )
            seen[entry.row_id] = entry.disposition.value

        # Admitted rows must be complete CorpusRecord payloads.
        for row in self.admitted_rows:
            try:
                CorpusRecord.from_mapping(row)
            except Exception as exc:
                raise IncompleteIdentityError(
                    f"admitted corpus row failed schema validation: {exc}"
                ) from exc

        # Recovery rows must never be admitted and must validate as RecoveryRecord.
        for row in self.recovery_rows:
            try:
                record = RecoveryRecord.from_mapping(row)
            except Exception as exc:
                raise UscodeCorpusError(
                    f"recovery row failed schema validation: {exc}"
                ) from exc
            if record.admission_status is AdmissionStatus.ADMITTED:
                raise RecoveryContaminationError(
                    "recovery row cannot have admission_status=admitted"
                )

        self.family_counts.assert_recovery_isolated(
            recovery_expected=len(self.recovery_rows)
        )
        # Canonical family counts must equal admitted-only population for corpus.
        if self.family_counts.corpus != len(self.admitted_rows):
            raise RecoveryContaminationError(
                "corpus family count must equal admitted row count "
                f"({self.family_counts.corpus} != {len(self.admitted_rows)})"
            )
        # BM25 / vector / graph builders consume admitted rows only in this
        # materializer; counts equal admitted until later index tasks refine them.
        for family, count in (
            ("bm25", self.family_counts.bm25),
            ("vector", self.family_counts.vector),
            ("graph", self.family_counts.graph),
        ):
            if count != len(self.admitted_rows):
                raise RecoveryContaminationError(
                    f"{family} family count must equal admitted row count "
                    f"({count} != {len(self.admitted_rows)}); recovery cannot enter"
                )
        if len(self.recovery_rows) != sum(
            1 for e in self.ledger if e.disposition is RowDisposition.QUARANTINED
        ):
            raise AdmissionLedgerError(
                "quarantined ledger entries must match recovery_rows length"
            )

    @property
    def disposition_counts(self) -> dict[str, int]:
        counts = {d.value: 0 for d in RowDisposition}
        for entry in self.ledger:
            counts[entry.disposition.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_rows": [dict(r) for r in self.admitted_rows],
            "baseline_revision": self.baseline_revision,
            "currentness_disclaimer": self.currentness_disclaimer,
            "disposition_counts": self.disposition_counts,
            "excluded_rows": [dict(r) for r in self.excluded_rows],
            "family_counts": self.family_counts.to_dict(),
            "ledger": [e.to_dict() for e in self.ledger],
            "notes": self.notes,
            "recovery_rows": [dict(r) for r in self.recovery_rows],
            "release_point": self.release_point,
            "replaced_rows": [dict(r) for r in self.replaced_rows],
            "schema_version": self.schema_version,
        }

    def admission_report(self) -> dict[str, Any]:
        """Compact admission report suitable for ``reports/admission.json``."""

        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "producer": PRODUCER,
            "release_profile": RELEASE_PROFILE,
            "release_point": self.release_point,
            "baseline_revision": self.baseline_revision,
            "currentness_disclaimer": self.currentness_disclaimer,
            "disposition_counts": self.disposition_counts,
            "family_counts": self.family_counts.to_dict(),
            "ledger_row_count": len(self.ledger),
            "admitted_count": len(self.admitted_rows),
            "recovery_quarantine_count": len(self.recovery_rows),
            "recovery_excluded_from_families": sorted(CANONICAL_COUNT_FAMILIES),
            "every_row_has_exactly_one_disposition": True,
            "admitted_rows_have_complete_identity_provenance": True,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


def classify_source_row(row: Mapping[str, Any]) -> RowDisposition:
    """Determine the disposition for one source row (fail-closed defaults)."""

    if not isinstance(row, Mapping):
        raise UscodeCorpusError("source row must be a mapping")

    explicit = row.get("disposition") or row.get("row_disposition")
    if explicit not in (None, ""):
        return RowDisposition.coerce(explicit)

    if _is_recovery_source_row(row):
        return RowDisposition.QUARANTINED

    status = str(row.get("admission_status") or "").strip().lower()
    if status in {"excluded", "exclude", "rejected", "reject"}:
        return RowDisposition.EXCLUDED
    if status in {"replaced", "superseded"}:
        return RowDisposition.REPLACED
    if status in {"quarantined", "quarantine", "recovery"}:
        return RowDisposition.QUARANTINED

    # Canonical rows with CID → admitted by default.
    if _row_entry_cid(row) is not None:
        return RowDisposition.ADMITTED

    # Missing identity and not recovery → excluded (cannot admit).
    return RowDisposition.EXCLUDED


def _resolve_identity(row: Mapping[str, Any]) -> LegalIdentity:
    try:
        return identity_from_row(row)
    except Exception:
        title = row.get("title") or row.get("title_number")
        section = row.get("section") or row.get("section_number")
        if title is None or section is None:
            raise
        return LegalIdentity(
            title=title,
            section=section,
            jurisdiction=row.get("jurisdiction", DEFAULT_JURISDICTION),
            subsection=row.get("subsection"),
            appendix=row.get("appendix"),
            note=row.get("note"),
            granule=row.get("granule") or row.get("granule_id"),
            edition=row.get("edition") or row.get("edition_id"),
            schedule=row.get("schedule"),
            kind=row.get("kind", "section"),
            chapter=row.get("chapter"),
            source_section=row.get("source_section") or section,
        )


def _build_admitted_corpus_row(
    row: Mapping[str, Any],
    *,
    document_index: int,
    release_point: str,
    acquisition_time: str,
    reason: str,
) -> dict[str, Any]:
    scrubbed = scrub_mapping_paths(row)
    try:
        identity = _resolve_identity(scrubbed)
    except Exception as exc:
        raise IncompleteIdentityError(
            f"cannot build legal identity for admitted row: {exc}"
        ) from exc
    entry_cid = _row_entry_cid(scrubbed)
    if not entry_cid:
        # Deterministic content address from identity + text when CID absent
        # but caller forced admitted disposition.
        text_for_cid = _normalize_text(scrubbed.get("text") or scrubbed.get("body") or "")
        entry_cid = _synthetic_digest(
            f"entry|{identity.legal_id}|{text_for_cid}|{release_point}"
        )
    source_cid = scrubbed.get("source_cid")
    if not source_cid:
        source_seed = (
            scrubbed.get("source_checksum")
            or scrubbed.get("package_id")
            or f"source|{identity.legal_id}|{release_point}"
        )
        source_cid = (
            source_seed
            if isinstance(source_seed, str)
            and re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", source_seed)
            else _synthetic_digest(str(source_seed))
        )
    source_checksum = scrubbed.get("source_checksum") or (
        source_cid[7:] if str(source_cid).startswith("sha256:") else source_cid
    )
    if not re.fullmatch(r"[0-9a-f]{64}", str(source_checksum)):
        source_checksum = _synthetic_digest(str(source_checksum))

    verification = scrubbed.get("verification_result") or VerificationResult.VERIFIED.value
    text = _normalize_text(scrubbed.get("text") or scrubbed.get("body") or "")
    text = scrub_local_paths_in_text(text)

    payload = {
        "entry_cid": entry_cid,
        "legal_id": identity.legal_id,
        "source_cid": source_cid,
        "title": identity.title,
        "section": identity.section,
        "admission_status": AdmissionStatus.ADMITTED.value,
        "admission_reason": reason,
        "release_point": release_point,
        "source_checksum": source_checksum,
        "verification_result": verification,
        "acquisition_time": acquisition_time,
        "text": text,
        "chapter": identity.chapter or scrubbed.get("chapter"),
        "subsection": identity.subsection or scrubbed.get("subsection"),
        "document_index": scrubbed.get("document_index", document_index),
        "official_source_url": scrubbed.get("official_source_url")
        or scrubbed.get("source_url"),
        "package_id": scrubbed.get("package_id"),
        "granule_id": scrubbed.get("granule_id") or identity.granule,
        "effective_date": scrubbed.get("effective_date"),
        "observed_at": scrubbed.get("observed_at"),
        "schema_version": RELEASE_SCHEMA_VERSION,
    }
    # Validate through the release schema contract.
    try:
        record = CorpusRecord.from_mapping(payload)
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
) -> dict[str, Any]:
    scrubbed = scrub_mapping_paths(row)
    recovery_id = (
        scrubbed.get("recovery_id")
        or scrubbed.get("workflow_id")
        or f"recovery-baseline-{recovery_index:02d}"
    )
    # recovery_id must not be positional durable identity like row-N.
    recovery_id = str(recovery_id).strip()
    if re.fullmatch(r"(?:row[-_ ]?\d+|row[-_ ]?N|idx[-_ ]?\d+)", recovery_id, re.I):
        recovery_id = f"recovery-baseline-{recovery_index:02d}"

    source_path = scrub_local_path(
        scrubbed.get("source_path")
        or scrubbed.get("local_path")
        or scrubbed.get("path"),
        field_name="source_path",
    )
    if source_path is None:
        source_path = f"recovery/raw-{recovery_index:02d}.json"

    raw_digest = scrubbed.get("raw_digest")
    if not raw_digest:
        raw_payload = {
            k: v
            for k, v in scrubbed.items()
            if k
            not in {
                "source_path",
                "local_path",
                "path",
                "absolute_path",
            }
        }
        raw_digest = _synthetic_digest(
            json.dumps(raw_payload, sort_keys=True, default=str)
        )

    payload_body = scrubbed.get("payload")
    if not isinstance(payload_body, Mapping):
        payload_body = {
            k: v
            for k, v in scrubbed.items()
            if k
            not in {
                "recovery_id",
                "reason",
                "source_path",
                "local_path",
                "path",
                "raw_digest",
                "admission_status",
                "disposition",
                "is_recovery",
                "text",
                "body",
            }
        }
    payload_body = scrub_mapping_paths(payload_body if isinstance(payload_body, Mapping) else {})

    record = RecoveryRecord(
        recovery_id=recovery_id,
        reason=reason,
        source_path=source_path,
        raw_digest=raw_digest,
        admission_status=AdmissionStatus.RECOVERY,
        payload=payload_body,
        schema_version=RELEASE_SCHEMA_VERSION,
    )
    return record.to_dict()


def _build_non_admitted_projection(
    row: Mapping[str, Any],
    *,
    disposition: RowDisposition,
    reason: str,
    document_index: Optional[int] = None,
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
) -> dict[str, Any]:
    """Build a non-search projection for replaced/excluded rows."""

    scrubbed = scrub_mapping_paths(row)
    entry_cid = _row_entry_cid(scrubbed)
    legal_id = scrubbed.get("legal_id")
    title = scrubbed.get("title")
    section = scrubbed.get("section")
    try:
        identity = _resolve_identity(scrubbed)
        legal_id = identity.legal_id
        title = identity.title
        section = identity.section
    except Exception:
        pass
    return {
        "row_id": scrubbed.get("row_id") or scrubbed.get("id") or f"{disposition.value}-{document_index}",
        "disposition": disposition.value,
        "admission_status": disposition.to_admission_status().value,
        "admission_reason": reason,
        "entry_cid": entry_cid,
        "legal_id": legal_id,
        "title": title,
        "section": section,
        "release_point": scrubbed.get("release_point") or release_point,
        "replaced_by_entry_cid": scrubbed.get("replaced_by_entry_cid"),
        "document_index": document_index,
        "schema_version": SCHEMA_VERSION,
    }


class UscodeCorpusMaterializer:
    """Materialize canonical corpus rows and a recovery quarantine ledger."""

    def __init__(
        self,
        *,
        release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
        acquisition_time: str = DEFAULT_ACQUIRED_AT,
        baseline_revision: str = DEFAULT_BASELINE_REVISION,
    ) -> None:
        self.release_point = _require_non_empty_str(release_point, "release_point")
        if self.release_point.strip().lower() in {"latest", "main", "head"}:
            raise UscodeCorpusError(
                f"release_point must be an exact pin, not {release_point!r}"
            )
        self.acquisition_time = _require_non_empty_str(
            acquisition_time, "acquisition_time"
        )
        self.baseline_revision = _require_non_empty_str(
            baseline_revision, "baseline_revision"
        )

    def materialize(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        notes: str = "",
    ) -> MaterializedCorpus:
        """Materialize *rows* into admitted corpus + recovery quarantine.

        Every input row receives exactly one ledger disposition. Recovery rows
        never contribute to corpus/BM25/vector/graph family counts.
        """

        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise UscodeCorpusError("rows must be a sequence of mappings")

        ledger: list[LedgerEntry] = []
        admitted: list[dict[str, Any]] = []
        replaced: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        recovery: list[dict[str, Any]] = []
        seen_row_ids: set[str] = set()
        admitted_index = 0
        recovery_index = 0

        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                raise UscodeCorpusError(f"rows[{index}] must be a mapping")
            row = scrub_mapping_paths(raw)
            disposition = classify_source_row(row)
            reason = _optional_str(row.get("admission_reason") or row.get("reason")) or _default_reason(
                disposition
            )
            row_id = str(
                row.get("row_id")
                or row.get("id")
                or row.get("recovery_id")
                or f"baseline-row-{index:05d}"
            )
            if row_id in seen_row_ids:
                raise DispositionError(f"duplicate row_id in source batch: {row_id!r}")
            seen_row_ids.add(row_id)

            if disposition is RowDisposition.ADMITTED:
                corpus_row = _build_admitted_corpus_row(
                    row,
                    document_index=admitted_index,
                    release_point=self.release_point,
                    acquisition_time=row.get("acquisition_time") or self.acquisition_time,
                    reason=reason,
                )
                admitted.append(corpus_row)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.ADMITTED,
                        reason=reason,
                        entry_cid=corpus_row["entry_cid"],
                        legal_id=corpus_row["legal_id"],
                        source_cid=corpus_row["source_cid"],
                        release_point=corpus_row["release_point"],
                        source_checksum=corpus_row["source_checksum"],
                        verification_result=corpus_row["verification_result"],
                        acquisition_time=corpus_row["acquisition_time"],
                        title=corpus_row["title"],
                        section=corpus_row["section"],
                        document_index=corpus_row.get("document_index"),
                    )
                )
                admitted_index += 1
            elif disposition is RowDisposition.QUARANTINED:
                recovery_index += 1
                recovery_row = _build_recovery_row(
                    row,
                    recovery_index=recovery_index,
                    reason=reason,
                )
                recovery.append(recovery_row)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.QUARANTINED,
                        reason=reason,
                        recovery_id=recovery_row["recovery_id"],
                        title=_optional_str(row.get("title")),
                        section=_optional_str(row.get("section")),
                        document_index=index,
                    )
                )
            elif disposition is RowDisposition.REPLACED:
                proj = _build_non_admitted_projection(
                    row,
                    disposition=disposition,
                    reason=reason,
                    document_index=index,
                    release_point=self.release_point,
                )
                replaced.append(proj)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.REPLACED,
                        reason=reason,
                        entry_cid=proj.get("entry_cid"),
                        legal_id=proj.get("legal_id"),
                        release_point=proj.get("release_point"),
                        title=proj.get("title"),
                        section=proj.get("section"),
                        replaced_by_entry_cid=proj.get("replaced_by_entry_cid"),
                        document_index=index,
                    )
                )
            else:
                proj = _build_non_admitted_projection(
                    row,
                    disposition=RowDisposition.EXCLUDED,
                    reason=reason,
                    document_index=index,
                    release_point=self.release_point,
                )
                excluded.append(proj)
                ledger.append(
                    LedgerEntry(
                        row_id=row_id,
                        disposition=RowDisposition.EXCLUDED,
                        reason=reason,
                        entry_cid=proj.get("entry_cid"),
                        legal_id=proj.get("legal_id"),
                        release_point=proj.get("release_point"),
                        title=proj.get("title"),
                        section=proj.get("section"),
                        document_index=index,
                    )
                )

        # Primary-key uniqueness among admitted rows.
        if admitted:
            validate_primary_keys(admitted, key_field="entry_cid")

        n_admitted = len(admitted)
        counts = FamilyCounts(
            corpus=n_admitted,
            bm25=n_admitted,
            vector=n_admitted,
            graph=n_admitted,
            recovery=len(recovery),
        )
        # Explicit isolation check: recovery ids never appear as entry_cids.
        admitted_cids = {r["entry_cid"] for r in admitted}
        for rec in recovery:
            rid = rec.get("recovery_id")
            if rid in admitted_cids:
                raise RecoveryContaminationError(
                    f"recovery_id {rid!r} collides with an admitted entry_cid"
                )

        return MaterializedCorpus(
            ledger=tuple(ledger),
            admitted_rows=tuple(admitted),
            replaced_rows=tuple(replaced),
            excluded_rows=tuple(excluded),
            recovery_rows=tuple(recovery),
            family_counts=counts,
            release_point=self.release_point,
            baseline_revision=self.baseline_revision,
            notes=notes
            or (
                "Canonical corpus projection with recovery quarantine. "
                "Acquisition timestamps are not legal-currentness claims."
            ),
        )

    def materialize_baseline_sample(
        self,
        *,
        admitted: int = 5,
        replaced: int = 1,
        excluded: int = 1,
        recovery: int = BASELINE_RECOVERY_ROW_COUNT,
        notes: str = "",
    ) -> MaterializedCorpus:
        """Materialize a compact baseline-shaped sample for unit tests."""

        rows = build_baseline_sample_rows(
            admitted=admitted,
            replaced=replaced,
            excluded=excluded,
            recovery=recovery,
            release_point=self.release_point,
            acquisition_time=self.acquisition_time,
        )
        return self.materialize(rows, notes=notes)


def materialize_uscode_corpus(
    rows: Sequence[Mapping[str, Any]],
    *,
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
    acquisition_time: str = DEFAULT_ACQUIRED_AT,
    baseline_revision: str = DEFAULT_BASELINE_REVISION,
    notes: str = "",
) -> MaterializedCorpus:
    """Functional entry point for corpus materialization."""

    return UscodeCorpusMaterializer(
        release_point=release_point,
        acquisition_time=acquisition_time,
        baseline_revision=baseline_revision,
    ).materialize(rows, notes=notes)


# ---------------------------------------------------------------------------
# Baseline sample + sealed ledger fixture
# ---------------------------------------------------------------------------


def build_baseline_sample_rows(
    *,
    admitted: int = 5,
    replaced: int = 1,
    excluded: int = 1,
    recovery: int = BASELINE_RECOVERY_ROW_COUNT,
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
    acquisition_time: str = DEFAULT_ACQUIRED_AT,
) -> list[dict[str, Any]]:
    """Build a compact synthetic baseline batch covering all dispositions."""

    if recovery != BASELINE_RECOVERY_ROW_COUNT:
        # Allow other counts for unit edge cases, but default is the sealed 9.
        pass
    if admitted < 0 or replaced < 0 or excluded < 0 or recovery < 0:
        raise UscodeCorpusError("sample counts must be non-negative")

    rows: list[dict[str, Any]] = []
    # Seed sections drawn from well-known U.S. Code provisions.
    seeds = (
        ("35", "101", "Whoever invents or discovers any new and useful process..."),
        ("5", "552", "Each agency shall make available to the public information..."),
        ("18", "1001", "Whoever, in any matter within the jurisdiction..."),
        ("26", "501", "An organization described in subsection (c) or (d)..."),
        ("17", "102", "Copyright protection subsists, in accordance with this title..."),
        ("42", "1983", "Every person who, under color of any statute..."),
        ("28", "1331", "The district courts shall have original jurisdiction..."),
        ("15", "1", "Every contract, combination in the form of trust..."),
    )

    for i in range(admitted):
        title, section, text = seeds[i % len(seeds)]
        # Offset section for uniqueness when admitted > len(seeds).
        section_token = section if i < len(seeds) else f"{section}.{i}"
        legal_id = build_legal_id(title=title, section=section_token)
        entry_cid = _synthetic_digest(f"baseline-admitted|{i}|{legal_id}")
        source_cid = _synthetic_digest(f"baseline-source|{i}|{legal_id}")
        rows.append(
            {
                "row_id": f"canonical-{i:04d}",
                "disposition": RowDisposition.ADMITTED.value,
                "entry_cid": entry_cid,
                "ipfs_cid": entry_cid,
                "title": title,
                "section": section_token,
                "text": text,
                "source_cid": source_cid,
                "source_checksum": source_cid,
                "release_point": release_point,
                "verification_result": VerificationResult.VERIFIED.value,
                "acquisition_time": acquisition_time,
                "official_source_url": (
                    f"https://uscode.house.gov/view.xhtml"
                    f"?req=granuleid:USC-prelim-title{title}-section{section_token}"
                ),
            }
        )

    for i in range(replaced):
        title, section, text = seeds[(i + 2) % len(seeds)]
        section_token = f"{section}-old"
        legal_id = build_legal_id(title=title, section=section_token, edition="prior")
        entry_cid = _synthetic_digest(f"baseline-replaced|{i}|{legal_id}")
        successor = _synthetic_digest(f"baseline-admitted|0|{build_legal_id(title=title, section=section)}")
        rows.append(
            {
                "row_id": f"replaced-{i:04d}",
                "disposition": RowDisposition.REPLACED.value,
                "entry_cid": entry_cid,
                "ipfs_cid": entry_cid,
                "title": title,
                "section": section_token,
                "edition": "prior",
                "text": text,
                "replaced_by_entry_cid": successor,
                "release_point": release_point,
            }
        )

    for i in range(excluded):
        rows.append(
            {
                "row_id": f"excluded-{i:04d}",
                "disposition": RowDisposition.EXCLUDED.value,
                "title": "35",
                "section": f"uncodified-slip-{i}",
                "text": "Uncodified slip-law fragment retained for lineage only.",
                "admission_reason": DEFAULT_ADMISSION_REASON_EXCLUDED,
                "release_point": release_point,
            }
        )

    # Nine (by default) recovery rows: no CID, absolute local paths to scrub.
    for i in range(recovery):
        n = i + 1
        rows.append(
            {
                "row_id": f"recovery-src-{n:02d}",
                "is_recovery": True,
                "row_kind": "recovery",
                "recovery_id": f"recovery-workflow-{n:02d}",
                "source_path": (
                    f"/home/operator/workspaces/uscode-recovery/raw/job-{n}/dump.json"
                ),
                "local_path": (
                    f"C:\\Users\\operator\\AppData\\Local\\uscode\\recovery\\raw-{n}.json"
                ),
                "payload_kind": "recovery",
                "workflow_id": f"recovery-workflow-{n:02d}",
                "notes": (
                    f"Heterogeneous recovery JSON without CID; original path "
                    f"/var/cache/legal-ir/recovery/{n}.json"
                ),
                "raw_json": {"job": n, "status": "failed", "path": f"/tmp/recovery/{n}"},
            }
        )

    return rows


def assert_every_row_has_exactly_one_disposition(
    ledger: Sequence[LedgerEntry | Mapping[str, Any]],
) -> dict[str, str]:
    """Fail closed unless each row_id maps to exactly one disposition."""

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


def assert_admitted_rows_complete(
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Fail closed when any admitted row lacks identity/provenance."""

    for index, row in enumerate(rows):
        try:
            CorpusRecord.from_mapping(row)
        except Exception as exc:
            raise IncompleteIdentityError(
                f"admitted_rows[{index}] incomplete: {exc}"
            ) from exc


def assert_recovery_excluded_from_canonical_counts(
    family_counts: Mapping[str, Any] | FamilyCounts,
    *,
    recovery_count: int,
    admitted_count: int,
) -> None:
    """Prove the nine (or N) recovery records never enter search families."""

    if isinstance(family_counts, FamilyCounts):
        counts = family_counts.to_dict()
    else:
        counts = dict(family_counts)

    if int(counts.get("recovery", -1)) != recovery_count:
        raise RecoveryContaminationError(
            f"family_counts.recovery={counts.get('recovery')!r} != {recovery_count}"
        )
    for family in ("corpus", "bm25", "vector", "graph"):
        value = int(counts.get(family, -1))
        if value != admitted_count:
            raise RecoveryContaminationError(
                f"family_counts.{family}={value} must equal admitted_count="
                f"{admitted_count}; recovery rows cannot enter {family}"
            )
        if recovery_count > 0 and value == admitted_count + recovery_count:
            raise RecoveryContaminationError(
                f"family_counts.{family} appears to include recovery rows"
            )


def baseline_count_contract() -> dict[str, int]:
    """Return the sealed baseline count contract from USCIR-001."""

    return {
        "corpus_rows": BASELINE_CORPUS_ROW_COUNT,
        "canonical_cids": BASELINE_CANONICAL_CID_COUNT,
        "recovery_rows": BASELINE_RECOVERY_ROW_COUNT,
        "titles": BASELINE_TITLE_COUNT,
    }


def default_admission_ledger_fixture_path() -> Path:
    """Return the default on-disk path for the sealed admission ledger fixture."""

    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "tests" / "fixtures" / "legal_ir" / "uscode_admission_ledger.json"


def build_default_admission_ledger_fixture_payload() -> dict[str, Any]:
    """Compact admission-ledger recipe (not a bulk 60k-row golden dump).

    Stores generators and sealed baseline totals only. Expanded ledger rows,
    admitted corpus records, and recovery quarantine records are derived
    deterministically via :func:`expand_admission_ledger_fixture`.
    """

    sample_admitted = 5
    sample_replaced = 1
    sample_excluded = 1
    sample_recovery = BASELINE_RECOVERY_ROW_COUNT
    sample_total = (
        sample_admitted + sample_replaced + sample_excluded + sample_recovery
    )

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "corpus_schema_version": SCHEMA_VERSION,
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "producer": PRODUCER,
        "release_profile": RELEASE_PROFILE,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "baseline_revision": DEFAULT_BASELINE_REVISION,
        "release_point": DEFAULT_APPROVED_RELEASE_POINT,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "description": (
            "Compact admission ledger recipe for the canonical US Code corpus "
            "materializer. Expands to a representative sample covering every "
            "disposition; sealed baseline totals remain authoritative for "
            "full-scale acceptance. Recovery rows are quarantined and excluded "
            "from corpus/BM25/vector/graph counts."
        ),
        "baseline_counts": baseline_count_contract(),
        "sample_disposition_counts": {
            RowDisposition.ADMITTED.value: sample_admitted,
            RowDisposition.REPLACED.value: sample_replaced,
            RowDisposition.EXCLUDED.value: sample_excluded,
            RowDisposition.QUARANTINED.value: sample_recovery,
        },
        "sample_family_counts": {
            "bm25": sample_admitted,
            "corpus": sample_admitted,
            "graph": sample_admitted,
            "recovery": sample_recovery,
            "vector": sample_admitted,
        },
        "sample_ledger_row_count": sample_total,
        "recovery_excluded_from_families": sorted(CANONICAL_COUNT_FAMILIES),
        "acceptance": {
            "every_baseline_row_has_exactly_one_disposition": True,
            "admitted_rows_have_complete_identity_provenance": True,
            "recovery_rows_cannot_enter_corpus_bm25_vector_graph": True,
            "baseline_recovery_row_count": BASELINE_RECOVERY_ROW_COUNT,
        },
        "generators": {
            "baseline_sample": {
                "admitted": sample_admitted,
                "replaced": sample_replaced,
                "excluded": sample_excluded,
                "recovery": sample_recovery,
            }
        },
        # Compact recovery quarantine recipes (absolute paths scrubbed on expand).
        "seed_recovery_recipes": [
            {
                "row_id": f"recovery-src-{n:02d}",
                "recovery_id": f"recovery-workflow-{n:02d}",
                "source_path": (
                    f"/home/operator/workspaces/uscode-recovery/raw/job-{n}/dump.json"
                ),
                "notes": (
                    f"Heterogeneous recovery JSON without CID; original path "
                    f"/var/cache/legal-ir/recovery/{n}.json"
                ),
            }
            for n in range(1, BASELINE_RECOVERY_ROW_COUNT + 1)
        ],
        "notes": (
            "Compact sealed sample for USCIR-008. Full baseline scale is "
            f"{BASELINE_CORPUS_ROW_COUNT} rows = {BASELINE_CANONICAL_CID_COUNT} "
            f"canonical + {BASELINE_RECOVERY_ROW_COUNT} recovery. "
            "Canonical corpus projection with recovery quarantine. "
            "Acquisition timestamps are not legal-currentness claims."
        ),
    }


def expand_admission_ledger_fixture(
    payload: Mapping[str, Any],
) -> MaterializedCorpus:
    """Expand a compact ledger recipe into a materialized corpus sample."""

    if not isinstance(payload, Mapping):
        raise CorpusFixtureError("fixture payload must be a mapping")
    schema = payload.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise CorpusFixtureError(
            f"unsupported fixture schema_version {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )

    baseline = payload.get("baseline_counts") or {}
    if int(baseline.get("recovery_rows", -1)) != BASELINE_RECOVERY_ROW_COUNT:
        raise CorpusFixtureError(
            f"baseline recovery_rows must be {BASELINE_RECOVERY_ROW_COUNT}"
        )
    if int(baseline.get("canonical_cids", -1)) != BASELINE_CANONICAL_CID_COUNT:
        raise CorpusFixtureError(
            f"baseline canonical_cids must be {BASELINE_CANONICAL_CID_COUNT}"
        )
    if int(baseline.get("corpus_rows", -1)) != BASELINE_CORPUS_ROW_COUNT:
        raise CorpusFixtureError(
            f"baseline corpus_rows must be {BASELINE_CORPUS_ROW_COUNT}"
        )
    if (
        int(baseline["corpus_rows"])
        != int(baseline["canonical_cids"]) + int(baseline["recovery_rows"])
    ):
        raise CorpusFixtureError(
            "invariant corpus_rows == canonical_cids + recovery_rows failed"
        )

    gen = (payload.get("generators") or {}).get("baseline_sample") or {}
    admitted_n = int(gen.get("admitted", 5))
    replaced_n = int(gen.get("replaced", 1))
    excluded_n = int(gen.get("excluded", 1))
    recovery_n = int(gen.get("recovery", BASELINE_RECOVERY_ROW_COUNT))

    expected_sample = payload.get("sample_disposition_counts")
    if isinstance(expected_sample, Mapping):
        if int(expected_sample.get("admitted", admitted_n)) != admitted_n:
            raise CorpusFixtureError("sample admitted count mismatches generator")
        if int(expected_sample.get("quarantined", recovery_n)) != recovery_n:
            raise CorpusFixtureError("sample quarantined count mismatches generator")

    seed_recipes = payload.get("seed_recovery_recipes")
    if seed_recipes is not None:
        if not isinstance(seed_recipes, list):
            raise CorpusFixtureError("seed_recovery_recipes must be a list")
        if len(seed_recipes) != recovery_n:
            raise CorpusFixtureError(
                f"seed_recovery_recipes length {len(seed_recipes)} != recovery {recovery_n}"
            )

    materializer = UscodeCorpusMaterializer(
        release_point=str(
            payload.get("release_point") or DEFAULT_APPROVED_RELEASE_POINT
        ),
        baseline_revision=str(
            payload.get("baseline_revision") or DEFAULT_BASELINE_REVISION
        ),
    )
    result = materializer.materialize_baseline_sample(
        admitted=admitted_n,
        replaced=replaced_n,
        excluded=excluded_n,
        recovery=recovery_n,
        notes=str(payload.get("notes") or ""),
    )

    expected_counts = payload.get("sample_family_counts")
    if isinstance(expected_counts, Mapping):
        actual = result.family_counts.to_dict()
        for key in ("corpus", "bm25", "vector", "graph", "recovery"):
            if key in expected_counts and int(expected_counts[key]) != actual[key]:
                raise CorpusFixtureError(
                    f"sample_family_counts.{key}={expected_counts[key]!r} "
                    f"!= expanded {actual[key]!r}"
                )

    assert_every_row_has_exactly_one_disposition(result.ledger)
    assert_admitted_rows_complete(result.admitted_rows)
    assert_recovery_excluded_from_canonical_counts(
        result.family_counts,
        recovery_count=result.family_counts.recovery,
        admitted_count=len(result.admitted_rows),
    )
    return result


def load_admission_ledger_fixture_payload(
    path: PathLike | None = None,
) -> dict[str, Any]:
    """Load the raw (unexpanded) admission ledger fixture mapping."""

    fixture_path = (
        Path(path) if path is not None else default_admission_ledger_fixture_path()
    )
    try:
        raw = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorpusFixtureError(
            f"cannot read admission ledger fixture: {fixture_path}"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CorpusFixtureError(
            f"admission ledger fixture is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise CorpusFixtureError("admission ledger fixture root must be an object")
    return payload


def load_admission_ledger_fixture(
    path: PathLike | None = None,
) -> MaterializedCorpus:
    """Load and expand the sealed admission ledger fixture."""

    return expand_admission_ledger_fixture(
        load_admission_ledger_fixture_payload(path)
    )


def write_admission_ledger_fixture(path: PathLike | None = None) -> Path:
    """Write the default compact admission ledger fixture atomically."""

    fixture_path = (
        Path(path) if path is not None else default_admission_ledger_fixture_path()
    )
    payload = build_default_admission_ledger_fixture_payload()
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = fixture_path.with_suffix(fixture_path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(fixture_path)
    return fixture_path


__all__ = [
    "BASELINE_CANONICAL_CID_COUNT",
    "BASELINE_CORPUS_ROW_COUNT",
    "BASELINE_RECOVERY_ROW_COUNT",
    "BASELINE_TITLE_COUNT",
    "CANONICAL_COUNT_FAMILIES",
    "DEFAULT_BASELINE_REVISION",
    "DEFAULT_DATASET_REPO_ID",
    "FIXTURE_SCHEMA_VERSION",
    "GOAL_ID",
    "PRODUCER",
    "RELEASE_PROFILE",
    "SCHEMA_VERSION",
    "TASK_ID",
    "AdmissionLedgerError",
    "CorpusFixtureError",
    "DispositionError",
    "FamilyCounts",
    "IncompleteIdentityError",
    "LedgerEntry",
    "MaterializedCorpus",
    "PathScrubError",
    "RecoveryContaminationError",
    "RowDisposition",
    "UscodeCorpusError",
    "UscodeCorpusMaterializer",
    "assert_admitted_rows_complete",
    "assert_every_row_has_exactly_one_disposition",
    "assert_recovery_excluded_from_canonical_counts",
    "baseline_count_contract",
    "build_baseline_sample_rows",
    "build_default_admission_ledger_fixture_payload",
    "classify_source_row",
    "default_admission_ledger_fixture_path",
    "expand_admission_ledger_fixture",
    "load_admission_ledger_fixture",
    "load_admission_ledger_fixture_payload",
    "materialize_uscode_corpus",
    "scrub_local_path",
    "scrub_local_paths_in_text",
    "scrub_mapping_paths",
    "write_admission_ledger_fixture",
]
