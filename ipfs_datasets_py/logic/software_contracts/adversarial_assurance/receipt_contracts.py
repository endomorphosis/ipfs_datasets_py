"""Signed campaign and policy-promotion receipt contracts (AAE-012).

Defines closed, versioned durable models for ``AssuranceCampaignReceipt`` and
``AssurancePolicyPromotionReceipt``, plus the frozen package catalog interface
``AdversarialAssuranceArtifacts@1``.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Signed evidence reuses the existing receipt/signature authority field
  vocabulary (EdDSA over ``did:key`` identities, base64url signature bytes,
  audience/action bindings). This module defines no new envelope, CID profile,
  or cryptographic scheme and does not perform host key operations.
* Signature verification status is an explicit closed field; content addressing
  never substitutes for authenticity.
* Complete live terminal status requires verified signatures and nonempty
  signature bytes.
* Candidates cannot self-authorize promotion; authorization CIDs must be
  distinct external evidence.
* Private material, model-written authority, and host fallbacks fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    AssuranceTerminalStatus,
    ExecutionMode,
    reject_private_model_authority_and_host_fallbacks,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE: Final[str] = "AssuranceCampaignReceipt@1"
ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-campaign-receipt@1"
)
ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE: Final[str] = (
    "AssurancePolicyPromotionReceipt@1"
)
ASSURANCE_POLICY_PROMOTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-policy-promotion-receipt@1"
)
RECEIPT_SIGNATURE_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-receipt-signature-binding@1"
)
ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE: Final[str] = (
    "AdversarialAssuranceArtifacts@1"
)
ADVERSARIAL_ASSURANCE_ARTIFACTS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-artifacts@1"
)

# Existing signature authority vocabulary (Profile G / Ed25519 did:key).
EXISTING_SIGNATURE_ALGORITHM: Final[str] = "EdDSA"
EXISTING_SIGNATURE_AUTHORITY: Final[str] = (
    "ipfs-datasets.profile-g.ed25519-did-key@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ID_LIST: Final[int] = 4_096
MAX_TOKEN_LIST: Final[int] = 256
MAX_SEAL_SCOPE: Final[int] = 64
MAX_SIGNATURE_CHARS: Final[int] = 512
MAX_REVISION: Final[int] = 2**63 - 1

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_DID_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^did:key:z[1-9A-HJ-NP-Za-km-z]{10,200}$"
)
# Base64url (no padding) encoding of Ed25519 signature bytes (64 bytes → 86 chars).
_SIGNATURE_B64URL_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9_-]{43,512}$"
)


class ReceiptContractError(AssuranceBaseError):
    """Raised when a campaign/promotion receipt contract is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class SignatureVerificationStatus(str, Enum):
    """Closed signature-verification status from the existing signer authority.

    Contracts record the status; cryptographic verification is performed by the
    existing receipt/signature authority, never by a second scheme here.
    """

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


class HeldOutResult(str, Enum):
    """Closed held-out evaluation result vocabulary."""

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


class SealAvailabilityStatus(str, Enum):
    """Whether released incremental seal evidence is bound, unavailable, etc."""

    BOUND = "bound"
    RELEASED = "released"
    UNAVAILABLE = "unavailable"
    NOT_REQUESTED = "not_requested"
    REJECTED = "rejected"


class SealScopeItem(str, Enum):
    """Closed seal-scope components the campaign seal may commit (plan §14).

    The seal commits exact bytes and completeness for these items. It never
    establishes repository correctness or mutation-set completeness by itself.
    """

    OPERATOR_VERSIONS = "operator_versions"
    CAMPAIGN_POLICY = "campaign_policy"
    ADMITTED_SET = "admitted_set"
    EXPECTED_DETECTION_SETS = "expected_detection_sets"
    OUTCOMES = "outcomes"
    SURVIVOR_REPORTS = "survivor_reports"
    VACUITY_FINDINGS = "vacuity_findings"
    HELD_OUT_EVALUATIONS = "held_out_evaluations"
    FINAL_POLICY_REVISION = "final_policy_revision"
    CAMPAIGN_ARTIFACTS = "campaign_artifacts"
    DECLARED_RESULT_COMPLETENESS = "declared_result_completeness"
    EVALUATION_TO_PROMOTION_BINDING = "evaluation_to_promotion_binding"
    STATUS_POLICY_SATISFACTION = "status_policy_satisfaction"
    CAMPAIGN_RECEIPT = "campaign_receipt"
    PROMOTION_RECEIPT = "promotion_receipt"


class ReceiptAction(str, Enum):
    """Closed action identities bound into signed receipt evidence."""

    SEAL_CAMPAIGN = "seal_campaign"
    COMPLETE_CAMPAIGN = "complete_campaign"
    PROMOTE_POLICY = "promote_policy"
    ROLLBACK_POLICY = "rollback_policy"
    AUTHORIZE_PROMOTION = "authorize_promotion"


# Terminal statuses that may claim verified production-complete evidence.
_COMPLETE_REQUIRES_VERIFIED: Final[frozenset[str]] = frozenset(
    {
        AssuranceTerminalStatus.COMPLETE.value,
    }
)

# Signature statuses that admit durable production use.
_PRODUCTION_SIGNATURE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        SignatureVerificationStatus.VERIFIED.value,
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise ReceiptContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ReceiptContractError(f"{name} must be trimmed NFC text")
    if len(value) > maximum or any(not char.isprintable() for char in value):
        raise ReceiptContractError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ReceiptContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ReceiptContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise ReceiptContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise ReceiptContractError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ReceiptContractError(f"{name} must be a boolean")
    return value


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ReceiptContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise ReceiptContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise ReceiptContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ReceiptContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise ReceiptContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise ReceiptContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    maximum: int = MAX_SEAL_SCOPE,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ReceiptContractError(f"{name} must be a list")
    ordered = tuple(sorted(_enum(value, enum_type, name) for value in values))
    if len(ordered) > maximum:
        raise ReceiptContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise ReceiptContractError(f"{name} must not contain duplicates")
    return ordered


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        return AssuranceArtifactHeader.from_dict(value)
    raise ReceiptContractError(f"{name} must be AssuranceArtifactHeader or mapping")


def _did_key(value: Any, name: str) -> str:
    text = _text(value, name, maximum=256)
    if _DID_KEY_RE.fullmatch(text) is None:
        raise ReceiptContractError(
            f"{name} must be an Ed25519 did:key identity matching {_DID_KEY_RE.pattern}"
        )
    return text


def _audience_or_action_identity(value: Any, name: str) -> str:
    """Audience/action may be a lowercase token or a did:key identity."""

    text = _text(value, name, maximum=256)
    if _TOKEN_RE.fullmatch(text) is not None or _DID_KEY_RE.fullmatch(text) is not None:
        return text
    raise ReceiptContractError(
        f"{name} must be a lowercase token or did:key identity"
    )


def _key_identity(value: Any, name: str) -> str:
    """Key identity is a content-addressed key CID or the signer did:key."""

    text = _text(value, name, maximum=256)
    if _DID_KEY_RE.fullmatch(text) is not None:
        return text
    try:
        return validate_cid(text)
    except Exception as exc:
        raise ReceiptContractError(
            f"{name} must be a valid key CID or did:key identity"
        ) from exc


def _signature_bytes(value: Any, name: str) -> str:
    """Opaque base64url signature bytes from the existing EdDSA authority."""

    text = _text(value, name, maximum=MAX_SIGNATURE_CHARS)
    if _SIGNATURE_B64URL_RE.fullmatch(text) is None:
        raise ReceiptContractError(
            f"{name} must be nonempty base64url signature bytes"
        )
    return text


# ---------------------------------------------------------------------------
# ReceiptSignatureBinding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReceiptSignatureBinding:
    """Existing-authority signature binding for signed assurance evidence.

    Binds signer/key/audience/action identities, EdDSA signature bytes, and
    verification status without introducing a second envelope or crypto API.
    """

    signer_identity: str
    key_identity: str
    audience: str
    action: str
    signature: str
    signature_verification_status: SignatureVerificationStatus | str
    signature_algorithm: str = EXISTING_SIGNATURE_ALGORITHM
    signature_authority: str = EXISTING_SIGNATURE_AUTHORITY

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "signer_identity",
            "key_identity",
            "audience",
            "action",
            "signature_algorithm",
            "signature_authority",
            "signature",
            "signature_verification_status",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "signer_identity", _did_key(self.signer_identity, "signer_identity")
        )
        object.__setattr__(
            self, "key_identity", _key_identity(self.key_identity, "key_identity")
        )
        object.__setattr__(
            self, "audience", _audience_or_action_identity(self.audience, "audience")
        )
        # Prefer closed ReceiptAction tokens when possible; allow did:key or token.
        action_raw = self.action
        try:
            action = _enum(action_raw, ReceiptAction, "action")
        except ReceiptContractError:
            action = _audience_or_action_identity(action_raw, "action")
        object.__setattr__(self, "action", action)
        algorithm = _text(self.signature_algorithm, "signature_algorithm", maximum=64)
        if algorithm != EXISTING_SIGNATURE_ALGORITHM:
            raise ReceiptContractError(
                "signature_algorithm must reuse the existing EdDSA authority "
                f"({EXISTING_SIGNATURE_ALGORITHM!r}); new schemes are forbidden"
            )
        object.__setattr__(self, "signature_algorithm", algorithm)
        authority = _text(self.signature_authority, "signature_authority", maximum=256)
        if authority != EXISTING_SIGNATURE_AUTHORITY:
            raise ReceiptContractError(
                "signature_authority must reuse the existing receipt/signature "
                f"authority ({EXISTING_SIGNATURE_AUTHORITY!r})"
            )
        object.__setattr__(self, "signature_authority", authority)
        status = _enum(
            self.signature_verification_status,
            SignatureVerificationStatus,
            "signature_verification_status",
        )
        object.__setattr__(self, "signature_verification_status", status)
        if status == SignatureVerificationStatus.VERIFIED.value:
            object.__setattr__(self, "signature", _signature_bytes(self.signature, "signature"))
        else:
            # Non-verified statuses still bind opaque signature material when present,
            # but allow empty only for unavailable (typed missing capability).
            if self.signature in (None, ""):
                if status != SignatureVerificationStatus.UNAVAILABLE.value:
                    raise ReceiptContractError(
                        "signature bytes required unless signature_verification_status "
                        "is unavailable"
                    )
                object.__setattr__(self, "signature", "")
            else:
                object.__setattr__(
                    self, "signature", _signature_bytes(self.signature, "signature")
                )
        if (
            status == SignatureVerificationStatus.VERIFIED.value
            and self.key_identity.startswith("did:key:")
            and self.key_identity != self.signer_identity
        ):
            raise ReceiptContractError(
                "when key_identity is a did:key it must match signer_identity"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SIGNATURE_BINDING_SCHEMA,
            "signer_identity": self.signer_identity,
            "key_identity": self.key_identity,
            "audience": self.audience,
            "action": self.action,
            "signature_algorithm": self.signature_algorithm,
            "signature_authority": self.signature_authority,
            "signature": self.signature,
            "signature_verification_status": self.signature_verification_status,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReceiptSignatureBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != RECEIPT_SIGNATURE_BINDING_SCHEMA:
            raise ReceiptContractError(
                "unsupported ReceiptSignatureBinding schema version"
            )
        result = cls(
            signer_identity=payload["signer_identity"],
            key_identity=payload["key_identity"],
            audience=payload["audience"],
            action=payload["action"],
            signature=payload["signature"],
            signature_verification_status=payload["signature_verification_status"],
            signature_algorithm=payload["signature_algorithm"],
            signature_authority=payload["signature_authority"],
        )
        if claimed != result.binding_cid:
            raise ReceiptContractError(
                "ReceiptSignatureBinding binding_cid identity mismatch"
            )
        return result


def _normalize_signature_binding(
    value: Any, name: str = "signature"
) -> ReceiptSignatureBinding:
    if isinstance(value, ReceiptSignatureBinding):
        return value
    if isinstance(value, Mapping):
        return ReceiptSignatureBinding.from_dict(value)
    raise ReceiptContractError(f"{name} must be ReceiptSignatureBinding or mapping")


def _assert_signature_matches_terminal(
    *,
    header: AssuranceArtifactHeader,
    signature: ReceiptSignatureBinding,
    name: str,
) -> None:
    """Fail closed when complete live evidence lacks verified signatures."""

    if header.terminal_status not in _COMPLETE_REQUIRES_VERIFIED:
        return
    if header.provenance.execution_mode == ExecutionMode.SIMULATED.value:
        raise ReceiptContractError(
            f"{name}: simulated provenance cannot claim complete terminal_status"
        )
    if signature.signature_verification_status not in _PRODUCTION_SIGNATURE_STATUSES:
        raise ReceiptContractError(
            f"{name}: complete terminal_status requires "
            "signature_verification_status=verified"
        )
    if not signature.signature:
        raise ReceiptContractError(
            f"{name}: complete terminal_status requires nonempty signature bytes"
        )


# ---------------------------------------------------------------------------
# AssuranceCampaignReceipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssuranceCampaignReceipt:
    """Signed, content-addressed campaign completion receipt.

    Interface: ``AssuranceCampaignReceipt@1``

    Binds complete campaign inputs, authorization, expected-old revision,
    held-out result, seal scope, terminal status (via header), signer/key/
    audience/action identities, signature bytes, signature-verification status,
    and canonical identity. Signature verification reuses the existing
    EdDSA/did:key authority vocabulary and defines no new envelope.
    """

    header: AssuranceArtifactHeader
    receipt_id: str
    campaign_plan_cid: str
    campaign_policy_cid: str
    campaign_policy_version: str
    admitted_set_cid: str
    expected_detection_sets_cid: str
    outcomes_cid: str
    survivor_reports_cid: str
    vacuity_findings_cid: str
    held_out_evaluation_cid: str
    held_out_result: HeldOutResult | str
    authorization_cid: str
    expected_old_revision: str
    seal_scope: Sequence[SealScopeItem | str]
    seal_status: SealAvailabilityStatus | str
    signature: ReceiptSignatureBinding | Mapping[str, Any]
    seal_evidence_cid: str | None = None
    gap_reports_cid: str | None = None
    input_artifact_cids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "receipt_id",
            "campaign_plan_cid",
            "campaign_policy_cid",
            "campaign_policy_version",
            "admitted_set_cid",
            "expected_detection_sets_cid",
            "outcomes_cid",
            "survivor_reports_cid",
            "vacuity_findings_cid",
            "held_out_evaluation_cid",
            "held_out_result",
            "authorization_cid",
            "expected_old_revision",
            "seal_scope",
            "seal_status",
            "seal_evidence_cid",
            "gap_reports_cid",
            "input_artifact_cids",
            "signature",
            "notes",
            "metadata",
            "receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "assurance_campaign_receipt":
            raise ReceiptContractError(
                "header.artifact_kind must be assurance_campaign_receipt"
            )
        object.__setattr__(self, "receipt_id", _token(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "campaign_plan_cid", _cid(self.campaign_plan_cid, "campaign_plan_cid")
        )
        object.__setattr__(
            self,
            "campaign_policy_cid",
            _cid(self.campaign_policy_cid, "campaign_policy_cid"),
        )
        object.__setattr__(
            self,
            "campaign_policy_version",
            _version(self.campaign_policy_version, "campaign_policy_version"),
        )
        object.__setattr__(
            self, "admitted_set_cid", _cid(self.admitted_set_cid, "admitted_set_cid")
        )
        object.__setattr__(
            self,
            "expected_detection_sets_cid",
            _cid(self.expected_detection_sets_cid, "expected_detection_sets_cid"),
        )
        object.__setattr__(self, "outcomes_cid", _cid(self.outcomes_cid, "outcomes_cid"))
        object.__setattr__(
            self,
            "survivor_reports_cid",
            _cid(self.survivor_reports_cid, "survivor_reports_cid"),
        )
        object.__setattr__(
            self,
            "vacuity_findings_cid",
            _cid(self.vacuity_findings_cid, "vacuity_findings_cid"),
        )
        object.__setattr__(
            self,
            "held_out_evaluation_cid",
            _cid(self.held_out_evaluation_cid, "held_out_evaluation_cid"),
        )
        held_out = _enum(self.held_out_result, HeldOutResult, "held_out_result")
        object.__setattr__(self, "held_out_result", held_out)
        object.__setattr__(
            self, "authorization_cid", _cid(self.authorization_cid, "authorization_cid")
        )
        object.__setattr__(
            self,
            "expected_old_revision",
            _version(self.expected_old_revision, "expected_old_revision"),
        )
        scope = _unique_sorted_enums(
            list(self.seal_scope), SealScopeItem, "seal_scope"
        )
        if not scope:
            raise ReceiptContractError("seal_scope must not be empty")
        object.__setattr__(self, "seal_scope", scope)
        seal_status = _enum(self.seal_status, SealAvailabilityStatus, "seal_status")
        object.__setattr__(self, "seal_status", seal_status)
        seal_evidence = _optional_cid(self.seal_evidence_cid, "seal_evidence_cid")
        if seal_status in {
            SealAvailabilityStatus.BOUND.value,
            SealAvailabilityStatus.RELEASED.value,
        } and seal_evidence is None:
            raise ReceiptContractError(
                "bound/released seal_status requires seal_evidence_cid"
            )
        if seal_status == SealAvailabilityStatus.UNAVAILABLE.value and seal_evidence is not None:
            raise ReceiptContractError(
                "unavailable seal_status forbids seal_evidence_cid"
            )
        object.__setattr__(self, "seal_evidence_cid", seal_evidence)
        object.__setattr__(
            self, "gap_reports_cid", _optional_cid(self.gap_reports_cid, "gap_reports_cid")
        )
        object.__setattr__(
            self,
            "input_artifact_cids",
            _unique_sorted_cids(list(self.input_artifact_cids), "input_artifact_cids"),
        )
        signature = _normalize_signature_binding(self.signature, "signature")
        object.__setattr__(self, "signature", signature)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        # Self-authorization is always rejected.
        forbidden = {
            self.campaign_plan_cid,
            self.campaign_policy_cid,
            self.admitted_set_cid,
            self.expected_detection_sets_cid,
            self.outcomes_cid,
            self.survivor_reports_cid,
            self.vacuity_findings_cid,
            self.held_out_evaluation_cid,
        }
        if self.gap_reports_cid is not None:
            forbidden.add(self.gap_reports_cid)
        if self.authorization_cid in forbidden:
            raise ReceiptContractError(
                "authorization_cid must be distinct external authorization evidence"
            )
        provisional = cid_for_structured(self._identity_payload_body())
        if self.authorization_cid == provisional:
            raise ReceiptContractError("campaign receipt cannot self-authorize")

        _assert_signature_matches_terminal(
            header=self.header, signature=signature, name="AssuranceCampaignReceipt"
        )
        if (
            self.header.terminal_status == AssuranceTerminalStatus.COMPLETE.value
            and held_out != HeldOutResult.PASSED.value
            and held_out != HeldOutResult.NOT_APPLICABLE.value
        ):
            raise ReceiptContractError(
                "complete campaign receipt requires held_out_result "
                "passed or not_applicable"
            )
        if signature.action not in {
            ReceiptAction.SEAL_CAMPAIGN.value,
            ReceiptAction.COMPLETE_CAMPAIGN.value,
        }:
            # Allow custom token actions only when not claiming complete.
            if self.header.terminal_status == AssuranceTerminalStatus.COMPLETE.value:
                raise ReceiptContractError(
                    "complete campaign receipt signature.action must be "
                    "seal_campaign or complete_campaign"
                )

    def _identity_payload_body(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA,
            "interface_id": ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE,
            "header": self.header.identity_payload(),
            "receipt_id": self.receipt_id,
            "campaign_plan_cid": self.campaign_plan_cid,
            "campaign_policy_cid": self.campaign_policy_cid,
            "campaign_policy_version": self.campaign_policy_version,
            "admitted_set_cid": self.admitted_set_cid,
            "expected_detection_sets_cid": self.expected_detection_sets_cid,
            "outcomes_cid": self.outcomes_cid,
            "survivor_reports_cid": self.survivor_reports_cid,
            "vacuity_findings_cid": self.vacuity_findings_cid,
            "held_out_evaluation_cid": self.held_out_evaluation_cid,
            "held_out_result": self.held_out_result,
            "authorization_cid": self.authorization_cid,
            "expected_old_revision": self.expected_old_revision,
            "seal_scope": list(self.seal_scope),
            "seal_status": self.seal_status,
            "seal_evidence_cid": self.seal_evidence_cid,
            "gap_reports_cid": self.gap_reports_cid,
            "input_artifact_cids": list(self.input_artifact_cids),
            "signature": self.signature.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    def identity_payload(self) -> dict[str, Any]:
        return self._identity_payload_body()

    @property
    def receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA,
            "interface_id": ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE,
            "header": self.header.to_dict(),
            "receipt_id": self.receipt_id,
            "campaign_plan_cid": self.campaign_plan_cid,
            "campaign_policy_cid": self.campaign_policy_cid,
            "campaign_policy_version": self.campaign_policy_version,
            "admitted_set_cid": self.admitted_set_cid,
            "expected_detection_sets_cid": self.expected_detection_sets_cid,
            "outcomes_cid": self.outcomes_cid,
            "survivor_reports_cid": self.survivor_reports_cid,
            "vacuity_findings_cid": self.vacuity_findings_cid,
            "held_out_evaluation_cid": self.held_out_evaluation_cid,
            "held_out_result": self.held_out_result,
            "authorization_cid": self.authorization_cid,
            "expected_old_revision": self.expected_old_revision,
            "seal_scope": list(self.seal_scope),
            "seal_status": self.seal_status,
            "seal_evidence_cid": self.seal_evidence_cid,
            "gap_reports_cid": self.gap_reports_cid,
            "input_artifact_cids": list(self.input_artifact_cids),
            "signature": self.signature.to_dict(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssuranceCampaignReceipt":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("receipt_cid")
        if payload.pop("schema") != ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA:
            raise ReceiptContractError(
                "unsupported AssuranceCampaignReceipt schema version"
            )
        if payload.pop("interface_id") != ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE:
            raise ReceiptContractError(
                "unsupported AssuranceCampaignReceipt interface_id"
            )
        result = cls(
            header=payload["header"],
            receipt_id=payload["receipt_id"],
            campaign_plan_cid=payload["campaign_plan_cid"],
            campaign_policy_cid=payload["campaign_policy_cid"],
            campaign_policy_version=payload["campaign_policy_version"],
            admitted_set_cid=payload["admitted_set_cid"],
            expected_detection_sets_cid=payload["expected_detection_sets_cid"],
            outcomes_cid=payload["outcomes_cid"],
            survivor_reports_cid=payload["survivor_reports_cid"],
            vacuity_findings_cid=payload["vacuity_findings_cid"],
            held_out_evaluation_cid=payload["held_out_evaluation_cid"],
            held_out_result=payload["held_out_result"],
            authorization_cid=payload["authorization_cid"],
            expected_old_revision=payload["expected_old_revision"],
            seal_scope=payload["seal_scope"],
            seal_status=payload["seal_status"],
            signature=payload["signature"],
            seal_evidence_cid=payload["seal_evidence_cid"],
            gap_reports_cid=payload["gap_reports_cid"],
            input_artifact_cids=payload["input_artifact_cids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.receipt_cid:
            raise ReceiptContractError(
                "AssuranceCampaignReceipt receipt_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# AssurancePolicyPromotionReceipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssurancePolicyPromotionReceipt:
    """Signed, content-addressed policy-promotion receipt.

    Interface: ``AssurancePolicyPromotionReceipt@1``

    Promotion requires canonical candidate identity, held-out result, external
    authorization, expected-old policy revision CAS, seal scope, verified
    signature bindings, and terminal status. Candidates cannot self-promote.
    """

    header: AssuranceArtifactHeader
    receipt_id: str
    campaign_receipt_cid: str
    candidate_cid: str
    evaluation_report_cid: str
    held_out_result: HeldOutResult | str
    authorization_cid: str
    expected_old_policy_cid: str
    expected_old_policy_version: str
    previous_policy_cid: str
    previous_policy_version: str
    promoted_policy_cid: str
    promoted_policy_version: str
    rollback_policy_cid: str
    cas_expected_version: str
    seal_scope: Sequence[SealScopeItem | str]
    seal_status: SealAvailabilityStatus | str
    signature: ReceiptSignatureBinding | Mapping[str, Any]
    held_out_evaluation_cid: str | None = None
    seal_evidence_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "receipt_id",
            "campaign_receipt_cid",
            "candidate_cid",
            "evaluation_report_cid",
            "held_out_evaluation_cid",
            "held_out_result",
            "authorization_cid",
            "expected_old_policy_cid",
            "expected_old_policy_version",
            "previous_policy_cid",
            "previous_policy_version",
            "promoted_policy_cid",
            "promoted_policy_version",
            "rollback_policy_cid",
            "cas_expected_version",
            "seal_scope",
            "seal_status",
            "seal_evidence_cid",
            "signature",
            "notes",
            "metadata",
            "receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "assurance_policy_promotion_receipt":
            raise ReceiptContractError(
                "header.artifact_kind must be assurance_policy_promotion_receipt"
            )
        object.__setattr__(self, "receipt_id", _token(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self,
            "campaign_receipt_cid",
            _cid(self.campaign_receipt_cid, "campaign_receipt_cid"),
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(
            self,
            "evaluation_report_cid",
            _cid(self.evaluation_report_cid, "evaluation_report_cid"),
        )
        object.__setattr__(
            self,
            "held_out_evaluation_cid",
            _optional_cid(self.held_out_evaluation_cid, "held_out_evaluation_cid"),
        )
        held_out = _enum(self.held_out_result, HeldOutResult, "held_out_result")
        object.__setattr__(self, "held_out_result", held_out)
        object.__setattr__(
            self, "authorization_cid", _cid(self.authorization_cid, "authorization_cid")
        )
        object.__setattr__(
            self,
            "expected_old_policy_cid",
            _cid(self.expected_old_policy_cid, "expected_old_policy_cid"),
        )
        object.__setattr__(
            self,
            "expected_old_policy_version",
            _version(self.expected_old_policy_version, "expected_old_policy_version"),
        )
        object.__setattr__(
            self,
            "previous_policy_cid",
            _cid(self.previous_policy_cid, "previous_policy_cid"),
        )
        object.__setattr__(
            self,
            "previous_policy_version",
            _version(self.previous_policy_version, "previous_policy_version"),
        )
        object.__setattr__(
            self,
            "promoted_policy_cid",
            _cid(self.promoted_policy_cid, "promoted_policy_cid"),
        )
        object.__setattr__(
            self,
            "promoted_policy_version",
            _version(self.promoted_policy_version, "promoted_policy_version"),
        )
        object.__setattr__(
            self,
            "rollback_policy_cid",
            _cid(self.rollback_policy_cid, "rollback_policy_cid"),
        )
        object.__setattr__(
            self,
            "cas_expected_version",
            _version(self.cas_expected_version, "cas_expected_version"),
        )
        # CAS expected-old must agree with declared previous/expected-old pins.
        if self.cas_expected_version != self.expected_old_policy_version:
            raise ReceiptContractError(
                "cas_expected_version must equal expected_old_policy_version"
            )
        if self.previous_policy_version != self.expected_old_policy_version:
            raise ReceiptContractError(
                "previous_policy_version must equal expected_old_policy_version"
            )
        if self.previous_policy_cid != self.expected_old_policy_cid:
            raise ReceiptContractError(
                "previous_policy_cid must equal expected_old_policy_cid"
            )
        if self.promoted_policy_cid == self.previous_policy_cid:
            raise ReceiptContractError(
                "promoted_policy_cid must differ from previous_policy_cid"
            )
        if self.promoted_policy_version == self.previous_policy_version:
            raise ReceiptContractError(
                "promoted_policy_version must differ from previous_policy_version"
            )
        scope = _unique_sorted_enums(
            list(self.seal_scope), SealScopeItem, "seal_scope"
        )
        if not scope:
            raise ReceiptContractError("seal_scope must not be empty")
        if SealScopeItem.FINAL_POLICY_REVISION.value not in scope:
            raise ReceiptContractError(
                "promotion seal_scope must include final_policy_revision"
            )
        if SealScopeItem.EVALUATION_TO_PROMOTION_BINDING.value not in scope:
            raise ReceiptContractError(
                "promotion seal_scope must include evaluation_to_promotion_binding"
            )
        object.__setattr__(self, "seal_scope", scope)
        seal_status = _enum(self.seal_status, SealAvailabilityStatus, "seal_status")
        object.__setattr__(self, "seal_status", seal_status)
        seal_evidence = _optional_cid(self.seal_evidence_cid, "seal_evidence_cid")
        if seal_status in {
            SealAvailabilityStatus.BOUND.value,
            SealAvailabilityStatus.RELEASED.value,
        } and seal_evidence is None:
            raise ReceiptContractError(
                "bound/released seal_status requires seal_evidence_cid"
            )
        if seal_status == SealAvailabilityStatus.UNAVAILABLE.value and seal_evidence is not None:
            raise ReceiptContractError(
                "unavailable seal_status forbids seal_evidence_cid"
            )
        object.__setattr__(self, "seal_evidence_cid", seal_evidence)
        signature = _normalize_signature_binding(self.signature, "signature")
        object.__setattr__(self, "signature", signature)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        forbidden = {
            self.campaign_receipt_cid,
            self.candidate_cid,
            self.evaluation_report_cid,
            self.expected_old_policy_cid,
            self.previous_policy_cid,
            self.promoted_policy_cid,
            self.rollback_policy_cid,
        }
        if self.held_out_evaluation_cid is not None:
            forbidden.add(self.held_out_evaluation_cid)
        if self.authorization_cid in forbidden:
            raise ReceiptContractError(
                "candidates cannot self-authorize; authorization_cid must be a "
                "distinct external authorization"
            )
        provisional = cid_for_structured(self._identity_payload_body())
        if self.authorization_cid == provisional:
            raise ReceiptContractError("promotion receipt cannot self-authorize")

        _assert_signature_matches_terminal(
            header=self.header,
            signature=signature,
            name="AssurancePolicyPromotionReceipt",
        )
        if self.header.terminal_status == AssuranceTerminalStatus.COMPLETE.value:
            if held_out != HeldOutResult.PASSED.value:
                raise ReceiptContractError(
                    "complete promotion receipt requires held_out_result=passed"
                )
            if signature.action != ReceiptAction.PROMOTE_POLICY.value:
                raise ReceiptContractError(
                    "complete promotion receipt signature.action must be promote_policy"
                )

    def _identity_payload_body(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_POLICY_PROMOTION_RECEIPT_SCHEMA,
            "interface_id": ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE,
            "header": self.header.identity_payload(),
            "receipt_id": self.receipt_id,
            "campaign_receipt_cid": self.campaign_receipt_cid,
            "candidate_cid": self.candidate_cid,
            "evaluation_report_cid": self.evaluation_report_cid,
            "held_out_evaluation_cid": self.held_out_evaluation_cid,
            "held_out_result": self.held_out_result,
            "authorization_cid": self.authorization_cid,
            "expected_old_policy_cid": self.expected_old_policy_cid,
            "expected_old_policy_version": self.expected_old_policy_version,
            "previous_policy_cid": self.previous_policy_cid,
            "previous_policy_version": self.previous_policy_version,
            "promoted_policy_cid": self.promoted_policy_cid,
            "promoted_policy_version": self.promoted_policy_version,
            "rollback_policy_cid": self.rollback_policy_cid,
            "cas_expected_version": self.cas_expected_version,
            "seal_scope": list(self.seal_scope),
            "seal_status": self.seal_status,
            "seal_evidence_cid": self.seal_evidence_cid,
            "signature": self.signature.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    def identity_payload(self) -> dict[str, Any]:
        return self._identity_payload_body()

    @property
    def receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_POLICY_PROMOTION_RECEIPT_SCHEMA,
            "interface_id": ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE,
            "header": self.header.to_dict(),
            "receipt_id": self.receipt_id,
            "campaign_receipt_cid": self.campaign_receipt_cid,
            "candidate_cid": self.candidate_cid,
            "evaluation_report_cid": self.evaluation_report_cid,
            "held_out_evaluation_cid": self.held_out_evaluation_cid,
            "held_out_result": self.held_out_result,
            "authorization_cid": self.authorization_cid,
            "expected_old_policy_cid": self.expected_old_policy_cid,
            "expected_old_policy_version": self.expected_old_policy_version,
            "previous_policy_cid": self.previous_policy_cid,
            "previous_policy_version": self.previous_policy_version,
            "promoted_policy_cid": self.promoted_policy_cid,
            "promoted_policy_version": self.promoted_policy_version,
            "rollback_policy_cid": self.rollback_policy_cid,
            "cas_expected_version": self.cas_expected_version,
            "seal_scope": list(self.seal_scope),
            "seal_status": self.seal_status,
            "seal_evidence_cid": self.seal_evidence_cid,
            "signature": self.signature.to_dict(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssurancePolicyPromotionReceipt":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("receipt_cid")
        if payload.pop("schema") != ASSURANCE_POLICY_PROMOTION_RECEIPT_SCHEMA:
            raise ReceiptContractError(
                "unsupported AssurancePolicyPromotionReceipt schema version"
            )
        if payload.pop("interface_id") != ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE:
            raise ReceiptContractError(
                "unsupported AssurancePolicyPromotionReceipt interface_id"
            )
        result = cls(
            header=payload["header"],
            receipt_id=payload["receipt_id"],
            campaign_receipt_cid=payload["campaign_receipt_cid"],
            candidate_cid=payload["candidate_cid"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            held_out_result=payload["held_out_result"],
            authorization_cid=payload["authorization_cid"],
            expected_old_policy_cid=payload["expected_old_policy_cid"],
            expected_old_policy_version=payload["expected_old_policy_version"],
            previous_policy_cid=payload["previous_policy_cid"],
            previous_policy_version=payload["previous_policy_version"],
            promoted_policy_cid=payload["promoted_policy_cid"],
            promoted_policy_version=payload["promoted_policy_version"],
            rollback_policy_cid=payload["rollback_policy_cid"],
            cas_expected_version=payload["cas_expected_version"],
            seal_scope=payload["seal_scope"],
            seal_status=payload["seal_status"],
            signature=payload["signature"],
            held_out_evaluation_cid=payload["held_out_evaluation_cid"],
            seal_evidence_cid=payload["seal_evidence_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.receipt_cid:
            raise ReceiptContractError(
                "AssurancePolicyPromotionReceipt receipt_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# AdversarialAssuranceArtifacts@1 — frozen package catalog
# ---------------------------------------------------------------------------


def _artifact_entry(
    *,
    name: str,
    interface_id: str,
    schema: str,
    module: str,
    artifact_kind: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": name,
        "interface_id": interface_id,
        "schema": schema,
        "module": module,
    }
    if artifact_kind is not None:
        entry["artifact_kind"] = artifact_kind
    return entry


def adversarial_assurance_artifact_catalog() -> tuple[Mapping[str, Any], ...]:
    """Return the frozen AAE-007…AAE-012 artifact catalog in stable order."""

    # Local imports keep module load free of circular import costs for
    # receipt-only consumers while still binding the complete export surface.
    from ipfs_datasets_py.logic.software_contracts.adversarial_assurance import (
        analysis_contracts as analysis,
        common as common_mod,
        execution_contracts as execution,
        mutation_contracts as mutation,
        remediation_contracts as remediation,
    )

    entries = (
        _artifact_entry(
            name="AssuranceArtifactHeader",
            interface_id=common_mod.ASSURANCE_ARTIFACT_HEADER_INTERFACE,
            schema=common_mod.ASSURANCE_ARTIFACT_HEADER_SCHEMA,
            module="common",
        ),
        _artifact_entry(
            name="MutationOperatorDefinition",
            interface_id=mutation.MUTATION_OPERATOR_DEFINITION_INTERFACE,
            schema=mutation.MUTATION_OPERATOR_DEFINITION_SCHEMA,
            module="mutation_contracts",
            artifact_kind="mutation_operator_definition",
        ),
        _artifact_entry(
            name="MutationTarget",
            interface_id=mutation.MUTATION_TARGET_INTERFACE,
            schema=mutation.MUTATION_TARGET_SCHEMA,
            module="mutation_contracts",
            artifact_kind="mutation_target",
        ),
        _artifact_entry(
            name="MutationCandidate",
            interface_id=mutation.MUTATION_CANDIDATE_INTERFACE,
            schema=mutation.MUTATION_CANDIDATE_SCHEMA,
            module="mutation_contracts",
            artifact_kind="mutation_candidate",
        ),
        _artifact_entry(
            name="MutationCampaignPolicy",
            interface_id=mutation.MUTATION_CAMPAIGN_POLICY_INTERFACE,
            schema=mutation.MUTATION_CAMPAIGN_POLICY_SCHEMA,
            module="mutation_contracts",
            artifact_kind="mutation_campaign_policy",
        ),
        _artifact_entry(
            name="MutationCampaignPlan",
            interface_id=mutation.MUTATION_CAMPAIGN_PLAN_INTERFACE,
            schema=mutation.MUTATION_CAMPAIGN_PLAN_SCHEMA,
            module="mutation_contracts",
            artifact_kind="mutation_campaign_plan",
        ),
        _artifact_entry(
            name="ExpectedDetectionSet",
            interface_id=execution.EXPECTED_DETECTION_SET_INTERFACE,
            schema=execution.EXPECTED_DETECTION_SET_SCHEMA,
            module="execution_contracts",
            artifact_kind="expected_detection_set",
        ),
        _artifact_entry(
            name="MutationExecutionPlan",
            interface_id=execution.MUTATION_EXECUTION_PLAN_INTERFACE,
            schema=execution.MUTATION_EXECUTION_PLAN_SCHEMA,
            module="execution_contracts",
            artifact_kind="mutation_execution_plan",
        ),
        _artifact_entry(
            name="MutationExecutionReceipt",
            interface_id=execution.MUTATION_EXECUTION_RECEIPT_INTERFACE,
            schema=execution.MUTATION_EXECUTION_RECEIPT_SCHEMA,
            module="execution_contracts",
            artifact_kind="mutation_execution_receipt",
        ),
        _artifact_entry(
            name="MutationOutcome",
            interface_id=execution.MUTATION_OUTCOME_INTERFACE,
            schema=execution.MUTATION_OUTCOME_SCHEMA,
            module="execution_contracts",
            artifact_kind="mutation_outcome",
        ),
        _artifact_entry(
            name="MutationEquivalenceAssessment",
            interface_id=execution.MUTATION_EQUIVALENCE_ASSESSMENT_INTERFACE,
            schema=execution.MUTATION_EQUIVALENCE_ASSESSMENT_SCHEMA,
            module="execution_contracts",
            artifact_kind="mutation_equivalence_assessment",
        ),
        _artifact_entry(
            name="SurvivingMutantReport",
            interface_id=analysis.SURVIVING_MUTANT_REPORT_INTERFACE,
            schema=analysis.SURVIVING_MUTANT_REPORT_SCHEMA,
            module="analysis_contracts",
            artifact_kind="surviving_mutant_report",
        ),
        _artifact_entry(
            name="AssuranceGap",
            interface_id=analysis.ASSURANCE_GAP_INTERFACE,
            schema=analysis.ASSURANCE_GAP_SCHEMA,
            module="analysis_contracts",
            artifact_kind="assurance_gap",
        ),
        _artifact_entry(
            name="VacuityFinding",
            interface_id=analysis.VACUITY_FINDING_INTERFACE,
            schema=analysis.VACUITY_FINDING_SCHEMA,
            module="analysis_contracts",
            artifact_kind="vacuity_finding",
        ),
        _artifact_entry(
            name="DetectionFailure",
            interface_id=analysis.DETECTION_FAILURE_INTERFACE,
            schema=analysis.DETECTION_FAILURE_SCHEMA,
            module="analysis_contracts",
            artifact_kind="detection_failure",
        ),
        _artifact_entry(
            name="TestAdequacyProfile",
            interface_id=analysis.TEST_ADEQUACY_PROFILE_INTERFACE,
            schema=analysis.TEST_ADEQUACY_PROFILE_SCHEMA,
            module="analysis_contracts",
            artifact_kind="test_adequacy_profile",
        ),
        _artifact_entry(
            name="ProofAdequacyProfile",
            interface_id=analysis.PROOF_ADEQUACY_PROFILE_INTERFACE,
            schema=analysis.PROOF_ADEQUACY_PROFILE_SCHEMA,
            module="analysis_contracts",
            artifact_kind="proof_adequacy_profile",
        ),
        _artifact_entry(
            name="PolicyAdequacyProfile",
            interface_id=analysis.POLICY_ADEQUACY_PROFILE_INTERFACE,
            schema=analysis.POLICY_ADEQUACY_PROFILE_SCHEMA,
            module="analysis_contracts",
            artifact_kind="policy_adequacy_profile",
        ),
        _artifact_entry(
            name="CapsuleAdequacyProfile",
            interface_id=analysis.CAPSULE_ADEQUACY_PROFILE_INTERFACE,
            schema=analysis.CAPSULE_ADEQUACY_PROFILE_SCHEMA,
            module="analysis_contracts",
            artifact_kind="capsule_adequacy_profile",
        ),
        _artifact_entry(
            name="CandidateTestSpecification",
            interface_id=remediation.CANDIDATE_TEST_SPECIFICATION_INTERFACE,
            schema=remediation.CANDIDATE_TEST_SPECIFICATION_SCHEMA,
            module="remediation_contracts",
            artifact_kind="candidate_test_specification",
        ),
        _artifact_entry(
            name="CandidateProofObligation",
            interface_id=remediation.CANDIDATE_PROOF_OBLIGATION_INTERFACE,
            schema=remediation.CANDIDATE_PROOF_OBLIGATION_SCHEMA,
            module="remediation_contracts",
            artifact_kind="candidate_proof_obligation",
        ),
        _artifact_entry(
            name="CandidatePolicyConstraint",
            interface_id=remediation.CANDIDATE_POLICY_CONSTRAINT_INTERFACE,
            schema=remediation.CANDIDATE_POLICY_CONSTRAINT_SCHEMA,
            module="remediation_contracts",
            artifact_kind="candidate_policy_constraint",
        ),
        _artifact_entry(
            name="CandidateAnalyzerRule",
            interface_id=remediation.CANDIDATE_ANALYZER_RULE_INTERFACE,
            schema=remediation.CANDIDATE_ANALYZER_RULE_SCHEMA,
            module="remediation_contracts",
            artifact_kind="candidate_analyzer_rule",
        ),
        _artifact_entry(
            name="GapRemediationPlan",
            interface_id=remediation.GAP_REMEDIATION_PLAN_INTERFACE,
            schema=remediation.GAP_REMEDIATION_PLAN_SCHEMA,
            module="remediation_contracts",
            artifact_kind="gap_remediation_plan",
        ),
        _artifact_entry(
            name="RemediationEvaluationReport",
            interface_id=remediation.REMEDIATION_EVALUATION_REPORT_INTERFACE,
            schema=remediation.REMEDIATION_EVALUATION_REPORT_SCHEMA,
            module="remediation_contracts",
            artifact_kind="remediation_evaluation_report",
        ),
        _artifact_entry(
            name="AssuranceCampaignReceipt",
            interface_id=ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE,
            schema=ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA,
            module="receipt_contracts",
            artifact_kind="assurance_campaign_receipt",
        ),
        _artifact_entry(
            name="AssurancePolicyPromotionReceipt",
            interface_id=ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE,
            schema=ASSURANCE_POLICY_PROMOTION_RECEIPT_SCHEMA,
            module="receipt_contracts",
            artifact_kind="assurance_policy_promotion_receipt",
        ),
        _artifact_entry(
            name="AdversarialAssuranceArtifacts",
            interface_id=ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE,
            schema=ADVERSARIAL_ASSURANCE_ARTIFACTS_SCHEMA,
            module="receipt_contracts",
        ),
    )
    ordered = tuple(
        sorted(
            (MappingProxyType(dict(item)) for item in entries),
            key=lambda row: str(row["interface_id"]),
        )
    )
    return ordered


@dataclass(frozen=True, slots=True)
class AdversarialAssuranceArtifacts:
    """Frozen package export catalog for datasets adversarial-assurance models.

    Interface: ``AdversarialAssuranceArtifacts@1``

    This is the sole datasets freeze of package exports and canonical schema
    identities for AAE contracts. Downstream kit/accelerate tasks consume this
    catalog without redefining identity, receipt, or signature authorities.
    """

    package: str = "ipfs_datasets_py.logic.software_contracts.adversarial_assurance"
    catalog_version: str = "1"
    signature_authority: str = EXISTING_SIGNATURE_AUTHORITY
    signature_algorithm: str = EXISTING_SIGNATURE_ALGORITHM
    content_authority: str = "ipfs_datasets_py.logic.software_contracts.content"
    schema_directory: str = (
        "ipfs_datasets_py/logic/software_contracts/adversarial_assurance/schemas"
    )
    artifacts: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "package",
            "catalog_version",
            "signature_authority",
            "signature_algorithm",
            "content_authority",
            "schema_directory",
            "artifacts",
            "catalog_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "package", _text(self.package, "package", maximum=512))
        object.__setattr__(
            self, "catalog_version", _version(self.catalog_version, "catalog_version")
        )
        if self.signature_authority != EXISTING_SIGNATURE_AUTHORITY:
            raise ReceiptContractError(
                "signature_authority must reuse the existing receipt/signature authority"
            )
        if self.signature_algorithm != EXISTING_SIGNATURE_ALGORITHM:
            raise ReceiptContractError(
                "signature_algorithm must reuse the existing EdDSA authority"
            )
        object.__setattr__(
            self,
            "content_authority",
            _text(self.content_authority, "content_authority", maximum=512),
        )
        object.__setattr__(
            self,
            "schema_directory",
            _text(self.schema_directory, "schema_directory", maximum=512),
        )
        if self.artifacts:
            if not isinstance(self.artifacts, (list, tuple)):
                raise ReceiptContractError("artifacts must be a list")
            sealed: list[Mapping[str, Any]] = []
            for index, item in enumerate(self.artifacts):
                if not isinstance(item, Mapping):
                    raise ReceiptContractError(
                        f"artifacts[{index}] must be a mapping"
                    )
                required = {"name", "interface_id", "schema", "module"}
                if not required.issubset(set(item)):
                    raise ReceiptContractError(
                        f"artifacts[{index}] missing required fields"
                    )
                allowed_keys = {
                    "name",
                    "interface_id",
                    "schema",
                    "module",
                    "artifact_kind",
                }
                extra = sorted(set(item) - allowed_keys)
                if extra:
                    raise ReceiptContractError(
                        f"artifacts[{index}] has unknown fields {extra}"
                    )
                entry = {
                    "name": _text(item["name"], f"artifacts[{index}].name", maximum=128),
                    "interface_id": _text(
                        item["interface_id"],
                        f"artifacts[{index}].interface_id",
                        maximum=128,
                    ),
                    "schema": _text(
                        item["schema"], f"artifacts[{index}].schema", maximum=256
                    ),
                    "module": _token(item["module"], f"artifacts[{index}].module"),
                }
                if "artifact_kind" in item and item["artifact_kind"] is not None:
                    entry["artifact_kind"] = _token(
                        item["artifact_kind"], f"artifacts[{index}].artifact_kind"
                    )
                sealed.append(MappingProxyType(entry))
            # Stable order by interface_id.
            sealed_sorted = tuple(
                sorted(sealed, key=lambda row: str(row["interface_id"]))
            )
            names = [row["name"] for row in sealed_sorted]
            if len(names) != len(set(names)):
                raise ReceiptContractError("artifact catalog names must be unique")
            object.__setattr__(self, "artifacts", sealed_sorted)
        else:
            object.__setattr__(
                self, "artifacts", adversarial_assurance_artifact_catalog()
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ADVERSARIAL_ASSURANCE_ARTIFACTS_SCHEMA,
            "interface_id": ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE,
            "package": self.package,
            "catalog_version": self.catalog_version,
            "signature_authority": self.signature_authority,
            "signature_algorithm": self.signature_algorithm,
            "content_authority": self.content_authority,
            "schema_directory": self.schema_directory,
            "artifacts": [dict(item) for item in self.artifacts],
        }

    @property
    def catalog_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["catalog_cid"] = self.catalog_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdversarialAssuranceArtifacts":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("catalog_cid")
        if payload.pop("schema") != ADVERSARIAL_ASSURANCE_ARTIFACTS_SCHEMA:
            raise ReceiptContractError(
                "unsupported AdversarialAssuranceArtifacts schema version"
            )
        if payload.pop("interface_id") != ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE:
            raise ReceiptContractError(
                "unsupported AdversarialAssuranceArtifacts interface_id"
            )
        result = cls(
            package=payload["package"],
            catalog_version=payload["catalog_version"],
            signature_authority=payload["signature_authority"],
            signature_algorithm=payload["signature_algorithm"],
            content_authority=payload["content_authority"],
            schema_directory=payload["schema_directory"],
            artifacts=payload["artifacts"],
        )
        if claimed != result.catalog_cid:
            raise ReceiptContractError(
                "AdversarialAssuranceArtifacts catalog_cid identity mismatch"
            )
        return result

    @classmethod
    def freeze_default(cls) -> "AdversarialAssuranceArtifacts":
        """Return the sole frozen default package export catalog."""

        return cls()


# ---------------------------------------------------------------------------
# Vocabulary / identity helpers
# ---------------------------------------------------------------------------


def signature_verification_statuses() -> tuple[str, ...]:
    return tuple(item.value for item in SignatureVerificationStatus)


def held_out_results() -> tuple[str, ...]:
    return tuple(item.value for item in HeldOutResult)


def seal_availability_statuses() -> tuple[str, ...]:
    return tuple(item.value for item in SealAvailabilityStatus)


def seal_scope_items() -> tuple[str, ...]:
    return tuple(item.value for item in SealScopeItem)


def receipt_actions() -> tuple[str, ...]:
    return tuple(item.value for item in ReceiptAction)


def verify_campaign_receipt_identity(
    receipt: AssuranceCampaignReceipt | Mapping[str, Any],
) -> str:
    """Recompute and return the campaign receipt CID; require verified signature when complete."""

    if isinstance(receipt, AssuranceCampaignReceipt):
        sealed = receipt
    elif isinstance(receipt, Mapping):
        sealed = AssuranceCampaignReceipt.from_dict(receipt)
    else:
        raise ReceiptContractError(
            "receipt must be AssuranceCampaignReceipt or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.receipt_cid:
        raise ReceiptContractError(
            "receipt_cid identity mismatch with recomputed identity"
        )
    if (
        sealed.header.terminal_status == AssuranceTerminalStatus.COMPLETE.value
        and sealed.signature.signature_verification_status
        != SignatureVerificationStatus.VERIFIED.value
    ):
        raise ReceiptContractError(
            "complete campaign receipt requires verified signature status"
        )
    return recomputed


def verify_promotion_receipt_identity(
    receipt: AssurancePolicyPromotionReceipt | Mapping[str, Any],
) -> str:
    """Recompute and return the promotion receipt CID; reject self-authorization."""

    if isinstance(receipt, AssurancePolicyPromotionReceipt):
        sealed = receipt
    elif isinstance(receipt, Mapping):
        sealed = AssurancePolicyPromotionReceipt.from_dict(receipt)
    else:
        raise ReceiptContractError(
            "receipt must be AssurancePolicyPromotionReceipt or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.receipt_cid:
        raise ReceiptContractError(
            "receipt_cid identity mismatch with recomputed identity"
        )
    if sealed.authorization_cid in {
        sealed.candidate_cid,
        sealed.evaluation_report_cid,
        sealed.promoted_policy_cid,
        sealed.receipt_cid,
    }:
        raise ReceiptContractError(
            "promotion authorization_cid collides with self-referential evidence"
        )
    return recomputed


def require_verified_signature_before_persistence(
    receipt: AssuranceCampaignReceipt | AssurancePolicyPromotionReceipt | Mapping[str, Any],
) -> str:
    """Gate durable use: verified signature required before first persistence.

    Returns the receipt CID when the sealed record is admissible. Unverified,
    invalid, unavailable, or rejected signatures fail closed.
    """

    if isinstance(receipt, Mapping):
        schema = receipt.get("schema")
        if schema == ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA:
            sealed: AssuranceCampaignReceipt | AssurancePolicyPromotionReceipt = (
                AssuranceCampaignReceipt.from_dict(receipt)
            )
        elif schema == ASSURANCE_POLICY_PROMOTION_RECEIPT_SCHEMA:
            sealed = AssurancePolicyPromotionReceipt.from_dict(receipt)
        else:
            raise ReceiptContractError(
                "receipt mapping must declare a known campaign/promotion schema"
            )
    elif isinstance(receipt, (AssuranceCampaignReceipt, AssurancePolicyPromotionReceipt)):
        sealed = receipt
    else:
        raise ReceiptContractError("receipt type is not admitted")

    status = sealed.signature.signature_verification_status
    if status != SignatureVerificationStatus.VERIFIED.value:
        raise ReceiptContractError(
            "signature verification must pass before durable write, content "
            "addressing, Merkle inclusion, sealing, or authorization "
            f"(status={status!r})"
        )
    if not sealed.signature.signature:
        raise ReceiptContractError(
            "verified signature requires nonempty signature bytes"
        )
    return sealed.receipt_cid


__all__ = [
    "ADVERSARIAL_ASSURANCE_ARTIFACTS_INTERFACE",
    "ADVERSARIAL_ASSURANCE_ARTIFACTS_SCHEMA",
    "ASSURANCE_CAMPAIGN_RECEIPT_INTERFACE",
    "ASSURANCE_CAMPAIGN_RECEIPT_SCHEMA",
    "ASSURANCE_POLICY_PROMOTION_RECEIPT_INTERFACE",
    "ASSURANCE_POLICY_PROMOTION_RECEIPT_SCHEMA",
    "EXISTING_SIGNATURE_ALGORITHM",
    "EXISTING_SIGNATURE_AUTHORITY",
    "RECEIPT_SIGNATURE_BINDING_SCHEMA",
    "AdversarialAssuranceArtifacts",
    "AssuranceCampaignReceipt",
    "AssurancePolicyPromotionReceipt",
    "HeldOutResult",
    "ReceiptAction",
    "ReceiptContractError",
    "ReceiptSignatureBinding",
    "SealAvailabilityStatus",
    "SealScopeItem",
    "SignatureVerificationStatus",
    "adversarial_assurance_artifact_catalog",
    "held_out_results",
    "receipt_actions",
    "require_verified_signature_before_persistence",
    "seal_availability_statuses",
    "seal_scope_items",
    "signature_verification_statuses",
    "verify_campaign_receipt_identity",
    "verify_promotion_receipt_identity",
]
