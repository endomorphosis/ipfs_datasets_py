"""Content-addressed Legal IR proof cache (LegalProofCache@1).

Persists Legal formalization artifacts and optional theorem proof receipts so a
gate or corpus loader can retrieve a fragment by CID without re-running
formalization or provers when integrity holds.

Integrity is fail-closed:

* every on-disk envelope is rehashed on load and rejected on digest mismatch;
* formalization artifact identity is recomputed from the stored payload and
  must match the recorded artifact digest and CID;
* source digest is bound to the artifact declaration digest;
* theorem receipts, when present, must carry ``theorem_proof`` authority and
  ``proved`` status, and must bind the same declaration id.

Secondary indexes support lookup by **profile** and **source digest**
(optionally disambiguated by profile when multiple profiles share a source).

Offline rebuild: load golden fixtures under
``tests/fixtures/legal_ir/proof_cache`` via
:meth:`LegalProofRecord.from_dict` + :meth:`LegalProofCache.put`, or call
:func:`rebuild_offline_from_fixture_dir`.
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
from ..ir_core.protocols import (
    AuthorityKind,
    ProofReceipt,
    ResultStatus,
)


LEGAL_PROOF_CACHE_INTERFACE: Final = "LegalProofCache@1"
LEGAL_PROOF_CACHE_SCHEMA_VERSION: Final = "legal-proof-cache/v1"
LEGAL_PROOF_RECORD_SCHEMA_VERSION: Final = "legal-proof-record/v1"
LEGAL_PROOF_INDEX_SCHEMA_VERSION: Final = "legal-proof-index/v1"

_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_JURISDICTION_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "artifact_cid",
        "artifact_digest",
        "content_cid",
        "content_digest",
        "jurisdiction",
        "profile",
        "schema_version",
        "source_digest",
        "source_id",
        "theorem_receipts",
    }
)


class LegalProofCacheError(ValueError):
    """Raised when a legal proof cache operation cannot proceed safely."""


class LegalProofIntegrityError(LegalProofCacheError):
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
        raise LegalProofCacheError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _require_profile(value: Any) -> str:
    profile = _require_text(value, "profile")
    if not _PROFILE_RE.fullmatch(profile):
        raise LegalProofCacheError(
            "profile must be a lowercase hyphenated identifier"
        )
    return profile


def _require_jurisdiction(value: Any) -> str:
    if value is None or value == "":
        return ""
    jurisdiction = _require_text(value, "jurisdiction")
    if not _JURISDICTION_RE.fullmatch(jurisdiction):
        raise LegalProofCacheError(
            "jurisdiction must be a lowercase hyphenated identifier"
        )
    return jurisdiction


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if not _DIGEST_RE.fullmatch(digest):
        raise LegalProofCacheError(
            f"{field_name} must be a sha256:<hex> digest"
        )
    return digest


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LegalProofCacheError(f"{label} must be a mapping")
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
    raise LegalProofCacheError(
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


def _normalize_artifact(
    artifact: FormalizationArtifact | Mapping[str, Any],
) -> tuple[FormalizationArtifact, dict[str, Any]]:
    if isinstance(artifact, FormalizationArtifact):
        produced = artifact
    else:
        try:
            produced = FormalizationArtifact.from_dict(
                _as_mapping(artifact, "artifact")
            )
        except (TypeError, ValueError) as exc:
            raise LegalProofCacheError(
                f"invalid formalization artifact: {exc}"
            ) from exc
    if produced.domain != "legal":
        raise LegalProofCacheError(
            "legal proof cache only accepts legal-domain formalization artifacts"
        )
    return produced, produced.to_dict()


def _normalize_theorem_receipt(value: Any) -> dict[str, Any]:
    """Normalize a theorem receipt; only affirmative theorem proofs are stored."""

    if isinstance(value, ProofReceipt):
        receipt = value
    elif isinstance(value, Mapping):
        try:
            receipt = ProofReceipt.from_dict(value)
        except (TypeError, ValueError) as exc:
            raise LegalProofCacheError(
                f"invalid theorem proof receipt: {exc}"
            ) from exc
    else:
        raise LegalProofCacheError(
            "theorem receipt must be a ProofReceipt or mapping"
        )
    if receipt.proof_authority is not AuthorityKind.THEOREM_PROOF:
        raise LegalProofCacheError(
            "theorem receipt proof_authority must be theorem_proof"
        )
    if receipt.status is not ResultStatus.PROVED:
        raise LegalProofCacheError(
            "theorem receipt status must be proved (no proof authority without receipt)"
        )
    return receipt.to_dict()


@dataclass(frozen=True, slots=True)
class LegalProofRecord:
    """One content-addressed legal formal artifact (+ optional theorem receipts)."""

    source_id: str
    source_digest: str
    profile: str
    artifact: Mapping[str, Any]
    artifact_digest: str = ""
    artifact_cid: str = ""
    theorem_receipts: tuple[Mapping[str, Any], ...] = ()
    jurisdiction: str = ""
    content_digest: str = ""
    content_cid: str = ""
    schema_version: str = LEGAL_PROOF_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _require_text(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "source_digest",
            _require_digest(self.source_digest, "source_digest"),
        )
        object.__setattr__(self, "profile", _require_profile(self.profile))
        object.__setattr__(
            self, "jurisdiction", _require_jurisdiction(self.jurisdiction)
        )
        artifact_map = dict(_as_mapping(self.artifact, "artifact"))
        object.__setattr__(self, "artifact", MappingProxyType(artifact_map))

        receipts = tuple(
            MappingProxyType(dict(_as_mapping(item, "theorem_receipt")))
            for item in self.theorem_receipts
        )
        object.__setattr__(self, "theorem_receipts", receipts)

        if self.schema_version != LEGAL_PROOF_RECORD_SCHEMA_VERSION:
            raise LegalProofCacheError(
                f"unsupported legal proof record schema: {self.schema_version!r}"
            )

        # Bind artifact identity from stored payload.
        produced, _ = _normalize_artifact(dict(self.artifact))
        object.__setattr__(self, "artifact", MappingProxyType(produced.to_dict()))
        art_digest = produced.digest
        art_cid = produced.artifact_id
        if self.artifact_digest:
            recorded = _require_digest(self.artifact_digest, "artifact_digest")
            if recorded != art_digest:
                raise LegalProofIntegrityError(
                    "artifact_digest does not match recomputed formalization identity"
                )
        if self.artifact_cid:
            recorded_cid = _require_text(self.artifact_cid, "artifact_cid")
            if recorded_cid != art_cid:
                raise LegalProofIntegrityError(
                    "artifact_cid does not match recomputed formalization identity"
                )
        object.__setattr__(self, "artifact_digest", art_digest)
        object.__setattr__(self, "artifact_cid", art_cid)

        if produced.declaration_digest != self.source_digest:
            raise LegalProofIntegrityError(
                "source_digest does not match artifact declaration_digest"
            )
        # Allow either declaration_id or sample_id as the source_id label.
        if self.source_id not in {produced.declaration_id, produced.sample_id}:
            raise LegalProofIntegrityError(
                "source_id does not match artifact declaration_id or sample_id"
            )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise LegalProofIntegrityError(
                    "legal proof record content_digest does not match payload"
                )
        if self.content_cid:
            recorded_cid = _require_text(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise LegalProofIntegrityError(
                    "legal proof record content_cid does not match payload"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

        self.verify_integrity()

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "artifact": _json_ready(dict(self.artifact)),
            "artifact_cid": self.artifact_cid,
            "artifact_digest": self.artifact_digest,
            "jurisdiction": self.jurisdiction,
            "profile": self.profile,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
            "theorem_receipts": [
                _json_ready(dict(item)) for item in self.theorem_receipts
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    def formalization_artifact(self) -> FormalizationArtifact:
        """Return the stored formalization artifact."""

        try:
            return FormalizationArtifact.from_dict(dict(self.artifact))
        except (TypeError, ValueError) as exc:
            raise LegalProofIntegrityError(
                f"stored artifact is not a valid FormalizationArtifact: {exc}"
            ) from exc

    def theorem_receipt_results(self) -> tuple[ProofReceipt, ...]:
        """Return typed theorem proof receipts attached to this record."""

        results: list[ProofReceipt] = []
        for item in self.theorem_receipts:
            try:
                results.append(ProofReceipt.from_dict(dict(item)))
            except (TypeError, ValueError) as exc:
                raise LegalProofIntegrityError(
                    f"stored theorem receipt is invalid: {exc}"
                ) from exc
        return tuple(results)

    def verify_integrity(self) -> "LegalProofRecord":
        """Recompute artifact identity and receipt bindings."""

        artifact = self.formalization_artifact()
        if artifact.domain != "legal":
            raise LegalProofIntegrityError(
                "stored artifact domain is not legal"
            )
        if artifact.digest != self.artifact_digest:
            raise LegalProofIntegrityError(
                "stored artifact_digest does not match recomputed identity"
            )
        if artifact.artifact_id != self.artifact_cid:
            raise LegalProofIntegrityError(
                "stored artifact_cid does not match recomputed identity"
            )
        if artifact.declaration_digest != self.source_digest:
            raise LegalProofIntegrityError(
                "source_digest drifted from artifact declaration_digest"
            )
        if (
            artifact.declaration_id != self.source_id
            and artifact.sample_id != self.source_id
        ):
            raise LegalProofIntegrityError(
                "source_id drifted from artifact declaration/sample identity"
            )
        for receipt in self.theorem_receipt_results():
            if receipt.proof_authority is not AuthorityKind.THEOREM_PROOF:
                raise LegalProofIntegrityError(
                    "theorem receipt lost theorem_proof authority under reload"
                )
            if receipt.status is not ResultStatus.PROVED:
                raise LegalProofIntegrityError(
                    "theorem receipt lost proved status under reload"
                )
            if receipt.declaration_id and receipt.declaration_id not in {
                self.source_id,
                artifact.declaration_id,
            }:
                raise LegalProofIntegrityError(
                    "theorem receipt declaration_id does not match proof record"
                )
        return self

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalProofRecord":
        value = _as_mapping(value, "legal proof record")
        unknown = sorted(set(value) - _RECORD_FIELDS)
        if unknown:
            raise LegalProofCacheError(
                "unknown legal proof record field(s): " + ", ".join(unknown)
            )
        return cls(
            source_id=value.get("source_id", ""),
            source_digest=value.get("source_digest", ""),
            profile=value.get("profile", ""),
            artifact=value.get("artifact", {}),
            artifact_digest=value.get("artifact_digest", ""),
            artifact_cid=value.get("artifact_cid", ""),
            theorem_receipts=tuple(value.get("theorem_receipts", ())),
            jurisdiction=value.get("jurisdiction", "") or "",
            content_digest=value.get("content_digest", ""),
            content_cid=value.get("content_cid", ""),
            schema_version=value.get(
                "schema_version", LEGAL_PROOF_RECORD_SCHEMA_VERSION
            ),
        )

    @classmethod
    def build(
        cls,
        artifact: FormalizationArtifact | Mapping[str, Any],
        *,
        profile: str,
        source_id: str | None = None,
        source_digest: str | None = None,
        jurisdiction: str = "",
        theorem_receipts: Sequence[Any] = (),
    ) -> "LegalProofRecord":
        """Build a verified record from a legal formalization artifact."""

        produced, artifact_payload = _normalize_artifact(artifact)
        resolved_source_id = source_id or produced.declaration_id or produced.sample_id
        resolved_source_digest = source_digest or produced.declaration_digest
        if source_digest is not None:
            resolved_source_digest = _require_digest(
                source_digest, "source_digest"
            )
            if resolved_source_digest != produced.declaration_digest:
                raise LegalProofCacheError(
                    "source_digest does not match artifact declaration_digest"
                )
        receipt_payloads = tuple(
            _normalize_theorem_receipt(item) for item in theorem_receipts
        )
        for receipt in receipt_payloads:
            declaration_id = receipt.get("declaration_id", "")
            if declaration_id and declaration_id not in {
                resolved_source_id,
                produced.declaration_id,
            }:
                raise LegalProofCacheError(
                    "theorem receipt declaration_id does not match proof record"
                )
        return cls(
            source_id=_require_text(resolved_source_id, "source_id"),
            source_digest=_require_digest(
                resolved_source_digest, "source_digest"
            ),
            profile=_require_profile(profile),
            artifact=artifact_payload,
            artifact_digest=produced.digest,
            artifact_cid=produced.artifact_id,
            theorem_receipts=receipt_payloads,
            jurisdiction=_require_jurisdiction(jurisdiction),
        )


@dataclass
class LegalProofCache:
    """Filesystem- or memory-backed Legal proof cache.

    Records are content-addressed by their envelope digest.  Secondary indexes
    support lookup by profile and by source digest (with optional profile
    disambiguation).  Statistics track hit/miss counts for get paths.
    """

    root: Path | None = None
    _records: dict[str, LegalProofRecord] = field(
        default_factory=dict, init=False, repr=False
    )
    _profile_index: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    # source_digest -> profile -> content_cid
    _source_index: dict[str, dict[str, str]] = field(
        default_factory=dict, init=False, repr=False
    )
    _hits: int = field(default=0, init=False, repr=False)
    _misses: int = field(default=0, init=False, repr=False)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.root is not None:
            object.__setattr__(self, "root", Path(self.root))
            self.root.mkdir(parents=True, exist_ok=True)
            self.reload()

    @property
    def interface(self) -> str:
        return LEGAL_PROOF_CACHE_INTERFACE

    @property
    def schema_version(self) -> str:
        return LEGAL_PROOF_CACHE_SCHEMA_VERSION

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._records),
            }

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
        safe = content_cid.replace("/", "_")
        return records_dir / f"{safe}.json"

    def _index_record(self, record: LegalProofRecord) -> None:
        self._records[record.content_cid] = record
        self._profile_index[record.profile] = record.content_cid
        by_source = self._source_index.setdefault(record.source_digest, {})
        by_source[record.profile] = record.content_cid

    def put(
        self,
        artifact: FormalizationArtifact
        | Mapping[str, Any]
        | LegalProofRecord,
        *,
        profile: str | None = None,
        source_id: str | None = None,
        source_digest: str | None = None,
        jurisdiction: str = "",
        theorem_receipts: Sequence[Any] = (),
    ) -> LegalProofRecord:
        """Store a legal formal artifact and return the verified cache record."""

        with self._lock:
            if isinstance(artifact, LegalProofRecord):
                if profile is not None and artifact.profile != _require_profile(
                    profile
                ):
                    raise LegalProofCacheError(
                        "profile argument conflicts with the supplied record"
                    )
                if theorem_receipts:
                    raise LegalProofCacheError(
                        "theorem_receipts cannot be supplied with a finished record"
                    )
                if source_id is not None and source_id != artifact.source_id:
                    raise LegalProofCacheError(
                        "source_id argument conflicts with the supplied record"
                    )
                if (
                    source_digest is not None
                    and source_digest != artifact.source_digest
                ):
                    raise LegalProofCacheError(
                        "source_digest argument conflicts with the supplied record"
                    )
                if jurisdiction and jurisdiction != artifact.jurisdiction:
                    raise LegalProofCacheError(
                        "jurisdiction argument conflicts with the supplied record"
                    )
                record = artifact.verify_integrity()
            else:
                if profile is None:
                    raise LegalProofCacheError(
                        "profile is required when putting an artifact"
                    )
                record = LegalProofRecord.build(
                    artifact,
                    profile=profile,
                    source_id=source_id,
                    source_digest=source_digest,
                    jurisdiction=jurisdiction,
                    theorem_receipts=theorem_receipts,
                )

            self._index_record(record)
            self._persist_record(record)
            self._persist_index()
            return record

    def get(self, content_cid: str) -> LegalProofRecord:
        """Load one proof record by content CID (memory first, then disk)."""

        cid = _require_text(content_cid, "content_cid")
        with self._lock:
            record = self._records.get(cid)
            if record is not None:
                self._hits += 1
                return record.verify_integrity()
            path = self._record_path(cid)
            if path is None or not path.is_file():
                self._misses += 1
                raise LegalProofCacheError(
                    f"proof record not found for content_cid={cid!r}"
                )
            record = self._load_record_file(path)
            if record.content_cid != cid:
                raise LegalProofIntegrityError(
                    "on-disk proof record CID does not match requested CID"
                )
            self._index_record(record)
            self._hits += 1
            return record

    def get_by_profile(self, profile: str) -> LegalProofRecord:
        """Return the proof record currently indexed for *profile*."""

        profile = _require_profile(profile)
        with self._lock:
            cid = self._profile_index.get(profile)
            if cid is None:
                self._misses += 1
                raise LegalProofCacheError(
                    f"no proof record indexed for profile={profile!r}"
                )
            return self.get(cid)

    def get_by_source_digest(
        self,
        source_digest: str,
        *,
        profile: str | None = None,
    ) -> LegalProofRecord:
        """Return a cached proof record for a source digest.

        When *profile* is provided the source+profile index is preferred.
        Otherwise the sole matching record is returned; multiple profiles for
        one source require an explicit profile.
        """

        source_digest = _require_digest(source_digest, "source_digest")
        with self._lock:
            by_profile = self._source_index.get(source_digest)
            if not by_profile:
                # Fall back to scanning disk / re-verify.
                self.reload()
                by_profile = self._source_index.get(source_digest)
            if not by_profile:
                self._misses += 1
                raise LegalProofCacheError(
                    f"no proof record for source_digest={source_digest!r}"
                )
            if profile is not None:
                profile = _require_profile(profile)
                cid = by_profile.get(profile)
                if cid is None:
                    self._misses += 1
                    raise LegalProofCacheError(
                        f"no proof record for source_digest={source_digest!r} "
                        f"profile={profile!r}"
                    )
                return self.get(cid)
            if len(by_profile) > 1:
                profiles = ", ".join(sorted(by_profile))
                raise LegalProofCacheError(
                    "multiple proof records for source_digest="
                    f"{source_digest!r}; specify profile (candidates: {profiles})"
                )
            cid = next(iter(by_profile.values()))
            return self.get(cid)

    def contains(self, content_cid: str) -> bool:
        """Return True on cache hit without raising; does not count as get hit."""

        try:
            cid = _require_text(content_cid, "content_cid")
        except LegalProofCacheError:
            return False
        with self._lock:
            if cid in self._records:
                return True
            path = self._record_path(cid)
            return path is not None and path.is_file()

    def profiles(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._profile_index))

    def source_digests(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._source_index))

    def cids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._records))

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def reload(self) -> int:
        """Reload all on-disk records with full integrity verification.

        Corrupt or digest-mismatched records fail closed and prevent the cache
        from accepting the damaged tree.  Returns the number of records loaded.
        """

        with self._lock:
            if self.root is None:
                for cid, record in list(self._records.items()):
                    verified = record.verify_integrity()
                    self._records[cid] = verified
                return len(self._records)

            records_dir = self._records_dir()
            assert records_dir is not None
            loaded: dict[str, LegalProofRecord] = {}
            profile_index: dict[str, str] = {}
            source_index: dict[str, dict[str, str]] = {}

            for path in sorted(records_dir.glob("*.json")):
                record = self._load_record_file(path)
                if record.content_cid in loaded:
                    raise LegalProofIntegrityError(
                        f"duplicate proof content_cid on disk: {record.content_cid}"
                    )
                loaded[record.content_cid] = record
                profile_index[record.profile] = record.content_cid
                source_index.setdefault(record.source_digest, {})[
                    record.profile
                ] = record.content_cid

            index_path = self._index_path()
            if index_path is not None and index_path.is_file():
                try:
                    index_payload = json.loads(
                        index_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise LegalProofIntegrityError(
                        f"legal proof cache index is unreadable: {exc}"
                    ) from exc
                index_payload = _as_mapping(index_payload, "legal proof cache index")
                if (
                    index_payload.get("schema_version")
                    != LEGAL_PROOF_INDEX_SCHEMA_VERSION
                ):
                    raise LegalProofIntegrityError(
                        "unsupported legal proof cache index schema: "
                        f"{index_payload.get('schema_version')!r}"
                    )
                profiles = index_payload.get("profiles", {})
                if not isinstance(profiles, Mapping):
                    raise LegalProofIntegrityError(
                        "legal proof cache index profiles must be a mapping"
                    )
                for profile, cid in profiles.items():
                    profile = _require_profile(profile)
                    cid = _require_text(cid, "index content_cid")
                    if cid not in loaded:
                        raise LegalProofIntegrityError(
                            f"index references missing proof record {cid!r}"
                        )
                    if loaded[cid].profile != profile:
                        raise LegalProofIntegrityError(
                            f"index profile {profile!r} points at record for "
                            f"{loaded[cid].profile!r}"
                        )
                    profile_index[profile] = cid

                sources = index_payload.get("source_digests", {})
                if sources is None:
                    sources = {}
                if not isinstance(sources, Mapping):
                    raise LegalProofIntegrityError(
                        "legal proof cache index source_digests must be a mapping"
                    )
                for source_digest, profile_map in sources.items():
                    source_digest = _require_digest(
                        source_digest, "index source_digest"
                    )
                    if not isinstance(profile_map, Mapping):
                        raise LegalProofIntegrityError(
                            "source_digests entries must map profiles to CIDs"
                        )
                    for profile, cid in profile_map.items():
                        profile = _require_profile(profile)
                        cid = _require_text(cid, "index content_cid")
                        if cid not in loaded:
                            raise LegalProofIntegrityError(
                                f"source index references missing proof record {cid!r}"
                            )
                        if loaded[cid].source_digest != source_digest:
                            raise LegalProofIntegrityError(
                                "source index digest does not match record"
                            )
                        if loaded[cid].profile != profile:
                            raise LegalProofIntegrityError(
                                "source index profile does not match record"
                            )
                        source_index.setdefault(source_digest, {})[profile] = cid

            self._records = loaded
            self._profile_index = profile_index
            self._source_index = source_index
            return len(loaded)

    def clear(self) -> None:
        """Drop in-memory state (does not delete on-disk files)."""

        with self._lock:
            self._records.clear()
            self._profile_index.clear()
            self._source_index.clear()
            self._hits = 0
            self._misses = 0

    def _persist_record(self, record: LegalProofRecord) -> None:
        path = self._record_path(record.content_cid)
        if path is None:
            return
        _atomic_write_json(path, record.to_dict())

    def _persist_index(self) -> None:
        path = self._index_path()
        if path is None:
            return
        payload = {
            "interface": LEGAL_PROOF_CACHE_INTERFACE,
            "profiles": {
                profile: cid
                for profile, cid in sorted(self._profile_index.items())
            },
            "record_cids": sorted(self._records),
            "schema_version": LEGAL_PROOF_INDEX_SCHEMA_VERSION,
            "source_digests": {
                digest: {
                    profile: cid
                    for profile, cid in sorted(profiles.items())
                }
                for digest, profiles in sorted(self._source_index.items())
            },
        }
        _atomic_write_json(path, payload)

    def _load_record_file(self, path: Path) -> LegalProofRecord:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise LegalProofIntegrityError(
                f"unable to read proof record {path}: {exc}"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LegalProofIntegrityError(
                f"proof record {path.name} is not valid JSON: {exc}"
            ) from exc
        try:
            record = LegalProofRecord.from_dict(
                _as_mapping(payload, "legal proof record")
            )
        except LegalProofCacheError as exc:
            raise LegalProofIntegrityError(
                f"proof record {path.name} failed validation: {exc}"
            ) from exc
        recomputed = _sha256_digest(_canonical_bytes(record._identity_payload()))
        if recomputed != record.content_digest:
            raise LegalProofIntegrityError(
                f"proof record {path.name} failed content rehash"
            )
        return record.verify_integrity()


# Architecture-plan / interface shorthand.
LegalProofCacheV1 = LegalProofCache


def put_legal_proof(
    cache: LegalProofCache,
    artifact: FormalizationArtifact | Mapping[str, Any],
    *,
    profile: str,
    source_id: str | None = None,
    source_digest: str | None = None,
    jurisdiction: str = "",
    theorem_receipts: Sequence[Any] = (),
) -> LegalProofRecord:
    """Functional put wrapper for LegalProofCache@1."""

    return cache.put(
        artifact,
        profile=profile,
        source_id=source_id,
        source_digest=source_digest,
        jurisdiction=jurisdiction,
        theorem_receipts=theorem_receipts,
    )


def get_legal_proof(
    cache: LegalProofCache,
    content_cid: str,
) -> LegalProofRecord:
    """Functional get wrapper for LegalProofCache@1."""

    return cache.get(content_cid)


def rebuild_offline_from_fixture_dir(
    fixture_dir: str | Path,
    *,
    root: str | Path | None = None,
) -> LegalProofCache:
    """Rebuild a cache from golden fixture records (offline, no provers).

    Expects a directory containing ``manifest.json`` and the record files it
    references.  Each sample record is put into a new
    :class:`LegalProofCache` with integrity rehash on load and store.
    """

    fixture_dir = Path(fixture_dir)
    manifest_path = fixture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise LegalProofCacheError(
            f"fixture manifest not found: {manifest_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegalProofCacheError(
            f"unable to read fixture manifest: {exc}"
        ) from exc
    if not isinstance(manifest, Mapping):
        raise LegalProofCacheError("fixture manifest must be a mapping")
    if manifest.get("interface") != LEGAL_PROOF_CACHE_INTERFACE:
        raise LegalProofCacheError(
            "fixture manifest interface is not LegalProofCache@1"
        )
    cache = LegalProofCache(root=Path(root) if root is not None else None)
    samples = manifest.get("samples", {})
    if not isinstance(samples, Mapping):
        raise LegalProofCacheError("fixture manifest samples must be a mapping")
    for _name, sample in samples.items():
        if not isinstance(sample, Mapping):
            raise LegalProofCacheError("fixture sample entry must be a mapping")
        record_path = fixture_dir / str(sample.get("record_path", ""))
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LegalProofCacheError(
                f"unable to read fixture record {record_path}: {exc}"
            ) from exc
        record = LegalProofRecord.from_dict(payload)
        cache.put(record)
    return cache


__all__ = [
    "LEGAL_PROOF_CACHE_INTERFACE",
    "LEGAL_PROOF_CACHE_SCHEMA_VERSION",
    "LEGAL_PROOF_INDEX_SCHEMA_VERSION",
    "LEGAL_PROOF_RECORD_SCHEMA_VERSION",
    "LegalProofCache",
    "LegalProofCacheError",
    "LegalProofCacheV1",
    "LegalProofIntegrityError",
    "LegalProofRecord",
    "get_legal_proof",
    "put_legal_proof",
    "rebuild_offline_from_fixture_dir",
]
