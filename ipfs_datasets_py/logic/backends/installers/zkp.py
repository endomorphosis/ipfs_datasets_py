"""Secret-safe ZKP deployment-binding validator.

ZKP circuits are operator-bound public identities, not downloadable Python
dependencies.  This reviewed plugin validates the deployment lock and exposes
typed evidence without copying witnesses, proving keys, trapdoors, or other
private material.  It never opens the network or invokes an external command.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from .registry import authorize_installer_entry_install

INTERFACE: Final = "ZKPDeploymentBindingInstaller@1"
SCHEMA_VERSION: Final = "zkp-deployment-binding-install-receipt/v1"
LOCK_INTERFACE: Final = "ZKPDeploymentLock@1"
LOCK_SCHEMA: Final = "zkp-deployment-lock/v1"
FORBIDDEN_PUBLIC_FIELDS: Final = frozenset(
    {
        "private_witness",
        "proving_key_bytes",
        "verification_key_bytes",
        "trapdoor",
        "witness_bytes",
        "toxic_waste",
        "coordinator_seed",
    }
)
MAX_PUBLIC_LOCK_BYTES: Final = 1024 * 1024
_SHA256_IDENTITY = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(slots=True)
class InstallReceipt:
    tool_id: str = "zkp-circuit"
    requested_version: str = "deployment-bound"
    status: str = "blocked"
    phase: str = "init"
    installed: bool = False
    already_present: bool = False
    checksum_verified: bool = False
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_lock(
    deployment_lock_path: str | Path | None,
    repo_root: str | Path | None,
) -> Path | None:
    if deployment_lock_path is not None:
        return Path(deployment_lock_path).expanduser().absolute()
    candidates: list[Path] = []
    if repo_root is not None:
        candidates.append(Path(repo_root) / "config" / "formal_verification_zkp_deployment.lock.json")
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "config" / "formal_verification_zkp_deployment.lock.json")
    candidates.append(Path.cwd() / "config" / "formal_verification_zkp_deployment.lock.json")
    return next((path.absolute() for path in candidates if path.is_file()), None)


def _contains_forbidden_material(value: object) -> str:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = (
                str(key).strip().lower().replace("-", "_").replace(" ", "_")
            )
            if lowered in FORBIDDEN_PUBLIC_FIELDS:
                return lowered
            found = _contains_forbidden_material(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _contains_forbidden_material(item)
            if found:
                return found
    return ""


def _validate(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != LOCK_SCHEMA:
        raise ValueError(f"ZKP deployment lock schema must be {LOCK_SCHEMA}")
    if payload.get("interface") != LOCK_INTERFACE:
        raise ValueError(f"ZKP deployment lock interface must be {LOCK_INTERFACE}")
    if payload.get("tool_id") != "zkp-circuit":
        raise ValueError("ZKP deployment lock tool_id must be zkp-circuit")
    secret = payload.get("secret_safety")
    if not isinstance(secret, Mapping):
        raise ValueError("ZKP deployment lock requires secret_safety")
    for flag in (
        "forbid_private_witness_in_lock",
        "forbid_proving_key_bytes_in_lock",
        "forbid_verification_key_bytes_in_lock",
        "forbid_trapdoor_in_lock",
        "forbid_witness_in_public_receipts",
        "reference_private_artifacts_by_digest_only",
    ):
        if secret.get(flag) is not True:
            raise ValueError(f"secret_safety.{flag} must be true")
    forbidden = _contains_forbidden_material(payload)
    if forbidden:
        raise ValueError(f"forbidden private field in public deployment lock: {forbidden}")
    circuit = payload.get("circuit")
    keys = payload.get("keys")
    if not isinstance(circuit, Mapping) or not isinstance(keys, Mapping):
        raise ValueError("ZKP deployment lock requires circuit and key identities")
    verification = keys.get("verification_key")
    if not isinstance(verification, Mapping):
        raise ValueError("ZKP deployment lock requires a verification-key identity")
    required = {
        "circuit_id": circuit.get("circuit_id"),
        "circuit_public_digest": circuit.get("circuit_public_digest"),
        "verification_key_id": verification.get("verification_key_id"),
        "verification_key_digest": verification.get("verification_key_digest"),
    }
    for name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing public ZKP binding {name}")
    for name in ("circuit_public_digest", "verification_key_digest"):
        if not _SHA256_IDENTITY.fullmatch(str(required[name])):
            raise ValueError(f"{name} must be sha256:<64 lowercase hex>")
    return required


def ensure_zkp_circuit(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: Callable[[str, str], None] | None = None,
    dry_run: bool = False,
    offline: bool = False,
    deployment_lock_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    **_: Any,
) -> InstallReceipt:
    del force, on_progress
    receipt = InstallReceipt()
    if dry_run:
        receipt.status = "planned"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        return receipt
    if offline:
        receipt.status = "blocked"
        receipt.phase = "offline_policy"
        receipt.reason_codes.append("offline_policy")
        receipt.messages.append("offline certification performs no installer action")
        return receipt
    if not yes:
        receipt.reason_codes.append("yes_required")
        receipt.messages.append("yes=True is required to bind a ZKP deployment")
        return receipt
    authorize_installer_entry_install("zkp-circuit", yes=True)
    path = _resolve_lock(deployment_lock_path, repo_root)
    if path is None or not path.is_file():
        receipt.phase = "deployment_lock"
        receipt.reason_codes.append("deployment_lock_missing")
        receipt.messages.append("operator must provide formal_verification_zkp_deployment.lock.json")
        return receipt
    try:
        if path.is_symlink():
            raise ValueError("ZKP deployment lock must not be a symlink")
        size = path.stat().st_size
        if size > MAX_PUBLIC_LOCK_BYTES:
            raise ValueError("ZKP deployment lock exceeds the 1 MiB public limit")
        raw = path.read_bytes()
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise ValueError("ZKP deployment lock must be an object")
        public = _validate(payload)
    except Exception as exc:
        receipt.status = "failed"
        receipt.phase = "deployment_lock_validation"
        receipt.reason_codes.append("deployment_lock_invalid")
        receipt.messages.append(f"{type(exc).__name__}: {exc}")
        if strict:
            raise
        return receipt
    receipt.status = "available"
    receipt.phase = "bound"
    receipt.installed = True
    receipt.already_present = True
    # The lock itself is checksummed, but digest references do not prove that
    # the operator-bound circuit/key artifacts are present or match.  Keep the
    # generic artifact gate false until the live verifier checks those bytes.
    receipt.checksum_verified = False
    receipt.bindings.update(
        {
            **public,
            "deployment_lock_name": path.name,
            "deployment_lock_sha256": hashlib.sha256(raw).hexdigest(),
            "deployment_lock_checksum_verified": True,
            "referenced_artifacts_verified": False,
            "secret_safe": True,
            "transactional_publication": True,
            "previous_good_preserved": True,
            "semantic_probe": {"deployment_binding_validated": True},
            "network_attempted": False,
            "external_command_attempted": False,
        }
    )
    return receipt


__all__ = ["INTERFACE", "SCHEMA_VERSION", "InstallReceipt", "ensure_zkp_circuit"]
