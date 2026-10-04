#!/usr/bin/env python3
"""Compare serial and batched readout of identical existing v1 weights.

Previously exposed train/tuning/test rows are readout regression inputs only.
There is no training, model selection, new holdout, or checkpoint mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
FALSE = dict(training_executed=False, model_selection_performed=False,
             new_holdout=False, admitted=False, qualified=False,
             proof_authority=False, source_semantics_verified=False,
             lake_executed=False, publication_performed=False,
             production_promotion_performed=False, downloads_performed=False)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw(value) + b"\n")


def sources():
    paths = [p for p in (ROOT / "ipfs_datasets_py").rglob("*") if p.is_file()
             and not {"__pycache__", ".pytest_cache", ".git"}.intersection(p.parts)
             and p.suffix not in {".pyc", ".pyo"}]
    paths.append(Path(__file__).resolve())
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def strict_serial(runtime, rows, contract):
    """Serial generation plus the adapter's stronger native work, timed together.

The original runtime already parsed/validated the envelope. Reuse that result
for successful envelopes, so the common semantic gate does not add a redundant
envelope-validation pass to just the serial measurement.
"""
    result = runtime.infer(rows)
    domain = result["domain_id"]
    for row in result["rows"]:
        envelope = row["candidate_ir"]
        envelope_valid = envelope is not None
        if envelope_valid:
            parsed_candidate, reason = envelope, None
        else:
            parsed = contract.parse_generated(row["generated_tokens"], ended=row["ended"])
            parsed_candidate = parsed["candidate"]
            reason = row["reason"] if parsed["json_valid"] else parsed["error"]
        candidate = None
        if envelope_valid:
            try:
                candidate = contract.validate_native_target(domain, parsed_candidate)["canonical_ir"]
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                reason = str(error)[:512]
        row.update(candidate_ir=candidate, raw_candidate_ir=parsed_candidate,
                   native_envelope_valid=envelope_valid, native_semantic_valid=candidate is not None,
                   status="unqualified_candidate" if candidate is not None else "invalid_generated_output",
                   reason=reason)
    return result


def compare(left, right):
    if len(left["rows"]) != len(right["rows"]):
        raise ValueError("different output row counts")
    delta = 0.
    fields = ("id", "generated_tokens", "ended", "candidate_ir", "raw_candidate_ir",
              "native_envelope_valid", "native_semantic_valid", "status", "reason",
              "target_access", "teacher_forcing")
    for serial, batched in zip(left["rows"], right["rows"]):
        for key in fields:
            if raw(serial[key]) != raw(batched[key]):
                raise ValueError(f"readout mismatch for {serial['id']}: {key}")
        a, b = serial["reconstructed_embedding"], batched["reconstructed_embedding"]
        if len(a) != 384 or len(b) != 384:
            raise ValueError("reconstruction dimension changed")
        delta = max(delta, max(abs(x-y) for x,y in zip(a,b)))
    if delta > 1e-6:
        raise ValueError(f"reconstruction maximum absolute difference {delta} exceeds 1e-6")
    return delta


def distribution(times, count):
    quartiles = statistics.quantiles(times, n=4, method="inclusive")
    median = statistics.median(times)
    return {"repeats": len(times), "median_seconds": median, "q1_seconds": quartiles[0],
            "q3_seconds": quartiles[2], "iqr_seconds": quartiles[2]-quartiles[0],
            "median_seconds_per_span": median/count, "median_spans_per_second": count/median,
            "measured_total_seconds": sum(times), "all_seconds": times}


def headroom():
    values = {"host_available_bytes": int(next(line.split()[1] for line in
        Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")))*1024}
    available = [values["host_available_bytes"]]
    maximum, current = Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory.current")
    if maximum.is_file() and current.is_file() and maximum.read_text().strip() != "max":
        values["mounted_cgroup_available_bytes"] = max(0,int(maximum.read_text())-int(current.read_text()))
        available.append(values["mounted_cgroup_available_bytes"])
    values.update(required_available_bytes=2*1024**3,
                  scope="observed host/mounted-cgroup headroom, not a lease or measured process bound")
    if min(available) < values["required_available_bytes"]:
        raise ValueError("less than 2 GiB observed headroom for imports and paired runtimes")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    process_started = time.perf_counter()
    prior, out = args.comparison.resolve(), args.output.resolve()
    if out.exists():
        raise SystemExit("Use a fresh output directory; old evidence must remain immutable")
    out.mkdir(parents=True)
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1",
                      MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    save(out/"started.json", {"comparison": str(prior), "source": str(ROOT),
                              "script_sha256": sha(Path(__file__)), **FALSE})
    save(out/"memory-preflight.json", headroom())
    pins, input_hashes = sources(), {}
    save(out/"source-manifest.json", pins)
    def read(relative):
        path = prior/relative
        value = json.loads(path.read_text())
        input_hashes[relative] = sha(path)
        return value
    plan, freeze = read("plan.json"), read("freeze.json")
    if freeze["plan_sha256"] != input_hashes["plan.json"]:
        raise ValueError("prior comparison plan differs from frozen plan")
    original_sources = read("source-manifest.json")
    if freeze["source_manifest_sha256"] != input_hashes["source-manifest.json"]:
        raise ValueError("prior producer manifest differs from frozen manifest")
    save(out/"original-producer-source-manifest.json",original_sources)
    descriptors = [r for r in freeze["fits"] if r["strategy"] == "v1"]
    if {(r["domain"],r["seed"]) for r in descriptors} != {(d,s) for d in ("intent_ir","ui_ux_ir") for s in (1729,1730)} or len(descriptors)!=4:
        raise ValueError("expected precisely the four v1 comparison checkpoints")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embedding_owner
    with embedding_owner._offline_guard():
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as serial_owner
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_batched_inference as batch_owner
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_fidelity as contract
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        import torch
        torch.set_num_threads(1)
        for module in (embedding_owner,serial_owner,batch_owner,contract):
            assert Path(module.__file__).resolve().is_relative_to(ROOT)
        logic_pin = require_workspace_logic_tree()
        _, assets = embedding_owner._snapshot_assets(embedding_owner.DEFAULT_SNAPSHOT_PATH)
        if assets != plan["embedding_assets"]:
            raise ValueError("local encoder assets differ from source-vector producer")
        save(out/"plan.json", {"comparison_plan_sha256": input_hashes["plan.json"],
            "checkpoint_count":4,"rows_per_checkpoint":36,"model_row_pairs":144,
            "warmups_per_runtime":1,"paired_repeats":20,"order":"alternate serial/batched first every repeat",
            "comparison_fields":"exact tokens, EOS, typed raw/native results, errors; embedding max_abs <=1e-6",
            "timing_scope":"public inference including stronger native validation; model loading/warmup/comparison excluded",
            "embedding_assets":assets,"embeddings_recomputed":False,"logic_tree_pin":logic_pin,
            "device":"cpu","torch_threads":torch.get_num_threads(),"temperature":0,**FALSE})
        all_inputs = {}
        for domain in ("intent_ir","ui_ux_ir"):
            rows = []
            for split,count in (("train",24),("tuning",6),("test",6)):
                original = read(f"{domain}/{split}.json")
                evidence = read(f"{domain}/{split}-embedding-evidence.json")
                assert len(original)==count and len(evidence["results"])==count
                assert evidence["assets"]==assets
                for row, producer in zip(original,evidence["results"]):
                    assert producer["input_id"]==row["id"] and producer["status"]=="embedded"
                    assert producer["source_sha256"]==hashlib.sha256(row["source_text"].encode()).hexdigest()
                    assert producer["embedding_sha256"]==serial_owner.digest(row["embedding"])
                    assert producer["vector"]==row["embedding"]
                    rows.append({k:row[k] for k in ("id","source_text","embedding")})
            assert len(rows)==36 and len({r["id"] for r in rows})==36
            all_inputs[domain]=rows
            save(out/domain/"inference-inputs.json",rows)
        total_start=time.perf_counter();reports=[]
        try:
            for descriptor in sorted(descriptors,key=lambda r:(r["domain"],r["seed"])):
                domain,seed=descriptor["domain"],descriptor["seed"]
                relative=f"{domain}/v1-{seed}/checkpoint.json"
                checkpoint=read(relative)
                expected=descriptor["checkpoint"]["sha256"]
                assert input_hashes[relative]==expected and checkpoint["config"]["max_target_tokens"]==64
                serial=serial_owner.Runtime(checkpoint)
                batched=batch_owner.Runtime(checkpoint)
                rows=all_inputs[domain];directory=out/domain/str(seed)
                save(directory/"runtime-descriptions.json",{"serial":serial.describe(),"batched":batched.describe()})
                # Both reusable runtimes receive one untimed warmup.
                warm_serial=strict_serial(serial,rows,contract);warm_batch=batched.infer(rows)
                save(directory/"warmup-outputs.json",{"serial":warm_serial,"batched":warm_batch})
                max_delta=compare(warm_serial,warm_batch)
                times={"serial":[],"batched":[]};digests=[]
                for repeat in range(20):
                    result={}
                    for name in (("serial","batched") if repeat%2==0 else ("batched","serial")):
                        tick=time.perf_counter()
                        result[name]=strict_serial(serial,rows,contract) if name=="serial" else batched.infer(rows)
                        times[name].append(time.perf_counter()-tick)
                    save(directory/f"repeat-{repeat:02d}-outputs.json",result)
                    max_delta=max(max_delta,compare(result["serial"],result["batched"]))
                    # Require repeat stability in addition to paired equality.
                    max_delta=max(max_delta,compare(warm_serial,result["serial"]))
                    digests.append({name:hashlib.sha256(raw(value)).hexdigest() for name,value in result.items()})
                assert sha(prior/relative)==expected
                assert serial_owner.digest(serial.checkpoint["model_state"])==checkpoint["weights_sha256"]
                assert serial_owner.digest(batched.checkpoint["model_state"])==checkpoint["weights_sha256"]
                report={"domain":domain,"seed":seed,"checkpoint_sha256_before":expected,
                    "checkpoint_sha256_after":sha(prior/relative),"rows":36,
                    "serial":distribution(times["serial"],36),"batched":distribution(times["batched"],36),
                    "maximum_embedding_absolute_difference":max_delta,"exact_output_agreement":True,
                    "output_digests":digests,"memory_estimate":warm_batch["inference_memory_estimate"],
                    "native_envelope_valid_count":sum(r["native_envelope_valid"] for r in warm_batch["rows"]),
                    "native_semantic_valid_count":sum(r["native_semantic_valid"] for r in warm_batch["rows"]),**FALSE}
                report["median_speed_ratio_serial_over_batched"]=report["serial"]["median_seconds"]/report["batched"]["median_seconds"]
                save(directory/"summary.json",report);reports.append(report)
                print(domain,seed,"readout agreement",report["median_speed_ratio_serial_over_batched"],flush=True)
            assert sources()==pins,"source changed during inference comparison"
            assert all(sha(prior/p)==digest for p,digest in input_hashes.items()),"input changed"
            assert embedding_owner._snapshot_assets(embedding_owner.DEFAULT_SNAPSHOT_PATH)[1]==assets
            loaded={name:str(Path(module.__file__).resolve()) for name,module in tuple(sys.modules.items())
                if name.startswith("ipfs_datasets_py") and getattr(module,"__file__",None)}
            assert all(Path(p).is_relative_to(ROOT) for p in loaded.values())
            save(out/"loaded-modules.json",loaded);save(out/"input-hashes.json",input_hashes)
            save(out/"summary.json",{"schema":"domain384-identical-weight-readout-comparison/v1",
                "reports":reports,"model_row_pairs":144,"timed_model_row_pairs_per_runtime":144*20,
                "timed_runtime_row_evaluations":144*20*2,
                "all_outputs_agree":True,"elapsed_seconds":time.perf_counter()-process_started,
                "readout_phase_seconds":time.perf_counter()-total_start,
                "max_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "rss_scope":"whole mixed benchmark process, no embedding model loaded",
                "source_unchanged":True,"inputs_unchanged":True,"checkpoints_unchanged":True,
                "assets_unchanged":True,"bridge_evaluate_executed":False,**FALSE})
        except Exception as error:
            save(out/"failure.json",{"error_type":type(error).__name__,"error":str(error),
                "comparison_passed":False,"completed_checkpoints":len(reports),"input_hashes":input_hashes,**FALSE})
            raise


if __name__=="__main__":
    main()
