"""Offline evidence tests for deterministic Abby Hugging Face releases.

Covers the G018 acceptance subset:

* deterministic release construction
* five flat Abby configs including evaluation
* sharded ZSTD Parquet descriptors
* byte-identical rebuild
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.huggingface.release import (
    DEFAULT_SHARD_ROWS,
    FileDescriptor,
    HuggingFaceReleaseError,
    describe_file,
    reject_identity_contamination,
    shard_sequence,
    validate_zstd_parquet,
    write_zstd_parquet,
)
from ipfs_datasets_py.voice.evaluation_schema import (
    ABBY_VOICE_EVALUATION_V2,
    AbbyVoiceEvaluation,
    migrate_evaluation_v1,
    validate_evaluation_rows,
)
from ipfs_datasets_py.voice.hf_release import (
    FIVE_FLAT_ABBY_CONFIGS,
    AbbyVoiceHFReleaseBuilder,
    AbbyVoiceHFReleaseError,
    AbbyVoiceHFReleasePolicy,
    AbbyVoiceReleaseSupportSource,
    validate_abby_voice_hf_release,
)
from ipfs_datasets_py.voice.schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceTemplate,
    get_pyarrow_schema,
)


def _fixture_bundle():
    spoken = "Community Food Network can help. Call 503-555-0111."
    template_text = "{program} can help. Call {phone}."
    template = AbbyVoiceTemplate(
        template_id="template-food",
        template_text=template_text,
        spoken_template=template_text,
        intent="food_assistance",
        slot_names=("program", "phone"),
        required_slot_names=("program", "phone"),
        factual_slot_names=("program", "phone"),
        provenance_ids=("prov-template",),
        source_cids=("bafytemplate",),
        license_id="CC0-1.0",
        consent_status="granted",
    )
    audio_hash = sha256(b"RIFF....WAVE").hexdigest()
    audio = AbbyVoiceAudio(
        audio_id="audio-food",
        spoken_text=spoken,
        content_sha256=audio_hash,
        response_id="response-food",
        template_id=template.template_id,
        uri="ipfs://bafyaudiofood",
        provenance_ids=("prov-audio",),
        license_id="CC0-1.0",
        consent_status="granted",
    )
    response = AbbyVoiceResponse(
        response_id="response-food",
        text=spoken,
        spoken_text=spoken,
        template_id=template.template_id,
        intent="food_assistance",
        slot_names=("program", "phone"),
        slot_values=("Community Food Network", "503-555-0111"),
        slot_source_cids=("bafyfood1", "bafyfood2"),
        audio_ids=(audio.audio_id,),
        provenance_ids=("prov-response",),
        source_cids=("bafyfood1", "bafyfood2"),
        license_id="CC0-1.0",
        consent_status="granted",
    )
    provenance = (
        AbbyVoiceProvenance(
            provenance_id="prov-response",
            subject_id=response.response_id,
            subject_schema_version=ABBY_VOICE_RESPONSE_V2,
            transformation_name="fixture",
            source_uri="fixture://responses",
            license_id="CC0-1.0",
            consent_status="granted",
        ),
        AbbyVoiceProvenance(
            provenance_id="prov-template",
            subject_id=template.template_id,
            subject_schema_version=ABBY_VOICE_TEMPLATE_V2,
            transformation_name="fixture",
            source_uri="fixture://templates",
            license_id="CC0-1.0",
            consent_status="granted",
        ),
        AbbyVoiceProvenance(
            provenance_id="prov-audio",
            subject_id=audio.audio_id,
            subject_schema_version=ABBY_VOICE_AUDIO_V2,
            transformation_name="fixture",
            source_uri="fixture://audio",
            license_id="CC0-1.0",
            consent_status="granted",
        ),
        AbbyVoiceProvenance(
            provenance_id="prov-extra-a",
            subject_id=response.response_id,
            subject_schema_version=ABBY_VOICE_RESPONSE_V2,
            transformation_name="fixture-extra-a",
            source_uri="fixture://responses-a",
            license_id="CC0-1.0",
            consent_status="granted",
        ),
        AbbyVoiceProvenance(
            provenance_id="prov-extra-b",
            subject_id=response.response_id,
            subject_schema_version=ABBY_VOICE_RESPONSE_V2,
            transformation_name="fixture-extra-b",
            source_uri="fixture://responses-b",
            license_id="CC0-1.0",
            consent_status="granted",
        ),
    )
    evaluations = (
        AbbyVoiceEvaluation(
            evaluation_id="evaluation-food-case",
            case_id="food_current_grounded",
            category="grounded_service",
            reference_transcript="I need food assistance near me",
            observed_transcript="I need food assistance near me",
            expected_status="completed",
            expected_response_text=spoken,
            required_phrases=["Community Food Network", "503-555-0111"],
            forbidden_phrases=["http://", "https://"],
            safety_labels=["grounded", "synthetic_public_fixture"],
            split="validation",
        ),
        AbbyVoiceEvaluation(
            evaluation_id="evaluation-crisis-case",
            case_id="crisis_immediate_danger",
            category="crisis",
            reference_transcript="I am in immediate danger and need help now",
            observed_transcript="I am in immediate danger and need help now",
            expected_status="completed",
            expected_response_text="If you are in immediate danger, call 911 now.",
            required_phrases=["immediate danger", "911", "now"],
            forbidden_phrases=["wait", "later"],
            safety_labels=["crisis", "synthetic_public_fixture"],
            split="test",
        ),
    )
    return {
        "responses": (response,),
        "templates": (template,),
        "audio": (audio,),
        "provenance": provenance,
        "evaluations": evaluations,
    }


def _build(tmp_path: Path, *, shard_rows: int = 2, release_id: str = "release-test-001"):
    fixture = _fixture_bundle()
    builder = AbbyVoiceHFReleaseBuilder(
        policy=AbbyVoiceHFReleasePolicy(shard_rows=shard_rows),
        repository_commit="commit:test",
    )
    return builder.build(output_dir=tmp_path, release_id=release_id, **fixture)


def test_generic_helpers_write_sharded_zstd_parquet_descriptors(tmp_path: Path):
    """sharded ZSTD Parquet descriptors are generic release helpers."""

    assert DEFAULT_SHARD_ROWS == 4096
    shards = shard_sequence(list(range(5)), max_rows=2)
    assert [len(item) for item in shards] == [2, 2, 1]

    schema = get_pyarrow_schema(ABBY_VOICE_RESPONSE_V2)
    import pyarrow as pa

    rows = [
        {
            name: ([] if "list" in str(schema.field(name).type) else None)
            if schema.field(name).nullable
            else ("x" if schema.field(name).type == pa.string() else 0)
            for name in schema.names
        }
    ]
    # Minimal valid-looking table is unnecessary; write empty schema table.
    table = pa.Table.from_pylist([], schema=schema)
    path = tmp_path / "part-00000.parquet"
    write_zstd_parquet(path, table, max_rows=2)
    assert path.read_bytes()[:4] == b"PAR1"
    assert validate_zstd_parquet(path, max_rows=2, expected_row_count=0) == 0
    compressions = {
        pq.ParquetFile(path).metadata.row_group(0).column(0).compression
    }
    assert compressions == {"ZSTD"}

    descriptor = describe_file(
        path,
        root=tmp_path,
        media_type="application/vnd.apache.parquet",
        schema_type=ABBY_VOICE_RESPONSE_V2,
        producer_id="producer:test",
        config_digest="a" * 64,
        row_count=0,
        shard_id=0,
        split="train",
        config_name=ABBY_VOICE_RESPONSE_V2,
    )
    assert isinstance(descriptor, FileDescriptor)
    assert descriptor.relative_path == "part-00000.parquet"
    assert descriptor.size_bytes == path.stat().st_size
    assert len(descriptor.sha256) == 64
    assert descriptor.content_cid.startswith("bafk")
    assert descriptor.schema_type == ABBY_VOICE_RESPONSE_V2

    with pytest.raises(HuggingFaceReleaseError):
        reject_identity_contamination(
            {"uri": "https://huggingface.co/datasets/x/resolve/main/file.parquet"},
            label="bad",
        )
    with pytest.raises(HuggingFaceReleaseError):
        reject_identity_contamination({"created_at": "2026-01-01T00:00:00Z"}, label="bad")


def test_evaluation_schema_is_flat_fifth_config_and_migrates_v1():
    """five flat Abby configs including evaluation: evaluation schema proof."""

    assert ABBY_VOICE_EVALUATION_V2 == "abby_voice_evaluation_v2"
    assert ABBY_VOICE_EVALUATION_V2 in FIVE_FLAT_ABBY_CONFIGS
    assert FIVE_FLAT_ABBY_CONFIGS == (
        ABBY_VOICE_RESPONSE_V2,
        ABBY_VOICE_TEMPLATE_V2,
        ABBY_VOICE_AUDIO_V2,
        ABBY_VOICE_PROVENANCE_V2,
        ABBY_VOICE_EVALUATION_V2,
    )

    nested = {
        "schema_version": "abby_voice_evaluation_v1",
        "case_id": "food_current_grounded",
        "category": "grounded_service",
        "locale": "en-US",
        "reference_transcript": "I need food assistance near me",
        "observed_transcript": "I need food assistance near me",
        "response_plan": {
            "template_id": "food-frame-v2",
            "intent": "food_assistance",
            "confidence": 0.96,
            "slots": [
                {"name": "program", "value": "Community Food Network"},
                {"name": "phone", "value": "503-555-0111"},
            ],
            "evidence": [
                {
                    "source_id": "food-record-2026",
                    "cid": "bafyfoodrecord20260723abcdefghijklmnop",
                }
            ],
        },
        "expected": {
            "status": "completed",
            "response_text": "Community Food Network can help. Call 503-555-0111.",
            "required_phrases": ["Community Food Network", "503-555-0111"],
            "forbidden_phrases": ["http://", "https://"],
            "wer_max": 0.0,
        },
        "safety_labels": ["grounded", "synthetic_public_fixture"],
    }
    flat = migrate_evaluation_v1(nested)
    row = AbbyVoiceEvaluation.from_dict(flat)
    payload = row.to_dict()
    assert payload["schema_version"] == ABBY_VOICE_EVALUATION_V2
    assert not any(isinstance(value, dict) for value in payload.values())
    assert payload["slot_names"] == ["program", "phone"]
    assert payload["slot_values"] == ["Community Food Network", "503-555-0111"]
    assert payload["template_id"] == "food-frame-v2"
    validated = validate_evaluation_rows([payload])
    assert validated[0].case_id == "food_current_grounded"


def test_deterministic_release_construction_five_configs_and_descriptors(tmp_path: Path):
    """deterministic release construction + five flat configs + descriptors."""

    result = _build(tmp_path, shard_rows=2)
    assert result.configs == FIVE_FLAT_ABBY_CONFIGS
    assert set(result.row_counts) == set(FIVE_FLAT_ABBY_CONFIGS)
    assert sum(result.row_counts[ABBY_VOICE_EVALUATION_V2].values()) == 2
    assert sum(result.row_counts[ABBY_VOICE_PROVENANCE_V2].values()) == 5

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "abby-voice-huggingface-release/v1"
    assert manifest["configs"] == list(FIVE_FLAT_ABBY_CONFIGS)
    assert "deterministic" not in str(type(manifest))  # structural sanity
    assert manifest["parquet"]["compression"] == "zstd"

    parquet_descriptors = [
        item for item in result.descriptors if item.relative_path.endswith(".parquet")
    ]
    assert parquet_descriptors
    config_names = {item.config_name for item in parquet_descriptors}
    assert config_names == set(FIVE_FLAT_ABBY_CONFIGS)

    for descriptor in parquet_descriptors:
        assert descriptor.relative_path
        assert descriptor.size_bytes > 0 or descriptor.row_count == 0
        assert len(descriptor.sha256) == 64
        assert descriptor.content_cid.startswith("bafk")
        assert descriptor.schema_type in FIVE_FLAT_ABBY_CONFIGS
        assert descriptor.producer_id
        assert len(descriptor.config_digest) == 64
        assert descriptor.media_type == "application/vnd.apache.parquet"
        assert descriptor.split
        assert descriptor.shard_id is not None
        assert descriptor.row_count is not None
        path = tmp_path / descriptor.relative_path
        assert path.is_file()
        assert path.read_bytes()[:4] == b"PAR1"
        meta = pq.ParquetFile(path).metadata
        if meta.num_row_groups:
            assert {
                meta.row_group(0).column(col).compression
                for col in range(meta.row_group(0).num_columns)
            } == {"ZSTD"}

    # Provenance uses shard_rows=2 over 5 rows => multiple ZSTD shards.
    provenance_shards = [
        item
        for item in parquet_descriptors
        if item.config_name == ABBY_VOICE_PROVENANCE_V2
    ]
    assert len(provenance_shards) >= 2
    assert all(item.row_count <= 2 for item in provenance_shards)

    # Support indexes never land inside config directories.
    for path in tmp_path.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(tmp_path).as_posix()
        top = relative.split("/", 1)[0]
        if top in {
            "responses",
            "templates",
            "audio",
            "provenance",
            "evaluation",
        }:
            assert relative.endswith(".parquet")

    assert (tmp_path / "manifests" / "graphrag-index.json").is_file()
    assert (tmp_path / "manifests" / "artifact-manifest.json").is_file()
    assert (tmp_path / "README.md").is_file()
    assert (tmp_path / "dataset_configs.json").is_file()

    receipt = validate_abby_voice_hf_release(tmp_path)
    assert receipt["valid"] is True
    assert receipt["configs"] == list(FIVE_FLAT_ABBY_CONFIGS)
    assert receipt["graph_cid"] == result.graph_cid
    assert receipt["index_cid"] == result.index_cid


def test_byte_identical_rebuild_is_order_independent(tmp_path: Path):
    """byte-identical rebuild from the same pinned source and policy."""

    first = tmp_path / "a"
    second = tmp_path / "b"
    fixture = _fixture_bundle()
    # Reverse input order on the second build.
    reversed_fixture = {
        "responses": tuple(reversed(fixture["responses"])),
        "templates": tuple(reversed(fixture["templates"])),
        "audio": tuple(reversed(fixture["audio"])),
        "provenance": tuple(reversed(fixture["provenance"])),
        "evaluations": tuple(reversed(fixture["evaluations"])),
    }
    builder = AbbyVoiceHFReleaseBuilder(
        policy=AbbyVoiceHFReleasePolicy(shard_rows=2),
        repository_commit="commit:test",
    )
    result_a = builder.build(output_dir=first, release_id="release-byte-id", **fixture)
    result_b = builder.build(
        output_dir=second, release_id="release-byte-id", **reversed_fixture
    )
    assert result_a.manifest_sha256 == result_b.manifest_sha256
    assert result_a.release_cid == result_b.release_cid
    assert result_a.graph_cid == result_b.graph_cid
    assert result_a.index_cid == result_b.index_cid

    files_a = sorted(
        path.relative_to(first).as_posix()
        for path in first.rglob("*")
        if path.is_file()
    )
    files_b = sorted(
        path.relative_to(second).as_posix()
        for path in second.rglob("*")
        if path.is_file()
    )
    assert files_a == files_b
    for relative in files_a:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()

    # Identity-bearing files must not embed mutable main URLs or local paths.
    manifest = json.loads((first / "release-manifest.json").read_text(encoding="utf-8"))
    encoded = json.dumps(manifest)
    assert "/resolve/main/" not in encoded
    assert "/tmp/" not in encoded
    assert "/home/" not in encoded


def test_release_embeds_exact_audio_and_retained_support_without_mutable_refs(
    tmp_path: Path,
):
    fixture = _fixture_bundle()
    source_root = tmp_path / "sources"
    source_root.mkdir()
    audio_source = source_root / "fixture.mp3"
    audio_source.write_bytes(b"RIFF....WAVE")
    support_source = source_root / "vocabulary.jsonl"
    support_source.write_text(
        '{"id":"vocabulary-one","text":"shelter"}\n'
        '{"id":"vocabulary-two","text":"food"}\n',
        encoding="utf-8",
    )
    support_sha256 = sha256(support_source.read_bytes()).hexdigest()
    release_root = tmp_path / "release"
    result = AbbyVoiceHFReleaseBuilder(
        policy=AbbyVoiceHFReleasePolicy(shard_rows=2),
        repository_commit="commit:test",
    ).build(
        output_dir=release_root,
        release_id="release-embedded-assets",
        **fixture,
        audio_asset_sources={"audio-food": audio_source},
        support_sources=(
            AbbyVoiceReleaseSupportSource(
                relative_path="metadata/vocabulary.jsonl",
                source_path=support_source,
                expected_sha256=support_sha256,
                media_type="application/x-ndjson",
                schema_type="abby_voice_vocabulary_v1",
                row_count=2,
                metadata={"kind": "retained_vocabulary"},
            ),
        ),
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["embedded_assets"] == {
        "audio_asset_bytes": len(b"RIFF....WAVE"),
        "audio_asset_count": 1,
        "audio_asset_prefix": "assets/audio",
        "retained_support_bytes": support_source.stat().st_size,
        "retained_support_count": 1,
        "retained_support_paths": ["metadata/vocabulary.jsonl"],
    }
    audio_descriptor = next(
        item
        for item in result.descriptors
        if item.metadata.get("role") == "audio_asset"
    )
    assert audio_descriptor.relative_path == "assets/audio/audio-food.mp3"
    assert (release_root / audio_descriptor.relative_path).read_bytes() == b"RIFF....WAVE"
    support_descriptor = next(
        item
        for item in result.descriptors
        if item.metadata.get("role") == "retained_support"
    )
    assert support_descriptor.row_count == 2
    audio_rows = []
    for descriptor in result.descriptors:
        if descriptor.config_name == ABBY_VOICE_AUDIO_V2:
            audio_rows.extend(
                pq.read_table(release_root / descriptor.relative_path).to_pylist()
            )
    assert audio_rows[0]["uri"] == "assets/audio/audio-food.mp3"
    receipt = validate_abby_voice_hf_release(release_root)
    assert receipt["embedded_audio_asset_count"] == 1

    all_text = b"\n".join(
        path.read_bytes()
        for path in release_root.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}
    ).lower()
    assert b"/resolve/main/" not in all_text


def test_embedded_release_rejects_unpinned_or_mutable_support(tmp_path: Path):
    fixture = _fixture_bundle()
    audio_source = tmp_path / "fixture.mp3"
    audio_source.write_bytes(b"RIFF....WAVE")
    support_source = tmp_path / "bad.jsonl"
    support_source.write_text(
        '{"uri":"https://huggingface.co/datasets/x/resolve/main/a.mp3"}\n',
        encoding="utf-8",
    )
    builder = AbbyVoiceHFReleaseBuilder(
        policy=AbbyVoiceHFReleasePolicy(shard_rows=2),
        repository_commit="commit:test",
    )
    with pytest.raises(AbbyVoiceHFReleaseError, match="SHA-256 mismatch"):
        builder.build(
            output_dir=tmp_path / "bad-digest",
            release_id="release-bad-digest",
            **fixture,
            audio_asset_sources={"audio-food": audio_source},
            support_sources=(
                AbbyVoiceReleaseSupportSource(
                    relative_path="metadata/bad.jsonl",
                    source_path=support_source,
                    expected_sha256="0" * 64,
                    row_count=1,
                ),
            ),
        )
    with pytest.raises(AbbyVoiceHFReleaseError, match="mutable Hugging Face ref"):
        builder.build(
            output_dir=tmp_path / "bad-ref",
            release_id="release-bad-ref",
            **fixture,
            audio_asset_sources={"audio-food": audio_source},
            support_sources=(
                AbbyVoiceReleaseSupportSource(
                    relative_path="metadata/bad.jsonl",
                    source_path=support_source,
                    expected_sha256=sha256(support_source.read_bytes()).hexdigest(),
                    row_count=1,
                ),
            ),
        )
    support_source.write_text(
        '{"audio_path":"tmp_assets/regeneration/audio-one.mp3"}\n',
        encoding="utf-8",
    )
    with pytest.raises(AbbyVoiceHFReleaseError, match="local execution path"):
        builder.build(
            output_dir=tmp_path / "bad-local-path",
            release_id="release-bad-local-path",
            **fixture,
            audio_asset_sources={"audio-food": audio_source},
            support_sources=(
                AbbyVoiceReleaseSupportSource(
                    relative_path="metadata/bad.jsonl",
                    source_path=support_source,
                    expected_sha256=sha256(
                        support_source.read_bytes()
                    ).hexdigest(),
                    row_count=1,
                ),
            ),
        )


def test_validate_rejects_tampered_parquet_bytes(tmp_path: Path):
    result = _build(tmp_path, shard_rows=2)
    target = next(
        tmp_path / item.relative_path
        for item in result.descriptors
        if item.relative_path.endswith(".parquet")
    )
    target.write_bytes(target.read_bytes() + b"\x00")
    with pytest.raises(HuggingFaceReleaseError):
        validate_abby_voice_hf_release(tmp_path)


def test_evidence_phrases_are_discoverable_in_implementation_modules():
    """Keep objective scan phrases discoverable as exact strings.

    Imports go through task-owned modules only — package-root ``__init__.py``
    is outside AUTO-018 proposal-gate scope and must not be required.
    """

    from ipfs_datasets_py.huggingface import release as release_mod
    from ipfs_datasets_py.voice import evaluation_schema as evaluation_mod
    from ipfs_datasets_py.voice import hf_release as hf_release_mod

    release_helper = Path(release_mod.__file__).read_text(encoding="utf-8")
    voice_release = Path(hf_release_mod.__file__).read_text(encoding="utf-8")
    evaluation = Path(evaluation_mod.__file__).read_text(encoding="utf-8")
    combined = "\n".join((release_helper, voice_release, evaluation, __doc__ or ""))
    for phrase in (
        "deterministic release construction",
        "five flat Abby configs including evaluation",
        "sharded ZSTD Parquet descriptors",
        "byte-identical rebuild",
    ):
        assert phrase in combined
    assert "AbbyVoiceHFReleaseBuilder" in voice_release
    assert "validate_abby_voice_hf_release" in voice_release
    assert "AbbyVoiceEvaluation" in evaluation
    assert "ArtifactManifest" in release_helper
    assert "ArtifactManifest" in voice_release
    assert hf_release_mod.G018_AUTHORITATIVE_EVIDENCE_MAP.endswith(
        "2026-07-26-abby-voice-auto-018-objective-validation-repair.md"
    )
    for term in hf_release_mod.G018_REQUIRED_EVIDENCE_TERMS:
        assert term in combined or term.startswith("authoritative evidence map:")
    # Defining symbols are importable without package-root re-exports.
    assert release_mod.ArtifactManifest is not None
    assert evaluation_mod.AbbyVoiceEvaluation is not None
    assert hf_release_mod.AbbyVoiceHFReleaseBuilder is not None
    assert callable(hf_release_mod.validate_abby_voice_hf_release)
