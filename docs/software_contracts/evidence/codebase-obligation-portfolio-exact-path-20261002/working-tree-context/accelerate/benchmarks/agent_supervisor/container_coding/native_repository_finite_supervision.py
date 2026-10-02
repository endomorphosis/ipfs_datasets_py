"""Repository facts, residual planning, native worker publication and fresh successor checks.

The fixture has an explicit controlled-language specification and finite domain.
It measures a model-off integration, not learned interpretation or Terminal-Bench.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, nullcontext
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

INPUTS = [-2, -1, 0, 1, 2]
INSTRUCTION = ("Under python-integer-offset-finite@1, calc.py::increment(n) must return an exact int for inputs [-2,-1,0,1,2].\n"
               "Under python-integer-offset-finite@1, calc.py::increment(n) must return n + 2 for inputs [-2,-1,0,1,2].")
SOURCE = "def increment(n: int) -> int:\n    return n + 1\n"
CHECK = "from calc import increment\nvalues = [increment(n) for n in [-2,-1,0,1,2]]\nassert all(type(v) is int for v in values)\nassert values == [0,1,2,3,4], values\n"


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def _git(root, *args):
    return subprocess.check_output(["/usr/bin/git", "-C", str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


def _index(connection, artifacts):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    store = DuckDBASTStore(connection=connection)
    cas = ImmutableCAS(artifacts)
    return RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas,
                                  catalog=CodebaseCatalog(store, cas))


def finite_successor_semantics(match):
    """Compare source/requirements/outcomes while retaining separate run receipts.

    Predicate IDs include the catalog head generation. A cold generation-1
    rebuild and incremental generation-2 rebuild must keep those identities
    distinct even when the exact source, complete query and observations agree.
    """
    result = {key: match[key] for key in ("status", "source_cid", "domain_cid", "domain_inputs",
        "eligible_clause_ids", "residual_clause_ids", "finite_counterexamples", "query")}
    result["source_snapshot_cid"] = match["head"]["snapshot_cid"]
    result["clause_results"] = [{key: value for key, value in row.items() if key != "predicate_id"}
                               for row in match["clause_results"]]
    run_receipts = {"artifacts", "head", "lean_certificate", "output", "python_process", "result_cid"}
    result["observation_semantics"] = {key: value for key, value in match["observation"].items()
                                       if key not in run_receipts}
    return result


def prepare_request(*, index, head, repository, intent, declared, tools, scheduler,
        semantic_index=None, checked_cache=None, parent_lease=None, cancel_event=None):
    """Derive roots from actual source, signed task/policy and explicit absent domains."""
    from ipfs_accelerate_py.agent_supervisor.planning import finite_integer_codebase as matcher
    from ipfs_accelerate_py.agent_supervisor.planning.finite_integer_plan_preview import (
        FiniteIntegerOperationCatalog, ReviewedFiniteIntegerOperation,
        finite_integer_prompt_cid, finite_integer_intent_cid,
    )
    from ipfs_accelerate_py.agent_supervisor.planning.repository_plan_preview import RepositoryPlanPreviewOwner
    from ipfs_accelerate_py.agent_supervisor.planning.plan_revision_contracts import (
        PlanAuthorityRoots, PlanCreateRequest, PlanRequestBudget, DirtyTreePolicy,
        TaskSourceKind, plan_revision_cid,
    )
    from ipfs_accelerate_py.agent_supervisor.runtime import local_planning_admission as local
    document = matcher.build_finite_integer_intent(INSTRUCTION)
    catalog = FiniteIntegerOperationCatalog(tuple(ReviewedFiniteIntegerOperation(
        requirement_id=requirement, task_id=task, producer_id="producer:" + task,
        path="calc.py", function_name="increment", parameter="n", review_ref="authored:bounded-offset-operation@1")
        for requirement, task in ((matcher.TYPE_STATEMENT_ID, "task:finite:type"),
                                  (matcher.OFFSET_STATEMENT_ID, "task:finite:offset"))))
    native_manifest = index.load(head.manifest_cid)
    selection = dict(tools=tools, operations=catalog.to_dict(), model="disabled",
                     native_task_cid=declared["task_cid"])
    if semantic_index is not None:
        selected_query = matcher.prepare_finite_integer_query(intent_document=document, source_text=INSTRUCTION)
        if semantic_index["contract"] != selected_query["contract"]:
            raise ValueError("semantic index declaration differs from the selected intent contract")
        selection["semantic_index"] = semantic_index
    if checked_cache is not None:
        selection["checked_cache"] = checked_cache["binding"]

    def observed_roots():
        if checked_cache is not None:
            lookup = checked_cache["owner"].lookup(owner_inputs=checked_cache["inputs"])
            if _cache_binding(lookup) != checked_cache["binding"]:
                raise ValueError("finite checked cache changed before planning admission")
        if semantic_index is not None:
            from .terminal_codebase_semantic_index import verify_semantic_index
            verify_semantic_index(index=index, repository=repository, expected_head=head,
                descriptor=semantic_index, scheduler=scheduler, parent_lease=parent_lease,
                cancel_event=cancel_event)
        admission = local.verify_local_benchmark_admission(declared["admission"], initial=True)
        projection = intent.plan_projection(task_cids=[declared["task_cid"]])
        return PlanAuthorityRoots(repository_id=head.repository_id,
            task_source_id="native-intent:" + str(intent.database_path),
            repository_root_cid=head.snapshot_cid, dirty_worktree_root=head.snapshot_cid,
            task_source_revision=plan_revision_cid(projection), policy_root=plan_revision_cid(local.LOCAL_POLICY),
            intent_ir_root=finite_integer_intent_cid(document),
            legal_ir_root=plan_revision_cid({"legal_constraints": "not_selected"}),
            security_ir_root=plan_revision_cid({"security_constraints": "not_selected"}),
            program_root=native_manifest.semantic_state.state_cid, capability_catalog_root=catalog.cid,
            provider_catalog_root=plan_revision_cid({"model_calls": "disabled"}),
            usage_policy_root=plan_revision_cid({"native_manifest_cid": admission["receipt"]["manifest_cid"]}),
            configuration_root=plan_revision_cid(selection))

    roots = observed_roots()
    request = PlanCreateRequest(prompt_source_cid=finite_integer_prompt_cid(INSTRUCTION),
        repository_id=head.repository_id, repository_root=str(repository), scope_paths=("calc.py",),
        dirty_tree_policy=DirtyTreePolicy.OBSERVE_AND_BIND, task_source_kind=TaskSourceKind.DUCKDB,
        board_namespace="finite-native-qualification", alias_prefix="FINITE", roots=roots,
        budget=PlanRequestBudget(max_tasks=2, max_goals=2, max_model_calls=0, max_latency_ms=90000),
        required_analysis_operations=(), optional_analysis_operations=(),
        required_logic_families=(), optional_logic_families=(), observe_roots=True)

    def policy_observer(bound):
        if bound != request:
            raise ValueError("native finite request changed")
        return observed_roots()

    return dict(owner=RepositoryPlanPreviewOwner(index=index, repository=repository,
        expected_head=head, scheduler=scheduler, parent_lease=parent_lease,
        cancel_event=cancel_event, timeout_seconds=90, memory_mb=1024),
        request=request, intent_document=document, source_text=INSTRUCTION,
        operation_catalog=catalog, tool_policy=tools, policy_observer=policy_observer)


def _cache_binding(result):
    return {key: result[key] for key in ("schema", "status", "record_cid", "request_key", "scope",
        "source_runtime_semantics_verified", "execution_authority", "completion_authority")}


def qualify(*, output: Path, python: Path, lean: Path, public_evidence: bool = False,
        semantic_manifest: bool = False, checked_cache: bool = False,
        behavioral_evidence: bool = False, budgeted_preparation: bool = False,
        full_trial_resources: bool = False, pipeline_resources: bool = False):
    import duckdb
    from ipfs_datasets_py.logic.software_contracts.codebase_finite_integer_observation import seal_finite_integer_tools
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
    from ipfs_accelerate_py.agent_supervisor.planning import finite_integer_codebase as matcher
    from ipfs_accelerate_py.agent_supervisor.entrypoints.admitted_benchmark_runtime import AdmittedBenchmarkRuntime
    from ipfs_accelerate_py.agent_supervisor.runtime.repository_finite_handoff import prepare_finite_repository_handoff
    from ipfs_accelerate_py.agent_supervisor.runtime.supervised_task_context import prepare_supervised_task_context
    from ipfs_accelerate_py.agent_supervisor.runtime.task_context_bundle import write_task_context_bundle
    from ipfs_accelerate_py.agent_supervisor.task_sources.intent_repository import IntentRepository
    from ipfs_accelerate_py.agent_supervisor.task_sources.task_execution_route_policy import GROK_CODEX_EXECUTION_MODE
    from .local_planning_qualification import prepare_local_task
    from .native_quack_qualification import open_existing_native_owner
    from .terminal_container_supervisor import _native_diagnostics
    from .terminal_codebase_finite_index import persist_finite_evidence_index, query_finite_evidence_index

    output = Path(output).absolute()
    if output.exists() or output.resolve() != output:
        raise ValueError("fresh exact qualification directory required")
    output.mkdir(parents=True)
    if pipeline_resources:
        full_trial_resources = True
    if full_trial_resources:
        behavioral_evidence = budgeted_preparation = True
    if behavioral_evidence:
        semantic_manifest = checked_cache = public_evidence = True
    if budgeted_preparation and not semantic_manifest:
        raise ValueError("budgeted preparation requires an explicitly selected semantic manifest")
    started = time.monotonic()
    resources_stack, trial_envelope = ExitStack(), None
    trial_pipeline = managed_phase = managed_context = None
    managed_before = None
    primary_error = None
    write_ceiling = 128 * 1024**2
    preparation_write_ceiling = 16 * 1024**2
    report = dict(schema="native-repository-finite-qualification@1", qualified=False,
        provider_calls=0, provider_tokens=0, training_steps=0, benchmark_result=False,
        intent_origin="complete explicitly scoped controlled-language IntentIR",
        learned_interpretation=False, proof_cache_bypass=False, production_activation=False,
        run_owner_pid=os.getpid(),
        behavioral_evidence_selected=behavioral_evidence,
        budgeted_preparation_selected=budgeted_preparation,
        full_trial_resources_selected=full_trial_resources,
        pipeline_resources_selected=pipeline_resources,
        preparation_reports=[],
        observations=[], trial_phases=[])
    if pipeline_resources:
        report["managed_profile"] = dict(cpu_slots=3, memory_mb=3072, process_slots=3,
            disk_bytes=1536*1024**2, protected_memory_mb=1024, protected_disk_bytes=640*1024**2,
            high_level_write_ceiling_bytes=write_ceiling,
            preparation_write_ceiling_bytes=preparation_write_ceiling,
            expected_ordinary_high_level_phases=5, expected_protected_high_level_phases=4,
            expected_ordinary_preparation_phases=12, expected_protected_preparation_phases=3,
            maximum_declared_ordinary_disk_bytes=832*1024**2,
            maximum_declared_protected_disk_bytes=560*1024**2,
            external_supervisor_and_worker_rss_captured=False,
            ambient_semantic_temporary_files_in_named_roots=False)
    phase_name, phase_started = "setup", started
    def cleanup_failure(error):
        value = dict(type=type(error).__name__, message=str(error)[:4096])
        report.setdefault("cleanup_errors", []).append(value)
        report.setdefault("error", value)
        report["qualified"] = False
    def finish_managed(error=None):
        nonlocal managed_phase, managed_context, managed_before
        if managed_phase is None:
            return
        phase, context, before = managed_phase, managed_context, managed_before
        managed_phase = managed_context = managed_before = None
        if error is None:
            try:
                growth = max(0, phase.check_usage()["observed_apparent_bytes"]-before)
                if growth > write_ceiling:
                    raise RuntimeError("trial phase exceeds sampled named-root write ceiling")
                phase.finalize(artifacts_durable=True)
            except BaseException as failure:
                context.__exit__(type(failure), failure, failure.__traceback__)
                raise
            context.__exit__(None, None, None)
        else:
            context.__exit__(type(error), error, error.__traceback__)

    def advance_phase(name, *, status="completed"):
        nonlocal phase_name, phase_started
        nonlocal managed_phase, managed_context, managed_before
        finish_managed()
        now = time.monotonic()
        report["trial_phases"].append(dict(phase=phase_name, status=status,
            elapsed_seconds=now-phase_started, start_seconds=phase_started-started,
            end_seconds=now-started))
        phase_name, phase_started = name, now
        if trial_envelope is not None:
            trial_envelope.remaining()
        if trial_pipeline is not None:
            from ipfs_accelerate_py.agent_supervisor.runtime.repository_resource_bridge import RepositoryPhaseDemand
            protected = name in {"initial_public_validation", "native_supervision_and_stop", "publication_verification"}
            kind = "cleanup" if name == "resource_cleanup" else "validation" if protected else "proof"
            attempt = output / "managed-attempts" / (str(len(report["trial_phases"])) + "-" + name)
            attempt.mkdir(mode=0o700)
            payload = json.dumps(dict(phase=name, instruction=INSTRUCTION), sort_keys=True).encode()
            managed_context = trial_pipeline.phase(RepositoryPhaseDemand(kind, memory_mb=1024,
                disk_bytes=write_ceiling), payload=payload, attempt_directory=attempt)
            managed_phase = managed_context.__enter__()
            managed_before = managed_phase.check_usage()["observed_apparent_bytes"]
            managed_phase.charge_external(output, write_ceiling)
    try:
        repository = output / "repository"; repository.mkdir()
        for name, body in {"calc.py": SOURCE, "instruction.txt": INSTRUCTION,
                "decoy.py": "def increment(n: int) -> int:\n    return n + 200\n",
                "unsupported.py": "def dynamic(n):\n    return eval(str(n))\n",
                "public_check.py": CHECK}.items():
            (repository / name).write_text(body)
        if semantic_manifest:
            # The stricter source profile captures ignore rules as versioned
            # source. Ambient info/exclude patterns cannot define its scope.
            (repository / ".gitignore").write_text(".runtime/\n__pycache__/\n")
        for args in (("init", "-q"), ("config", "user.name", "Repository finite qualification"),
                ("config", "user.email", "qualification@example.invalid"),
                ("add", "."), ("commit", "-qm", "Independent complete finite acceptance")):
            _git(repository, *args)
        if not semantic_manifest:
            (repository / ".git/info/exclude").write_text(".runtime/\n__pycache__/\n")
        (repository / ".runtime").mkdir(mode=0o755)
        baseline = _git(repository, "rev-parse", "HEAD")
        check = ["python3", "-B", "public_check.py"]
        if not pipeline_resources:
            report["initial_public_check_exit_code"] = subprocess.run(check, cwd=repository,
                capture_output=True, timeout=10).returncode
            if not report["initial_public_check_exit_code"]:
                raise RuntimeError("independent public acceptance must initially fail")
        tools = seal_finite_integer_tools(python_executable=python, lean_executable=lean)
        scheduler = get_global_resource_scheduler()
        advance_phase("host_admission")
        if full_trial_resources:
            from ipfs_accelerate_py.agent_supervisor.runtime.repository_resource_bridge import (
                RepositoryResourceBridge, RepositoryResourceBudget, RepositoryPhaseDemand,
            )
            from ipfs_accelerate_py.agent_supervisor.runtime.resource_scheduler import ResourceScheduler, ResourcePolicy
            # Preparation, proof work and delegated worker all consume children
            # of this sole host reservation. Setup time consumes its deadline.
            remaining_ms = 600000 - int((time.monotonic()-started)*1000)
            if pipeline_resources:
                from ipfs_accelerate_py.agent_supervisor.runtime.repository_pipeline_resources import (
                    RepositoryPipelineResources, PipelineResourcePolicy,
                )
                (output / "managed-attempts").mkdir(mode=0o700)
                trial_pipeline = resources_stack.enter_context(RepositoryPipelineResources(
                    ResourceScheduler(ResourcePolicy(max_lanes=8))).reserve(
                        repository_id="repository:finite-native-qualification", workspace=output,
                        budget=RepositoryResourceBudget(cpu_slots=3, memory_mb=3072, process_slots=3,
                            disk_bytes=1536*1024**2, wall_time_ms=remaining_ms),
                        policy=PipelineResourcePolicy(protected_memory_mb=1024,
                            protected_disk_bytes=640*1024**2),
                        ledger_path=output / "pipeline-disk-ledger.json", roots=[output]))
                trial_envelope = trial_pipeline.parent
                advance_phase("initial_public_validation")
                report["initial_public_check_exit_code"] = managed_phase.run(
                    [str(python), "-B", str(repository / "public_check.py")], timeout_seconds=10).returncode
                if not report["initial_public_check_exit_code"]:
                    raise RuntimeError("independent public acceptance must initially fail")
            else:
                trial_envelope = resources_stack.enter_context(RepositoryResourceBridge(
                    ResourceScheduler(ResourcePolicy(max_lanes=8))).reserve(
                        repository_id="repository:finite-native-qualification", workspace=output,
                        budget=RepositoryResourceBudget(cpu_slots=2, memory_mb=3072, process_slots=2,
                            wall_time_ms=remaining_ms)))
        def native_resources():
            if trial_envelope is None:
                return dict(scheduler=scheduler)
            trial_envelope.remaining()
            if trial_pipeline is not None:
                if managed_phase is None:
                    raise RuntimeError("managed native work requires an active admitted phase")
                options = managed_phase.native_options()
                return {key: options[key] for key in ("parent_lease", "cancel_event")}
            return dict(parent_lease=trial_envelope.native, cancel_event=trial_envelope.cancellation)
        def fresh_cache(value):
            if value is None:
                return None
            inputs = {key: item for key, item in value["inputs"].items()
                      if key not in {"scheduler", "parent_lease", "cancel_event"}}
            return {**value, "inputs": {**inputs, **native_resources()}}
        def prepare_source(index, *, repository_id, operation_id, expected_head):
            if not semantic_manifest:
                return index.prepare_current(repository, repository_id=repository_id,
                    operation_id=operation_id, expected_head=expected_head, scheduler=scheduler).head, None
            from .terminal_codebase_semantic_index import prepare_semantic_index
            from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
            if budgeted_preparation:
                from .repository_benchmark_preparation import (
                    prepare_repository_benchmark, RepositoryPreparationSelection, PreparationBudget,
                )
                from ipfs_datasets_py.logic.software_contracts.codebase_scan_policy import CodebaseScanPolicy
                from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
                from ipfs_accelerate_py.agent_supervisor.runtime.repository_resource_bridge import (
                    RepositoryResourceBridge, RepositoryResourceBudget,
                )
                from ipfs_accelerate_py.agent_supervisor.runtime.resource_scheduler import ResourceScheduler, ResourcePolicy
                from ipfs_accelerate_py.agent_supervisor.proof.finite_checked_cache import FiniteCheckedCache
                from ipfs_accelerate_py.agent_supervisor.proof.formal_verification_cache import FormalVerificationCache
                contract = IntegerOffsetContract("calc.py", "increment", "n", 2)
                proof_owner = FiniteCheckedCache(FormalVerificationCache(
                    output / (operation_id + "-preparation-cache") / "formal_verification_cache.duckdb",
                    exact_path=True), index.artifacts)
                bridge = RepositoryResourceBridge(ResourceScheduler(ResourcePolicy(max_lanes=8)))
                reservation = nullcontext(trial_envelope) if trial_envelope is not None else bridge.reserve(
                    repository_id=repository_id, workspace=output,
                    budget=RepositoryResourceBudget(memory_mb=1024, wall_time_ms=180000))
                with reservation as envelope:
                    prepared = prepare_repository_benchmark(index=index, repository=repository,
                        repository_id=repository_id, expected_head=expected_head, operation_id=operation_id,
                        selection=RepositoryPreparationSelection(CodebaseScanPolicy(),
                            proof_contracts=(contract,), proof_inputs=(tuple(INPUTS),)),
                        envelope=envelope, budget=PreparationBudget(memory_mb=1024),
                        checked_cache=proof_owner, tool_policy=tools,
                        **(dict(pipeline=trial_pipeline, pipeline_attempt_root=output / "managed-attempts",
                            pipeline_write_budget_bytes=preparation_write_ceiling) if trial_pipeline is not None else {}))
                report["preparation_reports"].append(dict(result=prepared,
                    resource_receipt_after_preparation=envelope.receipt(),
                    full_trial_parent_retained=trial_envelope is not None))
                _write(output / (operation_id + "-preparation.json"), report["preparation_reports"][-1])
                return CodebaseHead.from_dict(prepared["source_head"]), dict(
                    schema="terminal-codebase-semantic-index@1", manifest_cid=prepared["semantic_manifest_cid"],
                    policy_receipt_cid=prepared["policy_receipt_cid"], head=prepared["source_head"],
                    contract=contract.to_dict(), coverage=prepared["complete_inventory"],
                    proof_authority=False, training_executed=False)
            return prepare_semantic_index(index=index, repository=repository,
                repository_id=repository_id, operation_id=operation_id, expected_head=expected_head,
                contract=IntegerOffsetContract("calc.py", "increment", "n", 2), scheduler=scheduler)
        def prepare_cache(index, head, name):
            from ipfs_accelerate_py.agent_supervisor.proof.finite_checked_cache import FiniteCheckedCache
            from ipfs_accelerate_py.agent_supervisor.proof.formal_verification_cache import FormalVerificationCache
            from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
            owner = FiniteCheckedCache(FormalVerificationCache(
                output / "checked-cache" / "formal_verification_cache.duckdb", exact_path=True), index.artifacts)
            inputs = dict(index=index, repository=repository, expected_head=head,
                contract=IntegerOffsetContract("calc.py", "increment", "n", 2), inputs=INPUTS,
                tool_policy=tools, **native_resources())
            saved = owner.check_and_store(owner_inputs=inputs)
            _write(output / (name + "-checked-cache.json"), saved)
            return dict(owner=owner, inputs=inputs, binding=_cache_binding(saved)), saved
        advance_phase("initial_preparation")
        with duckdb.connect(str(output / "repository.duckdb"), config={"threads": 1, "memory_limit": "64MB"}) as cx:
            index = _index(cx, output / "artifacts")
            if behavioral_evidence:
                # These paths were created exclusively for this fresh run.
                (output / "repository.duckdb").chmod(0o600)
                (output / "artifacts").chmod(0o700)
            head, semantic_index = prepare_source(index, repository_id="repository:finite-native-qualification",
                operation_id="initial", expected_head=None)
            report["initial_semantic_index"] = semantic_index
            cached = None
            if checked_cache:
                cached, cache_result = prepare_cache(index, head, "initial")
                if behavioral_evidence:
                    cached["owner"].cache.path.chmod(0o600)
                report["initial_checked_cache"] = _cache_binding(cache_result)
                if cache_result["status"] != "refuted" or cache_result["positive_reuse_eligible"]:
                    raise RuntimeError("initial offset must remain a checked residual")
            advance_phase("planning_admission_and_context")
            with IntentRepository(output / "intent.duckdb") as intent:
                declared = prepare_local_task(repository=repository, state=output / "policy", intent=intent,
                    scope_paths=["calc.py", "instruction.txt", "public_check.py"], output_path="calc.py",
                    validation_argv=check, objective=INSTRUCTION.replace("\n", " "))
                cid = declared["task_cid"]
                planning_resources = native_resources()
                options = prepare_request(index=index, head=head, repository=repository, intent=intent,
                    declared=declared, tools=tools, scheduler=planning_resources.get("scheduler"),
                    parent_lease=planning_resources.get("parent_lease"),
                    cancel_event=planning_resources.get("cancel_event"),
                    semantic_index=semantic_index, checked_cache=fresh_cache(cached))
                if behavioral_evidence:
                    from ipfs_datasets_py.duckdb_control.intent_codebase_catalog import IntentCodebaseCatalog
                    from ipfs_accelerate_py.agent_supervisor.runtime.repository_behavioral_admission import prepare_behavioral_repository_handoff
                    catalog = IntentCodebaseCatalog(index)
                    catalog.publish(repository, expected_head=head, manifest_cid=semantic_index["manifest_cid"],
                        operation_id="behavioral-discovery", **native_resources())
                    candidate = prepare_behavioral_repository_handoff(catalog=catalog,
                        checked_cache=cached["owner"], semantic_manifest_cid=semantic_index["manifest_cid"],
                        **options, admission=declared["admission"], intent=intent, task_cid=cid,
                        state=output / "finite-repair", instruction_path="instruction.txt")
                    report["behavioral_preview"] = candidate["behavioral_preview"]
                else:
                    candidate = prepare_finite_repository_handoff(**options, admission=declared["admission"],
                        intent=intent, task_cid=cid, state=output / "finite-repair", instruction_path="instruction.txt")
                _write(output / "candidate-result.json", candidate)
                if candidate["status"] != "candidate_ready":
                    raise RuntimeError("native repository plan did not select a checked candidate")
                public_context = None
                if public_evidence:
                    from ipfs_accelerate_py.agent_supervisor.runtime.repository_finite_public_context import publish_finite_public_context
                    public_context = candidate["public_context"] if behavioral_evidence else publish_finite_public_context(
                        candidate=candidate, admission=declared["admission"], instruction=INSTRUCTION)
                    report["public_context"] = public_context
                historical = persist_finite_evidence_index(match=candidate["preview"]["match"], output=output / "finite-index")
                report["index_query"] = query_finite_evidence_index(index=index, repository=repository,
                    expected_head=head, expected=historical, **native_resources())
                context = prepare_supervised_task_context(repository=repository, intent=intent, task_cid=cid,
                    paths=["calc.py", "instruction.txt", "public_check.py"], required_raw_paths=["calc.py"],
                    output=repository / ".runtime/initial")
                bundle = write_task_context_bundle(repository=repository, prepared=[context],
                    output=repository / ".runtime/context-bundle.json")
                report.update(task_cid=cid, baseline_commit=baseline, initial_head=head.to_dict(),
                    captured_paths=[entry.path for entry in index.load(head.manifest_cid).snapshot.entries],
                    initial_fact_count=candidate["preview"]["current_facts_count"],
                    initial_residuals=candidate["preview"]["match"]["residual_clause_ids"],
                    selected_operations=candidate["preview"]["selected_task_ids"],
                    retained_preview_execution_debt=candidate["preview"]["execution_plan"],
                    context_bundle=bundle, handoff_sha256=candidate["handoff_sha256"])
        advance_phase("worker_prelaunch")
        binding = candidate["signed_evidence"]["binding"]
        runner_module = "repository_finite_public_context" if public_evidence else "repository_finite_runner"
        if behavioral_evidence:
            from ipfs_accelerate_py.agent_supervisor.runtime.repository_behavioral_admission import verify_behavioral_repository_handoff
            report["behavioral_prelaunch"] = verify_behavioral_repository_handoff(
                artifact=candidate["repository_admission_path"], expected_sha256=candidate["repository_admission_sha256"],
                task_cid=cid, owner_did=binding["identity"], profile_id=binding["profile_id"], **native_resources())
            runner_module = "repository_behavioral_runner"
        grant = None
        if full_trial_resources:
            from ipfs_accelerate_py.agent_supervisor.runtime.repository_resource_handoff import (
                write_repository_resource_grant, write_pipeline_resource_grant,
            )
            private = output / "private-resources"; private.mkdir(mode=0o700)
            if trial_pipeline is not None:
                advance_phase("native_supervision_and_stop")
                grant = write_pipeline_resource_grant(phase=managed_phase, directory=private, task_cid=cid)
            else:
                grant = write_repository_resource_grant(envelope=trial_envelope, directory=private,
                    task_cid=cid, demand=RepositoryPhaseDemand("validation", memory_mb=1024))
            runner_module = "repository_budgeted_behavioral_runner"
        command_args = [sys.executable, "-B", "-P", "-m",
            "ipfs_accelerate_py.agent_supervisor.runtime." + runner_module,
            "--artifact", candidate["handoff_path"], "--sha256", candidate["handoff_sha256"],
            "--task-cid", cid, "--owner-did", binding["identity"], "--profile-id", binding["profile_id"]]
        if public_context is not None:
            command_args += ["--public-context", public_context["artifact"], "--public-context-sha256", public_context["sha256"]]
        if behavioral_evidence:
            command_args += ["--repository-admission", candidate["repository_admission_path"],
                "--repository-admission-sha256", candidate["repository_admission_sha256"]]
        if grant is not None:
            command_args += ["--resource-grant", grant["artifact"], "--resource-grant-sha256", grant["sha256"],
                "--repository-id", head.repository_id]
        command = shlex.join(command_args)
        worktrees = output / "worktrees"; worktrees.mkdir(mode=0o750)
        if trial_pipeline is None:
            advance_phase("native_supervision_and_stop")
        with open_existing_native_owner(database=output / "intent.duckdb", checkout=repository,
                state_dir=output / "owner", repository_id=declared["manifest"]["payload"]["repository_cid"],
                execution_routes={declared["task_id"]: GROK_CODEX_EXECUTION_MODE}) as owner:
            runtime = AdmittedBenchmarkRuntime.create(output / "launch", admission=declared["admission"],
                server=owner.server, source=owner.source, implement=True, implementation_command=command,
                context_bundle=bundle, refresh_context_on_completion=True, max_task_attempts=1,
                timeout_ms=30000, lifetime_seconds=180, worker_worktree_root=worktrees)
            try:
                report["start"] = runtime.start().to_dict()
                if report["start"]["status"] != "succeeded":
                    raise RuntimeError("native START failed")
                deadline, previous = time.monotonic() + 90, None
                while time.monotonic() < deadline:
                    if trial_envelope is not None:
                        trial_envelope.remaining()
                    task = owner.source.get_task(cid)
                    current = (task.status, task.revision)
                    if current != previous:
                        report["observations"].append(dict(status=task.status, revision=task.revision,
                                                         seconds=time.monotonic() - started))
                        _write(output / "progress.json", report); previous = current
                    if task.status in {"completed", "failed", "blocked", "cancelled"}:
                        break
                    if not runtime.process.snapshot(runtime.profile).members:
                        raise RuntimeError("native supervisor ended before task completion")
                    time.sleep(.25)
                report["task"] = dict(status=task.status, revision=task.revision)
            finally:
                try:
                    report["stop"] = runtime.stop().to_dict()
                    report["remaining_processes"] = len(runtime.process.snapshot(runtime.profile).members)
                    report["native_diagnostics"] = _native_diagnostics(runtime.state)
                    report["bootstrap_errors"] = runtime.bootstrap_errors
                    if report["stop"]["status"] == "succeeded" and report["remaining_processes"] == 0:
                        report["after_stop"] = runtime.observe()
                finally:
                    runtime.close()
        advance_phase("publication_verification")
        if public_context is not None:
            receipts = []
            logs = list((output / "launch/state/run").glob(
                "admitted_database_portal_attempts/*/implementation-logs/*attempt-*.log"))
            if len(logs) > 4:
                raise RuntimeError("unexpected worker attempt population")
            for path in logs:
                with path.open("rb") as stream:
                    raw = stream.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise RuntimeError("worker log exceeds evidence bound")
                for line in raw.decode().splitlines():
                    if not line.startswith('{"artifact_cid":'):
                        continue
                    value = json.loads(line)
                    if value.get("schema") == "native-repository-finite-materialization@1":
                        receipts.append(value)
            if (len(receipts) != 1 or receipts[0]["task_cid"] != cid
                    or receipts[0]["public_context"]["sha256"] != public_context["sha256"]
                    or receipts[0]["public_context"]["integrity_replayed"] is not True
                    or receipts[0]["public_context"]["owner_keys_used"] is not False
                    or receipts[0]["public_context"]["injected_after_semantic_encoding"] is not True):
                raise RuntimeError("native worker public context delivery did not verify")
            report["public_context_worker_receipt"] = receipts[0]
            if behavioral_evidence:
                if receipts[0].get("repository_evidence_fence", {}).get("source_observed_before_and_after") is not True:
                    raise RuntimeError("native worker did not replay behavioral repository evidence")
                report["behavioral_worker_fence_replayed"] = True
            if full_trial_resources:
                resource_receipt = receipts[0].get("delegated_resource_phase", {})
                expected_parent = grant["parent_lease_id"] if trial_pipeline is not None else trial_envelope.native.lease_id
                if (resource_receipt.get("parent_lease_id") != expected_parent
                        or resource_receipt.get("lease", {}).get("released") is not True
                        or resource_receipt.get("private_token_disclosed") is not False):
                    raise RuntimeError("worker did not close its delegated native parent lease")
                if trial_pipeline is not None and any(resource_receipt.get(key) != grant[key]
                        for key in ("root_lease_id", "bridge_phase_lease_id", "daemon_reservation_id")):
                    raise RuntimeError("worker did not retain its exact managed resource ancestry")
                report["delegated_worker_resources_verified"] = True
        report["final_public_check_exit_code"] = (managed_phase.run(
            [str(python), "-B", str(repository / "public_check.py")], timeout_seconds=10).returncode
            if trial_pipeline is not None else subprocess.run(check, cwd=repository,
                capture_output=True, timeout=10).returncode)
        report["published_commit"] = _git(repository, "rev-parse", "HEAD")
        report["published_source_matches_checked_candidate"] = hashlib.sha256((repository / "calc.py").read_bytes()).hexdigest() == candidate["signed_evidence"]["payload"]["edit"]["after_sha256"]
        from ipfs_accelerate_py.agent_supervisor.runtime.repository_finite_runner import materialize_finite_candidate
        stale_workspace = output / "stale-allocated"
        _git(repository, "worktree", "add", "--detach", str(stale_workspace), baseline)
        try:
            try:
                materialize_finite_candidate(artifact=Path(candidate["handoff_path"]),
                    expected_sha256=candidate["handoff_sha256"], task_cid=cid,
                    owner_did=binding["identity"], profile_id=binding["profile_id"],
                    prompt=json.dumps({"objective_id": declared["task_id"]}), workspace=stale_workspace)
            except ValueError:
                report["stale_dispatch_refused"] = True
            else:
                report["stale_dispatch_refused"] = False
        finally:
            _git(repository, "worktree", "remove", "--force", str(stale_workspace))
        advance_phase("successor_preparation_and_reproof")
        # Reopen the durable owner and capture the actual published successor.
        with duckdb.connect(str(output / "repository.duckdb"), config={"threads": 1, "memory_limit": "64MB"}) as cx:
            index = _index(cx, output / "artifacts")
            prior = index.current(head.repository_id)
            successor, successor_index = prepare_source(index, repository_id=head.repository_id,
                operation_id="published-successor", expected_head=prior)
            report["successor_semantic_index"] = successor_index
            if checked_cache:
                successor_cache, cache_result = prepare_cache(index, successor, "successor")
                report["successor_checked_cache"] = _cache_binding(cache_result)
                # Reconstruct through a new cache handle after durable store.
                from ipfs_accelerate_py.agent_supervisor.proof.finite_checked_cache import FiniteCheckedCache
                from ipfs_accelerate_py.agent_supervisor.proof.formal_verification_cache import FormalVerificationCache
                reopened = FiniteCheckedCache(FormalVerificationCache(
                    output / "checked-cache" / "formal_verification_cache.duckdb", exact_path=True), index.artifacts)
                replay = reopened.lookup(owner_inputs=successor_cache["inputs"])
                _write(output / "successor-checked-cache-replay.json", replay)
                report["checked_cache_replay_agrees"] = (
                    _cache_binding(replay) == _cache_binding(cache_result)
                    and replay["positive_reuse_eligible"] is True
                    and replay["fresh_native_observation"] is True)
                try:
                    reopened.lookup(owner_inputs={**successor_cache["inputs"], "expected_head": head})
                except ValueError:
                    report["stale_checked_cache_refused"] = True
                else:
                    report["stale_checked_cache_refused"] = False
            if successor_index is not None:
                from ipfs_datasets_py.logic.software_contracts.codebase_semantic_manifest import load_codebase_semantic_manifest
                manifest = load_codebase_semantic_manifest(index, successor_index["manifest_cid"])
                successor_manifest_semantics = {key: manifest[key] for key in
                    ("units", "coverage", "declarations", "semantic_state_cid")}
            try:
                query_finite_evidence_index(index=index, repository=repository, expected_head=head,
                                           expected=historical, **native_resources())
            except ValueError:
                report["stale_index_refused"] = True
            else:
                report["stale_index_refused"] = False
            matched = matcher.match_finite_integer_intent(index=index, repository=repository,
                repository_id=head.repository_id, expected_head=successor,
                intent_document=matcher.build_finite_integer_intent(INSTRUCTION), source_text=INSTRUCTION,
                output=output / "successor-observation", tool_policy=tools, **native_resources())
            report["successor"] = dict(head=successor.to_dict(), fact_count=len(matched["current_facts"]),
                residuals=matched["residual_clause_ids"], observation_cid=matched["observation_cid"])
            _write(output / "successor-match.json", matched)
        advance_phase("independent_cold_comparison")
        with duckdb.connect(str(output / "cold.duckdb"), config={"threads": 1, "memory_limit": "64MB"}) as cx:
            cold = _index(cx, output / "cold-artifacts")
            cold_head, cold_index = prepare_source(cold, repository_id=head.repository_id,
                operation_id="independent-cold-successor", expected_head=None)
            report["cold_semantic_index"] = cold_index
            if cold_index is not None:
                manifest = load_codebase_semantic_manifest(cold, cold_index["manifest_cid"])
                cold_manifest_semantics = {key: manifest[key] for key in successor_manifest_semantics}
                report["cold_semantic_manifest_agrees"] = successor_manifest_semantics == cold_manifest_semantics
                _write(output / "semantic-manifest-comparison.json", dict(
                    incremental=successor_manifest_semantics, cold=cold_manifest_semantics,
                    source_head_generations_remain_distinct=successor.generation != cold_head.generation))
            cold_match = matcher.match_finite_integer_intent(index=cold, repository=repository,
                repository_id=head.repository_id, expected_head=cold_head,
                intent_document=matcher.build_finite_integer_intent(INSTRUCTION), source_text=INSTRUCTION,
                output=output / "cold-observation", tool_policy=tools, **native_resources())
            report["cold_successor_agrees"] = finite_successor_semantics(cold_match) == finite_successor_semantics(matched)
            _write(output / "successor-semantic-comparison.json", {
                "incremental": finite_successor_semantics(matched),
                "cold": finite_successor_semantics(cold_match),
                "generation_bound_receipts_remain_distinct": matched["observation_cid"] != cold_match["observation_cid"]})
            _write(output / "cold-match.json", cold_match)
        advance_phase("resource_cleanup")
        if trial_envelope is not None:
            finish_managed()
            resources_stack.close()
            report["full_trial_resource_receipt"] = trial_envelope.receipt()
        if trial_pipeline is not None:
            report["pipeline_resource_receipt"] = trial_pipeline.receipt()
        report["resource_state"] = scheduler.snapshot()
        report["owned_remaining_leases"] = [row for row in scheduler.active_leases()
                                             if row["owner_pid"] == os.getpid()]
        report["qualified"] = bool(report.get("task", {}).get("status") == "completed"
            and report["stop"]["status"] == "succeeded" and report["remaining_processes"] == 0
            and not report["bootstrap_errors"] and report["final_public_check_exit_code"] == 0
            and report["published_commit"] != baseline and report["published_source_matches_checked_candidate"]
            and report["stale_index_refused"] and report["stale_dispatch_refused"]
            and report["cold_successor_agrees"] and report["successor"]["fact_count"] == 2
            and (not semantic_manifest or report.get("cold_semantic_manifest_agrees") is True)
            and (not checked_cache or (report.get("checked_cache_replay_agrees") is True
                                      and report.get("stale_checked_cache_refused") is True))
            and (not behavioral_evidence or report.get("behavioral_worker_fence_replayed") is True)
            and (not full_trial_resources or report.get("delegated_worker_resources_verified") is True)
            and (not pipeline_resources or (report["pipeline_resource_receipt"]["closed"]
                and not report["pipeline_resource_receipt"]["retained_disk_reservations"]
                and not report["pipeline_resource_receipt"]["retained_host_phase_count"]))
            and not report["successor"]["residuals"]
            and not report["owned_remaining_leases"])
    except Exception as error:
        primary_error = error
        report["error"] = dict(type=type(error).__name__, message=str(error)[:4096])
        if "scheduler" in locals():
            try:
                report["resource_state"] = scheduler.snapshot()
            except Exception as observation_error:
                report["resource_observation_error"] = type(observation_error).__name__
        report["host_pressure"] = {kind: Path("/proc/pressure", kind).read_text()
            for kind in ("cpu", "memory", "io") if Path("/proc/pressure", kind).is_file()}
    finally:
        for cleanup in (lambda: finish_managed(primary_error), resources_stack.close):
            try:
                cleanup()
            except Exception as error:
                cleanup_failure(error)
        if trial_envelope is not None:
            try:
                report["full_trial_resource_receipt"] = trial_envelope.receipt()
            except Exception as error:
                cleanup_failure(error)
        if trial_pipeline is not None:
            try:
                report["pipeline_resource_receipt"] = trial_pipeline.receipt()
            except Exception as error:
                cleanup_failure(error)
        finished = time.monotonic()
        report["trial_phases"].append(dict(phase=phase_name,
            status="failed" if "error" in report else "completed",
            elapsed_seconds=finished-phase_started, start_seconds=phase_started-started,
            end_seconds=finished-started))
        report["seconds"] = finished - started
        report["phase_accounting"] = dict(schema="repository-trial-wall-accounting@1",
            includes_queue_waits=True, includes_cleanup=True,
            seconds=sum(row["elapsed_seconds"] for row in report["trial_phases"]),
            complete_contiguous_wall_coverage=True,
            setup_before_resource_admission=True,
            enforcement="cooperative_parent_and_native_subprocess_limits")
        _write(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--lean", required=True, type=Path)
    parser.add_argument("--public-evidence", action="store_true")
    parser.add_argument("--semantic-manifest", action="store_true")
    parser.add_argument("--checked-cache", action="store_true")
    parser.add_argument("--behavioral-evidence", action="store_true")
    parser.add_argument("--budgeted-preparation", action="store_true")
    parser.add_argument("--full-trial-resources", action="store_true")
    parser.add_argument("--pipeline-resources", action="store_true")
    result = qualify(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("qualified", "seconds", "provider_calls")}))
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
