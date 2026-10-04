"""Kernel-checked AST lowering for a closed source-bound integer profile.

Source grammar and native ProgramIR target are extracted independently. Lean
checks the lowering theorem for every admitted grammar value and Int input,
and the concrete native-target correspondence. Python parsing/capture and
CPython runtime equivalence are outside this theorem; no execution authority
is granted by historical certificates or caller-created records.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import math
import os
import stat
from pathlib import Path
import sys
import time
from typing import Any

from . import codebase_integer_profile as frontend
from . import codebase_finite_integer_observation as native
from . import codebase_integer_model_lean as existing_model
from .codebase_integer_profile import IntegerOffsetContract, compile_integer_offset
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ..backends.process import BoundedToolRunner, ToolRunLimits, BOUNDED_TOOL_RUNNER_VERSION
from ..software_verification.program import ProgramIR
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane,
)

SCHEMA = "codebase-integer-ast-lowering-proof@1"
PROFILE = "guarded-python-integer-offset-ast-lowering@2"
TRANSLATION_SCHEMA = "codebase-integer-ast-lowering-translation@1"
SCOPE = "formal_ast_lowering_correctness"
MAX_LOWERING_OUTPUT_BYTES = 1024 * 1024
_FALSE = {key: False for key in (
    "source_semantics_verified", "runtime_behavior_verified", "behavior_authority",
    "proof_authority", "execution_authority", "completion_authority", "mutation_authority",
    "whole_program_semantics_verified", "cpython_equivalence_proved",
    "source_origin_proved", "training_convergence_proved", "source_parser_correctness_proved",
    "universal_runtime_behavior_proved",
)}
_ARGS = ["-j", "1", "-o", "IntegerLowering.olean", "IntegerLowering.lean"]
_NAMES = {"source": "captured_source.py", "compiled": "compiled.json",
    "translation": "translation.json", "frontend": "frontend.json",
    "manifest": "manifest.json", "source_ast": "source_ast.json",
    "source_syntax": "source_syntax.json", "native_target": "native_target.json",
    "process_policy": "process_policy.json",
    "tool_policy": "tool_policy.json", "lean_source": "IntegerLowering.lean",
    "lean_olean": "IntegerLowering.olean", "lean_process": "lean_process.json",
    "lean_certificate": "lean_certificate.json"}
_RECORD_FIELDS = {"schema", "profile", "scope", "status", "head", "manifest_cid", "source_path",
    "source_cid", "source_sha256", "compiled_cid", "contract", "contract_cid", "translation",
    "translation_cid", "tool_policy", "tool_policy_cid", "process_policy", "process_policy_cid",
    "lean_certificate", "source_ast_semantics_defined", "source_ast_lowering_proved", "native_target_correspondence_proved",
    "requested_model_theorem_proved", "kernel_checked_model", "model_counterexample", "artifacts",
    "output", "result_cid", *_FALSE}
_CERTIFICATE_FIELDS = {"schema", "scope", "translation_cid", "source_cid", "olean_cid", "tool",
    "version_process", "process", "theorems", "dependency_scope", "claim", "process_policy_cid"}
_CERTIFICATE_CLAIM = "Lean kernel proves all closed source-AST grammar lowerings preserve Int evaluation, plus correspondence of the independently reconstructed native target. Captured-byte parsing, CPython/runtime equivalence and physical origin remain unproved; Init imports are trusted."


class IntegerOffsetLoweringError(ValueError):
    """Unsupported translation, invalid binding, or changed checked evidence."""


def _copy(value):
    try:
        raw = canonical_dag_json_bytes(value)
        if len(raw) > native.MAX_WORKSPACE_BYTES:
            raise ValueError("record byte bound")
        return json.loads(raw)
    except (TypeError, ValueError, RecursionError) as error:
        raise IntegerOffsetLoweringError("bounded canonical model record required") from error


@dataclass(frozen=True, slots=True)
class IntegerOffsetLoweringProof:
    """Immutable evidence record; constructing one grants no proof authority."""

    _wire: bytes

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._wire)

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        value = _copy(value)
        if set(value) != _RECORD_FIELDS or value.get("schema") != SCHEMA or value.get("profile") != PROFILE:
            raise IntegerOffsetLoweringError("exact operational model record required")
        return cls(canonical_dag_json_bytes(value))


def _implementation():
    from ..software_verification import program
    from . import cache, content
    identity = frontend._implementation_identity()
    identity["source_sha256"].update({module.__name__: hashlib.sha256(
        Path(module.__file__).read_bytes()).hexdigest()
        for module in (sys.modules[__name__], program, existing_model, cache, content)})
    identity["frontend_python"] = native._tool(Path(sys.executable))
    identity["claim"] = "Selected frontend implementation files; no parser, CPython, or transitive dependency correctness theorem."
    return _copy(identity)


def _need(condition, message):
    if not condition:
        raise IntegerOffsetLoweringError(message)


def _same(left, right):
    """Canonical equality retains bool/int and nested projection distinctions."""
    return canonical_dag_json_bytes(left) == canonical_dag_json_bytes(right)


def _source_syntax(source, contract):
    """Extract source grammar without reading the native translation's tree."""
    _need(type(source) is bytes and 0 < len(source) <= frontend.MAX_SOURCE_BYTES
        and source.isascii() and not any(c < 32 and c not in {9, 10} or c == 127 for c in source),
        "bounded ASCII source required")
    try:
        module = ast.parse(source.decode("ascii"), type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as error:
        raise IntegerOffsetLoweringError("source grammar parse failed") from error
    _need(sum(1 for _ in ast.walk(module)) <= frontend.MAX_AST_NODES
        and len(module.body) == 1 and type(module.body[0]) is ast.FunctionDef
        and not module.type_ignores, "one bounded synchronous source function required")
    function = module.body[0]
    args = function.args
    annotation = lambda node: type(node) is ast.Name and node.id == "int"
    _need(function.name == contract.function_name and not function.decorator_list
        and not function.type_comment and not getattr(function, "type_params", ())
        and annotation(function.returns) and len(args.args) == 1
        and args.args[0].arg == contract.parameter and annotation(args.args[0].annotation)
        and not args.args[0].type_comment and not args.posonlyargs and not args.kwonlyargs
        and not args.vararg and not args.kwarg and not args.defaults and not args.kw_defaults
        and len(function.body) == 1 and type(function.body[0]) is ast.Return,
        "closed typed single-return source function required")
    expression = function.body[0].value
    if type(expression) is ast.Name and expression.id == contract.parameter:
        return {"kind": "identity"}, function
    _need(type(expression) is ast.BinOp and type(expression.op) in {ast.Add, ast.Sub}
        and type(expression.left) is ast.Name and expression.left.id == contract.parameter,
        "source expression is outside the offset grammar")
    literal = expression.right
    kind = "literal"
    if type(literal) is ast.UnaryOp and type(literal.op) in {ast.UAdd, ast.USub}:
        kind = "positive" if type(literal.op) is ast.UAdd else "negative"
        literal = literal.operand
    _need(type(literal) is ast.Constant and type(literal.value) is int
        and literal.value.bit_length() <= frontend.MAX_LITERAL_BITS,
        "source requires a bounded exact signed integer literal")
    return {"kind": "add" if type(expression.op) is ast.Add else "sub",
        "literal": {"kind": kind, "value": literal.value}}, function


def _lower_source(body):
    if body["kind"] == "identity":
        return {"kind": "parameter"}
    literal = body["literal"]
    right = {"kind": "literal", "value": literal["value"]}
    if literal["kind"] != "literal":
        right = {"kind": "pos" if literal["kind"] == "positive" else "neg", "operand": right}
    return {"kind": body["kind"], "left": {"kind": "parameter"}, "right": right}


def _native_target(payload):
    """Reconstruct only the native expression graph, without a source AST."""
    function = payload["functions"][0]
    parameter = function["parameter_symbol_ids"][0]
    command = payload["commands"][0]
    rows = {row["expression_id"]: row for row in payload["expressions"]}
    active, used = set(), set()
    def visit(key, depth=0):
        _need(depth <= 8 and key not in active and key in rows,
            "bounded acyclic native executable expression graph required")
        active.add(key)
        used.add(key)
        row = rows[key]
        _need(row["type_ref"] in {"any", "int"}, "native expression type is outside Int model")
        kind = row["kind"]
        if kind == "symbol":
            _need(row["symbol_ids"] == [parameter] and not row["operand_ids"]
                and not row["evaluation_order"] and not row["operator"] and not row["attributes"],
                "native parameter expression differs")
            value = {"kind": "parameter"}
        elif kind == "literal":
            _need(set(row["attributes"]) == {"value"} and type(row["attributes"]["value"]) is int
                and row["attributes"]["value"].bit_length() <= frontend.MAX_LITERAL_BITS
                and not row["symbol_ids"] and not row["operand_ids"]
                and not row["evaluation_order"] and not row["operator"], "native literal differs")
            value = {"kind": "literal", "value": row["attributes"]["value"]}
        else:
            _need(not row["symbol_ids"] and not row["attributes"]
                and row["evaluation_order"] == row["operand_ids"], "native operation or order differs")
            if kind == "unary":
                _need(row["operator"] in {"neg", "pos"} and len(row["operand_ids"]) == 1,
                    "native unary expression unsupported")
                value = {"kind": row["operator"], "operand": visit(row["operand_ids"][0], depth + 1)}
            else:
                _need(kind == "binary" and row["operator"] in {"add", "sub"}
                    and len(row["operand_ids"]) == 2, "native binary expression unsupported")
                value = {"kind": row["operator"], "left": visit(row["operand_ids"][0], depth + 1),
                    "right": visit(row["operand_ids"][1], depth + 1)}
        active.remove(key)
        return value
    target = visit(command["expression_ids"][0])
    _need(all(key.startswith("expr:pipeline:") for key in set(rows) - used),
        "unaccounted native executable expressions")
    return target, sorted(used)


def _translation(compiled, head, implementation):
    # Reuse existing provenance/shape checking, not its lowered expression.
    checked = existing_model._translation(compiled, head, implementation)
    body, _ = _source_syntax(compiled.source, compiled.contract)
    payload = compiled.pipeline.program.to_dict()
    target, used = _native_target(payload)
    lowered = _lower_source(body)
    _need(target == lowered and used == checked["executable_expression_ids"],
        "independent source grammar and native target differ")
    return {**checked, "schema": TRANSLATION_SCHEMA, "profile": PROFILE, "scope": SCOPE,
        "source_ast_syntax": body, "native_target_syntax": target,
        "lowered_source_syntax": lowered, "source_ast_syntax_cid": cid_for_structured(body),
        "native_target_syntax_cid": cid_for_structured(target),
        "source_ast_lowering_proved": False, "native_target_correspondence_proved": False,
        "translation_correctness_proved": False,
        "claim": "Closed source-AST grammar to mathematical Int target lowering only; byte parsing and CPython/runtime semantics are outside the theorem.",
        **_FALSE}


def _lean(translation):
    def target(tree):
        kind = tree["kind"]
        if kind == "parameter": return "TargetExpr.parameter"
        if kind == "literal": return "(TargetExpr.literal (" + str(tree["value"]) + " : Int))"
        if kind in {"pos", "neg"}:
            return "(TargetExpr." + kind + " " + target(tree["operand"]) + ")"
        return "(TargetExpr." + kind + " " + target(tree["left"]) + " " + target(tree["right"]) + ")"
    body = translation["source_ast_syntax"]
    if body["kind"] == "identity":
        source = "SourceBody.identity"
    else:
        literal = body["literal"]
        source = "(SourceBody." + body["kind"] + " (SignedLiteral." + literal["kind"] + " (" + str(literal["value"]) + " : Int)))"
    actual, desired = translation["source_offset"], translation["requested_offset"]
    evidence = json.dumps(canonical_dag_json_bytes(translation).decode(), ensure_ascii=False)
    definitions = '''inductive SignedLiteral where
  | literal (value : Int)
  | positive (value : Int)
  | negative (value : Int)

inductive SourceBody where
  | identity
  | add (literal : SignedLiteral)
  | sub (literal : SignedLiteral)

inductive TargetExpr where
  | parameter
  | literal (value : Int)
  | add (left right : TargetExpr)
  | sub (left right : TargetExpr)
  | neg (operand : TargetExpr)
  | pos (operand : TargetExpr)

def sourceLiteralEval : SignedLiteral → Int
  | .literal value => value
  | .positive value => value
  | .negative value => -value

def sourceEval : SourceBody → Int → Int
  | .identity, input => input
  | .add literal, input => input + sourceLiteralEval literal
  | .sub literal, input => input - sourceLiteralEval literal

def targetEval : TargetExpr → Int → Int
  | .parameter, input => input
  | .literal value, _ => value
  | .add left right, input => targetEval left input + targetEval right input
  | .sub left right, input => targetEval left input - targetEval right input
  | .neg operand, input => -(targetEval operand input)
  | .pos operand, input => targetEval operand input

def lowerLiteral : SignedLiteral → TargetExpr
  | .literal value => .literal value
  | .positive value => .pos (.literal value)
  | .negative value => .neg (.literal value)

def lower : SourceBody → TargetExpr
  | .identity => .parameter
  | .add literal => .add .parameter (lowerLiteral literal)
  | .sub literal => .sub .parameter (lowerLiteral literal)

theorem signed_literal_lowering_correct : ∀ literal : SignedLiteral, ∀ input : Int,
    targetEval (lowerLiteral literal) input = sourceLiteralEval literal := by
  intro literal input
  cases literal <;> rfl

theorem lowering_correct : ∀ body : SourceBody, ∀ input : Int,
    targetEval (lower body) input = sourceEval body input := by
  intro body input
  cases body with
  | identity => rfl
  | add literal => simp only [lower, targetEval, sourceEval, signed_literal_lowering_correct]
  | sub literal => simp only [lower, targetEval, sourceEval, signed_literal_lowering_correct]
'''
    names = ["signed_literal_lowering_correct", "lowering_correct", "native_target_correspondence",
        "captured_ast_target_equivalence", "source_offset_identity"]
    identity_simp = "run, captured_ast_target_equivalence, capturedSourceBody, sourceEval"
    if body["kind"] != "identity":
        identity_simp += ", sourceLiteralEval"
    lines = ["import Init", "namespace CodebaseIntegerLowering", "set_option autoImplicit false",
        "-- Source-AST grammar theorem only; parsing, physical origin and CPython equivalence remain unproved.",
        "def translationEvidence : String := " + evidence, definitions,
        "def capturedSourceBody : SourceBody := " + source,
        "def nativeTargetExpression : TargetExpr := " + target(translation["native_target_syntax"]),
        "theorem native_target_correspondence : nativeTargetExpression = lower capturedSourceBody := by rfl",
        "theorem captured_ast_target_equivalence : ∀ input : Int, targetEval nativeTargetExpression input = sourceEval capturedSourceBody input := by\n  intro input\n  rw [native_target_correspondence]\n  exact lowering_correct capturedSourceBody input",
        "def run (input : Int) : Int := targetEval nativeTargetExpression input",
        "theorem source_offset_identity : ∀ input : Int, run input = input + (" + str(actual) + " : Int) := by\n  intro input\n  simp only [" + identity_simp + "]\n  <;> omega"]
    if actual == desired:
        lines.append("theorem requested_offset_identity : ∀ input : Int, run input = input + (" + str(desired) + " : Int) := source_offset_identity")
        names.append("requested_offset_identity")
    else:
        lines.extend(["theorem requested_offset_counterexample : run (0 : Int) ≠ (0 : Int) + (" + str(desired) + " : Int) := by\n  simp only [run, nativeTargetExpression, targetEval]\n  decide",
            "theorem requested_goal_refuted : ¬ (∀ input : Int, run input = input + (" + str(desired) + " : Int)) := by\n  intro claimed\n  exact requested_offset_counterexample (claimed 0)"])
        names.extend(["requested_offset_counterexample", "requested_goal_refuted"])
    return ("\n\n".join(lines + ["end CodebaseIntegerLowering", ""]).encode(), names)

def _read_bytes(path, bound, checkpoint):
    """Bound one physical read, checking atomic replacement before returning."""
    checkpoint()
    _need(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(),
        "canonical regular custody path required")
    def witness(value):
        return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        _need(stat.S_ISREG(before.st_mode) and before.st_size <= bound, "custody file bound exceeded")
        chunks, size = [], 0
        while raw := os.read(descriptor, min(65536, bound + 1 - size)):
            size += len(raw)
            _need(size <= bound, "custody file bound exceeded")
            chunks.append(raw)
            checkpoint()
        _need(witness(before) == witness(os.fstat(descriptor)) == witness(os.stat(path, follow_symlinks=False)),
            "custody file changed or was replaced during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _source_fence(index, repository, head, manifest, contract, source, checkpoint):
    """Check selected current source/AST and roots after all observer callbacks.

    This is a selected-source closure, not full repository or OS atomicity.
    Current SQL checks precede direct no-follow file/CAS reads.
    """
    checkpoint()
    _need(index.catalog.current(head.repository_id) == head, "current source head changed")
    entry = next(item for item in manifest.snapshot.entries if item.path == contract.path)
    unit = next(item for item in manifest.units if item.source_key == entry.source_key)
    projection = index.lookup(manifest, contract.path)
    _need(unit.ast_cid is not None and projection is not None
        and projection.ast_cid == unit.ast_cid and projection.source_cid == entry.source_cid,
        "current selected AST projection differs")
    manifest_raw = _read_bytes(index.artifacts.path_for(manifest.cid), native.MAX_WORKSPACE_BYTES, checkpoint)
    _need(manifest_raw == canonical_dag_json_bytes(manifest.to_dict()), "selected manifest CAS changed")
    ast_raw = _read_bytes(index.artifacts.path_for(unit.ast_cid), native.MAX_WORKSPACE_BYTES, checkpoint)
    _need(cid_for_structured(json.loads(ast_raw)) == unit.ast_cid
        and canonical_dag_json_bytes(json.loads(ast_raw)) == ast_raw, "selected AST CAS changed")
    _need(_read_bytes(index.artifacts.path_for(entry.source_cid, source=True), frontend.MAX_SOURCE_BYTES, checkpoint) == source,
        "selected source CAS changed")
    _need(_read_bytes(repository / contract.path, frontend.MAX_SOURCE_BYTES, checkpoint) == source,
        "current selected source bytes changed")
    checkpoint()
    return manifest_raw, ast_raw


def _verify_artifacts(value, index, checkpoint):
    output = Path(value["output"])
    _need(output.is_absolute() and output.resolve(strict=True) == output and not output.is_symlink(), "model output directory changed")
    _need(set(value["artifacts"]) == set(_NAMES), "model artifact population differs")
    for key, descriptor in value["artifacts"].items():
        checkpoint()
        path = output / _NAMES[key]
        _need(set(descriptor) == {"path", "sha256", "size_bytes", "cid"}
            and type(descriptor["size_bytes"]) is int and descriptor["size_bytes"] >= 0
            and descriptor["path"] == str(path) and not path.is_symlink()
            and path.resolve(strict=True) == path and path.is_file(), "model artifact path changed")
        raw = _read_bytes(path, native.MAX_WORKSPACE_BYTES, checkpoint)
        _need(descriptor["sha256"] == hashlib.sha256(raw).hexdigest()
            and descriptor["size_bytes"] == len(raw) and descriptor["cid"] == cid_for_bytes(raw)
            and _read_bytes(index.artifacts.path_for(descriptor["cid"], source=True),
                native.MAX_WORKSPACE_BYTES, checkpoint) == raw, "sealed model artifact changed")
    checkpoint()


def _verify_result(record, index, checkpoint):
    _need(_read_bytes(Path(record.to_dict()["output"]) / "result.json", native.MAX_WORKSPACE_BYTES, checkpoint) == record._wire
        and _read_bytes(index.artifacts.path_for(record.cid), native.MAX_WORKSPACE_BYTES, checkpoint) == record._wire
        and _read_bytes(index.artifacts.path_for(cid_for_bytes(record._wire), source=True),
            native.MAX_WORKSPACE_BYTES, checkpoint) == record._wire, "sealed lowering result changed")


def _process_policy(policy):
    """Bind the new bounded capture allowance without changing the old policy.

    Actual generic-lowering oleans exceeded the old finite-table 256 KiB
    output bound. This profile binds its separate 1 MiB allowance, retaining
    selected tools, memory/input/workspace and deadline bounds.
    """
    return _copy({"schema": "codebase-integer-ast-lowering-process-policy@2", "profile": PROFILE,
        "base_tool_policy_cid": policy["policy_cid"],
        "override": {"max_output_bytes": MAX_LOWERING_OUTPUT_BYTES},
        "max_input_bytes": native.MAX_IO_BYTES, "max_output_bytes": MAX_LOWERING_OUTPUT_BYTES,
        "max_workspace_bytes": native.MAX_WORKSPACE_BYTES, "max_output_files": 8,
        "address_space_bytes": policy["process_limits"]["lean"]["address_space_bytes"],
        "resident_memory_bytes": policy["process_limits"]["lean"]["resident_memory_bytes"],
        "cpu_slots": 1, "child_process_slots": 1, "reserved_child_memory_mb": 512,
        "maximum_timeout_ms": 90000, "maximum_cpu_seconds": 90,
        "lean_arguments": list(_ARGS), "environment": dict(native._ENV),
        "reason": "The generic source/target datatypes and lowering theorem exceed the prior finite-table compiled-output cap."})


def _successful_process(process, arguments, policy):
    flags = {"timed_out", "cancelled", "unavailable", "output_truncated",
        "workspace_limit_exceeded", "process_tree_terminated", "resource_exhausted", "workspace_cleaned"}
    fields = {"interface_version", "command", "returncode", "stdout", "stderr", "elapsed_ms",
        "limits", "termination_reason", "error", *flags}
    _need(type(process) is dict and set(process) == fields
        and process["interface_version"] == BOUNDED_TOOL_RUNNER_VERSION
        and type(process["command"]) is list and process["command"] == [policy["lean"]["path"], *arguments]
        and type(process["returncode"]) is int and process["returncode"] == 0
        and type(process["elapsed_ms"]) is int and process["elapsed_ms"] >= 0
        and all(type(process[key]) is str for key in ("stdout", "stderr", "termination_reason", "error"))
        and process["stderr"] == process["error"] == ""
        and process["termination_reason"] == "completed"
        and all(type(process[key]) is bool for key in flags)
        and process["workspace_cleaned"] is True
        and all(process[key] is False for key in flags - {"workspace_cleaned"}),
        "exact successful bounded lowering process required")
    limits = process["limits"]
    expected = {"address_space_bytes": policy["process_limits"]["lean"]["address_space_bytes"],
        "resident_memory_bytes": policy["process_limits"]["lean"]["resident_memory_bytes"],
        "max_input_bytes": native.MAX_IO_BYTES, "max_output_bytes": MAX_LOWERING_OUTPUT_BYTES,
        "max_workspace_bytes": native.MAX_WORKSPACE_BYTES, "max_output_files": 8}
    _need(type(limits) is dict and set(limits) == {*expected, "timeout_ms", "cpu_seconds"}
        and all(type(item) is int and item > 0 for item in limits.values())
        and all(limits[key] == value for key, value in expected.items())
        and limits["timeout_ms"] <= 90000 and limits["cpu_seconds"] <= 90,
        "exact bounded lowering process limits required")


def _controls(index, repository, expected_head, contract, timeout_seconds, memory_mb):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    _need(type(index) is RepositoryCodebaseIndex and index.catalog is not None and index.artifacts is not None
        and index.catalog.store is index.ingestor.store and index.catalog.artifacts is index.artifacts
        and type(expected_head) is CodebaseHead and type(contract) is IntegerOffsetContract,
        "exact native index, head and integer contract required")
    _need(type(timeout_seconds) in {int, float} and math.isfinite(timeout_seconds)
        and 0 < timeout_seconds <= 90 and type(memory_mb) is int and memory_mb >= 1024,
        "model check requires deadline at most 90 seconds and at least 1024 MiB")
    repository = Path(repository)
    _need(repository.is_absolute() and repository.resolve(strict=True) == repository and not repository.is_symlink(),
          "canonical repository required")
    return repository, CodebaseHead.from_dict(expected_head.to_dict()), IntegerOffsetContract.from_dict(contract.to_dict())


def prove_current_integer_offset_lowering(index, repository, *, expected_head, contract,
        tool_policy, output: Path, scheduler=None, parent_lease=None, cancel_event=None,
        timeout_seconds=60, memory_mb=1024) -> IntegerOffsetLoweringProof:
    """Run native Lean on a freshly captured, guarded operational model.

    Unsupported source and all stale/failed checks raise without returning a
    proof record. The desired offset is always retained, including refutation.
    """
    repository, expected_head, contract = _controls(index, repository, expected_head, contract, timeout_seconds, memory_mb)
    _need(isinstance(output, Path) and output.is_absolute() and output.resolve() == output
        and not output.exists() and not output.is_relative_to(repository), "fresh external canonical output required")
    policy = _copy(tool_policy)
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set(): raise LeaseCancelledError("integer lowering check cancelled")
            duration = deadline - time.monotonic()
            if duration <= 0: raise LeaseTimeoutError("integer lowering deadline exceeded")
            return duration
        policy = native._policy(policy, remaining)
        process_policy = _process_policy(policy)
        implementation = _implementation()
        def observe():
            duration = remaining()
            return index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, admission_timeout_seconds=min(30, duration),
                timeout_seconds=duration, memory_mb=512)
        current = observe()
        entry = next((item for item in current.manifest.snapshot.entries if item.path == contract.path), None)
        _need(entry is not None and not entry.is_opaque, "selected source absent or opaque")
        source = index.artifacts.get_bytes(entry.source_cid)
        compiled = compile_integer_offset(source, contract, revision="snapshot:" + expected_head.snapshot_cid)
        translation = _translation(compiled, expected_head, implementation)
        _need(compiled.source_cid == entry.source_cid, "current captured source identity differs")
        manifest_raw, ast_raw = _source_fence(index, repository, expected_head,
            current.manifest, contract, source, remaining)
        text, names = _lean(translation)
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        artifacts = {}
        def save(key, raw):
            descriptor = native._artifact(output, _NAMES[key], raw)
            _need(index.artifacts.put_bytes(raw) == descriptor["cid"], "model CAS artifact identity differs")
            artifacts[key] = descriptor
        for key, raw in (("source", source), ("compiled", canonical_dag_json_bytes(compiled.to_dict())),
                ("manifest", manifest_raw), ("source_ast", ast_raw),
                ("source_syntax", canonical_dag_json_bytes(translation["source_ast_syntax"])),
                ("native_target", canonical_dag_json_bytes(translation["native_target_syntax"])),
                ("process_policy", canonical_dag_json_bytes(process_policy)),
                ("translation", canonical_dag_json_bytes(translation)), ("frontend", canonical_dag_json_bytes(implementation)),
                ("tool_policy", canonical_dag_json_bytes(policy)), ("lean_source", text)):
            save(key, raw)
        def fence():
            observe()
            native._policy(policy, remaining)
            _need(_implementation() == implementation, "model frontend implementation changed")
            for key, descriptor in artifacts.items():
                raw = _read_bytes(output / _NAMES[key], native.MAX_WORKSPACE_BYTES, remaining)
                _need(cid_for_bytes(raw) == descriptor["cid"]
                    and _read_bytes(index.artifacts.path_for(descriptor["cid"], source=True),
                        native.MAX_WORKSPACE_BYTES, remaining) == raw, "sealed lowering artifact changed")
            _source_fence(index, repository, expected_head, current.manifest, contract, source, remaining)
            remaining()
        runner = BoundedToolRunner(base_environment=native._ENV)
        def run(arguments, files, outputs=()):
            fence()
            with lease.acquire_child(lane=ResourceLane.VALIDATION, cpu_slots=1, memory_mb=512,
                    child_process_slots=1, timeout=remaining(), cancel_event=signal,
                    request_id="codebase-integer-lowering:lean") as child:
                limits = ToolRunLimits(timeout_seconds=remaining(), cpu_seconds=max(1, math.ceil(remaining())),
                    memory_bytes=policy["process_limits"]["lean"]["address_space_bytes"],
                    resident_memory_bytes=policy["process_limits"]["lean"]["resident_memory_bytes"],
                    max_input_bytes=native.MAX_IO_BYTES, max_output_bytes=MAX_LOWERING_OUTPUT_BYTES,
                    max_workspace_bytes=native.MAX_WORKSPACE_BYTES, max_output_files=8)
                raw = runner.run([policy["lean"]["path"], *arguments], input_files=files,
                    output_paths=outputs, limits=limits, cancellation=child.combined_cancellation_signal(signal))
                if raw.cancelled or signal.is_set(): raise LeaseCancelledError("native lowering Lean cancelled")
            fence()
            process = native._process(raw, {"timeout_ms": math.ceil(limits.timeout_seconds * 1000),
                "cpu_seconds": limits.cpu_seconds, "address_space_bytes": limits.memory_bytes,
                "resident_memory_bytes": limits.resident_memory_bytes,
                "max_input_bytes": limits.max_input_bytes, "max_output_bytes": limits.max_output_bytes,
                "max_workspace_bytes": limits.max_workspace_bytes, "max_output_files": limits.max_output_files})
            return raw, process
        version, version_process = run(["--version"], {})
        checked, process = run(_ARGS, {"IntegerLowering.lean": text}, ("IntegerLowering.olean",))
        successful = (native._success(version) and version.stdout.startswith("Lean (version ")
            and native._success(checked) and not checked.stdout and bool(checked.output_files.get("IntegerLowering.olean"))
        )
        # Retain failed native process output/cost without publishing a proof.
        if not successful:
            failed_outputs = {}
            for name, raw in checked.output_files.items():
                descriptor = native._artifact(output, "failed-" + name, raw)
                index.artifacts.put_bytes(raw)
                failed_outputs[name] = descriptor
            diagnostic = {"schema": "codebase-integer-ast-lowering-native-failure@1",
                "profile": PROFILE, "status": "failed", "scope": SCOPE,
                "version_process": version_process, "process": process,
                "retained_outputs": failed_outputs, "output_bytes_may_be_truncated": checked.output_truncated,
                "frontend": implementation, "tool_policy": policy,
                "process_policy": process_policy, "process_policy_cid": cid_for_structured(process_policy), **_FALSE}
            raw = canonical_dag_json_bytes(diagnostic)
            native._artifact(output, "lean_failure.json", raw)
            index.artifacts.put_bytes(raw)
            raise IntegerOffsetLoweringError("native Lean lowering check failed: " + checked.stderr[:2048]
                + "; output_truncated=" + str(checked.output_truncated))
        _successful_process(version_process, ["--version"], policy)
        _successful_process(process, _ARGS, policy)
        save("lean_olean", checked.output_files["IntegerLowering.olean"])
        certificate = {"schema": "codebase-integer-ast-lowering-certificate@1", "scope": SCOPE,
            "translation_cid": cid_for_structured(translation), "source_cid": cid_for_bytes(text),
            "olean_cid": artifacts["lean_olean"]["cid"], "tool": policy["lean"],
            "version_process": version_process, "process": process, "theorems": names,
            "process_policy_cid": cid_for_structured(process_policy),
            "dependency_scope": policy["dependency_scope"],
            "claim": _CERTIFICATE_CLAIM}
        save("lean_process", canonical_dag_json_bytes({"version_process": version_process, "process": process}))
        save("lean_certificate", canonical_dag_json_bytes(certificate))
        matches = compiled.body_offset == contract.offset
        value = {"schema": SCHEMA, "profile": PROFILE, "scope": SCOPE,
            "status": "model_proved" if matches else "model_refuted", "head": expected_head.to_dict(),
            "manifest_cid": current.manifest.cid, "source_path": contract.path, "source_cid": entry.source_cid,
            "source_sha256": hashlib.sha256(source).hexdigest(), "compiled_cid": compiled.cid,
            "contract": contract.to_dict(), "contract_cid": contract.cid,
            "translation": translation, "translation_cid": cid_for_structured(translation),
            "tool_policy": policy, "tool_policy_cid": policy["policy_cid"], "lean_certificate": certificate,
            "process_policy": process_policy, "process_policy_cid": cid_for_structured(process_policy),
            "source_ast_semantics_defined": True, "source_ast_lowering_proved": True,
            "native_target_correspondence_proved": True, "requested_model_theorem_proved": matches, "kernel_checked_model": True,
            "model_counterexample": None if matches else {"input": 0, "model_output": compiled.body_offset,
                "required_output": contract.offset}, "artifacts": artifacts, "output": str(output), **_FALSE}
        fence()
        value["result_cid"] = cid_for_structured(value)
        record = IntegerOffsetLoweringProof.from_dict(value)
        index.artifacts.put(record.to_dict())
        index.artifacts.put_bytes(record._wire)
        native._artifact(output, "result.json", record._wire)
        # CAS writes, output writes and the final native observer are all fences.
        fence()
        _verify_artifacts(value, index, remaining)
        _verify_result(record, index, remaining)
        _source_fence(index, repository, expected_head, current.manifest, contract, source, remaining)
        remaining()
        return record


def validate_current_integer_offset_lowering(record, index, repository, *, expected_head,
        contract, tool_policy, scheduler=None, parent_lease=None, cancel_event=None,
        timeout_seconds=60, memory_mb=1024) -> IntegerOffsetLoweringProof:
    """Cold-read exact source, frontend, native model and sealed certificates.

    This does not invoke Lean or confer evidence-origin authority on a caller
    record. Consumers must retain the result of their actual proving call.
    """
    repository, expected_head, contract = _controls(index, repository, expected_head, contract, timeout_seconds, memory_mb)
    _need(type(record) is IntegerOffsetLoweringProof, "typed operational model record required")
    value = record.to_dict()
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set(): raise LeaseCancelledError("integer lowering cold validation cancelled")
            duration = deadline - time.monotonic()
            if duration <= 0: raise LeaseTimeoutError("integer lowering cold validation deadline exceeded")
            return duration
        def observe():
            duration = remaining()
            return index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, admission_timeout_seconds=min(30, duration), timeout_seconds=duration, memory_mb=512)
        policy = native._policy(tool_policy, remaining)
        process_policy = _process_policy(policy)
        current = observe()
        _need(set(value) == _RECORD_FIELDS and value.get("schema") == SCHEMA and value.get("profile") == PROFILE and value.get("scope") == SCOPE
            and _same(value.get("head"), expected_head.to_dict()) and value.get("manifest_cid") == current.manifest.cid
            and _same(value.get("contract"), contract.to_dict()) and value.get("contract_cid") == contract.cid
            and value.get("source_path") == contract.path and _same(value.get("tool_policy"), policy)
            and value.get("tool_policy_cid") == policy["policy_cid"]
            and _same(value.get("process_policy"), process_policy)
            and value.get("process_policy_cid") == cid_for_structured(value["process_policy"]) == cid_for_structured(process_policy)
            and all(value.get(key) is False for key in _FALSE), "model record roots, policy, or authority differ")
        _need(value.get("result_cid") == cid_for_structured({key: item for key, item in value.items() if key != "result_cid"}),
              "model result identity differs")
        entry = next((item for item in current.manifest.snapshot.entries if item.path == contract.path), None)
        _need(entry is not None and not entry.is_opaque and entry.source_cid == value["source_cid"], "current model source differs")
        source = index.artifacts.get_bytes(entry.source_cid)
        implementation = _implementation()
        compiled = compile_integer_offset(source, contract, revision="snapshot:" + expected_head.snapshot_cid)
        translation = _translation(compiled, expected_head, implementation)
        manifest_raw, ast_raw = _source_fence(index, repository, expected_head,
            current.manifest, contract, source, remaining)
        _need(_same(value["translation"], translation)
            and value["translation_cid"] == cid_for_structured(value["translation"]) == cid_for_structured(translation)
            and value["compiled_cid"] == compiled.cid and value["source_sha256"] == hashlib.sha256(source).hexdigest(),
            "cold native model translation differs")
        text, names = _lean(translation)
        certificate = value["lean_certificate"]
        _need(type(certificate) is dict and set(certificate) == _CERTIFICATE_FIELDS
            and certificate["schema"] == "codebase-integer-ast-lowering-certificate@1"
            and certificate["theorems"] == names and certificate["scope"] == SCOPE
            and certificate["translation_cid"] == value["translation_cid"] and _same(certificate["tool"], policy["lean"])
            and certificate["process_policy_cid"] == value["process_policy_cid"]
            and certificate["dependency_scope"] == policy["dependency_scope"] and certificate["claim"] == _CERTIFICATE_CLAIM
            and certificate["source_cid"] == cid_for_bytes(text)
            and certificate["olean_cid"] == value["artifacts"]["lean_olean"]["cid"], "model certificate bindings differ")
        for process, arguments in ((certificate["version_process"], ["--version"]), (certificate["process"], _ARGS)):
            _successful_process(process, arguments, policy)
        _need(certificate["version_process"]["stdout"].startswith("Lean (version ")
            and not certificate["process"]["stdout"], "model native version or compiler output differs")
        matches = compiled.body_offset == contract.offset
        _need(value["source_ast_semantics_defined"] is True and value["source_ast_lowering_proved"] is True
            and value["native_target_correspondence_proved"] is True and value["kernel_checked_model"] is True
            and value["requested_model_theorem_proved"] is matches
            and value["status"] == ("model_proved" if matches else "model_refuted")
            and _same(value["model_counterexample"], (None if matches else {"input": 0,
                "model_output": compiled.body_offset, "required_output": contract.offset})), "model goal verdict differs")
        _verify_artifacts(value, index, remaining)
        expected_bytes = {"source": source, "compiled": canonical_dag_json_bytes(compiled.to_dict()),
            "manifest": manifest_raw, "source_ast": ast_raw,
            "source_syntax": canonical_dag_json_bytes(translation["source_ast_syntax"]),
            "native_target": canonical_dag_json_bytes(translation["native_target_syntax"]),
            "process_policy": canonical_dag_json_bytes(process_policy),
            "translation": canonical_dag_json_bytes(translation), "frontend": canonical_dag_json_bytes(implementation),
            "tool_policy": canonical_dag_json_bytes(policy), "lean_source": text,
            "lean_certificate": canonical_dag_json_bytes(certificate),
            "lean_process": canonical_dag_json_bytes({"version_process": certificate["version_process"], "process": certificate["process"]})}
        _need(all(index.artifacts.get_bytes(value["artifacts"][key]["cid"]) == raw for key, raw in expected_bytes.items()),
              "model artifact content does not replay")
        _verify_result(record, index, remaining)
        observe()
        native._policy(policy, remaining)
        _need(_implementation() == implementation, "model frontend changed during cold validation")
        _verify_artifacts(value, index, remaining)
        _verify_result(record, index, remaining)
        _source_fence(index, repository, expected_head, current.manifest, contract, source, remaining)
        remaining()
        return record


__all__ = ["SCHEMA", "PROFILE", "SCOPE", "IntegerOffsetLoweringError", "IntegerOffsetLoweringProof",
    "prove_current_integer_offset_lowering", "validate_current_integer_offset_lowering"]
