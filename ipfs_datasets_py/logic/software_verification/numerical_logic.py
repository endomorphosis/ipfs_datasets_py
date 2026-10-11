"""Opt-in numerical structure to source-bound, unresolved logic obligations.

The native ProgramIR bridge, many-sorted FOL syntax kernel and shared SMT
compiler own the representations. NumPy calls remain opaque. Mathematical
obligation templates are *not* assumptions or claims about Python execution.
This preparation API runs neither a solver nor source code nor a model.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from ..backends.smt.compiler import (
    SoftwareVerificationSMTCompiler, SmtTerm, term_int, term_symbol,
)
from ..families.registry import build_default_registry
from ..syntax_core.ast import TypedExpression, mk_constant, mk_predicate
from ..syntax_core.signatures import atomic_sort, many_sorted_fol_signature
from .syntax_bridge import SoftwareVerificationSyntaxBridge

PROFILE = "python-numerical-structure@1"
SCHEMA = "numerical-source-logic/v1"
MAX_OBLIGATIONS = 256
MAX_REPORT_BYTES = 8 * 1024 * 1024
_FALSE = dict(proof_authority=False, source_semantics_verified=False,
    whole_program_semantics_verified=False, completion_authority=False,
    execution_authority=False, source_executed=False, model_inference_executed=False)


class NumericalLogicError(ValueError):
    """Invalid or stale numerical structural evidence."""


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise NumericalLogicError("inert bounded numerical logic JSON required") from exc
    if len(raw) > MAX_REPORT_BYTES:
        raise NumericalLogicError("numerical logic report exceeds byte bound")
    return raw


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def describe_numerical_logic_profile():
    """Resolve existing families; SMT and Lean are encodings, not new families."""
    registry = build_default_registry()
    unsupported = {
        "transition_system": "No reviewed numerical transition relation; TLA+ is not generated from a CFG alone.",
        "temporal": "No source-grounded temporal specification or trace semantics.",
        "separation_logic": "No reviewed heap, aliasing or ownership model.",
        "concurrency": "No thread/interference semantics.",
        "hyperproperty": "No explicit information-flow policy and trace relation.",
        "refinement": "No reviewed numerical implementation/specification refinement relation.",
        "horn_chc": "No complete numerical verification-condition semantics.",
        "frame_logic": "No reviewed object/frame interpretation.",
        "dcec": "No supplied cognitive, normative or event interpretation.",
        "tdfol": "No supplied temporal/normative interpretation.",
    }
    for family in ("program", "first_order", "higher_order", *unsupported):
        registry.resolve(family)
    return dict(profile=PROFILE, schema=SCHEMA, opt_in=True,
        routes=[dict(family="program", encoding="ProgramIR", status="structural_only",
                     owner=SoftwareVerificationSyntaxBridge.INTERFACE),
                dict(family="first_order", encoding="TypedExpression", status="pending_predicates"),
                dict(family="first_order", encoding="SMT-LIB", status="pending_abstract_integer_constraints",
                     owner=SoftwareVerificationSMTCompiler.INTERFACE),
                dict(family="higher_order", encoding="Lean4", status="definitions_and_conditional_lemmas")],
        unsupported_families=[dict(family=k, status="unsupported", reason=v)
                              for k, v in unsupported.items()],
        contract_vc_status="unsupported_without_reviewed_numerical_semantics",
        solver_calls=0, provider_calls=0, **_FALSE)


def _reachable_functions(program):
    expressions = {x.expression_id: x for x in program.expressions}
    commands = {x.command_id: x for x in program.commands}
    owners = {}
    for function in program.functions:
        pending = [key for block in function.cfg.blocks for cid in block.command_ids
                   for key in commands[cid].expression_ids]
        seen = set()
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            owners.setdefault(key, set()).add(function.function_id)
            pending.extend(expressions[key].operand_ids)
    return owners


def _derive_obligations(program):
    owners = _reachable_functions(program)
    expressions = {x.expression_id: x for x in program.expressions}
    rows = []

    def add(kind, expression, reason, roles=None):
        row = dict(kind=kind, expression_id=expression.expression_id,
            source_ref_ids=list(expression.source_ref_ids), span_ids=list(expression.span_ids),
            function_ids=sorted(owners.get(expression.expression_id, ())),
            roles=roles or {}, status="pending", reason=reason,
            assumptions_asserted=False, source_binding_is_semantic_proof=False, **_FALSE)
        row["obligation_id"] = "numerical:" + _sha(row)[:32]
        rows.append(row)

    for expression in program.expressions:
        attrs = expression.attributes.to_dict()
        if expression.kind.value == "index":
            index = expressions[expression.operand_ids[1]]
            indices = (index.operand_ids if index.attributes.to_dict().get("call_kind") == "python.tuple"
                       else (index.expression_id,))
            for axis, key in enumerate(indices):
                item = expressions[key]
                kind = ("slice_safety" if item.attributes.to_dict().get("call_kind") == "python.slice"
                        else "indexing_semantics" if item.type_ref in {
                            "python.list", "python.tuple", "python.literal.NoneType",
                            "python.literal.str", "python.literal.bool", "python.literal.float"}
                        else "index_safety")
                add(kind, expression,
                    "Resolve receiver type, rank, axis, scalar/slice/advanced-index semantics and actual extent before discharge.",
                    dict(receiver_expression=expression.operand_ids[0], index_expression=key,
                         syntactic_axis=axis, actual_axis_interpretation="pending"))
        if expression.kind.value != "call" or attrs.get("call_kind") != "python.call":
            continue
        add("library_semantics_and_effects", expression,
            "Call result, exceptions, dispatch, mutation and aliasing remain opaque; imported names do not prove runtime identity.",
            dict(callee_expression=expression.operand_ids[0],
                 imported_callee=attrs.get("imported_callee"),
                 qualified_callee=attrs.get("qualified_callee")))
        if attrs.get("callee_resolution") != "declared_import":
            continue
        callee = attrs.get("imported_callee")
        args = expression.operand_ids[1:]
        count = attrs.get("positional_count", 0)
        # Only a directly identifiable input supports a numerical library
        # obligation. Unresolved dynamic receivers do not inherit NumPy types.
        array = args[0] if count else None
        if array is None and "a" in attrs.get("keyword_names", ()):
            array = args[count + attrs["keyword_names"].index("a")]
        if array is None:
            continue
        roles = dict(input_expression=array, result_expression=expression.expression_id,
                     imported_callee=callee)
        if callee in {"numpy.linalg.eig", "numpy.linalg.eigh"}:
            add("matrix_shape", expression,
                "Bind actual ndarray rank and trailing dimensions; mathematical square-matrix template does not establish dtype or runtime shape.", roles)
            add("eigenpair_residual", expression,
                "Choose real/complex arithmetic, finite/nonfinite and tolerance policy; bind each output eigenpair and prove library/source refinement.", roles)
        if callee in {"numpy.argsort", "numpy.argmax", "numpy.argmin"}:
            add("selection", expression,
                "Resolve axis, ordering key, permutation/extremum, tie, NaN and complex policies before identifying a selected result.", roles)
    if len(rows) > MAX_OBLIGATIONS:
        raise NumericalLogicError("numerical obligation count exceeds bound")
    return rows


def _fol(row):
    # These are explicit unresolved predicates over source expression identities.
    # There is no axiom asserting any predicate, nor an invented entity referent.
    sort = atomic_sort("SourceExpression")
    signature = many_sorted_fol_signature("sig:" + row["obligation_id"],
        sorts=(sort,), constants=(("source_expression", sort),),
        predicates=((row["kind"], (sort,)),))
    expression = TypedExpression("fol:" + row["obligation_id"],
        mk_predicate("node:obligation", row["kind"],
            (mk_constant("node:source", "source_expression", sort),)), signature,
        metadata=dict(source_expression_id=row["expression_id"],
                      obligation_id=row["obligation_id"], status="pending"))
    return dict(obligation_id=row["obligation_id"], expression=expression.to_dict(),
                predicate_interpretation="unresolved; no axiom asserted", **_FALSE)


def _smt(row):
    # The shared compiler produces goals with *no assumptions*. A check-sat
    # command is an artifact only; no solver runs here. Abstract symbols are not
    # silently equated with Python values, dimensions, or NumPy array effects.
    if row["kind"] == "index_safety":
        extent, index = term_symbol("extent"), term_symbol("index")
        goal = SmtTerm("and", arguments=(
            SmtTerm("ge", arguments=(extent, term_int(0))),
            SmtTerm("and", arguments=(
                SmtTerm("le", arguments=(SmtTerm("neg", arguments=(extent,)), index)),
                SmtTerm("lt", arguments=(index, extent))))))
        symbols = ("extent", "index")
        prerequisites = ["actual builtin integer scalar index", "selected concrete axis extent",
                         "reviewed ndarray indexing and source-value interpretation"]
    elif row["kind"] == "matrix_shape":
        rows, columns = term_symbol("rows"), term_symbol("columns")
        goal = SmtTerm("and", arguments=(
            SmtTerm("ge", arguments=(rows, term_int(0))),
            SmtTerm("and", arguments=(SmtTerm("ge", arguments=(columns, term_int(0))),
                                      SmtTerm("eq", arguments=(rows, columns))))))
        symbols = ("rows", "columns")
        prerequisites = ["actual ndarray rank at least two", "trailing matrix axes bound to abstract rows/columns",
                         "reviewed dtype and batch semantics"]
    else:
        return None
    compiler = SoftwareVerificationSMTCompiler()
    result = compiler.compile_arithmetic_goal(obligation_id=row["obligation_id"],
        goal=goal, symbols=symbols, assumptions=(), request_unsat_core=False)
    return dict(obligation_id=row["obligation_id"], status="pending",
        interpretation_prerequisites=prerequisites, compilation=result.to_dict(),
        solver_executed=False, discharged=False, **_FALSE)


_LEAN_BASE = """import Std

namespace NumericalObligations

-- Specifications only: no declaration below asserts a property of Python.
def IndexSafety (extent : Nat) (index : Int) : Prop :=
  -(Int.ofNat extent) ≤ index ∧ index < Int.ofNat extent

def MatrixShape (rows columns : Nat) : Prop := rows = columns

def SelectionMax {α : Type} (le : α → α → Prop)
    (n : Nat) (score : Nat → α) (selected : Nat) : Prop :=
  selected < n ∧ ∀ j, j < n → le (score j) (score selected)

def SelectionMin {α : Type} (le : α → α → Prop)
    (n : Nat) (score : Nat → α) (selected : Nat) : Prop :=
  selected < n ∧ ∀ j, j < n → le (score selected) (score j)

def Ordering {α : Type} (le : α → α → Prop)
    (n : Nat) (score : Nat → α) (order : Nat → Nat) : Prop :=
  (∀ i, i < n → order i < n) ∧
  (∀ i, i < n → ∀ j, j < n → order i = order j → i = j) ∧
  (∀ i, i + 1 < n → le (score (order i)) (score (order (i + 1))))

def finiteSum {α : Type} (zero : α) (add : α → α → α)
    (term : Nat → α) : Nat → α
  | 0 => zero
  | n + 1 => add (finiteSum zero add term n) (term n)

def EigenpairResidual {α : Type} (zero : α) (add mul : α → α → α)
    (n : Nat) (matrix : Nat → Nat → α) (vector : Nat → α) (value : α) : Prop :=
  ∀ i, i < n → finiteSum zero add (fun j => mul (matrix i j) (vector j)) n =
    mul value (vector i)

def NormalizeIndex (extent : Nat) (index : Int) : Int :=
  if index < 0 then index + Int.ofNat extent else index

-- Conditional arithmetic lemmas; their premises are not established for source values.
theorem normalized_index_bounds (extent : Nat) (index : Int)
    (bounds : IndexSafety extent index) :
    0 ≤ NormalizeIndex extent index ∧ NormalizeIndex extent index < Int.ofNat extent := by
  unfold IndexSafety at bounds
  unfold NormalizeIndex
  split <;> omega

theorem last_index_bound (extent : Nat) (nonempty : 0 < extent) : extent - 1 < extent := by
  omega
"""


def _lean(rows):
    definitions = {"index_safety": "IndexSafety", "matrix_shape": "MatrixShape",
                   "eigenpair_residual": "EigenpairResidual"}
    bindings = []
    lines = [_LEAN_BASE]
    for row in rows:
        definition = definitions.get(row["kind"])
        if row["kind"] == "selection":
            definition = {"numpy.argmax": "SelectionMax", "numpy.argmin": "SelectionMin",
                          "numpy.argsort": "Ordering"}.get(row["roles"]["imported_callee"])
        if definition is None:
            continue
        name = "source_obligation_" + row["obligation_id"].split(":")[1]
        # Generated declaration names use digests, never unescaped source text.
        lines.append(f"def {name} := @{definition}\n")
        bindings.append(dict(obligation_id=row["obligation_id"], declaration=name,
            definition=definition, source_expression_id=row["expression_id"],
            interpretation="pending; template parameters are not source-value witnesses"))
    lines.append("end NumericalObligations\n")
    source = "\n".join(lines)
    return dict(family="higher_order", encoding="Lean4", status="prepared_not_built",
        library="NumericalObligations", source=source,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(), bindings=bindings,
        conditional_lemmas=["normalized_index_bounds", "last_index_bound"],
        source_obligations_discharged=0, lake_executed=False, **_FALSE)


def formalize_numerical_source(source_text, *, path="source.py"):
    """Prepare native structural and logic artifacts without executing anything.

    The original source text is not copied into this report. Source-derived
    names/spans and IR literals remain in the structural evidence. Consumers
    must replay with the same source bytes/path before reusing a proof index.
    """
    from .numerical_source import adapt_numerical_source
    structural = adapt_numerical_source(source_text, path=path)
    wire = structural.to_dict()
    program = structural.program
    obligations = _derive_obligations(program) if program is not None else []
    native = None
    if program is not None:
        bridge = SoftwareVerificationSyntaxBridge().round_trip(program)
        if not bridge.exact:
            raise NumericalLogicError("native numerical ProgramIR round trip differs")
        native = dict(family="program", encoding="ProgramIR", status="structural_only",
                      bridge=bridge.to_dict(), **_FALSE)
    fol = [_fol(row) for row in obligations]
    smt = [value for row in obligations if (value := _smt(row)) is not None]
    lean = _lean(obligations) if obligations else None
    projections = dict(program=native, first_order=fol, smt=smt, lean=lean)
    profile = describe_numerical_logic_profile()
    counts = Counter(fid for row in obligations for fid in row["function_ids"])
    coverage = wire["function_coverage"]
    functions = [dict(function_id=row["function_id"],
        qualified_name=row["name"].encode("utf-8")[:128].decode("utf-8", errors="ignore"),
        name_truncated=len(row["name"].encode("utf-8")) > 128,
        status="structurally_complete" if row["structurally_complete"] else "partial",
        structurally_complete=row["structurally_complete"],
        unsupported_construct_count=len(row["unsupported_constructs"]),
        pending_obligation_count=counts[row["function_id"]]) for row in coverage]
    report = dict(schema=SCHEMA, profile=PROFILE, source_sha256=wire["source_sha256"],
        path=path, structural=wire, pending_obligations=obligations, projections=projections,
        unsupported_families=profile["unsupported_families"],
        coverage=dict(structural_status=wire["status"],
                      function_coverage=wire["function_coverage"],
                      pending_obligation_count=len(obligations),
                      source_obligations_discharged=0),
        solver_calls=0, provider_calls=0, training_performed=False, **_FALSE)
    # Coverage status/details come from the frontend; summary handling is kept
    # separate from proof status, which is always unresolved here.
    complete = sum(row["structurally_complete"] for row in functions)
    report["summary"] = dict(schema=SCHEMA, profile=PROFILE,
        source_sha256=wire["source_sha256"], functions=len(functions),
        structurally_complete_functions=complete,
        partial_or_unsupported_functions=len(functions) - complete,
        structural_status=wire["status"],
        pending_obligation_count=len(obligations),
        families_with_artifacts=[family for family, present in
            (("program", native), ("first_order", fol or smt), ("higher_order", lean)) if present],
        per_function=functions[:16], omitted_function_summaries=max(0, len(functions)-16), **_FALSE)
    report["report_sha256"] = _sha(report)
    return report


def validate_numerical_logic_report(report, source_text, *, path="source.py"):
    """Recompute every source binding, obligation and artifact, rejecting tampering."""
    if type(report) is not dict:
        raise NumericalLogicError("native numerical logic report required")
    _raw(report)
    rebuilt = formalize_numerical_source(source_text, path=path)
    if _raw(report) != _raw(rebuilt):
        raise NumericalLogicError("numerical logic source, interpretation or artifact differs")
    return rebuilt


__all__ = ["PROFILE", "SCHEMA", "NumericalLogicError", "describe_numerical_logic_profile",
           "formalize_numerical_source", "validate_numerical_logic_report"]
