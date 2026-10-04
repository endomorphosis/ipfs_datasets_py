from __future__ import annotations

from hashlib import sha256

import pytest

from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher
from ipfs_datasets_py.voice.response_dag import (
    AbbyVoiceResponseDAGError,
    append_response_dag_candidate,
)


def _event(response_text: str, audio: bytes) -> dict[str, object]:
    return {
        "event_id": "abby-voice-cache-miss:sha256:" + "a" * 64,
        "intent": "resource_phone",
        "output_audio_sha256": sha256(audio).hexdigest(),
        "ready_for_dag_append": True,
        "rendered_text_sha256": sha256(response_text.encode()).hexdigest(),
        "response_id": "response-phone",
        "template_id": "template-phone",
        "validation_receipt_id": "asr-validation-1",
    }


def _audio(audio: bytes) -> dict[str, object]:
    return {
        "audio_id": "audio-phone",
        "byte_length": len(audio),
        "content_sha256": sha256(audio).hexdigest(),
        "media_type": "audio/wav",
        "uri": "hf://datasets/Publicus/211-abby-tts/audio/audio-phone.wav",
    }


def test_validated_miss_adds_template_vocabulary_response_and_audio() -> None:
    response = "Call five zero three, five five five, zero one zero zero."
    audio = b"RIFF-validated-cache-miss-WAVE"

    candidate = append_response_dag_candidate(
        _event(response, audio),
        response_text=response,
        audio_descriptor=_audio(audio),
        template_text="Call {phone_number}.",
        slot_bindings={
            "phone_number": {
                "value": "five zero three, five five five, zero one zero zero",
                "source_cids": ["bafy-phone-source"],
            }
        },
    )
    again = append_response_dag_candidate(
        _event(response, audio),
        response_text=response,
        audio_descriptor=_audio(audio),
        template_text="Call {phone_number}.",
        slot_bindings={
            "phone_number": {
                "value": "five zero three, five five five, zero one zero zero",
                "source_cids": ["bafy-phone-source"],
            }
        },
    )

    assert candidate.candidate_id == again.candidate_id
    assert {node["kind"] for node in candidate.nodes} == {
        "audio",
        "response",
        "template",
        "vocabulary",
    }
    assert {edge["kind"] for edge in candidate.edges} == {
        "response_to_audio",
        "template_to_response",
        "template_to_vocabulary",
        "vocabulary_to_response",
    }


def test_append_fails_closed_before_asr_validation_or_on_audio_mismatch() -> None:
    response = "Safe response."
    audio = b"RIFF-safe-WAVE"
    event = _event(response, audio)
    event["ready_for_dag_append"] = False

    with pytest.raises(AbbyVoiceResponseDAGError, match="ASR validation"):
        append_response_dag_candidate(
            event,
            response_text=response,
            audio_descriptor=_audio(audio),
        )

    event["ready_for_dag_append"] = True
    bad_audio = _audio(b"RIFF-different-WAVE")
    with pytest.raises(AbbyVoiceResponseDAGError, match="does not match"):
        append_response_dag_candidate(
            event,
            response_text=response,
            audio_descriptor=bad_audio,
        )


def test_candidate_materializes_as_append_only_hf_dry_run(tmp_path) -> None:
    response = "A reusable response."
    audio = b"RIFF-reusable-WAVE"
    event = _event(response, audio)
    event["template_id"] = ""
    candidate = append_response_dag_candidate(
        event,
        response_text=response,
        audio_descriptor=_audio(audio),
    )

    release_root = tmp_path / "release"
    manifest = candidate.materialize(release_root)
    publisher = HuggingFaceReleasePublisher(
        repository_id="Publicus/211-abby-tts"
    )
    plan = publisher.plan_dry_run(manifest, local_root=release_root)

    assert plan.dry_run is True
    assert plan.remote_write_contacted is False
    assert all(operation.operation == "add" for operation in plan.operations)
    assert len(plan.operations) == len(candidate.file_payloads())
    assert plan.cost_receipt["upload_bytes"] > 0
