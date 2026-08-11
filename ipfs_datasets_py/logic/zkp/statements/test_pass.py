"""Test-pass ZKP statement (TestPassStatementV1).

Defines the public/private inputs and predicate for proof-backed pytest reuse.
The circuit relation proves possession of an admitted complete-pass receipt
whose constrained fields match exact public bindings.  It does **not** prove
general program correctness, dependency-trace completeness, or future behavior.

Public inputs (visible to the verifier; reconstructed by the verifier)
----------------------------------------------------------------------
* ``receipt_cid`` — content identity of the trusted pass receipt
* ``execution_key_cid`` — exact current reusable execution context
* ``policy_cid`` — reuse / outcome policy identity
* ``statement_cid`` — pinned statement schema identity (this interface)
* ``circuit_cid`` — reviewed circuit identity
* ``verifying_key_cid`` — pinned verification-key identity
* ``issuer_id`` — runner / issuer trust binding
* ``epoch`` — revocation / decision epoch
* phase outcome bits (``setup_outcome``, ``call_outcome``, ``teardown_outcome``)
* disqualifying outcome bits (must be empty / clear for admission)
* optional locator, completeness, and circuit-ref pins

Private witness (minimal)
-------------------------
Canonical trusted receipt bytes (or a reviewed structured opening of those
bytes) whose content digest equals ``receipt_cid``.  The witness never appears
in public inputs, certificates, indexes, or diagnostics.

Predicate (claim boundary)
--------------------------
1. private receipt preimage hashes to the public receipt CID;
2. constrained receipt fields equal public execution-key, policy, issuer,
   epoch, and optional locator/completeness bindings;
3. setup, call, and teardown outcomes are all ``pass``;
4. every disqualifying bit is clear;
5. public inputs contain no private material, nonfinite values, or malformed
   types.

No pytest or accelerator dependency is introduced here: this module only
defines the statement protocol used by later certificate/issuer adapters.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Iterable

from ..statement import format_circuit_ref


# ---------------------------------------------------------------------------
# Interface / circuit pins
# ---------------------------------------------------------------------------

TEST_PASS_STATEMENT_INTERFACE: Final = "TestPassStatementV1"
TEST_PASS_STATEMENT_VERSION: Final = 1
TEST_PASS_CIRCUIT_ID: Final = "test_pass"
TEST_PASS_CIRCUIT_VERSION: Final = 1
TEST_PASS_CIRCUIT_REF: Final = format_circuit_ref(
    TEST_PASS_CIRCUIT_ID, TEST_PASS_CIRCUIT_VERSION
)
TEST_PASS_RULESET_ID: Final = "test_pass_v1"
TEST_PASS_PUBLIC_INPUT_SCHEMA: Final = "test-pass-public-inputs@1"
TEST_PASS_CONTENT_PROFILE: Final = "sha256-canonical-json-v1"
TEST_PASS_PROOF_DOMAIN: Final = b"TestPassStatementV1|test_pass@v1"

_DIGEST_PREFIX: Final = "sha256:"
_PHASE_PASS: Final = "pass"

# Closed phase outcome vocabulary (matches TestPassReceipt@1 doctrine).
PHASE_OUTCOMES: Final = frozenset(
    {
        "pass",
        "fail",
        "skip",
        "xfail",
        "xpass",
        "error",
        "not_run",
        "interrupted",
        "rerun",
    }
)

# Bits that disqualify a receipt from admission / skip authority.
DISQUALIFYING_BITS: Final = frozenset(
    {
        "fail",
        "skip",
        "xfail",
        "xpass",
        "error",
        "not_run",
        "interrupted",
        "rerun",
        "timed_out",
        "leaked_resource",
        "incomplete_trace",
        "coverage",
        "mutation",
        "debugger",
        "benchmark",
        "leak_detection",
    }
)

_PRIVATE_FIELD_MARKERS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "hidden_witness",
        "password",
        "private_key",
        "private_premise",
        "private_witness",
        "refresh_token",
        "secret",
        "session_token",
        "witness",
    }
)

# Public-input identity fields required by acceptance / threat model.
REQUIRED_PUBLIC_IDENTITY_FIELDS: Final = (
    "receipt_cid",
    "execution_key_cid",
    "policy_cid",
    "statement_cid",
    "circuit_cid",
    "verifying_key_cid",
    "issuer_id",
    "epoch",
)

_CID_OR_DIGEST_RE: Final = re.compile(
    r"^(?:sha256:[0-9a-f]{64}|bafy[a-z2-7]{10,}|cid:[A-Za-z0-9:._/@+-]{1,512}"
    r"|[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,2047})$"
)
_EPOCH_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,255}$")
_ISSUER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}$")

MAX_TEXT_CHARS: Final = 4_096
MAX_SEQUENCE_ITEMS: Final = 64
MAX_PUBLIC_INPUT_KEYS: Final = 64
MAX_RECEIPT_BYTES: Final = 1_048_576


class TestPassStatementError(ValueError):
    """Raised when a test-pass statement cannot be constructed or satisfied."""

    # Not a pytest test class.
    __test__ = False


# ---------------------------------------------------------------------------
# Canonical encoding / digests
# ---------------------------------------------------------------------------


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


def compute_receipt_cid(payload: Any) -> str:
    """Return ``sha256:<hex>`` of the canonical JSON form of *payload*.

    This is the content-identity profile used when the statement binds a
    structured receipt opening without an external multiformats dependency.
    Bytes witnesses use :func:`content_digest_of_bytes` instead.
    """

    return _sha256_digest(_canonical_bytes(_json_ready(payload)))


def content_digest_of_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` of raw *data*."""

    if not isinstance(data, (bytes, bytearray)):
        raise TestPassStatementError("receipt bytes must be bytes")
    return _sha256_digest(bytes(data))


# ---------------------------------------------------------------------------
# Validation primitives
# ---------------------------------------------------------------------------


def _require_text(
    value: Any,
    field_name: str,
    *,
    max_chars: int = MAX_TEXT_CHARS,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TestPassStatementError(f"{field_name} must be a string")
    if value != value.strip():
        raise TestPassStatementError(
            f"{field_name} must be a trimmed string (no leading/trailing whitespace)"
        )
    if not allow_empty and not value:
        raise TestPassStatementError(f"{field_name} must be a non-empty string")
    if len(value) > max_chars:
        raise TestPassStatementError(
            f"{field_name} exceeds bounded length of {max_chars} characters"
        )
    return value


def _require_identity(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not _CID_OR_DIGEST_RE.match(text):
        raise TestPassStatementError(
            f"{field_name} must be a bounded content identity string"
        )
    if text.startswith(_DIGEST_PREFIX):
        hex_part = text[len(_DIGEST_PREFIX) :]
        if hex_part != hex_part.lower():
            raise TestPassStatementError(
                f"{field_name} digest hex must be lowercase"
            )
        try:
            int(hex_part, 16)
        except ValueError as exc:
            raise TestPassStatementError(
                f"{field_name} must be a sha256:<hex> digest"
            ) from exc
    return text


def _require_phase_outcome(value: Any, field_name: str) -> str:
    outcome = _require_text(value, field_name, max_chars=32)
    if outcome not in PHASE_OUTCOMES:
        raise TestPassStatementError(
            f"{field_name} must be one of {sorted(PHASE_OUTCOMES)}"
        )
    return outcome


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TestPassStatementError(f"{field_name} must be a boolean")
    return value


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TestPassStatementError(f"{label} must be a mapping")
    return value


def _is_private_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in _PRIVATE_FIELD_MARKERS:
        return True
    return any(
        marker in lowered
        for marker in (
            "private",
            "secret",
            "password",
            "api_key",
            "witness",
            "credential",
            "token",
        )
    )


def _reject_nonfinite(value: Any, field_name: str) -> None:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise TestPassStatementError(
                f"{field_name} must not contain nonfinite values"
            )
        raise TestPassStatementError(
            f"{field_name} must not contain floating-point values"
        )
    if isinstance(value, Mapping):
        if len(value) > MAX_PUBLIC_INPUT_KEYS:
            raise TestPassStatementError(
                f"{field_name} exceeds bounded key count of {MAX_PUBLIC_INPUT_KEYS}"
            )
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise TestPassStatementError(
                    f"{field_name} keys must be non-empty strings"
                )
            if _is_private_key(key):
                raise TestPassStatementError(
                    f"{field_name} rejects private material key {key!r}"
                )
            _reject_nonfinite(item, field_name=f"{field_name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_SEQUENCE_ITEMS:
            raise TestPassStatementError(
                f"{field_name} exceeds bounded item count of {MAX_SEQUENCE_ITEMS}"
            )
        for index, item in enumerate(value):
            _reject_nonfinite(item, field_name=f"{field_name}[{index}]")
        return
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, bool):
            return
        if isinstance(value, int) and not isinstance(value, bool):
            return
        if isinstance(value, str) and len(value) > MAX_TEXT_CHARS:
            raise TestPassStatementError(
                f"{field_name} exceeds bounded length of {MAX_TEXT_CHARS}"
            )
        return
    raise TestPassStatementError(
        f"{field_name} has unsupported value type {type(value).__name__}"
    )


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        raise TestPassStatementError(
            "floating-point values are not JSON-safe for public or witness openings"
        )
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
    raise TestPassStatementError(
        f"value of type {type(value).__name__} is not JSON-serializable"
    )


def _normalize_disqualifying_bits(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TestPassStatementError(
            "disqualifying_bits must be a sequence of strings, not a bare string"
        )
    if not isinstance(value, Sequence):
        raise TestPassStatementError("disqualifying_bits must be a sequence")
    if len(value) > MAX_SEQUENCE_ITEMS:
        raise TestPassStatementError(
            f"disqualifying_bits exceeds bounded item count of {MAX_SEQUENCE_ITEMS}"
        )
    bits: list[str] = []
    seen: set[str] = set()
    for item in value:
        bit = _require_text(item, "disqualifying_bits item", max_chars=64)
        if bit not in DISQUALIFYING_BITS and bit not in PHASE_OUTCOMES - {_PHASE_PASS}:
            # Allow only known disqualifying vocabulary (fail-closed on unknown).
            raise TestPassStatementError(
                f"unknown disqualifying bit: {bit!r}"
            )
        if bit == _PHASE_PASS:
            raise TestPassStatementError(
                "disqualifying_bits must not include the pass outcome"
            )
        if bit not in seen:
            seen.add(bit)
            bits.append(bit)
    return tuple(sorted(bits))


# ---------------------------------------------------------------------------
# Public inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TestPassPublicInputs:
    """Public inputs bound into TestPassStatementV1 certificates.

    These fields are integrity-sensitive.  Omitting or ambiguously encoding one
    can allow substitution across receipt, execution, policy, circuit, key,
    issuer, or epoch identities.
    """

    # Not a pytest test class.
    __test__ = False

    receipt_cid: str
    execution_key_cid: str
    policy_cid: str
    statement_cid: str
    circuit_cid: str
    verifying_key_cid: str
    issuer_id: str
    epoch: str
    setup_outcome: str = _PHASE_PASS
    call_outcome: str = _PHASE_PASS
    teardown_outcome: str = _PHASE_PASS
    disqualifying_bits: tuple[str, ...] = ()
    locator_cid: str = ""
    completeness_policy_cid: str = ""
    completeness_admitted: bool = True
    circuit_ref: str = TEST_PASS_CIRCUIT_REF
    public_input_schema: str = TEST_PASS_PUBLIC_INPUT_SCHEMA
    content_profile: str = TEST_PASS_CONTENT_PROFILE
    statement_version: int = TEST_PASS_STATEMENT_VERSION
    extra: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_cid", _require_identity(self.receipt_cid, "receipt_cid")
        )
        object.__setattr__(
            self,
            "execution_key_cid",
            _require_identity(self.execution_key_cid, "execution_key_cid"),
        )
        object.__setattr__(
            self, "policy_cid", _require_identity(self.policy_cid, "policy_cid")
        )
        object.__setattr__(
            self,
            "statement_cid",
            _require_identity(self.statement_cid, "statement_cid"),
        )
        object.__setattr__(
            self, "circuit_cid", _require_identity(self.circuit_cid, "circuit_cid")
        )
        object.__setattr__(
            self,
            "verifying_key_cid",
            _require_identity(self.verifying_key_cid, "verifying_key_cid"),
        )
        issuer = _require_text(self.issuer_id, "issuer_id", max_chars=256)
        if not _ISSUER_RE.match(issuer):
            raise TestPassStatementError(
                "issuer_id must be a bounded issuer / trust identity"
            )
        object.__setattr__(self, "issuer_id", issuer)
        epoch = _require_text(self.epoch, "epoch", max_chars=256)
        if not _EPOCH_RE.match(epoch):
            raise TestPassStatementError(
                "epoch must be a bounded epoch / revocation identity"
            )
        object.__setattr__(self, "epoch", epoch)

        object.__setattr__(
            self,
            "setup_outcome",
            _require_phase_outcome(self.setup_outcome, "setup_outcome"),
        )
        object.__setattr__(
            self,
            "call_outcome",
            _require_phase_outcome(self.call_outcome, "call_outcome"),
        )
        object.__setattr__(
            self,
            "teardown_outcome",
            _require_phase_outcome(self.teardown_outcome, "teardown_outcome"),
        )
        object.__setattr__(
            self,
            "disqualifying_bits",
            _normalize_disqualifying_bits(self.disqualifying_bits),
        )

        if self.locator_cid in (None, ""):
            object.__setattr__(self, "locator_cid", "")
        else:
            object.__setattr__(
                self,
                "locator_cid",
                _require_identity(self.locator_cid, "locator_cid"),
            )
        if self.completeness_policy_cid in (None, ""):
            object.__setattr__(self, "completeness_policy_cid", "")
        else:
            object.__setattr__(
                self,
                "completeness_policy_cid",
                _require_identity(
                    self.completeness_policy_cid, "completeness_policy_cid"
                ),
            )
        object.__setattr__(
            self,
            "completeness_admitted",
            _require_bool(self.completeness_admitted, "completeness_admitted"),
        )

        circuit_ref = _require_text(self.circuit_ref, "circuit_ref", max_chars=256)
        if circuit_ref != TEST_PASS_CIRCUIT_REF:
            raise TestPassStatementError(
                f"unsupported circuit_ref: {circuit_ref!r}; "
                f"expected {TEST_PASS_CIRCUIT_REF!r}"
            )
        object.__setattr__(self, "circuit_ref", circuit_ref)
        object.__setattr__(
            self,
            "public_input_schema",
            _require_text(
                self.public_input_schema, "public_input_schema", max_chars=128
            ),
        )
        if self.public_input_schema != TEST_PASS_PUBLIC_INPUT_SCHEMA:
            raise TestPassStatementError(
                f"unsupported public_input_schema: {self.public_input_schema!r}"
            )
        object.__setattr__(
            self,
            "content_profile",
            _require_text(self.content_profile, "content_profile", max_chars=128),
        )
        if self.content_profile != TEST_PASS_CONTENT_PROFILE:
            raise TestPassStatementError(
                f"unsupported content_profile: {self.content_profile!r}"
            )
        if not isinstance(self.statement_version, int) or isinstance(
            self.statement_version, bool
        ):
            raise TestPassStatementError("statement_version must be an int")
        if self.statement_version != TEST_PASS_STATEMENT_VERSION:
            raise TestPassStatementError(
                f"unsupported statement_version: {self.statement_version!r}"
            )

        extra_map = _as_mapping(self.extra, "extra")
        _reject_nonfinite(dict(extra_map), "extra")
        # Forbid reserved identity keys from being smuggled via extra.
        reserved = set(REQUIRED_PUBLIC_IDENTITY_FIELDS) | {
            "setup_outcome",
            "call_outcome",
            "teardown_outcome",
            "disqualifying_bits",
            "locator_cid",
            "completeness_policy_cid",
            "completeness_admitted",
            "circuit_ref",
            "public_input_schema",
            "content_profile",
            "statement_version",
            "interface",
            "witness",
            "private_witness",
        }
        for key in extra_map:
            if key in reserved or _is_private_key(str(key)):
                raise TestPassStatementError(
                    f"extra public field {key!r} is reserved or private"
                )
        ready_extra = _json_ready(dict(extra_map))
        if not isinstance(ready_extra, dict):
            raise TestPassStatementError("extra must be a mapping")
        object.__setattr__(self, "extra", MappingProxyType(ready_extra))

        # Full public payload must reject private / nonfinite material.
        _reject_nonfinite(self.to_dict(), "public_inputs")

    # -- predicate helpers -------------------------------------------------

    @property
    def interface(self) -> str:
        return TEST_PASS_STATEMENT_INTERFACE

    @property
    def all_phases_pass(self) -> bool:
        return (
            self.setup_outcome == _PHASE_PASS
            and self.call_outcome == _PHASE_PASS
            and self.teardown_outcome == _PHASE_PASS
        )

    @property
    def disqualifying_bits_clear(self) -> bool:
        return len(self.disqualifying_bits) == 0

    def is_admitted_complete_pass(self) -> bool:
        """Return True when public outcome bits admit a complete pass."""

        return (
            self.all_phases_pass
            and self.disqualifying_bits_clear
            and self.completeness_admitted is True
        )

    def identity_payload(self) -> dict[str, Any]:
        """Canonical public payload used for the statement digest."""

        payload: dict[str, Any] = {
            "call_outcome": self.call_outcome,
            "circuit_cid": self.circuit_cid,
            "circuit_ref": self.circuit_ref,
            "completeness_admitted": self.completeness_admitted,
            "completeness_policy_cid": self.completeness_policy_cid,
            "content_profile": self.content_profile,
            "disqualifying_bits": list(self.disqualifying_bits),
            "epoch": self.epoch,
            "execution_key_cid": self.execution_key_cid,
            "extra": dict(self.extra),
            "interface": TEST_PASS_STATEMENT_INTERFACE,
            "issuer_id": self.issuer_id,
            "locator_cid": self.locator_cid,
            "policy_cid": self.policy_cid,
            "public_input_schema": self.public_input_schema,
            "receipt_cid": self.receipt_cid,
            "setup_outcome": self.setup_outcome,
            "statement_cid": self.statement_cid,
            "statement_version": self.statement_version,
            "teardown_outcome": self.teardown_outcome,
            "verifying_key_cid": self.verifying_key_cid,
        }
        return payload

    def statement_digest(self) -> str:
        """Return ``sha256:<hex>`` of the canonical public statement."""

        return _sha256_digest(_canonical_bytes(self.identity_payload()))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.identity_payload())

    def to_public_inputs(self) -> dict[str, Any]:
        """Return public inputs embedded in a certificate envelope."""

        payload = self.identity_payload()
        payload["statement_digest"] = self.statement_digest()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestPassPublicInputs":
        mapping = _as_mapping(data, "public_inputs")
        _reject_nonfinite(dict(mapping), "public_inputs")
        for key in mapping:
            if _is_private_key(str(key)):
                raise TestPassStatementError(
                    f"public_inputs rejects private material key {key!r}"
                )
        # Ignore derived digest when reconstructing.
        extra_raw = mapping.get("extra") or {}
        return cls(
            receipt_cid=str(mapping.get("receipt_cid", "")),
            execution_key_cid=str(mapping.get("execution_key_cid", "")),
            policy_cid=str(mapping.get("policy_cid", "")),
            statement_cid=str(mapping.get("statement_cid", "")),
            circuit_cid=str(mapping.get("circuit_cid", "")),
            verifying_key_cid=str(mapping.get("verifying_key_cid", "")),
            issuer_id=str(mapping.get("issuer_id", "")),
            epoch=str(mapping.get("epoch", "")),
            setup_outcome=str(mapping.get("setup_outcome", _PHASE_PASS)),
            call_outcome=str(mapping.get("call_outcome", _PHASE_PASS)),
            teardown_outcome=str(mapping.get("teardown_outcome", _PHASE_PASS)),
            disqualifying_bits=tuple(mapping.get("disqualifying_bits") or ()),
            locator_cid=str(mapping.get("locator_cid", "") or ""),
            completeness_policy_cid=str(
                mapping.get("completeness_policy_cid", "") or ""
            ),
            completeness_admitted=(
                mapping["completeness_admitted"]
                if "completeness_admitted" in mapping
                else True
            ),
            circuit_ref=str(mapping.get("circuit_ref", TEST_PASS_CIRCUIT_REF)),
            public_input_schema=str(
                mapping.get("public_input_schema", TEST_PASS_PUBLIC_INPUT_SCHEMA)
            ),
            content_profile=str(
                mapping.get("content_profile", TEST_PASS_CONTENT_PROFILE)
            ),
            statement_version=int(
                mapping.get("statement_version", TEST_PASS_STATEMENT_VERSION)
            ),
            extra=_as_mapping(extra_raw, "extra") if extra_raw is not None else {},
        )


# ---------------------------------------------------------------------------
# Private witness
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TestPassPrivateWitness:
    """Minimal private opening of ``receipt_cid``.

    Prefer providing ``receipt_bytes`` (canonical trusted receipt bytes).
    Optionally provide a structured ``receipt_fields`` mapping whose constrained
    fields are checked against public inputs; when both are present, the
    structured fields must be consistent with the byte opening.

    The witness is never serialized into public certificates or indexes.
    ``to_dict`` is for tests/debug only and reveals private data.
    """

    # Not a pytest test class.
    __test__ = False

    receipt_bytes: bytes
    receipt_fields: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_bytes, (bytes, bytearray)):
            raise TestPassStatementError("receipt_bytes must be bytes")
        raw = bytes(self.receipt_bytes)
        if not raw:
            raise TestPassStatementError("receipt_bytes must be non-empty")
        if len(raw) > MAX_RECEIPT_BYTES:
            raise TestPassStatementError(
                f"receipt_bytes exceeds bounded length of {MAX_RECEIPT_BYTES}"
            )
        object.__setattr__(self, "receipt_bytes", raw)

        fields_map = _as_mapping(self.receipt_fields, "receipt_fields")
        _reject_nonfinite(dict(fields_map), "receipt_fields")
        ready = _json_ready(dict(fields_map))
        if not isinstance(ready, dict):
            raise TestPassStatementError("receipt_fields must be a mapping")
        object.__setattr__(self, "receipt_fields", MappingProxyType(ready))

    def opening_digest(self) -> str:
        """Content digest of the private receipt bytes."""

        return content_digest_of_bytes(self.receipt_bytes)

    def binds_receipt_cid(self, receipt_cid: str) -> bool:
        return self.opening_digest() == receipt_cid

    def constrained_fields(self) -> dict[str, Any]:
        """Return fields used for public binding checks.

        When ``receipt_fields`` is empty, attempt to parse ``receipt_bytes`` as
        canonical JSON.  Malformed bytes with no structured fields yield an
        empty mapping (hash binding still applies).
        """

        if self.receipt_fields:
            return dict(self.receipt_fields)
        try:
            decoded = json.loads(self.receipt_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {}
        if not isinstance(decoded, Mapping):
            return {}
        return _json_ready(dict(decoded))

    def to_dict(self) -> dict[str, Any]:
        """Serialize witness (reveals private data — tests/debug only)."""

        return {
            "receipt_bytes_hex": self.receipt_bytes.hex(),
            "receipt_fields": _json_ready(dict(self.receipt_fields)),
            "opening_digest": self.opening_digest(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestPassPrivateWitness":
        mapping = _as_mapping(data, "witness")
        raw = mapping.get("receipt_bytes")
        if raw is None and "receipt_bytes_hex" in mapping:
            try:
                raw = bytes.fromhex(str(mapping["receipt_bytes_hex"]))
            except ValueError as exc:
                raise TestPassStatementError(
                    "receipt_bytes_hex must be hex-encoded bytes"
                ) from exc
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        fields = mapping.get("receipt_fields") or {}
        return cls(
            receipt_bytes=bytes(raw or b""),
            receipt_fields=_as_mapping(fields, "receipt_fields"),
        )

    @classmethod
    def from_receipt_payload(cls, payload: Mapping[str, Any]) -> "TestPassPrivateWitness":
        """Build a witness from a structured receipt mapping.

        Canonical JSON bytes are the private preimage; their digest is the
        receipt CID under :data:`TEST_PASS_CONTENT_PROFILE`.
        """

        ready = _json_ready(_as_mapping(payload, "receipt payload"))
        if not isinstance(ready, dict):
            raise TestPassStatementError("receipt payload must be a mapping")
        return cls(
            receipt_bytes=_canonical_bytes(ready),
            receipt_fields=ready,
        )


# ---------------------------------------------------------------------------
# Statement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TestPassStatementV1:
    """Pinned TestPassStatementV1 public statement.

    Combines validated public inputs with the circuit/ruleset pins required by
    the datasets ZKP statement protocol.
    """

    # Not a pytest test class.
    __test__ = False

    public_inputs: TestPassPublicInputs
    circuit_version: int = TEST_PASS_CIRCUIT_VERSION
    ruleset_id: str = TEST_PASS_RULESET_ID

    def __post_init__(self) -> None:
        if not isinstance(self.public_inputs, TestPassPublicInputs):
            raise TestPassStatementError(
                "public_inputs must be a TestPassPublicInputs instance"
            )
        if not isinstance(self.circuit_version, int) or isinstance(
            self.circuit_version, bool
        ):
            raise TestPassStatementError("circuit_version must be an int")
        if self.circuit_version != TEST_PASS_CIRCUIT_VERSION:
            raise TestPassStatementError(
                f"unsupported test_pass circuit_version: {self.circuit_version!r}"
            )
        ruleset = _require_text(self.ruleset_id, "ruleset_id", max_chars=128)
        if ruleset != TEST_PASS_RULESET_ID:
            raise TestPassStatementError(
                f"unsupported ruleset_id: {ruleset!r}"
            )
        object.__setattr__(self, "ruleset_id", ruleset)

    @property
    def interface(self) -> str:
        return TEST_PASS_STATEMENT_INTERFACE

    @property
    def circuit_ref(self) -> str:
        return format_circuit_ref(TEST_PASS_CIRCUIT_ID, self.circuit_version)

    @property
    def receipt_cid(self) -> str:
        return self.public_inputs.receipt_cid

    @property
    def execution_key_cid(self) -> str:
        return self.public_inputs.execution_key_cid

    def identity_payload(self) -> dict[str, Any]:
        payload = self.public_inputs.identity_payload()
        payload["circuit_version"] = self.circuit_version
        payload["ruleset_id"] = self.ruleset_id
        return payload

    def statement_digest(self) -> str:
        return _sha256_digest(_canonical_bytes(self.identity_payload()))

    def to_public_inputs(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["statement_digest"] = self.statement_digest()
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "circuit_version": self.circuit_version,
            "interface": TEST_PASS_STATEMENT_INTERFACE,
            "public_inputs": self.public_inputs.to_dict(),
            "ruleset_id": self.ruleset_id,
            "statement_digest": self.statement_digest(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestPassStatementV1":
        mapping = _as_mapping(data, "statement")
        public_raw = mapping.get("public_inputs", mapping)
        public = TestPassPublicInputs.from_dict(
            _as_mapping(public_raw, "public_inputs")
        )
        return cls(
            public_inputs=public,
            circuit_version=int(
                mapping.get("circuit_version", TEST_PASS_CIRCUIT_VERSION)
            ),
            ruleset_id=str(mapping.get("ruleset_id", TEST_PASS_RULESET_ID)),
        )

    def requires_admitted_pass(self) -> None:
        """Raise if public outcome bits are not an admitted complete pass."""

        pi = self.public_inputs
        if not pi.all_phases_pass:
            raise TestPassStatementError(
                "all three pytest phases (setup, call, teardown) must pass; "
                f"got setup={pi.setup_outcome!r}, call={pi.call_outcome!r}, "
                f"teardown={pi.teardown_outcome!r}"
            )
        if not pi.disqualifying_bits_clear:
            raise TestPassStatementError(
                "disqualifying bits must be clear; "
                f"got {list(pi.disqualifying_bits)!r}"
            )
        if not pi.completeness_admitted:
            raise TestPassStatementError(
                "completeness_admitted must be true for an admitted pass statement"
            )

    def witness_satisfies(self, witness: TestPassPrivateWitness) -> bool:
        """Return True when *witness* satisfies the statement predicate."""

        try:
            assert_witness_satisfies(self, witness)
        except TestPassStatementError:
            return False
        return True


# ---------------------------------------------------------------------------
# Constraint checking
# ---------------------------------------------------------------------------


def _field_equal(fields: Mapping[str, Any], key: str, expected: Any) -> bool:
    if key not in fields:
        return False
    return fields.get(key) == expected


def assert_witness_satisfies(
    statement: TestPassStatementV1,
    witness: TestPassPrivateWitness,
) -> None:
    """Fail closed unless *witness* meets every statement constraint.

    Checks:

    1. receipt preimage digests to public ``receipt_cid``;
    2. when structured fields are available, execution-key / policy / issuer /
       epoch (and optional locator / completeness) match public bindings;
    3. structured phase outcomes are all pass when present;
    4. structured disqualifying bits are clear when present;
    5. public inputs themselves admit a complete pass.
    """

    if not isinstance(statement, TestPassStatementV1):
        raise TestPassStatementError("statement must be TestPassStatementV1")
    if not isinstance(witness, TestPassPrivateWitness):
        raise TestPassStatementError("witness must be TestPassPrivateWitness")

    statement.requires_admitted_pass()

    if not witness.binds_receipt_cid(statement.public_inputs.receipt_cid):
        raise TestPassStatementError(
            "witness does not open public receipt_cid"
        )

    fields = witness.constrained_fields()
    if not fields:
        # Hash-only opening is accepted when no structured fields are available.
        # Production certificate paths should supply structured fields so the
        # circuit can constrain phase/outcome bits inside the receipt.
        return

    pi = statement.public_inputs
    bindings: list[tuple[str, Any]] = [
        ("execution_key_cid", pi.execution_key_cid),
        ("policy_cid", pi.policy_cid),
        ("issuer_id", pi.issuer_id),
        ("epoch", pi.epoch),
    ]
    if pi.locator_cid:
        bindings.append(("locator_cid", pi.locator_cid))
    if pi.completeness_policy_cid:
        bindings.append(("completeness_policy_cid", pi.completeness_policy_cid))

    for key, expected in bindings:
        if key in fields and fields[key] != expected:
            raise TestPassStatementError(
                f"witness field {key!r} does not match public input"
            )

    for phase_key, expected in (
        ("setup_outcome", pi.setup_outcome),
        ("call_outcome", pi.call_outcome),
        ("teardown_outcome", pi.teardown_outcome),
    ):
        if phase_key in fields:
            if fields[phase_key] != expected:
                raise TestPassStatementError(
                    f"witness {phase_key} does not match public input"
                )
            if fields[phase_key] != _PHASE_PASS:
                raise TestPassStatementError(
                    f"witness {phase_key} must be pass"
                )

    if "disqualifying_bits" in fields or "disqualifying_states" in fields:
        raw_bits = fields.get("disqualifying_bits", fields.get("disqualifying_states"))
        bits = _normalize_disqualifying_bits(raw_bits)
        if bits:
            raise TestPassStatementError(
                f"witness carries disqualifying bits: {list(bits)!r}"
            )

    if "admitted" in fields and fields["admitted"] is not True:
        raise TestPassStatementError("witness receipt is not admitted")


def disqualifying_bits_present(bits: Iterable[str]) -> tuple[str, ...]:
    """Return sorted known disqualifying bits from *bits* (empty if clear)."""

    present = []
    for bit in bits:
        text = str(bit).strip().lower()
        if text in DISQUALIFYING_BITS:
            present.append(text)
    return tuple(sorted(set(present)))


def phases_all_pass(
    setup_outcome: str, call_outcome: str, teardown_outcome: str
) -> bool:
    """Return True when all three pytest phases are ``pass``."""

    return (
        str(setup_outcome) == _PHASE_PASS
        and str(call_outcome) == _PHASE_PASS
        and str(teardown_outcome) == _PHASE_PASS
    )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_public_inputs(
    *,
    receipt_cid: str,
    execution_key_cid: str,
    policy_cid: str,
    statement_cid: str,
    circuit_cid: str,
    verifying_key_cid: str,
    issuer_id: str,
    epoch: str,
    setup_outcome: str = _PHASE_PASS,
    call_outcome: str = _PHASE_PASS,
    teardown_outcome: str = _PHASE_PASS,
    disqualifying_bits: Sequence[str] | None = None,
    locator_cid: str = "",
    completeness_policy_cid: str = "",
    completeness_admitted: bool = True,
    extra: Mapping[str, Any] | None = None,
) -> TestPassPublicInputs:
    """Construct validated public inputs for TestPassStatementV1."""

    return TestPassPublicInputs(
        receipt_cid=receipt_cid,
        execution_key_cid=execution_key_cid,
        policy_cid=policy_cid,
        statement_cid=statement_cid,
        circuit_cid=circuit_cid,
        verifying_key_cid=verifying_key_cid,
        issuer_id=issuer_id,
        epoch=epoch,
        setup_outcome=setup_outcome,
        call_outcome=call_outcome,
        teardown_outcome=teardown_outcome,
        disqualifying_bits=tuple(disqualifying_bits or ()),
        locator_cid=locator_cid,
        completeness_policy_cid=completeness_policy_cid,
        completeness_admitted=completeness_admitted,
        extra=dict(extra or {}),
    )


def build_statement(
    public_inputs: TestPassPublicInputs | Mapping[str, Any],
    *,
    require_admitted_pass: bool = True,
) -> TestPassStatementV1:
    """Build a validated statement, optionally requiring admitted pass bits."""

    if isinstance(public_inputs, Mapping):
        pi = TestPassPublicInputs.from_dict(public_inputs)
    elif isinstance(public_inputs, TestPassPublicInputs):
        pi = public_inputs
    else:
        raise TestPassStatementError(
            "public_inputs must be TestPassPublicInputs or a mapping"
        )
    statement = TestPassStatementV1(public_inputs=pi)
    if require_admitted_pass:
        statement.requires_admitted_pass()
    return statement


def build_statement_from_receipt(
    receipt_payload: Mapping[str, Any],
    *,
    execution_key_cid: str,
    policy_cid: str,
    statement_cid: str,
    circuit_cid: str,
    verifying_key_cid: str,
    issuer_id: str,
    epoch: str,
    locator_cid: str = "",
    completeness_policy_cid: str = "",
    completeness_admitted: bool = True,
    extra: Mapping[str, Any] | None = None,
) -> tuple[TestPassStatementV1, TestPassPrivateWitness]:
    """Build a statement + minimal witness pair from a private receipt payload.

    The receipt payload must record all three phases as pass and carry no
    disqualifying bits.  Public outcome bits are derived from the payload when
    present, otherwise default to an admitted complete pass.
    """

    ready = _json_ready(_as_mapping(receipt_payload, "receipt_payload"))
    if not isinstance(ready, dict):
        raise TestPassStatementError("receipt_payload must be a mapping")

    # Normalize constrained bindings into the private payload so the witness
    # opening remains consistent with public inputs.
    payload = dict(ready)
    payload.setdefault("execution_key_cid", execution_key_cid)
    payload.setdefault("policy_cid", policy_cid)
    payload.setdefault("issuer_id", issuer_id)
    payload.setdefault("epoch", epoch)
    if locator_cid:
        payload.setdefault("locator_cid", locator_cid)
    if completeness_policy_cid:
        payload.setdefault("completeness_policy_cid", completeness_policy_cid)
    payload.setdefault("setup_outcome", _PHASE_PASS)
    payload.setdefault("call_outcome", _PHASE_PASS)
    payload.setdefault("teardown_outcome", _PHASE_PASS)
    payload.setdefault("disqualifying_bits", [])
    payload.setdefault("admitted", True)

    if not phases_all_pass(
        str(payload["setup_outcome"]),
        str(payload["call_outcome"]),
        str(payload["teardown_outcome"]),
    ):
        raise TestPassStatementError(
            "receipt payload must have setup, call, and teardown pass"
        )
    bits = _normalize_disqualifying_bits(payload.get("disqualifying_bits") or ())
    if bits:
        raise TestPassStatementError(
            f"receipt payload must not carry disqualifying bits: {list(bits)!r}"
        )
    if payload.get("admitted") is not True:
        raise TestPassStatementError("receipt payload must be admitted")

    # Align constrained fields with public bindings (fail if payload disagrees).
    for key, expected in (
        ("execution_key_cid", execution_key_cid),
        ("policy_cid", policy_cid),
        ("issuer_id", issuer_id),
        ("epoch", epoch),
    ):
        if payload.get(key) != expected:
            raise TestPassStatementError(
                f"receipt payload {key} does not match statement binding"
            )

    witness = TestPassPrivateWitness.from_receipt_payload(payload)
    public = build_public_inputs(
        receipt_cid=witness.opening_digest(),
        execution_key_cid=execution_key_cid,
        policy_cid=policy_cid,
        statement_cid=statement_cid,
        circuit_cid=circuit_cid,
        verifying_key_cid=verifying_key_cid,
        issuer_id=issuer_id,
        epoch=epoch,
        setup_outcome=str(payload["setup_outcome"]),
        call_outcome=str(payload["call_outcome"]),
        teardown_outcome=str(payload["teardown_outcome"]),
        disqualifying_bits=(),
        locator_cid=locator_cid,
        completeness_policy_cid=completeness_policy_cid,
        completeness_admitted=completeness_admitted,
        extra=extra,
    )
    statement = build_statement(public, require_admitted_pass=True)
    assert_witness_satisfies(statement, witness)
    return statement, witness


def validate_public_inputs(data: Mapping[str, Any]) -> TestPassPublicInputs:
    """Validate a raw public-input mapping (rejects malformed/private/nonfinite)."""

    return TestPassPublicInputs.from_dict(data)


def public_identity_bindings(public: TestPassPublicInputs) -> dict[str, str]:
    """Return the required public identity bindings as a plain dict."""

    return {
        "receipt_cid": public.receipt_cid,
        "execution_key_cid": public.execution_key_cid,
        "policy_cid": public.policy_cid,
        "statement_cid": public.statement_cid,
        "circuit_cid": public.circuit_cid,
        "verifying_key_cid": public.verifying_key_cid,
        "issuer_id": public.issuer_id,
        "epoch": public.epoch,
    }


__all__ = [
    "DISQUALIFYING_BITS",
    "MAX_PUBLIC_INPUT_KEYS",
    "MAX_RECEIPT_BYTES",
    "MAX_SEQUENCE_ITEMS",
    "MAX_TEXT_CHARS",
    "PHASE_OUTCOMES",
    "REQUIRED_PUBLIC_IDENTITY_FIELDS",
    "TEST_PASS_CIRCUIT_ID",
    "TEST_PASS_CIRCUIT_REF",
    "TEST_PASS_CIRCUIT_VERSION",
    "TEST_PASS_CONTENT_PROFILE",
    "TEST_PASS_PROOF_DOMAIN",
    "TEST_PASS_PUBLIC_INPUT_SCHEMA",
    "TEST_PASS_RULESET_ID",
    "TEST_PASS_STATEMENT_INTERFACE",
    "TEST_PASS_STATEMENT_VERSION",
    "TestPassPrivateWitness",
    "TestPassPublicInputs",
    "TestPassStatementError",
    "TestPassStatementV1",
    "assert_witness_satisfies",
    "build_public_inputs",
    "build_statement",
    "build_statement_from_receipt",
    "compute_receipt_cid",
    "content_digest_of_bytes",
    "disqualifying_bits_present",
    "phases_all_pass",
    "public_identity_bindings",
    "validate_public_inputs",
]
