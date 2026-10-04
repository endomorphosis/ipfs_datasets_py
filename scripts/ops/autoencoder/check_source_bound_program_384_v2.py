#!/usr/bin/env python3
"""Replay frozen Security weights through source binding and actual native Lake.

Consumes all primary/canary rows without targets; never fits, selects parameters,
rewrites predictions, or treats compilation as proof of source equivalence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, value):
    path.write_bytes(_raw(value))
    return {"path": str(path), "sha256": _sha(path.read_bytes())}


def run(run_directory, output_directory, *, freeze_sha256, lake_executable, source_text_replay=False):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_program_runtime_384 as consumer
    from ipfs_datasets_py.logic.formalization.autoencoder import source_program_lake_384 as gate
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384 as embeddings
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder

    root, output = Path(run_directory).resolve(), Path(output_directory).resolve()
    if output.exists():
        raise ValueError("fresh replay directory required")
    if _sha((root / "freeze.json").read_bytes()) != freeze_sha256:
        raise ValueError("frozen experiment identity differs")
    freeze = json.loads((root / "freeze.json").read_text())
    for relative, digest in freeze.items():
        path = (root / relative).resolve()
        if root not in path.parents or _sha(path.read_bytes()) != digest:
            raise ValueError("frozen experiment file differs: " + relative)
    checkpoint = root / "security_ir/augmented-0-checkpoint.json"
    checkpoint_sha = freeze["security_ir/augmented-0-checkpoint.json"]
    runtime = consumer.load_source_program_decoder_384(checkpoint, expected_sha256=checkpoint_sha)
    input_hashes = {"freeze.json": freeze_sha256, **freeze}
    producer = {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
                for module in (consumer, embeddings, decoder)}
    producer[str(Path(__file__).resolve())] = _sha(Path(__file__).read_bytes())
    output.mkdir(parents=True)
    summaries = {}
    for partition in ("test", "canary"):
        source_path = root / ("security_ir/" + partition + ".json")
        archive_path = root / ("security_ir/augmented-" + partition + "-evaluation.json")
        for path in (source_path, archive_path):
            input_hashes[str(path.relative_to(root))] = _sha(path.read_bytes())
        # Strip all target/style/score fields before calling the learned runtime.
        records = json.loads(source_path.read_text())["rows"]
        inputs = [{key: row[key] for key in ("id", "source_text", "embedding")} for row in records]
        source_rows = [{key: row[key] for key in ("id", "source_text")} for row in inputs]
        start = time.perf_counter()
        report = runtime.infer(inputs)
        decode_seconds = time.perf_counter() - start
        archived = json.loads(archive_path.read_text())["reconstruction"]["rows"]
        identity_fields = ("id", "source_sha256", "candidate_ir", "head_sha256", "projection_sha256")
        predicted_identity = [{key: row[key] for key in identity_fields} for row in report["rows"]]
        archived_identity = [{key: row[key] for key in identity_fields} for row in archived]
        if predicted_identity != archived_identity:
            raise ValueError("live predictions differ from frozen evaluation: " + partition)
        decoded_artifact = _write(output / (partition + "-inference.json"), report)
        start = time.perf_counter()
        execution = consumer.build_decoded_source_program_lake(report, source_rows,
            lake_executable=lake_executable, output_directory=output / (partition + "-lake"))
        gate_rows = [dict(id=predicted["id"], source_text=source["source_text"], candidate_ir=predicted["candidate_ir"])
            for source, predicted in zip(source_rows, report["rows"])]
        receipt = gate.verify_source_program_lake(execution, gate_rows)
        lake_workflow_seconds = time.perf_counter() - start
        row_summaries = [dict(id=row["id"], source_sha256=row["source_sha256"],
            candidate_sha256=row["candidate_sha256"], source_status=row["source_qualification"]["status"],
            lake_status=row["lake_status"], reason=row["reason"]) for row in receipt["rows"]]
        summary = dict(count=len(inputs), status=receipt["status"],
            source_status_counts=dict(Counter(row["source_status"] for row in row_summaries)),
            lake_status_counts=dict(Counter(row["lake_status"] for row in row_summaries)),
            actual_lake_builds=int(receipt["backend_executed"]),
            predictions_equal_frozen_evaluation=True, predictions_sha256=_sha(_raw(predicted_identity)),
            decode_with_source_qualification_seconds=decode_seconds,
            lake_with_preparation_and_live_verification_seconds=lake_workflow_seconds,
            inference=decoded_artifact, rows=row_summaries,
            lake_receipt={"path": str(output / (partition + "-lake/receipt.json")),
                "sha256": _sha((output / (partition + "-lake/receipt.json")).read_bytes())},
            producer=receipt["producer"], tool_binary_sha256=receipt["tool_binary_sha256"],
            toolchain=receipt["execution"].get("toolchain"))
        # An intervention verifies the head participates numerically; source
        # checks do not silently repair a zeroed decoder back to the AST target.
        ablated = runtime.infer(inputs, weight_ablation="zero_head")
        summary["zero_head_ablation"] = dict(count=len(inputs),
            changed_candidates=sum(a["candidate_ir"] != b["candidate_ir"]
                for a, b in zip(ablated["rows"], report["rows"])),
            source_status_counts=dict(Counter(row.get("source_contract", {}).get("status", "no_candidate")
                for row in ablated["rows"])), lake_executed=False)
        summary["zero_head_ablation"]["artifact"] = _write(output / (partition + "-zero-head.json"), ablated)
        if source_text_replay:
            start = time.perf_counter()
            live = runtime.infer_texts([row["source_text"] for row in inputs])
            duration = time.perf_counter() - start
            # infer_texts assigns input-N IDs; source/candidate identity remains.
            compared = tuple(key for key in identity_fields if key != "id")
            matches = sum(all(a[key] == b[key] for key in compared)
                for a, b in zip(live["rows"], report["rows"]))
            import torch
            summary["source_text_replay"] = dict(count=len(live["rows"]),
                matching_candidates_and_source_hashes=matches,
                source_status_counts=dict(Counter(row.get("source_contract", {}).get("status", "no_candidate")
                    for row in live["rows"])), seconds=duration,
                device="cuda:" + str(torch.cuda.current_device()) if torch.cuda.is_available() else "cpu",
                scope="includes hash verification, embedding, decoding and source qualification; first call includes model load",
                artifact=_write(output / (partition + "-source-text.json"), live))
        summaries[partition] = summary
        _write(output / (partition + "-summary.json"), summary)
        print(json.dumps({"partition": partition, "count": summary["count"], "status": summary["status"],
            "source_status_counts": summary["source_status_counts"], "lake_status_counts": summary["lake_status_counts"]}), flush=True)
    for name, expected in input_hashes.items():
        if _sha((root / name).read_bytes()) != expected:
            raise ValueError("historical input changed during replay: " + name)
    for path, expected in producer.items():
        if _sha(Path(path).read_bytes()) != expected:
            raise ValueError("inference producer changed during replay")
    result = dict(schema="source-bound-program-384-checkpoint-lake/v2", run_directory=str(root),
        checkpoint={"path": str(checkpoint), "sha256": checkpoint_sha}, runtime=runtime.describe(),
        producer=producer, input_sha256=input_hashes, partitions=summaries,
        frozen_files_unchanged=True, training_performed=False, checkpoint_modified=False,
        prediction_repair_performed=False, publication_performed=False,
        proof_authority=False, source_semantics_verified=False, execution_authority=False,
        security_specification_inferred=False,
        scope="authored closed-schema development panel; native mathematical Int/Bool definitions, not arbitrary Python or CVE correctness")
    _write(output / "report.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--lake-executable", required=True)
    parser.add_argument("--source-text-replay", action="store_true")
    args = parser.parse_args()
    run(args.run_directory, args.output_directory, freeze_sha256=args.freeze_sha256,
        lake_executable=args.lake_executable, source_text_replay=args.source_text_replay)
