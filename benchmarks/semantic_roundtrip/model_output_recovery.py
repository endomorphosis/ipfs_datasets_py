"""Bounded model-output recovery for the SRT-023 replacement experiment.

This module is deliberately additive.  It does not alter the frozen SRT-014
adapters or their results.  Instead, it provides a strict wrapper for a new
experiment over the same direct and SyMAI routes to the same one-slot
Leanstral service.

The wrapper is fail closed:

* L1 and L2 must be nonempty canonical IR objects;
* T1 is a bounded list of one explicitly polarised realization per input rule;
* an output is never repaired locally, recovered from source, or borrowed from
  another call;
* only the single retry declared by :class:`RecoveryPolicy` is possible; and
* every provider call, rejection, retry, and terminal typed failure is retained
  in a source-free receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Protocol

from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ContractError,
    FailureReason,
    RealizerRequest,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    CONSTRUCTOR_MAX_TOKENS,
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    CompletionClient,
    LeanstralMalformedResponseError,
    LeanstralRequestError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
    _constructor_prompt,
    canonical_ir_schema,
)
from benchmarks.semantic_roundtrip.constructors.symai import (
    SYMAI_ROUTE,
    SyMAICompletionClient,
    SyMAIMalformedResponseError,
    SyMAIRouteError,
    _complete_symai_json,
)
from benchmarks.semantic_roundtrip.realizers.leanstral import (
    REALIZATION_MAX_LENGTH,
    REALIZER_MAX_TOKENS,
    _realizer_prompt,
)
from benchmarks.semantic_roundtrip_capabilities import (
    LEANSTRAL_BACKEND,
    LEANSTRAL_BACKEND_OWNER,
    LEANSTRAL_CAPACITY,
    LEANSTRAL_PROVIDER,
)


BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE: Final = (
    "BoundedModelOutputRecovery@1"
)
SYMAI_POLARITY_CONTRACT_INTERFACE: Final = "SyMAIPolarityContract@1"
MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION: Final = (
    "ipfs-datasets.semantic-roundtrip-model-output-recovery.v1"
)

DIRECT_ROUTE_ID: Final = "direct_openai_compatible_http"
# The tokenizer is embedded in the exact frozen GGUF.  Binding its observed
# vocabulary metadata avoids pretending that a separate, substitutable
# Hugging Face tokenizer is involved.
LEANSTRAL_TOKENIZER_IDENTITY: Final = (
    f"{LEANSTRAL_MODEL}#embedded-gguf-tokenizer:"
    "vocab_type=2:n_vocab=131072"
)

_POLARITY_LABELS: Final = {
    "O": "obligation",
    "P": "permission",
    "F": "prohibition",
}
_RETRYABLE_REJECTIONS: Final = frozenset(
    {
        "blank_output",
        "empty_output",
        "malformed_output",
        "polarity_ambiguous",
    }
)
_RETRY_SYSTEM_SUFFIX: Final = (
    " This is the sole preregistered correction attempt. Return a fresh object "
    "for the same input and schema; do not quote, recover, or request source "
    "material and do not change route, model, or decoding settings."
)
_RETRY_PROMPT_SUFFIX: Final = (
    "\nPREREGISTERED_RETRY_REASON:{reason}\n"
    "Correct only that contract violation. All original instructions remain "
    "binding."
)


class RecoveryRole(str, Enum):
    """The three model-output positions in a semantic round trip."""

    L1 = "l1"
    T1 = "t1"
    L2 = "l2"


class RecoveryRoute(str, Enum):
    """The two preregistered paths to the one physical Leanstral service."""

    DIRECT = "direct"
    SYMAI = "symai"

    @property
    def route_id(self) -> str:
        return (
            DIRECT_ROUTE_ID
            if self is RecoveryRoute.DIRECT
            else SYMAI_ROUTE
        )


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """Outcome-independent retry policy fixed before an experiment starts."""

    replacement_experiment_id: str
    max_retries: int = 1
    retryable_rejections: tuple[str, ...] = tuple(
        sorted(_RETRYABLE_REJECTIONS)
    )

    def __post_init__(self) -> None:
        experiment_id = self.replacement_experiment_id
        if (
            not isinstance(experiment_id, str)
            or not experiment_id.strip()
            or len(experiment_id) > 160
        ):
            raise ContractError(
                "replacement_experiment_id must be a bounded nonblank string"
            )
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries not in {0, 1}
        ):
            raise ContractError(
                "model-output recovery permits at most one retry"
            )
        retryable = self.retryable_rejections
        if (
            not isinstance(retryable, Sequence)
            or isinstance(retryable, (str, bytes, bytearray))
            or len(set(retryable)) != len(retryable)
            or any(item not in _RETRYABLE_REJECTIONS for item in retryable)
        ):
            raise ContractError(
                "retryable_rejections must be a unique bounded preregistration"
            )
        if self.max_retries and not experiment_id.strip().startswith(
            "srt-023-replacement-"
        ):
            raise ContractError(
                "a retry is permitted only inside the SRT-023 replacement "
                "experiment namespace"
            )
        object.__setattr__(
            self, "replacement_experiment_id", experiment_id.strip()
        )
        object.__setattr__(self, "retryable_rejections", tuple(retryable))

    def permits(self, rejection: str) -> bool:
        return (
            self.max_retries == 1
            and rejection in self.retryable_rejections
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "replacement_experiment_id": self.replacement_experiment_id,
            "max_attempts": self.max_retries + 1,
            "max_retries": self.max_retries,
            "retryable_rejections": list(self.retryable_rejections),
            "outcome_adaptive_extension_allowed": False,
        }


PREREGISTERED_SRT023_POLICY: Final = RecoveryPolicy(
    replacement_experiment_id="srt-023-replacement-model-remediation-v1"
)


@dataclass(frozen=True, slots=True)
class ModelCallReceipt:
    """A source-free record of one physical model call."""

    call_number: int
    serialized_call_ordinal: int
    attempt_kind: str
    role: RecoveryRole
    route: RecoveryRoute
    request_sha256: str
    prompt_sha256: str
    schema_name: str
    max_tokens: int
    outcome: str
    rejection: str | None = None
    failure_reason: FailureReason | None = None
    detail: str | None = None
    symai_route_receipt: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.call_number < 1 or self.serialized_call_ordinal < 1:
            raise ContractError("model call ordinals must be positive")
        for field, digest in (
            ("request_sha256", self.request_sha256),
            ("prompt_sha256", self.prompt_sha256),
        ):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ContractError(f"model call {field} is invalid")
        if (
            not isinstance(self.schema_name, str)
            or not self.schema_name.startswith("srt023_replacement_")
            or self.max_tokens not in {
                CONSTRUCTOR_MAX_TOKENS,
                REALIZER_MAX_TOKENS,
            }
        ):
            raise ContractError("model call schema or token bound is invalid")
        if self.attempt_kind not in {"initial", "preregistered_retry"}:
            raise ContractError("model call attempt kind is invalid")
        if self.outcome not in {"accepted", "rejected", "call_failed"}:
            raise ContractError("model call outcome is invalid")
        if self.outcome == "accepted" and (
            self.rejection is not None or self.failure_reason is not None
        ):
            raise ContractError("accepted model call cannot carry a failure")
        if self.outcome != "accepted" and self.failure_reason is None:
            raise ContractError("failed model call needs a typed failure")
        if self.symai_route_receipt is not None:
            object.__setattr__(
                self,
                "symai_route_receipt",
                _freeze_json(self.symai_route_receipt),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "call_number": self.call_number,
            "serialized_call_ordinal": self.serialized_call_ordinal,
            "attempt_kind": self.attempt_kind,
            "role": self.role.value,
            "route": self.route.value,
            "route_id": self.route.route_id,
            "request_sha256": self.request_sha256,
            "prompt_sha256": self.prompt_sha256,
            "schema_name": self.schema_name,
            "max_tokens": self.max_tokens,
            "cache": {
                "prompt_cache_enabled": False,
                "response_cache_enabled": False,
                "cache_hit": False,
                "result_reused": False,
            },
            "outcome": self.outcome,
            "rejection": self.rejection,
            "failure_reason": (
                None
                if self.failure_reason is None
                else self.failure_reason.value
            ),
            "detail": self.detail,
            "symai_route_receipt": (
                None
                if self.symai_route_receipt is None
                else _thaw_json(self.symai_route_receipt)
            ),
        }


@dataclass(frozen=True, slots=True)
class ModelOutputRecoveryReceipt:
    """Complete evidence for one recovery invocation."""

    role: RecoveryRole
    route: RecoveryRoute
    request_sha256: str
    policy: RecoveryPolicy
    calls: tuple[ModelCallReceipt, ...]
    status: ComponentStatus
    terminal_failure: FailureReason | None
    terminal_rejection: str | None

    def __post_init__(self) -> None:
        if not self.calls:
            raise ContractError("a recovery receipt must retain a model call")
        if len(self.calls) > self.policy.max_retries + 1:
            raise ContractError("receipt exceeds the preregistered call bound")
        if any(
            call.call_number != index
            or call.role is not self.role
            or call.route is not self.route
            or call.request_sha256 != self.request_sha256
            for index, call in enumerate(self.calls, start=1)
        ):
            raise ContractError("recovery call lineage is inconsistent")
        if any(
            call.attempt_kind
            != ("initial" if index == 1 else "preregistered_retry")
            for index, call in enumerate(self.calls, start=1)
        ):
            raise ContractError("recovery retry lineage is inconsistent")
        if self.status is ComponentStatus.SUCCESS:
            if (
                self.terminal_failure is not None
                or self.terminal_rejection is not None
                or self.calls[-1].outcome != "accepted"
            ):
                raise ContractError("successful recovery receipt is inconsistent")
        elif self.terminal_failure is None:
            raise ContractError("failed recovery receipt needs a typed failure")

    @property
    def rejections(self) -> tuple[ModelCallReceipt, ...]:
        return tuple(call for call in self.calls if call.outcome != "accepted")

    @property
    def retries(self) -> int:
        return max(0, len(self.calls) - 1)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION,
            "interface": BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE,
            "polarity_interface": SYMAI_POLARITY_CONTRACT_INTERFACE,
            "role": self.role.value,
            "identity": {
                "provider": LEANSTRAL_PROVIDER,
                "endpoint": LEANSTRAL_ENDPOINT,
                "backend": LEANSTRAL_BACKEND,
                "backend_owner": LEANSTRAL_BACKEND_OWNER,
                "model": LEANSTRAL_MODEL,
                "tokenizer": LEANSTRAL_TOKENIZER_IDENTITY,
                "route": self.route.value,
                "route_id": self.route.route_id,
                "direct_and_symai_are_independent_models": False,
                "physical_model_slots": LEANSTRAL_CAPACITY,
                "execution": "globally_serialized_one_slot",
            },
            "boundary": {
                "source_withheld": self.role is RecoveryRole.T1,
                "source_recovery_allowed": False,
                "fallback_allowed": False,
                "route_substitution_allowed": False,
                "cross_call_result_reuse_allowed": False,
            },
            "cache": {
                "prompt_cache_enabled": False,
                "response_cache_enabled": False,
                "cache_hit": False,
            },
            "request_sha256": self.request_sha256,
            "policy": self.policy.to_dict(),
            "calls": [call.to_dict() for call in self.calls],
            "call_count": len(self.calls),
            "rejection_count": len(self.rejections),
            "retry_count": self.retries,
            "status": self.status.value,
            "terminal_failure": (
                None
                if self.terminal_failure is None
                else self.terminal_failure.value
            ),
            "terminal_rejection": self.terminal_rejection,
        }


@dataclass(frozen=True, slots=True)
class ModelOutputRecoveryResult:
    """Typed value or typed terminal failure from the recovery wrapper."""

    role: RecoveryRole
    status: ComponentStatus
    receipt: ModelOutputRecoveryReceipt
    canonical_ir: CanonicalRuleIR | None = None
    text: str | None = None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if self.status is ComponentStatus.SUCCESS:
            expected_ir = self.role in {RecoveryRole.L1, RecoveryRole.L2}
            if expected_ir != (self.canonical_ir is not None):
                raise ContractError("successful recovery value has wrong role")
            if (self.role is RecoveryRole.T1) != (self.text is not None):
                raise ContractError("successful recovery text has wrong role")
            if self.failure_reason is not None:
                raise ContractError("successful recovery cannot carry failure")
        elif self.failure_reason is None:
            raise ContractError("failed recovery result needs typed failure")


class _Client(Protocol):
    endpoint: str
    model: str


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_json(value: Mapping[str, object]) -> Mapping[str, object]:
    def freeze(item: object) -> object:
        if isinstance(item, Mapping):
            return MappingProxyType(
                {str(key): freeze(nested) for key, nested in item.items()}
            )
        if isinstance(item, (tuple, list)):
            return tuple(freeze(nested) for nested in item)
        return item

    return freeze(dict(value))  # type: ignore[return-value]


class _OutputRejected(ContractError):
    def __init__(
        self,
        rejection: str,
        failure_reason: FailureReason,
        detail: str,
    ) -> None:
        super().__init__(detail)
        self.rejection = rejection
        self.failure_reason = failure_reason
        self.detail = detail


class SyMAIPolarityContract:
    """Strict, role-aware O/P/F schema and output validator.

    The historical name is retained because the modal-plus-SyMAI path exposed
    the motivating failure.  The same contract is intentionally applied to
    the direct route so orchestration is the only route difference.
    """

    interface: Final = SYMAI_POLARITY_CONTRACT_INTERFACE

    _POSITIVE_OBLIGATION = re.compile(
        r"\b(?:must|shall)(?!\s+not\b)|\b(?:is|are)\s+required\s+to\b",
        re.IGNORECASE,
    )
    _PERMISSION = re.compile(
        r"\bmay(?!\s+not\b)|\b(?:is|are)\s+(?:permitted|allowed)\s+to\b",
        re.IGNORECASE,
    )
    _PROHIBITION = re.compile(
        r"\b(?:must|shall)\s+not\b|"
        r"\b(?:is|are)\s+(?:prohibited|forbidden)\s+from\b",
        re.IGNORECASE,
    )
    _AMBIGUOUS_MAY_NOT = re.compile(r"\bmay\s+not\b", re.IGNORECASE)

    @classmethod
    def instructions(cls, role: RecoveryRole) -> str:
        common = (
            "Polarity is mandatory and exclusive: O means obligation "
            "(must/shall), P means permission (may/is permitted to), and F "
            "means prohibition (must not/shall not/is prohibited from). Never "
            "use 'may not', because it is polarity-ambiguous. Never map one "
            "symbol to another or omit a supplied modality."
        )
        if role is RecoveryRole.T1:
            return (
                common
                + " Return exactly one indexed rule object for each input "
                "rule, repeat its unchanged O/P/F modality and matching "
                "polarity label, and use one explicit matching modal phrase "
                "in that rule's text."
            )
        return (
            common
            + " Every canonical rule must contain exactly one modality symbol "
            "from the enum O, P, F."
        )

    @classmethod
    def canonical_schema(
        cls,
        vocabulary: AllowedAtomVocabulary,
    ) -> dict[str, object]:
        schema = canonical_ir_schema(vocabulary)
        rules = schema["properties"]["rules"]  # type: ignore[index]
        rules["minItems"] = 1  # type: ignore[index]
        return schema

    @classmethod
    def realization_schema(
        cls,
        canonical_ir: CanonicalRuleIR,
    ) -> dict[str, object]:
        count = len(canonical_ir.rules)
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["rules"],
            "properties": {
                "rules": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "index",
                            "modality",
                            "polarity",
                            "text",
                        ],
                        "properties": {
                            "index": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": max(0, count - 1),
                            },
                            "modality": {
                                "type": "string",
                                "enum": ["O", "P", "F"],
                            },
                            "polarity": {
                                "type": "string",
                                "enum": [
                                    "obligation",
                                    "permission",
                                    "prohibition",
                                ],
                            },
                            "text": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": REALIZATION_MAX_LENGTH,
                            },
                        },
                    },
                }
            },
        }

    @classmethod
    def validate_canonical(
        cls,
        candidate: object,
        vocabulary: AllowedAtomVocabulary,
        *,
        role: RecoveryRole,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> CanonicalRuleIR:
        if role not in {RecoveryRole.L1, RecoveryRole.L2}:
            raise ContractError("canonical validation requires L1 or L2")
        try:
            canonical_ir = CanonicalRuleIR.from_dict(candidate, vocabulary)
        except (ContractError, TypeError, ValueError) as exc:
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                f"{role.value.upper()} is not bounded canonical IR",
            ) from exc
        if canonical_ir.is_empty:
            reason = (
                FailureReason.EMPTY_L1
                if role is RecoveryRole.L1
                else FailureReason.EMPTY_L2
            )
            raise _OutputRejected(
                "empty_output",
                reason,
                f"{role.value.upper()} canonical rules are empty",
            )
        if expected_ir is not None:
            expected = Counter(rule.modality for rule in expected_ir.rules)
            observed = Counter(rule.modality for rule in canonical_ir.rules)
            if observed != expected:
                raise _OutputRejected(
                    "polarity_ambiguous",
                    FailureReason.INVALID_OUTPUT,
                    (
                        f"{role.value.upper()} O/P/F multiplicities do not "
                        "preserve the preregistered input IR"
                    ),
                )
        return canonical_ir

    @classmethod
    def validate_realization(
        cls,
        candidate: object,
        canonical_ir: CanonicalRuleIR,
    ) -> str:
        if not isinstance(candidate, Mapping) or set(candidate) != {"rules"}:
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "T1 must contain exactly the rules key",
            )
        raw_rules = candidate["rules"]
        if (
            not isinstance(raw_rules, Sequence)
            or isinstance(raw_rules, (str, bytes, bytearray))
        ):
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "T1 rules must be an array",
            )
        if not raw_rules:
            raise _OutputRejected(
                "blank_output",
                FailureReason.BLANK_T1,
                "T1 realization is blank",
            )
        if len(raw_rules) != len(canonical_ir.rules):
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "T1 must realize every and only the input rules",
            )

        realized: list[str] = []
        for index, (raw, expected) in enumerate(
            zip(raw_rules, canonical_ir.rules, strict=True)
        ):
            if not isinstance(raw, Mapping) or set(raw) != {
                "index",
                "modality",
                "polarity",
                "text",
            }:
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} has malformed fields",
                )
            if type(raw["index"]) is not int or raw["index"] != index:
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} has a noncanonical index",
                )
            modality = raw["modality"]
            label = raw["polarity"]
            if (
                modality != expected.modality
                or label != _POLARITY_LABELS[expected.modality]
            ):
                raise _OutputRejected(
                    "polarity_ambiguous",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} changed or ambiguously labelled polarity",
                )
            text = raw["text"]
            if not isinstance(text, str):
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} text must be a string",
                )
            text = " ".join(text.strip().split())
            if not text:
                raise _OutputRejected(
                    "blank_output",
                    FailureReason.BLANK_T1,
                    f"T1 rule {index} text is blank",
                )
            if len(text) > REALIZATION_MAX_LENGTH:
                raise _OutputRejected(
                    "malformed_output",
                    FailureReason.INVALID_OUTPUT,
                    f"T1 rule {index} exceeds the character bound",
                )
            cls._validate_text_polarity(text, expected.modality, index)
            realized.append(text)
        combined = " ".join(realized)
        if len(combined) > REALIZATION_MAX_LENGTH:
            raise _OutputRejected(
                "malformed_output",
                FailureReason.INVALID_OUTPUT,
                "combined T1 realization exceeds the character bound",
            )
        return combined

    @classmethod
    def _validate_text_polarity(
        cls,
        text: str,
        expected: str,
        index: int,
    ) -> None:
        if cls._AMBIGUOUS_MAY_NOT.search(text):
            raise _OutputRejected(
                "polarity_ambiguous",
                FailureReason.INVALID_OUTPUT,
                f"T1 rule {index} uses ambiguous 'may not' polarity",
            )
        observed = {
            modality
            for modality, pattern in (
                ("O", cls._POSITIVE_OBLIGATION),
                ("P", cls._PERMISSION),
                ("F", cls._PROHIBITION),
            )
            if pattern.search(text)
        }
        if observed != {expected}:
            raise _OutputRejected(
                "polarity_ambiguous",
                FailureReason.INVALID_OUTPUT,
                (
                    f"T1 rule {index} must contain exactly one explicit "
                    f"{expected} polarity construction"
                ),
            )


_SERIALIZATION_LOCK = threading.Lock()
_ORDINAL_LOCK = threading.Lock()
_NEXT_SERIALIZED_CALL = 0


def _next_ordinal() -> int:
    global _NEXT_SERIALIZED_CALL
    with _ORDINAL_LOCK:
        _NEXT_SERIALIZED_CALL += 1
        return _NEXT_SERIALIZED_CALL


class BoundedModelOutputRecovery:
    """Replacement-experiment wrapper around one pinned Leanstral route."""

    interface: Final = BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE
    provider_id: Final = "leanstral-local"

    def __init__(
        self,
        client: CompletionClient | SyMAICompletionClient,
        *,
        route: RecoveryRoute | str,
        policy: RecoveryPolicy = PREREGISTERED_SRT023_POLICY,
    ) -> None:
        if not isinstance(policy, RecoveryPolicy):
            raise TypeError("policy must be RecoveryPolicy")
        try:
            self._route = RecoveryRoute(route)
        except ValueError as exc:
            raise ContractError(
                "route must be exactly direct or symai"
            ) from exc
        self._validate_client_identity(client)
        self._client = client
        self._policy = policy
        self._last_receipt: ModelOutputRecoveryReceipt | None = None

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{self._route.route_id}:"
            f"{LEANSTRAL_ENDPOINT}:{LEANSTRAL_BACKEND}:{LEANSTRAL_MODEL}:"
            f"{LEANSTRAL_TOKENIZER_IDENTITY}:slots={LEANSTRAL_CAPACITY}:"
            "cache=disabled:fallback=forbidden"
        )

    @property
    def route(self) -> RecoveryRoute:
        return self._route

    @property
    def policy(self) -> RecoveryPolicy:
        return self._policy

    @property
    def last_receipt(self) -> ModelOutputRecoveryReceipt | None:
        return self._last_receipt

    def recover_l1(
        self,
        request: ConstructorRequest,
        *,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> ModelOutputRecoveryResult:
        return self.recover(
            RecoveryRole.L1, request, expected_ir=expected_ir
        )

    def recover_t1(
        self,
        request: RealizerRequest,
    ) -> ModelOutputRecoveryResult:
        return self.recover(RecoveryRole.T1, request)

    def recover_l2(
        self,
        request: ConstructorRequest,
        *,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> ModelOutputRecoveryResult:
        return self.recover(
            RecoveryRole.L2, request, expected_ir=expected_ir
        )

    def recover(
        self,
        role: RecoveryRole | str,
        request: ConstructorRequest | RealizerRequest,
        *,
        expected_ir: CanonicalRuleIR | None = None,
    ) -> ModelOutputRecoveryResult:
        """Invoke the fixed route and apply the preregistered recovery policy."""

        try:
            parsed_role = RecoveryRole(role)
        except ValueError as exc:
            raise ContractError("role must be exactly l1, t1, or l2") from exc
        self._validate_request(parsed_role, request, expected_ir)
        system, prompt, schema_name, schema, max_tokens = self._call_contract(
            parsed_role, request
        )
        request_sha256 = self._request_digest(parsed_role, request)
        calls: list[ModelCallReceipt] = []
        terminal_failure: FailureReason | None = None
        terminal_rejection: str | None = None
        failure_detail: str | None = None

        for call_index in range(1, self._policy.max_retries + 2):
            is_retry = call_index > 1
            call_system = system
            call_prompt = prompt
            if is_retry:
                # The retry uses only the preregistered rejection class.  It
                # never includes rejected output or source-bearing state.
                call_system += _RETRY_SYSTEM_SUFFIX
                call_prompt += _RETRY_PROMPT_SUFFIX.format(
                    reason=terminal_rejection
                )
            try:
                candidate, route_receipt, ordinal = self._invoke(
                    system=call_system,
                    prompt=call_prompt,
                    schema_name=schema_name,
                    schema=schema,
                    max_tokens=max_tokens,
                )
                if parsed_role is RecoveryRole.T1:
                    assert isinstance(request, RealizerRequest)
                    value = SyMAIPolarityContract.validate_realization(
                        candidate, request.canonical_ir
                    )
                else:
                    assert isinstance(request, ConstructorRequest)
                    value = SyMAIPolarityContract.validate_canonical(
                        candidate,
                        request.allowed_atom_vocabulary,
                        role=parsed_role,
                        expected_ir=expected_ir,
                    )
                calls.append(
                    self._call_receipt(
                        call_index=call_index,
                        ordinal=ordinal,
                        role=parsed_role,
                        request_sha256=request_sha256,
                        prompt=call_prompt,
                        schema_name=schema_name,
                        max_tokens=max_tokens,
                        outcome="accepted",
                        route_receipt=route_receipt,
                    )
                )
                receipt = ModelOutputRecoveryReceipt(
                    role=parsed_role,
                    route=self._route,
                    request_sha256=request_sha256,
                    policy=self._policy,
                    calls=tuple(calls),
                    status=ComponentStatus.SUCCESS,
                    terminal_failure=None,
                    terminal_rejection=None,
                )
                self._last_receipt = receipt
                if parsed_role is RecoveryRole.T1:
                    assert isinstance(value, str)
                    return ModelOutputRecoveryResult(
                        role=parsed_role,
                        status=ComponentStatus.SUCCESS,
                        text=value,
                        receipt=receipt,
                    )
                assert isinstance(value, CanonicalRuleIR)
                return ModelOutputRecoveryResult(
                    role=parsed_role,
                    status=ComponentStatus.SUCCESS,
                    canonical_ir=value,
                    receipt=receipt,
                )
            except _OutputRejected as exc:
                ordinal = locals().get("ordinal")
                if not isinstance(ordinal, int):
                    raise AssertionError("model rejection has no call ordinal")
                terminal_failure = exc.failure_reason
                terminal_rejection = exc.rejection
                failure_detail = exc.detail
                calls.append(
                    self._call_receipt(
                        call_index=call_index,
                        ordinal=ordinal,
                        role=parsed_role,
                        request_sha256=request_sha256,
                        prompt=call_prompt,
                        schema_name=schema_name,
                        max_tokens=max_tokens,
                        outcome="rejected",
                        rejection=exc.rejection,
                        failure_reason=exc.failure_reason,
                        detail=exc.detail,
                        route_receipt=locals().get("route_receipt"),
                    )
                )
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                ordinal = getattr(exc, "_srt023_call_ordinal", None)
                if not isinstance(ordinal, int):
                    raise AssertionError("model call failure has no ordinal")
                (
                    terminal_failure,
                    terminal_rejection,
                    failure_detail,
                    retryable,
                ) = self._classify_call_failure(exc)
                calls.append(
                    self._call_receipt(
                        call_index=call_index,
                        ordinal=ordinal,
                        role=parsed_role,
                        request_sha256=request_sha256,
                        prompt=call_prompt,
                        schema_name=schema_name,
                        max_tokens=max_tokens,
                        outcome="call_failed",
                        rejection=terminal_rejection,
                        failure_reason=terminal_failure,
                        detail=failure_detail,
                    )
                )
                if not retryable:
                    break

            assert terminal_rejection is not None
            if (
                call_index > self._policy.max_retries
                or not self._policy.permits(terminal_rejection)
            ):
                break

        assert terminal_failure is not None
        if len(calls) > 1:
            terminal_failure = FailureReason.RETRY_EXHAUSTED
            failure_detail = (
                "preregistered model-output recovery retry exhausted after "
                f"{terminal_rejection}"
            )
        receipt = ModelOutputRecoveryReceipt(
            role=parsed_role,
            route=self._route,
            request_sha256=request_sha256,
            policy=self._policy,
            calls=tuple(calls),
            status=ComponentStatus.FAILED,
            terminal_failure=terminal_failure,
            terminal_rejection=terminal_rejection,
        )
        self._last_receipt = receipt
        return ModelOutputRecoveryResult(
            role=parsed_role,
            status=ComponentStatus.FAILED,
            receipt=receipt,
            failure_reason=terminal_failure,
            failure_detail=failure_detail,
        )

    def _invoke(
        self,
        *,
        system: str,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> tuple[Mapping[str, object], Mapping[str, object] | None, int]:
        with _SERIALIZATION_LOCK:
            ordinal = _next_ordinal()
            try:
                if self._route is RecoveryRoute.DIRECT:
                    candidate = self._client.complete_json(  # type: ignore[union-attr]
                        system=system,
                        prompt=prompt,
                        schema_name=schema_name,
                        schema=schema,
                        max_tokens=max_tokens,
                    )
                    if not isinstance(candidate, Mapping):
                        raise LeanstralMalformedResponseError(
                            "direct Leanstral output must be one JSON object"
                        )
                    return candidate, None, ordinal
                candidate, symai_receipt = _complete_symai_json(
                    self._client,  # type: ignore[arg-type]
                    system=system,
                    prompt=prompt,
                    schema_name=schema_name,
                    schema=schema,
                    max_tokens=max_tokens,
                )
                return candidate, symai_receipt.to_dict(), ordinal
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                try:
                    setattr(exc, "_srt023_call_ordinal", ordinal)
                except Exception:
                    wrapped = RuntimeError(
                        f"model call raised {type(exc).__name__}"
                    )
                    setattr(wrapped, "_srt023_call_ordinal", ordinal)
                    raise wrapped from exc
                raise

    def _call_contract(
        self,
        role: RecoveryRole,
        request: ConstructorRequest | RealizerRequest,
    ) -> tuple[
        str,
        str,
        str,
        Mapping[str, object],
        int,
    ]:
        polarity = SyMAIPolarityContract.instructions(role)
        if role is RecoveryRole.T1:
            assert isinstance(request, RealizerRequest)
            system = (
                "You are a source-withheld formal-logic realizer. The supplied "
                "canonical IR is your only semantic authority. Return one "
                "compact JSON object matching the supplied schema. "
                + polarity
            )
            prompt = (
                _realizer_prompt(request)
                + "\nOUTPUT_SHAPE: Return only the indexed rules array "
                "required by the schema; do not add combined text or metadata."
            )
            return (
                system,
                prompt,
                "srt023_replacement_t1_realization_v1",
                SyMAIPolarityContract.realization_schema(
                    request.canonical_ir
                ),
                REALIZER_MAX_TOKENS,
            )

        assert isinstance(request, ConstructorRequest)
        system = (
            "You are a deterministic legal semantic parser. Return one "
            "compact JSON object matching the supplied schema. Never explain, "
            "add keys, repeat a rule, or claim generated logic is proved. "
            + polarity
        )
        return (
            system,
            _constructor_prompt(request, None),
            f"srt023_replacement_{role.value}_canonical_ir_v1",
            SyMAIPolarityContract.canonical_schema(
                request.allowed_atom_vocabulary
            ),
            CONSTRUCTOR_MAX_TOKENS,
        )

    def _request_digest(
        self,
        role: RecoveryRole,
        request: ConstructorRequest | RealizerRequest,
    ) -> str:
        if role is RecoveryRole.T1:
            assert isinstance(request, RealizerRequest)
            # Hash only the exact source-withheld material actually supplied.
            value: object = {
                "role": role.value,
                "canonical_ir": request.canonical_ir.to_dict(),
                "allowed_atom_vocabulary": (
                    request.allowed_atom_vocabulary.to_dict()
                ),
            }
        else:
            assert isinstance(request, ConstructorRequest)
            # Config is intentionally excluded because model prompts never use
            # it; hashing it could retain a hidden source-bearing dependency.
            value = {
                "role": role.value,
                "source_text": request.source_text,
                "allowed_atom_vocabulary": (
                    request.allowed_atom_vocabulary.to_dict()
                ),
            }
        return _sha256(_canonical_json(value))

    def _call_receipt(
        self,
        *,
        call_index: int,
        ordinal: int,
        role: RecoveryRole,
        request_sha256: str,
        prompt: str,
        schema_name: str,
        max_tokens: int,
        outcome: str,
        rejection: str | None = None,
        failure_reason: FailureReason | None = None,
        detail: str | None = None,
        route_receipt: object = None,
    ) -> ModelCallReceipt:
        bounded_route_receipt = (
            route_receipt if isinstance(route_receipt, Mapping) else None
        )
        return ModelCallReceipt(
            call_number=call_index,
            serialized_call_ordinal=ordinal,
            attempt_kind=(
                "initial" if call_index == 1 else "preregistered_retry"
            ),
            role=role,
            route=self._route,
            request_sha256=request_sha256,
            prompt_sha256=_sha256(prompt),
            schema_name=schema_name,
            max_tokens=max_tokens,
            outcome=outcome,
            rejection=rejection,
            failure_reason=failure_reason,
            detail=None if detail is None else detail[:500],
            symai_route_receipt=bounded_route_receipt,
        )

    def _classify_call_failure(
        self, exc: BaseException
    ) -> tuple[FailureReason, str, str, bool]:
        if isinstance(
            exc, (LeanstralTimeoutError, TimeoutError, socket.timeout)
        ):
            return (
                FailureReason.TIMEOUT,
                "call_timeout",
                "pinned Leanstral call timed out",
                False,
            )
        if isinstance(exc, (SyMAIRouteError, LeanstralUnavailableError)):
            return (
                FailureReason.CAPABILITY_UNAVAILABLE,
                "route_contract_failure",
                "pinned model route was unavailable or drifted",
                False,
            )
        if isinstance(
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
            return (
                FailureReason.INVALID_OUTPUT,
                "malformed_output",
                "model call returned malformed output",
                True,
            )
        return (
            FailureReason.EXCEPTION,
            "call_exception",
            f"pinned model call failed with {type(exc).__name__}",
            False,
        )

    def _validate_client_identity(self, client: _Client) -> None:
        if (
            not hasattr(client, "complete_json")
            or getattr(client, "endpoint", "").rstrip("/")
            != LEANSTRAL_ENDPOINT
            or getattr(client, "model", None) != LEANSTRAL_MODEL
        ):
            raise ContractError(
                "client must bind the exact frozen Leanstral endpoint/model"
            )
        optional_exact = {
            "backend": LEANSTRAL_BACKEND,
            "backend_owner": LEANSTRAL_BACKEND_OWNER,
            "tokenizer": LEANSTRAL_TOKENIZER_IDENTITY,
            "tokenizer_identity": LEANSTRAL_TOKENIZER_IDENTITY,
            "capacity": LEANSTRAL_CAPACITY,
            "parallel_slots": LEANSTRAL_CAPACITY,
        }
        for field, frozen in optional_exact.items():
            if hasattr(client, field) and getattr(client, field) != frozen:
                raise ContractError(
                    f"client {field} drifted from the frozen identity"
                )
        for field in ("cache_enabled", "cache_prompt"):
            if hasattr(client, field) and getattr(client, field) is not False:
                raise ContractError(
                    "client must preserve the disabled-cache identity"
                )
        if hasattr(client, "route"):
            route = getattr(client, "route")
            allowed = {
                self._route.value,
                self._route.route_id,
            }
            if route not in allowed:
                raise ContractError(
                    "client route drifted from the preregistered route"
                )

    def _validate_request(
        self,
        role: RecoveryRole,
        request: ConstructorRequest | RealizerRequest,
        expected_ir: CanonicalRuleIR | None,
    ) -> None:
        if role is RecoveryRole.T1:
            if not isinstance(request, RealizerRequest):
                raise TypeError("T1 recovery requires RealizerRequest")
            if expected_ir is not None:
                raise ContractError(
                    "T1 polarity authority is the request canonical IR"
                )
            if request.canonical_ir.is_empty:
                raise ContractError(
                    "T1 recovery requires nonempty canonical IR"
                )
            return
        if not isinstance(request, ConstructorRequest):
            raise TypeError("L1/L2 recovery requires ConstructorRequest")
        if expected_ir is not None:
            if not isinstance(expected_ir, CanonicalRuleIR):
                raise TypeError("expected_ir must be CanonicalRuleIR")
            expected_ir.validate_vocabulary(
                request.allowed_atom_vocabulary
            )


__all__ = [
    "BOUNDED_MODEL_OUTPUT_RECOVERY_INTERFACE",
    "SYMAI_POLARITY_CONTRACT_INTERFACE",
    "MODEL_OUTPUT_RECOVERY_SCHEMA_VERSION",
    "DIRECT_ROUTE_ID",
    "LEANSTRAL_TOKENIZER_IDENTITY",
    "RecoveryRole",
    "RecoveryRoute",
    "RecoveryPolicy",
    "PREREGISTERED_SRT023_POLICY",
    "ModelCallReceipt",
    "ModelOutputRecoveryReceipt",
    "ModelOutputRecoveryResult",
    "SyMAIPolarityContract",
    "BoundedModelOutputRecovery",
]
