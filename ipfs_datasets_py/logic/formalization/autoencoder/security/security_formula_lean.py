"""Lean equations for independently checked learned pure-function candidates.

This additive route leaves the frozen production decoder and its checkpoint
unchanged. It models integer arithmetic and constant strings, not arbitrary
Python execution. Source and learned candidate are lowered independently; Lake
checks their model equality. No security specification is inferred.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import shutil

SCHEMA = "security-learned-pure-equations/v1"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class UnsupportedEquation(ValueError):
    """The candidate needs semantics outside the explicit pure model."""


def _lower(raw):
    """Independently inspect Python AST; do not consume decoder teacher labels."""
    if not 0 < len(raw) <= 65_536:
        raise UnsupportedEquation("bounded_function_required")
    tree = ast.parse(raw, type_comments=True)
    if len(list(ast.walk(tree))) > 1024 or len(tree.body) != 1 or type(tree.body[0]) is not ast.FunctionDef:
        raise UnsupportedEquation("one_bounded_synchronous_function_required")
    fn = tree.body[0]
    args = fn.args
    if (tree.type_ignores or fn.decorator_list or fn.returns or fn.type_comment
            or getattr(fn, "type_params", ()) or args.posonlyargs or args.kwonlyargs
            or args.vararg or args.kwarg or args.defaults or args.kw_defaults
            or any(a.annotation or a.type_comment for a in args.args)):
        raise UnsupportedEquation("signature_or_decorator_has_unmodeled_semantics")
    statements = fn.body
    if (statements and type(statements[0]) is ast.Expr and type(statements[0].value) is ast.Constant
            and type(statements[0].value.value) is str):
        statements = statements[1:]
    if not statements or type(statements[-1]) is not ast.Return or statements[-1].value is None:
        raise UnsupportedEquation("terminal_value_return_required")
    names = [a.arg for a in args.args]
    if len(names) != len(set(names)) or len(names) > 32:
        raise UnsupportedEquation("bounded_distinct_parameters_required")
    env = {name: ("Int", "p"+str(i)) for i, name in enumerate(names)}
    used_parameters = set()

    def expression(node, depth=0):
        if depth > 32:
            raise UnsupportedEquation("expression_depth_bound")
        if type(node) is ast.Constant and type(node.value) is int and node.value.bit_length() <= 64:
            return "Int", {"kind":"integer", "value":node.value}
        if type(node) is ast.Constant and type(node.value) is str and len(node.value) <= 128:
            if any(0xD800 <= ord(c) <= 0xDFFF for c in node.value):
                raise UnsupportedEquation("surrogate_string_literal")
            return "String", {"kind":"string", "codepoints":[ord(c) for c in node.value]}
        if type(node) is ast.Name and node.id in env:
            sort, name = env[node.id]
            if node.id in names:
                used_parameters.add(node.id)
            return sort, {"kind":"name", "name":name}
        if type(node) is ast.BinOp and type(node.op) in (ast.Add, ast.Sub, ast.Mult):
            left_sort, left = expression(node.left, depth+1)
            right_sort, right = expression(node.right, depth+1)
            if left_sort != "Int" or right_sort != "Int":
                raise UnsupportedEquation("only_integer_binary_operations_modeled")
            return "Int", {"kind":{ast.Add:"add",ast.Sub:"sub",ast.Mult:"mul"}[type(node.op)], "left":left,"right":right}
        if type(node) is ast.UnaryOp and type(node.op) in (ast.UAdd, ast.USub):
            sort, child = expression(node.operand, depth+1)
            if sort != "Int":
                raise UnsupportedEquation("only_integer_unary_operations_modeled")
            return sort, {"kind":"pos" if type(node.op) is ast.UAdd else "neg", "child":child}
        raise UnsupportedEquation("unsupported_expression:"+type(node).__name__)

    bindings = []
    for statement in statements[:-1]:
        if (type(statement) is not ast.Assign or len(statement.targets) != 1
                or type(statement.targets[0]) is not ast.Name or statement.type_comment):
            raise UnsupportedEquation("only_fresh_local_assignments_modeled")
        name = statement.targets[0].id
        if name in env:
            raise UnsupportedEquation("reassignment_not_modeled")
        sort, value = expression(statement.value)
        alias = "v"+str(len(bindings))
        bindings.append({"name":alias,"sort":sort,"value":value})
        env[name] = sort, alias
    result_sort, result = expression(statements[-1].value)
    return {"parameters":[{"source_name":name,"name":"p"+str(i),
                            "sort":"Int" if name in used_parameters else "opaque"} for i,name in enumerate(names)],
            "bindings":bindings,"result_sort":result_sort,"result":result}


def _expr(value):
    kind = value["kind"]
    if kind == "integer":
        return "("+str(value["value"])+" : Int)"
    if kind == "string":
        return "(String.ofList ["+", ".join("Char.ofNat "+str(c) for c in value["codepoints"])+"])"
    if kind == "name":
        return value["name"]
    if kind == "pos":
        return _expr(value["child"])
    if kind == "neg":
        return "(-"+_expr(value["child"])+")"
    op = {"add":"+", "sub":"-", "mul":"*"}[kind]
    return "("+_expr(value["left"])+" "+op+" "+_expr(value["right"])+")"


def _render(candidate, reference):
    def signature(model):
        generics = ["{T"+str(i)+" : Type}" for i,p in enumerate(model["parameters"]) if p["sort"] == "opaque"]
        params = ["("+p["name"]+" : "+("T"+str(i) if p["sort"] == "opaque" else p["sort"])+")" for i,p in enumerate(model["parameters"])]
        return " ".join(generics+params)
    def body(model):
        return "\n".join(["  let "+v["name"]+" : "+v["sort"]+" := "+_expr(v["value"]) for v in model["bindings"]]+["  "+_expr(model["result"])])
    sig = signature(candidate)
    applied = " ".join(p["name"] for p in candidate["parameters"])
    lines = ["-- Pure source models; Python runtime semantics and security specifications are not asserted.",
             "namespace SecurityEquations", "set_option autoImplicit false", "",
             "def predicted "+sig+" : "+candidate["result_sort"]+" :=", body(candidate), "",
             "def reference "+signature(reference)+" : "+reference["result_sort"]+" :=", body(reference), "",
             "theorem predicted_matches_source_model "+sig+" : predicted "+applied+" = reference "+applied+" := by", "  rfl", "",
             "end SecurityEquations", ""]
    return "\n".join(lines)


def project_security_formula_lean(*, source_bytes, checkpoint, source_path,
                                  model_enabled=True, weight_ablation=None):
    """Execute the frozen learned decoder before emitting source-bound equations."""
    from .security_formula_decoder import decode_security_formula
    decoded = decode_security_formula(source_bytes=source_bytes, checkpoint=checkpoint,
        source_path=source_path, model_enabled=model_enabled, weight_ablation=weight_ablation)
    report = {"schema":SCHEMA,"status":"unsupported","source_sha256":_sha(source_bytes),
              "source_path":source_path,"checkpoint":checkpoint,"decode":decoded,
              "candidate_model":None,"source_model":None,"lean_source":None,
              "learned_equation_count":0,"frontiers":[],"model_equality_verified":False,
              "source_runtime_semantics_verified":False,"security_specification_inferred":False,
              "proof_authority":False,"execution_authority":False,
              "assumptions":["Used parameters are exact built-in Python integers; operator overloading is excluded.",
                  "Unused parameters stay polymorphic; constant strings use Unicode scalar values.",
                  "The equality theorem compares two independently lowered pure models, not executions of Python."]}
    if not decoded["predicted_productions"] or not decoded["validation"]["source_AST_equivalent"]:
        report["frontiers"] = ["no_independently_checked_learned_candidate"]
    else:
        try:
            candidate = _lower(decoded["candidate_source"].encode())
            reference = _lower(source_bytes)
            if candidate != reference:
                raise UnsupportedEquation("candidate_source_models_differ")
            report.update(status="candidate",candidate_model=candidate,source_model=reference,
                          lean_source=_render(candidate,reference),learned_equation_count=1,
                          model_equality_verified=True)
        except (UnsupportedEquation, SyntaxError, ValueError, RecursionError) as exc:
            report["frontiers"] = [str(exc)]
    report["projection_sha256"] = _sha(_wire(report))
    return report


def validate_security_formula_lean(report, *, source_bytes, checkpoint, lake_executable,
                                   timeout_seconds=30):
    """Regenerate with the actual model, then build using an installed native Lake.

    Caller-provided Lean is never executed. An elan shim is refused here to avoid
    accidental toolchain downloads; select its installed toolchain's bin/lake.
    """
    from ....backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
    if type(timeout_seconds) not in (int,float) or not 0 < timeout_seconds <= 60:
        raise ValueError("bounded Lake timeout required")
    expected = project_security_formula_lean(source_bytes=source_bytes, checkpoint=checkpoint,
        source_path=report["source_path"], model_enabled=report["decode"]["model_enabled"],
        weight_ablation=report["decode"]["weight_ablation"])
    if _wire(expected) != _wire(report):
        raise ValueError("projection differs from regenerated learned candidate")
    receipt = {"schema":"security-pure-equations-lake/v1","status":"not_run",
               "projection_sha256":report["projection_sha256"],"backend_executed":False,
               "model_equality_proved":False,"source_runtime_semantics_verified":False,
               "proof_authority":False,"observations":[],"validation_decoder_replays":1}
    if report["status"] != "candidate":
        return receipt
    found = shutil.which(str(lake_executable))
    if found is None:
        receipt.update(status="unavailable",reason="lake_executable_missing")
        return receipt
    executable = Path(found).absolute()
    if executable.parent.name == "bin" and executable.parent.parent.name == ".elan":
        receipt.update(status="unavailable",reason="select_installed_native_lake_not_elan_shim")
        return receipt
    runner = BoundedToolRunner()
    probe = runner.run(ToolRunRequest(argv=(str(executable),"--version"),
        limits=ToolRunLimits(timeout_seconds=5,max_output_bytes=16384)))
    version = re.search(r"Lean version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)",probe.stdout)
    if not probe.ok or not version:
        receipt.update(status="unavailable",reason="native_lake_version_probe_failed")
        return receipt
    toolchain = "leanprover/lean4:v"+version.group(1)
    files = {"lakefile.toml":'name = "security_equations"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "SecurityEquations"\n',
             "lean-toolchain":toolchain+"\n","SecurityEquations.lean":report["lean_source"]}
    command = (str(executable),"build","SecurityEquations")
    run = runner.run(ToolRunRequest(argv=command,input_files=files,environment={"ELAN_TOOLCHAIN":toolchain},
        limits=ToolRunLimits(timeout_seconds=timeout_seconds,cpu_seconds=timeout_seconds,
            max_input_bytes=262144,max_output_bytes=262144,max_workspace_bytes=32*1024*1024)))
    passed = run.ok and not run.output_truncated and not run.workspace_limit_exceeded
    receipt.update(status="passed" if passed else "failed",backend_executed=True,
        model_equality_proved=passed,command=list(command),toolchain=toolchain,
        lean_source_sha256=_sha(report["lean_source"].encode()),
        observations=[{"returncode":run.returncode,"stdout":run.stdout,"stderr":run.stderr,"timed_out":run.timed_out}])
    return receipt
