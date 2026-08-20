"""Unit tests for protocol/Tamarin/program frontend convergence (LFP2-014).

Acceptance:

* No raw protocol rule, target source, or program assertion bypasses
  parse/elaboration artifacts
* Protocol, Tamarin, and program emit ParseArtifact@2 / ElaborationArtifact@2
* Terms/equations/roles/events/rules and contracts/commands/VCs are typed with
  source maps and profile limits
* Frontends register under SharedFrontendConformance@1
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.parsers.frontend_contract import (
    SharedFrontendConformance,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers.program_v2 import (
    CODE_RAW_ASSERTION,
    CODE_UNSUPPORTED_LOOP,
    CODE_VC_WITHOUT_ARTIFACTS,
    DEFAULT_FRONTEND_LIMITS as PROGRAM_DEFAULT_LIMITS,
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    PROGRAM_FRONTEND_V2_INTERFACE,
    PROGRAM_V2_BINDING_VERSION,
    PROGRAM_V2_DESCRIPTOR_ID,
    PROGRAM_V2_FAMILY_ID,
    PROGRAM_V2_GOAL_ID,
    PROGRAM_V2_MODULE_VERSION,
    PROGRAM_V2_NOTATION_ID,
    PROGRAM_V2_PROFILE_ID,
    PROGRAM_V2_STATE_VERSION,
    PROGRAM_V2_TASK_ID,
    VC_BRIDGE_V2_INTERFACE,
    VC_VIEW_ROLE,
    ProgramArtifactBypassError,
    ProgramFrontendV2,
    build_program_v2_descriptor,
    lower_to_vc_v2,
    parse_program_v2,
    print_program_v2,
    register_program_v2_frontend,
)
from ipfs_datasets_py.logic.parsers.protocol_v2 import (
    CODE_BYPASS_BLOCKED,
    CODE_RAW_RULE,
    CODE_RAW_TARGET_SOURCE,
    CODE_UNSUPPORTED_PROCESS,
    DEFAULT_FRONTEND_LIMITS as PROTOCOL_DEFAULT_LIMITS,
    PROTOCOL_FRONTEND_V2_INTERFACE,
    PROTOCOL_PROGRAM_DESCRIPTOR_ID,
    PROTOCOL_PROGRAM_FRONTEND_INTERFACE,
    PROTOCOL_V2_DESCRIPTOR_ID,
    PROTOCOL_V2_FAMILY_ID,
    PROTOCOL_V2_GOAL_ID,
    PROTOCOL_V2_MODULE_VERSION,
    PROTOCOL_V2_NOTATION_ID,
    PROTOCOL_V2_PROFILE_ID,
    PROTOCOL_V2_TASK_ID,
    ProcessKind,
    ProcessNode,
    ProtocolArtifactBypassError,
    ProtocolFrontendV2,
    ProtocolProgramFrontend,
    TAMARIN_FRONTEND_V2_INTERFACE,
    TAMARIN_V2_DESCRIPTOR_ID,
    TAMARIN_V2_FAMILY_ID,
    TAMARIN_V2_NOTATION_ID,
    TAMARIN_V2_PROFILE_ID,
    TamarinFrontendV2,
    build_protocol_program_descriptor,
    build_protocol_v2_descriptor,
    build_tamarin_v2_descriptor,
    parse_protocol_v2,
    parse_tamarin_v2,
    print_protocol_v2,
    print_tamarin_v2,
    register_protocol_program_frontend,
    register_protocol_v2_frontend,
    register_tamarin_v2_frontend,
)
from ipfs_datasets_py.logic.software_verification.contracts import (
    ContractClause,
    ContractClauseKind,
    DynamicLogicExit,
    DynamicLogicFormula,
    DynamicLogicModality,
    DynamicProgramKind,
    FrameCondition,
    HoareTriple,
    LoopContract,
    ProgramContract,
)
from ipfs_datasets_py.logic.software_verification.program import (
    BasicBlock,
    CommandKind,
    ControlFlowEdge,
    ControlFlowGraph,
    EdgeKind,
    EffectSummary,
    ExpressionKind,
    ProgramCommand,
    ProgramExpression,
    ProgramFunction,
    ProgramIR,
    ProgramSymbol,
    Purity,
    SymbolKind,
    UndefinedBehaviorCondition,
    UndefinedBehaviorConsequence,
)
from ipfs_datasets_py.logic.software_verification.protocol import (
    AdversaryAccess,
    AdversaryCapability,
    AdversaryKind,
    AdversaryKnowledge,
    ChannelSecurity,
    CorrespondenceKind,
    EquationalTheory,
    EventPhase,
    FreshName,
    FreshNameKind,
    FunctionKind,
    KeyKind,
    ProtocolAdversary,
    ProtocolChannel,
    ProtocolClaim,
    ProtocolClaimKind,
    ProtocolEvent,
    ProtocolFunction,
    ProtocolIR,
    ProtocolKey,
    ProtocolMessage,
    ProtocolRole,
    ProtocolSort,
    ProtocolTerm,
    ProtocolVariable,
    RewriteFact,
    SortKind,
    TrustAssumption,
)
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseStatus
from ipfs_datasets_py.logic.parsers.tamarin import (
    FactKind,
    FactMultiplicity,
    MultisetFact,
    MultisetRule,
    TraceLemma,
    LemmaQuantifier,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SOURCE_ID = "source:handshake"
SPAN_ID = "span:protocol"
PROG_SOURCE_ID = "source:counter"
PROG_SPAN_ID = "span:counter"


def _source() -> SourceRef:
    return SourceRef(
        ref_id=SOURCE_ID,
        source_uri="file:///protocols/handshake.protocol.json",
        source_id="handshake.protocol.json",
        source_revision="git:0123456789abcdef",
        content_sha256="a" * 64,
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id=SPAN_ID,
        source_ref_id=SOURCE_ID,
        start_byte=0,
        end_byte=1024,
        start_line=1,
        start_column=1,
        end_line=40,
        end_column=2,
    )


def _mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (SOURCE_ID,), "span_ids": (SPAN_ID,)}


def _protocol(
    *,
    equational_theories: tuple[EquationalTheory, ...] = (
        EquationalTheory.FREE,
        EquationalTheory.SYMMETRIC_ENCRYPTION,
    ),
    adversary_kind: AdversaryKind = AdversaryKind.DOLEV_YAO,
) -> ProtocolIR:
    use_symmetric = EquationalTheory.SYMMETRIC_ENCRYPTION in equational_theories
    theory = (
        EquationalTheory.SYMMETRIC_ENCRYPTION
        if use_symmetric
        else EquationalTheory.FREE
    )
    sorts = (
        ProtocolSort("sort:agent", "Agent", SortKind.AGENT, **_mapped()),
        ProtocolSort("sort:key", "Key", SortKind.KEY, **_mapped()),
        ProtocolSort("sort:message", "Message", SortKind.MESSAGE, **_mapped()),
        ProtocolSort("sort:nonce", "Nonce", SortKind.NONCE, **_mapped()),
    )
    variables = (
        ProtocolVariable(
            "variable:initiator-peer",
            "peer",
            "sort:agent",
            role_id="role:initiator",
            **_mapped(),
        ),
        ProtocolVariable(
            "variable:responder-peer",
            "peer",
            "sort:agent",
            role_id="role:responder",
            **_mapped(),
        ),
    )
    roles = (
        ProtocolRole(
            "role:initiator",
            "Initiator",
            parameter_ids=("variable:initiator-peer",),
            **_mapped(),
        ),
        ProtocolRole(
            "role:responder",
            "Responder",
            parameter_ids=("variable:responder-peer",),
            **_mapped(),
        ),
    )
    nonce = FreshName(
        "name:challenge",
        "challenge",
        "sort:nonce",
        "role:initiator",
        FreshNameKind.NONCE,
        **_mapped(),
    )
    keys = (
        ProtocolKey(
            "key:session",
            "session_key",
            "sort:key",
            KeyKind.SYMMETRIC,
            ("role:initiator", "role:responder"),
            **_mapped(),
        ),
    )
    functions = (
        ProtocolFunction(
            "function:encrypt",
            "encrypt",
            ("sort:nonce", "sort:key"),
            "sort:message",
            FunctionKind.CONSTRUCTOR,
            theory,
            **_mapped(),
        ),
        ProtocolFunction(
            "function:decrypt",
            "decrypt",
            ("sort:message", "sort:key"),
            "sort:nonce",
            FunctionKind.DESTRUCTOR,
            theory,
            **_mapped(),
        ),
    )
    nonce_term = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    session_key = ProtocolTerm.symbol("key:session", "sort:key")
    ciphertext = ProtocolTerm.application(
        "function:encrypt", (nonce_term, session_key), "sort:message"
    )
    plaintext = ProtocolTerm.application(
        "function:decrypt", (ciphertext, session_key), "sort:nonce"
    )
    assumption = TrustAssumption(
        "assumption:session-key",
        "The long-term mechanism delivers the session key only to both roles.",
        trusted_role_ids=("role:initiator", "role:responder"),
        trusted_key_ids=("key:session",),
        **_mapped(),
    )
    channel = ProtocolChannel(
        "channel:network",
        "network",
        ChannelSecurity.PUBLIC,
        AdversaryAccess.CONTROL
        if adversary_kind is AdversaryKind.DOLEV_YAO
        else AdversaryAccess.OBSERVE,
        **_mapped(),
    )
    message = ProtocolMessage(
        "message:challenge",
        "encrypted challenge",
        ciphertext,
        "role:initiator",
        ("role:responder",),
        "channel:network",
        **_mapped(),
    )
    begin = ProtocolEvent(
        "event:begin",
        "BeginChallenge",
        "role:initiator",
        (nonce_term,),
        EventPhase.BEGIN,
        **_mapped(),
    )
    accept = ProtocolEvent(
        "event:accept",
        "AcceptChallenge",
        "role:responder",
        (nonce_term,),
        EventPhase.ACCEPT,
        **_mapped(),
    )
    claims = (
        ProtocolClaim(
            "claim:secrecy",
            ProtocolClaimKind.SECRECY,
            "The challenge remains secret.",
            secret_terms=(nonce_term,),
            assumption_ids=("assumption:session-key",),
            **_mapped(),
        ),
        ProtocolClaim(
            "claim:authentication",
            ProtocolClaimKind.AUTHENTICATION,
            "Every accept authenticates an initiator run.",
            antecedent_event_ids=("event:accept",),
            consequent_event_ids=("event:begin",),
            correspondence=CorrespondenceKind.INJECTIVE,
            assumption_ids=("assumption:session-key",),
            **_mapped(),
        ),
    )
    if adversary_kind is AdversaryKind.DOLEV_YAO:
        capabilities = tuple(AdversaryCapability)
    elif adversary_kind is AdversaryKind.PASSIVE:
        capabilities = (
            AdversaryCapability.COMPOSE,
            AdversaryCapability.DECOMPOSE,
            AdversaryCapability.INTERCEPT,
        )
    else:
        capabilities = ()
    adversary = ProtocolAdversary(
        "adversary:network",
        adversary_kind,
        capabilities,
        knowledge=(
            AdversaryKnowledge(
                "knowledge:public-observation",
                ProtocolTerm(sort="sort:message", literal="public-tag"),
                **_mapped(),
            ),
        )
        if adversary_kind is not AdversaryKind.NONE
        else (),
        **_mapped(),
    )
    rewrite_facts = ()
    if use_symmetric:
        rewrite_facts = (
            RewriteFact(
                "fact:decrypt-encrypt",
                plaintext,
                nonce_term,
                EquationalTheory.SYMMETRIC_ENCRYPTION,
                **_mapped(),
            ),
        )
    return ProtocolIR(
        sources=(_source(),),
        spans=(_span(),),
        sorts=sorts,
        variables=variables,
        roles=roles,
        fresh_names=(nonce,),
        keys=keys,
        functions=functions,
        trust_assumptions=(assumption,),
        channels=(channel,),
        messages=(message,),
        adversary=adversary,
        rewrite_facts=rewrite_facts,
        events=(begin, accept),
        claims=claims,
        equational_theories=equational_theories,
        metadata={"protocol": "challenge-response", "version": 1},
    )


def _initiator_process() -> ProcessNode:
    nonce_term = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    session_key = ProtocolTerm.symbol("key:session", "sort:key")
    ciphertext = ProtocolTerm.application(
        "function:encrypt", (nonce_term, session_key), "sort:message"
    )
    return ProcessNode(
        kind=ProcessKind.SEQUENCE,
        children=(
            ProcessNode(
                kind=ProcessKind.NEW,
                name="name:challenge",
                sort="sort:nonce",
                children=(
                    ProcessNode(
                        kind=ProcessKind.EVENT,
                        event_id="event:begin",
                        parameters=(nonce_term,),
                        children=(
                            ProcessNode(
                                kind=ProcessKind.OUT,
                                channel="channel:network",
                                term=ciphertext,
                                children=(ProcessNode.null(),),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _protocol_document_payload() -> dict:
    protocol = _protocol()
    return {
        "protocol": protocol.to_dict(),
        "processes": {
            "role:initiator": _initiator_process().to_dict(),
        },
    }


def _tamarin_document_payload() -> dict:
    protocol = _protocol()
    nonce_term = ProtocolTerm.symbol("name:challenge", "sort:nonce")
    fact_st = MultisetFact(
        fact_id="fact:StInit",
        name="St_Init",
        multiplicity=FactMultiplicity.LINEAR,
        kind=FactKind.STATE,
        arguments=(nonce_term,),
        **_mapped(),
    )
    fact_out = MultisetFact(
        fact_id="fact:Out",
        name="Out",
        multiplicity=FactMultiplicity.LINEAR,
        kind=FactKind.MESSAGE_OUT,
        arguments=(nonce_term,),
        **_mapped(),
    )
    fact_action = MultisetFact(
        fact_id="fact:action-begin",
        name="BeginChallenge",
        multiplicity=FactMultiplicity.LINEAR,
        kind=FactKind.ACTION,
        arguments=(nonce_term,),
        **_mapped(),
    )
    rule = MultisetRule(
        rule_id="rule:send",
        name="SendChallenge",
        premises=(fact_st,),
        actions=(fact_action,),
        conclusions=(fact_out,),
        **_mapped(),
    )
    lemma = TraceLemma(
        lemma_id="lemma:secrecy",
        name="secrecy",
        quantifier=LemmaQuantifier.ALL_TRACES,
        formula="All n #i. Secret(n) @ i ==> not (Ex #j. K(n) @ j)",
        claim_id="claim:secrecy",
        **_mapped(),
    )
    return {
        "protocol": protocol.to_dict(),
        "facts": [fact_st.to_dict(), fact_out.to_dict(), fact_action.to_dict()],
        "rules": [rule.to_dict()],
        "lemmas": [lemma.to_dict()],
    }


def _prog_mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (PROG_SOURCE_ID,), "span_ids": (PROG_SPAN_ID,)}


def _program() -> ProgramIR:
    symbols = (
        ProgramSymbol(
            "symbol:x",
            "x",
            "integer",
            SymbolKind.PARAMETER,
            **_prog_mapped(),
        ),
        ProgramSymbol(
            "symbol:result",
            "result",
            "integer",
            SymbolKind.RESULT,
            **_prog_mapped(),
        ),
    )
    expressions = (
        ProgramExpression(
            "expr:x",
            ExpressionKind.SYMBOL,
            "integer",
            symbol_ids=("symbol:x",),
            **_prog_mapped(),
        ),
        ProgramExpression(
            "expr:zero",
            ExpressionKind.LITERAL,
            "integer",
            attributes={"value": 0},
            **_prog_mapped(),
        ),
        ProgramExpression(
            "expr:one",
            ExpressionKind.LITERAL,
            "integer",
            attributes={"value": 1},
            **_prog_mapped(),
        ),
        ProgramExpression(
            "expr:positive",
            ExpressionKind.BINARY,
            "boolean",
            operand_ids=("expr:x", "expr:zero"),
            evaluation_order=("expr:x", "expr:zero"),
            operator="greater_than",
            **_prog_mapped(),
        ),
        ProgramExpression(
            "expr:add",
            ExpressionKind.BINARY,
            "integer",
            operand_ids=("expr:x", "expr:one"),
            evaluation_order=("expr:one", "expr:x"),
            operator="add",
            **_prog_mapped(),
        ),
        ProgramExpression(
            "expr:result",
            ExpressionKind.RESULT,
            "integer",
            symbol_ids=("symbol:result",),
            **_prog_mapped(),
        ),
    )
    undefined = UndefinedBehaviorCondition(
        "ub:overflow",
        "expr:positive",
        "The source language traps when its bounded integer overflows.",
        UndefinedBehaviorConsequence.TRAP,
        **_prog_mapped(),
    )
    commands = (
        ProgramCommand(
            "command:guard",
            CommandKind.ASSERT,
            expression_ids=("expr:positive",),
            effects=EffectSummary(reads=("symbol:x",)),
            **_prog_mapped(),
        ),
        ProgramCommand(
            "command:increment",
            CommandKind.ASSIGN,
            expression_ids=("expr:add",),
            target_symbol_ids=("symbol:result",),
            effects=EffectSummary(reads=("symbol:x",), writes=("symbol:result",)),
            undefined_behavior=(undefined,),
            **_prog_mapped(),
        ),
        ProgramCommand(
            "command:return",
            CommandKind.RETURN,
            expression_ids=("expr:result",),
            effects=EffectSummary(reads=("symbol:result",)),
            **_prog_mapped(),
        ),
        ProgramCommand(
            "command:throw",
            CommandKind.THROW,
            effects=EffectSummary(raises=("ValueError",)),
            **_prog_mapped(),
        ),
    )
    cfg = ControlFlowGraph(
        graph_id="cfg:increment",
        entry_block_id="block:entry",
        blocks=(
            BasicBlock("block:entry", ("command:guard",), **_prog_mapped()),
            BasicBlock(
                "block:normal",
                ("command:increment", "command:return"),
                **_prog_mapped(),
            ),
            BasicBlock("block:exception", ("command:throw",), **_prog_mapped()),
        ),
        edges=(
            ControlFlowEdge(
                "edge:valid",
                "block:entry",
                "block:normal",
                EdgeKind.TRUE,
                order=0,
                condition_expression_id="expr:positive",
            ),
            ControlFlowEdge(
                "edge:invalid",
                "block:entry",
                "block:exception",
                EdgeKind.FALSE,
                order=1,
                condition_expression_id="expr:positive",
            ),
        ),
        normal_exit_block_ids=("block:normal",),
        exceptional_exit_block_ids=("block:exception",),
    )
    function = ProgramFunction(
        function_id="function:increment",
        name="increment",
        cfg=cfg,
        parameter_symbol_ids=("symbol:x",),
        result_symbol_id="symbol:result",
        return_type="integer",
        purity=Purity.IMPURE,
        effects=EffectSummary(
            reads=("symbol:x", "symbol:result"),
            writes=("symbol:result",),
            raises=("ValueError",),
        ),
        declared_exceptions=("ValueError",),
        **_prog_mapped(),
    )
    return ProgramIR(
        sources=(
            SourceRef(
                ref_id=PROG_SOURCE_ID,
                source_uri="file:///src/counter.example",
                source_id="counter.example",
                source_revision="git:0123456789abcdef",
                content_sha256="a" * 64,
            ),
        ),
        spans=(
            SourceSpan(
                span_id=PROG_SPAN_ID,
                source_ref_id=PROG_SOURCE_ID,
                start_byte=0,
                end_byte=120,
                start_line=1,
                start_column=1,
                end_line=8,
                end_column=2,
            ),
        ),
        symbols=symbols,
        expressions=expressions,
        commands=commands,
        functions=(function,),
        metadata={"language": "example", "integer_model": "bounded"},
    )


def _clause(
    clause_id: str,
    kind: ContractClauseKind,
    expression_id: str,
    *,
    exception_type: str = "",
) -> ContractClause:
    return ContractClause(
        clause_id,
        kind,
        expression_id,
        f"{kind.value} for increment.",
        exception_type=exception_type,
        **_prog_mapped(),
    )


def _contract() -> ProgramContract:
    return ProgramContract(
        contract_id="contract:increment",
        function_id="function:increment",
        preconditions=(
            _clause(
                "clause:requires-positive",
                ContractClauseKind.PRECONDITION,
                "expr:positive",
            ),
        ),
        postconditions=(
            _clause(
                "clause:ensures-result",
                ContractClauseKind.POSTCONDITION,
                "expr:result",
            ),
        ),
        exceptional_postconditions=(
            _clause(
                "clause:signals-value-error",
                ContractClauseKind.EXCEPTIONAL_POSTCONDITION,
                "expr:positive",
                exception_type="ValueError",
            ),
        ),
        frame=FrameCondition(
            readable_symbol_ids=("symbol:x", "symbol:result"),
            writable_symbol_ids=("symbol:result",),
        ),
        effects=EffectSummary(
            reads=("symbol:x", "symbol:result"),
            writes=("symbol:result",),
            raises=("ValueError",),
        ),
        purity=Purity.IMPURE,
        undefined_behavior=(
            UndefinedBehaviorCondition(
                "ub:contract-overflow",
                "expr:positive",
                "Overflow traps instead of producing a mathematical integer.",
                UndefinedBehaviorConsequence.TRAP,
                **_prog_mapped(),
            ),
        ),
        **_prog_mapped(),
    )


def _hoare() -> HoareTriple:
    return HoareTriple(
        triple_id="hoare:increment",
        command_id="command:increment",
        precondition_ids=("expr:positive",),
        normal_postcondition_ids=("expr:result",),
        **_prog_mapped(),
    )


def _dynamic() -> DynamicLogicFormula:
    return DynamicLogicFormula(
        formula_id="dl:increment",
        modality=DynamicLogicModality.BOX,
        program_kind=DynamicProgramKind.COMMAND,
        program_ref_id="command:increment",
        postcondition_expression_id="expr:result",
        exit=DynamicLogicExit.NORMAL,
        **_prog_mapped(),
    )


def _program_document_payload() -> dict:
    program = _program()
    return {
        "program": program.to_dict(),
        "contracts": [_contract().to_dict()],
        "hoare_triples": [_hoare().to_dict()],
        "dynamic_formulas": [_dynamic().to_dict()],
        "family_id": "program",
        "binding_version": PROGRAM_V2_BINDING_VERSION,
        "state_version": PROGRAM_V2_STATE_VERSION,
    }


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert PROTOCOL_FRONTEND_V2_INTERFACE == "ProtocolFrontend@2"
    assert TAMARIN_FRONTEND_V2_INTERFACE == "TamarinFrontend@2"
    assert PROTOCOL_PROGRAM_FRONTEND_INTERFACE == "ProtocolProgramFrontend@2"
    assert PROGRAM_FRONTEND_V2_INTERFACE == "ProgramFrontend@2"
    assert VC_BRIDGE_V2_INTERFACE == "VerificationConditionBridge@2"
    assert PROTOCOL_V2_TASK_ID == "LFP2-014"
    assert PROGRAM_V2_TASK_ID == "LFP2-014"
    assert PROTOCOL_V2_GOAL_ID == "LFP2-G030"
    assert PROGRAM_V2_GOAL_ID == "LFP2-G030"
    assert PROTOCOL_V2_MODULE_VERSION == "2.0.0"
    assert PROGRAM_V2_MODULE_VERSION == "2.0.0"
    assert PROTOCOL_V2_NOTATION_ID == "symbolic_protocol"
    assert TAMARIN_V2_NOTATION_ID == "tamarin_spthy"
    assert PROGRAM_V2_NOTATION_ID == "canonical_program_logic"
    assert PROTOCOL_V2_PROFILE_ID == "applied_pi_controlled"
    assert TAMARIN_V2_PROFILE_ID == "multiset_rewriting_controlled"
    assert PROGRAM_V2_PROFILE_ID == "dynamic_hoare"
    assert PROTOCOL_V2_FAMILY_ID == "cryptographic_protocol"
    assert TAMARIN_V2_FAMILY_ID == "cryptographic_protocol"
    assert PROGRAM_V2_FAMILY_ID == "program"
    assert VC_VIEW_ROLE == "verification_condition"
    assert PROTOCOL_DEFAULT_LIMITS.parse_limits.max_input_bytes > 0
    assert PROGRAM_DEFAULT_LIMITS.parse_limits.max_input_bytes > 0

    protocol = ProtocolFrontendV2()
    assert protocol.interface == PROTOCOL_FRONTEND_V2_INTERFACE
    assert protocol.descriptor.descriptor_id == PROTOCOL_V2_DESCRIPTOR_ID

    tamarin = TamarinFrontendV2()
    assert tamarin.interface == TAMARIN_FRONTEND_V2_INTERFACE
    assert tamarin.descriptor.descriptor_id == TAMARIN_V2_DESCRIPTOR_ID

    program = ProgramFrontendV2()
    assert program.interface == PROGRAM_FRONTEND_V2_INTERFACE
    assert program.descriptor.descriptor_id == PROGRAM_V2_DESCRIPTOR_ID
    assert program.binding_version == PROGRAM_V2_BINDING_VERSION
    assert program.state_version == PROGRAM_V2_STATE_VERSION
    assert program.view_role == VC_VIEW_ROLE

    joint = ProtocolProgramFrontend()
    assert joint.interface == PROTOCOL_PROGRAM_FRONTEND_INTERFACE
    assert joint.descriptor.descriptor_id == PROTOCOL_PROGRAM_DESCRIPTOR_ID


# ---------------------------------------------------------------------------
# Descriptor / shared frontend conformance
# ---------------------------------------------------------------------------


def test_descriptors_declare_shared_artifacts_limits_diagnostics() -> None:
    for builder in (
        build_protocol_v2_descriptor,
        build_tamarin_v2_descriptor,
        build_program_v2_descriptor,
        build_protocol_program_descriptor,
    ):
        descriptor = builder()
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
        assert descriptor.fixtures


def test_frontends_register_under_shared_conformance() -> None:
    registry = SharedFrontendConformance()
    _, protocol_admitted = register_protocol_v2_frontend(registry)
    _, tamarin_admitted = register_tamarin_v2_frontend(registry)
    _, program_admitted = register_program_v2_frontend(registry)
    _, joint_admitted = register_protocol_program_frontend(registry)

    assert protocol_admitted.descriptor_id == PROTOCOL_V2_DESCRIPTOR_ID
    assert tamarin_admitted.descriptor_id == TAMARIN_V2_DESCRIPTOR_ID
    assert program_admitted.descriptor_id == PROGRAM_V2_DESCRIPTOR_ID
    assert joint_admitted.descriptor_id == PROTOCOL_PROGRAM_DESCRIPTOR_ID
    assert len(registry) == 4


# ---------------------------------------------------------------------------
# Happy-path: protocol / tamarin / program with typed artifacts
# ---------------------------------------------------------------------------


def test_parse_protocol_emits_parse_and_elaboration_artifacts() -> None:
    result = parse_protocol_v2(_protocol_document_payload())
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.parse_artifact, ParseArtifactV2)
    assert isinstance(result.elaboration_artifact, ElaborationArtifactV2)
    assert result.parse_artifact.interface == "ParseArtifact@2"
    assert result.elaboration_artifact.interface == "ElaborationArtifact@2"
    assert result.parse_artifact.status is ParseStatus.OK
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.OK
    assert result.typed_expression is not None
    assert result.document is not None
    assert len(result.document.process_nodes) == 1
    assert result.document.protocol.roles
    assert result.document.protocol.events
    assert result.document.protocol.equational_theories
    assert result.parse_artifact.metadata.get("raw_rules_admitted") is False
    assert result.parse_artifact.metadata.get("raw_target_source_admitted") is False
    assert result.parse_artifact.metadata.get("execution_admitted") is False
    assert result.raw_rules_admitted is False
    assert result.raw_target_source_admitted is False

    result.elaboration_artifact.validate_lineage(
        parse_artifact=result.parse_artifact,
        document=result.source_document,
    )
    assert result.parse_artifact.cst is not None
    assert result.parse_artifact.typed_roots
    assert result.elaboration_artifact.typed_expression is not None

    root = result.typed_expression.root
    assert root.extension is not None
    payload = dict(root.extension.payload)
    assert payload.get("raw_rules_admitted") is False
    assert payload.get("raw_target_source_admitted") is False
    assert payload.get("typed") is True
    assert payload.get("process_count") == 1
    assert "role:initiator" in payload.get("role_ids", [])


def test_parse_tamarin_emits_typed_rules_and_artifacts() -> None:
    result = parse_tamarin_v2(_tamarin_document_payload())
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.parse_artifact, ParseArtifactV2)
    assert isinstance(result.elaboration_artifact, ElaborationArtifactV2)
    assert result.document is not None
    assert len(result.document.rules) == 1
    assert result.document.rules[0].rule_id == "rule:send"
    assert len(result.document.lemmas) == 1
    assert result.parse_artifact.metadata.get("raw_rules_admitted") is False
    assert result.raw_rules_admitted is False

    root = result.typed_expression.root  # type: ignore[union-attr]
    assert root.extension is not None
    payload = dict(root.extension.payload)
    assert payload.get("raw_rules_admitted") is False
    assert "rule:send" in payload.get("rule_ids", [])
    assert any(
        child.extension is not None
        and dict(child.extension.payload).get("typed") is True
        for child in root.extension.children
    )


def test_parse_program_emits_hoare_contract_vc_view() -> None:
    result = parse_program_v2(_program_document_payload())
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.parse_artifact, ParseArtifactV2)
    assert isinstance(result.elaboration_artifact, ElaborationArtifactV2)
    doc = result.document
    assert doc is not None
    assert doc.family_id == "program"
    assert doc.binding_version == PROGRAM_V2_BINDING_VERSION
    assert doc.state_version == PROGRAM_V2_STATE_VERSION
    assert len(doc.contracts) == 1
    assert len(doc.hoare_triples) == 1
    assert len(doc.dynamic_formulas) == 1
    assert result.raw_assertions_admitted is False
    assert result.assertions_typed is True
    assert result.parse_artifact.metadata.get("raw_assertions_admitted") is False
    assert result.parse_artifact.metadata.get("view_role") == VC_VIEW_ROLE
    assert result.parse_artifact.metadata.get("family_id") == "program"

    root = result.typed_expression.root  # type: ignore[union-attr]
    assert root.extension is not None
    payload = dict(root.extension.payload)
    assert payload.get("raw_assertions_admitted") is False
    assert payload.get("family_id") == "program"
    assert VC_VIEW_ROLE in payload.get("view_roles", [])
    assert payload.get("binding_version") == PROGRAM_V2_BINDING_VERSION


def test_program_vc_lowering_from_typed_result() -> None:
    result = parse_program_v2(
        _program_document_payload(),
        lower_vc=True,
        function_id="function:increment",
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.vc_result is not None
    assert result.vc_result.family_id == "program"
    assert result.vc_result.view_role == VC_VIEW_ROLE
    assert result.vc_result.binding_version == PROGRAM_V2_BINDING_VERSION
    assert result.vc_result.state_version == PROGRAM_V2_STATE_VERSION
    assert result.vc_result.vc_sets

    # Also via explicit bridge on typed result.
    vc = lower_to_vc_v2(result, function_id="function:increment")
    assert vc.family_id == "program"
    assert vc.view_role == VC_VIEW_ROLE


def test_protocol_lower_proverif_requires_typed_path() -> None:
    result = parse_protocol_v2(_protocol_document_payload(), lower_proverif=True)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.controlled_source is not None
    assert result.controlled_source.source
    assert "process" in result.controlled_source.source or "out(" in result.controlled_source.source

    frontend = ProtocolFrontendV2()
    lowered = frontend.lower_to_proverif(result)
    assert lowered.source_digest


def test_tamarin_lower_requires_typed_path() -> None:
    result = parse_tamarin_v2(_tamarin_document_payload(), lower_tamarin=True)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.controlled_source is not None
    assert "rule" in result.controlled_source.source

    frontend = TamarinFrontendV2()
    lowered = frontend.lower_to_tamarin(result)
    assert lowered.source_digest


def test_print_round_trip_preserves_structure() -> None:
    protocol_result = parse_protocol_v2(_protocol_document_payload())
    assert protocol_result.ok and protocol_result.document is not None
    printed = print_protocol_v2(protocol_result.document)
    again = parse_protocol_v2(printed)
    assert again.ok and again.document is not None
    assert again.document.protocol.document_id == protocol_result.document.protocol.document_id

    tamarin_result = parse_tamarin_v2(_tamarin_document_payload())
    assert tamarin_result.ok and tamarin_result.document is not None
    tprinted = print_tamarin_v2(tamarin_result.document)
    tagain = parse_tamarin_v2(tprinted)
    assert tagain.ok and tagain.document is not None
    assert len(tagain.document.rules) == len(tamarin_result.document.rules)

    program_result = parse_program_v2(_program_document_payload())
    assert program_result.ok and program_result.document is not None
    pprinted = print_program_v2(program_result.document)
    pagain = parse_program_v2(pprinted)
    assert pagain.ok and pagain.document is not None
    assert pagain.document.program.program_id == program_result.document.program.program_id


# ---------------------------------------------------------------------------
# Fail-closed: unsupported constructs still emit artifacts
# ---------------------------------------------------------------------------


def test_unsupported_process_fails_with_artifacts() -> None:
    payload = _protocol_document_payload()
    payload["processes"] = {
        "role:initiator": {"kind": "phase", "children": []},
    }
    result = parse_protocol_v2(payload)
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_PROCESS for item in result.errors)
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED
    assert result.parse_artifact.metadata.get("execution_admitted") is False
    assert result.typed_expression is None


def test_unsupported_loop_fails_with_artifacts() -> None:
    payload = _program_document_payload()
    payload["loop_contracts"] = [
        {
            "loop_id": "loop:bad",
            "function_id": "function:increment",
            "header_block_id": "block:entry",
            "construct": "foreach",
            "invariants": [],
            "variants": [],
            "source_ref_ids": [PROG_SOURCE_ID],
            "span_ids": [PROG_SPAN_ID],
        }
    ]
    result = parse_program_v2(payload)
    assert not result.ok
    assert any(
        item.code in {CODE_UNSUPPORTED_LOOP, "program.invalid_loop"}
        for item in result.errors
    )
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED


def test_malformed_json_fails_closed() -> None:
    result = parse_protocol_v2("{not-json")
    assert not result.ok
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED

    result2 = parse_program_v2("")
    assert not result2.ok


# ---------------------------------------------------------------------------
# Acceptance: raw bypass blocked
# ---------------------------------------------------------------------------


def test_raw_protocol_rule_cannot_bypass_artifacts() -> None:
    frontend = ProtocolFrontendV2()
    with pytest.raises(ProtocolArtifactBypassError) as exc:
        frontend.admit_raw_protocol_rule("rule Send: [ ] --[]-> [ ]")
    assert exc.value.code == CODE_RAW_RULE

    tamarin = TamarinFrontendV2()
    with pytest.raises(ProtocolArtifactBypassError) as exc2:
        tamarin.admit_raw_protocol_rule("rule Foo: [ Fr(~x) ] --> [ Out(~x) ]")
    assert exc2.value.code == CODE_RAW_RULE

    joint = ProtocolProgramFrontend()
    with pytest.raises(ProtocolArtifactBypassError):
        joint.admit_raw_protocol_rule("raw")


def test_raw_target_source_cannot_bypass_artifacts() -> None:
    frontend = ProtocolFrontendV2()
    with pytest.raises(ProtocolArtifactBypassError) as exc:
        frontend.admit_raw_target_source("free c: channel.\nprocess 0")
    assert exc.value.code == CODE_RAW_TARGET_SOURCE

    # Lowering from a failed/empty result is blocked.
    failed = parse_protocol_v2("{not-json")
    with pytest.raises(ProtocolArtifactBypassError) as exc2:
        frontend.lower_to_proverif(failed)
    assert exc2.value.code == CODE_BYPASS_BLOCKED

    tamarin = TamarinFrontendV2()
    with pytest.raises(ProtocolArtifactBypassError):
        tamarin.admit_raw_target_source("theory Bad begin\nend")

    failed_t = parse_tamarin_v2("{bad")
    with pytest.raises(ProtocolArtifactBypassError):
        tamarin.lower_to_tamarin(failed_t)


def test_raw_program_assertion_cannot_bypass_artifacts() -> None:
    frontend = ProgramFrontendV2()
    with pytest.raises(ProgramArtifactBypassError) as exc:
        frontend.admit_raw_assertion("{x > 0} increment {result > 0}")
    assert exc.value.code == CODE_RAW_ASSERTION

    # VC without typed artifacts is blocked.
    failed = parse_program_v2("{not-json")
    with pytest.raises(ProgramArtifactBypassError) as exc2:
        frontend.lower_to_vc(failed)
    assert exc2.value.code == CODE_VC_WITHOUT_ARTIFACTS

    joint = ProtocolProgramFrontend()
    with pytest.raises(ProtocolArtifactBypassError):
        joint.admit_raw_program_assertion("assert true")


def test_execute_blocked_on_all_frontends() -> None:
    with pytest.raises(ProtocolArtifactBypassError):
        ProtocolFrontendV2().execute()
    with pytest.raises(ProtocolArtifactBypassError):
        TamarinFrontendV2().execute()
    with pytest.raises(ProgramArtifactBypassError):
        ProgramFrontendV2().execute()
    with pytest.raises(ProtocolArtifactBypassError):
        ProtocolProgramFrontend().execute()


def test_joint_facade_routes_and_blocks() -> None:
    joint = ProtocolProgramFrontend()
    p = joint.parse_protocol(_protocol_document_payload())
    assert p.ok
    t = joint.parse_tamarin(_tamarin_document_payload())
    assert t.ok
    g = joint.parse_program(_program_document_payload())
    assert g.ok
    assert g.has_typed_artifacts

    with pytest.raises(ProtocolArtifactBypassError):
        joint.admit_raw_target_source("raw.pv")
    with pytest.raises(ProtocolArtifactBypassError):
        joint.admit_raw_protocol_rule("raw rule")
    with pytest.raises(ProtocolArtifactBypassError):
        joint.admit_raw_program_assertion("raw assert")
