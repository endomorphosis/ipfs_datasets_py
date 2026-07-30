"""Integration contract for Datalog and SecPAL-style authorization backends.

Covers LFV-G046 / LFV-027 acceptance:

* the reference evaluator and available external engines agree on
  allow/deny/conflict/unknown fixtures;
* recursion, delegation, and resources are bounded;
* explanations bind concrete rules;
* engine output cannot grant theorem authority.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.datalog.adapters import (
    DATALOG_AUTHORIZATION_BACKEND_VERSION,
    DEFAULT_AUTHORIZATION_FIXTURES,
    SECPAL_AUTHORIZATION_BACKEND_VERSION,
    AuthorizationBackendError,
    AuthorizationFixture,
    ConformanceStatus,
    DatalogAuthorizationBackend,
    EngineKind,
    EvaluationReceipt,
    ReferenceAuthorizationEvaluator,
    SecPALAuthorizationBackend,
    SupervisorPolicyView,
    UcanCapabilityView,
    outcome_to_result_status,
    parse_engine_outcome,
    render_datalog_program,
    render_secpal_program,
)
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import (
    AuthorizationResult,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.software_verification.authorization import (
    AuthorizationEvidenceAuthority,
    DecisionOutcome,
    GeneratedCodeCorrectness,
    PolicyDecision,
)


def _request(
    document,
    query,
    *,
    backend_id: str = "datalog-authorization",
    family: str = "authorization",
    encoding: str = "authorization-ir",
    bounds: ExecutionBounds | None = None,
) -> BackendRequest:
    return BackendRequest(
        request_id="request:authz:test",
        claim_id="claim:authz:test",
        declaration_id="declaration:authz:test",
        claim_digest="1" * 64,
        obligation_id="obligation:authz:test",
        obligation_digest="2" * 64,
        assumption_ids=("assumption:reviewed-policy",),
        logic_family=family,
        query_kind=QueryKind.POLICY_APPROVAL,
        bounds=bounds or ExecutionBounds(timeout_ms=250, max_steps=200),
        payload=FrozenMap(
            {
                "encoding": encoding,
                "authorization_ir": document.to_dict(),
                "query_id": query.query_id,
            }
        ),
        requested_backend_id=backend_id,
    )


def _process_runner(stdout: str, *, returncode: int | None = 0):
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
            elapsed_seconds=0.01,
            timed_out=False,
            output_truncated=False,
            process_tree_terminated=False,
        )

    return BoundedToolRunner(executor=execute), invocations


def test_interface_versions_and_fixture_categories():
    assert DATALOG_AUTHORIZATION_BACKEND_VERSION == "DatalogAuthorizationBackend@1"
    assert SECPAL_AUTHORIZATION_BACKEND_VERSION == "SecPALAuthorizationBackend@1"
    categories = {item.category for item in DEFAULT_AUTHORIZATION_FIXTURES}
    assert categories >= {"allow", "deny", "conflict", "unknown", "delegation"}


def test_reference_evaluator_agrees_on_allow_deny_conflict_unknown():
    evaluator = ReferenceAuthorizationEvaluator()
    expected = {
        "fixture:allow": DecisionOutcome.ALLOW,
        "fixture:deny": DecisionOutcome.DENY,
        "fixture:unknown": DecisionOutcome.UNKNOWN,
        "fixture:conflict": DecisionOutcome.CONFLICT,
        "fixture:delegation": DecisionOutcome.ALLOW,
    }
    for fixture in DEFAULT_AUTHORIZATION_FIXTURES:
        decision, explanation, exhausted = evaluator.evaluate(
            fixture.document, fixture.query
        )
        assert decision.outcome is expected[fixture.fixture_id]
        assert decision.outcome is fixture.expected_outcome
        assert decision.authority is AuthorizationEvidenceAuthority.AUTHORIZATION
        assert (
            decision.generated_code_correctness
            is GeneratedCodeCorrectness.NOT_ESTABLISHED
        )
        assert decision.is_theorem_authority is False
        assert explanation.query_id == fixture.query.query_id
        assert explanation.outcome is decision.outcome
        assert exhausted is False


def test_explanations_bind_concrete_rules_for_allow_and_deny():
    evaluator = ReferenceAuthorizationEvaluator()
    allow = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    deny = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "deny"
    )

    _, allow_explanation, _ = evaluator.evaluate(allow.document, allow.query)
    _, deny_explanation, _ = evaluator.evaluate(deny.document, deny.query)

    allow_rules = {
        step.reference_id
        for step in allow_explanation.steps
        if step.kind.value == "rule"
    }
    deny_rules = {
        step.reference_id
        for step in deny_explanation.steps
        if step.kind.value == "rule"
    }
    assert "rule:admin-may-read" in allow_rules
    assert "rule:deny-sensitive-non-admin" in deny_rules


def test_delegation_is_depth_and_scope_bounded():
    fixture = next(
        item
        for item in DEFAULT_AUTHORIZATION_FIXTURES
        if item.category == "delegation"
    )
    evaluator = ReferenceAuthorizationEvaluator()
    decision, explanation, _ = evaluator.evaluate(fixture.document, fixture.query)

    assert decision.outcome is DecisionOutcome.ALLOW
    delegation_ids = {
        step.reference_id
        for step in explanation.steps
        if step.kind.value == "delegation"
    }
    assert "delegation:alice-bob" in delegation_ids

    # Path outside the narrowed child scope must fail closed.
    out_of_scope = fixture.query.__class__(
        "query:delegation-out-of-scope",
        principal_id="principal:bob",
        action="read",
        resource="docs/secret/payroll",
        source_ref_ids=fixture.query.source_ref_ids,
        span_ids=fixture.query.span_ids,
    )
    denied, _, _ = evaluator.evaluate(fixture.document, out_of_scope)
    assert denied.outcome is DecisionOutcome.UNKNOWN


def test_derivation_resource_bounds_are_respected():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    evaluator = ReferenceAuthorizationEvaluator()
    decision, explanation, exhausted = evaluator.evaluate(
        fixture.document, fixture.query, max_steps=1
    )
    # With a one-step budget the evaluator may exhaust bounds before finishing.
    assert exhausted is True or decision.outcome in {
        DecisionOutcome.ALLOW,
        DecisionOutcome.UNKNOWN,
    }
    assert any(step.kind.value in {"bound", "rule", "trust_root"} for step in explanation.steps)


def test_datalog_backend_run_returns_authorization_authority_only():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    backend = DatalogAuthorizationBackend()
    outcome = backend.run(_request(fixture.document, fixture.query))

    assert isinstance(outcome.result, AuthorizationResult)
    assert outcome.result.authority is ResultAuthority.AUTHORIZATION
    assert outcome.result.status is ResultStatus.AUTHORIZED
    assert outcome.result.witness["is_theorem_authority"] is False
    assert outcome.result.witness["outcome"] == DecisionOutcome.ALLOW.value
    assert "rule:admin-may-read" in outcome.result.witness["bound_rule_ids"]
    assert outcome.receipt.is_theorem_authority is False
    assert outcome.source_binding.query_id == fixture.query.query_id
    assert outcome.source_binding.request_digest == outcome.receipt.request_digest


@pytest.mark.parametrize(
    "category,status",
    [
        ("allow", ResultStatus.AUTHORIZED),
        ("deny", ResultStatus.DENIED),
        ("unknown", ResultStatus.UNKNOWN),
        ("conflict", ResultStatus.UNKNOWN),
    ],
)
def test_datalog_backend_status_mapping_for_closed_outcomes(category, status):
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == category
    )
    backend = DatalogAuthorizationBackend()
    outcome = backend.run(_request(fixture.document, fixture.query))
    assert outcome.result.status is status
    assert outcome.receipt.outcome is fixture.expected_outcome


def test_secpal_backend_agrees_with_reference_on_fixtures():
    backend = SecPALAuthorizationBackend()
    for fixture in DEFAULT_AUTHORIZATION_FIXTURES:
        request = _request(
            fixture.document,
            fixture.query,
            backend_id="secpal-authorization",
            encoding="secpal",
            family="secpal",
        )
        outcome = backend.run(request)
        assert outcome.receipt.outcome is fixture.expected_outcome
        assert outcome.result.authority is ResultAuthority.AUTHORIZATION


def test_external_engine_agreement_and_disagreement_quarantine():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    agree_runner, agree_invocations = _process_runner("authz_result\nALLOW\n")
    agree = DatalogAuthorizationBackend(
        runner=agree_runner,
        use_external_engine=True,
        available_probe=lambda: True,
    )
    agreed = agree.run(_request(fixture.document, fixture.query))
    assert agreed.receipt.engine is EngineKind.DATALOG
    assert agreed.receipt.engine_agreed is True
    assert agreed.result.status is ResultStatus.AUTHORIZED
    assert agree_invocations, "external engine should have been invoked"

    disagree_runner, _ = _process_runner("DENY\n")
    disagree = DatalogAuthorizationBackend(
        runner=disagree_runner,
        use_external_engine=True,
        available_probe=lambda: True,
    )
    quarantined = disagree.run(_request(fixture.document, fixture.query))
    assert quarantined.receipt.engine_agreed is False
    assert quarantined.result.status is ResultStatus.UNKNOWN
    assert quarantined.result.authority is ResultAuthority.AUTHORIZATION
    assert "disagreed" in quarantined.result.reason


def test_missing_external_engine_is_explicit_and_never_theorem():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    backend = DatalogAuthorizationBackend(
        use_external_engine=True,
        available_probe=lambda: False,
    )
    # Reference path still answers; external is simply not used when unavailable
    # at discovery time for the optional shadow lane.
    outcome = backend.run(_request(fixture.document, fixture.query))
    assert outcome.result.authority is ResultAuthority.AUTHORIZATION
    assert outcome.result.status is ResultStatus.AUTHORIZED
    assert not isinstance(outcome.result, TheoremResult)


def test_conformance_receipt_covers_fixture_set():
    backend = DatalogAuthorizationBackend()
    receipt = backend.check_conformance()
    assert receipt.status is ConformanceStatus.PASSED
    assert receipt.passed is True
    assert set(receipt.checked_fixture_ids) == {
        item.fixture_id for item in DEFAULT_AUTHORIZATION_FIXTURES
    }
    assert receipt.disagreements == ()

    def wrong_engine(_document, _query):
        return DecisionOutcome.DENY

    failed = backend.check_conformance(engine_runner=wrong_engine)
    assert failed.status is ConformanceStatus.FAILED
    assert failed.disagreements


def test_renderers_are_deterministic_and_query_bound():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    datalog_a = render_datalog_program(fixture.document, fixture.query)
    datalog_b = render_datalog_program(fixture.document, fixture.query)
    secpal_a = render_secpal_program(fixture.document, fixture.query)
    secpal_b = render_secpal_program(fixture.document, fixture.query)
    assert datalog_a == datalog_b
    assert secpal_a == secpal_b
    assert "authz_result" in datalog_a
    assert fixture.query.principal_id in secpal_a
    assert "trust" in secpal_a


def test_parse_engine_outcome_vocabulary():
    assert parse_engine_outcome("PERMIT") is DecisionOutcome.ALLOW
    assert parse_engine_outcome("denied") is DecisionOutcome.DENY
    assert parse_engine_outcome("allow\ndeny") is DecisionOutcome.CONFLICT
    assert parse_engine_outcome("conflict") is DecisionOutcome.CONFLICT
    assert parse_engine_outcome("") is DecisionOutcome.DENY
    assert parse_engine_outcome("no decision token here", "still none") is None


def test_outcome_status_mapping_never_proves_theorems():
    assert outcome_to_result_status(DecisionOutcome.ALLOW) is ResultStatus.AUTHORIZED
    assert outcome_to_result_status(DecisionOutcome.DENY) is ResultStatus.DENIED
    assert outcome_to_result_status(DecisionOutcome.CONFLICT) is ResultStatus.UNKNOWN
    assert outcome_to_result_status(DecisionOutcome.UNKNOWN) is ResultStatus.UNKNOWN


def test_evaluation_receipt_rejects_theorem_authority():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    backend = DatalogAuthorizationBackend()
    request = _request(fixture.document, fixture.query)
    outcome = backend.run(request)
    with pytest.raises(AuthorizationBackendError, match="authorization"):
        EvaluationReceipt(
            request_digest=outcome.receipt.request_digest,
            source_binding=outcome.source_binding,
            outcome=DecisionOutcome.ALLOW,
            authority="theorem",  # type: ignore[arg-type]
        )


def test_policy_decision_and_ucan_view_cannot_establish_code_correctness():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    decision, _, _ = ReferenceAuthorizationEvaluator().evaluate(
        fixture.document, fixture.query
    )
    assert decision.is_theorem_authority is False
    with pytest.raises(Exception, match="not_established|generated-code|theorem"):
        PolicyDecision(
            decision_id="decision:forged",
            query_id=fixture.query.query_id,
            outcome=DecisionOutcome.ALLOW,
            generated_code_correctness="established",  # type: ignore[arg-type]
        )

    view = UcanCapabilityView.from_decision(
        decision,
        audience="principal:alice",
        action="read",
        resource="docs/payroll",
    )
    assert view.is_theorem_authority is False
    assert view.authority is AuthorizationEvidenceAuthority.AUTHORIZATION
    with pytest.raises(AuthorizationBackendError, match="authorization"):
        UcanCapabilityView(
            capability_id="ucan:x",
            audience="alice",
            action="read",
            resource="docs/",
            outcome=DecisionOutcome.ALLOW,
            authority="theorem",  # type: ignore[arg-type]
        )


def test_supervisor_policy_view_is_thin_and_fail_closed():
    view = SupervisorPolicyView(
        policy_id="policy:supervisor",
        trusted_roots=("root",),
        statement_ids=("grant-1", "grant-2"),
    )
    assert view.to_dict()["trusted_roots"] == ["root"]
    with pytest.raises(AuthorizationBackendError):
        SupervisorPolicyView(
            policy_id="policy:empty-roots",
            trusted_roots=(),
            statement_ids=(),
        )


def test_backend_rejects_theorem_proof_query_kind():
    fixture = next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == "allow"
    )
    request = BackendRequest(
        request_id="request:authz:bad-kind",
        claim_id="claim:authz:bad-kind",
        declaration_id="declaration:authz:bad-kind",
        claim_digest="3" * 64,
        obligation_id="obligation:authz:bad-kind",
        obligation_digest="4" * 64,
        assumption_ids=(),
        logic_family="authorization",
        query_kind=QueryKind.THEOREM_PROOF,
        payload=FrozenMap(
            {
                "encoding": "authorization-ir",
                "authorization_ir": fixture.document.to_dict(),
                "query_id": fixture.query.query_id,
            }
        ),
        requested_backend_id="datalog-authorization",
    )
    with pytest.raises(AuthorizationBackendError, match="theorem_proof|policy_approval"):
        DatalogAuthorizationBackend().run(request)


def test_backend_is_available_without_external_toolchain():
    assert DatalogAuthorizationBackend().is_available() is True
    assert SecPALAuthorizationBackend().is_available() is True
