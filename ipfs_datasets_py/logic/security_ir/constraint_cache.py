"""Content-addressed Security IR constraint cache (SecurityConstraintCache@1).

Caches formalized Security IR constraints (and optional policy decisions) so a
gate or supervisor can load a constraint set by CID and profile without
re-adapting legacy models on every call.

Integrity is fail-closed:

* every on-disk envelope is rehashed on load and rejected on digest mismatch;
* declaration identity is recomputed from the stored payload and must match the
  recorded digest and CID;
* extensions outside the known vocabulary allowlist (crypto-exchange, Xaman,
  plus any caller-registered vocabularies) are rejected on put and on reload.

This module does not rewrite formalization adapters.  It consumes immutable
:class:`~ipfs_datasets_py.logic.security_ir.model.SecurityIR` declarations and
optional :class:`~ipfs_datasets_py.logic.formalization.compiler.FormalizationArtifact`
outputs produced by the shared formalization path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ..formalization.compiler import FormalizationArtifact
from ..ir_core.identity import cid_v1_from_digest
from ..ir_core.protocols import AuthorityKind, BoundedResult, PolicyDecision
from .exchange.vocabulary import (
    EXCHANGE_EXTENSION_ID,
    EXCHANGE_VOCABULARY,
    EXCHANGE_VOCABULARY_VERSION,
)
from .formalization_adapter import (
    SecurityIRFormalizationAdapter,
    SecurityIRFormalizationAdapterError,
    adapt_security_ir,
)
from .model import SecurityExtension, SecurityIR, SecurityIRValidationError
from .xaman.config import (
    XAMAN_EXTENSION_ID,
    XAMAN_VOCABULARY,
    XAMAN_VOCABULARY_VERSION,
)


SECURITY_CONSTRAINT_CACHE_INTERFACE: Final = "SecurityConstraintCache@1"
SECURITY_CONSTRAINT_CACHE_SCHEMA_VERSION: Final = "security-constraint-cache/v1"
SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION: Final = "security-constraint-record/v1"
SECURITY_CONSTRAINT_INDEX_SCHEMA_VERSION: Final = "security-constraint-index/v1"

_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")

# Built-in domain vocabularies that the cache treats as reviewed/known.
KNOWN_SECURITY_EXTENSION_VOCABULARIES: Final[frozenset[str]] = frozenset(
    {
        EXCHANGE_VOCABULARY,
        XAMAN_VOCABULARY,
    }
)

_KNOWN_EXTENSION_IDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        EXCHANGE_VOCABULARY: frozenset({EXCHANGE_EXTENSION_ID}),
        XAMAN_VOCABULARY: frozenset({XAMAN_EXTENSION_ID}),
    }
)

_KNOWN_EXTENSION_VERSIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        EXCHANGE_VOCABULARY: frozenset({EXCHANGE_VOCABULARY_VERSION}),
        XAMAN_VOCABULARY: frozenset({XAMAN_VOCABULARY_VERSION}),
    }
)

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "content_cid",
        "content_digest",
        "declaration",
        "declaration_cid",
        "declaration_digest",
        "declaration_id",
        "extension_ids",
        "extension_vocabularies",
        "policy_decisions",
        "profile",
        "schema_version",
    }
)


class SecurityConstraintCacheError(ValueError):
    """Raised when a constraint cache operation cannot proceed safely."""


class UnknownSecurityExtensionError(SecurityConstraintCacheError):
    """Raised when a declaration carries an extension outside the allowlist."""


class SecurityConstraintIntegrityError(SecurityConstraintCacheError):
    """Raised when a stored envelope fails integrity verification."""


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


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SecurityConstraintCacheError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _require_profile(value: Any) -> str:
    profile = _require_text(value, "profile")
    if not _PROFILE_RE.fullmatch(profile):
        raise SecurityConstraintCacheError(
            "profile must be a lowercase hyphenated identifier"
        )
    return profile


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if not _DIGEST_RE.fullmatch(digest):
        raise SecurityConstraintCacheError(
            f"{field_name} must be a sha256:<hex> digest"
        )
    return digest


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SecurityConstraintCacheError(f"{label} must be a mapping")
    return value


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
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
    raise SecurityConstraintCacheError(
        f"value of type {type(value).__name__} is not JSON-serializable for the cache"
    )


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_bytes(payload)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def known_extension_vocabularies(
    extra: Iterable[str] | None = None,
) -> frozenset[str]:
    """Return the effective known-extension vocabulary allowlist."""

    values = set(KNOWN_SECURITY_EXTENSION_VOCABULARIES)
    if extra is not None:
        for item in extra:
            values.add(_require_text(item, "known extension vocabulary"))
    return frozenset(values)


def validate_extensions_known(
    declaration: SecurityIR,
    *,
    known_vocabularies: Iterable[str] | None = None,
    known_extension_ids: Mapping[str, Iterable[str]] | None = None,
    known_versions: Mapping[str, Iterable[str]] | None = None,
) -> tuple[SecurityExtension, ...]:
    """Fail closed when any declaration extension is outside the allowlist."""

    if not isinstance(declaration, SecurityIR):
        raise SecurityConstraintCacheError("declaration must be a SecurityIR")
    try:
        declaration.validate()
    except SecurityIRValidationError as exc:
        raise SecurityConstraintCacheError(
            f"invalid Security IR declaration: {exc}"
        ) from exc

    allowed = known_extension_vocabularies(known_vocabularies)
    id_allow = {
        key: frozenset(values)
        for key, values in {
            **dict(_KNOWN_EXTENSION_IDS),
            **{
                _require_text(k, "known_extension_ids key"): values
                for k, values in (known_extension_ids or {}).items()
            },
        }.items()
    }
    version_allow = {
        key: frozenset(values)
        for key, values in {
            **dict(_KNOWN_EXTENSION_VERSIONS),
            **{
                _require_text(k, "known_versions key"): values
                for k, values in (known_versions or {}).items()
            },
        }.items()
    }

    for extension in declaration.extensions:
        if extension.vocabulary not in allowed:
            raise UnknownSecurityExtensionError(
                "unknown security extension vocabulary "
                f"{extension.vocabulary!r} for extension "
                f"{extension.extension_id!r}; fail closed"
            )
        allowed_ids = id_allow.get(extension.vocabulary)
        if allowed_ids is not None and extension.extension_id not in allowed_ids:
            raise UnknownSecurityExtensionError(
                "unknown security extension id "
                f"{extension.extension_id!r} for vocabulary "
                f"{extension.vocabulary!r}; fail closed"
            )
        allowed_versions = version_allow.get(extension.vocabulary)
        if (
            allowed_versions is not None
            and extension.version not in allowed_versions
        ):
            raise UnknownSecurityExtensionError(
                "unsupported security extension version "
                f"{extension.version!r} for vocabulary "
                f"{extension.vocabulary!r}; fail closed"
            )
    return declaration.extensions


def _normalize_policy_decision(value: Any) -> dict[str, Any]:
    """Normalize a policy decision while preserving AuthorityKind."""

    if isinstance(value, PolicyDecision):
        payload = value.to_dict()
    elif isinstance(value, BoundedResult):
        if value.result_type != PolicyDecision.result_type:
            raise SecurityConstraintCacheError(
                "only policy_decision results may be attached to the constraint cache"
            )
        payload = value.to_dict()
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise SecurityConstraintCacheError(
            "policy decision must be a PolicyDecision or mapping"
        )

    # Reparse through the typed contract so authority kind cannot drift.
    try:
        decision = PolicyDecision.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise SecurityConstraintCacheError(
            f"invalid policy decision payload: {exc}"
        ) from exc
    if decision.authority.kind is not AuthorityKind.POLICY_APPROVAL:
        raise SecurityConstraintCacheError(
            "policy decision authority must be policy_approval"
        )
    return decision.to_dict()


def _normalize_artifact(
    artifact: FormalizationArtifact | Mapping[str, Any] | None,
    declaration: SecurityIR,
) -> dict[str, Any]:
    if artifact is None:
        try:
            produced = adapt_security_ir(declaration)
        except (
            SecurityIRFormalizationAdapterError,
            TypeError,
            ValueError,
        ) as exc:
            raise SecurityConstraintCacheError(
                f"failed to formalize security declaration: {exc}"
            ) from exc
        artifact = produced
    if isinstance(artifact, FormalizationArtifact):
        payload = artifact.to_dict()
        produced_artifact = artifact
    else:
        payload = dict(_as_mapping(artifact, "artifact"))
        try:
            produced_artifact = FormalizationArtifact.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise SecurityConstraintCacheError(
                f"invalid formalization artifact: {exc}"
            ) from exc
        payload = produced_artifact.to_dict()

    if produced_artifact.declaration_id != declaration.declaration_id:
        raise SecurityConstraintCacheError(
            "artifact declaration_id does not match the cached declaration"
        )
    if produced_artifact.declaration_digest != declaration.digest:
        raise SecurityConstraintCacheError(
            "artifact declaration_digest does not match the cached declaration"
        )
    if produced_artifact.domain != "security":
        raise SecurityConstraintCacheError(
            "constraint cache only accepts security-domain formalization artifacts"
        )
    return payload


@dataclass(frozen=True, slots=True)
class SecurityConstraintRecord:
    """One content-addressed constraint set for a declaration and profile."""

    declaration_id: str
    declaration_digest: str
    declaration_cid: str
    profile: str
    declaration: Mapping[str, Any]
    artifact: Mapping[str, Any]
    policy_decisions: tuple[Mapping[str, Any], ...] = ()
    extension_ids: tuple[str, ...] = ()
    extension_vocabularies: tuple[str, ...] = ()
    content_digest: str = ""
    content_cid: str = ""
    schema_version: str = SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "declaration_id",
            _require_text(self.declaration_id, "declaration_id"),
        )
        object.__setattr__(
            self,
            "declaration_digest",
            _require_digest(self.declaration_digest, "declaration_digest"),
        )
        object.__setattr__(
            self,
            "declaration_cid",
            _require_text(self.declaration_cid, "declaration_cid"),
        )
        object.__setattr__(self, "profile", _require_profile(self.profile))
        declaration = dict(_as_mapping(self.declaration, "declaration"))
        artifact = dict(_as_mapping(self.artifact, "artifact"))
        object.__setattr__(self, "declaration", MappingProxyType(declaration))
        object.__setattr__(self, "artifact", MappingProxyType(artifact))

        decisions = tuple(
            MappingProxyType(dict(_as_mapping(item, "policy_decision")))
            for item in self.policy_decisions
        )
        object.__setattr__(self, "policy_decisions", decisions)

        ext_ids = tuple(
            _require_text(item, "extension_ids") for item in self.extension_ids
        )
        ext_vocabs = tuple(
            _require_text(item, "extension_vocabularies")
            for item in self.extension_vocabularies
        )
        if len(ext_ids) != len(set(ext_ids)):
            raise SecurityConstraintCacheError("extension_ids must be unique")
        if len(ext_vocabs) != len(set(ext_vocabs)):
            raise SecurityConstraintCacheError(
                "extension_vocabularies must be unique"
            )
        object.__setattr__(self, "extension_ids", ext_ids)
        object.__setattr__(self, "extension_vocabularies", tuple(sorted(ext_vocabs)))

        if self.schema_version != SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION:
            raise SecurityConstraintCacheError(
                f"unsupported constraint record schema: {self.schema_version!r}"
            )

        # Bind identity after field normalization.
        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise SecurityConstraintIntegrityError(
                    "constraint record content_digest does not match payload"
                )
        if self.content_cid:
            recorded_cid = _require_text(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise SecurityConstraintIntegrityError(
                    "constraint record content_cid does not match payload"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

        # Structural integrity only; vocabulary allowlisting is a cache policy.
        self.verify_integrity(check_extensions=False)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "artifact": _json_ready(dict(self.artifact)),
            "declaration": _json_ready(dict(self.declaration)),
            "declaration_cid": self.declaration_cid,
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "extension_ids": list(self.extension_ids),
            "extension_vocabularies": list(self.extension_vocabularies),
            "policy_decisions": [_json_ready(dict(item)) for item in self.policy_decisions],
            "profile": self.profile,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    def security_ir(self) -> SecurityIR:
        """Return the stored declaration as a validated SecurityIR."""

        try:
            return SecurityIR.from_dict(dict(self.declaration))
        except (TypeError, ValueError, SecurityIRValidationError) as exc:
            raise SecurityConstraintIntegrityError(
                f"stored declaration is not a valid SecurityIR: {exc}"
            ) from exc

    def formalization_artifact(self) -> FormalizationArtifact:
        """Return the stored formalization artifact."""

        try:
            return FormalizationArtifact.from_dict(dict(self.artifact))
        except (TypeError, ValueError) as exc:
            raise SecurityConstraintIntegrityError(
                f"stored artifact is not a valid FormalizationArtifact: {exc}"
            ) from exc

    def policy_decision_results(self) -> tuple[PolicyDecision, ...]:
        """Return typed policy decisions attached to this constraint set."""

        results: list[PolicyDecision] = []
        for item in self.policy_decisions:
            try:
                results.append(PolicyDecision.from_dict(dict(item)))
            except (TypeError, ValueError) as exc:
                raise SecurityConstraintIntegrityError(
                    f"stored policy decision is invalid: {exc}"
                ) from exc
        return tuple(results)

    def verify_integrity(
        self,
        *,
        known_vocabularies: Iterable[str] | None = None,
        check_extensions: bool = True,
    ) -> "SecurityConstraintRecord":
        """Recompute declaration identity and optionally enforce extension policy."""

        declaration = self.security_ir()
        if declaration.declaration_id != self.declaration_id:
            raise SecurityConstraintIntegrityError(
                "stored declaration_id does not match SecurityIR payload"
            )
        if declaration.digest != self.declaration_digest:
            raise SecurityConstraintIntegrityError(
                "stored declaration_digest does not match recomputed identity"
            )
        if declaration.cid != self.declaration_cid:
            raise SecurityConstraintIntegrityError(
                "stored declaration_cid does not match recomputed identity"
            )
        expected_ids = tuple(
            sorted({item.extension_id for item in declaration.extensions})
        )
        expected_vocabs = tuple(
            sorted({item.vocabulary for item in declaration.extensions})
        )
        if tuple(sorted(self.extension_ids)) != expected_ids:
            raise SecurityConstraintIntegrityError(
                "stored extension_ids do not match declaration extensions"
            )
        if self.extension_vocabularies != expected_vocabs:
            raise SecurityConstraintIntegrityError(
                "stored extension_vocabularies do not match declaration extensions"
            )
        if check_extensions:
            validate_extensions_known(
                declaration, known_vocabularies=known_vocabularies
            )
        # Artifact binding already checked at construction; re-check after reload.
        artifact = self.formalization_artifact()
        if artifact.declaration_digest != declaration.digest:
            raise SecurityConstraintIntegrityError(
                "artifact declaration_digest drifted from declaration identity"
            )
        for decision in self.policy_decision_results():
            if decision.authority.kind is not AuthorityKind.POLICY_APPROVAL:
                raise SecurityConstraintIntegrityError(
                    "policy decision lost policy_approval authority under reload"
                )
            if decision.declaration_id and (
                decision.declaration_id != self.declaration_id
            ):
                raise SecurityConstraintIntegrityError(
                    "policy decision declaration_id does not match constraint set"
                )
        return self

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityConstraintRecord":
        value = _as_mapping(value, "constraint record")
        unknown = sorted(set(value) - _RECORD_FIELDS)
        if unknown:
            raise SecurityConstraintCacheError(
                "unknown constraint record field(s): " + ", ".join(unknown)
            )
        return cls(
            declaration_id=value.get("declaration_id", ""),
            declaration_digest=value.get("declaration_digest", ""),
            declaration_cid=value.get("declaration_cid", ""),
            profile=value.get("profile", ""),
            declaration=value.get("declaration", {}),
            artifact=value.get("artifact", {}),
            policy_decisions=tuple(value.get("policy_decisions", ())),
            extension_ids=tuple(value.get("extension_ids", ())),
            extension_vocabularies=tuple(value.get("extension_vocabularies", ())),
            content_digest=value.get("content_digest", ""),
            content_cid=value.get("content_cid", ""),
            schema_version=value.get(
                "schema_version", SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION
            ),
        )

    @classmethod
    def build(
        cls,
        declaration: SecurityIR | Mapping[str, Any],
        *,
        profile: str,
        artifact: FormalizationArtifact | Mapping[str, Any] | None = None,
        policy_decisions: Sequence[Any] = (),
        known_vocabularies: Iterable[str] | None = None,
    ) -> "SecurityConstraintRecord":
        """Build a verified record from a declaration and optional artifact."""

        if isinstance(declaration, SecurityIR):
            security_ir = declaration
        else:
            try:
                security_ir = SecurityIR.from_dict(
                    _as_mapping(declaration, "declaration")
                )
            except (TypeError, ValueError, SecurityIRValidationError) as exc:
                raise SecurityConstraintCacheError(
                    f"invalid Security IR declaration: {exc}"
                ) from exc
        validate_extensions_known(
            security_ir, known_vocabularies=known_vocabularies
        )
        artifact_payload = _normalize_artifact(artifact, security_ir)
        decision_payloads = tuple(
            _normalize_policy_decision(item) for item in policy_decisions
        )
        for decision in decision_payloads:
            declaration_id = decision.get("declaration_id", "")
            if declaration_id and declaration_id != security_ir.declaration_id:
                raise SecurityConstraintCacheError(
                    "policy decision declaration_id does not match constraint set"
                )
        return cls(
            declaration_id=security_ir.declaration_id,
            declaration_digest=security_ir.digest,
            declaration_cid=security_ir.cid,
            profile=_require_profile(profile),
            declaration=security_ir.to_dict(),
            artifact=artifact_payload,
            policy_decisions=decision_payloads,
            extension_ids=tuple(
                sorted({item.extension_id for item in security_ir.extensions})
            ),
            extension_vocabularies=tuple(
                sorted({item.vocabulary for item in security_ir.extensions})
            ),
        )


@dataclass
class SecurityConstraintCache:
    """Filesystem- or memory-backed Security constraint cache.

    Records are content-addressed by their envelope digest.  The optional
    profile index lets callers retrieve the constraint set for a named gate
    profile without remembering the CID.
    """

    root: Path | None = None
    known_vocabularies: frozenset[str] = field(
        default_factory=lambda: frozenset(KNOWN_SECURITY_EXTENSION_VOCABULARIES)
    )
    formalization_adapter: SecurityIRFormalizationAdapter | None = None
    _records: dict[str, SecurityConstraintRecord] = field(
        default_factory=dict, init=False, repr=False
    )
    _profile_index: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.root is not None:
            object.__setattr__(self, "root", Path(self.root))
        object.__setattr__(
            self,
            "known_vocabularies",
            known_extension_vocabularies(self.known_vocabularies),
        )
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
            self.reload()

    @property
    def interface(self) -> str:
        return SECURITY_CONSTRAINT_CACHE_INTERFACE

    @property
    def schema_version(self) -> str:
        return SECURITY_CONSTRAINT_CACHE_SCHEMA_VERSION

    def _records_dir(self) -> Path | None:
        if self.root is None:
            return None
        path = self.root / "records"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _index_path(self) -> Path | None:
        if self.root is None:
            return None
        return self.root / "index.json"

    def _record_path(self, content_cid: str) -> Path | None:
        records_dir = self._records_dir()
        if records_dir is None:
            return None
        # CIDs are filesystem-safe base32 strings under the fixed CID profile.
        safe = content_cid.replace("/", "_")
        return records_dir / f"{safe}.json"

    def put(
        self,
        declaration: SecurityIR
        | Mapping[str, Any]
        | SecurityConstraintRecord
        | FormalizationArtifact,
        *,
        profile: str | None = None,
        artifact: FormalizationArtifact | Mapping[str, Any] | None = None,
        policy_decisions: Sequence[Any] = (),
    ) -> SecurityConstraintRecord:
        """Store a constraint set and return the verified cache record.

        Accepts a finished :class:`SecurityConstraintRecord`, a
        :class:`SecurityIR` declaration (formalized on demand), a formalization
        artifact whose declaration is embedded in metadata is not supported —
        pass declaration separately — or a mapping declaration payload.
        """

        with self._lock:
            if isinstance(declaration, SecurityConstraintRecord):
                if profile is not None and declaration.profile != _require_profile(
                    profile
                ):
                    raise SecurityConstraintCacheError(
                        "profile argument conflicts with the supplied record"
                    )
                if artifact is not None:
                    raise SecurityConstraintCacheError(
                        "artifact cannot be supplied with a finished record"
                    )
                if policy_decisions:
                    raise SecurityConstraintCacheError(
                        "policy_decisions cannot be supplied with a finished record"
                    )
                record = declaration.verify_integrity(
                    known_vocabularies=self.known_vocabularies
                )
            elif isinstance(declaration, FormalizationArtifact):
                raise SecurityConstraintCacheError(
                    "put requires a SecurityIR declaration; pass artifact=..."
                )
            else:
                if profile is None:
                    raise SecurityConstraintCacheError(
                        "profile is required when putting a declaration"
                    )
                if artifact is None and self.formalization_adapter is not None:
                    try:
                        artifact = self.formalization_adapter.adapt_artifact(
                            declaration
                        )
                    except (
                        SecurityIRFormalizationAdapterError,
                        TypeError,
                        ValueError,
                    ) as exc:
                        raise SecurityConstraintCacheError(
                            f"failed to formalize security declaration: {exc}"
                        ) from exc
                record = SecurityConstraintRecord.build(
                    declaration,
                    profile=profile,
                    artifact=artifact,
                    policy_decisions=policy_decisions,
                    known_vocabularies=self.known_vocabularies,
                )

            self._records[record.content_cid] = record
            self._profile_index[record.profile] = record.content_cid
            self._persist_record(record)
            self._persist_index()
            return record

    def get(self, content_cid: str) -> SecurityConstraintRecord:
        """Load one constraint set by content CID (memory first, then disk)."""

        cid = _require_text(content_cid, "content_cid")
        with self._lock:
            record = self._records.get(cid)
            if record is not None:
                return record.verify_integrity(
                    known_vocabularies=self.known_vocabularies
                )
            path = self._record_path(cid)
            if path is None or not path.is_file():
                raise SecurityConstraintCacheError(
                    f"constraint record not found for content_cid={cid!r}"
                )
            record = self._load_record_file(path)
            if record.content_cid != cid:
                raise SecurityConstraintIntegrityError(
                    "on-disk constraint record CID does not match requested CID"
                )
            self._records[record.content_cid] = record
            self._profile_index[record.profile] = record.content_cid
            return record

    def get_by_profile(self, profile: str) -> SecurityConstraintRecord:
        """Return the constraint set currently indexed for *profile*."""

        profile = _require_profile(profile)
        with self._lock:
            cid = self._profile_index.get(profile)
            if cid is None:
                raise SecurityConstraintCacheError(
                    f"no constraint record indexed for profile={profile!r}"
                )
            return self.get(cid)

    def get_by_declaration(
        self,
        declaration_cid: str,
        *,
        profile: str | None = None,
    ) -> SecurityConstraintRecord:
        """Return a cached constraint set for a declaration CID.

        When *profile* is provided the profile index is preferred.  Otherwise
        the first matching record is returned; multiple profiles for one
        declaration are distinguished only when a profile is supplied.
        """

        declaration_cid = _require_text(declaration_cid, "declaration_cid")
        with self._lock:
            if profile is not None:
                record = self.get_by_profile(profile)
                if record.declaration_cid != declaration_cid:
                    raise SecurityConstraintCacheError(
                        "profile index points at a different declaration_cid"
                    )
                return record
            matches = [
                record
                for record in self._records.values()
                if record.declaration_cid == declaration_cid
            ]
            if not matches:
                # Fall back to scanning disk if present.
                self.reload()
                matches = [
                    record
                    for record in self._records.values()
                    if record.declaration_cid == declaration_cid
                ]
            if not matches:
                raise SecurityConstraintCacheError(
                    f"no constraint record for declaration_cid={declaration_cid!r}"
                )
            if len(matches) > 1:
                profiles = ", ".join(sorted(item.profile for item in matches))
                raise SecurityConstraintCacheError(
                    "multiple constraint records for declaration_cid="
                    f"{declaration_cid!r}; specify profile (candidates: {profiles})"
                )
            return matches[0].verify_integrity(
                known_vocabularies=self.known_vocabularies
            )

    def contains(self, content_cid: str) -> bool:
        try:
            self.get(content_cid)
            return True
        except SecurityConstraintCacheError:
            return False

    def profiles(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._profile_index))

    def cids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._records))

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def reload(self) -> int:
        """Reload all on-disk records with full integrity verification.

        Corrupt, digest-mismatched, or unknown-extension records fail closed
        and prevent the cache from accepting the damaged tree.  Returns the
        number of records loaded.
        """

        with self._lock:
            if self.root is None:
                # Memory-only: re-verify existing entries.
                for cid, record in list(self._records.items()):
                    verified = record.verify_integrity(
                        known_vocabularies=self.known_vocabularies
                    )
                    self._records[cid] = verified
                return len(self._records)

            records_dir = self._records_dir()
            assert records_dir is not None
            loaded: dict[str, SecurityConstraintRecord] = {}
            profile_index: dict[str, str] = {}

            for path in sorted(records_dir.glob("*.json")):
                record = self._load_record_file(path)
                if record.content_cid in loaded:
                    raise SecurityConstraintIntegrityError(
                        f"duplicate constraint content_cid on disk: {record.content_cid}"
                    )
                loaded[record.content_cid] = record
                # Last writer wins for a profile only if digests agree with index.
                profile_index[record.profile] = record.content_cid

            index_path = self._index_path()
            if index_path is not None and index_path.is_file():
                try:
                    index_payload = json.loads(
                        index_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise SecurityConstraintIntegrityError(
                        f"constraint cache index is unreadable: {exc}"
                    ) from exc
                index_payload = _as_mapping(index_payload, "constraint cache index")
                if (
                    index_payload.get("schema_version")
                    != SECURITY_CONSTRAINT_INDEX_SCHEMA_VERSION
                ):
                    raise SecurityConstraintIntegrityError(
                        "unsupported constraint cache index schema: "
                        f"{index_payload.get('schema_version')!r}"
                    )
                profiles = index_payload.get("profiles", {})
                if not isinstance(profiles, Mapping):
                    raise SecurityConstraintIntegrityError(
                        "constraint cache index profiles must be a mapping"
                    )
                for profile, cid in profiles.items():
                    profile = _require_profile(profile)
                    cid = _require_text(cid, "index content_cid")
                    if cid not in loaded:
                        raise SecurityConstraintIntegrityError(
                            f"index references missing constraint record {cid!r}"
                        )
                    if loaded[cid].profile != profile:
                        raise SecurityConstraintIntegrityError(
                            f"index profile {profile!r} points at record for "
                            f"{loaded[cid].profile!r}"
                        )
                    profile_index[profile] = cid

            self._records = loaded
            self._profile_index = profile_index
            return len(loaded)

    def clear(self) -> None:
        """Drop in-memory state (does not delete on-disk files)."""

        with self._lock:
            self._records.clear()
            self._profile_index.clear()

    def _persist_record(self, record: SecurityConstraintRecord) -> None:
        path = self._record_path(record.content_cid)
        if path is None:
            return
        _atomic_write_json(path, record.to_dict())

    def _persist_index(self) -> None:
        path = self._index_path()
        if path is None:
            return
        payload = {
            "interface": SECURITY_CONSTRAINT_CACHE_INTERFACE,
            "profiles": {
                profile: cid
                for profile, cid in sorted(self._profile_index.items())
            },
            "record_cids": sorted(self._records),
            "schema_version": SECURITY_CONSTRAINT_INDEX_SCHEMA_VERSION,
        }
        _atomic_write_json(path, payload)

    def _load_record_file(self, path: Path) -> SecurityConstraintRecord:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise SecurityConstraintIntegrityError(
                f"unable to read constraint record {path}: {exc}"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SecurityConstraintIntegrityError(
                f"constraint record {path.name} is not valid JSON: {exc}"
            ) from exc
        try:
            record = SecurityConstraintRecord.from_dict(
                _as_mapping(payload, "constraint record")
            )
        except SecurityConstraintCacheError as exc:
            raise SecurityConstraintIntegrityError(
                f"constraint record {path.name} failed validation: {exc}"
            ) from exc
        # Fail closed if the file bytes were reordered or padded while still
        # parsing: re-encode and compare digests of the semantic payload.
        recomputed = _sha256_digest(_canonical_bytes(record._identity_payload()))
        if recomputed != record.content_digest:
            raise SecurityConstraintIntegrityError(
                f"constraint record {path.name} failed content rehash"
            )
        return record.verify_integrity(known_vocabularies=self.known_vocabularies)


# Architecture-plan / interface shorthand.
SecurityConstraintCacheV1 = SecurityConstraintCache


def put_security_constraints(
    cache: SecurityConstraintCache,
    declaration: SecurityIR | Mapping[str, Any],
    *,
    profile: str,
    artifact: FormalizationArtifact | Mapping[str, Any] | None = None,
    policy_decisions: Sequence[Any] = (),
) -> SecurityConstraintRecord:
    """Functional put wrapper for SecurityConstraintCache@1."""

    return cache.put(
        declaration,
        profile=profile,
        artifact=artifact,
        policy_decisions=policy_decisions,
    )


def get_security_constraints(
    cache: SecurityConstraintCache,
    content_cid: str,
) -> SecurityConstraintRecord:
    """Functional get wrapper for SecurityConstraintCache@1."""

    return cache.get(content_cid)


__all__ = [
    "KNOWN_SECURITY_EXTENSION_VOCABULARIES",
    "SECURITY_CONSTRAINT_CACHE_INTERFACE",
    "SECURITY_CONSTRAINT_CACHE_SCHEMA_VERSION",
    "SECURITY_CONSTRAINT_INDEX_SCHEMA_VERSION",
    "SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION",
    "SecurityConstraintCache",
    "SecurityConstraintCacheError",
    "SecurityConstraintCacheV1",
    "SecurityConstraintIntegrityError",
    "SecurityConstraintRecord",
    "UnknownSecurityExtensionError",
    "get_security_constraints",
    "known_extension_vocabularies",
    "put_security_constraints",
    "validate_extensions_known",
]
