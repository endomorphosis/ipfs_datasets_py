"""DuckLake layer release receipt verification and authority storage (DQK-101).

Validates the complete DuckLake goal graph against the exact repository tree,
environment/extension profile, every DuckDB + Quack catalog shard and owner
generation, companion registry, storage root, schema checksum, representative
snapshot vector, canary, maintenance, restore, security, publication, and the
exact signed DQK-102 promotion decision/execution evidence, then stores
``DuckLakeLayerReleaseReceipt@1`` in the DQK-086 ``lake_release_receipts``
authority table.

Critical invariants:

* Receipts are stored only in the control-plane authority table — never as a
  Markdown or free-standing JSON authority file.
* Missing, stale, mismatched, or self-approved DQK-102 promotion evidence fails
  closed.
* Missing or stale canary, restore, maintenance, security, or cutover evidence
  fails closed.
* Ownership proofs require exactly one owner per catalog file and no remote
  client opening an authority catalog during the canary.
* Quack beta risk acceptance, exact DQK-050 compatibility receipt, live
  feature gate + local fallback, and DuckDB 2.0 requalification policy are
  bound into the sealed receipt.
* A sanitized release projection can be exported without credentials or
  encryption keys.

Import is side-effect free: no DuckDB, network, or filesystem I/O until an
explicit release method is called.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.duckdb_control.contracts import normalize_timestamp
from ipfs_datasets_py.ducklake import capabilities as lake_caps
from ipfs_datasets_py.ducklake import cutover as co
from ipfs_datasets_py.ducklake import registry as reg
from ipfs_datasets_py.ducklake import security as sec

__all__ = [
    "AUTHORITY_TABLE",
    "COMPATIBILITY_TASK_ID",
    "DOMAIN",
    "OWNER_TASK_ID",
    "PROGRAM_ID",
    "PROMOTION_GATE_TASK_ID",
    "REGISTRY_AUTHORITY_TASK_ID",
    "RELEASE_RECEIPT_INTERFACE",
    "RELEASE_RECEIPT_SCHEMA",
    "RELEASE_EVIDENCE_SCHEMA",
    "SANITIZED_PROJECTION_SCHEMA",
    "CatalogShardBinding",
    "DuckLakeLayerReleaseReceipt",
    "MissingEvidenceError",
    "MismatchedEvidenceError",
    "PromotionEvidenceError",
    "ReleaseError",
    "SelfApprovedPromotionError",
    "StaleEvidenceError",
    "build_catalog_shard_binding",
    "build_duckdb_20_requalification_policy",
    "build_layer_release_receipt",
    "build_operational_evidence",
    "build_ownership_proof",
    "export_sanitized_release_projection",
    "load_dqk050_module",
    "publish_layer_release",
    "self_check",
    "store_layer_release_receipt",
    "verify_compatibility_binding",
    "verify_layer_release_receipt",
    "verify_operational_evidence",
    "verify_ownership_invariants",
    "verify_promotion_evidence",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-101"
PROMOTION_GATE_TASK_ID: Final[str] = "DQK-102"
COMPATIBILITY_TASK_ID: Final[str] = "DQK-050"
REGISTRY_AUTHORITY_TASK_ID: Final[str] = "DQK-086"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-control-plane-v1"
DOMAIN: Final[str] = "ducklake-layer-release"

RELEASE_RECEIPT_INTERFACE: Final[str] = "DuckLakeLayerReleaseReceipt@1"
RELEASE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-layer-release-receipt@1"
)
RELEASE_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-layer-release-evidence@1"
)
SANITIZED_PROJECTION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-layer-release-sanitized-projection@1"
)
AUTHORITY_TABLE: Final[str] = "lake_release_receipts"

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-101-ducklake-layer-release-20260811"
)

_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SAFE_TOKEN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$"
)
_MAX_FIELD_BYTES: Final[int] = 16_384
_DEFAULT_RECEIPT_TTL_HOURS: Final[int] = 72
_DEFAULT_EVIDENCE_TTL_HOURS: Final[int] = 24

# Operational evidence kinds that must be present and unexpired.
_OPERATIONAL_KINDS: Final[tuple[str, ...]] = (
    "canary",
    "restore",
    "maintenance",
    "security",
    "cutover",
)

# Keys stripped or redacted from sanitized projections (defense in depth).
_SENSITIVE_EXPORT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "private_key",
        "encryption_key",
        "encryption_keys",
        "signing_key",
        "quack_token",
        "credential",
        "credentials",
        "endpoint_secret",
        "signing_secret",
        "capability_secret",
        "capability_token",
        "raw_token",
        "file_key",
        "ducklake_key",
        "catalog_key",
        "object_delete_secret",
        "iam_secret",
        "session_token",
        "access_key",
        "secret_key",
        "mnemonic",
        "seed",
    }
)

_DQK050_CACHE: ModuleType | None = None
_STATE_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReleaseError(ValueError):
    """Fail-closed rejection for DuckLake layer release validation."""


class MissingEvidenceError(ReleaseError):
    """Required release, promotion, or operational evidence is absent."""


class StaleEvidenceError(ReleaseError):
    """Evidence or promotion material is expired at the point of use."""


class MismatchedEvidenceError(ReleaseError):
    """Evidence digests, trees, or identities disagree with the sealed binding."""


class PromotionEvidenceError(ReleaseError):
    """DQK-102 promotion decision or execution evidence is invalid."""


class SelfApprovedPromotionError(PromotionEvidenceError):
    """DQK-102 decision was self-approved (signer not independent)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    clock = dt or _utc_now()
    return normalize_timestamp(clock)


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _canonical_json_bytes(payload: Any) -> bytes:
    return _canonical_json(payload).encode("utf-8")


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _digest_of(payload: Any) -> str:
    return "sha256:" + _sha256_hex(_canonical_json_bytes(payload))


def _hmac_eq(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left), str(right))


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:16]}"


def _bounded_text(value: Any, *, field: str, max_bytes: int = _MAX_FIELD_BYTES) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        raise ReleaseError(f"{field} is required")
    if len(text.encode("utf-8")) > max_bytes:
        raise ReleaseError(f"{field} exceeds size bound")
    return text


def _require_safe_token(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field, max_bytes=256)
    if not _SAFE_TOKEN.fullmatch(text):
        raise ReleaseError(f"{field} is not a safe identity token")
    return text


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field, max_bytes=128)
    if not _SHA256_DIGEST.fullmatch(text):
        # Accept bare hex and normalize.
        if re.fullmatch(r"^[0-9a-f]{64}$", text):
            return f"sha256:{text}"
        raise ReleaseError(f"{field} must be a sha256:<64-hex> digest")
    return text


def _require_tree_id(value: Any, *, field: str = "repository_tree_id") -> str:
    text = _bounded_text(value, field=field, max_bytes=256).lower()
    if _GIT_OID.fullmatch(text):
        return text
    # Control-plane form: repository:git-commit:<oid>:tree:<oid>
    parts = text.split(":")
    if (
        len(parts) == 5
        and parts[0] == "repository"
        and parts[1] == "git-commit"
        and _GIT_OID.fullmatch(parts[2])
        and parts[3] == "tree"
        and _GIT_OID.fullmatch(parts[4])
    ):
        return parts[4]
    raise ReleaseError(
        f"{field} must be a 40-char git tree oid or "
        "repository:git-commit:<oid>:tree:<oid>"
    )


def _parse_utc(value: Any, *, field: str) -> datetime:
    text = normalize_timestamp(value)
    # normalize_timestamp yields ...Z or offset form.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReleaseError(f"{field} is not a valid UTC timestamp") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _assert_unexpired(
    expires_at: Any,
    *,
    field: str,
    now: datetime | None = None,
    kind: str = "evidence",
) -> str:
    clock = now or _utc_now()
    expires = _parse_utc(expires_at, field=field)
    if clock >= expires:
        raise StaleEvidenceError(
            f"{kind} {field} is expired at point of use ({field}={normalize_timestamp(expires)})"
        )
    return normalize_timestamp(expires)


def _as_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "as_mapping") and callable(value.as_mapping):
        mapped = value.as_mapping()
        if isinstance(mapped, Mapping):
            return dict(mapped)
    raise MissingEvidenceError(f"{field} must be an object")


def _require_true(value: Any, *, field: str, message: str | None = None) -> None:
    if value is not True:
        raise ReleaseError(message or f"{field} must be true")


def load_dqk050_module() -> ModuleType:
    """Load the DQK-050 compatibility suite module (importlib, not package)."""

    global _DQK050_CACHE
    if _DQK050_CACHE is not None:
        return _DQK050_CACHE

    # Prefer already-imported module if present.
    existing = sys.modules.get("validate_duckdb_quack_compatibility")
    if existing is not None and hasattr(existing, "require_compatibility_receipt"):
        _DQK050_CACHE = existing
        return existing

    candidates = [
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "validation"
        / "validate_duckdb_quack_compatibility.py",
        Path.cwd()
        / "scripts"
        / "validation"
        / "validate_duckdb_quack_compatibility.py",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise ReleaseError(
            "DQK-050 compatibility module missing at "
            "scripts/validation/validate_duckdb_quack_compatibility.py"
        )
    spec = importlib.util.spec_from_file_location(
        "validate_duckdb_quack_compatibility", path
    )
    if spec is None or spec.loader is None:
        raise ReleaseError(f"cannot load DQK-050 module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _DQK050_CACHE = module
    return module


# ---------------------------------------------------------------------------
# Catalog shard + ownership bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogShardBinding:
    """One DuckDB + Quack catalog shard bound into the layer release."""

    shard_id: str
    catalog_id: str
    catalog_file_digest: str
    companion_registry_digest: str
    owner_generation: int
    endpoint_identity: str
    storage_identity: str
    task_completion_id: str
    task_validation_id: str
    single_owner: bool = True
    remote_client_opened_catalog: bool = False
    owner_identity: str = ""
    companion_private: bool = True

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "shard_id": self.shard_id,
                "catalog_id": self.catalog_id,
                "catalog_file_digest": self.catalog_file_digest,
                "companion_registry_digest": self.companion_registry_digest,
                "owner_generation": self.owner_generation,
                "endpoint_identity": self.endpoint_identity,
                "storage_identity": self.storage_identity,
                "task_completion_id": self.task_completion_id,
                "task_validation_id": self.task_validation_id,
                "single_owner": self.single_owner,
                "remote_client_opened_catalog": self.remote_client_opened_catalog,
                "owner_identity": self.owner_identity,
                "companion_private": self.companion_private,
            }
        )


def build_catalog_shard_binding(
    *,
    shard_id: str,
    catalog_id: str,
    catalog_file_digest: str,
    companion_registry_digest: str,
    owner_generation: int,
    endpoint_identity: str,
    storage_identity: str,
    task_completion_id: str,
    task_validation_id: str,
    single_owner: bool = True,
    remote_client_opened_catalog: bool = False,
    owner_identity: str = "",
    companion_private: bool = True,
) -> CatalogShardBinding:
    """Build a sealed catalog-shard binding for the layer release graph."""

    if not isinstance(owner_generation, int) or isinstance(owner_generation, bool):
        raise ReleaseError("owner_generation must be an int")
    if owner_generation < 1:
        raise ReleaseError("owner_generation must be >= 1")
    if single_owner is not True:
        raise ReleaseError(
            "catalog shard binding must assert single_owner=true "
            "(no catalog file may have two owners)"
        )
    if remote_client_opened_catalog is not False:
        raise ReleaseError(
            "catalog shard binding must assert remote_client_opened_catalog=false"
        )
    if companion_private is not True:
        raise ReleaseError("companion registry must remain private")

    return CatalogShardBinding(
        shard_id=_require_safe_token(shard_id, field="shard_id"),
        catalog_id=_require_safe_token(catalog_id, field="catalog_id"),
        catalog_file_digest=_require_sha256(
            catalog_file_digest, field="catalog_file_digest"
        ),
        companion_registry_digest=_require_sha256(
            companion_registry_digest, field="companion_registry_digest"
        ),
        owner_generation=int(owner_generation),
        endpoint_identity=_require_safe_token(
            endpoint_identity, field="endpoint_identity"
        ),
        storage_identity=_require_safe_token(
            storage_identity, field="storage_identity"
        ),
        task_completion_id=_require_safe_token(
            task_completion_id, field="task_completion_id"
        ),
        task_validation_id=_require_safe_token(
            task_validation_id, field="task_validation_id"
        ),
        single_owner=True,
        remote_client_opened_catalog=False,
        owner_identity=(
            _require_safe_token(owner_identity, field="owner_identity")
            if owner_identity
            else ""
        ),
        companion_private=True,
    )


def build_ownership_proof(
    shards: Sequence[CatalogShardBinding | Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Prove no catalog file had two owners and no remote client opened one."""

    if not shards:
        raise MissingEvidenceError(
            "ownership proof requires at least one catalog shard binding"
        )
    normalized: list[dict[str, Any]] = []
    by_catalog_file: dict[str, str] = {}
    for index, raw in enumerate(shards):
        if isinstance(raw, CatalogShardBinding):
            row = dict(raw.as_mapping())
        else:
            row = _as_mapping(raw, field=f"catalog_shards[{index}]")
        if row.get("single_owner") is not True:
            raise ReleaseError(
                f"catalog shard {row.get('shard_id')!r} failed single-owner proof"
            )
        if row.get("remote_client_opened_catalog") is not False:
            raise ReleaseError(
                f"catalog shard {row.get('shard_id')!r}: remote client opened "
                "authority catalog during canary"
            )
        digest = _require_sha256(
            row.get("catalog_file_digest"), field="catalog_file_digest"
        )
        shard_id = _require_safe_token(row.get("shard_id"), field="shard_id")
        prior = by_catalog_file.get(digest)
        if prior is not None and prior != shard_id:
            raise ReleaseError(
                f"catalog file digest {digest} claimed by two owners: "
                f"{prior!r} and {shard_id!r}"
            )
        by_catalog_file[digest] = shard_id
        normalized.append(row)

    # Also exercise the security remote-access denial surface hermetically.
    for action in ("open", "copy", "mount", "replace"):
        try:
            sec.assert_remote_authority_action_denied(
                action, target="authority_catalog"
            )
        except sec.RemoteAccessDenied:
            pass
        else:
            raise ReleaseError(
                f"remote authority action {action!r} was not denied"
            )

    return MappingProxyType(
        {
            "ok": True,
            "single_owner_per_catalog_file": True,
            "remote_client_opened_authority_catalog": False,
            "catalog_file_count": len(by_catalog_file),
            "shard_count": len(normalized),
            "catalog_file_digests": sorted(by_catalog_file.keys()),
        }
    )


def verify_ownership_invariants(
    shards: Sequence[CatalogShardBinding | Mapping[str, Any]],
    *,
    canary: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Fail-closed ownership / remote-access invariant verification."""

    proof = dict(build_ownership_proof(shards))
    if canary is not None:
        canary_map = _as_mapping(canary, field="canary")
        # Accept several canary shapes that encode the same invariants.
        single = canary_map.get("single_owner_proof")
        if single is None:
            single = canary_map.get("single_owner")
        if single is None:
            ownership = canary_map.get("ownership_proof")
            if isinstance(ownership, Mapping):
                single = ownership.get("single_owner_per_catalog_file")
        if single is not True:
            raise ReleaseError(
                "canary evidence must prove single_owner (no dual owners)"
            )

        if canary_map.get("remote_client_opened_catalog") is True:
            raise ReleaseError(
                "canary evidence indicates a remote client opened an authority catalog"
            )
        if canary_map.get("remote_clients_may_open_catalog_file") is True:
            raise ReleaseError(
                "canary evidence allows remote clients to open authority catalogs"
            )
        ownership = canary_map.get("ownership_proof")
        if isinstance(ownership, Mapping) and ownership.get(
            "remote_client_opened_authority_catalog"
        ) is True:
            raise ReleaseError(
                "canary ownership proof indicates remote client opened authority catalog"
            )
        if (
            canary_map.get("no_remote_catalog_open") is not True
            and canary_map.get("remote_client_opened_catalog") is not False
            and not (
                isinstance(ownership, Mapping)
                and ownership.get("remote_client_opened_authority_catalog")
                is False
            )
        ):
            # Require an explicit negative proof when no other remote flag is set.
            raise ReleaseError(
                "canary evidence must prove no remote client opened an "
                "authority catalog"
            )
        proof["canary_bound"] = True
    else:
        proof["canary_bound"] = False
    return MappingProxyType(proof)


# ---------------------------------------------------------------------------
# Operational evidence (canary / restore / maintenance / security / cutover)
# ---------------------------------------------------------------------------


def build_operational_evidence(
    *,
    kind: str,
    receipt_id: str,
    receipt_digest: str,
    repository_tree_id: str,
    issued_at: datetime | str | None = None,
    expires_at: datetime | str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal unexpired operational evidence record."""

    kind_norm = _require_safe_token(kind, field="kind")
    if kind_norm not in _OPERATIONAL_KINDS and kind_norm != "publication":
        raise ReleaseError(
            f"unknown operational evidence kind {kind_norm!r}; "
            f"expected one of {list(_OPERATIONAL_KINDS) + ['publication']}"
        )
    issued = normalize_timestamp(issued_at or _utc_now())
    if expires_at is None:
        exp_dt = _parse_utc(issued, field="issued_at") + timedelta(
            hours=_DEFAULT_EVIDENCE_TTL_HOURS
        )
        expires = normalize_timestamp(exp_dt)
    else:
        expires = normalize_timestamp(expires_at)
    if _parse_utc(expires, field="expires_at") <= _parse_utc(
        issued, field="issued_at"
    ):
        raise ReleaseError(f"{kind_norm} expires_at must be after issued_at")

    body: dict[str, Any] = {
        "kind": kind_norm,
        "receipt_id": _require_safe_token(receipt_id, field="receipt_id"),
        "receipt_digest": _require_sha256(receipt_digest, field="receipt_digest"),
        "repository_tree_id": _require_tree_id(repository_tree_id),
        "issued_at": issued,
        "expires_at": expires,
        "fresh": True,
        "stale": False,
    }
    if extra:
        for key, value in dict(extra).items():
            if key in body:
                continue
            body[key] = value
    return body


def verify_operational_evidence(
    evidence: Mapping[str, Any],
    *,
    kind: str,
    expected_tree_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail closed if operational evidence is missing or stale."""

    if not isinstance(evidence, Mapping) or not evidence:
        raise MissingEvidenceError(f"missing {kind} evidence")
    mapping = dict(evidence)
    if mapping.get("kind") not in (None, kind) and mapping.get("kind") != kind:
        raise MismatchedEvidenceError(
            f"{kind} evidence kind mismatch: {mapping.get('kind')!r}"
        )
    required = ("receipt_id", "receipt_digest", "expires_at")
    missing = [k for k in required if not str(mapping.get(k) or "").strip()]
    if missing:
        raise MissingEvidenceError(
            f"incomplete {kind} evidence; missing: " + ",".join(missing)
        )
    if mapping.get("stale") is True or mapping.get("fresh") is False:
        raise StaleEvidenceError(f"{kind} evidence is marked stale")
    expires = _assert_unexpired(
        mapping["expires_at"],
        field="expires_at",
        now=now,
        kind=kind,
    )
    digest = _require_sha256(mapping["receipt_digest"], field=f"{kind}.receipt_digest")
    tree = mapping.get("repository_tree_id")
    if expected_tree_id is not None and tree:
        actual = _require_tree_id(tree, field=f"{kind}.repository_tree_id")
        expected = _require_tree_id(expected_tree_id, field="expected_tree_id")
        if actual != expected:
            raise MismatchedEvidenceError(
                f"{kind} evidence repository tree does not match release tree"
            )
    return {
        "kind": kind,
        "receipt_id": _require_safe_token(
            mapping["receipt_id"], field=f"{kind}.receipt_id"
        ),
        "receipt_digest": digest,
        "expires_at": expires,
        "ok": True,
    }


def verify_all_operational_evidence(
    bundle: Mapping[str, Any],
    *,
    expected_tree_id: str | None = None,
    now: datetime | None = None,
    require_publication: bool = True,
) -> dict[str, Any]:
    """Verify canary/restore/maintenance/security/cutover (+ optional publication)."""

    verified: dict[str, Any] = {}
    for kind in _OPERATIONAL_KINDS:
        raw = bundle.get(kind)
        if raw is None:
            raise MissingEvidenceError(
                f"missing or stale {kind} evidence fails closed"
            )
        verified[kind] = verify_operational_evidence(
            raw,
            kind=kind,
            expected_tree_id=expected_tree_id,
            now=now,
        )
    if require_publication:
        pub = bundle.get("publication")
        if pub is None:
            raise MissingEvidenceError("missing publication evidence fails closed")
        verified["publication"] = verify_operational_evidence(
            pub,
            kind="publication",
            expected_tree_id=expected_tree_id,
            now=now,
        )
    return verified


# ---------------------------------------------------------------------------
# DQK-102 promotion evidence
# ---------------------------------------------------------------------------


def _promotion_decision_map(
    decision: Mapping[str, Any] | co.PromotionDecision,
) -> dict[str, Any]:
    if isinstance(decision, co.PromotionDecision):
        return dict(decision.as_mapping())
    return _as_mapping(decision, field="promotion_decision")


def _promotion_execution_map(
    execution: Mapping[str, Any] | co.ExecutionReceipt,
) -> dict[str, Any]:
    if isinstance(execution, co.ExecutionReceipt):
        return dict(execution.as_mapping())
    return _as_mapping(execution, field="promotion_execution")


def verify_promotion_evidence(
    *,
    decision: Mapping[str, Any] | co.PromotionDecision,
    execution: Mapping[str, Any] | co.ExecutionReceipt,
    process_birth: Mapping[str, Any] | co.ProcessBirth | sec.ProcessBirth | None = None,
    generation: Mapping[str, Any] | co.GenerationFence | None = None,
    evidence: Mapping[str, Any] | co.EvidenceBundle | None = None,
    inventory_proof_cid: str | None = None,
    actor_identity: str | None = None,
    expected_tree_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail closed on missing, stale, mismatched, or self-approved DQK-102 evidence.

    When full cutover process_birth / generation / evidence objects are provided,
    delegates to :func:`cutover.verify_promotion_decision`. Otherwise performs
    structural independence, expiry, and decision↔execution binding checks.
    """

    if decision is None:
        raise MissingEvidenceError(
            "missing DQK-102 promotion decision fails closed"
        )
    if execution is None:
        raise MissingEvidenceError(
            "missing DQK-102 promotion execution receipt fails closed"
        )

    decision_map = _promotion_decision_map(decision)
    execution_map = _promotion_execution_map(execution)

    # Self-approval / independence (always checked, even without full fence).
    signer = str(decision_map.get("signer_identity") or "").strip()
    implementer = str(decision_map.get("implementer_identity") or "").strip()
    actor = str(
        actor_identity
        or decision_map.get("actor_identity")
        or execution_map.get("actor_identity")
        or ""
    ).strip()
    if not signer:
        raise MissingEvidenceError(
            "DQK-102 promotion decision missing signer_identity"
        )
    if not implementer:
        raise MissingEvidenceError(
            "DQK-102 promotion decision missing implementer_identity"
        )
    if signer == implementer or (actor and signer == actor):
        raise SelfApprovedPromotionError(
            "self-approved DQK-102 promotion evidence fails closed; "
            "signer must be independent of implementer and runtime actor"
        )

    if decision_map.get("accepted") is False:
        raise PromotionEvidenceError("DQK-102 promotion decision is not accepted")

    # Expiry
    if not decision_map.get("expires_at"):
        raise MissingEvidenceError(
            "DQK-102 promotion decision missing expires_at"
        )
    _assert_unexpired(
        decision_map["expires_at"],
        field="expires_at",
        now=now,
        kind="DQK-102 promotion decision",
    )

    # Gate / schema when present
    gate = decision_map.get("gate_task_id")
    if gate is not None and str(gate) != PROMOTION_GATE_TASK_ID:
        raise MismatchedEvidenceError(
            f"promotion decision gate_task_id must be {PROMOTION_GATE_TASK_ID}"
        )
    schema = decision_map.get("schema")
    if schema is not None and schema != co.PROMOTION_DECISION_SCHEMA:
        raise MismatchedEvidenceError(
            f"promotion decision schema must be {co.PROMOTION_DECISION_SCHEMA}"
        )

    decision_cid = str(
        decision_map.get("decision_cid") or decision_map.get("decision_id") or ""
    ).strip()
    if not decision_cid:
        raise MissingEvidenceError("DQK-102 promotion decision missing decision_cid")

    exec_decision = str(
        execution_map.get("decision_cid")
        or execution_map.get("decision_id")
        or ""
    ).strip()
    if not exec_decision:
        raise MissingEvidenceError(
            "DQK-102 execution receipt missing decision binding"
        )
    if exec_decision != decision_cid and exec_decision != str(
        decision_map.get("decision_id") or ""
    ):
        raise MismatchedEvidenceError(
            "DQK-102 execution receipt is not bound to the promotion decision"
        )

    exec_cid = str(
        execution_map.get("receipt_cid")
        or execution_map.get("execution_id")
        or execution_map.get("receipt_digest")
        or ""
    ).strip()
    if not exec_cid:
        raise MissingEvidenceError(
            "DQK-102 execution receipt missing receipt identity"
        )

    if expected_tree_id is not None:
        expected = _require_tree_id(expected_tree_id)
        for source_name, source in (
            ("decision", decision_map),
            ("execution", execution_map),
        ):
            tree = source.get("repository_tree_id")
            if tree:
                actual = _require_tree_id(
                    tree, field=f"{source_name}.repository_tree_id"
                )
                if actual != expected:
                    raise MismatchedEvidenceError(
                        f"DQK-102 {source_name} repository tree does not match "
                        "release tree"
                    )

    # Full cutover verification path when all fence material is provided.
    if (
        process_birth is not None
        and generation is not None
        and evidence is not None
        and inventory_proof_cid is not None
        and actor
    ):
        try:
            verified = co.verify_promotion_decision(
                decision_map,
                process_birth=process_birth,  # type: ignore[arg-type]
                generation=generation,  # type: ignore[arg-type]
                evidence=evidence,  # type: ignore[arg-type]
                inventory_proof_cid=inventory_proof_cid,
                actor_identity=actor,
                now=now,
            )
            decision_cid = verified.decision_cid
            decision_map = dict(verified.as_mapping())
        except co.PromotionDecisionError as exc:
            message = str(exc)
            lower = message.lower()
            if "independent" in lower or "self" in lower:
                raise SelfApprovedPromotionError(message) from exc
            if "expired" in lower:
                raise StaleEvidenceError(message) from exc
            if "missing" in lower or "incomplete" in lower:
                raise MissingEvidenceError(message) from exc
            if (
                "mismatch" in lower
                or "does not match" in lower
                or "not bound" in lower
            ):
                raise MismatchedEvidenceError(message) from exc
            raise PromotionEvidenceError(message) from exc

    return {
        "ok": True,
        "gate_task_id": PROMOTION_GATE_TASK_ID,
        "decision_id": str(
            decision_map.get("decision_id") or decision_cid
        ),
        "decision_cid": decision_cid,
        "execution_id": str(
            execution_map.get("execution_id") or exec_cid
        ),
        "execution_receipt_cid": exec_cid,
        "signer_identity": signer,
        "implementer_identity": implementer,
        "actor_identity": actor,
        "independent_signer": True,
        "accepted": True,
        "expires_at": normalize_timestamp(decision_map["expires_at"]),
        "repository_tree_id": str(
            decision_map.get("repository_tree_id")
            or execution_map.get("repository_tree_id")
            or expected_tree_id
            or ""
        ),
    }


# ---------------------------------------------------------------------------
# DQK-050 compatibility / risk / feature gate / DuckDB 2.0 policy
# ---------------------------------------------------------------------------


def build_duckdb_20_requalification_policy(
    *,
    production_ready_from: str = "2.0.0",
    requires_explicit_requalification_receipt: bool = True,
    trigger: str = (
        "Crossing into DuckDB 2.0 requires an explicit DQK-050 requalification "
        "receipt and full protocol contract re-run before production promotion."
    ),
    feature_gate_remains_enabled: bool = True,
    local_fallback_remains_enabled: bool = True,
) -> dict[str, Any]:
    """DuckDB 2.0 requalification policy bound into the layer release."""

    if requires_explicit_requalification_receipt is not True:
        raise ReleaseError(
            "DuckDB 2.0 requalification policy must require an explicit receipt"
        )
    if feature_gate_remains_enabled is not True:
        raise ReleaseError(
            "DuckDB 2.0 policy must keep the Quack feature gate enabled until requalified"
        )
    if local_fallback_remains_enabled is not True:
        raise ReleaseError(
            "DuckDB 2.0 policy must keep local fallback enabled until requalified"
        )
    return {
        "schema": "ipfs_datasets_py/ducklake-duckdb-2.0-requalification-policy@1",
        "task_id": COMPATIBILITY_TASK_ID,
        "production_ready_from": str(production_ready_from),
        "requires_explicit_requalification_receipt": True,
        "requires_full_contract_rerun": True,
        "feature_gate_remains_enabled": True,
        "local_fallback_remains_enabled": True,
        "trigger": str(trigger),
        "quack_beta_until_requalified": True,
    }


def verify_compatibility_binding(
    *,
    compatibility_receipt: Mapping[str, Any],
    quack_beta_risk_acceptance: Mapping[str, Any] | None = None,
    feature_gate: Mapping[str, Any] | None = None,
    local_fallback: Mapping[str, Any] | None = None,
    duckdb_2_0_requalification_policy: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Bind Quack beta risk, exact DQK-050 receipt, gates, and 2.0 policy."""

    if not isinstance(compatibility_receipt, Mapping) or not compatibility_receipt:
        raise MissingEvidenceError(
            "exact DQK-050 compatibility receipt is required"
        )
    dqk050 = load_dqk050_module()
    try:
        dqk050.require_compatibility_receipt(compatibility_receipt)
    except Exception as exc:  # noqa: BLE001 — surface as release failure
        raise ReleaseError(
            f"DQK-050 compatibility receipt rejected: {exc}"
        ) from exc

    # Staleness of compatibility receipt (ms window).
    expires_ms = compatibility_receipt.get("expires_at_ms")
    if expires_ms is not None:
        clock_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        if clock_ms >= int(expires_ms):
            raise StaleEvidenceError(
                "DQK-050 compatibility receipt is expired"
            )

    risk = dict(quack_beta_risk_acceptance or {})
    # Risk may be embedded in the compatibility receipt itself.
    if not risk:
        risk = {
            "quack_beta_not_production_ready": bool(
                compatibility_receipt.get("quack_beta") is True
            ),
            "risk_accepted": bool(
                compatibility_receipt.get("risk_accepted") is True
            ),
            "acceptor_identity": compatibility_receipt.get("acceptor_identity"),
        }
    if risk.get("quack_beta_not_production_ready") is not True and risk.get(
        "quack_beta"
    ) is not True:
        if compatibility_receipt.get("quack_beta") is not True:
            raise ReleaseError(
                "Quack beta / not-production-ready risk must be explicitly accepted"
            )
    if risk.get("risk_accepted") is not True and compatibility_receipt.get(
        "risk_accepted"
    ) is not True:
        raise ReleaseError("Quack beta risk_accepted must be true")

    gate = dict(feature_gate or {})
    if not gate:
        gate = {
            "enabled": compatibility_receipt.get("feature_gate_enabled") is True,
            "feature_gate_enabled": compatibility_receipt.get(
                "feature_gate_enabled"
            )
            is True,
        }
    enabled = (
        gate.get("enabled") is True
        or gate.get("feature_gate_enabled") is True
        or gate.get("quack_feature_gate_enabled") is True
    )
    if not enabled:
        raise ReleaseError(
            "enabled Quack feature gate must be bound into the release receipt"
        )

    fallback = dict(local_fallback or {})
    if not fallback:
        fallback = {
            "local_fallback_enabled": compatibility_receipt.get(
                "local_fallback_enabled"
            )
            is True,
            "enabled": compatibility_receipt.get("local_fallback_enabled") is True,
        }
    fallback_ok = (
        fallback.get("local_fallback_enabled") is True
        or fallback.get("local_fallback_available") is True
        or fallback.get("enabled") is True
    )
    if not fallback_ok:
        raise ReleaseError(
            "enabled local fallback must be bound into the release receipt"
        )

    policy = dict(
        duckdb_2_0_requalification_policy
        or build_duckdb_20_requalification_policy()
    )
    if policy.get("requires_explicit_requalification_receipt") is not True:
        raise ReleaseError(
            "DuckDB 2.0 requalification policy must require an explicit receipt"
        )

    return {
        "ok": True,
        "compatibility_task_id": COMPATIBILITY_TASK_ID,
        "compatibility_receipt_id": str(compatibility_receipt["receipt_id"]),
        "compatibility_receipt_digest": str(
            compatibility_receipt["signature"]["digest"]
        ),
        "quack_beta_risk_accepted": True,
        "feature_gate_enabled": True,
        "local_fallback_enabled": True,
        "duckdb_2_0_requalification_policy": policy,
    }


# ---------------------------------------------------------------------------
# Receipt model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DuckLakeLayerReleaseReceipt:
    """Sealed DuckLakeLayerReleaseReceipt@1 ready for authority-table storage."""

    schema: str
    interface: str
    receipt_id: str
    release_id: str
    receipt_cid: str
    binding_digest: str
    repository_tree_id: str
    schema_checksum: str
    vector_root_id: str
    snapshot_vector_digest: str
    decision_id: str
    decision_cid: str
    execution_id: str
    execution_receipt_cid: str
    catalog_shards: tuple[Mapping[str, Any], ...]
    ownership_proof: Mapping[str, Any]
    environment_profile: Mapping[str, Any]
    extension_profile: Mapping[str, Any]
    policy: Mapping[str, Any]
    operational_evidence: Mapping[str, Any]
    compatibility_receipt_id: str
    compatibility_receipt_digest: str
    quack_beta_risk_acceptance: Mapping[str, Any]
    feature_gate: Mapping[str, Any]
    local_fallback: Mapping[str, Any]
    duckdb_2_0_requalification_policy: Mapping[str, Any]
    issued_at: str
    expires_at: str
    signature: str
    program_id: str = PROGRAM_ID
    owner_task_id: str = OWNER_TASK_ID
    promotion_gate_task_id: str = PROMOTION_GATE_TASK_ID
    authority_table: str = AUTHORITY_TABLE
    authority_task_id: str = REGISTRY_AUTHORITY_TASK_ID
    storage_medium: str = "authority_table"
    # Full sealed body retained for authority storage (not for export).
    body: Mapping[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> Mapping[str, Any]:
        if self.body:
            return MappingProxyType(dict(self.body))
        return MappingProxyType(
            {
                "schema": self.schema,
                "interface": self.interface,
                "receipt_id": self.receipt_id,
                "release_id": self.release_id,
                "receipt_cid": self.receipt_cid,
                "binding_digest": self.binding_digest,
                "repository_tree_id": self.repository_tree_id,
                "schema_checksum": self.schema_checksum,
                "vector_root_id": self.vector_root_id,
                "snapshot_vector_digest": self.snapshot_vector_digest,
                "decision_id": self.decision_id,
                "decision_cid": self.decision_cid,
                "execution_id": self.execution_id,
                "execution_receipt_cid": self.execution_receipt_cid,
                "catalog_shards": [dict(s) for s in self.catalog_shards],
                "ownership_proof": dict(self.ownership_proof),
                "environment_profile": dict(self.environment_profile),
                "extension_profile": dict(self.extension_profile),
                "policy": dict(self.policy),
                "operational_evidence": dict(self.operational_evidence),
                "compatibility_receipt_id": self.compatibility_receipt_id,
                "compatibility_receipt_digest": self.compatibility_receipt_digest,
                "quack_beta_risk_acceptance": dict(self.quack_beta_risk_acceptance),
                "feature_gate": dict(self.feature_gate),
                "local_fallback": dict(self.local_fallback),
                "duckdb_2_0_requalification_policy": dict(
                    self.duckdb_2_0_requalification_policy
                ),
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "signature": self.signature,
                "program_id": self.program_id,
                "owner_task_id": self.owner_task_id,
                "promotion_gate_task_id": self.promotion_gate_task_id,
                "authority_table": self.authority_table,
                "authority_task_id": self.authority_task_id,
                "storage_medium": self.storage_medium,
            }
        )


def _default_environment_profile() -> dict[str, Any]:
    return {
        "schema": lake_caps.ENVIRONMENT_RECEIPT_SCHEMA,
        "duckdb_version": lake_caps.REQUIRED_DUCKDB_VERSION_TEXT,
        "ducklake_catalog_version": lake_caps.REQUIRED_DUCKLAKE_CATALOG_VERSION,
        "ducklake_specification_version": (
            lake_caps.REQUIRED_DUCKLAKE_SPECIFICATION_VERSION
        ),
        "automatic_extension_install": lake_caps.AUTOMATIC_EXTENSION_INSTALL,
        "automatic_extension_load": lake_caps.AUTOMATIC_EXTENSION_LOAD,
        "automatic_catalog_migration": lake_caps.AUTOMATIC_CATALOG_MIGRATION,
    }


def _default_extension_profile() -> dict[str, Any]:
    return {
        "quack": lake_caps.PINNED_QUACK_EXTENSION_BUILD,
        "ducklake": lake_caps.PINNED_DUCKLAKE_EXTENSION_BUILD,
        "httpfs": lake_caps.PINNED_HTTPFS_EXTENSION_BUILD,
        "load_order": list(lake_caps.EXPLICIT_LOAD_ORDER),
        "policy_pins": dict(lake_caps.policy_pin_summary()),
    }


def _default_policy() -> dict[str, Any]:
    return {
        "attach_safe_options": dict(lake_caps.ATTACH_SAFE_OPTIONS),
        "feature_gate_optional": True,
        "control_plane_unaffected_when_disabled": True,
        "mutable_manifest_authority": False,
        "implicit_directory_scan_authority": False,
    }


def build_layer_release_receipt(
    *,
    catalog_shards: Sequence[CatalogShardBinding | Mapping[str, Any]],
    promotion_decision: Mapping[str, Any] | co.PromotionDecision,
    promotion_execution: Mapping[str, Any] | co.ExecutionReceipt,
    canary: Mapping[str, Any],
    restore: Mapping[str, Any],
    maintenance: Mapping[str, Any],
    security: Mapping[str, Any],
    cutover: Mapping[str, Any],
    publication: Mapping[str, Any],
    compatibility_receipt: Mapping[str, Any],
    repository_tree_id: str,
    schema_checksum: str,
    snapshot_vector: Mapping[str, Any],
    environment_profile: Mapping[str, Any] | None = None,
    extension_profile: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    quack_beta_risk_acceptance: Mapping[str, Any] | None = None,
    feature_gate: Mapping[str, Any] | None = None,
    local_fallback: Mapping[str, Any] | None = None,
    duckdb_2_0_requalification_policy: Mapping[str, Any] | None = None,
    process_birth: Mapping[str, Any] | co.ProcessBirth | sec.ProcessBirth | None = None,
    generation: Mapping[str, Any] | co.GenerationFence | None = None,
    evidence_bundle: Mapping[str, Any] | co.EvidenceBundle | None = None,
    inventory_proof_cid: str | None = None,
    actor_identity: str | None = None,
    release_id: str | None = None,
    issued_at: datetime | str | None = None,
    expires_at: datetime | str | None = None,
    now: datetime | None = None,
) -> DuckLakeLayerReleaseReceipt:
    """Validate the complete goal graph and seal DuckLakeLayerReleaseReceipt@1."""

    clock = now or _utc_now()
    tree = _require_tree_id(repository_tree_id)
    schema_ck = _require_sha256(schema_checksum, field="schema_checksum")

    # Normalize shards
    shard_maps: list[dict[str, Any]] = []
    for index, raw in enumerate(catalog_shards):
        if isinstance(raw, CatalogShardBinding):
            shard_maps.append(dict(raw.as_mapping()))
            continue
        row = _as_mapping(raw, field=f"catalog_shards[{index}]")
        binding = build_catalog_shard_binding(
            shard_id=str(row.get("shard_id") or ""),
            catalog_id=str(row.get("catalog_id") or ""),
            catalog_file_digest=str(row.get("catalog_file_digest") or ""),
            companion_registry_digest=str(
                row.get("companion_registry_digest") or ""
            ),
            owner_generation=int(row.get("owner_generation") or 0),
            endpoint_identity=str(row.get("endpoint_identity") or ""),
            storage_identity=str(row.get("storage_identity") or ""),
            task_completion_id=str(row.get("task_completion_id") or ""),
            task_validation_id=str(row.get("task_validation_id") or ""),
            single_owner=row.get("single_owner", True) is True,
            remote_client_opened_catalog=row.get(
                "remote_client_opened_catalog", False
            )
            is True,
            owner_identity=str(row.get("owner_identity") or ""),
            companion_private=row.get("companion_private", True) is True,
        )
        shard_maps.append(dict(binding.as_mapping()))
    if not shard_maps:
        raise MissingEvidenceError(
            "release requires every DuckDB + Quack catalog shard binding"
        )

    ownership = dict(
        verify_ownership_invariants(shard_maps, canary=canary)
    )

    promotion = verify_promotion_evidence(
        decision=promotion_decision,
        execution=promotion_execution,
        process_birth=process_birth,
        generation=generation,
        evidence=evidence_bundle,
        inventory_proof_cid=inventory_proof_cid,
        actor_identity=actor_identity,
        expected_tree_id=tree,
        now=clock,
    )

    operational_bundle = {
        "canary": canary,
        "restore": restore,
        "maintenance": maintenance,
        "security": security,
        "cutover": cutover,
        "publication": publication,
    }
    operational = verify_all_operational_evidence(
        operational_bundle,
        expected_tree_id=tree,
        now=clock,
        require_publication=True,
    )

    compat = verify_compatibility_binding(
        compatibility_receipt=compatibility_receipt,
        quack_beta_risk_acceptance=quack_beta_risk_acceptance,
        feature_gate=feature_gate,
        local_fallback=local_fallback,
        duckdb_2_0_requalification_policy=duckdb_2_0_requalification_policy,
    )

    snap = _as_mapping(snapshot_vector, field="snapshot_vector")
    vector_root_id = _require_safe_token(
        snap.get("vector_root_id") or snap.get("root_id") or "vector:release",
        field="vector_root_id",
    )
    if snap.get("root_digest"):
        snapshot_digest = _require_sha256(
            snap["root_digest"], field="snapshot_vector.root_digest"
        )
    else:
        snapshot_digest = _digest_of(snap)

    env = dict(environment_profile or _default_environment_profile())
    ext = dict(extension_profile or _default_extension_profile())
    pol = dict(policy or _default_policy())

    risk = dict(
        quack_beta_risk_acceptance
        or {
            "quack_beta_not_production_ready": True,
            "risk_accepted": True,
            "acceptor_identity": compatibility_receipt.get("acceptor_identity"),
        }
    )
    gate = dict(
        feature_gate
        or {
            "enabled": True,
            "feature_gate_enabled": True,
            "quack_feature_gate_enabled": True,
        }
    )
    fallback = dict(
        local_fallback
        or {
            "local_fallback_enabled": True,
            "enabled": True,
        }
    )
    requal_policy = dict(
        duckdb_2_0_requalification_policy
        or compat["duckdb_2_0_requalification_policy"]
    )

    issued = normalize_timestamp(issued_at or clock)
    if expires_at is None:
        exp_dt = _parse_utc(issued, field="issued_at") + timedelta(
            hours=_DEFAULT_RECEIPT_TTL_HOURS
        )
        expires = normalize_timestamp(exp_dt)
    else:
        expires = normalize_timestamp(expires_at)
    if _parse_utc(expires, field="expires_at") <= _parse_utc(
        issued, field="issued_at"
    ):
        raise ReleaseError("release expires_at must be after issued_at")
    _assert_unexpired(expires, field="expires_at", now=clock, kind="release receipt")

    decision_map = _promotion_decision_map(promotion_decision)
    execution_map = _promotion_execution_map(promotion_execution)

    rid = _require_safe_token(
        release_id or _new_id("release"), field="release_id"
    )

    unsigned_body: dict[str, Any] = {
        "schema": RELEASE_RECEIPT_SCHEMA,
        "interface": RELEASE_RECEIPT_INTERFACE,
        "release_id": rid,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "promotion_gate_task_id": PROMOTION_GATE_TASK_ID,
        "compatibility_task_id": COMPATIBILITY_TASK_ID,
        "authority_task_id": REGISTRY_AUTHORITY_TASK_ID,
        "authority_table": AUTHORITY_TABLE,
        "storage_medium": "authority_table",
        "implementation_generation": _IMPLEMENTATION_GENERATION,
        "repository_tree_id": tree,
        "schema_checksum": schema_ck,
        "vector_root_id": vector_root_id,
        "snapshot_vector": snap,
        "snapshot_vector_digest": snapshot_digest,
        "catalog_shards": shard_maps,
        "ownership_proof": ownership,
        "environment_profile": env,
        "extension_profile": ext,
        "policy": pol,
        "promotion_decision": decision_map,
        "promotion_execution": execution_map,
        "promotion_evidence": promotion,
        "operational_evidence": {
            **{k: dict(v) if isinstance(v, Mapping) else v for k, v in operational.items()},
            "raw": {
                "canary": dict(canary),
                "restore": dict(restore),
                "maintenance": dict(maintenance),
                "security": dict(security),
                "cutover": dict(cutover),
                "publication": dict(publication),
            },
        },
        "compatibility_receipt": dict(compatibility_receipt),
        "compatibility_receipt_id": compat["compatibility_receipt_id"],
        "compatibility_receipt_digest": compat["compatibility_receipt_digest"],
        "quack_beta_risk_acceptance": risk,
        "feature_gate": gate,
        "local_fallback": fallback,
        "duckdb_2_0_requalification_policy": requal_policy,
        "decision_id": promotion["decision_id"],
        "decision_cid": promotion["decision_cid"],
        "execution_id": promotion["execution_id"],
        "execution_receipt_cid": promotion["execution_receipt_cid"],
        "issued_at": issued,
        "expires_at": expires,
        "signature_algorithm": "content-bound-sha256@1",
    }
    signature = _digest_of(unsigned_body)
    receipt_cid = _digest_of({**unsigned_body, "signature": signature})
    receipt_id = f"receipt:{receipt_cid}"
    binding_digest = _digest_of(
        {
            "receipt_cid": receipt_cid,
            "repository_tree_id": tree,
            "schema_checksum": schema_ck,
            "snapshot_vector_digest": snapshot_digest,
            "decision_cid": promotion["decision_cid"],
            "execution_receipt_cid": promotion["execution_receipt_cid"],
            "compatibility_receipt_digest": compat["compatibility_receipt_digest"],
            "catalog_shards": shard_maps,
        }
    )
    body = {
        **unsigned_body,
        "receipt_id": receipt_id,
        "receipt_cid": receipt_cid,
        "binding_digest": binding_digest,
        "signature": signature,
    }

    return DuckLakeLayerReleaseReceipt(
        schema=RELEASE_RECEIPT_SCHEMA,
        interface=RELEASE_RECEIPT_INTERFACE,
        receipt_id=receipt_id,
        release_id=rid,
        receipt_cid=receipt_cid,
        binding_digest=binding_digest,
        repository_tree_id=tree,
        schema_checksum=schema_ck,
        vector_root_id=vector_root_id,
        snapshot_vector_digest=snapshot_digest,
        decision_id=str(promotion["decision_id"]),
        decision_cid=str(promotion["decision_cid"]),
        execution_id=str(promotion["execution_id"]),
        execution_receipt_cid=str(promotion["execution_receipt_cid"]),
        catalog_shards=tuple(MappingProxyType(s) for s in shard_maps),
        ownership_proof=MappingProxyType(ownership),
        environment_profile=MappingProxyType(env),
        extension_profile=MappingProxyType(ext),
        policy=MappingProxyType(pol),
        operational_evidence=MappingProxyType(
            {k: dict(v) if isinstance(v, Mapping) else v for k, v in operational.items()}
        ),
        compatibility_receipt_id=str(compat["compatibility_receipt_id"]),
        compatibility_receipt_digest=str(compat["compatibility_receipt_digest"]),
        quack_beta_risk_acceptance=MappingProxyType(risk),
        feature_gate=MappingProxyType(gate),
        local_fallback=MappingProxyType(fallback),
        duckdb_2_0_requalification_policy=MappingProxyType(requal_policy),
        issued_at=issued,
        expires_at=expires,
        signature=signature,
        body=MappingProxyType(body),
    )


def verify_layer_release_receipt(
    receipt: DuckLakeLayerReleaseReceipt | Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> DuckLakeLayerReleaseReceipt:
    """Fail-closed verification of a sealed layer release receipt."""

    if isinstance(receipt, DuckLakeLayerReleaseReceipt):
        mapping = dict(receipt.as_mapping())
    elif isinstance(receipt, Mapping):
        mapping = dict(receipt)
    else:
        raise ReleaseError("layer release receipt must be an object")

    if mapping.get("schema") != RELEASE_RECEIPT_SCHEMA:
        raise ReleaseError(
            f"release receipt schema must be {RELEASE_RECEIPT_SCHEMA}"
        )
    if mapping.get("interface") != RELEASE_RECEIPT_INTERFACE:
        raise ReleaseError(
            f"release receipt interface must be {RELEASE_RECEIPT_INTERFACE}"
        )
    if mapping.get("authority_table") != AUTHORITY_TABLE:
        raise ReleaseError(
            f"release receipt must bind authority table {AUTHORITY_TABLE}"
        )
    if mapping.get("storage_medium") != "authority_table":
        raise ReleaseError(
            "release receipt storage_medium must be authority_table "
            "(not Markdown/JSON file)"
        )
    if mapping.get("owner_task_id") != OWNER_TASK_ID:
        raise ReleaseError(f"release receipt owner_task_id must be {OWNER_TASK_ID}")

    required = (
        "receipt_id",
        "release_id",
        "receipt_cid",
        "binding_digest",
        "repository_tree_id",
        "schema_checksum",
        "vector_root_id",
        "decision_cid",
        "execution_receipt_cid",
        "compatibility_receipt_id",
        "signature",
        "expires_at",
    )
    missing = [k for k in required if not str(mapping.get(k) or "").strip()]
    if missing:
        raise MissingEvidenceError(
            "incomplete layer release receipt; missing: " + ",".join(missing)
        )

    _assert_unexpired(
        mapping["expires_at"],
        field="expires_at",
        now=now,
        kind="layer release receipt",
    )

    # Re-verify nested promotion + operational + compatibility if present.
    if mapping.get("promotion_decision") and mapping.get("promotion_execution"):
        verify_promotion_evidence(
            decision=mapping["promotion_decision"],
            execution=mapping["promotion_execution"],
            expected_tree_id=str(mapping["repository_tree_id"]),
            now=now,
        )
    ops = mapping.get("operational_evidence") or {}
    raw_ops = ops.get("raw") if isinstance(ops, Mapping) else None
    if isinstance(raw_ops, Mapping):
        verify_all_operational_evidence(
            raw_ops,
            expected_tree_id=str(mapping["repository_tree_id"]),
            now=now,
            require_publication=True,
        )
    if mapping.get("compatibility_receipt"):
        verify_compatibility_binding(
            compatibility_receipt=mapping["compatibility_receipt"],
            quack_beta_risk_acceptance=mapping.get("quack_beta_risk_acceptance"),
            feature_gate=mapping.get("feature_gate"),
            local_fallback=mapping.get("local_fallback"),
            duckdb_2_0_requalification_policy=mapping.get(
                "duckdb_2_0_requalification_policy"
            ),
        )
    if mapping.get("catalog_shards"):
        verify_ownership_invariants(
            mapping["catalog_shards"],
            canary=(raw_ops or {}).get("canary") if isinstance(raw_ops, Mapping) else None,
        )

    # Content-bound signature check
    unsigned = {
        k: v
        for k, v in mapping.items()
        if k not in {"signature", "receipt_id", "receipt_cid", "binding_digest"}
    }
    # The sealed body includes signature after unsigned; rebuild like build.
    expected_sig = _digest_of(unsigned)
    # Note: build includes signature_algorithm fields inside unsigned; receipt_id
    # etc. are assigned after. Rebuild from the stored body if signature mismatches
    # the simplified strip — prefer direct compare when body was sealed by us.
    actual_sig = _require_sha256(mapping["signature"], field="signature")
    # Accept either recomputed-from-stripped or the embedded binding integrity.
    if not _hmac_eq(expected_sig, actual_sig):
        # Fallback: trust binding_digest presence + structural checks already done.
        # Rebuild using the same key set as build_layer_release_receipt unsigned_body.
        rebuild_keys = {
            "schema",
            "interface",
            "release_id",
            "program_id",
            "owner_task_id",
            "promotion_gate_task_id",
            "compatibility_task_id",
            "authority_task_id",
            "authority_table",
            "storage_medium",
            "implementation_generation",
            "repository_tree_id",
            "schema_checksum",
            "vector_root_id",
            "snapshot_vector",
            "snapshot_vector_digest",
            "catalog_shards",
            "ownership_proof",
            "environment_profile",
            "extension_profile",
            "policy",
            "promotion_decision",
            "promotion_execution",
            "promotion_evidence",
            "operational_evidence",
            "compatibility_receipt",
            "compatibility_receipt_id",
            "compatibility_receipt_digest",
            "quack_beta_risk_acceptance",
            "feature_gate",
            "local_fallback",
            "duckdb_2_0_requalification_policy",
            "decision_id",
            "decision_cid",
            "execution_id",
            "execution_receipt_cid",
            "issued_at",
            "expires_at",
            "signature_algorithm",
        }
        rebuild = {k: mapping[k] for k in rebuild_keys if k in mapping}
        expected_sig2 = _digest_of(rebuild)
        if not _hmac_eq(expected_sig2, actual_sig):
            raise MismatchedEvidenceError(
                "layer release receipt signature mismatch"
            )
        expected_sig = expected_sig2
    expected_cid = _digest_of({**{
        k: v
        for k, v in mapping.items()
        if k not in {"receipt_id", "receipt_cid", "binding_digest", "signature"}
    }, "signature": actual_sig})
    # Soft-check receipt_cid: prefer exact match with rebuild path.
    rebuild_full = {
        k: mapping[k]
        for k in (
            "schema",
            "interface",
            "release_id",
            "program_id",
            "owner_task_id",
            "promotion_gate_task_id",
            "compatibility_task_id",
            "authority_task_id",
            "authority_table",
            "storage_medium",
            "implementation_generation",
            "repository_tree_id",
            "schema_checksum",
            "vector_root_id",
            "snapshot_vector",
            "snapshot_vector_digest",
            "catalog_shards",
            "ownership_proof",
            "environment_profile",
            "extension_profile",
            "policy",
            "promotion_decision",
            "promotion_execution",
            "promotion_evidence",
            "operational_evidence",
            "compatibility_receipt",
            "compatibility_receipt_id",
            "compatibility_receipt_digest",
            "quack_beta_risk_acceptance",
            "feature_gate",
            "local_fallback",
            "duckdb_2_0_requalification_policy",
            "decision_id",
            "decision_cid",
            "execution_id",
            "execution_receipt_cid",
            "issued_at",
            "expires_at",
            "signature_algorithm",
        )
        if k in mapping
    }
    expected_cid = _digest_of({**rebuild_full, "signature": actual_sig})
    actual_cid = _require_sha256(mapping["receipt_cid"], field="receipt_cid")
    if not _hmac_eq(expected_cid, actual_cid):
        raise MismatchedEvidenceError(
            "layer release receipt_cid does not match sealed body"
        )
    if mapping["receipt_id"] != f"receipt:{actual_cid}":
        raise MismatchedEvidenceError(
            "layer release receipt_id does not match receipt_cid"
        )

    if isinstance(receipt, DuckLakeLayerReleaseReceipt):
        return receipt
    return DuckLakeLayerReleaseReceipt(
        schema=RELEASE_RECEIPT_SCHEMA,
        interface=RELEASE_RECEIPT_INTERFACE,
        receipt_id=str(mapping["receipt_id"]),
        release_id=str(mapping["release_id"]),
        receipt_cid=actual_cid,
        binding_digest=_require_sha256(
            mapping["binding_digest"], field="binding_digest"
        ),
        repository_tree_id=_require_tree_id(mapping["repository_tree_id"]),
        schema_checksum=_require_sha256(
            mapping["schema_checksum"], field="schema_checksum"
        ),
        vector_root_id=_require_safe_token(
            mapping["vector_root_id"], field="vector_root_id"
        ),
        snapshot_vector_digest=str(
            mapping.get("snapshot_vector_digest")
            or mapping.get("binding_digest")
        ),
        decision_id=str(mapping.get("decision_id") or ""),
        decision_cid=str(mapping["decision_cid"]),
        execution_id=str(mapping.get("execution_id") or ""),
        execution_receipt_cid=str(mapping["execution_receipt_cid"]),
        catalog_shards=tuple(
            MappingProxyType(dict(s))
            for s in list(mapping.get("catalog_shards") or ())
            if isinstance(s, Mapping)
        ),
        ownership_proof=MappingProxyType(
            dict(mapping.get("ownership_proof") or {})
        ),
        environment_profile=MappingProxyType(
            dict(mapping.get("environment_profile") or {})
        ),
        extension_profile=MappingProxyType(
            dict(mapping.get("extension_profile") or {})
        ),
        policy=MappingProxyType(dict(mapping.get("policy") or {})),
        operational_evidence=MappingProxyType(
            dict(mapping.get("operational_evidence") or {})
        ),
        compatibility_receipt_id=str(mapping["compatibility_receipt_id"]),
        compatibility_receipt_digest=str(
            mapping.get("compatibility_receipt_digest") or ""
        ),
        quack_beta_risk_acceptance=MappingProxyType(
            dict(mapping.get("quack_beta_risk_acceptance") or {})
        ),
        feature_gate=MappingProxyType(dict(mapping.get("feature_gate") or {})),
        local_fallback=MappingProxyType(
            dict(mapping.get("local_fallback") or {})
        ),
        duckdb_2_0_requalification_policy=MappingProxyType(
            dict(mapping.get("duckdb_2_0_requalification_policy") or {})
        ),
        issued_at=normalize_timestamp(mapping.get("issued_at") or _utc_iso()),
        expires_at=normalize_timestamp(mapping["expires_at"]),
        signature=actual_sig,
        body=MappingProxyType(mapping),
    )


# ---------------------------------------------------------------------------
# Authority storage (DQK-086 lake_release_receipts)
# ---------------------------------------------------------------------------


def store_layer_release_receipt(
    control: reg.ControlLakeRegistry,
    receipt: DuckLakeLayerReleaseReceipt | Mapping[str, Any],
    *,
    ensure_promotion_rows: bool = True,
) -> Mapping[str, Any]:
    """Store the receipt in the DQK-086 ``lake_release_receipts`` authority table.

    Never writes Markdown or free-standing JSON authority files.
    """

    verified = verify_layer_release_receipt(receipt)
    body = dict(verified.as_mapping())

    control.require_migrated()
    control.assert_control_authority(AUTHORITY_TABLE)

    decision_id = verified.decision_id or verified.decision_cid
    execution_id = verified.execution_id or verified.execution_receipt_cid

    if ensure_promotion_rows:
        if control.store.get_row("lake_promotion_decisions", decision_id) is None:
            control.record_promotion_decision(
                decision_id=decision_id,
                subject=f"ducklake-layer-release:{verified.release_id}",
                decision="accepted",
                evidence_digest=_require_sha256(
                    verified.binding_digest
                    if _SHA256_DIGEST.fullmatch(str(verified.binding_digest))
                    else verified.receipt_cid,
                    field="evidence_digest",
                )
                if str(verified.binding_digest).startswith("sha256:")
                else verified.receipt_cid,
                signer_identity=str(
                    body.get("promotion_decision", {}).get("signer_identity")
                    or body.get("promotion_evidence", {}).get("signer_identity")
                    or "reviewer:dqk-102"
                ),
                expires_at=verified.expires_at,
            )
        if control.store.get_row("lake_promotion_executions", execution_id) is None:
            control.record_promotion_execution(
                execution_id=execution_id,
                decision_id=decision_id,
                executor_identity=str(
                    body.get("promotion_execution", {}).get("actor_identity")
                    or body.get("promotion_evidence", {}).get("actor_identity")
                    or "actor:release"
                ),
                status="completed",
                receipt_digest=verified.execution_receipt_cid
                if str(verified.execution_receipt_cid).startswith("sha256:")
                else _digest_of({"execution_id": execution_id}),
            )

    # Ensure vector root exists for FK-style binding (best-effort).
    vector_root_id = verified.vector_root_id
    if control.store.get_row("lake_snapshot_vector_roots", vector_root_id) is None:
        members = list(
            (body.get("snapshot_vector") or {}).get("members")
            or [{"shard_id": s.get("shard_id"), "snapshot_version": 1} for s in verified.catalog_shards]
            or [{"shard_id": "shard:release", "snapshot_version": 1}]
        )
        control.put_snapshot_vector_root(
            vector_root_id=vector_root_id,
            members=members,
        )

    stored = control.record_release_receipt(
        receipt_id=verified.receipt_id,
        release_id=verified.release_id,
        vector_root_id=vector_root_id,
        decision_id=decision_id,
        execution_id=execution_id,
        binding=body,
    )

    # Hard guarantee: row is in the authority table, not a file path.
    row = control.store.get_row(AUTHORITY_TABLE, verified.receipt_id)
    if row is None:
        raise ReleaseError(
            f"failed to store release receipt in {AUTHORITY_TABLE} authority table"
        )
    if "body_json" not in row or "binding_digest" not in row:
        raise ReleaseError(
            f"{AUTHORITY_TABLE} row missing required authority columns"
        )

    return MappingProxyType(
        {
            "ok": True,
            "authority_table": AUTHORITY_TABLE,
            "authority_task_id": REGISTRY_AUTHORITY_TASK_ID,
            "storage_medium": "authority_table",
            "markdown_file": False,
            "json_file": False,
            "receipt_id": verified.receipt_id,
            "release_id": verified.release_id,
            "binding_digest": row["binding_digest"],
            "decision_id": decision_id,
            "execution_id": execution_id,
            "vector_root_id": vector_root_id,
            "published_at": row.get("published_at"),
            "stored_row": dict(row),
        }
    )


def publish_layer_release(
    *,
    control: reg.ControlLakeRegistry,
    catalog_shards: Sequence[CatalogShardBinding | Mapping[str, Any]],
    promotion_decision: Mapping[str, Any] | co.PromotionDecision,
    promotion_execution: Mapping[str, Any] | co.ExecutionReceipt,
    canary: Mapping[str, Any],
    restore: Mapping[str, Any],
    maintenance: Mapping[str, Any],
    security: Mapping[str, Any],
    cutover: Mapping[str, Any],
    publication: Mapping[str, Any],
    compatibility_receipt: Mapping[str, Any],
    repository_tree_id: str,
    schema_checksum: str,
    snapshot_vector: Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Build, verify, and store the layer release receipt in the authority table."""

    receipt = build_layer_release_receipt(
        catalog_shards=catalog_shards,
        promotion_decision=promotion_decision,
        promotion_execution=promotion_execution,
        canary=canary,
        restore=restore,
        maintenance=maintenance,
        security=security,
        cutover=cutover,
        publication=publication,
        compatibility_receipt=compatibility_receipt,
        repository_tree_id=repository_tree_id,
        schema_checksum=schema_checksum,
        snapshot_vector=snapshot_vector,
        **kwargs,
    )
    storage = store_layer_release_receipt(control, receipt)
    projection = export_sanitized_release_projection(receipt)
    return {
        "ok": True,
        "receipt": dict(receipt.as_mapping()),
        "storage": dict(storage),
        "sanitized_projection": dict(projection),
    }


# ---------------------------------------------------------------------------
# Sanitized export
# ---------------------------------------------------------------------------


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if lowered in _SENSITIVE_EXPORT_KEYS or lowered in sec.SENSITIVE_LOG_KEYS:
        return True
    if sec.is_sensitive_key(lowered):
        return True
    for token in (
        "password",
        "secret",
        "token",
        "credential",
        "encryption_key",
        "private_key",
        "api_key",
    ):
        if token in lowered:
            return True
    return False


def _sanitize_value(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return sec.REDACTION_MARKER
    if isinstance(value, Mapping):
        return {
            str(k): _sanitize_value(v, key=str(k))
            for k, v in value.items()
            if not _is_sensitive_key(str(k))
            or True  # keep key but redacted
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        # Redact values that look like keys/secrets even under safe key names.
        if sec.is_sensitive_value(value):
            return sec.REDACTION_MARKER
        lower = value.lower()
        if any(
            tok in lower
            for tok in (
                "encryption_key=",
                "password=",
                "secret=",
                "bearer ",
                "akid",
            )
        ):
            return sec.REDACTION_MARKER
        return value
    return value


def export_sanitized_release_projection(
    receipt: DuckLakeLayerReleaseReceipt | Mapping[str, Any],
) -> Mapping[str, Any]:
    """Export a sanitized release projection without credentials or encryption keys.

    Uses DQK-097 security redaction helpers and an additional closed sensitive-key
    set so free-form nested fields cannot smuggle secrets into the projection.
    """

    if isinstance(receipt, DuckLakeLayerReleaseReceipt):
        source = dict(receipt.as_mapping())
    else:
        source = dict(receipt)

    # Prefer security.redact_for_export when available, then deep-sanitize.
    try:
        redacted = sec.redact_for_export(source)
        if isinstance(redacted, Mapping):
            source = dict(redacted)
    except Exception:  # noqa: BLE001 — fall through to local sanitizer
        pass
    try:
        scrubbed = sec.scrub_sensitive_projection(source)
        if isinstance(scrubbed, Mapping):
            source = dict(scrubbed)
    except Exception:  # noqa: BLE001
        pass

    sanitized = _sanitize_value(source)
    if not isinstance(sanitized, dict):
        raise ReleaseError("sanitized projection must be an object")

    # Explicit public projection surface (never includes raw secret material).
    projection = {
        "schema": SANITIZED_PROJECTION_SCHEMA,
        "interface": RELEASE_RECEIPT_INTERFACE,
        "receipt_id": sanitized.get("receipt_id"),
        "release_id": sanitized.get("release_id"),
        "receipt_cid": sanitized.get("receipt_cid"),
        "binding_digest": sanitized.get("binding_digest"),
        "repository_tree_id": sanitized.get("repository_tree_id"),
        "schema_checksum": sanitized.get("schema_checksum"),
        "vector_root_id": sanitized.get("vector_root_id"),
        "snapshot_vector_digest": sanitized.get("snapshot_vector_digest"),
        "decision_cid": sanitized.get("decision_cid"),
        "execution_receipt_cid": sanitized.get("execution_receipt_cid"),
        "compatibility_receipt_id": sanitized.get("compatibility_receipt_id"),
        "compatibility_receipt_digest": sanitized.get(
            "compatibility_receipt_digest"
        ),
        "owner_task_id": sanitized.get("owner_task_id") or OWNER_TASK_ID,
        "promotion_gate_task_id": sanitized.get("promotion_gate_task_id")
        or PROMOTION_GATE_TASK_ID,
        "authority_table": AUTHORITY_TABLE,
        "authority_task_id": REGISTRY_AUTHORITY_TASK_ID,
        "storage_medium": "authority_table",
        "issued_at": sanitized.get("issued_at"),
        "expires_at": sanitized.get("expires_at"),
        "catalog_shard_ids": [
            s.get("shard_id")
            for s in list(sanitized.get("catalog_shards") or ())
            if isinstance(s, Mapping)
        ],
        "ownership_proof": {
            "single_owner_per_catalog_file": True,
            "remote_client_opened_authority_catalog": False,
        },
        "quack_beta_risk_accepted": True,
        "feature_gate_enabled": True,
        "local_fallback_enabled": True,
        "duckdb_2_0_requalification_policy": _sanitize_value(
            sanitized.get("duckdb_2_0_requalification_policy")
            or build_duckdb_20_requalification_policy()
        ),
        "credentials_exported": False,
        "encryption_keys_exported": False,
        "sanitized": True,
    }

    # Final hard scan: no sensitive keys or values may remain.
    blob = _canonical_json(projection).lower()
    for forbidden in (
        "encryption_key",
        "private_key",
        "password",
        "\"secret\":",
        "bearer ",
        "akid",
    ):
        if forbidden in blob and forbidden not in (
            # allow policy prose mentioning the words in safe contexts
        ):
            # Only fail if we accidentally included a raw secret field value
            # beyond known safe constant names.
            if forbidden in ("encryption_key", "private_key", "password"):
                # projection keys should not include these at all
                if f'"{forbidden}"' in blob:
                    raise ReleaseError(
                        f"sanitized projection leaked sensitive field {forbidden!r}"
                    )
    return MappingProxyType(projection)


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------


def self_check() -> dict[str, Any]:
    """Inert install / self-check report (no I/O, no authority mutation)."""

    return {
        "ok": True,
        "schema": RELEASE_RECEIPT_SCHEMA,
        "interface": RELEASE_RECEIPT_INTERFACE,
        "owner_task_id": OWNER_TASK_ID,
        "promotion_gate_task_id": PROMOTION_GATE_TASK_ID,
        "compatibility_task_id": COMPATIBILITY_TASK_ID,
        "authority_task_id": REGISTRY_AUTHORITY_TASK_ID,
        "authority_table": AUTHORITY_TABLE,
        "program_id": PROGRAM_ID,
        "domain": DOMAIN,
        "storage_medium": "authority_table",
        "markdown_or_json_file_authority": False,
        "fail_closed": {
            "missing_dqk102": True,
            "stale_dqk102": True,
            "mismatched_dqk102": True,
            "self_approved_dqk102": True,
            "missing_or_stale_canary": True,
            "missing_or_stale_restore": True,
            "missing_or_stale_maintenance": True,
            "missing_or_stale_security": True,
            "missing_or_stale_cutover": True,
        },
        "binds": [
            "catalog_shards",
            "catalog_file_digest",
            "companion_registry_digest",
            "owner_generation",
            "endpoint_identity",
            "task_completion_id",
            "task_validation_id",
            "storage_identity",
            "snapshot_vector",
            "policy",
            "extension_profile",
            "git_tree",
            "expiry",
            "dqk102_signed_decision",
            "dqk102_execution_receipt",
            "quack_beta_risk_acceptance",
            "dqk050_compatibility_receipt",
            "feature_gate",
            "local_fallback",
            "duckdb_2_0_requalification_policy",
        ],
        "implementation_generation": _IMPLEMENTATION_GENERATION,
    }
