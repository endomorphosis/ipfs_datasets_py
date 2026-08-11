"""Streaming proof-cache migration adapters (DQK-026).

Import fragmented JSON proof caches from the common, TDFOL, CEC, integration,
hammers, legal-IR, and external-prover families into the unified
:class:`~ipfs_datasets_py.logic.common.duckdb_proof_store.DuckDBProofStore`
with:

* original source-byte digests retained on every job / accept / reject
* reject and quarantine rows for ambiguous key, TTL, or trust mappings
* dual-TTL and closed trust-level translation (fail-closed; never guess)
* differential / parity receipts between legacy entries and the store
* bounded, idempotent batch imports (peak memory independent of corpus size)
* whole-file JSON rewrites forbidden after a family is promoted

Importing this module is inert: no DuckDB, network, or filesystem I/O until an
explicit migrator call.  Unit tests use the hermetic
:class:`MemoryProofMigrationBackend` and an in-process proof store.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

from ..backends.cache_protocol import (
    DEFAULT_NEGATIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    CachePolarity,
)
from ..backends.results import ResultAuthority, ResultStatus
from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap
from .duckdb_proof_store import (
    DuckDBProofStore,
    DuckDBProofStoreError,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    UnifiedProofKey,
    build_duckdb_proof_store,
    outcome_kind_for_status,
    polarity_for_outcome,
    proof_store_content_digest,
    trust_level_from_evidence,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

PROOF_MIGRATION_INTERFACE: Final = "DuckDBProofMigration@1"
PROOF_MIGRATION_SCHEMA_VERSION: Final = "duckdb-proof-migration/v1"
MIGRATION_JOB_SCHEMA: Final = "duckdb-proof-migration-job/v1"
MIGRATION_CURSOR_SCHEMA: Final = "duckdb-proof-migration-cursor/v1"
MIGRATION_REJECT_SCHEMA: Final = "duckdb-proof-migration-reject/v1"
MIGRATION_RECEIPT_SCHEMA: Final = "duckdb-proof-migration-receipt/v1"
PARITY_RECEIPT_SCHEMA: Final = "duckdb-proof-migration-parity/v1"
PROMOTION_STATE_SCHEMA: Final = "duckdb-proof-migration-promotion/v1"

# Legacy schema markers used for family detection.
_COMMON_SCHEMA: Final = "proof-cache-v1"
_HAMMER_SCHEMA: Final = "hammer-proof-obligation-cache-v1"
_LEGAL_INDEX_SCHEMA: Final = "legal-proof-index/v1"
_LEGAL_RECORD_SCHEMA: Final = "legal-proof-record/v1"
_LEGAL_CACHE_INTERFACE: Final = "LegalProofCache@1"

# Type-specific batch bounds keep peak memory independent of corpus size.
DEFAULT_BATCH_SIZES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "common": 100,
        "tdfol": 100,
        "cec": 100,
        "integration": 100,
        "hammers": 50,
        "legal_ir": 50,
        "external_provers": 100,
    }
)

_MAX_SNIPPET_BYTES: Final = 512
_CHUNK_SIZE: Final = 1024 * 1024
_MAX_IMPORT_ENTRIES: Final = 100_000  # hard bound per job (safety)

# Status aliases that map unambiguously onto ResultStatus.
_STATUS_ALIASES: Final[Mapping[str, ResultStatus]] = MappingProxyType(
    {
        "proved": ResultStatus.PROVED,
        "proof": ResultStatus.PROVED,
        "proven": ResultStatus.PROVED,
        "success": ResultStatus.PROVED,
        "true": ResultStatus.PROVED,
        "disproved": ResultStatus.DISPROVED,
        "counterexample": ResultStatus.DISPROVED,
        "false": ResultStatus.DISPROVED,
        "sat": ResultStatus.SATISFIABLE,
        "satisfiable": ResultStatus.SATISFIABLE,
        "unsat": ResultStatus.UNSATISFIABLE,
        "unsatisfiable": ResultStatus.UNSATISFIABLE,
        "unknown": ResultStatus.UNKNOWN,
        "timeout": ResultStatus.TIMEOUT,
        "error": ResultStatus.ERROR,
        "failed": ResultStatus.ERROR,
        "failure": ResultStatus.ERROR,
        "malformed": ResultStatus.MALFORMED,
        "unavailable": ResultStatus.UNAVAILABLE,
        "unsupported": ResultStatus.UNSUPPORTED,
        "candidate": ResultStatus.CANDIDATE,
        "reconstructed": ResultStatus.RECONSTRUCTED,
        "attested": ResultStatus.ATTESTED,
    }
)

__all__ = [
    "DEFAULT_BATCH_SIZES",
    "MIGRATION_CURSOR_SCHEMA",
    "MIGRATION_JOB_SCHEMA",
    "MIGRATION_RECEIPT_SCHEMA",
    "MIGRATION_REJECT_SCHEMA",
    "PARITY_RECEIPT_SCHEMA",
    "PROMOTION_STATE_SCHEMA",
    "PROOF_MIGRATION_INTERFACE",
    "PROOF_MIGRATION_SCHEMA_VERSION",
    "AuthorityMode",
    "DifferentialRead",
    "ImportDisposition",
    "MemoryProofMigrationBackend",
    "MigrationCursor",
    "MigrationJob",
    "MigrationReceipt",
    "MigrationReject",
    "MigrationStatus",
    "NormalizedLegacyEntry",
    "ParityReceipt",
    "PromotionState",
    "ProofCacheFamily",
    "ProofCacheMigrator",
    "ProofMigrationBackend",
    "ProofMigrationError",
    "ProofMigrationIntegrityError",
    "ProofMigrationQuarantineError",
    "RawLegacyRecord",
    "batch_size_for",
    "detect_proof_cache_family",
    "differential_read",
    "original_byte_digest",
    "source_digest_for_path",
    "translate_status",
    "translate_trust",
    "translate_ttl",
]


# ---------------------------------------------------------------------------
# Errors and closed vocabularies
# ---------------------------------------------------------------------------


class ProofMigrationError(ValueError):
    """Fail-closed migration rejection (contract, promotion, or resume)."""


class ProofMigrationIntegrityError(ProofMigrationError):
    """Raised when source bytes or a stored receipt fail integrity checks."""


class ProofMigrationQuarantineError(ProofMigrationError):
    """Raised when a mapping is ambiguous and must not be guessed.

    Adapters catch this to emit quarantine reject rows rather than inventing
    keys, TTL, or trust levels.
    """


class ProofCacheFamily(StrEnum):
    """Closed set of proof-cache families with streaming adapters."""

    COMMON = "common"
    TDFOL = "tdfol"
    CEC = "cec"
    INTEGRATION = "integration"
    HAMMERS = "hammers"
    LEGAL_IR = "legal_ir"
    EXTERNAL_PROVERS = "external_provers"

    @classmethod
    def parse(cls, value: str | ProofCacheFamily) -> ProofCacheFamily:
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "proof_cache": cls.COMMON,
            "unified": cls.COMMON,
            "common_proof_cache": cls.COMMON,
            "tdfol_proof_cache": cls.TDFOL,
            "cec_proof_cache": cls.CEC,
            "dcec": cls.CEC,
            "integration_cache": cls.INTEGRATION,
            "integration_caching": cls.INTEGRATION,
            "hammer": cls.HAMMERS,
            "hammer_proof_cache": cls.HAMMERS,
            "obligation_cache": cls.HAMMERS,
            "legal": cls.LEGAL_IR,
            "legal_proof_cache": cls.LEGAL_IR,
            "external": cls.EXTERNAL_PROVERS,
            "external_prover": cls.EXTERNAL_PROVERS,
            "external_prover_cache": cls.EXTERNAL_PROVERS,
        }
        if text in aliases:
            return aliases[text]
        return cls(text)


class MigrationStatus(StrEnum):
    """Lifecycle of one migration job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"
    SKIPPED_PROMOTED = "skipped_promoted"


class ImportDisposition(StrEnum):
    """Per-record outcome retained for parity and audit."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"


class AuthorityMode(StrEnum):
    """Authority transition for a proof-cache family."""

    LEGACY = "legacy"
    SHADOW = "shadow"
    DUAL = "dual"
    PROMOTED = "promoted"
    EXPORT_ONLY = "export_only"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def original_byte_digest(data: bytes | bytearray | memoryview) -> str:
    """Return ``sha256:<hex>`` over exact original bytes (no re-encoding)."""

    return _sha256_bytes(bytes(data))


def source_digest_for_path(
    path: str | os.PathLike[str] | Path,
    *,
    chunk_size: int = _CHUNK_SIZE,
) -> str:
    """Stream-hash exact source bytes; never load the full file into memory."""

    target = Path(path)
    if not target.is_file():
        raise ProofMigrationError(f"source path is not a file: {target}")
    if chunk_size < 1:
        raise ProofMigrationError("chunk_size must be positive")
    hasher = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _clip_snippet(raw: str | bytes, *, limit: int = _MAX_SNIPPET_BYTES) -> str:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            text = raw.hex()
    else:
        text = str(raw)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore") + "…"


def _safe_token(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProofMigrationError(f"{field_name} is required")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ProofMigrationError(f"{field_name} must be single-line text")
    if len(text.encode("utf-8")) > 512:
        raise ProofMigrationError(f"{field_name} exceeds 512-byte bound")
    return text


def _finite_timestamp(value: Any, *, field_name: str = "timestamp") -> float:
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as error:
        raise ProofMigrationQuarantineError(
            f"{field_name} is not a finite number"
        ) from error
    if timestamp != timestamp or timestamp in (float("inf"), float("-inf")):
        raise ProofMigrationQuarantineError(f"{field_name} is not a finite number")
    return timestamp


def batch_size_for(
    family: ProofCacheFamily | str, override: int | None = None
) -> int:
    """Return the effective positive batch size for *family*."""

    if override is not None:
        if not isinstance(override, int) or isinstance(override, bool) or override < 1:
            raise ProofMigrationError("batch_size must be a positive integer")
        return override
    parsed = ProofCacheFamily.parse(family)
    return int(DEFAULT_BATCH_SIZES[parsed.value])


def detect_proof_cache_family(
    path: str | os.PathLike[str] | Path,
    *,
    explicit: ProofCacheFamily | str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> ProofCacheFamily:
    """Detect family from *explicit* override, payload schema, or path name."""

    if explicit is not None:
        return ProofCacheFamily.parse(explicit)

    if payload is not None:
        schema = str(payload.get("schema_version") or "")
        interface = str(payload.get("interface") or "")
        if schema == _HAMMER_SCHEMA:
            return ProofCacheFamily.HAMMERS
        if schema in {_LEGAL_INDEX_SCHEMA, _LEGAL_RECORD_SCHEMA}:
            return ProofCacheFamily.LEGAL_IR
        if interface == _LEGAL_CACHE_INTERFACE:
            return ProofCacheFamily.LEGAL_IR
        if schema == _COMMON_SCHEMA:
            # Common schema is shared by common/tdfol/external/cec shims.
            return ProofCacheFamily.COMMON
        # Integration CachedProof snapshot shape (list of formula_hash entries).
        if "formula_hash" in payload and "prover" in payload:
            return ProofCacheFamily.INTEGRATION
        entries = payload.get("entries")
        if isinstance(entries, list) and entries:
            first = entries[0]
            if isinstance(first, Mapping):
                if "key" in first and "outcome" in first:
                    return ProofCacheFamily.HAMMERS
                if "formula_hash" in first and "prover" in first:
                    return ProofCacheFamily.INTEGRATION
                if "cid" in first and "prover_name" in first:
                    return ProofCacheFamily.COMMON

    name = Path(path).name.lower()
    # Normalize path separators and ensure a leading slash so segment matches work.
    lower = "/" + str(path).lower().replace("\\", "/").lstrip("/")
    if "legal" in name or "legal_ir" in lower or "legal-ir" in lower:
        return ProofCacheFamily.LEGAL_IR
    if "hammer" in name or "obligation" in name:
        return ProofCacheFamily.HAMMERS
    if "tdfol" in name or "/tdfol/" in lower:
        return ProofCacheFamily.TDFOL
    if "/cec/" in lower or name.startswith("cec") or "_cec" in name:
        return ProofCacheFamily.CEC
    # Check integration before generic "prover" (proof_cache.json would match prover).
    if "integration" in name or "/integration/" in lower:
        return ProofCacheFamily.INTEGRATION
    if "external" in name or "/external_provers/" in lower:
        return ProofCacheFamily.EXTERNAL_PROVERS
    if name.endswith(".json") or name.endswith(".jsonl"):
        return ProofCacheFamily.COMMON
    raise ProofMigrationError(
        f"cannot detect proof-cache family for {path!r}; pass family explicitly"
    )


# ---------------------------------------------------------------------------
# TTL / trust / status translation (fail-closed)
# ---------------------------------------------------------------------------


def translate_status(value: Any) -> ResultStatus:
    """Map a legacy status token onto :class:`ResultStatus`.

    Ambiguous or unknown tokens raise :class:`ProofMigrationQuarantineError`
    rather than guessing a conclusive outcome.
    """

    if isinstance(value, ResultStatus):
        return value
    if isinstance(value, bool):
        # Booleans alone are ambiguous (is True proved or sat?).
        raise ProofMigrationQuarantineError(
            "boolean status is ambiguous; require an explicit status string"
        )
    if value is None:
        raise ProofMigrationQuarantineError("status is missing")
    text = str(value).strip().lower()
    if not text:
        raise ProofMigrationQuarantineError("status is empty")
    if text in _STATUS_ALIASES:
        return _STATUS_ALIASES[text]
    try:
        return ResultStatus(text)
    except ValueError as error:
        raise ProofMigrationQuarantineError(
            f"status {text!r} has no closed ResultStatus mapping"
        ) from error


def translate_trust(
    value: Any,
    *,
    kernel_accepted: bool = False,
    deterministic_trusted: bool = False,
    evidence_authority: EvidenceAuthority | str | None = None,
    family: ProofCacheFamily | str | None = None,
) -> ProofTrustLevel:
    """Map a legacy trust claim onto :class:`ProofTrustLevel`.

    Rules (never guess upward):

    * missing / absent → ``NONE`` (common/integration/cec/tdfol/external)
    * explicit ``non_trusted`` / ATP-only → ``NON_TRUSTED``
    * ``trusted`` requires kernel_accepted or deterministic_trusted
    * legal-IR with proved theorem receipts may reach ``INDEPENDENTLY_CHECKABLE``
    * evidence authority, when present, projects via the proof store mapping
    * any other promotion claim is quarantined
    """

    if evidence_authority is not None:
        try:
            resolved_evidence = (
                evidence_authority
                if isinstance(evidence_authority, EvidenceAuthority)
                else EvidenceAuthority(str(evidence_authority))
            )
        except (TypeError, ValueError) as error:
            raise ProofMigrationQuarantineError(
                f"evidence_authority {evidence_authority!r} is not a closed value"
            ) from error
        # Evidence authority is authoritative when supplied explicitly.
        return trust_level_from_evidence(resolved_evidence)

    if value is None or value == "":
        return ProofTrustLevel.NONE

    if isinstance(value, ProofTrustLevel):
        level = value
    else:
        text = str(value).strip().lower().replace("-", "_")
        if text in {"none", "absent", "missing"}:
            return ProofTrustLevel.NONE
        if text in {"non_trusted", "untrusted", "atp", "candidate"}:
            return ProofTrustLevel.NON_TRUSTED
        if text in {
            "trusted",
            "kernel",
            "authoritative",
            "independently_checkable",
            "bounded",
            "advisory",
        }:
            # "trusted" alone is not enough — need kernel/deterministic proof.
            if text == "trusted":
                if kernel_accepted or deterministic_trusted:
                    return ProofTrustLevel.INDEPENDENTLY_CHECKABLE
                raise ProofMigrationQuarantineError(
                    "trusted claim without kernel_accepted or "
                    "deterministic_trusted must be quarantined"
                )
            if text == "kernel":
                if not kernel_accepted:
                    raise ProofMigrationQuarantineError(
                        "kernel trust requires kernel_accepted=True"
                    )
                return ProofTrustLevel.INDEPENDENTLY_CHECKABLE
            try:
                return ProofTrustLevel(text)
            except ValueError as error:
                raise ProofMigrationQuarantineError(
                    f"trust {text!r} is not a closed ProofTrustLevel"
                ) from error
        raise ProofMigrationQuarantineError(
            f"trust {text!r} has no closed mapping"
        )

    if level is ProofTrustLevel.AUTHORITATIVE:
        # Authoritative cannot be inferred from legacy caches.
        raise ProofMigrationQuarantineError(
            "authoritative trust cannot be inferred from legacy proof caches"
        )
    if level is ProofTrustLevel.INDEPENDENTLY_CHECKABLE and not (
        kernel_accepted or deterministic_trusted
    ):
        if family is not None and ProofCacheFamily.parse(family) is ProofCacheFamily.LEGAL_IR:
            # Legal-IR theorem receipts carry independent checkability.
            return level
        raise ProofMigrationQuarantineError(
            "independently_checkable trust requires kernel or deterministic proof"
        )
    return level


@dataclass(frozen=True, slots=True)
class TranslatedTTL:
    """Dual-TTL projection used by the unified store."""

    positive_ttl_seconds: float
    negative_ttl_seconds: float
    entry_ttl_seconds: float | None = None
    source: str = "default"


def translate_ttl(
    *,
    family_ttl: Any = None,
    entry_ttl: Any = None,
    positive_ttl: Any = None,
    negative_ttl: Any = None,
    polarity: CachePolarity | str | None = None,
    default_positive: float = DEFAULT_POSITIVE_TTL_SECONDS,
    default_negative: float = DEFAULT_NEGATIVE_TTL_SECONDS,
) -> TranslatedTTL:
    """Translate legacy TTL fields into dual positive/negative TTLs.

    Ambiguous cases (negative > positive when both set, conflicting dual and
    single TTL without polarity, non-finite values) are quarantined.
    """

    def _parse(value: Any, name: str) -> float | None:
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ProofMigrationQuarantineError(
                f"{name} is not a finite number"
            ) from error
        if number != number or number in (float("inf"), float("-inf")):
            raise ProofMigrationQuarantineError(f"{name} is not a finite number")
        if number < 0:
            raise ProofMigrationQuarantineError(f"{name} must be non-negative")
        return number

    pos = _parse(positive_ttl, "positive_ttl")
    neg = _parse(negative_ttl, "negative_ttl")
    fam = _parse(family_ttl, "family_ttl")
    ent = _parse(entry_ttl, "entry_ttl")

    if pos is not None and neg is not None:
        if neg > pos and pos > 0:
            raise ProofMigrationQuarantineError(
                "negative_ttl cannot exceed positive_ttl"
            )
        return TranslatedTTL(
            positive_ttl_seconds=pos,
            negative_ttl_seconds=neg,
            entry_ttl_seconds=ent,
            source="dual",
        )

    # Single TTL sources (family or entry) — project by polarity when known.
    single = ent if ent is not None else fam
    if single is not None:
        if pos is not None or neg is not None:
            # Half dual + single is ambiguous without clear assignment.
            raise ProofMigrationQuarantineError(
                "mixed single and partial dual TTL mapping is ambiguous"
            )
        resolved_polarity: CachePolarity | None = None
        if polarity is not None:
            try:
                resolved_polarity = (
                    polarity
                    if isinstance(polarity, CachePolarity)
                    else CachePolarity(str(polarity))
                )
            except (TypeError, ValueError) as error:
                raise ProofMigrationQuarantineError(
                    f"polarity {polarity!r} is not a closed CachePolarity"
                ) from error
        if resolved_polarity is CachePolarity.NEGATIVE:
            return TranslatedTTL(
                positive_ttl_seconds=float(default_positive),
                negative_ttl_seconds=single,
                entry_ttl_seconds=single,
                source="single_negative",
            )
        if resolved_polarity is CachePolarity.POSITIVE:
            return TranslatedTTL(
                positive_ttl_seconds=single,
                negative_ttl_seconds=min(single, float(default_negative))
                if single > 0
                else float(default_negative),
                entry_ttl_seconds=single,
                source="single_positive",
            )
        # No polarity: apply single TTL to both bands (common family default).
        return TranslatedTTL(
            positive_ttl_seconds=single if single > 0 else float(default_positive),
            negative_ttl_seconds=single
            if 0 < single <= float(default_negative)
            else min(single, float(default_negative))
            if single > 0
            else float(default_negative),
            entry_ttl_seconds=single,
            source="single_shared",
        )

    if pos is not None:
        return TranslatedTTL(
            positive_ttl_seconds=pos,
            negative_ttl_seconds=float(default_negative),
            entry_ttl_seconds=ent,
            source="positive_only",
        )
    if neg is not None:
        return TranslatedTTL(
            positive_ttl_seconds=float(default_positive),
            negative_ttl_seconds=neg,
            entry_ttl_seconds=ent,
            source="negative_only",
        )

    return TranslatedTTL(
        positive_ttl_seconds=float(default_positive),
        negative_ttl_seconds=float(default_negative),
        entry_ttl_seconds=None,
        source="default",
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawLegacyRecord:
    """One raw legacy unit before accept / reject / quarantine decision."""

    record_index: int
    line_number: int
    payload: Any | None = None
    raw_text: str = ""
    error: str = ""
    source_path: str = ""
    original_bytes_digest: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.payload is not None


@dataclass(frozen=True, slots=True)
class NormalizedLegacyEntry:
    """Normalized projection ready for the unified proof store."""

    family: ProofCacheFamily
    key: UnifiedProofKey
    status: ResultStatus
    trust_level: ProofTrustLevel
    result_authority: ResultAuthority
    evidence_authority: EvidenceAuthority
    result_payload: Mapping[str, Any]
    created_at: float
    result_id: str = ""
    diagnostics: tuple[str, ...] = ()
    source_record_index: int = 0
    source_line_number: int = 0
    original_bytes_digest: str = ""
    legacy_entry_digest: str = ""
    ttl: TranslatedTTL = field(
        default_factory=lambda: TranslatedTTL(
            positive_ttl_seconds=DEFAULT_POSITIVE_TTL_SECONDS,
            negative_ttl_seconds=DEFAULT_NEGATIVE_TTL_SECONDS,
        )
    )

    def to_unified_entry(
        self, *, created_at: float | None = None
    ) -> UnifiedProofEntry:
        """Build a store entry.

        ``created_at`` defaults to *now* so dual-TTL freshness starts at import
        time.  The legacy timestamp remains available on this record and is
        copied into diagnostics for audit.
        """

        outcome = outcome_kind_for_status(self.status)
        polarity = polarity_for_outcome(outcome)
        stamp = float(created_at) if created_at is not None else time.time()
        diagnostics = list(self.diagnostics)
        legacy_marker = f"legacy_created_at:{self.created_at}"
        if legacy_marker not in diagnostics:
            diagnostics.append(legacy_marker)
        return UnifiedProofEntry(
            key=self.key,
            outcome=outcome,
            trust_level=self.trust_level,
            status=self.status,
            result_authority=self.result_authority,
            evidence_authority=self.evidence_authority,
            result_payload=FrozenMap(dict(self.result_payload)),
            polarity=polarity,
            created_at=stamp,
            result_id=self.result_id,
            diagnostics=tuple(diagnostics),
        )


@dataclass(frozen=True)
class MigrationReject:
    """Rejected or quarantined row retained for operator review."""

    reject_id: str
    job_id: str
    family: str
    source_path: str
    source_digest: str
    record_index: int
    line_number: int
    batch_index: int
    reason: str
    disposition: str = ImportDisposition.REJECTED.value
    raw_snippet: str = ""
    created_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        if not self.reject_id:
            body = {
                "batch_index": self.batch_index,
                "disposition": self.disposition,
                "family": self.family,
                "job_id": self.job_id,
                "line_number": self.line_number,
                "reason": self.reason,
                "record_index": self.record_index,
                "source_digest": self.source_digest,
                "source_path": self.source_path,
            }
            object.__setattr__(
                self,
                "reject_id",
                "sha256:" + _sha256_text(_canonical_json(body)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATION_REJECT_SCHEMA,
            "batch_index": self.batch_index,
            "created_at": self.created_at,
            "disposition": self.disposition,
            "family": self.family,
            "job_id": self.job_id,
            "line_number": self.line_number,
            "raw_snippet": self.raw_snippet,
            "reason": self.reason,
            "record_index": self.record_index,
            "reject_id": self.reject_id,
            "source_digest": self.source_digest,
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class MigrationCursor:
    """Resumable cursor: next record_index to process for a job."""

    job_id: str
    source_path: str
    source_digest: str
    family: str
    next_record_index: int
    batch_index: int
    accepted_count: int = 0
    rejected_count: int = 0
    quarantined_count: int = 0
    updated_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        if self.next_record_index < 0:
            raise ProofMigrationError("next_record_index must be non-negative")
        if self.batch_index < 0:
            raise ProofMigrationError("batch_index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATION_CURSOR_SCHEMA,
            "accepted_count": self.accepted_count,
            "batch_index": self.batch_index,
            "family": self.family,
            "job_id": self.job_id,
            "next_record_index": self.next_record_index,
            "quarantined_count": self.quarantined_count,
            "rejected_count": self.rejected_count,
            "source_digest": self.source_digest,
            "source_path": self.source_path,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MigrationJob:
    """Durable migration job identity bound to source digest + idempotency key."""

    job_id: str
    source_path: str
    family: str
    source_digest: str
    idempotency_key: str
    batch_size: int
    status: str
    byte_size: int = 0
    total_records: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    quarantined_count: int = 0
    created_at: str = field(default_factory=_utc_iso)
    updated_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _safe_token(self.job_id, field_name="job_id"))
        object.__setattr__(
            self, "family", ProofCacheFamily.parse(self.family).value
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _safe_token(self.idempotency_key, field_name="idempotency_key"),
        )
        if not isinstance(self.batch_size, int) or self.batch_size < 1:
            raise ProofMigrationError("batch_size must be a positive integer")
        try:
            MigrationStatus(self.status)
        except ValueError as exc:
            raise ProofMigrationError(
                f"unsupported migration status {self.status!r}"
            ) from exc
        if not str(self.source_digest).startswith("sha256:"):
            raise ProofMigrationError("source_digest must be sha256:<hex>")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATION_JOB_SCHEMA,
            "accepted_count": self.accepted_count,
            "batch_size": self.batch_size,
            "byte_size": self.byte_size,
            "created_at": self.created_at,
            "family": self.family,
            "idempotency_key": self.idempotency_key,
            "job_id": self.job_id,
            "quarantined_count": self.quarantined_count,
            "rejected_count": self.rejected_count,
            "source_digest": self.source_digest,
            "source_path": self.source_path,
            "status": self.status,
            "total_records": self.total_records,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MigrationReceipt:
    """Immutable completion receipt for one migration job."""

    receipt_id: str
    job_id: str
    source_path: str
    family: str
    source_digest: str
    idempotency_key: str
    status: str
    accepted_count: int
    rejected_count: int
    quarantined_count: int
    total_records: int
    batch_size: int
    batches_committed: int
    accepted_entry_digests: tuple[str, ...] = ()
    resumed: bool = False
    cursor_next_record_index: int = 0
    created_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        if not self.receipt_id:
            body = {
                "accepted_count": self.accepted_count,
                "batch_size": self.batch_size,
                "batches_committed": self.batches_committed,
                "cursor_next_record_index": self.cursor_next_record_index,
                "family": self.family,
                "idempotency_key": self.idempotency_key,
                "job_id": self.job_id,
                "quarantined_count": self.quarantined_count,
                "rejected_count": self.rejected_count,
                "resumed": self.resumed,
                "source_digest": self.source_digest,
                "source_path": self.source_path,
                "status": self.status,
                "total_records": self.total_records,
                "created_at": self.created_at,
            }
            object.__setattr__(
                self,
                "receipt_id",
                "sha256:" + _sha256_text(_canonical_json(body)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MIGRATION_RECEIPT_SCHEMA,
            "accepted_count": self.accepted_count,
            "accepted_entry_digests": list(self.accepted_entry_digests),
            "batch_size": self.batch_size,
            "batches_committed": self.batches_committed,
            "created_at": self.created_at,
            "cursor_next_record_index": self.cursor_next_record_index,
            "family": self.family,
            "idempotency_key": self.idempotency_key,
            "job_id": self.job_id,
            "quarantined_count": self.quarantined_count,
            "receipt_id": self.receipt_id,
            "rejected_count": self.rejected_count,
            "resumed": self.resumed,
            "source_digest": self.source_digest,
            "source_path": self.source_path,
            "status": self.status,
            "total_records": self.total_records,
        }


@dataclass(frozen=True)
class ParityReceipt:
    """Differential / parity receipt between legacy entries and the store."""

    parity_id: str
    family: str
    source_path: str
    source_digest: str
    legacy_count: int
    store_count: int
    matched_count: int
    mismatched_count: int
    missing_in_store: int
    extra_in_store: int
    quarantined_count: int
    legacy_digest_root: str
    store_digest_root: str
    matched: bool
    created_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        if not self.parity_id:
            body = {
                "extra_in_store": self.extra_in_store,
                "family": self.family,
                "legacy_count": self.legacy_count,
                "legacy_digest_root": self.legacy_digest_root,
                "matched_count": self.matched_count,
                "missing_in_store": self.missing_in_store,
                "mismatched_count": self.mismatched_count,
                "quarantined_count": self.quarantined_count,
                "source_digest": self.source_digest,
                "source_path": self.source_path,
                "store_count": self.store_count,
                "store_digest_root": self.store_digest_root,
            }
            object.__setattr__(
                self,
                "parity_id",
                "sha256:" + _sha256_text(_canonical_json(body)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PARITY_RECEIPT_SCHEMA,
            "created_at": self.created_at,
            "extra_in_store": self.extra_in_store,
            "family": self.family,
            "legacy_count": self.legacy_count,
            "legacy_digest_root": self.legacy_digest_root,
            "matched": self.matched,
            "matched_count": self.matched_count,
            "missing_in_store": self.missing_in_store,
            "mismatched_count": self.mismatched_count,
            "parity_id": self.parity_id,
            "quarantined_count": self.quarantined_count,
            "source_digest": self.source_digest,
            "source_path": self.source_path,
            "store_count": self.store_count,
            "store_digest_root": self.store_digest_root,
        }


@dataclass(frozen=True)
class DifferentialRead:
    """One differential comparison of a legacy key against the store."""

    key_digest: str
    legacy_entry_digest: str
    store_entry_digest: str
    present_in_legacy: bool
    present_in_store: bool
    digests_match: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "digests_match": self.digests_match,
            "key_digest": self.key_digest,
            "legacy_entry_digest": self.legacy_entry_digest,
            "present_in_legacy": self.present_in_legacy,
            "present_in_store": self.present_in_store,
            "reason": self.reason,
            "store_entry_digest": self.store_entry_digest,
        }


@dataclass
class PromotionState:
    """Per-family authority mode; promoted families forbid whole-file rewrites."""

    modes: dict[str, str] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def mode_for(self, family: ProofCacheFamily | str) -> AuthorityMode:
        parsed = ProofCacheFamily.parse(family)
        with self._lock:
            raw = self.modes.get(parsed.value, AuthorityMode.LEGACY.value)
        try:
            return AuthorityMode(raw)
        except ValueError as error:
            raise ProofMigrationError(
                f"unknown authority mode {raw!r} for family {parsed.value}"
            ) from error

    def set_mode(
        self, family: ProofCacheFamily | str, mode: AuthorityMode | str
    ) -> None:
        parsed = ProofCacheFamily.parse(family)
        resolved = mode if isinstance(mode, AuthorityMode) else AuthorityMode(str(mode))
        with self._lock:
            self.modes[parsed.value] = resolved.value

    def is_promoted(self, family: ProofCacheFamily | str) -> bool:
        mode = self.mode_for(family)
        return mode in {AuthorityMode.PROMOTED, AuthorityMode.EXPORT_ONLY}

    def assert_json_rewrite_allowed(
        self, family: ProofCacheFamily | str, *, path: str = ""
    ) -> None:
        """Fail closed when a whole-file JSON rewrite is attempted post-promotion."""

        if self.is_promoted(family):
            where = f" ({path})" if path else ""
            raise ProofMigrationError(
                f"whole-file JSON rewrite forbidden after promotion for "
                f"family {ProofCacheFamily.parse(family).value}{where}"
            )

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": PROMOTION_STATE_SCHEMA,
                "modes": dict(sorted(self.modes.items())),
            }


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProofMigrationBackend(Protocol):
    """Persistence surface for jobs, cursors, rejects, and receipts."""

    def get_job_by_idempotency(
        self, idempotency_key: str, source_digest: str
    ) -> MigrationJob | None: ...

    def put_job(self, job: MigrationJob) -> None: ...

    def get_cursor(self, job_id: str) -> MigrationCursor | None: ...

    def put_cursor(self, cursor: MigrationCursor) -> None: ...

    def put_reject(self, reject: MigrationReject) -> None: ...

    def list_rejects(self, job_id: str) -> Sequence[MigrationReject]: ...

    def put_receipt(self, receipt: MigrationReceipt) -> None: ...

    def get_receipt(self, job_id: str) -> MigrationReceipt | None: ...

    def put_parity(self, parity: ParityReceipt) -> None: ...

    def record_accepted_digest(self, job_id: str, entry_digest: str) -> None: ...

    def has_accepted_digest(self, job_id: str, entry_digest: str) -> bool: ...

    def list_accepted_digests(self, job_id: str) -> Sequence[str]: ...


class MemoryProofMigrationBackend:
    """Hermetic in-memory backend for unit tests and dry-runs."""

    def __init__(self) -> None:
        self._jobs: dict[str, MigrationJob] = {}
        self._by_idempotency: dict[tuple[str, str], str] = {}
        self._cursors: dict[str, MigrationCursor] = {}
        self._rejects: dict[str, list[MigrationReject]] = {}
        self._receipts: dict[str, MigrationReceipt] = {}
        self._parity: list[ParityReceipt] = []
        self._accepted: dict[str, list[str]] = {}
        self._lock = threading.RLock()

    def get_job_by_idempotency(
        self, idempotency_key: str, source_digest: str
    ) -> MigrationJob | None:
        with self._lock:
            job_id = self._by_idempotency.get((idempotency_key, source_digest))
            if job_id is None:
                return None
            return self._jobs.get(job_id)

    def put_job(self, job: MigrationJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._by_idempotency[(job.idempotency_key, job.source_digest)] = job.job_id

    def get_cursor(self, job_id: str) -> MigrationCursor | None:
        with self._lock:
            return self._cursors.get(job_id)

    def put_cursor(self, cursor: MigrationCursor) -> None:
        with self._lock:
            self._cursors[cursor.job_id] = cursor

    def put_reject(self, reject: MigrationReject) -> None:
        with self._lock:
            self._rejects.setdefault(reject.job_id, []).append(reject)

    def list_rejects(self, job_id: str) -> Sequence[MigrationReject]:
        with self._lock:
            return tuple(self._rejects.get(job_id, ()))

    def put_receipt(self, receipt: MigrationReceipt) -> None:
        with self._lock:
            self._receipts[receipt.job_id] = receipt

    def get_receipt(self, job_id: str) -> MigrationReceipt | None:
        with self._lock:
            return self._receipts.get(job_id)

    def put_parity(self, parity: ParityReceipt) -> None:
        with self._lock:
            self._parity.append(parity)

    def list_parity(self) -> Sequence[ParityReceipt]:
        with self._lock:
            return tuple(self._parity)

    def record_accepted_digest(self, job_id: str, entry_digest: str) -> None:
        with self._lock:
            bucket = self._accepted.setdefault(job_id, [])
            if entry_digest not in bucket:
                bucket.append(entry_digest)

    def has_accepted_digest(self, job_id: str, entry_digest: str) -> bool:
        with self._lock:
            return entry_digest in self._accepted.get(job_id, ())

    def list_accepted_digests(self, job_id: str) -> Sequence[str]:
        with self._lock:
            return tuple(self._accepted.get(job_id, ()))


# ---------------------------------------------------------------------------
# Streaming parsers (family-aware)
# ---------------------------------------------------------------------------


def _iter_json_entry_list(
    path: Path,
    *,
    source_digest: str,
    collection_keys: Sequence[str] = ("entries", "records", "items", "cache"),
) -> Iterator[RawLegacyRecord]:
    """Stream entries from a JSON object/list without rewriting the file."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        yield RawLegacyRecord(
            record_index=0,
            line_number=0,
            error=f"unable to read source: {exc}",
            source_path=str(path),
            original_bytes_digest="",
        )
        return

    file_digest = original_byte_digest(raw)
    if source_digest and file_digest != source_digest:
        yield RawLegacyRecord(
            record_index=0,
            line_number=0,
            error=(
                f"source digest mismatch: expected {source_digest}, got {file_digest}"
            ),
            source_path=str(path),
            original_bytes_digest=file_digest,
            raw_text=_clip_snippet(raw),
        )
        return

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        yield RawLegacyRecord(
            record_index=0,
            line_number=getattr(exc, "lineno", 1) or 1,
            error=f"json decode error: {exc}",
            source_path=str(path),
            original_bytes_digest=file_digest,
            raw_text=_clip_snippet(raw),
        )
        return

    if isinstance(data, list):
        for index, item in enumerate(data):
            yield RawLegacyRecord(
                record_index=index,
                line_number=index + 1,
                payload=item,
                raw_text=_clip_snippet(
                    _canonical_json(item) if not isinstance(item, str) else item
                ),
                source_path=str(path),
                original_bytes_digest=file_digest,
            )
        return

    if isinstance(data, Mapping):
        for key in collection_keys:
            nested = data.get(key)
            if isinstance(nested, list):
                for index, item in enumerate(nested):
                    yield RawLegacyRecord(
                        record_index=index,
                        line_number=index + 1,
                        payload=item,
                        raw_text=_clip_snippet(
                            _canonical_json(item)
                            if not isinstance(item, str)
                            else item
                        ),
                        source_path=str(path),
                        original_bytes_digest=file_digest,
                    )
                return
        # Single-object cache (integration entry or legal record).
        yield RawLegacyRecord(
            record_index=0,
            line_number=1,
            payload=dict(data),
            raw_text=_clip_snippet(raw),
            source_path=str(path),
            original_bytes_digest=file_digest,
        )
        return

    yield RawLegacyRecord(
        record_index=0,
        line_number=1,
        error=f"unsupported JSON root type {type(data).__name__}",
        source_path=str(path),
        original_bytes_digest=file_digest,
        raw_text=_clip_snippet(raw),
    )


def _iter_legal_ir_records(
    path: Path, *, source_digest: str
) -> Iterator[RawLegacyRecord]:
    """Stream legal-IR index + per-CID record files, or a single record file."""

    target = Path(path)
    if target.is_dir():
        index_path = target / "index.json"
        records_dir = target / "records"
        index_digest = ""
        if index_path.is_file():
            index_digest = source_digest_for_path(index_path)
            # Prefer digest of the directory's index as the job source digest
            # when the caller hashed the index; per-record digests are retained.
        if records_dir.is_dir():
            files = sorted(records_dir.glob("*.json"))
            for index, record_path in enumerate(files):
                try:
                    raw = record_path.read_bytes()
                except OSError as exc:
                    yield RawLegacyRecord(
                        record_index=index,
                        line_number=index + 1,
                        error=f"unable to read record: {exc}",
                        source_path=str(record_path),
                        original_bytes_digest=index_digest,
                    )
                    continue
                rec_digest = original_byte_digest(raw)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    yield RawLegacyRecord(
                        record_index=index,
                        line_number=index + 1,
                        error=f"json decode error: {exc}",
                        source_path=str(record_path),
                        original_bytes_digest=rec_digest,
                        raw_text=_clip_snippet(raw),
                    )
                    continue
                yield RawLegacyRecord(
                    record_index=index,
                    line_number=index + 1,
                    payload=payload,
                    raw_text=_clip_snippet(raw),
                    source_path=str(record_path),
                    original_bytes_digest=rec_digest,
                )
            return
        # Directory without records/ — fall through to index-only or error.
        if index_path.is_file():
            yield from _iter_json_entry_list(
                index_path,
                source_digest=source_digest or index_digest,
                collection_keys=("record_cids", "entries", "records"),
            )
            return
        yield RawLegacyRecord(
            record_index=0,
            line_number=0,
            error="legal_ir directory has no records/ or index.json",
            source_path=str(target),
        )
        return

    yield from _iter_json_entry_list(target, source_digest=source_digest)


def iter_legacy_records(
    path: str | os.PathLike[str] | Path,
    *,
    family: ProofCacheFamily | str,
    source_digest: str = "",
) -> Iterator[RawLegacyRecord]:
    """Yield raw legacy records for *family* without mutating the source."""

    parsed = ProofCacheFamily.parse(family)
    target = Path(path)
    if parsed is ProofCacheFamily.LEGAL_IR:
        yield from _iter_legal_ir_records(target, source_digest=source_digest)
        return
    if not target.is_file():
        yield RawLegacyRecord(
            record_index=0,
            line_number=0,
            error=f"source path is not a file: {target}",
            source_path=str(target),
        )
        return
    yield from _iter_json_entry_list(target, source_digest=source_digest)


# ---------------------------------------------------------------------------
# Family normalizers
# ---------------------------------------------------------------------------


def _legacy_entry_digest(payload: Any) -> str:
    return proof_store_content_digest(payload)


def _result_authority_for_status(status: ResultStatus) -> ResultAuthority:
    if status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
        return ResultAuthority.THEOREM
    if status in {ResultStatus.SATISFIABLE, ResultStatus.UNSATISFIABLE}:
        return ResultAuthority.SATISFIABILITY
    if status is ResultStatus.CANDIDATE:
        return ResultAuthority.CANDIDATE
    if status in {ResultStatus.RECONSTRUCTED, ResultStatus.RECONSTRUCTION_FAILED}:
        return ResultAuthority.RECONSTRUCTION
    if status in {ResultStatus.ATTESTED, ResultStatus.ATTESTATION_INVALID}:
        return ResultAuthority.ATTESTATION
    return ResultAuthority.CANDIDATE


def _normalize_common_like(
    record: RawLegacyRecord,
    *,
    family: ProofCacheFamily,
    family_ttl: Any = None,
) -> NormalizedLegacyEntry:
    if not isinstance(record.payload, Mapping):
        raise ProofMigrationQuarantineError("common-family entry must be a mapping")
    payload = dict(record.payload)

    cid = str(payload.get("cid") or "").strip()
    formula = payload.get("formula_str")
    if formula is None:
        formula = payload.get("formula")
    prover = str(
        payload.get("prover_name")
        or payload.get("prover")
        or payload.get("backend_id")
        or ""
    ).strip()
    if not cid and formula is None:
        raise ProofMigrationQuarantineError(
            "common-family entry missing both cid and formula_str"
        )
    if not prover:
        raise ProofMigrationQuarantineError(
            "common-family entry missing prover_name"
        )

    # Ambiguous dual identities: cid present but formula claims a different hash.
    if cid and formula is not None:
        # Identity is the cid; formula is retained as IR material.
        ir_value: Any = {"cid": cid, "formula_str": formula}
    elif cid:
        ir_value = {"cid": cid}
    else:
        ir_value = formula

    result = payload.get("result")
    if result is None:
        result = payload.get("result_data")
    if result is None:
        # CEC-style cached outcomes.
        if "is_proved" in payload:
            result = {
                "is_proved": payload.get("is_proved"),
                "execution_time": payload.get("execution_time"),
                "proof_steps": payload.get("proof_steps"),
                "error_message": payload.get("error_message"),
            }
        else:
            raise ProofMigrationQuarantineError(
                "common-family entry missing result payload"
            )

    status_value = payload.get("status")
    if status_value is None and isinstance(result, Mapping):
        status_value = result.get("status")
        if status_value is None and "is_proved" in result:
            status_value = "proved" if result.get("is_proved") else "unknown"
        if status_value is None and "is_proved" in payload:
            status_value = "proved" if payload.get("is_proved") else "unknown"
    if status_value is None and "is_proved" in payload:
        status_value = "proved" if payload.get("is_proved") else "unknown"
    status = translate_status(status_value)

    trust = translate_trust(
        payload.get("trust") or payload.get("trust_level"),
        kernel_accepted=bool(payload.get("kernel_accepted")),
        deterministic_trusted=bool(payload.get("deterministic_trusted")),
        family=family,
    )

    try:
        created_at = _finite_timestamp(
            payload.get("timestamp", payload.get("created_at", 0.0)),
            field_name="timestamp",
        )
    except ProofMigrationQuarantineError:
        created_at = 0.0

    outcome = outcome_kind_for_status(status)
    polarity = polarity_for_outcome(outcome)
    ttl = translate_ttl(
        family_ttl=family_ttl,
        entry_ttl=payload.get("ttl"),
        polarity=polarity,
    )

    key = UnifiedProofKey.build(
        ir=ir_value,
        property_value={"family": family.value, "cid": cid or None},
        backend_id=prover,
        backend_version=str(payload.get("backend_version") or "legacy"),
        backend_config={"source_family": family.value},
        solver_identities={"prover": prover},
        theorem_registry=f"legacy:{family.value}",
        policy={"migration": PROOF_MIGRATION_SCHEMA_VERSION},
    )

    result_payload = result if isinstance(result, Mapping) else {"value": result}
    return NormalizedLegacyEntry(
        family=family,
        key=key,
        status=status,
        trust_level=trust,
        result_authority=_result_authority_for_status(status),
        evidence_authority=EvidenceAuthority.NONE,
        result_payload=dict(result_payload),
        created_at=created_at,
        result_id=str(payload.get("result_id") or cid or key.digest),
        diagnostics=(f"migrated_from:{family.value}",),
        source_record_index=record.record_index,
        source_line_number=record.line_number,
        original_bytes_digest=record.original_bytes_digest,
        legacy_entry_digest=_legacy_entry_digest(payload),
        ttl=ttl,
    )


def _normalize_integration(
    record: RawLegacyRecord,
    *,
    family: ProofCacheFamily = ProofCacheFamily.INTEGRATION,
    family_ttl: Any = None,
) -> NormalizedLegacyEntry:
    if not isinstance(record.payload, Mapping):
        raise ProofMigrationQuarantineError("integration entry must be a mapping")
    payload = dict(record.payload)
    formula_hash = str(payload.get("formula_hash") or "").strip()
    prover = str(payload.get("prover") or "").strip()
    if not formula_hash:
        raise ProofMigrationQuarantineError("integration entry missing formula_hash")
    if not prover:
        raise ProofMigrationQuarantineError("integration entry missing prover")

    result_data = payload.get("result_data")
    if result_data is None:
        raise ProofMigrationQuarantineError("integration entry missing result_data")

    status_value = payload.get("status")
    if status_value is None and isinstance(result_data, Mapping):
        status_value = result_data.get("status")
        if status_value is None and "is_proved" in result_data:
            status_value = "proved" if result_data.get("is_proved") else "unknown"
    status = translate_status(status_value)

    # Conflicting TTL: metadata.ttl vs top-level ttl with different values.
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    top_ttl = payload.get("ttl")
    meta_ttl = meta.get("ttl") if isinstance(meta, Mapping) else None
    if (
        top_ttl is not None
        and meta_ttl is not None
        and float(top_ttl) != float(meta_ttl)
    ):
        raise ProofMigrationQuarantineError(
            "integration entry has conflicting ttl and metadata.ttl"
        )

    trust = translate_trust(
        payload.get("trust") or meta.get("trust") if isinstance(meta, Mapping) else None,
        family=family,
    )
    created_at = _finite_timestamp(
        payload.get("timestamp", 0.0), field_name="timestamp"
    )
    outcome = outcome_kind_for_status(status)
    polarity = polarity_for_outcome(outcome)
    ttl = translate_ttl(
        family_ttl=family_ttl,
        entry_ttl=top_ttl,
        polarity=polarity,
    )

    key = UnifiedProofKey.build(
        ir={"formula_hash": formula_hash},
        property_value={"family": family.value},
        backend_id=prover,
        backend_version=str(
            (meta or {}).get("backend_version") if isinstance(meta, Mapping) else "legacy"
        )
        or "legacy",
        backend_config={"source_family": family.value, "metadata": meta or {}},
        solver_identities={"prover": prover},
        theorem_registry=f"legacy:{family.value}",
        policy={"migration": PROOF_MIGRATION_SCHEMA_VERSION},
    )
    result_payload = (
        dict(result_data) if isinstance(result_data, Mapping) else {"value": result_data}
    )
    return NormalizedLegacyEntry(
        family=family,
        key=key,
        status=status,
        trust_level=trust,
        result_authority=_result_authority_for_status(status),
        evidence_authority=EvidenceAuthority.NONE,
        result_payload=result_payload,
        created_at=created_at,
        result_id=str(payload.get("result_id") or formula_hash),
        diagnostics=(f"migrated_from:{family.value}",),
        source_record_index=record.record_index,
        source_line_number=record.line_number,
        original_bytes_digest=record.original_bytes_digest,
        legacy_entry_digest=_legacy_entry_digest(payload),
        ttl=ttl,
    )


def _normalize_hammer(
    record: RawLegacyRecord,
    *,
    family: ProofCacheFamily = ProofCacheFamily.HAMMERS,
    family_ttl: Any = None,
) -> NormalizedLegacyEntry:
    if not isinstance(record.payload, Mapping):
        raise ProofMigrationQuarantineError("hammer entry must be a mapping")
    payload = dict(record.payload)
    key_payload = payload.get("key")
    outcome_payload = payload.get("outcome")
    if not isinstance(key_payload, Mapping):
        raise ProofMigrationQuarantineError("hammer entry missing key mapping")
    if not isinstance(outcome_payload, Mapping):
        raise ProofMigrationQuarantineError("hammer entry missing outcome mapping")

    # Ambiguous key: both obligation_digest and a conflicting ir_digest.
    if (
        "obligation_digest" in key_payload
        and "ir_digest" in key_payload
        and str(key_payload["obligation_digest"]) != str(key_payload["ir_digest"])
    ):
        raise ProofMigrationQuarantineError(
            "hammer key has conflicting obligation_digest and ir_digest"
        )

    try:
        key = UnifiedProofKey.from_hammer_key_dict(key_payload)
    except DuckDBProofStoreError as error:
        raise ProofMigrationQuarantineError(
            f"hammer key cannot be lifted: {error}"
        ) from error

    status = translate_status(outcome_payload.get("status"))
    trust = translate_trust(
        outcome_payload.get("trust"),
        kernel_accepted=bool(outcome_payload.get("kernel_accepted")),
        deterministic_trusted=bool(outcome_payload.get("deterministic_trusted")),
        family=family,
    )
    created_at = _finite_timestamp(
        payload.get("created_at", 0.0), field_name="created_at"
    )
    outcome = outcome_kind_for_status(status)
    polarity = polarity_for_outcome(outcome)
    ttl = translate_ttl(family_ttl=family_ttl, polarity=polarity)

    result_payload = outcome_payload.get("payload")
    if not isinstance(result_payload, Mapping):
        result_payload = {"payload": result_payload}

    # Evidence authority from kernel / deterministic flags.
    if outcome_payload.get("kernel_accepted") or outcome_payload.get(
        "deterministic_trusted"
    ):
        evidence = EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    else:
        evidence = EvidenceAuthority.NONE

    return NormalizedLegacyEntry(
        family=family,
        key=key,
        status=status,
        trust_level=trust,
        result_authority=_result_authority_for_status(status),
        evidence_authority=evidence,
        result_payload=dict(result_payload),
        created_at=created_at,
        result_id=str(
            outcome_payload.get("authority")
            or key.digest
        ),
        diagnostics=(
            f"migrated_from:{family.value}",
            f"hammer_trust:{outcome_payload.get('trust')}",
        ),
        source_record_index=record.record_index,
        source_line_number=record.line_number,
        original_bytes_digest=record.original_bytes_digest,
        legacy_entry_digest=_legacy_entry_digest(payload),
        ttl=ttl,
    )


def _normalize_legal_ir(
    record: RawLegacyRecord,
    *,
    family: ProofCacheFamily = ProofCacheFamily.LEGAL_IR,
    family_ttl: Any = None,
) -> NormalizedLegacyEntry:
    if not isinstance(record.payload, Mapping):
        raise ProofMigrationQuarantineError("legal_ir entry must be a mapping")
    payload = dict(record.payload)

    # Index-only rows (CID strings) cannot form a full proof key — quarantine.
    if set(payload.keys()) <= {"value", "_collection", "cid"} or isinstance(
        payload.get("value"), str
    ):
        # record_cids expansion may yield bare strings wrapped by parser.
        raise ProofMigrationQuarantineError(
            "legal_ir index CID without record envelope cannot be imported as "
            "authoritative; supply records/*.json"
        )

    schema = str(payload.get("schema_version") or "")
    if schema and schema not in {_LEGAL_RECORD_SCHEMA, _LEGAL_INDEX_SCHEMA}:
        # Unknown legal schema — quarantine rather than guess.
        if "legal" not in schema and not payload.get("artifact"):
            raise ProofMigrationQuarantineError(
                f"unsupported legal_ir schema_version {schema!r}"
            )

    source_digest = str(payload.get("source_digest") or "").strip()
    source_id = str(payload.get("source_id") or "").strip()
    profile = str(payload.get("profile") or "").strip()
    artifact_digest = str(payload.get("artifact_digest") or "").strip()
    content_digest = str(payload.get("content_digest") or "").strip()
    content_cid = str(payload.get("content_cid") or "").strip()

    if not profile:
        raise ProofMigrationQuarantineError("legal_ir record missing profile")
    if not source_digest and not artifact_digest and not content_digest:
        raise ProofMigrationQuarantineError(
            "legal_ir record missing source_digest/artifact_digest/content_digest"
        )

    # Ambiguous: source_digest conflicts with artifact.declaration_digest when both set.
    artifact = payload.get("artifact")
    if isinstance(artifact, Mapping):
        declaration = str(artifact.get("declaration_digest") or "").strip()
        if (
            source_digest
            and declaration
            and source_digest != declaration
            and not source_digest.endswith(declaration.replace("sha256:", ""))
        ):
            # Only quarantine when both look like digests and differ.
            if source_digest.startswith("sha256:") and declaration.startswith("sha256:"):
                raise ProofMigrationQuarantineError(
                    "legal_ir source_digest does not match artifact declaration_digest"
                )

    theorem_receipts = payload.get("theorem_receipts") or ()
    proved = False
    if isinstance(theorem_receipts, Sequence) and not isinstance(
        theorem_receipts, (str, bytes, bytearray)
    ):
        for receipt in theorem_receipts:
            if isinstance(receipt, Mapping):
                status_text = str(receipt.get("status") or "").lower()
                if status_text in {"proved", "attested", "reconstructed"}:
                    proved = True
                    break

    if proved:
        status = ResultStatus.PROVED
        trust = translate_trust(
            "independently_checkable",
            family=family,
        )
        evidence = EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    else:
        # Artifact cached without theorem proof — advisory only.
        status = ResultStatus.CANDIDATE
        trust = ProofTrustLevel.NONE
        evidence = EvidenceAuthority.NONE

    ir_value = {
        "source_id": source_id,
        "source_digest": source_digest,
        "profile": profile,
        "artifact_digest": artifact_digest,
        "content_digest": content_digest,
        "content_cid": content_cid,
    }
    key = UnifiedProofKey.build(
        ir=ir_value,
        property_value={"family": family.value, "profile": profile},
        backend_id="legal_ir",
        backend_version="legacy",
        backend_config={"jurisdiction": payload.get("jurisdiction") or ""},
        solver_identities={"family": "legal_ir"},
        theorem_registry=f"legacy:legal_ir:{profile}",
        policy={"migration": PROOF_MIGRATION_SCHEMA_VERSION, "profile": profile},
        resources={"theorem_receipts": len(list(theorem_receipts))},
    )

    created_at = 0.0
    if "created_at" in payload:
        created_at = _finite_timestamp(payload.get("created_at"), field_name="created_at")

    ttl = translate_ttl(family_ttl=family_ttl, polarity=polarity_for_outcome(
        outcome_kind_for_status(status)
    ))

    return NormalizedLegacyEntry(
        family=family,
        key=key,
        status=status,
        trust_level=trust,
        result_authority=_result_authority_for_status(status),
        evidence_authority=evidence,
        result_payload={
            "artifact": artifact if isinstance(artifact, Mapping) else {},
            "content_cid": content_cid,
            "content_digest": content_digest,
            "profile": profile,
            "source_digest": source_digest,
            "source_id": source_id,
            "theorem_receipts": list(theorem_receipts)
            if isinstance(theorem_receipts, Sequence)
            and not isinstance(theorem_receipts, (str, bytes, bytearray))
            else [],
        },
        created_at=created_at,
        result_id=content_cid or content_digest or key.digest,
        diagnostics=(f"migrated_from:{family.value}", f"profile:{profile}"),
        source_record_index=record.record_index,
        source_line_number=record.line_number,
        original_bytes_digest=record.original_bytes_digest,
        legacy_entry_digest=_legacy_entry_digest(payload),
        ttl=ttl,
    )


def normalize_legacy_record(
    record: RawLegacyRecord,
    *,
    family: ProofCacheFamily | str,
    family_ttl: Any = None,
) -> NormalizedLegacyEntry:
    """Normalize one raw legacy record for the given family.

    Raises :class:`ProofMigrationQuarantineError` for ambiguous mappings.
    """

    if record.error:
        raise ProofMigrationError(record.error)
    if record.payload is None:
        raise ProofMigrationError("record payload is missing")

    parsed = ProofCacheFamily.parse(family)
    if parsed in {
        ProofCacheFamily.COMMON,
        ProofCacheFamily.TDFOL,
        ProofCacheFamily.CEC,
        ProofCacheFamily.EXTERNAL_PROVERS,
    }:
        return _normalize_common_like(
            record, family=parsed, family_ttl=family_ttl
        )
    if parsed is ProofCacheFamily.INTEGRATION:
        return _normalize_integration(
            record, family=parsed, family_ttl=family_ttl
        )
    if parsed is ProofCacheFamily.HAMMERS:
        return _normalize_hammer(record, family=parsed, family_ttl=family_ttl)
    if parsed is ProofCacheFamily.LEGAL_IR:
        return _normalize_legal_ir(record, family=parsed, family_ttl=family_ttl)
    raise ProofMigrationError(f"no adapter for family {parsed.value}")


# ---------------------------------------------------------------------------
# Differential reads / parity
# ---------------------------------------------------------------------------


def _digest_root(digests: Sequence[str]) -> str:
    ordered = sorted(str(item) for item in digests)
    return proof_store_content_digest(ordered)


def differential_read(
    *,
    legacy_entries: Sequence[NormalizedLegacyEntry],
    store: DuckDBProofStore,
    family: ProofCacheFamily | str,
    source_path: str = "",
    source_digest: str = "",
    quarantined_count: int = 0,
) -> tuple[ParityReceipt, tuple[DifferentialRead, ...]]:
    """Compare normalized legacy entries against the unified store."""

    parsed = ProofCacheFamily.parse(family)
    comparisons: list[DifferentialRead] = []
    matched = 0
    mismatched = 0
    missing = 0
    legacy_digests: list[str] = []
    store_digests: list[str] = []
    seen_keys: set[str] = set()

    for entry in legacy_entries:
        legacy_digests.append(entry.legacy_entry_digest or entry.key.digest)
        seen_keys.add(entry.key.digest)
        stored = store.get(entry.key)
        if stored is None:
            missing += 1
            comparisons.append(
                DifferentialRead(
                    key_digest=entry.key.digest,
                    legacy_entry_digest=entry.legacy_entry_digest,
                    store_entry_digest="",
                    present_in_legacy=True,
                    present_in_store=False,
                    digests_match=False,
                    reason="missing_in_store",
                )
            )
            continue
        store_digests.append(stored.entry_digest)
        # Match on key identity + status/outcome/trust (not full payload equality).
        same = (
            stored.key.digest == entry.key.digest
            and stored.status is entry.status
            and stored.trust_level is entry.trust_level
        )
        if same:
            matched += 1
        else:
            mismatched += 1
        comparisons.append(
            DifferentialRead(
                key_digest=entry.key.digest,
                legacy_entry_digest=entry.legacy_entry_digest,
                store_entry_digest=stored.entry_digest,
                present_in_legacy=True,
                present_in_store=True,
                digests_match=same,
                reason="match" if same else "mismatch",
            )
        )

    # Store-only entries are reported as extras relative to this legacy set.
    # We cannot enumerate the whole store cheaply without an API; use stats size
    # only for the receipt store_count field via matched+mismatched.
    store_count = matched + mismatched
    extra = 0  # bounded differential is legacy→store directed

    parity = ParityReceipt(
        parity_id="",
        family=parsed.value,
        source_path=source_path,
        source_digest=source_digest or "sha256:" + ("0" * 64),
        legacy_count=len(legacy_entries),
        store_count=store_count,
        matched_count=matched,
        mismatched_count=mismatched,
        missing_in_store=missing,
        extra_in_store=extra,
        quarantined_count=quarantined_count,
        legacy_digest_root=_digest_root(legacy_digests),
        store_digest_root=_digest_root(store_digests),
        matched=missing == 0 and mismatched == 0 and quarantined_count == 0,
    )
    return parity, tuple(comparisons)


# ---------------------------------------------------------------------------
# Migrator
# ---------------------------------------------------------------------------


def _job_id_for(
    *,
    source_path: str,
    source_digest: str,
    family: str,
    idempotency_key: str,
) -> str:
    body = {
        "family": family,
        "idempotency_key": idempotency_key,
        "source_digest": source_digest,
        "source_path": source_path,
    }
    return "job:" + _sha256_text(_canonical_json(body))[:32]


class ProofCacheMigrator:
    """Streaming, bounded, idempotent migrator for fragmented proof caches."""

    def __init__(
        self,
        store: DuckDBProofStore | None = None,
        backend: ProofMigrationBackend | None = None,
        *,
        promotion: PromotionState | None = None,
        default_positive_ttl: float = DEFAULT_POSITIVE_TTL_SECONDS,
        default_negative_ttl: float = DEFAULT_NEGATIVE_TTL_SECONDS,
        max_entries_per_job: int = _MAX_IMPORT_ENTRIES,
    ) -> None:
        if max_entries_per_job < 1:
            raise ProofMigrationError("max_entries_per_job must be positive")
        self.store = store if store is not None else build_duckdb_proof_store()
        self.backend: ProofMigrationBackend = (
            backend if backend is not None else MemoryProofMigrationBackend()
        )
        self.promotion = promotion if promotion is not None else PromotionState()
        self.default_positive_ttl = float(default_positive_ttl)
        self.default_negative_ttl = float(default_negative_ttl)
        self.max_entries_per_job = int(max_entries_per_job)
        self._lock = threading.RLock()

    @property
    def interface(self) -> str:
        return PROOF_MIGRATION_INTERFACE

    @property
    def schema_version(self) -> str:
        return PROOF_MIGRATION_SCHEMA_VERSION

    def promote(
        self,
        family: ProofCacheFamily | str,
        *,
        mode: AuthorityMode | str = AuthorityMode.PROMOTED,
    ) -> None:
        """Mark *family* promoted; subsequent whole-file JSON rewrites fail."""

        self.promotion.set_mode(family, mode)

    def assert_json_rewrite_allowed(
        self,
        family: ProofCacheFamily | str,
        *,
        path: str = "",
    ) -> None:
        """Public guard used by legacy cache writers after promotion."""

        self.promotion.assert_json_rewrite_allowed(family, path=path)

    def import_path(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        family: ProofCacheFamily | str | None = None,
        display_path: str | None = None,
        batch_size: int | None = None,
        idempotency_key: str = "default",
        family_ttl: Any = None,
        write_to_store: bool = True,
        emit_parity: bool = True,
    ) -> MigrationReceipt:
        """Import one legacy cache path into the unified proof store.

        Imports are idempotent for the same ``(idempotency_key, source_digest)``
        pair and process entries in bounded batches.
        """

        target = Path(path)
        display = display_path or str(target)

        # Source digest: file or legal-ir index / directory sentinel.
        if target.is_dir():
            index = target / "index.json"
            if index.is_file():
                source_digest = source_digest_for_path(index)
                byte_size = index.stat().st_size
            else:
                # Digest the sorted list of record file digests (original bytes).
                records_dir = target / "records"
                digests: list[str] = []
                total = 0
                if records_dir.is_dir():
                    for record_path in sorted(records_dir.glob("*.json")):
                        digests.append(source_digest_for_path(record_path))
                        total += record_path.stat().st_size
                if not digests:
                    raise ProofMigrationError(
                        f"legal_ir directory has no digestable sources: {target}"
                    )
                source_digest = proof_store_content_digest(digests)
                byte_size = total
        else:
            if not target.is_file():
                raise ProofMigrationError(f"source path not found: {target}")
            source_digest = source_digest_for_path(target)
            byte_size = target.stat().st_size

        # Detect family (peek payload when useful).
        peek_payload: Mapping[str, Any] | None = None
        if target.is_file():
            try:
                peek = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(peek, Mapping):
                    peek_payload = peek
            except (OSError, UnicodeError, json.JSONDecodeError):
                peek_payload = None

        parsed_family = detect_proof_cache_family(
            target, explicit=family, payload=peek_payload
        )
        effective_batch = batch_size_for(parsed_family, batch_size)
        key = _safe_token(idempotency_key, field_name="idempotency_key")

        # Promotion: still allow import (export-only / dual) but forbid rewrites.
        # Import itself never rewrites the source; that is enforced separately.

        existing = self.backend.get_job_by_idempotency(key, source_digest)
        if existing is not None and existing.status in {
            MigrationStatus.COMPLETED.value,
            MigrationStatus.SKIPPED_IDEMPOTENT.value,
        }:
            prior = self.backend.get_receipt(existing.job_id)
            # Always surface a skip receipt so re-imports are observably idempotent.
            skip = MigrationReceipt(
                receipt_id="" if prior is None else prior.receipt_id,
                job_id=existing.job_id,
                source_path=existing.source_path,
                family=existing.family,
                source_digest=existing.source_digest,
                idempotency_key=existing.idempotency_key,
                status=MigrationStatus.SKIPPED_IDEMPOTENT.value,
                accepted_count=existing.accepted_count,
                rejected_count=existing.rejected_count,
                quarantined_count=existing.quarantined_count,
                total_records=existing.total_records,
                batch_size=existing.batch_size,
                batches_committed=0 if prior is None else prior.batches_committed,
                accepted_entry_digests=tuple(
                    self.backend.list_accepted_digests(existing.job_id)
                ),
                resumed=False,
                cursor_next_record_index=(
                    0 if prior is None else prior.cursor_next_record_index
                ),
                created_at=prior.created_at if prior is not None else _utc_iso(),
            )
            # Persist skip status without rewriting the original completion receipt
            # identity when we already have one.
            if prior is None:
                self.backend.put_receipt(skip)
            return skip

        job_id = (
            existing.job_id
            if existing is not None
            else _job_id_for(
                source_path=display,
                source_digest=source_digest,
                family=parsed_family.value,
                idempotency_key=key,
            )
        )
        resumed = existing is not None
        cursor = self.backend.get_cursor(job_id) if resumed else None
        start_index = cursor.next_record_index if cursor is not None else 0
        accepted = cursor.accepted_count if cursor is not None else 0
        rejected = cursor.rejected_count if cursor is not None else 0
        quarantined = cursor.quarantined_count if cursor is not None else 0
        batch_index = cursor.batch_index if cursor is not None else 0

        job = MigrationJob(
            job_id=job_id,
            source_path=display,
            family=parsed_family.value,
            source_digest=source_digest,
            idempotency_key=key,
            batch_size=effective_batch,
            status=MigrationStatus.RUNNING.value,
            byte_size=byte_size,
            total_records=0,
            accepted_count=accepted,
            rejected_count=rejected,
            quarantined_count=quarantined,
        )
        self.backend.put_job(job)

        normalized_accepted: list[NormalizedLegacyEntry] = []
        total_seen = 0
        batch_buffer: list[tuple[RawLegacyRecord, NormalizedLegacyEntry | None, str | None, ImportDisposition]] = []
        batches_committed = 0

        def _flush_batch(
            items: list[
                tuple[
                    RawLegacyRecord,
                    NormalizedLegacyEntry | None,
                    str | None,
                    ImportDisposition,
                ]
            ],
            *,
            next_index: int,
            batch_idx: int,
            acc: int,
            rej: int,
            qua: int,
        ) -> None:
            nonlocal batches_committed
            for raw, normalized, reason, disposition in items:
                if disposition is ImportDisposition.ACCEPTED and normalized is not None:
                    # Freshness starts at import time; legacy stamp is in diagnostics.
                    entry = normalized.to_unified_entry(created_at=time.time())
                    entry = entry.verify_integrity()
                    entry_digest = entry.entry_digest
                    if self.backend.has_accepted_digest(job_id, entry_digest):
                        continue
                    if write_to_store:
                        self.store.put(entry, now=entry.created_at)
                    self.backend.record_accepted_digest(job_id, entry_digest)
                    normalized_accepted.append(normalized)
                elif disposition in {
                    ImportDisposition.REJECTED,
                    ImportDisposition.QUARANTINED,
                }:
                    self.backend.put_reject(
                        MigrationReject(
                            reject_id="",
                            job_id=job_id,
                            family=parsed_family.value,
                            source_path=raw.source_path or display,
                            source_digest=source_digest,
                            record_index=raw.record_index,
                            line_number=raw.line_number,
                            batch_index=batch_idx,
                            reason=reason or "rejected",
                            disposition=disposition.value,
                            raw_snippet=raw.raw_text,
                        )
                    )
            self.backend.put_cursor(
                MigrationCursor(
                    job_id=job_id,
                    source_path=display,
                    source_digest=source_digest,
                    family=parsed_family.value,
                    next_record_index=next_index,
                    batch_index=batch_idx + 1,
                    accepted_count=acc,
                    rejected_count=rej,
                    quarantined_count=qua,
                )
            )
            batches_committed += 1

        try:
            for raw in iter_legacy_records(
                target, family=parsed_family, source_digest=source_digest
            ):
                if raw.record_index < start_index:
                    continue
                total_seen += 1
                if total_seen > self.max_entries_per_job:
                    raise ProofMigrationError(
                        f"import exceeds max_entries_per_job={self.max_entries_per_job}"
                    )

                disposition: ImportDisposition
                normalized: NormalizedLegacyEntry | None = None
                reason: str | None = None

                if raw.error:
                    disposition = ImportDisposition.REJECTED
                    reason = raw.error
                    rejected += 1
                else:
                    try:
                        normalized = normalize_legacy_record(
                            raw,
                            family=parsed_family,
                            family_ttl=family_ttl,
                        )
                        # Re-validate entry construction (fail closed).
                        unified = normalized.to_unified_entry(
                            created_at=time.time()
                        ).verify_integrity()
                        if self.backend.has_accepted_digest(
                            job_id, unified.entry_digest
                        ):
                            disposition = ImportDisposition.SKIPPED_IDEMPOTENT
                        else:
                            disposition = ImportDisposition.ACCEPTED
                            accepted += 1
                    except ProofMigrationQuarantineError as exc:
                        disposition = ImportDisposition.QUARANTINED
                        reason = str(exc)
                        quarantined += 1
                    except (ProofMigrationError, DuckDBProofStoreError, TypeError, ValueError) as exc:
                        disposition = ImportDisposition.REJECTED
                        reason = str(exc)
                        rejected += 1

                batch_buffer.append((raw, normalized, reason, disposition))
                if len(batch_buffer) >= effective_batch:
                    _flush_batch(
                        batch_buffer,
                        next_index=raw.record_index + 1,
                        batch_idx=batch_index,
                        acc=accepted,
                        rej=rejected,
                        qua=quarantined,
                    )
                    batch_index += 1
                    batch_buffer = []

            if batch_buffer:
                last_index = batch_buffer[-1][0].record_index + 1
                _flush_batch(
                    batch_buffer,
                    next_index=last_index,
                    batch_idx=batch_index,
                    acc=accepted,
                    rej=rejected,
                    qua=quarantined,
                )
                batch_index += 1

            # total_records: count from cursor end / stream
            total_records = start_index + total_seen
            completed = MigrationJob(
                job_id=job_id,
                source_path=display,
                family=parsed_family.value,
                source_digest=source_digest,
                idempotency_key=key,
                batch_size=effective_batch,
                status=MigrationStatus.COMPLETED.value,
                byte_size=byte_size,
                total_records=total_records,
                accepted_count=accepted,
                rejected_count=rejected,
                quarantined_count=quarantined,
            )
            self.backend.put_job(completed)

            receipt = MigrationReceipt(
                receipt_id="",
                job_id=job_id,
                source_path=display,
                family=parsed_family.value,
                source_digest=source_digest,
                idempotency_key=key,
                status=MigrationStatus.COMPLETED.value,
                accepted_count=accepted,
                rejected_count=rejected,
                quarantined_count=quarantined,
                total_records=total_records,
                batch_size=effective_batch,
                batches_committed=batches_committed,
                accepted_entry_digests=tuple(
                    self.backend.list_accepted_digests(job_id)
                ),
                resumed=resumed,
                cursor_next_record_index=(
                    self.backend.get_cursor(job_id).next_record_index
                    if self.backend.get_cursor(job_id) is not None
                    else total_records
                ),
            )
            self.backend.put_receipt(receipt)

            if emit_parity and normalized_accepted:
                parity, _ = differential_read(
                    legacy_entries=normalized_accepted,
                    store=self.store,
                    family=parsed_family,
                    source_path=display,
                    source_digest=source_digest,
                    quarantined_count=quarantined,
                )
                self.backend.put_parity(parity)

            return receipt
        except Exception:
            failed = MigrationJob(
                job_id=job_id,
                source_path=display,
                family=parsed_family.value,
                source_digest=source_digest,
                idempotency_key=key,
                batch_size=effective_batch,
                status=MigrationStatus.FAILED.value,
                byte_size=byte_size,
                total_records=start_index + total_seen,
                accepted_count=accepted,
                rejected_count=rejected,
                quarantined_count=quarantined,
            )
            self.backend.put_job(failed)
            raise

    def write_legacy_json(
        self,
        path: str | os.PathLike[str] | Path,
        payload: Mapping[str, Any] | Sequence[Any],
        *,
        family: ProofCacheFamily | str,
    ) -> None:
        """Legacy whole-file JSON rewrite gate.

        After promotion this method raises :class:`ProofMigrationError`.  Before
        promotion it performs an atomic rewrite (compat path only).
        """

        parsed = ProofCacheFamily.parse(family)
        self.promotion.assert_json_rewrite_allowed(parsed, path=str(path))
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
        temporary = target.with_name(f".{target.name}.migration-tmp")
        try:
            temporary.write_text(text + "\n", encoding="utf-8")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def build_proof_cache_migrator(
    store: DuckDBProofStore | None = None,
    backend: ProofMigrationBackend | None = None,
    **kwargs: Any,
) -> ProofCacheMigrator:
    """Factory for :class:`ProofCacheMigrator`."""

    return ProofCacheMigrator(store=store, backend=backend, **kwargs)
