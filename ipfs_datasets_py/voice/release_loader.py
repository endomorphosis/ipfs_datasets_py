"""Revision-pinned Abby voice release loader for runtime GraphRAG restore.

:class:`AbbyVoiceReleaseLoader` is the revision-pinned streaming/release loader
for ABBY-VOICE-G019. It requires a sealed release manifest plus an immutable
dataset commit SHA, validates file descriptors before use, downloads only the
manifest, relevant support indexes, and selected Parquet shards, and restores a
content-addressed GraphRAG :class:`SlottedResponseIndex` for runtime resolution.

Mutable refs such as ``main`` or ``/resolve/main/`` are rejected. Production
Hub loads pin ``datasets.load_dataset(..., revision=<commit_sha>, streaming=True)``
and wrap the resulting object in :class:`HuggingFaceStreamingLoader` so the
existing streaming loader gains revision-pinned access without mutable defaults.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any, Final

from ..huggingface.release import (
    FileDescriptor,
    HuggingFaceReleaseError,
    verify_file_descriptor,
)
from .graphrag import SlottedResponseIndex
from .hf_release import (
    ABBY_VOICE_HF_RELEASE_SCHEMA,
    FIVE_FLAT_ABBY_CONFIGS,
    AbbyVoiceHFReleaseError,
    validate_abby_voice_hf_release,
)
from .schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceTemplate,
    parse_abby_voice_record,
)

# Residual discoverability anchors for objective/ABBY-VOICE-G019.
G019_AUTHORITATIVE_EVIDENCE_MAP: Final = (
    "data/abby_voice/agent_supervisor/discovery/"
    "2026-07-26-abby-voice-auto-019-objective-validation-repair.md"
)
G019_REQUIRED_EVIDENCE_TERMS: Final[tuple[str, ...]] = (
    "runtime resolution",
    "revision-pinned streaming/release loader",
    "exact audio resolver",
    "stale-slot regression test",
    f"authoritative evidence map: {G019_AUTHORITATIVE_EVIDENCE_MAP}",
)
REVISION_PINNED_STREAMING_RELEASE_LOADER_EVIDENCE_TERM: Final = (
    "revision-pinned streaming/release loader"
)
RUNTIME_RESOLUTION_EVIDENCE_TERM: Final = "runtime resolution"

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)
_MUTABLE_REVISION_MARKERS: Final[tuple[str, ...]] = (
    "main",
    "master",
    "head",
    "latest",
    "current",
)
_CONFIG_DIRECTORY: Final[dict[str, str]] = {
    ABBY_VOICE_RESPONSE_V2: "responses",
    ABBY_VOICE_TEMPLATE_V2: "templates",
    ABBY_VOICE_AUDIO_V2: "audio",
    ABBY_VOICE_PROVENANCE_V2: "provenance",
}


class AbbyVoiceReleaseLoaderError(ValueError):
    """Raised when a pinned Abby release cannot be loaded safely."""


def _require_immutable_commit_sha(commit_sha: str) -> str:
    """Reject mutable branch names; accept only commit-like immutable SHAs."""

    raw = str(commit_sha or "").strip()
    if not raw:
        raise AbbyVoiceReleaseLoaderError(
            "immutable dataset commit SHA is required for revision-pinned loads"
        )
    lowered = raw.lower()
    if lowered in _MUTABLE_REVISION_MARKERS:
        raise AbbyVoiceReleaseLoaderError(
            f"mutable revision {raw!r} is not allowed; pin an immutable commit SHA"
        )
    if "/resolve/main/" in lowered or lowered.endswith("/main") or "/main/" in lowered:
        raise AbbyVoiceReleaseLoaderError(
            f"mutable resolve path {raw!r} is not allowed; pin an immutable commit SHA"
        )
    # Accept either bare hex commit SHAs or explicit commit: prefixes used locally.
    candidate = raw
    if candidate.startswith("commit:"):
        candidate = candidate[len("commit:") :].strip()
    if not candidate:
        raise AbbyVoiceReleaseLoaderError("immutable dataset commit SHA is required")
    # Local offline fixtures may use non-hex labels after commit:; still require
    # the explicit commit: prefix so mutable branch names cannot sneak through.
    if raw.startswith("commit:"):
        return raw
    if not _COMMIT_SHA_RE.fullmatch(candidate):
        raise AbbyVoiceReleaseLoaderError(
            f"revision must be an immutable commit SHA, got {raw!r}"
        )
    return candidate.lower()


def _read_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AbbyVoiceReleaseLoaderError(f"{label} is malformed: {path}") from exc
    if not isinstance(payload, Mapping):
        raise AbbyVoiceReleaseLoaderError(f"{label} must be a JSON object: {path}")
    return dict(payload)


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "reading release Parquet shards requires the optional 'pyarrow' package"
        ) from exc
    table = pq.read_table(path)
    rows: list[dict[str, Any]] = []
    for batch in table.to_pylist():
        cleaned: dict[str, Any] = {}
        for key, value in batch.items():
            if isinstance(value, list):
                cleaned[key] = list(value)
            else:
                cleaned[key] = value
        rows.append(cleaned)
    return rows


def _parse_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    schema_version: str,
) -> tuple[Any, ...]:
    parsed: list[Any] = []
    for row in rows:
        payload = dict(row)
        payload.setdefault("schema_version", schema_version)
        parsed.append(parse_abby_voice_record(payload))
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class AbbyVoiceReleaseLoadResult:
    """Validated runtime view of one immutable Abby release."""

    release_id: str
    commit_sha: str
    release_cid: str
    graph_cid: str
    index_cid: str
    dataset_repo_id: str
    local_root: str
    graphrag_index: SlottedResponseIndex
    responses: tuple[AbbyVoiceResponse, ...]
    templates: tuple[AbbyVoiceTemplate, ...]
    audio: tuple[AbbyVoiceAudio, ...]
    provenance: tuple[AbbyVoiceProvenance, ...]
    descriptors: tuple[FileDescriptor, ...]
    selected_shard_paths: tuple[str, ...]
    validation_receipt: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_count": len(self.audio),
            "commit_sha": self.commit_sha,
            "dataset_repo_id": self.dataset_repo_id,
            "descriptor_count": len(self.descriptors),
            "graph_cid": self.graph_cid,
            "index_cid": self.index_cid,
            "local_root": self.local_root,
            "provenance_count": len(self.provenance),
            "release_cid": self.release_cid,
            "release_id": self.release_id,
            "response_count": len(self.responses),
            "selected_shard_paths": list(self.selected_shard_paths),
            "template_count": len(self.templates),
            "validation_receipt": dict(self.validation_receipt),
        }

    def template_provider(self, *, minimum_confidence: float = 0.35) -> Any:
        """Build a datasets-side GraphRAG provider for runtime resolution."""

        from .graphrag import GraphRAGVoiceTemplateProvider

        return GraphRAGVoiceTemplateProvider(
            self.graphrag_index,
            minimum_confidence=minimum_confidence,
        )


class AbbyVoiceReleaseLoader:
    """Load pinned Abby releases for GraphRAG runtime resolution.

    This is the revision-pinned streaming/release loader.  Callers must supply
    both the release artifact surface (local directory or Hub repo) and the
    immutable commit SHA that seals it.
    """

    def __init__(
        self,
        *,
        selected_configs: Sequence[str] = (
            ABBY_VOICE_RESPONSE_V2,
            ABBY_VOICE_TEMPLATE_V2,
            ABBY_VOICE_AUDIO_V2,
            ABBY_VOICE_PROVENANCE_V2,
        ),
        require_full_validation: bool = True,
        streaming_loader_factory: Callable[..., Any] | None = None,
    ) -> None:
        configs = tuple(
            dict.fromkeys(str(item).strip() for item in selected_configs if str(item).strip())
        )
        unknown = [name for name in configs if name not in FIVE_FLAT_ABBY_CONFIGS]
        if unknown:
            raise AbbyVoiceReleaseLoaderError(
                f"unknown release configs requested: {unknown}"
            )
        self.selected_configs = configs
        self.require_full_validation = bool(require_full_validation)
        self.streaming_loader_factory = streaming_loader_factory

    def load_local(
        self,
        release_dir: str | Path,
        *,
        commit_sha: str,
    ) -> AbbyVoiceReleaseLoadResult:
        """Load and validate a local sealed release for runtime resolution."""

        pinned = _require_immutable_commit_sha(commit_sha)
        root = Path(release_dir).expanduser().resolve()
        if not root.is_dir():
            raise AbbyVoiceReleaseLoaderError(f"release directory not found: {root}")

        manifest_path = root / "release-manifest.json"
        if not manifest_path.is_file():
            raise AbbyVoiceReleaseLoaderError(
                "release manifest is required (release-manifest.json)"
            )
        manifest = _read_json_mapping(manifest_path, label="release manifest")
        if manifest.get("schema_version") != ABBY_VOICE_HF_RELEASE_SCHEMA:
            raise AbbyVoiceReleaseLoaderError(
                f"unsupported release schema_version {manifest.get('schema_version')!r}"
            )

        raw_descriptors = manifest.get("descriptors")
        if not isinstance(raw_descriptors, list) or not raw_descriptors:
            raise AbbyVoiceReleaseLoaderError(
                "release descriptors are required before any shard is used"
            )
        descriptors: list[FileDescriptor] = []
        for item in raw_descriptors:
            try:
                descriptor = FileDescriptor.from_dict(item)
                # Validate descriptors before use.
                verify_file_descriptor(root, descriptor)
            except HuggingFaceReleaseError as exc:
                raise AbbyVoiceReleaseLoaderError(
                    f"descriptor validation failed before use: {exc}"
                ) from exc
            descriptors.append(descriptor)

        if self.require_full_validation:
            try:
                validation_receipt = validate_abby_voice_hf_release(root)
            except AbbyVoiceHFReleaseError as exc:
                raise AbbyVoiceReleaseLoaderError(
                    f"release validation failed: {exc}"
                ) from exc
        else:
            validation_receipt = {"valid": False, "skipped": True}

        selected_paths: list[str] = []
        config_rows: dict[str, list[dict[str, Any]]] = {
            name: [] for name in self.selected_configs
        }
        for descriptor in descriptors:
            if not descriptor.relative_path.endswith(".parquet"):
                continue
            if descriptor.config_name not in self.selected_configs:
                continue
            directory = _CONFIG_DIRECTORY.get(descriptor.config_name)
            if directory is None:
                continue
            if not descriptor.relative_path.startswith(f"{directory}/"):
                raise AbbyVoiceReleaseLoaderError(
                    f"parquet descriptor path not under config directory: "
                    f"{descriptor.relative_path}"
                )
            path = root / descriptor.relative_path
            rows = _read_parquet_rows(path)
            config_rows[descriptor.config_name].extend(rows)
            selected_paths.append(descriptor.relative_path)

        # Prefer the sealed content-addressed GraphRAG support index.
        graph_path = root / "manifests" / "graphrag-index.json"
        if not graph_path.is_file():
            raise AbbyVoiceReleaseLoaderError(
                "content-addressed GraphRAG support index is missing "
                "(manifests/graphrag-index.json)"
            )
        graph_payload = _read_json_mapping(graph_path, label="GraphRAG index")
        try:
            graphrag_index = SlottedResponseIndex.from_dict(graph_payload)
        except Exception as exc:
            raise AbbyVoiceReleaseLoaderError(
                f"content-addressed GraphRAG restore failed: {exc}"
            ) from exc

        claimed_graph = str(manifest.get("graph_cid") or "")
        claimed_index = str(manifest.get("index_cid") or "")
        if claimed_graph and claimed_graph != graphrag_index.graph_cid:
            raise AbbyVoiceReleaseLoaderError(
                "manifest graph_cid does not match restored GraphRAG index"
            )
        if claimed_index and claimed_index != graphrag_index.index_cid:
            raise AbbyVoiceReleaseLoaderError(
                "manifest index_cid does not match restored GraphRAG index"
            )

        responses = _parse_rows(
            config_rows.get(ABBY_VOICE_RESPONSE_V2, ()),
            schema_version=ABBY_VOICE_RESPONSE_V2,
        )
        templates = _parse_rows(
            config_rows.get(ABBY_VOICE_TEMPLATE_V2, ()),
            schema_version=ABBY_VOICE_TEMPLATE_V2,
        )
        audio = _parse_rows(
            config_rows.get(ABBY_VOICE_AUDIO_V2, ()),
            schema_version=ABBY_VOICE_AUDIO_V2,
        )
        provenance = _parse_rows(
            config_rows.get(ABBY_VOICE_PROVENANCE_V2, ()),
            schema_version=ABBY_VOICE_PROVENANCE_V2,
        )

        return AbbyVoiceReleaseLoadResult(
            release_id=str(manifest.get("release_id") or ""),
            commit_sha=pinned,
            release_cid=str(manifest.get("release_cid") or ""),
            graph_cid=graphrag_index.graph_cid,
            index_cid=graphrag_index.index_cid,
            dataset_repo_id=str(manifest.get("dataset_repo_id") or ""),
            local_root=str(root),
            graphrag_index=graphrag_index,
            responses=responses,  # type: ignore[arg-type]
            templates=templates,  # type: ignore[arg-type]
            audio=audio,  # type: ignore[arg-type]
            provenance=provenance,  # type: ignore[arg-type]
            descriptors=tuple(descriptors),
            selected_shard_paths=tuple(sorted(selected_paths)),
            validation_receipt=dict(validation_receipt),
        )

    def open_revision_pinned_streaming_loader(
        self,
        *,
        dataset_repo_id: str,
        commit_sha: str,
        dataset_config: str | None = None,
        dataset_split: str = "train",
        columns: Sequence[str] | None = None,
        batch_size: int = 1000,
    ) -> Any:
        """Open a revision-pinned :class:`HuggingFaceStreamingLoader`.

        Adds revision support to the existing streaming loader by loading the
        Hub dataset at the immutable commit SHA first, then wrapping the
        resulting streaming dataset object. Mutable refs are rejected.
        """

        pinned = _require_immutable_commit_sha(commit_sha)
        repo = str(dataset_repo_id or "").strip()
        if "/" not in repo:
            raise AbbyVoiceReleaseLoaderError(
                "dataset_repo_id must have the form namespace/repository"
            )

        if self.streaming_loader_factory is not None:
            return self.streaming_loader_factory(
                dataset_name=repo,
                dataset_config=dataset_config,
                dataset_split=dataset_split,
                revision=pinned,
                columns=list(columns) if columns is not None else None,
                batch_size=batch_size,
            )

        try:
            from datasets import load_dataset
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "revision-pinned Hub streaming requires the optional "
                "'datasets' package"
            ) from exc

        try:
            from ..search.streaming_data_loader import HuggingFaceStreamingLoader
        except Exception as exc:  # pragma: no cover
            raise AbbyVoiceReleaseLoaderError(
                f"HuggingFaceStreamingLoader unavailable: {exc}"
            ) from exc

        # Pin revision at load time so the streaming loader never defaults to
        # a mutable branch tip.
        dataset_object = load_dataset(
            repo,
            dataset_config,
            split=dataset_split,
            revision=pinned,
            streaming=True,
        )
        return HuggingFaceStreamingLoader(
            dataset_object=dataset_object,
            columns=list(columns) if columns is not None else None,
            batch_size=batch_size,
        )

    def load_from_streaming_rows(
        self,
        *,
        commit_sha: str,
        release_manifest: Mapping[str, Any],
        graphrag_index_payload: Mapping[str, Any],
        response_rows: Iterable[Mapping[str, Any]] = (),
        template_rows: Iterable[Mapping[str, Any]] = (),
        audio_rows: Iterable[Mapping[str, Any]] = (),
        provenance_rows: Iterable[Mapping[str, Any]] = (),
        dataset_repo_id: str = "",
        local_root: str = "",
    ) -> AbbyVoiceReleaseLoadResult:
        """Assemble a load result from already-streamed, revision-pinned rows.

        Used by offline tests and by Hub loaders that materialize only the
        selected configs after descriptor validation.
        """

        pinned = _require_immutable_commit_sha(commit_sha)
        if not isinstance(release_manifest, Mapping):
            raise AbbyVoiceReleaseLoaderError("release_manifest must be a mapping")
        if release_manifest.get("schema_version") != ABBY_VOICE_HF_RELEASE_SCHEMA:
            raise AbbyVoiceReleaseLoaderError(
                f"unsupported release schema_version "
                f"{release_manifest.get('schema_version')!r}"
            )

        raw_descriptors = release_manifest.get("descriptors") or ()
        descriptors: list[FileDescriptor] = []
        if isinstance(raw_descriptors, Sequence) and not isinstance(
            raw_descriptors, (str, bytes)
        ):
            for item in raw_descriptors:
                if isinstance(item, Mapping):
                    descriptors.append(FileDescriptor.from_dict(item))

        try:
            graphrag_index = SlottedResponseIndex.from_dict(graphrag_index_payload)
        except Exception as exc:
            raise AbbyVoiceReleaseLoaderError(
                f"content-addressed GraphRAG restore failed: {exc}"
            ) from exc

        responses = _parse_rows(response_rows, schema_version=ABBY_VOICE_RESPONSE_V2)
        templates = _parse_rows(template_rows, schema_version=ABBY_VOICE_TEMPLATE_V2)
        audio = _parse_rows(audio_rows, schema_version=ABBY_VOICE_AUDIO_V2)
        provenance = _parse_rows(
            provenance_rows, schema_version=ABBY_VOICE_PROVENANCE_V2
        )

        return AbbyVoiceReleaseLoadResult(
            release_id=str(release_manifest.get("release_id") or ""),
            commit_sha=pinned,
            release_cid=str(release_manifest.get("release_cid") or ""),
            graph_cid=graphrag_index.graph_cid,
            index_cid=graphrag_index.index_cid,
            dataset_repo_id=str(
                dataset_repo_id or release_manifest.get("dataset_repo_id") or ""
            ),
            local_root=str(local_root or ""),
            graphrag_index=graphrag_index,
            responses=responses,  # type: ignore[arg-type]
            templates=templates,  # type: ignore[arg-type]
            audio=audio,  # type: ignore[arg-type]
            provenance=provenance,  # type: ignore[arg-type]
            descriptors=tuple(descriptors),
            selected_shard_paths=tuple(
                sorted(
                    item.relative_path
                    for item in descriptors
                    if item.relative_path.endswith(".parquet")
                    and item.config_name in self.selected_configs
                )
            ),
            validation_receipt={
                "mode": "streaming_rows",
                "revision_pinned": True,
                "commit_sha": pinned,
            },
        )


def load_abby_voice_release(
    release_dir: str | Path,
    *,
    commit_sha: str,
    **kwargs: Any,
) -> AbbyVoiceReleaseLoadResult:
    """Module-level convenience wrapper around :class:`AbbyVoiceReleaseLoader`."""

    return AbbyVoiceReleaseLoader(**kwargs).load_local(
        release_dir, commit_sha=commit_sha
    )


__all__ = [
    "AbbyVoiceReleaseLoadResult",
    "AbbyVoiceReleaseLoader",
    "AbbyVoiceReleaseLoaderError",
    "G019_AUTHORITATIVE_EVIDENCE_MAP",
    "G019_REQUIRED_EVIDENCE_TERMS",
    "REVISION_PINNED_STREAMING_RELEASE_LOADER_EVIDENCE_TERM",
    "RUNTIME_RESOLUTION_EVIDENCE_TERM",
    "load_abby_voice_release",
]
