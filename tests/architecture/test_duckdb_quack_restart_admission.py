from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_accelerate_py.agent_supervisor.code_evidence_graph import (
    POST_MERGE_EVIDENCE_ACCEPTANCE_CRITERIA,
    CodeImpactIndex,
    assemble_post_merge_evidence,
)
from ipfs_accelerate_py.agent_supervisor.formal_verification_contracts import (
    EvidenceAuthority,
    EvidenceKind,
    EvidenceVerdict,
    ProofEvidence,
    ProofReceipt,
    ProofVerdict,
    ResourceBudget,
)
from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    DuckDBMergeIntegratedReceipt,
    DuckDBTaskCompletionEvidence,
    DuckDBValidationExecutionReceipt,
    PortalImplementationDaemon,
    _duckdb_compact_validation_proof_digest,
)
from ipfs_accelerate_py.agent_supervisor.validation_scheduler import (
    ImpactValidationCheck,
    ImpactValidationDAGReceipt,
    ImpactValidationKind,
    ImpactValidationNodeReceipt,
    RepositoryValidationPolicy,
    ValidationNodeDisposition,
    build_impact_selected_validation_dag,
)

from scripts.ops import ipfs_datasets_duckdb_quack_program as program

TARGET_BRANCH = "feat/duckdb-quack-control-plane"


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def _write_and_commit(repository: Path, relative_path: str, value: str, subject: str) -> str:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    _git(repository, "add", "--", relative_path)
    _git(repository, "commit", "-m", subject)
    return _git(repository, "rev-parse", "HEAD")


@pytest.fixture()
def restart_authority(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    accelerator = tmp_path / "accelerator"
    accelerator.mkdir()
    _git(accelerator, "init", "-b", "main")
    _git(accelerator, "config", "user.name", "Restart Admission Test")
    _git(accelerator, "config", "user.email", "restart-admission@example.invalid")
    accelerator_v1 = _write_and_commit(
        accelerator, "version.txt", "v1\n", "accelerator v1"
    )
    accelerator_v2 = _write_and_commit(
        accelerator, "version.txt", "v2\n", "accelerator v2"
    )
    accelerator_v2_tree = _git(accelerator, "rev-parse", "HEAD^{tree}")

    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", TARGET_BRANCH)
    _git(repository, "config", "user.name", "Restart Admission Test")
    _git(repository, "config", "user.email", "restart-admission@example.invalid")
    _write_and_commit(repository, "seed.txt", "seed\n", "seed")
    verifier_body = "#!/usr/bin/env python3\n# typed release verifier fixture\n"
    _write_and_commit(
        repository,
        "scripts/validation/validate_accelerate_duckdb_quack_release.py",
        verifier_body,
        "add release verifier",
    )
    _git(
        repository,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(accelerator),
        "ipfs_accelerate_py",
    )
    _git(repository / "ipfs_accelerate_py", "checkout", accelerator_v1)
    _git(repository, "add", ".gitmodules", "ipfs_accelerate_py")
    _git(repository, "commit", "-m", "pin initial accelerator")
    seed_commit = _git(repository, "rev-parse", "HEAD")
    seed_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    repository_binding = (
        f"repository:git-commit:{seed_commit}:tree:{seed_tree}"
    )

    control_database = tmp_path / "runtime/control.duckdb"
    merge_queue_root = tmp_path / "runtime/merge-queue"
    control_database.parent.mkdir(parents=True)
    merge_queue_root.mkdir(parents=True)
    DuckDBTaskSource, _providers = program._accelerate_imports()
    source = DuckDBTaskSource(control_database)
    source.materialize(
        program.formal_source(repository_binding),
        repository_tree_id=repository_binding,
        expected_absent=True,
    )

    monkeypatch.setattr(program, "REPO_ROOT", repository)
    monkeypatch.setattr(program, "DATABASE_PATH", control_database)
    monkeypatch.setattr(program, "MERGE_QUEUE_ROOT", merge_queue_root)
    monkeypatch.setattr(program, "TARGET_BRANCH", TARGET_BRANCH)
    monkeypatch.setattr(
        program,
        "DEFAULT_MARKDOWN_EXPORT",
        repository / "docs/architecture/generated-plan.md",
    )
    monkeypatch.setattr(
        program,
        "DEFAULT_JSON_EXPORT",
        repository / "data/exports/generated-plan.json",
    )
    return {
        "repository": repository,
        "repository_binding": repository_binding,
        "seed_commit": seed_commit,
        "source": source,
        "merge_queue_root": merge_queue_root,
        "accelerator_v2": accelerator_v2,
        "accelerator_v2_tree": accelerator_v2_tree,
    }


def _merge_one_implementation(
    repository: Path,
    *,
    task_id: str = "DQK-001",
    relative_path: str = "implementation.txt",
    value: str = "implemented\n",
) -> tuple[str, str, str, str]:
    seed_commit = _git(repository, "rev-parse", TARGET_BRANCH)
    branch_name = f"agent/{task_id.lower()}"
    _git(repository, "checkout", "-b", branch_name)
    implementation_commit = _write_and_commit(
        repository,
        relative_path,
        value,
        f"{task_id}: implement",
    )
    implementation_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    _git(repository, "checkout", TARGET_BRANCH)
    _git(repository, "merge", "--no-ff", branch_name, "-m", f"Merge {task_id}")
    merge_commit = _git(repository, "rev-parse", "HEAD")
    merge_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    assert _git(repository, "rev-list", "--parents", "-n", "1", merge_commit).split() == [
        merge_commit,
        seed_commit,
        implementation_commit,
    ]
    return implementation_commit, implementation_tree, merge_commit, merge_tree


def _merge_metadata(
    authority: dict[str, Any],
    *,
    implementation_commit: str,
    implementation_tree: str,
    task_id: str = "DQK-001",
) -> tuple[Any, dict[str, Any], tuple[str, ...], str]:
    source = authority["source"]
    task = source.get_task(task_id)
    assert task is not None
    source_identity = program._repository_task_source_identity(
        source, source.snapshot()
    )
    writer = source.current_writer_fence()
    task_slug = task_id.lower()
    proposal_receipt_id = f"proposal-receipt:{task_slug}"
    result_record = {
        "command": "python -m pytest -q focused.py",
        "validation_id": f"validation:{task_slug}",
        "validation_result_digest": "sha256:" + "1" * 64,
        "returncode": 0,
        "passed": True,
    }
    validation_proof: dict[str, Any] = {
        "attempted": True,
        "passed": True,
        "returncode": 0,
        "target_commit": implementation_commit,
        "target_tree": implementation_tree,
        "repository_tree_id": f"git-tree:{implementation_tree}",
        "selection": {"scope": "pre_merge"},
        "results": [result_record],
        "proposal_gate": {
            "accepted": True,
            "receipt_id": proposal_receipt_id,
        },
    }
    execution_receipt = DuckDBValidationExecutionReceipt(
        task_cid=task.task_cid,
        task_source_identity_id=source_identity["identity_id"],
        target_commit=implementation_commit,
        target_tree=implementation_tree,
        selection_scope="pre_merge",
        validation_result_digests=(result_record["validation_result_digest"],),
        validation_ids=(result_record["validation_id"],),
        proposal_receipt_id=proposal_receipt_id,
        compact_proof_digest=_duckdb_compact_validation_proof_digest(
            validation_proof
        ),
    )
    validation_receipt_ids = (execution_receipt.receipt_id,)
    validation_proof.update(
        {
            "validation_execution_receipt": execution_receipt.to_record(),
            "validation_receipt_ids": list(validation_receipt_ids),
        }
    )
    canonical_task_key = f"task-key:{task_slug}"
    metadata = {
        "schema": program._MERGE_CANDIDATE_SCHEMA,
        "target_binding_schema": program._MERGE_TARGET_BINDING_SCHEMA,
        "target_repository_id": program._repository_id(),
        "target_branch": TARGET_BRANCH,
        "baseline_ref": authority["seed_commit"],
        "implementation_commit": implementation_commit,
        "candidate_tree": implementation_tree,
        "repository_tree_id": f"git-tree:{implementation_tree}",
        "todo_path": str(program.DATABASE_PATH),
        "repo_root": str(authority["repository"]),
        "task": {"task_id": task.task_id},
        "canonical_task_cid": task.task_cid,
        "canonical_task_key": canonical_task_key,
        "task_source_identity": source_identity,
        "task_source_writer": {
            "writer_id": writer.writer_id,
            "fencing_token": writer.fencing_token,
        },
        "validation_proof": validation_proof,
    }
    assert PortalImplementationDaemon._merge_completion_receipt_binding(
        metadata
    ) == (validation_receipt_ids, proposal_receipt_id)
    return task, metadata, validation_receipt_ids, proposal_receipt_id


def _write_queue_row(
    authority: dict[str, Any],
    *,
    task: Any,
    request_id: str,
    metadata: dict[str, Any],
    implementation_commit: str,
    status: str,
    claim_generation: int,
    finished_at: float,
    claimed_at: float = 0.0,
    consumer_id: str = "",
    claim_token: str = "",
) -> None:
    database = authority["merge_queue_root"] / "merge_queue.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            """CREATE TABLE merge_requests (
                   request_id VARCHAR PRIMARY KEY,
                   branch_name VARCHAR NOT NULL,
                   task_id VARCHAR NOT NULL,
                   attempt INTEGER NOT NULL,
                   metadata_json VARCHAR NOT NULL,
                   commit_sha VARCHAR NOT NULL,
                   canonical_task_id VARCHAR NOT NULL,
                   canonical_task_key VARCHAR NOT NULL,
                   status VARCHAR NOT NULL,
                   claimed_at DOUBLE NOT NULL,
                   consumer_id VARCHAR NOT NULL,
                   claim_token VARCHAR NOT NULL,
                   claim_generation BIGINT NOT NULL,
                   failure_count INTEGER NOT NULL,
                   finished_at DOUBLE NOT NULL
               )"""
        )
        connection.execute(
            "INSERT INTO merge_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                "agent/dqk-001",
                task.task_id,
                1,
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                implementation_commit,
                task.task_cid,
                metadata["canonical_task_key"],
                status,
                claimed_at,
                consumer_id,
                claim_token,
                claim_generation,
                0,
                finished_at,
            ),
        )
    finally:
        connection.close()


def _persist_merge_integrated(
    authority: dict[str, Any],
    *,
    task: Any,
    metadata: dict[str, Any],
    request_id: str,
    implementation_commit: str,
    implementation_tree: str,
    merge_commit: str,
    merge_tree: str,
    merge_parents: tuple[str, str],
    claim_generation: int = 1,
    consumer_id: str = "merge-train:test",
    claim_token: str = "claim:test",
    validation_receipt_ids: tuple[str, ...] | None = None,
    proposal_receipt_id: str | None = None,
) -> tuple[DuckDBMergeIntegratedReceipt, Path]:
    validation_ids, proposal_id = (
        PortalImplementationDaemon._merge_completion_receipt_binding(metadata)
    )
    writer = authority["source"].current_writer_fence()
    receipt = DuckDBMergeIntegratedReceipt(
        repository_id=program._repository_id(),
        target_branch=TARGET_BRANCH,
        request_id=request_id,
        task_id=task.task_id,
        task_cid=task.task_cid,
        task_source_identity_id=metadata["task_source_identity"]["identity_id"],
        task_source_writer_id=writer.writer_id,
        task_source_fencing_token=writer.fencing_token,
        candidate_commit=implementation_commit,
        candidate_tree=implementation_tree,
        merge_commit=merge_commit,
        merge_tree=merge_tree,
        merge_parents=merge_parents,
        merge_consumer_id=consumer_id,
        lease_id=claim_token,
        fencing_token=claim_generation,
        validation_receipt_ids=(
            validation_ids
            if validation_receipt_ids is None
            else validation_receipt_ids
        ),
        proposal_receipt_id=(
            proposal_id
            if proposal_receipt_id is None
            else proposal_receipt_id
        ),
    )
    persisted = PortalImplementationDaemon._persist_merge_integrated_receipt(
        authority["merge_queue_root"], receipt
    )
    path = authority["merge_queue_root"] / "train/receipts" / (
        "merge-integrated-"
        + receipt.receipt_id.removeprefix("sha256:")
        + ".json"
    )
    assert persisted == receipt
    assert DuckDBMergeIntegratedReceipt.load_file(path) == receipt
    return receipt, path


def _post_merge_evidence_payload(
    authority: dict[str, Any],
    *,
    task: Any,
    policy_id: str,
    candidate_tree: str,
    merge_commit: str,
    merge_tree: str,
) -> dict[str, Any]:
    observed_at = "2035-01-01T00:00:00+00:00"
    freshness_deadline = "2035-01-01T01:00:00+00:00"
    candidate_tree_id = f"git-tree:{candidate_tree}"
    merged_tree_id = f"git-tree:{merge_tree}"
    repository_id = program._repository_id()
    validation_plan = build_impact_selected_validation_dag(
        impact_index=CodeImpactIndex(
            repository_tree_id=merged_tree_id,
            symbol_paths={},
            symbol_dependencies={},
            path_dependencies={"implementation.txt": ()},
            validation_targets={},
        ),
        checks=(
            ImpactValidationCheck(
                "unit",
                ImpactValidationKind.UNIT,
                "pytest -q focused.py",
                cacheable=False,
            ),
        ),
        changed_paths=("implementation.txt",),
        repository_policy=RepositoryValidationPolicy(
            required_kinds=(ImpactValidationKind.UNIT,),
            kind_dependencies={},
            require_acceptance_coverage=False,
            require_transitive_validation=False,
        ),
    )
    planned = validation_plan.nodes[0]
    validation_receipt = ImpactValidationDAGReceipt(
        dag=validation_plan,
        nodes=(
            ImpactValidationNodeReceipt(
                check_id=planned.check_id,
                kind=planned.check.kind,
                technique=planned.check.technique,
                command=planned.check.command,
                disposition=ValidationNodeDisposition.SUCCEEDED,
                reason="validation_passed",
                mandatory=planned.mandatory,
                selection_reasons=planned.selection_reasons,
                depends_on=planned.depends_on,
                returncode=0,
                result_digest="sha256:" + "3" * 64,
            ),
        ),
        passed=True,
        started_at=observed_at,
        finished_at=observed_at,
    ).to_dict()
    validation_report = {
        "passed": True,
        "target_tree_id": merged_tree_id,
        "hermetic": True,
        "hermetic_policy": {
            "policy_id": "hermetic@1",
            "complete_selected_dag": True,
        },
        "impact_validation_receipt": validation_receipt,
        "results": [
            {
                "validation_id": "unit",
                "returncode": 0,
                "outcome": "passed",
                "authoritative": True,
                "stable": True,
                "attempts": [
                    {"attempt_number": 1, "returncode": 0},
                    {"attempt_number": 2, "returncode": 0},
                ],
                "runtime_id": "runtime-unit",
                "hermetic_runtime": {
                    "runtime_id": "runtime-unit",
                    "repository_tree_id": merged_tree_id,
                    "network_mode": "none",
                    "filesystem_mode": "read_only_root_workspace",
                },
                "validation_result_digest": "sha256:" + "3" * 64,
            }
        ],
        "seeded_defect_summary": {
            "seeded_count": 1,
            "detected_count": 1,
            "escaped_count": 0,
            "zero_escaped": True,
        },
        "escaped_seeded_defect_ids": [],
    }

    def proof(obligation_id: str, kernel_id: str) -> dict[str, Any]:
        return ProofReceipt(
            obligation_id=obligation_id,
            plan_id="plan:dqk-restart",
            attempt_id=f"attempt:{obligation_id}",
            repository_id=repository_id,
            repository_tree_id=merged_tree_id,
            ast_scope_ids=("post-merge-restart",),
            premise_ids=(),
            translator_id="translator:fixture",
            solver_id="solver:fixture",
            kernel_id=kernel_id,
            toolchain_id="toolchain:fixture",
            policy_id=policy_id,
            resource_budget=ResourceBudget(
                wall_time_ms=10_000,
                cpu_time_ms=8_000,
                memory_bytes=64 * 1024 * 1024,
                max_processes=2,
            ),
            verdict=ProofVerdict.PROVED,
            evidence=(
                ProofEvidence(
                    kind=EvidenceKind.KERNEL_VERIFICATION,
                    authority=EvidenceAuthority.KERNEL,
                    verdict=EvidenceVerdict.ACCEPTED,
                    artifact_id=f"artifact:{obligation_id}",
                    subject_id=obligation_id,
                    verifier_id=kernel_id,
                    independent=True,
                ),
            ),
            started_at=observed_at,
            finished_at=observed_at,
        ).to_dict()

    criterion = POST_MERGE_EVIDENCE_ACCEPTANCE_CRITERIA[0]
    receipt = assemble_post_merge_evidence(
        repository_id=repository_id,
        task_id=task.task_id,
        policy_id=policy_id,
        candidate_tree_id=candidate_tree_id,
        merged_tree_id=merged_tree_id,
        merge_commit_id=merge_commit,
        current_repository_tree_id=merged_tree_id,
        assembled_at=observed_at,
        freshness_deadline=freshness_deadline,
        proposal_admission={
            "proposal_id": "proposal:dqk-001",
            "receipt_id": "proposal-receipt:dqk-001",
            "task_id": task.task_id,
            "policy_id": policy_id,
            "repository_tree_id": candidate_tree_id,
            "accepted": True,
        },
        validation_report=validation_report,
        validation_receipt=validation_receipt,
        semantic_checks=(
            {
                "validation_receipt_id": "semantic:dqk-001",
                "repository_tree_id": merged_tree_id,
                "status": "passed",
                "freshness": "current",
                "observed_at": observed_at,
            },
        ),
        protocol_checks=(
            {
                "validation_receipt_id": "protocol:dqk-001",
                "repository_tree_id": merged_tree_id,
                "status": "passed",
                "freshness": "current",
                "observed_at": observed_at,
            },
        ),
        legal_logic_obligations=(
            {
                "obligation_id": "legal:dqk-001",
                "receipt_id": "legal-receipt:dqk-001",
                "repository_tree_id": merged_tree_id,
                "status": "proved",
                "freshness": "current",
                "observed_at": observed_at,
            },
        ),
        theorem_obligations=(
            {
                "obligation_id": "theorem:dqk-001",
                "receipt_id": "theorem-receipt:dqk-001",
                "repository_tree_id": merged_tree_id,
                "status": "proved",
                "freshness": "current",
                "observed_at": observed_at,
            },
        ),
        proof_receipts=(
            proof("legal:dqk-001", "kernel:legal"),
            proof("theorem:dqk-001", "kernel:theorem"),
        ),
        merge_record={
            "merge_receipt_id": "merge-receipt:dqk-001",
            "task_id": task.task_id,
            "candidate_tree_id": candidate_tree_id,
            "repository_tree_id": merged_tree_id,
            "merged_tree_id": merged_tree_id,
            "merge_commit_id": merge_commit,
            "status": "merged",
            "completion_status": "completed",
            "freshness": "current",
            "observed_at": observed_at,
        },
        criterion_coverage=(
            {
                "criterion": criterion,
                "repository_tree_id": merged_tree_id,
                "implementation": ["implementation.txt"],
                "receipt_ids": [
                    "proposal-receipt:dqk-001",
                    validation_receipt["receipt_id"],
                    "semantic:dqk-001",
                    "protocol:dqk-001",
                    "proof receipts are content addressed",
                    "merge-receipt:dqk-001",
                ],
                "freshness": "current",
                "observed_at": observed_at,
            },
        ),
        merged_tree_records={
            "ast_records": [
                {
                    "scope_id": "post-merge-restart",
                    "kind": "qualified_symbol",
                    "qualified_symbol": "restart.fixture.acceptance",
                    "repository_tree_id": merged_tree_id,
                    "path": "implementation.txt",
                    "source_hash": "sha256:" + "4" * 64,
                }
            ]
        },
    )
    assert receipt.accepted is True
    return receipt.to_dict()


def _persist_parallel_acceptance(
    authority: dict[str, Any],
    *,
    task: Any,
    metadata: dict[str, Any],
    request_id: str,
    implementation_commit: str,
    implementation_tree: str,
    merge_commit: str,
    merge_tree: str,
    claim_generation: int,
    consumer_id: str,
    claim_token: str,
) -> Path:
    Receipt = program._repository_parallel_acceptance_type()
    policy_id = "policy:dqk-restart-admission"
    metadata["policy_id"] = policy_id
    evidence_payload = _post_merge_evidence_payload(
        authority,
        task=task,
        policy_id=policy_id,
        candidate_tree=implementation_tree,
        merge_commit=merge_commit,
        merge_tree=merge_tree,
    )
    validation_receipt_id = str(evidence_payload["receipt_id"])
    merged_tree_validation_receipt_id = "validation:merged-tree"
    acceptance_validation_receipt_ids = tuple(
        sorted(
            (
                validation_receipt_id,
                merged_tree_validation_receipt_id,
            )
        )
    )
    receipt = Receipt(
        request_id=request_id,
        canonical_task_id=task.task_cid,
        candidate_commit=implementation_commit,
        target_commit=merge_commit,
        preflight={"passed": True, "target_sensitive": False},
        integration={
            "status": "merged",
            "integrated": True,
            "request_id": request_id,
            "canonical_task_id": task.task_cid,
            "commit_sha": implementation_commit,
            "target_commit": merge_commit,
        },
        post_merge_validation={
            "passed": True,
            "validated_commit": merge_commit,
            "repository_tree_id": f"git-tree:{merge_tree}",
            "validation_receipt_id": merged_tree_validation_receipt_id,
            "validation_receipt_ids": list(
                acceptance_validation_receipt_ids
            ),
            "post_merge_evidence": {
                "passed": True,
                "reason": "",
                "reason_codes": [],
                "receipt": evidence_payload,
                "receipt_id": validation_receipt_id,
                "repository_tree_id": f"git-tree:{merge_tree}",
                "merge_commit": merge_commit,
            },
            "post_merge_evidence_receipt": evidence_payload,
        },
        mutation_fence_owner=consumer_id,
        mutation_fence_generation=claim_generation,
        mutation_fence_token_digest=(
            "sha256:" + hashlib.sha256(claim_token.encode("utf-8")).hexdigest()
        ),
        accepted=True,
        validation_receipt_ids=acceptance_validation_receipt_ids,
    )
    payload = receipt.to_dict()
    receipt_id = str(payload["receipt_id"])
    receipt_directory = authority["merge_queue_root"] / "train/receipts"
    receipt_directory.mkdir(parents=True)
    receipt_path = receipt_directory / f"acceptance-{receipt_id.removeprefix('sha256:')}.json"
    receipt_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    metadata["completion"] = {
        "acceptance_receipt_id": receipt_id,
        "requirement_id": program._PARALLEL_ACCEPTANCE_REQUIREMENT_ID,
        "target_commit": merge_commit,
        "post_merge_evidence_receipt_id": validation_receipt_id,
        "post_merge_evidence_requirement_id": (
            program._POST_MERGE_EVIDENCE_REQUIREMENT_ID
        ),
    }
    return receipt_path


def test_restart_admits_one_receipted_task_merge_and_rejects_foreign_queue_binding(
    restart_authority: dict[str, Any],
) -> None:
    repository = restart_authority["repository"]
    implementation, implementation_tree, merge_commit, merge_tree = (
        _merge_one_implementation(repository)
    )
    task, metadata, validation_ids, proposal_id = _merge_metadata(
        restart_authority,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
    )
    request_id = "merge-request:dqk-001:1"
    writer = restart_authority["source"].current_writer_fence()
    evidence = DuckDBTaskCompletionEvidence(
        task_cid=task.task_cid,
        task_source_identity_id=metadata["task_source_identity"]["identity_id"],
        implementation_commit=implementation,
        merge_commit=merge_commit,
        target_tree=merge_tree,
        validation_receipt_ids=validation_ids,
        proposal_receipt_id=proposal_id,
        merge_request_id=request_id,
        merge_consumer_id="merge-train:test",
        lease_id="claim:test",
        fencing_token=1,
        task_source_writer_id=writer.writer_id,
        task_source_fencing_token=writer.fencing_token,
    )
    current = restart_authority["source"].get_task(task.task_id)
    assert current is not None
    restart_authority["source"].compare_and_set_status(
        task.task_id,
        expected_revision=current.revision,
        status="completed",
        receipt={
            "operation": "mark_task_completed",
            "task_source_identity_id": metadata["task_source_identity"][
                "identity_id"
            ],
            "completion_evidence": evidence.to_record(),
        },
    )
    # Model claim recovery and re-dequeue after the task completion CAS.  The
    # completion evidence retains generation 1, while the final typed
    # acceptance receipt binds the authoritative recovered claim at generation
    # 3 and queue completion advances the row to generation 4.
    acceptance_path = _persist_parallel_acceptance(
        restart_authority,
        task=task,
        metadata=metadata,
        request_id=request_id,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
        merge_commit=merge_commit,
        merge_tree=merge_tree,
        claim_generation=3,
        consumer_id="merge-train:recovered",
        claim_token="claim:recovered",
    )
    _write_queue_row(
        restart_authority,
        task=task,
        request_id=request_id,
        metadata=metadata,
        implementation_commit=implementation,
        status="completed",
        claim_generation=4,
        finished_at=1.0,
    )
    queue_database = restart_authority["merge_queue_root"] / "merge_queue.duckdb"
    valid_acceptance_payload = json.loads(acceptance_path.read_text(encoding="utf-8"))
    Receipt = program._repository_parallel_acceptance_type()
    valid_acceptance = Receipt.from_dict(valid_acceptance_payload)

    def select_acceptance(
        receipt_payload: dict[str, Any], *, post_merge_receipt_id: str
    ) -> Path:
        selected_path = acceptance_path.parent / (
            "acceptance-"
            + str(receipt_payload["receipt_id"]).removeprefix("sha256:")
            + ".json"
        )
        selected_path.write_text(
            json.dumps(receipt_payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        selected_metadata = json.loads(json.dumps(metadata))
        selected_metadata["completion"].update(
            {
                "acceptance_receipt_id": receipt_payload["receipt_id"],
                "post_merge_evidence_receipt_id": post_merge_receipt_id,
            }
        )
        connection = duckdb.connect(str(queue_database))
        try:
            connection.execute(
                "UPDATE merge_requests SET metadata_json=? WHERE request_id=?",
                (
                    json.dumps(
                        selected_metadata,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    request_id,
                ),
            )
        finally:
            connection.close()
        return selected_path

    def acceptance_variant(
        validation: dict[str, Any], validation_receipt_ids: tuple[str, ...]
    ) -> dict[str, Any]:
        return Receipt(
            request_id=valid_acceptance.request_id,
            canonical_task_id=valid_acceptance.canonical_task_id,
            candidate_commit=valid_acceptance.candidate_commit,
            target_commit=valid_acceptance.target_commit,
            preflight=valid_acceptance.preflight,
            integration=valid_acceptance.integration,
            post_merge_validation=validation,
            mutation_fence_owner=valid_acceptance.mutation_fence_owner,
            mutation_fence_generation=(
                valid_acceptance.mutation_fence_generation
            ),
            mutation_fence_token_digest=(
                valid_acceptance.mutation_fence_token_digest
            ),
            accepted=True,
            validation_receipt_ids=validation_receipt_ids,
        ).to_dict()

    acceptance_text = acceptance_path.read_text(encoding="utf-8")
    acceptance_path.unlink()
    missing, missing_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not missing
    assert "acceptance receipt projection is unavailable" in missing_detail
    acceptance_path.write_text(acceptance_text, encoding="utf-8")

    missing_evidence_validation = json.loads(
        json.dumps(valid_acceptance.post_merge_validation)
    )
    missing_evidence_validation.pop("post_merge_evidence_receipt")
    missing_evidence_payload = acceptance_variant(
        missing_evidence_validation,
        tuple(valid_acceptance.validation_receipt_ids),
    )
    select_acceptance(
        missing_evidence_payload,
        post_merge_receipt_id=str(
            valid_acceptance.post_merge_validation[
                "post_merge_evidence_receipt"
            ]["receipt_id"]
        ),
    )
    missing_evidence, missing_evidence_detail = (
        program._repository_binding_is_launch_compatible(
            restart_authority["repository_binding"],
            source=restart_authority["source"],
        )
    )
    assert not missing_evidence
    assert (
        "launch_blocker=post_merge_evidence_receipt_missing_from_acceptance"
        in missing_evidence_detail
    )

    forged_validation = json.loads(
        json.dumps(valid_acceptance.post_merge_validation)
    )
    forged_post_merge_id = "0" * 64
    forged_post_merge = dict(
        forged_validation["post_merge_evidence_receipt"]
    )
    forged_post_merge["receipt_id"] = forged_post_merge_id
    forged_validation["post_merge_evidence_receipt"] = forged_post_merge
    forged_validation["post_merge_evidence"]["receipt"] = forged_post_merge
    forged_validation["post_merge_evidence"]["receipt_id"] = (
        forged_post_merge_id
    )
    forged_validation_ids = tuple(
        sorted((forged_post_merge_id, "validation:merged-tree"))
    )
    forged_validation["validation_receipt_ids"] = list(
        forged_validation_ids
    )
    forged_payload = acceptance_variant(
        forged_validation, forged_validation_ids
    )
    select_acceptance(
        forged_payload, post_merge_receipt_id=forged_post_merge_id
    )
    forged, forged_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not forged
    assert "post-merge evidence receipt identity mismatch" in forged_detail

    empty_validation = json.loads(
        json.dumps(valid_acceptance.post_merge_validation)
    )
    empty_validation["validation_receipt_ids"] = []
    empty_payload = acceptance_variant(empty_validation, ())
    select_acceptance(
        empty_payload,
        post_merge_receipt_id=str(
            empty_validation["post_merge_evidence_receipt"]["receipt_id"]
        ),
    )
    empty, empty_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not empty
    assert "parallel acceptance receipt is stale, incomplete, or foreign" in empty_detail

    select_acceptance(
        valid_acceptance_payload,
        post_merge_receipt_id=str(
            valid_acceptance.post_merge_validation[
                "post_merge_evidence_receipt"
            ]["receipt_id"]
        ),
    )

    compatible, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert compatible, detail
    assert "receipt_merges=1" in detail
    assert "task_cas_crash_tip=none" in detail

    connection = duckdb.connect(str(queue_database))
    try:
        unsupported_bundle = dict(metadata)
        unsupported_bundle["bundle_work_order"] = {
            "primary_task_id": task.task_id,
            "covered_task_ids": ["DQK-002"],
        }
        connection.execute(
            "UPDATE merge_requests SET metadata_json=? WHERE request_id=?",
            (
                json.dumps(
                    unsupported_bundle,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                request_id,
            ),
        )
    finally:
        connection.close()
    bundled, bundled_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not bundled
    assert (
        "launch_blocker=typed_bundle_completion_receipt_set_missing"
        in bundled_detail
    )

    connection = duckdb.connect(str(queue_database))
    try:
        foreign = dict(metadata)
        foreign["target_repository_id"] = "repository:foreign"
        connection.execute(
            "UPDATE merge_requests SET metadata_json=? WHERE request_id=?",
            (
                json.dumps(foreign, sort_keys=True, separators=(",", ":")),
                request_id,
            ),
        )
    finally:
        connection.close()
    rejected, rejection_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not rejected
    assert "foreign" in rejection_detail


def test_restart_admits_exact_merge_integrated_tip_then_post_cas_processing_tip(
    restart_authority: dict[str, Any],
) -> None:
    repository = restart_authority["repository"]
    implementation, implementation_tree, merge_commit, merge_tree = (
        _merge_one_implementation(repository)
    )
    task, metadata, validation_ids, proposal_id = _merge_metadata(
        restart_authority,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
    )
    request_id = "merge-request:dqk-001:processing"
    _write_queue_row(
        restart_authority,
        task=task,
        request_id=request_id,
        metadata=metadata,
        implementation_commit=implementation,
        status="processing",
        claim_generation=1,
        finished_at=0.0,
        claimed_at=1.0,
        consumer_id="merge-train:test",
        claim_token="claim:test",
    )

    rejected, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not rejected
    assert (
        "launch_blocker=merge_integrated_receipt_missing_before_task_cas:"
        + request_id
    ) in detail

    parents = tuple(
        _git(
            repository,
            "rev-list",
            "--parents",
            "-n",
            "1",
            merge_commit,
        ).split()[1:]
    )
    assert len(parents) == 2
    _receipt, receipt_path = _persist_merge_integrated(
        restart_authority,
        task=task,
        metadata=metadata,
        request_id=request_id,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
        merge_commit=merge_commit,
        merge_tree=merge_tree,
        merge_parents=parents,
    )
    (receipt_path.parent / "acceptance-corrupt.json").write_text(
        "this unrelated projection is intentionally not JSON\n",
        encoding="utf-8",
    )
    compatible, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert compatible, detail
    assert f"merge_integrated_crash_tip={request_id}" in detail
    assert "task_cas_crash_tip=none" in detail

    writer = restart_authority["source"].current_writer_fence()
    evidence = DuckDBTaskCompletionEvidence(
        task_cid=task.task_cid,
        task_source_identity_id=metadata["task_source_identity"]["identity_id"],
        implementation_commit=implementation,
        merge_commit=merge_commit,
        target_tree=merge_tree,
        validation_receipt_ids=validation_ids,
        proposal_receipt_id=proposal_id,
        merge_request_id=request_id,
        merge_consumer_id="merge-train:test",
        lease_id="claim:test",
        fencing_token=1,
        task_source_writer_id=writer.writer_id,
        task_source_fencing_token=writer.fencing_token,
    )
    current = restart_authority["source"].get_task(task.task_id)
    assert current is not None
    restart_authority["source"].compare_and_set_status(
        task.task_id,
        expected_revision=current.revision,
        status="completed",
        receipt={
            "operation": "mark_task_completed",
            "task_source_identity_id": metadata["task_source_identity"][
                "identity_id"
            ],
            "completion_evidence": evidence.to_record(),
        },
    )

    compatible, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert compatible, detail
    assert f"task_cas_crash_tip={request_id}" in detail

    _write_and_commit(repository, "unrelated.txt", "unrelated\n", "unrelated")
    rejected, rejection_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not rejected
    assert "single HEAD crash tip" in rejection_detail


def test_merge_integrated_restart_rejects_stale_ambiguous_and_unsafe_authority(
    restart_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = restart_authority["repository"]
    implementation, implementation_tree, merge_commit, merge_tree = (
        _merge_one_implementation(repository)
    )
    task, metadata, _validation_ids, _proposal_id = _merge_metadata(
        restart_authority,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
    )
    request_id = "merge-request:dqk-001:integrated-negatives"
    _write_queue_row(
        restart_authority,
        task=task,
        request_id=request_id,
        metadata=metadata,
        implementation_commit=implementation,
        status="processing",
        claim_generation=1,
        finished_at=0.0,
        claimed_at=1.0,
        consumer_id="merge-train:test",
        claim_token="claim:test",
    )
    parents = tuple(
        _git(
            repository,
            "rev-list",
            "--parents",
            "-n",
            "1",
            merge_commit,
        ).split()[1:]
    )
    _receipt, receipt_path = _persist_merge_integrated(
        restart_authority,
        task=task,
        metadata=metadata,
        request_id=request_id,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
        merge_commit=merge_commit,
        merge_tree=merge_tree,
        merge_parents=parents,
    )
    queue_database = restart_authority["merge_queue_root"] / "merge_queue.duckdb"

    connection = duckdb.connect(str(queue_database))
    try:
        connection.execute(
            "UPDATE merge_requests SET claim_generation=2 WHERE request_id=?",
            (request_id,),
        )
    finally:
        connection.close()
    stale, stale_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not stale
    assert "fencing_token" in stale_detail

    connection = duckdb.connect(str(queue_database))
    try:
        connection.execute(
            "UPDATE merge_requests SET claim_generation=1 WHERE request_id=?",
            (request_id,),
        )
    finally:
        connection.close()
    _stale_receipt, stale_receipt_path = _persist_merge_integrated(
        restart_authority,
        task=task,
        metadata=metadata,
        request_id=request_id,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
        merge_commit=merge_commit,
        merge_tree=merge_tree,
        merge_parents=parents,
        claim_generation=2,
        claim_token="claim:stale",
    )
    ambiguous, ambiguous_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not ambiguous
    assert "receipt authority is ambiguous" in ambiguous_detail
    stale_receipt_path.unlink()

    compound_metadata = json.loads(json.dumps(metadata))
    compound_metadata["changed_submodule_paths"] = ["ipfs_accelerate_py"]
    connection = duckdb.connect(str(queue_database))
    try:
        connection.execute(
            "UPDATE merge_requests SET metadata_json=? WHERE request_id=?",
            (
                json.dumps(
                    compound_metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                request_id,
            ),
        )
    finally:
        connection.close()
    compound, compound_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not compound
    assert "typed_compound_integration_receipt_set_missing" in compound_detail

    connection = duckdb.connect(str(queue_database))
    try:
        connection.execute(
            "UPDATE merge_requests SET metadata_json=? WHERE request_id=?",
            (
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                request_id,
            ),
        )
    finally:
        connection.close()
    receipt_directory = receipt_path.parent
    real_receipt_directory = receipt_directory.with_name("receipts-real")
    receipt_directory.rename(real_receipt_directory)
    receipt_directory.symlink_to(real_receipt_directory, target_is_directory=True)
    unsafe, unsafe_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not unsafe
    assert "symlink or non-directory ancestor" in unsafe_detail
    receipt_directory.unlink()
    real_receipt_directory.rename(receipt_directory)

    receipt_directory.rename(real_receipt_directory)
    receipt_directory.write_text("not a directory\n", encoding="utf-8")
    non_directory, non_directory_detail = (
        program._repository_binding_is_launch_compatible(
            restart_authority["repository_binding"],
            source=restart_authority["source"],
        )
    )
    assert not non_directory
    assert "symlink or non-directory ancestor" in non_directory_detail
    receipt_directory.unlink()
    real_receipt_directory.rename(receipt_directory)

    with monkeypatch.context() as context:
        context.setattr(program, "_MAX_MERGE_INTEGRATED_RECEIPTS", 0)
        unbounded, unbounded_detail = program._repository_binding_is_launch_compatible(
            restart_authority["repository_binding"],
            source=restart_authority["source"],
        )
    assert not unbounded
    assert "receipt scan exceeds its bound" in unbounded_detail

    original_rows = program._repository_merge_queue_rows
    calls = 0

    def changed_on_reread() -> dict[str, dict[str, Any]]:
        nonlocal calls
        calls += 1
        rows = original_rows()
        if calls == 2:
            rows[request_id] = dict(rows[request_id])
            rows[request_id]["claim_generation"] = 2
        return rows

    with monkeypatch.context() as context:
        context.setattr(program, "_repository_merge_queue_rows", changed_on_reread)
        raced, raced_detail = program._repository_binding_is_launch_compatible(
            restart_authority["repository_binding"],
            source=restart_authority["source"],
        )
    assert not raced
    assert "queue claim changed at reread" in raced_detail


def test_merge_integrated_restart_rejects_an_actual_gitlink_change(
    restart_authority: dict[str, Any],
) -> None:
    repository = restart_authority["repository"]
    seed_commit = _git(repository, "rev-parse", TARGET_BRANCH)
    _git(repository, "checkout", "-b", "agent/dqk-001-gitlink")
    _git(
        repository / "ipfs_accelerate_py",
        "checkout",
        restart_authority["accelerator_v2"],
    )
    _git(repository, "add", "--", "ipfs_accelerate_py")
    _git(repository, "commit", "-m", "DQK-001: change accelerator gitlink")
    implementation = _git(repository, "rev-parse", "HEAD")
    implementation_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    _git(repository, "checkout", TARGET_BRANCH)
    _git(
        repository,
        "merge",
        "--no-ff",
        "agent/dqk-001-gitlink",
        "-m",
        "Merge DQK-001",
    )
    merge_commit = _git(repository, "rev-parse", "HEAD")
    merge_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    parents = (seed_commit, implementation)

    task, metadata, _validation_ids, _proposal_id = _merge_metadata(
        restart_authority,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
    )
    request_id = "merge-request:dqk-001:gitlink"
    _write_queue_row(
        restart_authority,
        task=task,
        request_id=request_id,
        metadata=metadata,
        implementation_commit=implementation,
        status="processing",
        claim_generation=1,
        finished_at=0.0,
        claimed_at=1.0,
        consumer_id="merge-train:test",
        claim_token="claim:test",
    )
    _persist_merge_integrated(
        restart_authority,
        task=task,
        metadata=metadata,
        request_id=request_id,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
        merge_commit=merge_commit,
        merge_tree=merge_tree,
        merge_parents=parents,
    )

    compatible, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not compatible
    assert "typed_compound_integration_receipt_set_missing" in detail


def test_restart_never_admits_an_unclaimed_pending_queue_row(
    restart_authority: dict[str, Any],
) -> None:
    repository = restart_authority["repository"]
    implementation, implementation_tree, _merge_commit, _merge_tree = (
        _merge_one_implementation(repository)
    )
    task, metadata, _validation_ids, _proposal_id = _merge_metadata(
        restart_authority,
        implementation_commit=implementation,
        implementation_tree=implementation_tree,
    )
    request_id = "merge-request:dqk-001:pending"
    _write_queue_row(
        restart_authority,
        task=task,
        request_id=request_id,
        metadata=metadata,
        implementation_commit=implementation,
        status="pending",
        claim_generation=2,
        finished_at=0.0,
    )

    compatible, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not compatible
    assert f"launch_blocker=unclaimed_pending_merge_request:{request_id}" in detail


def test_restart_admits_only_self_verifying_atomic_export_commit(
    restart_authority: dict[str, Any],
) -> None:
    repository = restart_authority["repository"]
    body = (
        "# Generated plan\n\n"
        "> Generated projection only. The DuckDB task source is authoritative."
    )
    rendered = (
        body
        + "\n<!-- rendered-body-sha256: "
        + program._sha256_text(body)
        + " -->\n"
    )
    _write_and_commit(
        repository,
        "docs/architecture/generated-plan.md",
        rendered,
        "export generated plan",
    )
    compatible, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert compatible, detail
    assert "transport_exports=1" in detail

    export_path = repository / "docs/architecture/generated-plan.md"
    export_path.write_text(rendered.replace("Generated plan", "Forged plan"), encoding="utf-8")
    _git(repository, "add", "--", "docs/architecture/generated-plan.md")
    _git(repository, "commit", "-m", "forge generated plan")
    rejected, rejection_detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=restart_authority["source"],
    )
    assert not rejected
    assert "unadmitted linear commit" in rejection_detail


@pytest.mark.parametrize(
    ("acknowledged_at", "expires_at", "expected_rejection"),
    (
        (
            "2035-01-01T00:00:00+00:00",
            "2035-01-02T00:00:00+00:00",
            "launch_blocker=manual_gate_authenticated_execution_missing",
        ),
        (
            "2025-01-01T00:00:00+00:00",
            "2025-01-02T00:00:00+00:00",
            "launch_blocker=manual_gate_authenticated_execution_missing",
        ),
    ),
)
def test_restart_blocks_unauthenticated_or_expired_dqk_056_ack(
    restart_authority: dict[str, Any],
    acknowledged_at: str,
    expires_at: str,
    expected_rejection: str,
) -> None:
    repository = restart_authority["repository"]
    verifier_body = (
        "#!/usr/bin/env python3\n"
        "# implemented typed DQP release verifier fixture\n"
    )
    (
        verifier_implementation,
        verifier_implementation_tree,
        verifier_merge,
        verifier_merge_tree,
    ) = _merge_one_implementation(
        repository,
        task_id=program.RELEASE_VERIFIER_TASK_ID,
        relative_path=(
            "scripts/validation/validate_accelerate_duckdb_quack_release.py"
        ),
        value=verifier_body,
    )
    verifier_task, verifier_metadata, validation_ids, proposal_id = (
        _merge_metadata(
            restart_authority,
            implementation_commit=verifier_implementation,
            implementation_tree=verifier_implementation_tree,
            task_id=program.RELEASE_VERIFIER_TASK_ID,
        )
    )
    request_id = "merge-request:dqk-057:1"
    writer = restart_authority["source"].current_writer_fence()
    verifier_evidence = DuckDBTaskCompletionEvidence(
        task_cid=verifier_task.task_cid,
        task_source_identity_id=verifier_metadata["task_source_identity"][
            "identity_id"
        ],
        implementation_commit=verifier_implementation,
        merge_commit=verifier_merge,
        target_tree=verifier_merge_tree,
        validation_receipt_ids=validation_ids,
        proposal_receipt_id=proposal_id,
        merge_request_id=request_id,
        merge_consumer_id="merge-train:verifier",
        lease_id="claim:verifier",
        fencing_token=1,
        task_source_writer_id=writer.writer_id,
        task_source_fencing_token=writer.fencing_token,
    )
    restart_authority["source"].compare_and_set_status(
        verifier_task.task_id,
        expected_revision=verifier_task.revision,
        status="completed",
        receipt={
            "operation": "mark_task_completed",
            "task_source_identity_id": verifier_metadata[
                "task_source_identity"
            ]["identity_id"],
            "completion_evidence": verifier_evidence.to_record(),
        },
    )
    _persist_parallel_acceptance(
        restart_authority,
        task=verifier_task,
        metadata=verifier_metadata,
        request_id=request_id,
        implementation_commit=verifier_implementation,
        implementation_tree=verifier_implementation_tree,
        merge_commit=verifier_merge,
        merge_tree=verifier_merge_tree,
        claim_generation=1,
        consumer_id="merge-train:verifier",
        claim_token="claim:verifier",
    )
    _write_queue_row(
        restart_authority,
        task=verifier_task,
        request_id=request_id,
        metadata=verifier_metadata,
        implementation_commit=verifier_implementation,
        status="completed",
        claim_generation=2,
        finished_at=1.0,
    )

    accelerator_v2 = restart_authority["accelerator_v2"]
    _git(repository / "ipfs_accelerate_py", "checkout", accelerator_v2)
    _git(repository, "add", "--", "ipfs_accelerate_py")
    _git(repository, "commit", "-m", "DQK-056: pin verified accelerator release")
    superproject_commit = _git(repository, "rev-parse", "HEAD")
    source = restart_authority["source"]
    task = source.get_task(program.RELEASE_GATE_TASK_ID)
    assert task is not None and task.status == "blocked"
    snapshot = source.snapshot()
    source.compare_and_set_status(
        task.task_id,
        expected_revision=task.revision,
        status="completed",
        receipt={
            "schema": program._RELEASE_GATE_RECEIPT_SCHEMA,
            "input_receipt_sha256": "sha256:" + "1" * 64,
            "verification": {
                "schema": program._RELEASE_VERIFICATION_SCHEMA,
                "accepted": True,
                "accelerator_commit": accelerator_v2,
                "accelerator_tree": restart_authority["accelerator_v2_tree"],
                "decision_cid": "decision:dqk-056",
                "release_receipt_cid": "release:dqk-056",
                "cutover_receipt_cid": "cutover:dqk-056",
                "store_generation": "generation:dqk-056",
                "schema_checksum": "sha256:" + "2" * 64,
                "quack_profile": "quack-profile:dqk-056",
                "expires_at": expires_at,
            },
            "verifier_sha256": "sha256:"
            + hashlib.sha256(verifier_body.encode("utf-8")).hexdigest(),
            "plan_root_cid": snapshot.plan_root_cid,
            "repository_tree_id": snapshot.repository_tree_id,
            "superproject_commit": superproject_commit,
            "acknowledged_at": acknowledged_at,
        },
    )

    compatible, detail = program._repository_binding_is_launch_compatible(
        restart_authority["repository_binding"],
        source=source,
    )
    assert not compatible
    assert expected_rejection in detail
