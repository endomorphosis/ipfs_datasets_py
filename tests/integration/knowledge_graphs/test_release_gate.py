"""Integration tests: production release evidence gate (KGP-035).

Acceptance:
  Require exact fresh passing receipts for child goals KGP-G010 through
  KGP-G090 and every root definition-of-done clause, including corpus-specific
  sign-off. Reject task status, coverage, prose, optional-dependency skip,
  sample-only corpus runs, absent soak/chaos, missing UCAN negative proof, or
  unknown environment as substitutes. Emit a signed/content-addressed release
  decision and retain the platform as not production ready until it passes.

Conflict policy:
  Missing, stale, foreign-tree, skipped, partial, or contradicted evidence
  fails closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs import release_gate as rg
from ipfs_datasets_py.knowledge_graphs.release_gate import (
    ACCEPTED_EVIDENCE_KINDS,
    BUNDLE_SCHEMA_VERSION,
    DECISION_SCHEMA_VERSION,
    DEFAULT_MAX_RECEIPT_AGE,
    GOAL_ID,
    POLICY_ID,
    REJECTED_SUBSTITUTES,
    REQUIRED_CHILD_GOALS,
    REQUIRED_CORPORA,
    ROOT_DOD_CLAUSE_IDS,
    ROOT_DOD_CLAUSES,
    SCHEMA_VERSION,
    TASK_ID,
    BlockerCode,
    CorpusSignOff,
    DecisionOutcome,
    DodClauseReceipt,
    EnvironmentBinding,
    GoalReceipt,
    GraphReleaseGate,
    ReleaseEvidenceBundle,
    ReleaseGateError,
    ReleaseGateFailClosed,
    SoakChaosEvidence,
    UCANNegativeProof,
    build_passing_bundle,
    content_address,
    content_cid,
    default_not_production_ready_decision,
    evaluate_release_evidence,
    is_production_ready,
    is_rejected_substitute,
    is_unknown_environment,
    make_corpus_signoff,
    make_dod_receipt,
    make_goal_receipt,
    policy_dict,
    sign_decision,
    verify_decision_signature,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_DOC = REPO_ROOT / "docs" / "operations" / "knowledge_graphs_release.md"
RELEASE_GATE_PY = (
    REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs" / "release_gate.py"
)

TREE_ID = "tree-ab30e5a9e5f5225e6375a72eee8ee47988bcf9a4"
FOREIGN_TREE = "tree-ffffffffffffffffffffffffffffffffffffffff"
SIGNING_KEY = b"kgp-035-test-signing-key-not-for-production"
FIXED_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _ts(dt: datetime | None = None) -> str:
    value = (dt or FIXED_NOW).astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _passing_bundle(**overrides) -> ReleaseEvidenceBundle:
    bundle = build_passing_bundle(
        tree_id=TREE_ID,
        now=FIXED_NOW,
        package_version="0.1.0-test",
    )
    for key, value in overrides.items():
        setattr(bundle, key, value)
    return bundle


def _blocker_codes(decision) -> set[str]:
    return {b.code for b in decision.blockers}


def _subjects_for(decision, code: str) -> set[str]:
    return {b.subject for b in decision.blockers if b.code == code}


# ---------------------------------------------------------------------------
# Module / policy surface
# ---------------------------------------------------------------------------


def test_required_child_goals_are_exact_g010_through_g090() -> None:
    assert REQUIRED_CHILD_GOALS == (
        "KGP-G010",
        "KGP-G020",
        "KGP-G030",
        "KGP-G040",
        "KGP-G050",
        "KGP-G060",
        "KGP-G070",
        "KGP-G080",
        "KGP-G090",
    )
    assert len(REQUIRED_CHILD_GOALS) == 9


def test_root_dod_clauses_cover_plan_definition_of_done() -> None:
    ids = set(ROOT_DOD_CLAUSE_IDS)
    assert "concurrent_identity_durability" in ids
    assert "storage_profiles_contract" in ids
    assert "four_surface_parity" in ids
    assert "ucan_fail_closed" in ids
    assert "sharded_integrity" in ids
    assert "corpora_differential" in ids
    assert "load_soak_chaos_ops" in ids
    assert "migration_reversible" in ids
    assert len(ROOT_DOD_CLAUSES) == 8


def test_required_corpora_match_inventory() -> None:
    assert set(REQUIRED_CORPORA) == {
        "cvefixes",
        "skillcenter",
        "two_eleven",
        "code_evidence",
    }


def test_rejected_substitutes_include_acceptance_list() -> None:
    required = {
        "task_status",
        "coverage",
        "prose",
        "optional_dependency_skip",
        "sample_only_corpus",
        "absent_soak_chaos",
        "missing_ucan_negative_proof",
        "unknown_environment",
    }
    assert required <= REJECTED_SUBSTITUTES
    for kind in required:
        assert is_rejected_substitute(kind)


def test_policy_dict_is_stable_and_complete() -> None:
    policy = policy_dict()
    assert policy["schema_version"] == SCHEMA_VERSION
    assert policy["task_id"] == TASK_ID
    assert policy["goal_id"] == GOAL_ID
    assert policy["policy_id"] == POLICY_ID
    assert policy["required_child_goals"] == list(REQUIRED_CHILD_GOALS)
    assert {c["clause_id"] for c in policy["required_dod_clauses"]} == set(
        ROOT_DOD_CLAUSE_IDS
    )


def test_module_and_docs_exist() -> None:
    assert RELEASE_GATE_PY.is_file()
    assert RELEASE_DOC.is_file()
    text = RELEASE_DOC.read_text(encoding="utf-8")
    assert "KGP-035" in text
    assert "GraphReleaseGate" in text or "release_gate" in text
    assert "not production ready" in text.lower() or "not production-ready" in text.lower()
    assert "KGP-G010" in text and "KGP-G090" in text


# ---------------------------------------------------------------------------
# Default posture: not production ready
# ---------------------------------------------------------------------------


def test_platform_not_production_ready_without_evaluation() -> None:
    assert is_production_ready(None) is False
    decision = default_not_production_ready_decision(tree_id=TREE_ID)
    assert decision.production_ready is False
    assert decision.outcome == DecisionOutcome.NOT_PRODUCTION_READY.value
    assert decision.decision_cid
    assert decision.signature
    assert not decision.is_pass()


def test_empty_bundle_fails_closed() -> None:
    empty = ReleaseEvidenceBundle(tree_id=TREE_ID)
    decision = evaluate_release_evidence(
        empty,
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
        signing_key=SIGNING_KEY,
    )
    assert decision.production_ready is False
    assert decision.outcome == DecisionOutcome.FAIL.value
    codes = _blocker_codes(decision)
    assert BlockerCode.MISSING_GOAL_RECEIPT.value in codes
    assert BlockerCode.MISSING_DOD_CLAUSE.value in codes
    assert BlockerCode.MISSING_CORPUS_SIGNOFF.value in codes
    assert BlockerCode.MISSING_UCAN_NEGATIVE.value in codes
    assert BlockerCode.ABSENT_SOAK.value in codes
    assert BlockerCode.ABSENT_CHAOS.value in codes
    assert BlockerCode.MISSING_ENVIRONMENT.value in codes


def test_none_bundle_is_not_production_ready() -> None:
    decision = evaluate_release_evidence(
        None, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert is_production_ready(decision) is False
    assert BlockerCode.MISSING_BUNDLE.value in _blocker_codes(decision)


# ---------------------------------------------------------------------------
# Happy path: complete fresh evidence
# ---------------------------------------------------------------------------


def test_complete_fresh_bundle_passes_and_is_production_ready() -> None:
    bundle = _passing_bundle()
    decision = evaluate_release_evidence(
        bundle,
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
        signing_key=SIGNING_KEY,
    )
    assert decision.outcome == DecisionOutcome.PASS.value
    assert decision.production_ready is True
    assert decision.is_pass()
    assert is_production_ready(decision) is True
    assert decision.satisfied_child_goals == REQUIRED_CHILD_GOALS
    assert set(decision.satisfied_dod_clauses) == set(ROOT_DOD_CLAUSE_IDS)
    assert not decision.blockers
    assert decision.decision_cid.startswith("kg-rel1-")
    assert decision.signature.startswith("hmac-sha256:")
    assert decision.bundle_digest.startswith("sha256:")
    assert decision.schema_version == DECISION_SCHEMA_VERSION
    assert verify_decision_signature(decision, signing_key=SIGNING_KEY)


def test_graph_release_gate_facade_evaluate_and_raise() -> None:
    gate = GraphReleaseGate(
        expected_tree_id=TREE_ID,
        signing_key=SIGNING_KEY,
        package_version="0.1.0",
    )
    standing = gate.standing_decision()
    assert gate.is_production_ready(standing) is False

    decision = gate.evaluate(_passing_bundle(), now=FIXED_NOW)
    assert gate.is_production_ready(decision) is True
    assert gate.last_decision is decision

    ok = gate.evaluate_or_raise(_passing_bundle(), now=FIXED_NOW)
    assert ok.is_pass()

    with pytest.raises(ReleaseGateFailClosed) as excinfo:
        gate.evaluate_or_raise(ReleaseEvidenceBundle(tree_id=TREE_ID), now=FIXED_NOW)
    assert excinfo.value.decision is not None
    assert excinfo.value.decision.production_ready is False


def test_gate_requires_expected_tree_id() -> None:
    with pytest.raises(ReleaseGateError):
        GraphReleaseGate(expected_tree_id="")


def test_content_addressed_decision_without_operator_key() -> None:
    decision = evaluate_release_evidence(
        _passing_bundle(),
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
        signing_key=None,
    )
    assert decision.is_pass()
    assert decision.signature.startswith("content-addressed:")
    assert decision.decision_cid == content_cid(
        # Recompute via decision body path: cid is stable across re-eval
        # when inputs match.
        decision._body_for_addressing(),
        domain=rg.SIGNATURE_DOMAIN,
    )


# ---------------------------------------------------------------------------
# Rejected substitutes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    sorted(
        {
            "task_status",
            "coverage",
            "prose",
            "optional_dependency_skip",
            "sample_only_corpus",
            "absent_soak_chaos",
            "missing_ucan_negative_proof",
            "unknown_environment",
            "line_coverage",
            "narrative",
            "skip",
            "documentation_only",
        }
    ),
)
def test_rejected_substitute_goal_evidence_fails(kind: str) -> None:
    bundle = _passing_bundle()
    # Replace G010 with a substitute "receipt".
    others = [r for r in bundle.goal_receipts if r.goal_id != "KGP-G010"]
    bad = make_goal_receipt(
        "KGP-G010",
        tree_id=TREE_ID,
        collected_at=_ts(),
        evidence_kind=kind,
        status="pass",
    )
    bundle.goal_receipts = others + [bad]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert decision.production_ready is False
    assert BlockerCode.REJECTED_SUBSTITUTE.value in _blocker_codes(decision)
    assert "KGP-G010" in _subjects_for(
        decision, BlockerCode.REJECTED_SUBSTITUTE.value
    )


def test_task_status_alone_never_passes_gate() -> None:
    """A bundle that only claims backlog task status must fail closed."""

    receipts = [
        GoalReceipt(
            goal_id=goal_id,
            tree_id=TREE_ID,
            status="complete",
            collected_at=_ts(),
            evidence_kind="task_status",
            notes="backlog says done",
        )
        for goal_id in REQUIRED_CHILD_GOALS
    ]
    bundle = ReleaseEvidenceBundle(tree_id=TREE_ID, goal_receipts=receipts)
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert decision.production_ready is False
    assert BlockerCode.REJECTED_SUBSTITUTE.value in _blocker_codes(decision)


def test_coverage_prose_optional_skip_rejected_on_dod() -> None:
    bundle = _passing_bundle()
    others = [
        r for r in bundle.dod_receipts if r.clause_id != "four_surface_parity"
    ]
    bad = make_dod_receipt(
        "four_surface_parity",
        tree_id=TREE_ID,
        collected_at=_ts(),
        evidence_kind="coverage",
    )
    bundle.dod_receipts = others + [bad]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.REJECTED_SUBSTITUTE.value in _blocker_codes(decision)


# ---------------------------------------------------------------------------
# Missing / skipped / partial / stale / foreign / contradicted
# ---------------------------------------------------------------------------


def test_missing_single_goal_receipt_fails() -> None:
    bundle = _passing_bundle()
    bundle.goal_receipts = [
        r for r in bundle.goal_receipts if r.goal_id != "KGP-G050"
    ]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.MISSING_GOAL_RECEIPT.value in _blocker_codes(decision)
    assert "KGP-G050" in _subjects_for(
        decision, BlockerCode.MISSING_GOAL_RECEIPT.value
    )
    assert "KGP-G050" not in decision.satisfied_child_goals


def test_skipped_goal_receipt_fails() -> None:
    bundle = _passing_bundle()
    others = [r for r in bundle.goal_receipts if r.goal_id != "KGP-G030"]
    skipped = make_goal_receipt(
        "KGP-G030",
        tree_id=TREE_ID,
        collected_at=_ts(),
        status="skipped",
        notes="optional dependency unavailable",
    )
    bundle.goal_receipts = others + [skipped]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.SKIPPED_RECEIPT.value in _blocker_codes(decision)


def test_stale_receipt_fails() -> None:
    stale_at = FIXED_NOW - DEFAULT_MAX_RECEIPT_AGE - timedelta(days=1)
    bundle = _passing_bundle()
    others = [r for r in bundle.goal_receipts if r.goal_id != "KGP-G020"]
    stale = make_goal_receipt(
        "KGP-G020",
        tree_id=TREE_ID,
        collected_at=_ts(stale_at),
    )
    bundle.goal_receipts = others + [stale]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.STALE_RECEIPT.value in _blocker_codes(decision)


def test_foreign_tree_receipt_fails() -> None:
    bundle = _passing_bundle()
    others = [r for r in bundle.goal_receipts if r.goal_id != "KGP-G070"]
    foreign = make_goal_receipt(
        "KGP-G070",
        tree_id=FOREIGN_TREE,
        collected_at=_ts(),
    )
    bundle.goal_receipts = others + [foreign]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.FOREIGN_TREE.value in _blocker_codes(decision)


def test_bundle_foreign_tree_fails() -> None:
    bundle = build_passing_bundle(tree_id=FOREIGN_TREE, now=FIXED_NOW)
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.FOREIGN_TREE.value in _blocker_codes(decision)


def test_contradicted_digest_fails() -> None:
    bundle = _passing_bundle()
    good = next(r for r in bundle.goal_receipts if r.goal_id == "KGP-G010")
    tampered = GoalReceipt(
        goal_id=good.goal_id,
        tree_id=good.tree_id,
        status=good.status,
        collected_at=good.collected_at,
        evidence_kind=good.evidence_kind,
        validation_command=good.validation_command,
        receipt_digest="sha256:" + "0" * 64,
        notes=good.notes,
    )
    others = [r for r in bundle.goal_receipts if r.goal_id != "KGP-G010"]
    bundle.goal_receipts = others + [tampered]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.CONTRADICTED_EVIDENCE.value in _blocker_codes(decision)


def test_partial_dod_missing_clause_fails() -> None:
    bundle = _passing_bundle()
    bundle.dod_receipts = [
        r
        for r in bundle.dod_receipts
        if r.clause_id != "migration_reversible"
    ]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.MISSING_DOD_CLAUSE.value in _blocker_codes(decision)
    assert "migration_reversible" in _subjects_for(
        decision, BlockerCode.MISSING_DOD_CLAUSE.value
    )


def test_non_passing_status_fails() -> None:
    bundle = _passing_bundle()
    others = [r for r in bundle.goal_receipts if r.goal_id != "KGP-G090"]
    failed = make_goal_receipt(
        "KGP-G090",
        tree_id=TREE_ID,
        collected_at=_ts(),
        status="failed",
    )
    bundle.goal_receipts = others + [failed]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.NOT_PASSING.value in _blocker_codes(decision)


# ---------------------------------------------------------------------------
# Corpus sign-off
# ---------------------------------------------------------------------------


def test_missing_corpus_signoff_fails() -> None:
    bundle = _passing_bundle()
    bundle.corpus_signoffs = [
        s for s in bundle.corpus_signoffs if s.corpus_id != "cvefixes"
    ]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.MISSING_CORPUS_SIGNOFF.value in _blocker_codes(decision)


def test_sample_only_corpus_signoff_rejected() -> None:
    bundle = _passing_bundle()
    others = [s for s in bundle.corpus_signoffs if s.corpus_id != "skillcenter"]
    sample = make_corpus_signoff(
        "skillcenter",
        tree_id=TREE_ID,
        producer_id="producer-skillcenter",
        signer="owner-skillcenter",
        mode="sample",
        signed_at=_ts(),
    )
    bundle.corpus_signoffs = others + [sample]
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.SAMPLE_ONLY_CORPUS.value in _blocker_codes(decision)


# ---------------------------------------------------------------------------
# UCAN negative / soak / chaos / environment
# ---------------------------------------------------------------------------


def test_missing_ucan_negative_proof_fails() -> None:
    bundle = _passing_bundle()
    bundle.ucan_negative = None
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.MISSING_UCAN_NEGATIVE.value in _blocker_codes(decision)


def test_empty_deny_receipt_cids_fails() -> None:
    bundle = _passing_bundle()
    bundle.ucan_negative = UCANNegativeProof(
        tree_id=TREE_ID,
        deny_receipt_cids=(),
        collected_at=_ts(),
    )
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.MISSING_UCAN_NEGATIVE.value in _blocker_codes(decision)


def test_absent_soak_fails() -> None:
    bundle = _passing_bundle()
    assert bundle.soak_chaos is not None
    bundle.soak_chaos = SoakChaosEvidence(
        tree_id=TREE_ID,
        environment_id="lab-kg-release-1",
        soak_receipt_digest="",
        chaos_receipt_digest="sha256:" + "d" * 64,
        collected_at=_ts(),
    )
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.ABSENT_SOAK.value in _blocker_codes(decision)


def test_absent_chaos_fails() -> None:
    bundle = _passing_bundle()
    assert bundle.soak_chaos is not None
    bundle.soak_chaos = SoakChaosEvidence(
        tree_id=TREE_ID,
        environment_id="lab-kg-release-1",
        soak_receipt_digest="sha256:" + "c" * 64,
        chaos_receipt_digest="",
        collected_at=_ts(),
    )
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.ABSENT_CHAOS.value in _blocker_codes(decision)


def test_absent_soak_chaos_entirely_fails() -> None:
    bundle = _passing_bundle()
    bundle.soak_chaos = None
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    codes = _blocker_codes(decision)
    assert BlockerCode.ABSENT_SOAK.value in codes
    assert BlockerCode.ABSENT_CHAOS.value in codes


def test_unknown_environment_fails() -> None:
    assert is_unknown_environment("unknown")
    assert is_unknown_environment("")
    assert is_unknown_environment(None)

    bundle = _passing_bundle()
    bundle.environment = EnvironmentBinding(
        environment_id="unknown",
        label="unknown",
        tree_id=TREE_ID,
        collected_at=_ts(),
    )
    # Keep soak/chaos consistent with unknown env so both surfaces fail closed.
    bundle.soak_chaos = SoakChaosEvidence(
        tree_id=TREE_ID,
        environment_id="unknown",
        soak_receipt_digest="sha256:" + "c" * 64,
        chaos_receipt_digest="sha256:" + "d" * 64,
        collected_at=_ts(),
    )
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert not decision.production_ready
    assert BlockerCode.UNKNOWN_ENVIRONMENT.value in _blocker_codes(decision)


def test_missing_environment_fails() -> None:
    bundle = _passing_bundle()
    bundle.environment = None
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert BlockerCode.MISSING_ENVIRONMENT.value in _blocker_codes(decision)


# ---------------------------------------------------------------------------
# Signing / content addressing invariants
# ---------------------------------------------------------------------------


def test_sign_and_verify_roundtrip() -> None:
    decision = evaluate_release_evidence(
        _passing_bundle(),
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
        signing_key=None,
    )
    signed = sign_decision(decision, signing_key=SIGNING_KEY)
    assert signed.signature.startswith("hmac-sha256:")
    assert verify_decision_signature(signed, signing_key=SIGNING_KEY)
    assert not verify_decision_signature(signed, signing_key=b"wrong-key")


def test_empty_signing_key_rejected() -> None:
    decision = evaluate_release_evidence(
        _passing_bundle(),
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
    )
    with pytest.raises(ReleaseGateError):
        sign_decision(decision, signing_key=b"")


def test_decision_cid_deterministic_for_same_inputs() -> None:
    d1 = evaluate_release_evidence(
        _passing_bundle(),
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
        signing_key=SIGNING_KEY,
    )
    d2 = evaluate_release_evidence(
        _passing_bundle(),
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
        signing_key=SIGNING_KEY,
    )
    assert d1.decision_cid == d2.decision_cid
    assert d1.bundle_digest == d2.bundle_digest
    assert d1.signature == d2.signature


def test_content_address_domain_bound() -> None:
    payload = {"a": 1, "b": [2, 3]}
    a = content_address(payload, domain="domain-a")
    b = content_address(payload, domain="domain-b")
    assert a != b
    assert a.startswith("sha256:")


def test_bundle_roundtrip_from_mapping() -> None:
    original = _passing_bundle()
    restored = ReleaseEvidenceBundle.from_mapping(original.to_dict())
    assert restored.tree_id == original.tree_id
    assert len(restored.goal_receipts) == len(original.goal_receipts)
    assert len(restored.dod_receipts) == len(original.dod_receipts)
    assert len(restored.corpus_signoffs) == len(original.corpus_signoffs)
    assert restored.content_digest() == original.content_digest()

    decision = evaluate_release_evidence(
        restored,
        expected_tree_id=TREE_ID,
        now=FIXED_NOW,
        signing_key=SIGNING_KEY,
    )
    assert decision.is_pass()


def test_schema_mismatch_fails() -> None:
    bundle = _passing_bundle()
    bundle.schema_version = "kg-release-evidence-bundle/v0-old"
    decision = evaluate_release_evidence(
        bundle, expected_tree_id=TREE_ID, now=FIXED_NOW
    )
    assert BlockerCode.SCHEMA_MISMATCH.value in _blocker_codes(decision)
    assert not decision.production_ready


def test_accepted_evidence_kinds_non_empty_and_disjoint_from_rejects() -> None:
    assert ACCEPTED_EVIDENCE_KINDS
    assert ACCEPTED_EVIDENCE_KINDS.isdisjoint(REJECTED_SUBSTITUTES)


def test_receipt_helpers_produce_valid_digests() -> None:
    goal = make_goal_receipt("KGP-G010", tree_id=TREE_ID, collected_at=_ts())
    assert goal.receipt_digest == goal.compute_digest()
    dod = make_dod_receipt(
        "four_surface_parity", tree_id=TREE_ID, collected_at=_ts()
    )
    assert dod.receipt_digest == dod.compute_digest()
    signoff = make_corpus_signoff(
        "cvefixes",
        tree_id=TREE_ID,
        producer_id="p",
        signer="s",
        signed_at=_ts(),
    )
    assert signoff.receipt_digest == signoff.compute_digest()
    assert isinstance(goal, GoalReceipt)
    assert isinstance(dod, DodClauseReceipt)
    assert isinstance(signoff, CorpusSignOff)


def test_decision_to_dict_includes_blockers_and_cid() -> None:
    decision = evaluate_release_evidence(
        None, expected_tree_id=TREE_ID, now=FIXED_NOW, signing_key=SIGNING_KEY
    )
    payload = decision.to_dict()
    assert payload["decision_cid"] == decision.decision_cid
    assert payload["signature"] == decision.signature
    assert payload["production_ready"] is False
    assert isinstance(payload["blockers"], list)
    assert payload["schema_version"] == DECISION_SCHEMA_VERSION
    assert payload["required_child_goals"] == list(REQUIRED_CHILD_GOALS)


def test_bundle_schema_version_constant() -> None:
    assert BUNDLE_SCHEMA_VERSION == "kg-release-evidence-bundle/v1"
    assert SCHEMA_VERSION == "kg-release-gate/v1"
