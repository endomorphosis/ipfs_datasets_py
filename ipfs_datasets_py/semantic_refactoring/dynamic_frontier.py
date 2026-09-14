"""SPAR-008 dynamic Python frontier and hermetic runtime evidence adapters.

This module extends current ``ipfs_datasets_py`` semantic authority with
``DynamicPythonFrontier@1`` and typed findings.  It does not replace capsule,
identity, compatibility, or projection contracts, does not mint a second
content-identity profile, and does not import or export providers, models, or
completion authority.

Normative rules:

* Reflection, dynamic import/dispatch, monkeypatching, registration, framework
  dynamics, FFI, generated code, and related inventory kinds are classified,
  never hidden.
* Exact static facts, conservative may-facts, and runtime observations stay
  distinct evidence classes.
* Unknown presence widens the frontier and lowers autonomy.
* Opaque confidence forces Tier E.
* Bounded hermetic observation cannot upgrade a finding to exact static fact
  and cannot authorize a transition.
* Observational metadata is excluded from identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import ast
import json
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
)
from ipfs_datasets_py.semantic_refactoring.capsules import (
    EvidenceClass,
    IDENTITY_DIMENSIONS,
)


TASK_ID: Final[str] = "SPAR-008"
GOAL_ID: Final[str] = "SPAR-G022"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"

DYNAMIC_PYTHON_FRONTIER_INTERFACE: Final[str] = "DynamicPythonFrontier@1"
DYNAMIC_FINDING_INTERFACE: Final[str] = "DynamicFinding@1"
HERMETIC_OBSERVATION_PROFILE_INTERFACE: Final[str] = "HermeticObservationProfile@1"
HERMETIC_RUNTIME_OBSERVATION_INTERFACE: Final[str] = "HermeticRuntimeObservation@1"

DYNAMIC_PYTHON_FRONTIER_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.dynamic-python-frontier@1"
)
DYNAMIC_FINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.dynamic-finding@1"
)
HERMETIC_OBSERVATION_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.hermetic-observation-profile@1"
)
HERMETIC_RUNTIME_OBSERVATION_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.hermetic-runtime-observation@1"
)

FRONTIER_CONTRACT_VERSION: Final[str] = "1"
FRONTIER_CID_CODEC: Final[str] = STRUCTURED_CODEC
FRONTIER_CID_PROFILE: Final[str] = PROFILE_ID

FRONTIER_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
FRONTIER_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
FRONTIER_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False
RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT: Final[bool] = True
UNKNOWN_WIDENS_FRONTIER: Final[bool] = True

FORBIDDEN_OBSERVATIONAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "timestamp",
        "timestamps",
        "clock",
        "clocks",
        "wall_clock",
        "process_id",
        "pid",
        "local_path",
        "local_paths",
        "checkout_path",
        "store_path",
        "model_output",
        "provider_output",
        "llm_output",
        "prompt",
        "prompts",
        "model",
        "provider",
        "lease",
        "fence",
        "generation",
        "receipt",
        "acceptance",
    }
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_FINDINGS: Final[int] = 4_096
NETWORK_DENY: Final[str] = "deny"

INVENTORY_KIND_LABELS: Final[tuple[str, ...]] = (
    "getattr/setattr/delattr",
    "globals/locals",
    "eval/exec/compile",
    "dynamic import/importlib",
    "metaclasses/descriptors",
    "decorator/class-decorator side effects",
    "monkeypatch/pytest monkeypatch",
    "plugins/entry points/registries",
    "singledispatch/multimethod",
    "dependency injection/callbacks/higher-order",
    "closures/nonlocals",
    "contextvars/thread/task locals",
    "signals/atexit",
    "module __getattr__/__dir__",
    "serialization/pickle",
    "inspect/getsource/signature",
    "__module__/__qualname__",
    "traceback/log path expectations",
    "relative/circular imports",
    "native extensions/FFI",
    "generated code",
    "ORM/model registration",
    "web route registration",
    "CLI command registration",
    "environment-dependent imports",
)


class DynamicFrontierError(ValueError):
    """Fail-closed violation of a SPAR-008 dynamic frontier contract."""


class DynamicRiskKind(str, Enum):
    GETATTR_SETATTR_DELATTR = "getattr_setattr_delattr"
    GLOBALS_LOCALS = "globals_locals"
    EVAL_EXEC_COMPILE = "eval_exec_compile"
    DYNAMIC_IMPORT = "dynamic_import"
    METACLASS_DESCRIPTOR = "metaclass_descriptor"
    DECORATOR_SIDE_EFFECT = "decorator_side_effect"
    MONKEYPATCH = "monkeypatch"
    PLUGIN_REGISTRY = "plugin_registry"
    SINGLEDISPATCH = "singledispatch"
    HIGHER_ORDER = "higher_order"
    CLOSURE_NONLOCAL = "closure_nonlocal"
    CONTEXT_THREAD_TASK_LOCAL = "context_thread_task_local"
    SIGNAL_ATEXIT = "signal_atexit"
    MODULE_GETATTR_DIR = "module_getattr_dir"
    SERIALIZATION_PICKLE = "serialization_pickle"
    INSPECT = "inspect"
    MODULE_QUALNAME = "module_qualname"
    TRACEBACK_PATH = "traceback_path"
    RELATIVE_CIRCULAR_IMPORT = "relative_circular_import"
    NATIVE_FFI = "native_ffi"
    GENERATED_CODE = "generated_code"
    ORM_REGISTRATION = "orm_registration"
    WEB_ROUTE_REGISTRATION = "web_route_registration"
    CLI_REGISTRATION = "cli_registration"
    ENVIRONMENT_IMPORT = "environment_import"


class DynamicRiskFamily(str, Enum):
    REFLECTION = "reflection"
    DYNAMIC_IMPORT_DISPATCH = "dynamic_import_dispatch"
    MONKEYPATCH = "monkeypatch"
    REGISTRATION = "registration"
    FRAMEWORK = "framework"
    FFI = "ffi"
    GENERATED_CODE = "generated_code"
    RUNTIME_LOCAL_STATE = "runtime_local_state"
    SERIALIZATION = "serialization"
    INTROSPECTION = "introspection"
    IMPORT_STRUCTURE = "import_structure"


class Presence(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class AutonomyTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class ObservationStatus(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


KIND_INVENTORY_LABEL: Final[Mapping[DynamicRiskKind, str]] = {
    DynamicRiskKind.GETATTR_SETATTR_DELATTR: "getattr/setattr/delattr",
    DynamicRiskKind.GLOBALS_LOCALS: "globals/locals",
    DynamicRiskKind.EVAL_EXEC_COMPILE: "eval/exec/compile",
    DynamicRiskKind.DYNAMIC_IMPORT: "dynamic import/importlib",
    DynamicRiskKind.METACLASS_DESCRIPTOR: "metaclasses/descriptors",
    DynamicRiskKind.DECORATOR_SIDE_EFFECT: "decorator/class-decorator side effects",
    DynamicRiskKind.MONKEYPATCH: "monkeypatch/pytest monkeypatch",
    DynamicRiskKind.PLUGIN_REGISTRY: "plugins/entry points/registries",
    DynamicRiskKind.SINGLEDISPATCH: "singledispatch/multimethod",
    DynamicRiskKind.HIGHER_ORDER: "dependency injection/callbacks/higher-order",
    DynamicRiskKind.CLOSURE_NONLOCAL: "closures/nonlocals",
    DynamicRiskKind.CONTEXT_THREAD_TASK_LOCAL: "contextvars/thread/task locals",
    DynamicRiskKind.SIGNAL_ATEXIT: "signals/atexit",
    DynamicRiskKind.MODULE_GETATTR_DIR: "module __getattr__/__dir__",
    DynamicRiskKind.SERIALIZATION_PICKLE: "serialization/pickle",
    DynamicRiskKind.INSPECT: "inspect/getsource/signature",
    DynamicRiskKind.MODULE_QUALNAME: "__module__/__qualname__",
    DynamicRiskKind.TRACEBACK_PATH: "traceback/log path expectations",
    DynamicRiskKind.RELATIVE_CIRCULAR_IMPORT: "relative/circular imports",
    DynamicRiskKind.NATIVE_FFI: "native extensions/FFI",
    DynamicRiskKind.GENERATED_CODE: "generated code",
    DynamicRiskKind.ORM_REGISTRATION: "ORM/model registration",
    DynamicRiskKind.WEB_ROUTE_REGISTRATION: "web route registration",
    DynamicRiskKind.CLI_REGISTRATION: "CLI command registration",
    DynamicRiskKind.ENVIRONMENT_IMPORT: "environment-dependent imports",
}

KIND_FAMILY: Final[Mapping[DynamicRiskKind, DynamicRiskFamily]] = {
    DynamicRiskKind.GETATTR_SETATTR_DELATTR: DynamicRiskFamily.REFLECTION,
    DynamicRiskKind.GLOBALS_LOCALS: DynamicRiskFamily.REFLECTION,
    DynamicRiskKind.EVAL_EXEC_COMPILE: DynamicRiskFamily.REFLECTION,
    DynamicRiskKind.METACLASS_DESCRIPTOR: DynamicRiskFamily.REFLECTION,
    DynamicRiskKind.INSPECT: DynamicRiskFamily.INTROSPECTION,
    DynamicRiskKind.MODULE_QUALNAME: DynamicRiskFamily.INTROSPECTION,
    DynamicRiskKind.TRACEBACK_PATH: DynamicRiskFamily.INTROSPECTION,
    DynamicRiskKind.MODULE_GETATTR_DIR: DynamicRiskFamily.REFLECTION,
    DynamicRiskKind.DYNAMIC_IMPORT: DynamicRiskFamily.DYNAMIC_IMPORT_DISPATCH,
    DynamicRiskKind.SINGLEDISPATCH: DynamicRiskFamily.DYNAMIC_IMPORT_DISPATCH,
    DynamicRiskKind.HIGHER_ORDER: DynamicRiskFamily.DYNAMIC_IMPORT_DISPATCH,
    DynamicRiskKind.MONKEYPATCH: DynamicRiskFamily.MONKEYPATCH,
    DynamicRiskKind.DECORATOR_SIDE_EFFECT: DynamicRiskFamily.REGISTRATION,
    DynamicRiskKind.PLUGIN_REGISTRY: DynamicRiskFamily.REGISTRATION,
    DynamicRiskKind.SIGNAL_ATEXIT: DynamicRiskFamily.REGISTRATION,
    DynamicRiskKind.ORM_REGISTRATION: DynamicRiskFamily.FRAMEWORK,
    DynamicRiskKind.WEB_ROUTE_REGISTRATION: DynamicRiskFamily.FRAMEWORK,
    DynamicRiskKind.CLI_REGISTRATION: DynamicRiskFamily.FRAMEWORK,
    DynamicRiskKind.NATIVE_FFI: DynamicRiskFamily.FFI,
    DynamicRiskKind.GENERATED_CODE: DynamicRiskFamily.GENERATED_CODE,
    DynamicRiskKind.CLOSURE_NONLOCAL: DynamicRiskFamily.RUNTIME_LOCAL_STATE,
    DynamicRiskKind.CONTEXT_THREAD_TASK_LOCAL: DynamicRiskFamily.RUNTIME_LOCAL_STATE,
    DynamicRiskKind.SERIALIZATION_PICKLE: DynamicRiskFamily.SERIALIZATION,
    DynamicRiskKind.RELATIVE_CIRCULAR_IMPORT: DynamicRiskFamily.IMPORT_STRUCTURE,
    DynamicRiskKind.ENVIRONMENT_IMPORT: DynamicRiskFamily.IMPORT_STRUCTURE,
}

# Single-module AST can prove absence only for these closed patterns.
ABSENCE_DETECTABLE_KINDS: Final[frozenset[DynamicRiskKind]] = frozenset(
    {
        DynamicRiskKind.GETATTR_SETATTR_DELATTR,
        DynamicRiskKind.GLOBALS_LOCALS,
        DynamicRiskKind.EVAL_EXEC_COMPILE,
        DynamicRiskKind.DYNAMIC_IMPORT,
        DynamicRiskKind.METACLASS_DESCRIPTOR,
        DynamicRiskKind.DECORATOR_SIDE_EFFECT,
        DynamicRiskKind.SINGLEDISPATCH,
        DynamicRiskKind.CLOSURE_NONLOCAL,
        DynamicRiskKind.CONTEXT_THREAD_TASK_LOCAL,
        DynamicRiskKind.SIGNAL_ATEXIT,
        DynamicRiskKind.MODULE_GETATTR_DIR,
        DynamicRiskKind.SERIALIZATION_PICKLE,
        DynamicRiskKind.INSPECT,
        DynamicRiskKind.MODULE_QUALNAME,
        DynamicRiskKind.TRACEBACK_PATH,
        DynamicRiskKind.ENVIRONMENT_IMPORT,
    }
)

_TIER_RANK: Final[Mapping[str, int]] = {
    AutonomyTier.A.value: 0,
    AutonomyTier.B.value: 1,
    AutonomyTier.C.value: 2,
    AutonomyTier.D.value: 3,
    AutonomyTier.E.value: 4,
}

_EXACT_EVIDENCE: Final[frozenset[str]] = frozenset(
    {EvidenceClass.EXACT_STATIC_FACT.value}
)
_CONSERVATIVE_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        EvidenceClass.CONSERVATIVE_MAY_FACT.value,
        EvidenceClass.RUNTIME_OBSERVATION.value,
        EvidenceClass.REVIEWED_SPECIFICATION.value,
        EvidenceClass.TEST.value,
        EvidenceClass.PROOF_CANDIDATE.value,
        EvidenceClass.RECONSTRUCTED_PROOF.value,
        EvidenceClass.COUNTERMODEL.value,
        EvidenceClass.REPLAYED_COUNTEREXAMPLE.value,
        EvidenceClass.HUMAN_POLICY_DECISION.value,
    }
)
_HEURISTIC_EVIDENCE: Final[frozenset[str]] = _CONSERVATIVE_EVIDENCE | frozenset(
    {
        EvidenceClass.VECTOR_CANDIDATE.value,
        EvidenceClass.MODEL_HYPOTHESIS.value,
    }
)
_OPAQUE_EVIDENCE: Final[frozenset[str]] = frozenset({EvidenceClass.UNKNOWN.value})

_REFLECTION_NAMES: Final[frozenset[str]] = frozenset(
    {"getattr", "setattr", "delattr", "hasattr"}
)
_GLOBALS_NAMES: Final[frozenset[str]] = frozenset({"globals", "locals", "vars"})
_EVAL_NAMES: Final[frozenset[str]] = frozenset({"eval", "exec", "compile"})
_DYNAMIC_IMPORT_NAMES: Final[frozenset[str]] = frozenset({"__import__", "import_module"})
_DESCRIPTOR_DUNDERS: Final[frozenset[str]] = frozenset(
    {
        "__get__",
        "__set__",
        "__delete__",
        "__set_name__",
        "__getattribute__",
        "__getattr__",
    }
)
_MONKEYPATCH_NAMES: Final[frozenset[str]] = frozenset(
    {"monkeypatch", "patch", "MagicMock", "Mock"}
)
_PLUGIN_NAMES: Final[frozenset[str]] = frozenset(
    {"entry_points", "iter_entry_points", "pkg_resources"}
)
_SINGLEDISPATCH_NAMES: Final[frozenset[str]] = frozenset(
    {"singledispatch", "singledispatchmethod"}
)
_CONTEXT_NAMES: Final[frozenset[str]] = frozenset(
    {"ContextVar", "local", "contextvars", "threading", "contextvars"}
)
_SIGNAL_NAMES: Final[frozenset[str]] = frozenset({"signal", "atexit"})
_PICKLE_NAMES: Final[frozenset[str]] = frozenset(
    {"pickle", "dumps", "loads", "__reduce__", "__getstate__", "__setstate__"}
)
_INSPECT_NAMES: Final[frozenset[str]] = frozenset(
    {"inspect", "getsource", "signature", "getmodule"}
)
_QUALNAME_ATTRS: Final[frozenset[str]] = frozenset({"__module__", "__qualname__"})
_TRACEBACK_NAMES: Final[frozenset[str]] = frozenset({"traceback", "format_exc"})
_FFI_MODULES: Final[frozenset[str]] = frozenset(
    {"ctypes", "cffi", "_ctypes", "cython"}
)
_GENERATED_NAMES: Final[frozenset[str]] = frozenset(
    {"codegen", "generated", "jinja2", "mako"}
)
_ORM_NAMES: Final[frozenset[str]] = frozenset(
    {"declarative_base", "models", "SQLAlchemy", "Model"}
)
_WEB_NAMES: Final[frozenset[str]] = frozenset(
    {"route", "get", "post", "api_view", "endpoint"}
)
_CLI_NAMES: Final[frozenset[str]] = frozenset(
    {"command", "group", "click", "argparse", "typer"}
)


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise DynamicFrontierError(f"{name} must be a string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise DynamicFrontierError(f"{name} must be trimmed NFC text")
    if not empty and not value:
        raise DynamicFrontierError(f"{name} must be a nonempty string")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise DynamicFrontierError(f"{name} contains invalid text")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise DynamicFrontierError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise DynamicFrontierError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise DynamicFrontierError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise DynamicFrontierError(f"{name} must be a nonnegative integer")
    return value


def _tree_id(value: Any) -> str:
    text = _text(value, "tree_id")
    if len(text) not in {40, 64} or any(
        char not in "0123456789abcdef" for char in text
    ):
        raise DynamicFrontierError(
            "tree_id must be a lowercase hex Git tree identity"
        )
    return text


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise DynamicFrontierError(f"{name} must be a mapping")
    overlap = FORBIDDEN_OBSERVATIONAL_FIELDS.intersection(data)
    if overlap:
        raise DynamicFrontierError(
            f"{name} excludes observational fields {sorted(overlap)}"
        )
    actual = set(data)
    if actual != fields:
        raise DynamicFrontierError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_dag_json(value: Any, name: str) -> None:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise DynamicFrontierError(f"{name} must be strict DAG-JSON") from exc


def _verify_cid(claimed: Any, computed: str, name: str) -> None:
    cid = _cid(claimed, name)
    if cid != computed:
        raise DynamicFrontierError(f"{name} does not verify")


def kind_for_inventory_label(label: str) -> DynamicRiskKind:
    text = _text(label, "inventory_label")
    for kind, mapped in KIND_INVENTORY_LABEL.items():
        if mapped == text:
            return kind
    raise DynamicFrontierError(f"unknown inventory label {label!r}")


def family_for_kind(kind: DynamicRiskKind | str) -> DynamicRiskFamily:
    resolved = (
        kind if isinstance(kind, DynamicRiskKind) else DynamicRiskKind(kind)
    )
    return KIND_FAMILY[resolved]


def autonomy_for_finding(
    *,
    presence: str,
    confidence: str,
    evidence_class: str,
) -> str:
    if presence == Presence.ABSENT.value and confidence == AnalysisConfidence.EXACT.value:
        return AutonomyTier.A.value
    if confidence == AnalysisConfidence.OPAQUE.value:
        return AutonomyTier.E.value
    if presence == Presence.UNKNOWN.value:
        return AutonomyTier.D.value
    if evidence_class == EvidenceClass.UNKNOWN.value:
        return AutonomyTier.E.value
    if evidence_class in {
        EvidenceClass.VECTOR_CANDIDATE.value,
        EvidenceClass.MODEL_HYPOTHESIS.value,
    }:
        return AutonomyTier.D.value
    if presence == Presence.PRESENT.value:
        return AutonomyTier.D.value
    return AutonomyTier.D.value


def lowest_autonomy(tiers: Iterable[str]) -> str:
    ranked = [_TIER_RANK[_enum(tier, AutonomyTier, "autonomy_tier")] for tier in tiers]
    if not ranked:
        raise DynamicFrontierError("autonomy_tier set must be nonempty")
    rank = max(ranked)
    for name, value in _TIER_RANK.items():
        if value == rank:
            return name
    raise DynamicFrontierError("autonomy_tier rank is not closed")


def _check_confidence_evidence(confidence: str, evidence: str, presence: str) -> None:
    if confidence == AnalysisConfidence.EXACT.value:
        if presence == Presence.UNKNOWN.value:
            raise DynamicFrontierError("exact confidence forbids unknown presence")
        if evidence not in _EXACT_EVIDENCE:
            raise DynamicFrontierError(
                "exact confidence requires exact_static_fact evidence"
            )
    elif confidence == AnalysisConfidence.CONSERVATIVE.value:
        if evidence not in _CONSERVATIVE_EVIDENCE:
            raise DynamicFrontierError(
                "conservative confidence has an incompatible evidence_class"
            )
        if presence == Presence.ABSENT.value:
            raise DynamicFrontierError(
                "conservative confidence cannot prove absence"
            )
    elif confidence == AnalysisConfidence.HEURISTIC.value:
        if evidence not in _HEURISTIC_EVIDENCE:
            raise DynamicFrontierError(
                "heuristic confidence has an incompatible evidence_class"
            )
        if presence == Presence.ABSENT.value:
            raise DynamicFrontierError("heuristic confidence cannot prove absence")
    elif confidence == AnalysisConfidence.OPAQUE.value:
        if presence != Presence.UNKNOWN.value:
            raise DynamicFrontierError("opaque confidence requires unknown presence")
        if evidence not in _OPAQUE_EVIDENCE:
            raise DynamicFrontierError(
                "opaque confidence requires unknown evidence_class"
            )
    if evidence == EvidenceClass.RUNTIME_OBSERVATION.value:
        if presence == Presence.ABSENT.value:
            raise DynamicFrontierError(
                "runtime observation cannot prove absence as a static fact"
            )
        if confidence == AnalysisConfidence.EXACT.value:
            raise DynamicFrontierError(
                "runtime observation cannot be exact_static_fact"
            )


@dataclass(frozen=True, slots=True)
class DynamicFinding:
    """Typed SPAR-008 finding for one inventory risk kind at one site."""

    kind: DynamicRiskKind | str
    presence: Presence | str
    confidence: AnalysisConfidence | str
    evidence_class: EvidenceClass | str
    subject_cid: str
    source_cid: str
    tree_id: str
    lineno: int = 0
    col_offset: int = 0
    name: str = ""
    unresolved: bool = False
    autonomy_tier: AutonomyTier | str | None = None

    SCHEMA: ClassVar[str] = DYNAMIC_FINDING_SCHEMA
    INTERFACE: ClassVar[str] = DYNAMIC_FINDING_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "kind",
            "inventory_label",
            "family",
            "presence",
            "confidence",
            "evidence_class",
            "autonomy_tier",
            "subject_cid",
            "source_cid",
            "tree_id",
            "lineno",
            "col_offset",
            "name",
            "unresolved",
            "finding_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(self.kind, DynamicRiskKind, "kind")
        presence = _enum(self.presence, Presence, "presence")
        confidence = _enum(self.confidence, AnalysisConfidence, "confidence")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        unresolved = _bool(self.unresolved, "unresolved")
        _check_confidence_evidence(confidence, evidence, presence)
        if presence == Presence.UNKNOWN.value and not unresolved:
            raise DynamicFrontierError("unknown presence must remain unresolved")
        if presence != Presence.UNKNOWN.value and unresolved:
            if confidence == AnalysisConfidence.EXACT.value:
                raise DynamicFrontierError(
                    "exact resolved findings cannot be unresolved"
                )
        derived = autonomy_for_finding(
            presence=presence, confidence=confidence, evidence_class=evidence
        )
        if self.autonomy_tier is None:
            tier = derived
        else:
            tier = _enum(self.autonomy_tier, AutonomyTier, "autonomy_tier")
            if _TIER_RANK[tier] < _TIER_RANK[derived]:
                raise DynamicFrontierError(
                    "autonomy_tier cannot be higher than evidence permits"
                )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "presence", presence)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "autonomy_tier", tier)
        object.__setattr__(self, "unresolved", unresolved)
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "lineno", _nonneg_int(self.lineno, "lineno"))
        object.__setattr__(
            self, "col_offset", _nonneg_int(self.col_offset, "col_offset")
        )
        object.__setattr__(self, "name", _text(self.name, "name", empty=True))

    @property
    def inventory_label(self) -> str:
        return KIND_INVENTORY_LABEL[DynamicRiskKind(self.kind)]

    @property
    def family(self) -> str:
        return family_for_kind(self.kind).value

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": DYNAMIC_FINDING_SCHEMA,
            "interface": DYNAMIC_FINDING_INTERFACE,
            "kind": self.kind,
            "inventory_label": self.inventory_label,
            "family": self.family,
            "presence": self.presence,
            "confidence": self.confidence,
            "evidence_class": self.evidence_class,
            "autonomy_tier": self.autonomy_tier,
            "subject_cid": self.subject_cid,
            "source_cid": self.source_cid,
            "tree_id": self.tree_id,
            "lineno": self.lineno,
            "col_offset": self.col_offset,
            "name": self.name,
            "unresolved": self.unresolved,
        }
        _require_dag_json(payload, "DynamicFinding")
        return payload

    @property
    def finding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["finding_cid"] = self.finding_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DynamicFinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("finding_cid")
        if payload.pop("schema") != DYNAMIC_FINDING_SCHEMA:
            raise DynamicFrontierError("unsupported DynamicFinding schema")
        if payload.pop("interface") != DYNAMIC_FINDING_INTERFACE:
            raise DynamicFrontierError("unsupported DynamicFinding interface")
        label = payload.pop("inventory_label")
        family = payload.pop("family")
        result = cls(**payload)
        if label != result.inventory_label:
            raise DynamicFrontierError("inventory_label does not match kind")
        if family != result.family:
            raise DynamicFrontierError("family does not match kind")
        _verify_cid(claimed, result.finding_cid, "finding_cid")
        return result


def _finding_sort_key(finding: DynamicFinding) -> tuple[str, int, int, str, str]:
    return (
        finding.kind,
        finding.lineno,
        finding.col_offset,
        finding.name,
        finding.finding_cid,
    )


@dataclass(frozen=True, slots=True)
class HermeticObservationProfile:
    """Bounded hermetic observation profile. Network and install stay denied."""

    network: str = NETWORK_DENY
    implicit_install: bool = False
    allow_exec: bool = False
    subprocesses: int = 0
    timeout_ms: int = 1000
    profile_id: str = "hermetic-deny-exec@1"

    SCHEMA: ClassVar[str] = HERMETIC_OBSERVATION_PROFILE_SCHEMA
    INTERFACE: ClassVar[str] = HERMETIC_OBSERVATION_PROFILE_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "network",
            "implicit_install",
            "allow_exec",
            "subprocesses",
            "timeout_ms",
            "profile_id",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        network = _text(self.network, "network")
        if network != NETWORK_DENY:
            raise DynamicFrontierError("hermetic observation requires network=deny")
        if _bool(self.implicit_install, "implicit_install"):
            raise DynamicFrontierError("hermetic observation forbids implicit install")
        allow_exec = _bool(self.allow_exec, "allow_exec")
        subprocesses = _nonneg_int(self.subprocesses, "subprocesses")
        if subprocesses != 0:
            raise DynamicFrontierError("hermetic observation forbids subprocesses")
        timeout_ms = _nonneg_int(self.timeout_ms, "timeout_ms")
        if timeout_ms < 1:
            raise DynamicFrontierError("timeout_ms must be a positive integer")
        object.__setattr__(self, "network", network)
        object.__setattr__(self, "implicit_install", False)
        object.__setattr__(self, "allow_exec", allow_exec)
        object.__setattr__(self, "subprocesses", 0)
        object.__setattr__(self, "timeout_ms", timeout_ms)
        object.__setattr__(
            self, "profile_id", _text(self.profile_id, "profile_id")
        )

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": HERMETIC_OBSERVATION_PROFILE_SCHEMA,
            "interface": HERMETIC_OBSERVATION_PROFILE_INTERFACE,
            "network": self.network,
            "implicit_install": self.implicit_install,
            "allow_exec": self.allow_exec,
            "subprocesses": self.subprocesses,
            "timeout_ms": self.timeout_ms,
            "profile_id": self.profile_id,
        }
        _require_dag_json(payload, "HermeticObservationProfile")
        return payload

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["profile_cid"] = self.profile_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HermeticObservationProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != HERMETIC_OBSERVATION_PROFILE_SCHEMA:
            raise DynamicFrontierError("unsupported HermeticObservationProfile schema")
        if payload.pop("interface") != HERMETIC_OBSERVATION_PROFILE_INTERFACE:
            raise DynamicFrontierError(
                "unsupported HermeticObservationProfile interface"
            )
        result = cls(**payload)
        _verify_cid(claimed, result.profile_cid, "profile_cid")
        return result


DEFAULT_HERMETIC_PROFILE: Final[HermeticObservationProfile] = (
    HermeticObservationProfile()
)


@dataclass(frozen=True, slots=True)
class HermeticRuntimeObservation:
    """Bounded runtime observation. Never an exact static fact."""

    finding_cid: str
    profile_cid: str
    status: ObservationStatus | str
    evidence_class: EvidenceClass | str = EvidenceClass.RUNTIME_OBSERVATION
    kind: DynamicRiskKind | str | None = None
    note: str = ""

    SCHEMA: ClassVar[str] = HERMETIC_RUNTIME_OBSERVATION_SCHEMA
    INTERFACE: ClassVar[str] = HERMETIC_RUNTIME_OBSERVATION_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "finding_cid",
            "profile_cid",
            "status",
            "evidence_class",
            "kind",
            "note",
            "observation_cid",
        }
    )

    def __post_init__(self) -> None:
        status = _enum(self.status, ObservationStatus, "status")
        evidence = _enum(self.evidence_class, EvidenceClass, "evidence_class")
        if evidence == EvidenceClass.EXACT_STATIC_FACT.value:
            raise DynamicFrontierError(
                "runtime observation cannot be exact_static_fact"
            )
        if status == ObservationStatus.OBSERVED.value:
            if evidence != EvidenceClass.RUNTIME_OBSERVATION.value:
                raise DynamicFrontierError(
                    "observed runtime evidence must use runtime_observation"
                )
        elif status == ObservationStatus.UNAVAILABLE.value:
            if evidence != EvidenceClass.UNKNOWN.value:
                raise DynamicFrontierError(
                    "unavailable observation requires unknown evidence_class"
                )
        elif status == ObservationStatus.UNSUPPORTED.value:
            if evidence not in {
                EvidenceClass.UNKNOWN.value,
                EvidenceClass.REVIEWED_SPECIFICATION.value,
            }:
                raise DynamicFrontierError(
                    "unsupported observation has an incompatible evidence_class"
                )
        kind = None if self.kind is None else _enum(self.kind, DynamicRiskKind, "kind")
        object.__setattr__(self, "finding_cid", _cid(self.finding_cid, "finding_cid"))
        object.__setattr__(self, "profile_cid", _cid(self.profile_cid, "profile_cid"))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence_class", evidence)
        object.__setattr__(self, "kind", kind or "")
        object.__setattr__(self, "note", _text(self.note, "note", empty=True))

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": HERMETIC_RUNTIME_OBSERVATION_SCHEMA,
            "interface": HERMETIC_RUNTIME_OBSERVATION_INTERFACE,
            "finding_cid": self.finding_cid,
            "profile_cid": self.profile_cid,
            "status": self.status,
            "evidence_class": self.evidence_class,
            "kind": self.kind,
            "note": self.note,
        }
        _require_dag_json(payload, "HermeticRuntimeObservation")
        return payload

    @property
    def observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["observation_cid"] = self.observation_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HermeticRuntimeObservation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("observation_cid")
        if payload.pop("schema") != HERMETIC_RUNTIME_OBSERVATION_SCHEMA:
            raise DynamicFrontierError("unsupported HermeticRuntimeObservation schema")
        if payload.pop("interface") != HERMETIC_RUNTIME_OBSERVATION_INTERFACE:
            raise DynamicFrontierError(
                "unsupported HermeticRuntimeObservation interface"
            )
        kind = payload.get("kind") or None
        payload["kind"] = kind
        result = cls(**payload)
        _verify_cid(claimed, result.observation_cid, "observation_cid")
        return result


def _coverage_error(findings: Sequence[DynamicFinding]) -> None:
    by_kind: dict[str, list[DynamicFinding]] = {kind.value: [] for kind in DynamicRiskKind}
    for finding in findings:
        by_kind[finding.kind].append(finding)
    missing = [kind for kind, items in by_kind.items() if not items]
    if missing:
        raise DynamicFrontierError(
            f"frontier hides unknown inventory kinds: {sorted(missing)}"
        )
    for kind, items in by_kind.items():
        presences = {item.presence for item in items}
        if Presence.PRESENT.value in presences and Presence.ABSENT.value in presences:
            raise DynamicFrontierError(
                f"kind {kind} cannot be both present and absent"
            )
        if Presence.ABSENT.value in presences and len(items) != 1:
            raise DynamicFrontierError(
                f"kind {kind} absence must be a single exact finding"
            )
        if Presence.UNKNOWN.value in presences:
            if Presence.PRESENT.value in presences:
                raise DynamicFrontierError(
                    f"kind {kind} cannot mix present sites with hidden unknown"
                )
            if len(items) != 1:
                raise DynamicFrontierError(
                    f"kind {kind} unknown coverage must be a single finding"
                )


def _unknown_kinds(findings: Sequence[DynamicFinding]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                finding.kind
                for finding in findings
                if finding.presence == Presence.UNKNOWN.value
            }
        )
    )


@dataclass(frozen=True, slots=True)
class DynamicPythonFrontier:
    """Closed SPAR-008 frontier: typed findings plus optional observations."""

    tree_id: str
    subject_cid: str
    source_cid: str
    findings: Sequence[DynamicFinding | Mapping[str, Any]]
    observations: Sequence[HermeticRuntimeObservation | Mapping[str, Any]] = ()
    observation_profile_cid: str | None = None
    autonomy_tier: AutonomyTier | str | None = None

    SCHEMA: ClassVar[str] = DYNAMIC_PYTHON_FRONTIER_SCHEMA
    INTERFACE: ClassVar[str] = DYNAMIC_PYTHON_FRONTIER_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "tree_id",
            "subject_cid",
            "source_cid",
            "findings",
            "observations",
            "unknown_kinds",
            "autonomy_tier",
            "observation_profile_cid",
            "unresolved_count",
            "frontier_cid",
        }
    )

    def __post_init__(self) -> None:
        findings = tuple(_coerce_finding(item) for item in self.findings)
        if len(findings) > MAX_FINDINGS:
            raise DynamicFrontierError("findings exceed maximum length")
        findings = tuple(sorted(findings, key=_finding_sort_key))
        _coverage_error(findings)
        observations = tuple(_coerce_observation(item) for item in self.observations)
        observations = tuple(
            sorted(observations, key=lambda item: item.observation_cid)
        )
        finding_ids = {item.finding_cid for item in findings}
        profile_cids = {
            item.profile_cid for item in observations if item.profile_cid
        }
        for observation in observations:
            if observation.finding_cid not in finding_ids:
                raise DynamicFrontierError(
                    "runtime observation must bind a frontier finding"
                )
        profile = _optional_cid(
            self.observation_profile_cid, "observation_profile_cid"
        )
        if observations:
            if profile is None and len(profile_cids) == 1:
                profile = next(iter(profile_cids))
            if profile is None:
                raise DynamicFrontierError(
                    "observations require observation_profile_cid"
                )
            if any(item.profile_cid != profile for item in observations):
                raise DynamicFrontierError(
                    "observations must share the bound observation profile"
                )
        elif profile is not None:
            raise DynamicFrontierError(
                "observation_profile_cid requires observations"
            )
        constraining = [
            item.autonomy_tier
            for item in findings
            if not (
                item.presence == Presence.ABSENT.value
                and item.confidence == AnalysisConfidence.EXACT.value
            )
        ]
        if observations:
            for observation in observations:
                if observation.status == ObservationStatus.UNAVAILABLE.value:
                    constraining.append(AutonomyTier.D.value)
                elif observation.status == ObservationStatus.UNSUPPORTED.value:
                    constraining.append(AutonomyTier.D.value)
        derived = (
            lowest_autonomy(constraining)
            if constraining
            else AutonomyTier.A.value
        )
        if self.autonomy_tier is None:
            tier = derived
        else:
            tier = _enum(self.autonomy_tier, AutonomyTier, "autonomy_tier")
            if _TIER_RANK[tier] < _TIER_RANK[derived]:
                raise DynamicFrontierError(
                    "frontier autonomy_tier cannot exceed finding constraints"
                )
        object.__setattr__(self, "tree_id", _tree_id(self.tree_id))
        object.__setattr__(self, "subject_cid", _cid(self.subject_cid, "subject_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "observation_profile_cid", profile)
        object.__setattr__(self, "autonomy_tier", tier)

    @property
    def unknown_kinds(self) -> tuple[str, ...]:
        return _unknown_kinds(self.findings)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for item in self.findings if item.unresolved)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": DYNAMIC_PYTHON_FRONTIER_SCHEMA,
            "interface": DYNAMIC_PYTHON_FRONTIER_INTERFACE,
            "tree_id": self.tree_id,
            "subject_cid": self.subject_cid,
            "source_cid": self.source_cid,
            "findings": [item.identity_payload() for item in self.findings],
            "observations": [
                item.identity_payload() for item in self.observations
            ],
            "unknown_kinds": list(self.unknown_kinds),
            "autonomy_tier": self.autonomy_tier,
            "observation_profile_cid": self.observation_profile_cid,
            "unresolved_count": self.unresolved_count,
        }
        _require_dag_json(payload, "DynamicPythonFrontier")
        return payload

    @property
    def frontier_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["findings"] = [item.to_dict() for item in self.findings]
        payload["observations"] = [item.to_dict() for item in self.observations]
        payload["frontier_cid"] = self.frontier_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DynamicPythonFrontier":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("frontier_cid")
        if payload.pop("schema") != DYNAMIC_PYTHON_FRONTIER_SCHEMA:
            raise DynamicFrontierError("unsupported DynamicPythonFrontier schema")
        if payload.pop("interface") != DYNAMIC_PYTHON_FRONTIER_INTERFACE:
            raise DynamicFrontierError("unsupported DynamicPythonFrontier interface")
        unknown_kinds = payload.pop("unknown_kinds")
        unresolved_count = payload.pop("unresolved_count")
        result = cls(
            tree_id=payload["tree_id"],
            subject_cid=payload["subject_cid"],
            source_cid=payload["source_cid"],
            findings=payload["findings"],
            observations=payload["observations"],
            observation_profile_cid=payload["observation_profile_cid"],
            autonomy_tier=payload["autonomy_tier"],
        )
        if list(unknown_kinds) != list(result.unknown_kinds):
            raise DynamicFrontierError("unknown_kinds does not verify")
        if unresolved_count != result.unresolved_count:
            raise DynamicFrontierError("unresolved_count does not verify")
        _verify_cid(claimed, result.frontier_cid, "frontier_cid")
        return result

    def with_observations(
        self,
        observations: Sequence[HermeticRuntimeObservation],
        *,
        profile: HermeticObservationProfile,
    ) -> "DynamicPythonFrontier":
        if profile.profile_cid != (
            self.observation_profile_cid or profile.profile_cid
        ) and self.observation_profile_cid not in {None, profile.profile_cid}:
            raise DynamicFrontierError("cannot mix observation profiles")
        combined = tuple(self.observations) + tuple(observations)
        return DynamicPythonFrontier(
            tree_id=self.tree_id,
            subject_cid=self.subject_cid,
            source_cid=self.source_cid,
            findings=self.findings,
            observations=combined,
            observation_profile_cid=profile.profile_cid,
        )


def _coerce_finding(value: DynamicFinding | Mapping[str, Any]) -> DynamicFinding:
    if isinstance(value, DynamicFinding):
        return value
    if isinstance(value, Mapping):
        if "finding_cid" in value:
            return DynamicFinding.from_dict(value)
        return DynamicFinding(**{
            key: item
            for key, item in value.items()
            if key
            not in {
                "schema",
                "interface",
                "inventory_label",
                "family",
                "finding_cid",
            }
        })
    raise DynamicFrontierError("finding must be a DynamicFinding record")


def _coerce_observation(
    value: HermeticRuntimeObservation | Mapping[str, Any],
) -> HermeticRuntimeObservation:
    if isinstance(value, HermeticRuntimeObservation):
        return value
    if isinstance(value, Mapping):
        if "observation_cid" in value:
            return HermeticRuntimeObservation.from_dict(value)
        return HermeticRuntimeObservation(**{
            key: item
            for key, item in value.items()
            if key not in {"schema", "interface", "observation_cid"}
        })
    raise DynamicFrontierError(
        "observation must be a HermeticRuntimeObservation record"
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _site(node: ast.AST) -> tuple[int, int]:
    return (getattr(node, "lineno", 0) or 0, getattr(node, "col_offset", 0) or 0)


def _present(
    kind: DynamicRiskKind,
    node: ast.AST,
    name: str,
    *,
    confidence: AnalysisConfidence,
    evidence: EvidenceClass,
    subject_cid: str,
    source_cid: str,
    tree_id: str,
) -> DynamicFinding:
    lineno, col = _site(node)
    unresolved = confidence != AnalysisConfidence.EXACT
    return DynamicFinding(
        kind=kind,
        presence=Presence.PRESENT,
        confidence=confidence,
        evidence_class=evidence,
        subject_cid=subject_cid,
        source_cid=source_cid,
        tree_id=tree_id,
        lineno=lineno,
        col_offset=col,
        name=name,
        unresolved=unresolved,
    )


def _leaf_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


class _FrontierVisitor(ast.NodeVisitor):
    def __init__(self, *, subject_cid: str, source_cid: str, tree_id: str) -> None:
        self.subject_cid = subject_cid
        self.source_cid = source_cid
        self.tree_id = tree_id
        self.detected: list[DynamicFinding] = []
        self._function_depth = 0
        self._class_depth = 0
        self._in_except_import_error = False

    def _add(
        self,
        kind: DynamicRiskKind,
        node: ast.AST,
        name: str,
        *,
        confidence: AnalysisConfidence = AnalysisConfidence.EXACT,
        evidence: EvidenceClass = EvidenceClass.EXACT_STATIC_FACT,
    ) -> None:
        if confidence is AnalysisConfidence.EXACT:
            evidence = EvidenceClass.EXACT_STATIC_FACT
        elif evidence is EvidenceClass.EXACT_STATIC_FACT:
            evidence = EvidenceClass.CONSERVATIVE_MAY_FACT
        self.detected.append(
            _present(
                kind,
                node,
                name,
                confidence=confidence,
                evidence=evidence,
                subject_cid=self.subject_cid,
                source_cid=self.source_cid,
                tree_id=self.tree_id,
            )
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        if node.decorator_list:
            self._add(
                DynamicRiskKind.DECORATOR_SIDE_EFFECT,
                node,
                node.name,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
            for decorator in node.decorator_list:
                deco = _call_name(decorator) or _leaf_name(decorator)
                if any(token in deco for token in _SINGLEDISPATCH_NAMES):
                    self._add(DynamicRiskKind.SINGLEDISPATCH, decorator, deco)
                if any(token in deco for token in _CLI_NAMES):
                    self._add(
                        DynamicRiskKind.CLI_REGISTRATION,
                        decorator,
                        deco,
                        confidence=AnalysisConfidence.CONSERVATIVE,
                    )
                if any(token in deco for token in _WEB_NAMES):
                    self._add(
                        DynamicRiskKind.WEB_ROUTE_REGISTRATION,
                        decorator,
                        deco,
                        confidence=AnalysisConfidence.CONSERVATIVE,
                    )
        if (
            self._function_depth == 0
            and self._class_depth == 0
            and node.name in {"__getattr__", "__dir__"}
        ):
            self._add(DynamicRiskKind.MODULE_GETATTR_DIR, node, node.name)
        if node.name in _DESCRIPTOR_DUNDERS:
            self._add(DynamicRiskKind.METACLASS_DESCRIPTOR, node, node.name)
        if node.name in {"__reduce__", "__getstate__", "__setstate__"}:
            self._add(DynamicRiskKind.SERIALIZATION_PICKLE, node, node.name)
        if self._function_depth > 0:
            self._add(
                DynamicRiskKind.CLOSURE_NONLOCAL,
                node,
                node.name,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.decorator_list:
            self._add(
                DynamicRiskKind.DECORATOR_SIDE_EFFECT,
                node,
                node.name,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        for keyword in node.keywords:
            if keyword.arg == "metaclass":
                self._add(DynamicRiskKind.METACLASS_DESCRIPTOR, node, node.name)
        bases = [_call_name(base) or _leaf_name(base) for base in node.bases]
        if any(name in _ORM_NAMES or name.endswith("Model") for name in bases):
            self._add(
                DynamicRiskKind.ORM_REGISTRATION,
                node,
                node.name,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        self._class_depth += 1
        self.generic_visit(node)
        self._class_depth -= 1

    def visit_Lambda(self, node: ast.Lambda) -> None:
        if self._function_depth > 0 or self._class_depth > 0:
            self._add(
                DynamicRiskKind.CLOSURE_NONLOCAL,
                node,
                "<lambda>",
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._add(DynamicRiskKind.CLOSURE_NONLOCAL, node, ",".join(node.names))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        leaf = _leaf_name(node.func)
        if leaf in _REFLECTION_NAMES:
            name_arg = node.args[1] if len(node.args) >= 2 else None
            constant_name = isinstance(name_arg, ast.Constant) and type(
                name_arg.value
            ) is str
            self._add(
                DynamicRiskKind.GETATTR_SETATTR_DELATTR,
                node,
                leaf,
                confidence=(
                    AnalysisConfidence.EXACT
                    if constant_name
                    else AnalysisConfidence.CONSERVATIVE
                ),
            )
        if leaf in _GLOBALS_NAMES:
            self._add(DynamicRiskKind.GLOBALS_LOCALS, node, leaf)
        if leaf in _EVAL_NAMES:
            self._add(DynamicRiskKind.EVAL_EXEC_COMPILE, node, leaf)
        if leaf in _DYNAMIC_IMPORT_NAMES or name.startswith("importlib."):
            self._add(DynamicRiskKind.DYNAMIC_IMPORT, node, name or leaf)
        if leaf in _MONKEYPATCH_NAMES or "monkeypatch" in name:
            self._add(DynamicRiskKind.MONKEYPATCH, node, name or leaf)
        if leaf in _PLUGIN_NAMES or "entry_point" in name:
            self._add(
                DynamicRiskKind.PLUGIN_REGISTRY,
                node,
                name or leaf,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        if leaf in _SINGLEDISPATCH_NAMES:
            self._add(DynamicRiskKind.SINGLEDISPATCH, node, leaf)
        if leaf in _SIGNAL_NAMES or name.startswith("atexit.") or name.startswith(
            "signal."
        ):
            self._add(DynamicRiskKind.SIGNAL_ATEXIT, node, name or leaf)
        if leaf in _INSPECT_NAMES or name.startswith("inspect."):
            self._add(DynamicRiskKind.INSPECT, node, name or leaf)
        if leaf in _PICKLE_NAMES or name.startswith("pickle."):
            self._add(DynamicRiskKind.SERIALIZATION_PICKLE, node, name or leaf)
        if leaf in _TRACEBACK_NAMES or name.startswith("traceback."):
            self._add(DynamicRiskKind.TRACEBACK_PATH, node, name or leaf)
        if any(isinstance(arg, ast.Lambda) for arg in node.args):
            self._add(
                DynamicRiskKind.HIGHER_ORDER,
                node,
                name or leaf,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        if leaf in {"ContextVar"} or name.endswith(".local"):
            self._add(
                DynamicRiskKind.CONTEXT_THREAD_TASK_LOCAL, node, name or leaf
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _QUALNAME_ATTRS:
            self._add(DynamicRiskKind.MODULE_QUALNAME, node, node.attr)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._classify_module(node, alias.name)
        if self._in_except_import_error:
            self._add(
                DynamicRiskKind.ENVIRONMENT_IMPORT,
                node,
                ",".join(alias.name for alias in node.names),
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level and node.level > 0:
            self._add(
                DynamicRiskKind.RELATIVE_CIRCULAR_IMPORT,
                node,
                module,
            )
        self._classify_module(node, module)
        names = {alias.name for alias in node.names}
        if names & _PLUGIN_NAMES or module in {"importlib.metadata", "pkg_resources"}:
            self._add(
                DynamicRiskKind.PLUGIN_REGISTRY,
                node,
                module,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        if names & _SINGLEDISPATCH_NAMES or module == "functools":
            if names & _SINGLEDISPATCH_NAMES:
                self._add(DynamicRiskKind.SINGLEDISPATCH, node, module)
        if module in {"contextvars", "threading"} or names & {"ContextVar", "local"}:
            self._add(DynamicRiskKind.CONTEXT_THREAD_TASK_LOCAL, node, module)
        if module in {"signal", "atexit"}:
            self._add(DynamicRiskKind.SIGNAL_ATEXIT, node, module)
        if module == "inspect" or names & _INSPECT_NAMES:
            self._add(DynamicRiskKind.INSPECT, node, module or ",".join(sorted(names)))
        if module in {"pickle", "jsonpickle"}:
            self._add(DynamicRiskKind.SERIALIZATION_PICKLE, node, module)
        if module == "traceback":
            self._add(DynamicRiskKind.TRACEBACK_PATH, node, module)
        if module in {"unittest.mock", "pytest"} or names & _MONKEYPATCH_NAMES:
            self._add(DynamicRiskKind.MONKEYPATCH, node, module)
        if self._in_except_import_error:
            self._add(DynamicRiskKind.ENVIRONMENT_IMPORT, node, module)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.visit_all(node.body)
        for handler in node.handlers:
            name = ""
            if isinstance(handler.type, ast.Name):
                name = handler.type.id
            elif isinstance(handler.type, ast.Tuple):
                name = ",".join(
                    elt.id for elt in handler.type.elts if isinstance(elt, ast.Name)
                )
            previous = self._in_except_import_error
            if "ImportError" in name or "ModuleNotFoundError" in name:
                self._in_except_import_error = True
            self.visit_all(handler.body)
            self._in_except_import_error = previous
        self.visit_all(node.orelse)
        self.visit_all(node.finalbody)

    def visit_all(self, nodes: Sequence[ast.AST]) -> None:
        for child in nodes:
            self.visit(child)

    def _classify_module(self, node: ast.AST, module: str) -> None:
        root = module.split(".", 1)[0]
        if root in _FFI_MODULES or module.endswith(".so"):
            self._add(DynamicRiskKind.NATIVE_FFI, node, module)
        if root in _GENERATED_NAMES:
            self._add(
                DynamicRiskKind.GENERATED_CODE,
                node,
                module,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        if root in {"django", "sqlalchemy"} or module.endswith(".models"):
            self._add(
                DynamicRiskKind.ORM_REGISTRATION,
                node,
                module,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        if root in {"flask", "fastapi", "starlette", "django"}:
            self._add(
                DynamicRiskKind.WEB_ROUTE_REGISTRATION,
                node,
                module,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        if root in {"click", "typer", "argparse"}:
            self._add(
                DynamicRiskKind.CLI_REGISTRATION,
                node,
                module,
                confidence=AnalysisConfidence.CONSERVATIVE,
            )
        if root == "importlib" or module == "importlib":
            self._add(DynamicRiskKind.DYNAMIC_IMPORT, node, module)


def _coverage_finding(
    kind: DynamicRiskKind,
    *,
    subject_cid: str,
    source_cid: str,
    tree_id: str,
) -> DynamicFinding:
    if kind in ABSENCE_DETECTABLE_KINDS:
        return DynamicFinding(
            kind=kind,
            presence=Presence.ABSENT,
            confidence=AnalysisConfidence.EXACT,
            evidence_class=EvidenceClass.EXACT_STATIC_FACT,
            subject_cid=subject_cid,
            source_cid=source_cid,
            tree_id=tree_id,
            unresolved=False,
        )
    return DynamicFinding(
        kind=kind,
        presence=Presence.UNKNOWN,
        confidence=AnalysisConfidence.CONSERVATIVE,
        evidence_class=EvidenceClass.CONSERVATIVE_MAY_FACT,
        subject_cid=subject_cid,
        source_cid=source_cid,
        tree_id=tree_id,
        unresolved=True,
    )


def analyze_source(
    source: str,
    *,
    tree_id: str,
    subject_cid: str,
    source_cid: str | None = None,
) -> DynamicPythonFrontier:
    """Classify inventory kinds for one Python module source without hiding unknowns."""

    text = source if type(source) is str else None
    if text is None:
        raise DynamicFrontierError("source must be a string")
    resolved_source_cid = source_cid or cid_for_bytes(text.encode("utf-8"))
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise DynamicFrontierError("source must be parseable Python") from exc
    visitor = _FrontierVisitor(
        subject_cid=subject_cid,
        source_cid=resolved_source_cid,
        tree_id=tree_id,
    )
    visitor.visit(tree)
    present_kinds = {DynamicRiskKind(item.kind) for item in visitor.detected}
    findings: list[DynamicFinding] = list(visitor.detected)
    for kind in DynamicRiskKind:
        if kind in present_kinds:
            continue
        findings.append(
            _coverage_finding(
                kind,
                subject_cid=subject_cid,
                source_cid=resolved_source_cid,
                tree_id=tree_id,
            )
        )
    return DynamicPythonFrontier(
        tree_id=tree_id,
        subject_cid=subject_cid,
        source_cid=resolved_source_cid,
        findings=findings,
    )


class HermeticRuntimeEvidenceAdapter:
    """Bounded hermetic observer. Exec and network stay denied by default."""

    def __init__(
        self, profile: HermeticObservationProfile | None = None
    ) -> None:
        self.profile = profile or DEFAULT_HERMETIC_PROFILE

    def observe(
        self,
        frontier: DynamicPythonFrontier,
        finding: DynamicFinding,
    ) -> HermeticRuntimeObservation:
        if finding.finding_cid not in {item.finding_cid for item in frontier.findings}:
            raise DynamicFrontierError("observation target is not in the frontier")
        if finding.kind == DynamicRiskKind.EVAL_EXEC_COMPILE.value:
            return HermeticRuntimeObservation(
                finding_cid=finding.finding_cid,
                profile_cid=self.profile.profile_cid,
                status=ObservationStatus.UNSUPPORTED,
                evidence_class=EvidenceClass.UNKNOWN,
                kind=finding.kind,
                note="eval/exec/compile observation is unsupported under hermetic deny-exec",
            )
        if self.profile.allow_exec:
            return HermeticRuntimeObservation(
                finding_cid=finding.finding_cid,
                profile_cid=self.profile.profile_cid,
                status=ObservationStatus.UNSUPPORTED,
                evidence_class=EvidenceClass.UNKNOWN,
                kind=finding.kind,
                note="exec remains unsupported; observation cannot mint exact_static_fact",
            )
        if finding.presence == Presence.UNKNOWN.value:
            return HermeticRuntimeObservation(
                finding_cid=finding.finding_cid,
                profile_cid=self.profile.profile_cid,
                status=ObservationStatus.UNAVAILABLE,
                evidence_class=EvidenceClass.UNKNOWN,
                kind=finding.kind,
                note="unknown presence cannot be hidden by unavailable observation",
            )
        if finding.presence == Presence.ABSENT.value:
            return HermeticRuntimeObservation(
                finding_cid=finding.finding_cid,
                profile_cid=self.profile.profile_cid,
                status=ObservationStatus.UNAVAILABLE,
                evidence_class=EvidenceClass.UNKNOWN,
                kind=finding.kind,
                note="absence stays an exact static fact; observation does not rewrite it",
            )
        return HermeticRuntimeObservation(
            finding_cid=finding.finding_cid,
            profile_cid=self.profile.profile_cid,
            status=ObservationStatus.UNAVAILABLE,
            evidence_class=EvidenceClass.UNKNOWN,
            kind=finding.kind,
            note="hermetic deny-exec does not execute the subject; static finding stands",
        )

    def attach(
        self,
        frontier: DynamicPythonFrontier,
        finding: DynamicFinding,
    ) -> DynamicPythonFrontier:
        observation = self.observe(frontier, finding)
        return frontier.with_observations((observation,), profile=self.profile)


def encode_canonical_frontier(frontier: DynamicPythonFrontier) -> bytes:
    if type(frontier) is not DynamicPythonFrontier:
        raise DynamicFrontierError("encode requires a DynamicPythonFrontier@1 record")
    data = canonical_dag_json_bytes(frontier.identity_payload())
    if canonical_dag_json_bytes(json.loads(data.decode("utf-8"))) != data:
        raise DynamicFrontierError("frontier encoding is not canonical")
    return data


def decode_canonical_frontier(data: bytes) -> DynamicPythonFrontier:
    if type(data) is not bytes:
        raise DynamicFrontierError("canonical frontier bytes must be exact bytes")

    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise DynamicFrontierError("canonical frontier bytes must be UTF-8 JSON") from exc
    if canonical_dag_json_bytes(payload) != data:
        raise DynamicFrontierError("frontier bytes are not canonical DAG-JSON")
    result = DynamicPythonFrontier(
        tree_id=payload["tree_id"],
        subject_cid=payload["subject_cid"],
        source_cid=payload["source_cid"],
        findings=payload["findings"],
        observations=payload["observations"],
        observation_profile_cid=payload["observation_profile_cid"],
        autonomy_tier=payload["autonomy_tier"],
    )
    if result.canonical_bytes() != data:
        raise DynamicFrontierError(
            "frontier bytes are not the normalized identity payload"
        )
    return result


def frontier_cid_profile() -> dict[str, str]:
    return {
        "profile_id": FRONTIER_CID_PROFILE,
        "codec": FRONTIER_CID_CODEC,
        "contract_version": FRONTIER_CONTRACT_VERSION,
        "rule": (
            "CID identifies exact canonical bytes under declared codec/profile, "
            "not universal meaning"
        ),
    }


def provider_free_exports() -> tuple[str, ...]:
    return tuple(sorted(__all__))


__all__ = [
    "ABSENCE_DETECTABLE_KINDS",
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "DEFAULT_HERMETIC_PROFILE",
    "DUCKLAKE_IS_AUTHORITY",
    "DYNAMIC_FINDING_INTERFACE",
    "DYNAMIC_FINDING_SCHEMA",
    "DYNAMIC_PYTHON_FRONTIER_INTERFACE",
    "DYNAMIC_PYTHON_FRONTIER_SCHEMA",
    "FORBIDDEN_OBSERVATIONAL_FIELDS",
    "FRONTIER_CAN_AUTHORIZE_COMPLETION",
    "FRONTIER_CAN_AUTHORIZE_TRANSITION",
    "FRONTIER_CAN_CREATE_AUTHORITY",
    "FRONTIER_CID_CODEC",
    "FRONTIER_CID_PROFILE",
    "FRONTIER_CONTRACT_VERSION",
    "GOAL_ID",
    "HERMETIC_OBSERVATION_PROFILE_INTERFACE",
    "HERMETIC_OBSERVATION_PROFILE_SCHEMA",
    "HERMETIC_RUNTIME_OBSERVATION_INTERFACE",
    "HERMETIC_RUNTIME_OBSERVATION_SCHEMA",
    "IDENTITY_DIMENSIONS",
    "INVENTORY_KIND_LABELS",
    "KIND_FAMILY",
    "KIND_INVENTORY_LABEL",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "NETWORK_DENY",
    "PROGRAM",
    "RUNTIME_OBSERVATION_IS_NOT_STATIC_FACT",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "UNKNOWN_WIDENS_FRONTIER",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "WORKER_SELF_APPROVAL",
    "AutonomyTier",
    "DynamicFinding",
    "DynamicFrontierError",
    "DynamicPythonFrontier",
    "DynamicRiskFamily",
    "DynamicRiskKind",
    "HermeticObservationProfile",
    "HermeticRuntimeEvidenceAdapter",
    "HermeticRuntimeObservation",
    "ObservationStatus",
    "Presence",
    "analyze_source",
    "autonomy_for_finding",
    "decode_canonical_frontier",
    "encode_canonical_frontier",
    "family_for_kind",
    "frontier_cid_profile",
    "kind_for_inventory_label",
    "lowest_autonomy",
    "provider_free_exports",
]
