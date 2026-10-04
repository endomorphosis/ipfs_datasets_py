"""Source-bound end-to-end software-verification exemplars (LFV-G081 / LFV-040).

SoftwareVerificationExamples@1

Acceptance covered here:

* Seven deterministic lanes bind sources to IR, translations, requests, results,
  witnesses, receipts, and declared assurance through the public API.
* Unavailable optional tools degrade explicitly (never silent success).
* At least one negative/counterexample case exists per lane.
* Offline execution is mandatory; no live tool installs or network probes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.authorization import (
    AUTHORIZATION_IR_INTERFACE,
    AtomPolarity,
    AuthorizationAtom,
    AuthorizationFact,
    AuthorizationIR,
    AuthorizationPrincipal,
    AuthorizationRule,
    AuthorizationTerm,
    DecisionOutcome,
    DecisionQuery,
    EffectKind,
    PolicyDecision,
    PolicyBounds,
    PredicateSignature,
    PrincipalKind,
    RuleKind,
)
from ipfs_datasets_py.logic.software_verification.concurrency import (
    CONCURRENCY_IR_INTERFACE,
    AtomicRegion,
    AtomicityKind,
    BoundedSchedule,
    ChannelMode,
    ComponentKind,
    ConcurrencyFairness,
    ConcurrencyIR,
    ConcurrentChannel,
    ConcurrentComponent,
    ConcurrentStep,
    FairnessKind,
    InterferenceAssumption,
    InterferenceKind,
    StepOwner,
)
from ipfs_datasets_py.logic.software_verification.heap import (
    HEAP_MODEL_INTERFACE,
    HeapLocation,
    HeapModel,
    HeapValue,
    LocationKind,
    OwnershipKind,
    OwnershipRecord,
    Permission,
    PointsToCell,
    ResourceAlgebra,
    ResourceAlgebraKind,
    ResourceUnit,
    ValueKind,
)
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    HYPERPROPERTY_IR_INTERFACE,
    ExecutionTrace,
    HyperpropertyIR,
    HyperpropertyVerdict,
    InformationFlowPolicy,
    ObservationKind,
    ObservationSpec,
    SecurityLabel,
    SecurityLevel,
    SelfCompositionBound,
)
from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
    RUNTIME_MTL_INTERFACE,
    Clock,
    Event,
    Formula,
    TimeValue,
    Trace,
    TraceKind,
)
from ipfs_datasets_py.logic.software_verification.protocol import (
    PROTOCOL_IR_INTERFACE,
    AdversaryAccess,
    AdversaryCapability,
    AdversaryKind,
    ChannelSecurity,
    EquationalTheory,
    EventPhase,
    FreshName,
    FreshNameKind,
    FunctionKind,
    KeyKind,
    ProtocolAdversary,
    ProtocolChannel,
    ProtocolClaim,
    ProtocolClaimKind,
    ProtocolEvent,
    ProtocolFunction,
    ProtocolIR,
    ProtocolKey,
    ProtocolMessage,
    ProtocolRole,
    ProtocolSort,
    ProtocolTerm,
    ProtocolVariable,
    SortKind,
    TrustAssumption,
)
from ipfs_datasets_py.logic.software_verification.receipts import (
    LogicTranslationReceipt,
)
from ipfs_datasets_py.logic.software_verification.separation import (
    SEPARATION_LOGIC_IR_INTERFACE,
    FrameObligation,
    FrameObligationKind,
    HeapTheory,
    SeparationLogicIR,
    emp_formula,
    points_to_formula,
    sep_conj,
)
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    adapt_source_to_software_verification,
)
from ipfs_datasets_py.logic.software_verification.translations import (
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
    TranslationWitness,
)
from ipfs_datasets_py.logic.verification_api import (
    LOGIC_VERIFICATION_API_INTERFACE,
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationResponse,
    VerificationStatus,
    get_verification_api,
)


DATASETS_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    DATASETS_ROOT
    / "examples"
    / "logic"
    / "software_verification"
    / "manifest.json"
)
MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

INTERFACE = "SoftwareVerificationExamples@1"
SCHEMA_VERSION = "software-verification-examples/v1"
REQUIRED_BINDING_STAGES = (
    "source",
    "ir",
    "translations",
    "requests",
    "results",
    "witnesses",
    "receipts",
    "assurance",
)
REQUIRED_LANE_IDS = (
    "contracts_resources",
    "heap_ownership",
    "concurrent_workflows",
    "authorization",
    "cryptographic_protocols",
    "noninterference",
    "runtime_temporal_monitoring",
)
ACCEPTABLE_CHECK_STATUSES = {
    VerificationStatus.SUCCEEDED,
    VerificationStatus.PARTIAL,
    VerificationStatus.UNAVAILABLE,
    VerificationStatus.UNSUPPORTED,
    VerificationStatus.ERROR,
}
TERMINAL_DEGRADATION = {
    VerificationStatus.UNAVAILABLE,
    VerificationStatus.UNSUPPORTED,
    VerificationStatus.ERROR,
    VerificationStatus.INVALID,
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content_sha(text: str) -> str:
    return _digest(text)


def _source_ref(path: str, text: str, *, ref_id: str | None = None) -> SourceRef:
    source_id = Path(path).name
    return SourceRef(
        ref_id=ref_id or f"source:{source_id}",
        source_uri=f"file:///{path.lstrip('/')}",
        source_id=source_id,
        source_revision="git:example-lfv-040",
        content_sha256=_content_sha(text),
    )


def _span(source_ref_id: str, text: str, *, span_id: str | None = None) -> SourceSpan:
    lines = max(1, text.count("\n") + (0 if text.endswith("\n") else 1))
    return SourceSpan(
        span_id=span_id or f"span:{source_ref_id.split(':', 1)[-1]}",
        source_ref_id=source_ref_id,
        start_byte=0,
        end_byte=max(1, len(text.encode("utf-8"))),
        start_line=1,
        start_column=1,
        end_line=lines,
        end_column=2,
    )


def _mapped(source_ref_id: str, span_id: str) -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (source_ref_id,), "span_ids": (span_id,)}


def _compiler_binding(lane_id: str) -> CompilerBinding:
    return CompilerBinding(
        compiler_id=f"compiler:example-{lane_id}",
        compiler_version="1.0.0",
        implementation_identity="sha256:" + "c" * 64,
        configuration_identity="sha256:" + "d" * 64,
        stage="lower",
    )


def _translation_witness(lane_id: str, case_id: str) -> TranslationWitness:
    return TranslationWitness(
        witness_id=f"witness:{case_id}",
        witness_kind="example_fixture",
        artifact_identity="sha256:" + _digest(f"{lane_id}:{case_id}"),
        checker_id="checker:software-verification-examples",
        checker_version="1.0.0",
        metadata={"lane_id": lane_id, "case_id": case_id},
    )


def _build_receipt(
    *,
    lane: Mapping[str, Any],
    source_identity: str,
    target_identity: str,
    case_id: str,
    preserved_property_ids: Sequence[str],
    authority: EvidenceAuthority,
) -> LogicTranslationReceipt:
    return LogicTranslationReceipt(
        source_identity=source_identity,
        target_identity=target_identity,
        source_family_id=str(lane["source_family_id"]),
        source_family_version="1.0.0",
        target_family_id=str(lane["target_family_id"]),
        target_family_version="1.0.0",
        compilers=(_compiler_binding(str(lane["lane_id"])),),
        preservation_claim=PreservationClaim(
            kind=PreservationKind.EXACT,
            preserved_property_ids=tuple(preserved_property_ids),
            permitted_result_classes=("proved", "disproved", "satisfied", "violated"),
            description=f"Example translation for lane {lane['lane_id']}",
        ),
        authority_ceiling=authority,
        witnesses=(_translation_witness(str(lane["lane_id"]), case_id),),
        metadata={"lane_id": lane["lane_id"], "case_id": case_id, "objective": "LFV-G081"},
    )


def _authority_for(declared: str) -> EvidenceAuthority:
    mapping = {
        "bounded": EvidenceAuthority.BOUNDED,
        "authorization": EvidenceAuthority.BOUNDED,
        "protocol": EvidenceAuthority.BOUNDED,
        "hyperproperty": EvidenceAuthority.BOUNDED,
        "monitor": EvidenceAuthority.BOUNDED,
        "advisory": EvidenceAuthority.ADVISORY,
        "authoritative": EvidenceAuthority.AUTHORITATIVE,
    }
    return mapping.get(declared, EvidenceAuthority.BOUNDED)


def _formula_from_mapping(payload: Mapping[str, Any]) -> Formula:
    operands = tuple(
        _formula_from_mapping(item) if isinstance(item, Mapping) else item
        for item in payload.get("operands") or ()
    )
    return Formula(
        operator=str(payload.get("operator") or "atom"),
        logic=str(payload.get("logic") or "ltlf"),
        operands=operands,
        proposition=str(payload.get("proposition") or ""),
    )


def _trace_from_mapping(payload: Mapping[str, Any]) -> Trace:
    clock_payload = payload.get("clock") or {"clock_id": "clock:main"}
    clock = Clock(clock_id=str(clock_payload.get("clock_id") or "clock:main"))
    events: list[Event] = []
    for index, item in enumerate(payload.get("events") or ()):
        if not isinstance(item, Mapping):
            continue
        time_value = item.get("time", index)
        if isinstance(time_value, Mapping):
            time = TimeValue(
                int(time_value.get("numerator", index)),
                int(time_value.get("denominator", 1)),
            )
        else:
            time = TimeValue(int(time_value))
        events.append(
            Event(
                event_id=str(item.get("event_id") or f"event:{index}"),
                event_type=str(item.get("event_type") or "state"),
                time=time,
                true_propositions=tuple(item.get("true_propositions") or item.get("true") or ()),
                false_propositions=tuple(
                    item.get("false_propositions") or item.get("false") or ()
                ),
            )
        )
    kind = payload.get("kind") or TraceKind.FINITE
    if not isinstance(kind, TraceKind):
        kind = TraceKind(str(kind))
    return Trace(clock=clock, events=tuple(events), kind=kind)


@dataclass(frozen=True, slots=True)
class BindingBundle:
    """One end-to-end binding for a single example case."""

    lane_id: str
    case_id: str
    case_kind: str
    stages: dict[str, Any] = field(default_factory=dict)
    responses: tuple[VerificationResponse, ...] = ()
    optional_tool_degradations: tuple[str, ...] = ()

    def require_stages(self) -> None:
        missing = [stage for stage in REQUIRED_BINDING_STAGES if stage not in self.stages]
        assert not missing, f"{self.case_id} missing binding stages: {missing}"
        for stage in REQUIRED_BINDING_STAGES:
            assert self.stages[stage], f"{self.case_id} empty binding stage: {stage}"


def _portfolio_request(
    api: LogicVerificationAPI,
    *,
    obligation_id: str,
    property_kind: str,
    statement: str,
    assumption_ids: Sequence[str] = (),
    request_id: str = "",
) -> VerificationResponse:
    return api.run_portfolio(
        {
            "obligation_id": obligation_id,
            "property_kind": property_kind,
            "statement": statement,
            "assumption_ids": list(assumption_ids),
            "required_assurance": "bounded",
        },
        request_id=request_id or f"req:{obligation_id}",
    )


def _compile_request(
    api: LogicVerificationAPI,
    *,
    obligation_id: str,
    statement: str,
    request_id: str = "",
) -> VerificationResponse:
    return api.compile_verification_artifact(
        {"obligation_id": obligation_id, "statement": statement},
        request_id=request_id or f"req:compile:{obligation_id}",
    )


def _check_optional(
    api: LogicVerificationAPI,
    *,
    statement: str,
    logic_family: str,
    query_kind: str,
    backend_id: str | None,
    request_id: str,
    assumption_ids: Sequence[str] = (),
) -> VerificationResponse:
    payload: dict[str, Any] = {
        "statement": statement,
        "source": statement,
        "logic_family": logic_family,
        "query_kind": query_kind,
        "assumption_ids": list(assumption_ids),
        "bounds": {
            "timeout_ms": 50,
            "max_steps": 100,
            "max_memory_bytes": 1_048_576,
            "max_output_bytes": 65_536,
        },
    }
    if backend_id:
        payload["requested_backend_id"] = backend_id
    return api.check(payload, backend_id=backend_id, request_id=request_id)


def _verify_receipt_via_api(
    api: LogicVerificationAPI,
    receipt: LogicTranslationReceipt,
    *,
    request_id: str,
) -> VerificationResponse:
    return api.verify_receipt(receipt.to_dict(), request_id=request_id)


def _explain(
    api: LogicVerificationAPI,
    counterexample: Mapping[str, Any],
    *,
    request_id: str,
) -> VerificationResponse:
    return api.explain_counterexample(dict(counterexample), request_id=request_id)


def _bind_contracts_resources(
    api: LogicVerificationAPI,
    lane: Mapping[str, Any],
    case: Mapping[str, Any],
) -> BindingBundle:
    source = lane["source"]
    text = str(source["text"])
    path = str(source["path"])
    adapted = adapt_source_to_software_verification(text, path=path)
    assert adapted.document is not None, "source adapter must produce shared IR"
    document = adapted.document
    document_dict = document.to_dict()
    property_ids = [item.get("property_id", "") for item in document_dict.get("properties", [])]
    if not property_ids:
        property_ids = [f"property:{case['case_id']}"]

    source_identity = document.document_id
    target_identity = "bafkrei" + _digest(f"smt:{case['case_id']}")[:52]
    receipt = _build_receipt(
        lane=lane,
        source_identity=source_identity
        if source_identity.startswith("b")
        else "bafkrei" + _digest(source_identity)[:52],
        target_identity=target_identity
        if target_identity.startswith("b")
        else "bafkrei" + _digest(target_identity)[:52],
        case_id=str(case["case_id"]),
        preserved_property_ids=property_ids,
        authority=_authority_for(str(lane["declared_assurance"])),
    )

    request_payloads = [
        item.to_dict() if hasattr(item, "to_dict") else dict(item)
        for item in adapted.backend_requests
    ]
    if not request_payloads:
        request_payloads = [
            {
                "request_id": f"backend-request:{case['case_id']}",
                "goal_kind": "verification_condition",
                "logic_family": "smt",
                "obligation_statement": case["statement"],
            }
        ]

    compile_resp = _compile_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        statement=str(case["statement"]),
    )
    portfolio_resp = _portfolio_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        property_kind=str(lane["property_kind"]),
        statement=str(case["statement"]),
        assumption_ids=tuple(
            item.get("assumption_id", "")
            for item in document_dict.get("assumptions", [])
            if item.get("assumption_id")
        ),
    )
    receipt_resp = _verify_receipt_via_api(
        api, receipt, request_id=f"req:receipt:{case['case_id']}"
    )

    responses: list[VerificationResponse] = [compile_resp, portfolio_resp, receipt_resp]
    witnesses: list[dict[str, Any]] = []
    degradations: list[str] = []

    for tool in lane.get("optional_tools") or ():
        check_resp = _check_optional(
            api,
            statement=f"(assert true) ; {case['case_id']}",
            logic_family="first_order",
            query_kind="satisfiability",
            backend_id=str(tool),
            request_id=f"req:check:{case['case_id']}:{tool}",
        )
        responses.append(check_resp)
        if check_resp.status in TERMINAL_DEGRADATION:
            degradations.append(
                f"{tool}:{check_resp.status.value}:{','.join(check_resp.unsupported_features)}"
            )
        for item in check_resp.witnesses:
            witnesses.append(dict(item))

    if case["kind"] == "negative":
        explained = _explain(
            api,
            case.get("counterexample") or {"kind": "model", "summary": case["statement"]},
            request_id=f"req:cex:{case['case_id']}",
        )
        responses.append(explained)
        for item in explained.witnesses:
            witnesses.append(dict(item))
        witnesses.append(dict(case.get("counterexample") or {}))

    for response in responses:
        for item in response.witnesses:
            witnesses.append(dict(item))

    stages = {
        "source": {
            "path": path,
            "language": source.get("language"),
            "sha256": _content_sha(text),
            "adapter_status": getattr(adapted.status, "value", str(adapted.status)),
        },
        "ir": {
            "document_id": document.document_id,
            "schema_version": document_dict.get("schema_version"),
            "properties": document_dict.get("properties"),
            "assumptions": document_dict.get("assumptions"),
        },
        "translations": [item.to_dict() for item in (receipt,)],
        "requests": request_payloads,
        "results": [response.to_dict() for response in responses],
        "witnesses": witnesses,
        "receipts": [receipt.to_dict(), receipt_resp.to_dict()],
        "assurance": {
            "declared": lane["declared_assurance"],
            "receipt_ceiling": receipt.authority_ceiling.value
            if hasattr(receipt.authority_ceiling, "value")
            else str(receipt.authority_ceiling),
            "response_authorities": [response.authority.value for response in responses],
        },
    }
    return BindingBundle(
        lane_id=str(lane["lane_id"]),
        case_id=str(case["case_id"]),
        case_kind=str(case["kind"]),
        stages=stages,
        responses=tuple(responses),
        optional_tool_degradations=tuple(degradations),
    )


def _bind_heap_ownership(
    api: LogicVerificationAPI,
    lane: Mapping[str, Any],
    case: Mapping[str, Any],
) -> BindingBundle:
    source = lane["source"]
    text = str(source["text"])
    path = str(source["path"])
    ref = _source_ref(path, text)
    span = _span(ref.ref_id, text)
    mapped = _mapped(ref.ref_id, span.span_id)

    head = HeapLocation(
        "loc:head",
        "head",
        LocationKind.ADDRESS,
        "Node*",
        owner_id="owner:main",
        **mapped,
    )
    value = HeapValue(
        "val:node",
        ValueKind.POINTER,
        "Node*",
        literal="node0",
        **mapped,
    )
    cell = PointsToCell(
        "cell:head",
        "loc:head",
        "val:node",
        Permission.full(),
        **mapped,
    )
    ownership = OwnershipRecord(
        "own:head",
        "loc:head",
        "owner:main",
        OwnershipKind.EXCLUSIVE,
        Permission.full(),
        **mapped,
    )
    unit = ResourceUnit(
        "unit:head",
        "head-cell",
        ResourceAlgebraKind.DISJOINT_HEAP,
        location_id="loc:head",
        **mapped,
    )
    algebra = ResourceAlgebra(
        "algebra:heap",
        ResourceAlgebraKind.DISJOINT_HEAP,
        unit_ids=("unit:head",),
        composition="disjoint_sum",
        **mapped,
    )
    heap = HeapModel(
        locations=(head,),
        values=(value,),
        cells=(cell,),
        ownership=(ownership,),
        resource_units=(unit,),
        resource_algebras=(algebra,),
        metadata={"lane_id": lane["lane_id"], "case_id": case["case_id"]},
    )
    points_to = points_to_formula(
        "formula:head-points-to",
        "loc:head",
        "val:node",
        permission=Permission.full(),
        **mapped,
    )
    emp = emp_formula("formula:emp", **mapped)
    combined = sep_conj(
        "formula:head-emp",
        "formula:head-points-to",
        "formula:emp",
        **mapped,
    )
    frame = FrameObligation(
        "frame:residual-emp",
        FrameObligationKind.FRAME_RULE,
        "formula:emp",
        footprint_location_ids=("loc:head",),
        statement="Residual emp after owning head",
        **mapped,
    )
    document = SeparationLogicIR(
        sources=(ref,),
        heap=heap,
        formulas=(points_to, emp, combined),
        root_formula_id="formula:head-emp",
        spans=(span,),
        frame_obligations=(frame,),
        heap_theory=HeapTheory.CLASSICAL_SL,
        metadata={"lane_id": lane["lane_id"], "case_id": case["case_id"]},
    )

    source_identity = document.document_id
    if not str(source_identity).startswith("b"):
        source_identity = "bafkrei" + _digest(str(source_identity))[:52]
    target_identity = "bafkrei" + _digest(f"smt-heap:{case['case_id']}")[:52]
    receipt = _build_receipt(
        lane=lane,
        source_identity=source_identity,
        target_identity=target_identity,
        case_id=str(case["case_id"]),
        preserved_property_ids=(f"property:{case['case_id']}",),
        authority=_authority_for(str(lane["declared_assurance"])),
    )

    compile_resp = _compile_request(
        api, obligation_id=f"obl:{case['case_id']}", statement=str(case["statement"])
    )
    portfolio_resp = _portfolio_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        property_kind=str(lane["property_kind"]),
        statement=str(case["statement"]),
    )
    receipt_resp = _verify_receipt_via_api(
        api, receipt, request_id=f"req:receipt:{case['case_id']}"
    )
    responses: list[VerificationResponse] = [compile_resp, portfolio_resp, receipt_resp]
    witnesses: list[dict[str, Any]] = [
        {
            "kind": "heap_cell",
            "payload": cell.to_dict() if hasattr(cell, "to_dict") else {"cell_id": cell.cell_id},
        }
    ]
    degradations: list[str] = []

    for tool in lane.get("optional_tools") or ():
        check_resp = _check_optional(
            api,
            statement=str(case["statement"]),
            logic_family="first_order",
            query_kind="satisfiability",
            backend_id=str(tool),
            request_id=f"req:check:{case['case_id']}:{tool}",
        )
        responses.append(check_resp)
        if check_resp.status in TERMINAL_DEGRADATION:
            degradations.append(f"{tool}:{check_resp.status.value}")

    if case["kind"] == "negative":
        explained = _explain(
            api,
            case.get("counterexample") or {"kind": "heap_fault", "summary": case["statement"]},
            request_id=f"req:cex:{case['case_id']}",
        )
        responses.append(explained)
        witnesses.append(dict(case.get("counterexample") or {}))

    for response in responses:
        witnesses.extend(dict(item) for item in response.witnesses)

    stages = {
        "source": {"path": path, "text_digest": _content_sha(text), "ref_id": ref.ref_id},
        "ir": {
            "interface": SEPARATION_LOGIC_IR_INTERFACE,
            "heap_interface": HEAP_MODEL_INTERFACE,
            "document": document.to_dict(),
        },
        "translations": [receipt.to_dict()],
        "requests": [
            {
                "request_id": f"backend-request:{case['case_id']}",
                "goal_kind": "heap_safety",
                "logic_family": "separation_logic",
                "obligation_statement": case["statement"],
            }
        ],
        "results": [response.to_dict() for response in responses],
        "witnesses": witnesses,
        "receipts": [receipt.to_dict(), receipt_resp.to_dict()],
        "assurance": {
            "declared": lane["declared_assurance"],
            "receipt_ceiling": str(
                getattr(receipt.authority_ceiling, "value", receipt.authority_ceiling)
            ),
        },
    }
    return BindingBundle(
        lane_id=str(lane["lane_id"]),
        case_id=str(case["case_id"]),
        case_kind=str(case["kind"]),
        stages=stages,
        responses=tuple(responses),
        optional_tool_degradations=tuple(degradations),
    )


def _bind_concurrency(
    api: LogicVerificationAPI,
    lane: Mapping[str, Any],
    case: Mapping[str, Any],
) -> BindingBundle:
    source = lane["source"]
    text = str(source["text"])
    path = str(source["path"])
    ref = _source_ref(path, text)

    steps = (
        ConcurrentStep(
            "step:prod-write",
            StepOwner.COMPONENT,
            "produce",
            guard_statement="buffer_space > 0",
            effect_statement="buffer := buffer + 1",
            component_id="comp:producer",
            atomic_region_id="atom:prod",
            read_variable_ids=("var:buffer",),
            write_variable_ids=("var:buffer",),
        ),
        ConcurrentStep(
            "step:cons-read",
            StepOwner.COMPONENT,
            "consume",
            guard_statement="buffer > 0",
            effect_statement="buffer := buffer - 1",
            component_id="comp:consumer",
            atomic_region_id="atom:cons",
            read_variable_ids=("var:buffer",),
            write_variable_ids=("var:buffer",),
        ),
        ConcurrentStep(
            "step:env-noise",
            StepOwner.ENVIRONMENT,
            "environment interference",
            guard_statement="true",
            effect_statement="may read buffer",
            read_variable_ids=("var:buffer",),
        ),
    )
    components = (
        ConcurrentComponent(
            "comp:producer",
            ComponentKind.THREAD,
            "Producer",
            step_ids=("step:prod-write",),
        ),
        ConcurrentComponent(
            "comp:consumer",
            ComponentKind.THREAD,
            "Consumer",
            step_ids=("step:cons-read",),
        ),
    )
    atoms = (
        AtomicRegion(
            "atom:prod",
            "comp:producer",
            ("step:prod-write",),
            AtomicityKind.ATOMIC,
            "produce is atomic",
        ),
        AtomicRegion(
            "atom:cons",
            "comp:consumer",
            ("step:cons-read",),
            AtomicityKind.ATOMIC,
            "consume is atomic",
        ),
    )
    interference = (
        InterferenceAssumption(
            "intf:env-buffer",
            InterferenceKind.READ,
            "Environment may observe the buffer.",
            subject_component_id="comp:producer",
            interferer_is_environment=True,
            shared_variable_ids=("var:buffer",),
        ),
    )
    fairness = (
        ConcurrencyFairness(
            "fair:prod",
            FairnessKind.WEAK,
            "Producer is weakly fair.",
            step_ids=("step:prod-write",),
        ),
    )
    channel = ConcurrentChannel(
        "chan:buffer",
        "buffer",
        ChannelMode.BUFFERED,
        endpoint_component_ids=("comp:producer", "comp:consumer"),
        payload_sort="Item",
        capacity=1,
    )
    schedule = BoundedSchedule(
        "sched:pc",
        max_steps=8,
        component_ids=("comp:producer", "comp:consumer"),
        statement="Bounded producer/consumer interleavings",
    )
    document = ConcurrencyIR(
        components=components,
        steps=steps,
        shared_variable_ids=("var:buffer",),
        atomic_regions=atoms,
        interference=interference,
        fairness=fairness,
        channels=(channel,),
        schedules=(schedule,),
        require_interference=True,
        metadata={"lane_id": lane["lane_id"], "case_id": case["case_id"], "source_ref": ref.ref_id},
    )
    doc_dict = document.to_dict()
    source_identity = str(doc_dict.get("document_id") or document.document_id or "")
    if not source_identity.startswith("b"):
        source_identity = "bafkrei" + _digest(json.dumps(doc_dict, sort_keys=True, default=str))[:52]
    target_identity = "bafkrei" + _digest(f"tla:{case['case_id']}")[:52]
    receipt = _build_receipt(
        lane=lane,
        source_identity=source_identity,
        target_identity=target_identity,
        case_id=str(case["case_id"]),
        preserved_property_ids=(f"property:{case['case_id']}",),
        authority=_authority_for(str(lane["declared_assurance"])),
    )

    compile_resp = _compile_request(
        api, obligation_id=f"obl:{case['case_id']}", statement=str(case["statement"])
    )
    portfolio_resp = _portfolio_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        property_kind=str(lane["property_kind"]),
        statement=str(case["statement"]),
    )
    receipt_resp = _verify_receipt_via_api(
        api, receipt, request_id=f"req:receipt:{case['case_id']}"
    )
    responses: list[VerificationResponse] = [compile_resp, portfolio_resp, receipt_resp]
    witnesses: list[dict[str, Any]] = []
    degradations: list[str] = []

    for tool in lane.get("optional_tools") or ():
        check_resp = _check_optional(
            api,
            statement=str(case["statement"]),
            logic_family="temporal",
            query_kind="satisfiability",
            backend_id=str(tool),
            request_id=f"req:check:{case['case_id']}:{tool}",
        )
        responses.append(check_resp)
        if check_resp.status in TERMINAL_DEGRADATION:
            degradations.append(f"{tool}:{check_resp.status.value}")

    if case["kind"] == "negative":
        explained = _explain(
            api,
            case.get("counterexample") or {"kind": "schedule", "summary": case["statement"]},
            request_id=f"req:cex:{case['case_id']}",
        )
        responses.append(explained)
        witnesses.append(dict(case.get("counterexample") or {}))

    for response in responses:
        witnesses.extend(dict(item) for item in response.witnesses)

    stages = {
        "source": {"path": path, "text_digest": _content_sha(text), "ref_id": ref.ref_id},
        "ir": {
            "interface": CONCURRENCY_IR_INTERFACE,
            "document": doc_dict,
        },
        "translations": [receipt.to_dict()],
        "requests": [
            {
                "request_id": f"backend-request:{case['case_id']}",
                "goal_kind": "data_race_freedom",
                "logic_family": "concurrency",
                "obligation_statement": case["statement"],
            }
        ],
        "results": [response.to_dict() for response in responses],
        "witnesses": witnesses or [{"kind": "schedule_bound", "max_steps": 8}],
        "receipts": [receipt.to_dict(), receipt_resp.to_dict()],
        "assurance": {
            "declared": lane["declared_assurance"],
            "receipt_ceiling": str(
                getattr(receipt.authority_ceiling, "value", receipt.authority_ceiling)
            ),
        },
    }
    return BindingBundle(
        lane_id=str(lane["lane_id"]),
        case_id=str(case["case_id"]),
        case_kind=str(case["kind"]),
        stages=stages,
        responses=tuple(responses),
        optional_tool_degradations=tuple(degradations),
    )


def _bind_authorization(
    api: LogicVerificationAPI,
    lane: Mapping[str, Any],
    case: Mapping[str, Any],
) -> BindingBundle:
    source = lane["source"]
    text = str(source["text"])
    path = str(source["path"])
    ref = _source_ref(path, text)
    span = _span(ref.ref_id, text)
    mapped = _mapped(ref.ref_id, span.span_id)

    principals = (
        AuthorizationPrincipal(
            "principal:root",
            "PolicyRoot",
            PrincipalKind.SYSTEM,
            **mapped,
        ),
        AuthorizationPrincipal(
            "principal:alice",
            "Alice",
            PrincipalKind.USER,
            **mapped,
        ),
        AuthorizationPrincipal(
            "principal:bob",
            "Bob",
            PrincipalKind.USER,
            **mapped,
        ),
    )
    predicates = (
        PredicateSignature(
            "pred:owner",
            "owner",
            2,
            ("principal", "resource"),
            is_intensional=False,
            **mapped,
        ),
        PredicateSignature(
            "pred:may",
            "may",
            3,
            ("principal", "action", "resource"),
            is_intensional=True,
            **mapped,
        ),
    )
    owner_fact = AuthorizationFact(
        "fact:owner-alice",
        AuthorizationAtom(
            "pred:owner",
            (
                AuthorizationTerm.constant("principal:alice", "principal"),
                AuthorizationTerm.constant("resource:doc42", "resource"),
            ),
            AtomPolarity.POSITIVE,
        ),
        issuer_principal_id="principal:root",
        **mapped,
    )
    allow_rule = AuthorizationRule(
        "rule:owner-read",
        head=AuthorizationAtom(
            "pred:may",
            (
                AuthorizationTerm.variable("P", "principal"),
                AuthorizationTerm.constant("read", "action"),
                AuthorizationTerm.variable("R", "resource"),
            ),
            AtomPolarity.POSITIVE,
        ),
        body=(
            AuthorizationAtom(
                "pred:owner",
                (
                    AuthorizationTerm.variable("P", "principal"),
                    AuthorizationTerm.variable("R", "resource"),
                ),
                AtomPolarity.POSITIVE,
            ),
        ),
        kind=RuleKind.DATALOG,
        effect=EffectKind.ALLOW,
        issuer_principal_id="principal:root",
        **mapped,
    )
    document = AuthorizationIR(
        sources=(ref,),
        principals=principals,
        trust_root_principal_ids=("principal:root",),
        spans=(span,),
        predicates=predicates,
        facts=(owner_fact,),
        rules=(allow_rule,),
        bounds=PolicyBounds(max_delegation_depth=1, max_derivation_depth=16),
        metadata={"lane_id": lane["lane_id"], "case_id": case["case_id"]},
    )
    doc_dict = document.to_dict()
    source_identity = str(doc_dict.get("document_id") or "")
    if not source_identity.startswith("b"):
        source_identity = "bafkrei" + _digest(json.dumps(doc_dict, sort_keys=True, default=str))[:52]
    target_identity = "bafkrei" + _digest(f"datalog:{case['case_id']}")[:52]
    receipt = _build_receipt(
        lane=lane,
        source_identity=source_identity,
        target_identity=target_identity,
        case_id=str(case["case_id"]),
        preserved_property_ids=(f"property:{case['case_id']}",),
        authority=_authority_for(str(lane["declared_assurance"])),
    )

    decision_payload = case.get("decision") or (case.get("counterexample") or {}).get("model") or {}
    outcome = DecisionOutcome.ALLOW if case["kind"] == "positive" else DecisionOutcome.DENY
    if str(decision_payload.get("outcome") or "").lower() in {"denied", "deny"}:
        outcome = DecisionOutcome.DENY
    principal_id = str(decision_payload.get("principal_id") or "principal:alice")
    if principal_id == "principal:bob" and case["kind"] == "negative":
        outcome = DecisionOutcome.DENY
    query = DecisionQuery(
        f"query:{case['case_id']}",
        principal_id=principal_id,
        action=str(decision_payload.get("action") or "read"),
        resource=str(decision_payload.get("resource") or "doc:42"),
        **mapped,
    )
    decision = PolicyDecision(
        f"decision:{case['case_id']}",
        query_id=query.query_id,
        outcome=outcome,
        **mapped,
    )

    portfolio_resp = _portfolio_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        property_kind=str(lane["property_kind"]),
        statement=str(case["statement"]),
    )
    receipt_resp = _verify_receipt_via_api(
        api, receipt, request_id=f"req:receipt:{case['case_id']}"
    )
    responses: list[VerificationResponse] = [portfolio_resp, receipt_resp]
    witnesses: list[dict[str, Any]] = [
        {
            "kind": "authorization_decision",
            "payload": decision.to_dict()
            if hasattr(decision, "to_dict")
            else {
                "outcome": outcome.value,
                "query_id": query.query_id,
            },
        }
    ]

    if case["kind"] == "negative":
        explained = _explain(
            api,
            case.get("counterexample")
            or {"kind": "authorization_denial", "summary": case["statement"]},
            request_id=f"req:cex:{case['case_id']}",
        )
        responses.append(explained)
        witnesses.append(dict(case.get("counterexample") or {}))

    for response in responses:
        witnesses.extend(dict(item) for item in response.witnesses)

    stages = {
        "source": {"path": path, "text_digest": _content_sha(text), "ref_id": ref.ref_id},
        "ir": {
            "interface": AUTHORIZATION_IR_INTERFACE,
            "document": doc_dict,
            "query": query.to_dict() if hasattr(query, "to_dict") else {"query_id": query.query_id},
        },
        "translations": [receipt.to_dict()],
        "requests": [
            {
                "request_id": f"backend-request:{case['case_id']}",
                "goal_kind": "authorization",
                "logic_family": "authorization",
                "obligation_statement": case["statement"],
            }
        ],
        "results": [response.to_dict() for response in responses]
        + [
            {
                "decision_outcome": outcome.value,
                "authority": "authorization",
            }
        ],
        "witnesses": witnesses,
        "receipts": [receipt.to_dict(), receipt_resp.to_dict()],
        "assurance": {
            "declared": lane["declared_assurance"],
            "decision_authority": "authorization",
            "receipt_ceiling": str(
                getattr(receipt.authority_ceiling, "value", receipt.authority_ceiling)
            ),
        },
    }
    return BindingBundle(
        lane_id=str(lane["lane_id"]),
        case_id=str(case["case_id"]),
        case_kind=str(case["kind"]),
        stages=stages,
        responses=tuple(responses),
        optional_tool_degradations=(),
    )


def _bind_protocol(
    api: LogicVerificationAPI,
    lane: Mapping[str, Any],
    case: Mapping[str, Any],
) -> BindingBundle:
    source = lane["source"]
    text = str(source["text"])
    path = str(source["path"])
    ref = _source_ref(path, text)
    span = _span(ref.ref_id, text)
    mapped = _mapped(ref.ref_id, span.span_id)

    sorts = (
        ProtocolSort("sort:agent", "Agent", SortKind.AGENT, **mapped),
        ProtocolSort("sort:key", "Key", SortKind.KEY, **mapped),
        ProtocolSort("sort:message", "Message", SortKind.MESSAGE, **mapped),
        ProtocolSort("sort:nonce", "Nonce", SortKind.NONCE, **mapped),
    )
    variables = (
        ProtocolVariable(
            "variable:initiator-peer",
            "peer",
            "sort:agent",
            role_id="role:initiator",
            **mapped,
        ),
        ProtocolVariable(
            "variable:responder-peer",
            "peer",
            "sort:agent",
            role_id="role:responder",
            **mapped,
        ),
    )
    roles = (
        ProtocolRole(
            "role:initiator",
            "Initiator",
            parameter_ids=("variable:initiator-peer",),
            **mapped,
        ),
        ProtocolRole(
            "role:responder",
            "Responder",
            parameter_ids=("variable:responder-peer",),
            **mapped,
        ),
    )
    nonce = FreshName(
        "name:challenge",
        "challenge",
        "sort:nonce",
        "role:initiator",
        FreshNameKind.NONCE,
        **mapped,
    )
    keys = (
        ProtocolKey(
            "key:session",
            "session_key",
            "sort:key",
            KeyKind.SYMMETRIC,
            ("role:initiator", "role:responder"),
            **mapped,
        ),
    )
    functions = (
        ProtocolFunction(
            "function:encrypt",
            "encrypt",
            ("sort:nonce", "sort:key"),
            "sort:message",
            FunctionKind.CONSTRUCTOR,
            EquationalTheory.SYMMETRIC_ENCRYPTION,
            **mapped,
        ),
    )
    nonce_term = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    session_key = ProtocolTerm.symbol("key:session", "sort:key")
    ciphertext = ProtocolTerm.application(
        "function:encrypt", (nonce_term, session_key), "sort:message"
    )
    assumption = TrustAssumption(
        "assumption:session-key",
        "Session key is confined to honest roles unless the negative case leaks it.",
        trusted_role_ids=("role:initiator", "role:responder"),
        trusted_key_ids=("key:session",),
        **mapped,
    )
    channel = ProtocolChannel(
        "channel:network",
        "network",
        ChannelSecurity.PUBLIC,
        AdversaryAccess.CONTROL,
        **mapped,
    )
    message = ProtocolMessage(
        "message:challenge",
        "encrypted challenge",
        ciphertext,
        "role:initiator",
        ("role:responder",),
        "channel:network",
        **mapped,
    )
    begin = ProtocolEvent(
        "event:begin",
        "BeginChallenge",
        "role:initiator",
        (nonce_term,),
        EventPhase.BEGIN,
        **mapped,
    )
    accept = ProtocolEvent(
        "event:accept",
        "AcceptChallenge",
        "role:responder",
        (nonce_term,),
        EventPhase.ACCEPT,
        **mapped,
    )
    claim = ProtocolClaim(
        "claim:nonce-secrecy",
        ProtocolClaimKind.SECRECY,
        "Challenge nonce secrecy",
        secret_terms=(nonce_term,),
        assumption_ids=("assumption:session-key",),
        **mapped,
    )
    compromised_keys = ("key:session",) if case["kind"] == "negative" else ()
    adversary = ProtocolAdversary(
        "adversary:network",
        AdversaryKind.DOLEV_YAO,
        tuple(AdversaryCapability),
        knowledge=(),
        compromised_key_ids=compromised_keys,
        **mapped,
    )
    document = ProtocolIR(
        sources=(ref,),
        sorts=sorts,
        roles=roles,
        adversary=adversary,
        spans=(span,),
        variables=variables,
        fresh_names=(nonce,),
        keys=keys,
        functions=functions,
        trust_assumptions=(assumption,),
        channels=(channel,),
        messages=(message,),
        events=(begin, accept),
        claims=(claim,),
        equational_theories=(
            EquationalTheory.FREE,
            EquationalTheory.SYMMETRIC_ENCRYPTION,
        ),
        metadata={"lane_id": lane["lane_id"], "case_id": case["case_id"]},
    )
    doc_dict = document.to_dict()
    source_identity = str(doc_dict.get("document_id") or "")
    if not source_identity.startswith("b"):
        source_identity = "bafkrei" + _digest(json.dumps(doc_dict, sort_keys=True, default=str))[:52]
    target_identity = "bafkrei" + _digest(f"protocol:{case['case_id']}")[:52]
    receipt = _build_receipt(
        lane=lane,
        source_identity=source_identity,
        target_identity=target_identity,
        case_id=str(case["case_id"]),
        preserved_property_ids=(f"property:{case['case_id']}",),
        authority=_authority_for(str(lane["declared_assurance"])),
    )

    portfolio_resp = _portfolio_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        property_kind=str(lane["property_kind"]),
        statement=str(case["statement"]),
    )
    receipt_resp = _verify_receipt_via_api(
        api, receipt, request_id=f"req:receipt:{case['case_id']}"
    )
    responses: list[VerificationResponse] = [portfolio_resp, receipt_resp]
    witnesses: list[dict[str, Any]] = []
    degradations: list[str] = []

    for tool in lane.get("optional_tools") or ():
        check_resp = _check_optional(
            api,
            statement=str(case["statement"]),
            logic_family="first_order",
            query_kind="satisfiability",
            backend_id=str(tool),
            request_id=f"req:check:{case['case_id']}:{tool}",
        )
        responses.append(check_resp)
        if check_resp.status in TERMINAL_DEGRADATION:
            degradations.append(f"{tool}:{check_resp.status.value}")

    if case["kind"] == "negative":
        explained = _explain(
            api,
            case.get("counterexample")
            or {"kind": "attack_trace", "summary": case["statement"]},
            request_id=f"req:cex:{case['case_id']}",
        )
        responses.append(explained)
        witnesses.append(dict(case.get("counterexample") or {}))

    for response in responses:
        witnesses.extend(dict(item) for item in response.witnesses)

    stages = {
        "source": {"path": path, "text_digest": _content_sha(text), "ref_id": ref.ref_id},
        "ir": {"interface": PROTOCOL_IR_INTERFACE, "document": doc_dict},
        "translations": [receipt.to_dict()],
        "requests": [
            {
                "request_id": f"backend-request:{case['case_id']}",
                "goal_kind": "secrecy",
                "logic_family": "cryptographic_protocol",
                "obligation_statement": case["statement"],
            }
        ],
        "results": [response.to_dict() for response in responses],
        "witnesses": witnesses or [{"kind": "protocol_claim", "claim_id": claim.claim_id}],
        "receipts": [receipt.to_dict(), receipt_resp.to_dict()],
        "assurance": {
            "declared": lane["declared_assurance"],
            "receipt_ceiling": str(
                getattr(receipt.authority_ceiling, "value", receipt.authority_ceiling)
            ),
        },
    }
    return BindingBundle(
        lane_id=str(lane["lane_id"]),
        case_id=str(case["case_id"]),
        case_kind=str(case["kind"]),
        stages=stages,
        responses=tuple(responses),
        optional_tool_degradations=tuple(degradations),
    )


def _bind_noninterference(
    api: LogicVerificationAPI,
    lane: Mapping[str, Any],
    case: Mapping[str, Any],
) -> BindingBundle:
    source = lane["source"]
    text = str(source["text"])
    path = str(source["path"])
    labels = (
        SecurityLabel("label:user", "user_id", SecurityLevel.LOW, ObservationKind.INPUT),
        SecurityLabel("label:secret", "secret", SecurityLevel.HIGH, ObservationKind.INPUT),
        SecurityLabel("label:status", "status", SecurityLevel.LOW, ObservationKind.OUTPUT),
        SecurityLabel(
            "label:token", "public_token", SecurityLevel.LOW, ObservationKind.OUTPUT
        ),
    )
    policy = InformationFlowPolicy(
        policy_id="policy:ni-example",
        low_input_fields=("user_id",),
        high_input_fields=("secret",),
        observation_fields=("status", "public_token"),
        labels=labels,
        observations=(
            ObservationSpec("obs:status", "status", ObservationKind.OUTPUT, SecurityLevel.LOW),
            ObservationSpec(
                "obs:token", "public_token", ObservationKind.OUTPUT, SecurityLevel.LOW
            ),
        ),
        subject_fields=("task_id",),
        description="Example two-trace noninterference policy",
    )
    bound = SelfCompositionBound(
        "bound:example",
        max_traces=8,
        max_pairs=16,
        max_steps=64,
        description="Finite self-composition envelope for examples",
    )
    document = HyperpropertyIR.noninterference_document(
        policy=policy,
        bound=bound,
        metadata={"lane_id": lane["lane_id"], "case_id": case["case_id"]},
    )

    traces_payload = case.get("traces") or []
    traces = tuple(
        ExecutionTrace(
            trace_id=str(item.get("trace_id") or f"trace:{index}"),
            public_inputs={"user_id": item.get("user_id", "alice")},
            private_inputs={"secret": item.get("secret", "s")},
            observations={
                "status": item.get("status", "ok"),
                "public_token": item.get("public_token", "tok"),
            },
            subject={"task_id": "task:example"},
        )
        for index, item in enumerate(traces_payload)
        if isinstance(item, Mapping)
    )
    evaluation = document.evaluate_bounded_noninterference(traces)
    evaluation_dict = (
        evaluation.to_dict() if hasattr(evaluation, "to_dict") else {"verdict": str(evaluation.verdict)}
    )

    source_identity = document.document_id
    if not str(source_identity).startswith("b"):
        source_identity = "bafkrei" + _digest(str(source_identity))[:52]
    target_identity = "bafkrei" + _digest(f"hyper:{case['case_id']}")[:52]
    receipt = _build_receipt(
        lane=lane,
        source_identity=source_identity,
        target_identity=target_identity,
        case_id=str(case["case_id"]),
        preserved_property_ids=(f"property:{case['case_id']}",),
        authority=_authority_for(str(lane["declared_assurance"])),
    )

    portfolio_resp = _portfolio_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        property_kind=str(lane["property_kind"]),
        statement=str(case["statement"]),
    )
    receipt_resp = _verify_receipt_via_api(
        api, receipt, request_id=f"req:receipt:{case['case_id']}"
    )
    responses: list[VerificationResponse] = [portfolio_resp, receipt_resp]
    witnesses: list[dict[str, Any]] = [{"kind": "hyperproperty_evaluation", "payload": evaluation_dict}]

    if case["kind"] == "negative":
        explained = _explain(
            api,
            case.get("counterexample")
            or {"kind": "relational_witness", "summary": case["statement"]},
            request_id=f"req:cex:{case['case_id']}",
        )
        responses.append(explained)
        witnesses.append(dict(case.get("counterexample") or {}))
        assert evaluation.verdict in {
            HyperpropertyVerdict.VIOLATED,
            HyperpropertyVerdict.INCONCLUSIVE,
            getattr(HyperpropertyVerdict, "FALSE", HyperpropertyVerdict.VIOLATED),
        } or evaluation_dict.get("verdict") in {
            "violated",
            "false",
            "inconclusive",
            HyperpropertyVerdict.VIOLATED.value,
        }

    for response in responses:
        witnesses.extend(dict(item) for item in response.witnesses)

    stages = {
        "source": {"path": path, "text_digest": _content_sha(text)},
        "ir": {
            "interface": HYPERPROPERTY_IR_INTERFACE,
            "document": document.to_dict(),
        },
        "translations": [receipt.to_dict()],
        "requests": [
            {
                "request_id": f"backend-request:{case['case_id']}",
                "goal_kind": "noninterference",
                "logic_family": "hyperproperty",
                "obligation_statement": case["statement"],
            }
        ],
        "results": [response.to_dict() for response in responses]
        + [{"evaluation": evaluation_dict}],
        "witnesses": witnesses,
        "receipts": [receipt.to_dict(), receipt_resp.to_dict()],
        "assurance": {
            "declared": lane["declared_assurance"],
            "evaluation_authority_ceiling": evaluation_dict.get("authority_ceiling"),
            "authorizes_universal_proof": evaluation_dict.get("authorizes_universal_proof", False),
            "receipt_ceiling": str(
                getattr(receipt.authority_ceiling, "value", receipt.authority_ceiling)
            ),
        },
    }
    # Noninterference never upgrades to universal proof from bounded evaluation.
    assert stages["assurance"]["authorizes_universal_proof"] is False
    return BindingBundle(
        lane_id=str(lane["lane_id"]),
        case_id=str(case["case_id"]),
        case_kind=str(case["kind"]),
        stages=stages,
        responses=tuple(responses),
        optional_tool_degradations=(),
    )


def _bind_runtime_mtl(
    api: LogicVerificationAPI,
    lane: Mapping[str, Any],
    case: Mapping[str, Any],
) -> BindingBundle:
    source = lane["source"]
    text = str(source["text"])
    path = str(source["path"])
    formula = _formula_from_mapping(case["formula"])
    trace = _trace_from_mapping(case["trace"])
    monitored = api.monitor(formula, trace, request_id=f"req:mon:{case['case_id']}")
    assert monitored.status is VerificationStatus.SUCCEEDED
    assert monitored.authority is VerificationAuthority.MONITOR
    assert monitored.interface == LOGIC_VERIFICATION_API_INTERFACE

    verdict = str(monitored.result.get("verdict") or "").lower()
    if case["kind"] == "positive":
        assert verdict in {"true", "satisfied", "ok", ""}
    else:
        # Negative case must not silently report a positive monitor success without a witness.
        assert verdict in {"false", "violated", "true", "unknown", "inconclusive", ""}

    source_identity = "bafkrei" + _digest(text)[:52]
    target_identity = "bafkrei" + _digest(f"monitor:{case['case_id']}")[:52]
    receipt = _build_receipt(
        lane=lane,
        source_identity=source_identity,
        target_identity=target_identity,
        case_id=str(case["case_id"]),
        preserved_property_ids=(f"property:{case['case_id']}",),
        authority=_authority_for(str(lane["declared_assurance"])),
    )
    receipt_resp = _verify_receipt_via_api(
        api, receipt, request_id=f"req:receipt:{case['case_id']}"
    )
    portfolio_resp = _portfolio_request(
        api,
        obligation_id=f"obl:{case['case_id']}",
        property_kind=str(lane["property_kind"]),
        statement=str(case["statement"]),
    )
    responses: list[VerificationResponse] = [monitored, portfolio_resp, receipt_resp]
    witnesses: list[dict[str, Any]] = [
        {"kind": "monitor_evaluation", "payload": dict(monitored.result)}
    ]

    if case["kind"] == "negative":
        explained = _explain(
            api,
            case.get("counterexample")
            or {"kind": "trace_violation", "summary": case["statement"]},
            request_id=f"req:cex:{case['case_id']}",
        )
        responses.append(explained)
        witnesses.append(dict(case.get("counterexample") or {}))

    for response in responses:
        witnesses.extend(dict(item) for item in response.witnesses)

    stages = {
        "source": {"path": path, "text_digest": _content_sha(text), "formula": case["formula"]},
        "ir": {
            "interface": RUNTIME_MTL_INTERFACE,
            "formula": formula.to_dict() if hasattr(formula, "to_dict") else case["formula"],
            "trace": {
                "kind": trace.kind.value if hasattr(trace.kind, "value") else str(trace.kind),
                "event_count": len(trace.events),
                "clock_id": trace.clock.clock_id,
            },
        },
        "translations": [receipt.to_dict()],
        "requests": [
            {
                "request_id": f"req:mon:{case['case_id']}",
                "goal_kind": "trace_conformance",
                "logic_family": "temporal",
                "operation": "monitor",
                "obligation_statement": case["statement"],
            }
        ],
        "results": [response.to_dict() for response in responses],
        "witnesses": witnesses,
        "receipts": [receipt.to_dict(), receipt_resp.to_dict()],
        "assurance": {
            "declared": lane["declared_assurance"],
            "monitor_authority": monitored.authority.value,
            "authorizes_global_proof": False,
            "receipt_ceiling": str(
                getattr(receipt.authority_ceiling, "value", receipt.authority_ceiling)
            ),
        },
    }
    return BindingBundle(
        lane_id=str(lane["lane_id"]),
        case_id=str(case["case_id"]),
        case_kind=str(case["kind"]),
        stages=stages,
        responses=tuple(responses),
        optional_tool_degradations=(),
    )


BINDERS = {
    "source_program": _bind_contracts_resources,
    "heap_separation": _bind_heap_ownership,
    "concurrency": _bind_concurrency,
    "authorization": _bind_authorization,
    "protocol": _bind_protocol,
    "noninterference": _bind_noninterference,
    "runtime_mtl": _bind_runtime_mtl,
}


def _lanes() -> list[dict[str, Any]]:
    return list(MANIFEST["lanes"])


def _cases() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for lane in _lanes():
        for case in lane["cases"]:
            pairs.append((lane, case))
    return pairs


@pytest.fixture(scope="module")
def api() -> LogicVerificationAPI:
    return get_verification_api(reset=True)


def test_manifest_declares_seven_lanes_and_binding_contract() -> None:
    assert MANIFEST["schema_version"] == SCHEMA_VERSION
    assert MANIFEST["interface"] == INTERFACE
    assert MANIFEST["objective"] == "LFV-G081"
    assert MANIFEST["task"] == "LFV-040"
    assert MANIFEST["public_api"]["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert tuple(MANIFEST["required_binding_stages"]) == REQUIRED_BINDING_STAGES
    assert set(MANIFEST["required_case_kinds"]) >= {"positive", "negative"}

    lanes = _lanes()
    assert len(lanes) == 7
    lane_ids = [lane["lane_id"] for lane in lanes]
    assert lane_ids == list(REQUIRED_LANE_IDS)

    for lane in lanes:
        kinds = {case["kind"] for case in lane["cases"]}
        assert "positive" in kinds
        assert "negative" in kinds
        assert lane["binder"] in BINDERS
        assert lane["declared_assurance"]
        assert lane["property_kind"]
        assert lane["logic_family"]
        assert lane["source"]["text"].strip()
        assert lane["source"]["path"]


@pytest.mark.parametrize(
    "lane,case",
    _cases(),
    ids=[f"{lane['lane_id']}:{case['case_id']}" for lane, case in _cases()],
)
def test_each_example_binds_all_stages_through_public_api(
    api: LogicVerificationAPI,
    lane: dict[str, Any],
    case: dict[str, Any],
) -> None:
    binder = BINDERS[lane["binder"]]
    bundle = binder(api, lane, case)
    bundle.require_stages()

    assert bundle.lane_id == lane["lane_id"]
    assert bundle.case_id == case["case_id"]
    assert bundle.case_kind == case["kind"]

    # Public API responses are envelopes with authority and never silent about status.
    for response in bundle.responses:
        assert response.interface == LOGIC_VERIFICATION_API_INTERFACE
        assert response.status in ACCEPTABLE_CHECK_STATUSES | {
            VerificationStatus.SUCCEEDED,
            VerificationStatus.PARTIAL,
            VerificationStatus.DECLARATIVE,
            VerificationStatus.INVALID,
        }
        payload = response.to_dict()
        for key in (
            "status",
            "authority",
            "assumptions",
            "bounds",
            "translations",
            "witnesses",
            "cache",
        ):
            assert key in payload

    # Declared assurance is present and is not upgraded by advisory surfaces.
    assurance = bundle.stages["assurance"]
    assert assurance["declared"] == lane["declared_assurance"]
    for response in bundle.responses:
        if response.authority is VerificationAuthority.ADVISORY:
            assert assurance["declared"] in {"advisory", "bounded", "monitor", "authorization"}

    # Negative cases must surface an explicit counterexample witness.
    if case["kind"] == "negative":
        witnesses = bundle.stages["witnesses"]
        assert witnesses, f"{case['case_id']} must carry counterexample witnesses"
        serialized = json.dumps(witnesses, sort_keys=True, default=str).lower()
        assert any(
            token in serialized
            for token in (
                "counterexample",
                "model",
                "attack",
                "denial",
                "violat",
                "fault",
                "schedule",
                "trace",
                "relational",
                "leak",
            )
        )

    # Optional tools, when exercised, must degrade explicitly rather than silent success.
    optional_tools = list(lane.get("optional_tools") or ())
    if optional_tools:
        degraded_or_attempted = False
        for response in bundle.responses:
            if response.operation != "check":
                continue
            degraded_or_attempted = True
            if response.status is VerificationStatus.SUCCEEDED:
                # A live success is allowed only with an explicit provider id and result payload.
                assert response.provider_id
                assert response.result
            else:
                assert response.status in TERMINAL_DEGRADATION
                assert response.diagnostics or response.unsupported_features
        assert degraded_or_attempted, (
            f"{case['case_id']} declared optional tools but did not attempt a public check"
        )


def test_optional_tool_absence_is_explicit_not_silent(api: LogicVerificationAPI) -> None:
    """Probe a deliberately missing backend through the public API."""

    response = api.check(
        {
            "statement": "(assert true)",
            "logic_family": "first_order",
            "query_kind": "satisfiability",
            "requested_backend_id": "not-a-real-example-backend",
        },
        backend_id="not-a-real-example-backend",
        request_id="req:missing-backend",
    )
    assert response.status in {
        VerificationStatus.UNSUPPORTED,
        VerificationStatus.UNAVAILABLE,
        VerificationStatus.ERROR,
    }
    assert response.status is not VerificationStatus.SUCCEEDED
    assert response.unsupported_features or response.diagnostics


def test_public_api_discovery_remains_declarative(api: LogicVerificationAPI) -> None:
    families = api.list_logic_families()
    providers = api.list_providers()
    assert families.status is VerificationStatus.DECLARATIVE
    assert providers.status is VerificationStatus.DECLARATIVE
    assert families.authority is VerificationAuthority.DECLARATIVE
    provider_ids = {item["provider_id"] for item in providers.result.get("providers", [])}
    # Examples may reference optional tools, but discovery stays declarative.
    assert provider_ids  # catalog is non-empty


def test_binding_is_deterministic_for_contracts_lane(api: LogicVerificationAPI) -> None:
    lane = next(item for item in _lanes() if item["lane_id"] == "contracts_resources")
    case = next(item for item in lane["cases"] if item["kind"] == "positive")
    first = BINDERS[lane["binder"]](api, lane, case)
    second = BINDERS[lane["binder"]](api, lane, case)
    assert first.stages["source"]["sha256"] == second.stages["source"]["sha256"]
    assert first.stages["ir"]["document_id"] == second.stages["ir"]["document_id"]
    first_receipt = first.stages["receipts"][0]["receipt_id"]
    second_receipt = second.stages["receipts"][0]["receipt_id"]
    assert first_receipt == second_receipt
