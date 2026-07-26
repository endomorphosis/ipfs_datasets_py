"""Extended, auditable semantic round-trip composition matrix.

This module registers the optional SRT composition layers without weakening
the frozen :mod:`benchmarks.semantic_roundtrip.matrix` scoring contract.
Every scoreable constructor arm is crossed with the deterministic, direct
Leanstral, and SyMAI-routed realizers.  Unsupported products are not silently
dropped: they are represented by typed :class:`OmittedComposition` records.

The core matrix remains the semantic authority for cases, losses, gates,
failure denominators, candidate CIDs, and post-hoc validation.  This module
adds composition coordinates and a complete execution receipt containing
component calls, model calls, fallbacks, validation actions, and exact
resource bindings.  All users of the one physical Leanstral service are
serialized through one lock.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.contracts import (
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
    RoundTripConstructor,
    RoundTripRealizer,
)
from benchmarks.semantic_roundtrip.matrix import (
    MatrixCase,
    MatrixCoordinateRecord,
    MatrixRunResult,
    PostHocValidator,
    SemanticRoundTripMatrix,
    default_post_hoc_validators,
)
from benchmarks.semantic_roundtrip_capabilities import (
    AUTOENCODER_EFFECTIVE_ARCHITECTURE,
    AUTOENCODER_STATE_CID,
    LEANSTRAL_BACKEND,
    LEANSTRAL_CAPACITY,
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LEANSTRAL_PROVIDER,
    SPACY_MODEL,
    SPACY_MODEL_VERSION,
    SPACY_PIPELINE,
    SYMAI_PROVIDER,
    SYMAI_VERSION,
)


EXTENDED_SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE: Final = (
    "ExtendedSemanticRoundTripMatrix@1"
)
SHARED_MODEL_RESOURCE_ID: Final = "leanstral-local-primary"
DEFAULT_BASE_CONSTRUCTOR_IDS: Final = ("typed_deontic", "modal_spacy")
DEFAULT_REALIZER_IDS: Final = (
    "deterministic",
    "leanstral_direct",
    "leanstral_symai",
)
_SHARED_MODEL_LOCK: Final = threading.RLock()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain(to_dict())
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _identity(component: object, role: str) -> str:
    value = getattr(component, "identity", None)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{role} identity must be a nonblank string")
    return value


def _sha256(value: object) -> str:
    encoded = repr(_plain(value)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GuidanceMode(str, Enum):
    """Autoencoder guidance intervention assigned to a constructor arm."""

    NO_GUIDANCE = "no_guidance"
    GUIDED = "guided"
    NOT_APPLICABLE = "not_applicable"


class RepairMode(str, Enum):
    """Learned-repair intervention assigned to a constructor arm."""

    NO_REPAIR = "no_repair"
    SELECTIVE = "selective"
    ALWAYS_ON = "always_on"


class ModelRoute(str, Enum):
    """How a model-backed action reaches the one Leanstral service."""

    DIRECT = "direct"
    SYMAI = "symai"
    NOT_APPLICABLE = "not_applicable"


class RealizerMode(str, Enum):
    """Whether the reverse stage is deterministic or model-backed."""

    DETERMINISTIC = "deterministic"
    MODEL = "model"


class OmissionReason(str, Enum):
    """Typed reasons for deliberately absent Cartesian products."""

    DETERMINISTIC_CONSTRUCTOR_HAS_NO_MODEL_ROUTE = (
        "deterministic_constructor_has_no_model_route"
    )
    SELECTIVE_REPAIR_HAS_NO_SYMAI_ROUTE = (
        "selective_repair_has_no_symai_route"
    )
    GUIDANCE_CANNOT_WRAP_ALWAYS_ON_MODEL = (
        "guidance_cannot_wrap_always_on_model"
    )
    BASE_CONSTRUCTOR_REPLACED_BY_ALWAYS_ON_MODEL = (
        "base_constructor_replaced_by_always_on_model"
    )
    VALIDATION_IS_NONSCORING_OVERLAY = "validation_is_nonscoring_overlay"


@dataclass(frozen=True, slots=True)
class CompositionSpec:
    """One scoreable forward-stage composition."""

    base_constructor_id: str
    guidance: GuidanceMode
    repair: RepairMode
    constructor_route: ModelRoute

    def __post_init__(self) -> None:
        if (
            not isinstance(self.base_constructor_id, str)
            or not self.base_constructor_id.strip()
        ):
            raise ContractError("base_constructor_id must be nonblank")
        for field, enum_type in (
            ("guidance", GuidanceMode),
            ("repair", RepairMode),
            ("constructor_route", ModelRoute),
        ):
            value = getattr(self, field)
            if not isinstance(value, enum_type):
                try:
                    object.__setattr__(self, field, enum_type(value))
                except (TypeError, ValueError) as exc:
                    raise ContractError(
                        f"composition {field} is invalid"
                    ) from exc
        if self.repair is RepairMode.ALWAYS_ON:
            if (
                self.base_constructor_id != "model"
                or self.guidance is not GuidanceMode.NOT_APPLICABLE
                or self.constructor_route
                not in {ModelRoute.DIRECT, ModelRoute.SYMAI}
            ):
                raise ContractError(
                    "always-on repair must be the model/not-applicable "
                    "composition with a direct or SyMAI route"
                )
        elif (
            self.base_constructor_id == "model"
            or self.guidance is GuidanceMode.NOT_APPLICABLE
            or self.constructor_route is not ModelRoute.NOT_APPLICABLE
        ):
            raise ContractError(
                "deterministic-base compositions require a guidance arm and "
                "a not-applicable constructor route"
            )

    @property
    def arm_id(self) -> str:
        return "__".join(
            (
                self.base_constructor_id,
                self.guidance.value,
                self.repair.value,
                self.constructor_route.value,
            )
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "arm_id": self.arm_id,
            "base_constructor_id": self.base_constructor_id,
            "guidance": self.guidance.value,
            "repair": self.repair.value,
            "constructor_route": self.constructor_route.value,
        }


@dataclass(frozen=True, slots=True)
class RealizerSpec:
    """One reverse-stage composition."""

    realizer_id: str
    mode: RealizerMode
    route: ModelRoute

    def __post_init__(self) -> None:
        if not isinstance(self.realizer_id, str) or not self.realizer_id.strip():
            raise ContractError("realizer_id must be nonblank")
        if not isinstance(self.mode, RealizerMode):
            object.__setattr__(self, "mode", RealizerMode(self.mode))
        if not isinstance(self.route, ModelRoute):
            object.__setattr__(self, "route", ModelRoute(self.route))
        if self.mode is RealizerMode.DETERMINISTIC:
            if self.route is not ModelRoute.NOT_APPLICABLE:
                raise ContractError(
                    "deterministic realizer route must be not_applicable"
                )
        elif self.route not in {ModelRoute.DIRECT, ModelRoute.SYMAI}:
            raise ContractError(
                "model realizer requires a direct or SyMAI route"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "realizer_id": self.realizer_id,
            "mode": self.mode.value,
            "route": self.route.value,
        }


@dataclass(frozen=True, slots=True)
class OmittedComposition:
    """A requested but impossible product, retained with a typed reason."""

    axes: Mapping[str, str]
    reason: OmissionReason
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, OmissionReason):
            object.__setattr__(self, "reason", OmissionReason(self.reason))
        if not isinstance(self.axes, Mapping) or not self.axes:
            raise ContractError("omitted composition axes must be nonempty")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ContractError("omitted composition detail must be nonblank")
        object.__setattr__(
            self,
            "axes",
            _freeze({str(key): str(value) for key, value in self.axes.items()}),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "axes": _plain(self.axes),
            "reason": self.reason.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ValidationOverlaySpec:
    """A proof action that can annotate but never change semantic scoring."""

    validator_id: str
    resource_identity: str
    applicable_when: str = "complete_nonempty_l1_l2"
    candidate_mutation_allowed: bool = False
    score_mutation_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.validator_id or not self.resource_identity:
            raise ContractError("validation overlay identities must be nonblank")
        if self.candidate_mutation_allowed or self.score_mutation_allowed:
            raise ContractError(
                "validation-only overlays cannot mutate candidates or scores"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "validator_id": self.validator_id,
            "resource_identity": self.resource_identity,
            "applicable_when": self.applicable_when,
            "candidate_mutation_allowed": False,
            "score_mutation_allowed": False,
        }


@dataclass(frozen=True, slots=True)
class ExtendedMatrixPlan:
    """Frozen inventory of included arms, realizers, overlays, and omissions."""

    compositions: tuple[CompositionSpec, ...]
    realizers: tuple[RealizerSpec, ...]
    validation_overlays: tuple[ValidationOverlaySpec, ...]
    omissions: tuple[OmittedComposition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "compositions", tuple(self.compositions))
        object.__setattr__(self, "realizers", tuple(self.realizers))
        object.__setattr__(
            self, "validation_overlays", tuple(self.validation_overlays)
        )
        object.__setattr__(self, "omissions", tuple(self.omissions))
        if not all(
            isinstance(item, CompositionSpec) for item in self.compositions
        ):
            raise ContractError("composition plan contains an invalid arm")
        if not all(
            isinstance(item, RealizerSpec) for item in self.realizers
        ):
            raise ContractError("composition plan contains an invalid realizer")
        if not all(
            isinstance(item, ValidationOverlaySpec)
            for item in self.validation_overlays
        ):
            raise ContractError("composition plan contains an invalid overlay")
        if not all(
            isinstance(item, OmittedComposition) for item in self.omissions
        ):
            raise ContractError("composition plan contains an invalid omission")
        arm_ids = [item.arm_id for item in self.compositions]
        realizer_ids = [item.realizer_id for item in self.realizers]
        validator_ids = [
            item.validator_id for item in self.validation_overlays
        ]
        if not self.compositions or len(set(arm_ids)) != len(arm_ids):
            raise ContractError("composition plan requires unique arms")
        if not self.realizers or len(set(realizer_ids)) != len(realizer_ids):
            raise ContractError("composition plan requires unique realizers")
        if len(set(validator_ids)) != len(validator_ids):
            raise ContractError("validation overlay ids must be unique")

    @property
    def cell_ids(self) -> tuple[str, ...]:
        return tuple(
            f"{composition.arm_id}__{realizer.realizer_id}"
            for composition in self.compositions
            for realizer in self.realizers
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "compositions": [item.to_dict() for item in self.compositions],
            "realizers": [item.to_dict() for item in self.realizers],
            "validation_overlays": [
                item.to_dict() for item in self.validation_overlays
            ],
            "omissions": [item.to_dict() for item in self.omissions],
            "cell_count": len(self.cell_ids),
        }


def build_extended_matrix_plan(
    *,
    base_constructor_ids: Sequence[str] = DEFAULT_BASE_CONSTRUCTOR_IDS,
    validator_ids: Sequence[str] = ("hammer_cvc5", "lean"),
) -> ExtendedMatrixPlan:
    """Build the preregistered matrix without pretending invalid products exist."""

    bases = tuple(base_constructor_ids)
    if (
        not bases
        or len(set(bases)) != len(bases)
        or any(not isinstance(item, str) or not item for item in bases)
    ):
        raise ContractError("base_constructor_ids must be unique and nonblank")

    compositions: list[CompositionSpec] = []
    for base_id in bases:
        for guidance in (
            GuidanceMode.NO_GUIDANCE,
            GuidanceMode.GUIDED,
        ):
            for repair in (RepairMode.NO_REPAIR, RepairMode.SELECTIVE):
                compositions.append(
                    CompositionSpec(
                        base_id,
                        guidance,
                        repair,
                        ModelRoute.NOT_APPLICABLE,
                    )
                )
    for route in (ModelRoute.DIRECT, ModelRoute.SYMAI):
        compositions.append(
            CompositionSpec(
                "model",
                GuidanceMode.NOT_APPLICABLE,
                RepairMode.ALWAYS_ON,
                route,
            )
        )

    realizers = (
        RealizerSpec(
            "deterministic",
            RealizerMode.DETERMINISTIC,
            ModelRoute.NOT_APPLICABLE,
        ),
        RealizerSpec(
            "leanstral_direct",
            RealizerMode.MODEL,
            ModelRoute.DIRECT,
        ),
        RealizerSpec(
            "leanstral_symai",
            RealizerMode.MODEL,
            ModelRoute.SYMAI,
        ),
    )
    overlay_resources = {
        "hammer_cvc5": "Hammer/cvc5 structural validator",
        "lean": "Lean native kernel validator",
    }
    overlays = tuple(
        ValidationOverlaySpec(
            validator_id,
            overlay_resources.get(
                validator_id, f"post-hoc validator:{validator_id}"
            ),
        )
        for validator_id in validator_ids
    )
    omissions: list[OmittedComposition] = []
    for base_id in bases:
        omissions.extend(
            (
                OmittedComposition(
                    {
                        "base_constructor_id": base_id,
                        "constructor_route": ModelRoute.SYMAI.value,
                    },
                    OmissionReason.DETERMINISTIC_CONSTRUCTOR_HAS_NO_MODEL_ROUTE,
                    "A deterministic constructor is invoked directly; SyMAI "
                    "routing is meaningful only for a model call.",
                ),
                OmittedComposition(
                    {
                        "base_constructor_id": base_id,
                        "repair": RepairMode.SELECTIVE.value,
                        "repair_route": ModelRoute.SYMAI.value,
                    },
                    OmissionReason.SELECTIVE_REPAIR_HAS_NO_SYMAI_ROUTE,
                    "The validated selective-repair contract binds direct "
                    "Leanstral and has no SyMAI repair adapter.",
                ),
            )
        )
    omissions.extend(
        (
            OmittedComposition(
                {
                    "guidance": GuidanceMode.GUIDED.value,
                    "repair": RepairMode.ALWAYS_ON.value,
                },
                OmissionReason.GUIDANCE_CANNOT_WRAP_ALWAYS_ON_MODEL,
                "Autoencoder guidance is a deterministic-constructor advisor, "
                "not an intervention over an always-on text-to-IR model.",
            ),
            OmittedComposition(
                {
                    "base_constructor_id": ",".join(bases),
                    "repair": RepairMode.ALWAYS_ON.value,
                },
                OmissionReason.BASE_CONSTRUCTOR_REPLACED_BY_ALWAYS_ON_MODEL,
                "The always-on arm replaces, rather than duplicates, each "
                "deterministic base constructor.",
            ),
            OmittedComposition(
                {
                    "axis": "validation",
                    "requested_product": "scored_candidate",
                },
                OmissionReason.VALIDATION_IS_NONSCORING_OVERLAY,
                "Post-hoc proof validation annotates a bound candidate and "
                "therefore is not multiplied into separate scored cells.",
            ),
        )
    )
    return ExtendedMatrixPlan(
        tuple(compositions),
        realizers,
        overlays,
        tuple(omissions),
    )


DEFAULT_EXTENDED_MATRIX_PLAN: Final = build_extended_matrix_plan()
EXTENDED_CONSTRUCTOR_IDS: Final = tuple(
    item.arm_id for item in DEFAULT_EXTENDED_MATRIX_PLAN.compositions
)
EXTENDED_REALIZER_IDS: Final = tuple(
    item.realizer_id for item in DEFAULT_EXTENDED_MATRIX_PLAN.realizers
)
EXPECTED_EXTENDED_CELL_IDS: Final = DEFAULT_EXTENDED_MATRIX_PLAN.cell_ids
EXTENDED_MATRIX_INTERFACE: Final = (
    EXTENDED_SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE
)


@dataclass(frozen=True, slots=True)
class ExtendedConstructorArm:
    spec: CompositionSpec
    component: RoundTripConstructor

    def __post_init__(self) -> None:
        if not isinstance(self.component, RoundTripConstructor):
            raise ContractError(
                "extended constructor must implement RoundTripConstructor"
            )
        _identity(self.component, "constructor")


@dataclass(frozen=True, slots=True)
class ExtendedRealizerArm:
    spec: RealizerSpec
    component: RoundTripRealizer

    def __post_init__(self) -> None:
        if not isinstance(self.component, RoundTripRealizer):
            raise ContractError(
                "extended realizer must implement RoundTripRealizer"
            )
        _identity(self.component, "realizer")


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def default_resource_identities() -> dict[str, object]:
    """Return exact static bindings used by default extended compositions."""

    return {
        "python": {
            "implementation": sys.implementation.name,
            "version": sys.version.split()[0],
        },
        "multiformats": {
            "distribution": "multiformats",
            "version": _package_version("multiformats"),
            "use": "dag-json and raw CID addressing",
        },
        "spacy_pipeline": {
            "model": SPACY_MODEL,
            "model_version": SPACY_MODEL_VERSION,
            "pipeline": list(SPACY_PIPELINE),
            "fallback_allowed": False,
        },
        "autoencoder_state": {
            "state_cid": AUTOENCODER_STATE_CID,
            "architecture": AUTOENCODER_EFFECTIVE_ARCHITECTURE,
            "read_only": True,
        },
        SHARED_MODEL_RESOURCE_ID: {
            "provider": LEANSTRAL_PROVIDER,
            "endpoint": LEANSTRAL_ENDPOINT,
            "model": LEANSTRAL_MODEL,
            "backend": LEANSTRAL_BACKEND,
            "capacity": LEANSTRAL_CAPACITY,
        },
        "symai_route": {
            "provider": SYMAI_PROVIDER,
            "version": SYMAI_VERSION,
            "inner_resource": SHARED_MODEL_RESOURCE_ID,
            "independent_model": False,
        },
    }


@dataclass(frozen=True, slots=True)
class _Invocation:
    sequence: int
    role: str
    component_identity: str
    request_cid: str
    status: str
    failure: Mapping[str, object] | None
    diagnostics: Mapping[str, object]
    model_calls: tuple[Mapping[str, object], ...]
    fallbacks: tuple[Mapping[str, object], ...]

    def to_dict(self, *, phase: str) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "phase": phase,
            "role": self.role,
            "component_identity": self.component_identity,
            "request_cid": self.request_cid,
            "status": self.status,
            "failure": _plain(self.failure),
            "diagnostics": _plain(self.diagnostics),
            "model_calls": _plain(self.model_calls),
            "fallbacks": _plain(self.fallbacks),
        }


class _ExecutionLedger:
    def __init__(self) -> None:
        # All runner instances share this process-wide lock because they bind
        # the same one-capacity physical service.
        self.lock = _SHARED_MODEL_LOCK
        self._sequence = 0
        self._model_sequence = 0

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def bind_model_calls(
        self,
        calls: Sequence[Mapping[str, object]],
        *,
        role: str,
        component_identity: str,
        request_cid: str,
        status: str,
    ) -> tuple[Mapping[str, object], ...]:
        bound: list[Mapping[str, object]] = []
        for raw in calls:
            self._model_sequence += 1
            value = dict(_plain(raw))  # type: ignore[arg-type]
            value.setdefault(
                "call_id",
                _sha256(
                    {
                        "role": role,
                        "component_identity": component_identity,
                        "request_cid": request_cid,
                        "model_sequence": self._model_sequence,
                    }
                ),
            )
            value.update(
                {
                    "slot_sequence": self._model_sequence,
                    "resource_id": SHARED_MODEL_RESOURCE_ID,
                    "shared_capacity": LEANSTRAL_CAPACITY,
                    "serialized": True,
                }
            )
            value.setdefault("status", status)
            value.setdefault("endpoint", LEANSTRAL_ENDPOINT)
            value.setdefault("model", LEANSTRAL_MODEL)
            bound.append(_freeze(value))  # type: ignore[arg-type]
        return tuple(bound)


def _diagnostic_value(value: object) -> dict[str, object]:
    if value is None:
        return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        plain = _plain(to_dict())
    else:
        plain = _plain(value)
    return plain if isinstance(plain, dict) else {"value": plain}


def _nested_receipts(component: object) -> dict[str, object]:
    receipts: dict[str, object] = {}
    last = getattr(component, "last_receipt", None)
    if last is not None:
        receipts["route"] = _diagnostic_value(last)
    nested = getattr(component, "base_constructor", None)
    if nested is not None and nested is not component:
        nested_last = getattr(nested, "last_diagnostics", None)
        if nested_last:
            receipts["baseline"] = _plain(nested_last)
        deeper = _nested_receipts(nested)
        if deeper:
            receipts["baseline_component"] = deeper
    return receipts


def _find_model_calls(value: object) -> list[Mapping[str, object]]:
    calls: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "model_calls" and isinstance(item, (tuple, list)):
                calls.extend(
                    dict(candidate)
                    for candidate in item
                    if isinstance(candidate, Mapping)
                )
            else:
                calls.extend(_find_model_calls(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            calls.extend(_find_model_calls(item))
    return calls


def _find_fallbacks(
    value: object, path: str = "diagnostics"
) -> list[Mapping[str, object]]:
    fallbacks: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key == "fallback_used" and isinstance(item, bool):
                fallbacks.append(
                    {
                        "path": child,
                        "used": item,
                        "policy": "declared_component_diagnostic",
                    }
                )
            else:
                fallbacks.extend(_find_fallbacks(item, child))
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            fallbacks.extend(_find_fallbacks(item, f"{path}[{index}]"))
    return fallbacks


def _find_structural_validations(
    value: object,
) -> list[Mapping[str, object]]:
    """Extract every selective-repair proof-tool action from nested receipts."""

    actions: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "structural_receipts" and isinstance(
                item, (tuple, list)
            ):
                actions.extend(
                    dict(receipt)
                    for receipt in item
                    if isinstance(receipt, Mapping)
                )
            else:
                actions.extend(_find_structural_validations(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            actions.extend(_find_structural_validations(item))
    return actions


def _uses_model(component: object) -> bool:
    provider = getattr(component, "provider_id", None)
    if isinstance(provider, str) and provider:
        return True
    nested = getattr(component, "base_constructor", None)
    return bool(nested is not None and nested is not component and _uses_model(nested))


def _is_selective(component: object) -> bool:
    return "SelectiveLeanstralRepair" in _identity(component, "constructor")


def _one_implicit_model_call(
    component: object, diagnostics: Mapping[str, object]
) -> bool:
    if not _uses_model(component) or _find_model_calls(diagnostics):
        return False
    if _is_selective(component):
        # A not-triggered or baseline-failed selective arm made no model call.
        return False
    return True


class _DiagnosticConstructorDelegate:
    """Preserve nested diagnostics when a repair wrapper calls its baseline."""

    def __init__(self, component: RoundTripConstructor) -> None:
        self._component = component
        self.last_diagnostics: Mapping[str, object] = MappingProxyType({})

    @property
    def identity(self) -> str:
        return _identity(self._component, "constructor")

    @property
    def base_constructor(self) -> RoundTripConstructor:
        """Expose the wrapped component for recursive receipt collection."""

        return self._component

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        method = getattr(self._component, "construct_with_diagnostics", None)
        if callable(method):
            outcome = method(request)
            result = getattr(outcome, "result", None)
            diagnostics = getattr(
                outcome, "diagnostics", getattr(outcome, "receipt", None)
            )
            if isinstance(result, ConstructorResult):
                self.last_diagnostics = _freeze(
                    _diagnostic_value(diagnostics)
                )  # type: ignore[assignment]
                return result
        self.last_diagnostics = MappingProxyType({})
        return self._component.construct(request)


class _TracingConstructor:
    def __init__(
        self, component: RoundTripConstructor, ledger: _ExecutionLedger
    ) -> None:
        self.component = component
        self.ledger = ledger
        self.invocations: list[_Invocation] = []

    @property
    def identity(self) -> str:
        return _identity(self.component, "constructor")

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        request_cid = cid_for_dag_json(request.to_payload())
        method = getattr(self.component, "construct_with_diagnostics", None)
        diagnostic: object = None
        lock = self.ledger.lock if _uses_model(self.component) else _NullLock()
        try:
            with lock:
                if callable(method):
                    outcome = method(request)
                    result = getattr(outcome, "result", None)
                    diagnostic = getattr(
                        outcome,
                        "diagnostics",
                        getattr(outcome, "receipt", None),
                    )
                else:
                    result = self.component.construct(request)
            if not isinstance(result, ConstructorResult):
                result = ConstructorResult(
                    ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail=(
                        "constructor returned a non-ConstructorResult"
                    ),
                )
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            result = ConstructorResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.EXCEPTION,
                failure_detail=(
                    f"constructor raised {type(exc).__name__}"
                )[:1000],
            )
            diagnostic = {
                "trace_capture": "component_exception",
                "exception_type": type(exc).__name__,
            }
        diagnostics = _diagnostic_value(diagnostic)
        receipts = _nested_receipts(self.component)
        if receipts:
            diagnostics["component_receipts"] = receipts
        model_calls = _find_model_calls(diagnostics)
        if _one_implicit_model_call(self.component, diagnostics):
            model_calls.append(
                {
                    "role": "constructor",
                    "route": (
                        "symai"
                        if "symai" in self.identity.lower()
                        else "direct"
                    ),
                    "provider_id": getattr(
                        self.component, "provider_id", LEANSTRAL_PROVIDER
                    ),
                    "outcome": result.status.value,
                }
            )
        fallbacks = _find_fallbacks(diagnostics)
        if not fallbacks:
            fallbacks.append(
                {
                    "path": "component",
                    "used": False,
                    "policy": "fail_closed_no_undeclared_fallback",
                }
            )
        failure = (
            None
            if result.failure_reason is None
            else {
                "reason": result.failure_reason.value,
                "detail": result.failure_detail,
            }
        )
        invocation = _Invocation(
            sequence=self.ledger.next_sequence(),
            role="constructor",
            component_identity=self.identity,
            request_cid=request_cid,
            status=result.status.value,
            failure=_freeze(failure) if failure else None,  # type: ignore[arg-type]
            diagnostics=_freeze(diagnostics),  # type: ignore[arg-type]
            model_calls=self.ledger.bind_model_calls(
                model_calls,
                role="constructor",
                component_identity=self.identity,
                request_cid=request_cid,
                status=result.status.value,
            ),
            fallbacks=tuple(
                _freeze(item) for item in fallbacks
            ),  # type: ignore[arg-type]
        )
        self.invocations.append(invocation)
        return result


class _TracingRealizer:
    def __init__(
        self, component: RoundTripRealizer, ledger: _ExecutionLedger
    ) -> None:
        self.component = component
        self.ledger = ledger
        self.invocations: list[_Invocation] = []

    @property
    def identity(self) -> str:
        return _identity(self.component, "realizer")

    def realize(self, request: RealizerRequest) -> RealizerResult:
        request_cid = cid_for_dag_json(request.to_payload())
        lock = self.ledger.lock if _uses_model(self.component) else _NullLock()
        try:
            with lock:
                result = self.component.realize(request)
            if not isinstance(result, RealizerResult):
                result = RealizerResult(
                    ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail="realizer returned a non-RealizerResult",
                )
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            result = RealizerResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.EXCEPTION,
                failure_detail=(
                    f"realizer raised {type(exc).__name__}"
                )[:1000],
            )
        diagnostics = _nested_receipts(self.component)
        model_calls: list[Mapping[str, object]] = []
        if _uses_model(self.component):
            model_calls.append(
                {
                    "role": "realizer",
                    "route": (
                        "symai"
                        if "symai" in self.identity.lower()
                        else "direct"
                    ),
                    "provider_id": getattr(
                        self.component, "provider_id", LEANSTRAL_PROVIDER
                    ),
                    "outcome": result.status.value,
                    "route_receipt": diagnostics.get("route"),
                }
            )
        failure = (
            None
            if result.failure_reason is None
            else {
                "reason": result.failure_reason.value,
                "detail": result.failure_detail,
            }
        )
        self.invocations.append(
            _Invocation(
                sequence=self.ledger.next_sequence(),
                role="realizer",
                component_identity=self.identity,
                request_cid=request_cid,
                status=result.status.value,
                failure=_freeze(failure) if failure else None,  # type: ignore[arg-type]
                diagnostics=_freeze(diagnostics),  # type: ignore[arg-type]
                model_calls=self.ledger.bind_model_calls(
                    model_calls,
                    role="realizer",
                    component_identity=self.identity,
                    request_cid=request_cid,
                    status=result.status.value,
                ),
                fallbacks=(
                    _freeze(
                        {
                            "path": "component",
                            "used": False,
                            "policy": "fail_closed_no_undeclared_fallback",
                        }
                    ),
                ),  # type: ignore[arg-type]
            )
        )
        return result


class _NullLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None


@dataclass(frozen=True, slots=True)
class ExtendedCoordinateRecord:
    """One core-scored coordinate plus its full causal execution receipt."""

    composition: CompositionSpec
    realizer: RealizerSpec
    semantic_record: MatrixCoordinateRecord
    execution: Mapping[str, object]
    record_cid: str

    @property
    def cell_id(self) -> str:
        return self.semantic_record.cell_id

    @property
    def result(self):
        return self.semantic_record.result

    @property
    def status(self) -> ComponentStatus:
        return self.semantic_record.status

    @property
    def primary_loss(self) -> float:
        return self.semantic_record.primary_loss

    @property
    def candidate_cid(self) -> str:
        return self.semantic_record.candidate_cid

    @property
    def cid(self) -> str:
        return self.record_cid

    @property
    def coordinate_cid(self) -> str:
        return self.record_cid

    def _payload(self) -> dict[str, object]:
        return {
            "interface": EXTENDED_SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE,
            "composition": self.composition.to_dict(),
            "realizer": self.realizer.to_dict(),
            "semantic_record": self.semantic_record.to_dict(),
            "execution": _plain(self.execution),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "record_cid": self.record_cid}


@dataclass(frozen=True, slots=True)
class ExtendedCaseRecord:
    case_id: str
    case_cid: str
    source_text_cid: str
    gold_ir_cid: str
    coordinates: tuple[ExtendedCoordinateRecord, ...]
    record_cid: str

    @property
    def cid(self) -> str:
        return self.record_cid

    def _payload(self) -> dict[str, object]:
        return {
            "interface": EXTENDED_SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE,
            "case_id": self.case_id,
            "case_cid": self.case_cid,
            "source_text_cid": self.source_text_cid,
            "gold_ir_cid": self.gold_ir_cid,
            "coordinate_count": len(self.coordinates),
            "coordinates": [item.to_dict() for item in self.coordinates],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "record_cid": self.record_cid}


@dataclass(frozen=True, slots=True)
class ExtendedMatrixRunResult:
    plan: ExtendedMatrixPlan
    cases: tuple[ExtendedCaseRecord, ...]
    summaries: Mapping[str, object]
    resource_identities: Mapping[str, object]
    core_run_cid: str
    run_cid: str

    @property
    def cid(self) -> str:
        return self.run_cid

    @property
    def coordinates(self) -> tuple[ExtendedCoordinateRecord, ...]:
        return tuple(
            coordinate
            for case in self.cases
            for coordinate in case.coordinates
        )

    def _payload(self) -> dict[str, object]:
        return {
            "interface": EXTENDED_SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE,
            "plan": self.plan.to_dict(),
            "case_count": len(self.cases),
            "cases": [case.to_dict() for case in self.cases],
            "summaries": _plain(self.summaries),
            "resource_identities": _plain(self.resource_identities),
            "core_run_cid": self.core_run_cid,
            "scoring_contract": {
                "implementation": "SemanticRoundTripMatrix@1",
                "identical_cases": True,
                "identical_primary_loss": True,
                "failures_retained_in_denominators": True,
                "validation_changes_scores": False,
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "run_cid": self.run_cid}


class ExtendedSemanticRoundTripMatrix:
    """Run the extended registry through the unchanged core matrix scorer."""

    interface: Final = EXTENDED_SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE

    def __init__(
        self,
        constructor_arms: (
            Sequence[ExtendedConstructorArm]
            | Mapping[str, RoundTripConstructor]
        ),
        realizer_arms: (
            Sequence[ExtendedRealizerArm]
            | Mapping[str, RoundTripRealizer]
        ),
        *,
        plan: ExtendedMatrixPlan | None = None,
        constructor_configs: Mapping[str, Mapping[str, object]] | None = None,
        realizer_configs: Mapping[str, Mapping[str, object]] | None = None,
        validators: Mapping[str, PostHocValidator] | None = None,
        resource_identities: Mapping[str, object] | None = None,
    ) -> None:
        registry_plan = plan or DEFAULT_EXTENDED_MATRIX_PLAN
        if isinstance(constructor_arms, Mapping):
            constructor_registry = dict(constructor_arms)
            expected = {
                item.arm_id for item in registry_plan.compositions
            }
            if set(constructor_registry) != expected:
                raise ContractError(
                    "constructor registry must equal the extended plan"
                )
            self._constructor_arms = tuple(
                ExtendedConstructorArm(
                    item, constructor_registry[item.arm_id]
                )
                for item in registry_plan.compositions
            )
        else:
            self._constructor_arms = tuple(constructor_arms)
        if isinstance(realizer_arms, Mapping):
            realizer_registry = dict(realizer_arms)
            expected = {
                item.realizer_id for item in registry_plan.realizers
            }
            if set(realizer_registry) != expected:
                raise ContractError(
                    "realizer registry must equal the extended plan"
                )
            self._realizer_arms = tuple(
                ExtendedRealizerArm(
                    item, realizer_registry[item.realizer_id]
                )
                for item in registry_plan.realizers
            )
        else:
            self._realizer_arms = tuple(realizer_arms)
        if not self._constructor_arms or not self._realizer_arms:
            raise ContractError(
                "extended matrix requires constructor and realizer arms"
            )
        constructor_ids = [item.spec.arm_id for item in self._constructor_arms]
        realizer_ids = [
            item.spec.realizer_id for item in self._realizer_arms
        ]
        if len(set(constructor_ids)) != len(constructor_ids):
            raise ContractError("extended constructor arm ids must be unique")
        if len(set(realizer_ids)) != len(realizer_ids):
            raise ContractError("extended realizer ids must be unique")
        selected_validators = (
            default_post_hoc_validators()
            if validators is None
            else dict(validators)
        )
        inferred_compositions = tuple(
            item.spec for item in self._constructor_arms
        )
        inferred_realizers = tuple(item.spec for item in self._realizer_arms)
        default_shape = (
            [item.arm_id for item in inferred_compositions]
            == list(EXTENDED_CONSTRUCTOR_IDS)
            and [item.realizer_id for item in inferred_realizers]
            == list(EXTENDED_REALIZER_IDS)
        )
        selected_plan = plan or ExtendedMatrixPlan(
            inferred_compositions,
            inferred_realizers,
            tuple(
                ValidationOverlaySpec(
                    validator_id,
                    _identity(validator, "validator")
                    if isinstance(getattr(validator, "identity", None), str)
                    else f"post-hoc validator:{validator_id}",
                )
                for validator_id, validator in selected_validators.items()
            ),
            (
                DEFAULT_EXTENDED_MATRIX_PLAN.omissions
                if default_shape
                else ()
            ),
        )
        if constructor_ids != [
            item.arm_id for item in selected_plan.compositions
        ]:
            raise ContractError(
                "constructor registry order must equal the extended plan"
            )
        if realizer_ids != [
            item.realizer_id for item in selected_plan.realizers
        ]:
            raise ContractError(
                "realizer registry order must equal the extended plan"
            )
        if set(selected_validators) != {
            item.validator_id for item in selected_plan.validation_overlays
        }:
            raise ContractError(
                "validator registry must equal the plan's overlays"
            )
        self.plan = selected_plan
        self._constructor_configs = dict(constructor_configs or {})
        self._realizer_configs = dict(realizer_configs or {})
        self._validators = selected_validators
        resources = default_resource_identities()
        if resource_identities:
            resources.update(
                dict(_plain(resource_identities))  # type: ignore[arg-type]
            )
        for overlay in self.plan.validation_overlays:
            resources[f"validator:{overlay.validator_id}"] = {
                "identity": overlay.resource_identity,
                "validation_only": True,
            }
        self._resources = _freeze(resources)

    @property
    def cell_ids(self) -> tuple[str, ...]:
        return self.plan.cell_ids

    def _core_run(
        self, cases: Sequence[MatrixCase]
    ) -> tuple[
        MatrixRunResult,
        dict[str, _TracingConstructor],
        dict[str, _TracingRealizer],
    ]:
        ledger = _ExecutionLedger()
        constructors = {
            arm.spec.arm_id: _TracingConstructor(arm.component, ledger)
            for arm in self._constructor_arms
        }
        realizers = {
            arm.spec.realizer_id: _TracingRealizer(arm.component, ledger)
            for arm in self._realizer_arms
        }
        core = SemanticRoundTripMatrix(
            constructors,
            realizers,
            constructor_configs=self._constructor_configs,
            realizer_configs=self._realizer_configs,
            validators=self._validators,
            require_eight_cells=False,
        ).run(cases)
        return core, constructors, realizers

    def run(
        self, cases: Sequence[MatrixCase]
    ) -> ExtendedMatrixRunResult:
        core, constructors, realizers = self._core_run(cases)
        constructor_cursor = {key: 0 for key in constructors}
        realizer_cursor = {key: 0 for key in realizers}
        extended_cases: list[ExtendedCaseRecord] = []

        for core_case in core.cases:
            coordinates: list[ExtendedCoordinateRecord] = []
            for constructor_arm in self._constructor_arms:
                constructor_id = constructor_arm.spec.arm_id
                constructor_trace = constructors[constructor_id].invocations
                initial_index = constructor_cursor[constructor_id]
                initial = constructor_trace[initial_index]
                constructor_cursor[constructor_id] += 1
                for realizer_arm in self._realizer_arms:
                    realizer_id = realizer_arm.spec.realizer_id
                    semantic = next(
                        item
                        for item in core_case.coordinates
                        if item.constructor_id == constructor_id
                        and item.realizer_id == realizer_id
                    )
                    calls: list[dict[str, object]] = [
                        initial.to_dict(phase="t0_to_l1")
                    ]
                    if semantic.result.l1 is not None:
                        index = realizer_cursor[realizer_id]
                        realized = realizers[realizer_id].invocations[index]
                        realizer_cursor[realizer_id] += 1
                        calls.append(realized.to_dict(phase="l1_to_t1"))
                    if semantic.result.reconstruction is not None:
                        index = constructor_cursor[constructor_id]
                        reapplied = constructor_trace[index]
                        constructor_cursor[constructor_id] += 1
                        calls.append(reapplied.to_dict(phase="t1_to_l2"))

                    validation_actions = [
                        {
                            "phase": "selective_candidate_structural_filter",
                            "candidate_mutation_allowed": False,
                            "score_mutation_allowed": False,
                            "semantic_authority": False,
                            "receipt": _plain(receipt),
                        }
                        for call in calls
                        for receipt in _find_structural_validations(
                            call["diagnostics"]
                        )
                    ]
                    validation_results = semantic.validation["results"]
                    assert isinstance(validation_results, Mapping)
                    for overlay in self.plan.validation_overlays:
                        receipt = validation_results[overlay.validator_id]
                        validation_actions.append(
                            {
                                **overlay.to_dict(),
                                "phase": (
                                    "post_hoc_after_candidate_binding"
                                ),
                                "candidate_cid": semantic.candidate_cid,
                                "candidate_unchanged": semantic.validation[
                                    "candidate_unchanged"
                                ],
                                "receipt": _plain(receipt),
                            }
                        )
                    execution = {
                        "component_calls": calls,
                        "model_calls": [
                            model_call
                            for call in calls
                            for model_call in call[  # type: ignore[union-attr]
                                "model_calls"
                            ]
                        ],
                        "fallbacks": [
                            fallback
                            for call in calls
                            for fallback in call[  # type: ignore[union-attr]
                                "fallbacks"
                            ]
                        ],
                        "validation_actions": validation_actions,
                        "resource_identities": _plain(self._resources),
                        "single_model_slot": {
                            "resource_id": SHARED_MODEL_RESOURCE_ID,
                            "capacity": LEANSTRAL_CAPACITY,
                            "all_calls_serialized": True,
                        },
                    }
                    provisional = ExtendedCoordinateRecord(
                        composition=constructor_arm.spec,
                        realizer=realizer_arm.spec,
                        semantic_record=semantic,
                        execution=_freeze(execution),  # type: ignore[arg-type]
                        record_cid="",
                    )
                    coordinates.append(
                        ExtendedCoordinateRecord(
                            composition=provisional.composition,
                            realizer=provisional.realizer,
                            semantic_record=provisional.semantic_record,
                            execution=provisional.execution,
                            record_cid=cid_for_dag_json(
                                provisional._payload()
                            ),
                        )
                    )
            provisional_case = ExtendedCaseRecord(
                case_id=core_case.case_id,
                case_cid=core_case.case_cid,
                source_text_cid=core_case.source_text_cid,
                gold_ir_cid=core_case.gold_ir_cid,
                coordinates=tuple(coordinates),
                record_cid="",
            )
            extended_cases.append(
                ExtendedCaseRecord(
                    case_id=provisional_case.case_id,
                    case_cid=provisional_case.case_cid,
                    source_text_cid=provisional_case.source_text_cid,
                    gold_ir_cid=provisional_case.gold_ir_cid,
                    coordinates=provisional_case.coordinates,
                    record_cid=cid_for_dag_json(
                        provisional_case._payload()
                    ),
                )
            )

        if any(
            constructor_cursor[key] != len(component.invocations)
            for key, component in constructors.items()
        ) or any(
            realizer_cursor[key] != len(component.invocations)
            for key, component in realizers.items()
        ):
            raise ContractError("execution trace did not map one-to-one to cells")

        provisional = ExtendedMatrixRunResult(
            plan=self.plan,
            cases=tuple(extended_cases),
            summaries=core.summaries,
            resource_identities=self._resources,  # type: ignore[arg-type]
            core_run_cid=core.run_cid,
            run_cid="",
        )
        return ExtendedMatrixRunResult(
            plan=provisional.plan,
            cases=provisional.cases,
            summaries=provisional.summaries,
            resource_identities=provisional.resource_identities,
            core_run_cid=provisional.core_run_cid,
            run_cid=cid_for_dag_json(provisional._payload()),
        )


def default_extended_component_arms(
    *,
    leanstral_client: object | None = None,
    symai_client: object | None = None,
    guidance_applicators: Mapping[str, Callable[..., object]] | None = None,
) -> tuple[
    tuple[ExtendedConstructorArm, ...],
    tuple[ExtendedRealizerArm, ...],
]:
    """Instantiate every scoreable default arm in preregistered order."""

    from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
        make_autoencoder_guidance_pair,
    )
    from benchmarks.semantic_roundtrip.constructors.leanstral import (
        LeanstralCanonicalConstructor,
    )
    from benchmarks.semantic_roundtrip.constructors.modal_spacy import (
        ModalSpacyCanonicalConstructor,
    )
    from benchmarks.semantic_roundtrip.constructors.symai import (
        SyMAICanonicalConstructor,
    )
    from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
        TypedDeonticCanonicalConstructor,
    )
    from benchmarks.semantic_roundtrip.realizers.deterministic import (
        CanonicalDeterministicRealizer,
    )
    from benchmarks.semantic_roundtrip.realizers.leanstral import (
        LeanstralCanonicalRealizer,
    )
    from benchmarks.semantic_roundtrip.realizers.symai import (
        SyMAICanonicalRealizer,
    )
    from benchmarks.semantic_roundtrip.selective_repair import (
        SelectiveLeanstralRepair,
    )

    raw_bases: dict[str, RoundTripConstructor] = {
        "typed_deontic": TypedDeonticCanonicalConstructor(),
        "modal_spacy": ModalSpacyCanonicalConstructor(),
    }
    applicators = dict(guidance_applicators or {})
    constructors: list[ExtendedConstructorArm] = []
    for base_id, raw_base in raw_bases.items():
        # Preserve frontend diagnostics (notably spaCy fallback evidence)
        # through both the autoencoder and repair wrapper layers.
        base = _DiagnosticConstructorDelegate(raw_base)
        pair = make_autoencoder_guidance_pair(
            base,
            guidance_applicator=applicators.get(base_id),
        )
        paired = {
            GuidanceMode.NO_GUIDANCE: pair.no_guidance,
            GuidanceMode.GUIDED: pair.guidance,
        }
        for guidance, component in paired.items():
            no_repair = CompositionSpec(
                base_id,
                guidance,
                RepairMode.NO_REPAIR,
                ModelRoute.NOT_APPLICABLE,
            )
            constructors.append(ExtendedConstructorArm(no_repair, component))
            diagnostic_baseline = _DiagnosticConstructorDelegate(component)
            selective_component = SelectiveLeanstralRepair(
                diagnostic_baseline,
                client=leanstral_client,  # type: ignore[arg-type]
            )
            selective = CompositionSpec(
                base_id,
                guidance,
                RepairMode.SELECTIVE,
                ModelRoute.NOT_APPLICABLE,
            )
            constructors.append(
                ExtendedConstructorArm(selective, selective_component)
            )
    constructors.extend(
        (
            ExtendedConstructorArm(
                CompositionSpec(
                    "model",
                    GuidanceMode.NOT_APPLICABLE,
                    RepairMode.ALWAYS_ON,
                    ModelRoute.DIRECT,
                ),
                LeanstralCanonicalConstructor(
                    leanstral_client  # type: ignore[arg-type]
                ),
            ),
            ExtendedConstructorArm(
                CompositionSpec(
                    "model",
                    GuidanceMode.NOT_APPLICABLE,
                    RepairMode.ALWAYS_ON,
                    ModelRoute.SYMAI,
                ),
                SyMAICanonicalConstructor(
                    symai_client  # type: ignore[arg-type]
                ),
            ),
        )
    )
    realizers = (
        ExtendedRealizerArm(
            RealizerSpec(
                "deterministic",
                RealizerMode.DETERMINISTIC,
                ModelRoute.NOT_APPLICABLE,
            ),
            CanonicalDeterministicRealizer(),
        ),
        ExtendedRealizerArm(
            RealizerSpec(
                "leanstral_direct",
                RealizerMode.MODEL,
                ModelRoute.DIRECT,
            ),
            LeanstralCanonicalRealizer(
                leanstral_client  # type: ignore[arg-type]
            ),
        ),
        ExtendedRealizerArm(
            RealizerSpec(
                "leanstral_symai",
                RealizerMode.MODEL,
                ModelRoute.SYMAI,
            ),
            SyMAICanonicalRealizer(
                symai_client  # type: ignore[arg-type]
            ),
        ),
    )
    return tuple(constructors), realizers


def default_extended_matrix(
    *,
    leanstral_client: object | None = None,
    symai_client: object | None = None,
    guidance_applicators: Mapping[str, Callable[..., object]] | None = None,
    validators: Mapping[str, PostHocValidator] | None = None,
) -> ExtendedSemanticRoundTripMatrix:
    """Create the complete default matrix, retaining unavailable arms."""

    selected_validators = (
        default_post_hoc_validators()
        if validators is None
        else dict(validators)
    )
    plan = build_extended_matrix_plan(
        validator_ids=tuple(selected_validators)
    )
    constructors, realizers = default_extended_component_arms(
        leanstral_client=leanstral_client,
        symai_client=symai_client,
        guidance_applicators=guidance_applicators,
    )
    return ExtendedSemanticRoundTripMatrix(
        constructors,
        realizers,
        plan=plan,
        validators=selected_validators,
    )


def default_extended_component_registries(
    *,
    leanstral_client: object | None = None,
    symai_client: object | None = None,
    guidance_applicators: Mapping[str, Callable[..., object]] | None = None,
) -> tuple[
    dict[str, RoundTripConstructor],
    dict[str, RoundTripRealizer],
]:
    """Return default components in the mapping form used by the core runner."""

    constructors, realizers = default_extended_component_arms(
        leanstral_client=leanstral_client,
        symai_client=symai_client,
        guidance_applicators=guidance_applicators,
    )
    return (
        {item.spec.arm_id: item.component for item in constructors},
        {item.spec.realizer_id: item.component for item in realizers},
    )


def run_extended_matrix(
    cases: Sequence[MatrixCase],
    constructor_arms: (
        Sequence[ExtendedConstructorArm]
        | Mapping[str, RoundTripConstructor]
    ),
    realizer_arms: (
        Sequence[ExtendedRealizerArm]
        | Mapping[str, RoundTripRealizer]
    ),
    *,
    plan: ExtendedMatrixPlan | None = None,
    constructor_configs: Mapping[str, Mapping[str, object]] | None = None,
    realizer_configs: Mapping[str, Mapping[str, object]] | None = None,
    validators: Mapping[str, PostHocValidator] | None = None,
    resource_identities: Mapping[str, object] | None = None,
) -> ExtendedMatrixRunResult:
    """One-call convenience wrapper for an explicit extended registry."""

    return ExtendedSemanticRoundTripMatrix(
        constructor_arms,
        realizer_arms,
        plan=plan,
        constructor_configs=constructor_configs,
        realizer_configs=realizer_configs,
        validators=validators,
        resource_identities=resource_identities,
    ).run(cases)


# Concise compatibility names for benchmark callers.
ExtendedMatrixRunner = ExtendedSemanticRoundTripMatrix
ExtendedMatrixResult = ExtendedMatrixRunResult
ExtendedMatrixCellResult = ExtendedCoordinateRecord
ExtendedMatrixCaseResult = ExtendedCaseRecord
build_plan = build_extended_matrix_plan


__all__ = [
    "EXTENDED_SEMANTIC_ROUND_TRIP_MATRIX_INTERFACE",
    "SHARED_MODEL_RESOURCE_ID",
    "DEFAULT_BASE_CONSTRUCTOR_IDS",
    "DEFAULT_REALIZER_IDS",
    "DEFAULT_EXTENDED_MATRIX_PLAN",
    "EXTENDED_MATRIX_INTERFACE",
    "EXTENDED_CONSTRUCTOR_IDS",
    "EXTENDED_REALIZER_IDS",
    "EXPECTED_EXTENDED_CELL_IDS",
    "GuidanceMode",
    "RepairMode",
    "ModelRoute",
    "RealizerMode",
    "OmissionReason",
    "CompositionSpec",
    "RealizerSpec",
    "OmittedComposition",
    "ValidationOverlaySpec",
    "ExtendedMatrixPlan",
    "ExtendedConstructorArm",
    "ExtendedRealizerArm",
    "ExtendedCoordinateRecord",
    "ExtendedCaseRecord",
    "ExtendedMatrixRunResult",
    "ExtendedSemanticRoundTripMatrix",
    "ExtendedMatrixRunner",
    "ExtendedMatrixResult",
    "ExtendedMatrixCellResult",
    "ExtendedMatrixCaseResult",
    "build_extended_matrix_plan",
    "build_plan",
    "default_resource_identities",
    "default_extended_component_arms",
    "default_extended_component_registries",
    "default_extended_matrix",
    "run_extended_matrix",
]
