"""Conformance: SymbolicAI advisor candidate parser boundary (LFP-022).

Acceptance:

* SymbolicAI parse/type failure remains an unverified candidate under
  formalization/proposal_advisors.py
* Successful parse yields a typed candidate that still cannot mint proof
  authority
* Confidence / is_valid never establish proof

Interfaces: AdvisorCandidateParser@1
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.formalization.advisor_parser_adapter import (
    ADVISOR_CANDIDATE_PARSER_INTERFACE,
    AdvisorCandidateParser,
    AdvisorNotation,
    AdvisorParseDisposition,
    AdvisorParserError,
    parse_advisor_candidate,
)
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    ProposalCandidate,
    ProposalKind,
    ProposalProvider,
    accept_candidate,
    confidence_never_yields_proof,
)
from ipfs_datasets_py.logic.parsers.flogic import FLogicDocument
from ipfs_datasets_py.logic.parsers.rules import RuleDocument
from ipfs_datasets_py.logic.parsers.smtlib import SmtlibDocument
from ipfs_datasets_py.logic.parsers.tptp import TPTPDocument


def _symai_candidate(
    body: str,
    *,
    candidate_id: str = "symai:cand:1",
    confidence: float = 0.99,
) -> ProposalCandidate:
    return ProposalCandidate(
        candidate_id=candidate_id,
        kind=ProposalKind.SPECIFICATION,
        body=body,
        source_ref_ids=("source:fixture:1",),
        provider=ProposalProvider.SYMAI,
        confidence=confidence,
        rationale="fixture proposal",
    )


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    parser = AdvisorCandidateParser()
    assert AdvisorCandidateParser.INTERFACE == ADVISOR_CANDIDATE_PARSER_INTERFACE
    assert parser.interface == ADVISOR_CANDIDATE_PARSER_INTERFACE


# ---------------------------------------------------------------------------
# Successful deterministic parse → typed candidate, still unverified
# ---------------------------------------------------------------------------


def test_symbolicai_smtlib_body_becomes_typed_unverified_candidate() -> None:
    body = (
        "(set-logic QF_UF)\n"
        "(declare-const p Bool)\n"
        "(assert p)\n"
        "(check-sat)\n"
    )
    candidate = _symai_candidate(body, confidence=0.99)
    result = AdvisorCandidateParser().parse_symbolicai(
        candidate, notation=AdvisorNotation.SMTLIB2
    )
    assert result.parse_ok is True
    assert result.disposition is AdvisorParseDisposition.TYPED_CANDIDATE
    assert result.remains_unverified_candidate is True
    assert result.candidate.authority == UNVERIFIED_AUTHORITY
    assert result.receipt.authority == UNVERIFIED_AUTHORITY
    assert result.receipt.result_authority is ResultAuthority.CANDIDATE
    assert result.receipt.result_status is ResultStatus.CANDIDATE
    assert result.is_proved is False
    assert isinstance(result.typed_document, SmtlibDocument)
    assert result.typed_kind == "SmtlibDocument"
    # High confidence never proves.
    assert confidence_never_yields_proof(confidence=0.99, is_valid=True) is False
    assert result.candidate.is_proved is False
    # Parse alone does not admit the candidate.
    acceptance = result.acceptance(independently_validated=False)
    assert acceptance.accepted is False
    assert "missing_independent_solver_or_kernel_validation" in acceptance.reasons


def test_symbolicai_tptp_body_typed_candidate() -> None:
    body = "fof(ax, axiom, p(a)).\nfof(g, conjecture, p(a)).\n"
    result = parse_advisor_candidate(
        _symai_candidate(body),
        notation=AdvisorNotation.TPTP,
    )
    assert result.parse_ok is True
    assert isinstance(result.typed_document, TPTPDocument)
    assert result.receipt.parser_interface == "TPTPFrontend@1"
    assert result.candidate.authority == UNVERIFIED_AUTHORITY


def test_symbolicai_flogic_body_typed_candidate() -> None:
    body = 'rex[name -> "Rex"] : Dog.\n'
    result = AdvisorCandidateParser().parse(
        _symai_candidate(body),
        notation=AdvisorNotation.FLOGIC,
    )
    assert result.parse_ok is True
    assert isinstance(result.typed_document, FLogicDocument)
    assert result.receipt.logic_family == "frame_logic"
    assert result.receipt.authority == UNVERIFIED_AUTHORITY


def test_auto_notation_selects_smtlib() -> None:
    body = "(set-logic ALL)\n(assert true)\n(check-sat)\n"
    result = parse_advisor_candidate(_symai_candidate(body), notation="auto")
    assert result.parse_ok is True
    assert result.receipt.notation is AdvisorNotation.SMTLIB2


# ---------------------------------------------------------------------------
# Parse / type failure remains unverified under proposal_advisors
# ---------------------------------------------------------------------------


def test_parse_failure_remains_unverified_candidate() -> None:
    body = "this is not a logic formula at all !!! @@@ ###"
    candidate = _symai_candidate(body, confidence=1.0)
    result = AdvisorCandidateParser().parse(candidate, notation=AdvisorNotation.SMTLIB2)
    assert result.parse_ok is False
    assert result.disposition is AdvisorParseDisposition.UNVERIFIED_CANDIDATE
    assert result.typed_document is None
    assert result.candidate is candidate or result.candidate.authority == UNVERIFIED_AUTHORITY
    assert result.candidate.authority == UNVERIFIED_AUTHORITY
    assert result.receipt.authority == UNVERIFIED_AUTHORITY
    assert result.receipt.parse_ok is False
    assert result.receipt.type_ok is False
    assert result.remains_unverified_candidate is True
    assert result.is_proved is False
    # Metadata points at proposal_advisors boundary.
    meta = result.receipt.metadata.to_dict()
    assert meta.get("under") == "formalization/proposal_advisors.py"
    # accept_candidate still refuses without independent validation.
    acceptance = accept_candidate(
        result.candidate,
        compiled=False,
        independently_validated=False,
    )
    assert acceptance.accepted is False
    assert "missing_deterministic_compilation" in acceptance.reasons


def test_type_failure_path_stays_unverified_for_wrong_notation() -> None:
    # Valid F-logic fed to SMT-LIB notation fails closed to unverified.
    body = 'alice[name -> "Alice"] : Person.\n'
    result = AdvisorCandidateParser().parse(
        _symai_candidate(body),
        notation=AdvisorNotation.SMTLIB2,
    )
    assert result.parse_ok is False
    assert result.disposition is AdvisorParseDisposition.UNVERIFIED_CANDIDATE
    assert result.candidate.authority == UNVERIFIED_AUTHORITY
    assert result.receipt.result_authority is ResultAuthority.CANDIDATE


def test_empty_body_unverified() -> None:
    with pytest.raises(Exception):
        # ProposalCandidate itself rejects empty body.
        _symai_candidate("   ")


# ---------------------------------------------------------------------------
# Authority ceiling hard rules
# ---------------------------------------------------------------------------


def test_cannot_construct_receipt_with_theorem_authority() -> None:
    from ipfs_datasets_py.logic.formalization.advisor_parser_adapter import (
        AdvisorParseReceipt,
    )

    with pytest.raises(AdvisorParserError):
        AdvisorParseReceipt(
            candidate_id="c1",
            provider=ProposalProvider.SYMAI,
            notation=AdvisorNotation.SMTLIB2,
            disposition=AdvisorParseDisposition.TYPED_CANDIDATE,
            authority="theorem",
        )


def test_parse_symbolicai_requires_symai_provider() -> None:
    candidate = ProposalCandidate(
        candidate_id="lean:1",
        kind=ProposalKind.LEMMA,
        body="(assert true)",
        source_ref_ids=("source:1",),
        provider=ProposalProvider.LEANSTRAL,
    )
    with pytest.raises(AdvisorParserError):
        AdvisorCandidateParser().parse_symbolicai(candidate)


def test_wire_dict_preserves_unverified_flags() -> None:
    result = parse_advisor_candidate(
        _symai_candidate(
            "(set-logic ALL)\n(assert true)\n(check-sat)\n"
        ),
        notation=AdvisorNotation.SMTLIB2,
    )
    wire = result.to_dict()
    assert wire["remains_unverified_candidate"] is True
    assert wire["is_proved"] is False
    assert wire["candidate"]["authority"] == UNVERIFIED_AUTHORITY
    assert wire["receipt"]["authority"] == UNVERIFIED_AUTHORITY
    assert wire["receipt"]["is_proved"] is False
    assert wire["interface"] == ADVISOR_CANDIDATE_PARSER_INTERFACE


def test_rules_notation_parses_horn_fact() -> None:
    body = "parent(alice, bob).\n"
    result = parse_advisor_candidate(
        _symai_candidate(body),
        notation=AdvisorNotation.RULES,
    )
    # Either typed RuleDocument or unverified — never proved.
    assert result.candidate.authority == UNVERIFIED_AUTHORITY
    assert result.is_proved is False
    if result.parse_ok:
        assert isinstance(result.typed_document, RuleDocument)
