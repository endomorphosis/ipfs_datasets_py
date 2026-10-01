"""Executable finite AuthorizationIR interpretations with a strict semantic boundary.

This fragment follows ReferenceAuthorizationEvaluator for ground policies whose
rule bodies refer only to extensional predicates. It does not infer policy from
source, assert permissions, or grant authorization to a caller. Facts are EDB
assertions (including issuer provenance), not automatically allow evidence.
"""
from __future__ import annotations

import hashlib
import json

from ...software_verification.authorization import AuthorizationIR
from .native_family_lean_emitters import UnsupportedNativeLean, require, string

PROFILE = "native-ground-extensional-authorization-lean/v1"

PRELUDE = '''set_option linter.unusedVariables false
structure AuthAtom where
  predicate : String
  arguments : List String
  deriving DecidableEq, BEq
structure AuthFact where
  identity : String
  atom : AuthAtom
  issuer : String
inductive AuthGuard where
  | equal (left right : String)
  | unequal (left right : String)
  | member (value : String) (members : List String)
def AuthGuard.holds : AuthGuard → Bool
  | .equal left right => left == right
  | .unequal left right => left != right
  | .member value members => members.contains value
inductive AuthEffect where
  | allow | deny | derive
  deriving DecidableEq, BEq
inductive AuthOutcome where
  | allow | deny | conflict | unknown
  deriving DecidableEq, BEq
inductive AuthPrecedence where
  | deny_overrides | allow_overrides | first_applicable | explicit_conflict
structure AuthRule where
  identity : String
  head : AuthAtom
  positive : List AuthAtom
  negative : List AuthAtom
  guards : List AuthGuard
  secpal : Bool
  issuer : String
  effect : AuthEffect
  stratum : Nat
structure AuthQuery where
  identity : String
  principal : String
  action : String
  resource : String
  goal : Option AuthAtom

def issuerAuthorized (roots : List String) (rule : AuthRule) : Bool :=
  !rule.secpal || roots.contains rule.issuer

def bodySatisfied (facts : List AuthAtom) (rule : AuthRule) : Bool :=
  rule.positive.all facts.contains &&
  rule.negative.all (fun atom => !facts.contains atom) &&
  rule.guards.all AuthGuard.holds

-- Exactly the ground head alignment used by the reference evaluator.
def headAligned (query : AuthQuery) (head : AuthAtom) : Bool :=
  match head.arguments with
  | [] => true
  | [principal] => principal == query.principal
  | [principal, action] => principal == query.principal && action == query.action
  | [principal, action, resource] =>
      principal == query.principal && action == query.action && resource == query.resource
  | _ => false

def evidenceMatches (query : AuthQuery) (atom : AuthAtom) : Bool :=
  match atom.arguments with
  | [] => true
  | [value] => [query.principal, query.action, query.resource].contains value
  | [principal, value] => principal == query.principal &&
      [query.action, query.resource].contains value
  | [principal, action, resource] =>
      principal == query.principal && action == query.action &&
      (query.resource == "" || [query.resource, "*", ""].contains resource)
  | _ => false

def resolveAuthorization (precedence : AuthPrecedence) (allow deny : Bool)
    (first : Option AuthEffect) : AuthOutcome :=
  if allow && deny then
    match precedence with
    | .deny_overrides => .deny
    | .allow_overrides => .allow
    | .explicit_conflict => .conflict
    | .first_applicable =>
      match first with
      | some .allow => .allow
      | some .deny => .deny
      | _ => .conflict
  else if deny then .deny else if allow then .allow else .unknown

def applicableRules (facts : List AuthAtom) (roots : List String)
    (rules : List AuthRule) : List AuthRule :=
  rules.filter (fun rule => issuerAuthorized roots rule && bodySatisfied facts rule)

def queryDirectedRules (query : AuthQuery) (rules : List AuthRule) : List AuthRule :=
  rules.filter (fun rule => headAligned query rule.head)

def evaluatedFacts (facts : List AuthAtom) (applicable : List AuthRule)
    (query : AuthQuery) : List AuthAtom :=
  facts ++ ((queryDirectedRules query applicable).map AuthRule.head) ++
    ((applicable.filter (fun rule => rule.effect == .derive)).map AuthRule.head)

-- Native decision collection also scans EDB/IDB for effect-rule predicates;
-- effect and predicate identity are retained even for a rule that did not fire.
def hasEffectEvidence (effect : AuthEffect) (rules : List AuthRule)
    (facts : List AuthAtom) (query : AuthQuery) : Bool :=
  rules.any (fun rule => rule.effect == effect && facts.any (fun atom =>
    atom.predicate == rule.head.predicate && evidenceMatches query atom))

def evaluateAuthorization (facts : List AuthAtom) (roots : List String)
    (rules : List AuthRule) (precedence : AuthPrecedence) (query : AuthQuery) : AuthOutcome :=
  let applicable := applicableRules facts roots rules
  let materialized := evaluatedFacts facts applicable query
  let goal := match query.goal with
    | none => false
    | some atom => materialized.contains atom
  let allow := goal || hasEffectEvidence .allow rules materialized query
  let deny := hasEffectEvidence .deny rules materialized query
  let first := ((queryDirectedRules query applicable).find?
    (fun rule => rule.effect != .derive)).map AuthRule.effect
  resolveAuthorization precedence allow deny first
'''


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _list(items):
    return "[" + ", ".join(items) + "]"


def _atom(atom):
    require(all(term["kind"] == "constant" for term in atom["arguments"]),
            "authorization_variables_require_binding_semantics")
    require(len(atom["arguments"]) <= 3, "authorization_ground_atom_arity_exceeds_three")
    return "⟨" + string(atom["predicate_id"]) + ", " + _list(string(term["value"]) for term in atom["arguments"]) + "⟩"


def _guard(row):
    expression = row["expression"]
    require(not row["statement"], "authorization_constraint_statement_requires_separate_interpretation")
    kind = row["kind"]
    if kind in ("equality", "inequality"):
        require(set(expression) == {"left", "right"} and all(type(v) is str for v in expression.values()),
                "authorization_closed_ground_comparison_required")
        return "." + ("equal" if kind == "equality" else "unequal") + " " + string(expression["left"]) + " " + string(expression["right"])
    if kind == "membership":
        require(set(expression) == {"value", "members"} and type(expression["value"]) is str
                and type(expression["members"]) is list and len(expression["members"]) <= 128
                and all(type(v) is str for v in expression["members"]),
                "authorization_closed_ground_membership_required")
        return ".member " + string(expression["value"]) + " " + _list(map(string, expression["members"]))
    raise UnsupportedNativeLean("authorization_constraint_kind_requires_semantics:" + kind)


def emit_authorization(payload):
    """Return Lean declarations and diagnostics; never an authorization verdict."""
    native = AuthorizationIR.from_dict(payload)
    require(native.to_dict() == payload, "exact_native_authorization_roundtrip_required")
    require(len(_wire(payload).encode()) <= 262144, "bounded_authorization_payload_required")
    for field in ("roles", "speaks_for", "delegations", "decisions", "explanations", "metadata", "observations"):
        require(not payload[field], "authorization_" + field + "_requires_separate_semantics")
    require(any(payload[key] for key in ("facts", "rules", "queries")),
            "nonempty_authorization_facts_rules_or_queries_required")
    limits = {"principals": 64, "predicates": 64, "facts": 128, "rules": 64, "constraints": 64, "queries": 32}
    require(all(len(payload[key]) <= limit for key, limit in limits.items()), "bounded_authorization_declarations_required")
    require(all(not row["attributes"] for key in ("principals", "facts", "rules") for row in payload[key]),
            "authorization_attributes_require_separate_semantics")
    require(all(row["predicate_id"] != "speaks_for" for row in payload["predicates"]),
            "authorization_speaks_for_predicate_requires_trust_closure")
    rules = sorted(payload["rules"], key=lambda row: (row["stratum"], row["rule_id"]))
    head_predicates = {row["head"]["predicate_id"] for row in rules}
    require(all(atom["predicate_id"] not in head_predicates for row in rules for atom in row["body"]),
            "authorization_intensional_body_requires_fixpoint_semantics")
    require(all(row["kind"] in ("datalog", "secpal_says") for row in rules),
            "authorization_rule_kind_requires_separate_semantics")
    # Reference budgeting counts attempted insertions, including duplicate
    # ground heads. This conservative bound covers seed, query pass and two
    # extensional derive passes, so exhaustion is impossible in this fragment.
    step_bound = len(payload["facts"]) + 2 * len(rules) + 2 * sum(row["effect"] == "derive" for row in rules) + 1
    require(payload["bounds"]["max_derivation_depth"] >= step_bound,
            "authorization_derivation_budget_may_exhaust")
    require(payload["bounds"]["max_facts"] >= len(payload["facts"]) + len(rules),
            "authorization_fact_budget_may_exhaust")
    # The reference evaluator ignores universe_size; accepting it would erase
    # an explicit finite-universe constraint. Require the unspecified profile.
    require(payload["bounds"]["universe_size"] is None,
            "authorization_universe_size_requires_explicit_domain_semantics")
    guards = {row["constraint_id"]: _guard(row) for row in payload["constraints"]}
    declarations = [PRELUDE]
    declarations.append("def authorizationFacts : List AuthFact := " + _list(
        "⟨" + string(row["fact_id"]) + ", " + _atom(row["atom"]) + ", " + string(row["issuer_principal_id"]) + "⟩"
        for row in payload["facts"]))
    declarations.append("def authorizationRoots : List String := " + _list(map(string, payload["trust_root_principal_ids"])))
    rule_values = []
    for row in rules:
        positive = [_atom(atom) for atom in row["body"] if atom["polarity"] == "positive"]
        negative = [_atom(atom) for atom in row["body"] if atom["polarity"] == "negative"]
        rule_values.append("⟨" + ", ".join((string(row["rule_id"]), _atom(row["head"]), _list(positive), _list(negative),
            _list("(" + guards[key] + ")" for key in row["constraint_ids"]),
            "true" if row["kind"] == "secpal_says" else "false", string(row["issuer_principal_id"]),
            "." + row["effect"], str(row["stratum"]))) + "⟩")
    declarations.append("def authorizationRules : List AuthRule := " + _list(rule_values))
    declarations.append("def authorizationPrecedence : AuthPrecedence := ." + payload["precedence"]["resolution"])
    declarations.append("def authorizationDecision (query : AuthQuery) : AuthOutcome :=\n  evaluateAuthorization (authorizationFacts.map AuthFact.atom) authorizationRoots authorizationRules authorizationPrecedence query")
    query_symbols = {}
    for index, row in enumerate(payload["queries"]):
        require(not row["context"] and not row["constraint_ids"], "authorization_query_context_or_guards_require_semantics")
        symbol = "authorizationQuery_" + str(index)
        goal = "none" if row["goal_atom"] is None else "some (" + _atom(row["goal_atom"]) + ")"
        declarations.append("def " + symbol + " : AuthQuery := ⟨" + ", ".join((string(row["query_id"]),
            string(row["principal_id"]), string(row["action"]), string(row["resource"]), goal)) + "⟩")
        query_symbols[row["query_id"]] = symbol
    # Preserve non-operational type signatures and provenance as evidence data.
    # They are not used as substitutes for the executable semantics above.
    for index, row in enumerate(payload["predicates"]):
        declarations.append("def authorizationSignature_" + str(index) + " : String := " + string(_wire(row)))
    for key in ("principals", "sources", "spans", "constraints"):
        for index, row in enumerate(payload[key]):
            declarations.append("def authorizationEvidence_" + key + "_" + str(index) + " : String := " + string(_wire(row)))
    for key in ("bounds", "precedence"):
        declarations.append("def authorizationEvidence_" + key + " : String := " + string(_wire(payload[key])))
    for key in ("facts", "rules", "queries"):
        for index, row in enumerate(payload[key]):
            evidence = row
            declarations.append("def authorizationEvidence_" + key + "_" + str(index) + " : String := " + string(_wire(evidence)))
    digest = hashlib.sha256(_wire(payload).encode()).hexdigest()
    declarations.append("def authorizationPayloadSHA256 : String := " + string(digest))
    return "\n\n".join(declarations), {
        "profile": PROFILE, "validator": "AuthorizationIR_exact_ground_extensional_reference_fragment",
        "payload_sha256": digest, "query_symbols": query_symbols, "fact_count": len(payload["facts"]),
        "rule_count": len(rules), "query_count": len(query_symbols), "conservative_derivation_step_bound": step_bound,
        "operators": ["ground_facts", "extensional_body_rules", "negation_as_failure", "issuer_trust_roots",
            "ground_equality_inequality_membership", "query_directed_ground_heads", "native_effect_predicate_collection", "four_way_precedence"],
        "assumptions": [
            "Native facts are supplied extensional assertions; fact issuers are retained as provenance, as in the reference evaluator.",
            "SecPAL rule issuers must be declared trust roots; Datalog issuer fields do not impose a trust guard in the reference semantics.",
            "Rule bodies refer only to extensional predicates; all terms are ground and typed by exact native validation.",
            "Absent extensional atoms satisfy ground negative body literals under closed-world negation as failure.",
            "Decision collection includes the reference evaluator's scan of materialized effect-rule predicates; this is not a general SecPAL theorem.",
            "Declarations and query computations concern the supplied finite policy, not source-program correctness or real-world permission."],
        "capability_floor_eligible": False, "authorization_granted": False, "proof_authority": False,
        "source_semantics_verified": False, "generated_code_correctness": "not_established", "admitted": False,
    }
