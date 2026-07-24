"""Integration evidence for the bounded, draft-only Leanstral adapter."""

from __future__ import annotations

import hashlib

import pytest

from benchmarks.logic_pipeline import adapters, contracts


SHA_A = "a" * 64
SHA_B = "b" * 64


def _request(**input_data: object) -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id="leanstral-run-1",
        case_id="leanstral-case-1",
        case_manifest_sha256=SHA_A,
        input_data={
            "obligation_id": "obl-identity",
            "prompt": "Prove the identity obligation.",
            **input_data,
        },
        requested_identity={"provider": "leanstral_local", "model": "Leanstral"},
        environment_sha256=SHA_B,
    )


def _draft(text: str = "by exact rfl") -> dict[str, object]:
    return {
        "schema_version": adapters.LEANSTRAL_DRAFT_SCHEMA,
        "artifact_id": "leanstral-draft-test-1",
        "artifact_kind": "llm_output",
        "stage": "model_draft",
        "draft_text": text,
        "proof_text": text,
        "request_id": "provider-request-1",
        "llm_provider": "leanstral_local",
        "model": "Leanstral",
        "obligation_ids": ["obl-identity"],
        "resource_class": "model",
        "output_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "kernel_checked": False,
    }


def _run(handler, request: adapters.StageRequest | None = None):
    return adapters.LeanstralAdapter(handler).run(request or _request())


def test_objective_receipt_and_successful_draft_are_explicitly_unverified() -> None:
    assert adapters.HSSLEV0342A4C() == (
        "Leanstral proof drafts use strict schemas and one bounded unverified repair"
    )
    record = _run(lambda request: _draft())

    assert record.stage is contracts.StageName.LEANSTRAL
    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["schema"] == adapters.LEANSTRAL_EVIDENCE_SCHEMA
    assert record.data["mode"] == "synthesis"
    assert record.data["repair_attempts"] == 0
    assert record.data["obligation_id"] == "obl-identity"
    assert record.data["trust"] == {
        "assurance": "unverified",
        "verified": False,
        "authoritative": False,
        "kernel_checked": False,
    }
    assert record.kernel_accepted is False
    assert record.kernel_receipt_sha256 is None
    assert record.data["resource_classes"] == {
        "model_inference": "model",
        "kernel_check": "kernel",
    }
    assert contracts.StageRecord.from_dict(record.to_dict()).digest == record.digest


def test_repair_is_one_explicit_attempt_and_preserves_failure_context() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: adapters.StageRequest) -> dict[str, object]:
        assert isinstance(request.input_data, dict)
        seen.append(request.input_data)
        return _draft("by simp")

    record = _run(
        handler,
        _request(
            repair_attempt=1,
            repair={
                "failed_draft": "by exact wrong_lemma",
                "failure": "unknown constant wrong_lemma",
            },
        ),
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["mode"] == "repair"
    assert record.data["repair_attempts"] == 1
    assert len(seen) == 1
    assert seen[0]["max_repair_attempts"] == 1
    assert seen[0]["compact_failures"] == [
        {"message": "unknown constant wrong_lemma"}
    ]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda draft: draft | {"schema_version": "wrong-schema"},
        lambda draft: draft | {"obligation_ids": ["other-obligation"]},
        lambda draft: draft | {"draft_text": "by exact sorry", "proof_text": "by exact sorry"},
        lambda draft: draft | {"authoritative": True},
    ],
)
def test_malformed_forbidden_or_authoritative_model_output_fails_closed(mutator) -> None:
    record = _run(lambda _request: mutator(_draft()))

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )
    assert record.output_sha256 is None
    assert record.kernel_accepted is False


def test_timeout_and_unavailable_backend_are_distinct_explicit_outcomes() -> None:
    timed_out = _run(lambda _request: (_ for _ in ()).throw(TimeoutError("deadline")))
    assert timed_out.status is contracts.StageStatus.FAILED
    assert (
        timed_out.failure_code
        is contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )

    unavailable = _run(
        lambda _request: (_ for _ in ()).throw(
            ImportError("leanstral provider is not installed")
        )
    )
    assert unavailable.status is contracts.StageStatus.UNAVAILABLE
    assert unavailable.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE


def test_repair_bound_and_fixed_obligation_are_rejected_before_handler() -> None:
    calls = 0

    def handler(_request: adapters.StageRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _draft()

    too_many = _run(handler, _request(repair_attempt=2, repair={"failure": "x", "draft": "y"}))
    assert too_many.status is contracts.StageStatus.FAILED
    assert calls == 0

    multi = _run(handler, _request(obligation_ids=["obl-identity", "obl-other"]))
    assert multi.status is contracts.StageStatus.FAILED
    assert calls == 0

