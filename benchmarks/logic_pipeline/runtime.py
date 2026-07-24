"""Capability-bound live execution for the frozen logic-pipeline benchmark.

Importing this module is side-effect free.  Backends are imported or processes
are launched only after a caller builds a live runtime and executes a stage.
The runtime never changes production routing and never substitutes a different
benchmark arm when a requested capability is absent.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence

from .adapters import (
    CompilerAdapter,
    HammerAdapter,
    KernelAdapter,
    LeanstralAdapter,
    SpacyAdapter,
    SpacyAdapterConfig,
    SpacyAdapterMode,
    StageAdapter,
    StageArtifact,
    StageHandler,
    StageOutput,
    StageRequest,
    SymaiAdapter,
    SymaiAdapterConfig,
)
from .capabilities import (
    CapabilityInventory,
    CapabilityKind,
    CapabilityRecord,
    CapabilityStatus,
    probe_runtime_capabilities,
)
from .contracts import (
    FailureCode,
    ProtocolContractError,
    ResourceLane,
    StageName,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from .variants import (
    ALL_VARIANT_IDS,
    SpacyMode,
    StagePolicy,
    get_variant_definition,
)


RUNTIME_VERSION: Final = "1"
COMPILED_OBLIGATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.compiled-obligation.v1"
)
KERNEL_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.native-kernel-receipt.v1"
)
MAX_NATIVE_SOURCE_BYTES: Final = 64 * 1024
_SAFE_THEOREM = re.compile(r"[^A-Za-z0-9_]")
_FORBIDDEN_PROOF = re.compile(
    r"(?i)(?<![A-Za-z0-9_'])(?:sorry|admit|sorryAx|axiom|unsafe)(?![A-Za-z0-9_'])"
)


class RuntimeBindingError(ProtocolContractError):
    """Raised before measurement when a live stage cannot be bound exactly."""


def HSSLEV1142E95() -> str:
    """Return the AST-verifiable real bounded stage-graph evidence receipt."""

    return "every frozen arm executes its real capability-bound bounded stage graph"


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _safe_theorem_name(obligation_id: str) -> str:
    normalized = _SAFE_THEOREM.sub("_", obligation_id)
    if not normalized or not normalized[0].isalpha():
        normalized = f"obligation_{normalized}"
    return f"hssl_{normalized}"[:128]


@dataclass(frozen=True, slots=True)
class CompiledObligation:
    """Deterministic native-kernel input derived from one reviewed obligation."""

    schema: str
    compiler_version: str
    obligation_id: str
    kind: str
    logic: str
    semantic_target: str
    obligation_sha256: str
    theorem_name: str
    source_template: str
    source_template_sha256: str

    def __post_init__(self) -> None:
        if self.schema != COMPILED_OBLIGATION_SCHEMA:
            raise RuntimeBindingError("unsupported compiled-obligation schema")
        if self.compiler_version != RUNTIME_VERSION:
            raise RuntimeBindingError("compiled-obligation version drifted")
        for name in (
            "obligation_id",
            "kind",
            "logic",
            "semantic_target",
            "theorem_name",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise RuntimeBindingError(f"{name} must be bounded and nonempty")
        if self.source_template.count("{{PROOF}}") != 1:
            raise RuntimeBindingError(
                "compiled obligation must retain one proof insertion point"
            )
        if len(self.source_template.encode("utf-8")) > MAX_NATIVE_SOURCE_BYTES:
            raise RuntimeBindingError("compiled obligation exceeds source bound")
        if self.source_template_sha256 != hashlib.sha256(
            self.source_template.encode("utf-8")
        ).hexdigest():
            raise RuntimeBindingError("compiled obligation source digest changed")
        if not re.fullmatch(r"[0-9a-f]{64}", self.obligation_sha256):
            raise RuntimeBindingError("obligation_sha256 is invalid")

    @property
    def digest(self) -> str:
        return _sha(self.to_dict())

    def render(self, proof_text: str) -> str:
        if (
            not isinstance(proof_text, str)
            or not proof_text.strip()
            or len(proof_text.encode("utf-8")) > MAX_NATIVE_SOURCE_BYTES // 2
        ):
            raise RuntimeBindingError("kernel proof candidate is empty or unbounded")
        if _FORBIDDEN_PROOF.search(proof_text):
            raise RuntimeBindingError(
                "kernel proof candidate contains a forbidden construct"
            )
        source = self.source_template.replace("{{PROOF}}", proof_text.strip())
        if len(source.encode("utf-8")) > MAX_NATIVE_SOURCE_BYTES:
            raise RuntimeBindingError("rendered native source exceeds byte bound")
        return source

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "compiler_version": self.compiler_version,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "logic": self.logic,
            "semantic_target": self.semantic_target,
            "obligation_sha256": self.obligation_sha256,
            "theorem_name": self.theorem_name,
            "source_template": self.source_template,
            "source_template_sha256": self.source_template_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CompiledObligation":
        if not isinstance(value, Mapping):
            raise RuntimeBindingError("compiled obligation must be an object")
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise RuntimeBindingError("compiled obligation fields changed")
        return cls(**dict(value))  # type: ignore[arg-type]


def compile_reviewed_obligation(
    input_data: Mapping[str, object],
) -> CompiledObligation | None:
    """Compile the frozen abstract target without using outcome labels.

    The generated Lean declaration keeps the reviewed target opaque.  It is a
    runnable syntax/kernel input once a proof candidate is inserted, but this
    compilation does not assert that the target is true.
    """

    if not isinstance(input_data, Mapping):
        raise RuntimeBindingError("benchmark input must be an object")
    raw = input_data.get("proof_obligation")
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"kind", "logic", "target"}:
        raise RuntimeBindingError(
            "proof_obligation must contain exactly kind, logic, and target"
        )
    values = {key: raw[key] for key in ("kind", "logic", "target")}
    if not all(isinstance(value, str) and value.strip() for value in values.values()):
        raise RuntimeBindingError("proof_obligation values must be nonempty strings")
    kind = str(values["kind"])
    logic = str(values["logic"])
    target = str(values["target"])
    if kind not in {"theorem", "countermodel"}:
        raise RuntimeBindingError(f"unsupported proof obligation kind: {kind}")
    if logic not in {"fol", "deontic", "temporal"}:
        raise RuntimeBindingError(f"unsupported proof obligation logic: {logic}")
    raw_id = input_data.get("obligation_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise RuntimeBindingError("reviewed proof obligation requires obligation_id")
    theorem_name = _safe_theorem_name(raw_id)
    obligation_sha256 = _sha(dict(raw))
    # The opaque proposition is intentionally named by the reviewed target
    # digest.  No expected class or fixture answer is compiled into the goal.
    target_name = f"Target_{obligation_sha256[:16]}"
    source_template = (
        f"/- HSSL reviewed target sha256:{obligation_sha256}; "
        f"kind:{kind}; logic:{logic} -/\n"
        "namespace HSSLBenchmark\n"
        f"opaque {target_name} : Prop\n"
        f"theorem {theorem_name} : {target_name} := by\n"
        "  {{PROOF}}\n"
        "end HSSLBenchmark\n"
    )
    return CompiledObligation(
        schema=COMPILED_OBLIGATION_SCHEMA,
        compiler_version=RUNTIME_VERSION,
        obligation_id=raw_id,
        kind=kind,
        logic=logic,
        semantic_target=target,
        obligation_sha256=obligation_sha256,
        theorem_name=theorem_name,
        source_template=source_template,
        source_template_sha256=hashlib.sha256(
            source_template.encode("utf-8")
        ).hexdigest(),
    )


def _serialize(value: object) -> object:
    serializer = getattr(value, "to_dict", None)
    if callable(serializer):
        return serializer()
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _current_compiler_handler(request: StageRequest) -> StageOutput:
    """Invoke the repository's current deterministic modal codec lazily."""

    if not isinstance(request.input_data, Mapping):
        raise RuntimeBindingError("compiler input must be an object")
    text = request.input_data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeBindingError("compiler input requires source text")
    from ipfs_datasets_py.logic.modal.codec import (
        DeterministicModalLogicCodec,
        ModalLogicCodecConfig,
    )

    codec = DeterministicModalLogicCodec(ModalLogicCodecConfig())
    encoded = codec.encode(
        text,
        document_id=request.case_id,
        source="logic_pipeline_benchmark",
    )
    modal_ir = _serialize(getattr(encoded, "modal_ir", {}))
    compiled = compile_reviewed_obligation(request.input_data)
    payload: dict[str, object] = {
        "schema": "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1",
        "modal_ir": modal_ir,
        "modal_ir_sha256": _sha(modal_ir),
        "parser_name": str(getattr(encoded, "parser_name", "")),
        "compiled_obligation": None if compiled is None else compiled.to_dict(),
        "compiled_obligation_sha256": None if compiled is None else compiled.digest,
    }
    return StageOutput(
        data=payload,
        effective_identity={
            **dict(request.requested_identity),
            "entrypoint": (
                "ipfs_datasets_py.logic.modal.codec."
                "DeterministicModalLogicCodec.encode"
            ),
        },
    )


@dataclass(frozen=True, slots=True)
class RuntimeBackendHandlers:
    """Explicit live backend overrides used by tests and managed deployments."""

    compiler: StageHandler | None = None
    spacy: StageHandler | None = None
    symai: StageHandler | None = None
    legacy_symai: StageHandler | None = None
    hammer: StageHandler | None = None
    leanstral: StageHandler | None = None
    kernel: StageHandler | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise RuntimeBindingError(f"{name} backend handler is not callable")


def _record(
    inventory: CapabilityInventory, kind: CapabilityKind
) -> CapabilityRecord:
    return inventory.by_kind[kind]


def _available(
    inventory: CapabilityInventory, *kinds: CapabilityKind
) -> bool:
    return all(
        _record(inventory, kind).status is CapabilityStatus.AVAILABLE
        for kind in kinds
    )


def _unavailable_adapter(stage: StageName) -> StageAdapter:
    return StageAdapter(stage)


def _spacy_mode(mode: SpacyMode) -> SpacyAdapterMode:
    return {
        SpacyMode.FULL_MODEL: SpacyAdapterMode.FULL_MODEL,
        SpacyMode.REGEX_LEGAL: SpacyAdapterMode.REGEX_LEGAL,
        SpacyMode.BLANK_MODEL: SpacyAdapterMode.BLANK_MODEL,
        SpacyMode.CURRENT_EFFECTIVE: SpacyAdapterMode.FULL_MODEL,
    }[mode]


def _validated_kernel_handler(handler: StageHandler) -> StageHandler:
    """Prevent an injected kernel adapter from fabricating proof authority."""

    def invoke(request: StageRequest) -> StageOutput:
        raw = handler(request)
        output = raw if isinstance(raw, StageOutput) else StageOutput(data=raw)
        if not output.kernel_accepted:
            return output
        data = output.data
        receipt_sha256 = output.kernel_receipt_sha256
        valid = (
            isinstance(data, Mapping)
            and data.get("schema") == KERNEL_RECEIPT_SCHEMA
            and data.get("independent") is True
            and data.get("accepted") is True
            and data.get("active_process_count") == 0
            and isinstance(receipt_sha256, str)
            and data.get("receipt_sha256") == receipt_sha256
        )
        if valid:
            receipt = {
                key: value
                for key, value in data.items()
                if key != "receipt_sha256"
            }
            valid = _sha(receipt) == receipt_sha256
        if valid:
            return output
        return StageOutput(
            status=StageStatus.FAILED,
            data={
                "schema": KERNEL_RECEIPT_SCHEMA,
                "accepted": False,
                "reason": "invalid_independent_kernel_receipt",
                "independent": True,
            },
            effective_identity=output.effective_identity,
            failure_code=FailureCode.SAFETY_CONTROL_FAILURE,
            failure_detail=(
                "kernel authority requires an independently verifiable receipt"
            ),
            telemetry=output.telemetry,
        )

    return invoke


@dataclass(slots=True)
class NativeKernelRunner:
    """Independent Lean kernel handler with owned process-group lifecycle."""

    lean_path: str
    environment_sha256: str
    state_directory: Path
    timeout_seconds: float = 30.0
    memory_mb: int = 1024
    _supervisor: object | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.lean_path, str) or not self.lean_path:
            raise RuntimeBindingError("native kernel requires a Lean executable")
        if not re.fullmatch(r"[0-9a-f]{64}", self.environment_sha256):
            raise RuntimeBindingError("kernel environment digest is invalid")
        self.state_directory = Path(self.state_directory)
        if not 0 < float(self.timeout_seconds) <= 86_400:
            raise RuntimeBindingError("kernel timeout is invalid")
        if not 1 <= self.memory_mb <= 1_048_576:
            raise RuntimeBindingError("kernel memory bound is invalid")

    @property
    def supervisor(self) -> object:
        if self._supervisor is None:
            from ipfs_datasets_py.logic.hammers.process_lifecycle import (
                ProcessSupervisor,
            )

            self._supervisor = ProcessSupervisor(
                state_directory=self.state_directory
            )
        return self._supervisor

    @property
    def active_process_count(self) -> int:
        return int(getattr(self._supervisor, "active_process_count", 0))

    def close(self) -> None:
        if self._supervisor is not None:
            self._supervisor.close()

    def __enter__(self) -> "NativeKernelRunner":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _compiled(request: StageRequest) -> CompiledObligation | None:
        compiler = request.artifact(StageName.COMPILER)
        if compiler is None or not isinstance(compiler.data, Mapping):
            return None
        value = compiler.data.get("compiled_obligation")
        return None if value is None else CompiledObligation.from_dict(value)

    @staticmethod
    def _proof_candidate(request: StageRequest) -> tuple[str, str] | None:
        for stage in (StageName.LEANSTRAL, StageName.HAMMER):
            artifact = request.artifact(stage)
            if (
                artifact is None
                or not artifact.invoked
                or artifact.status is not StageStatus.SUCCESS
                or not isinstance(artifact.data, Mapping)
            ):
                continue
            data = artifact.data
            if stage is StageName.LEANSTRAL:
                draft = data.get("draft")
                if isinstance(draft, Mapping):
                    proof = draft.get("proof_text", draft.get("draft_text"))
                    if isinstance(proof, str) and proof.strip():
                        return proof, artifact.digest
            else:
                candidate = data.get("proof_candidate", data.get("candidate"))
                if isinstance(candidate, Mapping):
                    proof = candidate.get("certificate")
                    if isinstance(proof, str) and proof.strip():
                        return proof, artifact.digest
            proof = data.get("proof_text")
            if isinstance(proof, str) and proof.strip():
                return proof, artifact.digest
        return None

    def __call__(self, request: StageRequest) -> StageOutput:
        compiled = self._compiled(request)
        candidate = self._proof_candidate(request)
        if compiled is None or candidate is None:
            return StageOutput(
                data={
                    "schema": KERNEL_RECEIPT_SCHEMA,
                    "accepted": False,
                    "reason": (
                        "no_compiled_obligation"
                        if compiled is None
                        else "no_proof_candidate"
                    ),
                    "independent": True,
                },
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                telemetry=TelemetryRecord(resource_lane=ResourceLane.KERNEL),
            )
        proof_text, candidate_sha256 = candidate
        try:
            source = compiled.render(proof_text)
        except RuntimeBindingError as exc:
            return StageOutput(
                status=StageStatus.FAILED,
                effective_identity=request.requested_identity,
                failure_code=FailureCode.KERNEL_REJECTION,
                failure_detail=str(exc)[:512],
                telemetry=TelemetryRecord(resource_lane=ResourceLane.KERNEL),
            )
        from ipfs_datasets_py.logic.hammers.process_lifecycle import (
            ProcessKind,
            ProcessLimits,
        )

        with self.supervisor.temporary_directory(
            prefix=f"hssl-{request.case_id}-"
        ) as temporary:
            source_path = Path(temporary) / "Main.lean"
            source_path.write_text(source, encoding="utf-8")
            result = self.supervisor.run(
                (self.lean_path, str(source_path)),
                kind=ProcessKind.LEAN,
                limits=ProcessLimits(
                    wall_time_seconds=self.timeout_seconds,
                    cpu_seconds=self.timeout_seconds,
                    memory_mb=self.memory_mb,
                ),
                cwd=temporary,
            )
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        stdout_sha256 = hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()
        stderr_sha256 = hashlib.sha256(result.stderr.encode("utf-8")).hexdigest()
        accepted = bool(
            result.returncode == 0
            and not result.timed_out
            and not result.cancelled
            and not result.resource_exhausted
            and result.error is None
            and self.active_process_count == 0
        )
        receipt = {
            "schema": KERNEL_RECEIPT_SCHEMA,
            "run_id": request.run_id,
            "case_id": request.case_id,
            "variant_id": request.variant_id,
            "protocol_sha256": request.protocol_sha256,
            "case_manifest_sha256": request.case_manifest_sha256,
            "input_sha256": request.input_sha256,
            "split": request.split.value,
            "cache_mode": request.cache_mode.value,
            "compiled_obligation_sha256": compiled.digest,
            "obligation_sha256": compiled.obligation_sha256,
            "candidate_artifact_sha256": candidate_sha256,
            "source_sha256": source_sha256,
            "environment_sha256": self.environment_sha256,
            "command_sha256": hashlib.sha256(
                f"{self.lean_path}\0Main.lean".encode("utf-8")
            ).hexdigest(),
            "stdout_sha256": stdout_sha256,
            "stderr_sha256": stderr_sha256,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "cancelled": result.cancelled,
            "resource_exhausted": result.resource_exhausted,
            "termination_reason": result.termination_reason,
            "active_process_count": self.active_process_count,
            "accepted": accepted,
            "independent": True,
        }
        receipt_sha256 = _sha(receipt)
        if (
            result.timed_out
            or result.cancelled
            or result.resource_exhausted
            or result.error is not None
            or self.active_process_count
        ):
            failure_code = FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
            failure_detail = "native kernel process failed"
            if self.active_process_count:
                failure_code = FailureCode.ORPHANED_CHILD
                failure_detail = "native kernel process was not reaped"
            elif result.resource_exhausted:
                failure_code = FailureCode.OUT_OF_MEMORY
                failure_detail = "native kernel resource bound was exhausted"
            elif result.timed_out or result.cancelled:
                failure_code = FailureCode.RESOURCE_LEASE_CANCELLATION
                failure_detail = (
                    "native kernel execution timed out or was cancelled"
                )
            return StageOutput(
                status=StageStatus.FAILED,
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                failure_code=failure_code,
                failure_detail=failure_detail,
                telemetry=TelemetryRecord(
                    wall_time_ms=result.wall_time_seconds * 1000,
                    resource_lane=ResourceLane.KERNEL,
                ),
            )
        if result.returncode != 0:
            return StageOutput(
                status=StageStatus.FAILED,
                data={**receipt, "receipt_sha256": receipt_sha256},
                effective_identity={
                    **dict(request.requested_identity),
                    "implementation": "lean-native-kernel",
                    "executable": self.lean_path,
                },
                failure_code=FailureCode.KERNEL_REJECTION,
                failure_detail="native kernel rejected the proof candidate",
                telemetry=TelemetryRecord(
                    wall_time_ms=result.wall_time_seconds * 1000,
                    bytes_in=len(source.encode("utf-8")),
                    bytes_out=len(result.stdout.encode("utf-8"))
                    + len(result.stderr.encode("utf-8")),
                    resource_lane=ResourceLane.KERNEL,
                ),
            )
        return StageOutput(
            data={**receipt, "receipt_sha256": receipt_sha256},
            effective_identity={
                **dict(request.requested_identity),
                "implementation": "lean-native-kernel",
                "executable": self.lean_path,
            },
            telemetry=TelemetryRecord(
                wall_time_ms=result.wall_time_seconds * 1000,
                bytes_in=len(source.encode("utf-8")),
                bytes_out=len(result.stdout.encode("utf-8"))
                + len(result.stderr.encode("utf-8")),
                resource_lane=ResourceLane.KERNEL,
            ),
            kernel_accepted=accepted,
            kernel_receipt_sha256=receipt_sha256 if accepted else None,
        )


@dataclass(slots=True)
class LiveRuntime:
    """Exact per-arm adapter assembly bound to one capability inventory."""

    inventory: CapabilityInventory
    adapters: Mapping[str, Mapping[StageName, StageAdapter]]
    kernel_runner: NativeKernelRunner | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.inventory, CapabilityInventory):
            raise RuntimeBindingError("inventory must be a CapabilityInventory")
        frozen: dict[str, Mapping[StageName, StageAdapter]] = {}
        for variant_id, route in self.adapters.items():
            definition = get_variant_definition(variant_id)
            if not isinstance(route, Mapping):
                raise RuntimeBindingError("runtime routes must be mappings")
            if set(route) != set(definition.stages):
                raise RuntimeBindingError(
                    f"{variant_id} live route does not exactly match frozen stages"
                )
            for stage, adapter in route.items():
                if not isinstance(adapter, StageAdapter) or adapter.stage is not stage:
                    raise RuntimeBindingError(
                        f"{variant_id}/{stage.value} adapter binding is invalid"
                    )
                requires_handler = (
                    stage is StageName.COMPILER
                    or (
                        stage is StageName.SPACY
                        and (
                            definition.spacy_mode is SpacyMode.REGEX_LEGAL
                            or _available(
                                self.inventory,
                                CapabilityKind.SPACY_PIPELINE,
                            )
                        )
                    )
                    or (
                        stage is StageName.SYMAI
                        and _available(
                            self.inventory,
                            CapabilityKind.SYMAI,
                            CapabilityKind.LLM_ROUTER,
                        )
                    )
                    or (
                        stage is StageName.HAMMER
                        and _available(
                            self.inventory, CapabilityKind.HAMMER
                        )
                    )
                    or (
                        stage is StageName.LEANSTRAL
                        and _available(
                            self.inventory,
                            CapabilityKind.LEANSTRAL_SERVICE,
                        )
                    )
                    or (
                        stage is StageName.KERNEL
                        and _available(
                            self.inventory,
                            CapabilityKind.LEAN_TOOLCHAIN,
                        )
                    )
                )
                if requires_handler and adapter.handler is None:
                    raise RuntimeBindingError(
                        f"{variant_id}/{stage.value} available stage remained inert"
                    )
            frozen[variant_id] = MappingProxyType(dict(route))
        self.adapters = MappingProxyType(frozen)

    def close(self) -> None:
        if self.kernel_runner is not None:
            self.kernel_runner.close()

    def __enter__(self) -> "LiveRuntime":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _capability_handler(
    *,
    inventory: CapabilityInventory,
    kind: CapabilityKind,
    stage: StageName,
    injected: StageHandler | None,
    default_factory: Callable[[], StageAdapter] | None,
) -> StageAdapter:
    record = _record(inventory, kind)
    if record.status is not CapabilityStatus.AVAILABLE:
        return _unavailable_adapter(stage)
    if injected is not None:
        return {
            StageName.SPACY: SpacyAdapter,
            StageName.SYMAI: SymaiAdapter,
            StageName.HAMMER: HammerAdapter,
            StageName.LEANSTRAL: LeanstralAdapter,
            StageName.KERNEL: KernelAdapter,
        }[stage](injected)
    if default_factory is None:
        raise RuntimeBindingError(
            f"available {kind.value} capability has no live {stage.value} handler"
        )
    adapter = default_factory()
    if adapter.handler is None:
        raise RuntimeBindingError(
            f"available {kind.value} capability remained inert"
        )
    return adapter


def build_live_runtime(
    inventory: CapabilityInventory,
    handlers: RuntimeBackendHandlers = RuntimeBackendHandlers(),
    *,
    variant_ids: Sequence[str] = ALL_VARIANT_IDS,
    state_directory: str | Path | None = None,
    kernel_timeout_seconds: float = 30.0,
) -> LiveRuntime:
    """Build exact live adapters for every requested frozen arm.

    Available capabilities must bind a callable handler.  Degraded or
    unavailable capabilities remain explicit unavailable adapters; they are
    never replaced with another provider or arm.
    """

    if not isinstance(inventory, CapabilityInventory):
        raise RuntimeBindingError("inventory must be a CapabilityInventory")
    if not isinstance(handlers, RuntimeBackendHandlers):
        raise RuntimeBindingError("handlers must be RuntimeBackendHandlers")
    if inventory.run_id.strip() == "":
        raise RuntimeBindingError("inventory run_id is empty")
    variants = tuple(variant_ids)
    if not variants or len(set(variants)) != len(variants):
        raise RuntimeBindingError("variant_ids must be nonempty and unique")
    for variant_id in variants:
        get_variant_definition(variant_id)

    kernel_runner: NativeKernelRunner | None = None
    if handlers.kernel is None and _available(
        inventory, CapabilityKind.LEAN_TOOLCHAIN
    ):
        lean = _record(
            inventory, CapabilityKind.LEAN_TOOLCHAIN
        ).identity.get("lean")
        path = lean.get("path") if isinstance(lean, Mapping) else None
        if not isinstance(path, str) or not path:
            raise RuntimeBindingError(
                "available Lean toolchain lacks an executable path"
            )
        kernel_runner = NativeKernelRunner(
            path,
            inventory.sha256,
            Path(state_directory or ".hssl-runtime-processes")
            / inventory.run_id,
            timeout_seconds=kernel_timeout_seconds,
        )

    routes: dict[str, Mapping[StageName, StageAdapter]] = {}
    for variant_id in variants:
        definition = get_variant_definition(variant_id)
        route: dict[StageName, StageAdapter] = {}
        for stage in definition.stages:
            if stage is StageName.COMPILER:
                route[stage] = CompilerAdapter(
                    handlers.compiler or _current_compiler_handler
                )
            elif stage is StageName.SPACY:
                if definition.spacy_mode is SpacyMode.REGEX_LEGAL:
                    route[stage] = (
                        SpacyAdapter(handlers.spacy)
                        if handlers.spacy is not None
                        else SpacyAdapter(
                            config=SpacyAdapterConfig(
                                mode=SpacyAdapterMode.REGEX_LEGAL
                            )
                        )
                    )
                else:
                    requested = _record(
                        inventory, CapabilityKind.SPACY_PIPELINE
                    ).identity.get("requested_model", "en_core_web_sm")
                    route[stage] = _capability_handler(
                        inventory=inventory,
                        kind=CapabilityKind.SPACY_PIPELINE,
                        stage=stage,
                        injected=handlers.spacy,
                        default_factory=lambda mode=definition.spacy_mode, requested=requested: SpacyAdapter(
                            config=SpacyAdapterConfig(
                                requested_model=str(requested),
                                mode=_spacy_mode(mode),
                            )
                        ),
                    )
            elif stage is StageName.SYMAI:
                injected = (
                    handlers.legacy_symai
                    if definition.symai_policy is StagePolicy.LEGACY_DIAGNOSTIC
                    else handlers.symai
                )
                symai_record = _record(inventory, CapabilityKind.SYMAI)
                router_record = _record(inventory, CapabilityKind.LLM_ROUTER)
                if not _available(
                    inventory, CapabilityKind.SYMAI, CapabilityKind.LLM_ROUTER
                ):
                    route[stage] = _unavailable_adapter(stage)
                elif injected is not None:
                    route[stage] = SymaiAdapter(injected)
                elif definition.symai_policy is StagePolicy.LEGACY_DIAGNOSTIC:
                    raise RuntimeBindingError(
                        "available SyMAI capability lacks the distinct legacy S1 handler"
                    )
                else:
                    provider = symai_record.identity.get(
                        "requested_provider",
                        router_record.identity.get("requested_provider"),
                    )
                    model = symai_record.identity.get(
                        "requested_model",
                        router_record.identity.get("requested_model"),
                    )
                    if not isinstance(provider, str) or not isinstance(model, str):
                        raise RuntimeBindingError(
                            "available SyMAI/router identity is incomplete"
                        )
                    route[stage] = SymaiAdapter(
                        config=SymaiAdapterConfig(
                            provider=provider,
                            model=model,
                        )
                    )
            elif stage is StageName.HAMMER:
                route[stage] = _capability_handler(
                    inventory=inventory,
                    kind=CapabilityKind.HAMMER,
                    stage=stage,
                    injected=handlers.hammer,
                    default_factory=None,
                )
            elif stage is StageName.LEANSTRAL:
                route[stage] = _capability_handler(
                    inventory=inventory,
                    kind=CapabilityKind.LEANSTRAL_SERVICE,
                    stage=stage,
                    injected=handlers.leanstral,
                    default_factory=LeanstralAdapter,
                )
            elif stage is StageName.KERNEL:
                injected_kernel = (
                    None
                    if handlers.kernel is None
                    else _validated_kernel_handler(handlers.kernel)
                )
                route[stage] = _capability_handler(
                    inventory=inventory,
                    kind=CapabilityKind.LEAN_TOOLCHAIN,
                    stage=stage,
                    injected=injected_kernel,
                    default_factory=(
                        None
                        if kernel_runner is None
                        else lambda runner=kernel_runner: KernelAdapter(
                            _validated_kernel_handler(runner)
                        )
                    ),
                )
        routes[variant_id] = MappingProxyType(route)
    return LiveRuntime(inventory, MappingProxyType(routes), kernel_runner)


def build_live_adapters(
    inventory: CapabilityInventory,
    handlers: RuntimeBackendHandlers = RuntimeBackendHandlers(),
    **kwargs: object,
) -> Mapping[str, Mapping[StageName, StageAdapter]]:
    """Compatibility factory returning the strict per-variant adapter map."""

    return build_live_runtime(inventory, handlers, **kwargs).adapters


def _probe_cli(args: argparse.Namespace) -> int:
    from . import RunPaths

    inventory = probe_runtime_capabilities(
        args.run_id, RunPaths.for_run(args.run_id)
    )
    required = {
        item.strip()
        for item in (args.require or "").split(",")
        if item.strip()
    }
    unknown = required - {kind.value for kind in CapabilityKind}
    if unknown:
        raise RuntimeBindingError(
            f"unknown required capabilities: {sorted(unknown)}"
        )
    unavailable = [
        record.kind.value
        for record in inventory.capabilities
        if record.kind.value in required
        and record.status is not CapabilityStatus.AVAILABLE
    ]
    print(canonical_json(inventory.to_dict()))
    return 1 if unavailable else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Frozen logic-pipeline live runtime"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--run-id", default="hssl-runtime-probe")
    probe.add_argument("--require", default="")
    args = parser.parse_args(argv)
    if args.command == "probe":
        return _probe_cli(args)
    raise RuntimeBindingError(f"unsupported runtime command: {args.command}")


if __name__ == "__main__":  # pragma: no cover - exercised by operator CLI
    raise SystemExit(main())


__all__ = [
    "COMPILED_OBLIGATION_SCHEMA",
    "CompiledObligation",
    "HSSLEV1142E95",
    "KERNEL_RECEIPT_SCHEMA",
    "LiveRuntime",
    "NativeKernelRunner",
    "RUNTIME_VERSION",
    "RuntimeBackendHandlers",
    "RuntimeBindingError",
    "build_live_adapters",
    "build_live_runtime",
    "compile_reviewed_obligation",
    "main",
]
