from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import sys
import time
from types import MappingProxyType

import pytest

from benchmarks.logic_pipeline import (
    ablation,
    adapters as logic_adapters,
    cache_measurement,
    report,
    runner,
)
from benchmarks.logic_pipeline.adapters import (
    SpacyAdapter,
    SpacyAdapterConfig,
    SpacyAdapterMode,
    StageAdapter,
    StageOutput,
    SymaiAdapter,
    SymaiAdapterConfig,
)
from benchmarks.logic_pipeline.capabilities import (
    HSSLEV0118D14,
    WORKTREE_SAFETY_SCHEMA,
    WorktreeSafetyReceipt,
)
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    CaseResultRecord,
    FailureCode,
    NATIVE_KERNEL_RECEIPT_SCHEMA,
    OutcomeStatus,
    ProtocolContractError,
    Split,
    StageName,
    StageRecord,
    StageStatus,
    canonical_json,
    validate_native_kernel_stage_receipt,
)


SHA_ENVIRONMENT = hashlib.sha256(b"pinned environment").hexdigest()
SHA_DRIFTED_ENVIRONMENT = hashlib.sha256(b"drifted environment").hexdigest()
SHA_MANIFEST = hashlib.sha256(b"failure-isolation cases").hexdigest()
SOURCE_COMMIT = "1" * 40


def _scoped_run_id(base: str, tmp_path: Path) -> str:
    scope = hashlib.sha256(
        str(tmp_path.resolve()).encode("utf-8")
    ).hexdigest()[:12]
    return f"{base}-{scope}"


def _cases(*case_ids: str) -> tuple[runner.AblationCase, ...]:
    return tuple(
        runner.AblationCase.create(
            case_id,
            {"case_id": case_id, "text": f"input for {case_id}"},
            split=Split.PILOT,
        )
        for case_id in case_ids
    )


def _plan(
    run_id: str,
    cases: tuple[runner.AblationCase, ...],
    *,
    environment_sha256: str = SHA_ENVIRONMENT,
    variant_id: str = "A0",
    cache_mode: CacheMode = CacheMode.COLD,
    max_model_calls_per_case: int = 1,
) -> runner.AblationPlan:
    return runner.build_ablation_plan(
        run_id,
        cases,
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=70,
        variant_ids=(variant_id,),
        cache_modes=(cache_mode,),
        environment_sha256=environment_sha256,
        limits=runner.ResourceLimits(
            max_workers=1,
            case_timeout_seconds=2,
            max_memory_bytes=64 * 1024 * 1024,
            max_model_calls_per_case=max_model_calls_per_case,
            max_solver_processes_per_case=1,
        ),
    )


def _worktree_receipt(tmp_path: Path, run_id: str) -> WorktreeSafetyReceipt:
    source = tmp_path / "active-source"
    common = tmp_path / "git-common"
    state = tmp_path / "benchmark-state" / run_id
    worktree = state / "worktrees" / "source"
    source.mkdir()
    common.mkdir()
    worktree.mkdir(parents=True)
    return WorktreeSafetyReceipt(
        schema=WORKTREE_SAFETY_SCHEMA,
        run_id=run_id,
        evidence=HSSLEV0118D14(),
        source_checkout=source,
        source_git_common_dir=common,
        source_head=SOURCE_COMMIT,
        source_branch="refs/heads/main",
        source_status_sha256=hashlib.sha256(b"clean").hexdigest(),
        base_revision=SOURCE_COMMIT,
        base_commit=SOURCE_COMMIT,
        worktree_root=worktree,
        worktree_commit=SOURCE_COMMIT,
        state_root=state,
        submodule_commits=MappingProxyType({}),
        detached=True,
        auto_merge=False,
        source_unchanged=True,
    )


def _accepted_kernel_output(
    request,
    *,
    effective_identity: dict[str, object],
    process_stdout: bytes = b"accepted",
    receipt_extra: dict[str, object] | None = None,
) -> StageOutput:
    candidate = next(
        artifact
        for artifact in request.upstream_artifacts
        if artifact.stage is StageName.COMPILER
    )
    attempt_body = {
        "attempt_index": 0,
        "candidate_source": StageName.COMPILER.value,
        "candidate_artifact_sha256": candidate.digest,
        "source_sha256": hashlib.sha256(
            b"replay proof source"
        ).hexdigest(),
        "command_sha256": hashlib.sha256(
            b"lean Main.lean"
        ).hexdigest(),
        "stdout_sha256": hashlib.sha256(process_stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "returncode": 0,
        "timed_out": False,
        "cancelled": False,
        "resource_exhausted": False,
        "termination_reason": "completed",
        "process_group_reaped": True,
        "active_process_count": 0,
        "accepted": True,
    }
    attempt = {
        **attempt_body,
        "attempt_sha256": hashlib.sha256(
            canonical_json(attempt_body).encode("utf-8")
        ).hexdigest(),
    }
    receipt = {
        "schema": NATIVE_KERNEL_RECEIPT_SCHEMA,
        "protocol_sha256": request.protocol_sha256,
        "run_id": request.run_id,
        "case_id": request.case_id,
        "case_manifest_sha256": request.case_manifest_sha256,
        "variant_id": request.variant_id,
        "split": request.split.value,
        "cache_mode": request.cache_mode.value,
        "input_sha256": request.input_sha256,
        "environment_sha256": request.environment_sha256,
        "independent": True,
        "accepted": True,
        "active_process_count": 0,
        "compiled_obligation_sha256": hashlib.sha256(
            b"compiled obligation"
        ).hexdigest(),
        "obligation_sha256": hashlib.sha256(
            b"obligation"
        ).hexdigest(),
        "candidate_source": attempt["candidate_source"],
        "candidate_artifact_sha256": candidate.digest,
        "source_sha256": attempt["source_sha256"],
        "semantic_context_sha256": hashlib.sha256(
            b"semantic context"
        ).hexdigest(),
        "semantic_artifact_sha256s": [candidate.digest],
        "command_sha256": attempt["command_sha256"],
        "stdout_sha256": attempt["stdout_sha256"],
        "stderr_sha256": attempt["stderr_sha256"],
        "returncode": attempt["returncode"],
        "timed_out": attempt["timed_out"],
        "cancelled": attempt["cancelled"],
        "resource_exhausted": attempt["resource_exhausted"],
        "termination_reason": attempt["termination_reason"],
        "process_group_reaped": attempt["process_group_reaped"],
        "candidate_attempts": [attempt],
        "candidate_attempts_sha256": hashlib.sha256(
            canonical_json([attempt]).encode("utf-8")
        ).hexdigest(),
        "selected_attempt": {
            key: attempt[key]
            for key in (
                "attempt_index",
                "candidate_source",
                "candidate_artifact_sha256",
                "attempt_sha256",
                "accepted",
            )
        },
        **({} if receipt_extra is None else receipt_extra),
    }
    receipt_sha256 = hashlib.sha256(
        canonical_json(receipt).encode("utf-8")
    ).hexdigest()
    return StageOutput(
        data={**receipt, "receipt_sha256": receipt_sha256},
        effective_identity=effective_identity,
        kernel_accepted=True,
        kernel_receipt_sha256=receipt_sha256,
    )


def _run_replay_pair(
    tmp_path: Path,
    *,
    replay_environment: str = SHA_ENVIRONMENT,
    replay_backend_drift: bool = False,
    replay_proof_execution_drift: bool = False,
) -> tuple[
    CaseResultRecord,
    CaseResultRecord,
    object,
    object,
    WorktreeSafetyReceipt,
]:
    case = _cases("replay-case")
    source_run_id = _scoped_run_id("source-replay", tmp_path)
    replay_run_id = _scoped_run_id("fresh-replay", tmp_path)

    def adapters(
        *,
        drift: bool = False,
        proof_execution_drift: bool = False,
    ):
        result = {}
        for stage in (StageName.COMPILER, StageName.SPACY, StageName.KERNEL):
            def handler(request, current_stage=stage):
                data = {
                    "normalized": request.case_id,
                    "stable": True,
                    "stage": current_stage.value,
                }
                identity = dict(request.requested_identity)
                if drift and current_stage is StageName.SPACY:
                    identity["backend_revision"] = "drifted"
                if current_stage is StageName.KERNEL:
                    return _accepted_kernel_output(
                        request,
                        effective_identity=identity,
                        process_stdout=(
                            b"accepted with drift"
                            if proof_execution_drift
                            else b"accepted"
                        ),
                    )
                return StageOutput(
                    data=data,
                    effective_identity=identity,
                )

            result[stage] = StageAdapter(stage, handler)
        return result

    source_run = runner.execute_ablation(
        _plan(source_run_id, case, variant_id="A1"),
        adapters(),
        output_root=tmp_path / "source-output",
        resume=False,
    )
    replay_run = runner.execute_ablation(
        _plan(
            replay_run_id,
            case,
            environment_sha256=replay_environment,
            variant_id="A1",
        ),
        adapters(
            drift=replay_backend_drift,
            proof_execution_drift=replay_proof_execution_drift,
        ),
        output_root=tmp_path / "replay-output",
        resume=False,
    )
    return (
        source_run.results[0],
        replay_run.results[0],
        source_run.contracts[0],
        replay_run.contracts[0],
        _worktree_receipt(tmp_path, replay_run_id),
    )


class _ReplaySymaiEngine:
    def __init__(
        self,
        *,
        proposition: str,
        provider: str,
        model: str,
    ) -> None:
        self.proposition = proposition
        self.provider = provider
        self.model = model

    def forward(self, _argument):
        return (
            [
                json.dumps(
                    {
                        "candidate_ir": {
                            "propositions": [self.proposition],
                        },
                        "normalized_predicates": [self.proposition],
                        "quantifiers": ["forall"],
                        "entities": ["agency"],
                        "ambiguity_flags": [],
                        "confidence": 0.95,
                        "validation_errors": [],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ],
            {
                "backend": "llm_router",
                "effective_provider_name": self.provider,
                "effective_model_name": self.model,
            },
        )


class _ReplaySymaiAdapter(SymaiAdapter):
    def __init__(self, *, inject_unknown: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, "_inject_unknown", inject_unknown)

    def invoke(self, request, *, telemetry=None):
        invocation = super().invoke(request, telemetry=telemetry)
        if not self._inject_unknown:
            return invocation
        output = invocation.output
        data = dict(output.data)
        identity = dict(output.effective_identity)
        data["unexpected_semantic_extension"] = {
            "value": "must remain fail-closed",
        }
        identity["unexpected_backend_identity"] = "drifted"
        return replace(
            invocation,
            output=replace(
                output,
                data=data,
                effective_identity=identity,
            ),
        )


def _warm_to_cold_replay_pair(
    tmp_path: Path,
    *,
    replay_cache_mode: CacheMode = CacheMode.COLD,
    drift: str | None = None,
) -> tuple[
    CaseResultRecord,
    CaseResultRecord,
    object,
    object,
    WorktreeSafetyReceipt,
]:
    case = _cases("warm-replay-case")
    source_run_id = _scoped_run_id(
        "source-warm-replay",
        tmp_path,
    )
    replay_run_id = _scoped_run_id(
        "fresh-cold-replay",
        tmp_path,
    )

    def adapters(*, selected_drift: str | None = None):
        proposition = (
            "DifferentSemanticPredicate"
            if selected_drift == "symai_semantic"
            else "MustFileAnnualReport"
        )
        provider = (
            "different_provider"
            if selected_drift == "symai_provider"
            else "ipfs_accelerate_py"
        )
        model = (
            "DifferentLeanstralModel"
            if selected_drift == "symai_model"
            else "Leanstral-119B"
        )
        engine = _ReplaySymaiEngine(
            proposition=proposition,
            provider=provider,
            model=model,
        )
        symai = _ReplaySymaiAdapter(
            inject_unknown=selected_drift == "symai_unknown",
            config=SymaiAdapterConfig(
                provider=provider,
                model=model,
                max_retries=0,
                cache_enabled=True,
            ),
            engine_factory=lambda _config, _namespace: engine,
            trace_getter=lambda: {},
            cache={},
        )

        def simple(request, stage: StageName):
            return StageOutput(
                data={
                    "normalized": request.case_id,
                    "stable": True,
                    "stage": stage.value,
                },
                effective_identity=dict(request.requested_identity),
            )

        def hammer(request):
            return StageOutput(
                status=StageStatus.FAILED,
                effective_identity=dict(request.requested_identity),
                failure_code=(
                    FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE
                ),
                failure_detail=(
                    "bounded replay fixture fallback to Leanstral"
                ),
            )

        def leanstral(request):
            prompt = (
                "different prompt"
                if selected_drift == "lean_prompt"
                else "frozen prompt"
            )
            lean_model = (
                "DifferentLeanstralModel"
                if selected_drift == "lean_model"
                else "Leanstral-119B"
            )
            source = (
                "different Lean source"
                if selected_drift == "lean_source"
                else "theorem replay : True := by trivial"
            )
            proof = (
                "different proof"
                if selected_drift == "lean_proof"
                else "by trivial"
            )
            data = {
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "replay-lean-proof.v1"
                ),
                "prompt_sha256": hashlib.sha256(
                    prompt.encode("utf-8")
                ).hexdigest(),
                "model": lean_model,
                "source_sha256": hashlib.sha256(
                    source.encode("utf-8")
                ).hexdigest(),
                "proof_sha256": hashlib.sha256(
                    proof.encode("utf-8")
                ).hexdigest(),
                "proof_text": proof,
                "proof_success": True,
            }
            if selected_drift == "lean_unknown":
                data["unexpected_proof_extension"] = True
            return StageOutput(
                data=data,
                effective_identity={
                    **dict(request.requested_identity),
                    "provider": "leanstral_local",
                    "model": lean_model,
                    "prompt_sha256": data["prompt_sha256"],
                    "source_sha256": data["source_sha256"],
                },
            )

        def kernel(request):
            return _accepted_kernel_output(
                request,
                effective_identity=dict(request.requested_identity),
                process_stdout=(
                    b"accepted with process drift"
                    if selected_drift == "kernel_process"
                    else b"accepted"
                ),
                receipt_extra=(
                    {"unexpected_kernel_extension": "drifted"}
                    if selected_drift == "kernel_unknown"
                    else None
                ),
            )

        return {
            StageName.COMPILER: StageAdapter(
                StageName.COMPILER,
                lambda request: simple(request, StageName.COMPILER),
            ),
            StageName.SPACY: SpacyAdapter(
                config=SpacyAdapterConfig(
                    mode=SpacyAdapterMode.REGEX_LEGAL,
                ),
            ),
            StageName.SYMAI: symai,
            StageName.HAMMER: StageAdapter(StageName.HAMMER, hammer),
            StageName.LEANSTRAL: StageAdapter(
                StageName.LEANSTRAL, leanstral
            ),
            StageName.KERNEL: StageAdapter(StageName.KERNEL, kernel),
        }

    source_run = runner.execute_ablation(
        _plan(
            source_run_id,
            case,
            variant_id="A5",
            cache_mode=CacheMode.WARM,
            max_model_calls_per_case=4,
        ),
        adapters(),
        output_root=tmp_path / "source-output",
        resume=False,
    )
    replay_run = runner.execute_ablation(
        _plan(
            replay_run_id,
            case,
            variant_id="A5",
            cache_mode=replay_cache_mode,
            max_model_calls_per_case=4,
        ),
        adapters(selected_drift=drift),
        output_root=tmp_path / "replay-output",
        resume=False,
    )
    return (
        source_run.results[0],
        replay_run.results[0],
        source_run.contracts[0],
        replay_run.contracts[0],
        _worktree_receipt(tmp_path, replay_run_id),
    )


def _direct_leanstral_output(
    request,
    *,
    drift: str | None = None,
) -> StageOutput:
    proof_text = (
        "exact different_proof"
        if drift == "proof"
        else "exact trivial"
    )
    model = (
        "DifferentLeanstralModel"
        if drift == "model"
        else "Leanstral-119B"
    )
    prompt = (
        "different frozen prompt"
        if drift == "prompt"
        else "frozen direct Leanstral prompt"
    )
    prompt_sha256 = hashlib.sha256(
        prompt.encode("utf-8")
    ).hexdigest()
    theorem_id = (
        "different_normalized_theorem"
        if drift == "normalized_content"
        else "replay_theorem"
    )
    request_id = "leanstral-" + hashlib.sha256(
        (
            f"{request.run_id}:{request.case_id}:"
            f"{request.input_sha256}:0"
        ).encode("utf-8")
    ).hexdigest()[:48]
    timeout_ms = (
        119_000
        if request.cache_mode is CacheMode.WARM
        else 117_000
    )
    proposal = {
        "schema": logic_adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
        "theorem_id": theorem_id,
        "proposal_kind": "proof",
        "proof_text": proof_text,
    }
    normalized_proposal = canonical_json(proposal).encode("utf-8")
    raw_content = json.dumps(
        proposal,
        ensure_ascii=False,
        indent=4 if drift == "raw_content" else 2,
        sort_keys=True,
    ).encode("utf-8")
    canonical_source_digest = "sha256:" + hashlib.sha256(
        b"frozen canonical source"
    ).hexdigest()
    theorem_equivalence_key = hashlib.sha256(
        b"frozen theorem equivalence"
    ).hexdigest()
    context_capsule_id = hashlib.sha256(
        b"frozen context capsule"
    ).hexdigest()
    boundary = {
        "schema": logic_adapters.LEANSTRAL_GENERATION_BOUNDARY_SCHEMA,
        "endpoint": "http://127.0.0.1:8080/v1",
        "provider": "leanstral_local",
        "requested_model": model,
        "response_model": model,
        "cache_prompt": False,
        "prompt_sha256": prompt_sha256,
        "request_payload_sha256": hashlib.sha256(
            logic_adapters._leanstral_completion_payload_bytes(
                prompt,
                model=model,
                max_tokens=(
                    logic_adapters.LEANSTRAL_MEASURED_MAX_NEW_TOKENS
                ),
                theorem_id=theorem_id,
            )
        ).hexdigest(),
        "response_envelope_sha256": hashlib.sha256(
            f"response-envelope:{request.run_id}".encode("utf-8")
        ).hexdigest(),
        "raw_model_content_sha256": hashlib.sha256(
            raw_content
        ).hexdigest(),
        "raw_model_content_bytes": len(raw_content),
        "normalized_proposal_sha256": hashlib.sha256(
            normalized_proposal
        ).hexdigest(),
        "normalized_proposal_bytes": len(normalized_proposal),
        "normalization": "none",
    }
    boundary["receipt_sha256"] = hashlib.sha256(
        canonical_json(boundary).encode("utf-8")
    ).hexdigest()
    output_sha256 = hashlib.sha256(
        proof_text.encode("utf-8")
    ).hexdigest()
    draft = {
        "schema_version": logic_adapters.LEANSTRAL_DRAFT_SCHEMA,
        "artifact_kind": "llm_output",
        "stage": "model_draft",
        "draft_text": proof_text,
        "proof_text": proof_text,
        "request_id": request_id,
        "benchmark_request_id": (
            f"{request.run_id}:{request.case_id}"
        ),
        "llm_provider": "leanstral_local",
        "model": model,
        "obligation_ids": ["replay-obligation"],
        "canonical_source_digest": canonical_source_digest,
        "prompt_sha256": prompt_sha256,
        "theorem_id": theorem_id,
        "theorem_equivalence_key": theorem_equivalence_key,
        "context_capsule_id": context_capsule_id,
        "proposal_kind": "proof",
        "proposal_schema": (
            logic_adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
        ),
        "resource_class": "model",
        "output_sha256": output_sha256,
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "kernel_checked": False,
        "repair_attempt": 0,
        "timeout_ms": timeout_ms,
        "token_budget": (
            logic_adapters.LEANSTRAL_MEASURED_MAX_NEW_TOKENS
        ),
        "metadata": {
            "structured_output": True,
            "fixed_theorem_identity_digest": hashlib.sha256(
                b"frozen fixed theorem identity"
            ).hexdigest(),
            "benchmark_generation_boundary": boundary,
        },
        "decomposition": [],
        "reused_artifact_ids": [],
        "prompt_tokens": 16,
        "response_tokens": 2,
        "proof_attempted": False,
        "proof_success": False,
        "can_mutate_canonical_source": False,
        "can_mutate_obligations": False,
    }
    stable_artifact_identity = {
        key: draft[key]
        for key in (
            "schema_version",
            "llm_provider",
            "model",
            "obligation_ids",
            "canonical_source_digest",
            "theorem_id",
            "theorem_equivalence_key",
            "context_capsule_id",
            "proposal_kind",
            "prompt_sha256",
            "output_sha256",
        )
    }
    draft["artifact_id"] = "leanstral-draft-" + hashlib.sha256(
        canonical_json(stable_artifact_identity).encode("utf-8")
    ).hexdigest()
    evidence = {
        "schema": logic_adapters.LEANSTRAL_EVIDENCE_SCHEMA,
        "obligation_id": "replay-obligation",
        "mode": "synthesis",
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "draft": draft,
        "trust": {
            "assurance": "unverified",
            "verified": False,
            "authoritative": False,
            "kernel_checked": False,
        },
        "resource_classes": {
            "model_inference": "model",
            "kernel_check": "kernel",
        },
    }
    evidence_id = hashlib.sha256(
        canonical_json(evidence).encode("utf-8")
    ).hexdigest()
    return StageOutput(
        data={"evidence_id": evidence_id, **evidence},
        effective_identity={
            **dict(request.requested_identity),
            "provider": "leanstral_local",
            "model": model,
            "obligation_id": "replay-obligation",
            "repair_attempt": 0,
            "resource_class": "model",
            "generation_boundary_sha256": boundary[
                "receipt_sha256"
            ],
        },
    )


def _direct_leanstral_replay_pair(
    tmp_path: Path,
    *,
    drift: str | None = None,
) -> tuple[
    CaseResultRecord,
    CaseResultRecord,
    object,
    object,
    WorktreeSafetyReceipt,
]:
    case = _cases("direct-lean-replay-case")
    source_run_id = _scoped_run_id(
        "source-direct-lean",
        tmp_path,
    )
    replay_run_id = _scoped_run_id(
        "replay-direct-lean",
        tmp_path,
    )

    def adapters(*, selected_drift: str | None = None):
        def simple(request, stage: StageName):
            return StageOutput(
                data={
                    "normalized": request.case_id,
                    "stable": True,
                    "stage": stage.value,
                },
                effective_identity=dict(request.requested_identity),
            )

        def hammer(request):
            return StageOutput(
                status=StageStatus.FAILED,
                effective_identity=dict(request.requested_identity),
                failure_code=(
                    FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE
                ),
                failure_detail=(
                    "bounded direct replay fallback to Leanstral"
                ),
            )

        def kernel(request):
            return _accepted_kernel_output(
                request,
                effective_identity=dict(request.requested_identity),
            )

        return {
            StageName.COMPILER: StageAdapter(
                StageName.COMPILER,
                lambda request: simple(request, StageName.COMPILER),
            ),
            StageName.SPACY: StageAdapter(
                StageName.SPACY,
                lambda request: simple(request, StageName.SPACY),
            ),
            StageName.HAMMER: StageAdapter(StageName.HAMMER, hammer),
            StageName.LEANSTRAL: StageAdapter(
                StageName.LEANSTRAL,
                lambda request: _direct_leanstral_output(
                    request,
                    drift=selected_drift,
                ),
            ),
            StageName.KERNEL: StageAdapter(StageName.KERNEL, kernel),
        }

    source_run = runner.execute_ablation(
        _plan(
            source_run_id,
            case,
            variant_id="A3",
            cache_mode=CacheMode.WARM,
            max_model_calls_per_case=2,
        ),
        adapters(),
        output_root=tmp_path / "source-output",
        resume=False,
    )
    replay_run = runner.execute_ablation(
        _plan(
            replay_run_id,
            case,
            variant_id="A3",
            cache_mode=CacheMode.COLD,
            max_model_calls_per_case=2,
        ),
        adapters(selected_drift=drift),
        output_root=tmp_path / "replay-output",
        resume=False,
    )
    return (
        source_run.results[0],
        replay_run.results[0],
        source_run.contracts[0],
        replay_run.contracts[0],
        _worktree_receipt(tmp_path, replay_run_id),
    )


def _replace_warm_symai_prime(
    result: CaseResultRecord,
    *,
    cross_bound: bool,
) -> CaseResultRecord:
    rebuilt: list[StageRecord] = []
    for stage in result.stages:
        data = stage.to_dict()["data"]
        identity = dict(stage.provenance.effective_identity)
        if stage.stage is StageName.SYMAI:
            assert isinstance(data, dict)
            receipt = dict(
                data[cache_measurement.SYMAI_CACHE_PRIME_FIELD]
            )
            if cross_bound:
                receipt["case_id"] = "copied-cross-bound-case"
                receipt["receipt_sha256"] = hashlib.sha256(
                    canonical_json(
                        {
                            key: value
                            for key, value in receipt.items()
                            if key != "receipt_sha256"
                        }
                    ).encode("utf-8")
                ).hexdigest()
                identity[
                    cache_measurement.SYMAI_CACHE_PRIME_DIGEST_FIELD
                ] = receipt["receipt_sha256"]
            else:
                receipt["prime_semantic_output_sha256"] = "f" * 64
            data[cache_measurement.SYMAI_CACHE_PRIME_FIELD] = receipt
        provenance = replace(
            stage.provenance,
            effective_identity=identity,
            upstream_stage_digests=tuple(
                item.digest for item in rebuilt
            ),
        )
        rebuilt.append(
            StageRecord.create(
                protocol_sha256=stage.protocol_sha256,
                run_id=stage.run_id,
                case_id=stage.case_id,
                case_manifest_sha256=stage.case_manifest_sha256,
                variant_id=stage.variant_id,
                split=stage.split,
                cache_mode=stage.cache_mode,
                stage=stage.stage,
                adapter_version=stage.adapter_version,
                status=stage.status,
                provenance=provenance,
                telemetry=stage.telemetry,
                data=data,
                failure_code=stage.failure_code,
                failure_detail=stage.failure_detail,
                kernel_accepted=stage.kernel_accepted,
                kernel_receipt_sha256=stage.kernel_receipt_sha256,
            )
        )
    return CaseResultRecord.from_stages(rebuilt)


def test_injected_failures_are_classified_bounded_and_local(
    tmp_path: Path,
) -> None:
    kinds = {
        "missing-tool": (
            report.FailureInjectionKind.MISSING_TOOL,
            FailureCode.CAPABILITY_UNAVAILABLE,
        ),
        "malformed-output": (
            report.FailureInjectionKind.MALFORMED_OUTPUT,
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        ),
        "timeout": (
            report.FailureInjectionKind.TIMEOUT,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
        ),
        "cancellation": (
            report.FailureInjectionKind.CANCELLATION,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
        ),
        "cache-corruption": (
            report.FailureInjectionKind.CACHE_CORRUPTION,
            FailureCode.CACHE_CONTAMINATION,
        ),
        "backend-drift": (
            report.FailureInjectionKind.BACKEND_DRIFT,
            FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
        ),
    }
    case_ids = (*kinds, "healthy-case")

    def handler(request):
        if request.case_id == "healthy-case":
            return {"case_id": request.case_id, "healthy": True}
        kind, code = kinds[request.case_id]
        if kind is report.FailureInjectionKind.MISSING_TOOL:
            return StageOutput(
                status=StageStatus.UNAVAILABLE,
                failure_code=code,
                failure_detail="injected missing compiler",
            )
        if kind is report.FailureInjectionKind.MALFORMED_OUTPUT:
            return {"not-json-serializable"}  # runner must retain this exception
        return StageOutput(
            status=StageStatus.FAILED,
            failure_code=code,
            failure_detail=f"injected {kind.value}",
        )

    # Fatal injection classes are independent experiments.  Running each in
    # its own namespace preserves their classification evidence without
    # asking the ablation executor to continue past a required stop.
    by_case: dict[str, CaseResultRecord] = {}
    for case_id in case_ids:
        run = runner.execute_ablation(
            _plan(f"failure-matrix-{case_id}", _cases(case_id)),
            {StageName.COMPILER: StageAdapter(StageName.COMPILER, handler)},
            output_root=tmp_path / "matrix" / case_id,
            resume=False,
        )
        assert len(run.results) == 1
        assert run.result_paths[0].is_file()
        expected_stop = (
            kinds[case_id][1]
            if case_id in {"cache-corruption", "backend-drift"}
            else None
        )
        assert run.stop_failure_code is expected_stop
        assert run.complete is (expected_stop is None)
        by_case[case_id] = run.results[0]

    assert len(by_case) == len(case_ids)
    assert by_case["healthy-case"].status is OutcomeStatus.NOT_VERIFIED

    records = []
    for case_id, (kind, code) in kinds.items():
        result = by_case[case_id]
        assert result.failure_code is code
        record = report.FailureIsolationRecord.classify(
            f"inject-{case_id}",
            kind,
            result,
            elapsed_seconds=0.01,
            limit_seconds=1.0,
            affected_case_ids=(case_id,),
        )
        assert record.case_id == case_id
        assert record.stop_required is (
            kind
            in {
                report.FailureInjectionKind.CACHE_CORRUPTION,
                report.FailureInjectionKind.BACKEND_DRIFT,
            }
        )
        records.append(record)

    with pytest.raises(report.RobustnessValidationError, match="exactly its own"):
        report.FailureIsolationRecord.classify(
            "leaky-failure",
            report.FailureInjectionKind.CANCELLATION,
            by_case["cancellation"],
            elapsed_seconds=0.01,
            limit_seconds=1,
            affected_case_ids=("cancellation", "healthy-case"),
        )


def test_failed_stage_short_circuits_its_case_but_not_the_next_case(
    tmp_path: Path,
) -> None:
    calls: list[tuple[StageName, str]] = []

    def compiler(request):
        calls.append((StageName.COMPILER, request.case_id))
        if request.case_id == "failed-case":
            return StageOutput(
                status=StageStatus.FAILED,
                failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
                failure_detail="injected compiler failure",
            )
        return {"compiled": request.case_id}

    def spacy(request):
        calls.append((StageName.SPACY, request.case_id))
        return {"parsed": request.case_id}

    plan = runner.build_ablation_plan(
        "short-circuit",
        _cases("failed-case", "healthy-case"),
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=3,
        variant_ids=("A1",),
        cache_modes=(CacheMode.COLD,),
        environment_sha256=SHA_ENVIRONMENT,
    )
    run = runner.execute_ablation(
        plan,
        {
            StageName.COMPILER: StageAdapter(StageName.COMPILER, compiler),
            StageName.SPACY: StageAdapter(StageName.SPACY, spacy),
        },
        output_root=tmp_path,
        resume=False,
    )

    assert (StageName.SPACY, "failed-case") not in calls
    assert (StageName.SPACY, "healthy-case") in calls
    assert len(run.results) == 2


def test_immediate_stop_is_persisted_and_resume_cannot_skip_it(
    tmp_path: Path,
) -> None:
    plan = _plan(
        "immediate-stop",
        _cases("first", "second", "third"),
    )
    trigger_case = plan.jobs[0].case_id
    calls: list[str] = []

    def handler(request):
        calls.append(request.case_id)
        if request.case_id == trigger_case:
            return StageOutput(
                status=StageStatus.FAILED,
                failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                failure_detail="injected fatal receipt failure",
            )
        return {"case_id": request.case_id}

    output_root = tmp_path / "immediate-stop"
    run = runner.execute_ablation(
        plan,
        {StageName.COMPILER: StageAdapter(StageName.COMPILER, handler)},
        output_root=output_root,
        resume=False,
    )

    assert run.complete is False
    assert (
        run.stop_failure_code
        is FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    )
    assert calls == [trigger_case]
    assert len(run.results) == 1
    assert (
        run.results[0].failure_code
        is FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    )
    assert run.result_paths[0].is_file()
    assert all(not path.exists() for path in run.result_paths[1:])
    with pytest.raises(
        runner.AblationValidationError,
        match="incomplete",
    ):
        ablation.validate_ablation_evidence(
            plan,
            output_root=output_root,
        )

    resumed_calls: list[str] = []

    def forbidden(request):
        resumed_calls.append(request.case_id)
        raise AssertionError("resume crossed a persisted stop condition")

    resumed = runner.execute_ablation(
        plan,
        {StageName.COMPILER: StageAdapter(StageName.COMPILER, forbidden)},
        output_root=output_root,
        resume=True,
    )

    assert resumed.complete is False
    assert (
        resumed.stop_failure_code
        is FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    )
    assert resumed.executed_job_ids == ()
    assert resumed.resumed_job_ids == (plan.jobs[0].job_id,)
    assert len(resumed.results) == 1
    assert resumed_calls == []


@pytest.mark.parametrize("trigger_index", (0, -1))
def test_complete_persisted_sequence_cannot_bypass_a_protocol_stop(
    tmp_path: Path,
    trigger_index: int,
) -> None:
    plan = _plan(
        f"persisted-stop-{trigger_index}",
        _cases("one", "two", "three"),
    )
    output_root = tmp_path / f"persisted-stop-{trigger_index}"
    run = runner.execute_ablation(
        plan,
        {
            StageName.COMPILER: StageAdapter(
                StageName.COMPILER,
                lambda request: {"case_id": request.case_id},
            )
        },
        output_root=output_root,
        resume=False,
    )
    assert run.complete

    job = plan.jobs[trigger_index]
    contract = next(
        item
        for item in plan.run_contracts
        if (
            item.requested_variant_id == job.variant_id
            and item.cache_mode is job.cache_mode
        )
    )
    fatal = ablation._failure(
        plan,
        job,
        FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
        "restamped fatal persisted result",
    )
    run.result_paths[trigger_index].write_text(
        canonical_json(
            ablation._envelope(plan, job, contract, fatal)
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="frozen protocol stop condition",
    ):
        ablation.validate_ablation_evidence(
            plan,
            output_root=output_root,
        )

    resumed_calls: list[str] = []

    def forbidden(request):
        resumed_calls.append(request.case_id)
        raise AssertionError("resume invoked a backend for persisted evidence")

    resumed = runner.execute_ablation(
        plan,
        {StageName.COMPILER: StageAdapter(StageName.COMPILER, forbidden)},
        output_root=output_root,
        resume=True,
    )
    expected_count = (
        len(plan.jobs)
        if trigger_index == -1
        else trigger_index + 1
    )
    assert len(resumed.results) == expected_count
    assert resumed.complete is False
    assert (
        resumed.stop_failure_code
        is FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    )
    assert resumed_calls == []


def test_thresholded_oom_streak_resets_on_a_nonmatching_result(
    tmp_path: Path,
) -> None:
    plan = _plan(
        "oom-stop",
        _cases("one", "two", "three", "four", "five"),
    )
    ordered = [job.case_id for job in plan.jobs]
    outcomes = {
        ordered[0]: "oom",
        ordered[1]: "healthy",
        ordered[2]: "oom",
        ordered[3]: "oom",
        ordered[4]: "healthy",
    }
    calls: list[str] = []

    def handler(request):
        calls.append(request.case_id)
        if outcomes[request.case_id] == "oom":
            return StageOutput(
                status=StageStatus.FAILED,
                failure_code=FailureCode.OUT_OF_MEMORY,
                failure_detail="injected out-of-memory result",
            )
        return {"case_id": request.case_id}

    run = runner.execute_ablation(
        plan,
        {StageName.COMPILER: StageAdapter(StageName.COMPILER, handler)},
        output_root=tmp_path / "oom-stop",
        resume=False,
    )

    assert run.complete is False
    assert run.stop_failure_code is FailureCode.OUT_OF_MEMORY
    assert calls == ordered[:4]
    assert len(run.results) == 4
    assert run.results[-1].failure_code is FailureCode.OUT_OF_MEMORY
    assert not run.result_paths[4].exists()


def test_global_infrastructure_streak_stops_across_variants(
    tmp_path: Path,
) -> None:
    plan = runner.build_ablation_plan(
        "global-infrastructure-stop",
        _cases("first-block", "later-block"),
        case_manifest_sha256=SHA_MANIFEST,
        split=Split.PILOT,
        seed=17,
        variant_ids=("A0", "A1", "A2"),
        cache_modes=(CacheMode.COLD,),
        environment_sha256=SHA_ENVIRONMENT,
    )
    calls: list[tuple[str, str]] = []

    def compiler(request):
        calls.append((request.case_id, request.variant_id))
        return StageOutput(
            status=StageStatus.FAILED,
            failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
            failure_detail="injected run-wide infrastructure failure",
        )

    run = runner.execute_ablation(
        plan,
        {StageName.COMPILER: StageAdapter(StageName.COMPILER, compiler)},
        output_root=tmp_path / "global-infrastructure-stop",
        resume=False,
    )

    assert run.complete is False
    assert (
        run.stop_failure_code
        is FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
    )
    assert len(run.results) == 3
    assert len(calls) == 3
    assert len({variant for _, variant in calls}) == 3
    assert all(
        result.failure_code
        is FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
        for result in run.results
    )
    assert all(not path.exists() for path in run.result_paths[3:])


def test_timeout_and_explicit_cancellation_kill_the_process_group() -> None:
    program = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print(p.pid,flush=True);time.sleep(30)"
    )
    timed_out = report.run_bounded_process(
        (sys.executable, "-c", program),
        timeout_seconds=0.15,
        termination_grace_seconds=0.2,
    )

    assert timed_out.timed_out
    assert not timed_out.cancelled
    assert timed_out.failure_code is FailureCode.RESOURCE_LEASE_CANCELLATION
    assert timed_out.orphaned_child_count == 0
    assert timed_out.bounded
    assert report.BoundedProcessResult.from_dict(timed_out.to_dict()) == timed_out
    assert len(timed_out.digest) == 64
    child_pid = int(timed_out.stdout.strip())
    assert child_pid != timed_out.pid
    assert not Path(f"/proc/{child_pid}").exists() or (
        Path(f"/proc/{child_pid}/stat").read_text(encoding="utf-8").split()[2]
        == "Z"
    )

    class CancelSoon:
        def __init__(self) -> None:
            self.started = time.monotonic()

        def is_set(self) -> bool:
            return time.monotonic() - self.started >= 0.08

    cancelled = report.run_bounded_process(
        (sys.executable, "-c", "import time;time.sleep(30)"),
        timeout_seconds=2,
        cancellation=CancelSoon(),
        termination_grace_seconds=0.2,
    )
    assert cancelled.cancelled
    assert not cancelled.timed_out
    assert cancelled.failure_code is FailureCode.RESOURCE_LEASE_CANCELLATION
    assert cancelled.orphaned_child_count == 0
    assert cancelled.bounded


def test_normally_exiting_parent_cannot_hide_an_orphaned_child() -> None:
    program = (
        "import subprocess,sys;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "print(p.pid,flush=True)"
    )
    result = report.run_bounded_process(
        (sys.executable, "-c", program),
        timeout_seconds=1,
        termination_grace_seconds=0.2,
    )

    assert not result.timed_out
    assert not result.cancelled
    assert result.failure_code is FailureCode.ORPHANED_CHILD
    assert result.orphaned_child_count == 1
    child_pid = int(result.stdout.strip())
    assert not Path(f"/proc/{child_pid}").exists() or (
        Path(f"/proc/{child_pid}/stat").read_text(encoding="utf-8").split()[2]
        == "Z"
    )


def test_successful_receipt_replays_in_fresh_worktree_and_cold_cache(
    tmp_path: Path,
) -> None:
    original, replayed, original_contract, replay_contract, worktree = (
        _run_replay_pair(tmp_path)
    )

    replay = report.validate_replay(
        original,
        replayed,
        original_contract=original_contract,
        replay_contract=replay_contract,
        expected_environment_sha256=SHA_ENVIRONMENT,
        worktree_receipt=worktree,
        expected_source_commit=SOURCE_COMMIT,
    )

    assert replay.status is report.ReplayStatus.PASSED
    assert original.status is OutcomeStatus.VERIFIED
    assert replayed.status is OutcomeStatus.VERIFIED
    assert original.kernel_receipt_sha256 is not None
    assert replayed.kernel_receipt_sha256 is not None
    assert (
        original.kernel_receipt_sha256
        != replayed.kernel_receipt_sha256
    )
    assert validate_native_kernel_stage_receipt(original.stages[-1])
    assert validate_native_kernel_stage_receipt(replayed.stages[-1])
    assert (
        original.stages[-1].data["candidate_attempts_sha256"]
        == replayed.stages[-1].data["candidate_attempts_sha256"]
    )
    assert replay.original_run_id != replay.replay_run_id
    assert replay.original_cache_namespace != replay.replay_cache_namespace
    assert replay.source_commit == worktree.worktree_commit
    assert replay.environment_sha256 == SHA_ENVIRONMENT
    assert replay.original_receipt_sha256 != replay.replay_receipt_sha256
    assert report.ReplayValidationRecord.from_dict(replay.to_dict()) == replay


def test_warm_accepted_result_replays_in_mandatory_cold_namespace(
    tmp_path: Path,
) -> None:
    pair = _warm_to_cold_replay_pair(tmp_path)
    original, replayed = pair[:2]
    original_contract, replay_contract = pair[2:4]
    original_symai = next(
        stage
        for stage in original.stages
        if stage.stage is StageName.SYMAI
    )
    replay_symai = next(
        stage
        for stage in replayed.stages
        if stage.stage is StageName.SYMAI
    )

    assert original.status is OutcomeStatus.VERIFIED
    assert replayed.status is OutcomeStatus.VERIFIED
    assert original_contract.cache_mode is CacheMode.WARM
    assert replay_contract.cache_mode is CacheMode.COLD
    assert (
        original_symai.provenance.effective_identity["cache_namespace"]
        != replay_symai.provenance.effective_identity["cache_namespace"]
    )
    assert original_symai.provenance.effective_identity["cache_hit"] is True
    assert replay_symai.provenance.effective_identity["cache_hit"] is False
    assert "cache_prime" in original_symai.data
    assert "cache_prime" not in replay_symai.data
    assert (
        cache_measurement.symai_semantic_payload(original_symai)
        == cache_measurement.symai_semantic_payload(replay_symai)
    )
    assert (
        cache_measurement.symai_backend_identity(original_symai)
        == cache_measurement.symai_backend_identity(replay_symai)
    )

    replay = report.validate_replay(
        original,
        replayed,
        original_contract=original_contract,
        replay_contract=replay_contract,
        expected_environment_sha256=SHA_ENVIRONMENT,
        worktree_receipt=pair[4],
        expected_source_commit=SOURCE_COMMIT,
    )
    assert replay.status is report.ReplayStatus.PASSED


def test_direct_v2_leanstral_generation_replays_only_operational_bindings(
    tmp_path: Path,
) -> None:
    pair = _direct_leanstral_replay_pair(tmp_path)
    original, replayed = pair[:2]
    original_lean = next(
        stage
        for stage in original.stages
        if stage.stage is StageName.LEANSTRAL
    )
    replay_lean = next(
        stage
        for stage in replayed.stages
        if stage.stage is StageName.LEANSTRAL
    )
    original_evidence = original_lean.to_dict()["data"]
    replay_evidence = replay_lean.to_dict()["data"]
    original_draft = original_evidence["draft"]
    replay_draft = replay_evidence["draft"]
    original_boundary = original_draft["metadata"][
        "benchmark_generation_boundary"
    ]
    replay_boundary = replay_draft["metadata"][
        "benchmark_generation_boundary"
    ]

    assert original.status is OutcomeStatus.VERIFIED
    assert replayed.status is OutcomeStatus.VERIFIED
    assert (
        original_evidence["schema"]
        == logic_adapters.LEANSTRAL_EVIDENCE_SCHEMA
    )
    assert (
        original_boundary["schema"]
        == logic_adapters.LEANSTRAL_GENERATION_BOUNDARY_SCHEMA
    )
    assert original_draft["request_id"] != replay_draft["request_id"]
    assert (
        original_draft["benchmark_request_id"]
        != replay_draft["benchmark_request_id"]
    )
    assert original_draft["timeout_ms"] != replay_draft["timeout_ms"]
    assert (
        original_boundary["request_payload_sha256"]
        == replay_boundary["request_payload_sha256"]
    )
    for dependent_digest in (
        "response_envelope_sha256",
        "receipt_sha256",
    ):
        assert (
            original_boundary[dependent_digest]
            != replay_boundary[dependent_digest]
        )
    assert (
        original_evidence["evidence_id"]
        != replay_evidence["evidence_id"]
    )
    assert (
        original_lean.output_sha256
        != replay_lean.output_sha256
    )
    assert (
        original.kernel_receipt_sha256
        != replayed.kernel_receipt_sha256
    )

    stable_original = json.loads(canonical_json(original_evidence))
    stable_replay = json.loads(canonical_json(replay_evidence))
    for evidence in (stable_original, stable_replay):
        evidence.pop("evidence_id")
        draft = evidence["draft"]
        draft.pop("request_id")
        draft.pop("benchmark_request_id")
        draft.pop("timeout_ms")
        boundary = draft["metadata"]["benchmark_generation_boundary"]
        boundary.pop("response_envelope_sha256")
        boundary.pop("receipt_sha256")
    assert stable_original == stable_replay
    assert original_draft["prompt_sha256"] == replay_draft["prompt_sha256"]
    assert original_draft["model"] == replay_draft["model"]
    assert original_draft["proof_text"] == replay_draft["proof_text"]
    assert (
        original_boundary["raw_model_content_sha256"]
        == replay_boundary["raw_model_content_sha256"]
    )
    assert (
        original_boundary["normalized_proposal_sha256"]
        == replay_boundary["normalized_proposal_sha256"]
    )

    replay = report.validate_replay(
        original,
        replayed,
        original_contract=pair[2],
        replay_contract=pair[3],
        expected_environment_sha256=SHA_ENVIRONMENT,
        worktree_receipt=pair[4],
        expected_source_commit=SOURCE_COMMIT,
    )
    assert replay.status is report.ReplayStatus.PASSED


@pytest.mark.parametrize(
    "drift",
    (
        "prompt",
        "model",
        "proof",
        "raw_content",
        "normalized_content",
    ),
)
def test_direct_v2_leanstral_generation_rejects_content_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    pair = _direct_leanstral_replay_pair(tmp_path, drift=drift)
    assert pair[0].status is OutcomeStatus.VERIFIED
    assert pair[1].status is OutcomeStatus.VERIFIED
    assert validate_native_kernel_stage_receipt(pair[0].stages[-1])
    assert validate_native_kernel_stage_receipt(pair[1].stages[-1])

    with pytest.raises(
        report.RobustnessValidationError,
        match="leanstral|drift|corrupt",
    ):
        report.validate_replay(
            pair[0],
            pair[1],
            original_contract=pair[2],
            replay_contract=pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )


def test_valid_warm_symai_prime_replays_to_cold_after_receipt_validation(
    tmp_path: Path,
) -> None:
    pair = _warm_to_cold_replay_pair(tmp_path)
    original_symai = next(
        stage
        for stage in pair[0].stages
        if stage.stage is StageName.SYMAI
    )
    receipt = cache_measurement.validate_symai_warm_cache_measurement(
        original_symai
    )

    assert receipt.run_id == pair[0].run_id
    assert receipt.case_id == pair[0].case_id
    assert receipt.cache_mode == CacheMode.WARM.value
    replay = report.validate_replay(
        pair[0],
        pair[1],
        original_contract=pair[2],
        replay_contract=pair[3],
        expected_environment_sha256=SHA_ENVIRONMENT,
        worktree_receipt=pair[4],
        expected_source_commit=SOURCE_COMMIT,
    )
    assert replay.status is report.ReplayStatus.PASSED


@pytest.mark.parametrize(
    "cross_bound",
    (True, False),
    ids=("rehashed-cross-bound", "corrupt-unrehashed"),
)
def test_invalid_warm_symai_prime_fails_before_semantic_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cross_bound: bool,
) -> None:
    pair = _warm_to_cold_replay_pair(tmp_path)
    invalid = _replace_warm_symai_prime(
        pair[0],
        cross_bound=cross_bound,
    )
    invalid_symai = next(
        stage
        for stage in invalid.stages
        if stage.stage is StageName.SYMAI
    )
    with pytest.raises(ProtocolContractError):
        cache_measurement.validate_symai_warm_cache_measurement(
            invalid_symai
        )

    def projection_must_not_run(_value: object) -> object:
        raise AssertionError(
            "SyMAI semantic projection ran before prime validation"
        )

    monkeypatch.setattr(
        report,
        "symai_semantic_payload",
        projection_must_not_run,
    )
    with pytest.raises(
        report.RobustnessValidationError,
        match="corrupt or stale",
    ):
        report.validate_replay(
            invalid,
            pair[1],
            original_contract=pair[2],
            replay_contract=pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )


def test_warm_result_cannot_be_replayed_into_another_warm_cache(
    tmp_path: Path,
) -> None:
    pair = _warm_to_cold_replay_pair(
        tmp_path,
        replay_cache_mode=CacheMode.WARM,
    )
    assert pair[0].status is OutcomeStatus.VERIFIED
    assert pair[1].status is OutcomeStatus.VERIFIED
    with pytest.raises(
        report.RobustnessValidationError,
        match="cold cache",
    ):
        report.validate_replay(
            pair[0],
            pair[1],
            original_contract=pair[2],
            replay_contract=pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )


@pytest.mark.parametrize(
    "drift",
    (
        "symai_semantic",
        "symai_provider",
        "symai_model",
        "symai_unknown",
    ),
)
def test_warm_to_cold_replay_rejects_symai_semantic_or_identity_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    pair = _warm_to_cold_replay_pair(tmp_path, drift=drift)
    assert pair[0].status is OutcomeStatus.VERIFIED
    assert pair[1].status is OutcomeStatus.VERIFIED
    with pytest.raises(
        report.RobustnessValidationError,
        match="symai|backend or output drift",
    ):
        report.validate_replay(
            pair[0],
            pair[1],
            original_contract=pair[2],
            replay_contract=pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )


@pytest.mark.parametrize(
    "drift",
    (
        "lean_prompt",
        "lean_model",
        "lean_source",
        "lean_proof",
        "lean_unknown",
        "kernel_process",
        "kernel_unknown",
    ),
)
def test_warm_to_cold_replay_rejects_lean_or_kernel_execution_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    pair = _warm_to_cold_replay_pair(tmp_path, drift=drift)
    assert pair[0].status is OutcomeStatus.VERIFIED
    assert pair[1].status is OutcomeStatus.VERIFIED
    assert validate_native_kernel_stage_receipt(pair[0].stages[-1])
    assert validate_native_kernel_stage_receipt(pair[1].stages[-1])
    with pytest.raises(
        report.RobustnessValidationError,
        match="drift",
    ):
        report.validate_replay(
            pair[0],
            pair[1],
            original_contract=pair[2],
            replay_contract=pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )


def test_corrupt_stale_and_backend_drifted_receipts_fail_closed(
    tmp_path: Path,
) -> None:
    original, replayed, original_contract, replay_contract, worktree = (
        _run_replay_pair(tmp_path)
    )
    corrupted = replayed.to_dict()
    corrupted["stages"][0]["data"]["stable"] = False
    with pytest.raises(ProtocolContractError, match="output_sha256"):
        CaseResultRecord.from_dict(corrupted)

    stale_pair = _run_replay_pair(
        tmp_path / "stale",
        replay_environment=SHA_DRIFTED_ENVIRONMENT,
    )
    with pytest.raises(report.RobustnessValidationError, match="stale"):
        report.validate_replay(
            stale_pair[0],
            stale_pair[1],
            original_contract=stale_pair[2],
            replay_contract=stale_pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=stale_pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )

    drift_pair = _run_replay_pair(
        tmp_path / "drift",
        replay_backend_drift=True,
    )
    with pytest.raises(report.RobustnessValidationError, match="drift"):
        report.validate_replay(
            drift_pair[0],
            drift_pair[1],
            original_contract=drift_pair[2],
            replay_contract=drift_pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=drift_pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )

    proof_drift_pair = _run_replay_pair(
        tmp_path / "proof-drift",
        replay_proof_execution_drift=True,
    )
    assert validate_native_kernel_stage_receipt(
        proof_drift_pair[0].stages[-1]
    )
    assert validate_native_kernel_stage_receipt(
        proof_drift_pair[1].stages[-1]
    )
    with pytest.raises(
        report.RobustnessValidationError,
        match="proof execution drift",
    ):
        report.validate_replay(
            proof_drift_pair[0],
            proof_drift_pair[1],
            original_contract=proof_drift_pair[2],
            replay_contract=proof_drift_pair[3],
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=proof_drift_pair[4],
            expected_source_commit=SOURCE_COMMIT,
        )

    same_cache_contract = original_contract
    with pytest.raises(report.RobustnessValidationError, match="contract|fresh"):
        report.validate_replay(
            original,
            replayed,
            original_contract=original_contract,
            replay_contract=same_cache_contract,
            expected_environment_sha256=SHA_ENVIRONMENT,
            worktree_receipt=worktree,
            expected_source_commit=SOURCE_COMMIT,
        )


def test_complete_robustness_report_is_strict_canonical_and_immutable(
    tmp_path: Path,
) -> None:
    case_ids = tuple(kind.value for kind in report.FailureInjectionKind)

    def handler(request):
        kind = report.FailureInjectionKind(request.case_id)
        code = {
            report.FailureInjectionKind.MISSING_TOOL: FailureCode.CAPABILITY_UNAVAILABLE,
            report.FailureInjectionKind.MALFORMED_OUTPUT: (
                FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
            ),
            report.FailureInjectionKind.TIMEOUT: FailureCode.RESOURCE_LEASE_CANCELLATION,
            report.FailureInjectionKind.CANCELLATION: FailureCode.RESOURCE_LEASE_CANCELLATION,
            report.FailureInjectionKind.CACHE_CORRUPTION: FailureCode.CACHE_CONTAMINATION,
            report.FailureInjectionKind.BACKEND_DRIFT: FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
        }[kind]
        return StageOutput(
            status=(
                StageStatus.UNAVAILABLE
                if kind is report.FailureInjectionKind.MISSING_TOOL
                else StageStatus.FAILED
            ),
            failure_code=code,
            failure_detail=f"injected {kind.value}",
        )

    by_case: dict[str, CaseResultRecord] = {}
    for case_id in case_ids:
        run = runner.execute_ablation(
            _plan(f"report-matrix-{case_id}", _cases(case_id)),
            {StageName.COMPILER: StageAdapter(StageName.COMPILER, handler)},
            output_root=tmp_path / "matrix" / case_id,
            resume=False,
        )
        assert len(run.results) == 1
        expected_stop = (
            run.results[0].failure_code
            if case_id
            in {
                report.FailureInjectionKind.CACHE_CORRUPTION.value,
                report.FailureInjectionKind.BACKEND_DRIFT.value,
            }
            else None
        )
        assert run.stop_failure_code is expected_stop
        assert run.complete is (expected_stop is None)
        by_case[case_id] = run.results[0]
    failures = tuple(
        report.FailureIsolationRecord.classify(
            f"inject-{kind.value}",
            kind,
            by_case[kind.value],
            elapsed_seconds=0.01,
            limit_seconds=1,
            affected_case_ids=(kind.value,),
        )
        for kind in report.FailureInjectionKind
    )
    replay_pair = _run_replay_pair(tmp_path / "replay")
    replay = report.validate_replay(
        replay_pair[0],
        replay_pair[1],
        original_contract=replay_pair[2],
        replay_contract=replay_pair[3],
        expected_environment_sha256=SHA_ENVIRONMENT,
        worktree_receipt=replay_pair[4],
        expected_source_commit=SOURCE_COMMIT,
    )
    robustness = report.RobustnessReport.create(failures, (replay,))
    encoded = report.canonical_robustness_report_json(robustness)
    report_path = report.write_robustness_report(
        robustness,
        tmp_path / "report" / "robustness.json",
    )

    assert report.HSSLEV0702E85() == (
        "failure injection, bounded isolation, and pinned fresh-worktree receipt replay"
    )
    assert report.RobustnessReport.from_dict(json.loads(encoded)) == robustness
    assert report.load_robustness_report(report_path) == robustness
    assert len(robustness.digest) == 64
    assert robustness.stop_required
    with pytest.raises(FrozenInstanceError):
        robustness.evidence = "changed"  # type: ignore[misc]

    unknown = json.loads(encoded)
    unknown["unexpected"] = True
    with pytest.raises(report.RobustnessValidationError, match="fields changed"):
        report.RobustnessReport.from_dict(unknown)
    with pytest.raises(report.RobustnessValidationError, match="each preregistered"):
        report.RobustnessReport.create(failures[:-1], (replay,))
    with pytest.raises(report.RobustnessValidationError, match="overwrite"):
        report.write_robustness_report(robustness, report_path)

    report_path.write_text(encoded, encoding="utf-8")
    with pytest.raises(report.RobustnessValidationError, match="newline"):
        report.load_robustness_report(report_path)
