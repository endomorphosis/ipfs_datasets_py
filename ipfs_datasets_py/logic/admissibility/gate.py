"""Composite Intent admissibility gate (IntentAdmissibilityGate@1 / LIG-015).

Given a pre-built Intent formal artifact (content CID or artifact object) and an
admissibility profile, the gate queries attested Legal and Security constraints
from a :class:`ProofCorpusStore` via :class:`ProofCorpusQuery` and returns a
structured :class:`AdmissibilityDecision`.

Disposition (plan §2.4, fail closed):

* **allow** — every Intent obligation has an applicable positive grant, required
  families are covered under the profile, integrity holds, and optional ZKP
  requirements pass.  Never allows without constraints.
* **reject** — a hard Legal/Security constraint forbids the intent, constraints
  contradict, integrity fails, or the profile/intent is invalid.
* **abstain** — evidence incomplete, semantics unsupported, or ZKP missing /
  failed when required.  Abstain never promotes to allow.

Join logic is free of SkillCenter I/O and consumes the proof corpus only through
its public query/attest APIs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ..formalization.compiler import FormalizationArtifact
from ..proof_corpus.attest import (
    AttestationStatus,
    AttestationVerifyResult,
    verify_attestation,
)
from ..proof_corpus.index import normalize_obligation_digest
from ..proof_corpus.query import ProofCorpusQuery, ProofCorpusQueryError
from ..proof_corpus.schemas import (
    ArtifactEnvelope,
    ProofCorpusFamily,
    ProofCorpusIntegrityError,
    ProofCorpusSchemaError,
)
from ..proof_corpus.store import ProofCorpusStore, ProofCorpusStoreError
from .profiles import (
    AdmissibilityProfile,
    AdmissibilityProfileId,
    resolve_profile_fail_closed,
)
from .reasons import (
    AdmissibilityReason,
    AdmissibilityReasonCode,
    AdmissibilityStatus,
    default_status_for_reason,
    invalid_profile_reason,
)


ADMISSIBILITY_GATE_INTERFACE: Final = "IntentAdmissibilityGate@1"
ADMISSIBILITY_GATE_SCHEMA_VERSION: Final = "intent-admissibility-gate/v1"
ADMISSIBILITY_DECISION_INTERFACE: Final = "AdmissibilityDecision@1"
ADMISSIBILITY_DECISION_SCHEMA_VERSION: Final = "admissibility-decision/v1"

# Closed markers used to classify constraint formulas (case-normalized).
_FORBID_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "deny",
        "denied",
        "f",
        "forbid",
        "forbidden",
        "hard_forbid",
        "legal_hard_constraint",
        "negative",
        "prohibit",
        "prohibition",
        "security_hard_constraint",
    }
)
_GRANT_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "allow",
        "allowed",
        "grant",
        "p",
        "permission",
        "permit",
        "positive",
        "support",
        "supported",
    }
)

_UNSUPPORTED_DIAG_CODES: Final[frozenset[str]] = frozenset(
    {
        "ir.feature.unsupported",
        "semantics_unsupported",
        "unsupported",
        "unsupported_feature",
    }
)

# Severity rank for multi-reason join (higher wins).
_STATUS_RANK: Final[dict[AdmissibilityStatus, int]] = {
    AdmissibilityStatus.REJECT: 3,
    AdmissibilityStatus.ABSTAIN: 2,
    AdmissibilityStatus.ALLOW: 1,
}


class AdmissibilityGateError(ValueError):
    """Raised when the gate cannot evaluate without guessing (fail closed)."""


class ConstraintPolarity(str, Enum):
    """Normalized polarity of one constraint envelope relative to an intent."""

    GRANT = "grant"
    FORBID = "forbid"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class AdmissibilityDecision:
    """Structured wire result of one gate evaluation (AdmissibilityDecision@1).

    Acceptance fields (LIG-G060): ``status``, ``reasons``, ``intent_cid``,
    ``constraint_cids``, ``attestation_results``, ``profile_id``,
    ``config_digest``.
    """

    status: AdmissibilityStatus
    reasons: tuple[AdmissibilityReason, ...]
    intent_cid: str
    constraint_cids: tuple[str, ...]
    attestation_results: tuple[AttestationVerifyResult, ...]
    profile_id: str
    config_digest: str
    intent_artifact_cid: str = ""
    store_snapshot_digest: str = ""
    interface: str = ADMISSIBILITY_DECISION_INTERFACE
    schema_version: str = ADMISSIBILITY_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, AdmissibilityStatus):
            object.__setattr__(
                self, "status", AdmissibilityStatus(str(self.status))
            )
        if not isinstance(self.reasons, tuple):
            object.__setattr__(self, "reasons", tuple(self.reasons))
        for reason in self.reasons:
            if not isinstance(reason, AdmissibilityReason):
                raise AdmissibilityGateError(
                    "decision reasons must be AdmissibilityReason instances"
                )
        if not isinstance(self.constraint_cids, tuple):
            object.__setattr__(
                self, "constraint_cids", tuple(self.constraint_cids)
            )
        if list(self.constraint_cids) != sorted(self.constraint_cids):
            object.__setattr__(
                self,
                "constraint_cids",
                tuple(sorted(self.constraint_cids)),
            )
        if not isinstance(self.attestation_results, tuple):
            object.__setattr__(
                self, "attestation_results", tuple(self.attestation_results)
            )
        if not isinstance(self.intent_cid, str):
            raise AdmissibilityGateError("intent_cid must be a string")
        if not isinstance(self.profile_id, str):
            raise AdmissibilityGateError("profile_id must be a string")
        if not isinstance(self.config_digest, str):
            raise AdmissibilityGateError("config_digest must be a string")
        if self.interface != ADMISSIBILITY_DECISION_INTERFACE:
            raise AdmissibilityGateError(
                f"unsupported decision interface: {self.interface!r}"
            )
        if self.schema_version != ADMISSIBILITY_DECISION_SCHEMA_VERSION:
            raise AdmissibilityGateError(
                f"unsupported decision schema: {self.schema_version!r}"
            )

    @property
    def is_allow(self) -> bool:
        return self.status is AdmissibilityStatus.ALLOW

    @property
    def is_reject(self) -> bool:
        return self.status is AdmissibilityStatus.REJECT

    @property
    def is_abstain(self) -> bool:
        return self.status is AdmissibilityStatus.ABSTAIN

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Stable wire codes of all bound reasons."""

        return tuple(reason.code.value for reason in self.reasons)

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-serializable decision map."""

        return {
            "attestation_results": [
                result.to_dict() for result in self.attestation_results
            ],
            "config_digest": self.config_digest,
            "constraint_cids": list(self.constraint_cids),
            "intent_artifact_cid": self.intent_artifact_cid,
            "intent_cid": self.intent_cid,
            "interface": self.interface,
            "profile_id": self.profile_id,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "schema_version": self.schema_version,
            "status": self.status.value,
            "store_snapshot_digest": self.store_snapshot_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdmissibilityDecision":
        """Reconstruct a decision from a mapping (fail closed on unknown status)."""

        if not isinstance(value, Mapping):
            raise AdmissibilityGateError("decision payload must be a mapping")
        status_raw = value.get("status")
        try:
            status = AdmissibilityStatus(str(status_raw))
        except ValueError as exc:
            raise AdmissibilityGateError(
                f"unknown decision status {status_raw!r}; fail closed"
            ) from exc
        reasons_raw = value.get("reasons", ())
        if not isinstance(reasons_raw, Sequence) or isinstance(
            reasons_raw, (str, bytes, bytearray)
        ):
            raise AdmissibilityGateError("reasons must be a sequence")
        reasons = tuple(
            item
            if isinstance(item, AdmissibilityReason)
            else AdmissibilityReason.from_dict(item)
            for item in reasons_raw
        )
        attest_raw = value.get("attestation_results", ())
        if not isinstance(attest_raw, Sequence) or isinstance(
            attest_raw, (str, bytes, bytearray)
        ):
            raise AdmissibilityGateError(
                "attestation_results must be a sequence"
            )
        attestations = tuple(
            item
            if isinstance(item, AttestationVerifyResult)
            else AttestationVerifyResult.from_dict(item)
            for item in attest_raw
        )
        cids_raw = value.get("constraint_cids", ())
        if not isinstance(cids_raw, Sequence) or isinstance(
            cids_raw, (str, bytes, bytearray)
        ):
            raise AdmissibilityGateError("constraint_cids must be a sequence")
        return cls(
            status=status,
            reasons=reasons,
            intent_cid=str(value.get("intent_cid", "") or ""),
            constraint_cids=tuple(str(cid) for cid in cids_raw),
            attestation_results=attestations,
            profile_id=str(value.get("profile_id", "") or ""),
            config_digest=str(value.get("config_digest", "") or ""),
            intent_artifact_cid=str(
                value.get("intent_artifact_cid", "") or ""
            ),
            store_snapshot_digest=str(
                value.get("store_snapshot_digest", "") or ""
            ),
            interface=str(
                value.get("interface", ADMISSIBILITY_DECISION_INTERFACE)
            ),
            schema_version=str(
                value.get(
                    "schema_version", ADMISSIBILITY_DECISION_SCHEMA_VERSION
                )
            ),
        )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_snapshot_digest(store: ProofCorpusStore) -> str:
    """Return a deterministic digest of all content CIDs currently in *store*."""

    try:
        query = ProofCorpusQuery(store=store)
        envelopes = query.list_all()
    except (ProofCorpusQueryError, ProofCorpusStoreError, ProofCorpusSchemaError):
        # Empty or unreadable store still yields a stable empty digest.
        envelopes = ()
    payload = {
        "content_cids": sorted(env.content_cid for env in envelopes),
        "interface": ADMISSIBILITY_GATE_INTERFACE,
    }
    return "sha256:" + _sha256_hex(_canonical_json_bytes(payload))


def _normalize_marker(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _markers_from_mapping(payload: Mapping[str, Any]) -> set[str]:
    markers: set[str] = set()
    for key in (
        "role",
        "constraint_role",
        "gate_role",
        "norm_type",
        "polarity",
        "operator",
        "disposition",
        "decision",
        "modality",
        "kind",
    ):
        if key in payload:
            markers.add(_normalize_marker(payload.get(key)))
    # Nested deontic operator labels (legal IR).
    operator = payload.get("operator")
    if isinstance(operator, Mapping):
        for key in ("symbol", "label", "family"):
            markers.add(_normalize_marker(operator.get(key)))
    return {marker for marker in markers if marker}


def classify_constraint_polarity(
    envelope: ArtifactEnvelope | Mapping[str, Any],
) -> ConstraintPolarity:
    """Classify a constraint envelope as grant, forbid, or neutral.

    Inspects formula expressions and artifact metadata for closed polarity
    markers.  Unknown shapes default to neutral (never guessed as allow).
    """

    if isinstance(envelope, ArtifactEnvelope):
        env = envelope
    else:
        env = ArtifactEnvelope.from_dict(envelope)

    markers: set[str] = set()
    try:
        artifact = env.formalization_artifact()
    except ProofCorpusIntegrityError:
        return ConstraintPolarity.NEUTRAL

    meta = artifact.metadata.to_dict() if hasattr(artifact.metadata, "to_dict") else {}
    if isinstance(meta, Mapping):
        markers |= _markers_from_mapping(meta)

    for formula in artifact.formulas:
        expr = formula.expression
        if isinstance(expr, Mapping):
            markers |= _markers_from_mapping(expr)
            body = expr.get("body")
            if isinstance(body, Mapping):
                markers |= _markers_from_mapping(body)
        fmeta = formula.metadata
        if hasattr(fmeta, "to_dict"):
            fmeta = fmeta.to_dict()
        if isinstance(fmeta, Mapping):
            markers |= _markers_from_mapping(fmeta)

    if markers & _FORBID_MARKERS:
        # Forbid wins over grant when both appear (contradiction is handled
        # separately when grants also exist for the same obligation).
        if markers & _GRANT_MARKERS:
            return ConstraintPolarity.FORBID
        return ConstraintPolarity.FORBID
    if markers & _GRANT_MARKERS:
        return ConstraintPolarity.GRANT
    return ConstraintPolarity.NEUTRAL


def intent_has_unsupported_semantics(artifact: FormalizationArtifact) -> bool:
    """Return True when the Intent formalization is semantically incomplete."""

    if any(formula.opaque for formula in artifact.formulas):
        return True
    diagnostics = getattr(artifact.diagnostics, "diagnostics", ()) or ()
    for diagnostic in diagnostics:
        code = getattr(diagnostic, "code", diagnostic)
        code_value = getattr(code, "value", code)
        if _normalize_marker(str(code_value)) in {
            _normalize_marker(item) for item in _UNSUPPORTED_DIAG_CODES
        }:
            return True
        if "unsupported" in _normalize_marker(str(code_value)):
            return True
    return False


def _sort_reasons(
    reasons: Sequence[AdmissibilityReason],
) -> tuple[AdmissibilityReason, ...]:
    """Stable reason order: status severity desc, then code wire value, message."""

    return tuple(
        sorted(
            reasons,
            key=lambda reason: (
                -_STATUS_RANK[default_status_for_reason(reason.code)],
                reason.code.value,
                reason.message,
            ),
        )
    )


def _join_status(
    reasons: Sequence[AdmissibilityReason],
) -> AdmissibilityStatus:
    """Join multiple reason defaults: reject > abstain > allow; empty → reject."""

    if not reasons:
        return AdmissibilityStatus.REJECT
    best = AdmissibilityStatus.ALLOW
    best_rank = 0
    for reason in reasons:
        status = default_status_for_reason(reason.code)
        rank = _STATUS_RANK[status]
        if rank > best_rank:
            best = status
            best_rank = rank
    return best


def _reason(
    code: AdmissibilityReasonCode,
    message: str,
    *,
    detail: Mapping[str, Any] | None = None,
) -> AdmissibilityReason:
    return AdmissibilityReason(code=code, message=message, detail=detail)


@dataclass
class IntentAdmissibilityGate:
    """IntentAdmissibilityGate@1 — fail-closed composite admissibility join.

    Construct with a :class:`ProofCorpusStore`.  An optional prebuilt
    :class:`ProofCorpusQuery` may be supplied; otherwise one is created and
    its index is rebuilt from the store on first use.
    """

    store: ProofCorpusStore
    query: ProofCorpusQuery | None = None
    _query: ProofCorpusQuery | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.store, ProofCorpusStore):
            raise AdmissibilityGateError("store must be a ProofCorpusStore")
        if self.query is not None and not isinstance(
            self.query, ProofCorpusQuery
        ):
            raise AdmissibilityGateError(
                "query must be a ProofCorpusQuery when provided"
            )

    @property
    def interface(self) -> str:
        return ADMISSIBILITY_GATE_INTERFACE

    @property
    def schema_version(self) -> str:
        return ADMISSIBILITY_GATE_SCHEMA_VERSION

    def _active_query(self) -> ProofCorpusQuery:
        if self.query is not None:
            return self.query
        if self._query is None:
            self._query = ProofCorpusQuery(store=self.store)
            self._query.rebuild_index()
        return self._query

    def rebuild_index(self) -> ProofCorpusQuery:
        """Rebuild the query index from the current store snapshot."""

        active = self._active_query()
        active.rebuild_index()
        return active

    def _decision(
        self,
        *,
        status: AdmissibilityStatus,
        reasons: Sequence[AdmissibilityReason],
        intent_cid: str,
        constraint_cids: Sequence[str],
        attestation_results: Sequence[AttestationVerifyResult],
        profile: AdmissibilityProfile | None,
        intent_artifact_cid: str = "",
    ) -> AdmissibilityDecision:
        ordered = _sort_reasons(reasons)
        # Join status from reasons unless caller forced a stricter status.
        joined = _join_status(ordered) if ordered else status
        if _STATUS_RANK[joined] > _STATUS_RANK[status]:
            status = joined
        # Fail closed: allow only when an explicit allow reason is present and
        # no higher-severity reason joined above.
        if status is AdmissibilityStatus.ALLOW:
            if not any(
                reason.code is AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED
                for reason in ordered
            ):
                status = AdmissibilityStatus.REJECT
                if not ordered:
                    ordered = (
                        _reason(
                            AdmissibilityReasonCode.NO_CONSTRAINTS,
                            "no supporting reasons for allow; fail closed",
                        ),
                    )
        profile_id = profile.id if profile is not None else ""
        config_digest = profile.config_digest() if profile is not None else ""
        return AdmissibilityDecision(
            status=status,
            reasons=ordered,
            intent_cid=intent_cid,
            constraint_cids=tuple(sorted(set(constraint_cids))),
            attestation_results=tuple(attestation_results),
            profile_id=profile_id,
            config_digest=config_digest,
            intent_artifact_cid=intent_artifact_cid,
            store_snapshot_digest=store_snapshot_digest(self.store),
        )

    def _resolve_intent(
        self,
        intent: str
        | ArtifactEnvelope
        | FormalizationArtifact
        | Mapping[str, Any],
        *,
        profile: AdmissibilityProfile,
    ) -> tuple[ArtifactEnvelope | None, FormalizationArtifact | None, list[AdmissibilityReason]]:
        """Load and verify the Intent formal envelope.

        Returns ``(envelope, artifact, reasons)``.  On hard failure envelope
        and/or artifact may be ``None`` with reject reasons populated.
        """

        reasons: list[AdmissibilityReason] = []

        if isinstance(intent, str):
            cid = intent.strip()
            if not cid:
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.INVALID_INTENT,
                        "intent content CID is empty; fail closed",
                    )
                )
                return None, None, reasons
            try:
                envelope = self.store.get(cid)
            except ProofCorpusStoreError:
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.INVALID_INTENT,
                        "intent formal artifact CID not found in proof corpus",
                        detail={"content_cid": cid},
                    )
                )
                return None, None, reasons
            except ProofCorpusIntegrityError as exc:
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.INTEGRITY_FAILURE,
                        "intent envelope failed integrity verification",
                        detail={"error": str(exc), "content_cid": cid},
                    )
                )
                return None, None, reasons
        elif isinstance(intent, ArtifactEnvelope):
            try:
                envelope = intent.verify_integrity()
            except (
                ProofCorpusIntegrityError,
                ProofCorpusSchemaError,
            ) as exc:
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.INTEGRITY_FAILURE,
                        "intent envelope failed integrity verification",
                        detail={"error": str(exc)},
                    )
                )
                return None, None, reasons
        elif isinstance(intent, FormalizationArtifact):
            try:
                envelope = ArtifactEnvelope.from_intent_artifact(
                    intent, profile=profile.id
                )
            except (ProofCorpusSchemaError, ProofCorpusIntegrityError) as exc:
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.INVALID_INTENT,
                        "intent formalization artifact cannot form an envelope",
                        detail={"error": str(exc)},
                    )
                )
                return None, None, reasons
        elif isinstance(intent, Mapping):
            try:
                if "family" in intent or "content_cid" in intent:
                    envelope = ArtifactEnvelope.from_dict(intent).verify_integrity()
                else:
                    artifact = FormalizationArtifact.from_dict(intent)
                    envelope = ArtifactEnvelope.from_intent_artifact(
                        artifact, profile=profile.id
                    )
            except (
                ProofCorpusSchemaError,
                ProofCorpusIntegrityError,
                TypeError,
                ValueError,
            ) as exc:
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.INVALID_INTENT,
                        "intent payload is not a valid formal artifact/envelope",
                        detail={"error": str(exc)},
                    )
                )
                return None, None, reasons
        else:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.INVALID_INTENT,
                    "intent must be a content CID, envelope, or formalization artifact",
                    detail={"type": type(intent).__name__},
                )
            )
            return None, None, reasons

        if envelope.family is not ProofCorpusFamily.INTENT:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.INVALID_INTENT,
                    "admissibility gate requires an Intent-family formal artifact",
                    detail={
                        "family": envelope.family.value,
                        "content_cid": envelope.content_cid,
                    },
                )
            )
            return envelope, None, reasons

        try:
            artifact = envelope.formalization_artifact()
        except ProofCorpusIntegrityError as exc:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.INTEGRITY_FAILURE,
                    "stored intent artifact failed revalidation",
                    detail={
                        "error": str(exc),
                        "content_cid": envelope.content_cid,
                    },
                )
            )
            return envelope, None, reasons

        return envelope, artifact, reasons

    def _verify_constraint_zkp(
        self,
        envelope: ArtifactEnvelope,
        profile: AdmissibilityProfile,
    ) -> AttestationVerifyResult:
        """Verify ZKP attestation for one constraint envelope under *profile*."""

        # Attestations bind to the constraint envelope's stored profile; the
        # gate profile only supplies require_zkp_verify / accept_simulated_zkp.
        return verify_attestation(
            self.store,
            envelope.content_cid,
            envelope.profile,
            require_zkp_verify=profile.require_zkp_verify,
            accept_simulated_zkp=profile.accept_simulated_zkp,
        )

    def evaluate(
        self,
        intent: str
        | ArtifactEnvelope
        | FormalizationArtifact
        | Mapping[str, Any],
        profile: AdmissibilityProfile
        | AdmissibilityProfileId
        | str
        | None = None,
    ) -> AdmissibilityDecision:
        """Evaluate admissibility for *intent* under *profile*.

        Parameters
        ----------
        intent:
            Intent formal content CID, envelope, FormalizationArtifact, or
            mapping payload of either envelope or artifact shape.
        profile:
            Profile id / object, or ``None`` for the default ``legal-strict``.

        Returns
        -------
        AdmissibilityDecision
            Structured allow / reject / abstain with closed reason codes and
            bound constraint CIDs.  Never raises for policy outcomes; malformed
            store access is reflected as reject/abstain reasons.
        """

        resolution = resolve_profile_fail_closed(profile)
        if not resolution.ok or resolution.profile is None:
            reasons = list(resolution.reasons) or [
                invalid_profile_reason(profile)
            ]
            return self._decision(
                status=AdmissibilityStatus.REJECT,
                reasons=reasons,
                intent_cid="",
                constraint_cids=(),
                attestation_results=(),
                profile=None,
            )

        policy = resolution.profile
        envelope, artifact, early_reasons = self._resolve_intent(
            intent, profile=policy
        )
        if artifact is None:
            intent_cid = envelope.content_cid if envelope is not None else ""
            artifact_cid = (
                envelope.artifact_cid if envelope is not None else ""
            )
            # Prefer integrity/invalid over empty allow.
            status = _join_status(early_reasons) if early_reasons else (
                AdmissibilityStatus.REJECT
            )
            return self._decision(
                status=status,
                reasons=early_reasons
                or [
                    _reason(
                        AdmissibilityReasonCode.INVALID_INTENT,
                        "intent formalization could not be resolved; fail closed",
                    )
                ],
                intent_cid=intent_cid,
                constraint_cids=(),
                attestation_results=(),
                profile=policy,
                intent_artifact_cid=artifact_cid,
            )

        assert envelope is not None
        intent_cid = envelope.content_cid
        artifact_cid = envelope.artifact_cid
        reasons: list[AdmissibilityReason] = list(early_reasons)
        constraint_cids: set[str] = set()
        attestation_results: list[AttestationVerifyResult] = []

        unsupported = intent_has_unsupported_semantics(artifact)
        if unsupported:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.SEMANTICS_UNSUPPORTED,
                    "intent formalization retains unsupported or opaque semantics",
                    detail={"intent_cid": intent_cid},
                )
            )

        obligations = artifact.proof_obligations
        obligation_digests = [
            normalize_obligation_digest(obligation.digest)
            for obligation in obligations
        ]

        query = self._active_query()
        legal_grants = 0
        security_grants = 0
        legal_forbids = 0
        security_forbids = 0
        grants_for_obligation = 0
        forbids_for_obligation = 0
        obligations_with_grant = 0
        obligations_missing = 0
        constraints_seen = 0

        if not obligation_digests:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.MISSING_EVIDENCE,
                    "intent formalization declares no proof obligations",
                    detail={"intent_cid": intent_cid},
                )
            )
        else:
            for digest in obligation_digests:
                try:
                    matched = query.list_constraints_for_obligation(digest)
                except (
                    ProofCorpusQueryError,
                    ProofCorpusStoreError,
                    ProofCorpusIntegrityError,
                ) as exc:
                    reasons.append(
                        _reason(
                            AdmissibilityReasonCode.CORPUS_UNAVAILABLE,
                            "proof corpus query failed during obligation join",
                            detail={"error": str(exc), "obligation_digest": digest},
                        )
                    )
                    continue

                if not matched:
                    obligations_missing += 1
                    continue

                local_grants = 0
                local_forbids = 0
                for constraint in matched:
                    constraints_seen += 1
                    constraint_cids.add(constraint.content_cid)
                    polarity = classify_constraint_polarity(constraint)
                    family = constraint.family

                    if polarity is ConstraintPolarity.FORBID:
                        local_forbids += 1
                        forbids_for_obligation += 1
                        if family is ProofCorpusFamily.LEGAL:
                            legal_forbids += 1
                        elif family is ProofCorpusFamily.SECURITY:
                            security_forbids += 1
                    elif polarity is ConstraintPolarity.GRANT:
                        local_grants += 1
                        grants_for_obligation += 1
                        if family is ProofCorpusFamily.LEGAL:
                            legal_grants += 1
                        elif family is ProofCorpusFamily.SECURITY:
                            security_grants += 1

                    if (
                        policy.require_zkp_verify
                        and family is ProofCorpusFamily.LEGAL
                    ):
                        attestation_results.append(
                            self._verify_constraint_zkp(constraint, policy)
                        )

                if local_grants and local_forbids:
                    reasons.append(
                        _reason(
                            AdmissibilityReasonCode.CONSTRAINT_CONTRADICTION,
                            "grant and hard forbid constraints both apply to one obligation",
                            detail={"obligation_digest": digest},
                        )
                    )
                if local_grants:
                    obligations_with_grant += 1

        if legal_forbids:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.LEGAL_HARD_CONSTRAINT,
                    "attested Legal constraint forbids an Intent effect or action",
                    detail={"forbid_count": legal_forbids},
                )
            )
        if security_forbids:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.SECURITY_HARD_CONSTRAINT,
                    "attested Security constraint forbids an Intent effect or action",
                    detail={"forbid_count": security_forbids},
                )
            )

        # Family coverage under profile knobs.
        if obligation_digests and constraints_seen == 0 and not unsupported:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.NO_CONSTRAINTS,
                    "no Legal/Security constraints bound to Intent obligations; fail closed",
                    detail={"intent_cid": intent_cid},
                )
            )
        else:
            if (
                policy.require_legal_constraints
                and legal_grants == 0
                and legal_forbids == 0
                and obligation_digests
                and not unsupported
            ):
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.MISSING_EVIDENCE,
                        "profile requires attested Legal constraints; none granted",
                        detail={"profile_id": policy.id},
                    )
                )
            if (
                policy.require_security_constraints
                and security_grants == 0
                and security_forbids == 0
                and obligation_digests
                and not unsupported
            ):
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.MISSING_EVIDENCE,
                        "profile requires attested Security constraints; none granted",
                        detail={"profile_id": policy.id},
                    )
                )
            if obligations_missing and obligation_digests and not unsupported:
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.MISSING_EVIDENCE,
                        "one or more Intent obligations lack applicable constraints",
                        detail={
                            "missing_obligation_count": obligations_missing,
                            "obligation_count": len(obligation_digests),
                        },
                    )
                )

        # ZKP profile checks.
        if policy.require_zkp_verify:
            if not attestation_results and legal_grants == 0 and legal_forbids == 0:
                # No legal envelopes to attest — treat as missing ZKP evidence.
                reasons.append(
                    _reason(
                        AdmissibilityReasonCode.ZKP_MISSING,
                        "zkp-required profile has no Legal attestations to verify",
                        detail={"profile_id": policy.id},
                    )
                )
            for result in attestation_results:
                if result.status is AttestationStatus.ABSENT:
                    reasons.append(
                        _reason(
                            AdmissibilityReasonCode.ZKP_MISSING,
                            "required ZKP attestation is absent",
                            detail={
                                "content_cid": result.content_cid,
                                "profile_id": policy.id,
                            },
                        )
                    )
                elif result.status is AttestationStatus.FAIL:
                    reasons.append(
                        _reason(
                            AdmissibilityReasonCode.ZKP_VERIFY_FAILED,
                            "required ZKP attestation failed verification",
                            detail={
                                "content_cid": result.content_cid,
                                "reason": result.reason,
                                "is_simulated": result.is_simulated,
                            },
                        )
                    )

        # Positive allow path: full support, no blocking reasons.
        blocking_codes = {
            reason.code
            for reason in reasons
            if default_status_for_reason(reason.code)
            is not AdmissibilityStatus.ALLOW
        }
        full_grant_coverage = (
            bool(obligation_digests)
            and obligations_with_grant == len(obligation_digests)
            and (not policy.require_legal_constraints or legal_grants > 0)
            and (
                not policy.require_security_constraints or security_grants > 0
            )
            and forbids_for_obligation == 0
        )
        if full_grant_coverage and not blocking_codes and not unsupported:
            reasons.append(
                _reason(
                    AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED,
                    "all Intent obligations have applicable positive grants under the profile",
                    detail={
                        "obligation_count": len(obligation_digests),
                        "legal_grants": legal_grants,
                        "security_grants": security_grants,
                        "constraint_count": len(constraint_cids),
                    },
                )
            )

        # Deduplicate reasons by code+message while preserving join info.
        deduped: list[AdmissibilityReason] = []
        seen_keys: set[tuple[str, str]] = set()
        for reason in reasons:
            key = (reason.code.value, reason.message)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(reason)

        status = _join_status(deduped)
        return self._decision(
            status=status,
            reasons=deduped,
            intent_cid=intent_cid,
            constraint_cids=sorted(constraint_cids),
            attestation_results=attestation_results,
            profile=policy,
            intent_artifact_cid=artifact_cid,
        )


def evaluate_admissibility(
    store: ProofCorpusStore,
    intent: str
    | ArtifactEnvelope
    | FormalizationArtifact
    | Mapping[str, Any],
    profile: AdmissibilityProfile
    | AdmissibilityProfileId
    | str
    | None = None,
    *,
    query: ProofCorpusQuery | None = None,
) -> AdmissibilityDecision:
    """Module-level helper: evaluate intent admissibility against *store*."""

    gate = IntentAdmissibilityGate(store=store, query=query)
    return gate.evaluate(intent, profile)


__all__ = [
    "ADMISSIBILITY_DECISION_INTERFACE",
    "ADMISSIBILITY_DECISION_SCHEMA_VERSION",
    "ADMISSIBILITY_GATE_INTERFACE",
    "ADMISSIBILITY_GATE_SCHEMA_VERSION",
    "AdmissibilityDecision",
    "AdmissibilityGateError",
    "ConstraintPolarity",
    "IntentAdmissibilityGate",
    "classify_constraint_polarity",
    "evaluate_admissibility",
    "intent_has_unsupported_semantics",
    "store_snapshot_digest",
]
