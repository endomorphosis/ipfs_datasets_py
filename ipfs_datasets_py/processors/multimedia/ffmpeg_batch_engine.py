"""
Canonical FFmpeg batch processing engine.

Provides ffmpeg_batch_process and get_batch_status for parallel multi-file
FFmpeg operations with checkpoint/resume support.

MCP tool wrapper: ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_batch
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import anyio

from .ffmpeg_info_engine import _validate_input_file

logger = logging.getLogger(__name__)


async def ffmpeg_batch_process(
    input_files: Union[List[str], Dict[str, Any]],
    output_directory: str,
    operation: str = "convert",
    operation_params: Optional[Dict[str, Any]] = None,
    max_parallel: int = 2,
    save_progress: bool = True,
    resume_from_checkpoint: bool = True,
    timeout_per_file: int = 600,
) -> Dict[str, Any]:
    """Process multiple media files in batch using FFmpeg operations.

    Supports parallel processing, progress tracking, checkpoint/resume,
    and the same operations as the individual FFmpeg tool wrappers.

    Args:
        input_files: List of input file paths or a dataset dict with a
            ``files``, ``file_paths``, or ``data`` key.
        output_directory: Directory where processed files will be saved.
        operation: One of ``"convert"``, ``"filter"``, or ``"extract_audio"``.
        operation_params: Extra keyword args forwarded to the sub-operation.
        max_parallel: Maximum concurrent ffmpeg processes.
        save_progress: Persist progress to a checkpoint JSON file.
        resume_from_checkpoint: Skip already-processed files on restart.
        timeout_per_file: Per-file timeout in seconds.

    Returns:
        Dict with status, counts, results list, and checkpoint path.
    """
    start_time = time.time()

    # --- normalise input --------------------------------------------------
    if isinstance(input_files, dict):
        file_list: List[str] = (
            input_files.get("files")
            or input_files.get("file_paths")
            or (input_files.get("data") if isinstance(input_files.get("data"), list) else None)
            or []
        )
        if not file_list:
            return {
                "status": "error",
                "error": "Input dataset must contain 'files', 'file_paths', or 'data' field",
            }
    else:
        file_list = list(input_files)

    if not file_list:
        return {"status": "error", "error": "Input must be a non-empty list of file paths"}

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    if operation_params is None:
        operation_params = {}

    checkpoint_file = output_path / f"batch_progress_{int(start_time)}.json"

    # --- resume logic -----------------------------------------------------
    processed_set: set = set()
    if resume_from_checkpoint and save_progress:
        checkpoints = sorted(output_path.glob("batch_progress_*.json"), key=lambda p: p.stat().st_mtime)
        if checkpoints:
            try:
                with open(checkpoints[-1]) as fh:
                    data = json.load(fh)
                processed_set = set(data.get("processed_files", []))
                logger.info("Resuming: %d files already done", len(processed_set))
            except Exception as exc:
                logger.warning("Could not load checkpoint: %s", exc)

    files_to_process = [f for f in file_list if f not in processed_set]
    skipped_count = len(processed_set)

    # --- per-file worker --------------------------------------------------
    async def process_single(file_path: str) -> Dict[str, Any]:
        if not _validate_input_file(file_path):
            return {
                "status": "error",
                "input_file": file_path,
                "error": f"File not found: {file_path}",
            }
        in_path = Path(file_path)
        out_file = str(output_path / f"{in_path.stem}_processed{in_path.suffix}")
        try:
            if operation == "convert":
                from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
                w = FFmpegWrapper(enable_logging=False)
                result = await w.convert_video(
                    input_path=file_path, output_path=out_file,
                    timeout=timeout_per_file, **operation_params
                )
            elif operation == "filter":
                from .ffmpeg_filters_engine import ffmpeg_apply_filters
                result = await ffmpeg_apply_filters(
                    input_file=file_path, output_file=out_file,
                    timeout=timeout_per_file, **operation_params
                )
            elif operation == "extract_audio":
                audio_codec = operation_params.get("audio_codec", "mp3")
                audio_out = str(output_path / f"{in_path.stem}.{audio_codec}")
                from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
                w = FFmpegWrapper(enable_logging=False)
                result = await w.extract_audio(
                    input_path=file_path, output_path=audio_out,
                    timeout=timeout_per_file, **operation_params
                )
            else:
                result = {"status": "error", "error": f"Unsupported operation: {operation}"}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        result["input_file"] = file_path
        return result

    # --- bounded parallel execution --------------------------------------
    semaphore = anyio.Semaphore(max_parallel)
    results: List[Dict[str, Any]] = []
    processed_count = skipped_count
    failed_count = 0

    async def bounded(fp: str) -> Dict[str, Any]:
        async with semaphore:
            return await process_single(fp)

    n_tasks = len(files_to_process)
    send_s, recv_s = anyio.create_memory_object_stream(max(1, n_tasks))
    async with send_s, recv_s:
        async with anyio.create_task_group() as tg:
            for fp in files_to_process:
                async def _worker(fp=fp):
                    res = await bounded(fp)
                    await send_s.send(res)
                tg.start_soon(_worker)

            # Receive all results inside the task group so the stream
            # stays open while workers are still running.
            for _ in range(n_tasks):
                res = await recv_s.receive()
                results.append(res)
                if res["status"] == "success":
                    processed_count += 1
                    processed_set.add(res["input_file"])
                else:
                    failed_count += 1

                # periodic checkpoint
                if save_progress and len(results) % 10 == 0:
                    _save_checkpoint(
                        checkpoint_file, file_list, processed_set, operation, operation_params
                    )

    total_duration = time.time() - start_time
    if save_progress:
        _save_checkpoint(checkpoint_file, file_list, processed_set, operation, operation_params, completed=True)

    status = "success" if failed_count == 0 else ("partial" if processed_count > skipped_count else "error")
    return {
        "status": status,
        "total_files": len(file_list),
        "processed_files": processed_count,
        "failed_files": failed_count,
        "skipped_files": skipped_count,
        "results": results,
        "duration": total_duration,
        "average_time_per_file": total_duration / len(files_to_process) if files_to_process else 0,
        "checkpoint_file": str(checkpoint_file) if save_progress else None,
        "operation": operation,
        "message": f"Batch done: {processed_count} success, {failed_count} failed",
    }


def _save_checkpoint(
    path: Path,
    all_files: List[str],
    done: set,
    operation: str,
    params: Dict,
    completed: bool = False,
) -> None:
    try:
        with open(path, "w") as fh:
            json.dump({
                "total_files": len(all_files),
                "processed_files": list(done),
                "operation": operation,
                "operation_params": params,
                "timestamp": time.time(),
                "completed": completed,
            }, fh, indent=2)
    except Exception as exc:
        logger.warning("Could not save checkpoint: %s", exc)


async def get_batch_status(checkpoint_file: str) -> Dict[str, Any]:
    """Get the status of a batch processing job from its checkpoint file."""
    cp = Path(checkpoint_file)
    if not cp.exists():
        return {"status": "error", "error": f"Checkpoint file not found: {checkpoint_file}"}
    try:
        with open(cp) as fh:
            data = json.load(fh)
        done = len(data.get("processed_files", []))
        total = data.get("total_files", 0)
        return {
            "status": "success",
            "checkpoint_file": checkpoint_file,
            "total_files": total,
            "processed_files": done,
            "remaining_files": total - done,
            "progress_percentage": done / total * 100 if total else 0,
            "operation": data.get("operation", "unknown"),
            "timestamp": data.get("timestamp", 0),
            "completed": data.get("completed", False),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "checkpoint_file": checkpoint_file}
