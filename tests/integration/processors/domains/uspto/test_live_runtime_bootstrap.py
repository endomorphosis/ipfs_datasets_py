"""Integration tests: ODP runtime bootstrap without fixture recipes (PATLAW-124).

Ordinary configured production profiles construct clients from credential
references and bounded transport. Recorded/injected modes remain available for
deterministic CI. Key references stay stable across reopened runtimes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ApiKeySecret,
    ProviderOutcomeKind,
    ProviderResult,
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.providers.credential_resolver import (
    CredentialReference,
    CredentialResolver,
)
from ipfs_datasets_py.processors.domains.uspto.providers.http_transport import (
    BoundedHttpTransport,
    FakeOdpHttpServer,
    HostAllowlistPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.providers.odp_contract_monitor import (
    ContractCanaryKind,
    OdpContractMonitor,
    canary_distinguishes_auth_from_quota,
    classify_provider_result,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PatentFileWrapperClient,
    build_fixture_recipe,
)
from ipfs_datasets_py.processors.domains.uspto.runtime import (
    RUNTIME_SCHEMA_VERSION,
    RuntimeMode,
    RuntimeProfile,
    bootstrap_production,
    bootstrap_recorded,
    bootstrap_runtime,
)


APP_OK = "16123456"


def _app_body(status_code: int = 150) -> dict:
    return {
        "count": 1,
        "patentFileWrapperDataBag": [
            {
                "applicationNumberText": APP_OK,
                "applicationMetaData": {
                    "applicationStatusCode": status_code,
                    "applicationStatusDescriptionText": "Docketed New Case",
                },
                "lastIngestionDateTime": "2026-08-01T12:00:00",
            }
        ],
        "requestIdentifier": "bootstrap-test",
    }


def test_production_profile_does_not_require_fixture_recipe(tmp_path: Path) -> None:
    """Ordinary production path: credential ref + store root, no recipe."""

    store_root = tmp_path / "matter"
    resolver = CredentialResolver.from_mapping(
        vault={"odp-prod-key": "synthetic-bootstrap-key-not-live"}
    )
    # Inject a transport so no live network is required while still using
    # production mode (recipe_path left unset).
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP_OK}",
                status=200,
                body=_app_body(),
            )
        ]
    )
    profile = RuntimeProfile(
        mode=RuntimeMode.PRODUCTION,
        credential_ref="vault:odp-prod-key",
        store_root=store_root,
        tenant_id="tenant-a",
        transport=transport,
        api_key=None,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    runtime = bootstrap_runtime(profile, credential_resolver=resolver)

    assert runtime.schema_version == RUNTIME_SCHEMA_VERSION
    assert runtime.profile.recipe_path is None
    assert runtime.client is not None
    assert runtime.durable_state is not None
    assert runtime.durable_state.tenant_id == "tenant-a"
    # Production safe_config must not require fixture recipe keys.
    cfg = runtime.safe_config()
    assert cfg["profile"]["mode"] == "production"
    assert cfg["profile"]["recipe_path"] is None
    assert cfg["key_reference_id"] == "odp-prod-key"

    result = runtime.client.get_application_data(APP_OK)
    assert result.ok
    assert result.kind is ProviderOutcomeKind.SUCCESS


def test_bootstrap_production_helper(tmp_path: Path) -> None:
    transport = RecordedHttpTransport(
        [
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP_OK}/meta-data",
                status=200,
                body=_app_body(),
            )
        ]
    )
    resolver = CredentialResolver.from_mapping(
        environ={"USPTO_ODP_API_KEY": "env-bootstrap-key"}
    )
    runtime = bootstrap_production(
        credential_ref="env:USPTO_ODP_API_KEY",
        store_root=tmp_path / "s",
        tenant_id="t1",
        transport=transport,
        credential_resolver=resolver,
        enable_contract_canary=True,
        canary_application_number=APP_OK,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    assert runtime.contract_monitor.enabled is True
    canary = runtime.contract_monitor.probe()
    assert canary.kind is ContractCanaryKind.SUCCESS
    assert canary.opt_in is True


def test_key_reference_stable_across_cli_invocations(tmp_path: Path) -> None:
    store_root = tmp_path / "keys"
    ref = "vault:stable-odp-ref"
    resolver = CredentialResolver.from_mapping(vault={"stable-odp-ref": "k" * 16})
    transport = RecordedHttpTransport([])

    first = bootstrap_runtime(
        RuntimeProfile(
            mode=RuntimeMode.PRODUCTION,
            credential_ref=ref,
            store_root=store_root,
            tenant_id="shared",
            transport=transport,
            retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        ),
        credential_resolver=resolver,
    )
    second = bootstrap_runtime(
        RuntimeProfile(
            mode=RuntimeMode.PRODUCTION,
            credential_ref=ref,
            store_root=store_root,
            tenant_id="shared",
            transport=transport,
            retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        ),
        credential_resolver=resolver,
    )
    assert first.key_reference_id == second.key_reference_id == "stable-odp-ref"
    loaded_a = first.reload_key_reference()
    loaded_b = second.reload_key_reference()
    assert loaded_a is not None and loaded_b is not None
    assert loaded_a["reference_id"] == loaded_b["reference_id"] == "stable-odp-ref"
    assert "secret" not in json.dumps(loaded_a).lower()
    assert loaded_a.get("scheme") == "vault"


def test_recorded_bootstrap_still_available(tmp_path: Path) -> None:
    recipe = build_fixture_recipe(
        [
            {
                "method": "GET",
                "path": f"/api/v1/patent/applications/{APP_OK}",
                "status": 200,
                "body": _app_body(),
            }
        ]
    )
    runtime = bootstrap_recorded(
        recipe=recipe,
        store_root=tmp_path / "rec",
        tenant_id="rec-tenant",
    )
    assert runtime.client.get_application_data(APP_OK).ok


def test_canary_distinguishes_401_403_from_quota_and_empty() -> None:
    auth = classify_provider_result(
        ProviderResult(
            kind=ProviderOutcomeKind.UNAUTHORIZED,
            status_code=401,
            receipt=None,
            message="unauthorized",
        )
    )
    profile = classify_provider_result(
        ProviderResult(
            kind=ProviderOutcomeKind.FORBIDDEN,
            status_code=403,
            receipt=None,
            message="profile required",
        )
    )
    quota = classify_provider_result(
        ProviderResult(
            kind=ProviderOutcomeKind.RATE_LIMITED,
            status_code=429,
            receipt=None,
            message="too many requests",
        )
    )
    outage = classify_provider_result(
        ProviderResult(
            kind=ProviderOutcomeKind.UPSTREAM_ERROR,
            status_code=503,
            receipt=None,
            message="unavailable",
        )
    )
    empty = classify_provider_result(
        ProviderResult(
            kind=ProviderOutcomeKind.NOT_FOUND,
            status_code=404,
            receipt=None,
            message="not found",
        )
    )

    assert auth.kind is ContractCanaryKind.AUTHENTICATION_FAILURE
    assert profile.kind is ContractCanaryKind.PROFILE_OR_AUTHORIZATION_DRIFT
    assert auth.is_auth_drift and profile.is_auth_drift
    assert quota.kind is ContractCanaryKind.QUOTA_OR_RATE_LIMIT
    assert outage.kind is ContractCanaryKind.UPSTREAM_OUTAGE
    assert empty.kind is ContractCanaryKind.EMPTY_OR_NOT_FOUND
    assert empty.is_empty_result
    assert canary_distinguishes_auth_from_quota(auth, quota)
    assert canary_distinguishes_auth_from_quota(profile, outage)
    assert not auth.is_quota_or_outage
    assert not quota.is_auth_drift


def test_canary_disabled_by_default_is_opt_in() -> None:
    client = PatentFileWrapperClient(
        RecordedHttpTransport([]),
        api_key="x",
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )
    monitor = OdpContractMonitor(client=client, enabled=False)
    result = monitor.probe()
    assert result.opt_in is False
    assert result.kind is ContractCanaryKind.UNKNOWN
    assert "disabled" in result.message.lower()


def test_fake_server_production_transport_path(tmp_path: Path) -> None:
    """Bounded live-shaped transport against loopback (no external network)."""

    with FakeOdpHttpServer() as server:
        server.set_route(
            f"/api/v1/patent/applications/{APP_OK}/meta-data",
            status=200,
            body=_app_body(),
        )
        policy = HostAllowlistPolicy.for_loopback_testing(port=server.port)
        transport = BoundedHttpTransport(
            policy=policy,
            credential_ref=ApiKeySecret("loopback-key", reference_id="loop-ref"),
        )
        # Point client at loopback base.
        client = PatentFileWrapperClient(
            transport,
            base_url=server.base_url,
            api_key=ApiKeySecret("loopback-key", reference_id="loop-ref"),
            retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        )
        runtime = bootstrap_runtime(
            RuntimeProfile(
                mode=RuntimeMode.INJECTED,
                transport=transport,
                store_root=tmp_path / "loop",
                tenant_id="loop-tenant",
                api_key=ApiKeySecret("loopback-key", reference_id="loop-ref"),
                base_url=server.base_url,
                enable_contract_canary=True,
                canary_application_number=APP_OK,
            )
        )
        # Rebind monitor to client with correct base_url.
        runtime.contract_monitor = OdpContractMonitor(
            client=client, enabled=True, application_number=APP_OK
        )
        canary = runtime.contract_monitor.probe()
        assert canary.kind is ContractCanaryKind.SUCCESS
        assert canary.status_code == 200


def test_credential_reference_parse_stable() -> None:
    a = CredentialReference.parse("env:USPTO_ODP_API_KEY")
    b = CredentialReference.parse("env:USPTO_ODP_API_KEY")
    assert a.reference_id == b.reference_id
    assert a.to_dict() == b.to_dict()
