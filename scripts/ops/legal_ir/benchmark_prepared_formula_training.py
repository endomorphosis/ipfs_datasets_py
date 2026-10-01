#!/usr/bin/env python3
"""Three paired CPU throughput controls using only verified retained training rows.

Reference and prepared trainers start from the same fresh head and use exactly
1,000 updates in AB/BA/AB order. Timing includes each trainer's restore, input
preparation, loss observations and serialization. No held-out targets are read.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
from pathlib import Path
import resource
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import validate_teacher_student_transfer as shared

STEPS=1000
WARMUP_STEPS=25
PAIRS=(("reference","prepared"),("prepared","reference"),("reference","prepared"))
FALSE=dict(shared.FALSE,proof_authority=False,promotion_performed=False,publication_performed=False,
           independent_generalization_verified=False)
require,sha,write=shared.require,shared.sha,shared.write
_IMPORTED_SOURCE_SHA256=sha(__file__)


def read_reference(ref):
    path=Path(ref["path"])
    require(path.stat().st_size==ref["bytes"] and sha(path)==ref["sha256"],"retained artifact changed")
    return json.loads(path.read_text())


def source_binding():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_prepared as fast
    require(sha(__file__)==_IMPORTED_SOURCE_SHA256,"benchmark source changed since import")
    return dict(runner_sha256=_IMPORTED_SOURCE_SHA256,prepared=fast._check_sources())


def rates(report,elapsed,batch_size):
    require(type(elapsed) in (float,int) and math.isfinite(elapsed) and elapsed>0,"positive finite wall time required")
    require(report["optimizer_steps"]==STEPS and len(report["batch_losses"])==STEPS,
            "fixed update budget incomplete")
    require(report["training_after"]["complete"],"training metrics incomplete")
    tokens=sum(row["token_count"] for row in report["batch_losses"])
    require(tokens>0,"actual loss-token count required")
    return dict(wall_seconds=elapsed,optimizer_steps_per_second=STEPS/elapsed,
                row_presentations=STEPS*batch_size,row_presentations_per_second=STEPS*batch_size/elapsed,
                actual_loss_tokens=tokens,loss_tokens_per_second=tokens/elapsed,
                wall_seconds_per_row_presentation=elapsed/(STEPS*batch_size))


def require_exact(reference,prepared):
    require(reference["checkpoint"]==prepared["checkpoint"],"prepared full checkpoint differs from reference")
    fields=("batch_losses","parameter_evidence","formula_projection_gradient_norm_max",
            "training_before","training_after","tuning","progress","stopped_reason")
    for field in fields:
        require(reference["report"][field]==prepared["report"][field],"prepared numeric telemetry differs: "+field)


def require_resumed_update(reference,prepared):
    require(reference["report"]["optimizer_steps"]==prepared["report"]["optimizer_steps"]==1,
            "cross-backend resume probe did not execute its update")
    require_exact(reference,prepared)


def run(profile_directory,output_directory,profile_sha256):
    require(os.environ.get("CUDA_VISIBLE_DEVICES")=="","CPU benchmark requires CUDA_VISIBLE_DEVICES='' before Python starts")
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as reference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_prepared as fast
    started=time.perf_counter()
    require(sha(profile_directory/"report.json")==profile_sha256,"input profile receipt differs")
    profile=json.loads((profile_directory/"report.json").read_text())
    require(profile["training_count"]==48 and profile["tuning_count"]==profile["holdout_count"]==0,
            "benchmark requires the fixed training-only48 inputs")
    rows=read_reference(profile["inputs"])
    checkpoint=read_reference(profile["initial_head"])
    reference.validate_checkpoint(checkpoint)
    require(len(rows)==48 and checkpoint["config"]["batch_size"]==6 and checkpoint["progress"]["optimizer_steps"]==0,
            "fresh fixed48-row/batch6 benchmark required")
    require(checkpoint["training_manifest_sha256"]==reference.checkpoint_digest(rows)
            and checkpoint["tuning_manifest_sha256"]==reference.checkpoint_digest([]),"benchmark input manifests differ")
    producers=source_binding()
    output_directory.mkdir(parents=True,exist_ok=False)
    plan=dict(schema="prepared-formula-throughput-plan/v1",producer=producers,
        profile_receipt=dict(path=str(profile_directory/"report.json"),sha256=profile_sha256),
        inputs=profile["inputs"],initial_head=profile["initial_head"],pair_order=PAIRS,
        steps_per_arm=STEPS,warmup_steps_per_backend=WARMUP_STEPS,torch_threads=1,CUDA_VISIBLE_DEVICES="",
        device="cpu",training_rows=48,tuning_rows=0,holdout_rows=0,temperature=0,
        timing_scope="trainer call including restore, tensor preparation, updates, loss observations, serialization",
        input_targets_reused=True,legal_ir_bridge_names=[],legal_ir_target_count=0,
        legal_ir_evaluate_provers=False,legal_ir_parallel_workers=1,metric_disk_cache=False,**FALSE)
    plan_sha=write(output_directory/"plan.json",plan)["sha256"]
    trainers={"reference":reference.train,"prepared":fast.train}
    warm=[]
    for name in ("reference","prepared"):
        tick=time.perf_counter()
        observed=trainers[name](checkpoint,rows,[],epochs=1000,max_optimizer_steps=WARMUP_STEPS,max_seconds=120)
        require(observed["report"]["optimizer_steps"]==WARMUP_STEPS,"warmup update budget incomplete")
        warm.append(dict(backend=name,wall_seconds=time.perf_counter()-tick))
    setup_seconds=time.perf_counter()-started
    results=[]
    numeric_reference=None
    for index,order in enumerate(PAIRS):
        pair={}
        for name in order:
            require(source_binding()==producers and sha(output_directory/"plan.json")==plan_sha,"sealed benchmark producer/plan changed")
            gc.collect()
            tick=time.perf_counter()
            observed=trainers[name](checkpoint,rows,[],epochs=1000,max_optimizer_steps=STEPS,max_seconds=120)
            elapsed=time.perf_counter()-tick
            performance=rates(observed["report"],elapsed,checkpoint["config"]["batch_size"])
            if numeric_reference is None:
                numeric_reference=observed
            require_exact(numeric_reference,observed)
            head=reference.save_checkpoint(observed["checkpoint"],output_directory/f"pair-{index}-{name}-head.json")
            retained=reference.load_checkpoint(head["path"],expected_sha256=head["sha256"])
            require(retained==observed["checkpoint"],"reload changed the complete checkpoint")
            continued=fast.train(retained,rows,[],epochs=1,max_optimizer_steps=1,max_seconds=60)
            uninterrupted=reference.train(observed["checkpoint"],rows,[],epochs=1,max_optimizer_steps=1,max_seconds=60)
            require_resumed_update(uninterrupted,continued)
            record=dict(pair=index,backend=name,performance=performance,head=head,
                report=observed["report"],exact_checkpoint_and_numeric_telemetry=True,
                reload_exact=True,cross_backend_resume_exact=True,resume_steps_excluded_from_timing=True,**FALSE)
            pair[name]=record
            write(output_directory/f"pair-{index}-{name}-result.json",record)
            print(json.dumps(dict(pair=index,backend=name,**performance)),flush=True)
        results.append(dict(pair=index,order=order,backends=pair,
            wall_speedup=pair["reference"]["performance"]["wall_seconds"]/pair["prepared"]["performance"]["wall_seconds"]))
    require(source_binding()==producers and sha(output_directory/"plan.json")==plan_sha,"producer/plan changed")
    require(sha(profile_directory/"report.json")==profile_sha256,"input profile changed")
    read_reference(profile["inputs"]);read_reference(profile["initial_head"])
    summary={}
    for backend in trainers:
        times=[pair["backends"][backend]["performance"]["wall_seconds"] for pair in results]
        summary[backend]=dict(wall_seconds_mean=statistics.mean(times),wall_seconds_median=statistics.median(times),
            wall_seconds_stdev=statistics.stdev(times),wall_seconds_min=min(times),wall_seconds_max=max(times),
            optimizer_steps_per_second_aggregate=STEPS*len(times)/sum(times),
            row_presentations_per_second_aggregate=STEPS*6*len(times)/sum(times))
    write(output_directory/"report.json",dict(schema="prepared-formula-throughput-comparison/v1",plan=plan,
        warmup=warm,setup_and_warmup_seconds=setup_seconds,results=results,summary=summary,
        median_paired_wall_speedup=statistics.median(pair["wall_speedup"] for pair in results),
        operational_ok=True,all_numeric_results_exact=True,heldout_targets_read=False,
        elapsed_seconds=time.perf_counter()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        reference_steady_loop_timer_available=False,prepared_loop_timer_scope="optimization loop only; not end-to-end throughput",
        throughput_scope="repeated training row presentations and loss tokens; not distinct legal-span conversion",
        legal_ir_target_count=0,bridge_on_evaluate=None,**FALSE))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-directory",required=True,type=Path)
    parser.add_argument("--profile-sha256",required=True)
    parser.add_argument("--output-directory",required=True,type=Path)
    args=parser.parse_args()
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"]="0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"]="0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"]="0"
    run(args.profile_directory.resolve(),args.output_directory.resolve(),args.profile_sha256)


if __name__=="__main__":
    main()
