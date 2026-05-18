"""Guarded U.S. Code modal TODO daemon runner.

This module owns the production runner used by the optimizer experiments.  It
keeps validation clean by ignoring sample-specific memorization, rolling back
failed validation updates through ``ModalTodoSupervisor``, and avoiding
validation rows that already have sample-memory entries in the current state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
)
from ipfs_datasets_py.optimizers.agentic.patch_control import PatchManager, WorktreeManager
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalOptimizerPolicy,
    ModalTodo,
    ModalTodoQueue,
    ModalTodoSupervisor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
    HF_USCODE_DATASET_ID,
    USCODE_LAWS_PARQUET,
    USCodeParquetRecord,
)

LAW_COLUMNS = [
    "ipfs_cid",
    "title_number",
    "title_name",
    "section_number",
    "law_name",
    "source_url",
    "text",
    "citation_text",
    "normalized_citation",
]


CODEX_TARGET_FILE_HINTS = {
    "modal.compiler": [
        "ipfs_datasets_py/logic/modal/compiler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_modal_parser.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
    ],
    "modal.compiler.ambiguity": [
        "ipfs_datasets_py/logic/modal/compiler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
    ],
    "modal.compiler.registry": [
        "ipfs_datasets_py/logic/modal/compiler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
    ],
    "modal.frame_logic": [
        "ipfs_datasets_py/logic/modal/codec.py",
        "ipfs_datasets_py/optimizers/logic/flogic_optimizer.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py",
    ],
    "modal.ir_decompiler": [
        "ipfs_datasets_py/logic/modal/codec.py",
        "ipfs_datasets_py/logic/modal/decompiler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
    ],
}

CODEX_ACTION_FILE_HINTS = {
    "add_deterministic_parser_rule": [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_modal_parser.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
        "ipfs_datasets_py/logic/modal/compiler.py",
    ],
    "increase_modal_ir_span_coverage": [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
        "ipfs_datasets_py/logic/modal/compiler.py",
    ],
    "refine_semantic_decompiler_reconstruction": [
        "ipfs_datasets_py/logic/modal/decompiler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
    ],
}

CODEX_SANDBOX_FALLBACK = "danger-full-access"
CODEX_SANDBOX_BLOCKER_PATTERNS = (
    "blocked by the execution sandbox",
    "bwrap: loopback: failed rtm_newaddr",
    "operation not permitted",
)
CODEX_COMPLETED_WORK_STATUSES = {"created", "applied_to_main"}
CODEX_APPLY_VALIDATION_TESTS = (
    "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
    "tests/unit_tests/logic/modal/test_modal_codec.py",
)
CODEX_WORKTREE_ARTIFACT_FILENAMES = {"changes.patch"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def load_laws_table():
    fs = HfFileSystem()
    path = f"datasets/{HF_USCODE_DATASET_ID}/{USCODE_LAWS_PARQUET}"
    with fs.open(path, "rb") as laws_file:
        return pq.ParquetFile(laws_file).read(columns=LAW_COLUMNS)


@contextmanager
def queue_file_lock(queue_path: Path) -> Iterator[None]:
    """Serialize async autoencoder/Codex writes to the shared JSONL queue."""
    import fcntl

    lock_path = queue_path.with_suffix(queue_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def row_to_sample(row: Mapping[str, Any]):
    return USCodeParquetRecord.from_row(row).to_sample()


def sample_train_validation_rows(
    laws_table,
    rng: random.Random,
    *,
    train_count: int,
    validation_count: int,
    blocked_validation_sample_ids: set[str],
):
    train_indices = rng.sample(range(laws_table.num_rows), train_count)
    train_rows = laws_table.take(train_indices).to_pylist()
    train_samples = [row_to_sample(row) for row in train_rows]
    selected_indices = set(train_indices)
    validation_indices = []
    validation_samples = []
    attempts = 0
    max_attempts = max(1000, validation_count * 100)
    while len(validation_samples) < validation_count and attempts < max_attempts:
        attempts += 1
        index = rng.randrange(laws_table.num_rows)
        if index in selected_indices:
            continue
        sample = row_to_sample(laws_table.take([index]).to_pylist()[0])
        if sample.sample_id in blocked_validation_sample_ids:
            continue
        selected_indices.add(index)
        validation_indices.append(index)
        validation_samples.append(sample)
    if len(validation_samples) < validation_count:
        raise RuntimeError(
            "Unable to sample enough validation rows without prior sample-memory exposure"
        )
    return train_indices, train_samples, validation_indices, validation_samples, attempts


def metric_block(evaluation) -> Dict[str, Any]:
    return {
        "cosine_loss": round(evaluation.cosine_loss, 9),
        "cosine_similarity": round(evaluation.embedding_cosine_similarity, 9),
        "cross_entropy_loss": round(evaluation.cross_entropy_loss, 9),
        "reconstruction_loss": round(evaluation.reconstruction_loss, 9),
        "sample_count": evaluation.sample_count,
        "symbolic_validity_penalty": round(evaluation.symbolic_validity_penalty, 9),
    }


def compiler_ir_metric_block(
    samples: Sequence[Any],
    codec: DeterministicModalLogicCodec,
) -> Dict[str, Any]:
    """Aggregate deterministic compiler/IR/decompiler round-trip metrics."""
    sample_list = list(samples)
    if not sample_list:
        return {
            "evaluated_count": 0,
            "metric_failures": 0,
            "sample_count": 0,
        }

    losses: Dict[str, List[float]] = {
        "cosine_loss": [],
        "cosine_similarity": [],
        "cross_entropy_loss": [],
        "flogic_similarity_loss": [],
        "flogic_similarity_score": [],
        "frame_ranking_loss": [],
        "modal_span_coverage_loss": [],
        "ontology_violation_count": [],
        "reconstruction_loss": [],
        "symbolic_validity_penalty": [],
        "text_reconstruction_loss": [],
    }
    formula_counts: List[float] = []
    frame_candidate_counts: List[float] = []
    llm_call_counts: List[float] = []
    failures = 0
    for sample in sample_list:
        try:
            result = codec.encode(
                sample.text,
                document_id=sample.sample_id,
                citation=sample.citation,
                source=sample.source,
                source_embedding=sample.embedding_vector,
            )
        except Exception:
            failures += 1
            continue
        for name in losses:
            value = result.losses.get(name)
            if value is not None:
                losses[name].append(float(value))
        formula_counts.append(float(len(result.modal_ir.formulas)))
        frame_candidate_counts.append(float(len(result.frame_candidates)))
        llm_call_counts.append(float(result.metadata.get("llm_call_count", 0.0)))

    block: Dict[str, Any] = {
        "evaluated_count": len(formula_counts),
        "metric_failures": failures,
        "sample_count": len(sample_list),
    }
    for name, values in losses.items():
        if values:
            block[name] = round(sum(values) / len(values), 9)
    if formula_counts:
        block["formula_count"] = round(sum(formula_counts) / len(formula_counts), 9)
        block["frame_candidate_count"] = round(
            sum(frame_candidate_counts) / len(frame_candidate_counts),
            9,
        )
        block["llm_call_count"] = round(sum(llm_call_counts) / len(llm_call_counts), 9)
    if "modal_span_coverage_loss" in block:
        block["modal_span_coverage"] = round(
            1.0 - float(block["modal_span_coverage_loss"]),
            9,
        )
    if "text_reconstruction_loss" in block:
        block["text_reconstruction_similarity"] = round(
            1.0 - float(block["text_reconstruction_loss"]),
            9,
        )
    return block


def program_synthesis_status_block(
    queue: ModalTodoQueue,
    policy: ModalOptimizerPolicy,
    *,
    execution_mode: str = "queued_for_external_codex_worker",
) -> Dict[str, Any]:
    """Report program-synthesis queue status using the shared supervisor logic."""
    supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
    return supervisor.program_synthesis_status(execution_mode=execution_mode)


def update_program_synthesis_summary(
    summary: Dict[str, Any],
    queue: ModalTodoQueue,
    policy: ModalOptimizerPolicy,
    *,
    execution_mode: Optional[str] = None,
) -> Dict[str, Any]:
    supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
    return supervisor.update_program_synthesis_summary(
        summary,
        execution_mode=execution_mode or "queued_for_external_codex_worker",
    )


def codex_loop_execution_mode(args: argparse.Namespace) -> str:
    if getattr(args, "codex_exec_mode", "packet_only") == "codex_cli":
        return "codex_cli_executor"
    return "queued_for_external_codex_worker"


def build_paired_daemon_commands(
    args: argparse.Namespace,
    *,
    module_name: str,
) -> Dict[str, Any]:
    """Build child process commands for paired autoencoder/codex execution."""
    autoencoder_run_id = getattr(args, "autoencoder_run_id", None) or f"{args.run_id}-autoencoder"
    codex_run_id = getattr(args, "codex_run_id", None) or f"{args.run_id}-codex"
    queue_run_id = autoencoder_run_id
    codex_duration_seconds = float(args.duration_seconds) + max(
        0.0,
        float(getattr(args, "paired_grace_seconds", 0.0)),
    )
    autoencoder_command = [
        sys.executable,
        "-m",
        module_name,
        "--loop-role",
        "autoencoder",
        "--run-id",
        autoencoder_run_id,
        "--duration-seconds",
        str(args.duration_seconds),
        "--train-count",
        str(args.train_count),
        "--validation-count",
        str(args.validation_count),
        "--max-inner-iterations",
        str(args.max_inner_iterations),
        "--max-items",
        str(args.max_items),
        "--learning-rate",
        str(args.learning_rate),
        "--test-every-cycles",
        str(args.test_every_cycles),
    ]
    for warm_start_run_id in getattr(args, "warm_start_run_id", []):
        autoencoder_command.extend(["--warm-start-run-id", str(warm_start_run_id)])
    for warm_start_state in getattr(args, "warm_start_state", []):
        autoencoder_command.extend(["--warm-start-state", str(warm_start_state)])

    codex_command = [
        sys.executable,
        "-m",
        module_name,
        "--loop-role",
        "codex",
        "--run-id",
        codex_run_id,
        "--queue-run-id",
        queue_run_id,
        "--duration-seconds",
        str(codex_duration_seconds),
        "--max-items",
        str(args.max_items),
        "--poll-seconds",
        str(args.poll_seconds),
        "--codex-exec-mode",
        str(args.codex_exec_mode),
        "--codex-command",
        str(args.codex_command),
        "--codex-sandbox",
        str(args.codex_sandbox),
        "--codex-timeout-seconds",
        str(args.codex_timeout_seconds),
        "--codex-apply-mode",
        str(getattr(args, "codex_apply_mode", "patch_only")),
        "--codex-commit-mode",
        str(getattr(args, "codex_commit_mode", "none")),
    ]
    if getattr(args, "codex_scope", None):
        codex_command.extend(["--codex-scope", str(args.codex_scope)])
    if getattr(args, "worker_id", None):
        codex_command.extend(["--worker-id", str(args.worker_id)])
    if getattr(args, "codex_model", None):
        codex_command.extend(["--codex-model", str(args.codex_model)])

    return {
        "autoencoder_run_id": autoencoder_run_id,
        "codex_run_id": codex_run_id,
        "queue_run_id": queue_run_id,
        "autoencoder_command": autoencoder_command,
        "codex_command": codex_command,
    }


def create_codex_work_packet(
    *,
    cycle: int,
    queue_path: Path,
    queue_run_id: str,
    repo_root: Path,
    run_id: str,
    todos: Sequence[ModalTodo],
    work_dir: Path,
    worker_id: str,
) -> Dict[str, Any]:
    """Create an isolated worktree-backed Codex packet for claimed TODOs."""
    packet_id = f"packet-{cycle:06d}"
    packet_dir = work_dir / packet_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    suggested_files = _suggested_target_files(todos)
    program_synthesis_scopes = sorted(
        {
            str(todo.metadata.get("program_synthesis_scope") or "")
            for todo in todos
            if todo.metadata.get("program_synthesis_scope")
        }
    )
    todo_list_path = packet_dir / "TODO_LIST.jsonl"
    todo_markdown_path = packet_dir / "TODO_LIST.md"
    todo_list_path.write_text(
        "\n".join(todo.to_json() for todo in todos) + "\n",
        encoding="utf-8",
    )
    todo_markdown_path.write_text(
        _todo_list_markdown(todos=todos, queue_path=queue_path, queue_run_id=queue_run_id),
        encoding="utf-8",
    )

    worktree_path: Optional[Path] = None
    worktree_error: Optional[str] = None
    patch_path: Optional[Path] = None
    patch_status = "worktree_unavailable"
    patch_error: Optional[str] = None
    agent_id = _safe_artifact_name(f"{worker_id}-{packet_id}")
    source_repo_root = resolve_codex_worktree_repo_root(repo_root)

    try:
        worktree_manager = WorktreeManager(
            repo_path=source_repo_root,
            worktrees_base=work_dir / "worktrees",
        )
        worktree_path = worktree_manager.create_worktree(agent_id, branch="HEAD")
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        worktree_error = str(exc)

    if worktree_path is not None:
        try:
            patch_manager = PatchManager(patches_dir=packet_dir / "patches")
            patch = patch_manager.create_patch(
                agent_id=worker_id,
                task_id=packet_id,
                worktree_path=worktree_path,
                description=_packet_description(todos),
            )
            patch_path = patch_manager.save_patch(
                patch,
                packet_dir / "patches" / f"{packet_id}.patch",
            )
            patch_status = "created"
        except ValueError as exc:
            patch_status = "awaiting_codex_changes"
            patch_error = str(exc)
        except (OSError, RuntimeError, subprocess.SubprocessError, TypeError) as exc:
            patch_status = "patch_generation_failed"
            patch_error = str(exc)

    task_markdown = _codex_task_markdown(
        packet_id=packet_id,
        patch_path=patch_path,
        patch_status=patch_status,
        suggested_files=suggested_files,
        todo_list_path=todo_list_path,
        todo_markdown_path=todo_markdown_path,
        todos=todos,
        worktree_path=worktree_path,
    )
    task_path = packet_dir / "CODEX_TASK.md"
    task_path.write_text(task_markdown, encoding="utf-8")

    packet = {
        "claimed_at": utc_now(),
        "packet_id": packet_id,
        "patch_error": patch_error,
        "patch_path": str(patch_path) if patch_path is not None else None,
        "patch_status": patch_status,
        "queue_path": str(queue_path),
        "queue_run_id": queue_run_id,
        "repo_root": str(repo_root),
        "run_id": run_id,
        "program_synthesis_scopes": program_synthesis_scopes,
        "suggested_target_files": suggested_files,
        "source_repo_root": str(source_repo_root),
        "task_source": "autoencoder_supervisor_program_synthesis_queue",
        "task_path": str(task_path),
        "todo_list_path": str(todo_list_path),
        "todo_markdown_path": str(todo_markdown_path),
        "todos": [todo.to_dict() for todo in todos],
        "worker_id": worker_id,
        "worktree_error": worktree_error,
        "worktree_path": str(worktree_path) if worktree_path is not None else None,
    }
    packet_path = packet_dir / "packet.json"
    packet_path.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    packet["packet_path"] = str(packet_path)
    return packet


def refresh_codex_work_packet_patch(packet: Mapping[str, Any]) -> Dict[str, Any]:
    """Generate or refresh the patch file for a packet worktree."""
    updated = dict(packet)
    packet_path_value = updated.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    packet_dir = packet_path.parent if packet_path is not None else Path(".")
    worktree_value = updated.get("worktree_path")
    if not worktree_value:
        updated["patch_status"] = "worktree_unavailable"
        updated["patch_error"] = "packet has no worktree_path"
        _save_packet_if_possible(updated, packet_path)
        return updated

    patch_path: Optional[Path] = None
    patch_status = "patch_generation_failed"
    patch_error: Optional[str] = None
    try:
        patch_manager = PatchManager(patches_dir=packet_dir / "patches")
        patch = patch_manager.create_patch(
            agent_id=str(updated.get("worker_id") or "codex-worker"),
            task_id=str(updated.get("packet_id") or packet_dir.name),
            worktree_path=Path(str(worktree_value)),
            description=str(_packet_description_from_dict(updated)),
        )
        patch_path = patch_manager.save_patch(
            patch,
            packet_dir / "patches" / f"{updated.get('packet_id', packet_dir.name)}.patch",
        )
        patch_status = "created"
    except ValueError as exc:
        patch_status = "awaiting_codex_changes"
        patch_error = str(exc)
    except (OSError, RuntimeError, subprocess.SubprocessError, TypeError) as exc:
        patch_error = str(exc)

    updated["patch_error"] = patch_error
    updated["patch_path"] = str(patch_path) if patch_path is not None else None
    updated["patch_status"] = patch_status
    _save_packet_if_possible(updated, packet_path)
    return updated


def _save_codex_packet_diff_patch(
    packet: Mapping[str, Any],
    *,
    diff_content: str,
    reason: str,
) -> Optional[Path]:
    """Persist a worktree diff when direct application needs human inspection."""
    packet_path_value = packet.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    packet_dir = packet_path.parent if packet_path is not None else Path(".")
    packet_id = str(packet.get("packet_id") or packet_dir.name)
    patch_dir = packet_dir / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_path = patch_dir / f"{packet_id}.{reason}.patch"
    patch_path.write_text(diff_content, encoding="utf-8")
    return patch_path


def _is_codex_worktree_artifact(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    name = Path(normalized).name
    return name in CODEX_WORKTREE_ARTIFACT_FILENAMES or name.endswith(".patch")


def _codex_worktree_diff(worktree_path: Path) -> Dict[str, Any]:
    """Return a binary-safe git diff and target file list for a packet worktree."""
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    untracked.check_returncode()
    untracked_paths = [path for path in untracked.stdout.split("\0") if path]
    untracked_diff_paths = [
        path for path in untracked_paths if not _is_codex_worktree_artifact(path)
    ]
    if untracked_diff_paths:
        subprocess.run(
            ["git", "add", "-N", "--", *untracked_diff_paths],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=30.0,
            check=True,
        )

    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    diff.check_returncode()
    names = subprocess.run(
        ["git", "diff", "--name-only", "-z", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    names.check_returncode()
    target_files = [
        path
        for path in names.stdout.split("\0")
        if path and not _is_codex_worktree_artifact(path)
    ]
    if target_files:
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--", *target_files],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        diff.check_returncode()
    else:
        diff = subprocess.CompletedProcess(
            ["git", "diff", "--binary", "HEAD"],
            0,
            stdout="",
            stderr="",
        )
    return {
        "diff_content": diff.stdout,
        "target_files": target_files,
        "untracked_paths": untracked_diff_paths,
        "ignored_artifact_paths": [
            path for path in untracked_paths if _is_codex_worktree_artifact(path)
        ],
    }


def _dirty_target_files(repo_root: Path, target_files: Sequence[str]) -> List[str]:
    """Return target files that already have local edits in the destination checkout."""
    if not target_files:
        return []
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *target_files],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    result.check_returncode()
    dirty: List[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            dirty.append(path)
    return dirty


def _run_git_apply_stdin(
    repo_root: Path,
    diff_content: str,
    *args: str,
    timeout_seconds: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "apply", *args, "-"],
        cwd=repo_root,
        input=diff_content,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout_seconds)),
    )


def _default_codex_apply_validation_commands(repo_root: Path) -> List[List[str]]:
    tests = [path for path in CODEX_APPLY_VALIDATION_TESTS if (repo_root / path).exists()]
    if not tests:
        return []
    return [[sys.executable, "-m", "pytest", "-q", *tests]]


def _run_codex_apply_validation(
    repo_root: Path,
    packet_dir: Path,
    *,
    validation_commands: Optional[Sequence[Sequence[str]]] = None,
    timeout_seconds: float = 300.0,
) -> Dict[str, Any]:
    commands = (
        [list(command) for command in validation_commands]
        if validation_commands is not None
        else _default_codex_apply_validation_commands(repo_root)
    )
    if not commands:
        return {"commands": [], "status": "skipped"}

    results: List[Dict[str, Any]] = []
    for index, command in enumerate(commands, start=1):
        stdout_path = packet_dir / f"main-apply-validation-{index}.stdout.log"
        stderr_path = packet_dir / f"main-apply-validation-{index}.stderr.log"
        started = time.time()
        try:
            result = subprocess.run(
                command,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_seconds)),
            )
            stdout_path.write_text(result.stdout or "", encoding="utf-8")
            stderr_path.write_text(result.stderr or "", encoding="utf-8")
            command_result = {
                "command": command,
                "duration_seconds": round(time.time() - started, 3),
                "exit_code": result.returncode,
                "status": "passed" if result.returncode == 0 else "failed",
                "stderr_path": str(stderr_path),
                "stdout_path": str(stdout_path),
            }
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(_process_text(exc.stdout), encoding="utf-8")
            stderr_path.write_text(_process_text(exc.stderr), encoding="utf-8")
            command_result = {
                "command": command,
                "duration_seconds": round(time.time() - started, 3),
                "exit_code": None,
                "status": "timeout",
                "stderr_path": str(stderr_path),
                "stdout_path": str(stdout_path),
                "timeout_seconds": float(timeout_seconds),
            }
        results.append(command_result)
        if command_result["status"] != "passed":
            return {"commands": results, "status": command_result["status"]}
    return {"commands": results, "status": "passed"}


def _commit_codex_main_changes(
    repo_root: Path,
    *,
    packet: Mapping[str, Any],
    target_files: Sequence[str],
) -> Dict[str, Any]:
    if not target_files:
        return {"status": "skipped", "reason": "no_target_files"}
    add = subprocess.run(
        ["git", "add", "--", *target_files],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    if add.returncode != 0:
        return {
            "status": "failed",
            "step": "add",
            "exit_code": add.returncode,
            "stderr_tail": (add.stderr or "")[-500:],
            "stdout_tail": (add.stdout or "")[-500:],
        }

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *target_files],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    if diff.returncode == 0:
        return {"status": "skipped", "reason": "no_staged_changes"}

    packet_id = str(packet.get("packet_id") or "codex-packet")
    todo_ids = [
        str(todo.get("todo_id"))
        for todo in packet.get("todos", [])
        if isinstance(todo, Mapping) and todo.get("todo_id")
    ]
    message = f"Apply Codex legal IR packet {packet_id}"
    body_lines = [
        "Auto-applied from the legal IR autoencoder/Codex daemon.",
        f"Packet: {packet_id}",
    ]
    if todo_ids:
        body_lines.append("TODOs: " + ", ".join(todo_ids[:8]))
    commit = subprocess.run(
        ["git", "commit", "-m", message, "-m", "\n".join(body_lines), "--", *target_files],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120.0,
    )
    return {
        "status": "committed" if commit.returncode == 0 else "failed",
        "exit_code": commit.returncode,
        "stderr_tail": (commit.stderr or "")[-500:],
        "stdout_tail": (commit.stdout or "")[-500:],
    }


def apply_codex_worktree_changes_to_main(
    packet: Mapping[str, Any],
    *,
    commit_mode: str = "none",
    validation_commands: Optional[Sequence[Sequence[str]]] = None,
    validation_timeout_seconds: float = 300.0,
) -> Dict[str, Any]:
    """Apply a packet worktree diff to the source checkout and validate it."""
    updated = dict(packet)
    packet_path_value = updated.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    packet_dir = packet_path.parent if packet_path is not None else Path(".")
    worktree_value = updated.get("worktree_path")
    source_root_value = updated.get("source_repo_root") or updated.get("repo_root")

    updated["codex_apply_mode"] = "apply_to_main"
    updated["main_apply_status"] = "failed"
    if not worktree_value:
        updated["patch_status"] = "worktree_unavailable"
        updated["patch_error"] = "packet has no worktree_path"
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated
    if not source_root_value:
        updated["patch_status"] = "main_apply_missing_repo_root"
        updated["patch_error"] = "packet has no source_repo_root or repo_root"
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated

    worktree_path = Path(str(worktree_value))
    source_repo_root = Path(str(source_root_value)).resolve()
    updated["main_apply_target_repo_root"] = str(source_repo_root)

    try:
        diff_info = _codex_worktree_diff(worktree_path)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        updated["patch_status"] = "patch_generation_failed"
        updated["patch_error"] = str(exc)
        updated["main_apply_error"] = str(exc)
        _save_packet_if_possible(updated, packet_path)
        return updated

    diff_content = str(diff_info.get("diff_content") or "")
    target_files = [str(path) for path in diff_info.get("target_files", [])]
    updated["main_apply_target_files"] = target_files
    updated["main_apply_untracked_paths"] = [
        str(path) for path in diff_info.get("untracked_paths", [])
    ]
    updated["main_apply_ignored_artifact_paths"] = [
        str(path) for path in diff_info.get("ignored_artifact_paths", [])
    ]
    if not diff_content.strip():
        updated["patch_status"] = "awaiting_codex_changes"
        updated["patch_error"] = "No changes found in worktree"
        updated["patch_path"] = None
        updated["main_apply_status"] = "no_changes"
        _save_packet_if_possible(updated, packet_path)
        return updated

    try:
        dirty_files = _dirty_target_files(source_repo_root, target_files)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        dirty_files = []
        updated["main_apply_dirty_check_error"] = str(exc)
    if dirty_files:
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason="dirty-target",
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        updated["patch_status"] = "main_apply_dirty_target"
        updated["patch_error"] = "target checkout has local edits in Codex target files"
        updated["main_apply_dirty_files"] = dirty_files
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated

    check = _run_git_apply_stdin(source_repo_root, diff_content, "--check")
    updated["main_apply_check"] = {
        "exit_code": check.returncode,
        "stderr_tail": (check.stderr or "")[-500:],
        "stdout_tail": (check.stdout or "")[-500:],
    }
    if check.returncode != 0:
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason="apply-check-failed",
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        updated["patch_status"] = "main_apply_check_failed"
        updated["patch_error"] = check.stderr or check.stdout or "git apply --check failed"
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated

    apply_result = _run_git_apply_stdin(source_repo_root, diff_content)
    updated["main_apply_result"] = {
        "exit_code": apply_result.returncode,
        "stderr_tail": (apply_result.stderr or "")[-500:],
        "stdout_tail": (apply_result.stdout or "")[-500:],
    }
    if apply_result.returncode != 0:
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason="apply-failed",
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        updated["patch_status"] = "main_apply_failed"
        updated["patch_error"] = apply_result.stderr or apply_result.stdout or "git apply failed"
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated

    validation = _run_codex_apply_validation(
        source_repo_root,
        packet_dir,
        validation_commands=validation_commands,
        timeout_seconds=validation_timeout_seconds,
    )
    updated["main_apply_validation"] = validation
    if validation["status"] not in {"passed", "skipped"}:
        rollback = _run_git_apply_stdin(source_repo_root, diff_content, "-R")
        updated["main_apply_rollback"] = {
            "exit_code": rollback.returncode,
            "stderr_tail": (rollback.stderr or "")[-500:],
            "stdout_tail": (rollback.stdout or "")[-500:],
        }
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason="validation-failed",
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        updated["patch_status"] = (
            "main_apply_validation_failed_rolled_back"
            if rollback.returncode == 0
            else "main_apply_validation_failed_rollback_failed"
        )
        updated["patch_error"] = f"validation {validation['status']}"
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated

    if str(commit_mode).strip().lower() == "commit_applied":
        try:
            commit = _commit_codex_main_changes(
                source_repo_root,
                packet=updated,
                target_files=target_files,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            commit = {"status": "failed", "error": str(exc), "step": "commit"}
        updated["main_commit"] = commit
        if commit["status"] != "committed":
            subprocess.run(
                ["git", "reset", "--", *target_files],
                cwd=source_repo_root,
                capture_output=True,
                text=True,
                timeout=60.0,
            )
            rollback = _run_git_apply_stdin(source_repo_root, diff_content, "-R")
            updated["main_apply_rollback"] = {
                "exit_code": rollback.returncode,
                "stderr_tail": (rollback.stderr or "")[-500:],
                "stdout_tail": (rollback.stdout or "")[-500:],
            }
            patch_path = _save_codex_packet_diff_patch(
                updated,
                diff_content=diff_content,
                reason="commit-failed",
            )
            updated["patch_path"] = str(patch_path) if patch_path is not None else None
            updated["patch_status"] = (
                "main_apply_commit_failed_rolled_back"
                if rollback.returncode == 0
                else "main_apply_commit_failed_rollback_failed"
            )
            updated["patch_error"] = "commit failed"
            updated["main_apply_error"] = updated["patch_error"]
            _save_packet_if_possible(updated, packet_path)
            return updated

    updated["main_apply_status"] = "applied"
    updated["patch_error"] = None
    updated["patch_path"] = None
    updated["patch_status"] = "applied_to_main"
    _save_packet_if_possible(updated, packet_path)
    return updated


def execute_codex_work_packet(
    packet: Mapping[str, Any],
    *,
    apply_mode: str = "patch_only",
    commit_mode: str = "none",
    codex_command: str = "codex",
    model: Optional[str] = None,
    sandbox: str = "workspace-write",
    timeout_seconds: float = 900.0,
    validation_commands: Optional[Sequence[Sequence[str]]] = None,
    validation_timeout_seconds: float = 300.0,
) -> Dict[str, Any]:
    """Run ``codex exec`` in the packet worktree and collect/apply its changes."""
    updated = dict(packet)
    packet_path_value = updated.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    packet_dir = packet_path.parent if packet_path is not None else Path(".")
    task_value = updated.get("task_path")
    worktree_value = updated.get("worktree_path")
    if not task_value or not worktree_value:
        updated["codex_exec"] = {
            "status": "skipped",
            "reason": "packet is missing task_path or worktree_path",
        }
        _save_packet_if_possible(updated, packet_path)
        return updated

    prompt_path = packet_dir / "CODEX_PROMPT.md"
    stdout_path = packet_dir / "codex-stdout.log"
    stderr_path = packet_dir / "codex-stderr.log"
    last_message_path = packet_dir / "codex-last-message.md"
    prompt = _codex_exec_prompt(updated)
    prompt_path.write_text(prompt, encoding="utf-8")

    exec_result = _run_codex_exec_attempt(
        codex_command=codex_command,
        model=model,
        prompt=prompt,
        prompt_path=prompt_path,
        sandbox=sandbox,
        stderr_path=stderr_path,
        stdout_path=stdout_path,
        timeout_seconds=timeout_seconds,
        worktree_path=Path(str(worktree_value)),
        last_message_path=last_message_path,
    )
    updated["codex_exec"] = exec_result
    _save_packet_if_possible(updated, packet_path)
    normalized_apply_mode = str(apply_mode).strip().lower()
    if normalized_apply_mode == "apply_to_main":
        refreshed = apply_codex_worktree_changes_to_main(
            updated,
            commit_mode=commit_mode,
            validation_commands=validation_commands,
            validation_timeout_seconds=validation_timeout_seconds,
        )
    else:
        refreshed = refresh_codex_work_packet_patch(updated)
    exec_result["attempt_count"] = 1

    if _should_retry_codex_exec_with_fallback(
        exec_result=exec_result,
        patch_status=str(refreshed.get("patch_status") or ""),
        requested_sandbox=sandbox,
    ):
        fallback_stdout_path = packet_dir / "codex-stdout-fallback.log"
        fallback_stderr_path = packet_dir / "codex-stderr-fallback.log"
        fallback_last_message_path = packet_dir / "codex-last-message-fallback.md"
        fallback_result = _run_codex_exec_attempt(
            codex_command=codex_command,
            model=model,
            prompt=prompt,
            prompt_path=prompt_path,
            sandbox=CODEX_SANDBOX_FALLBACK,
            stderr_path=fallback_stderr_path,
            stdout_path=fallback_stdout_path,
            timeout_seconds=float(timeout_seconds),
            worktree_path=Path(str(worktree_value)),
            last_message_path=fallback_last_message_path,
        )
        fallback_result["attempt_count"] = 2
        fallback_result["fallback_from_sandbox"] = sandbox
        fallback_result["fallback_reason"] = "sandbox_block_or_no_patch"
        refreshed["codex_exec"] = fallback_result
        _save_packet_if_possible(refreshed, packet_path)
        if normalized_apply_mode == "apply_to_main":
            refreshed = apply_codex_worktree_changes_to_main(
                refreshed,
                commit_mode=commit_mode,
                validation_commands=validation_commands,
                validation_timeout_seconds=validation_timeout_seconds,
            )
        else:
            refreshed = refresh_codex_work_packet_patch(refreshed)
    return refreshed


def _process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_codex_exec_attempt(
    *,
    codex_command: str,
    model: Optional[str],
    prompt: str,
    prompt_path: Path,
    sandbox: str,
    stderr_path: Path,
    stdout_path: Path,
    timeout_seconds: float,
    worktree_path: Path,
    last_message_path: Path,
) -> Dict[str, Any]:
    cmd = [
        codex_command,
        "exec",
        "--cd",
        str(worktree_path),
        "--sandbox",
        sandbox,
        "--output-last-message",
        str(last_message_path),
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append("-")

    started = time.time()
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=max(1.0, float(timeout_seconds)),
        )
        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")
        status = "succeeded" if result.returncode == 0 else "failed"
        return {
            "command": cmd,
            "duration_seconds": round(time.time() - started, 3),
            "exit_code": result.returncode,
            "last_message_path": str(last_message_path),
            "prompt_path": str(prompt_path),
            "sandbox": sandbox,
            "status": status,
            "stderr_path": str(stderr_path),
            "stdout_path": str(stdout_path),
        }
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_process_text(exc.stdout), encoding="utf-8")
        stderr_path.write_text(_process_text(exc.stderr), encoding="utf-8")
        return {
            "command": cmd,
            "duration_seconds": round(time.time() - started, 3),
            "exit_code": None,
            "last_message_path": str(last_message_path),
            "prompt_path": str(prompt_path),
            "sandbox": sandbox,
            "status": "timeout",
            "stderr_path": str(stderr_path),
            "stdout_path": str(stdout_path),
            "timeout_seconds": float(timeout_seconds),
        }


def _should_retry_codex_exec_with_fallback(
    *,
    exec_result: Mapping[str, Any],
    patch_status: str,
    requested_sandbox: str,
) -> bool:
    normalized_sandbox = str(requested_sandbox).strip().lower()
    if normalized_sandbox == CODEX_SANDBOX_FALLBACK:
        return False

    normalized_status = str(exec_result.get("status") or "").strip().lower()
    if normalized_status in {"failed", "timeout"}:
        return True

    if patch_status.strip().lower() in CODEX_COMPLETED_WORK_STATUSES:
        return False
    return _codex_exec_logs_indicate_sandbox_block(exec_result)


def _codex_exec_logs_indicate_sandbox_block(exec_result: Mapping[str, Any]) -> bool:
    text_chunks: List[str] = []
    for key in ("stderr_path", "last_message_path"):
        value = exec_result.get(key)
        if not value:
            continue
        path = Path(str(value))
        if not path.exists():
            continue
        try:
            text_chunks.append(path.read_text(encoding="utf-8", errors="replace").lower())
        except OSError:
            continue
    if not text_chunks:
        return False
    combined = "\n".join(text_chunks)
    return any(pattern in combined for pattern in CODEX_SANDBOX_BLOCKER_PATTERNS)


def _suggested_target_files(todos: Sequence[ModalTodo]) -> List[str]:
    files: List[str] = []
    for todo in todos:
        target_component = str(todo.metadata.get("target_component") or "")
        added_component_hint = False
        for file_path in CODEX_TARGET_FILE_HINTS.get(target_component, []):
            if file_path not in files:
                files.append(file_path)
                added_component_hint = True
        if not added_component_hint:
            for file_path in CODEX_ACTION_FILE_HINTS.get(todo.action, []):
                if file_path not in files:
                    files.append(file_path)
    return files


def _packet_description(todos: Sequence[ModalTodo]) -> str:
    actions = sorted({todo.action for todo in todos})
    return "Codex modal program synthesis: " + ", ".join(actions)


def _packet_description_from_dict(packet: Mapping[str, Any]) -> str:
    todos = [dict(todo) for todo in packet.get("todos", [])]
    actions = sorted(str(todo.get("action", "")) for todo in todos if todo.get("action"))
    if not actions:
        return "Codex modal program synthesis"
    return "Codex modal program synthesis: " + ", ".join(actions)


def _todo_list_markdown(
    *,
    todos: Sequence[ModalTodo],
    queue_path: Path,
    queue_run_id: str,
) -> str:
    lines = [
        "# Autoencoder TODO List",
        "",
        "These TODOs were generated from autoencoder introspection and claimed from the supervisor queue.",
        "",
        f"- Queue run: `{queue_run_id}`",
        f"- Queue path: `{queue_path}`",
        f"- TODO count: `{len(todos)}`",
        "",
        "## TODOs",
    ]
    for todo in todos:
        lines.extend(
            [
                f"- `{todo.todo_id}`",
                f"  action: `{todo.action}`",
                f"  role: `{todo.metadata.get('optimizer_role', '')}`",
                f"  target: `{todo.metadata.get('target_component', '')}`",
                f"  loss: `{todo.loss_name}` = `{todo.loss_value}`",
                f"  objective: {todo.objective}",
                f"  samples: `{', '.join(todo.sample_ids)}`",
            ]
        )
        for evidence in todo.metadata.get("hint_evidence", [])[:4]:
            lines.append(f"  evidence: `{json.dumps(evidence, sort_keys=True)}`")
    return "\n".join(lines) + "\n"


def _codex_task_markdown(
    *,
    packet_id: str,
    patch_path: Optional[Path],
    patch_status: str,
    suggested_files: Sequence[str],
    todo_list_path: Path,
    todo_markdown_path: Path,
    todos: Sequence[ModalTodo],
    worktree_path: Optional[Path],
) -> str:
    lines = [
        f"# {packet_id}",
        "",
        "## Source",
        "The TODO batch is autoencoder/supervisor output; this file is the Codex-facing work order.",
        f"- Raw TODO JSONL: `{todo_list_path}`",
        f"- TODO markdown: `{todo_markdown_path}`",
        "",
        "## Worktree",
        str(worktree_path) if worktree_path is not None else "unavailable",
        "",
        "## Change Capture",
        str(patch_path) if patch_path is not None else f"pending: {patch_status}",
        "",
        "## Suggested Files",
    ]
    lines.extend(f"- `{file_path}`" for file_path in suggested_files)
    if not suggested_files:
        lines.append("- No direct target file hint was available.")
    lines.extend(["", "## TODOs"])
    for todo in todos:
        lines.extend(
            [
                f"- `{todo.todo_id}` `{todo.action}`",
                f"  target: `{todo.metadata.get('target_component', '')}`",
                f"  objective: {todo.objective}",
                f"  support: {todo.metadata.get('support_count', '')}",
            ]
        )
        for evidence in todo.metadata.get("hint_evidence", [])[:4]:
            lines.append(f"  evidence: `{json.dumps(evidence, sort_keys=True)}`")
    lines.extend(
        [
            "",
            "## Finish",
            "Leave the completed edits in the worktree; the daemon captures, applies, and validates the diff.",
        ]
    )
    return "\n".join(lines) + "\n"


def _codex_exec_prompt(packet: Mapping[str, Any]) -> str:
    task_path = Path(str(packet["task_path"]))
    todo_markdown_path = Path(str(packet.get("todo_markdown_path") or task_path))
    sections = [
        task_path.read_text(encoding="utf-8") if task_path.exists() else "",
        "",
        "## Execution Instructions",
        "Work only inside the packet worktree.",
        "Your worktree edits may be applied back to the source checkout and validated automatically when this packet finishes.",
        "Do not create changes.patch or other patch artifact files; leave source and test edits directly in the worktree.",
        "Treat the packet's program_synthesis_scope metadata as the AST/write-scope boundary; keep edits inside that lane unless a test requires a small adjacent change.",
        "Implement a narrow deterministic parser, IR, decoder, or frame-logic improvement for the claimed TODOs.",
        "Prefer explainable compiler/decompiler code over learned weights when the TODO concerns modal or frame semantics.",
        "Use local repository files and tests only; do not use web search for this packet.",
        "Run the smallest relevant tests you can before finishing.",
        "Leave unrelated files alone.",
    ]
    if todo_markdown_path.exists() and todo_markdown_path != task_path:
        sections.extend(
            [
                "",
                "## Claimed Autoencoder TODO List",
                todo_markdown_path.read_text(encoding="utf-8"),
            ]
        )
    return "\n".join(sections).strip() + "\n"


def _save_packet_if_possible(packet: Mapping[str, Any], packet_path: Optional[Path]) -> None:
    if packet_path is None:
        return
    packet_path.write_text(
        json.dumps(dict(packet), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_artifact_name(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    return safe.strip("-")[:96] or "codex-worker"


def resolve_codex_worktree_repo_root(repo_root: Path) -> Path:
    """Return the checkout that actually contains modal source files for Codex.

    The Portland site checkout tracks ``ipfs_datasets_py`` as a gitlink-like
    nested checkout. A worktree from the parent repo only contains the gitlink,
    so Codex cannot edit ``ipfs_datasets_py/logic/modal/...`` there. Prefer the
    nested package checkout when it exists and is itself a git worktree.
    """

    root = Path(repo_root).resolve()
    nested = root / "ipfs_datasets_py"
    if (
        (nested / "ipfs_datasets_py" / "logic" / "modal").exists()
        and _path_is_git_worktree(nested)
    ):
        return nested
    return root


def _path_is_git_worktree(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            text=True,
            capture_output=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def run_tests(root: Path, report_dir: Path, cycle: int) -> Dict[str, Any]:
    xml_path = report_dir / f"cycle-{cycle}.xml"
    test_root = resolve_codex_worktree_repo_root(root)
    cmd = [
        "pytest",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_uscode_dataset.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
        "-q",
        "--junitxml",
        str(xml_path),
    ]
    started = time.time()
    result = subprocess.run(cmd, cwd=test_root, text=True, capture_output=True)
    return {
        "cycle": cycle,
        "duration_seconds": round(time.time() - started, 3),
        "event": "tests",
        "exit_code": result.returncode,
        "junitxml": str(xml_path),
        "test_root": str(test_root),
        "stderr_tail": result.stderr[-500:],
        "stdout_tail": result.stdout[-500:],
    }


def append_event(path: Path, run_id: str, event: Mapping[str, Any]) -> None:
    payload = {"created_at": utc_now(), "run_id": run_id, **dict(event)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def save_summary(summary_path: Path, summary: Dict[str, Any], *, final: bool = False) -> None:
    summary["final"] = final
    summary["updated_at"] = utc_now()
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def initial_summary(args: argparse.Namespace, *, log_path: Path, queue_path: Path, state_path: Path) -> Dict[str, Any]:
    seed = int(hashlib.sha256(args.run_id.encode("utf-8")).hexdigest()[:12], 16)
    return {
        "best_validation_ce": 1.0e12,
        "best_validation_cosine": -1.0,
        "best_validation_ir_ce": 1.0e12,
        "best_validation_ir_cosine": -1.0,
        "best_validation_ir_reconstruction": 1.0e12,
        "best_validation_ir_text_reconstruction": 1.0e12,
        "best_validation_reconstruction": 1.0e12,
        "cycles": 0,
        "codex_program_synthesis_execution_mode": "queued_for_external_codex_worker",
        "dataset_id": HF_USCODE_DATASET_ID,
        "final": False,
        "laws_path": USCODE_LAWS_PARQUET,
        "log_path": str(log_path),
        "loop_role": getattr(args, "loop_role", "autoencoder"),
        "metric_failures": 0,
        "optimizer_policy": "autoencoder_sgd_with_codex_program_synthesis_backlog",
        "program_synthesis_claimed": 0,
        "program_synthesis_completed": 0,
        "program_synthesis_pending_cap": ModalOptimizerPolicy().max_program_synthesis_pending,
        "program_synthesis_pending": 0,
        "program_synthesis_seeded": 0,
        "queue_run_id": getattr(args, "queue_run_id", None) or args.run_id,
        "queue_path": str(queue_path),
        "run_id": args.run_id,
        "seed": seed,
        "started_at": utc_now(),
        "state_path": str(state_path),
        "test_failures": 0,
        "train_ce_improved_cycles": 0,
        "train_cosine_improved_cycles": 0,
        "validation_ce_improved_cycles": 0,
        "validation_cosine_improved_cycles": 0,
    }


def build_uscode_modal_daemon_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--loop-role",
        choices=("autoencoder", "codex", "paired"),
        default="autoencoder",
        help="Run one daemon loop, or run both loops together with a paired orchestrator.",
    )
    parser.add_argument(
        "--queue-run-id",
        default=None,
        help="Existing run id whose TODO queue should be shared by this loop.",
    )
    parser.add_argument("--duration-seconds", type=float, default=3600.0)
    parser.add_argument("--train-count", type=int, default=4)
    parser.add_argument("--validation-count", type=int, default=4)
    parser.add_argument("--max-inner-iterations", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.35)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--test-every-cycles", type=int, default=24)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument(
        "--codex-exec-mode",
        choices=("packet_only", "codex_cli"),
        default="packet_only",
        help="For the Codex loop, either only create work packets or run codex exec in each packet worktree.",
    )
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--codex-model", default="gpt-5.3-codex")
    parser.add_argument(
        "--codex-apply-mode",
        choices=("patch_only", "apply_to_main"),
        default="patch_only",
        help=(
            "For codex_cli packets, either save a patch artifact or apply "
            "validated worktree edits back to the source checkout."
        ),
    )
    parser.add_argument(
        "--codex-commit-mode",
        choices=("none", "commit_applied"),
        default="none",
        help="Optionally commit successfully validated apply_to_main packet edits.",
    )
    parser.add_argument(
        "--codex-scope",
        choices=(
            "compiler_parser",
            "compiler_registry",
            "compiler_ambiguity",
            "ir_decompiler",
            "frame_logic",
        ),
        default=None,
        help="Restrict the Codex worker to one AST/write-scope lane for parallel runs.",
    )
    parser.add_argument(
        "--codex-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    parser.add_argument("--codex-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--autoencoder-run-id", default=None)
    parser.add_argument("--codex-run-id", default=None)
    parser.add_argument("--paired-launch-delay-seconds", type=float, default=0.0)
    parser.add_argument("--paired-poll-seconds", type=float, default=1.0)
    parser.add_argument("--paired-grace-seconds", type=float, default=300.0)
    parser.add_argument(
        "--warm-start-run-id",
        action="append",
        default=[],
        help="Import feature-level state from a prior run id without sample-specific memory.",
    )
    parser.add_argument(
        "--warm-start-state",
        action="append",
        default=[],
        help="Import feature-level state from a prior state JSON path.",
    )
    return parser


def resolve_warm_start_state_paths(args: argparse.Namespace, queue_dir: Path) -> List[Path]:
    """Resolve explicit warm-start state paths and prior run ids."""
    paths = [Path(path) for path in getattr(args, "warm_start_state", [])]
    paths.extend(
        queue_dir / f"{run_id}.state.json"
        for run_id in getattr(args, "warm_start_run_id", [])
    )
    return paths


def load_warm_start_state(paths: Sequence[Path]) -> tuple[ModalAutoencoderTrainingState, Dict[str, Any]]:
    """Load and average generalizable state from previous runs."""
    loaded_states: List[ModalAutoencoderTrainingState] = []
    loaded_paths: List[str] = []
    missing_paths: List[str] = []
    for path in paths:
        if not path.exists():
            missing_paths.append(str(path))
            continue
        loaded_states.append(ModalAutoencoderTrainingState.load_json(path).generalizable_copy())
        loaded_paths.append(str(path))

    averaged = ModalAutoencoderTrainingState.average_generalizable(loaded_states)
    return averaged, {
        "feature_embedding_weight_entries": len(averaged.feature_embedding_weights),
        "feature_family_logit_entries": len(averaged.feature_family_logits),
        "loaded_paths": loaded_paths,
        "missing_paths": missing_paths,
        "source_count": len(loaded_states),
    }


def run_paired_uscode_modal_daemons(args: argparse.Namespace) -> int:
    """Run autoencoder and codex daemons as coordinated child processes."""
    root = Path.cwd()
    log_dir = root / "workspace" / "test-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{args.run_id}.jsonl"
    summary_path = log_dir / f"{args.run_id}.summary"
    paired = build_paired_daemon_commands(
        args,
        module_name="ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
    )
    auto_stdout_path = log_dir / f"{paired['autoencoder_run_id']}.orchestrator.stdout.log"
    auto_stderr_path = log_dir / f"{paired['autoencoder_run_id']}.orchestrator.stderr.log"
    codex_stdout_path = log_dir / f"{paired['codex_run_id']}.orchestrator.stdout.log"
    codex_stderr_path = log_dir / f"{paired['codex_run_id']}.orchestrator.stderr.log"

    summary: Dict[str, Any] = {
        "autoencoder_command": list(paired["autoencoder_command"]),
        "autoencoder_run_id": paired["autoencoder_run_id"],
        "autoencoder_stderr_path": str(auto_stderr_path),
        "autoencoder_stdout_path": str(auto_stdout_path),
        "codex_command": list(paired["codex_command"]),
        "codex_run_id": paired["codex_run_id"],
        "codex_stderr_path": str(codex_stderr_path),
        "codex_stdout_path": str(codex_stdout_path),
        "duration_seconds": float(args.duration_seconds),
        "final": False,
        "log_path": str(log_path),
        "loop_role": "paired",
        "paired_grace_seconds": float(args.paired_grace_seconds),
        "paired_poll_seconds": float(args.paired_poll_seconds),
        "queue_run_id": paired["queue_run_id"],
        "run_id": args.run_id,
        "started_at": utc_now(),
    }
    save_summary(summary_path, summary)

    stop_requested = False
    stop_signal: int | None = None
    previous_signal_handlers: Dict[int, Any] = {}

    def request_stop(signum: int, frame: Any) -> None:
        nonlocal stop_requested, stop_signal
        stop_requested = True
        stop_signal = signum

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_signal_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)

    append_event(
        log_path,
        args.run_id,
        {
            "event": "paired_runner_started",
            "autoencoder_run_id": paired["autoencoder_run_id"],
            "codex_run_id": paired["codex_run_id"],
            "queue_run_id": paired["queue_run_id"],
        },
    )

    started = time.time()
    auto_process: Optional[subprocess.Popen[str]] = None
    codex_process: Optional[subprocess.Popen[str]] = None
    auto_exit_code: Optional[int] = None
    codex_exit_code: Optional[int] = None

    try:
        with auto_stdout_path.open("a", encoding="utf-8") as auto_stdout, auto_stderr_path.open(
            "a", encoding="utf-8"
        ) as auto_stderr, codex_stdout_path.open("a", encoding="utf-8") as codex_stdout, codex_stderr_path.open(
            "a", encoding="utf-8"
        ) as codex_stderr:
            auto_process = subprocess.Popen(
                list(paired["autoencoder_command"]),
                cwd=root,
                stdout=auto_stdout,
                stderr=auto_stderr,
                text=True,
            )
            append_event(
                log_path,
                args.run_id,
                {
                    "event": "paired_child_started",
                    "child_role": "autoencoder",
                    "child_pid": auto_process.pid,
                    "child_run_id": paired["autoencoder_run_id"],
                },
            )

            launch_delay = max(0.0, float(args.paired_launch_delay_seconds))
            if launch_delay > 0.0:
                time.sleep(launch_delay)

            codex_process = subprocess.Popen(
                list(paired["codex_command"]),
                cwd=root,
                stdout=codex_stdout,
                stderr=codex_stderr,
                text=True,
            )
            append_event(
                log_path,
                args.run_id,
                {
                    "event": "paired_child_started",
                    "child_role": "codex",
                    "child_pid": codex_process.pid,
                    "child_run_id": paired["codex_run_id"],
                },
            )

            poll_seconds = max(0.2, float(args.paired_poll_seconds))
            max_wait = float(args.duration_seconds) + max(0.0, float(args.paired_grace_seconds))
            while True:
                auto_exit_code = auto_process.poll()
                codex_exit_code = codex_process.poll()
                summary["elapsed_seconds"] = round(time.time() - started, 3)
                summary["autoencoder_pid"] = auto_process.pid
                summary["codex_pid"] = codex_process.pid
                summary["autoencoder_exit_code"] = auto_exit_code
                summary["codex_exit_code"] = codex_exit_code
                summary["child_status"] = {
                    "autoencoder": "running" if auto_exit_code is None else "exited",
                    "codex": "running" if codex_exit_code is None else "exited",
                }
                save_summary(summary_path, summary)

                if auto_exit_code is not None and codex_exit_code is not None:
                    break
                if stop_requested:
                    break
                if (time.time() - started) > max_wait:
                    summary["latest_stop_reason"] = "paired_timeout_grace_exceeded"
                    break
                time.sleep(poll_seconds)
    finally:
        for process in (auto_process, codex_process):
            if process is None or process.poll() is not None:
                continue
            process.terminate()

        termination_wait_seconds = max(
            10.0,
            float(args.paired_grace_seconds),
        )
        for process in (auto_process, codex_process):
            if process is None or process.poll() is not None:
                continue
            try:
                process.wait(timeout=termination_wait_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)

        if auto_process is not None:
            auto_exit_code = auto_process.poll()
        if codex_process is not None:
            codex_exit_code = codex_process.poll()

        if stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_signal}"
            summary["stopped_by_signal"] = stop_signal
        summary["elapsed_seconds"] = round(time.time() - started, 3)
        summary["autoencoder_exit_code"] = auto_exit_code
        summary["codex_exit_code"] = codex_exit_code
        summary["child_status"] = {
            "autoencoder": "running" if auto_exit_code is None else "exited",
            "codex": "running" if codex_exit_code is None else "exited",
        }
        summary["finished_at"] = utc_now()
        summary["status"] = (
            "succeeded"
            if auto_exit_code == 0 and codex_exit_code == 0
            else "failed"
        )
        save_summary(summary_path, summary, final=True)
        append_event(
            log_path,
            args.run_id,
            {
                "event": "paired_runner_finished",
                "status": summary["status"],
                "autoencoder_exit_code": auto_exit_code,
                "codex_exit_code": codex_exit_code,
                "elapsed_seconds": summary["elapsed_seconds"],
            },
        )
        for signum, handler in previous_signal_handlers.items():
            signal.signal(signum, handler)

    return 0 if auto_exit_code == 0 and codex_exit_code == 0 else 1


def run_guarded_uscode_modal_daemon(args: argparse.Namespace) -> int:
    """Run the guarded modal TODO daemon using parsed CLI-style arguments."""

    root = Path.cwd()
    log_dir = root / "workspace" / "test-logs"
    queue_dir = root / "workspace" / "todo-queues"
    report_dir = root / "workspace" / "test-reports" / args.run_id
    log_path = log_dir / f"{args.run_id}.jsonl"
    summary_path = log_dir / f"{args.run_id}.summary"
    queue_path = queue_dir / f"{args.run_id}.jsonl"
    state_path = queue_dir / f"{args.run_id}.state.json"
    run_json_path = queue_dir / f"{args.run_id}.last-run.json"
    log_dir.mkdir(parents=True, exist_ok=True)
    queue_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    stop_requested = False
    stop_signal: int | None = None
    previous_signal_handlers: Dict[int, Any] = {}

    def request_stop(signum: int, frame: Any) -> None:
        nonlocal stop_requested, stop_signal
        stop_requested = True
        stop_signal = signum

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_signal_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = initial_summary(
            args,
            log_path=log_path,
            queue_path=queue_path,
            state_path=state_path,
        )
        save_summary(summary_path, summary)
    started_at = parse_utc(summary["started_at"])
    end_at = started_at + args.duration_seconds
    state = ModalAutoencoderTrainingState.load_json(state_path)
    warm_start_paths = resolve_warm_start_state_paths(args, queue_dir)
    if warm_start_paths:
        existing_warm_start = dict(summary.get("warm_start", {}))
        if existing_warm_start.get("applied") is True:
            append_event(
                log_path,
                args.run_id,
                {
                    "event": "warm_start_skipped",
                    "reason": "already_applied",
                    "warm_start": existing_warm_start,
                },
            )
        else:
            warm_state, warm_start = load_warm_start_state(warm_start_paths)
            state.merge_generalizable_from(warm_state)
            warm_start["applied"] = True
            summary["warm_start"] = warm_start
            state.save_json(state_path)
            save_summary(summary_path, summary)
            append_event(
                log_path,
                args.run_id,
                {"event": "warm_start_loaded", "warm_start": warm_start},
            )
    with queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
    feature_codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )
    autoencoder = AdaptiveModalAutoencoder(state=state, feature_codec=feature_codec)
    supervisor = ModalTodoSupervisor(queue=queue)
    rng = random.Random(int(summary.get("seed", 0)) + int(summary.get("cycles", 0)) + 1)
    blocked_validation_sample_ids = set(state.decoded_embeddings) | set(state.family_logits)

    append_event(log_path, args.run_id, {"event": "detached_runner_started"})
    laws_table = load_laws_table()
    append_event(
        log_path,
        args.run_id,
        {"event": "detached_dataset_loaded", "row_count": laws_table.num_rows},
    )

    try:
        while not stop_requested and time.time() + 8.0 < end_at:
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            (
                train_indices,
                train_samples,
                validation_indices,
                validation_samples,
                validation_sampling_attempts,
            ) = sample_train_validation_rows(
                laws_table,
                rng,
                train_count=args.train_count,
                validation_count=args.validation_count,
                blocked_validation_sample_ids=blocked_validation_sample_ids,
            )
            before_train = autoencoder.evaluate(train_samples)
            before_validation = autoencoder.evaluate(
                validation_samples,
                use_sample_memory=False,
            )
            compiler_ir_train = compiler_ir_metric_block(train_samples, feature_codec)
            compiler_ir_validation = compiler_ir_metric_block(
                validation_samples,
                feature_codec,
            )
            run = supervisor.optimize(
                train_samples,
                validation_samples=validation_samples,
                autoencoder=autoencoder,
                worker_id="random-uscode-daemon-detached",
                max_items=args.max_items,
                learning_rate=args.learning_rate,
                max_iterations=args.max_inner_iterations,
                target_cross_entropy_loss=0.001,
                target_cosine_similarity=0.999999,
            )
            after_train = run.final_evaluation
            after_validation = run.validation_final_evaluation or autoencoder.evaluate(
                validation_samples,
                use_sample_memory=False,
            )
            blocked_validation_sample_ids.update(sample.sample_id for sample in train_samples)
            with queue_file_lock(queue_path):
                latest_queue = ModalTodoQueue.load_jsonl(queue_path)
                latest_queue.merge_from(
                    supervisor.queue,
                    preserve_claimed_role=supervisor.policy.program_synthesis_role,
                )
                semantic_deduped_count = latest_queue.deduplicate_semantic(
                    optimizer_role=supervisor.policy.program_synthesis_role,
                    near_duplicate_jaccard=supervisor.policy.program_synthesis_near_duplicate_jaccard,
                )
                latest_queue.save_jsonl(queue_path)
                supervisor.queue = latest_queue
                queue = latest_queue
            autoencoder.state.save_json(state_path)
            run.save_json(run_json_path)

            train_ce_delta = before_train.cross_entropy_loss - after_train.cross_entropy_loss
            validation_ce_delta = before_validation.cross_entropy_loss - after_validation.cross_entropy_loss
            train_cos_delta = after_train.embedding_cosine_similarity - before_train.embedding_cosine_similarity
            validation_cos_delta = (
                after_validation.embedding_cosine_similarity
                - before_validation.embedding_cosine_similarity
            )
            summary["cycles"] = cycle
            summary["latest_stop_reason"] = run.stopped_reason
            summary["latest_queue_counts"] = supervisor.queue.status_counts()
            summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
            program_synthesis_status = update_program_synthesis_summary(
                summary,
                supervisor.queue,
                supervisor.policy,
            )
            summary["program_synthesis_seeded"] = int(
                summary.get("program_synthesis_seeded", 0)
            ) + sum(step.program_synthesis_seeded_count for step in run.steps)
            summary["program_synthesis_semantic_deduped"] = int(
                summary.get("program_synthesis_semantic_deduped", 0)
            ) + int(semantic_deduped_count)
            summary["metric_failures"] = int(summary.get("metric_failures", 0)) + int(
                compiler_ir_train.get("metric_failures", 0)
                + compiler_ir_validation.get("metric_failures", 0)
            )
            summary["train_ce_improved_cycles"] = int(summary.get("train_ce_improved_cycles", 0)) + int(train_ce_delta > 0.0)
            summary["validation_ce_improved_cycles"] = int(summary.get("validation_ce_improved_cycles", 0)) + int(validation_ce_delta > 0.0)
            summary["train_cosine_improved_cycles"] = int(summary.get("train_cosine_improved_cycles", 0)) + int(train_cos_delta > 0.0)
            summary["validation_cosine_improved_cycles"] = int(summary.get("validation_cosine_improved_cycles", 0)) + int(validation_cos_delta > 0.0)
            summary["best_validation_ce"] = min(summary.get("best_validation_ce"), after_validation.cross_entropy_loss)
            summary["best_validation_ir_ce"] = min(
                summary.get("best_validation_ir_ce", 1.0e12),
                float(compiler_ir_validation.get("cross_entropy_loss", 1.0e12)),
            )
            summary["best_validation_ir_cosine"] = max(
                summary.get("best_validation_ir_cosine", -1.0),
                float(compiler_ir_validation.get("cosine_similarity", -1.0)),
            )
            summary["best_validation_ir_reconstruction"] = min(
                summary.get("best_validation_ir_reconstruction", 1.0e12),
                float(compiler_ir_validation.get("reconstruction_loss", 1.0e12)),
            )
            summary["best_validation_ir_text_reconstruction"] = min(
                summary.get("best_validation_ir_text_reconstruction", 1.0e12),
                float(compiler_ir_validation.get("text_reconstruction_loss", 1.0e12)),
            )
            summary["best_validation_cosine"] = max(
                summary.get("best_validation_cosine"),
                after_validation.embedding_cosine_similarity,
            )
            summary["best_validation_reconstruction"] = min(
                summary.get("best_validation_reconstruction"),
                after_validation.reconstruction_loss,
            )
            append_event(
                log_path,
                args.run_id,
                {
                    "after_train": metric_block(after_train),
                    "after_validation": metric_block(after_validation),
                    "applied_count": sum(step.applied_count for step in run.steps),
                    "autoencoder_after_train": metric_block(after_train),
                    "autoencoder_after_validation": metric_block(after_validation),
                    "autoencoder_before_train": metric_block(before_train),
                    "autoencoder_before_validation": metric_block(before_validation),
                    "before_train": metric_block(before_train),
                    "before_validation": metric_block(before_validation),
                    "completed_count": sum(step.completed_count for step in run.steps),
                    "compiler_ir_train": compiler_ir_train,
                    "compiler_ir_validation": compiler_ir_validation,
                    "cycle": cycle,
                    "duration_seconds": round(time.time() - cycle_started, 3),
                    "event": "cycle",
                    "failed_validation_count": sum(step.failed_validation_count for step in run.steps),
                    "queue_counts": supervisor.queue.status_counts(),
                    "role_queue_counts": supervisor.queue.role_status_counts(),
                    "stopped_reason": run.stopped_reason,
                    "program_synthesis_claimed_count": program_synthesis_status["claimed"],
                    "program_synthesis_completed_count": program_synthesis_status["completed"],
                    "program_synthesis_execution_mode": program_synthesis_status["execution_mode"],
                    "program_synthesis_pending_count": program_synthesis_status["pending"],
                    "program_synthesis_seeded_count": sum(
                        step.program_synthesis_seeded_count for step in run.steps
                    ),
                    "program_synthesis_semantic_deduped_count": semantic_deduped_count,
                    "train_cosine_delta": round(train_cos_delta, 9),
                    "train_cross_entropy_delta": round(train_ce_delta, 9),
                    "train_indices": train_indices,
                    "validation_sampling_attempts": validation_sampling_attempts,
                    "validation_cosine_delta": round(validation_cos_delta, 9),
                    "validation_cross_entropy_delta": round(validation_ce_delta, 9),
                    "validation_indices": validation_indices,
                },
            )
            save_summary(summary_path, summary)

            if cycle % args.test_every_cycles == 0:
                test_result = run_tests(root, report_dir, cycle)
                summary["test_failures"] = int(summary.get("test_failures", 0)) + int(test_result["exit_code"] != 0)
                append_event(log_path, args.run_id, test_result)
                save_summary(summary_path, summary)
    finally:
        if stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_signal}"
            summary["stopped_by_signal"] = stop_signal
        summary["applied_todo_ids"] = len(autoencoder.state.applied_todo_ids)
        summary["decoded_embedding_entries"] = len(autoencoder.state.decoded_embeddings)
        summary["elapsed_seconds"] = round(time.time() - started_at, 3)
        summary["family_logit_entries"] = len(autoencoder.state.family_logits)
        summary["feature_embedding_weight_entries"] = len(autoencoder.state.feature_embedding_weights)
        summary["feature_family_logit_entries"] = len(autoencoder.state.feature_family_logits)
        summary["finished_at"] = utc_now()
        summary["latest_queue_counts"] = supervisor.queue.status_counts()
        summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
        update_program_synthesis_summary(
            summary,
            supervisor.queue,
            supervisor.policy,
        )
        save_summary(summary_path, summary, final=True)
        append_event(log_path, args.run_id, {"event": "run_finished", **summary})
        for signum, handler in previous_signal_handlers.items():
            signal.signal(signum, handler)
    return 0


def run_codex_program_synthesis_daemon(args: argparse.Namespace) -> int:
    """Claim program-synthesis TODOs asynchronously for an external Codex worker."""
    root = Path.cwd()
    log_dir = root / "workspace" / "test-logs"
    queue_dir = root / "workspace" / "todo-queues"
    work_dir = root / "workspace" / "codex-work" / args.run_id
    queue_run_id = getattr(args, "queue_run_id", None) or args.run_id
    queue_path = queue_dir / f"{queue_run_id}.jsonl"
    log_path = log_dir / f"{args.run_id}.jsonl"
    summary_path = log_dir / f"{args.run_id}.summary"
    worker_id = (
        getattr(args, "worker_id", None)
        or f"codex-program-synthesis-{args.run_id}"
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    queue_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    execution_mode = codex_loop_execution_mode(args)

    stop_requested = False
    stop_signal: int | None = None
    previous_signal_handlers: Dict[int, Any] = {}

    def request_stop(signum: int, frame: Any) -> None:
        nonlocal stop_requested, stop_signal
        stop_requested = True
        stop_signal = signum

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_signal_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {
            "codex_apply_mode": args.codex_apply_mode,
            "codex_claimed_total": 0,
            "codex_commit_mode": args.codex_commit_mode,
            "codex_exec_mode": args.codex_exec_mode,
            "codex_scope": args.codex_scope,
            "codex_execution_count": 0,
            "codex_execution_failure_count": 0,
            "codex_main_apply_count": 0,
            "codex_main_apply_failure_count": 0,
            "codex_packet_count": 0,
            "codex_patch_count": 0,
            "codex_program_synthesis_execution_mode": execution_mode,
            "codex_worktree_count": 0,
            "cycles": 0,
            "final": False,
            "log_path": str(log_path),
            "loop_role": "codex",
            "program_synthesis_claimed": 0,
            "program_synthesis_completed": 0,
            "program_synthesis_pending": 0,
            "queue_path": str(queue_path),
            "queue_run_id": queue_run_id,
            "run_id": args.run_id,
            "started_at": utc_now(),
            "worker_id": worker_id,
            "work_dir": str(work_dir),
        }
        save_summary(summary_path, summary)
    summary.setdefault("codex_apply_mode", args.codex_apply_mode)
    summary.setdefault("codex_commit_mode", args.codex_commit_mode)
    summary.setdefault("codex_scope", args.codex_scope)
    summary.setdefault("codex_main_apply_count", 0)
    summary.setdefault("codex_main_apply_failure_count", 0)

    started_at = parse_utc(summary["started_at"])
    end_at = started_at + args.duration_seconds
    policy = ModalOptimizerPolicy()
    append_event(
        log_path,
        args.run_id,
        {
            "codex_apply_mode": args.codex_apply_mode,
            "codex_commit_mode": args.codex_commit_mode,
            "codex_exec_mode": args.codex_exec_mode,
            "codex_scope": args.codex_scope,
            "codex_program_synthesis_execution_mode": execution_mode,
            "event": "codex_program_synthesis_runner_started",
            "queue_run_id": queue_run_id,
            "worker_id": worker_id,
        },
    )

    try:
        while not stop_requested and time.time() < end_at:
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            packet: Dict[str, Any] = {}
            with queue_file_lock(queue_path):
                queue = ModalTodoQueue.load_jsonl(queue_path)
                supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
                claimed = supervisor.claim_program_synthesis_batch(
                    worker_id=worker_id,
                    max_items=args.max_items,
                    program_synthesis_scope=getattr(args, "codex_scope", None),
                )
                if claimed:
                    queue.save_jsonl(queue_path)
                status = update_program_synthesis_summary(
                    summary,
                    queue,
                    policy,
                    execution_mode=execution_mode,
                )

            if claimed:
                packet = create_codex_work_packet(
                    cycle=cycle,
                    queue_path=queue_path,
                    queue_run_id=queue_run_id,
                    repo_root=root,
                    run_id=args.run_id,
                    todos=claimed,
                    work_dir=work_dir,
                    worker_id=worker_id,
                )
                if args.codex_exec_mode == "codex_cli":
                    packet = execute_codex_work_packet(
                        packet,
                        apply_mode=args.codex_apply_mode,
                        commit_mode=args.codex_commit_mode,
                        codex_command=args.codex_command,
                        model=args.codex_model,
                        sandbox=args.codex_sandbox,
                        timeout_seconds=args.codex_timeout_seconds,
                    )
                    exec_status = str(
                        dict(packet.get("codex_exec", {})).get("status", "unknown")
                    )
                    with queue_file_lock(queue_path):
                        queue = ModalTodoQueue.load_jsonl(queue_path)
                        supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
                        finalize_report = supervisor.finalize_program_synthesis_batch(
                            claimed,
                            codex_exec_status=exec_status,
                            patch_status=(
                                str(packet.get("patch_status"))
                                if packet.get("patch_status") is not None
                                else None
                            ),
                        )
                        if finalize_report["updated"]:
                            queue.save_jsonl(queue_path)
                        status = update_program_synthesis_summary(
                            summary,
                            queue,
                            policy,
                            execution_mode=execution_mode,
                        )

            summary["cycles"] = cycle
            summary["codex_claimed_total"] = int(
                summary.get("codex_claimed_total", 0)
            ) + len(claimed)
            if packet.get("codex_exec"):
                summary["codex_execution_count"] = int(
                    summary.get("codex_execution_count", 0)
                ) + 1
                exec_status = str(
                    packet.get("codex_exec", {}).get("status", "")
                ).strip().lower()
                patch_status = str(packet.get("patch_status", "")).strip().lower()
                if (
                    exec_status != "succeeded"
                    and patch_status not in CODEX_COMPLETED_WORK_STATUSES
                ):
                    summary["codex_execution_failure_count"] = int(
                        summary.get("codex_execution_failure_count", 0)
                    ) + 1
            main_apply_status = str(packet.get("main_apply_status", "")).strip().lower()
            if main_apply_status == "applied":
                summary["codex_main_apply_count"] = int(
                    summary.get("codex_main_apply_count", 0)
                ) + 1
            elif main_apply_status and main_apply_status not in {"no_changes", "skipped"}:
                summary["codex_main_apply_failure_count"] = int(
                    summary.get("codex_main_apply_failure_count", 0)
                ) + 1
            summary["codex_packet_count"] = int(
                summary.get("codex_packet_count", 0)
            ) + int(bool(packet.get("packet_path")))
            summary["codex_patch_count"] = int(
                summary.get("codex_patch_count", 0)
            ) + int(bool(packet.get("patch_path")))
            summary["codex_worktree_count"] = int(
                summary.get("codex_worktree_count", 0)
            ) + int(bool(packet.get("worktree_path")))
            summary["elapsed_seconds"] = round(time.time() - started_at, 3)
            summary["latest_queue_counts"] = queue.status_counts()
            summary["latest_role_queue_counts"] = queue.role_status_counts()
            summary["latest_stop_reason"] = (
                "claimed_program_synthesis_todos"
                if claimed
                else "waiting_for_program_synthesis_todos"
            )
            append_event(
                log_path,
                args.run_id,
                {
                    "claimed_count": len(claimed),
                    "cycle": cycle,
                    "codex_exec_status": dict(packet.get("codex_exec", {})).get("status"),
                    "codex_scope": getattr(args, "codex_scope", None),
                    "duration_seconds": round(time.time() - cycle_started, 3),
                    "event": "codex_program_synthesis_cycle",
                    "main_apply_status": packet.get("main_apply_status"),
                    "main_apply_target_repo_root": packet.get("main_apply_target_repo_root"),
                    "main_apply_validation_status": dict(
                        packet.get("main_apply_validation", {})
                    ).get("status"),
                    "main_commit_status": dict(packet.get("main_commit", {})).get("status"),
                    "packet_path": packet.get("packet_path"),
                    "patch_path": packet.get("patch_path"),
                    "patch_status": packet.get("patch_status"),
                    "program_synthesis_claimed_count": status["claimed"],
                    "program_synthesis_completed_count": status["completed"],
                    "program_synthesis_execution_mode": status["execution_mode"],
                    "program_synthesis_pending_count": status["pending"],
                    "queue_run_id": queue_run_id,
                    "todo_list_path": packet.get("todo_list_path"),
                    "todo_markdown_path": packet.get("todo_markdown_path"),
                    "worktree_path": packet.get("worktree_path"),
                },
            )
            save_summary(summary_path, summary)
            sleep_seconds = max(0.1, float(args.poll_seconds))
            if not stop_requested:
                time.sleep(sleep_seconds)
    finally:
        if stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_signal}"
            summary["stopped_by_signal"] = stop_signal
        summary["elapsed_seconds"] = round(time.time() - started_at, 3)
        with queue_file_lock(queue_path):
            queue = ModalTodoQueue.load_jsonl(queue_path)
            update_program_synthesis_summary(
                summary,
                queue,
                policy,
                execution_mode=execution_mode,
            )
            summary["latest_queue_counts"] = queue.status_counts()
            summary["latest_role_queue_counts"] = queue.role_status_counts()
        summary["finished_at"] = utc_now()
        save_summary(summary_path, summary, final=True)
        append_event(log_path, args.run_id, {"event": "run_finished", **summary})
        for signum, handler in previous_signal_handlers.items():
            signal.signal(signum, handler)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_uscode_modal_daemon_arg_parser()
    args = parser.parse_args(argv)
    if args.loop_role == "paired":
        return run_paired_uscode_modal_daemons(args)
    if args.loop_role == "codex":
        return run_codex_program_synthesis_daemon(args)
    return run_guarded_uscode_modal_daemon(args)


if __name__ == "__main__":
    raise SystemExit(main())
