"""Offline acceptance tests for Abby voice dataset normalization."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from ipfs_datasets_py.voice.normalize import (
    AbbyVoiceDatasetNormalizer,
    NormalizationConfig,
    QuarantineReason,
    build_slotted_response_dag,
    deduplicate_voice_response_chunks,
    deterministic_split,
    normalize_indextts_spoken_text,
    normalize_manifest,
)
from ipfs_datasets_py.voice.schema import (
    AbbyVoiceResponse,
    validate_bundle,
)


def _codes(result):
    return {
        code
        for item in result.quarantine
        for code in item.reason_codes
    }


def _response(identifier: str, text: str, **values):
    return {
        "id": identifier,
        "text": text,
        "sourceIds": [f"public-doc-{identifier}"],
        **values,
    }


def test_spoken_text_normalization_is_deterministic_and_tts_safe():
    raw = " **Call** <b>211</b> or [(503) 555-0100](https://example.org). "

    first = normalize_indextts_spoken_text(raw)
    second = normalize_indextts_spoken_text(first)

    assert first == (
        "Call two one one or five zero three, five five five, zero one zero zero."
    )
    assert second == first
    assert "http" not in first
    assert "<" not in first


def test_normalization_does_not_mutate_input_and_is_order_independent():
    records = [
        _response("z", "I can help you today.", routes=["help"]),
        _response(
            "a",
            " I   can help you today. ",
            serviceTags=["navigation"],
        ),
    ]
    snapshot = copy.deepcopy(records)

    forward = normalize_manifest(
        {"responses": records}, source_uri="fixture://responses"
    )
    reverse = normalize_manifest(
        {"responses": list(reversed(records))}, source_uri="fixture://responses"
    )

    assert records == snapshot
    assert forward.to_dict() == reverse.to_dict()
    assert len(forward.responses) == 1
    assert forward.duplicates[0].kind == "text"
    assert forward.duplicates[0].duplicate_source_refs
    assert "duplicate_text" in _codes(forward)
    assert forward.responses[0].route_labels == ("help",)
    assert forward.responses[0].service_tags == ("navigation",)


def test_stable_source_references_do_not_use_array_positions():
    values = [_response("row/a", "This is the first response.")]
    result = normalize_manifest(values, source_uri="fixture://one")

    assert result.provenance[0].source_uri == "fixture://one#responses/row%2Fa"
    assert result.warnings[0].source_ref == "fixture://one#responses/row%2Fa"


def test_empty_malformed_and_low_value_vocabulary_are_quarantined_losslessly():
    source = {
        "responses": [
            {"id": "empty", "text": ""},
            _response("broken", "Tap “ ” to continue."),
            {
                "id": "fragment",
                "text": "a",
                "sourceTypes": ["graphrag.bm25_term"],
            },
        ]
    }

    result = normalize_manifest(source, source_uri="fixture://quality")

    assert not result.responses
    assert {
        "empty_text",
        "malformed_spoken_text",
        "low_value_fragment",
    } <= _codes(result)
    assert len(result.quarantine) == 3
    for item in result.quarantine:
        assert item.source_ref.startswith("fixture://quality#responses/")
        assert len(item.source_sha256) == 64
        assert item.source_record == next(
            row for row in source["responses"] if row["id"] in item.source_ref
        )
        assert item.reason_codes == tuple(sorted(item.reason_codes))


def test_source_aware_vocabulary_gate_preserves_compositional_slot_values():
    result = normalize_manifest(
        {
            "responses": [
                {
                    "id": "portland",
                    "text": "Portland",
                    "sourceTypes": [
                        "graphrag.bm25_term",
                        "audio_plan.slot_value",
                    ],
                    "sourceIds": ["public-city-list"],
                }
            ]
        }
    )

    assert [row.spoken_text for row in result.responses] == ["Portland"]
    assert "low_value_fragment" not in _codes(result)


def test_ungrounded_factual_claim_is_rejected_but_grounded_claim_passes():
    ungrounded = normalize_manifest(
        {"responses": [{"id": "bad", "text": "Call 503-555-0100 today."}]}
    )
    grounded = normalize_manifest(
        {
            "responses": [
                _response("good", "Call 503-555-0100 today.")
            ]
        }
    )

    assert "ungrounded_claim" in _codes(ungrounded)
    assert len(grounded.responses) == 1


def test_slot_fidelity_requires_aligned_grounded_values():
    bad = normalize_manifest(
        {
            "responses": [
                _response(
                    "bad-slots",
                    "Call 503-555-0100.",
                    slotNames=["phone"],
                    slotValues=["503-555-0100"],
                    slotSourceCids=[],
                )
            ]
        }
    )
    good = normalize_manifest(
        {
            "responses": [
                _response(
                    "good-slots",
                    "Call 503-555-0100.",
                    slotNames=["phone"],
                    slotValues=["503-555-0100"],
                    slotSourceCids=["bafy-public-contact"],
                )
            ]
        }
    )

    assert "inconsistent_slots" in _codes(bad)
    assert good.responses[0].slot_names == ("phone",)
    assert good.responses[0].slot_values == ("503-555-0100",)
    assert good.responses[0].slot_source_cids == ("bafy-public-contact",)


def test_template_placeholder_fidelity_is_a_quality_gate():
    result = normalize_manifest(
        {
            "templates": [
                {
                    "id": "bad-template",
                    "text": "Call {phone}.",
                    "slotNames": ["address"],
                    "intent": "referral",
                }
            ]
        }
    )

    assert not result.templates
    assert "inconsistent_slots" in _codes(result)


def test_missing_audio_can_warn_or_quarantine_by_policy():
    manifest = {"responses": [_response("no-audio", "I can help.")]}

    permissive = normalize_manifest(manifest)
    strict = normalize_manifest(
        manifest, config=NormalizationConfig(require_audio=True)
    )

    assert len(permissive.responses) == 1
    assert permissive.warnings[0].reason_codes == ("missing_audio",)
    assert not strict.responses
    assert "missing_audio" in _codes(strict)


def test_audio_is_hashed_from_bytes_and_declared_hash_mismatch_is_rejected(
    tmp_path,
):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"synthetic public fixture audio")
    expected = sha256(audio.read_bytes()).hexdigest()
    record = _response(
        "audio",
        "This response has audio.",
        preferredAudioPath=audio.name,
        preferredMimeType="audio/mpeg",
        audioSha256="f" * 64,
    )

    bad = normalize_manifest(
        {"responses": [record]},
        source_uri="fixture://audio",
        audio_root=tmp_path,
        config=NormalizationConfig(require_audio=True),
    )
    record["audioSha256"] = expected
    good = normalize_manifest(
        {"responses": [record]},
        source_uri="fixture://audio",
        audio_root=tmp_path,
        config=NormalizationConfig(require_audio=True),
    )

    assert "audio_hash_mismatch" in _codes(bad)
    assert len(good.responses) == len(good.audio) == 1
    assert good.audio[0].content_sha256 == expected
    assert good.responses[0].audio_ids == (good.audio[0].audio_id,)
    validate_bundle(
        responses=good.responses,
        audio=good.audio,
        provenance=good.provenance,
    )


def test_audio_byte_deduplication_has_deterministic_ledger(tmp_path):
    audio = tmp_path / "same.mp3"
    audio.write_bytes(b"same synthetic bytes")
    digest = sha256(audio.read_bytes()).hexdigest()
    manifest = {
        "responses": [
            _response(
                "one",
                "The first spoken response.",
                preferredAudioPath=audio.name,
                audioSha256=digest,
            ),
            _response(
                "two",
                "The second spoken response.",
                preferredAudioPath=audio.name,
                audioSha256=digest,
            ),
        ]
    }

    result = normalize_manifest(
        manifest,
        source_uri="fixture://audio-dedupe",
        audio_root=tmp_path,
    )

    assert len(result.audio) == 1
    assert any(item.kind == "audio" for item in result.duplicates)
    assert "duplicate_audio" in _codes(result)
    assert result.quality_summary()["deduplication"]["audio_duplicates_removed"] == 1


def test_split_assignment_is_stable_and_related_rows_are_colocated(tmp_path):
    audio = tmp_path / "response.mp3"
    audio.write_bytes(b"split fixture")
    digest = sha256(audio.read_bytes()).hexdigest()
    result = normalize_manifest(
        {
            "responses": [
                _response(
                    "split",
                    "This response is colocated.",
                    preferredAudioPath=audio.name,
                    audioSha256=digest,
                )
            ]
        },
        source_uri="fixture://split",
        audio_root=tmp_path,
    )
    response = result.responses[0]
    asset = result.audio[0]

    assert deterministic_split(response.content_sha256) == deterministic_split(
        response.content_sha256
    )
    assert result.splits[response.response_id] == result.splits[asset.audio_id]
    assert all(
        result.splits[row.provenance_id] == result.splits[row.subject_id]
        for row in result.provenance
    )


def test_chunk_dedupe_and_slotted_dag_are_sorted_and_deterministic():
    rows = [
        AbbyVoiceResponse(
            response_id="response-b",
            text="I can help. Call two one one.",
            spoken_text="I can help. Call two one one.",
            intent="help",
        ),
        AbbyVoiceResponse(
            response_id="response-a",
            text="I can help.",
            spoken_text="I can help.",
            intent="help",
        ),
    ]

    report = deduplicate_voice_response_chunks(reversed(rows))
    dag = build_slotted_response_dag(reversed(rows))

    assert report["source_chunk_count"] == 3
    assert report["unique_chunk_count"] == 2
    assert report["duplicate_chunk_count"] == 1
    assert report["chunks"][0]["reuse_count"] == 2
    assert dag["nodes"] == sorted(dag["nodes"], key=lambda item: item["id"])
    assert dag["edges"] == sorted(dag["edges"], key=lambda item: item["id"])


def test_unknown_wrapper_and_non_mapping_rows_are_quarantined():
    wrapper = normalize_manifest({"summary": {"count": 1}})
    rows = normalize_manifest([42, _response("valid", "A valid response.")])

    assert "unsupported_wrapper" in _codes(wrapper)
    assert "invalid_record" in _codes(rows)
    assert len(rows.responses) == 1


def test_quality_summary_counts_are_sorted_and_reconciled():
    result = normalize_manifest(
        {
            "responses": [
                _response("valid", "This response is valid."),
                {"id": "bad", "text": ""},
            ]
        }
    )
    summary = result.quality_summary()

    assert summary["input_record_count"] == 2
    assert summary["accepted"]["responses"] == 1
    assert summary["quarantined_source_count"] == 1
    assert list(summary["reason_counts"]) == sorted(summary["reason_counts"])
    assert summary["reconciliation"]["quarantine_is_non_destructive"] is True


def test_builder_writes_byte_identical_outputs_and_preserves_source(
    tmp_path, capsys
):
    source = tmp_path / "input.json"
    source.write_text(
        json.dumps(
            {
                "responses": [
                    _response("builder", "This is a deterministic build.")
                ]
            },
            indent=4,
        )
        + "\n",
        encoding="utf-8",
    )
    original = source.read_bytes()
    first = tmp_path / "first"
    second = tmp_path / "second"

    repo_root = Path(__file__).resolve().parents[4]
    builder = repo_root / "scripts" / "build_abby_voice_dataset_v2.py"
    first_run = subprocess.run(
        [
            sys.executable,
            str(builder),
            str(source),
            "--output-dir",
            str(first),
            "--check",
            "--check-idempotence",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    second_run = subprocess.run(
        [
            sys.executable,
            str(builder),
            str(source),
            "--output-dir",
            str(second),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert first_run.returncode == 0, first_run.stderr
    assert second_run.returncode == 0, second_run.stderr

    assert source.read_bytes() == original
    first_files = {
        item.name: item.read_bytes() for item in first.iterdir() if item.is_file()
    }
    second_files = {
        item.name: item.read_bytes() for item in second.iterdir() if item.is_file()
    }
    assert first_files == second_files
    quality = json.loads(first_files["quality-report.json"])
    assert quality["accepted"]["responses"] == 1
    assert quality["reason_counts"]["missing_audio"] == 1
