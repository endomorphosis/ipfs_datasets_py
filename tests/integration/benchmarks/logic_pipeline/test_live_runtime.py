"""Integration evidence for capability-bound live runtime assembly."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.logic_pipeline import adapters, capabilities, contracts, runtime


def _inventory(
    *,
    unavailable: frozenset[capabilities.CapabilityKind] = frozenset(),
) -> capabilities.CapabilityInventory:
    records = []
    for kind in capabilities.CapabilityKind:
        status = (
            capabilities.CapabilityStatus.UNAVAILABLE
            if kind in unavailable
            else capabilities.CapabilityStatus.AVAILABLE
        )
        identity: dict[str, object] = {"implementation": f"test-{kind.value}"}
        if kind is capabilities.CapabilityKind.SPACY_PIPELINE:
            identity["requested_model"] = "en_core_web_sm"
        if kind in {
            capabilities.CapabilityKind.SYMAI,
            capabilities.CapabilityKind.LLM_ROUTER,
        }:
            identity.update(
                requested_provider="test-provider",
                requested_model="test-model",
            )
        if kind is capabilities.CapabilityKind.LEAN_TOOLCHAIN:
            identity.update(
                lean={"path": "/test/lean", "version": "test"},
                lake={"path": "/test/lake", "version": "test"},
            )
        records.append(
            capabilities.CapabilityRecord(
                kind,
                status,
                identity,
                ("integration-test",),
                None if status is capabilities.CapabilityStatus.AVAILABLE else "absent",
            )
        )
    return capabilities.CapabilityInventory.create(
        "live-runtime-test",
        records,
        environment={"suite": "test"},
    )


def _handler(stage: contracts.StageName):
    def invoke(request: adapters.StageRequest) -> adapters.StageOutput:
        return adapters.StageOutput(
            data={"stage": stage.value},
            effective_identity={
                **dict(request.requested_identity),
                "backend": f"real-{stage.value}",
            },
        )

    return invoke


def _handlers(**overrides: object) -> runtime.RuntimeBackendHandlers:
    values = {
        "compiler": _handler(contracts.StageName.COMPILER),
        "spacy": _handler(contracts.StageName.SPACY),
        "symai": _handler(contracts.StageName.SYMAI),
        "legacy_symai": _handler(contracts.StageName.SYMAI),
        "hammer": _handler(contracts.StageName.HAMMER),
        "leanstral": _handler(contracts.StageName.LEANSTRAL),
        "kernel": _handler(contracts.StageName.KERNEL),
    }
    values.update(overrides)
    return runtime.RuntimeBackendHandlers(**values)


def test_ast_evidence_and_every_requested_live_stage_is_callable() -> None:
    live = runtime.build_live_runtime(_inventory(), _handlers())

    assert runtime.HSSLEV1142E95() == (
        "every frozen arm executes its real capability-bound bounded stage graph"
    )
    assert set(live.adapters) == {*(f"A{i}" for i in range(13)), "S1"}
    for variant, route in live.adapters.items():
        assert set(route) == set(
            __import__(
                "benchmarks.logic_pipeline.variants", fromlist=["x"]
            ).get_variant_definition(variant).stages
        )
        assert all(adapter.handler is not None for adapter in route.values())


def test_available_backend_cannot_remain_inert_and_unavailable_is_not_substituted() -> None:
    missing_hammer = _handlers(hammer=None)
    with pytest.raises(runtime.RuntimeBindingError, match="no live hammer handler"):
        runtime.build_live_runtime(
            _inventory(), missing_hammer, variant_ids=("A2",)
        )

    unavailable = runtime.build_live_runtime(
        _inventory(
            unavailable=frozenset({capabilities.CapabilityKind.HAMMER})
        ),
        missing_hammer,
        variant_ids=("A2",),
    )
    adapter = unavailable.adapters["A2"][contracts.StageName.HAMMER]
    assert adapter.handler is None
    request = adapters.StageRequest(
        run_id="live-runtime-test",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A2",
        input_data={"text": "A policy applies."},
    )
    record = adapter.run(request)
    assert record.status is contracts.StageStatus.UNAVAILABLE
    assert record.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE

    dishonest = runtime.build_live_runtime(
        _inventory(),
        _handlers(
            kernel=lambda _request: adapters.StageOutput(
                data={"accepted": True},
                kernel_accepted=True,
                kernel_receipt_sha256="d" * 64,
            )
        ),
        variant_ids=("A1",),
    )
    dishonest_record = dishonest.adapters["A1"][
        contracts.StageName.KERNEL
    ].run(
        adapters.StageRequest(
            run_id="live-runtime-test",
            case_id="case-1",
            case_manifest_sha256="a" * 64,
            variant_id="A1",
            input_data={"text": "A policy applies."},
        )
    )
    assert dishonest_record.status is contracts.StageStatus.FAILED
    assert not dishonest_record.kernel_accepted
    assert (
        dishonest_record.failure_code
        is contracts.FailureCode.SAFETY_CONTROL_FAILURE
    )


def test_current_compiler_projects_oversized_derived_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real codec boundary must fit a durable stage artifact."""

    full_modal_ir = {
        "document_id": "case-1",
        "normalized_text": "A policy applies.",
        "formulas": [{"operator": "must", "predicate": "applies"}],
        "source": "logic_pipeline_benchmark",
        "version": "1",
        # Production graph/ontology exports can be much larger than the
        # benchmark's 64 KiB artifact boundary.
        "metadata": {"ontology_export": "x" * (160 * 1024)},
    }
    monkeypatch.setattr(
        runtime,
        "_encode_current_modal",
        lambda _text, _document_id: (full_modal_ir, "spacy"),
    )
    request = adapters.StageRequest(
        run_id="live-runtime-test",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A0",
        input_data={"text": "A policy applies."},
    )

    record = adapters.CompilerAdapter(
        runtime._current_compiler_handler
    ).run(request)

    assert record.status is contracts.StageStatus.SUCCESS
    durable_data = record.to_dict()["data"]
    assert durable_data["modal_ir"] == {
        key: full_modal_ir[key]
        for key in (
            "document_id",
            "formulas",
            "normalized_text",
            "source",
            "version",
        )
    }
    assert durable_data["modal_ir_sha256"] == hashlib.sha256(
        contracts.canonical_json(full_modal_ir).encode("utf-8")
    ).hexdigest()
    assert durable_data["modal_ir_canonical_bytes"] > 64 * 1024
    assert len(contracts.canonical_json(durable_data).encode("utf-8")) < 64 * 1024


def test_reviewed_obligation_compilation_is_deterministic_and_target_bound() -> None:
    value = {
        "obligation_id": "pilot-p01-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "trained",
        },
    }
    first = runtime.compile_reviewed_obligation(value)
    second = runtime.compile_reviewed_obligation(value)

    assert first is not None and second is not None
    assert first == second
    assert first.digest == second.digest
    assert first.semantic_target == "trained"
    assert first.obligation_sha256 == hashlib.sha256(
        contracts.canonical_json(value["proof_obligation"]).encode()
    ).hexdigest()
    assert first.obligation_sha256[:16] in first.source_template
    assert "{{PROOF}}" in first.source_template
    assert runtime.CompiledObligation.from_dict(first.to_dict()) == first

    mutated = runtime.compile_reviewed_obligation(
        {
            **value,
            "proof_obligation": {
                **value["proof_obligation"],
                "target": "changed",
            },
        }
    )
    assert mutated is not None and mutated.digest != first.digest
    injected = runtime.compile_reviewed_obligation(
        {
            **value,
            "proof_obligation": {
                **value["proof_obligation"],
                "target": "trained -/ theorem injected : False := by",
            },
        }
    )
    assert injected is not None
    assert injected.semantic_target.endswith("False := by")
    assert "theorem injected" not in injected.source_template
    with pytest.raises(runtime.RuntimeBindingError, match="unsupported"):
        runtime.compile_reviewed_obligation(
            {
                **value,
                "proof_obligation": {
                    "kind": "theorem",
                    "logic": "invented",
                    "target": "trained",
                },
            }
        )

class _FakeSupervisor:
    def __init__(self, root: Path, *, returncode: int = 0) -> None:
        self.root = root
        self.returncode = returncode
        self.active_process_count = 0
        self.closed = False

    @contextmanager
    def temporary_directory(self, **_kwargs: object):
        directory = self.root / "kernel"
        directory.mkdir()
        yield str(directory)

    def run(self, command: object, **_kwargs: object) -> object:
        source = Path(self.root / "kernel" / "Main.lean").read_text()
        assert "by\n  exact proof_token" in source
        return SimpleNamespace(
            returncode=self.returncode,
            stdout="accepted" if self.returncode == 0 else "",
            stderr="" if self.returncode == 0 else "rejected",
            timed_out=False,
            cancelled=False,
            resource_exhausted=False,
            error=None,
            termination_reason="completed",
            wall_time_seconds=0.01,
        )

    def close(self) -> None:
        self.closed = True


def test_independent_kernel_receipt_binds_candidate_and_reaps_owner(
    tmp_path: Path,
) -> None:
    compiled = runtime.compile_reviewed_obligation(
        {
            "obligation_id": "obl-1",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "target",
            },
        }
    )
    assert compiled is not None
    compiler = adapters.StageArtifact(
        contracts.StageName.COMPILER,
        contracts.StageStatus.SUCCESS,
        {"compiled_obligation": compiled.to_dict()},
        None,
        {"backend": "compiler"},
        0,
    )
    leanstral = adapters.StageArtifact(
        contracts.StageName.LEANSTRAL,
        contracts.StageStatus.SUCCESS,
        {"draft": {"proof_text": "exact proof_token"}},
        None,
        {"backend": "leanstral"},
        1,
    )
    runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        tmp_path / "state",
    )
    fake = _FakeSupervisor(tmp_path)
    runner._supervisor = fake
    request = adapters.StageRequest(
        run_id="runtime-kernel",
        case_id="case-1",
        case_manifest_sha256="a" * 64,
        variant_id="A9",
        input_data={"text": "target"},
        requested_identity={"kernel": "lean"},
        environment_sha256="b" * 64,
        upstream_artifacts=(compiler, leanstral),
        invocation_index=2,
    )

    output = runner(request)

    assert output.status is contracts.StageStatus.SUCCESS
    assert output.kernel_accepted
    assert output.kernel_receipt_sha256 == output.data["receipt_sha256"]
    assert output.data["independent"] is True
    assert output.data["candidate_artifact_sha256"] == leanstral.digest
    assert output.data["active_process_count"] == 0
    runner.close()
    assert fake.closed

    rejected_root = tmp_path / "rejected"
    rejected_root.mkdir()
    rejected_runner = runtime.NativeKernelRunner(
        "/test/lean",
        "b" * 64,
        rejected_root / "state",
    )
    rejected_runner._supervisor = _FakeSupervisor(
        rejected_root, returncode=1
    )
    rejected = rejected_runner(request)
    assert rejected.status is contracts.StageStatus.FAILED
    assert not rejected.kernel_accepted
    assert rejected.failure_code is contracts.FailureCode.KERNEL_REJECTION
    assert rejected.data["accepted"] is False
    rejected_runner.close()
