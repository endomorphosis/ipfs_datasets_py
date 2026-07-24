"""Integration evidence for the unchanged HSSL pilot/development matrix."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Mapping

import pytest

from benchmarks.logic_pipeline import ablation, capability_reprobe, runtime
from benchmarks.logic_pipeline import matrix_reassessment as reassessment
from benchmarks.logic_pipeline.adapters import StageOutput
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


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def frozen_reprobe() -> capability_reprobe.LiveCapabilityReprobe:
    return capability_reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )


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
        receipt = {
            "schema": runtime.KERNEL_RECEIPT_SCHEMA,
            "independent": True,
            "accepted": not invalid_control,
            "active_process_count": 0,
            "case_id": request.case_id,  # type: ignore[attr-defined]
            "variant_id": request.variant_id,  # type: ignore[attr-defined]
            "cache_mode": request.cache_mode.value,  # type: ignore[attr-defined]
        }
        digest = _canonical_sha256(receipt)
        return StageOutput(
            data={**receipt, "receipt_sha256": digest},
            effective_identity=dict(
                request.requested_identity  # type: ignore[attr-defined]
            ),
            kernel_accepted=not invalid_control,
            kernel_receipt_sha256=None if invalid_control else digest,
        )

    def runtime_handlers(self) -> RuntimeBackendHandlers:
        return RuntimeBackendHandlers(
            compiler=self.compiler,
            spacy=self.generic(StageName.SPACY),
            symai=self.generic(StageName.SYMAI),
            legacy_symai=self.legacy_symai,
            hammer=self.generic(StageName.HAMMER),
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
    frozen_reprobe: capability_reprobe.LiveCapabilityReprobe,
) -> None:
    output_root = tmp_path / "matrix"
    snapshot_path = tmp_path / "matrix-snapshot.json"
    handlers = _DeterministicHandlers()

    first = reassessment.execute_reassessment_matrix(
        frozen_reprobe,
        repository_root=ROOT,
        output_root=output_root,
        snapshot_path=snapshot_path,
        handlers=handlers.runtime_handlers(),
        resume=True,
    )
    first_call_count = len(handlers.calls)
    validated = reassessment.validate_reassessment_matrix(
        repository_root=ROOT,
        output_root=output_root,
        snapshot_path=snapshot_path,
    )
    # Simulate interruption after both split ledgers were durably written but
    # before the aggregate index/snapshot publication.
    (output_root.parent / "matrix-execution-v2.json").unlink()
    snapshot_path.unlink()
    replay = reassessment.execute_reassessment_matrix(
        frozen_reprobe,
        repository_root=ROOT,
        output_root=output_root,
        snapshot_path=snapshot_path,
        handlers=handlers.runtime_handlers(),
        resume=True,
    )

    assert dict(first) == dict(validated) == dict(replay)
    assert first_call_count > 0
    assert len(handlers.calls) == first_call_count
    assert snapshot_path.is_file()
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
    assert kernel_stages
    assert all(stage.kernel_receipt_sha256 for stage in kernel_stages)
    assert all(
        record.status is not OutcomeStatus.VERIFIED
        for record in records
        if record.variant_id == "S1"
    )


def test_validator_rejects_noncanonical_index_and_result_tamper(
    tmp_path: Path,
    frozen_reprobe: capability_reprobe.LiveCapabilityReprobe,
) -> None:
    output_root = tmp_path / "matrix"
    snapshot_path = tmp_path / "snapshot.json"
    reassessment.execute_reassessment_matrix(
        frozen_reprobe,
        repository_root=ROOT,
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
            output_root=output_root,
            snapshot_path=snapshot_path,
        )

    index_path.write_bytes(original_index)
    result_path = next(
        path
        for path in output_root.rglob("*.json")
        if _load(path).get("schema") == ablation.ABLATION_RESULT_SCHEMA
    )
    payload = _load(result_path)
    payload["case_result_sha256"] = "0" * 64
    result_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        reassessment.validate_reassessment_matrix(
            repository_root=ROOT,
            output_root=output_root,
            snapshot_path=snapshot_path,
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
    assert kwargs["splits"] == (Split.PILOT, Split.DEVELOPMENT)
    assert kwargs["cache_modes"] == (CacheMode.COLD, CacheMode.WARM)
    assert kwargs["output_root"] == output_root
    assert kwargs["snapshot_path"] == snapshot_path
    assert kwargs["resume"] is True
