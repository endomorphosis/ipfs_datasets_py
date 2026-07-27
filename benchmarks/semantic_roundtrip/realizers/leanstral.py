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
    LeanstralModelCallDiagnostic,
    LeanstralRequestError,
    LeanstralSchemaPath,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
    ModelRejectionReason,
)


LEANSTRAL_CANONICAL_REALIZER_INTERFACE: Final = "LeanstralCanonicalRealizer@1"
REALIZER_MAX_TOKENS: Final = 1536
REALIZATION_MAX_LENGTH: Final = min(12_000, MAX_TEXT_LENGTH)
STANDARD_REALIZATION_SCHEMA_NAME: Final = "semantic_roundtrip_realization_v1"
SINGLE_RULE_RESEARCH_REALIZATION_SCHEMA_NAME: Final = (
    "research_single_rule_realization_v1"
)

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

SINGLE_RULE_RESEARCH_REALIZATION_JSON_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text"],
    "properties": {
        "text": {
            "type": "string",
            "minLength": 1,
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


def single_rule_research_realization_schema() -> dict[str, object]:
    """Exactly-one-rule research realization envelope for hybrid repair."""

    return json.loads(json.dumps(SINGLE_RULE_RESEARCH_REALIZATION_JSON_SCHEMA))


def _classify_realizer_failure(
    exc: BaseException,
) -> tuple[FailureReason, str, ModelRejectionReason]:
    if isinstance(
        exc,
        (LeanstralTimeoutError, TimeoutError, socket.timeout),
    ):
        return (
            FailureReason.TIMEOUT,
            "Leanstral request timed out",
            ModelRejectionReason.TIMEOUT,
        )
    if isinstance(exc, LeanstralUnavailableError):
        return (
            FailureReason.CAPABILITY_UNAVAILABLE,
            str(exc) or "Leanstral capability is unavailable",
            ModelRejectionReason.OTHER,
        )
    if isinstance(
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
        return (
            FailureReason.INVALID_OUTPUT,
            str(exc) or "Leanstral returned malformed output",
            ModelRejectionReason.SCHEMA,
        )
    return (
        FailureReason.EXCEPTION,
        f"Leanstral realizer failed: {type(exc).__name__}",
        ModelRejectionReason.OTHER,
    )


def _failure_result(exc: BaseException) -> RealizerResult:
    reason, detail, _rejection = _classify_realizer_failure(exc)
    return RealizerResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


class LeanstralCanonicalRealizer:
    """Stateless canonical-IR-only model realizer."""

    interface: Final = LEANSTRAL_CANONICAL_REALIZER_INTERFACE
    provider_id: Final = LEANSTRAL_PROVIDER_ID

    def __init__(
        self,
        client: CompletionClient | None = None,
        *,
        schema_path: LeanstralSchemaPath | str = LeanstralSchemaPath.STANDARD,
    ) -> None:
        self._client = client or LeanstralClient()
        if (
            self._client.endpoint.rstrip("/") != LEANSTRAL_ENDPOINT
            or self._client.model != LEANSTRAL_MODEL
        ):
            raise ValueError(
                "client must bind the exact frozen Leanstral endpoint/model"
            )
        try:
            self._schema_path = LeanstralSchemaPath(schema_path)
        except ValueError as exc:
            raise ValueError(
                f"unsupported Leanstral schema path: {schema_path}"
            ) from exc
        self._last_call: LeanstralModelCallDiagnostic | None = None

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{LEANSTRAL_ENDPOINT}:{LEANSTRAL_MODEL}:"
            f"source_withheld:schema_path={self._schema_path.value}"
        )

    @property
    def schema_path(self) -> LeanstralSchemaPath:
        return self._schema_path

    @property
    def last_call(self) -> LeanstralModelCallDiagnostic | None:
        """Most recent model-call diagnostic with typed rejection reason."""

        return self._last_call

    def realize(self, request: RealizerRequest) -> RealizerResult:
        schema_name = (
            SINGLE_RULE_RESEARCH_REALIZATION_SCHEMA_NAME
            if self._schema_path is LeanstralSchemaPath.SINGLE_RULE_RESEARCH
            else STANDARD_REALIZATION_SCHEMA_NAME
        )
        if self._schema_path is LeanstralSchemaPath.SINGLE_RULE_RESEARCH:
            schema = single_rule_research_realization_schema()
        else:
            schema = REALIZATION_JSON_SCHEMA
        try:
            if not isinstance(request, RealizerRequest):
                raise TypeError("request must be RealizerRequest")
            if (
                self._schema_path is LeanstralSchemaPath.SINGLE_RULE_RESEARCH
                and len(request.canonical_ir.rules) != 1
            ):
                detail = (
                    "single-rule research path requires exactly one input rule"
                )
                self._last_call = LeanstralModelCallDiagnostic(
                    outcome="rejected",
                    rejection_reason=ModelRejectionReason.SCHEMA.value,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    detail=detail,
                    schema_name=schema_name,
                    schema_path=self._schema_path.value,
                )
                return RealizerResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail=detail,
                )
            candidate = self._client.complete_json(
                system=_REALIZER_SYSTEM,
                prompt=_realizer_prompt(request),
                schema_name=schema_name,
                schema=schema,
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
                detail = "Leanstral returned a blank realization"
                self._last_call = LeanstralModelCallDiagnostic(
                    outcome="rejected",
                    rejection_reason=ModelRejectionReason.BLANK.value,
                    failure_reason=FailureReason.BLANK_T1,
                    detail=detail,
                    schema_name=schema_name,
                    schema_path=self._schema_path.value,
                )
                return RealizerResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.BLANK_T1,
                    failure_detail=detail,
                )
            if len(text) > REALIZATION_MAX_LENGTH:
                raise LeanstralMalformedResponseError(
                    "realization exceeds the fixed character bound"
                )
            self._last_call = LeanstralModelCallDiagnostic(
                outcome="accepted",
                rejection_reason=None,
                failure_reason=None,
                detail=None,
                schema_name=schema_name,
                schema_path=self._schema_path.value,
            )
            return RealizerResult(
                status=ComponentStatus.SUCCESS,
                text=text,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            reason, detail, rejection = _classify_realizer_failure(exc)
            self._last_call = LeanstralModelCallDiagnostic(
                outcome="call_failed",
                rejection_reason=rejection.value,
                failure_reason=reason,
                detail=detail[:500],
                schema_name=schema_name,
                schema_path=self._schema_path.value,
            )
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=reason,
                failure_detail=detail[:1000],
            )


__all__ = [
    "LEANSTRAL_CANONICAL_REALIZER_INTERFACE",
    "REALIZER_MAX_TOKENS",
    "REALIZATION_MAX_LENGTH",
    "REALIZATION_JSON_SCHEMA",
    "STANDARD_REALIZATION_SCHEMA_NAME",
    "SINGLE_RULE_RESEARCH_REALIZATION_SCHEMA_NAME",
    "SINGLE_RULE_RESEARCH_REALIZATION_JSON_SCHEMA",
    "single_rule_research_realization_schema",
    "LeanstralCanonicalRealizer",
]
