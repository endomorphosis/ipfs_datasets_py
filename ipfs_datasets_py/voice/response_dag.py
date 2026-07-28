"""Append-only response-DAG candidates produced by validated voice cache misses."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from string import Formatter
from types import MappingProxyType
from typing import Any

from .normalize import canonical_json
from .schema import (
    stable_audio_id,
    stable_response_id,
    stable_template_id,
)

ABBY_VOICE_RESPONSE_DAG_APPEND_SCHEMA_VERSION = "abby_voice_response_dag_append_v1"
ABBY_VOICE_RESPONSE_DAG_RELEASE_SCHEMA_VERSION = (
    "abby_voice_response_dag_release_manifest_v1"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY_MARKERS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "signature",
    "token",
)


class AbbyVoiceResponseDAGError(ValueError):
    """A cache-miss append candidate failed a content or safety invariant."""


def _canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-" + sha256(_canonical_bytes(value)).hexdigest()[:24]


def _text(value: Any, *, field_name: str, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise AbbyVoiceResponseDAGError(f"{field_name} must not be empty")
    return result


def _digest(value: Any, *, field_name: str) -> str:
    result = _text(value, field_name=field_name).casefold()
    if not _SHA256_RE.fullmatch(result):
        raise AbbyVoiceResponseDAGError(
            f"{field_name} must be a full lowercase SHA-256"
        )
    return result


def _json_safe(value: Any, *, path: str = "value") -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        raise AbbyVoiceResponseDAGError(f"{path} must not contain raw bytes")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if any(marker in name.casefold() for marker in _SECRET_KEY_MARKERS):
                raise AbbyVoiceResponseDAGError(
                    f"{path}.{name} must not contain credentials"
                )
            result[name] = _json_safe(item, path=f"{path}.{name}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [
            _json_safe(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict(), path=path)
    raise AbbyVoiceResponseDAGError(
        f"{path} must contain deterministic JSON values"
    )


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        result = value
    else:
        to_dict = getattr(value, "to_dict", None)
        result = to_dict() if callable(to_dict) else None
    if not isinstance(result, Mapping):
        raise AbbyVoiceResponseDAGError(f"{field_name} must be a mapping")
    safe = _json_safe(result, path=field_name)
    if not isinstance(safe, Mapping):
        raise AbbyVoiceResponseDAGError(f"{field_name} must be a mapping")
    return safe


def _placeholder_names(template_text: str) -> tuple[str, ...]:
    names: list[str] = []
    try:
        parsed = Formatter().parse(template_text)
        for _literal, field_name, _format_spec, _conversion in parsed:
            if field_name:
                root = field_name.split(".", 1)[0].split("[", 1)[0]
                if root and root not in names:
                    names.append(root)
    except ValueError as exc:
        raise AbbyVoiceResponseDAGError(
            f"template_text has invalid slot syntax: {exc}"
        ) from exc
    return tuple(names)


def _edge(source: str, target: str, kind: str) -> dict[str, str]:
    return {
        "id": _stable_id(
            "edge",
            {"kind": kind, "source": source, "target": target},
        ),
        "kind": kind,
        "source": source,
        "target": target,
    }


def _normalize_audio_descriptor(value: Any) -> dict[str, Any]:
    audio = dict(_mapping(value, field_name="audio_descriptor"))
    content_sha = _digest(
        audio.get("content_sha256"), field_name="audio_descriptor.content_sha256"
    )
    audio_id = _text(
        audio.get("audio_id") or stable_audio_id(content_sha),
        field_name="audio_descriptor.audio_id",
    )
    byte_length = audio.get("byte_length")
    if (
        isinstance(byte_length, bool)
        or not isinstance(byte_length, int)
        or byte_length <= 0
    ):
        raise AbbyVoiceResponseDAGError(
            "audio_descriptor.byte_length must be a positive integer"
        )
    media_type = _text(
        audio.get("media_type") or audio.get("mime_type"),
        field_name="audio_descriptor.media_type",
    )
    if not media_type.startswith("audio/"):
        raise AbbyVoiceResponseDAGError(
            "audio_descriptor.media_type must be audio/*"
        )
    uri = _text(
        audio.get("uri"), field_name="audio_descriptor.uri", required=False
    )
    ipfs_cid = _text(
        audio.get("ipfs_cid"),
        field_name="audio_descriptor.ipfs_cid",
        required=False,
    )
    if not uri and not ipfs_cid:
        raise AbbyVoiceResponseDAGError(
            "validated audio requires an external uri or ipfs_cid"
        )
    if uri:
        if any(character.isspace() for character in uri):
            raise AbbyVoiceResponseDAGError(
                "audio_descriptor.uri must not contain whitespace"
            )
        if re.search(r"(?i)(?:token|signature|secret|credential)=", uri):
            raise AbbyVoiceResponseDAGError(
                "audio_descriptor.uri must not contain credentials"
            )
    return {
        "audio_id": audio_id,
        "byte_length": byte_length,
        "content_sha256": content_sha,
        "id": audio_id,
        "ipfs_cid": ipfs_cid,
        "kind": "audio",
        "media_type": media_type,
        "uri": uri,
    }


def _normalize_slot_bindings(
    values: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for raw_name, raw_binding in sorted((values or {}).items()):
        name = _text(raw_name, field_name="slot_name")
        if isinstance(raw_binding, Mapping) and "value" in raw_binding:
            value = _json_safe(raw_binding.get("value"), path=f"slot.{name}.value")
            source_cids_raw = raw_binding.get("source_cids") or ()
        else:
            value = _json_safe(raw_binding, path=f"slot.{name}.value")
            source_cids_raw = ()
        if value in (None, "", [], {}):
            raise AbbyVoiceResponseDAGError(
                f"slot binding {name!r} must not be empty"
            )
        if isinstance(source_cids_raw, str):
            source_cids_raw = (source_cids_raw,)
        if not isinstance(source_cids_raw, Sequence):
            raise AbbyVoiceResponseDAGError(
                f"slot binding {name!r} source_cids must be a sequence"
            )
        source_cids = tuple(
            sorted(
                {
                    _text(cid, field_name=f"slot.{name}.source_cid")
                    for cid in source_cids_raw
                }
            )
        )
        node_id = _stable_id(
            "vocabulary",
            {"slot_name": name, "source_cids": source_cids, "value": value},
        )
        result.append(
            {
                "id": node_id,
                "kind": "vocabulary",
                "slot_name": name,
                "source_cids": list(source_cids),
                "value": value,
            }
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ResponseDAGAppendCandidate:
    """Immutable local candidate suitable for an append-only Hub release."""

    cache_miss_event_id: str
    validation_receipt_id: str
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    rendered_text_sha256: str
    output_audio_sha256: str
    schema_version: str = ABBY_VOICE_RESPONSE_DAG_APPEND_SCHEMA_VERSION
    candidate_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        event_id = _text(
            self.cache_miss_event_id, field_name="cache_miss_event_id"
        )
        validation_id = _text(
            self.validation_receipt_id, field_name="validation_receipt_id"
        )
        text_digest = _digest(
            self.rendered_text_sha256, field_name="rendered_text_sha256"
        )
        audio_digest = _digest(
            self.output_audio_sha256, field_name="output_audio_sha256"
        )
        if self.schema_version != ABBY_VOICE_RESPONSE_DAG_APPEND_SCHEMA_VERSION:
            raise AbbyVoiceResponseDAGError(
                f"unsupported response-DAG append schema: {self.schema_version}"
            )
        nodes = tuple(
            sorted(
                (
                    _mapping(node, field_name=f"nodes[{index}]")
                    for index, node in enumerate(self.nodes)
                ),
                key=lambda node: str(node.get("id") or ""),
            )
        )
        edges = tuple(
            sorted(
                (
                    _mapping(edge, field_name=f"edges[{index}]")
                    for index, edge in enumerate(self.edges)
                ),
                key=lambda edge: str(edge.get("id") or ""),
            )
        )
        if not nodes or not edges:
            raise AbbyVoiceResponseDAGError(
                "response-DAG append requires nodes and edges"
            )
        node_ids = [_text(node.get("id"), field_name="node.id") for node in nodes]
        edge_ids = [_text(edge.get("id"), field_name="edge.id") for edge in edges]
        if len(node_ids) != len(set(node_ids)):
            raise AbbyVoiceResponseDAGError("response-DAG nodes must have unique IDs")
        if len(edge_ids) != len(set(edge_ids)):
            raise AbbyVoiceResponseDAGError("response-DAG edges must have unique IDs")
        known_nodes = set(node_ids)
        for edge in edges:
            if edge.get("source") not in known_nodes or edge.get("target") not in known_nodes:
                raise AbbyVoiceResponseDAGError(
                    f"edge {edge.get('id')!r} references an unknown node"
                )
        metadata = _mapping(self.metadata, field_name="metadata")

        object.__setattr__(self, "cache_miss_event_id", event_id)
        object.__setattr__(self, "validation_receipt_id", validation_id)
        object.__setattr__(self, "rendered_text_sha256", text_digest)
        object.__setattr__(self, "output_audio_sha256", audio_digest)
        object.__setattr__(
            self,
            "nodes",
            tuple(MappingProxyType(dict(node)) for node in nodes),
        )
        object.__setattr__(
            self,
            "edges",
            tuple(MappingProxyType(dict(edge)) for edge in edges),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(metadata)))

        computed = _stable_id("response-dag-candidate", self.identity_dict())
        if self.candidate_id and self.candidate_id != computed:
            raise AbbyVoiceResponseDAGError(
                "candidate_id does not match deterministic DAG content"
            )
        object.__setattr__(self, "candidate_id", computed)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "cache_miss_event_id": self.cache_miss_event_id,
            "edges": [dict(edge) for edge in self.edges],
            "metadata": dict(self.metadata),
            "nodes": [dict(node) for node in self.nodes],
            "output_audio_sha256": self.output_audio_sha256,
            "rendered_text_sha256": self.rendered_text_sha256,
            "schema_version": self.schema_version,
            "validation_receipt_id": self.validation_receipt_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_dict()
        payload["candidate_id"] = self.candidate_id
        payload["append_only"] = True
        return payload

    def file_payloads(self) -> dict[str, bytes]:
        """Return deterministic immutable files for Hub materialization."""

        prefix = f"response_dag/candidates/{self.candidate_id}"
        payloads = {
            f"{prefix}/candidate.json": _canonical_bytes(self.to_dict()) + b"\n"
        }
        for node in self.nodes:
            path = f"{prefix}/nodes/{node['id']}.json"
            payloads[path] = _canonical_bytes(dict(node)) + b"\n"
        for edge in self.edges:
            path = f"{prefix}/edges/{edge['id']}.json"
            payloads[path] = _canonical_bytes(dict(edge)) + b"\n"
        return dict(sorted(payloads.items()))

    def release_manifest(self) -> dict[str, Any]:
        payloads = self.file_payloads()
        files = [
            {
                "byte_length": len(body),
                "path": path,
                "sha256": sha256(body).hexdigest(),
            }
            for path, body in payloads.items()
        ]
        release_id = f"abby-voice-cache-miss-{self.candidate_id.rsplit('-', 1)[-1]}"
        identity = {
            "files": files,
            "release_id": release_id,
            "schema_version": ABBY_VOICE_RESPONSE_DAG_RELEASE_SCHEMA_VERSION,
        }
        return {
            **identity,
            "publication_status": "local_only",
            "release_sha256": sha256(_canonical_bytes(identity)).hexdigest(),
            "remote_writes": False,
        }

    def materialize(self, root: str | Path) -> dict[str, Any]:
        """Write immutable local files, refusing any mismatched existing path."""

        output_root = Path(root).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        for relative, body in self.file_payloads().items():
            safe = PurePosixPath(relative)
            if safe.is_absolute() or ".." in safe.parts:
                raise AbbyVoiceResponseDAGError(
                    f"unsafe response-DAG path: {relative}"
                )
            target = output_root.joinpath(*safe.parts)
            if target.exists():
                if not target.is_file() or target.is_symlink():
                    raise AbbyVoiceResponseDAGError(
                        f"append-only target is not a regular file: {relative}"
                    )
                if target.read_bytes() != body:
                    raise AbbyVoiceResponseDAGError(
                        f"append-only target already exists with different bytes: {relative}"
                    )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.partial")
            temporary.write_bytes(body)
            os.replace(temporary, target)
        return self.release_manifest()


def append_response_dag_candidate(
    cache_miss_event: Any,
    *,
    response_text: str,
    audio_descriptor: Any,
    template_text: str = "",
    slot_bindings: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ResponseDAGAppendCandidate:
    """Build an idempotent DAG append from a validated cache-miss event."""

    event = _mapping(cache_miss_event, field_name="cache_miss_event")
    if event.get("ready_for_dag_append") is not True:
        raise AbbyVoiceResponseDAGError(
            "cache miss must pass ASR validation before DAG append"
        )
    event_id = _text(event.get("event_id"), field_name="cache_miss_event.event_id")
    validation_id = _text(
        event.get("validation_receipt_id"),
        field_name="cache_miss_event.validation_receipt_id",
    )
    rendered = _text(response_text, field_name="response_text")
    rendered_digest = sha256(rendered.encode("utf-8")).hexdigest()
    if rendered_digest != _digest(
        event.get("rendered_text_sha256"),
        field_name="cache_miss_event.rendered_text_sha256",
    ):
        raise AbbyVoiceResponseDAGError(
            "response_text does not match cache-miss rendered_text_sha256"
        )

    audio_node = _normalize_audio_descriptor(audio_descriptor)
    event_audio_digest = _digest(
        event.get("output_audio_sha256"),
        field_name="cache_miss_event.output_audio_sha256",
    )
    if audio_node["content_sha256"] != event_audio_digest:
        raise AbbyVoiceResponseDAGError(
            "audio descriptor does not match cache-miss output_audio_sha256"
        )

    intent = _text(
        event.get("intent") or "general",
        field_name="cache_miss_event.intent",
    )
    bindings = _normalize_slot_bindings(slot_bindings)
    binding_names = tuple(node["slot_name"] for node in bindings)
    supplied_template_id = _text(
        event.get("template_id"),
        field_name="cache_miss_event.template_id",
        required=False,
    )
    normalized_template = _text(
        template_text, field_name="template_text", required=False
    )
    placeholders = _placeholder_names(normalized_template) if normalized_template else ()
    if normalized_template and set(placeholders) != set(binding_names):
        raise AbbyVoiceResponseDAGError(
            "template placeholders must exactly match slot bindings"
        )
    if bindings and not normalized_template:
        raise AbbyVoiceResponseDAGError(
            "slot bindings require a reusable slotted template"
        )
    template_id = supplied_template_id
    if normalized_template:
        template_id = template_id or stable_template_id(
            normalized_template,
            normalized_template,
            intent=intent,
        )

    response_id = _text(
        event.get("response_id"),
        field_name="cache_miss_event.response_id",
        required=False,
    ) or stable_response_id(rendered, rendered, intent=intent)
    response_node = {
        "cache_miss_event_id": event_id,
        "id": response_id,
        "intent": intent,
        "kind": "response",
        "slot_names": list(binding_names),
        "spoken_text": rendered,
        "template_id": template_id,
        "text": rendered,
        "text_sha256": rendered_digest,
        "validation_receipt_id": validation_id,
    }
    nodes: list[Mapping[str, Any]] = [response_node, audio_node]
    edges: list[Mapping[str, Any]] = [
        _edge(response_id, audio_node["audio_id"], "response_to_audio")
    ]
    if template_id:
        template_node = {
            "id": template_id,
            "intent": intent,
            "kind": "template",
            "slot_names": list(placeholders),
            "spoken_template": normalized_template or None,
            "template_text": normalized_template or None,
        }
        nodes.append(template_node)
        edges.append(_edge(template_id, response_id, "template_to_response"))
        for vocabulary_node in bindings:
            nodes.append(vocabulary_node)
            edges.append(
                _edge(
                    template_id,
                    str(vocabulary_node["id"]),
                    "template_to_vocabulary",
                )
            )
            edges.append(
                _edge(
                    str(vocabulary_node["id"]),
                    response_id,
                    "vocabulary_to_response",
                )
            )
    return ResponseDAGAppendCandidate(
        cache_miss_event_id=event_id,
        validation_receipt_id=validation_id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        rendered_text_sha256=rendered_digest,
        output_audio_sha256=event_audio_digest,
        metadata=dict(metadata or {}),
    )


__all__ = [
    "ABBY_VOICE_RESPONSE_DAG_APPEND_SCHEMA_VERSION",
    "ABBY_VOICE_RESPONSE_DAG_RELEASE_SCHEMA_VERSION",
    "AbbyVoiceResponseDAGError",
    "ResponseDAGAppendCandidate",
    "append_response_dag_candidate",
]
