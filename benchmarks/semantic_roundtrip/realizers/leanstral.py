"""Source-withheld Leanstral realizer for canonical semantic rules."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    MAX_TEXT_LENGTH,
    ComponentStatus,
    FailureReason,
    RealizerRequest,
    RealizerResult,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LEANSTRAL_PROVIDER_ID,
    LEANSTRAL_ROUND_TRIP_ADAPTERS_INTERFACE,
    CompletionClient,
    LeanstralClient,
    LeanstralMalformedResponseError,
    ModelRejectionTaxonomy,
    classify_leanstral_exception,
)


LEANSTRAL_CANONICAL_REALIZER_INTERFACE: Final = "LeanstralCanonicalRealizer@1"
REALIZER_MAX_TOKENS: Final = 1536
REALIZATION_MAX_LENGTH: Final = min(12_000, MAX_TEXT_LENGTH)
SINGLE_RULE_RESEARCH_REALIZATION_SCHEMA_NAME: Final = (
    "semantic_roundtrip_single_rule_research_realization_v1"
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
    """Return a single-text realization schema for hybrid repair experiments."""

    return json.loads(json.dumps(REALIZATION_JSON_SCHEMA))


def _failure_result(
    exc: BaseException,
) -> tuple[RealizerResult, ModelRejectionTaxonomy]:
    reason, taxonomy, detail = classify_leanstral_exception(exc)
    if reason is FailureReason.EXCEPTION:
        detail = f"Leanstral realizer failed: {type(exc).__name__}"
    return (
        RealizerResult(
            status=ComponentStatus.FAILED,
            failure_reason=reason,
            failure_detail=detail[:1000],
        ),
        taxonomy,
    )


class LeanstralCanonicalRealizer:
    """Stateless canonical-IR-only model realizer."""

    interface: Final = LEANSTRAL_CANONICAL_REALIZER_INTERFACE
    provider_id: Final = LEANSTRAL_PROVIDER_ID
    adapters_interface: Final = LEANSTRAL_ROUND_TRIP_ADAPTERS_INTERFACE

    def __init__(
        self,
        client: CompletionClient | None = None,
        *,
        research_single_rule_schema: bool = False,
    ) -> None:
        self._client = client or LeanstralClient()
        if (
            self._client.endpoint.rstrip("/") != LEANSTRAL_ENDPOINT
            or self._client.model != LEANSTRAL_MODEL
        ):
            raise ValueError(
                "client must bind the exact frozen Leanstral endpoint/model"
            )
        if not isinstance(research_single_rule_schema, bool):
            raise TypeError("research_single_rule_schema must be bool")
        self._research_single_rule_schema = research_single_rule_schema
        self._last_rejection_taxonomy: ModelRejectionTaxonomy | None = None
        self._model_calls: int = 0
        self._accepted_calls: int = 0

    @property
    def identity(self) -> str:
        schema_mode = (
            "single_rule_research"
            if self._research_single_rule_schema
            else "multi_rule_promotion"
        )
        return (
            f"{self.interface}:{LEANSTRAL_ENDPOINT}:{LEANSTRAL_MODEL}:"
            f"source_withheld:{schema_mode}"
        )

    @property
    def research_single_rule_schema(self) -> bool:
        return self._research_single_rule_schema

    @property
    def last_rejection_taxonomy(self) -> ModelRejectionTaxonomy | None:
        """Typed rejection for the most recent model call, if any."""

        return self._last_rejection_taxonomy

    @property
    def model_call_stats(self) -> Mapping[str, object]:
        """Call-level reliability counters separate from end-to-end loss."""

        total = self._model_calls
        accepted = self._accepted_calls
        return {
            "model_calls": total,
            "accepted_calls": accepted,
            "accept_rate": (
                float(accepted) / float(total) if total else 0.0
            ),
            "last_rejection_taxonomy": (
                None
                if self._last_rejection_taxonomy is None
                else self._last_rejection_taxonomy.value
            ),
        }

    def realize(self, request: RealizerRequest) -> RealizerResult:
        self._last_rejection_taxonomy = None
        try:
            if not isinstance(request, RealizerRequest):
                raise TypeError("request must be RealizerRequest")
            if (
                self._research_single_rule_schema
                and len(request.canonical_ir.rules) != 1
            ):
                self._last_rejection_taxonomy = ModelRejectionTaxonomy.SCHEMA
                return RealizerResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail=(
                        "single-rule research realizer requires exactly one "
                        "input rule"
                    ),
                )
            schema_name = (
                SINGLE_RULE_RESEARCH_REALIZATION_SCHEMA_NAME
                if self._research_single_rule_schema
                else "semantic_roundtrip_realization_v1"
            )
            schema = (
                single_rule_research_realization_schema()
                if self._research_single_rule_schema
                else REALIZATION_JSON_SCHEMA
            )
            self._model_calls += 1
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
                self._last_rejection_taxonomy = ModelRejectionTaxonomy.BLANK
                return RealizerResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.BLANK_T1,
                    failure_detail="Leanstral returned a blank realization",
                )
            if len(text) > REALIZATION_MAX_LENGTH:
                raise LeanstralMalformedResponseError(
                    "realization exceeds the fixed character bound"
                )
            self._accepted_calls += 1
            self._last_rejection_taxonomy = None
            return RealizerResult(
                status=ComponentStatus.SUCCESS,
                text=text,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            result, taxonomy = _failure_result(exc)
            self._last_rejection_taxonomy = taxonomy
            return result


__all__ = [
    "LEANSTRAL_CANONICAL_REALIZER_INTERFACE",
    "REALIZER_MAX_TOKENS",
    "REALIZATION_MAX_LENGTH",
    "REALIZATION_JSON_SCHEMA",
    "SINGLE_RULE_RESEARCH_REALIZATION_SCHEMA_NAME",
    "single_rule_research_realization_schema",
    "LeanstralCanonicalRealizer",
]
