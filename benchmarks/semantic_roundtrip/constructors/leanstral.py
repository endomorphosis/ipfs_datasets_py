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
LEANSTRAL_PROVIDER_ID: Final = "leanstral-local"
LEANSTRAL_TIMEOUT_SECONDS: Final = 120.0
CONSTRUCTOR_MAX_TOKENS: Final = 3072
MAX_REQUEST_BYTES: Final = 64 * 1024
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
SINGLE_RULE_RESEARCH_SCHEMA_NAME: Final = (
    "research_single_rule_canonical_ir_v1"
)
STANDARD_CANONICAL_SCHEMA_NAME: Final = "semantic_roundtrip_canonical_ir_v1"

# Closed EVAL-004 rejection taxonomy shared with model-output recovery.
TYPED_MODEL_REJECTION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "blank",
        "schema",
        "polarity",
        "empty_rules",
        "timeout",
        "other",
    }
)

_CONSTRUCTOR_SYSTEM: Final = (
    "You are a deterministic legal semantic parser. Return one compact JSON "
    "object matching the supplied schema. Never explain, add keys, repeat a "
    "rule, or claim that generated logic is proved."
)


class LeanstralConstructorArm(str, Enum):
    """The two declared model-constructor arms."""

    DIRECT = "direct"
    SPACY_EVIDENCE = "spacy_evidence"


class LeanstralSchemaPath(str, Enum):
    """Standard production schema vs single-rule research path."""

    STANDARD = "standard"
    SINGLE_RULE_RESEARCH = "single_rule_research"


class ModelRejectionReason(str, Enum):
    """Typed rejection reason recorded for every model call (EVAL-004)."""

    BLANK = "blank"
    SCHEMA = "schema"
    POLARITY = "polarity"
    EMPTY_RULES = "empty_rules"
    TIMEOUT = "timeout"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class LeanstralModelCallDiagnostic:
    """Source-free record of the most recent adapter model call."""

    outcome: str
    rejection_reason: str | None
    failure_reason: FailureReason | None
    detail: str | None
    schema_name: str
    schema_path: str

    def __post_init__(self) -> None:
        if self.outcome not in {"accepted", "rejected", "call_failed"}:
            raise ContractError("model call outcome is invalid")
        if self.outcome == "accepted":
            if (
                self.rejection_reason is not None
                or self.failure_reason is not None
            ):
                raise ContractError(
                    "accepted model call cannot carry a rejection"
                )
        else:
            if self.failure_reason is None:
                raise ContractError("failed model call needs a typed failure")
            if (
                self.rejection_reason is None
                or self.rejection_reason not in TYPED_MODEL_REJECTION_REASONS
            ):
                raise ContractError(
                    "failed model call needs a typed rejection reason"
                )
        if not isinstance(self.schema_name, str) or not self.schema_name:
            raise ContractError("schema_name must be nonblank")
        if self.schema_path not in {
            LeanstralSchemaPath.STANDARD.value,
            LeanstralSchemaPath.SINGLE_RULE_RESEARCH.value,
        }:
            raise ContractError("schema_path is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "rejection_reason": self.rejection_reason,
            "failure_reason": (
                None
                if self.failure_reason is None
                else self.failure_reason.value
            ),
            "detail": self.detail,
            "schema_name": self.schema_name,
            "schema_path": self.schema_path,
        }


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
) -> dict[str, object]:
    """Build the fixed bounded schema with only case-visible atom enums."""

    qualifier_schema = {
        "type": "array",
        "maxItems": MAX_LIST_ITEMS,
        "items": {
            "type": "string",
            "maxLength": MAX_ATOM_LENGTH,
            "enum": list(vocabulary.qualifiers),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rules"],
        "properties": {
            "rules": {
                "type": "array",
                "maxItems": MAX_RULES,
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
        },
    }


def single_rule_research_ir_schema(
    vocabulary: AllowedAtomVocabulary,
) -> dict[str, object]:
    """Exactly-one-rule research schema for hybrid repair experiments.

    The promotion constructor continues to use :func:`canonical_ir_schema`.
    """

    schema = canonical_ir_schema(vocabulary)
    rules = schema["properties"]["rules"]  # type: ignore[index]
    rules["minItems"] = 1  # type: ignore[index]
    rules["maxItems"] = 1  # type: ignore[index]
    return schema


def rejection_reason_for_failure(
    failure_reason: FailureReason,
) -> ModelRejectionReason:
    """Map a terminal FailureReason onto the closed rejection taxonomy."""

    if failure_reason is FailureReason.BLANK_T1:
        return ModelRejectionReason.BLANK
    if failure_reason in {FailureReason.EMPTY_L1, FailureReason.EMPTY_L2}:
        return ModelRejectionReason.EMPTY_RULES
    if failure_reason is FailureReason.TIMEOUT:
        return ModelRejectionReason.TIMEOUT
    if failure_reason is FailureReason.INVALID_OUTPUT:
        return ModelRejectionReason.SCHEMA
    return ModelRejectionReason.OTHER


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


def _classify_constructor_failure(
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
        f"Leanstral constructor failed: {type(exc).__name__}",
        ModelRejectionReason.OTHER,
    )


def _failure_result(exc: BaseException) -> ConstructorResult:
    reason, detail, _rejection = _classify_constructor_failure(exc)
    return ConstructorResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail[:1000],
    )


class LeanstralCanonicalConstructor:
    """Canonical constructor with direct and declared full-spaCy arms."""

    interface: Final = LEANSTRAL_CANONICAL_CONSTRUCTOR_INTERFACE
    provider_id: Final = LEANSTRAL_PROVIDER_ID

    def __init__(
        self,
        client: CompletionClient | None = None,
        *,
        arm: LeanstralConstructorArm | str = LeanstralConstructorArm.DIRECT,
        spacy_pipeline: object | None = None,
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
            self._arm = LeanstralConstructorArm(arm)
        except ValueError as exc:
            raise ValueError(f"unsupported Leanstral constructor arm: {arm}") from exc
        try:
            self._schema_path = LeanstralSchemaPath(schema_path)
        except ValueError as exc:
            raise ValueError(
                f"unsupported Leanstral schema path: {schema_path}"
            ) from exc
        if (
            self._arm is LeanstralConstructorArm.DIRECT
            and spacy_pipeline is not None
        ):
            raise ValueError(
                "the direct Leanstral arm may not receive spaCy evidence"
            )
        self._spacy_pipeline = spacy_pipeline
        self._last_call: LeanstralModelCallDiagnostic | None = None

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{self._arm.value}:"
            f"{LEANSTRAL_ENDPOINT}:{LEANSTRAL_MODEL}:"
            f"schema_path={self._schema_path.value}"
        )

    @property
    def arm(self) -> LeanstralConstructorArm:
        return self._arm

    @property
    def schema_path(self) -> LeanstralSchemaPath:
        return self._schema_path

    @property
    def last_call(self) -> LeanstralModelCallDiagnostic | None:
        """Most recent model-call diagnostic with typed rejection reason."""

        return self._last_call

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        schema_name = (
            SINGLE_RULE_RESEARCH_SCHEMA_NAME
            if self._schema_path is LeanstralSchemaPath.SINGLE_RULE_RESEARCH
            else STANDARD_CANONICAL_SCHEMA_NAME
        )
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
            if self._schema_path is LeanstralSchemaPath.SINGLE_RULE_RESEARCH:
                schema = single_rule_research_ir_schema(
                    request.allowed_atom_vocabulary
                )
            else:
                schema = canonical_ir_schema(request.allowed_atom_vocabulary)
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
                detail = "Leanstral returned an empty canonical IR"
                self._last_call = LeanstralModelCallDiagnostic(
                    outcome="rejected",
                    rejection_reason=ModelRejectionReason.EMPTY_RULES.value,
                    failure_reason=FailureReason.EMPTY_L1,
                    detail=detail,
                    schema_name=schema_name,
                    schema_path=self._schema_path.value,
                )
                return ConstructorResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.EMPTY_L1,
                    failure_detail=detail,
                )
            if (
                self._schema_path is LeanstralSchemaPath.SINGLE_RULE_RESEARCH
                and len(canonical_ir.rules) != 1
            ):
                detail = (
                    "single-rule research schema requires exactly one rule"
                )
                self._last_call = LeanstralModelCallDiagnostic(
                    outcome="rejected",
                    rejection_reason=ModelRejectionReason.SCHEMA.value,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    detail=detail,
                    schema_name=schema_name,
                    schema_path=self._schema_path.value,
                )
                return ConstructorResult(
                    status=ComponentStatus.FAILED,
                    failure_reason=FailureReason.INVALID_OUTPUT,
                    failure_detail=detail,
                )
            self._last_call = LeanstralModelCallDiagnostic(
                outcome="accepted",
                rejection_reason=None,
                failure_reason=None,
                detail=None,
                schema_name=schema_name,
                schema_path=self._schema_path.value,
            )
            return ConstructorResult(
                status=ComponentStatus.SUCCESS,
                canonical_ir=canonical_ir,
            )
        except BaseException as exc:
            # KeyboardInterrupt/SystemExit must remain process control signals.
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            reason, detail, rejection = _classify_constructor_failure(exc)
            self._last_call = LeanstralModelCallDiagnostic(
                outcome="call_failed",
                rejection_reason=rejection.value,
                failure_reason=reason,
                detail=detail[:500],
                schema_name=schema_name,
                schema_path=self._schema_path.value,
            )
            return ConstructorResult(
                status=ComponentStatus.FAILED,
                failure_reason=reason,
                failure_detail=detail[:1000],
            )


__all__ = [
    "LEANSTRAL_CANONICAL_CONSTRUCTOR_INTERFACE",
    "LEANSTRAL_PROVIDER_ID",
    "LEANSTRAL_ENDPOINT",
    "LEANSTRAL_MODEL",
    "CONSTRUCTOR_MAX_TOKENS",
    "SINGLE_RULE_RESEARCH_SCHEMA_NAME",
    "STANDARD_CANONICAL_SCHEMA_NAME",
    "TYPED_MODEL_REJECTION_REASONS",
    "LeanstralConstructorArm",
    "LeanstralSchemaPath",
    "ModelRejectionReason",
    "LeanstralModelCallDiagnostic",
    "LeanstralClientError",
    "LeanstralTimeoutError",
    "LeanstralUnavailableError",
    "LeanstralMalformedResponseError",
    "LeanstralRequestError",
    "CompletionClient",
    "LeanstralClient",
    "canonical_ir_schema",
    "single_rule_research_ir_schema",
    "rejection_reason_for_failure",
    "LeanstralCanonicalConstructor",
]
