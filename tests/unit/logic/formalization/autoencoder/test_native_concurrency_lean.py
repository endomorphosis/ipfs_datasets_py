"""Real kernel checks and mutation rejection for the closed concurrency fragment."""
import copy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_concurrency_lean as emit
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.software_verification.concurrency import (
    AtomicRegion, BoundedSchedule, ConcurrentComponent, ConcurrentStep,
    ConcurrencyFairness, ConcurrencyIR, InterferenceAssumption, RelyGuaranteeContract,
)


def fixture():
    """An explicit authored skip system, never a weakened producer/consumer IR."""
    return ConcurrencyIR(
        components=(
            ConcurrentComponent("comp:a", "thread", "Worker", step_ids=("step:a", "step:blocked")),
            ConcurrentComponent("comp:b", "process", "Peer", step_ids=("step:b",)),
        ),
        steps=(
            ConcurrentStep("step:a", "component", "tick", component_id="comp:a", atomic_region_id="atomic:a"),
            ConcurrentStep("step:b", "component", "peer tick", component_id="comp:b"),
            ConcurrentStep("step:blocked", "component", "disabled", component_id="comp:a", guard_statement="false"),
            ConcurrentStep("step:environment", "environment", "external tick"),
        ),
        atomic_regions=(AtomicRegion("atomic:a", "comp:a", ("step:a",)),),
        interference=(InterferenceAssumption("interference:environment", "internal", "true", "comp:a", interferer_is_environment=True),),
        fairness=(ConcurrencyFairness("fair:a", "weak", "weak", step_ids=("step:a",)),),
        rely_guarantee=(RelyGuaranteeContract("contract:a", "comp:a", "true", "true", interference_ids=("interference:environment",)),),
        schedules=(BoundedSchedule("schedule:two", 2),),
        require_fairness=True,
    ).to_dict()


def rebuild(payload):
    payload = copy.deepcopy(payload)
    payload.pop("document_id", None)
    return ConcurrencyIR.from_dict(payload).to_dict()


def lake(source, extra=""):
    paths = sorted((Path.home() / ".elan" / "toolchains").glob("*/bin/lake"))
    if not paths:
        pytest.skip("Installed Lake unavailable; no download attempted")
    return _execute("set_option autoImplicit false\nnamespace ConcurrencyFixture\n" + source + "\n" + extra + "\nend ConcurrencyFixture\n", "ConcurrencyFixture", paths[-1], 30)


TRACES = """
def store : Store Nat := fun _ => 0
def workerTrace : Execution Nat := ⟨fun _ => store, fun _ => Step.s0⟩
def peerTrace : Execution Nat := ⟨fun _ => store, fun _ => Step.s1⟩
"""


def test_closed_native_semantics_compile_and_keep_authority_false():
    source, details = emit.emit_concurrency(fixture())
    assert details["source_semantics_verified"] is False
    assert details["obligations_discharged"] is False
    assert details["capability_floor_eligible"] is False
    assert "axiom " not in source and "sorry" not in source
    result = lake(source, TRACES + """
example : componentKind Component.c0 = ComponentKind.thread := rfl
example : componentKind Component.c1 = ComponentKind.process := rfl
example : stepActor Step.s3 = Actor.environment := rfl
example : stepActor Step.s0 = Actor.component Component.c0 := rfl
example : componentStep Component.c0 Step.s0 store store := ⟨rfl, rfl, rfl⟩
example : environmentStep Step.s3 store store := ⟨rfl, rfl, rfl⟩
example : ¬ stepRelation Step.s2 store store := by
  simp [stepRelation, stepEnabled]
example : ¬ stepRelation Step.s0 store (fun _ => 1) := by
  intro h
  have wrong := congrFun h.2 "x"
  simp [store] at wrong
example : schedule_0 [Step.s0, Step.s3] := by simp [schedule_0, stepEnabled]
example : ¬ schedule_0 [Step.s0, Step.s0, Step.s0] := by simp [schedule_0, stepEnabled]
example : ¬ schedule_0 [Step.s2] := by simp [schedule_0, stepEnabled]
example : validExecution workerTrace := by
  intro time
  exact ⟨rfl, rfl⟩
example : atomicRegion_0 = (Component.c0, Step.s0) := rfl
example : unboundedRefinementProved = false := rfl
""")
    assert result["status"] == "passed", result


def test_fairness_rejects_starvation_but_accepts_worker_execution():
    source, _ = emit.emit_concurrency(fixture())
    result = lake(source, TRACES + """
example : fairness_0 workerTrace := by
  intro _ start
  exact ⟨start, Nat.le_refl start, by simp [workerTrace]⟩
example : ¬ fairness_0 peerTrace := by
  intro claim
  have enabled : continuouslyEventually (fun _ => selectedEnabled [Step.s0]) := by
    refine ⟨0, ?_⟩
    intro time _
    exact ⟨Step.s0, by simp, rfl⟩
  obtain ⟨time, _, wrong⟩ := claim enabled 0
  simp [peerTrace] at wrong
example : contract_0 workerTrace := by
  intro _ time _
  trivial
""")
    assert result["status"] == "passed", result
    failed = lake(source, TRACES + "example : fairness_0 peerTrace := by simp [fairness_0, weakFair, continuouslyEventually, selectedEnabled, infinitelyOften, peerTrace, stepEnabled]")
    assert failed["status"] == "failed" and failed["returncode"] != 0


def test_strong_unconditional_and_component_fairness_have_infinite_trace_semantics():
    payload = fixture()
    payload["fairness"] = [
        ConcurrencyFairness("fair:a", "strong", "strong", component_ids=("comp:a",)).to_dict(),
        ConcurrencyFairness("fair:b", "unconditional", "unconditional", step_ids=("step:b",)).to_dict(),
    ]
    source, _ = emit.emit_concurrency(rebuild(payload))
    result = lake(source, TRACES + """
example : fairness_0 workerTrace := by
  intro _ start
  exact ⟨start, Nat.le_refl start, by simp [workerTrace]⟩
example : fairness_1 peerTrace := by
  intro start
  exact ⟨start, Nat.le_refl start, by simp [peerTrace]⟩
example : ¬ fairness_1 workerTrace := by
  intro claim
  obtain ⟨time, _, wrong⟩ := claim 0
  simp [workerTrace] at wrong
""")
    assert result["status"] == "passed", result


def test_false_guarantee_is_not_an_axiom_and_rely_is_scoped_to_other_actors():
    payload = fixture()
    payload["rely_guarantee"][0]["guarantee_statement"] = "false"
    source, _ = emit.emit_concurrency(rebuild(payload))
    result = lake(source, TRACES + """
example : rely_0 workerTrace := by
  constructor
  · intro time _; trivial
  · intro time _; trivial
example : ¬ contract_0 workerTrace := by
  intro claim
  have rely : rely_0 workerTrace := by
    constructor <;> (intro time _; trivial)
  exact claim rely 0 rfl
example : guarantee_0 peerTrace := by
  intro time wrong
  simp [peerTrace, stepActor] at wrong
""")
    assert result["status"] == "passed", result
    failed = lake(source, TRACES + "example : guarantee_0 workerTrace := by simp [guarantee_0, workerTrace, stepActor]")
    assert failed["status"] == "failed"


def test_false_internal_interference_excludes_matching_actor_without_forbidding_other_actors():
    payload = fixture()
    payload["interference"][0]["statement"] = "false"
    source, _ = emit.emit_concurrency(rebuild(payload))
    result = lake(source, TRACES + """
def environmentTrace : Execution Nat := ⟨fun _ => store, fun _ => Step.s3⟩
example : ¬ interference_0 environmentTrace := by
  intro claim
  exact claim 0 rfl
example : interference_0 workerTrace := by
  intro time wrong
  simp [workerTrace, stepActor] at wrong
""")
    assert result["status"] == "passed", result


def test_finite_schedule_selection_is_not_erased():
    payload = fixture()
    payload["schedules"][0]["step_ids"] = ["step:b"]
    source, _ = emit.emit_concurrency(rebuild(payload))
    result = lake(source, """
example : schedule_0 [Step.s1] := by simp [schedule_0, stepEnabled]
example : ¬ schedule_0 [Step.s0] := by simp [schedule_0, stepEnabled]
example : ¬ schedule_0 [Step.s3] := by simp [schedule_0, stepEnabled]
""")
    assert result["status"] == "passed", result


@pytest.mark.parametrize("field,value", [
    ("guard_statement", "buffer > 0"), ("guard_statement", "True"),
    ("effect_statement", "x := 1"), ("effect_statement", "may read buffer"),
    ("read_variable_ids", ["x"]), ("write_variable_ids", ["x"]),
    ("attributes", {"operation": "write"}),
])
def test_unknown_step_semantics_fail_closed(field, value):
    payload = fixture()
    payload["steps"][0][field] = value
    with pytest.raises(UnsupportedNativeLean):
        emit.emit_concurrency(rebuild(payload))


@pytest.mark.parametrize("mutation", [
    lambda p: p["metadata"].update(source_behavior="safe"),
    lambda p: p["atomic_regions"][0].update(statement="all accesses linearize"),
    lambda p: p["atomic_regions"][0].update(atomicity="locked"),
    lambda p: p["atomic_regions"][0].update(step_ids=["step:a", "step:blocked"]),
    lambda p: p["steps"][0].update(atomic_region_id=""),
    lambda p: p["steps"][2].update(atomic_region_id="atomic:a"),
    lambda p: p["interference"][0].update(kind="read"),
    lambda p: p["interference"][0].update(statement="environment is harmless"),
    lambda p: p["interference"][0].update(shared_variable_ids=["x"]),
    lambda p: p["fairness"][0].update(statement="some fairness"),
    lambda p: p["fairness"][0].update(step_ids=["step:a", "step:b"]),
    lambda p: p["fairness"][0].update(component_ids=["comp:a"]),
    lambda p: p["rely_guarantee"][0].update(rely_statement="x remains positive"),
    lambda p: p["rely_guarantee"][0].update(guarantee_statement="x increases"),
    lambda p: p["rely_guarantee"][0].update(shared_variable_ids=["x"]),
    lambda p: p["interference"][0].update(subject_component_id="comp:b"),
    lambda p: p["schedules"][0].update(statement="all possible schedules"),
    lambda p: p["schedules"][0].update(max_steps=1048577),
    lambda p: p["schedules"][0].update(component_ids=["comp:a", "comp:b"]),
])
def test_additional_semantic_constraints_are_never_silently_dropped(mutation):
    payload = fixture()
    mutation(payload)
    with pytest.raises(UnsupportedNativeLean):
        emit.emit_concurrency(rebuild(payload))


def test_exact_native_identity_unknown_fields_and_authority_claims_are_rejected():
    payload = fixture()
    changed = copy.deepcopy(payload)
    changed["steps"][0]["guard_statement"] = "false"
    with pytest.raises(ValueError):
        emit.emit_concurrency(changed)
    changed = copy.deepcopy(payload)
    changed["unrecognized_semantics"] = True
    with pytest.raises(ValueError):
        emit.emit_concurrency(changed)
    changed = copy.deepcopy(payload)
    changed["schedules"][0]["claims_unbounded_refinement"] = True
    with pytest.raises(ValueError):
        emit.emit_concurrency(changed)
    changed = copy.deepcopy(payload)
    changed["components"][0]["step_ids"].append("step:environment")
    with pytest.raises(ValueError):
        emit.emit_concurrency(changed)


@pytest.mark.parametrize("key", ["steps", "components"])
def test_empty_native_model_is_rejected_before_emitting_lookup_cases(key):
    payload = fixture()
    payload[key] = []
    payload.pop("document_id", None)
    with pytest.raises(ValueError, match="at least one"):
        emit.emit_concurrency(payload)


def test_oversized_payload_rejected_before_native_validation():
    payload = fixture()
    payload["metadata"] = {"text": "x" * 262145}
    with pytest.raises(UnsupportedNativeLean, match="bounded_concurrency_payload"):
        emit.emit_concurrency(payload)


def test_rich_producer_consumer_example_remains_explicitly_unsupported():
    from tests.unit.logic.software_verification.test_concurrency_refinement import _producer_consumer
    # This imported native fixture contains channels, sessions, opaque arithmetic
    # and prose contracts. No fixture transformation is allowed to hide them.
    value = _producer_consumer()
    with pytest.raises(UnsupportedNativeLean):
        emit.emit_concurrency(value.to_dict())


def test_guard_mutation_changes_the_operational_result_and_retains_provenance():
    payload = fixture()
    baseline, baseline_details = emit.emit_concurrency(payload)
    payload["steps"][0]["guard_statement"] = "false"
    source, details = emit.emit_concurrency(rebuild(payload))
    assert source != baseline and details["payload_sha256"] != baseline_details["payload_sha256"]
    result = lake(source, TRACES + "example : ¬ stepRelation Step.s0 store store := by simp [stepRelation, stepEnabled]")
    assert result["status"] == "passed", result
    failed = lake(source, TRACES + "example : stepRelation Step.s0 store store := ⟨rfl, rfl⟩")
    assert failed["status"] == "failed"
