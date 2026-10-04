"""Learned Python candidates to typed pure IR, native logic views and Lean.

The learned decoder must reconstruct the source AST before either tree is
independently lowered.  This models exact built-in scalar inputs and total pure
expressions.  It neither executes Python nor invents a security specification.
Old pinned production grammar and projection modules are deliberately untouched.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil

SCHEMA = "security-learned-typed-logic/v2"
_SORTS = {"Int", "Bool", "String", "Unit", "opaque"}
_ARITH = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul"}
_COMPARE = {ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge"}
_AUTHORITY = {"proof_authority": False, "execution_authority": False,
              "source_runtime_semantics_verified": False, "security_specification_inferred": False}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 8_000_000:
        raise UnsupportedLogic("projection_resource_bound")
    return raw


class UnsupportedLogic(ValueError):
    """The source requires semantics outside the declared pure fragment."""


@dataclass(frozen=True, slots=True)
class PureExpression:
    op: str
    sort: str
    arguments: tuple["PureExpression", ...] = ()
    value: object = None

    def __post_init__(self):
        if self.sort not in _SORTS or self.sort == "opaque":
            raise UnsupportedLogic("expression_sort_unsupported")
        args = self.arguments
        if any(type(a) is not PureExpression for a in args):
            raise UnsupportedLogic("typed_expression_arguments_required")
        if self.op == "literal":
            if args or {int: "Int", bool: "Bool", str: "String", type(None): "Unit"}.get(type(self.value)) != self.sort:
                raise UnsupportedLogic("literal_sort_mismatch")
        elif self.op == "parameter":
            if args or type(self.value) is not str or not re.fullmatch(r"p[0-9]+", self.value):
                raise UnsupportedLogic("parameter_identifier_invalid")
        elif self.op in {"add", "sub", "mul", "neg", "pos"}:
            if len(args) != (1 if self.op in {"neg", "pos"} else 2) or self.sort != "Int" or any(a.sort != "Int" for a in args):
                raise UnsupportedLogic("integer_operator_sort_mismatch")
        elif self.op in {"not", "and", "or"}:
            if len(args) != (1 if self.op == "not" else 2) or self.sort != "Bool" or any(a.sort != "Bool" for a in args):
                raise UnsupportedLogic("boolean_operator_sort_mismatch")
        elif self.op in {"eq", "ne", "lt", "le", "gt", "ge"}:
            if len(args) != 2 or self.sort != "Bool" or args[0].sort != args[1].sort:
                raise UnsupportedLogic("comparison_sort_mismatch")
            if self.op not in {"eq", "ne"} and args[0].sort != "Int":
                raise UnsupportedLogic("ordering_requires_integers")
        elif self.op == "if":
            if len(args) != 3 or args[0].sort != "Bool" or args[1].sort != self.sort or args[2].sort != self.sort:
                raise UnsupportedLogic("conditional_sort_mismatch")
        else:
            raise UnsupportedLogic("unknown_expression_operator")

    def to_dict(self):
        return {"op": self.op, "sort": self.sort, "arguments": [x.to_dict() for x in self.arguments], "value": self.value}


@dataclass(frozen=True, slots=True)
class PureFunction:
    parameters: tuple[tuple[str, str, str], ...]
    result: PureExpression

    def __post_init__(self):
        if len(self.parameters) > 32 or type(self.result) is not PureExpression:
            raise UnsupportedLogic("bounded_typed_function_required")
        if any(p[1] != "p" + str(i) or p[2] not in _SORTS for i, p in enumerate(self.parameters)):
            raise UnsupportedLogic("typed_parameter_invalid")
        count = 0
        pending = [self.result]
        declared = {p[1]: p[2] for p in self.parameters}
        while pending:
            node = pending.pop()
            count += 1
            if count > 4096:
                raise UnsupportedLogic("expanded_expression_bound")
            if node.op == "parameter" and declared.get(node.value) != node.sort:
                raise UnsupportedLogic("parameter_sort_or_scope_mismatch")
            pending.extend(node.arguments)

    def to_dict(self):
        return {"schema": "security-pure-function-ir/v2", "parameters": [
            {"source_name": p[0], "name": p[1], "sort": p[2]} for p in self.parameters],
            "result_sort": self.result.sort, "result": self.result.to_dict(),
            "normalization": "fresh local substitution and path-sensitive conditional return"}


def lower_pure_function_v2(raw: bytes) -> PureFunction:
    """Independent AST lowering, with constrained scalar-sort unification."""
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise UnsupportedLogic("bounded_immutable_source_required")
    tree = ast.parse(raw, type_comments=True)
    count = 0
    pending = [(tree, 0)]
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > 1024 or depth > 40:
            raise UnsupportedLogic("source_ast_resource_bound")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    if len(tree.body) != 1 or type(tree.body[0]) is not ast.FunctionDef or tree.type_ignores:
        raise UnsupportedLogic("one_plain_synchronous_function_required")
    fn = tree.body[0]
    args = fn.args
    if (fn.decorator_list or fn.returns or fn.type_comment or getattr(fn, "type_params", ())
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults
            or args.kw_defaults or any(a.annotation or a.type_comment for a in args.args)):
        raise UnsupportedLogic("signature_or_decorator_has_unmodeled_semantics")
    names = [a.arg for a in args.args]
    if len(names) > 32 or len(names) != len(set(names)):
        raise UnsupportedLogic("bounded_distinct_parameters_required")
    substitution = {}
    used = set()
    lowering_steps = 0

    def budget():
        nonlocal lowering_steps
        lowering_steps += 1
        if lowering_steps > 4096:
            raise UnsupportedLogic("lowering_expansion_bound")

    def resolve(sort):
        while type(sort) is int and sort in substitution:
            sort = substitution[sort]
        return sort

    def unify(left, right):
        left, right = resolve(left), resolve(right)
        if left == right:
            return left
        if type(left) is int:
            substitution[left] = right
            return right
        if type(right) is int:
            substitution[right] = left
            return left
        raise UnsupportedLogic("scalar_sort_conflict:" + str(left) + ":" + str(right))

    env = {name: ("parameter", i, (), "p" + str(i)) for i, name in enumerate(names)}

    def expression(node, scope):
        budget()
        if type(node) is ast.Constant:
            sort = {int: "Int", bool: "Bool", str: "String", type(None): "Unit"}.get(type(node.value))
            if sort is None or (sort == "Int" and node.value.bit_length() > 64):
                raise UnsupportedLogic("literal_type_or_bound_unsupported")
            if sort == "String" and (len(node.value) > 1024 or any(0xD800 <= ord(c) <= 0xDFFF for c in node.value)):
                raise UnsupportedLogic("bounded_unicode_scalar_string_required")
            return "literal", sort, (), node.value
        if type(node) is ast.Name:
            if node.id not in scope:
                raise UnsupportedLogic("unbound_or_global_name")
            if node.id in names:
                used.add(names.index(node.id))
            return scope[node.id]
        if type(node) is ast.BinOp and type(node.op) in _ARITH:
            children = (expression(node.left, scope), expression(node.right, scope))
            for child in children:
                unify(child[1], "Int")
            return _ARITH[type(node.op)], "Int", children, None
        if type(node) is ast.UnaryOp and type(node.op) in (ast.UAdd, ast.USub, ast.Not):
            child = expression(node.operand, scope)
            sort = "Bool" if type(node.op) is ast.Not else "Int"
            unify(child[1], sort)
            return {ast.UAdd: "pos", ast.USub: "neg", ast.Not: "not"}[type(node.op)], sort, (child,), None
        if type(node) is ast.BoolOp and type(node.op) in (ast.And, ast.Or):
            children = [expression(v, scope) for v in node.values]
            for child in children:
                unify(child[1], "Bool")
            result = children[0]
            for child in children[1:]:
                result = "and" if type(node.op) is ast.And else "or", "Bool", (result, child), None
            return result
        if type(node) is ast.Compare and len(node.ops) == len(node.comparators) == 1 and type(node.ops[0]) in _COMPARE:
            children = (expression(node.left, scope), expression(node.comparators[0], scope))
            unify(children[0][1], children[1][1])
            if type(node.ops[0]) not in (ast.Eq, ast.NotEq):
                unify(children[0][1], "Int")
            return _COMPARE[type(node.ops[0])], "Bool", children, None
        if type(node) is ast.IfExp:
            return conditional(expression(node.test, scope), expression(node.body, scope), expression(node.orelse, scope))
        raise UnsupportedLogic("unsupported_expression:" + type(node).__name__)

    def conditional(test, yes, no):
        unify(test[1], "Bool")
        unify(yes[1], no[1])
        return "if", yes[1], (test, yes, no), None

    def block(statements, scope):
        budget()
        if not statements:
            raise UnsupportedLogic("every_path_requires_explicit_value_return")
        scope = dict(scope)
        for index, stmt in enumerate(statements):
            rest = statements[index + 1:]
            if type(stmt) is ast.Assign and len(stmt.targets) == 1 and type(stmt.targets[0]) is ast.Name and not stmt.type_comment:
                name = stmt.targets[0].id
                if name in scope:
                    raise UnsupportedLogic("reassignment_not_modeled")
                scope[name] = expression(stmt.value, scope)
            elif type(stmt) is ast.Return and stmt.value is not None:
                if rest:
                    raise UnsupportedLogic("unreachable_statements_not_modeled")
                return expression(stmt.value, scope)
            elif type(stmt) is ast.If:
                test = expression(stmt.test, scope)
                # Each arm is lowered separately; branch locals never leak.
                yes = block(stmt.body + rest, scope) if not _terminates(stmt.body) else block(stmt.body, scope)
                no = block(stmt.orelse + rest, scope) if not _terminates(stmt.orelse) else block(stmt.orelse, scope)
                if rest and _terminates(stmt.body) and _terminates(stmt.orelse):
                    raise UnsupportedLogic("unreachable_statements_not_modeled")
                return conditional(test, yes, no)
            else:
                raise UnsupportedLogic("unsupported_statement:" + type(stmt).__name__)
        raise UnsupportedLogic("every_path_requires_explicit_value_return")

    body = fn.body
    if body and type(body[0]) is ast.Expr and type(body[0].value) is ast.Constant and type(body[0].value.value) is str:
        body = body[1:]
    result = block(body, env)
    for i in used:
        if type(resolve(i)) is int:
            unify(i, "Int")

    expanded_nodes = 0

    def freeze(value, depth=0):
        nonlocal expanded_nodes
        expanded_nodes += 1
        if expanded_nodes > 4096 or depth > 64:
            raise UnsupportedLogic("expanded_expression_bound")
        op, sort, children, literal = value
        return PureExpression(op, resolve(sort), tuple(freeze(x, depth + 1) for x in children), literal)

    return PureFunction(tuple((name, "p" + str(i), resolve(i) if i in used else "opaque") for i, name in enumerate(names)), freeze(result))


def _terminates(statements):
    if not statements:
        return False
    last = statements[-1]
    return type(last) is ast.Return or (type(last) is ast.If and _terminates(last.body) and _terminates(last.orelse))


def _lean_expr(node):
    args = [_lean_expr(x) for x in node.arguments]
    if node.op == "literal":
        if node.sort == "Int": return "(" + str(node.value) + " : Int)"
        if node.sort == "Bool": return "true" if node.value else "false"
        if node.sort == "Unit": return "()"
        return "(String.ofList [" + ", ".join("Char.ofNat " + str(ord(c)) for c in node.value) + "])"
    if node.op == "parameter": return node.value
    if node.op == "pos": return args[0]
    if node.op in {"neg", "not"}: return "(" + ("-" if node.op == "neg" else "!") + args[0] + ")"
    if node.op == "if": return "(if " + args[0] + " then " + args[1] + " else " + args[2] + ")"
    op = {"add": "+", "sub": "-", "mul": "*", "and": "&&", "or": "||", "eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}[node.op]
    expr = "(" + args[0] + " " + op + " " + args[1] + ")"
    return "(decide " + expr + ")" if node.op in {"eq", "ne", "lt", "le", "gt", "ge"} else expr


def _render_lean(candidate, reference):
    generics = ["{T" + str(i) + " : Type}" for i, p in enumerate(candidate.parameters) if p[2] == "opaque"]
    params = ["(" + p[1] + " : " + ("T" + str(i) if p[2] == "opaque" else p[2]) + ")" for i, p in enumerate(candidate.parameters)]
    sig = " ".join(generics + params)
    applied = " ".join(p[1] for p in candidate.parameters)
    result = candidate.result.sort
    return "\n".join([
        "-- Equality of declared scalar models; no Python execution or inferred security requirement.",
        "namespace SecurityTypedLogic", "set_option autoImplicit false", "",
        "def predicted " + sig + " : " + result + " := " + _lean_expr(candidate.result),
        "def reference " + sig + " : " + result + " := " + _lean_expr(reference.result), "",
        "def resultContract " + sig + " (result : " + result + ") : Prop := result = reference " + applied,
        "theorem predicted_matches_source_model " + sig + " : predicted " + applied + " = reference " + applied + " := by rfl",
        "theorem predicted_satisfies_result_contract " + sig + " : resultContract " + applied + " (predicted " + applied + ") := by rfl",
        "end SecurityTypedLogic", ""])


def _native_projections(model, raw, path):
    from ....ir_core.provenance import SourceRef, SourceSpan
    from ....software_verification.program import (ProgramSymbol, ProgramExpression, ProgramCommand, ProgramFunction,
        ProgramIR, ControlFlowGraph, BasicBlock, EffectSummary)
    from ....software_verification.contracts import ProgramContract, ContractClause, FrameCondition
    from ....software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge
    source = SourceRef(ref_id="source:pure", source_uri="sha256:" + _sha(raw), source_id=path,
                       source_revision="sha256:" + _sha(raw), content_sha256=_sha(raw))
    span = SourceSpan(span_id="span:function", source_ref_id=source.ref_id, start_byte=0, end_byte=len(raw))
    mapped = {"source_ref_ids": (source.ref_id,), "span_ids": (span.span_id,)}
    symbols = [ProgramSymbol(p[1], p[0], p[2], "parameter", **mapped) for p in model.parameters]
    symbols.append(ProgramSymbol("result", "result", model.result.sort, "result", **mapped))
    expressions = []

    def expression(node):
        children = tuple(expression(x) for x in node.arguments)
        key = "expr:" + str(len(expressions))
        fields = {"operand_ids": children, "evaluation_order": children, **mapped}
        if node.op == "literal":
            kind = "literal"
            fields["attributes"] = {"value": node.value}
        elif node.op == "parameter":
            kind = "symbol"
            fields["symbol_ids"] = (node.value,)
        else:
            kind = "conditional" if node.op == "if" else ("unary" if len(children) == 1 else "binary")
            fields["operator"] = node.op
            if node.op in {"if", "and", "or"}:
                # The total pure model permits operand traversal without effects.
                fields["attributes"] = {"source_evaluation": "conditional", "operands_total_and_pure": True}
        expressions.append(ProgramExpression(key, kind, node.sort, **fields))
        return key

    result = expression(model.result)
    result_var = "expr:result"
    expressions.append(ProgramExpression(result_var, "result", model.result.sort, symbol_ids=("result",), **mapped))
    expressions.append(ProgramExpression("expr:contract", "binary", "Bool", operand_ids=(result_var, result),
        evaluation_order=(result_var, result), operator="eq", **mapped))
    reads = tuple(p[1] for p in model.parameters if p[2] != "opaque")
    effects = EffectSummary(reads=reads)
    command = ProgramCommand("command:return", "return", expression_ids=(result,), evaluation_order=(result,), effects=effects, **mapped)
    cfg = ControlFlowGraph("cfg:pure", "block:return", (BasicBlock("block:return", (command.command_id,), **mapped),), (), ("block:return",))
    function = ProgramFunction("function:pure", "source_model", cfg, parameter_symbol_ids=tuple(p[1] for p in model.parameters),
        result_symbol_id="result", return_type=model.result.sort, purity="pure", effects=effects, **mapped)
    program = ProgramIR((source,), (span,), tuple(symbols), tuple(expressions), (command,), (function,),
        metadata={"model": "total exact built-in scalar denotation", "source_spans": "whole function provenance; normalized model has no original instruction CFG",
                  "security_specification_inferred": False, "source_runtime_semantics_verified": False})
    contract = ProgramContract("contract:result", function.function_id,
        postconditions=(ContractClause("clause:result", "postcondition", "expr:contract",
            "Result equals the path-sensitive source scalar model under the declared input sorts.", **mapped),),
        frame=FrameCondition(readable_symbol_ids=reads), effects=effects, purity="pure", **mapped,
        attributes={"role": "derived_model_result_equation", "security_specification_inferred": False})
    contract.validate_against(program)
    bridge = SoftwareVerificationSyntaxBridge()
    result = []
    for kind, document in (("program", program), ("contract", contract)):
        roundtrip = bridge.round_trip(document)
        if not roundtrip.exact:
            raise UnsupportedLogic("native_bridge_not_exact:" + kind)
        route = bridge.route_for(kind)
        result.append({"kind": kind, "family_id": route.family_id, "profile_id": route.profile_id,
                       "native_document": document.to_dict(), "bridge": roundtrip.to_dict(), **_AUTHORITY})
    return result


def _smt_projection(candidate, reference):
    from ....backends.smt.compiler import (SmtTerm, SmtSort, SmtBinder, SmtObligation,
        SoftwareVerificationSMTCompiler)
    def term(node):
        if node.sort not in {"Int", "Bool"}:
            raise UnsupportedLogic("smt_scalar_route_requires_integer_or_boolean_values")
        if node.op == "literal":
            return SmtTerm("int" if node.sort == "Int" else "bool",
                value=str(node.value) if node.sort == "Int" else str(node.value).lower(), sort=SmtSort(node.sort))
        if node.op == "parameter":
            return SmtTerm("symbol", value=node.value, sort=SmtSort(node.sort))
        children = tuple(term(x) for x in node.arguments)
        if node.op == "pos": return children[0]
        kind = {"ne": "distinct", "if": "ite"}.get(node.op, node.op)
        return SmtTerm(kind, arguments=children, sort=SmtSort(node.sort))
    goal = SmtTerm("eq", arguments=(term(candidate.result), term(reference.result)))
    binders = tuple(SmtBinder(p[1], SmtSort(p[2])) for p in candidate.parameters if p[2] != "opaque")
    if binders:
        goal = SmtTerm("forall", arguments=(goal,), binders=binders)
    obligation = SmtObligation("obligation:learned_source_model_equality", "theorem_by_negation",
        features=("arithmetic", "equality", "quantifiers") if binders else ("arithmetic", "equality"),
        goal=goal, logic="ALL", attributes={"source_runtime_semantics_verified": False,
            "security_specification_inferred": False})
    compiled = SoftwareVerificationSMTCompiler().compile(obligation)
    return {"kind": "model_equality", "family_id": "smt", "profile_id": "scalar_first_order_model_equality",
            "native_obligation": obligation.to_dict(), "compilation": compiled.to_dict(),
            "solver_executed": False, **_AUTHORITY}


def project_security_formula_logic_v2(*, source_bytes, checkpoint, source_path,
                                      model_enabled=True, weight_ablation=None):
    from .security_formula_decoder_v2 import decode_security_formula_v2
    decoded = decode_security_formula_v2(source_bytes=source_bytes, checkpoint=checkpoint, source_path=source_path,
        model_enabled=model_enabled, weight_ablation=weight_ablation)
    report = {"schema": SCHEMA, "status": "unsupported", "source_sha256": _sha(source_bytes),
        "source_path": source_path, "checkpoint": checkpoint, "decode": decoded, "typed_ir": None,
        "source_typed_ir": None, "candidate_model": None, "source_model": None, "projections": [],
        "lean_source": None, "learned_equation_count": 0, "frontiers": [], "model_equality_verified": False,
        "projection_frontiers": [{"family_id": "transition_system", "reason": "no_explicit_state_schema_or_transition_relation"},
            {"family_id": "temporal", "reason": "no_trace_or_temporal_specification"},
            {"family_id": "deontic", "reason": "no_normative_requirement_inferred_from_code"}],
        "assumptions": ["Used parameters have exactly the inferred built-in scalar sorts; overloading and implicit truthiness are excluded.",
            "Unconstrained used parameters are modeled as mathematical integers; unused parameters remain polymorphic.",
            "Fresh locals are substituted; return paths become total pure conditional expressions.",
            "Resource exhaustion, concurrency and Python execution are outside this model.",
            "The derived result contract describes the model; it is not an independently supplied security requirement."], **_AUTHORITY}
    if not decoded.get("predicted_productions") or not decoded.get("validation", {}).get("source_AST_equivalent"):
        report["frontiers"] = ["no_independently_checked_learned_candidate"]
    else:
        try:
            candidate = lower_pure_function_v2(decoded["candidate_source"].encode())
            reference = lower_pure_function_v2(source_bytes)
            if candidate != reference:
                raise UnsupportedLogic("candidate_source_models_differ")
            projections = _native_projections(candidate, source_bytes, source_path)
            try:
                projections.append(_smt_projection(candidate, reference))
            except UnsupportedLogic as exc:
                report["projection_frontiers"].append({"family_id": "smt", "reason": str(exc)})
            report.update(status="candidate", typed_ir=candidate.to_dict(), source_typed_ir=reference.to_dict(),
                candidate_model=candidate.to_dict(), source_model=reference.to_dict(), projections=projections,
                lean_source=_render_lean(candidate, reference), learned_equation_count=1, model_equality_verified=True)
        except (UnsupportedLogic, SyntaxError, ValueError, RecursionError) as exc:
            report["frontiers"] = [str(exc)]
    report["projection_sha256"] = _sha(_wire(report))
    return report


def validate_security_formula_logic_v2(report, *, source_bytes, checkpoint, lake_executable, timeout_seconds=30):
    """Replay learned inference, regenerate every artifact, then run native Lake."""
    from ....backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("bounded Lake timeout required")
    expected = project_security_formula_logic_v2(source_bytes=source_bytes, checkpoint=checkpoint,
        source_path=report["source_path"], model_enabled=report["decode"]["model_enabled"],
        weight_ablation=report["decode"]["weight_ablation"])
    if _wire(expected) != _wire(report):
        raise ValueError("projection differs from regenerated learned candidate")
    receipt = {"schema": "security-typed-logic-lake/v2", "status": "not_run", "projection_sha256": report["projection_sha256"],
        "backend_executed": False, "model_equality_proved": False, "derived_result_contract_proved": False,
        "observations": [], "validation_decoder_replays": 1, **_AUTHORITY}
    if report["status"] != "candidate": return receipt
    found = shutil.which(str(lake_executable))
    if found is None:
        receipt.update(status="unavailable", reason="lake_executable_missing")
        return receipt
    executable = Path(found).absolute()
    if executable.parent.name == "bin" and executable.parent.parent.name == ".elan":
        receipt.update(status="unavailable", reason="select_installed_native_lake_not_elan_shim")
        return receipt
    runner = BoundedToolRunner()
    probe = runner.run(ToolRunRequest(argv=(str(executable), "--version"), limits=ToolRunLimits(timeout_seconds=5, max_output_bytes=16384)))
    version = re.search(r"Lean version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", probe.stdout)
    if not probe.ok or not version:
        receipt.update(status="unavailable", reason="native_lake_version_probe_failed")
        return receipt
    toolchain = "leanprover/lean4:v" + version.group(1)
    files = {"lakefile.toml": 'name = "security_typed_logic"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "SecurityTypedLogic"\n',
        "lean-toolchain": toolchain + "\n", "SecurityTypedLogic.lean": report["lean_source"]}
    command = (str(executable), "build", "SecurityTypedLogic")
    run = runner.run(ToolRunRequest(argv=command, input_files=files, environment={"ELAN_TOOLCHAIN": toolchain},
        limits=ToolRunLimits(timeout_seconds=timeout_seconds, cpu_seconds=timeout_seconds,
            max_input_bytes=1048576, max_output_bytes=262144, max_workspace_bytes=32 * 1024 * 1024)))
    passed = run.ok and not run.output_truncated and not run.workspace_limit_exceeded
    receipt.update(status="passed" if passed else "failed", backend_executed=True, model_equality_proved=passed,
        derived_result_contract_proved=passed, command=list(command), toolchain=toolchain,
        lean_source_sha256=_sha(report["lean_source"].encode()), observations=[{"returncode": run.returncode,
            "stdout": run.stdout, "stderr": run.stderr, "timed_out": run.timed_out}])
    return receipt
