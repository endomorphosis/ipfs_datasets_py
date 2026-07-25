"""Offline evidence tests for the deterministic Abby dataset manager."""

from __future__ import annotations

from hashlib import sha256

import pytest

from ipfs_datasets_py.huggingface.bucket import (
    HuggingFaceBucketInventory,
    HuggingFaceBucketObject,
)
from ipfs_datasets_py.voice.dataset_manager import (
    AbbyVoiceDatasetManager,
    PinnedVoiceSource,
)
from ipfs_datasets_py.voice.legacy_sources import (
    LegacyAudioCandidate,
    LegacyDispositionReason,
    LegacyDispositionStatus,
    reconcile_legacy_audio_candidates,
)
from ipfs_datasets_py.voice.normalize import normalize_manifest
from ipfs_datasets_py.voice.schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    sha256_text,
    stable_audio_id,
    stable_response_id,
    validate_bundle,
)
from ipfs_datasets_py.voice.workset import (
    AudioArtifactDescriptor,
    AudioWorkOperation,
    AudioWorkReason,
    VoiceAudioWorkset,
)

_REVISION = "a" * 40
_WAV = b"RIFF" + (4).to_bytes(4, "little") + b"WAVE"
_WAV_SHA = sha256(_WAV).hexdigest()


def _source(payload, name="responses.json"):
    return PinnedVoiceSource.from_payload(
        payload,
        dataset_id="Publicus/abby-voice",
        dataset_revision=_REVISION,
        repository_file=name,
    )


def _inventory(*objects):
    return HuggingFaceBucketInventory(
        bucket_id=f"Publicus/abby-audio@{'b' * 40}",
        objects=tuple(objects),
    )


def _audio_object(path="audio/exact.wav", **changes):
    values = {
        "path": path,
        "size_bytes": len(_WAV),
        "sha256": _WAV_SHA,
        "etag": "immutable-etag",
        "media_type": "audio/wav",
    }
    values.update(changes)
    return HuggingFaceBucketObject(**values)


def _canonical_response(identifier="one", text="This is an exact response."):
    payload = {
        "responses": [
            {
                "id": identifier,
                "text": text,
                "sourceIds": [f"doc-{identifier}"],
                "license_id": "CC0-1.0",
                "consent_status": "granted",
            }
        ]
    }
    row = normalize_manifest(payload, source_uri="fixture://identity").responses[0]
    return payload, row


def test_package_level_dataset_manager_exports_preserve_direct_module_identity():
    import ipfs_datasets_py.voice as voice
    from ipfs_datasets_py.voice.legacy_sources import LegacyAudioCandidate as DirectCandidate
    from ipfs_datasets_py.voice.workset import VoiceAudioWorkset as DirectWorkset

    assert voice.AbbyVoiceDatasetManager is AbbyVoiceDatasetManager
    assert voice.LegacyAudioCandidate is DirectCandidate
    assert voice.VoiceAudioWorkset is DirectWorkset
    assert voice.reconcile_legacy_audio_candidates is reconcile_legacy_audio_candidates


def test_manager_composes_strict_four_config_bundle_and_artifact_evidence():
    payload, row = _canonical_response()
    source = _source(payload)
    candidate = LegacyAudioCandidate(
        candidate_id="candidate-exact",
        subject_id=row.response_id,
        spoken_text=row.spoken_text,
        paths=("audio/exact.wav",),
        expected_sha256=_WAV_SHA,
        media_type="audio/wav",
    )
    inventory = _inventory(
        _audio_object(),
        HuggingFaceBucketObject(
            path="metadata/readme.json",
            size_bytes=2,
            sha256=sha256(b"{}").hexdigest(),
            etag="metadata-etag",
            media_type="application/json",
        ),
    )

    result = AbbyVoiceDatasetManager(repository_commit="commit:test").build(
        sources=(source,),
        inventory=inventory,
        legacy_candidates=(candidate,),
        byte_resolver=lambda path: _WAV if path == "audio/exact.wav" else None,
        decode_validator=lambda payload, media: payload == _WAV and media == "audio/wav",
        evaluation_support_bytes=b'{"metric":"pending"}\n',
    )

    assert validate_bundle(
        responses=result.bundle.responses,
        templates=result.bundle.templates,
        audio=result.bundle.audio,
        provenance=result.bundle.provenance,
    ) == result.bundle
    assert set(result.four_config_bundle) == {
        ABBY_VOICE_RESPONSE_V2,
        ABBY_VOICE_TEMPLATE_V2,
        ABBY_VOICE_AUDIO_V2,
        ABBY_VOICE_PROVENANCE_V2,
    }
    assert result.bundle.responses[0].audio_ids == (result.bundle.audio[0].audio_id,)
    assert result.bundle.audio[0].provenance_ids
    assert set(result.bundle.audio[0].provenance_ids) <= {
        item.provenance_id for item in result.bundle.provenance
    }
    assert result.graphrag_index.bundle == result.bundle
    assert result.artifact_manifest.manifest_id
    assert result.evaluation_support_artifact is not None
    assert result.evaluation_support_artifact.review_status == "support_pending_g018"
    assert "abby_voice_evaluation_v2" not in result.four_config_bundle
    assert result.artifact_manifest.deterministic_metadata["evaluation_support"]["status"] == (
        "pending_abby_voice_evaluation_v2"
    )

    refs = [item.source_ref for item in result.dispositions]
    assert len(refs) == len(set(refs)) == 4  # input row + candidate + two inventory objects
    assert any(item.reason == "exact_verified_link" for item in result.dispositions)
    assert any(item.reason == "non_audio_inventory_object" for item in result.dispositions)


def test_manager_dispositions_use_pinned_identity_for_canonical_provenance_input():
    payload, row = _canonical_response()
    provenance = AbbyVoiceProvenance(
        provenance_id="provenance-upstream",
        subject_id=row.response_id,
        subject_schema_version=ABBY_VOICE_RESPONSE_V2,
        transformation_name="upstream_import",
        transformation_version="1",
        source_uri="external://upstream",
        source_revision="revision:upstream",
        source_sha256="c" * 64,
        license_id="CC0-1.0",
        consent_status="granted",
    )
    payload["provenance"] = [provenance.to_dict()]
    source = _source(payload, "bundle.json")

    result = AbbyVoiceDatasetManager(repository_commit="commit:test").build(
        sources=(source,),
        inventory=_inventory(),
    )

    expected_ref = (
        f"{source.snapshot.logical_source}#"
        f"{ABBY_VOICE_PROVENANCE_V2}/{provenance.provenance_id}"
    )
    refs = {item.source_ref for item in result.dispositions}
    assert expected_ref in refs
    assert provenance.source_uri not in refs
    assert len(refs) == result.normalization.input_record_count


def test_manager_rejects_duplicate_pinned_source_identities():
    source, _ = _canonical_response()
    source = _source(source)

    with pytest.raises(ValueError, match="source identities must be unique"):
        AbbyVoiceDatasetManager(repository_commit="commit:test").build(
            sources=(source, source),
            inventory=_inventory(),
        )


def test_manager_rejects_nonpublishable_canonical_rows():
    source = _source({"responses": [{"id": "one", "text": "Safe useful response."}]})

    with pytest.raises(ValueError, match="not publishable|publication-ready"):
        AbbyVoiceDatasetManager(repository_commit="commit:test").build(
            sources=(source,),
            inventory=_inventory(),
        )


@pytest.mark.parametrize(
    "payload", (b"", b"\n", b"\xff", b"not-json\n", b"[1,2,3]\n")
)
def test_manager_rejects_mislabeled_evaluation_support(payload):
    source, _ = _canonical_response()

    with pytest.raises(ValueError, match="evaluation support"):
        AbbyVoiceDatasetManager(repository_commit="commit:test").build(
            sources=(_source(source),),
            inventory=_inventory(),
            evaluation_support_bytes=payload,
        )


@pytest.mark.parametrize(
    ("spoken_text", "paths", "subject_suffix", "reason"),
    [
        (
            "This is a nearby response.",
            ("audio/exact.wav",),
            "",
            LegacyDispositionReason.FUZZY_MATCH_REVIEW_REQUIRED,
        ),
        (
            "This is an exact response.",
            ("audio/exact.wav", "audio/other.wav"),
            "",
            LegacyDispositionReason.AMBIGUOUS_PATH_REVIEW_REQUIRED,
        ),
        (
            "This is an exact response.",
            ("audio/exact.wav",),
            "-nearby",
            LegacyDispositionReason.UNKNOWN_SUBJECT,
        ),
    ],
)
def test_fuzzy_and_ambiguous_legacy_candidates_are_review_only_quarantine(
    spoken_text, paths, subject_suffix, reason
):
    _, row = _canonical_response()
    candidate = LegacyAudioCandidate(
        candidate_id="candidate-review",
        subject_id=row.response_id + subject_suffix,
        spoken_text=spoken_text,
        paths=paths,
        expected_sha256=_WAV_SHA,
        media_type="audio/wav",
    )
    inventory = _inventory(_audio_object(), _audio_object("audio/other.wav"))

    result = reconcile_legacy_audio_candidates(
        subjects=(row,),
        candidates=(candidate,),
        inventory=inventory,
        byte_resolver=lambda _path: _WAV,
        decode_validator=lambda *_args: True,
    )

    disposition = next(
        item for item in result.dispositions if item.source_ref == candidate.source_ref
    )
    assert disposition.status is LegacyDispositionStatus.REVIEW
    assert disposition.reason is reason
    assert not result.linked_audio
    assert disposition in result.review_quarantine


@pytest.mark.parametrize(
    ("path", "claimed_hash"),
    [
        ("exact.wav", _WAV_SHA),
        ("audio/exact.wav", _WAV_SHA[:16]),
    ],
)
def test_basename_and_truncated_hash_candidates_are_retained_for_review(
    path, claimed_hash
):
    _, row = _canonical_response()
    candidate = LegacyAudioCandidate(
        "candidate-fuzzy-identity",
        row.response_id,
        row.spoken_text,
        (path,),
        claimed_hash,
        "audio/wav",
    )

    result = reconcile_legacy_audio_candidates(
        subjects=(row,),
        candidates=(candidate,),
        inventory=_inventory(_audio_object()),
        byte_resolver=lambda _path: _WAV,
        decode_validator=lambda *_args: True,
    )

    disposition = next(item for item in result.dispositions if item.candidate_id)
    assert disposition.status is LegacyDispositionStatus.REVIEW
    assert disposition.reason is LegacyDispositionReason.FUZZY_MATCH_REVIEW_REQUIRED
    assert not result.linked_audio


def test_multiple_exact_paths_for_one_subject_remain_ambiguous_review():
    _, row = _canonical_response()
    candidates = tuple(
        LegacyAudioCandidate(
            f"candidate-{index}",
            row.response_id,
            row.spoken_text,
            (path,),
            _WAV_SHA,
            "audio/wav",
        )
        for index, path in enumerate(("audio/exact.wav", "audio/other.wav"))
    )
    result = reconcile_legacy_audio_candidates(
        subjects=(row,),
        candidates=candidates,
        inventory=_inventory(_audio_object(), _audio_object("audio/other.wav")),
        byte_resolver=lambda _path: _WAV,
        decode_validator=lambda *_args: True,
    )

    candidate_dispositions = [item for item in result.dispositions if item.candidate_id]
    assert not result.linked_audio
    assert {item.reason for item in candidate_dispositions} == {
        LegacyDispositionReason.AMBIGUOUS_PATH_REVIEW_REQUIRED
    }


def test_one_inventory_path_cannot_link_to_multiple_subjects():
    spoken_text = "The exact shared spoken text."
    subjects = (
        AbbyVoiceResponse("response-one", spoken_text, spoken_text),
        AbbyVoiceResponse("response-two", spoken_text, spoken_text),
    )
    item = _audio_object()
    candidates = tuple(
        LegacyAudioCandidate(
            f"candidate-{index}",
            row.response_id,
            row.spoken_text,
            (item.path,),
            item.sha256,
            item.media_type,
        )
        for index, row in enumerate(subjects)
    )

    result = reconcile_legacy_audio_candidates(
        subjects=subjects,
        candidates=candidates,
        inventory=_inventory(item),
        byte_resolver=lambda _path: _WAV,
        decode_validator=lambda *_args: True,
    )

    assert not result.linked_audio
    candidate_dispositions = [item for item in result.dispositions if item.candidate_id]
    assert len(candidate_dispositions) == 2
    assert {item.reason for item in candidate_dispositions} == {
        LegacyDispositionReason.AMBIGUOUS_PATH_REVIEW_REQUIRED
    }


def test_empty_normalized_text_and_locale_mismatch_never_link():
    item = _audio_object()
    subject = AbbyVoiceResponse(
        "response-url",
        "https://example.test/one",
        "https://example.test/one",
        locale="en-US",
    )
    locale_subject = AbbyVoiceResponse(
        "response-locale",
        "Exact locale-sensitive text.",
        "Exact locale-sensitive text.",
        locale="en-US",
    )
    candidates = (
        LegacyAudioCandidate(
            "candidate-empty-identity",
            subject.response_id,
            "https://example.test/two",
            (item.path,),
            item.sha256,
            item.media_type,
        ),
        LegacyAudioCandidate(
            "candidate-locale",
            locale_subject.response_id,
            locale_subject.spoken_text,
            ("audio/locale.wav",),
            item.sha256,
            item.media_type,
            locale="fr-FR",
        ),
    )
    locale_item = _audio_object(path="audio/locale.wav")

    result = reconcile_legacy_audio_candidates(
        subjects=(subject, locale_subject),
        candidates=candidates,
        inventory=_inventory(item, locale_item),
        byte_resolver=lambda _path: _WAV,
        decode_validator=lambda *_args: True,
    )

    assert not result.linked_audio
    reasons = {
        item.candidate_id: item.reason
        for item in result.dispositions
        if item.candidate_id
    }
    assert reasons["candidate-empty-identity"] is LegacyDispositionReason.TEXT_IDENTITY_MISMATCH
    assert reasons["candidate-locale"] is LegacyDispositionReason.LOCALE_MISMATCH


@pytest.mark.parametrize(
    ("object_changes", "payload", "decode", "expected_reason"),
    [
        ({"sha256": "1" * 64}, _WAV, True, "fuzzy_match_review_required"),
        ({"size_bytes": len(_WAV) + 1}, _WAV, True, "size_mismatch"),
        ({}, b"not wave bytes", True, "sha256_mismatch"),
        ({}, _WAV, False, "decode_failed"),
    ],
)
def test_integrity_failures_never_auto_link(
    object_changes, payload, decode, expected_reason
):
    _, row = _canonical_response()
    item = _audio_object(**object_changes)
    candidate = LegacyAudioCandidate(
        "candidate-integrity",
        row.response_id,
        row.spoken_text,
        (item.path,),
        _WAV_SHA,
        "audio/wav",
    )

    result = reconcile_legacy_audio_candidates(
        subjects=(row,),
        candidates=(candidate,),
        inventory=_inventory(item),
        byte_resolver=lambda _path: payload,
        decode_validator=lambda *_args: decode,
    )

    assert not result.linked_audio
    disposition = next(item for item in result.dispositions if item.candidate_id)
    assert disposition.reason.value == expected_reason


def test_missing_decode_validator_never_auto_links_verified_magic_bytes():
    _, row = _canonical_response()
    item = _audio_object()
    candidate = LegacyAudioCandidate(
        "candidate-without-decoder",
        row.response_id,
        row.spoken_text,
        (item.path,),
        _WAV_SHA,
        "audio/wav",
    )

    result = reconcile_legacy_audio_candidates(
        subjects=(row,),
        candidates=(candidate,),
        inventory=_inventory(item),
        byte_resolver=lambda _path: _WAV,
    )

    assert not result.linked_audio
    disposition = next(item for item in result.dispositions if item.candidate_id)
    assert disposition.status is LegacyDispositionStatus.QUARANTINED
    assert disposition.reason is LegacyDispositionReason.DECODE_VALIDATOR_UNAVAILABLE


@pytest.mark.parametrize(
    "uri",
    (
        "/tmp/audio.wav",
        "audio/local.wav",
        "file:///tmp/audio.wav",
        "data:audio/wav;base64,UklGRg==",
        "https://user:password@example.test/audio.wav",
        "https://example.test/audio.wav?access_token=secret",
        "https://example.test/../private/audio.wav",
        "https://example.test/audio.wav#local-fragment",
    ),
)
def test_audio_work_descriptors_reject_local_raw_or_credentialed_uris(uri):
    with pytest.raises(ValueError, match="audio uri"):
        AudioArtifactDescriptor(
            audio_id="audio:test",
            content_sha256=_WAV_SHA,
            byte_length=len(_WAV),
            media_type="audio/wav",
            uri=uri,
        )


def test_deterministic_tts_asr_and_validation_work_manifests_cover_selection_matrix():
    def response(label):
        text = f"This is the {label} response."
        return AbbyVoiceResponse(
            response_id=stable_response_id(text, text),
            text=text,
            spoken_text=text,
        )

    current, missing, corrupt, stale, revalidate, text_only = (
        response(label)
        for label in ("current", "missing", "corrupt", "stale", "revalidate", "text only")
    )

    def audio(row):
        digest = sha256(row.response_id.encode()).hexdigest()
        return AbbyVoiceAudio(
            audio_id=stable_audio_id(digest),
            spoken_text=row.spoken_text,
            content_sha256=digest,
            response_id=row.response_id,
            uri=f"ipfs://bafy-{row.response_id}",
            byte_length=123,
        )

    workset = VoiceAudioWorkset.build(
        responses=(text_only, revalidate, stale, corrupt, missing, current),
        audio=(audio(current), audio(corrupt), audio(stale), audio(revalidate)),
        source_manifest_id=f"manifest:sha256:{'a' * 64}",
        policy_id=f"policy:sha256:{'b' * 64}",
        corrupt_subject_ids=(corrupt.response_id,),
        stale_policy_subject_ids=(stale.response_id,),
        revalidate_subject_ids=(revalidate.response_id,),
        intentionally_text_only_subject_ids=(text_only.response_id,),
    )
    reversed_workset = VoiceAudioWorkset.build(
        responses=(current, missing, corrupt, stale, revalidate, text_only),
        audio=tuple(reversed((audio(current), audio(corrupt), audio(stale), audio(revalidate)))),
        source_manifest_id=f"manifest:sha256:{'a' * 64}",
        policy_id=f"policy:sha256:{'b' * 64}",
        corrupt_subject_ids=(corrupt.response_id,),
        stale_policy_subject_ids=(stale.response_id,),
        revalidate_subject_ids=(revalidate.response_id,),
        intentionally_text_only_subject_ids=(text_only.response_id,),
    )

    assert workset.canonical_bytes() == reversed_workset.canonical_bytes()
    assert workset.workset_id == reversed_workset.workset_id
    assert {item.subject_id for item in workset.tts_manifest.items} == {
        missing.response_id,
        corrupt.response_id,
        stale.response_id,
    }
    assert {item.reason for item in workset.tts_manifest.items} == {
        AudioWorkReason.MISSING,
        AudioWorkReason.CORRUPT,
        AudioWorkReason.STALE_POLICY,
    }
    assert {item.subject_id for item in workset.asr_manifest.items} == {
        missing.response_id,
        corrupt.response_id,
        stale.response_id,
        revalidate.response_id,
    }
    assert {item.subject_id for item in workset.validation_manifest.items} == {
        missing.response_id,
        corrupt.response_id,
        stale.response_id,
        revalidate.response_id,
    }
    assert all(item.operation is AudioWorkOperation.TTS for item in workset.tts_manifest.items)
    assert b"audio_validation" in workset.validation_manifest.canonical_bytes()
    assert _WAV not in workset.canonical_bytes()


def test_stale_text_audio_is_corrupt_work_not_current_audio():
    text = "Current response text."
    row = AbbyVoiceResponse(
        response_id=stable_response_id(text, text),
        text=text,
        spoken_text=text,
    )
    stale_audio = AbbyVoiceAudio(
        audio_id="audio-stale-text",
        spoken_text="Stale response text.",
        content_sha256="d" * 64,
        response_id=row.response_id,
        uri="ipfs://bafy-stale",
        byte_length=12,
    )

    workset = VoiceAudioWorkset.build(
        responses=(row,),
        audio=(stale_audio,),
        source_manifest_id="manifest:source",
        policy_id="policy:audio",
    )

    assert len(workset.tts_manifest.items) == 1
    assert workset.tts_manifest.items[0].reason is AudioWorkReason.CORRUPT
    assert {item.subject_id for item in workset.items} == {row.response_id}


def test_workset_rejects_duplicate_audio_ids_and_overlapping_policy():
    text = "Current response text."
    row = AbbyVoiceResponse(
        response_id=stable_response_id(text, text),
        text=text,
        spoken_text=text,
    )
    audio_rows = tuple(
        AbbyVoiceAudio(
            audio_id="audio-conflict",
            spoken_text=text,
            content_sha256=character * 64,
            response_id=row.response_id,
            uri=f"ipfs://bafy-{character}",
            byte_length=12,
        )
        for character in ("a", "b")
    )
    kwargs = {
        "responses": (row,),
        "source_manifest_id": "manifest:source",
        "policy_id": "policy:audio",
    }

    with pytest.raises(ValueError, match="audio IDs must be unique"):
        VoiceAudioWorkset.build(audio=audio_rows, **kwargs)
    with pytest.raises(ValueError, match="must not overlap"):
        VoiceAudioWorkset.build(
            corrupt_subject_ids=(row.response_id,),
            intentionally_text_only_subject_ids=(row.response_id,),
            **kwargs,
        )


def test_manager_rebuild_is_byte_identical_and_input_order_independent():
    first_payload, first_row = _canonical_response("one", "This is response one.")
    second_payload, _ = _canonical_response("two", "This is response two.")
    first_source = _source(first_payload, "one.json")
    second_source = _source(second_payload, "two.json")
    candidate = LegacyAudioCandidate(
        "candidate-one",
        first_row.response_id,
        first_row.spoken_text,
        ("audio/exact.wav",),
        _WAV_SHA,
        "audio/wav",
    )
    inventory = _inventory(_audio_object())
    manager = AbbyVoiceDatasetManager(repository_commit="commit:deterministic")

    forward = manager.build(
        sources=(first_source, second_source),
        inventory=inventory,
        legacy_candidates=(candidate,),
        byte_resolver=lambda _path: _WAV,
        decode_validator=lambda *_args: True,
    )
    reverse = manager.build(
        sources=(second_source, first_source),
        inventory=HuggingFaceBucketInventory(
            bucket_id=inventory.bucket_id,
            objects=tuple(reversed(inventory.objects)),
        ),
        legacy_candidates=tuple(reversed((candidate,))),
        byte_resolver=lambda _path: _WAV,
        decode_validator=lambda *_args: True,
    )

    assert forward.workset.canonical_bytes() == reverse.workset.canonical_bytes()
    assert forward.disposition_bytes() == reverse.disposition_bytes()
    assert forward.graphrag_index.index_cid == reverse.graphrag_index.index_cid
    assert forward.graphrag_index.graph_cid == reverse.graphrag_index.graph_cid
    assert forward.artifact_manifest.deterministic_bytes() == (
        reverse.artifact_manifest.deterministic_bytes()
    )
    assert dict(forward.artifact_payloads) == dict(reverse.artifact_payloads)


def test_pinned_source_and_workset_fail_closed_on_identity_errors():
    payload = {"responses": [{"id": "one", "text": "Safe useful response."}]}
    source = _source(payload)
    with pytest.raises(ValueError, match="SHA-256"):
        PinnedVoiceSource(source.snapshot, source.source_bytes[:-1] + b"x")

    row = AbbyVoiceResponse(
        response_id="response-one",
        text="Safe useful response.",
        spoken_text="Safe useful response.",
    )
    with pytest.raises(ValueError, match="unknown subject"):
        VoiceAudioWorkset.build(
            responses=(row,),
            source_manifest_id="manifest:pinned",
            policy_id="policy:pinned",
            revalidate_subject_ids=("response-does-not-exist",),
        )
    assert sha256_text(row.spoken_text) == row.content_sha256
