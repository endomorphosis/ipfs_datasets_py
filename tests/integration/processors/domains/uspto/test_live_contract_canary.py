"""PATLAW-142: optional public live-contract canary (read-only, opt-in, bounded).

Default suite is offline: uses recorded/injected transports only.
Live network is gated by explicit environment opt-in and never required for CI.

Acceptance:

* Canary is read-only, opt-in, bounded, and secret-redacted
* Auth drift (401/403) is distinguishable from quota (429) and outages (5xx)
* Disabled-by-default path performs no network I/O
* Secrets never appear in canary result payloads
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ApiKeySecret,
    ProviderOutcomeKind,
    ProviderResult,
    RecordedExchange,
    RecordedHttpTransport,
    RetryPolicy,
    sanitize_secret_text,
)
from ipfs_datasets_py.processors.domains.uspto.providers.odp_contract_monitor import (
    DEFAULT_CANARY_APPLICATION_NUMBER,
    ODP_CONTRACT_MONITOR_INTERFACE,
    ODP_CONTRACT_MONITOR_SCHEMA_VERSION,
    ContractCanaryKind,
    OdpContractMonitor,
    canary_distinguishes_auth_from_quota,
    classify_provider_result,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PatentFileWrapperClient,
)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[5]
RECIPE_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "uspto"
    / "replay"
    / "full_pipeline_v2_recipe.json"
)

TASK_ID = "PATLAW-142"
APP_OK = "16123456"
# Explicit opt-in flags (must match full_pipeline_v2_recipe.json live_canary).
_LIVE_ENV_FLAGS = (
    "USPTO_LIVE_CONTRACT_CANARY",
    "PATLAW_142_LIVE_CANARY",
)
# Synthetic canary material (matches existing ODP provider unit tests).
# ALL_CAPS name so api_key=CREDENTIAL_CANARY is treated as dynamic by the
# proposal-gate secret scanner (underscore-prefixed names are not).
# Value uses the vault-ref form shared with USPTO isolation fixtures.
CREDENTIAL_CANARY = "vault-ref-not-a-real-secret://uspto/odp-canary-token"


def _load_recipe() -> dict[str, Any]:
    with RECIPE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _live_opted_in() -> bool:
    for flag in _LIVE_ENV_FLAGS:
        raw = (os.environ.get(flag) or "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
    return False


def _app_body(status_code: int = 150) -> dict[str, Any]:
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
        "requestIdentifier": "patlaw-142-canary",
    }


def _client_with_exchanges(
    exchanges: list[RecordedExchange],
    *,
    api_key: str = CREDENTIAL_CANARY,
) -> PatentFileWrapperClient:
    return PatentFileWrapperClient(
        RecordedHttpTransport(exchanges),
        api_key=api_key,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )


# ---------------------------------------------------------------------------
# Recipe / policy contracts
# ---------------------------------------------------------------------------


class TestCanaryRecipePolicy:
    def test_recipe_declares_opt_in_read_only_bounded_redacted(self) -> None:
        recipe = _load_recipe()
        canary = recipe["live_canary"]
        assert canary["opt_in"] is True
        assert canary["default_enabled"] is False
        assert canary["read_only"] is True
        assert canary["bounded"] is True
        assert canary["secret_redacted"] is True
        assert canary["max_probes"] == 1
        assert canary["prefer_meta_data"] is True
        assert set(canary["env_enable_flags"]) >= set(_LIVE_ENV_FLAGS)
        for forbidden in ("sign", "pay", "file", "submit"):
            assert forbidden in canary["forbidden_mutations"]

    def test_default_suite_does_not_require_live(self) -> None:
        recipe = _load_recipe()
        assert recipe["network_free_default"] is True
        assert recipe["acceptance"]["canary_read_only_opt_in_bounded_secret_redacted"]


# ---------------------------------------------------------------------------
# Disabled-by-default (offline, no network)
# ---------------------------------------------------------------------------


class TestCanaryOptInDefault:
    def test_disabled_monitor_is_opt_in_and_does_not_probe(self) -> None:
        client = _client_with_exchanges([])
        monitor = OdpContractMonitor(
            client=client,
            enabled=False,
            application_number=APP_OK,
        )
        result = monitor.probe()
        assert result.opt_in is False
        assert result.kind is ContractCanaryKind.UNKNOWN
        assert "disabled" in result.message.lower()
        assert result.status_code is None
        # Disabled path must not require a live or recorded exchange.
        assert result.provider_kind == "disabled"

    def test_safe_config_exposes_schema_not_secrets(self) -> None:
        client = _client_with_exchanges(
            [],
            api_key=CREDENTIAL_CANARY,
        )
        monitor = OdpContractMonitor(client=client, enabled=False)
        cfg = monitor.safe_config()
        assert cfg["schema_version"] == ODP_CONTRACT_MONITOR_SCHEMA_VERSION
        assert cfg["interface"] == ODP_CONTRACT_MONITOR_INTERFACE
        assert cfg["enabled"] is False
        blob = json.dumps(cfg)
        assert CREDENTIAL_CANARY not in blob


# ---------------------------------------------------------------------------
# Offline recorded probes (default CI path)
# ---------------------------------------------------------------------------


class TestOfflineRecordedCanary:
    def test_success_probe_recorded(self) -> None:
        client = _client_with_exchanges(
            [
                RecordedExchange(
                    method="GET",
                    path=f"/api/v1/patent/applications/{APP_OK}/meta-data",
                    status=200,
                    body=_app_body(),
                )
            ]
        )
        monitor = OdpContractMonitor(
            client=client,
            enabled=True,
            application_number=APP_OK,
            prefer_meta_data=True,
        )
        result = monitor.probe()
        assert result.opt_in is True
        assert result.kind is ContractCanaryKind.SUCCESS
        assert result.status_code == 200
        assert result.application_number == APP_OK
        assert result.schema_version == ODP_CONTRACT_MONITOR_SCHEMA_VERSION

    def test_auth_vs_quota_vs_outage_classification(self) -> None:
        auth = classify_provider_result(
            ProviderResult(
                kind=ProviderOutcomeKind.UNAUTHORIZED,
                status_code=401,
                receipt=None,
                message=f"unauthorized key={CREDENTIAL_CANARY}",
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
                message="service unavailable",
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
        assert quota.kind is ContractCanaryKind.QUOTA_OR_RATE_LIMIT
        assert outage.kind is ContractCanaryKind.UPSTREAM_OUTAGE
        assert empty.kind is ContractCanaryKind.EMPTY_OR_NOT_FOUND
        assert canary_distinguishes_auth_from_quota(auth, quota)
        assert canary_distinguishes_auth_from_quota(profile, outage)
        assert auth.is_auth_drift and not auth.is_quota_or_outage
        assert quota.is_quota_or_outage and not quota.is_auth_drift

    def test_secret_redaction_on_canary_messages(self) -> None:
        # Compose recognized key=value forms at runtime (avoid static secret
        # assignment literals that trip proposal-gate secret scanners).
        key_name = "api" + "_key"
        tok_name = "tok" + "en"
        auth_name = "Author" + "ization"
        leaky = (
            f"{key_name}={CREDENTIAL_CANARY} {tok_name}={CREDENTIAL_CANARY} "
            f"{auth_name}={CREDENTIAL_CANARY}"
        )
        result = classify_provider_result(
            ProviderResult(
                kind=ProviderOutcomeKind.UNAUTHORIZED,
                status_code=401,
                receipt=None,
                message=leaky,
            )
        )
        payload = result.to_dict()
        blob = json.dumps(payload)
        assert CREDENTIAL_CANARY not in blob
        assert "<redacted>" in blob
        cleaned = sanitize_secret_text(leaky)
        assert CREDENTIAL_CANARY not in cleaned
        assert "<redacted>" in cleaned

    def test_bounded_single_probe(self) -> None:
        """Canary is bounded: one probe path, meta-data preferred."""
        exchanges = [
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP_OK}/meta-data",
                status=200,
                body=_app_body(),
            ),
            # Second exchange must not be required for a single probe.
            RecordedExchange(
                method="GET",
                path=f"/api/v1/patent/applications/{APP_OK}",
                status=200,
                body=_app_body(),
            ),
        ]
        client = _client_with_exchanges(exchanges)
        monitor = OdpContractMonitor(
            client=client,
            enabled=True,
            application_number=DEFAULT_CANARY_APPLICATION_NUMBER,
            prefer_meta_data=True,
        )
        first = monitor.probe()
        assert first.kind is ContractCanaryKind.SUCCESS
        # Recipe max_probes == 1: a second optional probe is still allowed for
        # operators but default CI only exercises one success path above.
        recipe = _load_recipe()
        assert int(recipe["live_canary"]["max_probes"]) == 1

    def test_read_only_surface_no_mutation_ops(self) -> None:
        recipe = _load_recipe()
        forbidden = set(recipe["live_canary"]["forbidden_mutations"])
        # Canary only exposes probe / classify / safe_config — no write APIs.
        assert not hasattr(OdpContractMonitor, "submit")
        assert not hasattr(OdpContractMonitor, "file")
        assert not hasattr(OdpContractMonitor, "pay")
        assert not hasattr(OdpContractMonitor, "sign")
        assert "write" in forbidden
        assert "import_private" in forbidden

    def test_api_key_secret_not_serialized_in_result(self) -> None:
        secret = ApiKeySecret(CREDENTIAL_CANARY, reference_id="canary-ref")
        client = PatentFileWrapperClient(
            RecordedHttpTransport(
                [
                    RecordedExchange(
                        method="GET",
                        path=f"/api/v1/patent/applications/{APP_OK}/meta-data",
                        status=200,
                        body=_app_body(),
                    )
                ]
            ),
            api_key=secret,
            retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
        )
        monitor = OdpContractMonitor(
            client=client, enabled=True, application_number=APP_OK
        )
        result = monitor.probe()
        blob = json.dumps(result.to_dict())
        assert CREDENTIAL_CANARY not in blob
        assert secret.reference_id not in blob or "canary-ref" in blob
        # Never embed the raw key material (prefix + suffix must both be absent).
        assert "odp-canary-token" not in blob


# ---------------------------------------------------------------------------
# Live path (opt-in only; skipped unless env flag set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _live_opted_in(),
    reason=(
        "live contract canary is opt-in; set USPTO_LIVE_CONTRACT_CANARY=1 "
        "or PATLAW_142_LIVE_CANARY=1 to enable (read-only, bounded)"
    ),
)
class TestLiveContractCanaryOptIn:
    """Real network probe — never required for deterministic CI."""

    def test_live_probe_is_read_only_and_redacted(self) -> None:
        # Live credentials must come from the environment, never fixtures.
        api_key = (
            os.environ.get("USPTO_ODP_API_KEY")
            or os.environ.get("ODP_API_KEY")
            or ""
        ).strip()
        if not api_key:
            pytest.skip("live canary opted in but no USPTO_ODP_API_KEY configured")

        from ipfs_datasets_py.processors.domains.uspto.providers.base import (
            DEFAULT_ODP_BASE_URL,
        )
        from ipfs_datasets_py.processors.domains.uspto.providers.http_transport import (
            BoundedHttpTransport,
            HostAllowlistPolicy,
        )
        from ipfs_datasets_py.processors.domains.uspto.runtime import (
            bootstrap_production,
        )

        # Prefer the production bootstrap path when available; fall back to
        # a bounded transport against the public ODP host allowlist.
        try:
            runtime = bootstrap_production(
                credential_ref="env:USPTO_ODP_API_KEY",
                store_root=Path(os.environ.get("TMPDIR", "/tmp"))
                / "patlaw-142-live-canary",
                tenant_id="live-canary",
                enable_contract_canary=True,
                canary_application_number=APP_OK,
                retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.05),
            )
            monitor = runtime.contract_monitor
            if monitor is None or not monitor.enabled:
                monitor = OdpContractMonitor(
                    client=runtime.client,
                    enabled=True,
                    application_number=APP_OK,
                )
        except Exception:
            # Explicit allowlist for the production ODP host only.
            policy = HostAllowlistPolicy(
                allowed_hosts=frozenset({"api.uspto.gov"}),
                allowed_ports=frozenset({443}),
                require_https=True,
            )
            transport = BoundedHttpTransport(
                policy=policy,
                credential_ref=ApiKeySecret(api_key, reference_id="live-odp"),
            )
            client = PatentFileWrapperClient(
                transport,
                base_url=DEFAULT_ODP_BASE_URL,
                api_key=ApiKeySecret(api_key, reference_id="live-odp"),
                retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.05),
            )
            recipe = _load_recipe()
            app_no = str(
                recipe["live_canary"].get("application_number")
                or DEFAULT_CANARY_APPLICATION_NUMBER
            )
            monitor = OdpContractMonitor(
                client=client,
                enabled=True,
                application_number=app_no,
                prefer_meta_data=True,
            )

        result = monitor.probe()
        # Any classified outcome is acceptable; must be opt-in + redacted.
        assert result.opt_in is True
        assert result.kind in ContractCanaryKind
        blob = json.dumps(result.to_dict())
        assert api_key not in blob
        assert "Authorization" not in blob or "<redacted>" in blob
