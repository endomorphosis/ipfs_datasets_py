"""Conformance: classical/rule parser join with Z3, cvc5, Vampire, E, SecPAL, ErgoAI (LFP-022).

Acceptance:

* Exact routes run hermetically or report unavailable
* Approximate/unsupported routes cannot promote authority
* No backend reparses natural language or free-form family labels
* Typed source reaches shared backend requests with preservation receipts

Interfaces: ClassicalBackendAdapter@1
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.datalog.adapters import (
    DEFAULT_AUTHORIZATION_FIXTURES,
    SecPALAuthorizationBackend,
)
from ipfs_datasets_py.logic.backends.results import (
    AuthorizationResult,
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from ipfs_datasets_py.logic.parsers.classical_adapters import (
    CLASSICAL_BACKEND_ADAPTER_INTERFACE,
    AuthorityPromotionError,
    ClassicalBackendAdapter,
    ClassicalRouteKind,
    ClassicalRouteReceipt,
    FreeFormFamilyError,
    NaturalLanguageRejectedError,
    RouteExactness,
    enforce_authority_ceiling,
    is_exact_route,
    normalize_route_kind,
    reject_free_form_family,
    reject_natural_language_payload,
    route_authority_ceiling,
    route_exactness,
)
from ipfs_datasets_py.logic.parsers.flogic import (
    ErgoAIControlledSource,
    FLogicFrontend,
)
from ipfs_datasets_py.logic.parsers.smtlib import SMTLIB2Frontend
from ipfs_datasets_py.logic.parsers.tptp import TPTPFrontend
from ipfs_datasets_py.logic.software_verification.authorization import (
    DecisionOutcome,
)


# ---------------------------------------------------------------------------
# Hermetic fake backends
# ---------------------------------------------------------------------------


class _FakeSmtBackend:
    """Injected SMT backend with controllable availability and verdict."""

    def __init__(
        self,
        backend_id: str = "z3",
        *,
        available: bool = True,
        status: ResultStatus = ResultStatus.UNSATISFIABLE,
    ) -> None:
        self.backend_id = backend_id
        self._available = available
        self._status = status
        self.calls: list[BackendRequest] = []

    def is_available(self) -> bool:
        return self._available

    def run(self, request: BackendRequest, **_kwargs: Any) -> SatisfiabilityResult:
        self.calls.append(request)
        # Prove the request carries typed SMT-LIB, not natural language.
        payload = request.payload.to_dict()
        source = str(payload.get("smtlib") or payload.get("source") or "")
        assert "(" in source
        assert "natural language" not in source.lower()
        return SatisfiabilityResult(
            result_id=f"result:{self.backend_id}:fake",
            backend_id=self.backend_id,
            backend_version="fake/v1",
            authority=ResultAuthority.SATISFIABILITY,
            status=self._status,
            assumptions=request.assumption_ids,
            bounds=request.bounds,
            usage=ResourceUsage(elapsed_ms=1),
            reason="hermetic fake SMT",
        )


class _FakeAtpBackend:
    def __init__(
        self,
        backend_id: str = "vampire",
        *,
        available: bool = True,
    ) -> None:
        self.backend_id = backend_id
        self._available = available
        self.calls: list[BackendRequest] = []

    def is_available(self) -> bool:
        return self._available

    def run(self, request: BackendRequest, **_kwargs: Any) -> CandidateResult:
        self.calls.append(request)
        payload = request.payload.to_dict()
        source = str(payload.get("source") or "")
        assert source.lstrip().startswith(("fof", "cnf", "tff", "%"))
        return CandidateResult(
            result_id=f"result:{self.backend_id}:fake",
            backend_id=self.backend_id,
            backend_version="fake/v1",
            authority=ResultAuthority.CANDIDATE,
            status=ResultStatus.CANDIDATE,
            assumptions=request.assumption_ids,
            bounds=request.bounds,
            reason="unreconstructed ATP candidate",
            diagnostics=("atp_unreconstructed_candidate",),
        )


# ---------------------------------------------------------------------------
# Interface / route catalog
# ---------------------------------------------------------------------------


def test_interface_and_route_catalog() -> None:
    adapter = ClassicalBackendAdapter(availability={"z3": False, "cvc5": False})
    assert ClassicalBackendAdapter.INTERFACE == CLASSICAL_BACKEND_ADAPTER_INTERFACE
    assert adapter.interface == CLASSICAL_BACKEND_ADAPTER_INTERFACE
    routes = set(adapter.known_routes())
    for expected in ("z3", "cvc5", "vampire", "e", "eprover", "secpal", "ergoai"):
        assert expected in routes
    assert normalize_route_kind("eprover") is ClassicalRouteKind.E
    assert normalize_route_kind("datalog_secpal") is ClassicalRouteKind.SECPAL
    assert normalize_route_kind("ergo_ai") is ClassicalRouteKind.ERGOAI


def test_route_authority_ceilings() -> None:
    assert route_authority_ceiling("z3") is ResultAuthority.SATISFIABILITY
    assert route_authority_ceiling("cvc5") is ResultAuthority.SATISFIABILITY
    assert route_authority_ceiling("vampire") is ResultAuthority.CANDIDATE
    assert route_authority_ceiling("e") is ResultAuthority.CANDIDATE
    assert route_authority_ceiling("secpal") is ResultAuthority.AUTHORIZATION
    assert route_authority_ceiling("ergoai") is ResultAuthority.CANDIDATE
    assert is_exact_route("z3")
    assert is_exact_route("vampire")
    assert is_exact_route("secpal")
    assert route_exactness("ergoai") is RouteExactness.APPROXIMATE
    assert not is_exact_route("ergoai")


def test_approximate_routes_cannot_promote_authority() -> None:
    with pytest.raises(AuthorityPromotionError):
        enforce_authority_ceiling(
            route=ClassicalRouteKind.ERGOAI,
            authority=ResultAuthority.THEOREM,
        )
    with pytest.raises(AuthorityPromotionError):
        enforce_authority_ceiling(
            route=ClassicalRouteKind.Z3,
            authority=ResultAuthority.THEOREM,
        )
    with pytest.raises(AuthorityPromotionError):
        ClassicalRouteReceipt(
            route=ClassicalRouteKind.ERGOAI,
            exactness=RouteExactness.APPROXIMATE,
            authority_ceiling=ResultAuthority.THEOREM,
            logic_family="frame_logic",
            source_format="flogic",
            source_digest="a" * 64,
            request_digest="b" * 64,
            parser_interface="ErgoAIControlledSource@1",
            backend_id="ergoai",
            availability="available",
        )


# ---------------------------------------------------------------------------
# Free-form family / natural language rejection
# ---------------------------------------------------------------------------


def test_rejects_free_form_family_labels() -> None:
    with pytest.raises(FreeFormFamilyError):
        reject_free_form_family("please prove this FOL thing")
    with pytest.raises(FreeFormFamilyError):
        reject_free_form_family("my_custom_logic_family")
    assert reject_free_form_family("first_order") == "first_order"
    assert reject_free_form_family("authorization") == "authorization"


def test_rejects_natural_language_payloads() -> None:
    with pytest.raises(NaturalLanguageRejectedError):
        reject_natural_language_payload(
            "Please prove in plain English that every human is mortal"
        )
    with pytest.raises(NaturalLanguageRejectedError):
        reject_natural_language_payload("natural language goal for the solver")
    # Controlled SMT-LIB is admitted.
    text = "(assert true)\n(check-sat)"
    assert reject_natural_language_payload(text) == text


def test_smt_route_rejects_natural_language() -> None:
    adapter = ClassicalBackendAdapter(
        z3=_FakeSmtBackend(available=True),
        availability={"z3": True},
    )
    with pytest.raises((NaturalLanguageRejectedError, Exception)):
        adapter.run(
            "z3",
            "In natural language, show that the claim holds for all models",
        )


def test_backend_request_never_carries_free_form_family() -> None:
    fake = _FakeSmtBackend(available=True)
    adapter = ClassicalBackendAdapter(z3=fake, availability={"z3": True})
    source = (
        "(set-logic QF_UF)\n"
        "(declare-const p Bool)\n"
        "(assert p)\n"
        "(check-sat)\n"
    )
    result = adapter.run_smt(source, route="z3")
    assert result.backend_request is not None
    assert result.backend_request.logic_family == "first_order"
    with pytest.raises(FreeFormFamilyError):
        reject_free_form_family("fol-ish free form")


# ---------------------------------------------------------------------------
# SMT exact routes (hermetic or unavailable)
# ---------------------------------------------------------------------------


def test_z3_exact_route_runs_hermetically_with_typed_smtlib() -> None:
    fake = _FakeSmtBackend(
        backend_id="z3",
        available=True,
        status=ResultStatus.UNSATISFIABLE,
    )
    adapter = ClassicalBackendAdapter(z3=fake, availability={"z3": True})
    doc = SMTLIB2Frontend().parse_text_or_raise(
        "(set-logic QF_UF)\n"
        "(declare-const p Bool)\n"
        "(assert (not p))\n"
        "(assert p)\n"
        "(check-sat)\n"
    )
    result = adapter.run_smt(doc, route=ClassicalRouteKind.Z3)
    assert result.route is ClassicalRouteKind.Z3
    assert not result.unavailable
    assert result.receipt.exactness is RouteExactness.EXACT
    assert result.receipt.can_promote_authority is True
    assert result.authority is ResultAuthority.SATISFIABILITY
    assert result.status is ResultStatus.UNSATISFIABLE
    assert result.receipt.proof_safe is True
    assert fake.calls
    payload = fake.calls[0].payload.to_dict()
    assert payload["encoding"] == "smtlib2"
    assert "source" in payload
    assert result.source_binding is not None
    assert result.source_binding.source_format == "smtlib2"
    assert result.receipt.parser_interface == "SMTLIB2Frontend@1"


def test_cvc5_exact_route_reports_unavailable_when_missing() -> None:
    adapter = ClassicalBackendAdapter(
        cvc5=_FakeSmtBackend(backend_id="cvc5", available=False),
        availability={"cvc5": False},
    )
    source = "(set-logic ALL)\n(assert true)\n(check-sat)\n"
    result = adapter.run_smt(source, route="cvc5")
    assert result.route is ClassicalRouteKind.CVC5
    assert result.unavailable
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.receipt.availability.value == "unavailable"
    # Unavailable never invents a conclusive satisfiability verdict.
    assert result.authority is ResultAuthority.CANDIDATE


def test_smt_counterexample_safe_model_path() -> None:
    fake = _FakeSmtBackend(
        backend_id="z3",
        available=True,
        status=ResultStatus.SATISFIABLE,
    )
    adapter = ClassicalBackendAdapter(z3=fake, availability={"z3": True})
    result = adapter.run_smt(
        "(set-logic QF_UF)\n(declare-const p Bool)\n(assert p)\n(check-sat)\n",
        route="z3",
    )
    assert result.status is ResultStatus.SATISFIABLE
    assert result.receipt.counterexample_safe is True
    assert result.receipt.proof_safe is False


# ---------------------------------------------------------------------------
# ATP exact routes — candidate until reconstruction
# ---------------------------------------------------------------------------


def test_vampire_route_emits_atp_candidate() -> None:
    fake = _FakeAtpBackend(backend_id="vampire", available=True)
    adapter = ClassicalBackendAdapter(vampire=fake, availability={"vampire": True})
    doc = TPTPFrontend().parse_text_or_raise(
        "fof(ax, axiom, p(a)).\n"
        "fof(conj, conjecture, p(a)).\n"
    )
    result = adapter.run_atp(doc, route="vampire")
    assert result.route is ClassicalRouteKind.VAMPIRE
    assert result.authority is ResultAuthority.CANDIDATE
    assert result.status is ResultStatus.CANDIDATE
    assert result.receipt.authority_ceiling is ResultAuthority.CANDIDATE
    assert fake.calls
    assert fake.calls[0].payload.to_dict()["encoding"] == "tptp"


def test_e_route_reports_unavailable() -> None:
    adapter = ClassicalBackendAdapter(
        eprover=_FakeAtpBackend(backend_id="e", available=False),
        availability={"e": False},
    )
    result = adapter.run_atp(
        "fof(a, axiom, p).\nfof(c, conjecture, p).\n",
        route="eprover",
    )
    assert result.route is ClassicalRouteKind.E
    assert result.unavailable
    assert result.status is ResultStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# SecPAL authorization decision (hermetic reference evaluator)
# ---------------------------------------------------------------------------


def test_secpal_route_hermetic_authorization_decision() -> None:
    fixture = DEFAULT_AUTHORIZATION_FIXTURES[0]
    adapter = ClassicalBackendAdapter(
        secpal=SecPALAuthorizationBackend(use_external_engine=False),
        availability={"secpal": True},
    )
    result = adapter.run_secpal(fixture.document, query=fixture.query)
    assert result.route is ClassicalRouteKind.SECPAL
    assert result.authority is ResultAuthority.AUTHORIZATION
    assert isinstance(result.result, AuthorizationResult)
    assert result.result.authority is ResultAuthority.AUTHORIZATION
    assert result.status in {
        ResultStatus.AUTHORIZED,
        ResultStatus.DENIED,
        ResultStatus.UNKNOWN,
    }
    assert result.receipt.exactness is RouteExactness.EXACT
    assert result.receipt.can_promote_authority is True
    # Never theorem.
    assert result.authority is not ResultAuthority.THEOREM
    assert result.backend_request is not None
    assert result.backend_request.query_kind is QueryKind.POLICY_APPROVAL
    payload = result.backend_request.payload.to_dict()
    assert payload["encoding"] == "authorization-ir"
    assert "authorization_ir" in payload


def test_secpal_matches_fixture_expected_outcome() -> None:
    adapter = ClassicalBackendAdapter(
        secpal=SecPALAuthorizationBackend(use_external_engine=False),
    )
    # Find an allow fixture if present.
    allow = next(
        (
            item
            for item in DEFAULT_AUTHORIZATION_FIXTURES
            if item.expected_outcome is DecisionOutcome.ALLOW
        ),
        None,
    )
    if allow is None:
        pytest.skip("no allow fixture in DEFAULT_AUTHORIZATION_FIXTURES")
    result = adapter.run_secpal(allow.document, query=allow.query)
    assert result.status is ResultStatus.AUTHORIZED


# ---------------------------------------------------------------------------
# ErgoAI advisor-only
# ---------------------------------------------------------------------------


def test_ergoai_route_is_advisor_candidate_only() -> None:
    adapter = ClassicalBackendAdapter()
    doc = FLogicFrontend().parse_text_or_raise(
        'rex[name -> "Rex"] : Dog.\n'
    )
    result = adapter.run_ergoai(doc)
    assert result.route is ClassicalRouteKind.ERGOAI
    assert result.authority is ResultAuthority.CANDIDATE
    assert result.status is ResultStatus.CANDIDATE
    assert result.receipt.exactness is RouteExactness.APPROXIMATE
    assert result.receipt.can_promote_authority is False
    assert "ergoai_advisor_only" in result.receipt.approximated_constructs
    controlled = ErgoAIControlledSource.from_document(doc)
    result2 = adapter.run_ergoai(controlled)
    assert result2.authority is ResultAuthority.CANDIDATE
    # Approximate receipt refuses theorem ceiling.
    with pytest.raises(AuthorityPromotionError):
        enforce_authority_ceiling(
            route="ergoai",
            authority=ResultAuthority.AUTHORIZATION,
        )


# ---------------------------------------------------------------------------
# Dispatch + receipts
# ---------------------------------------------------------------------------


def test_run_dispatch_covers_all_primary_routes() -> None:
    z3 = _FakeSmtBackend(available=True)
    vampire = _FakeAtpBackend(available=True)
    fixture = DEFAULT_AUTHORIZATION_FIXTURES[0]
    adapter = ClassicalBackendAdapter(
        z3=z3,
        vampire=vampire,
        secpal=SecPALAuthorizationBackend(use_external_engine=False),
        availability={"z3": True, "vampire": True, "secpal": True},
    )
    smt = adapter.run(
        "z3",
        "(set-logic ALL)\n(assert true)\n(check-sat)\n",
    )
    assert smt.route is ClassicalRouteKind.Z3
    atp = adapter.run(
        "vampire",
        "fof(a, axiom, p).\nfof(c, conjecture, p).\n",
    )
    assert atp.authority is ResultAuthority.CANDIDATE
    authz = adapter.run("secpal", fixture.document, query=fixture.query)
    assert authz.authority is ResultAuthority.AUTHORIZATION
    ergo = adapter.run(
        "ergoai",
        FLogicFrontend().parse_text_or_raise('rex[name -> "Rex"] : Dog.\n'),
    )
    assert ergo.authority is ResultAuthority.CANDIDATE


def test_route_receipt_wire_round_trip_fields() -> None:
    adapter = ClassicalBackendAdapter(
        z3=_FakeSmtBackend(available=True),
        availability={"z3": True},
    )
    result = adapter.run_smt(
        "(set-logic ALL)\n(assert true)\n(check-sat)\n",
        route="z3",
    )
    wire = result.to_dict()
    assert wire["interface"] == CLASSICAL_BACKEND_ADAPTER_INTERFACE
    assert wire["receipt"]["source_format"] == "smtlib2"
    assert wire["receipt"]["parser_interface"] == "SMTLIB2Frontend@1"
    assert wire["source_binding"]["source_digest"]
    assert result.receipt.request_digest == result.backend_request.digest  # type: ignore[union-attr]


def test_default_bounds_are_finite() -> None:
    adapter = ClassicalBackendAdapter(
        z3=_FakeSmtBackend(available=True),
        availability={"z3": True},
        default_bounds=ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=1024 * 1024,
            max_output_bytes=4096,
        ),
    )
    result = adapter.run_smt(
        "(set-logic ALL)\n(assert true)\n(check-sat)\n",
        route="z3",
    )
    assert result.backend_request is not None
    assert result.backend_request.bounds.timeout_ms == 1000
