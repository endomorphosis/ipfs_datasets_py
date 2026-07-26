"""Integration evidence for the bounded, draft-only Leanstral adapter."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import time
from types import SimpleNamespace
import urllib.error

import pytest

from benchmarks.logic_pipeline import adapters, contracts, runtime


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


def _draft(text: str = "exact rfl") -> dict[str, object]:
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


def _repair_source_artifacts(
    *,
    failed_draft: dict[str, object] | None = None,
) -> tuple[adapters.StageArtifact, adapters.StageArtifact]:
    leanstral = adapters.StageArtifact(
        stage=contracts.StageName.LEANSTRAL,
        status=contracts.StageStatus.SUCCESS,
        data={
            "schema": adapters.LEANSTRAL_EVIDENCE_SCHEMA,
            "draft": failed_draft or _draft("exact wrong_lemma"),
        },
        output_sha256=None,
        effective_identity={"graph_invoked": True},
        invocation_index=0,
    )
    kernel_body = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "native-kernel-receipt.v1"
        ),
        "accepted": False,
        "independent": True,
        "active_process_count": 0,
        "returncode": 1,
    }
    kernel = adapters.StageArtifact(
        stage=contracts.StageName.KERNEL,
        status=contracts.StageStatus.FAILED,
        data={
            **kernel_body,
            "receipt_sha256": hashlib.sha256(
                contracts.canonical_json(kernel_body).encode("utf-8")
            ).hexdigest(),
        },
        output_sha256=None,
        effective_identity={"graph_invoked": True},
        invocation_index=1,
    )
    return leanstral, kernel


def _source_bound_repair_request(
    base: adapters.StageRequest | None = None,
    *,
    failure_text: str = "unknown constant wrong_lemma",
) -> tuple[
    adapters.StageRequest,
    adapters.StageRequest,
    adapters.StageArtifact,
    adapters.StageArtifact,
]:
    original = base or _request()
    leanstral, kernel = _repair_source_artifacts()
    context = adapters.build_leanstral_repair_context(
        case_input_sha256=original.input_sha256,
        failed_leanstral_artifact=leanstral,
        kernel_rejection_artifact=kernel,
        failure_text=failure_text,
    )
    repair = replace(
        original,
        repair_context=context,
        upstream_artifacts=(leanstral, kernel),
        invocation_index=2,
    )
    return original, repair, leanstral, kernel


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
        return _draft("simp")

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


def test_out_of_band_repair_is_source_bound_without_changing_case_identity() -> None:
    seen: list[adapters.StageRequest] = []
    original, repair, leanstral, kernel = _source_bound_repair_request(
        failure_text=" unknown\nconstant\x00wrong_lemma "
    )
    original_input_sha256 = original.input_sha256
    original_input_data = original.input_data

    def handler(request: adapters.StageRequest) -> dict[str, object]:
        seen.append(request)
        return _draft("simp")

    record = _run(handler, repair)

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["mode"] == "repair"
    assert record.data["repair_attempts"] == 1
    assert repair.input_data is original_input_data
    assert repair.input_sha256 == original_input_sha256
    assert record.provenance.input_sha256 == original_input_sha256
    assert repair.repair_context is not None
    assert repair.repair_context["failure_text"] == (
        "unknown constant wrong_lemma"
    )
    assert repair.repair_context["failed_leanstral_artifact_sha256"] == (
        leanstral.digest
    )
    assert repair.repair_context["kernel_rejection_receipt_sha256"] == (
        kernel.data["receipt_sha256"]
    )
    with pytest.raises(TypeError):
        repair.repair_context["failure_text"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        repair.repair_context["failed_draft"]["proof_text"] = "mutated"  # type: ignore[index]

    assert len(seen) == 1
    projected = seen[0]
    assert projected.repair_context is None
    assert isinstance(projected.input_data, dict)
    assert projected.input_data["repair_attempt"] == 1
    assert projected.input_data["compact_failures"] == [
        {"message": "unknown constant wrong_lemma"}
    ]
    assert projected.input_data["reusable_drafts"] == [
        adapters._thaw_json(repair.repair_context["failed_draft"])
    ]
    projected_repair = projected.input_data["repair"]
    assert projected_repair["case_input_sha256"] == original_input_sha256
    assert projected_repair["failed_leanstral_artifact_sha256"] == (
        leanstral.digest
    )
    assert projected_repair["kernel_rejection_receipt_sha256"] == (
        kernel.data["receipt_sha256"]
    )
    expected_provider_id = "leanstral-" + hashlib.sha256(
        (
            f"{repair.run_id}:{repair.case_id}:"
            f"{original_input_sha256}:1"
        ).encode("utf-8")
    ).hexdigest()[:48]
    assert adapters._provider_request_id(repair, 1) == expected_provider_id


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        (
            "case_input_sha256",
            "c" * 64,
            "current case input",
        ),
        (
            "attempt",
            0,
            "attempt must be exactly one",
        ),
        (
            "failed_leanstral_artifact_sha256",
            "c" * 64,
            "failed Leanstral artifact",
        ),
        (
            "kernel_rejection_receipt_sha256",
            "c" * 64,
            "kernel rejection receipt",
        ),
        (
            "failure_text_sha256",
            "c" * 64,
            "failure_text digest",
        ),
        (
            "failed_draft_sha256",
            "c" * 64,
            "failed_draft digest",
        ),
    ],
)
def test_out_of_band_repair_context_rejects_tampered_bindings(
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    original, repair, leanstral, kernel = _source_bound_repair_request()
    assert repair.repair_context is not None
    tampered = adapters._thaw_json(repair.repair_context)
    assert isinstance(tampered, dict)
    tampered[field_name] = replacement

    with pytest.raises(contracts.ProtocolContractError, match=message):
        replace(
            original,
            repair_context=tampered,
            upstream_artifacts=(leanstral, kernel),
            invocation_index=2,
        )


def test_out_of_band_repair_context_rejects_draft_and_receipt_source_tampering() -> None:
    original, repair, leanstral, kernel = _source_bound_repair_request()
    assert repair.repair_context is not None
    changed = adapters._thaw_json(repair.repair_context)
    assert isinstance(changed, dict)
    changed["failed_draft"]["draft_text"] = "exact other"
    changed["failed_draft"]["proof_text"] = "exact other"
    changed["failed_draft_sha256"] = hashlib.sha256(
        contracts.canonical_json(changed["failed_draft"]).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        contracts.ProtocolContractError,
        match="failed Leanstral artifact",
    ):
        replace(
            original,
            repair_context=changed,
            upstream_artifacts=(leanstral, kernel),
            invocation_index=2,
        )

    kernel_data = dict(kernel.data)
    kernel_data["returncode"] = 2
    changed_kernel = replace(kernel, data=kernel_data)
    with pytest.raises(
        contracts.ProtocolContractError,
        match="kernel rejection receipt",
    ):
        replace(
            original,
            repair_context=repair.repair_context,
            upstream_artifacts=(leanstral, changed_kernel),
            invocation_index=2,
        )


def test_repair_context_can_reconstruct_payload_for_downstream_kernel_check() -> None:
    original, repair, _failed_leanstral, kernel = (
        _source_bound_repair_request()
    )
    assert repair.repair_context is not None
    repaired_leanstral = adapters.StageArtifact(
        stage=contracts.StageName.LEANSTRAL,
        status=contracts.StageStatus.SUCCESS,
        data={
            "schema": adapters.LEANSTRAL_EVIDENCE_SCHEMA,
            "mode": "repair",
            "repair_attempts": 1,
            "draft": _draft("simp"),
        },
        output_sha256=None,
        effective_identity={"graph_invoked": True},
        invocation_index=2,
    )
    downstream = replace(
        original,
        repair_context=repair.repair_context,
        upstream_artifacts=(repaired_leanstral, kernel),
        invocation_index=3,
    )

    payload, obligation_id, repair_attempt = adapters._leanstral_input(
        downstream,
        adapters.LeanstralAdapterConfig(),
    )

    assert downstream.input_sha256 == original.input_sha256
    assert obligation_id == "obl-identity"
    assert repair_attempt == 1
    assert payload["repair"]["failed_leanstral_artifact_sha256"] == (
        repair.repair_context["failed_leanstral_artifact_sha256"]
    )
    assert payload["repair"]["kernel_rejection_receipt_sha256"] == (
        kernel.data["receipt_sha256"]
    )


def test_out_of_band_repair_context_enforces_failure_and_draft_bounds() -> None:
    original = _request()
    leanstral, kernel = _repair_source_artifacts()
    with pytest.raises(
        contracts.ProtocolContractError,
        match="failure_text exceeds",
    ):
        adapters.build_leanstral_repair_context(
            case_input_sha256=original.input_sha256,
            failed_leanstral_artifact=leanstral,
            kernel_rejection_artifact=kernel,
            failure_text="x" * (
                adapters.LEANSTRAL_MAX_REPAIR_FAILURE_BYTES + 1
            ),
        )

    oversized = _draft(
        "x" * (adapters.LEANSTRAL_MAX_REPAIR_DRAFT_BYTES + 1)
    )
    large_leanstral, kernel = _repair_source_artifacts(
        failed_draft=oversized
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="failed_draft exceeds",
    ):
        adapters.build_leanstral_repair_context(
            case_input_sha256=original.input_sha256,
            failed_leanstral_artifact=large_leanstral,
            kernel_rejection_artifact=kernel,
            failure_text="kernel rejected candidate",
        )


def test_out_of_band_and_legacy_repair_sources_cannot_conflict() -> None:
    legacy = _request(
        repair_attempt=1,
        repair={
            "failure": "legacy failure",
            "failed_draft": "exact legacy",
        },
    )
    _original, repair, _leanstral, _kernel = (
        _source_bound_repair_request(legacy)
    )
    calls = 0

    def handler(_request: adapters.StageRequest) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _draft("simp")

    record = _run(handler, repair)

    assert record.status is contracts.StageStatus.FAILED
    assert calls == 0
    assert record.data["safe_failure_class"] == "malformed_request"
    assert record.failure_detail == (
        "Leanstral request violated the strict provider contract"
    )


def test_frozen_case_text_is_the_prompt_at_the_leanstral_boundary() -> None:
    seen: list[dict[str, object]] = []
    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )

    def handler(request: adapters.StageRequest) -> dict[str, object]:
        assert isinstance(request.input_data, dict)
        seen.append(request.input_data)
        return _draft()

    record = _run(handler, _request(prompt=None, text=source_text))

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(seen) == 1
    assert seen[0]["prompt"] == source_text
    assert seen[0]["text"] == source_text
    assert seen[0]["obligation_id"] == "obl-identity"


def test_frozen_case_text_crosses_the_supervisor_provider_contract() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    seen_prompts: list[str] = []
    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )
    provider = LeanstralProofProvider(
        llm_generate=lambda prompt, **_kwargs: (
            seen_prompts.append(prompt) or "exact h"
        )
    )

    record = adapters.LeanstralAdapter(provider=provider).run(
        _request(prompt=None, text=source_text)
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert seen_prompts == [source_text]
    assert record.data["draft"]["schema_version"] == adapters.LEANSTRAL_DRAFT_SCHEMA
    assert record.data["draft"]["obligation_ids"] == ("obl-identity",)
    assert record.data["trust"]["assurance"] == "unverified"
    assert record.kernel_accepted is False


def test_a3_fallback_binds_the_compiler_theorem_and_structured_schema() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )
    compiled = runtime.compile_reviewed_obligation(
        {
            "text": source_text,
            "obligation_id": "obl-identity",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        }
    )
    assert compiled is not None
    compiler = adapters.StageArtifact(
        stage=contracts.StageName.COMPILER,
        status=contracts.StageStatus.SUCCESS,
        data={"compiled_obligation": compiled.to_dict()},
        output_sha256=None,
        effective_identity={"entrypoint": "test-compiler"},
        invocation_index=0,
    )
    seen_prompts: list[dict[str, object]] = []

    def generate(prompt: str, **_kwargs: object) -> str:
        structured = json.loads(prompt)
        seen_prompts.append(structured)
        theorem = structured["fixed_theorem"]
        return json.dumps(
            {
                "schema": (
                    "ipfs_accelerate_py.agent_supervisor."
                    "leanstral-proof-proposal@1"
                ),
                "theorem_id": theorem["theorem_id"],
                "proposal_kind": "proof",
                "proof_text": "exact rule witness fact",
            }
        )

    request = replace(
        _request(prompt=None, text=source_text),
        variant_id="A3",
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    record = adapters.LeanstralAdapter(
        provider=LeanstralProofProvider(llm_generate=generate)
    ).run(request)

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(seen_prompts) == 1
    fixed = seen_prompts[0]["fixed_theorem"]
    assert "translation:direct_unary_entailment" in compiled.source_template
    assert fixed["obligation_id"] == "obl-identity"
    assert fixed["declaration_name"] == compiled.theorem_name
    assert [item.split()[0] for item in fixed["assumptions"]] == [
        "(witness",
        "(rule",
        "(fact",
    ]
    assert fixed["conclusion"]
    assert fixed["conclusion"] in compiled.source_template
    assert fixed["canonical_source_digest"] == (
        f"sha256:{compiled.source_template_sha256}"
    )
    assert seen_prompts[0]["output_schema"]["schema"] == (
        "ipfs_accelerate_py.agent_supervisor.leanstral-proof-proposal@1"
    )
    assert record.data["draft"]["context_capsule_id"].startswith(
        "proof-context:sha256:"
    )
    assert record.data["draft"]["proof_text"] == "exact rule witness fact"
    rendered = compiled.render(record.data["draft"]["proof_text"])
    assert "by\n  exact rule witness fact" in rendered
    assert "by\n  by" not in rendered
    assert record.kernel_accepted is False


def test_semantic_confidence_numbers_cross_strict_provider_boundary() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )
    compiled = runtime.compile_reviewed_obligation(
        {
            "text": source_text,
            "obligation_id": "obl-identity",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        }
    )
    assert compiled is not None
    compiler = adapters.StageArtifact(
        stage=contracts.StageName.COMPILER,
        status=contracts.StageStatus.SUCCESS,
        data={"compiled_obligation": compiled.to_dict()},
        output_sha256=None,
        effective_identity={"entrypoint": "test-compiler"},
        invocation_index=0,
    )
    spacy = adapters.StageArtifact(
        stage=contracts.StageName.SPACY,
        status=contracts.StageStatus.SUCCESS,
        data={
            "schema": adapters.SPACY_EVIDENCE_SCHEMA,
            "semantic_roles": [
                {
                    "frame_id": "role-1",
                    "sentence": "Ada is trained.",
                    "predicate": "train",
                    "predicate_span": [7, 14],
                    "arguments": [
                        {
                            "role": "Agent",
                            "text": "Ada",
                            "span": [0, 3],
                            "confidence": 0.8,
                        }
                    ],
                    "confidence": 0.8,
                    "source": "spacy",
                }
            ],
        },
        output_sha256=None,
        effective_identity={
            "graph_invoked": True,
            "graph_invocation_index": 1,
        },
        invocation_index=1,
    )
    max_text = "x" * 77
    candidate_ir = {
        "propositions": [
            f"{index:02d}-{max_text}" for index in range(12)
        ]
    }
    symai = adapters.StageArtifact(
        stage=contracts.StageName.SYMAI,
        status=contracts.StageStatus.SUCCESS,
        data={
            "schema": adapters.SYMAI_EVIDENCE_SCHEMA,
            "candidate_ir": candidate_ir,
            "candidate_ir_sha256": hashlib.sha256(
                contracts.canonical_json(candidate_ir).encode("utf-8")
            ).hexdigest(),
            "normalized_predicates": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "quantifiers": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "entities": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "ambiguity_flags": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "confidence": 0.9,
            "validation_errors": [
                f"{index:02d}-{max_text}" for index in range(24)
            ],
            "assurance": {
                "semantic_hypothesis": True,
                "authoritative": False,
            },
        },
        output_sha256=None,
        effective_identity={
            "graph_invoked": True,
            "graph_invocation_index": 2,
        },
        invocation_index=2,
    )
    prompts: list[dict[str, object]] = []
    prompt_texts: list[str] = []

    def generate(prompt: str, **_kwargs: object) -> str:
        structured = json.loads(prompt)
        prompt_texts.append(prompt)
        prompts.append(structured)
        return json.dumps(
            {
                "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
                "theorem_id": structured["fixed_theorem"]["theorem_id"],
                "proposal_kind": "proof",
                "proof_text": "exact rule witness fact",
            }
        )

    request = replace(
        _request(prompt=None, text=source_text),
        variant_id="A4",
        upstream_artifacts=(compiler, spacy, symai),
        invocation_index=3,
    )
    source_context = adapters.build_upstream_semantic_context(request)
    payload, _obligation_id, _repair_attempt = adapters._leanstral_input(
        request,
        adapters.LeanstralAdapterConfig(),
    )
    record = adapters.LeanstralAdapter(
        provider=LeanstralProofProvider(llm_generate=generate)
    ).run(request)

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(prompts) == 1
    fields = payload["context_capsule"]["untrusted_suggestions"][0]["fields"]
    assert fields["schema"] == (
        adapters.LEANSTRAL_STRICT_SEMANTIC_CONTEXT_SCHEMA
    )
    assert "source_semantic_context_sha256" not in fields
    assert fields["semantic_context"]["schema"] == (
        adapters.LEANSTRAL_MODEL_SEMANTIC_CONTEXT_SCHEMA
    )
    assert source_context["artifacts"][0]["artifact_sha256"] == spacy.digest
    assert source_context["artifacts"][1]["artifact_sha256"] == symai.digest
    encoded_role = fields["semantic_context"]["artifacts"][0]["evidence"][
        "semantic_roles"
    ][0]
    assert encoded_role["confidence"] == {
        "schema": adapters.LEANSTRAL_JSON_NUMBER_SCHEMA,
        "json_number": "0.8",
    }
    assert encoded_role["arguments"][0]["confidence"] == {
        "schema": adapters.LEANSTRAL_JSON_NUMBER_SCHEMA,
        "json_number": "0.8",
    }
    encoded_symai = fields["semantic_context"]["artifacts"][1]["evidence"]
    assert "artifact_sha256" not in fields["semantic_context"]["artifacts"][0]
    assert "output_sha256" not in fields["semantic_context"]["artifacts"][0]
    assert "execution" not in fields["semantic_context"]["artifacts"][0][
        "evidence"
    ]
    assert "candidate_ir_sha256" not in encoded_symai
    assert len(encoded_symai["normalized_predicates"]) == 24
    assert encoded_symai["confidence"] == {
        "schema": adapters.LEANSTRAL_JSON_NUMBER_SCHEMA,
        "json_number": "0.9",
    }
    final_hints = prompts[0]["untrusted_semantic_hints"]
    assert len(final_hints) == 1
    hint = final_hints[0]
    assert hint["semantic_context"] == fields
    assert hint["trust"] == "untrusted_suggestion"
    assert hint["checked_evidence"] is False
    assert hint["authoritative"] is False
    assert hint["usable_as_premise"] is False
    assert hint["usable_as_proof_evidence"] is False
    assert hint["usable_as_failure_evidence"] is False
    assert hint["content_sha256"] == (
        "sha256:"
        + hashlib.sha256(
            contracts.canonical_json(fields).encode("utf-8")
        ).hexdigest()
    )
    assert len(contracts.canonical_json(hint).encode("utf-8")) > 10_002
    assert prompts[0]["semantic_hint_policy"] == {
        "semantic_guidance_only": True,
        "authoritative": False,
        "usable_as_premise": False,
        "usable_as_trusted_receipt": False,
        "usable_as_proof_evidence": False,
        "usable_as_failure_evidence": False,
    }
    final_prompt_sha256 = hashlib.sha256(
        prompt_texts[0].encode("utf-8")
    ).hexdigest()
    assert record.data["draft"]["prompt_sha256"] == final_prompt_sha256
    assert record.data["draft"]["context_capsule_id"] == (
        payload["context_capsule"]["capsule_id"]
    )


def test_leanstral_prompt_identity_ignores_cache_receipts_but_not_semantics() -> None:
    source_text = (
        "Every archivist is trained. Ada is an archivist. "
        "Therefore Ada is trained."
    )
    compiled = runtime.compile_reviewed_obligation(
        {
            "text": source_text,
            "obligation_id": "obl-cache-invariance",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "fol",
                "target": "trained",
            },
        }
    )
    assert compiled is not None
    compiler = adapters.StageArtifact(
        stage=contracts.StageName.COMPILER,
        status=contracts.StageStatus.SUCCESS,
        data={"compiled_obligation": compiled.to_dict()},
        output_sha256=None,
        effective_identity={"entrypoint": "test-compiler"},
        invocation_index=0,
    )

    def request_for(
        mode: contracts.CacheMode,
        *,
        cache_marker: str,
        predicate: str,
    ) -> adapters.StageRequest:
        spacy = adapters.StageArtifact(
            stage=contracts.StageName.SPACY,
            status=contracts.StageStatus.SUCCESS,
            data={
                "schema": adapters.SPACY_EVIDENCE_SCHEMA,
                "semantic_roles": [
                    {
                        "frame_id": "role-1",
                        "predicate": predicate,
                        "arguments": [{"role": "Agent", "text": "Ada"}],
                        "confidence": 1,
                        "source": "spacy",
                    }
                ],
                # Future cache-setup receipts must remain durable but must not
                # become model evidence.
                "cache_prime": {
                    "marker": cache_marker,
                    "receipt_sha256": hashlib.sha256(
                        cache_marker.encode("utf-8")
                    ).hexdigest(),
                },
            },
            output_sha256=None,
            effective_identity={
                "backend": "spacy",
                "cache_marker": cache_marker,
            },
            invocation_index=1,
        )
        candidate_ir = {"propositions": [f"{predicate}(Ada)"]}
        symai = adapters.StageArtifact(
            stage=contracts.StageName.SYMAI,
            status=contracts.StageStatus.SUCCESS,
            data={
                "schema": adapters.SYMAI_EVIDENCE_SCHEMA,
                "candidate_ir": candidate_ir,
                "candidate_ir_sha256": hashlib.sha256(
                    contracts.canonical_json(candidate_ir).encode("utf-8")
                ).hexdigest(),
                "normalized_predicates": [predicate],
                "quantifiers": [],
                "entities": ["Ada"],
                "ambiguity_flags": [],
                "confidence": 1,
                "validation_errors": [],
                "assurance": {
                    "semantic_hypothesis": True,
                    "authoritative": False,
                },
                "cache": {"mode": mode.value, "hit": mode is contracts.CacheMode.WARM},
                "cache_prime": {
                    "marker": cache_marker,
                    "receipt_sha256": hashlib.sha256(
                        f"prime:{cache_marker}".encode("utf-8")
                    ).hexdigest(),
                },
            },
            output_sha256=None,
            effective_identity={
                "backend": "symai",
                "cache_marker": cache_marker,
            },
            invocation_index=2,
        )
        return replace(
            _request(
                prompt=None,
                text=source_text,
                obligation_id="obl-cache-invariance",
            ),
            variant_id="A4",
            cache_mode=mode,
            upstream_artifacts=(compiler, spacy, symai),
            invocation_index=3,
        )

    def prompt_identity(
        request: adapters.StageRequest,
    ) -> tuple[str, str, dict[str, object], dict[str, object]]:
        payload, _, _ = adapters._leanstral_input(
            request,
            adapters.LeanstralAdapterConfig(),
        )
        proof_context = adapters.import_source_bound_ipfs_accelerate(
            "ipfs_accelerate_py.agent_supervisor.proof_context"
        )
        capsule = proof_context.ProofContextCapsule.from_dict(
            payload["context_capsule"]
        )
        final_context = proof_context.build_leanstral_proof_context(
            capsule,
            payload["fixed_theorem"],
        )
        return (
            payload["context_capsule"]["capsule_id"],
            final_context.prompt_sha256,
            payload,
            adapters.build_upstream_semantic_context(request),
        )

    cold = prompt_identity(
        request_for(
            contracts.CacheMode.COLD,
            cache_marker="cold-prime",
            predicate="trained",
        )
    )
    warm = prompt_identity(
        request_for(
            contracts.CacheMode.WARM,
            cache_marker="warm-hit",
            predicate="trained",
        )
    )
    changed = prompt_identity(
        request_for(
            contracts.CacheMode.WARM,
            cache_marker="warm-hit",
            predicate="certified",
        )
    )

    assert cold[0:2] == warm[0:2]
    assert cold[3]["context_sha256"] != warm[3]["context_sha256"]
    assert cold[0] != changed[0]
    assert cold[1] != changed[1]
    for payload in (cold[2], warm[2], changed[2]):
        semantic = payload["context_capsule"]["untrusted_suggestions"][0][
            "fields"
        ]["semantic_context"]
        encoded = contracts.canonical_json(semantic)
        assert "cache_prime" not in encoded
        assert "cache_marker" not in encoded
        assert "artifact_sha256" not in encoded
        assert "output_sha256" not in encoded


def test_non_corpus_runtime_readiness_smoke_uses_the_same_strict_boundary() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
        LeanstralProofProviderConfig,
    )

    calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def generate(prompt: str, **kwargs: object) -> str:
        structured = json.loads(prompt)
        calls.append((structured, kwargs))
        return json.dumps(
            {
                "schema": (
                    "ipfs_accelerate_py.agent_supervisor."
                    "leanstral-proof-proposal@1"
                ),
                "theorem_id": structured["fixed_theorem"]["theorem_id"],
                "proposal_kind": "proof",
                "proof_text": "rfl",
            }
        )

    provider = LeanstralProofProvider(
        LeanstralProofProviderConfig(
            llm_provider="leanstral_local",
            model="exact-test-model",
        ),
        llm_generate=generate,
    )
    record = adapters.run_leanstral_runtime_readiness_smoke(
        provider,
        provider_identity={
            "provider": "leanstral_local",
            "model": "exact-test-model",
        },
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(calls) == 1
    prompt, kwargs = calls[0]
    assert prompt["fixed_theorem"]["obligation_id"] == (
        "leanstral-runtime-smoke-obligation"
    )
    assert kwargs["provider"] == "leanstral_local"
    assert kwargs["model_name"] == "exact-test-model"
    assert kwargs["allow_local_fallback"] is False
    assert 0 < kwargs["timeout"] <= adapters.LEANSTRAL_MEASURED_TIMEOUT_SECONDS
    assert kwargs["max_new_tokens"] == (
        adapters.LEANSTRAL_MEASURED_MAX_NEW_TOKENS
    )
    assert record.data["draft"]["context_capsule_id"].startswith(
        "proof-context:sha256:"
    )
    assert record.data["draft"]["model"] == "exact-test-model"
    assert record.kernel_accepted is False


def test_measured_supervisor_request_binds_budget_and_absolute_deadline() -> None:
    requests: list[object] = []

    class Provider:
        def prove(self, request: object) -> dict[str, object]:
            requests.append(request)
            return _draft()

    config = adapters.LeanstralAdapterConfig(
        model_timeout_seconds=17.0,
        model_token_limit=321,
    )
    case_request = _request()
    expected_request_id = "leanstral-" + hashlib.sha256(
        (
            f"{case_request.run_id}:{case_request.case_id}:"
            f"{case_request.input_sha256}:0"
        ).encode("utf-8")
    ).hexdigest()[:48]
    before_ms = int(time.time() * 1_000)
    record = adapters.LeanstralAdapter(
        provider=Provider(),
        config=config,
    ).run(case_request)
    after_ms = int(time.time() * 1_000)

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(requests) == 1
    provider_request = requests[0]
    assert provider_request.resource_budget.wall_time_ms == 17_000
    assert provider_request.resource_budget.model_token_limit == 321
    assert provider_request.resource_budget.max_output_bytes == (
        adapters.LEANSTRAL_MAX_DRAFT_BYTES
    )
    assert provider_request.request_id == expected_request_id
    assert before_ms + 17_000 <= provider_request.deadline_unix_ms
    assert provider_request.deadline_unix_ms <= after_ms + 17_000
    assert provider_request.network_allowed is False


def test_case_deadline_caps_measured_leanstral_invocation() -> None:
    requests: list[object] = []

    class Provider:
        def prove(self, request: object) -> dict[str, object]:
            requests.append(request)
            return _draft()

    case_deadline_unix_ms = int(time.time() * 1_000) + 500
    record = adapters.LeanstralAdapter(
        provider=Provider(),
        config=adapters.LeanstralAdapterConfig(
            model_timeout_seconds=17.0,
            model_token_limit=321,
        ),
    ).run(
        replace(
            _request(),
            deadline_unix_ms=case_deadline_unix_ms,
        )
    )

    assert record.status is contracts.StageStatus.SUCCESS
    assert len(requests) == 1
    provider_request = requests[0]
    assert provider_request.deadline_unix_ms == case_deadline_unix_ms
    assert 1 <= provider_request.resource_budget.wall_time_ms <= 500
    assert provider_request.resource_budget.model_token_limit == 321


def test_expired_absolute_deadline_cancels_before_model_generation() -> None:
    from ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider import (
        LeanstralProofProvider,
    )

    model_calls = 0

    def generate(_prompt: str, **_kwargs: object) -> str:
        nonlocal model_calls
        model_calls += 1
        return "exact rfl"

    delegate = LeanstralProofProvider(llm_generate=generate)

    class DelayedProvider:
        def prove(self, request: object) -> object:
            time.sleep(0.02)
            return delegate.prove(request)

    record = adapters.LeanstralAdapter(
        provider=DelayedProvider(),
        config=adapters.LeanstralAdapterConfig(
            model_timeout_seconds=0.005,
            model_token_limit=64,
        ),
    ).run(_request())

    assert record.status is contracts.StageStatus.FAILED
    assert record.failure_code is (
        contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )
    assert record.data["safe_failure_class"] == "timed_out"
    assert record.failure_detail == "Leanstral provider timed out"
    assert record.telemetry.model_calls == 0
    assert model_calls == 0


def test_strict_provider_request_failure_is_safe_and_pre_generation() -> None:
    provider_calls = 0

    class Provider:
        def prove(self, _request: object) -> dict[str, object]:
            nonlocal provider_calls
            provider_calls += 1
            return _draft()

    record = adapters.LeanstralAdapter(provider=Provider()).run(
        _request(context_capsule={"confidence": 0.8})
    )

    assert record.status is contracts.StageStatus.FAILED
    assert record.failure_code is (
        contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )
    assert record.data["safe_failure_class"] == "malformed_request"
    assert record.failure_detail == (
        "Leanstral request violated the strict provider contract"
    )
    assert record.telemetry.model_calls == 0
    assert provider_calls == 0


def test_request_isolated_provider_does_not_reuse_delegate_state() -> None:
    instances: list[object] = []

    class StatefulProvider:
        def __init__(self) -> None:
            self.calls = 0
            instances.append(self)

        def prove(self, _request: object) -> int:
            self.calls += 1
            return self.calls

    provider = adapters._RequestIsolatedLeanstralProvider(StatefulProvider)

    assert provider.prove(object()) == 1
    assert provider.prove(object()) == 1
    assert len(instances) == 2


def test_pinned_typed_failure_binds_exact_route_and_original_receipt() -> None:
    endpoint = "http://127.0.0.1:8080/v1"
    provider_name = "leanstral_local"
    model = "exact-test-model"
    pinned_identity = {
        "endpoint": endpoint,
        "provider": provider_name,
        "model": model,
        "cache_prompt": False,
    }
    failure = adapters.LeanstralGenerationFailure(
        "timed_out",
        phase="completion_request",
        request_payload_sha256=hashlib.sha256(b"request").hexdigest(),
    )

    class Provider:
        @staticmethod
        def prove(_request: object) -> object:
            raise failure

    isolated = adapters._RequestIsolatedLeanstralProvider(
        Provider,
        pinned_identity=pinned_identity,
    )
    adapter = adapters.LeanstralAdapter(provider=isolated)
    record = adapter.run(_request())

    assert dict(adapter.pinned_provider_identity) == pinned_identity
    assert record.status is contracts.StageStatus.FAILED
    assert record.data["safe_failure_class"] == "timed_out"
    boundary = record.data["generation_failure_boundary"]
    assert boundary["endpoint"] == endpoint
    assert boundary["provider"] == provider_name
    assert boundary["requested_model"] == model
    assert boundary["cache_prompt"] is False
    assert boundary["provider_failure_receipt_sha256"] == (
        failure.boundary_receipt["receipt_sha256"]
    )
    identity = record.provenance.effective_identity
    assert identity["endpoint"] == endpoint
    assert identity["provider"] == provider_name
    assert identity["model"] == model
    assert identity["cache_prompt"] is False
    assert identity["leanstral_failure_boundary_sha256"] == (
        boundary["receipt_sha256"]
    )


def test_pinned_provider_accepts_only_a_route_bound_raw_failure() -> None:
    request = _request()
    pinned_identity = {
        "endpoint": "http://127.0.0.1:8080/v1",
        "provider": "leanstral_local",
        "model": "exact-test-model",
        "cache_prompt": False,
    }
    output = adapters._leanstral_failure(
        request,
        safe_failure_class="resource_exhausted",
        pinned_identity=pinned_identity,
    )

    class Provider:
        @staticmethod
        def prove(_request: object) -> object:
            return output

    record = adapters.LeanstralAdapter(
        provider=adapters._RequestIsolatedLeanstralProvider(
            Provider,
            pinned_identity=pinned_identity,
        )
    ).run(request)

    assert record.status is contracts.StageStatus.FAILED
    assert record.data["safe_failure_class"] == "resource_exhausted"
    assert record.data["generation_failure_boundary"] == (
        output.data["generation_failure_boundary"]
    )


@pytest.mark.parametrize("forged_route", [False, True])
def test_pinned_provider_rejects_missing_or_forged_raw_failure_identity(
    forged_route: bool,
) -> None:
    request = _request()
    pinned_identity = {
        "endpoint": "http://127.0.0.1:8080/v1",
        "provider": "leanstral_local",
        "model": "exact-test-model",
        "cache_prompt": False,
    }
    wrong_identity = {
        **pinned_identity,
        "endpoint": "http://127.0.0.1:9090/v1",
        "model": "substituted-model",
    }
    output = adapters._leanstral_failure(
        request,
        safe_failure_class="timed_out",
        pinned_identity=wrong_identity if forged_route else None,
    )

    class Provider:
        @staticmethod
        def prove(_request: object) -> object:
            return output

    record = adapters.LeanstralAdapter(
        provider=adapters._RequestIsolatedLeanstralProvider(
            Provider,
            pinned_identity=pinned_identity,
        )
    ).run(request)

    assert record.status is contracts.StageStatus.FAILED
    assert record.data["safe_failure_class"] == "malformed_response"
    boundary = record.data["generation_failure_boundary"]
    assert boundary["endpoint"] == pinned_identity["endpoint"]
    assert boundary["provider"] == pinned_identity["provider"]
    assert boundary["requested_model"] == pinned_identity["model"]
    assert boundary["cache_prompt"] is False
    identity = record.provenance.effective_identity
    assert identity["endpoint"] == pinned_identity["endpoint"]
    assert identity["provider"] == pinned_identity["provider"]
    assert identity["model"] == pinned_identity["model"]
    assert identity["cache_prompt"] is False
    if forged_route:
        serialized = contracts.canonical_json(record.to_dict())
        assert wrong_identity["endpoint"] not in serialized
        assert wrong_identity["model"] not in serialized


def test_strict_live_generator_pins_endpoint_model_and_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "http://127.0.0.1:8080/v1"
    provider = "leanstral_local"
    model = "exact-test-model"
    calls: list[tuple[str, bytes | None]] = []
    timeouts: list[float] = []
    monotonic = iter((100.0, 101.0, 105.0))

    class Response:
        def __init__(self, value: object, url: str) -> None:
            self._raw = json.dumps(value).encode("utf-8")
            self._url = url

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, maximum: int) -> bytes:
            return self._raw[:maximum]

        def geturl(self) -> str:
            return self._url

    raw_output = json.dumps(
        {
            "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
            "theorem_id": "hssl_test",
            "proposal_kind": "proof",
            "proof_text": "by\n  rfl",
        }
    )
    expected_output = {
        "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
        "theorem_id": "hssl_test",
        "proposal_kind": "proof",
        "proof_text": "rfl",
    }

    def urlopen(request: object, *, timeout: float) -> Response:
        timeouts.append(timeout)
        calls.append((request.full_url, request.data))
        if request.full_url.endswith("/models"):
            return Response(
                {"data": [{"id": model}]}, request.full_url
            )
        payload = json.loads(request.data.decode("utf-8"))
        schema = payload["response_format"]["json_schema"]["schema"]
        assert payload["model"] == model
        assert payload["stream"] is False
        assert payload["cache_prompt"] is False
        assert payload["seed"] == 0
        assert payload["messages"][0]["role"] == "system"
        assert "tactic body" in payload["messages"][0]["content"]
        assert "already in scope" in payload["messages"][0]["content"]
        assert "explanatory comments" in payload["messages"][0]["content"]
        assert payload["stop"] == [
            "<|tool_call_end|>",
            "<|im_end|>",
            "<|im_start|>",
        ]
        assert schema["properties"]["theorem_id"] == {"const": "hssl_test"}
        assert schema["properties"]["schema"] == {
            "const": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
        }
        return Response(
            {
                "model": model,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": raw_output},
                    }
                ],
            },
            request.full_url,
        )

    monkeypatch.setattr(adapters, "_leanstral_urlopen", urlopen)
    monkeypatch.setattr(adapters.time, "monotonic", lambda: next(monotonic))
    generate = adapters.create_pinned_leanstral_llm_generate(
        endpoint=endpoint,
        provider=provider,
        model=model,
    )
    prompt = json.dumps(
        {
            "fixed_theorem": {"theorem_id": "hssl_test"},
            "output_schema": {
                "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
            },
        }
    )

    generated = generate(
        prompt,
        provider=provider,
        model_name=model,
        timeout=30.0,
        max_new_tokens=64,
        allow_local_fallback=False,
        disable_model_retry=True,
        temperature=0.0,
    )
    assert json.loads(generated) == expected_output
    receipt = generate.consume_receipt(
        hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    )
    assert receipt is not None
    assert receipt["schema"] == adapters.LEANSTRAL_GENERATION_BOUNDARY_SCHEMA
    assert receipt["endpoint"] == endpoint
    assert receipt["requested_model"] == model
    assert receipt["response_model"] == model
    assert receipt["cache_prompt"] is False
    assert receipt["normalization"] == "strip_single_leading_by"
    assert receipt["raw_model_content_sha256"] == hashlib.sha256(
        raw_output.encode("utf-8")
    ).hexdigest()
    assert receipt["normalized_proposal_sha256"] == hashlib.sha256(
        generated.encode("utf-8")
    ).hexdigest()
    assert receipt["request_payload_sha256"] == hashlib.sha256(
        calls[1][1]
    ).hexdigest()
    receipt_body = {
        key: value
        for key, value in receipt.items()
        if key != "receipt_sha256"
    }
    assert receipt["receipt_sha256"] == hashlib.sha256(
        contracts.canonical_json(receipt_body).encode("utf-8")
    ).hexdigest()
    assert calls == [
        (f"{endpoint}/models", None),
        (f"{endpoint}/chat/completions", calls[1][1]),
    ]
    assert timeouts == [29.0, 25.0]


def _audited_provider_draft(
    prompt_sha256: str,
    proof_text: str,
) -> dict[str, object]:
    return {
        "proposal_schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
        "theorem_id": "hssl_test",
        "proposal_kind": "proof",
        "draft_text": proof_text,
        "proof_text": proof_text,
        "prompt_sha256": prompt_sha256,
        "metadata": {},
    }


def _generation_receipt_for_draft(
    prompt_sha256: str,
    proof_text: str,
) -> dict[str, object]:
    normalized = json.dumps(
        {
            "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA,
            "theorem_id": "hssl_test",
            "proposal_kind": "proof",
            "proof_text": proof_text,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return adapters._content_addressed_receipt(
        {
            "schema": adapters.LEANSTRAL_GENERATION_BOUNDARY_SCHEMA,
            "endpoint": "http://127.0.0.1:8080/v1",
            "provider": "leanstral_local",
            "requested_model": "exact-test-model",
            "response_model": "exact-test-model",
            "cache_prompt": False,
            "prompt_sha256": prompt_sha256,
            "request_payload_sha256": hashlib.sha256(
                b"request-payload"
            ).hexdigest(),
            "response_envelope_sha256": hashlib.sha256(
                b"response-envelope"
            ).hexdigest(),
            "raw_model_content_sha256": hashlib.sha256(
                b"raw-model-content"
            ).hexdigest(),
            "raw_model_content_bytes": len(b"raw-model-content"),
            "normalized_proposal_sha256": hashlib.sha256(normalized).hexdigest(),
            "normalized_proposal_bytes": len(normalized),
            "normalization": "none",
        }
    )


def test_audited_provider_selects_exact_receipt_for_same_prompt() -> None:
    prompt_sha256 = hashlib.sha256(b"same prompt").hexdigest()
    generator = adapters._PinnedLeanstralGenerate(
        endpoint="http://127.0.0.1:8080/v1",
        provider="leanstral_local",
        model="exact-test-model",
    )
    calls = iter(("exact first", "exact second"))

    class Delegate:
        def prove(self, _request: object) -> dict[str, object]:
            proof_text = next(calls)
            receipt = _generation_receipt_for_draft(
                prompt_sha256, proof_text
            )
            generator._receipt_local.pending = (prompt_sha256, receipt)
            return _audited_provider_draft(prompt_sha256, proof_text)

    audited = adapters._AuditedLeanstralProvider(Delegate(), generator)
    first = audited.prove(object())
    second = audited.prove(object())

    assert first["metadata"]["benchmark_generation_boundary"] == (
        _generation_receipt_for_draft(prompt_sha256, "exact first")
    )
    assert second["metadata"]["benchmark_generation_boundary"] == (
        _generation_receipt_for_draft(prompt_sha256, "exact second")
    )
    assert generator.consume_receipt(prompt_sha256) is None


@pytest.mark.parametrize(
    "tamper",
    [
        lambda receipt: {**receipt, "prompt_sha256": "0" * 64},
        lambda receipt: {
            **receipt,
            "normalized_proposal_bytes": (
                int(receipt["normalized_proposal_bytes"]) + 1
            ),
        },
    ],
)
def test_audited_provider_rejects_tampered_generation_receipt(
    tamper,
) -> None:
    prompt_sha256 = hashlib.sha256(b"fixed prompt").hexdigest()
    draft = _audited_provider_draft(prompt_sha256, "exact target")
    generator = adapters._PinnedLeanstralGenerate(
        endpoint="http://127.0.0.1:8080/v1",
        provider="leanstral_local",
        model="exact-test-model",
    )
    receipt = tamper(
        _generation_receipt_for_draft(prompt_sha256, "exact target")
    )
    generator._receipt_local.pending = (prompt_sha256, receipt)

    class Delegate:
        @staticmethod
        def prove(_request: object) -> dict[str, object]:
            return draft

    audited = adapters._AuditedLeanstralProvider(Delegate(), generator)
    with pytest.raises(
        adapters.LeanstralAdapterContractError,
        match="does not match the returned draft",
    ):
        audited.prove(object())
    assert generator.consume_receipt(prompt_sha256) is None


def test_strict_live_generator_rejects_model_substitution_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def urlopen(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        return SimpleNamespace()

    monkeypatch.setattr(adapters, "_leanstral_urlopen", urlopen)
    generate = adapters.create_pinned_leanstral_llm_generate(
        endpoint="http://127.0.0.1:8080/v1",
        provider="leanstral_local",
        model="exact-test-model",
    )

    with pytest.raises(
        adapters.LeanstralGenerationFailure,
    ) as caught:
        generate(
            json.dumps(
                {
                    "fixed_theorem": {"theorem_id": "hssl_test"},
                    "output_schema": {
                        "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
                    },
                }
            ),
            provider="leanstral_local",
            model_name="substituted-model",
            timeout=30.0,
            max_new_tokens=64,
            allow_local_fallback=False,
            disable_model_retry=True,
            temperature=0.0,
        )
    assert caught.value.safe_failure_class == "malformed_request"
    assert called is False


def test_strict_live_generator_types_length_exhaustion_without_content_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "exact-test-model"
    secret = "DO_NOT_LEAK_MODEL_CONTENT"

    class Response:
        def __init__(self, value: object, url: str) -> None:
            self._raw = json.dumps(value).encode("utf-8")
            self._url = url

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, maximum: int) -> bytes:
            return self._raw[:maximum]

        def geturl(self) -> str:
            return self._url

    def urlopen(request: object, *, timeout: float) -> Response:
        del timeout
        if request.full_url.endswith("/models"):
            return Response(
                {"data": [{"id": model}]}, request.full_url
            )
        return Response(
            {
                "model": model,
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": secret},
                    }
                ],
            },
            request.full_url,
        )

    monkeypatch.setattr(adapters, "_leanstral_urlopen", urlopen)
    generate = adapters.create_pinned_leanstral_llm_generate(
        endpoint="http://127.0.0.1:8080/v1",
        provider="leanstral_local",
        model=model,
    )
    with pytest.raises(adapters.LeanstralGenerationFailure) as caught:
        generate(
            json.dumps(
                {
                    "fixed_theorem": {"theorem_id": "hssl_test"},
                    "output_schema": {
                        "schema": adapters.LEANSTRAL_PROOF_OUTPUT_SCHEMA
                    },
                }
            ),
            provider="leanstral_local",
            model_name=model,
            timeout=30.0,
            max_new_tokens=64,
            allow_local_fallback=False,
            disable_model_retry=True,
            temperature=0.0,
        )
    assert caught.value.safe_failure_class == "length_exhausted"
    assert secret not in str(caught.value)
    assert secret not in contracts.canonical_json(
        caught.value.boundary_receipt
    )


@pytest.mark.parametrize(
    ("status", "safe_failure_class"),
    [
        (404, "unavailable"),
        (429, "resource_exhausted"),
        (503, "provider_error"),
        (504, "timed_out"),
    ],
)
def test_http_failures_have_precise_secret_safe_boundary_receipts(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    safe_failure_class: str,
) -> None:
    secret = "DO_NOT_LEAK_HTTP_BODY"

    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "http://127.0.0.1:8080/v1/chat/completions",
            status,
            "provider detail",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(adapters, "_leanstral_urlopen", urlopen)
    request = adapters.urllib.request.Request(
        "http://127.0.0.1:8080/v1/chat/completions",
        data=secret.encode("utf-8"),
        method="POST",
    )
    with pytest.raises(adapters.LeanstralGenerationFailure) as caught:
        adapters._strict_leanstral_http_object(
            request,
            phase="completion_request",
            timeout_seconds=1.0,
            max_response_bytes=1024,
        )
    failure = caught.value
    assert failure.safe_failure_class == safe_failure_class
    assert failure.boundary_receipt["http_status"] == status
    assert failure.boundary_receipt["request_payload_sha256"] == (
        hashlib.sha256(secret.encode("utf-8")).hexdigest()
    )
    assert secret not in str(failure)
    assert secret not in contracts.canonical_json(failure.boundary_receipt)


def test_leanstral_http_opener_disables_proxies_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    class Opener:
        @staticmethod
        def open(request: object, *, timeout: float) -> object:
            return request, timeout

    def build_opener(*handlers: object) -> Opener:
        captured.extend(handlers)
        return Opener()

    monkeypatch.setattr(
        adapters.urllib.request, "build_opener", build_opener
    )
    request = adapters.urllib.request.Request(
        "http://127.0.0.1:8080/v1/models"
    )

    assert adapters._leanstral_urlopen(
        request, timeout=1.0
    ) == (request, 1.0)
    proxy = next(
        item
        for item in captured
        if isinstance(item, adapters.urllib.request.ProxyHandler)
    )
    redirect = next(
        item
        for item in captured
        if isinstance(item, adapters._LeanstralNoRedirect)
    )
    assert proxy.proxies == {}
    assert (
        redirect.redirect_request(
            request, None, 302, "redirect", {}, "http://evil.invalid"
        )
        is None
    )


def test_strict_http_rejects_changed_final_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def geturl() -> str:
            return "http://different.invalid/v1/models"

        @staticmethod
        def read(_maximum: int) -> bytes:
            return b'{"data":[]}'

    monkeypatch.setattr(
        adapters,
        "_leanstral_urlopen",
        lambda _request, *, timeout: Response(),
    )
    request = adapters.urllib.request.Request(
        "http://127.0.0.1:8080/v1/models"
    )
    with pytest.raises(
        adapters.LeanstralGenerationFailure
    ) as caught:
        adapters._strict_leanstral_http_object(
            request,
            phase="model_registry",
            timeout_seconds=1.0,
            max_response_bytes=1024,
        )
    assert caught.value.safe_failure_class == "provider_error"
    assert caught.value.boundary_receipt["phase"] == "model_registry"


def test_adapter_failure_receipt_types_are_bound_and_never_echo_exceptions() -> None:
    secret = "DO_NOT_LEAK_PROVIDER_EXCEPTION"
    record = _run(
        lambda _request: (_ for _ in ()).throw(
            adapters.LeanstralAdapterContractError(secret)
        )
    )

    assert record.status is contracts.StageStatus.FAILED
    assert record.data["safe_failure_class"] == "malformed_response"
    assert record.provenance.effective_identity[
        "leanstral_safe_failure_class"
    ] == "malformed_response"
    boundary = record.data["generation_failure_boundary"]
    body = {
        key: value
        for key, value in boundary.items()
        if key != "receipt_sha256"
    }
    assert boundary["receipt_sha256"] == hashlib.sha256(
        contracts.canonical_json(body).encode("utf-8")
    ).hexdigest()
    assert (
        record.provenance.effective_identity[
            "leanstral_failure_boundary_sha256"
        ]
        == boundary["receipt_sha256"]
    )
    assert secret not in record.failure_detail
    assert secret not in contracts.canonical_json(record.to_dict())


@pytest.mark.parametrize(
    ("phase", "safe_failure_class", "expected_model_calls"),
    [
        ("request_validation", "malformed_request", 0),
        ("model_registry", "unavailable", 0),
        ("completion_pre_dispatch", "timed_out", 0),
        ("completion_request", "provider_error", 1),
        ("completion_response", "length_exhausted", 1),
        ("proposal_validation", "inadmissible_proposal", 1),
    ],
)
def test_failure_boundary_phase_controls_model_call_telemetry(
    phase: str,
    safe_failure_class: str,
    expected_model_calls: int,
) -> None:
    record = _run(
        lambda _request: (_ for _ in ()).throw(
            adapters.LeanstralGenerationFailure(
                safe_failure_class,
                phase=phase,
            )
        )
    )

    assert record.data["safe_failure_class"] == safe_failure_class
    assert record.data["generation_failure_boundary"]["phase"] == phase
    assert record.telemetry.model_calls == expected_model_calls
    if safe_failure_class == "unavailable":
        assert record.status is contracts.StageStatus.UNAVAILABLE
        assert record.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE
    else:
        assert record.status is contracts.StageStatus.FAILED
        assert record.failure_code is (
            contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
        )


def test_failure_telemetry_retains_elapsed_wall_and_cpu_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wall = iter((10.0, 11.0, 13.5))
    cpu = iter((20.0, 21.0, 22.25))
    monkeypatch.setattr(
        adapters.time, "perf_counter", lambda: next(wall)
    )
    monkeypatch.setattr(
        adapters.time, "process_time", lambda: next(cpu)
    )

    record = _run(
        lambda _request: (_ for _ in ()).throw(TimeoutError())
    )

    assert record.status is contracts.StageStatus.FAILED
    assert record.telemetry.wall_time_ms == 2_500.0
    assert record.telemetry.cpu_time_ms == 1_250.0
    assert record.telemetry.model_calls == 1


@pytest.mark.parametrize(
    ("mutator", "safe_failure_class"),
    [
        (lambda draft: draft | {"schema_version": "wrong-schema"}, "malformed_response"),
        (lambda draft: draft | {"obligation_ids": ["other-obligation"]}, "malformed_response"),
        (
            lambda draft: draft
            | {"draft_text": "exact sorry", "proof_text": "exact sorry"},
            "inadmissible_proposal",
        ),
        (
            lambda draft: draft
            | {"draft_text": "by exact rfl", "proof_text": "by exact rfl"},
            "inadmissible_proposal",
        ),
        (
            lambda draft: draft
            | {
                "draft_text": "import Mathlib\ntheorem x : True := by\n  trivial",
                "proof_text": "import Mathlib\ntheorem x : True := by\n  trivial",
            },
            "inadmissible_proposal",
        ),
        (
            lambda draft: draft
            | {
                "draft_text": "```lean\nexact rfl\n```",
                "proof_text": "```lean\nexact rfl\n```",
            },
            "inadmissible_proposal",
        ),
        (
            lambda draft: draft | {"authoritative": True},
            "inadmissible_proposal",
        ),
    ],
)
def test_malformed_forbidden_or_authoritative_model_output_fails_closed(
    mutator,
    safe_failure_class: str,
) -> None:
    record = _run(lambda _request: mutator(_draft()))

    assert record.status is contracts.StageStatus.FAILED
    assert (
        record.failure_code
        is contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
    )
    assert record.data["safe_failure_class"] == safe_failure_class
    assert record.output_sha256 is None
    assert record.kernel_accepted is False


def test_nested_by_inside_a_tactic_body_is_not_rejected() -> None:
    text = "have h : True := by\n  trivial\nexact h"
    record = _run(lambda _request: _draft(text))

    assert record.status is contracts.StageStatus.SUCCESS
    assert record.data["draft"]["proof_text"] == text


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
