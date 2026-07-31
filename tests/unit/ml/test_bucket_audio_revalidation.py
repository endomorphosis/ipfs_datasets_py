"""Verified bucket audio -> accelerator revalidation workset tests."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

import pytest

from ipfs_accelerate_py.voice_jobs.contracts import VoiceJobResult
from ipfs_accelerate_py.voice_jobs.executor import (
    ArtifactPolicy,
    ArtifactResolver,
    execute_voice_asr_job,
    execute_voice_audio_validation_job,
)
from ipfs_datasets_py.ml.accelerate_integration.bucket_audio import (
    CriticalFactClassification,
    build_bucket_audio_revalidation_plan,
    classify_legacy_critical_facts,
)
from ipfs_datasets_py.ml.accelerate_integration.bucket_audio_admission import (
    admit_bucket_audio_revalidation,
)
from ipfs_datasets_py.ml.accelerate_integration.voice_jobs import (
    VoiceWorksetBridgeConfig,
    jobs_from_voice_workset,
)
from ipfs_datasets_py.voice.audio_quality import (
    build_minimal_wav,
    derive_legacy_critical_slots,
    find_unclassified_legacy_critical_facts,
)
from ipfs_datasets_py.voice.bucket_audio_recovery import (
    AbbyVoiceBucketAudioRecovery,
    BucketAudioRecoveryError,
    DecodeProbeEvidence,
    VerifiedBucketAudioRecord,
    bucket_audio_cache_path,
)
from ipfs_datasets_py.voice.schema import sha256_text


def _record(*, response_id: str, spoken_text: str, payload: bytes, digit: str):
    digest = sha256(payload).hexdigest()
    return VerifiedBucketAudioRecord(
        plan_id="bucket-plan:test",
        listing_sha256="a" * 64,
        bucket_id="Publicus/abby-voice",
        response_id=response_id,
        canonical_text_sha256=sha256_text(spoken_text),
        spoken_text=spoken_text,
        locale="en-US",
        legacy_text_hash=digit * 20,
        source_ref=f"source:{response_id}",
        source_record_sha256=digit * 64,
        bucket_path=f"runs/approved/audio/abby-tts-{digit * 20}.wav",
        xet_hash=chr(ord(digit) + 1) * 64,
        listed_size_bytes=len(payload),
        verified_size_bytes=len(payload),
        raw_sha256=digest,
        media_type="audio/wav",
        decode_probe=DecodeProbeEvidence(
            probe_name="ffmpeg",
            probe_version="fixture-1",
            passed=True,
            details={"full_frame_decode": True},
        ),
    )


def _fixture(tmp_path):
    first_payload = build_minimal_wav(amplitude=7_000)
    second_payload = build_minimal_wav(amplitude=8_000)
    first = _record(
        response_id="response-critical",
        spoken_text=(
            "Call five zero three five five five one two one two. "
            "Go to 123 Main Street. Call nine one one in an emergency."
        ),
        payload=first_payload,
        digit="1",
    )
    second = _record(
        response_id="response-general",
        spoken_text="You are doing your best, and I can stay with you.",
        payload=second_payload,
        digit="3",
    )
    recovery = AbbyVoiceBucketAudioRecovery(
        plan_id=first.plan_id,
        listing_sha256=first.listing_sha256,
        bucket_id=first.bucket_id,
        planned_selection_count=2,
        target_response_ids=(first.response_id, second.response_id),
        records=(first, second),
        failures=(),
    )
    cache_root = tmp_path / "recovery-cache"
    for record, payload in ((first, first_payload), (second, second_payload)):
        target = bucket_audio_cache_path(cache_root, record.xet_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return recovery, cache_root, first, second


@pytest.mark.parametrize(
    ("spoken_text", "expected_binding"),
    (
        (
            "Call 5 … 0 … 3 … 2 … 2 … 2 … 5 … 5 … 5 … 5.",
            ("phone", "5032225555"),
        ),
        (
            "Call `5 4 1` … `2 2 1` … `0 8 2 4`.",
            ("phone", "5412210824"),
        ),
        (
            "Call 5...0...3...8...4...6...3...0...9...4.",
            ("phone", "5038463094"),
        ),
        (
            "Bring your photo ID and Medicaid card.",
            ("eligibility", "Bring your photo ID and Medicaid card."),
        ),
        (
            "The balance is about four hundred dollars.",
            ("amount", "four hundred dollars"),
        ),
        (
            "Call two one one for a local resource navigator.",
            ("phone", "211"),
        ),
        (
            "Call five four one, four eight five, one zero one seven, "
            "extension one zero zero.",
            ("phone_extension", "100"),
        ),
    ),
)
def test_legacy_critical_extractor_covers_cluttered_source_forms(
    spoken_text,
    expected_binding,
):
    bindings = derive_legacy_critical_slots(spoken_text)

    assert expected_binding in bindings
    assert find_unclassified_legacy_critical_facts(spoken_text, bindings) == ()
    assert (
        classify_legacy_critical_facts(spoken_text)
        is CriticalFactClassification.BOUND
    )


def test_likely_critical_but_unsupported_identifier_fails_closed(tmp_path):
    payload = build_minimal_wav(amplitude=7_000)
    record = _record(
        response_id="response-unclassified-extension",
        spoken_text="Use confirmation number one two three four.",
        payload=payload,
        digit="5",
    )
    recovery = AbbyVoiceBucketAudioRecovery(
        plan_id=record.plan_id,
        listing_sha256=record.listing_sha256,
        bucket_id=record.bucket_id,
        planned_selection_count=1,
        target_response_ids=(record.response_id,),
        records=(record,),
        failures=(),
    )
    cache_root = tmp_path / "recovery-cache"
    target = bucket_audio_cache_path(cache_root, record.xet_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    artifact_root = tmp_path / "accelerator-artifacts"

    assert (
        classify_legacy_critical_facts(record.spoken_text)
        is CriticalFactClassification.UNCLASSIFIED
    )
    assert find_unclassified_legacy_critical_facts(record.spoken_text) == (
        "contextual_identifier_unclassified",
    )
    with pytest.raises(
        BucketAudioRecoveryError,
        match="likely_critical_facts_unclassified",
    ):
        build_bucket_audio_revalidation_plan(
            recovery,
            cache_dir=cache_root,
            artifact_root=artifact_root,
        )
    assert not artifact_root.exists()


def test_explicit_unknown_amount_does_not_invent_a_critical_value():
    spoken_text = (
        "You don't need the exact dollar amount to start. "
        "The benefit amount is unknown right now."
    )

    bindings = derive_legacy_critical_slots(spoken_text)

    assert bindings == ()
    assert find_unclassified_legacy_critical_facts(spoken_text, bindings) == ()
    assert (
        classify_legacy_critical_facts(spoken_text)
        is CriticalFactClassification.NONE_DETECTED
    )


def test_pinned_source_likely_critical_patterns_never_silently_fall_through():
    source_path = (
        Path(__file__).resolve().parents[4]
        / "docs"
        / "pregenerated_text_response_manifest.json"
    )
    if not source_path.is_file():
        pytest.skip("integrated pinned Abby response manifest is unavailable")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    rows = payload["responses"]

    digit_token = (
        r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|\d)"
    )
    digit_tokens = re.compile(
        rf"(?<![A-Za-z]){digit_token}(?![A-Za-z])",
        re.IGNORECASE,
    )
    phone_context = re.compile(
        r"\b(?:call|dial|line|number|phone|text)\b",
        re.IGNORECASE,
    )
    eligibility_pattern = re.compile(
        r"\b(?:bring|show|provide|present|take)\b[^.!?\n]{0,96}\b"
        r"(?:id|identification|card|documents?|paperwork|proof|lease|bill|"
        r"mail|letter|forms?|records?|verification)\b|"
        r"\b(?:id|identification|card|documents?|paperwork|proof|lease|bill|"
        r"mail|letter|forms?|records?|verification)\b[^.!?\n]{0,64}\b"
        r"(?:required|needed|acceptable|to\s+(?:bring|show|provide|present))\b",
        re.IGNORECASE,
    )
    number_word = (
        r"(?:a|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
        r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
        r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
        r"hundred|thousand|million)"
    )
    word_amount_pattern = re.compile(
        rf"\b{number_word}(?:[\s-]+(?:and[\s-]+)?{number_word})*"
        rf"\s+dollars?\b",
        re.IGNORECASE,
    )

    matched_counts = {"punctuated_digits": 0, "eligibility": 0, "amount": 0}
    failures: list[tuple[str, str]] = []
    unclassified_failures: list[tuple[str, tuple[str, ...]]] = []
    for row in rows:
        response_id = row["id"]
        text = row["text"]
        bindings = derive_legacy_critical_slots(text)
        markers = find_unclassified_legacy_critical_facts(text, bindings)
        if markers:
            unclassified_failures.append((response_id, markers))
        requested_categories: set[str] = set()
        for sentence_match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", text):
            sentence = sentence_match.group(0)
            if (
                ("…" in sentence or "`" in sentence)
                and phone_context.search(sentence)
                and len(digit_tokens.findall(sentence)) >= 7
            ):
                requested_categories.add("punctuated_digits")
                break
        if eligibility_pattern.search(text):
            requested_categories.add("eligibility")
        if word_amount_pattern.search(text):
            requested_categories.add("amount")
        if not requested_categories:
            continue

        slot_names = {name for name, _value in bindings}
        for category in requested_categories:
            matched_counts[category] += 1
            if category == "punctuated_digits":
                if not ({"phone", "emergency"} & slot_names):
                    failures.append((response_id, category))
            elif category not in slot_names:
                failures.append((response_id, category))

    assert matched_counts["punctuated_digits"] > 0
    assert matched_counts["eligibility"] > 0
    assert matched_counts["amount"] > 0
    assert failures == []
    assert unclassified_failures == []


def test_verified_recovery_builds_asr_validation_only_content_addressed_work(tmp_path):
    recovery, cache_root, first, second = _fixture(tmp_path)
    artifact_root = tmp_path / "accelerator-artifacts"

    plan = build_bucket_audio_revalidation_plan(
        recovery,
        cache_dir=cache_root,
        artifact_root=artifact_root,
    )
    repeated = build_bucket_audio_revalidation_plan(
        recovery,
        cache_dir=cache_root,
        artifact_root=artifact_root,
    )

    assert plan.revalidation_plan_id == repeated.revalidation_plan_id
    assert plan.workset.tts_manifest.items == ()
    assert len(plan.workset.asr_manifest.items) == 2
    assert len(plan.workset.validation_manifest.items) == 2
    assert plan.workset.source_manifest_id == recovery.recovery_id
    assert plan.workset.policy_id == plan.policy.identity
    assert plan.policy.required_sample_rate_hz is None
    assert plan.policy.required_channels == 1

    by_response = {item.response_id: item for item in plan.bindings}
    critical = by_response[first.response_id]
    assert critical.raw_sha256 == first.raw_sha256
    assert critical.critical_fact_classification is CriticalFactClassification.BOUND
    assert set(critical.slot_names) >= {"address", "emergency", "phone"}
    assert by_response[second.response_id].critical_fact_classification is (
        CriticalFactClassification.NONE_DETECTED
    )

    jobs = jobs_from_voice_workset(plan.workset)
    assert [job.task_type for job in jobs].count("voice.asr") == 2
    assert [job.task_type for job in jobs].count("voice.audio-validate") == 2
    assert VoiceWorksetBridgeConfig().asr_provider == "huggingface"
    assert VoiceWorksetBridgeConfig().asr_retention_policy == "result"
    serialized = json.dumps([job.to_payload() for job in jobs], sort_keys=True)
    assert "file://" not in serialized
    assert "audio_bytes" not in serialized
    assert "xet_hash" not in serialized
    assert first.raw_sha256 in serialized
    assert all(item.artifact_uri.startswith("ipfs://") for item in plan.bindings)
    assert len(list(artifact_root.rglob("*.wav"))) == 2


def test_revalidation_rehashes_cache_and_rejects_tampering(tmp_path):
    recovery, cache_root, first, _second = _fixture(tmp_path)
    path = bucket_audio_cache_path(cache_root, first.xet_hash)
    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(BucketAudioRecoveryError, match="size changed"):
        build_bucket_audio_revalidation_plan(
            recovery,
            cache_dir=cache_root,
            artifact_root=tmp_path / "accelerator-artifacts",
        )


def test_completed_asr_and_validation_receipts_admit_only_exactly_bound_audio(
    tmp_path,
):
    recovery, cache_root, _first, _second = _fixture(tmp_path)
    artifact_root = tmp_path / "accelerator-artifacts"
    plan = build_bucket_audio_revalidation_plan(
        recovery,
        cache_dir=cache_root,
        artifact_root=artifact_root,
    )
    jobs = jobs_from_voice_workset(plan.workset)
    resolver = ArtifactResolver(
        ArtifactPolicy(
            output_root=artifact_root,
            max_duration_ms=plan.policy.max_duration_ms,
        )
    )
    spoken_by_sha = {
        record.raw_sha256: record.spoken_text for record in recovery.records
    }
    results: dict[str, VoiceJobResult] = {}
    transcript_bytes: dict[str, bytes] = {}
    for job in jobs:
        if job.task_type == "voice.asr":
            assert job.source_audio is not None
            payload = execute_voice_asr_job(
                job,
                resolver=resolver,
                speech_to_text_fn=lambda _data, *, _sha=job.source_audio.sha256, **_kwargs: (
                    spoken_by_sha[_sha]
                ),
            )
            receipt = VoiceJobResult.from_payload(payload)
            results[job.task_id] = receipt
            transcript_bytes[job.task_id] = resolver.resolve(
                receipt.artifacts[0].to_dict()
            )
        elif job.task_type == "voice.audio-validate":
            results[job.task_id] = VoiceJobResult.from_payload(
                execute_voice_audio_validation_job(job, resolver=resolver)
            )
    audio_bytes = {
        record.raw_sha256: bucket_audio_cache_path(
            cache_root, record.xet_hash
        ).read_bytes()
        for record in recovery.records
    }

    admitted = admit_bucket_audio_revalidation(
        recovery,
        plan,
        jobs=jobs,
        results_by_task_id=results,
        transcript_bytes_by_asr_task_id=transcript_bytes,
        audio_bytes_by_sha256=audio_bytes,
    )

    assert admitted.promoted_count == 2
    assert admitted.quarantined_count == 0
    assert {row.response_id for row in admitted.linked_audio} == set(
        recovery.target_response_ids
    )
    persisted_quality = json.dumps(admitted.quality_report, sort_keys=True)
    assert "hypothesis_text" not in persisted_quality
    assert "reference_text" not in persisted_quality

    asr_task_id = next(iter(transcript_bytes))
    tampered = {
        **transcript_bytes,
        asr_task_id: transcript_bytes[asr_task_id] + b"tampered",
    }
    with pytest.raises(BucketAudioRecoveryError, match="do not match"):
        admit_bucket_audio_revalidation(
            recovery,
            plan,
            jobs=jobs,
            results_by_task_id=results,
            transcript_bytes_by_asr_task_id=tampered,
            audio_bytes_by_sha256=audio_bytes,
        )


def test_admit_quarantines_missing_receipts_without_aborting_siblings(tmp_path):
    recovery, cache_root, first, second = _fixture(tmp_path)
    artifact_root = tmp_path / "accelerator-artifacts"
    plan = build_bucket_audio_revalidation_plan(
        recovery,
        cache_dir=cache_root,
        artifact_root=artifact_root,
    )
    jobs = jobs_from_voice_workset(plan.workset)
    resolver = ArtifactResolver(
        ArtifactPolicy(
            output_root=artifact_root,
            max_duration_ms=plan.policy.max_duration_ms,
        )
    )
    spoken_by_sha = {
        record.raw_sha256: record.spoken_text for record in recovery.records
    }
    results: dict[str, VoiceJobResult] = {}
    transcript_bytes: dict[str, bytes] = {}
    first_work_ids = {
        binding.asr_work_id
        for binding in plan.bindings
        if binding.response_id == first.response_id
    } | {
        binding.validation_work_id
        for binding in plan.bindings
        if binding.response_id == first.response_id
    }
    for job in jobs:
        # Only complete jobs for the first response; leave second missing.
        if job.lineage.work_item_id not in first_work_ids:
            continue
        if job.task_type == "voice.asr":
            assert job.source_audio is not None
            payload = execute_voice_asr_job(
                job,
                resolver=resolver,
                speech_to_text_fn=lambda _data, *, _sha=job.source_audio.sha256, **_kwargs: (
                    spoken_by_sha[_sha]
                ),
            )
            receipt = VoiceJobResult.from_payload(payload)
            results[job.task_id] = receipt
            transcript_bytes[job.task_id] = resolver.resolve(
                receipt.artifacts[0].to_dict()
            )
        elif job.task_type == "voice.audio-validate":
            results[job.task_id] = VoiceJobResult.from_payload(
                execute_voice_audio_validation_job(job, resolver=resolver)
            )
    audio_bytes = {
        record.raw_sha256: bucket_audio_cache_path(
            cache_root, record.xet_hash
        ).read_bytes()
        for record in recovery.records
    }

    admitted = admit_bucket_audio_revalidation(
        recovery,
        plan,
        jobs=jobs,
        results_by_task_id=results,
        transcript_bytes_by_asr_task_id=transcript_bytes,
        audio_bytes_by_sha256=audio_bytes,
    )

    assert admitted.promoted_count == 1
    assert {row.response_id for row in admitted.linked_audio} == {first.response_id}
    second_dispositions = [
        item
        for item in admitted.dispositions
        if item.subject_id == second.response_id
    ]
    assert second_dispositions
    assert all(item.retryable for item in second_dispositions)
    assert any(
        item.reason.value == "job_not_completed" for item in second_dispositions
    )


def test_revalidation_plan_round_trips_through_from_dict(tmp_path):
    recovery, cache_root, _first, _second = _fixture(tmp_path)
    plan = build_bucket_audio_revalidation_plan(
        recovery,
        cache_dir=cache_root,
        artifact_root=tmp_path / "accelerator-artifacts",
    )
    restored = type(plan).from_dict(plan.to_dict())
    assert restored.revalidation_plan_id == plan.revalidation_plan_id
    assert restored.recovery_id == plan.recovery_id
    assert restored.workset.workset_id == plan.workset.workset_id
    assert [item.to_dict() for item in restored.bindings] == [
        item.to_dict() for item in plan.bindings
    ]
