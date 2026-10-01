"""Explicit, source-bound static-frame interpretations of native protocol claims.

This supplies static observation semantics, not role-process equivalence. Every
finite observer recipe is quantified over in Lean; witness search is merely a
bounded convenience and never reports equivalence from a missing witness.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json

from .native_family_lean_emitters import require, string

SCHEMA = "protocol-static-frame-interpretation/v1"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class ProtocolFrameInterpretation:
    """An immutable choice of static semantics for unchanged native operands."""
    _wire: str

    @classmethod
    def from_dict(cls, value):
        require(type(value) is dict and set(value) == {
            "schema", "native_document_sha256", "claim_ids", "mode"},
            "closed_protocol_static_frame_interpretation_required")
        require(value["schema"] == SCHEMA and value["mode"] == "static_observation_vectors",
                "explicit_protocol_static_observation_mode_required")
        digest = value["native_document_sha256"]
        require(type(digest) is str and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest),
                "protocol_static_frame_native_digest_required")
        ids = value["claim_ids"]
        require(type(ids) is list and 1 <= len(ids) <= 64 and all(type(x) is str and x for x in ids)
                and ids == sorted(set(ids)), "sorted_unique_protocol_static_claim_ids_required")
        require(len(_json(value).encode()) <= 32768, "bounded_protocol_static_interpretation_required")
        return cls(_json(value))

    def to_dict(self):
        return json.loads(self._wire)


class _Algebra:
    def __init__(self, payload, symmetric):
        self.payload = payload
        self.functions = {row["function_id"]: row for row in payload["functions"]}
        self.sorts = {row["sort_id"] for row in payload["sorts"]}
        self.symmetric = symmetric
        require(not any(row["available_after_event_ids"] for row in payload["adversary"]["knowledge"]),
                "protocol_static_frame_conditional_knowledge_requires_an_explicit_cutpoint")
        require(payload["adversary"]["kind"] != "none",
                "protocol_static_frame_requires_an_explicit_observer")
        self.capabilities = set(payload["adversary"]["capabilities"])
        self.initial = [row["term"] for row in payload["adversary"]["knowledge"]]
        self.initial += [dict(sort=row["sort"], symbol_id=row["key_id"], function_id="", literal="", arguments=[])
            for row in payload["keys"] if row["kind"] == "public" or row["key_id"] in payload["adversary"]["compromised_key_ids"]]
        require(all(self.normalize(value) is not None for value in self.initial),
                "protocol_static_initial_knowledge_must_have_a_value")
        # The selected algebra has a terminating perfect-symmetric normalizer.
        # Arbitrary ground equations cannot be ignored or treated as consistent.
        for rule in payload["rewrite_facts"]:
            left, right = self.normalize(rule["left"]), self.normalize(rule["right"])
            require(left is not None and right is not None and left == right,
                    "protocol_static_frame_noncanonical_equation_requires_another_algebra")

    def apply(self, function_id, arguments):
        function = self.functions.get(function_id)
        if function is None or [row["sort"] for row in arguments] != function["parameter_sorts"]:
            return None
        if function["kind"] == "constructor":
            return dict(sort=function["result_sort"], symbol_id="", literal="", function_id=function_id, arguments=arguments)
        encrypt, decrypt = self.symmetric
        if function_id != decrypt["function_id"] or len(arguments) != 2:
            return None
        cipher, key = arguments
        if cipher["function_id"] != encrypt["function_id"] or len(cipher["arguments"]) != 2:
            return None
        plaintext, required_key = cipher["arguments"]
        return plaintext if required_key == key else None

    def normalize(self, term):
        if not term["function_id"]:
            return term
        arguments = [self.normalize(value) for value in term["arguments"]]
        if any(value is None for value in arguments):
            return None
        return self.apply(term["function_id"], arguments)

    def evaluate(self, frame, recipe):
        kind = recipe["kind"]
        if kind in ("handle", "initial"):
            values = frame if kind == "handle" else self.initial
            index = recipe["index"]
            return self.normalize(values[index]) if 0 <= index < len(values) else None
        if kind == "literal":
            value = recipe["value"]
            if recipe["sort"] not in self.sorts:
                return None
            return dict(sort=recipe["sort"], literal=value, symbol_id="", function_id="", arguments=[])
        function = self.functions.get(recipe["function_id"])
        if not function or ("compose" if function["kind"] == "constructor" else "decompose") not in self.capabilities:
            return None
        arguments = [self.evaluate(frame, item) for item in recipe["arguments"]]
        return None if any(value is None for value in arguments) else self.apply(recipe["function_id"], arguments)

    def observe(self, frame, first, second):
        left, right = self.evaluate(frame, first), self.evaluate(frame, second)
        return None if left is None or right is None else left == right


def _recipe(row):
    kind = row["kind"]
    if kind in ("handle", "initial"):
        return "(." + kind + " " + str(row["index"]) + ")"
    if kind == "literal":
        return "(.literal " + string(row["sort"]) + " " + string(row["value"]) + ")"
    return "(.apply " + string(row["function_id"]) + " [" + ", ".join(_recipe(x) for x in row["arguments"]) + "])"


def _witness(algebra, left, right):
    """A bounded counterexample search, independent of the unbounded formula."""
    recipes = [{"kind": "handle", "index": i} for i in range(len(left))]
    recipes += [{"kind": "initial", "index": i} for i in range(len(algebra.initial))]
    literals = {}
    def collect(term):
        if term["literal"]:
            recipe = dict(kind="literal", sort=term["sort"], value=term["literal"])
            literals[_json(recipe)] = recipe
        for child in term["arguments"]:
            collect(child)
    for term in [*left, *right, *algebra.initial]:
        collect(term)
    recipes += [literals[key] for key in sorted(literals)]
    recipes = recipes[:256]
    # Include one application layer, enough to exhibit direct decryption leaks.
    # The search limit is reported and never bounds the quantified Lean model.
    basis = list(recipes)
    for function in algebra.functions.values():
        if len(function["parameter_sorts"]) > 3:
            continue
        options = []
        for sort in function["parameter_sorts"]:
            options.append([r for r in basis if any(value is not None and value["sort"] == sort
                for value in (algebra.evaluate(left, r), algebra.evaluate(right, r)))])
        for arguments in itertools.product(*options):
            if len(recipes) >= 256:
                break
            recipes.append(dict(kind="apply", function_id=function["function_id"], arguments=list(arguments)))
    values = [(recipe, *[None if (value := algebra.evaluate(frame, recipe)) is None else _json(value)
                        for frame in (left, right)]) for recipe in recipes]
    for first, first_left, first_right in values:
        for second, second_left, second_right in values:
            lresult = None if first_left is None or second_left is None else first_left == second_left
            rresult = None if first_right is None or second_right is None else first_right == second_right
            if lresult != rresult:
                return dict(first=first, second=second, left_observation=lresult, right_observation=rresult,
                            searched_recipes=len(recipes))
    return None


FRAME_EQUALITY = '''
mutual
  def frameTermEq (left right : Term) : Bool :=
    match left, right with
    | .atom sort value, .atom otherSort other => sort == otherSort && value == other
    | .literal sort value, .literal otherSort other => sort == otherSort && value == other
    | .app sort function args, .app otherSort otherFunction others =>
      sort == otherSort && function == otherFunction && frameTermsEq args others
    | _, _ => false
  termination_by sizeOf left
  def frameTermsEq (left right : List Term) : Bool :=
    match left, right with
    | [], [] => true
    | first :: tail, other :: rest => frameTermEq first other && frameTermsEq tail rest
    | _, _ => false
  termination_by sizeOf left
end
theorem frameTermEq_exact (left : Term) : ∀ right, frameTermEq left right = true ↔ left = right := by
  refine Term.rec (motive_1 := fun a => ∀ b, frameTermEq a b = true ↔ a = b)
    (motive_2 := fun xs => ∀ ys, frameTermsEq xs ys = true ↔ xs = ys) ?_ ?_ ?_ ?_ ?_ left
  · intro sort symbol right
    cases right <;> simp [frameTermEq]
  · intro sort value right
    cases right <;> simp [frameTermEq]
  · intro sort function arguments ih right
    cases right <;> simp [frameTermEq, ih, and_assoc]
  · intro ys
    cases ys <;> simp [frameTermsEq]
  · intro head tail ihHead ihTail ys
    cases ys <;> simp [frameTermsEq, ihHead, ihTail]
'''


FRAME_EVALUATOR = '''
inductive ObserverRecipe where
  | handle : Nat → ObserverRecipe
  | initial : Nat → ObserverRecipe
  | literal : String → String → ObserverRecipe
  | apply : String → List ObserverRecipe → ObserverRecipe
  deriving Repr
def frameNormalize (term : Term) : Option Term :=
  match term with
  | .atom sort symbol => some (.atom sort symbol)
  | .literal sort value => some (.literal sort value)
  | .app _ function arguments => do
    let values ← arguments.attach.mapM (fun child => frameNormalize child.val)
    frameApply function values
termination_by sizeOf term
decreasing_by
  simp_wf
  have h := List.sizeOf_lt_of_mem child.property
  omega
def frameEvaluate (frame : List Term) (recipe : ObserverRecipe) : Option Term :=
  match recipe with
  | .handle index => frame[index]?.bind frameNormalize
  | .initial index => initialKnowledge[index]?.bind frameNormalize
  | .literal sort value =>
    if frameSortKnown sort then some (.literal sort value) else none
  | .apply function arguments => do
    if !frameFunctionAccessible function then none else do
      let values ← arguments.attach.mapM (fun child => frameEvaluate frame child.val)
      frameApply function values
termination_by sizeOf recipe
decreasing_by
  simp_wf
  have h := List.sizeOf_lt_of_mem child.property
  omega
def frameObservation (frame : List Term) (first second : ObserverRecipe) : Option Bool := do
  let left ← frameEvaluate frame first
  let right ← frameEvaluate frame second
  pure (frameTermEq left right)
def staticFrameEquivalent (left right : List Term) : Prop :=
  ∀ first second, frameObservation left first second = frameObservation right first second
'''


def emit_static_frames(payload, interpretation):
    """Return exact frame formulas, never claims about missing role processes."""
    from .native_protocol_lean import _validate, _term, _terms, _strings
    _, symmetric = _validate(payload, allow_equivalence=True)
    if type(interpretation) is ProtocolFrameInterpretation:
        interpretation = interpretation.to_dict()
    declaration = ProtocolFrameInterpretation.from_dict(interpretation).to_dict()
    require(declaration["native_document_sha256"] == _digest(payload),
            "protocol_static_frame_interpretation_native_digest_differs")
    claims = [row for row in payload["claims"] if row["kind"] == "equivalence"]
    require(declaration["claim_ids"] == sorted(row["claim_id"] for row in claims),
            "protocol_static_interpretation_must_cover_exactly_every_equivalence_claim")
    algebra = _Algebra(payload, symmetric)
    lines = ["def retainedStaticFrameInterpretation : String := " + string(_json(declaration)),
             "def frameSortKnown (sort : String) : Bool := " + _strings(sorted(algebra.sorts)) + ".contains sort"]
    accessible = []
    for row in payload["functions"]:
        capability = "compose" if row["kind"] == "constructor" else "decompose"
        accessible.append("(function == " + string(row["function_id"]) + " && hasCapability " + string(capability) + ")")
    lines.append("def frameFunctionAccessible (function : String) : Bool := " + (" || ".join(accessible) or "false"))
    # Equality is a structural recursive definition with a kernel-checked
    # exactness theorem, not JSON equality or an opaque predicate interpretation.
    lines.append(FRAME_EQUALITY)
    lines.append("def frameApply (function : String) (arguments : List Term) : Option Term :=")
    for row in payload["functions"]:
        lines.append("  if function == " + string(row["function_id"]) + " && arguments.map termSort == "
                     + _strings(row["parameter_sorts"]) + " then")
        if row["kind"] == "constructor":
            lines.append("    some (.app " + string(row["result_sort"]) + " function arguments)")
        else:
            encrypt, _ = symmetric
            lines.extend(["    match arguments with", "    | [.app sort constructor [plain, key], supplied] =>",
                "      if sort == " + string(encrypt["result_sort"]) + " && constructor == " + string(encrypt["function_id"])
                    + " && frameTermEq key supplied then some plain else none", "    | _ => none"])
        lines.append("  else")
    lines.append("  none")
    lines.append(FRAME_EVALUATOR)
    queries = {}; evaluations = []
    for index, claim in enumerate(claims):
        left, right = claim["left_terms"], claim["right_terms"]
        require(all(algebra.normalize(term) is not None for term in [*left, *right]),
                "protocol_static_frame_operands_must_have_values")
        name = "frameClaim_" + str(index)
        lines.extend(["def " + name + "Left : List Term := " + _terms(left),
            "def " + name + "Right : List Term := " + _terms(right),
            "def " + name + " : Prop := staticFrameEquivalent " + name + "Left " + name + "Right"])
        queries[claim["claim_id"]] = name
        witness = _witness(algebra, left, right)
        if witness:
            a, b = _recipe(witness["first"]), _recipe(witness["second"])
            lines.extend(["theorem " + name + "_distinguishing_observation :",
                "    frameObservation " + name + "Left " + a + " " + b + " ≠ frameObservation " + name + "Right " + a + " " + b + " := by",
                "  simp [frameObservation, frameEvaluate, frameNormalize, frameApply, termSort, frameTermEq, frameTermsEq, frameFunctionAccessible, frameSortKnown, initialKnowledge, hasCapability, capabilities, " + name + "Left, " + name + "Right]",
                "theorem " + name + "_not_equivalent : ¬ " + name + " := by",
                "  intro equivalence", "  exact " + name + "_distinguishing_observation (equivalence " + a + " " + b + ")"])
        evaluations.append(dict(claim_id=claim["claim_id"], query_symbol=name,
            counterexample=witness, counterexample_found=witness is not None,
            equivalent_proved=False, process_equivalence_verified=False,
            witness_search_scope="at most one application layer over observation/initial/literal seeds; absence is inconclusive",
            witness_search_recipe_budget=256,
            semantic_recipe_depth_bound=None))
    details = dict(schema=SCHEMA, interpretation=declaration, interpretation_sha256=_digest(declaration),
        queries=queries, claim_evaluations=evaluations,
        semantics="unbounded_static_frame_observation_equivalence_under_explicit_interpretation",
        native_document_rewritten=False, claim_operands_rewritten=False, source_semantics_verified=False,
        process_equivalence_verified=False, protocol_security_verified=False, admitted=False, qualified=False,
        assumptions=["Native left/right vectors are explicitly interpreted as simultaneous observation frames; role processes are not inferred.",
            "All finite typed observer recipes are quantified over, including public literals and permitted constructor/destructor applications.",
            "Observations compare both successful evaluation and structural equality of normalized symbolic values.",
            "Public literals are guessable values; private fresh-name atoms cannot be manufactured by a literal recipe.",
            "Only canonical free/symmetric algebra is accepted; additional equations, conditional disclosure cutpoints and other theories fail closed.",
            "A found witness refutes the interpreted static claim. A missing witness makes no equivalence assertion."])
    return "\n".join(lines) + "\n", details


__all__ = ["SCHEMA", "ProtocolFrameInterpretation", "emit_static_frames"]
