"""Deterministic local merge of admitted audio into an Abby dataset bundle.

This module is deliberately side-effect free.  It neither writes a release nor
calls a remote publisher.  The returned bundle and rebuilt GraphRAG index can be
passed directly to :class:`~ipfs_datasets_py.voice.hf_release.AbbyVoiceHFReleaseBuilder`
for a separate local release-validation step.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from .graphrag import SlottedResponseIndex
from .normalize import NORMALIZATION_VERSION, QUALITY_REPORT_VERSION
from .reconcile import (
    AudioDispositionReason,
    AudioDispositionStatus,
    AudioReconciliationResult,
)
from .schema import (
    ABBY_VOICE_AUDIO_V2,
    AbbyVoiceAudio,
    AbbyVoiceDatasetBundle,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    stable_audio_id,
    validate_bundle,
    validate_publishable,
)

ABBY_VOICE_DATASET_MERGE_SCHEMA_VERSION = "abby_voice_dataset_merge_v1"
ABBY_VOICE_NORMALIZED_BUILD_SCHEMA_VERSION = "abby_voice_dataset_build_v2"
ABBY_VOICE_NORMALIZED_BUILD_MANIFEST_NAME = "manifest.json"

_NORMALIZED_ROW_FILES = {
    "audio.jsonl": "audio_id",
    "provenance.jsonl": "provenance_id",
    "responses.jsonl": "response_id",
    "templates.jsonl": "template_id",
}
_NORMALIZED_SUPPORT_JSONL_FILES = frozenset(
    {
        "duplicate-ledger.jsonl",
        "quarantine.jsonl",
        "warnings.jsonl",
    }
)
_NORMALIZED_JSON_FILES = frozenset(
    {
        "quality-report.json",
        "splits.json",
    }
)
_NORMALIZED_BUILD_FILES = frozenset(
    {
        *_NORMALIZED_ROW_FILES,
        *_NORMALIZED_SUPPORT_JSONL_FILES,
        *_NORMALIZED_JSON_FILES,
    }
)
_NORMALIZED_JSONL_FILES = frozenset(
    {*_NORMALIZED_ROW_FILES, *_NORMALIZED_SUPPORT_JSONL_FILES}
)


class AbbyVoiceDatasetMergeError(ValueError):
    """Raised when admitted audio cannot be bound to the normalized dataset."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _require_sha256(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AbbyVoiceDatasetMergeError(
            f"{label} must be a full lowercase SHA-256"
        )
    return value


def _parse_strict_json(payload: bytes, *, label: str) -> Any:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AbbyVoiceDatasetMergeError(f"{label} must be UTF-8 JSON") from exc

    def reject_duplicate_keys(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AbbyVoiceDatasetMergeError(
                    f"{label} contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except AbbyVoiceDatasetMergeError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AbbyVoiceDatasetMergeError(f"{label} is malformed JSON") from exc


def _parse_canonical_jsonl(
    payload: bytes,
    *,
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    if not payload:
        return ()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AbbyVoiceDatasetMergeError(f"{label} must be UTF-8 JSONL") from exc
    if not text.endswith("\n"):
        raise AbbyVoiceDatasetMergeError(
            f"{label} must end with a newline"
        )
    raw_lines = text.splitlines()
    if not raw_lines or any(not line for line in raw_lines):
        raise AbbyVoiceDatasetMergeError(
            f"{label} must not contain blank JSONL rows"
        )
    rows: list[Mapping[str, Any]] = []
    rendered: list[bytes] = []
    for line_number, line in enumerate(raw_lines, start=1):
        value = _parse_strict_json(
            line.encode("utf-8"),
            label=f"{label} row {line_number}",
        )
        if not isinstance(value, Mapping):
            raise AbbyVoiceDatasetMergeError(
                f"{label} row {line_number} must be a JSON object"
            )
        rows.append(value)
        try:
            rendered.append(_canonical_bytes(value) + b"\n")
        except (TypeError, ValueError) as exc:
            raise AbbyVoiceDatasetMergeError(
                f"{label} row {line_number} is not canonical JSON"
            ) from exc
    if b"".join(rendered) != payload:
        raise AbbyVoiceDatasetMergeError(
            f"{label} does not use canonical JSONL serialization"
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class AbbyVoiceNormalizedDatasetLoadResult:
    """Validated view of one manifest-pinned normalized dataset build."""

    bundle: AbbyVoiceDatasetBundle
    normalized_dir: str
    manifest_sha256: str
    manifest: Mapping[str, Any]
    normalization_version: str
    source_manifest_count: int
    input_record_count: int

    def __post_init__(self) -> None:
        digest = _require_sha256(
            self.manifest_sha256,
            label="manifest_sha256",
        )
        if not isinstance(self.bundle, AbbyVoiceDatasetBundle):
            raise TypeError("bundle must be an AbbyVoiceDatasetBundle")
        if (
            not isinstance(self.normalized_dir, str)
            or not self.normalized_dir
        ):
            raise AbbyVoiceDatasetMergeError(
                "normalized_dir must be a non-empty path"
            )
        if self.normalization_version != NORMALIZATION_VERSION:
            raise AbbyVoiceDatasetMergeError(
                "normalization_version does not match the supported build"
            )
        for name in ("source_manifest_count", "input_record_count"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise AbbyVoiceDatasetMergeError(
                    f"{name} must be a non-negative integer"
                )
        if not isinstance(self.manifest, Mapping):
            raise TypeError("manifest must be a mapping")
        # Retain an independent JSON-safe snapshot. The manifest digest remains
        # the authoritative identity if a caller later modifies its local copy.
        manifest_copy = json.loads(
            json.dumps(
                dict(self.manifest),
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        )
        object.__setattr__(self, "manifest", manifest_copy)
        object.__setattr__(self, "manifest_sha256", digest)

    @property
    def manifest_id(self) -> str:
        return (
            "abby-voice-normalized-build:sha256:"
            f"{self.manifest_sha256}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_count": len(self.bundle.audio),
            "input_record_count": self.input_record_count,
            "manifest_id": self.manifest_id,
            "manifest_sha256": self.manifest_sha256,
            "normalization_version": self.normalization_version,
            "normalized_dir": self.normalized_dir,
            "provenance_count": len(self.bundle.provenance),
            "response_count": len(self.bundle.responses),
            "source_manifest_count": self.source_manifest_count,
            "template_count": len(self.bundle.templates),
        }


def load_normalized_dataset_bundle(
    normalized_dir: str | Path,
    *,
    expected_manifest_sha256: str,
) -> AbbyVoiceNormalizedDatasetLoadResult:
    """Load one exact, manifest-pinned ``abby_voice_dataset_build_v2`` tree.

    The loader fails closed on symlinks, unexpected directory entries,
    non-canonical JSON, descriptor inconsistencies, malformed canonical rows,
    and broken cross-config references. It performs no filesystem writes.
    """

    expected_digest = _require_sha256(
        expected_manifest_sha256,
        label="expected_manifest_sha256",
    )
    raw_root = Path(normalized_dir).expanduser()
    if raw_root.is_symlink():
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset directory must not be a symlink"
        )
    root = raw_root.resolve()
    if not root.is_dir():
        raise AbbyVoiceDatasetMergeError(
            f"normalized dataset directory does not exist: {root}"
        )

    expected_directory_names = {
        *_NORMALIZED_BUILD_FILES,
        ABBY_VOICE_NORMALIZED_BUILD_MANIFEST_NAME,
    }
    actual_directory_names = {item.name for item in root.iterdir()}
    if actual_directory_names != expected_directory_names:
        missing = sorted(expected_directory_names - actual_directory_names)
        extra = sorted(actual_directory_names - expected_directory_names)
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset directory has an unexpected file set: "
            f"missing={missing!r}, extra={extra!r}"
        )
    for name in sorted(expected_directory_names):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset artifact is not a regular file: {name}"
            )

    manifest_path = root / ABBY_VOICE_NORMALIZED_BUILD_MANIFEST_NAME
    manifest_bytes = manifest_path.read_bytes()
    actual_manifest_sha256 = sha256(manifest_bytes).hexdigest()
    if actual_manifest_sha256 != expected_digest:
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset manifest SHA-256 mismatch: "
            f"expected {expected_digest}, received {actual_manifest_sha256}"
        )
    manifest = _parse_strict_json(
        manifest_bytes,
        label="normalized dataset manifest",
    )
    expected_manifest_keys = {
        "deterministic",
        "files",
        "input_record_count",
        "normalization_version",
        "schema_version",
        "source_manifest_count",
    }
    if (
        not isinstance(manifest, Mapping)
        or set(manifest) != expected_manifest_keys
        or manifest.get("schema_version")
        != ABBY_VOICE_NORMALIZED_BUILD_SCHEMA_VERSION
        or manifest.get("normalization_version") != NORMALIZATION_VERSION
        or manifest.get("deterministic") is not True
    ):
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset manifest has an unsupported shape or policy"
        )
    try:
        canonical_manifest = _pretty_json_bytes(manifest)
    except (TypeError, ValueError) as exc:
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset manifest is not canonical JSON"
        ) from exc
    if canonical_manifest != manifest_bytes:
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset manifest is not canonical"
        )
    for count_name in ("source_manifest_count", "input_record_count"):
        count = manifest[count_name]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset manifest {count_name} is invalid"
            )

    raw_descriptors = manifest["files"]
    if not isinstance(raw_descriptors, list):
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset manifest files must be a list"
        )
    descriptors: dict[str, Mapping[str, Any]] = {}
    descriptor_paths: list[str] = []
    for index, descriptor in enumerate(raw_descriptors):
        if not isinstance(descriptor, Mapping):
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset file descriptor {index} must be an object"
            )
        path_value = descriptor.get("path")
        if not isinstance(path_value, str):
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset file descriptor {index} has no path"
            )
        expected_descriptor_keys = {
            "byte_length",
            "path",
            "sha256",
            *(
                ("row_count",)
                if path_value in _NORMALIZED_JSONL_FILES
                else ()
            ),
        }
        if set(descriptor) != expected_descriptor_keys:
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset descriptor shape is invalid: {path_value}"
            )
        if path_value in descriptors:
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset descriptor path is duplicated: {path_value}"
            )
        byte_length = descriptor["byte_length"]
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length < 0
        ):
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset byte_length is invalid: {path_value}"
            )
        _require_sha256(
            descriptor["sha256"],
            label=f"{path_value} descriptor sha256",
        )
        if path_value in _NORMALIZED_JSONL_FILES:
            row_count = descriptor["row_count"]
            if (
                isinstance(row_count, bool)
                or not isinstance(row_count, int)
                or row_count < 0
            ):
                raise AbbyVoiceDatasetMergeError(
                    f"normalized dataset row_count is invalid: {path_value}"
                )
        descriptors[path_value] = descriptor
        descriptor_paths.append(path_value)
    if (
        set(descriptors) != _NORMALIZED_BUILD_FILES
        or descriptor_paths != sorted(_NORMALIZED_BUILD_FILES)
    ):
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset manifest has an unexpected file descriptor set"
        )

    payloads: dict[str, bytes] = {}
    jsonl_rows: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for name in sorted(_NORMALIZED_BUILD_FILES):
        content = (root / name).read_bytes()
        descriptor = descriptors[name]
        if (
            len(content) != descriptor["byte_length"]
            or sha256(content).hexdigest() != descriptor["sha256"]
        ):
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset artifact checksum mismatch: {name}"
            )
        payloads[name] = content
        if name in _NORMALIZED_JSONL_FILES:
            rows = _parse_canonical_jsonl(content, label=name)
            if len(rows) != descriptor["row_count"]:
                raise AbbyVoiceDatasetMergeError(
                    f"normalized dataset row_count mismatch: {name}"
                )
            jsonl_rows[name] = rows

    json_documents: dict[str, Mapping[str, Any]] = {}
    for name in sorted(_NORMALIZED_JSON_FILES):
        value = _parse_strict_json(payloads[name], label=name)
        if not isinstance(value, Mapping):
            raise AbbyVoiceDatasetMergeError(
                f"{name} must contain a JSON object"
            )
        try:
            canonical_value = _pretty_json_bytes(value)
        except (TypeError, ValueError) as exc:
            raise AbbyVoiceDatasetMergeError(
                f"{name} is not canonical JSON"
            ) from exc
        if canonical_value != payloads[name]:
            raise AbbyVoiceDatasetMergeError(
                f"{name} does not use canonical JSON serialization"
            )
        json_documents[name] = value

    quality = json_documents["quality-report.json"]
    accepted = quality.get("accepted")
    if (
        quality.get("schema_version") != QUALITY_REPORT_VERSION
        or quality.get("normalization_version") != NORMALIZATION_VERSION
        or quality.get("source_manifest_count")
        != manifest["source_manifest_count"]
        or quality.get("input_record_count") != manifest["input_record_count"]
        or not isinstance(accepted, Mapping)
    ):
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset quality report does not bind the manifest"
        )
    accepted_counts = {
        "audio": descriptors["audio.jsonl"]["row_count"],
        "provenance": descriptors["provenance.jsonl"]["row_count"],
        "responses": descriptors["responses.jsonl"]["row_count"],
        "templates": descriptors["templates.jsonl"]["row_count"],
    }
    if dict(accepted) != accepted_counts:
        raise AbbyVoiceDatasetMergeError(
            "normalized dataset quality accepted counts do not match row descriptors"
        )

    try:
        bundle = validate_bundle(
            responses=jsonl_rows["responses.jsonl"],
            templates=jsonl_rows["templates.jsonl"],
            audio=jsonl_rows["audio.jsonl"],
            provenance=jsonl_rows["provenance.jsonl"],
            require_references=True,
        )
    except (TypeError, ValueError) as exc:
        raise AbbyVoiceDatasetMergeError(
            f"normalized dataset canonical rows are invalid: {exc}"
        ) from exc
    row_groups = {
        "audio.jsonl": bundle.audio,
        "provenance.jsonl": bundle.provenance,
        "responses.jsonl": bundle.responses,
        "templates.jsonl": bundle.templates,
    }
    for name, rows in row_groups.items():
        identity_field = _NORMALIZED_ROW_FILES[name]
        identities = [
            str(getattr(row, identity_field))
            for row in rows
        ]
        if identities != sorted(identities):
            raise AbbyVoiceDatasetMergeError(
                f"normalized dataset rows are not canonically ordered: {name}"
            )

    return AbbyVoiceNormalizedDatasetLoadResult(
        bundle=bundle,
        normalized_dir=str(root),
        manifest_sha256=actual_manifest_sha256,
        manifest=manifest,
        normalization_version=str(manifest["normalization_version"]),
        source_manifest_count=int(manifest["source_manifest_count"]),
        input_record_count=int(manifest["input_record_count"]),
    )


def _bundle_dict(bundle: AbbyVoiceDatasetBundle) -> dict[str, list[dict[str, Any]]]:
    return {
        "audio": [row.to_dict() for row in bundle.audio],
        "provenance": [row.to_dict() for row in bundle.provenance],
        "responses": [row.to_dict() for row in bundle.responses],
        "templates": [row.to_dict() for row in bundle.templates],
    }


@dataclass(frozen=True, slots=True)
class AbbyVoiceDatasetMergeResult:
    """Content-addressed receipt for one pure local dataset merge."""

    bundle: AbbyVoiceDatasetBundle
    graphrag_index: SlottedResponseIndex
    reconciliation_id: str
    admitted_audio_ids: tuple[str, ...]
    response_audio_links: tuple[tuple[str, str], ...]
    require_publishable: bool = True
    schema_version: str = ABBY_VOICE_DATASET_MERGE_SCHEMA_VERSION
    merge_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != ABBY_VOICE_DATASET_MERGE_SCHEMA_VERSION:
            raise AbbyVoiceDatasetMergeError("unsupported dataset merge schema")
        if (
            not isinstance(self.reconciliation_id, str)
            or not self.reconciliation_id.strip()
            or self.reconciliation_id.strip() != self.reconciliation_id
        ):
            raise AbbyVoiceDatasetMergeError(
                "reconciliation_id must be a non-empty canonical string"
            )
        if not isinstance(self.require_publishable, bool):
            raise TypeError("require_publishable must be boolean")
        audio_ids = tuple(sorted(self.admitted_audio_ids))
        links = tuple(sorted(self.response_audio_links))
        if len(audio_ids) != len(set(audio_ids)):
            raise AbbyVoiceDatasetMergeError("admitted audio IDs must be unique")
        if len(links) != len(set(links)):
            raise AbbyVoiceDatasetMergeError("response/audio links must be unique")
        if (
            len(links) != len(audio_ids)
            or {audio_id for _, audio_id in links} != set(audio_ids)
        ):
            raise AbbyVoiceDatasetMergeError(
                "every admitted audio ID must have exactly one response link"
            )
        if self.graphrag_index.bundle != self.bundle:
            raise AbbyVoiceDatasetMergeError(
                "GraphRAG index does not bind the merged dataset bundle"
            )
        object.__setattr__(self, "admitted_audio_ids", audio_ids)
        object.__setattr__(self, "response_audio_links", links)
        computed = (
            "abby-voice-dataset-merge:sha256:"
            + sha256(_canonical_bytes(self._identity_document())).hexdigest()
        )
        if self.merge_id and self.merge_id != computed:
            raise AbbyVoiceDatasetMergeError(
                "merge_id does not match deterministic merge content"
            )
        object.__setattr__(self, "merge_id", computed)

    def _identity_document(self) -> dict[str, Any]:
        return {
            "admitted_audio_ids": list(self.admitted_audio_ids),
            "bundle": _bundle_dict(self.bundle),
            "graph_cid": self.graphrag_index.graph_cid,
            "index_cid": self.graphrag_index.index_cid,
            "reconciliation_id": self.reconciliation_id,
            "require_publishable": self.require_publishable,
            "response_audio_links": [
                {"audio_id": audio_id, "response_id": response_id}
                for response_id, audio_id in self.response_audio_links
            ],
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"merge_id": self.merge_id, **self._identity_document()}

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())


def _merge_rows(
    existing: tuple[Any, ...],
    admitted: tuple[Any, ...],
    *,
    id_attribute: str,
    label: str,
) -> tuple[Any, ...]:
    by_id = {getattr(row, id_attribute): row for row in existing}
    for row in admitted:
        identity = getattr(row, id_attribute)
        previous = by_id.get(identity)
        if previous is not None and previous != row:
            raise AbbyVoiceDatasetMergeError(
                f"admitted {label} conflicts with existing ID {identity!r}"
            )
        by_id[identity] = row
    return tuple(sorted(by_id.values(), key=lambda row: getattr(row, id_attribute)))


def _validate_admission_bindings(
    *,
    responses_by_id: dict[str, AbbyVoiceResponse],
    admission: AudioReconciliationResult,
) -> tuple[tuple[AbbyVoiceAudio, ...], tuple[AbbyVoiceProvenance, ...]]:
    linked = tuple(admission.linked_audio)
    linked_by_id = {row.audio_id: row for row in linked}
    linked_dispositions = tuple(
        item
        for item in admission.dispositions
        if item.status is AudioDispositionStatus.LINKED
    )
    if linked and (
        not admission.policy_identity
        or admission.policy_identity.strip() != admission.policy_identity
    ):
        raise AbbyVoiceDatasetMergeError(
            "linked admission must have a canonical policy identity"
        )
    dispositions_by_audio_id = {
        item.audio_id: item for item in linked_dispositions if item.audio_id
    }
    if (
        len(dispositions_by_audio_id) != len(linked_dispositions)
        or set(dispositions_by_audio_id) != set(linked_by_id)
    ):
        raise AbbyVoiceDatasetMergeError(
            "linked dispositions must correspond one-to-one with admitted audio"
        )

    referenced_provenance: set[str] = set()
    for audio_id, row in linked_by_id.items():
        if (
            not row.response_id
            or row.template_id is not None
            or row.segment_kind != "response"
        ):
            raise AbbyVoiceDatasetMergeError(
                f"admitted audio {audio_id!r} is not response audio"
            )
        response = responses_by_id.get(row.response_id)
        if response is None:
            raise AbbyVoiceDatasetMergeError(
                f"admitted audio {audio_id!r} names unknown response "
                f"{row.response_id!r}"
            )
        if row.audio_id != stable_audio_id(
            row.content_sha256, segment_kind=row.segment_kind
        ):
            raise AbbyVoiceDatasetMergeError(
                f"admitted audio {audio_id!r} does not have its stable content ID"
            )
        if (
            row.spoken_text != response.spoken_text
            or row.text_sha256 != response.content_sha256
            or row.locale != response.locale
        ):
            raise AbbyVoiceDatasetMergeError(
                f"admitted audio {audio_id!r} does not match response text and locale"
            )
        if (
            row.license_id != response.license_id
            or row.consent_status != response.consent_status
        ):
            raise AbbyVoiceDatasetMergeError(
                f"admitted audio {audio_id!r} does not match response rights"
            )
        if not row.provenance_ids:
            raise AbbyVoiceDatasetMergeError(
                f"admitted audio {audio_id!r} has no provenance"
            )
        disposition = dispositions_by_audio_id[audio_id]
        if (
            disposition.reason is not AudioDispositionReason.PROMOTED
            or disposition.subject_id != row.response_id
            or disposition.artifact_sha256 != row.content_sha256
            or disposition.policy_identity != admission.policy_identity
        ):
            raise AbbyVoiceDatasetMergeError(
                f"linked disposition for {audio_id!r} does not bind the admitted row"
            )
        referenced_provenance.update(row.provenance_ids)

    provenance = tuple(admission.provenance)
    provenance_by_id = {row.provenance_id: row for row in provenance}
    if (
        len(provenance_by_id) != len(provenance)
        or set(provenance_by_id) != referenced_provenance
    ):
        raise AbbyVoiceDatasetMergeError(
            "admission provenance must exactly cover admitted audio"
        )
    for provenance_id, row in provenance_by_id.items():
        if (
            row.subject_schema_version != ABBY_VOICE_AUDIO_V2
            or row.subject_id not in linked_by_id
        ):
            raise AbbyVoiceDatasetMergeError(
                f"admission provenance {provenance_id!r} is not bound to admitted audio"
            )
        audio = linked_by_id[row.subject_id]
        if (
            provenance_id not in audio.provenance_ids
            or row.source_sha256 != audio.content_sha256
            or row.locale != audio.locale
            or row.license_id != audio.license_id
            or row.consent_status != audio.consent_status
        ):
            raise AbbyVoiceDatasetMergeError(
                f"admission provenance {provenance_id!r} does not bind its audio row"
            )
    return linked, provenance


def merge_admitted_audio(
    bundle: AbbyVoiceDatasetBundle,
    admission: AudioReconciliationResult,
    *,
    require_publishable: bool = True,
) -> AbbyVoiceDatasetMergeResult:
    """Merge admitted response audio and rebuild the local GraphRAG index.

    Existing identical rows make this operation idempotent.  Conflicting IDs,
    missing response bindings, stale text/locale/rights, forged dispositions,
    or incomplete provenance fail closed.  No filesystem or network operation
    occurs.
    """

    if not isinstance(bundle, AbbyVoiceDatasetBundle):
        raise TypeError("bundle must be an AbbyVoiceDatasetBundle")
    if not isinstance(admission, AudioReconciliationResult):
        raise TypeError("admission must be an AudioReconciliationResult")
    if not isinstance(require_publishable, bool):
        raise TypeError("require_publishable must be boolean")

    base = validate_bundle(
        responses=bundle.responses,
        templates=bundle.templates,
        audio=bundle.audio,
        provenance=bundle.provenance,
    )
    responses_by_id = {row.response_id: row for row in base.responses}
    admitted_audio, admitted_provenance = _validate_admission_bindings(
        responses_by_id=responses_by_id,
        admission=admission,
    )

    audio = _merge_rows(
        base.audio,
        admitted_audio,
        id_attribute="audio_id",
        label="audio",
    )
    provenance = _merge_rows(
        base.provenance,
        admitted_provenance,
        id_attribute="provenance_id",
        label="provenance",
    )
    links_by_response: dict[str, set[str]] = {}
    for row in admitted_audio:
        links_by_response.setdefault(str(row.response_id), set()).add(row.audio_id)
    responses = tuple(
        sorted(
            (
                replace(
                    row,
                    audio_ids=tuple(
                        sorted(
                            set(row.audio_ids)
                            | links_by_response.get(row.response_id, set())
                        )
                    ),
                )
                for row in base.responses
            ),
            key=lambda row: row.response_id,
        )
    )
    templates = tuple(sorted(base.templates, key=lambda row: row.template_id))
    merged = validate_bundle(
        responses=responses,
        templates=templates,
        audio=audio,
        provenance=provenance,
    )
    if require_publishable:
        validate_publishable(merged)
    graphrag_index = SlottedResponseIndex.from_rows(
        templates=merged.templates,
        responses=merged.responses,
        audio=merged.audio,
        provenance=merged.provenance,
    )
    admitted_ids = tuple(row.audio_id for row in admitted_audio)
    links = tuple(
        (str(row.response_id), row.audio_id) for row in admitted_audio
    )
    return AbbyVoiceDatasetMergeResult(
        bundle=merged,
        graphrag_index=graphrag_index,
        reconciliation_id=admission.reconciliation_id,
        admitted_audio_ids=admitted_ids,
        response_audio_links=links,
        require_publishable=require_publishable,
    )


__all__ = [
    "ABBY_VOICE_DATASET_MERGE_SCHEMA_VERSION",
    "ABBY_VOICE_NORMALIZED_BUILD_MANIFEST_NAME",
    "ABBY_VOICE_NORMALIZED_BUILD_SCHEMA_VERSION",
    "AbbyVoiceDatasetMergeError",
    "AbbyVoiceDatasetMergeResult",
    "AbbyVoiceNormalizedDatasetLoadResult",
    "load_normalized_dataset_bundle",
    "merge_admitted_audio",
]
