"""Real checkpoint/supervisor replay plus authored finite arithmetic controls.

Run with the matching datasets and accelerate checkouts on PYTHONPATH. No
training, downloads, source Python execution or provider calls are performed.
The one checkpoint instruction is an existing tuning control, not a holdout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from ipfs_datasets_py.logic.formalization.autoencoder.source_state_lake import (
    build_source_state_lake, verify_source_state_lake)
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression
from ipfs_accelerate_py.agent_supervisor.runtime.security_source_program_advisor_384 import (
    prepare_security_source_program_advice, STATE_CONFIG_SCHEMA)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


def read(path):
    return json.loads(path.read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def producers():
    import ipfs_datasets_py
    import ipfs_accelerate_py
    roots = {"datasets": Path(ipfs_datasets_py.__file__).resolve().parent.parent,
             "accelerate": Path(ipfs_accelerate_py.__file__).resolve().parent.parent}
    result = []
    for name, module in sorted(list(sys.modules.items())):
        owner = ("accelerate" if name.startswith("ipfs_accelerate_py.agent_supervisor.runtime.")
            else "datasets" if name.startswith(("ipfs_datasets_py.logic.formalization.autoencoder.",
                "ipfs_datasets_py.optimizers.logic_theorem_optimizer.")) else None)
        path = getattr(module, "__file__", None)
        if owner is not None and path and Path(path).suffix == ".py":
            path = Path(path).resolve()
            relative = path.relative_to(roots[owner]).as_posix()
            result.append(dict(repository=owner, module=name, path=relative, sha256=sha(path.read_bytes())))
    return dict(schema="source-state-replay-producer-sources/v1", modules=result,
        reproducer_sha256=sha(Path(__file__).read_bytes()),
        scope="loaded advisor/inference module source files; native gate receipts separately pin native owners; not an OS or external-library capsule")


def control(operator, temporary):
    kind = "boolean" if operator in ("<", "<=", ">", ">=", "==", "!=") else "integer"
    source = "def compute(left: int, right: int) -> " + ("bool" if kind == "boolean" else "int") + ":\n"
    expression = "left " + operator + " right"
    source += ("    answer = " + expression + "\n    return answer\n" if temporary else "    return " + expression + "\n")
    ids = ("expr:left", "expr:right")
    return dict(id=("temporary:" if temporary else "direct:") + operator, source_text=source,
        candidate_ir=dict(kind="program_expression", document=ProgramExpression(
            "expr:result", "binary", kind, operand_ids=ids, evaluation_order=ids,
            operator=operator, source_ref_ids=("source",)).to_dict()),
        input_domains={name: dict(lower=-1, upper=1) for name in ("left", "right")})


def compact(receipt):
    return dict(status=receipt["status"], candidates=receipt["count"],
        supported_candidates=receipt["supported_count"],
        cases=sum(row.get("case_count", 0) for row in receipt["rows"]),
        all_candidates_checked=receipt["all_candidates_checked"],
        finite_correspondence_kernel_checked=receipt["finite_correspondence_kernel_checked"],
        lake_passed=sum(row["lake_status"] == "passed" for row in receipt["rows"]),
        sany_passed=sum(row["sany_status"] == "passed" for row in receipt["rows"]),
        source_semantics_verified=False, proof_authority=False, model_checker_executed=False)


p = argparse.ArgumentParser()
p.add_argument("--training-round", type=Path, required=True, help="original security_ir round directory")
p.add_argument("--output", type=Path, required=True)
p.add_argument("--lake", required=True)
p.add_argument("--java", required=True)
p.add_argument("--sany-jar", required=True)
a = p.parse_args()
if a.output.exists():
    raise ValueError("fresh output required")
a.output.mkdir(parents=True)
before_producers = producers()
selection = read(a.training_round / "merged-result.json")
plan = read(a.training_round / "coordinator/plan.json")
provenance = plan["dataset"]["source"]
assert provenance["redistribution_allowed"] is True
assert provenance["source_path"] == "tests/fixtures/logic/source_reconstruction_v3.py"
checkpoint_path = Path(selection["checkpoint_path"])
checkpoint_hash = sha(checkpoint_path.read_bytes())
assert checkpoint_hash == "2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5"
row = read(a.training_round / "coordinator/validation.json")[0]
source = row["source_text"]
assert source == "def derive(capacity: int, threshold: int) -> int:\n    return capacity + threshold\n"
sources = [dict(id="checkpoint-source.py", source_text=source, source_sha256=sha(source.encode()))]
domains = {"checkpoint-source.py": {name: dict(lower=-1, upper=1) for name in ("capacity", "threshold")}}
config = dict(schema=STATE_CONFIG_SCHEMA, checkpoint_path=str(checkpoint_path),
    checkpoint_sha256=checkpoint_hash, decoder="structured", embedding_snapshot_path=None,
    lake=dict(executable=a.lake, timeout_seconds=60), finite_state_domains=domains)
save(a.output / "checkpoint-source-inputs.json", sources)
save(a.output / "supervisor-config.json", config)
save(a.output / "source-provenance.json", provenance)
save(a.output / "published-checkpoint-reference.json", selection["publication"])
started = time.monotonic()
advice = prepare_security_source_program_advice(config=config, source_rows=sources)
save(a.output / "supervisor-advice.json", advice)
assert advice["inference"] is not None, advice
assert advice["inference"]["checkpoint_sha256"] == checkpoint_hash
assert advice["source_state"]["native"] is not None, advice["source_state"]
native = advice["source_state"]["native"]
assert native["all_candidates_checked"] and native["finite_correspondence_kernel_checked"], native["status"]
assert advice["source_state"]["live_build_verified"]
prediction = advice["inference"]["rows"][0]
rows = [dict(id=prediction["id"], source_text=source, candidate_ir=prediction["candidate_ir"],
    input_domains=domains["checkpoint-source.py"])]
save(a.output / "checkpoint-state-rows.json", rows)
tools = dict(lake_executable=a.lake, java_executable=a.java, tla2tools_jar=a.sany_jar)
handle = build_source_state_lake(rows, **tools, output_directory=a.output / "checkpoint-native")
checkpoint_result = verify_source_state_lake(handle, rows)
assert checkpoint_result["all_candidates_checked"]
assert sha(checkpoint_path.read_bytes()) == checkpoint_hash
checkpoint_summary = dict(checkpoint_sha256=checkpoint_hash, existing_tuning_row_id=row["id"],
    elapsed_seconds=time.monotonic()-started, supervisor_used=True, checkpoint_loaded=True,
    embeddings_recomputed=True, source_executed=False, **compact(checkpoint_result))
print(json.dumps(dict(checkpoint=checkpoint_summary)), flush=True)
controls = []
for temporary in (False, True):
    rows = [control(op, temporary) for op in ("+", "-", "*", "<", "<=", ">", ">=", "==", "!=")]
    label = "temporary" if temporary else "direct"
    save(a.output / "controls" / label / "inputs.json", rows)
    handle = build_source_state_lake(rows, **tools, output_directory=a.output / "controls" / label / "native")
    report = verify_source_state_lake(handle, rows)
    assert report["all_candidates_checked"], report["execution"]
    controls.append(dict(name=label, learned_candidates=False, **compact(report)))
    print(json.dumps(controls[-1]), flush=True)
after_producers = producers()
indexed = {(r["repository"], r["path"]): r["sha256"] for r in after_producers["modules"]}
assert all(indexed[(r["repository"], r["path"])] == r["sha256"] for r in before_producers["modules"])
assert after_producers["reproducer_sha256"] == before_producers["reproducer_sha256"]
save(a.output / "producer-sources.json", after_producers)
save(a.output / "summary.json", dict(schema="source-derived-finite-state-development-evidence/v1",
    checkpoint=checkpoint_summary, authored_controls=controls, training_executed=False,
    weights_changed=False, new_holdout_evaluation=False, terminal_bench_executed=False,
    provider_calls=0, source_executed=False, source_semantics_verified=False,
    proof_authority=False, admitted=False, qualified=False,
    scope="one existing tuning prediction through the supervisor plus separate authored scalar controls"))
