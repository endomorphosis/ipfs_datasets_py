"""Exact counterexample replay recipes and receipts (CounterexampleReplay@1).

Safe, content-addressed replay recipes reconstruct a property violation from
immutable source/model/tool/policy/bound identities without exposing private
material.

Acceptance obligations (FVT-G041 / FVT-015):

* Corpus witnesses replay under their exact identities.
* Binding fails closed when tree, property, assumption, tool, or bound
  identities change.
* Unavailable tools return ``unavailable`` rather than success.
* Raw private artifacts never appear in public recipes.
* Replay results and receipts are content-addressed.

This module owns the replay contract and deterministic runtime.  Provider
syntax is never reinterpreted here; external tools are only probed for
availability (or invoked via an injected adapter/runner).  Violation
confirmation uses a caller-supplied oracle or a bounded adapter callback so
tests and hermetic lanes remain independent of live provers.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

COUNTEREXAMPLE_REPLAY_INTERFACE: Final = "CounterexampleReplay@1"
REPLAY_RECIPE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-replay-recipe@1"
)
REPLAY_RECEIPT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-replay-receipt@1"
)
REPLAY_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-replay-result@1"
)
ALGORITHM_VERSION: Final = "counterexample-replay/1.0.0"
ALGORITHM_NAME: Final = "exact_binding_counterexample_replay"

# Binding dimensions that must match exactly for a successful replay.
_BINDING_FIELDS: Final[tuple[str, ...]] = (
    "tree_id",
    "property_id",
    "assumption_ids",
    "tool_id",
    "tool_version",
    "policy_id",
    "bounds",
    "witness_content_id",
)

# Private / forbidden channel markers that must never appear in public recipes.
_FORBIDDEN_PUBLIC_MARKERS: Final[tuple[str, ...]] = (
    "hidden_witness",
    "private_witness",
    "private_inputs",
    "credential",
    "access_token",
    "refresh_token",
    "api_key",
    "raw_output",
    "prover_output",
    "stdout",
    "stderr",
    "source_excerpt",
    "source_code",
    "source_text",
    "file_content",
    "repository_source",
)

_PRIVATE_CHANNEL_KEY_RE = re.compile(
    r"(?:^|[_\-.])(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|session[_-]?token|credential|authorization|cookie|"
    r"private[_-]?key|private[_-]?premise|private[_-]?input|"
    r"hidden[_-]?witness|private[_-]?witness|witness)(?:$|[_\-.])",
    re.IGNORECASE,
)
_FORBIDDEN_CHANNEL_KEY_RE = re.compile(
    r"^(?:raw|raw_data|raw_output|provider_output|prover_output|stdout|stderr|"
    r"transcript|full_trace|full_model|source|source_code|source_text|"
    r"source_excerpt|file_content|repository_source|proof_text|command_output|"
    r"(?:[a-z0-9]+_)+source(?:_code|_text|_excerpt|_content)?)$",
    re.IGNORECASE,
)

# Keys that identify binding context and must not be treated as removable
# witness payload when building public recipes.
_IDENTITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "kind",
        "property_class",
        "property_id",
        "violated_property",
        "assumption_ids",
        "assumptions",
        "bounds",
        "finite_bounds",
        "tool",
        "tool_id",
        "tool_version",
        "provider_id",
        "provider_version",
        "oracle_id",
        "bindings",
        "source_map",
        "schema",
        "interface",
        "counterexample_id",
        "content_id",
        "semantic_id",
        "authority",
        "observation_policy_id",
        "policy_id",
        "tree_id",
        "tree_ids",
        "property_snapshot_id",
        "private_artifacts",
        "redaction",
        "summary",
    }
)

# Public payload keys retained in recipes (public witness projection only).
_PUBLIC_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "assignments",
        "model",
        "core",
        "unsat_core",
        "steps",
        "trace",
        "events",
        "states",
        "roles",
        "messages",
        "differences",
        "observed_fields",
        "failure_code",
        "theorem_id",
        "artifact_id",
        "labels",
        "prefix",
        "lasso",
    }
)


class ReplayError(ValueError):
    """Raised when a replay recipe or request is malformed."""


class ReplayStatus(StrEnum):
    """Closed status set for counterexample replay outcomes."""

    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    BINDING_MISMATCH = "binding_mismatch"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class ReplayMismatchField(StrEnum):
    """Binding dimensions that can fail exact identity checks."""

    TREE_ID = "tree_id"
    PROPERTY_ID = "property_id"
    ASSUMPTION_IDS = "assumption_ids"
    TOOL_ID = "tool_id"
    TOOL_VERSION = "tool_version"
    POLICY_ID = "policy_id"
    BOUNDS = "bounds"
    WITNESS_CONTENT_ID = "witness_content_id"


# Oracle: True iff the candidate still violates the bound property.
ViolationOracle = Callable[[Mapping[str, Any]], bool]

# Optional tool availability probe.  Returning False yields UNAVAILABLE.
ToolAvailabilityProbe = Callable[[str, str], bool]


@runtime_checkable
class CounterexampleReplayProtocol(Protocol):
    """CounterexampleReplay@1 structural contract."""

    interface: str

    def build_recipe(
        self,
        witness: Mapping[str, Any] | Any,
        *,
        oracle_id: str = "",
        tree_id: str = "",
        property_id: str = "",
        assumption_ids: Sequence[str] | None = None,
        tool_id: str = "",
        tool_version: str = "",
        policy_id: str = "",
        bounds: Mapping[str, Any] | None = None,
    ) -> "ReplayRecipe":
        ...

    def replay(
        self,
        recipe: "ReplayRecipe | Mapping[str, Any]",
        *,
        oracle: ViolationOracle | None = None,
        observed_bindings: Mapping[str, Any] | None = None,
        tool_available: bool | ToolAvailabilityProbe | None = None,
    ) -> "ReplayResult":
        ...


def _text(value: object, label: str, *, optional: bool = False, maximum: int = 512) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise ReplayError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise ReplayError(f"{label} must not contain NUL")
    if not optional and not text:
        raise ReplayError(f"{label} is required")
    if len(text) > maximum:
        text = text[: max(0, maximum - 1)] + "…"
    return text


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        item = _text(value, label, maximum=256)
        return (item,) if item else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise ReplayError(f"{label} must be a sequence of strings")
    items: list[str] = []
    for raw in value:
        item = _text(raw, label, maximum=256)
        if item:
            items.append(item)
    return tuple(sorted(set(items)))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ReplayError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ReplayError(f"{label} keys must be strings")
    return dict(value)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_ready(item) for item in value), key=_canonical)
    if isinstance(value, StrEnum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _content_id(prefix: str, payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("recipe_id", None)
    body.pop("receipt_id", None)
    body.pop("content_id", None)
    body.pop("result_id", None)
    return f"{prefix}:{_digest(body)[:32]}"


def _sha256_hex(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


# Structural / identity keys that are public-safe even when a substring would
# otherwise match a private-channel regex (e.g. ``witness_content_id``).
_SAFE_PUBLIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "assumption_ids",
        "assumptions",
        "algorithm",
        "algorithm_version",
        "bindings",
        "bindings_expected",
        "bindings_observed",
        "bounds",
        "byte_size",
        "channel",
        "contains_private_material",
        "contains_raw_prover_output",
        "contains_source",
        "content_id",
        "counterexample_id",
        "detail",
        "digest",
        "finite_bounds",
        "interface",
        "kind",
        "media_type",
        "mismatch_fields",
        "oracle_calls",
        "oracle_id",
        "policy_id",
        "private_artifact_refs",
        "property_id",
        "public_payload",
        "recipe_id",
        "receipt_id",
        "receipt",
        "recipe",
        "redacted",
        "retained",
        "retention_policy_id",
        "reproduced",
        "schema",
        "source_map",
        "status",
        "summary",
        "tool_available",
        "tool_id",
        "tool_version",
        "tree_id",
        "tree_ids",
        "violation_reproduced",
        "wall_ms",
        "witness_content_id",
        "ast_scope_ids",
        "source_ref_ids",
        "span_ids",
        # Public payload families:
        "assignments",
        "model",
        "core",
        "unsat_core",
        "steps",
        "trace",
        "events",
        "states",
        "roles",
        "messages",
        "differences",
        "observed_fields",
        "failure_code",
        "theorem_id",
        "artifact_id",
        "labels",
        "prefix",
        "lasso",
        "label",
        "action",
        "field",
        "left",
        "right",
        "type",
        "payload",
    }
)

_SAFE_PUBLIC_CHANNEL_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "secret_material",
        "provider_transcript",
        "provider_artifact",
        "source_blob",
        "private_channel",
    }
)


def _is_private_or_forbidden_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in _SAFE_PUBLIC_KEYS:
        return False
    return bool(
        _PRIVATE_CHANNEL_KEY_RE.search(normalized)
        or _FORBIDDEN_CHANNEL_KEY_RE.match(normalized)
    )


def _assert_public_safe(value: Any, *, label: str = "replay recipe") -> None:
    """Reject private field names and secret-bearing values on public surfaces."""

    def walk(node: Any, *, path: str, allow_channel_class: bool = False) -> None:
        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = str(raw_key)
                key_l = key.lower().replace("-", "_")
                child_path = f"{path}.{key}" if path else key
                if key_l in _SAFE_PUBLIC_KEYS:
                    nested_allow = key_l in {
                        "private_artifact_refs",
                        "channel",
                    }
                    walk(
                        child,
                        path=child_path,
                        allow_channel_class=nested_allow or allow_channel_class,
                    )
                    continue
                if _is_private_or_forbidden_key(key) or any(
                    marker == key_l or marker in key_l
                    for marker in _FORBIDDEN_PUBLIC_MARKERS
                ):
                    raise ReplayError(
                        f"{label} contains forbidden public channel key {key!r}"
                    )
                walk(child, path=child_path, allow_channel_class=allow_channel_class)
            return
        if isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray, memoryview)
        ):
            for index, child in enumerate(node):
                walk(
                    child,
                    path=f"{path}[{index}]",
                    allow_channel_class=allow_channel_class,
                )
            return
        if isinstance(node, str):
            if allow_channel_class and node in _SAFE_PUBLIC_CHANNEL_CLASSES:
                return
            if node in _SAFE_PUBLIC_CHANNEL_CLASSES:
                return
            text = node.lower()
            for marker in _FORBIDDEN_PUBLIC_MARKERS:
                if marker in text:
                    raise ReplayError(
                        f"{label} contains forbidden public channel "
                        f"{marker!r} at {path or '<root>'}"
                    )

    walk(value, path="")


def _strip_private(value: Any) -> Any:
    """Recursively drop private/forbidden keys from a mapping/list tree."""

    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            if _is_private_or_forbidden_key(key):
                continue
            if any(marker in key.lower().replace("-", "_") for marker in _FORBIDDEN_PUBLIC_MARKERS):
                continue
            cleaned[key] = _strip_private(child)
        return cleaned
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [_strip_private(item) for item in value]
    if isinstance(value, str):
        # Redact inline secret-shaped substrings rather than embedding them.
        text = value
        lowered = text.lower()
        for marker in _FORBIDDEN_PUBLIC_MARKERS:
            if marker in lowered:
                return "<redacted>"
        return text
    return value


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    to_public = getattr(value, "to_public_dict", None)
    if callable(to_public):
        converted = to_public()
        if isinstance(converted, Mapping):
            return dict(converted)
    to_witness = getattr(value, "to_witness_dict", None)
    if callable(to_witness):
        converted = to_witness()
        if isinstance(converted, Mapping):
            return dict(converted)
    raise ReplayError("witness must be a mapping or expose to_dict()/to_public_dict()")


def _extract_tool_id(raw: Mapping[str, Any]) -> str:
    for key in ("tool_id", "provider_id", "primary_provider_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    tool = raw.get("tool")
    if isinstance(tool, Mapping):
        for key in ("tool_id", "provider_id", "primary_provider_id", "id", "name"):
            value = tool.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        providers = tool.get("provider_ids")
        if isinstance(providers, Sequence) and providers:
            first = providers[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
    return ""


def _extract_tool_version(raw: Mapping[str, Any]) -> str:
    for key in ("tool_version", "provider_version", "backend_version"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    tool = raw.get("tool")
    if isinstance(tool, Mapping):
        for key in ("version", "tool_version", "provider_version", "backend_version"):
            value = tool.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_tree_id(raw: Mapping[str, Any]) -> str:
    for key in ("tree_id", "tree_cid", "repository_tree_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    bindings = raw.get("bindings")
    if isinstance(bindings, Mapping):
        for key in ("tree_id", "tree_cid", "repository_tree_id"):
            value = bindings.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        tree_ids = bindings.get("tree_ids")
        if isinstance(tree_ids, Sequence) and tree_ids:
            first = tree_ids[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
    source_map = raw.get("source_map")
    if isinstance(source_map, Mapping):
        tree_ids = source_map.get("tree_ids")
        if isinstance(tree_ids, Sequence) and tree_ids:
            first = tree_ids[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
    return ""


def _extract_property_id(raw: Mapping[str, Any]) -> str:
    for key in ("property_id", "violated_property", "obligation_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_assumption_ids(raw: Mapping[str, Any]) -> tuple[str, ...]:
    for key in ("assumption_ids", "assumptions"):
        if key in raw:
            return _string_tuple(raw.get(key), key)
    bindings = raw.get("bindings")
    if isinstance(bindings, Mapping) and "assumption_ids" in bindings:
        return _string_tuple(bindings.get("assumption_ids"), "assumption_ids")
    return ()


def _extract_bounds(raw: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("bounds", "finite_bounds"):
        value = raw.get(key)
        if isinstance(value, Mapping) and value:
            return _strip_private(dict(value))
    bindings = raw.get("bindings")
    if isinstance(bindings, Mapping):
        value = bindings.get("bounds") or bindings.get("finite_bounds")
        if isinstance(value, Mapping) and value:
            return _strip_private(dict(value))
    return {}


def _extract_policy_id(raw: Mapping[str, Any]) -> str:
    for key in ("policy_id", "observation_policy_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    bindings = raw.get("bindings")
    if isinstance(bindings, Mapping):
        for key in ("policy_id", "observation_policy_id"):
            value = bindings.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_kind(raw: Mapping[str, Any]) -> str:
    value = raw.get("kind")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return "generic_failure"


def _extract_public_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Build a public-only witness payload suitable for recipes."""

    payload_src: Mapping[str, Any]
    nested = raw.get("payload")
    if isinstance(nested, Mapping) and nested:
        payload_src = nested
    else:
        payload_src = raw

    public: dict[str, Any] = {}
    for key, value in payload_src.items():
        key_s = str(key)
        if key_s in _IDENTITY_KEYS:
            continue
        if _is_private_or_forbidden_key(key_s):
            continue
        if key_s in _PUBLIC_PAYLOAD_KEYS or key_s not in {
            "stdout",
            "stderr",
            "raw_output",
            "source_code",
            "source_excerpt",
            "hidden_witness",
            "credential",
        }:
            if key_s in _PUBLIC_PAYLOAD_KEYS or (
                key_s not in _IDENTITY_KEYS and not _is_private_or_forbidden_key(key_s)
            ):
                # Only retain known public payload families or other non-private
                # non-identity keys that already passed the private-key filter.
                if key_s in _PUBLIC_PAYLOAD_KEYS:
                    public[key_s] = _strip_private(value)

    # Fall back: if nothing extracted, try top-level public fields.
    if not public:
        for key in _PUBLIC_PAYLOAD_KEYS:
            if key in raw and key not in _IDENTITY_KEYS:
                public[key] = _strip_private(raw[key])

    return _strip_private(public)


def _extract_private_artifact_refs(
    raw: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Retain only public private-artifact *references* (digest/channel/policy)."""

    refs: list[dict[str, Any]] = []
    private = raw.get("private_artifacts") or ()
    if not isinstance(private, Sequence) or isinstance(private, (str, bytes, bytearray)):
        return ()
    for item in private:
        if hasattr(item, "to_dict") and callable(item.to_dict):
            item = item.to_dict()
        if not isinstance(item, Mapping):
            continue
        channel = item.get("channel", "")
        digest = item.get("digest", "")
        if not isinstance(channel, str) or not isinstance(digest, str):
            continue
        if not channel.strip() or not digest.strip():
            continue
        # Never re-emit raw key names like "hidden_witness" — only channel classes.
        if _is_private_or_forbidden_key(channel):
            channel = "secret_material"
        refs.append(
            {
                "channel": channel.strip(),
                "digest": digest.strip(),
                "retention_policy_id": str(
                    item.get("retention_policy_id") or "policy:public-counterexample-drop@1"
                ),
                "retained": bool(item.get("retained", False)),
                "byte_size": item.get("byte_size"),
                "media_type": str(item.get("media_type") or ""),
            }
        )
    refs.sort(key=lambda row: (row["channel"], row["digest"]))
    return tuple(refs)


def _witness_content_id(raw: Mapping[str, Any], public_payload: Mapping[str, Any]) -> str:
    claimed = raw.get("content_id") or raw.get("semantic_id") or raw.get("counterexample_id")
    if isinstance(claimed, str) and claimed.strip().startswith("sha256:"):
        return claimed.strip()
    if isinstance(claimed, str) and claimed.strip() and claimed.strip().startswith("cex:"):
        # Supervisor semantic ids are already content-addressed identities.
        return claimed.strip()
    body = {
        "kind": _extract_kind(raw),
        "payload": dict(public_payload),
        "property_id": _extract_property_id(raw),
        "assumption_ids": list(_extract_assumption_ids(raw)),
        "bounds": _extract_bounds(raw),
        "tool_id": _extract_tool_id(raw),
        "tree_id": _extract_tree_id(raw),
    }
    return _sha256_hex(_canonical(body).encode("utf-8"))


@dataclass(frozen=True, slots=True)
class ReplayBindings:
    """Immutable identity surface required for exact counterexample replay."""

    tree_id: str = ""
    property_id: str = ""
    assumption_ids: tuple[str, ...] = ()
    tool_id: str = ""
    tool_version: str = ""
    policy_id: str = ""
    bounds: Mapping[str, Any] = field(default_factory=dict)
    witness_content_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", optional=True, maximum=256)
        )
        object.__setattr__(
            self,
            "property_id",
            _text(self.property_id, "property_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _string_tuple(self.assumption_ids, "assumption_ids"),
        )
        object.__setattr__(
            self, "tool_id", _text(self.tool_id, "tool_id", optional=True, maximum=256)
        )
        object.__setattr__(
            self,
            "tool_version",
            _text(self.tool_version, "tool_version", optional=True, maximum=128),
        )
        object.__setattr__(
            self,
            "policy_id",
            _text(self.policy_id, "policy_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "bounds",
            MappingProxyType(_strip_private(_mapping(self.bounds, "bounds"))),
        )
        object.__setattr__(
            self,
            "witness_content_id",
            _text(
                self.witness_content_id,
                "witness_content_id",
                optional=True,
                maximum=256,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "bounds": dict(self.bounds),
            "policy_id": self.policy_id,
            "property_id": self.property_id,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "tree_id": self.tree_id,
            "witness_content_id": self.witness_content_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ReplayBindings":
        if value is None:
            return cls()
        if isinstance(value, ReplayBindings):
            return value
        if not isinstance(value, Mapping):
            raise ReplayError("bindings must be a mapping")
        return cls(
            tree_id=str(value.get("tree_id") or ""),
            property_id=str(value.get("property_id") or value.get("violated_property") or ""),
            assumption_ids=tuple(value.get("assumption_ids") or value.get("assumptions") or ()),
            tool_id=str(value.get("tool_id") or ""),
            tool_version=str(value.get("tool_version") or ""),
            policy_id=str(
                value.get("policy_id") or value.get("observation_policy_id") or ""
            ),
            bounds=value.get("bounds") or value.get("finite_bounds") or {},
            witness_content_id=str(
                value.get("witness_content_id") or value.get("content_id") or ""
            ),
        )

    def compare(self, other: "ReplayBindings") -> tuple[ReplayMismatchField, ...]:
        """Return sorted mismatch fields between expected (self) and observed."""

        mismatches: list[ReplayMismatchField] = []
        if self.tree_id and other.tree_id and self.tree_id != other.tree_id:
            mismatches.append(ReplayMismatchField.TREE_ID)
        if self.property_id and other.property_id and self.property_id != other.property_id:
            mismatches.append(ReplayMismatchField.PROPERTY_ID)
        if self.assumption_ids and other.assumption_ids:
            if tuple(self.assumption_ids) != tuple(other.assumption_ids):
                mismatches.append(ReplayMismatchField.ASSUMPTION_IDS)
        if self.tool_id and other.tool_id and self.tool_id != other.tool_id:
            mismatches.append(ReplayMismatchField.TOOL_ID)
        if self.tool_version and other.tool_version and self.tool_version != other.tool_version:
            mismatches.append(ReplayMismatchField.TOOL_VERSION)
        if self.policy_id and other.policy_id and self.policy_id != other.policy_id:
            mismatches.append(ReplayMismatchField.POLICY_ID)
        if self.bounds and other.bounds is not None:
            if _canonical(dict(self.bounds)) != _canonical(dict(other.bounds)):
                mismatches.append(ReplayMismatchField.BOUNDS)
        if (
            self.witness_content_id
            and other.witness_content_id
            and self.witness_content_id != other.witness_content_id
        ):
            mismatches.append(ReplayMismatchField.WITNESS_CONTENT_ID)
        return tuple(mismatches)


@dataclass(frozen=True, slots=True)
class ReplayRecipe:
    """Public-safe, content-addressed recipe for exact counterexample replay.

    Recipes never embed raw private material.  Private channels appear only as
    digest/retention references when already projected through the public
    counterexample boundary.
    """

    kind: str
    bindings: ReplayBindings
    public_payload: Mapping[str, Any] = field(default_factory=dict)
    oracle_id: str = ""
    counterexample_id: str = ""
    summary: str = ""
    private_artifact_refs: tuple[Mapping[str, Any], ...] = ()
    source_map: Mapping[str, Any] = field(default_factory=dict)
    recipe_id: str = ""
    algorithm: str = ALGORITHM_NAME
    algorithm_version: str = ALGORITHM_VERSION
    schema: str = REPLAY_RECIPE_SCHEMA
    interface: str = COUNTEREXAMPLE_REPLAY_INTERFACE
    contains_private_material: bool = False
    contains_raw_prover_output: bool = False
    contains_source: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _text(self.kind, "kind", maximum=128) or "generic_failure"
        )
        if not isinstance(self.bindings, ReplayBindings):
            object.__setattr__(
                self, "bindings", ReplayBindings.from_mapping(self.bindings)  # type: ignore[arg-type]
            )
        object.__setattr__(
            self,
            "public_payload",
            MappingProxyType(_strip_private(_mapping(self.public_payload, "public_payload"))),
        )
        object.__setattr__(
            self, "oracle_id", _text(self.oracle_id, "oracle_id", optional=True, maximum=256)
        )
        object.__setattr__(
            self,
            "counterexample_id",
            _text(self.counterexample_id, "counterexample_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", optional=True, maximum=512)
        )
        refs = tuple(
            MappingProxyType(dict(item)) if isinstance(item, Mapping) else item
            for item in self.private_artifact_refs
        )
        object.__setattr__(self, "private_artifact_refs", refs)
        object.__setattr__(
            self,
            "source_map",
            MappingProxyType(_strip_private(_mapping(self.source_map, "source_map"))),
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "schema", maximum=256) or REPLAY_RECIPE_SCHEMA,
        )
        if self.schema != REPLAY_RECIPE_SCHEMA:
            raise ReplayError(f"unsupported replay recipe schema {self.schema!r}")
        object.__setattr__(
            self,
            "interface",
            _text(self.interface, "interface", maximum=128)
            or COUNTEREXAMPLE_REPLAY_INTERFACE,
        )
        for flag_name in (
            "contains_private_material",
            "contains_raw_prover_output",
            "contains_source",
        ):
            if getattr(self, flag_name) is not False:
                raise ReplayError(f"public replay recipes must set {flag_name}=False")

        public = self._public_core()
        _assert_public_safe(public, label="replay recipe")
        computed = _content_id("replay-recipe", public)
        if self.recipe_id:
            claimed = _text(self.recipe_id, "recipe_id", maximum=256)
            if claimed != computed:
                raise ReplayError("replay recipe content identity does not match")
            object.__setattr__(self, "recipe_id", claimed)
        else:
            object.__setattr__(self, "recipe_id", computed)

    def _public_core(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "bindings": self.bindings.to_dict(),
            "contains_private_material": False,
            "contains_raw_prover_output": False,
            "contains_source": False,
            "counterexample_id": self.counterexample_id,
            "interface": self.interface,
            "kind": self.kind,
            "oracle_id": self.oracle_id,
            "private_artifact_refs": [dict(item) for item in self.private_artifact_refs],
            "public_payload": dict(self.public_payload),
            "schema": self.schema,
            "source_map": dict(self.source_map),
            "summary": self.summary,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._public_core()
        payload["recipe_id"] = self.recipe_id
        _assert_public_safe(payload, label="replay recipe dict")
        return payload

    def candidate_witness(self) -> dict[str, Any]:
        """Witness mapping presented to a violation oracle under recipe bindings."""

        witness: dict[str, Any] = {
            "kind": self.kind,
            "property_id": self.bindings.property_id,
            "violated_property": self.bindings.property_id,
            "assumption_ids": list(self.bindings.assumption_ids),
            "assumptions": list(self.bindings.assumption_ids),
            "bounds": dict(self.bindings.bounds),
            "finite_bounds": dict(self.bindings.bounds),
            "tool_id": self.bindings.tool_id,
            "tool_version": self.bindings.tool_version,
            "tree_id": self.bindings.tree_id,
            "policy_id": self.bindings.policy_id,
            "content_id": self.bindings.witness_content_id,
            "counterexample_id": self.counterexample_id,
            "oracle_id": self.oracle_id,
        }
        witness.update(dict(self.public_payload))
        # Nested payload form for oracles that look under payload.
        if self.public_payload:
            witness.setdefault("payload", dict(self.public_payload))
        return witness

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayRecipe":
        if not isinstance(value, Mapping):
            raise ReplayError("replay recipe must be an object")
        return cls(
            kind=str(value.get("kind") or "generic_failure"),
            bindings=ReplayBindings.from_mapping(value.get("bindings")),
            public_payload=value.get("public_payload") or {},
            oracle_id=str(value.get("oracle_id") or ""),
            counterexample_id=str(value.get("counterexample_id") or ""),
            summary=str(value.get("summary") or ""),
            private_artifact_refs=tuple(value.get("private_artifact_refs") or ()),
            source_map=value.get("source_map") or {},
            recipe_id=str(value.get("recipe_id") or ""),
            algorithm=str(value.get("algorithm") or ALGORITHM_NAME),
            algorithm_version=str(value.get("algorithm_version") or ALGORITHM_VERSION),
            schema=str(value.get("schema") or REPLAY_RECIPE_SCHEMA),
            interface=str(value.get("interface") or COUNTEREXAMPLE_REPLAY_INTERFACE),
            contains_private_material=bool(value.get("contains_private_material", False)),
            contains_raw_prover_output=bool(value.get("contains_raw_prover_output", False)),
            contains_source=bool(value.get("contains_source", False)),
        )


@dataclass(frozen=True, slots=True)
class ReplayReceipt:
    """Machine-checkable, content-addressed record of one replay attempt."""

    receipt_id: str
    recipe_id: str
    status: ReplayStatus | str
    bindings_expected: Mapping[str, Any]
    bindings_observed: Mapping[str, Any]
    mismatch_fields: tuple[str, ...] = ()
    tool_available: bool | None = None
    violation_reproduced: bool = False
    oracle_id: str = ""
    oracle_calls: int = 0
    algorithm: str = ALGORITHM_NAME
    algorithm_version: str = ALGORITHM_VERSION
    detail: str = ""
    wall_ms: int = 0
    content_id: str = ""
    schema: str = REPLAY_RECEIPT_SCHEMA
    interface: str = COUNTEREXAMPLE_REPLAY_INTERFACE

    def __post_init__(self) -> None:
        status = (
            self.status
            if isinstance(self.status, ReplayStatus)
            else ReplayStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "bindings_expected",
            MappingProxyType(dict(self.bindings_expected or {})),
        )
        object.__setattr__(
            self,
            "bindings_observed",
            MappingProxyType(dict(self.bindings_observed or {})),
        )
        object.__setattr__(
            self,
            "mismatch_fields",
            tuple(str(item) for item in self.mismatch_fields if str(item)),
        )
        object.__setattr__(
            self, "oracle_id", _text(self.oracle_id, "oracle_id", optional=True, maximum=256)
        )
        object.__setattr__(
            self, "detail", _text(self.detail, "detail", optional=True, maximum=512)
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "schema", maximum=256) or REPLAY_RECEIPT_SCHEMA,
        )
        object.__setattr__(
            self,
            "interface",
            _text(self.interface, "interface", maximum=128)
            or COUNTEREXAMPLE_REPLAY_INTERFACE,
        )
        if not self.receipt_id:
            object.__setattr__(
                self, "receipt_id", _content_id("replay-receipt", self.to_dict(identity=False))
            )
        if not self.content_id:
            object.__setattr__(
                self,
                "content_id",
                _sha256_hex(
                    _canonical(self.to_dict(identity=False)).encode("utf-8")
                ),
            )

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        status = (
            self.status.value if isinstance(self.status, ReplayStatus) else str(self.status)
        )
        payload: dict[str, Any] = {
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "bindings_expected": dict(self.bindings_expected),
            "bindings_observed": dict(self.bindings_observed),
            "detail": self.detail,
            "interface": self.interface,
            "mismatch_fields": list(self.mismatch_fields),
            "oracle_calls": int(self.oracle_calls),
            "oracle_id": self.oracle_id,
            "recipe_id": self.recipe_id,
            "schema": self.schema,
            "status": status,
            "tool_available": self.tool_available,
            "violation_reproduced": bool(self.violation_reproduced),
            "wall_ms": int(self.wall_ms),
        }
        if identity:
            payload["receipt_id"] = self.receipt_id
            payload["content_id"] = self.content_id
        return payload


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Replay outcome: status, public recipe, and content-addressed receipt."""

    status: ReplayStatus | str
    recipe: ReplayRecipe
    receipt: ReplayReceipt
    schema: str = REPLAY_RESULT_SCHEMA
    interface: str = COUNTEREXAMPLE_REPLAY_INTERFACE
    content_id: str = ""

    def __post_init__(self) -> None:
        status = (
            self.status
            if isinstance(self.status, ReplayStatus)
            else ReplayStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
        if not self.content_id:
            body = {
                "interface": self.interface,
                "recipe_id": self.recipe.recipe_id,
                "receipt": self.receipt.to_dict(identity=False),
                "schema": self.schema,
                "status": status.value,
            }
            object.__setattr__(
                self,
                "content_id",
                _sha256_hex(_canonical(body).encode("utf-8")),
            )

    @property
    def reproduced(self) -> bool:
        return self.status is ReplayStatus.REPRODUCED or self.status == ReplayStatus.REPRODUCED

    @property
    def binding_mismatch(self) -> bool:
        return (
            self.status is ReplayStatus.BINDING_MISMATCH
            or self.status == ReplayStatus.BINDING_MISMATCH
        )

    @property
    def unavailable(self) -> bool:
        return self.status is ReplayStatus.UNAVAILABLE or self.status == ReplayStatus.UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        status = (
            self.status.value if isinstance(self.status, ReplayStatus) else str(self.status)
        )
        payload = {
            "content_id": self.content_id,
            "interface": self.interface,
            "receipt": self.receipt.to_dict(),
            "recipe": self.recipe.to_dict(),
            "reproduced": self.reproduced,
            "schema": self.schema,
            "status": status,
        }
        _assert_public_safe(payload, label="replay result")
        return payload


class CounterexampleReplayer:
    """Deterministic CounterexampleReplay@1 runtime.

    Builds public-safe recipes from witnesses/envelopes and replays them under
    exact identity bindings.  Uses an injected violation oracle (or optional
    tool probe) and never treats unavailable tools as success.
    """

    interface: Final = COUNTEREXAMPLE_REPLAY_INTERFACE
    algorithm: Final = ALGORITHM_NAME
    algorithm_version: Final = ALGORITHM_VERSION

    def __init__(
        self,
        *,
        default_oracle: ViolationOracle | None = None,
        default_tool_probe: ToolAvailabilityProbe | None = None,
    ) -> None:
        self.default_oracle = default_oracle
        self.default_tool_probe = default_tool_probe

    def build_recipe(
        self,
        witness: Mapping[str, Any] | Any,
        *,
        oracle_id: str = "",
        tree_id: str = "",
        property_id: str = "",
        assumption_ids: Sequence[str] | None = None,
        tool_id: str = "",
        tool_version: str = "",
        policy_id: str = "",
        bounds: Mapping[str, Any] | None = None,
    ) -> ReplayRecipe:
        raw = _as_mapping(witness)
        public_payload = _extract_public_payload(raw)
        resolved_tree = tree_id or _extract_tree_id(raw)
        resolved_property = property_id or _extract_property_id(raw)
        resolved_assumptions = (
            _string_tuple(assumption_ids, "assumption_ids")
            if assumption_ids is not None
            else _extract_assumption_ids(raw)
        )
        resolved_tool = tool_id or _extract_tool_id(raw)
        resolved_tool_version = tool_version or _extract_tool_version(raw)
        resolved_policy = policy_id or _extract_policy_id(raw)
        resolved_bounds = (
            _strip_private(dict(bounds)) if bounds is not None else _extract_bounds(raw)
        )
        witness_cid = _witness_content_id(raw, public_payload)
        bindings = ReplayBindings(
            tree_id=resolved_tree,
            property_id=resolved_property,
            assumption_ids=resolved_assumptions,
            tool_id=resolved_tool,
            tool_version=resolved_tool_version,
            policy_id=resolved_policy,
            bounds=resolved_bounds,
            witness_content_id=witness_cid,
        )
        source_map = raw.get("source_map") if isinstance(raw.get("source_map"), Mapping) else {}
        # Keep only identifier lists in source_map (never source text).
        safe_source_map: dict[str, Any] = {}
        if isinstance(source_map, Mapping):
            for key in (
                "ast_scope_ids",
                "source_ref_ids",
                "span_ids",
                "tree_ids",
            ):
                value = source_map.get(key)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    safe_source_map[key] = [
                        str(item).strip()
                        for item in value
                        if isinstance(item, str) and item.strip()
                    ]
        counterexample_id = str(
            raw.get("counterexample_id") or raw.get("semantic_id") or ""
        )
        summary = str(raw.get("summary") or "")
        private_refs = _extract_private_artifact_refs(raw)
        recipe = ReplayRecipe(
            kind=_extract_kind(raw),
            bindings=bindings,
            public_payload=public_payload,
            oracle_id=oracle_id or str(raw.get("oracle_id") or ""),
            counterexample_id=counterexample_id,
            summary=summary,
            private_artifact_refs=private_refs,
            source_map=safe_source_map,
        )
        return recipe

    def check_bindings(
        self,
        expected: ReplayBindings | Mapping[str, Any],
        observed: ReplayBindings | Mapping[str, Any] | None,
    ) -> tuple[ReplayMismatchField, ...]:
        exp = (
            expected
            if isinstance(expected, ReplayBindings)
            else ReplayBindings.from_mapping(expected)
        )
        if observed is None:
            return ()
        obs = (
            observed
            if isinstance(observed, ReplayBindings)
            else ReplayBindings.from_mapping(observed)
        )
        return exp.compare(obs)

    def replay(
        self,
        recipe: ReplayRecipe | Mapping[str, Any],
        *,
        oracle: ViolationOracle | None = None,
        observed_bindings: Mapping[str, Any] | ReplayBindings | None = None,
        tool_available: bool | ToolAvailabilityProbe | None = None,
    ) -> ReplayResult:
        started = time.monotonic()
        if isinstance(recipe, Mapping):
            recipe = ReplayRecipe.from_dict(recipe)
        if not isinstance(recipe, ReplayRecipe):
            raise ReplayError("recipe must be a ReplayRecipe or mapping")

        expected = recipe.bindings
        # Default observed bindings to the recipe's own bindings (exact replay).
        if observed_bindings is None:
            observed = expected
        elif isinstance(observed_bindings, ReplayBindings):
            observed = observed_bindings
        else:
            # Merge partial observed overrides onto expected so omitted fields
            # do not falsely mismatch when only one dimension changes.
            base = expected.to_dict()
            overrides = dict(observed_bindings)
            # Empty strings mean "use expected" so tests can change one field.
            for key, value in list(overrides.items()):
                if value == "" or value is None:
                    overrides.pop(key, None)
            base.update(overrides)
            observed = ReplayBindings.from_mapping(base)

        mismatches = expected.compare(observed)
        wall_ms = int((time.monotonic() - started) * 1000)

        if mismatches:
            receipt = ReplayReceipt(
                receipt_id="",
                recipe_id=recipe.recipe_id,
                status=ReplayStatus.BINDING_MISMATCH,
                bindings_expected=expected.to_dict(),
                bindings_observed=observed.to_dict(),
                mismatch_fields=tuple(field.value for field in mismatches),
                tool_available=None,
                violation_reproduced=False,
                oracle_id=recipe.oracle_id,
                oracle_calls=0,
                detail=(
                    "exact binding mismatch: "
                    + ", ".join(field.value for field in mismatches)
                ),
                wall_ms=wall_ms,
            )
            return ReplayResult(
                status=ReplayStatus.BINDING_MISMATCH,
                recipe=recipe,
                receipt=receipt,
            )

        # Tool availability: unavailable must never report success.
        tool_id = expected.tool_id
        tool_version = expected.tool_version
        availability: bool | None = None
        probe = tool_available if tool_available is not None else self.default_tool_probe
        if probe is not None and tool_id:
            if isinstance(probe, bool):
                availability = probe
            elif callable(probe):
                availability = bool(probe(tool_id, tool_version))
            else:
                raise ReplayError("tool_available must be bool or callable")
            if not availability:
                wall_ms = int((time.monotonic() - started) * 1000)
                receipt = ReplayReceipt(
                    receipt_id="",
                    recipe_id=recipe.recipe_id,
                    status=ReplayStatus.UNAVAILABLE,
                    bindings_expected=expected.to_dict(),
                    bindings_observed=observed.to_dict(),
                    mismatch_fields=(),
                    tool_available=False,
                    violation_reproduced=False,
                    oracle_id=recipe.oracle_id,
                    oracle_calls=0,
                    detail=f"tool unavailable: {tool_id}",
                    wall_ms=wall_ms,
                )
                return ReplayResult(
                    status=ReplayStatus.UNAVAILABLE,
                    recipe=recipe,
                    receipt=receipt,
                )

        active_oracle = oracle if oracle is not None else self.default_oracle
        if active_oracle is None:
            wall_ms = int((time.monotonic() - started) * 1000)
            receipt = ReplayReceipt(
                receipt_id="",
                recipe_id=recipe.recipe_id,
                status=ReplayStatus.UNSUPPORTED,
                bindings_expected=expected.to_dict(),
                bindings_observed=observed.to_dict(),
                mismatch_fields=(),
                tool_available=availability,
                violation_reproduced=False,
                oracle_id=recipe.oracle_id,
                oracle_calls=0,
                detail="no violation oracle provided for replay",
                wall_ms=wall_ms,
            )
            return ReplayResult(
                status=ReplayStatus.UNSUPPORTED,
                recipe=recipe,
                receipt=receipt,
            )

        candidate = recipe.candidate_witness()
        try:
            violated = bool(active_oracle(candidate))
            oracle_calls = 1
        except Exception as exc:  # noqa: BLE001 — surface as non-success
            wall_ms = int((time.monotonic() - started) * 1000)
            receipt = ReplayReceipt(
                receipt_id="",
                recipe_id=recipe.recipe_id,
                status=ReplayStatus.ERROR,
                bindings_expected=expected.to_dict(),
                bindings_observed=observed.to_dict(),
                mismatch_fields=(),
                tool_available=availability if availability is not None else True,
                violation_reproduced=False,
                oracle_id=recipe.oracle_id,
                oracle_calls=1,
                detail=f"oracle error: {type(exc).__name__}",
                wall_ms=wall_ms,
            )
            return ReplayResult(
                status=ReplayStatus.ERROR,
                recipe=recipe,
                receipt=receipt,
            )

        status = (
            ReplayStatus.REPRODUCED if violated else ReplayStatus.NOT_REPRODUCED
        )
        wall_ms = int((time.monotonic() - started) * 1000)
        receipt = ReplayReceipt(
            receipt_id="",
            recipe_id=recipe.recipe_id,
            status=status,
            bindings_expected=expected.to_dict(),
            bindings_observed=observed.to_dict(),
            mismatch_fields=(),
            tool_available=availability if availability is not None else True,
            violation_reproduced=violated,
            oracle_id=recipe.oracle_id,
            oracle_calls=oracle_calls,
            detail=(
                "property violation reproduced under exact bindings"
                if violated
                else "oracle reports no violation under exact bindings"
            ),
            wall_ms=wall_ms,
        )
        return ReplayResult(status=status, recipe=recipe, receipt=receipt)


def build_replay_recipe(
    witness: Mapping[str, Any] | Any,
    **kwargs: Any,
) -> ReplayRecipe:
    """Module-level convenience for :meth:`CounterexampleReplayer.build_recipe`."""

    return CounterexampleReplayer().build_recipe(witness, **kwargs)


def replay_counterexample(
    recipe: ReplayRecipe | Mapping[str, Any] | Any,
    *,
    oracle: ViolationOracle | None = None,
    observed_bindings: Mapping[str, Any] | ReplayBindings | None = None,
    tool_available: bool | ToolAvailabilityProbe | None = None,
    oracle_id: str = "",
    **recipe_kwargs: Any,
) -> ReplayResult:
    """Build a recipe when needed and replay under exact bindings.

    Accepts either a :class:`ReplayRecipe`/mapping recipe or a raw witness.
    When a raw witness is supplied, ``recipe_kwargs`` are forwarded to
    :meth:`CounterexampleReplayer.build_recipe`.
    """

    replayer = CounterexampleReplayer()
    if isinstance(recipe, ReplayRecipe):
        built = recipe
    elif isinstance(recipe, Mapping) and (
        recipe.get("schema") == REPLAY_RECIPE_SCHEMA
        or "public_payload" in recipe
        or "recipe_id" in recipe
    ):
        built = ReplayRecipe.from_dict(recipe)
    else:
        if oracle_id and "oracle_id" not in recipe_kwargs:
            recipe_kwargs["oracle_id"] = oracle_id
        built = replayer.build_recipe(recipe, **recipe_kwargs)
    return replayer.replay(
        built,
        oracle=oracle,
        observed_bindings=observed_bindings,
        tool_available=tool_available,
    )


__all__ = [
    "ALGORITHM_NAME",
    "ALGORITHM_VERSION",
    "COUNTEREXAMPLE_REPLAY_INTERFACE",
    "REPLAY_RECEIPT_SCHEMA",
    "REPLAY_RECIPE_SCHEMA",
    "REPLAY_RESULT_SCHEMA",
    "CounterexampleReplayProtocol",
    "CounterexampleReplayer",
    "ReplayBindings",
    "ReplayError",
    "ReplayMismatchField",
    "ReplayReceipt",
    "ReplayRecipe",
    "ReplayResult",
    "ReplayStatus",
    "ToolAvailabilityProbe",
    "ViolationOracle",
    "build_replay_recipe",
    "replay_counterexample",
]
