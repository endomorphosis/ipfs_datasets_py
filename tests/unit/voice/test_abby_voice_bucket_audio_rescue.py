"""Tests for unmapped bucket-audio rescue (hash join + ASR matching)."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.voice.bucket_audio_inventory import build_bucket_audio_inventory
from ipfs_datasets_py.voice.bucket_audio_normalize import (
    BucketAudioMappingStatus,
    normalize_bucket_audio_entries,
)
from ipfs_datasets_py.voice.bucket_audio_plan import plan_abby_voice_bucket_audio
from ipfs_datasets_py.voice.bucket_audio_rescue import (
    AsrRescueCandidate,
    load_text_hash_catalog,
    rescue_unmapped_by_asr,
    rescue_unmapped_by_text_hash,
)
from ipfs_datasets_py.voice.normalize import normalize_manifest
from ipfs_datasets_py.voice.bucket_audio_normalize import (
    BucketAudioMappingMethod,
    BucketAudioSubjectKind,
)


def _response_source(text: str) -> dict[str, object]:
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


def test_hash_join_rescues_bm25_vocabulary_terms(tmp_path: Path):
    matched = _response_source("This accepted response has production audio.")
    vocab_text = "Portland"
    from hashlib import sha256

    vocab_hash = sha256(" ".join(vocab_text.split()).encode()).hexdigest()[:20]
    bm25_manifest = {
        "responses": [
            {
                "id": f"abby-tts-vocab-{vocab_hash}",
                "textHash": vocab_hash,
                "text": vocab_text,
            }
        ]
    }
    bm25_path = tmp_path / "bm25.json"
    bm25_path.write_text(json.dumps(bm25_manifest), encoding="utf-8")

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
                f"abby-tts-{vocab_hash}.mp3"
            ),
            "size": 12,
            "xet_hash": "b" * 64,
        },
    ]
    normalized_manifest = normalize_manifest({"responses": [matched]})
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
        listing_sha256="c" * 64,
    )
    bundle = normalize_bucket_audio_entries(
        inventory=inventory, plan=plan, plan_id=plan.plan_id
    )
    assert bundle.summary()["unmapped_linkable_count"] == 1

    catalog = load_text_hash_catalog(
        bm25_path,
        catalog_name="bm25",
        subject_kind=BucketAudioSubjectKind.BM25_TERM,
    )
    rescued, stats = rescue_unmapped_by_text_hash(
        bundle,
        [
            (
                catalog,
                BucketAudioMappingStatus.MAPPED_TO_VOCABULARY,
                BucketAudioMappingMethod.BM25_TEXT_HASH,
            )
        ],
    )
    assert stats["rescued"] == 1
    assert rescued.summary()["unmapped_linkable_count"] == 0
    vocab_entry = next(
        item
        for item in rescued.entries
        if item.legacy_text_hash == vocab_hash
    )
    assert vocab_entry.mapping_status is BucketAudioMappingStatus.MAPPED_TO_VOCABULARY
    assert vocab_entry.source_text == "Portland"
    assert vocab_entry.subject_kind is BucketAudioSubjectKind.BM25_TERM


def test_asr_rescue_matches_response_by_normalized_identity():
    from ipfs_datasets_py.voice.schema import AbbyVoiceResponse, stable_response_id
    from ipfs_datasets_py.voice.normalize import normalize_indextts_spoken_text

    spoken_src = "Call two one one for local resources."
    orphan_hash = "f" * 20
    spoken = normalize_indextts_spoken_text(spoken_src)
    response_id = stable_response_id(spoken_src, spoken, "en-US", None)
    response = AbbyVoiceResponse(
        response_id=response_id,
        text=spoken_src,
        spoken_text=spoken,
        locale="en-US",
    )
    objects = [
        {
            "path": f"runs/orphan/audio/abby-tts-{orphan_hash}.mp3",
            "size": 50,
            "xet_hash": "b" * 64,
        },
    ]
    # Empty plan selections: force the object to stay unmapped_linkable.
    inventory = build_bucket_audio_inventory(
        objects,
        bucket_id="Publicus/abby-voice",
        listing_sha256="d" * 64,
    )
    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": []},
        accepted_responses=(response,),
        discovered_objects=objects,
    )
    bundle = normalize_bucket_audio_entries(
        inventory=inventory, plan=plan, plan_id=plan.plan_id
    )
    orphan_path = f"runs/orphan/audio/abby-tts-{orphan_hash}.mp3"
    assert any(
        item.mapping_status is BucketAudioMappingStatus.UNMAPPED_LINKABLE
        for item in bundle.entries
    )
    rescued, stats = rescue_unmapped_by_asr(
        bundle,
        [
            AsrRescueCandidate(
                path=orphan_path,
                transcript=spoken_src,
            )
        ],
        response_texts={response_id: (spoken_src, spoken)},
        vocabulary_texts={},
    )
    assert stats["matched"] == 1
    orphan = next(item for item in rescued.entries if item.legacy_text_hash == orphan_hash)
    assert orphan.mapping_status is BucketAudioMappingStatus.ASR_RESCUED_RESPONSE
    assert orphan.response_id == response_id
