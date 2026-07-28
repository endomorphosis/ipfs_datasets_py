"""Optional ZKP attestation verify helper for the proof corpus (LIG-013).

Loads a content-addressed envelope from :class:`ProofCorpusStore` and verifies
an optional zero-knowledge attestation bound to that envelope.  The helper is
deliberately fail-closed on absence:

* **pass** — a present attestation verifies and binds the envelope + profile
* **fail** — a present attestation is malformed, unbound, or does not verify
* **absent** — no attestation is supplied or stored (never treated as pass)

Legal envelopes use :mod:`ipfs_datasets_py.logic.zkp.statements.legal_constraint`
(LIG-008).  Attestations may be passed inline to
:func:`verify_attestation` or persisted beside the store under
``attestations/<content_cid>.json`` (and in-memory for rootless stores).

Acceptance (LIG-013)
--------------------
* Honest legal fixture with a present ZKP verifies (status ``pass``).
* Missing ZKP is ``absent``, never ``pass``.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from ..zkp.statements.legal_constraint import (
    LEGAL_CONSTRAINT_ZKP_INTERFACE,
    LegalConstraintAttestation,
    LegalConstraintStatement,
    LegalConstraintWitness,
    LegalConstraintZKPError,
    attestation_satisfies_zkp_required,
    build_statement_from_payload,
    compute_constraint_digest,
    prove_legal_constraint_attestation,
    verify_legal_constraint_attestation,
)
from .schemas import (
    ArtifactEnvelope,
    ProofCorpusFamily,
    ProofCorpusSchemaError,
    as_mapping,
    require_profile,
    require_text,
)
from .store import ProofCorpusStore, ProofCorpusStoreError

PROOF_CORPUS_ATTEST_INTERFACE: Final = "ProofCorpusAttest@1"
PROOF_CORPUS_ATTEST_SCHEMA_VERSION: Final = "proof-corpus-attest/v1"

# Rootless stores pin attestations by id(store) -> content_cid -> payload.
_MEMORY_ATTESTATIONS: dict[int, dict[str, dict[str, Any]]] = {}
_MEMORY_LOCK = threading.RLock()


class ProofCorpusAttestError(ProofCorpusSchemaError):
    """Raised when an attestation helper operation cannot proceed safely."""


class AttestationStatus(str, Enum):
    """Typed verification outcome for :func:`verify_attestation`.

    ``ABSENT`` is distinct from ``FAIL`` and from ``PASS`` so gate logic can
    abstain when a profile requires ZKP but none is available — missing proof
    is never a silent pass.
    """

    PASS = "pass"
    FAIL = "fail"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class AttestationVerifyResult:
    """Structured result of :func:`verify_attestation`.

    ``status`` is the authority field.  Convenience properties mirror it for
    callers that prefer booleans without treating absence as success.
    """

    status: AttestationStatus
    content_cid: str
    profile: str
    family: str = ""
    reason: str = ""
    statement_digest: str = ""
    is_simulated: bool = False
    attestation_interface: str = ""
    backend: str = ""
    schema_version: str = PROOF_CORPUS_ATTEST_SCHEMA_VERSION
    interface: str = PROOF_CORPUS_ATTEST_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.status, AttestationStatus):
            object.__setattr__(
                self, "status", AttestationStatus(str(self.status))
            )
        object.__setattr__(
            self, "content_cid", require_text(self.content_cid, "content_cid")
        )
        object.__setattr__(
            self, "profile", require_profile(self.profile)
        )
        if self.family not in ("", None):
            object.__setattr__(self, "family", str(self.family))
        else:
            object.__setattr__(self, "family", "")
        if not isinstance(self.reason, str):
            raise ProofCorpusAttestError("reason must be a string")
        if not isinstance(self.statement_digest, str):
            raise ProofCorpusAttestError("statement_digest must be a string")
        if not isinstance(self.is_simulated, bool):
            raise ProofCorpusAttestError("is_simulated must be a bool")
        if not isinstance(self.attestation_interface, str):
            raise ProofCorpusAttestError(
                "attestation_interface must be a string"
            )
        if not isinstance(self.backend, str):
            raise ProofCorpusAttestError("backend must be a string")
        if self.schema_version != PROOF_CORPUS_ATTEST_SCHEMA_VERSION:
            raise ProofCorpusAttestError(
                f"unsupported attest schema: {self.schema_version!r}"
            )
        if self.interface != PROOF_CORPUS_ATTEST_INTERFACE:
            raise ProofCorpusAttestError(
                f"unsupported attest interface: {self.interface!r}"
            )

    @property
    def is_pass(self) -> bool:
        return self.status is AttestationStatus.PASS

    @property
    def is_fail(self) -> bool:
        return self.status is AttestationStatus.FAIL

    @property
    def is_absent(self) -> bool:
        return self.status is AttestationStatus.ABSENT

    @property
    def ok(self) -> bool:
        """True only on verified pass — absence and fail are both not ok."""

        return self.is_pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "attestation_interface": self.attestation_interface,
            "backend": self.backend,
            "content_cid": self.content_cid,
            "family": self.family,
            "interface": self.interface,
            "is_simulated": self.is_simulated,
            "profile": self.profile,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "statement_digest": self.statement_digest,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttestationVerifyResult":
        payload = dict(as_mapping(value, "attestation verify result"))
        return cls(
            status=AttestationStatus(str(payload.get("status", ""))),
            content_cid=str(payload.get("content_cid", "")),
            profile=str(payload.get("profile", "")),
            family=str(payload.get("family", "") or ""),
            reason=str(payload.get("reason", "") or ""),
            statement_digest=str(payload.get("statement_digest", "") or ""),
            is_simulated=bool(payload.get("is_simulated", False)),
            attestation_interface=str(
                payload.get("attestation_interface", "") or ""
            ),
            backend=str(payload.get("backend", "") or ""),
            schema_version=str(
                payload.get(
                    "schema_version", PROOF_CORPUS_ATTEST_SCHEMA_VERSION
                )
            ),
            interface=str(
                payload.get("interface", PROOF_CORPUS_ATTEST_INTERFACE)
            ),
        )


def _result(
    *,
    status: AttestationStatus,
    content_cid: str,
    profile: str,
    family: str = "",
    reason: str = "",
    statement_digest: str = "",
    is_simulated: bool = False,
    attestation_interface: str = "",
    backend: str = "",
) -> AttestationVerifyResult:
    return AttestationVerifyResult(
        status=status,
        content_cid=content_cid,
        profile=profile,
        family=family,
        reason=reason,
        statement_digest=statement_digest,
        is_simulated=is_simulated,
        attestation_interface=attestation_interface,
        backend=backend,
    )


def constraint_payload_for_envelope(
    envelope: ArtifactEnvelope | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the deterministic private payload bound by a legal ZKP witness.

    The payload commits to envelope identity fields (not private legal text).
    Its canonical digest becomes ``constraint_digest`` in the public statement.
    """

    if isinstance(envelope, ArtifactEnvelope):
        env = envelope.verify_integrity()
    else:
        env = ArtifactEnvelope.from_dict(as_mapping(envelope, "envelope"))
    return {
        "artifact_cid": env.artifact_cid,
        "artifact_digest": env.artifact_digest,
        "content_cid": env.content_cid,
        "content_digest": env.content_digest,
        "family": env.family.value,
        "jurisdiction": env.jurisdiction,
        "profile": env.profile,
        "source_digest": env.source_digest,
        "source_id": env.source_id,
    }


def build_legal_statement_for_envelope(
    envelope: ArtifactEnvelope | Mapping[str, Any],
    *,
    profile: str | None = None,
) -> tuple[LegalConstraintStatement, LegalConstraintWitness]:
    """Build a legal-constraint statement + witness pair for *envelope*.

    When *profile* is provided it must match the envelope profile (fail closed).
    """

    if isinstance(envelope, ArtifactEnvelope):
        env = envelope.verify_integrity()
    else:
        env = ArtifactEnvelope.from_dict(as_mapping(envelope, "envelope"))
    if env.family is not ProofCorpusFamily.LEGAL:
        raise ProofCorpusAttestError(
            "legal-constraint ZKP statements require a legal envelope; "
            f"got family={env.family.value!r}"
        )
    resolved_profile = env.profile
    if profile is not None:
        resolved_profile = require_profile(profile)
        if resolved_profile != env.profile:
            raise ProofCorpusAttestError(
                f"profile {resolved_profile!r} does not match envelope profile "
                f"{env.profile!r}"
            )
    payload = constraint_payload_for_envelope(env)
    return build_statement_from_payload(
        payload,
        source_digest=env.source_digest,
        profile=resolved_profile,
        jurisdiction=env.jurisdiction,
        artifact_cid=env.artifact_cid,
    )


def prove_legal_envelope_attestation(
    envelope: ArtifactEnvelope | Mapping[str, Any],
    *,
    profile: str | None = None,
    backend: str = "simulated",
    seed: bytes | str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> LegalConstraintAttestation:
    """Prove a legal-constraint ZKP over the envelope identity payload.

    Default backend is the labeled simulated path from LIG-008.  Callers that
    require production ZKP must not treat simulated receipts as success
    (see :func:`verify_attestation` ``accept_simulated`` /
    ``require_zkp_verify``).
    """

    statement, witness = build_legal_statement_for_envelope(
        envelope, profile=profile
    )
    meta: dict[str, Any] = {
        "corpus_interface": PROOF_CORPUS_ATTEST_INTERFACE,
        "corpus_schema_version": PROOF_CORPUS_ATTEST_SCHEMA_VERSION,
    }
    if extra_metadata:
        meta.update(dict(extra_metadata))
    return prove_legal_constraint_attestation(
        statement,
        witness,
        backend=backend,
        seed=seed,
        extra_metadata=meta,
    )


def _normalize_attestation(
    value: LegalConstraintAttestation | Mapping[str, Any],
) -> LegalConstraintAttestation:
    try:
        if isinstance(value, LegalConstraintAttestation):
            return value
        return LegalConstraintAttestation.from_dict(
            as_mapping(value, "attestation")
        )
    except (LegalConstraintZKPError, TypeError, ValueError) as exc:
        raise ProofCorpusAttestError(
            f"invalid legal-constraint attestation: {exc}"
        ) from exc


def _attestation_dir(store: ProofCorpusStore) -> Path | None:
    root = store.root
    if root is None:
        return None
    path = Path(root) / "attestations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _attestation_path(store: ProofCorpusStore, content_cid: str) -> Path | None:
    directory = _attestation_dir(store)
    if directory is None:
        return None
    safe = content_cid.replace("/", "_")
    return directory / f"{safe}.json"


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
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


def put_attestation(
    store: ProofCorpusStore,
    content_cid: str,
    attestation: LegalConstraintAttestation | Mapping[str, Any],
) -> dict[str, Any]:
    """Persist a ZKP attestation for *content_cid* beside *store*.

    The envelope must already exist in the store so CID binding can be checked
    later by :func:`verify_attestation`.  Returns the serialised attestation
    mapping.
    """

    if not isinstance(store, ProofCorpusStore):
        raise ProofCorpusAttestError("store must be a ProofCorpusStore")
    cid = require_text(content_cid, "content_cid")
    # Ensure the envelope exists (raises ProofCorpusStoreError if not).
    store.get(cid)
    att = _normalize_attestation(attestation)
    payload = att.to_dict()
    path = _attestation_path(store, cid)
    if path is not None:
        _atomic_write_json(path, payload)
    with _MEMORY_LOCK:
        by_cid = _MEMORY_ATTESTATIONS.setdefault(id(store), {})
        by_cid[cid] = dict(payload)
    return dict(payload)


def get_attestation(
    store: ProofCorpusStore, content_cid: str
) -> dict[str, Any] | None:
    """Return a stored attestation mapping for *content_cid*, or ``None``."""

    if not isinstance(store, ProofCorpusStore):
        raise ProofCorpusAttestError("store must be a ProofCorpusStore")
    cid = require_text(content_cid, "content_cid")
    with _MEMORY_LOCK:
        memory = _MEMORY_ATTESTATIONS.get(id(store), {})
        if cid in memory:
            return dict(memory[cid])
    path = _attestation_path(store, cid)
    if path is not None and path.is_file():
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        with _MEMORY_LOCK:
            by_cid = _MEMORY_ATTESTATIONS.setdefault(id(store), {})
            by_cid[cid] = dict(payload)
        return dict(payload)
    return None


def has_attestation(store: ProofCorpusStore, content_cid: str) -> bool:
    """Return True when a ZKP attestation blob is present for *content_cid*."""

    return get_attestation(store, content_cid) is not None


def clear_attestation(store: ProofCorpusStore, content_cid: str) -> bool:
    """Remove a stored attestation.  Returns True if one was present."""

    if not isinstance(store, ProofCorpusStore):
        raise ProofCorpusAttestError("store must be a ProofCorpusStore")
    cid = require_text(content_cid, "content_cid")
    removed = False
    with _MEMORY_LOCK:
        by_cid = _MEMORY_ATTESTATIONS.get(id(store))
        if by_cid is not None and cid in by_cid:
            del by_cid[cid]
            removed = True
    path = _attestation_path(store, cid)
    if path is not None and path.is_file():
        try:
            path.unlink()
            removed = True
        except OSError:
            pass
    return removed


def _statement_binds_envelope(
    statement: LegalConstraintStatement,
    envelope: ArtifactEnvelope,
    *,
    profile: str,
) -> tuple[bool, str]:
    """Check public statement fields bind the loaded envelope + profile."""

    if statement.profile != profile:
        return False, "statement_profile_mismatch"
    if statement.profile != envelope.profile:
        return False, "statement_envelope_profile_mismatch"
    if statement.source_digest != envelope.source_digest:
        return False, "statement_source_digest_mismatch"
    if statement.artifact_cid and statement.artifact_cid != envelope.artifact_cid:
        return False, "statement_artifact_cid_mismatch"
    if (
        statement.jurisdiction
        and statement.jurisdiction != envelope.jurisdiction
    ):
        return False, "statement_jurisdiction_mismatch"
    expected_payload = constraint_payload_for_envelope(envelope)
    expected_digest = compute_constraint_digest(expected_payload)
    if statement.constraint_digest != expected_digest:
        return False, "statement_constraint_digest_mismatch"
    return True, ""


def verify_attestation(
    store: ProofCorpusStore,
    content_cid: str,
    profile: str,
    *,
    attestation: LegalConstraintAttestation | Mapping[str, Any] | None = None,
    require_zkp_verify: bool = False,
    accept_simulated_zkp: bool = False,
) -> AttestationVerifyResult:
    """Verify optional ZKP attestation for envelope *content_cid* under *profile*.

    Parameters
    ----------
    store:
        Proof corpus store that holds the envelope.
    content_cid:
        Content CID of the envelope to verify against.
    profile:
        Profile wire id that must match both the envelope and the statement.
    attestation:
        Optional inline attestation.  When omitted, a previously
        :func:`put_attestation`-stored blob is used if present.
    require_zkp_verify:
        When True (``zkp-required`` style), simulated receipts never pass
        unless ``accept_simulated_zkp`` is also True.
    accept_simulated_zkp:
        Whether labeled simulated ZKP receipts may count as pass.

    Returns
    -------
    AttestationVerifyResult
        Typed ``pass`` / ``fail`` / ``absent``.  Missing ZKP is always
        ``absent`` (never ``pass``), even when ``require_zkp_verify`` is False.
    """

    if not isinstance(store, ProofCorpusStore):
        raise ProofCorpusAttestError("store must be a ProofCorpusStore")
    cid = require_text(content_cid, "content_cid")
    profile = require_profile(profile)

    if require_zkp_verify and accept_simulated_zkp:
        raise ProofCorpusAttestError(
            "require_zkp_verify=True cannot accept_simulated_zkp=True"
        )

    try:
        envelope = store.get(cid)
    except ProofCorpusStoreError as exc:
        return _result(
            status=AttestationStatus.FAIL,
            content_cid=cid,
            profile=profile,
            reason=f"envelope_not_found: {exc}",
        )
    except Exception as exc:
        return _result(
            status=AttestationStatus.FAIL,
            content_cid=cid,
            profile=profile,
            reason=f"envelope_load_failed: {exc}",
        )

    family = envelope.family.value
    if profile != envelope.profile:
        return _result(
            status=AttestationStatus.FAIL,
            content_cid=cid,
            profile=profile,
            family=family,
            reason="profile_envelope_mismatch",
        )

    resolved = attestation
    if resolved is None:
        resolved = get_attestation(store, cid)

    if resolved is None:
        return _result(
            status=AttestationStatus.ABSENT,
            content_cid=cid,
            profile=profile,
            family=family,
            reason="zkp_missing",
        )

    # Present attestation for a non-legal family cannot pass.
    if envelope.family is not ProofCorpusFamily.LEGAL:
        return _result(
            status=AttestationStatus.FAIL,
            content_cid=cid,
            profile=profile,
            family=family,
            reason="unsupported_family_for_zkp",
        )

    try:
        att = _normalize_attestation(resolved)
    except ProofCorpusAttestError as exc:
        return _result(
            status=AttestationStatus.FAIL,
            content_cid=cid,
            profile=profile,
            family=family,
            reason=f"attestation_invalid: {exc}",
        )

    meta_backend = str(att.backend or "")
    meta_iface = str(att.interface or "")
    stmt_digest = str(att.statement_digest or "")

    binds, bind_reason = _statement_binds_envelope(
        att.statement, envelope, profile=profile
    )
    if not binds:
        return _result(
            status=AttestationStatus.FAIL,
            content_cid=cid,
            profile=profile,
            family=family,
            reason=bind_reason,
            statement_digest=stmt_digest,
            is_simulated=bool(att.is_simulated),
            attestation_interface=meta_iface,
            backend=meta_backend,
        )

    if not verify_legal_constraint_attestation(
        att, expected_statement=att.statement
    ):
        return _result(
            status=AttestationStatus.FAIL,
            content_cid=cid,
            profile=profile,
            family=family,
            reason="zkp_verify_failed",
            statement_digest=stmt_digest,
            is_simulated=bool(att.is_simulated),
            attestation_interface=meta_iface,
            backend=meta_backend,
        )

    # Profile policy: when require_zkp_verify is set (or accept_sim is False
    # with the default path), consult LIG-008 zkp-required helper.
    if require_zkp_verify or not accept_simulated_zkp:
        if not attestation_satisfies_zkp_required(
            att,
            require_zkp_verify=require_zkp_verify,
            accept_simulated_zkp=accept_simulated_zkp,
        ):
            reason = (
                "simulated_zkp_rejected"
                if att.is_simulated
                else "zkp_profile_rejected"
            )
            return _result(
                status=AttestationStatus.FAIL,
                content_cid=cid,
                profile=profile,
                family=family,
                reason=reason,
                statement_digest=stmt_digest,
                is_simulated=bool(att.is_simulated),
                attestation_interface=meta_iface,
                backend=meta_backend,
            )

    return _result(
        status=AttestationStatus.PASS,
        content_cid=cid,
        profile=profile,
        family=family,
        reason="zkp_verified",
        statement_digest=stmt_digest,
        is_simulated=bool(att.is_simulated),
        attestation_interface=meta_iface or LEGAL_CONSTRAINT_ZKP_INTERFACE,
        backend=meta_backend,
    )


def verify_attestation_for_envelope(
    envelope: ArtifactEnvelope | Mapping[str, Any],
    profile: str,
    *,
    attestation: LegalConstraintAttestation | Mapping[str, Any] | None = None,
    require_zkp_verify: bool = False,
    accept_simulated_zkp: bool = False,
) -> AttestationVerifyResult:
    """Verify *attestation* against an already-loaded envelope (no store).

    When *attestation* is ``None``, returns ``absent`` without inventing a pass.
    """

    profile = require_profile(profile)
    try:
        if isinstance(envelope, ArtifactEnvelope):
            env = envelope.verify_integrity()
        else:
            env = ArtifactEnvelope.from_dict(
                as_mapping(envelope, "envelope")
            )
    except Exception as exc:
        return _result(
            status=AttestationStatus.FAIL,
            content_cid="unknown",
            profile=profile,
            reason=f"envelope_invalid: {exc}",
        )

    store = ProofCorpusStore()
    store.put(env)
    return verify_attestation(
        store,
        env.content_cid,
        profile,
        attestation=attestation,
        require_zkp_verify=require_zkp_verify,
        accept_simulated_zkp=accept_simulated_zkp,
    )


__all__ = [
    "PROOF_CORPUS_ATTEST_INTERFACE",
    "PROOF_CORPUS_ATTEST_SCHEMA_VERSION",
    "AttestationStatus",
    "AttestationVerifyResult",
    "ProofCorpusAttestError",
    "build_legal_statement_for_envelope",
    "clear_attestation",
    "constraint_payload_for_envelope",
    "get_attestation",
    "has_attestation",
    "prove_legal_envelope_attestation",
    "put_attestation",
    "verify_attestation",
    "verify_attestation_for_envelope",
]
