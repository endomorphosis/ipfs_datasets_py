"""ODP client runtime bootstrap and durable matter wiring (PATLAW-124).

Constructs production or recorded Patent File Wrapper clients from **explicit
profiles**. Ordinary configured API/CLI paths no longer require a fixture
recipe: a production profile with a credential reference and optional bounded
transport is sufficient.

Key references are persisted in durable matter state so they remain stable
across CLI invocations. Secrets are never written to disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping

from ipfs_datasets_py.processors.domains.uspto.application_status_processor import (
    ApplicationStatusProcessor,
    InMemoryStatusSnapshotStore,
    StatusSnapshotStore,
)
from ipfs_datasets_py.processors.domains.uspto.durable_stores import (
    DURABLE_STORES_SCHEMA_VERSION,
    DurableMatterState,
    EncryptionMetadata,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    DEFAULT_ODP_BASE_URL,
    ApiKeySecret,
    CancellationToken,
    HttpTransport,
    ProviderConfigError,
    RatePolicy,
    RecordedHttpTransport,
    RetryPolicy,
    load_recorded_exchanges,
)
from ipfs_datasets_py.processors.domains.uspto.providers.credential_resolver import (
    CredentialReference,
    CredentialResolver,
)
from ipfs_datasets_py.processors.domains.uspto.providers.http_transport import (
    BoundedHttpTransport,
    BoundedTransportLimits,
    HostAllowlistPolicy,
)
from ipfs_datasets_py.processors.domains.uspto.providers.odp_contract_monitor import (
    OdpContractMonitor,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PATENT_FILE_WRAPPER_SCHEMA_VERSION,
    PatentFileWrapperClient,
    build_fixture_recipe,
    default_fixture_dir,
)
from ipfs_datasets_py.processors.domains.uspto.status_vocabulary import (
    STATUS_VOCABULARY_SCHEMA_VERSION,
    vocabulary_manifest,
)

RUNTIME_SCHEMA_VERSION: Final = "uspto.odp.runtime.v1"
RUNTIME_INTERFACE: Final = "OdpRuntimeBootstrap@1"


class RuntimeMode(str, Enum):
    """How the runtime obtains an HTTP transport."""

    PRODUCTION = "production"
    RECORDED = "recorded"
    INJECTED = "injected"


class RuntimeBootstrapError(ProviderConfigError):
    """Runtime profile is incomplete or inconsistent."""

    code = "runtime_bootstrap_error"


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    """Explicit configuration for constructing an ODP runtime.

    Production profiles require a credential **reference** (env/vault/ref) or a
    pre-resolved :class:`ApiKeySecret` / transport — never a fixture recipe.
    Recorded profiles may use a recipe path when tests need deterministic I/O.
    """

    mode: RuntimeMode | str = RuntimeMode.PRODUCTION
    credential_ref: str | CredentialReference | None = None
    api_key: ApiKeySecret | str | None = None
    base_url: str = DEFAULT_ODP_BASE_URL
    tenant_id: str = "default"
    store_root: str | Path | None = None
    recipe_path: str | Path | None = None
    fixture_dir: str | Path | None = None
    enable_contract_canary: bool = False
    canary_application_number: str = "16123456"
    key_id: str = "default"
    encryption_suite: str = "none"
    retry_policy: RetryPolicy | None = None
    rate_policy: RatePolicy | None = None
    cancellation: CancellationToken | None = None
    transport: HttpTransport | None = None
    allow_loopback: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mode = self.mode
        if not isinstance(mode, RuntimeMode):
            object.__setattr__(self, "mode", RuntimeMode(str(mode).strip().lower()))
        if self.extra and not isinstance(self.extra, Mapping):
            raise RuntimeBootstrapError("extra must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        cred = None
        if self.credential_ref is not None:
            if isinstance(self.credential_ref, CredentialReference):
                cred = self.credential_ref.to_dict()
            else:
                try:
                    cred = CredentialReference.parse(str(self.credential_ref)).to_dict()
                except Exception:  # noqa: BLE001 — diagnostic only
                    cred = {"reference_id": str(self.credential_ref), "kind": "opaque"}
        return {
            "allow_loopback": self.allow_loopback,
            "base_url": self.base_url,
            "canary_application_number": self.canary_application_number,
            "credential_ref": cred,
            "enable_contract_canary": self.enable_contract_canary,
            "encryption_suite": self.encryption_suite,
            "fixture_dir": None if self.fixture_dir is None else str(self.fixture_dir),
            "has_api_key": self.api_key is not None,
            "has_injected_transport": self.transport is not None,
            "key_id": self.key_id,
            "mode": self.mode.value if isinstance(self.mode, RuntimeMode) else str(self.mode),
            "recipe_path": None if self.recipe_path is None else str(self.recipe_path),
            "store_root": None if self.store_root is None else str(self.store_root),
            "tenant_id": self.tenant_id,
        }


@dataclass
class OdpRuntime:
    """Bootstrapped ODP clients, status processor, durable state, and canary."""

    profile: RuntimeProfile
    client: PatentFileWrapperClient
    durable_state: DurableMatterState | None
    status_processor: ApplicationStatusProcessor
    contract_monitor: OdpContractMonitor
    credential_reference: CredentialReference | None
    key_reference_id: str | None

    @property
    def schema_version(self) -> str:
        return RUNTIME_SCHEMA_VERSION

    def safe_config(self) -> dict[str, Any]:
        return {
            "client": self.client.safe_config(),
            "contract_monitor": self.contract_monitor.safe_config(),
            "credential_reference": None
            if self.credential_reference is None
            else self.credential_reference.to_dict(),
            "durable_state": None
            if self.durable_state is None
            else self.durable_state.safe_config(),
            "interface": RUNTIME_INTERFACE,
            "key_reference_id": self.key_reference_id,
            "profile": self.profile.to_dict(),
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "status_vocabulary": vocabulary_manifest(),
            "versions": {
                "durable_stores": DURABLE_STORES_SCHEMA_VERSION,
                "patent_file_wrapper": PATENT_FILE_WRAPPER_SCHEMA_VERSION,
                "runtime": RUNTIME_SCHEMA_VERSION,
                "status_vocabulary": STATUS_VOCABULARY_SCHEMA_VERSION,
            },
        }

    def reload_key_reference(self) -> dict[str, Any] | None:
        """Load the persisted key reference (stable across CLI invocations)."""

        if self.durable_state is None or self.key_reference_id is None:
            return None
        return self.durable_state.get_key_reference(self.key_reference_id)


def bootstrap_runtime(
    profile: RuntimeProfile | Mapping[str, Any],
    *,
    status_store: StatusSnapshotStore | None = None,
    credential_resolver: CredentialResolver | None = None,
    durable_state: DurableMatterState | None = None,
) -> OdpRuntime:
    """Construct a production-ready ODP runtime from an explicit profile.

    * **production** — ``BoundedHttpTransport`` + credential reference/API key;
      no fixture recipe required.
    * **recorded** — fixture recipe / recorded transport for deterministic tests.
    * **injected** — caller-supplied transport (fake server, custom opener).
    """

    if isinstance(profile, Mapping):
        profile = RuntimeProfile(**dict(profile))  # type: ignore[arg-type]
    if not isinstance(profile, RuntimeProfile):
        raise RuntimeBootstrapError("profile must be RuntimeProfile or mapping")

    mode = profile.mode if isinstance(profile.mode, RuntimeMode) else RuntimeMode(str(profile.mode))
    cred_ref: CredentialReference | None = None
    key_reference_id: str | None = None
    api_key = profile.api_key

    if profile.credential_ref is not None:
        cred_ref = (
            profile.credential_ref
            if isinstance(profile.credential_ref, CredentialReference)
            else CredentialReference.parse(str(profile.credential_ref))
        )
        key_reference_id = cred_ref.reference_id

    if mode is RuntimeMode.PRODUCTION:
        # Resolve credential reference for production even when a transport is
        # injected (ordinary API/CLI path — never requires a fixture recipe).
        if api_key is None and cred_ref is not None and credential_resolver is not None:
            try:
                api_key = credential_resolver.resolve(cred_ref)
            except Exception:
                api_key = None
        client = _build_production_client(
            profile,
            api_key=api_key,
            cred_ref=cred_ref,
            credential_resolver=credential_resolver,
        )
    elif mode is RuntimeMode.RECORDED:
        client = _build_recorded_client(profile, api_key=api_key)
    elif mode is RuntimeMode.INJECTED:
        if profile.transport is None:
            raise RuntimeBootstrapError(
                "injected mode requires profile.transport",
            )
        client = PatentFileWrapperClient(
            profile.transport,
            base_url=profile.base_url,
            api_key=api_key,
            retry_policy=profile.retry_policy,
            rate_policy=profile.rate_policy,
            cancellation=profile.cancellation,
        )
    else:
        raise RuntimeBootstrapError(f"unsupported runtime mode: {mode!r}")

    state = durable_state
    if state is None and profile.store_root is not None:
        state = DurableMatterState(
            profile.store_root,
            tenant_id=profile.tenant_id,
            encryption=EncryptionMetadata(
                tenant_id=profile.tenant_id,
                key_id=profile.key_id,
                suite=profile.encryption_suite,
                namespace=f"private://tenant/{profile.tenant_id}/key/{profile.key_id}",
            ),
        )

    if state is not None and cred_ref is not None and key_reference_id is not None:
        state.put_key_reference(
            reference_id=key_reference_id,
            reference=cred_ref.to_dict(),
        )

    store = status_store or InMemoryStatusSnapshotStore()
    processor = ApplicationStatusProcessor(client=client, store=store)
    monitor = OdpContractMonitor(
        client=client,
        enabled=bool(profile.enable_contract_canary),
        application_number=str(profile.canary_application_number),
    )
    return OdpRuntime(
        profile=profile,
        client=client,
        durable_state=state,
        status_processor=processor,
        contract_monitor=monitor,
        credential_reference=cred_ref,
        key_reference_id=key_reference_id,
    )


def bootstrap_production(
    *,
    credential_ref: str | CredentialReference,
    store_root: str | Path,
    tenant_id: str = "default",
    base_url: str = DEFAULT_ODP_BASE_URL,
    enable_contract_canary: bool = False,
    credential_resolver: CredentialResolver | None = None,
    **kwargs: Any,
) -> OdpRuntime:
    """Convenience: production runtime without any fixture recipe."""

    profile = RuntimeProfile(
        mode=RuntimeMode.PRODUCTION,
        credential_ref=credential_ref,
        store_root=store_root,
        tenant_id=tenant_id,
        base_url=base_url,
        enable_contract_canary=enable_contract_canary,
        **kwargs,
    )
    return bootstrap_runtime(profile, credential_resolver=credential_resolver)


def bootstrap_recorded(
    *,
    recipe: str | Path | Mapping[str, Any] | None = None,
    store_root: str | Path | None = None,
    tenant_id: str = "default",
    api_key: ApiKeySecret | str | None = "test-key-not-a-secret",
    **kwargs: Any,
) -> OdpRuntime:
    """Convenience: recorded-transport runtime for tests."""

    profile = RuntimeProfile(
        mode=RuntimeMode.RECORDED,
        recipe_path=None if isinstance(recipe, Mapping) else recipe,
        store_root=store_root,
        tenant_id=tenant_id,
        api_key=api_key,
        **kwargs,
    )
    if isinstance(recipe, Mapping):
        transport = RecordedHttpTransport(load_recorded_exchanges(dict(recipe)))
        profile = RuntimeProfile(
            mode=RuntimeMode.INJECTED,
            transport=transport,
            store_root=store_root,
            tenant_id=tenant_id,
            api_key=api_key,
            **{k: v for k, v in kwargs.items() if k != "transport"},
        )
    return bootstrap_runtime(profile)


def _build_production_client(
    profile: RuntimeProfile,
    *,
    api_key: ApiKeySecret | str | None,
    cred_ref: CredentialReference | None,
    credential_resolver: CredentialResolver | None,
) -> PatentFileWrapperClient:
    if profile.transport is not None:
        return PatentFileWrapperClient(
            profile.transport,
            base_url=profile.base_url,
            api_key=api_key,
            retry_policy=profile.retry_policy,
            rate_policy=profile.rate_policy,
            cancellation=profile.cancellation,
        )

    resolved = api_key
    resolver = credential_resolver
    if resolved is None and cred_ref is not None:
        resolver = resolver or CredentialResolver()
        try:
            resolved = resolver.resolve(cred_ref)
        except Exception:
            # Leave unresolved: BoundedHttpTransport may attach at request time
            # when a resolver + ref are provided on the transport.
            resolved = None

    if resolved is None and cred_ref is None and profile.credential_ref is None:
        raise RuntimeBootstrapError(
            "production mode requires credential_ref, api_key, or transport; "
            "fixture recipes are not required and must not be the only path"
        )

    if profile.allow_loopback:
        policy = HostAllowlistPolicy.for_loopback_testing()
    else:
        policy = HostAllowlistPolicy.odp_default()

    transport = BoundedHttpTransport(
        policy=policy,
        limits=BoundedTransportLimits(),
        credential_resolver=resolver,
        credential_ref=cred_ref if resolved is None else None,
        cancellation=profile.cancellation,
    )
    return PatentFileWrapperClient(
        transport,
        base_url=profile.base_url,
        api_key=resolved,
        retry_policy=profile.retry_policy,
        rate_policy=profile.rate_policy,
        cancellation=profile.cancellation,
    )


def _build_recorded_client(
    profile: RuntimeProfile,
    *,
    api_key: ApiKeySecret | str | None,
) -> PatentFileWrapperClient:
    if profile.transport is not None:
        return PatentFileWrapperClient(
            profile.transport,
            base_url=profile.base_url,
            api_key=api_key,
            retry_policy=profile.retry_policy,
            rate_policy=profile.rate_policy,
            cancellation=profile.cancellation,
        )
    if profile.recipe_path is not None:
        return PatentFileWrapperClient.from_recorded_recipe(
            profile.recipe_path,
            api_key=api_key or "test-key-not-a-secret",
            base_url=profile.base_url,
            retry_policy=profile.retry_policy,
            rate_policy=profile.rate_policy,
            cancellation=profile.cancellation,
        )
    fixture_dir = profile.fixture_dir or default_fixture_dir()
    return PatentFileWrapperClient.from_fixture_dir(
        fixture_dir,
        api_key=api_key or "test-key-not-a-secret",
        base_url=profile.base_url,
        retry_policy=profile.retry_policy,
        rate_policy=profile.rate_policy,
        cancellation=profile.cancellation,
    )


# AST / plan aliases
ODPClientBootstrap = bootstrap_runtime
ApplicationStatusVocabulary = vocabulary_manifest


__all__ = [
    "RUNTIME_INTERFACE",
    "RUNTIME_SCHEMA_VERSION",
    "ApplicationStatusVocabulary",
    "ODPClientBootstrap",
    "OdpRuntime",
    "RuntimeBootstrapError",
    "RuntimeMode",
    "RuntimeProfile",
    "bootstrap_production",
    "bootstrap_recorded",
    "bootstrap_runtime",
    "build_fixture_recipe",
]
