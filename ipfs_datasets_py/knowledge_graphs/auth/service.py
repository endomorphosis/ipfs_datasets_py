"""UCAN enforcement for GraphService (KGP-022).

:class:`GraphAuthorizationService` validates attenuated graph UCAN chains
**before** catalog metadata lookup, graph open, index, or shard access. It
implements the same authorizer protocol used by :class:`GraphService` so
Python and CLI callers can opt into identical enforcement by injecting this
service as ``authorizer=...``.

Checks (fail-closed)
--------------------
- resource containment and ability attenuation across every chain link
- issuer/audience linkage
- expiry / not-before
- revocation (CID / proof CID)
- nonce / idempotency replay defense
- closed-key caveats (branch, revision, query, property, row, byte, depth,
  time, audience, count)

Every allow and deny emits a bounded, content-addressed, redacted audit
receipt with policy / revision / request digests.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Mapping, MutableSet, Sequence
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
    Union,
)

from ipfs_datasets_py.knowledge_graphs.audit import (
    AuthorizationAuditLog,
    AuditEmitter,
    EnrichedAuthorizationReceipt,
    NullAuditEmitter,
    build_enriched_receipt,
    policy_revision_digest,
)
from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    CONTRACT_VERSION,
    OPERATION_ABILITIES,
    ChainValidationResult,
    GraphCaveats,
    GraphDelegationLink,
    GraphResource,
    UCANContractError,
    ability_for_operation,
    build_authorization_receipt,
    caveats_from_mapping,
    deny_reason_to_error_code,
    link_from_delegation_token,
    parse_graph_resource,
    validate_delegation_chain,
)

# Optional import of GraphService decision type — keep soft to avoid cycles
# when only contracts + this module are loaded under test.
try:
    from ipfs_datasets_py.knowledge_graphs.service import (  # type: ignore
        AuthorizationDecision,
        GraphTarget,
    )
except Exception:  # pragma: no cover - fallback shapes for isolated unit tests
    from dataclasses import dataclass as _dc

    @_dc(frozen=True, slots=True)
    class AuthorizationDecision:  # type: ignore[no-redef]
        allowed: bool
        principal: Optional[str]
        ability: str
        receipt_ref: str
        reason: Optional[str] = None
        code: Optional[str] = None

        def to_json_dict(self) -> Dict[str, Any]:
            return {
                "allowed": self.allowed,
                "principal": self.principal,
                "ability": self.ability,
                "receipt_ref": self.receipt_ref,
                "reason": self.reason,
                "code": self.code,
            }

    @_dc(frozen=True, slots=True)
    class GraphTarget:  # type: ignore[no-redef]
        tenant: str
        graph_id: str
        branch: Optional[str] = None
        revision: Optional[str] = None
        storage_profile: Optional[str] = None

        @property
        def uri(self) -> str:
            base = f"kg://{self.tenant}/{self.graph_id}"
            if self.revision is not None:
                return f"{base}/revisions/{self.revision}"
            if self.branch is not None:
                return f"{base}/branches/{self.branch}"
            return base

        def to_json_dict(self) -> Dict[str, Any]:
            return {
                "tenant": self.tenant,
                "graph_id": self.graph_id,
                "branch": self.branch,
                "revision": self.revision,
                "storage_profile": self.storage_profile,
                "uri": self.uri,
            }


JSONDict = Dict[str, Any]
ClockFn = Callable[[], float]

# Mutating abilities that bind nonce / idempotency by default when required.
_MUTATING_ABILITIES = frozenset(
    {"graph/write", "graph/admin", "graph/pin", "graph/delegate"}
)

# Operations that imply catalog / shard / index / metadata access after auth.
_PROTECTED_OPERATIONS = frozenset(OPERATION_ABILITIES.keys()) | frozenset(
    {"pin", "unpin", "delegate", "prefetch_shard", "open_index", "read_metadata"}
)

# Free-form pre-access operations → ability (not in OPERATION_ABILITIES).
_ACCESS_ABILITY_ALIASES: Dict[str, str] = {
    "prefetch_shard": "graph/read",
    "open_index": "graph/read",
    "read_metadata": "graph/read",
    "pin": "graph/pin",
    "unpin": "graph/pin",
    "delegate": "graph/delegate",
}


# ---------------------------------------------------------------------------
# Stores (revocation + nonce / idempotency)
# ---------------------------------------------------------------------------


class RevocationStore(Protocol):
    def is_revoked(self, cid: str) -> bool:
        ...

    def revoke(self, cid: str) -> None:
        ...

    def revoked_cids(self) -> Iterable[str]:
        ...


class InMemoryRevocationStore:
    """Thread-safe in-process revocation set."""

    def __init__(self, initial: Optional[Iterable[str]] = None) -> None:
        self._lock = threading.RLock()
        self._cids: Set[str] = set(initial or ())

    def is_revoked(self, cid: str) -> bool:
        with self._lock:
            return cid in self._cids

    def revoke(self, cid: str) -> None:
        if not cid:
            return
        with self._lock:
            self._cids.add(str(cid))

    def revoke_many(self, cids: Iterable[str]) -> None:
        with self._lock:
            for cid in cids:
                if cid:
                    self._cids.add(str(cid))

    def revoked_cids(self) -> Iterable[str]:
        with self._lock:
            return frozenset(self._cids)


class NonceStore(Protocol):
    """Replay cache for nonces and idempotency keys."""

    def seen(self, key: str) -> bool:
        ...

    def remember(self, key: str) -> bool:
        """Record *key*. Return False if it was already present (replay)."""
        ...


class InMemoryNonceStore:
    """Thread-safe nonce / idempotency store with optional capacity bound."""

    def __init__(self, *, max_entries: int = 100_000) -> None:
        self._lock = threading.RLock()
        self._keys: Dict[str, float] = {}
        self._max = max(1, int(max_entries))

    def seen(self, key: str) -> bool:
        with self._lock:
            return key in self._keys

    def remember(self, key: str) -> bool:
        if not key:
            return True
        with self._lock:
            if key in self._keys:
                return False
            self._keys[key] = time.time()
            while len(self._keys) > self._max:
                # Drop oldest by timestamp.
                oldest = min(self._keys.items(), key=lambda kv: kv[1])[0]
                del self._keys[oldest]
            return True

    def clear(self) -> None:
        with self._lock:
            self._keys.clear()

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.seen(key)


# ---------------------------------------------------------------------------
# Auth context parsing
# ---------------------------------------------------------------------------


def target_to_resource(target: Any) -> GraphResource:
    """Map a GraphTarget (or URI / mapping) to a :class:`GraphResource`."""
    if isinstance(target, GraphResource):
        return target
    if isinstance(target, str):
        return parse_graph_resource(target)
    uri = getattr(target, "uri", None)
    if isinstance(uri, str) and uri.startswith("kg://"):
        return parse_graph_resource(uri)
    if isinstance(target, Mapping):
        if target.get("uri"):
            return parse_graph_resource(str(target["uri"]))
        return GraphResource(
            tenant=str(target["tenant"]),
            graph_id=str(target["graph_id"]) if target.get("graph_id") else None,
            branch=target.get("branch"),
            revision=target.get("revision"),
        )
    tenant = getattr(target, "tenant", None)
    graph_id = getattr(target, "graph_id", None)
    if tenant is None or graph_id is None:
        raise UCANContractError(
            "invalid_resource",
            "cannot resolve GraphResource from target",
            details={"target_type": type(target).__name__},
        )
    return GraphResource(
        tenant=str(tenant),
        graph_id=str(graph_id),
        branch=getattr(target, "branch", None),
        revision=getattr(target, "revision", None),
    )


def _principal_from_auth(auth: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not auth:
        return None
    for key in ("principal", "subject", "invoker", "did", "actor"):
        val = auth.get(key)
        if val is not None and str(val):
            return str(val)
    return None


def _link_from_mapping(data: Mapping[str, Any]) -> GraphDelegationLink:
    """Build a :class:`GraphDelegationLink` from a JSON-like mapping."""
    caps_raw = data.get("capabilities") or []
    from ipfs_datasets_py.knowledge_graphs.auth.contracts import GraphCapability

    capabilities = []
    for cap in caps_raw:
        if isinstance(cap, GraphCapability):
            capabilities.append(cap)
        elif isinstance(cap, Mapping):
            capabilities.append(GraphCapability.from_mapping(cap))
        else:
            capabilities.append(
                GraphCapability.from_mapping(
                    {
                        "resource": getattr(cap, "resource", None),
                        "ability": getattr(cap, "ability", None),
                        "caveats": getattr(cap, "caveats", None),
                    }
                )
            )
    expiry = data.get("expiry")
    not_before = data.get("not_before")
    return GraphDelegationLink(
        issuer=str(data.get("issuer") or ""),
        audience=str(data.get("audience") or ""),
        capabilities=tuple(capabilities),
        expiry=float(expiry) if expiry is not None else None,
        not_before=float(not_before) if not_before is not None else None,
        cid=data.get("cid"),
        proof_cid=data.get("proof_cid") or data.get("proof"),
        nonce=data.get("nonce"),
        caveats=caveats_from_mapping(data.get("caveats")),
    )


def parse_delegation_chain(
    auth: Optional[Mapping[str, Any]],
) -> Tuple[List[GraphDelegationLink], Optional[str]]:
    """Extract a delegation chain from an auth context mapping.

    Accepts (in order of preference):

    - ``chain`` / ``links``: list of link mappings or :class:`GraphDelegationLink`
    - ``ucan_chain``: same
    - ``delegations`` / ``tokens``: Profile C tokens adapted via
      :func:`link_from_delegation_token`
    - single ``token`` / ``delegation``: one-link chain

    Returns ``(links, parse_error_reason)``. On success *parse_error_reason*
    is ``None``. Missing chain → ``("empty_chain" or "missing_token")``.
    """
    if not auth:
        return [], "missing_token"

    raw: Any = None
    for key in ("chain", "links", "ucan_chain", "delegation_chain"):
        if key in auth and auth[key] is not None:
            raw = auth[key]
            break

    if raw is None:
        for key in ("delegations", "tokens"):
            if key in auth and auth[key] is not None:
                raw = auth[key]
                break

    if raw is None:
        for key in ("token", "delegation", "ucan"):
            if key in auth and auth[key] is not None:
                raw = [auth[key]]
                break

    if raw is None:
        return [], "missing_token"

    if not isinstance(raw, (list, tuple)):
        raw = [raw]

    if len(raw) == 0:
        return [], "empty_chain"

    links: List[GraphDelegationLink] = []
    try:
        for item in raw:
            if isinstance(item, GraphDelegationLink):
                links.append(item)
            elif isinstance(item, Mapping):
                # Mapping may be a contract link or a thin Profile C view.
                if "capabilities" in item or "issuer" in item:
                    links.append(_link_from_mapping(item))
                else:
                    links.append(link_from_delegation_token(item))
            else:
                links.append(link_from_delegation_token(item))
    except UCANContractError as exc:
        return [], exc.reason
    except (TypeError, ValueError, KeyError):
        return [], "invalid_resource"

    return links, None


def _request_nonce(
    auth: Optional[Mapping[str, Any]],
    links: Sequence[GraphDelegationLink],
) -> Optional[str]:
    """Resolve the idempotency / nonce key for this invocation."""
    if auth:
        for key in ("nonce", "idempotency_key", "idempotencyKey"):
            val = auth.get(key)
            if val is not None and str(val):
                return str(val)
    if links:
        leaf = links[-1]
        if leaf.nonce:
            return str(leaf.nonce)
    return None


def _request_caveats_from_auth(
    auth: Optional[Mapping[str, Any]],
    *,
    target: Any = None,
) -> GraphCaveats:
    if not auth:
        return GraphCaveats.empty()
    raw = auth.get("caveats") or auth.get("request_caveats")
    if raw is None:
        # Promote well-known request dimensions into caveats for admission.
        promo: JSONDict = {}
        if auth.get("query_kind"):
            promo["query"] = [str(auth["query_kind"])]
        if auth.get("query_kinds"):
            promo["query"] = list(auth["query_kinds"])
        branch = auth.get("branch")
        if branch is None and target is not None:
            branch = getattr(target, "branch", None)
        if branch:
            promo["branch"] = [str(branch)]
        revision = auth.get("revision")
        if revision is None and target is not None:
            revision = getattr(target, "revision", None)
        if revision:
            promo["revision"] = [str(revision)]
        if promo:
            raw = promo
    return caveats_from_mapping(raw if isinstance(raw, Mapping) or raw is None else None)


# ---------------------------------------------------------------------------
# Enforcement result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnforcementResult:
    """Full outcome of a UCAN enforcement check (pre-catalog / pre-shard)."""

    allowed: bool
    decision: AuthorizationDecision
    receipt: EnrichedAuthorizationReceipt
    chain_result: ChainValidationResult
    resource_uri: str
    ability: str
    principal: Optional[str]
    phase: str = "before_access"

    def to_json_dict(self) -> JSONDict:
        return {
            "allowed": self.allowed,
            "decision": self.decision.to_json_dict(),
            "receipt": self.receipt.to_json_dict(),
            "chain_result": self.chain_result.to_json_dict(),
            "resource_uri": self.resource_uri,
            "ability": self.ability,
            "principal": self.principal,
            "phase": self.phase,
        }


# ---------------------------------------------------------------------------
# GraphAuthorizationService
# ---------------------------------------------------------------------------


@dataclass
class GraphAuthorizationService:
    """Fail-closed UCAN authorizer for :class:`GraphService`.

    Inject into GraphService::

        authz = GraphAuthorizationService(policy_id="policy:kg", ...)
        svc = GraphService.open(path, authorizer=authz, audit=authz.audit_log)

    Python / CLI opt-in uses the same object: pass it as ``authorizer`` (and
    optionally share :attr:`audit_log` as the service audit sink).
    """

    policy_id: str = "policy:kg-ucan"
    policy_revision: str = CONTRACT_VERSION
    require_invoker: bool = True
    require_nonce_for_mutations: bool = True
    require_nonce_always: bool = False
    clock: ClockFn = field(default_factory=lambda: time.time)
    revocations: RevocationStore = field(default_factory=InMemoryRevocationStore)
    nonces: NonceStore = field(default_factory=InMemoryNonceStore)
    audit_log: AuthorizationAuditLog = field(default_factory=AuthorizationAuditLog)
    policy_metadata: Dict[str, Any] = field(default_factory=dict)
    # When False, missing auth falls through as deny (never allow-all).
    # There is intentionally no "soft allow" mode.
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        policy_id: str = "policy:kg-ucan",
        policy_revision: str = CONTRACT_VERSION,
        require_nonce_for_mutations: bool = True,
        revoked_cids: Optional[Iterable[str]] = None,
        audit_sink: Optional[AuditEmitter] = None,
        **kwargs: Any,
    ) -> "GraphAuthorizationService":
        """Factory for Python/CLI opt-in enforcement contexts."""
        rev = InMemoryRevocationStore(revoked_cids)
        log = AuthorizationAuditLog(sink=audit_sink)
        return cls(
            policy_id=policy_id,
            policy_revision=policy_revision,
            require_nonce_for_mutations=require_nonce_for_mutations,
            revocations=rev,
            audit_log=log,
            **kwargs,
        )

    def bind_audit_sink(self, sink: AuditEmitter) -> None:
        """Attach a secondary sink (e.g. GraphService InMemoryAuditSink)."""
        self.audit_log.sink = sink

    # ------------------------------------------------------------------
    # Revocation / nonce administration
    # ------------------------------------------------------------------

    def revoke(self, *cids: str) -> None:
        for cid in cids:
            self.revocations.revoke(cid)

    def is_revoked(self, cid: str) -> bool:
        return self.revocations.is_revoked(cid)

    # ------------------------------------------------------------------
    # Authorizer protocol (GraphService)
    # ------------------------------------------------------------------

    def authorize(
        self,
        *,
        operation: str,
        target: Any,
        auth: Optional[Mapping[str, Any]],
        request_id: Optional[str],
    ) -> AuthorizationDecision:
        """GraphService authorizer entrypoint — always runs before handlers."""
        result = self.enforce(
            operation=operation,
            target=target,
            auth=auth,
            request_id=request_id,
            access_kind="service",
        )
        return result.decision

    # ------------------------------------------------------------------
    # Explicit pre-access gate (metadata / graph / index / shard)
    # ------------------------------------------------------------------

    def check_before_access(
        self,
        *,
        operation: str,
        target: Any,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        access_kind: str = "metadata",
    ) -> EnforcementResult:
        """Enforce UCAN before metadata, graph, index, or shard access.

        ``access_kind`` is recorded on the result for audit (``metadata``,
        ``graph``, ``index``, ``shard``, ``service``) but does not weaken
        validation — all kinds use the same fail-closed chain checks.
        """
        if access_kind not in {
            "metadata",
            "graph",
            "index",
            "shard",
            "service",
            "prefetch",
        }:
            access_kind = "metadata"
        return self.enforce(
            operation=operation,
            target=target,
            auth=auth,
            request_id=request_id,
            access_kind=access_kind,
        )

    def enforce(
        self,
        *,
        operation: str,
        target: Any,
        auth: Optional[Mapping[str, Any]] = None,
        request_id: Optional[str] = None,
        access_kind: str = "service",
        now: Optional[float] = None,
    ) -> EnforcementResult:
        """Full enforcement pipeline; always emits a receipt."""
        t = float(now if now is not None else self.clock())
        rid = request_id or f"req-{int(t * 1000)}"

        # Resolve ability (lifecycle ops + pre-access aliases)
        ability = self._ability_for_operation(operation)

        # Resolve resource
        try:
            resource = target_to_resource(target)
            resource_uri = resource.uri
        except UCANContractError as exc:
            return self._finalize_deny(
                reason=exc.reason,
                message=exc.message,
                ability=ability if "ability" in dir() else "graph/admin",
                resource_uri=str(getattr(target, "uri", "kg://invalid")),
                principal=_principal_from_auth(auth),
                request_id=rid,
                operation=operation,
                access_kind=access_kind,
                now=t,
                auth=auth,
                details=exc.details,
            )

        principal = _principal_from_auth(auth)
        links, parse_reason = parse_delegation_chain(auth)

        if parse_reason is not None:
            return self._finalize_deny(
                reason=parse_reason,
                message=f"authorization chain unavailable: {parse_reason}",
                ability=ability,
                resource_uri=resource_uri,
                principal=principal,
                request_id=rid,
                operation=operation,
                access_kind=access_kind,
                now=t,
                auth=auth,
                chain=links,
            )

        # Attach request-level nonce onto leaf for replay check when only
        # auth.nonce / idempotency_key is provided.
        req_nonce = _request_nonce(auth, links)
        if req_nonce and links and not links[-1].nonce:
            leaf = links[-1]
            links = list(links)
            links[-1] = GraphDelegationLink(
                issuer=leaf.issuer,
                audience=leaf.audience,
                capabilities=leaf.capabilities,
                expiry=leaf.expiry,
                not_before=leaf.not_before,
                cid=leaf.cid,
                proof_cid=leaf.proof_cid,
                nonce=req_nonce,
                caveats=leaf.caveats,
            )

        require_nonce = self.require_nonce_always or (
            self.require_nonce_for_mutations and ability in _MUTATING_ABILITIES
        )

        # Snapshot seen nonces (do not consume until allow).
        seen: List[str] = []
        if req_nonce and self.nonces.seen(req_nonce):
            seen.append(req_nonce)
        for link in links:
            if link.nonce and self.nonces.seen(link.nonce):
                seen.append(link.nonce)

        revoked = list(self.revocations.revoked_cids())
        # Resolve request dimensions for post-chain admission. We intentionally
        # do **not** pass partial request caveats into validate_delegation_chain
        # as child caveats (that API treats them as delegation attenuation and
        # requires every parent upper-bound to reappear). Invocation admission
        # uses caveats_allow_request against effective capabilities instead.
        try:
            request_dims = self._request_dimensions(auth, target=target, resource=resource)
        except UCANContractError as exc:
            return self._finalize_deny(
                reason=exc.reason,
                message=exc.message,
                ability=ability,
                resource_uri=resource_uri,
                principal=principal,
                request_id=rid,
                operation=operation,
                access_kind=access_kind,
                now=t,
                auth=auth,
                chain=links,
                details=exc.details,
            )

        chain_result = validate_delegation_chain(
            links,
            resource=resource,
            ability=ability,
            invoker=principal,
            require_invoker=self.require_invoker,
            now=t,
            revoked_cids=revoked,
            seen_nonces=seen,
            require_nonce=require_nonce,
            request_caveats=None,
        )

        if not chain_result.allowed:
            return self._finalize_from_chain(
                chain_result=chain_result,
                ability=ability,
                resource=resource,
                principal=principal,
                request_id=rid,
                operation=operation,
                access_kind=access_kind,
                now=t,
                auth=auth,
                chain=links,
            )

        # Request-level caveat admission against covering leaf capabilities.
        admission = self._admit_request_caveats(
            chain_result=chain_result,
            links=links,
            resource=resource,
            invoker=principal,
            now=t,
            dims=request_dims,
        )
        if admission is not None:
            return self._finalize_from_chain(
                chain_result=admission,
                ability=ability,
                resource=resource,
                principal=principal,
                request_id=rid,
                operation=operation,
                access_kind=access_kind,
                now=t,
                auth=auth,
                chain=links,
            )

        # Consume nonce only after allow (atomic check-and-set).
        if req_nonce:
            if not self.nonces.remember(req_nonce):
                replay = ChainValidationResult(
                    allowed=False,
                    reason="replay",
                    error_code="FORBIDDEN",
                    message="nonce / idempotency key already used",
                    leaf_audience=chain_result.leaf_audience,
                    root_issuer=chain_result.root_issuer,
                    details={"nonce": req_nonce},
                )
                return self._finalize_from_chain(
                    chain_result=replay,
                    ability=ability,
                    resource=resource,
                    principal=principal,
                    request_id=rid,
                    operation=operation,
                    access_kind=access_kind,
                    now=t,
                    auth=auth,
                    chain=links,
                )
        else:
            # Still remember link nonces on allow to prevent chain replay.
            for link in links:
                if link.nonce:
                    self.nonces.remember(link.nonce)

        return self._finalize_from_chain(
            chain_result=chain_result,
            ability=ability,
            resource=resource,
            principal=principal,
            request_id=rid,
            operation=operation,
            access_kind=access_kind,
            now=t,
            auth=auth,
            chain=links,
        )

    # ------------------------------------------------------------------
    # Ability / caveat helpers
    # ------------------------------------------------------------------

    def _ability_for_operation(self, operation: str) -> str:
        try:
            return ability_for_operation(operation)
        except UCANContractError:
            return _ACCESS_ABILITY_ALIASES.get(operation, "graph/admin")

    def _request_dimensions(
        self,
        auth: Optional[Mapping[str, Any]],
        *,
        target: Any,
        resource: GraphResource,
    ) -> JSONDict:
        """Collect concrete request dimensions for caveat admission."""
        dims: JSONDict = {
            "branch": resource.branch,
            "revision": resource.revision,
            "query_kind": None,
            "properties": None,
            "rows": None,
            "bytes_": None,
            "depth": None,
            "mutation_count": None,
        }
        if not auth:
            return dims
        if auth.get("query_kind"):
            dims["query_kind"] = str(auth["query_kind"])
        elif auth.get("query_kinds"):
            kinds = auth["query_kinds"]
            if isinstance(kinds, (list, tuple)) and kinds:
                dims["query_kind"] = str(kinds[0])
        cav = auth.get("caveats") or auth.get("request_caveats")
        if isinstance(cav, Mapping):
            if dims["query_kind"] is None and cav.get("query"):
                q = cav["query"]
                if isinstance(q, str):
                    dims["query_kind"] = q
                elif isinstance(q, (list, tuple)) and q:
                    dims["query_kind"] = str(q[0])
            if cav.get("property") is not None:
                props = cav["property"]
                if isinstance(props, str):
                    dims["properties"] = [props]
                elif isinstance(props, (list, tuple)):
                    dims["properties"] = [str(p) for p in props]
            for src, dest in (
                ("row", "rows"),
                ("byte", "bytes_"),
                ("depth", "depth"),
                ("count", "mutation_count"),
            ):
                if cav.get(src) is not None and dims[dest] is None:
                    dims[dest] = cav[src]
        if auth.get("rows") is not None:
            dims["rows"] = auth["rows"]
        if auth.get("bytes") is not None:
            dims["bytes_"] = auth["bytes"]
        if auth.get("depth") is not None:
            dims["depth"] = auth["depth"]
        if auth.get("mutation_count") is not None:
            dims["mutation_count"] = auth["mutation_count"]
        if auth.get("properties") is not None:
            props = auth["properties"]
            if isinstance(props, str):
                dims["properties"] = [props]
            elif isinstance(props, (list, tuple)):
                dims["properties"] = [str(p) for p in props]
        # Validate query kind vocabulary when present via caveats parser.
        if dims["query_kind"] is not None:
            caveats_from_mapping({"query": [dims["query_kind"]]})
        return dims

    def _admit_request_caveats(
        self,
        *,
        chain_result: ChainValidationResult,
        links: Sequence[GraphDelegationLink],
        resource: GraphResource,
        invoker: Optional[str],
        now: float,
        dims: Mapping[str, Any],
    ) -> Optional[ChainValidationResult]:
        """Apply grant caveats to the concrete request; return deny or None."""
        from ipfs_datasets_py.knowledge_graphs.auth.contracts import caveats_allow_request

        covering = list(chain_result.effective_capabilities)
        if not covering and links:
            covering = list(links[-1].capabilities)
        leaf = links[-1] if links else None

        def _check(caveats: GraphCaveats, label: str) -> Optional[ChainValidationResult]:
            ok, reason = caveats_allow_request(
                caveats,
                branch=dims.get("branch") or resource.branch,
                revision=dims.get("revision") or resource.revision,
                query_kind=dims.get("query_kind"),
                properties=dims.get("properties"),
                rows=dims.get("rows"),
                bytes_=dims.get("bytes_"),
                depth=dims.get("depth"),
                audience=invoker,
                mutation_count=dims.get("mutation_count"),
                now=now,
            )
            if ok:
                return None
            return ChainValidationResult(
                allowed=False,
                reason=reason or "caveat_not_attenuated",
                error_code=deny_reason_to_error_code(reason or "caveat_not_attenuated"),
                message=f"request denied by {label} caveats",
                leaf_audience=chain_result.leaf_audience,
                root_issuer=chain_result.root_issuer,
                details={"label": label, "dims": dict(dims)},
            )

        for cap in covering:
            denied = _check(cap.caveats, "capability")
            if denied is not None:
                return denied
        if leaf is not None:
            denied = _check(leaf.caveats, "link")
            if denied is not None:
                return denied
        return None

    # ------------------------------------------------------------------
    # Receipt / decision assembly
    # ------------------------------------------------------------------

    def _policy_payload(self) -> JSONDict:
        return {
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "contract_version": CONTRACT_VERSION,
            "require_invoker": self.require_invoker,
            "require_nonce_for_mutations": self.require_nonce_for_mutations,
            "metadata": dict(self.policy_metadata),
        }

    def _request_payload(
        self,
        *,
        operation: str,
        resource_uri: str,
        ability: str,
        request_id: str,
        access_kind: str,
        auth: Optional[Mapping[str, Any]],
        principal: Optional[str],
    ) -> JSONDict:
        # Redaction happens inside build_enriched_receipt / audit log.
        safe_auth: JSONDict = {}
        if auth:
            for k, v in auth.items():
                # Never copy raw token material into request digest inputs
                # under original keys — pass through so redact_for_audit can
                # mark them; digests still bind structure.
                safe_auth[str(k)] = v
        return {
            "operation": operation,
            "resource": resource_uri,
            "ability": ability,
            "request_id": request_id,
            "access_kind": access_kind,
            "principal": principal,
            "auth": safe_auth,
        }

    def _finalize_from_chain(
        self,
        *,
        chain_result: ChainValidationResult,
        ability: str,
        resource: GraphResource,
        principal: Optional[str],
        request_id: str,
        operation: str,
        access_kind: str,
        now: float,
        auth: Optional[Mapping[str, Any]],
        chain: Sequence[GraphDelegationLink],
    ) -> EnforcementResult:
        resource_uri = resource.uri
        revision = resource.revision
        if revision is None and auth:
            revision = auth.get("revision")  # type: ignore[assignment]
            if revision is not None:
                revision = str(revision)

        receipt = build_enriched_receipt(
            result=chain_result,
            resource=resource,
            ability=ability,
            principal=principal or chain_result.leaf_audience,
            policy=self._policy_payload(),
            request=self._request_payload(
                operation=operation,
                resource_uri=resource_uri,
                ability=ability,
                request_id=request_id,
                access_kind=access_kind,
                auth=auth,
                principal=principal,
            ),
            chain=chain,
            revision=revision,
            target_uri=resource_uri,
            operation=operation,
            request_id=request_id,
            now=now,
        )
        self.audit_log.record_receipt(receipt)

        decision = AuthorizationDecision(
            allowed=bool(chain_result.allowed),
            principal=principal or chain_result.leaf_audience,
            ability=ability,
            receipt_ref=receipt.receipt_ref,
            reason=chain_result.reason
            if not chain_result.allowed
            else (chain_result.message or "ok"),
            code=None
            if chain_result.allowed
            else (chain_result.error_code or deny_reason_to_error_code(chain_result.reason or "")),
        )
        return EnforcementResult(
            allowed=decision.allowed,
            decision=decision,
            receipt=receipt,
            chain_result=chain_result,
            resource_uri=resource_uri,
            ability=ability,
            principal=decision.principal,
            phase=f"before_{access_kind}",
        )

    def _finalize_deny(
        self,
        *,
        reason: str,
        message: str,
        ability: str,
        resource_uri: str,
        principal: Optional[str],
        request_id: str,
        operation: str,
        access_kind: str,
        now: float,
        auth: Optional[Mapping[str, Any]],
        chain: Optional[Sequence[GraphDelegationLink]] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> EnforcementResult:
        chain_result = ChainValidationResult(
            allowed=False,
            reason=reason,
            error_code=deny_reason_to_error_code(reason),
            message=message,
            leaf_audience=None,
            root_issuer=None,
            details=dict(details or {}),
        )
        try:
            resource = parse_graph_resource(resource_uri)
        except UCANContractError:
            # Synthetic resource for receipt binding only.
            resource = resource_uri  # type: ignore[assignment]

        revision = None
        if auth and auth.get("revision"):
            revision = str(auth["revision"])
        elif not isinstance(resource, str):
            revision = resource.revision

        receipt = build_enriched_receipt(
            result=chain_result,
            resource=resource if not isinstance(resource, str) else resource_uri,
            ability=ability,
            principal=principal,
            policy=self._policy_payload(),
            request=self._request_payload(
                operation=operation,
                resource_uri=resource_uri,
                ability=ability,
                request_id=request_id,
                access_kind=access_kind,
                auth=auth,
                principal=principal,
            ),
            chain=chain or (),
            revision=revision,
            target_uri=resource_uri,
            operation=operation,
            request_id=request_id,
            now=now,
        )
        self.audit_log.record_receipt(receipt)

        decision = AuthorizationDecision(
            allowed=False,
            principal=principal,
            ability=ability,
            receipt_ref=receipt.receipt_ref,
            reason=reason,
            code=chain_result.error_code,
        )
        return EnforcementResult(
            allowed=False,
            decision=decision,
            receipt=receipt,
            chain_result=chain_result,
            resource_uri=resource_uri,
            ability=ability,
            principal=principal,
            phase=f"before_{access_kind}",
        )


# ---------------------------------------------------------------------------
# Opt-in helpers for Python / CLI
# ---------------------------------------------------------------------------


def make_enforcement_context(
    *,
    policy_id: str = "policy:kg-ucan",
    policy_revision: str = CONTRACT_VERSION,
    revoked_cids: Optional[Iterable[str]] = None,
    require_nonce_for_mutations: bool = True,
    audit_sink: Optional[AuditEmitter] = None,
    **kwargs: Any,
) -> GraphAuthorizationService:
    """Create a shared UCAN enforcement context for Python or CLI entrypoints.

    Example::

        ctx = make_enforcement_context(policy_id="policy:cli")
        service = GraphService.open(catalog, authorizer=ctx, audit=ctx.audit_log)
    """
    return GraphAuthorizationService.create(
        policy_id=policy_id,
        policy_revision=policy_revision,
        revoked_cids=revoked_cids,
        require_nonce_for_mutations=require_nonce_for_mutations,
        audit_sink=audit_sink,
        **kwargs,
    )


def auth_context_from_chain(
    links: Sequence[Union[GraphDelegationLink, Mapping[str, Any]]],
    *,
    principal: Optional[str] = None,
    nonce: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    caveats: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> JSONDict:
    """Build a GraphService ``auth=`` mapping from a chain of links.

    Convenience for tests and CLI callers that already hold contract links.
    """
    normalized: List[Any] = []
    for item in links:
        if isinstance(item, GraphDelegationLink):
            normalized.append(item)
        elif isinstance(item, Mapping):
            normalized.append(item)
        else:
            normalized.append(link_from_delegation_token(item))
    ctx: JSONDict = {"chain": normalized}
    if principal is not None:
        ctx["principal"] = principal
    elif normalized:
        leaf = normalized[-1]
        if isinstance(leaf, GraphDelegationLink):
            ctx["principal"] = leaf.audience
        elif isinstance(leaf, Mapping) and leaf.get("audience"):
            ctx["principal"] = leaf["audience"]
    if nonce is not None:
        ctx["nonce"] = nonce
    if idempotency_key is not None:
        ctx["idempotency_key"] = idempotency_key
    if caveats is not None:
        ctx["caveats"] = dict(caveats)
    if extra:
        for k, v in extra.items():
            ctx.setdefault(k, v)
    return ctx


__all__ = [
    "GraphAuthorizationService",
    "EnforcementResult",
    "RevocationStore",
    "InMemoryRevocationStore",
    "NonceStore",
    "InMemoryNonceStore",
    "target_to_resource",
    "parse_delegation_chain",
    "make_enforcement_context",
    "auth_context_from_chain",
]
