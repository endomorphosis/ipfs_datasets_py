"""Adversarial integration tests for the ITP hammer pipeline (HAMMER-014).

Complements ``test_end_to_end_hammer.py``'s golden happy-path/graceful-
degradation coverage with deliberately hostile inputs, covering the
remaining acceptance-criteria cases the taskboard calls out:

- Malformed proof trace -- a genuinely garbled TSTP derivation listing must
  resolve to ``EvidenceKind.MALFORMED`` / ``HammerResultStatus.UNKNOWN``,
  never a usable proof.
- Corrupted receipt -- tampering with a persisted
  :class:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt`'s on-disk
  payload must either be detected via digest mismatch
  (:func:`~ipfs_datasets_py.logic.hammers.receipts.compute_receipt_digest`)
  or, when the tamper attempts to forge a ``VERIFIED`` status, rejected
  outright by :class:`~ipfs_datasets_py.logic.hammers.models.HammerResult`'s
  own trust-boundary invariant.
- Premise-poisoning -- re-ingesting an existing corpus identity with a
  different statement must be rejected
  (``DuplicateTheoremIdentityError``), and citing a fabricated premise id
  that was never actually ingested must be rejected by
  :func:`~ipfs_datasets_py.logic.hammers.corpus.verify_hammer_result_corpus`
  (``CorpusRevisionMismatchError``).
- Cancellation -- when one allowlisted solver reaches a conclusive verdict
  first, every other still-running attempt must be genuinely cancelled
  (never fabricated as conclusive) and recorded as such.
- Hallucinated candidate premises / corrupted theorem statements -- a
  solver-claimed premise that does not correspond to a real local
  hypothesis, or a corrupted goal, must never let a real kernel accept a
  reconstruction (real Lean kernel, skipped if unavailable).
- LLM-suggested decomposition hints (HAMMER-011) remain redacted and
  untrusted (``SubgoalStatus`` never reaches ``VERIFIED``) purely from
  human review -- only an independent, passing kernel check could do that.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import json
import os
import shutil
import stat
import time
from pathlib import Path as _Path

import pytest

# See test_end_to_end_hammer.py's identical loader for why this is a
# file-path import rather than a package-relative one: the ``hammers``
# leaf test packages under ``tests/unit_tests/logic`` and
# ``tests/integration/logic`` collide on the same top-level module name
# under ``--import-mode=importlib``.
_helpers_spec = _importlib_util.spec_from_file_location(
    "ipfs_datasets_py_hammer_test_golden_helpers",
    _Path(__file__).resolve().with_name("_golden_helpers.py"),
)
gh = _importlib_util.module_from_spec(_helpers_spec)
_helpers_spec.loader.exec_module(gh)

from ipfs_datasets_py.logic.hammers.corpus import (
    CorpusRevisionMismatchError,
    DuplicateTheoremIdentityError,
    verify_hammer_result_corpus,
)
from ipfs_datasets_py.logic.hammers.fallbacks import (
    DecompositionSource,
    FallbackTrigger,
    ReviewStatus,
    SubgoalStatus,
    build_decomposition_plan,
    redact_llm_text,
    review_decomposition_subgoal,
)
from ipfs_datasets_py.logic.hammers.frontends.base import (
    CapabilityEvidence,
    GoalSnapshot,
    LocalHypothesis,
    SourcePosition,
    UniverseContext,
)
from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy,
    HammerRequest,
    HammerResult,
    HammerResultStatus,
    ITPKind,
    PremiseRecord,
    ProofCandidateRecord,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy
from ipfs_datasets_py.logic.hammers.portfolio import (
    PortfolioAttemptSpec,
    SolverPortfolio,
    SolverProcessOutcome,
)
from ipfs_datasets_py.logic.hammers.provenance import EvidenceKind, normalize_solver_evidence
from ipfs_datasets_py.logic.hammers.receipts import (
    HammerReceipt,
    ReceiptStore,
    compute_receipt_digest,
)

LEAN_AVAILABLE = shutil.which("lean") is not None


@pytest.fixture(scope="module")
def golden_manifest():
    return gh.load_golden_corpus_manifest()


# ---------------------------------------------------------------------------
# Malformed proof trace
# ---------------------------------------------------------------------------


class TestMalformedProofTrace:
    def test_malformed_tstp_trace_resolves_to_malformed_unknown(self):
        malformed_text = gh.MALFORMED_TSTP_PROOF_PATH.read_text(encoding="utf-8")
        attempt = SolverAttemptRecord(
            attempt_id="adversarial-malformed-1",
            request_id="adversarial-malformed-req",
            translation_id="adversarial-malformed-t1",
            solver_name="vampire",
            target=TranslationTarget.TPTP,
            verdict=SolverVerdict.PROVED,
        )
        normalized = normalize_solver_evidence(
            request_id="adversarial-malformed-req",
            attempt=attempt,
            raw_stdout=malformed_text,
            raw_stderr="",
        )
        assert normalized.kind == EvidenceKind.MALFORMED
        assert normalized.recommended_status is HammerResultStatus.UNKNOWN
        assert normalized.malformed_reason

    def test_malformed_evidence_can_never_back_a_proof_candidate(self):
        malformed_text = gh.MALFORMED_TSTP_PROOF_PATH.read_text(encoding="utf-8")
        attempt = SolverAttemptRecord(
            attempt_id="adversarial-malformed-2",
            request_id="adversarial-malformed-req",
            translation_id="adversarial-malformed-t1",
            solver_name="vampire",
            target=TranslationTarget.TPTP,
            verdict=SolverVerdict.PROVED,
        )
        normalized = normalize_solver_evidence(
            request_id="adversarial-malformed-req",
            attempt=attempt,
            raw_stdout=malformed_text,
            raw_stderr="",
        )
        from ipfs_datasets_py.logic.hammers.provenance import (
            MalformedEvidenceError,
            build_proof_candidate_record,
        )

        with pytest.raises(MalformedEvidenceError):
            build_proof_candidate_record(
                normalized,
                candidate_id="should-never-exist",
                request_id="adversarial-malformed-req",
                solver_attempt_id=attempt.attempt_id,
            )

    def test_unknown_status_result_never_claims_verified(self, golden_manifest):
        malformed_text = gh.MALFORMED_TSTP_PROOF_PATH.read_text(encoding="utf-8")
        corpus_revision = golden_manifest.revision
        request = gh.make_fixed_request(
            request_id="adversarial-malformed-result-1",
            theorem_id="hammer_adversarial_malformed",
            goal_statement="forall x, p(x) -> p(x)",
            corpus_revision=corpus_revision,
            policy=gh.make_fixed_policy(allowed_solvers=["vampire"]),
        )
        attempt = SolverAttemptRecord(
            attempt_id="adversarial-malformed-3",
            request_id=request.request_id,
            translation_id="adversarial-malformed-t1",
            solver_name="vampire",
            target=TranslationTarget.TPTP,
            verdict=SolverVerdict.PROVED,
            started_at=gh.FIXED_CREATED_AT,
            finished_at=gh.FIXED_COMPLETED_AT,
        )
        normalize_solver_evidence(
            request_id=request.request_id, attempt=attempt, raw_stdout=malformed_text, raw_stderr=""
        )

        result = HammerResult(
            result_id=f"{request.request_id}:result",
            request=request,
            status=HammerResultStatus.UNKNOWN,
            corpus_revision=corpus_revision,
            solver_attempts=[attempt],
            created_at=gh.FIXED_CREATED_AT,
            completed_at=gh.FIXED_COMPLETED_AT,
            notes=["solver trace was malformed; no usable candidate could be built"],
        )
        assert not result.is_verified()


# ---------------------------------------------------------------------------
# Corrupted receipt
# ---------------------------------------------------------------------------


class TestCorruptedReceipt:
    def _persist_candidate_receipt(self, golden_manifest, tmp_path):
        result, _normalized = gh.build_candidate_only_case(golden_manifest)
        receipt = HammerReceipt(result=result)
        store = ReceiptStore(root_dir=tmp_path / "receipts")
        persisted = store.put(receipt)
        return receipt, store, persisted

    def test_tampering_an_authoritative_field_is_detected_via_digest(
        self, golden_manifest, tmp_path
    ):
        receipt, store, persisted = self._persist_candidate_receipt(golden_manifest, tmp_path)
        raw = json.loads(open(persisted.full.path, encoding="utf-8").read())
        raw["result"]["request"]["goal_statement"] = "forall x, TAMPERED_GOAL(x)"
        with open(persisted.full.path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)

        reloaded = store.get(receipt.receipt_id)
        assert compute_receipt_digest(reloaded) != reloaded.receipt_id
        assert compute_receipt_digest(reloaded) != receipt.receipt_id

    def test_tampering_to_forge_verified_status_is_rejected_outright(
        self, golden_manifest, tmp_path
    ):
        receipt, store, persisted = self._persist_candidate_receipt(golden_manifest, tmp_path)
        raw = json.loads(open(persisted.full.path, encoding="utf-8").read())
        # Attempt to upgrade an untrusted CANDIDATE straight to VERIFIED
        # without ever adding a kernel-accepted ReconstructionRecord.
        raw["result"]["status"] = "verified"
        with open(persisted.full.path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)

        with pytest.raises(ValueError, match="VERIFIED"):
            store.get(receipt.receipt_id)

    def test_corrupted_json_payload_is_reported_not_silently_accepted(
        self, golden_manifest, tmp_path
    ):
        receipt, store, persisted = self._persist_candidate_receipt(golden_manifest, tmp_path)
        with open(persisted.full.path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not valid json ]")

        # A corrupted cache file falls through to "not found" (no crash, no
        # silent fabrication of receipt content) since the index has no
        # separate IPFS-backed copy to recover from in this test.
        from ipfs_datasets_py.logic.hammers.receipts import ReceiptNotFoundError

        with pytest.raises(ReceiptNotFoundError):
            store.get(receipt.receipt_id)


# ---------------------------------------------------------------------------
# Premise poisoning
# ---------------------------------------------------------------------------


class TestPremisePoisoning:
    def test_reingesting_existing_identity_with_different_statement_is_rejected(
        self, golden_manifest
    ):
        poison = gh.load_poisoned_premise_fixture()
        mutable_manifest = gh.load_golden_corpus_manifest()
        with pytest.raises(DuplicateTheoremIdentityError):
            mutable_manifest.add_theorem(
                theorem_id=poison["poisoned_theorem_id"],
                corpus_id=poison["poisoned_corpus_id"],
                statement=poison["poisoned_statement"],
                imports=poison["poisoned_imports"],
            )
        # The original, trusted entry must be completely untouched.
        assert mutable_manifest.revision == golden_manifest.revision

    def test_fabricated_premise_id_is_rejected_by_corpus_binding(self, golden_manifest):
        poison = gh.load_poisoned_premise_fixture()
        result, _normalized = gh.build_candidate_only_case(golden_manifest)
        fabricated = PremiseRecord(
            premise_id=poison["fabricated_premise_id"],
            statement="a fabricated premise that was never actually ingested",
            source_itp=ITPKind.LEAN,
            corpus_revision=golden_manifest.revision,
            rank=99,
            score=0.0,
        )
        import dataclasses

        poisoned_result = dataclasses.replace(
            result, premises=list(result.premises) + [fabricated]
        )
        with pytest.raises(CorpusRevisionMismatchError):
            verify_hammer_result_corpus(poisoned_result, golden_manifest)

    def test_premise_with_mismatched_corpus_revision_is_rejected(self, golden_manifest):
        result, _normalized = gh.build_candidate_only_case(golden_manifest)
        wrong_revision_premise = PremiseRecord(
            premise_id=result.premises[0].premise_id,
            statement=result.premises[0].statement,
            source_itp=result.premises[0].source_itp,
            corpus_revision="sha256:0000000000000000000000000000000000000000000000000000000000000",
            rank=0,
            score=1.0,
        )
        import dataclasses

        poisoned_result = dataclasses.replace(
            result, premises=[wrong_revision_premise] + list(result.premises[1:])
        )
        with pytest.raises(CorpusRevisionMismatchError):
            verify_hammer_result_corpus(poisoned_result, golden_manifest)

    def test_a_hallucinated_candidate_premise_never_fools_verify_hammer_result_corpus(
        self, golden_manifest
    ):
        """Even a *reconstructed and kernel-verified* result must still be
        rejected by corpus binding if one of its cited premises is
        fabricated -- kernel acceptance of the *proof* is orthogonal to
        whether the corpus-provenance bookkeeping itself was poisoned."""

        result, _normalized = gh.build_candidate_only_case(golden_manifest)
        import dataclasses

        fabricated = PremiseRecord(
            premise_id="Hammer.Nat.completely_hallucinated_by_llm",
            statement="theorem completely_hallucinated : False",
            source_itp=ITPKind.LEAN,
            corpus_revision=golden_manifest.revision,
            rank=0,
            score=99.0,
        )
        poisoned = dataclasses.replace(result, premises=[fabricated])
        with pytest.raises(CorpusRevisionMismatchError):
            verify_hammer_result_corpus(poisoned, golden_manifest)


@pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available in this environment")
class TestHallucinatedPremiseAgainstRealKernel:
    """A solver-claimed premise id that does not correspond to any real
    local hypothesis, applied to a corrupted (false) theorem statement,
    must never let the real Lean kernel accept a reconstruction."""

    def test_hallucinated_premise_on_corrupted_goal_is_rejected_by_real_kernel(self):
        from ipfs_datasets_py.logic.hammers.frontends import LeanFrontend
        from ipfs_datasets_py.logic.hammers.reconstructors.lean import LeanReconstructor

        source = gh.LEAN_VERIFIED_CORRUPT_PATH.read_text(encoding="utf-8")
        theorem_id = "hammer_golden_corrupt"
        snapshot = LeanFrontend().snapshot_goal(source, theorem_id=theorem_id)
        request = HammerRequest(
            request_id="adversarial-hallucinated-premise-1",
            itp=ITPKind.LEAN,
            theorem_id=theorem_id,
            goal_statement=snapshot.goal_text,
            corpus_revision="corpus-rev-adversarial",
            policy=gh.make_fixed_policy(),
        )
        candidate = ProofCandidateRecord(
            candidate_id="hallucinated-premise-candidate",
            request_id=request.request_id,
            solver_attempt_id="fake-solver-attempt",
            premise_ids=["h", "totally_fabricated_lemma_the_solver_never_used"],
        )

        record, _evidence, _lock = LeanReconstructor().reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=source,
        )
        assert record.kernel_accepted is False
        assert record.failure_reason

        with pytest.raises(ValueError):
            HammerResult(
                result_id="adversarial-hallucinated-result",
                request=request,
                status=HammerResultStatus.VERIFIED,
                corpus_revision=request.corpus_revision,
                proof_candidate=candidate,
                reconstruction=record,
            )


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def _make_fake_executable(path) -> str:
    path = str(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestCancellation:
    def test_other_attempts_are_genuinely_cancelled_on_first_conclusive_verdict(self, tmp_path):
        fake_vampire = _make_fake_executable(tmp_path / "vampire")
        fake_e = _make_fake_executable(tmp_path / "eprover")

        from ipfs_datasets_py.logic.hammers.translation import TranslationContext

        ctx = TranslationContext(request_id="cancel-req")
        translation = ctx.translate(
            source_construct="goal", term=gh.tautology_term(), target=TranslationTarget.TPTP
        )

        policy = PortfolioPolicy(
            hammer_policy=HammerPolicy(timeout_seconds=10.0, allowed_solvers=["vampire", "e"]),
            executable_overrides={"vampire": fake_vampire, "e": fake_e},
            cancel_on_first_conclusive=True,
        )

        def _runner(command, *, budget, cancel_event=None):
            exe_name = os.path.basename(command[0])
            if exe_name == "eprover":
                return SolverProcessOutcome(
                    command=command, stdout="% SZS status Theorem for cancel-req\n"
                )
            start = time.monotonic()
            while time.monotonic() - start < 2.0:
                if cancel_event is not None and cancel_event.is_set():
                    return SolverProcessOutcome(
                        command=command,
                        cancelled=True,
                        wall_time_seconds=time.monotonic() - start,
                    )
                time.sleep(0.005)
            return SolverProcessOutcome(
                command=command, stdout="% SZS status Timeout\n", wall_time_seconds=2.0
            )

        portfolio = SolverPortfolio(policy, process_runner=_runner, version_prober=lambda *_: None)
        result = portfolio.run(
            "cancel-req",
            [
                PortfolioAttemptSpec(translation=translation, solver_name="vampire"),
                PortfolioAttemptSpec(translation=translation, solver_name="e"),
            ],
        )

        assert len(result.attempts) == 2
        by_solver = {a.solver_name: a for a in result.attempts}
        assert by_solver["e"].verdict is SolverVerdict.PROVED
        assert by_solver["vampire"].verdict is SolverVerdict.UNKNOWN
        assert result.cancelled_attempt_ids == [by_solver["vampire"].attempt_id]

        # A cancelled attempt must never be fabricated as conclusive.
        assert by_solver["vampire"].verdict not in {
            SolverVerdict.SAT,
            SolverVerdict.UNSAT,
            SolverVerdict.PROVED,
            SolverVerdict.DISPROVED,
        }

    def test_cancellation_can_be_disabled_and_all_attempts_run_to_completion(self, tmp_path):
        fake_vampire = _make_fake_executable(tmp_path / "vampire")
        fake_e = _make_fake_executable(tmp_path / "eprover")

        from ipfs_datasets_py.logic.hammers.translation import TranslationContext

        ctx = TranslationContext(request_id="no-cancel-req")
        translation = ctx.translate(
            source_construct="goal", term=gh.tautology_term(), target=TranslationTarget.TPTP
        )

        policy = PortfolioPolicy(
            hammer_policy=HammerPolicy(timeout_seconds=10.0, allowed_solvers=["vampire", "e"]),
            executable_overrides={"vampire": fake_vampire, "e": fake_e},
            cancel_on_first_conclusive=False,
        )

        def _runner(command, *, budget, cancel_event=None):
            return SolverProcessOutcome(
                command=command, stdout="% SZS status Theorem for no-cancel-req\n"
            )

        portfolio = SolverPortfolio(policy, process_runner=_runner, version_prober=lambda *_: None)
        result = portfolio.run(
            "no-cancel-req",
            [
                PortfolioAttemptSpec(translation=translation, solver_name="vampire"),
                PortfolioAttemptSpec(translation=translation, solver_name="e"),
            ],
        )
        assert result.cancelled_attempt_ids == []
        assert len(result.attempts) == 2
        assert all(a.verdict is SolverVerdict.PROVED for a in result.attempts)


# ---------------------------------------------------------------------------
# LLM-suggested decomposition hints remain untrusted (HAMMER-011)
# ---------------------------------------------------------------------------


class TestLLMDecompositionHintsRemainUntrusted:
    def _make_snapshot(self) -> GoalSnapshot:
        return GoalSnapshot(
            itp=ITPKind.LEAN,
            itp_version="synthetic",
            theorem_id="hammer_adversarial_decomposition",
            goal_text="n = n",
            hypotheses=[LocalHypothesis(names=["n"], type_text="Nat", raw="n : Nat")],
            imports=[],
            universe_context=UniverseContext(),
            source_position=SourcePosition(file="Goal.lean", line=1, column=0),
            native_command=["lean", "Goal.lean"],
            raw_native_output="context:\nn : Nat\n\u22a2 n = n",
        )

    def _make_request(self, **policy_overrides) -> HammerRequest:
        defaults = dict(
            timeout_seconds=20.0,
            allowed_solvers=[],
            allow_llm_decomposition_hints=True,
            max_decomposition_subgoals=4,
        )
        defaults.update(policy_overrides)
        policy = HammerPolicy(**defaults)
        return HammerRequest(
            request_id="adversarial-decomp-1",
            itp=ITPKind.LEAN,
            theorem_id="hammer_adversarial_decomposition",
            goal_statement="n = n",
            corpus_revision="corpus-rev-adversarial",
            policy=policy,
        )

    def test_llm_suggestion_is_redacted_and_pending_review_by_default(self):
        request = self._make_request()
        snapshot = self._make_snapshot()

        def llm_provider(_snapshot):
            return ["n = n  -- trust me, this is obviously true"]

        plan = build_decomposition_plan(
            request=request,
            trigger=FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=llm_provider,
        )
        assert len(plan.subgoals) == 1
        subgoal = plan.subgoals[0]
        assert subgoal.source is DecompositionSource.LLM_SUGGESTED
        assert subgoal.review_status is ReviewStatus.PENDING_REVIEW
        assert subgoal.status is SubgoalStatus.PENDING
        assert subgoal.redacted_suggestion == redact_llm_text(
            "n = n  -- trust me, this is obviously true"
        )
        # The redacted placeholder must never leak the raw suggestion text.
        assert "trust me" not in subgoal.redacted_suggestion

    def test_approval_alone_never_promotes_a_subgoal_to_verified(self):
        request = self._make_request()
        snapshot = self._make_snapshot()

        def llm_provider(_snapshot):
            return ["n = n"]

        plan = build_decomposition_plan(
            request=request,
            trigger=FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=llm_provider,
        )
        subgoal = plan.subgoals[0]
        review_decomposition_subgoal(subgoal, approve=True, reviewer="a-human-reviewer")
        assert subgoal.review_status is ReviewStatus.REVIEWED
        # Approval alone must never advance verification status -- only an
        # independent, passing kernel check (verify_decomposition_subgoal)
        # may do that, and it was never invoked here.
        assert subgoal.status is SubgoalStatus.PENDING
        assert subgoal.status is not SubgoalStatus.VERIFIED

    def test_rejected_llm_suggestion_can_never_be_verified(self):
        request = self._make_request()
        snapshot = self._make_snapshot()

        def llm_provider(_snapshot):
            return ["totally fabricated and false subgoal"]

        plan = build_decomposition_plan(
            request=request,
            trigger=FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=llm_provider,
        )
        subgoal = plan.subgoals[0]
        review_decomposition_subgoal(subgoal, approve=False, reviewer="a-human-reviewer")
        assert subgoal.review_status is ReviewStatus.REJECTED
        assert subgoal.status is SubgoalStatus.REJECTED

    def test_disabled_llm_hints_are_ignored_entirely(self):
        request = self._make_request(allow_llm_decomposition_hints=False)
        snapshot = self._make_snapshot()

        def llm_provider(_snapshot):
            return ["should never be included"]

        plan = build_decomposition_plan(
            request=request,
            trigger=FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=llm_provider,
        )
        assert plan.subgoals == []
        assert any("ignored" in note for note in plan.notes)
