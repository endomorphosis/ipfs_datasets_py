"""Unit tests for the composite admissibility gate core (LIG-015).

Acceptance:

* Unit tests for four outcome classes (allow, legal-hard reject, security-hard
  reject, abstain).
* Decisions are deterministic for a fixed store snapshot.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.admissibility.gate import (
    ADMISSIBILITY_DECISION_INTERFACE,
    ADMISSIBILITY_GATE_INTERFACE,
    AdmissibilityDecision,
    ConstraintPolarity,
    IntentAdmissibilityGate,
    classify_constraint_polarity,
    evaluate_admissibility,
    intent_has_unsupported_semantics,
    store_snapshot_digest,
)
from ipfs_datasets_py.logic.admissibility.profiles import (
    DEFAULT_PROFILE_ID,
    get_profile,
)
from ipfs_datasets_py.logic.admissibility.reasons import (
    AdmissibilityReasonCode,
    AdmissibilityStatus,
)
from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.proof_corpus.query import ProofCorpusQuery
from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "fixtures" / "intent_ir" / "admissibility"
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _intent_artifact(case_id: str = "benign_skill") -> FormalizationArtifact:
    path = FIXTURE_ROOT / "formal_artifacts" / f"{case_id}.json"
    return FormalizationArtifact.from_dict(_load_json(path))


def _constraint_from_intent(
    intent_raw: dict[str, Any],
    *,
    domain: str,
    role: str,
) -> FormalizationArtifact:
    """Clone an Intent formal artifact into a Legal/Security constraint.

    Obligation digests are preserved so the gate can join via
    :meth:`ProofCorpusQuery.list_constraints_for_obligation`.  Formula
    expressions carry closed polarity markers for grant/forbid classification.
    """

    payload = copy.deepcopy(intent_raw)
    payload["domain"] = domain
    metadata = dict(payload.get("metadata") or {})
    metadata["gate_role"] = role
    metadata["constraint_family"] = domain
    payload["metadata"] = metadata
    for formula in payload.get("formulas", []):
        expression = formula.get("expression")
        if isinstance(expression, dict):
            expression = dict(expression)
            expression["role"] = role
            if role in {"grant", "permission", "support"}:
                expression["norm_type"] = "permission"
                expression["polarity"] = "positive"
            else:
                expression["norm_type"] = "prohibition"
                expression["polarity"] = "negative"
            formula["expression"] = expression
    return FormalizationArtifact.from_dict(payload)


def _put_intent(
    store: ProofCorpusStore,
    artifact: FormalizationArtifact,
    *,
    profile: str = "legal-strict",
) -> ArtifactEnvelope:
    return store.put(
        ArtifactEnvelope.from_intent_artifact(artifact, profile=profile)
    )


def _put_constraint(
    store: ProofCorpusStore,
    artifact: FormalizationArtifact,
    *,
    family: str,
    profile: str = "legal-strict",
) -> ArtifactEnvelope:
    return store.put(
        ArtifactEnvelope.build(
            artifact,
            profile=profile,
            family=family,
            producer_id=f"test-{family}-constraint",
        )
    )


def _fixed_allow_store() -> tuple[ProofCorpusStore, ArtifactEnvelope]:
    """Store snapshot that should allow under legal-strict."""

    intent_raw = _load_json(
        FIXTURE_ROOT / "formal_artifacts" / "benign_skill.json"
    )
    intent = FormalizationArtifact.from_dict(intent_raw)
    legal = _constraint_from_intent(intent_raw, domain="legal", role="grant")
    security = _constraint_from_intent(
        intent_raw, domain="security", role="grant"
    )
    store = ProofCorpusStore()
    intent_env = _put_intent(store, intent)
    _put_constraint(store, legal, family="legal")
    _put_constraint(store, security, family="security")
    return store, intent_env


def _fixed_legal_reject_store() -> tuple[ProofCorpusStore, ArtifactEnvelope]:
    intent_raw = _load_json(
        FIXTURE_ROOT / "formal_artifacts" / "legally_risky_effect.json"
    )
    intent = FormalizationArtifact.from_dict(intent_raw)
    legal = _constraint_from_intent(
        intent_raw, domain="legal", role="prohibition"
    )
    security = _constraint_from_intent(
        intent_raw, domain="security", role="grant"
    )
    store = ProofCorpusStore()
    intent_env = _put_intent(store, intent)
    _put_constraint(store, legal, family="legal")
    _put_constraint(store, security, family="security")
    return store, intent_env


def _fixed_security_reject_store() -> tuple[ProofCorpusStore, ArtifactEnvelope]:
    intent_raw = _load_json(
        FIXTURE_ROOT
        / "formal_artifacts"
        / "security_sensitive_resource.json"
    )
    intent = FormalizationArtifact.from_dict(intent_raw)
    legal = _constraint_from_intent(intent_raw, domain="legal", role="grant")
    security = _constraint_from_intent(
        intent_raw, domain="security", role="prohibition"
    )
    store = ProofCorpusStore()
    intent_env = _put_intent(store, intent)
    _put_constraint(store, legal, family="legal")
    _put_constraint(store, security, family="security")
    return store, intent_env


def _fixed_abstain_store() -> tuple[ProofCorpusStore, ArtifactEnvelope]:
    """Incomplete/unsupported Intent with no supporting constraints."""

    intent = _intent_artifact("incomplete_unsupported_semantics")
    store = ProofCorpusStore()
    intent_env = _put_intent(store, intent)
    return store, intent_env


# ---------------------------------------------------------------------------
# Interface contracts
# ---------------------------------------------------------------------------


def test_gate_interfaces_are_pinned() -> None:
    store, _ = _fixed_allow_store()
    gate = IntentAdmissibilityGate(store=store)
    assert gate.interface == ADMISSIBILITY_GATE_INTERFACE
    assert gate.interface == "IntentAdmissibilityGate@1"
    assert ADMISSIBILITY_DECISION_INTERFACE == "AdmissibilityDecision@1"
    assert DEFAULT_PROFILE_ID.value == "legal-strict"


# ---------------------------------------------------------------------------
# Four outcome classes
# ---------------------------------------------------------------------------


def test_outcome_allow_obligations_supported() -> None:
    store, intent_env = _fixed_allow_store()
    gate = IntentAdmissibilityGate(store=store)
    decision = gate.evaluate(intent_env.content_cid, "legal-strict")

    assert decision.status is AdmissibilityStatus.ALLOW
    assert decision.is_allow is True
    assert AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED.value in (
        decision.reason_codes
    )
    assert decision.profile_id == "legal-strict"
    assert decision.config_digest == get_profile("legal-strict").config_digest()
    assert decision.intent_cid == intent_env.content_cid
    assert decision.intent_artifact_cid == intent_env.artifact_cid
    assert len(decision.constraint_cids) >= 2
    assert decision.constraint_cids == tuple(sorted(decision.constraint_cids))
    assert decision.store_snapshot_digest.startswith("sha256:")
    assert decision.interface == ADMISSIBILITY_DECISION_INTERFACE


def test_outcome_legal_hard_constraint_reject() -> None:
    store, intent_env = _fixed_legal_reject_store()
    decision = evaluate_admissibility(
        store, intent_env.content_cid, "legal-strict"
    )

    assert decision.status is AdmissibilityStatus.REJECT
    assert decision.is_reject is True
    assert (
        AdmissibilityReasonCode.LEGAL_HARD_CONSTRAINT.value
        in decision.reason_codes
    )
    assert decision.intent_cid == intent_env.content_cid
    assert decision.constraint_cids  # legal forbid bound


def test_outcome_security_hard_constraint_reject() -> None:
    store, intent_env = _fixed_security_reject_store()
    gate = IntentAdmissibilityGate(store=store)
    decision = gate.evaluate(intent_env.content_cid, profile="legal-strict")

    assert decision.status is AdmissibilityStatus.REJECT
    assert (
        AdmissibilityReasonCode.SECURITY_HARD_CONSTRAINT.value
        in decision.reason_codes
    )
    assert decision.intent_cid == intent_env.content_cid


def test_outcome_abstain_unsupported_semantics_and_missing_evidence() -> None:
    store, intent_env = _fixed_abstain_store()
    intent = intent_env.formalization_artifact()
    assert intent_has_unsupported_semantics(intent) is True
    assert len(intent.proof_obligations) == 0

    gate = IntentAdmissibilityGate(store=store)
    decision = gate.evaluate(intent_env.content_cid)

    assert decision.status is AdmissibilityStatus.ABSTAIN
    assert decision.is_abstain is True
    codes = set(decision.reason_codes)
    assert AdmissibilityReasonCode.SEMANTICS_UNSUPPORTED.value in codes
    assert AdmissibilityReasonCode.MISSING_EVIDENCE.value in codes
    # Never promote incomplete evidence to allow.
    assert decision.status is not AdmissibilityStatus.ALLOW


# ---------------------------------------------------------------------------
# Determinism for fixed store snapshot
# ---------------------------------------------------------------------------


def test_decision_is_deterministic_for_fixed_store_snapshot() -> None:
    store, intent_env = _fixed_allow_store()
    snapshot = store_snapshot_digest(store)
    gate = IntentAdmissibilityGate(store=store)

    first = gate.evaluate(intent_env.content_cid, "legal-strict")
    second = gate.evaluate(intent_env.content_cid, "legal-strict")
    third = evaluate_admissibility(
        store, intent_env.content_cid, "legal-strict"
    )

    assert first.to_dict() == second.to_dict() == third.to_dict()
    assert first.store_snapshot_digest == snapshot
    assert second.store_snapshot_digest == snapshot
    # Round-trip preserves wire identity.
    restored = AdmissibilityDecision.from_dict(first.to_dict())
    assert restored.to_dict() == first.to_dict()


def test_decision_deterministic_across_query_rebuild() -> None:
    store, intent_env = _fixed_legal_reject_store()
    gate = IntentAdmissibilityGate(
        store=store, query=ProofCorpusQuery(store=store)
    )
    gate.rebuild_index()
    a = gate.evaluate(intent_env.content_cid, "legal-strict")
    gate.rebuild_index()
    b = gate.evaluate(intent_env.content_cid, "legal-strict")
    assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# Fail-closed profile / intent / no-constraints
# ---------------------------------------------------------------------------


def test_invalid_profile_fails_closed_as_reject() -> None:
    store, intent_env = _fixed_allow_store()
    gate = IntentAdmissibilityGate(store=store)
    decision = gate.evaluate(intent_env.content_cid, "not-a-real-profile")
    assert decision.status is AdmissibilityStatus.REJECT
    assert decision.reason_codes == (
        AdmissibilityReasonCode.INVALID_PROFILE.value,
    )
    assert decision.profile_id == ""
    assert decision.is_allow is False


def test_missing_intent_cid_fails_closed() -> None:
    store, _ = _fixed_allow_store()
    gate = IntentAdmissibilityGate(store=store)
    decision = gate.evaluate("bafkreimissingintentcid00000000000000000001")
    assert decision.status is AdmissibilityStatus.REJECT
    assert AdmissibilityReasonCode.INVALID_INTENT.value in decision.reason_codes


def test_default_profile_never_allows_without_constraints() -> None:
    intent = _intent_artifact("benign_skill")
    store = ProofCorpusStore()
    intent_env = _put_intent(store, intent)
    # Intent only — no Legal/Security grants in the corpus.
    decision = evaluate_admissibility(store, intent_env.content_cid, None)
    assert decision.profile_id == "legal-strict"
    assert decision.status is AdmissibilityStatus.REJECT
    assert AdmissibilityReasonCode.NO_CONSTRAINTS.value in decision.reason_codes
    assert decision.is_allow is False


def test_zkp_required_missing_proof_abstains() -> None:
    store, intent_env = _fixed_allow_store()
    gate = IntentAdmissibilityGate(store=store)
    decision = gate.evaluate(intent_env.content_cid, "zkp-required")
    # Grants exist but no ZKP attestations are stored for legal envelopes.
    assert decision.status is AdmissibilityStatus.ABSTAIN
    assert AdmissibilityReasonCode.ZKP_MISSING.value in decision.reason_codes
    assert decision.is_allow is False


# ---------------------------------------------------------------------------
# Constraint polarity helpers
# ---------------------------------------------------------------------------


def test_classify_constraint_polarity_grant_and_forbid() -> None:
    intent_raw = _load_json(
        FIXTURE_ROOT / "formal_artifacts" / "benign_skill.json"
    )
    grant = ArtifactEnvelope.build(
        _constraint_from_intent(intent_raw, domain="legal", role="grant"),
        profile="legal-strict",
        family="legal",
    )
    forbid = ArtifactEnvelope.build(
        _constraint_from_intent(
            intent_raw, domain="security", role="prohibition"
        ),
        profile="legal-strict",
        family="security",
    )
    assert classify_constraint_polarity(grant) is ConstraintPolarity.GRANT
    assert classify_constraint_polarity(forbid) is ConstraintPolarity.FORBID


def test_evaluate_accepts_formalization_artifact_directly() -> None:
    store, _ = _fixed_allow_store()
    intent = _intent_artifact("benign_skill")
    decision = evaluate_admissibility(store, intent, "legal-strict")
    assert decision.status is AdmissibilityStatus.ALLOW
    assert decision.intent_cid  # envelope content cid derived from artifact
    assert (
        AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED.value
        in decision.reason_codes
    )


def test_contradiction_when_grant_and_forbid_share_obligation() -> None:
    intent_raw = _load_json(
        FIXTURE_ROOT / "formal_artifacts" / "benign_skill.json"
    )
    intent = FormalizationArtifact.from_dict(intent_raw)
    legal_grant = _constraint_from_intent(
        intent_raw, domain="legal", role="grant"
    )
    legal_forbid = _constraint_from_intent(
        intent_raw, domain="legal", role="prohibition"
    )
    # Distinct security grant so family requirements can still be considered.
    security = _constraint_from_intent(
        intent_raw, domain="security", role="grant"
    )
    # Differentiate two legal envelopes: mutate metadata role already differs
    # so digests differ.
    store = ProofCorpusStore()
    intent_env = _put_intent(store, intent)
    _put_constraint(store, legal_grant, family="legal")
    # Second legal envelope needs a distinct identity — tweak formula text.
    forbid_raw = copy.deepcopy(intent_raw)
    forbid_raw["domain"] = "legal"
    meta = dict(forbid_raw.get("metadata") or {})
    meta["gate_role"] = "prohibition"
    meta["constraint_variant"] = "forbid-twin"
    forbid_raw["metadata"] = meta
    for formula in forbid_raw.get("formulas", []):
        expression = formula.get("expression")
        if isinstance(expression, dict):
            expression = dict(expression)
            expression["role"] = "prohibition"
            expression["norm_type"] = "prohibition"
            expression["polarity"] = "negative"
            expression["variant"] = "forbid-twin"
            formula["expression"] = expression
    legal_forbid = FormalizationArtifact.from_dict(forbid_raw)
    _put_constraint(store, legal_forbid, family="legal")
    _put_constraint(store, security, family="security")

    decision = evaluate_admissibility(
        store, intent_env.content_cid, "legal-strict"
    )
    assert decision.status is AdmissibilityStatus.REJECT
    codes = set(decision.reason_codes)
    assert (
        AdmissibilityReasonCode.CONSTRAINT_CONTRADICTION.value in codes
        or AdmissibilityReasonCode.LEGAL_HARD_CONSTRAINT.value in codes
    )
