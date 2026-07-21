"""Unit coverage for selective Leanstral audit routing policy."""

from __future__ import annotations

from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LeanstralAuditWorkerConfig,
    canonical_sha256,
    plan_leanstral_audit_work_items,
)
from ipfs_datasets_py.logic.modal.leanstral_audit_policy import (
    LeanstralAuditPolicyConfig,
    LeanstralAuditPolicyOutcome,
    leanstral_policy_report_with_cache_hits,
    select_informative_leanstral_audit_clusters,
)


def _cluster(
    cluster_id: str,
    family: str,
    surface: str,
    *,
    recurrence: int = 1,
    impact: float = 0.04,
    confidence: float = 0.9,
    severity: float = 0.4,
    mean_score: float = 0.02,
    rank: float = 0.1,
    evidence_id: str | None = None,
    gaps: list[dict] | None = None,
) -> dict:
    evidence_id = evidence_id or f"evidence-{cluster_id}"
    return {
        "cluster_id": cluster_id,
        "compiler_surface": surface,
        "confidence": confidence,
        "evidence_ids": [evidence_id],
        "formal_severity": severity,
        "gaps": gaps
        if gaps is not None
        else [
            {
                "evidence_id": evidence_id,
                "gap_kind": "semantic_family_gap",
                "source_key": "legal_ir_views.predicted_family",
            }
        ],
        "heldout_impact": impact,
        "mean_normalized_score": mean_score,
        "owned_code_paths": ["ipfs_datasets_py/logic/modal/codec.py"],
        "rank_score": rank,
        "recurrence": recurrence,
        "semantic_family": family,
        "semantic_signature": f"{family}:{cluster_id}",
    }


def _record(
    evidence_id: str,
    *,
    state_hash: str = "state-a",
    proof_status: dict | None = None,
) -> dict:
    return {
        "evidence_hashes": {"state_hash": state_hash},
        "evidence_id": evidence_id,
        "legal_ir_views": {
            "predicted": {"family_distribution": {"deontic": 0.52, "temporal": 0.48}}
        },
        "proof_route_status": proof_status
        if proof_status is not None
        else {"attempted_count": 0, "route_status": ""},
        "run_context": {"compiler_commit": "commit-a", "state_hash": state_hash},
        "sample_hashes": {
            "modal_ir_hash": canonical_sha256({"modal": evidence_id}),
            "sample_id": f"sample-{evidence_id}",
            "source_text_hash": canonical_sha256({"source": evidence_id}),
        },
        "schema_version": "legal-ir-introspection-packet-v1",
    }


def test_policy_selects_only_informative_unresolved_owned_gaps() -> None:
    clusters = [
        _cluster("recurrent", "deontic", "deontic.ir", recurrence=3),
        _cluster("severe", "temporal", "modal.temporal", severity=0.92),
        _cluster("uncertain", "frame_logic", "modal.frame_logic", confidence=0.50),
        _cluster(
            "hammer",
            "prover",
            "external_provers.router",
            evidence_id="evidence-hammer",
            gaps=[
                {
                    "evidence_id": "evidence-hammer",
                    "gap_kind": "formal_prover_gap",
                    "source_key": "proof_route_status.failure_ratio",
                }
            ],
        ),
        _cluster("noise", "decompiler", "modal.ir_decompiler"),
        _cluster(
            "solved",
            "prover",
            "external_provers.router",
            evidence_id="evidence-solved",
            gaps=[
                {
                    "evidence_id": "evidence-solved",
                    "gap_kind": "formal_prover_gap",
                    "source_key": "proof_route_status.failure_ratio",
                }
            ],
        ),
        _cluster("unowned", "deontic", "outside.compiler", severity=0.95),
    ]
    records = {
        "evidence-hammer": _record(
            "evidence-hammer",
            proof_status={
                "attempted_count": 1,
                "failure_count": 1,
                "route_status": "failed",
                "valid_count": 0,
            },
        ),
        "evidence-solved": _record(
            "evidence-solved",
            proof_status={
                "attempted_count": 1,
                "failure_count": 0,
                "route_status": "compiled",
                "valid_count": 1,
            },
        ),
    }

    report = select_informative_leanstral_audit_clusters(
        clusters,
        records_by_evidence_id=records,
        config=LeanstralAuditPolicyConfig(max_selected_per_family=10),
    )
    decisions = {decision.candidate_id: decision for decision in report.decisions}

    assert report.selected_count == 4
    assert decisions["recurrent"].triggers == ("recurrent",)
    assert decisions["severe"].triggers == ("high_severity",)
    assert "high_uncertainty" in decisions["uncertain"].triggers
    assert "hammer_unsolved" in decisions["hammer"].triggers
    assert decisions["noise"].outcome == LeanstralAuditPolicyOutcome.MARGINAL_VALUE
    assert decisions["solved"].outcome == LeanstralAuditPolicyOutcome.SKIPPED
    assert decisions["solved"].reason == "solved_obligation"
    assert decisions["unowned"].reason == "unowned_compiler_surface"
    assert report.to_dict()["outcome_counts"]["marginal_value"] == 1


def test_policy_enforces_fair_family_budget_and_exhaustion() -> None:
    clusters = [
        _cluster(f"d{index}", "deontic", "deontic.ir", severity=0.95)
        for index in range(3)
    ] + [_cluster("temporal", "temporal", "modal.temporal", severity=0.95)]

    report = select_informative_leanstral_audit_clusters(
        clusters,
        config=LeanstralAuditPolicyConfig(max_selected_per_family=2),
    )
    decisions = {decision.candidate_id: decision for decision in report.decisions}

    assert report.family_selection_counts == {"deontic": 2, "temporal": 1}
    assert decisions["d0"].outcome == LeanstralAuditPolicyOutcome.SELECTED
    assert decisions["d1"].outcome == LeanstralAuditPolicyOutcome.SELECTED
    assert decisions["d2"].outcome == LeanstralAuditPolicyOutcome.ABSTAINED
    assert decisions["d2"].reason == "family_budget_exhausted"

    exhausted = select_informative_leanstral_audit_clusters(
        [_cluster("done", "deontic", "deontic.ir", severity=0.95)],
        config=LeanstralAuditPolicyConfig(exhausted_families=("deontic",)),
    )

    assert exhausted.decisions[0].outcome == LeanstralAuditPolicyOutcome.ABSTAINED
    assert exhausted.decisions[0].reason == "family_exhausted"


def test_policy_reports_cache_hits_without_consuming_family_budget() -> None:
    report = select_informative_leanstral_audit_clusters(
        [
            _cluster("cached", "deontic", "deontic.ir", severity=0.95),
            _cluster("fresh", "deontic", "deontic.ir", severity=0.95),
        ],
        config=LeanstralAuditPolicyConfig(max_selected_per_family=2),
    )

    cached = leanstral_policy_report_with_cache_hits(report, ("cached",))
    decisions = {decision.candidate_id: decision for decision in cached.decisions}

    assert cached.cached_count == 1
    assert cached.selected_count == 1
    assert cached.family_selection_counts == {"deontic": 1}
    assert decisions["cached"].outcome == LeanstralAuditPolicyOutcome.CACHED
    assert decisions["fresh"].family_budget_used == 1


def test_policy_marks_stale_snapshot_when_expected_state_is_absent() -> None:
    report = select_informative_leanstral_audit_clusters(
        [_cluster("stale", "deontic", "deontic.ir", severity=0.95)],
        records_by_evidence_id={
            "evidence-stale": _record("evidence-stale", state_hash="old-state")
        },
        config=LeanstralAuditPolicyConfig(expected_state_hash="current-state"),
    )

    assert report.stale_count == 1
    assert report.decisions[0].outcome == LeanstralAuditPolicyOutcome.STALE


def _packet(index: int, *, component: str = "deontic") -> dict:
    evidence_id = f"evidence-{index:03d}"
    sample_id = f"sample-{index:03d}"
    modal_hash = canonical_sha256({"modal": sample_id})
    return {
        "compiler_decompiler_metrics": {"cross_entropy_loss": 0.31, "cosine_similarity": 0.7},
        "evidence_hashes": {
            "canonical_modal_ir_hash": modal_hash,
            "state_hash": "state-a",
        },
        "evidence_id": evidence_id,
        "legal_ir_component_gaps": {f"{component}.obligation_scope": 0.42},
        "legal_ir_views": {
            "canonical": {"family_distribution": {"deontic": 1.0}, "modal_ir_hash": modal_hash},
            "predicted": {"family_distribution": {"temporal": 0.8}, "predicted_family": "temporal", "target_family": "deontic"},
        },
        "proof_route_status": {
            "attempted_count": 1,
            "compiles": True,
            "route_status": "compiled",
            "valid_count": 1,
        },
        "run_context": {
            "compiler_commit": "commit-a",
            "cycle": index,
            "evaluation_role": "guided",
            "sample_role": "holdout",
            "state_hash": "state-a",
        },
        "sample_hashes": {
            "modal_ir_hash": modal_hash,
            "normalized_text_hash": canonical_sha256({"normalized": sample_id}),
            "sample_id": sample_id,
            "source_text_hash": canonical_sha256({"source": sample_id}),
        },
        "schema_version": "legal-ir-introspection-packet-v1",
    }


def test_work_item_planner_embeds_policy_decision_report() -> None:
    items, stale, report = plan_leanstral_audit_work_items(
        [_packet(1)],
        config=LeanstralAuditWorkerConfig(cache_dir=None),
    )

    assert stale == []
    assert len(items) == 1
    assert report["selected_count"] == 1
    assert report["outcome_counts"]["selected"] == 1
    decision = items[0].cluster["leanstral_audit_policy"]
    assert decision["outcome"] == "selected"
    assert "high_severity" in decision["triggers"]
