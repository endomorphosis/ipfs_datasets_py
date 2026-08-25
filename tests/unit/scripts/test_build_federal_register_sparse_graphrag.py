"""Unit tests for streaming full/delta Federal Register build orchestration (LCR-061)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_release import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    DEFAULT_BUILD_FAMILIES,
    DEFAULT_PARTITIONS,
    FAMILY_DEPENDENCIES,
    GOAL_ID,
    GLOBAL_PARTITION,
    PROGRAM_ID,
    SCHEMA_VERSION,
    TASK_ID,
    BuildCheckpointError,
    BuildConfig,
    BuildMode,
    DecisionSource,
    FederalRegisterBuildOrchestrator,
    GlobalRebuildKind,
    HubUploadForbiddenError,
    MemoryBudget,
    MemoryBudgetError,
    PromotionError,
    ResourceLimitError,
    ResourceLimits,
    SealError,
    WorkUnitStatus,
    assemble_candidate_root,
    assert_checkpoint_compatible,
    assert_promotable,
    compute_seal,
    consume_family_builders,
    cutoff_delta_partitions,
    decide_global_rebuild,
    default_fixture_producer,
    dependency_closure,
    fixture_partition_snapshots,
    invalidate_dependency_closure,
    load_checkpoint,
    plan_delta_build,
    plan_full_build,
    reject_hub_upload,
    run_fixture_build,
    run_hermetic_check,
    stream_bounded,
    write_checkpoint_atomic,
)
import scripts.ops.legal_data.build_federal_register_sparse_graphrag as cli


PARTITIONS = DEFAULT_PARTITIONS
FAMILIES = ("corpus", "bm25", "vectors")


def test_schema_and_task_identity_are_stable() -> None:
    assert TASK_ID == "LCR-061"
    assert GOAL_ID == "LCR-G130"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert SCHEMA_VERSION == "federal-register-build-orchestration-v1"
    assert DEFAULT_BUILD_FAMILIES == (
        "corpus",
        "bm25",
        "vectors",
        "graph",
        "adjacency",
    )
    assert AUTHORIZES_HUB_UPLOAD is False
    assert AUTHORIZES_PUBLICATION is False
    assert FAMILY_DEPENDENCIES["adjacency"] == ("graph", "bm25")
    assert FAMILY_DEPENDENCIES["bm25"] == ("corpus",)


def test_cli_identity_and_help() -> None:
    assert cli.TASK_ID == "LCR-061"
    assert cli.GOAL_ID == "LCR-G130"
    parser = cli.build_parser()
    assert parser.prog == "build_federal_register_sparse_graphrag.py"
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0


def test_config_digest_is_deterministic() -> None:
    a = BuildConfig(partitions=PARTITIONS, families=FAMILIES, notes="first")
    b = BuildConfig(partitions=PARTITIONS, families=FAMILIES, notes="second")
    assert a.digest == b.digest
    assert a.digest != BuildConfig(partitions=("2026-03",), families=FAMILIES).digest


def test_mutable_cutoff_rejected() -> None:
    with pytest.raises(Exception):
        BuildConfig(observation_cutoff="latest", partitions=PARTITIONS)


def test_fixture_only_required() -> None:
    with pytest.raises(Exception, match="fixture-only"):
        BuildConfig(fixture_only=False, partitions=PARTITIONS, families=FAMILIES)


def test_hub_upload_forbidden() -> None:
    with pytest.raises(HubUploadForbiddenError):
        reject_hub_upload(True)
    reject_hub_upload(False)
    with pytest.raises(SystemExit):
        cli.main(["--fixture-only", "--hub-upload"])


def test_full_plan_builds_every_unit_and_forces_global_full() -> None:
    config = BuildConfig(mode=BuildMode.FULL, partitions=PARTITIONS, families=FAMILIES)
    plan = plan_full_build(config)
    assert plan.mode is BuildMode.FULL
    assert len(plan.units) == len(PARTITIONS) + (len(FAMILIES) - 1)
    assert all(u.action == "build" for u in plan.units)
    assert plan.global_decisions["bm25"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["vectors"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["bm25"].equivalent_to_full is True
    corpus_units = [u for u in plan.units if u.family == "corpus"]
    assert {u.partition for u in corpus_units} == set(PARTITIONS)
    assert all(
        u.partition == GLOBAL_PARTITION
        for u in plan.units
        if u.family != "corpus"
    )


def test_delta_plan_skips_unchanged_and_records_explicit_global_decisions() -> None:
    config = BuildConfig(
        mode=BuildMode.DELTA,
        partitions=PARTITIONS,
        families=FAMILIES,
        bm25_rebuild_threshold=0.6,
        cluster_rebuild_threshold=0.6,
    )
    prior = fixture_partition_snapshots(PARTITIONS, salt="prior")
    current = dict(prior)
    current["2026-08"] = fixture_partition_snapshots(
        ("2026-08",), salt="changed"
    )["2026-08"]
    plan = plan_delta_build(config, current=current, prior=prior)
    assert plan.mode is BuildMode.DELTA
    assert plan.changed_partitions == ("2026-08",)
    assert "2026-03" in plan.unchanged_partitions
    assert plan.changed_document_ratio == 0.5
    by_key = {u.key: u for u in plan.units}
    assert by_key["2026-03/corpus"].action == "reuse"
    assert by_key["2026-08/corpus"].action == "build"
    assert by_key["*/bm25"].action == "build"
    bm25 = plan.global_decisions["bm25"]
    vectors = plan.global_decisions["vectors"]
    assert bm25.kind is GlobalRebuildKind.DELTA_REFRESH
    assert vectors.kind is GlobalRebuildKind.DELTA_REFRESH
    assert bm25.equivalent_to_full is False
    assert vectors.equivalent_to_full is False
    assert "bm25" in plan.invalidated_families
    assert "NOT equivalent" in bm25.reason or "not" in bm25.proof


def test_cutoff_delta_marks_months_after_prior_cutoff() -> None:
    unchanged, changed = cutoff_delta_partitions(
        PARTITIONS,
        prior_cutoff="2026-03-02",
        current_cutoff="2026-08-10T00:00:00Z",
    )
    assert "2026-03" in unchanged
    assert "2026-08" in changed


def test_dependency_closure_invalidates_downstream_families() -> None:
    closed = invalidate_dependency_closure({"corpus"})
    assert closed == dependency_closure({"corpus"})
    assert "bm25" in closed
    assert "vectors" in closed
    assert "graph" in closed
    assert "adjacency" in closed
    assert invalidate_dependency_closure({"bm25"}) == frozenset({"bm25", "adjacency"})


def test_delta_auto_full_rebuild_when_threshold_crossed() -> None:
    config = BuildConfig(
        mode=BuildMode.DELTA,
        partitions=PARTITIONS,
        families=FAMILIES,
        bm25_rebuild_threshold=0.10,
        cluster_rebuild_threshold=0.10,
    )
    prior = fixture_partition_snapshots(PARTITIONS, salt="prior")
    current = fixture_partition_snapshots(PARTITIONS, salt="all-changed")
    plan = plan_delta_build(config, current=current, prior=prior)
    assert plan.changed_document_ratio == 1.0
    assert plan.global_decisions["bm25"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["vectors"].kind is GlobalRebuildKind.FULL_REBUILD
    assert plan.global_decisions["bm25"].equivalent_to_full is True
    assert all(
        u.action == "build"
        for u in plan.units
        if u.family in {"bm25", "vectors"}
    )


def test_auto_full_rebuild_at_exact_threshold() -> None:
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


def test_delta_refresh_cannot_claim_equivalent_to_full() -> None:
    decision = decide_global_rebuild(
        "bm25",
        mode=BuildMode.DELTA,
        changed_ratio=0.05,
        threshold=0.5,
        explicit=GlobalRebuildKind.DELTA_REFRESH,
        prior_present=True,
    )
    assert decision.equivalent_to_full is False
    from ipfs_datasets_py.processors.legal_data.federal_register_release import (
        GlobalRebuildDecision,
    )

    with pytest.raises(Exception):
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
        executed.append(unit.key)
        return default_fixture_producer(unit, config, output_dir)

    first = run_fixture_build(
        output,
        partitions=PARTITIONS,
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

    second = run_fixture_build(
        output,
        partitions=PARTITIONS,
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
    assert set(second.executed_keys).isdisjoint(set(second.resumed_keys))
    expected = len(PARTITIONS) + (len(FAMILIES) - 1)
    assert len(executed) == expected
    assert executed.count(first_executed[0]) == 1
    assert executed.count(first_executed[1]) == 1


def test_stale_config_mismatched_checkpoint_fails(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output, partitions=PARTITIONS, families=FAMILIES, mode=BuildMode.FULL
    )
    assert result.seal is not None
    with pytest.raises(BuildCheckpointError, match="config_digest"):
        run_fixture_build(
            output,
            partitions=("2026-03", "2026-04", "2026-08"),
            families=FAMILIES,
            mode=BuildMode.FULL,
            resume=True,
        )


def test_schema_mismatched_checkpoint_fails(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output, partitions=("2026-03",), families=("corpus",), mode=BuildMode.FULL
    )
    path = Path(result.checkpoint_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "not-a-real-schema"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BuildCheckpointError, match="schema_version"):
        load_checkpoint(path)


def test_partial_output_cannot_be_sealed_or_promoted(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output,
        partitions=PARTITIONS,
        families=FAMILIES,
        mode=BuildMode.FULL,
        interrupt_after_units=1,
    )
    assert result.interrupted is True
    assert result.checkpoint.sealed is False
    with pytest.raises(PromotionError):
        assert_promotable(result.checkpoint)
    with pytest.raises((SealError, PromotionError), match="incomplete|promote|cannot"):
        compute_seal(result.checkpoint)
    orchestrator = FederalRegisterBuildOrchestrator(output_dir=output)
    config = BuildConfig(
        mode=BuildMode.FULL, partitions=PARTITIONS, families=FAMILIES
    )
    with pytest.raises((SealError, PromotionError)):
        orchestrator.seal_existing(config)


def test_validation_only_does_not_write_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output,
        partitions=("2026-03",),
        families=("corpus", "bm25"),
        mode=BuildMode.FULL,
        validation_only=True,
    )
    assert result.validation_only is True
    assert result.seal is not None
    assert result.checkpoint_path == ""
    assert result.seal_path == ""
    assert not (output / "corpus").exists()
    assert not (output / ".checkpoints").exists()


def test_resource_limits_enforced() -> None:
    config = BuildConfig(
        mode=BuildMode.FULL,
        partitions=PARTITIONS,
        families=FAMILIES,
        resource_limits=ResourceLimits(max_partitions=1, max_work_units=100),
    )
    with pytest.raises(ResourceLimitError, match="max_partitions"):
        plan_full_build(config)


def test_streaming_memory_budget_never_holds_whole_corpus() -> None:
    budget = MemoryBudget(max_resident_records=2)
    values = list(stream_bounded(range(10), budget=budget))
    assert values == list(range(10))
    assert budget.peak_resident_records <= 2
    with pytest.raises(MemoryBudgetError):
        MemoryBudget(max_resident_records=1).check_materialize(18)


def test_checkpoint_roundtrip_atomic(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output, partitions=("2026-03",), families=("corpus",), mode=BuildMode.FULL
    )
    loaded = load_checkpoint(result.checkpoint_path)
    assert loaded.config_digest == result.checkpoint.config_digest
    assert loaded.sealed is True
    assert loaded.units["2026-03/corpus"].status is WorkUnitStatus.VERIFIED
    assert loaded.schema_version == SCHEMA_VERSION
    alt = tmp_path / "copy.json"
    write_checkpoint_atomic(alt, loaded)
    again = load_checkpoint(alt)
    assert again.to_dict() == loaded.to_dict()


def test_assert_checkpoint_compatible_rejects_mode_drift(tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = run_fixture_build(
        output, partitions=("2026-03",), families=("corpus",), mode=BuildMode.FULL
    )
    other = BuildConfig(
        mode=BuildMode.DELTA, partitions=("2026-03",), families=("corpus",)
    )
    with pytest.raises(BuildCheckpointError):
        assert_checkpoint_compatible(result.checkpoint, other)


def test_delta_fixture_build_reuses_unchanged_partitions(tmp_path: Path) -> None:
    output = tmp_path / "out"
    executed: list[str] = []

    def counting_producer(unit, config, output_dir):
        executed.append(unit.key)
        return default_fixture_producer(unit, config, output_dir)

    config = BuildConfig(
        mode=BuildMode.DELTA,
        partitions=PARTITIONS,
        families=FAMILIES,
        bm25_rebuild_threshold=0.9,
        cluster_rebuild_threshold=0.9,
    )
    prior = fixture_partition_snapshots(PARTITIONS, salt="same")
    current = {
        "2026-03": prior["2026-03"],
        "2026-08": fixture_partition_snapshots(("2026-08",), salt="new-08")["2026-08"],
    }
    orch = FederalRegisterBuildOrchestrator(
        output_dir=output, producer=counting_producer
    )
    result = orch.run(config, current=current, prior=prior)
    assert result.seal is not None
    assert "2026-03/corpus" not in result.executed_keys
    assert "2026-08/corpus" in result.executed_keys
    assert any(k.endswith("/bm25") for k in result.executed_keys)
    assert "2026-03/corpus" in result.skipped_keys
    bm25 = result.plan.global_decisions["bm25"]
    assert bm25.kind is GlobalRebuildKind.DELTA_REFRESH
    assert bm25.equivalent_to_full is False
    assert "bm25" in result.plan.invalidated_families


def test_two_build_logical_determinism(tmp_path: Path) -> None:
    first = run_fixture_build(
        tmp_path / "a", partitions=PARTITIONS, families=FAMILIES, mode=BuildMode.FULL
    )
    second = run_fixture_build(
        tmp_path / "b", partitions=PARTITIONS, families=FAMILIES, mode=BuildMode.FULL
    )
    assert first.seal is not None and second.seal is not None
    assert first.seal.seal_digest == second.seal.seal_digest
    assert first.candidate_root == second.candidate_root
    assert first.seal.family_roots == second.seal.family_roots


def test_full_and_forced_full_delta_share_equivalence_flags(tmp_path: Path) -> None:
    full = run_fixture_build(
        tmp_path / "full", partitions=PARTITIONS, families=FAMILIES, mode=BuildMode.FULL
    )
    delta = run_fixture_build(
        tmp_path / "delta",
        partitions=PARTITIONS,
        families=FAMILIES,
        mode=BuildMode.DELTA,
        current_salt="all-changed",
        prior_salt="prior",
        bm25_decision=GlobalRebuildKind.FULL_REBUILD,
        cluster_decision=GlobalRebuildKind.FULL_REBUILD,
    )
    assert full.seal is not None and delta.seal is not None
    assert delta.plan.global_decisions["bm25"].equivalent_to_full is True
    assert delta.plan.global_decisions["vectors"].equivalent_to_full is True
    assert all(unit.action == "build" for unit in delta.plan.units)


def test_atomic_candidate_root_assembled_only_when_complete(tmp_path: Path) -> None:
    result = run_fixture_build(
        tmp_path / "root",
        partitions=PARTITIONS,
        families=FAMILIES,
        mode=BuildMode.FULL,
    )
    assert result.candidate_root
    path = tmp_path / "root" / "candidate_root.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["candidate_root"] == result.candidate_root
    assert payload["authorizing_hub_upload"] is False
    assert payload["task_id"] == TASK_ID
    assembled = assemble_candidate_root(
        result.checkpoint, output_dir=tmp_path / "root-copy"
    )
    assert assembled["candidate_root"] == result.candidate_root


def test_family_checkpoints_stream_to_disk(tmp_path: Path) -> None:
    result = run_fixture_build(
        tmp_path / "families",
        partitions=("2026-03",),
        families=("corpus", "bm25"),
        mode=BuildMode.FULL,
    )
    assert result.seal is not None
    family_dir = tmp_path / "families" / ".checkpoints" / "families"
    assert (family_dir / "corpus" / "2026-03.json").is_file()
    assert (family_dir / "bm25" / "global.json").is_file()


def test_cli_plan_only_and_fixture_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        [
            "--fixture-only",
            "--plan-only",
            "--json",
            "--partitions",
            "2026-03,2026-08",
            "--families",
            "corpus,bm25",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "LCR-061"
    assert payload["plan"]["mode"] == "full"
    assert payload["plan"]["unit_count"] == 3

    out = tmp_path / "cli-out"
    code = cli.main(
        [
            "--fixture-only",
            "--json",
            "--output-dir",
            str(out),
            "--partitions",
            "2026-03",
            "--families",
            "corpus",
        ]
    )
    assert code == 0
    built = json.loads(capsys.readouterr().out)
    assert built["checkpoint"]["sealed"] is True
    assert built["authorizing_hub_upload"] is False


def test_cli_check_is_hermetic(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--fixture-only", "--check", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_id"] == "LCR-061"
    assert payload["goal_id"] == "LCR-G130"
    assert payload["program_id"] == "legal-corpora-reindex-v1"
    assert payload["authorizing_hub_upload"] is False
    required = {
        "two_build_logical_determinism",
        "stale_checkpoint_cannot_promote",
        "interrupted_retry_idempotent",
        "full_delta_equivalence_flags",
        "cutoff_delta_invalidates_dependency_closure",
        "no_whole_corpus_memory_load",
        "family_builders_consumed",
        "resource_budget_enforced",
    }
    assert required.issubset(set(payload["proofs"]))
    assert payload["family_builder_consumption"]["bm25_root"]
    assert payload["family_builder_consumption"]["vector_root"]
    assert payload["family_builder_consumption"]["graph_root"]


def test_run_hermetic_check_matches_cli() -> None:
    payload = run_hermetic_check()
    assert payload["ok"] is True
    assert payload["fixture_only"] is True
    assert "check_digest" in payload


def test_consume_family_builders_is_read_only_and_offline() -> None:
    payload = consume_family_builders()
    assert payload["authorizing_hub_upload"] is False
    assert payload["whole_corpus_loaded"] is False
    assert payload["peak_resident_records"] <= 32
    assert payload["bm25_root"]
    assert payload["vector_root"]
    assert payload["graph_root"]
    assert payload["adjacency_root"]
    assert payload["task_id"] == TASK_ID
