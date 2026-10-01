"""Kernel-checked executable policy semantics and strict unsupported boundaries."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_authorization_lean as emit
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v5 import _execute
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.software_verification.authorization import (
    AuthorizationIR, AuthorizationPrincipal, PredicateSignature, AuthorizationFact,
    AuthorizationAtom, AuthorizationTerm, AuthorizationRule, AuthorizationConstraint,
    DecisionQuery, PrecedencePolicy, PolicyBounds,
)
from ipfs_datasets_py.logic.backends.datalog.adapters import ReferenceAuthorizationEvaluator


def policy(*, allow=True, deny=False, precedence="deny_overrides", negative=False,
           issuer="principal:root", guard=None, fact=True, goal=False, derive=False):
    mapped = {"source_ref_ids": ("source:auth",)}
    c = AuthorizationTerm.constant
    def atom(name, *values, polarity="positive"):
        sorts = ("principal",) if len(values) == 1 else ("principal", "action", "resource")
        return AuthorizationAtom(name, tuple(c(value, sort) for value, sort in zip(values, sorts)), polarity)
    facts = (AuthorizationFact("fact:eligible", atom("pred:eligible", "principal:alice"),
             issuer_principal_id="principal:root", **mapped),) if fact else ()
    constraints = () if guard is None else (AuthorizationConstraint("guard:gate", guard[0], guard[1], **mapped),)
    rules = []
    for enabled, effect in ((allow, "allow"), (deny, "deny"), (derive, "derive")):
        if enabled:
            rules.append(AuthorizationRule("rule:" + effect,
                atom("pred:" + effect, "principal:alice", "read", "resource:document"),
                body=(atom("pred:eligible", "principal:alice", polarity="negative" if negative else "positive"),),
                constraint_ids=("guard:gate",) if guard else (), effect=effect,
                kind="secpal_says", issuer_principal_id=issuer, stratum=1, **mapped))
    predicates = [PredicateSignature("pred:eligible", "eligible", 1, ("principal",), **mapped)]
    for effect in ("allow", "deny", "derive"):
        predicates.append(PredicateSignature("pred:" + effect, effect, 3,
            ("principal", "action", "resource"), is_intensional=True, **mapped))
    query = DecisionQuery("query:read", "principal:alice", "read", "resource:document",
        goal_atom=atom("pred:derive", "principal:alice", "read", "resource:document") if goal else None, **mapped)
    return AuthorizationIR(sources=(SourceRef("source:auth", "urn:test:policy", "policy", "fixture:v1", content_sha256="a" * 64),),
        principals=tuple(AuthorizationPrincipal("principal:" + name, name, "user", **mapped)
            for name in ("root", "alice", "outsider")),
        trust_root_principal_ids=("principal:root",), predicates=tuple(predicates),
        facts=facts, rules=tuple(rules), constraints=constraints, queries=(query,),
        precedence=PrecedencePolicy(precedence))


def lake(source, extra=""):
    paths = sorted((Path.home() / ".elan" / "toolchains").glob("*/bin/lake"))
    if not paths:
        pytest.skip("Installed native Lake unavailable; no download attempted")
    return _execute("set_option autoImplicit false\nnamespace AuthorizationIR\n" + source +
                    "\n" + extra + "\nend AuthorizationIR\n", "AuthorizationIR", paths[-1], 45)


def case_source(document, *, expected=None):
    source, details = emit.emit_authorization(document.to_dict())
    decision, _, exhausted = ReferenceAuthorizationEvaluator().evaluate(document)
    assert not exhausted
    if expected is not None:
        assert decision.outcome.value == expected
    theorem = "example : authorizationDecision authorizationQuery_0 = ." + decision.outcome.value + " := by decide"
    assert not details["proof_authority"] and not details["authorization_granted"]
    return source + "\n" + theorem, details


def test_ground_authored_fact_is_not_automatically_an_allow_decision():
    document = replace(policy(allow=False), queries=(), document_id="")
    source, details = emit.emit_authorization(document.to_dict())
    assert details["query_count"] == 0 and details["fact_count"] == 1
    assert not details["capability_floor_eligible"]
    result = lake(source, 'example : authorizationDecision ⟨"q", "principal:alice", "read", "resource:document", none⟩ = .unknown := by decide')
    assert result["status"] == "passed", result


def test_four_way_precedence_and_rule_mutations_agree_with_reference_in_lean():
    cases = []
    for precedence, expected in (("deny_overrides", "deny"), ("allow_overrides", "allow"),
                                 ("explicit_conflict", "conflict"), ("first_applicable", "allow")):
        cases.append((policy(allow=True, deny=True, precedence=precedence), expected))
    cases.extend([
        (policy(), "allow"), (policy(allow=False, deny=True), "deny"),
        (policy(fact=False), "unknown"), (policy(negative=True), "unknown"),
        (policy(negative=True, fact=False), "allow"),
        (policy(issuer="principal:outsider"), "unknown"),
        (policy(allow=False, derive=True, goal=True), "allow"),
        (policy(allow=False, derive=True, goal=False), "unknown"),
        (policy(guard=("equality", {"left": "x", "right": "x"})), "allow"),
        (policy(guard=("equality", {"left": "x", "right": "y"})), "unknown"),
        (policy(guard=("inequality", {"left": "x", "right": "y"})), "allow"),
        (policy(guard=("membership", {"value": "read", "members": ["read", "write"]})), "allow"),
        (policy(guard=("membership", {"value": "read", "members": ["write"]})), "unknown"),
    ])
    pieces = []
    for index, (document, expected) in enumerate(cases):
        source, _ = case_source(document, expected=expected)
        pieces.append("namespace Case" + str(index) + "\n" + source + "\nend Case" + str(index))
    result = lake("\n".join(pieces))
    assert result["status"] == "passed", result


def test_denial_cannot_compile_as_an_allow_proof():
    source, _ = emit.emit_authorization(policy(deny=True).to_dict())
    result = lake(source, "example : authorizationDecision authorizationQuery_0 = .allow := by decide")
    assert result["status"] == "failed" and result["returncode"] != 0, result


def test_first_applicable_preserves_stratum_then_rule_identifier_order():
    document = policy(deny=True, precedence="first_applicable")
    deny = next(row for row in document.rules if row.effect.value == "deny")
    allow = next(row for row in document.rules if row.effect.value == "allow")
    document = replace(document, rules=(replace(deny, stratum=0), allow), document_id="")
    source, _ = case_source(document, expected="deny")
    result = lake(source)
    assert result["status"] == "passed", result


def test_effect_predicate_scan_and_fact_issuer_follow_native_reference():
    document = policy(issuer="principal:outsider")
    allow = document.rules[0]
    fact = AuthorizationFact("fact:preexisting", allow.head, issuer_principal_id="principal:outsider",
        source_ref_ids=("source:auth",))
    document = replace(document, facts=(*document.facts, fact), document_id="")
    source, details = case_source(document, expected="allow")
    assert any("scan" in item for item in details["assumptions"])
    result = lake(source)
    assert result["status"] == "passed", result


def canonical(payload):
    payload = deepcopy(payload)
    payload.pop("document_id", None)
    return AuthorizationIR.from_dict(payload).to_dict()


@pytest.mark.parametrize("kind", ["comparison", "custom", "scope", "temporal_window"])
def test_opaque_guard_kinds_fail_closed_even_if_reference_defaults_to_true(kind):
    with pytest.raises(UnsupportedNativeLean, match="constraint_kind_requires_semantics"):
        emit.emit_authorization(policy(guard=(kind, {})).to_dict())


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["rules"][0].update(attributes={"requires": "mfa"}), "attributes"),
    (lambda p: p.update(metadata={"extra_requirement": "mfa"}), "metadata"),
    (lambda p: p.update(observations={"wall_time": 10}), "observations"),
    (lambda p: p["queries"][0].update(context={"mfa": False}), "query_context"),
    (lambda p: p["bounds"].update(max_derivation_depth=1), "derivation_budget"),
    (lambda p: p["bounds"].update(max_facts=1), "fact_budget"),
    (lambda p: p["bounds"].update(universe_size=1), "universe_size"),
    (lambda p: p["rules"][0].update(kind="capability"), "rule_kind"),
    (lambda p: p["rules"][0]["body"][0]["arguments"][0].update(kind="variable", value="X"), "variables"),
])
def test_unsupported_semantics_are_rejected(mutation, reason):
    payload = policy().to_dict()
    mutation(payload)
    with pytest.raises(UnsupportedNativeLean, match=reason):
        emit.emit_authorization(canonical(payload))


def test_intensional_body_dependency_cannot_be_treated_as_extensional():
    document = policy(derive=True)
    allow = next(row for row in document.rules if row.effect.value == "allow")
    derive = next(row for row in document.rules if row.effect.value == "derive")
    document = replace(document, rules=(replace(allow, body=(derive.head,)), derive), document_id="")
    with pytest.raises(UnsupportedNativeLean, match="intensional_body"):
        emit.emit_authorization(document.to_dict())


def test_exact_native_identity_and_canonical_fields_are_required():
    payload = policy().to_dict()
    payload["unreviewed_semantics"] = True
    with pytest.raises(ValueError):
        emit.emit_authorization(payload)
    payload = policy().to_dict()
    payload["facts"][0]["issuer_principal_id"] = "principal:outsider"
    with pytest.raises(ValueError, match="document_id"):
        emit.emit_authorization(payload)
    payload = policy().to_dict()
    payload["interface"] = "InventedAuthorizationIR@1"
    with pytest.raises(UnsupportedNativeLean, match="exact_native"):
        emit.emit_authorization(payload)


def test_sort_mutation_is_rejected_by_the_native_parser():
    payload = policy().to_dict()
    payload["rules"][0]["head"]["arguments"][0]["sort"] = "resource"
    with pytest.raises(ValueError):
        canonical(payload)


def test_payload_is_immutable_and_stable_and_carries_explicit_false_authority():
    payload = policy().to_dict()
    before = deepcopy(payload)
    result = emit.emit_authorization(payload)
    assert payload == before and result == emit.emit_authorization(payload)
    details = result[1]
    assert all(details[key] is False for key in ("admitted", "proof_authority", "authorization_granted", "source_semantics_verified"))


def test_empty_policy_does_not_count_generic_interpreter_as_family_coverage():
    document = replace(policy(allow=False, fact=False), queries=(), document_id="")
    with pytest.raises(UnsupportedNativeLean, match="nonempty_authorization"):
        emit.emit_authorization(document.to_dict())
