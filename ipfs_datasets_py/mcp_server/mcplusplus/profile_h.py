"""Paid dataset capabilities using MCP++ Profile H and x402 v2.

This module is transport-neutral and deliberately keeps commercial policy
separate from data authorization.  A successful payment can never widen a
tenant, licence, row, field, or privacy scope.  Protected inputs and outputs
are represented in durable/public evidence only by salted-free cryptographic
commitments; the values themselves are passed directly to the caller's effect.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from mcplusplus_profile_h import (
    CallbackFacilitator,
    CapabilityCatalog,
    CommercialBinding,
    Decision,
    DuckDBPaymentLedger,
    FileCIDArtifactStore,
    PaidCapability,
    PaymentContext,
    PaymentPolicyEngine,
    PaymentRequirement,
    RequestContext,
    SellerResult,
    SellerRuntime,
    ProfileHControlPlane,
    http_response,
    libp2p_response,
)
from mcplusplus_profile_h.canonical import canonical_json, cid_for, commitment
from mcplusplus_profile_h.errors import ProfileHError


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_OPERATIONS = frozenset({"query/execute", "transform/run", "graphrag/query"})
_MISSING = object()


class DatasetPaymentError(ProfileHError):
    """Stable failure raised before protected dataset content is accessed."""


@dataclass(frozen=True, slots=True)
class DatasetPolicy:
    """A fixed-price, version-pinned data access policy.

    ``row_constraints`` maps a column to the values a tenant may select.  Every
    constrained column must appear in the request filter, which prevents a
    broad query followed by client-side filtering.  Set ``allowed_fields`` to
    ``("*",)`` only for datasets whose licence permits every field.
    """

    dataset_id: str
    version: str
    amount: str
    license_id: str
    tenants: tuple[str, ...]
    operations: tuple[str, ...] = ("query/execute", "transform/run", "graphrag/query")
    allowed_fields: tuple[str, ...] = ("*",)
    denied_fields: tuple[str, ...] = ()
    row_constraints: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    privacy_modes: tuple[str, ...] = ("aggregate",)
    max_rows: int = 1_000
    max_epsilon: float | None = None
    minimum_k: int | None = None
    entitlement_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        for value, label in ((self.dataset_id, "dataset_id"), (self.version, "version"),
                             (self.license_id, "license_id")):
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"invalid {label}")
        if not self.amount.isdigit() or (len(self.amount) > 1 and self.amount.startswith("0")):
            raise ValueError("amount must be a canonical atomic-unit integer")
        if not self.tenants or any(not _IDENTIFIER.fullmatch(item) for item in self.tenants):
            raise ValueError("at least one valid tenant is required")
        if not self.operations or not set(self.operations).issubset(_OPERATIONS):
            raise ValueError("unsupported dataset operation")
        if not self.allowed_fields or set(self.allowed_fields).intersection(self.denied_fields):
            raise ValueError("field scopes must be non-empty and disjoint")
        if "*" in self.allowed_fields and len(self.allowed_fields) != 1:
            raise ValueError("wildcard allowed_fields cannot be combined with named fields")
        if not self.privacy_modes or self.max_rows < 1 or not 1 <= self.entitlement_ttl_seconds <= 86_400:
            raise ValueError("invalid privacy, row, or entitlement bound")
        if self.max_epsilon is not None and self.max_epsilon <= 0:
            raise ValueError("max_epsilon must be positive")
        if self.minimum_k is not None and self.minimum_k < 2:
            raise ValueError("minimum_k must be at least two")
        constraints = {str(key): tuple(values) for key, values in self.row_constraints.items()}
        if any(not key or not values for key, values in constraints.items()):
            raise ValueError("row constraints require a name and at least one value")
        object.__setattr__(self, "tenants", tuple(self.tenants))
        object.__setattr__(self, "operations", tuple(dict.fromkeys(self.operations)))
        object.__setattr__(self, "allowed_fields", tuple(dict.fromkeys(self.allowed_fields)))
        object.__setattr__(self, "denied_fields", tuple(dict.fromkeys(self.denied_fields)))
        object.__setattr__(self, "privacy_modes", tuple(dict.fromkeys(self.privacy_modes)))
        object.__setattr__(self, "row_constraints", MappingProxyType(constraints))

    @property
    def dataset_version(self) -> str:
        return f"{self.dataset_id}@{self.version}"

    @property
    def policy_commitment(self) -> str:
        return commitment({
            "dataset": self.dataset_id, "version": self.version, "license": self.license_id,
            "tenants": self.tenants, "allowedFields": self.allowed_fields,
            "deniedFields": self.denied_fields, "rowConstraints": dict(self.row_constraints),
            "privacyModes": self.privacy_modes, "maxRows": self.max_rows,
            "maxEpsilon": self.max_epsilon, "minimumK": self.minimum_k,
        })


# Naming aliases used by dataset registries and earlier integration packets.
PaidDataset = DatasetPolicy
DatasetCapability = DatasetPolicy
DatasetOffer = DatasetPolicy


@dataclass(frozen=True, slots=True)
class DatasetPaymentConfig:
    seller_did: str
    descriptor_cid: str
    pay_to: str
    asset: str
    datasets: Mapping[str, DatasetPolicy]
    network: str = "eip155:84532"
    scheme: str = "exact"
    catalog_version: str = "1"
    unlisted_free: bool = True

    def __post_init__(self) -> None:
        if not self.seller_did.startswith("did:") or not self.descriptor_cid:
            raise ValueError("seller_did and descriptor_cid are required")
        if ":" not in self.network or not self.pay_to or not self.asset:
            raise ValueError("valid network, asset, and payee are required")
        normalized = {str(name): item for name, item in self.datasets.items()}
        if not normalized or any(not _IDENTIFIER.fullmatch(name) for name in normalized):
            raise ValueError("at least one named dataset policy is required")
        versions = [item.dataset_version for item in normalized.values()]
        if len(versions) != len(set(versions)):
            raise ValueError("dataset and version policies must be unique")
        object.__setattr__(self, "datasets", MappingProxyType(normalized))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DatasetPaymentConfig":
        datasets = {
            name: item if isinstance(item, DatasetPolicy) else DatasetPolicy(**dict(item))
            for name, item in dict(value.get("datasets", {})).items()
        }
        return cls(datasets=datasets, **{key: item for key, item in value.items() if key != "datasets"})


DatasetsPaymentConfig = DatasetPaymentConfig


class CatalogSigner:
    """State-local Ed25519 catalog signer with an atomic, mode-0600 key."""

    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key

    @classmethod
    def generate(cls) -> "CatalogSigner":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load_or_create(cls, path: str | Path) -> "CatalogSigner":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = Ed25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
            except FileExistsError:
                raw = path.read_bytes()
        if len(raw) != 32:
            raise ValueError("invalid persisted Ed25519 catalog key")
        os.chmod(path, 0o600)
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    def sign(self, document: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = dict(document)
        unsigned.pop("signature", None)
        public = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        unsigned.update({"signatureAlg": "Ed25519", "publicKey": base64.b64encode(public).decode("ascii")})
        return {**unsigned, "signature": base64.b64encode(self._key.sign(canonical_json(unsigned))).decode("ascii")}

    @staticmethod
    def verify(document: Mapping[str, Any]) -> bool:
        try:
            unsigned = dict(document)
            unsigned.pop("signedCatalogCid", None)
            signature = base64.b64decode(unsigned.pop("signature"), validate=True)
            public = base64.b64decode(unsigned["publicKey"], validate=True)
            Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical_json(unsigned))
            return True
        except (InvalidSignature, KeyError, TypeError, ValueError):
            return False


class DatasetEvidenceStore:
    """Durable, private-content-free entitlement and provenance index."""

    def __init__(self, path: str | Path, artifacts: FileCIDArtifactStore,
                 clock_ms: Callable[[], int]) -> None:
        self.path, self.artifacts, self.clock_ms = Path(path), artifacts, clock_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS dataset_executions ("
                "idempotency_key TEXT PRIMARY KEY,request_cid TEXT NOT NULL,operation TEXT NOT NULL,"
                "dataset_id TEXT NOT NULL,dataset_version TEXT NOT NULL,query_commitment TEXT NOT NULL,"
                "execution_id TEXT UNIQUE NOT NULL,status TEXT NOT NULL,entitlement_cid TEXT NOT NULL,"
                "settlement_cid TEXT NOT NULL,usage_cid TEXT,provenance_cid TEXT,output_cid TEXT,"
                "created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    @staticmethod
    def _row(row: tuple[Any, ...]) -> dict[str, Any]:
        keys = ("idempotencyKey", "requestCid", "operation", "datasetId", "datasetVersion",
                "queryCommitment", "executionId", "status", "entitlementCid", "settlementCid",
                "usageRecordCid", "provenanceCid", "outputReceiptCid", "createdAt", "updatedAt")
        return dict(zip(keys, row))

    def begin(self, *, context: RequestContext, operation: str, policy: DatasetPolicy,
              query_commitment: str, settlement_cid: str, subject: str,
              tenant: str) -> tuple[dict[str, Any], bool]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM dataset_executions WHERE idempotency_key=?",
                             (context.idempotency_key,)).fetchone()
            if row:
                db.rollback()
                record = self._row(row)
                expected = (context.request_cid, operation, policy.dataset_id, policy.version, query_commitment)
                actual = (record["requestCid"], record["operation"], record["datasetId"],
                          record["datasetVersion"], record["queryCommitment"])
                if actual != expected:
                    raise DatasetPaymentError("H_REQUEST_MISMATCH", "entitlement is bound to different dataset work")
                return record, True
            now = self.clock_ms()
            execution_id = f"dataset-{uuid.uuid4().hex}"
            entitlement = {
                "schema": "mcp++/profile-h/dataset-entitlement@1.0", "createdAt": now,
                "expiresAt": now + policy.entitlement_ttl_seconds * 1_000,
                "parents": [settlement_cid], "settlementCid": settlement_cid,
                "requestCid": context.request_cid, "operation": operation,
                "datasetCommitment": commitment(policy.dataset_id),
                "versionCommitment": commitment(policy.version),
                "queryCommitment": query_commitment, "policyCommitment": policy.policy_commitment,
                "subjectCommitment": commitment(subject), "tenantCommitment": commitment(tenant),
                "executionId": execution_id,
                "authority": {"canReadBoundResult": True, "canSignPayments": False},
            }
            entitlement_cid = self.artifacts.put(entitlement)
            db.execute("INSERT INTO dataset_executions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                context.idempotency_key, context.request_cid, operation, policy.dataset_id, policy.version,
                query_commitment, execution_id, "starting", entitlement_cid, settlement_cid,
                None, None, None, now, now,
            ))
            db.commit()
        return self.get(execution_id) or {}, False

    def finish(self, execution_id: str, result: Any, *, policy: DatasetPolicy,
               operation: str, requested_rows: int | None) -> dict[str, Any]:
        record = self.get(execution_id)
        if not record:
            raise DatasetPaymentError("H_RECONCILIATION_REQUIRED", "dataset execution record is missing", retryable=True)
        output_commitment = commitment(result)
        usage = {
            "schema": "mcp++/profile-h/dataset-usage@1.0", "createdAt": self.clock_ms(),
            "parents": [record["entitlementCid"], record["settlementCid"]],
            "entitlementCid": record["entitlementCid"], "requestCid": record["requestCid"],
            "queryCommitment": record["queryCommitment"], "outputCommitment": output_commitment,
            "executionId": execution_id, "operation": operation,
            "rowCountBucket": self._row_bucket(requested_rows), "outcome": "succeeded",
        }
        usage_cid = self.artifacts.put(usage)
        provenance = {
            "schema": "mcp++/profile-h/dataset-provenance@1.0", "createdAt": self.clock_ms(),
            "parents": [record["entitlementCid"], usage_cid],
            "entitlementCid": record["entitlementCid"], "usageRecordCid": usage_cid,
            "datasetCommitment": commitment(policy.dataset_id),
            "versionCommitment": commitment(policy.version),
            "queryCommitment": record["queryCommitment"], "outputCommitment": output_commitment,
            "policyCommitment": policy.policy_commitment, "operation": operation,
        }
        provenance_cid = self.artifacts.put(provenance)
        output_receipt = {
            "schema": "mcp++/profile-h/dataset-output-receipt@1.0", "createdAt": self.clock_ms(),
            "parents": [usage_cid, provenance_cid], "usageRecordCid": usage_cid,
            "provenanceCid": provenance_cid, "entitlementCid": record["entitlementCid"],
            "queryCommitment": record["queryCommitment"], "outputCommitment": output_commitment,
        }
        output_cid = self.artifacts.put(output_receipt)
        with self._lock, self._connect() as db:
            changed = db.execute(
                "UPDATE dataset_executions SET status='succeeded',usage_cid=?,provenance_cid=?,"
                "output_cid=?,updated_at=? WHERE execution_id=? AND status='starting'",
                (usage_cid, provenance_cid, output_cid, self.clock_ms(), execution_id),
            ).rowcount
        if not changed:
            latest = self.get(execution_id)
            if not latest or latest["status"] != "succeeded":
                raise DatasetPaymentError("H_RECONCILIATION_REQUIRED", "conflicting dataset execution outcome")
        return self.get(execution_id) or {}

    def fail(self, execution_id: str, error: BaseException) -> dict[str, Any]:
        record = self.get(execution_id)
        if not record:
            raise DatasetPaymentError("H_RECONCILIATION_REQUIRED", "dataset execution record is missing", retryable=True)
        failure = {
            "schema": "mcp++/profile-h/dataset-usage@1.0", "createdAt": self.clock_ms(),
            "parents": [record["entitlementCid"], record["settlementCid"]],
            "entitlementCid": record["entitlementCid"], "requestCid": record["requestCid"],
            "queryCommitment": record["queryCommitment"], "executionId": execution_id,
            "outcome": "failed", "errorTypeCommitment": commitment(type(error).__name__),
        }
        usage_cid = self.artifacts.put(failure)
        with self._connect() as db:
            db.execute("UPDATE dataset_executions SET status='failed',usage_cid=?,updated_at=? "
                       "WHERE execution_id=? AND status='starting'", (usage_cid, self.clock_ms(), execution_id))
        return self.get(execution_id) or {}

    @staticmethod
    def _row_bucket(count: int | None) -> str:
        if count is None:
            return "unspecified"
        if count <= 10:
            return "1-10"
        if count <= 100:
            return "11-100"
        if count <= 1_000:
            return "101-1000"
        return "1001+"

    def get(self, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM dataset_executions WHERE execution_id=?", (execution_id,)).fetchone()
        return self._row(row) if row else None

    def get_by_key(self, key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM dataset_executions WHERE idempotency_key=?", (key,)).fetchone()
        return self._row(row) if row else None

    def get_by_evidence(self, cid: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM dataset_executions WHERE entitlement_cid=? OR usage_cid=? OR provenance_cid=? OR output_cid=?",
                (cid, cid, cid, cid),
            ).fetchone()
        return self._row(row) if row else None

    def reconcile(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM dataset_executions WHERE status='starting' ORDER BY created_at").fetchall()
        return [{**self._row(row), "reconciliationRequired": True} for row in rows]

    def diagnostics(self) -> dict[str, int]:
        with self._connect() as db:
            return {str(status): int(count) for status, count in
                    db.execute("SELECT status,count(*) FROM dataset_executions GROUP BY status")}


class PaidDatasetService:
    """Profile H facade for dataset query, transform, and GraphRAG work."""

    ROUTES = {
        ("POST", "/mcp/datasets/query"): "query/execute",
        ("POST", "/mcp/datasets/transform"): "transform/run",
        ("POST", "/mcp/datasets/graphrag"): "graphrag/query",
        ("POST", "/mcp/tools/dataset/query"): "query/execute",
        ("POST", "/mcp/tools/dataset/transform"): "transform/run",
        ("POST", "/mcp/tools/graphrag/query"): "graphrag/query",
    }

    def __init__(self, config: DatasetPaymentConfig, state_dir: str | Path, facilitator: Any, *,
                 signer: CatalogSigner | None = None, clock_ms: Callable[[], int] | None = None,
                 control_mode: str | None = None) -> None:
        self.config, self.state_dir = config, Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.signer = signer or CatalogSigner.load_or_create(self.state_dir / "catalog-signing.key")
        self.artifacts = FileCIDArtifactStore(self.state_dir / "artifacts")
        capabilities: list[PaidCapability] = []
        self._capability_policies: dict[str, DatasetPolicy] = {}
        for name, policy in config.datasets.items():
            requirement = PaymentRequirement(
                config.scheme, config.network, config.asset, policy.amount, config.pay_to,
                extra={"datasetPolicy": name, "datasetVersion": policy.dataset_version},
            )
            for operation in policy.operations:
                key = f"tool:{operation}:{name}"
                capabilities.append(PaidCapability(key, (requirement,), metadata={
                    "ability": f"tool:{operation}", "operation": operation,
                    "datasetPolicy": name, "datasetVersion": policy.dataset_version,
                    "license": policy.license_id, "privacyModes": list(policy.privacy_modes),
                    "maxRows": policy.max_rows, "policyCommitment": policy.policy_commitment,
                }))
                self._capability_policies[key] = policy
        catalog = CapabilityCatalog(capabilities, version=config.catalog_version)
        self.runtime = SellerRuntime(
            PaymentPolicyEngine(catalog, unlisted=Decision.FREE if config.unlisted_free else Decision.DENIED),
            DuckDBPaymentLedger(self.state_dir / "payments.duckdb"), facilitator, self.artifacts,
            seller_did=config.seller_did, descriptor_cid=config.descriptor_cid, clock_ms=self.clock_ms,
        )
        self.evidence = DatasetEvidenceStore(self.state_dir / "dataset-evidence.sqlite3", self.artifacts, self.clock_ms)
        self._catalog = self._build_catalog()
        mode = control_mode or ("local-test" if isinstance(facilitator, CallbackFacilitator) else "facilitator")
        self.control_plane = ProfileHControlPlane(
            runtime=self.runtime, catalog=self.catalog, bind=self._commercial_binding,
            reconcile=self.reconcile, evidence=self._control_evidence, mode=mode,
            upstream_x402_http_conformance=mode != "local-test",
        )

    def _build_catalog(self) -> dict[str, Any]:
        path = self.state_dir / "signed-datasets-catalog.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(saved, dict) and CatalogSigner.verify(saved)
                    and saved.get("catalogCid") == self.runtime.policy.catalog.cid
                    and saved.get("sellerDid") == self.config.seller_did
                    and saved.get("descriptorCid") == self.config.descriptor_cid):
                return saved
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        document = {
            "schema": "mcp++/profile-h/datasets-catalog@1.0", "createdAt": self.clock_ms(),
            "sellerDid": self.config.seller_did, "descriptorCid": self.config.descriptor_cid,
            "pricingModel": "fixed-dataset-version", **self.runtime.policy.catalog.public_document(),
        }
        signed = self.signer.sign(document)
        signed["signedCatalogCid"] = cid_for(signed)
        self.artifacts.put({key: value for key, value in signed.items() if key != "signedCatalogCid"})
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(canonical_json(signed))
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return signed

    def catalog(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._catalog))

    def _resolve_policy(self, operation: str, params: Mapping[str, Any]) -> tuple[str, DatasetPolicy]:
        dataset_id = str(params.get("datasetId", params.get("dataset_id", params.get("dataset", ""))))
        version = str(params.get("version", params.get("datasetVersion", params.get("dataset_version", ""))))
        matches = [(name, item) for name, item in self.config.datasets.items()
                   if item.dataset_id == dataset_id and item.version == version and operation in item.operations]
        if len(matches) != 1:
            raise DatasetPaymentError("H_DATASET_SCOPE_DENIED", "dataset/version is not a paid capability")
        return matches[0]

    @staticmethod
    def _values(value: Any) -> tuple[Any, ...]:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(value)
        return (value,)

    def _authorize(self, policy: DatasetPolicy, context: RequestContext,
                   params: Mapping[str, Any]) -> None:
        if not context.authorized or not context.policy_allowed:
            raise DatasetPaymentError("H_PAYMENT_POLICY_DENIED", "base authorization policy denied")

        tenant = context.attributes.get("tenant", context.attributes.get("tenant_id", _MISSING))
        requested_tenant = params.get("tenant", params.get("tenantId", tenant))
        if tenant is _MISSING or str(tenant) not in policy.tenants or str(requested_tenant) != str(tenant):
            raise DatasetPaymentError("H_TENANT_SCOPE_DENIED", "tenant scope denied")

        licenses = context.attributes.get("licenses", context.attributes.get("license", ()))
        license_values = {str(item) for item in self._values(licenses)}
        if policy.license_id not in license_values:
            raise DatasetPaymentError("H_LICENSE_REQUIRED", "dataset licence is not granted")

        fields = params.get("fields", params.get("projection", params.get("select", ())))
        selected = {str(item) for item in self._values(fields)} if fields not in (None, (), []) else set()
        if selected.intersection(policy.denied_fields):
            raise DatasetPaymentError("H_FIELD_SCOPE_DENIED", "a protected field was requested")
        if "*" not in policy.allowed_fields and (not selected or not selected.issubset(policy.allowed_fields)):
            raise DatasetPaymentError("H_FIELD_SCOPE_DENIED", "field projection exceeds the allowed scope")

        filters = params.get("rowFilter", params.get("row_filter", params.get("filters", {})))
        if not isinstance(filters, Mapping):
            raise DatasetPaymentError("H_ROW_SCOPE_DENIED", "row filter must be structured")
        for column, allowed in policy.row_constraints.items():
            if column not in filters:
                raise DatasetPaymentError("H_ROW_SCOPE_DENIED", "required tenant row filter is absent")
            requested = self._values(filters[column])
            if not requested or any(value not in allowed for value in requested):
                raise DatasetPaymentError("H_ROW_SCOPE_DENIED", "row filter exceeds the allowed scope")

        rows = params.get("limit", params.get("maxRows", params.get("max_rows", policy.max_rows)))
        if isinstance(rows, bool) or not isinstance(rows, int) or not 1 <= rows <= policy.max_rows:
            raise DatasetPaymentError("H_ROW_SCOPE_DENIED", "row limit exceeds the allowed scope")

        privacy = params.get("privacy", {})
        if not isinstance(privacy, Mapping):
            raise DatasetPaymentError("H_PRIVACY_POLICY_DENIED", "privacy policy must be structured")
        mode = str(privacy.get("mode", params.get("privacyMode", params.get("privacy_mode", "raw"))))
        if mode not in policy.privacy_modes:
            raise DatasetPaymentError("H_PRIVACY_POLICY_DENIED", "privacy mode is not permitted")
        epsilon = privacy.get("epsilon", params.get("epsilon"))
        if policy.max_epsilon is not None and mode == "dp":
            if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)) or not 0 < epsilon <= policy.max_epsilon:
                raise DatasetPaymentError("H_PRIVACY_POLICY_DENIED", "privacy epsilon exceeds policy")
        k_value = privacy.get("k", params.get("k"))
        if policy.minimum_k is not None:
            if isinstance(k_value, bool) or not isinstance(k_value, int) or k_value < policy.minimum_k:
                raise DatasetPaymentError("H_PRIVACY_POLICY_DENIED", "k-anonymity is below policy")

    @staticmethod
    def _private_input(operation: str, params: Mapping[str, Any]) -> dict[str, Any]:
        excluded = {"datasetId", "dataset_id", "dataset", "version", "datasetVersion", "dataset_version", "tenant", "tenantId"}
        return {"operation": operation, "arguments": {str(key): value for key, value in params.items() if key not in excluded}}

    def _bound_context(self, operation: str, policy: DatasetPolicy, context: RequestContext,
                       query_commitment: str) -> RequestContext:
        tenant = context.attributes.get("tenant", context.attributes.get("tenant_id", ""))
        subject = context.attributes.get("subject", "anonymous")
        bound_cid = cid_for({"callerRequestCid": context.request_cid, "operation": operation,
                             "dataset": policy.dataset_id, "version": policy.version,
                             "queryCommitment": query_commitment,
                             "tenantCommitment": commitment(tenant),
                             "subjectCommitment": commitment(subject),
                             "policyCommitment": policy.policy_commitment})
        return replace(context, request_cid=bound_cid)

    def _commercial_binding(self, operation: str, context: RequestContext,
                            params: Mapping[str, Any]) -> CommercialBinding:
        if operation not in _OPERATIONS:
            raise DatasetPaymentError("H_PAYMENT_POLICY_DENIED", "unknown protected dataset operation")
        name, policy = self._resolve_policy(operation, params)
        self._authorize(policy, context, params)
        private = commitment(self._private_input(operation, params))
        return CommercialBinding(f"tool:{operation}:{name}", self._bound_context(operation, policy, context, private))

    def _control_evidence(self, kind: str, cid: str, context: RequestContext) -> Mapping[str, Any] | None:
        record = self.evidence.get_by_evidence(cid)
        field = "entitlementCid" if kind == "entitlement" else "usageRecordCid"
        if not record or record.get(field) != cid:
            return None
        return self.artifacts.get(cid)

    async def profile_h(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch one complete Profile H control-plane operation."""
        return await self.control_plane.dispatch(method, params)

    async def dispatch(self, operation: str, context: RequestContext, params: Mapping[str, Any],
                       effect: Callable[..., Any], *, payment: PaymentContext | None = None) -> SellerResult:
        if operation not in _OPERATIONS:
            raise DatasetPaymentError("H_PAYMENT_POLICY_DENIED", "unknown protected dataset operation")
        if not isinstance(params, Mapping):
            raise DatasetPaymentError("H_REQUEST_MISMATCH", "dataset parameters must be structured")
        name, policy = self._resolve_policy(operation, params)
        private_input_commitment = commitment(self._private_input(operation, params))
        bound = self._bound_context(operation, policy, context, private_input_commitment)
        operation_key = f"tool:{operation}:{name}"

        # Preserve the shared runtime's normative denied result for base access
        # controls. Dataset-specific controls below use precise stable errors.
        if not context.authorized or not context.policy_allowed:
            return await self.runtime.dispatch(operation_key, bound, lambda: None, payment=payment)
        self._authorize(policy, context, params)

        # Payment contexts are wire-bound to the service's canonical request,
        # not to an arbitrary caller-provided CID.
        if payment is not None and payment.request_cid == context.request_cid:
            payment = PaymentContext(payment.payload, payment.quote_cid, bound.request_cid,
                                     payment.requirement_index)

        async def execute_after_payment() -> Any:
            # The second check is intentionally adjacent to data access: policy
            # may be mutable at a caller-controlled authorization boundary.
            self._authorize(policy, context, params)
            ledger = self.runtime.ledger.get(bound.idempotency_key)
            if not ledger or not ledger.settlement_cid:
                raise DatasetPaymentError("H_RECONCILIATION_REQUIRED", "settlement evidence is missing", retryable=True)
            tenant = str(context.attributes.get("tenant", context.attributes.get("tenant_id")))
            subject = str(context.attributes.get("subject", "anonymous"))
            record, existed = self.evidence.begin(
                context=bound, operation=operation, policy=policy,
                query_commitment=private_input_commitment, settlement_cid=ledger.settlement_cid,
                subject=subject, tenant=tenant,
            )
            if existed:
                if record["status"] in {"succeeded", "failed"}:
                    return self._record_envelope(record, recovered=True)
                raise DatasetPaymentError("H_RECONCILIATION_REQUIRED", "dataset work may already have started", retryable=True)
            handoff = {
                "executionId": record["executionId"], "operation": operation,
                "datasetId": policy.dataset_id, "datasetVersion": policy.version,
                "entitlementCid": record["entitlementCid"],
                "queryCommitment": private_input_commitment,
            }
            try:
                value = await self._invoke_effect(effect, handoff)
            except Exception as error:
                self.evidence.fail(record["executionId"], error)
                raise
            completed = self.evidence.finish(
                record["executionId"], value, policy=policy, operation=operation,
                requested_rows=params.get("limit", params.get("maxRows", params.get("max_rows"))),
            )
            envelope = self._record_envelope(completed)
            return {**dict(value), **envelope} if isinstance(value, Mapping) else {"result": value, **envelope}

        result = await self.runtime.dispatch(operation_key, bound, execute_after_payment, payment=payment)
        if result.replayed and result.value is None:
            record = self.evidence.get_by_key(bound.idempotency_key)
            if record:
                return replace(result, value=self._record_envelope(record, recovered=True))
        return result

    @staticmethod
    def _record_envelope(record: Mapping[str, Any], *, recovered: bool = False) -> dict[str, Any]:
        return {key: value for key, value in {
            "executionId": record["executionId"], "entitlementCid": record["entitlementCid"],
            "usageRecordCid": record.get("usageRecordCid"), "provenanceCid": record.get("provenanceCid"),
            "outputReceiptCid": record.get("outputReceiptCid"), "outcome": record["status"],
            "recovered": recovered or None,
        }.items() if value is not None}

    @staticmethod
    async def _invoke_effect(effect: Callable[..., Any], handoff: Mapping[str, Any]) -> Any:
        try:
            signature = inspect.signature(effect)
            accepts = any(item.kind in (item.VAR_POSITIONAL, item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)
                          for item in signature.parameters.values())
        except (TypeError, ValueError):
            accepts = False
        value = effect(dict(handoff)) if accepts else effect()
        return await value if inspect.isawaitable(value) else value

    async def handle_http(self, method: str, path: str, context: RequestContext,
                          params: Mapping[str, Any], effect: Callable[..., Any] | None = None, *,
                          payment_header: str | None = None) -> tuple[int, dict[str, str], Any]:
        method = method.upper()
        if method == "GET" and path == "/mcp/payments/catalog":
            return 200, {"ETag": self._catalog["signedCatalogCid"]}, self.catalog()
        evidence_prefixes = {
            "/mcp/payments/entitlements/": "entitlementCid",
            "/mcp/payments/usage/": "usageRecordCid",
            "/mcp/payments/provenance/": "provenanceCid",
            "/mcp/payments/outputs/": "outputReceiptCid",
        }
        for prefix, field_name in evidence_prefixes.items():
            if method == "GET" and path.startswith(prefix):
                if not context.authorized or not context.policy_allowed:
                    return 403, {}, {"error": "H_PAYMENT_POLICY_DENIED"}
                evidence_cid = path.removeprefix(prefix)
                record = self.evidence.get_by_evidence(evidence_cid)
                if not record or record[field_name] != evidence_cid:
                    return 404, {}, {"error": "H_EVIDENCE_NOT_FOUND"}
                artifact = self.artifacts.get(evidence_cid)
                return (200, {}, artifact) if artifact else (404, {}, {"error": "H_EVIDENCE_NOT_FOUND"})
        operation = self.ROUTES.get((method, path))
        if operation is None:
            return 404, {}, {"error": "H_PAYMENT_POLICY_DENIED"}
        if effect is None:
            raise ValueError("a protected dataset operation requires an effect callback")
        payment = self._decode_payment(payment_header) if payment_header else None
        try:
            return http_response(await self.dispatch(operation, context, params, effect, payment=payment))
        except DatasetPaymentError as error:
            return 403, {}, {"error": error.code}

    async def handle_libp2p(self, request: Mapping[str, Any], context: RequestContext,
                            effect: Callable[..., Any] | None = None) -> dict[str, Any]:
        operation = str(request.get("operation", ""))
        if operation == "mcp++/payments/catalog":
            return {"result": self.catalog()}
        params = request.get("params", {})
        if operation not in _OPERATIONS or not isinstance(params, Mapping) or effect is None:
            return {"error": {"code": "H_PAYMENT_POLICY_DENIED"}}
        raw = request.get("payment_context")
        payment = None
        if isinstance(raw, Mapping):
            payment = PaymentContext(raw.get("payload", {}), str(raw.get("quoteCid", "")),
                                     str(raw.get("requestCid", "")), int(raw.get("requirementIndex", 0)))
        try:
            return libp2p_response(await self.dispatch(operation, context, params, effect, payment=payment))
        except DatasetPaymentError as error:
            return {"error": {"code": error.code}}

    @staticmethod
    def _decode_payment(value: str) -> PaymentContext:
        try:
            data = json.loads(base64.b64decode(value, validate=True))
            return PaymentContext(data["payload"], data["quoteCid"], data["requestCid"],
                                  int(data.get("requirementIndex", 0)))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise DatasetPaymentError("H_INVALID_PAYMENT_MESSAGE", "invalid PAYMENT-SIGNATURE header") from error

    async def reconcile(self) -> dict[str, Any]:
        return {"payments": await self.runtime.reconcile(), "datasetExecutions": self.evidence.reconcile()}

    async def diagnostics(self) -> dict[str, Any]:
        base = await self.runtime.diagnostics()
        return {**base, "signedCatalogCid": self._catalog["signedCatalogCid"],
                "catalogSignatureValid": CatalogSigner.verify(self._catalog),
                "datasetVersions": sorted(item.dataset_version for item in self.config.datasets.values()),
                "datasetExecutions": self.evidence.diagnostics()}


PaidDatasetsService = PaidDatasetService
DatasetService = PaidDatasetService
DatasetsPaymentError = DatasetPaymentError

__all__ = [
    "CatalogSigner", "DatasetCapability", "DatasetEvidenceStore", "DatasetOffer",
    "DatasetPaymentConfig", "DatasetPaymentError", "DatasetPolicy", "DatasetService",
    "DatasetsPaymentConfig", "DatasetsPaymentError", "PaidDataset", "PaidDatasetService",
    "PaidDatasetsService",
]

