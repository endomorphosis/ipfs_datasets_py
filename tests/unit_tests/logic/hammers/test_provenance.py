"""Tests for normalizing proof traces and counterexample evidence (HAMMER-009).

These tests cover:
- Structural TSTP/TPTP derivation-listing normalization
  (:func:`parse_tstp_proof`): recovering step id/role/rule/parents/source
  name from ``file(...)``/``inference(...)`` annotations, deriving the used
  premise "unsat core" from leaf steps
  (:func:`unsat_core_from_proof_steps`), and fail-closed
  ``malformed_reason`` reporting for unbalanced parentheses or a missing
  terminating ``.``.
- Generic SMT-LIB s-expression parsing (:func:`parse_all_sexprs`) and its
  unsat-core/model interpretations (:func:`parse_smtlib_unsat_core`,
  :func:`parse_smtlib_model`), including malformed-input handling.
- The end-to-end :func:`normalize_solver_evidence` entry point across every
  :class:`~ipfs_datasets_py.logic.hammers.models.SolverVerdict`: proof,
  unsat-core, model, and counterexample evidence, an absent trace despite a
  conclusive verdict, a malformed trace, and the inconclusive
  verdicts (``UNKNOWN``/``TIMEOUT``/``ERROR``) that never produce evidence.
- Premise-id and :class:`~ipfs_datasets_py.logic.hammers.translation.
  TranslationMap` preservation/cross-referencing.
- The hard trust invariant: :class:`NormalizedEvidence` can never be
  constructed with ``recommended_status=HammerResultStatus.VERIFIED``, and
  every malformed/absent/unsupported-trace path always resolves to
  ``CANDIDATE`` or ``UNKNOWN``.
- Content-addressing (deterministic ``content_digest``/``evidence_id``) and
  ``to_dict``/``from_dict`` round-trips.
- :func:`build_proof_candidate_record` (including its refusal to build a
  candidate from non-``CANDIDATE`` evidence),
  :func:`normalize_portfolio_run`, and :func:`aggregate_recommended_status`.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.hammers.models import (
    HammerResultStatus,
    ProofCandidateRecord,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.portfolio import PortfolioRunResult, SolverAttemptEvidence
from ipfs_datasets_py.logic.hammers.provenance import (
    ALLOWED_RECOMMENDED_STATUSES,
    EvidenceKind,
    MalformedEvidenceError,
    ModelBinding,
    NormalizedEvidence,
    NormalizedModel,
    NormalizedUnsatCore,
    ProofStep,
    aggregate_recommended_status,
    build_proof_candidate_record,
    normalize_certificate,
    normalize_portfolio_run,
    normalize_solver_evidence,
    parse_all_sexprs,
    parse_smtlib_model,
    parse_smtlib_unsat_core,
    parse_tptp_model,
    parse_tstp_proof,
    unsat_core_from_proof_steps,
)
from ipfs_datasets_py.logic.hammers.translation import TranslationMap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _attempt(
    verdict: SolverVerdict,
    *,
    target: TranslationTarget = TranslationTarget.TPTP,
    attempt_id: str = "attempt-1",
    request_id: str = "req-1",
    translation_id: str = "translation-1",
    solver_name: str = "vampire",
) -> SolverAttemptRecord:
    return SolverAttemptRecord(
        attempt_id=attempt_id,
        request_id=request_id,
        translation_id=translation_id,
        solver_name=solver_name,
        target=target,
        verdict=verdict,
    )


_TSTP_PROOF_TEXT = (
    "fof(f1,axiom,( ! [X] : (p(X) => q(X)) ),file('input.p', premise_p_implies_q)).\n"
    "fof(f2,axiom,(p(a)),file('input.p', premise_p_a)).\n"
    "fof(f3,negated_conjecture,(~q(a)),inference(negated_conjecture,[status(cth)],[f0])).\n"
    "fof(f4,plain,(q(a)),inference(resolution,[status(thm)],[f1,f2])).\n"
    "fof(f5,plain,($false),inference(resolution,[status(thm)],[f3,f4])).\n"
    "SZS status Theorem for input.p\n"
)


def _translation_map_with_premise_ref() -> TranslationMap:
    tmap = TranslationMap()
    tmap.add(
        source_name="Nat.add_comm",
        target_name="premise_p_implies_q",
        target=TranslationTarget.TPTP,
        kind="function",
        origin="original",
    )
    return tmap


# ---------------------------------------------------------------------------
# parse_tstp_proof / unsat_core_from_proof_steps
# ---------------------------------------------------------------------------


class TestParseTstpProof:
    def test_parses_axiom_and_inference_annotations(self) -> None:
        steps, reason = parse_tstp_proof(_TSTP_PROOF_TEXT)
        assert reason is None
        assert [s.step_id for s in steps] == ["f1", "f2", "f3", "f4", "f5"]

        f1 = steps[0]
        assert f1.role == "axiom"
        assert f1.rule is None
        assert f1.source_name == "premise_p_implies_q"
        assert f1.parent_ids == []

        f3 = steps[2]
        assert f3.rule == "negated_conjecture"
        assert f3.parent_ids == ["f0"]
        assert f3.source_name is None

        f5 = steps[4]
        assert f5.rule == "resolution"
        assert f5.parent_ids == ["f3", "f4"]

    def test_no_statements_is_absent_not_malformed(self) -> None:
        steps, reason = parse_tstp_proof("SZS status Theorem for input.p\n% nothing else\n")
        assert steps == []
        assert reason is None

    def test_empty_text_is_absent(self) -> None:
        steps, reason = parse_tstp_proof("")
        assert steps == []
        assert reason is None

    def test_unbalanced_parentheses_is_malformed(self) -> None:
        steps, reason = parse_tstp_proof("fof(f1, axiom, p(a).\n")
        assert steps == []
        assert reason is not None
        assert "unbalanced parentheses" in reason

    def test_missing_terminating_dot_is_malformed(self) -> None:
        steps, reason = parse_tstp_proof("fof(f1, axiom, p(a), file('input.p', ax1))\n")
        assert steps == []
        assert reason is not None
        assert "missing terminating" in reason

    def test_too_few_top_level_fields_is_malformed(self) -> None:
        steps, reason = parse_tstp_proof("fof(f1, axiom).\n")
        assert steps == []
        assert reason is not None
        assert "malformed TSTP statement" in reason

    def test_cnf_and_tff_heads_are_also_recognized(self) -> None:
        text = "cnf(c1, axiom, p(a), file('input.p', ax1)).\ntff(t1, axiom, q(a), file('input.p', ax2)).\n"
        steps, reason = parse_tstp_proof(text)
        assert reason is None
        assert [s.step_id for s in steps] == ["c1", "t1"]


class TestUnsatCoreFromProofSteps:
    def test_leaf_steps_form_the_core_preferring_source_name(self) -> None:
        steps, reason = parse_tstp_proof(_TSTP_PROOF_TEXT)
        assert reason is None
        core = unsat_core_from_proof_steps(steps)
        assert core.core_ids == ["premise_p_implies_q", "premise_p_a"]

    def test_leaf_without_source_name_falls_back_to_step_id(self) -> None:
        steps = [ProofStep(step_id="ax1", role="axiom", rule=None, formula="p(a)")]
        core = unsat_core_from_proof_steps(steps)
        assert core.core_ids == ["ax1"]

    def test_derived_steps_are_excluded(self) -> None:
        steps, _ = parse_tstp_proof(_TSTP_PROOF_TEXT)
        core = unsat_core_from_proof_steps(steps)
        assert "f4" not in core.core_ids
        assert "f5" not in core.core_ids


# ---------------------------------------------------------------------------
# SMT-LIB s-expression parsing
# ---------------------------------------------------------------------------


class TestParseAllSexprs:
    def test_parses_nested_lists_and_atoms(self) -> None:
        exprs = parse_all_sexprs("(a1 a2 a3) unsat")
        assert exprs == [["a1", "a2", "a3"], "unsat"]

    def test_unbalanced_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_all_sexprs("(a1 a2")

    def test_unexpected_close_paren_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_all_sexprs("a1)")


class TestParseSmtlibUnsatCore:
    def test_flat_list_is_a_core(self) -> None:
        core, reason = parse_smtlib_unsat_core("(premise_p_implies_q premise_p_a)\n")
        assert reason is None
        assert core is not None
        assert core.core_ids == ["premise_p_implies_q", "premise_p_a"]

    def test_empty_text_is_absent(self) -> None:
        core, reason = parse_smtlib_unsat_core("")
        assert core is None
        assert reason is None

    def test_unbalanced_is_malformed(self) -> None:
        core, reason = parse_smtlib_unsat_core("(a1 a2")
        assert core is None
        assert reason is not None
        assert "malformed" in reason

    def test_non_flat_output_is_absent_not_a_core(self) -> None:
        # A `(model ...)` response is not a flat atom list, so it must not
        # be misinterpreted as an unsat core.
        core, reason = parse_smtlib_unsat_core("(model (define-fun x () Int 5))\n")
        assert core is None
        assert reason is None


class TestParseSmtlibModel:
    def test_model_wrapper_with_define_fun(self) -> None:
        text = "(model (define-fun x () Int 5) (define-fun y () Bool false))\n"
        model, reason = parse_smtlib_model(text)
        assert reason is None
        assert model is not None
        symbols = {b.symbol: b.value for b in model.bindings}
        assert symbols == {"x": "5", "y": "false"}

    def test_bare_define_fun_list_without_model_wrapper(self) -> None:
        text = "((define-fun x () Int 5))\n"
        model, reason = parse_smtlib_model(text)
        assert reason is None
        assert model is not None
        assert model.bindings[0].symbol == "x"
        assert model.bindings[0].value == "5"

    def test_get_value_style_pairs(self) -> None:
        text = "((x 5) (y true))\n"
        model, reason = parse_smtlib_model(text)
        assert reason is None
        assert model is not None
        symbols = {b.symbol: b.value for b in model.bindings}
        assert symbols == {"x": "5", "y": "true"}

    def test_empty_text_is_absent(self) -> None:
        model, reason = parse_smtlib_model("")
        assert model is None
        assert reason is None

    def test_unbalanced_is_malformed(self) -> None:
        model, reason = parse_smtlib_model("(model (define-fun x () Int 5)")
        assert model is None
        assert reason is not None


class TestParseTptpModel:
    def test_reuses_tstp_scanner_for_finite_model_listing(self) -> None:
        text = "fof(dom1, fi_domain, ( ! [X] : (X = a) )).\n"
        model, reason = parse_tptp_model(text)
        assert reason is None
        assert model is not None
        assert model.bindings[0].symbol == "dom1"

    def test_malformed_finite_model_listing(self) -> None:
        model, reason = parse_tptp_model("fof(dom1, fi_domain, (X = a)\n")
        assert model is None
        assert reason is not None


# ---------------------------------------------------------------------------
# NormalizedEvidence construction / trust invariants
# ---------------------------------------------------------------------------


class TestNormalizedEvidenceInvariants:
    def test_recommended_status_verified_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            NormalizedEvidence(
                request_id="req-1",
                attempt_id="attempt-1",
                kind=EvidenceKind.PROOF,
                format="tstp",
                verdict=SolverVerdict.PROVED,
                recommended_status=HammerResultStatus.VERIFIED,
            )

    def test_recommended_status_timeout_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            NormalizedEvidence(
                request_id="req-1",
                attempt_id="attempt-1",
                kind=EvidenceKind.ABSENT,
                verdict=SolverVerdict.TIMEOUT,
                recommended_status=HammerResultStatus.TIMEOUT,
            )

    def test_malformed_kind_requires_reason(self) -> None:
        with pytest.raises(ValueError):
            NormalizedEvidence(
                request_id="req-1",
                attempt_id="attempt-1",
                kind=EvidenceKind.MALFORMED,
                verdict=SolverVerdict.PROVED,
                recommended_status=HammerResultStatus.UNKNOWN,
            )

    def test_unsupported_kind_requires_reason(self) -> None:
        with pytest.raises(ValueError):
            NormalizedEvidence(
                request_id="req-1",
                attempt_id="attempt-1",
                kind=EvidenceKind.UNSUPPORTED,
                verdict=SolverVerdict.UNKNOWN,
                recommended_status=HammerResultStatus.UNKNOWN,
            )

    def test_counterexample_kind_requires_counterexample_status(self) -> None:
        with pytest.raises(ValueError):
            NormalizedEvidence(
                request_id="req-1",
                attempt_id="attempt-1",
                kind=EvidenceKind.COUNTEREXAMPLE,
                verdict=SolverVerdict.DISPROVED,
                recommended_status=HammerResultStatus.CANDIDATE,
            )

    def test_counterexample_status_requires_counterexample_kind(self) -> None:
        with pytest.raises(ValueError):
            NormalizedEvidence(
                request_id="req-1",
                attempt_id="attempt-1",
                kind=EvidenceKind.MODEL,
                verdict=SolverVerdict.SAT,
                recommended_status=HammerResultStatus.COUNTEREXAMPLE,
            )

    def test_unknown_evidence_kind_string_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            NormalizedEvidence(
                request_id="req-1",
                attempt_id="attempt-1",
                kind="not-a-real-kind",
                verdict=SolverVerdict.UNKNOWN,
                recommended_status=HammerResultStatus.UNKNOWN,
            )

    def test_content_digest_is_deterministic_and_equals_evidence_id(self) -> None:
        kwargs = dict(
            request_id="req-1",
            attempt_id="attempt-1",
            kind=EvidenceKind.ABSENT,
            verdict=SolverVerdict.UNKNOWN,
            recommended_status=HammerResultStatus.UNKNOWN,
        )
        ev1 = NormalizedEvidence(**kwargs)
        ev2 = NormalizedEvidence(**kwargs)
        assert ev1.content_digest
        assert ev1.evidence_id == ev1.content_digest
        assert ev1.content_digest == ev2.content_digest

    def test_different_content_changes_digest(self) -> None:
        ev1 = NormalizedEvidence(
            request_id="req-1",
            attempt_id="attempt-1",
            kind=EvidenceKind.ABSENT,
            verdict=SolverVerdict.UNKNOWN,
            recommended_status=HammerResultStatus.UNKNOWN,
        )
        ev2 = NormalizedEvidence(
            request_id="req-1",
            attempt_id="attempt-2",
            kind=EvidenceKind.ABSENT,
            verdict=SolverVerdict.UNKNOWN,
            recommended_status=HammerResultStatus.UNKNOWN,
        )
        assert ev1.content_digest != ev2.content_digest

    def test_to_dict_from_dict_round_trip(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.PROVED),
            raw_stdout=_TSTP_PROOF_TEXT,
            premise_ids=["premise_p_implies_q", "premise_p_a"],
        )
        restored = NormalizedEvidence.from_dict(ev.to_dict())
        assert restored.to_dict() == ev.to_dict()
        assert restored.content_digest == ev.content_digest


# ---------------------------------------------------------------------------
# normalize_solver_evidence: end-to-end per SolverVerdict
# ---------------------------------------------------------------------------


class TestNormalizeSolverEvidenceProof:
    def test_tptp_proof_produces_candidate_with_unsat_core_and_translation_refs(self) -> None:
        tmap = _translation_map_with_premise_ref()
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.PROVED, target=TranslationTarget.TPTP),
            raw_stdout=_TSTP_PROOF_TEXT,
            premise_ids=["premise_p_implies_q", "premise_p_a", "premise_unused"],
            translation_map=tmap,
        )
        assert ev.kind == EvidenceKind.PROOF
        assert ev.recommended_status is HammerResultStatus.CANDIDATE
        assert ev.format == "tstp"
        assert len(ev.proof_steps) == 5
        assert ev.unsat_core is not None
        assert ev.unsat_core.matched_premise_ids == ["premise_p_a", "premise_p_implies_q"]
        assert any(
            ref.target_name == "premise_p_implies_q" for ref in ev.translation_map_refs
        )
        assert ev.premise_ids == ["premise_p_implies_q", "premise_p_a", "premise_unused"]
        assert ev.translation_ids == ["translation-1"]

    def test_smtlib_unsat_verdict_produces_unsat_core_candidate(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(
                SolverVerdict.UNSAT, target=TranslationTarget.SMTLIB, attempt_id="a-smt"
            ),
            raw_stdout="unsat\n(premise_p_a premise_p_implies_q)\n",
            premise_ids=["premise_p_a", "premise_p_implies_q"],
        )
        assert ev.kind == EvidenceKind.UNSAT_CORE
        assert ev.recommended_status is HammerResultStatus.CANDIDATE
        assert ev.unsat_core is not None
        assert set(ev.unsat_core.matched_premise_ids) == {"premise_p_a", "premise_p_implies_q"}

    def test_proved_with_empty_stdout_is_absent_candidate(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1", attempt=_attempt(SolverVerdict.PROVED), raw_stdout=""
        )
        assert ev.kind == EvidenceKind.ABSENT
        assert ev.recommended_status is HammerResultStatus.CANDIDATE

    def test_proved_with_malformed_tstp_is_unknown(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.PROVED),
            raw_stdout="fof(f1, axiom, p(a).\n",
        )
        assert ev.kind == EvidenceKind.MALFORMED
        assert ev.recommended_status is HammerResultStatus.UNKNOWN
        assert ev.malformed_reason is not None

    def test_unsat_with_malformed_smtlib_core_is_unknown(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.UNSAT, target=TranslationTarget.SMTLIB),
            raw_stdout="unsat\n(a1 a2\n",
        )
        assert ev.kind == EvidenceKind.MALFORMED
        assert ev.recommended_status is HammerResultStatus.UNKNOWN

    def test_smtlib_unsat_without_core_text_is_absent_candidate(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.UNSAT, target=TranslationTarget.SMTLIB),
            raw_stdout="unsat\n",
        )
        assert ev.kind == EvidenceKind.ABSENT
        assert ev.recommended_status is HammerResultStatus.CANDIDATE


class TestNormalizeSolverEvidenceModelAndCounterexample:
    def test_smtlib_sat_produces_model_candidate(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.SAT, target=TranslationTarget.SMTLIB),
            raw_stdout="sat\n(model (define-fun x () Int 5))\n",
        )
        assert ev.kind == EvidenceKind.MODEL
        assert ev.recommended_status is HammerResultStatus.CANDIDATE
        assert ev.model is not None
        assert ev.model.bindings[0].symbol == "x"

    def test_smtlib_sat_with_translation_map_resolves_source_name(self) -> None:
        tmap = TranslationMap()
        tmap.add(
            source_name="Nat.zero",
            target_name="x",
            target=TranslationTarget.SMTLIB,
            kind="function",
        )
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.SAT, target=TranslationTarget.SMTLIB),
            raw_stdout="sat\n(model (define-fun x () Int 5))\n",
            translation_map=tmap,
        )
        assert ev.model is not None
        assert ev.model.bindings[0].source_name == "Nat.zero"
        assert any(ref.source_name == "Nat.zero" for ref in ev.translation_map_refs)

    def test_tptp_countersatisfiable_produces_counterexample(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.DISPROVED, target=TranslationTarget.TPTP),
            raw_stdout="fof(dom1, fi_domain, ( ! [X] : (X = a) )).\nSZS status CounterSatisfiable\n",
        )
        assert ev.kind == EvidenceKind.COUNTEREXAMPLE
        assert ev.recommended_status is HammerResultStatus.COUNTEREXAMPLE
        assert ev.model is not None

    def test_disproved_with_empty_stdout_is_absent_candidate(self) -> None:
        # An absent trace is never reported as COUNTEREXAMPLE (that kind is
        # reserved for an actually-normalized countermodel) — per the
        # HAMMER-009 acceptance contract it always resolves to CANDIDATE or
        # UNKNOWN, here CANDIDATE since DISPROVED is still a conclusive
        # solver claim.
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.DISPROVED, target=TranslationTarget.TPTP),
            raw_stdout="",
        )
        assert ev.kind == EvidenceKind.ABSENT
        assert ev.recommended_status is HammerResultStatus.CANDIDATE

    def test_disproved_with_malformed_model_is_unknown(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.DISPROVED, target=TranslationTarget.TPTP),
            raw_stdout="fof(dom1, fi_domain, (X = a)\n",
        )
        assert ev.kind == EvidenceKind.MALFORMED
        assert ev.recommended_status is HammerResultStatus.UNKNOWN


class TestNormalizeSolverEvidenceInconclusive:
    @pytest.mark.parametrize(
        "verdict", [SolverVerdict.UNKNOWN, SolverVerdict.TIMEOUT, SolverVerdict.ERROR]
    )
    def test_inconclusive_verdicts_are_always_absent_unknown(self, verdict) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(verdict),
            raw_stdout="garbage that looks like nothing in particular",
        )
        assert ev.kind == EvidenceKind.ABSENT
        assert ev.recommended_status is HammerResultStatus.UNKNOWN


class TestSolverVerdictExhaustiveness:
    def test_every_solver_verdict_never_recommends_verified(self) -> None:
        for verdict in SolverVerdict:
            for target in (TranslationTarget.TPTP, TranslationTarget.SMTLIB):
                ev = normalize_solver_evidence(
                    request_id="req-1",
                    attempt=_attempt(verdict, target=target),
                    raw_stdout="",
                )
                assert ev.recommended_status in ALLOWED_RECOMMENDED_STATUSES
                assert ev.recommended_status is not HammerResultStatus.VERIFIED


# ---------------------------------------------------------------------------
# normalize_certificate: unsupported certificate formats
# ---------------------------------------------------------------------------


class TestNormalizeCertificate:
    def test_unsupported_format_is_unknown(self) -> None:
        ev = normalize_certificate(
            request_id="req-1",
            attempt_id="attempt-1",
            verdict=SolverVerdict.PROVED,
            certificate="(some lfsc proof term)",
            certificate_format="lfsc",
        )
        assert ev.kind == EvidenceKind.UNSUPPORTED
        assert ev.recommended_status is HammerResultStatus.UNKNOWN
        assert ev.malformed_reason is not None

    def test_missing_format_is_unsupported(self) -> None:
        ev = normalize_certificate(
            request_id="req-1",
            attempt_id="attempt-1",
            verdict=SolverVerdict.PROVED,
            certificate="whatever",
            certificate_format=None,
        )
        assert ev.kind == EvidenceKind.UNSUPPORTED
        assert ev.recommended_status is HammerResultStatus.UNKNOWN

    def test_tstp_certificate_normalizes_like_solver_stdout(self) -> None:
        ev = normalize_certificate(
            request_id="req-1",
            attempt_id="attempt-1",
            verdict=SolverVerdict.PROVED,
            certificate=_TSTP_PROOF_TEXT,
            certificate_format="tstp",
        )
        assert ev.kind == EvidenceKind.PROOF
        assert ev.recommended_status is HammerResultStatus.CANDIDATE

    def test_absent_certificate_is_absent(self) -> None:
        ev = normalize_certificate(
            request_id="req-1",
            attempt_id="attempt-1",
            verdict=SolverVerdict.UNSAT,
            certificate=None,
            certificate_format="smtlib",
        )
        assert ev.kind == EvidenceKind.ABSENT
        assert ev.recommended_status is HammerResultStatus.CANDIDATE


# ---------------------------------------------------------------------------
# normalize_portfolio_run
# ---------------------------------------------------------------------------


class TestNormalizePortfolioRun:
    def test_normalizes_every_attempt_keyed_by_attempt_id(self) -> None:
        attempt = _attempt(SolverVerdict.PROVED, attempt_id="a1")
        evidence = SolverAttemptEvidence(
            attempt_id="a1",
            command=["vampire", "input.p"],
            input_digest="sha256:deadbeef",
            raw_stdout=_TSTP_PROOF_TEXT,
            raw_stderr="",
        )
        run_result = PortfolioRunResult(
            request_id="req-1", attempts=[attempt], evidence={"a1": evidence}
        )
        normalized = normalize_portfolio_run(run_result, premise_ids=["premise_p_a"])
        assert set(normalized.keys()) == {"a1"}
        assert normalized["a1"].kind == EvidenceKind.PROOF
        assert normalized["a1"].request_id == "req-1"

    def test_missing_evidence_entry_is_treated_as_absent(self) -> None:
        attempt = _attempt(SolverVerdict.PROVED, attempt_id="a2")
        run_result = PortfolioRunResult(request_id="req-1", attempts=[attempt], evidence={})
        normalized = normalize_portfolio_run(run_result)
        assert normalized["a2"].kind == EvidenceKind.ABSENT
        assert normalized["a2"].recommended_status is HammerResultStatus.CANDIDATE

    def test_request_id_override(self) -> None:
        attempt = _attempt(SolverVerdict.UNKNOWN, attempt_id="a3")
        run_result = PortfolioRunResult(request_id="req-original", attempts=[attempt])
        normalized = normalize_portfolio_run(run_result, request_id="req-override")
        assert normalized["a3"].request_id == "req-override"


# ---------------------------------------------------------------------------
# build_proof_candidate_record
# ---------------------------------------------------------------------------


class TestBuildProofCandidateRecord:
    def test_builds_candidate_from_candidate_evidence(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.PROVED),
            raw_stdout=_TSTP_PROOF_TEXT,
            premise_ids=["premise_p_implies_q", "premise_p_a"],
        )
        candidate = build_proof_candidate_record(
            ev,
            candidate_id="cand-1",
            request_id="req-1",
            solver_attempt_id="attempt-1",
            certificate=_TSTP_PROOF_TEXT,
            certificate_format="tstp",
        )
        assert isinstance(candidate, ProofCandidateRecord)
        candidate.validate()
        assert set(candidate.premise_ids) == {"premise_p_implies_q", "premise_p_a"}
        assert candidate.certificate_format == "tstp"

    def test_falls_back_to_premise_ids_when_no_core(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.PROVED),
            raw_stdout="",
            premise_ids=["premise_x"],
        )
        assert ev.kind == EvidenceKind.ABSENT
        candidate = build_proof_candidate_record(
            ev, candidate_id="cand-2", request_id="req-1", solver_attempt_id="attempt-1"
        )
        candidate.validate()
        assert candidate.premise_ids == ["premise_x"]
        assert candidate.certificate is None

    def test_refuses_to_build_from_counterexample_evidence(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1",
            attempt=_attempt(SolverVerdict.DISPROVED, target=TranslationTarget.TPTP),
            raw_stdout="fof(dom1, fi_domain, ( ! [X] : (X = a) )).\n",
        )
        assert ev.recommended_status is HammerResultStatus.COUNTEREXAMPLE
        with pytest.raises(MalformedEvidenceError):
            build_proof_candidate_record(
                ev, candidate_id="cand-3", request_id="req-1", solver_attempt_id="attempt-1"
            )

    def test_refuses_to_build_from_unknown_evidence(self) -> None:
        ev = normalize_solver_evidence(
            request_id="req-1", attempt=_attempt(SolverVerdict.TIMEOUT), raw_stdout=""
        )
        assert ev.recommended_status is HammerResultStatus.UNKNOWN
        with pytest.raises(MalformedEvidenceError):
            build_proof_candidate_record(
                ev, candidate_id="cand-4", request_id="req-1", solver_attempt_id="attempt-1"
            )


# ---------------------------------------------------------------------------
# aggregate_recommended_status
# ---------------------------------------------------------------------------


class TestAggregateRecommendedStatus:
    def test_prefers_candidate_over_counterexample_over_unknown(self) -> None:
        candidate_ev = NormalizedEvidence(
            request_id="r",
            attempt_id="a",
            kind=EvidenceKind.PROOF,
            verdict=SolverVerdict.PROVED,
            recommended_status=HammerResultStatus.CANDIDATE,
        )
        counterexample_ev = NormalizedEvidence(
            request_id="r",
            attempt_id="b",
            kind=EvidenceKind.COUNTEREXAMPLE,
            verdict=SolverVerdict.DISPROVED,
            recommended_status=HammerResultStatus.COUNTEREXAMPLE,
        )
        unknown_ev = NormalizedEvidence(
            request_id="r",
            attempt_id="c",
            kind=EvidenceKind.ABSENT,
            verdict=SolverVerdict.TIMEOUT,
            recommended_status=HammerResultStatus.UNKNOWN,
        )
        assert (
            aggregate_recommended_status([unknown_ev, counterexample_ev])
            is HammerResultStatus.COUNTEREXAMPLE
        )
        assert (
            aggregate_recommended_status([unknown_ev, counterexample_ev, candidate_ev])
            is HammerResultStatus.CANDIDATE
        )
        assert aggregate_recommended_status([unknown_ev]) is HammerResultStatus.UNKNOWN

    def test_empty_iterable_is_unknown(self) -> None:
        assert aggregate_recommended_status([]) is HammerResultStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Dataclass to_dict/from_dict smoke tests
# ---------------------------------------------------------------------------


class TestNestedDataclasses:
    def test_proof_step_round_trip(self) -> None:
        step = ProofStep(
            step_id="f1", role="axiom", rule=None, formula="p(a)", parent_ids=[], source_name="ax1"
        )
        assert ProofStep.from_dict(step.to_dict()) == step

    def test_unsat_core_round_trip(self) -> None:
        core = NormalizedUnsatCore(core_ids=["a", "b"], matched_premise_ids=["a"])
        assert NormalizedUnsatCore.from_dict(core.to_dict()) == core

    def test_model_round_trip(self) -> None:
        model = NormalizedModel(
            bindings=[ModelBinding(symbol="x", value="5", source_name="Nat.zero")]
        )
        assert NormalizedModel.from_dict(model.to_dict()) == model
