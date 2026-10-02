"""Direct typed ProgramIR must not bypass the source proof profile.

The generic IR intentionally represents more than this SMT slice. These
fixtures pass its structural validator, then require semantic abstention at
the public lowering entrypoint before a compiler or solver can erase fields.
"""

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
from ipfs_datasets_py.logic.software_verification.codebase_pipeline import (
    ContractSpec,
    SOURCE_SEMANTICS_PROFILE,
    UnsupportedConstructError,
    attach_contract_specs,
    lower_vc_obligation_to_smt,
)
from ipfs_datasets_py.logic.software_verification.program import (
    BasicBlock,
    CommandKind,
    ControlFlowEdge,
    EdgeKind,
    ExpressionKind,
    ProgramSymbol,
    Purity,
    SymbolKind,
    UndefinedBehaviorCondition,
    UndefinedBehaviorConsequence,
)
from ipfs_datasets_py.logic.software_verification.codebase_source_adapters import (
    adapt_source_to_software_verification,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    VCRuleKind,
    generate_verification_conditions,
)


def _bound_program():
    adapted = adapt_source_to_software_verification(
        "def f(x: int) -> int:\n    pass\n    y = x + 1\n    return y\n",
        path="authored_direct_ir.py",
        revision="snapshot:direct-ir-boundary",
        preserve_type_annotations=True,
        include_supervisor_evidence=False,
    )
    assert adapted.supported and adapted.program is not None
    program, contracts = attach_contract_specs(
        adapted.program,
        (ContractSpec("f", postconditions=("result == x + 1",)),),
    )
    return program, contracts[0]


def _replace_command(program, command, **function_changes):
    return replace(
        program,
        commands=tuple(command if item.command_id == command.command_id else item
                       for item in program.commands),
        functions=(replace(program.functions[0], **function_changes),),
        program_id="",
    )


def _condition(program, contract):
    # Construction and validation succeeding is part of the regression: the
    # generic IR cannot decide this narrower source-to-SMT semantic policy.
    program.validate()
    contract.validate_against(program)
    conditions = generate_verification_conditions(program, contract)
    return conditions.obligations_by_rule(VCRuleKind.POSTCONDITION_NORMAL)[0]


def _reject(program, contract, reason):
    condition = _condition(program, contract)
    with pytest.raises(UnsupportedConstructError, match=reason):
        lower_vc_obligation_to_smt(program, condition)


def test_clean_direct_ir_retains_local_body_equations_and_profile():
    program, contract = _bound_program()
    obligation, body_names = lower_vc_obligation_to_smt(program, _condition(program, contract))
    compilation = SoftwareVerificationSMTCompiler().compile(obligation)
    assert body_names == ("body_assign_0", "body_return_1")
    assert obligation.attributes["source_semantics_profile"] == SOURCE_SEMANTICS_PROFILE
    assert "body_assign_0" in compilation.smtlib and "body_return_1" in compilation.smtlib


def test_direct_entry_assumption_rule_requires_a_separate_profile():
    program, contract = _bound_program()
    condition = replace(_condition(program, contract), rule=VCRuleKind.PRECONDITION)
    with pytest.raises(UnsupportedConstructError, match="VC rule"):
        lower_vc_obligation_to_smt(program, condition)


def test_direct_goal_cannot_fall_back_to_its_own_assumptions():
    program, contract = _bound_program()
    condition = _condition(program, contract)
    condition = replace(condition, goal_expression_ids=(),
                        assumption_expression_ids=condition.goal_expression_ids)
    with pytest.raises(UnsupportedConstructError, match="no goal expressions"):
        lower_vc_obligation_to_smt(program, condition)


@pytest.mark.parametrize("extra", ["value", "target"])
def test_return_cannot_discard_extra_values_or_write_targets(extra):
    program, contract = _bound_program()
    command = next(item for item in program.commands if item.kind is CommandKind.RETURN)
    if extra == "value":
        literal = next(item for item in program.expressions if item.kind is ExpressionKind.LITERAL)
        command = replace(command, expression_ids=(*command.expression_ids, literal.expression_id),
                          evaluation_order=())
    else:
        command = replace(command, target_symbol_ids=program.functions[0].local_symbol_ids)
    _reject(_replace_command(program, command), contract, "return must have exactly one value")


def test_skip_cannot_discard_declared_write_targets():
    program, contract = _bound_program()
    command = next(item for item in program.commands if item.kind is CommandKind.SKIP)
    command = replace(command, target_symbol_ids=program.functions[0].local_symbol_ids)
    _reject(_replace_command(program, command), contract, "command kind skip")


@pytest.mark.parametrize("command_kind", [CommandKind.ASSIGN, CommandKind.RETURN, CommandKind.SKIP])
@pytest.mark.parametrize("effect", ["performs_io", "nondeterministic", "synchronizes",
                                   "allocates", "deallocates", "raises"])
def test_observable_command_effects_are_not_erased(command_kind, effect):
    program, contract = _bound_program()
    command = next(item for item in program.commands if item.kind is command_kind)
    function = program.functions[0]
    value = (("ValueError",) if effect == "raises" else
             function.local_symbol_ids if effect in {"allocates", "deallocates"} else True)
    command = replace(command, effects=replace(command.effects, **{effect: value}))
    changes = {"effects": replace(function.effects, **{effect: value}), "purity": Purity.IMPURE}
    if effect == "raises":
        changes["declared_exceptions"] = ("ValueError",)
    changed = _replace_command(program, command, **changes)
    changed_contract = replace(contract, effects=changed.functions[0].effects,
                               purity=Purity.IMPURE)
    _reject(changed, changed_contract, "effects are outside|exceptional exits")


@pytest.mark.parametrize("effect", ["reads", "writes"])
def test_declared_read_and_write_effects_require_execution_correspondence(effect):
    program, contract = _bound_program()
    function = program.functions[0]
    if effect == "reads":
        command = next(item for item in program.commands if item.kind is CommandKind.ASSIGN)
        # y is a valid local symbol, but is not defined before this command.
        value = function.local_symbol_ids
    else:
        command = next(item for item in program.commands if item.kind is CommandKind.RETURN)
        # A return has no corresponding local assignment target.
        value = function.local_symbol_ids
    command = replace(command, effects=replace(command.effects, **{effect: value}))
    function_effects = replace(function.effects, **{
        effect: tuple(sorted(set(getattr(function.effects, effect)) | set(value)))
    })
    changed = _replace_command(program, command, effects=function_effects)
    changed_contract = replace(contract, effects=function_effects)
    _reject(changed, changed_contract, "unmodeled read/write effects")


def test_command_undefined_behavior_cannot_be_ignored():
    program, contract = _bound_program()
    command = next(item for item in program.commands if item.kind is CommandKind.ASSIGN)
    literal = next(item for item in program.expressions if item.kind is ExpressionKind.LITERAL)
    predicate = replace(literal, expression_id="expr:undefined-predicate", type_ref="boolean",
                        attributes={"value": True})
    condition = UndefinedBehaviorCondition(
        "condition:unmodeled", predicate.expression_id, "Unmodeled trap condition",
        UndefinedBehaviorConsequence.TRAP,
        source_ref_ids=command.source_ref_ids, span_ids=command.span_ids,
    )
    program = replace(program, expressions=(*program.expressions, predicate), program_id="")
    command = replace(command, undefined_behavior=(condition,))
    _reject(_replace_command(program, command), contract, "undefined behavior")


@pytest.mark.parametrize("exception_surface", ["declaration", "symbol", "cfg"])
def test_exception_frontiers_cannot_claim_straight_line_semantics(exception_surface):
    program, contract = _bound_program()
    function = program.functions[0]
    symbols = program.symbols
    if exception_surface == "declaration":
        function = replace(function, declared_exceptions=("ValueError",))
    elif exception_surface == "symbol":
        symbol = ProgramSymbol(
            "symbol:exception", "exception", "any", SymbolKind.EXCEPTION,
            source_ref_ids=function.source_ref_ids, span_ids=function.span_ids,
        )
        symbols = (*symbols, symbol)
        function = replace(function, exception_symbol_ids=(symbol.symbol_id,))
    else:
        entry = BasicBlock("block:new-entry", (), source_ref_ids=function.source_ref_ids,
                           span_ids=function.span_ids)
        exceptional = BasicBlock("block:exception", (), source_ref_ids=function.source_ref_ids,
                                 span_ids=function.span_ids)
        edges = (
            ControlFlowEdge("edge:normal", entry.block_id, function.cfg.entry_block_id,
                            EdgeKind.NORMAL, order=0),
            ControlFlowEdge("edge:exception", entry.block_id, exceptional.block_id,
                            EdgeKind.EXCEPTION, order=1, exception_type="ValueError"),
        )
        function = replace(function, cfg=replace(function.cfg,
                           entry_block_id=entry.block_id,
                           blocks=(*function.cfg.blocks, entry, exceptional), edges=edges,
                           exceptional_exit_block_ids=(exceptional.block_id,)),
                           declared_exceptions=("ValueError",))
    program = replace(program, functions=(function,), symbols=symbols, program_id="")
    _reject(program, contract, "exceptional exits|path-sensitive CFG")


@pytest.mark.parametrize("kind", [ExpressionKind.SYMBOL, ExpressionKind.RESULT])
def test_value_expressions_cannot_hide_an_unsupported_call(kind):
    program, contract = _bound_program()
    expression = next(item for item in program.expressions if item.kind is kind)
    hidden = replace(expression, expression_id="expr:hidden-call", kind=ExpressionKind.CALL,
                     operand_ids=(), evaluation_order=(), symbol_ids=(),
                     type_ref="integer", operator="unmodeled_callback")
    changed_expression = replace(expression, operand_ids=(hidden.expression_id,), evaluation_order=())
    program = replace(program,
                      expressions=tuple(changed_expression if item.expression_id == expression.expression_id
                                        else item for item in program.expressions) + (hidden,),
                      program_id="")
    _reject(program, contract, "exactly one typed symbol")


def test_arithmetic_expressions_cannot_hide_extra_symbol_dependencies():
    program, contract = _bound_program()
    expression = next(item for item in program.expressions
                      if item.kind is ExpressionKind.BINARY and item.operator == "add")
    expression = replace(expression, symbol_ids=program.functions[0].parameter_symbol_ids)
    program = replace(program,
                      expressions=tuple(expression if item.expression_id == expression.expression_id
                                        else item for item in program.expressions), program_id="")
    _reject(program, contract, "conceal extra symbol dependencies")


def test_direct_entrypoint_cannot_disable_source_body_admission():
    program, contract = _bound_program()
    with pytest.raises(UnsupportedConstructError, match="body semantics"):
        lower_vc_obligation_to_smt(program, _condition(program, contract),
                                  include_body_semantics=False)
