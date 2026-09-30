"""Score span-cache rows with the legacy 8-d checkpoint on CUDA.

Writes outside the feature-pretraining campaign root and uploads shards to a
dataset branch so commits do not move the branch the feature run publishes on.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")
os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"] = "0"
os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import pyarrow as pa
import pyarrow.parquet as pq
import torch
from huggingface_hub import HfApi

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
    cosine_similarity,
    mse_loss,
)

ROOT = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/legacy-cuda-span-scores")
CHECKPOINT = Path(
    "/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/"
    "federal-corpus-audits/feature-pretraining-smoke-20260930/parent/"
    "legal-ir-autoencoder-canonical-20260630T221836Z.state.json"
)
LAWS = Path(
    "/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots/"
    "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/uscode_parquet/laws.parquet"
)
SPANS = Path("/tmp/legacy-span-inputs/autoformal/uscode/resume-checkpoint.parquet")
RESOLVED = ROOT / "resolved-spans.parquet"
CURSOR = ROOT / "cursor.json"
PARTS = ROOT / "parts"
REPO = "justicedao/uscode-autoformal-span-cache"
BRANCH = "legacy-dense-v1-cuda-span-scores"
REMOTE_PREFIX = "autoformal/uscode/legacy-dense-v1-cuda/span-scores"
SCHEMA = "legacy-dense-v1-cuda-span-score/v1"
SHARD_ROWS = 1000
CHECKPOINT_SHA = "7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text or "").strip()
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", flat) if part.strip()]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def log(message: str) -> None:
    print(message, flush=True)


def build_index() -> int:
    if RESOLVED.exists() and RESOLVED.stat().st_size > 0:
        rows = pq.ParquetFile(RESOLVED).metadata.num_rows
        log(f"index_ready rows={rows}")
        return rows
    spans = pq.read_table(
        SPANS, columns=["record_kind", "status", "reason", "source_sha256", "source_span_id", "legal_id"]
    )
    wanted: dict[str, list[dict[str, str]]] = {}
    for kind, status, reason, digest, span_id, legal_id in zip(
        spans.column("record_kind").to_pylist(),
        spans.column("status").to_pylist(),
        spans.column("reason").to_pylist(),
        spans.column("source_sha256").to_pylist(),
        spans.column("source_span_id").to_pylist(),
        spans.column("legal_id").to_pylist(),
    ):
        if kind != "span" or not digest or not span_id:
            continue
        wanted.setdefault(digest, []).append(
            {
                "source_span_id": span_id,
                "source_sha256": digest,
                "legal_id": legal_id or "",
                "status": status or "",
                "reason": reason or "",
            }
        )
    found: dict[str, tuple[str, str, str]] = {}
    laws = pq.read_table(LAWS, columns=["title_number", "section_number", "text"])
    for title, section, text in zip(
        laws.column("title_number").to_pylist(),
        laws.column("section_number").to_pylist(),
        laws.column("text").to_pylist(),
    ):
        if len(found) == len(wanted):
            break
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        candidates = [cleaned, text or ""]
        candidates.extend(sentences(text or ""))
        for candidate in candidates:
            digest = sha(candidate)
            if digest in wanted and digest not in found:
                found[digest] = (str(title or ""), str(section or ""), candidate)
    missing = len(wanted) - len(found)
    if missing:
        raise SystemExit(f"unjoined span hashes: {missing}")
    rows = []
    for digest, metas in wanted.items():
        title, section, text = found[digest]
        for meta in metas:
            rows.append({**meta, "title": title, "section": section, "text": text})
    rows.sort(key=lambda row: (0 if row["status"] == "sealed" else 1, row["source_span_id"]))
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, RESOLVED)
    log(f"index_built rows={table.num_rows} sealed={sum(row['status']=='sealed' for row in rows)}")
    return table.num_rows


def contribution(item) -> dict:
    return {
        "contribution_type": item.contribution_type,
        "family": item.family,
        "feature": item.feature,
        "magnitude": item.magnitude,
        "value": item.value,
    }


def score_row(model, row: dict) -> dict:
    sample = build_us_code_sample(title=row["title"], section=row["section"], text=row["text"])
    raw = model._decoded_for(sample, use_sample_memory=False, apply_reconstruction_projection=False)
    report = model.introspect_sample(
        sample, use_sample_memory=False, include_causal_attribution=False, top_k=8
    )
    return {
        "schema_version": SCHEMA,
        "source_span_id": row["source_span_id"],
        "source_sha256": row["source_sha256"],
        "legal_id": row["legal_id"],
        "title": row["title"],
        "section": row["section"],
        "status": row["status"],
        "reason": row["reason"],
        "text": row["text"],
        "embedding_model": sample.embedding_model,
        "embedding_dim": len(sample.embedding_vector),
        "checkpoint_sha256": CHECKPOINT_SHA,
        "checkpoint_file_architecture": "legacy_dense_v1",
        "loaded_architecture": model.state.architecture_version,
        "compute_backend": model.compute_backend,
        "compute_device": str(model.compute_device),
        "physical_gpu_index": 1,
        "raw_cosine": cosine_similarity(sample.embedding_vector, raw),
        "raw_reconstruction_loss": mse_loss(sample.embedding_vector, raw),
        "projected_cosine": report.cosine_similarity,
        "projected_reconstruction_loss": report.reconstruction_loss,
        "target_family": report.target_family,
        "predicted_family": report.predicted_family,
        "family_margin": report.family_margin,
        "feature_count": report.feature_count,
        "top_family_contributions": [contribution(item) for item in report.top_family_contributions],
        "top_embedding_contributions": [contribution(item) for item in report.top_embedding_contributions],
        "pipeline_stage_focus": list(report.pipeline_stage_focus),
        "decoded_embedding": list(report.decoded_embedding),
        "sample_memory_used": False,
        "admitted": False,
        "qualified": False,
        "formalized": False,
    }


def worker_id() -> tuple[int, int]:
    worker = int(os.environ.get("LEGACY_SCORE_WORKER", "0"))
    workers = int(os.environ.get("LEGACY_SCORE_WORKERS", "1"))
    if workers < 1 or not 0 <= worker < workers:
        raise SystemExit(f"invalid worker {worker} of {workers}")
    return worker, workers


def cursor_path(worker: int) -> Path:
    return ROOT / f"cursor-w{worker}.json"


def read_cursor(worker: int) -> dict:
    path = cursor_path(worker)
    if path.exists():
        return json.loads(path.read_text())
    return {"next_offset": 0, "uploaded_shards": [], "errors": 0, "scored": 0, "worker": worker}


def write_cursor(worker: int, cursor: dict) -> None:
    path = cursor_path(worker)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(cursor, sort_keys=True))
    temporary.replace(path)


def defer_upload() -> bool:
    return os.environ.get("LEGACY_SCORE_DEFER_UPLOAD") == "1"


def upload_shard(api: HfApi, path: Path, remote_name: str) -> str:
    if defer_upload():
        log(f"deferred {remote_name}")
        return "deferred"
    last_error = None
    for attempt in range(6):
        try:
            info = api.upload_file(
                path_or_fileobj=str(path),
                path_in_repo=f"{REMOTE_PREFIX}/{remote_name}",
                repo_id=REPO,
                repo_type="dataset",
                revision=BRANCH,
                commit_message=f"legacy dense v1 CUDA span scores {remote_name}",
            )
            return str(getattr(info, "commit_url", "") or getattr(info, "oid", "") or "uploaded")
        except Exception as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            delay = min(20.0, 0.5 * (2 ** attempt))
            if status == 429:
                # The dataset commit cap is hourly. A short backoff exits and restarts the shard.
                raw = None
                headers = getattr(getattr(exc, "response", None), "headers", None)
                if headers is not None:
                    raw = headers.get("Retry-After")
                try:
                    hinted = float(raw)
                except (TypeError, ValueError):
                    hinted = 600.0
                delay = max(600.0, min(1200.0, hinted))
            log(
                f"upload_retry attempt={attempt} status={status} "
                f"error={type(exc).__name__} sleep_s={delay:.0f}"
            )
            time.sleep(delay)
    raise RuntimeError(f"shard upload failed: {last_error}")


def upload_manifest(api: HfApi, worker: int, workers: int, cursor: dict, owned: int, backend: str) -> None:
    manifest = {
        "schema_version": "legacy-dense-v1-cuda-span-score-manifest/v1",
        "repository_id": REPO,
        "branch": BRANCH,
        "worker": worker,
        "workers": workers,
        "checkpoint_sha256": CHECKPOINT_SHA,
        "checkpoint_file_architecture": "legacy_dense_v1",
        "embedding_model": "mock:stable-sha256",
        "embedding_dim": 8,
        "compute_backend": backend,
        "physical_gpu_index": 1,
        "source_dataset": "justicedao/ipfs_uscode",
        "source_revision": "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e",
        "owned_rows": owned,
        "scored": cursor["scored"],
        "next_offset": cursor["next_offset"],
        "errors": cursor["errors"],
        "uploaded_shards": cursor["uploaded_shards"],
        "measurement": "decoder output before the safety projection, plus the projected residual from introspection",
        "causal_ablation": False,
        "admitted": False,
        "qualified": False,
        "formalized": False,
    }
    destination = ROOT / f"manifest-w{worker}.json"
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    upload_shard(api, destination, destination.name)


def main() -> None:
    worker, workers = worker_id()
    ROOT.mkdir(parents=True, exist_ok=True)
    PARTS.mkdir(parents=True, exist_ok=True)
    Path(f"/tmp/legacy-cuda-span-score-w{worker}.pid").write_text(str(os.getpid()) + "\n")
    digest = file_sha256(CHECKPOINT)
    if digest != CHECKPOINT_SHA:
        raise SystemExit(f"checkpoint hash mismatch: {digest}")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available on the visible device")
    total = build_index()
    owned_indices = list(range(worker, total, workers))
    api = HfApi()
    if not defer_upload():
        for attempt in range(8):
            try:
                api.create_branch(repo_id=REPO, repo_type="dataset", branch=BRANCH, exist_ok=True)
                break
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                delay = 1.0 + attempt
                if status == 429 or "429" in str(exc)[:300]:
                    delay = 600.0
                log(
                    f"branch_retry worker={worker} attempt={attempt} "
                    f"status={status} error={type(exc).__name__} sleep_s={delay:.0f}"
                )
                time.sleep(delay)
        else:
            raise SystemExit("could not create the score branch")
    log(f"worker={worker}/{workers} gpu {torch.cuda.get_device_name(0)} owned={len(owned_indices)}")
    state = ModalAutoencoderTrainingState.load_json(CHECKPOINT)
    model = AdaptiveModalAutoencoder(state=state, compute_device="cuda")
    if model.compute_backend != "torch_cuda":
        raise SystemExit(f"expected torch_cuda, got {model.compute_backend}")
    log(
        f"model_ready worker={worker} architecture={state.architecture_version} "
        f"features={len(state.feature_embedding_weights)} backend={model.compute_backend}"
    )
    cursor = read_cursor(worker)
    table = pq.read_table(RESOLVED)
    started = time.perf_counter()
    while cursor["next_offset"] < len(owned_indices):
        offset = cursor["next_offset"]
        chosen = owned_indices[offset:offset + SHARD_ROWS]
        # Rows are sorted sealed-first, so take a contiguous slice when this worker owns a stride.
        batch = [table.slice(index, 1).to_pylist()[0] for index in chosen]
        first = chosen[0]
        shard_path = PARTS / f"part-w{worker}-{first:07d}.jsonl"
        errors_before = cursor["errors"]
        with shard_path.open("w") as handle:
            for ordinal, row in enumerate(batch):
                try:
                    scored = score_row(model, row)
                    scored["worker"] = worker
                except Exception as exc:
                    cursor["errors"] += 1
                    scored = {
                        "schema_version": SCHEMA,
                        "source_span_id": row["source_span_id"],
                        "source_sha256": row["source_sha256"],
                        "legal_id": row["legal_id"],
                        "status": row["status"],
                        "worker": worker,
                        "error": f"{type(exc).__name__}: {exc}",
                        "admitted": False,
                        "qualified": False,
                        "formalized": False,
                    }
                handle.write(json.dumps(scored, ensure_ascii=True, sort_keys=True) + "\n")
                handle.flush()
                cursor["scored"] += 1
                if cursor["scored"] <= 100 and (cursor["errors"] - errors_before) > 20:
                    raise SystemExit("too many scoring errors in the first shard")
                if ordinal and ordinal % 50 == 0:
                    elapsed = time.perf_counter() - started
                    log(
                        f"progress worker={worker} scored={cursor['scored']} "
                        f"offset={offset + ordinal + 1}/{len(owned_indices)} "
                        f"errors={cursor['errors']} elapsed_s={elapsed:.1f}"
                    )
        remote = shard_path.name
        upload_shard(api, shard_path, remote)
        cursor["next_offset"] = offset + len(chosen)
        cursor["uploaded_shards"].append(remote)
        write_cursor(worker, cursor)
        upload_manifest(api, worker, workers, cursor, len(owned_indices), model.compute_backend)
        log(
            f"uploaded {remote} worker={worker} offset={cursor['next_offset']}/"
            f"{len(owned_indices)} errors={cursor['errors']}"
        )
    log(f"EXIT:0 complete worker={worker} scored={cursor['scored']} errors={cursor['errors']}")


if __name__ == "__main__":
    main()
