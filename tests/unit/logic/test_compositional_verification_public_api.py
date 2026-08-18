"""Public-facade tests for the compositional-verification P1--P5 slice.

These tests intentionally call :mod:`logic.verification_api` rather than the
implementation modules.  The facade is the compatibility boundary shared by
the accelerator; the underlying typed artifacts remain datasets-owned.
"""

from __future__ import annotations

from dataclasses import replace

from ipfs_datasets_py.logic.backends.smt.compiler import (
    INT_SORT,
    SmtTerm,
    SmtTermKind,
    term_int,
    term_symbol,
)
from ipfs_datasets_py.logic.backends.smt.incremental import SmtCheckStatus
from ipfs_datasets_py.logic.backends.smt.interpolation import InterpolationStatus
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
    COMPOSITIONAL_VERIFICATION_OPERATIONS,
    analyze_abstract_state,
    compile_component_contract,
    compute_and_validate_interpolant,
    discharge_assume_guarantee,
    get_verification_api,
    open_incremental_smt_session,
    plan_incremental_verification,
)


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
