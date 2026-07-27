"""Fail-closed orchestration for the measured canonical legal round trip.

``CanonicalSemanticRoundTrip@1`` is intentionally a very small composition:

``structured text -> typed deontic compiler -> canonical IR ->``
``source-withheld deterministic decompiler -> text -> compiler -> IR``.

Pipeline ``SUCCESS`` means only that the three stages completed successfully
with a sealed L1→T1→L2 evidence chain.  It is *not* a semantic parity or
noninferiority decision.  Scored SRT-018 admission lives in the separate
parity-report artifact (``CanonicalSemanticRoundTripParityReport@1``) and
must recompute losses/gates under the frozen SRT-015 policy CID.

The orchestrator has no dependency on the benchmark package.  It first
validates the frozen parity policy and component identities, stops at the
first non-successful stage, and never invokes a fallback or model.  In
particular, the decompiler request is constructed afresh from L1; it cannot
see the original source, source map, compiler provenance, or caller request.

The integrated result retains the three public stage results and content
identities, but never retains the originating source text.  Its strict wire
decoder recomputes every nested result CID and the outer result CID.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ipfs_datasets_py.logic.legal_ir.canonical_compiler import (
    TYPED_DEONTIC_COMPILER_CONFIG_CID,
    TypedDeonticCanonicalCompiler,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    IMPLEMENTATION_REPRESENTATIVE_ARM_ID,
    IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID,
    SELECTED_REALIZER_INTERFACE,
    SOURCE_WITHHELD_DECOMPILER_CONFIG,
    SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
    SOURCE_WITHHELD_RENDERING_SPEC_CID,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CanonicalError,
    CanonicalErrorCode,
    CanonicalStructuredTextCompiler,
    CanonicalStructuredTextDecompiler,
    CompilerRequest,
    CompilerResult,
    DecompilerRequest,
    DecompilerResult,
    OperationStatus,
    load_parity_policy,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
    SourceWithheldCanonicalDecompiler,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json, validate_cid


CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE: Final = (
    "CanonicalSemanticRoundTrip@1"
)
CANONICAL_SEMANTIC_ROUNDTRIP_RESULT_SCHEMA: Final = (
    "ipfs-datasets.canonical-semantic-roundtrip-result.v1"
)
CANONICAL_SEMANTIC_ROUNDTRIP_COMPONENT_ID: Final = (
    "typed_deontic_source_withheld_roundtrip"
)
CANONICAL_SEMANTIC_ROUNDTRIP_STAGES: Final = (
    "l1_compile",
    "t1_decompile",
    "l2_compile",
)


def _configuration_payload() -> dict[str, object]:
    """Return the frozen production composition without runtime state."""

    return {
        "interface": CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE,
        "component_id": CANONICAL_SEMANTIC_ROUNDTRIP_COMPONENT_ID,
        "policy_cid": CANONICAL_PARITY_POLICY_CID,
        "selection": {
            "implementation_representative_arm_id": (
                IMPLEMENTATION_REPRESENTATIVE_ARM_ID
            ),
            "implementation_representative_arm_identity_cid": (
                IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID
            ),
        },
        "compiler": {
            "interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
            "configuration_cid": TYPED_DEONTIC_COMPILER_CONFIG_CID,
        },
        "decompiler": {
            "interface": SELECTED_REALIZER_INTERFACE,
            "configuration_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
            "rendering_spec_cid": SOURCE_WITHHELD_RENDERING_SPEC_CID,
            "source_withheld": True,
        },
        "deterministic": True,
        "fallback_allowed": False,
        "learned_stages": [],
        "model_call_count": 0,
    }


CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID: Final = cid_for_dag_json(
    _configuration_payload()
)


def roundtrip_configuration() -> dict[str, object]:
    """Return a detached copy of the only accepted composition."""

    return _configuration_payload()


def measured_parity_compiler_request(
    source_text: str,
    *,
    request_id: str,
    atom_vocabulary: CanonicalAtomVocabulary,
    config: Mapping[str, object] | None = None,
) -> CompilerRequest:
    """Build a compiler request for measured SRT-018 parity runs.

    Production ``CompilerRequest`` defaults to
    ``allow_explicit_partial=False``, which is intentionally stricter than the
    selected benchmark constructor.  Parity against that arm requires explicit
    partial disclosure so multi-facet pilot documents do not systematically
    abstain while still surfacing unsupported diagnostics.
    """

    return CompilerRequest(
        source_text=source_text,
        request_id=request_id,
        atom_vocabulary=atom_vocabulary,
        policy_cid=CANONICAL_PARITY_POLICY_CID,
        allow_explicit_partial=True,
        config={} if config is None else dict(config),
    )


def _dag_json_cid(value: object, field: str) -> str:
    try:
        return validate_cid(value, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(
            f"{field} must be a canonical dag-json CIDv1"
        ) from exc


def _raw_cid(value: object, field: str) -> str:
    try:
        return validate_cid(value, codecs=("raw",))
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(
            f"{field} must be a canonical raw CIDv1"
        ) from exc


def _error_from_stage(
    stage_result: CompilerResult | DecompilerResult,
) -> CanonicalError:
    if stage_result.error is None:
        raise CanonicalContractError(
            "non-successful stage result must carry a canonical error"
        )
    return stage_result.error


@dataclass(frozen=True, slots=True)
class CanonicalSemanticRoundTripResult:
    """CID-bound terminal result that deliberately excludes original text."""

    status: OperationStatus
    request_cid: str
    source_cid: str
    policy_cid: str
    terminal_stage: str
    completed_stages: tuple[str, ...] = ()
    l1_result: CompilerResult | None = None
    t1_result: DecompilerResult | None = None
    l2_result: CompilerResult | None = None
    error: CanonicalError | None = None

    def __post_init__(self) -> None:
        try:
            status = (
                self.status
                if isinstance(self.status, OperationStatus)
                else OperationStatus(self.status)
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalContractError(
                "roundtrip status is not a terminal operation status"
            ) from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "request_cid",
            _dag_json_cid(self.request_cid, "request_cid"),
        )
        object.__setattr__(
            self, "source_cid", _raw_cid(self.source_cid, "source_cid")
        )
        policy_cid = _dag_json_cid(self.policy_cid, "policy_cid")
        if policy_cid != CANONICAL_PARITY_POLICY_CID:
            raise CanonicalContractError("roundtrip policy CID changed")
        object.__setattr__(self, "policy_cid", policy_cid)

        if not isinstance(self.terminal_stage, str) or self.terminal_stage not in {
            "policy_validation",
            "component_validation",
            *CANONICAL_SEMANTIC_ROUNDTRIP_STAGES,
            "complete",
        }:
            raise CanonicalContractError("roundtrip terminal_stage changed")
        if not isinstance(self.completed_stages, Sequence) or isinstance(
            self.completed_stages, (str, bytes, bytearray)
        ):
            raise CanonicalContractError("completed_stages must be an array")
        completed = tuple(self.completed_stages)
        expected_prefix = CANONICAL_SEMANTIC_ROUNDTRIP_STAGES[
            : len(completed)
        ]
        if completed != expected_prefix:
            raise CanonicalContractError(
                "completed_stages must be an ordered stage prefix"
            )
        object.__setattr__(self, "completed_stages", completed)

        for field_name, expected_type in (
            ("l1_result", CompilerResult),
            ("t1_result", DecompilerResult),
            ("l2_result", CompilerResult),
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, expected_type):
                raise CanonicalContractError(
                    f"{field_name} must use its canonical result contract"
                )
        if self.error is not None and not isinstance(self.error, CanonicalError):
            raise CanonicalContractError("roundtrip error must be canonical")

        present = (
            self.l1_result is not None,
            self.t1_result is not None,
            self.l2_result is not None,
        )
        if present not in {
            (False, False, False),
            (True, False, False),
            (True, True, False),
            (True, True, True),
        }:
            raise CanonicalContractError(
                "roundtrip stage results must form an ordered prefix"
            )
        if self.l1_result is not None:
            if self.l1_result.request_cid != self.request_cid:
                raise CanonicalContractError(
                    "L1 result is not bound to the outer request"
                )
            l1_provenance = self.l1_result.provenance
            if (
                not isinstance(l1_provenance, Mapping)
                or l1_provenance.get("source_cid") != self.source_cid
            ):
                raise CanonicalContractError(
                    "L1 provenance is not bound to the outer source_cid"
                )
        if self.t1_result is not None:
            if (
                self.l1_result is None
                or self.l1_result.status is not OperationStatus.SUCCESS
                or self.l1_result.canonical_ir is None
            ):
                raise CanonicalContractError(
                    "T1 result requires a successful nonempty L1"
                )
            if not self.t1_result.component_trace or any(
                trace.input_cid != self.l1_result.canonical_ir.ir_cid
                for trace in self.t1_result.component_trace
            ):
                raise CanonicalContractError(
                    "T1 trace is not bound only to the L1 canonical IR"
                )
        if self.l2_result is not None:
            if (
                self.t1_result is None
                or self.t1_result.status is not OperationStatus.SUCCESS
                or self.t1_result.text_cid is None
            ):
                raise CanonicalContractError(
                    "L2 result requires a successful nonblank T1"
                )
            l2_provenance = self.l2_result.provenance
            if (
                not isinstance(l2_provenance, Mapping)
                or l2_provenance.get("source_cid") != self.t1_result.text_cid
            ):
                raise CanonicalContractError(
                    "L2 provenance is not bound to the T1 text_cid"
                )
        traces = tuple(
            trace
            for result in (
                self.l1_result,
                self.t1_result,
                self.l2_result,
            )
            if result is not None
            for trace in result.component_trace
        )
        if any(trace.model_receipt_cid is not None for trace in traces):
            raise CanonicalContractError(
                "measured canonical roundtrip cannot carry a model receipt"
            )

        if status is OperationStatus.SUCCESS:
            # Stage-completion success only.  Semantic L1/L2 identity, gate
            # eligibility, and SRT-015 noninferiority are scored by the
            # separate parity-report contract, not by this outer status.
            if (
                self.terminal_stage != "complete"
                or completed != CANONICAL_SEMANTIC_ROUNDTRIP_STAGES
                or self.error is not None
                or self.l1_result is None
                or self.t1_result is None
                or self.l2_result is None
                or any(
                    result.status is not OperationStatus.SUCCESS
                    for result in (
                        self.l1_result,
                        self.t1_result,
                        self.l2_result,
                    )
                )
            ):
                raise CanonicalContractError(
                    "successful roundtrip requires three successful stages"
                )
        elif self.terminal_stage == "complete" or self.error is None:
            raise CanonicalContractError(
                "non-successful roundtrip requires a stage and error"
            )

    @property
    def model_call_count(self) -> int:
        """The frozen composition has no learned stage."""

        return 0

    @property
    def model_receipt_cids(self) -> tuple[str, ...]:
        """Expose the auditable absence of model receipts."""

        return ()

    def identity_payload(self) -> dict[str, object]:
        """Return the source-free payload covered by ``result_cid``."""

        return {
            "interface": CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE,
            "schema_version": CANONICAL_SEMANTIC_ROUNDTRIP_RESULT_SCHEMA,
            "status": self.status.value,
            "request_cid": self.request_cid,
            "source_cid": self.source_cid,
            "policy_cid": self.policy_cid,
            "configuration_cid": CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
            "terminal_stage": self.terminal_stage,
            "completed_stages": list(self.completed_stages),
            "stage_results": {
                "l1": (
                    None
                    if self.l1_result is None
                    else self.l1_result.to_dict()
                ),
                "t1": (
                    None
                    if self.t1_result is None
                    else self.t1_result.to_dict()
                ),
                "l2": (
                    None
                    if self.l2_result is None
                    else self.l2_result.to_dict()
                ),
            },
            "source_withheld": True,
            "fallback_used": False,
            "model_call_count": self.model_call_count,
            "model_receipt_cids": list(self.model_receipt_cids),
            "error": None if self.error is None else self.error.to_dict(),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "result_cid": self.result_cid,
            "result_cid_codec": "dag-json",
            "result_cid_scope": "document_without_result_cid_fields",
        }

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalSemanticRoundTripResult":
        """Strictly decode and revalidate a source-free result receipt."""

        if not isinstance(value, Mapping):
            raise CanonicalContractError("roundtrip result must be an object")
        expected = {
            "interface",
            "schema_version",
            "status",
            "request_cid",
            "source_cid",
            "policy_cid",
            "configuration_cid",
            "terminal_stage",
            "completed_stages",
            "stage_results",
            "source_withheld",
            "fallback_used",
            "model_call_count",
            "model_receipt_cids",
            "error",
            "result_cid",
            "result_cid_codec",
            "result_cid_scope",
        }
        if set(value) != expected:
            raise CanonicalContractError("roundtrip result fields changed")
        if value["interface"] != CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE:
            raise CanonicalContractError("roundtrip result interface changed")
        if (
            value["schema_version"]
            != CANONICAL_SEMANTIC_ROUNDTRIP_RESULT_SCHEMA
        ):
            raise CanonicalContractError("roundtrip result schema changed")
        if (
            value["configuration_cid"]
            != CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID
        ):
            raise CanonicalContractError(
                "roundtrip result configuration CID changed"
            )
        if (
            value["source_withheld"] is not True
            or value["fallback_used"] is not False
            or value["model_call_count"] != 0
            or value["model_receipt_cids"] != []
        ):
            raise CanonicalContractError(
                "roundtrip execution profile changed"
            )
        if (
            value["result_cid_codec"] != "dag-json"
            or value["result_cid_scope"]
            != "document_without_result_cid_fields"
        ):
            raise CanonicalContractError("roundtrip result CID contract changed")
        stage_results = value["stage_results"]
        if not isinstance(stage_results, Mapping) or set(stage_results) != {
            "l1",
            "t1",
            "l2",
        }:
            raise CanonicalContractError("roundtrip stage result fields changed")
        raw_error = value["error"]
        result = cls(
            status=value["status"],  # type: ignore[arg-type]
            request_cid=value["request_cid"],  # type: ignore[arg-type]
            source_cid=value["source_cid"],  # type: ignore[arg-type]
            policy_cid=value["policy_cid"],  # type: ignore[arg-type]
            terminal_stage=value["terminal_stage"],  # type: ignore[arg-type]
            completed_stages=tuple(value["completed_stages"]),  # type: ignore[arg-type]
            l1_result=(
                None
                if stage_results["l1"] is None
                else CompilerResult.from_dict(stage_results["l1"])
            ),
            t1_result=(
                None
                if stage_results["t1"] is None
                else DecompilerResult.from_dict(stage_results["t1"])
            ),
            l2_result=(
                None
                if stage_results["l2"] is None
                else CompilerResult.from_dict(stage_results["l2"])
            ),
            error=(
                None
                if raw_error is None
                else CanonicalError.from_dict(raw_error)
            ),
        )
        supplied = _dag_json_cid(value["result_cid"], "result_cid")
        if supplied != result.result_cid:
            raise CanonicalContractError(
                "result_cid does not match roundtrip result"
            )
        return result


class CanonicalSemanticRoundTrip:
    """Execute the exact selected compiler/decompiler composition."""

    __slots__ = ("_compiler", "_decompiler")

    def __init__(
        self,
        compiler: CanonicalStructuredTextCompiler | None = None,
        decompiler: CanonicalStructuredTextDecompiler | None = None,
    ) -> None:
        self._compiler = (
            TypedDeonticCanonicalCompiler()
            if compiler is None
            else compiler
        )
        self._decompiler = (
            SourceWithheldCanonicalDecompiler()
            if decompiler is None
            else decompiler
        )

    @property
    def identity(self) -> str:
        return CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE

    @property
    def configuration_cid(self) -> str:
        return CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID

    @property
    def deterministic(self) -> bool:
        return True

    @property
    def uses_model(self) -> bool:
        return False

    def _failure(
        self,
        request: CompilerRequest,
        *,
        terminal_stage: str,
        completed_stages: tuple[str, ...],
        error: CanonicalError,
        status: OperationStatus = OperationStatus.FAILED,
        l1_result: CompilerResult | None = None,
        t1_result: DecompilerResult | None = None,
        l2_result: CompilerResult | None = None,
    ) -> CanonicalSemanticRoundTripResult:
        return CanonicalSemanticRoundTripResult(
            status=status,
            request_cid=request.request_cid,
            source_cid=request.source_cid,
            policy_cid=CANONICAL_PARITY_POLICY_CID,
            terminal_stage=terminal_stage,
            completed_stages=completed_stages,
            l1_result=l1_result,
            t1_result=t1_result,
            l2_result=l2_result,
            error=error,
        )

    def _component_error(self) -> CanonicalError | None:
        """Validate identities/configuration before invoking either component."""

        if (
            getattr(self._compiler, "identity", None)
            != CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE
            or getattr(self._compiler, "configuration_cid", None)
            != TYPED_DEONTIC_COMPILER_CONFIG_CID
        ):
            return CanonicalError(
                code=CanonicalErrorCode.POLICY_MISMATCH,
                message=(
                    "compiler identity or configuration does not match the "
                    "frozen measured composition"
                ),
                retryable=False,
                details={},
            )
        if (
            getattr(self._decompiler, "identity", None)
            != SELECTED_REALIZER_INTERFACE
            or getattr(self._decompiler, "deterministic", None) is not True
            or getattr(self._decompiler, "uses_model", None) is not False
        ):
            return CanonicalError(
                code=CanonicalErrorCode.POLICY_MISMATCH,
                message=(
                    "decompiler identity or execution profile does not match "
                    "the frozen source-withheld composition"
                ),
                retryable=False,
                details={},
            )
        return None

    def run(
        self, request: CompilerRequest
    ) -> CanonicalSemanticRoundTripResult:
        """Compile, realize without source, and compile again.

        Policy and component drift are rejected before a component call.  The
        same caller-supplied vocabulary, partial-disclosure choice, and
        compiler config are reused for L2; no data other than L1 is passed to
        the decompiler.
        """

        if not isinstance(request, CompilerRequest):
            raise CanonicalContractError(
                "request must be CompilerRequest; unbound source is rejected"
            )

        try:
            policy = load_parity_policy()
            if policy.policy_cid != CANONICAL_PARITY_POLICY_CID:
                raise CanonicalContractError(
                    "loaded parity policy CID changed"
                )
        except Exception as exc:
            return self._failure(
                request,
                terminal_stage="policy_validation",
                completed_stages=(),
                error=CanonicalError(
                    code=CanonicalErrorCode.POLICY_MISMATCH,
                    message=(
                        "canonical parity policy is unavailable or invalid; "
                        "no component was called"
                    ),
                    retryable=False,
                    details={"exception_type": type(exc).__name__},
                ),
            )

        component_error = self._component_error()
        if component_error is not None:
            return self._failure(
                request,
                terminal_stage="component_validation",
                completed_stages=(),
                error=component_error,
            )

        l1_result = self._compiler.compile(request)
        if l1_result.status is not OperationStatus.SUCCESS:
            return self._failure(
                request,
                terminal_stage="l1_compile",
                completed_stages=(),
                error=_error_from_stage(l1_result),
                status=l1_result.status,
                l1_result=l1_result,
            )
        if l1_result.canonical_ir is None:  # defensive protocol fence
            return self._failure(
                request,
                terminal_stage="l1_compile",
                completed_stages=(),
                error=CanonicalError(
                    code=CanonicalErrorCode.EMPTY_OUTPUT,
                    message="successful L1 compiler result did not contain IR",
                    retryable=False,
                    details={},
                ),
                l1_result=l1_result,
            )

        # This fresh object is the source-withholding boundary.  Only the
        # canonical semantic object and frozen public identities cross it.
        decompiler_request = DecompilerRequest(
            canonical_ir=l1_result.canonical_ir,
            request_id=f"{request.request_id}:t1",
            policy_cid=policy.policy_cid,
            config=dict(SOURCE_WITHHELD_DECOMPILER_CONFIG),
        )
        t1_result = self._decompiler.decompile(decompiler_request)
        if t1_result.status is not OperationStatus.SUCCESS:
            return self._failure(
                request,
                terminal_stage="t1_decompile",
                completed_stages=("l1_compile",),
                error=_error_from_stage(t1_result),
                status=t1_result.status,
                l1_result=l1_result,
                t1_result=t1_result,
            )
        if t1_result.text is None:  # defensive protocol fence
            return self._failure(
                request,
                terminal_stage="t1_decompile",
                completed_stages=("l1_compile",),
                error=CanonicalError(
                    code=CanonicalErrorCode.EMPTY_OUTPUT,
                    message="successful decompiler result did not contain text",
                    retryable=False,
                    details={},
                ),
                l1_result=l1_result,
                t1_result=t1_result,
            )

        l2_request = CompilerRequest(
            source_text=t1_result.text,
            request_id=f"{request.request_id}:l2",
            atom_vocabulary=request.atom_vocabulary,
            policy_cid=policy.policy_cid,
            allow_explicit_partial=request.allow_explicit_partial,
            config=dict(request.config),
        )
        l2_result = self._compiler.compile(l2_request)
        if l2_result.status is not OperationStatus.SUCCESS:
            return self._failure(
                request,
                terminal_stage="l2_compile",
                completed_stages=("l1_compile", "t1_decompile"),
                error=_error_from_stage(l2_result),
                status=l2_result.status,
                l1_result=l1_result,
                t1_result=t1_result,
                l2_result=l2_result,
            )

        return CanonicalSemanticRoundTripResult(
            status=OperationStatus.SUCCESS,
            request_cid=request.request_cid,
            source_cid=request.source_cid,
            policy_cid=policy.policy_cid,
            terminal_stage="complete",
            completed_stages=CANONICAL_SEMANTIC_ROUNDTRIP_STAGES,
            l1_result=l1_result,
            t1_result=t1_result,
            l2_result=l2_result,
            error=None,
        )

    round_trip = run


CanonicalRoundTrip = CanonicalSemanticRoundTrip


__all__ = [
    "CANONICAL_SEMANTIC_ROUNDTRIP_COMPONENT_ID",
    "CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID",
    "CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE",
    "CANONICAL_SEMANTIC_ROUNDTRIP_RESULT_SCHEMA",
    "CANONICAL_SEMANTIC_ROUNDTRIP_STAGES",
    "CanonicalRoundTrip",
    "CanonicalSemanticRoundTrip",
    "CanonicalSemanticRoundTripResult",
    "measured_parity_compiler_request",
    "roundtrip_configuration",
]
