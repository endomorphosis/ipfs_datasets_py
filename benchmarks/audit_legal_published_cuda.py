"""Independent stdlib-only joins for the closed published Legal384 CUDA replay."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import time

from audit_modal_formula_cuda import (_decision, _false_authority, _identity, _integer,
    _parse, _raw, _require, _snapshot, _timing, _vectors)

DESCRIPTOR = {"domain_id":"legal_ir", "manifest_sha256":"34794ea4bbf128678eafdd8ba1862b58c8d0bf36b8ae83e20de75abf57e9debc",
    "release_prefix":"releases/20261002-384-development-v1", "repository_id":"Publicus/legal-ir-autoencoder",
    "revision":"9542bbee70a55ea79fb24e4ef01ff2a6f88204a2", "schema":"ir-384-hub-descriptor/v1"}


def _report(report, *, cuda, count, package_sha, formula_sha):
    _require(report["checkpoint_sha256"] == package_sha and report["runtime"] == "legal_current_v2",
             "released package inference identity differs")
    _integer(report["training_steps"],0,0,"published inference training steps")
    _integer(report["provider_calls"],0,0,"published inference provider calls")
    implementation = report["inference_implementation"]
    _require(implementation["core_device"] == "cpu" and implementation["whole_model_cuda"] is False,
             "released CPU core device scope changed")
    selection = implementation["formula_head_selection"]
    _require(selection["device"] == ("cuda:0" if cuda else "cpu")
             and selection["cuda_selected"] is cuda and "cuda_executed" not in selection,
             "head selection must not attest execution")
    value = report["result"]
    _require(value["checkpoint_sha256"] == formula_sha and value["binding"]["dimension"] == 384
             and value["binding"]["lineage_id"] == "current_legal_v2", "released head binding differs")
    _require(len(value["rows"]) == count and set(value["decoded_embeddings"]) == {row["id"] for row in value["rows"]},
             "complete released inference membership required")
    _integer(value["decoded_count"],0,count,"published decoded count")
    head = value["inference_implementation"]["formula_decoder"]
    _require(head["device"] == ("cuda:0" if cuda else "cpu") and head["cuda_selected"] is cuda
             and head["cuda_executed"] is cuda and head["actual_forward_executed"] is True,
             "actual released formula forward evidence differs")
    _require(set(head["actual_forward_calls"]) == {"projection_down","projection_up","output"},
             "closed released forward counters required")
    for number in head["actual_forward_calls"].values():
        _integer(number,1,16384,"released forward calls")
    return value


def validate(record,load):
    _require(record["schema"] == "published-legal384-private-cuda-qualification/v1"
             and record["qualified"] is True and record["error"] is None, "published native qualification failed")
    _false_authority(record,root=True)
    _require(record["whole_model_cuda"] is False and record["codebase_384d_qualification"] is False
             and record["execution_attestation"] is False and record["core_device"] == "cpu",
             "published private-stage scope broadened")
    _integer(record["training_calls"],0,0,"published training calls")
    _timing(record["elapsed_seconds"],"published elapsed")
    _timing(record["download_seconds"],"bounded immutable download")
    _require(record["own_lease_released"] is True, "published lease not released")
    _require(record["peak_rss_bytes"] <= 2048*1024*1024 and 0 < record["peak_gpu_allocated_bytes"] <= 2048*1024*1024,
             "observed published memory exceeded reservation")
    _require(record["descriptor"] == DESCRIPTOR, "immutable public descriptor differs")
    manifest_raw=load("release/manifest.json")
    _require(hashlib.sha256(manifest_raw).hexdigest() == DESCRIPTOR["manifest_sha256"], "public manifest bytes differ")
    manifest=_parse(manifest_raw)
    _require(manifest == record["downloaded_release"] and manifest["dimension"] == 384
             and manifest["domain_id"] == "legal_ir" and manifest["proof_authority"] is False,
             "released package inventory differs")
    for name,pin in manifest["files"].items():
        raw=load("release/"+name)
        _require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
                 "public weight file bytes differ")
    package_raw=load("release/"+manifest["checkpoint_file"])
    package=_parse(package_raw)
    _false_authority(package)
    package_sha=hashlib.sha256(package_raw).hexdigest()
    _require(package_sha == record["release_package_sha256"], "released package identity differs")
    head=package["formula_checkpoint"]
    formula_sha=hashlib.sha256(_raw(head)).hexdigest()
    _require(formula_sha == record["formula_checkpoint_sha256"] and head["progress"] == record["retained_formula_progress"],
             "retained formula/Adam identity differs")
    _integer(head["progress"]["epochs_completed"],1,1000000,"retained published epochs")
    _integer(head["progress"]["optimizer_steps"],1,1000000,"retained published Adam steps")
    _integer(head["progress"]["row_cursor"],0,1000000,"retained published cursor")
    _require(record["native_core_unchanged"] is True and record["checkpoint_and_adam_unchanged"] is True,
             "published inference changed numerical state")
    _require(len(record["source_pins"]) == 14 and len({pin["copy"] for pin in record["source_pins"]}) == 14,
             "complete distinct published producer inventory required")
    for pin in record["source_pins"]:
        raw=load(pin["copy"])
        _require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"], "published producer bytes differ")
    fixture=_parse(load("retained-fixture.json"))
    _require(fixture == package["fixture"]["rows"], "retained released fixture differs")
    replays=record["direct_inference"]
    _require([item["count"] for item in replays] == [1,17,128], "complete released scalar/batch replays required")
    errors=[]
    for item in replays:
        _integer(item["count"],1,128,"published sample count")
        for duration in item["inference_seconds"].values():
            _timing(duration,"published inference")
        left=_report(item["cpu"],cuda=False,count=item["count"],package_sha=package_sha,formula_sha=formula_sha)
        right=_report(item["cuda"],cuda=True,count=item["count"],package_sha=package_sha,formula_sha=formula_sha)
        _require([_decision(row) for row in left["rows"]] == [_decision(row) for row in right["rows"]],
                 "released direct canonical/status/token decisions differ")
        for index,row in enumerate(left["rows"]):
            _require(row["id"] == "published-"+str(index) and row["source_sha256"] == hashlib.sha256(
                fixture[index%len(fixture)]["source_text"].encode()).hexdigest(), "released source-row identity differs")
        names=sorted(left["decoded_embeddings"])
        error=_vectors([left["decoded_embeddings"][name] for name in names],
                       [right["decoded_embeddings"][name] for name in names],384)
        _require(error == item["max_absolute_error"] and item["exact_decision_parity"] is True,
                 "recorded released direct parity differs")
        errors.append(error)
    texts=record["source_text_inference"]
    count=min(len(fixture),2)
    _require(texts["latent_identity_parity"] == "finite_numerical_not_bitwise"
             and texts["exact_source_token_identity"] is True and texts["exact_decision_parity"] is True,
             "source encoder device identity scope differs")
    left=_report(texts["cpu"],cuda=False,count=count,package_sha=package_sha,formula_sha=formula_sha)
    right=_report(texts["cuda"],cuda=True,count=count,package_sha=package_sha,formula_sha=formula_sha)
    def source_decision(row):
        value=_decision(row)
        value.pop("latent_sha256")
        return value
    _require([source_decision(row) for row in left["rows"]] == [source_decision(row) for row in right["rows"]],
             "released source-only canonical/status/token decisions differ")
    cpu_embed,cuda_embed=texts["cpu"]["embedding_execution"],texts["cuda"]["embedding_execution"]
    _require(cpu_embed["tokens"] == cuda_embed["tokens"] and cpu_embed["source_sha256"] == cuda_embed["source_sha256"],
             "released encoder actual source/token identity differs")
    _require(cpu_embed["source_sha256"] == [hashlib.sha256(row["source_text"].encode()).hexdigest() for row in fixture[:2]],
             "released encoder sources differ from retained fixture")
    for cuda,embedding in ((False,cpu_embed),(True,cuda_embed)):
        device="cuda:0" if cuda else "cpu"
        _require(embedding["cuda_executed"] is cuda and embedding["profile"]["device"] == device
                 and embedding["actual_forward_batches"] == [dict(rows=count,input_device=device,
                    output_device=device,output_dtype="torch.float32")], "actual released encoder tensors differ")
    names=sorted(left["decoded_embeddings"])
    error=_vectors([left["decoded_embeddings"][name] for name in names],[right["decoded_embeddings"][name] for name in names],384)
    _require(error == texts["max_absolute_error"], "recorded released source numeric parity differs")
    return {"descriptor":DESCRIPTOR,"direct_rows_per_device":146,"source_text_rows_per_device":count,
        "max_direct_absolute_error":max(errors),"source_max_absolute_error":error,"new_training_calls":0,
        "retained_progress":head["progress"],"authority_preserved":True,"no_native_execution_or_owners":True}


def audit(root):
    root=Path(root).absolute()
    start=time.monotonic()
    before=_snapshot(root)
    root_identity=_identity(root.lstat())
    def load(name):
        _require(type(name)is str and name in before,"published artifact outside closed inventory")
        return (root/name).read_bytes()
    result={"schema":"published-legal384-private-cuda-closed-audit/v1","qualified":False,
        "execution_attestation":False,"errors":[],"reader_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_reader_sha256":hashlib.sha256(Path(__file__).with_name("audit_modal_formula_cuda.py").read_bytes()).hexdigest()}
    try:
        result["validated"]=validate(_parse(load("result.json")),load)
        result["qualified"]=True
    except (ValueError,KeyError,TypeError,OverflowError,RecursionError) as error:
        result["errors"].append(str(error))
    result["primary_archive"]={"preserved":before==_snapshot(root) and root_identity==_identity(root.lstat()),
        "files":len(before),"bytes":sum(pin["bytes"] for pin in before.values()),"inventory":before,
        "root_identity":list(root_identity)}
    result["qualified"]=result["qualified"] and result["primary_archive"]["preserved"]
    result["elapsed_seconds"]=time.monotonic()-start
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("archive",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    _require(not args.output.exists(),"published audit output must be new")
    value=audit(args.archive)
    args.output.write_bytes(_raw(value))
    args.output.chmod(0o444)
    print({key: item for key,item in value.items() if key!="primary_archive"})
    raise SystemExit(0 if value["qualified"] else 1)
