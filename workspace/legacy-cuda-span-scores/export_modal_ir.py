"""Recover the modal IR the span scorer parsed and then dropped.

The numeric score shards keep reconstruction metrics only. This process reads
the same resolved span rows, runs the deterministic legal modal parser, and
uploads the formula documents to the dataset's main branch.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import HfApi

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample

ROOT = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/legacy-cuda-span-scores")
RESOLVED = ROOT / "resolved-spans.parquet"
OUT = ROOT / "modal-ir"
PARTS = OUT / "parts"
LOCK = OUT / "upload.lock"
REPO = "justicedao/uscode-autoformal-span-cache"
REVISION = "main"
REMOTE_PREFIX = "autoformal/uscode/modal-ir/legal-modal-parser-v1"
SCHEMA = "uscode-modal-ir/v1"
SHARD_ROWS = 4000
DEFER_UPLOAD = os.environ.get("MODAL_IR_DEFER_UPLOAD", "1") == "1"


def log(message: str) -> None:
    print(message, flush=True)


def worker_id() -> tuple[int, int]:
    worker = int(os.environ["MODAL_IR_WORKER"])
    workers = int(os.environ["MODAL_IR_WORKERS"])
    if workers < 1 or not 0 <= worker < workers:
        raise SystemExit(f"invalid worker {worker} of {workers}")
    return worker, workers


def logic_line(formula) -> str:
    operator = formula.operator
    predicate = formula.predicate
    arguments = [str(item) for item in predicate.arguments if str(item)]
    atom = predicate.name if not arguments else f"{predicate.name}({', '.join(arguments)})"
    line = f"{operator.symbol}({atom})"
    if formula.conditions:
        line += " if " + " ; ".join(formula.conditions)
    if formula.exceptions:
        line += " unless " + " ; ".join(formula.exceptions)
    return line


def cursor_path(worker: int) -> Path:
    return OUT / f"cursor-w{worker}.json"


def read_cursor(worker: int) -> dict:
    path = cursor_path(worker)
    if path.exists():
        return json.loads(path.read_text())
    return {"next_offset": 0, "uploaded_shards": [], "errors": 0, "parsed": 0, "formula_count": 0, "worker": worker}


def write_cursor(worker: int, cursor: dict) -> None:
    temporary = cursor_path(worker).with_suffix(".json.tmp")
    temporary.write_text(json.dumps(cursor, sort_keys=True))
    temporary.replace(cursor_path(worker))


def publish_file(api: HfApi, path: Path, remote_name: str) -> None:
    if DEFER_UPLOAD:
        log(f"local {remote_name}")
        return
    upload_file(api, path, remote_name)


def upload_file(api: HfApi, path: Path, remote_name: str) -> None:
    last_error = None
    for attempt in range(8):
        try:
            with LOCK.open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    api.upload_file(
                        path_or_fileobj=str(path),
                        path_in_repo=f"{REMOTE_PREFIX}/{remote_name}",
                        repo_id=REPO,
                        repo_type="dataset",
                        revision=REVISION,
                        commit_message=f"uscode modal IR {remote_name}",
                    )
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            return
        except Exception as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            delay = min(20.0, 0.5 * (2 ** attempt))
            if status == 429:
                raw = None
                headers = getattr(getattr(exc, "response", None), "headers", None)
                if headers is not None:
                    raw = headers.get("Retry-After")
                try:
                    hinted = float(raw)
                except (TypeError, ValueError):
                    hinted = 60.0
                delay = max(delay, min(90.0, hinted))
            log(f"upload_retry attempt={attempt} status={status} error={type(exc).__name__}")
            time.sleep(delay)
    raise RuntimeError(f"upload failed: {last_error}")


def record_for(sample_builder, row: dict) -> dict:
    sample = sample_builder(title=str(row["title"]), section=str(row["section"]), text=row["text"] or "")
    formulas = list(sample.modal_ir.formulas)
    return {
        "schema_version": SCHEMA,
        "source_span_id": row["source_span_id"],
        "source_sha256": row["source_sha256"],
        "legal_id": row["legal_id"],
        "title": str(row["title"]),
        "section": str(row["section"]),
        "status": row["status"],
        "reason": row["reason"],
        "text": row["text"],
        "parser": "legal_modal_parser_v1",
        "formula_count": len(formulas),
        "logic_lines": [logic_line(formula) for formula in formulas],
        "selected_frame": sample.selected_frame,
        "frame_candidates": sample.frame_candidates,
        "modal_ir": sample.modal_ir.to_dict(),
        "admitted": False,
        "qualified": False,
        "formalized": False,
    }


def main() -> None:
    worker, workers = worker_id()
    OUT.mkdir(parents=True, exist_ok=True)
    PARTS.mkdir(parents=True, exist_ok=True)
    Path(f"/tmp/modal-ir-w{worker}.pid").write_text(str(os.getpid()) + "\n")
    table = pq.read_table(RESOLVED)
    total = table.num_rows
    owned_index = list(range(worker, total, workers))
    rows = table.take(owned_index).to_pylist()
    del table
    cursor = read_cursor(worker)
    start = int(cursor["next_offset"])
    log(f"ready worker={worker} owned={len(rows)} resume={start}")
    parser_holder = {}

    def sample_builder(*, title: str, section: str, text: str):
        if "parser" not in parser_holder:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import LegalModalParser

            parser_holder["parser"] = LegalModalParser()
            parser_holder["selector"] = BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)
        return build_us_code_sample(
            title=title,
            section=section,
            text=text,
            parser=parser_holder["parser"],
            frame_selector=parser_holder["selector"],
        )

    api = HfApi()
    if worker == 0 and start == 0:
        schema = {
            "schema_version": SCHEMA,
            "repository_id": REPO,
            "revision": REVISION,
            "remote_prefix": REMOTE_PREFIX,
            "parser": "legal_modal_parser_v1",
            "frame_selector": "bm25_v1",
            "recovered_from": "resolved span text that the CUDA scorer parsed and did not save",
            "joins_on": "source_span_id",
            "score_branch": "legacy-dense-v1-cuda-span-scores",
            "admitted": False,
            "qualified": False,
            "formalized": False,
        }
        schema_path = OUT / "schema.json"
        schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        publish_file(api, schema_path, "schema.json")
        log("schema.json ready")

    batch = []
    batch_first = None
    started = time.perf_counter()
    for local_offset in range(start, len(rows)):
        global_index = owned_index[local_offset]
        row = rows[local_offset]
        try:
            item = record_for(sample_builder, row)
            cursor["formula_count"] += item["formula_count"]
        except Exception as exc:
            item = {
                "schema_version": SCHEMA,
                "source_span_id": row.get("source_span_id"),
                "source_sha256": row.get("source_sha256"),
                "legal_id": row.get("legal_id"),
                "status": row.get("status"),
                "error": f"{type(exc).__name__}: {exc}",
                "formula_count": 0,
                "logic_lines": [],
                "admitted": False,
                "qualified": False,
                "formalized": False,
            }
            cursor["errors"] += 1
        if batch_first is None:
            batch_first = global_index
        batch.append(item)
        cursor["parsed"] += 1
        if cursor["parsed"] % 500 == 0:
            elapsed = time.perf_counter() - started
            log(
                f"progress worker={worker} parsed={cursor['parsed']} "
                f"offset={local_offset + 1}/{len(rows)} formulas={cursor['formula_count']} "
                f"errors={cursor['errors']} elapsed_s={elapsed:.1f}"
            )
        if cursor["errors"] > 20 and cursor["parsed"] <= 100:
            raise SystemExit(f"worker {worker} error threshold")
        if len(batch) < SHARD_ROWS and local_offset + 1 != len(rows):
            continue
        part_name = f"part-w{worker}-{batch_first:07d}.jsonl"
        part_path = PARTS / part_name
        part_path.write_text("".join(json.dumps(item, ensure_ascii=True, sort_keys=True) + "\n" for item in batch))
        publish_file(api, part_path, f"parts/{part_name}")
        cursor["uploaded_shards"].append(part_name)
        cursor["next_offset"] = local_offset + 1
        write_cursor(worker, cursor)
        manifest = {
            "schema_version": "uscode-modal-ir-manifest/v1",
            "repository_id": REPO,
            "revision": REVISION,
            "worker": worker,
            "workers": workers,
            "parser": "legal_modal_parser_v1",
            "owned_rows": len(rows),
            "parsed": cursor["parsed"],
            "formula_count": cursor["formula_count"],
            "errors": cursor["errors"],
            "next_offset": cursor["next_offset"],
            "uploaded_shards": cursor["uploaded_shards"],
            "admitted": False,
            "qualified": False,
            "formalized": False,
        }
        manifest_path = OUT / f"manifest-w{worker}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        publish_file(api, manifest_path, manifest_path.name)
        log(f"saved {part_name} offset={cursor['next_offset']}/{len(rows)} formulas={cursor['formula_count']}")
        batch = []
        batch_first = None
    log(f"EXIT:0 complete worker={worker} parsed={cursor['parsed']} formulas={cursor['formula_count']} errors={cursor['errors']}")


if __name__ == "__main__":
    main()
