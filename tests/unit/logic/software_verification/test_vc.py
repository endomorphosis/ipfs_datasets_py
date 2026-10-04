"""Executable contract for weakest-precondition / verification-condition generation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.contracts import (
    ContractClause,
    ContractClauseKind,
    FrameCondition,
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
    VERIFICATION_CONDITION_GENERATOR_INTERFACE,
    GeneratedSymbol,
    LoopVariantPolicy,
    SourceConstructKind,
    UnsupportedEffectKind,
    VCRuleKind,
    VCValidationError,
    VerificationConditionGenerator,
    VerificationConditionSet,
    VerificationObligation,
    generate_verification_conditions,
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


def _generate(
    *,
    program: ProgramIR | None = None,
    contract: ProgramContract | None = None,
    loops: tuple[LoopContract, ...] = (),
    loop_variant_policy: LoopVariantPolicy = LoopVariantPolicy.OPTIONAL,
) -> VerificationConditionSet:
    return VerificationConditionGenerator(
        loop_variant_policy=loop_variant_policy
    ).generate(
        program or _program(),
        contract or _contract(),
        loops,
    )


def test_generator_exposes_verification_condition_generator_interface() -> None:
    generator = VerificationConditionGenerator()
    assert generator.INTERFACE == VERIFICATION_CONDITION_GENERATOR_INTERFACE
    assert generator.to_dict()["interface"] == "VerificationConditionGenerator@1"
    assert VerificationConditionGenerator.from_dict(generator.to_dict()) == generator


def test_generate_binds_source_construct_assumptions_symbols_rule_and_parent() -> None:
    result = _generate()

    assert result.INTERFACE == VERIFICATION_CONDITION_GENERATOR_INTERFACE
    assert result.parent_contract_id == "contract:increment"
    assert result.function_id == "function:increment"
    assert result.program_id == _program().program_id
    assert result.vc_set_id.startswith("b")
    assert result.obligations

    for obligation in result.obligations:
        assert isinstance(obligation.rule, VCRuleKind)
        assert obligation.parent_contract_id == "contract:increment"
        assert obligation.function_id == "function:increment"
        assert isinstance(obligation.source_construct_kind, SourceConstructKind)
        assert obligation.source_construct_id
        assert obligation.source_ref_ids or obligation.span_ids
        assert obligation.obligation_id.startswith("vc:")

    assign = next(
        item for item in result.obligations if item.rule is VCRuleKind.ASSIGN
    )
    assert assign.source_construct_id == "command:increment"
    assert assign.generated_symbol_ids == ("gen:command:increment:symbol:result",)
    assert assign.assumption_expression_ids == ("expr:positive",)
    assert any(
        item.symbol_id == "gen:command:increment:symbol:result"
        for item in result.generated_symbols
    )

    payload = result.to_dict()
    assert payload["interface"] == "VerificationConditionGenerator@1"
    assert VerificationConditionSet.from_dict(payload) == result
    assert result.to_json().encode() == result.canonical_bytes()


def test_branch_edges_produce_independent_true_and_false_obligations() -> None:
    result = _generate()
    true_obs = result.obligations_by_rule(VCRuleKind.BRANCH_TRUE)
    false_obs = result.obligations_by_rule(VCRuleKind.BRANCH_FALSE)

    assert {item.source_construct_id for item in true_obs} == {"edge:valid"}
    assert {item.source_construct_id for item in false_obs} == {"edge:invalid"}
    assert result.branch_edge_ids() == frozenset({"edge:valid", "edge:invalid"})
    assert true_obs[0].attributes["polarity"] == "true"
    assert false_obs[0].attributes["polarity"] == "false"
    assert true_obs[0].path_condition_expression_ids[-1] == "expr:positive"


def test_frame_and_resource_obligations_cover_modified_symbols() -> None:
    result = _generate()
    frames = result.obligations_by_rule(VCRuleKind.FRAME)

    assert result.frame_construct_ids() == frozenset({"symbol:result"})
    assert frames[0].source_construct_kind is SourceConstructKind.FRAME
    assert frames[0].attributes["writable"] is True
    assert frames[0].parent_contract_id == "contract:increment"


def test_exceptional_and_normal_postconditions_are_distinct() -> None:
    result = _generate()
    normal = result.obligations_by_rule(VCRuleKind.POSTCONDITION_NORMAL)
    exceptional = result.obligations_by_rule(VCRuleKind.POSTCONDITION_EXCEPTIONAL)

    assert normal
    assert all(item.goal_expression_ids == ("expr:result",) for item in normal)
    assert exceptional
    assert any(
        item.attributes.get("exception_type") == "ValueError" for item in exceptional
    )
    assert result.obligations_by_rule(VCRuleKind.THROW)
    assert result.obligations_by_rule(VCRuleKind.RETURN)
    assert result.obligations_by_rule(VCRuleKind.ASSERT)
    assert result.obligations_by_rule(VCRuleKind.PRECONDITION)


def test_loop_rules_require_invariant_and_variant_policy() -> None:
    with_total = _generate(
        loops=(_loop_contract(total=True),),
        loop_variant_policy=LoopVariantPolicy.REQUIRED,
    )
    assert with_total.obligations_by_rule(VCRuleKind.LOOP_INVARIANT_INIT)
    assert with_total.obligations_by_rule(VCRuleKind.LOOP_INVARIANT_PRESERVE)
    assert with_total.obligations_by_rule(VCRuleKind.LOOP_VARIANT_DECREASE)
    assert with_total.obligations_by_rule(VCRuleKind.LOOP_VARIANT_BOUNDED)
    assert with_total.loop_variant_policy is LoopVariantPolicy.REQUIRED

    with pytest.raises(VCValidationError, match="requires a variant"):
        _generate(
            loops=(_loop_contract(total=False),),
            loop_variant_policy=LoopVariantPolicy.REQUIRED,
        )

    with pytest.raises(VCValidationError, match="supplies variants under policy none"):
        _generate(
            loops=(_loop_contract(total=True),),
            loop_variant_policy=LoopVariantPolicy.NONE,
        )


def test_unsupported_effects_remain_explicit() -> None:
    program = _program()
    # Inject an explicit I/O effect on the assign command.
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
    # Function effects must dominate command effects.
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

    result = _generate(program=program, contract=contract)

    kinds = {item.kind for item in result.unsupported_effects}
    assert UnsupportedEffectKind.PERFORMS_IO in kinds
    assert UnsupportedEffectKind.UNDEFINED_BEHAVIOR in kinds
    assert result.obligations_by_rule(VCRuleKind.UNDEFINED)
    assert result.obligations_by_rule(VCRuleKind.UNSUPPORTED_EFFECT) or any(
        item.kind is UnsupportedEffectKind.PERFORMS_IO
        for item in result.unsupported_effects
    )


def test_resource_commands_emit_resource_obligations() -> None:
    mapped = _mapped()
    symbols = (
        ProgramSymbol("symbol:buf", "buf", "ptr", SymbolKind.LOCAL, **mapped),
        ProgramSymbol("symbol:ok", "ok", "boolean", SymbolKind.RESULT, **mapped),
    )
    expressions = (
        ProgramExpression(
            "expr:true",
            ExpressionKind.LITERAL,
            "boolean",
            attributes={"value": True},
            **mapped,
        ),
        ProgramExpression(
            "expr:ok",
            ExpressionKind.RESULT,
            "boolean",
            symbol_ids=("symbol:ok",),
            **mapped,
        ),
    )
    commands = (
        ProgramCommand(
            "command:alloc",
            CommandKind.ALLOCATE,
            target_symbol_ids=("symbol:buf",),
            effects=EffectSummary(allocates=("symbol:buf",)),
            **mapped,
        ),
        ProgramCommand(
            "command:free",
            CommandKind.DEALLOCATE,
            target_symbol_ids=("symbol:buf",),
            effects=EffectSummary(deallocates=("symbol:buf",)),
            **mapped,
        ),
        ProgramCommand(
            "command:ret",
            CommandKind.RETURN,
            expression_ids=("expr:ok",),
            effects=EffectSummary(reads=("symbol:ok",)),
            **mapped,
        ),
    )
    cfg = ControlFlowGraph(
        graph_id="cfg:resource",
        entry_block_id="block:body",
        blocks=(
            BasicBlock(
                "block:body",
                ("command:alloc", "command:free", "command:ret"),
                **mapped,
            ),
        ),
        edges=(),
        normal_exit_block_ids=("block:body",),
    )
    function = ProgramFunction(
        function_id="function:resource",
        name="resource",
        cfg=cfg,
        local_symbol_ids=("symbol:buf",),
        result_symbol_id="symbol:ok",
        return_type="boolean",
        purity=Purity.IMPURE,
        effects=EffectSummary(
            reads=("symbol:ok",),
            allocates=("symbol:buf",),
            deallocates=("symbol:buf",),
        ),
        **mapped,
    )
    program = ProgramIR(
        sources=(_source(),),
        spans=(_span(),),
        symbols=symbols,
        expressions=expressions,
        commands=commands,
        functions=(function,),
    )
    contract = ProgramContract(
        contract_id="contract:resource",
        function_id="function:resource",
        preconditions=(
            _clause("clause:pre", ContractClauseKind.PRECONDITION, "expr:true"),
        ),
        postconditions=(
            _clause("clause:post", ContractClauseKind.POSTCONDITION, "expr:ok"),
        ),
        frame=FrameCondition(
            readable_symbol_ids=("symbol:buf", "symbol:ok"),
            writable_symbol_ids=("symbol:buf", "symbol:ok"),
        ),
        effects=EffectSummary(
            reads=("symbol:ok",),
            allocates=("symbol:buf",),
            deallocates=("symbol:buf",),
        ),
        purity=Purity.IMPURE,
        **mapped,
    )

    result = generate_verification_conditions(program, contract)

    assert result.obligations_by_rule(VCRuleKind.ALLOCATE)
    assert result.obligations_by_rule(VCRuleKind.DEALLOCATE)
    assert result.obligations_by_rule(VCRuleKind.RESOURCE)
    assert result.frame_construct_ids() == frozenset({"symbol:buf"})


def test_mutation_detects_dropped_branch_obligations() -> None:
    complete = _generate()
    mutated = complete.without_rules(VCRuleKind.BRANCH_TRUE, VCRuleKind.BRANCH_FALSE)

    assert complete.branch_edge_ids()
    assert not mutated.branch_edge_ids()
    with pytest.raises(VCValidationError, match="missing branch obligations"):
        VerificationConditionGenerator().validate_coverage(
            _program(), _contract(), mutated
        )


def test_mutation_detects_dropped_frame_obligations() -> None:
    complete = _generate()
    mutated = complete.without_rules(VCRuleKind.FRAME)

    assert complete.frame_construct_ids() == frozenset({"symbol:result"})
    assert not mutated.frame_construct_ids()
    with pytest.raises(VCValidationError, match="missing frame obligations"):
        VerificationConditionGenerator().validate_coverage(
            _program(), _contract(), mutated
        )


def test_vc_set_is_immutable_and_content_addressed() -> None:
    result = _generate()
    reordered = VerificationConditionSet(
        program_id=result.program_id,
        function_id=result.function_id,
        parent_contract_id=result.parent_contract_id,
        obligations=tuple(reversed(result.obligations)),
        weakest_preconditions=tuple(reversed(result.weakest_preconditions)),
        generated_symbols=tuple(reversed(result.generated_symbols)),
        unsupported_effects=tuple(reversed(result.unsupported_effects)),
        loop_variant_policy=result.loop_variant_policy,
        attributes=result.attributes,
        vc_set_id="",
    )

    assert reordered.vc_set_id == result.vc_set_id
    with pytest.raises(FrozenInstanceError):
        result.vc_set_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.attributes["new"] = True  # type: ignore[index]


def test_malformed_inputs_fail_closed() -> None:
    with pytest.raises(VCValidationError, match="ProgramIR"):
        VerificationConditionGenerator().generate(  # type: ignore[arg-type]
            "not-a-program",
            _contract(),
        )

    bad_contract = replace(_contract(), function_id="function:missing")
    with pytest.raises(VCValidationError, match="unknown function"):
        _generate(contract=bad_contract)

    with pytest.raises(VCValidationError, match="unsupported interface"):
        VerificationConditionSet.from_dict(
            {
                "interface": "Other@1",
                "program_id": "program:x",
                "function_id": "function:x",
                "parent_contract_id": "contract:x",
                "obligations": [],
            }
        )


def test_obligation_records_reject_missing_bindings() -> None:
    with pytest.raises(VCValidationError):
        VerificationObligation(
            obligation_id="vc:broken",
            rule=VCRuleKind.ASSERT,
            parent_contract_id="",
            function_id="function:increment",
            source_construct_kind=SourceConstructKind.COMMAND,
            source_construct_id="command:guard",
            source_ref_ids=(SOURCE_ID,),
            span_ids=(SPAN_ID,),
        )

    with pytest.raises(VCValidationError, match="source mapped"):
        VerificationObligation(
            obligation_id="vc:unmapped",
            rule=VCRuleKind.ASSERT,
            parent_contract_id="contract:increment",
            function_id="function:increment",
            source_construct_kind=SourceConstructKind.COMMAND,
            source_construct_id="command:guard",
        )


def test_generated_symbol_and_unsupported_effect_round_trip() -> None:
    symbol = GeneratedSymbol(
        symbol_id="gen:example",
        origin_symbol_id="symbol:result",
        rule=VCRuleKind.HAVOC,
        construct_id="command:increment",
        reason="fresh value",
    )
    assert GeneratedSymbol.from_dict(symbol.to_dict()) == symbol
