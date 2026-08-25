"""Privacy-safe analytical telemetry projection into DuckLake (EAAEF-132).

Records carry identities, counts, durations, and fence/run ids only. Secrets,
transcript bodies, hidden chain-of-thought, raw prompts and source bodies are
rejected. Telemetry never grants current authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final


TELEMETRY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-telemetry@1"
)

ALLOWED_IDENTITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "run_id",
        "task_id",
        "attempt_id",
        "fence_id",
        "fence_token",
        "event_id",
        "artifact_cid",
        "epoch_id",
    }
)

_HIDDEN_CHAIN_OF_THOUGHT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "chain_of_thought",
        "cot",
        "hidden_chain_of_thought",
        "hidden_cot",
        "hidden_reasoning",
        "hidden_thoughts",
        "internal_monologue",
        "model_thoughts",
        "private_reasoning",
        "private_thinking",
        "scratchpad",
        "thinking",
        "thinking_blocks",
        "thinking_private",
        "thinking_text",
    }
)
_PRIVATE_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "private_key",
        "secret",
        "session_token",
        "transcript_body",
        "witness",
    }
)
_TRANSCRIPT_BODY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "body",
        "full_transcript",
        "prompt",
        "raw_bytes",
        "raw_export",
        "raw_prompt",
        "raw_transcript",
        "source_body",
        "transcript",
        "transcript_body",
        "transcript_text",
    }
)

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/=@+-]*$"
)


class TelemetryError(ValueError):
    """Malformed or privacy-unsafe telemetry record."""


class TelemetryPrivacyError(TelemetryError):
    """Secrets, transcript bodies, or hidden reasoning appeared on telemetry."""


class TelemetryAuthorityError(TelemetryError):
    """Telemetry attempted to grant current authority."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_")


def _key_is_forbidden(key: str) -> str | None:
    normalized = _normalize_key(key)
    if normalized in _HIDDEN_CHAIN_OF_THOUGHT_KEYS:
        return "hidden_chain_of_thought"
    if normalized in _TRANSCRIPT_BODY_KEYS:
        return "transcript_body"
    if any(
        normalized == marker or normalized.endswith("_" + marker) or marker in normalized
        for marker in _PRIVATE_FIELD_MARKERS
    ):
        return "private_material"
    return None


def _reject_forbidden_keys(value: Any, *, name: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            reason = _key_is_forbidden(str(raw_key))
            if reason == "hidden_chain_of_thought":
                raise TelemetryPrivacyError(
                    f"{name} must not represent hidden chain-of-thought"
                )
            if reason == "transcript_body":
                raise TelemetryPrivacyError(
                    f"{name} must not embed transcript bodies"
                )
            if reason == "private_material":
                raise TelemetryPrivacyError(
                    f"{name} must not contain secrets or private material"
                )
            _reject_forbidden_keys(item, name=name)
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        for item in value:
            _reject_forbidden_keys(item, name=name)


def _require_identity(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TelemetryError(f"{field_name} is required")
    if _SHA256_RE.fullmatch(text) or _ID_RE.fullmatch(text):
        return text
    raise TelemetryError(f"{field_name} is not a permitted identity")


def _nonneg_int_map(value: Any, *, name: str) -> Mapping[str, int]:
    if value is None:
        items: Mapping[str, Any] = {}
    elif not isinstance(value, Mapping):
        raise TelemetryError(f"{name} must be an object")
    else:
        items = value
    out: dict[str, int] = {}
    for key, raw in items.items():
        token = str(key).strip()
        if not token:
            raise TelemetryError(f"{name} keys must be non-empty")
        reason = _key_is_forbidden(token)
        if reason:
            raise TelemetryPrivacyError(f"{name} must not contain forbidden field {token}")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise TelemetryError(f"{name}.{token} must be a non-negative int")
        out[token] = raw
    return MappingProxyType(out)


def _authority_denied(action: str) -> None:
    raise TelemetryAuthorityError(
        f"telemetry cannot {action}; current authority remains on the DuckDB/Quack owner"
    )


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    """Digest/reference/count-only telemetry row."""

    run_id: str
    task_id: str
    fence_id: str
    counts: Mapping[str, int]
    durations: Mapping[str, int]
    attempt_id: str = ""
    event_id: str = ""
    identities: Mapping[str, str] = MappingProxyType({})
    content_digest: str = ""
    grants_current_authority: bool = False

    def __post_init__(self) -> None:
        if self.grants_current_authority:
            _authority_denied("grant current authority")
        object.__setattr__(self, "grants_current_authority", False)
        object.__setattr__(self, "run_id", _require_identity(self.run_id, field_name="run_id"))
        object.__setattr__(self, "task_id", _require_identity(self.task_id, field_name="task_id"))
        object.__setattr__(
            self, "fence_id", _require_identity(self.fence_id, field_name="fence_id")
        )
        object.__setattr__(self, "counts", _nonneg_int_map(self.counts, name="counts"))
        object.__setattr__(
            self, "durations", _nonneg_int_map(self.durations, name="durations")
        )
        object.__setattr__(self, "attempt_id", str(self.attempt_id or "").strip())
        object.__setattr__(self, "event_id", str(self.event_id or "").strip())
        identities = {
            str(key).strip(): str(value).strip()
            for key, value in dict(self.identities or {}).items()
            if str(key).strip()
        }
        identities.setdefault("run_id", self.run_id)
        identities.setdefault("task_id", self.task_id)
        identities.setdefault("fence_id", self.fence_id)
        extra = set(identities).difference(ALLOWED_IDENTITY_KEYS)
        if extra:
            raise TelemetryError(f"unsupported telemetry identity {sorted(extra)[0]}")
        _reject_forbidden_keys(identities, name="telemetry identities")
        object.__setattr__(self, "identities", MappingProxyType(identities))
        payload = {
            "schema": TELEMETRY_SCHEMA,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "fence_id": self.fence_id,
            "attempt_id": self.attempt_id,
            "event_id": self.event_id,
            "counts": dict(self.counts),
            "durations": dict(self.durations),
            "identities": dict(identities),
            "grants_current_authority": False,
        }
        _reject_forbidden_keys(payload, name="telemetry record")
        digest = str(self.content_digest or "").strip() or _sha256_text(
            _canonical_json(payload)
        )
        if not _SHA256_RE.fullmatch(digest):
            raise TelemetryError("content_digest must be sha256:<64-hex>")
        object.__setattr__(self, "content_digest", digest)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": TELEMETRY_SCHEMA,
                "run_id": self.run_id,
                "task_id": self.task_id,
                "fence_id": self.fence_id,
                "attempt_id": self.attempt_id,
                "event_id": self.event_id,
                "counts": dict(self.counts),
                "durations": dict(self.durations),
                "identities": dict(self.identities),
                "content_digest": self.content_digest,
                "grants_current_authority": False,
            }
        )

    def grant_claim(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant claims")

    def grant_lease(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant leases")

    def grant_fence(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant fences")

    def grant_merge_authority(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant merge authority")


def project_telemetry(
    record: Mapping[str, Any] | TelemetryRecord,
) -> TelemetryRecord:
    """Project one privacy-safe analytical telemetry record."""

    if isinstance(record, TelemetryRecord):
        return record
    if not isinstance(record, Mapping):
        raise TelemetryError("telemetry payload must be an object")
    _reject_forbidden_keys(record, name="telemetry record")
    identities = dict(record.get("identities") or {})
    for key in ALLOWED_IDENTITY_KEYS:
        if key in record and key not in identities and record.get(key):
            identities[key] = str(record[key])
    return TelemetryRecord(
        run_id=str(record.get("run_id") or identities.get("run_id") or ""),
        task_id=str(record.get("task_id") or identities.get("task_id") or ""),
        fence_id=str(
            record.get("fence_id")
            or record.get("fence_token")
            or identities.get("fence_id")
            or identities.get("fence_token")
            or ""
        ),
        attempt_id=str(record.get("attempt_id") or identities.get("attempt_id") or ""),
        event_id=str(record.get("event_id") or identities.get("event_id") or ""),
        counts=dict(record.get("counts") or {}),
        durations=dict(record.get("durations") or {}),
        identities=identities,
        grants_current_authority=bool(record.get("grants_current_authority", False)),
    )


__all__ = (
    "ALLOWED_IDENTITY_KEYS",
    "TELEMETRY_SCHEMA",
    "TelemetryAuthorityError",
    "TelemetryError",
    "TelemetryPrivacyError",
    "TelemetryRecord",
    "project_telemetry",
)
