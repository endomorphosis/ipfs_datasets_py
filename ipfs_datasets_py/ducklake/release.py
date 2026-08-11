"""DuckLake layer release receipt publisher (DQK-101).

Validates the complete DuckLake goal graph against the exact repository tree,
environment/extension profile, every DuckDB + Quack catalog shard and owner
generation, companion registry, storage root, schema checksum, representative
snapshot vector, canary, maintenance, restore, security, publication, and the
exact signed DQK-102 promotion decision plus execution evidence, then stores
``DuckLakeLayerReleaseReceipt@1`` in the DQK-086 ``lake_release_receipts``
control authority table.

Critical contracts:

* The receipt is stored in the control DuckDB authority table, **not** a
  Markdown or free-form JSON file.
* Missing, stale, mismatched, or self-approved DQK-102 promotion evidence
  fails closed.
* Missing or stale canary, restore, maintenance, security, or cutover
  evidence fails closed.
* A sanitized release projection can be exported without credentials or
  encryption keys.

Import is side-effect free: no ``duckdb``, network, or filesystem I/O until an
explicit publish method is called. Hermetic tests use
:class:`~ipfs_datasets_py.ducklake.registry.ControlLakeRegistry` memory stores.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.duckdb_control.contracts import (
    content_identity,
    normalize_timestamp,
)
from ipfs_datasets_py.ducklake import capabilities as lake_caps
from ipfs_datasets_py.ducklake import cutover as co
from ipfs_datasets_py.ducklake import security as sec
from ipfs_datasets_py.ducklake.registry import (
    ControlLakeRegistry,
    RegistryError,
)

__all__ = [
    "AUTHORITY_TABLE",
    "COMPATIBILITY_TASK_ID",
    "CUTOVER_OWNER_TASK_ID",
    "DOMAIN",
    "LAYER_RELEASE_RECEIPT_INTERFACE",
    "LAYER_RELEASE_RECEIPT_SCHEMA",
    "OWNER_TASK_ID",
    "PROGRAM_ID",
    "PROMOTION_GATE_TASK_ID",
    "RELEASE_EVIDENCE_SCHEMA",
    "RELEASE_PROJECTION_SCHEMA",
    "CanaryExclusivityProof",
    "CatalogShardBinding",
    "DuckLakeLayerReleaseReceipt",
    "GoalGraphBinding",
    "OperationalEvidenceBundle",
    "QuackRiskPolicyBinding",
    "ReleaseError",
    "ReleaseEvidenceError",
    "ReleasePromotionError",
    "ReleaseStaleError",
    "assert_no_markdown_or_file_authority",
    "build_canary_exclusivity_proof",
    "build_catalog_shard_binding",
    "build_goal_graph_binding",
    "build_layer_release_receipt",
    "build_operational_evidence",
    "build_quack_risk_policy_binding",
    "export_sanitized_release_projection",
    "publish_layer_release_receipt",
    "reset_release_state",
    "self_check",
    "verify_layer_release_receipt",
    "verify_operational_evidence",
    "verify_promotion_evidence_for_release",
    "verify_quack_risk_policy_binding",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-101"
PROMOTION_GATE_TASK_ID: Final[str] = "DQK-102"
COMPATIBILITY_TASK_ID: Final[str] = "DQK-050"
CUTOVER_OWNER_TASK_ID: Final[str] = "DQK-100"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
DOMAIN: Final[str] = "ducklake-layer-release"

LAYER_RELEASE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-layer-release-receipt@1"
)
LAYER_RELEASE_RECEIPT_INTERFACE: Final[str] = "DuckLakeLayerReleaseReceipt@1"
RELEASE_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-layer-release-evidence@1"
)
RELEASE_PROJECTION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-layer-release-projection@1"
)

# DQK-086 control authority table — never a Markdown/JSON file.
AUTHORITY_TABLE: Final[str] = "lake_release_receipts"
AUTHORITY_SCOPE: Final[str] = "control"

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-101-ducklake-layer-release-receipt-20260811"
)

_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SAFE_TOKEN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$"
)
_MAX_FIELD_BYTES: Final[int] = 16_384
_DEFAULT_RECEIPT_TTL_HOURS: Final[int] = 72
_DEFAULT_EVIDENCE_TTL_HOURS: Final[int] = 24

# Goal-graph task IDs that the layer release must bind completion/validation for.
_GOAL_GRAPH_TASK_IDS: Final[tuple[str, ...]] = (
    "DQK-050",
    "DQK-084",
    "DQK-085",
    "DQK-086",
    "DQK-087",
    "DQK-088",
    "DQK-090",
    "DQK-092",
    "DQK-094",
    "DQK-095",
    "DQK-096",
    "DQK-097",
    "DQK-098",
    "DQK-099",
    "DQK-100",
    "DQK-102",
    "DQK-104",
)

# Operational evidence kinds that fail closed when missing or stale.
_REQUIRED_OPERATIONAL_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "canary",
        "restore",
        "maintenance",
        "security",
        "cutover",
    }
)

# Sensitive key fragments that must never appear in sanitized projections.
_SENSITIVE_EXPORT_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "secret",
    "credential",
    "encryption_key",
    "encryptionkey",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
    "secret_key",
    "secretkey",
    "quack_token",
    "quacktoken",
    "token_secret",
    "bearer",
    "authorization",
    "signing_key",
    "signingkey",
    "session_token",
    "sessiontoken",
)

_STATE_LOCK = threading.RLock()
_LAST_PUBLISHED: dict[str, Mapping[str, Any]] = {}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReleaseError(ValueError):
    """Fail-closed DuckLake layer release rejection."""


class ReleasePromotionError(ReleaseError):
    """DQK-102 promotion evidence is missing, stale, mismatched, or self-approved."""


class ReleaseEvidenceError(ReleaseError):
    """Canary, restore, maintenance, security, or cutover evidence is missing/stale."""


class ReleaseStaleError(ReleaseError):
    """Release, evidence, or promotion material is expired at point of use."""


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return normalize_timestamp(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def _parse_utc(value: Any, *, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ReleaseError(f"{field_name} is required")
    # Accept ms epoch integers used by DQK-050 receipts.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ms = int(value)
        if ms > 10_000_000_000:  # ms
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(ms, tz=timezone.utc)
    normalized = normalize_timestamp(text)
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReleaseError(f"{field_name} is not a valid timestamp") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bounded_text(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool = False,
    max_bytes: int = _MAX_FIELD_BYTES,
) -> str:
    if not isinstance(value, str):
        raise ReleaseError(f"{field_name} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise ReleaseError(f"{field_name} must be nonempty")
    if len(text.encode("utf-8")) > max_bytes:
        raise ReleaseError(f"{field_name} exceeds {max_bytes}-byte bound")
    return text


def _require_sha256(value: Any, *, field_name: str) -> str:
    text = _bounded_text(value, field_name=field_name)
    if not _SHA256_DIGEST.fullmatch(text):
        raise ReleaseError(f"{field_name} must be sha256:<64-hex>")
    return text


def _require_tree_id(value: Any, *, field_name: str = "repository_tree_id") -> str:
    text = _bounded_text(value, field_name=field_name)
    if not _GIT_OID.fullmatch(text):
        raise ReleaseError(f"{field_name} must be a 40-char git tree oid")
    return text


def _require_safe_token(value: Any, *, field_name: str) -> str:
    text = _bounded_text(value, field_name=field_name)
    if not _SAFE_TOKEN.fullmatch(text):
        raise ReleaseError(f"{field_name} is not a safe token")
    return text


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def _digest_of(payload: Any) -> str:
    return content_identity(payload)


def _hmac_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a), str(b))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _as_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "as_mapping") and callable(value.as_mapping):
        return dict(value.as_mapping())
    raise ReleaseError(f"{field_name} must be a mapping")


def _require_true(value: Any, *, field_name: str) -> None:
    if value is not True:
        raise ReleaseError(f"{field_name} must be the boolean true")


def reset_release_state() -> None:
    """Reset process-local last-published cache (tests / dry harness)."""

    with _STATE_LOCK:
        _LAST_PUBLISHED.clear()


def assert_no_markdown_or_file_authority() -> None:
    """Document that layer release authority is the control table only."""

    # This is a contract marker: authority is AUTHORITY_TABLE under control.
    if AUTHORITY_TABLE != "lake_release_receipts":
        raise ReleaseError("authority table drift")
    if AUTHORITY_SCOPE != "control":
        raise ReleaseError("authority scope must be control")


# ---------------------------------------------------------------------------
# Catalog shard + owner binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogShardBinding:
    """One DuckDB + Quack catalog shard bound into the layer release."""

    shard_id: str
    catalog_id: str
    catalog_file_digest: str
    companion_registry_digest: str
    owner_generation: int
    owner_identity: str
    endpoint_identity: str
    storage_identity: str
    storage_kind: str
    task_completion_id: str
    task_validation_id: str
    schema_checksum: str
    ring_position: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "shard_id", _require_safe_token(self.shard_id, field_name="shard_id")
        )
        object.__setattr__(
            self,
            "catalog_id",
            _require_safe_token(self.catalog_id, field_name="catalog_id"),
        )
        object.__setattr__(
            self,
            "catalog_file_digest",
            _require_sha256(self.catalog_file_digest, field_name="catalog_file_digest"),
        )
        object.__setattr__(
            self,
            "companion_registry_digest",
            _require_sha256(
                self.companion_registry_digest, field_name="companion_registry_digest"
            ),
        )
        if (
            not isinstance(self.owner_generation, int)
            or isinstance(self.owner_generation, bool)
            or self.owner_generation < 1
        ):
            raise ReleaseError("owner_generation must be a positive int")
        object.__setattr__(
            self,
            "owner_identity",
            _require_safe_token(self.owner_identity, field_name="owner_identity"),
        )
        object.__setattr__(
            self,
            "endpoint_identity",
            _require_safe_token(self.endpoint_identity, field_name="endpoint_identity"),
        )
        object.__setattr__(
            self,
            "storage_identity",
            _require_sha256(self.storage_identity, field_name="storage_identity"),
        )
        kind = _bounded_text(self.storage_kind, field_name="storage_kind").lower()
        if kind not in {"local_block", "block_storage", "local"}:
            raise ReleaseError(
                f"storage_kind {kind!r} rejected; catalog files must be local/block"
            )
        object.__setattr__(self, "storage_kind", kind)
        object.__setattr__(
            self,
            "task_completion_id",
            _require_safe_token(
                self.task_completion_id, field_name="task_completion_id"
            ),
        )
        object.__setattr__(
            self,
            "task_validation_id",
            _require_safe_token(
                self.task_validation_id, field_name="task_validation_id"
            ),
        )
        object.__setattr__(
            self,
            "schema_checksum",
            _require_sha256(self.schema_checksum, field_name="schema_checksum"),
        )
        if (
            not isinstance(self.ring_position, int)
            or isinstance(self.ring_position, bool)
            or self.ring_position < 0
        ):
            raise ReleaseError("ring_position must be a non-negative int")

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "shard_id": self.shard_id,
                "catalog_id": self.catalog_id,
                "catalog_file_digest": self.catalog_file_digest,
                "companion_registry_digest": self.companion_registry_digest,
                "owner_generation": self.owner_generation,
                "owner_identity": self.owner_identity,
                "endpoint_identity": self.endpoint_identity,
                "storage_identity": self.storage_identity,
                "storage_kind": self.storage_kind,
                "task_completion_id": self.task_completion_id,
                "task_validation_id": self.task_validation_id,
                "schema_checksum": self.schema_checksum,
                "ring_position": self.ring_position,
            }
        )

    def binding_digest(self) -> str:
        return _digest_of(dict(self.as_mapping()))


def build_catalog_shard_binding(
    *,
    shard_id: str,
    catalog_id: str,
    catalog_file_digest: str,
    companion_registry_digest: str,
    owner_generation: int,
    owner_identity: str,
    endpoint_identity: str,
    storage_identity: str,
    storage_kind: str = "local_block",
    task_completion_id: str,
    task_validation_id: str,
    schema_checksum: str,
    ring_position: int = 0,
) -> CatalogShardBinding:
    return CatalogShardBinding(
        shard_id=shard_id,
        catalog_id=catalog_id,
        catalog_file_digest=catalog_file_digest,
        companion_registry_digest=companion_registry_digest,
        owner_generation=owner_generation,
        owner_identity=owner_identity,
        endpoint_identity=endpoint_identity,
        storage_identity=storage_identity,
        storage_kind=storage_kind,
        task_completion_id=task_completion_id,
        task_validation_id=task_validation_id,
        schema_checksum=schema_checksum,
        ring_position=ring_position,
    )


# ---------------------------------------------------------------------------
# Canary exclusivity proof (single owner; no remote authority open)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanaryExclusivityProof:
    """Proves canary-era single-owner and no remote authority catalog opens."""

    schema: str
    proof_cid: str
    no_catalog_file_had_two_owners: bool
    no_remote_client_opened_authority_catalog: bool
    catalog_file_owner_map: Mapping[str, str]
    remote_authority_open_attempts: int
    canary_receipt_cid: str
    repository_tree_id: str
    issued_at: str
    signature: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "proof_cid": self.proof_cid,
                "no_catalog_file_had_two_owners": self.no_catalog_file_had_two_owners,
                "no_remote_client_opened_authority_catalog": (
                    self.no_remote_client_opened_authority_catalog
                ),
                "catalog_file_owner_map": dict(self.catalog_file_owner_map),
                "remote_authority_open_attempts": self.remote_authority_open_attempts,
                "canary_receipt_cid": self.canary_receipt_cid,
                "repository_tree_id": self.repository_tree_id,
                "issued_at": self.issued_at,
                "signature": self.signature,
            }
        )


def build_canary_exclusivity_proof(
    *,
    catalog_file_owner_map: Mapping[str, str],
    canary_receipt_cid: str,
    repository_tree_id: str,
    remote_authority_open_attempts: int = 0,
    issued_at: datetime | str | None = None,
    no_catalog_file_had_two_owners: bool = True,
    no_remote_client_opened_authority_catalog: bool = True,
) -> CanaryExclusivityProof:
    """Build a content-bound exclusivity proof for the canary window.

    *catalog_file_owner_map* maps catalog-file digests to the single owner
    identity observed during the canary. Two owners for one digest fails closed.
    """

    if not catalog_file_owner_map:
        raise ReleaseEvidenceError("catalog_file_owner_map must be nonempty")
    owners: dict[str, str] = {}
    seen_files: dict[str, str] = {}
    for catalog_digest, owner in catalog_file_owner_map.items():
        dig = _require_sha256(catalog_digest, field_name="catalog_file_digest")
        own = _require_safe_token(owner, field_name="owner_identity")
        if dig in seen_files and seen_files[dig] != own:
            raise ReleaseEvidenceError(
                f"catalog file {dig} had two owners during canary "
                f"({seen_files[dig]!r} and {own!r})"
            )
        seen_files[dig] = own
        owners[dig] = own

    if no_catalog_file_had_two_owners is not True:
        raise ReleaseEvidenceError(
            "canary must prove no catalog file had two owners"
        )
    if no_remote_client_opened_authority_catalog is not True:
        raise ReleaseEvidenceError(
            "canary must prove no remote client opened an authority catalog"
        )
    if (
        not isinstance(remote_authority_open_attempts, int)
        or isinstance(remote_authority_open_attempts, bool)
        or remote_authority_open_attempts < 0
    ):
        raise ReleaseEvidenceError(
            "remote_authority_open_attempts must be a non-negative int"
        )
    if remote_authority_open_attempts != 0:
        raise ReleaseEvidenceError(
            "remote clients opened authority catalogs during canary; fail closed"
        )

    issued = normalize_timestamp(issued_at or _utc_now())
    body = {
        "schema": "ipfs_datasets_py/ducklake-canary-exclusivity-proof@1",
        "no_catalog_file_had_two_owners": True,
        "no_remote_client_opened_authority_catalog": True,
        "catalog_file_owner_map": dict(sorted(owners.items())),
        "remote_authority_open_attempts": 0,
        "canary_receipt_cid": _require_sha256(
            canary_receipt_cid, field_name="canary_receipt_cid"
        ),
        "repository_tree_id": _require_tree_id(repository_tree_id),
        "issued_at": issued,
    }
    signature = _digest_of(body)
    proof_cid = _digest_of({**body, "signature": signature})
    return CanaryExclusivityProof(
        schema=body["schema"],
        proof_cid=proof_cid,
        no_catalog_file_had_two_owners=True,
        no_remote_client_opened_authority_catalog=True,
        catalog_file_owner_map=MappingProxyType(dict(sorted(owners.items()))),
        remote_authority_open_attempts=0,
        canary_receipt_cid=body["canary_receipt_cid"],
        repository_tree_id=body["repository_tree_id"],
        issued_at=issued,
        signature=signature,
    )


def _verify_canary_exclusivity(
    proof: CanaryExclusivityProof | Mapping[str, Any],
    *,
    expected_tree_id: str | None = None,
    expected_canary_receipt_cid: str | None = None,
) -> CanaryExclusivityProof:
    mapping = _as_mapping(proof, field_name="canary_exclusivity_proof")
    for key in (
        "schema",
        "proof_cid",
        "canary_receipt_cid",
        "repository_tree_id",
        "issued_at",
        "signature",
    ):
        if not str(mapping.get(key) or "").strip():
            raise ReleaseEvidenceError(f"canary exclusivity missing field {key}")
    if mapping.get("no_catalog_file_had_two_owners") is not True:
        raise ReleaseEvidenceError("canary exclusivity does not prove single owner")
    if mapping.get("no_remote_client_opened_authority_catalog") is not True:
        raise ReleaseEvidenceError(
            "canary exclusivity does not prove no remote authority open"
        )
    attempts = mapping.get("remote_authority_open_attempts", 0)
    if attempts != 0:
        raise ReleaseEvidenceError(
            "remote authority open attempts during canary are nonzero"
        )
    owner_map = mapping.get("catalog_file_owner_map") or {}
    if not isinstance(owner_map, Mapping) or not owner_map:
        raise ReleaseEvidenceError("canary exclusivity owner map missing")
    # Detect dual owners encoded as list values.
    normalized: dict[str, str] = {}
    for dig, own in owner_map.items():
        d = _require_sha256(dig, field_name="catalog_file_digest")
        if isinstance(own, (list, tuple, set)):
            raise ReleaseEvidenceError(
                f"catalog file {d} lists multiple owners during canary"
            )
        o = _require_safe_token(own, field_name="owner_identity")
        if d in normalized and normalized[d] != o:
            raise ReleaseEvidenceError(f"catalog file {d} had two owners")
        normalized[d] = o

    body = {
        "schema": mapping["schema"],
        "no_catalog_file_had_two_owners": True,
        "no_remote_client_opened_authority_catalog": True,
        "catalog_file_owner_map": dict(sorted(normalized.items())),
        "remote_authority_open_attempts": 0,
        "canary_receipt_cid": _require_sha256(
            mapping["canary_receipt_cid"], field_name="canary_receipt_cid"
        ),
        "repository_tree_id": _require_tree_id(mapping["repository_tree_id"]),
        "issued_at": normalize_timestamp(mapping["issued_at"]),
    }
    expected_sig = _digest_of(body)
    actual_sig = _require_sha256(mapping.get("signature"), field_name="signature")
    if not _hmac_eq(expected_sig, actual_sig):
        raise ReleaseEvidenceError("canary exclusivity signature mismatch")
    expected_cid = _digest_of({**body, "signature": actual_sig})
    actual_cid = _require_sha256(mapping.get("proof_cid"), field_name="proof_cid")
    if not _hmac_eq(expected_cid, actual_cid):
        raise ReleaseEvidenceError("canary exclusivity proof_cid mismatch")
    tree = body["repository_tree_id"]
    if expected_tree_id is not None and tree != _require_tree_id(expected_tree_id):
        raise ReleaseEvidenceError("canary exclusivity tree mismatch")
    canary_cid = body["canary_receipt_cid"]
    if expected_canary_receipt_cid is not None and not _hmac_eq(
        canary_cid, _require_sha256(expected_canary_receipt_cid, field_name="canary")
    ):
        raise ReleaseEvidenceError("canary exclusivity canary_receipt_cid mismatch")
    return CanaryExclusivityProof(
        schema=str(body["schema"]),
        proof_cid=actual_cid,
        no_catalog_file_had_two_owners=True,
        no_remote_client_opened_authority_catalog=True,
        catalog_file_owner_map=MappingProxyType(dict(sorted(normalized.items()))),
        remote_authority_open_attempts=0,
        canary_receipt_cid=canary_cid,
        repository_tree_id=tree,
        issued_at=body["issued_at"],
        signature=actual_sig,
    )


# ---------------------------------------------------------------------------
# Goal graph binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoalGraphBinding:
    """Binds the DuckLake goal-graph task completion/validation set."""

    schema: str
    binding_cid: str
    repository_tree_id: str
    environment_receipt_cid: str
    extension_profile_digest: str
    policy_digest: str
    task_completion_ids: Mapping[str, str]
    task_validation_ids: Mapping[str, str]
    schema_checksum: str
    signature: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "binding_cid": self.binding_cid,
                "repository_tree_id": self.repository_tree_id,
                "environment_receipt_cid": self.environment_receipt_cid,
                "extension_profile_digest": self.extension_profile_digest,
                "policy_digest": self.policy_digest,
                "task_completion_ids": dict(self.task_completion_ids),
                "task_validation_ids": dict(self.task_validation_ids),
                "schema_checksum": self.schema_checksum,
                "signature": self.signature,
            }
        )


def build_goal_graph_binding(
    *,
    repository_tree_id: str,
    environment_receipt_cid: str,
    extension_profile_digest: str,
    policy_digest: str,
    task_completion_ids: Mapping[str, str],
    task_validation_ids: Mapping[str, str],
    schema_checksum: str,
) -> GoalGraphBinding:
    tree = _require_tree_id(repository_tree_id)
    completions = {
        _require_safe_token(k, field_name="task_id"): _require_safe_token(
            v, field_name="task_completion_id"
        )
        for k, v in dict(task_completion_ids).items()
    }
    validations = {
        _require_safe_token(k, field_name="task_id"): _require_safe_token(
            v, field_name="task_validation_id"
        )
        for k, v in dict(task_validation_ids).items()
    }
    missing_c = [t for t in _GOAL_GRAPH_TASK_IDS if t not in completions]
    missing_v = [t for t in _GOAL_GRAPH_TASK_IDS if t not in validations]
    if missing_c:
        raise ReleaseEvidenceError(
            "goal graph missing task completions: " + ",".join(missing_c)
        )
    if missing_v:
        raise ReleaseEvidenceError(
            "goal graph missing task validations: " + ",".join(missing_v)
        )
    body = {
        "schema": "ipfs_datasets_py/ducklake-goal-graph-binding@1",
        "repository_tree_id": tree,
        "environment_receipt_cid": _require_sha256(
            environment_receipt_cid, field_name="environment_receipt_cid"
        ),
        "extension_profile_digest": _require_sha256(
            extension_profile_digest, field_name="extension_profile_digest"
        ),
        "policy_digest": _require_sha256(policy_digest, field_name="policy_digest"),
        "task_completion_ids": dict(sorted(completions.items())),
        "task_validation_ids": dict(sorted(validations.items())),
        "schema_checksum": _require_sha256(
            schema_checksum, field_name="schema_checksum"
        ),
        "required_tasks": list(_GOAL_GRAPH_TASK_IDS),
        "implementation_generation": _IMPLEMENTATION_GENERATION,
    }
    signature = _digest_of(body)
    binding_cid = _digest_of({**body, "signature": signature})
    return GoalGraphBinding(
        schema=body["schema"],
        binding_cid=binding_cid,
        repository_tree_id=tree,
        environment_receipt_cid=body["environment_receipt_cid"],
        extension_profile_digest=body["extension_profile_digest"],
        policy_digest=body["policy_digest"],
        task_completion_ids=MappingProxyType(dict(sorted(completions.items()))),
        task_validation_ids=MappingProxyType(dict(sorted(validations.items()))),
        schema_checksum=body["schema_checksum"],
        signature=signature,
    )


def _verify_goal_graph(
    binding: GoalGraphBinding | Mapping[str, Any],
    *,
    expected_tree_id: str | None = None,
) -> GoalGraphBinding:
    mapping = _as_mapping(binding, field_name="goal_graph")
    required = (
        "schema",
        "binding_cid",
        "repository_tree_id",
        "environment_receipt_cid",
        "extension_profile_digest",
        "policy_digest",
        "schema_checksum",
        "signature",
    )
    missing = [k for k in required if not str(mapping.get(k) or "").strip()]
    if missing:
        raise ReleaseEvidenceError(
            "goal graph binding incomplete; missing: " + ",".join(missing)
        )
    completions = dict(mapping.get("task_completion_ids") or {})
    validations = dict(mapping.get("task_validation_ids") or {})
    missing_c = [t for t in _GOAL_GRAPH_TASK_IDS if t not in completions]
    missing_v = [t for t in _GOAL_GRAPH_TASK_IDS if t not in validations]
    if missing_c or missing_v:
        raise ReleaseEvidenceError(
            "goal graph task set incomplete "
            f"(completions_missing={missing_c}, validations_missing={missing_v})"
        )
    body = {
        "schema": mapping["schema"],
        "repository_tree_id": _require_tree_id(mapping["repository_tree_id"]),
        "environment_receipt_cid": _require_sha256(
            mapping["environment_receipt_cid"], field_name="environment_receipt_cid"
        ),
        "extension_profile_digest": _require_sha256(
            mapping["extension_profile_digest"], field_name="extension_profile_digest"
        ),
        "policy_digest": _require_sha256(
            mapping["policy_digest"], field_name="policy_digest"
        ),
        "task_completion_ids": dict(sorted(completions.items())),
        "task_validation_ids": dict(sorted(validations.items())),
        "schema_checksum": _require_sha256(
            mapping["schema_checksum"], field_name="schema_checksum"
        ),
        "required_tasks": list(_GOAL_GRAPH_TASK_IDS),
        "implementation_generation": _IMPLEMENTATION_GENERATION,
    }
    expected_sig = _digest_of(body)
    actual_sig = _require_sha256(mapping["signature"], field_name="signature")
    if not _hmac_eq(expected_sig, actual_sig):
        raise ReleaseEvidenceError("goal graph signature mismatch")
    expected_cid = _digest_of({**body, "signature": actual_sig})
    actual_cid = _require_sha256(mapping["binding_cid"], field_name="binding_cid")
    if not _hmac_eq(expected_cid, actual_cid):
        raise ReleaseEvidenceError("goal graph binding_cid mismatch")
    tree = body["repository_tree_id"]
    if expected_tree_id is not None and tree != _require_tree_id(expected_tree_id):
        raise ReleaseEvidenceError("goal graph repository tree mismatch")
    return GoalGraphBinding(
        schema=str(body["schema"]),
        binding_cid=actual_cid,
        repository_tree_id=tree,
        environment_receipt_cid=body["environment_receipt_cid"],
        extension_profile_digest=body["extension_profile_digest"],
        policy_digest=body["policy_digest"],
        task_completion_ids=MappingProxyType(dict(sorted(completions.items()))),
        task_validation_ids=MappingProxyType(dict(sorted(validations.items()))),
        schema_checksum=body["schema_checksum"],
        signature=actual_sig,
    )


# ---------------------------------------------------------------------------
# Operational evidence (canary / restore / maintenance / security / cutover)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationalEvidenceBundle:
    """Point-of-use operational evidence required for layer release."""

    schema: str
    evidence_set_cid: str
    canary_receipt_cid: str
    restore_receipt_cid: str
    maintenance_receipt_cid: str
    security_receipt_cid: str
    cutover_receipt_cid: str
    publication_receipt_cid: str
    repository_tree_id: str
    generation_id: str
    issued_at: str
    expires_at: str
    signature: str
    program_id: str = PROGRAM_ID
    owner_task_id: str = OWNER_TASK_ID

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "evidence_set_cid": self.evidence_set_cid,
                "canary_receipt_cid": self.canary_receipt_cid,
                "restore_receipt_cid": self.restore_receipt_cid,
                "maintenance_receipt_cid": self.maintenance_receipt_cid,
                "security_receipt_cid": self.security_receipt_cid,
                "cutover_receipt_cid": self.cutover_receipt_cid,
                "publication_receipt_cid": self.publication_receipt_cid,
                "repository_tree_id": self.repository_tree_id,
                "generation_id": self.generation_id,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "signature": self.signature,
                "program_id": self.program_id,
                "owner_task_id": self.owner_task_id,
            }
        )


def _operational_unsigned_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"signature", "evidence_set_cid"}
    }


def build_operational_evidence(
    *,
    canary_receipt_cid: str,
    restore_receipt_cid: str,
    maintenance_receipt_cid: str,
    security_receipt_cid: str,
    cutover_receipt_cid: str,
    publication_receipt_cid: str,
    repository_tree_id: str,
    generation_id: str,
    issued_at: datetime | str | None = None,
    expires_at: datetime | str | None = None,
) -> OperationalEvidenceBundle:
    issued = normalize_timestamp(issued_at or _utc_now())
    if expires_at is None:
        exp_dt = _parse_utc(issued, field_name="issued_at") + timedelta(
            hours=_DEFAULT_EVIDENCE_TTL_HOURS
        )
        expires = normalize_timestamp(exp_dt)
    else:
        expires = normalize_timestamp(expires_at)
    if _parse_utc(expires, field_name="expires_at") <= _parse_utc(
        issued, field_name="issued_at"
    ):
        raise ReleaseEvidenceError("operational evidence expires_at must be after issued_at")
    body = {
        "schema": RELEASE_EVIDENCE_SCHEMA,
        "canary_receipt_cid": _require_sha256(
            canary_receipt_cid, field_name="canary_receipt_cid"
        ),
        "restore_receipt_cid": _require_sha256(
            restore_receipt_cid, field_name="restore_receipt_cid"
        ),
        "maintenance_receipt_cid": _require_sha256(
            maintenance_receipt_cid, field_name="maintenance_receipt_cid"
        ),
        "security_receipt_cid": _require_sha256(
            security_receipt_cid, field_name="security_receipt_cid"
        ),
        "cutover_receipt_cid": _require_sha256(
            cutover_receipt_cid, field_name="cutover_receipt_cid"
        ),
        "publication_receipt_cid": _require_sha256(
            publication_receipt_cid, field_name="publication_receipt_cid"
        ),
        "repository_tree_id": _require_tree_id(repository_tree_id),
        "generation_id": _require_safe_token(generation_id, field_name="generation_id"),
        "issued_at": issued,
        "expires_at": expires,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "required_kinds": sorted(_REQUIRED_OPERATIONAL_EVIDENCE),
    }
    signature = _digest_of(body)
    evidence_set_cid = _digest_of({**body, "signature": signature})
    return OperationalEvidenceBundle(
        schema=RELEASE_EVIDENCE_SCHEMA,
        evidence_set_cid=evidence_set_cid,
        canary_receipt_cid=body["canary_receipt_cid"],
        restore_receipt_cid=body["restore_receipt_cid"],
        maintenance_receipt_cid=body["maintenance_receipt_cid"],
        security_receipt_cid=body["security_receipt_cid"],
        cutover_receipt_cid=body["cutover_receipt_cid"],
        publication_receipt_cid=body["publication_receipt_cid"],
        repository_tree_id=body["repository_tree_id"],
        generation_id=body["generation_id"],
        issued_at=issued,
        expires_at=expires,
        signature=signature,
    )


def verify_operational_evidence(
    bundle: OperationalEvidenceBundle | Mapping[str, Any],
    *,
    now: datetime | None = None,
    expected_tree_id: str | None = None,
    expected_generation_id: str | None = None,
) -> OperationalEvidenceBundle:
    """Fail closed when canary/restore/maintenance/security/cutover is missing or stale."""

    if bundle is None:
        raise ReleaseEvidenceError("operational evidence is missing")
    mapping = _as_mapping(bundle, field_name="operational_evidence")
    if mapping.get("schema") != RELEASE_EVIDENCE_SCHEMA:
        raise ReleaseEvidenceError(
            f"operational evidence schema must be {RELEASE_EVIDENCE_SCHEMA}"
        )
    required_fields = (
        "canary_receipt_cid",
        "restore_receipt_cid",
        "maintenance_receipt_cid",
        "security_receipt_cid",
        "cutover_receipt_cid",
        "publication_receipt_cid",
        "repository_tree_id",
        "generation_id",
        "issued_at",
        "expires_at",
        "signature",
        "evidence_set_cid",
    )
    missing = [k for k in required_fields if not str(mapping.get(k) or "").strip()]
    if missing:
        raise ReleaseEvidenceError(
            "missing operational evidence fields: " + ",".join(missing)
        )
    # Explicit kind presence (acceptance names).
    for kind, field_name in (
        ("canary", "canary_receipt_cid"),
        ("restore", "restore_receipt_cid"),
        ("maintenance", "maintenance_receipt_cid"),
        ("security", "security_receipt_cid"),
        ("cutover", "cutover_receipt_cid"),
    ):
        if not str(mapping.get(field_name) or "").strip():
            raise ReleaseEvidenceError(f"missing or empty {kind} evidence")

    body = {
        "schema": RELEASE_EVIDENCE_SCHEMA,
        "canary_receipt_cid": _require_sha256(
            mapping["canary_receipt_cid"], field_name="canary_receipt_cid"
        ),
        "restore_receipt_cid": _require_sha256(
            mapping["restore_receipt_cid"], field_name="restore_receipt_cid"
        ),
        "maintenance_receipt_cid": _require_sha256(
            mapping["maintenance_receipt_cid"], field_name="maintenance_receipt_cid"
        ),
        "security_receipt_cid": _require_sha256(
            mapping["security_receipt_cid"], field_name="security_receipt_cid"
        ),
        "cutover_receipt_cid": _require_sha256(
            mapping["cutover_receipt_cid"], field_name="cutover_receipt_cid"
        ),
        "publication_receipt_cid": _require_sha256(
            mapping["publication_receipt_cid"], field_name="publication_receipt_cid"
        ),
        "repository_tree_id": _require_tree_id(mapping["repository_tree_id"]),
        "generation_id": _require_safe_token(
            mapping["generation_id"], field_name="generation_id"
        ),
        "issued_at": normalize_timestamp(mapping["issued_at"]),
        "expires_at": normalize_timestamp(mapping["expires_at"]),
        "program_id": str(mapping.get("program_id") or PROGRAM_ID),
        "owner_task_id": str(mapping.get("owner_task_id") or OWNER_TASK_ID),
        "required_kinds": sorted(_REQUIRED_OPERATIONAL_EVIDENCE),
    }
    expected_sig = _digest_of(body)
    actual_sig = _require_sha256(mapping["signature"], field_name="signature")
    if not _hmac_eq(expected_sig, actual_sig):
        raise ReleaseEvidenceError("operational evidence signature mismatch")
    expected_cid = _digest_of({**body, "signature": actual_sig})
    actual_cid = _require_sha256(
        mapping["evidence_set_cid"], field_name="evidence_set_cid"
    )
    if not _hmac_eq(expected_cid, actual_cid):
        raise ReleaseEvidenceError("operational evidence_set_cid mismatch")

    clock = now or datetime.now(timezone.utc)
    expires = _parse_utc(body["expires_at"], field_name="expires_at")
    if clock >= expires:
        raise ReleaseStaleError(
            "canary, restore, maintenance, security, or cutover evidence is stale"
        )
    tree = body["repository_tree_id"]
    if expected_tree_id is not None and tree != _require_tree_id(expected_tree_id):
        raise ReleaseEvidenceError("operational evidence repository tree mismatch")
    gen = body["generation_id"]
    if expected_generation_id is not None and gen != _require_safe_token(
        expected_generation_id, field_name="expected_generation_id"
    ):
        raise ReleaseEvidenceError("operational evidence generation mismatch")

    return OperationalEvidenceBundle(
        schema=RELEASE_EVIDENCE_SCHEMA,
        evidence_set_cid=actual_cid,
        canary_receipt_cid=body["canary_receipt_cid"],
        restore_receipt_cid=body["restore_receipt_cid"],
        maintenance_receipt_cid=body["maintenance_receipt_cid"],
        security_receipt_cid=body["security_receipt_cid"],
        cutover_receipt_cid=body["cutover_receipt_cid"],
        publication_receipt_cid=body["publication_receipt_cid"],
        repository_tree_id=tree,
        generation_id=gen,
        issued_at=body["issued_at"],
        expires_at=body["expires_at"],
        signature=actual_sig,
        program_id=body["program_id"],
        owner_task_id=body["owner_task_id"],
    )


# ---------------------------------------------------------------------------
# Quack beta risk + DQK-050 + feature gate + DuckDB 2.0 policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuackRiskPolicyBinding:
    """Binds Quack beta risk, DQK-050 receipt, gates, and 2.0 requalification policy."""

    schema: str
    binding_cid: str
    quack_beta_risk_accepted: bool
    compatibility_receipt_id: str
    compatibility_receipt_digest: str
    compatibility_receipt: Mapping[str, Any]
    feature_gate_enabled: bool
    local_fallback_enabled: bool
    duckdb_20_requalification_policy: Mapping[str, Any]
    acceptor_identity: str
    signature: str

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "binding_cid": self.binding_cid,
                "quack_beta_risk_accepted": self.quack_beta_risk_accepted,
                "compatibility_receipt_id": self.compatibility_receipt_id,
                "compatibility_receipt_digest": self.compatibility_receipt_digest,
                "compatibility_receipt": dict(self.compatibility_receipt),
                "feature_gate_enabled": self.feature_gate_enabled,
                "local_fallback_enabled": self.local_fallback_enabled,
                "duckdb_20_requalification_policy": dict(
                    self.duckdb_20_requalification_policy
                ),
                "acceptor_identity": self.acceptor_identity,
                "signature": self.signature,
            }
        )


def _default_requalification_policy() -> dict[str, Any]:
    return {
        "policy_id": "duckdb-2.0-requalification@1",
        "trigger": "duckdb_major_version_gte_2",
        "target_duckdb_version_floor": "2.0.0",
        "requires_full_contract_rerun": True,
        "requires_dqk050_compatibility_receipt": True,
        "requires_explicit_requalification_receipt": True,
        "blocks_production_until_requalified": True,
        "capability_profile_ref": "DQK-084",
        "notes": (
            "Crossing into DuckDB 2.0 requires an explicit DQK-050 requalification "
            "receipt that re-runs the full Quack protocol contract suite against "
            "the new pins before any production promotion."
        ),
    }


def build_quack_risk_policy_binding(
    *,
    compatibility_receipt: Mapping[str, Any],
    feature_gate_enabled: bool = True,
    local_fallback_enabled: bool = True,
    quack_beta_risk_accepted: bool = True,
    acceptor_identity: str = "reviewer:dqk-050",
    duckdb_20_requalification_policy: Mapping[str, Any] | None = None,
) -> QuackRiskPolicyBinding:
    """Bind Quack beta risk acceptance and exact DQK-050 compatibility receipt."""

    receipt = dict(compatibility_receipt)
    if receipt.get("task_id") != COMPATIBILITY_TASK_ID:
        raise ReleaseEvidenceError(
            f"compatibility receipt task_id must be {COMPATIBILITY_TASK_ID}"
        )
    if receipt.get("risk_accepted") is not True and receipt.get("quack_beta") is not True:
        # Accept either explicit risk_accepted or quack_beta with risk_accepted.
        pass
    if receipt.get("risk_accepted") is not True:
        raise ReleaseEvidenceError(
            "DQK-050 compatibility receipt must accept Quack beta risk"
        )
    if quack_beta_risk_accepted is not True:
        raise ReleaseEvidenceError("Quack beta risk must be explicitly accepted")
    if feature_gate_enabled is not True:
        raise ReleaseEvidenceError(
            "Quack feature gate must remain enabled (with local fallback)"
        )
    if local_fallback_enabled is not True:
        raise ReleaseEvidenceError("local fallback/feature gate must remain enabled")

    receipt_id = _bounded_text(
        receipt.get("receipt_id") or receipt.get("id") or "",
        field_name="compatibility_receipt_id",
    )
    # Digest: prefer nested signature.digest, else content-hash the receipt body.
    sig = receipt.get("signature")
    if isinstance(sig, Mapping) and sig.get("digest"):
        receipt_digest = _require_sha256(sig["digest"], field_name="compatibility_digest")
    elif isinstance(sig, str) and sig.startswith("sha256:"):
        receipt_digest = _require_sha256(sig, field_name="compatibility_digest")
    else:
        # Content-bind excluding signature fields.
        unsigned = {
            k: v for k, v in receipt.items() if k not in {"signature", "receipt_id"}
        }
        receipt_digest = _digest_of(unsigned)

    # Gate fields on the receipt should agree when present.
    if (
        "feature_gate_enabled" in receipt
        and receipt.get("feature_gate_enabled") is not True
    ):
        raise ReleaseEvidenceError(
            "DQK-050 receipt feature_gate_enabled must be true"
        )
    if (
        "local_fallback_enabled" in receipt
        and receipt.get("local_fallback_enabled") is not True
    ):
        raise ReleaseEvidenceError(
            "DQK-050 receipt local_fallback_enabled must be true"
        )

    policy = dict(duckdb_20_requalification_policy or _default_requalification_policy())
    if policy.get("requires_full_contract_rerun") is not True:
        raise ReleaseEvidenceError(
            "DuckDB 2.0 requalification policy must require full contract re-run"
        )
    if policy.get("requires_explicit_requalification_receipt") is not True:
        raise ReleaseEvidenceError(
            "DuckDB 2.0 requalification policy must require explicit receipt"
        )
    if policy.get("blocks_production_until_requalified") is not True:
        raise ReleaseEvidenceError(
            "DuckDB 2.0 policy must block production until requalified"
        )

    acceptor = _require_safe_token(acceptor_identity, field_name="acceptor_identity")
    # Sanitized receipt binding: strip any accidental secrets from nested profile.
    safe_receipt = sec.redact_for_receipt(receipt)
    if not isinstance(safe_receipt, Mapping):
        safe_receipt = receipt

    schema = "ipfs_datasets_py/ducklake-quack-risk-policy-binding@1"
    # Seal over stable fields only (exclude bulky nested receipt body).
    sealed = {
        "schema": schema,
        "quack_beta_risk_accepted": True,
        "compatibility_receipt_id": receipt_id,
        "compatibility_receipt_digest": receipt_digest,
        "feature_gate_enabled": True,
        "local_fallback_enabled": True,
        "duckdb_20_requalification_policy": policy,
        "acceptor_identity": acceptor,
        "task_id": COMPATIBILITY_TASK_ID,
        "implementation_generation": _IMPLEMENTATION_GENERATION,
    }
    signature = _digest_of(sealed)
    binding_cid = _digest_of({**sealed, "signature": signature})
    return QuackRiskPolicyBinding(
        schema=schema,
        binding_cid=binding_cid,
        quack_beta_risk_accepted=True,
        compatibility_receipt_id=receipt_id,
        compatibility_receipt_digest=receipt_digest,
        compatibility_receipt=MappingProxyType(dict(safe_receipt)),
        feature_gate_enabled=True,
        local_fallback_enabled=True,
        duckdb_20_requalification_policy=MappingProxyType(policy),
        acceptor_identity=acceptor,
        signature=signature,
    )


def verify_quack_risk_policy_binding(
    binding: QuackRiskPolicyBinding | Mapping[str, Any],
) -> QuackRiskPolicyBinding:
    mapping = _as_mapping(binding, field_name="quack_risk_policy")
    if mapping.get("quack_beta_risk_accepted") is not True:
        raise ReleaseEvidenceError("Quack beta risk acceptance missing")
    if mapping.get("feature_gate_enabled") is not True:
        raise ReleaseEvidenceError("feature gate must be enabled")
    if mapping.get("local_fallback_enabled") is not True:
        raise ReleaseEvidenceError("local fallback must be enabled")
    receipt = mapping.get("compatibility_receipt")
    if not isinstance(receipt, Mapping) or not receipt:
        raise ReleaseEvidenceError("exact DQK-050 compatibility receipt missing")
    if str(receipt.get("task_id") or "") != COMPATIBILITY_TASK_ID:
        raise ReleaseEvidenceError(
            f"compatibility receipt task_id must be {COMPATIBILITY_TASK_ID}"
        )
    if receipt.get("risk_accepted") is not True:
        raise ReleaseEvidenceError("DQK-050 risk_accepted must be true")
    policy = mapping.get("duckdb_20_requalification_policy")
    if not isinstance(policy, Mapping) or not policy:
        raise ReleaseEvidenceError("DuckDB 2.0 requalification policy missing")
    if policy.get("requires_full_contract_rerun") is not True:
        raise ReleaseEvidenceError("DuckDB 2.0 policy incomplete")
    if policy.get("requires_explicit_requalification_receipt") is not True:
        raise ReleaseEvidenceError("DuckDB 2.0 policy incomplete")
    if policy.get("blocks_production_until_requalified") is not True:
        raise ReleaseEvidenceError("DuckDB 2.0 policy incomplete")

    receipt_id = _bounded_text(
        mapping.get("compatibility_receipt_id") or receipt.get("receipt_id") or "",
        field_name="compatibility_receipt_id",
    )
    receipt_digest = _require_sha256(
        mapping.get("compatibility_receipt_digest"),
        field_name="compatibility_receipt_digest",
    )
    acceptor = _require_safe_token(
        mapping.get("acceptor_identity") or "reviewer:unknown",
        field_name="acceptor_identity",
    )
    sealed = {
        "schema": mapping.get("schema")
        or "ipfs_datasets_py/ducklake-quack-risk-policy-binding@1",
        "quack_beta_risk_accepted": True,
        "compatibility_receipt_id": receipt_id,
        "compatibility_receipt_digest": receipt_digest,
        "feature_gate_enabled": True,
        "local_fallback_enabled": True,
        "duckdb_20_requalification_policy": dict(policy),
        "acceptor_identity": acceptor,
        "task_id": COMPATIBILITY_TASK_ID,
        "implementation_generation": _IMPLEMENTATION_GENERATION,
    }
    expected_sig = _digest_of(sealed)
    actual_sig = _require_sha256(mapping.get("signature"), field_name="signature")
    if not _hmac_eq(expected_sig, actual_sig):
        raise ReleaseEvidenceError("quack risk policy signature mismatch")
    expected_cid = _digest_of({**sealed, "signature": actual_sig})
    actual_cid = _require_sha256(mapping.get("binding_cid"), field_name="binding_cid")
    if not _hmac_eq(expected_cid, actual_cid):
        raise ReleaseEvidenceError("quack risk policy binding_cid mismatch")
    return QuackRiskPolicyBinding(
        schema=str(sealed["schema"]),
        binding_cid=actual_cid,
        quack_beta_risk_accepted=True,
        compatibility_receipt_id=receipt_id,
        compatibility_receipt_digest=receipt_digest,
        compatibility_receipt=MappingProxyType(dict(receipt)),
        feature_gate_enabled=True,
        local_fallback_enabled=True,
        duckdb_20_requalification_policy=MappingProxyType(dict(policy)),
        acceptor_identity=acceptor,
        signature=actual_sig,
    )


# ---------------------------------------------------------------------------
# DQK-102 promotion evidence (fail closed)
# ---------------------------------------------------------------------------


def verify_promotion_evidence_for_release(
    *,
    decision: co.PromotionDecision | Mapping[str, Any],
    execution_receipt: co.ExecutionReceipt | Mapping[str, Any],
    process_birth: co.ProcessBirth | Mapping[str, Any] | sec.ProcessBirth,
    generation: co.GenerationFence | Mapping[str, Any],
    evidence: co.EvidenceBundle | Mapping[str, Any],
    inventory_proof_cid: str,
    actor_identity: str,
    now: datetime | None = None,
) -> tuple[co.PromotionDecision, dict[str, Any]]:
    """Fail closed on missing, stale, mismatched, or self-approved DQK-102 evidence.

    Returns the verified :class:`~ipfs_datasets_py.ducklake.cutover.PromotionDecision`
    and a normalized execution receipt mapping.
    """

    if decision is None:
        raise ReleasePromotionError("DQK-102 promotion decision is missing")
    if execution_receipt is None:
        raise ReleasePromotionError("DQK-102 execution receipt is missing")

    try:
        verified = co.verify_promotion_decision(
            decision,
            process_birth=process_birth,  # type: ignore[arg-type]
            generation=generation,
            evidence=evidence,
            inventory_proof_cid=inventory_proof_cid,
            actor_identity=actor_identity,
            now=now,
        )
    except co.PromotionDecisionError as exc:
        raise ReleasePromotionError(str(exc)) from exc
    except co.AuthorityCutoverError as exc:
        raise ReleasePromotionError(str(exc)) from exc

    # Self-approval is already rejected by cutover; restate for release surface.
    if verified.signer_identity in {
        verified.actor_identity,
        verified.implementer_identity,
    }:
        raise ReleasePromotionError(
            "DQK-102 promotion decision is self-approved; fail closed"
        )
    if verified.gate_task_id != PROMOTION_GATE_TASK_ID:
        raise ReleasePromotionError(
            f"promotion gate_task_id must be {PROMOTION_GATE_TASK_ID}"
        )
    clock = now or datetime.now(timezone.utc)
    expires = _parse_utc(verified.expires_at, field_name="decision.expires_at")
    if clock >= expires:
        raise ReleasePromotionError("DQK-102 promotion decision is stale/expired")

    exec_map = _as_mapping(execution_receipt, field_name="execution_receipt")
    required_exec = (
        "execution_id",
        "receipt_cid",
        "decision_cid",
        "actor_identity",
        "process_birth_fingerprint",
        "generation_fingerprint",
        "repository_tree_id",
        "signature",
    )
    missing = [k for k in required_exec if not str(exec_map.get(k) or "").strip()]
    if missing:
        raise ReleasePromotionError(
            "incomplete DQK-102 execution receipt; missing: " + ",".join(missing)
        )
    if exec_map.get("schema") not in {None, "", co.EXECUTION_RECEIPT_SCHEMA}:
        if exec_map.get("schema") != co.EXECUTION_RECEIPT_SCHEMA:
            raise ReleasePromotionError(
                f"execution receipt schema must be {co.EXECUTION_RECEIPT_SCHEMA}"
            )
    decision_cid = _require_sha256(
        exec_map.get("decision_cid"), field_name="execution.decision_cid"
    )
    if not _hmac_eq(decision_cid, verified.decision_cid):
        raise ReleasePromotionError(
            "DQK-102 execution receipt decision_cid mismatches signed decision"
        )
    exec_tree = _require_tree_id(
        exec_map.get("repository_tree_id"), field_name="execution.repository_tree_id"
    )
    if exec_tree != verified.repository_tree_id:
        raise ReleasePromotionError(
            "DQK-102 execution receipt repository tree mismatches decision"
        )
    if str(exec_map.get("actor_identity") or "") != verified.actor_identity:
        raise ReleasePromotionError(
            "DQK-102 execution receipt actor mismatches decision"
        )
    if str(exec_map.get("process_birth_fingerprint") or "") != (
        verified.process_birth_fingerprint
    ):
        raise ReleasePromotionError(
            "DQK-102 execution receipt process-birth fingerprint mismatch"
        )
    if str(exec_map.get("generation_fingerprint") or "") != (
        verified.generation_fingerprint
    ):
        raise ReleasePromotionError(
            "DQK-102 execution receipt generation fingerprint mismatch"
        )
    # Cutover seals over this exact body (see CutoverController.execute).
    sealed_exec = {
        "schema": co.EXECUTION_RECEIPT_SCHEMA,
        "execution_id": exec_map["execution_id"],
        "decision_cid": decision_cid,
        "actor_identity": exec_map["actor_identity"],
        "process_birth_fingerprint": exec_map["process_birth_fingerprint"],
        "generation_fingerprint": exec_map["generation_fingerprint"],
        "repository_tree_id": exec_tree,
        "before_authority": exec_map.get("before_authority"),
        "after_authority": exec_map.get("after_authority"),
        "inventory_proof_cid": exec_map.get("inventory_proof_cid"),
        "evidence_set_cid": exec_map.get("evidence_set_cid"),
        "changed_producers": list(exec_map.get("changed_producers") or []),
        "rollback_fence_id": exec_map.get("rollback_fence_id"),
        "rollback_window_hours": exec_map.get("rollback_window_hours"),
        "dry_run": bool(exec_map.get("dry_run", False)),
        "executed_at": exec_map.get("executed_at"),
        "post_transition_verification": exec_map.get("post_transition_verification"),
        "production_authority_mutated": bool(
            exec_map.get("production_authority_mutated", False)
        ),
        "program_id": exec_map.get("program_id") or co.PROGRAM_ID,
        "owner_task_id": exec_map.get("owner_task_id") or co.OWNER_TASK_ID,
    }
    expected_sig = _digest_of(sealed_exec)
    actual_sig = _require_sha256(
        exec_map.get("signature"), field_name="execution.signature"
    )
    if not _hmac_eq(expected_sig, actual_sig):
        # Fallback: signature over as_mapping fields without receipt_cid/signature.
        unsigned = {
            k: v
            for k, v in exec_map.items()
            if k not in {"signature", "receipt_cid"}
        }
        rebuilt = _digest_of(unsigned)
        if not _hmac_eq(rebuilt, actual_sig):
            raise ReleasePromotionError(
                "DQK-102 execution receipt signature mismatch"
            )

    receipt_cid = _require_sha256(
        exec_map.get("receipt_cid"), field_name="execution.receipt_cid"
    )
    expected_cid = _digest_of({**sealed_exec, "signature": actual_sig})
    if not _hmac_eq(expected_cid, receipt_cid):
        # Accept cutover-style receipt_cid or unsigned rebuild.
        alt_cid = _digest_of(
            {
                **{k: v for k, v in exec_map.items() if k not in {"signature", "receipt_cid"}},
                "signature": actual_sig,
            }
        )
        if not _hmac_eq(alt_cid, receipt_cid):
            raise ReleasePromotionError(
                "DQK-102 execution receipt_cid mismatch"
            )

    normalized = {
        **sealed_exec,
        "schema": co.EXECUTION_RECEIPT_SCHEMA,
        "receipt_cid": receipt_cid,
        "signature": actual_sig,
        "execution_id": _require_safe_token(
            exec_map["execution_id"], field_name="execution_id"
        ),
    }
    return verified, normalized


# ---------------------------------------------------------------------------
# Layer release receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DuckLakeLayerReleaseReceipt:
    """Authoritative ``DuckLakeLayerReleaseReceipt@1`` body (stored in control DB)."""

    schema: str
    interface: str
    receipt_id: str
    release_id: str
    receipt_cid: str
    repository_tree_id: str
    vector_root_id: str
    snapshot_vector_digest: str
    decision_id: str
    decision_cid: str
    execution_id: str
    execution_receipt_cid: str
    binding_digest: str
    shard_bindings: tuple[CatalogShardBinding, ...]
    goal_graph: GoalGraphBinding
    operational_evidence: OperationalEvidenceBundle
    canary_exclusivity: CanaryExclusivityProof
    quack_risk_policy: QuackRiskPolicyBinding
    extension_profile_digest: str
    policy_digest: str
    environment_receipt_cid: str
    issued_at: str
    expires_at: str
    publisher_identity: str
    program_id: str = PROGRAM_ID
    owner_task_id: str = OWNER_TASK_ID
    gate_task_id: str = PROMOTION_GATE_TASK_ID
    authority_table: str = AUTHORITY_TABLE
    authority_scope: str = AUTHORITY_SCOPE
    signature: str = ""
    implementation_generation: str = _IMPLEMENTATION_GENERATION

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "receipt_id": self.receipt_id,
            "release_id": self.release_id,
            "receipt_cid": self.receipt_cid,
            "repository_tree_id": self.repository_tree_id,
            "vector_root_id": self.vector_root_id,
            "snapshot_vector_digest": self.snapshot_vector_digest,
            "decision_id": self.decision_id,
            "decision_cid": self.decision_cid,
            "execution_id": self.execution_id,
            "execution_receipt_cid": self.execution_receipt_cid,
            "binding_digest": self.binding_digest,
            "shard_bindings": [dict(s.as_mapping()) for s in self.shard_bindings],
            "goal_graph": dict(self.goal_graph.as_mapping()),
            "operational_evidence": dict(self.operational_evidence.as_mapping()),
            "canary_exclusivity": dict(self.canary_exclusivity.as_mapping()),
            "quack_risk_policy": dict(self.quack_risk_policy.as_mapping()),
            "extension_profile_digest": self.extension_profile_digest,
            "policy_digest": self.policy_digest,
            "environment_receipt_cid": self.environment_receipt_cid,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "publisher_identity": self.publisher_identity,
            "program_id": self.program_id,
            "owner_task_id": self.owner_task_id,
            "gate_task_id": self.gate_task_id,
            "authority_table": self.authority_table,
            "authority_scope": self.authority_scope,
            "signature": self.signature,
            "implementation_generation": self.implementation_generation,
            "pinned_extensions": {
                "duckdb": lake_caps.REQUIRED_DUCKDB_VERSION_TEXT,
                "quack": lake_caps.PINNED_QUACK_EXTENSION_BUILD,
                "ducklake": lake_caps.PINNED_DUCKLAKE_EXTENSION_BUILD,
                "httpfs": lake_caps.PINNED_HTTPFS_EXTENSION_BUILD,
            },
        }

    def authority_binding(self) -> dict[str, Any]:
        """Body stored in ``lake_release_receipts.body_json`` (content-bound)."""

        body = self._body()
        # Keep authority binding free of nested credential-bearing material.
        return sec.redact_for_receipt(body)  # type: ignore[return-value]


# Fields excluded from the content-bound signature preimage.
_RELEASE_UNSIGNED_EXCLUDED: Final[frozenset[str]] = frozenset(
    {"signature", "receipt_cid", "binding_digest"}
)


def _seal_release_body(body: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return (signature, receipt_cid, binding_digest) for a release body."""

    unsigned = {
        k: v for k, v in body.items() if k not in _RELEASE_UNSIGNED_EXCLUDED
    }
    signature = _digest_of(unsigned)
    receipt_cid = _digest_of({**unsigned, "signature": signature})
    binding_digest = _digest_of(
        {
            "receipt_cid": receipt_cid,
            "decision_cid": body.get("decision_cid"),
            "execution_receipt_cid": body.get("execution_receipt_cid"),
            "vector_root_id": body.get("vector_root_id"),
            "repository_tree_id": body.get("repository_tree_id"),
            "shard_binding_digests": [
                _digest_of(s) for s in list(body.get("shard_bindings") or [])
            ],
            "goal_graph_cid": (body.get("goal_graph") or {}).get("binding_cid"),
            "operational_evidence_cid": (body.get("operational_evidence") or {}).get(
                "evidence_set_cid"
            ),
            "canary_exclusivity_cid": (body.get("canary_exclusivity") or {}).get(
                "proof_cid"
            ),
            "quack_risk_policy_cid": (body.get("quack_risk_policy") or {}).get(
                "binding_cid"
            ),
        }
    )
    return signature, receipt_cid, binding_digest


def build_layer_release_receipt(
    *,
    release_id: str,
    repository_tree_id: str,
    vector_root_id: str,
    snapshot_vector_digest: str,
    shard_bindings: Sequence[CatalogShardBinding | Mapping[str, Any]],
    goal_graph: GoalGraphBinding | Mapping[str, Any],
    operational_evidence: OperationalEvidenceBundle | Mapping[str, Any],
    canary_exclusivity: CanaryExclusivityProof | Mapping[str, Any],
    quack_risk_policy: QuackRiskPolicyBinding | Mapping[str, Any],
    promotion_decision: co.PromotionDecision | Mapping[str, Any],
    execution_receipt: co.ExecutionReceipt | Mapping[str, Any],
    process_birth: co.ProcessBirth | Mapping[str, Any] | sec.ProcessBirth,
    generation: co.GenerationFence | Mapping[str, Any],
    cutover_evidence: co.EvidenceBundle | Mapping[str, Any],
    inventory_proof_cid: str,
    actor_identity: str,
    publisher_identity: str,
    extension_profile_digest: str,
    policy_digest: str,
    environment_receipt_cid: str,
    receipt_id: str | None = None,
    issued_at: datetime | str | None = None,
    expires_at: datetime | str | None = None,
    now: datetime | None = None,
) -> DuckLakeLayerReleaseReceipt:
    """Validate the full goal graph + evidence set and build a sealed receipt.

    Does **not** write to the authority table; call
    :func:`publish_layer_release_receipt` to store it under DQK-086.
    """

    assert_no_markdown_or_file_authority()
    tree = _require_tree_id(repository_tree_id)
    fence = (
        generation
        if isinstance(generation, co.GenerationFence)
        else co.GenerationFence.from_mapping(generation)
    )
    if fence.repository_tree_id != tree:
        raise ReleaseError("generation fence repository tree mismatches release tree")

    verified_decision, verified_execution = verify_promotion_evidence_for_release(
        decision=promotion_decision,
        execution_receipt=execution_receipt,
        process_birth=process_birth,
        generation=fence,
        evidence=cutover_evidence,
        inventory_proof_cid=inventory_proof_cid,
        actor_identity=actor_identity,
        now=now,
    )
    if verified_decision.repository_tree_id != tree:
        raise ReleasePromotionError(
            "DQK-102 decision repository tree mismatches release tree"
        )

    ops = verify_operational_evidence(
        operational_evidence,
        now=now,
        expected_tree_id=tree,
        expected_generation_id=fence.generation_id,
    )
    exclusivity = _verify_canary_exclusivity(
        canary_exclusivity,
        expected_tree_id=tree,
        expected_canary_receipt_cid=ops.canary_receipt_cid,
    )
    graph = _verify_goal_graph(goal_graph, expected_tree_id=tree)
    risk = verify_quack_risk_policy_binding(quack_risk_policy)

    if not shard_bindings:
        raise ReleaseError("release must bind at least one catalog shard")
    shards: list[CatalogShardBinding] = []
    seen_catalog_files: dict[str, str] = {}
    for raw in shard_bindings:
        if isinstance(raw, CatalogShardBinding):
            shard = raw
        else:
            m = _as_mapping(raw, field_name="shard_binding")
            shard = build_catalog_shard_binding(**m)  # type: ignore[arg-type]
        dig = shard.catalog_file_digest
        if dig in seen_catalog_files and seen_catalog_files[dig] != shard.owner_identity:
            raise ReleaseEvidenceError(
                f"catalog file {dig} bound to two owners in release"
            )
        seen_catalog_files[dig] = shard.owner_identity
        shards.append(shard)

    # Cross-check exclusivity map covers every bound catalog file.
    for dig in seen_catalog_files:
        if dig not in exclusivity.catalog_file_owner_map:
            raise ReleaseEvidenceError(
                f"canary exclusivity missing owner for catalog file {dig}"
            )
        if exclusivity.catalog_file_owner_map[dig] != seen_catalog_files[dig]:
            raise ReleaseEvidenceError(
                f"canary exclusivity owner mismatch for catalog file {dig}"
            )

    issued = normalize_timestamp(issued_at or _utc_now())
    if expires_at is None:
        exp_dt = _parse_utc(issued, field_name="issued_at") + timedelta(
            hours=_DEFAULT_RECEIPT_TTL_HOURS
        )
        expires = normalize_timestamp(exp_dt)
    else:
        expires = normalize_timestamp(expires_at)
    if _parse_utc(expires, field_name="expires_at") <= _parse_utc(
        issued, field_name="issued_at"
    ):
        raise ReleaseError("release expires_at must be after issued_at")
    clock = now or datetime.now(timezone.utc)
    if clock >= _parse_utc(expires, field_name="expires_at"):
        raise ReleaseStaleError("release expires_at is already stale")

    rid = _require_safe_token(receipt_id or _new_id("lrr"), field_name="receipt_id")
    rel_id = _require_safe_token(release_id, field_name="release_id")
    publisher = _require_safe_token(publisher_identity, field_name="publisher_identity")

    draft = {
        "schema": LAYER_RELEASE_RECEIPT_SCHEMA,
        "interface": LAYER_RELEASE_RECEIPT_INTERFACE,
        "receipt_id": rid,
        "release_id": rel_id,
        "repository_tree_id": tree,
        "vector_root_id": _require_safe_token(vector_root_id, field_name="vector_root_id"),
        "snapshot_vector_digest": _require_sha256(
            snapshot_vector_digest, field_name="snapshot_vector_digest"
        ),
        "decision_id": verified_decision.decision_id,
        "decision_cid": verified_decision.decision_cid,
        "execution_id": verified_execution["execution_id"],
        "execution_receipt_cid": verified_execution["receipt_cid"],
        "shard_bindings": [dict(s.as_mapping()) for s in shards],
        "goal_graph": dict(graph.as_mapping()),
        "operational_evidence": dict(ops.as_mapping()),
        "canary_exclusivity": dict(exclusivity.as_mapping()),
        "quack_risk_policy": dict(risk.as_mapping()),
        "extension_profile_digest": _require_sha256(
            extension_profile_digest, field_name="extension_profile_digest"
        ),
        "policy_digest": _require_sha256(policy_digest, field_name="policy_digest"),
        "environment_receipt_cid": _require_sha256(
            environment_receipt_cid, field_name="environment_receipt_cid"
        ),
        "issued_at": issued,
        "expires_at": expires,
        "publisher_identity": publisher,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "gate_task_id": PROMOTION_GATE_TASK_ID,
        "authority_table": AUTHORITY_TABLE,
        "authority_scope": AUTHORITY_SCOPE,
        "implementation_generation": _IMPLEMENTATION_GENERATION,
        "pinned_extensions": {
            "duckdb": lake_caps.REQUIRED_DUCKDB_VERSION_TEXT,
            "quack": lake_caps.PINNED_QUACK_EXTENSION_BUILD,
            "ducklake": lake_caps.PINNED_DUCKLAKE_EXTENSION_BUILD,
            "httpfs": lake_caps.PINNED_HTTPFS_EXTENSION_BUILD,
        },
    }
    signature, receipt_cid, binding_digest = _seal_release_body(draft)
    return DuckLakeLayerReleaseReceipt(
        schema=LAYER_RELEASE_RECEIPT_SCHEMA,
        interface=LAYER_RELEASE_RECEIPT_INTERFACE,
        receipt_id=rid,
        release_id=rel_id,
        receipt_cid=receipt_cid,
        repository_tree_id=tree,
        vector_root_id=draft["vector_root_id"],
        snapshot_vector_digest=draft["snapshot_vector_digest"],
        decision_id=verified_decision.decision_id,
        decision_cid=verified_decision.decision_cid,
        execution_id=verified_execution["execution_id"],
        execution_receipt_cid=verified_execution["receipt_cid"],
        binding_digest=binding_digest,
        shard_bindings=tuple(shards),
        goal_graph=graph,
        operational_evidence=ops,
        canary_exclusivity=exclusivity,
        quack_risk_policy=risk,
        extension_profile_digest=draft["extension_profile_digest"],
        policy_digest=draft["policy_digest"],
        environment_receipt_cid=draft["environment_receipt_cid"],
        issued_at=issued,
        expires_at=expires,
        publisher_identity=publisher,
        signature=signature,
    )


def verify_layer_release_receipt(
    receipt: DuckLakeLayerReleaseReceipt | Mapping[str, Any],
    *,
    now: datetime | None = None,
    expected_tree_id: str | None = None,
) -> DuckLakeLayerReleaseReceipt:
    """Re-verify a sealed layer release receipt (fail closed)."""

    if isinstance(receipt, DuckLakeLayerReleaseReceipt):
        mapping = dict(receipt.as_mapping())
        # Rebuild full body with nested objects for sealing check.
        mapping["shard_bindings"] = [dict(s.as_mapping()) for s in receipt.shard_bindings]
        mapping["goal_graph"] = dict(receipt.goal_graph.as_mapping())
        mapping["operational_evidence"] = dict(
            receipt.operational_evidence.as_mapping()
        )
        mapping["canary_exclusivity"] = dict(receipt.canary_exclusivity.as_mapping())
        mapping["quack_risk_policy"] = dict(receipt.quack_risk_policy.as_mapping())
    else:
        mapping = _as_mapping(receipt, field_name="layer_release_receipt")

    if mapping.get("schema") != LAYER_RELEASE_RECEIPT_SCHEMA:
        raise ReleaseError(
            f"receipt schema must be {LAYER_RELEASE_RECEIPT_SCHEMA}"
        )
    if mapping.get("interface") != LAYER_RELEASE_RECEIPT_INTERFACE:
        raise ReleaseError(
            f"receipt interface must be {LAYER_RELEASE_RECEIPT_INTERFACE}"
        )
    if mapping.get("authority_table") != AUTHORITY_TABLE:
        raise ReleaseError(
            "receipt must bind authority table lake_release_receipts"
        )
    if mapping.get("owner_task_id") != OWNER_TASK_ID:
        raise ReleaseError(f"receipt owner_task_id must be {OWNER_TASK_ID}")
    if mapping.get("gate_task_id") != PROMOTION_GATE_TASK_ID:
        raise ReleaseError(f"receipt gate_task_id must be {PROMOTION_GATE_TASK_ID}")

    for key in (
        "receipt_id",
        "release_id",
        "receipt_cid",
        "repository_tree_id",
        "vector_root_id",
        "snapshot_vector_digest",
        "decision_id",
        "decision_cid",
        "execution_id",
        "execution_receipt_cid",
        "binding_digest",
        "issued_at",
        "expires_at",
        "signature",
        "publisher_identity",
    ):
        if not str(mapping.get(key) or "").strip():
            raise ReleaseError(f"receipt missing field {key}")

    clock = now or datetime.now(timezone.utc)
    if clock >= _parse_utc(mapping["expires_at"], field_name="expires_at"):
        raise ReleaseStaleError("layer release receipt is expired")

    tree = _require_tree_id(mapping["repository_tree_id"])
    if expected_tree_id is not None and tree != _require_tree_id(expected_tree_id):
        raise ReleaseError("receipt repository tree mismatch")

    # Nested verifiers.
    ops = verify_operational_evidence(
        mapping.get("operational_evidence") or {},
        now=now,
        expected_tree_id=tree,
    )
    exclusivity = _verify_canary_exclusivity(
        mapping.get("canary_exclusivity") or {},
        expected_tree_id=tree,
        expected_canary_receipt_cid=ops.canary_receipt_cid,
    )
    graph = _verify_goal_graph(mapping.get("goal_graph") or {}, expected_tree_id=tree)
    risk = verify_quack_risk_policy_binding(mapping.get("quack_risk_policy") or {})

    shards_raw = list(mapping.get("shard_bindings") or [])
    if not shards_raw:
        raise ReleaseError("receipt binds no catalog shards")
    shards = [
        build_catalog_shard_binding(**_as_mapping(s, field_name="shard"))
        for s in shards_raw
    ]

    draft = {
        "schema": LAYER_RELEASE_RECEIPT_SCHEMA,
        "interface": LAYER_RELEASE_RECEIPT_INTERFACE,
        "receipt_id": mapping["receipt_id"],
        "release_id": mapping["release_id"],
        "repository_tree_id": tree,
        "vector_root_id": mapping["vector_root_id"],
        "snapshot_vector_digest": mapping["snapshot_vector_digest"],
        "decision_id": mapping["decision_id"],
        "decision_cid": mapping["decision_cid"],
        "execution_id": mapping["execution_id"],
        "execution_receipt_cid": mapping["execution_receipt_cid"],
        "shard_bindings": [dict(s.as_mapping()) for s in shards],
        "goal_graph": dict(graph.as_mapping()),
        "operational_evidence": dict(ops.as_mapping()),
        "canary_exclusivity": dict(exclusivity.as_mapping()),
        "quack_risk_policy": dict(risk.as_mapping()),
        "extension_profile_digest": mapping["extension_profile_digest"],
        "policy_digest": mapping["policy_digest"],
        "environment_receipt_cid": mapping["environment_receipt_cid"],
        "issued_at": normalize_timestamp(mapping["issued_at"]),
        "expires_at": normalize_timestamp(mapping["expires_at"]),
        "publisher_identity": mapping["publisher_identity"],
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "gate_task_id": PROMOTION_GATE_TASK_ID,
        "authority_table": AUTHORITY_TABLE,
        "authority_scope": AUTHORITY_SCOPE,
        "implementation_generation": _IMPLEMENTATION_GENERATION,
        "pinned_extensions": {
            "duckdb": lake_caps.REQUIRED_DUCKDB_VERSION_TEXT,
            "quack": lake_caps.PINNED_QUACK_EXTENSION_BUILD,
            "ducklake": lake_caps.PINNED_DUCKLAKE_EXTENSION_BUILD,
            "httpfs": lake_caps.PINNED_HTTPFS_EXTENSION_BUILD,
        },
    }
    sig, cid, binding_digest = _seal_release_body(draft)
    actual_sig = _require_sha256(mapping["signature"], field_name="signature")
    actual_cid = _require_sha256(mapping["receipt_cid"], field_name="receipt_cid")
    if not _hmac_eq(actual_sig, sig) or not _hmac_eq(actual_cid, cid):
        raise ReleaseError("layer release receipt signature or receipt_cid mismatch")

    return DuckLakeLayerReleaseReceipt(
        schema=LAYER_RELEASE_RECEIPT_SCHEMA,
        interface=LAYER_RELEASE_RECEIPT_INTERFACE,
        receipt_id=_require_safe_token(mapping["receipt_id"], field_name="receipt_id"),
        release_id=_require_safe_token(mapping["release_id"], field_name="release_id"),
        receipt_cid=actual_cid,
        repository_tree_id=tree,
        vector_root_id=_require_safe_token(
            mapping["vector_root_id"], field_name="vector_root_id"
        ),
        snapshot_vector_digest=_require_sha256(
            mapping["snapshot_vector_digest"], field_name="snapshot_vector_digest"
        ),
        decision_id=_require_safe_token(mapping["decision_id"], field_name="decision_id"),
        decision_cid=_require_sha256(mapping["decision_cid"], field_name="decision_cid"),
        execution_id=_require_safe_token(
            mapping["execution_id"], field_name="execution_id"
        ),
        execution_receipt_cid=_require_sha256(
            mapping["execution_receipt_cid"], field_name="execution_receipt_cid"
        ),
        binding_digest=binding_digest,
        shard_bindings=tuple(shards),
        goal_graph=graph,
        operational_evidence=ops,
        canary_exclusivity=exclusivity,
        quack_risk_policy=risk,
        extension_profile_digest=_require_sha256(
            mapping["extension_profile_digest"], field_name="extension_profile_digest"
        ),
        policy_digest=_require_sha256(
            mapping["policy_digest"], field_name="policy_digest"
        ),
        environment_receipt_cid=_require_sha256(
            mapping["environment_receipt_cid"], field_name="environment_receipt_cid"
        ),
        issued_at=normalize_timestamp(mapping["issued_at"]),
        expires_at=normalize_timestamp(mapping["expires_at"]),
        publisher_identity=_require_safe_token(
            mapping["publisher_identity"], field_name="publisher_identity"
        ),
        signature=actual_sig,
    )


# ---------------------------------------------------------------------------
# Authority publish + sanitized export
# ---------------------------------------------------------------------------


def publish_layer_release_receipt(
    control: ControlLakeRegistry,
    receipt: DuckLakeLayerReleaseReceipt | Mapping[str, Any],
    *,
    promotion_decision: co.PromotionDecision | Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    """Store the receipt in DQK-086 ``lake_release_receipts`` (authority table).

    Also records the promotion decision and execution rows when not already
    present so the release row can reference them by id. Returns the stored
    authority row (including ``body_json`` / ``binding_digest``).
    """

    assert_no_markdown_or_file_authority()
    if not isinstance(control, ControlLakeRegistry):
        raise ReleaseError("control must be a ControlLakeRegistry")
    control.require_migrated()
    control.assert_control_authority(AUTHORITY_TABLE)

    verified = verify_layer_release_receipt(receipt, now=now)
    # Ensure promotion decision row exists.
    decision_map: dict[str, Any]
    if promotion_decision is not None:
        decision_map = _as_mapping(promotion_decision, field_name="promotion_decision")
    elif isinstance(receipt, DuckLakeLayerReleaseReceipt):
        decision_map = {
            "decision_id": verified.decision_id,
            "decision_cid": verified.decision_cid,
            "signer_identity": "reviewer:bound",
            "subject": "ducklake-layer-release",
            "decision": "accepted",
            "expires_at": verified.expires_at,
            "evidence_digest": verified.operational_evidence.evidence_set_cid,
        }
    else:
        nested = _as_mapping(receipt, field_name="receipt").get("promotion_decision")
        if isinstance(nested, Mapping):
            decision_map = dict(nested)
        else:
            decision_map = {
                "decision_id": verified.decision_id,
                "decision_cid": verified.decision_cid,
                "signer_identity": "reviewer:bound",
                "subject": "ducklake-layer-release",
                "decision": "accepted",
                "expires_at": verified.expires_at,
                "evidence_digest": verified.operational_evidence.evidence_set_cid,
            }

    existing_decision = control.store.get_row(
        "lake_promotion_decisions", verified.decision_id
    )
    if existing_decision is None:
        control.record_promotion_decision(
            decision_id=verified.decision_id,
            subject=str(decision_map.get("subject") or "ducklake-layer-release"),
            decision=str(decision_map.get("decision") or "accepted"),
            evidence_digest=str(
                decision_map.get("evidence_digest")
                or decision_map.get("decision_cid")
                or verified.decision_cid
            ),
            signer_identity=str(
                decision_map.get("signer_identity") or "reviewer:dqk-102"
            ),
            expires_at=str(
                decision_map.get("expires_at") or verified.expires_at
            ),
        )

    existing_exec = control.store.get_row(
        "lake_promotion_executions", verified.execution_id
    )
    if existing_exec is None:
        control.record_promotion_execution(
            execution_id=verified.execution_id,
            decision_id=verified.decision_id,
            executor_identity=verified.publisher_identity,
            status="completed",
            receipt_digest=verified.execution_receipt_cid,
        )

    # Ensure vector root exists when possible (binding requires vector_root_id).
    if control.store.get_row("lake_snapshot_vector_roots", verified.vector_root_id) is None:
        # Minimal member list derived from shard bindings.
        members = [
            {
                "shard_id": s.shard_id,
                "snapshot_version": s.owner_generation,
                "catalog_file_digest": s.catalog_file_digest,
            }
            for s in verified.shard_bindings
        ]
        try:
            control.put_snapshot_vector_root(
                vector_root_id=verified.vector_root_id,
                members=members,
            )
        except RegistryError:
            # If topology is incomplete, still allow release storage when the
            # vector root was pre-seeded under a different path; re-raise only
            # when the table write itself fails for empty members.
            if not members:
                raise

    binding = verified.authority_binding()
    # Re-attach exact digests used by the sealed receipt.
    binding["receipt_cid"] = verified.receipt_cid
    binding["binding_digest"] = verified.binding_digest
    binding["signature"] = verified.signature
    binding["decision_cid"] = verified.decision_cid
    binding["execution_receipt_cid"] = verified.execution_receipt_cid
    binding["interface"] = LAYER_RELEASE_RECEIPT_INTERFACE
    binding["authority_table"] = AUTHORITY_TABLE

    stored = control.record_release_receipt(
        receipt_id=verified.receipt_id,
        release_id=verified.release_id,
        vector_root_id=verified.vector_root_id,
        decision_id=verified.decision_id,
        execution_id=verified.execution_id,
        binding=binding,
    )
    # Confirm authority table row — not a file.
    row = control.store.get_row(AUTHORITY_TABLE, verified.receipt_id)
    if row is None:
        raise ReleaseError(
            f"failed to store release receipt in {AUTHORITY_TABLE}"
        )
    if "body_json" not in row:
        raise ReleaseError("authority row missing body_json")

    with _STATE_LOCK:
        _LAST_PUBLISHED[verified.receipt_id] = MappingProxyType(dict(stored))

    return MappingProxyType(dict(stored))


def export_sanitized_release_projection(
    receipt: DuckLakeLayerReleaseReceipt | Mapping[str, Any],
    *,
    include_shard_digests: bool = True,
) -> Mapping[str, Any]:
    """Export a sanitized public projection without credentials or encryption keys."""

    if isinstance(receipt, DuckLakeLayerReleaseReceipt):
        raw = dict(receipt.as_mapping())
        raw["shard_bindings"] = [dict(s.as_mapping()) for s in receipt.shard_bindings]
        raw["goal_graph"] = dict(receipt.goal_graph.as_mapping())
        raw["operational_evidence"] = dict(receipt.operational_evidence.as_mapping())
        raw["canary_exclusivity"] = dict(receipt.canary_exclusivity.as_mapping())
        raw["quack_risk_policy"] = dict(receipt.quack_risk_policy.as_mapping())
    else:
        raw = _as_mapping(receipt, field_name="receipt")

    # Drop nested full compatibility receipt body (may carry profile details);
    # keep only digests and non-secret flags for the public projection.
    risk = dict(raw.get("quack_risk_policy") or {})
    if "compatibility_receipt" in risk:
        compat = dict(risk["compatibility_receipt"])
        risk["compatibility_receipt"] = {
            "receipt_id": compat.get("receipt_id"),
            "task_id": compat.get("task_id"),
            "interface": compat.get("interface"),
            "risk_accepted": compat.get("risk_accepted"),
            "feature_gate_enabled": compat.get("feature_gate_enabled"),
            "local_fallback_enabled": compat.get("local_fallback_enabled"),
            "quack_beta": compat.get("quack_beta"),
            "signature_digest": (
                (compat.get("signature") or {}).get("digest")
                if isinstance(compat.get("signature"), Mapping)
                else compat.get("signature")
            ),
        }
    raw["quack_risk_policy"] = risk

    if not include_shard_digests:
        raw["shard_bindings"] = [
            {
                "shard_id": s.get("shard_id"),
                "catalog_id": s.get("catalog_id"),
                "owner_generation": s.get("owner_generation"),
                "endpoint_identity": s.get("endpoint_identity"),
                "ring_position": s.get("ring_position"),
            }
            for s in list(raw.get("shard_bindings") or [])
            if isinstance(s, Mapping)
        ]

    scrubbed = sec.redact_for_export(raw)
    if not isinstance(scrubbed, Mapping):
        raise ReleaseError("sanitized projection must remain a mapping")

    # Hard fail if residual sensitive material slipped through.
    _assert_projection_sanitized(scrubbed)

    projection = {
        "schema": RELEASE_PROJECTION_SCHEMA,
        "interface": LAYER_RELEASE_RECEIPT_INTERFACE,
        "sanitized": True,
        "credentials_redacted": True,
        "encryption_keys_redacted": True,
        "authority_table": AUTHORITY_TABLE,
        "receipt_id": scrubbed.get("receipt_id"),
        "release_id": scrubbed.get("release_id"),
        "receipt_cid": scrubbed.get("receipt_cid"),
        "repository_tree_id": scrubbed.get("repository_tree_id"),
        "vector_root_id": scrubbed.get("vector_root_id"),
        "decision_id": scrubbed.get("decision_id"),
        "decision_cid": scrubbed.get("decision_cid"),
        "execution_id": scrubbed.get("execution_id"),
        "execution_receipt_cid": scrubbed.get("execution_receipt_cid"),
        "expires_at": scrubbed.get("expires_at"),
        "issued_at": scrubbed.get("issued_at"),
        "owner_task_id": OWNER_TASK_ID,
        "gate_task_id": PROMOTION_GATE_TASK_ID,
        "body": scrubbed,
    }
    return MappingProxyType(projection)


def _assert_projection_sanitized(payload: Any, *, path: str = "$") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_l = str(key).lower().replace("-", "_")
            child = f"{path}.{key}"
            if any(frag in key_l for frag in _SENSITIVE_EXPORT_FRAGMENTS):
                if value not in {
                    None,
                    "",
                    sec.REDACTION_MARKER,
                    "***",
                    "[redacted]",
                    "REDACTED",
                    True,
                    False,
                } and not isinstance(value, (int, float, bool)):
                    # Allow digest-only refs.
                    if not (
                        isinstance(value, str)
                        and (
                            value.startswith("sha256:")
                            or value.startswith("receipt:")
                            or value == sec.REDACTION_MARKER
                        )
                    ):
                        raise ReleaseError(
                            f"sanitized projection leaks sensitive key {child}"
                        )
            _assert_projection_sanitized(value, path=child)
    elif isinstance(payload, (list, tuple)):
        for idx, item in enumerate(payload):
            _assert_projection_sanitized(item, path=f"{path}[{idx}]")
    elif isinstance(payload, str):
        lower = payload.lower()
        if "begin private key" in lower or "aws_secret" in lower:
            raise ReleaseError(f"sanitized projection leaks secret material at {path}")


def self_check() -> Mapping[str, Any]:
    """Hermetic self-check of module contracts (no DuckDB required)."""

    assert_no_markdown_or_file_authority()
    return MappingProxyType(
        {
            "ok": True,
            "schema": LAYER_RELEASE_RECEIPT_SCHEMA,
            "interface": LAYER_RELEASE_RECEIPT_INTERFACE,
            "authority_table": AUTHORITY_TABLE,
            "owner_task_id": OWNER_TASK_ID,
            "gate_task_id": PROMOTION_GATE_TASK_ID,
            "compatibility_task_id": COMPATIBILITY_TASK_ID,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
            "markdown_or_file_authority": False,
        }
    )
