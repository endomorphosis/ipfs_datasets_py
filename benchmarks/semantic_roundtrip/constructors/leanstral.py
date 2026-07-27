"""Fair, bounded Leanstral constructors for the semantic round-trip matrix.

The adapters in this module talk only to the already-running service frozen by
``semantic_roundtrip_capabilities``.  They deliberately have no conversation
or response cache: each matrix coordinate is one independent request.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol

from benchmarks.semantic_roundtrip.contracts import (
    LIST_FIELDS,
    MAX_ATOM_LENGTH,
    MAX_LIST_ITEMS,
    MAX_RULES,
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
)
from benchmarks.semantic_roundtrip_capabilities import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    SPACY_PIPELINE,
    SPACY_REQUIRED_ANNOTATIONS,
)


LEANSTRAL_CANONICAL_CONSTRUCTOR_INTERFACE: Final = (
    "LeanstralCanonicalConstructor@1"
)
LEANSTRAL_ROUND_TRIP_ADAPTERS_INTERFACE: Final = "LeanstralRoundTripAdapters@1"
LEANSTRAL_PROVIDER_ID: Final = "leanstral-local"
LEANSTRAL_TIMEOUT_SECONDS: Final = 120.0
CONSTRUCTOR_MAX_TOKENS: Final = 3072
MAX_REQUEST_BYTES: Final = 64 * 1024
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
SINGLE_RULE_RESEARCH_SCHEMA_NAME: Final = (
    "semantic_roundtrip_single_rule_research_canonical_ir_v1"
)

_CONSTRUCTOR_SYSTEM: Final = (
    "You are a deterministic legal semantic parser. Return one compact JSON "
    "object matching the supplied schema. Never explain, add keys, repeat a "
    "rule, or claim that generated logic is proved."
)


class ModelRejectionTaxonomy(str, Enum):
    """Typed rejection reasons recorded for every model call.

    Distinct from end-to-end :class:`FailureReason` loss codes.  Promotion and
    research paths share the same six-way taxonomy so accept/reject rates are
    comparable across arms without conflating semantic loss.
    """

    BLANK = "blank"
    SCHEMA = "schema"
    POLARITY = "polarity"
    EMPTY_RULES = "empty_rules"
    TIMEOUT = "timeout"
    OTHER = "other"


_DETAILED_REJECTION_TO_TAXONOMY: Final[Mapping[str, ModelRejectionTaxonomy]] = {
    "blank_output": ModelRejectionTaxonomy.BLANK,
    "blank": ModelRejectionTaxonomy.BLANK,
    "empty_output": ModelRejectionTaxonomy.EMPTY_RULES,
    "empty_rules": ModelRejectionTaxonomy.EMPTY_RULES,
    "malformed_output": ModelRejectionTaxonomy.SCHEMA,
    "schema": ModelRejectionTaxonomy.SCHEMA,
    "polarity_ambiguous": ModelRejectionTaxonomy.POLARITY,
    "polarity": ModelRejectionTaxonomy.POLARITY,
    "call_timeout": ModelRejectionTaxonomy.TIMEOUT,
    "timeout": ModelRejectionTaxonomy.TIMEOUT,
    "route_contract_failure": ModelRejectionTaxonomy.OTHER,
    "call_exception": ModelRejectionTaxonomy.OTHER,
    "other": ModelRejectionTaxonomy.OTHER,
}


def classify_model_rejection(
    rejection: str | None,
    *,
    failure_reason: FailureReason | None = None,
) -> ModelRejectionTaxonomy | None:
    """Map a detailed rejection or failure reason onto the typed taxonomy."""

    if rejection is None and failure_reason is None:
        return None
    if isinstance(rejection, str) and rejection.strip():
        key = rejection.strip().lower()
        if key in _DETAILED_REJECTION_TO_TAXONOMY:
            return _DETAILED_REJECTION_TO_TAXONOMY[key]
        if key in {item.value for item in ModelRejectionTaxonomy}:
            return ModelRejectionTaxonomy(key)
    if failure_reason is FailureReason.TIMEOUT:
        return ModelRejectionTaxonomy.TIMEOUT
    if failure_reason in {FailureReason.EMPTY_L1, FailureReason.EMPTY_L2}:
        return ModelRejectionTaxonomy.EMPTY_RULES
    if failure_reason is FailureReason.BLANK_T1:
        return ModelRejectionTaxonomy.BLANK
    if failure_reason is FailureReason.INVALID_OUTPUT:
        return ModelRejectionTaxonomy.SCHEMA
    return ModelRejectionTaxonomy.OTHER


class LeanstralConstructorArm(str, Enum):
    """The two declared model-constructor arms."""

    DIRECT = "direct"
    SPACY_EVIDENCE = "spacy_evidence"


class LeanstralClientError(RuntimeError):
    """Base class for bounded Leanstral client failures."""


class LeanstralTimeoutError(LeanstralClientError):
    """The pinned service did not finish within the request deadline."""


class LeanstralUnavailableError(LeanstralClientError):
    """The pinned endpoint or exact model was unavailable."""


class LeanstralMalformedResponseError(LeanstralClientError):
    """The service returned an envelope or JSON value outside the contract."""


class LeanstralRequestError(LeanstralClientError):
    """The locally constructed provider request violated its byte bound."""


def classify_leanstral_exception(
    exc: BaseException,
) -> tuple[FailureReason, ModelRejectionTaxonomy, str]:
    """Classify a provider exception into failure reason and rejection taxonomy."""

    if isinstance(exc, (LeanstralTimeoutError, TimeoutError, socket.timeout)):
        return (
            FailureReason.TIMEOUT,
            ModelRejectionTaxonomy.TIMEOUT,
            "Leanstral request timed out",
        )
    if isinstance(exc, LeanstralUnavailableError):
        return (
            FailureReason.CAPABILITY_UNAVAILABLE,
            ModelRejectionTaxonomy.OTHER,
            str(exc) or "Leanstral capability is unavailable",
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
            ModelRejectionTaxonomy.SCHEMA,
            str(exc) or "Leanstral returned malformed output",
        )
    return (
        FailureReason.EXCEPTION,
        ModelRejectionTaxonomy.OTHER,
        f"Leanstral call failed: {type(exc).__name__}",
    )


class CompletionClient(Protocol):
    """Narrow dependency injected into both adapters and their unit tests."""

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
    ) -> Mapping[str, object]:
        """Return the one strict JSON object produced by the model."""


Transport = Callable[[str, bytes, float], object]


def _strict_json_object(raw: str) -> dict[str, object]:
    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LeanstralMalformedResponseError(
                    f"duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                LeanstralMalformedResponseError(
                    f"non-finite JSON constant: {token}"
                )
            ),
        )
    except LeanstralMalformedResponseError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise LeanstralMalformedResponseError(
            "model content is not strict JSON"
        ) from exc
    if not isinstance(value, dict):
        raise LeanstralMalformedResponseError(
            "model content must be one JSON object"
        )
    return value


def _server_schema(value: object) -> object:
    """Adapt the client-enforced schema to the pinned llama.cpp grammar.

    The pinned grammar compiler does not support ``maxLength``.  Structural
    bounds, array bounds, enums, required keys, and additional-properties
    rules remain server enforced; the canonical contracts enforce string
    lengths again after generation.
    """

    if isinstance(value, Mapping):
        return {
            str(key): _server_schema(item)
            for key, item in value.items()
            if key != "maxLength"
        }
    if isinstance(value, list):
        return [_server_schema(item) for item in value]
    return value


def _urllib_transport(url: str, body: bytes, timeout: float) -> object:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in {408, 504}:
            raise LeanstralTimeoutError(
                "Leanstral request timed out"
            ) from exc
        raise LeanstralUnavailableError(
            f"Leanstral endpoint returned HTTP {exc.code}"
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise LeanstralTimeoutError("Leanstral request timed out") from exc
    except (ConnectionError, OSError, urllib.error.URLError) as exc:
        raise LeanstralUnavailableError(
            "Leanstral endpoint is unavailable"
        ) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise LeanstralMalformedResponseError(
            "Leanstral response exceeds the byte bound"
        )
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as exc:
        raise LeanstralMalformedResponseError(
            "Leanstral response envelope is not JSON"
        ) from exc


@dataclass(frozen=True, slots=True)
class LeanstralClient:
    """Stateless client for the exact, pre-existing local Leanstral service."""

    endpoint: str = LEANSTRAL_ENDPOINT
    model: str = LEANSTRAL_MODEL
    timeout_seconds: float = LEANSTRAL_TIMEOUT_SECONDS
    transport: Transport = _urllib_transport

    def __post_init__(self) -> None:
        if self.endpoint.rstrip("/") != LEANSTRAL_ENDPOINT:
            raise ValueError(
                f"endpoint must be the frozen identity {LEANSTRAL_ENDPOINT!r}"
            )
        if self.model != LEANSTRAL_MODEL:
            raise ValueError(
                f"model must be the frozen identity {LEANSTRAL_MODEL!r}"
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "endpoint", self.endpoint.rstrip("/"))

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> Mapping[str, object]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "seed": 0,
            "max_tokens": max_tokens,
            "stop": ["<|im_end|>"],
            # Explicitly prevent server-side prompt/session reuse across arms.
            "cache_prompt": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": _server_schema(schema),
                },
            },
        }
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise LeanstralRequestError(
                "Leanstral request exceeds the 64 KiB bound"
            )

        try:
            envelope = self.transport(
                self.endpoint + "/chat/completions",
                body,
                float(self.timeout_seconds),
            )
        except (LeanstralClientError, TimeoutError, ConnectionError):
            raise
        except Exception as exc:
            raise LeanstralUnavailableError(
                "Leanstral transport failed"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise LeanstralMalformedResponseError(
                "Leanstral response envelope must be an object"
            )
        if envelope.get("model") != self.model:
            raise LeanstralUnavailableError(
                "Leanstral response model identity drifted"
            )
        choices = envelope.get("choices")
        if (
            not isinstance(choices, Sequence)
            or isinstance(choices, (str, bytes, bytearray))
            or len(choices) != 1
            or not isinstance(choices[0], Mapping)
        ):
            raise LeanstralMalformedResponseError(
                "Leanstral response has an invalid choice set"
            )
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise LeanstralMalformedResponseError(
                "Leanstral response did not finish at a complete JSON object"
            )
        message = choice.get("message")
        content = (
            message.get("content")
            if isinstance(message, Mapping)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise LeanstralMalformedResponseError(
                "Leanstral response has no content"
            )
        return _strict_json_object(content)


def canonical_ir_schema(
    vocabulary: AllowedAtomVocabulary,
    *,
    min_rules: int = 0,
    max_rules: int = MAX_RULES,
) -> dict[str, object]:
    """Build the fixed bounded schema with only case-visible atom enums."""

    if (
        isinstance(min_rules, bool)
        or isinstance(max_rules, bool)
        or not isinstance(min_rules, int)
        or not isinstance(max_rules, int)
        or min_rules < 0
        or max_rules < min_rules
        or max_rules > MAX_RULES
    ):
        raise ContractError("canonical IR schema rule bounds are invalid")

    qualifier_schema = {
        "type": "array",
        "maxItems": MAX_LIST_ITEMS,
        "items": {
            "type": "string",
            "maxLength": MAX_ATOM_LENGTH,
            "enum": list(vocabulary.qualifiers),
        },
    }
    rules_schema: dict[str, object] = {
        "type": "array",
        "maxItems": max_rules,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "modality",
                "actor",
                "action",
                "object",
                "conditions",
                "exceptions",
                "temporal",
            ],
            "properties": {
                "modality": {
                    "type": "string",
                    "enum": ["O", "P", "F"],
                },
                "actor": {
                    "type": "string",
                    "maxLength": MAX_ATOM_LENGTH,
                    "enum": list(vocabulary.actors),
                },
                "action": {
                    "type": "string",
                    "maxLength": MAX_ATOM_LENGTH,
                    "enum": list(vocabulary.actions),
                },
                "object": {
                    "type": "string",
                    "maxLength": MAX_ATOM_LENGTH,
                    "enum": ["", *vocabulary.objects],
                },
                **{
                    field: json.loads(json.dumps(qualifier_schema))
                    for field in LIST_FIELDS
                },
            },
        },
    }
    if min_rules > 0:
        rules_schema["minItems"] = min_rules
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rules"],
        "properties": {
            "rules": rules_schema,
        },
    }


def single_rule_research_canonical_schema(
    vocabulary: AllowedAtomVocabulary,
) -> dict[str, object]:
    """Return the single-rule research schema for hybrid repair experiments.

    Promotion constructors keep the multi-rule matrix schema.  Hybrid repair
    experiments may request this narrower path when repairing exactly one
    rule in isolation without changing the promotion default.
    """

    return canonical_ir_schema(vocabulary, min_rules=1, max_rules=1)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _constructor_prompt(
    request: ConstructorRequest,
    evidence: Mapping[str, object] | None,
) -> str:
    prompt = (
        "Convert the source into every and only atomic legal rules. O means "
        "obligation, P permission, and F prohibition. Preserve negation, "
        "actor/action/object binding, conditions, exceptions, and temporal "
        "scope. Use only exact atom IDs from ALLOWED_ATOMS. Return an empty "
        "rules array only when the source contains no norm.\n"
        "ALLOWED_ATOMS_JSON:\n"
        + _canonical_json(request.allowed_atom_vocabulary.to_dict())
        + "\nSOURCE_TEXT_JSON_STRING:\n"
        + _canonical_json(request.source_text)
    )
    if evidence is not None:
        prompt += "\nSPACY_EVIDENCE_JSON:\n" + _canonical_json(evidence)
    return prompt


def _validate_full_spacy_pipeline(nlp: object) -> None:
    pipe_names = getattr(nlp, "pipe_names", None)
    if (
        not isinstance(pipe_names, Sequence)
        or isinstance(pipe_names, (str, bytes, bytearray))
        or tuple(pipe_names) != tuple(SPACY_PIPELINE)
    ):
        raise LeanstralUnavailableError(
            "the declared full spaCy pipeline is unavailable or degraded"
        )
    if not callable(nlp):
        raise LeanstralUnavailableError(
            "the declared spaCy pipeline is not callable"
        )
    if getattr(nlp, "lang", None) != "en":
        raise LeanstralUnavailableError(
            "the declared spaCy pipeline is not the required English pipeline"
        )


def _spacy_evidence(nlp: object, text: str) -> dict[str, object]:
    _validate_full_spacy_pipeline(nlp)
    try:
        doc = nlp(text)  # type: ignore[operator]
        has_annotation = getattr(doc, "has_annotation", None)
        if not callable(has_annotation) or any(
            not has_annotation(name) for name in SPACY_REQUIRED_ANNOTATIONS
        ):
            raise LeanstralUnavailableError(
                "the declared full spaCy annotations are unavailable"
            )
        tokens = list(doc)[:256]
        entities = list(getattr(doc, "ents", ()))[:32]
        return {
            "pipeline": list(SPACY_PIPELINE),
            "tokens": [
                {
                    "text": str(token.text),
                    "lemma": str(token.lemma_),
                    "pos": str(token.pos_),
                    "dep": str(token.dep_),
                    "head": int(token.head.i),
                }
                for token in tokens
            ],
            "entities": [
                {"text": str(entity.text), "label": str(entity.label_)}
                for entity in entities
            ],
        }
    except LeanstralClientError:
        raise
    except Exception as exc:
        raise LeanstralUnavailableError(
            "the declared full spaCy pipeline failed"
        ) from exc


def _failure_result(
    exc: BaseException,
) -> tuple[ConstructorResult, ModelRejectionTaxonomy]:
    reason, taxonomy, detail = classify_leanstral_exception(exc)
    if reason is FailureReason.EXCEPTION:
        detail = f"Leanstral constructor failed: {type(exc).__name__}"
    return (
        ConstructorResult(
            status=ComponentStatus.FAILED,
            failure_reason=reason,
            failure_detail=detail[:1000],
        ),
        taxonomy,
    )


class LeanstralCanonicalConstructor:
    """Canonical constructor with direct and declared full-spaCy arms."""

    interface: Final = LEANSTRAL_CANONICAL_CONSTRUCTOR_INTERFACE
    provider_id: Final = LEANSTRAL_PROVIDER_ID
    adapters_interface: Final = LEANSTRAL_ROUND_TRIP_ADAPTERS_INTERFACE

    def __init__(
        self,
        client: CompletionClient | None = None,
        *,
        arm: LeanstralConstructorArm | str = LeanstralConstructorArm.DIRECT,
        spacy_pipeline: object | None = None,
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
        try:
            self._arm = LeanstralConstructorArm(arm)
        except ValueError as exc:
            raise ValueError(f"unsupported Leanstral constructor arm: {arm}") from exc
        if (
            self._arm is LeanstralConstructorArm.DIRECT
            and spacy_pipeline is not None
        ):
            raise ValueError(
                "the direct Leanstral arm may not receive spaCy evidence"
            )
        if not isinstance(research_single_rule_schema, bool):
            raise TypeError("research_single_rule_schema must be bool")
        self._spacy_pipeline = spacy_pipeline
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
            f"{self.interface}:{self._arm.value}:"
            f"{LEANSTRAL_ENDPOINT}:{LEANSTRAL_MODEL}:{schema_mode}"
        )

    @property
    def arm(self) -> LeanstralConstructorArm:
        return self._arm

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

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self._last_rejection_taxonomy = None
        try:
            if not isinstance(request, ConstructorRequest):
                raise TypeError("request must be ConstructorRequest")
            evidence: Mapping[str, object] | None = None
            if self._arm is LeanstralConstructorArm.SPACY_EVIDENCE:
                if self._spacy_pipeline is None:
                    raise LeanstralUnavailableError(
                        "the declared full spaCy pipeline is unavailable"
                    )
                evidence = _spacy_evidence(
                    self._spacy_pipeline, request.source_text
                )
            if self._research_single_rule_schema:
                schema_name = SINGLE_RULE_RESEARCH_SCHEMA_NAME
                schema = single_rule_research_canonical_schema(
                    request.allowed_atom_vocabulary
                )
            else:
                schema_name = "semantic_roundtrip_canonical_ir_v1"
                schema = canonical_ir_schema(request.allowed_atom_vocabulary)
            self._model_calls += 1
            candidate = self._client.complete_json(
                system=_CONSTRUCTOR_SYSTEM,
                prompt=_constructor_prompt(request, evidence),
                schema_name=schema_name,
                schema=schema,
                max_tokens=CONSTRUCTOR_MAX_TOKENS,
            )
            canonical_ir = CanonicalRuleIR.from_dict(
                candidate, request.allowed_atom_vocabulary
            )
            if canonical_ir.is_empty:
                self._last_rejection_taxonomy = (
                    ModelRejectionTaxonomy.EMPTY_RULES
                )
                return ConstructorResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.EMPTY_L1,
                    failure_detail="Leanstral returned an empty canonical IR",
                )
            if (
                self._research_single_rule_schema
                and len(canonical_ir.rules) != 1
            ):
                self._last_rejection_taxonomy = ModelRejectionTaxonomy.SCHEMA
                return ConstructorResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail=(
                        "single-rule research schema requires exactly one rule"
                    ),
                )
            self._accepted_calls += 1
            self._last_rejection_taxonomy = None
            return ConstructorResult(
                status=ComponentStatus.SUCCESS,
                canonical_ir=canonical_ir,
            )
        except BaseException as exc:
            # KeyboardInterrupt/SystemExit must remain process control signals.
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            result, taxonomy = _failure_result(exc)
            self._last_rejection_taxonomy = taxonomy
            return result


__all__ = [
    "LEANSTRAL_CANONICAL_CONSTRUCTOR_INTERFACE",
    "LEANSTRAL_ROUND_TRIP_ADAPTERS_INTERFACE",
    "LEANSTRAL_PROVIDER_ID",
    "LEANSTRAL_ENDPOINT",
    "LEANSTRAL_MODEL",
    "CONSTRUCTOR_MAX_TOKENS",
    "SINGLE_RULE_RESEARCH_SCHEMA_NAME",
    "ModelRejectionTaxonomy",
    "classify_model_rejection",
    "classify_leanstral_exception",
    "LeanstralConstructorArm",
    "LeanstralClientError",
    "LeanstralTimeoutError",
    "LeanstralUnavailableError",
    "LeanstralMalformedResponseError",
    "LeanstralRequestError",
    "CompletionClient",
    "LeanstralClient",
    "canonical_ir_schema",
    "single_rule_research_canonical_schema",
    "LeanstralCanonicalConstructor",
]
