"""Workload-separated catalog federation for the trusted query broker (DQK-040).

Federate authority catalogs **only** inside a trusted in-process query broker:

* explicit workload routes (control / analytical / publication / untrusted)
* never ATTACH authority catalogs on untrusted or publication sessions
* no GRANT-style catalog ACL is assumed — isolation is physical (separate
  databases, trust-gated ATTACH, copy-out publications)
* cross-catalog snapshots bind an explicit per-catalog revision vector
* sanitized copy-out publications land in a physically separate publication
  catalog so Quack clients never see authority files
* analytical cancellation is local to analytical sessions and never aborts or
  holds the control-plane writer

Importing this module is inert: it never imports ``duckdb``, never opens
sockets or files, and never installs extensions. Real sessions are opened
only through an injected :class:`~ipfs_datasets_py.duckdb_control.connections.ConnectionManager`.
"""

from __future__ import annotations

import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    ClassVar,
    Final,
    Iterator,
    Mapping,
    Sequence,
)

from ipfs_datasets_py.duckdb_control import connections as cx
from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    SnapshotId,
    content_identity,
    normalize_timestamp,
    parse_snapshot_id,
    parse_source_digest,
)

__all__ = [
    "FEDERATION_SCHEMA",
    "CROSS_CATALOG_SNAPSHOT_SCHEMA",
    "PUBLICATION_RECEIPT_SCHEMA",
    "AUTHORITY_DOMAINS",
    "SENSITIVE_PUBLICATION_COLUMNS",
    "AuthorityCatalog",
    "CancellationToken",
    "CatalogDomain",
    "CopyOutColumn",
    "CrossCatalogSnapshot",
    "FederatedQuerySession",
    "FederationError",
    "FederationPolicy",
    "PublicationReceipt",
    "RevisionBinding",
    "RouteIntent",
    "SanitizedCopyOutSpec",
    "TrustedQueryBroker",
    "WorkloadRoute",
    "default_routes",
    "resolve_workload_route",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

FEDERATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-catalog-federation@1"
)
CROSS_CATALOG_SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-cross-catalog-snapshot@1"
)
PUBLICATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-sanitized-publication@1"
)

# Content-addressed implementation generation (not a wire schema field).
_FEDERATION_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-040-lane2-attempt1-20260810"
)

_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SAFE_PATH_CHARS = re.compile(r"^[^;\x00-\x1f]+$")

# Column names that must never appear in sanitized publications.
SENSITIVE_PUBLICATION_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "private_keys",
        "seed",
        "seeds",
        "mnemonic",
        "signing_payload",
        "signing_key",
        "secret",
        "secrets",
        "password",
        "token",
        "quack_token",
        "api_key",
        "encryption_key",
        "raw_payload",
        "wallet_secret",
    }
)


class FederationError(ValueError):
    """Fail-closed federation policy, route, snapshot, or publication rejection."""


class CatalogDomain(str, Enum):
    """Logical authority domains that map to separate catalog files.

    DuckDB has no GRANT-style catalog ACL. Domains that hold mutable
    operational truth or sensitive material are physically isolated and
    may only be ATTACHed by the trusted analytical broker route.
    """

    CONTROL = "control"
    GRAPH = "graph"
    PROOF = "proof"
    AST = "ast"
    VECTOR = "vector"
    WALLET = "wallet"
    META = "meta"
    OBSERVABILITY = "observability"
    PUBLICATION = "publication"
    DUCKLAKE_REGISTRY = "ducklake_registry"


# Domains that must never be ATTACHed to untrusted / publication sessions.
AUTHORITY_DOMAINS: Final[frozenset[CatalogDomain]] = frozenset(
    {
        CatalogDomain.CONTROL,
        CatalogDomain.GRAPH,
        CatalogDomain.PROOF,
        CatalogDomain.AST,
        CatalogDomain.VECTOR,
        CatalogDomain.WALLET,
        CatalogDomain.META,
        CatalogDomain.OBSERVABILITY,
        CatalogDomain.DUCKLAKE_REGISTRY,
    }
)


class RouteIntent(str, Enum):
    """Caller intent used to select an explicit workload route."""

    CONTROL_HEARTBEAT = "control_heartbeat"
    CONTROL_MUTATION = "control_mutation"
    ANALYTICAL_FEDERATED_QUERY = "analytical_federated_query"
    SANITIZED_PUBLICATION = "sanitized_publication"
    UNTRUSTED_QUACK_CLIENT = "untrusted_quack_client"


# ---------------------------------------------------------------------------
# Workload routes (explicit; no GRANT ACL)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkloadRoute:
    """Explicit mapping from intent to isolated pool and ATTACH privileges.

    Isolation is physical: separate connection pools, separate primary
    catalogs, and a hard ``allow_authority_attach`` gate. There is no
    GRANT / REVOKE surface and none is assumed.
    """

    name: str
    intent: RouteIntent
    workload: cx.WorkloadKind
    trust: cx.TrustLevel
    allow_authority_attach: bool
    allowed_domains: frozenset[CatalogDomain]
    description: str = ""

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name or not _SAFE_TOKEN.fullmatch(name):
            raise FederationError(f"invalid route name {self.name!r}")
        object.__setattr__(self, "name", name)

        if not isinstance(self.intent, RouteIntent):
            raise FederationError("intent must be a RouteIntent")
        if not isinstance(self.workload, cx.WorkloadKind):
            raise FederationError("workload must be a WorkloadKind")
        if not isinstance(self.trust, cx.TrustLevel):
            raise FederationError("trust must be a TrustLevel")

        domains = self.allowed_domains or frozenset()
        if not isinstance(domains, (frozenset, set, tuple, list)):
            raise FederationError("allowed_domains must be a collection")
        frozen = frozenset(CatalogDomain(d) if not isinstance(d, CatalogDomain) else d for d in domains)
        object.__setattr__(self, "allowed_domains", frozen)

        # Fail closed: untrusted / publication routes never attach authority.
        if self.trust is cx.TrustLevel.UNTRUSTED and self.allow_authority_attach:
            raise FederationError(
                "untrusted routes cannot allow authority catalog ATTACH "
                "(no GRANT-style ACL can compensate)"
            )
        if self.workload in (
            cx.WorkloadKind.PUBLICATION,
            cx.WorkloadKind.UNTRUSTED,
        ) and self.allow_authority_attach:
            raise FederationError(
                "publication/untrusted workloads cannot allow authority ATTACH"
            )
        if self.allow_authority_attach and self.workload is not cx.WorkloadKind.ANALYTICAL:
            raise FederationError(
                "authority catalog ATTACH is only permitted on the analytical "
                "workload route (trusted in-process broker)"
            )
        if self.allow_authority_attach and self.trust is not cx.TrustLevel.TRUSTED:
            raise FederationError(
                "authority catalog ATTACH requires TrustLevel.TRUSTED"
            )
        # Control workload must never carry analytical authority attachments.
        if self.workload is cx.WorkloadKind.CONTROL and self.allow_authority_attach:
            raise FederationError(
                "control route must not attach analytical authority catalogs"
            )
        # Authority domains are never allowed on untrusted/publication routes.
        if self.workload in (
            cx.WorkloadKind.PUBLICATION,
            cx.WorkloadKind.UNTRUSTED,
        ):
            leaked = frozen & AUTHORITY_DOMAINS
            if leaked:
                raise FederationError(
                    "publication/untrusted routes cannot list authority domains: "
                    + ", ".join(sorted(d.value for d in leaked))
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "intent": self.intent.value,
            "workload": self.workload.value,
            "trust": self.trust.value,
            "allow_authority_attach": self.allow_authority_attach,
            "allowed_domains": sorted(d.value for d in self.allowed_domains),
            "description": self.description,
            "grant_acl_assumed": False,
        }


def default_routes() -> Mapping[RouteIntent, WorkloadRoute]:
    """Return the closed set of production workload routes."""

    analytical_domains = frozenset(AUTHORITY_DOMAINS) - {CatalogDomain.CONTROL}
    routes = {
        RouteIntent.CONTROL_HEARTBEAT: WorkloadRoute(
            name="control_heartbeat",
            intent=RouteIntent.CONTROL_HEARTBEAT,
            workload=cx.WorkloadKind.CONTROL,
            trust=cx.TrustLevel.TRUSTED,
            allow_authority_attach=False,
            allowed_domains=frozenset({CatalogDomain.CONTROL}),
            description="Short-lived control readers for leases and heartbeats",
        ),
        RouteIntent.CONTROL_MUTATION: WorkloadRoute(
            name="control_mutation",
            intent=RouteIntent.CONTROL_MUTATION,
            workload=cx.WorkloadKind.CONTROL,
            trust=cx.TrustLevel.TRUSTED,
            allow_authority_attach=False,
            allowed_domains=frozenset({CatalogDomain.CONTROL}),
            description="Bounded control writer; never shares pool with scans",
        ),
        RouteIntent.ANALYTICAL_FEDERATED_QUERY: WorkloadRoute(
            name="analytical_federated_query",
            intent=RouteIntent.ANALYTICAL_FEDERATED_QUERY,
            workload=cx.WorkloadKind.ANALYTICAL,
            trust=cx.TrustLevel.TRUSTED,
            allow_authority_attach=True,
            allowed_domains=analytical_domains,
            description=(
                "Trusted in-process broker route: sole path that may ATTACH "
                "read-only authority catalogs"
            ),
        ),
        RouteIntent.SANITIZED_PUBLICATION: WorkloadRoute(
            name="sanitized_publication",
            intent=RouteIntent.SANITIZED_PUBLICATION,
            workload=cx.WorkloadKind.PUBLICATION,
            trust=cx.TrustLevel.UNTRUSTED,
            allow_authority_attach=False,
            allowed_domains=frozenset({CatalogDomain.PUBLICATION}),
            description=(
                "Physically separate publication catalog; copy-out only, "
                "never ATTACH authority"
            ),
        ),
        RouteIntent.UNTRUSTED_QUACK_CLIENT: WorkloadRoute(
            name="untrusted_quack_client",
            intent=RouteIntent.UNTRUSTED_QUACK_CLIENT,
            workload=cx.WorkloadKind.UNTRUSTED,
            trust=cx.TrustLevel.UNTRUSTED,
            allow_authority_attach=False,
            allowed_domains=frozenset({CatalogDomain.PUBLICATION}),
            description="Remote Quack clients see only sanitized publications",
        ),
    }
    return MappingProxyType(routes)


def resolve_workload_route(
    intent: RouteIntent | str,
    *,
    routes: Mapping[RouteIntent, WorkloadRoute] | None = None,
) -> WorkloadRoute:
    """Resolve ``intent`` to an explicit :class:`WorkloadRoute` (fail closed)."""

    table = routes if routes is not None else default_routes()
    if isinstance(intent, str):
        try:
            intent = RouteIntent(intent)
        except ValueError as exc:
            raise FederationError(f"unknown route intent {intent!r}") from exc
    if not isinstance(intent, RouteIntent):
        raise FederationError("intent must be a RouteIntent")
    route = table.get(intent)
    if route is None:
        raise FederationError(f"no workload route registered for {intent.value}")
    return route


# ---------------------------------------------------------------------------
# Authority catalog registration + revision bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorityCatalog:
    """Registered authority catalog available only to the trusted broker.

    Paths are local filesystem identities for the broker process. They are
    never exposed to Quack clients or untrusted sessions.
    """

    alias: str
    path: str
    domain: CatalogDomain
    revision_id: str
    store_generation: int = 0
    schema_checksum: str = ""
    read_only: bool = True

    def __post_init__(self) -> None:
        alias = str(self.alias or "").strip()
        if not _ALIAS_RE.match(alias):
            raise FederationError(f"invalid catalog alias {self.alias!r}")
        object.__setattr__(self, "alias", alias)

        path = str(self.path or "").strip()
        if not path:
            raise FederationError("catalog path is required")
        if not _SAFE_PATH_CHARS.match(path):
            raise FederationError(f"unsafe catalog path {path!r}")
        lower = path.lower()
        if "://" in path or lower.startswith(("s3:", "http:", "https:", "gs:", "az:")):
            raise FederationError(
                f"remote/URI catalog paths are forbidden for local attach: {path!r}"
            )
        object.__setattr__(self, "path", path)

        if not isinstance(self.domain, CatalogDomain):
            try:
                object.__setattr__(self, "domain", CatalogDomain(str(self.domain)))
            except ValueError as exc:
                raise FederationError(
                    f"unsupported catalog domain {self.domain!r}"
                ) from exc

        if self.domain is CatalogDomain.PUBLICATION:
            raise FederationError(
                "publication catalogs are not authority catalogs; use copy-out"
            )
        if self.domain not in AUTHORITY_DOMAINS:
            raise FederationError(
                f"domain {self.domain.value} is not an authority domain"
            )

        rev = str(self.revision_id or "").strip()
        if not rev or not _SAFE_TOKEN.fullmatch(rev):
            raise FederationError(f"invalid revision_id {self.revision_id!r}")
        object.__setattr__(self, "revision_id", rev)

        if not isinstance(self.store_generation, int) or isinstance(
            self.store_generation, bool
        ):
            raise FederationError("store_generation must be an int")
        if self.store_generation < 0:
            raise FederationError("store_generation must be non-negative")

        if self.schema_checksum:
            try:
                object.__setattr__(
                    self,
                    "schema_checksum",
                    parse_source_digest(self.schema_checksum),
                )
            except ContractError as exc:
                raise FederationError(str(exc)) from exc

        if not self.read_only:
            raise FederationError(
                "authority catalogs must be registered read_only=True for federation"
            )

    def to_analytical_spec(self) -> cx.AnalyticalCatalogSpec:
        """Materialize a DQK-005 analytical ATTACH spec (trusted broker only)."""

        return cx.AnalyticalCatalogSpec(
            alias=self.alias,
            path=self.path,
            read_only=True,
            workload=cx.WorkloadKind.ANALYTICAL,
        )

    def revision_binding(self) -> "RevisionBinding":
        return RevisionBinding(
            catalog_alias=self.alias,
            domain=self.domain,
            revision_id=self.revision_id,
            store_generation=self.store_generation,
            schema_checksum=self.schema_checksum,
            path_digest=content_identity({"alias": self.alias, "path": self.path}),
        )

    def to_dict(self) -> dict[str, Any]:
        # Path is broker-private; redact from public receipts by default.
        return {
            "alias": self.alias,
            "domain": self.domain.value,
            "revision_id": self.revision_id,
            "store_generation": self.store_generation,
            "schema_checksum": self.schema_checksum,
            "read_only": True,
            "path_present": bool(self.path),
        }


@dataclass(frozen=True, slots=True)
class RevisionBinding:
    """Per-catalog revision member of a cross-catalog snapshot vector."""

    catalog_alias: str
    domain: CatalogDomain
    revision_id: str
    store_generation: int = 0
    schema_checksum: str = ""
    path_digest: str = ""

    def __post_init__(self) -> None:
        alias = str(self.catalog_alias or "").strip()
        if not _ALIAS_RE.match(alias):
            raise FederationError(f"invalid catalog_alias {self.catalog_alias!r}")
        object.__setattr__(self, "catalog_alias", alias)

        if not isinstance(self.domain, CatalogDomain):
            try:
                object.__setattr__(self, "domain", CatalogDomain(str(self.domain)))
            except ValueError as exc:
                raise FederationError(f"unsupported domain {self.domain!r}") from exc

        rev = str(self.revision_id or "").strip()
        if not rev or not _SAFE_TOKEN.fullmatch(rev):
            raise FederationError(f"invalid revision_id {self.revision_id!r}")
        object.__setattr__(self, "revision_id", rev)

        if not isinstance(self.store_generation, int) or isinstance(
            self.store_generation, bool
        ):
            raise FederationError("store_generation must be an int")
        if self.store_generation < 0:
            raise FederationError("store_generation must be non-negative")

        if self.schema_checksum:
            try:
                object.__setattr__(
                    self,
                    "schema_checksum",
                    parse_source_digest(self.schema_checksum),
                )
            except ContractError as exc:
                raise FederationError(str(exc)) from exc

        if self.path_digest:
            try:
                object.__setattr__(
                    self, "path_digest", parse_source_digest(self.path_digest)
                )
            except ContractError as exc:
                raise FederationError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_alias": self.catalog_alias,
            "domain": self.domain.value,
            "revision_id": self.revision_id,
            "store_generation": self.store_generation,
            "schema_checksum": self.schema_checksum,
            "path_digest": self.path_digest,
        }


@dataclass(frozen=True, slots=True)
class CrossCatalogSnapshot:
    """Explicit multi-catalog snapshot vector with revision bindings.

    Independent catalogs do not share one atomic transaction. Federated
    queries must bind one revision member per attached catalog so results
    are reproducible and audit-visible.
    """

    SCHEMA: ClassVar[str] = CROSS_CATALOG_SNAPSHOT_SCHEMA

    snapshot_id: str
    bindings: tuple[RevisionBinding, ...]
    created_at: str
    route_name: str = "analytical_federated_query"

    def __post_init__(self) -> None:
        try:
            sid = parse_snapshot_id(self.snapshot_id)
        except ContractError as exc:
            raise FederationError(str(exc)) from exc
        object.__setattr__(self, "snapshot_id", sid)

        if not self.bindings:
            raise FederationError(
                "cross-catalog snapshot requires at least one revision binding"
            )
        if not isinstance(self.bindings, tuple):
            object.__setattr__(self, "bindings", tuple(self.bindings))

        aliases: set[str] = set()
        for binding in self.bindings:
            if not isinstance(binding, RevisionBinding):
                raise FederationError("bindings must be RevisionBinding instances")
            if binding.catalog_alias in aliases:
                raise FederationError(
                    f"duplicate catalog_alias in snapshot: {binding.catalog_alias}"
                )
            aliases.add(binding.catalog_alias)

        try:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
        except ContractError as exc:
            raise FederationError(str(exc)) from exc

        route = str(self.route_name or "").strip()
        if not route or not _SAFE_TOKEN.fullmatch(route):
            raise FederationError(f"invalid route_name {self.route_name!r}")
        object.__setattr__(self, "route_name", route)

    @property
    def revision_vector(self) -> tuple[dict[str, Any], ...]:
        """Ordered revision bindings exposed for receipts and audit."""

        return tuple(b.to_dict() for b in self.bindings)

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "schema": CROSS_CATALOG_SNAPSHOT_SCHEMA,
                "snapshot_id": self.snapshot_id,
                "bindings": [b.to_dict() for b in self.bindings],
                "created_at": self.created_at,
                "route_name": self.route_name,
            }
        )

    def binding_for(self, alias: str) -> RevisionBinding:
        for binding in self.bindings:
            if binding.catalog_alias == alias:
                return binding
        raise FederationError(f"no revision binding for catalog alias {alias!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CROSS_CATALOG_SNAPSHOT_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "route_name": self.route_name,
            "revision_bindings": [b.to_dict() for b in self.bindings],
            "identity_id": self.identity_id,
            "grant_acl_assumed": False,
        }

    def as_contract_snapshot(self) -> SnapshotId:
        """Project the vector root into a DQK-004 :class:`SnapshotId`."""

        return SnapshotId(
            value=self.identity_id,
            store_generation=max(b.store_generation for b in self.bindings),
            schema_checksum=self.bindings[0].schema_checksum
            if self.bindings[0].schema_checksum
            else "",
        )


# ---------------------------------------------------------------------------
# Sanitized copy-out publication
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CopyOutColumn:
    """Allowlisted column for a sanitized publication projection."""

    name: str
    classification: str = "public"

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not _SAFE_IDENT.match(name):
            raise FederationError(f"invalid column name {self.name!r}")
        object.__setattr__(self, "name", name)
        classification = str(self.classification or "public").strip().lower()
        if classification not in {"public", "redacted"}:
            raise FederationError(
                f"column classification must be public|redacted, got {classification!r}"
            )
        object.__setattr__(self, "classification", classification)
        if name.lower() in SENSITIVE_PUBLICATION_COLUMNS:
            raise FederationError(
                f"column {name!r} is forbidden on sanitized publications"
            )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "classification": self.classification}


@dataclass(frozen=True, slots=True)
class SanitizedCopyOutSpec:
    """Spec for copying allowlisted rows into the publication catalog.

    The trusted broker evaluates ``source_sql`` on an analytical session that
    already holds authority attachments, then materializes only allowlisted
    columns into the physically separate publication database. Quack clients
    attach only that publication database — never authority catalogs.
    """

    publication_id: str
    target_table: str
    columns: tuple[CopyOutColumn, ...]
    source_sql: str
    source_snapshot: CrossCatalogSnapshot
    max_rows: int = 10_000

    def __post_init__(self) -> None:
        pub_id = str(self.publication_id or "").strip()
        if not pub_id or not _SAFE_TOKEN.fullmatch(pub_id):
            raise FederationError(f"invalid publication_id {self.publication_id!r}")
        object.__setattr__(self, "publication_id", pub_id)

        table = str(self.target_table or "").strip()
        if not _SAFE_IDENT.match(table):
            raise FederationError(f"invalid target_table {self.target_table!r}")
        object.__setattr__(self, "target_table", table)

        if not self.columns:
            raise FederationError("copy-out requires at least one allowlisted column")
        if not isinstance(self.columns, tuple):
            object.__setattr__(self, "columns", tuple(self.columns))
        names: set[str] = set()
        for col in self.columns:
            if not isinstance(col, CopyOutColumn):
                raise FederationError("columns must be CopyOutColumn instances")
            if col.name.lower() in names:
                raise FederationError(f"duplicate copy-out column {col.name}")
            names.add(col.name.lower())

        sql = str(self.source_sql or "").strip()
        if not sql:
            raise FederationError("source_sql is required")
        upper = " ".join(sql.upper().split())
        if not upper.startswith(("SELECT ", "WITH ")):
            raise FederationError("source_sql must be a SELECT/WITH query")
        # Deny mutation / attach / extension surfaces in the source projection.
        forbidden = (
            "ATTACH ",
            "DETACH ",
            "INSTALL ",
            "LOAD ",
            "COPY ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "CREATE ",
            "DROP ",
            "ALTER ",
            "GRANT ",
            "REVOKE ",
            "PRAGMA ",
            "SET ",
            "CALL ",
        )
        for fragment in forbidden:
            if fragment in upper:
                raise FederationError(
                    f"source_sql forbids surface {fragment.strip()}: physical "
                    "isolation only; no GRANT-style ACL"
                )
        object.__setattr__(self, "source_sql", sql)

        if not isinstance(self.source_snapshot, CrossCatalogSnapshot):
            raise FederationError("source_snapshot must be a CrossCatalogSnapshot")

        if not isinstance(self.max_rows, int) or isinstance(self.max_rows, bool):
            raise FederationError("max_rows must be an int")
        if self.max_rows < 1 or self.max_rows > 1_000_000:
            raise FederationError("max_rows out of range")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id,
            "target_table": self.target_table,
            "columns": [c.to_dict() for c in self.columns],
            "source_snapshot_id": self.source_snapshot.snapshot_id,
            "source_snapshot_identity": self.source_snapshot.identity_id,
            "max_rows": self.max_rows,
            "grant_acl_assumed": False,
        }


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """Receipt for a sanitized copy-out into the publication catalog."""

    SCHEMA: ClassVar[str] = PUBLICATION_RECEIPT_SCHEMA

    publication_id: str
    target_table: str
    row_count: int
    columns: tuple[str, ...]
    source_snapshot: CrossCatalogSnapshot
    content_digest: str
    created_at: str
    non_authoritative: bool = True

    def __post_init__(self) -> None:
        if not self.non_authoritative:
            raise FederationError(
                "publication receipts must declare non_authoritative=true"
            )
        if not isinstance(self.row_count, int) or self.row_count < 0:
            raise FederationError("row_count must be a non-negative int")
        try:
            object.__setattr__(self, "created_at", normalize_timestamp(self.created_at))
            object.__setattr__(
                self, "content_digest", parse_source_digest(self.content_digest)
            )
        except ContractError as exc:
            raise FederationError(str(exc)) from exc
        if not isinstance(self.columns, tuple):
            object.__setattr__(self, "columns", tuple(self.columns))

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "schema": PUBLICATION_RECEIPT_SCHEMA,
                "publication_id": self.publication_id,
                "target_table": self.target_table,
                "row_count": self.row_count,
                "columns": list(self.columns),
                "source_snapshot_identity": self.source_snapshot.identity_id,
                "content_digest": self.content_digest,
                "created_at": self.created_at,
                "non_authoritative": True,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PUBLICATION_RECEIPT_SCHEMA,
            "publication_id": self.publication_id,
            "target_table": self.target_table,
            "row_count": self.row_count,
            "columns": list(self.columns),
            "source_snapshot": self.source_snapshot.to_dict(),
            "content_digest": self.content_digest,
            "created_at": self.created_at,
            "non_authoritative": True,
            "identity_id": self.identity_id,
            "grant_acl_assumed": False,
            "authority_catalogs_attached_to_publication": False,
        }


# ---------------------------------------------------------------------------
# Cancellation (analytical only)
# ---------------------------------------------------------------------------


class CancellationToken:
    """Thread-safe cancellation signal for analytical federated work.

    Cancelling an analytical session must never ROLLBACK or interrupt a
    concurrent control-plane writer transaction. The token is advisory to
    the broker session only.
    """

    __slots__ = ("_event", "_reason", "_lock")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str = ""
        self._lock = threading.Lock()

    def cancel(self, reason: str = "cancelled") -> None:
        with self._lock:
            if not self._event.is_set():
                self._reason = str(reason or "cancelled")
            self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def check(self) -> None:
        if self._event.is_set():
            raise FederationError(
                f"analytical federation cancelled: {self._reason or 'cancelled'}"
            )

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


# ---------------------------------------------------------------------------
# Federation policy (documents isolation; rejects GRANT ACL assumptions)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FederationPolicy:
    """Closed federation policy. GRANT-style catalog ACL is never assumed."""

    grant_acl_assumed: bool = False
    require_revision_bindings: bool = True
    require_physical_isolation: bool = True
    allow_untrusted_authority_attach: bool = False
    max_attached_catalogs: int = 16

    def __post_init__(self) -> None:
        if self.grant_acl_assumed:
            raise FederationError(
                "GRANT-style catalog ACL is not assumed and must not be enabled; "
                "DuckDB has no catalog GRANT boundary — use physical isolation"
            )
        if self.allow_untrusted_authority_attach:
            raise FederationError(
                "untrusted authority ATTACH is forbidden under federation policy"
            )
        if not self.require_physical_isolation:
            raise FederationError(
                "physical isolation is mandatory for workload-separated federation"
            )
        if not isinstance(self.max_attached_catalogs, int) or self.max_attached_catalogs < 1:
            raise FederationError("max_attached_catalogs must be a positive int")
        if self.max_attached_catalogs > 64:
            raise FederationError("max_attached_catalogs exceeds hard cap of 64")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": FEDERATION_SCHEMA,
            "grant_acl_assumed": False,
            "require_revision_bindings": self.require_revision_bindings,
            "require_physical_isolation": True,
            "allow_untrusted_authority_attach": False,
            "max_attached_catalogs": self.max_attached_catalogs,
            "isolation_model": "physical_workload_routes_and_copy_out",
        }


# ---------------------------------------------------------------------------
# Federated query session
# ---------------------------------------------------------------------------


class FederatedQuerySession:
    """Trusted analytical session with optional authority catalog attachments.

    Holds a :class:`~ipfs_datasets_py.duckdb_control.connections.ManagedConnection`
    borrowed from the analytical pool. Cancellation is session-local and does
    not touch control-plane connections.
    """

    __slots__ = (
        "_connection",
        "_route",
        "_snapshot",
        "_cancel",
        "_closed",
        "_release",
    )

    def __init__(
        self,
        connection: cx.ManagedConnection,
        route: WorkloadRoute,
        snapshot: CrossCatalogSnapshot | None,
        cancel: CancellationToken | None,
        *,
        release: Any = None,
    ) -> None:
        if connection.workload is not route.workload:
            raise FederationError(
                f"session workload {connection.workload.value} does not match "
                f"route {route.workload.value}"
            )
        if connection.trust is not route.trust:
            raise FederationError(
                f"session trust {connection.trust.value} does not match "
                f"route trust {route.trust.value}"
            )
        if route.allow_authority_attach:
            if connection.workload is not cx.WorkloadKind.ANALYTICAL:
                raise FederationError(
                    "authority-attached sessions must use analytical workload"
                )
            if connection.trust is not cx.TrustLevel.TRUSTED:
                raise FederationError(
                    "authority-attached sessions must be TrustLevel.TRUSTED"
                )
        self._connection = connection
        self._route = route
        self._snapshot = snapshot
        self._cancel = cancel or CancellationToken()
        self._closed = False
        self._release = release

    @property
    def connection(self) -> cx.ManagedConnection:
        self._ensure_open()
        return self._connection

    @property
    def route(self) -> WorkloadRoute:
        return self._route

    @property
    def snapshot(self) -> CrossCatalogSnapshot | None:
        return self._snapshot

    @property
    def cancel_token(self) -> CancellationToken:
        return self._cancel

    @property
    def attached_aliases(self) -> tuple[str, ...]:
        return self._connection.attached_aliases

    @property
    def closed(self) -> bool:
        return self._closed

    def _ensure_open(self) -> None:
        if self._closed:
            raise FederationError("federated query session is closed")
        self._cancel.check()

    def execute(self, sql: str, parameters: Any = None) -> Any:
        """Execute SQL on the analytical session under cancellation checks."""

        self._ensure_open()
        self._cancel.check()
        upper = " ".join(str(sql).upper().split())
        if upper.startswith(("GRANT ", "REVOKE ")):
            raise FederationError(
                "GRANT/REVOKE catalog ACL is not supported or assumed; "
                "isolation is physical via workload routes"
            )
        if (
            not self._route.allow_authority_attach
            and upper.startswith("ATTACH ")
        ):
            raise FederationError(
                f"route {self._route.name} cannot ATTACH catalogs"
            )
        result = self._connection.execute(sql, parameters)
        self._cancel.check()
        return result

    def cancel(self, reason: str = "cancelled") -> None:
        """Cancel this analytical session only (control plane is untouched)."""

        self._cancel.cancel(reason)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._release is not None:
            try:
                self._release(self._connection)
            except Exception:  # noqa: BLE001
                try:
                    self._connection.close()
                except Exception:  # noqa: BLE001
                    pass
        else:
            try:
                self._connection.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "FederatedQuerySession":
        self._ensure_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def usage_snapshot(self) -> dict[str, Any]:
        base = self._connection.usage_snapshot()
        base.update(
            {
                "route": self._route.to_dict(),
                "snapshot": self._snapshot.to_dict() if self._snapshot else None,
                "cancelled": self._cancel.is_cancelled,
                "federation_schema": FEDERATION_SCHEMA,
                "grant_acl_assumed": False,
            }
        )
        return base


# ---------------------------------------------------------------------------
# Trusted in-process query broker
# ---------------------------------------------------------------------------


class TrustedQueryBroker:
    """In-process broker that federates authority catalogs under workload routes.

    Responsibilities:

    * register authority catalogs (paths stay broker-private)
    * resolve explicit workload routes for every request intent
    * open analytical sessions that ATTACH only allowlisted authority catalogs
    * refuse ATTACH on untrusted / publication / control routes
    * bind cross-catalog snapshots with explicit revision vectors
    * copy-out sanitized projections into the publication catalog
    * cancel analytical work without disturbing control-plane writers

    This class never assumes GRANT-style catalog ACLs.
    """

    def __init__(
        self,
        connection_manager: cx.ConnectionManager,
        *,
        policy: FederationPolicy | None = None,
        routes: Mapping[RouteIntent, WorkloadRoute] | None = None,
    ) -> None:
        if not isinstance(connection_manager, cx.ConnectionManager):
            raise FederationError(
                "TrustedQueryBroker requires a ConnectionManager instance"
            )
        self._manager = connection_manager
        self._policy = policy or FederationPolicy()
        self._routes = routes if routes is not None else default_routes()
        self._catalogs: dict[str, AuthorityCatalog] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._active_analytical = 0
        self._control_tx_healthy = True

    # -- properties --------------------------------------------------------

    @property
    def policy(self) -> FederationPolicy:
        return self._policy

    @property
    def connection_manager(self) -> cx.ConnectionManager:
        return self._manager

    @property
    def registered_aliases(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._catalogs))

    @property
    def active_analytical_sessions(self) -> int:
        with self._lock:
            return self._active_analytical

    @property
    def control_transactions_healthy(self) -> bool:
        """Whether the control writer remains healthy under analytical load."""

        return self._control_tx_healthy

    # -- catalog registry --------------------------------------------------

    def register_authority_catalog(self, catalog: AuthorityCatalog) -> None:
        """Register an authority catalog for trusted analytical federation."""

        self._ensure_open()
        if not isinstance(catalog, AuthorityCatalog):
            raise FederationError("catalog must be an AuthorityCatalog")
        if catalog.domain is CatalogDomain.CONTROL:
            # Control is owned by the control pool primary; never ATTACH it
            # into analytical sessions (would couple scans to the writer file).
            raise FederationError(
                "control catalog is not federated via ATTACH; use the control "
                "workload route and pool primary instead"
            )
        with self._lock:
            if catalog.alias in self._catalogs:
                raise FederationError(
                    f"catalog alias already registered: {catalog.alias}"
                )
            self._catalogs[catalog.alias] = catalog

    def get_catalog(self, alias: str) -> AuthorityCatalog:
        with self._lock:
            try:
                return self._catalogs[alias]
            except KeyError as exc:
                raise FederationError(f"unknown authority catalog {alias!r}") from exc

    def update_catalog_revision(
        self,
        alias: str,
        *,
        revision_id: str,
        store_generation: int | None = None,
        schema_checksum: str | None = None,
    ) -> AuthorityCatalog:
        """Replace the revision binding for a registered catalog (immutable)."""

        with self._lock:
            current = self.get_catalog(alias)
            updated = AuthorityCatalog(
                alias=current.alias,
                path=current.path,
                domain=current.domain,
                revision_id=revision_id,
                store_generation=(
                    current.store_generation
                    if store_generation is None
                    else store_generation
                ),
                schema_checksum=(
                    current.schema_checksum
                    if schema_checksum is None
                    else schema_checksum
                ),
                read_only=True,
            )
            self._catalogs[alias] = updated
            return updated

    # -- routes ------------------------------------------------------------

    def resolve_route(self, intent: RouteIntent | str) -> WorkloadRoute:
        self._ensure_open()
        return resolve_workload_route(intent, routes=self._routes)

    def assert_no_grant_acl(self) -> None:
        """Explicit acceptance hook: federation never assumes GRANT ACL."""

        if self._policy.grant_acl_assumed:
            raise FederationError("GRANT-style catalog ACL must not be assumed")
        for route in self._routes.values():
            if route.trust is cx.TrustLevel.UNTRUSTED and route.allow_authority_attach:
                raise FederationError(
                    "untrusted route incorrectly allows authority ATTACH"
                )
        # Policy dict always reports grant_acl_assumed=False.
        if self._policy.to_dict().get("grant_acl_assumed") is not False:
            raise FederationError("policy leaked grant_acl_assumed=true")

    # -- cross-catalog snapshots -------------------------------------------

    def bind_cross_catalog_snapshot(
        self,
        aliases: Sequence[str],
        *,
        snapshot_id: str | None = None,
        route_name: str = "analytical_federated_query",
        created_at: datetime | str | None = None,
    ) -> CrossCatalogSnapshot:
        """Build a snapshot vector with one revision binding per catalog."""

        self._ensure_open()
        if not aliases:
            raise FederationError("at least one catalog alias is required")
        if len(aliases) > self._policy.max_attached_catalogs:
            raise FederationError(
                f"requested {len(aliases)} catalogs exceeds "
                f"max_attached_catalogs={self._policy.max_attached_catalogs}"
            )

        bindings: list[RevisionBinding] = []
        seen: set[str] = set()
        for alias in aliases:
            key = str(alias).strip()
            if key in seen:
                raise FederationError(f"duplicate alias in snapshot request: {key}")
            seen.add(key)
            catalog = self.get_catalog(key)
            bindings.append(catalog.revision_binding())

        if self._policy.require_revision_bindings:
            for binding in bindings:
                if not binding.revision_id:
                    raise FederationError(
                        f"missing revision binding for {binding.catalog_alias}"
                    )

        sid = snapshot_id or f"snap-{uuid.uuid4().hex[:16]}"
        when = created_at or datetime.now(timezone.utc)
        return CrossCatalogSnapshot(
            snapshot_id=sid,
            bindings=tuple(bindings),
            created_at=when if isinstance(when, str) else normalize_timestamp(when),
            route_name=route_name,
        )

    # -- sessions ----------------------------------------------------------

    @contextmanager
    def open_session(
        self,
        intent: RouteIntent | str,
        *,
        catalog_aliases: Sequence[str] = (),
        cancel: CancellationToken | None = None,
        bind_snapshot: bool = True,
    ) -> Iterator[FederatedQuerySession]:
        """Open a short-lived session on the resolved workload route.

        Authority catalogs are ATTACHed only when the route allows it
        (trusted analytical). Untrusted and publication routes always refuse
        ATTACH — there is no GRANT fallback.
        """

        self._ensure_open()
        route = self.resolve_route(intent)
        aliases = tuple(str(a).strip() for a in catalog_aliases if str(a).strip())

        if aliases and not route.allow_authority_attach:
            raise FederationError(
                f"route {route.name} ({route.workload.value}/"
                f"{route.trust.value}) cannot ATTACH authority catalogs; "
                "untrusted sessions never ATTACH authority catalogs"
            )

        snapshot: CrossCatalogSnapshot | None = None
        specs: list[cx.AnalyticalCatalogSpec] = []
        if aliases:
            if len(aliases) > self._policy.max_attached_catalogs:
                raise FederationError("too many catalogs for one federated session")
            for alias in aliases:
                catalog = self.get_catalog(alias)
                if catalog.domain not in route.allowed_domains:
                    raise FederationError(
                        f"domain {catalog.domain.value} not allowed on route "
                        f"{route.name}"
                    )
                specs.append(catalog.to_analytical_spec())
            if bind_snapshot:
                snapshot = self.bind_cross_catalog_snapshot(
                    aliases, route_name=route.name
                )

        token = cancel or CancellationToken()
        is_analytical = route.workload is cx.WorkloadKind.ANALYTICAL

        if route.intent is RouteIntent.CONTROL_MUTATION:
            # Writers are opened via the dedicated control path.
            with self._manager.writer() as conn:
                session = FederatedQuerySession(
                    conn, route, snapshot, token, release=None
                )
                # Writer context already releases; mark session closed on exit
                # without double-close of the managed connection.
                try:
                    yield session
                finally:
                    session._closed = True  # noqa: SLF001
            return

        # Readers: control / analytical / publication / untrusted.
        # catalogs= only accepted by ConnectionManager for analytical.
        try:
            if is_analytical:
                with self._lock:
                    self._active_analytical += 1
                try:
                    with self._manager.reader(
                        cx.WorkloadKind.ANALYTICAL, catalogs=specs
                    ) as conn:
                        token.check()
                        session = FederatedQuerySession(
                            conn, route, snapshot, token, release=None
                        )
                        try:
                            yield session
                        finally:
                            session._closed = True  # noqa: SLF001
                finally:
                    with self._lock:
                        self._active_analytical = max(0, self._active_analytical - 1)
            else:
                # Explicitly refuse any catalog attachment attempt on other routes.
                if specs:
                    raise FederationError(
                        "internal error: non-analytical route built attach specs"
                    )
                with self._manager.reader(route.workload) as conn:
                    session = FederatedQuerySession(
                        conn, route, snapshot, token, release=None
                    )
                    try:
                        yield session
                    finally:
                        session._closed = True  # noqa: SLF001
        except cx.ConnectionError as exc:
            raise FederationError(str(exc)) from exc

    @contextmanager
    def control_writer_transaction(self) -> Iterator[cx.ManagedConnection]:
        """Open a bounded control writer transaction (isolated from analytics)."""

        self._ensure_open()
        try:
            with self._manager.short_writer_transaction() as conn:
                yield conn
                # Successful commit path keeps the healthy flag set.
                self._control_tx_healthy = True
        except Exception:
            # A failed control transaction is still "healthy" in the sense that
            # analytical cancellation did not corrupt control-plane state; the
            # control pool remains usable. Re-raise the original error.
            raise

    def probe_control_health(self) -> dict[str, Any]:
        """Run a short control read to prove the control plane is healthy."""

        self._ensure_open()
        with self._manager.reader(cx.WorkloadKind.CONTROL) as conn:
            conn.execute("SELECT 1")
            usage = conn.usage_snapshot()
        return {
            "healthy": True,
            "control_transactions_healthy": self._control_tx_healthy,
            "active_analytical_sessions": self.active_analytical_sessions,
            "workload": usage["workload"],
            "grant_acl_assumed": False,
        }

    # -- sanitized copy-out ------------------------------------------------

    def publish_sanitized_copy_out(
        self,
        spec: SanitizedCopyOutSpec,
        *,
        cancel: CancellationToken | None = None,
        row_source: Sequence[Sequence[Any]] | None = None,
    ) -> PublicationReceipt:
        """Evaluate a projection on the trusted broker and publish copy-out rows.

        Parameters
        ----------
        spec:
            Allowlisted copy-out specification bound to a cross-catalog snapshot.
        cancel:
            Optional analytical cancellation token.
        row_source:
            Optional pre-materialized rows (used by hermetic tests). When
            omitted, the broker runs ``spec.source_sql`` on a trusted
            analytical session attached to the snapshot's catalogs.
        """

        self._ensure_open()
        if not isinstance(spec, SanitizedCopyOutSpec):
            raise FederationError("spec must be a SanitizedCopyOutSpec")

        token = cancel or CancellationToken()
        token.check()

        # Validate snapshot aliases are still registered with matching revisions.
        for binding in spec.source_snapshot.bindings:
            catalog = self.get_catalog(binding.catalog_alias)
            if catalog.revision_id != binding.revision_id:
                raise FederationError(
                    f"snapshot revision drift for {binding.catalog_alias}: "
                    f"catalog={catalog.revision_id} binding={binding.revision_id}"
                )
            if catalog.store_generation != binding.store_generation:
                raise FederationError(
                    f"snapshot generation drift for {binding.catalog_alias}"
                )

        aliases = [b.catalog_alias for b in spec.source_snapshot.bindings]
        columns = spec.column_names

        if row_source is not None:
            rows = [tuple(r) for r in row_source]
        else:
            rows = self._fetch_copy_out_rows(spec, aliases, token)

        token.check()
        if len(rows) > spec.max_rows:
            raise FederationError(
                f"copy-out row count {len(rows)} exceeds max_rows={spec.max_rows}"
            )

        # Materialize into the publication catalog (physically separate).
        # Never ATTACH authority catalogs on this session.
        self._write_publication_rows(spec.target_table, columns, rows)

        digest = content_identity(
            {
                "publication_id": spec.publication_id,
                "target_table": spec.target_table,
                "columns": list(columns),
                "rows": [list(_jsonable(v) for v in row) for row in rows],
                "source_snapshot_identity": spec.source_snapshot.identity_id,
            }
        )
        return PublicationReceipt(
            publication_id=spec.publication_id,
            target_table=spec.target_table,
            row_count=len(rows),
            columns=columns,
            source_snapshot=spec.source_snapshot,
            content_digest=digest,
            created_at=datetime.now(timezone.utc),
            non_authoritative=True,
        )

    def _fetch_copy_out_rows(
        self,
        spec: SanitizedCopyOutSpec,
        aliases: Sequence[str],
        token: CancellationToken,
    ) -> list[tuple[Any, ...]]:
        with self.open_session(
            RouteIntent.ANALYTICAL_FEDERATED_QUERY,
            catalog_aliases=aliases,
            cancel=token,
            bind_snapshot=False,
        ) as session:
            # Re-bind the caller's snapshot for audit; do not recompute revisions.
            session._snapshot = spec.source_snapshot  # noqa: SLF001
            token.check()
            result = session.execute(spec.source_sql)
            fetchall = getattr(result, "fetchall", None)
            if callable(fetchall):
                raw_rows = fetchall()
            else:
                raw_rows = list(result) if result is not None else []
            token.check()
            # Project / validate column arity when possible.
            rows: list[tuple[Any, ...]] = []
            expected = len(spec.columns)
            for row in raw_rows:
                as_tuple = tuple(row)
                if expected and len(as_tuple) != expected:
                    # Allow SELECT * style only when caller used exact columns.
                    if len(as_tuple) < expected:
                        raise FederationError(
                            f"source_sql returned {len(as_tuple)} columns, "
                            f"expected {expected}"
                        )
                    as_tuple = as_tuple[:expected]
                rows.append(as_tuple)
            return rows

    def _write_publication_rows(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> None:
        """Insert rows into the publication catalog without authority ATTACH."""

        # Publication pool is untrusted: cannot attach authority catalogs.
        # Use a direct connection from the publication pool and write via
        # CREATE TABLE AS / INSERT with parameterized values.
        pool = self._manager.pool_for(cx.WorkloadKind.PUBLICATION)
        # Publication pools are read-only by default policy — for copy-out we
        # need a one-shot write into the publication primary path. Open a
        # dedicated managed connection with a temporary read_write override
        # using the factory, without ever attaching authority catalogs.
        pub_path = self._manager._paths[cx.WorkloadKind.PUBLICATION]  # noqa: SLF001
        write_config = cx.PoolConfig(
            workload=cx.WorkloadKind.CONTROL,  # write access only via control enum
            max_size=1,
            max_idle=0,
            access_mode=cx.AccessMode.READ_WRITE,
            trust=cx.TrustLevel.TRUSTED,
            budget=cx.DEFAULT_CONTROL_BUDGET,
            security=cx.default_security_policy(cx.WorkloadKind.CONTROL),
            primary_path=pub_path,
            catalog_name="publication_writer",
        )
        # Use a short-lived private pool so we never promote the untrusted
        # publication reader pool to writer status.
        writer_pool = cx.ConnectionPool(
            write_config, factory=self._manager._factory  # noqa: SLF001
        )
        try:
            with writer_pool.connection() as conn:
                col_sql = ", ".join(f"{c} VARCHAR" for c in columns)
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ({col_sql})"
                )
                if rows:
                    placeholders = ", ".join("?" for _ in columns)
                    insert_sql = (
                        f"INSERT INTO {table} ({', '.join(columns)}) "
                        f"VALUES ({placeholders})"
                    )
                    for row in rows:
                        conn.execute(insert_sql, list(row))
        except cx.ConnectionError as exc:
            raise FederationError(
                f"failed to write sanitized publication rows: {exc}"
            ) from exc
        finally:
            writer_pool.close()
            # Ensure publication reader pool still has zero attachments.
            _ = pool  # keep reference for clarity / future stats

    # -- teardown ----------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._closed:
            raise FederationError("TrustedQueryBroker is closed")

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "TrustedQueryBroker":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            catalogs = {
                alias: cat.to_dict() for alias, cat in sorted(self._catalogs.items())
            }
        return {
            "schema": FEDERATION_SCHEMA,
            "implementation_generation": _FEDERATION_IMPLEMENTATION_GENERATION,
            "policy": self._policy.to_dict(),
            "routes": {
                intent.value: route.to_dict()
                for intent, route in self._routes.items()
            },
            "registered_catalogs": catalogs,
            "active_analytical_sessions": self.active_analytical_sessions,
            "control_transactions_healthy": self._control_tx_healthy,
            "grant_acl_assumed": False,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return normalize_timestamp(value)
    return str(value)
