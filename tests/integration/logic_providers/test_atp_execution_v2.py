"""Integration tests: Vampire / E typed TPTP/TSTP reconstruction (LFP2-033).

Acceptance (fail-closed):

* ATP success remains candidate evidence until checked/replayed.
* Input profile and translation assumptions are exact on every answer.
* DCEC / TDFOL are labeled translated, never native Vampire/E surface.
* THF is explicit unsupported.
* Mock / fallback / availability / confidence never establish theorem.
* SZS/TSTP parse, proof/countermodel reconstruction, and replay are typed.

Interfaces: ATPProviderEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.atp.execution_v2 import (
    ATP_EXECUTION_V2_TASK_ID,
    ATP_PROVIDER_EVIDENCE_V2_INTERFACE,
    AtpAuthorityError,
    AtpClaimKind,
    AtpDisposition,
    AtpExecutionEngineV2,
    AtpExecutionError,
    AtpExecutionMode,
    AtpExecutionRequestV2,
    AtpInputProfile,
    AtpProviderEvidenceV2,
    AtpProviderKind,
    AtpQueryMode,
    AtpSourceKind,
    atp_success_establishes_theorem,
    detect_input_profile,
    execute_atp,
    execute_eprover,
    execute_vampire,
    hermetic_engine,
    non_authoritative_signal_establishes,
    normalize_atp_provider,
    translation_assumptions_for,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority


# ---------------------------------------------------------------------------
# Compact TPTP / TSTP recipes
# ---------------------------------------------------------------------------

FOF_THEOREM = """\
fof(ax1, axiom, p).
fof(goal, conjecture, p).
"""

FOF_COUNTERMODEL = """\
fof(ax1, axiom, ~p).
fof(goal, conjecture, p).
"""

TFF_TYPED = """\
tff(p_type, type, p: $o).
tff(ax1, axiom, p).
tff(goal, conjecture, p).
"""

CNF_PROBLEM = """\
cnf(ax1, axiom, p).
cnf(goal, negated_conjecture, ~p).
"""

THF_HIGHER_ORDER = """\
thf(goal, conjecture, ![P:$o]: (P => P)).
"""

TSTP_THEOREM = """\
% SZS status Theorem
% SZS output start CNFRefutation
cnf(c_0, plain, p(a), file('problem.p', ax1)).
cnf(c_1, plain, ~p(a), inference(assume, [], [])).
cnf(c_2, plain, $false, inference(resolution, [], [c_0, c_1])).
% SZS output end CNFRefutation
"""

TSTP_UNSAT = """\
% SZS status Unsatisfiable
% SZS output start CNFRefutation
cnf(c_0, plain, p(a), file('problem.p', ax1)).
cnf(c_1, plain, ~p(a), inference(assume, [], [])).
cnf(c_2, plain, $false, inference(resolution, [], [c_0, c_1])).
% SZS output end CNFRefutation
"""

TSTP_COUNTER_SAT = """\
% SZS status CounterSatisfiable for canonical
"""

TSTP_SAT = """\
% SZS status Satisfiable
"""


def _fof_request(**overrides: object) -> AtpExecutionRequestV2:
    payload: dict[str, object] = {
        "request_id": "req:atp:fof:1",
        "source": FOF_THEOREM,
        "provider": AtpProviderKind.VAMPIRE,
        "mode": AtpExecutionMode.HERMETIC_FIXTURE,
        "query_mode": AtpQueryMode.THEOREM_PROOF,
        "source_ref_ids": ("source:fixture:atp:fof-theorem",),
        "available": True,
        "confidence": 0.99,
        "fluent_text": "Obviously Vampire proved this.",
    }
    payload.update(overrides)
    return AtpExecutionRequestV2(**payload)  # type: ignore[arg-type]


def _theorem_engine(
    *,
    verify: bool = False,
    checker_id: str = "tstp-checker:reviewed-v1",
) -> AtpExecutionEngineV2:
    return hermetic_engine(
        vampire_stdout=TSTP_THEOREM,
        eprover_stdout=TSTP_THEOREM,
        vampire_kwargs={"solver_version": "vampire-hermetic"},
        eprover_kwargs={"solver_version": "eprover-hermetic"},
        proof_checker_id=checker_id if verify else "",
        verify_reconstruction=verify,
    )


def _countermodel_engine() -> AtpExecutionEngineV2:
    return hermetic_engine(
        vampire_stdout=TSTP_COUNTER_SAT,
        eprover_stdout=TSTP_COUNTER_SAT,
    )


def _assert_exact_bindings(evidence: AtpProviderEvidenceV2) -> None:
    """Every answer must bind exact profile and translation assumptions."""

    assert evidence.profile is not None
    assert evidence.profile.profile is not None
    assert evidence.profile.source_kind is not None
    assert evidence.profile.source_digest
    assert evidence.translation is not None
    assert isinstance(evidence.translation.is_translated, bool)
    assert evidence.translation.assumption_digest
    assert evidence.theorem_established is False
    assert evidence.proof_established is False
    assert evidence.claim_theorem is False
    wire = evidence.to_dict()
    assert wire["atp_success_remains_candidate_until_checked_replayed"] is True
    assert wire["theorem_established"] is False


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = AtpExecutionEngineV2()
    assert engine.INTERFACE == ATP_PROVIDER_EVIDENCE_V2_INTERFACE
    assert engine.interface == "ATPProviderEvidence@2"
    assert engine.TASK_ID == ATP_EXECUTION_V2_TASK_ID
    assert engine.TASK_ID == "LFP2-033"
    assert AtpExecutionRequestV2.interface == "AtpExecutionRequest@2"
    assert AtpProviderEvidenceV2.interface == "ATPProviderEvidence@2"


def test_provider_normalization() -> None:
    assert normalize_atp_provider("vampire") is AtpProviderKind.VAMPIRE
    assert normalize_atp_provider("eprover") is AtpProviderKind.EPROVER
    assert normalize_atp_provider("e") is AtpProviderKind.EPROVER
    assert normalize_atp_provider("e_prover") is AtpProviderKind.EPROVER
    assert normalize_atp_provider(AtpProviderKind.VAMPIRE) is AtpProviderKind.VAMPIRE
    with pytest.raises(AtpExecutionError):
        normalize_atp_provider("z3")
    with pytest.raises(AtpExecutionError):
        normalize_atp_provider("lean")


def test_input_profile_detection() -> None:
    profile, kind, langs = detect_input_profile(FOF_THEOREM)
    assert profile is AtpInputProfile.FOF
    assert kind is AtpSourceKind.NATIVE
    assert "fof" in langs

    profile, kind, _ = detect_input_profile(TFF_TYPED)
    assert profile is AtpInputProfile.TFF
    assert kind is AtpSourceKind.NATIVE

    profile, kind, _ = detect_input_profile(CNF_PROBLEM)
    assert profile is AtpInputProfile.CNF

    profile, kind, _ = detect_input_profile(THF_HIGHER_ORDER)
    assert profile is AtpInputProfile.THF_UNSUPPORTED
    assert kind is AtpSourceKind.UNSUPPORTED

    profile, kind, _ = detect_input_profile(
        FOF_THEOREM, source_profile="dcec"
    )
    assert profile is AtpInputProfile.DCEC_TRANSLATED
    assert kind is AtpSourceKind.TRANSLATED

    profile, kind, _ = detect_input_profile(
        FOF_THEOREM, source_profile="tdfol"
    )
    assert profile is AtpInputProfile.TDFOL_TRANSLATED
    assert kind is AtpSourceKind.TRANSLATED


# ---------------------------------------------------------------------------
# Hermetic conclusive candidate execution + replay
# ---------------------------------------------------------------------------


def test_vampire_fof_theorem_remains_candidate_until_checked() -> None:
    engine = _theorem_engine(verify=False)
    result = engine.execute(_fof_request())
    evidence = result.evidence

    _assert_exact_bindings(evidence)
    assert evidence.interface == ATP_PROVIDER_EVIDENCE_V2_INTERFACE
    assert evidence.provider is AtpProviderKind.VAMPIRE
    assert evidence.profile.profile is AtpInputProfile.FOF
    assert evidence.profile.source_kind is AtpSourceKind.NATIVE
    assert evidence.profile.native_vampire_e is True
    assert evidence.translation.is_translated is False
    assert evidence.translation.assumptions == ()
    assert evidence.szs.present is True
    assert evidence.szs.status == "Theorem"
    assert evidence.proof.present is True
    assert evidence.proof.status.value in {"candidate", "reconstructed"}
    assert evidence.candidate_established is True or evidence.disposition in {
        AtpDisposition.REPLAY_MATCHED,
        AtpDisposition.CANDIDATE_THEOREM,
    }
    assert evidence.reconstruction_established is False
    assert evidence.theorem_established is False
    assert evidence.result_authority is ResultAuthority.CANDIDATE
    assert evidence.role is ToolRole.CANDIDATE
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.CANDIDATE
    assert evidence.replay is not None
    assert evidence.replay.matched is True
    assert "atp_success_remains_candidate_until_checked_replayed" in evidence.diagnostics


def test_eprover_unsat_candidate_and_replay() -> None:
    engine = hermetic_engine(eprover_stdout=TSTP_UNSAT)
    result = execute_eprover(
        CNF_PROBLEM,
        request_id="req:atp:e:unsat",
        engine=engine,
        query_mode=AtpQueryMode.SATISFIABILITY,
        source_ref_ids=("source:fixture:atp:cnf-unsat",),
    )
    evidence = result.evidence
    _assert_exact_bindings(evidence)
    assert evidence.provider is AtpProviderKind.EPROVER
    assert evidence.profile.profile is AtpInputProfile.CNF
    assert evidence.szs.status == "Unsatisfiable"
    assert evidence.proof.present is True
    assert evidence.theorem_established is False
    assert evidence.result_authority is ResultAuthority.CANDIDATE
    assert evidence.replay is not None
    assert evidence.replay.matched is True


def test_checked_reconstruction_elevates_to_reconstruction_not_theorem() -> None:
    engine = _theorem_engine(verify=True)
    result = engine.execute(_fof_request(request_id="req:atp:checked:1"))
    evidence = result.evidence

    _assert_exact_bindings(evidence)
    assert evidence.reconstruction_established is True
    assert evidence.disposition is AtpDisposition.RECONSTRUCTED
    assert evidence.result_authority is ResultAuthority.RECONSTRUCTION
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.RECONSTRUCTION
    assert evidence.proof.checked is True
    assert evidence.proof.verified is True
    assert evidence.theorem_established is False
    assert evidence.proof_established is False
    assert evidence.claim_theorem is False
    assert evidence.claim_reconstruction is True
    assert evidence.replay is not None
    assert evidence.replay.matched is True
    assert evidence.replay.replay_claimed is True


def test_countermodel_candidate_binding() -> None:
    engine = _countermodel_engine()
    result = execute_vampire(
        FOF_COUNTERMODEL,
        request_id="req:atp:cm:1",
        engine=engine,
        source_ref_ids=("source:fixture:atp:countermodel",),
    )
    evidence = result.evidence
    _assert_exact_bindings(evidence)
    assert evidence.szs.status == "CounterSatisfiable"
    assert evidence.countermodel.present is True
    assert evidence.countermodel.validated is False
    assert evidence.theorem_established is False
    assert evidence.result_authority is ResultAuthority.CANDIDATE


def test_tff_profile_exact() -> None:
    engine = _theorem_engine()
    result = execute_vampire(
        TFF_TYPED,
        request_id="req:atp:tff:1",
        engine=engine,
        source_ref_ids=("source:fixture:atp:tff",),
    )
    evidence = result.evidence
    assert evidence.profile.profile is AtpInputProfile.TFF
    assert evidence.profile.native_vampire_e is True
    assert evidence.translation.is_translated is False


# ---------------------------------------------------------------------------
# DCEC / TDFOL translated labeling
# ---------------------------------------------------------------------------


def test_dcec_labeled_translated_not_native() -> None:
    engine = _theorem_engine()
    result = engine.execute(
        _fof_request(
            request_id="req:atp:dcec:1",
            source_profile="dcec",
            translation_receipt_id="translation:dcec:tptp-fof:1",
        )
    )
    evidence = result.evidence
    _assert_exact_bindings(evidence)
    assert evidence.profile.profile is AtpInputProfile.DCEC_TRANSLATED
    assert evidence.profile.source_kind is AtpSourceKind.TRANSLATED
    assert evidence.profile.native_vampire_e is False
    assert evidence.translation.is_translated is True
    assert evidence.translation.labeled_native is False
    assert evidence.translation.source_profile == "dcec"
    assert len(evidence.translation.assumptions) >= 1
    assert "not_native_vampire_e_surface" in evidence.translation.assumptions
    assert evidence.translation_ceiling is EvidenceAuthority.ADVISORY
    assert evidence.disposition in {
        AtpDisposition.TRANSLATED_CANDIDATE,
        AtpDisposition.REPLAY_MATCHED,
        AtpDisposition.RECONSTRUCTED,
    }


def test_tdfol_labeled_translated_not_native() -> None:
    engine = _theorem_engine()
    assumptions = translation_assumptions_for("tdfol")
    result = engine.execute(
        _fof_request(
            request_id="req:atp:tdfol:1",
            source_profile="tdfol",
            translation_assumptions=assumptions,
        )
    )
    evidence = result.evidence
    assert evidence.profile.profile is AtpInputProfile.TDFOL_TRANSLATED
    assert evidence.translation.is_translated is True
    assert evidence.translation.labeled_native is False
    assert "temporal_operators_reified_as_predicates" in evidence.translation.assumptions
    for item in assumptions:
        assert item in evidence.translation.assumptions


def test_native_source_rejects_translation_assumptions() -> None:
    engine = _theorem_engine()
    with pytest.raises(AtpExecutionError, match="translation assumptions"):
        engine.execute(
            _fof_request(
                translation_assumptions=("illegal_assumption",),
            )
        )


# ---------------------------------------------------------------------------
# Unsupported THF / mock / fallback / authority
# ---------------------------------------------------------------------------


def test_thf_is_explicit_unsupported() -> None:
    engine = _theorem_engine()
    result = engine.execute(
        AtpExecutionRequestV2(
            request_id="req:atp:thf:1",
            source=THF_HIGHER_ORDER,
            provider=AtpProviderKind.VAMPIRE,
            mode=AtpExecutionMode.HERMETIC_FIXTURE,
        )
    )
    evidence = result.evidence
    assert evidence.disposition is AtpDisposition.UNSUPPORTED_PROFILE
    assert evidence.profile.profile is AtpInputProfile.THF_UNSUPPORTED
    assert evidence.profile.source_kind is AtpSourceKind.UNSUPPORTED
    assert evidence.profile.native_vampire_e is False
    assert evidence.candidate_established is False
    assert evidence.theorem_established is False
    assert evidence.result_status is ResultStatus.UNSUPPORTED


def test_mock_never_establishes() -> None:
    engine = _theorem_engine()
    result = engine.execute(
        _fof_request(
            mode=AtpExecutionMode.MOCK,
            mock_output={"status": "Theorem", "proved": True},
        )
    )
    evidence = result.evidence
    assert evidence.disposition is AtpDisposition.MOCK_REJECTED
    assert evidence.candidate_established is False
    assert evidence.reconstruction_established is False
    assert evidence.theorem_established is False
    assert evidence.mock_output_present is True


def test_fallback_never_establishes() -> None:
    engine = _theorem_engine()
    result = engine.execute(
        _fof_request(
            mode=AtpExecutionMode.FALLBACK,
            fallback_output={"szs": "Theorem"},
        )
    )
    evidence = result.evidence
    assert evidence.disposition is AtpDisposition.FALLBACK_REJECTED
    assert evidence.candidate_established is False
    assert evidence.fallback_output_present is True


def test_unavailable_never_establishes() -> None:
    engine = _theorem_engine()
    result = engine.execute(_fof_request(available=False))
    evidence = result.evidence
    assert evidence.disposition is AtpDisposition.UNAVAILABLE
    assert evidence.candidate_established is False
    assert evidence.available is False


def test_atp_success_never_establishes_theorem() -> None:
    assert (
        atp_success_establishes_theorem(
            szs_status="Theorem",
            proof_present=True,
            reconstruction_ok=True,
            replay_matched=True,
            available=True,
            confidence=1.0,
        )
        is False
    )


@pytest.mark.parametrize("claim", list(AtpClaimKind))
def test_non_authoritative_signals_never_establish(claim: AtpClaimKind) -> None:
    assert (
        non_authoritative_signal_establishes(
            claim,
            mock_output={"proved": True},
            fallback_output={"proved": True},
            available=True,
            confidence=1.0,
            fluent_text="Obviously a theorem.",
        )
        is False
    )


def test_evidence_rejects_theorem_established_flag() -> None:
    engine = _theorem_engine()
    result = engine.execute(_fof_request(request_id="req:atp:auth:1"))
    payload = result.evidence.to_dict()
    payload["theorem_established"] = True
    with pytest.raises(AtpAuthorityError):
        AtpProviderEvidenceV2(
            evidence_id=payload["evidence_id"],
            request_id=payload["request_id"],
            request_digest=payload["request_digest"],
            provider=payload["provider"],
            disposition=payload["disposition"],
            mode=payload["mode"],
            query_mode=payload["query_mode"],
            source_digest=payload["source_digest"],
            profile=payload["profile"],
            translation=payload["translation"],
            theorem_established=True,
        )


def test_execute_atp_convenience() -> None:
    engine = _theorem_engine()
    result = execute_atp(
        FOF_THEOREM,
        request_id="req:atp:conv:1",
        provider="vampire",
        engine=engine,
        source_ref_ids=("source:fixture:atp:conv",),
    )
    assert result.evidence.provider is AtpProviderKind.VAMPIRE
    assert result.evidence.theorem_established is False


def test_malformed_szs_is_typed() -> None:
    engine = hermetic_engine(
        vampire_stdout="Proof found! Theorem proved!\n",
    )
    result = engine.execute(_fof_request(request_id="req:atp:malformed:1"))
    evidence = result.evidence
    assert evidence.disposition is AtpDisposition.MALFORMED
    assert evidence.candidate_established is False
    assert evidence.theorem_established is False


def test_translation_assumptions_are_exact_and_digest_bound() -> None:
    assumptions = translation_assumptions_for(AtpInputProfile.DCEC_TRANSLATED)
    assert assumptions
    assert "not_native_vampire_e_surface" in assumptions
    # Closed set is stable: re-deriving yields the same ordered tuple.
    assert translation_assumptions_for("dcec") == assumptions
    assert translation_assumptions_for("cec_dcec") == assumptions

    tdfol = translation_assumptions_for("tdfol")
    assert "time_sort_introduced" in tdfol
    assert tdfol != assumptions


def test_backend_outcome_never_mints_theorem_authority() -> None:
    """Checked reconstruction elevates reconstruction only — never theorem."""

    engine = _theorem_engine(verify=True)
    result = engine.execute(_fof_request(request_id="req:atp:no-thm:1"))
    evidence = result.evidence
    assert evidence.reconstruction_established is True
    assert evidence.theorem_established is False
    assert evidence.proof_established is False
    assert evidence.result_authority is ResultAuthority.RECONSTRUCTION
    assert evidence.result_authority is not ResultAuthority.THEOREM
    wire = evidence.to_dict()
    assert wire["theorem_established"] is False
    assert wire["proof_established"] is False
    assert wire["claim_theorem"] is False
    assert wire["atp_success_remains_candidate_until_checked_replayed"] is True
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.RECONSTRUCTION
    # Adapter layer keeps ATP as candidate; promotion is only on the evidence.
    if result.backend_outcome is not None:
        assert result.backend_outcome.result.authority is ResultAuthority.CANDIDATE


def test_profile_and_translation_present_on_reject_paths() -> None:
    engine = _theorem_engine()
    for mode, kwargs in (
        (AtpExecutionMode.MOCK, {"mock_output": {"status": "Theorem"}}),
        (AtpExecutionMode.FALLBACK, {"fallback_output": {"szs": "Theorem"}}),
    ):
        result = engine.execute(
            _fof_request(
                request_id=f"req:atp:reject:{mode.value}",
                mode=mode,
                **kwargs,
            )
        )
        _assert_exact_bindings(result.evidence)
        assert result.evidence.profile.profile is AtpInputProfile.FOF
        assert result.evidence.translation.is_translated is False
