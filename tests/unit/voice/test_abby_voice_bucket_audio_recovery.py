"""Offline tests for resumable, byte-verified Abby bucket audio recovery."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.bucket import HuggingFaceBucketStore
from ipfs_datasets_py.voice.bucket_audio_plan import plan_abby_voice_bucket_audio
from ipfs_datasets_py.voice.bucket_audio_recovery import (
    AbbyVoiceBucketAudioRecovery,
    BucketAudioFailureStage,
    BucketAudioRecoveryError,
    BucketAudioRecoveryFailure,
    DecodeProbeEvidence,
    PendingBucketAudioCandidate,
    VerifiedBucketAudioRecord,
    bucket_audio_cache_path,
    parse_verified_bucket_audio_jsonl,
    read_verified_bucket_audio_jsonl,
    recover_abby_voice_bucket_audio,
    verified_bucket_audio_jsonl_bytes,
)
from ipfs_datasets_py.voice.legacy_sources import LegacyAudioCandidate
from ipfs_datasets_py.voice.normalize import normalize_manifest


def _legacy_hash(text: str) -> str:
    return sha256(" ".join(text.split()).encode()).hexdigest()[:20]


def _source(identifier: str, text: str) -> dict:
    digest = _legacy_hash(text)
    return {
        "id": f"abby-tts-{digest}",
        "textHash": digest,
        "text": text,
        "originalTexts": [text],
        "routes": ["referral"],
        "sourceIds": [f"document-{identifier}"],
        "license_id": "CC0-1.0",
        "consent_status": "granted",
    }


def _mp3(seed: bytes) -> bytes:
    return b"ID3\x04\x00\x00\x00\x00\x00\x04" + seed * 8


class _DownloadClient:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str, str, int]] = []

    def download_bucket_file(
        self,
        *,
        bucket_id: str,
        path: str,
        destination: Path,
        expected_xet_hash: str,
        expected_size_bytes: int,
    ) -> int:
        payload = self.payloads[path]
        self.calls.append(
            (bucket_id, path, expected_xet_hash, expected_size_bytes)
        )
        assert len(payload) == expected_size_bytes
        return destination.write_bytes(payload)


class _FailSelectedDownloadClient(_DownloadClient):
    def __init__(self, payloads: dict[str, bytes], selected_path: str) -> None:
        super().__init__(payloads)
        self.selected_path = selected_path

    def download_bucket_file(
        self,
        *,
        bucket_id: str,
        path: str,
        destination: Path,
        expected_xet_hash: str,
        expected_size_bytes: int,
    ) -> int:
        if path == self.selected_path:
            self.calls.append(
                (bucket_id, path, expected_xet_hash, expected_size_bytes)
            )
            raise FileNotFoundError(path)
        return super().download_bucket_file(
            bucket_id=bucket_id,
            path=path,
            destination=destination,
            expected_xet_hash=expected_xet_hash,
            expected_size_bytes=expected_size_bytes,
        )


class _OSErrorStore(HuggingFaceBucketStore):
    def __init__(self, bucket_id: str, *, client, failing_path: str) -> None:
        super().__init__(bucket_id, client=client)
        self.failing_path = failing_path

    def fetch_discovered(self, item, destination):
        if item.path == self.failing_path:
            raise OSError("temporary local I/O failure")
        return super().fetch_discovered(item, destination)


def _fixture():
    sources = [
        _source(
            "one",
            "Call 211 now for a complete referral to the nearest available service.",
        ),
        _source(
            "two",
            "This is another complete response with enough words for dataset acceptance.",
        ),
    ]
    normalized = normalize_manifest({"responses": sources})
    assert len(normalized.responses) == 2
    payload_by_hash = {
        sources[0]["textHash"]: _mp3(b"first"),
        sources[1]["textHash"]: _mp3(b"second"),
    }
    discovered = []
    payloads = {}
    for index, source in enumerate(sources):
        path = (
            "runs/abby-full-preprocess-20260622T152102Z/"
            f"phase4-residual/audio/abby-tts-{source['textHash']}.mp3"
        )
        payload = payload_by_hash[source["textHash"]]
        payloads[path] = payload
        discovered.append(
            {
                "path": path,
                "size_bytes": len(payload),
                # Deliberately a storage identity other than raw SHA-256.
                "xet_hash": sha256(f"xet-{index}".encode()).hexdigest(),
            }
        )
    plan = plan_abby_voice_bucket_audio(
        source_manifest={"responses": sources},
        accepted_responses=normalized.responses,
        discovered_objects=discovered,
        source_uri="hf://datasets/Publicus/211-abby-tts/source.json@commit",
        bucket_id="Publicus/abby-voice",
        listing_sha256="a" * 64,
    )
    return plan, payloads


def test_recovery_is_canary_limited_resumable_and_emits_exact_contracts(
    tmp_path: Path,
) -> None:
    import ipfs_datasets_py.voice as voice

    assert voice.recover_abby_voice_bucket_audio is recover_abby_voice_bucket_audio
    assert voice.DecodeProbeEvidence is DecodeProbeEvidence
    assert voice.BucketAudioRecoveryFailure is BucketAudioRecoveryFailure

    plan, payloads = _fixture()
    client = _DownloadClient(payloads)
    store = HuggingFaceBucketStore(plan.bucket_id, client=client)
    ledger = tmp_path / "verified.jsonl"
    cache = tmp_path / "cache"

    def probe(payload: bytes, media_type: str) -> DecodeProbeEvidence:
        return DecodeProbeEvidence(
            probe_name="test-mp3-probe",
            probe_version="1",
            passed=payload.startswith(b"ID3") and media_type == "audio/mpeg",
            details={"bytes_seen": len(payload)},
        )

    first = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=cache,
        ledger_path=ledger,
        decode_probe=probe,
        limit=1,
    )

    assert len(client.calls) == 1
    assert len(first.records) == first.inventory.object_count == 1
    assert len(first.candidates) == 1
    assert first.target_complete is True
    assert first.plan_complete is False
    record = first.records[0]
    pending = first.candidates[0]
    assert isinstance(pending, PendingBucketAudioCandidate)
    assert not isinstance(pending, LegacyAudioCandidate)
    assert not hasattr(pending, "candidate_id")
    assert not hasattr(pending, "subject_id")
    assert not hasattr(pending, "paths")
    assert not hasattr(pending, "expected_sha256")
    assert record.raw_sha256 == sha256(payloads[record.bucket_path]).hexdigest()
    assert record.raw_sha256 != record.xet_hash
    assert record.decode_probe is not None
    assert record.decode_probe.details["bytes_seen"] == record.verified_size_bytes
    assert first.inventory.objects[0].sha256 == record.raw_sha256
    assert pending.raw_sha256 == record.raw_sha256
    assert pending.response_id == record.response_id
    assert pending.verified_record_id == record.record_id
    assert PendingBucketAudioCandidate.from_json(pending.to_json()) == pending
    assert first.summary()["xet_hash_used_as_raw_sha256"] is False
    assert first.summary()["publishable"] is False
    assert first.summary()["semantic_asr_and_critical_slot_validation_required"] is True
    assert first.summary()["target_complete"] is True
    assert first.summary()["plan_complete"] is False
    assert "complete" not in first.summary()
    assert not first.failures
    assert bucket_audio_cache_path(cache, record.xet_hash).read_bytes() == payloads[
        record.bucket_path
    ]
    assert read_verified_bucket_audio_jsonl(ledger) == first.records
    assert AbbyVoiceBucketAudioRecovery.from_json(first.to_json()) == first
    assert VerifiedBucketAudioRecord.from_json(record.to_json()) == record

    # The same total canary target is a cache/ledger-only resume.
    resumed = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=cache,
        ledger_path=ledger,
        decode_probe=probe,
        limit=1,
    )
    assert resumed == first
    assert len(client.calls) == 1

    # Raising the total target fetches only the newly included selection.
    complete = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=cache,
        ledger_path=ledger,
        decode_probe=probe,
        limit=2,
    )
    assert len(client.calls) == 2
    assert len(complete.records) == len(complete.candidates) == 2
    assert complete.target_complete is True
    assert complete.plan_complete is True
    assert complete.summary()["pending_candidate_count"] == 2
    assert read_verified_bucket_audio_jsonl(ledger) == complete.records


def test_jsonl_is_strict_and_stale_plan_binding_is_rejected(
    tmp_path: Path,
) -> None:
    plan, payloads = _fixture()
    client = _DownloadClient(payloads)
    store = HuggingFaceBucketStore(plan.bucket_id, client=client)
    ledger = tmp_path / "verified.jsonl"
    result = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=tmp_path / "cache",
        ledger_path=ledger,
        limit=1,
    )
    canonical = verified_bucket_audio_jsonl_bytes(result.records)
    assert parse_verified_bucket_audio_jsonl(canonical) == result.records
    with pytest.raises(BucketAudioRecoveryError, match="end with a newline"):
        parse_verified_bucket_audio_jsonl(canonical.rstrip(b"\n"))
    payload = json.loads(result.records[0].to_json())
    payload["unknown"] = True
    with pytest.raises(BucketAudioRecoveryError, match="unknown fields"):
        parse_verified_bucket_audio_jsonl(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )

    stale = replace(
        result.records[0],
        plan_id="abby-voice-bucket-audio-plan:sha256:" + ("f" * 64),
        record_id="",
    )
    ledger.write_bytes(verified_bucket_audio_jsonl_bytes((stale,)))
    with pytest.raises(BucketAudioRecoveryError, match="stale plan_id"):
        recover_abby_voice_bucket_audio(
            plan=plan,
            store=store,
            cache_dir=tmp_path / "cache",
            ledger_path=ledger,
            limit=1,
        )


def test_corrupt_cache_is_refetched_but_decode_failure_is_not_ledgered(
    tmp_path: Path,
) -> None:
    plan, payloads = _fixture()
    client = _DownloadClient(payloads)
    store = HuggingFaceBucketStore(plan.bucket_id, client=client)
    cache = tmp_path / "cache"
    ledger = tmp_path / "verified.jsonl"
    first = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=cache,
        ledger_path=ledger,
        limit=1,
    )
    cached = bucket_audio_cache_path(cache, first.records[0].xet_hash)
    original = payloads[first.records[0].bucket_path]
    substitution = b"ID3" + (b"x" * (len(original) - 3))
    assert len(substitution) == len(original)
    assert sha256(substitution).hexdigest() != first.records[0].raw_sha256
    cached.write_bytes(substitution)

    resumed = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=cache,
        ledger_path=ledger,
        limit=1,
    )
    assert resumed == first
    assert len(client.calls) == 2
    assert cached.read_bytes() == payloads[first.records[0].bucket_path]

    failing_ledger = tmp_path / "failing.jsonl"
    with pytest.raises(BucketAudioRecoveryError, match="decode probe rejected"):
        recover_abby_voice_bucket_audio(
            plan=plan,
            store=store,
            cache_dir=tmp_path / "other-cache",
            ledger_path=failing_ledger,
            decode_probe=lambda _payload, _media: False,
            limit=1,
            fail_fast=True,
        )
    assert not failing_ledger.exists()


def test_unledgered_same_size_xet_cache_file_is_never_trusted(
    tmp_path: Path,
) -> None:
    plan, payloads = _fixture()
    selection = sorted(plan.selections, key=lambda item: item.response_id)[0]
    assert selection.selected.xet_hash is not None
    cache = tmp_path / "cache"
    cached = bucket_audio_cache_path(cache, selection.selected.xet_hash)
    cached.parent.mkdir(parents=True)
    expected = payloads[selection.selected.path]
    substitution = b"ID3" + (b"z" * (len(expected) - 3))
    assert len(substitution) == selection.selected.size_bytes
    cached.write_bytes(substitution)

    client = _DownloadClient(payloads)
    result = recover_abby_voice_bucket_audio(
        plan=plan,
        store=HuggingFaceBucketStore(plan.bucket_id, client=client),
        cache_dir=cache,
        limit=1,
    )

    assert len(client.calls) == 1
    assert cached.read_bytes() == expected
    assert result.records[0].raw_sha256 == sha256(expected).hexdigest()


def test_one_unrecoverable_row_is_disposed_and_later_rows_continue(
    tmp_path: Path,
) -> None:
    plan, payloads = _fixture()
    missing_selection = sorted(
        plan.selections, key=lambda item: item.response_id
    )[0]
    payloads.pop(missing_selection.selected.path)
    client = _DownloadClient(payloads)

    result = recover_abby_voice_bucket_audio(
        plan=plan,
        store=HuggingFaceBucketStore(plan.bucket_id, client=client),
        cache_dir=tmp_path / "cache",
        ledger_path=tmp_path / "verified.jsonl",
        limit=2,
    )

    assert len(result.records) == 1
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.response_id == missing_selection.response_id
    assert failure.stage is BucketAudioFailureStage.FETCH_AND_VERIFY
    assert failure.retryable is True
    assert failure.selected_bucket_path in failure.attempted_bucket_paths
    assert result.summary()["target_complete"] is False
    assert result.summary()["plan_complete"] is False
    assert result.summary()["failed_record_count"] == 1
    assert result.summary()["verified_record_count"] == 1
    assert result.summary()["pending_candidate_count"] == 1
    assert BucketAudioRecoveryFailure.from_json(failure.to_json()) == failure
    assert AbbyVoiceBucketAudioRecovery.from_json(result.to_json()) == result
    assert read_verified_bucket_audio_jsonl(
        tmp_path / "verified.jsonl"
    ) == result.records


def test_missing_xet_is_a_row_local_failure_disposition(
    tmp_path: Path,
) -> None:
    plan, payloads = _fixture()
    target = sorted(plan.selections, key=lambda item: item.response_id)[0]
    missing_xet_target = replace(
        target,
        selected=replace(target.selected, xet_hash=None),
    )
    plan = replace(
        plan,
        selections=tuple(
            missing_xet_target
            if item.response_id == target.response_id
            else item
            for item in plan.selections
        ),
        plan_id="",
    )
    client = _DownloadClient(payloads)

    result = recover_abby_voice_bucket_audio(
        plan=plan,
        store=HuggingFaceBucketStore(plan.bucket_id, client=client),
        cache_dir=tmp_path / "cache",
        limit=1,
    )

    assert not client.calls
    assert not result.records
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.response_id == target.response_id
    assert failure.xet_hash is None
    assert failure.attempted_bucket_paths == (target.selected.path,)
    assert failure.stage is BucketAudioFailureStage.FETCH_AND_VERIFY
    assert "has no Xet hash" in failure.detail
    assert failure.retryable is True
    assert BucketAudioRecoveryFailure.from_json(failure.to_json()) == failure
    assert AbbyVoiceBucketAudioRecovery.from_json(result.to_json()) == result


def test_row_local_oserror_is_disposed_and_later_rows_continue(
    tmp_path: Path,
) -> None:
    plan, payloads = _fixture()
    target = sorted(plan.selections, key=lambda item: item.response_id)[0]
    client = _DownloadClient(payloads)
    store = _OSErrorStore(
        plan.bucket_id,
        client=client,
        failing_path=target.selected.path,
    )

    result = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=tmp_path / "cache",
        limit=2,
    )

    assert len(result.records) == 1
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.response_id == target.response_id
    assert failure.stage is BucketAudioFailureStage.FETCH_AND_VERIFY
    assert "temporary local I/O failure" in failure.detail
    assert failure.retryable is True
    assert result.target_complete is False
    assert result.plan_complete is False


def test_selected_path_failure_uses_only_an_exact_xet_and_size_alternative(
    tmp_path: Path,
) -> None:
    plan, payloads = _fixture()
    selection = sorted(plan.selections, key=lambda item: item.response_id)[0]
    selected = selection.selected
    alternative_path = (
        "runs/abby-full-preprocess-20260614T004544Z/"
        f"phase4-residual/audio/abby-tts-{selection.legacy_text_hash}.mp3"
    )
    alternative = replace(selected, path=alternative_path)
    plan = replace(
        plan,
        selections=tuple(
            replace(item, alternatives=(alternative, *item.alternatives))
            if item.response_id == selection.response_id
            else item
            for item in plan.selections
        ),
        plan_id="",
    )
    payloads[alternative_path] = payloads[selected.path]
    client = _FailSelectedDownloadClient(payloads, selected.path)

    result = recover_abby_voice_bucket_audio(
        plan=plan,
        store=HuggingFaceBucketStore(plan.bucket_id, client=client),
        cache_dir=tmp_path / "cache",
        limit=1,
    )

    assert [call[1] for call in client.calls] == [selected.path, alternative_path]
    assert result.records[0].bucket_path == alternative_path
    assert result.records[0].xet_hash == selected.xet_hash
    assert result.records[0].raw_sha256 == sha256(
        payloads[alternative_path]
    ).hexdigest()


def test_checkpoint_interval_is_batched_validated_and_always_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ipfs_datasets_py.voice.bucket_audio_recovery as recovery_module

    plan, payloads = _fixture()
    store = HuggingFaceBucketStore(
        plan.bucket_id, client=_DownloadClient(payloads)
    )
    with pytest.raises(BucketAudioRecoveryError, match="positive integer"):
        recover_abby_voice_bucket_audio(
            plan=plan,
            store=store,
            cache_dir=tmp_path / "invalid",
            checkpoint_interval=0,
        )

    writes: list[Path] = []
    original = recovery_module.write_verified_bucket_audio_jsonl

    def observed_write(path, records):
        writes.append(Path(path))
        return original(path, records)

    monkeypatch.setattr(
        recovery_module, "write_verified_bucket_audio_jsonl", observed_write
    )
    ledger = tmp_path / "checkpointed.jsonl"
    result = recover_abby_voice_bucket_audio(
        plan=plan,
        store=store,
        cache_dir=tmp_path / "cache",
        ledger_path=ledger,
        limit=2,
        checkpoint_interval=1,
    )
    # Each interval is written once; the exact final boundary is not duplicated.
    assert writes == [ledger, ledger]
    assert read_verified_bucket_audio_jsonl(ledger) == result.records
