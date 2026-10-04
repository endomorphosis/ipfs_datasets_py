"""Tests for deterministic local admission-to-dataset merging."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from ipfs_datasets_py.voice.dataset_merge import (
    ABBY_VOICE_NORMALIZED_BUILD_SCHEMA_VERSION,
    AbbyVoiceDatasetMergeError,
    AbbyVoiceNormalizedDatasetLoadResult,
    load_normalized_dataset_bundle,
    merge_admitted_audio,
)
from ipfs_datasets_py.voice.normalize import (
    NORMALIZATION_VERSION,
    QUALITY_REPORT_VERSION,
)
from ipfs_datasets_py.voice.reconcile import (
    AudioDisposition,
    AudioDispositionReason,
    AudioDispositionStatus,
    AudioReconciliationResult,
)
from ipfs_datasets_py.voice.schema import (
    ABBY_VOICE_AUDIO_V2,
    AbbyVoiceAudio,
    AbbyVoiceDatasetBundle,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    stable_audio_id,
    stable_provenance_id,
    validate_bundle,
    validate_publishable,
)

_POLICY_ID = "policy:legacy-bucket-audio"
_AUDIO_SHA = sha256(b"historical audio").hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
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


def _response(*, response_id: str = "response-abby") -> AbbyVoiceResponse:
    return AbbyVoiceResponse(
        response_id=response_id,
        text="Call 211 for help.",
        spoken_text="Call two one one for help.",
        locale="en-US",
        license_id="MIT",
        consent_status="not_required",
    )


def _admission(
    response: AbbyVoiceResponse,
    *,
    audio: AbbyVoiceAudio | None = None,
    provenance: AbbyVoiceProvenance | None = None,
    disposition: AudioDisposition | None = None,
) -> AudioReconciliationResult:
    audio_id = stable_audio_id(_AUDIO_SHA, segment_kind="response")
    source_uri = "ipfs://bafy-admitted-audio"
    provenance_id = stable_provenance_id(
        audio_id,
        source_uri,
        "reconcile_voice_job_result",
        _AUDIO_SHA,
    )
    audio = audio or AbbyVoiceAudio(
        audio_id=audio_id,
        spoken_text=response.spoken_text,
        content_sha256=_AUDIO_SHA,
        response_id=response.response_id,
        uri=source_uri,
        segment_kind="response",
        mime_type="audio/mpeg",
        codec="mp3",
        byte_length=123,
        duration_ms=1000,
        sample_rate_hz=22050,
        channels=1,
        provenance_ids=(provenance_id,),
        license_id=response.license_id,
        consent_status=response.consent_status,
    )
    provenance = provenance or AbbyVoiceProvenance(
        provenance_id=provenance_id,
        subject_id=audio.audio_id,
        subject_schema_version=ABBY_VOICE_AUDIO_V2,
        transformation_name="reconcile_voice_job_result",
        transformation_version="1.0.0",
        source_uri=source_uri,
        source_revision="recovery:test",
        source_sha256=audio.content_sha256,
        locale=response.locale,
        license_id=response.license_id,
        consent_status=response.consent_status,
    )
    disposition = disposition or AudioDisposition(
        source_ref=f"voice-job:task-admit:{response.response_id}",
        source_sha256="d" * 64,
        status=AudioDispositionStatus.LINKED,
        reason=AudioDispositionReason.PROMOTED,
        subject_id=response.response_id,
        task_id="task-admit",
        work_item_id="work-admit",
        audio_id=audio.audio_id,
        artifact_sha256=audio.content_sha256,
        policy_identity=_POLICY_ID,
    )
    return AudioReconciliationResult(
        linked_audio=(audio,),
        provenance=(provenance,),
        dispositions=(disposition,),
        policy_identity=_POLICY_ID,
    )


def _write_normalized_build(root: Path) -> str:
    response = _response()
    row_counts = {
        "audio.jsonl": 0,
        "duplicate-ledger.jsonl": 0,
        "provenance.jsonl": 0,
        "quarantine.jsonl": 0,
        "responses.jsonl": 1,
        "templates.jsonl": 0,
        "warnings.jsonl": 0,
    }
    artifacts = {
        "audio.jsonl": b"",
        "duplicate-ledger.jsonl": b"",
        "provenance.jsonl": b"",
        "quality-report.json": _pretty_bytes(
            {
                "accepted": {
                    "audio": 0,
                    "provenance": 0,
                    "responses": 1,
                    "templates": 0,
                },
                "input_record_count": 1,
                "normalization_version": NORMALIZATION_VERSION,
                "schema_version": QUALITY_REPORT_VERSION,
                "source_manifest_count": 1,
            }
        ),
        "quarantine.jsonl": b"",
        "responses.jsonl": _canonical_bytes(response.to_dict()) + b"\n",
        "splits.json": _pretty_bytes({response.response_id: "train"}),
        "templates.jsonl": b"",
        "warnings.jsonl": b"",
    }
    manifest = {
        "deterministic": True,
        "files": [
            {
                "byte_length": len(content),
                "path": name,
                "sha256": sha256(content).hexdigest(),
                **(
                    {"row_count": row_counts[name]}
                    if name in row_counts
                    else {}
                ),
            }
            for name, content in sorted(artifacts.items())
        ],
        "input_record_count": 1,
        "normalization_version": NORMALIZATION_VERSION,
        "schema_version": ABBY_VOICE_NORMALIZED_BUILD_SCHEMA_VERSION,
        "source_manifest_count": 1,
    }
    root.mkdir()
    for name, content in artifacts.items():
        (root / name).write_bytes(content)
    manifest_bytes = _pretty_bytes(manifest)
    (root / "manifest.json").write_bytes(manifest_bytes)
    return sha256(manifest_bytes).hexdigest()


def _reseal_normalized_artifact(
    root: Path,
    *,
    name: str,
    content: bytes,
    row_count: int | None = None,
) -> str:
    (root / name).write_bytes(content)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = next(
        item for item in manifest["files"] if item["path"] == name
    )
    descriptor["byte_length"] = len(content)
    descriptor["sha256"] = sha256(content).hexdigest()
    if row_count is not None:
        descriptor["row_count"] = row_count
    manifest_bytes = _pretty_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    return sha256(manifest_bytes).hexdigest()


def test_load_normalized_dataset_bundle_verifies_manifest_and_rows(
    tmp_path: Path,
) -> None:
    normalized_dir = tmp_path / "normalized"
    manifest_sha256 = _write_normalized_build(normalized_dir)

    loaded = load_normalized_dataset_bundle(
        normalized_dir,
        expected_manifest_sha256=manifest_sha256,
    )

    assert isinstance(loaded, AbbyVoiceNormalizedDatasetLoadResult)
    assert loaded.bundle.responses == (_response(),)
    assert loaded.bundle.templates == ()
    assert loaded.bundle.audio == ()
    assert loaded.bundle.provenance == ()
    assert loaded.normalized_dir == str(normalized_dir.resolve())
    assert loaded.manifest_sha256 == manifest_sha256
    assert loaded.manifest_id == (
        f"abby-voice-normalized-build:sha256:{manifest_sha256}"
    )
    assert loaded.manifest["schema_version"] == (
        ABBY_VOICE_NORMALIZED_BUILD_SCHEMA_VERSION
    )
    assert loaded.source_manifest_count == 1
    assert loaded.input_record_count == 1


def test_load_normalized_dataset_bundle_rejects_manifest_or_file_tamper(
    tmp_path: Path,
) -> None:
    normalized_dir = tmp_path / "normalized"
    manifest_sha256 = _write_normalized_build(normalized_dir)

    with pytest.raises(
        AbbyVoiceDatasetMergeError,
        match="manifest SHA-256 mismatch",
    ):
        load_normalized_dataset_bundle(
            normalized_dir,
            expected_manifest_sha256="0" * 64,
        )

    responses_path = normalized_dir / "responses.jsonl"
    responses_path.write_bytes(responses_path.read_bytes() + b" ")
    with pytest.raises(
        AbbyVoiceDatasetMergeError,
        match="artifact checksum mismatch",
    ):
        load_normalized_dataset_bundle(
            normalized_dir,
            expected_manifest_sha256=manifest_sha256,
        )


def test_load_normalized_dataset_bundle_rejects_symlinked_artifact(
    tmp_path: Path,
) -> None:
    normalized_dir = tmp_path / "normalized"
    manifest_sha256 = _write_normalized_build(normalized_dir)
    response_path = normalized_dir / "responses.jsonl"
    external = tmp_path / "external-responses.jsonl"
    external.write_bytes(response_path.read_bytes())
    response_path.unlink()
    response_path.symlink_to(external)

    with pytest.raises(
        AbbyVoiceDatasetMergeError,
        match="not a regular file",
    ):
        load_normalized_dataset_bundle(
            normalized_dir,
            expected_manifest_sha256=manifest_sha256,
        )


@pytest.mark.parametrize("mode", ["extra", "missing"])
def test_load_normalized_dataset_bundle_rejects_unexpected_file_set(
    tmp_path: Path,
    mode: str,
) -> None:
    normalized_dir = tmp_path / "normalized"
    manifest_sha256 = _write_normalized_build(normalized_dir)
    if mode == "extra":
        (normalized_dir / "latest.json").write_text("{}\n", encoding="utf-8")
    else:
        (normalized_dir / "warnings.jsonl").unlink()

    with pytest.raises(
        AbbyVoiceDatasetMergeError,
        match="unexpected file set",
    ):
        load_normalized_dataset_bundle(
            normalized_dir,
            expected_manifest_sha256=manifest_sha256,
        )


def test_load_normalized_dataset_bundle_rejects_row_count_mismatch(
    tmp_path: Path,
) -> None:
    normalized_dir = tmp_path / "normalized"
    _write_normalized_build(normalized_dir)
    manifest_sha256 = _reseal_normalized_artifact(
        normalized_dir,
        name="responses.jsonl",
        content=(normalized_dir / "responses.jsonl").read_bytes(),
        row_count=2,
    )

    with pytest.raises(
        AbbyVoiceDatasetMergeError,
        match="row_count mismatch",
    ):
        load_normalized_dataset_bundle(
            normalized_dir,
            expected_manifest_sha256=manifest_sha256,
        )


def test_load_normalized_dataset_bundle_rejects_malformed_canonical_row(
    tmp_path: Path,
) -> None:
    normalized_dir = tmp_path / "normalized"
    _write_normalized_build(normalized_dir)
    manifest_sha256 = _reseal_normalized_artifact(
        normalized_dir,
        name="responses.jsonl",
        content=b'{"not":"a canonical voice row"}\n',
        row_count=1,
    )

    with pytest.raises(
        AbbyVoiceDatasetMergeError,
        match="canonical rows are invalid",
    ):
        load_normalized_dataset_bundle(
            normalized_dir,
            expected_manifest_sha256=manifest_sha256,
        )


def test_merge_links_audio_reciprocally_and_rebuilds_graphrag() -> None:
    response = _response()
    base = AbbyVoiceDatasetBundle(responses=(response,))
    admission = _admission(response)

    merged = merge_admitted_audio(base, admission)

    audio = merged.bundle.audio[0]
    linked_response = merged.bundle.responses[0]
    assert linked_response.audio_ids == (audio.audio_id,)
    assert audio.response_id == linked_response.response_id
    assert merged.bundle.provenance[0].subject_id == audio.audio_id
    assert merged.graphrag_index.bundle == merged.bundle
    assert merged.admitted_audio_ids == (audio.audio_id,)
    assert merged.response_audio_links == ((response.response_id, audio.audio_id),)
    assert merged.merge_id.startswith("abby-voice-dataset-merge:sha256:")
    assert validate_bundle(
        responses=merged.bundle.responses,
        templates=merged.bundle.templates,
        audio=merged.bundle.audio,
        provenance=merged.bundle.provenance,
    ) == merged.bundle
    validate_publishable(merged.bundle)


def test_merge_is_idempotent_and_content_addressed() -> None:
    response = _response()
    admission = _admission(response)
    first = merge_admitted_audio(
        AbbyVoiceDatasetBundle(responses=(response,)),
        admission,
    )
    repeated = merge_admitted_audio(first.bundle, admission)

    assert repeated.bundle == first.bundle
    assert repeated.graphrag_index.index_cid == first.graphrag_index.index_cid
    assert repeated.graphrag_index.graph_cid == first.graphrag_index.graph_cid
    assert repeated.merge_id == first.merge_id
    assert repeated.canonical_bytes() == first.canonical_bytes()


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"response_id": "response-missing"}, "unknown response"),
        ({"spoken_text": "Different spoken text."}, "text and locale"),
        ({"locale": "fr-FR"}, "text and locale"),
        ({"license_id": "CC0-1.0"}, "response rights"),
    ],
)
def test_merge_rejects_stale_or_unknown_response_binding(
    change: dict[str, object],
    error: str,
) -> None:
    response = _response()
    original = _admission(response)
    audio_changes = dict(change)
    if "spoken_text" in audio_changes:
        audio_changes["text_sha256"] = sha256(
            str(audio_changes["spoken_text"]).encode("utf-8")
        ).hexdigest()
    audio = replace(original.linked_audio[0], **audio_changes)
    provenance = replace(
        original.provenance[0],
        subject_id=audio.audio_id,
        source_sha256=audio.content_sha256,
        license_id=audio.license_id,
    )
    disposition = replace(
        original.dispositions[0],
        subject_id=str(audio.response_id),
        audio_id=audio.audio_id,
        artifact_sha256=audio.content_sha256,
    )
    admission = _admission(
        response,
        audio=audio,
        provenance=provenance,
        disposition=disposition,
    )

    with pytest.raises(AbbyVoiceDatasetMergeError, match=error):
        merge_admitted_audio(
            AbbyVoiceDatasetBundle(responses=(response,)),
            admission,
        )


def test_merge_rejects_forged_disposition_or_incomplete_provenance() -> None:
    response = _response()
    valid = _admission(response)
    quarantined = replace(
        valid.dispositions[0],
        status=AudioDispositionStatus.QUARANTINED,
        reason=AudioDispositionReason.STALE_POLICY,
        audio_id="",
    )
    forged = AudioReconciliationResult(
        linked_audio=valid.linked_audio,
        provenance=valid.provenance,
        dispositions=(quarantined,),
        policy_identity=_POLICY_ID,
    )

    with pytest.raises(AbbyVoiceDatasetMergeError, match="one-to-one"):
        merge_admitted_audio(
            AbbyVoiceDatasetBundle(responses=(response,)),
            forged,
        )

    extra = replace(
        valid.provenance[0],
        provenance_id="provenance-extra",
    )
    incomplete = AudioReconciliationResult(
        linked_audio=valid.linked_audio,
        provenance=(*valid.provenance, extra),
        dispositions=valid.dispositions,
        policy_identity=_POLICY_ID,
    )
    with pytest.raises(AbbyVoiceDatasetMergeError, match="exactly cover"):
        merge_admitted_audio(
            AbbyVoiceDatasetBundle(responses=(response,)),
            incomplete,
        )

    wrong_hash = replace(valid.provenance[0], source_sha256="e" * 64)
    misbound = AudioReconciliationResult(
        linked_audio=valid.linked_audio,
        provenance=(wrong_hash,),
        dispositions=valid.dispositions,
        policy_identity=_POLICY_ID,
    )
    with pytest.raises(AbbyVoiceDatasetMergeError, match="bind its audio row"):
        merge_admitted_audio(
            AbbyVoiceDatasetBundle(responses=(response,)),
            misbound,
        )


def test_merge_rejects_conflicting_existing_audio_identity() -> None:
    response = _response()
    admission = _admission(response)
    admitted_audio = admission.linked_audio[0]
    conflicting = replace(admitted_audio, uri="ipfs://bafy-conflicting-location")
    base = AbbyVoiceDatasetBundle(
        responses=(
            replace(response, audio_ids=(conflicting.audio_id,)),
        ),
        audio=(conflicting,),
        provenance=admission.provenance,
    )

    with pytest.raises(AbbyVoiceDatasetMergeError, match="conflicts"):
        merge_admitted_audio(base, admission)
