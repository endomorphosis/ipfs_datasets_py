"""Canonical contracts for the multi-view LegalIR pipeline.

The logic bridges historically identified views with ad-hoc component strings.
This module is the dependency-light source of truth for those identifiers and
for the information that must survive a projection.  It deliberately stores
only provenance identifiers; legal source text belongs in the source document,
not in contract, metric, learning-feature, or Codex task payloads.

Contract IDs and family names are public data contracts.  Change them only by
introducing a new schema version, never by deriving them from descriptions or
from runtime ordering.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final


LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION: Final = "legal-ir-view-contract-v1"
LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION: Final = "legal-ir-view-contract-registry-v1"


class LegalIRView(str, Enum):
    """Stable, human-facing names for the canonical LegalIR views."""

    DEONTIC = "deontic"
    FRAME_LOGIC = "frame_logic"
    TDFOL = "tdfol"
    CEC = "cec"
    KNOWLEDGE_GRAPHS = "knowledge_graphs"
    EXTERNAL_PROVERS = "external_provers"
    DECOMPILER = "decompiler"


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class LegalIRFieldRequirement:
    """One required JSON field in a canonical view payload.

    ``path`` supports dotted mapping paths.  Aliases are accepted while legacy
    producers migrate, but manifests always publish the canonical path.
    """

    path: str
    value_types: tuple[str, ...]
    description: str
    allow_empty: bool = False
    aliases: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "allow_empty": self.allow_empty,
            "allowed_values": list(self.allowed_values),
            "description": self.description,
            "path": self.path,
            "value_types": list(self.value_types),
        }


@dataclass(frozen=True)
class LegalIRModalitySemantics:
    """How modal force is represented and preserved by one view."""

    family: str
    operators: tuple[str, ...]
    force_mapping: tuple[tuple[str, str], ...]
    polarity_values: tuple[str, ...]
    temporal_semantics: str
    exception_semantics: str
    preservation_rules: tuple[str, ...]

    def force_for(self, operator: str) -> str | None:
        normalized = str(operator or "").strip().lower()
        for symbol, force in self.force_mapping:
            if symbol.lower() == normalized:
                return force
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_semantics": self.exception_semantics,
            "family": self.family,
            "force_mapping": {key: value for key, value in self.force_mapping},
            "operators": list(self.operators),
            "polarity_values": list(self.polarity_values),
            "preservation_rules": list(self.preservation_rules),
            "temporal_semantics": self.temporal_semantics,
        }


@dataclass(frozen=True)
class LegalIRProvenanceRequirements:
    """Identifier-only provenance policy shared by canonical view payloads."""

    identifier_field: str = "provenance_ids"
    identifier_aliases: tuple[str, ...] = ("provenance.id", "provenance.source_id")
    minimum_identifiers: int = 1
    source_text_policy: str = "identifiers_only"
    forbidden_source_fields: tuple[str, ...] = (
        "copied_text",
        "draft_text",
        "full_text",
        "normalized_text",
        "raw_source",
        "source_span",
        "source_text",
        "text",
    )

    @property
    def required(self) -> bool:
        return self.minimum_identifiers > 0

    @property
    def stores_source_text(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "forbidden_source_fields": list(self.forbidden_source_fields),
            "identifier_aliases": list(self.identifier_aliases),
            "identifier_field": self.identifier_field,
            "minimum_identifiers": self.minimum_identifiers,
            "required": self.required,
            "source_text_policy": self.source_text_policy,
            "stores_source_text": self.stores_source_text,
        }


@dataclass(frozen=True)
class LegalIRValidationHook:
    """Serializable reference to a deterministic payload validator."""

    hook_id: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {"description": self.description, "hook_id": self.hook_id}


@dataclass(frozen=True)
class LegalIRRepairLane:
    """A bounded implementation route for a failed contract."""

    lane_id: str
    action: str
    target_component: str
    allowed_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "allowed_paths": list(self.allowed_paths),
            "description": self.description,
            "lane_id": self.lane_id,
            "target_component": self.target_component,
            "validation_commands": list(self.validation_commands),
        }


@dataclass(frozen=True)
class LegalIRContractValidationIssue:
    """One deterministic contract violation."""

    code: str
    message: str
    field_path: str = ""
    hook_id: str = ""
    severity: ValidationSeverity = ValidationSeverity.ERROR

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "hook_id": self.hook_id,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass(frozen=True)
class LegalIRContractValidationResult:
    """Validation result safe to include in telemetry and guidance."""

    contract_id: str
    view: str
    issues: tuple[LegalIRContractValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not any(
            issue.severity is ValidationSeverity.ERROR for issue in self.issues
        )

    @property
    def missing_required_fields(self) -> tuple[str, ...]:
        return tuple(
            issue.field_path
            for issue in self.issues
            if issue.code == "missing_required_field"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "issues": [issue.to_dict() for issue in self.issues],
            "missing_required_fields": list(self.missing_required_fields),
            "valid": self.valid,
            "view": self.view,
        }


ValidationHookCallable = Callable[
    ["LegalIRViewContract", Mapping[str, Any]], Sequence[LegalIRContractValidationIssue]
]


@dataclass(frozen=True)
class LegalIRViewContract:
    """Immutable contract for one canonical LegalIR representation."""

    contract_id: str
    view: LegalIRView
    target_component: str
    description: str
    required_fields: tuple[LegalIRFieldRequirement, ...]
    modality_semantics: LegalIRModalitySemantics
    provenance_requirements: LegalIRProvenanceRequirements
    repair_lanes: tuple[LegalIRRepairLane, ...]
    validation_hooks: tuple[LegalIRValidationHook, ...]
    obligation_families: tuple[str, ...]
    cross_view_obligation_families: tuple[str, ...]
    metric_families: tuple[str, ...]
    autoencoder_feature_families: tuple[str, ...] = (
        "contract_id",
        "obligation_family",
        "metric_family",
        "repair_lane",
        "view",
    )
    aliases: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION

    @property
    def required_field_names(self) -> tuple[str, ...]:
        return tuple(requirement.path for requirement in self.required_fields)

    @property
    def allowed_repair_lanes(self) -> tuple[str, ...]:
        return tuple(lane.lane_id for lane in self.repair_lanes)

    @property
    def all_obligation_families(self) -> tuple[str, ...]:
        return _unique(
            (*self.obligation_families, *self.cross_view_obligation_families)
        )

    def repair_lane(self, lane_id: str) -> LegalIRRepairLane:
        for lane in self.repair_lanes:
            if lane.lane_id == lane_id or lane.action == lane_id:
                return lane
        raise KeyError(lane_id)

    def validate(
        self, payload: Mapping[str, Any] | Any
    ) -> LegalIRContractValidationResult:
        normalized = _payload_mapping(payload)
        issues: list[LegalIRContractValidationIssue] = []
        for hook in self.validation_hooks:
            validator = _VALIDATION_HOOK_IMPLEMENTATIONS.get(hook.hook_id)
            if validator is None:
                issues.append(
                    LegalIRContractValidationIssue(
                        code="unknown_validation_hook",
                        message=f"No validator is registered for {hook.hook_id!r}",
                        hook_id=hook.hook_id,
                    )
                )
                continue
            issues.extend(validator(self, normalized))
        return LegalIRContractValidationResult(
            contract_id=self.contract_id,
            view=self.view.value,
            issues=tuple(_dedupe_issues(issues)),
        )

    def autoencoder_features(self) -> tuple[str, ...]:
        """Return bounded categorical feature values; never source content."""

        values = [f"contract_id:{self.contract_id}", f"view:{self.view.value}"]
        values.extend(
            f"obligation_family:{item}" for item in self.all_obligation_families
        )
        values.extend(f"metric_family:{item}" for item in self.metric_families)
        values.extend(f"repair_lane:{item}" for item in self.allowed_repair_lanes)
        return tuple(values)

    def codex_todo_projection(self, lane_id: str | None = None) -> dict[str, Any]:
        """Return the deterministic, path-bounded part of a Codex TODO packet."""

        lanes = self.repair_lanes if lane_id is None else (self.repair_lane(lane_id),)
        return {
            "allowed_repair_lanes": [lane.lane_id for lane in lanes],
            "allowed_paths": list(
                _unique(path for lane in lanes for path in lane.allowed_paths)
            ),
            "contract_id": self.contract_id,
            "obligation_families": list(self.all_obligation_families),
            "repair_actions": [lane.action for lane in lanes],
            "target_component": self.target_component,
            "validation_commands": list(
                _unique(
                    command for lane in lanes for command in lane.validation_commands
                )
            ),
            "view": self.view.value,
        }

    def consumer_contract(self) -> dict[str, Any]:
        """Compact shared descriptor for obligations, metrics, features, and TODOs."""

        return {
            "autoencoder_feature_families": list(self.autoencoder_feature_families),
            "contract_id": self.contract_id,
            "cross_view_obligation_families": list(self.cross_view_obligation_families),
            "metric_families": list(self.metric_families),
            "obligation_families": list(self.all_obligation_families),
            "repair_lanes": list(self.allowed_repair_lanes),
            "target_component": self.target_component,
            "view": self.view.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "allowed_repair_lanes": list(self.allowed_repair_lanes),
            "all_obligation_families": list(self.all_obligation_families),
            "autoencoder_feature_families": list(self.autoencoder_feature_families),
            "contract_id": self.contract_id,
            "cross_view_obligation_families": list(self.cross_view_obligation_families),
            "description": self.description,
            "metric_families": list(self.metric_families),
            "modality_semantics": self.modality_semantics.to_dict(),
            "obligation_families": list(self.obligation_families),
            "provenance_requirements": self.provenance_requirements.to_dict(),
            "repair_lanes": [lane.to_dict() for lane in self.repair_lanes],
            "required_fields": [
                requirement.to_dict() for requirement in self.required_fields
            ],
            "required_field_names": list(self.required_field_names),
            "schema_version": self.schema_version,
            "target_component": self.target_component,
            "validation_hooks": [hook.to_dict() for hook in self.validation_hooks],
            "view": self.view.value,
        }


class LegalIRViewContractRegistry(Mapping[str, LegalIRViewContract]):
    """Read-only registry with canonical and compatibility-name resolution."""

    def __init__(self, contracts: Sequence[LegalIRViewContract]) -> None:
        ordered = tuple(contracts)
        by_view = {contract.view.value: contract for contract in ordered}
        if len(by_view) != len(ordered):
            raise ValueError("LegalIR view names must be unique")
        by_id = {contract.contract_id: contract for contract in ordered}
        if len(by_id) != len(ordered):
            raise ValueError("LegalIR contract IDs must be unique")
        aliases: dict[str, LegalIRViewContract] = {}
        for contract in ordered:
            for name in (
                contract.view.value,
                contract.contract_id,
                contract.target_component,
                *contract.aliases,
            ):
                key = _lookup_key(name)
                existing = aliases.get(key)
                if existing is not None and existing is not contract:
                    raise ValueError(f"LegalIR contract alias collision: {name!r}")
                aliases[key] = contract
        self._ordered = ordered
        self._by_view = MappingProxyType(by_view)
        self._aliases = MappingProxyType(aliases)

    def __getitem__(self, key: str | LegalIRView) -> LegalIRViewContract:
        name = key.value if isinstance(key, LegalIRView) else str(key)
        try:
            return self._aliases[_lookup_key(name)]
        except KeyError:
            raise KeyError(name) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._by_view)

    def __len__(self) -> int:
        return len(self._ordered)

    @property
    def contract_ids(self) -> tuple[str, ...]:
        return tuple(contract.contract_id for contract in self._ordered)

    def contracts(self) -> tuple[LegalIRViewContract, ...]:
        return self._ordered

    def resolve(self, view_or_alias: str | LegalIRView) -> LegalIRViewContract:
        return self[view_or_alias]

    def validate(
        self, view_or_alias: str | LegalIRView, payload: Mapping[str, Any] | Any
    ) -> LegalIRContractValidationResult:
        return self[view_or_alias].validate(payload)

    def manifest(self) -> dict[str, Any]:
        return {
            "contract_count": len(self),
            "contract_ids": list(self.contract_ids),
            "contracts": [contract.to_dict() for contract in self._ordered],
            "consumer_contracts": [
                contract.consumer_contract() for contract in self._ordered
            ],
            "registry_version": LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION,
        }

    def codex_todo_projection(
        self, view_or_alias: str | LegalIRView, lane_id: str | None = None
    ) -> dict[str, Any]:
        return self[view_or_alias].codex_todo_projection(lane_id)


_PROVENANCE = LegalIRProvenanceRequirements()
_REQUIRED_HOOK = LegalIRValidationHook(
    "required_fields", "Require the typed fields declared by the view contract."
)
_PROVENANCE_HOOK = LegalIRValidationHook(
    "provenance_identifiers_only",
    "Require stable provenance IDs and reject copied legal source fields.",
)


def _field(
    path: str,
    *value_types: str,
    description: str,
    allow_empty: bool = False,
    aliases: tuple[str, ...] = (),
    allowed_values: tuple[str, ...] = (),
) -> LegalIRFieldRequirement:
    return LegalIRFieldRequirement(
        path=path,
        value_types=tuple(value_types),
        description=description,
        allow_empty=allow_empty,
        aliases=aliases,
        allowed_values=allowed_values,
    )


def _lane(
    lane_id: str,
    action: str,
    component: str,
    paths: tuple[str, ...],
    description: str,
) -> LegalIRRepairLane:
    return LegalIRRepairLane(
        lane_id=lane_id,
        action=action,
        target_component=component,
        allowed_paths=paths,
        validation_commands=(
            ".venv-cuda/bin/python -m pytest tests/unit/logic/integration/"
            "test_legal_ir_view_contracts.py -q",
        ),
        description=description,
    )


_CONTRACTS: tuple[LegalIRViewContract, ...] = (
    LegalIRViewContract(
        contract_id="legal-ir-view/deontic/v1",
        view=LegalIRView.DEONTIC,
        target_component="deontic.ir",
        description="Normative force, polarity, scope, conditions, and defeasible exceptions.",
        required_fields=(
            _field(
                "formula_id", "string", description="Stable source-scoped formula ID."
            ),
            _field("operator", "string", description="Deontic operator symbol."),
            _field(
                "norm_type",
                "string",
                description="Obligation, permission, or prohibition.",
                allowed_values=("obligation", "permission", "prohibition"),
            ),
            _field(
                "polarity",
                "string",
                description="Norm polarity.",
                allowed_values=("positive", "negative"),
            ),
            _field("actor", "string", description="Typed norm bearer."),
            _field("action", "string", description="Typed governed action."),
            _field("object", "string", "object", description="Typed governed object."),
            _field(
                "conditions",
                "array",
                description="Scoped activation conditions.",
                allow_empty=True,
            ),
            _field(
                "exceptions",
                "array",
                description="Scoped defeaters in precedence order.",
                allow_empty=True,
            ),
            _field(
                "provenance_ids",
                "array",
                "string",
                description="Stable provenance identifiers.",
            ),
        ),
        modality_semantics=LegalIRModalitySemantics(
            family="deontic",
            operators=(
                "O",
                "P",
                "F",
                "shall",
                "must",
                "may",
                "shall_not",
                "must_not",
                "may_not",
            ),
            force_mapping=(
                ("O", "obligation"),
                ("shall", "obligation"),
                ("must", "obligation"),
                ("P", "permission"),
                ("may", "permission"),
                ("F", "prohibition"),
                ("shall_not", "prohibition"),
                ("must_not", "prohibition"),
                ("may_not", "prohibition"),
            ),
            polarity_values=("positive", "negative"),
            temporal_semantics="Conditions retain explicit anchors for TDFOL projection.",
            exception_semantics="Specific scoped exceptions defeat the general norm before projection.",
            preservation_rules=(
                "operator_force",
                "prohibition_polarity",
                "condition_scope",
                "exception_precedence",
            ),
        ),
        provenance_requirements=_PROVENANCE,
        repair_lanes=(
            _lane(
                "deontic.norm_semantics",
                "repair_deontic_bridge_quality_gate",
                "deontic.ir",
                (
                    "ipfs_datasets_py/logic/bridge/deontic_norms.py",
                    "ipfs_datasets_py/logic/deontic/converter.py",
                    "ipfs_datasets_py/logic/deontic/ir.py",
                    "ipfs_datasets_py/logic/deontic/prover_syntax.py",
                ),
                "Repair norm force, polarity, scope, or typed slots.",
            ),
        ),
        validation_hooks=(
            _REQUIRED_HOOK,
            _PROVENANCE_HOOK,
            LegalIRValidationHook(
                "deontic_semantics", "Validate operator force and prohibition polarity."
            ),
        ),
        obligation_families=(
            "deontic_required_fields",
            "deontic_polarity",
            "exception_scope_precedence",
        ),
        cross_view_obligation_families=("cross_view_deontic_preservation",),
        metric_families=(
            "deontic_decoder_slot_loss",
            "deontic_proof_failure_ratio",
            "symbolic_validity_penalty",
        ),
        aliases=("deontic.ir", "deontic_ir", "deontic_norms"),
    ),
    LegalIRViewContract(
        contract_id="legal-ir-view/frame-logic/v1",
        view=LegalIRView.FRAME_LOGIC,
        target_component="modal.frame_logic",
        description="Typed frame roles and relations shared by modal and graph views.",
        required_fields=(
            _field("formula_id", "string", description="Owning formula ID."),
            _field("frame_id", "string", description="Stable frame ID."),
            _field("subject", "string", description="Typed relation subject."),
            _field("predicate", "string", description="Ontology relation."),
            _field("object", "string", "object", description="Typed relation object."),
            _field(
                "role",
                "string",
                description="Actor/action/object/condition/exception/remedy/authority role.",
            ),
            _field(
                "provenance_ids",
                "array",
                "string",
                description="Stable provenance identifiers.",
            ),
        ),
        modality_semantics=LegalIRModalitySemantics(
            family="frame_logic",
            operators=("box", "diamond", "O", "P", "F"),
            force_mapping=(
                ("box", "necessity"),
                ("diamond", "possibility"),
                ("O", "obligation"),
                ("P", "permission"),
                ("F", "prohibition"),
            ),
            polarity_values=("positive", "negative", "not_applicable"),
            temporal_semantics="Temporal roles are typed relations, not flattened labels.",
            exception_semantics="Exception and governed-rule frames retain explicit scoped edges.",
            preservation_rules=(
                "typed_role",
                "relation_direction",
                "modal_operator",
                "exception_scope",
            ),
        ),
        provenance_requirements=_PROVENANCE,
        repair_lanes=(
            _lane(
                "frame_logic.ontology",
                "repair_flogic_ontology_constraints",
                "modal.frame_logic",
                (
                    "ipfs_datasets_py/logic/bridge/modal_frame_logic.py",
                    "ipfs_datasets_py/logic/modal/compiler.py",
                    "ipfs_datasets_py/logic/modal/kg_bridge.py",
                ),
                "Repair typed role or ontology relation preservation.",
            ),
        ),
        validation_hooks=(
            _REQUIRED_HOOK,
            _PROVENANCE_HOOK,
            LegalIRValidationHook(
                "frame_relation_typing",
                "Validate non-empty typed relation endpoints and role.",
            ),
        ),
        obligation_families=("frame_logic_required_fields", "frame_role_typing"),
        cross_view_obligation_families=("cross_view_frame_consistency",),
        metric_families=(
            "flogic_similarity_loss",
            "frame_ranking_loss",
            "symbolic_validity_penalty",
        ),
        aliases=("modal.frame_logic", "modal_frame_logic", "frame-logic"),
    ),
    LegalIRViewContract(
        contract_id="legal-ir-view/tdfol/v1",
        view=LegalIRView.TDFOL,
        target_component="TDFOL.prover",
        description="Typed first-order temporal formula and explicit time anchors.",
        required_fields=(
            _field("formula_id", "string", description="Stable formula ID."),
            _field(
                "expression",
                "string",
                "object",
                description="Typed TDFOL expression.",
                aliases=("formula", "tdfol_formula"),
            ),
            _field(
                "quantifiers",
                "array",
                description="Bound quantifiers.",
                allow_empty=True,
            ),
            _field(
                "temporal_anchors", "array", description="Explicit event/time anchors."
            ),
            _field(
                "provenance_ids",
                "array",
                "string",
                description="Stable provenance identifiers.",
            ),
        ),
        modality_semantics=LegalIRModalitySemantics(
            family="temporal_first_order",
            operators=("always", "eventually", "until", "before", "after", "within"),
            force_mapping=(
                ("always", "invariant"),
                ("eventually", "eventuality"),
                ("until", "bounded_continuation"),
                ("before", "strict_precedence"),
                ("after", "strict_succession"),
                ("within", "deadline"),
            ),
            polarity_values=("positive", "negative"),
            temporal_semantics="Every temporal constraint references a typed anchor or event relation.",
            exception_semantics="Exception scope is encoded before temporal lowering.",
            preservation_rules=(
                "quantifier_scope",
                "temporal_anchor",
                "event_order",
                "deontic_force",
            ),
        ),
        provenance_requirements=_PROVENANCE,
        repair_lanes=(
            _lane(
                "tdfol.temporal",
                "repair_tdfol_bridge_parse",
                "TDFOL.prover",
                (
                    "ipfs_datasets_py/logic/bridge/fol_tdfol.py",
                    "ipfs_datasets_py/logic/TDFOL/tdfol_converter.py",
                    "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",
                    "ipfs_datasets_py/logic/TDFOL/tdfol_prover.py",
                ),
                "Repair formula lowering, temporal anchors, or parser validity.",
            ),
        ),
        validation_hooks=(
            _REQUIRED_HOOK,
            _PROVENANCE_HOOK,
            LegalIRValidationHook(
                "temporal_anchors", "Validate explicit temporal anchors."
            ),
        ),
        obligation_families=("tdfol_required_fields", "temporal_anchor"),
        cross_view_obligation_families=("cross_view_temporal_consistency",),
        metric_families=(
            "tdfol_parse_failure_ratio",
            "tdfol_no_formula_loss",
            "hammer_proof_success_rate",
        ),
        aliases=("TDFOL.prover", "tdfol_prover", "TDFOL", "temporal"),
    ),
    LegalIRViewContract(
        contract_id="legal-ir-view/cec/v1",
        view=LegalIRView.CEC,
        target_component="CEC.native",
        description="Event-calculus events, fluents, and lifecycle transitions.",
        required_fields=(
            _field("formula_id", "string", description="Stable formula ID."),
            _field("events", "array", description="Typed lifecycle events."),
            _field("fluents", "array", description="Typed state fluents."),
            _field(
                "lifecycle_transitions",
                "array",
                description="Event-to-fluent transitions.",
            ),
            _field(
                "provenance_ids",
                "array",
                "string",
                description="Stable provenance identifiers.",
            ),
        ),
        modality_semantics=LegalIRModalitySemantics(
            family="event_calculus",
            operators=("Happens", "HoldsAt", "Initiates", "Terminates", "Clipped"),
            force_mapping=(
                ("Happens", "event_occurrence"),
                ("HoldsAt", "state_holding"),
                ("Initiates", "state_start"),
                ("Terminates", "state_end"),
                ("Clipped", "state_interruption"),
            ),
            polarity_values=("positive", "negative"),
            temporal_semantics="Lifecycle changes are explicit event/fluent/time transitions.",
            exception_semantics="Defeaters inhibit or clip a transition without deleting its source event.",
            preservation_rules=(
                "event_identity",
                "fluent_identity",
                "transition_direction",
                "time_anchor",
            ),
        ),
        provenance_requirements=_PROVENANCE,
        repair_lanes=(
            _lane(
                "cec.lifecycle",
                "repair_cec_dcec_bridge",
                "CEC.native",
                (
                    "ipfs_datasets_py/logic/bridge/cec_dcec.py",
                    "ipfs_datasets_py/logic/CEC/native/event_calculus.py",
                    "ipfs_datasets_py/logic/CEC/native/temporal.py",
                ),
                "Repair event, fluent, or lifecycle transition projection.",
            ),
        ),
        validation_hooks=(
            _REQUIRED_HOOK,
            _PROVENANCE_HOOK,
            LegalIRValidationHook(
                "cec_lifecycle", "Validate typed lifecycle transitions."
            ),
        ),
        obligation_families=("cec_required_fields", "cec_lifecycle_transition"),
        cross_view_obligation_families=("cross_view_event_consistency",),
        metric_families=(
            "cec_dcec_validation_failure_ratio",
            "cec_dcec_event_formula_invalid_ratio",
            "hammer_proof_success_rate",
        ),
        aliases=("CEC.native", "cec_native", "event_calculus", "dcec"),
    ),
    LegalIRViewContract(
        contract_id="legal-ir-view/knowledge-graphs/v1",
        view=LegalIRView.KNOWLEDGE_GRAPHS,
        target_component="knowledge_graphs.neo4j_compat",
        description="Neo4j-compatible typed nodes and directed relationships.",
        required_fields=(
            _field("graph_id", "string", description="Stable graph projection ID."),
            _field("nodes", "array", description="Nodes with stable IDs and labels."),
            _field(
                "relationships", "array", description="Typed directed relationships."
            ),
            _field(
                "provenance_ids",
                "array",
                "string",
                description="Stable provenance identifiers.",
            ),
        ),
        modality_semantics=LegalIRModalitySemantics(
            family="graph_projection",
            operators=("typed_edge", "scoped_edge"),
            force_mapping=(
                ("typed_edge", "semantic_relation"),
                ("scoped_edge", "qualified_relation"),
            ),
            polarity_values=("positive", "negative", "not_applicable"),
            temporal_semantics="Time and event anchors remain typed nodes or relationship properties.",
            exception_semantics="Exception edges target the governed rule or frame explicitly.",
            preservation_rules=(
                "endpoint_identity",
                "edge_direction",
                "edge_type",
                "provenance_identity",
            ),
        ),
        provenance_requirements=_PROVENANCE,
        repair_lanes=(
            _lane(
                "knowledge_graphs.projection",
                "repair_multiview_legal_ir_graph_projection",
                "knowledge_graphs.neo4j_compat",
                (
                    "ipfs_datasets_py/logic/modal/kg_bridge.py",
                    "ipfs_datasets_py/knowledge_graphs/neo4j_compat/legal_ir_projection.py",
                ),
                "Repair node typing, relationship endpoints, or frame alignment.",
            ),
        ),
        validation_hooks=(
            _REQUIRED_HOOK,
            _PROVENANCE_HOOK,
            LegalIRValidationHook(
                "knowledge_graph_endpoints",
                "Validate node IDs and typed relationship endpoints.",
            ),
        ),
        obligation_families=(
            "knowledge_graph_required_fields",
            "knowledge_graph_endpoint_typing",
        ),
        cross_view_obligation_families=("cross_view_graph_consistency",),
        metric_families=(
            "legal_ir_multiview_graph_failure_penalty",
            "ontology_violation_count",
            "symbolic_validity_penalty",
        ),
        aliases=(
            "knowledge_graphs.neo4j_compat",
            "knowledge_graphs_neo4j_compat",
            "knowledge_graph",
            "neo4j_compat",
        ),
    ),
    LegalIRViewContract(
        contract_id="legal-ir-view/external-provers/v1",
        view=LegalIRView.EXTERNAL_PROVERS,
        target_component="external_provers.router",
        description="Bounded prover route, backend result, and reconstruction receipt.",
        required_fields=(
            _field(
                "obligation_id", "string", description="Stable proof obligation ID."
            ),
            _field(
                "input_formula_id",
                "string",
                description="Formula identity before translation.",
                aliases=("formula_id",),
            ),
            _field(
                "backend_route",
                "array",
                "string",
                description="Ordered or parallel backend route.",
            ),
            _field(
                "backend_status",
                "object",
                "string",
                description="Per-backend or winning status.",
            ),
            _field(
                "reconstruction_status",
                "string",
                description="Native reconstruction outcome.",
            ),
            _field(
                "provenance_ids",
                "array",
                "string",
                description="Stable provenance identifiers.",
            ),
        ),
        modality_semantics=LegalIRModalitySemantics(
            family="proof_translation",
            operators=("SMT-LIB", "TPTP", "Lean"),
            force_mapping=(
                ("SMT-LIB", "satisfiability_route"),
                ("TPTP", "first_order_proof_route"),
                ("Lean", "native_reconstruction_route"),
            ),
            polarity_values=("asserted", "negated_goal"),
            temporal_semantics="Temporal and modal operators survive type encoding and translation receipts.",
            exception_semantics="Exception precedence is fixed before backend translation.",
            preservation_rules=(
                "input_formula_id",
                "modal_operator",
                "type_encoding",
                "route_status",
                "trust_boundary",
            ),
        ),
        provenance_requirements=_PROVENANCE,
        repair_lanes=(
            _lane(
                "external_provers.routing",
                "repair_external_prover_router",
                "external_provers.router",
                (
                    "ipfs_datasets_py/logic/bridge/external_prover_router.py",
                    "ipfs_datasets_py/logic/external_provers/prover_router.py",
                    "ipfs_datasets_py/logic/external_provers/lazy_installer.py",
                ),
                "Repair translation-preserving backend selection and bounded fallback.",
            ),
        ),
        validation_hooks=(
            _REQUIRED_HOOK,
            _PROVENANCE_HOOK,
            LegalIRValidationHook(
                "external_prover_route",
                "Validate non-empty backend routing and receipt status.",
            ),
        ),
        obligation_families=(
            "external_prover_required_fields",
            "external_prover_route_preservation",
        ),
        cross_view_obligation_families=("cross_view_proof_consistency",),
        metric_families=(
            "legal_ir_multiview_proof_failure_ratio",
            "external_prover_failure_ratio",
            "hammer_proof_success_rate",
        ),
        aliases=(
            "external_provers.router",
            "external_provers_router",
            "prover_router",
            "prover",
        ),
    ),
    LegalIRViewContract(
        contract_id="legal-ir-view/decompiler/v1",
        view=LegalIRView.DECOMPILER,
        target_component="modal.ir_decompiler",
        description="Deterministic structural round trip from typed IR without copied source text.",
        required_fields=(
            _field("formula_id", "string", description="Stable formula identity."),
            _field(
                "source_contract_id",
                "string",
                description="Contract of the decoded input view.",
                aliases=("contract_id",),
            ),
            _field(
                "reconstructed_structure",
                "object",
                description="Typed reconstructed slots, not prose.",
            ),
            _field("operator", "string", description="Preserved modal operator."),
            _field(
                "predicate",
                "string",
                "object",
                description="Preserved predicate signature.",
            ),
            _field(
                "arguments",
                "array",
                description="Preserved typed arguments.",
                allow_empty=True,
            ),
            _field(
                "conditions",
                "array",
                description="Preserved conditions.",
                allow_empty=True,
            ),
            _field(
                "exceptions",
                "array",
                description="Preserved scoped exceptions.",
                allow_empty=True,
            ),
            _field(
                "provenance_ids",
                "array",
                "string",
                description="Stable provenance identifiers.",
            ),
        ),
        modality_semantics=LegalIRModalitySemantics(
            family="structural_round_trip",
            operators=("preserve",),
            force_mapping=(("preserve", "identity"),),
            polarity_values=("preserved",),
            temporal_semantics="Temporal anchors and ordering are reconstructed as typed slots.",
            exception_semantics="Exception membership, order, and governed scope are structurally preserved.",
            preservation_rules=(
                "formula_identity",
                "operator_force",
                "predicate_signature",
                "argument_roles",
                "condition_scope",
                "exception_scope",
            ),
        ),
        provenance_requirements=_PROVENANCE,
        repair_lanes=(
            _lane(
                "decompiler.round_trip",
                "refine_typed_ir_or_decompiler_slots",
                "modal.ir_decompiler",
                (
                    "ipfs_datasets_py/logic/modal/decompiler.py",
                    "ipfs_datasets_py/logic/modal/codec.py",
                    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
                ),
                "Repair deterministic structural reconstruction while retaining identifier-only provenance.",
            ),
        ),
        validation_hooks=(
            _REQUIRED_HOOK,
            _PROVENANCE_HOOK,
            LegalIRValidationHook(
                "decompiler_structure",
                "Validate contract identity and structural round-trip slots.",
            ),
        ),
        obligation_families=(
            "decompiler_required_fields",
            "decompiler_round_trip_structure",
        ),
        cross_view_obligation_families=("cross_view_round_trip_consistency",),
        metric_families=(
            "reconstruction_loss",
            "source_decompiled_text_embedding_cosine_loss",
            "source_decompiled_text_token_loss",
        ),
        aliases=(
            "modal.ir_decompiler",
            "modal.decompiler",
            "ir_decompiler",
            "round_trip",
        ),
    ),
)


def _lookup_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


_MISSING = object()


def _payload_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        mapping = value
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        converted = value.to_dict()
        mapping = converted if isinstance(converted, Mapping) else {}
    elif hasattr(value, "__dict__"):
        mapping = vars(value)
    else:
        mapping = {}
    nested = mapping.get("payload")
    return nested if isinstance(nested, Mapping) else mapping


def _path_get(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _field_value(
    payload: Mapping[str, Any], requirement: LegalIRFieldRequirement
) -> Any:
    for path in (requirement.path, *requirement.aliases):
        value = _path_get(payload, path)
        if value is not _MISSING:
            return value
    return _MISSING


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return "unknown"


def _is_empty(value: Any) -> bool:
    return value is None or (
        isinstance(value, (str, Mapping, Sequence))
        and not isinstance(value, (bytes, bytearray))
        and len(value) == 0
    )


def _issue(
    code: str, message: str, field_path: str, hook_id: str
) -> LegalIRContractValidationIssue:
    return LegalIRContractValidationIssue(
        code=code, message=message, field_path=field_path, hook_id=hook_id
    )


def _validate_required_fields(
    contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    issues: list[LegalIRContractValidationIssue] = []
    for requirement in contract.required_fields:
        value = _field_value(payload, requirement)
        if (
            value is _MISSING
            and requirement.path == contract.provenance_requirements.identifier_field
        ):
            for alias in contract.provenance_requirements.identifier_aliases:
                value = _path_get(payload, alias)
                if value is not _MISSING:
                    break
        if value is _MISSING:
            issues.append(
                _issue(
                    "missing_required_field",
                    f"Required field {requirement.path!r} is missing",
                    requirement.path,
                    "required_fields",
                )
            )
            continue
        actual_type = _json_type(value)
        compatible = actual_type in requirement.value_types or (
            actual_type == "integer" and "number" in requirement.value_types
        )
        if not compatible:
            issues.append(
                _issue(
                    "invalid_field_type",
                    f"Field {requirement.path!r} must be one of {requirement.value_types}; got {actual_type}",
                    requirement.path,
                    "required_fields",
                )
            )
        elif not requirement.allow_empty and _is_empty(value):
            issues.append(
                _issue(
                    "empty_required_field",
                    f"Required field {requirement.path!r} may not be empty",
                    requirement.path,
                    "required_fields",
                )
            )
        if (
            requirement.allowed_values
            and isinstance(value, str)
            and value.lower()
            not in {item.lower() for item in requirement.allowed_values}
        ):
            issues.append(
                _issue(
                    "unsupported_field_value",
                    f"Field {requirement.path!r} has unsupported value {value!r}",
                    requirement.path,
                    "required_fields",
                )
            )
    return issues


def _walk_source_fields(
    value: Any, forbidden: frozenset[str], path: str = ""
) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            child_path = f"{path}.{name}" if path else name
            lowered = name.lower()
            if lowered in forbidden or lowered.endswith("_source_text"):
                yield child_path
            else:
                yield from _walk_source_fields(child, forbidden, child_path)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            yield from _walk_source_fields(child, forbidden, f"{path}[{index}]")


def _provenance_values(
    contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> list[Any]:
    policy = contract.provenance_requirements
    value = _path_get(payload, policy.identifier_field)
    if value is _MISSING:
        for alias in policy.identifier_aliases:
            value = _path_get(payload, alias)
            if value is not _MISSING:
                break
    if value is _MISSING or value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _validate_provenance(
    contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    hook = "provenance_identifiers_only"
    policy = contract.provenance_requirements
    values = _provenance_values(contract, payload)
    issues: list[LegalIRContractValidationIssue] = []
    if len(values) < policy.minimum_identifiers:
        issues.append(
            _issue(
                "missing_provenance_id",
                f"At least {policy.minimum_identifiers} provenance identifier(s) are required",
                policy.identifier_field,
                hook,
            )
        )
    elif any(not isinstance(value, str) or not value.strip() for value in values):
        issues.append(
            _issue(
                "invalid_provenance_id",
                "Provenance identifiers must be non-empty strings",
                policy.identifier_field,
                hook,
            )
        )
    forbidden = frozenset(name.lower() for name in policy.forbidden_source_fields)
    for path in _walk_source_fields(payload, forbidden):
        issues.append(
            _issue(
                "source_text_forbidden",
                f"Raw source field {path!r} must be replaced by a provenance ID or hash",
                path,
                hook,
            )
        )
    return issues


def _validate_deontic(
    contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    operator = str(payload.get("operator") or "")
    norm_type = str(payload.get("norm_type") or "").lower()
    polarity = str(payload.get("polarity") or "").lower()
    force = contract.modality_semantics.force_for(operator)
    issues: list[LegalIRContractValidationIssue] = []
    if operator and force is None:
        issues.append(
            _issue(
                "unsupported_modal_operator",
                f"Operator {operator!r} is not declared by the contract",
                "operator",
                "deontic_semantics",
            )
        )
    if force and norm_type and force != norm_type:
        issues.append(
            _issue(
                "deontic_force_mismatch",
                f"Operator {operator!r} denotes {force}, not {norm_type}",
                "norm_type",
                "deontic_semantics",
            )
        )
    if norm_type == "prohibition" and polarity != "negative":
        issues.append(
            _issue(
                "prohibition_polarity_mismatch",
                "A prohibition must retain negative polarity",
                "polarity",
                "deontic_semantics",
            )
        )
    if (
        norm_type in {"obligation", "permission"}
        and polarity == "negative"
        and force not in {"prohibition", None}
    ):
        issues.append(
            _issue(
                "deontic_polarity_mismatch",
                "Positive obligation/permission force cannot be marked negative",
                "polarity",
                "deontic_semantics",
            )
        )
    return issues


def _validate_nonempty_collection(
    payload: Mapping[str, Any], field_path: str, hook_id: str, code: str
) -> Sequence[LegalIRContractValidationIssue]:
    value = _path_get(payload, field_path)
    if (
        value is not _MISSING
        and isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and not value
    ):
        return (
            _issue(
                code,
                f"Field {field_path!r} requires at least one typed entry",
                field_path,
                hook_id,
            ),
        )
    return ()


def _validate_frame_relation(
    _contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    return ()  # Required-field validation supplies the complete typed relation gate.


def _validate_temporal(
    _contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    return _validate_nonempty_collection(
        payload, "temporal_anchors", "temporal_anchors", "missing_temporal_anchor"
    )


def _validate_cec(
    _contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    return _validate_nonempty_collection(
        payload,
        "lifecycle_transitions",
        "cec_lifecycle",
        "missing_lifecycle_transition",
    )


def _validate_kg(
    _contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    issues: list[LegalIRContractValidationIssue] = []
    nodes = payload.get("nodes")
    relationships = payload.get("relationships")
    if isinstance(nodes, Sequence) and not isinstance(nodes, (str, bytes, bytearray)):
        node_ids = {
            str(node.get("id"))
            for node in nodes
            if isinstance(node, Mapping) and node.get("id") not in (None, "")
        }
        for index, node in enumerate(nodes):
            if (
                not isinstance(node, Mapping)
                or not node.get("id")
                or not (node.get("type") or node.get("labels") or node.get("label"))
            ):
                issues.append(
                    _issue(
                        "untyped_graph_node",
                        "Each graph node requires an ID and a type or label",
                        f"nodes[{index}]",
                        "knowledge_graph_endpoints",
                    )
                )
        if isinstance(relationships, Sequence) and not isinstance(
            relationships, (str, bytes, bytearray)
        ):
            for index, edge in enumerate(relationships):
                if not isinstance(edge, Mapping):
                    issues.append(
                        _issue(
                            "untyped_graph_relationship",
                            "Each relationship must be an object",
                            f"relationships[{index}]",
                            "knowledge_graph_endpoints",
                        )
                    )
                    continue
                source = edge.get("source", edge.get("subject"))
                target = edge.get("target", edge.get("object"))
                edge_type = edge.get("type", edge.get("predicate"))
                if not source or not target or not edge_type:
                    issues.append(
                        _issue(
                            "untyped_graph_relationship",
                            "Each relationship requires source, target, and type",
                            f"relationships[{index}]",
                            "knowledge_graph_endpoints",
                        )
                    )
                elif node_ids and (
                    str(source) not in node_ids or str(target) not in node_ids
                ):
                    issues.append(
                        _issue(
                            "unknown_graph_endpoint",
                            "Relationship endpoints must reference declared node IDs",
                            f"relationships[{index}]",
                            "knowledge_graph_endpoints",
                        )
                    )
    return issues


def _validate_external(
    _contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    route = payload.get("backend_route")
    if route is not None and _is_empty(route):
        return (
            _issue(
                "empty_backend_route",
                "At least one bounded prover backend is required",
                "backend_route",
                "external_prover_route",
            ),
        )
    return ()


def _validate_decompiler(
    contract: LegalIRViewContract, payload: Mapping[str, Any]
) -> Sequence[LegalIRContractValidationIssue]:
    source_contract_id = str(
        payload.get("source_contract_id") or payload.get("contract_id") or ""
    )
    if source_contract_id and source_contract_id == contract.contract_id:
        return (
            _issue(
                "recursive_decompiler_contract",
                "source_contract_id must identify the decoded input view, not the decompiler contract",
                "source_contract_id",
                "decompiler_structure",
            ),
        )
    return ()


_VALIDATION_HOOK_IMPLEMENTATIONS: Mapping[str, ValidationHookCallable] = (
    MappingProxyType(
        {
            "required_fields": _validate_required_fields,
            "provenance_identifiers_only": _validate_provenance,
            "deontic_semantics": _validate_deontic,
            "frame_relation_typing": _validate_frame_relation,
            "temporal_anchors": _validate_temporal,
            "cec_lifecycle": _validate_cec,
            "knowledge_graph_endpoints": _validate_kg,
            "external_prover_route": _validate_external,
            "decompiler_structure": _validate_decompiler,
        }
    )
)


def _unique(values: Sequence[str] | Iterator[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _dedupe_issues(
    issues: Sequence[LegalIRContractValidationIssue],
) -> list[LegalIRContractValidationIssue]:
    seen: set[tuple[str, str, str]] = set()
    result: list[LegalIRContractValidationIssue] = []
    for issue in issues:
        key = (issue.code, issue.field_path, issue.hook_id)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _validate_registry(contracts: Sequence[LegalIRViewContract]) -> None:
    expected = {view.value for view in LegalIRView}
    actual = {contract.view.value for contract in contracts}
    if actual != expected:
        raise ValueError(
            f"Canonical LegalIR views differ: missing={expected - actual}, extra={actual - expected}"
        )
    for contract in contracts:
        if contract.schema_version != LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION:
            raise ValueError(f"Unexpected schema version for {contract.contract_id}")
        if (
            not contract.required_fields
            or not contract.obligation_families
            or not contract.cross_view_obligation_families
            or not contract.metric_families
        ):
            raise ValueError(f"Incomplete consumer families for {contract.contract_id}")
        if not contract.repair_lanes or not contract.validation_hooks:
            raise ValueError(
                f"Incomplete repair/validation contract for {contract.contract_id}"
            )
        if contract.provenance_requirements.source_text_policy != "identifiers_only":
            raise ValueError(f"Unsafe provenance policy for {contract.contract_id}")
        if (
            contract.provenance_requirements.identifier_field
            not in contract.required_field_names
        ):
            raise ValueError(
                f"Missing provenance required field for {contract.contract_id}"
            )
        if len(set(contract.allowed_repair_lanes)) != len(
            contract.allowed_repair_lanes
        ):
            raise ValueError(f"Duplicate repair lane in {contract.contract_id}")
        unknown_hooks = {hook.hook_id for hook in contract.validation_hooks} - set(
            _VALIDATION_HOOK_IMPLEMENTATIONS
        )
        if unknown_hooks:
            raise ValueError(
                f"Unknown validation hooks for {contract.contract_id}: {sorted(unknown_hooks)}"
            )


_validate_registry(_CONTRACTS)
LEGAL_IR_VIEW_CONTRACTS: Final = LegalIRViewContractRegistry(_CONTRACTS)
LEGAL_IR_VIEW_CONTRACT_REGISTRY: Final = LEGAL_IR_VIEW_CONTRACTS
CANONICAL_LEGAL_IR_VIEW_CONTRACTS: Final = _CONTRACTS
CANONICAL_LEGAL_IR_VIEW_NAMES: Final = tuple(
    contract.view.value for contract in _CONTRACTS
)
LEGAL_IR_VIEW_CONTRACT_IDS: Final = MappingProxyType(
    {contract.view.value: contract.contract_id for contract in _CONTRACTS}
)


def legal_ir_view_contracts() -> tuple[LegalIRViewContract, ...]:
    """Return canonical contracts in stable registry order."""

    return LEGAL_IR_VIEW_CONTRACTS.contracts()


def legal_ir_view_contract(view_or_alias: str | LegalIRView) -> LegalIRViewContract:
    """Resolve a view name, target component, alias, or stable contract ID."""

    return LEGAL_IR_VIEW_CONTRACTS[view_or_alias]


def legal_ir_view_contract_manifest() -> dict[str, Any]:
    """Return a deterministic JSON-ready manifest for downstream consumers."""

    return LEGAL_IR_VIEW_CONTRACTS.manifest()


def validate_legal_ir_view(
    view_or_alias: str | LegalIRView, payload: Mapping[str, Any] | Any
) -> LegalIRContractValidationResult:
    """Validate a view payload against its canonical contract."""

    return LEGAL_IR_VIEW_CONTRACTS.validate(view_or_alias, payload)


def legal_ir_codex_todo_projection(
    view_or_alias: str | LegalIRView, lane_id: str | None = None
) -> dict[str, Any]:
    """Project an identifier-only, path-bounded repair contract for Codex."""

    return LEGAL_IR_VIEW_CONTRACTS.codex_todo_projection(view_or_alias, lane_id)


__all__ = [
    "CANONICAL_LEGAL_IR_VIEW_CONTRACTS",
    "CANONICAL_LEGAL_IR_VIEW_NAMES",
    "LEGAL_IR_VIEW_CONTRACT_REGISTRY",
    "LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION",
    "LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION",
    "LEGAL_IR_VIEW_CONTRACTS",
    "LEGAL_IR_VIEW_CONTRACT_IDS",
    "LegalIRContractValidationIssue",
    "LegalIRContractValidationResult",
    "LegalIRFieldRequirement",
    "LegalIRModalitySemantics",
    "LegalIRProvenanceRequirements",
    "LegalIRRepairLane",
    "LegalIRValidationHook",
    "LegalIRView",
    "LegalIRViewContract",
    "LegalIRViewContractRegistry",
    "ValidationSeverity",
    "legal_ir_codex_todo_projection",
    "legal_ir_view_contract",
    "legal_ir_view_contract_manifest",
    "legal_ir_view_contracts",
    "validate_legal_ir_view",
]
