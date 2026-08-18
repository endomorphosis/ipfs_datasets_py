"""Public-facade tests for the compositional-verification P1--P5 slice.

These tests intentionally call :mod:`logic.verification_api` rather than the
implementation modules.  The facade is the compatibility boundary shared by
the accelerator; the underlying typed artifacts remain datasets-owned.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5SoftwareVerificationBackend
from ipfs_datasets_py.logic.backends.smt.compiler import (
    INT_SORT,
    SmtFunDecl,
    SmtNamedAssertion,
    SmtObligation,
    SmtQueryMode,
    SmtTerm,
    SmtTermKind,
    term_int,
    term_symbol,
)
from ipfs_datasets_py.logic.backends.smt.differential import (
    DifferentialClassification,
    SmtDifferentialReport,
    SmtRawSolverOutput,
    SmtSolverVerdict,
)
from ipfs_datasets_py.logic.backends.smt.incremental import (
    IncrementalSmtUnavailable,
    SmtCheckStatus,
)
from ipfs_datasets_py.logic.backends.smt.interpolation import InterpolationStatus
from ipfs_datasets_py.logic.backends.z3.compiler import Z3SoftwareVerificationBackend
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_contracts.compositional import (
    CompositionalContract,
    SemanticContractClause,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    BoundedPredicate,
    CallableContract,
    ContractAuthority,
    ContractProvenance,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    RepositoryState,
)
from ipfs_datasets_py.logic.software_verification.abstract_interpretation import (
    ConstantValue,
)
from ipfs_datasets_py.logic.software_verification.assume_guarantee import (
    ComponentCompositionGraph,
    CompositionEdge,
    DischargeDisposition,
)
from ipfs_datasets_py.logic.verification_api import (
    COMPOSITIONAL_ABSTRACT_ANALYSIS_INTERFACE,
    COMPOSITIONAL_ABSTRACT_ANALYSIS_SCHEMA,
    COMPOSITIONAL_ASSUME_GUARANTEE_INTERFACE,
    COMPOSITIONAL_ASSUME_GUARANTEE_RECEIPT_SCHEMA,
    COMPOSITIONAL_CONTRACT_INTERFACE,
    COMPOSITIONAL_CONTRACT_SCHEMA,
    COMPOSITIONAL_INCREMENTAL_SMT_INTERFACE,
    COMPOSITIONAL_INCREMENTAL_SMT_SCHEMA,
    COMPOSITIONAL_INCREMENTAL_VERIFICATION_INTERFACE,
    COMPOSITIONAL_INCREMENTAL_VERIFICATION_RECEIPT_SCHEMA,
    COMPOSITIONAL_INTERPOLATION_INTERFACE,
    COMPOSITIONAL_INTERPOLATION_RECEIPT_SCHEMA,
    COMPOSITIONAL_SMT_DIFFERENTIAL_INTERFACE,
    COMPOSITIONAL_SMT_DIFFERENTIAL_SCHEMA,
    COMPOSITIONAL_VERIFICATION_OPERATIONS,
    VerificationAPIError,
    analyze_abstract_state,
    compile_component_contract,
    compute_and_validate_interpolant,
    discharge_assume_guarantee,
    get_verification_api,
    open_incremental_smt_session,
    plan_incremental_verification,
    run_z3_cvc5_differential,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        fact_kind="inferred",
        authority=ContractAuthority(
            authority_id="authority:public-api-test",
            rank="inference",
            owner="ipfs_datasets_py.logic",
            revision="public-api-test@1",
        ),
        source_path="fixture.py",
        source_symbol="fixture.value",
    )


def _roots() -> dict[str, str]:
    return {
        name: f"sha256:{index:064x}"
        for index, name in enumerate(
            (
                "source_root",
                "ast_root",
                "symbol_version_root",
                "interface_root",
                "configuration_root",
                "toolchain_root",
            ),
            1,
        )
    }


def _clause(clause_id: str, kind: str, lower: int, upper: int) -> SemanticContractClause:
    return SemanticContractClause(
        clause_id=clause_id,
        kind=kind,
        support="typed_inline",
        predicate=BoundedPredicate(
            predicate_id=f"{clause_id}:predicate",
            role="assumption" if kind == "assumption" else "postcondition",
            operator="range_int",
            subject="return",
            provenance=_provenance(),
            arguments=(lower, upper),
        ),
    )


def _contract(
    component: str,
    *,
    assumptions: tuple[SemanticContractClause, ...] = (),
    guarantees: tuple[SemanticContractClause, ...] = (),
) -> CompositionalContract:
    return CompositionalContract(
        contract_id=f"contract:{component}",
        component_id=component,
        component_kind="callable",
        provenance=_provenance(),
        assumptions=assumptions,
        guarantees=guarantees,
        confidence="conservative",
        semantic_support_class="supported_subset",
        **_roots(),
    )


def _range(symbol: str, lower: int, upper: int) -> SmtTerm:
    value = term_symbol(symbol)
    return SmtTerm(
        SmtTermKind.AND,
        arguments=(
            SmtTerm(SmtTermKind.GE, arguments=(value, term_int(lower))),
            SmtTerm(SmtTermKind.LE, arguments=(value, term_int(upper))),
        ),
    )


def test_public_facade_advertises_and_executes_analysis_and_v1_contract_adapter() -> None:
    api = get_verification_api(reset=True)
    assert tuple(api.to_dict()["compositional_verification_operations"]) == (
        COMPOSITIONAL_VERIFICATION_OPERATIONS
    )

    analysis = analyze_abstract_state(
        "def answer():\n    return 42\n", source_uri="fixture://public-api.py"
    )
    assert analysis.summaries_by_name["answer"].return_value.constant == (
        ConstantValue.constant(42)
    )

    predicate = BoundedPredicate(
        predicate_id="answer:postcondition",
        role="postcondition",
        operator="range_int",
        subject="return",
        provenance=_provenance(),
        arguments=(42, 42),
    )
    legacy = CallableContract(
        contract_id="contract:legacy-answer",
        qualified_name="fixture.answer",
        owner_module="fixture",
        shape="sync_function",
        provenance=_provenance(),
        postconditions=(predicate,),
    )
    compiled = compile_component_contract(legacy, **_roots())
    assert compiled.component_id == "fixture.answer"
    assert compiled.normal_postconditions[0].predicate == predicate
    assert compiled.attributes.to_dict()["adapted_from"] == "CallableContract@v1"


def test_public_facade_discharge_and_incremental_plan_return_typed_receipts() -> None:
    producer = _contract(
        "A", guarantees=(_clause("A:guarantee", "guarantee", 0, 10),)
    )
    consumer = _contract(
        "B", assumptions=(_clause("B:assumption", "assumption", 0, 20),)
    )
    state = RepositoryState("repository:public-compositional-api")
    graph = ComponentCompositionGraph(
        semantic_state_root=state.state_cid,
        contracts=(producer, consumer),
        edges=(
            CompositionEdge(
                edge_id="A-to-B",
                producer_component_id="A",
                consumer_component_id="B",
                guarantee_clause_ids=("A:guarantee",),
                assumption_clause_ids=("B:assumption",),
            ),
        ),
    )

    discharge = discharge_assume_guarantee(
        graph,
        expected_semantic_state_root=state.state_cid,
        expected_contract_root=graph.contract_root,
    )
    assert discharge.disposition is DischargeDisposition.PROVED
    assert discharge.receipt_cid.startswith("b")

    plan = plan_incremental_verification(
        state,
        state,
        composition_graph=graph,
        previous_composition_graph=graph,
    )
    assert plan.previous_state_cid == state.state_cid
    assert plan.current_state_cid == state.state_cid
    assert plan.changed_symbol_ids == ()
    assert plan.reverse_contract_closure == ()
    assert plan.receipt_cid.startswith("b")


def test_public_incremental_smt_replay_identity_excludes_process_statistics() -> None:
    def solve_once():
        session = open_incremental_smt_session(
            session_id="public-replay-session",
            translator_identity="translator:public-api-test@1",
            theory_fingerprint="QF_LIA:public-api-test@1",
            policy_root="policy:deny-network@1",
            configuration_root="configuration:public-api-test@1",
            environment_root="environment:public-api-test@1",
            deterministic_seed=0,
        )
        session.declare_symbol("x", INT_SORT)
        session.add_named_assertion(
            "lower",
            SmtTerm(SmtTermKind.GE, arguments=(term_symbol("x"), term_int(3))),
            source_ref="fixture.py:1",
            obligation_id="obligation:public-range",
        )
        session.add_named_assertion(
            "upper",
            SmtTerm(SmtTermKind.LE, arguments=(term_symbol("x"), term_int(2))),
            source_ref="fixture.py:2",
            obligation_id="obligation:public-range",
        )
        result = session.check()
        manifest = session.snapshot_or_replay_manifest()
        session.close()
        return result, manifest

    first, first_manifest = solve_once()
    replayed, replayed_manifest = solve_once()
    assert first.status is SmtCheckStatus.UNSAT
    assert first.core_validated
    assert first.receipt_id == replayed.receipt_id
    assert first_manifest["manifest_cid"] == replayed_manifest["manifest_cid"]

    # Statistics are useful observation telemetry, but are process-local and
    # cannot participate in the semantic evidence identity.
    changed_statistics = replace(first, statistics={"synthetic allocation count": 999_999})
    assert changed_statistics.to_dict()["statistics"] != first.to_dict()["statistics"]
    assert changed_statistics.receipt_id == first.receipt_id


def test_public_interpolation_wrapper_returns_independently_validated_receipt() -> None:
    receipt = compute_and_validate_interpolant(
        _range("x", 0, 10),
        _range("x", 20, 30),
    )
    assert receipt.status is InterpolationStatus.VALIDATED
    assert receipt.interpolant is not None
    assert set(receipt.interpolant_vocabulary) <= {"x"}
    assert receipt.a_implies_i_receipt.startswith("b")
    assert receipt.i_and_b_unsat_receipt.startswith("b")
    assert receipt.schema == COMPOSITIONAL_INTERPOLATION_RECEIPT_SCHEMA
    assert receipt.receipt_cid.startswith("b")


def _arith_vc_obligation() -> SmtObligation:
    """Reviewed QF_LIA common-fragment fixture: x >= 1 entails x > 0."""

    x = term_symbol("x")
    return SmtObligation(
        obligation_id="obl:public-vc-x-positive",
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=("arithmetic", "equality", "verification_conditions"),
        goal=SmtTerm(SmtTermKind.GT, arguments=(x, term_int(0))),
        assumptions=(
            SmtNamedAssertion(
                formula=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(1))),
                name="assume_ge_one",
            ),
        ),
        functions=(SmtFunDecl(name="x", range=INT_SORT, is_const=True),),
        request_unsat_core=True,
        property_ids=("property:public-vc-x-positive",),
    )


def _fixed_runner(stdout: str, **kwargs):
    def run(_smtlib: str, _bounds: ExecutionBounds) -> SmtRawSolverOutput:
        return SmtRawSolverOutput(
            stdout=stdout,
            stderr=kwargs.get("stderr", ""),
            returncode=kwargs.get("returncode", 0),
            elapsed_ms=kwargs.get("elapsed_ms", 7),
            solver_version=kwargs.get("solver_version", "mock-solver/1.0"),
            timed_out=kwargs.get("timed_out", False),
            unavailable=kwargs.get("unavailable", False),
        )

    return run


def _bounds() -> ExecutionBounds:
    return ExecutionBounds(
        timeout_ms=5_000,
        max_steps=100_000,
        max_memory_bytes=64 * 1024 * 1024,
        max_output_bytes=65_536,
    )


def test_public_adapters_are_checked_and_preserve_artifact_identities() -> None:
    analysis = analyze_abstract_state(
        "def answer():\n    return 42\n", source_uri="fixture://public-api.py"
    )
    assert analysis.INTERFACE == COMPOSITIONAL_ABSTRACT_ANALYSIS_INTERFACE
    assert analysis.schema_version == COMPOSITIONAL_ABSTRACT_ANALYSIS_SCHEMA
    assert analysis.analysis_id.startswith("b")

    compiled = compile_component_contract(
        CallableContract(
            contract_id="contract:checked-answer",
            qualified_name="fixture.answer",
            owner_module="fixture",
            shape="sync_function",
            provenance=_provenance(),
            postconditions=(
                BoundedPredicate(
                    predicate_id="answer:postcondition",
                    role="postcondition",
                    operator="range_int",
                    subject="return",
                    provenance=_provenance(),
                    arguments=(42, 42),
                ),
            ),
        ),
        **_roots(),
    )
    assert compiled.schema == COMPOSITIONAL_CONTRACT_SCHEMA
    assert compiled.cid.startswith("b")
    assert getattr(compiled, "INTERFACE", COMPOSITIONAL_CONTRACT_INTERFACE) == (
        COMPOSITIONAL_CONTRACT_INTERFACE
    )

    producer = _contract("A", guarantees=(_clause("A:guarantee", "guarantee", 0, 10),))
    consumer = _contract("B", assumptions=(_clause("B:assumption", "assumption", 0, 20),))
    state = RepositoryState("repository:public-checked-api")
    graph = ComponentCompositionGraph(
        semantic_state_root=state.state_cid,
        contracts=(producer, consumer),
        edges=(
            CompositionEdge(
                edge_id="A-to-B",
                producer_component_id="A",
                consumer_component_id="B",
                guarantee_clause_ids=("A:guarantee",),
                assumption_clause_ids=("B:assumption",),
            ),
        ),
    )
    discharge = discharge_assume_guarantee(
        graph,
        expected_semantic_state_root=state.state_cid,
        expected_contract_root=graph.contract_root,
    )
    assert discharge.schema == COMPOSITIONAL_ASSUME_GUARANTEE_RECEIPT_SCHEMA
    assert discharge.receipt_cid.startswith("b")
    assert getattr(discharge, "INTERFACE", COMPOSITIONAL_ASSUME_GUARANTEE_INTERFACE) == (
        COMPOSITIONAL_ASSUME_GUARANTEE_INTERFACE
    )

    plan = plan_incremental_verification(
        state,
        state,
        composition_graph=graph,
        previous_composition_graph=graph,
    )
    assert plan.schema == COMPOSITIONAL_INCREMENTAL_VERIFICATION_RECEIPT_SCHEMA
    assert plan.receipt_cid.startswith("b")
    assert plan.identity_payload()["interface"] == (
        COMPOSITIONAL_INCREMENTAL_VERIFICATION_INTERFACE
    )
    assert plan.invalidation_plan_cid
    assert plan.changed_symbol_ids == ()
    assert plan.invalidated_contract_cids == ()


def test_public_adapters_reject_missing_inputs_fail_closed() -> None:
    with pytest.raises(VerificationAPIError, match="source"):
        analyze_abstract_state("")
    with pytest.raises(VerificationAPIError, match="contract"):
        compile_component_contract(None)
    with pytest.raises(VerificationAPIError, match="graph"):
        discharge_assume_guarantee(None)
    with pytest.raises(VerificationAPIError, match="previous_state"):
        plan_incremental_verification(None, object())
    with pytest.raises(VerificationAPIError, match="partition_a"):
        compute_and_validate_interpolant(None, _range("x", 0, 1))
    with pytest.raises(VerificationAPIError, match="obligation"):
        run_z3_cvc5_differential(None)


def test_public_session_cancel_is_typed_and_does_not_raise_authority() -> None:
    session = open_incremental_smt_session(
        session_id="public-cancel-session",
        translator_identity="translator:public-api-test@1",
        theory_fingerprint="QF_LIA:public-api-test@1",
        policy_root="policy:deny-network@1",
        configuration_root="configuration:public-api-test@1",
        environment_root="environment:public-api-test@1",
        deterministic_seed=0,
        timeout_ms=250,
    )
    assert session.interface == COMPOSITIONAL_INCREMENTAL_SMT_INTERFACE
    assert session.fingerprint.schema == COMPOSITIONAL_INCREMENTAL_SMT_SCHEMA
    assert session.fingerprint.timeout_ms == 250
    session.cancel()
    cancelled = session.check()
    assert cancelled.status is SmtCheckStatus.CANCELLED
    assert "incremental_reuse_does_not_raise_evidence_authority" in cancelled.limitations
    session.close()
    with pytest.raises(ValueError, match="closed"):
        session.check()


def test_public_unqualified_provider_stays_typed_unavailable() -> None:
    with pytest.raises(IncrementalSmtUnavailable, match="cvc5"):
        open_incremental_smt_session(
            session_id="public-cvc5-session",
            provider="cvc5",
            translator_identity="translator:public-api-test@1",
            theory_fingerprint="QF_LIA:public-api-test@1",
            policy_root="policy:deny-network@1",
            configuration_root="configuration:public-api-test@1",
            environment_root="environment:public-api-test@1",
        )


def test_public_differential_agreement_receipt_is_checked() -> None:
    report = run_z3_cvc5_differential(
        _arith_vc_obligation(),
        bounds=_bounds(),
        z3_backend=Z3SoftwareVerificationBackend(
            runner=_fixed_runner("unsat\n(assume_ge_one)\n", solver_version="z3-mock"),
            availability_probe=lambda: True,
        ),
        cvc5_backend=CVC5SoftwareVerificationBackend(
            runner=_fixed_runner(
                "unsat\n(\nassume_ge_one\n)\n", solver_version="cvc5-mock"
            ),
            availability_probe=lambda: True,
        ),
    )
    assert isinstance(report, SmtDifferentialReport)
    assert report.interface == COMPOSITIONAL_SMT_DIFFERENTIAL_INTERFACE
    assert report.schema_version == COMPOSITIONAL_SMT_DIFFERENTIAL_SCHEMA
    assert report.agreement is True
    assert report.classification is DifferentialClassification.AGREE_PROVED
    assert report.left.verdict is SmtSolverVerdict.UNSAT
    assert report.right.verdict is SmtSolverVerdict.UNSAT
    assert report.left.compilation.script.digest == report.right.compilation.script.digest
    assert report.script_digest == report.compilation.script.digest
    payload = report.to_dict()
    assert payload["report_id"] == report.report_id
    assert payload["translation_receipt_id"] == report.compilation.receipt.receipt_id


def test_public_differential_disagreement_returns_typed_discrepancy() -> None:
    report = run_z3_cvc5_differential(
        _arith_vc_obligation(),
        bounds=_bounds(),
        z3_backend=Z3SoftwareVerificationBackend(
            runner=_fixed_runner("unsat\n", solver_version="z3-mock"),
            availability_probe=lambda: True,
        ),
        cvc5_backend=CVC5SoftwareVerificationBackend(
            runner=_fixed_runner("sat\n", solver_version="cvc5-mock"),
            availability_probe=lambda: True,
        ),
    )
    assert report.agreement is False
    assert report.classification is DifferentialClassification.DISAGREE
    evidence = report.disagreement_evidence.to_dict()
    assert evidence["preserved"] is True
    assert evidence["left"]["verdict"] == "unsat"
    assert evidence["right"]["verdict"] == "sat"
    assert evidence["script_digest"] == report.script_digest
    assert report.report_id


def test_public_differential_unavailable_solvers_stay_typed() -> None:
    partial = run_z3_cvc5_differential(
        _arith_vc_obligation(),
        bounds=_bounds(),
        z3_backend=Z3SoftwareVerificationBackend(
            runner=_fixed_runner("unsat\n"),
            availability_probe=lambda: True,
        ),
        cvc5_backend=CVC5SoftwareVerificationBackend(
            runner=_fixed_runner("", unavailable=True),
            availability_probe=lambda: False,
        ),
    )
    assert partial.classification is DifferentialClassification.PARTIAL_UNAVAILABLE
    assert partial.agreement is False

    both = run_z3_cvc5_differential(
        _arith_vc_obligation(),
        bounds=_bounds(),
        z3_backend=Z3SoftwareVerificationBackend(
            runner=_fixed_runner("", unavailable=True),
            availability_probe=lambda: False,
        ),
        cvc5_backend=CVC5SoftwareVerificationBackend(
            runner=_fixed_runner("", unavailable=True),
            availability_probe=lambda: False,
        ),
    )
    assert both.classification is DifferentialClassification.BOTH_UNAVAILABLE
    assert both.agreement is False


def test_public_bounded_solver_differential_agrees_or_returns_typed_discrepancy() -> None:
    report = run_z3_cvc5_differential(_arith_vc_obligation(), bounds=_bounds())
    assert report.interface == COMPOSITIONAL_SMT_DIFFERENTIAL_INTERFACE
    assert report.schema_version == COMPOSITIONAL_SMT_DIFFERENTIAL_SCHEMA
    assert report.classification in DifferentialClassification
    if report.classification is DifferentialClassification.DISAGREE:
        evidence = report.disagreement_evidence.to_dict()
        assert report.agreement is False
        assert evidence["preserved"] is True
        assert evidence["left"]["verdict"]
        assert evidence["right"]["verdict"]
        return
    if report.classification in {
        DifferentialClassification.AGREE_PROVED,
        DifferentialClassification.AGREE_DISPROVED,
        DifferentialClassification.AGREE_SATISFIABLE,
        DifferentialClassification.AGREE_UNSATISFIABLE,
        DifferentialClassification.AGREE_UNKNOWN,
    }:
        assert report.agreement is True
        if (
            report.left.verdict in {SmtSolverVerdict.SAT, SmtSolverVerdict.UNSAT}
            and report.right.verdict in {SmtSolverVerdict.SAT, SmtSolverVerdict.UNSAT}
        ):
            assert report.classification is DifferentialClassification.AGREE_PROVED
            assert report.left.verdict is SmtSolverVerdict.UNSAT
            assert report.right.verdict is SmtSolverVerdict.UNSAT
        return
    assert report.classification in {
        DifferentialClassification.PARTIAL_UNAVAILABLE,
        DifferentialClassification.BOTH_UNAVAILABLE,
        DifferentialClassification.MALFORMED,
        DifferentialClassification.ERROR,
    }
    assert report.agreement is False


def test_compositional_verification_api_cold_import_loads_no_solver() -> None:
    script = """
import json
import sys
import ipfs_datasets_py.logic.verification_api as api
forbidden = (
    "z3",
    "cvc5",
    "ipfs_datasets_py.logic.backends.smt.incremental",
    "ipfs_datasets_py.logic.backends.smt.interpolation",
    "ipfs_datasets_py.logic.backends.smt.differential",
    "ipfs_datasets_py.logic.software_verification.abstract_interpretation",
    "ipfs_datasets_py.logic.software_verification.assume_guarantee",
    "ipfs_datasets_py.logic.software_verification.incremental_verification",
    "ipfs_datasets_py.logic.software_contracts.compositional",
)
print(json.dumps({
    "operations": list(api.COMPOSITIONAL_VERIFICATION_OPERATIONS),
    "loaded": sorted(name for name in forbidden if name in sys.modules),
}))
"""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["operations"] == list(COMPOSITIONAL_VERIFICATION_OPERATIONS)
    assert payload["loaded"] == []
