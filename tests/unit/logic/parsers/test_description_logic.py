"""Unit tests for DescriptionLogicProfiles@1 (LFP2-039).

Evidence subset:

* supported DL profile (ALC / ALCQ / EL) is explicit
* open-world semantics are explicit on every profile and axiom payload
* concept / role / individual / inclusion / disjointness / cardinality /
  ontology-import identities
* unsupported OWL constructs fail without silent FOL approximation
* parse/print/parse semantic round-trip
* legal / UI / intent / KG ontology profile factories
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.description_logic import (
    CODE_FOL_APPROXIMATION_REJECTED,
    CODE_PROFILE_MISMATCH,
    CODE_UNSUPPORTED_OWL,
    DESCRIPTION_LOGIC_PROFILE_INTERFACE,
    DESCRIPTION_LOGIC_PROFILES_INTERFACE,
    DL_FAMILY_ID,
    DL_NOTATION_ID,
    AuthorityPromotionError,
    CardinalityIdentity,
    ConceptIdentity,
    DLExpressivity,
    DescriptionLogicEvidenceContract,
    DescriptionLogicParser,
    DescriptionLogicPrinter,
    DescriptionLogicProfile,
    DescriptionLogicProfiles,
    DisjointnessIdentity,
    DomainUseCase,
    EvidenceAuthority,
    EvidenceSource,
    InclusionIdentity,
    IndividualIdentity,
    OntologyImportIdentity,
    RoleIdentity,
    WorldAssumption,
    description_logic_semantic_identity,
    extract_dl_identities,
    fol_approximation_evidence_contract,
    local_classifier_evidence_contract,
    parse_description_logic,
    parse_print_parse,
    print_description_logic,
    profile_alc,
    profile_alcq,
    profile_el,
    profile_intent_ontology,
    profile_kg_ontology,
    profile_legal_ontology,
    profile_ui_ontology,
    reject_fol_approximation,
    tableau_reasoner_evidence_contract,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)


def _alc() -> DescriptionLogicProfile:
    return profile_alc()


def _alcq() -> DescriptionLogicProfile:
    return profile_alcq()


def _el() -> DescriptionLogicProfile:
    return profile_el()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert DESCRIPTION_LOGIC_PROFILES_INTERFACE == "DescriptionLogicProfiles@1"
    assert DESCRIPTION_LOGIC_PROFILE_INTERFACE == "DescriptionLogicProfile@1"
    assert DL_FAMILY_ID == "description_logic"
    assert DL_NOTATION_ID == "canonical_description_logic"
    logic = DescriptionLogicProfiles(_alc())
    assert logic.interface == DESCRIPTION_LOGIC_PROFILES_INTERFACE
    assert isinstance(logic.parser, DescriptionLogicParser)
    assert isinstance(logic.printer, DescriptionLogicPrinter)


def test_profiles_expose_explicit_expressivity_and_open_world() -> None:
    alc = _alc()
    assert alc.expressivity is DLExpressivity.ALC
    assert alc.world_assumption is WorldAssumption.OPEN_WORLD
    assert alc.is_open_world is True
    assert alc.allows_fol_approximation is False
    assert alc.allows_complete_owl is False
    assert alc.admit_cardinality is False

    alcq = _alcq()
    assert alcq.expressivity is DLExpressivity.ALCQ
    assert alcq.admit_cardinality is True
    assert alcq.world_assumption is WorldAssumption.OPEN_WORLD

    el = _el()
    assert el.expressivity is DLExpressivity.EL
    assert el.admit_complement is False
    assert el.admit_disjunction is False
    assert el.admit_universal is False
    assert el.is_open_world is True

    semantic = alc.semantic_identity
    assert semantic["world_assumption"] == "open_world"
    assert semantic["expressivity"] == "ALC"
    assert semantic["allows_fol_approximation"] is False
    assert semantic["allows_complete_owl"] is False


def test_domain_ontology_profiles() -> None:
    legal = profile_legal_ontology()
    assert legal.domain is DomainUseCase.LEGAL
    assert legal.expressivity is DLExpressivity.ALCQ
    assert legal.ontology_id == "ontology:legal:v1"
    assert legal.is_open_world

    ui = profile_ui_ontology()
    assert ui.domain is DomainUseCase.UI
    assert ui.expressivity is DLExpressivity.ALC

    intent = profile_intent_ontology()
    assert intent.domain is DomainUseCase.INTENT

    kg = profile_kg_ontology()
    assert kg.domain is DomainUseCase.KNOWLEDGE_GRAPH
    assert kg.admit_cardinality is True


def test_identity_records_fail_closed() -> None:
    with pytest.raises(SyntaxContractError, match="required"):
        ConceptIdentity(concept_id="")
    with pytest.raises(SyntaxContractError, match="required"):
        RoleIdentity(role_id="")
    with pytest.raises(SyntaxContractError, match="required"):
        IndividualIdentity(individual_id="")
    with pytest.raises(SyntaxContractError, match="required"):
        OntologyImportIdentity(import_iri="")
    with pytest.raises(SyntaxContractError, match="at least two"):
        DisjointnessIdentity(concept_ids=("OnlyOne",))
    with pytest.raises(SyntaxContractError, match="non-negative"):
        CardinalityIdentity(cardinality=-1, role_id="hasPart")
    ok = InclusionIdentity(subclass_id="A", superclass_id="B")
    assert ok.to_dict()["subclass_id"] == "A"


def test_profile_rejects_fol_approximation_and_complete_owl_flags() -> None:
    with pytest.raises(SyntaxContractError, match="allows_fol_approximation"):
        DescriptionLogicProfile(
            profile_id="bad",
            allows_fol_approximation=True,
        )
    with pytest.raises(SyntaxContractError, match="allows_complete_owl"):
        DescriptionLogicProfile(
            profile_id="bad",
            allows_complete_owl=True,
        )


def test_el_profile_rejects_alc_flags() -> None:
    with pytest.raises(SyntaxContractError, match="EL expressivity"):
        DescriptionLogicProfile(
            profile_id="bad_el",
            expressivity=DLExpressivity.EL,
            admit_complement=True,
            admit_disjunction=False,
            admit_universal=False,
        )


def test_alc_rejects_cardinality_flag() -> None:
    with pytest.raises(SyntaxContractError, match="ALC expressivity"):
        DescriptionLogicProfile(
            profile_id="bad_alc",
            expressivity=DLExpressivity.ALC,
            admit_cardinality=True,
        )


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


def test_parse_subclass_of() -> None:
    result = parse_description_logic(
        "SubClassOf(Person, Agent)",
        _alc(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    printed = print_description_logic(result.root)
    assert printed.startswith("SubClassOf(")
    assert "Person" in printed and "Agent" in printed
    assert result.identities["world_assumption"] == "open_world"
    extracted = extract_dl_identities(result.root)
    assert "Person" in extracted["concepts"]
    assert "Agent" in extracted["concepts"]
    assert "subclass_of" in extracted["axioms"]


def test_parse_equivalent_and_disjoint() -> None:
    result = parse_description_logic(
        "EquivalentClasses(Human, Person); DisjointClasses(Person, Organization)",
        _alc(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    extracted = extract_dl_identities(result.root)
    assert "equivalent_classes" in extracted["axioms"]
    assert "disjoint_classes" in extracted["axioms"]
    assert any("Person" in ids and "Organization" in ids for ids in extracted["disjointness"])


def test_parse_concept_constructors_alc() -> None:
    result = parse_description_logic(
        "SubClassOf(and(Parent, some(hasChild, Person)), or(Mother, Father))",
        _alc(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_description_logic(result.root)
    assert "and(" in printed
    assert "some(" in printed
    assert "or(" in printed
    extracted = extract_dl_identities(result.root)
    assert "hasChild" in extracted["roles"]


def test_parse_not_and_only() -> None:
    result = parse_description_logic(
        "SubClassOf(not(Minor), only(hasGuardian, Adult))",
        _alc(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_description_logic(result.root)
    assert "not(" in printed
    assert "only(" in printed


def test_parse_thing_and_nothing() -> None:
    result = parse_description_logic(
        "SubClassOf(Nothing, Thing)",
        _alc(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_description_logic(result.root)
    assert "Nothing" in printed
    assert "Thing" in printed


def test_parse_cardinality_alcq() -> None:
    result = parse_description_logic(
        "SubClassOf(Parent, min(1, hasChild, Person))",
        _alcq(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_description_logic(result.root)
    assert "min(1, hasChild, Person)" in printed
    extracted = extract_dl_identities(result.root)
    assert any(c["kind"] == "min" and c["cardinality"] == 1 for c in extracted["cardinalities"])


def test_parse_max_and_exactly() -> None:
    result = parse_description_logic(
        "SubClassOf(BinaryTree, and(max(2, hasChild), exactly(1, hasRoot)))",
        _alcq(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    extracted = extract_dl_identities(result.root)
    kinds = {c["kind"] for c in extracted["cardinalities"]}
    assert "max" in kinds
    assert "exactly" in kinds


def test_parse_class_and_role_assertions() -> None:
    result = parse_description_logic(
        "ClassAssertion(Person, alice); "
        "ObjectPropertyAssertion(knows, alice, bob)",
        _alc(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    extracted = extract_dl_identities(result.root)
    assert "alice" in extracted["individuals"]
    assert "bob" in extracted["individuals"]
    assert "knows" in extracted["roles"]
    assert "class_assertion" in extracted["axioms"]
    assert "object_property_assertion" in extracted["axioms"]


def test_parse_ontology_import() -> None:
    result = parse_description_logic(
        'Import("http://example.org/legal.owl"); SubClassOf(Contract, LegalDocument)',
        profile_legal_ontology(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    extracted = extract_dl_identities(result.root)
    assert "http://example.org/legal.owl" in extracted["imports"]
    assert result.identities["ontology_id"] == "ontology:legal:v1"


def test_semantic_identity_includes_open_world() -> None:
    result = parse_description_logic("SubClassOf(A, B)", _alc())
    assert result.ok
    identity = description_logic_semantic_identity(result.root, _alc())
    assert identity["family"] == "description_logic"
    assert identity["world_assumption"] == "open_world"
    assert identity["profile"]["expressivity"] == "ALC"
    assert identity["profile"]["allows_fol_approximation"] is False


def test_axiom_payload_carries_open_world() -> None:
    result = parse_description_logic("SubClassOf(A, B)", _alc())
    assert result.ok and result.root is not None
    ext = result.root.extension
    assert ext is not None
    assert ext.payload["world_assumption"] == "open_world"


# ---------------------------------------------------------------------------
# Profile mismatch / unsupported constructs fail closed
# ---------------------------------------------------------------------------


def test_alc_rejects_cardinality() -> None:
    result = parse_description_logic(
        "SubClassOf(Parent, min(1, hasChild))",
        _alc(),
    )
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_el_rejects_complement_and_disjunction() -> None:
    not_result = parse_description_logic(
        "SubClassOf(not(A), B)",
        _el(),
    )
    assert not not_result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in not_result.diagnostics)

    or_result = parse_description_logic(
        "SubClassOf(or(A, B), C)",
        _el(),
    )
    assert not or_result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in or_result.diagnostics)


def test_el_rejects_universal() -> None:
    result = parse_description_logic(
        "SubClassOf(only(hasPart, Widget), Assembly)",
        _el(),
    )
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_el_admits_conjunction_and_existential() -> None:
    result = parse_description_logic(
        "SubClassOf(and(Parent, some(hasChild, Person)), Ancestor)",
        _el(),
    )
    assert result.ok, [d.message for d in result.diagnostics]


@pytest.mark.parametrize(
    "surface",
    [
        "InverseOf(hasParent)",
        "ObjectInverseOf(hasParent)",
        "PropertyChain(hasParent, hasBrother)",
        "ObjectPropertyChain(hasParent, hasBrother)",
        "ObjectOneOf(alice, bob)",
        "OneOf(alice)",
        "HasValue(hasName, alice)",
        "ObjectHasValue(hasName, alice)",
        "HasSelf(likes)",
        "DataProperty(hasAge)",
        "Datatype(xsd:integer)",
        "SWRL(rule1)",
        "HasKey(Person, hasSSN)",
        "Transitive(hasPart)",
        "Symmetric(knows)",
        "Functional(hasMother)",
        "SameAs(alice, alice2)",
        "DifferentFrom(alice, bob)",
        "SubObjectPropertyOf(hasMother, hasParent)",
        "ObjectPropertyDomain(hasChild, Person)",
        "DataPropertyAssertion(hasAge, alice, 30)",
        "Ontology(http://example.org/)",
    ],
)
def test_unsupported_owl_constructs_fail_without_fol_approximation(
    surface: str,
) -> None:
    result = parse_description_logic(surface, _alcq())
    assert not result.ok
    assert any(d.code == CODE_UNSUPPORTED_OWL for d in result.diagnostics)
    # Diagnostics must explicitly refuse FOL approximation.
    assert any(
        d.metadata.get("allows_fol_approximation") is False
        for d in result.diagnostics
        if d.code == CODE_UNSUPPORTED_OWL
    )
    assert any(
        "FOL approximation" in d.message or "fol" in d.message.casefold()
        for d in result.diagnostics
    )


def test_reject_fol_approximation_helper() -> None:
    diag = reject_fol_approximation(construct="ObjectInverseOf")
    assert diag.code == CODE_FOL_APPROXIMATION_REJECTED
    assert diag.metadata["allows_fol_approximation"] is False
    assert "ObjectInverseOf" in diag.message


def test_empty_input_rejected() -> None:
    result = parse_description_logic("   ", _alc())
    assert not result.ok
    assert result.status is not ParseStatus.OK


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_parse_print_parse_round_trip_subclass() -> None:
    text = "SubClassOf(and(Parent, some(hasChild, Person)), Ancestor)"
    first, second, equivalent = parse_print_parse(text, _alc())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent
    assert alpha_equivalent(first.root, second.root)


def test_parse_print_parse_round_trip_alcq_cardinality() -> None:
    text = "SubClassOf(Parent, min(1, hasChild, Person))"
    first, second, equivalent = parse_print_parse(text, _alcq())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent


def test_parse_print_parse_multi_axiom() -> None:
    text = (
        'Import("http://example.org/base.owl"); '
        "SubClassOf(Contract, LegalDocument); "
        "DisjointClasses(Person, Organization); "
        "ClassAssertion(Person, alice)"
    )
    first, second, equivalent = parse_print_parse(text, profile_legal_ontology())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent


# ---------------------------------------------------------------------------
# Evidence: FOL approximation cannot become DL entailment authority
# ---------------------------------------------------------------------------


def test_fol_approximation_is_advisory_only() -> None:
    evidence = fol_approximation_evidence_contract(_alc())
    assert evidence.source is EvidenceSource.FOL_APPROXIMATION
    assert evidence.authority_ceiling is EvidenceAuthority.ADVISORY
    assert evidence.may_promote_to_entailment is False
    with pytest.raises(AuthorityPromotionError, match="cannot be promoted"):
        evidence.promote_to_entailment()


def test_cannot_construct_fol_approximation_as_entailment() -> None:
    with pytest.raises(AuthorityPromotionError, match="FOL approximation"):
        DescriptionLogicEvidenceContract(
            source=EvidenceSource.FOL_APPROXIMATION,
            authority=EvidenceAuthority.ENTAILMENT,
        )


def test_cannot_grant_entailment_from_fol_approximation() -> None:
    with pytest.raises(AuthorityPromotionError, match="FOL approximation"):
        DescriptionLogicEvidenceContract(
            source=EvidenceSource.FOL_APPROXIMATION,
            authority=EvidenceAuthority.ADVISORY,
            grants_entailment_authority=True,
        )


def test_local_classifier_is_bounded() -> None:
    evidence = local_classifier_evidence_contract(_alcq())
    assert evidence.authority_ceiling is EvidenceAuthority.BOUNDED
    assert evidence.world_assumption is WorldAssumption.OPEN_WORLD or (
        evidence.world_assumption == WorldAssumption.OPEN_WORLD
    )


def test_tableau_reasoner_entailment_requires_grant() -> None:
    bounded = tableau_reasoner_evidence_contract(_alc())
    assert bounded.authority_ceiling is EvidenceAuthority.BOUNDED
    granted = tableau_reasoner_evidence_contract(
        _alc(), grants_entailment_authority=True
    )
    assert granted.authority_ceiling is EvidenceAuthority.ENTAILMENT
    assert granted.grants_entailment_authority is True


def test_evidence_contract_carries_open_world() -> None:
    evidence = fol_approximation_evidence_contract(profile_kg_ontology())
    payload = evidence.to_dict()
    assert payload["world_assumption"] == "open_world"
    assert payload["expressivity"] == "ALCQ"
    assert payload["may_promote_to_entailment"] is False


# ---------------------------------------------------------------------------
# Profile serialization
# ---------------------------------------------------------------------------


def test_profile_round_trip_dict() -> None:
    original = profile_legal_ontology()
    restored = DescriptionLogicProfile.from_dict(original.to_dict())
    assert restored.profile_id == original.profile_id
    assert restored.expressivity is DLExpressivity.ALCQ
    assert restored.world_assumption is WorldAssumption.OPEN_WORLD
    assert restored.domain is DomainUseCase.LEGAL
    assert restored.ontology_id == original.ontology_id
    assert restored.allows_fol_approximation is False


def test_identities_to_dict_round_trip() -> None:
    concept = ConceptIdentity(concept_id="Contract")
    role = RoleIdentity(role_id="partyTo")
    individual = IndividualIdentity(individual_id="alice")
    card = CardinalityIdentity(cardinality=1, role_id="hasParty", kind="min")
    imp = OntologyImportIdentity(import_iri="http://example.org/legal.owl")
    assert ConceptIdentity.from_dict(concept.to_dict()).concept_id == "Contract"
    assert RoleIdentity.from_dict(role.to_dict()).role_id == "partyTo"
    assert (
        IndividualIdentity.from_dict(individual.to_dict()).individual_id == "alice"
    )
    assert CardinalityIdentity.from_dict(card.to_dict()).cardinality == 1
    assert OntologyImportIdentity.from_dict(imp.to_dict()).import_iri.startswith(
        "http"
    )


def test_parse_result_to_dict_exposes_profile() -> None:
    result = parse_description_logic("SubClassOf(A, B)", _alc())
    assert result.ok
    payload = result.to_dict()
    assert payload["interface"] == DESCRIPTION_LOGIC_PROFILES_INTERFACE
    assert payload["profile"]["world_assumption"] == "open_world"
    assert payload["profile"]["allows_fol_approximation"] is False
    assert payload["status"] == ParseStatus.OK.value
