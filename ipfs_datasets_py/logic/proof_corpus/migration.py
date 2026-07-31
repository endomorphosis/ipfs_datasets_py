"""Legacy proof-corpus reader and non-authoritative quarantine (LIG-032).

Interface:

* ``LegacyProofCorpusReader@1`` — read incomplete legacy cache records, report
  every absent authority binding, and never grant authority.  Incomplete
  records remain audit-only until rebuilt under the attested envelope model.

Conflict policy (task): consume existing caches read-only; do not mutate or
delete legacy data.  Quarantine is a separate non-destructive disposition
record that marks records as non-authoritative for consumers.

This leaf does not rewrite :mod:`.model`, :mod:`.store`, :mod:`.verifier`,
or family-specific cache implementations.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable

from ..ir_core.identity import cid_v1_from_digest
from .verifier import (
    REQUIRED_AUTHORITY_BINDINGS,
    ProofVerifierError,
)

LEGACY_PROOF_CORPUS_READER_INTERFACE: Final = "LegacyProofCorpusReader@1"
LEGACY_PROOF_CORPUS_READER_SCHEMA_VERSION: Final = (
    "legacy-proof-corpus-reader/v1"
)
LEGACY_RECORD_INSPECTION_SCHEMA_VERSION: Final = (
    "legacy-record-inspection/v1"
)
LEGACY_QUARANTINE_RECORD_SCHEMA_VERSION: Final = (
    "legacy-quarantine-record/v1"
)
LEGACY_AUTHORITY_MANIFEST_SCHEMA_VERSION: Final = (
    "legacy-authority-manifest/v1"
)
LEGACY_AUTHORITY_MANIFEST_INTERFACE: Final = "LegacyAuthorityManifest@1"

# Disposition labels for quarantine / audit-only handling.
QUARANTINE_AUDIT_ONLY: Final = "audit_only"
QUARANTINE_INCOMPLETE: Final = "incomplete_legacy"
QUARANTINE_NON_AUTHORITATIVE: Final = "non_authoritative"
QUARANTINE_AWAITING_REBUILD: Final = "awaiting_rebuild"

_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")

# Alias map: legacy field names -> canonical authority binding paths.
_LEGACY_FIELD_ALIASES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "statement_digest": ("statement_digest", "statement", "goal_digest"),
        "assumption_digest": (
            "assumption_digest",
            "assumptions_digest",
            "assumptions",
        ),
        "obligation_digest": (
            "obligation_digest",
            "obligation",
            "constraint_digest",
        ),
        "source_snapshot_cid": (
            "source_snapshot_cid",
            "source_cid",
            "source_snapshot",
            "source_id",
        ),
        "build_manifest_cid": (
            "build_manifest_cid",
            "build_manifest",
            "build_cid",
        ),
        "compiler_id": ("compiler_id", "compiler", "compiler_config.compiler_id"),
        "solver_id": ("solver_id", "solver"),
        "translation_id": ("translation_id", "translation"),
        "reconstruction_id": ("reconstruction_id", "reconstruction"),
        "proof_artifact_cid": (
            "proof_artifact_cid",
            "proof_cid",
            "artifact_cid",
        ),
        "proof_bytes_digest": (
            "proof_bytes_digest",
            "proof_digest",
            "artifact_digest",
        ),
        "corpus_root_cid": ("corpus_root_cid", "corpus_root", "root_cid"),
        "revocation_root_cid": (
            "revocation_root_cid",
            "revocation_root",
        ),
        "policy_id": ("policy_id", "policy", "security_profile"),
        "attestation_kind": ("attestation_kind", "attestation", "kind"),
        "result_authority": (
            "result_authority",
            "authority",
            "authority_kind",
        ),
        "circuit.circuit_id": (
            "circuit.circuit_id",
            "circuit_id",
            "circuit.id",
        ),
        "circuit.circuit_digest": (
            "circuit.circuit_digest",
            "circuit_digest",
        ),
        "circuit.vk_id": ("circuit.vk_id", "vk_id", "verification_key_id"),
        "circuit.vk_digest": (
            "circuit.vk_digest",
            "vk_digest",
            "verification_key_digest",
        ),
        "circuit.public_inputs": (
            "circuit.public_inputs",
            "public_inputs",
        ),
        "public_inputs": ("public_inputs", "circuit.public_inputs"),
        "scope.tenant": ("scope.tenant", "tenant", "tenant_id"),
        "scope.jurisdiction": (
            "scope.jurisdiction",
            "jurisdiction",
        ),
        "temporal.effective_at": (
            "temporal.effective_at",
            "effective_at",
            "valid_from",
        ),
        "temporal.expires_at": (
            "temporal.expires_at",
            "expires_at",
            "valid_to",
            "expiry",
        ),
        "coverage": ("coverage", "coverage_complete", "covered_selectors"),
        "parent_cids": ("parent_cids", "parents", "parent_cid"),
        "security_profile": ("security_profile", "profile"),
        "backend_id": ("backend_id", "backend"),
    }
)


class LegacyProofCorpusError(ProofVerifierError):
    """Raised when a legacy reader operation cannot proceed safely."""


class LegacyDisposition(str, Enum):
    """Closed disposition vocabulary for legacy inspections."""

    AUDIT_ONLY = QUARANTINE_AUDIT_ONLY
    INCOMPLETE = QUARANTINE_INCOMPLETE
    NON_AUTHORITATIVE = QUARANTINE_NON_AUTHORITATIVE
    AWAITING_REBUILD = QUARANTINE_AWAITING_REBUILD


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise LegacyProofCorpusError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the legacy proof corpus reader"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LegacyProofCorpusError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise LegacyProofCorpusError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _unique_texts(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise LegacyProofCorpusError(
            f"{field_name} must be a sequence of strings"
        )
    try:
        items = tuple(_require_text(item, field_name) for item in values)
    except TypeError as exc:
        raise LegacyProofCorpusError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if len(items) != len(set(items)):
        raise LegacyProofCorpusError(f"{field_name} values must be unique")
    return items


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise LegacyProofCorpusError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise LegacyProofCorpusError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _lookup_path(record: Mapping[str, Any], path: str) -> Any:
    """Lookup dotted path; supports a single nesting level via dots."""

    if path in record:
        return record[path]
    if "." not in path:
        return None
    head, *rest = path.split(".")
    current: Any = record.get(head)
    for part in rest:
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence):
        return len(value) > 0
    return True


def resolve_legacy_binding(
    record: Mapping[str, Any], binding: str
) -> tuple[bool, Any, str]:
    """Resolve *binding* on a legacy record via aliases.

    Returns ``(present, value, matched_alias)``.
    """

    aliases = _LEGACY_FIELD_ALIASES.get(binding, (binding,))
    for alias in aliases:
        value = _lookup_path(record, alias)
        if _value_present(value):
            return True, value, alias
    return False, None, ""


def report_absent_bindings(
    record: Mapping[str, Any],
    *,
    required: Sequence[str] = REQUIRED_AUTHORITY_BINDINGS,
) -> tuple[str, ...]:
    """Return every required authority binding absent from *record*.

    The legacy reader always reports the full absent set; it never treats
    partial presence as authority.
    """

    if not isinstance(record, Mapping):
        raise LegacyProofCorpusError("record must be a mapping")
    absent: list[str] = []
    for binding in required:
        present, _, _ = resolve_legacy_binding(record, binding)
        if not present:
            absent.append(binding)
    return tuple(absent)


def record_content_digest(record: Mapping[str, Any]) -> str:
    """Stable content digest of a legacy record mapping."""

    return _sha256_digest(_canonical_bytes(_json_ready(dict(record))))


# ---------------------------------------------------------------------------
# Inspection / quarantine records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegacyRecordInspection:
    """Inspection result for one legacy cache record.

    ``grants_authority`` is always ``False``.  Incomplete records stay
    audit-only until rebuilt as attested envelopes.
    """

    record_id: str
    absent_bindings: tuple[str, ...]
    present_bindings: tuple[str, ...] = ()
    disposition: LegacyDisposition | str = LegacyDisposition.AUDIT_ONLY
    grants_authority: bool = False
    record_digest: str = ""
    source_path: str = ""
    notes: str = ""
    schema_version: str = LEGACY_RECORD_INSPECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _require_text(self.record_id, "record_id")
        )
        object.__setattr__(
            self,
            "absent_bindings",
            _unique_texts(self.absent_bindings, "absent_bindings"),
        )
        object.__setattr__(
            self,
            "present_bindings",
            _unique_texts(self.present_bindings, "present_bindings"),
        )
        object.__setattr__(
            self,
            "disposition",
            _parse_enum(self.disposition, LegacyDisposition, "disposition"),
        )
        if not isinstance(self.grants_authority, bool):
            raise LegacyProofCorpusError("grants_authority must be a bool")
        # Hard invariant: legacy reader never grants authority.
        if self.grants_authority:
            raise LegacyProofCorpusError(
                "LegacyRecordInspection never grants authority"
            )
        object.__setattr__(self, "grants_authority", False)
        object.__setattr__(
            self,
            "record_digest",
            _optional_text(self.record_digest, "record_digest"),
        )
        object.__setattr__(
            self, "source_path", _optional_text(self.source_path, "source_path")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != LEGACY_RECORD_INSPECTION_SCHEMA_VERSION:
            raise LegacyProofCorpusError(
                f"unsupported inspection schema: {self.schema_version!r}"
            )

    @property
    def is_complete(self) -> bool:
        return not self.absent_bindings

    @property
    def is_audit_only(self) -> bool:
        return True  # Always audit-only until rebuild.

    def to_dict(self) -> dict[str, Any]:
        return {
            "absent_bindings": list(self.absent_bindings),
            "disposition": self.disposition.value,
            "grants_authority": False,
            "is_complete": self.is_complete,
            "notes": self.notes,
            "present_bindings": list(self.present_bindings),
            "record_digest": self.record_digest,
            "record_id": self.record_id,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "LegacyRecordInspection":
        payload = dict(_as_mapping(value, "legacy record inspection"))
        payload.pop("is_complete", None)
        _reject_unknown(
            payload,
            frozenset(
                {
                    "absent_bindings",
                    "disposition",
                    "grants_authority",
                    "notes",
                    "present_bindings",
                    "record_digest",
                    "record_id",
                    "schema_version",
                    "source_path",
                }
            ),
            "legacy record inspection",
        )
        return cls(
            record_id=payload.get("record_id", ""),
            absent_bindings=tuple(payload.get("absent_bindings", ()) or ()),
            present_bindings=tuple(payload.get("present_bindings", ()) or ()),
            disposition=payload.get(
                "disposition", LegacyDisposition.AUDIT_ONLY.value
            ),
            grants_authority=False,
            record_digest=payload.get("record_digest", ""),
            source_path=payload.get("source_path", ""),
            notes=payload.get("notes", ""),
            schema_version=payload.get(
                "schema_version", LEGACY_RECORD_INSPECTION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class LegacyQuarantineRecord:
    """Non-destructive quarantine disposition for a legacy cache record.

    The source record is never modified or deleted.  Quarantine is an
    additive audit artifact that blocks authority use.
    """

    record_id: str
    absent_bindings: tuple[str, ...]
    disposition: LegacyDisposition | str = LegacyDisposition.AWAITING_REBUILD
    grants_authority: bool = False
    record_digest: str = ""
    source_path: str = ""
    reason: str = "incomplete_legacy_authority_bindings"
    quarantine_digest: str = ""
    quarantine_cid: str = ""
    schema_version: str = LEGACY_QUARANTINE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _require_text(self.record_id, "record_id")
        )
        object.__setattr__(
            self,
            "absent_bindings",
            _unique_texts(self.absent_bindings, "absent_bindings"),
        )
        object.__setattr__(
            self,
            "disposition",
            _parse_enum(self.disposition, LegacyDisposition, "disposition"),
        )
        if not isinstance(self.grants_authority, bool):
            raise LegacyProofCorpusError("grants_authority must be a bool")
        if self.grants_authority:
            raise LegacyProofCorpusError(
                "LegacyQuarantineRecord never grants authority"
            )
        object.__setattr__(self, "grants_authority", False)
        object.__setattr__(
            self,
            "record_digest",
            _optional_text(self.record_digest, "record_digest"),
        )
        object.__setattr__(
            self, "source_path", _optional_text(self.source_path, "source_path")
        )
        object.__setattr__(
            self, "reason", _require_text(self.reason, "reason")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != LEGACY_QUARANTINE_RECORD_SCHEMA_VERSION:
            raise LegacyProofCorpusError(
                f"unsupported quarantine schema: {self.schema_version!r}"
            )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.quarantine_digest and self.quarantine_digest != digest:
            raise LegacyProofCorpusError(
                "quarantine_digest does not match payload"
            )
        if self.quarantine_cid and self.quarantine_cid != cid:
            raise LegacyProofCorpusError(
                "quarantine_cid does not match payload"
            )
        object.__setattr__(self, "quarantine_digest", digest)
        object.__setattr__(self, "quarantine_cid", cid)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "absent_bindings": list(self.absent_bindings),
            "disposition": self.disposition.value,
            "grants_authority": False,
            "reason": self.reason,
            "record_digest": self.record_digest,
            "record_id": self.record_id,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["quarantine_cid"] = self.quarantine_cid
        payload["quarantine_digest"] = self.quarantine_digest
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "LegacyQuarantineRecord":
        payload = dict(_as_mapping(value, "legacy quarantine record"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "absent_bindings",
                    "disposition",
                    "grants_authority",
                    "quarantine_cid",
                    "quarantine_digest",
                    "reason",
                    "record_digest",
                    "record_id",
                    "schema_version",
                    "source_path",
                }
            ),
            "legacy quarantine record",
        )
        return cls(
            record_id=payload.get("record_id", ""),
            absent_bindings=tuple(payload.get("absent_bindings", ()) or ()),
            disposition=payload.get(
                "disposition", LegacyDisposition.AWAITING_REBUILD.value
            ),
            grants_authority=False,
            record_digest=payload.get("record_digest", ""),
            source_path=payload.get("source_path", ""),
            reason=payload.get(
                "reason", "incomplete_legacy_authority_bindings"
            ),
            quarantine_digest=payload.get("quarantine_digest", ""),
            quarantine_cid=payload.get("quarantine_cid", ""),
            schema_version=payload.get(
                "schema_version", LEGACY_QUARANTINE_RECORD_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


@dataclass
class LegacyProofCorpusReader:
    """Read-only legacy cache inspector (LegacyProofCorpusReader@1).

    Never grants authority.  Reports every absent binding on every record.
    Quarantine is non-destructive and held in memory (or optional side path).
    """

    required_bindings: tuple[str, ...] = REQUIRED_AUTHORITY_BINDINGS
    quarantine: list[LegacyQuarantineRecord] = field(default_factory=list)
    inspections: list[LegacyRecordInspection] = field(default_factory=list)
    schema_version: str = LEGACY_PROOF_CORPUS_READER_SCHEMA_VERSION
    interface: str = LEGACY_PROOF_CORPUS_READER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_bindings",
            _unique_texts(self.required_bindings, "required_bindings"),
        )
        if not self.required_bindings:
            raise LegacyProofCorpusError(
                "required_bindings must not be empty"
            )
        if self.schema_version != LEGACY_PROOF_CORPUS_READER_SCHEMA_VERSION:
            raise LegacyProofCorpusError(
                f"unsupported reader schema: {self.schema_version!r}"
            )
        if self.interface != LEGACY_PROOF_CORPUS_READER_INTERFACE:
            raise LegacyProofCorpusError(
                f"unsupported reader interface: {self.interface!r}"
            )

    def inspect_record(
        self,
        record: Mapping[str, Any],
        *,
        record_id: str = "",
        source_path: str = "",
        notes: str = "",
    ) -> LegacyRecordInspection:
        """Inspect one legacy record and report every absent binding."""

        if not isinstance(record, Mapping):
            raise LegacyProofCorpusError("record must be a mapping")
        rid = record_id or str(
            record.get("record_id")
            or record.get("id")
            or record.get("content_cid")
            or record.get("source_id")
            or ""
        )
        if not rid:
            rid = record_content_digest(record)

        absent = report_absent_bindings(
            record, required=self.required_bindings
        )
        present = tuple(
            binding
            for binding in self.required_bindings
            if binding not in absent
        )
        if absent:
            disposition = LegacyDisposition.INCOMPLETE
            note = notes or (
                "legacy record missing authority bindings; audit-only"
            )
        else:
            # Even "complete" legacy shapes never grant authority without
            # consumer rebuild under AttestedProofEnvelope@1.
            disposition = LegacyDisposition.NON_AUTHORITATIVE
            note = notes or (
                "legacy record is non-authoritative until attested rebuild"
            )

        inspection = LegacyRecordInspection(
            record_id=rid,
            absent_bindings=absent,
            present_bindings=present,
            disposition=disposition,
            grants_authority=False,
            record_digest=record_content_digest(record),
            source_path=source_path,
            notes=note,
        )
        self.inspections.append(inspection)
        return inspection

    def quarantine_record(
        self,
        record: Mapping[str, Any],
        *,
        record_id: str = "",
        source_path: str = "",
        reason: str = "incomplete_legacy_authority_bindings",
    ) -> LegacyQuarantineRecord:
        """Quarantine *record* without mutating the source payload.

        Returns a content-addressed quarantine disposition.  The original
        record mapping is left unchanged.
        """

        inspection = self.inspect_record(
            record, record_id=record_id, source_path=source_path
        )
        # Always quarantine: legacy never grants authority.
        disposition = (
            LegacyDisposition.AWAITING_REBUILD
            if inspection.absent_bindings
            else LegacyDisposition.NON_AUTHORITATIVE
        )
        quarantine = LegacyQuarantineRecord(
            record_id=inspection.record_id,
            absent_bindings=inspection.absent_bindings,
            disposition=disposition,
            grants_authority=False,
            record_digest=inspection.record_digest,
            source_path=source_path,
            reason=reason
            if inspection.absent_bindings
            else "legacy_non_authoritative_until_rebuild",
        )
        self.quarantine.append(quarantine)
        return quarantine

    def inspect_many(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        id_field: str = "record_id",
    ) -> tuple[LegacyRecordInspection, ...]:
        results: list[LegacyRecordInspection] = []
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise LegacyProofCorpusError(
                    f"records[{index}] must be a mapping"
                )
            rid = str(record.get(id_field) or record.get("id") or f"record-{index}")
            results.append(self.inspect_record(record, record_id=rid))
        return tuple(results)

    def quarantine_incomplete(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        id_field: str = "record_id",
    ) -> tuple[LegacyQuarantineRecord, ...]:
        """Quarantine every record (incomplete or complete-but-legacy)."""

        results: list[LegacyQuarantineRecord] = []
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise LegacyProofCorpusError(
                    f"records[{index}] must be a mapping"
                )
            rid = str(record.get(id_field) or record.get("id") or f"record-{index}")
            results.append(
                self.quarantine_record(record, record_id=rid)
            )
        return tuple(results)

    def load_json_path(self, path: str | Path) -> dict[str, Any]:
        """Load a JSON mapping from *path* (read-only)."""

        file_path = Path(path)
        try:
            raw = file_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LegacyProofCorpusError(
                f"cannot load legacy record from {file_path}: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise LegacyProofCorpusError(
                f"legacy record at {file_path} must be a JSON object"
            )
        return dict(payload)

    def inspect_path(self, path: str | Path) -> LegacyRecordInspection:
        """Inspect a legacy JSON record at *path* without modifying it."""

        file_path = Path(path)
        record = self.load_json_path(file_path)
        return self.inspect_record(
            record,
            record_id=str(
                record.get("record_id")
                or record.get("id")
                or file_path.stem
            ),
            source_path=str(file_path),
        )

    def grants_authority_for(self, record: Mapping[str, Any]) -> bool:
        """Always ``False`` — legacy reader never grants authority."""

        _ = record
        return False

    def any_authority_granted(self) -> bool:
        """Return whether any inspection granted authority (always False)."""

        return False

    def quarantine_summary(self) -> dict[str, Any]:
        return {
            "grants_authority": False,
            "inspection_count": len(self.inspections),
            "interface": self.interface,
            "quarantine_count": len(self.quarantine),
            "quarantine_ids": [item.record_id for item in self.quarantine],
            "required_bindings": list(self.required_bindings),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "grants_authority": False,
            "inspections": [item.to_dict() for item in self.inspections],
            "interface": self.interface,
            "quarantine": [item.to_dict() for item in self.quarantine],
            "required_bindings": list(self.required_bindings),
            "schema_version": self.schema_version,
        }


def load_legacy_authority_manifest(
    path: str | Path | None = None,
    *,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and validate a legacy authority manifest fixture.

    Either *path* or *payload* must be provided.  Returns the normalized
    manifest mapping.
    """

    if payload is None:
        if path is None:
            raise LegacyProofCorpusError(
                "load_legacy_authority_manifest requires path or payload"
            )
        file_path = Path(path)
        try:
            raw = file_path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LegacyProofCorpusError(
                f"cannot load legacy authority manifest from {file_path}: {exc}"
            ) from exc
        if not isinstance(loaded, Mapping):
            raise LegacyProofCorpusError(
                "legacy authority manifest must be a JSON object"
            )
        payload = loaded

    data = dict(_as_mapping(payload, "legacy authority manifest"))
    interface = data.get("interface", LEGACY_AUTHORITY_MANIFEST_INTERFACE)
    if interface != LEGACY_AUTHORITY_MANIFEST_INTERFACE:
        raise LegacyProofCorpusError(
            f"unsupported legacy authority manifest interface: {interface!r}"
        )
    schema = data.get(
        "schema_version", LEGACY_AUTHORITY_MANIFEST_SCHEMA_VERSION
    )
    if schema != LEGACY_AUTHORITY_MANIFEST_SCHEMA_VERSION:
        raise LegacyProofCorpusError(
            f"unsupported legacy authority manifest schema: {schema!r}"
        )
    required = data.get("required_bindings")
    if not isinstance(required, Sequence) or isinstance(
        required, (str, bytes, bytearray)
    ):
        raise LegacyProofCorpusError(
            "required_bindings must be a sequence of strings"
        )
    required_tuple = tuple(str(item) for item in required)
    if not required_tuple:
        raise LegacyProofCorpusError("required_bindings must not be empty")
    samples = data.get("samples", {})
    if samples is not None and not isinstance(samples, Mapping):
        raise LegacyProofCorpusError("samples must be a mapping when present")
    return {
        "description": str(data.get("description") or ""),
        "interface": interface,
        "required_bindings": list(required_tuple),
        "samples": dict(samples or {}),
        "schema_version": schema,
        "quarantine_policy": dict(data.get("quarantine_policy") or {}),
    }


def inspect_manifest_samples(
    manifest: Mapping[str, Any],
    *,
    reader: LegacyProofCorpusReader | None = None,
) -> tuple[LegacyRecordInspection, ...]:
    """Inspect all sample records declared in a legacy authority manifest."""

    normalized = load_legacy_authority_manifest(payload=manifest)
    reader = reader or LegacyProofCorpusReader(
        required_bindings=tuple(normalized["required_bindings"])
    )
    inspections: list[LegacyRecordInspection] = []
    samples = normalized.get("samples") or {}
    for sample_id, sample in samples.items():
        if not isinstance(sample, Mapping):
            raise LegacyProofCorpusError(
                f"sample {sample_id!r} must be a mapping"
            )
        record = sample.get("record")
        if not isinstance(record, Mapping):
            # Allow inline sample fields as the record itself.
            record = {
                key: value
                for key, value in sample.items()
                if key not in {"expected_absent", "description", "record"}
            }
        inspection = reader.inspect_record(
            record,
            record_id=str(sample.get("record_id") or sample_id),
            source_path=str(sample.get("source_path") or ""),
            notes=str(sample.get("description") or ""),
        )
        expected_absent = sample.get("expected_absent")
        if expected_absent is not None:
            expected_set = set(expected_absent)
            actual_set = set(inspection.absent_bindings)
            if not expected_set.issubset(actual_set):
                raise LegacyProofCorpusError(
                    f"sample {sample_id!r} expected absent bindings "
                    f"{sorted(expected_set - actual_set)} were present"
                )
        inspections.append(inspection)
    return tuple(inspections)


def build_legacy_proof_corpus_reader(
    **kwargs: Any,
) -> LegacyProofCorpusReader:
    """Keyword sugar for :class:`LegacyProofCorpusReader`."""

    return LegacyProofCorpusReader(**kwargs)


def default_legacy_authority_manifest_path() -> Path:
    """Return the packaged fixture path for the legacy authority manifest."""

    # tests/fixtures/proof_corpus/legacy_authority_manifest.json relative to repo.
    here = Path(__file__).resolve()
    # ipfs_datasets_py/logic/proof_corpus/migration.py -> repo root is parents[3]
    repo_root = here.parents[3]
    return (
        repo_root
        / "tests"
        / "fixtures"
        / "proof_corpus"
        / "legacy_authority_manifest.json"
    )


__all__ = [
    "LEGACY_AUTHORITY_MANIFEST_INTERFACE",
    "LEGACY_AUTHORITY_MANIFEST_SCHEMA_VERSION",
    "LEGACY_PROOF_CORPUS_READER_INTERFACE",
    "LEGACY_PROOF_CORPUS_READER_SCHEMA_VERSION",
    "LEGACY_QUARANTINE_RECORD_SCHEMA_VERSION",
    "LEGACY_RECORD_INSPECTION_SCHEMA_VERSION",
    "QUARANTINE_AUDIT_ONLY",
    "QUARANTINE_AWAITING_REBUILD",
    "QUARANTINE_INCOMPLETE",
    "QUARANTINE_NON_AUTHORITATIVE",
    "LegacyDisposition",
    "LegacyProofCorpusError",
    "LegacyProofCorpusReader",
    "LegacyQuarantineRecord",
    "LegacyRecordInspection",
    "build_legacy_proof_corpus_reader",
    "default_legacy_authority_manifest_path",
    "inspect_manifest_samples",
    "load_legacy_authority_manifest",
    "record_content_digest",
    "report_absent_bindings",
    "resolve_legacy_binding",
]
