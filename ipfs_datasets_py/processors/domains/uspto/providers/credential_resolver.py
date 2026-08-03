"""USPTO ODP credential reference resolution (PATLAW-120).

Credentials are held only as opaque references. Secret material is resolved
at request time through an injected source (environment, vault mapping, or
callable) and returned as :class:`ApiKeySecret`. Resolved values never appear
in ``repr``/``str``/diagnostics, receipts, or serializable configs.

Supported reference forms (case-sensitive scheme, fail-closed parsing):

* ``env:VAR_NAME`` — process environment variable
* ``vault:KEY`` / ``vault://KEY`` — vault backend key
* ``ref:REFERENCE_ID`` — abstract reference id looked up via vault backend
* bare ``REFERENCE_ID`` — same as ``ref:`` (no embedded secret material)

Inline secret material (``inline:``, ``secret:``, raw key blobs) is rejected.
Importing this module performs no I/O and never contacts a network.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

from .base import (
    API_KEY_HEADER,
    ApiKeySecret,
    ProviderConfigError,
    ProviderError,
    sanitize_secret_text,
)

CREDENTIAL_RESOLVER_SCHEMA_VERSION: Final = "uspto.provider.credential_resolver.v1"

# Official ODP header name (re-exported for adapter convenience).
ODP_API_KEY_HEADER: Final = API_KEY_HEADER

# Default environment variable names operators may use for ODP keys.
DEFAULT_ODP_ENV_NAMES: Final = (
    "USPTO_ODP_API_KEY",
    "USPTO_API_KEY",
    "ODP_API_KEY",
)

# Reference id / vault key: safe printable identifiers only.
_REFERENCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,127}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

# Schemes that would embed raw secret material — always rejected.
_FORBIDDEN_SCHEMES: Final = frozenset(
    {
        "inline",
        "secret",
        "plaintext",
        "raw",
        "bearer",
        "password",
        "token",
        "apikey",
        "api-key",
        "api_key",
        "x-api-key",
    }
)

_ALLOWED_SCHEMES: Final = frozenset({"env", "vault", "ref"})


class CredentialResolutionError(ProviderError):
    """Secret resolution failed without embedding secret material."""

    code = "credential_resolution_failed"

    def __init__(
        self,
        message: str = "credential resolution failed",
        *,
        code: str | None = None,
        reference_id: str | None = None,
    ) -> None:
        super().__init__(sanitize_secret_text(message), code=code or self.code)
        self.reference_id = reference_id

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        if self.reference_id is not None:
            out["reference_id"] = self.reference_id
        return out


class CredentialReferenceError(ProviderConfigError):
    """The credential reference itself is malformed or forbidden."""

    code = "invalid_credential_reference"


@dataclass(frozen=True, slots=True)
class CredentialReference:
    """Serializable pointer to secret material held outside this process.

    The reference never carries the secret. ``to_dict`` / ``repr`` expose only
    scheme + reference id (or a digest for long vault paths).
    """

    scheme: str
    name: str
    raw: str

    def __post_init__(self) -> None:
        scheme = str(self.scheme or "").strip().lower()
        name = str(self.name or "").strip()
        raw = str(self.raw or "").strip()
        if scheme in _FORBIDDEN_SCHEMES:
            raise CredentialReferenceError(
                f"credential scheme {scheme!r} embeds secret material and is forbidden"
            )
        if scheme not in _ALLOWED_SCHEMES:
            raise CredentialReferenceError(
                f"unsupported credential scheme: {scheme or '<empty>'!r}"
            )
        if not name or not raw:
            raise CredentialReferenceError("credential reference must be non-empty")
        if scheme == "env":
            if not _ENV_NAME_RE.fullmatch(name):
                raise CredentialReferenceError("environment variable name is invalid")
        else:
            if not _REFERENCE_ID_RE.fullmatch(name):
                raise CredentialReferenceError("credential reference name is invalid")
            if any(ch in name for ch in ("\x00", "\r", "\n")) or any(
                ch.isspace() for ch in name
            ):
                raise CredentialReferenceError(
                    "credential reference name contains invalid characters"
                )
        object.__setattr__(self, "scheme", scheme)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "raw", raw)

    @property
    def reference_id(self) -> str:
        """Stable public label for receipts and configs (never the secret)."""

        return self.name if self.scheme != "env" else f"env:{self.name}"

    @property
    def reference_digest(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()[:12]

    def __repr__(self) -> str:
        return (
            f"CredentialReference(scheme={self.scheme!r}, "
            f"reference_id={self.reference_id!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": "credential_reference",
            "reference_digest": self.reference_digest,
            "reference_id": self.reference_id,
            "scheme": self.scheme,
        }

    @classmethod
    def parse(cls, value: str | CredentialReference | ApiKeySecret) -> "CredentialReference":
        """Parse a reference string or wrap an existing typed reference."""

        if isinstance(value, CredentialReference):
            return value
        if isinstance(value, ApiKeySecret):
            # Existing secret already resolved: re-bind as ref: for labeling only.
            return cls(scheme="ref", name=value.reference_id, raw=f"ref:{value.reference_id}")
        if not isinstance(value, str) or not value.strip():
            raise CredentialReferenceError("credential reference must be a non-empty string")
        text = value.strip()
        if len(text) > 256:
            raise CredentialReferenceError("credential reference exceeds maximum length")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
            raise CredentialReferenceError("credential reference contains control characters")

        if "://" in text:
            scheme, _, rest = text.partition("://")
            name = rest.lstrip("/")
        elif ":" in text:
            scheme, _, name = text.partition(":")
            scheme_candidate = scheme.strip().lower()
            # Any explicit scheme-like prefix must be known; unknown schemes
            # fail closed rather than being silently treated as bare ids.
            # Treat common scheme shapes (including underscore forms like
            # ``api_key:``) as explicit schemes so forbidden ones fail closed.
            if re.fullmatch(r"[a-z][a-z0-9+._-]{0,31}", scheme_candidate):
                # Keep scheme/name split for allow/forbid checks below.
                pass
            else:
                # Not a URI scheme — keep entire text as bare ref id.
                scheme, name = "ref", text
        else:
            scheme, name = "ref", text

        scheme_l = scheme.strip().lower()
        name = name.strip()
        if scheme_l in _FORBIDDEN_SCHEMES:
            raise CredentialReferenceError(
                f"credential scheme {scheme_l!r} embeds secret material and is forbidden"
            )
        if scheme_l not in _ALLOWED_SCHEMES:
            raise CredentialReferenceError(
                f"unsupported credential scheme: {scheme_l!r}"
            )
        if not name:
            raise CredentialReferenceError("credential reference name is empty")
        return cls(scheme=scheme_l, name=name, raw=text)


@runtime_checkable
class CredentialSource(Protocol):
    """Backend that maps a reference name to a secret string."""

    def get(self, name: str) -> str | None:
        """Return the secret for *name*, or ``None`` if absent."""
        ...


class EnvironmentCredentialSource:
    """Read secrets from process environment variables only."""

    __slots__ = ("_environ",)

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        # Default: live os.environ at resolve time (not a frozen snapshot).
        self._environ = environ

    def get(self, name: str) -> str | None:
        if not _ENV_NAME_RE.fullmatch(name):
            return None
        env = self._environ if self._environ is not None else os.environ
        value = env.get(name)
        if value is None:
            return None
        text = str(value)
        if not text or text.strip() == "":
            return None
        return text

    def __repr__(self) -> str:
        return "EnvironmentCredentialSource(<env>)"


class MappingVaultCredentialSource:
    """In-memory or operator-injected vault mapping (tests and process vaults)."""

    __slots__ = ("_store", "label")

    def __init__(
        self,
        store: Mapping[str, str] | None = None,
        *,
        label: str = "vault",
    ) -> None:
        self._store = {str(k): str(v) for k, v in dict(store or {}).items()}
        if not isinstance(label, str) or not label or len(label) > 64:
            raise CredentialReferenceError("vault label is invalid")
        self.label = label

    def get(self, name: str) -> str | None:
        value = self._store.get(name)
        if value is None:
            return None
        if not value or not str(value).strip():
            return None
        return str(value)

    def put(self, name: str, value: str) -> None:
        """Insert or replace a vault entry (operator / test helper)."""

        if not _REFERENCE_ID_RE.fullmatch(name):
            raise CredentialReferenceError("vault key is invalid")
        if not isinstance(value, str) or not value:
            raise CredentialReferenceError("vault value must be a non-empty string")
        self._store[name] = value

    def __repr__(self) -> str:
        return f"MappingVaultCredentialSource(label={self.label!r}, keys={len(self._store)})"


class CallableCredentialSource:
    """Adapter around a pure ``name -> secret | None`` callable."""

    __slots__ = ("_lookup", "label")

    def __init__(
        self,
        lookup: Callable[[str], str | None],
        *,
        label: str = "callable",
    ) -> None:
        if not callable(lookup):
            raise TypeError("lookup must be callable")
        self._lookup = lookup
        self.label = str(label or "callable")[:64]

    def get(self, name: str) -> str | None:
        try:
            value = self._lookup(name)
        except CredentialResolutionError:
            raise
        except Exception as exc:  # noqa: BLE001 — untrusted backend
            raise CredentialResolutionError(
                f"credential backend error: {type(exc).__name__}"
            ) from None
        if value is None:
            return None
        if not isinstance(value, str):
            raise CredentialResolutionError("credential backend returned a non-string value")
        if not value:
            return None
        return value

    def __repr__(self) -> str:
        return f"CallableCredentialSource(label={self.label!r})"


class CredentialResolver:
    """Resolve opaque credential references to :class:`ApiKeySecret` at request time.

    No environment, file, or vault is consulted until :meth:`resolve` is called.
    Diagnostics and serializable state never include secret values.
    """

    __slots__ = (
        "_env_source",
        "_resolution_count",
        "_vault_source",
    )

    def __init__(
        self,
        *,
        env_source: CredentialSource | None = None,
        vault_source: CredentialSource | None = None,
    ) -> None:
        self._env_source: CredentialSource = env_source or EnvironmentCredentialSource()
        self._vault_source: CredentialSource = (
            vault_source or MappingVaultCredentialSource()
        )
        self._resolution_count = 0

    @classmethod
    def from_mapping(
        cls,
        vault: Mapping[str, str] | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "CredentialResolver":
        """Build a resolver with explicit vault and optional frozen environ."""

        return cls(
            env_source=EnvironmentCredentialSource(environ),
            vault_source=MappingVaultCredentialSource(vault),
        )

    @classmethod
    def from_env_defaults(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        extra_env_names: tuple[str, ...] = (),
    ) -> "CredentialResolver":
        """Resolver that only consults known ODP environment variable names.

        The returned resolver still requires an explicit ``env:NAME`` reference
        (or a bare name matching an env var via :meth:`resolve_default`).
        """

        _ = extra_env_names  # reserved for future allowlist tightening
        return cls(env_source=EnvironmentCredentialSource(environ))

    @property
    def resolution_count(self) -> int:
        return self._resolution_count

    def __repr__(self) -> str:
        return (
            f"CredentialResolver(env={self._env_source!r}, "
            f"vault={self._vault_source!r}, resolutions={self._resolution_count})"
        )

    def safe_config(self) -> dict[str, Any]:
        """Serializable config with no secrets."""

        return {
            "env_source": type(self._env_source).__name__,
            "resolution_count": self._resolution_count,
            "schema_version": CREDENTIAL_RESOLVER_SCHEMA_VERSION,
            "vault_source": type(self._vault_source).__name__,
        }

    def parse(self, reference: str | CredentialReference | ApiKeySecret) -> CredentialReference:
        return CredentialReference.parse(reference)

    def resolve(
        self,
        reference: str | CredentialReference | ApiKeySecret,
        *,
        reference_id: str | None = None,
    ) -> ApiKeySecret:
        """Resolve *reference* to an :class:`ApiKeySecret`.

        Already-resolved :class:`ApiKeySecret` instances are returned unchanged
        (no re-lookup). Failures raise :class:`CredentialResolutionError` with
        messages that never embed the secret value.
        """

        if isinstance(reference, ApiKeySecret):
            self._resolution_count += 1
            return reference

        parsed = CredentialReference.parse(reference)
        secret_text: str | None
        try:
            if parsed.scheme == "env":
                secret_text = self._env_source.get(parsed.name)
            else:
                # vault: and ref: both go through the vault backend.
                secret_text = self._vault_source.get(parsed.name)
        except CredentialResolutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CredentialResolutionError(
                f"credential resolution failed: {type(exc).__name__}",
                reference_id=parsed.reference_id,
            ) from None

        if secret_text is None:
            raise CredentialResolutionError(
                "credential not found",
                reference_id=parsed.reference_id,
            )
        if not isinstance(secret_text, str) or not secret_text:
            raise CredentialResolutionError(
                "credential backend returned an empty value",
                reference_id=parsed.reference_id,
            )
        # Reject values that look like nested references (prevent recursion).
        stripped = secret_text.strip()
        if "://" in stripped[:32] or (
            ":" in stripped
            and stripped.split(":", 1)[0].lower()
            in _ALLOWED_SCHEMES | _FORBIDDEN_SCHEMES
        ):
            # Allow only if the whole value clearly is not a scheme pointer —
            # real API keys almost never look like "env:FOO".
            scheme_part = stripped.split(":", 1)[0].lower()
            if scheme_part in _ALLOWED_SCHEMES | _FORBIDDEN_SCHEMES and len(
                stripped
            ) < 256:
                raise CredentialResolutionError(
                    "resolved credential looks like a nested reference",
                    reference_id=parsed.reference_id,
                )

        label = reference_id or parsed.reference_id
        try:
            secret = ApiKeySecret(secret_text, reference_id=label)
        except ProviderConfigError as exc:
            raise CredentialResolutionError(
                f"resolved credential is invalid: {exc}",
                reference_id=parsed.reference_id,
            ) from None
        self._resolution_count += 1
        return secret

    def resolve_default(
        self,
        *,
        env_names: tuple[str, ...] = DEFAULT_ODP_ENV_NAMES,
        vault_keys: tuple[str, ...] = (),
        reference_id: str = "odp-api-key",
    ) -> ApiKeySecret:
        """Resolve the first available default ODP credential source.

        Order: vault keys (if provided), then environment names. Raises if none
        resolve. Used by production bootstrap when no explicit ref is supplied.
        """

        for key in vault_keys:
            try:
                return self.resolve(f"vault:{key}", reference_id=reference_id)
            except CredentialResolutionError:
                continue
        for name in env_names:
            try:
                return self.resolve(f"env:{name}", reference_id=reference_id)
            except CredentialResolutionError:
                continue
        raise CredentialResolutionError(
            "no default ODP credential found in vault or environment",
            reference_id=reference_id,
        )

    def resolve_header(
        self,
        reference: str | CredentialReference | ApiKeySecret,
        *,
        header_name: str = ODP_API_KEY_HEADER,
        reference_id: str | None = None,
    ) -> dict[str, str]:
        """Resolve and return a single-header dict for request construction.

        The returned mapping holds the raw secret value for immediate use by
        the HTTP transport. Callers must not log or serialize the result.
        """

        if not isinstance(header_name, str) or not header_name.strip():
            raise CredentialReferenceError("header_name must be non-empty")
        secret = self.resolve(reference, reference_id=reference_id)
        return {header_name.strip(): secret.reveal()}

    def diagnostic_dict(
        self,
        reference: str | CredentialReference | ApiKeySecret | None = None,
    ) -> dict[str, Any]:
        """Safe diagnostic snapshot (no secrets)."""

        out: dict[str, Any] = {
            "schema_version": CREDENTIAL_RESOLVER_SCHEMA_VERSION,
            **self.safe_config(),
        }
        if reference is not None:
            if isinstance(reference, ApiKeySecret):
                out["reference"] = reference.to_dict()
            else:
                try:
                    parsed = CredentialReference.parse(reference)
                    out["reference"] = parsed.to_dict()
                except CredentialReferenceError as exc:
                    out["reference_error"] = {
                        "code": exc.code,
                        "message": str(exc),
                    }
        return out


def redact_credential_diagnostics(payload: Any, *, secret: str | None = None) -> Any:
    """Deep-copy *payload* with credential fields and secret values redacted."""

    if secret and isinstance(payload, str) and secret and secret in payload:
        return payload.replace(secret, "<redacted>")
    if isinstance(payload, Mapping):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_s = str(key)
            key_l = key_s.lower()
            if key_l in {
                "api_key",
                "apikey",
                "authorization",
                "cookie",
                "password",
                "secret",
                "token",
                "x-api-key",
                "x_api_key",
            }:
                out[key_s] = "<redacted>"
            elif key_l in {"reference_id", "kind", "scheme", "reference_digest"}:
                out[key_s] = value
            else:
                out[key_s] = redact_credential_diagnostics(value, secret=secret)
        return out
    if isinstance(payload, (list, tuple)):
        return [redact_credential_diagnostics(item, secret=secret) for item in payload]
    if isinstance(payload, str):
        text = sanitize_secret_text(payload)
        if secret and secret in text:
            text = text.replace(secret, "<redacted>")
        return text
    return payload


def contains_resolved_secret(payload: Any, secret: str) -> bool:
    """Return True if *secret* appears in a serialized form of *payload*."""

    if not secret:
        return False
    if isinstance(payload, str):
        return secret in payload
    try:
        import json

        text = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return secret in text


__all__ = [
    "API_KEY_HEADER",
    "CREDENTIAL_RESOLVER_SCHEMA_VERSION",
    "CallableCredentialSource",
    "CredentialReference",
    "CredentialReferenceError",
    "CredentialResolutionError",
    "CredentialResolver",
    "CredentialSource",
    "DEFAULT_ODP_ENV_NAMES",
    "EnvironmentCredentialSource",
    "MappingVaultCredentialSource",
    "ODP_API_KEY_HEADER",
    "contains_resolved_secret",
    "redact_credential_diagnostics",
]
