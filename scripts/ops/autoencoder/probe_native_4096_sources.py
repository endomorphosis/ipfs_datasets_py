#!/usr/bin/env python3
"""Reserved source-only native4096 vocabulary preflight; no forward or fit.

Input literal strings are joined from an existing three-width cache; vectors
and target labels are never submitted to the native worker. A complete receipt
can establish tokenizer fit and native metadata width only.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_inventory(cache):
    native = cache["dimensions"]["384"]
    sources = set()
    for split in ("train", "validation"):
        for row in native[split] + native["clause_cache"][split]:
            text = row["source_text"]
            if type(text) is not str or not text:
                raise ValueError("literal source text required")
            sources.add(text)
    return [{"id": "source:" + hashlib.sha256(text.encode()).hexdigest(), "source_text": text}
            for text in sorted(sources)]


def native_protocol_controls(executable, output):
    """Execute the compiled source-only parser without opening any model FD."""
    nonce = "a" * 64
    request = {"schema": "native-source4096-worker-request/v1", "nonce": nonce,
               "rows": [{"id": "control", "source_text": "The agency shall retain records."}]}
    wire = lambda value: json.dumps(value, separators=(",", ":")).encode()
    cases = [("valid", wire(request), 0)]
    cases.append(("extra_target", wire(dict(request, target="O(retain)")), 2))
    cases.append(("duplicate_key", wire(request)[:-1] + b',"nonce":"' + nonce.encode() + b'"}', 2))
    cases.append(("wrong_nonce", wire(dict(request, nonce="b"*64)), 2))
    cases.append(("duplicate_id", wire(dict(request, rows=request["rows"]*2)), 2))
    cases.append(("empty_source", wire(dict(request, rows=[{"id":"control","source_text":""}])), 2))
    cases.append(("too_many_rows", wire(dict(request, rows=[{"id":str(i),"source_text":"x"} for i in range(4097)])), 2))
    results = []
    for name, raw, expected in cases:
        completed = subprocess.run([executable, "--model-fd", "0", "--mode", "validate-request",
            "--nonce", nonce, "--deadline-seconds", "5"], input=raw, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10, env={"PATH":"/usr/bin:/bin","CUDA_VISIBLE_DEVICES":""})
        if completed.returncode != expected or len(completed.stdout) > 65536 or len(completed.stderr) > 65536:
            raise ValueError("native protocol control failed: " + name)
        record = json.loads(completed.stdout)
        if expected == 0:
            if record["schema"] != "native-source4096-request-control/v1" or record["model_opened"] is not False:
                raise ValueError("native parser control opened a model")
        elif record["schema"] != "native-source4096-worker-error/v1" or record["entry_emitted"] is not False:
            raise ValueError("invalid native request passed its entry fence")
        results.append({"case": name, "request_sha256": hashlib.sha256(raw).hexdigest(),
            "returncode": completed.returncode, "record": record,
            "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest()})
    Path(output).write_text(json.dumps({"cases":results,"model_opened":False,"qualified":False},sort_keys=True,indent=2)+"\n")
    return len(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["preflight"], required=True)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--extension-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    manifest_raw = args.manifest.read_bytes()
    manifest = json.loads(manifest_raw)
    plan_raw = args.plan.read_bytes()
    if hashlib.sha256(plan_raw).hexdigest() != manifest["plan_sha256"]:
        raise ValueError("native probe plan changed")
    for relative, digest in manifest["extensions"].items():
        if sha(args.extension_root / relative) != digest:
            raise ValueError("native probe extension changed: " + relative)
    for path, digest in manifest["inputs"].items():
        if sha(path) != digest:
            raise ValueError("native probe input changed: " + path)
    plan = json.loads(plan_raw)
    if plan["scope"] != "vocabulary_only_no_weights_or_context" or plan["dimension"] != 4096:
        raise ValueError("closed preflight scope required")
    cache_raw = Path(plan["source_cache"]).read_bytes()
    if hashlib.sha256(cache_raw).hexdigest() != manifest["inputs"].get(plan["source_cache"]):
        raise ValueError("source inventory is not the authenticated cache")
    rows = source_inventory(json.loads(cache_raw))
    if len(rows) != plan["expected_unique_sources"]:
        raise ValueError("native source inventory changed")
    args.output.mkdir(exist_ok=False)
    builder = load("owned_native4096_builder", args.extension_root / "scripts/ops/autoencoder/build_leanstral4096_worker.py")
    owner = load("owned_native4096_preflight", args.extension_root / "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_4096_native_owner.py")
    build = builder.build_worker(args.output / "build", args.extension_root, Path(plan["native_root"]))
    control_count = native_protocol_controls(build["executable"]["path"], args.output / "native-protocol-controls.json")
    receipt = owner.run_vocab_probe(rows, worker_path=build["executable"]["path"],
        worker_sha256=build["executable"]["sha256"], worker_source_sha256=build["worker_source_sha256"],
        model_path=plan["model_path"], output_directory=args.output / "vocabulary",
        deadline_seconds=plan["tokenizer_deadline_seconds"])
    # Recheck the exact native inputs rather than trusting a reusable build flag.
    for path, expected in build["inputs"].items():
        if builder.metadata(path) != expected:
            raise ValueError("native input changed during vocabulary probe")
    for relative, digest in manifest["extensions"].items():
        if sha(args.extension_root / relative) != digest:
            raise ValueError("producer changed during native probe")
    for path, digest in manifest["inputs"].items():
        if sha(path) != digest:
            raise ValueError("bound input changed during native probe")
    if args.manifest.read_bytes() != manifest_raw or args.plan.read_bytes() != plan_raw:
        raise ValueError("native probe recipe changed during execution")
    summary = {"schema": "native-source4096-source-inventory-preflight/v1", "complete": True,
        "sample_count": len(rows), "elapsed_seconds": time.monotonic()-started,
        "native_preflight_elapsed_seconds": receipt["elapsed_seconds"],
        "vocabulary_wall_seconds_per_span": receipt["elapsed_seconds"] / len(rows),
        "min_source_tokens": receipt["min_source_tokens"], "max_source_tokens": receipt["max_source_tokens"],
        "native_input_dimension": None, "native_output_dimension": None,
        "metadata_architecture": receipt["geometry"]["metadata_architecture"],
        "declared_metadata_embedding_length": receipt["geometry"]["metadata_embedding_length"],
        "declared_metadata_embedding_length_out": receipt["geometry"]["metadata_embedding_length_out"],
        "max_context_tokens": 512, "bridge_names": [], "prover_flag": False,
        "legal_ir_metric_disk_cache": False, "workers": 1,
        "build_manifest_sha256": sha(build["manifest_path"]),
        "compiled_native_protocol_controls_passed": control_count,
        "vocabulary_receipt_sha256": sha(args.output / "vocabulary/receipt.json"),
        "vectors_produced": 0, "training_executed": False, "native_model_content_hash_verified": False,
        "qualified": False, "admitted": False, "proof_authority": False,
        "cache_scope": "new native vocabulary process; OS page cache uncontrolled; no embedding vectors cached or produced",
        "claim_scope": "real native vocabulary and declared model metadata only; not actual forward width, bridge-on evaluation or full-forward readiness"}
    (args.output / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2)+"\n")
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
