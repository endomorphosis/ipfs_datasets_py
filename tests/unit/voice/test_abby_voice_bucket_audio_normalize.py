"""Full-bucket audio entry normalization tests."""

from __future__ import annotations

from ipfs_datasets_py.voice.bucket_audio_inventory import build_bucket_audio_inventory
from ipfs_datasets_py.voice.bucket_audio_normalize import (
    BucketAudioMappingStatus,
    normalize_bucket_audio_entries,
)
from ipfs_datasets_py.voice.bucket_audio_plan import plan_abby_voice_bucket_audio
from ipfs_datasets_py.voice.normalize import normalize_manifest


def _source(text: str) -> dict[str, object]:
    from hashlib import sha256

    collapsed = " ".join(text.split())
    legacy = sha256(collapsed.encode("utf-8")).hexdigest()[:20]
    return {
        "id": f"abby-tts-{legacy}",
        "text": text,
        "textHash": legacy,
        "accepted": True,
        "locale": "en-US",
    }


def test_normalize_covers_all_objects_including_unmapped_linkable():
    matched = _source("This accepted response has production audio.")
    other = _source("This orphan abby-tts file is not in the accepted corpus.")
    # Force other into a different hash by ensuring distinct text.
    assert matched["textHash"] != other["textHash"]

    normalized_manifest = normalize_manifest({"responses": [matched]})
    objects = [
        {
            "path": (
                "runs/abby-full-preprocess-20260622T152102Z/phase4/audio/"
                f"abby-tts-{matched['textHash']}.mp3"
            ),
            "size": 100,
            "xet_hash": "a" * 64,
        },
        {
            "path": (
                "runs/abby-full-preprocess-20260605T063738Z/phase1-bm25/audio/"
                f"abby-tts-{matched['textHash']}.mp3"
            ),
            "size": 90,
            "xet_hash": "b" * 64,
        },
        {
            "path": (
                "runs/abby-full-preprocess-20260622T152102Z/phase4/audio/"
                f"abby-tts-{other['textHash']}.mp3"
            ),
            "size": 80,
            "xet_hash": "c" * 64,
        },
        {
            "path": "spk_1779904536.wav",
            "size": 70,
            "xet_hash": "d" * 64,
        },
        {
            "path": "smoke-tests/note.log",
            "size": 10,
            "xet_hash": "e" * 64,
        },
    ]
    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [matched]},
        accepted_responses=normalized_manifest.responses,
        discovered_objects=objects,
        allowed_run_ids=(
            "abby-full-preprocess-20260622T152102Z",
            "abby-full-preprocess-20260605T063738Z",
        ),
    )
    inventory = build_bucket_audio_inventory(
        objects,
        bucket_id="Publicus/abby-voice",
        listing_sha256="f" * 64,
    )

    bundle = normalize_bucket_audio_entries(
        inventory=inventory,
        plan=plan,
        plan_id=plan.plan_id,
    )

    assert len(bundle.entries) == 5
    summary = bundle.summary()
    assert summary["entry_count"] == 5
    assert summary["response_linkable_count"] == 3
    assert summary["preferred_selection_count"] == 1
    assert summary["unmapped_linkable_count"] == 1
    assert summary["mapping_status_counts"][
        BucketAudioMappingStatus.SELECTED_FOR_RESPONSE.value
    ] == 1
    assert summary["mapping_status_counts"][
        BucketAudioMappingStatus.ALTERNATE_FOR_RESPONSE.value
    ] == 1
    assert summary["mapping_status_counts"][
        BucketAudioMappingStatus.UNMAPPED_LINKABLE.value
    ] == 1
    assert summary["mapping_status_counts"][
        BucketAudioMappingStatus.NON_RESPONSE_AUDIO.value
    ] == 1
    assert summary["mapping_status_counts"][
        BucketAudioMappingStatus.METADATA_ONLY.value
    ] == 1

    by_path = {item.path: item for item in bundle.entries}
    preferred = by_path[
        f"runs/abby-full-preprocess-20260622T152102Z/phase4/audio/"
        f"abby-tts-{matched['textHash']}.mp3"
    ]
    assert preferred.is_preferred_selection is True
    assert preferred.response_id is not None
    assert preferred.mapping_status is BucketAudioMappingStatus.SELECTED_FOR_RESPONSE

    alternate = by_path[
        f"runs/abby-full-preprocess-20260605T063738Z/phase1-bm25/audio/"
        f"abby-tts-{matched['textHash']}.mp3"
    ]
    assert alternate.is_preferred_selection is False
    assert alternate.response_id == preferred.response_id
    assert alternate.mapping_status is BucketAudioMappingStatus.ALTERNATE_FOR_RESPONSE

    unmapped = by_path[
        f"runs/abby-full-preprocess-20260622T152102Z/phase4/audio/"
        f"abby-tts-{other['textHash']}.mp3"
    ]
    assert unmapped.response_id is None
    assert unmapped.mapping_status is BucketAudioMappingStatus.UNMAPPED_LINKABLE

    # Round-trip
    restored = type(bundle).from_dict(bundle.to_dict())
    assert restored.normalized_id == bundle.normalized_id
    assert len(restored.to_jsonl_bytes().splitlines()) == 5
