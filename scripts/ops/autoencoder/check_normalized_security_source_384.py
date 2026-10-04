#!/usr/bin/env python3
"""Explicit hybrid AST-normalized inference on already exposed source panels.

Weights and raw-decoder measurements stay unchanged. This is a preprocessing
diagnostic, not a new heldout training experiment or a proof of Python behavior.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw(value))
    return dict(path=str(path), sha256=sha(path))


def run(panel_directory, checkpoint, checkpoint_sha256, output, lake_executable):
    from ipfs_datasets_py.logic.formalization.autoencoder import normalized_source_program_runtime_384 as normalized
    from ipfs_datasets_py.logic.formalization.autoencoder.security import source_normalization_384 as normalization
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import build_decoded_source_program_lake
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_lake_384 import verify_source_program_lake
    if output.exists():
        raise ValueError("fresh diagnostic directory required")
    runtime = normalized.load_normalized_source_program_decoder_384(checkpoint, expected_sha256=checkpoint_sha256)
    producer = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in (normalized, normalization)}
    producer[str(Path(__file__).resolve())] = sha(__file__)
    inputs = {str(checkpoint): checkpoint_sha256}
    output.mkdir(parents=True)
    summaries = {}
    for partition in ("test", "canary"):
        source_file = panel_directory / (partition + ".json")
        inputs[str(source_file)] = sha(source_file)
        rows = json.loads(source_file.read_text())["rows"]
        results, batches = [], []
        inference_seconds, unique_embedding_views = 0., 0
        zero_statuses = Counter()
        changed_by_zero_head = 0
        for start in range(0, len(rows), 64):
            chunk = rows[start:start+64]
            texts = [row["source_text"] for row in chunk]
            tick = time.perf_counter()
            # The only inference input is original source text. Gold rows are
            # consulted later solely to score, never to normalize or decode.
            decoded = runtime.infer_texts(texts)
            inference_seconds += time.perf_counter() - tick
            unique_embedding_views += decoded["unique_embedding_views"]
            original_candidates = [raw(row["candidate_ir"]) for row in decoded["rows"]]
            source_rows = [dict(id="input-" + str(index), source_text=text) for index, text in enumerate(texts)]
            out = output / (partition + "-lake-" + str(start // 64))
            handle = build_decoded_source_program_lake(decoded, source_rows, lake_executable=lake_executable,
                output_directory=out)
            gate_rows = [dict(**source, candidate_ir=prediction["candidate_ir"])
                for source, prediction in zip(source_rows, decoded["rows"])]
            receipt = verify_source_program_lake(handle, gate_rows)
            if original_candidates != [raw(row["candidate_ir"]) for row in decoded["rows"]]:
                raise ValueError("source gate rewrote a decoded candidate")
            ablated = runtime.infer_texts(texts, weight_ablation="zero_head")
            for before, after in zip(decoded["rows"], ablated["rows"]):
                zero_statuses[after.get("source_contract", {}).get("status", "no_candidate")] += 1
                changed_by_zero_head += int(before["candidate_ir"] != after["candidate_ir"])
            for source, prediction, checked in zip(chunk, decoded["rows"], receipt["rows"]):
                results.append(dict(source_id=source["id"], source_sha256=prediction["source_sha256"],
                    candidate_sha256=hashlib.sha256(raw(prediction["candidate_ir"])).hexdigest(),
                    exact_target=prediction["candidate_ir"] == source["target"],
                    source_status=prediction.get("source_contract", {}).get("status", "no_candidate"),
                    normalization=prediction["source_normalization"], lake_status=checked["lake_status"],
                    head_sha256=prediction["head_sha256"], projection_sha256=prediction["projection_sha256"]))
            batches.append(dict(receipt_path=str(out / "receipt.json"), receipt_sha256=sha(out / "receipt.json"),
                inference=save(output / (partition + "-inference-" + str(start // 64) + ".json"), decoded),
                zero_head=save(output / (partition + "-zero-head-" + str(start // 64) + ".json"), ablated),
                status=receipt["status"], backend_executed=receipt["backend_executed"],
                execution=receipt["execution"], producer=receipt["producer"],
                tool_binary_sha256=receipt["tool_binary_sha256"]))
        summary = dict(count=len(rows), exact=sum(row["exact_target"] for row in results),
            source_status_counts=dict(Counter(row["source_status"] for row in results)),
            lake_status_counts=dict(Counter(row["lake_status"] for row in results)),
            normalization_status_counts=dict(Counter(row["normalization"]["status"] for row in results)),
            actual_lake_builds=sum(batch["backend_executed"] for batch in batches), batches=batches, rows=results,
            inference_seconds=inference_seconds, unique_embedding_views_across_batches=unique_embedding_views,
            inference_timing_scope="normalization, verified CUDA-or-CPU embedding, numerical decoding and original-source qualification; first call includes model load",
            zero_head=dict(count=len(rows), source_status_counts=dict(zero_statuses), changed_candidates=changed_by_zero_head))
        summaries[partition] = summary
        save(output / (partition + "-report.json"), summary)
        print(json.dumps({key: summary[key] for key in ("count", "exact", "source_status_counts", "lake_status_counts")}), flush=True)
    for path, expected in {**inputs, **producer}.items():
        if sha(path) != expected:
            raise ValueError("diagnostic input or producer changed")
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    observed_embedding_devices = sorted({str(next(model.parameters()).device)
        for model in source_embeddings_384._MODEL_CACHE.values()})
    result = dict(schema="hybrid-normalized-source-384-diagnostic/v1", runtime=runtime.describe(),
        checkpoint=dict(path=str(checkpoint), sha256=checkpoint_sha256), producer=producer, input_sha256=inputs,
        observed_embedding_parameter_devices=observed_embedding_devices,
        partitions=summaries, source_input_view="guarded_ast_normalized", raw_decoder_accuracy_replaced=False,
        already_exposed_development_regression=True, fresh_holdout=False, source_parser_used=True,
        training_performed=False, prediction_repair_performed=False, source_files_modified=False,
        proof_authority=False, source_semantics_verified=False, model_promoted=False,
        scope="hybrid AST-preprocessed learned decoder over narrow Int/Bool source grammar; compilation is definition/type evidence")
    save(output / "report.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-directory", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--lake-executable", required=True)
    args = parser.parse_args()
    run(args.panel_directory.resolve(), args.checkpoint.resolve(), args.checkpoint_sha256,
        args.output_directory.resolve(), args.lake_executable)
