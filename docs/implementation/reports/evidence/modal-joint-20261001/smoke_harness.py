"""Authored synthetic integration smoke. No pretrained downloads or admission."""
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import torch

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
api = importlib.import_module(PREFIX + ".autoencoder_runtime_registry")
schema = importlib.import_module(PREFIX + ".autoencoder_decoded_schema")
learning = importlib.import_module(PREFIX + ".modal_latent_formula")
fixture = ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_modal_joint_formula.py"
spec = importlib.util.spec_from_file_location("modal_e2e_fixture", fixture)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
torch.set_num_threads(1)

def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))

def sample_rows(version):
    lineage = importlib.import_module(PREFIX + ".autoencoder_lineages." + version)
    return lineage, fixtures._training_rows(lineage)

if len(sys.argv) > 1 and sys.argv[1] == "reload":
    version = sys.argv[2]
    folder = OUT / version
    info = json.loads((folder / "checkpoint-info.json").read_text())
    runtime = api.LegalRuntime(version, compute_device="cpu", formula_checkpoint=folder / "formula-head.json",
                               formula_sha256=info["sha256"])
    _, (rows, _, _, _) = sample_rows(version)
    start = time.monotonic()
    result = runtime.infer(rows)
    write(folder / "fresh-process-inference.json", {"inference": result,
        "elapsed_seconds": time.monotonic() - start,
        "checkpoint_sha256": learning.checkpoint_digest(runtime.model.formula_checkpoint),
        "training_executed": False, "weights_downloaded": False})
    raise SystemExit(0)

started = time.monotonic()
report = {"schema": "modal-joint-decoder-e2e-smoke/v1", "source_kind": "authored_synthetic_integration_fixture",
          "scope": "separate_8d_and_384d_heads_joint_training_and_actual_decoded_schema_builds",
          "lineages": [], "qualified": False, "admitted": False, "formalized": False,
          "roundtrip_ok": False, "held_out_semantic_evaluation": False, "semantic_embeddings_verified": False,
          "parser_features_in_input": True, "independent_text_to_logic": False,
          "sample_memory_used": False, "temperature": 0, "weights_downloaded": False,
          "hub_uploads_performed": False, "supported_logic_families": ["deontic"],
          "full_family_coverage_verified": False, "bridges": {"names": [], "legal_ir_target_count": 0,
          "evaluate_provers": False, "metric_disk_cache": False, "workers": 1,
          "is_bridge_on_speed_measurement": False}, "torch_threads": torch.get_num_threads(),
          "device": "cpu", "training_schedule": {"epochs": 250, "max_seconds": 60}}
for version in ("legacy_v1", "current_v2"):
    folder = OUT / version
    folder.mkdir(exist_ok=False)
    lineage, (rows, tuning, targets, tuning_targets) = sample_rows(version)
    runtime = api.LegalRuntime(version, compute_device="cpu")
    before = runtime.model.state.to_dict()
    start = time.monotonic()
    training = runtime.train(rows, validation_samples=tuning,
        formula_targets=targets, validation_formula_targets=tuning_targets,
        formula_options={"learning_rate": .03, "batch_size": 2, "hidden_size": 16,
            "token_embedding_dim": 8, "projection_width": 4, "seed": 1729}, epochs=250, max_seconds=60)
    training_elapsed = time.monotonic() - start
    write(folder / "training-report.json", training["report"])
    checkpoint_info = runtime.model.save_formula_checkpoint(folder / "formula-head.json")
    write(folder / "checkpoint-info.json", checkpoint_info)
    start = time.monotonic()
    inference = runtime.infer(rows)
    inference_elapsed = time.monotonic() - start
    write(folder / "inference.json", inference)
    lake = schema.validate_decoded_outputs(runtime, rows, output_directory=folder / "schema")
    env = dict(os.environ, PYTHONPATH=str(ROOT), HF_HUB_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
    with (folder / "reload.log").open("wb") as stream:
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "reload", version],
                               cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    reloaded_path = folder / "fresh-process-inference.json"
    reloaded = json.loads(reloaded_path.read_text()) if reloaded_path.is_file() else None
    exact = all(row["canonical_ir"] == target["canonical_ir"] for row, target in zip(inference["rows"], targets))
    observations = {"runtime_version": version, "dimension": lineage.DIMENSION,
        "training_sample_count": len(rows), "tuning_sample_count": len(tuning),
        "samples_are_authored_synthetic": True, "numeric_core_is_fresh_empty_frozen_fixture": True,
        "archived_checkpoints_used": False, "training_report": training["report"],
        "core_unchanged": before == runtime.model.state.to_dict(), "checkpoint_info": checkpoint_info,
        "training_wall_seconds": training_elapsed, "inference_wall_seconds": inference_elapsed,
        "inference_wall_seconds_per_span": inference_elapsed / len(rows),
        "inference": inference, "training_target_ast_exact_count": sum(row["canonical_ir"] == target["canonical_ir"]
            for row, target in zip(inference["rows"], targets)), "schema_report": lake,
        "fresh_process_reload_returncode": child.returncode,
        "fresh_process_exact_inference_match": reloaded is not None and reloaded["inference"] == inference,
        "fresh_process_checkpoint_sha256": None if reloaded is None else reloaded["checkpoint_sha256"],
        "passed_integration": exact and lake["schema_checks_complete"] and child.returncode == 0
            and reloaded is not None and reloaded["inference"] == inference}
    report["lineages"].append(observations)
report["elapsed_seconds"] = time.monotonic() - started
report["passed_integration"] = all(item["passed_integration"] for item in report["lineages"])
report["lake_build_count"] = sum(item["schema_report"]["lake_build_count"] for item in report["lineages"])
report["schema_pass_count"] = sum(item["schema_report"]["schema_pass_count"] for item in report["lineages"])
write(OUT / "report.json", report)
print(json.dumps({key: report[key] for key in ("passed_integration", "elapsed_seconds", "lake_build_count", "schema_pass_count")}, indent=2))
raise SystemExit(0 if report["passed_integration"] else 1)
