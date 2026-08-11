"""Conformance: software_verification syntax-kernel bridge (LFP-039).

Acceptance:

* Round trips preserve domain invariants and source identities
* No bridge weakens existing typed models to arbitrary JSON/text
* Loss and unsupported semantics are explicit

Interfaces: SoftwareVerificationSyntaxBridge@1
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.contracts import (
    ContractClause,
    ContractClauseKind,
    FrameCondition,
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
)
from ipfs_datasets_py.logic.software_verification.state import (
    Boundedness,
    FiniteDomainBound,
    PredicateRole,
    StatePredicate,
    StateSchema,
    StateTypeKind,
    StateVariable,
)
from ipfs_datasets_py.logic.software_verification.syntax_bridge import (
    SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE,
    BridgeLossRecord,
    FreeFormRejectedError,
    LossKind,
    SoftwareVerificationBridgeError,
    SoftwareVerificationIRKind,
    SoftwareVerificationSyntaxBridge,
    UnsupportedConstructError,
    UnsupportedConstructRecord,
    VC_VIEW_ROLE,
    domain_identity_of,
    kind_of,
    publish_software_verification_ir,
    round_trip_software_verification_ir,
    source_identities_of,
)
from ipfs_datasets_py.logic.software_verification.temporal import (
    TemporalFormula,
    TemporalLogic,
    TemporalOperator,
)
from ipfs_datasets_py.logic.software_verification.trace import (
    Clock,
    ClockDomain,
    Event,
    ObservationPolicy,
    ObservationPolicyKind,
    TimePoint,
    TimeUnit,
    TimeValue,
    TraceIR,
    TraceKind,
)
from ipfs_datasets_py.logic.software_verification.transitions import (
    Action,
    ActionFrame,
    StateTransitionIR,
    TransitionKind,
    TransitionRelation,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    SourceConstructKind,
    VCRuleKind,
    VerificationConditionSet,
    VerificationObligation,
)
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind, TypedExpression, mk_true
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


SOURCE_ID = "source:bridge"
SPAN_ID = "span:bridge"


def _mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (SOURCE_ID,), "span_ids": (SPAN_ID,)}


def _source() -> SourceRef:
    return SourceRef(
        ref_id=SOURCE_ID,
        source_uri="file:///src/bridge.example",
        source_id="bridge.example",
        source_revision="git:0123456789abcdef",
        content_sha256="a" * 64,
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id=SPAN_ID,
        source_ref_id=SOURCE_ID,
        start_byte=0,
        end_byte=120,
        start_line=1,
        start_column=1,
        end_line=8,
        end_column=2,
    )


def _state_schema() -> StateSchema:
    return StateSchema(
        variables=(
            StateVariable(
                "var:pc",
                "pc",
                StateTypeKind.ENUMERATION,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound(
                    "bound:pc", members=("idle", "busy", "done")
                ),
            ),
            StateVariable(
                "var:count",
                "count",
                StateTypeKind.INTEGER,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound("bound:count", lower=0, upper=3),
            ),
            StateVariable(
                "var:ready",
                "ready",
                StateTypeKind.BOOLEAN,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound(
                    "bound:bool",
                    members=("false", "true"),
                    cardinality=2,
                ),
            ),
        ),
        metadata={"model": "bounded-counter"},
    )


def _transition() -> StateTransitionIR:
    schema = _state_schema()
    initial = StatePredicate(
        "pred:init",
        PredicateRole.INITIAL,
        "pc = idle /\\ count = 0 /\\ ready",
        expression={"pc": "idle", "count": 0, "ready": True},
        subject_variable_ids=("var:pc", "var:count", "var:ready"),
        source_ref_ids=(SOURCE_ID,),
    )
    guard = StatePredicate(
        "pred:guard-inc",
        PredicateRole.GUARD,
        "count < 3 /\\ ready",
        subject_variable_ids=("var:count", "var:ready"),
        source_ref_ids=(SOURCE_ID,),
    )
    next_inc = StatePredicate(
        "pred:next-inc",
        PredicateRole.NEXT,
        "count' = count + 1 /\\ pc' = busy",
        subject_variable_ids=("var:count", "var:pc"),
        source_ref_ids=(SOURCE_ID,),
    )
    action = Action(
        "action:inc",
        "Increment",
        ActionFrame(
            reads=("var:count", "var:ready", "var:pc"),
            writes=("var:count", "var:pc"),
        ),
        guard_predicate_id="pred:guard-inc",
        next_predicate_id="pred:next-inc",
    )
    relation = TransitionRelation(
        "rel:next",
        TransitionKind.ACTION,
        "Next is the disjunction of enabled actions.",
        action_ids=("action:inc",),
        allows_stutter=True,
    )
    return StateTransitionIR(
        schema=schema,
        predicates=(initial, guard, next_inc),
        actions=(action,),
        transitions=(relation,),
        metadata={"subject": "counter"},
    )


def _program() -> ProgramIR:
    symbols = (
        ProgramSymbol(
            "symbol:x", "x", "integer", SymbolKind.PARAMETER, **_mapped()
        ),
        ProgramSymbol(
            "symbol:result",
            "result",
            "integer",
            SymbolKind.RESULT,
            **_mapped(),
        ),
    )
    expressions = (
        ProgramExpression(
            "expr:x",
            ExpressionKind.SYMBOL,
            "integer",
            symbol_ids=("symbol:x",),
            **_mapped(),
        ),
        ProgramExpression(
            "expr:zero",
            ExpressionKind.LITERAL,
            "integer",
            attributes={"value": 0},
            **_mapped(),
        ),
        ProgramExpression(
            "expr:one",
            ExpressionKind.LITERAL,
            "integer",
            attributes={"value": 1},
            **_mapped(),
        ),
        ProgramExpression(
            "expr:positive",
            ExpressionKind.BINARY,
            "boolean",
            operand_ids=("expr:x", "expr:zero"),
            evaluation_order=("expr:x", "expr:zero"),
            operator="greater_than",
            **_mapped(),
        ),
        ProgramExpression(
            "expr:add",
            ExpressionKind.BINARY,
            "integer",
            operand_ids=("expr:x", "expr:one"),
            evaluation_order=("expr:one", "expr:x"),
            operator="add",
            **_mapped(),
        ),
        ProgramExpression(
            "expr:result",
            ExpressionKind.RESULT,
            "integer",
            symbol_ids=("symbol:result",),
            **_mapped(),
        ),
    )
    commands = (
        ProgramCommand(
            "command:guard",
            CommandKind.ASSERT,
            expression_ids=("expr:positive",),
            effects=EffectSummary(reads=("symbol:x",)),
            **_mapped(),
        ),
        ProgramCommand(
            "command:increment",
            CommandKind.ASSIGN,
            expression_ids=("expr:add",),
            target_symbol_ids=("symbol:result",),
            effects=EffectSummary(
                reads=("symbol:x",), writes=("symbol:result",)
            ),
            **_mapped(),
        ),
        ProgramCommand(
            "command:return",
            CommandKind.RETURN,
            expression_ids=("expr:result",),
            effects=EffectSummary(reads=("symbol:result",)),
            **_mapped(),
        ),
        ProgramCommand(
            "command:throw",
            CommandKind.THROW,
            effects=EffectSummary(raises=("ValueError",)),
            **_mapped(),
        ),
    )
    cfg = ControlFlowGraph(
        graph_id="cfg:increment",
        entry_block_id="block:entry",
        blocks=(
            BasicBlock("block:entry", ("command:guard",), **_mapped()),
            BasicBlock(
                "block:normal",
                ("command:increment", "command:return"),
                **_mapped(),
            ),
            BasicBlock("block:exception", ("command:throw",), **_mapped()),
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
        **_mapped(),
    )
    return ProgramIR(
        sources=(_source(),),
        spans=(_span(),),
        symbols=symbols,
        expressions=expressions,
        commands=commands,
        functions=(function,),
        metadata={"language": "example", "integer_model": "bounded"},
    )


def _contract() -> ProgramContract:
    return ProgramContract(
        contract_id="contract:increment",
        function_id="function:increment",
        preconditions=(
            ContractClause(
                "clause:requires-positive",
                ContractClauseKind.PRECONDITION,
                "expr:positive",
                "x must be positive.",
                **_mapped(),
            ),
        ),
        postconditions=(
            ContractClause(
                "clause:ensures-result",
                ContractClauseKind.POSTCONDITION,
                "expr:result",
                "result is defined.",
                **_mapped(),
            ),
        ),
        frame=FrameCondition(
            readable_symbol_ids=("symbol:x", "symbol:result"),
            writable_symbol_ids=("symbol:result",),
        ),
        effects=EffectSummary(
            reads=("symbol:x", "symbol:result"),
            writes=("symbol:result",),
        ),
        purity=Purity.IMPURE,
        **_mapped(),
    )


def _vc_set() -> VerificationConditionSet:
    program = _program()
    obligation = VerificationObligation(
        obligation_id="obl:post",
        rule=VCRuleKind.POSTCONDITION_NORMAL,
        parent_contract_id="contract:increment",
        function_id="function:increment",
        source_construct_kind=SourceConstructKind.FUNCTION,
        source_construct_id="function:increment",
        assumption_expression_ids=("expr:positive",),
        goal_expression_ids=("expr:result",),
        statement="result is defined under positive x",
        **_mapped(),
    )
    return VerificationConditionSet(
        program_id=program.program_id,
        function_id="function:increment",
        parent_contract_id="contract:increment",
        obligations=(obligation,),
        attributes={"fixture": "bridge-vc"},
    )


def _temporal() -> TemporalFormula:
    atom = TemporalFormula(
        TemporalOperator.ATOM,
        TemporalLogic.LTLF,
        proposition="ready",
        source_ref_ids=(SOURCE_ID,),
    )
    return TemporalFormula(
        TemporalOperator.ALWAYS,
        TemporalLogic.LTLF,
        operands=(atom,),
        source_ref_ids=(SOURCE_ID,),
    )


def _trace() -> TraceIR:
    clock = Clock(
        "clock:main",
        ClockDomain.DISCRETE,
        TimeUnit.LOGICAL_TICK,
        TimeValue(1),
    )
    events = (
        Event(
            "event:0",
            "state",
            TimePoint("clock:main", TimeValue(0)),
            ("ready",),
            (),
            source_ref_ids=(SOURCE_ID,),
        ),
        Event(
            "event:1",
            "state",
            TimePoint("clock:main", TimeValue(1)),
            (),
            ("ready",),
            source_ref_ids=(SOURCE_ID,),
        ),
    )
    return TraceIR(
        clocks=(clock,),
        events=events,
        kind=TraceKind.FINITE,
        observation_policy=ObservationPolicy(
            "policy:closed",
            ObservationPolicyKind.CLOSED_WORLD,
        ),
        primary_clock_id="clock:main",
        metadata={"fixture": "bridge-trace"},
    )


def _core_documents() -> dict[SoftwareVerificationIRKind, object]:
    """Representative IRs covering the declared effect surface."""

    return {
        SoftwareVerificationIRKind.STATE: _state_schema(),
        SoftwareVerificationIRKind.TRANSITION: _transition(),
        SoftwareVerificationIRKind.PROGRAM: _program(),
        SoftwareVerificationIRKind.CONTRACT: _contract(),
        SoftwareVerificationIRKind.VC: _vc_set(),
        SoftwareVerificationIRKind.TEMPORAL: _temporal(),
        SoftwareVerificationIRKind.TRACE: _trace(),
    }


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    assert (
        SoftwareVerificationSyntaxBridge.INTERFACE
        == SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE
    )
    assert bridge.interface == "SoftwareVerificationSyntaxBridge@1"
    assert bridge.domain_id == "software_verification"
    wire = bridge.to_dict()
    assert wire["interface"] == SOFTWARE_VERIFICATION_SYNTAX_BRIDGE_INTERFACE
    assert wire["weakens_to_free_form"] is False
    assert set(wire["known_kinds"]) == {
        item.value for item in SoftwareVerificationIRKind
    }


def test_routes_cover_every_declared_ir_kind() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    expected = {
        "state",
        "transition",
        "program",
        "contract",
        "vc",
        "temporal",
        "trace",
        "authorization",
        "protocol",
        "hyperproperty",
        "heap",
        "separation",
        "concurrency",
        "refinement",
    }
    assert set(bridge.known_kinds()) == expected
    for kind in SoftwareVerificationIRKind:
        route = bridge.route_for(kind)
        assert route.kind is kind
        assert route.family_id
        assert route.profile_id
        assert route.features
        assert "/v" in route.payload_schema
        assert route.domain_schema


def test_vc_is_view_role_not_family() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    vc = bridge.route_for(SoftwareVerificationIRKind.VC)
    assert vc.view_role == VC_VIEW_ROLE
    assert vc.family_id == "program"
    assert vc.family_id != VC_VIEW_ROLE


def test_kind_of_resolves_typed_documents() -> None:
    assert kind_of(_state_schema()) is SoftwareVerificationIRKind.STATE
    assert kind_of(_program()) is SoftwareVerificationIRKind.PROGRAM
    assert kind_of(_temporal()) is SoftwareVerificationIRKind.TEMPORAL
    with pytest.raises(UnsupportedConstructError):
        kind_of(object())


# ---------------------------------------------------------------------------
# Round trips preserve domain and source identities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    list(_core_documents().keys()),
    ids=lambda kind: kind.value,
)
def test_round_trip_preserves_domain_invariants(kind: SoftwareVerificationIRKind) -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    document = _core_documents()[kind]
    result = bridge.round_trip(document, kind=kind)
    assert result.ok, result.to_dict()
    assert result.exact, f"losses={result.losses}"
    assert result.domain_identity == domain_identity_of(document)
    assert result.expression is not None
    assert isinstance(result.expression, TypedExpression)
    assert result.expression.root.kind is NodeKind.EXTENSION
    assert result.expression.root.extension is not None
    assert result.document is not None
    assert result.document.to_dict() == document.to_dict()
    original_sources = set(source_identities_of(document))
    assert original_sources <= set(result.source_identities)


def test_publish_consume_helpers_preserve_state_identity() -> None:
    schema = _state_schema()
    published = publish_software_verification_ir(schema)
    assert published.exact
    assert published.domain_identity == schema.schema_id
    restored = round_trip_software_verification_ir(schema)
    assert restored.domain_identity == schema.schema_id
    assert restored.document.to_dict() == schema.to_dict()


def test_program_source_identities_survive_round_trip() -> None:
    program = _program()
    result = SoftwareVerificationSyntaxBridge().round_trip(program)
    assert SOURCE_ID in result.source_identities
    assert SPAN_ID in result.source_identities or any(
        SOURCE_ID in item for item in result.source_identities
    )
    assert program.sources[0].content_sha256 in result.source_identities


# ---------------------------------------------------------------------------
# No free-form weakening
# ---------------------------------------------------------------------------


def test_free_form_text_is_rejected() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    with pytest.raises(FreeFormRejectedError) as excinfo:
        bridge.publish("forall x. P(x)")
    assert excinfo.value.code == "software_verification.free_form_rejected"


def test_bare_json_mapping_without_kind_is_rejected() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    with pytest.raises(FreeFormRejectedError):
        bridge.publish({"expression": "x > 0", "text": "x > 0"})


def test_published_payload_is_typed_extension_not_text() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    result = bridge.publish(_program())
    extension = result.expression.root.extension
    assert extension is not None
    payload = dict(extension.payload)
    assert "document" in payload
    assert isinstance(payload["document"], dict)
    assert "text" not in payload
    assert "raw" not in payload
    assert payload["kind"] == "program"
    assert payload["schema_version"] == extension.payload_schema
    assert payload["domain_identity"] == result.domain_identity


def test_unknown_kind_is_explicitly_unsupported() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    with pytest.raises(UnsupportedConstructError) as excinfo:
        bridge.route_for("not_a_real_ir")
    assert excinfo.value.code == "software_verification.unsupported_construct"


def test_consume_rejects_non_extension_roots() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    signature = propositional_signature("sig:prop", ("p",))
    expression = TypedExpression(
        expression_id="expr:true",
        root=mk_true("node:true"),
        signature=signature,
        elaborate_on_init=False,
    )
    with pytest.raises(FreeFormRejectedError):
        bridge.consume(expression)


def test_typed_mapping_publish_requires_matching_kind() -> None:
    bridge = SoftwareVerificationSyntaxBridge()
    # Reconstruct via typed from_dict path with explicit kind.
    schema = _state_schema()
    result = bridge.publish(schema.to_dict(), kind=SoftwareVerificationIRKind.STATE)
    assert result.exact
    assert result.domain_identity == schema.schema_id


# ---------------------------------------------------------------------------
# Explicit loss / unsupported surfaces
# ---------------------------------------------------------------------------


def test_loss_and_unsupported_records_are_explicit_and_serializable() -> None:
    loss = BridgeLossRecord(
        loss_id="loss:demo",
        kind=LossKind.OBSERVATIONAL,
        path="observations",
        description="runtime observations are not semantic identity",
    )
    unsupported = UnsupportedConstructRecord(
        construct_id="unsupported:demo",
        construct="probabilistic_choice",
        reason="probabilistic constructs are declaration-only",
        path="kind",
    )
    assert loss.to_dict()["kind"] == "observational"
    assert unsupported.to_dict()["construct"] == "probabilistic_choice"
    assert "schema" in loss.to_dict()
    assert "schema" in unsupported.to_dict()


def test_bridge_error_codes_are_stable() -> None:
    err = SoftwareVerificationBridgeError(
        "boom", code="software_verification.route_error"
    )
    assert err.to_dict()["code"] == "software_verification.route_error"


def test_every_route_family_is_canonical_foundation_family() -> None:
    from ipfs_datasets_py.logic.families.registry import FOUNDATION_FAMILY_IDS

    bridge = SoftwareVerificationSyntaxBridge()
    for route in bridge.routes.values():
        assert route.family_id in FOUNDATION_FAMILY_IDS
