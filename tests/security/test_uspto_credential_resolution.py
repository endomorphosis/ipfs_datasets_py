"""Security tests for USPTO ODP credential reference resolution (PATLAW-120).

Proves:
* secrets resolve only at request time through env/vault backends
* references never embed raw secret material
* serializable configs, diagnostics, receipts, and error messages never leak
* forbidden inline/secret schemes are rejected fail-closed
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    API_KEY_HEADER,
    ApiKeySecret,
    HttpRequest,
    contains_secret_leak,
    sanitize_headers,
    sanitize_secret_text,
)
from ipfs_datasets_py.processors.domains.uspto.providers.credential_resolver import (
    CREDENTIAL_RESOLVER_SCHEMA_VERSION,
    CallableCredentialSource,
    CredentialReference,
    CredentialReferenceError,
    CredentialResolutionError,
    CredentialResolver,
    EnvironmentCredentialSource,
    MappingVaultCredentialSource,
    contains_resolved_secret,
    redact_credential_diagnostics,
)
from ipfs_datasets_py.processors.domains.uspto.providers.http_transport import (
    BoundedHttpTransport,
    HostAllowlistPolicy,
    ScriptedOpener,
)

# Synthetic canary values — not live credentials.
CANARY = "uspto-odp-canary-secret-VALUE-9f3a2c"
CANARY_ENV = "uspto-odp-env-canary-VALUE-aa11"
VAULT_KEY = "odp/production/api-key"
ENV_NAME = "USPTO_ODP_API_KEY_TEST_CANARY"


def _request_header(request: object, name: str) -> str | None:
    target = name.lower()
    for bag_name in ("headers", "unredirected_hdrs"):
        bag = getattr(request, bag_name, None) or {}
        for key, value in dict(bag).items():
            if str(key).lower() == target:
                return str(value)
    return None


def _blob(*parts: object) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, (dict, list, tuple)):
            chunks.append(json.dumps(part, sort_keys=True, default=str))
        else:
            chunks.append(repr(part))
            chunks.append(str(part))
    return "\n".join(chunks)


def _assert_clean(text: str, *secrets: str) -> None:
    for secret in secrets:
        assert secret not in text, f"secret leaked into diagnostic surface"
    assert not re.search(
        r"x-api-key['\"]?\s*[:=]\s*['\"]?(?!<redacted>)[A-Za-z0-9_\-]{8,}",
        text,
        re.I,
    )


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------


def test_reference_parse_schemes() -> None:
    env_ref = CredentialReference.parse(f"env:{ENV_NAME}")
    assert env_ref.scheme == "env"
    assert env_ref.name == ENV_NAME
    assert env_ref.reference_id == f"env:{ENV_NAME}"

    vault_ref = CredentialReference.parse(f"vault:{VAULT_KEY}")
    assert vault_ref.scheme == "vault"
    assert vault_ref.name == VAULT_KEY

    vault_uri = CredentialReference.parse(f"vault://{VAULT_KEY}")
    assert vault_uri.scheme == "vault"
    assert vault_uri.name == VAULT_KEY

    bare = CredentialReference.parse("odp-api-key")
    assert bare.scheme == "ref"
    assert bare.name == "odp-api-key"

    ref_scheme = CredentialReference.parse("ref:odp-api-key")
    assert ref_scheme.scheme == "ref"


@pytest.mark.parametrize(
    "raw",
    [
        "inline:super-secret",
        "secret:abc",
        "plaintext:xyz",
        "raw:deadbeef",
        "bearer:tok",
        "token:abc",
        "api_key:value",
        "password:hunter2",
        "",
        "env:",
        "vault:",
        "env:not-valid-name!",
        "vault:bad key with spaces",
        "unknown:something",
    ],
)
def test_forbidden_and_invalid_references_rejected(raw: str) -> None:
    with pytest.raises((CredentialReferenceError, CredentialResolutionError)):
        CredentialReference.parse(raw)


def test_reference_repr_and_dict_never_contain_secret() -> None:
    ref = CredentialReference.parse(f"vault:{VAULT_KEY}")
    text = _blob(ref, ref.to_dict(), repr(ref), str(ref))
    _assert_clean(text, CANARY)
    assert "kind" in ref.to_dict()
    assert ref.to_dict()["scheme"] == "vault"
    assert "reference_digest" in ref.to_dict()


# ---------------------------------------------------------------------------
# Resolution backends
# ---------------------------------------------------------------------------


def test_vault_resolution_request_time_only() -> None:
    vault = MappingVaultCredentialSource({VAULT_KEY: CANARY})
    resolver = CredentialResolver(vault_source=vault)
    assert resolver.resolution_count == 0
    secret = resolver.resolve(f"vault:{VAULT_KEY}")
    assert isinstance(secret, ApiKeySecret)
    assert secret.reveal() == CANARY
    assert resolver.resolution_count == 1
    # Surfaces stay clean.
    text = _blob(
        secret,
        secret.to_dict(),
        repr(secret),
        str(secret),
        resolver.safe_config(),
        resolver.diagnostic_dict(f"vault:{VAULT_KEY}"),
    )
    _assert_clean(text, CANARY)
    assert secret.to_dict()["reference_id"] == VAULT_KEY


def test_env_resolution_uses_injected_environ() -> None:
    environ = {ENV_NAME: CANARY_ENV}
    resolver = CredentialResolver(
        env_source=EnvironmentCredentialSource(environ),
    )
    secret = resolver.resolve(f"env:{ENV_NAME}")
    assert secret.reveal() == CANARY_ENV
    _assert_clean(_blob(secret.to_dict(), resolver.safe_config()), CANARY_ENV)


def test_env_resolution_missing_raises_without_leak() -> None:
    resolver = CredentialResolver(
        env_source=EnvironmentCredentialSource({}),
    )
    with pytest.raises(CredentialResolutionError) as exc_info:
        resolver.resolve(f"env:{ENV_NAME}")
    err = exc_info.value
    assert err.code == "credential_resolution_failed"
    _assert_clean(_blob(err, err.to_dict(), str(err)), CANARY, CANARY_ENV)


def test_callable_backend_and_error_redaction() -> None:
    def boom(_name: str) -> str | None:
        raise RuntimeError(f"backend exploded with {CANARY}")

    resolver = CredentialResolver(
        vault_source=CallableCredentialSource(boom, label="test-backend"),
    )
    with pytest.raises(CredentialResolutionError) as exc_info:
        resolver.resolve(f"vault:{VAULT_KEY}")
    _assert_clean(str(exc_info.value), CANARY)
    assert "RuntimeError" in str(exc_info.value) or "failed" in str(exc_info.value).lower()


def test_resolve_header_for_request_construction() -> None:
    resolver = CredentialResolver.from_mapping({VAULT_KEY: CANARY})
    headers = resolver.resolve_header(f"vault:{VAULT_KEY}")
    assert headers[API_KEY_HEADER] == CANARY
    # Sanitized copy for logs is clean.
    safe = sanitize_headers(headers)
    assert safe[API_KEY_HEADER] == "<redacted>"
    _assert_clean(json.dumps(safe), CANARY)


def test_resolve_default_prefers_vault_then_env() -> None:
    resolver = CredentialResolver.from_mapping(
        {"preferred": CANARY},
        environ={ENV_NAME: CANARY_ENV},
    )
    secret = resolver.resolve_default(
        vault_keys=("preferred",),
        env_names=(ENV_NAME,),
        reference_id="odp-default",
    )
    assert secret.reveal() == CANARY
    assert secret.reference_id == "odp-default"

    resolver_env_only = CredentialResolver.from_mapping(
        {},
        environ={ENV_NAME: CANARY_ENV},
    )
    secret_env = resolver_env_only.resolve_default(env_names=(ENV_NAME,))
    assert secret_env.reveal() == CANARY_ENV


def test_resolve_default_missing_raises() -> None:
    resolver = CredentialResolver.from_mapping({}, environ={})
    with pytest.raises(CredentialResolutionError):
        resolver.resolve_default(env_names=("NO_SUCH_VAR",), vault_keys=("nope",))


def test_nested_reference_value_rejected() -> None:
    resolver = CredentialResolver.from_mapping({"k": "env:OTHER"})
    with pytest.raises(CredentialResolutionError):
        resolver.resolve("vault:k")


def test_api_key_secret_passthrough() -> None:
    existing = ApiKeySecret(CANARY, reference_id="pre-resolved")
    resolver = CredentialResolver.from_mapping({})
    out = resolver.resolve(existing)
    assert out is existing
    assert resolver.resolution_count == 1


# ---------------------------------------------------------------------------
# Redaction helpers and leak detectors
# ---------------------------------------------------------------------------


def test_redact_credential_diagnostics_strips_secret_keys() -> None:
    payload = {
        "api_key": CANARY,
        "authorization": f"Bearer {CANARY}",
        "nested": {"token": CANARY, "ok": True},
        "reference_id": "odp-api-key",
        "message": f"X-API-KEY: {CANARY}",
    }
    redacted = redact_credential_diagnostics(payload, secret=CANARY)
    text = json.dumps(redacted)
    _assert_clean(text, CANARY)
    assert redacted["reference_id"] == "odp-api-key"
    assert redacted["api_key"] == "<redacted>"
    assert contains_resolved_secret(payload, CANARY) is True
    assert contains_resolved_secret(redacted, CANARY) is False


def test_sanitize_secret_text_bounds_and_redacts() -> None:
    # Pattern redacts ``authorization: <token>`` as a single assignment.
    text = sanitize_secret_text(f"authorization: {CANARY}")
    assert CANARY not in text
    assert "<redacted>" in text
    # Also bound long inputs.
    long_text = sanitize_secret_text("x" * 600)
    assert len(long_text) <= 512


def test_schema_version_present() -> None:
    resolver = CredentialResolver.from_mapping({})
    assert resolver.safe_config()["schema_version"] == CREDENTIAL_RESOLVER_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# End-to-end: resolver + transport never log secrets
# ---------------------------------------------------------------------------


def test_transport_attaches_resolved_key_without_logging_it() -> None:
    opener = ScriptedOpener()
    opener.add(status=200, body={"ok": True})
    resolver = CredentialResolver.from_mapping({VAULT_KEY: CANARY})
    transport = BoundedHttpTransport(
        policy=HostAllowlistPolicy(
            allowed_hosts=frozenset({"api.uspto.gov"}),
            allowed_ports=frozenset({443}),
        ),
        credential_resolver=resolver,
        credential_ref=f"vault:{VAULT_KEY}",
        opener=opener,
    )
    response = transport.request(
        HttpRequest(method="GET", url="https://api.uspto.gov/api/v1/patent/applications/1")
    )
    assert response.status_code == 200
    # On the wire (opener) the key is present for the real request.
    sent = opener.requests[0]
    assert _request_header(sent, API_KEY_HEADER) == CANARY
    # Every durable/diagnostic surface is clean.
    surfaces = _blob(
        transport.safe_config(),
        transport.diagnostic_dict(
            last_request=HttpRequest(
                method="GET",
                url="https://api.uspto.gov/api/v1/patent/applications/1",
                headers={API_KEY_HEADER: CANARY},
            ),
            secret=CANARY,
        ),
        resolver.diagnostic_dict(f"vault:{VAULT_KEY}"),
        sanitize_headers({API_KEY_HEADER: CANARY}),
    )
    _assert_clean(surfaces, CANARY)
    assert not contains_secret_leak(surfaces, secret=CANARY)


def test_missing_resolver_with_ref_fails_closed() -> None:
    transport = BoundedHttpTransport(
        policy=HostAllowlistPolicy(
            allowed_hosts=frozenset({"api.uspto.gov"}),
            allowed_ports=frozenset({443}),
        ),
        credential_ref=f"vault:{VAULT_KEY}",
        # no resolver
        opener=ScriptedOpener(),
    )
    with pytest.raises(CredentialResolutionError):
        transport.request(
            HttpRequest(method="GET", url="https://api.uspto.gov/api/v1/patent/applications/1")
        )


def test_process_environ_isolation_for_injected_source() -> None:
    """Injected environ snapshot is used; live os.environ changes do not apply."""

    # Ensure the canary env name is not unexpectedly set from a prior test.
    os.environ.pop(ENV_NAME, None)
    frozen = {ENV_NAME: CANARY_ENV}
    resolver = CredentialResolver(
        env_source=EnvironmentCredentialSource(frozen),
    )
    # Mutating live environ after construction must not affect frozen source.
    os.environ[ENV_NAME] = "wrong-value-should-not-resolve"
    try:
        secret = resolver.resolve(f"env:{ENV_NAME}")
        assert secret.reveal() == CANARY_ENV
    finally:
        os.environ.pop(ENV_NAME, None)


def test_vault_put_rejects_invalid_keys() -> None:
    vault = MappingVaultCredentialSource()
    with pytest.raises(CredentialReferenceError):
        vault.put("bad key", CANARY)
    vault.put(VAULT_KEY, CANARY)
    assert vault.get(VAULT_KEY) == CANARY
    _assert_clean(repr(vault), CANARY)


def test_error_to_dict_is_serializable_and_clean() -> None:
    err = CredentialResolutionError(
        "credential not found",
        reference_id=VAULT_KEY,
    )
    payload: dict[str, Any] = err.to_dict()
    assert payload["code"] == "credential_resolution_failed"
    assert payload["reference_id"] == VAULT_KEY
    _assert_clean(json.dumps(payload), CANARY)
