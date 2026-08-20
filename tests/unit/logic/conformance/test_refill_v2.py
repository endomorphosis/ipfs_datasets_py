"""Unit tests for ReachableGapScorer@1 / DerivedTaskAdmission@2 (LFP2-048)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.conformance.refill_v2 import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MAX_GOALS_PER_EPOCH,
    DEFAULT_MAX_OPEN_TASKS,
    DEFAULT_MAX_REFINEMENT_DEPTH,
    DEFAULT_MAX_TASKS_PER_EPOCH,
    DEFAULT_MAX_UNCHANGED_FAILURE_RETRIES,
    DEFAULT_PROTECTED_PATHS,
    DERIVED_TASK_ADMISSION_INTERFACE,
    DERIVED_TASK_ADMISSION_VERSION,
    GOAL_ID,
    IMMUTABLE_SEED_GOAL_COUNT,
    IMMUTABLE_SEED_GOALS,
    PROGRAM_ID,
    REACHABLE_GAP_SCORER_INTERFACE,
    REACHABLE_GAP_SCORER_VERSION,
    TASK_ID,
    AdmissionDisposition,
    DerivedTaskAdmission,
    EpochDisposition,
    GapKind,
    ReachableGapCandidate,
    ReachableGapScorer,
    RefillMemory,
    RefillPolicyV2,
    RefillV2AuthorityError,
    RefillV2BoundsError,
    ScanIdentity,
    count_derived_goals,
    is_seed_goal,
    is_unscoped_codebase_scope,
    is_vague_cleanup_text,
    run_admission_epoch,
    score_reachable_gap,
    score_reachable_gaps,
)


def _scan(
    *,
    source: str = "source:tree-a",
    config: str = "config:sched-a",
    corpus: str = "corpus:a",
) -> ScanIdentity:
    return ScanIdentity(
        source_identity=source,
        config_identity=config,
        corpus_identity=corpus,
        provider_identity="provider:sealed",
        registry_identity="registry:families",
        objective_identity="objective:LFP2-G090",
        tree_id="tree:a",
        repository_id="repository:lfp2",
    )


def _gap(
    gap_id: str,
    *,
    owner: str = "ipfs_datasets_py/ipfs_datasets_py/logic/parsers/fol.py",
    subject: str = "fol.parse",
    kind: GapKind = GapKind.PARSER_COUNTEREXAMPLE,
    owned_paths: tuple[str, ...] | None = None,
    depth: int = 1,
    attempt_count: int = 0,
    last_failure_fingerprint: str = "",
    last_attempt_epoch_s: int = 0,
    refill_eligible: bool = True,
    evidence_obligation: str = "parser_surface_with_parse_artifact",
    discovery_receipt: str = "discovery:receipt:001",
    content_identity: str = "",
    authority_ceiling: str = "none",
    validation_commands: tuple[str, ...] | None = None,
    dependencies: tuple[str, ...] = ("LFP2-005",),
    support_status: str = "native",
    route_disposition: str = "admitted",
    context_budget_bytes: int = 8_000,
    originating_goal_id: str = "LFP2-G090",
    evidence: str = "",
    metadata: dict | None = None,
) -> ReachableGapCandidate:
    paths = owned_paths
    if paths is None:
        paths = (owner,)
    commands = validation_commands
    if commands is None:
        commands = (
            "cd ipfs_datasets_py && python -m pytest -q "
            "tests/unit/logic/conformance/test_refill_v2.py",
        )
    return ReachableGapCandidate(
        gap_id=gap_id,
        gap_kind=kind,
        owner=owner,
        subject=subject,
        evidence_obligation=evidence_obligation,
        discovery_receipt=discovery_receipt,
        content_identity=content_identity,
        evidence=evidence or f"evidence-for-{gap_id}",
        originating_goal_id=originating_goal_id,
        owned_paths=paths,
        context_paths=paths,
        validation_commands=commands,
        dependencies=dependencies,
        depth=depth,
        attempt_count=attempt_count,
        last_failure_fingerprint=last_failure_fingerprint,
        last_attempt_epoch_s=last_attempt_epoch_s,
        refill_eligible=refill_eligible,
        family_id="classical_fol",
        authority_ceiling=authority_ceiling,
        support_status=support_status,
        route_disposition=route_disposition,
        context_budget_bytes=context_budget_bytes,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Interfaces / seed goals / policy invariants
# ---------------------------------------------------------------------------


def test_interfaces_and_task_identity() -> None:
    assert REACHABLE_GAP_SCORER_INTERFACE == "ReachableGapScorer@1"
    assert DERIVED_TASK_ADMISSION_INTERFACE == "DerivedTaskAdmission@2"
    assert REACHABLE_GAP_SCORER_VERSION == "1.0.0"
    assert DERIVED_TASK_ADMISSION_VERSION == "2.0.0"
    assert TASK_ID == "LFP2-048"
    assert GOAL_ID == "LFP2-G090"
    assert PROGRAM_ID == "ipfs-datasets-logic-family-parser-v2"
    scorer = ReachableGapScorer()
    assert scorer.interface == REACHABLE_GAP_SCORER_INTERFACE
    gate = DerivedTaskAdmission()
    assert gate.interface == DERIVED_TASK_ADMISSION_INTERFACE


def test_eleven_immutable_seed_goals() -> None:
    assert len(IMMUTABLE_SEED_GOALS) == IMMUTABLE_SEED_GOAL_COUNT == 11
    assert IMMUTABLE_SEED_GOALS[0] == "LFP2-G000"
    assert IMMUTABLE_SEED_GOALS[-1] == "LFP2-G100"
    for goal_id in IMMUTABLE_SEED_GOALS:
        assert is_seed_goal(goal_id)
    assert not is_seed_goal("LFP2-D-LFP2-G090-deadbeef")
    assert count_derived_goals(IMMUTABLE_SEED_GOALS) == 0
    assert count_derived_goals((*IMMUTABLE_SEED_GOALS, "LFP2-D-x")) == 1


def test_default_policy_matches_scheduler_bounds() -> None:
    policy = RefillPolicyV2.default()
    assert policy.max_goals_per_epoch == DEFAULT_MAX_GOALS_PER_EPOCH == 8
    assert policy.max_tasks_per_epoch == DEFAULT_MAX_TASKS_PER_EPOCH == 24
    assert policy.max_open_tasks == DEFAULT_MAX_OPEN_TASKS == 48
    assert policy.max_refinement_depth == DEFAULT_MAX_REFINEMENT_DEPTH == 3
    assert (
        policy.max_unchanged_failure_retries
        == DEFAULT_MAX_UNCHANGED_FAILURE_RETRIES
        == 2
    )
    assert policy.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS == 3600
    assert policy.mutate_seed_board is False
    assert policy.mutate_seed_objectives is False
    assert policy.seed_tasks_are_immutable is True
    assert policy.seed_goals_are_immutable is True
    assert policy.unscoped_codebase_refill_allowed is False
    assert policy.cartesian_unsupported_allowed is False
    assert policy.advisor_only_allowed is False
    assert policy.vague_cleanup_allowed is False
    payload = policy.to_dict()
    assert payload["seed_goals_excluded_from_derived_budget"] is True
    assert payload["immutable_seed_goal_count"] == 11
    assert "IPFS_DATASETS_LOGIC_FAMILY_PARSER_V2_PLAN.md" in str(
        DEFAULT_PROTECTED_PATHS
    )


def test_policy_rejects_seed_board_mutation() -> None:
    with pytest.raises(RefillV2AuthorityError):
        RefillPolicyV2(mutate_seed_board=True)
    with pytest.raises(RefillV2AuthorityError):
        RefillPolicyV2(mutate_seed_objectives=True)
    with pytest.raises(RefillV2AuthorityError):
        RefillPolicyV2(seed_tasks_are_immutable=False)
    with pytest.raises(RefillV2AuthorityError):
        RefillPolicyV2(seed_goals_are_immutable=False)


def test_policy_rejects_over_ceiling_bounds() -> None:
    with pytest.raises(RefillV2BoundsError):
        RefillPolicyV2(max_goals_per_epoch=9)
    with pytest.raises(RefillV2BoundsError):
        RefillPolicyV2(max_tasks_per_epoch=25)
    with pytest.raises(RefillV2BoundsError):
        RefillPolicyV2(max_open_tasks=49)


# ---------------------------------------------------------------------------
# Scoring — ReachableGapScorer@1
# ---------------------------------------------------------------------------


def test_score_is_deterministic_and_reproducible() -> None:
    gap = _gap("gap-score-1")
    first = score_reachable_gap(gap)
    second = score_reachable_gap(gap)
    assert first.content_identity == second.content_identity
    assert first.score_digest == second.score_digest
    assert first.priority == second.priority
    assert first.admissible is True
    assert first.interface == REACHABLE_GAP_SCORER_INTERFACE

    scorer = ReachableGapScorer()
    receipt = scorer.receipt([gap, _gap("gap-score-2", subject="other")])
    assert receipt["interface"] == REACHABLE_GAP_SCORER_INTERFACE
    assert receipt["admissible_count"] == 2
    assert receipt["completion_authority"] is False
    # Re-score order is stable by priority then gap_id.
    scores = score_reachable_gaps(
        [
            _gap("gap-z", subject="z", kind=GapKind.OTHER_REACHABLE),
            _gap("gap-a", subject="a", kind=GapKind.PARSER_COUNTEREXAMPLE),
        ]
    )
    assert scores[0].gap_id == "gap-a"
    assert scores[0].priority > scores[1].priority


def test_score_rejects_cartesian_unsupported() -> None:
    gap = _gap(
        "gap-cartesian",
        kind=GapKind.CARTESIAN_UNSUPPORTED,
        support_status="unsupported",
        route_disposition="excluded",
    )
    score = score_reachable_gap(gap)
    assert score.admissible is False
    assert "cartesian_unsupported" in score.rejection_reasons
    assert score.priority == 0


def test_score_rejects_advisor_only() -> None:
    by_kind = score_reachable_gap(_gap("gap-adv-k", kind=GapKind.ADVISOR_ONLY))
    assert by_kind.admissible is False
    assert "advisor_only" in by_kind.rejection_reasons

    by_ceiling = score_reachable_gap(
        _gap("gap-adv-c", authority_ceiling="advisory")
    )
    assert by_ceiling.admissible is False
    assert "advisor_only" in by_ceiling.rejection_reasons


def test_score_rejects_vague_cleanup() -> None:
    assert is_vague_cleanup_text("general cleanup of the codebase")
    gap = _gap(
        "gap-vague",
        subject="general cleanup of the codebase",
        kind=GapKind.VAGUE_CLEANUP,
    )
    score = score_reachable_gap(gap)
    assert score.admissible is False
    assert "vague_cleanup" in score.rejection_reasons

    by_text = score_reachable_gap(
        _gap(
            "gap-vague-text",
            subject="tech debt sweep",
            kind=GapKind.OTHER_REACHABLE,
        )
    )
    assert by_text.admissible is False
    assert "vague_cleanup" in by_text.rejection_reasons


# ---------------------------------------------------------------------------
# Admission — DerivedTaskAdmission@2 (reject before append)
# ---------------------------------------------------------------------------


def test_admits_owner_scoped_reachable_gap() -> None:
    gap = _gap("gap-001")
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert receipt.interface == DERIVED_TASK_ADMISSION_INTERFACE
    assert receipt.disposition is EpochDisposition.ADMITTED
    assert len(receipt.admitted_tasks) == 1
    task = receipt.admitted_tasks[0]
    assert task.gap_id == "gap-001"
    assert task.owned_paths == (gap.owner,)
    assert task.evidence_obligation == gap.evidence_obligation
    assert task.discovery_receipt == gap.discovery_receipt
    assert task.authority_ceiling == "none"
    assert task.to_dict()["completion_authority"] is False
    assert task.to_dict()["mutation_authority"] is False
    assert task.to_dict()["seed_board_edit"] is False
    assert not is_seed_goal(task.goal_id)
    assert receipt.seed_definitions_mutated is False
    assert all(not is_seed_goal(g) for g in receipt.derived_goal_ids)
    assert receipt.scores[0].admissible is True


def test_cartesian_unsupported_rejected_before_append() -> None:
    gap = _gap("gap-cart", kind=GapKind.CARTESIAN_UNSUPPORTED)
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert not receipt.admits_work
    assert receipt.decisions[0].disposition is AdmissionDisposition.CARTESIAN_REJECTED
    assert "cartesian_unsupported" in receipt.decisions[0].reason_codes


def test_advisor_only_rejected_before_append() -> None:
    gap = _gap("gap-adv", authority_ceiling="advisory")
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert not receipt.admits_work
    assert (
        receipt.decisions[0].disposition is AdmissionDisposition.ADVISOR_ONLY_REJECTED
    )


def test_vague_cleanup_rejected_before_append() -> None:
    gap = _gap("gap-clean", subject="codebase cleanup pass")
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert not receipt.admits_work
    assert (
        receipt.decisions[0].disposition
        is AdmissionDisposition.VAGUE_CLEANUP_REJECTED
    )


def test_duplicate_identity_rejected_on_second_epoch() -> None:
    gap = _gap("gap-dup")
    first = run_admission_epoch([gap], scan_identity=_scan())
    assert first.admits_work
    second = run_admission_epoch(
        [gap],
        scan_identity=_scan(),
        memory=first.memory,
    )
    assert not second.admits_work
    assert second.disposition is EpochDisposition.DUPLICATE_ONLY
    assert second.decisions[0].disposition is AdmissionDisposition.DUPLICATE


def test_unsafe_command_rejected_before_append() -> None:
    gap = _gap(
        "gap-unsafe",
        validation_commands=("rm -rf / && pytest",),
    )
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert not receipt.admits_work
    assert receipt.decisions[0].disposition is AdmissionDisposition.UNSAFE_REJECTED
    assert "unsafe_command" in receipt.decisions[0].reason_codes


def test_unsafe_kind_rejected_before_append() -> None:
    gap = _gap("gap-unsafe-kind", kind=GapKind.UNSAFE)
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert not receipt.admits_work
    assert receipt.decisions[0].disposition is AdmissionDisposition.UNSAFE_REJECTED


def test_protected_paths_rejected_before_append() -> None:
    protected = DEFAULT_PROTECTED_PATHS[1]  # V2 plan
    gap = _gap(
        "gap-protected",
        owner=protected,
        owned_paths=(protected,),
    )
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert not receipt.admits_work
    assert receipt.decisions[0].disposition is AdmissionDisposition.PROTECTED_REJECTED


def test_broad_unscoped_tasks_rejected_before_append() -> None:
    assert is_unscoped_codebase_scope(())
    assert is_unscoped_codebase_scope(("ipfs_datasets_py",))
    assert is_unscoped_codebase_scope(("**/*",))
    assert not is_unscoped_codebase_scope(
        ("ipfs_datasets_py/ipfs_datasets_py/logic/parsers/fol.py",)
    )

    gap = _gap(
        "gap-unscoped",
        owned_paths=("ipfs_datasets_py",),
        owner="ipfs_datasets_py",
    )
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert not receipt.admits_work
    assert receipt.decisions[0].disposition is AdmissionDisposition.BROAD_REJECTED


def test_missing_requirements_rejected_before_append() -> None:
    missing_evidence = _gap("gap-no-ev", evidence_obligation="")
    r1 = run_admission_epoch([missing_evidence], scan_identity=_scan())
    assert r1.decisions[0].disposition is AdmissionDisposition.MISSING_REQUIREMENT
    assert "missing_evidence_obligation" in r1.decisions[0].reason_codes

    missing_discovery = _gap("gap-no-disc", discovery_receipt="")
    r2 = run_admission_epoch([missing_discovery], scan_identity=_scan())
    assert r2.decisions[0].disposition is AdmissionDisposition.MISSING_REQUIREMENT
    assert "missing_discovery_receipt" in r2.decisions[0].reason_codes


def test_depth_limit_holds() -> None:
    gap = _gap("gap-deep", depth=4)
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert receipt.decisions[0].disposition is AdmissionDisposition.DEPTH_REJECTED


def test_unchanged_failure_retry_and_cooldown() -> None:
    fp = "sha256:" + "ab" * 32
    gap = _gap(
        "gap-retry",
        attempt_count=2,
        last_failure_fingerprint=fp,
        last_attempt_epoch_s=100,
    )
    memory = RefillMemory(
        attempt_counts={gap.identity_key: 2},
        last_failure_fingerprints={gap.identity_key: fp},
        last_attempt_epoch_s={gap.identity_key: 100},
        now_epoch_s=200,
    )
    exhausted = run_admission_epoch(
        [gap],
        scan_identity=_scan(),
        memory=memory,
        now_epoch_s=200,
    )
    assert exhausted.decisions[0].disposition is AdmissionDisposition.RETRY_EXHAUSTED

    gap2 = _gap(
        "gap-retry2",
        attempt_count=1,
        last_failure_fingerprint=fp,
        last_attempt_epoch_s=1000,
        subject="other-subject-for-unique-identity",
    )
    memory2 = RefillMemory(
        attempt_counts={gap2.identity_key: 1},
        last_failure_fingerprints={gap2.identity_key: fp},
        last_attempt_epoch_s={gap2.identity_key: 1000},
        now_epoch_s=1010,
    )
    cooled = run_admission_epoch(
        [gap2],
        scan_identity=_scan(),
        memory=memory2,
        now_epoch_s=1010,
    )
    assert cooled.decisions[0].disposition is AdmissionDisposition.COOLDOWN


def test_open_and_task_bounds_hold() -> None:
    policy = RefillPolicyV2(
        max_tasks_per_epoch=2,
        max_open_tasks=2,
        min_open_tasks=0,
    )
    gaps = [
        _gap(
            f"gap-bound-{index}",
            subject=f"subject-{index}",
            owner=f"ipfs_datasets_py/ipfs_datasets_py/logic/parsers/p{index}.py",
            owned_paths=(
                f"ipfs_datasets_py/ipfs_datasets_py/logic/parsers/p{index}.py",
            ),
        )
        for index in range(5)
    ]
    receipt = run_admission_epoch(gaps, scan_identity=_scan(), policy=policy)
    assert len(receipt.admitted_tasks) == 2
    rejected = [
        d
        for d in receipt.decisions
        if d.disposition is AdmissionDisposition.BOUND_REJECTED
    ]
    assert len(rejected) == 3

    memory = RefillMemory(open_task_count=2)
    ceiling = run_admission_epoch(
        gaps[:1],
        scan_identity=_scan(),
        policy=policy,
        memory=memory,
    )
    assert not ceiling.admits_work
    assert ceiling.decisions[0].disposition is AdmissionDisposition.BOUND_REJECTED
    assert "open_work_ceiling" in ceiling.decisions[0].reason_codes


def test_derived_goal_budget_excludes_seed_goals() -> None:
    policy = RefillPolicyV2(max_goals_per_epoch=2, max_tasks_per_epoch=24)
    gaps = [
        _gap(
            f"gap-goal-{index}",
            subject=f"goal-subject-{index}",
            owner=f"ipfs_datasets_py/ipfs_datasets_py/logic/families/f{index}.py",
            owned_paths=(
                f"ipfs_datasets_py/ipfs_datasets_py/logic/families/f{index}.py",
            ),
        )
        for index in range(4)
    ]
    receipt = run_admission_epoch(gaps, scan_identity=_scan(), policy=policy)
    assert len(receipt.derived_goal_ids) == 2
    assert count_derived_goals(receipt.derived_goal_ids) == 2
    assert all(not is_seed_goal(g) for g in receipt.derived_goal_ids)
    bound = [
        d
        for d in receipt.decisions
        if d.disposition is AdmissionDisposition.BOUND_REJECTED
        and "goal_bound" in d.reason_codes
    ]
    assert len(bound) == 2


def test_authority_claims_in_metadata_rejected() -> None:
    with pytest.raises(RefillV2AuthorityError):
        ReachableGapCandidate(
            gap_id="gap-auth",
            gap_kind=GapKind.OTHER_REACHABLE,
            owner="ipfs_datasets_py/ipfs_datasets_py/logic/api.py",
            subject="x",
            evidence_obligation="registry_or_matrix_declaration",
            discovery_receipt="discovery:x",
            owned_paths=("ipfs_datasets_py/ipfs_datasets_py/logic/api.py",),
            metadata={"completion_authority": True},
        )


def test_not_refill_eligible_skipped() -> None:
    gap = _gap("gap-no", refill_eligible=False)
    receipt = run_admission_epoch([gap], scan_identity=_scan())
    assert receipt.decisions[0].disposition is AdmissionDisposition.NOT_REFILL_ELIGIBLE
    assert not receipt.admits_work


def test_epoch_is_deterministic() -> None:
    gaps = [
        _gap("gap-z", subject="z", kind=GapKind.OTHER_REACHABLE),
        _gap(
            "gap-a",
            subject="a",
            kind=GapKind.PARSER_COUNTEREXAMPLE,
            owner="ipfs_datasets_py/ipfs_datasets_py/logic/parsers/modal.py",
            owned_paths=(
                "ipfs_datasets_py/ipfs_datasets_py/logic/parsers/modal.py",
            ),
        ),
    ]
    first = run_admission_epoch(gaps, scan_identity=_scan(), epoch_id="epoch-fixed")
    second = run_admission_epoch(gaps, scan_identity=_scan(), epoch_id="epoch-fixed")
    assert first.receipt_digest == second.receipt_digest
    assert [t.task_cid for t in first.admitted_tasks] == [
        t.task_cid for t in second.admitted_tasks
    ]
    # Higher priority (parser) admitted before lower priority.
    assert first.admitted_tasks[0].gap_id == "gap-a"
    shuffled = run_admission_epoch(
        list(reversed(gaps)),
        scan_identity=_scan(),
        epoch_id="epoch-fixed",
    )
    assert [t.gap_id for t in shuffled.admitted_tasks] == [
        t.gap_id for t in first.admitted_tasks
    ]
    assert shuffled.receipt_digest == first.receipt_digest


def test_gap_content_identity_stable() -> None:
    gap = _gap("gap-stable")
    assert gap.identity_key == gap.identity_key
    assert gap.derived_content_identity.startswith("sha256:")
    assert len(gap.derived_content_identity) == len("sha256:") + 64
    # Explicit content identity is preferred when provided.
    pinned = _gap("gap-pinned", content_identity="cid:explicit-1")
    assert pinned.identity_key == "cid:explicit-1"


def test_derived_task_admission_class_api() -> None:
    gate = DerivedTaskAdmission()
    receipt = gate.admit([_gap("gap-class")], scan_identity=_scan())
    assert receipt.admits_work
    assert receipt.to_dict()["interface"] == DERIVED_TASK_ADMISSION_INTERFACE
    assert receipt.to_dict()["version"] == DERIVED_TASK_ADMISSION_VERSION
    assert receipt.to_dict()["completion_authority"] is False


def test_empty_input_epoch_disposition() -> None:
    receipt = run_admission_epoch((), scan_identity=_scan())
    assert receipt.disposition is EpochDisposition.EMPTY_INPUT
    assert not receipt.admits_work


def test_seed_definitions_never_change_across_epochs() -> None:
    gaps = [
        _gap(
            f"gap-seed-{i}",
            subject=f"s{i}",
            owner=f"ipfs_datasets_py/ipfs_datasets_py/logic/conformance/x{i}.py",
            owned_paths=(
                f"ipfs_datasets_py/ipfs_datasets_py/logic/conformance/x{i}.py",
            ),
        )
        for i in range(3)
    ]
    receipt = run_admission_epoch(gaps, scan_identity=_scan())
    assert receipt.seed_definitions_mutated is False
    for goal_id in receipt.derived_goal_ids:
        assert goal_id not in IMMUTABLE_SEED_GOALS
    for task in receipt.admitted_tasks:
        assert task.goal_id not in IMMUTABLE_SEED_GOALS
        assert task.to_dict()["seed_board_edit"] is False


def test_mixed_population_rejects_bad_admits_good() -> None:
    """Only admissible reachable gaps append; all rejection classes stay out."""

    good = _gap("gap-good")
    cartesian = _gap("gap-cart", kind=GapKind.CARTESIAN_UNSUPPORTED)
    advisor = _gap("gap-adv", authority_ceiling="advisory")
    vague = _gap("gap-vague", subject="vague cleanup of modules")
    protected = _gap(
        "gap-prot",
        owner=DEFAULT_PROTECTED_PATHS[0],
        owned_paths=(DEFAULT_PROTECTED_PATHS[0],),
    )
    broad = _gap(
        "gap-broad",
        owner="docs",
        owned_paths=("docs",),
    )
    unsafe = _gap(
        "gap-unsafe",
        validation_commands=("sudo rm -rf /tmp/x",),
    )
    receipt = run_admission_epoch(
        [cartesian, advisor, vague, protected, broad, unsafe, good],
        scan_identity=_scan(),
    )
    assert len(receipt.admitted_tasks) == 1
    assert receipt.admitted_tasks[0].gap_id == "gap-good"
    dispositions = {d.gap_id: d.disposition for d in receipt.decisions}
    assert dispositions["gap-cart"] is AdmissionDisposition.CARTESIAN_REJECTED
    assert dispositions["gap-adv"] is AdmissionDisposition.ADVISOR_ONLY_REJECTED
    assert dispositions["gap-vague"] is AdmissionDisposition.VAGUE_CLEANUP_REJECTED
    assert dispositions["gap-prot"] is AdmissionDisposition.PROTECTED_REJECTED
    assert dispositions["gap-broad"] is AdmissionDisposition.BROAD_REJECTED
    assert dispositions["gap-unsafe"] is AdmissionDisposition.UNSAFE_REJECTED
    assert dispositions["gap-good"] is AdmissionDisposition.ADMITTED


def test_scan_identity_composite_is_deterministic() -> None:
    a = _scan()
    b = _scan()
    assert a.composite_digest == b.composite_digest
    assert a.matches(b)
    drifted = _scan(corpus="corpus:other")
    assert not a.matches(drifted)
    assert a.composite_digest != drifted.composite_digest
