"""Closed schema authority for VerifiedGuiOptimizer wire models (VGO-001).

This module owns:

* explicit interface and schema-version identities for every required model and
  nested wire record;
* closed enum vocabularies, including independent analysis-classification and
  verification-status dimensions;
* fail-closed decoding helpers (unknown fields, invalid enums, unsupported
  schema versions, non-finite numbers, wrong container types, non-NFC keys).

It deliberately imports only the Python standard library. Identity CID
profiles, scanners, proof caches, semantic indexes, and model routers live
elsewhere and must not be imported here.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, TypeVar

# ---------------------------------------------------------------------------
# Package / interface identity
# ---------------------------------------------------------------------------

PACKAGE_ID: Final = "ipfs-datasets.logic.gui-optimizer"
CANONICAL_JSON_PROFILE: Final = "gui-optimizer-canonical-json/v1"

# Interface labels match the board Interfaces: Name@1.
GUI_APPLICATION_IDENTITY_INTERFACE: Final = "GuiApplicationIdentity@1"
GUI_SCREEN_IDENTITY_INTERFACE: Final = "GuiScreenIdentity@1"
UI_COMPONENT_IDENTITY_INTERFACE: Final = "UiComponentIdentity@1"
UI_COMPONENT_VERSION_INTERFACE: Final = "UiComponentVersion@1"
UI_DEPENDENCY_EDGE_INTERFACE: Final = "UiDependencyEdge@1"
UI_STATE_DEFINITION_INTERFACE: Final = "UiStateDefinition@1"
UI_EVENT_DEFINITION_INTERFACE: Final = "UiEventDefinition@1"
UI_TRANSITION_DEFINITION_INTERFACE: Final = "UiTransitionDefinition@1"
UI_ACTION_BINDING_INTERFACE: Final = "UiActionBinding@1"
UI_LAYOUT_CONSTRAINT_INTERFACE: Final = "UiLayoutConstraint@1"
UI_ACCESSIBILITY_CONTRACT_INTERFACE: Final = "UiAccessibilityContract@1"
UI_SEMANTIC_CAPSULE_INTERFACE: Final = "UiSemanticCapsule@1"
UI_CHANGE_SET_INTERFACE: Final = "UiChangeSet@1"
UI_INVALIDATION_PLAN_INTERFACE: Final = "UiInvalidationPlan@1"
UI_EVALUATION_SCENARIO_INTERFACE: Final = "UiEvaluationScenario@1"
UI_BASELINE_INTERFACE: Final = "UiBaseline@1"
UI_CONTEXT_PACK_INTERFACE: Final = "UiContextPack@1"
GUI_IMPROVEMENT_PROPOSAL_INTERFACE: Final = "GuiImprovementProposal@1"
VISUAL_REGRESSION_RECEIPT_INTERFACE: Final = "VisualRegressionReceipt@1"
ACCESSIBILITY_RECEIPT_INTERFACE: Final = "AccessibilityReceipt@1"
INTERACTION_RECEIPT_INTERFACE: Final = "InteractionReceipt@1"
UI_CONSTRAINT_RECEIPT_INTERFACE: Final = "UiConstraintReceipt@1"
GUI_IMPROVEMENT_RECEIPT_INTERFACE: Final = "GuiImprovementReceipt@1"

# Nested shared wire records.
SOURCE_SPAN_INTERFACE: Final = "SourceSpan@1"
VIEWPORT_SPEC_INTERFACE: Final = "ViewportSpec@1"
VISUAL_CHANGE_REGION_INTERFACE: Final = "VisualChangeRegion@1"
UI_CONTEXT_SOURCE_INTERFACE: Final = "UiContextSource@1"
UI_CONTEXT_STYLE_INTERFACE: Final = "UiContextStyle@1"
UI_CONTEXT_TEST_INTERFACE: Final = "UiContextTest@1"
UI_CONTEXT_STATE_MACHINE_INTERFACE: Final = "UiContextStateMachine@1"
UI_CONTEXT_FORMAL_FAILURE_INTERFACE: Final = "UiContextFormalFailure@1"
UI_CONTEXT_ACCESSIBILITY_VIOLATION_INTERFACE: Final = (
    "UiContextAccessibilityViolation@1"
)
UI_CONTEXT_VISUAL_REFERENCE_INTERFACE: Final = "UiContextVisualReference@1"
UI_CONTEXT_SCREENSHOT_DESCRIPTION_INTERFACE: Final = (
    "UiContextScreenshotDescription@1"
)
UI_CONTEXT_ROUTE_INTERFACE: Final = "UiContextRoute@1"
UI_CONTEXT_METRIC_BASELINE_INTERFACE: Final = "UiContextMetricBaseline@1"

# Wire schema versions (closed; unsupported versions fail decode).
GUI_APPLICATION_IDENTITY_SCHEMA: Final = "gui-application-identity/v1"
GUI_SCREEN_IDENTITY_SCHEMA: Final = "gui-screen-identity/v1"
UI_COMPONENT_IDENTITY_SCHEMA: Final = "ui-component-identity/v1"
UI_COMPONENT_VERSION_SCHEMA: Final = "ui-component-version/v1"
UI_DEPENDENCY_EDGE_SCHEMA: Final = "ui-dependency-edge/v1"
UI_STATE_DEFINITION_SCHEMA: Final = "ui-state-definition/v1"
UI_EVENT_DEFINITION_SCHEMA: Final = "ui-event-definition/v1"
UI_TRANSITION_DEFINITION_SCHEMA: Final = "ui-transition-definition/v1"
UI_ACTION_BINDING_SCHEMA: Final = "ui-action-binding/v1"
UI_LAYOUT_CONSTRAINT_SCHEMA: Final = "ui-layout-constraint/v1"
UI_ACCESSIBILITY_CONTRACT_SCHEMA: Final = "ui-accessibility-contract/v1"
UI_SEMANTIC_CAPSULE_SCHEMA: Final = "ui-semantic-capsule/v1"
UI_CHANGE_SET_SCHEMA: Final = "ui-change-set/v1"
UI_INVALIDATION_PLAN_SCHEMA: Final = "ui-invalidation-plan/v1"
UI_EVALUATION_SCENARIO_SCHEMA: Final = "ui-evaluation-scenario/v1"
UI_BASELINE_SCHEMA: Final = "ui-baseline/v1"
UI_CONTEXT_PACK_SCHEMA: Final = "ui-context-pack/v1"
GUI_IMPROVEMENT_PROPOSAL_SCHEMA: Final = "gui-improvement-proposal/v1"
VISUAL_REGRESSION_RECEIPT_SCHEMA: Final = "visual-regression-receipt/v1"
ACCESSIBILITY_RECEIPT_SCHEMA: Final = "accessibility-receipt/v1"
INTERACTION_RECEIPT_SCHEMA: Final = "interaction-receipt/v1"
UI_CONSTRAINT_RECEIPT_SCHEMA: Final = "ui-constraint-receipt/v1"
GUI_IMPROVEMENT_RECEIPT_SCHEMA: Final = "gui-improvement-receipt/v1"
SOURCE_SPAN_SCHEMA: Final = "gui-source-span/v1"
VIEWPORT_SPEC_SCHEMA: Final = "gui-viewport-spec/v1"
VISUAL_CHANGE_REGION_SCHEMA: Final = "visual-change-region/v1"
UI_CONTEXT_SOURCE_SCHEMA: Final = "ui-context-source/v1"
UI_CONTEXT_STYLE_SCHEMA: Final = "ui-context-style/v1"
UI_CONTEXT_TEST_SCHEMA: Final = "ui-context-test/v1"
UI_CONTEXT_STATE_MACHINE_SCHEMA: Final = "ui-context-state-machine/v1"
UI_CONTEXT_FORMAL_FAILURE_SCHEMA: Final = "ui-context-formal-failure/v1"
UI_CONTEXT_ACCESSIBILITY_VIOLATION_SCHEMA: Final = (
    "ui-context-accessibility-violation/v1"
)
UI_CONTEXT_VISUAL_REFERENCE_SCHEMA: Final = "ui-context-visual-reference/v1"
UI_CONTEXT_SCREENSHOT_DESCRIPTION_SCHEMA: Final = (
    "ui-context-screenshot-description/v1"
)
UI_CONTEXT_ROUTE_SCHEMA: Final = "ui-context-route/v1"
UI_CONTEXT_METRIC_BASELINE_SCHEMA: Final = "ui-context-metric-baseline/v1"

# Required model inventory for tests and registry checks.
REQUIRED_MODEL_INTERFACES: Final[tuple[str, ...]] = (
    ACCESSIBILITY_RECEIPT_INTERFACE,
    GUI_APPLICATION_IDENTITY_INTERFACE,
    GUI_IMPROVEMENT_PROPOSAL_INTERFACE,
    GUI_IMPROVEMENT_RECEIPT_INTERFACE,
    GUI_SCREEN_IDENTITY_INTERFACE,
    INTERACTION_RECEIPT_INTERFACE,
    UI_ACCESSIBILITY_CONTRACT_INTERFACE,
    UI_ACTION_BINDING_INTERFACE,
    UI_BASELINE_INTERFACE,
    UI_CHANGE_SET_INTERFACE,
    UI_COMPONENT_IDENTITY_INTERFACE,
    UI_COMPONENT_VERSION_INTERFACE,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    UI_CONTEXT_PACK_INTERFACE,
    UI_DEPENDENCY_EDGE_INTERFACE,
    UI_EVALUATION_SCENARIO_INTERFACE,
    UI_EVENT_DEFINITION_INTERFACE,
    UI_INVALIDATION_PLAN_INTERFACE,
    UI_LAYOUT_CONSTRAINT_INTERFACE,
    UI_SEMANTIC_CAPSULE_INTERFACE,
    UI_STATE_DEFINITION_INTERFACE,
    UI_TRANSITION_DEFINITION_INTERFACE,
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
)

SCHEMA_VERSION_BY_INTERFACE: Final[Mapping[str, str]] = MappingProxyType(
    {
        ACCESSIBILITY_RECEIPT_INTERFACE: ACCESSIBILITY_RECEIPT_SCHEMA,
        GUI_APPLICATION_IDENTITY_INTERFACE: GUI_APPLICATION_IDENTITY_SCHEMA,
        GUI_IMPROVEMENT_PROPOSAL_INTERFACE: GUI_IMPROVEMENT_PROPOSAL_SCHEMA,
        GUI_IMPROVEMENT_RECEIPT_INTERFACE: GUI_IMPROVEMENT_RECEIPT_SCHEMA,
        GUI_SCREEN_IDENTITY_INTERFACE: GUI_SCREEN_IDENTITY_SCHEMA,
        INTERACTION_RECEIPT_INTERFACE: INTERACTION_RECEIPT_SCHEMA,
        UI_ACCESSIBILITY_CONTRACT_INTERFACE: UI_ACCESSIBILITY_CONTRACT_SCHEMA,
        UI_ACTION_BINDING_INTERFACE: UI_ACTION_BINDING_SCHEMA,
        UI_BASELINE_INTERFACE: UI_BASELINE_SCHEMA,
        UI_CHANGE_SET_INTERFACE: UI_CHANGE_SET_SCHEMA,
        UI_COMPONENT_IDENTITY_INTERFACE: UI_COMPONENT_IDENTITY_SCHEMA,
        UI_COMPONENT_VERSION_INTERFACE: UI_COMPONENT_VERSION_SCHEMA,
        UI_CONSTRAINT_RECEIPT_INTERFACE: UI_CONSTRAINT_RECEIPT_SCHEMA,
        UI_CONTEXT_PACK_INTERFACE: UI_CONTEXT_PACK_SCHEMA,
        UI_DEPENDENCY_EDGE_INTERFACE: UI_DEPENDENCY_EDGE_SCHEMA,
        UI_EVALUATION_SCENARIO_INTERFACE: UI_EVALUATION_SCENARIO_SCHEMA,
        UI_EVENT_DEFINITION_INTERFACE: UI_EVENT_DEFINITION_SCHEMA,
        UI_INVALIDATION_PLAN_INTERFACE: UI_INVALIDATION_PLAN_SCHEMA,
        UI_LAYOUT_CONSTRAINT_INTERFACE: UI_LAYOUT_CONSTRAINT_SCHEMA,
        UI_SEMANTIC_CAPSULE_INTERFACE: UI_SEMANTIC_CAPSULE_SCHEMA,
        UI_STATE_DEFINITION_INTERFACE: UI_STATE_DEFINITION_SCHEMA,
        UI_TRANSITION_DEFINITION_INTERFACE: UI_TRANSITION_DEFINITION_SCHEMA,
        VISUAL_REGRESSION_RECEIPT_INTERFACE: VISUAL_REGRESSION_RECEIPT_SCHEMA,
    }
)

NESTED_SCHEMA_VERSION_BY_INTERFACE: Final[Mapping[str, str]] = MappingProxyType(
    {
        SOURCE_SPAN_INTERFACE: SOURCE_SPAN_SCHEMA,
        UI_CONTEXT_ACCESSIBILITY_VIOLATION_INTERFACE: (
            UI_CONTEXT_ACCESSIBILITY_VIOLATION_SCHEMA
        ),
        UI_CONTEXT_FORMAL_FAILURE_INTERFACE: UI_CONTEXT_FORMAL_FAILURE_SCHEMA,
        UI_CONTEXT_METRIC_BASELINE_INTERFACE: UI_CONTEXT_METRIC_BASELINE_SCHEMA,
        UI_CONTEXT_ROUTE_INTERFACE: UI_CONTEXT_ROUTE_SCHEMA,
        UI_CONTEXT_SCREENSHOT_DESCRIPTION_INTERFACE: (
            UI_CONTEXT_SCREENSHOT_DESCRIPTION_SCHEMA
        ),
        UI_CONTEXT_SOURCE_INTERFACE: UI_CONTEXT_SOURCE_SCHEMA,
        UI_CONTEXT_STATE_MACHINE_INTERFACE: UI_CONTEXT_STATE_MACHINE_SCHEMA,
        UI_CONTEXT_STYLE_INTERFACE: UI_CONTEXT_STYLE_SCHEMA,
        UI_CONTEXT_TEST_INTERFACE: UI_CONTEXT_TEST_SCHEMA,
        UI_CONTEXT_VISUAL_REFERENCE_INTERFACE: UI_CONTEXT_VISUAL_REFERENCE_SCHEMA,
        VIEWPORT_SPEC_INTERFACE: VIEWPORT_SPEC_SCHEMA,
        VISUAL_CHANGE_REGION_INTERFACE: VISUAL_CHANGE_REGION_SCHEMA,
    }
)

# Authoritative closed vocabulary of every registered optimizer schema version.
REGISTERED_OPTIMIZER_SCHEMA_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        *SCHEMA_VERSION_BY_INTERFACE.values(),
        *NESTED_SCHEMA_VERSION_BY_INTERFACE.values(),
    }
)

# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_CONTENT_CHARS: Final = 262_144
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_SAFE_INTEGER: Final = (1 << 53) - 1

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPO_PATH_RE: Final = re.compile(
    r"^(?!/)(?!\.\.(?:/|$))(?!.*/\.\.(?:/|$))"
    r"[A-Za-z0-9][A-Za-z0-9._+/\-]{0,511}$"
)
_EXTRACTOR_VERSION_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GuiOptimizerSchemaError(ValueError):
    """Raised when a GUI optimizer schema contract is violated."""


class GuiOptimizerDecodeError(GuiOptimizerSchemaError):
    """Raised when a closed wire decoder rejects input."""


# ---------------------------------------------------------------------------
# Closed enum vocabularies
# ---------------------------------------------------------------------------


class AnalysisClassification(str, Enum):
    """Extractor confidence / completeness classification.

    Independent from :class:`VerificationStatus`. Content identity never
    upgrades analysis classification to a stronger verification claim.
    """

    EXACT = "exact"
    CONSERVATIVE = "conservative"
    HEURISTIC = "heuristic"
    OPAQUE = "opaque"


class VerificationStatus(str, Enum):
    """Independent verification outcome for a bound artifact or claim."""

    VERIFIED = "verified"
    STRUCTURALLY_VALID = "structurally_valid"
    INTEGRITY_VALID = "integrity_valid"
    UNVERIFIED = "unverified"
    STALE = "stale"
    INVALID = "invalid"
    SIMULATED = "simulated"


class ExtractionConfidence(str, Enum):
    """Per-edge or per-finding extraction confidence (scanner vocabulary)."""

    EXACT = "exact"
    CONSERVATIVE = "conservative"
    HEURISTIC = "heuristic"
    OPAQUE = "opaque"


class UiDependencyRelation(str, Enum):
    """Closed typed dependency-graph edge relations."""

    RENDERS = "renders"
    CONTAINS = "contains"
    ROUTES_TO = "routes_to"
    OPENS_DIALOG = "opens_dialog"
    CLOSES_DIALOG = "closes_dialog"
    UPDATES_STATE = "updates_state"
    READS_STATE = "reads_state"
    SUBMITS = "submits"
    VALIDATES = "validates"
    INVOKES_ACTION = "invokes_action"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    DEPENDS_ON_POLICY = "depends_on_policy"
    DEPENDS_ON_SCHEMA = "depends_on_schema"
    STYLED_BY = "styled_by"
    USES_DESIGN_TOKEN = "uses_design_token"
    LOCALIZED_BY = "localized_by"
    TESTED_BY = "tested_by"
    SCREENSHOT_BY = "screenshot_by"
    RESPONSIVE_VARIANT_OF = "responsive_variant_of"
    DEVICE_PROJECTION_OF = "device_projection_of"


class UiComponentKind(str, Enum):
    """Closed component kind vocabulary for stable identity."""

    SCREEN = "screen"
    DIALOG = "dialog"
    FORM = "form"
    BUTTON = "button"
    LINK = "link"
    INPUT = "input"
    LABEL = "label"
    MENU = "menu"
    LIST = "list"
    TABLE = "table"
    PANEL = "panel"
    TAB = "tab"
    NAV = "nav"
    ICON = "icon"
    IMAGE = "image"
    TEXT = "text"
    COMPOSITE = "composite"
    HOST_BOUNDARY = "host_boundary"
    UNKNOWN = "unknown"


class UiStateKind(str, Enum):
    """Closed UI state kinds for explicit state machines."""

    INITIAL = "initial"
    LOADING = "loading"
    READY = "ready"
    EMPTY = "empty"
    SUCCESS = "success"
    FAILURE = "failure"
    CONFIRMATION = "confirmation"
    DISABLED = "disabled"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"
    TERMINAL = "terminal"
    RECOVERY = "recovery"


class UiEventKind(str, Enum):
    """Closed event kinds for state transitions and interaction receipts."""

    CLICK = "click"
    SUBMIT = "submit"
    CANCEL = "cancel"
    ESCAPE = "escape"
    KEYBOARD_ACTIVATION = "keyboard_activation"
    TIMEOUT = "timeout"
    NETWORK_SUCCESS = "network_success"
    NETWORK_FAILURE = "network_failure"
    VALIDATION_FAILURE = "validation_failure"
    CONFIRMATION_GRANT = "confirmation_grant"
    CONFIRMATION_DENIAL = "confirmation_denial"
    SERVICE_UNAVAILABLE = "service_unavailable"
    FOCUS = "focus"
    BLUR = "blur"
    CHANGE = "change"
    CUSTOM = "custom"


class ExtractionMethod(str, Enum):
    """How a fact or edge was obtained (non-executing analysis only)."""

    TYPESCRIPT_COMPILER_API = "typescript_compiler_api"
    JSX_PARSER = "jsx_parser"
    HTML_PARSER = "html_parser"
    CSS_PARSER = "css_parser"
    TEMPLATE_LITERAL_SCAN = "template_literal_scan"
    MANIFEST_READ = "manifest_read"
    REGISTRY_READ = "registry_read"
    HEURISTIC_INFERENCE = "heuristic_inference"
    MANUAL_ANNOTATION = "manual_annotation"


class CompletenessBoundary(str, Enum):
    """How complete a capsule or plan claims to be within its stated scope."""

    COMPLETE_WITHIN_BOUNDARY = "complete_within_boundary"
    PARTIAL = "partial"
    BEST_EFFORT = "best_effort"
    UNKNOWN = "unknown"


class ChangeKind(str, Enum):
    """Normalized change categories feeding invalidation."""

    COMPONENT_IMPLEMENTATION = "component_implementation"
    PROPS_EVENT_CONTRACT = "props_event_contract"
    STATE_MACHINE = "state_machine"
    CSS_DESIGN_TOKEN = "css_design_token"
    ACTION_BINDING = "action_binding"
    LOCALIZATION = "localization"
    ACCESSIBILITY = "accessibility"
    TEST = "test"
    SCREENSHOT = "screenshot"
    OTHER = "other"


class InvalidationReason(str, Enum):
    """Why an identity, scenario, or check is invalidated."""

    COMPONENT_CHANGED = "component_changed"
    PROPS_CHANGED = "props_changed"
    STATE_CHANGED = "state_changed"
    STYLE_CHANGED = "style_changed"
    ACTION_CHANGED = "action_changed"
    LOCALIZATION_CHANGED = "localization_changed"
    DEPENDENCY_CHANGED = "dependency_changed"
    EXTRACTOR_CHANGED = "extractor_changed"
    SCHEMA_CHANGED = "schema_changed"
    STALE_EDGE = "stale_edge"
    OPAQUE_EDGE = "opaque_edge"
    MISSING_EDGE = "missing_edge"
    FALLBACK_EXPANSION = "fallback_expansion"


class ProposalDecision(str, Enum):
    """Gate decision for a GUI improvement proposal or receipt."""

    ACCEPT = "accept"
    REJECT = "reject"
    HUMAN_REVIEW = "human_review"
    PENDING = "pending"


class ProposalRouteKind(str, Enum):
    """Caller-selected proposal route (not a model router)."""

    DETERMINISTIC_TRANSFORM = "deterministic_transform"
    SMALL_LOCAL_MODEL = "small_local_model"
    MEDIUM_MODEL = "medium_model"
    FRONTIER_MODEL = "frontier_model"
    HUMAN_REVIEW = "human_review"


class EvidenceLevel(str, Enum):
    """Authority label for an observation or claim."""

    AUTOMATED = "automated"
    STRUCTURAL = "structural"
    INTEGRITY = "integrity"
    HEURISTIC = "heuristic"
    HUMAN_REVIEWED = "human_reviewed"
    SIMULATED = "simulated"


class VisualDecision(str, Enum):
    """Outcome of a visual regression comparison."""

    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"
    SKIPPED = "skipped"
    BASELINE_MISSING = "baseline_missing"


class ConstraintCheckStatus(str, Enum):
    """Status of a bounded formal or structural constraint check."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"
    SKIPPED = "skipped"
    ERROR = "error"


class LayoutConstraintKind(str, Enum):
    """Closed layout / responsive constraint kinds."""

    MIN_WIDTH = "min_width"
    MAX_WIDTH = "max_width"
    MIN_HEIGHT = "min_height"
    MAX_HEIGHT = "max_height"
    ASPECT_RATIO = "aspect_ratio"
    NO_HORIZONTAL_OVERFLOW = "no_horizontal_overflow"
    NO_CLIPPING = "no_clipping"
    RESPONSIVE_BREAKPOINT = "responsive_breakpoint"
    TEXT_SCALE = "text_scale"
    OTHER = "other"


class AccessibilityRequirementKind(str, Enum):
    """Closed accessibility contract requirement kinds."""

    ACCESSIBLE_NAME = "accessible_name"
    ROLE = "role"
    KEYBOARD_ACTIVATION = "keyboard_activation"
    FOCUS_ORDER = "focus_order"
    FOCUS_TRAP = "focus_trap"
    FOCUS_RESTORE = "focus_restore"
    ERROR_ASSOCIATION = "error_association"
    REQUIRED_STATE = "required_state"
    ALT_TEXT = "alt_text"
    DECORATIVE_HIDDEN = "decorative_hidden"
    HEADING_STRUCTURE = "heading_structure"
    CONTRAST = "contrast"
    UNIQUE_ID = "unique_id"
    OTHER = "other"


class StyleKind(str, Enum):
    """Closed style / design-token kind for context-pack style payloads."""

    DESIGN_TOKEN = "design-token"
    CSS = "css"
    STYLESHEET = "stylesheet"
    INLINE = "inline"
    OTHER = "other"


class AccessibilitySeverity(str, Enum):
    """Closed severity vocabulary for accessibility violations."""

    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

E = TypeVar("E", bound=Enum)
_MISSING: Final = object()


def reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    record_name: str,
) -> None:
    """Reject any wire key not in the closed field set."""

    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GuiOptimizerDecodeError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    """Require an exact JSON object (plain ``dict``) before field coercion.

    Arrays/strings/scalars never decode as mappings. Mapping proxies, dict
    subclasses, dataclasses, models, and enums are rejected. Non-string keys,
    non-NFC keys, and NFC-equivalent key collisions fail closed.
    """

    if type(value) is not dict:
        raise GuiOptimizerDecodeError(f"{name} must be a mapping")
    seen_nfc: dict[str, str] = {}
    for key in value:
        if type(key) is not str:
            raise GuiOptimizerDecodeError(f"{name} keys must be strings")
        nfc = unicodedata.normalize("NFC", key)
        if key != nfc:
            raise GuiOptimizerDecodeError(f"{name} keys must be NFC-normalized")
        if nfc in seen_nfc:
            raise GuiOptimizerDecodeError(
                f"{name} has canonical-key collision for {key!r}"
            )
        seen_nfc[nfc] = key
    return value


def require_list(value: Any, name: str) -> list[Any]:
    """Require an exact JSON array (plain ``list``) before item coercion.

    Tuples, list subclasses, strings, mappings, scalars, and null never decode
    as arrays.
    """

    if type(value) is not list:
        raise GuiOptimizerDecodeError(f"{name} must be a sequence")
    return value


def require_sequence(value: Any, name: str) -> list[Any]:
    """Alias for :func:`require_list` (wire arrays are exact JSON lists)."""

    return require_list(value, name)


def require_wire_string(
    value: Any,
    name: str,
    *,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    """Require an exact ``str`` wire string (not Enum, not str subclass)."""

    if type(value) is not str:
        raise GuiOptimizerDecodeError(f"{name} must be a string")
    if len(value) > max_chars:
        raise GuiOptimizerDecodeError(
            f"{name} exceeds maximum length of {max_chars}"
        )
    if "\x00" in value:
        raise GuiOptimizerDecodeError(f"{name} must not contain NUL bytes")
    return value


def require_text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    text = require_wire_string(value, name, max_chars=max_chars)
    if value != value.strip():
        raise GuiOptimizerDecodeError(
            f"{name} must not have surrounding whitespace"
        )
    if not allow_empty and not value:
        raise GuiOptimizerDecodeError(f"{name} must be a non-empty string")
    return text


def require_content_string(
    value: Any,
    name: str,
    *,
    max_chars: int = MAX_CONTENT_CHARS,
) -> str:
    """Exact raw content string: preserves every code point, no trimming."""

    return require_wire_string(value, name, max_chars=max_chars)


def optional_text(
    value: Any,
    name: str,
    *,
    max_chars: int = MAX_STRING_CHARS,
    missing_default: str = "",
) -> str:
    """Optional non-null string. Explicit null is rejected; omission uses default."""

    if value is _MISSING:
        return missing_default
    if value is None:
        raise GuiOptimizerDecodeError(f"{name} must be a string")
    if value == "":
        return ""
    return require_text(value, name, max_chars=max_chars)


def require_identifier(value: Any, name: str) -> str:
    text = require_text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise GuiOptimizerDecodeError(f"{name} is not a stable identifier")
    return text


def optional_identifier(
    value: Any,
    name: str,
    *,
    missing_default: str = "",
) -> str:
    if value is _MISSING:
        return missing_default
    if value is None:
        raise GuiOptimizerDecodeError(f"{name} must be a string")
    if value == "":
        return ""
    return require_identifier(value, name)


def require_digest(value: Any, name: str) -> str:
    text = require_text(value, name, max_chars=80)
    if not _DIGEST_RE.fullmatch(text):
        raise GuiOptimizerDecodeError(
            f"{name} must be a sha256:<64-hex> digest"
        )
    return text


def optional_digest(
    value: Any,
    name: str,
    *,
    missing_default: str = "",
) -> str:
    if value is _MISSING:
        return missing_default
    if value is None:
        raise GuiOptimizerDecodeError(f"{name} must be a string")
    if value == "":
        return ""
    return require_digest(value, name)


def require_repo_path(value: Any, name: str) -> str:
    text = require_text(value, name, max_chars=512)
    if not _REPO_PATH_RE.fullmatch(text):
        raise GuiOptimizerDecodeError(
            f"{name} must be a repository-relative path without '..' segments"
        )
    return text


def optional_repo_path(
    value: Any,
    name: str,
    *,
    missing_default: str = "",
) -> str:
    if value is _MISSING:
        return missing_default
    if value is None:
        raise GuiOptimizerDecodeError(f"{name} must be a string")
    if value == "":
        return ""
    return require_repo_path(value, name)


def require_extractor_version(value: Any, name: str = "extractor_version") -> str:
    text = require_text(value, name, max_chars=64)
    if not _EXTRACTOR_VERSION_RE.fullmatch(text):
        raise GuiOptimizerDecodeError(
            f"{name} must be a compact version token"
        )
    return text


def require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise GuiOptimizerDecodeError(f"{name} must be a boolean")
    return value


def require_int(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise GuiOptimizerDecodeError(f"{name} must be an integer")
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        raise GuiOptimizerDecodeError(f"{name} is outside the safe integer range")
    if minimum is not None and value < minimum:
        raise GuiOptimizerDecodeError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise GuiOptimizerDecodeError(f"{name} must be <= {maximum}")
    return value


def optional_int(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    allow_null: bool = False,
) -> int | None:
    if value is _MISSING:
        return None
    if value is None:
        if allow_null:
            return None
        raise GuiOptimizerDecodeError(f"{name} must be an integer")
    return require_int(value, name, minimum=minimum, maximum=maximum)


def require_finite_number(value: Any, name: str) -> float | int:
    if type(value) is int:
        return require_int(value, name)
    if type(value) is float:
        if not math.isfinite(value):
            raise GuiOptimizerDecodeError(f"{name} must be a finite number")
        return value
    raise GuiOptimizerDecodeError(f"{name} must be a finite number")


def require_finite_float(value: Any, name: str) -> float:
    """Require an exact finite ``float`` (not int, not subclass)."""

    if type(value) is not float:
        raise GuiOptimizerDecodeError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise GuiOptimizerDecodeError(f"{name} must be a finite number")
    return value


def parse_enum(value: Any, enum_cls: type[E], name: str) -> E:
    """Parse a closed enum from an exact wire string (never a Python Enum)."""

    if isinstance(value, Enum):
        raise GuiOptimizerDecodeError(f"{name} must be a string enum value")
    if type(value) is not str:
        raise GuiOptimizerDecodeError(f"{name} must be a string")
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise GuiOptimizerDecodeError(
            f"{name} must be one of: {allowed}"
        ) from exc


def require_schema_version(
    value: Any,
    expected: str,
    name: str = "schema_version",
) -> str:
    text = require_text(value, name, max_chars=128)
    if text not in REGISTERED_OPTIMIZER_SCHEMA_VERSIONS:
        raise GuiOptimizerDecodeError(
            f"unregistered optimizer schema version: {text!r}"
        )
    if text != expected:
        raise GuiOptimizerDecodeError(
            f"unsupported {name}: {text!r}; expected {expected!r}"
        )
    return text


def require_registered_optimizer_schema_version(
    value: Any,
    name: str = "optimizer_schema_version",
) -> str:
    """Accept only schema versions sealed in the package registry."""

    text = require_text(value, name, max_chars=128)
    if text not in REGISTERED_OPTIMIZER_SCHEMA_VERSIONS:
        raise GuiOptimizerDecodeError(
            f"unregistered optimizer schema version: {text!r}"
        )
    return text


def require_interface(
    value: Any,
    expected: str,
    name: str = "interface",
) -> str:
    text = require_text(value, name, max_chars=128)
    if text != expected:
        raise GuiOptimizerDecodeError(
            f"unsupported {name}: {text!r}; expected {expected!r}"
        )
    return text


def require_wire_identity(
    payload: Mapping[str, Any],
    *,
    expected_interface: str,
    expected_schema: str,
    record_name: str,
) -> tuple[str, str]:
    """Require exact interface + schema_version on wire input before coercion."""

    if "interface" not in payload:
        raise GuiOptimizerDecodeError(
            f"{record_name} interface is required on wire input"
        )
    if "schema_version" not in payload:
        raise GuiOptimizerDecodeError(
            f"{record_name} schema_version is required on wire input"
        )
    interface = require_interface(payload["interface"], expected_interface)
    schema_version = require_schema_version(
        payload["schema_version"], expected_schema
    )
    return interface, schema_version


def field_value(
    payload: Mapping[str, Any],
    key: str,
    default: Any = _MISSING,
) -> Any:
    """Return a field value, distinguishing omission from present null."""

    if key not in payload:
        return default
    return payload[key]


def unique_identifiers(
    values: Any,
    name: str,
    *,
    max_items: int = MAX_COLLECTION_ITEMS,
    preserve_order: bool = True,
    required: bool = False,
) -> tuple[str, ...]:
    if values is _MISSING:
        if required:
            raise GuiOptimizerDecodeError(f"{name} is required")
        return ()
    sequence = require_list(values, name)
    if len(sequence) > max_items:
        raise GuiOptimizerDecodeError(
            f"{name} exceeds maximum of {max_items} items"
        )
    items = tuple(require_identifier(item, f"{name} item") for item in sequence)
    if len(items) != len(set(items)):
        raise GuiOptimizerDecodeError(f"{name} must not contain duplicates")
    return items if preserve_order else tuple(sorted(items))


def unique_texts(
    values: Any,
    name: str,
    *,
    max_items: int = MAX_COLLECTION_ITEMS,
    max_chars: int = MAX_STRING_CHARS,
    preserve_order: bool = True,
    allow_empty_items: bool = False,
    required: bool = False,
) -> tuple[str, ...]:
    if values is _MISSING:
        if required:
            raise GuiOptimizerDecodeError(f"{name} is required")
        return ()
    sequence = require_list(values, name)
    if len(sequence) > max_items:
        raise GuiOptimizerDecodeError(
            f"{name} exceeds maximum of {max_items} items"
        )
    items = tuple(
        require_text(
            item,
            f"{name} item",
            allow_empty=allow_empty_items,
            max_chars=max_chars,
        )
        for item in sequence
    )
    if len(items) != len(set(items)):
        raise GuiOptimizerDecodeError(f"{name} must not contain duplicates")
    return items if preserve_order else tuple(sorted(items))


def unique_digests(
    values: Any,
    name: str,
    *,
    max_items: int = MAX_COLLECTION_ITEMS,
    preserve_order: bool = True,
    required: bool = False,
) -> tuple[str, ...]:
    if values is _MISSING:
        if required:
            raise GuiOptimizerDecodeError(f"{name} is required")
        return ()
    sequence = require_list(values, name)
    if len(sequence) > max_items:
        raise GuiOptimizerDecodeError(
            f"{name} exceeds maximum of {max_items} items"
        )
    items = tuple(require_digest(item, f"{name} item") for item in sequence)
    if len(items) != len(set(items)):
        raise GuiOptimizerDecodeError(f"{name} must not contain duplicates")
    return items if preserve_order else tuple(sorted(items))


def unique_repo_paths(
    values: Any,
    name: str,
    *,
    max_items: int = MAX_COLLECTION_ITEMS,
    preserve_order: bool = True,
    required: bool = False,
) -> tuple[str, ...]:
    if values is _MISSING:
        if required:
            raise GuiOptimizerDecodeError(f"{name} is required")
        return ()
    sequence = require_list(values, name)
    if len(sequence) > max_items:
        raise GuiOptimizerDecodeError(
            f"{name} exceeds maximum of {max_items} items"
        )
    items = tuple(require_repo_path(item, f"{name} item") for item in sequence)
    if len(items) != len(set(items)):
        raise GuiOptimizerDecodeError(f"{name} must not contain duplicates")
    return items if preserve_order else tuple(sorted(items))


def parse_enum_sequence(
    values: Any,
    enum_cls: type[E],
    name: str,
    *,
    max_items: int = MAX_COLLECTION_ITEMS,
    preserve_order: bool = True,
    required: bool = False,
) -> tuple[E, ...]:
    if values is _MISSING:
        if required:
            raise GuiOptimizerDecodeError(f"{name} is required")
        return ()
    sequence = require_list(values, name)
    if len(sequence) > max_items:
        raise GuiOptimizerDecodeError(
            f"{name} exceeds maximum of {max_items} items"
        )
    items = tuple(
        parse_enum(item, enum_cls, f"{name} item") for item in sequence
    )
    if len(items) != len(set(items)):
        raise GuiOptimizerDecodeError(f"{name} must not contain duplicates")
    return items if preserve_order else tuple(sorted(items, key=lambda i: i.value))


def require_closed_json_value(value: Any, name: str) -> Any:
    """Recursively validate a closed JSON value with exact built-in types."""

    value_type = type(value)
    if value is None or value_type is bool or value_type is str:
        if value_type is str and "\x00" in value:
            raise GuiOptimizerDecodeError(f"{name} must not contain NUL bytes")
        return value
    if value_type is int:
        return require_int(value, name)
    if value_type is float:
        return require_finite_float(value, name)
    if value_type is list:
        return [
            require_closed_json_value(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        ]
    if value_type is dict:
        mapping = require_mapping(value, name)
        return {
            key: require_closed_json_value(item, f"{name}.{key}")
            for key, item in mapping.items()
        }
    raise GuiOptimizerDecodeError(
        f"{name} must be a closed JSON value; got {value_type.__name__}"
    )


def deep_copy_json(value: Any) -> Any:
    """Defensive deep copy of a closed JSON value."""

    value_type = type(value)
    if value is None or value_type in (bool, int, float, str):
        return value
    if value_type is list:
        return [deep_copy_json(item) for item in value]
    if value_type is dict:
        return {key: deep_copy_json(item) for key, item in value.items()}
    raise GuiOptimizerDecodeError(
        f"cannot deep-copy non-JSON type {value_type.__name__}"
    )


def enum_values(enum_cls: type[Enum]) -> tuple[str, ...]:
    return tuple(item.value for item in enum_cls)


def decode_closed_record(
    cls: type[Any],
    value: Any,
    *,
    record_name: str,
    builder: Callable[[dict[str, Any]], Any],
) -> Any:
    """Shared closed-record decoder used by all versioned wire models."""

    payload = require_mapping(value, record_name)
    payload = deep_copy_json(payload)
    reject_unknown_fields(payload, cls._FIELDS, record_name)
    require_wire_identity(
        payload,
        expected_interface=cls.INTERFACE,
        expected_schema=cls.SCHEMA_VERSION,
        record_name=record_name,
    )
    return builder(payload)


def decode_nested_record(cls: type[Any], value: Any, name: str) -> Any:
    if type(value) is not dict:
        raise GuiOptimizerDecodeError(f"{name} must be a mapping")
    return cls.from_dict(value)


def optional_nested_record(cls: type[Any], value: Any, name: str) -> Any | None:
    if value is _MISSING or value is None:
        return None
    return decode_nested_record(cls, value, name)


def nested_record_list(
    cls: type[Any],
    values: Any,
    name: str,
    *,
    min_items: int = 0,
) -> tuple[Any, ...]:
    if values is _MISSING:
        values = []
    sequence = require_list(values, name)
    if len(sequence) > MAX_COLLECTION_ITEMS:
        raise GuiOptimizerDecodeError(
            f"{name} exceeds maximum of {MAX_COLLECTION_ITEMS} items"
        )
    items = tuple(
        decode_nested_record(cls, item, f"{name} item") for item in sequence
    )
    if len(items) < min_items:
        raise GuiOptimizerDecodeError(
            f"{name} must contain at least {min_items} item(s)"
        )
    return items


def store_attrs(obj: Any, **values: Any) -> None:
    for key, value in values.items():
        if key == 'acceptance_criteria':
            obj.acceptance_criteria = value
        elif key == 'accessibility_contract_id':
            obj.accessibility_contract_id = value
        elif key == 'accessibility_receipt_ids':
            obj.accessibility_receipt_ids = value
        elif key == 'accessibility_violations':
            obj.accessibility_violations = value
        elif key == 'accessibility_digest':
            obj.accessibility_digest = value
        elif key == 'actions_digest':
            obj.actions_digest = value
        elif key == 'handlers_digest':
            obj.handlers_digest = value
        elif key == 'props_digest':
            obj.props_digest = value
        elif key == 'state_digest':
            obj.state_digest = value
        elif key == 'structure_digest':
            obj.structure_digest = value
        elif key == 'styles_digest':
            obj.styles_digest = value
        elif key == 'action_binding_ids':
            obj.action_binding_ids = value
        elif key == 'action_bindings':
            obj.action_bindings = value
        elif key == 'action_id':
            obj.action_id = value
        elif key == 'action_ids':
            obj.action_ids = value
        elif key == 'action_invocation_ids':
            obj.action_invocation_ids = value
        elif key == 'action_side_effects':
            obj.action_side_effects = value
        elif key == 'affected_check_ids':
            obj.affected_check_ids = value
        elif key == 'affected_component_ids':
            obj.affected_component_ids = value
        elif key == 'affected_routes':
            obj.affected_routes = value
        elif key == 'affected_scenario_ids':
            obj.affected_scenario_ids = value
        elif key == 'affected_tests':
            obj.affected_tests = value
        elif key == 'analysis_classification':
            obj.analysis_classification = value
        elif key == 'application_id':
            obj.application_id = value
        elif key == 'artifact_digest':
            obj.artifact_digest = value
        elif key == 'artifact_digests':
            obj.artifact_digests = value
        elif key == 'automated_pass_count':
            obj.automated_pass_count = value
        elif key == 'baseline_digest':
            obj.baseline_digest = value
        elif key == 'baseline_id':
            obj.baseline_id = value
        elif key == 'breakpoint':
            obj.breakpoint = value
        elif key == 'browser':
            obj.browser = value
        elif key == 'browser_version':
            obj.browser_version = value
        elif key == 'capsule_id':
            obj.capsule_id = value
        elif key == 'capsule_tokens':
            obj.capsule_tokens = value
        elif key == 'change_kinds':
            obj.change_kinds = value
        elif key == 'change_set_id':
            obj.change_set_id = value
        elif key == 'check_ids':
            obj.check_ids = value
        elif key == 'child_capsules':
            obj.child_capsules = value
        elif key == 'child_component_ids':
            obj.child_component_ids = value
        elif key == 'color_scheme':
            obj.color_scheme = value
        elif key == 'completeness_boundary':
            obj.completeness_boundary = value
        elif key == 'component_id':
            obj.component_id = value
        elif key == 'component_ids':
            obj.component_ids = value
        elif key == 'component_kind':
            obj.component_kind = value
        elif key == 'component_type':
            obj.component_type = value
        elif key == 'component_version_ids':
            obj.component_version_ids = value
        elif key == 'compression_ratio':
            obj.compression_ratio = value
        elif key == 'confidence':
            obj.confidence = value
        elif key == 'confirmation_id':
            obj.confirmation_id = value
        elif key == 'confirmation_required':
            obj.confirmation_required = value
        elif key == 'constraint_id':
            obj.constraint_id = value
        elif key == 'constraint_receipt_ids':
            obj.constraint_receipt_ids = value
        elif key == 'content':
            obj.content = value
        elif key == 'context_pack_id':
            obj.context_pack_id = value
        elif key == 'contract_id':
            obj.contract_id = value
        elif key == 'decision':
            obj.decision = value
        elif key == 'dependency_edge_ids':
            obj.dependency_edge_ids = value
        elif key == 'depends_on_schema':
            obj.depends_on_schema = value
        elif key == 'description':
            obj.description = value
        elif key == 'device_scale_factor':
            obj.device_scale_factor = value
        elif key == 'display_name':
            obj.display_name = value
        elif key == 'editable':
            obj.editable = value
        elif key == 'effect_ids':
            obj.effect_ids = value
        elif key == 'emitted_event_ids':
            obj.emitted_event_ids = value
        elif key == 'empty_behavior':
            obj.empty_behavior = value
        elif key == 'end_column':
            obj.end_column = value
        elif key == 'end_line':
            obj.end_line = value
        elif key == 'error_behavior':
            obj.error_behavior = value
        elif key == 'escalation_conditions':
            obj.escalation_conditions = value
        elif key == 'event_id':
            obj.event_id = value
        elif key == 'event_ids':
            obj.event_ids = value
        elif key == 'events':
            obj.events = value
        elif key == 'evidence_level':
            obj.evidence_level = value
        elif key == 'evidence_reason':
            obj.evidence_reason = value
        elif key == 'excluded_context_explanation':
            obj.excluded_context_explanation = value
        elif key == 'expected_change_regions':
            obj.expected_change_regions = value
        elif key == 'expected_screenshot_ids':
            obj.expected_screenshot_ids = value
        elif key == 'expected_test_ids':
            obj.expected_test_ids = value
        elif key == 'expression':
            obj.expression = value
        elif key == 'extra_control_count':
            obj.extra_control_count = value
        elif key == 'extraction_method':
            obj.extraction_method = value
        elif key == 'extractor_version':
            obj.extractor_version = value
        elif key == 'fallback_explanation':
            obj.fallback_explanation = value
        elif key == 'fallback_triggered':
            obj.fallback_triggered = value
        elif key == 'file_paths':
            obj.file_paths = value
        elif key == 'fixture_digest':
            obj.fixture_digest = value
        elif key == 'focus_behavior':
            obj.focus_behavior = value
        elif key == 'focus_sequence':
            obj.focus_sequence = value
        elif key == 'forbidden_change_regions':
            obj.forbidden_change_regions = value
        elif key == 'formal_invariant_failures':
            obj.formal_invariant_failures = value
        elif key == 'from_state_id':
            obj.from_state_id = value
        elif key == 'guard':
            obj.guard = value
        elif key == 'height':
            obj.height = value
        elif key == 'initial_state_id':
            obj.initial_state_id = value
        elif key == 'intended_component_ids':
            obj.intended_component_ids = value
        elif key == 'intended_file_paths':
            obj.intended_file_paths = value
        elif key == 'interaction_receipt_ids':
            obj.interaction_receipt_ids = value
        elif key == 'interface':
            obj.interface = value
        elif key == 'invalidation_plan_id':
            obj.invalidation_plan_id = value
        elif key == 'invariant_id':
            obj.invariant_id = value
        elif key == 'is_destructive':
            obj.is_destructive = value
        elif key == 'is_initial':
            obj.is_initial = value
        elif key == 'is_noop':
            obj.is_noop = value
        elif key == 'is_terminal':
            obj.is_terminal = value
        elif key == 'keyboard_interactions':
            obj.keyboard_interactions = value
        elif key == 'keyboard_result':
            obj.keyboard_result = value
        elif key == 'kind':
            obj.kind = value
        elif key == 'known_violation_ids':
            obj.known_violation_ids = value
        elif key == 'label':
            obj.label = value
        elif key == 'layout_role':
            obj.layout_role = value
        elif key == 'loading_behavior':
            obj.loading_behavior = value
        elif key == 'locale':
            obj.locale = value
        elif key == 'localization_digest':
            obj.localization_digest = value
        elif key == 'localization_keys':
            obj.localization_keys = value
        elif key == 'lower_bound':
            obj.lower_bound = value
        elif key == 'machine_id':
            obj.machine_id = value
        elif key == 'manual_check_ids':
            obj.manual_check_ids = value
        elif key == 'manual_review_threshold_percent':
            obj.manual_review_threshold_percent = value
        elif key == 'max_unexplained_diff_percent':
            obj.max_unexplained_diff_percent = value
        elif key == 'method':
            obj.method = value
        elif key == 'metric_baseline':
            obj.metric_baseline = value
        elif key == 'metric_digest':
            obj.metric_digest = value
        elif key == 'metric_id':
            obj.metric_id = value
        elif key == 'metrics':
            obj.metrics = value
        elif key == 'missing_control_count':
            obj.missing_control_count = value
        elif key == 'name':
            obj.name = value
        elif key == 'notes':
            obj.notes = value
        elif key == 'objective':
            obj.objective = value
        elif key == 'optimizer_schema_version':
            obj.optimizer_schema_version = value
        elif key == 'ordinary_raw_dependency_tokens':
            obj.ordinary_raw_dependency_tokens = value
        elif key == 'other_context_tokens':
            obj.other_context_tokens = value
        elif key == 'pack_id':
            obj.pack_id = value
        elif key == 'package_namespace':
            obj.package_namespace = value
        elif key == 'parent_capsules':
            obj.parent_capsules = value
        elif key == 'patch_digest':
            obj.patch_digest = value
        elif key == 'path':
            obj.path = value
        elif key == 'pixel_diff_percent':
            obj.pixel_diff_percent = value
        elif key == 'plan_id':
            obj.plan_id = value
        elif key == 'policy_id':
            obj.policy_id = value
        elif key == 'prop_names':
            obj.prop_names = value
        elif key == 'proposal_id':
            obj.proposal_id = value
        elif key == 'purpose':
            obj.purpose = value
        elif key == 'qualified_name':
            obj.qualified_name = value
        elif key == 'raw_source_tokens':
            obj.raw_source_tokens = value
        elif key == 'raw_sources':
            obj.raw_sources = value
        elif key == 'reasons':
            obj.reasons = value
        elif key == 'receipt_id':
            obj.receipt_id = value
        elif key == 'recovery_ids':
            obj.recovery_ids = value
        elif key == 'reduced_motion':
            obj.reduced_motion = value
        elif key == 'region_id':
            obj.region_id = value
        elif key == 'rejection_reasons':
            obj.rejection_reasons = value
        elif key == 'relation':
            obj.relation = value
        elif key == 'repository_revision':
            obj.repository_revision = value
        elif key == 'repository_root':
            obj.repository_root = value
        elif key == 'required_names':
            obj.required_names = value
        elif key == 'required_roles':
            obj.required_roles = value
        elif key == 'requirement_kinds':
            obj.requirement_kinds = value
        elif key == 'requires_confirmation':
            obj.requires_confirmation = value
        elif key == 'requires_human_review':
            obj.requires_human_review = value
        elif key == 'responsive_behavior':
            obj.responsive_behavior = value
        elif key == 'route_id':
            obj.route_id = value
        elif key == 'route_kind':
            obj.route_kind = value
        elif key == 'scenario_id':
            obj.scenario_id = value
        elif key == 'scenario_ids':
            obj.scenario_ids = value
        elif key == 'schema_id':
            obj.schema_id = value
        elif key == 'schema_version':
            obj.schema_version = value
        elif key == 'screen_id':
            obj.screen_id = value
        elif key == 'screen_reader_reviewed':
            obj.screen_reader_reviewed = value
        elif key == 'screenshot_analysis_tokens':
            obj.screenshot_analysis_tokens = value
        elif key == 'screenshot_descriptions':
            obj.screenshot_descriptions = value
        elif key == 'screenshot_digest':
            obj.screenshot_digest = value
        elif key == 'screenshot_height':
            obj.screenshot_height = value
        elif key == 'screenshot_ids':
            obj.screenshot_ids = value
        elif key == 'screenshot_width':
            obj.screenshot_width = value
        elif key == 'severity':
            obj.severity = value
        elif key == 'solver_id':
            obj.solver_id = value
        elif key == 'source_component_id':
            obj.source_component_id = value
        elif key == 'source_revision':
            obj.source_revision = value
        elif key == 'source_span':
            obj.source_span = value
        elif key == 'source_tokens_replaced_by_capsules':
            obj.source_tokens_replaced_by_capsules = value
        elif key == 'stable_identity':
            obj.stable_identity = value
        elif key == 'start_column':
            obj.start_column = value
        elif key == 'start_line':
            obj.start_line = value
        elif key == 'state_effect_ids':
            obj.state_effect_ids = value
        elif key == 'state_id':
            obj.state_id = value
        elif key == 'state_ids':
            obj.state_ids = value
        elif key == 'state_machine':
            obj.state_machine = value
        elif key == 'state_variable_ids':
            obj.state_variable_ids = value
        elif key == 'states':
            obj.states = value
        elif key == 'status':
            obj.status = value
        elif key == 'statuses':
            obj.statuses = value
        elif key == 'step_ids':
            obj.step_ids = value
        elif key == 'structural_diff_percent':
            obj.structural_diff_percent = value
        elif key == 'style_kind':
            obj.style_kind = value
        elif key == 'styles':
            obj.styles = value
        elif key == 'success_behavior':
            obj.success_behavior = value
        elif key == 'summary':
            obj.summary = value
        elif key == 'tags':
            obj.tags = value
        elif key == 'target_component_id':
            obj.target_component_id = value
        elif key == 'test_id':
            obj.test_id = value
        elif key == 'test_ids':
            obj.test_ids = value
        elif key == 'text_scale_percent':
            obj.text_scale_percent = value
        elif key == 'timezone':
            obj.timezone = value
        elif key == 'to_state_id':
            obj.to_state_id = value
        elif key == 'token_budget':
            obj.token_budget = value
        elif key == 'total_estimated_prompt_tokens':
            obj.total_estimated_prompt_tokens = value
        elif key == 'transition_id':
            obj.transition_id = value
        elif key == 'transition_ids':
            obj.transition_ids = value
        elif key == 'transitions':
            obj.transitions = value
        elif key == 'unexpected_layout_shift_count':
            obj.unexpected_layout_shift_count = value
        elif key == 'unresolved_dynamic_behavior':
            obj.unresolved_dynamic_behavior = value
        elif key == 'unresolved_observation_ids':
            obj.unresolved_observation_ids = value
        elif key == 'unsupported_check_ids':
            obj.unsupported_check_ids = value
        elif key == 'unsupported_criteria':
            obj.unsupported_criteria = value
        elif key == 'upper_bound':
            obj.upper_bound = value
        elif key == 'verification_status':
            obj.verification_status = value
        elif key == 'version_identity':
            obj.version_identity = value
        elif key == 'viewport':
            obj.viewport = value
        elif key == 'violated_check_ids':
            obj.violated_check_ids = value
        elif key == 'violation_count':
            obj.violation_count = value
        elif key == 'violation_id':
            obj.violation_id = value
        elif key == 'violation_ids':
            obj.violation_ids = value
        elif key == 'visible_state_ids':
            obj.visible_state_ids = value
        elif key == 'visual_effect_summary':
            obj.visual_effect_summary = value
        elif key == 'visual_receipt_ids':
            obj.visual_receipt_ids = value
        elif key == 'visual_references':
            obj.visual_references = value
        elif key == 'width':
            obj.width = value
        elif key == 'x':
            obj.x = value
        elif key == 'y':
            obj.y = value
        else:
            raise GuiOptimizerDecodeError(f"unsupported model attribute: {key}")


__all__ = [
    "PACKAGE_ID",
    "CANONICAL_JSON_PROFILE",
    "REQUIRED_MODEL_INTERFACES",
    "SCHEMA_VERSION_BY_INTERFACE",
    "NESTED_SCHEMA_VERSION_BY_INTERFACE",
    "REGISTERED_OPTIMIZER_SCHEMA_VERSIONS",
    "GuiOptimizerSchemaError",
    "GuiOptimizerDecodeError",
    "AnalysisClassification",
    "VerificationStatus",
    "ExtractionConfidence",
    "UiDependencyRelation",
    "UiComponentKind",
    "UiStateKind",
    "UiEventKind",
    "ExtractionMethod",
    "CompletenessBoundary",
    "ChangeKind",
    "InvalidationReason",
    "ProposalDecision",
    "ProposalRouteKind",
    "EvidenceLevel",
    "VisualDecision",
    "ConstraintCheckStatus",
    "LayoutConstraintKind",
    "AccessibilityRequirementKind",
    "StyleKind",
    "AccessibilitySeverity",
    "reject_unknown_fields",
    "require_mapping",
    "require_list",
    "require_sequence",
    "require_wire_string",
    "require_text",
    "require_content_string",
    "optional_text",
    "require_identifier",
    "optional_identifier",
    "require_digest",
    "optional_digest",
    "require_repo_path",
    "optional_repo_path",
    "require_extractor_version",
    "require_bool",
    "require_int",
    "optional_int",
    "require_finite_number",
    "require_finite_float",
    "parse_enum",
    "require_schema_version",
    "require_registered_optimizer_schema_version",
    "require_interface",
    "require_wire_identity",
    "field_value",
    "unique_identifiers",
    "unique_texts",
    "unique_digests",
    "unique_repo_paths",
    "parse_enum_sequence",
    "require_closed_json_value",
    "deep_copy_json",
    "enum_values",
    "decode_closed_record",
    "decode_nested_record",
    "optional_nested_record",
    "nested_record_list",
    "store_attrs",
    "_MISSING",
]
