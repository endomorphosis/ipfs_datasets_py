"""Role-aware toolchain authority and promotion.

``FormalVerificationToolRole@1`` / ``RoleAwarePromotionPolicy@1`` (FVT-G100 / FVT-037).

Replaces availability-shaped promotion with a closed per-tool role model:

* every matrix entry carries exactly one closed role and one authority ceiling;
* support / advisor / candidate / shadow presence alone can never satisfy a
  certified-authority requirement;
* semantic property lanes are independently registered so later certification
  work owns a lane handler instead of mutating a monolithic certifier.

Importing this module is pure data.  It never installs tools, probes the host,
opens the network, or writes disk state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Final

FORMAL_VERIFICATION_TOOL_ROLE_INTERFACE: Final = "FormalVerificationToolRole@1"
ROLE_AWARE_PROMOTION_POLICY_INTERFACE: Final = "RoleAwarePromotionPolicy@1"
FORMAL_VERIFICATION_SPECIALIZED_RECEIPT_AGGREGATION_INTERFACE: Final = (
    "FormalVerificationSpecializedReceiptAggregation@1"
)
TOOL_ROLE_SCHEMA: Final = "formal-verification-tool-role/v1"
PROMOTION_POLICY_SCHEMA: Final = "role-aware-promotion-policy/v1"
SEMANTIC_LANE_SCHEMA: Final = "formal-verification-semantic-lane/v1"
SPECIALIZED_RECEIPT_AGGREGATION_SCHEMA: Final = (
    "formal-verification-specialized-receipt-aggregation/v1"
)
GOAL_ID: Final = "FVT-G100"
TASK_ID: Final = "FVT-037"
SPECIALIZED_RECEIPT_AGGREGATION_GOAL_ID: Final = "FVT-G203"
SPECIALIZED_RECEIPT_AGGREGATION_TASK_ID: Final = "FVT-065"
PROGRAM: Final = "formal-verification-tactician/toolchain-governance"

# Composite-slot key when a handler covers an entire multi-tool lane.
_COMPOSITE_HANDLER_TOOL_KEY: Final = ""


class ToolchainRoleError(ValueError):
    """Raised when role metadata or promotion policy is violated."""


class ToolRole(StrEnum):
    """Closed toolchain participation roles (exactly one per matrix entry)."""

    SUPPORT = "support"
    ADVISOR = "advisor"
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    AUTHORITY = "authority"


class ToolchainAuthorityCeiling(StrEnum):
    """Closed authority ceilings a tool may advertise (cannot self-upgrade).

    Domain notes (acceptance mapping for FVT-G100):

    * ``none`` — support-only companions (Java, Maude, OPAM) and pure shadows
      that never certify a property lane by themselves.
    * ``advisory`` / ``candidate`` — learned advisors and untrusted bridges
      (Leanstral, autoencoder, SymAI, ErgoAI, Hammer) until independent
      reconstruction elevates them under a separate policy change.
    * ``authorization`` — in-process Datalog / SecPAL only.
    * ``finite_trace`` — Runtime MTL monitors (finite-trace authority).
    * ``bounded`` — state-model and hyperproperty tools.
    * ``kernel`` — Lean / Rocq / Isabelle kernel proof checking.
    * ``attestation`` — ZKP / circuit attestation bindings only.
    * ``satisfiability`` / ``protocol`` / ``reconstruction`` — remaining
      primary solvers and provers that can hold certified authority when the
      role is ``authority`` and hermetic certification succeeds.
    """

    NONE = "none"
    ADVISORY = "advisory"
    CANDIDATE = "candidate"
    BOUNDED = "bounded"
    SATISFIABILITY = "satisfiability"
    AUTHORIZATION = "authorization"
    FINITE_TRACE = "finite_trace"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    RECONSTRUCTION = "reconstruction"
    KERNEL = "kernel"
    ATTESTATION = "attestation"


# Roles that may never satisfy a certified-authority requirement by presence alone.
_NON_CERTIFYING_ROLES: Final[frozenset[ToolRole]] = frozenset(
    {
        ToolRole.SUPPORT,
        ToolRole.ADVISOR,
        ToolRole.CANDIDATE,
        ToolRole.SHADOW,
    }
)

# Authority ceilings that never count as certified property authority.
_NON_CERTIFYING_CEILINGS: Final[frozenset[ToolchainAuthorityCeiling]] = frozenset(
    {
        ToolchainAuthorityCeiling.NONE,
        ToolchainAuthorityCeiling.ADVISORY,
        ToolchainAuthorityCeiling.CANDIDATE,
    }
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolchainRoleError(f"{label} must be a non-empty string")
    if len(value) > 256:
        raise ToolchainRoleError(f"{label} exceeds maximum length")
    return value.strip()


def _optional_text(value: object, label: str) -> str:
    if value is None or value == "":
        return ""
    return _text(value, label)


def _enum(value: object, enum_type: type[StrEnum], label: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except ValueError as exc:
        raise ToolchainRoleError(
            f"{label} must be one of {[item.value for item in enum_type]}"
        ) from exc


def role_can_satisfy_certified_authority(
    role: ToolRole | str,
    authority_ceiling: ToolchainAuthorityCeiling | str,
) -> bool:
    """Return True only when the role/ceiling pair may ever certify authority.

    Support, advisor, candidate, and shadow roles always return False.
    Authority role still requires a non-advisory ceiling.
    """

    resolved_role = _enum(role, ToolRole, "role")
    resolved_ceiling = _enum(
        authority_ceiling, ToolchainAuthorityCeiling, "authority_ceiling"
    )
    if resolved_role in _NON_CERTIFYING_ROLES:
        return False
    if resolved_ceiling in _NON_CERTIFYING_CEILINGS:
        return False
    return resolved_role is ToolRole.AUTHORITY


@dataclass(frozen=True, slots=True)
class FormalVerificationToolRole:
    """One closed role assignment for a matrix tool (``FormalVerificationToolRole@1``)."""

    tool_id: str
    role: ToolRole
    authority_ceiling: ToolchainAuthorityCeiling
    lane_ids: tuple[str, ...]
    display_name: str = ""
    families: tuple[str, ...] = ()
    notes: str = ""
    independent_reconstruction_required: bool = False
    schema_version: str = TOOL_ROLE_SCHEMA
    interface: str = FORMAL_VERIFICATION_TOOL_ROLE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _text(self.tool_id, "tool_id").lower())
        object.__setattr__(self, "role", _enum(self.role, ToolRole, "role"))
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(
                self.authority_ceiling,
                ToolchainAuthorityCeiling,
                "authority_ceiling",
            ),
        )
        object.__setattr__(
            self,
            "lane_ids",
            tuple(_text(item, "lane_id") for item in self.lane_ids),
        )
        if not self.lane_ids:
            raise ToolchainRoleError(
                f"tool {self.tool_id!r} must declare at least one lane_id"
            )
        object.__setattr__(
            self,
            "display_name",
            _optional_text(self.display_name, "display_name") or self.tool_id,
        )
        object.__setattr__(
            self,
            "families",
            tuple(_text(item, "family") for item in self.families),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        if not isinstance(self.independent_reconstruction_required, bool):
            raise ToolchainRoleError(
                "independent_reconstruction_required must be a boolean"
            )
        if self.schema_version != TOOL_ROLE_SCHEMA:
            raise ToolchainRoleError(
                f"tool role schema must be {TOOL_ROLE_SCHEMA}"
            )
        if self.interface != FORMAL_VERIFICATION_TOOL_ROLE_INTERFACE:
            raise ToolchainRoleError(
                f"tool role interface must be {FORMAL_VERIFICATION_TOOL_ROLE_INTERFACE}"
            )
        self._assert_role_ceiling_consistency()

    def _assert_role_ceiling_consistency(self) -> None:
        role = self.role
        ceiling = self.authority_ceiling
        if role is ToolRole.SUPPORT and ceiling is not ToolchainAuthorityCeiling.NONE:
            raise ToolchainRoleError(
                f"support tool {self.tool_id!r} must use authority ceiling 'none'"
            )
        if role is ToolRole.SHADOW and ceiling not in {
            ToolchainAuthorityCeiling.NONE,
            ToolchainAuthorityCeiling.ADVISORY,
        }:
            raise ToolchainRoleError(
                f"shadow tool {self.tool_id!r} cannot hold certifying authority"
            )
        if role in {ToolRole.ADVISOR, ToolRole.CANDIDATE} and ceiling not in {
            ToolchainAuthorityCeiling.ADVISORY,
            ToolchainAuthorityCeiling.CANDIDATE,
            ToolchainAuthorityCeiling.NONE,
        }:
            raise ToolchainRoleError(
                f"advisor/candidate tool {self.tool_id!r} cannot hold "
                f"ceiling {ceiling.value!r} until independent reconstruction"
            )
        if role is ToolRole.AUTHORITY and ceiling in _NON_CERTIFYING_CEILINGS:
            raise ToolchainRoleError(
                f"authority tool {self.tool_id!r} requires a certifying ceiling, "
                f"got {ceiling.value!r}"
            )
        expected_certifying = role_can_satisfy_certified_authority(role, ceiling)
        if role in _NON_CERTIFYING_ROLES and expected_certifying:
            raise ToolchainRoleError(
                f"non-certifying role {role.value!r} cannot satisfy certified authority"
            )

    @property
    def can_satisfy_certified_authority(self) -> bool:
        """Whether this assignment may ever satisfy a certified-authority requirement."""

        return role_can_satisfy_certified_authority(self.role, self.authority_ceiling)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "interface": self.interface,
            "tool_id": self.tool_id,
            "display_name": self.display_name,
            "role": self.role.value,
            "authority_ceiling": self.authority_ceiling.value,
            "lane_ids": list(self.lane_ids),
            "families": list(self.families),
            "notes": self.notes,
            "independent_reconstruction_required": (
                self.independent_reconstruction_required
            ),
            "can_satisfy_certified_authority": self.can_satisfy_certified_authority,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FormalVerificationToolRole:
        if not isinstance(payload, Mapping):
            raise ToolchainRoleError("tool role payload must be a mapping")
        return cls(
            tool_id=str(payload.get("tool_id") or ""),
            role=str(payload.get("role") or ""),  # type: ignore[arg-type]
            authority_ceiling=str(payload.get("authority_ceiling") or ""),  # type: ignore[arg-type]
            lane_ids=tuple(payload.get("lane_ids") or ()),
            display_name=str(payload.get("display_name") or ""),
            families=tuple(payload.get("families") or ()),
            notes=str(payload.get("notes") or ""),
            independent_reconstruction_required=bool(
                payload.get("independent_reconstruction_required", False)
            ),
            schema_version=str(payload.get("schema_version") or TOOL_ROLE_SCHEMA),
            interface=str(
                payload.get("interface") or FORMAL_VERIFICATION_TOOL_ROLE_INTERFACE
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticLane:
    """Independently owned semantic certification lane."""

    lane_id: str
    property_class: str
    description: str
    tool_ids: tuple[str, ...]
    authority_tool_ids: tuple[str, ...]
    owner_module: str
    handler_id: str
    schema_version: str = SEMANTIC_LANE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "lane_id", _text(self.lane_id, "lane_id"))
        object.__setattr__(
            self, "property_class", _text(self.property_class, "property_class")
        )
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        object.__setattr__(
            self,
            "tool_ids",
            tuple(_text(item, "tool_id").lower() for item in self.tool_ids),
        )
        object.__setattr__(
            self,
            "authority_tool_ids",
            tuple(
                _text(item, "authority_tool_id").lower()
                for item in self.authority_tool_ids
            ),
        )
        if not self.tool_ids:
            raise ToolchainRoleError(
                f"lane {self.lane_id!r} must declare at least one tool_id"
            )
        if not set(self.authority_tool_ids).issubset(self.tool_ids):
            raise ToolchainRoleError(
                f"lane {self.lane_id!r} authority_tool_ids must be a subset of tool_ids"
            )
        # Advisor-only and support-only lanes may declare an empty authority set:
        # presence of those tools never satisfies a certified-authority requirement.
        object.__setattr__(
            self, "owner_module", _text(self.owner_module, "owner_module")
        )
        object.__setattr__(self, "handler_id", _text(self.handler_id, "handler_id"))
        if self.schema_version != SEMANTIC_LANE_SCHEMA:
            raise ToolchainRoleError(
                f"semantic lane schema must be {SEMANTIC_LANE_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lane_id": self.lane_id,
            "property_class": self.property_class,
            "description": self.description,
            "tool_ids": list(self.tool_ids),
            "authority_tool_ids": list(self.authority_tool_ids),
            "owner_module": self.owner_module,
            "handler_id": self.handler_id,
        }


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Outcome of role-aware promotion evaluation."""

    tool_id: str
    role: ToolRole
    authority_ceiling: ToolchainAuthorityCeiling
    allowed: bool
    reason_codes: tuple[str, ...]
    can_satisfy_certified_authority: bool
    schema_version: str = PROMOTION_POLICY_SCHEMA
    interface: str = ROLE_AWARE_PROMOTION_POLICY_INTERFACE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "interface": self.interface,
            "tool_id": self.tool_id,
            "role": self.role.value,
            "authority_ceiling": self.authority_ceiling.value,
            "allowed": self.allowed,
            "reason_codes": list(self.reason_codes),
            "can_satisfy_certified_authority": self.can_satisfy_certified_authority,
        }


LaneHandler = Callable[..., Any]


def handler_registry_key(lane_id: str, tool_id: str | None = None) -> str:
    """Canonical registry key for a lane or ``(lane_id, tool_id)`` handler slot.

    Tool-specific handlers use ``"{lane_id}::{tool_id}"``. Composite handlers
    that own an entire multi-tool lane use the bare ``lane_id``.
    """

    lane_key = _text(lane_id, "lane_id")
    if tool_id is None or str(tool_id).strip() == "":
        return lane_key
    return f"{lane_key}::{_text(tool_id, 'tool_id').lower()}"


def parse_handler_registry_key(key: str) -> tuple[str, str | None]:
    """Inverse of :func:`handler_registry_key`."""

    text = _text(key, "handler_key")
    if "::" not in text:
        return text, None
    lane_id, tool_id = text.split("::", 1)
    return lane_id, tool_id.lower()


def infer_handler_tool_id(handler: LaneHandler) -> str | None:
    """Best-effort tool ownership for a callable certifier handler.

    Single-tool certifiers publish ``TOOL_ID`` on the callable or its module
    globals. Multi-tool composite certifiers (ATP, state-model, hyperproperty)
    leave ownership unset so they bind as a composite lane handler.
    """

    for attr in ("tool_id", "TOOL_ID"):
        value = getattr(handler, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

    # LaneHandlerPlaceholder and similar declare lane ownership only.
    if getattr(handler, "status", None) == "registered_pending_implementation":
        return None

    globals_map = getattr(handler, "__globals__", None)
    if isinstance(globals_map, Mapping):
        # Multi-tool modules intentionally omit a single TOOL_ID or declare
        # TOOL_IDS / ENGINE_IDS; keep them as composite handlers.
        multi = globals_map.get("TOOL_IDS") or globals_map.get("ENGINE_IDS")
        if multi:
            return None
        value = globals_map.get("TOOL_ID")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


@dataclass(frozen=True, slots=True)
class CompositeLaneHandler:
    """Fan-out handler that retains distinct per-tool specialized receipts.

    Sibling tools on the same property lane (kernel: lean/rocq/isabelle,
    protocol: tamarin/proverif) must not overwrite each other. Invoking the
    composite returns every specialized receipt under ``per_tool_receipts``.
    """

    lane_id: str
    tool_handlers: Mapping[str, LaneHandler]
    composite_handler: LaneHandler | None = None
    interface: str = FORMAL_VERIFICATION_SPECIALIZED_RECEIPT_AGGREGATION_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_handlers",
            MappingProxyType(dict(self.tool_handlers)),
        )
        if not self.tool_handlers and self.composite_handler is None:
            raise ToolchainRoleError(
                f"composite lane handler for {self.lane_id!r} has no children"
            )

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        per_tool: dict[str, Any] = {}
        for tool_id in sorted(self.tool_handlers):
            receipt = self.tool_handlers[tool_id](*args, **kwargs)
            per_tool[tool_id] = receipt
        composite_receipt: Any | None = None
        if self.composite_handler is not None:
            composite_receipt = self.composite_handler(*args, **kwargs)
            if isinstance(composite_receipt, Mapping):
                nested = composite_receipt.get("per_tool_receipts")
                if isinstance(nested, Mapping):
                    for tool_id, receipt in nested.items():
                        # Tool-specific handlers win; never overwrite a sibling.
                        per_tool.setdefault(str(tool_id), receipt)
        certified_flags: list[bool] = []
        for receipt in per_tool.values():
            if isinstance(receipt, Mapping):
                certified_flags.append(
                    bool(
                        receipt.get("certified")
                        or receipt.get("production_certified")
                    )
                )
            else:
                certified_flags.append(False)
        return {
            "interface": self.interface,
            "lane_id": self.lane_id,
            "composite": True,
            "handler_keys": [
                handler_registry_key(self.lane_id, tool_id)
                for tool_id in sorted(per_tool)
            ],
            "tool_ids": sorted(per_tool),
            "per_tool_receipts": per_tool,
            "composite_receipt": composite_receipt,
            "certified": bool(certified_flags) and all(certified_flags),
            "lossless": True,
            "collapse_by_check_kind": False,
            "sibling_overwrite_forbidden": True,
        }


@dataclass
class RoleAwarePromotionPolicy:
    """``RoleAwarePromotionPolicy@1`` evaluator and lane-handler registry.

    Handlers are keyed by ``(lane_id, tool_id)`` when a certifier owns a single
    tool, or by ``lane_id`` alone for composite multi-tool certifiers. Sibling
    tools on the same property lane never overwrite each other (FVT-G203).
    """

    interface: str = ROLE_AWARE_PROMOTION_POLICY_INTERFACE
    schema_version: str = PROMOTION_POLICY_SCHEMA
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    roles: Mapping[str, FormalVerificationToolRole] = field(default_factory=dict)
    lanes: Mapping[str, SemanticLane] = field(default_factory=dict)
    # Registry key is handler_registry_key(lane_id, tool_id|None).
    _handlers: dict[str, LaneHandler] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.interface != ROLE_AWARE_PROMOTION_POLICY_INTERFACE:
            raise ToolchainRoleError(
                f"promotion policy interface must be "
                f"{ROLE_AWARE_PROMOTION_POLICY_INTERFACE}"
            )
        if self.schema_version != PROMOTION_POLICY_SCHEMA:
            raise ToolchainRoleError(
                f"promotion policy schema must be {PROMOTION_POLICY_SCHEMA}"
            )
        object.__setattr__(self, "roles", MappingProxyType(dict(self.roles)))
        object.__setattr__(self, "lanes", MappingProxyType(dict(self.lanes)))

    def get_role(self, tool_id: str) -> FormalVerificationToolRole:
        key = _text(tool_id, "tool_id").lower()
        try:
            return self.roles[key]
        except KeyError as exc:
            raise ToolchainRoleError(f"unknown tool_id {tool_id!r}") from exc

    def list_tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.roles))

    def list_lane_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.lanes))

    def register_lane_handler(
        self,
        lane_id: str,
        handler: LaneHandler,
        *,
        tool_id: str | None = None,
        replace: bool = False,
    ) -> None:
        """Bind an independently owned certification handler.

        When ``tool_id`` is omitted, ownership is inferred from the handler
        (module ``TOOL_ID``). Inferred tool-specific handlers register under
        ``(lane_id, tool_id)`` so siblings such as Lean/Rocq/Isabelle or
        Tamarin/ProVerif never overwrite each other. Explicit composite
        multi-tool handlers (no single TOOL_ID) still bind to the bare lane.
        """

        key_lane = _text(lane_id, "lane_id")
        if key_lane not in self.lanes:
            raise ToolchainRoleError(
                f"cannot register handler for unknown lane {lane_id!r}; "
                "lanes are pre-registered in the role model"
            )
        if not callable(handler):
            raise ToolchainRoleError("lane handler must be callable")

        resolved_tool = (
            _text(tool_id, "tool_id").lower()
            if tool_id is not None and str(tool_id).strip()
            else infer_handler_tool_id(handler)
        )
        registry_key = handler_registry_key(key_lane, resolved_tool)
        if registry_key in self._handlers and not replace:
            raise ToolchainRoleError(
                f"lane handler for {registry_key!r} is already registered; "
                "pass replace=True to override deliberately"
            )

        # Drop pending composite placeholders once a real tool-specific handler
        # arrives so first-check / one-handler-per-lane fan-in cannot conceal
        # sibling specialized evidence.
        if resolved_tool:
            composite_key = handler_registry_key(key_lane, None)
            existing_composite = self._handlers.get(composite_key)
            if existing_composite is not None and (
                getattr(existing_composite, "status", None)
                == "registered_pending_implementation"
            ):
                del self._handlers[composite_key]

        self._handlers[registry_key] = handler

    def get_tool_handler(
        self,
        lane_id: str,
        tool_id: str,
    ) -> LaneHandler | None:
        """Return the specialized handler for exactly one ``(lane_id, tool_id)``."""

        return self._handlers.get(
            handler_registry_key(lane_id, tool_id)
        )

    def list_lane_tool_handlers(
        self,
        lane_id: str,
    ) -> dict[str, LaneHandler]:
        """Return every tool-specific handler registered under ``lane_id``."""

        key_lane = _text(lane_id, "lane_id")
        found: dict[str, LaneHandler] = {}
        prefix = f"{key_lane}::"
        for registry_key, handler in self._handlers.items():
            if registry_key.startswith(prefix):
                _, tool = parse_handler_registry_key(registry_key)
                if tool:
                    found[tool] = handler
        return found

    def get_lane_handler(
        self,
        lane_id: str,
        tool_id: str | None = None,
    ) -> LaneHandler | None:
        """Return a lane or tool-scoped handler without sibling overwrite.

        * With ``tool_id``, return that specialized handler only.
        * Without ``tool_id``, prefer a single specialized handler when the
          lane has exactly one tool registration; otherwise return a
          :class:`CompositeLaneHandler` that yields distinct per-tool receipts.
        """

        key_lane = _text(lane_id, "lane_id")
        if tool_id is not None and str(tool_id).strip():
            return self.get_tool_handler(key_lane, tool_id)

        composite = self._handlers.get(handler_registry_key(key_lane, None))
        tool_handlers = self.list_lane_tool_handlers(key_lane)

        if not tool_handlers:
            return composite
        if len(tool_handlers) == 1 and composite is None:
            return next(iter(tool_handlers.values()))
        return CompositeLaneHandler(
            lane_id=key_lane,
            tool_handlers=tool_handlers,
            composite_handler=composite,
        )

    def registered_handler_ids(self) -> tuple[str, ...]:
        """Lane ids that have at least one registered handler (compat surface)."""

        lanes: set[str] = set()
        for registry_key in self._handlers:
            lane_id, _ = parse_handler_registry_key(registry_key)
            lanes.add(lane_id)
        return tuple(sorted(lanes))

    def registered_handler_keys(self) -> tuple[str, ...]:
        """Exact registry keys, including ``lane_id::tool_id`` specialized slots."""

        return tuple(sorted(self._handlers))

    def evaluate_promotion(
        self,
        tool_id: str,
        *,
        present: bool = False,
        usable: bool = False,
        production_certified: bool = False,
        independent_reconstruction: bool = False,
        hermetic_certificate: bool = False,
    ) -> PromotionDecision:
        """Decide whether a tool may contribute certified authority for promotion.

        Availability (present/usable) alone never authorizes promotion for
        support, advisor, candidate, or shadow roles.
        """

        assignment = self.get_role(tool_id)
        reasons: list[str] = []
        certifying = assignment.can_satisfy_certified_authority

        if assignment.role in _NON_CERTIFYING_ROLES:
            reasons.append(f"role_{assignment.role.value}_cannot_certify")
        if assignment.authority_ceiling in _NON_CERTIFYING_CEILINGS:
            reasons.append(
                f"ceiling_{assignment.authority_ceiling.value}_cannot_certify"
            )
        if assignment.independent_reconstruction_required and not independent_reconstruction:
            reasons.append("independent_reconstruction_required")
        if present and assignment.role in _NON_CERTIFYING_ROLES:
            reasons.append("presence_alone_is_not_authority")
        if usable and assignment.role in _NON_CERTIFYING_ROLES:
            reasons.append("usability_alone_is_not_authority")
        if not certifying:
            reasons.append("cannot_satisfy_certified_authority_requirement")
            # De-duplicate while preserving order.
            unique = tuple(dict.fromkeys(reasons))
            return PromotionDecision(
                tool_id=assignment.tool_id,
                role=assignment.role,
                authority_ceiling=assignment.authority_ceiling,
                allowed=False,
                reason_codes=unique,
                can_satisfy_certified_authority=False,
            )

        if not production_certified:
            reasons.append("production_certification_required")
        if not hermetic_certificate:
            reasons.append("hermetic_certificate_required")
        if not usable:
            reasons.append("usability_required")

        allowed = not reasons
        if allowed:
            reasons.append("role_aware_authority_satisfied")
        return PromotionDecision(
            tool_id=assignment.tool_id,
            role=assignment.role,
            authority_ceiling=assignment.authority_ceiling,
            allowed=allowed,
            reason_codes=tuple(dict.fromkeys(reasons)),
            can_satisfy_certified_authority=True,
        )

    def assert_matrix_invariants(self) -> None:
        """Fail closed if the matrix violates FVT-G100 structural rules."""

        if not self.roles:
            raise ToolchainRoleError("role matrix is empty")
        seen: set[str] = set()
        for tool_id, assignment in self.roles.items():
            if tool_id != assignment.tool_id:
                raise ToolchainRoleError(
                    f"role map key {tool_id!r} does not match tool_id "
                    f"{assignment.tool_id!r}"
                )
            if tool_id in seen:
                raise ToolchainRoleError(f"duplicate tool_id {tool_id!r}")
            seen.add(tool_id)
            # Exactly one closed role and ceiling — enforced by enum fields.
            if not isinstance(assignment.role, ToolRole):
                raise ToolchainRoleError(f"{tool_id!r} role is not closed")
            if not isinstance(
                assignment.authority_ceiling, ToolchainAuthorityCeiling
            ):
                raise ToolchainRoleError(
                    f"{tool_id!r} authority ceiling is not closed"
                )
            for lane_id in assignment.lane_ids:
                if lane_id not in self.lanes:
                    raise ToolchainRoleError(
                        f"tool {tool_id!r} references unregistered lane {lane_id!r}"
                    )
        for lane_id, lane in self.lanes.items():
            for tool_id in lane.tool_ids:
                if tool_id not in self.roles:
                    raise ToolchainRoleError(
                        f"lane {lane_id!r} references unknown tool {tool_id!r}"
                    )
            for tool_id in lane.authority_tool_ids:
                assignment = self.roles[tool_id]
                if (
                    assignment.role is ToolRole.AUTHORITY
                    and not assignment.can_satisfy_certified_authority
                ):
                    raise ToolchainRoleError(
                        f"lane {lane_id!r} authority tool {tool_id!r} cannot certify"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "interface": self.interface,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "program": PROGRAM,
            "roles": [self.roles[key].to_dict() for key in sorted(self.roles)],
            "lanes": [self.lanes[key].to_dict() for key in sorted(self.lanes)],
            "registered_handlers": list(self.registered_handler_ids()),
            "registered_handler_keys": list(self.registered_handler_keys()),
            "non_certifying_roles": sorted(role.value for role in _NON_CERTIFYING_ROLES),
            "non_certifying_ceilings": sorted(
                ceiling.value for ceiling in _NON_CERTIFYING_CEILINGS
            ),
            "policy": {
                "support_advisor_shadow_presence_cannot_certify": True,
                "availability_is_not_authority": True,
                "exactly_one_role_and_ceiling_per_tool": True,
                "lanes_independently_owned": True,
                "handlers_keyed_by_lane_and_tool": True,
                "sibling_handlers_never_overwrite": True,
                "lossless_specialized_receipt_aggregation": True,
            },
        }


def _role(
    tool_id: str,
    role: ToolRole,
    ceiling: ToolchainAuthorityCeiling,
    *lane_ids: str,
    display_name: str = "",
    families: Sequence[str] = (),
    notes: str = "",
    independent_reconstruction_required: bool = False,
) -> FormalVerificationToolRole:
    return FormalVerificationToolRole(
        tool_id=tool_id,
        role=role,
        authority_ceiling=ceiling,
        lane_ids=tuple(lane_ids),
        display_name=display_name,
        families=tuple(families),
        notes=notes,
        independent_reconstruction_required=independent_reconstruction_required,
    )


def _lane(
    lane_id: str,
    property_class: str,
    description: str,
    tool_ids: Sequence[str],
    authority_tool_ids: Sequence[str],
    owner_module: str,
    handler_id: str,
) -> SemanticLane:
    return SemanticLane(
        lane_id=lane_id,
        property_class=property_class,
        description=description,
        tool_ids=tuple(tool_ids),
        authority_tool_ids=tuple(authority_tool_ids),
        owner_module=owner_module,
        handler_id=handler_id,
    )


def _build_default_lanes() -> tuple[SemanticLane, ...]:
    """Pre-register semantic lanes with independent owner modules.

    Later tasks (Lean, authorization, advisors, …) bind handlers under
    ``tools.logic.certification.<lane>`` without editing the central certifier.
    """

    return (
        _lane(
            "smt",
            "smt_software_verification",
            "SMT solvers for software-verification VCs",
            ("z3", "cvc5"),
            ("z3", "cvc5"),
            "tools.logic.certification.smt",
            "smt_semantic_certification@1",
        ),
        _lane(
            "tla",
            "tla_state_model",
            "TLA+/TLC/Apalache state-model checking (Java is support only)",
            ("apalache", "tlc", "java"),
            ("apalache", "tlc"),
            "tools.logic.certification.state_model",
            "state_model_toolchain_certification@1",
        ),
        _lane(
            "datalog_secpal",
            "authorization_datalog_secpal",
            "In-process authorization authority; external engines are shadows",
            (
                "datalog-authorization",
                "secpal-authorization",
                "souffle",
                "secpal",
            ),
            ("datalog-authorization", "secpal-authorization"),
            "tools.logic.certification.authorization",
            "authorization_semantic_certification@1",
        ),
        _lane(
            "protocol",
            "protocol_verification",
            "Tamarin/ProVerif protocol verification (Maude is support only)",
            ("tamarin", "proverif", "maude"),
            ("tamarin", "proverif"),
            "tools.logic.certification.tamarin",
            "protocol_toolchain_certification@1",
        ),
        _lane(
            "hyperltl",
            "hyperproperty",
            "HyperLTL / hyperproperty tools with bounded authority",
            ("hyperltl", "autohyper", "mchyper"),
            ("hyperltl", "autohyper", "mchyper"),
            "tools.logic.certification.hyperproperty",
            "hyperproperty_toolchain_certification@1",
        ),
        _lane(
            "atp",
            "automated_theorem_proving",
            "First-order ATP portfolio",
            ("vampire", "eprover"),
            ("vampire", "eprover"),
            "tools.logic.certification.atp",
            "atp_toolchain_certification@1",
        ),
        _lane(
            "hammer",
            "hammer_advisor",
            "Hammer / advisor bridges (advisor/candidate until reconstruction)",
            (
                "symbolicai",
                "ergoai",
                "leanstral",
                "autoencoder",
                "hammer",
            ),
            # Empty: advisors never satisfy certified-authority requirements.
            (),
            "tools.logic.certification.advisors",
            "advisor_role_certification@1",
        ),
        _lane(
            "kernel",
            "interactive_proof_kernel",
            "Lean / Rocq / Isabelle kernels (kernel authority)",
            ("lean", "coq", "isabelle"),
            ("lean", "coq", "isabelle"),
            "tools.logic.certification.lean",
            "kernel_semantic_certification@1",
        ),
        _lane(
            "runtime_mtl",
            "runtime_mtl_monitoring",
            "Runtime MTL monitors with finite-trace authority",
            ("runtime-mtl", "runtime-mtl-external"),
            ("runtime-mtl", "runtime-mtl-external"),
            "tools.logic.certification.runtime_mtl",
            "runtime_mtl_semantic_certification@1",
        ),
        _lane(
            "attestation",
            "attestation_zkp",
            "ZKP / circuit attestation authority only",
            ("zkp-circuit",),
            ("zkp-circuit",),
            "tools.logic.certification.zkp",
            "zkp_deployment_certification@1",
        ),
        _lane(
            "support",
            "support_companions",
            "Host companions that never hold property authority",
            ("java", "maude", "opam"),
            # Empty: support presence never satisfies certified authority.
            (),
            "tools.logic.certification.roles",
            "support_role_boundary@1",
        ),
    )


def _build_default_roles() -> tuple[FormalVerificationToolRole, ...]:
    """Closed FVT-G100 matrix: exactly one role and ceiling per tool."""

    return (
        # SMT — satisfiability authority
        _role(
            "z3",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.SATISFIABILITY,
            "smt",
            display_name="Z3 SMT solver",
            families=("smt", "software_verification"),
        ),
        _role(
            "cvc5",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.SATISFIABILITY,
            "smt",
            display_name="CVC5 SMT solver",
            families=("smt", "software_verification"),
        ),
        # State model — bounded authority; Java is support only
        _role(
            "apalache",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.BOUNDED,
            "tla",
            display_name="Apalache",
            families=("tla", "state_model"),
            notes="Bounded state-model authority; never theorem/kernel authority.",
        ),
        _role(
            "tlc",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.BOUNDED,
            "tla",
            display_name="TLC",
            families=("tla", "state_model"),
            notes="Bounded state-model authority; never theorem/kernel authority.",
        ),
        _role(
            "java",
            ToolRole.SUPPORT,
            ToolchainAuthorityCeiling.NONE,
            "tla",
            "support",
            display_name="Host JVM (java)",
            families=("tla", "state_model"),
            notes="Support only; cannot promote a property lane by itself.",
        ),
        # Authorization — in-process authority; external engines are shadows
        _role(
            "datalog-authorization",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.AUTHORIZATION,
            "datalog_secpal",
            display_name="In-process Datalog authorization",
            families=("authorization", "datalog"),
            notes="Authorization-only authority.",
        ),
        _role(
            "secpal-authorization",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.AUTHORIZATION,
            "datalog_secpal",
            display_name="In-process SecPAL authorization",
            families=("authorization", "secpal"),
            notes="Authorization-only authority.",
        ),
        _role(
            "souffle",
            ToolRole.SHADOW,
            ToolchainAuthorityCeiling.NONE,
            "datalog_secpal",
            display_name="External Souffle (shadow)",
            families=("authorization", "datalog"),
            notes="Shadow checker only; presence never certifies authority.",
        ),
        _role(
            "secpal",
            ToolRole.SHADOW,
            ToolchainAuthorityCeiling.NONE,
            "datalog_secpal",
            display_name="External SecPAL (shadow)",
            families=("authorization", "secpal"),
            notes="Shadow checker only; presence never certifies authority.",
        ),
        # Protocol — Maude is support only
        _role(
            "tamarin",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.PROTOCOL,
            "protocol",
            display_name="Tamarin",
            families=("protocol",),
        ),
        _role(
            "proverif",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.PROTOCOL,
            "protocol",
            display_name="ProVerif",
            families=("protocol",),
        ),
        _role(
            "maude",
            ToolRole.SUPPORT,
            ToolchainAuthorityCeiling.NONE,
            "protocol",
            "support",
            display_name="Maude",
            families=("protocol",),
            notes="Support only; cannot promote a property lane by itself.",
        ),
        # Hyperproperty — bounded authority
        _role(
            "hyperltl",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.BOUNDED,
            "hyperltl",
            display_name="HyperLTL",
            families=("hyperproperty",),
            notes="Bounded hyperproperty authority.",
        ),
        _role(
            "autohyper",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.BOUNDED,
            "hyperltl",
            display_name="AutoHyper",
            families=("hyperproperty",),
            notes="Bounded hyperproperty authority.",
        ),
        _role(
            "mchyper",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.BOUNDED,
            "hyperltl",
            display_name="MCHyper",
            families=("hyperproperty",),
            notes="Bounded hyperproperty authority.",
        ),
        # ATP
        _role(
            "vampire",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.RECONSTRUCTION,
            "atp",
            display_name="Vampire ATP",
            families=("atp",),
        ),
        _role(
            "eprover",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.RECONSTRUCTION,
            "atp",
            display_name="E prover",
            families=("atp",),
        ),
        # Advisors / candidates until independent reconstruction
        _role(
            "symbolicai",
            ToolRole.ADVISOR,
            ToolchainAuthorityCeiling.ADVISORY,
            "hammer",
            display_name="SymbolicAI (SymAI)",
            families=("advisor",),
            notes="Advisor only until independent reconstruction.",
            independent_reconstruction_required=True,
        ),
        _role(
            "ergoai",
            ToolRole.ADVISOR,
            ToolchainAuthorityCeiling.ADVISORY,
            "hammer",
            display_name="ErgoAI",
            families=("advisor", "flogic"),
            notes="Advisor only until independent reconstruction.",
            independent_reconstruction_required=True,
        ),
        _role(
            "leanstral",
            ToolRole.CANDIDATE,
            ToolchainAuthorityCeiling.CANDIDATE,
            "hammer",
            display_name="Leanstral",
            families=("advisor", "candidate"),
            notes="Candidate/advisor only until independent reconstruction.",
            independent_reconstruction_required=True,
        ),
        _role(
            "autoencoder",
            ToolRole.CANDIDATE,
            ToolchainAuthorityCeiling.CANDIDATE,
            "hammer",
            display_name="Autoencoder advisor",
            families=("advisor", "candidate"),
            notes="Candidate/advisor only until independent reconstruction.",
            independent_reconstruction_required=True,
        ),
        _role(
            "hammer",
            ToolRole.ADVISOR,
            ToolchainAuthorityCeiling.ADVISORY,
            "hammer",
            display_name="Hammer bridge",
            families=("advisor", "hammer"),
            notes="Advisor only until independent reconstruction.",
            independent_reconstruction_required=True,
        ),
        # Kernels
        _role(
            "lean",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.KERNEL,
            "kernel",
            display_name="Lean",
            families=("kernel", "reconstruction"),
            notes="Kernel proof-checking authority only.",
        ),
        _role(
            "coq",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.KERNEL,
            "kernel",
            display_name="Rocq/Coq",
            families=("kernel", "reconstruction"),
            notes="Kernel proof-checking authority only.",
        ),
        _role(
            "isabelle",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.KERNEL,
            "kernel",
            display_name="Isabelle",
            families=("kernel", "reconstruction", "hammer"),
            notes="Kernel proof-checking authority only.",
        ),
        # Runtime MTL — finite-trace authority
        _role(
            "runtime-mtl",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.FINITE_TRACE,
            "runtime_mtl",
            display_name="In-process Runtime MTL",
            families=("temporal", "runtime_mtl"),
            notes="Finite-trace monitor authority only.",
        ),
        _role(
            "runtime-mtl-external",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.FINITE_TRACE,
            "runtime_mtl",
            display_name="External Runtime MTL",
            families=("temporal", "runtime_mtl"),
            notes="Finite-trace monitor authority only when hermetically certified.",
        ),
        # ZKP — attestation only
        _role(
            "zkp-circuit",
            ToolRole.AUTHORITY,
            ToolchainAuthorityCeiling.ATTESTATION,
            "attestation",
            display_name="ZKP circuit binding",
            families=("attestation", "zkp"),
            notes="Attestation authority only; never theorem/kernel authority.",
        ),
        # OPAM support companion
        _role(
            "opam",
            ToolRole.SUPPORT,
            ToolchainAuthorityCeiling.NONE,
            "support",
            "kernel",
            "protocol",
            display_name="OPAM",
            families=("kernel", "protocol"),
            notes="Support only; cannot promote a property lane by itself.",
        ),
    )


def build_default_role_matrix() -> dict[str, FormalVerificationToolRole]:
    roles = {item.tool_id: item for item in _build_default_roles()}
    if len(roles) != len(_build_default_roles()):
        raise ToolchainRoleError("duplicate tool_id in default role matrix")
    return roles


def build_default_lanes() -> dict[str, SemanticLane]:
    lanes = {item.lane_id: item for item in _build_default_lanes()}
    if len(lanes) != len(_build_default_lanes()):
        raise ToolchainRoleError("duplicate lane_id in default lane registry")
    return lanes


def default_promotion_policy() -> RoleAwarePromotionPolicy:
    """Construct the canonical role-aware promotion policy and matrix."""

    policy = RoleAwarePromotionPolicy(
        roles=build_default_role_matrix(),
        lanes=build_default_lanes(),
    )
    policy.assert_matrix_invariants()
    return policy


_DEFAULT_POLICY: RoleAwarePromotionPolicy | None = None


def default_policy() -> RoleAwarePromotionPolicy:
    global _DEFAULT_POLICY
    if _DEFAULT_POLICY is None:
        _DEFAULT_POLICY = default_promotion_policy()
    return _DEFAULT_POLICY


def reset_default_policy() -> None:
    """Test helper: drop the cached default policy."""

    global _DEFAULT_POLICY
    _DEFAULT_POLICY = None


def get_tool_role(tool_id: str) -> FormalVerificationToolRole:
    return default_policy().get_role(tool_id)


def list_tool_roles() -> tuple[FormalVerificationToolRole, ...]:
    policy = default_policy()
    return tuple(policy.roles[key] for key in policy.list_tool_ids())


def list_semantic_lanes() -> tuple[SemanticLane, ...]:
    policy = default_policy()
    return tuple(policy.lanes[key] for key in policy.list_lane_ids())


def evaluate_role_aware_promotion(
    tool_id: str,
    **kwargs: Any,
) -> PromotionDecision:
    return default_policy().evaluate_promotion(tool_id, **kwargs)


def can_satisfy_certified_authority_requirement(tool_id: str) -> bool:
    return default_policy().get_role(tool_id).can_satisfy_certified_authority


def tools_by_role(role: ToolRole | str) -> tuple[FormalVerificationToolRole, ...]:
    resolved = _enum(role, ToolRole, "role")
    return tuple(
        item for item in list_tool_roles() if item.role is resolved
    )


def tools_by_authority_ceiling(
    ceiling: ToolchainAuthorityCeiling | str,
) -> tuple[FormalVerificationToolRole, ...]:
    resolved = _enum(ceiling, ToolchainAuthorityCeiling, "authority_ceiling")
    return tuple(
        item
        for item in list_tool_roles()
        if item.authority_ceiling is resolved
    )


def role_matrix_side_effect_free_on_import() -> bool:
    """Documented guarantee for security tests and packaging gates."""

    return True


__all__ = [
    "FORMAL_VERIFICATION_TOOL_ROLE_INTERFACE",
    "ROLE_AWARE_PROMOTION_POLICY_INTERFACE",
    "FORMAL_VERIFICATION_SPECIALIZED_RECEIPT_AGGREGATION_INTERFACE",
    "TOOL_ROLE_SCHEMA",
    "PROMOTION_POLICY_SCHEMA",
    "SEMANTIC_LANE_SCHEMA",
    "SPECIALIZED_RECEIPT_AGGREGATION_SCHEMA",
    "GOAL_ID",
    "TASK_ID",
    "SPECIALIZED_RECEIPT_AGGREGATION_GOAL_ID",
    "SPECIALIZED_RECEIPT_AGGREGATION_TASK_ID",
    "PROGRAM",
    "ToolchainRoleError",
    "ToolRole",
    "ToolchainAuthorityCeiling",
    "FormalVerificationToolRole",
    "SemanticLane",
    "PromotionDecision",
    "CompositeLaneHandler",
    "RoleAwarePromotionPolicy",
    "handler_registry_key",
    "parse_handler_registry_key",
    "infer_handler_tool_id",
    "role_can_satisfy_certified_authority",
    "build_default_role_matrix",
    "build_default_lanes",
    "default_promotion_policy",
    "default_policy",
    "reset_default_policy",
    "get_tool_role",
    "list_tool_roles",
    "list_semantic_lanes",
    "evaluate_role_aware_promotion",
    "can_satisfy_certified_authority_requirement",
    "tools_by_role",
    "tools_by_authority_ceiling",
    "role_matrix_side_effect_free_on_import",
]
