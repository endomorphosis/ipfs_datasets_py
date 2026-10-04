"""Offline tests for exact Abby source aliases and bucket-audio planning."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256

import pytest

from ipfs_datasets_py.voice.bucket_audio_plan import (
    ABBY_VOICE_BUCKET_AUDIO_PLAN_SCHEMA_VERSION,
    AbbyVoiceBucketAudioPlan,
    BucketAudioDiscoveryObject,
    BucketAudioSelection,
    SourceAliasExclusion,
    SourceAliasExclusionReason,
    SourceResponseAlias,
    plan_abby_voice_bucket_audio,
)
from ipfs_datasets_py.voice.normalize import normalize_manifest


def _legacy_hash(text: str) -> str:
    return sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:20]


def _response(identifier: str, text: str, *, route: str = "referral") -> dict:
    legacy_hash = _legacy_hash(text)
    return {
        "id": f"abby-tts-{legacy_hash}",
        "textHash": legacy_hash,
        "text": text,
        "originalTexts": [text],
        "routes": [route],
        "sourceIds": [f"document-{identifier}"],
        "license_id": "CC0-1.0",
        "consent_status": "granted",
    }


@dataclass(frozen=True)
class _ListingObject:
    path: str
    size_bytes: int
    xet_hash: str


def test_alias_preserves_legacy_hash_when_spoken_normalization_changes_identity():
    import ipfs_datasets_py.voice as voice

    assert voice.plan_abby_voice_bucket_audio is plan_abby_voice_bucket_audio
    assert voice.AbbyVoiceBucketAudioPlan is AbbyVoiceBucketAudioPlan

    source = _response("normalized", "Call 211 now for help.")
    source["originalTexts"] = ["Call **211** now for help."]
    normalized = normalize_manifest({"responses": [source]})
    response = normalized.responses[0]
    legacy_hash = source["textHash"]
    assert response.spoken_text == "Call two one one now for help."
    assert response.content_sha256 != legacy_hash
    assert not response.content_sha256.startswith(legacy_hash)

    path = (
        "runs/abby-full-preprocess-20260622T152102Z/"
        f"phase4-residual/audio/abby-tts-{legacy_hash}.mp3"
    )
    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [source]},
        accepted_responses=normalized.responses,
        discovered_objects=[
            _ListingObject(path=path, size_bytes=321, xet_hash="a" * 64)
        ],
        source_uri="hf://datasets/Publicus/211-abby-tts/source.json@commit",
        bucket_id="Publicus/abby-voice",
        listing_sha256="b" * 64,
    )

    assert len(plan.aliases) == len(plan.selections) == 1
    alias = plan.aliases[0]
    assert alias.response_id == response.response_id
    assert alias.canonical_text_sha256 == response.content_sha256
    assert alias.legacy_text_hash == legacy_hash
    assert alias.source_record == source
    assert plan.selections[0].selected.path == path
    assert plan.selections[0].selected.xet_hash == "a" * 64
    assert plan.selections[0].requires_raw_sha256_verification is True

    payload = json.loads(plan.to_json())
    assert payload["integrity_policy"] == {
        "raw_sha256_required_after_download": True,
        "xet_hash_is_raw_sha256": False,
    }
    assert payload["selections"][0]["selected"]["xet_hash"] == "a" * 64
    assert "sha256" not in payload["selections"][0]["selected"]
    assert payload["schema_version"] == ABBY_VOICE_BUCKET_AUDIO_PLAN_SCHEMA_VERSION
    assert payload["plan_id"] == plan.plan_id
    assert payload["bucket_id"] == "Publicus/abby-voice"
    assert payload["listing_sha256"] == "b" * 64
    assert payload["listing_id"].endswith("b" * 64)
    assert AbbyVoiceBucketAudioPlan.from_json(plan.to_json()) == plan
    assert SourceResponseAlias.from_json(
        json.dumps(alias.to_dict(), sort_keys=True)
    ) == alias
    assert BucketAudioSelection.from_json(
        json.dumps(plan.selections[0].to_dict(), sort_keys=True)
    ) == plan.selections[0]
    assert BucketAudioDiscoveryObject.from_json(
        json.dumps(plan.selections[0].selected.to_dict(), sort_keys=True)
    ) == plan.selections[0].selected


def test_selection_prefers_production_phase4_then_newer_run_and_is_order_independent():
    source = _response("selection", "A sufficiently useful response for selection.")
    normalized = normalize_manifest({"responses": [source]})
    filename = f"abby-tts-{source['textHash']}.mp3"
    paths = [
        f"scratch/phase4-residual/audio/{filename}",
        (
            "runs/abby-full-preprocess-20260622T152102Z/"
            f"phase3-duplicate/audio/{filename}"
        ),
        (
            "runs/abby-full-preprocess-20260614T004544Z/"
            f"phase4-residual/audio/{filename}"
        ),
        (
            "runs/abby-full-preprocess-20260622T152102Z/"
            f"phase4-residual/audio/{filename}"
        ),
    ]
    objects = [
        {"path": path, "size_bytes": index + 10, "xet_hash": f"xet-{index}"}
        for index, path in enumerate(paths)
    ]
    # Exact duplicate listing entries are harmless and are de-duplicated by path.
    objects.append(dict(objects[-1]))

    forward = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [source]},
        accepted_responses=normalized.responses,
        discovered_objects=objects,
    )
    reverse = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [source]},
        accepted_responses=reversed(normalized.responses),
        discovered_objects=reversed(objects),
    )

    selection = forward.selections[0]
    assert selection.selected.path == paths[3]
    assert [item.path for item in selection.alternatives] == [
        paths[2],
        paths[1],
        paths[0],
    ]
    assert forward.discovered_object_count == 4
    assert forward.plan_id == reverse.plan_id
    assert forward.canonical_bytes() == reverse.canonical_bytes()


def test_allowed_run_ids_exclude_unapproved_future_lookalike_objects():
    source = _response(
        "approved-run",
        "Only an explicitly approved production run may supply this response.",
    )
    normalized = normalize_manifest({"responses": [source]})
    filename = f"abby-tts-{source['textHash']}.mp3"
    approved_run = "abby-full-preprocess-20260622T152102Z"
    approved = {
        "path": f"runs/{approved_run}/phase4-residual/audio/{filename}",
        "size_bytes": 321,
        "xet_hash": "a" * 64,
    }
    unapproved_future = {
        "path": (
            "runs/abby-full-preprocess-20991231T235959Z/"
            f"phase4-residual/audio/{filename}"
        ),
        "size_bytes": 999,
        "xet_hash": "f" * 64,
    }

    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [source]},
        accepted_responses=normalized.responses,
        discovered_objects=[unapproved_future, approved],
        allowed_run_ids=[approved_run],
    )

    assert plan.allowed_run_ids == (approved_run,)
    assert plan.selections[0].selected.path == approved["path"]
    assert not plan.selections[0].alternatives
    assert plan.ignored_object_count == 1
    assert plan.summary()["allowed_run_count"] == 1
    payload = json.loads(plan.to_json())
    assert payload["selection_policy"] == {
        "allowed_run_ids": [approved_run],
        "unlisted_runs_are_eligible": False,
    }
    assert AbbyVoiceBucketAudioPlan.from_json(plan.to_json()) == plan


def test_missing_audio_is_explicit_and_inexact_names_are_ignored():
    matched = _response("matched", "This accepted response has an exact MP3.")
    missing = _response("missing", "This accepted response still needs new TTS.")
    normalized = normalize_manifest({"responses": [matched, missing]})
    matched_name = f"abby-tts-{matched['textHash']}.mp3"
    missing_hash = missing["textHash"]
    objects = [
        {
            "path": f"runs/abby-full-preprocess-20260622T152102Z/phase4/audio/{matched_name}",
            "size": 12,
            "xet_hash": "matched-xet",
        },
        {
            # Exact abby-tts basename with .wav is now response-linkable under
            # the inventory schema, so this fills the previously missing row.
            "path": f"runs/test/audio/abby-tts-{missing_hash}.wav",
            "size": 13,
            "xet_hash": "wav-is-linkable",
        },
        {
            "path": f"runs/test/audio/abby-tts-{missing_hash}-extra.mp3",
            "size": 14,
            "xet_hash": "inexact-name",
        },
        {
            "path": "spk_1779904536.wav",
            "size": 15,
            "xet_hash": "speaker-prompt-orphan",
        },
    ]

    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [matched, missing]},
        accepted_responses=normalized.responses,
        discovered_objects=objects,
    )

    assert plan.missing_response_ids == ()
    assert len(plan.selections) == 2
    # Inexact basename + speaker prompt are ignored for response selection.
    assert plan.ignored_object_count == 2
    assert plan.summary()["missing_audio_count"] == 0
    assert plan.summary()["raw_sha256_verification_required"] is True


def test_quarantined_and_other_unaccepted_source_rows_cannot_claim_bucket_audio():
    accepted = _response(
        "accepted", "This grounded accepted response should claim its exact audio."
    )
    quarantined = _response("quarantined", "a")
    unaccepted = _response(
        "unaccepted", "This valid source row is absent from the accepted allowlist."
    )
    manifest = {"responses": [accepted, quarantined, unaccepted]}
    normalized = normalize_manifest(manifest)
    accepted_only = tuple(
        row for row in normalized.responses if row.text == accepted["text"]
    )
    assert len(accepted_only) == 1
    assert normalized.quarantine

    objects = [
        BucketAudioDiscoveryObject(
            path=(
                "runs/abby-full-preprocess-20260622T152102Z/phase4-residual/audio/"
                f"abby-tts-{row['textHash']}.mp3"
            ),
            size_bytes=10,
            xet_hash=f"xet-{index}",
        )
        for index, row in enumerate((accepted, quarantined, unaccepted))
    ]
    plan = plan_abby_voice_bucket_audio(
        source_manifest=manifest,
        accepted_responses=accepted_only,
        discovered_objects=objects,
        quarantined_sources=normalized.quarantine,
    )

    assert len(plan.aliases) == len(plan.selections) == 1
    assert plan.aliases[0].legacy_text_hash == accepted["textHash"]
    assert {item.reason for item in plan.exclusions} == {
        SourceAliasExclusionReason.QUARANTINED_SOURCE,
        SourceAliasExclusionReason.UNACCEPTED_RESPONSE,
    }
    assert all(
        SourceAliasExclusion.from_json(
            json.dumps(item.to_dict(), sort_keys=True)
        )
        == item
        for item in plan.exclusions
    )
    assert quarantined["textHash"] not in {
        item.legacy_text_hash for item in plan.aliases
    }
    assert unaccepted["textHash"] not in {
        item.legacy_text_hash for item in plan.aliases
    }


def test_ambiguous_source_alias_is_fail_closed_and_conflicting_duplicate_paths_fail():
    source = _response("ambiguous", "This response has conflicting source aliases.")
    conflicting = dict(source)
    conflicting["id"] = f"{source['id']}-duplicate-source"
    conflicting["sourceIds"] = ["document-conflicting"]
    normalized = normalize_manifest({"responses": [source]})

    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [source, conflicting]},
        accepted_responses=normalized.responses,
        discovered_objects=[],
    )
    assert not plan.aliases
    assert plan.unmapped_response_ids == (normalized.responses[0].response_id,)
    assert {item.reason for item in plan.exclusions} == {
        SourceAliasExclusionReason.AMBIGUOUS_SOURCE_ALIAS
    }

    path = (
        "runs/abby-full-preprocess-20260622T152102Z/phase4-residual/audio/"
        f"abby-tts-{source['textHash']}.mp3"
    )
    with pytest.raises(ValueError, match="conflicting bucket discovery metadata"):
        plan_abby_voice_bucket_audio(
            source_manifest={"responses": [source]},
            accepted_responses=normalized.responses,
            discovered_objects=[
                {"path": path, "size_bytes": 10, "xet_hash": "one"},
                {"path": path, "size_bytes": 11, "xet_hash": "two"},
            ],
        )


def test_source_text_hash_must_match_the_historical_hash_algorithm():
    source = _response(
        "mismatched-hash",
        "This canonical response must not trust a mismatched legacy hash.",
    )
    normalized = normalize_manifest({"responses": [source]})
    tampered = dict(source)
    tampered["textHash"] = "f" * 20

    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [tampered]},
        accepted_responses=normalized.responses,
        discovered_objects=[
            {
                "path": (
                    "runs/abby-full-preprocess-20260622T152102Z/"
                    "phase4-residual/audio/abby-tts-"
                    f"{tampered['textHash']}.mp3"
                ),
                "size_bytes": 10,
                "xet_hash": "tampered-xet",
            }
        ],
    )

    assert not plan.aliases
    assert not plan.selections
    assert plan.unmapped_response_ids == (normalized.responses[0].response_id,)
    assert {item.reason for item in plan.exclusions} == {
        SourceAliasExclusionReason.LEGACY_TEXT_HASH_MISMATCH
    }


def test_plan_rejects_cross_response_selection_swaps():
    first = _response("first", "The first response has its own exact audio.")
    second = _response("second", "The second response has different exact audio.")
    normalized = normalize_manifest({"responses": [first, second]})
    discovered = [
        {
            "path": (
                "runs/abby-full-preprocess-20260622T152102Z/"
                f"phase4-residual/audio/abby-tts-{row['textHash']}.mp3"
            ),
            "size_bytes": 10 + index,
            "xet_hash": f"xet-{index}",
        }
        for index, row in enumerate((first, second))
    ]
    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": [first, second]},
        accepted_responses=normalized.responses,
        discovered_objects=discovered,
    )
    first_selection, second_selection = plan.selections
    swapped = (
        replace(first_selection, response_id=second_selection.response_id),
        replace(second_selection, response_id=first_selection.response_id),
    )

    with pytest.raises(ValueError, match="does not match its response alias"):
        replace(plan, selections=swapped, plan_id="")
