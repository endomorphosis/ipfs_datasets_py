"""Native TLA/Lean correspondence boundaries and actual local parser checks."""
import copy
from pathlib import Path
import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_tla_projection as tla
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake as lake
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.software_verification.state import StateSchema, StateVariable, FiniteDomainBound, StatePredicate
from ipfs_datasets_py.logic.software_verification.transitions import StateTransitionIR, Action, ActionFrame, TransitionRelation

JAVA = Path.home()/".local/share/ipfs_datasets_py/theorem-provers/advisors/temurin-jdk/17.0.20+8/jdk/bin/java"
JAR = Path.home()/".local/share/ipfs_datasets_py/theorem-provers/tlc/1.8.0/tla2tools.jar"


def state(*, stutter=False):
    schema=StateSchema(variables=(
        StateVariable("var:x","x","integer","finite",domain_bound=FiniteDomainBound("bound:x",lower=0,upper=1)),
        StateVariable("var:b","b","boolean","finite",domain_bound=FiniteDomainBound("bound:b",cardinality=2))))
    initial=StatePredicate("initial","initial","x=1 and b",expression={"x":1,"var:b":True})
    nxt=StatePredicate("next","next","x=0 and not b",expression={"var:x":0,"b":False})
    action=Action("action:set","Set",ActionFrame(reads=("var:x","var:b"),writes=("var:x","var:b")),next_predicate_id="next")
    return StateTransitionIR(schema=schema,predicates=(initial,nxt),actions=(action,),
        transitions=(TransitionRelation("relation:set","action","Set",action_ids=("action:set",),allows_stutter=stutter),))


def rebuild(wire):
    wire.pop("document_id",None)
    return StateTransitionIR.from_dict(wire)


def sany(source, name="BoundedNativeState"):
    if not JAVA.is_file() or not JAR.is_file(): pytest.skip("Local Java17/SANY unavailable; no downloads")
    return tla.check_sany({"module_name":name,"model_text":source},java_executable=JAVA,tla2tools_jar=JAR)


def actual_lake(source,extra=""):
    tools=sorted((Path.home()/".elan/toolchains").glob("*/bin/lake"))
    if not tools:pytest.skip("Installed native Lake unavailable; no downloads")
    return lake._execute("namespace SecurityIR\n"+source+"\n"+extra+"\nend SecurityIR\n","SecurityIR",tools[-1],30)


def test_native_aliases_zero_and_false_preserved_in_both_artifacts():
    artifact=tla.compile_bounded_state(state(),max_steps=3)
    aliases=artifact["source_variable_aliases"]
    assert aliases["var:x"]==aliases["x"] and aliases["var:b"]==aliases["b"]
    assert aliases["x"]+"' = 0" in artifact["model_text"]
    assert aliases["b"]+"' = FALSE" in artifact["model_text"]
    assert " = false" in artifact["lean_source"] and " = (0 : Int)" in artifact["lean_source"]
    assert artifact["generated_liveness_properties"]==[] and not artifact["model_checker_executed"]
    assert "MaxSteps == 3" in artifact["model_text"] and "step' = step + 1" in artifact["model_text"]
    assert "trace (n + 1) = trace n" in artifact["lean_source"]
    assert "DeclaredStutter ==" not in artifact["model_text"]
    assert sany(artifact["model_text"])["status"]=="passed"
    fields={v["variable_id"]:"v"+str(i) for i,v in enumerate(artifact["native_document"]["schema"]["variables"])}
    initial="{ "+fields["var:x"]+" := 1, "+fields["var:b"]+" := true }"
    final="{ "+fields["var:x"]+" := 0, "+fields["var:b"]+" := false }"
    extra="example : boundedNext { state := "+initial+", steps := 0, lastLabel := \"initial\" } { state := "+final+", steps := 1, lastLabel := \"action:set\" } := by simp [boundedNext, boundedTypeOK, maxSteps, next, transition_0, action_0, typeOK, predicate_1]"
    receipt=actual_lake(artifact["lean_source"],extra)
    assert receipt["status"]=="passed",receipt


def test_declared_stutter_is_distinct_from_specification_stuttering():
    artifact=tla.compile_bounded_state(state(stutter=True),max_steps=1)
    assert "DeclaredStutter == UNCHANGED" in artifact["model_text"]
    assert "actionLabel' = \"stutter\"" in artifact["model_text"]
    assert "step < MaxSteps" in artifact["model_text"] and "[][Next]_vars" in artifact["model_text"]
    assert "label = \"stutter\" ∧ t = s" in artifact["lean_source"]
    assert "s.steps < maxSteps" in artifact["lean_source"]


def intent_state():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel
    from ipfs_datasets_py.logic.formalization.autoencoder.family_training_v3 import prepare_family_training_targets_v3
    report=prepare_family_training_targets_v3("intent_ir",**panel.source_inputs(panel.rows("intent_ir","train")[0]))
    row=next(r for r in report["projections"] if r["projection_id"]=="intent-extended/transition_system/default/v1")
    return StateTransitionIR.from_dict(row["payload"]["payload"])


def test_exact_reviewed_Intent_scope_and_origins_compile_without_inventing_effects():
    artifact=tla.compile_bounded_state(intent_state(),max_steps=64)
    assert "ActionIntentOrigins == <<" in artifact["model_text"] and "intentAction" not in artifact["model_text"]
    assert '"action:abstract:0", "action:0"' in artifact["model_text"]
    assert "SourceIntentIRSHA256 ==" in artifact["model_text"] and "CodeEffectsModeled == FALSE" in artifact["model_text"]
    assert "NormativeComplianceModeled == FALSE" in artifact["model_text"]
    assert "def actionIntentOrigins : List (String × String)" in artifact["lean_source"]
    assert len(artifact["self_loop_normalization"])==1
    assert sany(artifact["model_text"])["status"]=="passed"
    receipt=actual_lake(artifact["lean_source"])
    assert receipt["status"]=="passed",receipt
    with pytest.raises(UnsupportedNativeLean,match="exact_reviewed_Intent_scope"):
        tla.compile_bounded_state(intent_state(),max_steps=63)


def test_unknown_metadata_and_claimed_runtime_events_remain_blocked():
    wire=state().to_dict();wire["metadata"]={"code_effects_modeled":True}
    with pytest.raises(UnsupportedNativeLean,match="metadata"):tla.compile_bounded_state(rebuild(wire))
    wire=state().to_dict();wire["actions"][0]["attributes"]={"UI_transition_id":"move","event_id":"click",
        "step_is_declared_possibility_not_observed_occurrence":False}
    with pytest.raises(UnsupportedNativeLean,match="UI_action"):tla.compile_bounded_state(rebuild(wire))


def test_ui_event_join_is_present_as_mapping_not_an_attested_occurrence():
    wire=state().to_dict();wire["actions"][0]["attributes"]={"UI_transition_id":"move","event_id":"click",
        "step_is_declared_possibility_not_observed_occurrence":True}
    artifact=tla.compile_bounded_state(rebuild(wire))
    assert 'ActionEventOrigins == <<<<"action:set", "move", "click">>>>' in artifact["model_text"]
    assert "RuntimeEventOccurrencesAttested == FALSE" in artifact["model_text"]
    assert 'def actionEventOrigins : List (String × String × String) := [("action:set", "move", "click")]' in artifact["lean_source"]


def test_artifact_replay_rejects_changed_model_and_unsupported_bounds():
    artifact=tla.compile_bounded_state(state())
    altered=copy.deepcopy(artifact);altered["model_text"]=altered["model_text"].replace("MaxSteps == 64","MaxSteps == 65")
    with pytest.raises(UnsupportedNativeLean,match="replay_differs"):
        tla.emit_projection({"profile":"tla_plus","payload":altered})
    for bound in (0,True,1025):
        with pytest.raises(UnsupportedNativeLean,match="step_count"):tla.compile_bounded_state(state(),max_steps=bound)


def test_missing_sany_has_no_syntax_execution_evidence():
    result=tla.check_sany({"module_name":"Absent","model_text":"anything"})
    assert result["status"]=="blocked" and result["executed"] is False


def test_zero_exit_non_java_program_is_not_syntax_evidence(tmp_path):
    jar=tmp_path/"existing.jar";jar.write_bytes(b"not a Java archive")
    result=tla.check_sany({"module_name":"Absent","model_text":"anything"},java_executable="/bin/true",tla2tools_jar=jar)
    assert result["status"]=="blocked" and result["executed"] is False
    assert result["reason"]=="native_Java17_or_newer_version_probe_required"


def test_java_probe_alone_without_matching_parser_stages_cannot_pass(tmp_path):
    # A misconfigured command that answers -version but does no parsing must
    # not turn zero exit status into positive syntax evidence.
    script=tmp_path/"misconfigured-java"
    script.write_text('#!/bin/sh\nif [ "$1" = "-version" ]; then echo \'openjdk version "17.0.20"\'; fi\nexit 0\n')
    script.chmod(0o700)
    jar=tmp_path/"existing.jar";jar.write_bytes(b"not a Java archive")
    result=tla.check_sany({"module_name":"Absent","model_text":"anything"},java_executable=script,tla2tools_jar=jar)
    assert result["status"]=="failed" and result["executed"] is True
    assert not result["matching_module_parse_observed"] and not result["matching_module_semantic_processing_observed"]


@pytest.mark.parametrize("source",[
    "---- MODULE Broken ----\nVARIABLE x\nBad == (\n====\n",
    "---- MODULE Broken ----\nVARIABLE x\nBad == []x'\n====\n",
])
def test_sany_rejects_malformed_and_temporal_level_invalid_formulas(source):
    receipt=sany(source,"Broken")
    assert receipt["status"]=="failed" and receipt["executed"] is True and receipt["returncode"]!=0,receipt
    assert "-error-codes" in receipt["command"] and receipt["level_checking_enabled"] is True


def ui_state():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel
    from ipfs_datasets_py.logic.formalization.autoencoder.family_training_v3 import prepare_family_training_targets_v3
    report=prepare_family_training_targets_v3("ui_ux_ir",**panel.source_inputs(panel.rows("ui_ux_ir","train")[0]))
    row=next(r for r in report["projections"] if r["projection_id"]=="ui_ux_ir/declared_state/native/v2")
    return StateTransitionIR.from_dict(row["payload"]["native_document"])


def test_actual_panel_UI_state_retains_terminal_and_cancelable_declarations_only():
    artifact=tla.compile_bounded_state(ui_state(),max_steps=4)
    assert 'UIStateMap == <<<<"finished", "state_0">>, <<"pending", "state_1">>>>' in artifact["model_text"]
    assert 'UITerminalStates == {"state_0"}' in artifact["model_text"]
    assert 'UIDeclaredCancelableActions == {"action:ui:0"}' in artifact["model_text"]
    assert "CancellationExecutionModeled == FALSE" in artifact["model_text"]
    assert artifact["cancellation_execution_modeled"] is False and artifact["actual_event_occurrence_asserted"] is False
    assert 'def uiTerminal (s : State)' in artifact["lean_source"] and 'def uiDeclaredCancelable (action : String)' in artifact["lean_source"]
    assert '[][Next]_vars' in artifact["model_text"] and not artifact["generated_liveness_properties"]
    assert sany(artifact["model_text"])["status"]=="passed"
    extra='example : uiTerminal { v0 := "state_0" } := by simp [uiTerminal, uiTerminalStates]\nexample : uiDeclaredCancelable "action:ui:0" = true := by decide'
    result=actual_lake(artifact["lean_source"],extra)
    assert result["status"]=="passed",result


@pytest.mark.parametrize("change,reason",[
    (lambda m:m.update(source_sha256="0"*64),"source_reference_metadata_digest"),
    (lambda m:m["state_map"].update(finished="state_1"),"bijection"),
    (lambda m:m["origins"][0].update(from_state="state_0"),"origin_or_terminal"),
    (lambda m:m["terminal_states"].append("state_1"),"origin_or_terminal"),
    (lambda m:m["origins"][0]["transition"].update(cancelable=False),"recovery"),
    (lambda m:m["origins"][0]["transition"].update(cancelable=1),"recovery"),
    (lambda m:m["origins"][0]["transition"].update(priority=False),"recovery"),
    (lambda m:m["origins"][0]["transition"].update(retryable=0),"recovery"),
    (lambda m:m["origins"][0]["transition"].update(extra=False),"closed_transition"),
    (lambda m:m["origins"].clear(),"all_action_origins"),
    (lambda m:m["origins"].append(copy.deepcopy(m["origins"][0])),"all_action_origins"),
])
def test_UI_metadata_changes_cannot_borrow_declared_state_validation(change,reason):
    wire=ui_state().to_dict();change(wire["metadata"])
    with pytest.raises(UnsupportedNativeLean,match=reason):tla.compile_bounded_state(rebuild(wire))


def test_extra_UI_predicate_and_changed_origin_event_join_reject():
    wire=ui_state().to_dict();extra=copy.deepcopy(wire["predicates"][0]);extra["predicate_id"]="extra";wire["predicates"].append(extra)
    with pytest.raises(UnsupportedNativeLean,match="extra_or_missing_native_predicate"):tla.compile_bounded_state(rebuild(wire))
    wire=ui_state().to_dict();wire["actions"][0]["attributes"]["event_id"]="changed"
    with pytest.raises(UnsupportedNativeLean,match="action_event_origin_differs"):tla.compile_bounded_state(rebuild(wire))
