"""Unit tests for Rule/SecPAL/F-logic frontend convergence (LFP2-013).

Acceptance:

* Unsafe/ambiguous rules and raw query strings cannot reach execution without
  typed artifacts and exact diagnostics
* Datalog, SecPAL, and F-logic emit ParseArtifact@2 / ElaborationArtifact@2
* Variables, safety, stratification, delegation, frame slots, rule priority,
  queries, and controlled ErgoAI source are typed
* Frontends register under SharedFrontendConformance@1
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)
from ipfs_datasets_py.logic.parsers.flogic_v2 import (
    CODE_AMBIGUOUS_SLOT,
    CODE_EMPTY_INPUT as FLOGIC_CODE_EMPTY,
    CODE_INPUT_LIMIT as FLOGIC_CODE_INPUT_LIMIT,
    CODE_LAZY_EXECUTION,
    CODE_TOKEN_LIMIT as FLOGIC_CODE_TOKEN_LIMIT,
    CODE_UNSUPPORTED_CONSTRUCT as FLOGIC_CODE_UNSUPPORTED,
    ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE,
    FLOGIC_FRONTEND_V2_INTERFACE,
    FLOGIC_V2_DESCRIPTOR_ID,
    FLOGIC_V2_FAMILY_ID,
    FLOGIC_V2_GOAL_ID,
    FLOGIC_V2_MODULE_VERSION,
    FLOGIC_V2_NOTATION_ID,
    FLOGIC_V2_PROFILE_ID,
    FLOGIC_V2_TASK_ID,
    ErgoAIAuthorityV2Error,
    ErgoAIControlledSourceV2,
    FLogicFrontendV2,
    FLogicFrontendV2Error,
    FLogicItemRole,
    FLogicSpecKind,
    build_flogic_v2_descriptor,
    controlled_source_from_text_v2,
    elaborate_flogic_v2,
    parse_flogic_v2,
    parse_print_parse_flogic_v2,
    print_flogic_v2,
    register_flogic_v2_frontend,
)
from ipfs_datasets_py.logic.parsers.frontend_contract import (
    SharedFrontendConformance,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers.rules_v2 import (
    CODE_AMBIGUOUS_TERM,
    CODE_EMPTY_INPUT,
    CODE_EXECUTION_BLOCKED,
    CODE_INPUT_LIMIT,
    CODE_MISSING_PRIORITY,
    CODE_MISSING_WORLD,
    CODE_TOKEN_LIMIT,
    CODE_UNSAFE_VARIABLE,
    CODE_UNSTRATIFIED_NEGATION,
    CODE_UNSUPPORTED_CONSTRUCT,
    DEFAULT_FRONTEND_LIMITS,
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    PriorityPolicyKind,
    RULE_FRAME_DESCRIPTOR_ID,
    RULE_FRAME_FRONTEND_INTERFACE,
    RULE_FRONTEND_V2_INTERFACE,
    RULE_V2_DESCRIPTOR_ID,
    RULE_V2_FAMILY_ID,
    RULE_V2_GOAL_ID,
    RULE_V2_MODULE_VERSION,
    RULE_V2_NOTATION_ID,
    RULE_V2_PROFILE_ID,
    RULE_V2_TASK_ID,
    RuleEffect,
    RuleExecutionBlockedError,
    RuleFrameFrontend,
    RuleFrontendV2,
    RuleItemRole,
    RuleProfile,
    RuleStatementKind,
    SECPAL_FRONTEND_V2_INTERFACE,
    SECPAL_V2_DESCRIPTOR_ID,
    SECPAL_V2_FAMILY_ID,
    SECPAL_V2_PROFILE_ID,
    SecPALFrontendV2,
    WorldPolicyKind,
    build_rule_frame_descriptor,
    build_rules_v2_descriptor,
    build_secpal_v2_descriptor,
    elaborate_rules_v2,
    lower_to_chc,
    parse_print_parse_rules_v2,
    parse_rules_v2,
    parse_secpal_v2,
    print_rules_v2,
    register_rule_frame_frontend,
    register_rules_v2_frontend,
    register_secpal_v2_frontend,
)
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseLimits, ParseStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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

SAMPLE_FLOGIC = """\
% Animals ontology
Animal.
Dog :: Animal.
Cat :: Animal.
Person[name => string, age => integer, friends =>> Person].
rex[name -> "Rex", age -> 5] : Dog.
whiskers[name -> "Whiskers"] : Cat.
proj1[member ->> {alice, bob}] : Project.
?X[mammal -> true] :- ?X : Animal.
?- ?X : Dog.
"""


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert RULE_FRONTEND_V2_INTERFACE == "RuleFrontend@2"
    assert SECPAL_FRONTEND_V2_INTERFACE == "SecPALFrontend@2"
    assert RULE_FRAME_FRONTEND_INTERFACE == "RuleFrameFrontend@2"
    assert FLOGIC_FRONTEND_V2_INTERFACE == "FLogicFrontend@2"
    assert ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE == "ErgoAIControlledSource@2"
    assert RULE_V2_TASK_ID == "LFP2-013"
    assert FLOGIC_V2_TASK_ID == "LFP2-013"
    assert RULE_V2_GOAL_ID == "LFP2-G030"
    assert FLOGIC_V2_GOAL_ID == "LFP2-G030"
    assert RULE_V2_MODULE_VERSION == "2.0.0"
    assert FLOGIC_V2_MODULE_VERSION == "2.0.0"
    assert RULE_V2_NOTATION_ID == "datalog_rules"
    assert FLOGIC_V2_NOTATION_ID == "flogic"
    assert RULE_V2_PROFILE_ID == "horn"
    assert RULE_V2_FAMILY_ID == "datalog"
    assert SECPAL_V2_PROFILE_ID == "secpal"
    assert SECPAL_V2_FAMILY_ID == "authorization"
    assert FLOGIC_V2_PROFILE_ID == "frame_core"
    assert FLOGIC_V2_FAMILY_ID == "frame_logic"

    rules = RuleFrontendV2()
    assert rules.interface == RULE_FRONTEND_V2_INTERFACE
    assert rules.descriptor.descriptor_id == RULE_V2_DESCRIPTOR_ID
    assert DEFAULT_FRONTEND_LIMITS.parse_limits.max_input_bytes > 0

    secpal = SecPALFrontendV2()
    assert secpal.interface == SECPAL_FRONTEND_V2_INTERFACE
    assert secpal.family_id == SECPAL_V2_FAMILY_ID

    frame = RuleFrameFrontend()
    assert frame.interface == RULE_FRAME_FRONTEND_INTERFACE
    assert frame.descriptor.descriptor_id == RULE_FRAME_DESCRIPTOR_ID

    flogic = FLogicFrontendV2()
    assert flogic.interface == FLOGIC_FRONTEND_V2_INTERFACE
    assert flogic.authority is ResultAuthority.CANDIDATE
    assert flogic.role is ToolRole.ADVISOR
    assert flogic.authority_ceiling is ToolchainAuthorityCeiling.ADVISORY
    assert not role_can_satisfy_certified_authority(
        flogic.role, flogic.authority_ceiling
    )


# ---------------------------------------------------------------------------
# Descriptor / shared frontend conformance
# ---------------------------------------------------------------------------


def test_rules_descriptor_declares_shared_artifacts_limits_diagnostics() -> None:
    descriptor = build_rules_v2_descriptor()
    validate_frontend_descriptor(descriptor)
    interfaces = {item.interface for item in descriptor.artifact_outputs}
    assert PARSE_ARTIFACT_V2_INTERFACE in interfaces
    assert ELABORATION_ARTIFACT_V2_INTERFACE in interfaces
    assert descriptor.limits.parse_limits.max_input_bytes > 0
    assert descriptor.limits.parse_limits.max_tokens > 0
    assert descriptor.diagnostics
    assert all("." in code for code in descriptor.diagnostics)
    assert "parse" in descriptor.features
    assert "elaborate" in descriptor.features
    assert "source_map" in descriptor.features
    assert "typecheck" in descriptor.features
    assert descriptor.fixtures


def test_secpal_and_rule_frame_and_flogic_register() -> None:
    registry = SharedFrontendConformance()
    _, rules_admitted = register_rules_v2_frontend(registry)
    _, secpal_admitted = register_secpal_v2_frontend(registry)
    _, frame_admitted = register_rule_frame_frontend(registry)
    _, flogic_admitted = register_flogic_v2_frontend(registry)

    assert rules_admitted.descriptor_id == RULE_V2_DESCRIPTOR_ID
    assert secpal_admitted.descriptor_id == SECPAL_V2_DESCRIPTOR_ID
    assert frame_admitted.descriptor_id == RULE_FRAME_DESCRIPTOR_ID
    assert flogic_admitted.descriptor_id == FLOGIC_V2_DESCRIPTOR_ID
    assert len(registry) == 4

    for descriptor in (
        build_secpal_v2_descriptor(),
        build_rule_frame_descriptor(),
        build_flogic_v2_descriptor(),
    ):
        validate_frontend_descriptor(descriptor)
        assert PARSE_ARTIFACT_V2_INTERFACE in descriptor.artifact_interfaces()
        assert ELABORATION_ARTIFACT_V2_INTERFACE in descriptor.artifact_interfaces()


# ---------------------------------------------------------------------------
# Happy-path: Datalog / SecPAL / CHC with typed artifacts
# ---------------------------------------------------------------------------


def test_parse_datalog_emits_parse_and_elaboration_artifacts() -> None:
    result = parse_rules_v2(SAMPLE_DATALOG)
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.parse_artifact, ParseArtifactV2)
    assert isinstance(result.elaboration_artifact, ElaborationArtifactV2)
    assert result.parse_artifact.interface == "ParseArtifact@2"
    assert result.elaboration_artifact.interface == "ElaborationArtifact@2"
    assert result.parse_artifact.status is ParseStatus.OK
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.OK
    assert result.typed_expression is not None
    assert result.document is not None
    assert result.document.world_policy is WorldPolicyKind.CLOSED_WORLD
    assert result.document.priority_policy is PriorityPolicyKind.DENY_OVERRIDES
    assert result.document.profile is RuleProfile.DATALOG
    assert len(result.document.rules) == 2
    assert len(result.document.queries) == 1
    assert result.queries_typed
    assert result.parse_artifact.metadata.get("raw_query_strings_admitted") is False
    assert result.parse_artifact.metadata.get("execution_admitted") is False
    assert result.elaboration_artifact.metadata.get("queries_typed") is True

    result.elaboration_artifact.validate_lineage(
        parse_artifact=result.parse_artifact,
        document=result.source_document,
    )
    assert result.parse_artifact.cst is not None
    assert result.parse_artifact.source_map is not None
    assert result.parse_artifact.typed_roots
    assert result.elaboration_artifact.typed_expression is not None

    # Typed query inventory on the expression root payload.
    root = result.typed_expression.root
    assert root.extension is not None
    payload = dict(root.extension.payload)
    assert payload.get("raw_query_strings_admitted") is False
    assert payload.get("query_count") == 1
    assert payload["queries"][0]["typed"] is True
    assert payload["queries"][0]["predicate"] == "may"


def test_parse_secpal_delegation_speaks_for_typed_query() -> None:
    result = parse_secpal_v2(SAMPLE_SECPAL)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.profile is RuleProfile.SECPAL
    assert any(s.role is RuleItemRole.SECPAL_SAYS for s in doc.statements)
    assert len(doc.speaks_for) == 1
    assert doc.speaks_for[0].principal == "alice"
    assert len(doc.delegations) == 1
    deleg = doc.delegations[0]
    assert deleg.subject == "carol"
    assert deleg.action == "read"
    assert deleg.delegation_depth == 1
    assert len(doc.queries) == 1
    q = doc.queries[0]
    assert q.principal == "alice"
    assert q.action == "read"
    assert q.resource == "docs_payroll"
    assert result.queries_typed
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.typed_expression is not None


def test_parse_chc_and_lowering() -> None:
    result = RuleFrontendV2(default_profile=RuleProfile.CHC).parse_text(
        SAMPLE_CHC, lower_chc=True
    )
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert any(r.kind is RuleStatementKind.CHC for r in doc.rules)
    lowered = result.chc_lowering or lower_to_chc(doc)
    assert lowered.ok
    assert len(lowered.clauses) >= 3


def test_stratified_negation_and_priority_effects() -> None:
    result = parse_rules_v2(SAMPLE_DATALOG)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    allow_rule = next(r for r in doc.rules if r.effect is RuleEffect.ALLOW)
    deny_rule = next(r for r in doc.rules if r.effect is RuleEffect.DENY)
    assert allow_rule.stratum == 0
    assert deny_rule.stratum == 1
    assert any(atom.is_negative for atom in deny_rule.body)


def test_rules_round_trip() -> None:
    result = parse_print_parse_rules_v2(SAMPLE_DATALOG)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.document is not None
    assert result.parse_artifact is not None
    reprinted = print_rules_v2(result.document)
    assert "may" in reprinted
    assert "role" in reprinted


# ---------------------------------------------------------------------------
# Happy-path: F-logic frames, slots, queries, controlled source
# ---------------------------------------------------------------------------


def test_parse_flogic_emits_typed_frame_slots_and_artifacts() -> None:
    result = parse_flogic_v2(SAMPLE_FLOGIC)
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.parse_artifact, ParseArtifactV2)
    assert isinstance(result.elaboration_artifact, ElaborationArtifactV2)
    assert result.typed_expression is not None
    doc = result.document
    assert doc is not None
    assert "Dog" in doc.class_names
    assert "name" in doc.method_names
    assert "rex" in doc.frame_object_ids
    assert len(doc.queries) == 1
    assert result.queries_typed

    root = result.typed_expression.root
    assert root.extension is not None
    payload = dict(root.extension.payload)
    assert payload.get("raw_query_strings_admitted") is False
    assert payload.get("frame_slots")
    assert any(slot["method"] == "name" for slot in payload["frame_slots"])
    assert any(q["typed"] is True for q in payload["queries"])

    assert result.controlled_source is not None
    src = result.controlled_source
    assert src.interface == ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE
    assert src.authority is ResultAuthority.CANDIDATE
    assert src.status is ResultStatus.CANDIDATE
    assert src.role is ToolRole.ADVISOR
    assert src.trusted is False
    assert src.can_certify is False
    assert src.has_typed_artifacts


def test_flogic_inheritance_signatures_and_round_trip() -> None:
    result = parse_flogic_v2(
        "Dog :: Animal.\nPerson[name => string, friends =>> Person].\n"
    )
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    inherit = doc.facts[0]
    assert inherit.role is FLogicItemRole.INHERITANCE
    sig = doc.facts[1]
    assert sig.role is FLogicItemRole.SIGNATURE
    kinds = {spec.kind for spec in sig.head.specs}  # type: ignore[union-attr]
    assert FLogicSpecKind.SCALAR_SIGNATURE in kinds
    assert FLogicSpecKind.SET_SIGNATURE in kinds

    rt = parse_print_parse_flogic_v2(SAMPLE_FLOGIC)
    assert rt.ok, [d.message for d in rt.diagnostics]
    assert rt.document is not None
    printed = print_flogic_v2(rt.document)
    assert "Dog" in printed


def test_flogic_controlled_source_from_text() -> None:
    src = controlled_source_from_text_v2("rex[name -> \"Rex\"] : Dog.\n")
    assert isinstance(src, ErgoAIControlledSourceV2)
    assert src.has_typed_artifacts
    assert src.authority is ResultAuthority.CANDIDATE


# ---------------------------------------------------------------------------
# Fail-closed: unsafe / ambiguous / missing semantics
# ---------------------------------------------------------------------------


def test_unsafe_head_variable_fails_with_exact_diagnostic_and_artifacts() -> None:
    text = """\
@world closed_world.
parent(alice, bob).
ancestor(X, Y) :- parent(X, Z).
"""
    result = parse_rules_v2(text)
    assert not result.ok
    assert any(item.code == CODE_UNSAFE_VARIABLE for item in result.errors)
    assert any("unsafe" in item.message.lower() for item in result.errors)
    # Fail-closed: parse + failed elaboration artifacts still present.
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED
    assert result.parse_artifact.metadata.get("execution_admitted") is False
    assert result.typed_expression is None


def test_unstratified_negation_fails() -> None:
    text = """\
@world closed_world.
base(a).
@stratum 1.
p(X) :- base(X), q(X).
q(X) :- base(X), not p(X).
"""
    result = parse_rules_v2(text)
    assert not result.ok
    assert any(item.code == CODE_UNSTRATIFIED_NEGATION for item in result.errors)
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED


def test_missing_world_and_priority_fail() -> None:
    neg = parse_rules_v2("base(a).\nq(X) :- base(X), not missing(X).\n")
    assert not neg.ok
    assert any(item.code == CODE_MISSING_WORLD for item in neg.errors)

    allow = parse_rules_v2(
        """\
@world closed_world.
role(alice, admin).
resource(docs).
allow may(P, read, R) :- role(P, admin), resource(R).
"""
    )
    assert not allow.ok
    assert any(item.code == CODE_MISSING_PRIORITY for item in allow.errors)


def test_ambiguous_principal_resource_action_under_secpal_fails() -> None:
    text = """\
@world closed_world.
@priority deny_overrides.
@profile secpal.
@trust root.
may(alice, read, docs).
"""
    result = parse_secpal_v2(text)
    assert not result.ok
    assert any(item.code == CODE_AMBIGUOUS_TERM for item in result.errors)
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED
    assert result.typed_expression is None


def test_ambiguous_frame_slot_fails() -> None:
    text = """\
rex[name -> "Rex"].
rex[name -> "Max"].
"""
    result = parse_flogic_v2(text)
    assert not result.ok
    assert any(item.code == CODE_AMBIGUOUS_SLOT for item in result.errors)
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED
    assert result.typed_expression is None


# ---------------------------------------------------------------------------
# Execution blocked without typed path
# ---------------------------------------------------------------------------


def test_rules_and_frame_execute_blocked() -> None:
    rules = RuleFrontendV2()
    with pytest.raises(RuleExecutionBlockedError) as exc:
        rules.execute("?- may(alice, read, docs).")
    assert exc.value.code == CODE_EXECUTION_BLOCKED

    frame = RuleFrameFrontend()
    with pytest.raises(RuleExecutionBlockedError):
        frame.execute()

    flogic = FLogicFrontendV2()
    with pytest.raises(FLogicFrontendV2Error) as fexc:
        flogic.execute()
    assert fexc.value.code == CODE_LAZY_EXECUTION

    src = controlled_source_from_text_v2("rex[name -> \"Rex\"] : Dog.\n")
    with pytest.raises(FLogicFrontendV2Error) as sexc:
        src.execute()
    assert sexc.value.code == CODE_LAZY_EXECUTION


def test_ergoai_authority_cannot_elevate() -> None:
    result = parse_flogic_v2("rex[name -> \"Rex\"] : Dog.\n")
    assert result.ok
    assert result.document is not None
    with pytest.raises(ErgoAIAuthorityV2Error):
        ErgoAIControlledSourceV2(
            document=result.document,
            authority=ResultAuthority.THEOREM,  # type: ignore[arg-type]
        )


def test_raw_query_string_not_executable_via_ok_path() -> None:
    """Successful results always carry typed queries; never raw-only goals."""

    result = elaborate_rules_v2("?- path(a, c).\nedge(a, c).\n@world closed_world.\n")
    # May fail validation if world/facts incomplete — either way no execution.
    if result.ok:
        assert result.queries_typed
        assert result.typed_expression is not None
        assert result.parse_artifact is not None
        assert result.elaboration_artifact is not None
        assert result.parse_artifact.metadata.get("raw_query_strings_admitted") is False
    else:
        assert result.parse_artifact is not None
        assert result.elaboration_artifact is not None
        assert result.typed_expression is None

    fresult = elaborate_flogic_v2("?- ?X : Dog.\nDog :: Animal.\n")
    assert fresult.ok, [d.message for d in fresult.diagnostics]
    assert fresult.queries_typed
    assert fresult.typed_expression is not None
    root = fresult.typed_expression.root
    assert root.extension is not None
    assert root.extension.payload.get("raw_query_strings_admitted") is False


# ---------------------------------------------------------------------------
# Resource limits
# ---------------------------------------------------------------------------


def test_input_and_token_limits_reject() -> None:
    tiny = ParseLimits(max_input_bytes=8, max_tokens=4, max_depth=8, max_diagnostics=8)
    r = parse_rules_v2(SAMPLE_DATALOG, limits=tiny)
    assert not r.ok
    assert any(
        item.code in {CODE_INPUT_LIMIT, CODE_TOKEN_LIMIT, CODE_EMPTY_INPUT}
        for item in r.errors
    )
    assert r.parse_artifact is not None

    f = parse_flogic_v2(SAMPLE_FLOGIC, limits=tiny)
    assert not f.ok
    assert any(
        item.code
        in {
            FLOGIC_CODE_INPUT_LIMIT,
            FLOGIC_CODE_TOKEN_LIMIT,
            FLOGIC_CODE_EMPTY,
        }
        for item in f.errors
    )
    assert f.parse_artifact is not None


def test_empty_input_fails() -> None:
    r = parse_rules_v2("")
    assert not r.ok
    assert any(item.code == CODE_EMPTY_INPUT for item in r.errors)

    f = parse_flogic_v2("")
    assert not f.ok
    assert any(item.code == FLOGIC_CODE_EMPTY for item in f.errors)


# ---------------------------------------------------------------------------
# Joint RuleFrameFrontend facade
# ---------------------------------------------------------------------------


def test_rule_frame_facade_dispatches_rules_secpal_flogic() -> None:
    facade = RuleFrameFrontend()
    rules_result = facade.parse_rules(SAMPLE_DATALOG)
    assert rules_result.ok, [d.message for d in rules_result.diagnostics]
    assert rules_result.parse_artifact is not None
    assert rules_result.elaboration_artifact is not None

    secpal_result = facade.parse_secpal(SAMPLE_SECPAL)
    assert secpal_result.ok, [d.message for d in secpal_result.diagnostics]

    flogic_result = facade.parse_flogic(SAMPLE_FLOGIC)
    assert flogic_result.ok, [d.message for d in flogic_result.diagnostics]
    assert flogic_result.controlled_source is not None
    assert flogic_result.controlled_source.has_typed_artifacts


def test_unsupported_ergoai_construct_diagnosed() -> None:
    # Transaction / defeasible markers outside controlled subset.
    text = "p(X) ~> q(X).\n"
    result = parse_flogic_v2(text)
    # Either fails or retains unsupported with diagnostic.
    if result.ok:
        assert result.document is not None
        assert result.document.has_unsupported or any(
            item.code == FLOGIC_CODE_UNSUPPORTED for item in result.diagnostics
        )
    else:
        assert any(
            item.code == FLOGIC_CODE_UNSUPPORTED
            or item.code.startswith("flogic.")
            for item in result.errors
        )
    assert result.parse_artifact is not None
