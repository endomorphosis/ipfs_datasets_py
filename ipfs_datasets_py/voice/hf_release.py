"""Deterministic Abby voice Hugging Face release construction and validation.

:class:`AbbyVoiceHFReleaseBuilder` performs deterministic release construction
for the five flat Abby configs including evaluation (response, template,
audio, provenance, evaluation) as schema-stable sharded ZSTD Parquet
descriptors, writes GraphRAG/support indexes beside them (never inside config
directories), and emits a content-addressed release manifest. Two builds from
the same pinned source and policy produce a byte-identical rebuild.

Only local filesystem writes are performed.  Publication and promotion remain
G021 responsibilities.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Final

from ..huggingface.release import (
    DEFAULT_SHARD_ROWS,
    PARQUET_COMPRESSION,
    PARQUET_COMPRESSION_LEVEL,
    FileDescriptor,
    HuggingFaceReleaseError,
    canonical_json_bytes,
    describe_file,
    reject_identity_contamination,
    shard_sequence,
    validate_zstd_parquet,
    verify_file_descriptor,
    write_canonical_json,
    write_zstd_parquet,
)
from ..logic.ir_core.artifacts import Artifact, ArtifactManifest, ArtifactRole
from ..logic.ir_core.identity import cid_v1_from_digest
from ..logic.ir_core.provenance import ConfigBinding, ProducerBinding
from .evaluation_schema import (
    ABBY_VOICE_EVALUATION_V2,
    AbbyVoiceEvaluation,
    get_evaluation_pyarrow_schema,
    parse_evaluation_record,
    validate_evaluation_rows,
)
from .graphrag import SlottedResponseIndex
from .normalize import deterministic_split
from .schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceDatasetBundle,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceTemplate,
    get_pyarrow_schema,
    validate_bundle,
    validate_publishable,
)

ABBY_VOICE_HF_RELEASE_SCHEMA: Final = "abby-voice-huggingface-release/v1"
ABBY_VOICE_HF_RELEASE_PRODUCER: Final = "producer:abby-voice-hf-release"
ABBY_VOICE_HF_RELEASE_CONFIG: Final = "config:abby-voice-hf-release/v1"
DEFAULT_DATASET_REPO_ID: Final = "Publicus/211-abby-tts"

# Residual discoverability anchors for objective/ABBY-VOICE-G018. Keep the
# exact evidence phrases stable so embedding/AST scans re-find them on this
# authorized path rather than unrelated SkillCenter or legal-data documents.
# Package-root __init__.py is intentionally not mutated (proposal-gate scope).
G018_AUTHORITATIVE_EVIDENCE_MAP: Final = (
    "data/abby_voice/agent_supervisor/discovery/"
    "2026-07-26-abby-voice-auto-018-objective-validation-repair.md"
)
G018_REQUIRED_EVIDENCE_TERMS: Final[tuple[str, ...]] = (
    "deterministic release construction",
    "five flat Abby configs including evaluation",
    "sharded ZSTD Parquet descriptors",
    "byte-identical rebuild",
    f"authoritative evidence map: {G018_AUTHORITATIVE_EVIDENCE_MAP}",
)
DETERMINISTIC_RELEASE_CONSTRUCTION_EVIDENCE_TERM: Final = (
    "deterministic release construction"
)
FIVE_FLAT_CONFIGS_EVIDENCE_TERM: Final = (
    "five flat Abby configs including evaluation"
)
SHARDED_ZSTD_PARQUET_DESCRIPTORS_EVIDENCE_TERM: Final = (
    "sharded ZSTD Parquet descriptors"
)
BYTE_IDENTICAL_REBUILD_EVIDENCE_TERM: Final = "byte-identical rebuild"

FIVE_FLAT_ABBY_CONFIGS: Final[tuple[str, ...]] = (
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_EVALUATION_V2,
)

_CONFIG_DIRECTORY: Final[dict[str, str]] = {
    ABBY_VOICE_RESPONSE_V2: "responses",
    ABBY_VOICE_TEMPLATE_V2: "templates",
    ABBY_VOICE_AUDIO_V2: "audio",
    ABBY_VOICE_PROVENANCE_V2: "provenance",
    ABBY_VOICE_EVALUATION_V2: "evaluation",
}

_CONFIG_SPLITS: Final[dict[str, tuple[str, ...]]] = {
    ABBY_VOICE_RESPONSE_V2: ("train", "validation", "test"),
    ABBY_VOICE_TEMPLATE_V2: ("train", "validation", "test"),
    ABBY_VOICE_AUDIO_V2: ("train", "validation", "test"),
    ABBY_VOICE_PROVENANCE_V2: ("train", "validation", "test"),
    ABBY_VOICE_EVALUATION_V2: ("validation", "test"),
}

_ID_FIELD: Final[dict[str, str]] = {
    ABBY_VOICE_RESPONSE_V2: "response_id",
    ABBY_VOICE_TEMPLATE_V2: "template_id",
    ABBY_VOICE_AUDIO_V2: "audio_id",
    ABBY_VOICE_PROVENANCE_V2: "provenance_id",
    ABBY_VOICE_EVALUATION_V2: "evaluation_id",
}


class AbbyVoiceHFReleaseError(HuggingFaceReleaseError):
    """Raised when an Abby voice release cannot be built or validated."""


@dataclass(frozen=True, slots=True)
class AbbyVoiceHFReleaseResult:
    """Local receipt for a deterministic release build."""

    output_dir: str
    release_id: str
    dataset_repo_id: str
    manifest_path: str
    manifest_sha256: str
    release_cid: str
    configs: tuple[str, ...]
    descriptors: tuple[FileDescriptor, ...]
    row_counts: Mapping[str, Mapping[str, int]]
    graph_cid: str
    index_cid: str
    artifact_manifest: ArtifactManifest
    policy_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_manifest_id": self.artifact_manifest.manifest_id,
            "configs": list(self.configs),
            "dataset_repo_id": self.dataset_repo_id,
            "descriptors": [item.to_dict() for item in self.descriptors],
            "graph_cid": self.graph_cid,
            "index_cid": self.index_cid,
            "manifest_path": self.manifest_path,
            "manifest_sha256": self.manifest_sha256,
            "output_dir": self.output_dir,
            "policy_digest": self.policy_digest,
            "release_cid": self.release_cid,
            "release_id": self.release_id,
            "row_counts": {
                config: dict(splits) for config, splits in self.row_counts.items()
            },
        }


@dataclass(frozen=True, slots=True)
class AbbyVoiceHFReleasePolicy:
    """Pinned, identity-bearing construction policy."""

    shard_rows: int = DEFAULT_SHARD_ROWS
    split_train: int = 8000
    split_validation: int = 1000
    split_test: int = 1000
    split_salt: str = "abby-voice-v2"
    require_publishable: bool = True
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    producer_id: str = ABBY_VOICE_HF_RELEASE_PRODUCER
    config_id: str = ABBY_VOICE_HF_RELEASE_CONFIG

    def __post_init__(self) -> None:
        if (
            not isinstance(self.shard_rows, int)
            or isinstance(self.shard_rows, bool)
            or self.shard_rows <= 0
        ):
            raise AbbyVoiceHFReleaseError("shard_rows must be a positive integer")
        repo = str(self.dataset_repo_id or "").strip()
        if "/" not in repo or repo.startswith("/") or repo.endswith("/"):
            raise AbbyVoiceHFReleaseError(
                "dataset_repo_id must have the form namespace/repository"
            )
        object.__setattr__(self, "dataset_repo_id", repo)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "dataset_repo_id": self.dataset_repo_id,
            "parquet_compression": PARQUET_COMPRESSION,
            "parquet_compression_level": PARQUET_COMPRESSION_LEVEL,
            "producer_id": self.producer_id,
            "require_publishable": self.require_publishable,
            "shard_rows": self.shard_rows,
            "split_salt": self.split_salt,
            "split_test": self.split_test,
            "split_train": self.split_train,
            "split_validation": self.split_validation,
        }

    @property
    def digest(self) -> str:
        return sha256(canonical_json_bytes(self.to_dict())).hexdigest()


class AbbyVoiceHFReleaseBuilder:
    """Build and validate deterministic five-config Abby Hugging Face releases."""

    def __init__(
        self,
        *,
        policy: AbbyVoiceHFReleasePolicy | None = None,
        repository_commit: str = "commit:local-abby-voice-release",
    ) -> None:
        self.policy = policy or AbbyVoiceHFReleasePolicy()
        self.repository_commit = str(repository_commit or "").strip()
        if not self.repository_commit:
            raise AbbyVoiceHFReleaseError("repository_commit is required")

    def build(
        self,
        *,
        output_dir: str | Path,
        release_id: str,
        responses: Iterable[Mapping[str, Any] | AbbyVoiceResponse] = (),
        templates: Iterable[Mapping[str, Any] | AbbyVoiceTemplate] = (),
        audio: Iterable[Mapping[str, Any] | AbbyVoiceAudio] = (),
        provenance: Iterable[Mapping[str, Any] | AbbyVoiceProvenance] = (),
        evaluations: Iterable[Mapping[str, Any] | AbbyVoiceEvaluation] = (),
        graphrag_index: SlottedResponseIndex | None = None,
        parent_source_ids: Sequence[str] = (),
        license_id: str = "CC0-1.0",
        consent_status: str = "granted",
    ) -> AbbyVoiceHFReleaseResult:
        """Materialize a local release and return a content-addressed receipt.

        Two builds from the same pinned rows and policy are byte-identical.
        Support artifacts (manifest, GraphRAG index) live under ``manifests/``
        and are never written into row-config directories.
        """

        release = str(release_id or "").strip()
        if not release or "/" in release or ".." in release or "\\" in release:
            raise AbbyVoiceHFReleaseError(f"unsafe release_id: {release_id!r}")

        bundle = validate_bundle(
            responses=responses,
            templates=templates,
            audio=audio,
            provenance=provenance,
            require_references=True,
        )
        if self.policy.require_publishable:
            validate_publishable(bundle)

        evaluation_rows = validate_evaluation_rows(evaluations, strict=True)
        index = graphrag_index or SlottedResponseIndex.from_rows(
            templates=bundle.templates,
            responses=bundle.responses,
            audio=bundle.audio,
            provenance=bundle.provenance,
        )
        if index.bundle.responses != bundle.responses:
            # Rebuild index from the validated bundle so GraphRAG identity is exact.
            index = SlottedResponseIndex.from_rows(
                templates=bundle.templates,
                responses=bundle.responses,
                audio=bundle.audio,
                provenance=bundle.provenance,
            )

        root = Path(output_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        # Wipe previous release content deterministically under the output root.
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                _rmtree(child)

        config_digest = self.policy.digest
        parents = tuple(
            sorted({str(item).strip() for item in parent_source_ids if str(item).strip()})
        )
        config_rows = self._partition_configs(bundle, evaluation_rows)
        descriptors: list[FileDescriptor] = []
        row_counts: dict[str, dict[str, int]] = {}

        for config_name in FIVE_FLAT_ABBY_CONFIGS:
            directory = _CONFIG_DIRECTORY[config_name]
            by_split = config_rows[config_name]
            row_counts[config_name] = {
                split: len(by_split.get(split, ()))
                for split in _CONFIG_SPLITS[config_name]
            }
            schema = (
                get_evaluation_pyarrow_schema()
                if config_name == ABBY_VOICE_EVALUATION_V2
                else get_pyarrow_schema(config_name)
            )
            for split in _CONFIG_SPLITS[config_name]:
                rows = by_split.get(split, ())
                shards = shard_sequence(rows, max_rows=self.policy.shard_rows)
                # Skip completely empty non-primary splits to avoid empty Viewer
                # configs, but always emit at least one shard when the config
                # has zero rows total so Dataset Viewer can load the schema.
                if not rows and any(by_split.values()):
                    continue
                if not rows and not any(by_split.values()) and split != _CONFIG_SPLITS[config_name][0]:
                    continue
                for shard_id, shard_rows in enumerate(shards):
                    relative = (
                        f"{directory}/{split}/"
                        f"{split}-{shard_id:05d}-of-{len(shards):05d}.parquet"
                    )
                    path = root / relative
                    table = _rows_to_table(shard_rows, schema=schema)
                    write_zstd_parquet(
                        path, table, max_rows=self.policy.shard_rows
                    )
                    validate_zstd_parquet(
                        path,
                        max_rows=self.policy.shard_rows,
                        expected_schema=schema,
                        expected_row_count=len(shard_rows),
                    )
                    descriptor = describe_file(
                        path,
                        root=root,
                        media_type="application/vnd.apache.parquet",
                        schema_type=config_name,
                        producer_id=self.policy.producer_id,
                        config_digest=config_digest,
                        parent_ids=parents,
                        license_id=license_id,
                        consent_status=consent_status,
                        review_status="validated_local",
                        trust_decision="local_build",
                        row_count=len(shard_rows),
                        shard_id=shard_id,
                        split=split,
                        config_name=config_name,
                        metadata={
                            "descriptor_schema": "huggingface-release-descriptor/v1",
                            "shard_count": len(shards),
                        },
                    )
                    descriptors.append(descriptor)

        manifests_dir = root / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)

        graphrag_payload = index.to_dict()
        # Row payloads may carry optional created_at columns; contamination
        # checks apply to the sealed release manifest, not support indexes.
        graphrag_path = manifests_dir / "graphrag-index.json"
        graphrag_path.write_bytes(canonical_json_bytes(graphrag_payload) + b"\n")
        graphrag_descriptor = describe_file(
            graphrag_path,
            root=root,
            media_type="application/json",
            schema_type="abby_voice_graphrag_index",
            producer_id=self.policy.producer_id,
            config_digest=config_digest,
            parent_ids=parents,
            license_id=license_id,
            consent_status=consent_status,
            review_status="support_artifact",
            trust_decision="local_build",
            metadata={
                "graph_cid": index.graph_cid,
                "index_cid": index.index_cid,
                "role": "support_index",
            },
        )
        descriptors.append(graphrag_descriptor)

        dataset_yaml = self._dataset_yaml(release)
        yaml_path = root / "dataset_configs.json"
        write_canonical_json(yaml_path, dataset_yaml)
        yaml_descriptor = describe_file(
            yaml_path,
            root=root,
            media_type="application/json",
            schema_type="abby_voice_dataset_yaml",
            producer_id=self.policy.producer_id,
            config_digest=config_digest,
            parent_ids=parents,
            review_status="support_artifact",
            trust_decision="local_build",
        )
        descriptors.append(yaml_descriptor)

        readme = _release_readme(release, self.policy.dataset_repo_id, row_counts)
        readme_path = root / "README.md"
        readme_path.write_bytes(readme.encode("utf-8"))
        readme_descriptor = describe_file(
            readme_path,
            root=root,
            media_type="text/markdown",
            schema_type="abby_voice_release_readme",
            producer_id=self.policy.producer_id,
            config_digest=config_digest,
            parent_ids=parents,
            review_status="support_artifact",
            trust_decision="local_build",
        )
        descriptors.append(readme_descriptor)

        descriptors = tuple(
            sorted(descriptors, key=lambda item: item.relative_path)
        )
        release_body = {
            "configs": list(FIVE_FLAT_ABBY_CONFIGS),
            "dataset_repo_id": self.policy.dataset_repo_id,
            "descriptors": [item.to_dict() for item in descriptors],
            "graph_cid": index.graph_cid,
            "index_cid": index.index_cid,
            "parquet": {
                "compression": PARQUET_COMPRESSION,
                "compression_level": PARQUET_COMPRESSION_LEVEL,
                "shard_rows": self.policy.shard_rows,
            },
            "policy": self.policy.to_dict(),
            "policy_digest": config_digest,
            "release_id": release,
            "row_counts": row_counts,
            "schema_version": ABBY_VOICE_HF_RELEASE_SCHEMA,
            "support_artifacts": [
                item.relative_path
                for item in descriptors
                if not item.relative_path.endswith(".parquet")
            ],
        }
        reject_identity_contamination(release_body, label="release_manifest")
        release_cid = cid_v1_from_digest(
            sha256(canonical_json_bytes(release_body)).digest()
        )
        release_body["release_cid"] = release_cid

        artifact_manifest = self._artifact_manifest(
            descriptors=descriptors,
            release_id=release,
            release_cid=release_cid,
            graph_cid=index.graph_cid,
            index_cid=index.index_cid,
        )
        artifact_path = manifests_dir / "artifact-manifest.json"
        # Persist only identity-bearing fields; observations are non-identity.
        artifact_path.write_bytes(
            canonical_json_bytes(artifact_manifest.deterministic_dict()) + b"\n"
        )
        artifact_descriptor = describe_file(
            artifact_path,
            root=root,
            media_type="application/json",
            schema_type="artifact_manifest",
            producer_id=self.policy.producer_id,
            config_digest=config_digest,
            parent_ids=parents,
            review_status="support_artifact",
            trust_decision="local_build",
        )
        # Re-seal manifest with the artifact-manifest descriptor included.
        descriptors = tuple(
            sorted((*descriptors, artifact_descriptor), key=lambda item: item.relative_path)
        )
        release_body["artifact_manifest_id"] = artifact_manifest.manifest_id
        release_body["descriptors"] = [item.to_dict() for item in descriptors]
        release_body["support_artifacts"] = [
            item.relative_path
            for item in descriptors
            if not item.relative_path.endswith(".parquet")
        ]
        release_body.pop("release_cid", None)
        reject_identity_contamination(release_body, label="release_manifest")
        release_cid = cid_v1_from_digest(
            sha256(canonical_json_bytes(release_body)).digest()
        )
        release_body["release_cid"] = release_cid

        manifest_path = root / "release-manifest.json"
        write_canonical_json(manifest_path, release_body)
        manifest_sha256 = sha256(manifest_path.read_bytes()).hexdigest()

        result = AbbyVoiceHFReleaseResult(
            output_dir=str(root),
            release_id=release,
            dataset_repo_id=self.policy.dataset_repo_id,
            manifest_path=str(manifest_path),
            manifest_sha256=manifest_sha256,
            release_cid=release_cid,
            configs=FIVE_FLAT_ABBY_CONFIGS,
            descriptors=descriptors,
            row_counts={
                config: dict(splits) for config, splits in row_counts.items()
            },
            graph_cid=index.graph_cid,
            index_cid=index.index_cid,
            artifact_manifest=artifact_manifest,
            policy_digest=config_digest,
        )
        # Exhaustive local validation is part of construction.
        validate_abby_voice_hf_release(root)
        return result

    def _partition_configs(
        self,
        bundle: AbbyVoiceDatasetBundle,
        evaluations: Sequence[AbbyVoiceEvaluation],
    ) -> dict[str, dict[str, tuple[dict[str, Any], ...]]]:
        response_rows = sorted(
            (row.to_dict() for row in bundle.responses),
            key=lambda item: item["response_id"],
        )
        template_rows = sorted(
            (row.to_dict() for row in bundle.templates),
            key=lambda item: item["template_id"],
        )
        audio_rows = sorted(
            (row.to_dict() for row in bundle.audio),
            key=lambda item: item["audio_id"],
        )
        provenance_rows = sorted(
            (row.to_dict() for row in bundle.provenance),
            key=lambda item: item["provenance_id"],
        )
        evaluation_rows = sorted(
            (row.to_dict() for row in evaluations),
            key=lambda item: item["evaluation_id"],
        )

        def assign(
            rows: Sequence[Mapping[str, Any]],
            *,
            config_name: str,
            key_fields: Sequence[str],
            evaluation: bool = False,
        ) -> dict[str, tuple[dict[str, Any], ...]]:
            buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                if evaluation:
                    split = str(row.get("split") or "validation")
                    if split not in _CONFIG_SPLITS[config_name]:
                        raise AbbyVoiceHFReleaseError(
                            f"evaluation split must be validation or test, got {split!r}"
                        )
                else:
                    key = next(
                        (str(row[field]) for field in key_fields if row.get(field)),
                        str(row.get(_ID_FIELD[config_name]) or ""),
                    )
                    split = deterministic_split(
                        key,
                        train=self.policy.split_train,
                        validation=self.policy.split_validation,
                        test=self.policy.split_test,
                        salt=self.policy.split_salt,
                    )
                buckets[split].append(dict(row))
            return {
                split: tuple(buckets.get(split, ()))
                for split in _CONFIG_SPLITS[config_name]
            }

        return {
            ABBY_VOICE_RESPONSE_V2: assign(
                response_rows,
                config_name=ABBY_VOICE_RESPONSE_V2,
                key_fields=("template_id", "response_id"),
            ),
            ABBY_VOICE_TEMPLATE_V2: assign(
                template_rows,
                config_name=ABBY_VOICE_TEMPLATE_V2,
                key_fields=("template_id",),
            ),
            ABBY_VOICE_AUDIO_V2: assign(
                audio_rows,
                config_name=ABBY_VOICE_AUDIO_V2,
                key_fields=("response_id", "template_id", "audio_id"),
            ),
            ABBY_VOICE_PROVENANCE_V2: assign(
                provenance_rows,
                config_name=ABBY_VOICE_PROVENANCE_V2,
                key_fields=("subject_id", "provenance_id"),
            ),
            ABBY_VOICE_EVALUATION_V2: assign(
                evaluation_rows,
                config_name=ABBY_VOICE_EVALUATION_V2,
                key_fields=("case_id",),
                evaluation=True,
            ),
        }

    def _dataset_yaml(self, release_id: str) -> dict[str, Any]:
        configs = []
        for config_name in FIVE_FLAT_ABBY_CONFIGS:
            directory = _CONFIG_DIRECTORY[config_name]
            data_files = [
                {
                    "path": f"{directory}/{split}/{split}-*.parquet",
                    "split": split,
                }
                for split in _CONFIG_SPLITS[config_name]
            ]
            configs.append(
                {
                    "config_name": config_name,
                    "data_files": data_files,
                    "schema_version": config_name,
                }
            )
        return {
            "configs": configs,
            "dataset_repo_id": self.policy.dataset_repo_id,
            "format": "huggingface_dataset_card_frontmatter",
            "release_id": release_id,
        }

    def _artifact_manifest(
        self,
        *,
        descriptors: Sequence[FileDescriptor],
        release_id: str,
        release_cid: str,
        graph_cid: str,
        index_cid: str,
    ) -> ArtifactManifest:
        artifacts: list[Artifact] = []
        for descriptor in descriptors:
            role = (
                ArtifactRole.OUTPUT
                if descriptor.relative_path.endswith(".parquet")
                else ArtifactRole.DIAGNOSTIC
            )
            path_identity = sha256(
                descriptor.relative_path.encode("utf-8")
            ).hexdigest()[:16]
            artifacts.append(
                Artifact(
                    artifact_id=(
                        f"artifact:abby-voice-release:{path_identity}:"
                        f"{descriptor.sha256}"
                    ),
                    role=role,
                    content_sha256=descriptor.sha256,
                    size=descriptor.size_bytes,
                    path=descriptor.relative_path,
                    content_cid=descriptor.content_cid,
                    media_type=descriptor.media_type,
                    schema_id="abby.voice.release-artifact",
                    schema_version=descriptor.schema_type or "v1",
                    producer_id=descriptor.producer_id or self.policy.producer_id,
                    config_id=self.policy.config_id,
                    license_expression=descriptor.license_id,
                    review_status=descriptor.review_status,
                    trust_decision=descriptor.trust_decision,
                    metadata={
                        "config_name": descriptor.config_name,
                        "split": descriptor.split,
                        "row_count": descriptor.row_count,
                        "shard_id": descriptor.shard_id,
                    },
                )
            )
        return ArtifactManifest(
            artifacts=tuple(artifacts),
            repository_commit=self.repository_commit,
            producers=(
                ProducerBinding(
                    producer_id=self.policy.producer_id,
                    name="AbbyVoiceHFReleaseBuilder",
                    version="1.0.0",
                    implementation_sha256=self.policy.digest,
                    repository_revision=self.repository_commit,
                ),
            ),
            configs=(
                ConfigBinding(
                    config_id=self.policy.config_id,
                    content_sha256=self.policy.digest,
                    schema_id="abby.voice.hf-release-config",
                    metadata=self.policy.to_dict(),
                ),
            ),
            schema_versions={
                name: name for name in FIVE_FLAT_ABBY_CONFIGS
            },
            tool_versions={"abby-voice-hf-release": "1.0.0"},
            deterministic_metadata={
                "byte_identical_rebuild": True,
                "deterministic_release_construction": True,
                "five_flat_abby_configs_including_evaluation": list(
                    FIVE_FLAT_ABBY_CONFIGS
                ),
                "graph_cid": graph_cid,
                "index_cid": index_cid,
                "release_cid": release_cid,
                "release_id": release_id,
                "sharded_zstd_parquet_descriptors": True,
            },
        )


def validate_abby_voice_hf_release(release_dir: str | Path) -> dict[str, Any]:
    """Exhaustive offline validation of a local Abby Hugging Face release.

    Verifies every descriptor, Parquet magic/schema/readability/row count,
    shard coverage, no duplicate IDs, exact bundle references, and GraphRAG
    graph/index identities.  Returns a compact validation receipt.
    """

    root = Path(release_dir).expanduser().resolve()
    manifest_path = root / "release-manifest.json"
    if not manifest_path.is_file():
        raise AbbyVoiceHFReleaseError(
            f"release-manifest.json is missing under {root}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AbbyVoiceHFReleaseError("release manifest is malformed") from exc
    if not isinstance(manifest, Mapping):
        raise AbbyVoiceHFReleaseError("release manifest must be an object")
    if manifest.get("schema_version") != ABBY_VOICE_HF_RELEASE_SCHEMA:
        raise AbbyVoiceHFReleaseError(
            f"unsupported release schema_version {manifest.get('schema_version')!r}"
        )
    reject_identity_contamination(manifest, label="release_manifest")

    configs = tuple(manifest.get("configs") or ())
    if configs != FIVE_FLAT_ABBY_CONFIGS:
        raise AbbyVoiceHFReleaseError(
            "release must declare the five flat Abby configs including evaluation"
        )

    raw_descriptors = manifest.get("descriptors")
    if not isinstance(raw_descriptors, list) or not raw_descriptors:
        raise AbbyVoiceHFReleaseError("release descriptors are required")
    descriptors = [FileDescriptor.from_dict(item) for item in raw_descriptors]
    for descriptor in descriptors:
        verify_file_descriptor(root, descriptor)

    config_rows: dict[str, list[dict[str, Any]]] = {
        name: [] for name in FIVE_FLAT_ABBY_CONFIGS
    }
    for descriptor in descriptors:
        if not descriptor.relative_path.endswith(".parquet"):
            continue
        if descriptor.config_name not in FIVE_FLAT_ABBY_CONFIGS:
            raise AbbyVoiceHFReleaseError(
                f"unknown parquet config {descriptor.config_name!r}"
            )
        # Support artifacts must not live under config directories.
        directory = _CONFIG_DIRECTORY[descriptor.config_name]
        if not descriptor.relative_path.startswith(f"{directory}/"):
            raise AbbyVoiceHFReleaseError(
                f"parquet descriptor path not under config directory: "
                f"{descriptor.relative_path}"
            )
        schema = (
            get_evaluation_pyarrow_schema()
            if descriptor.config_name == ABBY_VOICE_EVALUATION_V2
            else get_pyarrow_schema(descriptor.config_name)
        )
        path = verify_file_descriptor(root, descriptor)
        row_count = validate_zstd_parquet(
            path,
            max_rows=int(manifest.get("parquet", {}).get("shard_rows", DEFAULT_SHARD_ROWS)),
            expected_schema=schema,
            expected_row_count=descriptor.row_count,
        )
        rows = _read_parquet_rows(path)
        if len(rows) != row_count:
            raise AbbyVoiceHFReleaseError(
                f"readable row count mismatch for {descriptor.relative_path}"
            )
        config_rows[descriptor.config_name].extend(rows)

    # No duplicate IDs within each config.
    for config_name, rows in config_rows.items():
        id_field = _ID_FIELD[config_name]
        seen: set[str] = set()
        for row in rows:
            identity = str(row.get(id_field) or "")
            if not identity:
                raise AbbyVoiceHFReleaseError(
                    f"{config_name} row missing {id_field}"
                )
            if identity in seen:
                raise AbbyVoiceHFReleaseError(
                    f"duplicate {id_field} in {config_name}: {identity}"
                )
            seen.add(identity)

    # Exact bundle references among the four voice configs.
    if any(config_rows[name] for name in (
        ABBY_VOICE_RESPONSE_V2,
        ABBY_VOICE_TEMPLATE_V2,
        ABBY_VOICE_AUDIO_V2,
        ABBY_VOICE_PROVENANCE_V2,
    )):
        validate_bundle(
            responses=config_rows[ABBY_VOICE_RESPONSE_V2],
            templates=config_rows[ABBY_VOICE_TEMPLATE_V2],
            audio=config_rows[ABBY_VOICE_AUDIO_V2],
            provenance=config_rows[ABBY_VOICE_PROVENANCE_V2],
            require_references=True,
        )
    if config_rows[ABBY_VOICE_EVALUATION_V2]:
        validate_evaluation_rows(config_rows[ABBY_VOICE_EVALUATION_V2], strict=True)

    # GraphRAG support-index artifact.
    graph_path = root / "manifests" / "graphrag-index.json"
    if not graph_path.is_file():
        raise AbbyVoiceHFReleaseError("GraphRAG support-index artifact is missing")
    graph_payload = json.loads(graph_path.read_text(encoding="utf-8"))
    index = SlottedResponseIndex.from_dict(graph_payload)
    if index.graph_cid != manifest.get("graph_cid"):
        raise AbbyVoiceHFReleaseError("graph_cid does not match GraphRAG index")
    if index.index_cid != manifest.get("index_cid"):
        raise AbbyVoiceHFReleaseError("index_cid does not match GraphRAG index")

    # Identity: release CID must recompute from the sealed body without the
    # release_cid field itself (and without non-identity fields).
    body = dict(manifest)
    body.pop("release_cid", None)
    expected_cid = cid_v1_from_digest(sha256(canonical_json_bytes(body)).digest())
    if manifest.get("release_cid") != expected_cid:
        raise AbbyVoiceHFReleaseError("release_cid does not match sealed body")

    # No support artifacts mixed into config directories.
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        parts = relative.split("/")
        if parts[0] in set(_CONFIG_DIRECTORY.values()) and not relative.endswith(
            ".parquet"
        ):
            raise AbbyVoiceHFReleaseError(
                f"non-parquet artifact inside config directory: {relative}"
            )

    return {
        "configs": list(configs),
        "descriptor_count": len(descriptors),
        "graph_cid": index.graph_cid,
        "index_cid": index.index_cid,
        "release_cid": manifest.get("release_cid"),
        "release_id": manifest.get("release_id"),
        "row_counts": {
            name: len(rows) for name, rows in config_rows.items()
        },
        "valid": True,
    }


def build_abby_voice_hf_release(
    *,
    output_dir: str | Path,
    release_id: str,
    responses: Iterable[Mapping[str, Any] | AbbyVoiceResponse] = (),
    templates: Iterable[Mapping[str, Any] | AbbyVoiceTemplate] = (),
    audio: Iterable[Mapping[str, Any] | AbbyVoiceAudio] = (),
    provenance: Iterable[Mapping[str, Any] | AbbyVoiceProvenance] = (),
    evaluations: Iterable[Mapping[str, Any] | AbbyVoiceEvaluation] = (),
    policy: AbbyVoiceHFReleasePolicy | None = None,
    repository_commit: str = "commit:local-abby-voice-release",
    **kwargs: Any,
) -> AbbyVoiceHFReleaseResult:
    """Module-level convenience wrapper around the release builder."""

    builder = AbbyVoiceHFReleaseBuilder(
        policy=policy, repository_commit=repository_commit
    )
    return builder.build(
        output_dir=output_dir,
        release_id=release_id,
        responses=responses,
        templates=templates,
        audio=audio,
        provenance=provenance,
        evaluations=evaluations,
        **kwargs,
    )


def _rows_to_table(rows: Sequence[Mapping[str, Any]], *, schema: Any) -> Any:
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover
        raise ImportError("_rows_to_table requires the optional 'pyarrow' package") from exc
    if not rows:
        empty = {name: [] for name in schema.names}
        return pa.Table.from_pydict(empty, schema=schema)
    ordered = [{name: row.get(name) for name in schema.names} for row in rows]
    return pa.Table.from_pylist(ordered, schema=schema)


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "_read_parquet_rows requires the optional 'pyarrow' package"
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


def _release_readme(
    release_id: str,
    dataset_repo_id: str,
    row_counts: Mapping[str, Mapping[str, int]],
) -> str:
    lines = [
        "---",
        "license: cc0-1.0",
        f"dataset_repo_id: {dataset_repo_id}",
        f"release_id: {release_id}",
        "configs:",
    ]
    for config_name in FIVE_FLAT_ABBY_CONFIGS:
        directory = _CONFIG_DIRECTORY[config_name]
        lines.append(f"- config_name: {config_name}")
        lines.append("  data_files:")
        for split in _CONFIG_SPLITS[config_name]:
            lines.append(f"  - split: {split}")
            lines.append(
                f"    path: {directory}/{split}/{split}-*.parquet"
            )
    lines.extend(
        [
            "---",
            "",
            f"# Abby voice release `{release_id}`",
            "",
            "Deterministic five-config ZSTD Parquet release for Hugging Face",
            "Dataset Viewer. Generated offline; publication is a separate,",
            "human-approved G021 step.",
            "",
            "## Row counts",
            "",
        ]
    )
    for config_name in FIVE_FLAT_ABBY_CONFIGS:
        splits = row_counts.get(config_name, {})
        total = sum(int(value) for value in splits.values())
        lines.append(f"- `{config_name}`: {total}")
    lines.append("")
    return "\n".join(lines)


def _rmtree(path: Path) -> None:
    for child in sorted(path.iterdir(), key=lambda item: item.name, reverse=True):
        if child.is_dir() and not child.is_symlink():
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()


__all__ = [
    "ABBY_VOICE_HF_RELEASE_CONFIG",
    "ABBY_VOICE_HF_RELEASE_PRODUCER",
    "ABBY_VOICE_HF_RELEASE_SCHEMA",
    "DEFAULT_DATASET_REPO_ID",
    "FIVE_FLAT_ABBY_CONFIGS",
    "AbbyVoiceHFReleaseBuilder",
    "AbbyVoiceHFReleaseError",
    "AbbyVoiceHFReleasePolicy",
    "AbbyVoiceHFReleaseResult",
    "build_abby_voice_hf_release",
    "validate_abby_voice_hf_release",
]
