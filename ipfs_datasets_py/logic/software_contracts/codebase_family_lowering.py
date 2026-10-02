"""Closed source-bound integer claims and explicit finite-state family bridges.

Reuse the native ProgramIR/contract/VC/SMT owner and the native TLA state compiler.
These are mathematical source-model projections under the integer profile's
assumptions, never an assertion of arbitrary Python execution equivalence.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import json

from .codebase_integer_profile import CompiledIntegerOffset, compile_integer_offset, ASSUMPTIONS
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ..backends.smt.differential import normalize_smtlib_for_solver
from ..backends.tla.compiler import TLACompiler, TLACompileBounds
from ..software_verification.state import (
    Boundedness, FiniteDomainBound, PredicateRole, StatePredicate, StateSchema, StateTypeKind, StateVariable,
)
from ..software_verification.transitions import Action, ActionFrame, StateTransitionIR, TransitionKind, TransitionRelation

SCHEMA = "codebase-integer-family-lowering@1"
PROFILE = "closed-integer-offset-mathematical-and-finite-state@1"
FAMILIES = ("smt_lia", "lean4", "rocq", "isabelle_hol", "tla_plus")
BRIDGE_SCOPE = "Mathematical integer equality restricted to the exact finite initial inputs of a stuttering state model; no liveness, arbitrary TLA equivalence or Python-runtime theorem."


class CodebaseFamilyError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise CodebaseFamilyError(message)


def _copy(value):
    return json.loads(canonical_dag_json_bytes(value))


def _inputs(values):
    _require(type(values) in (tuple, list) and 1 <= len(values) <= 16
             and all(type(v) is int and abs(v) <= 2**31 for v in values)
             and list(values) == sorted(set(values)) and max(values)-min(values) <= 64,
             "1–16 sorted exact finite inputs with span at most64 required")
    return list(values)


def _tla(compiled, inputs):
    offset, expected = compiled.body_offset, compiled.contract.offset
    # TLC's concrete integer value implementation is a bounded machine integer.
    # Keep every literal and reachable addition strictly inside that range;
    # the independent mathematical kernel claim remains unbounded over Int/Z.
    concrete_values=[*inputs,offset,expected,
        min(inputs)+offset,max(inputs)+offset,min(inputs)+expected,max(inputs)+expected]
    _require(all(abs(value)<=2**31-1 for value in concrete_values),
             'TLC integer constants and reachable additions exceed the closed exact range')
    schema = StateSchema(variables=(
        StateVariable("var:argument", "argument", StateTypeKind.INTEGER, Boundedness.FINITE,
                      domain_bound=FiniteDomainBound("bound:argument", lower=min(inputs), upper=max(inputs))),
        StateVariable("var:result", "result", StateTypeKind.INTEGER, Boundedness.FINITE,
                      domain_bound=FiniteDomainBound("bound:result", lower=min(inputs)+offset, upper=max(inputs)+offset)),
    ), metadata={"compiled_cid": compiled.cid, "source_cid": compiled.source_cid})
    initial = StatePredicate("pred:init", PredicateRole.INITIAL,
        "argument \\in {" + ", ".join(map(str, inputs)) + "} /\\ result = argument + (" + str(offset) + ")",
        subject_variable_ids=("var:argument", "var:result"))
    invariant = StatePredicate("pred:offset", PredicateRole.INVARIANT,
        "result = argument + (" + str(expected) + ")", subject_variable_ids=("var:argument", "var:result"))
    guard = StatePredicate("pred:guard", PredicateRole.GUARD, "argument = argument")
    action = Action("action:stutter", "Stutter", ActionFrame(reads=("var:argument", "var:result"), writes=()), guard_predicate_id="pred:guard")
    relation = TransitionRelation("rel:next", TransitionKind.ACTION, "Only stuttering of the mathematical input/output pair.",
                                  action_ids=("action:stutter",), allows_stutter=True)
    document = StateTransitionIR(schema=schema, predicates=(initial, invariant, guard), actions=(action,), transitions=(relation,),
        metadata={"compiled_cid": compiled.cid, "domain": inputs, "bridge_scope": BRIDGE_SCOPE})
    artifacts = TLACompiler(bounds=TLACompileBounds(max_steps=2, max_variables=2, max_actions=1,
        max_predicates=3, max_integer_span=65, max_enum_members=16, max_module_bytes=32768)).compile(document, module_name="CodebaseOffset")
    _require(all(loss.construct == "finite_step_bound" for loss in artifacts.losses),
             "closed finite lowering unexpectedly loses semantics")
    # The generic compiler always proposes BoundedProgress. This profile asks
    # only for an invariant of a stuttering model; no progress property follows.
    # Retain generated source and finite-step disclosure, select safety clauses
    # explicitly in a new immutable artifact rather than silently claiming it.
    artifacts = replace(artifacts,
        tlc_config_text="\n".join(line for line in artifacts.tlc_config_text.splitlines()
                                  if not line.startswith("PROPERTY ")) + "\nCHECK_DEADLOCK FALSE\n",
        liveness_properties=(), fairness_limitations=artifacts.fairness_limitations +
        ("Closed codebase profile selects safety only; compiler BoundedProgress is not requested or claimed.",))
    return document, artifacts


def _kernel(family, body, expected, inputs, *, bridge=False):
    integer = lambda value: "(" + str(value) + " : Int)"
    if bridge:
        _require(family == "lean4", "finite restriction bridge uses the selected Lean kernel")
        finite = ", ".join(integer(v) for v in inputs)
        return ("import Init\nset_option autoImplicit false\n"
            "theorem codebase_bridge (h : ∀ n : Int, n + " + integer(body) + " = n + " + integer(expected) + ") :\n"
            "    ∀ n : Int, n ∈ ([" + finite + "] : List Int) → n + " + integer(body) + " = n + " + integer(expected) + " := by\n"
            "  intro n _\n  exact h n\n#print axioms codebase_bridge\n")
    positive = body == expected
    witness = inputs[0]
    if family == "lean4":
        statement = ("∀ n : Int, n + " + integer(body) + " = n + " + integer(expected)) if positive else (
            integer(witness) + " + " + integer(body) + " ≠ " + integer(witness) + " + " + integer(expected))
        proof = "intro n; rfl" if positive else "decide"
        return "import Init\nset_option autoImplicit false\ntheorem codebase_claim : " + statement + " := by " + proof + "\n#print axioms codebase_claim\n"
    if family == "rocq":
        statement = ("forall n : Z, n + (" + str(body) + ") = n + (" + str(expected) + ")") if positive else (
            "(" + str(witness) + ") + (" + str(body) + ") <> (" + str(witness) + ") + (" + str(expected) + ")")
        proof = "intros n; reflexivity" if positive else "vm_compute; discriminate"
        return "From Stdlib Require Import ZArith.\nOpen Scope Z_scope.\nTheorem codebase_claim : " + statement + ".\nProof. " + proof + ". Qed.\nPrint Assumptions codebase_claim.\n"
    if family == "isabelle_hol":
        statement = ("ALL n::int. n + (" + str(body) + ") = n + (" + str(expected) + ")") if positive else (
            "(" + str(witness) + "::int) + (" + str(body) + ") ~= (" + str(witness) + ") + (" + str(expected) + ")")
        return 'theory CodebaseOffset\nimports Main\nbegin\ntheorem codebase_claim: "' + statement + '" by simp\nend\n'
    raise CodebaseFamilyError("unsupported kernel family")


@dataclass(frozen=True)
class CodebaseFamilyBundle:
    compiled: CompiledIntegerOffset
    inputs: tuple[int, ...]

    def __post_init__(self):
        _require(type(self.compiled) is CompiledIntegerOffset, "exact native compilation required")
        _inputs(self.inputs)
        replay = compile_integer_offset(self.compiled.source, self.compiled.contract, revision=self.compiled.revision)
        _require(replay.cid == self.compiled.cid and canonical_dag_json_bytes(replay.pipeline.to_dict()) == canonical_dag_json_bytes(self.compiled.pipeline.to_dict()),
                 "source/ProgramIR/contract compilation does not reconstruct")

    def tla(self):
        return _tla(self.compiled, list(self.inputs))

    def kernel_source(self, family, *, bridge=False):
        return _kernel(family, self.compiled.body_offset, self.compiled.contract.offset, list(self.inputs), bridge=bridge)

    def smt_source(self):
        return "\n".join(line for line in normalize_smtlib_for_solver(self.compiled.compilation.smtlib).splitlines()
            if line.strip() not in {"(get-model)", "(get-unsat-core)"}) + "\n"

    def to_dict(self):
        document, artifacts = self.tla()
        return dict(schema=SCHEMA, profile=PROFILE, compiled_cid=self.compiled.cid,
            contract_cid=self.compiled.contract.cid, source_cid=self.compiled.source_cid, revision=self.compiled.revision,
            operation="prove_offset" if self.compiled.body_offset == self.compiled.contract.offset else "refute_offset_with_declared_domain_witness",
            assumptions=list(ASSUMPTIONS), mathematical_domain="unbounded_integer",
            finite_inputs=list(self.inputs), finite_domain_cid=cid_for_structured(list(self.inputs)),
            source_lowering="existing_native_closed_integer_offset_ProgramIR_contract_VC",
            families=list(FAMILIES), source_correspondence_cid=cid_for_structured(self.compiled.pipeline.bindings.to_dict()),
            smt_query_cid=cid_for_bytes(self.smt_source().encode()),
            kernel_source_cids={family: cid_for_bytes(self.kernel_source(family).encode()) for family in ("lean4", "rocq", "isabelle_hol")},
            finite_state_ir_cid=cid_for_structured(document.to_dict()), tla_artifact_digest=artifacts.artifact_digest,
            tla_model_cid=cid_for_bytes(artifacts.model_text.encode()), tla_configuration_cid=cid_for_bytes(artifacts.tlc_config_text.encode()),
            bridge=dict(operation="restrict_mathematical_equality_to_declared_finite_inputs", source_family="mathematical_integer", target_family="tla_plus",
                source_cid=cid_for_bytes(self.kernel_source("lean4", bridge=True).encode()), scope=BRIDGE_SCOPE,
                assumptions_preserved=True, reverse_implication_claimed=False, arbitrary_cross_family_equivalence_claimed=False),
            source_runtime_semantics_verified=False, proof_claimed=False)

    @property
    def cid(self):
        return cid_for_structured(self.to_dict())
