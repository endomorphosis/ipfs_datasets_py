"""Unit tests for resumable full/delta US Code build orchestration (USCIR-030)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_build import (
    SCHEMA_VERSION,
    TASK_ID,
    BuildCheckpointError,
    BuildConfig,
    BuildMode,
    DecisionSource,
    GlobalRebuildKind,
    ResourceLimitError,
    ResourceLimits,
    SealError,
    UscodeBuildOrchestrator,
    WorkUnitStatus,
    assert_checkpoint_compatible,
    compute_seal,
    decide_global_rebuild,
    fixture_title_snapshots,
    load_checkpoint,
    plan_delta_build,
    plan_full_build,
    run_fixture_build,
    write_checkpoint_atomic,
)


TITLES = ("1", "35")
FAMILIES = ("corpus", "bm25", "vectors")


def test_config_digest_is_deterministic() -> None:
    a = BuildConfig(titles=TITLES, families=FAMILIES, notes="first")
    b = BuildConfig(titles=TITLES, families=FAMILIES, notes="second")
    assert a.digest == b.digest
    assert a.digest != BuildConfig(titles=("1",), families=FAMILIES).digest


def test_mutable_release_point_rejected() -> None:
    with pytest.raises(Exception):
        BuildConfig(release_point="latest", titles=TITLES)


def test_full_plan_builds_every_unit_and_forces_global_full() -> None:
    config = BuildConfig(mode=BuildMode.FULL, titles=TITLES, families=FAMILIES)
    plan = plan_full_build(config)
    assert plan.mode is BuildMode.FULL
    assert len(plan.units) == len(TITLES) * len(FAMILIES)
    assert all(u.action == "build" for u in plan.units)
    assert plan.global_decisions["bm25"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["vectors"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["bm25"].equivalent_to_full is True
    assert plan.global_decisions["vectors"].equivalent_to_full is True


def test_delta_plan_skips_unchanged_and_records_explicit_global_decisions() -> None:
    config = BuildConfig(
        mode=BuildMode.DELTA,
        titles=TITLES,
        families=FAMILIES,
        # One of two equal-weight titles changes → ratio 0.5. Keep thresholds
        # strictly above that so auto mode stays on delta_refresh (full rebuild
        # triggers when changed_ratio >= threshold).
        bm25_rebuild_threshold=0.6,
        cluster_rebuild_threshold=0.6,
    )
    prior = fixture_title_snapshots(TITLES, salt="prior")
    current = dict(prior)
    # Change only title 35.
    current["35"] = fixture_title_snapshots(("35",), salt="changed")["35"]
    plan = plan_delta_build(config, current=current, prior=prior)
    assert plan.mode is BuildMode.DELTA
    assert plan.changed_titles == ("35",)
    assert "1" in plan.unchanged_titles
    assert plan.changed_document_ratio == 0.5
    # corpus for title 1 should be reuse; title 35 build
    by_key = {u.key: u for u in plan.units}
    assert by_key["1/corpus"].action == "reuse"
    assert by_key["35/corpus"].action == "build"
    # Global decisions are present and explicit about non-equivalence when delta.
    bm25 = plan.global_decisions["bm25"]
    vectors = plan.global_decisions["vectors"]
    assert bm25.kind is GlobalRebuildKind.DELTA_REFRESH
    assert vectors.kind is GlobalRebuildKind.DELTA_REFRESH
    assert bm25.equivalent_to_full is False
    assert vectors.equivalent_to_full is False
    assert "NOT equivalent" in bm25.reason or "not" in bm25.proof


def test_delta_auto_full_rebuild_when_threshold_crossed() -> None:
    config = BuildConfig(
        mode=BuildMode.DELTA,
        titles=TITLES,
        families=FAMILIES,
        bm25_rebuild_threshold=0.10,
        cluster_rebuild_threshold=0.10,
    )
    prior = fixture_title_snapshots(TITLES, salt="prior")
    current = fixture_title_snapshots(TITLES, salt="all-changed")
    plan = plan_delta_build(config, current=current, prior=prior)
    assert plan.changed_document_ratio == 1.0
    assert plan.global_decisions["bm25"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["vectors"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["bm25"].equivalent_to_full is True
    # Full global rebuild means every title's global family is built.
    assert all(
        u.action == "build"
        for u in plan.units
        if u.family in {"bm25", "vectors"}
    )


def test_auto_full_rebuild_at_exact_threshold() -> None:
    """Auto mode full-rebuilds when changed_ratio meets the threshold (>=)."""
    decision = decide_global_rebuild(
        "bm25",
        mode=BuildMode.DELTA,
        changed_ratio=0.5,
        threshold=0.5,
        prior_present=True,
    )
    assert decision.kind is GlobalRebuildKind.FULL_REBUILD
    assert decision.equivalent_to_full is True
    assert decision.source is DecisionSource.AUTO_THRESHOLD
    assert decision.changed_ratio == 0.5
    assert decision.threshold == 0.5


def test_explicit_global_decision_override() -> None:
    decision = decide_global_rebuild(
        "bm25",
        mode=BuildMode.DELTA,
        changed_ratio=0.01,
        threshold=0.5,
        explicit=GlobalRebuildKind.FULL_REBUILD,
        prior_present=True,
    )
    assert decision.kind is GlobalRebuildKind.FULL_REBUILD
    assert decision.source.value == "explicit"
    assert decision.equivalent_to_full is True


def test_delta_refresh_cannot_claim_equivalent_to_full() -> None:
    with pytest.raises(Exception):
        # Construct via decide (should set equivalent_to_full False).
        decision = decide_global_rebuild(
            "bm25",
            mode=BuildMode.DELTA,
            changed_ratio=0.05,
            threshold=0.5,
            explicit=GlobalRebuildKind.DELTA_REFRESH,
            prior_present=True,
        )
        assert decision.equivalent_to_full is False
        # Direct construction with illegal flag must fail.
        from ipfs_datasets_py.processors.legal_data.uscode_build import (
            DecisionSource,
            GlobalRebuildDecision,
        )

        GlobalRebuildDecision(
            family="bm25",
            kind=GlobalRebuildKind.DELTA_REFRESH,
            reason="illegal",
            source=DecisionSource.EXPLICIT,
            equivalent_to_full=True,
        )


def test_interrupted_fixture_build_resumes_without_duplicating_verified_work(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"
    executed: list[str] = []

    def counting_producer(unit, config, output_dir):
        from ipfs_datasets_py.processors.legal_data.uscode_build import (
            default_fixture_producer,
        )

        executed.append(unit.key)
        return default_fixture_producer(unit, config, output_dir)

    first = run_fixture_build(
        output,
        titles=TITLES,
        families=FAMILIES,
        mode=BuildMode.FULL,
        interrupt_after_units=2,
        producer=counting_producer,
    )
    assert first.interrupted is True
    assert first.seal is None
    assert first.checkpoint.sealed is False
    assert first.checkpoint.verified_count == 2
    assert len(executed) == 2
    first_executed = list(executed)

    # Resume: only remaining units should run.
    second = run_fixture_build(
        output,
        titles=TITLES,
        families=FAMILIES,
        mode=BuildMode.FULL,
        resume=True,
        producer=counting_producer,
    )
    assert second.interrupted is False
    assert second.seal is not None
    assert second.checkpoint.sealed is True
    assert second.checkpoint.all_verified is True
    assert set(second.resumed_keys) == set(first_executed)
    # Newly executed keys must not overlap resumed ones.
    assert set(second.executed_keys).isdisjoint(set(second.resumed_keys))
    assert len(executed) == len(TITLES) * len(FAMILIES)
    # No duplicate executions of the first two units.
    assert executed.count(first_executed[0]) == 1
    assert executed.count(first_executed[1]) == 1


def test_stale_config_mismatched_checkpoint_fails(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output, titles=TITLES, families=FAMILIES, mode=BuildMode.FULL
    )
    assert result.seal is not None

    # Different titles → different config digest.
    with pytest.raises(BuildCheckpointError, match="config_digest"):
        run_fixture_build(
            output,
            titles=("1", "2", "35"),
            families=FAMILIES,
            mode=BuildMode.FULL,
            resume=True,
        )


def test_schema_mismatched_checkpoint_fails(tmp_path: Path) -> None:
    output = tmp_path / "out"
    ckpt_dir = output / ".checkpoints"
    result = run_fixture_build(
        output, titles=("1",), families=("corpus",), mode=BuildMode.FULL
    )
    path = Path(result.checkpoint_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "not-a-real-schema"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BuildCheckpointError, match="schema_version"):
        load_checkpoint(path)


def test_partial_output_cannot_be_sealed(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output,
        titles=TITLES,
        families=FAMILIES,
        mode=BuildMode.FULL,
        interrupt_after_units=1,
    )
    assert result.interrupted is True
    assert result.checkpoint.sealed is False
    with pytest.raises(SealError, match="incomplete|partial|cannot seal"):
        compute_seal(result.checkpoint)

    orchestrator = UscodeBuildOrchestrator(output_dir=output)
    config = BuildConfig(mode=BuildMode.FULL, titles=TITLES, families=FAMILIES)
    with pytest.raises(SealError):
        orchestrator.seal_existing(config)


def test_validation_only_does_not_write_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output,
        titles=("1",),
        families=("corpus", "bm25"),
        mode=BuildMode.FULL,
        validation_only=True,
    )
    assert result.validation_only is True
    assert result.seal is not None  # in-memory seal after full verification
    assert result.checkpoint_path == ""
    assert result.seal_path == ""
    assert not (output / "corpus").exists()
    assert not (output / ".checkpoints").exists()


def test_resource_limits_enforced() -> None:
    config = BuildConfig(
        mode=BuildMode.FULL,
        titles=TITLES,
        families=FAMILIES,
        resource_limits=ResourceLimits(max_titles=1, max_work_units=100),
    )
    with pytest.raises(ResourceLimitError, match="max_titles"):
        plan_full_build(config)


def test_checkpoint_roundtrip_atomic(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output, titles=("1",), families=("corpus",), mode=BuildMode.FULL
    )
    loaded = load_checkpoint(result.checkpoint_path)
    assert loaded.config_digest == result.checkpoint.config_digest
    assert loaded.sealed is True
    assert loaded.units["1/corpus"].status is WorkUnitStatus.VERIFIED
    assert loaded.schema_version == SCHEMA_VERSION

    # Re-write atomically and compare digests.
    alt = tmp_path / "copy.json"
    write_checkpoint_atomic(alt, loaded)
    again = load_checkpoint(alt)
    assert again.to_dict() == loaded.to_dict()


def test_assert_checkpoint_compatible_rejects_mode_drift(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output, titles=("1",), families=("corpus",), mode=BuildMode.FULL
    )
    other = BuildConfig(mode=BuildMode.DELTA, titles=("1",), families=("corpus",))
    with pytest.raises(BuildCheckpointError):
        assert_checkpoint_compatible(result.checkpoint, other)


def test_delta_fixture_build_reuses_unchanged_titles(tmp_path: Path) -> None:
    output = tmp_path / "out"
    executed: list[str] = []

    def counting_producer(unit, config, output_dir):
        from ipfs_datasets_py.processors.legal_data.uscode_build import (
            default_fixture_producer,
        )

        executed.append(unit.key)
        return default_fixture_producer(unit, config, output_dir)

    # prior and current share salt for title 1; title 35 differs via
    # run_fixture_build salts — use orchestrator directly for precision.
    config = BuildConfig(
        mode=BuildMode.DELTA,
        titles=TITLES,
        families=FAMILIES,
        bm25_rebuild_threshold=0.9,
        cluster_rebuild_threshold=0.9,
    )
    prior = fixture_title_snapshots(TITLES, salt="same")
    current = {
        "1": prior["1"],
        "35": fixture_title_snapshots(("35",), salt="new-35")["35"],
    }
    orch = UscodeBuildOrchestrator(output_dir=output, producer=counting_producer)
    result = orch.run(config, current=current, prior=prior)
    assert result.seal is not None
    # Only changed title units (and non-reuse global families for that title)
    # should have been produced.
    assert all(k.startswith("35/") for k in result.executed_keys)
    assert any(k.startswith("1/") for k in result.skipped_keys)
    bm25 = result.plan.global_decisions["bm25"]
    assert bm25.kind is GlobalRebuildKind.DELTA_REFRESH
    assert bm25.equivalent_to_full is False


def test_task_identity_constants() -> None:
    assert TASK_ID == "USCIR-030"
    assert SCHEMA_VERSION.startswith("uscode-build-orchestration")
