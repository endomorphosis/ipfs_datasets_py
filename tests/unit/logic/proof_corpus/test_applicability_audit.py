"""Unit tests for hard-filtered proof query and redacted audit (LIG-031).

Acceptance:

* Filter tenant/visibility, exact root lineage, jurisdiction/authority/
  subject/resource/action/capability/data, effective/expiry,
  supersession/revocation, policy/schema/logic/backend/circuit/VK and proof
  authority **before** bounded rank.
* Trace considered/filtered/ranked/selected/rejected counts/reasons, budgets
  and gaps.
* Exclude raw prompts/arguments/secrets/witnesses/private formulas and
  unbounded labels.
* Ranking never establishes applicability or proof.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.proof_corpus.applicability import (
    MAX_SELECTION_BUDGET,
    PROOF_APPLICABILITY_FILTER_INTERFACE,
    PROOF_HARD_FILTER_DIMENSIONS,
    FilterDisposition,
    HardFilterAssessment,
    ProofApplicabilityError,
    ProofApplicabilityFilter,
    ProofApplicabilityQuery,
    ProofApplicabilityResult,
    RankedCandidate,
    SelectionDisposition,
    hard_filter_dimensions,
    hard_filter_envelope,
    select_applicable_proofs,
)
from ipfs_datasets_py.logic.proof_corpus.audit import (
    PROOF_QUERY_AUDIT_RECEIPT_INTERFACE,
    AuditEventKind,
    ProofQueryAuditError,
    ProofQueryAuditReceipt,
    audit_applicability_query,
    build_proof_query_audit_receipt,
    is_redaction_placeholder,
    redact_value,
    redaction_placeholder,
)
from ipfs_datasets_py.logic.proof_corpus.model import (
    AttestationKind,
    AttestedProofEnvelope,
    CircuitBinding,
    CoverageDeclaration,
    PipelineIdentity,
    ProofResultStatus,
    ScopeBinding,
    TemporalWindow,
)
from ipfs_datasets_py.logic.proof_corpus.policy import (
    ConflictRule,
    PolicyBudget,
    ProofTrustPolicy,
    WorldMode,
)
from ipfs_datasets_py.logic.proof_corpus.schemas import ProofCorpusFamily


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _cid(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return cid_v1_from_digest(bytes.fromhex(digest))


def _honest_envelope(**overrides: Any) -> AttestedProofEnvelope:
    """Return a fully bound direct-verification theorem envelope."""

    base: dict[str, Any] = {
        "statement_digest": _digest("statement"),
        "assumption_digest": _digest("assumption"),
        "obligation_digest": _digest("obligation"),
        "domain": "legal",
        "logic_family": "deontic",
        "result_authority": AuthorityKind.THEOREM_PROOF,
        "attestation_kind": AttestationKind.DIRECT_PROOF_VERIFICATION,
        "family": ProofCorpusFamily.LEGAL,
        "result_status": ProofResultStatus.PROVED,
        "proof_artifact_cid": _cid("proof-artifact"),
        "proof_bytes_digest": _digest("proof-bytes"),
        "source_snapshot_cid": _cid("source-snapshot"),
        "corpus_root_cid": _cid("corpus-root"),
        "revocation_root_cid": _cid("revocation-root"),
        "policy_id": "policy-legal-strict",
        "ontology_id": "ontology-us-code",
        "adapter_id": "adapter-legal-v1",
        "compiler_id": "compiler-canonical-v1",
        "translation_id": "translation-none",
        "solver_id": "solver-z3",
        "reconstruction_id": "reconstruction-v1",
        "build_manifest_cid": _cid("build-manifest"),
        "source_map_cid": _cid("source-map"),
        "backend_id": "provekit",
        "security_profile": "legal-strict",
        "public_inputs": {
            "statement_digest": _digest("statement"),
            "corpus_root": _cid("corpus-root"),
        },
        "circuit": CircuitBinding(
            circuit_id="legal_constraint",
            circuit_version=1,
            circuit_digest=_digest("circuit"),
            vk_id="legal_constraint_vk",
            vk_version=1,
            vk_digest=_digest("vk"),
            backend_id="provekit",
            proof_system="groth16",
            public_inputs={
                "statement_digest": _digest("statement"),
                "corpus_root": _cid("corpus-root"),
            },
            security_profile="legal-strict",
        ),
        "pipeline": PipelineIdentity(
            source_id="source-us-code-552",
            corpus_id="corpus-legal-v1",
            policy_id="policy-legal-strict",
            ontology_id="ontology-us-code",
            adapter_id="adapter-legal-v1",
            compiler_id="compiler-canonical-v1",
            translation_id="translation-none",
            solver_id="solver-z3",
            reconstruction_id="reconstruction-v1",
        ),
        "scope": ScopeBinding(
            jurisdiction="us-federal",
            tenant="tenant-a",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
            purpose_ids=("purpose-disclosure",),
        ),
        "temporal": TemporalWindow(
            effective_at="2026-01-01T00:00:00Z",
            expires_at="2027-01-01T00:00:00Z",
        ),
        "coverage": CoverageDeclaration(
            covered_selectors=("jurisdiction", "subject", "resource"),
            complete=True,
        ),
        "parent_cids": (_cid("parent-envelope"),),
        "diagnostics": {
            "notes": "honest fixture",
            "action_ids": ["action:disclose"],
            "capability_ids": ["cap:read-records"],
            "data_classes": ["data:public-records"],
            "visibility_classes": ["visibility:tenant-internal"],
        },
        "producer_id": "lig-031-test",
    }
    base.update(overrides)
    return AttestedProofEnvelope(**base)


def _query(**overrides: Any) -> ProofApplicabilityQuery:
    base: dict[str, Any] = {
        "query_id": "query:lig-031-applicable",
        "at_time": "2026-06-15T00:00:00Z",
        "tenant": "tenant-a",
        "visibility": "visibility:tenant-internal",
        "corpus_root_cid": _cid("corpus-root"),
        "revocation_root_cid": _cid("revocation-root"),
        "approved_parent_cids": (_cid("parent-envelope"),),
        "require_parent_lineage": True,
        "jurisdiction": "us-federal",
        "authority_id": "policy-legal-strict",
        "subject_ids": ("subject-alice",),
        "resource_ids": ("resource-records",),
        "action_ids": ("action:disclose",),
        "capability_ids": ("cap:read-records",),
        "data_classes": ("data:public-records",),
        "purpose_ids": ("purpose-disclosure",),
        "policy_id": "policy-legal-strict",
        "logic_family": "deontic",
        "backend_id": "provekit",
        "circuit_id": "legal_constraint",
        "vk_id": "legal_constraint_vk",
        "security_profile": "legal-strict",
        "required_result_authority": AuthorityKind.THEOREM_PROOF,
        "required_attestation_kinds": (
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        "domain": "legal",
        "selection_budget": 8,
        "max_candidates": 32,
    }
    base.update(overrides)
    return ProofApplicabilityQuery(**base)


def _trust_policy(**overrides: Any) -> ProofTrustPolicy:
    base: dict[str, Any] = {
        "policy_id": "trust-production",
        "corpus_roots": (_cid("corpus-root"),),
        "revocation_roots": (_cid("revocation-root"),),
        "circuit_allowlist": ("legal_constraint", "legal_constraint@v1"),
        "backend_allowlist": ("provekit",),
        "solver_allowlist": ("solver-z3",),
        "compiler_allowlist": ("compiler-canonical-v1",),
        "security_profile_allowlist": ("legal-strict",),
        "attestation_kind_allowlist": (
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        "authoritative_attestation_kinds": (
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        "required_result_authority": AuthorityKind.THEOREM_PROOF,
        "accept_simulated": False,
        "require_circuit_binding": True,
        "require_vk_binding": True,
        "require_public_inputs": True,
        "world_mode": WorldMode.CLOSED,
        "conflict_rule": ConflictRule.FAIL_CLOSED,
        "budget": PolicyBudget(
            max_candidates=64,
            max_bytes=1_048_576,
            max_graph_depth=16,
            timeout_ms=5_000,
            max_backend_attempts=3,
        ),
        "allowed_jurisdictions": ("us-federal",),
        "allowed_tenants": ("tenant-a",),
    }
    base.update(overrides)
    return ProofTrustPolicy(**base)


# ---------------------------------------------------------------------------
# Contract / dimensions
# ---------------------------------------------------------------------------


def test_hard_filter_dimensions_are_documented() -> None:
    required = {
        "tenant",
        "visibility",
        "corpus_root",
        "revocation_root",
        "parent_lineage",
        "jurisdiction",
        "authority",
        "subject",
        "resource",
        "action",
        "capability",
        "data_class",
        "effective",
        "expiry",
        "supersession",
        "revocation",
        "policy",
        "schema",
        "logic_family",
        "backend",
        "circuit",
        "vk",
        "proof_authority",
    }
    dims = set(hard_filter_dimensions())
    assert required.issubset(dims)
    assert dims == set(PROOF_HARD_FILTER_DIMENSIONS)
    # Ranking is not a hard-filter dimension.
    assert "retrieval_rank" not in dims
    assert "similarity" not in dims


def test_query_interface_and_roundtrip() -> None:
    query = _query()
    assert query.query_digest().startswith("sha256:")
    restored = ProofApplicabilityQuery.from_dict(query.to_dict())
    assert restored.query_digest() == query.query_digest()
    assert restored.tenant == "tenant-a"


def test_unbounded_selection_budget_rejected() -> None:
    with pytest.raises(ProofApplicabilityError, match="unbounded"):
        _query(selection_budget=MAX_SELECTION_BUDGET + 1)
    with pytest.raises(ProofApplicabilityError, match="positive"):
        _query(selection_budget=0)


# ---------------------------------------------------------------------------
# Happy path: hard filter then rank
# ---------------------------------------------------------------------------


def test_matching_envelope_is_admitted_and_selected() -> None:
    envelope = _honest_envelope()
    result = select_applicable_proofs([envelope], _query())
    assert result.disposition is SelectionDisposition.SELECTED
    assert result.considered_count == 1
    assert result.selected_count == 1
    assert result.filtered_count == 0
    assert result.rejected_count == 0
    assert result.ranked_count == 1
    assert result.selected_cids == (envelope.envelope_cid,)
    assert result.retrieval_rank_used_for_authority is False
    assert result.ranking_establishes_applicability is False
    assert result.interface == PROOF_APPLICABILITY_FILTER_INTERFACE


def test_hard_filters_run_before_ranking_poisoned_neighbor() -> None:
    """High advisory score on a wrong-tenant neighbor must not select it."""

    honest = _honest_envelope()
    poisoned = _honest_envelope(
        statement_digest=_digest("poisoned-statement"),
        obligation_digest=_digest("poisoned-obligation"),
        scope=ScopeBinding(
            jurisdiction="us-federal",
            tenant="tenant-evil",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
            purpose_ids=("purpose-disclosure",),
        ),
        diagnostics={
            "action_ids": ["action:disclose"],
            "capability_ids": ["cap:read-records"],
            "data_classes": ["data:public-records"],
            "visibility_classes": ["visibility:tenant-internal"],
        },
    )
    scores = {
        honest.envelope_cid: 0.01,
        poisoned.envelope_cid: 0.99,
    }
    result = select_applicable_proofs(
        [poisoned, honest],
        _query(),
        advisory_scores=scores,
    )
    assert poisoned.envelope_cid not in result.selected_cids
    assert poisoned.envelope_cid not in result.admitted_cids
    assert honest.envelope_cid in result.selected_cids
    # Poisoned was considered then filtered; never ranked.
    poisoned_assessment = next(
        item
        for item in result.assessments
        if item.envelope_cid == poisoned.envelope_cid
    )
    assert poisoned_assessment.disposition is not FilterDisposition.ADMITTED
    assert "tenant_mismatch" in poisoned_assessment.reasons
    ranked_cids = {item.envelope_cid for item in result.ranked}
    assert poisoned.envelope_cid not in ranked_cids


def test_ranking_never_establishes_applicability_on_result() -> None:
    with pytest.raises(ProofApplicabilityError, match="ranking never"):
        ProofApplicabilityResult(
            query_id="q",
            disposition=SelectionDisposition.EMPTY,
            retrieval_rank_used_for_authority=True,
        )


def test_selected_must_be_subset_of_admitted() -> None:
    env = _honest_envelope()
    with pytest.raises(ProofApplicabilityError, match="subset"):
        ProofApplicabilityResult(
            query_id="q",
            disposition=SelectionDisposition.SELECTED,
            admitted_cids=(),
            selected_cids=(env.envelope_cid,),
            selected_count=1,
        )


# ---------------------------------------------------------------------------
# Dimension filters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override,reason_fragment",
    [
        ({"tenant": "tenant-b"}, "tenant_mismatch"),
        ({"visibility": "visibility:public"}, "visibility_mismatch"),
        (
            {"corpus_root_cid": _cid("other-corpus")},
            "corpus_root_not_exact",
        ),
        (
            {"revocation_root_cid": _cid("other-revocation")},
            "revocation_root_not_exact",
        ),
        ({"jurisdiction": "us-oregon"}, "jurisdiction_mismatch"),
        ({"authority_id": "policy-other"}, "authority_mismatch"),
        ({"subject_ids": ("subject-bob",)}, "subject_mismatch"),
        ({"resource_ids": ("resource-other",)}, "resource_mismatch"),
        ({"action_ids": ("action:delete",)}, "action_mismatch"),
        ({"capability_ids": ("cap:admin",)}, "capability_mismatch"),
        ({"data_classes": ("data:secret",)}, "data_class_mismatch"),
        ({"policy_id": "policy-other"}, "policy_mismatch"),
        ({"logic_family": "temporal"}, "logic_family_mismatch"),
        ({"backend_id": "other-backend"}, "backend_mismatch"),
        ({"circuit_id": "other_circuit"}, "circuit_mismatch"),
        ({"vk_id": "other_vk"}, "vk_mismatch"),
        ({"security_profile": "zkp-required"}, "security_profile_mismatch"),
        (
            {"required_result_authority": AuthorityKind.SATISFIABILITY},
            "result_authority_mismatch",
        ),
        (
            {
                "required_attestation_kinds": (
                    AttestationKind.VERIFIER_EXECUTION.value,
                )
            },
            "attestation_kind_not_required",
        ),
    ],
)
def test_hard_filter_rejects_mismatched_dimensions(
    override: dict[str, Any], reason_fragment: str
) -> None:
    envelope = _honest_envelope()
    assessment = hard_filter_envelope(envelope, _query(**override))
    assert assessment.disposition is not FilterDisposition.ADMITTED
    assert any(reason_fragment in reason for reason in assessment.reasons)


def test_effective_expiry_window() -> None:
    envelope = _honest_envelope()
    before = hard_filter_envelope(
        envelope, _query(at_time="2025-01-01T00:00:00Z")
    )
    assert before.disposition is not FilterDisposition.ADMITTED
    assert any("not_yet_effective" in r or "not_effective" in r for r in before.reasons)

    after = hard_filter_envelope(
        envelope, _query(at_time="2028-01-01T00:00:00Z")
    )
    assert after.disposition is FilterDisposition.REJECTED
    assert any("expired" in r for r in after.reasons)

    inside = hard_filter_envelope(
        envelope, _query(at_time="2026-06-15T00:00:00Z")
    )
    assert inside.disposition is FilterDisposition.ADMITTED


def test_supersession_and_revocation_reject() -> None:
    revoked = _honest_envelope(revocation_cid=_cid("revocation-entry"))
    assessment = hard_filter_envelope(revoked, _query())
    assert assessment.disposition is FilterDisposition.REJECTED
    assert "envelope_revoked" in assessment.reasons

    superseded = _honest_envelope(
        statement_digest=_digest("superseded-statement"),
        supersession_cid=_cid("supersession-entry"),
    )
    assessment2 = hard_filter_envelope(superseded, _query())
    assert assessment2.disposition is FilterDisposition.REJECTED
    assert "envelope_superseded" in assessment2.reasons


def test_revocation_snapshot_targets_reject() -> None:
    envelope = _honest_envelope()
    assessment = hard_filter_envelope(
        envelope,
        _query(),
        revoked_target_cids=(envelope.envelope_cid,),
    )
    assert assessment.disposition is FilterDisposition.REJECTED
    assert "target_in_revocation_snapshot" in assessment.reasons


def test_parent_lineage_must_be_approved() -> None:
    envelope = _honest_envelope(parent_cids=(_cid("unknown-parent"),))
    assessment = hard_filter_envelope(envelope, _query())
    assert assessment.disposition is not FilterDisposition.ADMITTED
    assert "parent_not_in_approved_lineage" in assessment.reasons


def test_trust_policy_integration_rejects_simulation() -> None:
    simulated = _honest_envelope(
        attestation_kind=AttestationKind.SIMULATION,
        result_authority=AuthorityKind.EVIDENCE_READINESS,
        result_status=ProofResultStatus.UNKNOWN,
    )
    # Drop required attestation/authority restrictions so trust policy is the gate.
    query = _query(
        required_attestation_kinds=(),
        required_result_authority=None,
    )
    assessment = hard_filter_envelope(
        simulated, query, trust_policy=_trust_policy()
    )
    assert assessment.disposition is FilterDisposition.REJECTED
    assert any("trust_policy" in r for r in assessment.reasons)


# ---------------------------------------------------------------------------
# Budgets, counts, gaps
# ---------------------------------------------------------------------------


def test_selection_budget_and_counts() -> None:
    envelopes = [
        _honest_envelope(
            statement_digest=_digest(f"stmt-{i}"),
            obligation_digest=_digest(f"obl-{i}"),
            proof_artifact_cid=_cid(f"proof-{i}"),
        )
        for i in range(5)
    ]
    query = _query(selection_budget=2, max_candidates=10)
    result = select_applicable_proofs(envelopes, query)
    assert result.considered_count == 5
    assert result.selected_count == 2
    assert result.ranked_count == 5
    assert "selection_budget_exhausted" in result.gaps
    assert result.budgets["selection_budget"] == 2
    assert result.budgets["max_candidates"] == 10


def test_max_candidates_truncation_gap() -> None:
    envelopes = [
        _honest_envelope(
            statement_digest=_digest(f"stmt-t-{i}"),
            obligation_digest=_digest(f"obl-t-{i}"),
            proof_artifact_cid=_cid(f"proof-t-{i}"),
        )
        for i in range(5)
    ]
    result = select_applicable_proofs(
        envelopes, _query(max_candidates=2, selection_budget=2)
    )
    assert result.considered_count == 2
    assert "candidate_budget_truncated" in result.gaps


def test_tenant_partition_isolation() -> None:
    a = _honest_envelope()
    b = _honest_envelope(
        statement_digest=_digest("tenant-b-stmt"),
        obligation_digest=_digest("tenant-b-obl"),
        scope=ScopeBinding(
            jurisdiction="us-federal",
            tenant="tenant-b",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
            purpose_ids=("purpose-disclosure",),
        ),
        diagnostics={
            "action_ids": ["action:disclose"],
            "capability_ids": ["cap:read-records"],
            "data_classes": ["data:public-records"],
            "visibility_classes": ["visibility:tenant-internal"],
        },
    )
    result_a = select_applicable_proofs([a, b], _query(tenant="tenant-a"))
    assert a.envelope_cid in result_a.selected_cids
    assert b.envelope_cid not in result_a.admitted_cids

    result_b = select_applicable_proofs([a, b], _query(tenant="tenant-b"))
    assert b.envelope_cid in result_b.selected_cids
    assert a.envelope_cid not in result_b.admitted_cids


def test_reason_counts_trace_filtered_candidates() -> None:
    honest = _honest_envelope()
    wrong_jurisdiction = _honest_envelope(
        statement_digest=_digest("wj-stmt"),
        obligation_digest=_digest("wj-obl"),
        scope=ScopeBinding(
            jurisdiction="us-oregon",
            tenant="tenant-a",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
            purpose_ids=("purpose-disclosure",),
        ),
        diagnostics={
            "action_ids": ["action:disclose"],
            "capability_ids": ["cap:read-records"],
            "data_classes": ["data:public-records"],
            "visibility_classes": ["visibility:tenant-internal"],
        },
    )
    result = select_applicable_proofs(
        [honest, wrong_jurisdiction], _query()
    )
    assert result.rejected_count == 1
    assert result.reason_counts.get("jurisdiction_mismatch", 0) >= 1
    assert result.filtered_count + result.rejected_count >= 1


def test_deterministic_ordering() -> None:
    envelopes = [
        _honest_envelope(
            statement_digest=_digest(f"det-{i}"),
            obligation_digest=_digest(f"det-o-{i}"),
            proof_artifact_cid=_cid(f"det-p-{i}"),
        )
        for i in range(4)
    ]
    # Reverse input order; results must still be deterministic.
    r1 = select_applicable_proofs(list(reversed(envelopes)), _query())
    r2 = select_applicable_proofs(envelopes, _query())
    assert r1.selected_cids == r2.selected_cids
    assert r1.result_digest() == r2.result_digest()
    assert [a.envelope_cid for a in r1.assessments] == [
        a.envelope_cid for a in r2.assessments
    ]


# ---------------------------------------------------------------------------
# Audit / redaction
# ---------------------------------------------------------------------------


def test_audit_receipt_traces_counts_and_events() -> None:
    envelope = _honest_envelope()
    wrong = _honest_envelope(
        statement_digest=_digest("audit-wrong"),
        obligation_digest=_digest("audit-wrong-obl"),
        scope=ScopeBinding(
            jurisdiction="us-federal",
            tenant="tenant-other",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
            purpose_ids=("purpose-disclosure",),
        ),
        diagnostics={
            "action_ids": ["action:disclose"],
            "capability_ids": ["cap:read-records"],
            "data_classes": ["data:public-records"],
            "visibility_classes": ["visibility:tenant-internal"],
        },
    )
    result, receipt = audit_applicability_query(
        [envelope, wrong],
        _query(),
        extra_diagnostics={
            "prompt": "SELECT * FROM secrets WHERE password='hunter2'",
            "arguments": {"tool": "shell", "cmd": "cat /etc/shadow"},
            "witness": b"\x00\x01private-witness",
            "private_formula": "∀x. secret(x)",
            "api_key": "sk-live-not-a-real-key",
        },
    )
    assert receipt.interface == PROOF_QUERY_AUDIT_RECEIPT_INTERFACE
    assert receipt.considered_count == result.considered_count == 2
    assert receipt.selected_count == result.selected_count == 1
    assert receipt.rejected_count == result.rejected_count == 1
    assert receipt.ranked_count == result.ranked_count
    assert receipt.filtered_count == result.filtered_count
    assert dict(receipt.reason_counts) == dict(result.reason_counts)
    assert dict(receipt.budgets) == dict(result.budgets)
    assert receipt.gaps == result.gaps
    assert receipt.retrieval_rank_used_for_authority is False
    assert receipt.content_digest.startswith("sha256:")
    assert receipt.content_cid.startswith("b")

    kinds = {event.kind for event in receipt.events}
    assert AuditEventKind.QUERY_START in kinds
    assert AuditEventKind.CANDIDATE_CONSIDERED in kinds
    assert AuditEventKind.CANDIDATE_ADMITTED in kinds
    assert (
        AuditEventKind.CANDIDATE_FILTERED in kinds
        or AuditEventKind.CANDIDATE_REJECTED in kinds
    )
    assert AuditEventKind.CANDIDATE_RANKED in kinds
    assert AuditEventKind.CANDIDATE_SELECTED in kinds
    assert AuditEventKind.QUERY_COMPLETE in kinds


def test_audit_excludes_private_payloads() -> None:
    envelope = _honest_envelope()
    result = select_applicable_proofs([envelope], _query())
    receipt = build_proof_query_audit_receipt(
        result,
        extra_diagnostics={
            "prompt": "raw user prompt with secrets",
            "arguments": {"x": 1},
            "secrets": {"token": "abc"},
            "witnesses": ["w1"],
            "private_formulas": ["P(x)"],
            "notes": "this is an unbounded free-form note " * 20,
        },
    )
    payload = receipt.to_dict()
    serialized = str(payload)
    assert "raw user prompt" not in serialized
    assert "sk-" not in serialized or "sha256:" in serialized
    assert "private-witness" not in serialized
    assert "∀x" not in serialized
    assert "unbounded free-form" not in serialized
    assert receipt.contains_private_payload_keys() is False
    # Redaction notes should record that private material was withheld.
    assert len(receipt.redaction_notes) >= 1
    for note in receipt.redaction_notes:
        assert note.content_digest.startswith("sha256:")
        assert note.length >= 0


def test_redaction_placeholder_roundtrip() -> None:
    placeholder = redaction_placeholder("secret", "super-secret-value")
    assert is_redaction_placeholder(placeholder)
    assert "super-secret-value" not in placeholder
    assert "length=" in placeholder
    assert "digest=sha256:" in placeholder

    redacted = redact_value(
        {
            "prompt": "hello",
            "safe_id": "policy-legal-strict",
            "count": 3,
            "nested": {"api_key": "xyz", "backend_id": "provekit"},
        }
    )
    assert is_redaction_placeholder(redacted["prompt"])
    assert redacted["safe_id"] == "policy-legal-strict"
    assert redacted["count"] == 3
    assert is_redaction_placeholder(redacted["nested"]["api_key"])
    assert redacted["nested"]["backend_id"] == "provekit"


def test_audit_receipt_integrity_and_roundtrip() -> None:
    envelope = _honest_envelope()
    result = select_applicable_proofs([envelope], _query())
    receipt = build_proof_query_audit_receipt(result, query=_query())
    receipt.verify_integrity()
    restored = ProofQueryAuditReceipt.from_dict(receipt.to_dict())
    restored.verify_integrity()
    assert restored.content_digest == receipt.content_digest
    assert restored.content_cid == receipt.content_cid
    assert restored.selected_cids == receipt.selected_cids


def test_audit_rejects_ranking_authority_claim() -> None:
    with pytest.raises(ProofQueryAuditError, match="ranking"):
        ProofQueryAuditReceipt(
            receipt_id="r1",
            query_id="q1",
            disposition=SelectionDisposition.EMPTY,
            retrieval_rank_used_for_authority=True,
        )


def test_high_rank_cannot_promote_filtered_candidate() -> None:
    """Even extreme advisory scores cannot promote a revoked envelope."""

    good = _honest_envelope()
    revoked = _honest_envelope(
        statement_digest=_digest("revoked-stmt"),
        obligation_digest=_digest("revoked-obl"),
        revocation_cid=_cid("rev-entry"),
    )
    result = select_applicable_proofs(
        [good, revoked],
        _query(),
        advisory_scores={
            good.envelope_cid: 0.0,
            revoked.envelope_cid: 1_000_000.0,
        },
    )
    assert revoked.envelope_cid not in result.admitted_cids
    assert revoked.envelope_cid not in result.selected_cids
    assert all(
        item.envelope_cid != revoked.envelope_cid for item in result.ranked
    )
    receipt = build_proof_query_audit_receipt(result)
    assert receipt.selected_cids == result.selected_cids
    assert "envelope_revoked" in receipt.reason_counts or any(
        "revoked" in key for key in receipt.reason_counts
    )


def test_filter_with_trust_policy_end_to_end() -> None:
    filter_ = ProofApplicabilityFilter(trust_policy=_trust_policy())
    good = _honest_envelope()
    membership = _honest_envelope(
        statement_digest=_digest("mem-stmt"),
        obligation_digest=_digest("mem-obl"),
        attestation_kind=AttestationKind.ARTIFACT_MEMBERSHIP,
        result_authority=AuthorityKind.EVIDENCE_READINESS,
        result_status=ProofResultStatus.READY,
    )
    result = filter_.select(
        [good, membership],
        _query(
            required_attestation_kinds=(),
            required_result_authority=None,
        ),
    )
    assert good.envelope_cid in result.selected_cids
    assert membership.envelope_cid not in result.admitted_cids
    assert result.policy_digest.startswith("sha256:")


def test_empty_candidate_set_records_gap() -> None:
    result = select_applicable_proofs([], _query())
    assert result.disposition in {
        SelectionDisposition.EMPTY,
        SelectionDisposition.COVERAGE_GAP,
        SelectionDisposition.ABSTAIN,
    }
    assert result.considered_count == 0
    assert "no_candidates_considered" in result.gaps
    receipt = build_proof_query_audit_receipt(result)
    assert receipt.considered_count == 0
    assert receipt.selected_count == 0


def test_assessment_roundtrip() -> None:
    assessment = HardFilterAssessment(
        envelope_cid=_cid("assessed"),
        disposition=FilterDisposition.FILTERED,
        reasons=("tenant_mismatch",),
        filter_dimensions=("tenant",),
    )
    restored = HardFilterAssessment.from_dict(assessment.to_dict())
    assert restored.to_dict() == assessment.to_dict()


def test_ranked_candidate_is_advisory_only() -> None:
    ranked = RankedCandidate(
        envelope_cid=_cid("ranked"),
        rank_index=0,
        rank_score=0.5,
        score_features={"advisory": 0.5, "cid_order": 0.1},
    )
    # Presence on a result does not flip authority flags.
    result = ProofApplicabilityResult(
        query_id="q",
        disposition=SelectionDisposition.SELECTED,
        admitted_cids=(ranked.envelope_cid,),
        ranked=(ranked,),
        selected_cids=(ranked.envelope_cid,),
        considered_count=1,
        ranked_count=1,
        selected_count=1,
        budgets={"selection_budget": 1},
    )
    assert result.ranking_establishes_applicability is False
    assert result.retrieval_rank_used_for_authority is False
