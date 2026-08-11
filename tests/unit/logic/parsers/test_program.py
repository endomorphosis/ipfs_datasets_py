"""Unit tests for ProgramLogicSyntax@1 and VerificationConditionBridge@1 (LFP-031).

Evidence subset:

* hoare, contract, dynamic logic, wp, sp, invariant, modifies
* vc, source maps, lowering

Acceptance:

* Binding and state versions are explicit
* Unsupported effects/loops produce obligations rather than assumptions
* VC is never emitted as a semantic family ID
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.parsers.program import (
    CODE_FAMILY_NAMESPACE,
    CODE_UNSUPPORTED_LOOP,
    CODE_VERSION_MISMATCH,
    DYNAMIC_LOGIC_PROFILE_ID,
    PROGRAM_LOGIC_BINDING_VERSION,
    PROGRAM_LOGIC_FAMILY_ID,
    PROGRAM_LOGIC_STATE_VERSION,
    PROGRAM_LOGIC_SYNTAX_INTERFACE,
    UNSUPPORTED_LOOP_CONSTRUCTS,
    VC_VIEW_ROLE,
    VERIFICATION_CONDITION_BRIDGE_INTERFACE,
    FrameCondition,
    ProgramLogicDocument,
    ProgramLogicError,
    ProgramLogicSyntax,
    SourceMapBinding,
    StrongestPostcondition,
    SurfaceForm,
    SurfaceKind,
    VerificationConditionBridge,
    VerificationConditionBridgeError,
    VerificationConditionBridgeResult,
    lower_to_verification_conditions,
    parse_dynamic_surface,
    parse_hoare_surface,
    parse_program_logic,
    program_logic_namespace,
)
from ipfs_datasets_py.logic.software_verification.contracts import (
    ContractClause,
    ContractClauseKind,
    DynamicLogicExit,
    DynamicLogicFormula,
    DynamicLogicModality,
    DynamicProgramKind,
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
from ipfs_datasets_py.logic.software_verification.vc import (
    LoopVariantPolicy,
    SourceConstructKind,
    UnsupportedEffectKind,
    VCRuleKind,
)

SOURCE_ID = "source:counter"
SPAN_ID = "span:counter"


def _source() -> SourceRef:
    return SourceRef(
        ref_id=SOURCE_ID,
        source_uri="file:///src/counter.example",
        source_id="counter.example",
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


def _mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (SOURCE_ID,), "span_ids": (SPAN_ID,)}


def _program() -> ProgramIR:
    symbols = (
        ProgramSymbol(
            "symbol:x",
            "x",
            "integer",
            SymbolKind.PARAMETER,
            **_mapped(),
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
    undefined = UndefinedBehaviorCondition(
        "ub:overflow",
        "expr:positive",
        "The source language traps when its bounded integer overflows.",
        UndefinedBehaviorConsequence.TRAP,
        **_mapped(),
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
            effects=EffectSummary(reads=("symbol:x",), writes=("symbol:result",)),
            undefined_behavior=(undefined,),
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
        **_mapped(),
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
                **_mapped(),
            ),
        ),
        **_mapped(),
    )


def _loop_contract(*, total: bool = True) -> LoopContract:
    return LoopContract(
        loop_id="loop:entry",
        function_id="function:increment",
        header_block_id="block:entry",
        invariants=(
            _clause(
                "clause:loop-invariant",
                ContractClauseKind.LOOP_INVARIANT,
                "expr:positive",
            ),
        ),
        variants=(
            _clause(
                "clause:loop-variant",
                ContractClauseKind.LOOP_VARIANT,
                "expr:x",
            ),
        )
        if total
        else (),
        total_correctness=total,
        **_mapped(),
    )


def _hoare() -> HoareTriple:
    return HoareTriple(
        triple_id="hoare:increment",
        command_id="command:increment",
        precondition_ids=("expr:positive",),
        normal_postcondition_ids=("expr:result",),
        **_mapped(),
    )


def _dynamic(*, modality: DynamicLogicModality = DynamicLogicModality.BOX) -> DynamicLogicFormula:
    return DynamicLogicFormula(
        formula_id="dl:increment",
        modality=modality,
        program_kind=DynamicProgramKind.COMMAND,
        program_ref_id="command:increment",
        postcondition_expression_id="expr:result",
        exit=DynamicLogicExit.NORMAL,
        **_mapped(),
    )


def _document(
    *,
    program: ProgramIR | None = None,
    contract: ProgramContract | None = None,
    loops: tuple[LoopContract, ...] = (),
    hoare: tuple[HoareTriple, ...] = (),
    dynamic: tuple[DynamicLogicFormula, ...] = (),
    surfaces: tuple[SurfaceForm, ...] = (),
) -> ProgramLogicDocument:
    return ProgramLogicDocument(
        program=program or _program(),
        contracts=(contract or _contract(),),
        loop_contracts=loops,
        hoare_triples=hoare or (_hoare(),),
        dynamic_formulas=dynamic or (_dynamic(),),
        surfaces=surfaces,
        source_maps=(
            SourceMapBinding(
                owner_id="contract:increment",
                source_ref_ids=(SOURCE_ID,),
                span_ids=(SPAN_ID,),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Interface identity and namespace
# ---------------------------------------------------------------------------


def test_interface_and_namespace_identity() -> None:
    assert PROGRAM_LOGIC_SYNTAX_INTERFACE == "ProgramLogicSyntax@1"
    assert VERIFICATION_CONDITION_BRIDGE_INTERFACE == "VerificationConditionBridge@1"
    assert PROGRAM_LOGIC_FAMILY_ID == "program"
    assert VC_VIEW_ROLE == "verification_condition"
    assert DYNAMIC_LOGIC_PROFILE_ID == "dynamic_logic"
    assert PROGRAM_LOGIC_BINDING_VERSION == "program-binding/v1"
    assert PROGRAM_LOGIC_STATE_VERSION == "program-state/v1"

    syntax = ProgramLogicSyntax()
    assert syntax.interface == PROGRAM_LOGIC_SYNTAX_INTERFACE
    assert syntax.family_id == "program"
    assert syntax.binding_version == PROGRAM_LOGIC_BINDING_VERSION
    assert syntax.state_version == PROGRAM_LOGIC_STATE_VERSION
    assert isinstance(syntax.vc_bridge, VerificationConditionBridge)
    assert syntax.vc_bridge.view_role == VC_VIEW_ROLE
    assert syntax.vc_bridge.family_id == "program"

    ns = program_logic_namespace()
    assert ns["family_id"] == "program"
    assert ns["view_role"] == "verification_condition"
    assert ns["binding_version"] == PROGRAM_LOGIC_BINDING_VERSION
    assert ns["state_version"] == PROGRAM_LOGIC_STATE_VERSION
    assert "verification_condition" not in {
        ns["family_id"],
        ns.get("dynamic_logic_profile", ""),
    }


def test_vc_never_emitted_as_semantic_family_id() -> None:
    doc = _document()
    payload = doc.semantic_dict()
    assert payload["family_id"] == "program"
    assert payload["view_roles"] == ["verification_condition"]
    assert payload["family_id"] != "verification_condition"
    assert payload["family_id"] != "vc"

    with pytest.raises(ProgramLogicError) as excinfo:
        ProgramLogicDocument(
            program=_program(),
            contracts=(_contract(),),
            family_id="verification_condition",
        )
    assert excinfo.value.code == CODE_FAMILY_NAMESPACE

    with pytest.raises(ProgramLogicError) as excinfo:
        ProgramLogicDocument.from_dict(
            {
                "program": _program().to_dict(),
                "contracts": [_contract().to_dict()],
                "family_id": "vc",
            }
        )
    assert excinfo.value.code == CODE_FAMILY_NAMESPACE

    result = lower_to_verification_conditions(doc)
    assert result.family_id == "program"
    assert result.view_role == "verification_condition"
    wire = result.to_dict()
    assert wire["family_id"] == "program"
    assert wire["view_role"] == "verification_condition"
    assert wire["family_id"] != wire["view_role"]


# ---------------------------------------------------------------------------
# Binding and state versions are explicit
# ---------------------------------------------------------------------------


def test_binding_and_state_versions_are_explicit_on_document() -> None:
    doc = _document()
    assert doc.binding_version == PROGRAM_LOGIC_BINDING_VERSION
    assert doc.state_version == PROGRAM_LOGIC_STATE_VERSION
    semantic = doc.semantic_dict()
    assert semantic["binding_version"] == PROGRAM_LOGIC_BINDING_VERSION
    assert semantic["state_version"] == PROGRAM_LOGIC_STATE_VERSION
    assert "binding_version" in doc.to_dict()
    assert "state_version" in doc.to_dict()

    with pytest.raises(ProgramLogicError) as excinfo:
        ProgramLogicDocument(
            program=_program(),
            contracts=(_contract(),),
            binding_version="program-binding/v0",
        )
    assert excinfo.value.code == CODE_VERSION_MISMATCH

    with pytest.raises(ProgramLogicError) as excinfo:
        ProgramLogicDocument(
            program=_program(),
            contracts=(_contract(),),
            state_version="program-state/v0",
        )
    assert excinfo.value.code == CODE_VERSION_MISMATCH


def test_binding_and_state_versions_propagate_through_vc_bridge() -> None:
    doc = _document()
    result = VerificationConditionBridge().lower(doc)
    assert result.binding_version == doc.binding_version
    assert result.state_version == doc.state_version
    assert result.binding_version == PROGRAM_LOGIC_BINDING_VERSION
    assert result.state_version == PROGRAM_LOGIC_STATE_VERSION
    wire = result.to_dict()
    assert wire["binding_version"] == PROGRAM_LOGIC_BINDING_VERSION
    assert wire["state_version"] == PROGRAM_LOGIC_STATE_VERSION
    restored = VerificationConditionBridgeResult.from_dict(wire)
    assert restored.binding_version == result.binding_version
    assert restored.state_version == result.state_version
    assert restored.family_id == "program"
    assert restored.view_role == "verification_condition"


# ---------------------------------------------------------------------------
# Document parse / print / identity
# ---------------------------------------------------------------------------


def test_document_round_trip_json_and_identity() -> None:
    doc = _document(loops=(_loop_contract(),))
    restored = ProgramLogicDocument.from_json(doc.to_json())
    assert restored.document_id == doc.document_id
    assert restored.semantic_dict() == doc.semantic_dict()
    assert restored.contracts[0].contract_id == "contract:increment"
    assert restored.hoare_triples[0].triple_id == "hoare:increment"
    assert restored.dynamic_formulas[0].modality is DynamicLogicModality.BOX
    assert restored.loop_contracts[0].loop_id == "loop:entry"

    via_mapping = parse_program_logic(doc.to_dict())
    assert via_mapping.document_id == doc.document_id

    via_ir = parse_program_logic(
        _program(),
        contracts=(_contract(),),
        hoare_triples=(_hoare(),),
        dynamic_formulas=(_dynamic(),),
    )
    assert via_ir.program.program_id == _program().program_id
    assert via_ir.family_id == "program"


def test_document_validates_contracts_and_hoare_against_program() -> None:
    with pytest.raises(ProgramLogicError):
        ProgramLogicDocument(
            program=_program(),
            contracts=(
                replace(
                    _contract(),
                    function_id="function:missing",
                ),
            ),
        )


def test_source_maps_are_explicit() -> None:
    doc = _document()
    assert doc.source_maps
    assert doc.source_maps[0].owner_id == "contract:increment"
    assert SOURCE_ID in doc.source_maps[0].source_ref_ids
    assert SPAN_ID in doc.source_maps[0].span_ids
    assert doc.semantic_dict()["source_maps"]

    with pytest.raises(ProgramLogicError):
        SourceMapBinding(owner_id="orphan", source_ref_ids=(), span_ids=())


# ---------------------------------------------------------------------------
# Hoare, contract, dynamic logic, modifies surfaces
# ---------------------------------------------------------------------------


def test_hoare_surface_parse_elaborate_and_print() -> None:
    surface = parse_hoare_surface(
        "{x > 0} command:increment {result}",
        form_id="surface:hoare-inc",
        precondition_expression_id="expr:positive",
        postcondition_expression_id="expr:result",
        command_id="command:increment",
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    assert surface.kind is SurfaceKind.HOARE
    triple = surface.elaborate_hoare()
    assert triple.command_id == "command:increment"
    assert triple.precondition_ids == ("expr:positive",)
    assert triple.normal_postcondition_ids == ("expr:result",)
    triple.validate_against(_program())

    syntax = ProgramLogicSyntax()
    printed = syntax.print_hoare(triple)
    assert printed.startswith("{")
    assert "command:increment" in printed
    assert printed.endswith("}")

    doc = _document(surfaces=(surface,), hoare=(triple,))
    assert doc.surfaces[0].form_id == "surface:hoare-inc"


def test_dynamic_logic_surface_box_and_diamond() -> None:
    box = parse_dynamic_surface(
        "[command:increment]expr:result",
        form_id="surface:box",
        postcondition_expression_id="expr:result",
        program_ref_id="command:increment",
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    diamond = parse_dynamic_surface(
        "<command:increment>expr:result",
        form_id="surface:diamond",
        postcondition_expression_id="expr:result",
        program_ref_id="command:increment",
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    assert box.kind is SurfaceKind.DYNAMIC_BOX
    assert diamond.kind is SurfaceKind.DYNAMIC_DIAMOND
    box_f = box.elaborate_dynamic()
    diamond_f = diamond.elaborate_dynamic()
    assert box_f.modality is DynamicLogicModality.BOX
    assert diamond_f.modality is DynamicLogicModality.DIAMOND
    box_f.validate_against(_program())
    diamond_f.validate_against(_program())

    syntax = ProgramLogicSyntax()
    assert syntax.print_dynamic(box_f).startswith("[")
    assert syntax.print_dynamic(diamond_f).startswith("<")


def test_modifies_clause_and_contract_clause_surfaces() -> None:
    modifies = SurfaceForm(
        form_id="surface:modifies",
        kind=SurfaceKind.MODIFIES,
        text="modifies symbol:result",
        symbol_ids=("symbol:result",),
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    frame = modifies.elaborate_frame()
    assert frame.writable_symbol_ids == ("symbol:result",)
    assert ProgramLogicSyntax().print_modifies(frame) == "modifies symbol:result"
    assert ProgramLogicSyntax().print_modifies(
        FrameCondition(allows_all_writes=True)
    ) == "modifies *"
    assert ProgramLogicSyntax().print_modifies(FrameCondition()) == "modifies \\nothing"

    requires = SurfaceForm(
        form_id="surface:requires",
        kind=SurfaceKind.REQUIRES,
        text="requires x > 0",
        precondition_expression_id="expr:positive",
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    clause = requires.elaborate_clause()
    assert clause.kind is ContractClauseKind.PRECONDITION
    assert clause.expression_id == "expr:positive"

    invariant = SurfaceForm(
        form_id="surface:inv",
        kind=SurfaceKind.INVARIANT,
        text="invariant x > 0",
        postcondition_expression_id="expr:positive",
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    inv_clause = invariant.elaborate_clause()
    assert inv_clause.kind is ContractClauseKind.LOOP_INVARIANT


def test_malformed_surface_forms_fail_closed() -> None:
    with pytest.raises(ProgramLogicError):
        parse_hoare_surface(
            "not a triple",
            form_id="bad",
            precondition_expression_id="expr:positive",
            postcondition_expression_id="expr:result",
            command_id="command:increment",
            source_ref_ids=(SOURCE_ID,),
        )
    with pytest.raises(ProgramLogicError):
        parse_dynamic_surface(
            "box alpha P",
            form_id="bad",
            postcondition_expression_id="expr:result",
            program_ref_id="command:increment",
            source_ref_ids=(SOURCE_ID,),
        )


# ---------------------------------------------------------------------------
# WP / SP / VC lowering
# ---------------------------------------------------------------------------


def test_vc_bridge_lowers_wp_sp_invariant_and_source_maps() -> None:
    doc = _document(loops=(_loop_contract(total=True),))
    result = ProgramLogicSyntax(
        loop_variant_policy=LoopVariantPolicy.REQUIRED
    ).lower_to_vc(doc)

    assert result.interface == VERIFICATION_CONDITION_BRIDGE_INTERFACE
    assert len(result.vc_sets) == 1
    vc_set = result.vc_sets[0]
    assert vc_set.parent_contract_id == "contract:increment"
    assert vc_set.weakest_preconditions
    assert result.strongest_postconditions
    assert len(result.strongest_postconditions) == len(vc_set.weakest_preconditions)

    # WP dualizes to SP (matched via dual_of attribute, not sort order).
    wp_by_id = {item.wp_id: item for item in vc_set.weakest_preconditions}
    for sp in result.strongest_postconditions:
        assert isinstance(sp, StrongestPostcondition)
        dual = sp.attributes.to_dict().get("dual_of")
        assert dual in wp_by_id
        wp = wp_by_id[dual]
        assert sp.function_id == wp.function_id
        assert sp.program_point_id == wp.program_point_id
        assert sp.precondition_expression_ids == wp.assumption_expression_ids
        assert sp.postcondition_expression_ids == wp.consequent_expression_ids

    # Loop invariant / variant obligations present.
    assert vc_set.obligations_by_rule(VCRuleKind.LOOP_INVARIANT_INIT)
    assert vc_set.obligations_by_rule(VCRuleKind.LOOP_INVARIANT_PRESERVE)
    assert vc_set.obligations_by_rule(VCRuleKind.LOOP_VARIANT_DECREASE)

    # Frame / modifies coverage.
    assert vc_set.obligations_by_rule(VCRuleKind.FRAME)
    assert vc_set.frame_construct_ids()

    # Source maps on every obligation.
    for obligation in vc_set.obligations:
        assert obligation.source_ref_ids or obligation.span_ids
        assert obligation.parent_contract_id == "contract:increment"

    # Family remains program; view role is VC.
    assert result.family_id == "program"
    assert result.view_role == "verification_condition"


def test_hoare_and_dynamic_remain_distinct_typed_concepts() -> None:
    doc = _document(
        hoare=(_hoare(),),
        dynamic=(_dynamic(modality=DynamicLogicModality.DIAMOND),),
    )
    assert doc.hoare_triples[0].triple_id == "hoare:increment"
    assert doc.dynamic_formulas[0].modality is DynamicLogicModality.DIAMOND
    semantic = doc.semantic_dict()
    assert "hoare_triples" in semantic
    assert "dynamic_formulas" in semantic
    assert semantic["hoare_triples"][0]["command_id"] == "command:increment"
    assert semantic["dynamic_formulas"][0]["modality"] == "diamond"
    # Profile may be dynamic_hoare; family stays program.
    assert semantic["profile_id"] == "dynamic_hoare"
    assert semantic["family_id"] == "program"


# ---------------------------------------------------------------------------
# Unsupported effects / loops → obligations, not assumptions
# ---------------------------------------------------------------------------


def test_unsupported_effects_produce_obligations_not_assumptions() -> None:
    program = _program()
    commands = tuple(
        replace(
            command,
            effects=EffectSummary(
                reads=command.effects.reads,
                writes=command.effects.writes,
                performs_io=True,
            ),
        )
        if command.command_id == "command:increment"
        else command
        for command in program.commands
    )
    function = replace(
        program.functions[0],
        effects=EffectSummary(
            reads=("symbol:x", "symbol:result"),
            writes=("symbol:result",),
            raises=("ValueError",),
            performs_io=True,
        ),
    )
    program = replace(program, commands=commands, functions=(function,), program_id="")
    contract = replace(
        _contract(),
        effects=EffectSummary(
            reads=("symbol:x", "symbol:result"),
            writes=("symbol:result",),
            raises=("ValueError",),
            performs_io=True,
        ),
    )
    doc = _document(program=program, contract=contract)
    result = lower_to_verification_conditions(doc)

    unsupported_kinds = {
        item.kind
        for vc_set in result.vc_sets
        for item in vc_set.unsupported_effects
    }
    assert UnsupportedEffectKind.PERFORMS_IO in unsupported_kinds

    effect_obs = result.unsupported_effect_obligations()
    assert effect_obs, "unsupported effects must become obligations"
    for obligation in effect_obs:
        assert obligation.rule is VCRuleKind.UNSUPPORTED_EFFECT
        # Never assumed away.
        assert obligation.assumption_expression_ids == ()
        assert obligation.attributes.to_dict().get("never_assumption") is True
        assert obligation.attributes.to_dict().get("discharged_as") == "obligation"

    # No unsupported effect id may appear as a path assumption on any obligation.
    for vc_set in result.vc_sets:
        effect_ids = {item.effect_id for item in vc_set.unsupported_effects}
        for obligation in vc_set.obligations:
            assert effect_ids.isdisjoint(obligation.assumption_expression_ids)


def test_unsupported_loop_constructs_fail_or_become_obligations() -> None:
    for construct in sorted(UNSUPPORTED_LOOP_CONSTRUCTS):
        with pytest.raises(ProgramLogicError) as excinfo:
            ProgramLogicDocument.from_dict(
                {
                    "program": _program().to_dict(),
                    "contracts": [_contract().to_dict()],
                    "loop_contracts": [
                        {
                            "construct": construct,
                            "loop_id": "loop:bad",
                            "function_id": "function:increment",
                            "header_block_id": "block:entry",
                            "invariants": [],
                        }
                    ],
                }
            )
        assert excinfo.value.code == CODE_UNSUPPORTED_LOOP

    # Incomplete total-correctness loops under REQUIRED policy become obligations
    # rather than silent assumptions.
    incomplete = _loop_contract(total=False)
    doc = _document(loops=(incomplete,))
    result = VerificationConditionBridge(
        loop_variant_policy=LoopVariantPolicy.REQUIRED
    ).lower(doc)
    loop_obs = [
        item
        for item in result.all_obligations()
        if item.rule is VCRuleKind.UNSUPPORTED_EFFECT
        and item.source_construct_kind is SourceConstructKind.LOOP
    ]
    assert loop_obs
    for obligation in loop_obs:
        assert obligation.assumption_expression_ids == ()
        assert obligation.attributes.to_dict().get("never_assumption") is True
        assert "loop" in obligation.statement.casefold()


def test_bridge_rejects_missing_contracts() -> None:
    bare = ProgramLogicDocument(program=_program())
    with pytest.raises(VerificationConditionBridgeError):
        VerificationConditionBridge().lower(bare)


def test_syntax_facade_print_and_elaborate() -> None:
    syntax = ProgramLogicSyntax()
    doc = syntax.parse_program_ir(
        _program(),
        contracts=(_contract(),),
        hoare_triples=(_hoare(),),
        dynamic_formulas=(_dynamic(),),
    )
    assert syntax.elaborate(doc).program_id == doc.program.program_id
    text = syntax.print_json(doc)
    assert "program-logic-document/v1" in text or "binding_version" in text
    restored = syntax.parse_json(text)
    assert restored.document_id == doc.document_id
    lowered = syntax.lower_to_vc(doc)
    assert lowered.vc_sets
    assert lowered.family_id == "program"
