"""Allowlisted wallet / proof / AST cross-domain queries (DQK-039).

Provides a closed set of parameterized query templates that join:

* wallet **transactions** and **contracts** (DQK-035/036 ledger surface)
* AST **source symbols** (DQK-031/033)
* crypto-flow **graph** nodes/edges (DQK-038)
* formal **verification evidence** (DQK-025/029)

Design invariants (acceptance for DQK-039 / DQK-G700):

* Private keys, seeds, mnemonics, and signing payloads are **rejected** on
  every parameter surface and every result row (secret scanning).
* Every query-visible row exposes **authority** and **finality** columns.
* Cross-domain joins obey **tenant** isolation and **resource budgets**
  (row / time / domain / parameter-byte limits).
* Callers never submit arbitrary SQL; only versioned allowlisted templates
  execute against an in-process join plane.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Final

from .duckdb_schema import (
    ColumnDataClass,
    FORBIDDEN_QUERY_CLASSES,
    QUERY_VISIBLE_CLASSES,
    _FORBIDDEN_QUERY_VISIBLE_NAME_FRAGMENTS,
)
from .models import Finality, ensure_secret_safe

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_WALLET_QUERIES_INTERFACE: Final[str] = "WalletDuckDBQueries@1"
DUCKDB_WALLET_QUERIES_SCHEMA: Final[str] = (
    "ipfs_datasets_py/processors-wallets-duckdb-queries@1"
)
SCHEMA_VERSION: Final[int] = 1

# Domain stamps for join results (stable, never elevatable by callers).
DOMAIN_TRANSACTIONS: Final[str] = "wallet.transactions"
DOMAIN_CONTRACTS: Final[str] = "wallet.contracts"
DOMAIN_SOURCE_SYMBOLS: Final[str] = "ast.source_symbols"
DOMAIN_GRAPH_FLOWS: Final[str] = "crypto_flows.graph"
DOMAIN_VERIFICATION: Final[str] = "proofs.verification_evidence"

ALL_JOIN_DOMAINS: Final[tuple[str, ...]] = (
    DOMAIN_TRANSACTIONS,
    DOMAIN_CONTRACTS,
    DOMAIN_SOURCE_SYMBOLS,
    DOMAIN_GRAPH_FLOWS,
    DOMAIN_VERIFICATION,
)

# Required projection columns on every query-visible result row.
REQUIRED_RESULT_COLUMNS: Final[tuple[str, ...]] = (
    "tenant_id",
    "authority",
    "finality",
)

# Additional secret / signing surface fragments beyond schema name fragments.
_SIGNING_PAYLOAD_FRAGMENTS: Final[tuple[str, ...]] = (
    "signing_payload",
    "signed_payload",
    "signed_tx",
    "signed_transaction",
    "raw_signed",
    "signature_payload",
    "tx_blob",
    "serialized_tx",
    "private_key",
    "seed_phrase",
    "mnemonic",
    "wallet_seed",
    "recovery_phrase",
    "signing_key",
    "signing_material",
)

_SECRET_NAME_FRAGMENTS: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(
        (*_FORBIDDEN_QUERY_VISIBLE_NAME_FRAGMENTS, *_SIGNING_PAYLOAD_FRAGMENTS)
    )
)

# Authority vocabulary for wallet-side observation facts (closed, non-elevating).
class QueryAuthority(StrEnum):
    """Authority level exposed on query rows (never caller-elevatable)."""

    OBSERVATION = "observation"
    EVIDENCE = "evidence"
    ATTESTATION = "attestation"
    CANDIDATE = "candidate"
    NONE = "none"


class QueryTemplateId(StrEnum):
    """Closed allowlist of cross-domain query templates."""

    TRANSACTIONS_BY_TENANT = "transactions_by_tenant"
    TRANSACTION_CONTRACTS = "transaction_contracts"
    TRANSACTION_GRAPH_FLOWS = "transaction_graph_flows"
    TRANSACTION_SOURCE_SYMBOLS = "transaction_source_symbols"
    TRANSACTION_VERIFICATION = "transaction_verification"
    CROSS_DOMAIN_JOIN = "cross_domain_join"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WalletQueryError(ValueError):
    """Raised when an allowlisted wallet query fails closed."""


class SecretSurfaceRejected(WalletQueryError):
    """Raised when private keys, seeds, or signing payloads appear on a surface."""

    def __init__(self, message: str = "secret or signing surface rejected") -> None:
        super().__init__(message)
        self.reason_code = "wallet.query.secret_surface_rejected"


class QueryBudgetExceeded(WalletQueryError):
    """Raised when a query exhausts a resource budget."""

    def __init__(self, kind: str, limit: int | float) -> None:
        super().__init__(f"query budget exceeded: {kind} limit={limit}")
        self.kind = kind
        self.limit = limit
        self.reason_code = "wallet.query.budget_exceeded"


class TenantPolicyViolation(WalletQueryError):
    """Raised when a row or parameter violates tenant isolation policy."""

    def __init__(self, message: str = "tenant policy violation") -> None:
        super().__init__(message)
        self.reason_code = "wallet.query.tenant_policy_violation"


class UnknownQueryTemplateError(WalletQueryError):
    """Raised when a template id is not on the allowlist."""

    def __init__(self, template_id: str) -> None:
        super().__init__(f"query template not allowlisted: {template_id!r}")
        self.template_id = template_id
        self.reason_code = "wallet.query.unknown_template"


class ColumnPolicyError(WalletQueryError):
    """Raised when a result column fails classification or visibility policy."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.reason_code = "wallet.query.column_policy"


# ---------------------------------------------------------------------------
# Budgets and tenant policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryBudget:
    """Resource limits for allowlisted wallet queries.

    Cross-domain joins must not grow unboundedly across tenants or domains.
    """

    max_rows: int = 1_000
    max_seconds: float = 2.0
    max_join_domains: int = len(ALL_JOIN_DOMAINS)
    max_parameter_bytes: int = 65_536

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_rows, bool)
            or not isinstance(self.max_rows, int)
            or self.max_rows < 1
        ):
            raise WalletQueryError("max_rows must be a positive integer")
        if (
            isinstance(self.max_seconds, bool)
            or not isinstance(self.max_seconds, (int, float))
            or self.max_seconds <= 0
        ):
            raise WalletQueryError("max_seconds must be a positive number")
        if (
            isinstance(self.max_join_domains, bool)
            or not isinstance(self.max_join_domains, int)
            or self.max_join_domains < 1
        ):
            raise WalletQueryError("max_join_domains must be a positive integer")
        if (
            isinstance(self.max_parameter_bytes, bool)
            or not isinstance(self.max_parameter_bytes, int)
            or self.max_parameter_bytes < 1
        ):
            raise WalletQueryError("max_parameter_bytes must be a positive integer")


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    """Row-level tenant isolation for cross-domain wallet joins.

    Every fact and every result row must match ``tenant_id``.  Optional chain
    and source allowlists further restrict ledger-bound rows.
    """

    tenant_id: str
    allowed_chain_ref_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_source_ids: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise WalletQueryError("tenant_id must be a non-empty string")
        object.__setattr__(self, "tenant_id", self.tenant_id.strip())
        chains = frozenset(
            str(c).strip()
            for c in self.allowed_chain_ref_ids
            if str(c).strip()
        )
        sources = frozenset(
            str(s).strip() for s in self.allowed_source_ids if str(s).strip()
        )
        object.__setattr__(self, "allowed_chain_ref_ids", chains)
        object.__setattr__(self, "allowed_source_ids", sources)

    def permits_tenant(self, tenant_id: str) -> bool:
        return isinstance(tenant_id, str) and tenant_id.strip() == self.tenant_id

    def permits_chain(self, chain_ref_id: str | None) -> bool:
        if not self.allowed_chain_ref_ids:
            return True
        if chain_ref_id is None or not str(chain_ref_id).strip():
            return False
        return str(chain_ref_id).strip() in self.allowed_chain_ref_ids

    def permits_source(self, source_id: str | None) -> bool:
        if not self.allowed_source_ids:
            return True
        if source_id is None or not str(source_id).strip():
            return False
        return str(source_id).strip() in self.allowed_source_ids

    def enforce_row(self, row: Mapping[str, Any], *, surface: str) -> None:
        tenant = row.get("tenant_id")
        if not self.permits_tenant(str(tenant) if tenant is not None else ""):
            raise TenantPolicyViolation(
                f"{surface} row tenant does not match policy tenant_id"
            )
        chain = row.get("chain_ref_id")
        if chain is not None and not self.permits_chain(str(chain)):
            raise TenantPolicyViolation(
                f"{surface} row chain_ref_id not allowed by tenant policy"
            )
        source = row.get("source_id")
        if source is not None and not self.permits_source(str(source)):
            raise TenantPolicyViolation(
                f"{surface} row source_id not allowed by tenant policy"
            )


# ---------------------------------------------------------------------------
# Secret scanning and column classification
# ---------------------------------------------------------------------------


def _normalized_key(name: str) -> str:
    return (
        name.replace("-", "_")
        .replace(" ", "_")
        .replace(".", "_")
        .casefold()
        .strip("_")
    )


def _key_matches_secret_fragment(name: str) -> bool:
    normalized = _normalized_key(name)
    for fragment in _SECRET_NAME_FRAGMENTS:
        frag = fragment.casefold()
        if frag in normalized:
            return True
    return False


def scan_secret_surface(value: Any, *, surface: str = "query") -> None:
    """Reject private keys, seeds, signing payloads, and secret-shaped values.

    Combines field-name fragment checks with :func:`ensure_secret_safe` so both
    structured keys and concrete secret values fail closed without echoing
    attacker-controlled content in errors.
    """

    def walk(item: Any, depth: int) -> None:
        if depth > 32:
            raise SecretSurfaceRejected(f"{surface}: nesting limit exceeded")
        if isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(key, str) and _key_matches_secret_fragment(key):
                    raise SecretSurfaceRejected(
                        f"{surface}: forbidden secret/signing field rejected"
                    )
                walk(child, depth + 1)
            return
        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray, memoryview)
        ):
            for child in item:
                walk(child, depth + 1)
            return
        to_dict = getattr(item, "to_dict", None)
        if callable(to_dict):
            walk(to_dict(), depth + 1)

    try:
        walk(value, 0)
        ensure_secret_safe(value)
    except SecretSurfaceRejected:
        raise
    except ValueError as exc:
        text = str(exc).casefold()
        if "secret" in text or "security policy" in text:
            raise SecretSurfaceRejected(
                f"{surface}: secret-shaped value rejected"
            ) from None
        raise WalletQueryError(f"{surface}: invalid value") from None


def classify_result_columns(
    columns: Sequence[str],
    *,
    classifications: Mapping[str, ColumnDataClass],
) -> Mapping[str, ColumnDataClass]:
    """Validate that every result column is classified and query-visible."""

    out: dict[str, ColumnDataClass] = {}
    for name in columns:
        if not isinstance(name, str) or not name.strip():
            raise ColumnPolicyError("result column names must be non-empty strings")
        if _key_matches_secret_fragment(name):
            raise ColumnPolicyError(
                f"result column {name!r} matches secret/signing fragment"
            )
        if name not in classifications:
            raise ColumnPolicyError(f"result column {name!r} lacks classification")
        klass = classifications[name]
        if not isinstance(klass, ColumnDataClass):
            raise ColumnPolicyError(f"result column {name!r} has invalid classification")
        if klass in FORBIDDEN_QUERY_CLASSES:
            raise ColumnPolicyError(
                f"result column {name!r} classified as {klass.value}; "
                "forbidden on query-visible surface"
            )
        if klass not in QUERY_VISIBLE_CLASSES:
            raise ColumnPolicyError(
                f"result column {name!r} has non-visible classification {klass!r}"
            )
        out[name] = klass
    return MappingProxyType(out)


def _parameter_byte_size(params: Mapping[str, Any]) -> int:
    """Conservative UTF-8 size estimate for parameter budget enforcement."""

    total = 0

    def visit(item: Any) -> None:
        nonlocal total
        if isinstance(item, str):
            total += len(item.encode("utf-8", errors="replace"))
        elif isinstance(item, (bytes, bytearray, memoryview)):
            total += len(item)
        elif isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(key, str):
                    total += len(key.encode("utf-8", errors="replace"))
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for child in item:
                visit(child)
        elif item is None or isinstance(item, (bool, int, float)):
            total += 8
        else:
            total += len(repr(item).encode("utf-8", errors="replace"))

    visit(params)
    return total


# ---------------------------------------------------------------------------
# Domain facts (join plane)
# ---------------------------------------------------------------------------


def _require_nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WalletQueryError(f"{name} must be a non-empty string")
    return value.strip()


def _require_finality(value: Finality | str) -> str:
    if isinstance(value, Finality):
        return value.value
    text = _require_nonempty(str(value), "finality")
    try:
        return Finality(text).value
    except ValueError as exc:
        raise WalletQueryError(f"unknown finality value: {text!r}") from exc


def _require_authority(value: QueryAuthority | str) -> str:
    if isinstance(value, QueryAuthority):
        return value.value
    text = _require_nonempty(str(value), "authority")
    try:
        return QueryAuthority(text).value
    except ValueError as exc:
        raise WalletQueryError(f"unknown authority value: {text!r}") from exc


@dataclass(frozen=True, slots=True)
class TransactionFact:
    """Query-visible wallet transaction fact with authority and finality."""

    tenant_id: str
    record_id: str
    transaction_hash: str
    chain_ref_id: str
    source_id: str
    finality: str
    authority: str = QueryAuthority.OBSERVATION.value
    contract_account_id: str = ""
    status: str = "succeeded"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _require_nonempty(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "record_id", _require_nonempty(self.record_id, "record_id"))
        object.__setattr__(
            self,
            "transaction_hash",
            _require_nonempty(self.transaction_hash, "transaction_hash"),
        )
        object.__setattr__(
            self, "chain_ref_id", _require_nonempty(self.chain_ref_id, "chain_ref_id")
        )
        object.__setattr__(self, "source_id", _require_nonempty(self.source_id, "source_id"))
        object.__setattr__(self, "finality", _require_finality(self.finality))
        object.__setattr__(self, "authority", _require_authority(self.authority))
        object.__setattr__(
            self,
            "contract_account_id",
            self.contract_account_id.strip()
            if isinstance(self.contract_account_id, str)
            else "",
        )
        object.__setattr__(
            self,
            "status",
            self.status.strip() if isinstance(self.status, str) else "succeeded",
        )
        attrs = MappingProxyType(dict(self.attributes or {}))
        object.__setattr__(self, "attributes", attrs)
        scan_secret_surface(self.to_dict(), surface="TransactionFact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "chain_ref_id": self.chain_ref_id,
            "contract_account_id": self.contract_account_id,
            "domain": DOMAIN_TRANSACTIONS,
            "finality": self.finality,
            "record_id": self.record_id,
            "source_id": self.source_id,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "transaction_hash": self.transaction_hash,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class ContractFact:
    """Query-visible contract / contract-event fact with authority and finality."""

    tenant_id: str
    contract_account_id: str
    chain_ref_id: str
    source_id: str
    finality: str
    transaction_hash: str = ""
    event_signature: str = ""
    authority: str = QueryAuthority.OBSERVATION.value
    symbol_link: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _require_nonempty(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self,
            "contract_account_id",
            _require_nonempty(self.contract_account_id, "contract_account_id"),
        )
        object.__setattr__(
            self, "chain_ref_id", _require_nonempty(self.chain_ref_id, "chain_ref_id")
        )
        object.__setattr__(self, "source_id", _require_nonempty(self.source_id, "source_id"))
        object.__setattr__(self, "finality", _require_finality(self.finality))
        object.__setattr__(self, "authority", _require_authority(self.authority))
        object.__setattr__(
            self,
            "transaction_hash",
            self.transaction_hash.strip()
            if isinstance(self.transaction_hash, str)
            else "",
        )
        object.__setattr__(
            self,
            "event_signature",
            self.event_signature.strip()
            if isinstance(self.event_signature, str)
            else "",
        )
        object.__setattr__(
            self,
            "symbol_link",
            self.symbol_link.strip() if isinstance(self.symbol_link, str) else "",
        )
        attrs = MappingProxyType(dict(self.attributes or {}))
        object.__setattr__(self, "attributes", attrs)
        scan_secret_surface(self.to_dict(), surface="ContractFact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "chain_ref_id": self.chain_ref_id,
            "contract_account_id": self.contract_account_id,
            "domain": DOMAIN_CONTRACTS,
            "event_signature": self.event_signature,
            "finality": self.finality,
            "source_id": self.source_id,
            "symbol_link": self.symbol_link,
            "tenant_id": self.tenant_id,
            "transaction_hash": self.transaction_hash,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class SourceSymbolFact:
    """AST source-symbol fact bound to a source revision (DQK-033 surface)."""

    tenant_id: str
    symbol_id: str
    qualified_name: str
    source_revision: str
    finality: str = Finality.FINALIZED.value
    authority: str = QueryAuthority.EVIDENCE.value
    contract_account_id: str = ""
    file_path: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _require_nonempty(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "symbol_id", _require_nonempty(self.symbol_id, "symbol_id"))
        object.__setattr__(
            self,
            "qualified_name",
            _require_nonempty(self.qualified_name, "qualified_name"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _require_nonempty(self.source_revision, "source_revision"),
        )
        object.__setattr__(self, "finality", _require_finality(self.finality))
        object.__setattr__(self, "authority", _require_authority(self.authority))
        object.__setattr__(
            self,
            "contract_account_id",
            self.contract_account_id.strip()
            if isinstance(self.contract_account_id, str)
            else "",
        )
        object.__setattr__(
            self,
            "file_path",
            self.file_path.strip() if isinstance(self.file_path, str) else "",
        )
        attrs = MappingProxyType(dict(self.attributes or {}))
        object.__setattr__(self, "attributes", attrs)
        scan_secret_surface(self.to_dict(), surface="SourceSymbolFact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "contract_account_id": self.contract_account_id,
            "domain": DOMAIN_SOURCE_SYMBOLS,
            "file_path": self.file_path,
            "finality": self.finality,
            "qualified_name": self.qualified_name,
            "source_revision": self.source_revision,
            "symbol_id": self.symbol_id,
            "tenant_id": self.tenant_id,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class GraphFlowFact:
    """Crypto-flow graph node/edge projection fact (DQK-038 surface)."""

    tenant_id: str
    node_or_edge_id: str
    kind: str
    plane: str
    finality: str
    authority: str = QueryAuthority.OBSERVATION.value
    transaction_hash: str = ""
    chain_ref_id: str = ""
    graph_revision: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _require_nonempty(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self,
            "node_or_edge_id",
            _require_nonempty(self.node_or_edge_id, "node_or_edge_id"),
        )
        object.__setattr__(self, "kind", _require_nonempty(self.kind, "kind"))
        object.__setattr__(self, "plane", _require_nonempty(self.plane, "plane"))
        object.__setattr__(self, "finality", _require_finality(self.finality))
        object.__setattr__(self, "authority", _require_authority(self.authority))
        object.__setattr__(
            self,
            "transaction_hash",
            self.transaction_hash.strip()
            if isinstance(self.transaction_hash, str)
            else "",
        )
        object.__setattr__(
            self,
            "chain_ref_id",
            self.chain_ref_id.strip() if isinstance(self.chain_ref_id, str) else "",
        )
        object.__setattr__(
            self,
            "graph_revision",
            self.graph_revision.strip() if isinstance(self.graph_revision, str) else "",
        )
        attrs = MappingProxyType(dict(self.attributes or {}))
        object.__setattr__(self, "attributes", attrs)
        scan_secret_surface(self.to_dict(), surface="GraphFlowFact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "chain_ref_id": self.chain_ref_id,
            "domain": DOMAIN_GRAPH_FLOWS,
            "finality": self.finality,
            "graph_revision": self.graph_revision,
            "kind": self.kind,
            "node_or_edge_id": self.node_or_edge_id,
            "plane": self.plane,
            "tenant_id": self.tenant_id,
            "transaction_hash": self.transaction_hash,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class VerificationEvidenceFact:
    """Formal verification evidence fact (DQK-029 surface)."""

    tenant_id: str
    evidence_id: str
    evidence_kind: str
    authority: str
    finality: str = Finality.FINALIZED.value
    subject_ref: str = ""
    transaction_hash: str = ""
    contract_account_id: str = ""
    content_digest: str = ""
    trust_level: str = "none"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _require_nonempty(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self, "evidence_id", _require_nonempty(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "evidence_kind", _require_nonempty(self.evidence_kind, "evidence_kind")
        )
        object.__setattr__(self, "authority", _require_authority(self.authority))
        object.__setattr__(self, "finality", _require_finality(self.finality))
        object.__setattr__(
            self,
            "subject_ref",
            self.subject_ref.strip() if isinstance(self.subject_ref, str) else "",
        )
        object.__setattr__(
            self,
            "transaction_hash",
            self.transaction_hash.strip()
            if isinstance(self.transaction_hash, str)
            else "",
        )
        object.__setattr__(
            self,
            "contract_account_id",
            self.contract_account_id.strip()
            if isinstance(self.contract_account_id, str)
            else "",
        )
        object.__setattr__(
            self,
            "content_digest",
            self.content_digest.strip() if isinstance(self.content_digest, str) else "",
        )
        object.__setattr__(
            self,
            "trust_level",
            self.trust_level.strip() if isinstance(self.trust_level, str) else "none",
        )
        attrs = MappingProxyType(dict(self.attributes or {}))
        object.__setattr__(self, "attributes", attrs)
        scan_secret_surface(self.to_dict(), surface="VerificationEvidenceFact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "content_digest": self.content_digest,
            "contract_account_id": self.contract_account_id,
            "domain": DOMAIN_VERIFICATION,
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "finality": self.finality,
            "subject_ref": self.subject_ref,
            "tenant_id": self.tenant_id,
            "transaction_hash": self.transaction_hash,
            "trust_level": self.trust_level,
            "attributes": dict(self.attributes),
        }


# ---------------------------------------------------------------------------
# Join plane
# ---------------------------------------------------------------------------


@dataclass
class WalletJoinPlane:
    """In-memory cross-domain join plane for hermetic fixtures and brokers.

    Populated from wallet ledger rows, AST symbols, crypto-flow projections,
    and verification evidence.  Does not open DuckDB itself.
    """

    transactions: list[TransactionFact] = field(default_factory=list)
    contracts: list[ContractFact] = field(default_factory=list)
    source_symbols: list[SourceSymbolFact] = field(default_factory=list)
    graph_flows: list[GraphFlowFact] = field(default_factory=list)
    verification_evidence: list[VerificationEvidenceFact] = field(default_factory=list)

    def add_transaction(self, fact: TransactionFact) -> None:
        if not isinstance(fact, TransactionFact):
            raise WalletQueryError("fact must be TransactionFact")
        self.transactions.append(fact)

    def add_contract(self, fact: ContractFact) -> None:
        if not isinstance(fact, ContractFact):
            raise WalletQueryError("fact must be ContractFact")
        self.contracts.append(fact)

    def add_source_symbol(self, fact: SourceSymbolFact) -> None:
        if not isinstance(fact, SourceSymbolFact):
            raise WalletQueryError("fact must be SourceSymbolFact")
        self.source_symbols.append(fact)

    def add_graph_flow(self, fact: GraphFlowFact) -> None:
        if not isinstance(fact, GraphFlowFact):
            raise WalletQueryError("fact must be GraphFlowFact")
        self.graph_flows.append(fact)

    def add_verification_evidence(self, fact: VerificationEvidenceFact) -> None:
        if not isinstance(fact, VerificationEvidenceFact):
            raise WalletQueryError("fact must be VerificationEvidenceFact")
        self.verification_evidence.append(fact)

    def domain_counts(self) -> dict[str, int]:
        return {
            DOMAIN_TRANSACTIONS: len(self.transactions),
            DOMAIN_CONTRACTS: len(self.contracts),
            DOMAIN_SOURCE_SYMBOLS: len(self.source_symbols),
            DOMAIN_GRAPH_FLOWS: len(self.graph_flows),
            DOMAIN_VERIFICATION: len(self.verification_evidence),
        }


# ---------------------------------------------------------------------------
# Template registry and result classification
# ---------------------------------------------------------------------------

_PUBLIC = ColumnDataClass.PUBLIC
_CONTENT_REF = ColumnDataClass.CONTENT_REF


def _base_result_classifications() -> dict[str, ColumnDataClass]:
    return {
        "tenant_id": _PUBLIC,
        "authority": _PUBLIC,
        "finality": _PUBLIC,
        "domain": _PUBLIC,
        "domains": _PUBLIC,
        "transaction_hash": _PUBLIC,
        "record_id": _PUBLIC,
        "chain_ref_id": _PUBLIC,
        "source_id": _PUBLIC,
        "contract_account_id": _PUBLIC,
        "status": _PUBLIC,
        "event_signature": _PUBLIC,
        "symbol_id": _PUBLIC,
        "qualified_name": _PUBLIC,
        "source_revision": _PUBLIC,
        "file_path": _PUBLIC,
        "node_or_edge_id": _PUBLIC,
        "kind": _PUBLIC,
        "plane": _PUBLIC,
        "graph_revision": _PUBLIC,
        "evidence_id": _PUBLIC,
        "evidence_kind": _PUBLIC,
        "subject_ref": _PUBLIC,
        "content_digest": _CONTENT_REF,
        "trust_level": _PUBLIC,
        "join_key": _PUBLIC,
    }


TEMPLATE_RESULT_CLASSIFICATIONS: Final[Mapping[str, Mapping[str, ColumnDataClass]]] = (
    MappingProxyType(
        {
            QueryTemplateId.TRANSACTIONS_BY_TENANT.value: MappingProxyType(
                {
                    **_base_result_classifications(),
                }
            ),
            QueryTemplateId.TRANSACTION_CONTRACTS.value: MappingProxyType(
                {
                    **_base_result_classifications(),
                }
            ),
            QueryTemplateId.TRANSACTION_GRAPH_FLOWS.value: MappingProxyType(
                {
                    **_base_result_classifications(),
                }
            ),
            QueryTemplateId.TRANSACTION_SOURCE_SYMBOLS.value: MappingProxyType(
                {
                    **_base_result_classifications(),
                }
            ),
            QueryTemplateId.TRANSACTION_VERIFICATION.value: MappingProxyType(
                {
                    **_base_result_classifications(),
                }
            ),
            QueryTemplateId.CROSS_DOMAIN_JOIN.value: MappingProxyType(
                {
                    **_base_result_classifications(),
                }
            ),
        }
    )
)

TEMPLATE_DOMAINS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        QueryTemplateId.TRANSACTIONS_BY_TENANT.value: (DOMAIN_TRANSACTIONS,),
        QueryTemplateId.TRANSACTION_CONTRACTS.value: (
            DOMAIN_TRANSACTIONS,
            DOMAIN_CONTRACTS,
        ),
        QueryTemplateId.TRANSACTION_GRAPH_FLOWS.value: (
            DOMAIN_TRANSACTIONS,
            DOMAIN_GRAPH_FLOWS,
        ),
        QueryTemplateId.TRANSACTION_SOURCE_SYMBOLS.value: (
            DOMAIN_TRANSACTIONS,
            DOMAIN_CONTRACTS,
            DOMAIN_SOURCE_SYMBOLS,
        ),
        QueryTemplateId.TRANSACTION_VERIFICATION.value: (
            DOMAIN_TRANSACTIONS,
            DOMAIN_CONTRACTS,
            DOMAIN_VERIFICATION,
        ),
        QueryTemplateId.CROSS_DOMAIN_JOIN.value: ALL_JOIN_DOMAINS,
    }
)

# Allowed parameter keys per template (closed; unknown keys rejected).
TEMPLATE_PARAMETER_KEYS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        QueryTemplateId.TRANSACTIONS_BY_TENANT.value: frozenset(
            {"transaction_hash", "chain_ref_id", "min_finality"}
        ),
        QueryTemplateId.TRANSACTION_CONTRACTS.value: frozenset(
            {"transaction_hash", "contract_account_id", "chain_ref_id"}
        ),
        QueryTemplateId.TRANSACTION_GRAPH_FLOWS.value: frozenset(
            {"transaction_hash", "plane", "graph_revision"}
        ),
        QueryTemplateId.TRANSACTION_SOURCE_SYMBOLS.value: frozenset(
            {
                "transaction_hash",
                "contract_account_id",
                "symbol_id",
                "source_revision",
            }
        ),
        QueryTemplateId.TRANSACTION_VERIFICATION.value: frozenset(
            {
                "transaction_hash",
                "contract_account_id",
                "evidence_id",
                "min_authority",
            }
        ),
        QueryTemplateId.CROSS_DOMAIN_JOIN.value: frozenset(
            {
                "transaction_hash",
                "contract_account_id",
                "symbol_id",
                "source_revision",
                "plane",
                "evidence_id",
            }
        ),
    }
)


def list_allowlisted_templates() -> tuple[str, ...]:
    """Return the closed, ordered allowlist of query template ids."""

    return tuple(t.value for t in QueryTemplateId)


def resolve_template_id(template_id: str | QueryTemplateId) -> str:
    """Resolve and validate a template id against the allowlist."""

    if isinstance(template_id, QueryTemplateId):
        return template_id.value
    if not isinstance(template_id, str) or not template_id.strip():
        raise UnknownQueryTemplateError(str(template_id))
    text = template_id.strip()
    try:
        return QueryTemplateId(text).value
    except ValueError as exc:
        raise UnknownQueryTemplateError(text) from exc


# ---------------------------------------------------------------------------
# Query result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Deterministic receipt for one allowlisted query execution."""

    template_id: str
    tenant_id: str
    domains: tuple[str, ...]
    columns: tuple[str, ...]
    column_classifications: Mapping[str, str]
    rows: tuple[Mapping[str, Any], ...]
    row_count: int
    truncated: bool
    budget: Mapping[str, Any]
    schema: str = DUCKDB_WALLET_QUERIES_SCHEMA
    interface: str = DUCKDB_WALLET_QUERIES_INTERFACE

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": dict(self.budget),
            "column_classifications": dict(self.column_classifications),
            "columns": list(self.columns),
            "domains": list(self.domains),
            "interface": self.interface,
            "row_count": self.row_count,
            "rows": [dict(row) for row in self.rows],
            "schema": self.schema,
            "template_id": self.template_id,
            "tenant_id": self.tenant_id,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


_FINALITY_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {
        Finality.UNKNOWN.value: 0,
        Finality.OBSERVED.value: 1,
        Finality.PENDING.value: 2,
        Finality.CONFIRMED.value: 3,
        Finality.SAFE.value: 4,
        Finality.FINALIZED.value: 5,
        Finality.FAILED.value: 0,
        Finality.ORPHANED.value: 0,
        Finality.REVERTED.value: 0,
    }
)

_AUTHORITY_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {
        QueryAuthority.NONE.value: 0,
        QueryAuthority.CANDIDATE.value: 1,
        QueryAuthority.OBSERVATION.value: 2,
        QueryAuthority.EVIDENCE.value: 3,
        QueryAuthority.ATTESTATION.value: 4,
    }
)


def _finality_meets(actual: str, minimum: str | None) -> bool:
    if minimum is None or not str(minimum).strip():
        return True
    return _FINALITY_RANK.get(actual, 0) >= _FINALITY_RANK.get(
        _require_finality(minimum), 0
    )


def _authority_meets(actual: str, minimum: str | None) -> bool:
    if minimum is None or not str(minimum).strip():
        return True
    return _AUTHORITY_RANK.get(actual, 0) >= _AUTHORITY_RANK.get(
        _require_authority(minimum), 0
    )


def _weakest_authority(*values: str) -> str:
    if not values:
        return QueryAuthority.NONE.value
    return min(values, key=lambda v: _AUTHORITY_RANK.get(v, 0))


def _weakest_finality(*values: str) -> str:
    if not values:
        return Finality.UNKNOWN.value
    return min(values, key=lambda v: _FINALITY_RANK.get(v, 0))


def _assert_required_result_columns(row: Mapping[str, Any]) -> None:
    for name in REQUIRED_RESULT_COLUMNS:
        value = row.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ColumnPolicyError(
                f"query result row missing required column {name!r}"
            )


def _project_public_row(
    row: Mapping[str, Any],
    *,
    classifications: Mapping[str, ColumnDataClass],
) -> dict[str, Any]:
    """Project a row onto classified, secret-safe, query-visible columns."""

    _assert_required_result_columns(row)
    scan_secret_surface(row, surface="query_result_row")
    projected: dict[str, Any] = {}
    for key, value in row.items():
        if key == "attributes":
            # Nested attributes are scanned but never projected unless classified.
            continue
        if key not in classifications:
            # Unknown columns are dropped rather than leaking unreviewed surfaces.
            continue
        projected[key] = value
    classify_result_columns(tuple(projected.keys()), classifications=classifications)
    scan_secret_surface(projected, surface="projected_result_row")
    return projected


class _BudgetClock:
    __slots__ = ("budget", "started", "rows_emitted")

    def __init__(self, budget: QueryBudget) -> None:
        self.budget = budget
        self.started = time.monotonic()
        self.rows_emitted = 0

    def check_time(self) -> None:
        if time.monotonic() - self.started > self.budget.max_seconds:
            raise QueryBudgetExceeded("time", self.budget.max_seconds)

    def would_exceed_rows(self) -> bool:
        return self.rows_emitted >= self.budget.max_rows

    def emit(self) -> bool:
        """Return True if the row may be kept; False if truncated."""

        self.check_time()
        if self.rows_emitted >= self.budget.max_rows:
            return False
        self.rows_emitted += 1
        return True


def _filter_transactions(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
) -> list[TransactionFact]:
    tx_hash = params.get("transaction_hash")
    chain = params.get("chain_ref_id")
    min_finality = params.get("min_finality")
    out: list[TransactionFact] = []
    for fact in plane.transactions:
        if not policy.permits_tenant(fact.tenant_id):
            continue
        if not policy.permits_chain(fact.chain_ref_id):
            continue
        if not policy.permits_source(fact.source_id):
            continue
        if tx_hash and fact.transaction_hash != str(tx_hash).strip():
            continue
        if chain and fact.chain_ref_id != str(chain).strip():
            continue
        if not _finality_meets(fact.finality, str(min_finality) if min_finality else None):
            continue
        out.append(fact)
    return out


def _filter_contracts(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    *,
    transaction_hashes: frozenset[str] | None = None,
) -> list[ContractFact]:
    tx_hash = params.get("transaction_hash")
    contract_id = params.get("contract_account_id")
    chain = params.get("chain_ref_id")
    out: list[ContractFact] = []
    for fact in plane.contracts:
        if not policy.permits_tenant(fact.tenant_id):
            continue
        if not policy.permits_chain(fact.chain_ref_id):
            continue
        if not policy.permits_source(fact.source_id):
            continue
        if tx_hash and fact.transaction_hash and fact.transaction_hash != str(tx_hash).strip():
            continue
        if transaction_hashes is not None and fact.transaction_hash:
            if fact.transaction_hash not in transaction_hashes:
                continue
        if contract_id and fact.contract_account_id != str(contract_id).strip():
            continue
        if chain and fact.chain_ref_id != str(chain).strip():
            continue
        out.append(fact)
    return out


def _filter_symbols(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    *,
    contract_ids: frozenset[str] | None = None,
) -> list[SourceSymbolFact]:
    symbol_id = params.get("symbol_id")
    revision = params.get("source_revision")
    contract_id = params.get("contract_account_id")
    out: list[SourceSymbolFact] = []
    for fact in plane.source_symbols:
        if not policy.permits_tenant(fact.tenant_id):
            continue
        if symbol_id and fact.symbol_id != str(symbol_id).strip():
            continue
        if revision and fact.source_revision != str(revision).strip():
            continue
        if contract_id and fact.contract_account_id != str(contract_id).strip():
            continue
        if contract_ids is not None and fact.contract_account_id:
            if fact.contract_account_id not in contract_ids:
                continue
        out.append(fact)
    return out


def _filter_graph_flows(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    *,
    transaction_hashes: frozenset[str] | None = None,
) -> list[GraphFlowFact]:
    tx_hash = params.get("transaction_hash")
    plane_name = params.get("plane")
    graph_revision = params.get("graph_revision")
    out: list[GraphFlowFact] = []
    for fact in plane.graph_flows:
        if not policy.permits_tenant(fact.tenant_id):
            continue
        if fact.chain_ref_id and not policy.permits_chain(fact.chain_ref_id):
            continue
        if tx_hash and fact.transaction_hash != str(tx_hash).strip():
            continue
        if transaction_hashes is not None and fact.transaction_hash:
            if fact.transaction_hash not in transaction_hashes:
                continue
        if plane_name and fact.plane != str(plane_name).strip():
            continue
        if graph_revision and fact.graph_revision != str(graph_revision).strip():
            continue
        out.append(fact)
    return out


def _filter_verification(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    *,
    transaction_hashes: frozenset[str] | None = None,
    contract_ids: frozenset[str] | None = None,
) -> list[VerificationEvidenceFact]:
    evidence_id = params.get("evidence_id")
    min_authority = params.get("min_authority")
    contract_id = params.get("contract_account_id")
    tx_hash = params.get("transaction_hash")
    out: list[VerificationEvidenceFact] = []
    for fact in plane.verification_evidence:
        if not policy.permits_tenant(fact.tenant_id):
            continue
        if evidence_id and fact.evidence_id != str(evidence_id).strip():
            continue
        if not _authority_meets(
            fact.authority, str(min_authority) if min_authority else None
        ):
            continue
        if contract_id and fact.contract_account_id != str(contract_id).strip():
            continue
        if tx_hash and fact.transaction_hash and fact.transaction_hash != str(tx_hash).strip():
            continue
        if transaction_hashes is not None and fact.transaction_hash:
            if fact.transaction_hash not in transaction_hashes:
                continue
        if contract_ids is not None and fact.contract_account_id:
            if fact.contract_account_id not in contract_ids:
                continue
        out.append(fact)
    return out


# ---------------------------------------------------------------------------
# Template executors
# ---------------------------------------------------------------------------


def _exec_transactions_by_tenant(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    clock: _BudgetClock,
    classifications: Mapping[str, ColumnDataClass],
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    truncated = False
    for fact in _filter_transactions(plane, policy, params):
        if clock.would_exceed_rows():
            truncated = True
            break
        raw = {
            "tenant_id": fact.tenant_id,
            "authority": fact.authority,
            "finality": fact.finality,
            "domain": DOMAIN_TRANSACTIONS,
            "record_id": fact.record_id,
            "transaction_hash": fact.transaction_hash,
            "chain_ref_id": fact.chain_ref_id,
            "source_id": fact.source_id,
            "contract_account_id": fact.contract_account_id,
            "status": fact.status,
        }
        policy.enforce_row(raw, surface="transactions_by_tenant")
        projected = _project_public_row(raw, classifications=classifications)
        if not clock.emit():
            truncated = True
            break
        rows.append(projected)
    return rows, truncated


def _exec_transaction_contracts(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    clock: _BudgetClock,
    classifications: Mapping[str, ColumnDataClass],
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    truncated = False
    txs = _filter_transactions(plane, policy, params)
    tx_by_hash = {t.transaction_hash: t for t in txs}
    contracts = _filter_contracts(
        plane,
        policy,
        params,
        transaction_hashes=frozenset(tx_by_hash) if tx_by_hash else None,
    )
    # Also include contracts filtered only by contract id / chain when no txs.
    if not contracts and not txs:
        contracts = _filter_contracts(plane, policy, params)

    for contract in contracts:
        clock.check_time()
        if clock.would_exceed_rows():
            truncated = True
            break
        tx = tx_by_hash.get(contract.transaction_hash)
        if tx is None and contract.transaction_hash:
            # Contract references a tx outside tenant/filter — skip silently.
            matched = [
                t
                for t in txs
                if t.contract_account_id == contract.contract_account_id
            ]
            tx = matched[0] if matched else None
        if tx is None and not contract.transaction_hash:
            matched = [
                t
                for t in txs
                if t.contract_account_id == contract.contract_account_id
            ]
            tx = matched[0] if matched else None
        if tx is None:
            continue
        raw = {
            "tenant_id": policy.tenant_id,
            "authority": _weakest_authority(tx.authority, contract.authority),
            "finality": _weakest_finality(tx.finality, contract.finality),
            "domains": f"{DOMAIN_TRANSACTIONS},{DOMAIN_CONTRACTS}",
            "transaction_hash": tx.transaction_hash,
            "record_id": tx.record_id,
            "chain_ref_id": tx.chain_ref_id,
            "source_id": tx.source_id,
            "contract_account_id": contract.contract_account_id,
            "event_signature": contract.event_signature,
            "status": tx.status,
            "join_key": f"{tx.transaction_hash}:{contract.contract_account_id}",
        }
        policy.enforce_row(raw, surface="transaction_contracts")
        projected = _project_public_row(raw, classifications=classifications)
        if not clock.emit():
            truncated = True
            break
        rows.append(projected)
    return rows, truncated


def _exec_transaction_graph_flows(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    clock: _BudgetClock,
    classifications: Mapping[str, ColumnDataClass],
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    truncated = False
    txs = _filter_transactions(plane, policy, params)
    tx_hashes = frozenset(t.transaction_hash for t in txs)
    flows = _filter_graph_flows(
        plane, policy, params, transaction_hashes=tx_hashes if tx_hashes else None
    )
    tx_by_hash = {t.transaction_hash: t for t in txs}
    for flow in flows:
        clock.check_time()
        if clock.would_exceed_rows():
            truncated = True
            break
        tx = tx_by_hash.get(flow.transaction_hash)
        if tx is None:
            continue
        raw = {
            "tenant_id": policy.tenant_id,
            "authority": _weakest_authority(tx.authority, flow.authority),
            "finality": _weakest_finality(tx.finality, flow.finality),
            "domains": f"{DOMAIN_TRANSACTIONS},{DOMAIN_GRAPH_FLOWS}",
            "transaction_hash": tx.transaction_hash,
            "record_id": tx.record_id,
            "chain_ref_id": tx.chain_ref_id or flow.chain_ref_id,
            "source_id": tx.source_id,
            "node_or_edge_id": flow.node_or_edge_id,
            "kind": flow.kind,
            "plane": flow.plane,
            "graph_revision": flow.graph_revision,
            "join_key": f"{tx.transaction_hash}:{flow.node_or_edge_id}",
        }
        policy.enforce_row(raw, surface="transaction_graph_flows")
        projected = _project_public_row(raw, classifications=classifications)
        if not clock.emit():
            truncated = True
            break
        rows.append(projected)
    return rows, truncated


def _exec_transaction_source_symbols(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    clock: _BudgetClock,
    classifications: Mapping[str, ColumnDataClass],
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    truncated = False
    txs = _filter_transactions(plane, policy, params)
    contracts = _filter_contracts(
        plane,
        policy,
        params,
        transaction_hashes=frozenset(t.transaction_hash for t in txs) or None,
    )
    contract_ids = frozenset(c.contract_account_id for c in contracts)
    # Include contract ids referenced directly on transactions.
    contract_ids = contract_ids | frozenset(
        t.contract_account_id for t in txs if t.contract_account_id
    )
    symbols = _filter_symbols(
        plane, policy, params, contract_ids=contract_ids or None
    )
    contract_by_id = {c.contract_account_id: c for c in contracts}
    tx_by_contract: dict[str, TransactionFact] = {}
    for t in txs:
        if t.contract_account_id:
            tx_by_contract.setdefault(t.contract_account_id, t)
    for c in contracts:
        if c.transaction_hash:
            for t in txs:
                if t.transaction_hash == c.transaction_hash:
                    tx_by_contract.setdefault(c.contract_account_id, t)

    for symbol in symbols:
        clock.check_time()
        if clock.would_exceed_rows():
            truncated = True
            break
        contract = contract_by_id.get(symbol.contract_account_id)
        tx = tx_by_contract.get(symbol.contract_account_id)
        if tx is None and contract is not None:
            for t in txs:
                if t.transaction_hash == contract.transaction_hash:
                    tx = t
                    break
        if tx is None:
            continue
        authorities = [tx.authority, symbol.authority]
        finalities = [tx.finality, symbol.finality]
        if contract is not None:
            authorities.append(contract.authority)
            finalities.append(contract.finality)
        raw = {
            "tenant_id": policy.tenant_id,
            "authority": _weakest_authority(*authorities),
            "finality": _weakest_finality(*finalities),
            "domains": (
                f"{DOMAIN_TRANSACTIONS},{DOMAIN_CONTRACTS},{DOMAIN_SOURCE_SYMBOLS}"
            ),
            "transaction_hash": tx.transaction_hash,
            "record_id": tx.record_id,
            "chain_ref_id": tx.chain_ref_id,
            "source_id": tx.source_id,
            "contract_account_id": symbol.contract_account_id
            or (contract.contract_account_id if contract else ""),
            "symbol_id": symbol.symbol_id,
            "qualified_name": symbol.qualified_name,
            "source_revision": symbol.source_revision,
            "file_path": symbol.file_path,
            "join_key": f"{tx.transaction_hash}:{symbol.symbol_id}",
        }
        policy.enforce_row(raw, surface="transaction_source_symbols")
        projected = _project_public_row(raw, classifications=classifications)
        if not clock.emit():
            truncated = True
            break
        rows.append(projected)
    return rows, truncated


def _exec_transaction_verification(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    clock: _BudgetClock,
    classifications: Mapping[str, ColumnDataClass],
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    truncated = False
    txs = _filter_transactions(plane, policy, params)
    contracts = _filter_contracts(
        plane,
        policy,
        params,
        transaction_hashes=frozenset(t.transaction_hash for t in txs) or None,
    )
    tx_hashes = frozenset(t.transaction_hash for t in txs)
    contract_ids = frozenset(c.contract_account_id for c in contracts) | frozenset(
        t.contract_account_id for t in txs if t.contract_account_id
    )
    evidence = _filter_verification(
        plane,
        policy,
        params,
        transaction_hashes=tx_hashes or None,
        contract_ids=contract_ids or None,
    )
    tx_by_hash = {t.transaction_hash: t for t in txs}
    tx_by_contract = {
        t.contract_account_id: t for t in txs if t.contract_account_id
    }

    for ev in evidence:
        clock.check_time()
        if clock.would_exceed_rows():
            truncated = True
            break
        tx = None
        if ev.transaction_hash:
            tx = tx_by_hash.get(ev.transaction_hash)
        if tx is None and ev.contract_account_id:
            tx = tx_by_contract.get(ev.contract_account_id)
        if tx is None:
            continue
        raw = {
            "tenant_id": policy.tenant_id,
            "authority": _weakest_authority(tx.authority, ev.authority),
            "finality": _weakest_finality(tx.finality, ev.finality),
            "domains": (
                f"{DOMAIN_TRANSACTIONS},{DOMAIN_CONTRACTS},{DOMAIN_VERIFICATION}"
            ),
            "transaction_hash": tx.transaction_hash,
            "record_id": tx.record_id,
            "chain_ref_id": tx.chain_ref_id,
            "source_id": tx.source_id,
            "contract_account_id": ev.contract_account_id or tx.contract_account_id,
            "evidence_id": ev.evidence_id,
            "evidence_kind": ev.evidence_kind,
            "subject_ref": ev.subject_ref,
            "content_digest": ev.content_digest,
            "trust_level": ev.trust_level,
            "join_key": f"{tx.transaction_hash}:{ev.evidence_id}",
        }
        policy.enforce_row(raw, surface="transaction_verification")
        projected = _project_public_row(raw, classifications=classifications)
        if not clock.emit():
            truncated = True
            break
        rows.append(projected)
    return rows, truncated


def _exec_cross_domain_join(
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    params: Mapping[str, Any],
    clock: _BudgetClock,
    classifications: Mapping[str, ColumnDataClass],
) -> tuple[list[dict[str, Any]], bool]:
    """Join all five domains on transaction / contract keys under budget."""

    rows: list[dict[str, Any]] = []
    truncated = False
    txs = _filter_transactions(plane, policy, params)
    tx_hashes = frozenset(t.transaction_hash for t in txs)
    contracts = _filter_contracts(
        plane, policy, params, transaction_hashes=tx_hashes or None
    )
    contract_ids = frozenset(c.contract_account_id for c in contracts) | frozenset(
        t.contract_account_id for t in txs if t.contract_account_id
    )
    symbols = _filter_symbols(
        plane, policy, params, contract_ids=contract_ids or None
    )
    flows = _filter_graph_flows(
        plane, policy, params, transaction_hashes=tx_hashes or None
    )
    evidence = _filter_verification(
        plane,
        policy,
        params,
        transaction_hashes=tx_hashes or None,
        contract_ids=contract_ids or None,
    )

    contracts_by_tx: dict[str, list[ContractFact]] = {}
    for c in contracts:
        if c.transaction_hash:
            contracts_by_tx.setdefault(c.transaction_hash, []).append(c)
    for t in txs:
        if t.contract_account_id:
            for c in contracts:
                if c.contract_account_id == t.contract_account_id:
                    contracts_by_tx.setdefault(t.transaction_hash, [])
                    if c not in contracts_by_tx[t.transaction_hash]:
                        contracts_by_tx[t.transaction_hash].append(c)

    symbols_by_contract: dict[str, list[SourceSymbolFact]] = {}
    for s in symbols:
        if s.contract_account_id:
            symbols_by_contract.setdefault(s.contract_account_id, []).append(s)

    flows_by_tx: dict[str, list[GraphFlowFact]] = {}
    for f in flows:
        if f.transaction_hash:
            flows_by_tx.setdefault(f.transaction_hash, []).append(f)

    evidence_by_tx: dict[str, list[VerificationEvidenceFact]] = {}
    for e in evidence:
        if e.transaction_hash:
            evidence_by_tx.setdefault(e.transaction_hash, []).append(e)
        elif e.contract_account_id:
            for t in txs:
                if t.contract_account_id == e.contract_account_id:
                    evidence_by_tx.setdefault(t.transaction_hash, []).append(e)

    for tx in txs:
        clock.check_time()
        tx_contracts = contracts_by_tx.get(tx.transaction_hash) or [None]
        tx_flows = flows_by_tx.get(tx.transaction_hash) or [None]
        tx_evidence = evidence_by_tx.get(tx.transaction_hash) or [None]
        for contract in tx_contracts:
            c_id = (
                contract.contract_account_id
                if contract is not None
                else tx.contract_account_id
            )
            tx_symbols = (
                symbols_by_contract.get(c_id) or [None] if c_id else [None]
            )
            for symbol in tx_symbols:
                for flow in tx_flows:
                    for ev in tx_evidence:
                        if clock.would_exceed_rows():
                            truncated = True
                            break
                        authorities = [tx.authority]
                        finalities = [tx.finality]
                        if contract is not None:
                            authorities.append(contract.authority)
                            finalities.append(contract.finality)
                        if symbol is not None:
                            authorities.append(symbol.authority)
                            finalities.append(symbol.finality)
                        if flow is not None:
                            authorities.append(flow.authority)
                            finalities.append(flow.finality)
                        if ev is not None:
                            authorities.append(ev.authority)
                            finalities.append(ev.finality)
                        raw: dict[str, Any] = {
                            "tenant_id": policy.tenant_id,
                            "authority": _weakest_authority(*authorities),
                            "finality": _weakest_finality(*finalities),
                            "domains": ",".join(ALL_JOIN_DOMAINS),
                            "transaction_hash": tx.transaction_hash,
                            "record_id": tx.record_id,
                            "chain_ref_id": tx.chain_ref_id,
                            "source_id": tx.source_id,
                            "contract_account_id": c_id or "",
                            "status": tx.status,
                            "event_signature": (
                                contract.event_signature if contract else ""
                            ),
                            "symbol_id": symbol.symbol_id if symbol else "",
                            "qualified_name": (
                                symbol.qualified_name if symbol else ""
                            ),
                            "source_revision": (
                                symbol.source_revision if symbol else ""
                            ),
                            "file_path": symbol.file_path if symbol else "",
                            "node_or_edge_id": (
                                flow.node_or_edge_id if flow else ""
                            ),
                            "kind": flow.kind if flow else "",
                            "plane": flow.plane if flow else "",
                            "graph_revision": (
                                flow.graph_revision if flow else ""
                            ),
                            "evidence_id": ev.evidence_id if ev else "",
                            "evidence_kind": ev.evidence_kind if ev else "",
                            "subject_ref": ev.subject_ref if ev else "",
                            "content_digest": (
                                ev.content_digest if ev else ""
                            ),
                            "trust_level": ev.trust_level if ev else "",
                            "join_key": (
                                f"{tx.transaction_hash}:"
                                f"{c_id or '-'}:"
                                f"{(symbol.symbol_id if symbol else '-')}:"
                                f"{(flow.node_or_edge_id if flow else '-')}:"
                                f"{(ev.evidence_id if ev else '-')}"
                            ),
                        }
                        policy.enforce_row(raw, surface="cross_domain_join")
                        projected = _project_public_row(
                            raw, classifications=classifications
                        )
                        if not clock.emit():
                            truncated = True
                            break
                        rows.append(projected)
                    if truncated:
                        break
                if truncated:
                    break
            if truncated:
                break
        if truncated:
            break
    return rows, truncated


_TEMPLATE_EXECUTORS: Final[
    Mapping[
        str,
        Callable[
            [
                WalletJoinPlane,
                TenantPolicy,
                Mapping[str, Any],
                _BudgetClock,
                Mapping[str, ColumnDataClass],
            ],
            tuple[list[dict[str, Any]], bool],
        ],
    ]
] = MappingProxyType(
    {
        QueryTemplateId.TRANSACTIONS_BY_TENANT.value: _exec_transactions_by_tenant,
        QueryTemplateId.TRANSACTION_CONTRACTS.value: _exec_transaction_contracts,
        QueryTemplateId.TRANSACTION_GRAPH_FLOWS.value: _exec_transaction_graph_flows,
        QueryTemplateId.TRANSACTION_SOURCE_SYMBOLS.value: (
            _exec_transaction_source_symbols
        ),
        QueryTemplateId.TRANSACTION_VERIFICATION.value: (
            _exec_transaction_verification
        ),
        QueryTemplateId.CROSS_DOMAIN_JOIN.value: _exec_cross_domain_join,
    }
)


# ---------------------------------------------------------------------------
# Public executor API
# ---------------------------------------------------------------------------


def validate_query_parameters(
    template_id: str | QueryTemplateId,
    params: Mapping[str, Any] | None,
    *,
    budget: QueryBudget | None = None,
) -> dict[str, Any]:
    """Validate and secret-scan parameters for an allowlisted template."""

    tid = resolve_template_id(template_id)
    raw = dict(params or {})
    scan_secret_surface(raw, surface=f"params:{tid}")
    allowed = TEMPLATE_PARAMETER_KEYS[tid]
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise WalletQueryError(
            f"template {tid!r} rejects unknown parameter(s): {unknown}"
        )
    for key in raw:
        if _key_matches_secret_fragment(key):
            raise SecretSurfaceRejected(
                f"params:{tid}: forbidden secret/signing field rejected"
            )
    bud = budget or QueryBudget()
    size = _parameter_byte_size(raw)
    if size > bud.max_parameter_bytes:
        raise QueryBudgetExceeded("parameter_bytes", bud.max_parameter_bytes)
    return raw


def execute_allowlisted_query(
    template_id: str | QueryTemplateId,
    plane: WalletJoinPlane,
    policy: TenantPolicy,
    *,
    params: Mapping[str, Any] | None = None,
    budget: QueryBudget | None = None,
) -> QueryResult:
    """Execute one allowlisted template against a join plane.

    Fails closed on unknown templates, secret surfaces, tenant violations, and
    resource budget exhaustion.  Every result row includes ``tenant_id``,
    ``authority``, and ``finality``.
    """

    if not isinstance(plane, WalletJoinPlane):
        raise WalletQueryError("plane must be a WalletJoinPlane")
    if not isinstance(policy, TenantPolicy):
        raise WalletQueryError("policy must be a TenantPolicy")

    tid = resolve_template_id(template_id)
    domains = TEMPLATE_DOMAINS[tid]
    bud = budget or QueryBudget()
    if len(domains) > bud.max_join_domains:
        raise QueryBudgetExceeded("join_domains", bud.max_join_domains)

    clean_params = validate_query_parameters(tid, params, budget=bud)
    classifications = TEMPLATE_RESULT_CLASSIFICATIONS[tid]
    clock = _BudgetClock(bud)
    executor = _TEMPLATE_EXECUTORS[tid]
    rows, truncated = executor(
        plane, policy, clean_params, clock, classifications
    )

    # Final row-level secret scan and required-column check.
    frozen_rows: list[Mapping[str, Any]] = []
    for row in rows:
        _assert_required_result_columns(row)
        scan_secret_surface(row, surface="result_row")
        policy.enforce_row(row, surface="result")
        frozen_rows.append(MappingProxyType(dict(row)))

    columns = tuple(sorted({key for row in frozen_rows for key in row}))
    if not columns:
        columns = REQUIRED_RESULT_COLUMNS
    column_classes = {
        name: classifications[name].value
        for name in columns
        if name in classifications
    }

    return QueryResult(
        template_id=tid,
        tenant_id=policy.tenant_id,
        domains=domains,
        columns=columns,
        column_classifications=MappingProxyType(column_classes),
        rows=tuple(frozen_rows),
        row_count=len(frozen_rows),
        truncated=truncated,
        budget=MappingProxyType(
            {
                "max_rows": bud.max_rows,
                "max_seconds": bud.max_seconds,
                "max_join_domains": bud.max_join_domains,
                "max_parameter_bytes": bud.max_parameter_bytes,
                "rows_emitted": clock.rows_emitted,
                "elapsed_seconds": round(time.monotonic() - clock.started, 6),
            }
        ),
    )


def wallet_queries_descriptor() -> dict[str, Any]:
    """Return a stable JSON-serializable module descriptor."""

    return {
        "interface": DUCKDB_WALLET_QUERIES_INTERFACE,
        "schema": DUCKDB_WALLET_QUERIES_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "required_result_columns": list(REQUIRED_RESULT_COLUMNS),
        "join_domains": list(ALL_JOIN_DOMAINS),
        "templates": [
            {
                "template_id": tid,
                "domains": list(TEMPLATE_DOMAINS[tid]),
                "parameter_keys": sorted(TEMPLATE_PARAMETER_KEYS[tid]),
                "result_columns": sorted(TEMPLATE_RESULT_CLASSIFICATIONS[tid]),
            }
            for tid in list_allowlisted_templates()
        ],
        "forbidden_query_classes": sorted(c.value for c in FORBIDDEN_QUERY_CLASSES),
        "query_visible_classes": sorted(c.value for c in QUERY_VISIBLE_CLASSES),
        "denied_field_fragments": list(_SECRET_NAME_FRAGMENTS),
    }


class WalletQueryService:
    """Stateful convenience wrapper around :func:`execute_allowlisted_query`."""

    __slots__ = ("_plane", "_default_budget")

    def __init__(
        self,
        plane: WalletJoinPlane | None = None,
        *,
        default_budget: QueryBudget | None = None,
    ) -> None:
        self._plane = plane if plane is not None else WalletJoinPlane()
        self._default_budget = default_budget or QueryBudget()

    @property
    def plane(self) -> WalletJoinPlane:
        return self._plane

    @property
    def interface(self) -> str:
        return DUCKDB_WALLET_QUERIES_INTERFACE

    @property
    def schema(self) -> str:
        return DUCKDB_WALLET_QUERIES_SCHEMA

    def execute(
        self,
        template_id: str | QueryTemplateId,
        policy: TenantPolicy,
        *,
        params: Mapping[str, Any] | None = None,
        budget: QueryBudget | None = None,
    ) -> QueryResult:
        return execute_allowlisted_query(
            template_id,
            self._plane,
            policy,
            params=params,
            budget=budget or self._default_budget,
        )

    def list_templates(self) -> tuple[str, ...]:
        return list_allowlisted_templates()


def open_wallet_query_service(
    plane: WalletJoinPlane | None = None,
    *,
    default_budget: QueryBudget | None = None,
) -> WalletQueryService:
    """Construct a :class:`WalletQueryService` with standard defaults."""

    return WalletQueryService(plane, default_budget=default_budget)


__all__ = [
    "ALL_JOIN_DOMAINS",
    "ColumnPolicyError",
    "ContractFact",
    "DOMAIN_CONTRACTS",
    "DOMAIN_GRAPH_FLOWS",
    "DOMAIN_SOURCE_SYMBOLS",
    "DOMAIN_TRANSACTIONS",
    "DOMAIN_VERIFICATION",
    "DUCKDB_WALLET_QUERIES_INTERFACE",
    "DUCKDB_WALLET_QUERIES_SCHEMA",
    "GraphFlowFact",
    "QueryAuthority",
    "QueryBudget",
    "QueryBudgetExceeded",
    "QueryResult",
    "QueryTemplateId",
    "REQUIRED_RESULT_COLUMNS",
    "SCHEMA_VERSION",
    "SecretSurfaceRejected",
    "SourceSymbolFact",
    "TEMPLATE_DOMAINS",
    "TEMPLATE_PARAMETER_KEYS",
    "TEMPLATE_RESULT_CLASSIFICATIONS",
    "TenantPolicy",
    "TenantPolicyViolation",
    "TransactionFact",
    "UnknownQueryTemplateError",
    "VerificationEvidenceFact",
    "WalletJoinPlane",
    "WalletQueryError",
    "WalletQueryService",
    "classify_result_columns",
    "execute_allowlisted_query",
    "list_allowlisted_templates",
    "open_wallet_query_service",
    "resolve_template_id",
    "scan_secret_surface",
    "validate_query_parameters",
    "wallet_queries_descriptor",
]
