"""Synthetic persistence tests for the source-safe HSSL-G211 bridge.

No benchmark fixture, corpus, manifest, or holdout data is loaded here.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import stat

import pytest

from benchmarks.logic_pipeline import adapters, contracts, runtime, variants
from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    build_semantic_ablation_plan,
)
from benchmarks.logic_pipeline.causal_ablation import (
    CausalExecutionProfileV2,
    CausalRescueCaseV2,
    build_causal_rescue_manifest_v2,
)
from benchmarks.logic_pipeline.causal_batch import (
    CausalRuntimeBatchError,
    HSSLEV2116C82,
    build_g211_compiler_reference_population_v2,
    persist_causal_runtime_batch_v2,
    validate_causal_runtime_batch_v2,
)
from benchmarks.logic_pipeline.causal_runtime import (
    CompilerReferenceExposureV2,
    execute_causal_runtime_case_v2,
)
from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.namespace_provenance import (
    G240RuntimeNamespaceEvidenceSetV2,
    G240RuntimeNamespaceReceiptV2,
    RuntimeNamespaceProvenanceError,
    build_g240_namespace_policy_v2,
    validate_g240_runtime_namespace_evidence_set_v2,
    validate_g240_runtime_namespace_receipt_v2,
)


RUN_ID = "synthetic-g211"
CASE_ID = "synthetic-g211-case"
SOURCE_TEXT = "Synthetic source for a persistence-only G211 test."
MANIFEST_SHA256 = "a" * 64
ENVIRONMENT_SHA256 = "b" * 64
PROOF_CONTEXT: dict[str, object] = {
    "obligation_id": "synthetic-g211-obligation",
    "proof_obligation": {
        "kind": "theorem",
        "logic": "fol",
        "target": "synthetic_claim",
    },
}


def _plan():
    return build_semantic_ablation_plan(
        RUN_ID,
        (
            AblationCase.create(
                CASE_ID,
                {"text": SOURCE_TEXT},
                split=contracts.Split.PILOT,
            ),
        ),
        case_manifest_sha256=MANIFEST_SHA256,
        split=contracts.Split.PILOT,
        seed=31,
        variant_ids=("A0",),
        cache_modes=(contracts.CacheMode.COLD,),
        environment_sha256=ENVIRONMENT_SHA256,
    )


def _manifest(plan, *, target: str = "synthetic_claim"):
    return build_causal_rescue_manifest_v2(
        plan,
        (
            CausalRescueCaseV2(
                case_id=CASE_ID,
                split=contracts.Split.PILOT,
                source_cid=cid_for_bytes(SOURCE_TEXT.encode("utf-8")),
                obligation_id="synthetic-g211-obligation",
                proof_obligation={
                    "kind": "theorem",
                    "logic": "fol",
                    "target": target,
                },
                optional_components=("hammer", "leanstral"),
                review_attestation_cid=cid_for_dag_json(
                    {
                        "schema": "synthetic-independent-review.v1",
                        "case_id": CASE_ID,
                        "reviewed": True,
                    }
                ),
            ),
        ),
    )


def _compiler_record() -> contracts.StageRecord:
    proof_input = {"text": SOURCE_TEXT, **PROOF_CONTEXT}
    compiled = runtime.compile_reviewed_obligation(proof_input)
    assert compiled is not None
    translation = runtime._entailment_translation(
        proof_input,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    assert translation is None
    request = adapters.StageRequest(
        run_id=RUN_ID,
        case_id=CASE_ID,
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id="A0",
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        input_data={"text": SOURCE_TEXT},
        requested_identity=variants.get_variant_definition(
            "A0"
        ).requested_identity(contracts.StageName.COMPILER),
        environment_sha256=ENVIRONMENT_SHA256,
        source=("synthetic-g211-test",),
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    adapter = adapters.StageAdapter(
        contracts.StageName.COMPILER,
        handler=lambda _request: adapters.StageOutput(
            data={
                "compiled_obligation": compiled.to_dict(),
                "compiled_obligation_sha256": compiled.digest,
                "entailment_translation": None,
                "entailment_translation_sha256": None,
                "native_proof_candidate": None,
            },
            effective_identity={
                "implementation": "synthetic-compiler",
                "graph_invoked": True,
            },
        ),
    )
    return adapter.run(request)


def _evidence(tmp_path: Path):
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _compiler_record(),
        source_text=SOURCE_TEXT,
    )
    runner = runtime.NativeKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
    )
    return execute_causal_runtime_case_v2(
        contracts.CaseResultRecord.from_stages(
            (exposure.compiler_record,)
        ),
        SOURCE_TEXT,
        PROOF_CONTEXT,
        exposure,
        {
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            )
        },
    )


def _inputs(tmp_path: Path):
    plan = _plan()
    manifest = _manifest(plan)
    evidence = _evidence(tmp_path)
    evidence_by_job = {plan.jobs[0].job_id: evidence}
    population = build_g211_compiler_reference_population_v2(
        plan,
        evidence_by_job,
    )
    profile = CausalExecutionProfileV2(
        plan_cid=manifest.plan_cid,
        source_manifest_cid=manifest.source_manifest_cid,
        rescue_manifest_cid=manifest.manifest_cid,
        semantic_calibration_artifact_cid=cid_for_dag_json(
            {"schema": "synthetic-g200-calibration.v1"}
        ),
        compiler_reference_population_cid=str(
            population["population_cid"]
        ),
        environment_sha256=ENVIRONMENT_SHA256,
    )
    return plan, manifest, profile, evidence_by_job


def _persist(tmp_path: Path):
    plan, manifest, profile, evidence = _inputs(tmp_path)
    root = tmp_path / "g211-run"
    result = persist_causal_runtime_batch_v2(
        plan,
        manifest,
        profile,
        evidence,
        output_root=root,
        resume=True,
    )
    return plan, manifest, profile, evidence, root, result


def _build_namespace_evidence(plan, evidence_by_job):
    policy = build_g240_namespace_policy_v2(
        (plan,),
        source_commit_cid=cid_for_dag_json(
            {"schema": "synthetic-source-commit.v1"}
        ),
        recursive_gitlinks_cid=cid_for_dag_json(
            {"schema": "synthetic-recursive-gitlinks.v1"}
        ),
        environment_cid=cid_for_dag_json(
            {"schema": "synthetic-environment.v1"}
        ),
        runtime_orchestration_policy_cid=cid_for_dag_json(
            {"schema": "synthetic-source-executor-contract.v1"}
        ),
        namespace_authority_cid=cid_for_dag_json(
            {"authority": "synthetic-namespace-policy"}
        ),
    )
    job = plan.jobs[0]
    evidence = evidence_by_job[job.job_id]
    receipt = G240RuntimeNamespaceReceiptV2.create(
        policy=policy,
        plan=plan,
        job=job,
        evidence=evidence,
        executor_identity_cid=cid_for_dag_json(
            {"authority": "synthetic-runtime-executor"}
        ),
        observer_identity_cid=cid_for_dag_json(
            {"authority": "synthetic-namespace-observer"}
        ),
        process_group_started=True,
        process_group_reaped=True,
        active_process_count_after_reap=0,
        state_namespace_created_exclusive=True,
        state_namespace_finalized=True,
        output_namespace_created_exclusive=True,
        output_namespace_finalized=True,
        cache_namespaces_mounted=True,
    )
    plan_cid = policy.plan_cids[0]
    evidence_set = G240RuntimeNamespaceEvidenceSetV2.create(
        policy=policy,
        plan_cids=(plan_cid,),
        receipts=(receipt,),
        validator_identity_cid=cid_for_dag_json(
            {"authority": "synthetic-namespace-validator"}
        ),
    )
    return plan, evidence_by_job, policy, receipt, evidence_set


def _namespace_evidence(tmp_path: Path):
    plan, _manifest_value, _profile, evidence_by_job = _inputs(tmp_path)
    return _build_namespace_evidence(plan, evidence_by_job)


def test_g211_marker_and_public_contract_are_stable() -> None:
    assert HSSLEV2116C82() == (
        "write-once full causal runtime evidence with exact plan coordinate "
        "resume race replay compiler exposure equality and derived aggregates"
    )


def test_g240_namespace_preimages_and_lifecycle_replay_from_sources(
    tmp_path: Path,
) -> None:
    plan, evidence_by_job, policy, receipt, evidence_set = (
        _namespace_evidence(tmp_path)
    )
    job = plan.jobs[0]
    evidence = evidence_by_job[job.job_id]

    restored_receipt = validate_g240_runtime_namespace_receipt_v2(
        receipt.to_dict(),
        policy=policy,
        plan=plan,
        job=job,
        evidence=evidence,
    )
    restored_set = validate_g240_runtime_namespace_evidence_set_v2(
        evidence_set.to_dict(),
        plans=(plan,),
        evidence_by_plan_and_job={
            (policy.plan_cids[0], job.job_id): evidence,
        },
    )

    assert restored_receipt.receipt_cid == receipt.receipt_cid
    assert restored_set.evidence_set_cid == evidence_set.evidence_set_cid
    coordinate = policy.jobs[0]
    assert set(coordinate.cache_namespace_cids) == {
        "compiler",
        "kernel",
    }
    assert set(receipt.cache_key_cids) == {"compiler", "kernel"}
    assert all(not values for values in receipt.cache_key_cids.values())


def test_g240_caller_copied_namespace_cid_fails_source_replay(
    tmp_path: Path,
) -> None:
    plan, evidence_by_job, policy, receipt, _evidence_set = (
        _namespace_evidence(tmp_path)
    )
    value = receipt.to_dict()
    value["process_namespace_cid"] = cid_for_dag_json(
        {"opaque": "caller-selected"}
    )
    value["receipt_cid"] = cid_for_dag_json(
        {
            key: member
            for key, member in value.items()
            if key != "receipt_cid"
        }
    )

    with pytest.raises(
        RuntimeNamespaceProvenanceError,
        match="differs from source evidence",
    ):
        validate_g240_runtime_namespace_receipt_v2(
            value,
            policy=policy,
            plan=plan,
            job=plan.jobs[0],
            evidence=evidence_by_job[plan.jobs[0].job_id],
        )


def test_g240_incomplete_process_lifecycle_fails_closed(
    tmp_path: Path,
) -> None:
    _plan_value, _evidence, _policy, receipt, _evidence_set = (
        _namespace_evidence(tmp_path)
    )
    value = receipt.to_dict()
    value["process_group_reaped"] = False
    value["active_process_count_after_reap"] = 1
    value["receipt_cid"] = cid_for_dag_json(
        {
            key: member
            for key, member in value.items()
            if key != "receipt_cid"
        }
    )

    with pytest.raises(
        RuntimeNamespaceProvenanceError,
        match="lifecycle is incomplete",
    ):
        G240RuntimeNamespaceReceiptV2.from_dict(value)


def test_g240_public_receipt_rejects_path_instead_of_cid(
    tmp_path: Path,
) -> None:
    _plan_value, _evidence, _policy, receipt, _evidence_set = (
        _namespace_evidence(tmp_path)
    )
    value = receipt.to_dict()
    value["output_namespace_cid"] = "/tmp/private-run/results"
    value["receipt_cid"] = cid_for_dag_json(
        {
            key: member
            for key, member in value.items()
            if key != "receipt_cid"
        }
    )

    with pytest.raises(
        RuntimeNamespaceProvenanceError,
        match="output_namespace_cid must be a canonical CID",
    ):
        G240RuntimeNamespaceReceiptV2.from_dict(value)


def test_g211_persists_and_replays_complete_g240_namespace_evidence(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence_by_job = _inputs(tmp_path)
    _plan, _evidence, policy, _receipt, evidence_set = (
        _build_namespace_evidence(plan, evidence_by_job)
    )
    root = tmp_path / "g211-with-g240"

    result = persist_causal_runtime_batch_v2(
        plan,
        manifest,
        profile,
        evidence_by_job,
        output_root=root,
        runtime_namespace_evidence_set=evidence_set,
    )
    restored = validate_causal_runtime_batch_v2(
        plan,
        manifest,
        profile,
        output_root=root,
    )

    assert result.runtime_namespace_evidence_set is not None
    assert restored.runtime_namespace_evidence_set is not None
    assert (
        restored.runtime_namespace_evidence_set.evidence_set_cid
        == evidence_set.evidence_set_cid
    )
    assert (
        restored.receipt["runtime_namespace_policy_cid"]
        == policy.policy_cid
    )
    assert (
        restored.receipt["runtime_namespace_evidence_set_cid"]
        == evidence_set.evidence_set_cid
    )
    assert (
        root / "state" / "runtime-namespace-evidence-set.json"
    ).is_file()


def test_relative_output_root_is_rejected(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence = _inputs(tmp_path)

    with pytest.raises(
        CausalRuntimeBatchError,
        match="output_root must be absolute",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            evidence,
            output_root=Path("relative-g211-output"),
        )


def test_output_root_inside_source_worktree_is_rejected(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence = _inputs(tmp_path)
    source_root = Path(__file__).resolve().parents[4]

    with pytest.raises(
        CausalRuntimeBatchError,
        match="inside a Git repository or worktree",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            evidence,
            output_root=source_root,
        )


def test_existing_symlink_output_root_is_rejected(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence = _inputs(tmp_path)
    target = tmp_path / "symlink-target"
    target.mkdir(mode=0o700)
    root = tmp_path / "symlink-output"
    root.symlink_to(target, target_is_directory=True)

    with pytest.raises(
        CausalRuntimeBatchError,
        match="real directory, not a symlink",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            evidence,
            output_root=root,
        )


def test_existing_non_directory_output_root_is_rejected(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence = _inputs(tmp_path)
    root = tmp_path / "not-a-directory"
    root.write_text("not a run directory", encoding="utf-8")

    with pytest.raises(
        CausalRuntimeBatchError,
        match="output_root must be a directory",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            evidence,
            output_root=root,
        )


def test_existing_group_accessible_output_root_is_rejected(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence = _inputs(tmp_path)
    root = tmp_path / "group-accessible-output"
    root.mkdir(mode=0o700)
    root.chmod(0o750)

    with pytest.raises(
        CausalRuntimeBatchError,
        match="not be accessible to group or others",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            evidence,
            output_root=root,
        )


def test_absolute_tmp_path_run_directories_are_private(
    tmp_path: Path,
) -> None:
    _plan_value, _manifest_value, _profile, _evidence_value, root, _result = (
        _persist(tmp_path)
    )

    assert root.is_absolute()
    directories = (root,) + tuple(
        path for path in root.rglob("*") if path.is_dir()
    )
    assert directories
    for directory in directories:
        assert stat.S_ISDIR(directory.lstat().st_mode)
        assert stat.S_IMODE(directory.lstat().st_mode) & 0o077 == 0


def test_complete_batch_persists_full_evidence_and_replays(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence, root, result = _persist(tmp_path)

    assert result.complete is True
    assert result.executed_job_ids == (plan.jobs[0].job_id,)
    assert result.resumed_job_ids == ()
    assert tuple(item.receipt_cid for item in result.evidence) == (
        evidence[plan.jobs[0].job_id].receipt_cid,
    )
    assert len(result.causal_aggregates) == 1
    assert result.receipt["complete"] is True
    assert result.receipt["holdout_included"] is False

    restored = validate_causal_runtime_batch_v2(
        plan,
        manifest,
        profile,
        output_root=root,
    )
    assert restored.receipt_cid == result.receipt_cid
    assert restored.executed_job_ids == ()
    assert restored.resumed_job_ids == (plan.jobs[0].job_id,)


def test_resume_is_byte_immutable_and_resume_false_rejects(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence, root, first = _persist(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*.json")
    }

    resumed = persist_causal_runtime_batch_v2(
        plan,
        manifest,
        profile,
        evidence,
        output_root=root,
        resume=True,
    )
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*.json")
    }
    assert resumed.receipt_cid == first.receipt_cid
    assert resumed.executed_job_ids == ()
    assert resumed.resumed_job_ids == (plan.jobs[0].job_id,)
    assert after == before

    with pytest.raises(
        CausalRuntimeBatchError,
        match="namespace exists with resume disabled",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            evidence,
            output_root=root,
            resume=False,
        )


def test_profile_must_bind_the_derived_compiler_population_before_writes(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence = _inputs(tmp_path)
    mismatched = CausalExecutionProfileV2(
        plan_cid=profile.plan_cid,
        source_manifest_cid=profile.source_manifest_cid,
        rescue_manifest_cid=profile.rescue_manifest_cid,
        semantic_calibration_artifact_cid=(
            profile.semantic_calibration_artifact_cid
        ),
        compiler_reference_population_cid=cid_for_dag_json(
            {"schema": "substituted-population.v1"}
        ),
        environment_sha256=profile.environment_sha256,
    )
    root = tmp_path / "must-not-exist"

    with pytest.raises(
        CausalRuntimeBatchError,
        match="does not bind the derived compiler",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            mismatched,
            evidence,
            output_root=root,
        )
    assert not root.exists()


def test_reviewed_proof_context_mismatch_fails_before_writes(
    tmp_path: Path,
) -> None:
    plan, _manifest_value, profile, evidence = _inputs(tmp_path)
    changed_manifest = _manifest(plan, target="another_claim")
    changed_profile = CausalExecutionProfileV2(
        plan_cid=profile.plan_cid,
        source_manifest_cid=changed_manifest.source_manifest_cid,
        rescue_manifest_cid=changed_manifest.manifest_cid,
        semantic_calibration_artifact_cid=(
            profile.semantic_calibration_artifact_cid
        ),
        compiler_reference_population_cid=(
            profile.compiler_reference_population_cid
        ),
        environment_sha256=profile.environment_sha256,
    )
    root = tmp_path / "must-not-exist"

    with pytest.raises(
        CausalRuntimeBatchError,
        match="crosses its reviewed rescue boundary",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            changed_manifest,
            changed_profile,
            evidence,
            output_root=root,
        )
    assert not root.exists()


def test_rebased_outer_envelope_cannot_hide_tampered_full_evidence(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, _evidence_value, root, _result = _persist(
        tmp_path
    )
    path = (
        root
        / "results"
        / "pilot"
        / "cold"
        / "A0"
        / f"{CASE_ID}.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    nested = value["causal_runtime_evidence"]
    nested["source_text_utf8"] = "substituted source"
    value["envelope_cid"] = cid_for_dag_json(
        {
            key: member
            for key, member in value.items()
            if key != "envelope_cid"
        }
    )
    path.write_bytes(canonical_dag_json_bytes(value) + b"\n")

    with pytest.raises(
        CausalRuntimeBatchError,
        match="envelope failed typed replay",
    ):
        validate_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            output_root=root,
        )


def test_foreign_result_is_rejected_without_mutating_authority(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, _evidence_value, root, _result = _persist(
        tmp_path
    )
    foreign = root / "results" / "foreign.json"
    foreign.write_bytes(canonical_dag_json_bytes({"foreign": True}) + b"\n")

    with pytest.raises(
        CausalRuntimeBatchError,
        match="foreign result records",
    ):
        validate_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            output_root=root,
        )


def test_concurrent_persistence_converges_on_one_exact_envelope(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, evidence = _inputs(tmp_path)
    root = tmp_path / "concurrent-g211"

    def persist():
        return persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            evidence,
            output_root=root,
            resume=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: persist(), range(2)))

    assert {item.receipt_cid for item in results} == {
        results[0].receipt_cid
    }
    assert sum(len(item.executed_job_ids) for item in results) == 1
    assert sum(len(item.resumed_job_ids) for item in results) == 1
    restored = validate_causal_runtime_batch_v2(
        plan,
        manifest,
        profile,
        output_root=root,
    )
    assert restored.receipt_cid == results[0].receipt_cid


def test_job_mapping_must_be_complete_before_namespace_creation(
    tmp_path: Path,
) -> None:
    plan, manifest, profile, _evidence = _inputs(tmp_path)
    root = tmp_path / "must-not-exist"

    with pytest.raises(
        CausalRuntimeBatchError,
        match="exactly cover every scheduled job",
    ):
        persist_causal_runtime_batch_v2(
            plan,
            manifest,
            profile,
            {},
            output_root=root,
        )
    assert not root.exists()
