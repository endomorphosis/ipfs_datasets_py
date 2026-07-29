"""Graph UCAN resource, ability, and caveat contracts (KGP-021).

This module is the normative, transport-neutral vocabulary for knowledge-graph
authorization under MCP++ / UCAN. It does **not** invent a token wire format:
tokens remain the existing MCP++ Profile C shapes
(``ipfs_datasets_py.mcp_server.ucan_delegation``) or wallet grants. Enforcement
in ``GraphService`` (KGP-022) consumes these pure rules.

Contract version: ``kg-ucan-contract/v1``

Canonical URI grammar (same as GraphTarget / service contract)::

    kg://<tenant>/<graph_id>
    kg://<tenant>/<graph_id>/branches/<branch>
    kg://<tenant>/<graph_id>/revisions/<revision>

Abilities (closed set)::

    graph/list | graph/read | graph/query | graph/write
    graph/admin | graph/pin | graph/delegate

Caveats (closed set of keys)::

    branch | revision | query | property | row | byte | depth
    time | audience | count

Every delegation link must satisfy **resource containment**, **ability
attenuation**, and **monotonic caveat attenuation**. Issuance, audience,
expiry, revocation, and replay rules fail closed. Allow and deny outcomes map
to service typed errors and emit redacted audit receipts.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Schema / closed vocabularies
# ---------------------------------------------------------------------------

CONTRACT_VERSION: Final = "kg-ucan-contract/v1"
RESOURCE_SCHEME: Final = "kg://"
IDENTITY_DOMAIN: Final = "kg.ucan"

# Closed ability set (plan § MCP++ and UCAN; service ``_OP_ABILITIES``).
GRAPH_ABILITIES: Final = frozenset(
    {
        "graph/list",
        "graph/read",
        "graph/query",
        "graph/write",
        "graph/admin",
        "graph/pin",
        "graph/delegate",
    }
)

# Operation → required ability (default authorizer vocabulary).
OPERATION_ABILITIES: Final = MappingProxyType(
    {
        "create": "graph/admin",
        "list": "graph/list",
        "describe": "graph/read",
        "open": "graph/read",
        "branch": "graph/admin",
        "delete": "graph/admin",
        "write": "graph/write",
        "query": "graph/query",
        "begin_tx": "graph/write",
        "commit_tx": "graph/write",
        "rollback_tx": "graph/write",
        "pin": "graph/pin",
        "unpin": "graph/pin",
        "delegate": "graph/delegate",
    }
)

# Ability attenuation lattice: parent may grant any ability in its downward set.
# Keys are parent abilities; values are abilities a child may hold under them.
# Every ability always includes itself.
_ABILITY_DOWNWARD: Final = MappingProxyType(
    {
        "graph/admin": frozenset(GRAPH_ABILITIES),
        "graph/write": frozenset(
            {"graph/write", "graph/read", "graph/query", "graph/list"}
        ),
        "graph/read": frozenset({"graph/read", "graph/list"}),
        "graph/query": frozenset({"graph/query"}),
        "graph/list": frozenset({"graph/list"}),
        "graph/pin": frozenset({"graph/pin"}),
        "graph/delegate": frozenset({"graph/delegate"}),
    }
)

# Closed caveat keys (acceptance + plan).
CAVEAT_KEYS: Final = frozenset(
    {
        "branch",
        "revision",
        "query",
        "property",
        "row",
        "byte",
        "depth",
        "time",
        "audience",
        "count",
    }
)

# Set-valued caveats: child values must be a subset of parent values.
_SET_CAVEAT_KEYS: Final = frozenset(
    {"branch", "revision", "query", "property", "audience"}
)

# Upper-bound numeric caveats: child ≤ parent (smaller is stricter).
_UPPER_BOUND_CAVEAT_KEYS: Final = frozenset({"row", "byte", "depth", "count"})

# time caveat nested fields (or flat aliases accepted when parsing).
_TIME_EXPIRY_ALIASES: Final = frozenset({"expiry", "exp", "expires_at", "not_after"})
_TIME_NBF_ALIASES: Final = frozenset({"not_before", "nbf", "valid_after"})
_TIME_TTL_ALIASES: Final = frozenset({"max_ttl_seconds", "ttl", "max_ttl"})

# Query kinds allowed by the ``query`` caveat when present.
QUERY_KINDS: Final = frozenset(
    {
        "cypher",
        "sparql",
        "graphql",
        "hybrid",
        "traversal",
        "vector",
        "fulltext",
        "describe",
        "list",
    }
)

# Deny/allow reason codes (machine-stable; map into TypedError via ERROR_CODE_MAP).
DENY_REASONS: Final = frozenset(
    {
        "missing_token",
        "missing_principal",
        "invalid_resource",
        "invalid_ability",
        "invalid_caveat",
        "resource_not_contained",
        "ability_not_attenuated",
        "caveat_not_attenuated",
        "chain_broken",
        "issuer_mismatch",
        "audience_mismatch",
        "not_yet_valid",
        "expired",
        "revoked",
        "replay",
        "nonce_required",
        "capability_missing",
        "empty_chain",
        "unknown_ability",
        "unknown_caveat_key",
    }
)

# Map deny reasons → service TypedError codes (kg-service-contract/v1).
ERROR_CODE_MAP: Final = MappingProxyType(
    {
        "missing_token": "UNAUTHORIZED",
        "missing_principal": "UNAUTHORIZED",
        "invalid_resource": "INVALID_REQUEST",
        "invalid_ability": "INVALID_REQUEST",
        "invalid_caveat": "INVALID_REQUEST",
        "resource_not_contained": "FORBIDDEN",
        "ability_not_attenuated": "FORBIDDEN",
        "caveat_not_attenuated": "FORBIDDEN",
        "chain_broken": "FORBIDDEN",
        "issuer_mismatch": "FORBIDDEN",
        "audience_mismatch": "FORBIDDEN",
        "not_yet_valid": "FORBIDDEN",
        "expired": "FORBIDDEN",
        "revoked": "FORBIDDEN",
        "replay": "FORBIDDEN",
        "nonce_required": "INVALID_REQUEST",
        "capability_missing": "FORBIDDEN",
        "empty_chain": "UNAUTHORIZED",
        "unknown_ability": "INVALID_REQUEST",
        "unknown_caveat_key": "INVALID_REQUEST",
    }
)

# Audit fields that must never appear in receipts (redaction denylist prefixes).
AUDIT_REDACT_KEYS: Final = frozenset(
    {
        "token",
        "ucan",
        "jwt",
        "signature",
        "private_key",
        "secret",
        "password",
        "raw_query",
        "query_text",
        "properties",
        "property_values",
        "rows",
        "payload",
        "authorization",
        "bearer",
    }
)

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_DID_RE = re.compile(r"^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$")

_URI_BRANCH = re.compile(
    r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)/branches/(?P<branch>[^/]+)$"
)
_URI_REV = re.compile(
    r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)/revisions/(?P<revision>[^/]+)$"
)
_URI_BASE = re.compile(r"^kg://(?P<tenant>[^/]+)/(?P<graph_id>[^/]+)$")
_URI_TENANT = re.compile(r"^kg://(?P<tenant>[^/]+)/?$")
_URI_WILDCARD_GRAPH = re.compile(r"^kg://(?P<tenant>[^/]+)/\*$")

JSONDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UCANContractError(ValueError):
    """Contract validation failure with a stable ``reason`` code."""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.details: JSONDict = dict(details or {})

    @property
    def error_code(self) -> str:
        """Service TypedError code for this reason."""
        return ERROR_CODE_MAP.get(self.reason, "FORBIDDEN")

    def to_json_dict(self) -> JSONDict:
        return {
            "reason": self.reason,
            "message": self.message,
            "error_code": self.error_code,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Resource model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphResource:
    """Canonical UCAN resource address for a knowledge graph target.

    Forms
    -----
    - tenant scope: ``kg://{tenant}`` or ``kg://{tenant}/*`` (all graphs)
    - graph base: ``kg://{tenant}/{graph_id}``
    - branch pin: ``kg://{tenant}/{graph_id}/branches/{branch}``
    - revision pin: ``kg://{tenant}/{graph_id}/revisions/{revision}``
    """

    tenant: str
    graph_id: Optional[str] = None
    branch: Optional[str] = None
    revision: Optional[str] = None
    wildcard_graph: bool = False

    def __post_init__(self) -> None:
        _validate_slug(self.tenant, field="tenant")
        if self.wildcard_graph:
            if self.graph_id is not None or self.branch is not None or self.revision is not None:
                raise UCANContractError(
                    "invalid_resource",
                    "wildcard tenant resource cannot name graph/branch/revision",
                )
            return
        if self.graph_id is None:
            if self.branch is not None or self.revision is not None:
                raise UCANContractError(
                    "invalid_resource",
                    "branch/revision require graph_id",
                )
            return
        _validate_slug(self.graph_id, field="graph_id")
        if self.branch is not None and self.revision is not None:
            raise UCANContractError(
                "invalid_resource",
                "branch and revision are mutually exclusive",
                details={"branch": self.branch, "revision": self.revision},
            )
        if self.branch is not None:
            _validate_slug(self.branch, field="branch")
        if self.revision is not None:
            if not isinstance(self.revision, str) or not _REVISION_RE.fullmatch(self.revision):
                raise UCANContractError(
                    "invalid_resource",
                    "revision failed id validation",
                    details={"revision": self.revision},
                )

    @property
    def uri(self) -> str:
        return resource_to_uri(self)

    def to_json_dict(self) -> JSONDict:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "revision": self.revision,
            "wildcard_graph": self.wildcard_graph,
            "uri": self.uri,
        }

    @classmethod
    def from_uri(cls, uri: str) -> "GraphResource":
        return parse_graph_resource(uri)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GraphResource":
        if not isinstance(data, Mapping):
            raise UCANContractError("invalid_resource", "resource must be a mapping")
        if "uri" in data and data["uri"] is not None and data.get("tenant") is None:
            return parse_graph_resource(str(data["uri"]))
        return cls(
            tenant=str(data["tenant"]),
            graph_id=data.get("graph_id"),
            branch=data.get("branch"),
            revision=data.get("revision"),
            wildcard_graph=bool(data.get("wildcard_graph", False)),
        )


def _validate_slug(value: Any, *, field: str) -> str:
    if value is None or not isinstance(value, str) or not value:
        raise UCANContractError(
            "invalid_resource",
            f"{field} must be a non-empty string",
            details={"field": field},
        )
    if value != value.strip():
        raise UCANContractError(
            "invalid_resource",
            f"{field} must not have surrounding whitespace",
            details={"field": field, "value": value},
        )
    if not _SLUG_RE.fullmatch(value):
        raise UCANContractError(
            "invalid_resource",
            f"{field} failed slug validation",
            details={"field": field, "value": value},
        )
    return value


def parse_graph_resource(uri: str) -> GraphResource:
    """Parse a ``kg://`` resource URI into :class:`GraphResource`."""
    if not isinstance(uri, str) or not uri:
        raise UCANContractError("invalid_resource", "uri must be a non-empty string")
    if not uri.startswith(RESOURCE_SCHEME):
        raise UCANContractError(
            "invalid_resource",
            f"uri must use {RESOURCE_SCHEME} scheme",
            details={"uri": uri},
        )

    m = _URI_WILDCARD_GRAPH.fullmatch(uri)
    if m:
        return GraphResource(tenant=m.group("tenant"), wildcard_graph=True)

    # Tenant-only: kg://tenant or kg://tenant/
    m = _URI_TENANT.fullmatch(uri)
    if m:
        return GraphResource(tenant=m.group("tenant"))

    m = _URI_BRANCH.fullmatch(uri)
    if m:
        return GraphResource(
            tenant=m.group("tenant"),
            graph_id=m.group("graph_id"),
            branch=m.group("branch"),
        )
    m = _URI_REV.fullmatch(uri)
    if m:
        return GraphResource(
            tenant=m.group("tenant"),
            graph_id=m.group("graph_id"),
            revision=m.group("revision"),
        )
    m = _URI_BASE.fullmatch(uri)
    if m:
        return GraphResource(
            tenant=m.group("tenant"),
            graph_id=m.group("graph_id"),
        )
    raise UCANContractError(
        "invalid_resource",
        f"uri does not match kg:// grammar: {uri!r}",
        details={"uri": uri},
    )


def resource_to_uri(resource: GraphResource) -> str:
    """Serialize :class:`GraphResource` to its canonical URI."""
    if resource.wildcard_graph or resource.graph_id is None:
        if resource.wildcard_graph:
            return f"kg://{resource.tenant}/*"
        return f"kg://{resource.tenant}"
    base = f"kg://{resource.tenant}/{resource.graph_id}"
    if resource.branch is not None:
        return f"{base}/branches/{resource.branch}"
    if resource.revision is not None:
        return f"{base}/revisions/{resource.revision}"
    return base


def resource_contains(parent: Union[GraphResource, str], child: Union[GraphResource, str]) -> bool:
    """Return True if *parent* resource authority covers *child*.

    Rules (path containment, never cross-tenant):

    1. Equal URIs always contain.
    2. Tenant scope (``kg://t`` or ``kg://t/*``) covers every resource under
       tenant ``t``.
    3. Graph base ``kg://t/g`` covers its branch and revision specializations.
    4. A branch resource covers only that exact branch (not other branches,
       not revisions, not the bare graph for write-wide authority beyond the
       pin — the pin is a *narrowing*).
    5. A revision resource covers only that exact revision.
    6. Different tenants never contain each other.
    """
    p = parent if isinstance(parent, GraphResource) else parse_graph_resource(parent)
    c = child if isinstance(child, GraphResource) else parse_graph_resource(child)

    if p.tenant != c.tenant:
        return False

    # Tenant-wide authority.
    if p.graph_id is None or p.wildcard_graph:
        return True

    if c.graph_id is None or c.wildcard_graph:
        # Child is broader than parent → not contained.
        return False

    if p.graph_id != c.graph_id:
        return False

    # Parent is bare graph → covers any specialization of that graph.
    if p.branch is None and p.revision is None:
        return True

    # Parent is branch-pinned.
    if p.branch is not None:
        return c.branch == p.branch and c.revision is None

    # Parent is revision-pinned.
    if p.revision is not None:
        return c.revision == p.revision and c.branch is None

    return False


def assert_resource_contained(
    parent: Union[GraphResource, str],
    child: Union[GraphResource, str],
) -> None:
    """Raise :class:`UCANContractError` unless *parent* contains *child*."""
    if not resource_contains(parent, child):
        p_uri = parent if isinstance(parent, str) else parent.uri
        c_uri = child if isinstance(child, str) else child.uri
        raise UCANContractError(
            "resource_not_contained",
            f"resource {c_uri!r} is not contained in {p_uri!r}",
            details={"parent": p_uri, "child": c_uri},
        )


# ---------------------------------------------------------------------------
# Abilities
# ---------------------------------------------------------------------------


def normalize_ability(ability: str) -> str:
    """Validate and return a canonical graph ability string."""
    if not isinstance(ability, str) or not ability:
        raise UCANContractError("invalid_ability", "ability must be a non-empty string")
    if ability not in GRAPH_ABILITIES:
        raise UCANContractError(
            "unknown_ability",
            f"ability {ability!r} is not in the closed graph ability set",
            details={"ability": ability, "allowed": sorted(GRAPH_ABILITIES)},
        )
    return ability


def ability_for_operation(operation: str) -> str:
    """Map a GraphService operation name to its required UCAN ability."""
    if not isinstance(operation, str) or not operation:
        raise UCANContractError("invalid_ability", "operation must be a non-empty string")
    ability = OPERATION_ABILITIES.get(operation)
    if ability is None:
        raise UCANContractError(
            "unknown_ability",
            f"no ability mapping for operation {operation!r}",
            details={"operation": operation},
        )
    return ability


def ability_contains(parent: str, child: str) -> bool:
    """Return True if *parent* ability may be attenuated to *child*."""
    p = normalize_ability(parent)
    c = normalize_ability(child)
    downward = _ABILITY_DOWNWARD.get(p, frozenset({p}))
    return c in downward


def assert_ability_attenuated(parent: str, child: str) -> None:
    """Raise unless *child* is a monotonic attenuation of *parent*."""
    if not ability_contains(parent, child):
        raise UCANContractError(
            "ability_not_attenuated",
            f"ability {child!r} is not an attenuation of {parent!r}",
            details={"parent": parent, "child": child},
        )


def abilities_cover(granted: Iterable[str], required: str) -> bool:
    """Return True if any ability in *granted* covers *required*."""
    req = normalize_ability(required)
    for raw in granted:
        try:
            if ability_contains(str(raw), req):
                return True
        except UCANContractError:
            continue
    return False


# ---------------------------------------------------------------------------
# Caveats
# ---------------------------------------------------------------------------


def _as_string_set(value: Any, *, key: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, (list, tuple, set, frozenset)):
        out: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item:
                raise UCANContractError(
                    "invalid_caveat",
                    f"caveat {key!r} entries must be non-empty strings",
                    details={"key": key, "value": value},
                )
            out.add(item)
        return frozenset(out)
    raise UCANContractError(
        "invalid_caveat",
        f"caveat {key!r} must be a string or list of strings",
        details={"key": key, "value": value},
    )


def _as_non_negative_int(value: Any, *, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UCANContractError(
            "invalid_caveat",
            f"caveat {key!r} must be a non-negative integer",
            details={"key": key, "value": value},
        )
    if isinstance(value, float) and not value.is_integer():
        raise UCANContractError(
            "invalid_caveat",
            f"caveat {key!r} must be an integer",
            details={"key": key, "value": value},
        )
    iv = int(value)
    if iv < 0:
        raise UCANContractError(
            "invalid_caveat",
            f"caveat {key!r} must be non-negative",
            details={"key": key, "value": value},
        )
    return iv


def _parse_time_caveat(value: Any) -> MappingProxyType:
    """Normalize a ``time`` caveat to ``{expiry?, not_before?, max_ttl_seconds?}``."""
    if value is None:
        return MappingProxyType({})
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return MappingProxyType({"expiry": float(value)})
    if isinstance(value, str):
        # ISO-8601 or numeric string → treat as expiry.
        try:
            return MappingProxyType({"expiry": float(value)})
        except ValueError:
            return MappingProxyType({"expiry": value})
    if not isinstance(value, Mapping):
        raise UCANContractError(
            "invalid_caveat",
            "time caveat must be a number, string, or object",
            details={"value": value},
        )
    out: JSONDict = {}
    for k, v in value.items():
        key = str(k)
        if key in _TIME_EXPIRY_ALIASES or key == "expiry":
            out["expiry"] = v
        elif key in _TIME_NBF_ALIASES or key == "not_before":
            out["not_before"] = v
        elif key in _TIME_TTL_ALIASES or key == "max_ttl_seconds":
            out["max_ttl_seconds"] = _as_non_negative_int(v, key="time.max_ttl_seconds")
        else:
            raise UCANContractError(
                "invalid_caveat",
                f"unknown time caveat field {key!r}",
                details={"key": key},
            )
    return MappingProxyType(out)


def _time_to_epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            pass
        # ISO-8601
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        from datetime import datetime

        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise UCANContractError(
                "invalid_caveat",
                f"unparseable time value {value!r}",
                details={"value": value},
            ) from exc
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    raise UCANContractError(
        "invalid_caveat",
        f"unsupported time type {type(value)!r}",
        details={"value": value},
    )


@dataclass(frozen=True, slots=True)
class GraphCaveats:
    """Normalized, closed-key caveat bag for graph UCAN capabilities.

    Semantics
    ---------
    - **branch / revision / query / property / audience**: allow-lists. Absence
      means unrestricted on that dimension; presence restricts to the set.
    - **row / byte / depth / count**: inclusive upper bounds. Absence means no
      extra UCAN cap (service budgets may still apply).
    - **time**: optional ``expiry`` (unix or ISO), ``not_before``, and
      ``max_ttl_seconds`` for further delegation.
    """

    branch: Optional[frozenset[str]] = None
    revision: Optional[frozenset[str]] = None
    query: Optional[frozenset[str]] = None
    property: Optional[frozenset[str]] = None
    row: Optional[int] = None
    byte: Optional[int] = None
    depth: Optional[int] = None
    time: Optional[Mapping[str, Any]] = None
    audience: Optional[frozenset[str]] = None
    count: Optional[int] = None

    def to_json_dict(self) -> JSONDict:
        out: JSONDict = {}
        if self.branch is not None:
            out["branch"] = sorted(self.branch)
        if self.revision is not None:
            out["revision"] = sorted(self.revision)
        if self.query is not None:
            out["query"] = sorted(self.query)
        if self.property is not None:
            out["property"] = sorted(self.property)
        if self.row is not None:
            out["row"] = self.row
        if self.byte is not None:
            out["byte"] = self.byte
        if self.depth is not None:
            out["depth"] = self.depth
        if self.time is not None:
            out["time"] = dict(self.time)
        if self.audience is not None:
            out["audience"] = sorted(self.audience)
        if self.count is not None:
            out["count"] = self.count
        return out

    def is_empty(self) -> bool:
        return not self.to_json_dict()

    @classmethod
    def empty(cls) -> "GraphCaveats":
        return cls()

    @classmethod
    def from_mapping(cls, data: Optional[Mapping[str, Any]]) -> "GraphCaveats":
        if data is None:
            return cls.empty()
        if not isinstance(data, Mapping):
            raise UCANContractError("invalid_caveat", "caveats must be a mapping")
        unknown = set(data.keys()) - CAVEAT_KEYS
        # Allow flat time aliases at top level for ergonomics; fold into time.
        flat_time: JSONDict = {}
        known: JSONDict = {}
        for key, value in data.items():
            if key in CAVEAT_KEYS:
                known[key] = value
            elif key in _TIME_EXPIRY_ALIASES | _TIME_NBF_ALIASES | _TIME_TTL_ALIASES:
                flat_time[key] = value
            else:
                raise UCANContractError(
                    "unknown_caveat_key",
                    f"unknown caveat key {key!r}",
                    details={"key": key, "allowed": sorted(CAVEAT_KEYS)},
                )
        if flat_time:
            merged_time = dict(known.get("time") or {})
            if isinstance(known.get("time"), (int, float, str)):
                merged_time = {"expiry": known["time"]}
            merged_time.update(flat_time)
            known["time"] = merged_time

        kwargs: JSONDict = {}
        for key in _SET_CAVEAT_KEYS:
            if key in known and known[key] is not None:
                s = _as_string_set(known[key], key=key)
                if key == "query":
                    bad = s - QUERY_KINDS
                    if bad:
                        raise UCANContractError(
                            "invalid_caveat",
                            f"unknown query kind(s): {sorted(bad)}",
                            details={"bad": sorted(bad), "allowed": sorted(QUERY_KINDS)},
                        )
                if key == "audience":
                    for did in s:
                        if not _DID_RE.fullmatch(did) and not did.startswith("did:"):
                            # Soft: require did: prefix for audience entries.
                            if ":" not in did:
                                raise UCANContractError(
                                    "invalid_caveat",
                                    f"audience entry must be a DID-like principal: {did!r}",
                                    details={"did": did},
                                )
                kwargs[key] = s
        for key in _UPPER_BOUND_CAVEAT_KEYS:
            if key in known and known[key] is not None:
                kwargs[key] = _as_non_negative_int(known[key], key=key)
        if "time" in known and known["time"] is not None:
            kwargs["time"] = dict(_parse_time_caveat(known["time"]))
        return cls(**kwargs)


def caveats_from_mapping(data: Optional[Mapping[str, Any]]) -> GraphCaveats:
    """Public alias for :meth:`GraphCaveats.from_mapping`."""
    return GraphCaveats.from_mapping(data)


def caveat_contains(parent: GraphCaveats, child: GraphCaveats) -> bool:
    """Return True if *child* is a monotonic attenuation of *parent*.

    Monotonicity
    ------------
    - Unrestricted parent dimension may be restricted by the child.
    - Restricted parent dimension **must** reappear on the child with a
      subset (sets) or ≤ bound (upper bounds).
    - ``time.expiry``: child expiry must be ≤ parent expiry (earlier).
    - ``time.not_before``: child nbf must be ≥ parent nbf (later).
    - ``time.max_ttl_seconds``: child ≤ parent.
    """
    # Set caveats
    for key in _SET_CAVEAT_KEYS:
        p_set = getattr(parent, key)
        c_set = getattr(child, key)
        if p_set is None:
            continue
        if c_set is None:
            return False
        if not c_set.issubset(p_set):
            return False

    # Upper bounds
    for key in _UPPER_BOUND_CAVEAT_KEYS:
        p_val = getattr(parent, key)
        c_val = getattr(child, key)
        if p_val is None:
            continue
        if c_val is None:
            return False
        if c_val > p_val:
            return False

    # Time
    p_time = parent.time or {}
    c_time = child.time or {}
    if p_time:
        if not c_time and p_time:
            # Child must preserve time restrictions.
            return False
        if "expiry" in p_time:
            if "expiry" not in c_time:
                return False
            try:
                if _time_to_epoch(c_time["expiry"]) > _time_to_epoch(p_time["expiry"]):  # type: ignore[operator]
                    return False
            except UCANContractError:
                return False
        if "not_before" in p_time:
            if "not_before" not in c_time:
                return False
            try:
                if _time_to_epoch(c_time["not_before"]) < _time_to_epoch(p_time["not_before"]):  # type: ignore[operator]
                    return False
            except UCANContractError:
                return False
        if "max_ttl_seconds" in p_time:
            if "max_ttl_seconds" not in c_time:
                return False
            if int(c_time["max_ttl_seconds"]) > int(p_time["max_ttl_seconds"]):
                return False

    return True


def assert_caveats_attenuated(parent: GraphCaveats, child: GraphCaveats) -> None:
    """Raise unless *child* monotonically attenuates *parent*."""
    if not caveat_contains(parent, child):
        raise UCANContractError(
            "caveat_not_attenuated",
            "child caveats are not a monotonic attenuation of parent caveats",
            details={
                "parent": parent.to_json_dict(),
                "child": child.to_json_dict(),
            },
        )


def caveats_allow_request(
    caveats: GraphCaveats,
    *,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    query_kind: Optional[str] = None,
    properties: Optional[Iterable[str]] = None,
    rows: Optional[int] = None,
    bytes_: Optional[int] = None,
    depth: Optional[int] = None,
    audience: Optional[str] = None,
    mutation_count: Optional[int] = None,
    now: Optional[float] = None,
) -> Tuple[bool, Optional[str]]:
    """Check whether a concrete request satisfies *caveats*.

    Returns ``(True, None)`` on allow, or ``(False, reason)`` on deny.
    """
    t = now if now is not None else time.time()

    # Only dimensions supplied by the caller are checked. Enforcement must pass
    # query_kind / rows / etc. when those are known for the operation so grants
    # cannot be bypassed by omission. Ambient constraints (audience, time)
    # always apply when present on the grant.
    if caveats.branch is not None and branch is not None:
        if branch not in caveats.branch:
            return False, "caveat_not_attenuated"
    if caveats.revision is not None and revision is not None:
        if revision not in caveats.revision:
            return False, "caveat_not_attenuated"
    if caveats.query is not None and query_kind is not None:
        if query_kind not in caveats.query:
            return False, "caveat_not_attenuated"
    if caveats.property is not None and properties is not None:
        props = frozenset(properties)
        if not props.issubset(caveats.property):
            return False, "caveat_not_attenuated"
    if caveats.row is not None and rows is not None and rows > caveats.row:
        return False, "caveat_not_attenuated"
    if caveats.byte is not None and bytes_ is not None and bytes_ > caveats.byte:
        return False, "caveat_not_attenuated"
    if caveats.depth is not None and depth is not None and depth > caveats.depth:
        return False, "caveat_not_attenuated"
    if caveats.count is not None and mutation_count is not None and mutation_count > caveats.count:
        return False, "caveat_not_attenuated"
    if caveats.audience is not None:
        if audience is None or audience not in caveats.audience:
            return False, "audience_mismatch"

    if caveats.time:
        nbf = caveats.time.get("not_before")
        if nbf is not None:
            try:
                if t < float(_time_to_epoch(nbf)):  # type: ignore[arg-type]
                    return False, "not_yet_valid"
            except (TypeError, UCANContractError):
                return False, "invalid_caveat"
        exp = caveats.time.get("expiry")
        if exp is not None:
            try:
                if t > float(_time_to_epoch(exp)):  # type: ignore[arg-type]
                    return False, "expired"
            except (TypeError, UCANContractError):
                return False, "invalid_caveat"

    return True, None


# ---------------------------------------------------------------------------
# Capability + chain contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphCapability:
    """Single graph capability: resource + ability + caveats."""

    resource: GraphResource
    ability: str
    caveats: GraphCaveats = field(default_factory=GraphCaveats.empty)

    def __post_init__(self) -> None:
        normalize_ability(self.ability)

    @property
    def resource_uri(self) -> str:
        return self.resource.uri

    def to_json_dict(self) -> JSONDict:
        return {
            "resource": self.resource.uri,
            "ability": self.ability,
            "caveats": self.caveats.to_json_dict(),
        }

    def covers(
        self,
        resource: Union[GraphResource, str],
        ability: str,
        request_caveats: Optional[GraphCaveats] = None,
    ) -> bool:
        """Return True if this capability covers the requested resource/ability."""
        if not resource_contains(self.resource, resource):
            return False
        if not ability_contains(self.ability, ability):
            return False
        if request_caveats is not None and not caveat_contains(self.caveats, request_caveats):
            # Request may add restrictions only if they still satisfy grant.
            # For invocation: grant caveats must allow the request dimensions
            # (checked separately via caveats_allow_request). Here we only
            # require that any *delegated* request caveats attenuate the grant.
            return False
        return True

    def attenuates_to(self, child: "GraphCapability") -> bool:
        """Return True if *child* is a valid attenuation of this capability."""
        if not resource_contains(self.resource, child.resource):
            return False
        if not ability_contains(self.ability, child.ability):
            return False
        if not caveat_contains(self.caveats, child.caveats):
            return False
        return True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GraphCapability":
        if not isinstance(data, Mapping):
            raise UCANContractError("invalid_resource", "capability must be a mapping")
        res_raw = data.get("resource")
        if isinstance(res_raw, Mapping):
            resource = GraphResource.from_mapping(res_raw)
        elif isinstance(res_raw, str):
            resource = parse_graph_resource(res_raw)
        else:
            raise UCANContractError("invalid_resource", "capability.resource required")
        ability = normalize_ability(str(data.get("ability", "")))
        caveats = GraphCaveats.from_mapping(data.get("caveats"))
        return cls(resource=resource, ability=ability, caveats=caveats)


def capability_contains(parent: GraphCapability, child: GraphCapability) -> bool:
    """Return True if *parent* may be attenuated to *child*."""
    return parent.attenuates_to(child)


def assert_capability_attenuated(parent: GraphCapability, child: GraphCapability) -> None:
    """Raise unless *child* is a full attenuation of *parent*."""
    try:
        assert_resource_contained(parent.resource, child.resource)
    except UCANContractError:
        raise
    assert_ability_attenuated(parent.ability, child.ability)
    assert_caveats_attenuated(parent.caveats, child.caveats)


@dataclass(frozen=True, slots=True)
class GraphDelegationLink:
    """One link in a graph UCAN delegation chain (root → … → leaf).

    This is a **contract view** of a Profile C token, not a new wire format.
    Use :func:`link_from_delegation_token` to adapt existing tokens.
    """

    issuer: str
    audience: str
    capabilities: Tuple[GraphCapability, ...]
    expiry: Optional[float] = None
    not_before: Optional[float] = None
    cid: Optional[str] = None
    proof_cid: Optional[str] = None
    nonce: Optional[str] = None
    caveats: GraphCaveats = field(default_factory=GraphCaveats.empty)

    def __post_init__(self) -> None:
        if not self.issuer or not isinstance(self.issuer, str):
            raise UCANContractError("invalid_resource", "issuer must be a non-empty string")
        if not self.audience or not isinstance(self.audience, str):
            raise UCANContractError("invalid_resource", "audience must be a non-empty string")
        if not self.capabilities:
            raise UCANContractError(
                "capability_missing",
                "delegation link must grant at least one capability",
            )

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Return True only when past ``expiry`` (not_before is separate)."""
        if self.expiry is None:
            return False
        t = now if now is not None else time.time()
        return t > self.expiry

    def is_active(self, now: Optional[float] = None) -> Tuple[bool, Optional[str]]:
        t = now if now is not None else time.time()
        if self.not_before is not None and t < self.not_before:
            return False, "not_yet_valid"
        if self.expiry is not None and t > self.expiry:
            return False, "expired"
        return True, None

    def covers(self, resource: Union[GraphResource, str], ability: str) -> bool:
        return any(cap.covers(resource, ability) for cap in self.capabilities)

    def to_json_dict(self) -> JSONDict:
        return {
            "issuer": self.issuer,
            "audience": self.audience,
            "capabilities": [c.to_json_dict() for c in self.capabilities],
            "expiry": self.expiry,
            "not_before": self.not_before,
            "cid": self.cid,
            "proof_cid": self.proof_cid,
            "nonce": self.nonce,
            "caveats": self.caveats.to_json_dict(),
        }


def _cap_from_token_capability(cap: Any, link_caveats: GraphCaveats) -> GraphCapability:
    """Adapt a Profile C ``Capability`` (resource/ability) to GraphCapability."""
    if isinstance(cap, GraphCapability):
        return cap
    if isinstance(cap, Mapping):
        data = dict(cap)
        if "caveats" not in data:
            data["caveats"] = link_caveats.to_json_dict()
        return GraphCapability.from_mapping(data)
    resource = getattr(cap, "resource", None)
    ability = getattr(cap, "ability", None)
    if resource is None or ability is None:
        raise UCANContractError(
            "capability_missing",
            "token capability missing resource/ability",
        )
    # Profile C capabilities do not carry graph caveats; link-level caveats apply.
    extra = getattr(cap, "caveats", None)
    caveats = (
        GraphCaveats.from_mapping(extra)
        if isinstance(extra, Mapping)
        else link_caveats
    )
    return GraphCapability(
        resource=parse_graph_resource(str(resource)),
        ability=normalize_ability(str(ability)),
        caveats=caveats,
    )


def link_from_delegation_token(
    token: Any,
    *,
    caveats: Optional[Mapping[str, Any]] = None,
) -> GraphDelegationLink:
    """Adapter: Profile C ``Delegation`` / ``DelegationToken`` → contract link.

    Does not invent a token format; only reads existing fields.
    """
    issuer = str(getattr(token, "issuer", "") or "")
    audience = str(getattr(token, "audience", "") or "")
    caps_raw = list(getattr(token, "capabilities", None) or [])
    link_caveats = GraphCaveats.from_mapping(
        caveats if caveats is not None else getattr(token, "caveats", None)
    )
    capabilities = tuple(_cap_from_token_capability(c, link_caveats) for c in caps_raw)
    expiry = getattr(token, "expiry", None)
    not_before = getattr(token, "not_before", None)
    if expiry is not None:
        expiry = float(expiry)
    if not_before is not None:
        not_before = float(not_before)
    return GraphDelegationLink(
        issuer=issuer,
        audience=audience,
        capabilities=capabilities,
        expiry=expiry,
        not_before=not_before,
        cid=getattr(token, "cid", None),
        proof_cid=getattr(token, "proof_cid", None),
        nonce=getattr(token, "nonce", None),
        caveats=link_caveats,
    )


def link_to_profile_c_capability_dicts(link: GraphDelegationLink) -> list[JSONDict]:
    """Export capabilities in Profile C ``{resource, ability}`` shape."""
    return [
        {"resource": cap.resource_uri, "ability": cap.ability}
        for cap in link.capabilities
    ]


@dataclass(frozen=True, slots=True)
class ChainValidationResult:
    """Outcome of validating a full attenuated delegation chain."""

    allowed: bool
    reason: Optional[str] = None
    error_code: Optional[str] = None
    message: str = ""
    leaf_audience: Optional[str] = None
    root_issuer: Optional[str] = None
    effective_capabilities: Tuple[GraphCapability, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> JSONDict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "error_code": self.error_code,
            "message": self.message,
            "leaf_audience": self.leaf_audience,
            "root_issuer": self.root_issuer,
            "effective_capabilities": [c.to_json_dict() for c in self.effective_capabilities],
            "details": dict(self.details),
        }


def _deny(
    reason: str,
    message: str,
    *,
    details: Optional[Mapping[str, Any]] = None,
    leaf_audience: Optional[str] = None,
    root_issuer: Optional[str] = None,
) -> ChainValidationResult:
    return ChainValidationResult(
        allowed=False,
        reason=reason,
        error_code=ERROR_CODE_MAP.get(reason, "FORBIDDEN"),
        message=message,
        leaf_audience=leaf_audience,
        root_issuer=root_issuer,
        details=dict(details or {}),
    )


def validate_chain_issuance(
    links: Sequence[GraphDelegationLink],
) -> Optional[ChainValidationResult]:
    """Validate issuer/audience linkage: each issuer equals previous audience."""
    if not links:
        return _deny("empty_chain", "delegation chain is empty")
    for idx in range(1, len(links)):
        prev = links[idx - 1]
        cur = links[idx]
        if cur.issuer != prev.audience:
            return _deny(
                "issuer_mismatch",
                f"chain break at link {idx}: issuer {cur.issuer!r} != previous audience {prev.audience!r}",
                details={"index": idx, "issuer": cur.issuer, "expected": prev.audience},
                root_issuer=links[0].issuer,
                leaf_audience=links[-1].audience,
            )
    return None


def validate_chain_attenuation(
    links: Sequence[GraphDelegationLink],
) -> Optional[ChainValidationResult]:
    """Validate resource/ability/caveat attenuation across consecutive links.

    Every capability on link ``i+1`` must be covered by at least one capability
    on link ``i`` (and link-level caveats must attenuate).
    """
    if not links:
        return _deny("empty_chain", "delegation chain is empty")
    for idx in range(1, len(links)):
        parent = links[idx - 1]
        child = links[idx]
        # Link-level caveat attenuation
        if not caveat_contains(parent.caveats, child.caveats):
            return _deny(
                "caveat_not_attenuated",
                f"link {idx} caveats do not attenuate parent",
                details={"index": idx},
                root_issuer=links[0].issuer,
                leaf_audience=links[-1].audience,
            )
        # Expiry must not extend past parent
        if parent.expiry is not None:
            if child.expiry is None or child.expiry > parent.expiry:
                return _deny(
                    "caveat_not_attenuated",
                    f"link {idx} expiry extends past parent",
                    details={
                        "index": idx,
                        "parent_expiry": parent.expiry,
                        "child_expiry": child.expiry,
                    },
                    root_issuer=links[0].issuer,
                    leaf_audience=links[-1].audience,
                )
        if parent.not_before is not None and child.not_before is not None:
            if child.not_before < parent.not_before:
                return _deny(
                    "caveat_not_attenuated",
                    f"link {idx} not_before weakens parent",
                    details={"index": idx},
                    root_issuer=links[0].issuer,
                    leaf_audience=links[-1].audience,
                )
        for child_cap in child.capabilities:
            if not any(parent_cap.attenuates_to(child_cap) for parent_cap in parent.capabilities):
                return _deny(
                    "ability_not_attenuated"
                    if not any(
                        ability_contains(p.ability, child_cap.ability)
                        for p in parent.capabilities
                    )
                    else (
                        "resource_not_contained"
                        if not any(
                            resource_contains(p.resource, child_cap.resource)
                            for p in parent.capabilities
                        )
                        else "caveat_not_attenuated"
                    ),
                    f"link {idx} capability not covered by parent",
                    details={
                        "index": idx,
                        "child": child_cap.to_json_dict(),
                    },
                    root_issuer=links[0].issuer,
                    leaf_audience=links[-1].audience,
                )
    return None


def validate_chain_time(
    links: Sequence[GraphDelegationLink],
    *,
    now: Optional[float] = None,
) -> Optional[ChainValidationResult]:
    """Ensure every link is within its validity window."""
    t = now if now is not None else time.time()
    for idx, link in enumerate(links):
        ok, reason = link.is_active(t)
        if not ok:
            return _deny(
                reason or "expired",
                f"link {idx} is not active ({reason})",
                details={"index": idx, "expiry": link.expiry, "not_before": link.not_before},
                root_issuer=links[0].issuer if links else None,
                leaf_audience=links[-1].audience if links else None,
            )
    return None


def validate_chain_revocation(
    links: Sequence[GraphDelegationLink],
    revoked_cids: Optional[Iterable[str]] = None,
) -> Optional[ChainValidationResult]:
    """Fail if any link CID appears in the revocation set."""
    revoked = frozenset(revoked_cids or ())
    if not revoked:
        return None
    for idx, link in enumerate(links):
        if link.cid and link.cid in revoked:
            return _deny(
                "revoked",
                f"link {idx} cid {link.cid!r} is revoked",
                details={"index": idx, "cid": link.cid},
                root_issuer=links[0].issuer,
                leaf_audience=links[-1].audience,
            )
        if link.proof_cid and link.proof_cid in revoked:
            return _deny(
                "revoked",
                f"link {idx} proof_cid {link.proof_cid!r} is revoked",
                details={"index": idx, "proof_cid": link.proof_cid},
                root_issuer=links[0].issuer,
                leaf_audience=links[-1].audience,
            )
    return None


def validate_chain_audience(
    links: Sequence[GraphDelegationLink],
    *,
    invoker: Optional[str],
    require_invoker: bool = True,
) -> Optional[ChainValidationResult]:
    """Leaf audience must match the invoker principal when required."""
    if not links:
        return _deny("empty_chain", "delegation chain is empty")
    leaf = links[-1]
    if require_invoker and not invoker:
        return _deny(
            "missing_principal",
            "invoker principal is required",
            leaf_audience=leaf.audience,
            root_issuer=links[0].issuer,
        )
    if invoker is not None and invoker != leaf.audience:
        return _deny(
            "audience_mismatch",
            f"invoker {invoker!r} is not leaf audience {leaf.audience!r}",
            details={"invoker": invoker, "audience": leaf.audience},
            leaf_audience=leaf.audience,
            root_issuer=links[0].issuer,
        )
    # Audience caveat on any link must include the invoker when present.
    if invoker is not None:
        for idx, link in enumerate(links):
            if link.caveats.audience is not None and invoker not in link.caveats.audience:
                return _deny(
                    "audience_mismatch",
                    f"link {idx} audience caveat excludes invoker",
                    details={"index": idx, "invoker": invoker},
                    leaf_audience=leaf.audience,
                    root_issuer=links[0].issuer,
                )
            for cap in link.capabilities:
                if cap.caveats.audience is not None and invoker not in cap.caveats.audience:
                    return _deny(
                        "audience_mismatch",
                        f"capability audience caveat excludes invoker at link {idx}",
                        details={"index": idx, "invoker": invoker},
                        leaf_audience=leaf.audience,
                        root_issuer=links[0].issuer,
                    )
    return None


def validate_chain_replay(
    links: Sequence[GraphDelegationLink],
    *,
    seen_nonces: Optional[Iterable[str]] = None,
    require_nonce: bool = False,
    ability: Optional[str] = None,
) -> Optional[ChainValidationResult]:
    """Reject reused nonces; optionally require nonce for mutating abilities."""
    mutating = ability in {"graph/write", "graph/admin", "graph/pin", "graph/delegate"}
    leaf = links[-1] if links else None
    if require_nonce or mutating:
        if leaf is not None and not leaf.nonce:
            if require_nonce or mutating:
                # Mutating ops should bind a nonce/idempotency key when the
                # policy requires replay defense; soft-require only when flag set.
                if require_nonce:
                    return _deny(
                        "nonce_required",
                        "nonce is required for this invocation",
                        leaf_audience=leaf.audience if leaf else None,
                        root_issuer=links[0].issuer if links else None,
                    )
    seen = frozenset(seen_nonces or ())
    for idx, link in enumerate(links):
        if link.nonce and link.nonce in seen:
            return _deny(
                "replay",
                f"nonce on link {idx} has already been used",
                details={"index": idx, "nonce": link.nonce},
                root_issuer=links[0].issuer if links else None,
                leaf_audience=links[-1].audience if links else None,
            )
    return None


def validate_delegation_chain(
    links: Sequence[GraphDelegationLink],
    *,
    resource: Union[GraphResource, str],
    ability: str,
    invoker: Optional[str] = None,
    require_invoker: bool = True,
    now: Optional[float] = None,
    revoked_cids: Optional[Iterable[str]] = None,
    seen_nonces: Optional[Iterable[str]] = None,
    require_nonce: bool = False,
    request_caveats: Optional[GraphCaveats] = None,
) -> ChainValidationResult:
    """Full fail-closed validation of an attenuated graph UCAN chain.

    Checks (in order): empty chain, ability vocabulary, issuance linkage,
    attenuation, time, revocation, audience, replay, and leaf capability cover
    of the requested resource/ability (plus request caveats when provided).
    """
    if not links:
        return _deny("empty_chain", "delegation chain is empty")

    try:
        req_ability = normalize_ability(ability)
        req_resource = (
            resource if isinstance(resource, GraphResource) else parse_graph_resource(resource)
        )
    except UCANContractError as exc:
        return _deny(exc.reason, exc.message, details=exc.details)

    for checker in (
        lambda: validate_chain_issuance(links),
        lambda: validate_chain_attenuation(links),
        lambda: validate_chain_time(links, now=now),
        lambda: validate_chain_revocation(links, revoked_cids),
        lambda: validate_chain_audience(
            links, invoker=invoker, require_invoker=require_invoker
        ),
        lambda: validate_chain_replay(
            links,
            seen_nonces=seen_nonces,
            require_nonce=require_nonce,
            ability=req_ability,
        ),
    ):
        failure = checker()
        if failure is not None:
            return failure

    leaf = links[-1]
    covering = [
        cap
        for cap in leaf.capabilities
        if resource_contains(cap.resource, req_resource)
        and ability_contains(cap.ability, req_ability)
    ]
    if not covering:
        return _deny(
            "capability_missing",
            f"leaf does not grant {req_ability!r} on {req_resource.uri!r}",
            details={"resource": req_resource.uri, "ability": req_ability},
            leaf_audience=leaf.audience,
            root_issuer=links[0].issuer,
        )

    # Effective caveats = intersection-style attenuation of covering caps + link.
    # For request admission, each covering cap's caveats (and link caveats) must
    # allow the request.
    req_cav = request_caveats or GraphCaveats.empty()
    for cap in covering:
        # Request caveats must be an attenuation of the grant caveats when the
        # grant is restricted; unrestricted request is checked via allow_request.
        if not caveat_contains(cap.caveats, req_cav) and not req_cav.is_empty():
            # If request carries tighter caveats they must still be subsets;
            # if grant is empty and request is empty, ok.
            if not cap.caveats.is_empty() and not caveat_contains(cap.caveats, req_cav):
                return _deny(
                    "caveat_not_attenuated",
                    "request caveats are not permitted by grant",
                    details={
                        "grant": cap.caveats.to_json_dict(),
                        "request": req_cav.to_json_dict(),
                    },
                    leaf_audience=leaf.audience,
                    root_issuer=links[0].issuer,
                )
        ok, reason = caveats_allow_request(
            cap.caveats,
            branch=req_resource.branch,
            revision=req_resource.revision,
            query_kind=(
                next(iter(req_cav.query)) if req_cav.query else None
            ),
            audience=invoker,
            now=now,
        )
        if not ok:
            return _deny(
                reason or "caveat_not_attenuated",
                "request denied by capability caveats",
                details={"capability": cap.to_json_dict()},
                leaf_audience=leaf.audience,
                root_issuer=links[0].issuer,
            )
        ok, reason = caveats_allow_request(
            leaf.caveats,
            branch=req_resource.branch,
            revision=req_resource.revision,
            audience=invoker,
            now=now,
        )
        if not ok:
            return _deny(
                reason or "caveat_not_attenuated",
                "request denied by link caveats",
                leaf_audience=leaf.audience,
                root_issuer=links[0].issuer,
            )

    return ChainValidationResult(
        allowed=True,
        message="ok",
        leaf_audience=leaf.audience,
        root_issuer=links[0].issuer,
        effective_capabilities=tuple(covering),
        details={"resource": req_resource.uri, "ability": req_ability},
    )


# ---------------------------------------------------------------------------
# Audit / receipt contracts
# ---------------------------------------------------------------------------

AUDIT_EVENT_TYPES: Final = frozenset({"ucan.allow", "ucan.deny"})


@dataclass(frozen=True, slots=True)
class AuthorizationReceipt:
    """Redacted, content-addressed allow/deny receipt (contract shape).

    Receipts **must not** contain raw UCAN tokens, signatures, graph property
    values, or raw query text. Digests bind policy and request metadata.
    """

    decision: str  # "allow" | "deny"
    principal: Optional[str]
    resource: str
    ability: str
    reason: Optional[str]
    error_code: Optional[str]
    policy_digest: str
    request_digest: str
    chain_digest: str
    contract_version: str = CONTRACT_VERSION
    receipt_cid: str = ""

    def __post_init__(self) -> None:
        if self.decision not in {"allow", "deny"}:
            raise UCANContractError(
                "invalid_caveat",
                "receipt decision must be 'allow' or 'deny'",
                details={"decision": self.decision},
            )
        if not self.receipt_cid:
            object.__setattr__(self, "receipt_cid", self.compute_cid())

    def compute_cid(self) -> str:
        payload = {
            "decision": self.decision,
            "principal": self.principal,
            "resource": self.resource,
            "ability": self.ability,
            "reason": self.reason,
            "error_code": self.error_code,
            "policy_digest": self.policy_digest,
            "request_digest": self.request_digest,
            "chain_digest": self.chain_digest,
            "contract_version": self.contract_version,
        }
        return content_digest(payload, domain="kg.ucan.receipt")

    def to_json_dict(self) -> JSONDict:
        return {
            "decision": self.decision,
            "principal": self.principal,
            "resource": self.resource,
            "ability": self.ability,
            "reason": self.reason,
            "error_code": self.error_code,
            "policy_digest": self.policy_digest,
            "request_digest": self.request_digest,
            "chain_digest": self.chain_digest,
            "contract_version": self.contract_version,
            "receipt_cid": self.receipt_cid,
        }


def content_digest(payload: Mapping[str, Any], *, domain: str = IDENTITY_DOMAIN) -> str:
    """Canonical JSON digest used for policy/request/chain binding."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(f"{domain}|{canonical}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def redact_for_audit(event: Mapping[str, Any]) -> JSONDict:
    """Return a copy of *event* with sensitive keys redacted.

    Redacts keys whose final path segment (case-insensitive) is in
    :data:`AUDIT_REDACT_KEYS`, or that contain ``token`` / ``secret`` /
    ``password`` / ``signature`` as substrings.
    """

    def _should_redact(key: str) -> bool:
        low = key.lower()
        if low in AUDIT_REDACT_KEYS:
            return True
        for needle in ("token", "secret", "password", "signature", "private_key", "bearer"):
            if needle in low:
                return True
        return False

    def _walk(obj: Any) -> Any:
        if isinstance(obj, Mapping):
            out: JSONDict = {}
            for k, v in obj.items():
                ks = str(k)
                if _should_redact(ks):
                    out[ks] = "[REDACTED]"
                else:
                    out[ks] = _walk(v)
            return out
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        return obj

    return _walk(dict(event))


def build_authorization_receipt(
    *,
    result: ChainValidationResult,
    resource: Union[GraphResource, str],
    ability: str,
    principal: Optional[str],
    policy: Optional[Mapping[str, Any]] = None,
    request: Optional[Mapping[str, Any]] = None,
    chain: Optional[Sequence[GraphDelegationLink]] = None,
) -> AuthorizationReceipt:
    """Build a redacted receipt from a chain validation result."""
    res_uri = resource if isinstance(resource, str) else resource.uri
    safe_request = redact_for_audit(request or {})
    safe_policy = redact_for_audit(policy or {"contract_version": CONTRACT_VERSION})
    chain_payload = [link.to_json_dict() for link in (chain or ())]
    # Strip nonces from chain digest material? Keep structure but redact nothing
    # critical beyond signatures (links have no raw signatures here).
    return AuthorizationReceipt(
        decision="allow" if result.allowed else "deny",
        principal=principal or result.leaf_audience,
        resource=res_uri,
        ability=ability,
        reason=result.reason,
        error_code=result.error_code,
        policy_digest=content_digest(safe_policy, domain="kg.ucan.policy"),
        request_digest=content_digest(safe_request, domain="kg.ucan.request"),
        chain_digest=content_digest({"links": chain_payload}, domain="kg.ucan.chain"),
    )


def deny_reason_to_error_code(reason: str) -> str:
    """Map a machine deny reason to a service TypedError code."""
    return ERROR_CODE_MAP.get(reason, "FORBIDDEN")


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "CONTRACT_VERSION",
    "RESOURCE_SCHEME",
    "GRAPH_ABILITIES",
    "OPERATION_ABILITIES",
    "CAVEAT_KEYS",
    "QUERY_KINDS",
    "DENY_REASONS",
    "ERROR_CODE_MAP",
    "AUDIT_REDACT_KEYS",
    "AUDIT_EVENT_TYPES",
    "UCANContractError",
    "GraphResource",
    "GraphCaveats",
    "GraphCapability",
    "GraphDelegationLink",
    "ChainValidationResult",
    "AuthorizationReceipt",
    "parse_graph_resource",
    "resource_to_uri",
    "resource_contains",
    "assert_resource_contained",
    "normalize_ability",
    "ability_for_operation",
    "ability_contains",
    "assert_ability_attenuated",
    "abilities_cover",
    "caveats_from_mapping",
    "caveat_contains",
    "assert_caveats_attenuated",
    "caveats_allow_request",
    "capability_contains",
    "assert_capability_attenuated",
    "link_from_delegation_token",
    "link_to_profile_c_capability_dicts",
    "validate_chain_issuance",
    "validate_chain_attenuation",
    "validate_chain_time",
    "validate_chain_revocation",
    "validate_chain_audience",
    "validate_chain_replay",
    "validate_delegation_chain",
    "content_digest",
    "redact_for_audit",
    "build_authorization_receipt",
    "deny_reason_to_error_code",
]
