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
import os
import random
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AbstractSet, Any, Dict, Iterator, List, Mapping, Optional, Sequence

import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
)
from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES
from ipfs_datasets_py.logic.submodule_registry import (
    logic_optimizer_target_file_hints,
    logic_submodule_specs,
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
    bridge_loss_evaluator_for_names,
    program_synthesis_todo_embedding_text,
    select_program_synthesis_vector_bundle,
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
DEFAULT_BRIDGE_LOSS_ADAPTERS = ",".join(DEFAULT_LEGAL_IR_BRIDGE_NAMES)

CODEX_AST_SCOPES = tuple(
    dict.fromkeys(
        scope
        for scope in (
            "compiler_parser",
            "compiler_registry",
            "compiler_ambiguity",
            "ir_decompiler",
            "frame_logic",
            *(
                spec.ast_scope
                for spec in logic_submodule_specs()
                if spec.ast_scope
            ),
        )
        if scope
    )
)


CODEX_TARGET_FILE_HINTS = {
    key: list(value)
    for key, value in logic_optimizer_target_file_hints().items()
}
CODEX_TARGET_FILE_HINTS.update({
    "logic.optimizer.autoencoder": [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ],
    "logic.optimizer.backlog": [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ],
    "logic.optimizer.codex_bundler": [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ],
    "logic.optimizer.residual_clusterer": [
        "ipfs_datasets_py/logic/modal/synthesis.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ],
    "logic.optimizer.residual_router": [
        "ipfs_datasets_py/logic/modal/synthesis.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ],
    "logic.optimizer.supervisor": [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ],
    "logic.optimizer.validation_gate": [
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ],
    "CEC.native": [
        "ipfs_datasets_py/logic/bridge/cec_dcec.py",
        "ipfs_datasets_py/logic/bridge/types.py",
        "ipfs_datasets_py/logic/CEC/cec_framework.py",
        "ipfs_datasets_py/logic/CEC/dcec_wrapper.py",
        "ipfs_datasets_py/logic/CEC/native",
    ],
    "TDFOL.prover": [
        "ipfs_datasets_py/logic/bridge/fol_tdfol.py",
        "ipfs_datasets_py/logic/bridge/types.py",
        "ipfs_datasets_py/logic/TDFOL/tdfol_core.py",
        "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",
        "ipfs_datasets_py/logic/TDFOL/tdfol_prover.py",
    ],
    "deontic.ir": [
        "ipfs_datasets_py/logic/bridge/deontic_norms.py",
        "ipfs_datasets_py/logic/bridge/types.py",
        "ipfs_datasets_py/logic/deontic/converter.py",
        "ipfs_datasets_py/logic/deontic/ir.py",
        "ipfs_datasets_py/logic/deontic/formula_builder.py",
        "ipfs_datasets_py/logic/deontic/prover_syntax.py",
        "ipfs_datasets_py/logic/deontic/metrics.py",
    ],
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
        "ipfs_datasets_py/logic/bridge/modal_frame_logic.py",
        "ipfs_datasets_py/logic/bridge/types.py",
        "ipfs_datasets_py/logic/modal/codec.py",
        "ipfs_datasets_py/logic/modal/kg_bridge.py",
        "ipfs_datasets_py/logic/flogic_optimizer.py",
        "ipfs_datasets_py/optimizers/logic/flogic_optimizer.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py",
    ],
    "modal.ir_decompiler": [
        "ipfs_datasets_py/logic/modal/codec.py",
        "ipfs_datasets_py/logic/modal/decompiler.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
    ],
    "external_provers.router": [
        "ipfs_datasets_py/logic/bridge/external_prover_router.py",
        "ipfs_datasets_py/logic/bridge/fol_tdfol.py",
        "ipfs_datasets_py/logic/external_provers/prover_router.py",
        "ipfs_datasets_py/logic/external_provers/lazy_installer.py",
    ],
})

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
    "blocked by execution environment",
    "blocked by the execution sandbox",
    "bwrap: loopback: failed rtm_newaddr",
    "operation not permitted",
)
CODEX_COMPLETED_WORK_STATUSES = {
    "created",
    "applied_to_main",
    "main_apply_no_merged_delta",
}
CODEX_TRANSIENT_FAILURE_PATTERNS = (
    "selected model is at capacity",
    "temporarily unavailable",
    "try again",
    "rate limit",
)
CODEX_BUNDLE_MODES = ("priority", "semantic", "vector")
CODEX_MERGE_REPAIR_MODES = ("off", "apply_3way")
CODEX_VECTOR_FALLBACK_MODES = ("hash", "priority")
CODEX_LANE_LOCK_MODES = ("target_file", "ast", "hybrid")
CODEX_APPLY_VALIDATION_TESTS = (
    "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
    "tests/unit_tests/logic/modal/test_modal_codec.py",
)
BRIDGE_IR_REPORT_CACHE_MAX = 4096
_BRIDGE_IR_REPORT_CACHE_LOCK = threading.Lock()
_BRIDGE_IR_REPORT_CACHE: Dict[str, Any] = {}
_ACTIVE_CODEX_EXEC_PROCESSES: List[subprocess.Popen[str]] = []
CODEX_WORKTREE_ARTIFACT_FILENAMES = {"changes.patch"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _todo_age_seconds(todo: ModalTodo, *, now: Optional[float] = None) -> float:
    try:
        created_at = parse_utc(str(todo.created_at))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, float(now if now is not None else time.time()) - created_at)


def _oldest_todo_age_seconds(todos: Sequence[ModalTodo]) -> float:
    if not todos:
        return 0.0
    now = time.time()
    return max(_todo_age_seconds(todo, now=now) for todo in todos)


def _claimed_todo_age_seconds(todo: ModalTodo, *, now: Optional[float] = None) -> float:
    try:
        claimed_at = parse_utc(str(todo.claimed_at or ""))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, float(now if now is not None else time.time()) - claimed_at)


def _todo_target_file_hints(todo: ModalTodo) -> List[str]:
    target_component = str(todo.metadata.get("target_component") or "")
    files: List[str] = []
    for file_path in CODEX_TARGET_FILE_HINTS.get(target_component, []):
        if file_path not in files:
            files.append(file_path)
    if not files:
        for file_path in CODEX_ACTION_FILE_HINTS.get(todo.action, []):
            if file_path not in files:
                files.append(file_path)
    return files


def _todo_program_synthesis_scope(todo: ModalTodo) -> str:
    return str(todo.metadata.get("program_synthesis_scope") or "").strip()


def _codex_lane_lock_mode(args: argparse.Namespace) -> str:
    raw = str(getattr(args, "codex_lane_lock_mode", "target_file") or "").strip().lower()
    return raw if raw in CODEX_LANE_LOCK_MODES else "target_file"


def _codex_target_file_lane_lock_scopes(args: argparse.Namespace) -> Optional[set[str]]:
    raw = str(
        getattr(args, "codex_target_file_lane_lock_scopes", "compiler_registry") or ""
    ).strip()
    if not raw:
        return set()
    if raw.lower() == "all":
        return None
    return {scope.strip() for scope in raw.split(",") if scope.strip()}


def _target_file_lane_lock_enabled_for(
    todo: ModalTodo,
    lock_scopes: Optional[set[str]],
) -> bool:
    if lock_scopes is None:
        return True
    if not lock_scopes:
        return False
    return _todo_program_synthesis_scope(todo) in lock_scopes


def _todo_modal_family_pairs(todo: ModalTodo) -> List[str]:
    pairs: List[str] = []
    semantic_bundle_key = todo.metadata.get("semantic_bundle_key")
    if isinstance(semantic_bundle_key, str) and semantic_bundle_key.strip():
        try:
            parsed = json.loads(semantic_bundle_key)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, Mapping):
            for pair in parsed.get("family_pairs") or []:
                value = str(pair).strip()
                if value and value not in pairs:
                    pairs.append(value)

    for evidence in todo.metadata.get("hint_evidence") or []:
        if not isinstance(evidence, Mapping):
            continue
        predicted = str(evidence.get("predicted_family") or "").strip()
        target = str(evidence.get("target_family") or "").strip()
        if not predicted or not target:
            continue
        value = f"{predicted}->{target}"
        if value not in pairs:
            pairs.append(value)
    return pairs


def _stable_lane_fragment(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _todo_ast_lane_keys(todo: ModalTodo) -> List[str]:
    scope = _todo_program_synthesis_scope(todo) or "unknown"
    target_component = str(todo.metadata.get("target_component") or "").strip()
    base = f"ast:{scope}:{target_component or todo.action}"
    keys: List[str] = []

    family_pairs = _todo_modal_family_pairs(todo)
    if family_pairs and scope in {"compiler_ambiguity", "compiler_registry"}:
        for pair in family_pairs:
            keys.append(f"{base}:family:{pair}")
        return keys

    semantic_bundle_key = str(todo.metadata.get("semantic_bundle_key") or "").strip()
    if semantic_bundle_key:
        return [f"{base}:semantic:{_stable_lane_fragment(semantic_bundle_key)}"]

    action = str(todo.action or "").strip()
    return [f"{base}:action:{action}"]


def _todo_lane_lock_keys(todo: ModalTodo, *, mode: str) -> List[str]:
    if mode == "ast":
        return _todo_ast_lane_keys(todo)
    if mode == "hybrid":
        keys: List[str] = []
        for value in [*_todo_ast_lane_keys(todo), *_todo_target_file_hints(todo)]:
            if value not in keys:
                keys.append(value)
        return keys
    return _todo_target_file_hints(todo)


def _active_target_file_locks(
    queue: ModalTodoQueue,
    *,
    optimizer_role: str,
    worker_id: str,
    max_age_seconds: float,
    lock_scopes: Optional[set[str]],
    lane_lock_mode: str = "target_file",
) -> Dict[str, List[str]]:
    """Return currently claimed lanes that should block new work."""
    if max_age_seconds <= 0.0:
        return {}
    now = time.time()
    locks: Dict[str, List[str]] = {}
    for todo in queue.claimed(optimizer_role=optimizer_role):
        if str(todo.claimed_by or "") == worker_id:
            continue
        if not _target_file_lane_lock_enabled_for(todo, lock_scopes):
            continue
        if todo.claimed_at and _claimed_todo_age_seconds(todo, now=now) > max_age_seconds:
            continue
        for lane_key in _todo_lane_lock_keys(todo, mode=lane_lock_mode):
            locks.setdefault(lane_key, []).append(todo.todo_id)
    return locks


def _target_file_lane_conflicts(
    todo: ModalTodo,
    active_locks: Mapping[str, Sequence[str]],
    *,
    lane_lock_mode: str = "target_file",
) -> List[str]:
    if not active_locks:
        return []
    return sorted(set(_todo_lane_lock_keys(todo, mode=lane_lock_mode)) & set(active_locks))


def _codex_stale_bundle_lease_path(queue_path: Path) -> Path:
    return queue_path.with_suffix(queue_path.suffix + ".stale-bundle-leases.json")


def _stale_bundle_lease_key(
    *,
    args: argparse.Namespace,
    selected: Sequence[Mapping[str, Any]],
) -> str:
    anchor = selected[0].get("todo") if selected else None
    if not isinstance(anchor, ModalTodo):
        return str(getattr(args, "codex_scope", None) or "all")
    scope = str(
        getattr(args, "codex_scope", None)
        or anchor.metadata.get("program_synthesis_scope")
        or "all"
    )
    target_component = str(anchor.metadata.get("target_component") or anchor.action or "")
    semantic_key = str(anchor.metadata.get("semantic_bundle_key") or "")
    return "|".join(part for part in (scope, target_component, semantic_key) if part)


def _try_acquire_stale_bundle_lease(
    *,
    queue_path: Path,
    lease_key: str,
    worker_id: str,
    cooldown_seconds: float,
    anchor_id: str,
    selected_count: int,
) -> Dict[str, Any]:
    """Throttle stale undersized vector bundles so one lane drains at a time."""
    cooldown_seconds = max(0.0, float(cooldown_seconds))
    if cooldown_seconds <= 0.0:
        return {"acquired": True, "enabled": False}

    lease_path = _codex_stale_bundle_lease_path(queue_path)
    now = time.time()
    try:
        leases = json.loads(lease_path.read_text(encoding="utf-8")) if lease_path.exists() else {}
        if not isinstance(leases, dict):
            leases = {}
    except (OSError, json.JSONDecodeError):
        leases = {}

    pruned: Dict[str, Any] = {}
    for key, value in leases.items():
        if not isinstance(value, Mapping):
            continue
        expires_at_epoch = float(value.get("expires_at_epoch") or 0.0)
        if expires_at_epoch > now:
            pruned[str(key)] = dict(value)

    existing = pruned.get(lease_key)
    if existing and str(existing.get("worker_id") or "") != worker_id:
        return {
            "acquired": False,
            "anchor_id": str(existing.get("anchor_id") or ""),
            "enabled": True,
            "expires_at": str(existing.get("expires_at") or ""),
            "held_by": str(existing.get("worker_id") or ""),
            "key": lease_key,
            "path": str(lease_path),
            "remaining_seconds": round(float(existing.get("expires_at_epoch") or now) - now, 3),
        }

    expires_at_epoch = now + cooldown_seconds
    pruned[lease_key] = {
        "anchor_id": anchor_id,
        "expires_at": datetime.fromtimestamp(expires_at_epoch, timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "expires_at_epoch": expires_at_epoch,
        "selected_count": int(selected_count),
        "worker_id": worker_id,
    }
    try:
        lease_path.parent.mkdir(parents=True, exist_ok=True)
        lease_path.write_text(json.dumps(pruned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        return {
            "acquired": True,
            "enabled": True,
            "error": str(exc),
            "key": lease_key,
            "path": str(lease_path),
        }
    return {
        "acquired": True,
        "enabled": True,
        "expires_at": str(pruned[lease_key]["expires_at"]),
        "key": lease_key,
        "path": str(lease_path),
    }


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


@contextmanager
def codex_main_apply_lock(packet: Mapping[str, Any]) -> Iterator[None]:
    """Serialize apply/validate/commit for parallel Codex worktree packets."""
    import fcntl

    source_root_value = packet.get("source_repo_root") or packet.get("repo_root")
    if not source_root_value:
        yield
        return

    source_repo_root = Path(str(source_root_value)).resolve()
    git_dir = source_repo_root / ".git"
    lock_dir = git_dir if git_dir.is_dir() else source_repo_root
    lock_path = lock_dir / "codex-main-apply.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def row_to_sample(row: Mapping[str, Any]):
    return USCodeParquetRecord.from_row(row).to_sample()


def _row_text_within_limit(row: Mapping[str, Any], max_text_chars: int) -> bool:
    if max_text_chars <= 0:
        return True
    return len(str(row.get("text") or "")) <= max_text_chars


def _sample_one_row(
    laws_table: Any,
    rng: random.Random,
    *,
    selected_indices: set[int],
    blocked_sample_ids: AbstractSet[str] = frozenset(),
    max_sample_text_chars: int = 0,
    max_attempts: int = 5000,
) -> tuple[int, Any, int]:
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        index = rng.randrange(laws_table.num_rows)
        if index in selected_indices:
            continue
        row = laws_table.take([index]).to_pylist()[0]
        if not _row_text_within_limit(row, max_sample_text_chars):
            continue
        sample = row_to_sample(row)
        if sample.sample_id in blocked_sample_ids:
            continue
        selected_indices.add(index)
        return index, sample, attempts
    raise RuntimeError(
        "Unable to sample a U.S. Code row matching daemon sampling constraints"
    )


def sample_train_validation_rows(
    laws_table,
    rng: random.Random,
    *,
    train_count: int,
    validation_count: int,
    blocked_train_sample_ids: AbstractSet[str] = frozenset(),
    blocked_validation_sample_ids: AbstractSet[str] = frozenset(),
    max_sample_text_chars: int = 0,
):
    selected_indices: set[int] = set()
    train_indices = []
    train_samples = []
    train_sampling_attempts = 0
    max_train_attempts = max(5000, train_count * 1000)
    for _ in range(train_count):
        index, sample, attempts = _sample_one_row(
            laws_table,
            rng,
            selected_indices=selected_indices,
            blocked_sample_ids=blocked_train_sample_ids,
            max_sample_text_chars=max_sample_text_chars,
            max_attempts=max_train_attempts,
        )
        train_indices.append(index)
        train_samples.append(sample)
        train_sampling_attempts += attempts
    validation_indices = []
    validation_samples = []
    attempts = 0
    max_attempts = max(5000, validation_count * 1000)
    while len(validation_samples) < validation_count and attempts < max_attempts:
        index, sample, sample_attempts = _sample_one_row(
            laws_table,
            rng,
            selected_indices=selected_indices,
            blocked_sample_ids=blocked_validation_sample_ids,
            max_sample_text_chars=max_sample_text_chars,
            max_attempts=max_attempts - attempts,
        )
        attempts += sample_attempts
        validation_indices.append(index)
        validation_samples.append(sample)
    if len(validation_samples) < validation_count:
        raise RuntimeError(
            "Unable to sample enough validation rows without prior sample-memory exposure"
        )
    return (
        train_indices,
        train_samples,
        validation_indices,
        validation_samples,
        train_sampling_attempts + attempts,
    )


def metric_block(evaluation) -> Dict[str, Any]:
    block = {
        "cosine_loss": round(evaluation.cosine_loss, 9),
        "cosine_similarity": round(evaluation.embedding_cosine_similarity, 9),
        "cross_entropy_loss": round(evaluation.cross_entropy_loss, 9),
        "reconstruction_loss": round(evaluation.reconstruction_loss, 9),
        "sample_count": evaluation.sample_count,
        "symbolic_validity_penalty": round(evaluation.symbolic_validity_penalty, 9),
    }
    legal_ir_losses = dict(getattr(evaluation, "legal_ir_losses", {}) or {})
    if legal_ir_losses:
        block["legal_ir_losses"] = {
            name: round(float(value), 9)
            for name, value in sorted(legal_ir_losses.items())
        }
        block["legal_ir_target_count"] = int(
            getattr(evaluation, "legal_ir_target_count", 0) or 0
        )
        block["legal_ir_target_hashes"] = dict(
            sorted(dict(getattr(evaluation, "legal_ir_target_hashes", {}) or {}).items())
        )
        block["legal_ir_view_distribution"] = {
            name: round(float(value), 9)
            for name, value in sorted(
                dict(getattr(evaluation, "legal_ir_view_distribution", {}) or {}).items()
            )
        }
        block["legal_ir_predicted_view_distribution"] = {
            name: round(float(value), 9)
            for name, value in sorted(
                dict(
                    getattr(
                        evaluation,
                        "legal_ir_predicted_view_distribution",
                        {},
                    )
                    or {}
                ).items()
            )
        }
    return block


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


BRIDGE_ROUND_TRIP_METRIC_NAMES = (
    "cosine_loss",
    "cosine_similarity",
    "cross_entropy_loss",
    "flogic_similarity_loss",
    "flogic_similarity_score",
    "frame_ranking_loss",
    "reconstruction_loss",
    "symbolic_validity_penalty",
    "text_reconstruction_loss",
)


def bridge_ir_metric_block(
    samples: Sequence[Any],
    bridge_names: Sequence[str],
    *,
    evaluate_provers: Optional[bool] = None,
    parallel_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """Aggregate bridge-level compiler/prover/KG diagnostics by adapter."""

    sample_list = list(samples)
    adapter_names = [
        name
        for name in dict.fromkeys(str(name).strip() for name in bridge_names)
        if name and name.lower() not in {"none", "off", "false"}
    ]
    block: Dict[str, Any] = {
        "adapter_count": len(adapter_names),
        "adapters": {},
        "evaluated_count": 0,
        "metric_failures": 0,
        "sample_count": len(sample_list),
    }
    if not sample_list or not adapter_names:
        return block

    aggregate_values: Dict[str, List[float]] = {
        "acceptance": [],
        "graph_failure_penalty": [],
        "proof_failure_ratio": [],
        "total_loss": [],
    }
    canonical_values: Dict[str, List[float]] = {
        "acceptance_rate": [],
        "graph_failure_penalty": [],
        "proof_failure_ratio": [],
        "total_loss": [],
        "view_coverage_loss": [],
        "view_count": [],
    }
    canonical_hashes: List[str] = []
    canonical_loss_values: Dict[str, List[float]] = {}
    canonical_view_distribution_values: Dict[str, List[float]] = {}
    reports_by_adapter: Dict[str, List[Any]] = {name: [] for name in adapter_names}
    failures_by_adapter: Dict[str, int] = {name: 0 for name in adapter_names}

    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    def evaluate_sample(sample: Any) -> Any:
        cache_key = _bridge_ir_report_cache_key(
            sample,
            bridge_names=adapter_names,
            evaluate_provers=evaluate_provers,
        )
        with _BRIDGE_IR_REPORT_CACHE_LOCK:
            cached = _BRIDGE_IR_REPORT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        report = evaluate_legal_ir_multiview(
            sample.text,
            bridge_names=adapter_names,
            document_id=sample.sample_id,
            citation=sample.citation,
            evaluate_provers=evaluate_provers,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        )
        with _BRIDGE_IR_REPORT_CACHE_LOCK:
            if len(_BRIDGE_IR_REPORT_CACHE) >= BRIDGE_IR_REPORT_CACHE_MAX:
                _BRIDGE_IR_REPORT_CACHE.pop(next(iter(_BRIDGE_IR_REPORT_CACHE)), None)
            _BRIDGE_IR_REPORT_CACHE[cache_key] = report
        return report

    worker_count = _parallel_worker_count(
        requested=parallel_workers,
        item_count=len(sample_list),
    )
    if worker_count <= 1:
        multiview_reports = [evaluate_sample(sample) for sample in sample_list]
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="bridge-ir-metrics",
        ) as executor:
            multiview_reports = list(executor.map(evaluate_sample, sample_list))

    for multiview in multiview_reports:
        canonical_values["acceptance_rate"].append(multiview.acceptance_rate)
        canonical_values["graph_failure_penalty"].append(multiview.graph_failure_penalty)
        canonical_values["proof_failure_ratio"].append(multiview.proof_failure_ratio)
        canonical_values["total_loss"].append(multiview.total_loss)
        canonical_values["view_coverage_loss"].append(multiview.view_coverage_loss())
        canonical_values["view_count"].append(float(multiview.view_count))
        canonical_hashes.append(multiview.document.canonical_hash())
        training_target = multiview.training_target()
        for name, value in training_target.losses.items():
            canonical_loss_values.setdefault(name, []).append(float(value))
        for name, value in training_target.view_distribution.items():
            canonical_view_distribution_values.setdefault(name, []).append(float(value))

        for adapter_name, report in multiview.reports.items():
            reports_by_adapter.setdefault(adapter_name, []).append(report)
        for adapter_name in multiview.failures:
            failures_by_adapter[adapter_name] = failures_by_adapter.get(adapter_name, 0) + 1

    block["canonical_ir"] = {
        "acceptance_rate": _mean(canonical_values["acceptance_rate"]),
        "document_hashes": canonical_hashes[:16],
        "graph_failure_penalty": _mean(canonical_values["graph_failure_penalty"]),
        "proof_failure_ratio": _mean(canonical_values["proof_failure_ratio"]),
        "total_loss": _mean(canonical_values["total_loss"]),
        "losses": {
            name: _mean(values)
            for name, values in sorted(canonical_loss_values.items())
            if values
        },
        "view_coverage_loss": _mean(canonical_values["view_coverage_loss"]),
        "view_count": _mean(canonical_values["view_count"]),
        "view_distribution": {
            name: _mean(values)
            for name, values in sorted(canonical_view_distribution_values.items())
            if values
        },
    }

    for adapter_name in adapter_names:
        adapter_block = _adapter_metrics_from_reports(
            adapter_name=adapter_name,
            reports=reports_by_adapter.get(adapter_name, []),
            sample_count=len(sample_list),
            failure_count=failures_by_adapter.get(adapter_name, 0),
        )
        block["adapters"][adapter_name] = adapter_block
        block["evaluated_count"] += int(adapter_block.get("evaluated_count", 0))
        block["metric_failures"] += int(adapter_block.get("metric_failures", 0))
        if int(adapter_block.get("evaluated_count", 0)) > 0:
            aggregate_values["acceptance"].append(float(adapter_block.get("acceptance_rate", 0.0)))
            aggregate_values["graph_failure_penalty"].append(
                float(adapter_block.get("graph_failure_penalty", 0.0))
            )
            aggregate_values["proof_failure_ratio"].append(
                float(adapter_block.get("proof_failure_ratio", 0.0))
            )
            aggregate_values["total_loss"].append(float(adapter_block.get("total_loss", 0.0)))

    for name, values in aggregate_values.items():
        if values:
            block[name if name != "acceptance" else "acceptance_rate"] = _mean(values)
    return block


def _adapter_metrics_from_reports(
    *,
    adapter_name: str,
    reports: Sequence[Any],
    sample_count: int,
    failure_count: int,
) -> Dict[str, Any]:
    metric_values: Dict[str, List[float]] = {
        "accepted": [],
        "graph_failure_penalty": [],
        "graph_node_count": [],
        "graph_relationship_count": [],
        "proof_attempted_count": [],
        "proof_error_count": [],
        "proof_failed_count": [],
        "proof_failure_ratio": [],
        "proof_unavailable_count": [],
        "proof_valid_count": [],
        "total_loss": [],
    }
    for name in BRIDGE_ROUND_TRIP_METRIC_NAMES:
        metric_values[name] = []

    status_counts: Dict[str, int] = {}
    view_counts: Dict[str, int] = {}
    view_metadata_values: Dict[str, Dict[str, List[float]]] = {}
    target_component = ""

    for report in reports:
        target_component = target_component or str(getattr(report, "target_component", ""))
        status = str(getattr(report, "status", "unknown") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        metric_values["accepted"].append(1.0 if bool(getattr(report, "accepted", False)) else 0.0)
        metric_values["total_loss"].append(float(getattr(report, "total_loss", 0.0) or 0.0))

        proof_gate = getattr(report, "proof_gate", None)
        metric_values["proof_attempted_count"].append(
            float(getattr(proof_gate, "attempted_count", 0) or 0)
        )
        metric_values["proof_valid_count"].append(float(getattr(proof_gate, "valid_count", 0) or 0))
        metric_values["proof_unavailable_count"].append(
            float(getattr(proof_gate, "unavailable_count", 0) or 0)
        )
        metric_values["proof_error_count"].append(float(getattr(proof_gate, "error_count", 0) or 0))
        metric_values["proof_failed_count"].append(float(getattr(proof_gate, "failed_count", 0) or 0))
        metric_values["proof_failure_ratio"].append(float(getattr(proof_gate, "failure_ratio", 0.0) or 0.0))

        graph_projection = getattr(report, "graph_projection", None)
        metric_values["graph_failure_penalty"].append(
            float(getattr(graph_projection, "graph_failure_penalty", 0.0) or 0.0)
        )
        metric_values["graph_node_count"].append(float(getattr(graph_projection, "node_count", 0) or 0))
        metric_values["graph_relationship_count"].append(
            float(getattr(graph_projection, "relationship_count", 0) or 0)
        )

        round_trip = getattr(report, "round_trip", None)
        for name in BRIDGE_ROUND_TRIP_METRIC_NAMES:
            metric_values[name].append(float(getattr(round_trip, name, 0.0) or 0.0))
        for name, value in dict(getattr(round_trip, "extra_losses", {}) or {}).items():
            metric_values.setdefault(str(name), []).append(_float_or_zero(value))

        ir_document = getattr(report, "ir_document", None)
        views = dict(getattr(ir_document, "views", {}) or {})
        for view_name, view in views.items():
            view_counts[str(view_name)] = view_counts.get(str(view_name), 0) + 1
            metadata_bucket = view_metadata_values.setdefault(str(view_name), {})
            for key, value in dict(getattr(view, "metadata", {}) or {}).items():
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    metadata_bucket.setdefault(str(key), []).append(float(value))

    evaluated_count = len(reports)
    adapter_block: Dict[str, Any] = {
        "adapter_name": adapter_name,
        "evaluated_count": evaluated_count,
        "metric_failures": failure_count,
        "sample_count": sample_count,
        "status_counts": dict(sorted(status_counts.items())),
        "target_component": target_component,
    }
    if evaluated_count > 0:
        adapter_block["accepted_count"] = int(round(sum(metric_values["accepted"])))
        adapter_block["acceptance_rate"] = _mean(metric_values["accepted"])
        for name, values in sorted(metric_values.items()):
            if name == "accepted" or not values:
                continue
            adapter_block[name] = _mean(values)
        adapter_block["views"] = {
            view_name: {
                "metadata": {
                    key: _mean(values)
                    for key, values in sorted(metadata.items())
                    if values
                },
                "present_count": count,
                "present_rate": round(count / evaluated_count, 9),
            }
            for view_name, count in sorted(view_counts.items())
            for metadata in [view_metadata_values.get(view_name, {})]
        }
    return adapter_block


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(float(value) for value in values) / len(values), 9)


def _parallel_worker_count(
    *,
    requested: Optional[int],
    item_count: int,
) -> int:
    if item_count <= 1:
        return 1
    if requested is None:
        raw = os.environ.get("IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS", "").strip()
        if not raw:
            return 1
        try:
            requested = int(raw)
        except ValueError:
            return 1
    return max(1, min(int(requested), int(item_count)))


def _bridge_ir_report_cache_key(
    sample: Any,
    *,
    bridge_names: Sequence[str],
    evaluate_provers: Optional[bool],
) -> str:
    """Return a stable key for cached bridge/prover/KG diagnostics."""
    embedding = [
        round(float(value), 12)
        for value in list(getattr(sample, "embedding_vector", []) or [])
    ]
    embedding_hash = hashlib.sha256(
        json.dumps(embedding, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "bridge_names": list(bridge_names),
        "citation": str(getattr(sample, "citation", "") or ""),
        "embedding_hash": embedding_hash,
        "evaluate_provers": evaluate_provers,
        "sample_id": str(getattr(sample, "sample_id", "") or ""),
        "source": str(getattr(sample, "source", "") or ""),
        "text_hash": hashlib.sha256(
            str(getattr(sample, "text", "") or "").encode("utf-8")
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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


def bridge_loss_adapter_names(args: argparse.Namespace) -> List[str]:
    """Return bridge adapters that should feed optimizer loss TODOs."""

    raw = str(
        getattr(args, "bridge_loss_adapters", DEFAULT_BRIDGE_LOSS_ADAPTERS) or ""
    ).strip()
    if raw.lower() in {"", "none", "off", "false"}:
        return []
    return [
        name
        for name in (part.strip() for part in raw.split(","))
        if name and name.lower() not in {"none", "off", "false"}
    ]


def parse_bool_flag(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean flag, got {value!r}")


def codex_loop_execution_mode(args: argparse.Namespace) -> str:
    if getattr(args, "codex_exec_mode", "packet_only") == "codex_cli":
        return "codex_cli_executor"
    return "queued_for_external_codex_worker"


def _codex_vector_index_path(args: argparse.Namespace, queue_path: Path) -> Path:
    configured = str(getattr(args, "codex_vector_index_path", "") or "").strip()
    if configured:
        return Path(configured)
    return queue_path.with_name(f"{queue_path.stem}.codex-task-vectors.json")


def _program_synthesis_queue_todos(
    queue: ModalTodoQueue,
    *,
    optimizer_role: str,
) -> List[ModalTodo]:
    return [
        todo
        for todo in queue.all()
        if str(todo.metadata.get("optimizer_role") or "").strip() == optimizer_role
    ]


def _codex_scope_filter(scope: Optional[str]) -> Optional[Dict[str, str]]:
    if not scope:
        return None
    return {"program_synthesis_scope": str(scope)}


def _metadata_matches(todo: ModalTodo, metadata_filter: Optional[Mapping[str, str]]) -> bool:
    if not metadata_filter:
        return True
    return all(str(todo.metadata.get(key) or "") == str(value) for key, value in metadata_filter.items())


def _codex_task_fingerprint(todo: ModalTodo) -> str:
    return hashlib.sha256(
        program_synthesis_todo_embedding_text(todo).encode("utf-8")
    ).hexdigest()


def _coerce_embedding_vector(value: Any) -> List[float]:
    if value is None:
        return []
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError):
        return []
    return vector if vector else []


def _hashed_embedding_texts(texts: Sequence[str], *, dimension: int = 128) -> List[List[float]]:
    vectors: List[List[float]] = []
    for text in texts:
        vector = [0.0] * int(dimension)
        tokens = [
            token.strip("`'\".,;:()[]{}<>").lower()
            for token in str(text or "").replace("\n", " ").split()
        ]
        for token in tokens:
            if not token:
                continue
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % len(vector)
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = sum(value * value for value in vector) ** 0.5
        if norm:
            vector = [value / norm for value in vector]
        vectors.append(vector)
    return vectors


def _router_codex_task_embeddings(
    texts: Sequence[str],
    *,
    args: argparse.Namespace,
) -> List[List[float]]:
    from ipfs_datasets_py import embeddings_router

    provider = str(getattr(args, "codex_task_embeddings_provider", "local_adapter") or "").strip()
    provider_arg = None if provider.lower() == "auto" else provider
    model = str(getattr(args, "codex_task_embeddings_model", "") or "").strip() or None
    device = str(getattr(args, "codex_task_embeddings_device", "") or "").strip() or None
    batch_size = max(1, int(getattr(args, "codex_task_embeddings_batch_size", 32) or 32))
    return embeddings_router.embed_texts_batched(
        list(texts),
        batch_size=batch_size,
        model_name=model,
        device=device,
        provider=provider_arg,
    )


def _load_codex_task_vector_index(index_path: Path) -> Dict[str, Any]:
    if not index_path.exists():
        return {"items": {}, "version": 1}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": {}, "version": 1}
    if not isinstance(payload, dict):
        return {"items": {}, "version": 1}
    items = payload.get("items")
    if not isinstance(items, dict):
        payload["items"] = {}
    return payload


def _save_codex_task_vector_index(index_path: Path, payload: Mapping[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _update_codex_task_vector_index(
    *,
    args: argparse.Namespace,
    index_path: Path,
    todos: Sequence[ModalTodo],
) -> tuple[Dict[str, List[float]], Dict[str, Any]]:
    """Update the persistent Codex TODO vector index and return vectors by id."""
    todos_by_id = {todo.todo_id: todo for todo in todos}
    missing: List[ModalTodo] = []

    with queue_file_lock(index_path):
        payload = _load_codex_task_vector_index(index_path)
        existing_items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
        for todo_id, todo in sorted(todos_by_id.items()):
            fingerprint = _codex_task_fingerprint(todo)
            existing = existing_items.get(todo_id) if isinstance(existing_items, dict) else None
            vector = (
                _coerce_embedding_vector(existing.get("vector"))
                if isinstance(existing, Mapping)
                and str(existing.get("fingerprint") or "") == fingerprint
                else []
            )
            if not vector:
                missing.append(todo)

    backend = "embeddings_router" if missing else str(payload.get("backend") or "embeddings_router")
    fallback_reason = ""
    refreshed = 0
    generated_items: Dict[str, Dict[str, Any]] = {}
    if missing:
        texts = [program_synthesis_todo_embedding_text(todo) for todo in missing]
        try:
            vectors = _router_codex_task_embeddings(texts, args=args)
        except Exception as exc:
            fallback_reason = str(exc)
            fallback_mode = str(getattr(args, "codex_vector_fallback_mode", "hash") or "hash")
            if fallback_mode == "priority":
                vectors = []
                backend = "priority_fallback"
            else:
                vectors = _hashed_embedding_texts(texts)
                backend = "local_hash_fallback"
        refreshed = len(vectors)
        for todo, vector in zip(missing, vectors):
            coerced = _coerce_embedding_vector(vector)
            if not coerced:
                continue
            generated_items[todo.todo_id] = {
                "fingerprint": _codex_task_fingerprint(todo),
                "status": todo.status,
                "vector": coerced,
            }

    with queue_file_lock(index_path):
        latest_payload = _load_codex_task_vector_index(index_path)
        latest_items = latest_payload.get("items") if isinstance(latest_payload.get("items"), dict) else {}
        items: Dict[str, Dict[str, Any]] = {}
        for todo_id, todo in sorted(todos_by_id.items()):
            fingerprint = _codex_task_fingerprint(todo)
            existing = latest_items.get(todo_id) if isinstance(latest_items, dict) else None
            vector = (
                _coerce_embedding_vector(existing.get("vector"))
                if isinstance(existing, Mapping)
                and str(existing.get("fingerprint") or "") == fingerprint
                else []
            )
            if vector:
                items[todo_id] = {
                    "fingerprint": fingerprint,
                    "status": todo.status,
                    "vector": vector,
                }
            elif todo_id in generated_items:
                items[todo_id] = dict(generated_items[todo_id])

        output = {
            "backend": backend,
            "fallback_reason": fallback_reason,
            "indexed_count": len(items),
            "items": items,
            "model": str(getattr(args, "codex_task_embeddings_model", "") or ""),
            "provider": str(getattr(args, "codex_task_embeddings_provider", "local_adapter") or ""),
            "refreshed_count": refreshed,
            "updated_at": utc_now(),
            "version": 1,
        }
        _save_codex_task_vector_index(index_path, output)
    vectors_by_id = {
        todo_id: list(data["vector"])
        for todo_id, data in items.items()
        if isinstance(data, Mapping) and _coerce_embedding_vector(data.get("vector"))
    }
    report = {
        "backend": backend,
        "fallback_reason": fallback_reason,
        "indexed_count": len(items),
        "path": str(index_path),
        "provider": output["provider"],
        "refreshed_count": refreshed,
    }
    return vectors_by_id, report


def _claim_vector_program_synthesis_batch(
    *,
    args: argparse.Namespace,
    queue_path: Path,
    worker_id: str,
    policy: ModalOptimizerPolicy,
    execution_mode: str,
    summary: Dict[str, Any],
) -> tuple[List[ModalTodo], ModalTodoQueue, Dict[str, Any], Dict[str, Any]]:
    """Claim a vector-nearest Codex bundle without holding the queue lock while embedding."""
    metadata_filter = _codex_scope_filter(getattr(args, "codex_scope", None))
    with queue_file_lock(queue_path):
        snapshot_queue = ModalTodoQueue.load_jsonl(queue_path)
        raw_candidates = [
            todo
            for todo in snapshot_queue.pending(optimizer_role=policy.program_synthesis_role)
            if _metadata_matches(todo, metadata_filter)
        ]
        target_lane_lock_seconds = max(
            0.0,
            float(getattr(args, "codex_target_file_lane_lock_seconds", 0.0) or 0.0),
        )
        target_lane_lock_scopes = _codex_target_file_lane_lock_scopes(args)
        lane_lock_mode = _codex_lane_lock_mode(args)
        active_target_locks = _active_target_file_locks(
            snapshot_queue,
            optimizer_role=policy.program_synthesis_role,
            worker_id=worker_id,
            max_age_seconds=target_lane_lock_seconds,
            lock_scopes=target_lane_lock_scopes,
            lane_lock_mode=lane_lock_mode,
        )
        candidates = [
            todo
            for todo in raw_candidates
            if not (
                _target_file_lane_lock_enabled_for(todo, target_lane_lock_scopes)
                and _target_file_lane_conflicts(
                    todo,
                    active_target_locks,
                    lane_lock_mode=lane_lock_mode,
                )
            )
        ]
        all_program_todos = _program_synthesis_queue_todos(
            snapshot_queue,
            optimizer_role=policy.program_synthesis_role,
        )

    vector_report: Dict[str, Any] = {
        "active_target_file_lane_count": len(active_target_locks),
        "available_candidate_count": len(candidates),
        "candidate_count": len(raw_candidates),
        "max_bundle_wait_seconds": max(
            0.0,
            float(getattr(args, "codex_vector_max_bundle_wait_seconds", 0.0) or 0.0),
        ),
        "min_bundle_size": max(
            1,
            int(getattr(args, "codex_vector_min_bundle_size", 1) or 1),
        ),
        "mode": "vector",
        "oldest_candidate_age_seconds": round(_oldest_todo_age_seconds(candidates), 3),
        "selected_count": 0,
        "target_file_lane_lock_mode": lane_lock_mode,
        "target_file_lane_lock_seconds": target_lane_lock_seconds,
        "target_file_lane_lock_scopes": (
            "all" if target_lane_lock_scopes is None else sorted(target_lane_lock_scopes)
        ),
        "target_file_lane_locked_count": len(raw_candidates) - len(candidates),
    }
    if not candidates:
        with queue_file_lock(queue_path):
            queue = ModalTodoQueue.load_jsonl(queue_path)
            status = update_program_synthesis_summary(
                summary,
                queue,
                policy,
                execution_mode=execution_mode,
            )
        if raw_candidates:
            vector_report["mode"] = "vector_target_file_lanes_busy"
            vector_report["wait_reason"] = "all scope candidates overlap active target-file lanes"
        return [], queue, status, vector_report

    index_path = _codex_vector_index_path(args, queue_path)
    vectors_by_id, index_report = _update_codex_task_vector_index(
        args=args,
        index_path=index_path,
        todos=all_program_todos,
    )
    vector_report.update(index_report)

    if not vectors_by_id:
        with queue_file_lock(queue_path):
            queue = ModalTodoQueue.load_jsonl(queue_path)
            supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
            claimed = supervisor.claim_program_synthesis_batch(
                worker_id=worker_id,
                max_items=args.max_items,
                program_synthesis_scope=getattr(args, "codex_scope", None),
                semantic_bundle=False,
            )
            if claimed:
                queue.save_jsonl(queue_path)
            status = update_program_synthesis_summary(
                summary,
                queue,
                policy,
                execution_mode=execution_mode,
            )
        vector_report["mode"] = "priority_fallback"
        vector_report["selected_count"] = len(claimed)
        return claimed, queue, status, vector_report

    selected = select_program_synthesis_vector_bundle(
        candidates,
        vectors_by_todo_id=vectors_by_id,
        max_items=args.max_items,
        min_similarity=float(getattr(args, "codex_vector_min_similarity", 0.72)),
        fill_min_similarity=getattr(args, "codex_vector_fill_min_similarity", None),
    )
    skipped_fresh_undersized_anchor_ids: List[str] = []
    min_bundle_size = int(vector_report["min_bundle_size"])
    max_bundle_wait_seconds = float(vector_report["max_bundle_wait_seconds"])
    oldest_candidate_age_seconds = float(vector_report["oldest_candidate_age_seconds"])
    if (
        selected
        and len(selected) < min_bundle_size
        and max_bundle_wait_seconds > 0.0
        and oldest_candidate_age_seconds < max_bundle_wait_seconds
    ):
        skipped_ids = {str(selected[0]["todo"].todo_id)}
        skipped_fresh_undersized_anchor_ids.append(str(selected[0]["todo"].todo_id))
        while True:
            alternate_candidates = [
                todo for todo in candidates if str(todo.todo_id) not in skipped_ids
            ]
            alternate_selected = select_program_synthesis_vector_bundle(
                alternate_candidates,
                vectors_by_todo_id=vectors_by_id,
                max_items=args.max_items,
                min_similarity=float(getattr(args, "codex_vector_min_similarity", 0.72)),
                fill_min_similarity=getattr(args, "codex_vector_fill_min_similarity", None),
            )
            if not alternate_selected:
                break
            if len(alternate_selected) >= min_bundle_size:
                selected = alternate_selected
                vector_report["mode"] = "vector_skipped_fresh_undersized_anchor"
                break
            alternate_anchor_id = str(alternate_selected[0]["todo"].todo_id)
            if alternate_anchor_id in skipped_ids:
                break
            skipped_ids.add(alternate_anchor_id)
            skipped_fresh_undersized_anchor_ids.append(alternate_anchor_id)

    selected_ids = [str(item["todo"].todo_id) for item in selected]
    similarity_by_id = {
        str(item["todo"].todo_id): float(item["similarity"])
        for item in selected
    }
    fill_reason_by_id = {
        str(item["todo"].todo_id): str(item.get("fill_reason") or "")
        for item in selected
        if item.get("fill_reason")
    }
    anchor_id = selected_ids[0] if selected_ids else ""
    if skipped_fresh_undersized_anchor_ids:
        vector_report["skipped_fresh_undersized_anchor_ids"] = (
            skipped_fresh_undersized_anchor_ids
        )
    undersized_stale_bundle = (
        bool(selected)
        and len(selected) < min_bundle_size
        and max_bundle_wait_seconds > 0.0
        and oldest_candidate_age_seconds >= max_bundle_wait_seconds
    )
    if (
        selected
        and len(selected) < min_bundle_size
        and max_bundle_wait_seconds > 0.0
        and oldest_candidate_age_seconds < max_bundle_wait_seconds
    ):
        with queue_file_lock(queue_path):
            queue = ModalTodoQueue.load_jsonl(queue_path)
            status = update_program_synthesis_summary(
                summary,
                queue,
                policy,
                execution_mode=execution_mode,
            )
        vector_report.update(
            {
                "anchor_id": anchor_id,
                "mode": "vector_waiting_for_bundle",
                "proposed_selected_count": len(selected),
                "proposed_selected_ids": selected_ids,
                "selected_count": 0,
                "wait_reason": "selected bundle below minimum and oldest candidate is still fresh",
            }
        )
        return [], queue, status, vector_report

    with queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
        if undersized_stale_bundle:
            lease_report = _try_acquire_stale_bundle_lease(
                queue_path=queue_path,
                lease_key=_stale_bundle_lease_key(args=args, selected=selected),
                worker_id=worker_id,
                cooldown_seconds=float(
                    getattr(args, "codex_vector_stale_drain_cooldown_seconds", 0.0) or 0.0
                ),
                anchor_id=anchor_id,
                selected_count=len(selected),
            )
            vector_report["stale_drain_lease"] = dict(lease_report)
            if not lease_report.get("acquired", False):
                status = update_program_synthesis_summary(
                    summary,
                    queue,
                    policy,
                    execution_mode=execution_mode,
                )
                vector_report.update(
                    {
                        "anchor_id": anchor_id,
                        "mode": "vector_waiting_for_stale_drain_lease",
                        "proposed_selected_count": len(selected),
                        "proposed_selected_ids": selected_ids,
                        "selected_count": 0,
                        "wait_reason": "another worker is draining a stale undersized bundle in this lane",
                    }
                )
                return [], queue, status, vector_report
        claimed = queue.claim_todo_ids(
            worker_id=worker_id,
            todo_ids=selected_ids,
            optimizer_role=policy.program_synthesis_role,
            metadata_filter=metadata_filter,
        )
        for todo in claimed:
            todo.metadata["vector_bundle_anchor_id"] = anchor_id
            todo.metadata["vector_bundle_similarity"] = round(
                similarity_by_id.get(todo.todo_id, 0.0),
                6,
            )
            if fill_reason_by_id.get(todo.todo_id):
                todo.metadata["vector_bundle_fill_reason"] = fill_reason_by_id[todo.todo_id]
            todo.metadata["vector_bundle_index_path"] = str(index_path)
            todo.metadata["vector_bundle_backend"] = str(vector_report.get("backend") or "")
        if claimed:
            queue.save_jsonl(queue_path)
        status = update_program_synthesis_summary(
            summary,
            queue,
            policy,
            execution_mode=execution_mode,
        )

    vector_report["anchor_id"] = anchor_id
    vector_report["selected_count"] = len(claimed)
    vector_report["selected_ids"] = [todo.todo_id for todo in claimed]
    vector_report["fill_selected_count"] = sum(
        1 for todo in claimed if todo.metadata.get("vector_bundle_fill_reason")
    )
    vector_report["fill_min_similarity"] = getattr(
        args,
        "codex_vector_fill_min_similarity",
        None,
    )
    vector_report["min_similarity"] = float(getattr(args, "codex_vector_min_similarity", 0.72))
    return claimed, queue, status, vector_report


def _codex_parallel_scope_values(args: argparse.Namespace) -> List[str]:
    raw = str(getattr(args, "codex_parallel_scopes", "") or "").strip()
    if not raw:
        return []
    if raw.lower() == "all":
        return list(CODEX_AST_SCOPES)
    scopes = [scope.strip() for scope in raw.split(",") if scope.strip()]
    invalid = [scope for scope in scopes if scope not in CODEX_AST_SCOPES]
    if invalid:
        raise ValueError(
            "unknown codex parallel scope(s): "
            + ", ".join(invalid)
            + "; expected one of "
            + ", ".join(CODEX_AST_SCOPES)
        )
    return list(dict.fromkeys(scopes))


def _codex_scope_worker_overrides(args: argparse.Namespace) -> Dict[str, int]:
    raw = str(getattr(args, "codex_scope_worker_map", "") or "").strip()
    if not raw:
        return {}
    overrides: Dict[str, int] = {}
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError("codex scope worker map entries must use scope=count")
        scope, count = [part.strip() for part in item.split("=", 1)]
        if scope not in CODEX_AST_SCOPES:
            raise ValueError(
                f"unknown codex scope worker map scope: {scope}; expected one of "
                + ", ".join(CODEX_AST_SCOPES)
            )
        overrides[scope] = max(0, int(count))
    return overrides


def _build_codex_child_command(
    args: argparse.Namespace,
    *,
    child_run_id: str,
    codex_duration_seconds: float,
    module_name: str,
    queue_run_id: str,
    scope: Optional[str],
    worker_id: Optional[str],
) -> List[str]:
    command = [
        sys.executable,
        "-m",
        module_name,
        "--loop-role",
        "codex",
        "--run-id",
        child_run_id,
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
        "--codex-bundle-mode",
        str(getattr(args, "codex_bundle_mode", "semantic")),
        "--codex-vector-min-similarity",
        str(getattr(args, "codex_vector_min_similarity", 0.72)),
        "--codex-vector-fill-min-similarity",
        str(getattr(args, "codex_vector_fill_min_similarity", 0.45)),
        "--codex-vector-min-bundle-size",
        str(getattr(args, "codex_vector_min_bundle_size", 1)),
        "--codex-vector-max-bundle-wait-seconds",
        str(getattr(args, "codex_vector_max_bundle_wait_seconds", 0.0)),
        "--codex-vector-stale-drain-cooldown-seconds",
        str(getattr(args, "codex_vector_stale_drain_cooldown_seconds", 0.0)),
        "--codex-target-file-lane-lock-seconds",
        str(getattr(args, "codex_target_file_lane_lock_seconds", 0.0)),
        "--codex-target-file-lane-lock-scopes",
        str(getattr(args, "codex_target_file_lane_lock_scopes", "compiler_registry")),
        "--codex-lane-lock-mode",
        str(getattr(args, "codex_lane_lock_mode", "target_file")),
        "--codex-task-embeddings-provider",
        str(getattr(args, "codex_task_embeddings_provider", "local_adapter")),
        "--codex-task-embeddings-batch-size",
        str(getattr(args, "codex_task_embeddings_batch_size", 32)),
        "--codex-vector-fallback-mode",
        str(getattr(args, "codex_vector_fallback_mode", "hash")),
        "--codex-merge-repair-mode",
        str(getattr(args, "codex_merge_repair_mode", "apply_3way")),
        "--codex-merge-repair-attempts",
        str(getattr(args, "codex_merge_repair_attempts", 1)),
    ]
    if getattr(args, "codex_vector_index_path", None):
        command.extend(["--codex-vector-index-path", str(args.codex_vector_index_path)])
    if getattr(args, "codex_task_embeddings_model", None):
        command.extend(["--codex-task-embeddings-model", str(args.codex_task_embeddings_model)])
    if getattr(args, "codex_task_embeddings_device", None):
        command.extend(["--codex-task-embeddings-device", str(args.codex_task_embeddings_device)])
    if scope:
        command.extend(["--codex-scope", str(scope)])
    if worker_id:
        command.extend(["--worker-id", str(worker_id)])
    if getattr(args, "codex_model", None):
        command.extend(["--codex-model", str(args.codex_model)])
    return command


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
        "--validation-canary-count",
        str(getattr(args, "validation_canary_count", 4)),
        "--max-sample-text-chars",
        str(getattr(args, "max_sample_text_chars", 0)),
        "--max-inner-iterations",
        str(args.max_inner_iterations),
        "--max-items",
        str(args.max_items),
        "--learning-rate",
        str(args.learning_rate),
        "--generalizable-projection-epochs",
        str(getattr(args, "generalizable_projection_epochs", 1)),
        "--bridge-loss-adapters",
        str(getattr(args, "bridge_loss_adapters", DEFAULT_BRIDGE_LOSS_ADAPTERS)),
        "--bridge-evaluate-provers",
        str(getattr(args, "bridge_evaluate_provers", True)).lower(),
        "--autoencoder-device",
        str(getattr(args, "autoencoder_device", "auto")),
        "--autoencoder-feature-family-logit-scale",
        str(getattr(args, "autoencoder_feature_family_logit_scale", 1.0)),
        "--autoencoder-feature-embedding-weight-scale",
        str(getattr(args, "autoencoder_feature_embedding_weight_scale", 0.5)),
        "--autoencoder-compiler-quality-embedding-weight-scale",
        str(getattr(args, "autoencoder_compiler_quality_embedding_weight_scale", 0.5)),
        "--autoencoder-compiler-quality-family-logit-scale",
        str(getattr(args, "autoencoder_compiler_quality_family_logit_scale", 1.0)),
        "--autoencoder-logic-signature-embedding-weight-scale",
        str(getattr(args, "autoencoder_logic_signature_embedding_weight_scale", 0.5)),
        "--autoencoder-logic-signature-family-logit-scale",
        str(getattr(args, "autoencoder_logic_signature_family_logit_scale", 1.0)),
        "--autoencoder-logic-signature-legal-ir-view-logit-scale",
        str(getattr(args, "autoencoder_logic_signature_legal_ir_view_logit_scale", 1.0)),
        "--autoencoder-round-trip-signal-embedding-weight-scale",
        str(getattr(args, "autoencoder_round_trip_signal_embedding_weight_scale", 0.5)),
        "--autoencoder-round-trip-signal-family-logit-scale",
        str(getattr(args, "autoencoder_round_trip_signal_family_logit_scale", 1.0)),
        "--autoencoder-round-trip-signal-legal-ir-view-logit-scale",
        str(getattr(args, "autoencoder_round_trip_signal_legal_ir_view_logit_scale", 1.0)),
        "--autoencoder-decompiler-plan-embedding-weight-scale",
        str(getattr(args, "autoencoder_decompiler_plan_embedding_weight_scale", 0.5)),
        "--autoencoder-decompiler-plan-family-logit-scale",
        str(getattr(args, "autoencoder_decompiler_plan_family_logit_scale", 1.0)),
        "--autoencoder-decompiler-plan-legal-ir-view-logit-scale",
        str(getattr(args, "autoencoder_decompiler_plan_legal_ir_view_logit_scale", 1.0)),
        "--autoencoder-predicate-argument-embedding-weight-scale",
        str(getattr(args, "autoencoder_predicate_argument_embedding_weight_scale", 0.5)),
        "--autoencoder-predicate-argument-family-logit-scale",
        str(getattr(args, "autoencoder_predicate_argument_family_logit_scale", 1.0)),
        "--autoencoder-predicate-argument-legal-ir-view-logit-scale",
        str(getattr(args, "autoencoder_predicate_argument_legal_ir_view_logit_scale", 1.0)),
        "--autoencoder-max-compiler-latent-profile-features",
        str(getattr(args, "autoencoder_max_compiler_latent_profile_features", 48)),
        "--autoencoder-max-round-trip-bridge-features",
        str(getattr(args, "autoencoder_max_round_trip_bridge_features", 64)),
        "--autoencoder-max-clause-topology-features",
        str(getattr(args, "autoencoder_max_clause_topology_features", 64)),
        "--autoencoder-embedding-head-update-normalization",
        str(getattr(args, "autoencoder_embedding_head_update_normalization", 0.5)),
        "--autoencoder-family-logit-head-update-normalization",
        str(getattr(args, "autoencoder_family_logit_head_update_normalization", 0.5)),
        "--autoencoder-legal-ir-view-head-update-normalization",
        str(getattr(args, "autoencoder_legal_ir_view_head_update_normalization", 0.5)),
        "--autoencoder-family-embedding-weight-scale",
        str(getattr(args, "autoencoder_family_embedding_weight_scale", 0.5)),
        "--autoencoder-family-semantic-slot-embedding-weight-scale",
        str(getattr(args, "autoencoder_family_semantic_slot_embedding_weight_scale", 0.5)),
        "--autoencoder-family-semantic-slot-legal-ir-view-embedding-weight-scale",
        str(getattr(args, "autoencoder_family_semantic_slot_legal_ir_view_embedding_weight_scale", 0.5)),
        "--autoencoder-family-legal-ir-view-embedding-weight-scale",
        str(getattr(args, "autoencoder_family_legal_ir_view_embedding_weight_scale", 0.5)),
        "--autoencoder-semantic-slot-family-logit-scale",
        str(getattr(args, "autoencoder_semantic_slot_family_logit_scale", 1.0)),
        "--autoencoder-legal-ir-view-family-logit-scale",
        str(getattr(args, "autoencoder_legal_ir_view_family_logit_scale", 1.0)),
        "--autoencoder-family-semantic-slot-legal-ir-view-logit-scale",
        str(getattr(args, "autoencoder_family_semantic_slot_legal_ir_view_logit_scale", 1.0)),
        "--autoencoder-semantic-slot-legal-ir-view-family-logit-scale",
        str(getattr(args, "autoencoder_semantic_slot_legal_ir_view_family_logit_scale", 1.0)),
        "--autoencoder-semantic-slot-embedding-weight-scale",
        str(getattr(args, "autoencoder_semantic_slot_embedding_weight_scale", 0.5)),
        "--autoencoder-semantic-slot-interaction-weight",
        str(getattr(args, "autoencoder_semantic_slot_interaction_weight", 0.35)),
        "--autoencoder-max-semantic-slot-interactions",
        str(getattr(args, "autoencoder_max_semantic_slot_interactions", 24)),
        "--autoencoder-semantic-slot-legal-ir-view-logit-scale",
        str(getattr(args, "autoencoder_semantic_slot_legal_ir_view_logit_scale", 1.0)),
        "--autoencoder-legal-ir-view-logit-scale",
        str(getattr(args, "autoencoder_legal_ir_view_logit_scale", 1.0)),
        "--autoencoder-legal-ir-view-embedding-weight-scale",
        str(getattr(args, "autoencoder_legal_ir_view_embedding_weight_scale", 0.5)),
        "--autoencoder-semantic-slot-legal-ir-view-embedding-weight-scale",
        str(getattr(args, "autoencoder_semantic_slot_legal_ir_view_embedding_weight_scale", 0.5)),
        "--autoencoder-cosine-reconstruction-weight",
        str(getattr(args, "autoencoder_cosine_reconstruction_weight", 0.25)),
        "--autoencoder-max-token-features",
        str(getattr(args, "autoencoder_max_token_features", 48)),
        "--autoencoder-max-token-bigram-features",
        str(getattr(args, "autoencoder_max_token_bigram_features", 24)),
        "--autoencoder-max-token-trigram-features",
        str(getattr(args, "autoencoder_max_token_trigram_features", 12)),
        "--autoencoder-max-legal-ir-token-features",
        str(getattr(args, "autoencoder_max_legal_ir_token_features", 24)),
        "--autoencoder-max-legal-ir-token-bigram-features",
        str(getattr(args, "autoencoder_max_legal_ir_token_bigram_features", 12)),
        "--autoencoder-max-legal-ir-token-trigram-features",
        str(getattr(args, "autoencoder_max_legal_ir_token_trigram_features", 8)),
        "--autoencoder-feature-activity-reference",
        str(getattr(args, "autoencoder_feature_activity_reference", 64)),
        "--autoencoder-feature-logit-clip",
        str(getattr(args, "autoencoder_feature_logit_clip", 24.0)),
        "--generalizable-projection-max-cosine-regression",
        str(getattr(args, "generalizable_projection_max_cosine_regression", 0.005)),
        "--generalizable-projection-max-reconstruction-regression",
        str(getattr(args, "generalizable_projection_max_reconstruction_regression", 0.01)),
        "--generalizable-projection-max-cross-entropy-regression",
        str(getattr(args, "generalizable_projection_max_cross_entropy_regression", 0.0)),
        "--generalizable-projection-max-legal-ir-loss-regression",
        str(getattr(args, "generalizable_projection_max_legal_ir_loss_regression", 0.01)),
        "--generalizable-projection-objective-cross-entropy-weight",
        str(getattr(args, "generalizable_projection_objective_cross_entropy_weight", 1.0)),
        "--generalizable-projection-objective-reconstruction-weight",
        str(getattr(args, "generalizable_projection_objective_reconstruction_weight", 1.0)),
        "--generalizable-projection-objective-cosine-gap-weight",
        str(getattr(args, "generalizable_projection_objective_cosine_gap_weight", 1.0)),
        "--generalizable-projection-objective-legal-ir-weight",
        str(getattr(args, "generalizable_projection_objective_legal_ir_weight", 1.0)),
        "--generalizable-projection-hard-example-fraction",
        str(getattr(args, "generalizable_projection_hard_example_fraction", 1.0)),
        "--learning-rate-floor-ratio",
        str(getattr(args, "learning_rate_floor_ratio", 0.25)),
        "--learning-rate-cap-ratio",
        str(getattr(args, "learning_rate_cap_ratio", 1.5)),
        "--learning-rate-plateau-delta",
        str(getattr(args, "learning_rate_plateau_delta", 1.0e-5)),
        "--autoencoder-bridge-workers",
        str(getattr(args, "autoencoder_bridge_workers", 1)),
        "--test-every-cycles",
        str(args.test_every_cycles),
    ]
    for warm_start_run_id in getattr(args, "warm_start_run_id", []):
        autoencoder_command.extend(["--warm-start-run-id", str(warm_start_run_id)])
    for warm_start_state in getattr(args, "warm_start_state", []):
        autoencoder_command.extend(["--warm-start-state", str(warm_start_state)])

    parallel_scopes = _codex_parallel_scope_values(args)
    if parallel_scopes:
        codex_children = []
        scope_workers = max(1, int(getattr(args, "codex_scope_workers", 1) or 1))
        worker_overrides = _codex_scope_worker_overrides(args)
        for scope in parallel_scopes:
            scope_worker_count = worker_overrides.get(scope, scope_workers)
            if scope_worker_count < 1:
                continue
            for worker_index in range(1, scope_worker_count + 1):
                worker_suffix = (
                    scope if scope_worker_count == 1 else f"{scope}-{worker_index:02d}"
                )
                child_run_id = f"{codex_run_id}-{worker_suffix}"
                child_worker_id = (
                    f"{args.worker_id}-{worker_suffix}"
                    if getattr(args, "worker_id", None)
                    else f"codex-{worker_suffix}"
                )
                codex_children.append(
                    {
                        "command": _build_codex_child_command(
                            args,
                            child_run_id=child_run_id,
                            codex_duration_seconds=codex_duration_seconds,
                            module_name=module_name,
                            queue_run_id=queue_run_id,
                            scope=scope,
                            worker_id=child_worker_id,
                        ),
                        "run_id": child_run_id,
                        "scope": scope,
                        "worker_id": child_worker_id,
                    }
                )
    else:
        codex_children = [
            {
                "command": _build_codex_child_command(
                    args,
                    child_run_id=codex_run_id,
                    codex_duration_seconds=codex_duration_seconds,
                    module_name=module_name,
                    queue_run_id=queue_run_id,
                    scope=getattr(args, "codex_scope", None),
                    worker_id=getattr(args, "worker_id", None),
                ),
                "run_id": codex_run_id,
                "scope": getattr(args, "codex_scope", None),
                "worker_id": getattr(args, "worker_id", None),
            }
        ]
    codex_command = list(codex_children[0]["command"])

    return {
        "autoencoder_run_id": autoencoder_run_id,
        "codex_run_id": codex_run_id,
        "queue_run_id": queue_run_id,
        "autoencoder_command": autoencoder_command,
        "codex_command": codex_command,
        "codex_children": codex_children,
    }


def _paired_codex_children_succeeded(
    codex_exit_codes: Mapping[str, Optional[int]],
    *,
    autoencoder_exit_code: Optional[int],
    runner_terminated_children: AbstractSet[str],
    stop_requested: bool,
) -> bool:
    """Return whether Codex children finished cleanly for paired-run accounting."""

    if not codex_exit_codes or autoencoder_exit_code != 0:
        return False
    for run_id, exit_code in codex_exit_codes.items():
        if exit_code == 0:
            continue
        runner_stopped_child = (
            not stop_requested
            and run_id in runner_terminated_children
            and exit_code in {-signal.SIGTERM, -signal.SIGKILL}
        )
        if not runner_stopped_child:
            return False
    return True


def _paired_autoencoder_succeeded(
    *,
    autoencoder_run_id: str,
    autoencoder_exit_code: Optional[int],
    runner_terminated_children: AbstractSet[str],
) -> bool:
    """Return whether the paired autoencoder child reached its own clean stop."""

    return autoencoder_exit_code == 0 and autoencoder_run_id not in runner_terminated_children


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
    semantic_bundle_keys = sorted(
        {
            str(todo.metadata.get("semantic_bundle_key") or "")
            for todo in todos
            if todo.metadata.get("semantic_bundle_key")
        }
    )
    vector_bundle_anchor_ids = sorted(
        {
            str(todo.metadata.get("vector_bundle_anchor_id") or "")
            for todo in todos
            if todo.metadata.get("vector_bundle_anchor_id")
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
        "semantic_bundle_keys": semantic_bundle_keys,
        "vector_bundle_anchor_ids": vector_bundle_anchor_ids,
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


def _safe_repo_relative_path(path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe repository-relative path: {path!r}")
    return relative


def _copy_source_path_to_worktree(source_path: Path, destination_path: Path) -> None:
    if destination_path.exists() or destination_path.is_symlink():
        if destination_path.is_dir() and not destination_path.is_symlink():
            shutil.rmtree(destination_path)
        else:
            destination_path.unlink()

    if not source_path.exists() and not source_path.is_symlink():
        return

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_symlink():
        os.symlink(os.readlink(source_path), destination_path)
    elif source_path.is_dir():
        shutil.copytree(source_path, destination_path, symlinks=True)
    else:
        shutil.copy2(source_path, destination_path)


def _materialize_source_targets_in_worktree(
    *,
    source_repo_root: Path,
    repair_worktree: Path,
    target_files: Sequence[str],
) -> None:
    for path in target_files:
        relative = _safe_repo_relative_path(path)
        _copy_source_path_to_worktree(
            source_repo_root / relative,
            repair_worktree / relative,
        )


def _git_stdout(
    repo_root: Path,
    *args: str,
    timeout_seconds: float = 60.0,
) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout_seconds)),
    )
    result.check_returncode()
    return result.stdout.strip()


def _commit_repair_worktree_targets(
    repair_worktree: Path,
    *,
    target_files: Sequence[str],
    message: str,
) -> Dict[str, Any]:
    if not target_files:
        return {
            "changed": False,
            "commit": _git_stdout(repair_worktree, "rev-parse", "HEAD"),
            "status": "no_target_files",
        }
    addable_targets: List[str] = []
    skipped_missing_targets: List[str] = []
    for path in target_files:
        relative = _safe_repo_relative_path(str(path))
        if (repair_worktree / relative).exists() or (repair_worktree / relative).is_symlink():
            addable_targets.append(str(path))
            continue
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(path)],
            cwd=repair_worktree,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        if tracked.returncode == 0:
            addable_targets.append(str(path))
        else:
            skipped_missing_targets.append(str(path))

    if not addable_targets:
        return {
            "changed": False,
            "commit": _git_stdout(repair_worktree, "rev-parse", "HEAD"),
            "skipped_missing_targets": skipped_missing_targets,
            "status": "no_addable_target_files",
        }

    add = subprocess.run(
        ["git", "add", "-A", "--", *addable_targets],
        cwd=repair_worktree,
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    if add.returncode != 0:
        return {
            "changed": False,
            "status": "add_failed",
            "exit_code": add.returncode,
            "skipped_missing_targets": skipped_missing_targets,
            "stderr_tail": (add.stderr or "")[-500:],
            "stdout_tail": (add.stdout or "")[-500:],
        }

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *addable_targets],
        cwd=repair_worktree,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    if diff.returncode == 0:
        return {
            "changed": False,
            "commit": _git_stdout(repair_worktree, "rev-parse", "HEAD"),
            "skipped_missing_targets": skipped_missing_targets,
            "status": "unchanged",
        }
    if diff.returncode != 1:
        return {
            "changed": False,
            "status": "diff_failed",
            "exit_code": diff.returncode,
            "skipped_missing_targets": skipped_missing_targets,
            "stderr_tail": (diff.stderr or "")[-500:],
            "stdout_tail": (diff.stdout or "")[-500:],
        }

    commit = subprocess.run(
        [
            "git",
            "-c",
            "user.email=codex-daemon@example.invalid",
            "-c",
            "user.name=Codex Legal IR Daemon",
            "commit",
            "--no-gpg-sign",
            "-m",
            message,
        ],
        cwd=repair_worktree,
        capture_output=True,
        text=True,
        timeout=120.0,
    )
    if commit.returncode != 0:
        return {
            "changed": False,
            "status": "commit_failed",
            "exit_code": commit.returncode,
            "skipped_missing_targets": skipped_missing_targets,
            "stderr_tail": (commit.stderr or "")[-500:],
            "stdout_tail": (commit.stdout or "")[-500:],
        }

    return {
        "changed": True,
        "commit": _git_stdout(repair_worktree, "rev-parse", "HEAD"),
        "skipped_missing_targets": skipped_missing_targets,
        "status": "committed",
    }


def _resolve_unmerged_targets_with_union(
    repair_worktree: Path,
    *,
    target_files: Sequence[str],
) -> Dict[str, Any]:
    """Resolve text merge conflicts by keeping both dirty-main and Codex hunks."""
    status = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U", "--", *target_files],
        cwd=repair_worktree,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    if status.returncode != 0:
        return {
            "status": "unmerged_scan_failed",
            "exit_code": status.returncode,
            "stderr_tail": (status.stderr or "")[-500:],
            "stdout_tail": (status.stdout or "")[-500:],
        }
    unmerged_paths = [path for path in status.stdout.splitlines() if path.strip()]
    if not unmerged_paths:
        return {"status": "no_unmerged_paths", "paths": []}

    resolved_paths: List[str] = []
    with tempfile.TemporaryDirectory(prefix="codex-union-merge-") as tmp:
        tmpdir = Path(tmp)
        for index, path in enumerate(unmerged_paths, start=1):
            relative = _safe_repo_relative_path(path)
            stage_paths: Dict[str, Path] = {}
            for stage, name in (("1", "base"), ("2", "ours"), ("3", "theirs")):
                stage_result = subprocess.run(
                    ["git", "show", f":{stage}:{path}"],
                    cwd=repair_worktree,
                    capture_output=True,
                    timeout=30.0,
                )
                if stage_result.returncode != 0:
                    return {
                        "status": f"{name}_stage_unavailable",
                        "path": path,
                        "exit_code": stage_result.returncode,
                        "stderr_tail": stage_result.stderr.decode(
                            "utf-8",
                            errors="replace",
                        )[-500:],
                    }
                stage_path = tmpdir / f"{index}-{name}"
                stage_path.write_bytes(stage_result.stdout)
                stage_paths[name] = stage_path

            merge_file = subprocess.run(
                [
                    "git",
                    "merge-file",
                    "--union",
                    "-p",
                    str(stage_paths["ours"]),
                    str(stage_paths["base"]),
                    str(stage_paths["theirs"]),
                ],
                cwd=repair_worktree,
                capture_output=True,
                timeout=30.0,
            )
            if merge_file.returncode != 0:
                return {
                    "status": "union_merge_file_failed",
                    "path": path,
                    "exit_code": merge_file.returncode,
                    "stderr_tail": merge_file.stderr.decode(
                        "utf-8",
                        errors="replace",
                    )[-500:],
                }
            destination = repair_worktree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(merge_file.stdout)
            resolved_paths.append(path)

    add = subprocess.run(
        ["git", "add", "--", *resolved_paths],
        cwd=repair_worktree,
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    if add.returncode != 0:
        return {
            "status": "add_resolved_failed",
            "paths": resolved_paths,
            "exit_code": add.returncode,
            "stderr_tail": (add.stderr or "")[-500:],
            "stdout_tail": (add.stdout or "")[-500:],
        }
    remaining = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U", "--", *target_files],
        cwd=repair_worktree,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    remaining_paths = [
        path for path in (remaining.stdout or "").splitlines() if path.strip()
    ]
    return {
        "paths": resolved_paths,
        "remaining_unmerged_paths": remaining_paths,
        "status": "resolved" if not remaining_paths else "unmerged_paths_remain",
    }


def _repair_codex_diff_against_dirty_targets(
    *,
    diff_content: str,
    packet: Mapping[str, Any],
    source_repo_root: Path,
    target_files: Sequence[str],
    dirty_files: Sequence[str],
) -> Dict[str, Any]:
    """Merge a packet diff with dirty target files inside a scratch worktree."""
    packet_path_value = packet.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    packet_dir = packet_path.parent if packet_path is not None else Path(".")
    packet_id = str(packet.get("packet_id") or packet_dir.name)
    repair_id = _safe_artifact_name(f"{packet_id}-dirty-target-merge")
    repair_base = packet_dir / "merge-repair-worktrees"
    repair_base.mkdir(parents=True, exist_ok=True)
    repair_worktree: Optional[Path] = None
    report: Dict[str, Any] = {
        "dirty_files": list(dirty_files),
        "mode": "dirty_target_worktree_merge",
        "status": "failed",
    }
    try:
        manager = WorktreeManager(repo_path=source_repo_root, worktrees_base=repair_base)
        repair_worktree = manager.create_worktree(repair_id, branch="HEAD")
        report["worktree_path"] = str(repair_worktree)
        base_commit = _git_stdout(repair_worktree, "rev-parse", "HEAD")
        report["base_commit"] = base_commit

        _materialize_source_targets_in_worktree(
            source_repo_root=source_repo_root,
            repair_worktree=repair_worktree,
            target_files=target_files,
        )
        source_snapshot = _commit_repair_worktree_targets(
            repair_worktree,
            target_files=target_files,
            message=f"{packet_id}: source dirty target snapshot",
        )
        report["source_snapshot"] = dict(source_snapshot)
        if source_snapshot["status"] in {"add_failed", "commit_failed", "diff_failed"}:
            report["status"] = f"source_snapshot_{source_snapshot['status']}"
            return report
        source_commit = str(source_snapshot.get("commit") or base_commit)

        checkout_base = subprocess.run(
            ["git", "checkout", "--detach", base_commit],
            cwd=repair_worktree,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        report["checkout_base"] = {
            "exit_code": checkout_base.returncode,
            "stderr_tail": (checkout_base.stderr or "")[-500:],
            "stdout_tail": (checkout_base.stdout or "")[-500:],
        }
        if checkout_base.returncode != 0:
            report["status"] = "checkout_base_failed"
            return report

        apply_codex = _run_git_apply_stdin(
            repair_worktree,
            diff_content,
            "--3way",
            timeout_seconds=120.0,
        )
        report["codex_apply_3way"] = {
            "exit_code": apply_codex.returncode,
            "stderr_tail": (apply_codex.stderr or "")[-1000:],
            "stdout_tail": (apply_codex.stdout or "")[-1000:],
        }
        if apply_codex.returncode != 0:
            apply_union_repair = _resolve_unmerged_targets_with_union(
                repair_worktree,
                target_files=target_files,
            )
            report["codex_apply_conflict_resolution"] = dict(apply_union_repair)
            if apply_union_repair.get("status") != "resolved":
                report["status"] = "codex_apply_3way_failed"
                return report
            report["codex_apply_conflict_resolution_strategy"] = "union"

        codex_snapshot = _commit_repair_worktree_targets(
            repair_worktree,
            target_files=target_files,
            message=f"{packet_id}: codex target snapshot",
        )
        report["codex_snapshot"] = dict(codex_snapshot)
        if codex_snapshot["status"] in {"add_failed", "commit_failed", "diff_failed"}:
            report["status"] = f"codex_snapshot_{codex_snapshot['status']}"
            return report
        if not codex_snapshot.get("changed"):
            report["status"] = "no_codex_snapshot_diff"
            return report
        codex_commit = str(codex_snapshot["commit"])

        checkout_source = subprocess.run(
            ["git", "checkout", "--detach", source_commit],
            cwd=repair_worktree,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        report["checkout_source"] = {
            "exit_code": checkout_source.returncode,
            "stderr_tail": (checkout_source.stderr or "")[-500:],
            "stdout_tail": (checkout_source.stdout or "")[-500:],
        }
        if checkout_source.returncode != 0:
            report["status"] = "checkout_source_failed"
            return report

        merge = subprocess.run(
            ["git", "merge", "--no-commit", "--no-ff", codex_commit],
            cwd=repair_worktree,
            capture_output=True,
            text=True,
            timeout=120.0,
        )
        report["merge"] = {
            "exit_code": merge.returncode,
            "stderr_tail": (merge.stderr or "")[-1000:],
            "stdout_tail": (merge.stdout or "")[-1000:],
        }
        if merge.returncode != 0:
            status = subprocess.run(
                ["git", "status", "--porcelain", "--", *target_files],
                cwd=repair_worktree,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
            report["merge_status_tail"] = (status.stdout or status.stderr or "")[-1000:]
            union_repair = _resolve_unmerged_targets_with_union(
                repair_worktree,
                target_files=target_files,
            )
            report["conflict_resolution"] = dict(union_repair)
            if union_repair.get("status") != "resolved":
                report["status"] = "merge_conflict"
                return report
            report["conflict_resolution_strategy"] = "union"

        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--", *target_files],
            cwd=repair_worktree,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        diff.check_returncode()
        names = subprocess.run(
            ["git", "diff", "--name-only", "-z", "HEAD", "--", *target_files],
            cwd=repair_worktree,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        names.check_returncode()
        repaired_content = diff.stdout
        repaired_targets = [path for path in names.stdout.split("\0") if path]
        report["target_files"] = repaired_targets
        if not repaired_content.strip():
            report["status"] = "no_merged_delta"
            return report
        report["diff_content"] = repaired_content
        report["status"] = "repaired"
        return report
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        report["status"] = "dirty_target_repair_exception"
        report["error"] = str(exc)
        return report
    finally:
        if repair_worktree is not None:
            cleanup = subprocess.run(
                ["git", "worktree", "remove", str(repair_worktree), "--force"],
                cwd=source_repo_root,
                capture_output=True,
                text=True,
                timeout=60.0,
            )
            report["cleanup"] = {
                "exit_code": cleanup.returncode,
                "stderr_tail": (cleanup.stderr or "")[-500:],
                "stdout_tail": (cleanup.stdout or "")[-500:],
            }


def _repair_codex_worktree_diff_against_main(
    *,
    diff_content: str,
    packet: Mapping[str, Any],
    source_repo_root: Path,
) -> Dict[str, Any]:
    """Replay a stale packet diff into a fresh worktree from current main."""
    packet_path_value = packet.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    packet_dir = packet_path.parent if packet_path is not None else Path(".")
    packet_id = str(packet.get("packet_id") or packet_dir.name)
    repair_id = _safe_artifact_name(f"{packet_id}-merge-repair")
    repair_base = packet_dir / "merge-repair-worktrees"
    repair_base.mkdir(parents=True, exist_ok=True)
    repair_worktree: Optional[Path] = None
    report: Dict[str, Any] = {
        "mode": "apply_3way",
        "status": "failed",
    }
    target_files = [
        str(path)
        for path in packet.get("main_apply_target_files", [])
        if str(path).strip()
    ]
    try:
        manager = WorktreeManager(repo_path=source_repo_root, worktrees_base=repair_base)
        repair_worktree = manager.create_worktree(repair_id, branch="HEAD")
        report["worktree_path"] = str(repair_worktree)
        apply_result = _run_git_apply_stdin(
            repair_worktree,
            diff_content,
            "--3way",
            timeout_seconds=120.0,
        )
        report["apply_3way"] = {
            "exit_code": apply_result.returncode,
            "stderr_tail": (apply_result.stderr or "")[-1000:],
            "stdout_tail": (apply_result.stdout or "")[-1000:],
        }
        if apply_result.returncode != 0:
            apply_union_repair = _resolve_unmerged_targets_with_union(
                repair_worktree,
                target_files=target_files,
            )
            report["apply_conflict_resolution"] = dict(apply_union_repair)
            if apply_union_repair.get("status") != "resolved":
                report["status"] = "apply_3way_failed"
                return report
            report["apply_conflict_resolution_strategy"] = "union"

        repaired_diff = _codex_worktree_diff(repair_worktree)
        repaired_content = str(repaired_diff.get("diff_content") or "")
        report["target_files"] = list(repaired_diff.get("target_files", []))
        if not repaired_content.strip():
            report["status"] = "no_repaired_diff"
            return report
        report["diff_content"] = repaired_content
        report["status"] = "repaired"
        return report
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        report["status"] = "repair_exception"
        report["error"] = str(exc)
        return report
    finally:
        if repair_worktree is not None:
            cleanup = subprocess.run(
                ["git", "worktree", "remove", str(repair_worktree), "--force"],
                cwd=source_repo_root,
                capture_output=True,
                text=True,
                timeout=60.0,
            )
            report["cleanup"] = {
                "exit_code": cleanup.returncode,
                "stderr_tail": (cleanup.stderr or "")[-500:],
                "stdout_tail": (cleanup.stdout or "")[-500:],
            }


def _repair_status_has_no_remaining_delta(status: str) -> bool:
    """Return whether merge repair proved the packet is already represented."""
    return str(status or "").strip().lower() in {
        "no_codex_snapshot_diff",
        "no_merged_delta",
        "no_repaired_diff",
    }


def _default_codex_apply_validation_commands(repo_root: Path) -> List[List[str]]:
    tests = [path for path in CODEX_APPLY_VALIDATION_TESTS if (repo_root / path).exists()]
    if not tests:
        return []
    return [[sys.executable, "-m", "pytest", "-q", *tests]]


def _codex_apply_validation_env() -> Dict[str, str]:
    """Run apply validation without contending with the autoencoder GPU loop."""
    env = dict(os.environ)
    allow_cuda = str(
        env.get("IPFS_DATASETS_CODEX_APPLY_VALIDATION_ALLOW_CUDA") or ""
    ).strip().lower()
    if allow_cuda not in {"1", "true", "yes", "on"}:
        env["CUDA_VISIBLE_DEVICES"] = ""
    return env


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
                env=_codex_apply_validation_env(),
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


def _codex_packet_metric_sample_payloads(
    packet: Mapping[str, Any],
    *,
    max_samples: int = 8,
) -> List[Dict[str, Any]]:
    """Return unique legal sample payloads carried by claimed TODO metadata."""
    payloads: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for todo in packet.get("todos", []):
        if not isinstance(todo, Mapping):
            continue
        metadata = dict(todo.get("metadata", {}) or {})
        for payload in metadata.get("metric_sample_payloads", []) or []:
            if not isinstance(payload, Mapping):
                continue
            sample_id = str(payload.get("sample_id") or "")
            key = sample_id or hashlib.sha256(
                json.dumps(dict(payload), sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            payloads.append(dict(payload))
            if len(payloads) >= max(0, int(max_samples)):
                return payloads
    return payloads


def _codex_packet_target_metric_names(packet: Mapping[str, Any]) -> List[str]:
    """Return target metrics declared by claimed TODO metadata."""
    metrics: List[str] = []
    for todo in packet.get("todos", []):
        if not isinstance(todo, Mapping):
            continue
        metadata = dict(todo.get("metadata", {}) or {})
        metrics.extend(str(metric) for metric in metadata.get("target_metrics", []) or [])
    return list(dict.fromkeys(metric for metric in metrics if metric))


def _codex_packet_target_metric_snapshot(
    packet: Mapping[str, Any],
    repo_root: Path,
    *,
    timeout_seconds: float = 120.0,
) -> Dict[str, Any]:
    """Measure target metrics in a fresh subprocess using packet sample payloads."""
    sample_payloads = _codex_packet_metric_sample_payloads(packet)
    target_metrics = _codex_packet_target_metric_names(packet)
    if not sample_payloads or not target_metrics:
        return {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "skipped",
            "target_metrics": target_metrics,
        }
    script = r'''
import json
import sys

from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES
from ipfs_datasets_py.logic.modal import DeterministicModalLogicCodec, ModalLogicCodecConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    bridge_ir_metric_block,
    compiler_ir_metric_block,
)

payload = json.loads(sys.stdin.read())
samples = []
for item in payload.get("samples", []):
    samples.append(
        build_us_code_sample(
            title=str(item.get("title") or ""),
            section=str(item.get("section") or ""),
            citation=str(item.get("citation") or "") or None,
            text=str(item.get("text") or ""),
            embedding_vector=item.get("embedding_vector") or None,
        )
    )
codec = DeterministicModalLogicCodec(ModalLogicCodecConfig())
compiler = compiler_ir_metric_block(samples, codec)
bridge = bridge_ir_metric_block(
    samples,
    DEFAULT_LEGAL_IR_BRIDGE_NAMES,
    evaluate_provers=False,
    parallel_workers=1,
)
metrics = {}
for key, value in compiler.items():
    if isinstance(value, (int, float)):
        metrics[str(key)] = float(value)
if "cosine_similarity" in metrics:
    metrics["embedding_cosine_similarity"] = metrics["cosine_similarity"]
canonical = dict(bridge.get("canonical_ir", {}) or {})
canonical_losses = dict(canonical.get("losses", {}) or {})
for key, value in canonical_losses.items():
    if isinstance(value, (int, float)):
        metrics[str(key)] = float(value)
canonical_map = {
    "legal_ir_multiview_total_loss": "total_loss",
    "legal_ir_multiview_graph_failure_penalty": "graph_failure_penalty",
    "legal_ir_multiview_proof_failure_ratio": "proof_failure_ratio",
    "legal_ir_multiview_view_coverage_loss": "view_coverage_loss",
}
for metric_name, source_key in canonical_map.items():
    value = canonical.get(source_key)
    if isinstance(value, (int, float)):
        metrics[metric_name] = float(value)
target_metrics = list(payload.get("target_metrics") or [])
selected = {
    metric: metrics[metric]
    for metric in target_metrics
    if metric in metrics
}
print(json.dumps({
    "compiler": compiler,
    "metric_count": len(selected),
    "metrics": selected,
    "sample_count": len(samples),
    "status": "measured",
    "target_metrics": target_metrics,
}, sort_keys=True))
'''
    payload = {"samples": sample_payloads, "target_metrics": target_metrics}
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            input=json.dumps(payload, ensure_ascii=True),
            capture_output=True,
            env=_codex_apply_validation_env(),
            text=True,
            timeout=max(1.0, float(timeout_seconds)),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "timeout",
            "stderr_tail": _process_text(exc.stderr)[-500:],
            "stdout_tail": _process_text(exc.stdout)[-500:],
            "target_metrics": target_metrics,
            "timeout_seconds": float(timeout_seconds),
        }
    if result.returncode != 0:
        return {
            "exit_code": result.returncode,
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "failed",
            "stderr_tail": (result.stderr or "")[-500:],
            "stdout_tail": (result.stdout or "")[-500:],
            "target_metrics": target_metrics,
        }
    try:
        stdout_lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
        snapshot = json.loads(stdout_lines[-1] if stdout_lines else "")
    except json.JSONDecodeError:
        return {
            "exit_code": result.returncode,
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "invalid_json",
            "stderr_tail": (result.stderr or "")[-500:],
            "stdout_tail": (result.stdout or "")[-500:],
            "target_metrics": target_metrics,
        }
    snapshot["stderr_tail"] = (result.stderr or "")[-500:]
    return snapshot


def _codex_packet_should_measure_target_metrics(
    packet: Mapping[str, Any],
    *,
    target_files: Sequence[str],
) -> bool:
    """Return true when packet metadata and changed files justify metric checks."""
    if not _codex_packet_metric_sample_payloads(packet):
        return False
    if not _codex_packet_target_metric_names(packet):
        return False
    return any(
        str(path).startswith(("ipfs_datasets_py/", "tests/", "tests/unit_tests/"))
        for path in target_files
    )


def _codex_target_metric_validation_report(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> Dict[str, Any]:
    """Compare before/after target metrics with positive deltas meaning better."""
    target_metrics = list(dict.fromkeys(list(before.get("target_metrics", []) or [])))
    before_metrics = dict(before.get("metrics", {}) or {})
    after_metrics = dict(after.get("metrics", {}) or {})
    metric_deltas: Dict[str, float] = {}
    improved_metrics: List[str] = []
    regressed_metrics: List[str] = []
    missing_metrics: List[str] = []
    for metric in target_metrics:
        if metric not in before_metrics or metric not in after_metrics:
            missing_metrics.append(str(metric))
            continue
        delta = _target_metric_improvement_delta(
            metric,
            before_value=float(before_metrics[metric]),
            after_value=float(after_metrics[metric]),
        )
        metric_deltas[str(metric)] = round(delta, 9)
        if delta > 0.0:
            improved_metrics.append(str(metric))
        elif delta < 0.0:
            regressed_metrics.append(str(metric))
    before_status = str(before.get("status") or "")
    after_status = str(after.get("status") or "")
    status = (
        "skipped"
        if before_status == "skipped" or after_status == "skipped"
        else "unavailable"
        if before_status != "measured" or after_status != "measured"
        else "regressed"
        if regressed_metrics
        else "passed"
    )
    return {
        "after": dict(after),
        "before": dict(before),
        "improved_metrics": improved_metrics,
        "metric_deltas": metric_deltas,
        "missing_metrics": missing_metrics,
        "regressed_metrics": regressed_metrics,
        "status": status,
        "target_metrics": target_metrics,
    }


def _target_metric_improvement_delta(
    metric_name: str,
    *,
    before_value: float,
    after_value: float,
) -> float:
    """Return positive when the metric improved."""
    normalized = str(metric_name)
    higher_is_better = (
        normalized in {"embedding_cosine_similarity", "cosine_similarity"}
        or normalized.endswith("_similarity")
        or normalized.endswith("_score")
        or normalized.endswith("_rate")
    ) and not normalized.endswith("_loss")
    if higher_is_better:
        return after_value - before_value
    return before_value - after_value


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
    merge_repair_attempts: int = 1,
    merge_repair_mode: str = "apply_3way",
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
        updated["main_apply_dirty_files"] = dirty_files
        normalized_repair_mode = str(merge_repair_mode or "off").strip().lower()
        if normalized_repair_mode == "apply_3way" and int(merge_repair_attempts) > 0:
            repair = _repair_codex_diff_against_dirty_targets(
                diff_content=diff_content,
                packet=updated,
                source_repo_root=source_repo_root,
                target_files=target_files,
                dirty_files=dirty_files,
            )
            repaired_diff_content = str(repair.get("diff_content") or "")
            repair.pop("diff_content", None)
            updated["main_apply_merge_repair"] = dict(repair)
            if repaired_diff_content.strip():
                diff_content = repaired_diff_content
                target_files = [
                    str(path)
                    for path in updated["main_apply_merge_repair"].get(
                        "target_files",
                        target_files,
                    )
                ]
                updated["main_apply_target_files"] = target_files
                updated["main_apply_repair_status"] = "repaired"
            else:
                repair_status = str(repair.get("status") or "failed")
                if _repair_status_has_no_remaining_delta(repair_status):
                    updated["patch_path"] = None
                    updated["patch_status"] = "main_apply_no_merged_delta"
                    updated["patch_error"] = None
                    updated["main_apply_status"] = "no_changes"
                    updated["main_apply_repair_status"] = repair_status
                    updated["main_apply_error"] = None
                    _save_packet_if_possible(updated, packet_path)
                    return updated
                patch_path = _save_codex_packet_diff_patch(
                    updated,
                    diff_content=diff_content,
                    reason=f"dirty-target-{repair_status}",
                )
                updated["patch_path"] = str(patch_path) if patch_path is not None else None
                updated["patch_status"] = "main_apply_dirty_target_repair_failed"
                updated["patch_error"] = (
                    "target checkout has local edits in Codex target files; "
                    f"dirty-target worktree merge repair failed: {repair_status}"
                )
                updated["main_apply_error"] = updated["patch_error"]
                _save_packet_if_possible(updated, packet_path)
                return updated
        else:
            patch_path = _save_codex_packet_diff_patch(
                updated,
                diff_content=diff_content,
                reason="dirty-target",
            )
            updated["patch_path"] = str(patch_path) if patch_path is not None else None
            updated["patch_status"] = "main_apply_dirty_target"
            updated["patch_error"] = "target checkout has local edits in Codex target files"
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
        normalized_repair_mode = str(merge_repair_mode or "off").strip().lower()
        if normalized_repair_mode == "apply_3way" and int(merge_repair_attempts) > 0:
            repair = _repair_codex_worktree_diff_against_main(
                diff_content=diff_content,
                packet=updated,
                source_repo_root=source_repo_root,
            )
            repaired_diff_content = str(repair.get("diff_content") or "")
            repair.pop("diff_content", None)
            updated["main_apply_merge_repair"] = dict(repair)
            if repaired_diff_content.strip():
                diff_content = repaired_diff_content
                target_files = [
                    str(path)
                    for path in updated["main_apply_merge_repair"].get(
                        "target_files",
                        target_files,
                    )
                ]
                updated["main_apply_target_files"] = target_files
                check = _run_git_apply_stdin(source_repo_root, diff_content, "--check")
                updated["main_apply_repaired_check"] = {
                    "exit_code": check.returncode,
                    "stderr_tail": (check.stderr or "")[-500:],
                    "stdout_tail": (check.stdout or "")[-500:],
                }
        if check.returncode == 0:
            updated["main_apply_repair_status"] = "repaired"
        else:
            repair_status = str(
                dict(updated.get("main_apply_merge_repair", {})).get("status") or ""
            )
            if _repair_status_has_no_remaining_delta(repair_status):
                updated["patch_path"] = None
                updated["patch_status"] = "main_apply_no_merged_delta"
                updated["patch_error"] = None
                updated["main_apply_status"] = "no_changes"
                updated["main_apply_repair_status"] = repair_status
                updated["main_apply_error"] = None
                _save_packet_if_possible(updated, packet_path)
                return updated
            reason = (
                "apply-check-failed"
                if not repair_status
                else f"apply-check-failed-{repair_status}"
            )
            patch_path = _save_codex_packet_diff_patch(
                updated,
                diff_content=diff_content,
                reason=reason,
            )
            updated["patch_path"] = str(patch_path) if patch_path is not None else None
            updated["patch_status"] = (
                "main_apply_check_failed"
                if not repair_status
                else "main_apply_check_failed_repair_failed"
            )
            updated["patch_error"] = check.stderr or check.stdout or "git apply --check failed"
            updated["main_apply_error"] = updated["patch_error"]
            _save_packet_if_possible(updated, packet_path)
            return updated

    measure_target_metrics = _codex_packet_should_measure_target_metrics(
        updated,
        target_files=target_files,
    )
    target_metric_before = (
        _codex_packet_target_metric_snapshot(
            updated,
            source_repo_root,
            timeout_seconds=min(float(validation_timeout_seconds), 120.0),
        )
        if measure_target_metrics
        else {
            "metric_count": 0,
            "metrics": {},
            "sample_count": 0,
            "status": "skipped",
            "target_metrics": _codex_packet_target_metric_names(updated),
        }
    )
    updated["target_metric_baseline"] = target_metric_before

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
        baseline_validation: Dict[str, Any] = {"status": "skipped", "commands": []}
        if rollback.returncode == 0:
            baseline_validation_dir = packet_dir / "baseline-validation"
            baseline_validation_dir.mkdir(parents=True, exist_ok=True)
            baseline_validation = _run_codex_apply_validation(
                source_repo_root,
                baseline_validation_dir,
                validation_commands=validation_commands,
                timeout_seconds=validation_timeout_seconds,
            )
        updated["main_apply_baseline_validation"] = baseline_validation
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason="validation-failed",
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        if baseline_validation["status"] not in {"passed", "skipped"}:
            updated["patch_status"] = (
                "main_apply_baseline_validation_failed_rolled_back"
                if rollback.returncode == 0
                else "main_apply_baseline_validation_failed_rollback_failed"
            )
            updated["patch_error"] = (
                f"baseline validation {baseline_validation['status']} "
                f"after packet validation {validation['status']}"
            )
        else:
            updated["patch_status"] = (
                "main_apply_validation_failed_rolled_back"
                if rollback.returncode == 0
                else "main_apply_validation_failed_rollback_failed"
            )
            updated["patch_error"] = f"validation {validation['status']}"
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated

    target_metric_after = (
        _codex_packet_target_metric_snapshot(
            updated,
            source_repo_root,
            timeout_seconds=min(float(validation_timeout_seconds), 120.0),
        )
        if measure_target_metrics
        else {
            "metric_count": 0,
            "metrics": {},
            "sample_count": 0,
            "status": "skipped",
            "target_metrics": _codex_packet_target_metric_names(updated),
        }
    )
    target_metric_validation = _codex_target_metric_validation_report(
        before=target_metric_before,
        after=target_metric_after,
    )
    updated["target_metric_validation"] = target_metric_validation
    updated["metric_deltas"] = dict(target_metric_validation.get("metric_deltas", {}))
    if target_metric_validation["status"] == "regressed":
        rollback = _run_git_apply_stdin(source_repo_root, diff_content, "-R")
        updated["main_apply_rollback"] = {
            "exit_code": rollback.returncode,
            "stderr_tail": (rollback.stderr or "")[-500:],
            "stdout_tail": (rollback.stdout or "")[-500:],
        }
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason="target-metric-regression",
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        updated["patch_status"] = (
            "main_apply_target_metric_regression_rolled_back"
            if rollback.returncode == 0
            else "main_apply_target_metric_regression_rollback_failed"
        )
        updated["patch_error"] = "target metric regression"
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
    merge_repair_attempts: int = 1,
    merge_repair_mode: str = "apply_3way",
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
        with codex_main_apply_lock(updated):
            refreshed = apply_codex_worktree_changes_to_main(
                updated,
                commit_mode=commit_mode,
                merge_repair_attempts=merge_repair_attempts,
                merge_repair_mode=merge_repair_mode,
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
            with codex_main_apply_lock(refreshed):
                refreshed = apply_codex_worktree_changes_to_main(
                    refreshed,
                    commit_mode=commit_mode,
                    merge_repair_attempts=merge_repair_attempts,
                    merge_repair_mode=merge_repair_mode,
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


def _terminate_process_group(process: subprocess.Popen[str], signum: int) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.terminate()
        except OSError:
            return


def _terminate_active_codex_exec_processes(signum: int = signal.SIGTERM) -> None:
    for process in list(_ACTIVE_CODEX_EXEC_PROCESSES):
        _terminate_process_group(process, signum)


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
    ]
    if str(sandbox).strip().lower() == CODEX_SANDBOX_FALLBACK:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd.extend(["--sandbox", sandbox])
    cmd.extend(["--output-last-message", str(last_message_path)])
    if model:
        cmd.extend(["--model", model])
    cmd.append("-")

    started = time.time()
    process: Optional[subprocess.Popen[str]] = None
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        _ACTIVE_CODEX_EXEC_PROCESSES.append(process)
        stdout, stderr = process.communicate(
            input=prompt,
            timeout=max(1.0, float(timeout_seconds)),
        )
        stdout_path.write_text(stdout or "", encoding="utf-8")
        stderr_path.write_text(stderr or "", encoding="utf-8")
        status = "succeeded" if process.returncode == 0 else "failed"
        return {
            "command": cmd,
            "duration_seconds": round(time.time() - started, 3),
            "exit_code": process.returncode,
            "last_message_path": str(last_message_path),
            "prompt_path": str(prompt_path),
            "sandbox": sandbox,
            "status": status,
            "stderr_path": str(stderr_path),
            "stdout_path": str(stdout_path),
        }
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            _terminate_process_group(process, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=5.0)
        else:
            stdout, stderr = exc.stdout, exc.stderr
        stdout_path.write_text(_process_text(stdout), encoding="utf-8")
        stderr_path.write_text(_process_text(stderr), encoding="utf-8")
        return {
            "command": cmd,
            "duration_seconds": round(time.time() - started, 3),
            "exit_code": process.returncode if process is not None else None,
            "last_message_path": str(last_message_path),
            "prompt_path": str(prompt_path),
            "sandbox": sandbox,
            "status": "timeout",
            "stderr_path": str(stderr_path),
            "stdout_path": str(stdout_path),
            "timeout_seconds": float(timeout_seconds),
        }
    finally:
        if process is not None and process in _ACTIVE_CODEX_EXEC_PROCESSES:
            _ACTIVE_CODEX_EXEC_PROCESSES.remove(process)


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


def _codex_exec_logs_indicate_transient_failure(exec_result: Mapping[str, Any]) -> bool:
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
    return any(pattern in combined for pattern in CODEX_TRANSIENT_FAILURE_PATTERNS)


def _codex_packet_should_requeue_transient(packet: Mapping[str, Any]) -> bool:
    exec_result = dict(packet.get("codex_exec", {}))
    exec_status = str(exec_result.get("status") or "").strip().lower()
    patch_status = str(packet.get("patch_status") or "").strip().lower()
    main_apply_status = str(packet.get("main_apply_status") or "").strip().lower()
    if patch_status in CODEX_COMPLETED_WORK_STATUSES or main_apply_status == "applied":
        return False
    if exec_status not in {"failed", "timeout"}:
        return False
    return _codex_exec_logs_indicate_transient_failure(exec_result)


def _codex_validation_commands_for_todos(
    todos: Sequence[ModalTodo],
) -> Optional[List[List[str]]]:
    """Return explicit validation commands requested by claimed TODO metadata."""
    commands: List[List[str]] = []
    seen: set[tuple[str, ...]] = set()
    for todo in todos:
        raw_commands = todo.metadata.get("validation_commands")
        if not isinstance(raw_commands, Sequence) or isinstance(raw_commands, (str, bytes)):
            raw_commands = [raw_commands] if raw_commands else []
        for raw_command in raw_commands:
            if isinstance(raw_command, str):
                command = shlex.split(raw_command)
            elif isinstance(raw_command, Sequence):
                command = [str(part) for part in raw_command]
            else:
                continue
            command = [part for part in command if part]
            key = tuple(command)
            if not command or key in seen:
                continue
            seen.add(key)
            commands.append(command)
    return commands or None


def _codex_packet_validation_report(packet: Mapping[str, Any]) -> Dict[str, Any]:
    """Summarize packet validation/apply evidence for queue finalization."""
    main_validation = dict(packet.get("main_apply_validation", {}) or {})
    baseline_validation = dict(packet.get("main_apply_baseline_validation", {}) or {})
    target_metric_validation = dict(packet.get("target_metric_validation", {}) or {})
    return {
        "baseline_status": baseline_validation.get("status"),
        "main_apply_status": packet.get("main_apply_status"),
        "metric_deltas": dict(packet.get("metric_deltas", {}) or {}),
        "patch_status": packet.get("patch_status"),
        "regressed_metrics": list(target_metric_validation.get("regressed_metrics", []) or []),
        "status": main_validation.get("status")
        or packet.get("main_apply_status")
        or packet.get("patch_status")
        or "not_measured",
        "target_metric_status": target_metric_validation.get("status"),
    }


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


def _todo_metric_guidance_lines(todo: ModalTodo, *, indent: str = "  ") -> List[str]:
    """Return compact target-metric and sample guidance for Codex task files."""
    lines: List[str] = []
    target_metrics = [
        str(metric)
        for metric in _metadata_sequence(todo.metadata.get("target_metrics", []))
        if str(metric)
    ]
    if target_metrics:
        lines.append(f"{indent}target_metrics: `{', '.join(target_metrics)}`")
    validation_commands = [
        str(command)
        for command in _metadata_sequence(todo.metadata.get("validation_commands", []))
        if str(command)
    ]
    if validation_commands:
        lines.append(f"{indent}validation: `{validation_commands[0]}`")
    sample_payloads = [
        payload
        for payload in _metadata_sequence(todo.metadata.get("metric_sample_payloads", []))
        if isinstance(payload, Mapping)
    ]
    if sample_payloads:
        lines.append(f"{indent}metric_samples: `{len(sample_payloads)}`")
    for payload in sample_payloads[:2]:
        citation = str(payload.get("citation") or "").strip()
        if not citation:
            title = str(payload.get("title") or "").strip()
            section = str(payload.get("section") or "").strip()
            citation = f"{title} U.S.C. {section}".strip()
        text = _compact_markdown_inline(str(payload.get("text") or ""), max_chars=240)
        if text:
            prefix = f"{citation}: " if citation else ""
            lines.append(f"{indent}sample_text: {prefix}{text}")
    return lines


def _packet_metric_guidance_lines(todos: Sequence[ModalTodo]) -> List[str]:
    target_metrics: List[str] = []
    sample_count = 0
    for todo in todos:
        target_metrics.extend(
            str(metric)
            for metric in _metadata_sequence(todo.metadata.get("target_metrics", []))
            if str(metric)
        )
        sample_count += len(
            [
                payload
                for payload in _metadata_sequence(todo.metadata.get("metric_sample_payloads", []))
                if isinstance(payload, Mapping)
            ]
        )
    unique_metrics = list(dict.fromkeys(target_metrics))
    if not unique_metrics and not sample_count:
        return []
    lines = [
        "## Metric Guard",
        "The daemon remeasures these target metrics before and after applying the worktree diff.",
        "A patch that regresses any targeted metric is rolled back and marked failed_validation.",
    ]
    if unique_metrics:
        lines.append(f"- Target metrics: `{', '.join(unique_metrics)}`")
    if sample_count:
        lines.append(f"- Metric sample payloads: `{sample_count}` across claimed TODOs")
    return lines


def _compact_markdown_inline(value: str, *, max_chars: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, int(max_chars) - 3)].rstrip() + "..."


def _metadata_sequence(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return [value]


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
                f"  scope: `{todo.metadata.get('program_synthesis_scope', '')}`",
                f"  bundle: `{todo.metadata.get('semantic_bundle_key', '')}`",
                f"  vector_bundle: `{todo.metadata.get('vector_bundle_anchor_id', '')}` score `{todo.metadata.get('vector_bundle_similarity', '')}`",
                f"  loss: `{todo.loss_name}` = `{todo.loss_value}`",
                f"  objective: {todo.objective}",
                f"  samples: `{', '.join(todo.sample_ids)}`",
            ]
        )
        lines.extend(_todo_metric_guidance_lines(todo))
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
    metric_guidance = _packet_metric_guidance_lines(todos)
    if metric_guidance:
        lines.extend(["", *metric_guidance])
    lines.extend(["", "## TODOs"])
    for todo in todos:
        lines.extend(
            [
                f"- `{todo.todo_id}` `{todo.action}`",
                f"  target: `{todo.metadata.get('target_component', '')}`",
                f"  scope: `{todo.metadata.get('program_synthesis_scope', '')}`",
                f"  bundle: `{todo.metadata.get('semantic_bundle_key', '')}`",
                f"  vector_bundle: `{todo.metadata.get('vector_bundle_anchor_id', '')}` score `{todo.metadata.get('vector_bundle_similarity', '')}`",
                f"  objective: {todo.objective}",
                f"  support: {todo.metadata.get('support_count', '')}",
            ]
        )
        lines.extend(_todo_metric_guidance_lines(todo))
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
        "When multiple TODOs are present, treat their semantic_bundle_key or vector_bundle metadata as evidence for one generalized compiler/decompiler/frame improvement over one-off sample fixes.",
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
        "best_validation_logic_bridge_acceptance": -1.0,
        "best_validation_logic_bridge_proof_failure_ratio": 1.0e12,
        "best_validation_logic_bridge_total_loss": 1.0e12,
        "bridge_evaluate_provers": bool(getattr(args, "bridge_evaluate_provers", True)),
        "bridge_loss_adapters": bridge_loss_adapter_names(args),
        "bridge_loss_failures": 0,
        "bridge_loss_samples": 0,
        "bridge_loss_signals": 0,
        "bridge_metric_failures": 0,
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
        "program_synthesis_deduped_total": 0,
        "program_synthesis_pending_cap": ModalOptimizerPolicy().max_program_synthesis_pending,
        "program_synthesis_pending": 0,
        "program_synthesis_preinsert_deduped": 0,
        "program_synthesis_seeded": 0,
        "program_synthesis_semantic_deduped": 0,
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
        "learning_rate_plateau_streak": 0,
        "learning_rate_cosine_regression_streak": 0,
        "learning_rate_applied": float(getattr(args, "learning_rate", 0.35)),
    }


def _cycle_learning_rate(args: argparse.Namespace, summary: Mapping[str, Any]) -> tuple[float, Dict[str, Any]]:
    """Return per-cycle learning rate using simple plateau/regression feedback."""
    base = max(1e-6, float(getattr(args, "learning_rate", 0.35)))
    floor_ratio = max(0.05, float(getattr(args, "learning_rate_floor_ratio", 0.25)))
    cap_ratio = max(1.0, float(getattr(args, "learning_rate_cap_ratio", 1.5)))
    plateau_streak = max(0, int(summary.get("learning_rate_plateau_streak", 0) or 0))
    cosine_regression_streak = max(
        0,
        int(summary.get("learning_rate_cosine_regression_streak", 0) or 0),
    )
    plateau_threshold = max(
        1e-9,
        float(getattr(args, "learning_rate_plateau_delta", 1e-5)),
    )
    scale = 1.0
    if plateau_streak >= 3:
        scale *= 1.1
    if cosine_regression_streak > 0:
        scale *= 0.85 ** float(cosine_regression_streak)
    lr = base * scale
    lr = max(base * floor_ratio, min(base * cap_ratio, lr))
    return lr, {
        "base_learning_rate": base,
        "applied_learning_rate": lr,
        "cap_ratio": cap_ratio,
        "cosine_regression_streak": cosine_regression_streak,
        "floor_ratio": floor_ratio,
        "plateau_delta_threshold": plateau_threshold,
        "plateau_streak": plateau_streak,
        "scale": scale,
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
    parser.add_argument(
        "--validation-canary-count",
        type=int,
        default=4,
        help=(
            "Sample this many fixed holdout rows once per run and use them for "
            "autoencoder acceptance so validation deltas are comparable across cycles. "
            "Zero keeps the prior rotating-validation behavior."
        ),
    )
    parser.add_argument(
        "--max-sample-text-chars",
        type=int,
        default=0,
        help=(
            "Skip randomly sampled U.S. Code rows whose text exceeds this many "
            "characters. Zero keeps the full corpus eligible."
        ),
    )
    parser.add_argument("--max-inner-iterations", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.35)
    parser.add_argument(
        "--learning-rate-floor-ratio",
        type=float,
        default=0.25,
        help="Lower bound for adaptive per-cycle learning rate as a ratio of --learning-rate.",
    )
    parser.add_argument(
        "--learning-rate-cap-ratio",
        type=float,
        default=1.5,
        help="Upper bound for adaptive per-cycle learning rate as a ratio of --learning-rate.",
    )
    parser.add_argument(
        "--learning-rate-plateau-delta",
        type=float,
        default=1.0e-5,
        help="Validation CE delta treated as plateau when absolute improvement is below this threshold.",
    )
    parser.add_argument(
        "--generalizable-projection-epochs",
        type=int,
        default=1,
        help=(
            "Feature-level pretraining epochs per daemon cycle before TODO claiming. "
            "Accepted epochs must improve the guarded holdout objective."
        ),
    )
    parser.add_argument(
        "--generalizable-projection-max-cosine-regression",
        type=float,
        default=0.005,
        help="Maximum tolerated holdout cosine-similarity regression during feature projection.",
    )
    parser.add_argument(
        "--generalizable-projection-max-reconstruction-regression",
        type=float,
        default=0.01,
        help="Maximum tolerated holdout reconstruction-loss regression during feature projection.",
    )
    parser.add_argument(
        "--generalizable-projection-max-cross-entropy-regression",
        type=float,
        default=0.0,
        help="Maximum tolerated holdout cross-entropy-loss regression during feature projection.",
    )
    parser.add_argument(
        "--generalizable-projection-max-legal-ir-loss-regression",
        type=float,
        default=0.01,
        help="Maximum tolerated holdout LegalIR loss regression during feature projection.",
    )
    parser.add_argument(
        "--generalizable-projection-objective-cross-entropy-weight",
        type=float,
        default=1.0,
        help="Weight for CE in feature-projection objective ranking/selection.",
    )
    parser.add_argument(
        "--generalizable-projection-objective-reconstruction-weight",
        type=float,
        default=1.0,
        help="Weight for reconstruction loss in feature-projection objective.",
    )
    parser.add_argument(
        "--generalizable-projection-objective-cosine-gap-weight",
        type=float,
        default=1.0,
        help="Weight for cosine gap (1-cosine) in feature-projection objective.",
    )
    parser.add_argument(
        "--generalizable-projection-objective-legal-ir-weight",
        type=float,
        default=1.0,
        help="Weight for LegalIR objective component in feature-projection objective.",
    )
    parser.add_argument(
        "--generalizable-projection-hard-example-fraction",
        type=float,
        default=1.0,
        help=(
            "Fraction of highest-loss train samples to update per projection epoch. "
            "Use values below one for hard-example curriculum."
        ),
    )
    parser.add_argument(
        "--bridge-loss-adapters",
        default=DEFAULT_BRIDGE_LOSS_ADAPTERS,
        help=(
            "Comma-separated logic bridge adapters that add compiler/prover/graph "
            "losses to optimizer TODO generation; use 'none' to disable."
        ),
    )
    parser.add_argument(
        "--bridge-evaluate-provers",
        type=parse_bool_flag,
        default=True,
        help=(
            "Whether bridge scoring should run expensive theorem-prover gates. "
            "Use false for daemon health checks that need fast compiler/KG/TODO cycles."
        ),
    )
    parser.add_argument(
        "--autoencoder-device",
        default="auto",
        help=(
            "Vector math device for the adaptive autoencoder: auto, python, "
            "cpu, cuda, or a specific CUDA device such as cuda:0."
        ),
    )
    parser.add_argument(
        "--autoencoder-feature-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale reusable feature-level modal-family logits during daemon "
            "validation. The guarded projection trainer rolls back family updates "
            "that regress the holdout objective."
        ),
    )
    parser.add_argument(
        "--autoencoder-feature-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale reusable feature-level embedding adjustments during decode. "
            "Higher values fit reconstruction faster but can overfit lexical noise."
        ),
    )
    parser.add_argument(
        "--autoencoder-compiler-quality-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale compiler-quality decoder prototypes for transferable failure "
            "modes such as missing symbolic formulas, frame uncertainty, and "
            "LegalIR bridge losses."
        ),
    )
    parser.add_argument(
        "--autoencoder-compiler-quality-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale compiler-quality modal-family logits so validation can learn "
            "from parser and bridge diagnostics, not only lexical cues."
        ),
    )
    parser.add_argument(
        "--autoencoder-logic-signature-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale clause-schema decoder prototypes built from operator, role, "
            "arity, condition/exception, frame, and KG signature features."
        ),
    )
    parser.add_argument(
        "--autoencoder-logic-signature-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale clause-schema modal-family logits for cross-entropy transfer "
            "across different legal wording with the same formal IR shape."
        ),
    )
    parser.add_argument(
        "--autoencoder-logic-signature-legal-ir-view-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale clause-schema LegalIR-view logits so frame, event, graph, "
            "and prover targets can specialize by formal clause shape."
        ),
    )
    parser.add_argument(
        "--autoencoder-round-trip-signal-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale source-only round-trip risk decoder prototypes built from "
            "base classifier uncertainty, parser ambiguity, frame ambiguity, "
            "and frame/KG structure."
        ),
    )
    parser.add_argument(
        "--autoencoder-round-trip-signal-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale source-only round-trip risk modal-family logits for "
            "cross-entropy transfer when similarly ambiguous clauses compile "
            "to the same formal family."
        ),
    )
    parser.add_argument(
        "--autoencoder-round-trip-signal-legal-ir-view-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale source-only round-trip risk LegalIR-view logits so hard "
            "compile/decompile cases can specialize frame, graph, and prover "
            "view predictions."
        ),
    )
    parser.add_argument(
        "--autoencoder-decompiler-plan-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale normalized source-clause decompiler-plan decoder prototypes "
            "built from modality cues, subject/action/object anchors, and "
            "condition/exception/temporal surface roles."
        ),
    )
    parser.add_argument(
        "--autoencoder-decompiler-plan-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale normalized source-clause decompiler-plan modal-family logits "
            "for transfer across equivalent legal wording."
        ),
    )
    parser.add_argument(
        "--autoencoder-decompiler-plan-legal-ir-view-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale normalized source-clause decompiler-plan LegalIR-view logits "
            "for frame, graph, event, and prover view transfer."
        ),
    )
    parser.add_argument(
        "--autoencoder-predicate-argument-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale predicate/argument skeleton decoder prototypes built from "
            "compiled predicate roles, argument positions, arity, and attached "
            "conditions or exceptions."
        ),
    )
    parser.add_argument(
        "--autoencoder-predicate-argument-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale predicate/argument skeleton modal-family logits for "
            "cross-entropy transfer across clauses with equivalent IR roles."
        ),
    )
    parser.add_argument(
        "--autoencoder-predicate-argument-legal-ir-view-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale predicate/argument skeleton LegalIR-view logits for "
            "decompiler, KG, event, frame, and prover view transfer."
        ),
    )
    parser.add_argument(
        "--autoencoder-embedding-head-update-normalization",
        type=float,
        default=0.5,
        help=(
            "Normalize decoder embedding update size by the number of active "
            "generalizable embedding heads. 0 disables normalization; 1 shares "
            "a fixed update budget equally across active heads."
        ),
    )
    parser.add_argument(
        "--autoencoder-family-logit-head-update-normalization",
        type=float,
        default=0.5,
        help=(
            "Normalize modal-family cross-entropy update size by the number of "
            "active generalizable family-logit heads."
        ),
    )
    parser.add_argument(
        "--autoencoder-legal-ir-view-head-update-normalization",
        type=float,
        default=0.5,
        help=(
            "Normalize LegalIR-view cross-entropy update size by the number of "
            "active view-logit heads."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-compiler-latent-profile-features",
        type=int,
        default=48,
        help=(
            "Maximum shared compiler-latent profile features to expose to the "
            "feature decoder. These compact source/IR bridge features combine "
            "modal cues, predicate roles, argument shape, frames, and KG shape."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-round-trip-bridge-features",
        type=int,
        default=64,
        help=(
            "Maximum round-trip bridge features to expose to the feature "
            "decoder. These bidirectional source/IR invariants align source "
            "roles with compiled families, predicates, arguments, and KG atoms."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-clause-topology-features",
        type=int,
        default=64,
        help=(
            "Maximum abstract clause topology features to expose to the feature "
            "decoder. These encode source role graph shape, modal scope, IR "
            "arity/condition/exception topology, and KG projection shape."
        ),
    )
    parser.add_argument(
        "--autoencoder-family-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale modal-family prototype vectors in the decoder. This lets "
            "reconstruction transfer through family predictions, not only exact text features."
        ),
    )
    parser.add_argument(
        "--autoencoder-family-semantic-slot-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale joint modal-family plus semantic-slot decoder prototypes. "
            "This lets conditions, exceptions, roles, frame terms, and graph "
            "slots reconstruct differently for deontic, temporal, constitutive, "
            "and other modal families."
        ),
    )
    parser.add_argument(
        "--autoencoder-family-semantic-slot-legal-ir-view-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale sparse modal-family plus semantic-slot plus LegalIR-view "
            "decoder prototypes for view-specific legal semantics."
        ),
    )
    parser.add_argument(
        "--autoencoder-family-legal-ir-view-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale joint modal-family plus LegalIR-view decoder prototypes. "
            "This lets reconstruction distinguish, for example, deontic KG "
            "targets from deontic prover targets."
        ),
    )
    parser.add_argument(
        "--autoencoder-semantic-slot-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale the compact semantic-slot classifier head for modal-family "
            "cross entropy. Slots summarize operators, predicate roles, conditions, "
            "exceptions, frame logic, and graph structure."
        ),
    )
    parser.add_argument(
        "--autoencoder-legal-ir-view-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale LegalIR-view-to-modal-family logits so compiler/decompiler "
            "view evidence can reduce modal-family cross entropy."
        ),
    )
    parser.add_argument(
        "--autoencoder-family-semantic-slot-legal-ir-view-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale modal-family plus semantic-slot LegalIR-view logits, letting "
            "the LegalIR view classifier specialize by legal modality and slot."
        ),
    )
    parser.add_argument(
        "--autoencoder-semantic-slot-legal-ir-view-family-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale joint semantic-slot plus LegalIR-view modal-family logits, "
            "letting bridge evidence disambiguate slots such as conditions and "
            "exceptions differently by target IR view."
        ),
    )
    parser.add_argument(
        "--autoencoder-semantic-slot-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale compact semantic-slot prototype vectors in the decoder so "
            "reconstruction can transfer through logical IR structure."
        ),
    )
    parser.add_argument(
        "--autoencoder-semantic-slot-interaction-weight",
        type=float,
        default=0.35,
        help=(
            "Weight bounded pairwise semantic-slot interactions, allowing "
            "operator+condition or exception+predicate-role compositions to learn."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-semantic-slot-interactions",
        type=int,
        default=24,
        help="Maximum semantic-slot pair features generated per sample.",
    )
    parser.add_argument(
        "--autoencoder-semantic-slot-legal-ir-view-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale the compact semantic-slot LegalIR-view classifier head for "
            "multiview cross-entropy optimization."
        ),
    )
    parser.add_argument(
        "--autoencoder-legal-ir-view-logit-scale",
        type=float,
        default=1.0,
        help=(
            "Scale the dedicated LegalIR-view feature head used for multiview "
            "cross-entropy optimization."
        ),
    )
    parser.add_argument(
        "--autoencoder-legal-ir-view-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale LegalIR-view prototype vectors in the decoder so reconstruction "
            "can transfer through frame logic, event calculus, prover, and graph views."
        ),
    )
    parser.add_argument(
        "--autoencoder-semantic-slot-legal-ir-view-embedding-weight-scale",
        type=float,
        default=0.5,
        help=(
            "Scale joint semantic-slot plus LegalIR-view decoder prototypes. "
            "This lets the same condition, exception, role, or graph slot "
            "reconstruct differently for KG, prover, frame-logic, and CEC views."
        ),
    )
    parser.add_argument(
        "--autoencoder-cosine-reconstruction-weight",
        type=float,
        default=0.25,
        help=(
            "Blend cosine-direction error into decoder feature/prototype updates "
            "alongside raw reconstruction error."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-token-features",
        type=int,
        default=48,
        help="Maximum unigram lexical features per sample in the modal head.",
    )
    parser.add_argument(
        "--autoencoder-max-token-bigram-features",
        type=int,
        default=24,
        help="Maximum bigram lexical features per sample in the modal head.",
    )
    parser.add_argument(
        "--autoencoder-max-token-trigram-features",
        type=int,
        default=12,
        help="Maximum trigram lexical features per sample in the modal head.",
    )
    parser.add_argument(
        "--autoencoder-max-legal-ir-token-features",
        type=int,
        default=24,
        help="Maximum unigram lexical features per sample in the LegalIR view head.",
    )
    parser.add_argument(
        "--autoencoder-max-legal-ir-token-bigram-features",
        type=int,
        default=12,
        help="Maximum bigram lexical features per sample in the LegalIR view head.",
    )
    parser.add_argument(
        "--autoencoder-max-legal-ir-token-trigram-features",
        type=int,
        default=8,
        help="Maximum trigram lexical features per sample in the LegalIR view head.",
    )
    parser.add_argument(
        "--autoencoder-feature-activity-reference",
        type=int,
        default=64,
        help=(
            "Feature-count reference before adaptive feature contribution "
            "down-scaling starts."
        ),
    )
    parser.add_argument(
        "--autoencoder-feature-logit-clip",
        type=float,
        default=24.0,
        help="Absolute clamp for modal and LegalIR logits after feature aggregation.",
    )
    parser.add_argument(
        "--autoencoder-bridge-workers",
        type=int,
        default=int(os.environ.get("IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS", "1") or 1),
        help=(
            "Parallel workers for per-sample legal IR bridge target evaluation. "
            "Use values above one when train/validation counts are also above one."
        ),
    )
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
        choices=CODEX_AST_SCOPES,
        default=None,
        help="Restrict the Codex worker to one AST/write-scope lane for parallel runs.",
    )
    parser.add_argument(
        "--codex-parallel-scopes",
        default=None,
        help=(
            "For paired runs, launch one Codex child per comma-separated AST scope "
            "or use 'all'. Each child claims only its scope."
        ),
    )
    parser.add_argument(
        "--codex-scope-workers",
        type=int,
        default=1,
        help=(
            "For paired parallel-scope runs, launch this many Codex children per "
            "AST scope. Each child keeps the same scope filter but uses a unique worker id."
        ),
    )
    parser.add_argument(
        "--codex-scope-worker-map",
        default="",
        help=(
            "Optional comma-separated per-scope worker override, e.g. "
            "compiler_ambiguity=2,compiler_registry=1,frame_logic=0."
        ),
    )
    parser.add_argument(
        "--codex-bundle-mode",
        choices=CODEX_BUNDLE_MODES,
        default="semantic",
        help=(
            "For Codex loops, claim plain priority batches, exact semantic "
            "bundles, or embeddings-router vector-nearest bundles in one AST scope."
        ),
    )
    parser.add_argument(
        "--codex-vector-min-similarity",
        type=float,
        default=0.72,
        help="Minimum cosine similarity for embeddings-router vector bundle neighbors.",
    )
    parser.add_argument(
        "--codex-vector-fill-min-similarity",
        type=float,
        default=0.45,
        help=(
            "Lower cosine threshold for filling remaining vector bundle slots from "
            "the same target component after strict neighbors are selected."
        ),
    )
    parser.add_argument(
        "--codex-vector-min-bundle-size",
        type=int,
        default=1,
        help=(
            "For vector bundles, wait instead of claiming a fresh undersized bundle "
            "until this many related TODOs are selected."
        ),
    )
    parser.add_argument(
        "--codex-vector-max-bundle-wait-seconds",
        type=float,
        default=0.0,
        help=(
            "Maximum age for the oldest pending vector candidate before an undersized "
            "bundle is allowed to run. Zero disables bundle patience."
        ),
    )
    parser.add_argument(
        "--codex-vector-stale-drain-cooldown-seconds",
        type=float,
        default=120.0,
        help=(
            "Cooldown per vector bundle lane after one stale undersized bundle is "
            "claimed, preventing parallel workers from all draining singletons."
        ),
    )
    parser.add_argument(
        "--codex-target-file-lane-lock-seconds",
        type=float,
        default=1200.0,
        help=(
            "Skip pending Codex TODOs whose suggested files overlap another active "
            "claimed packet for this many seconds. Zero disables target-file lanes."
        ),
    )
    parser.add_argument(
        "--codex-target-file-lane-lock-scopes",
        default="compiler_registry",
        help=(
            "Comma-separated program_synthesis_scope values that use target-file "
            "lane locks, or 'all'. Default focuses the conflict-prone registry lane."
        ),
    )
    parser.add_argument(
        "--codex-lane-lock-mode",
        choices=CODEX_LANE_LOCK_MODES,
        default="target_file",
        help=(
            "Conflict key used by Codex lane locks. 'target_file' serializes shared "
            "file hints; 'ast' serializes inferred AST/write-scope keys such as "
            "modal family-pair lanes; 'hybrid' applies both."
        ),
    )
    parser.add_argument(
        "--codex-vector-index-path",
        default=None,
        help="Optional JSON path for the Codex TODO vector index cache.",
    )
    parser.add_argument(
        "--codex-task-embeddings-provider",
        default="local_adapter",
        help="Provider passed to ipfs_datasets_py.embeddings_router for Codex TODO vectors; use 'auto' for router default.",
    )
    parser.add_argument(
        "--codex-task-embeddings-model",
        default=None,
        help="Optional embeddings model name passed to embeddings_router for Codex TODO vectors.",
    )
    parser.add_argument(
        "--codex-task-embeddings-device",
        default=None,
        help="Optional embeddings device passed to embeddings_router for Codex TODO vectors.",
    )
    parser.add_argument(
        "--codex-task-embeddings-batch-size",
        type=int,
        default=32,
        help="Batch size for embeddings_router Codex TODO vectorization.",
    )
    parser.add_argument(
        "--codex-vector-fallback-mode",
        choices=CODEX_VECTOR_FALLBACK_MODES,
        default="hash",
        help="Fallback when embeddings_router cannot vectorize TODOs: hash vectors or priority-only claiming.",
    )
    parser.add_argument(
        "--codex-merge-repair-mode",
        choices=CODEX_MERGE_REPAIR_MODES,
        default="apply_3way",
        help=(
            "When apply-to-main check fails, optionally replay the packet diff "
            "into a fresh current-main worktree with git apply --3way and retry once."
        ),
    )
    parser.add_argument(
        "--codex-merge-repair-attempts",
        type=int,
        default=1,
        help="Maximum automatic merge-repair attempts for one packet apply.",
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
        "compiler_quality_embedding_weight_entries": len(
            averaged.compiler_quality_embedding_weights
        ),
        "compiler_quality_family_logit_entries": len(
            averaged.compiler_quality_family_logits
        ),
        "logic_signature_embedding_weight_entries": len(
            averaged.logic_signature_embedding_weights
        ),
        "logic_signature_family_logit_entries": len(
            averaged.logic_signature_family_logits
        ),
        "logic_signature_legal_ir_view_logit_entries": len(
            averaged.logic_signature_legal_ir_view_logits
        ),
        "round_trip_signal_embedding_weight_entries": len(
            averaged.round_trip_signal_embedding_weights
        ),
        "round_trip_signal_family_logit_entries": len(
            averaged.round_trip_signal_family_logits
        ),
        "round_trip_signal_legal_ir_view_logit_entries": len(
            averaged.round_trip_signal_legal_ir_view_logits
        ),
        "decompiler_plan_embedding_weight_entries": len(
            averaged.decompiler_plan_embedding_weights
        ),
        "decompiler_plan_family_logit_entries": len(
            averaged.decompiler_plan_family_logits
        ),
        "decompiler_plan_legal_ir_view_logit_entries": len(
            averaged.decompiler_plan_legal_ir_view_logits
        ),
        "predicate_argument_embedding_weight_entries": len(
            averaged.predicate_argument_embedding_weights
        ),
        "predicate_argument_family_logit_entries": len(
            averaged.predicate_argument_family_logits
        ),
        "predicate_argument_legal_ir_view_logit_entries": len(
            averaged.predicate_argument_legal_ir_view_logits
        ),
        "family_embedding_weight_entries": len(averaged.family_embedding_weights),
        "family_semantic_slot_embedding_weight_entries": len(
            averaged.family_semantic_slot_embedding_weights
        ),
        "family_semantic_slot_legal_ir_view_embedding_weight_entries": len(
            averaged.family_semantic_slot_legal_ir_view_embedding_weights
        ),
        "family_legal_ir_view_embedding_weight_entries": len(
            averaged.family_legal_ir_view_embedding_weights
        ),
        "feature_embedding_weight_entries": len(averaged.feature_embedding_weights),
        "feature_family_logit_entries": len(averaged.feature_family_logits),
        "loaded_paths": loaded_paths,
        "legal_ir_view_embedding_weight_entries": len(
            averaged.legal_ir_view_embedding_weights
        ),
        "legal_ir_view_family_logit_entries": len(
            averaged.legal_ir_view_family_logits
        ),
        "missing_paths": missing_paths,
        "semantic_slot_embedding_weight_entries": len(
            averaged.semantic_slot_embedding_weights
        ),
        "semantic_slot_family_logit_entries": len(
            averaged.semantic_slot_family_logits
        ),
        "family_semantic_slot_legal_ir_view_logit_entries": len(
            averaged.family_semantic_slot_legal_ir_view_logits
        ),
        "semantic_slot_legal_ir_view_embedding_weight_entries": len(
            averaged.semantic_slot_legal_ir_view_embedding_weights
        ),
        "semantic_slot_legal_ir_view_family_logit_entries": len(
            averaged.semantic_slot_legal_ir_view_family_logits
        ),
        "semantic_slot_legal_ir_view_logit_entries": len(
            averaged.semantic_slot_legal_ir_view_logits
        ),
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
    codex_children = list(paired.get("codex_children") or [])
    if not codex_children:
        codex_children = [
            {
                "command": list(paired["codex_command"]),
                "run_id": paired["codex_run_id"],
                "scope": getattr(args, "codex_scope", None),
                "worker_id": getattr(args, "worker_id", None),
            }
        ]
    codex_child_summaries: List[Dict[str, Any]] = []
    for child in codex_children:
        child_run_id = str(child["run_id"])
        codex_child_summaries.append(
            {
                "command": list(child["command"]),
                "run_id": child_run_id,
                "scope": child.get("scope"),
                "stderr_path": str(log_dir / f"{child_run_id}.orchestrator.stderr.log"),
                "stdout_path": str(log_dir / f"{child_run_id}.orchestrator.stdout.log"),
                "worker_id": child.get("worker_id"),
            }
        )
    codex_stdout_path = Path(str(codex_child_summaries[0]["stdout_path"]))
    codex_stderr_path = Path(str(codex_child_summaries[0]["stderr_path"]))

    summary: Dict[str, Any] = {
        "autoencoder_command": list(paired["autoencoder_command"]),
        "autoencoder_run_id": paired["autoencoder_run_id"],
        "autoencoder_stderr_path": str(auto_stderr_path),
        "autoencoder_stdout_path": str(auto_stdout_path),
        "codex_command": list(paired["codex_command"]),
        "codex_children": codex_child_summaries,
        "codex_child_count": len(codex_child_summaries),
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
        _terminate_active_codex_exec_processes(signal.SIGTERM)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_signal_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)

    append_event(
        log_path,
        args.run_id,
        {
            "event": "paired_runner_started",
            "autoencoder_run_id": paired["autoencoder_run_id"],
            "codex_child_count": len(codex_child_summaries),
            "codex_children": [
                {"run_id": child["run_id"], "scope": child.get("scope")}
                for child in codex_child_summaries
            ],
            "codex_run_id": paired["codex_run_id"],
            "queue_run_id": paired["queue_run_id"],
        },
    )

    started = time.time()
    auto_process: Optional[subprocess.Popen[str]] = None
    codex_processes: Dict[str, subprocess.Popen[str]] = {}
    auto_exit_code: Optional[int] = None
    codex_exit_codes: Dict[str, Optional[int]] = {
        str(child["run_id"]): None for child in codex_child_summaries
    }
    runner_terminated_children: set[str] = set()

    try:
        with ExitStack() as stack:
            auto_stdout = stack.enter_context(auto_stdout_path.open("a", encoding="utf-8"))
            auto_stderr = stack.enter_context(auto_stderr_path.open("a", encoding="utf-8"))
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

            for child in codex_child_summaries:
                child_run_id = str(child["run_id"])
                child_stdout = stack.enter_context(
                    Path(str(child["stdout_path"])).open("a", encoding="utf-8")
                )
                child_stderr = stack.enter_context(
                    Path(str(child["stderr_path"])).open("a", encoding="utf-8")
                )
                process = subprocess.Popen(
                    list(child["command"]),
                    cwd=root,
                    stdout=child_stdout,
                    stderr=child_stderr,
                    text=True,
                )
                codex_processes[child_run_id] = process
                append_event(
                    log_path,
                    args.run_id,
                    {
                        "event": "paired_child_started",
                        "child_role": "codex",
                        "child_pid": process.pid,
                        "child_run_id": child_run_id,
                        "codex_scope": child.get("scope"),
                    },
                )

            poll_seconds = max(0.2, float(args.paired_poll_seconds))
            max_wait = float(args.duration_seconds) + max(0.0, float(args.paired_grace_seconds))
            while True:
                auto_exit_code = auto_process.poll()
                codex_exit_codes = {
                    run_id: process.poll()
                    for run_id, process in codex_processes.items()
                }
                summary["elapsed_seconds"] = round(time.time() - started, 3)
                summary["autoencoder_pid"] = auto_process.pid
                summary["codex_pids"] = {
                    run_id: process.pid for run_id, process in codex_processes.items()
                }
                summary["codex_pid"] = next(iter(summary["codex_pids"].values()), None)
                summary["autoencoder_exit_code"] = auto_exit_code
                summary["codex_exit_codes"] = codex_exit_codes
                summary["codex_exit_code"] = next(iter(codex_exit_codes.values()), None)
                summary["child_status"] = {
                    "autoencoder": "running" if auto_exit_code is None else "exited",
                    "codex": {
                        run_id: "running" if exit_code is None else "exited"
                        for run_id, exit_code in codex_exit_codes.items()
                    },
                }
                save_summary(summary_path, summary)

                if auto_exit_code is not None and all(
                    exit_code is not None for exit_code in codex_exit_codes.values()
                ):
                    break
                if stop_requested:
                    break
                if (time.time() - started) > max_wait:
                    summary["latest_stop_reason"] = "paired_timeout_grace_exceeded"
                    break
                time.sleep(poll_seconds)
    finally:
        process_labels: List[tuple[str, Optional[subprocess.Popen[str]]]] = [
            (str(paired["autoencoder_run_id"]), auto_process),
            *[(run_id, process) for run_id, process in codex_processes.items()],
        ]
        for child_run_id, process in process_labels:
            if process is None or process.poll() is not None:
                continue
            runner_terminated_children.add(child_run_id)
            process.terminate()

        termination_wait_seconds = max(
            10.0,
            min(60.0, float(args.paired_grace_seconds)),
        )
        for child_run_id, process in process_labels:
            if process is None or process.poll() is not None:
                continue
            try:
                process.wait(timeout=termination_wait_seconds)
            except subprocess.TimeoutExpired:
                runner_terminated_children.add(child_run_id)
                process.kill()
                process.wait(timeout=5.0)

        if auto_process is not None:
            auto_exit_code = auto_process.poll()
        codex_exit_codes = {
            run_id: process.poll()
            for run_id, process in codex_processes.items()
        }

        if stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_signal}"
            summary["stopped_by_signal"] = stop_signal
        summary["elapsed_seconds"] = round(time.time() - started, 3)
        summary["autoencoder_exit_code"] = auto_exit_code
        summary["codex_exit_codes"] = codex_exit_codes
        summary["codex_exit_code"] = next(iter(codex_exit_codes.values()), None)
        summary["runner_terminated_children"] = sorted(runner_terminated_children)
        summary["child_status"] = {
            "autoencoder": "running" if auto_exit_code is None else "exited",
            "codex": {
                run_id: "running" if exit_code is None else "exited"
                for run_id, exit_code in codex_exit_codes.items()
            },
        }
        summary["finished_at"] = utc_now()
        autoencoder_runner_terminated = (
            str(paired["autoencoder_run_id"]) in runner_terminated_children
        )
        autoencoder_success = _paired_autoencoder_succeeded(
            autoencoder_run_id=str(paired["autoencoder_run_id"]),
            autoencoder_exit_code=auto_exit_code,
            runner_terminated_children=runner_terminated_children,
        )
        codex_success = _paired_codex_children_succeeded(
            codex_exit_codes,
            autoencoder_exit_code=auto_exit_code,
            runner_terminated_children=runner_terminated_children,
            stop_requested=stop_requested,
        )
        summary["autoencoder_runner_terminated"] = autoencoder_runner_terminated
        summary["status"] = (
            "succeeded"
            if autoencoder_success and codex_success
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
                "codex_exit_codes": codex_exit_codes,
                "elapsed_seconds": summary["elapsed_seconds"],
                "runner_terminated_children": sorted(runner_terminated_children),
            },
        )
        for signum, handler in previous_signal_handlers.items():
            signal.signal(signum, handler)

    codex_success = _paired_codex_children_succeeded(
        codex_exit_codes,
        autoencoder_exit_code=auto_exit_code,
        runner_terminated_children=runner_terminated_children,
        stop_requested=stop_requested,
    )
    autoencoder_success = _paired_autoencoder_succeeded(
        autoencoder_run_id=str(paired["autoencoder_run_id"]),
        autoencoder_exit_code=auto_exit_code,
        runner_terminated_children=runner_terminated_children,
    )
    return 0 if autoencoder_success and codex_success else 1


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
    bridge_adapters = bridge_loss_adapter_names(args)
    bridge_evaluate_provers = bool(getattr(args, "bridge_evaluate_provers", True))
    bridge_parallel_workers = max(
        1,
        int(getattr(args, "autoencoder_bridge_workers", 1) or 1),
    )
    os.environ["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"] = str(bridge_parallel_workers)
    summary["bridge_loss_adapters"] = bridge_adapters
    summary["bridge_evaluate_provers"] = bridge_evaluate_provers
    summary["autoencoder_bridge_workers"] = bridge_parallel_workers
    summary["max_sample_text_chars"] = int(getattr(args, "max_sample_text_chars", 0) or 0)
    summary.setdefault("bridge_loss_failures", 0)
    summary.setdefault("bridge_loss_samples", 0)
    summary.setdefault("bridge_loss_signals", 0)
    summary.setdefault("bridge_metric_failures", 0)
    summary.setdefault("best_validation_logic_bridge_acceptance", -1.0)
    summary.setdefault("best_validation_logic_bridge_proof_failure_ratio", 1.0e12)
    summary.setdefault("best_validation_logic_bridge_total_loss", 1.0e12)
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
    autoencoder = AdaptiveModalAutoencoder(
        state=state,
        feature_codec=feature_codec,
        compute_device=args.autoencoder_device,
        compiler_quality_embedding_weight_scale=float(
            getattr(args, "autoencoder_compiler_quality_embedding_weight_scale", 0.5)
        ),
        compiler_quality_family_logit_scale=float(
            getattr(args, "autoencoder_compiler_quality_family_logit_scale", 1.0)
        ),
        logic_signature_embedding_weight_scale=float(
            getattr(args, "autoencoder_logic_signature_embedding_weight_scale", 0.5)
        ),
        logic_signature_family_logit_scale=float(
            getattr(args, "autoencoder_logic_signature_family_logit_scale", 1.0)
        ),
        logic_signature_legal_ir_view_logit_scale=float(
            getattr(args, "autoencoder_logic_signature_legal_ir_view_logit_scale", 1.0)
        ),
        round_trip_signal_embedding_weight_scale=float(
            getattr(args, "autoencoder_round_trip_signal_embedding_weight_scale", 0.5)
        ),
        round_trip_signal_family_logit_scale=float(
            getattr(args, "autoencoder_round_trip_signal_family_logit_scale", 1.0)
        ),
        round_trip_signal_legal_ir_view_logit_scale=float(
            getattr(args, "autoencoder_round_trip_signal_legal_ir_view_logit_scale", 1.0)
        ),
        decompiler_plan_embedding_weight_scale=float(
            getattr(args, "autoencoder_decompiler_plan_embedding_weight_scale", 0.5)
        ),
        decompiler_plan_family_logit_scale=float(
            getattr(args, "autoencoder_decompiler_plan_family_logit_scale", 1.0)
        ),
        decompiler_plan_legal_ir_view_logit_scale=float(
            getattr(args, "autoencoder_decompiler_plan_legal_ir_view_logit_scale", 1.0)
        ),
        predicate_argument_embedding_weight_scale=float(
            getattr(args, "autoencoder_predicate_argument_embedding_weight_scale", 0.5)
        ),
        predicate_argument_family_logit_scale=float(
            getattr(args, "autoencoder_predicate_argument_family_logit_scale", 1.0)
        ),
        predicate_argument_legal_ir_view_logit_scale=float(
            getattr(args, "autoencoder_predicate_argument_legal_ir_view_logit_scale", 1.0)
        ),
        embedding_head_update_normalization=float(
            getattr(args, "autoencoder_embedding_head_update_normalization", 0.5)
        ),
        family_logit_head_update_normalization=float(
            getattr(args, "autoencoder_family_logit_head_update_normalization", 0.5)
        ),
        legal_ir_view_head_update_normalization=float(
            getattr(args, "autoencoder_legal_ir_view_head_update_normalization", 0.5)
        ),
        feature_embedding_weight_scale=float(
            getattr(args, "autoencoder_feature_embedding_weight_scale", 0.5)
        ),
        family_embedding_weight_scale=float(
            getattr(args, "autoencoder_family_embedding_weight_scale", 0.5)
        ),
        family_semantic_slot_embedding_weight_scale=float(
            getattr(args, "autoencoder_family_semantic_slot_embedding_weight_scale", 0.5)
        ),
        family_semantic_slot_legal_ir_view_embedding_weight_scale=float(
            getattr(
                args,
                "autoencoder_family_semantic_slot_legal_ir_view_embedding_weight_scale",
                0.5,
            )
        ),
        family_legal_ir_view_embedding_weight_scale=float(
            getattr(args, "autoencoder_family_legal_ir_view_embedding_weight_scale", 0.5)
        ),
        semantic_slot_embedding_weight_scale=float(
            getattr(args, "autoencoder_semantic_slot_embedding_weight_scale", 0.5)
        ),
        feature_family_logit_scale=float(
            getattr(args, "autoencoder_feature_family_logit_scale", 1.0)
        ),
        semantic_slot_family_logit_scale=float(
            getattr(args, "autoencoder_semantic_slot_family_logit_scale", 1.0)
        ),
        legal_ir_view_family_logit_scale=float(
            getattr(args, "autoencoder_legal_ir_view_family_logit_scale", 1.0)
        ),
        family_semantic_slot_legal_ir_view_logit_scale=float(
            getattr(args, "autoencoder_family_semantic_slot_legal_ir_view_logit_scale", 1.0)
        ),
        semantic_slot_legal_ir_view_family_logit_scale=float(
            getattr(args, "autoencoder_semantic_slot_legal_ir_view_family_logit_scale", 1.0)
        ),
        semantic_slot_interaction_weight=float(
            getattr(args, "autoencoder_semantic_slot_interaction_weight", 0.35)
        ),
        max_semantic_slot_interactions=int(
            getattr(args, "autoencoder_max_semantic_slot_interactions", 24)
        ),
        legal_ir_view_logit_scale=float(
            getattr(args, "autoencoder_legal_ir_view_logit_scale", 1.0)
        ),
        semantic_slot_legal_ir_view_logit_scale=float(
            getattr(args, "autoencoder_semantic_slot_legal_ir_view_logit_scale", 1.0)
        ),
        legal_ir_view_embedding_weight_scale=float(
            getattr(args, "autoencoder_legal_ir_view_embedding_weight_scale", 0.5)
        ),
        semantic_slot_legal_ir_view_embedding_weight_scale=float(
            getattr(args, "autoencoder_semantic_slot_legal_ir_view_embedding_weight_scale", 0.5)
        ),
        cosine_reconstruction_weight=float(
            getattr(args, "autoencoder_cosine_reconstruction_weight", 0.25)
        ),
        max_token_features=int(getattr(args, "autoencoder_max_token_features", 48)),
        max_token_bigram_features=int(
            getattr(args, "autoencoder_max_token_bigram_features", 24)
        ),
        max_token_trigram_features=int(
            getattr(args, "autoencoder_max_token_trigram_features", 12)
        ),
        max_legal_ir_token_features=int(
            getattr(args, "autoencoder_max_legal_ir_token_features", 24)
        ),
        max_legal_ir_token_bigram_features=int(
            getattr(args, "autoencoder_max_legal_ir_token_bigram_features", 12)
        ),
        max_legal_ir_token_trigram_features=int(
            getattr(args, "autoencoder_max_legal_ir_token_trigram_features", 8)
        ),
        max_compiler_latent_profile_features=int(
            getattr(args, "autoencoder_max_compiler_latent_profile_features", 48)
        ),
        max_round_trip_bridge_features=int(
            getattr(args, "autoencoder_max_round_trip_bridge_features", 64)
        ),
        max_clause_topology_features=int(
            getattr(args, "autoencoder_max_clause_topology_features", 64)
        ),
        feature_activity_reference=int(
            getattr(args, "autoencoder_feature_activity_reference", 64)
        ),
        feature_logit_clip=float(
            getattr(args, "autoencoder_feature_logit_clip", 24.0)
        ),
    )
    summary["autoencoder_feature_family_logit_scale"] = float(
        getattr(args, "autoencoder_feature_family_logit_scale", 1.0)
    )
    summary["autoencoder_feature_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_feature_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_compiler_quality_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_compiler_quality_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_compiler_quality_family_logit_scale"] = float(
        getattr(args, "autoencoder_compiler_quality_family_logit_scale", 1.0)
    )
    summary["autoencoder_logic_signature_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_logic_signature_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_logic_signature_family_logit_scale"] = float(
        getattr(args, "autoencoder_logic_signature_family_logit_scale", 1.0)
    )
    summary["autoencoder_logic_signature_legal_ir_view_logit_scale"] = float(
        getattr(args, "autoencoder_logic_signature_legal_ir_view_logit_scale", 1.0)
    )
    summary["autoencoder_round_trip_signal_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_round_trip_signal_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_round_trip_signal_family_logit_scale"] = float(
        getattr(args, "autoencoder_round_trip_signal_family_logit_scale", 1.0)
    )
    summary["autoencoder_round_trip_signal_legal_ir_view_logit_scale"] = float(
        getattr(args, "autoencoder_round_trip_signal_legal_ir_view_logit_scale", 1.0)
    )
    summary["autoencoder_decompiler_plan_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_decompiler_plan_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_decompiler_plan_family_logit_scale"] = float(
        getattr(args, "autoencoder_decompiler_plan_family_logit_scale", 1.0)
    )
    summary["autoencoder_decompiler_plan_legal_ir_view_logit_scale"] = float(
        getattr(args, "autoencoder_decompiler_plan_legal_ir_view_logit_scale", 1.0)
    )
    summary["autoencoder_predicate_argument_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_predicate_argument_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_predicate_argument_family_logit_scale"] = float(
        getattr(args, "autoencoder_predicate_argument_family_logit_scale", 1.0)
    )
    summary["autoencoder_predicate_argument_legal_ir_view_logit_scale"] = float(
        getattr(args, "autoencoder_predicate_argument_legal_ir_view_logit_scale", 1.0)
    )
    summary["autoencoder_embedding_head_update_normalization"] = float(
        getattr(args, "autoencoder_embedding_head_update_normalization", 0.5)
    )
    summary["autoencoder_family_logit_head_update_normalization"] = float(
        getattr(args, "autoencoder_family_logit_head_update_normalization", 0.5)
    )
    summary["autoencoder_legal_ir_view_head_update_normalization"] = float(
        getattr(args, "autoencoder_legal_ir_view_head_update_normalization", 0.5)
    )
    summary["autoencoder_family_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_family_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_family_semantic_slot_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_family_semantic_slot_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_family_semantic_slot_legal_ir_view_embedding_weight_scale"] = float(
        getattr(
            args,
            "autoencoder_family_semantic_slot_legal_ir_view_embedding_weight_scale",
            0.5,
        )
    )
    summary["autoencoder_family_legal_ir_view_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_family_legal_ir_view_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_semantic_slot_family_logit_scale"] = float(
        getattr(args, "autoencoder_semantic_slot_family_logit_scale", 1.0)
    )
    summary["autoencoder_legal_ir_view_family_logit_scale"] = float(
        getattr(args, "autoencoder_legal_ir_view_family_logit_scale", 1.0)
    )
    summary["autoencoder_family_semantic_slot_legal_ir_view_logit_scale"] = float(
        getattr(args, "autoencoder_family_semantic_slot_legal_ir_view_logit_scale", 1.0)
    )
    summary["autoencoder_semantic_slot_legal_ir_view_family_logit_scale"] = float(
        getattr(args, "autoencoder_semantic_slot_legal_ir_view_family_logit_scale", 1.0)
    )
    summary["autoencoder_semantic_slot_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_semantic_slot_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_semantic_slot_interaction_weight"] = float(
        getattr(args, "autoencoder_semantic_slot_interaction_weight", 0.35)
    )
    summary["autoencoder_max_semantic_slot_interactions"] = int(
        getattr(args, "autoencoder_max_semantic_slot_interactions", 24)
    )
    summary["autoencoder_semantic_slot_legal_ir_view_logit_scale"] = float(
        getattr(args, "autoencoder_semantic_slot_legal_ir_view_logit_scale", 1.0)
    )
    summary["autoencoder_legal_ir_view_logit_scale"] = float(
        getattr(args, "autoencoder_legal_ir_view_logit_scale", 1.0)
    )
    summary["autoencoder_legal_ir_view_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_legal_ir_view_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_semantic_slot_legal_ir_view_embedding_weight_scale"] = float(
        getattr(args, "autoencoder_semantic_slot_legal_ir_view_embedding_weight_scale", 0.5)
    )
    summary["autoencoder_cosine_reconstruction_weight"] = float(
        getattr(args, "autoencoder_cosine_reconstruction_weight", 0.25)
    )
    summary["autoencoder_max_token_features"] = int(
        getattr(args, "autoencoder_max_token_features", 48)
    )
    summary["autoencoder_max_token_bigram_features"] = int(
        getattr(args, "autoencoder_max_token_bigram_features", 24)
    )
    summary["autoencoder_max_token_trigram_features"] = int(
        getattr(args, "autoencoder_max_token_trigram_features", 12)
    )
    summary["autoencoder_max_legal_ir_token_features"] = int(
        getattr(args, "autoencoder_max_legal_ir_token_features", 24)
    )
    summary["autoencoder_max_legal_ir_token_bigram_features"] = int(
        getattr(args, "autoencoder_max_legal_ir_token_bigram_features", 12)
    )
    summary["autoencoder_max_legal_ir_token_trigram_features"] = int(
        getattr(args, "autoencoder_max_legal_ir_token_trigram_features", 8)
    )
    summary["autoencoder_max_compiler_latent_profile_features"] = int(
        getattr(args, "autoencoder_max_compiler_latent_profile_features", 48)
    )
    summary["autoencoder_max_round_trip_bridge_features"] = int(
        getattr(args, "autoencoder_max_round_trip_bridge_features", 64)
    )
    summary["autoencoder_max_clause_topology_features"] = int(
        getattr(args, "autoencoder_max_clause_topology_features", 64)
    )
    summary["autoencoder_feature_activity_reference"] = int(
        getattr(args, "autoencoder_feature_activity_reference", 64)
    )
    summary["autoencoder_feature_logit_clip"] = float(
        getattr(args, "autoencoder_feature_logit_clip", 24.0)
    )
    summary.update(autoencoder.compute_backend_metadata())
    save_summary(summary_path, summary)
    supervisor = ModalTodoSupervisor(
        queue=queue,
        bridge_names=bridge_adapters,
        bridge_evaluate_provers=bridge_evaluate_provers,
        bridge_loss_evaluator=bridge_loss_evaluator_for_names(
            bridge_adapters,
            evaluate_provers=bridge_evaluate_provers,
        ),
    )
    rng = random.Random(int(summary.get("seed", 0)) + int(summary.get("cycles", 0)) + 1)
    blocked_validation_sample_ids = set(state.decoded_embeddings) | set(state.family_logits)

    append_event(
        log_path,
        args.run_id,
        {
            "bridge_loss_adapters": bridge_adapters,
            "bridge_evaluate_provers": bridge_evaluate_provers,
            "event": "detached_runner_started",
        },
    )
    laws_table = load_laws_table()
    append_event(
        log_path,
        args.run_id,
        {"event": "detached_dataset_loaded", "row_count": laws_table.num_rows},
    )
    validation_canary_count = max(
        0,
        int(getattr(args, "validation_canary_count", 0) or 0),
    )
    validation_canary_indices: List[int] = []
    validation_canary_samples: List[Any] = []
    validation_canary_sampling_attempts = 0
    if validation_canary_count > 0:
        stored_canary_indices: List[int] = []
        for raw_index in list(summary.get("validation_canary_indices", []) or []):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < laws_table.num_rows:
                stored_canary_indices.append(index)
        for index in stored_canary_indices[:validation_canary_count]:
            row = laws_table.take([index]).to_pylist()[0]
            if not _row_text_within_limit(
                row,
                int(getattr(args, "max_sample_text_chars", 0) or 0),
            ):
                continue
            validation_canary_indices.append(index)
            validation_canary_samples.append(row_to_sample(row))
        if len(validation_canary_samples) < validation_canary_count:
            (
                _unused_train_indices,
                _unused_train_samples,
                validation_canary_indices,
                validation_canary_samples,
                validation_canary_sampling_attempts,
            ) = sample_train_validation_rows(
                laws_table,
                rng,
                train_count=0,
                validation_count=validation_canary_count,
                blocked_validation_sample_ids=blocked_validation_sample_ids,
                max_sample_text_chars=int(
                    getattr(args, "max_sample_text_chars", 0) or 0
                ),
            )
        validation_canary_sample_ids = {
            sample.sample_id for sample in validation_canary_samples
        }
        blocked_validation_sample_ids.update(validation_canary_sample_ids)
        summary["validation_canary_count"] = len(validation_canary_samples)
        summary["validation_canary_indices"] = list(validation_canary_indices)
        summary["validation_canary_sampling_attempts"] = validation_canary_sampling_attempts
        save_summary(summary_path, summary)
        append_event(
            log_path,
            args.run_id,
            {
                "event": "validation_canary_selected",
                "sample_count": len(validation_canary_samples),
                "sampling_attempts": validation_canary_sampling_attempts,
                "validation_canary_indices": validation_canary_indices,
            },
        )
    else:
        validation_canary_sample_ids = set()
        summary["validation_canary_count"] = 0
        summary["validation_canary_indices"] = []

    try:
        while not stop_requested and time.time() + 8.0 < end_at:
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            cycle_learning_rate, cycle_lr_policy = _cycle_learning_rate(args, summary)
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
                blocked_train_sample_ids=validation_canary_sample_ids,
                blocked_validation_sample_ids=blocked_validation_sample_ids,
                max_sample_text_chars=int(getattr(args, "max_sample_text_chars", 0) or 0),
            )
            acceptance_validation_samples = validation_canary_samples or validation_samples
            acceptance_validation_indices = validation_canary_indices or validation_indices
            validation_mode = (
                "fixed_canary"
                if validation_canary_samples
                else "rotating_holdout"
            )
            before_train = autoencoder.evaluate(
                train_samples,
                legal_ir_bridge_names=bridge_adapters,
                legal_ir_evaluate_provers=bridge_evaluate_provers,
                legal_ir_parallel_workers=bridge_parallel_workers,
            )
            before_validation = autoencoder.evaluate(
                acceptance_validation_samples,
                legal_ir_bridge_names=bridge_adapters,
                legal_ir_evaluate_provers=bridge_evaluate_provers,
                legal_ir_parallel_workers=bridge_parallel_workers,
                use_sample_memory=False,
            )
            compiler_ir_train = compiler_ir_metric_block(train_samples, feature_codec)
            compiler_ir_validation = compiler_ir_metric_block(
                acceptance_validation_samples,
                feature_codec,
            )
            bridge_ir_train = bridge_ir_metric_block(
                train_samples,
                bridge_adapters,
                evaluate_provers=bridge_evaluate_provers,
                parallel_workers=bridge_parallel_workers,
            )
            bridge_ir_validation = bridge_ir_metric_block(
                acceptance_validation_samples,
                bridge_adapters,
                evaluate_provers=bridge_evaluate_provers,
                parallel_workers=bridge_parallel_workers,
            )
            feature_projection_report: Dict[str, Any] = {}
            generalizable_projection_epochs = max(
                0,
                int(getattr(args, "generalizable_projection_epochs", 0) or 0),
            )
            if generalizable_projection_epochs > 0 and train_samples:
                feature_projection_report = autoencoder.train_generalizable_projection(
                    train_samples,
                    validation_samples=acceptance_validation_samples,
                    epochs=generalizable_projection_epochs,
                    learning_rate=cycle_learning_rate,
                    legal_ir_bridge_names=bridge_adapters,
                    legal_ir_evaluate_provers=bridge_evaluate_provers,
                    legal_ir_parallel_workers=bridge_parallel_workers,
                    max_cosine_regression=float(
                        getattr(
                            args,
                            "generalizable_projection_max_cosine_regression",
                            0.005,
                        )
                    ),
                    max_reconstruction_regression=float(
                        getattr(
                            args,
                            "generalizable_projection_max_reconstruction_regression",
                            0.01,
                        )
                    ),
                    max_cross_entropy_regression=float(
                        getattr(
                            args,
                            "generalizable_projection_max_cross_entropy_regression",
                            0.0,
                        )
                    ),
                    max_legal_ir_loss_regression=float(
                        getattr(
                            args,
                            "generalizable_projection_max_legal_ir_loss_regression",
                            0.01,
                        )
                    ),
                    objective_cross_entropy_weight=float(
                        getattr(
                            args,
                            "generalizable_projection_objective_cross_entropy_weight",
                            1.0,
                        )
                    ),
                    objective_reconstruction_weight=float(
                        getattr(
                            args,
                            "generalizable_projection_objective_reconstruction_weight",
                            1.0,
                        )
                    ),
                    objective_cosine_gap_weight=float(
                        getattr(
                            args,
                            "generalizable_projection_objective_cosine_gap_weight",
                            1.0,
                        )
                    ),
                    objective_legal_ir_weight=float(
                        getattr(
                            args,
                            "generalizable_projection_objective_legal_ir_weight",
                            1.0,
                        )
                    ),
                    hard_example_fraction=float(
                        getattr(
                            args,
                            "generalizable_projection_hard_example_fraction",
                            1.0,
                        )
                    ),
                )
            run = supervisor.optimize(
                train_samples,
                validation_samples=acceptance_validation_samples,
                autoencoder=autoencoder,
                worker_id="random-uscode-daemon-detached",
                max_items=args.max_items,
                learning_rate=cycle_learning_rate,
                max_iterations=args.max_inner_iterations,
                target_cross_entropy_loss=0.001,
                target_cosine_similarity=0.999999,
            )
            after_train = autoencoder.evaluate(
                train_samples,
                legal_ir_bridge_names=bridge_adapters,
                legal_ir_evaluate_provers=bridge_evaluate_provers,
                legal_ir_parallel_workers=bridge_parallel_workers,
            )
            after_validation = autoencoder.evaluate(
                acceptance_validation_samples,
                legal_ir_bridge_names=bridge_adapters,
                legal_ir_evaluate_provers=bridge_evaluate_provers,
                legal_ir_parallel_workers=bridge_parallel_workers,
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
            summary.update(autoencoder.compute_backend_metadata())
            summary["latest_queue_counts"] = supervisor.queue.status_counts()
            summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
            summary["latest_feature_projection_report"] = feature_projection_report
            summary["validation_mode"] = validation_mode
            program_synthesis_status = update_program_synthesis_summary(
                summary,
                supervisor.queue,
                supervisor.policy,
            )
            summary["program_synthesis_seeded"] = int(
                summary.get("program_synthesis_seeded", 0)
            ) + sum(step.program_synthesis_seeded_count for step in run.steps)
            preinsert_deduped_count = sum(
                step.program_synthesis_deduped_count for step in run.steps
            )
            summary["program_synthesis_preinsert_deduped"] = int(
                summary.get("program_synthesis_preinsert_deduped", 0)
            ) + int(preinsert_deduped_count)
            summary["program_synthesis_semantic_deduped"] = int(
                summary.get("program_synthesis_semantic_deduped", 0)
            ) + int(semantic_deduped_count)
            summary["program_synthesis_deduped_total"] = int(
                summary.get("program_synthesis_preinsert_deduped", 0)
            ) + int(summary.get("program_synthesis_semantic_deduped", 0))
            bridge_loss_failures = sum(step.bridge_loss_failure_count for step in run.steps)
            bridge_loss_samples = sum(step.bridge_loss_sample_count for step in run.steps)
            bridge_loss_signals = sum(step.bridge_loss_signal_count for step in run.steps)
            summary["bridge_loss_failures"] = int(
                summary.get("bridge_loss_failures", 0)
            ) + int(bridge_loss_failures)
            summary["bridge_loss_samples"] = int(
                summary.get("bridge_loss_samples", 0)
            ) + int(bridge_loss_samples)
            summary["bridge_loss_signals"] = int(
                summary.get("bridge_loss_signals", 0)
            ) + int(bridge_loss_signals)
            summary["bridge_metric_failures"] = int(
                summary.get("bridge_metric_failures", 0)
            ) + int(
                bridge_ir_train.get("metric_failures", 0)
                + bridge_ir_validation.get("metric_failures", 0)
            )
            summary["latest_logic_bridge_train"] = bridge_ir_train
            summary["latest_logic_bridge_validation"] = bridge_ir_validation
            summary["metric_failures"] = int(summary.get("metric_failures", 0)) + int(
                compiler_ir_train.get("metric_failures", 0)
                + compiler_ir_validation.get("metric_failures", 0)
                + bridge_ir_train.get("metric_failures", 0)
                + bridge_ir_validation.get("metric_failures", 0)
            )
            summary["train_ce_improved_cycles"] = int(summary.get("train_ce_improved_cycles", 0)) + int(train_ce_delta > 0.0)
            summary["validation_ce_improved_cycles"] = int(summary.get("validation_ce_improved_cycles", 0)) + int(validation_ce_delta > 0.0)
            summary["train_cosine_improved_cycles"] = int(summary.get("train_cosine_improved_cycles", 0)) + int(train_cos_delta > 0.0)
            summary["validation_cosine_improved_cycles"] = int(summary.get("validation_cosine_improved_cycles", 0)) + int(validation_cos_delta > 0.0)
            plateau_threshold = max(
                1e-9,
                float(getattr(args, "learning_rate_plateau_delta", 1.0e-5)),
            )
            if validation_ce_delta <= plateau_threshold:
                summary["learning_rate_plateau_streak"] = int(
                    summary.get("learning_rate_plateau_streak", 0)
                ) + 1
            else:
                summary["learning_rate_plateau_streak"] = 0
            if validation_cos_delta < 0.0:
                summary["learning_rate_cosine_regression_streak"] = int(
                    summary.get("learning_rate_cosine_regression_streak", 0)
                ) + 1
            else:
                summary["learning_rate_cosine_regression_streak"] = 0
            summary["learning_rate_applied"] = float(cycle_learning_rate)
            summary["learning_rate_policy"] = cycle_lr_policy
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
            summary["best_validation_logic_bridge_acceptance"] = max(
                summary.get("best_validation_logic_bridge_acceptance", -1.0),
                float(bridge_ir_validation.get("acceptance_rate", -1.0)),
            )
            summary["best_validation_logic_bridge_proof_failure_ratio"] = min(
                summary.get("best_validation_logic_bridge_proof_failure_ratio", 1.0e12),
                float(bridge_ir_validation.get("proof_failure_ratio", 1.0e12)),
            )
            summary["best_validation_logic_bridge_total_loss"] = min(
                summary.get("best_validation_logic_bridge_total_loss", 1.0e12),
                float(bridge_ir_validation.get("total_loss", 1.0e12)),
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
                    "logic_bridge_train": bridge_ir_train,
                    "logic_bridge_validation": bridge_ir_validation,
                    "cycle": cycle,
                    "duration_seconds": round(time.time() - cycle_started, 3),
                    "event": "cycle",
                    "failed_validation_count": sum(step.failed_validation_count for step in run.steps),
                    "feature_projection_report": feature_projection_report,
                    "learning_rate_applied": float(cycle_learning_rate),
                    "learning_rate_policy": cycle_lr_policy,
                    "bridge_loss_failure_count": bridge_loss_failures,
                    "bridge_loss_sample_count": bridge_loss_samples,
                    "bridge_loss_signal_count": bridge_loss_signals,
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
                    "program_synthesis_preinsert_deduped_count": preinsert_deduped_count,
                    "program_synthesis_semantic_deduped_count": semantic_deduped_count,
                    "program_synthesis_deduped_total": summary.get(
                        "program_synthesis_deduped_total",
                        0,
                    ),
                    "train_cosine_delta": round(train_cos_delta, 9),
                    "train_cross_entropy_delta": round(train_ce_delta, 9),
                    "train_indices": train_indices,
                    "validation_sampling_attempts": validation_sampling_attempts,
                    "validation_cosine_delta": round(validation_cos_delta, 9),
                    "validation_cross_entropy_delta": round(validation_ce_delta, 9),
                    "validation_indices": acceptance_validation_indices,
                    "validation_mode": validation_mode,
                    "rotating_validation_indices": validation_indices,
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
        summary.update(autoencoder.compute_backend_metadata())
        summary["applied_todo_ids"] = len(autoencoder.state.applied_todo_ids)
        summary["compiler_quality_embedding_weight_entries"] = len(
            autoencoder.state.compiler_quality_embedding_weights
        )
        summary["compiler_quality_family_logit_entries"] = len(
            autoencoder.state.compiler_quality_family_logits
        )
        summary["logic_signature_embedding_weight_entries"] = len(
            autoencoder.state.logic_signature_embedding_weights
        )
        summary["logic_signature_family_logit_entries"] = len(
            autoencoder.state.logic_signature_family_logits
        )
        summary["logic_signature_legal_ir_view_logit_entries"] = len(
            autoencoder.state.logic_signature_legal_ir_view_logits
        )
        summary["round_trip_signal_embedding_weight_entries"] = len(
            autoencoder.state.round_trip_signal_embedding_weights
        )
        summary["round_trip_signal_family_logit_entries"] = len(
            autoencoder.state.round_trip_signal_family_logits
        )
        summary["round_trip_signal_legal_ir_view_logit_entries"] = len(
            autoencoder.state.round_trip_signal_legal_ir_view_logits
        )
        summary["decompiler_plan_embedding_weight_entries"] = len(
            autoencoder.state.decompiler_plan_embedding_weights
        )
        summary["decompiler_plan_family_logit_entries"] = len(
            autoencoder.state.decompiler_plan_family_logits
        )
        summary["decompiler_plan_legal_ir_view_logit_entries"] = len(
            autoencoder.state.decompiler_plan_legal_ir_view_logits
        )
        summary["predicate_argument_embedding_weight_entries"] = len(
            autoencoder.state.predicate_argument_embedding_weights
        )
        summary["predicate_argument_family_logit_entries"] = len(
            autoencoder.state.predicate_argument_family_logits
        )
        summary["predicate_argument_legal_ir_view_logit_entries"] = len(
            autoencoder.state.predicate_argument_legal_ir_view_logits
        )
        summary["decoded_embedding_entries"] = len(autoencoder.state.decoded_embeddings)
        summary["elapsed_seconds"] = round(time.time() - started_at, 3)
        summary["family_embedding_weight_entries"] = len(
            autoencoder.state.family_embedding_weights
        )
        summary["family_semantic_slot_embedding_weight_entries"] = len(
            autoencoder.state.family_semantic_slot_embedding_weights
        )
        summary["family_semantic_slot_legal_ir_view_embedding_weight_entries"] = len(
            autoencoder.state.family_semantic_slot_legal_ir_view_embedding_weights
        )
        summary["family_legal_ir_view_embedding_weight_entries"] = len(
            autoencoder.state.family_legal_ir_view_embedding_weights
        )
        summary["family_logit_entries"] = len(autoencoder.state.family_logits)
        summary["feature_embedding_weight_entries"] = len(autoencoder.state.feature_embedding_weights)
        summary["feature_family_logit_entries"] = len(autoencoder.state.feature_family_logits)
        summary["feature_legal_ir_view_logit_entries"] = len(
            autoencoder.state.feature_legal_ir_view_logits
        )
        summary["legal_ir_view_embedding_weight_entries"] = len(
            autoencoder.state.legal_ir_view_embedding_weights
        )
        summary["legal_ir_view_family_logit_entries"] = len(
            autoencoder.state.legal_ir_view_family_logits
        )
        summary["semantic_slot_embedding_weight_entries"] = len(
            autoencoder.state.semantic_slot_embedding_weights
        )
        summary["semantic_slot_family_logit_entries"] = len(
            autoencoder.state.semantic_slot_family_logits
        )
        summary["family_semantic_slot_legal_ir_view_logit_entries"] = len(
            autoencoder.state.family_semantic_slot_legal_ir_view_logits
        )
        summary["semantic_slot_legal_ir_view_embedding_weight_entries"] = len(
            autoencoder.state.semantic_slot_legal_ir_view_embedding_weights
        )
        summary["semantic_slot_legal_ir_view_family_logit_entries"] = len(
            autoencoder.state.semantic_slot_legal_ir_view_family_logits
        )
        summary["semantic_slot_legal_ir_view_logit_entries"] = len(
            autoencoder.state.semantic_slot_legal_ir_view_logits
        )
        summary["finished_at"] = utc_now()
        summary["legal_ir_view_logit_entries"] = len(
            autoencoder.state.legal_ir_view_logits
        )
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
        _terminate_active_codex_exec_processes(signal.SIGTERM)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_signal_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {
            "codex_apply_mode": args.codex_apply_mode,
            "codex_bundle_mode": args.codex_bundle_mode,
            "codex_claimed_total": 0,
            "codex_commit_mode": args.codex_commit_mode,
            "codex_exec_mode": args.codex_exec_mode,
            "codex_lane_lock_mode": args.codex_lane_lock_mode,
            "codex_merge_repair_attempts": args.codex_merge_repair_attempts,
            "codex_merge_repair_mode": args.codex_merge_repair_mode,
            "codex_scope": args.codex_scope,
            "codex_task_embeddings_provider": args.codex_task_embeddings_provider,
            "codex_vector_index_path": str(_codex_vector_index_path(args, queue_path)),
            "codex_vector_max_bundle_wait_seconds": args.codex_vector_max_bundle_wait_seconds,
            "codex_vector_min_bundle_size": args.codex_vector_min_bundle_size,
            "codex_vector_min_similarity": args.codex_vector_min_similarity,
            "codex_execution_count": 0,
            "codex_execution_failure_count": 0,
            "codex_main_apply_count": 0,
            "codex_main_apply_failure_count": 0,
            "codex_main_apply_repair_count": 0,
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
    summary.setdefault("codex_bundle_mode", args.codex_bundle_mode)
    summary.setdefault("codex_commit_mode", args.codex_commit_mode)
    summary.setdefault("codex_lane_lock_mode", args.codex_lane_lock_mode)
    summary.setdefault("codex_merge_repair_attempts", args.codex_merge_repair_attempts)
    summary.setdefault("codex_merge_repair_mode", args.codex_merge_repair_mode)
    summary.setdefault("codex_scope", args.codex_scope)
    summary.setdefault("codex_task_embeddings_provider", args.codex_task_embeddings_provider)
    summary.setdefault("codex_vector_index_path", str(_codex_vector_index_path(args, queue_path)))
    summary.setdefault("codex_vector_max_bundle_wait_seconds", args.codex_vector_max_bundle_wait_seconds)
    summary.setdefault("codex_vector_min_bundle_size", args.codex_vector_min_bundle_size)
    summary.setdefault("codex_vector_min_similarity", args.codex_vector_min_similarity)
    summary.setdefault("codex_main_apply_count", 0)
    summary.setdefault("codex_main_apply_failure_count", 0)
    summary.setdefault("codex_main_apply_repair_count", 0)
    summary.setdefault("codex_transient_requeue_count", 0)

    started_at = parse_utc(summary["started_at"])
    end_at = started_at + args.duration_seconds
    policy = ModalOptimizerPolicy()
    append_event(
        log_path,
        args.run_id,
        {
            "codex_apply_mode": args.codex_apply_mode,
            "codex_bundle_mode": args.codex_bundle_mode,
            "codex_commit_mode": args.codex_commit_mode,
            "codex_exec_mode": args.codex_exec_mode,
            "codex_lane_lock_mode": args.codex_lane_lock_mode,
            "codex_merge_repair_attempts": args.codex_merge_repair_attempts,
            "codex_merge_repair_mode": args.codex_merge_repair_mode,
            "codex_scope": args.codex_scope,
            "codex_task_embeddings_provider": args.codex_task_embeddings_provider,
            "codex_vector_index_path": str(_codex_vector_index_path(args, queue_path)),
            "codex_vector_max_bundle_wait_seconds": args.codex_vector_max_bundle_wait_seconds,
            "codex_vector_min_bundle_size": args.codex_vector_min_bundle_size,
            "codex_vector_min_similarity": args.codex_vector_min_similarity,
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
            vector_claim_report: Dict[str, Any] = {}
            bundle_mode = str(getattr(args, "codex_bundle_mode", "semantic")).strip().lower()
            if bundle_mode == "vector":
                claimed, queue, status, vector_claim_report = _claim_vector_program_synthesis_batch(
                    args=args,
                    queue_path=queue_path,
                    worker_id=worker_id,
                    policy=policy,
                    execution_mode=execution_mode,
                    summary=summary,
                )
            else:
                with queue_file_lock(queue_path):
                    queue = ModalTodoQueue.load_jsonl(queue_path)
                    supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
                    claimed = supervisor.claim_program_synthesis_batch(
                        worker_id=worker_id,
                        max_items=args.max_items,
                        program_synthesis_scope=getattr(args, "codex_scope", None),
                        semantic_bundle=(bundle_mode == "semantic"),
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
                if vector_claim_report:
                    packet["vector_claim_report"] = dict(vector_claim_report)
                    _save_packet_if_possible(
                        packet,
                        Path(str(packet["packet_path"])) if packet.get("packet_path") else None,
                    )
                if args.codex_exec_mode == "codex_cli":
                    packet = execute_codex_work_packet(
                        packet,
                        apply_mode=args.codex_apply_mode,
                        commit_mode=args.codex_commit_mode,
                        codex_command=args.codex_command,
                        merge_repair_attempts=args.codex_merge_repair_attempts,
                        merge_repair_mode=args.codex_merge_repair_mode,
                        model=args.codex_model,
                        sandbox=args.codex_sandbox,
                        timeout_seconds=args.codex_timeout_seconds,
                        validation_commands=_codex_validation_commands_for_todos(claimed),
                    )
                    exec_status = str(
                        dict(packet.get("codex_exec", {})).get("status", "unknown")
                    )
                    transient_requeue = _codex_packet_should_requeue_transient(packet)
                    finalize_exec_status = (
                        "transient_failure" if transient_requeue else exec_status
                    )
                    with queue_file_lock(queue_path):
                        queue = ModalTodoQueue.load_jsonl(queue_path)
                        supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
                        finalize_report = supervisor.finalize_program_synthesis_batch(
                            claimed,
                            codex_exec_status=finalize_exec_status,
                            patch_status=(
                                str(packet.get("patch_status"))
                                if packet.get("patch_status") is not None
                                else None
                            ),
                            validation_report=_codex_packet_validation_report(packet),
                        )
                        if finalize_report["updated"]:
                            queue.save_jsonl(queue_path)
                        status = update_program_synthesis_summary(
                            summary,
                            queue,
                            policy,
                            execution_mode=execution_mode,
                        )
                    if transient_requeue:
                        packet["transient_requeue"] = dict(finalize_report)
                        _save_packet_if_possible(
                            packet,
                            Path(str(packet["packet_path"])) if packet.get("packet_path") else None,
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
                    and not packet.get("transient_requeue")
                ):
                    summary["codex_execution_failure_count"] = int(
                        summary.get("codex_execution_failure_count", 0)
                    ) + 1
            if packet.get("transient_requeue"):
                summary["codex_transient_requeue_count"] = int(
                    summary.get("codex_transient_requeue_count", 0)
                ) + int(
                    dict(packet.get("transient_requeue", {})).get("requeued_count", 0)
                )
            main_apply_status = str(packet.get("main_apply_status", "")).strip().lower()
            if main_apply_status == "applied":
                summary["codex_main_apply_count"] = int(
                    summary.get("codex_main_apply_count", 0)
                ) + 1
                if str(packet.get("main_apply_repair_status", "")).strip().lower() == "repaired":
                    summary["codex_main_apply_repair_count"] = int(
                        summary.get("codex_main_apply_repair_count", 0)
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
            if vector_claim_report:
                summary["latest_codex_vector_claim_report"] = dict(vector_claim_report)
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
                    "codex_bundle_mode": getattr(args, "codex_bundle_mode", None),
                    "codex_vector_claim_report": vector_claim_report,
                    "duration_seconds": round(time.time() - cycle_started, 3),
                    "event": "codex_program_synthesis_cycle",
                    "main_apply_status": packet.get("main_apply_status"),
                    "main_apply_repair_status": packet.get("main_apply_repair_status"),
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
                    "transient_requeue": packet.get("transient_requeue"),
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
