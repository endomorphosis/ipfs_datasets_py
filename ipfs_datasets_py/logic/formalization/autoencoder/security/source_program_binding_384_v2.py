"""Add explicit complete effect summaries to the guarded v1 source binding.

The source grammar, learned prediction and scalar typing checks stay owned by
v1. This additive contract derives reads/writes from that validated native
expression graph, retaining all other effects, purity and original metadata.
It neither executes Python nor grants source-equivalence or proof authority.
"""
from __future__ import annotations

from copy import deepcopy

from . import source_program_binding_384 as previous
from ....software_verification.program import ProgramIR
from ....software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge

SCHEMA = "security-source-program-binding-384/v2"
EFFECTS_SCHEMA = "security-source-program-effects-384/v2"
EFFECT_AUDIT_SCHEMA = "security-source-program-effect-audit/v1"
EFFECT_SUMMARY_CONTRACT = "closed-command-expression-reads-and-assignment-writes/v1"
EFFECT_SUMMARY_ASSUMPTION = (
    "Read/write summaries are derived from the validated expression graph; "
    "all other effect flags and the native purity classification are preserved."
)
METADATA_EXTENSION_KEYS = (
    "source_binding_effects_schema", "effect_summary_contract",
    "effect_summary_assumption", "effect_summary_audit",
)
EFFECT_OTHER_FIELDS = (
    "allocates", "deallocates", "nondeterministic", "performs_io", "raises", "synchronizes",
)


class EffectContractError(ValueError):
    """A supposedly closed native source graph cannot support exact effects."""


def _require(condition, reason):
    if not condition:
        raise EffectContractError(reason)


def _summary(before_effects, reads, writes):
    _require(set(before_effects) == {"reads", "writes", *EFFECT_OTHER_FIELDS},
             "closed_native_effect_fields_required")
    before = {key: before_effects[key] for key in ("reads", "writes")}
    after = dict(reads=sorted(reads), writes=sorted(writes))
    _require(all(set(before[key]) <= set(after[key]) for key in before),
             "native_declared_effects_exceed_guarded_expression_model")
    retained = {key: deepcopy(before_effects[key]) for key in EFFECT_OTHER_FIELDS}
    return dict(before=deepcopy(before), after=after, retained_effects=retained)


def _complete_effects(payload):
    """Derive complete summaries, rejecting graphs outside the v1 source scope."""
    program = ProgramIR.from_dict(payload)
    _require(previous._wire(program.to_dict()) == previous._wire(payload),
             "exact_native_program_roundtrip_required")
    wire = deepcopy(payload)
    _require(not set(METADATA_EXTENSION_KEYS) & set(wire["metadata"]),
             "effect_contract_already_present")
    _require(len(wire["functions"]) == 1 and not wire["global_symbol_ids"],
             "one_closed_source_function_required")
    function = wire["functions"][0]
    cfg = function["cfg"]
    _require(len(cfg["blocks"]) == 1 and not cfg["edges"]
             and not cfg["exceptional_exit_block_ids"], "straight_line_source_cfg_required")
    block = cfg["blocks"][0]
    _require(cfg["entry_block_id"] == block["block_id"]
             and cfg["normal_exit_block_ids"] == [block["block_id"]], "single_normal_source_exit_required")
    symbols = {row["symbol_id"]: row for row in wire["symbols"]}
    expressions = {row["expression_id"]: row for row in wire["expressions"]}
    commands = {row["command_id"]: row for row in wire["commands"]}
    _require(set(commands) == set(block["command_ids"]) and len(commands) in (1, 2),
             "direct_or_one_temporary_source_commands_required")
    _require(len(function["parameter_symbol_ids"]) == 2
             and len(function["local_symbol_ids"]) == len(commands) - 1,
             "two_parameters_and_at_most_one_temporary_required")
    parameters = set(function["parameter_symbol_ids"])
    locals_ = set(function["local_symbol_ids"])
    _require(set(symbols) == parameters | locals_ | {function["result_symbol_id"]}
             and all(symbols[key]["kind"] == "parameter" and symbols[key]["type_ref"] == "integer"
                     for key in parameters)
             and all(symbols[key]["kind"] == "local" for key in locals_),
             "closed_annotated_integer_symbol_scope_required")
    memo, visiting, visited = {}, set(), set()

    def expression_reads(key):
        if key in memo:
            return memo[key]
        _require(key in expressions and key not in visiting, "cyclic_or_unbound_expression_graph")
        visiting.add(key)
        row = expressions[key]
        _require(not row["attributes"] and row["evaluation_order"] == row["operand_ids"],
                 "opaque_or_reordered_expression_not_supported")
        if row["kind"] == "symbol":
            _require(len(row["symbol_ids"]) == 1 and not row["operand_ids"] and not row["operator"],
                     "plain_symbol_expression_required")
            symbol = row["symbol_ids"][0]
            _require(symbol in parameters | locals_
                     and row["type_ref"] == symbols[symbol]["type_ref"],
                     "expression_symbol_or_type_outside_source_scope")
            reads = {symbol}
        else:
            _require(row["kind"] == "binary" and len(row["operand_ids"]) == 2 and not row["symbol_ids"],
                     "supported_binary_source_expression_required")
            expected_type = ("integer" if row["operator"] in ("add", "sub", "mul") else
                             "boolean" if row["operator"] in ("lt", "le", "gt", "ge", "eq", "ne") else None)
            _require(expected_type is not None and row["type_ref"] == expected_type
                     and all(expressions[operand]["type_ref"] == "integer" for operand in row["operand_ids"]),
                     "source_binary_operator_or_type_unsupported")
            reads = set().union(*(expression_reads(operand) for operand in row["operand_ids"]))
            _require(reads == parameters, "binary_expression_must_read_both_parameters")
        visiting.remove(key)
        visited.add(key)
        memo[key] = reads
        return reads

    audit = dict(schema=EFFECT_AUDIT_SCHEMA, base_program_id=program.program_id,
        base_program_sha256=previous._sha(previous._wire(payload)), commands=[], functions=[])
    initialized, total_reads, total_writes = set(parameters), set(), set()
    ordered = [commands[key] for key in block["command_ids"]]
    for index, command in enumerate(ordered):
        ids, targets = command["expression_ids"], command["target_symbol_ids"]
        _require(len(ids) == 1 and command["evaluation_order"] == ids
                 and not command["attributes"] and not command["undefined_behavior"],
                 "closed_source_command_required")
        reads = expression_reads(ids[0])
        _require(reads <= initialized, "source_read_before_initialization")
        if command["kind"] == "assign":
            _require(index == 0 and len(ordered) == 2 and len(targets) == 1 and set(targets) == locals_
                     and expressions[ids[0]]["kind"] == "binary"
                     and expressions[ids[0]]["type_ref"] == symbols[targets[0]]["type_ref"],
                     "single_fresh_temporary_assignment_required")
            writes = set(targets)
        else:
            _require(command["kind"] == "return" and index == len(ordered) - 1 and not targets
                     and expressions[ids[0]]["type_ref"] == function["return_type"],
                     "typed_terminal_return_required")
            _require((len(ordered) == 1 and expressions[ids[0]]["kind"] == "binary")
                     or (len(ordered) == 2 and expressions[ids[0]]["kind"] == "symbol" and reads == locals_),
                     "source_return_shape_mismatch")
            writes = set()
        change = dict(command_id=command["command_id"], **_summary(command["effects"], reads, writes))
        audit["commands"].append(change)
        command["effects"].update(change["after"])
        initialized.update(writes)
        total_reads.update(reads)
        total_writes.update(writes)
    _require(visited == set(expressions), "unused_native_expression_outside_source_scope")
    change = dict(function_id=function["function_id"],
        **_summary(function["effects"], total_reads, total_writes), purity=function["purity"])
    audit["functions"].append(change)
    function["effects"].update(change["after"])
    audit["commands"].sort(key=lambda row: row["command_id"])
    wire["metadata"].update(source_binding_effects_schema=EFFECTS_SCHEMA,
        effect_summary_contract=EFFECT_SUMMARY_CONTRACT,
        effect_summary_assumption=EFFECT_SUMMARY_ASSUMPTION, effect_summary_audit=audit)
    wire["program_id"] = ""
    return ProgramIR.from_dict(wire), audit


def qualify_source_candidate(source_text, candidate):
    """Qualify the v1 fragment and complete only audited read/write effects."""
    baseline = previous.qualify_source_candidate(source_text, candidate)
    report = deepcopy(baseline)
    report["schema"] = SCHEMA
    report["base_qualification_sha256"] = previous._sha(previous._wire(baseline))
    if baseline["status"] != "qualified":
        return report
    try:
        _require(len(report["projections"]) == 1, "one_source_program_projection_required")
        projection = report["projections"][0]
        program, audit = _complete_effects(projection["native_document"])
        bridge = SoftwareVerificationSyntaxBridge().round_trip(program)
        _require(bridge.exact, "effect_complete_native_program_roundtrip_not_exact")
        projection.update(native_document=program.to_dict(), bridge=bridge.to_dict())
        report["source_binding"].update(native_program_id=program.program_id,
            effect_summary_refinements=deepcopy(audit), effect_summary_contract=EFFECT_SUMMARY_CONTRACT)
        report["checks"].extend([
            dict(check="source_expression_graph_effects_complete", status="passed"),
            dict(check="effect_complete_native_program_roundtrip", status="passed"),
        ])
        report["assumptions"].append(EFFECT_SUMMARY_ASSUMPTION)
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
        report.update(status="unsupported", qualified=False, projections=[], source_binding=None,
            reason=str(exc) if isinstance(exc, EffectContractError) else "native_effect_contract_error",
            error_type=type(exc).__name__)
    return report


def verify_source_qualification(report, source_text, candidate):
    """Replay the source, learned fragment, type refinement and effect audit."""
    expected = qualify_source_candidate(source_text, candidate)
    if previous._wire(report) != previous._wire(expected):
        raise ValueError("source qualification v2 report does not match exact replay")
    return expected
