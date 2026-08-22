from __future__ import annotations

import pytest
from ipfs_datasets_py.logic.software_contracts.compositional import (
    ClauseKind,
    CompositionalContract,
    CompositionalContractError,
    SemanticContractClause,
    SemanticSupport,
    adapt_callable_contract,
    adapt_rely_guarantee_contract,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    Assumption,
    BoundedPredicate,
    CallableContract,
    ContractAuthority,
    ContractProvenance,
)
from ipfs_datasets_py.logic.software_verification.concurrency import (
    RelyGuaranteeContract,
)


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        fact_kind="inferred",
        authority=ContractAuthority(
            authority_id="authority:test",
            rank="inference",
            owner="datasets",
            revision="test-revision",
        ),
        source_path="module.py",
        source_symbol="module.value",
    )


def _roots() -> dict[str, str]:
    names = (
        "source_root",
        "ast_root",
        "symbol_version_root",
        "interface_root",
        "configuration_root",
        "toolchain_root",
    )
    return {name: f"sha256:{index:064x}" for index, name in enumerate(names, 1)}


def test_typed_contract_round_trip_and_content_identity() -> None:
    predicate = BoundedPredicate(
        predicate_id="return.range",
        role="postcondition",
        operator="range_int",
        subject="return",
        provenance=_provenance(),
        arguments=(0, 10),
    )
    clause = SemanticContractClause(
        clause_id="guarantee:range",
        kind=ClauseKind.GUARANTEE,
        support=SemanticSupport.TYPED_INLINE,
        predicate=predicate,
    )
    contract = CompositionalContract(
        contract_id="contract:a",
        component_id="module.a",
        component_kind="callable",
        provenance=_provenance(),
        guarantees=(clause,),
        confidence="conservative",
        semantic_support_class="supported_subset",
        **_roots(),
    )

    restored = CompositionalContract.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.cid == contract.cid
    assert restored.guarantees[0].can_discharge


def test_opaque_semantics_cannot_claim_exact_confidence() -> None:
    clause = SemanticContractClause(
        clause_id="legacy:statement",
        kind="assumption",
        support="opaque",
        annotation="the environment probably returns a positive integer",
    )
    with pytest.raises(CompositionalContractError, match="opaque clauses"):
        CompositionalContract(
            contract_id="contract:opaque",
            component_id="module.opaque",
            component_kind="callable",
            provenance=_provenance(),
            assumptions=(clause,),
            confidence="exact",
            semantic_support_class="partial",
            **_roots(),
        )


def test_callable_v1_adapter_retains_prose_as_opaque_not_true() -> None:
    legacy = CallableContract(
        contract_id="contract:legacy",
        qualified_name="module.legacy",
        owner_module="module",
        shape="sync_function",
        provenance=_provenance(),
        assumptions=(
            Assumption(
                assumption_id="assumption:legacy",
                statement="configuration is valid",
                provenance=_provenance(),
            ),
        ),
    )
    adapted = adapt_callable_contract(legacy, **_roots())

    assert adapted.assumptions[0].support is SemanticSupport.OPAQUE
    assert not adapted.assumptions[0].can_discharge
    assert adapted.confidence.value == "opaque"
    assert "legacy_v1_prose_assumptions_are_opaque" in adapted.limitations


def test_rely_guarantee_v1_adapter_does_not_compare_strings() -> None:
    legacy = RelyGuaranteeContract(
        contract_id="rg:legacy",
        component_id="worker",
        rely_statement="x never decreases",
        guarantee_statement="x always increases",
        shared_variable_ids=("x",),
    )
    adapted = adapt_rely_guarantee_contract(legacy, provenance=_provenance(), **_roots())

    assert adapted.rely[0].support is SemanticSupport.OPAQUE
    assert adapted.guarantees[0].support is SemanticSupport.OPAQUE
    assert adapted.confidence.value == "opaque"


def test_authority_records_reject_unknown_fields() -> None:
    predicate = BoundedPredicate(
        predicate_id="range",
        role="postcondition",
        operator="range_int",
        subject="return",
        provenance=_provenance(),
        arguments=(0, 1),
    )
    clause = SemanticContractClause("clause", "guarantee", "typed_inline", predicate)
    payload = clause.to_dict()
    payload["passed"] = True
    with pytest.raises(CompositionalContractError, match="extra"):
        SemanticContractClause.from_dict(payload)
