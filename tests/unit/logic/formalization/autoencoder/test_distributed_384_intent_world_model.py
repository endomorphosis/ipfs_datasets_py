"""Unchanged predictions acquire only explicit, source-bound state models."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import intent_world_model as api
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import digest
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projections_v2 import (
    prepare_candidate_projection, check_candidate_projection)
from .test_distributed_384_projections_v2 import sample, FORMULA_FAMILIES, formula_inputs
from .test_distributed_384_projection_inputs import guarded_row


def atomic_model(row):
    required = api.world_model_requirements(row["target"], row["source_text"])
    assert len(required["actions"]) == 1
    ref = required["source_ref_ids"][0]
    return dict(schema=api.SCHEMA, native_document_sha256=required["native_document_sha256"],
        evidence_ref=ref, max_steps=8,
        variables=[dict(variable_id="classified", kind="boolean", domain=[False, True],
                        initial_values=[False], evidence_ref=ref)],
        predicate_bindings=[], effect_bindings=[], retry_bounds=[],
        action_updates=[dict(action_id=required["actions"][0]["action_id"], evidence_ref=ref,
            outcomes=[dict(values={"classified": True}, evidence_ref=ref)])])


def test_original_atomic_prediction_retained_while_declared_world_closes_dependencies():
    row = sample("intent_ir")
    target = deepcopy(row["target"])
    inputs = formula_inputs("intent_ir", row)
    context = api.bind_intent_world_model(target, row["source_text"], atomic_model(row), additional_inputs=inputs)
    prepared = prepare_candidate_projection("intent_ir", target, row["source_text"],
        context=context, required_families=FORMULA_FAMILIES)
    report = prepared.report
    assert report["all_requested_dependencies_supported"]
    assert prepared.candidate == target == row["target"]
    assert report["candidate_sha256"] == digest(target)
    assert not report["context_inferred_by_model"] and not report["source_semantics_verified"]
    assert not report["complete_target_semantics"] and not report["proof_authority"]
    assert len(report["native_report"]["superseded_guarded_observations"]) >= 3


@pytest.mark.parametrize("change", ["source", "digest", "action", "type", "evidence", "extra", "goal_truth"])
def test_world_binding_cannot_borrow_or_invent_native_semantics(change):
    row = sample("intent_ir")
    model = atomic_model(row)
    if change == "source": row["source_text"] += " Another instruction."
    elif change == "digest": model["native_document_sha256"] = "0" * 64
    elif change == "action": model["action_updates"][0]["action_id"] = "unknown"
    elif change == "type": model["action_updates"][0]["outcomes"][0]["values"]["classified"] = 1
    elif change == "evidence": model["evidence_ref"] = "foreign-source"
    elif change == "extra": model["proof_authority"] = True
    else:
        required = api.world_model_requirements(row["target"], row["source_text"])
        model["predicate_bindings"] = [dict(statement_id=required["statements"][0]["statement_id"],
            expression={"op": "literal", "value": True}, evidence_ref=model["evidence_ref"])]
    with pytest.raises(ValueError):
        api.bind_intent_world_model(row["target"], row["source_text"], model)


def test_existing_interpretation_cannot_be_silently_replaced():
    row = sample("intent_ir")
    with pytest.raises(ValueError, match="overwrite"):
        api.bind_intent_world_model(row["target"], row["source_text"], atomic_model(row),
            additional_inputs={"projection_context": {}})


def test_false_declared_effect_remains_an_unmodified_counterexample():
    row, inputs = guarded_row()
    flow = inputs["projection_context"]["state"]["workflow"]
    model = dict(schema=api.SCHEMA, native_document_sha256=flow["source_ir_sha256"],
        max_steps=10, effect_bindings=deepcopy(inputs["guarded_effect_bindings"]["bindings"]),
        **{key: deepcopy(flow[key]) for key in ("evidence_ref", "variables", "predicate_bindings", "action_updates", "retry_bounds")})
    model["action_updates"][0]["outcomes"][0]["values"]["complete"] = False
    context = api.bind_intent_world_model(row["target"], row["source_text"], model)
    report = prepare_candidate_projection("intent_ir", row["target"], row["source_text"],
        context=context, required_families=["temporal"]).report
    assert not report["all_requested_dependencies_supported"]
    payloads = [p["payload"] for p in report["native_report"]["projections"]
               if p["projection_id"].startswith("intent_ir/guarded/")]
    assert payloads and all(not p["ready_for_training"] for p in payloads)
    assert all(any(not c["passed"] for c in p["effect_checks"]) for p in payloads)


def test_cli_exposes_native_requirements_then_emits_replayable_world_context(tmp_path):
    row = sample("intent_ir")
    root = Path(__file__).resolve().parents[5]
    candidate, source, world = (tmp_path / name for name in ("candidate.json", "source.txt", "world.json"))
    candidate.write_text(json.dumps(row["target"]))
    source.write_bytes(row["source_text"].encode())
    world.write_text(json.dumps(atomic_model(row)))
    args = [sys.executable, str(root / "scripts/ops/autoencoder/run_distributed_384.py"), "intent-world",
            "--candidate", str(candidate), "--source-text", str(source)]
    result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    requirements = json.loads(result.stdout)
    assert requirements["native_document_sha256"] == atomic_model(row)["native_document_sha256"]
    assert not requirements["world_model_inferred"]
    saved = tmp_path / "context.json"
    result = subprocess.run([*args, "--world-model", str(world), "--result", str(saved)],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)
    assert context == json.loads(saved.read_text())
    report = prepare_candidate_projection("intent_ir", row["target"], row["source_text"],
        context=context, required_families=["temporal"]).report
    assert report["all_requested_dependencies_supported"]


def test_real_lake_and_sany_check_the_same_atomic_prediction_with_explicit_world(tmp_path):
    lake, java, jar = (os.environ.get(key) for key in ("IR384_TEST_LAKE_EXECUTABLE", "IR384_TEST_JAVA_EXECUTABLE", "IR384_TEST_TLA2TOOLS_JAR"))
    if not all((lake, java, jar)):
        pytest.skip("real Lake and Java17/SANY executables required")
    row = sample("intent_ir")
    context = api.bind_intent_world_model(row["target"], row["source_text"], atomic_model(row),
        additional_inputs=formula_inputs("intent_ir", row))
    prepared = prepare_candidate_projection("intent_ir", row["target"], row["source_text"],
        context=context, required_families=FORMULA_FAMILIES)
    report = check_candidate_projection(prepared, lake_executable=lake, java_executable=java,
        tla2tools_jar=jar, output_directory=tmp_path / "native")
    assert report["all_requested_dependencies_supported"] and report["all_requested_native_checks_passed"]
    assert not report["source_semantics_verified"] and not report["proof_authority"]
