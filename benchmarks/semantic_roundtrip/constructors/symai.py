"""Canonical SyMAI constructor over the frozen Leanstral service.

SyMAI is an orchestration arm, not a second model arm.  This module therefore
uses the same endpoint, model, decoding settings, limits, and stateless cache
policy as the direct Leanstral constructor.  The only experimental difference
is the declared SyMAI router path and its strict route receipt.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final, Protocol

from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    CONSTRUCTOR_MAX_TOKENS,
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LEANSTRAL_TIMEOUT_SECONDS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    LeanstralMalformedResponseError,
    LeanstralRequestError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
    _constructor_prompt,
    _server_schema,
    _strict_json_object,
    canonical_ir_schema,
)
from benchmarks.semantic_roundtrip_capabilities import (
    LEANSTRAL_BACKEND,
    LEANSTRAL_CAPACITY,
    LEANSTRAL_PROVIDER,
    SYMAI_MODEL_ALIAS,
    SYMAI_PROVIDER,
    SYMAI_VERSION,
)


SYMAI_CANONICAL_CONSTRUCTOR_INTERFACE: Final = "SyMAICanonicalConstructor@1"
SYMAI_PROVIDER_ID: Final = "symai-leanstral-route"
SYMAI_ROUTE: Final = "symai_router"
SYMAI_ORCHESTRATOR: Final = "symbolicai"

# These settings intentionally mirror LeanstralClient.complete_json.  Retry
# and cache are held at the direct arm's one-stateless-exchange behavior.
SYMAI_TEMPERATURE: Final = 0
SYMAI_SEED: Final = 0
SYMAI_STOP: Final = ("<|im_end|>",)
SYMAI_MAX_RETRIES: Final = 0
SYMAI_CACHE_ENABLED: Final = False

_CONSTRUCTOR_SYSTEM: Final = (
    "You are a deterministic legal semantic parser. Return one compact JSON "
    "object matching the supplied schema. Never explain, add keys, repeat a "
    "rule, or claim that generated logic is proved."
)

_ROUTE_KEYS: Final = frozenset(
    {
        "resolved_provider_name",
        "resolved_provider",
        "resolved_model_name",
        "resolved_model",
        "service_endpoint",
        "resolved_endpoint",
        "routing_backend",
        "resolved_backend",
        "attempts",
        "retries",
        "cache",
        "cache_enabled",
        "cache_hit",
        "provider",
        "model",
        "backend",
        "temperature",
        "seed",
        "max_tokens",
        "stop",
        "timeout_seconds",
        "cache_prompt",
        "independent_model",
    }
)


class SyMAIClientError(RuntimeError):
    """Base class for SyMAI orchestration contract failures."""


class SyMAIRouteError(LeanstralUnavailableError, SyMAIClientError):
    """SyMAI did not resolve to the frozen inner Leanstral service."""


class SyMAIMalformedResponseError(
    LeanstralMalformedResponseError, SyMAIClientError
):
    """SyMAI returned an invalid envelope, route receipt, or JSON value."""


@dataclass(frozen=True, slots=True)
class SyMAIGenerationSettings:
    """The model-facing envelope shared with direct Leanstral."""

    endpoint: str
    model: str
    temperature: int
    seed: int
    max_tokens: int
    stop: tuple[str, ...]
    timeout_seconds: float
    cache_prompt: bool

    @classmethod
    def for_role(cls, max_tokens: int) -> "SyMAIGenerationSettings":
        return cls(
            endpoint=LEANSTRAL_ENDPOINT,
            model=LEANSTRAL_MODEL,
            temperature=SYMAI_TEMPERATURE,
            seed=SYMAI_SEED,
            max_tokens=max_tokens,
            stop=SYMAI_STOP,
            timeout_seconds=LEANSTRAL_TIMEOUT_SECONDS,
            cache_prompt=False,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "model": self.model,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
            "stop": list(self.stop),
            "timeout_seconds": self.timeout_seconds,
            "cache_prompt": self.cache_prompt,
        }


@dataclass(frozen=True, slots=True)
class SyMAIRouteReceipt:
    """Bounded evidence that only SyMAI orchestration changed."""

    role: str
    route: str
    orchestrator: str
    orchestrator_version: str
    router_provider: str
    model_alias: str
    resolved_provider: str
    resolved_endpoint: str
    resolved_model: str
    resolved_backend: str
    shared_capacity: int
    settings: SyMAIGenerationSettings
    attempts: int
    retries: int
    retry_policy: str
    cache_enabled: bool
    cache_hit: bool
    independent_model_evidence: bool
    comparison_scope: str
    canonical_contract_validated: bool = False
    ranking_eligible: bool = False
    ranking_exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "routing": {
                "route": self.route,
                "orchestrator": self.orchestrator,
                "orchestrator_version": self.orchestrator_version,
                "router_provider": self.router_provider,
                "model_alias": self.model_alias,
                "resolved_provider": self.resolved_provider,
                "resolved_endpoint": self.resolved_endpoint,
                "resolved_model": self.resolved_model,
                "resolved_backend": self.resolved_backend,
                "shared_capacity": self.shared_capacity,
            },
            "model_settings": self.settings.to_dict(),
            "retry": {
                "policy": self.retry_policy,
                "attempts": self.attempts,
                "retries": self.retries,
            },
            "cache": {
                "enabled": self.cache_enabled,
                "hit": self.cache_hit,
            },
            "attribution": {
                "independent_model_evidence": self.independent_model_evidence,
                "comparison_scope": self.comparison_scope,
            },
            "canonical_contract_validated": self.canonical_contract_validated,
            "ranking_eligible": self.ranking_eligible,
            "ranking_exclusion_reason": self.ranking_exclusion_reason,
        }


@dataclass(frozen=True, slots=True)
class SyMAICompletion:
    """One strict JSON candidate and its bounded router trace."""

    value: Mapping[str, object]
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.value, Mapping):
            raise SyMAIMalformedResponseError(
                "SyMAI completion value must be an object"
            )
        if not isinstance(self.metadata, Mapping):
            raise SyMAIMalformedResponseError(
                "SyMAI completion metadata must be an object"
            )
        object.__setattr__(self, "value", MappingProxyType(dict(self.value)))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(
                {
                    str(key): item
                    for key, item in self.metadata.items()
                    if str(key) in _ROUTE_KEYS
                }
            ),
        )


SyMAIOrchestrationReceipt = SyMAIRouteReceipt


class SyMAICompletionClient(Protocol):
    """Narrow, injectable SyMAI route used by both canonical adapters."""

    endpoint: str
    model: str

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> SyMAICompletion:
        """Return strict JSON together with the effective route trace."""


SyMAIInvoker = Callable[..., object]


def _metadata_string(
    metadata: Mapping[str, object],
    *keys: str,
) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metadata_bool(
    metadata: Mapping[str, object],
    key: str,
    default: bool,
) -> bool:
    value = metadata.get(key, default)
    if type(value) is not bool:
        raise SyMAIMalformedResponseError(f"SyMAI {key} must be a boolean")
    return value


def _metadata_nonnegative_int(
    metadata: Mapping[str, object],
    key: str,
    default: int,
) -> int:
    value = metadata.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SyMAIMalformedResponseError(
            f"SyMAI {key} must be a nonnegative integer"
        )
    return value


def _route_receipt(
    metadata: Mapping[str, object],
    *,
    role: str,
    max_tokens: int,
) -> SyMAIRouteReceipt:
    provider = _metadata_string(
        metadata, "resolved_provider_name", "resolved_provider"
    )
    endpoint = _metadata_string(
        metadata, "service_endpoint", "resolved_endpoint"
    )
    model = _metadata_string(
        metadata, "resolved_model_name", "resolved_model"
    )
    backend = _metadata_string(
        metadata, "routing_backend", "resolved_backend"
    )
    expected = {
        "resolved provider": (provider, LEANSTRAL_PROVIDER),
        "endpoint": (endpoint, LEANSTRAL_ENDPOINT),
        "model": (model, LEANSTRAL_MODEL),
        "backend": (backend, LEANSTRAL_BACKEND),
    }
    missing = [name for name, (actual, _) in expected.items() if actual is None]
    if missing:
        raise SyMAIRouteError(
            "SyMAI route receipt omitted " + ", ".join(missing)
        )
    drifted = [
        name
        for name, (actual, frozen) in expected.items()
        if actual != frozen
    ]
    if drifted:
        raise SyMAIRouteError(
            "SyMAI route drifted from direct Leanstral: "
            + ", ".join(drifted)
        )

    settings = SyMAIGenerationSettings.for_role(max_tokens)
    effective_settings: tuple[tuple[str, object, object], ...] = (
        ("temperature", metadata.get("temperature"), settings.temperature),
        ("seed", metadata.get("seed"), settings.seed),
        ("max_tokens", metadata.get("max_tokens"), settings.max_tokens),
        (
            "timeout_seconds",
            metadata.get("timeout_seconds"),
            settings.timeout_seconds,
        ),
        ("cache_prompt", metadata.get("cache_prompt"), settings.cache_prompt),
    )
    setting_drift = [
        name
        for name, actual, frozen in effective_settings
        if actual is not None
        and (
            isinstance(actual, bool) != isinstance(frozen, bool)
            or actual != frozen
        )
    ]
    raw_stop = metadata.get("stop")
    if raw_stop is not None and (
        not isinstance(raw_stop, Sequence)
        or isinstance(raw_stop, (str, bytes, bytearray))
        or tuple(raw_stop) != settings.stop
    ):
        setting_drift.append("stop")
    independent_model = _metadata_bool(
        metadata, "independent_model", False
    )
    if independent_model:
        setting_drift.append("independent_model")
    if setting_drift:
        raise SyMAIRouteError(
            "SyMAI model settings drifted from direct Leanstral: "
            + ", ".join(setting_drift)
        )

    attempts = _metadata_nonnegative_int(metadata, "attempts", 1)
    retries = _metadata_nonnegative_int(metadata, "retries", 0)
    cache_enabled = _metadata_bool(
        metadata, "cache_enabled", SYMAI_CACHE_ENABLED
    )
    cache_hit = _metadata_bool(metadata, "cache_hit", False)
    cache_value = metadata.get("cache")
    if isinstance(cache_value, str):
        cache_hit = cache_hit or cache_value.strip().lower() == "hit"
    if attempts != 1 or retries != 0:
        raise SyMAIRouteError(
            "SyMAI retry behavior drifted from the one-attempt direct arm"
        )
    if cache_enabled or cache_hit:
        raise SyMAIRouteError(
            "SyMAI cache behavior drifted from the uncached direct arm"
        )

    return SyMAIRouteReceipt(
        role=role,
        route=SYMAI_ROUTE,
        orchestrator=SYMAI_ORCHESTRATOR,
        orchestrator_version=SYMAI_VERSION,
        router_provider=SYMAI_PROVIDER,
        model_alias=SYMAI_MODEL_ALIAS,
        resolved_provider=provider or "",
        resolved_endpoint=endpoint or "",
        resolved_model=model or "",
        resolved_backend=backend or "",
        shared_capacity=LEANSTRAL_CAPACITY,
        settings=settings,
        attempts=attempts,
        retries=retries,
        retry_policy="none",
        cache_enabled=False,
        cache_hit=False,
        independent_model_evidence=False,
        comparison_scope="incremental_symai_orchestration_only",
    )


def _default_symai_invoke(**kwargs: object) -> object:
    """Use the existing SyMAI router path without starting a model service."""

    from ipfs_datasets_py import llm_router

    prompt = kwargs["prompt"]
    response_format = kwargs["response_format"]
    settings = kwargs["settings"]
    if not isinstance(prompt, str) or not isinstance(response_format, Mapping):
        raise SyMAIMalformedResponseError("SyMAI invocation is malformed")
    if not isinstance(settings, SyMAIGenerationSettings):
        raise SyMAIMalformedResponseError("SyMAI settings are malformed")
    route_binding = {
        "resolved_provider_name": LEANSTRAL_PROVIDER,
        "resolved_model_name": LEANSTRAL_MODEL,
        "service_endpoint": LEANSTRAL_ENDPOINT,
        "routing_backend": LEANSTRAL_BACKEND,
    }
    raw = llm_router.generate_text(
        prompt,
        model_name=SYMAI_MODEL_ALIAS,
        provider=SYMAI_PROVIDER,
        allow_local_fallback=False,
        disable_model_retry=True,
        response_format=dict(response_format),
        temperature=settings.temperature,
        seed=settings.seed,
        max_tokens=settings.max_tokens,
        stop=list(settings.stop),
        timeout=settings.timeout_seconds,
        cache_prompt=settings.cache_prompt,
        _symai_route_binding=route_binding,
    )
    getter = getattr(llm_router, "get_last_generation_trace", None)
    trace = getter() if callable(getter) else {}
    metadata = dict(trace) if isinstance(trace, Mapping) else {}
    for key, value in route_binding.items():
        metadata.setdefault(key, value)
    metadata.update(
        {
            "attempts": 1,
            "retries": 0,
            "cache_enabled": False,
            "cache_hit": False,
        }
    )
    return raw, metadata


class SyMAIClient:
    """Stateless strict-JSON client for the existing SyMAI Leanstral route."""

    endpoint: Final = LEANSTRAL_ENDPOINT
    model: Final = LEANSTRAL_MODEL

    def __init__(self, invoker: SyMAIInvoker | None = None) -> None:
        self._invoker = invoker or _default_symai_invoke
        self.last_receipt: SyMAIRouteReceipt | None = None

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> SyMAICompletion:
        self.last_receipt = None
        settings = SyMAIGenerationSettings.for_role(max_tokens)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": _server_schema(schema),
            },
        }
        routed_prompt = (
            "SYSTEM_INSTRUCTION:\n"
            + system
            + "\nUSER_REQUEST:\n"
            + prompt
        )
        request_bytes = json.dumps(
            {
                "prompt": routed_prompt,
                "response_format": response_format,
                "settings": settings.to_dict(),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(request_bytes) > MAX_REQUEST_BYTES:
            raise LeanstralRequestError(
                "SyMAI request exceeds the direct arm's 64 KiB bound"
            )
        try:
            result = self._invoker(
                prompt=routed_prompt,
                response_format=response_format,
                settings=settings,
                route=SYMAI_ROUTE,
                provider=SYMAI_PROVIDER,
                model_alias=SYMAI_MODEL_ALIAS,
            )
        except (SyMAIClientError, LeanstralTimeoutError, TimeoutError):
            raise
        except (socket.timeout,) as exc:
            raise LeanstralTimeoutError("SyMAI request timed out") from exc
        except Exception as exc:
            raise SyMAIRouteError("SyMAI route is unavailable") from exc

        if (
            not isinstance(result, Sequence)
            or isinstance(result, (str, bytes, bytearray))
            or len(result) != 2
            or not isinstance(result[1], Mapping)
        ):
            raise SyMAIMalformedResponseError(
                "SyMAI must return output and route metadata"
            )
        raw, metadata = result
        if isinstance(raw, str):
            if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise SyMAIMalformedResponseError(
                    "SyMAI response exceeds the direct arm's byte bound"
                )
            value: Mapping[str, object] = _strict_json_object(raw)
        elif isinstance(raw, Mapping):
            try:
                encoded = json.dumps(
                    raw,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            except (RecursionError, TypeError, ValueError) as exc:
                raise SyMAIMalformedResponseError(
                    "SyMAI output is not strict JSON data"
                ) from exc
            if len(encoded) > MAX_RESPONSE_BYTES:
                raise SyMAIMalformedResponseError(
                    "SyMAI response exceeds the direct arm's byte bound"
                )
            value = dict(raw)
        else:
            raise SyMAIMalformedResponseError(
                "SyMAI output must be JSON text or an object"
            )
        receipt = _route_receipt(
            metadata,
            role=schema_name,
            max_tokens=max_tokens,
        )
        self.last_receipt = receipt
        return SyMAICompletion(value=value, metadata=metadata)


def _coerce_completion(
    value: object,
    *,
    role: str,
    max_tokens: int,
) -> tuple[Mapping[str, object], SyMAIRouteReceipt]:
    if isinstance(value, SyMAICompletion):
        candidate = value.value
        metadata = value.metadata
    elif (
        isinstance(getattr(value, "value", None), Mapping)
        and isinstance(getattr(value, "metadata", None), Mapping)
    ):
        candidate = value.value
        metadata = value.metadata
    elif (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
        and isinstance(value[0], Mapping)
        and isinstance(value[1], Mapping)
    ):
        candidate = value[0]
        metadata = value[1]
    else:
        raise SyMAIMalformedResponseError(
            "SyMAI client must return a candidate and route metadata"
        )
    return candidate, _route_receipt(
        metadata,
        role=role,
        max_tokens=max_tokens,
    )


def _complete_symai_json(
    client: SyMAICompletionClient,
    *,
    system: str,
    prompt: str,
    schema_name: str,
    schema: Mapping[str, object],
    max_tokens: int,
) -> tuple[Mapping[str, object], SyMAIRouteReceipt]:
    raw = client.complete_json(
        system=system,
        prompt=prompt,
        schema_name=schema_name,
        schema=schema,
        max_tokens=max_tokens,
    )
    if isinstance(raw, Mapping):
        metadata = getattr(client, "last_metadata", None)
        if not isinstance(metadata, Mapping):
            metadata = getattr(client, "route_metadata", None)
        if isinstance(metadata, Mapping):
            raw = (raw, metadata)
    return _coerce_completion(raw, role=schema_name, max_tokens=max_tokens)


def _failure_result(exc: BaseException) -> ConstructorResult:
    if isinstance(exc, (LeanstralTimeoutError, TimeoutError, socket.timeout)):
        reason = FailureReason.TIMEOUT
        detail = "SyMAI Leanstral request timed out"
    elif isinstance(exc, (SyMAIRouteError, LeanstralUnavailableError)):
        reason = FailureReason.CAPABILITY_UNAVAILABLE
        detail = str(exc) or "SyMAI Leanstral route is unavailable"
    elif isinstance(
        exc,
        (
            SyMAIMalformedResponseError,
            LeanstralMalformedResponseError,
            LeanstralRequestError,
            ContractError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ),
    ):
        reason = FailureReason.INVALID_OUTPUT
        detail = str(exc) or "SyMAI returned malformed output"
    else:
        reason = FailureReason.EXCEPTION
        detail = f"SyMAI constructor failed: {type(exc).__name__}"
    return ConstructorResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


class SyMAICanonicalConstructor:
    """Strict canonical constructor measuring SyMAI orchestration only."""

    interface: Final = SYMAI_CANONICAL_CONSTRUCTOR_INTERFACE
    provider_id: Final = SYMAI_PROVIDER_ID

    def __init__(self, client: SyMAICompletionClient | None = None) -> None:
        self._client = client or SyMAIClient()
        if (
            self._client.endpoint.rstrip("/") != LEANSTRAL_ENDPOINT
            or self._client.model != LEANSTRAL_MODEL
        ):
            raise ValueError(
                "client must bind the exact frozen Leanstral endpoint/model"
            )
        self._last_receipt: SyMAIRouteReceipt | None = None

    @property
    def identity(self) -> str:
        settings = SyMAIGenerationSettings.for_role(
            CONSTRUCTOR_MAX_TOKENS
        )
        return (
            f"{self.interface}:{SYMAI_ROUTE}:{LEANSTRAL_ENDPOINT}:"
            f"{LEANSTRAL_MODEL}:temperature={settings.temperature}:"
            f"seed={settings.seed}:max_tokens={settings.max_tokens}:"
            "retry=none:cache=disabled:independent_model=false"
        )

    @property
    def last_receipt(self) -> SyMAIRouteReceipt | None:
        return self._last_receipt

    @property
    def last_route_receipt(self) -> SyMAIRouteReceipt | None:
        """Alias emphasizing that this is routing, not model, evidence."""

        return self._last_receipt

    @property
    def ranking_eligible(self) -> bool:
        return bool(
            self._last_receipt is not None
            and self._last_receipt.ranking_eligible
        )

    @property
    def round_trip_contract(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "l1": "canonical_rules",
                "l2": "canonical_rules",
                "same_constructor_required": True,
                "coarse_forward_only_rankable": False,
                "comparison_scope": "incremental_symai_orchestration_only",
            }
        )

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self._last_receipt = None
        receipt: SyMAIRouteReceipt | None = None
        try:
            if not isinstance(request, ConstructorRequest):
                raise TypeError("request must be ConstructorRequest")
            candidate, receipt = _complete_symai_json(
                self._client,
                system=_CONSTRUCTOR_SYSTEM,
                prompt=_constructor_prompt(request, None),
                schema_name="semantic_roundtrip_canonical_ir_v1",
                schema=canonical_ir_schema(
                    request.allowed_atom_vocabulary
                ),
                max_tokens=CONSTRUCTOR_MAX_TOKENS,
            )
            canonical_ir = CanonicalRuleIR.from_dict(
                candidate, request.allowed_atom_vocabulary
            )
            if canonical_ir.is_empty:
                self._last_receipt = replace(
                    receipt,
                    ranking_exclusion_reason="empty_canonical_rules",
                )
                return ConstructorResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.EMPTY_L1,
                    failure_detail="SyMAI returned an empty canonical IR",
                )
            self._last_receipt = replace(
                receipt,
                canonical_contract_validated=True,
                ranking_eligible=True,
            )
            return ConstructorResult(
                status=ComponentStatus.SUCCESS,
                canonical_ir=canonical_ir,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if receipt is not None:
                self._last_receipt = replace(
                    receipt,
                    ranking_exclusion_reason=(
                        "coarse_or_noncanonical_forward_response"
                    ),
                )
            return _failure_result(exc)


__all__ = [
    "SYMAI_CANONICAL_CONSTRUCTOR_INTERFACE",
    "SYMAI_PROVIDER_ID",
    "SYMAI_ROUTE",
    "SYMAI_ORCHESTRATOR",
    "SYMAI_TEMPERATURE",
    "SYMAI_SEED",
    "SYMAI_STOP",
    "SYMAI_MAX_RETRIES",
    "SYMAI_CACHE_ENABLED",
    "SyMAIClientError",
    "SyMAIRouteError",
    "SyMAIMalformedResponseError",
    "SyMAIGenerationSettings",
    "SyMAIRouteReceipt",
    "SyMAIOrchestrationReceipt",
    "SyMAICompletion",
    "SyMAICompletionClient",
    "SyMAIClient",
    "SyMAICanonicalConstructor",
]
