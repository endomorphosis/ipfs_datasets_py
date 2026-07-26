"""Integration evidence for the unchanged HSSL pilot/development matrix."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Mapping

import pytest

from benchmarks.logic_pipeline import (
    ablation,
    cache_measurement,
    capabilities,
    capability_reprobe,
    runtime,
)
from benchmarks.logic_pipeline import matrix_reassessment as reassessment
from benchmarks.logic_pipeline.adapters import (
    SpacyAdapter,
    SpacyAdapterConfig,
    SpacyAdapterMode,
    StageAdapter,
    StageOutput,
    SymaiAdapter,
    SymaiAdapterConfig,
)
from benchmarks.logic_pipeline.cases import FROZEN_CORPUS_MANIFEST_SHA256
from benchmarks.logic_pipeline.cases import DEFAULT_CORPUS_PATH, DEFAULT_MANIFEST_PATH
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    CaseResultRecord,
    DEFAULT_PROTOCOL_SHA256,
    FailureCode,
    OutcomeStatus,
    Split,
    StageName,
    StageStatus,
    canonical_json,
)
from benchmarks.logic_pipeline.runtime import RuntimeBackendHandlers
from benchmarks.logic_pipeline.variants import (
    ALL_VARIANT_IDS,
    VARIANT_REGISTRY_SHA256,
)


ROOT = Path(__file__).resolve().parents[4]
RECEIPTS = ROOT / capability_reprobe.DEFAULT_RECEIPT_DIRECTORY
TERMINAL_OUTCOMES = frozenset(OutcomeStatus)
FRESH_TEST_RUN_ID = "post-repair-matrix-test"


def _structured_symai_response() -> str:
    return canonical_json(
        {
            "candidate_ir": {
                "kind": "fol",
                "propositions": ["DeterministicMatrixReceipt"],
            },
            "normalized_predicates": ["DeterministicMatrixReceipt"],
            "quantifiers": [],
            "entities": ["matrix receipt"],
            "ambiguity_flags": [],
            "confidence": 1.0,
            "validation_errors": [],
        }
    )


class _DeterministicSymaiEngine:
    def __init__(self, config: SymaiAdapterConfig) -> None:
        self.config = config

    def forward(self, _argument: object):
        return (
            [_structured_symai_response()],
            {
                "backend": "llm_router",
                "effective_provider_name": self.config.provider,
                "effective_model_name": self.config.model,
                "resolved_provider_name": (
                    self.config.expected_inner_provider
                ),
                "resolved_model_name": self.config.expected_inner_model,
                "service_endpoint": self.config.expected_inner_endpoint,
                "routing_backend": self.config.expected_inner_backend,
            },
        )


@pytest.fixture(autouse=True)
def _dependency_free_configured_symai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def configured_factory(_state_directory: Path):
        def factory(
            config: SymaiAdapterConfig,
            _namespace: str,
        ) -> _DeterministicSymaiEngine:
            return _DeterministicSymaiEngine(config)

        return factory

    monkeypatch.setattr(
        runtime,
        "_configured_symai_engine_factory",
        configured_factory,
    )


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fresh_test_reprobe(
    published: capability_reprobe.LiveCapabilityReprobe,
) -> capability_reprobe.LiveCapabilityReprobe:
    """Rebind immutable checked evidence for dependency-free execution tests."""

    receipts: dict[str, dict[str, object]] = {}
    for component, frozen_receipt in published.receipts.items():
        receipt = json.loads(canonical_json(dict(frozen_receipt)))
        receipt["run_id"] = FRESH_TEST_RUN_ID
        if component == "leanstral_service":
            for identity_field in (
                "requested_identity",
                "effective_identity",
            ):
                receipt[identity_field]["routing_backend"] = (
                    "existing_leanstral_service"
                )
        receipt.pop("receipt_sha256")
        receipt["receipt_sha256"] = _canonical_sha256(receipt)
        receipts[component] = receipt
    records = []
    for record in published.inventory.capabilities:
        identity = dict(record.identity)
        component = str(identity["live_receipt_component"])
        if component == "leanstral_service":
            identity["routing_backend"] = (
                "existing_leanstral_service"
            )
        identity["live_receipt_sha256"] = receipts[component]["receipt_sha256"]
        records.append(
            capabilities.CapabilityRecord(
                kind=record.kind,
                status=record.status,
                identity=identity,
                provenance=record.provenance,
                reason=record.reason,
            )
        )
    environment = dict(published.inventory.environment)
    environment["run_id"] = FRESH_TEST_RUN_ID
    inventory = capabilities.CapabilityInventory.create(
        FRESH_TEST_RUN_ID,
        records,
        environment=environment,
        source_commit=published.inventory.source_commit,
    )
    return capability_reprobe.LiveCapabilityReprobe(
        inventory,
        receipts,
        published.source_binding,
    )


@pytest.fixture(scope="module")
def frozen_reprobe() -> capability_reprobe.LiveCapabilityReprobe:
    return capability_reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )


@pytest.fixture(scope="module")
def fresh_reprobe(
    frozen_reprobe: capability_reprobe.LiveCapabilityReprobe,
) -> capability_reprobe.LiveCapabilityReprobe:
    return _fresh_test_reprobe(frozen_reprobe)


class _DeterministicHandlers:
    """Dependency-free handlers that still exercise every scheduled route."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def _remember(self, stage: StageName, request: object) -> None:
        self.calls.append(
            (
                stage.value,
                request.case_id,  # type: ignore[attr-defined]
                request.variant_id,  # type: ignore[attr-defined]
                request.cache_mode.value,  # type: ignore[attr-defined]
            )
        )

    def compiler(self, request: object) -> StageOutput:
        self._remember(StageName.COMPILER, request)
        return StageOutput(
            data={
                "stage": StageName.COMPILER.value,
                "ambiguity_detected": True,
            },
            effective_identity=dict(
                request.requested_identity  # type: ignore[attr-defined]
            ),
        )

    def generic(self, stage: StageName):
        def invoke(request: object) -> StageOutput:
            self._remember(stage, request)
            return StageOutput(
                data={
                    "stage": stage.value,
                    "proof_success": stage is StageName.HAMMER,
                    "proof_text": (
                        "exact deterministic proof candidate"
                        if stage is StageName.HAMMER
                        else None
                    ),
                },
                effective_identity=dict(
                    request.requested_identity  # type: ignore[attr-defined]
                ),
            )

        return invoke

    def leanstral(self, request: object) -> StageOutput:
        self._remember(StageName.LEANSTRAL, request)
        return StageOutput(
            status=StageStatus.UNAVAILABLE,
            effective_identity=dict(
                request.requested_identity  # type: ignore[attr-defined]
            ),
            failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
            failure_detail="deterministic typed unavailable outcome",
        )

    def legacy_symai(self, request: object) -> StageOutput:
        self._remember(StageName.SYMAI, request)
        return StageOutput(
            status=StageStatus.UNAVAILABLE,
            effective_identity=dict(
                request.requested_identity  # type: ignore[attr-defined]
            ),
            failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
            failure_detail="deterministic legacy capability unavailable",
        )

    def kernel(self, request: object) -> StageOutput:
        self._remember(StageName.KERNEL, request)
        invalid_control = (
            request.input_data.get("expected_class") == "unsupported"  # type: ignore[attr-defined]
        )
        # These are injected runtime handlers, so they may exercise canonical
        # rejections but must never mint positive native-kernel authority.
        # Positive dependency-free graph fixtures live in
        # test_ablation_dataflow and bypass the live-runtime trust boundary.
        accepted = False
        receipt: dict[str, object] = {
            "schema": runtime.KERNEL_RECEIPT_SCHEMA,
            "protocol_sha256": request.protocol_sha256,  # type: ignore[attr-defined]
            "run_id": request.run_id,  # type: ignore[attr-defined]
            "case_id": request.case_id,  # type: ignore[attr-defined]
            "case_manifest_sha256": request.case_manifest_sha256,  # type: ignore[attr-defined]
            "variant_id": request.variant_id,  # type: ignore[attr-defined]
            "split": request.split.value,  # type: ignore[attr-defined]
            "cache_mode": request.cache_mode.value,  # type: ignore[attr-defined]
            "input_sha256": request.input_sha256,  # type: ignore[attr-defined]
            "environment_sha256": request.environment_sha256,  # type: ignore[attr-defined]
            "independent": True,
            "accepted": accepted,
            "active_process_count": 0,
        }
        if accepted:
            candidate_sha256 = request.upstream_artifacts[0].digest  # type: ignore[attr-defined]
            attempt_body = {
                "attempt_index": 0,
                "candidate_source": StageName.COMPILER.value,
                "candidate_artifact_sha256": candidate_sha256,
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "command_sha256": hashlib.sha256(b"command").hexdigest(),
                "stdout_sha256": hashlib.sha256(b"accepted").hexdigest(),
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
                "attempt_sha256": _canonical_sha256(attempt_body),
            }
            receipt.update(
                {
                    "compiled_obligation_sha256": hashlib.sha256(
                        b"compiled"
                    ).hexdigest(),
                    "obligation_sha256": hashlib.sha256(
                        b"obligation"
                    ).hexdigest(),
                    "candidate_source": attempt["candidate_source"],
                    "candidate_artifact_sha256": candidate_sha256,
                    "source_sha256": attempt["source_sha256"],
                    "semantic_context_sha256": hashlib.sha256(
                        b"semantic-context"
                    ).hexdigest(),
                    "semantic_artifact_sha256s": [
                        artifact.digest
                        for artifact in request.upstream_artifacts  # type: ignore[attr-defined]
                    ],
                    "command_sha256": attempt["command_sha256"],
                    "stdout_sha256": attempt["stdout_sha256"],
                    "stderr_sha256": attempt["stderr_sha256"],
                    "returncode": attempt["returncode"],
                    "timed_out": attempt["timed_out"],
                    "cancelled": attempt["cancelled"],
                    "resource_exhausted": attempt["resource_exhausted"],
                    "termination_reason": attempt["termination_reason"],
                    "process_group_reaped": attempt[
                        "process_group_reaped"
                    ],
                    "candidate_attempts": [attempt],
                    "candidate_attempts_sha256": _canonical_sha256(
                        [attempt]
                    ),
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
                }
            )
        else:
            receipt["reason"] = (
                "invalid_control"
                if invalid_control
                else "injected_test_kernel_non_authoritative"
            )
        digest = _canonical_sha256(receipt)
        return StageOutput(
            data={**receipt, "receipt_sha256": digest},
            effective_identity=dict(
                request.requested_identity  # type: ignore[attr-defined]
            ),
            kernel_accepted=accepted,
            kernel_receipt_sha256=None,
        )

    def runtime_handlers(self) -> RuntimeBackendHandlers:
        return RuntimeBackendHandlers(
            compiler=self.compiler,
            spacy=self.generic(StageName.SPACY),
            # Leave the current SyMAI route configured so cold misses and
            # warm setup->hit receipts exercise the production wrapper.
            symai=None,
            legacy_symai=self.legacy_symai,
            hammer=self.generic(StageName.HAMMER),
            learned_hammer=self.generic(StageName.HAMMER),
            premise_ranked_hammer=self.generic(StageName.HAMMER),
            leanstral=self.leanstral,
            kernel=self.kernel,
        )


def _plans(
    frozen_reprobe: capability_reprobe.LiveCapabilityReprobe,
) -> tuple[ablation.AblationPlan, ...]:
    return reassessment.build_reassessment_plans(
        frozen_reprobe,
        splits=(Split.PILOT, Split.DEVELOPMENT),
        cache_modes=(CacheMode.COLD, CacheMode.WARM),
    )


def _case_result_envelopes(root: Path) -> tuple[dict[str, object], ...]:
    envelopes: list[dict[str, object]] = []
    for path in root.rglob("*.json"):
        value = _load(path)
        if value.get("schema") == ablation.ABLATION_RESULT_SCHEMA:
            envelopes.append(value)
    return tuple(envelopes)


def _cache_isolation_run(tmp_path: Path) -> ablation.AblationRunResult:
    case = ablation.AblationCase.create(
        "matrix-cache-case",
        {"text": "cache isolation"},
        split=Split.PILOT,
    )
    plan = ablation.build_ablation_plan(
        "matrix-cache-isolation",
        (case,),
        case_manifest_sha256="a" * 64,
        split=Split.PILOT,
        seed=71,
        variant_ids=("A12",),
        cache_modes=(CacheMode.COLD, CacheMode.WARM),
        environment_sha256="b" * 64,
        limits=ablation.ResourceLimits(
            max_workers=1,
            case_timeout_seconds=2,
            max_memory_bytes=64 * 1024 * 1024,
            max_model_calls_per_case=4,
            max_solver_processes_per_case=2,
        ),
    )
    adapters: dict[StageName, StageAdapter] = {}
    for stage in StageName:
        def handler(request: object, current: StageName = stage) -> StageOutput:
            mode = request.cache_mode.value  # type: ignore[attr-defined]
            identity = dict(
                request.requested_identity  # type: ignore[attr-defined]
            )
            identity.update(
                {
                    "provider": "pinned-provider",
                    "model": "pinned-model",
                    "solver": "pinned-solver",
                    "backend_revision": "pinned",
                    "cache_mode": mode,
                    "cache_namespace": (
                        f"matrix-cache-isolation/{current.value}/{mode}"
                    ),
                    "cache_key": (
                        f"matrix-cache-case/{current.value}/{mode}"
                    ),
                    "cache_hit": (
                        request.cache_mode is CacheMode.WARM  # type: ignore[attr-defined]
                    ),
                    "router_cache": mode,
                    "semantic_context_sha256": hashlib.sha256(
                        f"{current.value}:{mode}".encode("utf-8")
                    ).hexdigest(),
                }
            )
            if (
                current is StageName.SYMAI
                and request.cache_mode is CacheMode.WARM  # type: ignore[attr-defined]
            ):
                prime_receipt = {
                    "schema": "test-symai-cache-prime.v1",
                    "cache_mode": CacheMode.WARM.value,
                }
                identity.update(
                    {
                        "cache_prime": True,
                        "cache_prime_receipt": prime_receipt,
                        "cache_prime_receipt_sha256": _canonical_sha256(
                            prime_receipt
                        ),
                        "cache_prime_setup_attempts": 1,
                        "cache_prime_setup_model_calls": 1,
                        "cache_prime_setup_wall_time_ms": 0.25,
                    }
                )
            return StageOutput(
                data={
                    "stage": current.value,
                    "ambiguity_detected": True,
                    "proof_success": False,
                },
                effective_identity=identity,
            )

        adapters[stage] = StageAdapter(stage, handler)
    adapters[StageName.SPACY] = SpacyAdapter(
        config=SpacyAdapterConfig(
            mode=SpacyAdapterMode.REGEX_LEGAL
        )
    )
    adapters[StageName.SYMAI] = SymaiAdapter(
        config=SymaiAdapterConfig(
            provider="ipfs_accelerate_py",
            model="Leanstral-119B",
            max_retries=0,
            cache_enabled=True,
        ),
        engine_factory=lambda config, _namespace: (
            _DeterministicSymaiEngine(config)
        ),
        trace_getter=lambda: {},
        cache={},
    )
    return ablation.execute_ablation(
        plan,
        adapters,
        output_root=tmp_path,
        resume=False,
    )


def _replace_warm_result(
    run: ablation.AblationRunResult,
    replacement: CaseResultRecord,
) -> ablation.AblationRunResult:
    return replace(
        run,
        results=tuple(
            replacement
            if result.cache_mode is CacheMode.WARM
            else result
            for result in run.results
        ),
    )


def _warm_stage_identity_drift(
    run: ablation.AblationRunResult,
    *,
    identity: str,
) -> ablation.AblationRunResult:
    warm = next(
        result
        for result in run.results
        if result.cache_mode is CacheMode.WARM
    )
    symai = next(
        stage for stage in warm.stages if stage.stage is StageName.SYMAI
    )
    provenance = symai.provenance
    if identity == "requested":
        provenance = replace(
            provenance,
            requested_identity={
                **dict(provenance.requested_identity),
                "backend_identity": "warm-drift",
            },
        )
    else:
        provenance = replace(
            provenance,
            effective_identity={
                **dict(provenance.effective_identity),
                "backend_revision": "warm-drift",
            },
        )
    replacement_stage = replace(symai, provenance=provenance)
    replacement = CaseResultRecord.from_stages(
        tuple(
            replacement_stage if stage is symai else stage
            for stage in warm.stages
        )
    )
    return _replace_warm_result(run, replacement)


def test_matrix_cache_isolation_accepts_canonical_warm_symai_prime_receipt(
    tmp_path: Path,
) -> None:
    run = _cache_isolation_run(tmp_path)
    warm_symai = next(
        stage
        for result in run.results
        if result.cache_mode is CacheMode.WARM
        for stage in result.stages
        if stage.stage is StageName.SYMAI
    )

    receipt = cache_measurement.validate_symai_warm_cache_measurement(
        warm_symai
    )
    assert (
        warm_symai.provenance.effective_identity[
            "cache_prime_receipt_sha256"
        ]
        == receipt.receipt_sha256
    )
    reassessment._validate_split_cache_isolation(run)


def test_matrix_cache_isolation_rejects_route_drift(tmp_path: Path) -> None:
    run = _cache_isolation_run(tmp_path)
    warm = next(
        result
        for result in run.results
        if result.cache_mode is CacheMode.WARM
    )
    replacement = CaseResultRecord.from_stages(
        tuple(
            stage
            for stage in warm.stages
            if stage.stage is not StageName.SPACY
        )
    )

    with pytest.raises(
        reassessment.MatrixReassessmentError,
        match="cache isolation failed: cold and warm results executed "
        "different routes",
    ):
        reassessment._validate_split_cache_isolation(
            _replace_warm_result(run, replacement)
        )


def test_resource_ledger_rejects_a_receipt_for_forged_suppression(
    tmp_path: Path,
) -> None:
    run = _cache_isolation_run(tmp_path)
    first = run.results[0]
    symai = next(
        stage for stage in first.stages if stage.stage is StageName.SYMAI
    )
    forged_stage = replace(
        symai,
        provenance=replace(
            symai.provenance,
            effective_identity={
                **dict(symai.provenance.effective_identity),
                "graph_invoked": False,
                "policy_reason": "forged_suppression",
            },
        ),
    )
    forged_result = CaseResultRecord.from_stages(
        tuple(
            forged_stage if stage is symai else stage
            for stage in first.stages
        )
    )
    forged_run = replace(
        run,
        results=(forged_result, *run.results[1:]),
    )

    with pytest.raises(
        reassessment.MatrixReassessmentError,
        match="receipts differ from the invoked stage graph",
    ):
        reassessment._build_ledger(forged_run)


@pytest.mark.parametrize("identity", ("requested", "effective"))
def test_matrix_cache_isolation_rejects_backend_identity_drift(
    tmp_path: Path,
    identity: str,
) -> None:
    run = _cache_isolation_run(tmp_path)

    with pytest.raises(
        reassessment.MatrixReassessmentError,
        match="cache isolation failed: backend, model, or solver identity "
        "drifted across modes",
    ):
        reassessment._validate_split_cache_isolation(
            _warm_stage_identity_drift(run, identity=identity)
        )


def test_evidence_symbol_is_ast_visible_and_describes_exact_scope() -> None:
    source = Path(reassessment.__file__).read_text(encoding="utf-8")
    names = {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    evidence = reassessment.HSSLEV1305A27()

    assert "HSSLEV1305A27" in names
    assert callable(reassessment.HSSLEV1305A27)
    assert all(
        term in evidence.lower()
        for term in ("pilot", "development", "cold", "warm")
    )


def test_builder_freezes_exact_560_coordinate_non_holdout_matrix(
    frozen_reprobe: capability_reprobe.LiveCapabilityReprobe,
) -> None:
    plans = _plans(frozen_reprobe)

    assert tuple(plan.split for plan in plans) == (
        Split.PILOT,
        Split.DEVELOPMENT,
    )
    assert sum(len(plan.jobs) for plan in plans) == 560
    assert all(len(plan.case_ids) == 10 for plan in plans)
    assert all(plan.variant_ids == tuple(ALL_VARIANT_IDS) for plan in plans)
    assert all(
        plan.cache_modes == (CacheMode.COLD, CacheMode.WARM)
        for plan in plans
    )
    assert all(plan.split is not Split.HOLDOUT for plan in plans)
    assert all(
        plan.protocol_sha256 == DEFAULT_PROTOCOL_SHA256
        and plan.registry_sha256 == VARIANT_REGISTRY_SHA256
        and plan.case_manifest_sha256 == FROZEN_CORPUS_MANIFEST_SHA256
        and plan.environment_sha256 == frozen_reprobe.inventory.sha256
        for plan in plans
    )
    assert all(
        contract.requested_variant_id == contract.effective_variant_id
        and contract.prompts_frozen
        and contract.policy_frozen
        and contract.model_identities_frozen
        and contract.thresholds_frozen
        for plan in plans
        for contract in plan.run_contracts
    )
    assert all(
        job.case.split is not Split.HOLDOUT
        for plan in plans
        for job in plan.jobs
    )
    assert {
        (
            plan.split,
            job.case.case_id,
            job.variant_id,
            job.cache_mode,
        )
        for plan in plans
        for job in plan.jobs
    } == {
        (plan.split, case_id, variant_id, cache_mode)
        for plan in plans
        for case_id in plan.case_ids
        for variant_id in ALL_VARIANT_IDS
        for cache_mode in (CacheMode.COLD, CacheMode.WARM)
    }

    # Each cache state receives every arm at every position equally (or within
    # one when the ten blocks cannot divide evenly across fourteen positions).
    for plan in plans:
        position_counts = {
            mode: {
                variant_id: [0] * len(ALL_VARIANT_IDS)
                for variant_id in ALL_VARIANT_IDS
            }
            for mode in (CacheMode.COLD, CacheMode.WARM)
        }
        for block in plan.blocks:
            assert len(block) == len(ALL_VARIANT_IDS)
            assert len({job.input_sha256 for job in block}) == 1
            assert {job.variant_id for job in block} == set(ALL_VARIANT_IDS)
            for position, job in enumerate(block):
                position_counts[job.cache_mode][job.variant_id][position] += 1
        for counts_by_variant in position_counts.values():
            assert all(
                max(counts) - min(counts) <= 1
                for counts in counts_by_variant.values()
            )


def test_published_snapshot_retains_exact_legacy_date_and_path() -> None:
    index_path = ROOT / reassessment.DEFAULT_MATRIX_INDEX
    index = reassessment._read_canonical(index_path, "published matrix index")
    expected = reassessment._snapshot(
        index,
        index_path,
        repository=ROOT,
        benchmark_root=reassessment.DEFAULT_BENCHMARK_ROOT,
    )

    assert expected == _load(ROOT / reassessment.DEFAULT_MATRIX_SNAPSHOT)
    assert expected["captured_on"] == "2026-07-24"
    assert expected["results"]["artifact"]["path"] == (
        reassessment.DEFAULT_MATRIX_INDEX.as_posix()
    )


def test_matrix_passes_frozen_case_limit_to_leanstral_runtime(
    tmp_path: Path,
    fresh_reprobe: capability_reprobe.LiveCapabilityReprobe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class RuntimeCaptured(RuntimeError):
        pass

    def capture_runtime(
        _inventory: object,
        _handlers: object,
        **kwargs: object,
    ) -> object:
        captured.update(kwargs)
        raise RuntimeCaptured

    monkeypatch.setattr(
        reassessment,
        "build_live_runtime",
        capture_runtime,
    )
    with pytest.raises(RuntimeCaptured):
        reassessment.execute_reassessment_matrix(
            fresh_reprobe,
            repository_root=ROOT,
            output_root=tmp_path / "matrix",
            snapshot_path=tmp_path / "snapshot.json",
            handlers=_DeterministicHandlers().runtime_handlers(),
            resume=False,
        )

    assert captured["leanstral_timeout_seconds"] == (
        ablation.ResourceLimits().case_timeout_seconds
    )
    assert captured["leanstral_max_new_tokens"] == (
        runtime.LEANSTRAL_MEASURED_MAX_NEW_TOKENS
    )


def test_non_holdout_reader_never_deserializes_the_sealed_tail(
    tmp_path: Path,
) -> None:
    source_lines = (ROOT / DEFAULT_CORPUS_PATH).read_bytes().splitlines(
        keepends=True
    )
    assert len(source_lines) == 30
    poisoned = tmp_path / "sealed-corpus.jsonl"
    poisoned.write_bytes(b"".join(source_lines[:20]) + b"{not-json}\n" * 10)

    _manifest, cases = reassessment._sealed_non_holdout_cases(
        corpus_path=poisoned,
        manifest_path=ROOT / DEFAULT_MANIFEST_PATH,
    )

    assert len(cases) == 20
    assert {case.split for case in cases} == {Split.PILOT, Split.DEVELOPMENT}


def test_full_matrix_execution_is_terminal_receipted_and_resumable(
    tmp_path: Path,
    fresh_reprobe: capability_reprobe.LiveCapabilityReprobe,
) -> None:
    benchmark_root = (tmp_path / "external-benchmark-root").resolve()
    layout = reassessment.ReassessmentRunLayout.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    output_root = layout.matrix_root
    snapshot_path = layout.matrix_snapshot
    handlers = _DeterministicHandlers()

    first = reassessment.execute_reassessment_matrix(
        fresh_reprobe,
        repository_root=ROOT,
        benchmark_root=benchmark_root,
        output_root=output_root,
        snapshot_path=snapshot_path,
        handlers=handlers.runtime_handlers(),
        resume=True,
    )
    first_call_count = len(handlers.calls)
    validated = reassessment.validate_reassessment_matrix(
        repository_root=ROOT,
        run_id=FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
        output_root=output_root,
        snapshot_path=snapshot_path,
        frozen_reprobe=fresh_reprobe,
    )
    # Simulate interruption after both split ledgers were durably written but
    # before the aggregate index/snapshot publication.
    (output_root.parent / "matrix-execution-v2.json").unlink()
    snapshot_path.unlink()
    replay = reassessment.execute_reassessment_matrix(
        fresh_reprobe,
        repository_root=ROOT,
        benchmark_root=benchmark_root,
        output_root=output_root,
        snapshot_path=snapshot_path,
        handlers=handlers.runtime_handlers(),
        resume=True,
    )

    assert dict(first) == dict(validated) == dict(replay)
    assert first_call_count > 0
    assert len(handlers.calls) == first_call_count
    assert snapshot_path.is_file()
    snapshot = _load(snapshot_path)
    captured = date.fromisoformat(str(snapshot["captured_on"]))
    assert captured <= datetime.now(timezone.utc).date()
    assert snapshot["results"]["artifact"]["path"] == (
        "results/matrix-execution-v2.json"
    )
    assert first["artifact_sha256"]
    assert first["totals"]["invalid_control_coordinate_count"] == 56
    assert first["totals"]["invalid_control_verified_count"] == 0
    selection = first["selection_inputs"]
    assert selection["tuning_permitted"] is False
    assert selection["selection_inputs_changed"] is False
    assert selection["source"] == {
        "path": reassessment.FROZEN_SELECTION_PATH.as_posix(),
        "bytes_sha256": reassessment.FROZEN_SELECTION_BYTES_SHA256,
        "semantic_sha256": reassessment.FROZEN_SELECTION_SHA256S["freeze"],
    }
    assert selection["prompts_sha256"] == (
        reassessment.FROZEN_SELECTION_SHA256S["prompts"]
    )
    assert selection["policies_sha256"] == (
        reassessment.FROZEN_SELECTION_SHA256S["policies"]
    )
    assert selection["thresholds_sha256"] == (
        reassessment.FROZEN_SELECTION_SHA256S["thresholds"]
    )
    split_runs = first["split_runs"]
    assert isinstance(split_runs, list)
    for split_run in split_runs:
        assert isinstance(split_run, Mapping)
        ledger_ref = split_run["resource_ledger"]
        assert isinstance(ledger_ref, Mapping)
        ledger = _load(output_root.parent / str(ledger_ref["path"]))
        assert ledger["receipt_count"] == ledger["invoked_stage_count"]
        assert isinstance(ledger["receipts"], list)
        assert len(ledger["receipts"]) == ledger["receipt_count"]
        assert int(ledger["receipt_count"]) > 0

    envelopes = _case_result_envelopes(output_root)
    records = tuple(
        CaseResultRecord.from_dict(envelope["case_result"])
        for envelope in envelopes
    )
    assert len(records) == 560
    assert len(
        {
            (
                record.split,
                record.case_id,
                record.variant_id,
                record.cache_mode,
            )
            for record in records
        }
    ) == 560
    assert {record.split for record in records} == {
        Split.PILOT,
        Split.DEVELOPMENT,
    }
    assert all(record.status in TERMINAL_OUTCOMES for record in records)
    assert any(
        record.status is OutcomeStatus.UNAVAILABLE for record in records
    )
    assert all(record.validate_provenance() is None for record in records)
    assert all(
        all(
            stage.provenance.effective_identity.get(key) == value
            for key, value in stage.provenance.requested_identity.items()
        )
        for record in records
        for stage in record.stages
    )
    assert all(
        stage.telemetry.wall_time_ms >= 0
        and stage.telemetry.cpu_time_ms >= 0
        for record in records
        for stage in record.stages
    )
    kernel_stages = tuple(
        stage
        for record in records
        for stage in record.stages
        if stage.stage is StageName.KERNEL and stage.kernel_accepted
    )
    assert kernel_stages == ()
    assert all(
        record.status is not OutcomeStatus.VERIFIED
        for record in records
        if record.variant_id == "S1"
    )


def test_validator_rejects_noncanonical_index_and_result_tamper(
    tmp_path: Path,
    fresh_reprobe: capability_reprobe.LiveCapabilityReprobe,
) -> None:
    benchmark_root = (tmp_path / "external-benchmark-root").resolve()
    layout = reassessment.ReassessmentRunLayout.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    output_root = layout.matrix_root
    snapshot_path = layout.matrix_snapshot
    reassessment.execute_reassessment_matrix(
        fresh_reprobe,
        repository_root=ROOT,
        benchmark_root=benchmark_root,
        output_root=output_root,
        snapshot_path=snapshot_path,
        handlers=_DeterministicHandlers().runtime_handlers(),
        resume=True,
    )

    index_path = output_root.parent / "matrix-execution-v2.json"
    assert index_path.is_file()
    original_index = index_path.read_bytes()
    index_path.write_text(
        json.dumps(_load(index_path), indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="canonical"):
        reassessment.validate_reassessment_matrix(
            repository_root=ROOT,
            run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
            output_root=output_root,
            snapshot_path=snapshot_path,
            frozen_reprobe=fresh_reprobe,
        )

    index_path.write_bytes(original_index)
    original_snapshot = snapshot_path.read_bytes()
    snapshot = _load(snapshot_path)
    snapshot["results"]["artifact"]["path"] = "../matrix-execution-v2.json"
    snapshot_path.write_text(canonical_json(snapshot) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="public matrix snapshot changed"):
        reassessment.validate_reassessment_matrix(
            repository_root=ROOT,
            run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
            output_root=output_root,
            snapshot_path=snapshot_path,
            frozen_reprobe=fresh_reprobe,
        )

    snapshot_path.write_bytes(original_snapshot)
    snapshot = _load(snapshot_path)
    snapshot["captured_on"] = "2999-01-01"
    snapshot_path.write_text(canonical_json(snapshot) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="capture date is invalid"):
        reassessment.validate_reassessment_matrix(
            repository_root=ROOT,
            run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
            output_root=output_root,
            snapshot_path=snapshot_path,
            frozen_reprobe=fresh_reprobe,
        )

    snapshot_path.write_bytes(original_snapshot)
    result_path = next(
        path
        for path in output_root.rglob("*.json")
        if _load(path).get("schema") == ablation.ABLATION_RESULT_SCHEMA
    )
    original_result = result_path.read_bytes()
    payload = _load(result_path)
    payload["schema"] = ablation.LEGACY_ABLATION_RESULT_SCHEMA
    result_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    with pytest.raises(
        ValueError,
        match="current validation requires an ablation-result.v2 envelope",
    ):
        reassessment.validate_reassessment_matrix(
            repository_root=ROOT,
            run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
            output_root=output_root,
            snapshot_path=snapshot_path,
            frozen_reprobe=fresh_reprobe,
        )

    result_path.write_bytes(original_result)
    payload = _load(result_path)
    payload["case_result_sha256"] = "0" * 64
    result_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        reassessment.validate_reassessment_matrix(
            repository_root=ROOT,
            run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
            output_root=output_root,
            snapshot_path=snapshot_path,
            frozen_reprobe=fresh_reprobe,
        )


def test_execute_cli_forwards_complete_scope_and_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_execute(*args: object, **kwargs: object) -> Mapping[str, object]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {
            "schema": "test-matrix-index.v1",
            "status": "complete",
            "coordinate_count": 560,
            "artifact_sha256": "a" * 64,
        }

    monkeypatch.setattr(
        reassessment, "execute_reassessment_matrix", fake_execute
    )
    output_root = tmp_path / "matrix"
    snapshot_path = tmp_path / "snapshot.json"
    exit_code = runtime.main(
        [
            "execute",
            "--run-id",
            "post-repair-cli-test",
            "--splits",
            "pilot,development",
            "--cache-mode",
            "both",
            "--validate-complete",
            "--output-root",
            str(output_root),
            "--snapshot",
            str(snapshot_path),
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["coordinate_count"] == 560
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["run_id"] == "post-repair-cli-test"
    assert kwargs["splits"] == (Split.PILOT, Split.DEVELOPMENT)
    assert kwargs["cache_modes"] == (CacheMode.COLD, CacheMode.WARM)
    assert kwargs["output_root"] == output_root
    assert kwargs["snapshot_path"] == snapshot_path
    assert kwargs["resume"] is True
