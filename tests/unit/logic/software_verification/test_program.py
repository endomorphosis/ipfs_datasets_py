"""Contracts for language-neutral program and contract semantics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.contracts import (
    ContractClause,
    ContractClauseKind,
    ContractValidationError,
    DynamicLogicExit,
    DynamicLogicFormula,
    DynamicLogicModality,
    DynamicProgramKind,
    ExceptionalPostcondition,
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
    ProgramValidationError,
    Purity,
    SymbolKind,
    UndefinedBehaviorCondition,
    UndefinedBehaviorConsequence,
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
            # Intentionally differs from operand order: a frontend's evaluation
            # order must survive canonicalization.
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


def test_program_ir_retains_source_and_evaluation_order_and_round_trips() -> None:
    program = _program()

    add = next(item for item in program.expressions if item.expression_id == "expr:add")
    block = next(
        item for item in program.functions[0].cfg.blocks if item.block_id == "block:normal"
    )

    assert add.operand_ids == ("expr:x", "expr:one")
    assert add.evaluation_order == ("expr:one", "expr:x")
    assert block.command_ids == ("command:increment", "command:return")
    assert add.span_ids == (SPAN_ID,)
    assert ProgramIR.from_dict(program.to_dict()) == program
    assert ProgramIR.from_dict(program.to_dict()).program_id == program.program_id
    assert program.program_id.startswith("b")


def test_program_ir_is_defensively_immutable_and_identity_is_order_independent() -> None:
    program = _program()
    payload = {"nested": {"values": [1]}}
    expression = ProgramExpression(
        "expr:immutable",
        ExpressionKind.LITERAL,
        "integer",
        attributes=payload,
        **_mapped(),
    )
    payload["nested"]["values"].append(2)

    reordered = replace(
        program,
        symbols=tuple(reversed(program.symbols)),
        expressions=tuple(reversed(program.expressions)),
        commands=tuple(reversed(program.commands)),
        program_id="",
    )

    assert expression.attributes["nested"]["values"] == (1,)
    assert reordered.program_id == program.program_id
    with pytest.raises(TypeError):
        expression.attributes["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        program.program_id = "changed"  # type: ignore[misc]


def test_cfg_separates_normal_and_exceptional_exits() -> None:
    cfg = _program().functions[0].cfg

    assert cfg.normal_exit_block_ids == ("block:normal",)
    assert cfg.exceptional_exit_block_ids == ("block:exception",)
    with pytest.raises(ProgramValidationError, match="normal and exceptional CFG exits"):
        replace(
            cfg,
            normal_exit_block_ids=("block:normal",),
            exceptional_exit_block_ids=("block:normal",),
        )


@pytest.mark.parametrize(
    ("edges", "message"),
    [
        (
            (
                ControlFlowEdge(
                    "edge:a",
                    "block:entry",
                    "block:normal",
                    EdgeKind.TRUE,
                    order=1,
                    condition_expression_id="expr:positive",
                ),
                ControlFlowEdge(
                    "edge:b",
                    "block:entry",
                    "block:exception",
                    EdgeKind.FALSE,
                    order=2,
                    condition_expression_id="expr:positive",
                ),
            ),
            "contiguous from zero",
        ),
        (
            (
                ControlFlowEdge(
                    "edge:a",
                    "block:entry",
                    "block:normal",
                    EdgeKind.NORMAL,
                ),
            ),
            "unreachable CFG blocks",
        ),
        (
            (
                ControlFlowEdge(
                    "edge:a",
                    "block:entry",
                    "block:normal",
                    EdgeKind.TRUE,
                    order=0,
                    condition_expression_id="expr:positive",
                ),
                ControlFlowEdge(
                    "edge:b",
                    "block:entry",
                    "block:exception",
                    EdgeKind.FALSE,
                    order=1,
                    condition_expression_id="expr:result",
                ),
            ),
            "must share one condition",
        ),
    ],
)
def test_malformed_cfgs_fail_closed(edges: tuple[ControlFlowEdge, ...], message: str) -> None:
    cfg = _program().functions[0].cfg
    with pytest.raises(ProgramValidationError, match=message):
        replace(cfg, edges=edges)


def test_cfg_rejects_unknown_commands() -> None:
    program = _program()
    cfg = program.functions[0].cfg
    changed_blocks = tuple(
        replace(block, command_ids=("command:missing",))
        if block.block_id == "block:normal"
        else block
        for block in cfg.blocks
    )
    changed_cfg = replace(cfg, blocks=changed_blocks)
    changed_function = replace(program.functions[0], cfg=changed_cfg)

    with pytest.raises(ProgramValidationError, match="unknown ids.*command:missing"):
        replace(program, functions=(changed_function,), program_id="")


def test_unbound_expression_symbols_fail_closed() -> None:
    program = _program()
    changed = tuple(
        replace(expression, symbol_ids=("symbol:ghost",))
        if expression.expression_id == "expr:x"
        else expression
        for expression in program.expressions
    )

    with pytest.raises(ProgramValidationError, match="unknown ids.*symbol:ghost"):
        replace(program, expressions=changed, program_id="")


def test_function_scope_rejects_a_symbol_owned_by_another_function() -> None:
    program = _program()
    ghost = ProgramSymbol(
        "symbol:other-local",
        "other",
        "integer",
        SymbolKind.LOCAL,
        **_mapped(),
    )
    changed = tuple(
        replace(expression, symbol_ids=("symbol:other-local",))
        if expression.expression_id == "expr:x"
        else expression
        for expression in program.expressions
    )

    with pytest.raises(ProgramValidationError, match="unknown ids.*other-local"):
        replace(
            program,
            symbols=program.symbols + (ghost,),
            expressions=changed,
            program_id="",
        )


def test_command_effects_must_fit_the_function_effect_summary() -> None:
    program = _program()
    changed_commands = tuple(
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

    with pytest.raises(ProgramValidationError, match="effects exceed function"):
        replace(program, commands=changed_commands, program_id="")


def test_contract_validates_effects_frames_exceptions_and_undefined_behavior() -> None:
    program = _program()
    contract = _contract()

    contract.validate_against(program)

    assert contract.normal_postconditions == contract.postconditions
    assert contract.purity is Purity.IMPURE
    assert contract.frame.writable_symbol_ids == ("symbol:result",)
    assert contract.undefined_behavior[0].consequence is UndefinedBehaviorConsequence.TRAP
    assert ProgramContract.from_dict(contract.to_dict()) == contract


def test_contract_frame_and_purity_are_fail_closed() -> None:
    with pytest.raises(ContractValidationError, match="exceed the contract frame"):
        replace(
            _contract(),
            frame=FrameCondition(readable_symbol_ids=("symbol:x",)),
        )

    with pytest.raises(ContractValidationError, match="pure contract"):
        replace(_contract(), purity=Purity.PURE)


def test_contract_rejects_unbound_expressions_and_undeclared_exceptions() -> None:
    program = _program()
    missing_expression = replace(
        _contract(),
        postconditions=(
            _clause(
                "clause:missing",
                ContractClauseKind.POSTCONDITION,
                "expr:missing",
            ),
        ),
    )
    with pytest.raises(ContractValidationError, match="unknown ids.*expr:missing"):
        missing_expression.validate_against(program)

    undeclared = replace(
        _contract(),
        exceptional_postconditions=(
            _clause(
                "clause:signals-other",
                ContractClauseKind.EXCEPTIONAL_POSTCONDITION,
                "expr:positive",
                exception_type="OtherError",
            ),
        ),
    )
    with pytest.raises(ContractValidationError, match="undeclared exceptions"):
        undeclared.validate_against(program)


def test_hoare_triples_keep_normal_and_exceptional_postconditions_distinct() -> None:
    program = _program()
    triple = HoareTriple(
        triple_id="hoare:increment",
        command_id="command:increment",
        precondition_ids=("expr:positive",),
        normal_postcondition_ids=("expr:result",),
        exceptional_postconditions=(ExceptionalPostcondition("ValueError", "expr:positive"),),
        total_correctness=True,
        variant_expression_ids=("expr:x",),
        **_mapped(),
    )

    triple.validate_against(program)

    assert triple.normal_postcondition_ids == ("expr:result",)
    assert triple.exceptional_postconditions[0].exception_type == "ValueError"
    with pytest.raises(ContractValidationError, match="require a variant"):
        replace(triple, variant_expression_ids=())


def test_loop_contract_has_invariants_and_ordered_variants() -> None:
    program = _program()
    loop = LoopContract(
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
        ),
        total_correctness=True,
        **_mapped(),
    )

    loop.validate_against(program)
    assert loop.variants[0].expression_id == "expr:x"

    with pytest.raises(ContractValidationError, match="require an invariant"):
        replace(loop, invariants=())


def test_dynamic_logic_box_and_diamond_name_an_explicit_exit_channel() -> None:
    program = _program()
    normal = DynamicLogicFormula(
        formula_id="dynamic:normal",
        modality=DynamicLogicModality.BOX,
        program_kind=DynamicProgramKind.FUNCTION,
        program_ref_id="function:increment",
        postcondition_expression_id="expr:result",
        exit=DynamicLogicExit.NORMAL,
        **_mapped(),
    )
    exceptional = DynamicLogicFormula(
        formula_id="dynamic:exceptional",
        modality=DynamicLogicModality.DIAMOND,
        program_kind=DynamicProgramKind.CFG,
        program_ref_id="cfg:increment",
        postcondition_expression_id="expr:positive",
        exit=DynamicLogicExit.EXCEPTIONAL,
        exception_type="ValueError",
        **_mapped(),
    )

    normal.validate_against(program)
    exceptional.validate_against(program)

    assert normal.to_dict()["modality"] == "box"
    assert exceptional.to_dict()["exit"] == "exceptional"
    with pytest.raises(ContractValidationError, match="require exception_type"):
        replace(exceptional, exception_type="")


def test_source_maps_are_resolved_against_program_sources() -> None:
    program = _program()
    contract = replace(
        _contract(),
        source_ref_ids=("source:missing",),
        span_ids=(),
    )

    with pytest.raises(ContractValidationError, match="source:missing"):
        contract.validate_against(program)
