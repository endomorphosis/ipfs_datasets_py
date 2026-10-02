"""Stable task identities shared by supervisor boards, queues, and leases."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


TASK_IDENTITY_SCHEMA = "ipfs_accelerate_py/agent-supervisor/task-identity@1"
_GLOB_MAGIC = frozenset("*?[")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode deterministic DAG-JSON-compatible bytes and reject floats."""

    def check(item: Any) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            raise ValueError("canonical task identity values cannot contain floats")
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("canonical task identity keys must be strings")
            for child in item.values():
                check(child)
            return
        raise ValueError(f"unsupported canonical task identity value: {type(item).__name__}")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def canonical_content_cid(value: Any) -> str:
    """Return a CIDv1 DAG-JSON/sha2-256 content identifier."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    raw = b"\x01\xa9\x02\x12\x20" + digest
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def normalize_identity_text(value: Any) -> str:
    """Normalize semantic prose without making it path or display-id dependent."""

    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def normalize_identity_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return re.sub(r"/+", "/", text).rstrip("/")


def normalize_exact_authorized_paths(value: Any) -> tuple[str, ...]:
    """Return bounded repository-relative paths with no glob authority."""

    normalized: set[str] = set()
    for item in _sequence(value):
        raw_path = str(item).strip()
        if "\0" in raw_path:
            continue
        path = normalize_identity_path(raw_path)
        if (
            not path
            or path == "."
            or path.startswith("/")
            or re.match(r"^[A-Za-z]:/", path)
            or ".." in Path(path).parts
            or any(marker in path for marker in _GLOB_MAGIC)
        ):
            continue
        normalized.add(path)
    return tuple(sorted(normalized))


def normalize_board_namespace(value: Any) -> str:
    text = normalize_identity_path(value)
    return text or "default"


def board_namespace_from_path(path: str | Path) -> str:
    """Return a compact provenance namespace; it is never identity material."""

    value = Path(path)
    return normalize_board_namespace(value.name or value.as_posix())


def _mapping_value(source: Mapping[str, Any], *keys: str) -> Any:
    normalized = {
        str(key).strip().casefold().replace("_", " "): value for key, value in source.items()
    }
    for key in keys:
        candidate = normalized.get(key.casefold().replace("_", " "))
        if candidate not in (None, "", [], ()):
            return candidate
    return ""


def _sequence(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [item for item in value if item not in (None, "")]
    return [value]


def _task_mapping(task: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(task, Mapping):
        source = dict(task)
    else:
        source = {
            name: getattr(task, name)
            for name in (
                "task_id",
                "title",
                "outputs",
                "acceptance",
                "track",
                "metadata",
            )
            if hasattr(task, name)
        }
    raw_metadata = source.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
    return source, metadata


@dataclass(frozen=True)
class TaskIdentity:
    """Canonical identity plus board-local provenance for one task alias."""

    canonical_task_key: str
    canonical_task_cid: str
    semantic_fingerprint: str
    display_task_id: str = ""
    board_namespace: str = "default"
    source_path: str = ""
    identity_version: int = 1

    @property
    def namespaced_alias(self) -> str:
        if not self.display_task_id:
            return ""
        return f"{self.board_namespace}::{self.display_task_id}"

    @property
    def short_id(self) -> str:
        return self.semantic_fingerprint[:12]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_task_identity(
    task: Any,
    *,
    board_namespace: str = "",
    source_path: str | Path = "",
) -> TaskIdentity:
    """Derive identity from semantic work while retaining local-id provenance."""

    source, metadata = _task_mapping(task)
    display_task_id = str(_mapping_value(source, "task id", "display task id") or "").strip()
    namespace = normalize_board_namespace(
        board_namespace
        or _mapping_value(metadata, "board namespace")
        or (board_namespace_from_path(source_path) if source_path else "default")
    )
    provided_key = str(
        _mapping_value(source, "canonical task key")
        or _mapping_value(metadata, "canonical task key")
        or ""
    ).strip()
    provided_cid = str(
        _mapping_value(source, "canonical task cid")
        or _mapping_value(metadata, "canonical task cid")
        or ""
    ).strip()
    allowed_paths = normalize_exact_authorized_paths(
        _mapping_value(source, "allowed paths")
        or _mapping_value(metadata, "allowed paths")
    )
    if provided_key and provided_cid:
        if allowed_paths:
            material = {
                "schema": TASK_IDENTITY_SCHEMA,
                "provided_identity": {
                    "canonical_task_key": provided_key,
                    "canonical_task_cid": provided_cid,
                },
                "authority": {
                    "additional_allowed_paths": list(allowed_paths),
                },
            }
            fingerprint = hashlib.sha256(
                canonical_json_bytes(material)
            ).hexdigest()
            return TaskIdentity(
                canonical_task_key=f"task/v1/{fingerprint}",
                canonical_task_cid=canonical_content_cid(material),
                semantic_fingerprint=fingerprint,
                display_task_id=display_task_id,
                board_namespace=namespace,
                source_path=normalize_identity_path(source_path),
            )
        key_suffix = provided_key.rsplit("/", 1)[-1].casefold()
        fingerprint = (
            key_suffix
            if re.fullmatch(r"[0-9a-f]{64}", key_suffix)
            else hashlib.sha256(canonical_json_bytes([provided_key, provided_cid])).hexdigest()
        )
        return TaskIdentity(
            canonical_task_key=provided_key,
            canonical_task_cid=provided_cid,
            semantic_fingerprint=fingerprint,
            display_task_id=display_task_id,
            board_namespace=namespace,
            source_path=normalize_identity_path(source_path),
        )
    explicit_key = normalize_identity_text(
        provided_key
        or _mapping_value(source, "dedupe key")
        or _mapping_value(metadata, "dedupe key")
    )
    if explicit_key:
        material: dict[str, Any] = {
            "schema": TASK_IDENTITY_SCHEMA,
            "explicit_key": explicit_key,
        }
    else:
        title = normalize_identity_text(
            _mapping_value(source, "title", "summary")
            or _mapping_value(metadata, "title", "summary")
        )
        outputs = sorted(
            {
                normalize_identity_path(item)
                for item in _sequence(
                    _mapping_value(source, "outputs", "paths", "files")
                    or _mapping_value(metadata, "outputs", "paths", "files")
                )
                if normalize_identity_path(item)
            }
        )
        acceptance = [
            normalize_identity_text(item)
            for item in _sequence(
                _mapping_value(source, "acceptance", "acceptance criteria")
                or _mapping_value(metadata, "acceptance", "acceptance criteria")
            )
            if normalize_identity_text(item)
        ]
        evidence = sorted(
            {
                normalize_identity_text(item)
                for item in _sequence(
                    _mapping_value(source, "missing evidence", "evidence")
                    or _mapping_value(metadata, "missing evidence", "evidence")
                )
                if normalize_identity_text(item)
            }
        )
        evidence_outputs = sorted(
            {
                normalize_identity_path(item)
                for item in _sequence(
                    _mapping_value(source, "evidence outputs")
                    or _mapping_value(metadata, "evidence outputs")
                )
                if normalize_identity_path(item)
            }
        )
        goal = normalize_identity_text(
            _mapping_value(source, "goal id", "goal packet key", "goal")
            or _mapping_value(metadata, "goal id", "goal packet key", "goal")
        )
        semantic_hint = normalize_identity_text(
            _mapping_value(source, "semantic key", "bundle key", "work scope", "fingerprint")
            or _mapping_value(metadata, "semantic key", "bundle key", "work scope", "fingerprint")
        )
        semantic = {
            key: value
            for key, value in {
                "title": title,
                "outputs": outputs,
                "acceptance": acceptance,
                "evidence": evidence,
                "evidence_outputs": evidence_outputs,
                "goal": goal,
                "semantic_hint": semantic_hint,
            }.items()
            if value
        }
        if not semantic:
            raise ValueError("task identity requires semantic work metadata")
        material = {"schema": TASK_IDENTITY_SCHEMA, "semantic": semantic}
    if allowed_paths:
        material["authority"] = {
            "additional_allowed_paths": list(allowed_paths),
        }

    semantic_fingerprint = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return TaskIdentity(
        canonical_task_key=f"task/v1/{semantic_fingerprint}",
        canonical_task_cid=canonical_content_cid(material),
        semantic_fingerprint=semantic_fingerprint,
        display_task_id=display_task_id,
        board_namespace=namespace,
        source_path=normalize_identity_path(source_path),
    )


def canonical_bundle_identity(bundle: Mapping[str, Any]) -> TaskIdentity:
    """Derive one execution identity from the canonical work items in a bundle."""

    raw_tasks = bundle.get("tasks")
    tasks = (
        [item for item in raw_tasks if isinstance(item, Mapping)]
        if isinstance(raw_tasks, Sequence) and not isinstance(raw_tasks, (str, bytes, bytearray))
        else []
    )
    identified_tasks: list[tuple[Mapping[str, Any], TaskIdentity]] = []
    for item in tasks:
        if not isinstance(item, Mapping):
            continue
        try:
            identity = canonical_task_identity(item)
        except ValueError:
            identity = canonical_task_identity(
                {
                    **dict(item),
                    "semantic_key": bundle.get("bundle_key") or "objective/general",
                }
            )
        identified_tasks.append((item, identity))

    selected_cids = {
        str(value).strip()
        for value in _sequence(bundle.get("execution_slice_task_cids"))
        if str(value).strip()
    }
    selected_ids = {
        str(value).strip()
        for value in _sequence(bundle.get("execution_slice_task_ids"))
        if str(value).strip()
    }
    if ("execution_slice_task_cids" in bundle or "execution_slice_task_ids" in bundle) and (
        selected_cids or selected_ids
    ):
        selected_tasks = [
            (item, identity)
            for item, identity in identified_tasks
            if identity.canonical_task_cid in selected_cids
            or str(item.get("canonical_task_cid") or item.get("task_cid") or "").strip()
            in selected_cids
            or str(item.get("task_id") or "").strip() in selected_ids
        ]
        if selected_tasks:
            identified_tasks = selected_tasks

    task_cids = [identity.canonical_task_cid for _, identity in identified_tasks]
    material = {
        "title": "agent supervisor bundle execution",
        "semantic_key": "|".join(sorted(task_cids))
        or normalize_identity_text(bundle.get("bundle_key") or "objective/general"),
        "outputs": [],
    }
    display_ids = sorted(
        str(item.get("task_id")) for item, _ in identified_tasks if item.get("task_id")
    )
    return canonical_task_identity(
        {**material, "task_id": ",".join(display_ids)},
        board_namespace=str(bundle.get("source_todo") or "bundle"),
        source_path=str(bundle.get("source_todo") or ""),
    )
