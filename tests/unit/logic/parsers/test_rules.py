"""Unit tests for RuleFrontend@1 and SecPALFrontend@1 (LFP-020).

Evidence subset:

* range restriction, recursion, stratification, negation
* principals, delegation, speaks-for
* CHC lowering with explicit loss receipts
* closed-world and priority semantics
* fail-closed: unsafe variables, unstratified negation, ambiguous
  principal/resource/action terms, missing world/priority semantics
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.rules import (
    CODE_AMBIGUOUS_TERM,
    CODE_EMPTY_INPUT,
    CODE_INPUT_LIMIT,
    CODE_MISSING_PRIORITY,
    CODE_MISSING_WORLD,
    CODE_TOKEN_LIMIT,
    CODE_UNSAFE_VARIABLE,
    CODE_UNSTRATIFIED_NEGATION,
    CODE_UNSUPPORTED_CONSTRUCT,
    PriorityPolicyKind,
    RULE_FAMILY_ID,
    RULE_FRONTEND_INTERFACE,
    RULE_NOTATION_ID,
    RULE_PROFILE_ID,
    RuleEffect,
    RuleFrontend,
    RuleItemRole,
    RuleParser,
    RulePrinter,
    RuleProfile,
    RuleStatementKind,
    RuleTermKind,
    SECPAL_FAMILY_ID,
    SECPAL_FRONTEND_INTERFACE,
    SECPAL_PROFILE_ID,
    SecPALFrontend,
    TermSortHint,
    WorldPolicyKind,
    check_range_restriction,
    documents_semantically_compatible,
    elaborate_rules,
    lower_to_chc,
    normalize_rules,
    parse_print_parse_rules,
    parse_rules,
    parse_secpal,
    print_rules,
    tokenize_rules,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseLimits, ParseStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _frontend() -> RuleFrontend:
    return RuleFrontend()


def _secpal() -> SecPALFrontend:
    return SecPALFrontend()


SAMPLE_DATALOG = """\
@world closed_world.
@priority deny_overrides.
@profile datalog.
@trust root.

role(alice, admin).
role(bob, reader).
sensitive(docs_payroll).
resource(docs_payroll).

@stratum 0.
allow may(P, read, R) :- role(P, admin), resource(R).

@stratum 1.
deny denied(P, read, R) :- role(P, reader), sensitive(R), not role(P, admin).

?- may(alice, read, docs_payroll).
"""

SAMPLE_SECPAL = """\
@world closed_world.
@priority deny_overrides.
@profile secpal.
@trust root.

"root" says role(alice, admin).
"root" says may(P:principal, read:action, R:resource) if role(P:principal, admin), resource(R:resource).
resource(docs_payroll:resource).
"alice" speaks-for "bob".
"root" says "carol" can "read" on "docs_public" with delegation-depth 1.
query "alice" can "read" on "docs_payroll".
"""

SAMPLE_CHC = """\
@profile chc.
edge(a, b).
edge(b, c).
chc path(X, Y) :- edge(X, Y).
chc path(X, Z) :- edge(X, Y), path(Y, Z).
?- path(a, c).
"""


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert RULE_FRONTEND_INTERFACE == "RuleFrontend@1"
    assert SECPAL_FRONTEND_INTERFACE == "SecPALFrontend@1"
    assert RULE_NOTATION_ID == "datalog_rules"
    assert RULE_PROFILE_ID == "horn"
    assert RULE_FAMILY_ID == "datalog"
    assert SECPAL_PROFILE_ID == "secpal"
    assert SECPAL_FAMILY_ID == "authorization"
    frontend = _frontend()
    assert frontend.interface == RULE_FRONTEND_INTERFACE
    assert isinstance(frontend.parser, RuleParser)
    assert isinstance(frontend.printer, RulePrinter)
    secpal = _secpal()
    assert secpal.interface == SECPAL_FRONTEND_INTERFACE
    assert secpal.family_id == SECPAL_FAMILY_ID


# ---------------------------------------------------------------------------
# Happy-path: facts, rules, queries, negation, priorities
# ---------------------------------------------------------------------------


def test_parse_datalog_facts_rules_queries_and_negation() -> None:
    result = parse_rules(SAMPLE_DATALOG)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.world_policy is WorldPolicyKind.CLOSED_WORLD
    assert doc.priority_policy is PriorityPolicyKind.DENY_OVERRIDES
    assert doc.profile is RuleProfile.DATALOG
    assert "root" in doc.trust_roots
    assert len(doc.facts) >= 3
    assert len(doc.rules) == 2
    assert len(doc.queries) == 1
    allow_rule = next(r for r in doc.rules if r.effect is RuleEffect.ALLOW)
    assert allow_rule.head is not None
    assert allow_rule.head.predicate == "may"
    assert allow_rule.stratum == 0
    deny_rule = next(r for r in doc.rules if r.effect is RuleEffect.DENY)
    assert any(atom.is_negative for atom in deny_rule.body)
    assert deny_rule.stratum == 1
    assert "role" in doc.predicate_names
    assert "may" in doc.predicate_names


def test_parse_horn_rule_range_restricted() -> None:
    text = """\
@world closed_world.
parent(alice, bob).
ancestor(X, Y) :- parent(X, Y).
ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z).
?- ancestor(alice, bob).
"""
    result = parse_rules(text)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.rules) == 2
    assert all(r.kind is RuleStatementKind.RULE for r in doc.rules)


def test_parse_secpal_says_speaks_for_delegation_query() -> None:
    result = parse_secpal(SAMPLE_SECPAL)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.profile is RuleProfile.SECPAL
    assert doc.family_id == SECPAL_FAMILY_ID
    assert any(s.role is RuleItemRole.SECPAL_SAYS for s in doc.statements)
    assert len(doc.speaks_for) == 1
    assert doc.speaks_for[0].principal == "alice"
    assert doc.speaks_for[0].subject == "bob"
    assert len(doc.delegations) == 1
    deleg = doc.delegations[0]
    assert deleg.principal == "root"
    assert deleg.subject == "carol"
    assert deleg.action == "read"
    assert deleg.resource == "docs_public"
    assert deleg.delegation_depth == 1
    assert len(doc.queries) == 1
    q = doc.queries[0]
    assert q.principal == "alice"
    assert q.action == "read"
    assert q.resource == "docs_payroll"


def test_parse_chc_surface_and_lowering() -> None:
    result = parse_rules(SAMPLE_CHC, profile=RuleProfile.CHC)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.profile is RuleProfile.CHC
    assert any(r.kind is RuleStatementKind.CHC for r in doc.rules)
    lowered = lower_to_chc(doc)
    assert lowered.ok
    assert len(lowered.clauses) >= 3  # 2 edges facts + path rules + query
    assert all(c.clause_id.startswith("chc:") for c in lowered.clauses)
    # No negation in SAMPLE_CHC → no unsupported negation losses for clauses.
    assert "negation" not in " ".join(lowered.unsupported)


def test_chc_lowering_records_secpal_and_negation_losses() -> None:
    text = """\
@world closed_world.
@priority deny_overrides.
@profile secpal.
@trust root.
"root" says role(alice, admin).
"alice" speaks-for "bob".
"root" says "carol" can "read" on "docs" with delegation-depth 1.
resource(docs:resource).
sensitive(docs:resource).
@stratum 0.
allow may(P:principal, read:action, R:resource) :- role(P:principal, admin), resource(R:resource).
@stratum 1.
deny denied(P:principal, read:action, R:resource) :- role(P:principal, admin), sensitive(R:resource), not role(P:principal, admin).
"""
    result = parse_secpal(text)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.document is not None
    lowered = lower_to_chc(result.document)
    kinds = {loss["kind"] for loss in lowered.loss_receipts}
    assert "speaks_for" in kinds
    assert "delegation" in kinds
    assert "negation" in kinds
    assert "speaks_for" in lowered.unsupported
    assert "delegation" in lowered.unsupported
    # Positive allow rule still lowers.
    assert any(c.head.predicate == "may" for c in lowered.clauses)


# ---------------------------------------------------------------------------
# Fail-closed acceptance criteria
# ---------------------------------------------------------------------------


def test_unsafe_head_variable_fails() -> None:
    text = """\
@world closed_world.
parent(alice, bob).
ancestor(X, Y) :- parent(X, Z).
"""
    result = parse_rules(text)
    assert not result.ok
    assert any(item.code == CODE_UNSAFE_VARIABLE for item in result.errors)
    assert any("unsafe" in item.message.lower() for item in result.errors)


def test_unsafe_fact_variable_fails() -> None:
    text = "parent(X, bob).\n"
    result = parse_rules(text, validate=True)
    assert not result.ok
    assert any(item.code == CODE_UNSAFE_VARIABLE for item in result.errors)


def test_unsafe_negative_literal_variable_fails() -> None:
    text = """\
@world closed_world.
p(a).
q(X) :- not r(X).
"""
    result = parse_rules(text)
    assert not result.ok
    assert any(item.code == CODE_UNSAFE_VARIABLE for item in result.errors)


def test_unstratified_negation_same_stratum_fails() -> None:
    text = """\
@world closed_world.
base(a).
@stratum 1.
p(X) :- base(X), q(X).
q(X) :- base(X), not p(X).
"""
    result = parse_rules(text)
    assert not result.ok
    assert any(item.code == CODE_UNSTRATIFIED_NEGATION for item in result.errors)


def test_stratified_negation_with_lower_stratum_succeeds() -> None:
    text = """\
@world closed_world.
base(a).
@stratum 0.
p(X) :- base(X).
@stratum 1.
q(X) :- base(X), not p(X).
"""
    # p is defined only at stratum 0; q at 1 negates p → stratified.
    result = parse_rules(text)
    assert result.ok, [d.message for d in result.diagnostics]


def test_missing_world_semantics_with_negation_fails() -> None:
    text = """\
base(a).
q(X) :- base(X), not missing(X).
"""
    result = parse_rules(text)
    assert not result.ok
    assert any(item.code == CODE_MISSING_WORLD for item in result.errors)


def test_missing_priority_semantics_with_allow_deny_fails() -> None:
    text = """\
@world closed_world.
role(alice, admin).
resource(docs).
allow may(P, read, R) :- role(P, admin), resource(R).
"""
    result = parse_rules(text)
    assert not result.ok
    assert any(item.code == CODE_MISSING_PRIORITY for item in result.errors)


def test_open_world_with_negation_unsupported() -> None:
    text = """\
@world open_world.
base(a).
q(X) :- base(X), not missing(X).
"""
    result = parse_rules(text)
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_CONSTRUCT for item in result.errors)


def test_ambiguous_principal_resource_action_under_secpal_fails() -> None:
    text = """\
@world closed_world.
@priority deny_overrides.
@profile secpal.
@trust root.
may(alice, read, docs).
"""
    result = parse_secpal(text)
    assert not result.ok
    assert any(item.code == CODE_AMBIGUOUS_TERM for item in result.errors)


def test_sorted_authz_terms_are_unambiguous() -> None:
    text = """\
@world closed_world.
@priority deny_overrides.
@profile secpal.
@trust root.
may(alice:principal, read:action, docs:resource).
"""
    result = parse_secpal(text)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    fact = doc.facts[0]
    assert fact.head is not None
    sorts = [arg.sort for arg in fact.head.arguments]
    assert sorts == [
        TermSortHint.PRINCIPAL,
        TermSortHint.ACTION,
        TermSortHint.RESOURCE,
    ]


def test_prefix_sort_annotations() -> None:
    text = """\
@world closed_world.
@priority deny_overrides.
@profile authorization.
@trust root.
may(principal:alice, action:read, resource:docs).
"""
    result = parse_rules(text, profile=RuleProfile.AUTHORIZATION)
    assert result.ok, [d.message for d in result.diagnostics]


# ---------------------------------------------------------------------------
# Unsupported constructs retained
# ---------------------------------------------------------------------------


def test_unsupported_aggregate_retained_as_warning() -> None:
    text = """\
@world closed_world.
p(a).
#count { X : p(X) }.
"""
    result = parse_rules(text)
    # Unsupported retained as warning; program otherwise OK.
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.has_unsupported
    assert any(item.code == CODE_UNSUPPORTED_CONSTRUCT for item in result.warnings)


# ---------------------------------------------------------------------------
# Deterministic print / round-trip
# ---------------------------------------------------------------------------


def test_print_emits_directives_and_rules() -> None:
    doc = elaborate_rules(SAMPLE_DATALOG)
    printed = print_rules(doc)
    assert "interface: RuleFrontend@1" in printed
    assert "@world closed_world." in printed
    assert "@priority deny_overrides." in printed
    assert ":-" in printed
    assert "not " in printed


def test_parse_print_parse_preserves_predicates() -> None:
    result = parse_print_parse_rules(SAMPLE_DATALOG)
    assert result.ok, (result.printed, [d.message for d in result.diagnostics])
    assert result.document is not None
    first = elaborate_rules(SAMPLE_DATALOG)
    assert set(first.predicate_names) == set(result.document.predicate_names)
    assert result.printed


def test_normalization_is_idempotent() -> None:
    doc = elaborate_rules(SAMPLE_DATALOG)
    once = normalize_rules(doc)
    twice = normalize_rules(once)
    assert once.structural_key() == twice.structural_key()
    assert documents_semantically_compatible(once, twice)


def test_secpal_print_round_trip_surface() -> None:
    result = parse_secpal(SAMPLE_SECPAL)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.document is not None
    printed = print_rules(result.document)
    assert "speaks-for" in printed
    assert "delegation-depth" in printed
    assert "query " in printed
    again = parse_secpal(printed)
    assert again.ok, [d.message for d in again.diagnostics]


# ---------------------------------------------------------------------------
# Fail-closed: empty input, limits
# ---------------------------------------------------------------------------


def test_empty_input_fails() -> None:
    result = parse_rules("   \n  % only comments\n")
    assert not result.ok
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert any(item.code == CODE_EMPTY_INPUT for item in result.errors)


def test_input_byte_limit_rejected() -> None:
    text = "p(a).\n" * 20
    result = parse_rules(
        text, limits=ParseLimits(max_input_bytes=16, max_tokens=64, max_depth=16)
    )
    assert not result.ok
    assert any(item.code == CODE_INPUT_LIMIT for item in result.errors)


def test_token_limit_rejected() -> None:
    text = "p(" + ", ".join(f"a{i}" for i in range(40)) + ")."
    result = parse_rules(
        text, limits=ParseLimits(max_input_bytes=4096, max_tokens=8, max_depth=64)
    )
    assert not result.ok
    assert any(item.code == CODE_TOKEN_LIMIT for item in result.errors)


def test_malformed_rule_fails() -> None:
    result = parse_rules("p(X) :- .\n")
    assert not result.ok
    assert result.errors


# ---------------------------------------------------------------------------
# Range restriction helper
# ---------------------------------------------------------------------------


def test_check_range_restriction_helper_on_safe_rule() -> None:
    doc = elaborate_rules(
        "@world closed_world.\np(a).\nq(X) :- p(X).\n"
    )
    rule = doc.rules[0]
    assert check_range_restriction(rule) == ()


def test_frontend_lower_to_chc_method() -> None:
    frontend = _frontend()
    doc = frontend.elaborate(SAMPLE_CHC)
    lowered = frontend.lower_to_chc(doc)
    assert lowered.clauses
    payload = lowered.to_dict()
    assert payload["schema_version"]
    assert payload["ok"] is True


def test_tokenize_rules_basic() -> None:
    tokens, diags = tokenize_rules("p(X) :- q(X), not r(X).")
    assert not diags
    kinds = [t.kind.value for t in tokens if t.kind.value != "eof"]
    assert "rule_neck" in kinds
    assert "not" in kinds
    assert "variable" in kinds


def test_variable_and_constant_term_kinds() -> None:
    doc = elaborate_rules(
        "@world closed_world.\nparent(alice, bob).\nancestor(X, Y) :- parent(X, Y).\n"
    )
    rule = doc.rules[0]
    assert rule.head is not None
    assert rule.head.arguments[0].kind is RuleTermKind.VARIABLE
    fact = doc.facts[0]
    assert fact.head is not None
    assert fact.head.arguments[0].kind is RuleTermKind.CONSTANT


def test_constraint_statement_parses() -> None:
    text = """\
@world closed_world.
constraint equality X equals Y.
p(a).
"""
    result = parse_rules(text)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.constraints) == 1
    assert doc.constraints[0].role is RuleItemRole.CONSTRAINT
