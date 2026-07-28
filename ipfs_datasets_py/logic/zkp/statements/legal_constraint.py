"""Legal constraint ZKP attestation path (LegalConstraintZKP@1).

Prove and verify an optional zero-knowledge attestation over a **pinned public
statement** of a legal constraint digest.  The circuit is intentionally
separate from the Legal proof cache index (LIG-007); cache records supply
digests that this module binds into a statement circuit.

Public statement (visible to the verifier)
------------------------------------------
* ``constraint_digest`` — content digest of the legal constraint / proof record
* ``source_digest`` — declaration / source identity digest
* ``profile`` — compile / admissibility profile wire id
* ``jurisdiction`` — optional jurisdiction tag
* ``artifact_cid`` — optional formalization artifact CID
* ``circuit_ref`` — pinned ``legal_constraint@v1``

Private witness
---------------
Opening material whose canonical digest equals ``constraint_digest``.  The
witness never appears in the attestation public inputs.

Backends
--------
The default path uses a **labeled simulated** backend (hash commitments).
Simulated receipts must never be counted as production ZKP success under
``zkp-required`` profiles (see :func:`attestation_satisfies_zkp_required`).
Production backends may be wired later without changing the statement schema.

Acceptance (LIG-008)
--------------------
* Honest prove → verify succeeds.
* Tampered statement → verify fails.
* ``zkp-required`` profiles can require this path later via the helpers below.
"""

from __future__ import annotations

import hashlib
import json
import time
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from ..statement import format_circuit_ref


LEGAL_CONSTRAINT_ZKP_INTERFACE: Final = "LegalConstraintZKP@1"
LEGAL_CONSTRAINT_CIRCUIT_ID: Final = "legal_constraint"
LEGAL_CONSTRAINT_CIRCUIT_VERSION: Final = 1
LEGAL_CONSTRAINT_CIRCUIT_REF: Final = format_circuit_ref(
    LEGAL_CONSTRAINT_CIRCUIT_ID, LEGAL_CONSTRAINT_CIRCUIT_VERSION
)
LEGAL_CONSTRAINT_RULESET_ID: Final = "legal_constraint_v1"
LEGAL_CONSTRAINT_PROOF_DOMAIN: Final = b"LegalConstraintZKP@1|legal_constraint@v1"
LEGAL_CONSTRAINT_PROOF_MAGIC: Final = b"LCZKP\x00\x01\x00"  # 8-byte layout header
LEGAL_CONSTRAINT_PROOF_BYTE_LENGTH: Final = 160

_DIGEST_PREFIX: Final = "sha256:"
_PROFILE_ALLOWED: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
_SIMULATED_BACKENDS: Final = frozenset({"simulated", "sim", ""})
_PRODUCTION_BACKENDS: Final = frozenset({"groth16", "provekit", "whir"})


class LegalConstraintZKPError(ValueError):
    """Raised when a legal-constraint ZKP operation cannot proceed safely."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_digest(data: bytes) -> str:
    return _DIGEST_PREFIX + _sha256_hex(data)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise LegalConstraintZKPError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if not digest.startswith(_DIGEST_PREFIX):
        raise LegalConstraintZKPError(
            f"{field_name} must be a sha256:<hex> digest"
        )
    hex_part = digest[len(_DIGEST_PREFIX) :]
    if len(hex_part) != 64:
        raise LegalConstraintZKPError(
            f"{field_name} must be a sha256:<64-hex> digest"
        )
    try:
        int(hex_part, 16)
    except ValueError as exc:
        raise LegalConstraintZKPError(
            f"{field_name} must be a sha256:<hex> digest"
        ) from exc
    if hex_part != hex_part.lower():
        raise LegalConstraintZKPError(
            f"{field_name} digest hex must be lowercase"
        )
    return digest


def _require_profile(value: Any) -> str:
    profile = _require_text(value, "profile")
    if profile[0] not in "abcdefghijklmnopqrstuvwxyz":
        raise LegalConstraintZKPError(
            "profile must start with a lowercase letter"
        )
    if any(ch not in _PROFILE_ALLOWED for ch in profile):
        raise LegalConstraintZKPError(
            "profile must be a lowercase hyphenated identifier"
        )
    if "--" in profile or profile.endswith("-"):
        raise LegalConstraintZKPError(
            "profile must be a lowercase hyphenated identifier"
        )
    return profile


def _require_jurisdiction(value: Any) -> str:
    if value is None or value == "":
        return ""
    jurisdiction = _require_text(value, "jurisdiction")
    if jurisdiction[0] not in "abcdefghijklmnopqrstuvwxyz":
        raise LegalConstraintZKPError(
            "jurisdiction must start with a lowercase letter"
        )
    if any(ch not in _PROFILE_ALLOWED for ch in jurisdiction):
        raise LegalConstraintZKPError(
            "jurisdiction must be a lowercase hyphenated identifier"
        )
    if "--" in jurisdiction or jurisdiction.endswith("-"):
        raise LegalConstraintZKPError(
            "jurisdiction must be a lowercase hyphenated identifier"
        )
    return jurisdiction


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LegalConstraintZKPError(f"{label} must be a mapping")
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
    raise LegalConstraintZKPError(
        f"value of type {type(value).__name__} is not JSON-serializable"
    )


def compute_constraint_digest(payload: Any) -> str:
    """Return ``sha256:<hex>`` of the canonical JSON form of *payload*."""

    return _sha256_digest(_canonical_bytes(_json_ready(payload)))


def _digest_raw(digest: str) -> bytes:
    return bytes.fromhex(digest.removeprefix(_DIGEST_PREFIX))


def is_simulated_backend(backend: str) -> bool:
    """Return True when *backend* is a labeled non-production backend."""

    normalized = str(backend or "").strip().lower()
    if normalized in _SIMULATED_BACKENDS:
        return True
    if normalized in _PRODUCTION_BACKENDS:
        return False
    # Unknown backends are treated as non-production until registered.
    return True


@dataclass(frozen=True, slots=True)
class LegalConstraintStatement:
    """Public statement pinned by the legal-constraint circuit."""

    constraint_digest: str
    source_digest: str
    profile: str
    jurisdiction: str = ""
    artifact_cid: str = ""
    circuit_version: int = LEGAL_CONSTRAINT_CIRCUIT_VERSION
    ruleset_id: str = LEGAL_CONSTRAINT_RULESET_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint_digest",
            _require_digest(self.constraint_digest, "constraint_digest"),
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
        if self.artifact_cid is None:
            object.__setattr__(self, "artifact_cid", "")
        elif not isinstance(self.artifact_cid, str):
            raise LegalConstraintZKPError("artifact_cid must be a string")
        else:
            object.__setattr__(self, "artifact_cid", self.artifact_cid.strip())

        if not isinstance(self.circuit_version, int) or isinstance(
            self.circuit_version, bool
        ):
            raise LegalConstraintZKPError("circuit_version must be an int")
        if self.circuit_version != LEGAL_CONSTRAINT_CIRCUIT_VERSION:
            raise LegalConstraintZKPError(
                f"unsupported legal_constraint circuit_version: "
                f"{self.circuit_version!r}"
            )
        ruleset = _require_text(self.ruleset_id, "ruleset_id")
        object.__setattr__(self, "ruleset_id", ruleset)

    @property
    def circuit_ref(self) -> str:
        return format_circuit_ref(LEGAL_CONSTRAINT_CIRCUIT_ID, self.circuit_version)

    def identity_payload(self) -> dict[str, Any]:
        """Canonical public payload used for the statement digest."""

        return {
            "artifact_cid": self.artifact_cid,
            "circuit_ref": self.circuit_ref,
            "circuit_version": self.circuit_version,
            "constraint_digest": self.constraint_digest,
            "jurisdiction": self.jurisdiction,
            "profile": self.profile,
            "ruleset_id": self.ruleset_id,
            "source_digest": self.source_digest,
        }

    def statement_digest(self) -> str:
        """Return ``sha256:<hex>`` of the canonical public statement."""

        return _sha256_digest(_canonical_bytes(self.identity_payload()))

    def to_public_inputs(self) -> dict[str, Any]:
        """Return public inputs embedded in the attestation envelope."""

        payload = self.identity_payload()
        payload["statement_digest"] = self.statement_digest()
        return payload

    def to_dict(self) -> dict[str, Any]:
        return dict(self.identity_payload())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalConstraintStatement":
        mapping = _as_mapping(data, "statement")
        return cls(
            constraint_digest=str(mapping.get("constraint_digest", "")),
            source_digest=str(mapping.get("source_digest", "")),
            profile=str(mapping.get("profile", "")),
            jurisdiction=str(mapping.get("jurisdiction", "") or ""),
            artifact_cid=str(mapping.get("artifact_cid", "") or ""),
            circuit_version=int(
                mapping.get("circuit_version", LEGAL_CONSTRAINT_CIRCUIT_VERSION)
            ),
            ruleset_id=str(
                mapping.get("ruleset_id", LEGAL_CONSTRAINT_RULESET_ID)
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalConstraintWitness:
    """Private opening of ``constraint_digest``.

    The witness is valid for a statement when
    ``compute_constraint_digest(payload) == statement.constraint_digest``.
    """

    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        payload_map = _as_mapping(self.payload, "witness.payload")
        ready = _json_ready(dict(payload_map))
        if not isinstance(ready, dict):
            raise LegalConstraintZKPError("witness.payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(ready))

    def opening_digest(self) -> str:
        return compute_constraint_digest(dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        """Serialize witness (reveals private data — tests/debug only)."""

        return {"payload": _json_ready(dict(self.payload))}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalConstraintWitness":
        mapping = _as_mapping(data, "witness")
        return cls(payload=_as_mapping(mapping.get("payload"), "witness.payload"))

    def binds_statement(self, statement: LegalConstraintStatement) -> bool:
        return self.opening_digest() == statement.constraint_digest


@dataclass(frozen=True, slots=True)
class LegalConstraintAttestation:
    """Serialisable prove result for LegalConstraintZKP@1."""

    statement: LegalConstraintStatement
    proof_data: bytes
    public_inputs: Mapping[str, Any]
    metadata: Mapping[str, Any]
    statement_digest: str
    timestamp: float
    interface: str = LEGAL_CONSTRAINT_ZKP_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.statement, LegalConstraintStatement):
            raise LegalConstraintZKPError(
                "statement must be a LegalConstraintStatement"
            )
        if not isinstance(self.proof_data, (bytes, bytearray)):
            raise LegalConstraintZKPError("proof_data must be bytes")
        object.__setattr__(self, "proof_data", bytes(self.proof_data))
        object.__setattr__(
            self,
            "public_inputs",
            MappingProxyType(dict(_as_mapping(self.public_inputs, "public_inputs"))),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(_as_mapping(self.metadata, "metadata"))),
        )
        object.__setattr__(
            self,
            "statement_digest",
            _require_digest(self.statement_digest, "statement_digest"),
        )
        if self.interface != LEGAL_CONSTRAINT_ZKP_INTERFACE:
            raise LegalConstraintZKPError(
                f"unsupported interface: {self.interface!r}"
            )
        if not isinstance(self.timestamp, (int, float)) or isinstance(
            self.timestamp, bool
        ):
            raise LegalConstraintZKPError("timestamp must be a number")

    @property
    def backend(self) -> str:
        return str(self.metadata.get("backend") or "simulated")

    @property
    def is_simulated(self) -> bool:
        if "is_simulated" in self.metadata:
            return bool(self.metadata["is_simulated"])
        return is_simulated_backend(self.backend)

    @property
    def proof_system(self) -> str:
        return str(self.metadata.get("proof_system") or "")

    @property
    def size_bytes(self) -> int:
        return len(self.proof_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "metadata": _json_ready(dict(self.metadata)),
            "proof_data": self.proof_data.hex(),
            "public_inputs": _json_ready(dict(self.public_inputs)),
            "statement": self.statement.to_dict(),
            "statement_digest": self.statement_digest,
            "timestamp": float(self.timestamp),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalConstraintAttestation":
        mapping = _as_mapping(data, "attestation")
        proof_raw = mapping.get("proof_data", "")
        if isinstance(proof_raw, (bytes, bytearray)):
            proof_data = bytes(proof_raw)
        elif isinstance(proof_raw, str):
            try:
                proof_data = bytes.fromhex(proof_raw)
            except ValueError as exc:
                raise LegalConstraintZKPError(
                    "proof_data must be hex-encoded bytes"
                ) from exc
        else:
            raise LegalConstraintZKPError("proof_data must be hex or bytes")
        return cls(
            statement=LegalConstraintStatement.from_dict(
                _as_mapping(mapping.get("statement"), "statement")
            ),
            proof_data=proof_data,
            public_inputs=_as_mapping(
                mapping.get("public_inputs"), "public_inputs"
            ),
            metadata=_as_mapping(mapping.get("metadata"), "metadata"),
            statement_digest=str(mapping.get("statement_digest", "")),
            timestamp=float(mapping.get("timestamp", 0.0)),
            interface=str(
                mapping.get("interface", LEGAL_CONSTRAINT_ZKP_INTERFACE)
            ),
        )


def build_statement(
    *,
    constraint_digest: str,
    source_digest: str,
    profile: str,
    jurisdiction: str = "",
    artifact_cid: str = "",
    circuit_version: int = LEGAL_CONSTRAINT_CIRCUIT_VERSION,
    ruleset_id: str = LEGAL_CONSTRAINT_RULESET_ID,
) -> LegalConstraintStatement:
    """Construct a validated public legal-constraint statement."""

    return LegalConstraintStatement(
        constraint_digest=constraint_digest,
        source_digest=source_digest,
        profile=profile,
        jurisdiction=jurisdiction,
        artifact_cid=artifact_cid,
        circuit_version=circuit_version,
        ruleset_id=ruleset_id,
    )


def build_statement_from_payload(
    payload: Mapping[str, Any],
    *,
    source_digest: str,
    profile: str,
    jurisdiction: str = "",
    artifact_cid: str = "",
) -> tuple[LegalConstraintStatement, LegalConstraintWitness]:
    """Build a statement + witness pair from a private constraint payload."""

    witness = LegalConstraintWitness(payload=payload)
    statement = build_statement(
        constraint_digest=witness.opening_digest(),
        source_digest=source_digest,
        profile=profile,
        jurisdiction=jurisdiction,
        artifact_cid=artifact_cid,
    )
    return statement, witness


def _witness_trapdoor(witness: LegalConstraintWitness) -> bytes:
    return hashlib.sha256(
        b"legal-constraint-witness|"
        + _digest_raw(witness.opening_digest())
        + b"|"
        + _canonical_bytes(dict(witness.payload))
    ).digest()


def _proof_core(
    *,
    statement_digest: str,
    trapdoor: bytes,
    seed: bytes | None = None,
) -> bytes:
    material = (
        LEGAL_CONSTRAINT_PROOF_DOMAIN
        + b"|"
        + _digest_raw(statement_digest)
        + b"|"
        + trapdoor
    )
    if seed:
        material = material + b"|" + seed
    return hashlib.sha256(material).digest()


def _simulate_proof_bytes(
    *,
    statement: LegalConstraintStatement,
    trapdoor: bytes,
    seed: bytes | None = None,
) -> bytes:
    """Build a fixed-layout simulated proof bound to the statement digest."""

    statement_digest = statement.statement_digest()
    statement_raw = _digest_raw(statement_digest)
    constraint_raw = _digest_raw(statement.constraint_digest)
    proof_hash = _proof_core(
        statement_digest=statement_digest, trapdoor=trapdoor, seed=seed
    )
    # Layout (160 bytes):
    # [0:8]     magic
    # [8:40]    proof_hash
    # [40:72]   statement_digest raw
    # [72:104]  constraint_digest raw
    # [104:160] deterministic padding from proof_hash/trapdoor
    pad_seed = hashlib.sha256(
        b"LCZKP_PAD_V1" + proof_hash + trapdoor + statement_raw
    ).digest()
    padding = (pad_seed * 3)[:56]
    proof = (
        LEGAL_CONSTRAINT_PROOF_MAGIC
        + proof_hash
        + statement_raw
        + constraint_raw
        + padding
    )
    if len(proof) != LEGAL_CONSTRAINT_PROOF_BYTE_LENGTH:
        raise LegalConstraintZKPError("internal: simulated proof length mismatch")
    return proof


def _parse_simulated_proof(proof_data: bytes) -> dict[str, bytes] | None:
    if len(proof_data) != LEGAL_CONSTRAINT_PROOF_BYTE_LENGTH:
        return None
    if proof_data[:8] != LEGAL_CONSTRAINT_PROOF_MAGIC:
        return None
    return {
        "magic": proof_data[0:8],
        "proof_hash": proof_data[8:40],
        "statement_digest_raw": proof_data[40:72],
        "constraint_digest_raw": proof_data[72:104],
        "padding": proof_data[104:160],
    }


def prove_legal_constraint_attestation(
    statement: LegalConstraintStatement,
    witness: LegalConstraintWitness,
    *,
    backend: str = "simulated",
    seed: bytes | str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> LegalConstraintAttestation:
    """Prove knowledge of a witness that opens *statement.constraint_digest*.

    The default ``backend="simulated"`` path is labeled and is **not**
    cryptographically secure.  Production backends are reserved for later
    wiring; unknown backends currently fail closed rather than silently
    claiming production strength.
    """

    if not isinstance(statement, LegalConstraintStatement):
        raise LegalConstraintZKPError(
            "statement must be a LegalConstraintStatement"
        )
    if not isinstance(witness, LegalConstraintWitness):
        raise LegalConstraintZKPError(
            "witness must be a LegalConstraintWitness"
        )
    if not witness.binds_statement(statement):
        raise LegalConstraintZKPError(
            "witness does not open statement.constraint_digest"
        )

    backend_id = str(backend or "simulated").strip().lower() or "simulated"
    simulated = is_simulated_backend(backend_id)
    if backend_id not in _SIMULATED_BACKENDS and backend_id not in _PRODUCTION_BACKENDS:
        raise LegalConstraintZKPError(
            f"unsupported legal-constraint ZKP backend: {backend_id!r}"
        )
    if not simulated:
        # Production backends are not wired for this circuit yet; fail closed
        # rather than minting a mislabeled simulated proof.
        raise LegalConstraintZKPError(
            f"production backend {backend_id!r} is not available for "
            f"{LEGAL_CONSTRAINT_CIRCUIT_REF}; use backend='simulated' or abstain"
        )

    warnings.warn(
        "LegalConstraintZKP prove path is using a SIMULATED backend. "
        "NOT cryptographically secure. zkp-required profiles must not treat "
        "this as production ZKP success.",
        UserWarning,
        stacklevel=2,
    )

    seed_bytes: bytes | None
    if seed is None:
        seed_bytes = None
    elif isinstance(seed, bytes):
        seed_bytes = seed
    elif isinstance(seed, str):
        seed_bytes = seed.encode("utf-8")
    else:
        raise LegalConstraintZKPError("seed must be bytes, str, or None")

    trapdoor = _witness_trapdoor(witness)
    proof_data = _simulate_proof_bytes(
        statement=statement, trapdoor=trapdoor, seed=seed_bytes
    )
    public_inputs = statement.to_public_inputs()
    statement_digest = statement.statement_digest()
    metadata: dict[str, Any] = {
        "backend": "simulated",
        "circuit_id": LEGAL_CONSTRAINT_CIRCUIT_ID,
        "circuit_ref": statement.circuit_ref,
        "interface": LEGAL_CONSTRAINT_ZKP_INTERFACE,
        "is_simulated": True,
        "proof_system": "legal_constraint (simulated)",
        "ruleset_id": statement.ruleset_id,
        "security": "simulation-only",
    }
    if extra_metadata:
        for key, value in dict(extra_metadata).items():
            if key in metadata and key in {
                "backend",
                "is_simulated",
                "interface",
                "circuit_ref",
            }:
                continue
            metadata[str(key)] = _json_ready(value)

    return LegalConstraintAttestation(
        statement=statement,
        proof_data=proof_data,
        public_inputs=public_inputs,
        metadata=metadata,
        statement_digest=statement_digest,
        timestamp=time.time(),
    )


def _public_inputs_match_statement(
    public_inputs: Mapping[str, Any],
    statement: LegalConstraintStatement,
) -> bool:
    expected = statement.to_public_inputs()
    for key, value in expected.items():
        if public_inputs.get(key) != value:
            return False
    return True


def verify_legal_constraint_attestation(
    attestation: LegalConstraintAttestation | Mapping[str, Any],
    *,
    expected_statement: LegalConstraintStatement | Mapping[str, Any] | None = None,
) -> bool:
    """Verify a legal-constraint attestation against its pinned statement.

    Returns True only when the proof binds the attestation statement and
    (when provided) *expected_statement*.  Any tampering of statement fields,
    public inputs, or proof embedding causes failure (fail closed).
    """

    try:
        if isinstance(attestation, Mapping):
            att = LegalConstraintAttestation.from_dict(attestation)
        elif isinstance(attestation, LegalConstraintAttestation):
            att = attestation
        else:
            return False
    except (LegalConstraintZKPError, TypeError, ValueError):
        return False

    statement = att.statement
    recomputed_digest = statement.statement_digest()
    if att.statement_digest != recomputed_digest:
        return False
    if not _public_inputs_match_statement(att.public_inputs, statement):
        return False
    if att.public_inputs.get("statement_digest") != recomputed_digest:
        return False
    if att.public_inputs.get("circuit_ref") != statement.circuit_ref:
        return False
    if str(att.metadata.get("interface") or "") not in {
        "",
        LEGAL_CONSTRAINT_ZKP_INTERFACE,
    }:
        return False

    if expected_statement is not None:
        try:
            if isinstance(expected_statement, Mapping):
                expected = LegalConstraintStatement.from_dict(expected_statement)
            elif isinstance(expected_statement, LegalConstraintStatement):
                expected = expected_statement
            else:
                return False
        except (LegalConstraintZKPError, TypeError, ValueError):
            return False
        if expected.identity_payload() != statement.identity_payload():
            return False
        if expected.statement_digest() != recomputed_digest:
            return False

    parsed = _parse_simulated_proof(att.proof_data)
    if parsed is None:
        return False
    if parsed["statement_digest_raw"] != _digest_raw(recomputed_digest):
        return False
    if parsed["constraint_digest_raw"] != _digest_raw(statement.constraint_digest):
        return False

    # Simulated proofs embed statement + constraint digests.  Without the
    # private trapdoor we cannot recompute proof_hash; structural binding of
    # digests into the proof bytes is the verification surface for this path.
    # Reject empty or all-zero proof hashes as malformed.
    if parsed["proof_hash"] == b"\x00" * 32:
        return False
    if len(parsed["padding"]) != 56:
        return False

    backend = str(att.metadata.get("backend") or "").lower()
    if att.is_simulated or is_simulated_backend(backend):
        # Require explicit simulation labeling so zkp-required can filter later.
        if att.metadata.get("is_simulated") is False:
            return False
        proof_system = str(att.metadata.get("proof_system") or "").lower()
        if "simulated" not in proof_system and "simulation" not in str(
            att.metadata.get("security") or ""
        ).lower():
            # Accept only when either proof_system or security marks simulation.
            if "sim" not in backend:
                return False

    return True


def attestation_satisfies_zkp_required(
    attestation: LegalConstraintAttestation | Mapping[str, Any],
    *,
    require_zkp_verify: bool = True,
    accept_simulated_zkp: bool = False,
) -> bool:
    """Return whether *attestation* may satisfy a zkp-required style profile.

    Profile semantics (plan §2.4 / LIG-014):

    * When ``require_zkp_verify`` is False, this helper returns True only if the
      attestation verifies (optional path).
    * When ``require_zkp_verify`` is True and ``accept_simulated_zkp`` is False
      (production ``zkp-required``), simulated attestations never satisfy the
      profile even if structural verify succeeds.
    * Missing / invalid attestations never satisfy the profile (fail closed).

    Gate join logic (LIG-015) can call this when ``require_zkp_verify`` is set.
    """

    try:
        if isinstance(attestation, Mapping):
            att = LegalConstraintAttestation.from_dict(attestation)
        elif isinstance(attestation, LegalConstraintAttestation):
            att = attestation
        else:
            return False
    except (LegalConstraintZKPError, TypeError, ValueError):
        return False

    if not verify_legal_constraint_attestation(att):
        return False

    if not require_zkp_verify:
        return True

    if att.is_simulated and not accept_simulated_zkp:
        return False
    return True


def prove_and_verify(
    statement: LegalConstraintStatement,
    witness: LegalConstraintWitness,
    *,
    backend: str = "simulated",
    seed: bytes | str | None = None,
) -> tuple[LegalConstraintAttestation, bool]:
    """Convenience: prove then verify the same statement (honest path)."""

    attestation = prove_legal_constraint_attestation(
        statement, witness, backend=backend, seed=seed
    )
    return attestation, verify_legal_constraint_attestation(
        attestation, expected_statement=statement
    )


__all__ = [
    "LEGAL_CONSTRAINT_CIRCUIT_ID",
    "LEGAL_CONSTRAINT_CIRCUIT_REF",
    "LEGAL_CONSTRAINT_CIRCUIT_VERSION",
    "LEGAL_CONSTRAINT_PROOF_BYTE_LENGTH",
    "LEGAL_CONSTRAINT_PROOF_DOMAIN",
    "LEGAL_CONSTRAINT_PROOF_MAGIC",
    "LEGAL_CONSTRAINT_RULESET_ID",
    "LEGAL_CONSTRAINT_ZKP_INTERFACE",
    "LegalConstraintAttestation",
    "LegalConstraintStatement",
    "LegalConstraintWitness",
    "LegalConstraintZKPError",
    "attestation_satisfies_zkp_required",
    "build_statement",
    "build_statement_from_payload",
    "compute_constraint_digest",
    "is_simulated_backend",
    "prove_and_verify",
    "prove_legal_constraint_attestation",
    "verify_legal_constraint_attestation",
]
