"""Source-withheld SyMAI realizer over the frozen Leanstral service."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from types import MappingProxyType
from typing import Final, Mapping

from benchmarks.semantic_roundtrip.contracts import (
    ComponentStatus,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LeanstralMalformedResponseError,
    LeanstralRequestError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
)
from benchmarks.semantic_roundtrip.constructors.symai import (
    SYMAI_PROVIDER_ID,
    SYMAI_ROUTE,
    SyMAIClient,
    SyMAICompletionClient,
    SyMAIGenerationSettings,
    SyMAIMalformedResponseError,
    SyMAIRouteError,
    SyMAIRouteReceipt,
    _complete_symai_json,
)
from benchmarks.semantic_roundtrip.realizers.leanstral import (
    REALIZATION_JSON_SCHEMA,
    REALIZATION_MAX_LENGTH,
    REALIZER_MAX_TOKENS,
    _realizer_prompt,
)


SYMAI_CANONICAL_REALIZER_INTERFACE: Final = "SyMAICanonicalRealizer@1"

_REALIZER_SYSTEM: Final = (
    "You are a source-withheld formal-logic realizer. The supplied canonical "
    "IR is your only semantic authority. Return one compact JSON object "
    "matching the supplied schema and never explain."
)


def _failure_result(exc: BaseException) -> RealizerResult:
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
        detail = f"SyMAI realizer failed: {type(exc).__name__}"
    return RealizerResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


class SyMAICanonicalRealizer:
    """Canonical-IR-only SyMAI route with no source or constructor state."""

    interface: Final = SYMAI_CANONICAL_REALIZER_INTERFACE
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
        settings = SyMAIGenerationSettings.for_role(REALIZER_MAX_TOKENS)
        return (
            f"{self.interface}:{SYMAI_ROUTE}:{LEANSTRAL_ENDPOINT}:"
            f"{LEANSTRAL_MODEL}:temperature={settings.temperature}:"
            f"seed={settings.seed}:max_tokens={settings.max_tokens}:"
            "source_withheld:retry=none:cache=disabled:"
            "independent_model=false"
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
                "input": "canonical_rules_only",
                "source_withheld": True,
                "output": "reconstruction_text",
                "l2_via_same_symai_constructor": "canonical_rules",
                "comparison_scope": "incremental_symai_orchestration_only",
            }
        )

    def realize(self, request: RealizerRequest) -> RealizerResult:
        self._last_receipt = None
        receipt: SyMAIRouteReceipt | None = None
        try:
            if not isinstance(request, RealizerRequest):
                raise TypeError("request must be RealizerRequest")
            candidate, receipt = _complete_symai_json(
                self._client,
                system=_REALIZER_SYSTEM,
                prompt=_realizer_prompt(request),
                schema_name="semantic_roundtrip_realization_v1",
                schema=REALIZATION_JSON_SCHEMA,
                max_tokens=REALIZER_MAX_TOKENS,
            )
            if set(candidate) != {"text"}:
                raise SyMAIMalformedResponseError(
                    "realization must contain exactly the text key"
                )
            text = candidate["text"]
            if not isinstance(text, str):
                raise SyMAIMalformedResponseError(
                    "realization text must be a string"
                )
            text = " ".join(text.strip().split())
            if not text:
                self._last_receipt = replace(
                    receipt,
                    ranking_exclusion_reason="blank_reconstruction",
                )
                return RealizerResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.BLANK_T1,
                    failure_detail="SyMAI returned a blank realization",
                )
            if len(text) > REALIZATION_MAX_LENGTH:
                raise SyMAIMalformedResponseError(
                    "realization exceeds the fixed character bound"
                )
            self._last_receipt = replace(
                receipt,
                canonical_contract_validated=True,
                ranking_eligible=True,
            )
            return RealizerResult(
                status=ComponentStatus.SUCCESS,
                text=text,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if receipt is not None:
                self._last_receipt = replace(
                    receipt,
                    ranking_exclusion_reason="invalid_reverse_response",
                )
            return _failure_result(exc)


__all__ = [
    "SYMAI_CANONICAL_REALIZER_INTERFACE",
    "SyMAICanonicalRealizer",
]
