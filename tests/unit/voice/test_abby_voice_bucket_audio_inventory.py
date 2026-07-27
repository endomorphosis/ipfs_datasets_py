"""Normalized bucket-audio inventory schema tests."""

from __future__ import annotations

from ipfs_datasets_py.voice.bucket_audio_inventory import (
    BucketAudioObjectClass,
    build_bucket_audio_inventory,
    classify_bucket_audio_object,
    discover_production_run_ids,
)


def test_classify_response_linkable_and_orphan_paths():
    assert classify_bucket_audio_object(
        path=(
            "runs/abby-full-preprocess-20260622T152102Z/phase4-residual/audio/"
            "abby-tts-8b88893b24d09bf99fdf.mp3"
        ),
        size_bytes=100,
    )[0] is BucketAudioObjectClass.RESPONSE_LINKABLE

    assert classify_bucket_audio_object(
        path="spk_1779904536.wav",
        size_bytes=100,
    )[0] is BucketAudioObjectClass.SPEAKER_PROMPT

    assert classify_bucket_audio_object(
        path="smoke-tests/example.wav",
        size_bytes=100,
    )[0] is BucketAudioObjectClass.DIAGNOSTIC_SMOKE

    assert classify_bucket_audio_object(
        path="spk_1779908396-item-1.wav",
        size_bytes=0,
    )[0] is BucketAudioObjectClass.EMPTY_PLACEHOLDER

    assert classify_bucket_audio_object(
        path="spk_1779904572-batch.zip",
        size_bytes=70,
    )[0] is BucketAudioObjectClass.ARCHIVE_BUNDLE


def test_inventory_summarizes_all_discovered_objects_and_run_ids():
    objects = [
        {
            "path": (
                "runs/abby-full-preprocess-20260622T152102Z/phase4/audio/"
                "abby-tts-aaaaaaaaaaaaaaaaaaaa.mp3"
            ),
            "size": 10,
            "xet_hash": "x" * 64,
        },
        {
            "path": (
                "runs/abby-full-preprocess-20260605T063738Z/phase1-bm25/audio/"
                "abby-tts-bbbbbbbbbbbbbbbbbbbb.mp3"
            ),
            "size": 11,
            "xet_hash": "y" * 64,
        },
        {
            "path": "spk_1779904536.wav",
            "size": 12,
            "xet_hash": "z" * 64,
        },
        {
            "path": "local_batch_gpu_smoke.log",
            "size": 13,
            "xet_hash": "w" * 64,
        },
    ]
    inventory = build_bucket_audio_inventory(
        objects,
        bucket_id="Publicus/abby-voice",
        listing_sha256="a" * 64,
    )

    summary = inventory.summary()
    assert summary["object_count"] == 4
    assert summary["response_linkable_count"] == 2
    assert summary["class_counts"]["response_linkable"] == 2
    assert summary["class_counts"]["speaker_prompt"] == 1
    assert summary["class_counts"]["log_or_metadata"] == 1
    assert inventory.production_run_ids == (
        "abby-full-preprocess-20260605T063738Z",
        "abby-full-preprocess-20260622T152102Z",
    )
    assert discover_production_run_ids(objects) == inventory.production_run_ids
    # Round-trip preserves identity.
    restored = type(inventory).from_dict(inventory.to_dict())
    assert restored.inventory_id == inventory.inventory_id
    assert len(restored.to_jsonl_bytes().splitlines()) == 4
