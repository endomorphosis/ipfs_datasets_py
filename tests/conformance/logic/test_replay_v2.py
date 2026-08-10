"""Conformance: process-backed vertical slices, differential, replay (LFP2-046).

Interfaces: ``LogicEvidenceReplay@1``, ``ExecutableVerticalSliceReceipt@1``

Acceptance (fail-closed):

* Static or hermetic metadata cannot satisfy ExecutableVerticalSliceReceipt@1
* Disagreement is preserved (typed inconclusive; never majority-voted)
* Every authority-bearing result has independent replay/reconstruction or a
  typed ceiling that forbids promotion

Evidence subset: differential model core trace attack witness proof
reconstruction replay
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ipfs_datasets_py.logic.conformance.matrix import AuthorityCeiling
from ipfs_datasets_py.logic.conformance.replay_v2 import (
    AUTHORITY_DISPOSITION_SCHEMA,
    DIFFERENTIAL_ALIGNMENT_CASE_SCHEMA,
    EVIDENCE_REPLAY_CASE_SCHEMA,
    EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE,
    EXECUTABLE_VERTICAL_SLICE_RECEIPT_SCHEMA,
    GOAL_ID,
    LOGIC_EVIDENCE_REPLAY_INTERFACE,
    LOGIC_EVIDENCE_REPLAY_SCHEMA,
    PROGRAM_ID,
    REPLAYABLE_EVIDENCE_KINDS,
    REQUIRED_EVIDENCE_SUBSET,
    TASK_ID,
    VERTICAL_SLICE_STAGES,
    AuthorityDisposition,
    AuthorityDispositionKind,
    AuthorityPromotionError,
    DEFAULT_LOGIC_EVIDENCE_REPLAY,
    DifferentialAlignmentCase,
    DifferentialJoinVerdict,
    EvidenceReplayCase,
    ExecutableSliceClaimError,
    ExecutableVerticalSliceReceipt,
    LogicEvidenceReplay,
    LogicEvidenceReplayReport,
    ProcessBackingKind,
    ReplayCaseDisposition,
    ReplayV2Error,
    SliceDisposition,
    SliceStageRecord,
    authority_promotion_allowed,
    build_authority_dispositions,
    build_differential_alignment_corpus,
    build_evidence_replay_corpus,
    build_executable_vertical_slice_receipt,
    build_logic_evidence_replay_report,
    build_stage_pipeline,
    build_vertical_slice_receipts,
    classify_differential_pair,
    command_digest,
    environment_digest,
    establishes_executable_vertical_slice,
    output_digest,
    require_executable_vertical_slice_claim,
    resolve_authority_disposition,
    run_pinned_process_probe,
    stage_digest,
    tool_digest,
)


# ---------------------------------------------------------------------------
# Interface / identity
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert LOGIC_EVIDENCE_REPLAY_INTERFACE == "LogicEvidenceReplay@1"
    assert (
        EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE
        == "ExecutableVerticalSliceReceipt@1"
    )
    assert TASK_ID == "LFP2-046"
    assert GOAL_ID == "LFP2-G080"
    assert PROGRAM_ID == "ipfs-datasets-logic-family-parser-v2"
    orchestrator = LogicEvidenceReplay()
    assert orchestrator.interface == LOGIC_EVIDENCE_REPLAY_INTERFACE
    assert DEFAULT_LOGIC_EVIDENCE_REPLAY.interface == LOGIC_EVIDENCE_REPLAY_INTERFACE


def test_report_interface_and_content_addressing() -> None:
    first = build_logic_evidence_replay_report()
    second = build_logic_evidence_replay_report()
    assert first.interface == LOGIC_EVIDENCE_REPLAY_INTERFACE
    assert first.schema_version == LOGIC_EVIDENCE_REPLAY_SCHEMA
    assert first.task_id == TASK_ID
    assert first.goal_id == GOAL_ID
    assert first.content_id == f"sha256:{first.content_sha256}"
    assert first.to_json() == second.to_json()
    assert first.content_sha256 == second.content_sha256
    wire = json.loads(first.to_json())
    assert wire["interface"] == "LogicEvidenceReplay@1"
    assert wire["task_id"] == "LFP2-046"
    assert set(wire["evidence_subset"]) >= set(REQUIRED_EVIDENCE_SUBSET)


def test_report_identity_is_stable_across_ambient_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/tmp/ambient-home-a")
    first_observation = run_pinned_process_probe(candidates=("true", "echo"))
    first = build_logic_evidence_replay_report()

    monkeypatch.setenv("HOME", "/tmp/ambient-home-b")
    second_observation = run_pinned_process_probe(candidates=("true", "echo"))
    second = build_logic_evidence_replay_report()

    expected_environment_digest = environment_digest(
        {
            "HOME": "/nonexistent/ipfs-datasets-logic-replay",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin",
        }
    )
    assert first_observation["environment_digest"] == expected_environment_digest
    assert second_observation["environment_digest"] == expected_environment_digest
    assert first.content_id == second.content_id
    assert first.to_json() == second.to_json()


def test_required_evidence_subset_complete() -> None:
    report = build_logic_evidence_replay_report()
    for required in (
        "differential",
        "model",
        "core",
        "trace",
        "attack",
        "witness",
        "proof",
        "reconstruction",
        "replay",
    ):
        assert required in report.evidence_subset


# ---------------------------------------------------------------------------
# Static / hermetic metadata cannot satisfy ExecutableVerticalSliceReceipt@1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "backing",
    [
        ProcessBackingKind.METADATA_ONLY,
        ProcessBackingKind.MOCK,
        ProcessBackingKind.HERMETIC_FIXTURE,
        ProcessBackingKind.STATIC_DECLARATION,
        ProcessBackingKind.UNAVAILABLE,
    ],
)
def test_non_process_backing_never_establishes_executable_slice(
    backing: ProcessBackingKind,
) -> None:
    assert not establishes_executable_vertical_slice(
        process_backing=backing,
        process_executed=True,
        execution_claimed=True,
    )
    assert not establishes_executable_vertical_slice(
        process_backing=backing,
        process_executed=False,
        execution_claimed=False,
    )
    with pytest.raises(ExecutableSliceClaimError):
        require_executable_vertical_slice_claim(
            process_backing=backing,
            process_executed=True,
            execution_claimed=True,
        )


@pytest.mark.parametrize(
    "backing",
    [
        ProcessBackingKind.METADATA_ONLY,
        ProcessBackingKind.MOCK,
        ProcessBackingKind.HERMETIC_FIXTURE,
        ProcessBackingKind.STATIC_DECLARATION,
    ],
)
def test_build_receipt_non_process_never_satisfied(
    backing: ProcessBackingKind,
) -> None:
    receipt = build_executable_vertical_slice_receipt(
        receipt_id=f"slice:test.{backing.value}",
        domain_id="software_verification",
        family_id="first_order",
        provider_id="z3",
        process_backing=backing,
        authority_ceiling=AuthorityCeiling.CANDIDATE.value,
    )
    assert receipt.executable_slice_satisfied is False
    assert receipt.execution_claimed is False
    assert receipt.process_executed is False
    assert receipt.interface == EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE
    assert receipt.schema_version == EXECUTABLE_VERTICAL_SLICE_RECEIPT_SCHEMA
    with pytest.raises(ExecutableSliceClaimError):
        receipt.require_executable_slice()


def test_hermetic_cannot_force_satisfied_flag() -> None:
    stages = build_stage_pipeline(
        domain_id="software_verification",
        family_id="first_order",
        provider_id="z3",
        source_text="true",
        translation_id="id",
        compile_digest="a" * 64,
        process_output_digest="b" * 64,
        decoded_evidence_digest="c" * 64,
        replay_or_reconstruction_digest="d" * 64,
    )
    # Craft digests for empty command / env.
    empty_cmd_digest = command_digest(())
    env_d = environment_digest({"PATH": "/usr/bin"})
    tool_d = tool_digest(executable_path="", tool_id="hermetic")
    out_d = output_digest(stdout="fixture", stderr="", returncode=0)
    with pytest.raises(ExecutableSliceClaimError):
        ExecutableVerticalSliceReceipt(
            receipt_id="slice:forced.hermetic",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="z3",
            process_backing=ProcessBackingKind.HERMETIC_FIXTURE,
            disposition=SliceDisposition.EXECUTABLE,
            stages=stages,
            command=(),
            command_digest=empty_cmd_digest,
            environment_digest=env_d,
            tool_digest=tool_d,
            output_digest=out_d,
            process_executed=True,
            execution_claimed=True,
            executable_slice_satisfied=True,
            authority_ceiling=AuthorityCeiling.EXACT.value,
        )


def test_metadata_only_cannot_claim_execution() -> None:
    stages = build_stage_pipeline(
        domain_id="software_verification",
        family_id="first_order",
        provider_id="z3",
        source_text="true",
        translation_id="id",
        compile_digest="a" * 64,
        process_output_digest="b" * 64,
        decoded_evidence_digest="c" * 64,
        replay_or_reconstruction_digest="d" * 64,
    )
    with pytest.raises(ExecutableSliceClaimError):
        ExecutableVerticalSliceReceipt(
            receipt_id="slice:metadata.claim",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="z3",
            process_backing=ProcessBackingKind.METADATA_ONLY,
            disposition=SliceDisposition.METADATA_ONLY,
            stages=stages,
            command=(),
            command_digest=command_digest(()),
            environment_digest=environment_digest({}),
            tool_digest=tool_digest(executable_path="", tool_id="meta"),
            output_digest=output_digest(stdout="", stderr="", returncode=None),
            process_executed=True,
            execution_claimed=True,
            executable_slice_satisfied=False,
            authority_ceiling=AuthorityCeiling.NONE.value,
        )


def test_process_backed_probe_and_receipt() -> None:
    observation = run_pinned_process_probe(candidates=("true", "echo"))
    if not observation["process_executed"]:
        pytest.skip("no process binary available under validation PATH")
    assert establishes_executable_vertical_slice(
        process_backing=ProcessBackingKind.PINNED_BINARY,
        process_executed=True,
        execution_claimed=True,
    )
    receipt = build_executable_vertical_slice_receipt(
        receipt_id="slice:live.probe.z3",
        domain_id="software_verification",
        family_id="first_order",
        provider_id="z3",
        process_backing=ProcessBackingKind.PINNED_BINARY,
        process_observation=observation,
        independently_replayed=True,
        authority_ceiling=AuthorityCeiling.EXACT.value,
        evidence_kind="model",
    )
    assert receipt.executable_slice_satisfied is True
    assert receipt.process_executed is True
    assert receipt.execution_claimed is True
    assert receipt.command
    assert len(receipt.command_digest) == 64
    assert len(receipt.environment_digest) == 64
    assert len(receipt.tool_digest) == 64
    assert len(receipt.output_digest) == 64
    assert [stage.stage for stage in receipt.stages] == list(VERTICAL_SLICE_STAGES)
    admitted = receipt.require_executable_slice()
    assert admitted.receipt_id == receipt.receipt_id


def test_vertical_slice_pipeline_stages_complete_and_ordered() -> None:
    stages = build_stage_pipeline(
        domain_id="crypto_ir",
        family_id="cryptographic_protocol",
        provider_id="proverif",
        source_text="free c:channel.",
        translation_id="applied_pi",
        compile_digest="1" * 64,
        process_output_digest="2" * 64,
        decoded_evidence_digest="3" * 64,
        replay_or_reconstruction_digest="4" * 64,
        authority_ceiling=AuthorityCeiling.PROTOCOL_SYMBOLIC.value,
    )
    assert tuple(item.stage for item in stages) == VERTICAL_SLICE_STAGES
    assert all(isinstance(item, SliceStageRecord) for item in stages)
    # Digests are deterministic.
    again = build_stage_pipeline(
        domain_id="crypto_ir",
        family_id="cryptographic_protocol",
        provider_id="proverif",
        source_text="free c:channel.",
        translation_id="applied_pi",
        compile_digest="1" * 64,
        process_output_digest="2" * 64,
        decoded_evidence_digest="3" * 64,
        replay_or_reconstruction_digest="4" * 64,
        authority_ceiling=AuthorityCeiling.PROTOCOL_SYMBOLIC.value,
    )
    assert [item.digest for item in stages] == [item.digest for item in again]


def test_incomplete_stage_pipeline_rejected() -> None:
    stages = build_stage_pipeline(
        domain_id="software_verification",
        family_id="first_order",
        provider_id="z3",
        source_text="true",
        translation_id="id",
        compile_digest="a" * 64,
        process_output_digest="b" * 64,
        decoded_evidence_digest="c" * 64,
        replay_or_reconstruction_digest="d" * 64,
    )
    incomplete = stages[:-1]
    with pytest.raises(ReplayV2Error, match="complete ordered pipeline"):
        ExecutableVerticalSliceReceipt(
            receipt_id="slice:incomplete",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="z3",
            process_backing=ProcessBackingKind.HERMETIC_FIXTURE,
            disposition=SliceDisposition.HERMETIC_ONLY,
            stages=incomplete,
            command=(),
            command_digest=command_digest(()),
            environment_digest=environment_digest({}),
            tool_digest=tool_digest(executable_path="", tool_id="x"),
            output_digest=output_digest(stdout="", stderr="", returncode=None),
            authority_ceiling=AuthorityCeiling.CANDIDATE.value,
        )


# ---------------------------------------------------------------------------
# Disagreement is preserved
# ---------------------------------------------------------------------------


def test_disagreement_is_typed_inconclusive() -> None:
    raw, join = classify_differential_pair("sat", "unsat")
    assert raw == "disagree"
    assert join == DifferentialJoinVerdict.INCONCLUSIVE.value
    case = DifferentialAlignmentCase(
        case_id="smt.disagree.test",
        family="smt",
        fragment="qf_uf",
        left_provider="z3",
        right_provider="cvc5",
        left_verdict="sat",
        right_verdict="unsat",
        raw_classification=raw,
        join_verdict=join,
    )
    assert case.disagreement_preserved is True
    assert case.join_verdict == "inconclusive"


def test_disagreement_cannot_be_majority_voted() -> None:
    with pytest.raises(ReplayV2Error, match="inconclusive"):
        DifferentialAlignmentCase(
            case_id="smt.bad.majority",
            family="smt",
            fragment="qf_uf",
            left_provider="z3",
            right_provider="cvc5",
            left_verdict="sat",
            right_verdict="unsat",
            raw_classification="disagree",
            join_verdict=DifferentialJoinVerdict.AGREE.value,
        )


def test_differential_corpus_preserves_all_disagreements() -> None:
    corpus = build_differential_alignment_corpus()
    assert corpus
    disagree = [item for item in corpus if item.raw_classification == "disagree"]
    assert disagree, "corpus must include disagreement cases"
    for item in disagree:
        assert item.join_verdict == DifferentialJoinVerdict.INCONCLUSIVE.value
        assert item.disagreement_preserved is True
    # Agreement and unavailable paths still present.
    assert any(item.raw_classification == "agree" for item in corpus)
    assert any("unavailable" in item.raw_classification for item in corpus)


def test_partial_unknown_is_inconclusive_not_vote() -> None:
    raw, join = classify_differential_pair("sat", "unknown")
    assert raw == "partial_unknown"
    assert join == DifferentialJoinVerdict.INCONCLUSIVE.value


def test_both_unavailable_stays_unavailable() -> None:
    raw, join = classify_differential_pair("unavailable", "timeout")
    assert raw == "both_unavailable"
    assert join == DifferentialJoinVerdict.UNAVAILABLE.value


# ---------------------------------------------------------------------------
# Authority-bearing results: replay/reconstruction or typed ceiling
# ---------------------------------------------------------------------------


def test_typed_ceiling_forbids_promotion() -> None:
    disp = resolve_authority_disposition(
        result_id="vampire.tstp",
        evidence_kind="tstp",
        authority_ceiling=AuthorityCeiling.CANDIDATE.value,
    )
    assert (
        disp.disposition
        is AuthorityDispositionKind.TYPED_CEILING_FORBIDS_PROMOTION
    )
    assert disp.promotion_forbidden is True
    assert not authority_promotion_allowed(
        authority_ceiling=AuthorityCeiling.CANDIDATE.value,
        independently_replayed=False,
        independently_reconstructed=False,
    )


def test_promotable_ceiling_without_evidence_raises() -> None:
    with pytest.raises(AuthorityPromotionError):
        resolve_authority_disposition(
            result_id="lean.orphan",
            evidence_kind="kernel_candidate",
            authority_ceiling=AuthorityCeiling.KERNEL.value,
            independently_replayed=False,
            independently_reconstructed=False,
        )


def test_independent_replay_closes_exact_authority() -> None:
    match = "a" * 64
    disp = resolve_authority_disposition(
        result_id="z3.model",
        evidence_kind="model",
        authority_ceiling=AuthorityCeiling.EXACT.value,
        independently_replayed=True,
        match_digest=match,
    )
    assert disp.disposition is AuthorityDispositionKind.INDEPENDENT_REPLAY
    assert authority_promotion_allowed(
        authority_ceiling=AuthorityCeiling.EXACT.value,
        independently_replayed=True,
        independently_reconstructed=False,
    )


def test_independent_reconstruction_closes_kernel_authority() -> None:
    disp = resolve_authority_disposition(
        result_id="lean.kernel",
        evidence_kind="kernel_candidate",
        authority_ceiling=AuthorityCeiling.KERNEL.value,
        independently_reconstructed=True,
        kernel_accepted=True,
    )
    assert (
        disp.disposition is AuthorityDispositionKind.INDEPENDENT_RECONSTRUCTION
    )
    assert authority_promotion_allowed(
        authority_ceiling=AuthorityCeiling.KERNEL.value,
        independently_replayed=False,
        independently_reconstructed=True,
        kernel_accepted=True,
    )
    # Reconstruction without kernel acceptance cannot promote.
    assert not authority_promotion_allowed(
        authority_ceiling=AuthorityCeiling.KERNEL.value,
        independently_replayed=False,
        independently_reconstructed=True,
        kernel_accepted=False,
    )


def test_replay_claimed_requires_matched_equal_digests() -> None:
    digest = "b" * 64
    case = EvidenceReplayCase(
        case_id="model.ok",
        evidence_kind="model",
        provider_id="z3",
        original_digest=digest,
        replayed_digest=digest,
        disposition=ReplayCaseDisposition.REPLAYED,
        matched=True,
        replay_claimed=True,
        authority_ceiling=AuthorityCeiling.EXACT.value,
    )
    assert case.replay_claimed is True
    with pytest.raises(ReplayV2Error, match="matched digests"):
        EvidenceReplayCase(
            case_id="model.bad",
            evidence_kind="model",
            provider_id="z3",
            original_digest=digest,
            replayed_digest=digest,
            disposition=ReplayCaseDisposition.REPLAYED,
            matched=False,
            replay_claimed=True,
            authority_ceiling=AuthorityCeiling.EXACT.value,
        )
    with pytest.raises(ReplayV2Error, match="equal digests|original==replayed"):
        EvidenceReplayCase(
            case_id="model.mismatch_claim",
            evidence_kind="model",
            provider_id="z3",
            original_digest=digest,
            replayed_digest="c" * 64,
            disposition=ReplayCaseDisposition.REPLAYED,
            matched=True,
            replay_claimed=True,
            authority_ceiling=AuthorityCeiling.EXACT.value,
        )


def test_reconstructed_requires_kernel_accepted() -> None:
    digest = "d" * 64
    with pytest.raises(ReplayV2Error, match="kernel_accepted"):
        EvidenceReplayCase(
            case_id="lean.no_kernel",
            evidence_kind="kernel_candidate",
            provider_id="lean",
            original_digest=digest,
            replayed_digest=digest,
            disposition=ReplayCaseDisposition.RECONSTRUCTED,
            matched=True,
            reconstructed=True,
            kernel_accepted=False,
            authority_ceiling=AuthorityCeiling.KERNEL.value,
        )


def test_evidence_replay_corpus_covers_required_kinds() -> None:
    corpus = build_evidence_replay_corpus()
    kinds = {item.evidence_kind for item in corpus}
    for required in (
        "model",
        "core",
        "trace",
        "attack",
        "witness",
        "proof",
        "tstp",
        "kernel_candidate",
    ):
        assert required in kinds
        assert required in REPLAYABLE_EVIDENCE_KINDS
    # At least one independent replay and one reconstruction.
    assert any(item.replay_claimed for item in corpus)
    assert any(item.reconstructed and item.kernel_accepted for item in corpus)
    # Ceiling-only cases present (no silent promotion).
    assert any(
        item.disposition is ReplayCaseDisposition.CEILING_ONLY for item in corpus
    )


def test_every_authority_disposition_is_closed() -> None:
    dispositions = build_authority_dispositions()
    assert dispositions
    for item in dispositions:
        assert isinstance(item, AuthorityDisposition)
        assert item.schema_version == AUTHORITY_DISPOSITION_SCHEMA
        assert item.disposition is not AuthorityDispositionKind.UNRESOLVED
        # Closed via replay, reconstruction, or typed ceiling.
        assert item.disposition in {
            AuthorityDispositionKind.INDEPENDENT_REPLAY,
            AuthorityDispositionKind.INDEPENDENT_RECONSTRUCTION,
            AuthorityDispositionKind.TYPED_CEILING_FORBIDS_PROMOTION,
        }


def test_process_satisfied_promotable_ceiling_requires_explicit_authority() -> None:
    observation = run_pinned_process_probe(candidates=("true", "echo"))
    if not observation["process_executed"]:
        pytest.skip("no process binary available under validation PATH")
    # Without independent replay/reconstruction, EXACT/KERNEL is forced down
    # to a non-promotable ceiling by the builder.
    receipt = build_executable_vertical_slice_receipt(
        receipt_id="slice:ceiling.fallback",
        domain_id="software_verification",
        family_id="first_order",
        provider_id="z3",
        process_backing=ProcessBackingKind.PINNED_BINARY,
        process_observation=observation,
        independently_replayed=False,
        independently_reconstructed=False,
        authority_ceiling=AuthorityCeiling.EXACT.value,
    )
    assert receipt.executable_slice_satisfied is True
    assert receipt.authority_ceiling == AuthorityCeiling.CANDIDATE.value
    assert (
        receipt.authority_disposition.disposition  # type: ignore[union-attr]
        is AuthorityDispositionKind.TYPED_CEILING_FORBIDS_PROMOTION
    )


# ---------------------------------------------------------------------------
# Joined report acceptance
# ---------------------------------------------------------------------------


def test_joined_report_acceptance_holds() -> None:
    report = build_logic_evidence_replay_report()
    assert report.acceptance_holds() is True
    summary = report.summary
    assert summary["disagree_all_preserved_inconclusive"] is True
    assert summary["non_process_slices_unsatisfied"] is True
    assert summary["every_authority_bearing_result_closed"] is True
    assert summary["replay_kinds_covered"] is True
    assert summary["differential_case_count"] > 0
    assert summary["replay_case_count"] > 0
    assert summary["vertical_slice_count"] > 0
    assert summary["non_process_slice_count"] > 0


def test_joined_report_non_process_slices_never_satisfied() -> None:
    report = build_logic_evidence_replay_report()
    non_process_kinds = {
        ProcessBackingKind.METADATA_ONLY,
        ProcessBackingKind.MOCK,
        ProcessBackingKind.HERMETIC_FIXTURE,
        ProcessBackingKind.STATIC_DECLARATION,
    }
    found = False
    for slice_receipt in report.vertical_slices:
        backing = slice_receipt.process_backing
        if isinstance(backing, ProcessBackingKind) and backing in non_process_kinds:
            found = True
            assert slice_receipt.executable_slice_satisfied is False
    assert found


def test_vertical_slice_receipts_include_fail_closed_kinds() -> None:
    receipts = build_vertical_slice_receipts()
    backings = {
        (
            item.process_backing.value
            if isinstance(item.process_backing, ProcessBackingKind)
            else str(item.process_backing)
        )
        for item in receipts
    }
    for required in (
        "hermetic_fixture",
        "metadata_only",
        "mock",
        "static_declaration",
    ):
        assert required in backings
    for item in receipts:
        if item.executable_slice_satisfied:
            assert item.process_backing in {
                ProcessBackingKind.LIVE_PROCESS,
                ProcessBackingKind.PINNED_BINARY,
            }
            assert item.command
            assert item.process_executed is True


def test_orchestrator_facade() -> None:
    orch = LogicEvidenceReplay()
    report = orch.build_report()
    assert isinstance(report, LogicEvidenceReplayReport)
    assert report.acceptance_holds()
    raw, join = orch.classify_pair("secure", "attack_found")
    assert raw == "disagree"
    assert join == "inconclusive"
    assert orch.establish_slice(
        process_backing=ProcessBackingKind.HERMETIC_FIXTURE,
        process_executed=True,
    ) is False
    assert orch.establish_slice(
        process_backing=ProcessBackingKind.PINNED_BINARY,
        process_executed=True,
    ) is True


def test_stage_digest_deterministic() -> None:
    first = stage_digest("parse", {"family_id": "first_order", "n": 1})
    second = stage_digest("parse", {"family_id": "first_order", "n": 1})
    third = stage_digest("parse", {"family_id": "first_order", "n": 2})
    assert first == second
    assert first != third
    assert len(first) == 64


def test_schema_constants_stable() -> None:
    assert DIFFERENTIAL_ALIGNMENT_CASE_SCHEMA.startswith("logic-evidence-")
    assert EVIDENCE_REPLAY_CASE_SCHEMA.startswith("logic-evidence-")
    assert AUTHORITY_DISPOSITION_SCHEMA.startswith("logic-evidence-")
    assert EXECUTABLE_VERTICAL_SLICE_RECEIPT_SCHEMA.startswith(
        "executable-vertical-slice"
    )


def test_report_rejects_wrong_task_id() -> None:
    with pytest.raises(ReplayV2Error, match="task_id"):
        LogicEvidenceReplayReport(
            task_id="LFP2-000",
            differential_cases=build_differential_alignment_corpus(),
            replay_cases=build_evidence_replay_corpus(),
            authority_dispositions=build_authority_dispositions(),
            vertical_slices=build_vertical_slice_receipts(),
            summary={"acceptance_holds": False},
        )


def test_wire_dict_round_trip_fields() -> None:
    report = build_logic_evidence_replay_report()
    payload = report.to_dict()
    assert payload["content_sha256"] == report.content_sha256
    for key in (
        "vertical_slices",
        "differential_cases",
        "replay_cases",
        "authority_dispositions",
        "evidence_subset",
        "summary",
    ):
        assert key in payload
    # Each vertical slice carries full pipeline stages.
    for slice_payload in payload["vertical_slices"]:
        assert slice_payload["interface"] == EXECUTABLE_VERTICAL_SLICE_RECEIPT_INTERFACE
        stages = slice_payload["stages"]
        assert [item["stage"] for item in stages] == list(VERTICAL_SLICE_STAGES)
        assert "authority_disposition" in slice_payload
        assert "command_digest" in slice_payload
        assert "environment_digest" in slice_payload
        assert "tool_digest" in slice_payload
        assert "output_digest" in slice_payload
