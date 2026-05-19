"""Bridge adapter registry for logic optimizer routing."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class LogicBridgeSpec:
    """Static description of one legal IR bridge adapter."""

    name: str
    target_component: str
    adapter_module: str
    adapter_class: str
    description: str
    roles: tuple[str, ...]
    source_view: str
    target_views: tuple[str, ...]
    loss_names: tuple[str, ...] = ()
    required_submodules: tuple[str, ...] = ()
    ast_scope: str = ""
    implemented: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_class": self.adapter_class,
            "adapter_module": self.adapter_module,
            "ast_scope": self.ast_scope,
            "description": self.description,
            "implemented": self.implemented,
            "loss_names": list(self.loss_names),
            "name": self.name,
            "required_submodules": list(self.required_submodules),
            "roles": list(self.roles),
            "source_view": self.source_view,
            "target_component": self.target_component,
            "target_views": list(self.target_views),
        }


_SPECS: tuple[LogicBridgeSpec, ...] = (
    LogicBridgeSpec(
        name="modal_frame_logic",
        target_component="modal.frame_logic",
        adapter_module="ipfs_datasets_py.logic.bridge.modal_frame_logic",
        adapter_class="ModalFrameLogicBridgeAdapter",
        description=(
            "spaCy legal text -> modal IR with embedded frame logic, "
            "Neo4j-compatible graph projection, and modal prover compilation gate."
        ),
        roles=("legal_ir", "modal", "frame_logic", "kg", "prover", "loss"),
        source_view="legal_text",
        target_views=("modal_ir", "frame_logic", "neo4j_graph_data"),
        loss_names=(
            "cosine_similarity",
            "cosine_loss",
            "cross_entropy_loss",
            "reconstruction_loss",
            "text_reconstruction_loss",
            "frame_ranking_loss",
            "flogic_similarity_loss",
            "symbolic_validity_penalty",
        ),
        required_submodules=("modal", "flogic", "knowledge_graphs"),
        ast_scope="frame_logic",
    ),
    LogicBridgeSpec(
        name="deontic_norms",
        target_component="deontic.ir",
        adapter_module="ipfs_datasets_py.logic.bridge.deontic_norms",
        adapter_class="DeonticNormsBridgeAdapter",
        description="Legal text -> deontic LegalNormIR, frame records, prover syntax, and bridge metrics.",
        roles=("legal_ir", "deontic", "frame_logic", "prover_input", "loss"),
        source_view="legal_text",
        target_views=(
            "deontic_ir",
            "deontic_formula_records",
            "deontic_prover_syntax",
            "deontic_parser_metrics",
            "deontic_parser_capability",
            "deontic_decoder_reconstructions",
            "deontic_proof_obligations",
            "deontic_repair_queue",
            "deontic_reconstruction_slot_loss",
            "deontic_ir_slot_provenance",
            "deontic_phase8_quality",
            "deontic_graph",
            "frame_logic",
            "neo4j_graph_data",
        ),
        loss_names=(
            "cosine_similarity",
            "cosine_loss",
            "reconstruction_loss",
            "text_reconstruction_loss",
            "symbolic_validity_penalty",
            "deontic_bridge_evaluation_failure_loss",
            "deontic_graph_failure_penalty",
            "deontic_proof_failure_ratio",
            "deontic_decoder_requires_validation_rate",
            "deontic_decoder_slot_loss",
            "deontic_graph_build_error_loss",
            "deontic_graph_conflict_loss",
            "deontic_graph_source_gap_loss",
            "deontic_ir_slot_provenance_loss",
            "deontic_phase8_quality_incomplete_loss",
            "deontic_quality_requires_validation_loss",
            "deontic_repair_queue_rate",
            "deontic_repair_required_rate",
        ),
        required_submodules=("deontic",),
        ast_scope="deontic",
    ),
    LogicBridgeSpec(
        name="fol_tdfol",
        target_component="TDFOL.prover",
        adapter_module="ipfs_datasets_py.logic.bridge.fol_tdfol",
        adapter_class="FolTdfolBridgeAdapter",
        description="Legal text -> FOL/TDFOL formulas, proof obligations, and parser proof gate.",
        roles=("legal_ir", "fol", "tdfol", "temporal", "prover"),
        source_view="legal_text",
        target_views=(
            "tdfol_formula",
            "proof_obligations",
            "frame_logic",
            "neo4j_graph_data",
        ),
        loss_names=(
            "tdfol_no_formula_loss",
            "tdfol_parse_failure_ratio",
        ),
        required_submodules=("fol", "TDFOL"),
        ast_scope="tdfol",
    ),
    LogicBridgeSpec(
        name="cec_dcec",
        target_component="CEC.native",
        adapter_module="ipfs_datasets_py.logic.bridge.cec_dcec",
        adapter_class="CecDcecBridgeAdapter",
        description="Legal text -> CEC/DCEC event formulas, validation trace, and graph records.",
        roles=("legal_ir", "cec", "event_calculus", "prover"),
        source_view="legal_text",
        target_views=(
            "cec_events",
            "dcec_formula",
            "proof_trace",
            "frame_logic",
            "neo4j_graph_data",
        ),
        loss_names=(
            "cec_dcec_no_formula_loss",
            "cec_dcec_validation_failure_ratio",
        ),
        required_submodules=("CEC",),
        ast_scope="cec",
    ),
    LogicBridgeSpec(
        name="external_prover_router",
        target_component="external_provers.router",
        adapter_module="ipfs_datasets_py.logic.bridge.external_prover_router",
        adapter_class="ExternalProverRouterBridgeAdapter",
        description="TDFOL formulas -> lazy external prover-router diagnostics and proof gate.",
        roles=("prover", "installer", "router"),
        source_view="formal_formula",
        target_views=("prover_formulas", "frame_logic", "neo4j_graph_data"),
        loss_names=(
            "external_prover_failure_ratio",
            "external_prover_unavailable_loss",
        ),
        required_submodules=("external_provers",),
        ast_scope="external_provers",
    ),
)

_SPECS_BY_NAME: Mapping[str, LogicBridgeSpec] = {spec.name: spec for spec in _SPECS}
DEFAULT_LEGAL_IR_BRIDGE_NAMES: tuple[str, ...] = tuple(
    spec.name for spec in _SPECS if spec.implemented
)


def logic_bridge_specs(*, implemented_only: bool = False) -> tuple[LogicBridgeSpec, ...]:
    """Return bridge adapter specs in deterministic order."""

    return tuple(
        spec
        for spec in _SPECS
        if not implemented_only or spec.implemented
    )


def logic_bridge_spec(name: str) -> LogicBridgeSpec:
    """Return one bridge spec by name."""

    return _SPECS_BY_NAME[name]


def logic_bridge_manifest() -> dict[str, Any]:
    """Return the bridge manifest used by optimizer routing."""

    specs = [spec.to_dict() for spec in _SPECS]
    by_component: dict[str, list[str]] = {}
    roles: dict[str, list[str]] = {}
    for spec in _SPECS:
        by_component.setdefault(spec.target_component, []).append(spec.name)
        for role in spec.roles:
            roles.setdefault(role, []).append(spec.name)
    return {
        "bridge_count": len(specs),
        "bridges": specs,
        "implemented_bridges": [spec.name for spec in _SPECS if spec.implemented],
        "manifest_version": 1,
        "target_components": {
            component: sorted(names)
            for component, names in sorted(by_component.items())
        },
        "roles": {role: sorted(names) for role, names in sorted(roles.items())},
    }


def load_logic_bridge_adapter(name: str, **kwargs: Any) -> Any:
    """Instantiate an implemented bridge adapter by name."""

    spec = logic_bridge_spec(name)
    if not spec.implemented or not spec.adapter_module or not spec.adapter_class:
        raise NotImplementedError(f"Logic bridge {name!r} is registered but not implemented")
    module = importlib.import_module(spec.adapter_module)
    adapter_cls = getattr(module, spec.adapter_class)
    return adapter_cls(**kwargs)


def bridge_name_for_component(target_component: str) -> Optional[str]:
    """Return the most specific bridge registered for an optimizer component."""

    target = str(target_component or "").strip()
    if not target:
        return None
    matches = [
        spec
        for spec in _SPECS
        if target.startswith(spec.target_component) or spec.target_component.startswith(target)
    ]
    if not matches:
        return None
    matches.sort(key=lambda spec: len(spec.target_component), reverse=True)
    return matches[0].name


__all__ = [
    "DEFAULT_LEGAL_IR_BRIDGE_NAMES",
    "LogicBridgeSpec",
    "bridge_name_for_component",
    "load_logic_bridge_adapter",
    "logic_bridge_manifest",
    "logic_bridge_spec",
    "logic_bridge_specs",
]
