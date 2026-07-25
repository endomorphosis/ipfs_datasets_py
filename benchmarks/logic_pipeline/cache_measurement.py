"""Source-bound SyMAI warm-cache measurement and setup receipts.

Warm-cache benchmark coordinates need two logically distinct operations: one
setup invocation that populates the run-scoped cache, followed by the measured
invocation that must be served entirely from that cache.  This module keeps
that distinction explicit without changing the adapter's own retry policy.

Only a configured, non-dry-run :class:`SymaiAdapter` in warm mode is eligible.
Every other adapter/request pair is invoked exactly once and receives no cache
prime envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re
import time
from typing import Final, Mapping, Sequence, Self

from .adapters import (
    StageAdapter,
    StageInvocation,
    StageOutput,
    StageRequest,
    SymaiAdapter,
)
from .contracts import (
    CacheMode,
    CacheScope,
    FailureCode,
    ProtocolContractError,
    ResourceLane,
    StageName,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)


__all__ = (
    "SYMAI_CACHE_PRIME_DIGEST_FIELD",
    "SYMAI_CACHE_PRIME_FIELD",
    "SYMAI_CACHE_PRIME_MAX_BYTES",
    "SYMAI_CACHE_PRIME_RECEIPT_SCHEMA",
    "SYMAI_CACHE_PRIME_REQUEST_SCHEMA",
    "SymaiCachePrimeReceipt",
    "extract_symai_cache_prime_receipt",
    "extract_symai_cache_setup_telemetry",
    "invoke_with_symai_cache_measurement",
    "is_symai_warm_cache_measurement_eligible",
    "symai_backend_identity",
    "symai_backend_identity_sha256",
    "symai_backend_invocation_count",
    "symai_semantic_payload",
    "symai_semantic_payload_sha256",
    "validate_symai_cache_prime_receipt",
    "validate_symai_warm_cache_measurement",
)


SYMAI_CACHE_PRIME_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-cache-prime-receipt.v2"
)
SYMAI_CACHE_PRIME_REQUEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-cache-prime-request.v1"
)
SYMAI_CACHE_PRIME_FIELD: Final = "cache_prime"
SYMAI_CACHE_PRIME_DIGEST_FIELD: Final = "cache_prime_receipt_sha256"
SYMAI_CACHE_PRIME_MAX_BYTES: Final = 32 * 1024

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CACHE_KEY_SUFFIX = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SOURCE_ITEMS: Final = len(StageName) * 2
_MAX_SOURCE_LENGTH: Final = 256
_OPERATIONAL_SEMANTIC_KEYS: Final = frozenset(
    {
        "backend_provenance",
        "cache",
        "cache_hit",
        "cache_key",
        "cache_namespace",
        "consumed_artifact_sha256",
        "graph_invocation_index",
        "graph_invoked",
        "graph_policy_reason",
        "policy_decision",
        "policy_decision_sha256",
        "raw_output",
        "routing_policy",
        "telemetry",
    }
)
_OPERATIONAL_BACKEND_IDENTITY_KEYS: Final = frozenset(
    {
        "attempt",
        "attempts",
        "cache",
        "cache_enabled",
        "cache_hit",
        "cache_hits",
        "cache_key",
        "cache_miss",
        "cache_misses",
        "cache_mode",
        "cache_namespace",
        "cache_prime",
        "cache_prime_receipt",
        "cache_prime_receipt_sha256",
        "cached_backend",
        "consumed_artifact_sha256",
        "cpu_time_ms",
        "graph_invocation_index",
        "graph_invoked",
        "graph_policy_reason",
        "model_calls",
        "peak_memory_bytes",
        "policy_decision",
        "policy_decision_sha256",
        "retries",
        "retry",
        "router_cache",
        "router_cache_key",
        "router_cached_backend",
        "routing_policy",
        "telemetry",
        "wall_time_ms",
    }
)


def _detached_json(value: object) -> object:
    """Detach immutable contract mappings into canonical JSON containers."""

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ProtocolContractError("JSON object keys must be strings")
        return {
            key: _detached_json(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_detached_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        canonical_json(value)
        return value
    raise ProtocolContractError("value is not canonical JSON data")


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        canonical_json(_detached_json(value)).encode("utf-8")
    ).hexdigest()


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProtocolContractError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _require_string(
    value: object,
    field: str,
    *,
    maximum: int = _MAX_SOURCE_LENGTH,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ProtocolContractError(f"{field} must be a bounded string")
    return value


def _optional_digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_digest(value, field)


def _require_boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProtocolContractError(f"{field} must be a boolean")
    return value


def _string_sequence(
    value: object,
    field: str,
    *,
    maximum_items: int,
    digests: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise ProtocolContractError(f"{field} must be an array")
    if len(value) > maximum_items:
        raise ProtocolContractError(f"{field} contains too many items")
    result = tuple(
        (
            _require_digest(item, f"{field}[]")
            if digests
            else _require_string(item, f"{field}[]")
        )
        for item in value
    )
    return result


def _without_receipt_digest(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in value.items()
        if key != "receipt_sha256"
    }


def _strip_semantic_operations(value: object) -> object:
    """Remove only top-level operational envelopes from SyMAI evidence.

    Names such as ``cache`` and ``telemetry`` are legitimate semantic keys
    inside ``candidate_ir``.  Recursively removing them would let a modified
    candidate compare equal to the primed candidate.  Stage-owned operational
    envelopes are top-level by contract, so nested values remain fully bound.
    """

    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ProtocolContractError(
                    "SyMAI semantic payload keys must be strings"
                )
            key = raw_key.strip()
            normalized = key.lower().replace("-", "_")
            if (
                normalized in _OPERATIONAL_SEMANTIC_KEYS
                or normalized == SYMAI_CACHE_PRIME_FIELD
                or normalized.startswith(f"{SYMAI_CACHE_PRIME_FIELD}_")
            ):
                continue
            projected[key] = _detached_json(item)
        return projected
    return _detached_json(value)


def _strip_backend_identity_operations(value: object) -> object:
    """Remove exact top-level operation fields and retain every other claim.

    The adapter and graph attach cache counters and routing receipts only at
    the top level.  Recursively stripping names, or treating arbitrary
    ``cache_*`` prefixes as operational, would let an unknown or nested
    backend-identity claim drift without invalidating a warm-cache receipt.
    """

    if not isinstance(value, Mapping):
        raise ProtocolContractError(
            "SyMAI backend identity must be an object"
        )
    projected: dict[str, object] = {}
    for raw_key, item in value.items():
        if not isinstance(raw_key, str):
            raise ProtocolContractError(
                "SyMAI backend identity keys must be strings"
            )
        if raw_key in _OPERATIONAL_BACKEND_IDENTITY_KEYS:
            continue
        projected[raw_key] = _detached_json(item)
    return projected


def symai_backend_identity(value: object) -> object:
    """Return the stable provider/model/backend identity for comparison.

    Cache namespaces, keys, hit counters, setup attempts, telemetry, and prime
    envelopes are deliberately excluded.  Provider, model, endpoint, routing
    backend, backend revision, and other non-cache identity fields remain.
    """

    if isinstance(value, StageInvocation):
        value = value.output.effective_identity
    elif isinstance(value, StageOutput):
        value = value.effective_identity
    elif isinstance(value, StageRecord):
        value = value.provenance.effective_identity
    if not isinstance(value, Mapping):
        raise ProtocolContractError(
            "SyMAI effective identity must be an object"
        )
    projected = _strip_backend_identity_operations(value)
    encoded = canonical_json(projected).encode("utf-8")
    if len(encoded) > SYMAI_CACHE_PRIME_MAX_BYTES:
        raise ProtocolContractError(
            "SyMAI backend identity exceeds the cache measurement bound"
        )
    return projected


def symai_backend_identity_sha256(value: object) -> str:
    """Return the digest of the stable cache-insensitive backend identity."""

    return _digest_json(symai_backend_identity(value))


def symai_semantic_payload(value: object) -> object:
    """Project SyMAI evidence without raw output or operational cache fields."""

    if isinstance(value, StageInvocation):
        value = value.output.data
    elif isinstance(value, StageOutput):
        value = value.data
    elif isinstance(value, StageRecord):
        value = value.data
    projected = _strip_semantic_operations(value)
    encoded = canonical_json(projected).encode("utf-8")
    if len(encoded) > SYMAI_CACHE_PRIME_MAX_BYTES:
        raise ProtocolContractError(
            "SyMAI semantic payload exceeds the cache measurement bound"
        )
    return projected


def symai_semantic_payload_sha256(value: object) -> str:
    """Return the cache-insensitive digest of a SyMAI stage payload."""

    return _digest_json(symai_semantic_payload(value))


def _request_binding(
    request: StageRequest,
    *,
    requested_identity_sha256: str,
    source: Sequence[str],
) -> dict[str, object]:
    return {
        "schema": SYMAI_CACHE_PRIME_REQUEST_SCHEMA,
        "protocol_sha256": request.protocol_sha256,
        "run_id": request.run_id,
        "case_id": request.case_id,
        "case_manifest_sha256": request.case_manifest_sha256,
        "variant_id": request.variant_id,
        "split": request.split.value,
        "cache_mode": request.cache_mode.value,
        "input_sha256": request.input_sha256,
        "environment_sha256": request.environment_sha256,
        "requested_identity_sha256": requested_identity_sha256,
        "source": list(source),
        "upstream_stage_digests": list(request.upstream_stage_digests),
        "upstream_artifact_sha256": [
            artifact.digest for artifact in request.upstream_artifacts
        ],
    }


@dataclass(frozen=True, slots=True)
class SymaiCachePrimeReceipt:
    """Content-addressed evidence for the unmeasured cache setup invocation."""

    schema: str
    protocol_sha256: str
    run_id: str
    case_id: str
    case_manifest_sha256: str
    variant_id: str
    split: str
    cache_mode: str
    input_sha256: str
    environment_sha256: str | None
    requested_identity_sha256: str
    source: tuple[str, ...]
    upstream_stage_digests: tuple[str, ...]
    upstream_artifact_sha256: tuple[str, ...]
    request_sha256: str
    cache_namespace: str
    cache_key: str
    prime_semantic_output_sha256: str
    prime_effective_identity_sha256: str
    prime_backend_identity_sha256: str
    prime_status: str
    prime_failure_code: str | None
    prime_failure_detail_sha256: str | None
    setup_telemetry: TelemetryRecord
    setup_telemetry_sha256: str
    measured_invoked: bool
    measured_status: str | None
    measured_failure_code: str | None
    measured_failure_detail_sha256: str | None
    measured_telemetry_sha256: str | None
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.schema != SYMAI_CACHE_PRIME_RECEIPT_SCHEMA:
            raise ProtocolContractError(
                "unsupported SyMAI cache-prime receipt schema"
            )
        for field in (
            "protocol_sha256",
            "case_manifest_sha256",
            "input_sha256",
            "requested_identity_sha256",
            "request_sha256",
            "prime_semantic_output_sha256",
            "prime_effective_identity_sha256",
            "prime_backend_identity_sha256",
            "setup_telemetry_sha256",
            "receipt_sha256",
        ):
            _require_digest(getattr(self, field), field)
        _optional_digest(
            self.environment_sha256, "environment_sha256"
        )
        _optional_digest(
            self.prime_failure_detail_sha256,
            "prime_failure_detail_sha256",
        )
        _require_boolean(self.measured_invoked, "measured_invoked")
        _optional_digest(
            self.measured_failure_detail_sha256,
            "measured_failure_detail_sha256",
        )
        _optional_digest(
            self.measured_telemetry_sha256,
            "measured_telemetry_sha256",
        )
        for field in ("run_id", "case_id", "variant_id"):
            _require_string(getattr(self, field), field, maximum=128)
        if self.split not in {"pilot", "development", "holdout"}:
            raise ProtocolContractError("receipt split is unsupported")
        if self.cache_mode != CacheMode.WARM.value:
            raise ProtocolContractError(
                "SyMAI cache-prime receipt must bind warm mode"
            )
        _string_sequence(
            self.source,
            "source",
            maximum_items=_MAX_SOURCE_ITEMS,
        )
        _string_sequence(
            self.upstream_stage_digests,
            "upstream_stage_digests",
            maximum_items=_MAX_SOURCE_ITEMS,
            digests=True,
        )
        _string_sequence(
            self.upstream_artifact_sha256,
            "upstream_artifact_sha256",
            maximum_items=_MAX_SOURCE_ITEMS,
            digests=True,
        )
        expected_namespace = CacheScope(
            run_id=self.run_id,
            protocol_sha256=self.protocol_sha256,
            variant_id=self.variant_id,
            split=_split_from_value(self.split),
            mode=CacheMode.WARM,
        ).namespace
        if self.cache_namespace != expected_namespace:
            raise ProtocolContractError(
                "cache-prime namespace does not bind the exact warm scope"
            )
        prefix = f"{self.cache_namespace}/stage/symai/"
        if (
            not isinstance(self.cache_key, str)
            or not self.cache_key.startswith(prefix)
            or _CACHE_KEY_SUFFIX.fullmatch(
                self.cache_key[len(prefix) :]
            )
            is None
        ):
            raise ProtocolContractError(
                "cache-prime key does not bind the exact SyMAI warm scope"
            )
        try:
            status = StageStatus(self.prime_status)
        except ValueError as exc:
            raise ProtocolContractError(
                "cache-prime status is unsupported"
            ) from exc
        if status is StageStatus.SKIPPED:
            raise ProtocolContractError(
                "a cache-prime invocation cannot be skipped"
            )
        failure_code: FailureCode | None = None
        if self.prime_failure_code is not None:
            try:
                failure_code = FailureCode(self.prime_failure_code)
            except ValueError as exc:
                raise ProtocolContractError(
                    "cache-prime failure code is unsupported"
                ) from exc
        if status is StageStatus.SUCCESS:
            if (
                failure_code is not None
                or self.prime_failure_detail_sha256 is not None
            ):
                raise ProtocolContractError(
                    "successful cache prime cannot contain a failure"
                )
        elif (
            failure_code is None
            or self.prime_failure_detail_sha256 is None
        ):
            raise ProtocolContractError(
                "failed cache prime must bind its failure code and detail"
            )
        if not isinstance(self.setup_telemetry, TelemetryRecord):
            raise ProtocolContractError(
                "setup_telemetry must be a TelemetryRecord"
            )
        if self.setup_telemetry.resource_lane is not ResourceLane.MODEL:
            raise ProtocolContractError(
                "SyMAI cache-prime telemetry must use the model lane"
            )
        if self.setup_telemetry.digest != self.setup_telemetry_sha256:
            raise ProtocolContractError(
                "cache-prime setup telemetry digest mismatch"
            )
        measured_fields = (
            self.measured_status,
            self.measured_failure_code,
            self.measured_failure_detail_sha256,
            self.measured_telemetry_sha256,
        )
        if not self.measured_invoked:
            if any(item is not None for item in measured_fields):
                raise ProtocolContractError(
                    "uninvoked SyMAI measurement cannot contain measured evidence"
                )
        else:
            if (
                self.measured_status is None
                or self.measured_telemetry_sha256 is None
            ):
                raise ProtocolContractError(
                    "invoked SyMAI measurement must bind status and telemetry"
                )
            try:
                measured_status = StageStatus(self.measured_status)
            except ValueError as exc:
                raise ProtocolContractError(
                    "measured SyMAI status is unsupported"
                ) from exc
            if measured_status is StageStatus.SKIPPED:
                raise ProtocolContractError(
                    "an invoked SyMAI measurement cannot be skipped"
                )
            measured_failure_code: FailureCode | None = None
            if self.measured_failure_code is not None:
                try:
                    measured_failure_code = FailureCode(
                        self.measured_failure_code
                    )
                except ValueError as exc:
                    raise ProtocolContractError(
                        "measured SyMAI failure code is unsupported"
                    ) from exc
            if measured_status is StageStatus.SUCCESS:
                if (
                    measured_failure_code is not None
                    or self.measured_failure_detail_sha256 is not None
                ):
                    raise ProtocolContractError(
                        "successful SyMAI measurement cannot contain a failure"
                    )
            elif (
                measured_failure_code is None
                or self.measured_failure_detail_sha256 is None
            ):
                raise ProtocolContractError(
                    "failed SyMAI measurement must bind its failure"
                )
        request_binding = {
            "schema": SYMAI_CACHE_PRIME_REQUEST_SCHEMA,
            "protocol_sha256": self.protocol_sha256,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "case_manifest_sha256": self.case_manifest_sha256,
            "variant_id": self.variant_id,
            "split": self.split,
            "cache_mode": self.cache_mode,
            "input_sha256": self.input_sha256,
            "environment_sha256": self.environment_sha256,
            "requested_identity_sha256": self.requested_identity_sha256,
            "source": list(self.source),
            "upstream_stage_digests": list(
                self.upstream_stage_digests
            ),
            "upstream_artifact_sha256": list(
                self.upstream_artifact_sha256
            ),
        }
        if _digest_json(request_binding) != self.request_sha256:
            raise ProtocolContractError(
                "cache-prime request binding digest mismatch"
            )
        encoded_without_digest = canonical_json(
            _without_receipt_digest(self.to_dict())
        ).encode("utf-8")
        encoded_receipt = canonical_json(self.to_dict()).encode("utf-8")
        if len(encoded_receipt) > SYMAI_CACHE_PRIME_MAX_BYTES:
            raise ProtocolContractError(
                "SyMAI cache-prime receipt exceeds its byte bound"
            )
        if (
            hashlib.sha256(encoded_without_digest).hexdigest()
            != self.receipt_sha256
        ):
            raise ProtocolContractError(
                "SyMAI cache-prime receipt digest mismatch"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "case_manifest_sha256": self.case_manifest_sha256,
            "variant_id": self.variant_id,
            "split": self.split,
            "cache_mode": self.cache_mode,
            "input_sha256": self.input_sha256,
            "environment_sha256": self.environment_sha256,
            "requested_identity_sha256": (
                self.requested_identity_sha256
            ),
            "source": list(self.source),
            "upstream_stage_digests": list(
                self.upstream_stage_digests
            ),
            "upstream_artifact_sha256": list(
                self.upstream_artifact_sha256
            ),
            "request_sha256": self.request_sha256,
            "cache_namespace": self.cache_namespace,
            "cache_key": self.cache_key,
            "prime_semantic_output_sha256": (
                self.prime_semantic_output_sha256
            ),
            "prime_effective_identity_sha256": (
                self.prime_effective_identity_sha256
            ),
            "prime_backend_identity_sha256": (
                self.prime_backend_identity_sha256
            ),
            "prime_status": self.prime_status,
            "prime_failure_code": self.prime_failure_code,
            "prime_failure_detail_sha256": (
                self.prime_failure_detail_sha256
            ),
            "setup_telemetry": self.setup_telemetry.to_dict(),
            "setup_telemetry_sha256": self.setup_telemetry_sha256,
            "measured_invoked": self.measured_invoked,
            "measured_status": self.measured_status,
            "measured_failure_code": self.measured_failure_code,
            "measured_failure_detail_sha256": (
                self.measured_failure_detail_sha256
            ),
            "measured_telemetry_sha256": (
                self.measured_telemetry_sha256
            ),
            "receipt_sha256": self.receipt_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, Mapping) or not all(
            isinstance(key, str) for key in value
        ):
            raise ProtocolContractError(
                "SyMAI cache-prime receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)
        actual = set(value)
        if actual != expected:
            missing = sorted(expected - actual)
            unknown = sorted(actual - expected)
            raise ProtocolContractError(
                "SyMAI cache-prime receipt has "
                f"missing={missing} unknown={unknown}"
            )
        return cls(
            schema=_require_string(value["schema"], "schema"),
            protocol_sha256=_require_digest(
                value["protocol_sha256"], "protocol_sha256"
            ),
            run_id=_require_string(value["run_id"], "run_id", maximum=128),
            case_id=_require_string(
                value["case_id"], "case_id", maximum=128
            ),
            case_manifest_sha256=_require_digest(
                value["case_manifest_sha256"],
                "case_manifest_sha256",
            ),
            variant_id=_require_string(
                value["variant_id"], "variant_id", maximum=128
            ),
            split=_require_string(value["split"], "split"),
            cache_mode=_require_string(
                value["cache_mode"], "cache_mode"
            ),
            input_sha256=_require_digest(
                value["input_sha256"], "input_sha256"
            ),
            environment_sha256=_optional_digest(
                value["environment_sha256"], "environment_sha256"
            ),
            requested_identity_sha256=_require_digest(
                value["requested_identity_sha256"],
                "requested_identity_sha256",
            ),
            source=_string_sequence(
                value["source"],
                "source",
                maximum_items=_MAX_SOURCE_ITEMS,
            ),
            upstream_stage_digests=_string_sequence(
                value["upstream_stage_digests"],
                "upstream_stage_digests",
                maximum_items=_MAX_SOURCE_ITEMS,
                digests=True,
            ),
            upstream_artifact_sha256=_string_sequence(
                value["upstream_artifact_sha256"],
                "upstream_artifact_sha256",
                maximum_items=_MAX_SOURCE_ITEMS,
                digests=True,
            ),
            request_sha256=_require_digest(
                value["request_sha256"], "request_sha256"
            ),
            cache_namespace=_require_string(
                value["cache_namespace"],
                "cache_namespace",
                maximum=2048,
            ),
            cache_key=_require_string(
                value["cache_key"], "cache_key", maximum=4096
            ),
            prime_semantic_output_sha256=_require_digest(
                value["prime_semantic_output_sha256"],
                "prime_semantic_output_sha256",
            ),
            prime_effective_identity_sha256=_require_digest(
                value["prime_effective_identity_sha256"],
                "prime_effective_identity_sha256",
            ),
            prime_backend_identity_sha256=_require_digest(
                value["prime_backend_identity_sha256"],
                "prime_backend_identity_sha256",
            ),
            prime_status=_require_string(
                value["prime_status"], "prime_status"
            ),
            prime_failure_code=(
                None
                if value["prime_failure_code"] is None
                else _require_string(
                    value["prime_failure_code"], "prime_failure_code"
                )
            ),
            prime_failure_detail_sha256=_optional_digest(
                value["prime_failure_detail_sha256"],
                "prime_failure_detail_sha256",
            ),
            setup_telemetry=TelemetryRecord.from_dict(
                value["setup_telemetry"]
            ),
            setup_telemetry_sha256=_require_digest(
                value["setup_telemetry_sha256"],
                "setup_telemetry_sha256",
            ),
            measured_invoked=_require_boolean(
                value["measured_invoked"], "measured_invoked"
            ),
            measured_status=(
                None
                if value["measured_status"] is None
                else _require_string(
                    value["measured_status"], "measured_status"
                )
            ),
            measured_failure_code=(
                None
                if value["measured_failure_code"] is None
                else _require_string(
                    value["measured_failure_code"],
                    "measured_failure_code",
                )
            ),
            measured_failure_detail_sha256=_optional_digest(
                value["measured_failure_detail_sha256"],
                "measured_failure_detail_sha256",
            ),
            measured_telemetry_sha256=_optional_digest(
                value["measured_telemetry_sha256"],
                "measured_telemetry_sha256",
            ),
            receipt_sha256=_require_digest(
                value["receipt_sha256"], "receipt_sha256"
            ),
        )


def _split_from_value(value: str):
    # Kept local to avoid widening the public receipt's primitive wire fields.
    from .contracts import Split

    try:
        return Split(value)
    except ValueError as exc:
        raise ProtocolContractError("receipt split is unsupported") from exc


@dataclass(frozen=True, slots=True)
class _CacheObservation:
    namespace: str
    key: str
    hit: bool | None
    errors: tuple[str, ...]


def _fallback_cache_key(request: StageRequest, namespace: str) -> str:
    suffix = _digest_json(
        {
            "schema": "symai-cache-key-fallback.v1",
            "request_input_sha256": request.input_sha256,
            "requested_identity_sha256": _digest_json(
                request.requested_identity
            ),
            "upstream_artifact_sha256": [
                artifact.digest for artifact in request.upstream_artifacts
            ],
        }
    )
    return f"{namespace}/stage/symai/{suffix}"


def _cache_observation(
    output: StageOutput,
    request: StageRequest,
) -> _CacheObservation:
    expected_namespace = CacheScope(
        request.run_id,
        request.protocol_sha256,
        request.variant_id,
        request.split,
        CacheMode.WARM,
    ).namespace
    namespaces: list[object] = []
    keys: list[object] = []
    hits: list[object] = []
    modes: list[object] = []
    data = output.data
    if isinstance(data, Mapping):
        nested = data.get("cache")
        if isinstance(nested, Mapping):
            namespaces.append(nested.get("namespace"))
            keys.append(nested.get("key"))
            hits.append(nested.get("hit"))
            modes.append(nested.get("mode"))
        else:
            namespaces.append(data.get("cache_namespace"))
            keys.append(data.get("cache_key"))
            if "cache_hit" in data:
                hits.append(data.get("cache_hit"))
    identity = output.effective_identity
    if isinstance(identity, Mapping):
        if "cache_namespace" in identity:
            namespaces.append(identity.get("cache_namespace"))
        if "cache_key" in identity:
            keys.append(identity.get("cache_key"))
        if "cache_hit" in identity:
            hits.append(identity.get("cache_hit"))

    errors: list[str] = []
    observed_namespaces = [
        value for value in namespaces if value is not None
    ]
    if not observed_namespaces:
        errors.append("cache namespace is absent")
    elif any(
        not isinstance(value, str) or value != expected_namespace
        for value in observed_namespaces
    ):
        errors.append("cache namespace drifted")

    fallback_key = _fallback_cache_key(request, expected_namespace)
    observed_keys = [value for value in keys if value is not None]
    string_keys = [
        value for value in observed_keys if isinstance(value, str)
    ]
    key = string_keys[0] if string_keys else fallback_key
    prefix = f"{expected_namespace}/stage/symai/"
    if not observed_keys:
        errors.append("cache key is absent")
    elif (
        len(string_keys) != len(observed_keys)
        or len(set(string_keys)) != 1
        or not key.startswith(prefix)
        or _CACHE_KEY_SUFFIX.fullmatch(key[len(prefix) :]) is None
    ):
        errors.append("cache key drifted")
        key = fallback_key

    observed_hits = [value for value in hits if value is not None]
    boolean_hits = [
        value for value in observed_hits if type(value) is bool
    ]
    hit: bool | None = boolean_hits[0] if boolean_hits else None
    if observed_hits and (
        len(boolean_hits) != len(observed_hits)
        or len(set(boolean_hits)) != 1
    ):
        errors.append("cache hit evidence drifted")
        hit = None
    if modes and any(value != CacheMode.WARM.value for value in modes):
        errors.append("cache mode drifted")
    return _CacheObservation(
        expected_namespace,
        key,
        hit,
        tuple(errors),
    )


def _create_receipt(
    adapter: StageAdapter,
    request: StageRequest,
    invocation: StageInvocation,
    cache: _CacheObservation,
) -> SymaiCachePrimeReceipt:
    output = invocation.output
    requested_identity_sha256 = _digest_json(
        request.requested_identity
    )
    source = (*adapter.source, *request.source)
    request_sha256 = _digest_json(
        _request_binding(
            request,
            requested_identity_sha256=requested_identity_sha256,
            source=source,
        )
    )
    effective_identity = (
        output.effective_identity or request.requested_identity
    )
    failure_detail_sha256 = (
        None
        if output.failure_detail is None
        else _digest_text(output.failure_detail)
    )
    without_digest: dict[str, object] = {
        "schema": SYMAI_CACHE_PRIME_RECEIPT_SCHEMA,
        "protocol_sha256": request.protocol_sha256,
        "run_id": request.run_id,
        "case_id": request.case_id,
        "case_manifest_sha256": request.case_manifest_sha256,
        "variant_id": request.variant_id,
        "split": request.split.value,
        "cache_mode": request.cache_mode.value,
        "input_sha256": request.input_sha256,
        "environment_sha256": request.environment_sha256,
        "requested_identity_sha256": requested_identity_sha256,
        "source": list(source),
        "upstream_stage_digests": list(
            request.upstream_stage_digests
        ),
        "upstream_artifact_sha256": [
            artifact.digest for artifact in request.upstream_artifacts
        ],
        "request_sha256": request_sha256,
        "cache_namespace": cache.namespace,
        "cache_key": cache.key,
        "prime_semantic_output_sha256": (
            symai_semantic_payload_sha256(output)
        ),
        "prime_effective_identity_sha256": _digest_json(
            effective_identity
        ),
        "prime_backend_identity_sha256": (
            symai_backend_identity_sha256(effective_identity)
        ),
        "prime_status": output.status.value,
        "prime_failure_code": (
            None
            if output.failure_code is None
            else output.failure_code.value
        ),
        "prime_failure_detail_sha256": failure_detail_sha256,
        "setup_telemetry": invocation.telemetry.to_dict(),
        "setup_telemetry_sha256": invocation.telemetry.digest,
        "measured_invoked": False,
        "measured_status": None,
        "measured_failure_code": None,
        "measured_failure_detail_sha256": None,
        "measured_telemetry_sha256": None,
    }
    receipt = {
        **without_digest,
        "receipt_sha256": _digest_json(without_digest),
    }
    return SymaiCachePrimeReceipt.from_dict(receipt)


def _bind_measured_invocation(
    receipt: SymaiCachePrimeReceipt,
    invocation: StageInvocation,
) -> SymaiCachePrimeReceipt:
    """Content-address one attempted measured call into its setup receipt."""

    output = invocation.output
    value = receipt.to_dict()
    value.update(
        {
            "measured_invoked": True,
            "measured_status": output.status.value,
            "measured_failure_code": (
                None
                if output.failure_code is None
                else output.failure_code.value
            ),
            "measured_failure_detail_sha256": (
                None
                if output.failure_detail is None
                else _digest_text(output.failure_detail)
            ),
            "measured_telemetry_sha256": invocation.telemetry.digest,
        }
    )
    value["receipt_sha256"] = _digest_json(
        _without_receipt_digest(value)
    )
    return SymaiCachePrimeReceipt.from_dict(value)


def validate_symai_cache_prime_receipt(
    value: object,
    *,
    request: StageRequest | None = None,
) -> SymaiCachePrimeReceipt:
    """Validate exact receipt fields, self-digests, and optional request binding."""

    receipt = (
        value
        if isinstance(value, SymaiCachePrimeReceipt)
        else SymaiCachePrimeReceipt.from_dict(value)
    )
    # Re-parse to defend callers passing an instance created through unusual
    # deserialization/object-construction paths.
    receipt = SymaiCachePrimeReceipt.from_dict(receipt.to_dict())
    if request is not None:
        if not isinstance(request, StageRequest):
            raise ProtocolContractError(
                "request must be a StageRequest"
            )
        expected_identity_sha256 = _digest_json(
            request.requested_identity
        )
        if (
            receipt.protocol_sha256 != request.protocol_sha256
            or receipt.run_id != request.run_id
            or receipt.case_id != request.case_id
            or receipt.case_manifest_sha256
            != request.case_manifest_sha256
            or receipt.variant_id != request.variant_id
            or receipt.split != request.split.value
            or receipt.cache_mode != request.cache_mode.value
            or receipt.input_sha256 != request.input_sha256
            or receipt.environment_sha256
            != request.environment_sha256
            or receipt.requested_identity_sha256
            != expected_identity_sha256
            or receipt.source[-len(request.source) :]
            != request.source
            or receipt.upstream_stage_digests
            != request.upstream_stage_digests
            or receipt.upstream_artifact_sha256
            != tuple(
                artifact.digest
                for artifact in request.upstream_artifacts
            )
        ):
            raise ProtocolContractError(
                "cache-prime receipt does not bind the supplied request"
            )
    return receipt


def _receipt_value(value: object) -> object | None:
    if isinstance(value, SymaiCachePrimeReceipt):
        return value
    if isinstance(value, StageInvocation):
        value = value.output
    if isinstance(value, StageOutput):
        value = value.data
    if isinstance(value, StageRecord):
        value = value.data
    if not isinstance(value, Mapping):
        raise ProtocolContractError(
            "cache-prime evidence must be a stage output or object"
        )
    if value.get("schema") == SYMAI_CACHE_PRIME_RECEIPT_SCHEMA:
        return value
    return value.get(SYMAI_CACHE_PRIME_FIELD)


def _validate_receipt_against_stage_record(
    receipt: SymaiCachePrimeReceipt,
    record: StageRecord,
) -> None:
    """Reject receipts copied across records, coordinates, or cache modes."""

    expected_namespace = CacheScope(
        record.run_id,
        record.protocol_sha256,
        record.variant_id,
        record.split,
        record.cache_mode,
    ).namespace
    effective_receipt_sha256 = (
        record.provenance.effective_identity.get(
            SYMAI_CACHE_PRIME_DIGEST_FIELD
        )
    )
    data_cache_namespace: object = None
    data_cache_key: object = None
    data_cache_mode: object = None
    if isinstance(record.data, Mapping):
        nested_cache = record.data.get("cache")
        if isinstance(nested_cache, Mapping):
            data_cache_namespace = nested_cache.get("namespace")
            data_cache_key = nested_cache.get("key")
            data_cache_mode = nested_cache.get("mode")
        else:
            data_cache_namespace = record.data.get(
                "cache_namespace"
            )
            data_cache_key = record.data.get("cache_key")
            data_cache_mode = record.cache_mode.value
    effective_cache_namespace = (
        record.provenance.effective_identity.get("cache_namespace")
    )
    effective_cache_key = (
        record.provenance.effective_identity.get("cache_key")
    )
    graph_consumed = record.provenance.effective_identity.get(
        "consumed_artifact_sha256"
    )
    if graph_consumed is None:
        upstream_binding_matches = (
            receipt.upstream_stage_digests
            == record.provenance.upstream_stage_digests
        )
    else:
        upstream_binding_matches = bool(
            isinstance(graph_consumed, Sequence)
            and not isinstance(
                graph_consumed, (str, bytes, bytearray)
            )
            and tuple(graph_consumed)
            == receipt.upstream_artifact_sha256
        )
    mismatches: list[str] = []
    comparisons = {
        "stage": record.stage is StageName.SYMAI,
        "protocol": (
            receipt.protocol_sha256 == record.protocol_sha256
        ),
        "run": receipt.run_id == record.run_id,
        "case": receipt.case_id == record.case_id,
        "manifest": (
            receipt.case_manifest_sha256
            == record.case_manifest_sha256
        ),
        "variant": receipt.variant_id == record.variant_id,
        "split": receipt.split == record.split.value,
        "cache_mode": (
            receipt.cache_mode == record.cache_mode.value
        ),
        "cache_namespace": (
            receipt.cache_namespace == expected_namespace
        ),
        "cache_data": (
            data_cache_namespace == receipt.cache_namespace
            and data_cache_key == receipt.cache_key
            and data_cache_mode == receipt.cache_mode
        ),
        "cache_effective_identity": (
            effective_cache_namespace == receipt.cache_namespace
            and effective_cache_key == receipt.cache_key
        ),
        "input": (
            receipt.input_sha256
            == record.provenance.input_sha256
        ),
        "environment": (
            receipt.environment_sha256
            == record.provenance.environment_sha256
        ),
        "source": (
            receipt.source == record.provenance.source
        ),
        "upstream_stage_digests": (
            upstream_binding_matches
        ),
        "requested_identity": (
            receipt.requested_identity_sha256
            == _digest_json(record.provenance.requested_identity)
        ),
        "effective_receipt_digest": (
            effective_receipt_sha256 == receipt.receipt_sha256
        ),
        "measured_telemetry": (
            record.telemetry.digest
            == (
                receipt.measured_telemetry_sha256
                if receipt.measured_invoked
                else _zero_measured_telemetry().digest
            )
        ),
    }
    mismatches.extend(
        field for field, matches in comparisons.items() if not matches
    )
    if mismatches:
        raise ProtocolContractError(
            "cache-prime receipt does not bind enclosing StageRecord: "
            + ", ".join(mismatches)
        )


def _validate_receipt_against_stage_output(
    receipt: SymaiCachePrimeReceipt,
    output: StageOutput,
    telemetry: TelemetryRecord,
) -> None:
    expected_telemetry_sha256 = (
        receipt.measured_telemetry_sha256
        if receipt.measured_invoked
        else _zero_measured_telemetry().digest
    )
    if (
        output.effective_identity.get(
            SYMAI_CACHE_PRIME_DIGEST_FIELD
        )
        != receipt.receipt_sha256
        or telemetry.digest != expected_telemetry_sha256
    ):
        raise ProtocolContractError(
            "cache-prime receipt does not bind enclosing StageOutput"
        )


def extract_symai_cache_prime_receipt(
    value: object,
    *,
    request: StageRequest | None = None,
) -> SymaiCachePrimeReceipt | None:
    """Extract and strictly validate a receipt, returning ``None`` for N/A."""

    receipt = _receipt_value(value)
    if receipt is None:
        return None
    validated = validate_symai_cache_prime_receipt(
        receipt, request=request
    )
    if isinstance(value, StageRecord):
        _validate_receipt_against_stage_record(validated, value)
    elif isinstance(value, StageInvocation):
        _validate_receipt_against_stage_output(
            validated,
            value.output,
            value.telemetry,
        )
    elif isinstance(value, StageOutput) and value.telemetry is not None:
        _validate_receipt_against_stage_output(
            validated,
            value,
            value.telemetry,
        )
    return validated


def extract_symai_cache_setup_telemetry(
    value: object,
    *,
    request: StageRequest | None = None,
) -> TelemetryRecord | None:
    """Return exact setup wall/model/retry/memory counters for accounting."""

    receipt = extract_symai_cache_prime_receipt(
        value, request=request
    )
    return None if receipt is None else receipt.setup_telemetry


def symai_backend_invocation_count(record: StageRecord) -> int:
    """Return validated actual SyMAI calls for one materialized graph node."""

    if not isinstance(record, StageRecord) or record.stage is not StageName.SYMAI:
        raise ProtocolContractError(
            "SyMAI backend invocation accounting requires a SyMAI StageRecord"
        )
    identity = record.provenance.effective_identity
    graph_invoked = identity.get("graph_invoked")
    receipt = extract_symai_cache_prime_receipt(record)
    if "graph_invoked" not in identity and receipt is not None:
        return 1 + int(receipt.measured_invoked)
    if type(graph_invoked) is not bool:
        raise ProtocolContractError(
            "SyMAI stage lacks an explicit graph invocation decision"
        )
    if not graph_invoked:
        if receipt is not None:
            raise ProtocolContractError(
                "suppressed SyMAI stage contains cache-prime activity"
            )
        return 0
    if receipt is None:
        return 1
    return 1 + int(receipt.measured_invoked)


def is_symai_warm_cache_measurement_eligible(
    adapter: StageAdapter,
    request: StageRequest,
) -> bool:
    """Return whether this pair requires a setup invocation and measured hit."""

    if not isinstance(adapter, SymaiAdapter) or not isinstance(
        request, StageRequest
    ):
        return False
    config = adapter.config
    return bool(
        config is not None
        and adapter.handler is not None
        and config.cache_enabled
        and not config.dry_run
        and request.cache_mode is CacheMode.WARM
    )


def _zero_measured_telemetry() -> TelemetryRecord:
    return TelemetryRecord(resource_lane=ResourceLane.MODEL)


def _attach_receipt(
    invocation: StageInvocation,
    receipt: SymaiCachePrimeReceipt,
    *,
    telemetry: TelemetryRecord | None = None,
    status: StageStatus | None = None,
    failure_code: FailureCode | None = None,
    failure_detail: str | None = None,
) -> StageInvocation:
    output = invocation.output
    if not isinstance(output.data, Mapping):
        data: dict[str, object] = {
            "stage_data_sha256": _digest_json(output.data)
        }
    else:
        if SYMAI_CACHE_PRIME_FIELD in output.data:
            raise ProtocolContractError(
                "stage output already contains a cache-prime envelope"
            )
        data = dict(output.data)
    if "cache" not in data:
        data.setdefault("cache_namespace", receipt.cache_namespace)
        data.setdefault("cache_key", receipt.cache_key)
    data[SYMAI_CACHE_PRIME_FIELD] = receipt.to_dict()
    identity = dict(output.effective_identity)
    identity.setdefault("cache_namespace", receipt.cache_namespace)
    identity.setdefault("cache_key", receipt.cache_key)
    identity[SYMAI_CACHE_PRIME_DIGEST_FIELD] = (
        receipt.receipt_sha256
    )
    measured = invocation.telemetry if telemetry is None else telemetry
    attached = replace(
        output,
        data=data,
        status=output.status if status is None else status,
        effective_identity=identity,
        failure_code=(
            output.failure_code
            if status is None
            else failure_code
        ),
        failure_detail=(
            output.failure_detail
            if status is None
            else failure_detail
        ),
        telemetry=measured,
        kernel_accepted=False,
        kernel_receipt_sha256=None,
    )
    return StageInvocation(attached, measured)


def _prime_is_exact_miss(
    invocation: StageInvocation,
    cache: _CacheObservation,
) -> bool:
    telemetry = invocation.telemetry
    return bool(
        invocation.output.status is StageStatus.SUCCESS
        and not cache.errors
        and cache.hit is False
        and telemetry.resource_lane is ResourceLane.MODEL
        and telemetry.model_calls >= 1
        and telemetry.cache_hits == 0
        and telemetry.cache_misses == 1
    )


def _measured_is_exact_hit(
    invocation: StageInvocation,
    cache: _CacheObservation,
    *,
    prime_cache: _CacheObservation,
    receipt: SymaiCachePrimeReceipt,
) -> bool:
    telemetry = invocation.telemetry
    return bool(
        invocation.output.status is StageStatus.SUCCESS
        and not cache.errors
        and cache.hit is True
        and cache.namespace == prime_cache.namespace
        and cache.key == prime_cache.key
        and telemetry.resource_lane is ResourceLane.MODEL
        and telemetry.model_calls == 0
        and telemetry.cache_hits == 1
        and telemetry.cache_misses == 0
        and telemetry.retries == 0
        and symai_semantic_payload_sha256(invocation.output)
        == receipt.prime_semantic_output_sha256
        and symai_backend_identity_sha256(invocation.output)
        == receipt.prime_backend_identity_sha256
    )


def invoke_with_symai_cache_measurement(
    adapter: StageAdapter,
    request: StageRequest,
) -> StageInvocation:
    """Invoke once, or prime then measure an exact configured SyMAI warm hit.

    The adapter retains sole ownership of its internal retry policy.  This
    wrapper never retries a failed setup or measured invocation.
    """

    if not isinstance(adapter, StageAdapter):
        raise ProtocolContractError(
            "adapter must be a StageAdapter"
        )
    if not isinstance(request, StageRequest):
        raise ProtocolContractError(
            "request must be a StageRequest"
        )
    if not is_symai_warm_cache_measurement_eligible(adapter, request):
        return adapter.invoke(request)

    prime = adapter.invoke(request)
    prime_cache = _cache_observation(prime.output, request)
    receipt = _create_receipt(adapter, request, prime, prime_cache)

    if prime.output.status is not StageStatus.SUCCESS:
        # No measured invocation occurred.  Its counters are therefore zero;
        # the complete setup cost remains available in the receipt.
        return _attach_receipt(
            prime,
            receipt,
            telemetry=_zero_measured_telemetry(),
        )
    if not _prime_is_exact_miss(prime, prime_cache):
        return _attach_receipt(
            prime,
            receipt,
            telemetry=_zero_measured_telemetry(),
            status=StageStatus.FAILED,
            failure_code=FailureCode.CACHE_CONTAMINATION,
            failure_detail=(
                "SyMAI cache setup was not an exact run-scoped miss"
            ),
        )
    if (
        request.deadline_unix_ms is not None
        and int(time.time() * 1_000) >= request.deadline_unix_ms
    ):
        return _attach_receipt(
            prime,
            receipt,
            telemetry=_zero_measured_telemetry(),
            status=StageStatus.FAILED,
            failure_code=FailureCode.RESOURCE_LEASE_CANCELLATION,
            failure_detail=(
                "SyMAI warm-cache case deadline expired after setup"
            ),
        )

    measured = adapter.invoke(request)
    receipt = _bind_measured_invocation(receipt, measured)
    measured_cache = _cache_observation(measured.output, request)
    if not _measured_is_exact_hit(
        measured,
        measured_cache,
        prime_cache=prime_cache,
        receipt=receipt,
    ):
        return _attach_receipt(
            measured,
            receipt,
            status=StageStatus.FAILED,
            failure_code=FailureCode.CACHE_CONTAMINATION,
            failure_detail=(
                "SyMAI measured warm request was not an exact semantic "
                "cache hit"
            ),
        )
    return _attach_receipt(measured, receipt)


def validate_symai_warm_cache_measurement(
    value: object,
    *,
    telemetry: TelemetryRecord | None = None,
    effective_identity: Mapping[str, object] | None = None,
    request: StageRequest | None = None,
) -> SymaiCachePrimeReceipt:
    """Validate a successful measured hit against its setup receipt."""

    output: StageOutput | None = None
    enclosing_record = (
        value if isinstance(value, StageRecord) else None
    )
    if isinstance(value, StageInvocation):
        output = value.output
        telemetry = value.telemetry
    elif isinstance(value, StageOutput):
        output = value
        telemetry = telemetry or value.telemetry
    elif isinstance(value, StageRecord):
        if value.status is not StageStatus.SUCCESS:
            raise ProtocolContractError(
                "measured SyMAI cache record was not successful"
            )
        data = value.data
        telemetry = telemetry or value.telemetry
        effective_identity = (
            effective_identity
            or value.provenance.effective_identity
        )
        output = None
    else:
        data = value
    if output is not None:
        data = output.data
        effective_identity = (
            effective_identity or output.effective_identity
        )
        if output.status is not StageStatus.SUCCESS:
            raise ProtocolContractError(
                "measured SyMAI cache output was not successful"
            )
    if telemetry is None or not isinstance(
        telemetry, TelemetryRecord
    ):
        raise ProtocolContractError(
            "measured SyMAI cache telemetry is required"
        )
    receipt = extract_symai_cache_prime_receipt(
        enclosing_record if enclosing_record is not None else data,
        request=request,
    )
    if receipt is None:
        raise ProtocolContractError(
            "measured SyMAI cache output omitted its prime receipt"
        )
    setup = receipt.setup_telemetry
    if (
        receipt.prime_status != StageStatus.SUCCESS.value
        or receipt.prime_failure_code is not None
        or receipt.prime_failure_detail_sha256 is not None
    ):
        raise ProtocolContractError(
            "measured SyMAI cache receipt did not bind a successful setup"
        )
    if (
        not receipt.measured_invoked
        or receipt.measured_status != StageStatus.SUCCESS.value
        or receipt.measured_failure_code is not None
        or receipt.measured_failure_detail_sha256 is not None
        or receipt.measured_telemetry_sha256 != telemetry.digest
    ):
        raise ProtocolContractError(
            "measured SyMAI cache receipt did not bind this successful call"
        )
    if (
        setup.resource_lane is not ResourceLane.MODEL
        or setup.model_calls < 1
        or setup.cache_hits != 0
        or setup.cache_misses != 1
    ):
        raise ProtocolContractError(
            "measured SyMAI cache setup telemetry is not an exact miss"
        )
    if (
        telemetry.resource_lane is not ResourceLane.MODEL
        or telemetry.model_calls != 0
        or telemetry.cache_hits != 1
        or telemetry.cache_misses != 0
        or telemetry.retries != 0
    ):
        raise ProtocolContractError(
            "measured SyMAI cache telemetry is not an exact hit"
        )
    if (
        effective_identity is None
        or effective_identity.get(
            SYMAI_CACHE_PRIME_DIGEST_FIELD
        )
        != receipt.receipt_sha256
    ):
        raise ProtocolContractError(
            "measured SyMAI identity omitted its prime receipt digest"
        )
    if symai_semantic_payload_sha256(data) != (
        receipt.prime_semantic_output_sha256
    ):
        raise ProtocolContractError(
            "measured SyMAI semantic output differs from cache setup"
        )
    if symai_backend_identity_sha256(
        effective_identity
    ) != receipt.prime_backend_identity_sha256:
        raise ProtocolContractError(
            "measured SyMAI backend identity differs from cache setup"
        )
    if isinstance(data, Mapping):
        nested = data.get("cache")
        if (
            not isinstance(nested, Mapping)
            or nested.get("namespace") != receipt.cache_namespace
            or nested.get("key") != receipt.cache_key
            or nested.get("mode") != CacheMode.WARM.value
            or nested.get("hit") is not True
        ):
            raise ProtocolContractError(
                "measured SyMAI cache evidence does not bind the receipt"
            )
    else:
        raise ProtocolContractError(
            "measured SyMAI stage data must be an object"
        )
    return receipt
