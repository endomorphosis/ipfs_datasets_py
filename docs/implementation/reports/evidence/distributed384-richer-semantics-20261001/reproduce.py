"""Replay unchanged models with explicit interpretations and real checkpoints.

All extra semantics are authored development controls. No training, source
correctness, holdout improvement, or successful security claim is implied.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts as c
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context, validate_context
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_inputs import security_source_ref
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.intent_world_model import bind_intent_world_model
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projections_v2 import prepare_candidate_projection, check_candidate_projection
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.qualification import qualify_round, CONTEXTS_SCHEMA
from ipfs_datasets_py.logic.formalization.autoencoder.structured_source_384 import Runtime
from tests.unit.logic.formalization.autoencoder.test_native_concurrency_interpretation import authored_interpretation as concurrency_interpretation
from tests.unit.logic.formalization.autoencoder.test_native_protocol_frames import authored_interpretation as protocol_interpretation
from tests.unit.logic.formalization.autoencoder.test_native_symbolic_refinement_lean import authored_interpretation as refinement_interpretation
from tests.unit.logic.formalization.autoencoder.test_distributed_384_intent_world_model import atomic_model
from tests.unit.logic.formalization.autoencoder.test_distributed_384_supplemental_native_lake import bound_protocol

OWNERS = dict(concurrency=concurrency_interpretation, protocol=protocol_interpretation, refinement=refinement_interpretation)


def interpretations(models):
    return [dict(kind=row["kind"], interpretation=OWNERS[row["kind"]](row["document"]))
            for row in models if row["kind"] in OWNERS]


def compact(report):
    execution = report["native_execution"]
    rows = execution["per_projection"]
    syntax = [check for row in rows for check in row.get("additional_syntax_checks", [])]
    counterexamples = []
    for row in rows:
        details = row.get("lowering") or {}
        for claim in details.get("static_frame_interpretation", {}).get("claim_evaluations", []):
            if claim["counterexample_found"]:
                counterexamples.append(dict(projection_id=row["projection_id"], **claim,
                    generated_refutation_compiled=row["lake_status"] == "passed"))
    return dict(domain_id=report["domain_id"], source_sha256=report["source_sha256"],
        candidate_sha256=report["candidate_sha256"], context_sha256=report["context_sha256"],
        required_families=len(report["families"]), supported_families=sum(f["status"] == "supported" for f in report["families"]),
        all_requested_dependencies_supported=report["all_requested_dependencies_supported"],
        all_requested_native_checks_passed=report["all_requested_native_checks_passed"],
        native_projections=len(rows), complete_checks=sum(r["lake_status"] == "passed" and r["parser_status"] == "passed" for r in rows),
        sany_checks=len(syntax), sany_passed=sum(x["status"] == "passed" for x in syntax),
        protocol_counterexamples=counterexamples,
        unsupported_rows=[dict(projection_id=r["projection_id"], reason=r["reason"]) for r in rows if not r["semantic_lowering_supported"]],
        source_semantics_verified=False, proof_authority=False, admitted=False, qualified=False,
        context_inferred_by_model=False)


p = argparse.ArgumentParser()
p.add_argument("--prior-evidence", type=Path, required=True)
p.add_argument("--training-round", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--lake", required=True)
p.add_argument("--java", required=True)
p.add_argument("--sany-jar", required=True)
a = p.parse_args()
if a.output.exists():
    raise ValueError("fresh output required")
a.output.mkdir(parents=True)
baseline = a.prior_evidence / "authored/run-01/unchanged-original-context"
original = c.read_json(baseline / "source-candidate.json")
old_context = c.read_json(baseline / "context.json")
models = deepcopy(old_context["inputs"]["supplemental_inputs"])
families = c.read_json(baseline / "report.json")["requested_families"]
new_inputs = deepcopy(old_context["inputs"])
new_inputs["supplemental_interpretations"] = interpretations(models)
new_context = bind_context("security_ir", original["candidate_ir"], original["source_text"], new_inputs)
authored = []
native_reports = []
for name, context in (("without-interpretations", old_context), ("with-explicit-interpretations", new_context)):
    directory = a.output / "authored" / name
    c.write_json(directory / "source-candidate.json", original)
    c.write_json(directory / "context.json", context)
    handle = prepare_candidate_projection("security_ir", original["candidate_ir"], original["source_text"],
        context=context, required_families=families)
    native_reports.append(handle.native_report)
    result = check_candidate_projection(handle, lake_executable=a.lake, java_executable=a.java,
        tla2tools_jar=a.sany_jar, output_directory=directory / "native")
    c.write_json(directory / "report.json", result)
    summary = dict(name=name, original_models_rewritten=False, learned_output=False, **compact(result))
    c.write_json(directory / "summary.json", summary)
    authored.append(summary)
    print(json.dumps(summary), flush=True)
assert native_reports[0] == native_reports[1], "interpretation changed the original native report"
assert authored[1]["all_requested_native_checks_passed"] and authored[1]["supported_families"] == 16

checkpoints = []
for domain in ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir"):
    old = a.training_round / domain
    published = c.read_json(old / "merged-result.json")
    checkpoint_path = Path(published["checkpoint_path"])
    checkpoint, checkpoint_ref = c.read_json_bound(checkpoint_path)
    plan = c.read_json(old / "coordinator/plan.json")
    raw = c.read_json(old / "coordinator/validation.json")[0]
    row = {key: raw[key] for key in ("id", "source_text", "embedding")}
    prediction = Runtime(checkpoint).infer([row])["rows"][0]
    candidate = prediction["candidate_ir"]
    prior_dir = a.prior_evidence / "checkpoints-run-01" / domain
    previous_context = c.read_json(prior_dir / "declared-context.json")["rows"][0]["context"]
    inputs = validate_context(previous_context, domain, candidate, row["source_text"])
    if domain == "intent_ir":
        assert row["source_text"] == "The dispatcher must classify the manifest.", "authored world only applies to the reviewed tuning fixture"
        model = atomic_model(dict(target=candidate, source_text=row["source_text"]))
        context = bind_intent_world_model(candidate, row["source_text"], model, additional_inputs=inputs)
        c.write_json(a.output / "checkpoints" / domain / "authored-world-model.json", model)
    elif domain == "security_ir":
        source = security_source_ref(inputs["code_unit"], row["source_text"])
        originals = {m["kind"]: m["document"] for m in models if m["kind"] in OWNERS}
        for native in inputs["supplemental_inputs"]:
            if native["kind"] in originals:
                native["document"] = (bound_protocol(deepcopy(originals["protocol"]), source, row["source_text"])
                    if native["kind"] == "protocol" else deepcopy(originals[native["kind"]]))
        inputs["supplemental_interpretations"] = interpretations(inputs["supplemental_inputs"])
        context = bind_context(domain, candidate, row["source_text"], inputs)
    else:
        context = previous_context
    batch = dict(schema=CONTEXTS_SCHEMA, plan_id=plan["plan_id"], checkpoint_sha256=checkpoint_ref["sha256"],
        rows=[dict(id=row["id"], context=context)], **c.FALSE)
    directory = a.output / "checkpoints" / domain
    c.write_json(directory / "published-checkpoint-reference.json", published["publication"])
    path = c.write_json(directory / "declared-context.json", batch)
    selected = c.read_json(prior_dir / "checks/job.json")["requested_families"]
    summary = qualify_round(old / "coordinator", checkpoint_path, directory / "checks", contexts_path=path,
        row_ids=[row["id"]], required_families=selected,
        lake_executable=a.lake, java_executable=a.java, tla2tools_jar=a.sany_jar)
    result = c.read_json(summary["records"][0]["report_path"])
    record = dict(checkpoint=checkpoint_ref, rows=1, scope="one unchanged tuning prediction plus explicit authored interpretations",
        source_native_models_rebound_for_this_CodeUnit=domain == "security_ir", **compact(result))
    assert checkpoint_ref == c.file_ref(checkpoint_path)
    assert record["all_requested_dependencies_supported"] and record["all_requested_native_checks_passed"]
    checkpoints.append(record)
    print(json.dumps(record), flush=True)

c.write_json(a.output / "summary.json", dict(schema="distributed384-explicit-native-interpretations-evidence/v1",
    authored=authored, checkpoints=checkpoints, original_native_reports_equal=True,
    training_executed=False, weights_changed=False, new_holdout_evaluation=False,
    source_semantics_verified=False, source_claims_all_proved=False,
    context_inferred_by_model=False, proof_authority=False, admitted=False, qualified=False))
