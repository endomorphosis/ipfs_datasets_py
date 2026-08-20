"""Canonical proof statements and public/private input declarations (IPS-010).

Datasets semantic authority for domain-separated statement payloads.  Each
evidence class carries an exact claim boundary, explicit public inputs, and a
private-input commitment that never embeds witness bytes.

Rules:

* only ``DirectExecutionStatement`` may assert a direct-computation claim;
* ``ReceiptAggregationStatement`` cannot serialize or load a direct-execution
  claim (consistency/completeness of admitted receipts only);
* private commitments are digests/CIDs only — witness material is rejected
  from every public and commitment serialization surface;
* claims bind exact program/circuit/inputs/outputs and state what remains
  trusted.

Interfaces: ``CanonicalProofStatement``, ``DirectExecutionStatement``,
``ReceiptAggregationStatement``, ``ForestTransitionStatement``,
``PublicInputDeclaration``, ``PrivateInputCommitment``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .evidence import EvidenceClass, EvidenceClassError

STATEMENTS_SUBSET: Final[str] = "ips/canonical-statements@1"
STATEMENTS_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/statements"
)
SCHEMA_MAJOR: Final[int] = 1
SCHEMA_VERSION: Final[str] = f"{SCHEMA_MAJOR}.0.0"
CANONICALIZATION_VERSION: Final[str] = f"ips/statement-canonicalization@{SCHEMA_MAJOR}"

PUBLIC_INPUT_SCHEMA: Final[str] = (
    f"{STATEMENTS_NAMESPACE}/public-input-declaration@{SCHEMA_MAJOR}"
)
PRIVATE_COMMITMENT_SCHEMA: Final[str] = (
    f"{STATEMENTS_NAMESPACE}/private-input-commitment@{SCHEMA_MAJOR}"
)
CANONICAL_STATEMENT_SCHEMA: Final[str] = (
    f"{STATEMENTS_NAMESPACE}/canonical-proof-statement@{SCHEMA_MAJOR}"
)
DIRECT_EXECUTION_SCHEMA: Final[str] = (
    f"{STATEMENTS_NAMESPACE}/direct-execution-statement@{SCHEMA_MAJOR}"
)
RECEIPT_AGGREGATION_SCHEMA: Final[str] = (
    f"{STATEMENTS_NAMESPACE}/receipt-aggregation-statement@{SCHEMA_MAJOR}"
)
FOREST_TRANSITION_SCHEMA: Final[str] = (
    f"{STATEMENTS_NAMESPACE}/forest-transition-statement@{SCHEMA_MAJOR}"
)

MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_FIELD_NAME_BYTES: Final[int] = 128
MAX_PUBLIC_FIELDS: Final[int] = 64
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1

# Domain separators bind statement kind so payloads cannot be cross-typed.
DOMAIN_DIRECT_EXECUTION: Final[str] = "ips.statement.direct_execution.v1"
DOMAIN_RECEIPT_AGGREGATION: Final[str] = "ips.statement.receipt_aggregation.v1"
DOMAIN_FOREST_TRANSITION: Final[str] = "ips.statement.forest_transition.v1"
DOMAIN_CANONICAL: Final[str] = "ips.statement.canonical.v1"

# Fields that must never appear on public or commitment surfaces.
WITNESS_AND_SECRET_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "witness",
        "private_witness",
        "witness_bytes",
        "witness_bytes_hex",
        "hidden_witness",
        "proving_key_bytes",
        "private_key",
        "secret",
        "password",
        "private_preimage",
        "preimage",
        "opening",
        "receipt_bytes",
        "receipt_bytes_hex",
    }
)

_PRIVATE_KEY_MARKERS: Final[tuple[str, ...]] = (
    "witness",
    "private_key",
    "secret",
    "password",
    "preimage",
    "opening",
    "proving_key_bytes",
)

# Structural keys that mention "witness" only to deny openings, not to carry them.
_ALLOWED_WITNESS_META_KEYS: Final[frozenset[str]] = frozenset(
    {
        "reveals_witness",
        "committed_roles",
    }
)


class StatementError(EvidenceClassError):
    """Canonical statement or public/private input contract violation."""


class StatementKind(str, Enum):
    CANONICAL = "canonical"
    DIRECT_EXECUTION = "direct_execution"
    RECEIPT_AGGREGATION = "receipt_aggregation"
    FOREST_TRANSITION = "forest_transition"


def closed_statement_kind_values() -> frozenset[str]:
    return frozenset(item.value for item in StatementKind)


def parse_statement_kind(value: Any) -> StatementKind:
    if isinstance(value, StatementKind):
        return value
    if not isinstance(value, str) or not value.strip():
        raise StatementError("StatementKind must be a non-empty closed string")
    try:
        return StatementKind(value.strip())
    except ValueError as exc:
        raise StatementError(
            f"unknown StatementKind {value!r}; closed set is "
            f"{sorted(item.value for item in StatementKind)}"
        ) from exc


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StatementError(f"{field} must be a non-empty string")
    text = value.strip()
    if text != value:
        raise StatementError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise StatementError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_digest_or_cid(value: Any, field: str) -> str:
    text = _require_identifier(value, field)
    if text.startswith("sha256:"):
        hex_part = text[7:]
        if len(hex_part) != 64 or any(c not in "0123456789abcdef" for c in hex_part):
            raise StatementError(f"{field} must be sha256:<64 lowercase hex>")
        return text
    if text.startswith("b") and 20 <= len(text) <= 128:
        return text
    if len(text) >= 8:
        return text
    raise StatementError(f"{field} is not a digest or CID")


def _require_sorted_unique(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StatementError(f"{field} must be a sequence")
    items = tuple(_require_digest_or_cid(item, field) for item in value)
    if list(items) != sorted(items):
        raise StatementError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise StatementError(f"{field} must be unique")
    return items


def _require_nonneg_int(value: Any, field: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise StatementError(f"{field} must be a finite int")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise StatementError(f"{field} is out of bounds")
    return value


def _canonical_json(payload: Mapping[str, Any]) -> str:
    _reject_witness_material(payload, surface="canonical")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _content_address(payload: Mapping[str, Any]) -> str:
    """Content-address a statement payload without requiring multiformats."""

    return _sha256_digest(_canonical_json(payload).encode("utf-8"))


def _is_private_key_name(key: str) -> bool:
    lowered = key.casefold().replace("-", "_")
    if lowered in WITNESS_AND_SECRET_FIELDS:
        return True
    return any(marker in lowered for marker in _PRIVATE_KEY_MARKERS)


def _reject_witness_material(payload: Mapping[str, Any], *, surface: str) -> None:
    keys = {str(key) for key in payload}
    leaked = (keys & WITNESS_AND_SECRET_FIELDS) - _ALLOWED_WITNESS_META_KEYS
    if leaked:
        raise StatementError(
            f"{surface} must not contain witness or secret fields: {sorted(leaked)}"
        )
    for key in keys:
        if key in _ALLOWED_WITNESS_META_KEYS:
            continue
        if _is_private_key_name(str(key)):
            raise StatementError(
                f"{surface} rejects private material key {key!r}"
            )


def _reject_direct_claim_on_non_direct(
    payload: Mapping[str, Any], *, statement_kind: StatementKind
) -> None:
    if payload.get("direct_computation_claim") is True and (
        statement_kind is not StatementKind.DIRECT_EXECUTION
    ):
        raise StatementError(
            "direct-execution claims require DirectExecutionStatement; "
            f"{statement_kind.value} cannot serialize a direct-execution claim"
        )
    if "direct_computation_claim" in payload and statement_kind is (
        StatementKind.RECEIPT_AGGREGATION
    ):
        # Even false/null must not appear: aggregation never speaks this claim.
        raise StatementError(
            "ReceiptAggregationStatement cannot serialize a direct-execution claim"
        )


# ---------------------------------------------------------------------------
# Public / private input declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicInputField:
    """One named public input bound into a statement."""

    name: str
    value: str
    role: str = "binding"

    def __post_init__(self) -> None:
        name = _require_identifier(self.name, "public_input.name")
        if len(name.encode("utf-8")) > MAX_FIELD_NAME_BYTES:
            raise StatementError("public_input.name exceeds field name bound")
        if _is_private_key_name(name):
            raise StatementError(f"public input name {name!r} is private material")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", _require_identifier(self.value, "public_input.value"))
        object.__setattr__(self, "role", _require_identifier(self.role, "public_input.role"))

    def to_canonical(self) -> dict[str, str]:
        return {"name": self.name, "role": self.role, "value": self.value}


@dataclass(frozen=True, slots=True)
class PublicInputDeclaration:
    """Explicit public inputs visible to verifiers and cache keys."""

    fields: tuple[PublicInputField, ...]
    schema: str = PUBLIC_INPUT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.fields, tuple):
            raise StatementError("public input fields must be a tuple")
        if len(self.fields) > MAX_PUBLIC_FIELDS:
            raise StatementError(
                f"public inputs exceed bound of {MAX_PUBLIC_FIELDS} fields"
            )
        names = [field.name for field in self.fields]
        if list(names) != sorted(names):
            raise StatementError("public input fields must be sorted by name")
        if len(set(names)) != len(names):
            raise StatementError("public input field names must be unique")
        for field in self.fields:
            if not isinstance(field, PublicInputField):
                raise StatementError("fields must be PublicInputField instances")
        object.__setattr__(
            self, "schema", _require_identifier(self.schema, "public_input.schema")
        )
        if self.schema != PUBLIC_INPUT_SCHEMA:
            raise StatementError(f"public input schema must be {PUBLIC_INPUT_SCHEMA}")

    def to_canonical(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "fields": [field.to_canonical() for field in self.fields],
        }
        _reject_witness_material(payload, surface="public_inputs")
        return payload

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def public_input_cid(self) -> str:
        return _content_address(self.to_canonical())

    def as_mapping(self) -> dict[str, str]:
        return {field.name: field.value for field in self.fields}

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> PublicInputDeclaration:
        if not isinstance(payload, Mapping):
            raise StatementError("public inputs must be a mapping")
        _reject_witness_material(payload, surface="public_inputs")
        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)):
            raise StatementError("public input fields must be a sequence")
        fields: list[PublicInputField] = []
        for item in raw_fields:
            if not isinstance(item, Mapping):
                raise StatementError("each public input field must be a mapping")
            fields.append(
                PublicInputField(
                    name=str(item.get("name") or ""),
                    value=str(item.get("value") or ""),
                    role=str(item.get("role") or "binding"),
                )
            )
        return cls(fields=tuple(fields), schema=str(payload.get("schema") or PUBLIC_INPUT_SCHEMA))

    @classmethod
    def from_mapping(cls, values: Mapping[str, str], *, role: str = "binding") -> PublicInputDeclaration:
        if not isinstance(values, Mapping):
            raise StatementError("public input mapping must be a mapping")
        _reject_witness_material(values, surface="public_inputs")
        fields = tuple(
            PublicInputField(name=name, value=str(values[name]), role=role)
            for name in sorted(values)
        )
        return cls(fields=fields)


@dataclass(frozen=True, slots=True)
class PrivateInputCommitment:
    """Commitment to private witness material without revealing the witness.

    Public artifacts and statement serializations may carry only the commitment
    digest/CID and scheme identity.  Opening bytes and witness preimages are
    forbidden on this surface.
    """

    commitment: str
    commitment_scheme: str = "sha256-canonical-json-v1"
    committed_roles: tuple[str, ...] = ("witness",)
    schema: str = PRIVATE_COMMITMENT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "commitment",
            _require_digest_or_cid(self.commitment, "private_input_commitment"),
        )
        object.__setattr__(
            self,
            "commitment_scheme",
            _require_identifier(self.commitment_scheme, "commitment_scheme"),
        )
        if not isinstance(self.committed_roles, tuple) or not self.committed_roles:
            raise StatementError("committed_roles must be a non-empty tuple")
        roles = tuple(_require_identifier(role, "committed_role") for role in self.committed_roles)
        if list(roles) != sorted(roles):
            raise StatementError("committed_roles must be canonically sorted")
        if len(set(roles)) != len(roles):
            raise StatementError("committed_roles must be unique")
        object.__setattr__(self, "committed_roles", roles)
        object.__setattr__(
            self, "schema", _require_identifier(self.schema, "private_commitment.schema")
        )
        if self.schema != PRIVATE_COMMITMENT_SCHEMA:
            raise StatementError(
                f"private commitment schema must be {PRIVATE_COMMITMENT_SCHEMA}"
            )

    def to_canonical(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "commitment": self.commitment,
            "commitment_scheme": self.commitment_scheme,
            "committed_roles": list(self.committed_roles),
            "reveals_witness": False,
        }
        _reject_witness_material(
            {k: v for k, v in payload.items() if k != "committed_roles"},
            surface="private_input_commitment",
        )
        # committed_roles may literally list the role name "witness" as the
        # abstract role being committed — that is not a witness opening.
        return payload

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def commitment_cid(self) -> str:
        return self.commitment

    def reveals_witness(self) -> bool:
        """Private commitments never reveal witness openings."""

        return False

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> PrivateInputCommitment:
        if not isinstance(payload, Mapping):
            raise StatementError("private commitment must be a mapping")
        # Reject openings even when nested under unexpected keys.
        for key in payload:
            key_text = str(key)
            if key_text in _ALLOWED_WITNESS_META_KEYS:
                continue
            if key_text in WITNESS_AND_SECRET_FIELDS or _is_private_key_name(key_text):
                raise StatementError(
                    f"private commitment must not contain witness material key {key!r}"
                )
        if payload.get("reveals_witness") is True:
            raise StatementError("private commitments must not reveal witness")
        raw_roles = payload.get("committed_roles", ("witness",))
        if isinstance(raw_roles, str):
            raise StatementError("committed_roles must be a sequence")
        if not isinstance(raw_roles, Sequence):
            raise StatementError("committed_roles must be a sequence")
        return cls(
            commitment=str(payload.get("commitment") or ""),
            commitment_scheme=str(
                payload.get("commitment_scheme") or "sha256-canonical-json-v1"
            ),
            committed_roles=tuple(str(item) for item in raw_roles),
            schema=str(payload.get("schema") or PRIVATE_COMMITMENT_SCHEMA),
        )

    @classmethod
    def commit_witness_bytes(
        cls,
        witness_bytes: bytes,
        *,
        commitment_scheme: str = "sha256-raw-v1",
        committed_roles: tuple[str, ...] = ("witness",),
    ) -> PrivateInputCommitment:
        """Derive a public commitment from private witness bytes.

        The returned object holds only the digest; *witness_bytes* are not
        retained on the commitment record.
        """

        if not isinstance(witness_bytes, (bytes, bytearray)):
            raise StatementError("witness_bytes must be bytes")
        raw = bytes(witness_bytes)
        if not raw:
            raise StatementError("witness_bytes must be non-empty")
        return cls(
            commitment=_sha256_digest(raw),
            commitment_scheme=commitment_scheme,
            committed_roles=tuple(sorted(committed_roles)),
        )


# ---------------------------------------------------------------------------
# Canonical statement base
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalProofStatement:
    """Domain-separated statement envelope shared by every evidence class."""

    statement_kind: StatementKind
    evidence_class: EvidenceClass
    domain_separator: str
    computation_id: str
    public_inputs: PublicInputDeclaration
    private_input_commitment: PrivateInputCommitment
    establishes: str
    does_not_establish: str
    trusted_assumptions: tuple[str, ...]
    proof_system_id: str
    circuit_id: str
    schema: str = CANONICAL_STATEMENT_SCHEMA
    schema_version: str = SCHEMA_VERSION
    canonicalization_version: str = CANONICALIZATION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.statement_kind, StatementKind):
            object.__setattr__(
                self, "statement_kind", parse_statement_kind(self.statement_kind)
            )
        if not isinstance(self.evidence_class, EvidenceClass):
            try:
                object.__setattr__(
                    self, "evidence_class", EvidenceClass(self.evidence_class)
                )
            except ValueError as exc:
                raise StatementError(
                    f"unknown evidence_class {self.evidence_class!r}"
                ) from exc
        object.__setattr__(
            self,
            "domain_separator",
            _require_identifier(self.domain_separator, "domain_separator"),
        )
        object.__setattr__(
            self,
            "computation_id",
            _require_identifier(self.computation_id, "computation_id"),
        )
        if not isinstance(self.public_inputs, PublicInputDeclaration):
            raise StatementError("public_inputs must be PublicInputDeclaration")
        if not isinstance(self.private_input_commitment, PrivateInputCommitment):
            raise StatementError(
                "private_input_commitment must be PrivateInputCommitment"
            )
        object.__setattr__(
            self, "establishes", _require_identifier(self.establishes, "establishes")
        )
        object.__setattr__(
            self,
            "does_not_establish",
            _require_identifier(self.does_not_establish, "does_not_establish"),
        )
        if not isinstance(self.trusted_assumptions, tuple):
            raise StatementError("trusted_assumptions must be a tuple")
        assumptions = tuple(
            _require_identifier(item, "trusted_assumption")
            for item in self.trusted_assumptions
        )
        if list(assumptions) != sorted(assumptions):
            raise StatementError("trusted_assumptions must be canonically sorted")
        if len(set(assumptions)) != len(assumptions):
            raise StatementError("trusted_assumptions must be unique")
        object.__setattr__(self, "trusted_assumptions", assumptions)
        object.__setattr__(
            self,
            "proof_system_id",
            _require_identifier(self.proof_system_id, "proof_system_id"),
        )
        object.__setattr__(
            self, "circuit_id", _require_identifier(self.circuit_id, "circuit_id")
        )
        object.__setattr__(self, "schema", _require_identifier(self.schema, "schema"))
        object.__setattr__(
            self,
            "schema_version",
            _require_identifier(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_identifier(
                self.canonicalization_version, "canonicalization_version"
            ),
        )
        if self.private_input_commitment.reveals_witness():
            raise StatementError("private commitments reveal no witness")

    @property
    def direct_computation_claim(self) -> bool:
        return self.statement_kind is StatementKind.DIRECT_EXECUTION

    def to_canonical(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "canonicalization_version": self.canonicalization_version,
            "statement_kind": self.statement_kind.value,
            "evidence_class": self.evidence_class.value,
            "domain_separator": self.domain_separator,
            "computation_id": self.computation_id,
            "public_inputs": self.public_inputs.to_canonical(),
            "public_input_cid": self.public_inputs.public_input_cid(),
            "private_input_commitment": self.private_input_commitment.to_canonical(),
            "establishes": self.establishes,
            "does_not_establish": self.does_not_establish,
            "trusted_assumptions": list(self.trusted_assumptions),
            "proof_system_id": self.proof_system_id,
            "circuit_id": self.circuit_id,
            "statements_subset": STATEMENTS_SUBSET,
        }
        if self.direct_computation_claim:
            payload["direct_computation_claim"] = True
        else:
            # Non-direct kinds either omit the claim (aggregation) or mark false.
            if self.statement_kind is not StatementKind.RECEIPT_AGGREGATION:
                payload["direct_computation_claim"] = False
        _reject_witness_material(payload, surface="statement")
        if self.statement_kind is StatementKind.RECEIPT_AGGREGATION:
            _reject_direct_claim_on_non_direct(
                payload, statement_kind=StatementKind.RECEIPT_AGGREGATION
            )
        return payload

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def statement_cid(self) -> str:
        return _content_address(self.to_canonical())

    def binds_computation(self, computation_id: str) -> bool:
        return self.computation_id == computation_id

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> CanonicalProofStatement:
        if not isinstance(payload, Mapping):
            raise StatementError("statement payload must be a mapping")
        _reject_witness_material(payload, surface="statement")
        kind = parse_statement_kind(payload.get("statement_kind") or "canonical")
        if kind is not StatementKind.CANONICAL:
            # Dispatch to specialized loaders for domain-separated kinds.
            return statement_from_canonical(payload)  # type: ignore[return-value]
        if payload.get("direct_computation_claim") is True:
            raise StatementError(
                "canonical envelope cannot carry a direct-execution claim"
            )
        evidence_raw = payload.get("evidence_class")
        try:
            evidence = (
                evidence_raw
                if isinstance(evidence_raw, EvidenceClass)
                else EvidenceClass(str(evidence_raw or ""))
            )
        except ValueError as exc:
            raise StatementError(f"unknown evidence_class {evidence_raw!r}") from exc
        public_raw = payload.get("public_inputs")
        if not isinstance(public_raw, Mapping):
            raise StatementError("public_inputs must be a mapping")
        private_raw = payload.get("private_input_commitment")
        if not isinstance(private_raw, Mapping):
            raise StatementError("private_input_commitment must be a mapping")
        return cls(
            statement_kind=StatementKind.CANONICAL,
            evidence_class=evidence,
            domain_separator=str(payload.get("domain_separator") or DOMAIN_CANONICAL),
            computation_id=str(payload.get("computation_id") or ""),
            public_inputs=PublicInputDeclaration.from_canonical(public_raw),
            private_input_commitment=PrivateInputCommitment.from_canonical(private_raw),
            establishes=str(payload.get("establishes") or ""),
            does_not_establish=str(payload.get("does_not_establish") or ""),
            trusted_assumptions=tuple(
                str(item) for item in (payload.get("trusted_assumptions") or ())
            ),
            proof_system_id=str(payload.get("proof_system_id") or ""),
            circuit_id=str(payload.get("circuit_id") or ""),
            schema=str(payload.get("schema") or CANONICAL_STATEMENT_SCHEMA),
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DirectExecutionStatement:
    """Declared program/circuit ran over committed inputs producing committed output.

    Binds exact program, circuit, proof system, public inputs, private
    commitment, input commitment, and output commitment.  Correctness beyond
    those exact bindings remains trusted only under declared assumptions.
    """

    program_id: str
    circuit_id: str
    proof_system_id: str
    input_commitment: str
    output_commitment: str
    public_inputs: PublicInputDeclaration
    private_input_commitment: PrivateInputCommitment
    trusted_assumptions: tuple[str, ...] = (
        "proof_system_soundness",
        "verification_key_authenticity",
    )
    property_id: str = "declared_output_property"
    schema: str = DIRECT_EXECUTION_SCHEMA
    schema_version: str = SCHEMA_VERSION
    canonicalization_version: str = CANONICALIZATION_VERSION

    ESTABLISHES: Final[str] = (
        "the declared program/verifier ran inside the proof system over "
        "committed inputs and produced the committed output/property"
    )
    DOES_NOT_ESTABLISH: Final[str] = (
        "correctness beyond that exact program, inputs, outputs, and "
        "proof-system assumptions"
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "program_id", _require_identifier(self.program_id, "program_id")
        )
        object.__setattr__(
            self, "circuit_id", _require_identifier(self.circuit_id, "circuit_id")
        )
        object.__setattr__(
            self,
            "proof_system_id",
            _require_identifier(self.proof_system_id, "proof_system_id"),
        )
        object.__setattr__(
            self,
            "input_commitment",
            _require_digest_or_cid(self.input_commitment, "input_commitment"),
        )
        object.__setattr__(
            self,
            "output_commitment",
            _require_digest_or_cid(self.output_commitment, "output_commitment"),
        )
        if not isinstance(self.public_inputs, PublicInputDeclaration):
            raise StatementError("public_inputs must be PublicInputDeclaration")
        if not isinstance(self.private_input_commitment, PrivateInputCommitment):
            raise StatementError(
                "private_input_commitment must be PrivateInputCommitment"
            )
        if self.private_input_commitment.reveals_witness():
            raise StatementError("private commitments reveal no witness")
        assumptions = tuple(
            _require_identifier(item, "trusted_assumption")
            for item in self.trusted_assumptions
        )
        if list(assumptions) != sorted(assumptions):
            raise StatementError("trusted_assumptions must be canonically sorted")
        if len(set(assumptions)) != len(assumptions):
            raise StatementError("trusted_assumptions must be unique")
        object.__setattr__(self, "trusted_assumptions", assumptions)
        object.__setattr__(
            self, "property_id", _require_identifier(self.property_id, "property_id")
        )
        object.__setattr__(self, "schema", _require_identifier(self.schema, "schema"))
        if self.schema != DIRECT_EXECUTION_SCHEMA:
            raise StatementError(
                f"direct execution schema must be {DIRECT_EXECUTION_SCHEMA}"
            )
        # Public inputs must bind the declared computation identities.
        bound = self.public_inputs.as_mapping()
        for key, expected in (
            ("program_id", self.program_id),
            ("circuit_id", self.circuit_id),
            ("proof_system_id", self.proof_system_id),
            ("input_commitment", self.input_commitment),
            ("output_commitment", self.output_commitment),
        ):
            if key in bound and bound[key] != expected:
                raise StatementError(
                    f"public input {key!r} does not bind declared computation"
                )

    @property
    def statement_kind(self) -> StatementKind:
        return StatementKind.DIRECT_EXECUTION

    @property
    def evidence_class(self) -> EvidenceClass:
        return EvidenceClass.DIRECT_EXECUTION_PROOF

    @property
    def domain_separator(self) -> str:
        return DOMAIN_DIRECT_EXECUTION

    @property
    def computation_id(self) -> str:
        return self.program_id

    @property
    def direct_computation_claim(self) -> bool:
        return True

    def binds_declared_computation(self) -> bool:
        """True when public bindings match program/circuit/inputs/outputs."""

        bound = self.public_inputs.as_mapping()
        required = {
            "program_id": self.program_id,
            "circuit_id": self.circuit_id,
            "proof_system_id": self.proof_system_id,
            "input_commitment": self.input_commitment,
            "output_commitment": self.output_commitment,
        }
        for key, expected in required.items():
            if bound.get(key, expected) != expected:
                return False
        return bool(
            self.program_id
            and self.circuit_id
            and self.input_commitment
            and self.output_commitment
            and self.proof_system_id
        )

    def to_canonical(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "canonicalization_version": self.canonicalization_version,
            "statement_kind": self.statement_kind.value,
            "evidence_class": self.evidence_class.value,
            "domain_separator": self.domain_separator,
            "program_id": self.program_id,
            "computation_id": self.computation_id,
            "circuit_id": self.circuit_id,
            "proof_system_id": self.proof_system_id,
            "input_commitment": self.input_commitment,
            "output_commitment": self.output_commitment,
            "property_id": self.property_id,
            "public_inputs": self.public_inputs.to_canonical(),
            "public_input_cid": self.public_inputs.public_input_cid(),
            "private_input_commitment": self.private_input_commitment.to_canonical(),
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
            "trusted_assumptions": list(self.trusted_assumptions),
            "direct_computation_claim": True,
            "statements_subset": STATEMENTS_SUBSET,
        }
        _reject_witness_material(payload, surface="direct_execution_statement")
        return payload

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def statement_cid(self) -> str:
        return _content_address(self.to_canonical())

    def as_canonical_envelope(self) -> CanonicalProofStatement:
        return CanonicalProofStatement(
            statement_kind=StatementKind.DIRECT_EXECUTION,
            evidence_class=EvidenceClass.DIRECT_EXECUTION_PROOF,
            domain_separator=DOMAIN_DIRECT_EXECUTION,
            computation_id=self.program_id,
            public_inputs=self.public_inputs,
            private_input_commitment=self.private_input_commitment,
            establishes=self.ESTABLISHES,
            does_not_establish=self.DOES_NOT_ESTABLISH,
            trusted_assumptions=self.trusted_assumptions,
            proof_system_id=self.proof_system_id,
            circuit_id=self.circuit_id,
            schema=CANONICAL_STATEMENT_SCHEMA,
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> DirectExecutionStatement:
        if not isinstance(payload, Mapping):
            raise StatementError("direct execution payload must be a mapping")
        _reject_witness_material(payload, surface="direct_execution_statement")
        if payload.get("statement_kind") not in (
            None,
            StatementKind.DIRECT_EXECUTION.value,
        ):
            if payload.get("statement_kind") != StatementKind.DIRECT_EXECUTION.value:
                raise StatementError("payload is not DirectExecutionStatement")
        if payload.get("evidence_class") not in (
            None,
            EvidenceClass.DIRECT_EXECUTION_PROOF.value,
        ):
            if (
                payload.get("evidence_class")
                != EvidenceClass.DIRECT_EXECUTION_PROOF.value
            ):
                raise StatementError(
                    "DirectExecutionStatement requires DirectExecutionProof evidence"
                )
        if payload.get("direct_computation_claim") is not True:
            raise StatementError(
                "direct proof statement requires direct_computation_claim=true"
            )
        if payload.get("domain_separator") not in (None, DOMAIN_DIRECT_EXECUTION):
            if payload.get("domain_separator") != DOMAIN_DIRECT_EXECUTION:
                raise StatementError("domain separator mismatch for direct execution")
        public_raw = payload.get("public_inputs")
        if not isinstance(public_raw, Mapping):
            raise StatementError("public_inputs must be a mapping")
        private_raw = payload.get("private_input_commitment")
        if not isinstance(private_raw, Mapping):
            raise StatementError("private_input_commitment must be a mapping")
        program_id = str(
            payload.get("program_id") or payload.get("computation_id") or ""
        )
        return cls(
            program_id=program_id,
            circuit_id=str(payload.get("circuit_id") or ""),
            proof_system_id=str(payload.get("proof_system_id") or ""),
            input_commitment=str(payload.get("input_commitment") or ""),
            output_commitment=str(payload.get("output_commitment") or ""),
            public_inputs=PublicInputDeclaration.from_canonical(public_raw),
            private_input_commitment=PrivateInputCommitment.from_canonical(private_raw),
            trusted_assumptions=tuple(
                str(item) for item in (payload.get("trusted_assumptions") or ())
            ),
            property_id=str(payload.get("property_id") or "declared_output_property"),
            schema=str(payload.get("schema") or DIRECT_EXECUTION_SCHEMA),
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Receipt aggregation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReceiptAggregationStatement:
    """Admitted receipt digests satisfy the aggregation circuit.

    Establishes consistency and completeness of the committed receipt set only.
    Never asserts that underlying programs executed; direct-computation claim
    language is rejected at construction and serialization time.
    """

    circuit_id: str
    proof_system_id: str
    receipt_digests: tuple[str, ...]
    public_inputs: PublicInputDeclaration
    private_input_commitment: PrivateInputCommitment
    trusted_assumptions: tuple[str, ...] = (
        "receipt_signature_verification",
        "signer_allowlist_trust",
    )
    aggregation_root: str = ""
    schema: str = RECEIPT_AGGREGATION_SCHEMA
    schema_version: str = SCHEMA_VERSION
    canonicalization_version: str = CANONICALIZATION_VERSION

    ESTABLISHES: Final[str] = (
        "admitted committed receipt fields satisfy the aggregation circuit; "
        "exact required receipt set/count/order has no blocking circuit status"
    )
    DOES_NOT_ESTABLISH: Final[str] = (
        "underlying tests ran unless signature verification and signer trust "
        "are inside the declared statement; never direct program execution"
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "circuit_id", _require_identifier(self.circuit_id, "circuit_id")
        )
        object.__setattr__(
            self,
            "proof_system_id",
            _require_identifier(self.proof_system_id, "proof_system_id"),
        )
        digests = _require_sorted_unique(self.receipt_digests, "receipt_digests")
        if not digests:
            raise StatementError("receipt_digests must be non-empty")
        object.__setattr__(self, "receipt_digests", digests)
        if not isinstance(self.public_inputs, PublicInputDeclaration):
            raise StatementError("public_inputs must be PublicInputDeclaration")
        if not isinstance(self.private_input_commitment, PrivateInputCommitment):
            raise StatementError(
                "private_input_commitment must be PrivateInputCommitment"
            )
        if self.private_input_commitment.reveals_witness():
            raise StatementError("private commitments reveal no witness")
        assumptions = tuple(
            _require_identifier(item, "trusted_assumption")
            for item in self.trusted_assumptions
        )
        if list(assumptions) != sorted(assumptions):
            raise StatementError("trusted_assumptions must be canonically sorted")
        if len(set(assumptions)) != len(assumptions):
            raise StatementError("trusted_assumptions must be unique")
        object.__setattr__(self, "trusted_assumptions", assumptions)
        if self.aggregation_root:
            object.__setattr__(
                self,
                "aggregation_root",
                _require_digest_or_cid(self.aggregation_root, "aggregation_root"),
            )
        object.__setattr__(self, "schema", _require_identifier(self.schema, "schema"))
        if self.schema != RECEIPT_AGGREGATION_SCHEMA:
            raise StatementError(
                f"receipt aggregation schema must be {RECEIPT_AGGREGATION_SCHEMA}"
            )

    @property
    def statement_kind(self) -> StatementKind:
        return StatementKind.RECEIPT_AGGREGATION

    @property
    def evidence_class(self) -> EvidenceClass:
        return EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF

    @property
    def domain_separator(self) -> str:
        return DOMAIN_RECEIPT_AGGREGATION

    @property
    def computation_id(self) -> str:
        return self.circuit_id

    @property
    def direct_computation_claim(self) -> bool:
        return False

    def to_canonical(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "canonicalization_version": self.canonicalization_version,
            "statement_kind": self.statement_kind.value,
            "evidence_class": self.evidence_class.value,
            "domain_separator": self.domain_separator,
            "computation_id": self.computation_id,
            "circuit_id": self.circuit_id,
            "proof_system_id": self.proof_system_id,
            "receipt_digests": list(self.receipt_digests),
            "receipt_count": len(self.receipt_digests),
            "aggregation_root": self.aggregation_root,
            "public_inputs": self.public_inputs.to_canonical(),
            "public_input_cid": self.public_inputs.public_input_cid(),
            "private_input_commitment": self.private_input_commitment.to_canonical(),
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
            "trusted_assumptions": list(self.trusted_assumptions),
            "statements_subset": STATEMENTS_SUBSET,
        }
        # Explicitly omit direct_computation_claim; presence is a violation.
        _reject_witness_material(payload, surface="receipt_aggregation_statement")
        _reject_direct_claim_on_non_direct(
            payload, statement_kind=StatementKind.RECEIPT_AGGREGATION
        )
        if "direct_computation_claim" in payload:
            raise StatementError(
                "ReceiptAggregationStatement cannot serialize a direct-execution claim"
            )
        return payload

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def statement_cid(self) -> str:
        return _content_address(self.to_canonical())

    def serialize(self) -> dict[str, Any]:
        """Serialize aggregation statement; refuses direct-execution claims."""

        return self.to_canonical()

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ReceiptAggregationStatement:
        if not isinstance(payload, Mapping):
            raise StatementError("receipt aggregation payload must be a mapping")
        _reject_witness_material(payload, surface="receipt_aggregation_statement")
        _reject_direct_claim_on_non_direct(
            payload, statement_kind=StatementKind.RECEIPT_AGGREGATION
        )
        if payload.get("direct_computation_claim") is True:
            raise StatementError(
                "ReceiptAggregationStatement cannot serialize a direct-execution claim"
            )
        if "direct_computation_claim" in payload:
            raise StatementError(
                "ReceiptAggregationStatement cannot serialize a direct-execution claim"
            )
        kind = payload.get("statement_kind")
        if kind not in (None, StatementKind.RECEIPT_AGGREGATION.value):
            raise StatementError("payload is not ReceiptAggregationStatement")
        if payload.get("evidence_class") not in (
            None,
            EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value,
        ):
            if (
                payload.get("evidence_class")
                != EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value
            ):
                raise StatementError(
                    "ReceiptAggregationStatement requires "
                    "ReceiptAggregationZkProof evidence"
                )
        if payload.get("domain_separator") not in (None, DOMAIN_RECEIPT_AGGREGATION):
            if payload.get("domain_separator") != DOMAIN_RECEIPT_AGGREGATION:
                raise StatementError(
                    "domain separator mismatch for receipt aggregation"
                )
        public_raw = payload.get("public_inputs")
        if not isinstance(public_raw, Mapping):
            raise StatementError("public_inputs must be a mapping")
        private_raw = payload.get("private_input_commitment")
        if not isinstance(private_raw, Mapping):
            raise StatementError("private_input_commitment must be a mapping")
        raw_digests = payload.get("receipt_digests")
        if not isinstance(raw_digests, Sequence) or isinstance(raw_digests, (str, bytes)):
            raise StatementError("receipt_digests must be a sequence")
        aggregation_root = payload.get("aggregation_root") or ""
        if aggregation_root is None:
            aggregation_root = ""
        return cls(
            circuit_id=str(payload.get("circuit_id") or payload.get("computation_id") or ""),
            proof_system_id=str(payload.get("proof_system_id") or ""),
            receipt_digests=tuple(str(item) for item in raw_digests),
            public_inputs=PublicInputDeclaration.from_canonical(public_raw),
            private_input_commitment=PrivateInputCommitment.from_canonical(private_raw),
            trusted_assumptions=tuple(
                str(item) for item in (payload.get("trusted_assumptions") or ())
            ),
            aggregation_root=str(aggregation_root),
            schema=str(payload.get("schema") or RECEIPT_AGGREGATION_SCHEMA),
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )

    @classmethod
    def refuse_direct_execution_claim(
        cls, payload: Mapping[str, Any]
    ) -> ReceiptAggregationStatement:
        """Load only when the payload is not a direct-execution claim."""

        if (
            payload.get("direct_computation_claim") is True
            or payload.get("statement_kind") == StatementKind.DIRECT_EXECUTION.value
            or payload.get("evidence_class")
            == EvidenceClass.DIRECT_EXECUTION_PROOF.value
        ):
            raise StatementError(
                "ReceiptAggregationStatement cannot serialize a direct-execution claim"
            )
        return cls.from_canonical(payload)


# ---------------------------------------------------------------------------
# Forest / state transition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForestTransitionStatement:
    """Accepted parent, explicit transition, and reused/replacement leaves.

    Binds the incremental seal transition: parent seal, transition identity,
    old/new verification roots, and sorted reused/replacement leaf CIDs.
    """

    parent_seal_cid: str
    transition_id: str
    old_verification_root: str
    new_verification_root: str
    reused_leaf_cids: tuple[str, ...]
    replacement_leaf_cids: tuple[str, ...]
    public_inputs: PublicInputDeclaration
    private_input_commitment: PrivateInputCommitment
    manifest_cid: str
    logical_epoch: int
    trusted_assumptions: tuple[str, ...] = (
        "parent_seal_acceptance",
        "policy_authorization",
    )
    proof_system_id: str = "forest_transition"
    circuit_id: str = "forest_transition@v1"
    schema: str = FOREST_TRANSITION_SCHEMA
    schema_version: str = SCHEMA_VERSION
    canonicalization_version: str = CANONICALIZATION_VERSION

    ESTABLISHES: Final[str] = (
        "an accepted parent, explicit state transition, valid reused/"
        "replacement leaves, complete new manifest, and new repository "
        "verification root"
    )
    DOES_NOT_ESTABLISH: Final[str] = (
        "arbitrary repository correctness or direct test execution unless "
        "child leaves prove it"
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parent_seal_cid",
            _require_digest_or_cid(self.parent_seal_cid, "parent_seal_cid"),
        )
        object.__setattr__(
            self,
            "transition_id",
            _require_identifier(self.transition_id, "transition_id"),
        )
        object.__setattr__(
            self,
            "old_verification_root",
            _require_digest_or_cid(
                self.old_verification_root, "old_verification_root"
            ),
        )
        object.__setattr__(
            self,
            "new_verification_root",
            _require_digest_or_cid(
                self.new_verification_root, "new_verification_root"
            ),
        )
        object.__setattr__(
            self,
            "reused_leaf_cids",
            _require_sorted_unique(self.reused_leaf_cids, "reused_leaf_cids"),
        )
        object.__setattr__(
            self,
            "replacement_leaf_cids",
            _require_sorted_unique(
                self.replacement_leaf_cids, "replacement_leaf_cids"
            ),
        )
        overlap = set(self.reused_leaf_cids) & set(self.replacement_leaf_cids)
        if overlap:
            raise StatementError(
                f"reused and replacement leaf CIDs must be disjoint: {sorted(overlap)}"
            )
        if not isinstance(self.public_inputs, PublicInputDeclaration):
            raise StatementError("public_inputs must be PublicInputDeclaration")
        if not isinstance(self.private_input_commitment, PrivateInputCommitment):
            raise StatementError(
                "private_input_commitment must be PrivateInputCommitment"
            )
        if self.private_input_commitment.reveals_witness():
            raise StatementError("private commitments reveal no witness")
        object.__setattr__(
            self,
            "manifest_cid",
            _require_digest_or_cid(self.manifest_cid, "manifest_cid"),
        )
        object.__setattr__(
            self, "logical_epoch", _require_nonneg_int(self.logical_epoch, "logical_epoch")
        )
        assumptions = tuple(
            _require_identifier(item, "trusted_assumption")
            for item in self.trusted_assumptions
        )
        if list(assumptions) != sorted(assumptions):
            raise StatementError("trusted_assumptions must be canonically sorted")
        if len(set(assumptions)) != len(assumptions):
            raise StatementError("trusted_assumptions must be unique")
        object.__setattr__(self, "trusted_assumptions", assumptions)
        object.__setattr__(
            self,
            "proof_system_id",
            _require_identifier(self.proof_system_id, "proof_system_id"),
        )
        object.__setattr__(
            self, "circuit_id", _require_identifier(self.circuit_id, "circuit_id")
        )
        object.__setattr__(self, "schema", _require_identifier(self.schema, "schema"))
        if self.schema != FOREST_TRANSITION_SCHEMA:
            raise StatementError(
                f"forest transition schema must be {FOREST_TRANSITION_SCHEMA}"
            )

    @property
    def statement_kind(self) -> StatementKind:
        return StatementKind.FOREST_TRANSITION

    @property
    def evidence_class(self) -> EvidenceClass:
        return EvidenceClass.INCREMENTAL_COMMIT_SEAL

    @property
    def domain_separator(self) -> str:
        return DOMAIN_FOREST_TRANSITION

    @property
    def computation_id(self) -> str:
        return self.transition_id

    @property
    def direct_computation_claim(self) -> bool:
        return False

    def to_canonical(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "canonicalization_version": self.canonicalization_version,
            "statement_kind": self.statement_kind.value,
            "evidence_class": self.evidence_class.value,
            "domain_separator": self.domain_separator,
            "computation_id": self.computation_id,
            "parent_seal_cid": self.parent_seal_cid,
            "transition_id": self.transition_id,
            "old_verification_root": self.old_verification_root,
            "new_verification_root": self.new_verification_root,
            "reused_leaf_cids": list(self.reused_leaf_cids),
            "replacement_leaf_cids": list(self.replacement_leaf_cids),
            "manifest_cid": self.manifest_cid,
            "logical_epoch": self.logical_epoch,
            "circuit_id": self.circuit_id,
            "proof_system_id": self.proof_system_id,
            "public_inputs": self.public_inputs.to_canonical(),
            "public_input_cid": self.public_inputs.public_input_cid(),
            "private_input_commitment": self.private_input_commitment.to_canonical(),
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
            "trusted_assumptions": list(self.trusted_assumptions),
            "direct_computation_claim": False,
            "statements_subset": STATEMENTS_SUBSET,
        }
        _reject_witness_material(payload, surface="forest_transition_statement")
        return payload

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    def statement_cid(self) -> str:
        return _content_address(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ForestTransitionStatement:
        if not isinstance(payload, Mapping):
            raise StatementError("forest transition payload must be a mapping")
        _reject_witness_material(payload, surface="forest_transition_statement")
        if payload.get("direct_computation_claim") is True:
            raise StatementError(
                "ForestTransitionStatement cannot carry a direct-execution claim"
            )
        kind = payload.get("statement_kind")
        if kind not in (None, StatementKind.FOREST_TRANSITION.value):
            raise StatementError("payload is not ForestTransitionStatement")
        if payload.get("evidence_class") not in (
            None,
            EvidenceClass.INCREMENTAL_COMMIT_SEAL.value,
        ):
            if (
                payload.get("evidence_class")
                != EvidenceClass.INCREMENTAL_COMMIT_SEAL.value
            ):
                raise StatementError(
                    "ForestTransitionStatement requires IncrementalCommitSeal evidence"
                )
        public_raw = payload.get("public_inputs")
        if not isinstance(public_raw, Mapping):
            raise StatementError("public_inputs must be a mapping")
        private_raw = payload.get("private_input_commitment")
        if not isinstance(private_raw, Mapping):
            raise StatementError("private_input_commitment must be a mapping")

        def _tuple(field: str) -> tuple[str, ...]:
            raw = payload.get(field) or ()
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise StatementError(f"{field} must be a sequence")
            return tuple(str(item) for item in raw)

        return cls(
            parent_seal_cid=str(payload.get("parent_seal_cid") or ""),
            transition_id=str(
                payload.get("transition_id") or payload.get("computation_id") or ""
            ),
            old_verification_root=str(payload.get("old_verification_root") or ""),
            new_verification_root=str(payload.get("new_verification_root") or ""),
            reused_leaf_cids=_tuple("reused_leaf_cids"),
            replacement_leaf_cids=_tuple("replacement_leaf_cids"),
            public_inputs=PublicInputDeclaration.from_canonical(public_raw),
            private_input_commitment=PrivateInputCommitment.from_canonical(private_raw),
            manifest_cid=str(payload.get("manifest_cid") or ""),
            logical_epoch=int(payload.get("logical_epoch", 0)),
            trusted_assumptions=tuple(
                str(item) for item in (payload.get("trusted_assumptions") or ())
            ),
            proof_system_id=str(payload.get("proof_system_id") or "forest_transition"),
            circuit_id=str(payload.get("circuit_id") or "forest_transition@v1"),
            schema=str(payload.get("schema") or FOREST_TRANSITION_SCHEMA),
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Dispatch / builders
# ---------------------------------------------------------------------------


StatementRecord = (
    CanonicalProofStatement
    | DirectExecutionStatement
    | ReceiptAggregationStatement
    | ForestTransitionStatement
)


def statement_from_canonical(payload: Mapping[str, Any]) -> StatementRecord:
    """Load a domain-separated statement; fail closed on unknown kinds/claims."""

    if not isinstance(payload, Mapping):
        raise StatementError("statement payload must be a mapping")
    _reject_witness_material(payload, surface="statement")
    kind_raw = payload.get("statement_kind")
    if kind_raw is None:
        # Infer from evidence class when kind is omitted.
        evidence = str(payload.get("evidence_class") or "")
        if evidence == EvidenceClass.DIRECT_EXECUTION_PROOF.value:
            kind_raw = StatementKind.DIRECT_EXECUTION.value
        elif evidence == EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value:
            kind_raw = StatementKind.RECEIPT_AGGREGATION.value
        elif evidence == EvidenceClass.INCREMENTAL_COMMIT_SEAL.value:
            kind_raw = StatementKind.FOREST_TRANSITION.value
        else:
            kind_raw = StatementKind.CANONICAL.value
    kind = parse_statement_kind(kind_raw)
    if kind is StatementKind.DIRECT_EXECUTION:
        return DirectExecutionStatement.from_canonical(payload)
    if kind is StatementKind.RECEIPT_AGGREGATION:
        return ReceiptAggregationStatement.from_canonical(payload)
    if kind is StatementKind.FOREST_TRANSITION:
        return ForestTransitionStatement.from_canonical(payload)
    if kind is StatementKind.CANONICAL:
        # Avoid recursive dispatch: build envelope directly.
        if payload.get("direct_computation_claim") is True:
            raise StatementError(
                "canonical envelope cannot carry a direct-execution claim"
            )
        evidence_raw = payload.get("evidence_class")
        try:
            evidence = (
                evidence_raw
                if isinstance(evidence_raw, EvidenceClass)
                else EvidenceClass(str(evidence_raw or ""))
            )
        except ValueError as exc:
            raise StatementError(f"unknown evidence_class {evidence_raw!r}") from exc
        public_raw = payload.get("public_inputs")
        if not isinstance(public_raw, Mapping):
            raise StatementError("public_inputs must be a mapping")
        private_raw = payload.get("private_input_commitment")
        if not isinstance(private_raw, Mapping):
            raise StatementError("private_input_commitment must be a mapping")
        return CanonicalProofStatement(
            statement_kind=StatementKind.CANONICAL,
            evidence_class=evidence,
            domain_separator=str(payload.get("domain_separator") or DOMAIN_CANONICAL),
            computation_id=str(payload.get("computation_id") or ""),
            public_inputs=PublicInputDeclaration.from_canonical(public_raw),
            private_input_commitment=PrivateInputCommitment.from_canonical(private_raw),
            establishes=str(payload.get("establishes") or ""),
            does_not_establish=str(payload.get("does_not_establish") or ""),
            trusted_assumptions=tuple(
                str(item) for item in (payload.get("trusted_assumptions") or ())
            ),
            proof_system_id=str(payload.get("proof_system_id") or ""),
            circuit_id=str(payload.get("circuit_id") or ""),
            schema=str(payload.get("schema") or CANONICAL_STATEMENT_SCHEMA),
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )
    raise StatementError(f"unsupported statement kind {kind!r}")


def build_direct_execution_statement(
    *,
    program_id: str,
    circuit_id: str,
    proof_system_id: str,
    input_commitment: str,
    output_commitment: str,
    private_commitment: str,
    extra_public: Mapping[str, str] | None = None,
    trusted_assumptions: Sequence[str] | None = None,
    property_id: str = "declared_output_property",
    witness_bytes: bytes | None = None,
) -> DirectExecutionStatement:
    """Construct a direct-execution statement binding the declared computation."""

    public_map: dict[str, str] = {
        "circuit_id": circuit_id,
        "input_commitment": input_commitment,
        "output_commitment": output_commitment,
        "program_id": program_id,
        "proof_system_id": proof_system_id,
        "property_id": property_id,
    }
    if extra_public:
        for key, value in extra_public.items():
            if key in public_map and public_map[key] != value:
                raise StatementError(
                    f"extra public input {key!r} conflicts with declared computation"
                )
            public_map[key] = value
    if witness_bytes is not None:
        private = PrivateInputCommitment.commit_witness_bytes(witness_bytes)
        if private_commitment and private_commitment != private.commitment:
            raise StatementError(
                "private_commitment does not match digest of witness_bytes"
            )
        commitment = private
    else:
        commitment = PrivateInputCommitment(commitment=private_commitment)
    return DirectExecutionStatement(
        program_id=program_id,
        circuit_id=circuit_id,
        proof_system_id=proof_system_id,
        input_commitment=input_commitment,
        output_commitment=output_commitment,
        public_inputs=PublicInputDeclaration.from_mapping(public_map),
        private_input_commitment=commitment,
        trusted_assumptions=tuple(
            sorted(
                trusted_assumptions
                or (
                    "proof_system_soundness",
                    "verification_key_authenticity",
                )
            )
        ),
        property_id=property_id,
    )


def build_receipt_aggregation_statement(
    *,
    circuit_id: str,
    proof_system_id: str,
    receipt_digests: Sequence[str],
    private_commitment: str,
    aggregation_root: str = "",
    extra_public: Mapping[str, str] | None = None,
    trusted_assumptions: Sequence[str] | None = None,
) -> ReceiptAggregationStatement:
    digests = tuple(sorted(str(item) for item in receipt_digests))
    public_map: dict[str, str] = {
        "circuit_id": circuit_id,
        "proof_system_id": proof_system_id,
        "receipt_count": str(len(digests)),
    }
    if aggregation_root:
        public_map["aggregation_root"] = aggregation_root
    if extra_public:
        public_map.update({str(k): str(v) for k, v in extra_public.items()})
    return ReceiptAggregationStatement(
        circuit_id=circuit_id,
        proof_system_id=proof_system_id,
        receipt_digests=digests,
        public_inputs=PublicInputDeclaration.from_mapping(public_map),
        private_input_commitment=PrivateInputCommitment(commitment=private_commitment),
        trusted_assumptions=tuple(
            sorted(
                trusted_assumptions
                or (
                    "receipt_signature_verification",
                    "signer_allowlist_trust",
                )
            )
        ),
        aggregation_root=aggregation_root,
    )


def build_forest_transition_statement(
    *,
    parent_seal_cid: str,
    transition_id: str,
    old_verification_root: str,
    new_verification_root: str,
    reused_leaf_cids: Sequence[str],
    replacement_leaf_cids: Sequence[str],
    manifest_cid: str,
    logical_epoch: int,
    private_commitment: str,
    extra_public: Mapping[str, str] | None = None,
) -> ForestTransitionStatement:
    public_map: dict[str, str] = {
        "manifest_cid": manifest_cid,
        "new_verification_root": new_verification_root,
        "old_verification_root": old_verification_root,
        "parent_seal_cid": parent_seal_cid,
        "transition_id": transition_id,
    }
    if extra_public:
        public_map.update({str(k): str(v) for k, v in extra_public.items()})
    return ForestTransitionStatement(
        parent_seal_cid=parent_seal_cid,
        transition_id=transition_id,
        old_verification_root=old_verification_root,
        new_verification_root=new_verification_root,
        reused_leaf_cids=tuple(sorted(str(item) for item in reused_leaf_cids)),
        replacement_leaf_cids=tuple(
            sorted(str(item) for item in replacement_leaf_cids)
        ),
        public_inputs=PublicInputDeclaration.from_mapping(public_map),
        private_input_commitment=PrivateInputCommitment(commitment=private_commitment),
        manifest_cid=manifest_cid,
        logical_epoch=logical_epoch,
    )


def sample_direct_execution_statement() -> DirectExecutionStatement:
    witness = b"private-witness-opening-not-retained"
    return build_direct_execution_statement(
        program_id="program/direct@v1",
        circuit_id="direct_zk@v1",
        proof_system_id="groth16",
        input_commitment="sha256:" + ("22" * 32),
        output_commitment="sha256:" + ("33" * 32),
        private_commitment="",
        witness_bytes=witness,
    )


def sample_receipt_aggregation_statement() -> ReceiptAggregationStatement:
    return build_receipt_aggregation_statement(
        circuit_id="receipt_agg@v1",
        proof_system_id="groth16",
        receipt_digests=(
            "sha256:" + ("aa" * 32),
            "sha256:" + ("bb" * 32),
        ),
        private_commitment="sha256:" + ("cc" * 32),
        aggregation_root="sha256:" + ("dd" * 32),
    )


def sample_forest_transition_statement() -> ForestTransitionStatement:
    return build_forest_transition_statement(
        parent_seal_cid="sha256:" + ("a1" * 32),
        transition_id="transition/epoch-2",
        old_verification_root="sha256:" + ("a2" * 32),
        new_verification_root="sha256:" + ("a3" * 32),
        reused_leaf_cids=("sha256:" + ("b1" * 32),),
        replacement_leaf_cids=("sha256:" + ("b2" * 32),),
        manifest_cid="sha256:" + ("c1" * 32),
        logical_epoch=2,
        private_commitment="sha256:" + ("d1" * 32),
    )
