"""End-to-end Intent admissibility gate integration (LIG-016 / LIG-G060).

Compact multi-family corpus *recipes* under ``tests/fixtures/logic/admissibility``
drive ``IntentAdmissibilityGate@1`` for allow, legal-hard reject, security-hard
reject, contradiction, missing-evidence abstain, and zkp-required missing-proof
abstain.

Envelopes are reconstructed at load time from pinned Intent formalization
artifacts in ``tests/fixtures/intent_ir/admissibility`` (read-only companion
fixtures).  Full lineage CIDs are asserted against the compact pins; no network
is required.
"""

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.admissibility.gate import (
    ADMISSIBILITY_DECISION_INTERFACE,
    ADMISSIBILITY_DECISION_SCHEMA_VERSION,
    ADMISSIBILITY_GATE_INTERFACE,
    AdmissibilityDecision,
    IntentAdmissibilityGate,
    evaluate_admissibility,
    store_snapshot_digest,
)
from ipfs_datasets_py.logic.admissibility.profiles import get_profile
from ipfs_datasets_py.logic.admissibility.reasons import (
    AdmissibilityReasonCode,
    AdmissibilityStatus,
)
from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "logic" / "admissibility"
INTENT_FORMAL_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "intent_ir" / "admissibility"
)

REQUIRED_CASE_IDS = (
    "benign_skill",
    "legal_hard_reject",
    "security_hard_reject",
    "abstain_incomplete",
    "contradiction_grant_and_forbid",
    "zkp_required_missing_proof",
)

REQUIRED_STRATA = (
    "allow",
    "legal_reject",
    "security_reject",
    "abstain",
    "contradiction",
    "zkp_abstain",
)

_CID_PREFIXES = ("bafy", "bafk", "bagu", "Qm")
_SHA256_PREFIX = "sha256:"


# ---------------------------------------------------------------------------
# Fixture loaders
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict[str, Any]:
    return _load_json(FIXTURE_ROOT / "manifest.json")


def _case_dir(case_id: str) -> Path:
    return FIXTURE_ROOT / "cases" / case_id


def _case_record(case_id: str) -> dict[str, Any]:
    return _load_json(_case_dir(case_id) / "case.json")


def _lineage(case_id: str) -> dict[str, Any]:
    return _load_json(_case_dir(case_id) / "lineage.json")


def _expected_decision(case_id: str) -> dict[str, Any]:
    return _load_json(_case_dir(case_id) / "expected_decision.json")


def _is_cid(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return value.startswith(_CID_PREFIXES)


def _is_digest(value: object) -> bool:
    if not isinstance(value, str):
        return False
    if value.startswith(_SHA256_PREFIX):
        return len(value) == len(_SHA256_PREFIX) + 64
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _constraint_from_intent(
    intent_raw: dict[str, Any],
    *,
    domain: str,
    role: str,
    variant: str | None = None,
) -> FormalizationArtifact:
    """Clone an Intent formal artifact into a Legal/Security constraint."""

    payload = copy.deepcopy(intent_raw)
    payload["domain"] = domain
    metadata = dict(payload.get("metadata") or {})
    metadata["gate_role"] = role
    metadata["constraint_family"] = domain
    if variant:
        metadata["constraint_variant"] = variant
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
            if variant:
                expression["variant"] = variant
            formula["expression"] = expression
    return FormalizationArtifact.from_dict(payload)


def _load_intent_formal(source_case_id: str) -> tuple[dict[str, Any], FormalizationArtifact]:
    path = INTENT_FORMAL_ROOT / "formal_artifacts" / f"{source_case_id}.json"
    raw = _load_json(path)
    return raw, FormalizationArtifact.from_dict(raw)


def _build_corpus(
    case_id: str,
) -> tuple[ProofCorpusStore, ArtifactEnvelope, dict[str, Any], dict[str, ArtifactEnvelope]]:
    """Rebuild the multi-family corpus for a compact recipe case."""

    case = _case_record(case_id)
    lineage = _lineage(case_id)
    intent_raw, intent = _load_intent_formal(case["source_formal_case_id"])
    env_profile = case.get("envelope_profile_id", "legal-strict")

    store = ProofCorpusStore()
    intent_env = store.put(
        ArtifactEnvelope.from_intent_artifact(intent, profile=env_profile)
    )
    by_name: dict[str, ArtifactEnvelope] = {"intent": intent_env}

    for c in case.get("constraints") or []:
        art = _constraint_from_intent(
            intent_raw,
            domain=c["domain"],
            role=c["role"],
            variant=c.get("variant"),
        )
        env = store.put(
            ArtifactEnvelope.build(
                art,
                profile=c.get("profile", "legal-strict"),
                family=c["family"],
                producer_id=f"test-{c['family']}-constraint",
            )
        )
        by_name[c["name"]] = env

    assert store_snapshot_digest(store) == lineage["store_snapshot_digest"]
    assert intent_env.content_cid == lineage["intent_content_cid"]
    assert intent_env.artifact_cid == lineage["intent_artifact_cid"]
    return store, intent_env, lineage, by_name


# ---------------------------------------------------------------------------
# Network guard — fixtures and gate must remain offline
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed if any test path attempts a real network connection."""

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "LIG-016 integration fixtures must not use the network"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *_a, **_k: 1)


# ---------------------------------------------------------------------------
# Manifest inventory
# ---------------------------------------------------------------------------


def test_fixture_manifest_covers_required_outcome_classes() -> None:
    manifest = _manifest()
    assert manifest["interface"] == "LogicAdmissibilityGateFixtures@1"
    assert manifest["schema_version"] == "logic-admissibility-gate-fixtures/v1"
    assert manifest["gate_interface"] == ADMISSIBILITY_GATE_INTERFACE
    assert manifest["decision_interface"] == ADMISSIBILITY_DECISION_INTERFACE
    assert manifest["default_profile_id"] == "legal-strict"

    case_ids = tuple(manifest["case_ids"])
    assert set(REQUIRED_CASE_IDS) <= set(case_ids)
    assert len(case_ids) == len(set(case_ids))
    assert [c["case_id"] for c in manifest["cases"]] == list(case_ids)

    strata = {c["stratum"] for c in manifest["cases"]}
    assert set(REQUIRED_STRATA) <= strata
    assert set(manifest["expected_strata"]) == strata

    for entry in manifest["cases"]:
        case_path = FIXTURE_ROOT / entry["path"]
        assert case_path.is_dir(), entry["path"]
        assert (case_path / "case.json").is_file()
        assert (case_path / "lineage.json").is_file()
        assert (case_path / "expected_decision.json").is_file()
        assert _is_cid(entry["intent_content_cid"])
        assert _is_cid(entry["intent_artifact_cid"])
        assert _is_digest(entry["intent_source_digest"])
        assert _is_digest(entry["store_snapshot_digest"])
        assert _is_digest(entry["profile_config_digest"])
        for cid in entry["constraint_content_cids"]:
            assert _is_cid(cid)
        # Source formal artifact used for reconstruction must exist.
        source = entry["source_formal_case_id"]
        assert (
            INTENT_FORMAL_ROOT / "formal_artifacts" / f"{source}.json"
        ).is_file()


# ---------------------------------------------------------------------------
# Parametrized end-to-end gate outcomes + full lineage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", REQUIRED_CASE_IDS)
def test_end_to_end_gate_decision_matches_pinned_lineage(case_id: str) -> None:
    case = _case_record(case_id)
    lineage = _lineage(case_id)
    expected = _expected_decision(case_id)
    store, intent_env, _, by_name = _build_corpus(case_id)

    gate = IntentAdmissibilityGate(store=store)
    assert gate.interface == ADMISSIBILITY_GATE_INTERFACE

    decision = gate.evaluate(intent_env.content_cid, case["profile_id"])
    via_helper = evaluate_admissibility(
        store, intent_env.content_cid, case["profile_id"]
    )
    assert decision.to_dict() == via_helper.to_dict()

    assert decision.status is AdmissibilityStatus(expected["status"])
    assert set(decision.reason_codes) == set(expected["reason_codes"])
    for code in expected["reason_codes"]:
        AdmissibilityReasonCode(code)  # closed enum

    assert decision.interface == ADMISSIBILITY_DECISION_INTERFACE
    assert decision.schema_version == ADMISSIBILITY_DECISION_SCHEMA_VERSION
    assert decision.profile_id == expected["profile_id"] == case["profile_id"]
    assert decision.config_digest == expected["config_digest"]
    assert decision.config_digest == case["profile_config_digest"]
    assert decision.config_digest == get_profile(case["profile_id"]).config_digest()

    # Full lineage: intent formalization → envelope → decision binding.
    assert decision.intent_cid == lineage["intent_content_cid"]
    assert decision.intent_cid == intent_env.content_cid
    assert decision.intent_cid == expected["intent_cid"]
    assert decision.intent_artifact_cid == lineage["intent_artifact_cid"]
    assert decision.intent_artifact_cid == intent_env.artifact_cid
    assert decision.intent_artifact_cid == expected["intent_artifact_cid"]
    assert intent_env.artifact_digest == lineage["intent_artifact_digest"]
    assert intent_env.source_digest == lineage["intent_source_digest"]
    assert intent_env.content_digest == lineage["intent_content_digest"]
    assert lineage["intent_formal_artifact_cid"] == intent_env.artifact_cid
    assert lineage["intent_declaration_digest"] == intent_env.source_digest

    # Constraint CIDs bound by the gate match the multi-family corpus pins.
    assert list(decision.constraint_cids) == list(expected["constraint_cids"])
    assert decision.constraint_cids == tuple(sorted(decision.constraint_cids))
    for cid in decision.constraint_cids:
        assert _is_cid(cid)
        assert cid in lineage["constraint_content_cids"]
        assert cid in lineage["corpus_content_cids"]
        bound = store.get(cid)
        assert bound.content_cid == cid
        assert bound.family.value in {"legal", "security"}
        assert bound.artifact_cid in lineage["constraint_artifact_cids"]

    for cid in lineage["corpus_content_cids"]:
        assert _is_cid(cid)
        assert store.get(cid).content_cid == cid

    assert decision.store_snapshot_digest == lineage["store_snapshot_digest"]
    assert decision.store_snapshot_digest == expected["store_snapshot_digest"]
    assert decision.store_snapshot_digest == store_snapshot_digest(store)
    assert _is_digest(decision.store_snapshot_digest)

    # Recipe envelope names reconstruct to the same content CIDs.
    assert set(by_name) == set(case["envelopes"])

    wire = decision.to_dict()
    assert wire["attestation_results"] == expected["attestation_results"]
    restored = AdmissibilityDecision.from_dict(wire)
    assert restored.to_dict() == wire


@pytest.mark.parametrize(
    ("case_id", "status", "required_codes"),
    [
        (
            "benign_skill",
            AdmissibilityStatus.ALLOW,
            (AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED,),
        ),
        (
            "legal_hard_reject",
            AdmissibilityStatus.REJECT,
            (AdmissibilityReasonCode.LEGAL_HARD_CONSTRAINT,),
        ),
        (
            "security_hard_reject",
            AdmissibilityStatus.REJECT,
            (AdmissibilityReasonCode.SECURITY_HARD_CONSTRAINT,),
        ),
        (
            "abstain_incomplete",
            AdmissibilityStatus.ABSTAIN,
            (
                AdmissibilityReasonCode.SEMANTICS_UNSUPPORTED,
                AdmissibilityReasonCode.MISSING_EVIDENCE,
            ),
        ),
        (
            "contradiction_grant_and_forbid",
            AdmissibilityStatus.REJECT,
            (AdmissibilityReasonCode.CONSTRAINT_CONTRADICTION,),
        ),
        (
            "zkp_required_missing_proof",
            AdmissibilityStatus.ABSTAIN,
            (AdmissibilityReasonCode.ZKP_MISSING,),
        ),
    ],
)
def test_outcome_class_semantics(
    case_id: str,
    status: AdmissibilityStatus,
    required_codes: tuple[AdmissibilityReasonCode, ...],
) -> None:
    store, intent_env, lineage, _ = _build_corpus(case_id)
    case = _case_record(case_id)
    decision = evaluate_admissibility(
        store, intent_env.content_cid, case["profile_id"]
    )

    assert decision.status is status
    codes = set(decision.reason_codes)
    for code in required_codes:
        assert code.value in codes

    if status is not AdmissibilityStatus.ALLOW:
        assert decision.is_allow is False
        assert decision.status is not AdmissibilityStatus.ALLOW
    else:
        assert decision.is_allow is True
        assert set(lineage["legal_content_cids"]) <= set(decision.constraint_cids)
        assert set(lineage["security_content_cids"]) <= set(
            decision.constraint_cids
        )
        assert len(decision.constraint_cids) >= 2


# ---------------------------------------------------------------------------
# Determinism, rebuild, and formal-artifact entry path
# ---------------------------------------------------------------------------


def test_decision_deterministic_for_fixed_corpus_snapshot() -> None:
    store, intent_env, lineage, _ = _build_corpus("benign_skill")
    gate = IntentAdmissibilityGate(store=store)
    first = gate.evaluate(intent_env.content_cid, "legal-strict")
    second = gate.evaluate(intent_env.content_cid, "legal-strict")
    third = evaluate_admissibility(store, intent_env.content_cid, "legal-strict")

    assert first.to_dict() == second.to_dict() == third.to_dict()
    assert first.store_snapshot_digest == lineage["store_snapshot_digest"]
    gate.rebuild_index()
    fourth = gate.evaluate(intent_env.content_cid, "legal-strict")
    assert fourth.to_dict() == first.to_dict()


def test_evaluate_from_formalization_artifact_preserves_lineage() -> None:
    """Gate accepts FormalizationArtifact and still binds intent envelope CIDs."""

    case_id = "benign_skill"
    store, _intent_env, lineage, _ = _build_corpus(case_id)
    _raw, artifact = _load_intent_formal(
        _case_record(case_id)["source_formal_case_id"]
    )
    assert artifact.artifact_id == lineage["intent_formal_artifact_cid"]
    assert artifact.declaration_digest == lineage["intent_declaration_digest"]

    decision = evaluate_admissibility(store, artifact, "legal-strict")
    assert decision.status is AdmissibilityStatus.ALLOW
    assert decision.intent_cid == lineage["intent_content_cid"]
    assert decision.intent_artifact_cid == lineage["intent_artifact_cid"]
    assert set(lineage["constraint_content_cids"]) == set(decision.constraint_cids)


def test_reconstructed_envelopes_rehash_to_pinned_content_cids() -> None:
    """Recipe reconstruction is integrity-bound; rehash equals pinned lineage."""

    for case_id in REQUIRED_CASE_IDS:
        case = _case_record(case_id)
        lineage = _lineage(case_id)
        store, intent_env, _, by_name = _build_corpus(case_id)
        assert store_snapshot_digest(store) == lineage["store_snapshot_digest"]

        for name in case["envelopes"]:
            env = by_name[name]
            rebuilt = ArtifactEnvelope.build(
                env.formalization_artifact(),
                profile=env.profile,
                family=env.family,
                source_id=env.source_id,
                source_digest=env.source_digest,
                producer_id=env.producer_id,
                review_state=env.review_state,
                jurisdiction=env.jurisdiction,
                attachments=dict(env.attachments),
            )
            assert rebuilt.content_cid == env.content_cid
            assert rebuilt.content_digest == env.content_digest
            assert rebuilt.artifact_cid == env.artifact_cid
            if name == "intent":
                assert env.content_cid == lineage["intent_content_cid"]
                assert env.artifact_cid == lineage["intent_artifact_cid"]
                assert env is intent_env
            elif name.startswith("legal"):
                assert env.content_cid in lineage["legal_content_cids"]
            elif name.startswith("security"):
                assert env.content_cid in lineage["security_content_cids"]


def test_default_profile_never_allows_without_constraints() -> None:
    """Corpus with Intent only (no Legal/Security) must not allow under default."""

    _raw, intent = _load_intent_formal("benign_skill")
    store = ProofCorpusStore()
    intent_env = store.put(
        ArtifactEnvelope.from_intent_artifact(intent, profile="legal-strict")
    )
    decision = evaluate_admissibility(store, intent_env.content_cid, None)
    assert decision.profile_id == "legal-strict"
    assert decision.is_allow is False
    assert decision.status is AdmissibilityStatus.REJECT
    assert AdmissibilityReasonCode.NO_CONSTRAINTS.value in decision.reason_codes


def test_intent_ir_source_digest_matches_lineage_when_present() -> None:
    """Intent IR source fixtures bind declaration lineage to formal artifacts."""

    case_id = "benign_skill"
    case = _case_record(case_id)
    lineage = _lineage(case_id)
    ir_path = REPO_ROOT / case["source_intent_ir_path"]
    assert ir_path.is_file()
    intent_ir = _load_json(ir_path)
    _raw, formal = _load_intent_formal(case["source_formal_case_id"])
    assert formal.declaration_digest == lineage["intent_declaration_digest"]
    assert formal.declaration_digest == lineage["intent_source_digest"]
    assert intent_ir.get("document_id") or intent_ir.get("schema_version")
    assert (
        formal.sample_id == lineage["intent_source_id"]
        or formal.declaration_id == lineage["intent_source_id"]
    )


def test_manifest_lineage_entries_match_case_files() -> None:
    """Top-level manifest pins agree with per-case lineage files."""

    manifest = _manifest()
    for entry in manifest["cases"]:
        case_id = entry["case_id"]
        lineage = _lineage(case_id)
        expected = _expected_decision(case_id)
        assert entry["intent_content_cid"] == lineage["intent_content_cid"]
        assert entry["intent_artifact_cid"] == lineage["intent_artifact_cid"]
        assert entry["intent_source_digest"] == lineage["intent_source_digest"]
        assert entry["constraint_content_cids"] == lineage["constraint_content_cids"]
        assert entry["store_snapshot_digest"] == lineage["store_snapshot_digest"]
        assert entry["expected_status"] == expected["status"]
        assert set(entry["expected_reason_codes"]) == set(expected["reason_codes"])
        assert entry["profile_config_digest"] == expected["config_digest"]
