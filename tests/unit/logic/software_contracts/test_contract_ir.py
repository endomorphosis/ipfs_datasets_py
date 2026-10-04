"""Software-contract IR and reviewed registry tests (DSCON-G200 / DSCON-014)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.contracts import (
    AUTHORITY_RANKS,
    FACT_KINDS,
    GOAL_ID,
    PREDICATE_OPERATORS,
    REJECTED_PREDICATE_OPERATORS,
    SOFTWARE_CONTRACT_SCHEMA,
    TASK_ID,
    Assumption,
    BoundedPredicate,
    CapabilityContract,
    CallableContract,
    ContractAuthority,
    ContractDocument,
    ContractFinding,
    ContractIRError,
    ContractProvenance,
    DataContract,
    DeterminismContract,
    EffectContract,
    ExceptionContract,
    ParameterContract,
    ResourceContract,
    SchemaContract,
    TemporalConstraint,
    TrustBoundaryContract,
    software_contract_schema_descriptor,
)
from ipfs_datasets_py.logic.software_contracts.registry import (
    REGISTRY_SCHEMA,
    ContractRegistry,
    ContractRegistryError,
    detect_callable_conflicts,
    empty_registry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def reviewed_authority(
    *,
    authority_id: str = "authority:registry:v1",
    rank: str = "reviewed_registry",
    owner: str = "ipfs_datasets_py",
    revision: str = "1.0.0",
) -> ContractAuthority:
    return ContractAuthority(
        authority_id=authority_id,
        rank=rank,
        owner=owner,
        revision=revision,
        policy_ref="policy:cross-package-contracts-v1",
        source_cid=None,
    )


def inference_authority() -> ContractAuthority:
    return ContractAuthority(
        authority_id="authority:inference:v1",
        rank="inference",
        owner="analyzer",
        revision="1.0.0",
        policy_ref=None,
        source_cid=None,
    )


def provenance(
    *,
    fact_kind: str = "declared",
    authority: ContractAuthority | None = None,
    source_path: str = "docs/schemas/software-contract-v1.schema.json",
    source_symbol: str | None = "load_dataset",
) -> ContractProvenance:
    return ContractProvenance(
        fact_kind=fact_kind,
        authority=authority or reviewed_authority(),
        source_path=source_path,
        source_symbol=source_symbol,
        note="",
    )


def sample_callable(
    *,
    contract_id: str = "contract:load_dataset:v1",
    qualified_name: str = "ipfs_datasets_py.core_operations.load_dataset",
    fact_kind: str = "declared",
    authority: ContractAuthority | None = None,
    timeout_max: int = 30_000,
    network_permitted: bool = True,
    range_min: int = 1,
    range_max: int = 1_000_000,
) -> CallableContract:
    auth = authority or reviewed_authority()
    prov = provenance(fact_kind=fact_kind, authority=auth)
    return CallableContract(
        contract_id=contract_id,
        qualified_name=qualified_name,
        owner_module="ipfs_datasets_py.core_operations",
        shape="sync_function",
        provenance=prov,
        visibility="public",
        parameters=(
            ParameterContract(
                name="source",
                kind="positional_or_named",
                position=0,
                data=DataContract(
                    data_id="data:source",
                    name="source",
                    type_name="str",
                    provenance=prov,
                    nullable=False,
                    predicates=(
                        BoundedPredicate(
                            predicate_id="pred:source:type",
                            role="data",
                            operator="type_is",
                            subject="source",
                            provenance=prov,
                            arguments=("str",),
                            description="source is a path or URI string",
                        ),
                    ),
                ),
                default_present=False,
            ),
            ParameterContract(
                name="limit",
                kind="positional_or_named",
                position=1,
                data=DataContract(
                    data_id="data:limit",
                    name="limit",
                    type_name="int",
                    provenance=prov,
                    nullable=True,
                    predicates=(
                        BoundedPredicate(
                            predicate_id="pred:limit:range",
                            role="data",
                            operator="range_int",
                            subject="limit",
                            provenance=prov,
                            arguments=(range_min, range_max),
                        ),
                    ),
                ),
                default_present=True,
            ),
        ),
        return_data=DataContract(
            data_id="data:return",
            name="return",
            type_name="Dataset",
            provenance=prov,
            nullable=False,
        ),
        preconditions=(
            BoundedPredicate(
                predicate_id="pred:pre:source-not-null",
                role="precondition",
                operator="is_not_null",
                subject="source",
                provenance=prov,
            ),
        ),
        postconditions=(
            BoundedPredicate(
                predicate_id="pred:post:return-not-null",
                role="postcondition",
                operator="is_not_null",
                subject="return",
                provenance=prov,
            ),
        ),
        invariants=(),
        assumptions=(
            Assumption(
                assumption_id="assume:no-network-unless-declared",
                statement=(
                    "Network I/O is only permitted when the effect contract "
                    "declares network/read or network/write."
                ),
                provenance=prov,
                required=True,
            ),
        ),
        effects=(
            EffectContract(
                effect_id="effect:filesystem:read",
                kind="filesystem",
                operation="read",
                provenance=prov,
                subject="source",
                permitted=True,
                required=False,
            ),
            EffectContract(
                effect_id="effect:network:read",
                kind="network",
                operation="read",
                provenance=prov,
                subject="source",
                permitted=network_permitted,
                required=False,
            ),
        ),
        exceptions=(
            ExceptionContract(
                exception_id="exc:FileNotFoundError",
                exception_type="FileNotFoundError",
                handling="raises",
                provenance=prov,
                condition="source path does not exist",
            ),
            ExceptionContract(
                exception_id="exc:ValueError",
                exception_type="ValueError",
                handling="raises",
                provenance=prov,
                condition="limit out of reviewed bounds",
            ),
        ),
        capabilities=(
            CapabilityContract(
                capability_id="cap:dataset-load",
                capability="dataset.load",
                required=True,
                provenance=prov,
                optional_dependency=None,
            ),
        ),
        resources=(
            ResourceContract(
                resource_id="res:timeout",
                kind="timeout_ms",
                minimum=0,
                maximum=timeout_max,
                provenance=prov,
                unit="ms",
            ),
            ResourceContract(
                resource_id="res:rows",
                kind="rows",
                minimum=0,
                maximum=range_max,
                provenance=prov,
                unit="rows",
            ),
        ),
        temporal=(
            TemporalConstraint(
                temporal_id="temp:open-before-read",
                earlier_event="open_source",
                later_event="read_rows",
                provenance=prov,
                strict=True,
            ),
        ),
        determinism=DeterminismContract(
            determinism_id="det:load_dataset",
            classification="deterministic",
            provenance=prov,
        ),
        schemas=(
            SchemaContract(
                schema_contract_id="schema:dataset-op",
                schema_identifier="ipfs-datasets.dataset-operation@1.0.0",
                target="return",
                provenance=prov,
                required=True,
            ),
        ),
        trust_boundaries=(
            TrustBoundaryContract(
                boundary_id="trust:source-untrusted",
                label="untrusted",
                site="source",
                provenance=prov,
                direction="in",
            ),
        ),
        symbol_id="symbol:load_dataset:0",
    )


# ---------------------------------------------------------------------------
# Schema descriptor / vocabulary
# ---------------------------------------------------------------------------


def test_schema_descriptor_guarantees_and_ast_symbols() -> None:
    descriptor = software_contract_schema_descriptor()
    assert descriptor["owner_goal"] == GOAL_ID
    assert descriptor["task_id"] == TASK_ID
    assert descriptor["contract_schema"] == SOFTWARE_CONTRACT_SCHEMA
    assert descriptor["fact_kinds"] == sorted(FACT_KINDS)
    assert descriptor["authority_ranks_high_to_low"] == list(AUTHORITY_RANKS)
    assert set(descriptor["predicate_operators"]) == PREDICATE_OPERATORS
    assert set(descriptor["rejected_predicate_operators"]) == (
        REJECTED_PREDICATE_OPERATORS
    )
    guarantees = descriptor["guarantees"]
    assert guarantees["explicit_assumptions_and_authority"] is True
    assert guarantees["rejects_unbounded_executable_predicates"] is True
    assert guarantees["rejects_ambiguous_canonical_values"] is True
    assert guarantees["distinguishes_declared_extracted_witnessed_inferred"] is True
    assert guarantees["contradictions_are_findings"] is True
    assert guarantees["schema_round_trips_and_cids_stable"] is True
    assert guarantees["only_sound_lowerable_constructs"] is True
    assert guarantees["inference_cannot_self_promote"] is True
    assert descriptor["ast_symbols"] == [
        "CallableContract",
        "EffectContract",
        "ResourceContract",
        "ContractRegistry",
        "ContractAuthority",
    ]
    # Golden CID: descriptor drift requires explicit review.
    assert (
        cid_for_structured(descriptor)
        == "baguqeerag7wiinxy2p4o6qaolixy2tvcnl3s4axyghjyplkpyum57ogp3gha"
    )


def test_json_schema_file_exists_and_names_closed_vocabularies() -> None:
    schema_path = (
        Path(__file__).resolve().parents[4]
        / "docs"
        / "schemas"
        / "software-contract-v1.schema.json"
    )
    # parents: unit -> logic -> software_contracts -> tests -> ipfs_datasets_py
    # Actually: test file is at
    #   ipfs_datasets_py/tests/unit/logic/software_contracts/test_contract_ir.py
    # parents[0]=software_contracts, [1]=logic, [2]=unit, [3]=tests,
    # [4]=ipfs_datasets_py package root
    assert schema_path.is_file(), f"missing schema at {schema_path}"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    assert payload["$id"].endswith("software-contract-v1.schema.json")
    assert (
        payload["properties"]["schema"]["const"] == SOFTWARE_CONTRACT_SCHEMA
    )
    assert payload["properties"]["owner_goal"]["const"] == GOAL_ID
    operators = set(payload["$defs"]["predicateOperator"]["enum"])
    assert operators == PREDICATE_OPERATORS
    assert "eval" not in operators
    assert "free_form" not in operators
    fact_kinds = set(payload["$defs"]["factKind"]["enum"])
    assert fact_kinds == FACT_KINDS
    ranks = payload["$defs"]["authorityRank"]["enum"]
    assert ranks == list(AUTHORITY_RANKS)


# ---------------------------------------------------------------------------
# Provenance / authority
# ---------------------------------------------------------------------------


def test_fact_kinds_are_distinguished() -> None:
    for kind in sorted(FACT_KINDS):
        auth = (
            inference_authority()
            if kind == "inferred"
            else reviewed_authority(
                rank=(
                    "type_declaration"
                    if kind == "extracted"
                    else "reviewed_registry"
                )
            )
        )
        if kind == "witnessed":
            auth = reviewed_authority(rank="documented_api")
        prov = provenance(fact_kind=kind, authority=auth)
        assert prov.fact_kind == kind
        restored = ContractProvenance.from_dict(prov.to_dict())
        assert restored == prov
        assert restored.cid == prov.cid


def test_inferred_facts_cannot_self_promote_to_reviewed_authority() -> None:
    with pytest.raises(ContractIRError, match="inference-rank"):
        ContractProvenance(
            fact_kind="inferred",
            authority=reviewed_authority(),
            source_path="src/example.py",
            source_symbol="f",
            note="",
        )


def test_declared_facts_cannot_use_inference_rank() -> None:
    with pytest.raises(ContractIRError, match="declared"):
        ContractProvenance(
            fact_kind="declared",
            authority=inference_authority(),
            source_path="manifests/contracts.json",
            source_symbol=None,
            note="",
        )


# ---------------------------------------------------------------------------
# Predicate soundness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operator", sorted(REJECTED_PREDICATE_OPERATORS))
def test_rejects_unbounded_executable_predicates(operator: str) -> None:
    with pytest.raises(ContractIRError, match="rejected|not a reviewed"):
        BoundedPredicate(
            predicate_id="pred:bad",
            role="precondition",
            operator=operator,
            subject="x",
            provenance=provenance(),
            arguments=(),
        )


def test_rejects_unknown_and_float_predicate_arguments() -> None:
    with pytest.raises(ContractIRError, match="not a reviewed"):
        BoundedPredicate(
            predicate_id="pred:unknown-op",
            role="precondition",
            operator="magic_unbounded_check",
            subject="x",
            provenance=provenance(),
        )
    with pytest.raises(ContractIRError, match="float"):
        BoundedPredicate(
            predicate_id="pred:float",
            role="precondition",
            operator="equals",
            subject="x",
            provenance=provenance(),
            arguments=(1.5,),  # type: ignore[arg-type]
        )


def test_range_int_rejects_inverted_bounds() -> None:
    with pytest.raises(ContractIRError, match="minimum exceeds maximum"):
        BoundedPredicate(
            predicate_id="pred:bad-range",
            role="precondition",
            operator="range_int",
            subject="n",
            provenance=provenance(),
            arguments=(10, 1),
        )


# ---------------------------------------------------------------------------
# Callable contract + document round-trip / CID stability
# ---------------------------------------------------------------------------


def test_callable_contract_round_trips_with_stable_cid() -> None:
    contract = sample_callable()
    restored = CallableContract.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.cid == contract.cid
    assert contract.verify_cid(contract.cid) == contract.cid
    assert (
        contract.cid
        == "baguqeeraellbrbjfomy7wivl5aqti4r2x27542o3mcd6h5gsi647h6b6cf4a"
    )
    # Nested records are frozen.
    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.qualified_name = "changed"  # type: ignore[misc]


def test_contract_document_json_round_trip_and_golden_cid() -> None:
    document = ContractDocument(
        document_id="document:dataset-ops:v1",
        callables=(sample_callable(),),
        findings=(),
        registry_revision="1.0.0",
    )
    from_mapping = ContractDocument.from_dict(document.to_dict())
    from_json = ContractDocument.from_json(document.to_json())
    assert from_mapping == from_json == document
    assert json.loads(document.to_json()) == document.to_dict()
    assert cid_for_structured(document.to_dict()) == document.cid
    assert document.verify_cid(document.cid) == document.cid
    # Golden root — schema/fields cannot drift without review.
    assert (
        document.cid
        == "baguqeerayqx6iygly4t3xswej7zcu4mnmbe2tcubsoubscarucxqvff43lwa"
    )
    again = ContractDocument.from_dict(document.to_dict())
    assert again.cid == document.cid


def test_record_order_is_canonicalized() -> None:
    first = sample_callable()
    # Build with reversed nested sequences where constructors re-sort.
    second = CallableContract(
        contract_id=first.contract_id,
        qualified_name=first.qualified_name,
        owner_module=first.owner_module,
        shape=first.shape,
        provenance=first.provenance,
        visibility=first.visibility,
        parameters=first.parameters,
        return_data=first.return_data,
        preconditions=first.preconditions,
        postconditions=first.postconditions,
        invariants=first.invariants,
        assumptions=first.assumptions,
        effects=tuple(reversed(first.effects)),
        exceptions=tuple(reversed(first.exceptions)),
        capabilities=first.capabilities,
        resources=tuple(reversed(first.resources)),
        temporal=first.temporal,
        determinism=first.determinism,
        schemas=first.schemas,
        trust_boundaries=first.trust_boundaries,
        symbol_id=first.symbol_id,
    )
    assert second.cid == first.cid
    assert [item.effect_id for item in second.effects] == [
        item.effect_id for item in first.effects
    ]


def test_closed_fields_reject_unknown_keys() -> None:
    payload = sample_callable().to_dict()
    payload["future_field"] = "nope"
    with pytest.raises(ContractIRError, match="fields are closed"):
        CallableContract.from_dict(payload)


def test_document_rejects_wrong_schema_and_goal() -> None:
    with pytest.raises(ContractIRError, match="schema must be exactly"):
        ContractDocument(
            document_id="document:x",
            callables=(),
            schema="other@1",
        )
    with pytest.raises(ContractIRError, match="owner_goal"):
        ContractDocument(
            document_id="document:x",
            callables=(),
            owner_goal="DSCON-G999",
        )


# ---------------------------------------------------------------------------
# Registry conflict detection
# ---------------------------------------------------------------------------


def test_registry_admits_reviewed_contract_and_round_trips() -> None:
    contract = sample_callable()
    registry = ContractRegistry.from_callables(
        "registry:dataset-ops:v1",
        [contract],
        revision="1.0.0",
    )
    assert len(registry) == 1
    assert contract.contract_id in registry
    assert registry.get(contract.contract_id) == contract
    assert (
        registry.get_by_qualified_name(contract.qualified_name) == contract
    )
    assert not registry.has_findings
    assert (
        registry.cid
        == "baguqeerag6pg4suv2xf4r5h3uo2nh7ksis53woxvja4m6te7l2klckoxkyga"
    )

    restored = ContractRegistry.from_dict(registry.to_dict())
    assert restored.cid == registry.cid
    assert restored.to_json() == registry.to_json()
    assert registry.verify_cid(registry.cid) == registry.cid
    assert isinstance(registry.contracts, MappingProxyType)

    document = registry.to_document()
    assert document.schema == SOFTWARE_CONTRACT_SCHEMA
    assert document.callables[0] == contract
    from_doc = ContractRegistry.from_document(document)
    assert list(from_doc.contracts) == list(registry.contracts)


def test_contradictory_equal_rank_predicates_become_findings() -> None:
    base = sample_callable(contract_id="contract:a", range_min=1, range_max=100)
    other = sample_callable(
        contract_id="contract:b",
        range_min=200,
        range_max=300,
    )
    # Force equal-rank predicate contradiction on limit range via shared name.
    # sample_callable uses same qualified_name by default.
    findings = detect_callable_conflicts(base, other)
    kinds = {item.kind for item in findings}
    assert "contradiction" in kinds

    registry = ContractRegistry.from_callables(
        "registry:conflict",
        [base, other],
    )
    assert registry.has_findings
    assert registry.error_findings
    # Higher-or-equal authority first keeps the first admitted contract.
    assert base.contract_id in registry.contracts


def test_lower_authority_cannot_override_higher() -> None:
    high = sample_callable(
        contract_id="contract:high",
        authority=reviewed_authority(rank="reviewed_registry"),
        network_permitted=False,
    )
    low = sample_callable(
        contract_id="contract:low",
        authority=reviewed_authority(
            authority_id="authority:type",
            rank="type_declaration",
        ),
        network_permitted=True,
    )
    findings = detect_callable_conflicts(high, low)
    assert any(item.kind == "authority_override" for item in findings)

    registry = ContractRegistry.from_callables(
        "registry:auth",
        [high, low],
    )
    assert high.contract_id in registry
    # Low-authority contract should not replace the high-authority one.
    assert registry.get_by_qualified_name(high.qualified_name).contract_id == (
        high.contract_id
    )


def test_reject_on_findings_raises() -> None:
    a = sample_callable(contract_id="contract:a", range_min=1, range_max=10)
    b = sample_callable(contract_id="contract:b", range_min=50, range_max=60)
    with pytest.raises(ContractRegistryError, match="conflict finding"):
        ContractRegistry.from_callables(
            "registry:strict",
            [a, b],
            reject_on_findings=True,
        )


def test_empty_registry_shell() -> None:
    registry = empty_registry()
    assert len(registry) == 0
    assert registry.schema == REGISTRY_SCHEMA
    assert registry.owner_goal == GOAL_ID
    assert not registry.has_findings
    with pytest.raises(ContractRegistryError, match="unknown contract_id"):
        registry.get("missing")


def test_registry_closed_fields() -> None:
    registry = ContractRegistry.from_callables(
        "registry:x",
        [sample_callable()],
    )
    payload = registry.to_dict()
    payload["extra"] = True
    with pytest.raises(ContractRegistryError, match="fields are closed"):
        ContractRegistry.from_dict(payload)


# ---------------------------------------------------------------------------
# Resource / effect / assumption coverage
# ---------------------------------------------------------------------------


def test_resource_contract_rejects_inverted_bounds() -> None:
    with pytest.raises(ContractIRError, match="minimum exceeds maximum"):
        ResourceContract(
            resource_id="res:bad",
            kind="bytes",
            minimum=100,
            maximum=10,
            provenance=provenance(),
        )


def test_effect_required_implies_permitted() -> None:
    with pytest.raises(ContractIRError, match="required effects"):
        EffectContract(
            effect_id="effect:bad",
            kind="network",
            operation="write",
            provenance=provenance(),
            permitted=False,
            required=True,
        )


def test_assumption_is_explicit_on_callable() -> None:
    contract = sample_callable()
    assert len(contract.assumptions) == 1
    assert contract.assumptions[0].required is True
    assert "Network I/O" in contract.assumptions[0].statement
    assert contract.assumptions[0].provenance.authority.rank == (
        "reviewed_registry"
    )


def test_all_record_types_have_content_identity() -> None:
    prov = provenance()
    records: list[Any] = [
        reviewed_authority(),
        prov,
        Assumption(
            assumption_id="a1",
            statement="explicit assumption",
            provenance=prov,
        ),
        BoundedPredicate(
            predicate_id="p1",
            role="precondition",
            operator="pure",
            subject="f",
            provenance=prov,
        ),
        EffectContract(
            effect_id="e1",
            kind="logging",
            operation="write",
            provenance=prov,
        ),
        ResourceContract(
            resource_id="r1",
            kind="concurrency",
            minimum=1,
            maximum=4,
            provenance=prov,
        ),
        ExceptionContract(
            exception_id="x1",
            exception_type="RuntimeError",
            handling="propagates",
            provenance=prov,
        ),
        CapabilityContract(
            capability_id="c1",
            capability="io.network",
            required=False,
            provenance=prov,
            optional_dependency="requests",
        ),
        TemporalConstraint(
            temporal_id="t1",
            earlier_event="a",
            later_event="b",
            provenance=prov,
        ),
        DeterminismContract(
            determinism_id="d1",
            classification="pure",
            provenance=prov,
        ),
        SchemaContract(
            schema_contract_id="s1",
            schema_identifier="example@1.0.0",
            target="return",
            provenance=prov,
        ),
        TrustBoundaryContract(
            boundary_id="tb1",
            label="secret",
            site="token",
            provenance=prov,
        ),
        DataContract(
            data_id="dd1",
            name="x",
            type_name="int",
            provenance=prov,
        ),
        ContractFinding(
            finding_id="f1",
            kind="contradiction",
            severity="error",
            message="example finding",
            subject="example.f",
        ),
        sample_callable(),
    ]
    for record in records:
        payload = record.to_dict()
        assert cid_for_structured(payload) == record.cid
        assert record.cid.startswith("b")


def test_witnessed_and_extracted_fact_kinds_on_effects() -> None:
    extracted = provenance(
        fact_kind="extracted",
        authority=reviewed_authority(rank="type_declaration"),
        source_path="src/module.py",
    )
    witnessed = provenance(
        fact_kind="witnessed",
        authority=reviewed_authority(rank="documented_api"),
        source_path="tests/test_module.py",
    )
    effect = EffectContract(
        effect_id="effect:extracted",
        kind="filesystem",
        operation="write",
        provenance=extracted,
    )
    assert effect.provenance.fact_kind == "extracted"
    resource = ResourceContract(
        resource_id="res:witnessed",
        kind="retries",
        minimum=0,
        maximum=3,
        provenance=witnessed,
    )
    assert resource.provenance.fact_kind == "witnessed"


def test_descriptor_path_matches_expected_output() -> None:
    descriptor = software_contract_schema_descriptor()
    assert descriptor["json_schema_path"] == (
        "ipfs_datasets_py/docs/schemas/software-contract-v1.schema.json"
    )
