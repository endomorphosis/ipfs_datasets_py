#!/usr/bin/env python3
"""Generate a bounded evidence batch; optional publication appends immutable files.

Source Parquet bypasses demonstrations. Compiler/codec/Lake receipts never grant
legal admission, statute proof, or learned-model training authority.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _publish_telemetry(path: Path, **kwargs):
    from ipfs_datasets_py.logic.autoformal.conversion_telemetry import publish_conversion_telemetry

    return publish_conversion_telemetry(path, **kwargs)


def _save(path: Path, value: Any) -> dict:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("evidence receipt exceeds bound")
    with path.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"bytes": len(raw), "sha256": _sha(raw), "name": path.name}


def read_source_spans(path: Path) -> tuple[list[dict], dict]:
    from ipfs_datasets_py.logic.autoformal.span_evidence import _batch_snapshot, MAX_BATCH_FILE_BYTES, MAX_BATCH_ROWS
    import pyarrow as pa
    import pyarrow.parquet as pq

    raw = _batch_snapshot(path)
    parquet = pq.ParquetFile(io.BytesIO(raw))
    required = ("source_span_id", "legal_id", "source_text")
    optional = "source_provenance_json"
    if not 1 <= parquet.metadata.num_rows <= MAX_BATCH_ROWS:
        raise ValueError("source row count exceeds bound")
    if len(parquet.schema_arrow.names) != len(set(parquet.schema_arrow.names)):
        raise ValueError("duplicate source columns")
    selected = [*required, *([optional] if optional in parquet.schema_arrow.names else [])]
    if any(name not in parquet.schema_arrow.names or not pa.types.is_string(parquet.schema_arrow.field(name).type)
           for name in selected):
        raise ValueError("source columns must be strings")
    if sum(parquet.metadata.row_group(i).total_byte_size for i in range(parquet.num_row_groups)) > MAX_BATCH_FILE_BYTES:
        raise ValueError("source decoded size exceeds bound")
    rows = parquet.read(columns=selected, use_threads=False).to_pylist()
    ids = set()
    for row in rows:
        if any(type(row[name]) is not str or not row[name].strip() for name in required):
            raise ValueError("source row requires ID, legal ID, and actual text")
        if row["source_span_id"] in ids or any(len(row[name].encode()) > 32768 for name in required):
            raise ValueError("source identity duplicate or text bound exceeded")
        ids.add(row["source_span_id"])
        if optional in row:
            if type(row[optional]) is not str or len(row[optional].encode()) > 131072:
                raise ValueError("source provenance exceeds bound")
            proof = json.loads(row[optional])
            if not isinstance(proof, dict):
                raise ValueError("source provenance must be an object")
        row["text"] = row["source_text"]
    return rows, {"sha256": _sha(raw), "bytes": len(raw), "row_count": len(rows)}


def measured_codec_capture(codec, text: str) -> dict:
    """Same deterministic codec observations, with absent measurements kept null."""
    from ipfs_datasets_py.logic.modal.ir_symbol_catalog import bluebook_symbols

    encoded = codec.encode(text, document_id="source-batch-" + _sha(text.encode())[:16])
    losses = dict(getattr(encoded, "losses", {}) or {})
    formulas = []
    for formula in list(getattr(encoded.modal_ir, "formulas", ()) or ())[:6]:
        operator, predicate = formula.operator.to_dict(), formula.predicate.to_dict()
        metadata = dict(getattr(formula, "metadata", {}) or {})
        row = {"arguments": [str(v) for v in predicate.get("arguments") or []][:4],
               "op": str(operator.get("symbol") or operator.get("name") or ""),
               "predicate": str(predicate.get("name") or "")}
        for key, value in (("aliased_from", metadata.get("aliased_from")), ("role", predicate.get("role"))):
            if value:
                row[key] = str(value)
        formulas.append(row)
    metadata = dict(getattr(encoded, "metadata", {}) or {})
    return {
        "codec_observation": {"spacy_model_name": metadata.get("spacy_model_name"),
                              "spacy_used_fallback_model": metadata.get("spacy_used_fallback_model"),
                              "parser_backend": metadata.get("parser_backend"),
                              "spacy_token_count": metadata.get("spacy_token_count"),
                              "source_embedding_kind": "stable_mock_embedding",
                              "decoded_embedding_kind": "structural_feature_hashing",
                              "learned_embedding": False,
                              "modal_ir": encoded.modal_ir.to_dict(),
                              "raw_losses": losses,
                              "full_structural_text": metadata.get("modal_decompiler_structural_text"),
                              "full_decoded_text": str(getattr(encoded, "decoded_text", "") or "")},
        "cosine_loss": losses.get("source_decompiled_text_embedding_cosine_loss"),
        "cosine_similarity": losses.get("source_decompiled_text_embedding_cosine_similarity"),
        "cross_entropy_loss": losses.get("cross_entropy_loss"),
        "ir_compression_loss": losses.get("ir_compression_loss"),
        "ir_compression_ratio": losses.get("ir_compression_ratio"),
        "reconstruction_loss": losses.get("text_reconstruction_loss"),
        "view_cross_entropy_loss": losses.get("guidance_legal_ir_view_cross_entropy_loss"),
        "citations": bluebook_symbols(text)[:6], "formulas": formulas,
        "decoded_text": " ".join(str(getattr(encoded, "decoded_text", "") or "").split()),
        "structural": " ".join(str((encoded.metadata or {}).get("modal_decompiler_structural_text") or "").split())[:180],
    }


def generate_batch(spans, *, compile_source: bool, lake_limit: int, lake_successes: int,
                   capture=None, compile_one=None, lake_check=None, code_identity=""):
    from ipfs_datasets_py.logic.autoformal.span_evidence import generate_span_evidence, _lean_source

    generation_started = time.perf_counter()
    injected_capture = capture is not None
    if capture is None:
        from ipfs_datasets_py.logic.modal.codec import DeterministicModalLogicCodec, ModalLogicCodecConfig
        codec = DeterministicModalLogicCodec(ModalLogicCodecConfig(use_flogic=False))
        capture = lambda text: measured_codec_capture(codec, text)
    if compile_one is None:
        from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
        session = AutoformalSession()
        compile_one = lambda _session, text, span_id: compile_span(
            session, text, span_id, vocabulary=None, allow_partial=False)
    if lake_check is None:
        from ipfs_datasets_py.logic.autoformal.lake_probe import lake_check
    inputs, lakes, codec_rows = [], [], []

    def timed_capture(text):
        started = time.perf_counter()
        result = dict(capture(text) or {})
        elapsed = time.perf_counter() - started
        index = len(codec_rows)
        if index >= len(spans):
            raise ValueError("unexpected codec call")
        original = spans[index]
        codec_rows.append({"source_span_id": original["source_span_id"],
                           "codec_input_sha256": _sha(text.encode()),
                           "wall_seconds": elapsed,
                           "full_decoded_text": str((result.get("codec_observation") or {}).get(
                               "full_decoded_text", result.get("decoded_text") or "")),
                           "observation": result.get("codec_observation"),
                           "injected_capture": injected_capture})
        return result

    def compiler(active, text, span_id):
        started = time.perf_counter()
        result = dict(compile_one(active, text, span_id) or {})
        elapsed = time.perf_counter() - started
        inputs.append({"source_span_id": span_id, "compiler_input": text, "wall_seconds": elapsed,
                       "compiler_input_sha256": _sha(text.encode()),
                       "compiler_result": result,
                       "compiler_status": str(result.get("compiler_status") or result.get("status") or "")})
        return result

    def lake(source):
        started = time.perf_counter()
        result = dict(lake_check(source) or {})
        elapsed = time.perf_counter() - started
        code = result.get("returncode")
        if code is not None and type(code) is not int:
            raise ValueError("Lake returncode must be an integer or null")
        lakes.append({"source": source, "source_sha256": _sha(source.encode()),
                      "lake_ok": result.get("lake_ok") is True, "wall_seconds": elapsed,
                      "returncode": code, "log": str(result.get("log") or ""),
                      "error": str(result.get("error") or ""),
                      "scope": "definitional modality/fingerprint boundary only",
                      "admitted": False, "formalized": False})
        return result

    rows = generate_span_evidence(spans, capture=timed_capture, compile_one=compiler, lake_check=lake,
                                 lake_limit=lake_limit, lake_successes=lake_successes,
                                 code_identity=code_identity,
                                 compiler_input_mode="source" if compile_source else "decoded")
    generation_seconds = time.perf_counter() - generation_started
    if len(rows) != len(spans) or len(inputs) != len(spans) or len(codec_rows) != len(spans):
        raise ValueError("generation did not cover every requested source span")
    by_id = {row["source_span_id"]: row for row in spans}
    for row in inputs:
        original = by_id[row["source_span_id"]]
        text = str(original.get("source_text") or original.get("text") or "")
        row.update(legal_id=original.get("legal_id", ""), original_source_text=text,
                   original_source_sha256=_sha(text.encode()),
                   source_provenance_json=original.get("source_provenance_json"))
        if compile_source and row["compiler_input"] != text:
            raise ValueError("source compilation changed the original input")
    # Both existing success and abstention paths render these exact formulas.
    # Identical Lean programs may correspond to multiple source spans; preserve all.
    lean_spans = {}
    for row in rows:
        lean = _lean_source(json.loads(row["formulas_json"]))
        if lean:
            lean_spans.setdefault(_sha(lean.encode()), []).append(row["source_span_id"])
    for record in lakes:
        record["source_span_ids"] = lean_spans.get(record["source_sha256"], [])
        if not record["source_span_ids"]:
            raise ValueError("Lake observation has no source span binding")
    return rows, {"compiler_inputs": inputs, "codec_observations": codec_rows, "lake_checks": lakes,
                  "generation_wall_seconds": generation_seconds,
                  "timing_scope": "total includes setup, codec, compiler, Lake, and row projection; stage times are nested",
                  "codec_use_flogic": False if not injected_capture else None,
                  "bridge_names": [], "evaluate_provers": False, "workers": 1,
                  "bridge_evaluate_run": False, "metric_cache_enabled": False,
                  "metric_cache_scope": "bridge metric cache not invoked by direct codec path",
                  "compiler_input_mode": "source" if compile_source else "decoded",
                  "external_vocabulary_supplied": False, "allow_partial_requested": False,
                  "codec_kind": "DeterministicModalLogicCodec", "learned_autoencoder_execution": False,
                  "native_model_training": False, "statute_semantics_proved": False,
                  "admitted": False, "formalized": False}


def verify_published_batch(publication: dict, rows: list[dict], proof_raw: bytes, *, download=None) -> dict:
    """Verify only the immutable returned commit, never mutable main."""
    from ipfs_datasets_py.logic.autoformal.span_evidence import _batch_snapshot, evidence_schema
    import pyarrow.parquet as pq

    if download is None:
        from huggingface_hub import hf_hub_download
        download = hf_hub_download
    sha = publication["commit_sha"]
    if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("immutable published SHA required")
    for item in publication["files"]:
        path = download(repo_id=publication["repository_id"], filename=item["path_in_repo"],
                        repo_type="dataset", revision=sha)
        # Hub cache paths can be symlinks: resolve explicitly to the immutable blob.
        raw = _batch_snapshot(Path(path).resolve(strict=True))
        if len(raw) != item["bytes"] or _sha(raw) != item["sha256"]:
            raise ValueError("pinned remote payload differs")
        if item["path_in_repo"].endswith("/span-evidence.parquet"):
            table = pq.ParquetFile(io.BytesIO(raw)).read(use_threads=False)
            if not table.schema.equals(evidence_schema(), check_metadata=False) or table.to_pylist() != rows:
                raise ValueError("pinned schema or exact evidence rows differ")
        elif raw != proof_raw:
            raise ValueError("pinned provenance differs")
    return {"commit_sha": sha, "verified": True, "file_count": len(publication["files"]),
            "row_count": len(rows), "admitted": False, "formalized": False}


def main(argv=None) -> int:
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    tree_pin = require_workspace_logic_tree()
    from ipfs_datasets_py.logic.autoformal.span_evidence import (
        BATCH_PROVENANCE_SCHEMA, _batch_snapshot, demonstration_spans,
        publish_span_evidence_batch, write_span_evidence_parquet)
    from ipfs_datasets_py.logic.autoformal.span_cache import compiler_identity, compiler_path_hashes

    parser = argparse.ArgumentParser(description="generate a small source-backed span evidence batch")
    parser.add_argument("--input-parquet", type=Path)
    parser.add_argument("--compile-source", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("/tmp/ipfs-uscode-autoformal/span-evidence.parquet"))
    parser.add_argument("--cache", default=None)
    parser.add_argument("--federal", type=int, default=4)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--lake-limit", type=int, default=4)
    parser.add_argument("--lake-successes", type=int, default=2)
    parser.add_argument("--no-federal", action="store_true")
    parser.add_argument("--batch-id")
    parser.add_argument("--audited-parent-commit")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.lake_limit <= 64 or not 0 <= args.lake_successes <= 64:
        parser.error("Lake count must be in0..64")
    if args.upload and not args.audited_parent_commit:
        parser.error("upload requires --audited-parent-commit")
    output = args.output.absolute()
    proof_path = output.with_suffix(".provenance.json")
    receipt_path = output.with_suffix(".receipt.json")
    publication_path = output.with_suffix(".publication.json")
    telemetry_path = output.with_name(output.stem + ".conversion-telemetry.parquet")
    if any(p.exists() or p.is_symlink() for p in (output, proof_path, receipt_path, publication_path, telemetry_path)):
        parser.error("output and receipt paths must be new")
    if args.input_parquet:
        spans, source = read_source_spans(args.input_parquet)
    else:
        spans, source = demonstration_spans(), None
        if not args.no_federal and args.federal > 0:
            from ipfs_datasets_py.logic.autoformal.span_agreement import FEDERAL_SPAN_CACHE, sample_federal_spans
            spans.extend(sample_federal_spans(args.cache or FEDERAL_SPAN_CACHE,
                                            count=args.federal, seed=args.seed, status="gap"))
    if not 1 <= len(spans) <= 64:
        parser.error("batch must contain1..64 spans")
    paths = compiler_path_hashes(ROOT)
    rows, execution = generate_batch(spans, compile_source=args.compile_source,
                                    lake_limit=args.lake_limit, lake_successes=args.lake_successes,
                                    code_identity=compiler_identity(paths))
    if args.input_parquet and _sha(_batch_snapshot(args.input_parquet)) != source["sha256"]:
        raise ValueError("source input changed during generation")
    if tree_pin != require_workspace_logic_tree():
        raise ValueError("compiler runtime origin changed during generation")
    if paths != compiler_path_hashes(ROOT):
        raise ValueError("compiler source identity changed during generation")
    from ipfs_datasets_py.logic.autoformal.conversion_telemetry import conversion_telemetry_rows, write_conversion_telemetry

    output.parent.mkdir(parents=True, exist_ok=True)
    written = write_span_evidence_parquet(rows, output, exclusive=True)
    telemetry_rows = conversion_telemetry_rows(
        rows,
        hyperparameters={
            "bridge_names": list(execution.get("bridge_names") or []),
            "epochs": 0 if execution.get("native_model_training") is False else 1,
            "rounds": 0,
            "seed": args.seed,
        },
    )
    telemetry_written = write_conversion_telemetry(telemetry_rows, telemetry_path)
    batch_id = args.batch_id or "source-" + written["sha256"][:24]
    proof = {"schema_version": BATCH_PROVENANCE_SCHEMA, "batch_id": batch_id,
             "input_artifact": source, "source_backed": source is not None,
             "parquet": {key: written[key] for key in ("sha256", "bytes", "row_count")},
             "compiler_path_hashes": paths, "logic_tree_pin": tree_pin, **execution}
    proof_ref = _save(proof_path, proof)
    publication = None
    telemetry_publication = None
    verification = None
    if args.upload:
        publication = publish_span_evidence_batch(output, proof_path, batch_id=batch_id,
                                                  audited_parent_commit=args.audited_parent_commit, upload=True)
        telemetry_publication = _publish_telemetry(
            telemetry_path,
            upload=True,
            path_in_repo=f"autoformal/uscode/batches/{batch_id}/conversion-telemetry.parquet",
        )
        # Persist the observed commit before verification so response/download
        # failure cannot erase evidence of a completed remote mutation.
        _save(publication_path, publication)
        verification = verify_published_batch(publication, rows, proof_path.read_bytes())
    receipt = {"schema_version": "uscode-autoformal-span-batch-execution/v1",
               "batch_id": batch_id, "parquet": proof["parquet"], "provenance": proof_ref,
               "telemetry": telemetry_written, "telemetry_publication": telemetry_publication,
               "source_backed": source is not None, "publication": publication, "verification": verification,
               "admitted": False, "formalized": False, "native_model_training": False}
    _save(receipt_path, receipt)
    print(json.dumps({"row_count": len(rows), "uploaded": publication is not None,
                      "commit_sha": publication["commit_sha"] if publication else None,
                      "receipt": str(receipt_path), "admitted": False, "formalized": False}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
