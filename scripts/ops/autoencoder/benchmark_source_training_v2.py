#!/usr/bin/env python3
"""Frozen four-domain composition comparison of shared 384D source decoders.

Explicit phases prevent development fitting after heldout exposure. Source
embeddings are built once per phase from verified local GTE-small assets.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
FIXTURE = REPO / "tests/fixtures/logic/source_reconstruction_v2.py"
spec = importlib.util.spec_from_file_location("source_composition_panel", FIXTURE)
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
DOMAINS = panel.DOMAINS
ARMS = {"raw_ce": dict(strategy="reference_ce", input_normalization="none"),
        "centered_ce": dict(strategy="reference_ce", input_normalization="center_rms"),
        "semantic": dict(strategy="semantic_v2", input_normalization="center_rms")}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw(value))
    return {"path": str(path), "sha256": sha(path)}


def inputs(folder, domain, partition):
    return json.loads((folder / domain / (partition + ".json")).read_bytes())["rows"]


def model_rows(rows, targets=True):
    keys = ("id", "source_text", "embedding", "target") if targets else ("id", "source_text", "embedding")
    return [{key: row[key] for key in keys} for row in rows]


def embed(partitions, device):
    import torch
    from sentence_transformers import SentenceTransformer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    start = time.perf_counter()
    snapshot, assets = producer._snapshot_assets(producer.DEFAULT_SNAPSHOT_PATH)
    with torch.random.fork_rng(devices=[]):
        encoder = SentenceTransformer(str(snapshot), local_files_only=True, trust_remote_code=False, device="cpu")
    encoder.eval()
    producer._validate_model(encoder, torch)
    if device == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("explicit CUDA embedding device unavailable")
        encoder.to("cuda")
    assert all(p.device.type == device and p.dtype == torch.float32 for p in encoder.parameters())
    rows = [row for values in partitions.values() for row in values]
    max_tokens = 0
    for row in rows:
        tokenized = producer._untruncated_tokens(encoder, row["source_text"])
        max_tokens = max(max_tokens, len(tokenized["input_ids"]))
        row["embedding_token_ids_sha256"] = hashlib.sha256(raw(tokenized)).hexdigest()
    load_seconds = time.perf_counter() - start
    start = time.perf_counter()
    with torch.inference_mode():
        vectors = encoder.encode([r["source_text"] for r in rows], batch_size=32,
            convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
    if device == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    for row, vector in zip(rows, vectors.tolist()):
        assert len(vector) == 384 and all(__import__("math").isfinite(x) for x in vector)
        row["embedding"] = vector
        row["embedding_sha256"] = hashlib.sha256(raw(vector)).hexdigest()
    return dict(model_id="thenlper/gte-small", revision=producer.PINNED_REVISION, dimension=384,
        assets=assets, device=device, dtype="float32", normalized=True, truncated=False,
        max_tokens_observed=max_tokens, batch_size=32, rows=len(rows), load_seconds=load_seconds,
        encode_seconds=elapsed, encode_rows_per_second=len(rows)/elapsed)


def prepare(folder, parent, device):
    assert not folder.exists(), "fresh output required"
    parent = parent.resolve()
    assert parent.is_file(), "complete trained Legal parent required"
    partitions = {(d,s):panel.rows(d,s) for d in DOMAINS for s in ("train", "validation")}
    for domain in DOMAINS:
        train, tune = partitions[domain,"train"], partitions[domain,"validation"]
        for key in ("id", "group_id", "source_sha256"):
            assert not {r[key] for r in train} & {r[key] for r in tune}, "development split overlap"
    provenance = embed(partitions, device)
    for (domain, partition), rows in partitions.items():
        save(folder / domain / (partition + ".json"), {"rows":rows,"source_embeddings":provenance})
    save(folder / "preparation.json", dict(schema="source-training-composition-preparation/v2",
        fixture_sha256=sha(FIXTURE), parent={"path":str(parent),"sha256":sha(parent)},
        corpus=panel.manifest(), source_embeddings=provenance, heldout_targets_generated=False,
        development_files={str(path.relative_to(folder)):sha(path) for path in folder.rglob("*.json")},
        source_semantics_verified=False, proof_authority=False))
    print(json.dumps({"development_rows":provenance["rows"],"embedding_rows_per_second":provenance["encode_rows_per_second"]}), flush=True)


def pins(trainer):
    return {str(p):sha(p) for p in (Path(__file__).resolve(),FIXTURE,Path(trainer.__file__))}


def guard_preparation(folder):
    saved=json.loads((folder/"preparation.json").read_bytes())
    assert saved["fixture_sha256"]==sha(FIXTURE)
    assert saved["parent"]["sha256"]==sha(saved["parent"]["path"])
    for name,digest in saved["development_files"].items():
        assert sha(folder/name)==digest
    return saved


def fit(folder, seeds, epochs):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2 as trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as previous
    prepared=guard_preparation(folder)
    assert not (folder/"evaluation-started.json").exists()
    save(folder/"plan.json", dict(producer=pins(trainer),arms=ARMS,seeds=seeds,epochs=epochs,
        batch_size=12,max_optimizer_steps=epochs*15,validation_interval=10,max_seconds=300,
        selection_on_test=False,source_input_contract="actual GTE384 only, provenance text not neural input",
        legal_published_parser_feature_baseline_included=False,
        original_native_v1_baseline_domains=list(previous.DOMAINS)))
    save(folder/"fit-started.json", {"once":True})
    fits=[]
    for domain in DOMAINS:
        train,tune=[model_rows(inputs(folder,domain,s)) for s in ("train","validation")]
        for seed in seeds:
            arms = [("native_v1", None)] if domain in previous.DOMAINS else []
            arms += list(ARMS.items())
            for arm, options in arms:
                started=time.perf_counter()
                if arm == "native_v1":
                    runtime = previous
                    settings=dict(epochs=epochs,batch_size=12,seed=seed,patience=1000,max_seconds=300,
                                  embedding_provenance=prepared["source_embeddings"])
                else:
                    runtime = trainer
                    settings={**options,"epochs":epochs,"batch_size":12,"max_optimizer_steps":epochs*15,"seed":seed,
                        "patience":0,"validation_interval":10,"max_seconds":300,
                        "embedding_provenance":prepared["source_embeddings"]}
                result=runtime.train(domain,train,tune,parent_projection=prepared["parent"],config=settings)
                elapsed=time.perf_counter()-started
                checkpoint=result["checkpoint"]
                identity=save(folder/domain/f"{arm}-{seed}-checkpoint.json", checkpoint)
                development={part:runtime.evaluate(checkpoint,rows) for part,rows in (("train",train),("validation",tune))}
                evidence=save(folder/domain/f"{arm}-{seed}-development.json", development)
                record=dict(domain=domain,arm=arm,seed=seed,checkpoint=identity,metrics=result["metrics"],
                    full_fit_seconds=elapsed,development=evidence)
                fits.append(record)
                print(json.dumps({"domain":domain,"arm":arm,"seed":seed,"full_fit_seconds":elapsed,
                    "selected_validation":result["metrics"]["selected_validation"],
                    "free_running_validation":{key:development["validation"][key] for key in ("count","exact_targets","valid_candidates")}}),flush=True)
    guard_preparation(folder)
    save(folder/"fits.json",fits)
    frozen=save(folder/"freeze.json", {str(path.relative_to(folder)):sha(path)
        for path in folder.rglob("*.json") if path.name!="freeze.json"})
    print(json.dumps({"freeze":frozen}),flush=True)


def evaluate(folder, expected):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2 as trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as previous
    prepared=guard_preparation(folder)
    assert sha(folder/"freeze.json")==expected, "explicit complete freeze SHA required"
    plan=json.loads((folder/"plan.json").read_bytes())
    assert plan["producer"]==pins(trainer), "runner or trainer changed"
    for name,digest in json.loads((folder/"freeze.json").read_bytes()).items():
        assert sha(folder/name)==digest, "frozen artifact changed"
    save(folder/"evaluation-started.json", {"heldouts_now_exposed":True})
    parts={(d,s):panel.rows(d,s) for d in DOMAINS for s in ("test","canary")}
    provenance=embed(parts,prepared["source_embeddings"]["device"])
    for (domain,partition),rows in parts.items():
        save(folder/domain/(partition+".json"),{"rows":rows,"source_embeddings":provenance})
    fits=json.loads((folder/"fits.json").read_bytes())
    summaries=[]
    for fit in fits:
        cp=json.loads(Path(fit["checkpoint"]["path"]).read_bytes())
        results={}
        for partition in ("test","canary"):
            rows=model_rows(parts[fit["domain"],partition])
            tick=time.perf_counter()
            runtime = previous if fit["arm"]=="native_v1" else trainer
            results[partition]=runtime.evaluate(cp,rows)
            results[partition]["inference_seconds_including_load_and_metrics"]=time.perf_counter()-tick
        save(folder/fit["domain"]/f"{fit['arm']}-{fit['seed']}-evaluation.json",results)
        summaries.append(dict(domain=fit["domain"],arm=fit["arm"],seed=fit["seed"],
            full_fit_seconds=fit["full_fit_seconds"],results=results))
        print(json.dumps({"domain":fit["domain"],"arm":fit["arm"],"scored":True}),flush=True)
    save(folder/"evaluation.json", dict(schema="source-composition-comparison/v2",rows=summaries,
        source_semantics_verified=False,proof_authority=False,models_promoted=False,
        source_input_contract="GTE384, no parser features",heldout_groups_per_domain=5))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("prepare","fit","evaluate"))
    parser.add_argument("--output-directory",type=Path,required=True)
    parser.add_argument("--parent-checkpoint",type=Path)
    parser.add_argument("--embedding-device",choices=("cpu","cuda"),default="cuda")
    parser.add_argument("--seeds",type=int,nargs="+",default=[1729])
    parser.add_argument("--epochs",type=int,default=100)
    parser.add_argument("--freeze-sha256")
    args=parser.parse_args()
    folder=args.output_directory.resolve()
    if args.phase=="prepare": prepare(folder,args.parent_checkpoint,args.embedding_device)
    elif args.phase=="fit": fit(folder,args.seeds,args.epochs)
    else: evaluate(folder,args.freeze_sha256)
