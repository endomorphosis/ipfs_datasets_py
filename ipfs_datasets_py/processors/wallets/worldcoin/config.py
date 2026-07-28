"""World ID backend configuration and secret descriptors.

This module is pure configuration: no network I/O, no crypto, and no secret
resolution at import time.  Secret *values* are never present in public
serializations; durable serialization retains opaque secret references only.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse


DEFAULT_WORLD_ID_ACTION = "wallet-attach-world-id-v1"
DEFAULT_WORLD_ID_CREDENTIAL_POLICY = "proof_of_human"
DEFAULT_WORLD_ID_VERIFY_BASE_URL = "https://developer.world.org"
DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS = 300
DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS = 15.0
SUPPORTED_WORLD_ID_ENVIRONMENTS = frozenset({"staging", "production"})

_PUBLIC_SECRET_ENV_NAMES = frozenset(
    {
        "ABBY_RUNTIME_WORLD_ID_NULLIFIER_HMAC_KEY",
        "ABBY_RUNTIME_WORLD_ID_RP_SIGNING_KEY",
        "VITE_WORLD_ID_NULLIFIER_HMAC_KEY",
        "VITE_WORLD_ID_RP_SIGNING_KEY",
    }
)


class WorldIdConfigError(ValueError):
    """Raised when World ID backend configuration is invalid."""


@dataclass(frozen=True)
class WorldIdSecretConfig:
    """Backend-only secret configuration without exposing values in repr output."""

    value: str = field(default="", repr=False)
    secret_ref: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.value or self.secret_ref)

    def public_dict(self) -> dict[str, bool | str]:
        """Browser-safe view: configured flag and source kind only."""

        return {
            "configured": self.configured,
            "source": "secret_ref" if self.secret_ref else ("direct" if self.value else ""),
        }

    def to_dict(self) -> dict[str, object]:
        """Durable serialization: secret references only, never raw values."""

        payload: dict[str, object] = {
            "configured": self.configured,
            "source": "secret_ref" if self.secret_ref else ("direct" if self.value else ""),
        }
        if self.secret_ref:
            digest = hashlib.sha256(self.secret_ref.encode("utf-8")).hexdigest()[:12]
            payload["reference_id"] = digest
            payload["kind"] = "secret_reference"
        elif self.value:
            # Value present but never serialized: only an opaque direct marker.
            payload["kind"] = "direct_secret"
            payload["reference_id"] = "direct"
        else:
            payload["kind"] = "unset"
        return payload


@dataclass(frozen=True)
class WorldIdConfig:
    """Validated backend configuration for World ID wallet binding.

    Safe defaults reject legacy IDKit evidence unless explicitly permitted
    via ``allow_legacy_proofs=True``.
    """

    enabled: bool
    environment: str = "staging"
    app_id: str = ""
    rp_id: str = ""
    allowed_actions: tuple[str, ...] = (DEFAULT_WORLD_ID_ACTION,)
    default_action: str = DEFAULT_WORLD_ID_ACTION
    credential_policy: str = DEFAULT_WORLD_ID_CREDENTIAL_POLICY
    allow_legacy_proofs: bool = False
    require_user_presence: bool = False
    rp_signature_ttl_seconds: int = DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS
    verify_base_url: str = DEFAULT_WORLD_ID_VERIFY_BASE_URL
    http_timeout_seconds: float = DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS
    rp_signing_key: WorldIdSecretConfig = field(default_factory=WorldIdSecretConfig, repr=False)
    nullifier_hmac_key: WorldIdSecretConfig = field(default_factory=WorldIdSecretConfig, repr=False)

    @property
    def public_actions(self) -> list[str]:
        return list(self.allowed_actions)

    def public_dict(self) -> dict[str, object]:
        """Return browser-safe configuration without backend secrets."""

        return {
            "enabled": self.enabled,
            "environment": self.environment,
            "app_id": self.app_id,
            "rp_id": self.rp_id,
            "allowed_actions": list(self.allowed_actions),
            "default_action": self.default_action,
            "credential_policy": self.credential_policy,
            "allow_legacy_proofs": self.allow_legacy_proofs,
            "require_user_presence": self.require_user_presence,
            "rp_signature_ttl_seconds": self.rp_signature_ttl_seconds,
            "verify_base_url": self.verify_base_url,
            "http_timeout_seconds": self.http_timeout_seconds,
        }

    def to_dict(self) -> dict[str, object]:
        """Serialize for durable storage. Secret values are never included."""

        return {
            **self.public_dict(),
            "rp_signing_key": self.rp_signing_key.to_dict(),
            "nullifier_hmac_key": self.nullifier_hmac_key.to_dict(),
        }


def load_world_id_config(env: Mapping[str, str] | None = None) -> WorldIdConfig:
    """Load and validate World ID wallet-binding configuration.

    When *env* is provided, only that mapping is read (no process env or secret
    manager I/O).  When *env* is ``None``, process environment is used and
    secret values may be resolved through the package secret helper.
    """

    _reject_public_secret_leaks(env)
    enabled = _bool_env(env, "WORLD_ID_ENABLED", default=False)
    environment = _str_env(env, "WORLD_ID_ENVIRONMENT", "staging").lower()
    if environment not in SUPPORTED_WORLD_ID_ENVIRONMENTS:
        raise WorldIdConfigError("WORLD_ID_ENVIRONMENT must be staging or production")

    default_action = _str_env(env, "WORLD_ID_DEFAULT_ACTION", DEFAULT_WORLD_ID_ACTION)
    allowed_actions = _actions_from_env(env, default_action)
    if default_action not in allowed_actions:
        raise WorldIdConfigError("WORLD_ID_DEFAULT_ACTION must be included in WORLD_ID_ALLOWED_ACTIONS")

    config = WorldIdConfig(
        enabled=enabled,
        environment=environment,
        app_id=_str_env(env, "WORLD_ID_APP_ID", ""),
        rp_id=_str_env(env, "WORLD_ID_RP_ID", ""),
        allowed_actions=tuple(allowed_actions),
        default_action=default_action,
        credential_policy=_str_env(env, "WORLD_ID_CREDENTIAL_POLICY", DEFAULT_WORLD_ID_CREDENTIAL_POLICY),
        # Safe default: legacy (v3) evidence is rejected unless explicitly enabled.
        allow_legacy_proofs=_bool_env(env, "WORLD_ID_ALLOW_LEGACY_PROOFS", default=False),
        require_user_presence=_bool_env(env, "WORLD_ID_REQUIRE_USER_PRESENCE", default=False),
        rp_signature_ttl_seconds=_positive_int_env(
            env,
            "WORLD_ID_RP_SIGNATURE_TTL_SECONDS",
            DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS,
        ),
        verify_base_url=_url_env(env, "WORLD_ID_VERIFY_BASE_URL", DEFAULT_WORLD_ID_VERIFY_BASE_URL),
        http_timeout_seconds=_positive_float_env(
            env,
            "WORLD_ID_HTTP_TIMEOUT_SECONDS",
            DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS,
        ),
        rp_signing_key=WorldIdSecretConfig(
            value=_secret_env(env, "WORLD_ID_RP_SIGNING_KEY"),
            secret_ref=_str_env(env, "WORLD_ID_RP_SIGNING_KEY_SECRET_REF", ""),
        ),
        nullifier_hmac_key=WorldIdSecretConfig(
            value=_secret_env(env, "WORLD_ID_NULLIFIER_HMAC_KEY"),
            secret_ref=_str_env(env, "WORLD_ID_NULLIFIER_HMAC_KEY_SECRET_REF", ""),
        ),
    )
    if enabled:
        _validate_enabled_config(config)
    return config


def validate_verify_base_url(value: str) -> str:
    """Normalize and validate a Developer Portal base URL (no network I/O)."""

    normalized = str(value or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WorldIdConfigError("base URL must be an absolute http(s) URL")
    return normalized


def _validate_enabled_config(config: WorldIdConfig) -> None:
    missing: list[str] = []
    if not config.app_id:
        missing.append("WORLD_ID_APP_ID")
    if not config.rp_id:
        missing.append("WORLD_ID_RP_ID")
    if not config.rp_signing_key.configured:
        missing.append("WORLD_ID_RP_SIGNING_KEY or WORLD_ID_RP_SIGNING_KEY_SECRET_REF")
    if not config.nullifier_hmac_key.configured:
        missing.append("WORLD_ID_NULLIFIER_HMAC_KEY or WORLD_ID_NULLIFIER_HMAC_KEY_SECRET_REF")
    if missing:
        raise WorldIdConfigError(
            f"World ID is enabled but missing required configuration: {', '.join(missing)}"
        )
    if not config.app_id.startswith("app_"):
        raise WorldIdConfigError("WORLD_ID_APP_ID must start with app_")
    if not config.rp_id.startswith("rp_"):
        raise WorldIdConfigError("WORLD_ID_RP_ID must start with rp_")


def _actions_from_env(env: Mapping[str, str] | None, default_action: str) -> list[str]:
    raw = _str_env(env, "WORLD_ID_ALLOWED_ACTIONS", default_action)
    actions: list[str] = []
    for item in raw.split(","):
        action = item.strip()
        if not action:
            continue
        if any(char.isspace() for char in action):
            raise WorldIdConfigError("World ID actions must not contain whitespace")
        if action not in actions:
            actions.append(action)
    if not actions:
        raise WorldIdConfigError("At least one World ID action must be configured")
    return actions


def _reject_public_secret_leaks(env: Mapping[str, str] | None) -> None:
    source = env if env is not None else os.environ
    leaked = sorted(name for name in _PUBLIC_SECRET_ENV_NAMES if str(source.get(name) or "").strip())
    if leaked:
        raise WorldIdConfigError(
            "World ID signing/nullifier secrets must not be configured in browser-exposed env vars: "
            + ", ".join(leaked)
        )


def _str_env(env: Mapping[str, str] | None, name: str, default: str) -> str:
    source = env if env is not None else os.environ
    return str(source.get(name) or default).strip()


def _secret_env(env: Mapping[str, str] | None, name: str) -> str:
    if env is not None:
        return str(env.get(name) or "").strip()
    # Lazy import so package import has no secret-manager side effects.
    from ipfs_datasets_py.utils.secrets import resolve_secret

    return resolve_secret(name).strip()


def _bool_env(env: Mapping[str, str] | None, name: str, *, default: bool) -> bool:
    raw = _str_env(env, name, "")
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in {"1", "true", "yes", "on", "enabled"}:
        return True
    if lowered in {"0", "false", "no", "off", "disabled"}:
        return False
    raise WorldIdConfigError(f"{name} must be a boolean value")


def _positive_int_env(env: Mapping[str, str] | None, name: str, default: int) -> int:
    raw = _str_env(env, name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise WorldIdConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise WorldIdConfigError(f"{name} must be positive")
    return value


def _positive_float_env(env: Mapping[str, str] | None, name: str, default: float) -> float:
    raw = _str_env(env, name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise WorldIdConfigError(f"{name} must be a number") from exc
    if value <= 0:
        raise WorldIdConfigError(f"{name} must be positive")
    return value


def _url_env(env: Mapping[str, str] | None, name: str, default: str) -> str:
    try:
        return validate_verify_base_url(_str_env(env, name, default))
    except WorldIdConfigError as exc:
        raise WorldIdConfigError(f"{name} must be an absolute http(s) URL") from exc


__all__ = [
    "DEFAULT_WORLD_ID_ACTION",
    "DEFAULT_WORLD_ID_CREDENTIAL_POLICY",
    "DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS",
    "DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS",
    "DEFAULT_WORLD_ID_VERIFY_BASE_URL",
    "SUPPORTED_WORLD_ID_ENVIRONMENTS",
    "WorldIdConfig",
    "WorldIdConfigError",
    "WorldIdSecretConfig",
    "load_world_id_config",
    "validate_verify_base_url",
]
