"""Consolidated replayable compiler pipeline over the canonical authority.

``TypedDeonticCanonicalCompiler`` remains the measured L1 constructor.  This
module is the single pipeline API: it reproduces source selection, typed
family parse, elaboration, formalization, the available DomainLogicSlice
adapter, the typed bridge, and the canonical target with explicit stage
identities.  Parallel LegalIR surfaces delegate here instead of inventing a
second compiler.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from ipfs_datasets_py.logic.bridge.canonical import (
    wrap_canonical_ir,
    wrap_compiler_result,
    wrap_formalization_artifact,
)
from ipfs_datasets_py.logic.legal_ir.canonical_compiler import (
    MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID,
    TYPED_DEONTIC_COMPILER_CONFIG_CID,
    TypedDeonticCanonicalCompiler,
    _load_deontic_components,
    _project_legal_norms,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_ROUNDTRIP_IR_INTERFACE,
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    SELECTED_CONSTRUCTOR_INTERFACE,
    CanonicalContractError,
    CanonicalRoundTripIR,
    CompilerRequest,
    CompilerResult,
    OperationStatus,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json


CANONICAL_COMPILER_PIPELINE_INTERFACE: Final = "CanonicalCompilerPipeline@1"
CANONICAL_SOURCE_SELECTION_INTERFACE: Final = "CanonicalSourceSelection@1"
CANONICAL_TYPED_FAMILY_PARSE_INTERFACE: Final = "TypedDeonticFamilyParse@1"
CANONICAL_ELABORATION_INTERFACE: Final = "CanonicalElaboration@1"
CANONICAL_FORMALIZATION_ADAPTER_INTERFACE: Final = "CanonicalFormalizationAdapter@1"
CANONICAL_DOMAIN_SLICE_ADAPTER_INTERFACE: Final = "CanonicalDomainSliceAdapter@1"
CANONICAL_TYPED_BRIDGE_ADAPTER_INTERFACE: Final = "CanonicalTypedBridgeAdapter@1"

CANONICAL_COMPILER_STAGE_IDS: Final = (
    "source_selection",
    "typed_family_parse",
    "elaboration",
    "formalization",
    "domain_slice_adapter",
    "bridge",
    "target",
)

_PIPELINE_STAGE_TABLE: Final = (
    {
        "stage_id": "source_selection",
        "interface": CANONICAL_SOURCE_SELECTION_INTERFACE,
        "authority": False,
    },
    {
        "stage_id": "typed_family_parse",
        "interface": CANONICAL_TYPED_FAMILY_PARSE_INTERFACE,
        "authority": False,
    },
    {
        "stage_id": "elaboration",
        "interface": CANONICAL_ELABORATION_INTERFACE,
        "authority": False,
    },
    {
        "stage_id": "formalization",
        "interface": CANONICAL_FORMALIZATION_ADAPTER_INTERFACE,
        "authority": False,
    },
    {
        "stage_id": "domain_slice_adapter",
        "interface": CANONICAL_DOMAIN_SLICE_ADAPTER_INTERFACE,
        "authority": False,
    },
    {
        "stage_id": "bridge",
        "interface": CANONICAL_TYPED_BRIDGE_ADAPTER_INTERFACE,
        "authority": False,
    },
    {
        "stage_id": "target",
        "interface": SELECTED_CONSTRUCTOR_INTERFACE,
        "authority": True,
    },
)

CANONICAL_COMPILER_STAGE_INTERFACES: Final[Mapping[str, str]] = MappingProxyType(
    {item["stage_id"]: item["interface"] for item in _PIPELINE_STAGE_TABLE}
)


def compiler_stage_identities() -> tuple[dict[str, object], ...]:
    """Return the frozen ordered pipeline stage identity table."""

    return tuple(dict(item) for item in _PIPELINE_STAGE_TABLE)


def compiler_pipeline_configuration() -> dict[str, object]:
    """Return a detached JSON copy of the frozen pipeline identity table."""

    return {
        "interface": CANONICAL_COMPILER_PIPELINE_INTERFACE,
        "stages": [dict(item) for item in _PIPELINE_STAGE_TABLE],
    }


CANONICAL_COMPILER_PIPELINE_CID: Final = cid_for_dag_json(compiler_pipeline_configuration())
"""DAG-JSON CID of the detached pipeline identity table."""


def _stage_config_cid(stage_id: str) -> str:
    return cid_for_dag_json(
        {
            "interface": CANONICAL_COMPILER_STAGE_INTERFACES[stage_id],
            "pipeline_cid": CANONICAL_COMPILER_PIPELINE_CID,
            "stage_id": stage_id,
        }
    )


def _sha256_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _norm_view(norm: object) -> dict[str, object]:
    to_dict = getattr(norm, "to_dict", None)
    data = to_dict() if callable(to_dict) else {}
    if not isinstance(data, Mapping):
        data = {}
    return {
        "action": _clean_text(data.get("action")),
        "action_object": _clean_text(data.get("action_object")),
        "action_verb": _clean_text(data.get("action_verb")),
        "actor": _clean_text(data.get("actor")),
        "modality": _clean_text(data.get("modality")),
        "norm_type": _clean_text(data.get("norm_type")),
    }


@dataclass(frozen=True, slots=True)
class CompilerStageRecord:
    """Replayable identity of one completed compiler pipeline stage."""

    stage_id: str
    interface: str
    input_cid: str
    output_cid: str
    config_cid: str
    status: str
    unsupported: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.stage_id not in CANONICAL_COMPILER_STAGE_INTERFACES:
            raise CanonicalContractError(f"unknown compiler pipeline stage {self.stage_id!r}")
        if self.interface != CANONICAL_COMPILER_STAGE_INTERFACES[self.stage_id]:
            raise CanonicalContractError(
                f"stage {self.stage_id!r} interface does not match the frozen table"
            )
        if self.config_cid != _stage_config_cid(self.stage_id):
            raise CanonicalContractError(
                f"stage {self.stage_id!r} config CID does not match the frozen table"
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "config_cid": self.config_cid,
            "input_cid": self.input_cid,
            "interface": self.interface,
            "output_cid": self.output_cid,
            "stage_id": self.stage_id,
            "status": self.status,
            "unsupported": [dict(item) for item in self.unsupported],
        }

    @property
    def identity_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload)

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "identity_cid": self.identity_cid}


@dataclass(frozen=True, slots=True)
class CompilerPipelineResult:
    """Authority compiler result plus the ordered replayable stage records."""

    result: CompilerResult
    stages: tuple[CompilerStageRecord, ...]
    pipeline_cid: str = CANONICAL_COMPILER_PIPELINE_CID

    def stage(self, stage_id: str) -> CompilerStageRecord:
        for item in self.stages:
            if item.stage_id == stage_id:
                return item
        raise CanonicalContractError(f"pipeline did not complete stage {stage_id!r}")

    def to_dict(self) -> dict[str, object]:
        return {
            "pipeline_cid": self.pipeline_cid,
            "result": self.result.to_dict(),
            "stages": [item.to_dict() for item in self.stages],
        }


def _stage_record(
    stage_id: str,
    *,
    input_cid: str,
    output_payload: Mapping[str, object],
    status: str = "success",
    unsupported: Sequence[Mapping[str, object]] = (),
) -> CompilerStageRecord:
    return CompilerStageRecord(
        stage_id=stage_id,
        interface=CANONICAL_COMPILER_STAGE_INTERFACES[stage_id],
        input_cid=input_cid,
        output_cid=cid_for_dag_json(dict(output_payload)),
        config_cid=_stage_config_cid(stage_id),
        status=status,
        unsupported=tuple(dict(item) for item in unsupported),
    )


def pipeline_trace_payload(stages: Sequence[CompilerStageRecord]) -> dict[str, object]:
    """Return the detached pipeline-trace object."""

    return {
        "interface": CANONICAL_COMPILER_PIPELINE_INTERFACE,
        "pipeline_cid": CANONICAL_COMPILER_PIPELINE_CID,
        "stages": [item.to_dict() for item in stages],
    }


def _source_selection_payload(request: CompilerRequest) -> dict[str, object]:
    return {
        "end": len(request.source_text),
        "source_cid": request.source_cid,
        "spans": [
            {
                "end": len(request.source_text),
                "kind": "document",
                "start": 0,
            }
        ],
        "start": 0,
    }


def _formalization_payload(
    request: CompilerRequest,
    canonical_ir: CanonicalRoundTripIR,
) -> dict[str, object]:
    digest = _sha256_digest(canonical_ir.to_dict())
    return {
        "assumptions": [],
        "declaration_digest": digest,
        "declaration_id": f"canonical:{request.request_cid}",
        "digest": digest,
        "domain": "deontic",
        "formulas": [
            {"formula_id": rule.rule_cid, "view_id": "canonical.primary"}
            for rule in canonical_ir.rules
        ],
        "sample_id": request.request_id,
        "schema_version": "formalization-artifact/v1",
        "source_map": {
            "sources": [
                {
                    "content_cid": request.source_cid,
                    "ref_id": "source:canonical",
                    "source_revision": "",
                    "source_uri": "",
                }
            ]
        },
    }


def _parse_norms(request: CompilerRequest) -> tuple[tuple[object, ...], str]:
    converter_type, legal_norm_type = _load_deontic_components()
    converter = converter_type(
        use_cache=False,
        use_ipfs=False,
        use_ml=False,
        enable_monitoring=False,
        document_type="general",
    )
    converted = converter.convert(request.source_text, use_cache=False)
    output = getattr(converted, "output", None)
    if output is None:
        return (), "empty_output"
    elements = list(getattr(output, "parser_elements", ()) or ())
    if not elements:
        return (), "empty_output"
    norms = tuple(legal_norm_type.from_parser_element(element) for element in elements)
    return norms, "success"


def _success_downstream(
    request: CompilerRequest,
    result: CompilerResult,
    *,
    previous_output_cid: str,
) -> tuple[CompilerStageRecord, ...]:
    canonical_ir = result.canonical_ir
    if canonical_ir is None:
        raise CanonicalContractError("successful compiler result requires canonical IR")

    formal_payload = _formalization_payload(request, canonical_ir)
    formal_bridge = wrap_formalization_artifact(
        formal_payload,
        family_id="deontic",
        adapter_name="typed_deontic_canonical_compiler",
    )
    formal_stage = _stage_record(
        "formalization",
        input_cid=previous_output_cid,
        output_payload={
            "bridge_cid": formal_bridge.bridge_cid,
            "declaration_id": formal_payload["declaration_id"],
            "digest": formal_payload["digest"],
            "formula_ids": [rule.rule_cid for rule in canonical_ir.rules],
        },
    )

    slice_bridge = wrap_canonical_ir(
        canonical_ir,
        family_id="deontic",
        source_text=request.source_text,
        provenance={
            "compiler_config_cid": TYPED_DEONTIC_COMPILER_CONFIG_CID,
            "measured_adapter_raw_cid": MEASURED_TYPED_DEONTIC_ADAPTER_RAW_CID,
            "request_cid": request.request_cid,
            "source_contract": CANONICAL_ROUNDTRIP_IR_INTERFACE,
        },
        adapter_name="typed_deontic_canonical_compiler",
        metadata={"wrapped": "canonical_compiler_pipeline"},
        project_slice=True,
    )
    slice_role = slice_bridge.domain_logic_slice
    if slice_role is None:
        raise CanonicalContractError("domain slice adapter did not emit a slice role")
    slice_stage = _stage_record(
        "domain_slice_adapter",
        input_cid=formal_stage.output_cid,
        output_payload=slice_role.to_dict(),
        unsupported=(
            ()
            if slice_role.unsupported is None
            else (slice_role.unsupported.to_dict(),)
        ),
    )

    result_bridge = wrap_compiler_result(
        result,
        family_id="deontic",
        source_text=request.source_text,
        adapter_name="typed_deontic_canonical_compiler",
    )
    bridge_stage = _stage_record(
        "bridge",
        input_cid=slice_stage.output_cid,
        output_payload={
            "bridge_cid": result_bridge.bridge_cid,
            "family_id": result_bridge.family_identity.family_id,
            "slice_bridge_cid": slice_bridge.bridge_cid,
            "unsupported_constructs": [
                item.to_dict() for item in result_bridge.unsupported_constructs
            ],
        },
        unsupported=tuple(item.to_dict() for item in result_bridge.unsupported_constructs),
    )

    target_stage = _stage_record(
        "target",
        input_cid=request.request_cid,
        output_payload={
            "canonical_ir": canonical_ir.to_dict(),
            "compiler_interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
            "ir_cid": canonical_ir.ir_cid,
            "result_cid": result.result_cid,
        },
    )
    return (formal_stage, slice_stage, bridge_stage, target_stage)


def compile_canonical_pipeline(request: CompilerRequest) -> CompilerPipelineResult:
    """Run the consolidated pipeline, delegating L1 to the measured compiler."""

    if not isinstance(request, CompilerRequest):
        raise CanonicalContractError(
            "request must be CompilerRequest; unbound input is rejected"
        )

    stages: list[CompilerStageRecord] = []
    selection = _stage_record(
        "source_selection",
        input_cid=request.request_cid,
        output_payload=_source_selection_payload(request),
    )
    stages.append(selection)

    result = TypedDeonticCanonicalCompiler().compile(request)

    try:
        norms, parse_status = _parse_norms(request)
    except Exception:
        norms, parse_status = (), "component_failed"
    parse_stage = _stage_record(
        "typed_family_parse",
        input_cid=selection.output_cid,
        output_payload={
            "norm_count": len(norms),
            "norms": [_norm_view(norm) for norm in norms],
            "status": parse_status,
        },
        status=parse_status,
    )
    stages.append(parse_stage)

    if norms:
        projected, unsupported_records = _project_legal_norms(
            norms,
            request.atom_vocabulary,
        )
        elaboration = _stage_record(
            "elaboration",
            input_cid=parse_stage.output_cid,
            output_payload={
                "rule_cids": [item.rule.rule_cid for item in projected],
                "rules": [item.rule.to_dict() for item in projected],
                "unsupported": [
                    {
                        "code": item.code,
                        "message": item.message,
                        "norm_index": item.norm_index,
                    }
                    for item in unsupported_records
                ],
            },
            unsupported=[
                {
                    "code": item.code,
                    "message": item.message,
                    "norm_index": item.norm_index,
                }
                for item in unsupported_records
            ],
        )
        stages.append(elaboration)
        previous = elaboration.output_cid
    else:
        previous = parse_stage.output_cid

    if result.status is OperationStatus.SUCCESS and result.canonical_ir is not None:
        stages.extend(
            _success_downstream(
                request,
                result,
                previous_output_cid=previous,
            )
        )

    return CompilerPipelineResult(result, tuple(stages))


def replay_compiler_pipeline(request: CompilerRequest) -> CompilerPipelineResult:
    """Re-execute the measured pipeline; identical to a fresh compile."""

    return compile_canonical_pipeline(request)


def replay_compiler_stage(
    stage_id: str,
    request: CompilerRequest,
) -> CompilerStageRecord:
    """Re-run the full pipeline and return one completed stage record."""

    if stage_id not in CANONICAL_COMPILER_STAGE_INTERFACES:
        raise CanonicalContractError(f"unknown compiler pipeline stage {stage_id!r}")
    return compile_canonical_pipeline(request).stage(stage_id)


__all__ = [
    "CANONICAL_COMPILER_PIPELINE_CID",
    "CANONICAL_COMPILER_PIPELINE_INTERFACE",
    "CANONICAL_COMPILER_STAGE_IDS",
    "CANONICAL_COMPILER_STAGE_INTERFACES",
    "CANONICAL_DOMAIN_SLICE_ADAPTER_INTERFACE",
    "CANONICAL_ELABORATION_INTERFACE",
    "CANONICAL_FORMALIZATION_ADAPTER_INTERFACE",
    "CANONICAL_SOURCE_SELECTION_INTERFACE",
    "CANONICAL_TYPED_BRIDGE_ADAPTER_INTERFACE",
    "CANONICAL_TYPED_FAMILY_PARSE_INTERFACE",
    "CompilerPipelineResult",
    "CompilerStageRecord",
    "compile_canonical_pipeline",
    "compiler_pipeline_configuration",
    "compiler_stage_identities",
    "pipeline_trace_payload",
    "replay_compiler_pipeline",
    "replay_compiler_stage",
]
