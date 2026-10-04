"""Read-only standard-library audit of a closed actual-device qualification.

No repository owners, Git, SQL, Torch, encoder or training imports. Hashes and
native execution receipts support bounded numerical replay; this reader does
not independently attest that historical CUDA kernels executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _require(value, message):
    if not value:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite JSON token " + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def _integer(value, low, high, label):
    _require(type(value) is int and low <= value <= high, "exact bounded integer " + label + " required")


def _timing(value, label, *, zero=False):
    _require(type(value) in (int, float) and math.isfinite(value)
             and (value >= 0 if zero else value > 0) and value <= 300,
             "finite bounded timing " + label + " required")


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode, value.st_nlink)


def _snapshot(root):
    _require(root.is_dir() and not root.is_symlink(), "closed archive must be a regular directory")
    result, total = {}, 0
    paths = sorted(root.rglob("*"))
    _require(len(paths) <= 128, "bounded archive traversal required")
    for path in paths:
        before = path.lstat()
        mode = before.st_mode
        _require(not stat.S_ISLNK(mode), "archive symlink is not allowed")
        if stat.S_ISDIR(mode):
            continue
        _require(stat.S_ISREG(mode) and before.st_size <= MAX_FILE_BYTES and before.st_nlink == 1,
                 "bounded regular archive file required")
        _require(len(result) < 64, "archive file count exceeds bound")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            _require(_identity(os.fstat(handle.fileno())) == _identity(before),
                     "archive file identity changed before reading")
            raw = handle.read(MAX_FILE_BYTES+1)
            _require(_identity(os.fstat(handle.fileno())) == _identity(before),
                     "archive file identity changed during reading")
        _require(_identity(path.lstat()) == _identity(before) and len(raw) == before.st_size,
                 "archive file identity changed after reading")
        total += len(raw)
        _require(total <= MAX_TOTAL_BYTES, "archive total bytes exceed bound")
        result[str(path.relative_to(root))] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "mode": stat.S_IMODE(mode), "device": before.st_dev, "inode": before.st_ino,
            "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns, "links": before.st_nlink}
    return result


def _vectors(left, right, width):
    _require(type(left) is list and type(right) is list and len(left) == len(right), "vector row count differs")
    error = 0.
    for a, b in zip(left, right):
        _require(type(a) is list and type(b) is list and len(a) == len(b) == width, "vector width differs")
        _require(all(type(v) in (int, float) and math.isfinite(v) for v in a+b), "finite exact numeric vectors required")
        error = max(error, max((abs(x-y) for x, y in zip(a, b)), default=0.))
    _require(error <= 5e-5, "numeric device parity exceeded bound")
    return error


def _decision(row):
    return {key: row.get(key) for key in ("id", "source_sha256", "latent_sha256", "status", "reason",
            "canonical_ir", "formula_text", "formal_outputs", "generated_token_ids")}


def _false_authority(value, *, root=False):
    names = {"qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
        "source_semantics_verified", "semantic_qualification", "semantic_correctness_verified",
        "execution_authority", "promotion_performed", "training_executed", "publication_performed",
        "target_access", "teacher_forcing", "source_text_is_neural_input", "sample_memory_used",
        "independent_text_to_logic", "lake_executed"}
    if type(value) is dict:
        for key, item in value.items():
            if key in names and not (root and key == "qualified"):
                _require(item is False, "numerical receipt cannot grant " + key)
            _false_authority(item)
    elif type(value) is list:
        for item in value:
            _false_authority(item)


def validate(record, load):
    """Validate inert receipt data; the loader supplies closed, pinned bytes."""
    _require(type(record) is dict and record.get("schema") == "native-legal-formula-cuda-qualification/v1",
             "native numerical qualification schema required")
    _require(record.get("qualified") is True and record.get("error") is None, "native qualification failed")
    _require(record.get("actual_initial_cuda_kernel") is True and record["hardware"]["cuda_available"] is True,
             "actual CUDA execution receipt missing")
    _integer(record["setup_training_calls"],2,2,"setup training calls")
    _integer(record["inference_training_calls"],0,0,"inference training calls")
    _timing(record["elapsed_seconds"],"native elapsed")
    _timing(record["admission"]["wait_seconds"],"admission wait",zero=True)
    _require(record["setup_training_calls"] == 2 and record["inference_training_calls"] == 0,
             "explicit two setup fits and zero inference fits required")
    _require(record.get("own_lease_released") is True, "native device lease was not released")
    _require(record["admission"]["cpu_slots"] == 1 and record["admission"]["requires_gpu"] is True
             and record["admission"]["memory_mb"] == record["admission"]["gpu_memory_mb"] == 2048,
             "actual bounded CPU/GPU shared admission required")
    _require(record["peak_rss_bytes"] <= 2048*1024*1024
             and 0 < record["peak_gpu_allocated_bytes"] <= 2048*1024*1024,
             "observed native memory exceeded reservation")
    _false_authority(record, root=True)
    for key in ("released_weight_qualification", "codebase_feature_cuda_qualification",
                "general_codebase_384d_qualification", "execution_attestation", "kernel_resource_enforcement"):
        _require(record[key] is False, "bounded numerical scope was broadened")
    _require(type(record["source_pins"]) is list and len(record["source_pins"]) == 15,
             "complete listed producer inventory required")
    _require(len({pin["copy"] for pin in record["source_pins"]}) == 15,
             "listed producer copies must be distinct")
    for pin in record["source_pins"]:
        raw = load(pin["copy"])
        _require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
                 "frozen producer bytes differ")
    embeddings = record["embeddings"]
    _integer(embeddings["count"],32,32,"embedding rows")
    _require(embeddings["count"] == 32, "complete 32 source rows required")
    cpu, cuda = embeddings["cpu"]["report"], embeddings["cuda"]["report"]
    _require(cpu["tokens"] == cuda["tokens"] and cpu["source_sha256"] == cuda["source_sha256"],
             "device embedding token/source identities differ")
    _require(cpu["profile"]["assets"] == cuda["profile"]["assets"], "embedding assets differ")
    for label, report, device in (("cpu", cpu, "cpu"), ("cuda", cuda, "cuda:0")):
        timings = embeddings[label]
        _timing(timings["cold_load_seconds"],"encoder cold load")
        _require(type(timings["warm_boundary_seconds"]) is list and len(timings["warm_boundary_seconds"]) == 3,
                 "three native warm boundary measurements required")
        for duration in timings["warm_boundary_seconds"]:
            _timing(duration,"encoder warm boundary")
        _timing(timings["median_seconds"],"encoder median")
        _require(timings["median_seconds"] == sorted(timings["warm_boundary_seconds"])[1],
                 "native encoder median differs from observations")
        _require(report["profile"]["device"] == device and report["profile"]["dtype"] == "float32"
                 and report["profile"]["optimized"] is (label == "cuda")
                 and report["cuda_executed"] is (label == "cuda"), "actual embedding device identity differs")
        _require(len(report["tokens"]) == len(report["vectors"]) == 32, "embedding membership differs")
        _require(report["actual_forward_batches"] == [dict(rows=16, input_device=device,
            output_device=device, output_dtype="torch.float32")]*2, "actual encoder forward tensor evidence differs")
        for vector in report["vectors"]:
            _require(abs(math.sqrt(sum(v*v for v in vector))-1.) <= 2e-5, "embedding normalization differs")
    embedding_error = _vectors(cpu["vectors"], cuda["vectors"], 384)
    _require(embedding_error == embeddings["max_absolute_error"], "recorded embedding parity differs")
    _require(record["existing_default_gte_path"]["actual_model_device"] == "cuda:0"
             and record["existing_default_gte_path"]["cuda_executed"] is True,
             "existing default CUDA encoder evidence missing")
    formulas = record["formulas"]
    _require(type(formulas) is list and [f["dimension"] for f in formulas] == [8, 384],
             "separate complete native Legal lineages required")
    errors = []
    for formula in formulas:
        width = formula["dimension"]
        _integer(width,8,384,"formula dimension")
        _timing(formula["training_seconds"],"explicit training")
        artifact = formula["checkpoint"]
        raw = load("legal-" + str(width) + "-checkpoint.json")
        _require(len(raw) == artifact["bytes"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"],
                 "checkpoint bytes differ")
        saved = _parse(raw)
        _false_authority(saved)
        _require(saved["binding"] == formula["binding"] and saved["binding"]["dimension"] == width
                 and saved["binding"]["lineage_id"] == ("legacy_hub_v1" if width == 8 else "current_legal_v2"),
                 "native checkpoint lineage or actual core binding differs")
        _require(saved["progress"] == formula["training_progress"] == dict(
            epochs_completed=30, optimizer_steps=30, row_cursor=0), "explicit setup Adam progress differs")
        for key, value in (("epochs_completed",30),("optimizer_steps",30),("row_cursor",0)):
            _integer(saved["progress"][key],value,value,"retained Adam " + key)
            _integer(formula["training_progress"][key],value,value,"reported Adam " + key)
        inputs = _parse(load("legal-" + str(width) + "-training-inputs.json"))
        _require(hashlib.sha256(_raw(inputs)).hexdigest() == saved["training_manifest_sha256"],
                 "native training input manifest differs")
        _require(formula["checkpoint_and_adam_unchanged"] is True and formula["actual_native_core_unchanged"] is True,
                 "inference changed a retained numerical model")
        _require([item["count"] for item in formula["inference"]] == [1, 17, 128],
                 "full scalar and batch native replay required")
        for item in formula["inference"]:
            _integer(item["count"],1,128,"formula sample count")
            _require(set(item["inference_seconds"]) == {"cpu","cuda"}, "complete formula device timings required")
            for duration in item["inference_seconds"].values():
                _timing(duration,"formula inference")
            left, right = item["cpu"], item["cuda"]
            _require(left["checkpoint_sha256"] == right["checkpoint_sha256"] == artifact["sha256"],
                     "inference checkpoint identity differs")
            _require(left["binding"] == right["binding"] == formula["binding"], "inference binding differs")
            _require(len(left["rows"]) == len(right["rows"]) == item["count"], "formula membership differs")
            _require([_decision(row) for row in left["rows"]] == [_decision(row) for row in right["rows"]],
                     "formula status/grammar/canonical decisions differ")
            for label, value in (("cpu", left), ("cuda", right)):
                _integer(value["decoded_count"],0,item["count"],"decoded formula count")
                profile = value["inference_implementation"]
                _require(set(profile["actual_forward_calls"]) == {"projection_down","projection_up","output"},
                         "closed native forward counters required")
                for number in profile["actual_forward_calls"].values():
                    _integer(number,1,16384,"actual forward calls")
                _require(profile["device"] == ("cpu" if label == "cpu" else "cuda:0")
                         and profile["cuda_selected"] is (label == "cuda")
                         and profile["cuda_executed"] is (label == "cuda")
                         and profile["actual_forward_executed"] is True
                         and profile["actual_forward_calls"]["projection_down"] > 0
                         and profile["actual_forward_calls"]["projection_up"] > 0
                         and profile["actual_forward_calls"]["output"] > 0,
                         "actual formula forward execution evidence differs")
            _require(len(item["cpu_projected"]) == len(item["cuda_projected"]) == item["count"],
                     "complete projected vector membership required")
            error = _vectors(item["cpu_projected"], item["cuda_projected"], width)
            _require(error == item["max_absolute_error"] and item["exact_decision_parity"] is True,
                     "recorded formula device parity differs")
            errors.append(error)
    names = {control["name"] for control in record["controls"]}
    _require(len(record["controls"]) == 6 and names == {"overlong_token_input", "129_embedding_rows", "foreign_process_embedding_session",
        "embedding_tensor_data_mutation", "formula_target_access", "formula_tensor_data_mutation"}
        and all(control["rejected"] is True for control in record["controls"]), "native guard controls missing")
    return {"native_lineages": [8, 384], "embedding_rows_per_replay": 32,
            "formula_rows_per_device_per_lineage": 146, "embedding_max_absolute_error": embedding_error,
            "formula_max_absolute_error": max(errors), "authority_preserved": True,
            "no_native_owner_or_execution": True}


def audit(root):
    # Resolving first would erase evidence that the caller supplied a symlink.
    root = Path(root).absolute()
    started = time.monotonic()
    before = _snapshot(root)
    root_before = _identity(root.lstat())
    def load(name):
        _require(type(name) is str and name in before, "artifact outside closed inventory")
        return (root / name).read_bytes()
    result = {"schema": "native-legal-formula-cuda-closed-audit/v1", "qualified": False,
              "execution_attestation": False, "errors": [], "reader_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        result["validated"] = validate(_parse(load("result.json")), load)
        result["qualified"] = True
    except (ValueError, KeyError, TypeError, RecursionError, OverflowError) as error:
        result["errors"].append(str(error))
    after = _snapshot(root)
    result["primary_archive"] = {"preserved": before == after and _identity(root.lstat()) == root_before,
        "files": len(before), "bytes": sum(value["bytes"] for value in before.values()),
        "inventory": before, "root_identity": list(root_before)}
    result["qualified"] = result["qualified"] and result["primary_archive"]["preserved"]
    result["elapsed_seconds"] = time.monotonic()-started
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _require(not args.output.exists(), "audit output must be new")
    value = audit(args.archive)
    args.output.write_bytes(_raw(value))
    args.output.chmod(0o444)
    print(json.dumps(value, indent=2))
    raise SystemExit(0 if value["qualified"] else 1)


if __name__ == "__main__":
    main()
