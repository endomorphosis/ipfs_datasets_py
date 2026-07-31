"""Canary routing and atomic catalog-head rollback (KGP-033).

Canary mode routes **allowlisted** graph IDs to the candidate (new-stack) read
path while all other graphs continue on the baseline. Promotion records the
pre-canary branch head as a **verified immutable head**. Rollback restores
that head with catalog CAS — never by converting or deleting legacy data.

Normative rules:

* Only allowlisted ``(tenant, graph_id)`` pairs receive canary traffic.
* Rollback is ``cas_set_head(expected=current, new=last_verified)``.
* Verified heads reference immutable revision records already in the catalog.
* No in-place conversion or deletion of legacy payloads.
* Security / correctness threshold breaches disable canary routing and may
  trigger automatic rollback when configured.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Final,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
)

from ipfs_datasets_py.knowledge_graphs.catalog import (
    DEFAULT_BRANCH,
    CatalogError,
    GraphCatalog,
)
from ipfs_datasets_py.knowledge_graphs.migration.shadow import (
    ShadowConfig,
    ShadowMetrics,
    ShadowReader,
    ShadowStopReason,
    ShadowStoppedError,
)

T = TypeVar("T")

CANARY_SCHEMA_VERSION: Final = "kg-canary-control/v1"
VERIFIED_HEAD_SCHEMA_VERSION: Final = "kg-verified-head/v1"
ROLLBACK_SCHEMA_VERSION: Final = "kg-canary-rollback/v1"

GraphKey = Tuple[str, str]  # (tenant, graph_id)


class CanaryRoute(str, Enum):
    """Which read path a request should use."""

    BASELINE = "baseline"
    CANARY = "canary"
    SHADOW = "shadow"  # dual-read; caller still gets baseline


class CanaryState(str, Enum):
    """Lifecycle state of the canary controller."""

    DISABLED = "disabled"
    ACTIVE = "active"
    STOPPED = "stopped"
    ROLLING_BACK = "rolling_back"


class RollbackReason(str, Enum):
    """Why a canary head was rolled back."""

    MANUAL = "manual"
    SECURITY = "security"
    CORRECTNESS = "correctness"
    MISMATCH_THRESHOLD = "mismatch_threshold"
    SHADOW_STOPPED = "shadow_stopped"
    OPERATOR = "operator"


class CanaryError(Exception):
    """Base error for canary / rollback controls."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "CANARY_ERROR",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class CanaryNotAllowlistedError(CanaryError):
    def __init__(self, tenant: str, graph_id: str) -> None:
        super().__init__(
            f"graph {tenant}/{graph_id} is not on the canary allowlist",
            code="NOT_ALLOWLISTED",
            details={"tenant": tenant, "graph_id": graph_id},
        )


class NoVerifiedHeadError(CanaryError):
    def __init__(self, tenant: str, graph_id: str, branch: str) -> None:
        super().__init__(
            f"no verified immutable head for {tenant}/{graph_id}@{branch}",
            code="NO_VERIFIED_HEAD",
            details={"tenant": tenant, "graph_id": graph_id, "branch": branch},
        )


class RollbackConflictError(CanaryError):
    def __init__(
        self,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message, code="ROLLBACK_CONFLICT", details=details)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


def _graph_key(tenant: str, graph_id: str) -> GraphKey:
    return (str(tenant).strip(), str(graph_id).strip())


@dataclass(frozen=True, slots=True)
class VerifiedHead:
    """Last known-good immutable branch head for rollback targets.

    Points at an immutable catalog revision. Payload data is never mutated
    when recording or restoring this head.
    """

    tenant: str
    graph_id: str
    branch: str
    revision_id: str
    verified_at: float
    checksum: Optional[str] = None
    pin_root: Optional[str] = None
    manifest_cid: Optional[str] = None
    source: str = "promotion"
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = VERIFIED_HEAD_SCHEMA_VERSION

    @property
    def key(self) -> GraphKey:
        return _graph_key(self.tenant, self.graph_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "revision_id": self.revision_id,
            "verified_at": self.verified_at,
            "checksum": self.checksum,
            "pin_root": self.pin_root,
            "manifest_cid": self.manifest_cid,
            "source": self.source,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VerifiedHead":
        return cls(
            tenant=str(data["tenant"]),
            graph_id=str(data["graph_id"]),
            branch=str(data.get("branch") or DEFAULT_BRANCH),
            revision_id=str(data["revision_id"]),
            verified_at=float(data.get("verified_at") or time.time()),
            checksum=data.get("checksum"),
            pin_root=data.get("pin_root"),
            manifest_cid=data.get("manifest_cid"),
            source=str(data.get("source") or "promotion"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CanaryConfig:
    """Allowlist and safety policy for canary routing."""

    allowlist: FrozenSet[GraphKey] = frozenset()
    enabled: bool = True
    auto_rollback_on_security: bool = True
    auto_rollback_on_correctness: bool = True
    auto_disable_on_shadow_stop: bool = True
    default_branch: str = DEFAULT_BRANCH
    label: str = "default"
    # When True, non-allowlisted graphs still dual-read in shadow mode.
    shadow_non_canary: bool = False

    def __post_init__(self) -> None:
        # Normalize allowlist keys.
        normalized: Set[GraphKey] = set()
        for item in self.allowlist:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                normalized.add(_graph_key(item[0], item[1]))
            else:
                raise ValueError(
                    "allowlist entries must be (tenant, graph_id) pairs"
                )
        object.__setattr__(self, "allowlist", frozenset(normalized))
        if not self.default_branch:
            raise ValueError("default_branch must be non-empty")

    def with_allowlist(
        self, entries: Iterable[Union[GraphKey, Sequence[str]]]
    ) -> "CanaryConfig":
        keys: Set[GraphKey] = set(self.allowlist)
        for item in entries:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                keys.add(_graph_key(item[0], item[1]))
            else:
                raise ValueError(
                    "allowlist entries must be (tenant, graph_id) pairs"
                )
        return CanaryConfig(
            allowlist=frozenset(keys),
            enabled=self.enabled,
            auto_rollback_on_security=self.auto_rollback_on_security,
            auto_rollback_on_correctness=self.auto_rollback_on_correctness,
            auto_disable_on_shadow_stop=self.auto_disable_on_shadow_stop,
            default_branch=self.default_branch,
            label=self.label,
            shadow_non_canary=self.shadow_non_canary,
        )

    def is_allowlisted(self, tenant: str, graph_id: str) -> bool:
        return _graph_key(tenant, graph_id) in self.allowlist

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowlist": sorted(
                [{"tenant": t, "graph_id": g} for t, g in self.allowlist],
                key=lambda d: (d["tenant"], d["graph_id"]),
            ),
            "enabled": self.enabled,
            "auto_rollback_on_security": self.auto_rollback_on_security,
            "auto_rollback_on_correctness": self.auto_rollback_on_correctness,
            "auto_disable_on_shadow_stop": self.auto_disable_on_shadow_stop,
            "default_branch": self.default_branch,
            "label": self.label,
            "shadow_non_canary": self.shadow_non_canary,
        }


@dataclass(frozen=True, slots=True)
class RollbackResult:
    """Outcome of an atomic catalog-head rollback."""

    ok: bool
    tenant: str
    graph_id: str
    branch: str
    from_revision: Optional[str]
    to_revision: Optional[str]
    reason: RollbackReason
    message: str = ""
    verified_head: Optional[VerifiedHead] = None
    error: Optional[str] = None
    schema_version: str = ROLLBACK_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "from_revision": self.from_revision,
            "to_revision": self.to_revision,
            "reason": self.reason.value,
            "message": self.message,
            "verified_head": (
                self.verified_head.to_dict() if self.verified_head else None
            ),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Outcome of promoting a canary revision onto an allowlisted graph."""

    ok: bool
    tenant: str
    graph_id: str
    branch: str
    previous_revision: str
    canary_revision: str
    verified_head: VerifiedHead
    message: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "previous_revision": self.previous_revision,
            "canary_revision": self.canary_revision,
            "verified_head": self.verified_head.to_dict(),
            "message": self.message,
            "error": self.error,
        }


@dataclass
class CanaryMetrics:
    """Bounded observability for canary routing and rollbacks."""

    schema_version: str = CANARY_SCHEMA_VERSION
    label: str = "default"
    route_baseline: int = 0
    route_canary: int = 0
    route_shadow: int = 0
    promotions: int = 0
    rollbacks: int = 0
    rollback_failures: int = 0
    auto_stops: int = 0
    last_rollback: Optional[Dict[str, Any]] = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def inc_route(self, route: CanaryRoute) -> None:
        with self._lock:
            if route is CanaryRoute.BASELINE:
                self.route_baseline += 1
            elif route is CanaryRoute.CANARY:
                self.route_canary += 1
            elif route is CanaryRoute.SHADOW:
                self.route_shadow += 1

    def record_promotion(self) -> None:
        with self._lock:
            self.promotions += 1

    def record_rollback(self, result: RollbackResult) -> None:
        with self._lock:
            if result.ok:
                self.rollbacks += 1
            else:
                self.rollback_failures += 1
            self.last_rollback = result.to_dict()

    def record_auto_stop(self) -> None:
        with self._lock:
            self.auto_stops += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema_version": self.schema_version,
                "label": self.label,
                "route_baseline": self.route_baseline,
                "route_canary": self.route_canary,
                "route_shadow": self.route_shadow,
                "promotions": self.promotions,
                "rollbacks": self.rollbacks,
                "rollback_failures": self.rollback_failures,
                "auto_stops": self.auto_stops,
                "last_rollback": self.last_rollback,
            }


# ---------------------------------------------------------------------------
# Verified head registry
# ---------------------------------------------------------------------------


class VerifiedHeadRegistry:
    """In-process registry of last verified immutable heads.

    The catalog remains the source of truth for revision immutability; this
    registry only records *which* revision is the rollback target.
    """

    def __init__(self) -> None:
        self._heads: Dict[Tuple[str, str, str], VerifiedHead] = {}
        self._lock = threading.RLock()

    def put(self, head: VerifiedHead) -> VerifiedHead:
        key = (head.tenant, head.graph_id, head.branch)
        with self._lock:
            self._heads[key] = head
        return head

    def get(
        self,
        tenant: str,
        graph_id: str,
        branch: str = DEFAULT_BRANCH,
    ) -> Optional[VerifiedHead]:
        with self._lock:
            return self._heads.get((tenant, graph_id, branch))

    def remove(
        self,
        tenant: str,
        graph_id: str,
        branch: str = DEFAULT_BRANCH,
    ) -> Optional[VerifiedHead]:
        with self._lock:
            return self._heads.pop((tenant, graph_id, branch), None)

    def list_heads(self) -> List[VerifiedHead]:
        with self._lock:
            return list(self._heads.values())

    def clear(self) -> None:
        with self._lock:
            self._heads.clear()

    def snapshot(self) -> List[Dict[str, Any]]:
        return [h.to_dict() for h in self.list_heads()]


# ---------------------------------------------------------------------------
# Canary router + controller
# ---------------------------------------------------------------------------


class CanaryRouter:
    """Route decisions for allowlisted graph IDs.

    * Allowlisted + canary active → :attr:`CanaryRoute.CANARY`
    * Non-allowlisted + shadow_non_canary → :attr:`CanaryRoute.SHADOW`
    * Otherwise → :attr:`CanaryRoute.BASELINE`
    """

    def __init__(self, config: Optional[CanaryConfig] = None) -> None:
        self._config = config or CanaryConfig()
        self._state = CanaryState.ACTIVE if self._config.enabled else CanaryState.DISABLED
        self._lock = threading.RLock()
        self.metrics = CanaryMetrics(label=self._config.label)

    @property
    def config(self) -> CanaryConfig:
        return self._config

    @property
    def state(self) -> CanaryState:
        with self._lock:
            return self._state

    def set_config(self, config: CanaryConfig) -> None:
        with self._lock:
            self._config = config
            if not config.enabled:
                self._state = CanaryState.DISABLED
            elif self._state is CanaryState.DISABLED:
                self._state = CanaryState.ACTIVE

    def enable(self) -> None:
        with self._lock:
            self._config = CanaryConfig(
                allowlist=self._config.allowlist,
                enabled=True,
                auto_rollback_on_security=self._config.auto_rollback_on_security,
                auto_rollback_on_correctness=self._config.auto_rollback_on_correctness,
                auto_disable_on_shadow_stop=self._config.auto_disable_on_shadow_stop,
                default_branch=self._config.default_branch,
                label=self._config.label,
                shadow_non_canary=self._config.shadow_non_canary,
            )
            if self._state is not CanaryState.STOPPED:
                self._state = CanaryState.ACTIVE

    def disable(self) -> None:
        with self._lock:
            self._config = CanaryConfig(
                allowlist=self._config.allowlist,
                enabled=False,
                auto_rollback_on_security=self._config.auto_rollback_on_security,
                auto_rollback_on_correctness=self._config.auto_rollback_on_correctness,
                auto_disable_on_shadow_stop=self._config.auto_disable_on_shadow_stop,
                default_branch=self._config.default_branch,
                label=self._config.label,
                shadow_non_canary=self._config.shadow_non_canary,
            )
            self._state = CanaryState.DISABLED

    def stop(self) -> None:
        with self._lock:
            self._state = CanaryState.STOPPED
            self.metrics.record_auto_stop()

    def resume(self) -> None:
        with self._lock:
            if self._config.enabled:
                self._state = CanaryState.ACTIVE
            else:
                self._state = CanaryState.DISABLED

    def add_to_allowlist(self, tenant: str, graph_id: str) -> None:
        with self._lock:
            self._config = self._config.with_allowlist([(tenant, graph_id)])

    def remove_from_allowlist(self, tenant: str, graph_id: str) -> None:
        with self._lock:
            remaining = {
                k for k in self._config.allowlist if k != _graph_key(tenant, graph_id)
            }
            self._config = CanaryConfig(
                allowlist=frozenset(remaining),
                enabled=self._config.enabled,
                auto_rollback_on_security=self._config.auto_rollback_on_security,
                auto_rollback_on_correctness=self._config.auto_rollback_on_correctness,
                auto_disable_on_shadow_stop=self._config.auto_disable_on_shadow_stop,
                default_branch=self._config.default_branch,
                label=self._config.label,
                shadow_non_canary=self._config.shadow_non_canary,
            )

    def is_allowlisted(self, tenant: str, graph_id: str) -> bool:
        return self._config.is_allowlisted(tenant, graph_id)

    def resolve(self, tenant: str, graph_id: str) -> CanaryRoute:
        """Decide the route for ``tenant/graph_id`` and record metrics."""

        with self._lock:
            cfg = self._config
            state = self._state

        if state in (CanaryState.DISABLED, CanaryState.STOPPED, CanaryState.ROLLING_BACK):
            route = CanaryRoute.BASELINE
        elif not cfg.enabled:
            route = CanaryRoute.BASELINE
        elif cfg.is_allowlisted(tenant, graph_id):
            route = CanaryRoute.CANARY
        elif cfg.shadow_non_canary:
            route = CanaryRoute.SHADOW
        else:
            route = CanaryRoute.BASELINE

        self.metrics.inc_route(route)
        return route

    def route_read(
        self,
        tenant: str,
        graph_id: str,
        *,
        baseline: Callable[[], T],
        canary: Callable[[], T],
        shadow_reader: Optional[ShadowReader] = None,
        operation: str = "read",
    ) -> Tuple[T, CanaryRoute]:
        """Execute the resolved route; caller result depends on route.

        * ``BASELINE`` / ``SHADOW`` → baseline value (shadow dual-reads when SHADOW)
        * ``CANARY`` → canary value
        """

        route = self.resolve(tenant, graph_id)
        if route is CanaryRoute.CANARY:
            return canary(), route
        if route is CanaryRoute.SHADOW and shadow_reader is not None:
            outcome = shadow_reader.read(
                primary=baseline,
                shadow=canary,
                operation=operation,
                graph_id=f"{tenant}/{graph_id}",
            )
            return outcome.result, route
        return baseline(), route


class CanaryController:
    """Promote, route, stop, and roll back canary graph heads.

    Binds a :class:`CanaryRouter`, optional :class:`ShadowReader`, verified-head
    registry, and a catalog for atomic CAS rollback.
    """

    def __init__(
        self,
        catalog: GraphCatalog,
        *,
        config: Optional[CanaryConfig] = None,
        shadow_reader: Optional[ShadowReader] = None,
        verified_heads: Optional[VerifiedHeadRegistry] = None,
    ) -> None:
        self.catalog = catalog
        self.router = CanaryRouter(config)
        self.shadow = shadow_reader or ShadowReader(
            ShadowConfig(label=(config.label if config else "default"))
        )
        self.verified_heads = verified_heads or VerifiedHeadRegistry()
        self._lock = threading.RLock()
        self._rollback_log: List[RollbackResult] = []

    @property
    def config(self) -> CanaryConfig:
        return self.router.config

    @property
    def state(self) -> CanaryState:
        return self.router.state

    # -- allowlist ---------------------------------------------------------

    def allowlist_graph(self, tenant: str, graph_id: str) -> None:
        self.router.add_to_allowlist(tenant, graph_id)

    def denylist_graph(self, tenant: str, graph_id: str) -> None:
        self.router.remove_from_allowlist(tenant, graph_id)

    # -- verified heads ----------------------------------------------------

    def record_verified_head(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        branch: Optional[str] = None,
        source: str = "explicit",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> VerifiedHead:
        """Record *revision_id* as the last verified immutable head.

        Validates that the revision exists in the catalog (immutable record)
        but never mutates graph payloads.
        """

        branch = branch or self.config.default_branch
        rev = self.catalog.get_revision(tenant, graph_id, revision_id)
        head = VerifiedHead(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            revision_id=revision_id,
            verified_at=time.time(),
            checksum=rev.checksum,
            pin_root=rev.pin_root,
            manifest_cid=rev.manifest_cid,
            source=source,
            metadata=dict(metadata or {}),
        )
        return self.verified_heads.put(head)

    def get_verified_head(
        self,
        tenant: str,
        graph_id: str,
        branch: Optional[str] = None,
    ) -> Optional[VerifiedHead]:
        branch = branch or self.config.default_branch
        return self.verified_heads.get(tenant, graph_id, branch)

    # -- promotion ---------------------------------------------------------

    def promote(
        self,
        tenant: str,
        graph_id: str,
        canary_revision: str,
        *,
        branch: Optional[str] = None,
        require_allowlisted: bool = True,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> PromotionResult:
        """Point catalog head at *canary_revision*, saving prior head as verified.

        The prior head becomes the rollback target. The canary revision must
        already be registered as an immutable catalog revision. Legacy data is
        never converted or deleted.
        """

        branch = branch or self.config.default_branch
        if require_allowlisted and not self.router.is_allowlisted(tenant, graph_id):
            raise CanaryNotAllowlistedError(tenant, graph_id)

        current = self.catalog.get_branch(tenant, graph_id, branch)
        previous = current.head_revision
        if previous == canary_revision:
            # Already at canary revision — still ensure verified head exists.
            existing = self.get_verified_head(tenant, graph_id, branch)
            if existing is None:
                # Record parent of canary if available.
                rev = self.catalog.get_revision(tenant, graph_id, canary_revision)
                parent = rev.parent_revision or previous
                existing = self.record_verified_head(
                    tenant,
                    graph_id,
                    parent,
                    branch=branch,
                    source="already_promoted",
                    metadata=metadata,
                )
            return PromotionResult(
                ok=True,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                previous_revision=previous,
                canary_revision=canary_revision,
                verified_head=existing,
                message="already_at_canary_revision",
            )

        # Ensure canary revision is registered (immutable) before CAS.
        self.catalog.get_revision(tenant, graph_id, canary_revision)

        verified = self.record_verified_head(
            tenant,
            graph_id,
            previous,
            branch=branch,
            source="promotion",
            metadata=metadata,
        )

        key = idempotency_key or f"canary-promote-{tenant}-{graph_id}-{canary_revision}-{uuid.uuid4().hex[:12]}"
        try:
            self.catalog.cas_set_head(
                tenant,
                graph_id,
                branch,
                expected_revision=previous,
                new_revision=canary_revision,
                pin_root=None,
                idempotency_key=key,
            )
        except CatalogError as exc:
            return PromotionResult(
                ok=False,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                previous_revision=previous,
                canary_revision=canary_revision,
                verified_head=verified,
                message="cas_promote_failed",
                error=f"{exc.code}: {exc}",
            )

        self.router.metrics.record_promotion()
        return PromotionResult(
            ok=True,
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            previous_revision=previous,
            canary_revision=canary_revision,
            verified_head=verified,
            message="promoted",
        )

    # -- rollback ----------------------------------------------------------

    def rollback(
        self,
        tenant: str,
        graph_id: str,
        *,
        branch: Optional[str] = None,
        reason: RollbackReason = RollbackReason.MANUAL,
        idempotency_key: Optional[str] = None,
        remove_from_allowlist: bool = True,
    ) -> RollbackResult:
        """Atomically restore the last verified immutable head.

        Uses catalog ``cas_set_head`` with ``expected_revision=current`` and
        ``new_revision=verified``. Never converts or deletes legacy data.
        """

        branch = branch or self.config.default_branch
        verified = self.get_verified_head(tenant, graph_id, branch)
        if verified is None:
            result = RollbackResult(
                ok=False,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                from_revision=None,
                to_revision=None,
                reason=reason,
                message="no_verified_head",
                error="NO_VERIFIED_HEAD",
            )
            self.router.metrics.record_rollback(result)
            self._append_rollback_log(result)
            raise NoVerifiedHeadError(tenant, graph_id, branch)

        # Confirm verified revision still exists and is immutable in catalog.
        try:
            rev = self.catalog.get_revision(
                tenant, graph_id, verified.revision_id
            )
        except CatalogError as exc:
            result = RollbackResult(
                ok=False,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                from_revision=None,
                to_revision=verified.revision_id,
                reason=reason,
                message="verified_revision_missing",
                verified_head=verified,
                error=f"{exc.code}: {exc}",
            )
            self.router.metrics.record_rollback(result)
            self._append_rollback_log(result)
            return result

        current = self.catalog.get_branch(tenant, graph_id, branch)
        from_rev = current.head_revision

        if from_rev == verified.revision_id:
            result = RollbackResult(
                ok=True,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                from_revision=from_rev,
                to_revision=verified.revision_id,
                reason=reason,
                message="already_at_verified_head",
                verified_head=verified,
            )
            if remove_from_allowlist:
                self.denylist_graph(tenant, graph_id)
            self.router.metrics.record_rollback(result)
            self._append_rollback_log(result)
            return result

        key = (
            idempotency_key
            or f"canary-rollback-{tenant}-{graph_id}-{verified.revision_id}-{uuid.uuid4().hex[:12]}"
        )
        with self._lock:
            prev_state = self.router.state
            # Mark rolling_back so concurrent route_read falls back to baseline.
            with self.router._lock:  # noqa: SLF001 — intentional controller coordination
                self.router._state = CanaryState.ROLLING_BACK  # noqa: SLF001

            try:
                self.catalog.cas_set_head(
                    tenant,
                    graph_id,
                    branch,
                    expected_revision=from_rev,
                    new_revision=verified.revision_id,
                    pin_root=rev.pin_root,
                    idempotency_key=key,
                )
            except CatalogError as exc:
                # Restore prior router state on conflict.
                with self.router._lock:  # noqa: SLF001
                    self.router._state = prev_state  # noqa: SLF001
                result = RollbackResult(
                    ok=False,
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    from_revision=from_rev,
                    to_revision=verified.revision_id,
                    reason=reason,
                    message="cas_rollback_failed",
                    verified_head=verified,
                    error=f"{exc.code}: {exc}",
                )
                self.router.metrics.record_rollback(result)
                self._append_rollback_log(result)
                if exc.code == "CONFLICT":
                    raise RollbackConflictError(
                        "branch head CAS conflict during rollback",
                        details={
                            "tenant": tenant,
                            "graph_id": graph_id,
                            "branch": branch,
                            "from_revision": from_rev,
                            "to_revision": verified.revision_id,
                            "catalog": getattr(exc, "details", {}),
                        },
                    ) from exc
                return result

            if remove_from_allowlist:
                self.denylist_graph(tenant, graph_id)
            # After successful rollback, disable canary routing for safety.
            self.router.stop()

        result = RollbackResult(
            ok=True,
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            from_revision=from_rev,
            to_revision=verified.revision_id,
            reason=reason,
            message="rolled_back_to_verified_head",
            verified_head=verified,
        )
        self.router.metrics.record_rollback(result)
        self._append_rollback_log(result)
        return result

    def rollback_all(
        self,
        *,
        reason: RollbackReason = RollbackReason.OPERATOR,
    ) -> List[RollbackResult]:
        """Roll back every graph that has a verified head."""

        results: List[RollbackResult] = []
        for head in self.verified_heads.list_heads():
            try:
                results.append(
                    self.rollback(
                        head.tenant,
                        head.graph_id,
                        branch=head.branch,
                        reason=reason,
                        remove_from_allowlist=True,
                    )
                )
            except (NoVerifiedHeadError, RollbackConflictError, CanaryError) as exc:
                results.append(
                    RollbackResult(
                        ok=False,
                        tenant=head.tenant,
                        graph_id=head.graph_id,
                        branch=head.branch,
                        from_revision=None,
                        to_revision=head.revision_id,
                        reason=reason,
                        message="rollback_all_item_failed",
                        verified_head=head,
                        error=str(exc),
                    )
                )
        return results

    # -- routed reads with shadow coupling ---------------------------------

    def read(
        self,
        tenant: str,
        graph_id: str,
        *,
        baseline: Callable[[], T],
        canary: Callable[[], T],
        operation: str = "read",
    ) -> Tuple[T, CanaryRoute]:
        """Route a read and react to shadow auto-stop thresholds."""

        value, route = self.router.route_read(
            tenant,
            graph_id,
            baseline=baseline,
            canary=canary,
            shadow_reader=self.shadow,
            operation=operation,
        )
        self._maybe_react_to_shadow_stop(tenant, graph_id)
        return value, route

    def shadow_compare(
        self,
        tenant: str,
        graph_id: str,
        *,
        baseline: Callable[[], T],
        candidate: Callable[[], Any],
        operation: str = "shadow_read",
    ) -> Any:
        """Always dual-read; return baseline result for the caller.

        Used when canary is not yet promoted but parity evidence is needed.
        """

        outcome = self.shadow.read(
            primary=baseline,
            shadow=candidate,
            operation=operation,
            graph_id=f"{tenant}/{graph_id}",
        )
        self._maybe_react_to_shadow_stop(tenant, graph_id)
        return outcome.result

    def _maybe_react_to_shadow_stop(self, tenant: str, graph_id: str) -> None:
        if not self.shadow.is_stopped:
            return
        reason = self.shadow.stop_reason
        cfg = self.config

        if cfg.auto_disable_on_shadow_stop and self.router.state is CanaryState.ACTIVE:
            self.router.stop()

        rollback_reason: Optional[RollbackReason] = None
        if reason is ShadowStopReason.SECURITY and cfg.auto_rollback_on_security:
            rollback_reason = RollbackReason.SECURITY
        elif reason in (
            ShadowStopReason.MISMATCH_RATE,
            ShadowStopReason.ABSOLUTE_MISMATCHES,
            ShadowStopReason.CORRECTNESS,
            ShadowStopReason.SHADOW_ERROR_RATE,
        ) and cfg.auto_rollback_on_correctness:
            if reason is ShadowStopReason.MISMATCH_RATE:
                rollback_reason = RollbackReason.MISMATCH_THRESHOLD
            else:
                rollback_reason = RollbackReason.CORRECTNESS
        elif reason is ShadowStopReason.MANUAL:
            rollback_reason = RollbackReason.SHADOW_STOPPED

        if rollback_reason is None:
            return
        if not self.router.is_allowlisted(tenant, graph_id):
            # Still try if a verified head exists for this graph.
            if self.get_verified_head(tenant, graph_id) is None:
                return
        try:
            self.rollback(
                tenant,
                graph_id,
                reason=rollback_reason,
                remove_from_allowlist=True,
            )
        except (NoVerifiedHeadError, RollbackConflictError, CanaryError):
            # Fail closed on routing (already stopped); surface via metrics.
            return

    def _append_rollback_log(self, result: RollbackResult) -> None:
        with self._lock:
            self._rollback_log.append(result)
            # Bound log size.
            if len(self._rollback_log) > 256:
                self._rollback_log = self._rollback_log[-256:]

    def rollback_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._rollback_log]

    def metrics_snapshot(self) -> Dict[str, Any]:
        return {
            "schema_version": CANARY_SCHEMA_VERSION,
            "state": self.state.value,
            "config": self.config.to_dict(),
            "canary": self.router.metrics.snapshot(),
            "shadow": self.shadow.metrics_snapshot(),
            "verified_heads": self.verified_heads.snapshot(),
            "rollback_history": self.rollback_history(),
        }


def capture_verified_head_from_catalog(
    catalog: GraphCatalog,
    tenant: str,
    graph_id: str,
    *,
    branch: str = DEFAULT_BRANCH,
    source: str = "catalog_capture",
) -> VerifiedHead:
    """Snapshot the current branch head as a verified immutable head.

    Read-only with respect to payloads; only records metadata.
    """

    br = catalog.get_branch(tenant, graph_id, branch)
    rev = catalog.get_revision(tenant, graph_id, br.head_revision)
    return VerifiedHead(
        tenant=tenant,
        graph_id=graph_id,
        branch=branch,
        revision_id=br.head_revision,
        verified_at=time.time(),
        checksum=rev.checksum,
        pin_root=rev.pin_root,
        manifest_cid=rev.manifest_cid,
        source=source,
    )


__all__ = [
    "CANARY_SCHEMA_VERSION",
    "VERIFIED_HEAD_SCHEMA_VERSION",
    "ROLLBACK_SCHEMA_VERSION",
    "GraphKey",
    "CanaryRoute",
    "CanaryState",
    "RollbackReason",
    "CanaryError",
    "CanaryNotAllowlistedError",
    "NoVerifiedHeadError",
    "RollbackConflictError",
    "VerifiedHead",
    "CanaryConfig",
    "RollbackResult",
    "PromotionResult",
    "CanaryMetrics",
    "VerifiedHeadRegistry",
    "CanaryRouter",
    "CanaryController",
    "capture_verified_head_from_catalog",
    # Re-exported for convenience with dual-read coupling
    "ShadowConfig",
    "ShadowMetrics",
    "ShadowReader",
    "ShadowStopReason",
    "ShadowStoppedError",
]
