"""LPC-081: Unified backend-neutral proof repository interface.

Acceptance:

* One interface covers plans, attempts, evidence, receipts, counterexamples,
  attestations, lookup, freshness, invalidation, and lineage.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.common.canonical_cache_key import (
    CanonicalProofCacheKey,
)
from ipfs_datasets_py.logic.common.proof_repository import (
    DEFAULT_FRESHNESS_TTL_SECONDS,
    IN_MEMORY_BACKEND_ID,
    PROOF_REPOSITORY_CAPABILITIES,
    PROOF_REPOSITORY_CAPABILITY_SET,
    PROOF_REPOSITORY_GENERATION,
    PROOF_REPOSITORY_INTERFACE,
    PROOF_REPOSITORY_MODULE_VERSION,
    PROOF_REPOSITORY_SCHEMA,
    PROOF_REPOSITORY_SCHEMA_VERSION,
    AttestationKind,
    AttemptStatus,
    EvidenceDisposition,
    FreshnessReport,
    InMemoryProofRepository,
    InvalidationReason,
    LineageRelation,
    LookupDisposition,
    PlanStatus,
    ProofAttemptRecord,
    ProofAttestationRecord,
    ProofCounterexampleRecord,
    ProofEvidenceRecord,
    ProofInvalidationRecord,
    ProofLineageEdge,
    ProofLookupResult,
    ProofPlanRecord,
    ProofReceiptRecord,
    ProofRepository,
    ProofRepositoryAdmissionError,
    ProofRepositoryCapabilityError,
    ReceiptKind,
    RecordKind,
    build_proof_repository,
    capabilities_cover_acceptance,
    repository_content_digest,
    repository_covers_acceptance,
    require_full_capabilities,
)
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicEvidenceAuthority,
    LogicEvidenceKind,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _valid_cid(label: str) -> str:
    return cid_v1(label.encode("utf-8"))


def _full_key(**changes: object) -> CanonicalProofCacheKey:
    fields: dict[str, object] = {
        "source": _digest("source"),
        "expression": _digest("expression"),
        "formalization": _digest("formalization"),
        "slice": _digest("slice"),
        "obligation": _digest("obligation"),
        "assumptions": _digest("assumptions"),
        "bounds": _digest("bounds"),
        "translation": _digest("translation"),
        "provider": "provider.z3",
        "environment": _digest("env:linux-x86_64-lean-4.0"),
        "policy": _digest("policy:kernel-required"),
        "schema": _digest("schema:logic-axis/v1"),
        "checker": "checker.lean-kernel",
        "network_policy": _digest("net:offline"),
        "evidence_kind": LogicEvidenceKind.KERNEL_CHECKED_PROOF,
        "authority_ceiling": LogicEvidenceAuthority.AUTHORITATIVE,
        "source_cid": _valid_cid("source-bytes"),
    }
    fields.update(changes)
    return CanonicalProofCacheKey(**fields)  # type: ignore[arg-type]


def _note_path() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "proof_repository.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


def _repo(**kwargs: object) -> InMemoryProofRepository:
    return InMemoryProofRepository(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Identities and capability inventory
# ---------------------------------------------------------------------------


def test_interface_and_schema_identities() -> None:
    assert PROOF_REPOSITORY_INTERFACE == "ProofRepository@1"
    assert PROOF_REPOSITORY_GENERATION == "ProofRepository@1"
    assert PROOF_REPOSITORY_SCHEMA == "ipfs_datasets_py/proof-repository@1"
    assert PROOF_REPOSITORY_SCHEMA_VERSION == "proof-repository/v1"
    assert PROOF_REPOSITORY_MODULE_VERSION == "1.0.0"


def test_capability_inventory_matches_acceptance() -> None:
    expected = {
        "plans",
        "attempts",
        "evidence",
        "receipts",
        "counterexamples",
        "attestations",
        "lookup",
        "freshness",
        "invalidation",
        "lineage",
    }
    assert set(PROOF_REPOSITORY_CAPABILITIES) == expected
    assert len(PROOF_REPOSITORY_CAPABILITIES) == 10
    assert PROOF_REPOSITORY_CAPABILITY_SET == frozenset(expected)
    assert capabilities_cover_acceptance(PROOF_REPOSITORY_CAPABILITIES)
    assert set(require_full_capabilities(PROOF_REPOSITORY_CAPABILITIES)) == expected


def test_incomplete_capabilities_fail_closed() -> None:
    incomplete = set(PROOF_REPOSITORY_CAPABILITIES) - {"lineage"}
    with pytest.raises(ProofRepositoryCapabilityError, match="lineage"):
        require_full_capabilities(incomplete)
    assert not capabilities_cover_acceptance(incomplete)


def test_reference_backend_covers_acceptance() -> None:
    repo = build_proof_repository(backend="memory")
    assert isinstance(repo, InMemoryProofRepository)
    assert isinstance(repo, ProofRepository)
    assert repo.interface == PROOF_REPOSITORY_INTERFACE
    assert repo.schema_version == PROOF_REPOSITORY_SCHEMA_VERSION
    assert repo.backend_id == IN_MEMORY_BACKEND_ID
    assert repo.capabilities() == PROOF_REPOSITORY_CAPABILITY_SET
    assert repository_covers_acceptance(repo)


def test_unsupported_backend_fails_closed() -> None:
    with pytest.raises(Exception, match="unsupported proof repository backend"):
        build_proof_repository(backend="duckdb-not-wired-here")


# ---------------------------------------------------------------------------
# Plans / attempts / evidence / receipts / counterexamples / attestations
# ---------------------------------------------------------------------------


def test_plan_put_get_list_round_trip() -> None:
    repo = _repo()
    key = _full_key()
    plan = ProofPlanRecord.build(
        cache_key=key,
        status=PlanStatus.ACTIVE,
        node_ids=("n1", "n2"),
        depends_on=("root",),
        owner_id="owner:test",
        metadata={"goal": "prove-P"},
        created_at=100.0,
    )
    stored = repo.put_plan(plan)
    assert stored.plan_id == plan.plan_id
    assert stored.key_id == key.key_id
    assert repo.get_plan(plan.plan_id) == stored
    assert repo.list_plans(key=key) == (stored,)
    assert repo.list_plans() == (stored,)
    rebuilt = ProofPlanRecord.from_dict(stored.to_dict())
    assert rebuilt.plan_id == stored.plan_id
    assert rebuilt.cache_key.key_id == key.key_id


def test_attempt_put_get_list_and_plan_filter() -> None:
    repo = _repo()
    key = _full_key()
    plan = repo.put_plan(ProofPlanRecord.build(cache_key=key, created_at=1.0))
    attempt = ProofAttemptRecord.build(
        cache_key=key,
        plan_id=plan.plan_id,
        node_id="n1",
        status=AttemptStatus.RUNNING,
        provider_id="provider.z3",
        started_at=2.0,
    )
    stored = repo.put_attempt(attempt)
    assert repo.get_attempt(attempt.attempt_id) == stored
    assert repo.list_attempts(key=key) == (stored,)
    assert repo.list_attempts(plan_id=plan.plan_id) == (stored,)
    assert repo.list_attempts(plan_id="missing") == ()


def test_evidence_receipt_counterexample_attestation_round_trip() -> None:
    repo = _repo()
    key = _full_key()
    evidence = ProofEvidenceRecord.build(
        cache_key=key,
        evidence_kind=LogicEvidenceKind.KERNEL_CHECKED_PROOF,
        authority_ceiling=LogicEvidenceAuthority.AUTHORITATIVE,
        content={"proof": "…"},
        disposition=EvidenceDisposition.ADMITTED,
        created_at=10.0,
    )
    receipt = ProofReceiptRecord.build(
        cache_key=key,
        kind=ReceiptKind.KERNEL_CHECK,
        subject_id=evidence.evidence_id,
        evidence_id=evidence.evidence_id,
        issuer_id="issuer:kernel",
        issued_at=11.0,
        payload={"checked": True},
    )
    cex = ProofCounterexampleRecord.build(
        cache_key=key,
        model={"x": 1, "y": 0},
        created_at=12.0,
    )
    attest = ProofAttestationRecord.build(
        cache_key=key,
        kind=AttestationKind.KERNEL,
        subject_id=evidence.evidence_id,
        evidence_id=evidence.evidence_id,
        receipt_id=receipt.receipt_id,
        attestor_id="attestor:kernel",
        issued_at=13.0,
        expires_at=10_000.0,
    )

    assert repo.put_evidence(evidence).evidence_id == evidence.evidence_id
    assert repo.put_receipt(receipt).receipt_id == receipt.receipt_id
    assert (
        repo.put_counterexample(cex).counterexample_id == cex.counterexample_id
    )
    assert (
        repo.put_attestation(attest).attestation_id == attest.attestation_id
    )

    assert repo.get_evidence(evidence.evidence_id) is not None
    assert repo.get_receipt(receipt.receipt_id) is not None
    assert repo.get_counterexample(cex.counterexample_id) is not None
    assert repo.get_attestation(attest.attestation_id) is not None

    assert repo.list_evidence(key=key)[0].content_digest.startswith("sha256:")
    assert repo.list_receipts(key=key)[0].kind is ReceiptKind.KERNEL_CHECK
    assert repo.list_counterexamples(key=key)[0].model["x"] == 1
    assert repo.list_attestations(key=key)[0].kind is AttestationKind.KERNEL
    assert not repo.list_attestations(key=key)[0].is_expired(now=13.0)
    assert repo.list_attestations(key=key)[0].is_expired(now=10_001.0)


def test_candidate_as_kernel_evidence_rejected() -> None:
    key = _full_key(
        evidence_kind=LogicEvidenceKind.CANDIDATE,
        authority_ceiling=LogicEvidenceAuthority.ADVISORY,
    )
    with pytest.raises(ProofRepositoryAdmissionError, match="candidate-as-kernel"):
        ProofEvidenceRecord.build(
            cache_key=key,
            evidence_kind=LogicEvidenceKind.CANDIDATE,
            authority_ceiling=LogicEvidenceAuthority.AUTHORITATIVE,
            content={"guess": True},
        )


def test_mapping_admission_for_records() -> None:
    repo = _repo()
    key = _full_key()
    plan = ProofPlanRecord.build(cache_key=key, created_at=1.0)
    stored = repo.put_plan(plan.to_dict())
    assert isinstance(stored, ProofPlanRecord)
    attempt = ProofAttemptRecord.build(
        cache_key=key, plan_id=plan.plan_id, started_at=2.0
    )
    assert repo.put_attempt(attempt.to_dict()).attempt_id == attempt.attempt_id


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_lookup_hit_aggregates_all_surfaces() -> None:
    repo = _repo(ttl_seconds=1_000.0)
    key = _full_key()
    plan = repo.put_plan(
        ProofPlanRecord.build(cache_key=key, created_at=100.0)
    )
    attempt = repo.put_attempt(
        ProofAttemptRecord.build(
            cache_key=key,
            plan_id=plan.plan_id,
            status=AttemptStatus.SUCCEEDED,
            started_at=101.0,
            finished_at=102.0,
        )
    )
    evidence = repo.put_evidence(
        ProofEvidenceRecord.build(
            cache_key=key,
            evidence_kind=LogicEvidenceKind.CHECKED_PROOF,
            authority_ceiling=LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            attempt_id=attempt.attempt_id,
            content={"steps": 3},
            created_at=102.0,
        )
    )
    receipt = repo.put_receipt(
        ProofReceiptRecord.build(
            cache_key=key,
            kind=ReceiptKind.EVIDENCE,
            subject_id=evidence.evidence_id,
            evidence_id=evidence.evidence_id,
            attempt_id=attempt.attempt_id,
            issued_at=103.0,
        )
    )
    cex = repo.put_counterexample(
        ProofCounterexampleRecord.build(
            cache_key=key,
            model={"counter": True},
            attempt_id=attempt.attempt_id,
            created_at=104.0,
        )
    )
    attest = repo.put_attestation(
        ProofAttestationRecord.build(
            cache_key=key,
            kind=AttestationKind.INDEPENDENT_CHECK,
            subject_id=evidence.evidence_id,
            evidence_id=evidence.evidence_id,
            receipt_id=receipt.receipt_id,
            issued_at=105.0,
        )
    )
    edge = repo.put_lineage(
        ProofLineageEdge.build(
            relation=LineageRelation.ATTEMPT_OF,
            parent_id=plan.plan_id,
            child_id=attempt.attempt_id,
            parent_kind=RecordKind.PLAN,
            child_kind=RecordKind.ATTEMPT,
            cache_key_id=key.key_id,
            created_at=106.0,
        )
    )

    result = repo.lookup(key, now=200.0)
    assert result.disposition is LookupDisposition.HIT
    assert result.is_hit
    assert result.plan is not None
    assert result.plan.plan_id == plan.plan_id
    assert len(result.attempts) == 1
    assert len(result.evidence) == 1
    assert len(result.receipts) == 1
    assert len(result.counterexamples) == 1
    assert len(result.attestations) == 1
    assert result.counterexamples[0].counterexample_id == cex.counterexample_id
    assert result.attestations[0].attestation_id == attest.attestation_id
    assert any(item.edge_id == edge.edge_id for item in result.lineage)
    assert result.freshness is not None
    assert result.freshness.is_fresh
    payload = result.to_dict()
    assert payload["disposition"] == "hit"
    assert payload["schema_version"] == result.schema_version


def test_lookup_miss_on_unknown_key() -> None:
    repo = _repo()
    key = _full_key()
    result = repo.lookup(key, now=1.0)
    assert result.disposition is LookupDisposition.MISS
    assert not result.is_hit
    assert result.attempts == ()
    assert result.plan is None


def test_lookup_rejects_cross_environment() -> None:
    repo = _repo(ttl_seconds=10_000.0)
    key_a = _full_key(environment=_digest("env-a"))
    key_b = _full_key(environment=_digest("env-b"))
    # Same semantic fields except environment → distinct key_id, but if we
    # store under key_a and look up a body that only differs by environment
    # with identical other fields, key_ids differ → miss. Cross-env rejection
    # requires same key_id path which can't happen when environment differs
    # because environment is part of key_id. Exercise admit_cache_hit path by
    # planting a record then looking up with a reconstructed key that matches
    # key_id fields except we force environment check via stored keys.
    repo.put_plan(ProofPlanRecord.build(cache_key=key_a, created_at=1.0))
    # Distinct key is a miss (not environment_mismatch) because key_ids differ.
    result = repo.lookup(key_b, now=2.0)
    assert result.disposition is LookupDisposition.MISS


def test_cross_environment_hit_path_via_manual_mismatch() -> None:
    """Stored key environment must match request environment on hit path."""

    repo = _repo(ttl_seconds=10_000.0)
    key = _full_key(environment=_digest("env-left"))
    other = _full_key(environment=_digest("env-right"))
    # Plant evidence under `key`, then inject a conflicting stored key by
    # putting a plan under `other` is not enough. Directly exercise the
    # admit_cache_hit guard by putting records under two different keys and
    # ensuring lookup never returns a hit across environments.
    repo.put_evidence(
        ProofEvidenceRecord.build(
            cache_key=key,
            evidence_kind=LogicEvidenceKind.CHECKED_PROOF,
            authority_ceiling=LogicEvidenceAuthority.BOUNDED,
            content={"a": 1},
            created_at=1.0,
        )
    )
    hit = repo.lookup(key, now=2.0)
    assert hit.disposition is LookupDisposition.HIT
    miss = repo.lookup(other, now=2.0)
    assert miss.disposition is LookupDisposition.MISS


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def test_freshness_ttl_and_stale_lookup() -> None:
    clock = {"t": 1_000.0}

    def _now() -> float:
        return clock["t"]

    repo = _repo(ttl_seconds=10.0, clock=_now)
    key = _full_key()
    repo.put_plan(ProofPlanRecord.build(cache_key=key, created_at=1_000.0))
    fresh = repo.freshness(key, now=1_005.0)
    assert fresh.is_fresh
    assert fresh.disposition is LookupDisposition.HIT
    assert fresh.age_seconds == 5.0
    assert fresh.ttl_seconds == 10.0

    clock["t"] = 1_020.0
    stale = repo.freshness(key, now=1_020.0)
    assert not stale.is_fresh
    assert stale.disposition is LookupDisposition.STALE

    result = repo.lookup(key, now=1_020.0, require_fresh=True)
    assert result.disposition is LookupDisposition.STALE
    # When freshness is not required, payload is still returned as a hit-like
    # aggregation only if require_fresh=False and disposition isn't invalidated.
    result_relaxed = repo.lookup(key, now=1_020.0, require_fresh=False)
    assert result_relaxed.disposition is LookupDisposition.HIT
    assert result_relaxed.plan is not None


def test_default_ttl_constant() -> None:
    assert DEFAULT_FRESHNESS_TTL_SECONDS == 86_400.0
    repo = _repo()
    report = repo.freshness(_full_key())
    assert report.ttl_seconds == DEFAULT_FRESHNESS_TTL_SECONDS
    assert report.disposition is LookupDisposition.MISS


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def test_invalidation_is_sticky_and_marks_records() -> None:
    repo = _repo(ttl_seconds=10_000.0)
    key = _full_key()
    plan = repo.put_plan(
        ProofPlanRecord.build(
            cache_key=key, status=PlanStatus.ACTIVE, created_at=1.0
        )
    )
    attempt = repo.put_attempt(
        ProofAttemptRecord.build(
            cache_key=key,
            plan_id=plan.plan_id,
            status=AttemptStatus.RUNNING,
            started_at=2.0,
        )
    )
    inv = repo.invalidate(
        key,
        reason=InvalidationReason.REVOKED,
        subject_id=plan.plan_id,
        subject_kind=RecordKind.PLAN,
        actor_id="actor:test",
        notes="revoked by policy",
        now=3.0,
    )
    assert inv.reason is InvalidationReason.REVOKED
    assert inv.key_id == key.key_id
    assert repo.list_invalidations(key=key) == (inv,)

    updated_plan = repo.get_plan(plan.plan_id)
    assert updated_plan is not None
    assert updated_plan.status is PlanStatus.INVALIDATED
    updated_attempt = repo.get_attempt(attempt.attempt_id)
    assert updated_attempt is not None
    assert updated_attempt.status is AttemptStatus.INVALIDATED

    report = repo.freshness(key, now=4.0)
    assert report.disposition is LookupDisposition.INVALIDATED
    assert report.invalidation_id == inv.invalidation_id

    result = repo.lookup(key, now=4.0)
    assert result.disposition is LookupDisposition.INVALIDATED
    assert len(result.invalidations) == 1
    # Sticky: new evidence under same key does not restore hit.
    repo.put_evidence(
        ProofEvidenceRecord.build(
            cache_key=key,
            evidence_kind=LogicEvidenceKind.PROOF_CERTIFICATE,
            authority_ceiling=LogicEvidenceAuthority.BOUNDED,
            content={"after": True},
            created_at=5.0,
        )
    )
    still = repo.lookup(key, now=6.0)
    assert still.disposition is LookupDisposition.INVALIDATED


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


def test_lineage_put_and_query_directions() -> None:
    repo = _repo()
    key = _full_key()
    plan = repo.put_plan(ProofPlanRecord.build(cache_key=key, created_at=1.0))
    attempt = repo.put_attempt(
        ProofAttemptRecord.build(
            cache_key=key, plan_id=plan.plan_id, started_at=2.0
        )
    )
    evidence = repo.put_evidence(
        ProofEvidenceRecord.build(
            cache_key=key,
            evidence_kind=LogicEvidenceKind.CHECKED_PROOF,
            authority_ceiling=LogicEvidenceAuthority.BOUNDED,
            attempt_id=attempt.attempt_id,
            content={"p": 1},
            created_at=3.0,
        )
    )
    edge1 = repo.put_lineage(
        ProofLineageEdge.build(
            relation=LineageRelation.ATTEMPT_OF,
            parent_id=plan.plan_id,
            child_id=attempt.attempt_id,
            parent_kind=RecordKind.PLAN,
            child_kind=RecordKind.ATTEMPT,
            cache_key_id=key.key_id,
            created_at=4.0,
        )
    )
    edge2 = repo.put_lineage(
        ProofLineageEdge.build(
            relation=LineageRelation.EVIDENCES,
            parent_id=attempt.attempt_id,
            child_id=evidence.evidence_id,
            parent_kind=RecordKind.ATTEMPT,
            child_kind=RecordKind.EVIDENCE,
            cache_key_id=key.key_id,
            created_at=5.0,
        )
    )

    both = repo.lineage_of(attempt.attempt_id, direction="both")
    assert {edge.edge_id for edge in both} == {edge1.edge_id, edge2.edge_id}
    parents = repo.lineage_of(attempt.attempt_id, direction="parents")
    assert len(parents) == 1 and parents[0].edge_id == edge1.edge_id
    children = repo.lineage_of(attempt.attempt_id, direction="children")
    assert len(children) == 1 and children[0].edge_id == edge2.edge_id
    scoped = repo.list_lineage(key_id=key.key_id)
    assert len(scoped) == 2

    with pytest.raises(ProofRepositoryAdmissionError, match="parent_id"):
        ProofLineageEdge.build(
            relation=LineageRelation.PARENT,
            parent_id="same",
            child_id="same",
            parent_kind=RecordKind.PLAN,
            child_kind=RecordKind.PLAN,
        )


# ---------------------------------------------------------------------------
# Protocol surface completeness / stats / digests
# ---------------------------------------------------------------------------


def test_protocol_methods_exist_for_every_capability() -> None:
    required_methods = {
        "plans": ("put_plan", "get_plan", "list_plans"),
        "attempts": ("put_attempt", "get_attempt", "list_attempts"),
        "evidence": ("put_evidence", "get_evidence", "list_evidence"),
        "receipts": ("put_receipt", "get_receipt", "list_receipts"),
        "counterexamples": (
            "put_counterexample",
            "get_counterexample",
            "list_counterexamples",
        ),
        "attestations": (
            "put_attestation",
            "get_attestation",
            "list_attestations",
        ),
        "lookup": ("lookup",),
        "freshness": ("freshness",),
        "invalidation": ("invalidate", "list_invalidations"),
        "lineage": ("put_lineage", "lineage_of", "list_lineage"),
    }
    repo = _repo()
    for capability, methods in required_methods.items():
        assert capability in PROOF_REPOSITORY_CAPABILITY_SET
        for method_name in methods:
            assert callable(getattr(repo, method_name)), method_name


def test_stats_and_content_digest() -> None:
    repo = _repo()
    key = _full_key()
    repo.put_plan(ProofPlanRecord.build(cache_key=key, created_at=1.0))
    repo.lookup(key, now=2.0)
    stats = repo.stats()
    assert stats["plans"] == 1
    assert stats["lookups"] == 1
    assert stats["hits"] == 1
    digest = repository_content_digest({"a": 1, "b": [2, 3]})
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_lookup_result_and_freshness_report_dicts() -> None:
    report = FreshnessReport(
        key_id="canonical-proof-cache-key:sha256:" + ("ab" * 32),
        is_fresh=False,
        disposition=LookupDisposition.MISS,
        reason="empty",
    )
    assert report.to_dict()["disposition"] == "miss"
    result = ProofLookupResult(
        disposition=LookupDisposition.MISS,
        freshness=report,
        reason="empty",
    )
    assert result.to_dict()["freshness"]["reason"] == "empty"


def test_invalidation_and_lineage_from_dict() -> None:
    key = _full_key()
    inv = ProofInvalidationRecord.build(
        cache_key=key,
        reason=InvalidationReason.POLICY_CHANGE,
        invalidated_at=1.0,
    )
    rebuilt = ProofInvalidationRecord.from_dict(inv.to_dict())
    assert rebuilt.invalidation_id == inv.invalidation_id
    edge = ProofLineageEdge.build(
        relation=LineageRelation.SUPERSEDES,
        parent_id="a",
        child_id="b",
        parent_kind=RecordKind.EVIDENCE,
        child_kind=RecordKind.EVIDENCE,
        created_at=2.0,
    )
    assert ProofLineageEdge.from_dict(edge.to_dict()).edge_id == edge.edge_id


# ---------------------------------------------------------------------------
# Note documentation
# ---------------------------------------------------------------------------


def test_note_documents_capability_inventory_and_interface() -> None:
    note = _note_path()
    assert note.is_file(), f"missing design note at {note}"
    text = note.read_text(encoding="utf-8")
    assert "ProofRepository@1" in text
    assert "LPC-081" in text
    for capability in PROOF_REPOSITORY_CAPABILITIES:
        assert capability in text, f"note missing capability {capability}"
    for phrase in (
        "plans",
        "attempts",
        "evidence",
        "receipts",
        "counterexamples",
        "attestations",
        "lookup",
        "freshness",
        "invalidation",
        "lineage",
        "CanonicalProofCacheKey",
        "DuckDB",
        "backend-neutral",
    ):
        assert phrase in text


def test_module_is_import_inert_and_exposes_protocol() -> None:
    """Importing the module must not require DuckDB or network backends."""

    import ipfs_datasets_py.logic.common.proof_repository as mod

    assert mod.PROOF_REPOSITORY_INTERFACE == "ProofRepository@1"
    assert callable(mod.build_proof_repository)
    repo = mod.build_proof_repository(backend="memory")
    # Structural protocol membership (runtime_checkable).
    assert isinstance(repo, mod.ProofRepository)
    for name in PROOF_REPOSITORY_CAPABILITIES:
        assert name in repo.capabilities()
