"""Exercise real checkpoint advice and explicitly authored cross-source contracts.

The learned Intent action currently has no effect declarations and must abstain.
Separate authored Intent contracts exercise proofs against an unchanged, freshly
decoded Security candidate. Neither population is a new holdout or benchmark.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from ipfs_accelerate_py.agent_supervisor.runtime.intent_autoencoder_advisor import prepare_intent_advice
from ipfs_accelerate_py.agent_supervisor.runtime.security_source_program_advisor_384 import prepare_security_source_program_advice
from ipfs_accelerate_py.agent_supervisor.runtime.intent_code_effect_advisor import prepare_intent_code_effect_advice
from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects as contracts
from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects_lake as gate
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from tests.unit.logic.formalization.autoencoder.test_intent_code_effects import fixture


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wire(value))


def producers():
    result = []
    for name, module in sorted(sys.modules.items()):
        if not (name.startswith("ipfs_datasets_py.logic.")
                or name.startswith("ipfs_datasets_py.optimizers.logic_theorem_optimizer.")
                or name.startswith("ipfs_accelerate_py.agent_supervisor.runtime.")
                or name.endswith("test_intent_code_effects")):
            continue
        path = getattr(module, "__file__", None)
        if not path or not Path(path).is_file():
            continue
        result.append(dict(module=name, path=str(Path(path).resolve()), sha256=sha(Path(path).read_bytes())))
    return result


def selected_row(inputs, identity):
    return dict(id=identity, **dict(zip(("intent_source_text", "intent_candidate_ir", "code_source_text",
        "code_candidate_ir", "input_domains", "association"), inputs)))


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--lake", required=True)
parser.add_argument("--prior-run", type=Path, required=True)
parser.add_argument("--intent-descriptor", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
reproducer_bytes = Path(__file__).read_bytes()
before_sources = producers()
source_rows = json.loads((args.prior_run / "checkpoint-source-inputs.json").read_bytes())
config = json.loads((args.prior_run / "supervisor-config.json").read_bytes())
config["lake"] = None
checkpoint = Path(config["checkpoint_path"])
checkpoint_bytes = checkpoint.read_bytes()
assert sha(checkpoint_bytes) == config["checkpoint_sha256"]
descriptor_bytes = args.intent_descriptor.read_bytes()
descriptor = json.loads(descriptor_bytes)
intent_manifest_path = Path(descriptor["path"])
intent_manifest_bytes = intent_manifest_path.read_bytes()
assert sha(intent_manifest_bytes) == descriptor["sha256"]
intent_manifest = json.loads(intent_manifest_bytes)
intent_weights_path = intent_manifest_path.parent / intent_manifest["backend"]["file"]
intent_weights_bytes = intent_weights_path.read_bytes()
assert sha(intent_weights_bytes) == intent_manifest["backend"]["sha256"]
(args.output / "intent-checkpoint-descriptor.json").write_bytes(descriptor_bytes)
(args.output / "intent-checkpoint-manifest.json").write_bytes(intent_manifest_bytes)
save(args.output / "intent-checkpoint-reference.json", dict(
    kind="existing_local_paired_text_roundtrip_checkpoint", published_384_checkpoint=False,
    descriptor=dict(path=str(args.intent_descriptor), sha256=sha(descriptor_bytes), bytes=len(descriptor_bytes)),
    manifest=dict(path=str(intent_manifest_path), sha256=sha(intent_manifest_bytes), bytes=len(intent_manifest_bytes),
        schema=intent_manifest["schema"]),
    weights=dict(path=str(intent_weights_path), sha256=sha(intent_weights_bytes), bytes=len(intent_weights_bytes),
        schema=intent_manifest["backend"]["schema"])))
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
save(args.output / "execution-environment.json", dict(embedding_device=device,
    cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"),
    scope="selected device for correctness replay, not a throughput measurement"))
save(args.output / "security-config.json", config)
save(args.output / "source-inputs.json", source_rows)
security = prepare_security_source_program_advice(config=config, source_rows=source_rows)
save(args.output / "security-advice.json", security)
assert security.get("qualified_candidate_count") == 1, security
prediction = security["inference"]["rows"][0]
code_source = source_rows[0]["source_text"]
domains = config["finite_state_domains"][source_rows[0]["id"]]

# These are separately authored interpretations, not learned Intent predictions.
rows = []
for disposition in ("satisfied", "refuted", "no_enabled_cases"):
    inputs = list(fixture(disposition))
    inputs[2:5] = [code_source, deepcopy(prediction["candidate_ir"]), deepcopy(domains)]
    required = contracts.intent_code_effect_requirements(*inputs[:5])
    association = inputs[-1]
    association.update({key: required[key] for key in contracts.IDENTITY_FIELDS})
    # Keep native source references exact after selecting the real code input.
    association["expression_program"]["sources"] = deepcopy(required["code_source_refs"])
    association["expression_program"].pop("program_id", None)
    association["expression_program"] = ProgramIR.from_dict(association["expression_program"]).to_dict()
    rows.append(selected_row(inputs, disposition))
save(args.output / "authored-contract-inputs.json", rows)
execution = gate.build_intent_code_effects_lake(rows, lake_executable=args.lake,
    output_directory=args.output / "authored-native")
native = gate.verify_intent_code_effects_lake(execution, rows)
assert native["all_candidates_checked"], native.get("execution")
assert [r["bounded_effects_satisfied"] for r in native["rows"]] == [True, False, False]
assert [r["counterexample_kernel_checked"] for r in native["rows"]] == [False, True, False]

# Use the actual trained Intent advisor. Missing effects must stay missing.
instruction = "the agent may delete the report."
intent = prepare_intent_advice(instruction=instruction, checkpoint_descriptor=descriptor)
save(args.output / "intent-advice.json", intent)
save(args.output / "intent-input.json", dict(instruction=instruction, checkpoint_descriptor=descriptor))
assert intent["status"] == "semantic_candidate_advice", intent
intent_candidate = intent["report"]["candidate_intent_ir"]
assert len(intent_candidate["actions"]) == 1 and not intent_candidate["actions"][0]["effect_ids"]
required = contracts.intent_code_effect_requirements(instruction, intent_candidate, code_source,
    prediction["candidate_ir"], domains)
association = deepcopy(rows[0]["association"])
association.update({key: required[key] for key in contracts.IDENTITY_FIELDS})
association.update(action_id=intent_candidate["actions"][0]["action_id"],
    intent_evidence_ref=intent_candidate["actions"][0]["source_ref_ids"][0],
    precondition_bindings=[], effect_bindings=[])
selection = dict(schema="supervisor-intent-code-effect-config/v1", lake=None,
    contracts=[dict(id="learned-no-effects", source_id=source_rows[0]["id"],
        input_domains=domains, association=association)])
save(args.output / "learned-contract-config.json", selection)
advice = prepare_intent_code_effect_advice(instruction=instruction, intent_advice=intent,
    security_advice=security, source_rows=source_rows, config=selection)
save(args.output / "learned-contract-advice.json", advice)
assert advice["status"] == "fail_open_no_supported_contracts", advice
assert "no declared effects" in advice["native"]["rows"][0]["reason"]
assert not advice["selected_bounded_effects_satisfied"] and advice["continue_planning"]
assert not advice["native"]["backend_executed"]
assert checkpoint.read_bytes() == checkpoint_bytes and args.intent_descriptor.read_bytes() == descriptor_bytes
assert intent_manifest_path.read_bytes() == intent_manifest_bytes
assert intent_weights_path.read_bytes() == intent_weights_bytes
assert Path(__file__).read_bytes() == reproducer_bytes
after_sources = producers()
indexed = {row["module"]: row for row in after_sources}
assert all(indexed[row["module"]] == row for row in before_sources)
save(args.output / "producer-sources.json", dict(modules=after_sources,
    reproducer_sha256=sha(reproducer_bytes), scope="listed imported modules; not complete environment"))
summary = dict(schema="intent-code-effects-development-evidence/v1",
    security_checkpoint_sha256=config["checkpoint_sha256"], security_checkpoint_loaded=True,
    security_embeddings_recomputed=True, intent_checkpoint_sha256=intent["report"]["checkpoint_sha256"],
    embedding_device=device, intent_checkpoint_family="existing_local_paired_text_roundtrip",
    intent_checkpoint_loaded=True, learned_intent_status=intent["status"],
    learned_contract_status=advice["status"], learned_effect_count=0,
    authored_contracts=[{key: r[key] for key in ("id", "effect_status", "case_count", "enabled_case_count",
        "finite_effects_kernel_checked", "bounded_effects_satisfied", "counterexample_kernel_checked")}
        for r in native["rows"]],
    authored_intent_learned=False, source_semantics_verified=False, proof_authority=False,
    whole_instruction_verified=False, training_executed=False, weights_changed=False,
    new_holdout_evaluation=False, terminal_bench_executed=False, full_daemon_executed=False,
    source_executed=False, provider_calls=0)
save(args.output / "summary.json", summary)
print(json.dumps(summary))
