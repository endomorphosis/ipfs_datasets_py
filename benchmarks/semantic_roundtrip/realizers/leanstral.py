"""Source-withheld Leanstral realizer for canonical semantic rules."""

from __future__ import annotations

import json
import socket
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    MAX_TEXT_LENGTH,
    ComponentStatus,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LEANSTRAL_PROVIDER_ID,
    CompletionClient,
    LeanstralClient,
    LeanstralMalformedResponseError,
    LeanstralRequestError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
)


LEANSTRAL_CANONICAL_REALIZER_INTERFACE: Final = "LeanstralCanonicalRealizer@1"
REALIZER_MAX_TOKENS: Final = 1536
REALIZATION_MAX_LENGTH: Final = min(12_000, MAX_TEXT_LENGTH)

REALIZATION_JSON_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text"],
    "properties": {
        "text": {
            "type": "string",
            "maxLength": REALIZATION_MAX_LENGTH,
        }
    },
}

_REALIZER_SYSTEM: Final = (
    "You are a source-withheld formal-logic realizer. The supplied canonical "
    "IR is your only semantic authority. Return one compact JSON object "
    "matching the supplied schema and never explain."
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _realizer_prompt(request: RealizerRequest) -> str:
    # Deliberately do not inspect or serialize request.config.  The contract
    # rejects source/native keys, and this stronger boundary supplies the model
    # only the canonical IR needed for realization.
    return (
        "Realize every and only the supplied legal rules as concise, fluent "
        "English. Replace atom-ID underscores with natural spacing and inflect "
        "minimally. Preserve O as shall/must, P as may, and F as shall not/must "
        "not. Preserve every condition, exception, and temporal qualifier with "
        "unambiguous scope. Do not invent facts, explanations, headings, "
        "citations, or rules.\nCANONICAL_IR_JSON:\n"
        + _canonical_json(request.canonical_ir.to_dict())
    )


def _failure_result(exc: BaseException) -> RealizerResult:
    if isinstance(
        exc,
        (LeanstralTimeoutError, TimeoutError, socket.timeout),
    ):
        reason = FailureReason.TIMEOUT
        detail = "Leanstral request timed out"
    elif isinstance(exc, LeanstralUnavailableError):
        reason = FailureReason.CAPABILITY_UNAVAILABLE
        detail = str(exc) or "Leanstral capability is unavailable"
    elif isinstance(
        exc,
        (
            LeanstralMalformedResponseError,
            LeanstralRequestError,
            ContractError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ),
    ):
        reason = FailureReason.INVALID_OUTPUT
        detail = str(exc) or "Leanstral returned malformed output"
    else:
        reason = FailureReason.EXCEPTION
        detail = f"Leanstral realizer failed: {type(exc).__name__}"
    return RealizerResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


class LeanstralCanonicalRealizer:
    """Stateless canonical-IR-only model realizer."""

    interface: Final = LEANSTRAL_CANONICAL_REALIZER_INTERFACE
    provider_id: Final = LEANSTRAL_PROVIDER_ID

    def __init__(self, client: CompletionClient | None = None) -> None:
        self._client = client or LeanstralClient()
        if (
            self._client.endpoint.rstrip("/") != LEANSTRAL_ENDPOINT
            or self._client.model != LEANSTRAL_MODEL
        ):
            raise ValueError(
                "client must bind the exact frozen Leanstral endpoint/model"
            )

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{LEANSTRAL_ENDPOINT}:{LEANSTRAL_MODEL}:"
            "source_withheld"
        )

    def realize(self, request: RealizerRequest) -> RealizerResult:
        try:
            if not isinstance(request, RealizerRequest):
                raise TypeError("request must be RealizerRequest")
            candidate = self._client.complete_json(
                system=_REALIZER_SYSTEM,
                prompt=_realizer_prompt(request),
                schema_name="semantic_roundtrip_realization_v1",
                schema=REALIZATION_JSON_SCHEMA,
                max_tokens=REALIZER_MAX_TOKENS,
            )
            if set(candidate) != {"text"}:
                raise LeanstralMalformedResponseError(
                    "realization must contain exactly the text key"
                )
            text = candidate["text"]
            if not isinstance(text, str):
                raise LeanstralMalformedResponseError(
                    "realization text must be a string"
                )
            text = " ".join(text.strip().split())
            if not text:
                return RealizerResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.BLANK_T1,
                    failure_detail="Leanstral returned a blank realization",
                )
            if len(text) > REALIZATION_MAX_LENGTH:
                raise LeanstralMalformedResponseError(
                    "realization exceeds the fixed character bound"
                )
            return RealizerResult(
                status=ComponentStatus.SUCCESS,
                text=text,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return _failure_result(exc)


__all__ = [
    "LEANSTRAL_CANONICAL_REALIZER_INTERFACE",
    "REALIZER_MAX_TOKENS",
    "REALIZATION_MAX_LENGTH",
    "REALIZATION_JSON_SCHEMA",
    "LeanstralCanonicalRealizer",
]
