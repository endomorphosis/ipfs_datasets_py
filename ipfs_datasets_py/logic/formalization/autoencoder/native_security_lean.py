"""Bounded Security heap/SL and relational hyperproperty Lean interpretations.

Definitions describe supplied native declarations. No source-program behavior,
ownership, noninterference theorem, event occurrence, or checker result is
invented. The enclosing gate must replay the report against its original source.
"""
from __future__ import annotations

import hashlib
import json
import re

from ...software_verification.heap import HeapModel
from ...software_verification.separation import SeparationLogicIR
from ...software_verification.hyperproperties import HyperpropertyIR, HyperpropertyFormula
from .native_family_lean_emitters import UnsupportedNativeLean, require, string

PROFILE = "native-security-resource-relational-lean/v1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _details(payload, validator, operators, assumptions, **extra):
    return {"profile": PROFILE, "validator": validator, "payload_sha256": _digest(payload),
        "operators": operators, "assumptions": assumptions, "source_semantics_verified": False,
        "model_checker_executed": False, "admitted": False, **extra}


HEAP_PRELUDE = '''set_option linter.unusedVariables false
inductive HeapValue where
  | integer (value : Int)
  | boolean (value : Bool)
  deriving DecidableEq
structure HeapInterpretation where
  address : String → Nat
abbrev Heap := Nat → Option HeapValue
def emptyHeap : Heap := fun _ => none
def singletonHeap (address : Nat) (value : HeapValue) : Heap :=
  fun location => if location = address then some value else none
def finiteHeap (heap : Heap) : Prop :=
  ∃ support : List Nat, ∀ address, heap address ≠ none → address ∈ support
def disjointHeaps (left right : Heap) : Prop :=
  ∀ address, left address = none ∨ right address = none
def unionHeap (left right : Heap) : Heap :=
  fun address => match left address with
    | some value => some value
    | none => right address
def emp (heap : Heap) : Prop := heap = emptyHeap
def pointsTo (address : Nat) (value : HeapValue) (heap : Heap) : Prop :=
  heap = singletonHeap address value
def separating (left right : Heap → Prop) (heap : Heap) : Prop :=
  ∃ first second, finiteHeap first ∧ finiteHeap second ∧ disjointHeaps first second ∧
    heap = unionHeap first second ∧ left first ∧ right second
theorem emptyHeap_finite : finiteHeap emptyHeap := by
  refine ⟨[], ?_⟩
  intro address h
  simp [emptyHeap] at h
theorem singletonHeap_finite (address : Nat) (value : HeapValue) :
    finiteHeap (singletonHeap address value) := by
  refine ⟨[address], ?_⟩
  intro other h
  by_cases same : other = address
  · simp [same]
  · simp [singletonHeap, same] at h
theorem singleton_not_disjoint_with_itself (address : Nat) (value : HeapValue) :
    ¬ disjointHeaps (singletonHeap address value) (singletonHeap address value) := by
  intro h
  have contradiction := h address
  simp [singletonHeap] at contradiction
'''


class _Heap:
    def __init__(self, payload):
        self.native = HeapModel.from_dict(payload)
        require(self.native.to_dict() == payload, "exact_native_heap_roundtrip_required")
        require(not any(payload[key] for key in ("ownership", "aliases", "resource_units", "resource_algebras", "metadata")),
                "heap_ownership_alias_resource_or_metadata_semantics_not_lowered")
        require(len(payload["locations"]) <= 64 and len(payload["values"]) <= 128 and len(payload["cells"]) <= 128,
                "bounded_heap_declarations_required")
        self.payload = payload
        self.locations = {row["location_id"]: row for row in payload["locations"]}
        self.values = {row["value_id"]: row for row in payload["values"]}
        self.location_names = {key: "location_" + str(i) for i, key in enumerate(self.locations)}
        self.value_names = {key: "value_" + str(i) for i, key in enumerate(self.values)}
        self.declarations = []
        for key, row in self.locations.items():
            require(row["kind"] == "address" and row["type_name"] in ("integer", "boolean") and
                    not row["owner_id"] and not row["attributes"], "concrete_heap_address_type_without_extra_claims_required")
            self.declarations.append("def " + self.location_names[key] + " (i : HeapInterpretation) : Nat := i.address " + string(key))
        for key, row in self.values.items():
            require(not row["attributes"] and not row["points_to_location_id"] and row["kind"] == row["type_name"],
                    "heap_value_extra_semantics_not_lowered")
            literal = row["literal"]
            if row["kind"] == "integer":
                require(len(literal) <= 256 and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", literal) is not None,
                        "canonical_bounded_integer_heap_literal_required")
                body = "HeapValue.integer (" + literal + " : Int)"
            elif row["kind"] == "boolean":
                require(literal in ("true", "false"), "canonical_Boolean_heap_literal_required")
                body = "HeapValue.boolean " + literal
            else: raise UnsupportedNativeLean("heap_value_kind_requires_separate_lowering:" + row["kind"])
            self.declarations.append("def " + self.value_names[key] + " : HeapValue := " + body)
        for cell in payload["cells"]:
            require(not cell["attributes"], "heap_cell_attributes_not_lowered")
            self.point(cell["location_id"], cell["value_id"], cell["permission"])

    def point(self, location, value, permission):
        require(permission and permission["numerator"] == permission["denominator"] == 1,
                "classical_heap_requires_full_permission")
        require(location in self.locations and value in self.values and
            self.locations[location]["type_name"] == self.values[value]["type_name"], "points_to_declared_types_differ")
        return "pointsTo (" + self.location_names[location] + " i) " + self.value_names[value]

    def source(self):
        result = [HEAP_PRELUDE, *self.declarations]
        fragments = [self.point(row["location_id"], row["value_id"], row["permission"]) for row in self.payload["cells"]]
        body = "emp"
        for fragment in reversed(fragments): body = "(separating (" + fragment + ") " + body + ")"
        result.append("def declaredHeapFragment (i : HeapInterpretation) (heap : Heap) : Prop := " + body + " heap")
        result.append("def allocatedCellCount : Nat := " + str(len(fragments)))
        return "\n\n".join(result)


HEAP_ASSUMPTIONS = [
    "Location identifiers are interpreted as addresses; distinct IDs are not asserted to be nonaliasing.",
    "Heap values retain the integer/Boolean distinction. Full permission denotes exclusive owned cells.",
    "The heap fragment describes owned resource, not the entire source program memory or an observed allocation.",
    "No ownership transfer, alias declaration, fractional resource, or source execution is inferred."]


def emit_heap(payload):
    heap = _Heap(payload)
    return heap.source(), _details(payload, "HeapModel_exact_roundtrip_full_permission_finite_heap_fragment",
        ["finite_partial_heap", "typed_points_to", "disjoint_heap_union"], HEAP_ASSUMPTIONS,
        allocated_cells=len(payload["cells"]), capability_floor_eligible=bool(payload["cells"]))


def emit_separation(payload):
    native = SeparationLogicIR.from_dict(payload)
    require(native.to_dict() == payload, "exact_native_separation_roundtrip_required")
    require(payload["heap_theory"] == "classical_sl" and not any(payload[key] for key in
        ("frame_obligations", "ownership_transfers", "metadata", "observations")), "separation_extra_theory_or_claims_not_lowered")
    heap = _Heap(payload["heap"])
    nodes = {row["formula_id"]: row for row in payload["formulas"]}
    require(1 <= len(nodes) <= 256, "bounded_separation_formula_DAG_required")
    names = {key: "formula_" + str(index) for index, key in enumerate(nodes)}
    lines = [heap.source()]; emitted = set(); active = set(); operators = []
    def formula(key, depth=0):
        require(depth <= 64 and key not in active, "bounded_acyclic_separation_DAG_required")
        if key in emitted: return
        row = nodes[key]; kind = row["kind"]; operands = row["operand_ids"]
        require(not any(row[k] for k in ("attributes", "pure_expression", "pure_expression_id", "bound_variable", "bound_type")),
                "opaque_pure_formula_or_quantifier_requires_typed_semantics")
        active.add(key)
        for child in operands: formula(child, depth + 1)
        if kind == "points_to":
            body = heap.point(row["location_id"], row["value_id"], row["permission"]) + " heap"
        else:
            require(not row["location_id"] and not row["value_id"] and row["permission"] is None,
                    "nonspatial_formula_carries_spatial_fields")
            if kind in ("emp", "true", "false"):
                require(not operands, "nullary_spatial_formula_required")
                body = {"emp": "emp heap", "true": "True", "false": "False"}[kind]
            elif kind == "sep_conj":
                require(len(operands) >= 2, "separating_conjunction_arity")
                chain = names[operands[-1]] + " i"
                for child in reversed(operands[:-1]): chain = "(separating (" + names[child] + " i) (" + chain + "))"
                body = chain + " heap"
            elif kind in ("and", "or", "implies"):
                require(len(operands) >= 2 and (kind != "implies" or len(operands) == 2), "classical_connective_arity")
                body = (" " + {"and": "∧", "or": "∨", "implies": "→"}[kind] + " ").join("(" + names[child] + " i heap)" for child in operands)
            elif kind == "not":
                require(len(operands) == 1, "negation_arity")
                body = "¬ (" + names[operands[0]] + " i heap)"
            else: raise UnsupportedNativeLean("unsupported_native_separation_connective:" + kind)
        lines.append("def " + names[key] + " (i : HeapInterpretation) (heap : Heap) : Prop := " + body)
        operators.append(kind); emitted.add(key); active.remove(key)
    for key in nodes: formula(key)
    lines.append("def separationFormula (i : HeapInterpretation) (heap : Heap) : Prop := finiteHeap heap ∧ " + names[payload["root_formula_id"]] + " i heap")
    return "\n\n".join(lines), _details(payload, "SeparationLogicIR_exact_classical_finite_heap_semantics",
        operators, HEAP_ASSUMPTIONS + ["Separating conjunction existentially splits finite disjoint heaps; ordinary conjunction evaluates both operands on the same heap.",
            "The selected formula and declared heap fragment are separate declarations; neither is asserted true of the other."],
        formula_symbols=names, root_formula_id=payload["root_formula_id"])


def emit_hyperproperty(payload):
    native = HyperpropertyIR.from_dict(payload)
    require(native.to_dict() == payload, "exact_native_hyperproperty_roundtrip_required")
    require(not any(payload[key] for key in ("witness_bundles", "metadata", "observations")), "hyperproperty_witness_or_metadata_requires_separate_evidence")
    formula = native.formula
    require(formula.kind.value == "noninterference" and len(formula.variables) == 2, "canonical_two_trace_noninterference_only")
    canonical = HyperpropertyFormula.noninterference(formula_id=formula.formula_id,
        policy_id=native.information_flow_policy.policy_id, left_name=formula.variables[0].name,
        right_name=formula.variables[1].name, description=formula.description)
    require(canonical.to_dict() == formula.to_dict(), "hyperproperty_matrix_prefix_or_relational_conditions_not_canonical")
    policy = payload["information_flow_policy"]
    require(not any(policy[key] for key in ("labels", "observations", "declassifications", "subject_fields")),
            "hyperproperty_policy_extra_semantics_not_lowered")
    require(all(len(policy[key]) <= 64 for key in ("low_input_fields", "high_input_fields", "observation_fields")),
            "bounded_hyperproperty_field_selection_required")
    bounds = payload["self_composition_bound"]
    require(bounds["max_traces"] <= 1024 and bounds["max_pairs"] <= 1048576 and
        (bounds["max_steps"] is None or bounds["max_steps"] <= 1048576), "bounded_hyperproperty_composition_budget_required")
    lines = ["set_option linter.unusedVariables false", "structure ExecutionView (Value : Type) where\n  publicValue : String → Value\n  privateValue : String → Value\n  observedValue : String → Value"]
    for name, key in (("lowFields", "low_input_fields"), ("highFields", "high_input_fields"), ("observationFields", "observation_fields")):
        lines.append("def " + name + " : List String := [" + ", ".join(string(value) for value in policy[key]) + "]")
    lines += ["def lowProjection {Value : Type} (trace : ExecutionView Value) : List Value := lowFields.map trace.publicValue",
        "def observationProjection {Value : Type} (trace : ExecutionView Value) : List Value := observationFields.map trace.observedValue",
        "def noninterference {Value : Type} (executions : ExecutionView Value → Prop) : Prop :=\n  ∀ left, executions left → ∀ right, executions right →\n    lowProjection left = lowProjection right → observationProjection left = observationProjection right",
        "def maxTraces : Nat := " + str(bounds["max_traces"]), "def maxPairs : Nat := " + str(bounds["max_pairs"]),
        "def declaredMaxSteps : Option Nat := " + ("none" if bounds["max_steps"] is None else "some " + str(bounds["max_steps"])),
        "def sampleWithinCompositionBudget {Value : Type} (sample : List (ExecutionView Value)) : Prop :=\n  sample.length ≤ maxTraces ∧ sample.length * (sample.length - 1) / 2 ≤ maxPairs",
        "def temporalExecutionBoundChecked : Bool := false", "def universalNoninterferenceProved : Bool := false",
        "def quantifierVariableOrder : List String := [" + ", ".join(string(item.variable_id) for item in formula.quantifier_prefix) + "]",
        "def policyIdentifier : String := " + string(policy["policy_id"])]
    return "\n\n".join(lines), _details(payload, "HyperpropertyIR_exact_canonical_noninterference_relational_projection",
        ["forall_execution", "forall_execution", "low_projection_equality", "observation_projection_equality", "implication"],
        ["Execution views expose already-projected native field-path values; no JSON decoder or source execution is inferred.",
         "The interpretation of Value must preserve the native comparison, including its missing/null projection convention.",
         "Quantification is over the supplied set of executions; no noninterference proposition is asserted as a theorem.",
         "Composition caps are retained as sampling budgets. ExecutionTrace has no time series, so max_steps is not used to invent temporal semantics.",
         "Private/high values remain unconstrained by the low-equality premise; no high variation or witness observation is fabricated."],
        capability_floor_eligible=False, provided_capabilities=["two_trace_relational_noninterference"],
        missing_capabilities=["temporal_HyperLTL_trace_semantics"], temporal_execution_bound_checked=False)


def emit_projection(row, *, report=None):
    routes = {"separation_logic.heap_model/v1": ("separation_logic", "heap_model", emit_heap),
        "separation_logic.ir/v1": ("separation_logic", "separation", emit_separation),
        "hyperproperty.ir/v1": ("hyperproperty", "hyperltl", emit_hyperproperty)}
    if row.get("projection_id") not in routes: raise NotImplementedError
    family, profile, render = routes[row["projection_id"]]
    require(row.get("logic_family") == family and row.get("profile") == profile, "Security_native_projection_route_differs")
    return render(row["payload"])


__all__ = ["emit_projection", "emit_heap", "emit_separation", "emit_hyperproperty"]
