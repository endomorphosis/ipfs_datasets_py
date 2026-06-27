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
import math
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import AbstractSet, Any, Callable, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence


def _ensure_sibling_ipfs_accelerate_py_on_path() -> None:
    """Make a sibling ipfs_accelerate_py checkout importable when it is not installed."""

    candidates: list[Path] = []
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "ipfs_accelerate_py")
    try:
        candidates.append(Path.home() / "ipfs_accelerate_py")
    except (OSError, RuntimeError):
        pass

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        runtime_path = (
            candidate
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "todo_daemon"
            / "supervisor_runtime.py"
        )
        if runtime_path.is_file():
            candidate_text = str(candidate)
            if candidate_text not in sys.path:
                sys.path.insert(0, candidate_text)
            return


_ensure_sibling_ipfs_accelerate_py_on_path()
try:
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.supervisor_runtime import (
        ChildSummaryHealthSpec,
        child_exit_should_restart as accelerate_child_exit_should_restart,
        install_stop_signal_handlers as accelerate_install_stop_signal_handlers,
        launch_process_child as accelerate_launch_process_child,
        run_process_group_capture as accelerate_run_process_group_capture,
        supervised_child_group_succeeded as accelerate_supervised_child_group_succeeded,
        supervised_child_succeeded as accelerate_supervised_child_succeeded,
        summarize_child_summary_files as accelerate_summarize_child_summary_files,
        terminate_process_group as accelerate_terminate_process_group,
        terminate_processes_with_grace as accelerate_terminate_processes_with_grace,
        terminate_process_with_grace as accelerate_terminate_process_with_grace,
        timestamp_age_seconds as accelerate_timestamp_age_seconds,
    )
except ModuleNotFoundError:
    class ChildSummaryHealthSpec:
        def __init__(
            self,
            *,
            numeric_total_fields: Sequence[str] = (),
            scope_field: str = "",
            waiting_reasons: AbstractSet[str] = frozenset(),
        ) -> None:
            self.numeric_total_fields = tuple(numeric_total_fields)
            self.scope_field = str(scope_field or "")
            self.waiting_reasons = frozenset(waiting_reasons)

    class _TerminationResult:
        def __init__(self, initial_exit_code: Optional[int], final_exit_code: Optional[int]):
            self.initial_exit_code = initial_exit_code
            self.final_exit_code = final_exit_code

    def accelerate_timestamp_age_seconds(timestamp: Any) -> Optional[float]:
        if not timestamp:
            return None
        try:
            value = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - value).total_seconds())

    def accelerate_summarize_child_summary_files(
        paths: Sequence[Path],
        *,
        spec: ChildSummaryHealthSpec,
        stale_seconds: float,
    ) -> Dict[str, Any]:
        summaries: List[Mapping[str, Any]] = []
        age_by_child: Dict[str, float] = {}
        numeric_totals = {field: 0.0 for field in spec.numeric_total_fields}
        scope_counts: Dict[str, int] = {}
        latest_stop_reasons: Dict[str, str] = {}
        stale_child_ids: List[str] = []
        waiting_count = 0
        active_count = 0
        now = datetime.now(timezone.utc)
        for path in paths:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, Mapping):
                continue
            summaries.append(data)
            child_id = str(data.get("run_id") or data.get("worker_id") or path)
            timestamp = data.get("heartbeat_at") or data.get("updated_at")
            age = accelerate_timestamp_age_seconds(timestamp)
            if age is not None:
                age_by_child[child_id] = age
                if age > max(0.0, float(stale_seconds)):
                    stale_child_ids.append(child_id)
            elif timestamp is None:
                stale_child_ids.append(child_id)
            for field in spec.numeric_total_fields:
                try:
                    numeric_totals[field] += float(data.get(field) or 0.0)
                except (TypeError, ValueError):
                    pass
            if spec.scope_field:
                scope = str(data.get(spec.scope_field) or "")
                if scope:
                    scope_counts[scope] = scope_counts.get(scope, 0) + 1
            reason = str(data.get("stop_reason") or data.get("latest_stop_reason") or "")
            if reason:
                latest_stop_reasons[child_id] = reason
            if reason in spec.waiting_reasons:
                waiting_count += 1
            if not reason or data.get("status") in {"running", "active"}:
                active_count += 1
        return {
            "active_count": active_count,
            "latest_stop_reasons": latest_stop_reasons,
            "numeric_totals": numeric_totals,
            "scope_counts": scope_counts,
            "stale_child_ids": stale_child_ids,
            "summary_age_seconds": age_by_child,
            "summary_count": len(summaries),
            "waiting_count": waiting_count,
        }

    def accelerate_supervised_child_succeeded(
        *,
        child_id: str,
        exit_code: Optional[int],
        runner_terminated_child_ids: Sequence[str] = (),
        allow_runner_terminated: bool = False,
    ) -> bool:
        if exit_code == 0:
            return True
        return bool(allow_runner_terminated and child_id in set(runner_terminated_child_ids))

    def accelerate_supervised_child_group_succeeded(
        exit_codes: Mapping[str, Optional[int]],
        *,
        runner_terminated_child_ids: Sequence[str] = (),
        stop_requested: bool = False,
        allow_runner_terminated: bool = False,
    ) -> bool:
        return all(
            accelerate_supervised_child_succeeded(
                child_id=str(child_id),
                exit_code=exit_code,
                runner_terminated_child_ids=runner_terminated_child_ids,
                allow_runner_terminated=allow_runner_terminated or stop_requested,
            )
            for child_id, exit_code in exit_codes.items()
        )

    def accelerate_child_exit_should_restart(
        *,
        exit_code: Optional[int],
        restart_count: int,
        restart_limit: int,
        stop_requested: bool = False,
    ) -> bool:
        return (
            not stop_requested
            and exit_code not in (0, None)
            and int(restart_count) < int(restart_limit)
        )

    def accelerate_launch_process_child(command: Sequence[str], **kwargs: Any) -> subprocess.Popen[str]:
        return subprocess.Popen(list(command), **kwargs)

    def accelerate_run_process_group_capture(
        command: Sequence[str],
        *,
        cwd: Path,
        env: Optional[Mapping[str, str]] = None,
        input_text: Optional[str] = None,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        started = time.time()
        try:
            completed = subprocess.run(
                list(command),
                cwd=str(cwd),
                env=dict(env) if env is not None else None,
                input=input_text,
                text=True,
                capture_output=True,
                timeout=max(0.1, float(timeout_seconds)),
                start_new_session=True,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "duration_seconds": time.time() - started,
                "exit_code": None,
                "status": "timeout",
                "stderr": _process_text(exc.stderr),
                "stdout": _process_text(exc.stdout),
            }
        return {
            "duration_seconds": time.time() - started,
            "exit_code": completed.returncode,
            "status": "passed" if completed.returncode == 0 else "failed",
            "stderr": completed.stderr,
            "stdout": completed.stdout,
        }

    def accelerate_terminate_process_group(process: subprocess.Popen[str], signum: int) -> None:
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        except OSError:
            process.send_signal(signum)

    def accelerate_terminate_process_with_grace(
        process: subprocess.Popen[str],
        *,
        grace_seconds: float,
        kill_wait_seconds: float = 5.0,
    ) -> _TerminationResult:
        initial = process.poll()
        if initial is not None:
            return _TerminationResult(initial, initial)
        accelerate_terminate_process_group(process, signal.SIGTERM)
        try:
            final = process.wait(timeout=max(0.0, float(grace_seconds)))
        except subprocess.TimeoutExpired:
            accelerate_terminate_process_group(process, signal.SIGKILL)
            try:
                final = process.wait(timeout=max(0.0, float(kill_wait_seconds)))
            except subprocess.TimeoutExpired:
                final = process.poll()
        return _TerminationResult(initial, final)

    def accelerate_terminate_processes_with_grace(
        labeled_processes: Sequence[tuple[str, subprocess.Popen[str]]],
        *,
        grace_seconds: float,
        kill_wait_seconds: float = 5.0,
    ) -> Dict[str, _TerminationResult]:
        return {
            str(label): accelerate_terminate_process_with_grace(
                process,
                grace_seconds=grace_seconds,
                kill_wait_seconds=kill_wait_seconds,
            )
            for label, process in labeled_processes
        }

    def accelerate_install_stop_signal_handlers(on_signal: Optional[Any] = None) -> Dict[str, Any]:
        return {"stop_requested": False, "on_signal": on_signal}
except ImportError:  # pragma: no cover - exercised when reusable supervisor runtime is absent.
    class ChildSummaryHealthSpec:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    def accelerate_timestamp_age_seconds(timestamp: Any) -> Optional[float]:
        if timestamp in (None, ""):
            return None
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())

    def accelerate_run_process_group_capture(
        args: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        timeout = kwargs.pop("timeout", None)
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            **kwargs,
        )

    def accelerate_launch_process_child(
        args: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.Popen[str]:
        return subprocess.Popen(
            list(args),
            start_new_session=True,
            text=True,
            **kwargs,
        )

    def accelerate_terminate_process_group(
        process: subprocess.Popen[Any],
        signum: int = signal.SIGTERM,
    ) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signum)
        except ProcessLookupError:
            return

    def accelerate_terminate_process_with_grace(
        process: subprocess.Popen[Any],
        *,
        timeout: float = 5.0,
        kill_timeout: float = 2.0,
    ) -> Dict[str, Any]:
        if process.poll() is not None:
            return {"status": "already_exited", "returncode": process.returncode}
        process.terminate()
        try:
            return {"status": "terminated", "returncode": process.wait(timeout=timeout)}
        except subprocess.TimeoutExpired:
            process.kill()
            return {"status": "killed", "returncode": process.wait(timeout=kill_timeout)}

    def accelerate_terminate_processes_with_grace(
        processes: Sequence[subprocess.Popen[Any]],
        **kwargs: Any,
    ) -> list[Dict[str, Any]]:
        return [
            accelerate_terminate_process_with_grace(process, **kwargs)
            for process in processes
        ]

    def accelerate_supervised_child_succeeded(*_args: Any, **kwargs: Any) -> bool:
        return int(kwargs.get("returncode", 0) or 0) == 0

    def accelerate_supervised_child_group_succeeded(*_args: Any, **kwargs: Any) -> bool:
        return int(kwargs.get("returncode", 0) or 0) == 0

    def accelerate_child_exit_should_restart(*_args: Any, **kwargs: Any) -> bool:
        return int(kwargs.get("returncode", 0) or 0) != 0

    def accelerate_summarize_child_summary_files(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"status": "unavailable", "summary_count": 0, "summaries": []}

    def accelerate_install_stop_signal_handlers(on_signal: Optional[Any] = None) -> Dict[str, Any]:
        stop_state: Dict[str, Any] = {"stop_requested": False, "signal": None}

        def _handler(signum: int, _frame: Any) -> None:
            stop_state["stop_requested"] = True
            stop_state["signal"] = signum
            if on_signal is not None:
                on_signal(signum)

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
        return stop_state

import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
    decoded_modal_phrase_slot_text_map,
    modal_text_token_similarity,
)
from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES
from ipfs_datasets_py.logic.submodule_registry import (
    logic_optimizer_scope_for_component,
    logic_optimizer_target_file_hints,
    logic_submodule_specs,
)
from ipfs_datasets_py.optimizers.agentic.patch_control import PatchManager, WorktreeManager
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_LOW_RANK_DEFAULT_RANK,
    MODAL_AUTOENCODER_LOW_RANK_STATE_SCHEMA_VERSION,
    MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    ModalAutoencoderTrainingState,
    PROJECTION_DEADBAND_DEFAULT_HARD_GUARDRAILS,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS,
    ModalOptimizerPolicy,
    ModalOptimizationRun,
    ModalTodo,
    ModalTodoQueue,
    ModalTodoSupervisor,
    PROGRAM_SYNTHESIS_ACTION_TARGETS,
    bridge_loss_evaluator_for_names,
    program_synthesis_todo_embedding_text,
    select_program_synthesis_vector_bundle,
    _program_synthesis_sample_payloads,
    _program_synthesis_scope,
    _program_synthesis_target_metrics,
    _program_synthesis_validation_failure_kind,
    _program_synthesis_validation_commands,
    _program_todo_id,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
    HF_USCODE_DATASET_ID,
    USCODE_EMBEDDINGS_PARQUET,
    USCODE_LAWS_PARQUET,
    USCodeParquetRecord,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    stable_mock_embedding,
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
DEFAULT_AUTOENCODER_METRIC_BRIDGE_ADAPTERS = (
    "modal_frame_logic",
    "deontic_norms",
    "fol_tdfol",
)
DEFAULT_AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS: tuple[str, ...] = ()
DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLES = 1
AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS_ENV = (
    "IPFS_DATASETS_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS"
)
DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS = 800
BRIDGE_EVALUATE_PROVERS_ENV = "IPFS_DATASETS_BRIDGE_EVALUATE_PROVERS"
DEFAULT_BRIDGE_EVALUATE_PROVERS = False

CODEX_AST_SCOPES = tuple(
    dict.fromkeys(
        scope
        for scope in (
            "compiler_parser",
            "compiler_registry",
            "compiler_ambiguity",
            "autoencoder",
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
    "modal.autoencoder": [
        "ipfs_datasets_py/logic/modal/synthesis.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_todo_daemon.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_modal_daemon_runner.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_autoencoder.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ],
    "logic.optimizer.autoencoder": [
        "ipfs_datasets_py/logic/modal/synthesis.py",
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

FAST_BOOTSTRAP_PROGRAM_SYNTHESIS_ACTIONS = (
    "add_deterministic_parser_rule",
    "add_or_review_modal_ambiguity_policy",
    "refine_modal_family_cue_rules",
    "increase_modal_ir_span_coverage",
    "refine_semantic_decompiler_reconstruction",
    "refine_typed_ir_or_decompiler_slots",
    "improve_flogic_frame_alignment",
    "repair_flogic_ontology_constraints",
    "repair_multiview_legal_ir_loss",
    "repair_deontic_bridge_quality_gate",
    "repair_tdfol_bridge_parse",
    "repair_cec_dcec_bridge",
    "repair_multiview_legal_ir_graph_projection",
    "repair_external_prover_router",
    "repair_zkp_attestation_bridge",
)

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
CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS = 600.0
CODEX_APPLY_VALIDATION_TIMEOUT_SECONDS = 600.0
CODEX_TARGET_METRIC_TIMEOUT_SECONDS = 120.0
CODEX_TARGET_METRIC_MAX_SAMPLES = 2
COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS_ENV = (
    "IPFS_DATASETS_COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS"
)
COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS_ENV = (
    "IPFS_DATASETS_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS"
)
COMPILER_IR_METRIC_TEXT_POLICY_ENV = "IPFS_DATASETS_COMPILER_IR_METRIC_TEXT_POLICY"
COMPILER_IR_METRIC_TEXT_POLICIES = ("skip", "truncate")
DEFAULT_COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS = 400
DEFAULT_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS = 10.0
DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY = "truncate"
DEFAULT_VALIDATION_CANARY_COUNT = 8
COMPILER_IR_TRAIN_MODE_ENV = "IPFS_DATASETS_COMPILER_IR_TRAIN_MODE"
COMPILER_IR_TRAIN_EVERY_N_CYCLES_ENV = (
    "IPFS_DATASETS_COMPILER_IR_TRAIN_EVERY_N_CYCLES"
)
COMPILER_IR_GUIDED_TRAIN_MODE_ENV = "IPFS_DATASETS_COMPILER_IR_GUIDED_TRAIN_MODE"
COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES_ENV = (
    "IPFS_DATASETS_COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES"
)
DEFAULT_COMPILER_IR_TRAIN_MODE = "periodic"
DEFAULT_COMPILER_IR_TRAIN_EVERY_N_CYCLES = 4
DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE = "periodic"
DEFAULT_COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES = 4
AUTOENCODER_BEFORE_TRAIN_EVAL_MODE_ENV = (
    "IPFS_DATASETS_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE"
)
AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES_ENV = (
    "IPFS_DATASETS_AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES"
)
AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE_ENV = (
    "IPFS_DATASETS_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE"
)
AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES_ENV = (
    "IPFS_DATASETS_AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES"
)
AUTOENCODER_TODO_SUPERVISOR_MODE_ENV = (
    "IPFS_DATASETS_AUTOENCODER_TODO_SUPERVISOR_MODE"
)
AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN_ENV = (
    "IPFS_DATASETS_AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN"
)
DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE = "periodic"
DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES = 4
DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE = "periodic"
DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES = 4
DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE = "starved"
DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN = 12
BRIDGE_IR_REPORT_CACHE_MAX = 4096
USCODE_DAEMON_METRIC_SCHEMA_VERSION = "uscode-modal-daemon-metrics-v2"
USCODE_DAEMON_ROLLOUT_STAGE = "observability-v1"
AUTOENCODER_LOW_RANK_SIDECAR_MAX_VECTORS_ENV = (
    "IPFS_DATASETS_AUTOENCODER_LOW_RANK_SIDECAR_MAX_VECTORS"
)
AUTOENCODER_LOW_RANK_SIDECAR_RANK_ENV = (
    "IPFS_DATASETS_AUTOENCODER_LOW_RANK_SIDECAR_RANK"
)
AUTOENCODER_LOW_RANK_LOAD_ENV = "IPFS_DATASETS_AUTOENCODER_LOW_RANK_LOAD"
AUTOENCODER_LOW_RANK_LOAD_OVERWRITE_ENV = (
    "IPFS_DATASETS_AUTOENCODER_LOW_RANK_LOAD_OVERWRITE"
)
AUTOENCODER_PROJECTION_DEADBAND_MODE_ENV = (
    "IPFS_DATASETS_AUTOENCODER_PROJECTION_DEADBAND_MODE"
)
AUTOENCODER_MAX_CE_DEADBAND_ENV = "IPFS_DATASETS_AUTOENCODER_MAX_CE_DEADBAND"
AUTOENCODER_MAX_COSINE_REGRESSION_ENV = (
    "IPFS_DATASETS_AUTOENCODER_MAX_COSINE_REGRESSION"
)
AUTOENCODER_HARD_GUARDRAIL_METRICS_ENV = (
    "IPFS_DATASETS_AUTOENCODER_HARD_GUARDRAIL_METRICS"
)
AUTOENCODER_PROJECTION_PRESCREEN_MODE_ENV = (
    "IPFS_DATASETS_AUTOENCODER_PROJECTION_PRESCREEN_MODE"
)
AUTOENCODER_PROJECTION_PRESCREEN_TOP_K_ENV = (
    "IPFS_DATASETS_AUTOENCODER_PROJECTION_PRESCREEN_TOP_K"
)
AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES_ENV = (
    "IPFS_DATASETS_AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES"
)
DEFAULT_AUTOENCODER_PROJECTION_DEADBAND_MODE = "shadow"
DEFAULT_AUTOENCODER_MAX_CE_DEADBAND = 1.0e-4
DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_MODE = "off"
DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_TOP_K = 3
DEFAULT_AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES = 8
DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS = 180.0
LEGAL_IR_METRIC_DISK_CACHE_VERSION = "legal-ir-metric-disk-cache-v1"
LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV = "IPFS_DATASETS_LEGAL_IR_METRIC_CACHE_DIR"
LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV = "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"
_FALSE_ENV_VALUES = {"0", "false", "no", "off", "none", "disabled"}
_BRIDGE_IR_REPORT_CACHE_LOCK = threading.Lock()
_BRIDGE_IR_REPORT_CACHE: Dict[str, Any] = {}
_METRIC_CODE_FINGERPRINT_LOCK = threading.Lock()
_METRIC_CODE_FINGERPRINT_VALUE: Optional[str] = None
_COMPILER_IR_METRIC_BLOCK_CACHE_VERSION = "compiler-ir-metric-block-cache-v5"
_COMPILER_IR_GUIDANCE_CACHE_POLICY = "codec-output-contract-v1"
_COMPILER_IR_GUIDANCE_DIAGNOSTICS_VERSION = "compiler-guidance-diagnostics-v1"
_COMPILER_IR_SAMPLE_CACHE_VERSION = "compiler-ir-metric-sample-cache-v5"
_COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY = "timeout_surface_fallback_per_sample_budget_v2"
_COMPILER_IR_SAMPLE_CODE_FINGERPRINT_LOCK = threading.Lock()
_COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE: Optional[str] = None
_ACTIVE_CODEX_EXEC_PROCESSES: List[subprocess.Popen[str]] = []
CODEX_WORKTREE_ARTIFACT_FILENAMES = {"changes.patch"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return max(float(minimum), value)


def _env_optional_float(name: str, *, minimum: float = 0.0) -> Optional[float]:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(float(minimum), value)


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(default)
    return max(int(minimum), value)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return bool(default)
    return str(raw).strip().lower() not in _FALSE_ENV_VALUES


def _should_run_cycle_tests(cycle: int, test_every_cycles: int) -> bool:
    cadence = int(test_every_cycles or 0)
    if cadence <= 0:
        return False
    return int(cycle) % cadence == 0


def _should_run_cycle_cadence(
    *,
    cycle: int,
    mode: str,
    every_n_cycles: int,
) -> bool:
    normalized = str(mode or "every_cycle").strip().lower()
    if normalized == "every_cycle":
        return True
    if normalized == "off":
        return False
    if normalized != "periodic":
        return True
    cadence = max(1, int(every_n_cycles or 1))
    return int(cycle) > 0 and int(cycle) % cadence == 0


def _program_synthesis_open_count(status: Mapping[str, Any]) -> int:
    """Count Codex-facing TODOs that still require worker attention."""

    try:
        pending = int(status.get("pending") or 0)
    except (TypeError, ValueError):
        pending = 0
    try:
        claimed = int(status.get("claimed") or 0)
    except (TypeError, ValueError):
        claimed = 0
    return max(0, pending) + max(0, claimed)


def _todo_supervisor_skip_decision(
    *,
    mode: str,
    program_synthesis_status: Mapping[str, Any],
    min_open: int,
) -> Dict[str, Any]:
    normalized = str(mode or DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE).strip().lower()
    if normalized not in {"every_cycle", "starved", "off"}:
        normalized = DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE
    threshold = max(1, int(min_open or 1))
    open_count = _program_synthesis_open_count(program_synthesis_status)
    if normalized == "off":
        skip = True
        reason = "todo_supervisor_disabled"
    elif normalized == "starved" and open_count >= threshold:
        skip = True
        reason = "program_synthesis_queue_sufficient"
    else:
        skip = False
        reason = ""
    return {
        "mode": normalized,
        "min_open": threshold,
        "open_count": open_count,
        "program_synthesis_status": dict(program_synthesis_status),
        "skip_reason": reason,
        "skipped": skip,
    }


def _stable_metric_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _metric_disk_cache_enabled() -> bool:
    raw = str(os.environ.get(LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV) or "").strip().lower()
    return raw not in _FALSE_ENV_VALUES


def _default_metric_disk_cache_dir() -> Path:
    try:
        repo_root = Path(__file__).resolve().parents[3]
    except (IndexError, OSError, RuntimeError):
        repo_root = Path.cwd()
    return repo_root / "workspace" / "test-logs" / "legal-ir-metric-cache"


def _metric_disk_cache_dir() -> Optional[Path]:
    if not _metric_disk_cache_enabled():
        return None
    raw = str(os.environ.get(LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV) or "").strip()
    if raw.lower() in _FALSE_ENV_VALUES:
        return None
    return Path(raw).expanduser() if raw else _default_metric_disk_cache_dir()


def _metric_code_fingerprint() -> str:
    global _METRIC_CODE_FINGERPRINT_VALUE
    with _METRIC_CODE_FINGERPRINT_LOCK:
        if _METRIC_CODE_FINGERPRINT_VALUE:
            return _METRIC_CODE_FINGERPRINT_VALUE
        try:
            package_root = Path(__file__).resolve().parents[2]
        except (IndexError, OSError, RuntimeError):
            package_root = Path.cwd()
        candidates = [
            Path(__file__),
            package_root / "logic" / "bridge",
            package_root / "logic" / "modal",
            package_root
            / "knowledge_graphs"
            / "neo4j_compat"
            / "legal_ir_projection.py",
        ]
        tokens: List[str] = []
        for candidate in candidates:
            paths = (
                sorted(candidate.rglob("*.py"))
                if candidate.is_dir()
                else [candidate]
            )
            for path in paths:
                try:
                    stat = path.stat()
                except (OSError, RuntimeError):
                    continue
                try:
                    relative = path.relative_to(package_root)
                except ValueError:
                    relative = path
                tokens.append(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}")
        if not tokens:
            _METRIC_CODE_FINGERPRINT_VALUE = "unknown"
        else:
            _METRIC_CODE_FINGERPRINT_VALUE = hashlib.sha256(
                "\n".join(tokens).encode("utf-8")
            ).hexdigest()
        return _METRIC_CODE_FINGERPRINT_VALUE


def _compiler_ir_sample_code_fingerprint() -> str:
    global _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE
    with _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_LOCK:
        if _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE:
            return _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE
        try:
            package_root = Path(__file__).resolve().parents[2]
        except (IndexError, OSError, RuntimeError):
            package_root = Path.cwd()
        candidates = [
            package_root / "logic" / "modal",
            package_root / "optimizers" / "logic_theorem_optimizer" / "frame_bm25_selector.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "legal_modal_parser.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "legal_samples.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "modal_ir.py",
        ]
        tokens: List[str] = []
        for candidate in candidates:
            paths = (
                sorted(candidate.rglob("*.py"))
                if candidate.is_dir()
                else [candidate]
            )
            for path in paths:
                try:
                    stat = path.stat()
                except (OSError, RuntimeError):
                    continue
                try:
                    relative = path.relative_to(package_root)
                except ValueError:
                    relative = path
                tokens.append(f"{relative}:{stat.st_mtime_ns}:{stat.st_size}")
        _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE = (
            hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()
            if tokens
            else "unknown"
        )
        return _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE


def _compiler_ir_metric_sample_disk_cache_key(payload: Mapping[str, Any]) -> str:
    wrapper = {
        "code_fingerprint": _compiler_ir_sample_code_fingerprint(),
        "kind": "compiler_ir_metric_sample",
        "payload": payload,
        "version": _COMPILER_IR_SAMPLE_CACHE_VERSION,
    }
    return hashlib.sha256(_stable_metric_json(wrapper).encode("utf-8")).hexdigest()


def _compiler_ir_metric_sample_timeout_disk_cache_key(
    payload: Mapping[str, Any]
) -> str:
    wrapper = {
        "code_fingerprint": _compiler_ir_sample_code_fingerprint(),
        "kind": "compiler_ir_metric_sample_timeout",
        "payload": payload,
        "version": _COMPILER_IR_SAMPLE_CACHE_VERSION,
    }
    return hashlib.sha256(_stable_metric_json(wrapper).encode("utf-8")).hexdigest()


def _metric_cache_object_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _metric_cache_object_payload(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_metric_cache_object_payload(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            "attrs": {
                str(key): _metric_cache_object_payload(item)
                for key, item in sorted(vars(value).items())
                if not str(key).startswith("_")
            },
            "type": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
        }
    return repr(value)


_COMPILER_IR_GUIDANCE_CACHE_CONTRACT_KEYS = (
    "bundle",
    "compiler_guidance_action",
    "compiler_guidance_route",
    "compiler_guidance_selected_frame_after",
    "compiler_guidance_todo_routes",
    "evidence",
    "evidences",
    "family_distribution",
    "feature_groups",
    "legal_ir_predicted_view_distribution",
    "legal_ir_target_view_distribution",
    "legal_ir_view_gap_distribution",
    "legal_ir_view_metrics",
    "ranked_guidance_features",
    "routes",
    "sample_id",
    "sample_memory_used",
    "semantic_bundle",
    "synthesis_focus",
    "target_component",
    "todo_routes",
)


def _compiler_ir_metric_guidance_cache_payload(
    compiler_guidance: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the guidance subset that can affect deterministic compiler metrics."""

    if not isinstance(compiler_guidance, Mapping) or not compiler_guidance:
        return None
    contract = {
        key: _metric_cache_object_payload(compiler_guidance.get(key))
        for key in _COMPILER_IR_GUIDANCE_CACHE_CONTRACT_KEYS
        if key in compiler_guidance
    }
    return {
        "contract": contract,
        "policy": _COMPILER_IR_GUIDANCE_CACHE_POLICY,
    }


def _metric_mapping_to_namespace(value: Any) -> Any:
    if isinstance(value, Mapping):
        return SimpleNamespace(
            **{
                str(key): _metric_mapping_to_namespace(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_metric_mapping_to_namespace(item) for item in value]
    return value


def _metric_mapping_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, SimpleNamespace):
        return dict(vars(value))
    return {}


def _bridge_report_training_target_payload(
    report: Any,
    *,
    bridge_names: Sequence[str],
) -> Optional[Dict[str, Any]]:
    if isinstance(report, Mapping):
        target_payload = dict(report.get("training_target", {}) or {})
        document_hash = str(
            target_payload.get("document_hash")
            or report.get("document_hash")
            or ""
        )
        if not document_hash:
            return None
        losses = dict(
            target_payload.get("losses")
            or report.get("canonical_loss_vector")
            or {}
        )
        view_distribution = dict(
            target_payload.get("view_distribution")
            or report.get("view_distribution")
            or {}
        )
        return {
            "accepted": bool(target_payload.get("accepted", report.get("accepted", False))),
            "adapter_losses": dict(target_payload.get("adapter_losses", {}) or {}),
            "bridge_names": list(target_payload.get("bridge_names") or bridge_names),
            "document_hash": document_hash,
            "document_id": str(target_payload.get("document_id") or report.get("document_id") or ""),
            "document_version": str(target_payload.get("document_version") or ""),
            "losses": losses,
            "view_distribution": view_distribution,
        }
    if hasattr(report, "to_dict"):
        try:
            report_payload = report.to_dict()
        except Exception:
            report_payload = None
        if isinstance(report_payload, Mapping):
            return _bridge_report_training_target_payload(
                report_payload,
                bridge_names=bridge_names,
            )
    try:
        target = report.training_target()
    except Exception:
        target = None
    if target is None:
        return None
    document = getattr(target, "document", None) or getattr(report, "document", None)
    document_hash = ""
    if document is not None and hasattr(document, "canonical_hash"):
        try:
            document_hash = str(document.canonical_hash())
        except Exception:
            document_hash = ""
    if not document_hash:
        return None
    return {
        "accepted": bool(getattr(target, "accepted", False)),
        "adapter_losses": dict(getattr(target, "adapter_losses", {}) or {}),
        "bridge_names": list(getattr(target, "bridge_names", ()) or bridge_names),
        "document_hash": document_hash,
        "document_id": str(getattr(document, "document_id", "") or ""),
        "document_version": str(getattr(document, "version", "") or ""),
        "losses": dict(getattr(target, "losses", {}) or {}),
        "view_distribution": dict(getattr(target, "view_distribution", {}) or {}),
    }


def _export_bridge_report_to_legal_ir_target_cache(
    sample: Any,
    report: Any,
    *,
    bridge_names: Sequence[str],
    evaluate_provers: Optional[bool],
) -> bool:
    payload = _bridge_report_training_target_payload(
        report,
        bridge_names=bridge_names,
    )
    if payload is None:
        return False
    try:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
            _legal_ir_target_cache_key,
            _write_legal_ir_target_disk_cache_payload,
        )

        cache_key = _legal_ir_target_cache_key(
            sample,
            bridge_names=bridge_names,
            evaluate_provers=evaluate_provers,
        )
        return _write_legal_ir_target_disk_cache_payload(cache_key, payload)
    except Exception:
        return False


def _sample_metric_cache_payload(sample: Any) -> Dict[str, Any]:
    embedding = [
        round(float(value), 12)
        for value in list(getattr(sample, "embedding_vector", []) or [])
    ]
    embedding_hash = hashlib.sha256(
        json.dumps(embedding, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "citation": str(getattr(sample, "citation", "") or ""),
        "embedding_dimensions": len(embedding),
        "embedding_hash": embedding_hash,
        "embedding_model": str(getattr(sample, "embedding_model", "") or ""),
        "sample_id": str(getattr(sample, "sample_id", "") or ""),
        "source": str(getattr(sample, "source", "") or ""),
        "text_hash": hashlib.sha256(
            str(getattr(sample, "text", "") or "").encode("utf-8")
        ).hexdigest(),
        "title": str(getattr(sample, "title", "") or ""),
        "section": str(getattr(sample, "section", "") or ""),
    }


def _metric_disk_cache_key(kind: str, payload: Mapping[str, Any]) -> str:
    wrapper = {
        "code_fingerprint": _metric_code_fingerprint(),
        "kind": str(kind),
        "payload": payload,
        "version": LEGAL_IR_METRIC_DISK_CACHE_VERSION,
    }
    return hashlib.sha256(_stable_metric_json(wrapper).encode("utf-8")).hexdigest()


def _metric_disk_cache_path(kind: str, key: str) -> Optional[Path]:
    root = _metric_disk_cache_dir()
    if root is None:
        return None
    safe_kind = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(kind)).strip("._") or "metric"
    key_text = re.sub(r"[^a-fA-F0-9]+", "", str(key)) or hashlib.sha256(
        str(key).encode("utf-8")
    ).hexdigest()
    return root / safe_kind / key_text[:2] / f"{key_text}.json"


def _read_metric_disk_cache(kind: str, key: str) -> Optional[Dict[str, Any]]:
    path = _metric_disk_cache_path(kind, key)
    if path is None or not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(wrapper, Mapping):
        return None
    if wrapper.get("version") != LEGAL_IR_METRIC_DISK_CACHE_VERSION:
        return None
    if wrapper.get("kind") != kind or wrapper.get("key") != key:
        return None
    payload = wrapper.get("payload")
    if not isinstance(payload, Mapping):
        return None
    return dict(payload)


def _write_metric_disk_cache(kind: str, key: str, payload: Mapping[str, Any]) -> None:
    path = _metric_disk_cache_path(kind, key)
    if path is None:
        return
    wrapper = {
        "created_at": utc_now(),
        "code_fingerprint": _metric_code_fingerprint(),
        "key": key,
        "kind": kind,
        "payload": dict(payload),
        "version": LEGAL_IR_METRIC_DISK_CACHE_VERSION,
    }
    tmp_path: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(path.parent),
            encoding="utf-8",
            prefix=f".{path.stem}.",
            suffix=".tmp",
        ) as handle:
            tmp_path = Path(handle.name)
            json.dump(wrapper, handle, default=str, ensure_ascii=True, sort_keys=True)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


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


class USCodeEmbeddingLookup:
    """Lookup first laws_embeddings.parquet vector by U.S. Code content CID."""

    def __init__(
        self,
        *,
        enabled: bool,
        mode: str,
        path: str,
        source: str,
        embedding_model: str,
        cid_to_index: Optional[Mapping[str, int]] = None,
        embedding_column: Any = None,
        dimensions: int = 0,
        load_error: str = "",
    ) -> None:
        self.enabled = bool(enabled)
        self.mode = str(mode or "auto")
        self.path = str(path or "")
        self.source = str(source or "")
        self.embedding_model = str(embedding_model or "mock:stable-sha256")
        self._cid_to_index = dict(cid_to_index or {})
        self._embedding_column = embedding_column
        self.dimensions = int(dimensions or 0)
        self.load_error = str(load_error or "")
        self.hit_count = 0
        self.miss_count = 0
        self.lookup_count = 0
        self.lookup_error_count = 0

    @classmethod
    def disabled(
        cls,
        *,
        mode: str,
        path: str = "",
        reason: str = "",
        load_error: str = "",
    ) -> "USCodeEmbeddingLookup":
        return cls(
            enabled=False,
            mode=mode,
            path=path,
            source="disabled",
            embedding_model="mock:stable-sha256",
            load_error=load_error or reason,
        )

    @classmethod
    def from_table(
        cls,
        table: Any,
        *,
        mode: str,
        path: str,
        source: str,
        embedding_model: str,
    ) -> "USCodeEmbeddingLookup":
        available = set(getattr(table, "column_names", []) or [])
        if not {"cid", "embedding"}.issubset(available):
            return cls.disabled(
                mode=mode,
                path=path,
                reason="embedding parquet is missing required cid/embedding columns",
            )
        cid_to_index: Dict[str, int] = {}
        for index, cid in enumerate(table.column("cid").to_pylist()):
            key = str(cid or "").strip()
            if key and key not in cid_to_index:
                cid_to_index[key] = index
        lookup = cls(
            enabled=bool(cid_to_index),
            mode=mode,
            path=path,
            source=source,
            embedding_model=embedding_model,
            cid_to_index=cid_to_index,
            embedding_column=table.column("embedding"),
        )
        lookup.dimensions = lookup._infer_dimensions()
        return lookup

    @classmethod
    def from_parquet_source(
        cls,
        parquet_source: Any,
        *,
        mode: str,
        path: str,
        source: str,
        embedding_model: str,
    ) -> "USCodeEmbeddingLookup":
        parquet_file = pq.ParquetFile(parquet_source)
        available = set(parquet_file.schema_arrow.names)
        columns = [column for column in ("cid", "embedding") if column in available]
        table = parquet_file.read(columns=columns)
        return cls.from_table(
            table,
            mode=mode,
            path=path,
            source=source,
            embedding_model=embedding_model,
        )

    def _infer_dimensions(self) -> int:
        for index in self._cid_to_index.values():
            vector = self._vector_at_index(index)
            if vector:
                return len(vector)
        return 0

    def _vector_at_index(self, index: int) -> Optional[List[float]]:
        if self._embedding_column is None:
            return None
        value = self._embedding_column[index]
        vector = value.as_py() if hasattr(value, "as_py") else value
        if not vector:
            return None
        return [float(item) for item in list(vector)]

    def vector_for_cid(self, cid: Any) -> Optional[List[float]]:
        self.lookup_count += 1
        key = str(cid or "").strip()
        if not self.enabled or not key:
            self.miss_count += 1
            return None
        index = self._cid_to_index.get(key)
        if index is None:
            self.miss_count += 1
            return None
        try:
            vector = self._vector_at_index(index)
        except Exception:
            self.lookup_error_count += 1
            self.miss_count += 1
            return None
        if not vector:
            self.miss_count += 1
            return None
        self.hit_count += 1
        if not self.dimensions:
            self.dimensions = len(vector)
        return vector

    def vector_and_model_for_row(
        self,
        row: Mapping[str, Any],
    ) -> tuple[Optional[List[float]], Optional[str]]:
        vector = self.vector_for_cid(row.get("ipfs_cid") or row.get("cid"))
        if vector is None:
            return None, None
        return vector, self.embedding_model

    def report(self) -> Dict[str, Any]:
        return {
            "cid_count": len(self._cid_to_index),
            "dimensions": self.dimensions,
            "embedding_model": self.embedding_model,
            "enabled": self.enabled,
            "hit_count": self.hit_count,
            "load_error": self.load_error,
            "lookup_count": self.lookup_count,
            "lookup_error_count": self.lookup_error_count,
            "miss_count": self.miss_count,
            "mode": self.mode,
            "path": self.path,
            "source": self.source,
        }


def load_laws_table():
    fs = HfFileSystem()
    path = f"datasets/{HF_USCODE_DATASET_ID}/{USCODE_LAWS_PARQUET}"
    with fs.open(path, "rb") as laws_file:
        return pq.ParquetFile(laws_file).read(columns=LAW_COLUMNS)


def load_uscode_embedding_lookup(args: argparse.Namespace) -> USCodeEmbeddingLookup:
    mode = str(getattr(args, "uscode_embeddings_mode", "auto") or "auto").strip().lower()
    if mode not in {"auto", "off", "required"}:
        mode = "auto"
    embeddings_path = str(
        getattr(args, "uscode_embeddings_path", USCODE_EMBEDDINGS_PARQUET)
        or USCODE_EMBEDDINGS_PARQUET
    ).strip()
    if mode == "off":
        return USCodeEmbeddingLookup.disabled(
            mode=mode,
            path=embeddings_path,
            reason="disabled by --uscode-embeddings-mode=off",
        )
    if not embeddings_path:
        return USCodeEmbeddingLookup.disabled(
            mode=mode,
            path=embeddings_path,
            reason="no embeddings path configured",
        )

    try:
        local_path = Path(embeddings_path).expanduser()
        if local_path.is_file():
            return USCodeEmbeddingLookup.from_parquet_source(
                local_path,
                mode=mode,
                path=str(local_path),
                source="local",
                embedding_model=f"parquet:{local_path.name}",
            )

        fs = HfFileSystem()
        hf_path = f"datasets/{HF_USCODE_DATASET_ID}/{embeddings_path.lstrip('/')}"
        with fs.open(hf_path, "rb") as embeddings_file:
            return USCodeEmbeddingLookup.from_parquet_source(
                embeddings_file,
                mode=mode,
                path=embeddings_path,
                source="huggingface",
                embedding_model=f"hf:{HF_USCODE_DATASET_ID}:{embeddings_path}",
            )
    except Exception as exc:
        if mode == "required":
            raise RuntimeError(
                f"Unable to load U.S. Code embeddings from {embeddings_path!r}"
            ) from exc
        return USCodeEmbeddingLookup.disabled(
            mode=mode,
            path=embeddings_path,
            load_error=f"{type(exc).__name__}: {exc}",
        )


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
def codex_main_apply_lock(
    packet: Mapping[str, Any],
    *,
    timeout_seconds: Optional[float] = None,
) -> Iterator[None]:
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
    timeout = (
        _env_float(
            "IPFS_DATASETS_CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS",
            CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS,
            minimum=1.0,
        )
        if timeout_seconds is None
        else max(1.0, float(timeout_seconds))
    )
    started = time.time()
    with lock_path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                elapsed = time.time() - started
                if elapsed >= timeout:
                    handle.seek(0)
                    owner = handle.read(2000)
                    raise TimeoutError(
                        f"Timed out after {elapsed:.1f}s waiting for {lock_path}; "
                        f"owner={owner.strip() or 'unknown'}"
                    ) from exc
                time.sleep(min(1.0, max(0.05, timeout - elapsed)))
        owner = {
            "acquired_at": utc_now(),
            "packet_id": packet.get("packet_id"),
            "pid": os.getpid(),
            "run_id": packet.get("run_id"),
            "timeout_seconds": timeout,
            "worker_id": packet.get("worker_id"),
        }
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(owner, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
        try:
            yield
        finally:
            try:
                handle.seek(0)
                handle.truncate()
                handle.write(
                    json.dumps(
                        {
                            **owner,
                            "released_at": utc_now(),
                        },
                        sort_keys=True,
                    )
                )
                handle.flush()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def row_to_sample(
    row: Mapping[str, Any],
    *,
    embedding_lookup: Optional[USCodeEmbeddingLookup] = None,
):
    embedding_vector: Optional[List[float]] = None
    embedding_model: Optional[str] = None
    if embedding_lookup is not None:
        embedding_vector, embedding_model = embedding_lookup.vector_and_model_for_row(row)
    return USCodeParquetRecord.from_row(row).to_sample(
        embedding_vector=embedding_vector,
        embedding_model=embedding_model,
    )


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
    embedding_lookup: Optional[USCodeEmbeddingLookup] = None,
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
        sample = row_to_sample(row, embedding_lookup=embedding_lookup)
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
    embedding_lookup: Optional[USCodeEmbeddingLookup] = None,
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
            embedding_lookup=embedding_lookup,
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
            embedding_lookup=embedding_lookup,
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
        "cross_entropy_entropy_loss": round(
            float(getattr(evaluation, "cross_entropy_entropy_loss", 0.0)),
            9,
        ),
        "cross_entropy_excess_loss": round(
            float(getattr(evaluation, "cross_entropy_excess_loss", 0.0)),
            9,
        ),
        "cross_entropy_loss": round(evaluation.cross_entropy_loss, 9),
        "reconstruction_loss": round(evaluation.reconstruction_loss, 9),
        "sample_count": evaluation.sample_count,
        "symbolic_validity_penalty": round(evaluation.symbolic_validity_penalty, 9),
    }
    sample_embedding_metrics = list(
        getattr(evaluation, "sample_embedding_metrics", []) or []
    )
    if sample_embedding_metrics:
        block["worst_sample_embedding_metrics"] = sample_embedding_metrics[:8]
    legal_ir_losses = dict(getattr(evaluation, "legal_ir_losses", {}) or {})
    if legal_ir_losses:
        block["legal_ir_losses"] = {
            name: round(float(value), 9)
            for name, value in sorted(legal_ir_losses.items())
        }
        block["legal_ir_target_count"] = int(
            getattr(evaluation, "legal_ir_target_count", 0) or 0
        )
        block["legal_ir_target_sampled"] = (
            int(block["legal_ir_target_count"]) < int(evaluation.sample_count)
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


def _basic_autoencoder_metric_block(evaluation: Any) -> Dict[str, Any]:
    return {
        "cosine_loss": round(float(getattr(evaluation, "cosine_loss", 0.0)), 9),
        "cosine_similarity": round(
            float(getattr(evaluation, "embedding_cosine_similarity", 0.0)),
            9,
        ),
        "cross_entropy_excess_loss": round(
            float(getattr(evaluation, "cross_entropy_excess_loss", 0.0)),
            9,
        ),
        "cross_entropy_loss": round(
            float(getattr(evaluation, "cross_entropy_loss", 0.0)),
            9,
        ),
        "reconstruction_loss": round(
            float(getattr(evaluation, "reconstruction_loss", 0.0)),
            9,
        ),
        "sample_count": int(getattr(evaluation, "sample_count", 0) or 0),
    }


def autoencoder_memory_gap_block(
    generalized_evaluation: Any,
    sample_memory_evaluation: Any,
    *,
    dataset: str,
    expected_holdout: bool = False,
    threshold: float = 1.0e-6,
) -> Dict[str, Any]:
    """Compare sample-memory-disabled and sample-memory-enabled autoencoder scores."""

    generalized = _basic_autoencoder_metric_block(generalized_evaluation)
    sample_memory = _basic_autoencoder_metric_block(sample_memory_evaluation)
    cosine_gain = (
        float(sample_memory["cosine_similarity"])
        - float(generalized["cosine_similarity"])
    )
    cross_entropy_gain = (
        float(generalized["cross_entropy_loss"])
        - float(sample_memory["cross_entropy_loss"])
    )
    cross_entropy_excess_gain = (
        float(generalized["cross_entropy_excess_loss"])
        - float(sample_memory["cross_entropy_excess_loss"])
    )
    reconstruction_gain = (
        float(generalized["reconstruction_loss"])
        - float(sample_memory["reconstruction_loss"])
    )
    advantage_detected = (
        cosine_gain > threshold
        or cross_entropy_gain > threshold
        or cross_entropy_excess_gain > threshold
        or reconstruction_gain > threshold
    )
    return {
        "cross_entropy_excess_gain_from_sample_memory": round(
            cross_entropy_excess_gain,
            9,
        ),
        "cross_entropy_gain_from_sample_memory": round(cross_entropy_gain, 9),
        "cosine_gain_from_sample_memory": round(cosine_gain, 9),
        "dataset": str(dataset),
        "expected_holdout": bool(expected_holdout),
        "generalized": generalized,
        "generalized_label": "sample_memory_disabled",
        "interpretation": (
            "sample memory improves this split; treat memory-enabled scores as a "
            "memorization probe, not generalization"
            if advantage_detected
            else "sample memory did not materially improve this split"
        ),
        "reconstruction_gain_from_sample_memory": round(reconstruction_gain, 9),
        "sample_count": int(generalized.get("sample_count", 0) or 0),
        "sample_memory": sample_memory,
        "sample_memory_advantage_detected": bool(advantage_detected),
        "sample_memory_label": "sample_memory_enabled",
        "threshold": float(threshold),
        "unexpected_holdout_memory_advantage": bool(
            expected_holdout and advantage_detected
        ),
    }


def skipped_autoencoder_metric_block(
    reference_evaluation: Any,
    *,
    cycle: int,
    dataset: str,
    every_n_cycles: int,
    mode: str,
    skip_reason: str,
) -> Dict[str, Any]:
    """Report an intentionally skipped diagnostic autoencoder metric."""

    return {
        "cadence_every_n_cycles": max(1, int(every_n_cycles or 1)),
        "cadence_mode": str(mode),
        "cycle": int(cycle),
        "dataset": str(dataset),
        "reference_metrics": metric_block(reference_evaluation),
        "sample_count": int(getattr(reference_evaluation, "sample_count", 0) or 0),
        "skip_reason": str(skip_reason),
        "skipped": True,
    }


def skipped_autoencoder_memory_gap_block(
    reference_evaluation: Any,
    *,
    cycle: int,
    dataset: str,
    every_n_cycles: int,
    expected_holdout: bool,
    mode: str,
    skip_reason: str,
) -> Dict[str, Any]:
    """Report that the diagnostic sample-memory gap was not measured this cycle."""

    return {
        "cadence_every_n_cycles": max(1, int(every_n_cycles or 1)),
        "cadence_mode": str(mode),
        "cycle": int(cycle),
        "dataset": str(dataset),
        "expected_holdout": bool(expected_holdout),
        "interpretation": (
            "sample-memory probe skipped by cadence; this cycle did not measure "
            "memorization pressure"
        ),
        "reference_metrics": metric_block(reference_evaluation),
        "sample_count": int(getattr(reference_evaluation, "sample_count", 0) or 0),
        "skip_reason": str(skip_reason),
        "skipped": True,
    }


def _distribution_cosine_similarity(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> float:
    """Return cosine similarity for sparse named distributions."""
    keys = sorted(set(left) | set(right))
    if not keys:
        return 0.0
    left_values = [float(left.get(key, 0.0)) for key in keys]
    right_values = [float(right.get(key, 0.0)) for key in keys]
    left_norm = sum(value * value for value in left_values) ** 0.5
    right_norm = sum(value * value for value in right_values) ** 0.5
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left_values, right_values)) / (
        left_norm * right_norm
    )


def learned_ir_metric_block(evaluation) -> Dict[str, Any]:
    """Summarize autoencoder-predicted legal-IR view alignment.

    The compiler IR metrics below are deterministic compiler/codec round-trip
    metrics. This block is the learned autoencoder-side view of legal-IR
    structure, so it can move when autoencoder weights move even if compiler
    code is unchanged inside a long-running process.
    """
    legal_ir_losses = dict(getattr(evaluation, "legal_ir_losses", {}) or {})
    target_distribution = dict(
        getattr(evaluation, "legal_ir_view_distribution", {}) or {}
    )
    predicted_distribution = dict(
        getattr(evaluation, "legal_ir_predicted_view_distribution", {}) or {}
    )
    block: Dict[str, Any] = {
        "target_count": int(getattr(evaluation, "legal_ir_target_count", 0) or 0),
        "view_cosine_similarity": round(
            _distribution_cosine_similarity(
                predicted_distribution,
                target_distribution,
            ),
            9,
        ),
    }
    view_ce = legal_ir_losses.get("legal_ir_view_cross_entropy_loss")
    if view_ce is not None:
        block["view_cross_entropy_loss"] = round(float(view_ce), 9)
    view_entropy = legal_ir_losses.get("legal_ir_view_entropy_loss")
    if view_entropy is not None:
        block["view_entropy_loss"] = round(float(view_entropy), 9)
    view_excess = legal_ir_losses.get("legal_ir_view_cross_entropy_excess_loss")
    if view_excess is not None:
        block["view_cross_entropy_excess_loss"] = round(float(view_excess), 9)
    family_ce = legal_ir_losses.get("legal_ir_view_family_cross_entropy_loss")
    if family_ce is not None:
        block["family_cross_entropy_loss"] = round(float(family_ce), 9)
    family_ce_excess = legal_ir_losses.get(
        "legal_ir_view_family_cross_entropy_excess_loss"
    )
    if family_ce_excess is not None:
        block["family_cross_entropy_excess_loss"] = round(
            float(family_ce_excess),
            9,
        )
    family_cosine_gap = legal_ir_losses.get("legal_ir_view_family_cosine_gap_loss")
    if family_cosine_gap is not None:
        block["family_cosine_gap_loss"] = round(float(family_cosine_gap), 9)
    family_gap_block = _learned_ir_family_gap_block(legal_ir_losses)
    if family_gap_block:
        block.update(family_gap_block)
    if legal_ir_losses:
        block["losses"] = {
            name: round(float(value), 9)
            for name, value in sorted(legal_ir_losses.items())
        }
    if target_distribution:
        block["target_view_distribution"] = {
            name: round(float(value), 9)
            for name, value in sorted(target_distribution.items())
        }
    if predicted_distribution:
        block["predicted_view_distribution"] = {
            name: round(float(value), 9)
            for name, value in sorted(predicted_distribution.items())
        }
    return block


def _guidance_slot_safe_key(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_").lower()


def _metadata_sequence_strings(value: Any) -> List[str]:
    if isinstance(value, Mapping):
        return [
            str(item)
            for item, count in sorted(value.items())
            if str(item) and _float_or_zero(count) > 0.0
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if str(item)]
    if value is None or isinstance(value, (str, bytes)):
        return [str(value)] if str(value or "") else []
    return [str(value)]


def compiler_guidance_slot_texts_from_result(result: Any) -> Dict[str, List[str]]:
    """Return guidance slots from decoded phrases, falling back to cached metadata."""

    cached_slot_texts = getattr(result, "compiler_guidance_slot_texts", None)
    if isinstance(cached_slot_texts, Mapping):
        return {
            str(slot): _metadata_sequence_strings(values)
            for slot, values in sorted(cached_slot_texts.items())
            if str(slot)
        }
    decoded = getattr(result, "decoded_modal_text", None)
    if hasattr(decoded, "phrases"):
        return decoded_modal_phrase_slot_text_map(decoded)
    metadata = dict(getattr(result, "metadata", {}) or {})
    cached_metadata_slot_texts = metadata.get("_compiler_guidance_slot_texts")
    if isinstance(cached_metadata_slot_texts, Mapping):
        return {
            str(slot): _metadata_sequence_strings(values)
            for slot, values in sorted(cached_metadata_slot_texts.items())
            if str(slot)
        }
    slot_texts: Dict[str, List[str]] = {}

    def add(slot: str, value: Any) -> None:
        text = str(value or "")
        if text:
            slot_texts.setdefault(slot, []).append(text)

    feature_groups = metadata.get("compiler_guidance_feature_groups")
    if isinstance(feature_groups, Mapping):
        for group_name, features in sorted(feature_groups.items()):
            safe_group = _guidance_slot_safe_key(group_name)
            if not safe_group:
                continue
            add("compiler_guidance_feature_group", safe_group)
            for feature in _metadata_sequence_strings(features):
                add(f"compiler_guidance_{safe_group}_feature", feature)

    predicted = metadata.get("compiler_guidance_legal_ir_predicted_view_distribution")
    target = metadata.get("compiler_guidance_legal_ir_target_view_distribution")
    if isinstance(predicted, Mapping) and isinstance(target, Mapping):
        for view in sorted(set(predicted) | set(target)):
            safe_view = _guidance_slot_safe_key(view)
            if not safe_view:
                continue
            predicted_value = _float_or_zero(predicted.get(view))
            target_value = _float_or_zero(target.get(view))
            if target_value > predicted_value:
                add("compiler_guidance_legal_ir_view_gap", safe_view)
                add(
                    "compiler_guidance_legal_ir_view_gap_direction",
                    f"{safe_view}:underrepresented",
                )
            elif predicted_value > target_value:
                add("compiler_guidance_legal_ir_view_gap", safe_view)
                add(
                    "compiler_guidance_legal_ir_view_gap_direction",
                    f"{safe_view}:overrepresented",
                )

    for route in _metadata_sequence_strings(
        metadata.get("compiler_guidance_todo_routes")
    ):
        add("compiler_guidance_todo_route", route)
    return slot_texts


def _learned_ir_family_gap_block(
    legal_ir_losses: Mapping[str, Any],
) -> Dict[str, Any]:
    """Summarize worst LegalIR family gaps without averaging them away."""

    ce_excess_by_family: Dict[str, float] = {}
    cosine_gap_by_family: Dict[str, float] = {}
    prefix = "legal_ir_view_family_"
    for raw_name, raw_value in dict(legal_ir_losses or {}).items():
        name = str(raw_name)
        if not name.startswith(prefix):
            continue
        family_metric = name[len(prefix) :]
        if family_metric in {
            "cross_entropy_loss",
            "entropy_loss",
            "cross_entropy_excess_loss",
            "cosine_gap_loss",
        }:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if value != value:
            continue
        if family_metric.endswith("_cross_entropy_excess_loss"):
            family = family_metric[: -len("_cross_entropy_excess_loss")]
            ce_excess_by_family[family] = max(0.0, value)
        elif family_metric.endswith("_cosine_gap_loss"):
            family = family_metric[: -len("_cosine_gap_loss")]
            cosine_gap_by_family[family] = max(0.0, value)

    block: Dict[str, Any] = {}
    if ce_excess_by_family:
        worst_family, worst_value = max(
            ce_excess_by_family.items(),
            key=lambda item: (item[1], item[0]),
        )
        block["family_cross_entropy_excess_by_family"] = {
            family: round(value, 9)
            for family, value in sorted(ce_excess_by_family.items())
        }
        block["worst_family_cross_entropy_excess_loss"] = round(worst_value, 9)
        block["worst_family_cross_entropy_excess_name"] = worst_family
    if cosine_gap_by_family:
        worst_family, worst_value = max(
            cosine_gap_by_family.items(),
            key=lambda item: (item[1], item[0]),
        )
        block["family_cosine_gap_by_family"] = {
            family: round(value, 9)
            for family, value in sorted(cosine_gap_by_family.items())
        }
        block["worst_family_cosine_gap_loss"] = round(worst_value, 9)
        block["worst_family_cosine_gap_name"] = worst_family
    return block


COMPILER_GUIDANCE_CANARY_METRICS = (
    "cross_entropy_loss",
    "cross_entropy_excess_loss",
    "cosine_similarity",
    "source_decompiled_text_embedding_cosine_loss",
    "source_decompiled_text_embedding_cosine_similarity",
    "source_decompiled_text_token_loss",
    "source_decompiled_text_token_similarity",
    "source_copy_loss",
    "source_copy_reward_hack_penalty",
    "structural_text_reconstruction_loss",
    "text_reconstruction_loss",
)


class CompilerIRMetricSampleTimeout(TimeoutError):
    """Raised when one deterministic compiler metric sample exceeds its budget."""


def _compiler_ir_metric_sample_timeout_supported(timeout_seconds: float) -> bool:
    return (
        float(timeout_seconds) > 0.0
        and threading.current_thread() is threading.main_thread()
        and hasattr(signal, "setitimer")
        and hasattr(signal, "getitimer")
    )


@contextmanager
def _compiler_ir_metric_sample_timeout(timeout_seconds: float) -> Iterator[bool]:
    timeout = max(0.0, float(timeout_seconds))
    if not _compiler_ir_metric_sample_timeout_supported(timeout):
        yield False
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def handle_timeout(_signum: int, _frame: Any) -> None:
        raise CompilerIRMetricSampleTimeout(
            f"compiler IR metric sample exceeded {timeout:.3f}s"
        )

    signal.signal(signal.SIGALRM, handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        yield True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer and previous_timer[0] > 0.0:
            signal.setitimer(
                signal.ITIMER_REAL,
                previous_timer[0],
                previous_timer[1],
            )


def _compiler_ir_guidance_block_cache_compatible(
    block: Mapping[str, Any],
    *,
    use_autoencoder_guidance: bool,
) -> bool:
    if not use_autoencoder_guidance:
        return True
    if (
        block.get("compiler_guidance_diagnostics_version")
        != _COMPILER_IR_GUIDANCE_DIAGNOSTICS_VERSION
    ):
        return False
    if _float_or_zero(block.get("autoencoder_guidance_applied_count")) <= 0.0:
        return True
    required_mapping_keys = (
        "compiler_guidance_feature_groups",
        "compiler_guidance_legal_ir_view_gaps",
        "compiler_guidance_semantic_overlay_terms",
        "compiler_guidance_surface_features",
        "compiler_guidance_todo_routes",
    )
    return all(isinstance(block.get(key), Mapping) for key in required_mapping_keys)


def _normalise_compiler_ir_metric_text_policy(value: Any) -> str:
    policy = str(value or DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY).strip().lower()
    if policy not in COMPILER_IR_METRIC_TEXT_POLICIES:
        return DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY
    return policy


def _compiler_ir_metric_bounded_text(text: str, max_chars: int) -> str:
    """Return a stable metric prefix without cutting the last token when possible."""

    limit = max(0, int(max_chars or 0))
    source_text = str(text or "")
    if limit <= 0 or len(source_text) <= limit:
        return source_text
    prefix = source_text[:limit].rstrip()
    if not prefix:
        return source_text[:limit]
    boundary = max(prefix.rfind(". "), prefix.rfind("; "), prefix.rfind("\n"))
    min_boundary = max(80, int(limit * 0.65))
    if boundary >= min_boundary:
        return prefix[: boundary + 1].rstrip()
    whitespace = prefix.rfind(" ")
    if whitespace >= min_boundary:
        return prefix[:whitespace].rstrip()
    return prefix


def _compiler_ir_metric_sample_for_text(
    sample: Any,
    *,
    metric_text: str,
) -> Any:
    """Return a metric-only sample clone with an embedding aligned to the text."""

    original_text = str(getattr(sample, "text", "") or "")
    if str(metric_text) == original_text:
        return sample
    sample_id = str(getattr(sample, "sample_id", "") or "sample")
    digest = hashlib.sha256(str(metric_text).encode("utf-8")).hexdigest()[:12]
    dimensions = len(list(getattr(sample, "embedding_vector", []) or [])) or 8
    embedding_model = str(getattr(sample, "embedding_model", "") or "")
    metric_embedding_model = (
        f"metric-prefix:{embedding_model}" if embedding_model else "metric-prefix:mock"
    )
    payload = {
        "embedding_model": metric_embedding_model,
        "embedding_vector": stable_mock_embedding(str(metric_text), dimensions=dimensions),
        "normalized_text": str(metric_text),
        "sample_id": f"{sample_id}:metric-prefix:{digest}",
        "text": str(metric_text),
    }
    try:
        return replace(sample, **payload)
    except Exception:
        fallback = dict(getattr(sample, "__dict__", {}) or {})
        fallback.update(payload)
        return SimpleNamespace(**fallback)


def _vector_cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = sum(float(value) * float(value) for value in left) ** 0.5
    right_norm = sum(float(value) * float(value) for value in right) ** 0.5
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return sum(float(a) * float(b) for a, b in zip(left, right)) / (left_norm * right_norm)


def _vector_mse_loss(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 1.0
    return sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)) / len(left)


def _compiler_ir_timeout_structural_text(metric_text: str) -> str:
    """Return a cheap modal-cue summary for timed-out deterministic codec metrics."""

    normalized = re.sub(r"\s+", " ", str(metric_text or "")).strip()
    if not normalized:
        return ""
    cue_re = re.compile(
        r"\b(?:shall|must|may|may\s+not|shall\s+not|required|prohibit(?:ed)?|"
        r"authorized|eligible|entitled|except|unless|provided|subject\s+to|"
        r"before|after|within|not\s+later\s+than|effective|repealed|means|"
        r"definition|penalty|violation|report)\b",
        flags=re.IGNORECASE,
    )
    clauses = [
        part.strip(" ;:,.")
        for part in re.split(r"(?<=[.;:])\s+|\n+|\s+\([a-z0-9]+\)\s+", normalized)
        if part.strip(" ;:,.")
    ]
    selected = [part for part in clauses if cue_re.search(part)]
    if not selected:
        selected = clauses[:2]
    structural = "; ".join(part[:220] for part in selected[:3]).strip()
    return structural[:640] or normalized[:640]


def _compiler_ir_timeout_family_distribution(metric_text: str, sample: Any) -> Dict[str, float]:
    counts: Dict[str, float] = {}
    modal_ir = getattr(sample, "modal_ir", None)
    for formula in list(getattr(modal_ir, "formulas", ()) or ()):
        operator = getattr(formula, "operator", None)
        family = str(getattr(operator, "family", "") or "").strip()
        if family:
            counts[family] = counts.get(family, 0.0) + 1.0
    lowered = str(metric_text or "").lower()
    cue_weights = {
        "deontic": ("shall", "must", "may", "required", "prohibited", "authorized"),
        "temporal": ("before", "after", "within", "deadline", "effective", "later than"),
        "conditional_normative": ("if", "unless", "provided", "subject to", "except"),
        "frame": ("means", "definition", "term", "section", "chapter"),
    }
    for family, cues in cue_weights.items():
        hit_count = sum(1 for cue in cues if cue in lowered)
        if hit_count:
            counts[family] = counts.get(family, 0.0) + float(hit_count)
    if not counts:
        counts["hybrid"] = 1.0
    total = sum(counts.values()) or 1.0
    return {name: value / total for name, value in sorted(counts.items()) if value > 0.0}


def _compiler_ir_timeout_entropy(distribution: Mapping[str, float]) -> float:
    return -sum(
        max(0.0, float(value)) * math.log(max(float(value), 1.0e-12))
        for value in distribution.values()
        if float(value) > 0.0
    )


def _compiler_ir_metric_timeout_fallback_result(
    sample: Any,
    *,
    metric_sample_id: str,
    metric_text: str,
    metric_text_length: int,
    original_text_length: int,
    sample_timeout_seconds: float,
) -> Any:
    """Return finite, degraded compiler metrics when codec scoring times out.

    A timeout means the expensive codec path failed to finish; it does not mean
    the sample has zero modal signal.  This fallback keeps a bounded surface
    round-trip signal available for scoring and TODO routing while preserving
    explicit timeout metadata.
    """

    modal_ir = getattr(sample, "modal_ir", None)
    formulas = list(getattr(modal_ir, "formulas", ()) or ())
    frame_candidates = list(getattr(sample, "frame_candidates", ()) or ())
    structural_text = _compiler_ir_timeout_structural_text(metric_text)
    dimensions = len(list(getattr(sample, "embedding_vector", []) or [])) or 8
    source_embedding = list(getattr(sample, "embedding_vector", []) or []) or stable_mock_embedding(
        str(metric_text),
        dimensions=dimensions,
    )
    decoded_embedding = stable_mock_embedding(structural_text, dimensions=len(source_embedding))
    embedding_cosine = _vector_cosine_similarity(source_embedding, decoded_embedding)
    token_similarity = modal_text_token_similarity(str(metric_text), structural_text)
    family_distribution = _compiler_ir_timeout_family_distribution(metric_text, sample)
    family_entropy = _compiler_ir_timeout_entropy(family_distribution)
    source_copy_ratio = min(1.0, max(0.0, token_similarity))
    source_copy_penalty = max(0.0, source_copy_ratio - 0.65)
    symbolic_validity_penalty = 0.25 if formulas else 0.75
    cross_entropy = min(1.0, family_entropy + 0.20 + symbolic_validity_penalty * 0.20)
    losses = {
        "cosine_loss": max(0.0, 1.0 - embedding_cosine),
        "cosine_similarity": embedding_cosine,
        "cross_entropy_entropy_loss": min(1.0, family_entropy),
        "cross_entropy_excess_loss": max(0.0, cross_entropy - min(1.0, family_entropy)),
        "cross_entropy_loss": cross_entropy,
        "flogic_similarity_loss": max(0.15, 1.0 - token_similarity),
        "flogic_similarity_score": min(0.85, max(0.0, token_similarity)),
        "frame_ranking_loss": 0.25 if frame_candidates else 0.75,
        "modal_span_coverage_loss": max(0.0, 1.0 - token_similarity),
        "ontology_violation_count": symbolic_validity_penalty,
        "raw_source_embedding_cosine_similarity": embedding_cosine,
        "reconstruction_loss": _vector_mse_loss(source_embedding, decoded_embedding),
        "source_copy_loss": source_copy_ratio,
        "source_copy_reward_hack_penalty": source_copy_penalty,
        "source_decompiled_text_embedding_cosine_loss": max(0.0, 1.0 - embedding_cosine),
        "source_decompiled_text_embedding_cosine_similarity": embedding_cosine,
        "source_decompiled_text_token_loss": max(0.0, 1.0 - token_similarity),
        "source_decompiled_text_token_similarity": token_similarity,
        "source_span_copy_ratio": source_copy_ratio,
        "source_span_text_reconstruction_loss": max(0.0, 1.0 - token_similarity),
        "structural_text_reconstruction_loss": max(0.0, 1.0 - token_similarity),
        "structural_text_reconstruction_similarity": token_similarity,
        "symbolic_validity_penalty": symbolic_validity_penalty,
        "text_reconstruction_loss": max(0.0, 1.0 - token_similarity),
    }
    metadata = {
        "compiler_ir_metric_timeout_fallback": True,
        "compiler_ir_metric_timeout_fallback_kind": "surface_modal_approximation",
        "compiler_ir_metric_timeout_family_distribution": family_distribution,
        "llm_call_count": 0.0,
        "metric_sample_id": metric_sample_id,
        "modal_decompiler_structural_text": structural_text,
        "metric_text_length": int(metric_text_length),
        "original_text_length": int(original_text_length),
        "sample_timeout_seconds": float(sample_timeout_seconds),
        "skip_reason": "sample_timeout",
    }
    return SimpleNamespace(
        decoded_modal_text=structural_text,
        frame_candidates=frame_candidates,
        losses=losses,
        metadata=metadata,
        modal_ir=SimpleNamespace(formulas=formulas),
    )


def autoencoder_metric_bridge_samples_for_evaluation(
    samples: Sequence[Any],
    *,
    max_sample_text_chars: int = DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
) -> List[Any]:
    """Return metric-only bridge samples bounded for synchronous LegalIR scoring."""

    limit = max(0, int(max_sample_text_chars or 0))
    bounded_samples: List[Any] = []
    for sample in samples:
        sample_text = str(getattr(sample, "text", "") or "")
        if limit <= 0 or len(sample_text) <= limit:
            bounded_samples.append(sample)
            continue
        metric_text = _compiler_ir_metric_bounded_text(sample_text, limit)
        bounded_samples.append(
            _compiler_ir_metric_sample_for_text(sample, metric_text=metric_text)
        )
    return bounded_samples


def compiler_ir_metric_block(
    samples: Sequence[Any],
    codec: DeterministicModalLogicCodec,
    *,
    autoencoder: Optional[AdaptiveModalAutoencoder] = None,
    use_autoencoder_guidance: bool = False,
    guidance_top_k: int = 16,
    max_sample_metric_records: int = 32,
    max_sample_text_chars: int = 0,
    metric_text_policy: str = DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY,
    progress_callback: Optional[Callable[[Mapping[str, Any]], None]] = None,
    sample_timeout_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Aggregate deterministic compiler/IR/decompiler round-trip metrics."""
    sample_list = list(samples)
    if not sample_list:
        return {
            "autoencoder_guidance_enabled": bool(use_autoencoder_guidance),
            "evaluated_count": 0,
            "metric_failures": 0,
            "sample_count": 0,
        }

    started_at = time.time()
    max_sample_text_chars = max(0, int(max_sample_text_chars or 0))
    metric_text_policy = _normalise_compiler_ir_metric_text_policy(
        metric_text_policy
    )
    sample_timeout_seconds = max(0.0, float(sample_timeout_seconds or 0.0))
    sample_timeout_supported = _compiler_ir_metric_sample_timeout_supported(
        sample_timeout_seconds
    )

    def emit_progress(stage: str, **payload: Any) -> None:
        if progress_callback is None:
            return
        event = {
            "block": "compiler_ir",
            "elapsed_seconds": round(time.time() - started_at, 3),
            "sample_count": len(sample_list),
            "stage": stage,
        }
        event.update(payload)
        try:
            progress_callback(event)
        except Exception:
            pass

    emit_progress(
        "start",
        autoencoder_guidance_enabled=bool(use_autoencoder_guidance),
        max_sample_text_chars=max_sample_text_chars,
        metric_text_policy=metric_text_policy,
    )
    guidance_applied_count = 0
    guidance_empty_count = 0
    guidance_failures = 0
    guidance_produced_count = 0
    guidance_requested_count = 0
    precomputed_guidance: List[Optional[Mapping[str, Any]]] = []
    guidance_cache_records: List[Dict[str, Any]] = []
    if use_autoencoder_guidance and autoencoder is not None:
        emit_progress("guidance_start")
        for sample_index, sample in enumerate(sample_list, start=1):
            guidance_requested_count += 1
            guidance_error = ""
            compiler_guidance: Optional[Mapping[str, Any]] = None
            try:
                compiler_guidance = autoencoder.compiler_guidance_for_sample(
                    sample,
                    use_sample_memory=False,
                    top_k=guidance_top_k,
                )
                if compiler_guidance:
                    guidance_produced_count += 1
                else:
                    guidance_empty_count += 1
            except Exception as exc:
                guidance_failures += 1
                guidance_error = f"{type(exc).__name__}: {str(exc)[:240]}"
                compiler_guidance = None
            precomputed_guidance.append(compiler_guidance)
            guidance_cache_records.append(
                {
                    "error": guidance_error,
                    "guidance": _compiler_ir_metric_guidance_cache_payload(
                        compiler_guidance
                    ),
                    "sample": _sample_metric_cache_payload(sample),
                    "sample_index": sample_index,
                }
            )
        emit_progress(
            "guidance_done",
            guidance_empty_count=guidance_empty_count,
            guidance_failures=guidance_failures,
            guidance_produced_count=guidance_produced_count,
            guidance_requested_count=guidance_requested_count,
        )
    persistent_cache_key: Optional[str] = None
    metric_block_cacheable = (
        (not use_autoencoder_guidance and autoencoder is None)
        or (
            use_autoencoder_guidance
            and autoencoder is not None
            and not guidance_failures
        )
    )
    if metric_block_cacheable:
        persistent_cache_key = _compiler_ir_metric_block_cache_key(
            sample_list,
            codec=codec,
            guidance_cache_records=guidance_cache_records,
            guidance_top_k=guidance_top_k,
            max_sample_metric_records=max_sample_metric_records,
            max_sample_text_chars=max_sample_text_chars,
            metric_text_policy=metric_text_policy,
            sample_timeout_seconds=sample_timeout_seconds,
        )
        cached_block = _read_metric_disk_cache(
            "compiler_ir_metric_block",
            persistent_cache_key,
        )
        if cached_block is not None and _compiler_ir_guidance_block_cache_compatible(
            cached_block,
            use_autoencoder_guidance=use_autoencoder_guidance,
        ):
            cached = dict(cached_block)
            cached["persistent_cache_enabled"] = True
            cached["persistent_cache_hit"] = True
            cached["persistent_cache_key"] = persistent_cache_key
            cached["persistent_cache_kind"] = "compiler_ir_metric_block"
            cached["compiler_ir_guidance_cache_policy"] = (
                _COMPILER_IR_GUIDANCE_CACHE_POLICY
            )
            cached["sample_timeout_cache_policy"] = (
                _COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY
            )
            cached["sample_timeout_seconds"] = sample_timeout_seconds
            cached["sample_cache_not_consulted_due_block_hit"] = True
            cached["persistent_sample_cache_hits"] = 0
            cached["persistent_sample_cache_misses"] = 0
            cached["persistent_sample_timeout_cache_hits"] = 0
            emit_progress(
                "persistent_cache_hit",
                cache_key=persistent_cache_key,
                evaluated_count=cached.get("evaluated_count", 0),
            )
            return cached
        if cached_block is not None:
            emit_progress(
                "persistent_cache_stale",
                cache_key=persistent_cache_key,
                reason="guided_diagnostics_schema",
            )
        emit_progress("persistent_cache_miss", cache_key=persistent_cache_key)
    losses: Dict[str, List[float]] = {
        "cosine_loss": [],
        "cosine_similarity": [],
        "cross_entropy_entropy_loss": [],
        "cross_entropy_excess_loss": [],
        "cross_entropy_loss": [],
        "flogic_similarity_loss": [],
        "flogic_similarity_score": [],
        "frame_ranking_loss": [],
        "guidance_family_cross_entropy_excess_loss": [],
        "guidance_family_cross_entropy_loss": [],
        "guidance_legal_ir_view_cross_entropy_excess_loss": [],
        "guidance_legal_ir_view_cross_entropy_loss": [],
        "guidance_legal_ir_view_entropy_loss": [],
        "modal_span_coverage_loss": [],
        "ontology_violation_count": [],
        "raw_source_embedding_cosine_similarity": [],
        "reconstruction_loss": [],
        "source_decompiled_text_embedding_cosine_loss": [],
        "source_decompiled_text_embedding_cosine_similarity": [],
        "source_decompiled_text_token_loss": [],
        "source_decompiled_text_token_similarity": [],
        "source_copy_loss": [],
        "source_copy_reward_hack_penalty": [],
        "source_span_copy_ratio": [],
        "source_span_text_reconstruction_loss": [],
        "structural_text_reconstruction_loss": [],
        "structural_text_reconstruction_similarity": [],
        "symbolic_validity_penalty": [],
        "text_reconstruction_loss": [],
    }
    formula_counts: List[float] = []
    frame_candidate_counts: List[float] = []
    llm_call_counts: List[float] = []
    failures = 0
    sample_timeouts = 0
    timeout_fallback_count = 0
    skipped_sample_count = 0
    text_length_skipped_count = 0
    text_length_truncated_count = 0
    persistent_sample_cache_hits = 0
    persistent_sample_cache_misses = 0
    persistent_sample_timeout_cache_hits = 0
    guidance_frame_boost_counts: List[float] = []
    guidance_frame_changed_count = 0
    guidance_feature_groups: Counter[str] = Counter()
    guidance_legal_ir_view_gaps: Counter[str] = Counter()
    guidance_semantic_overlay_counts: List[float] = []
    guidance_semantic_overlay_terms: Counter[str] = Counter()
    guidance_surface_features: Counter[str] = Counter()
    guidance_todo_routes: Counter[str] = Counter()
    guidance_todo_route_examples: Dict[str, List[Dict[str, str]]] = {}
    sample_metric_records: List[Dict[str, Any]] = []
    for sample_index, sample in enumerate(sample_list, start=1):
        sample_started_at = time.time()
        sample_id = str(getattr(sample, "sample_id", "") or "")
        citation = str(getattr(sample, "citation", "") or "")
        sample_text = str(getattr(sample, "text", "") or "")
        sample_text_length = len(sample_text)
        metric_sample = sample
        metric_text = sample_text
        metric_sample_id = sample_id
        metric_text_length = sample_text_length
        metric_text_truncated = False
        emit_progress(
            "sample_start",
            citation=citation,
            max_sample_text_chars=max_sample_text_chars,
            metric_text_policy=metric_text_policy,
            sample_id=sample_id,
            sample_index=sample_index,
            text_length=sample_text_length,
        )
        if max_sample_text_chars > 0 and sample_text_length > max_sample_text_chars:
            if metric_text_policy == "skip":
                skipped_sample_count += 1
                text_length_skipped_count += 1
                sample_record = {
                    "citation": citation,
                    "max_sample_text_chars": max_sample_text_chars,
                    "metric_text_policy": metric_text_policy,
                    "original_text_length": sample_text_length,
                    "sample_id": sample_id,
                    "skip_reason": "text_length_limit",
                    "source_text_preview": re.sub(r"\s+", " ", sample_text).strip()[
                        :240
                    ],
                    "text_length": sample_text_length,
                }
                if len(sample_metric_records) < max(0, int(max_sample_metric_records)):
                    sample_metric_records.append(sample_record)
                emit_progress(
                    "sample_skipped",
                    citation=citation,
                    max_sample_text_chars=max_sample_text_chars,
                    metric_text_policy=metric_text_policy,
                    sample_id=sample_id,
                    sample_index=sample_index,
                    skip_reason="text_length_limit",
                    text_length=sample_text_length,
                )
                continue
            metric_text = _compiler_ir_metric_bounded_text(
                sample_text,
                max_sample_text_chars,
            )
            metric_sample = _compiler_ir_metric_sample_for_text(
                sample,
                metric_text=metric_text,
            )
            metric_sample_id = str(getattr(metric_sample, "sample_id", "") or sample_id)
            metric_text_length = len(metric_text)
            metric_text_truncated = metric_text_length < sample_text_length
            if metric_text_truncated:
                text_length_truncated_count += 1
            emit_progress(
                "sample_text_truncated",
                citation=citation,
                max_sample_text_chars=max_sample_text_chars,
                metric_sample_id=metric_sample_id,
                metric_text_length=metric_text_length,
                metric_text_policy=metric_text_policy,
                original_text_length=sample_text_length,
                sample_id=sample_id,
                sample_index=sample_index,
            )
        compiler_guidance = None
        if precomputed_guidance:
            compiler_guidance = precomputed_guidance[sample_index - 1]
        elif use_autoencoder_guidance and autoencoder is not None:
            guidance_requested_count += 1
            try:
                compiler_guidance = autoencoder.compiler_guidance_for_sample(
                    sample,
                    use_sample_memory=False,
                    top_k=guidance_top_k,
                )
                if compiler_guidance:
                    guidance_produced_count += 1
                else:
                    guidance_empty_count += 1
            except Exception:
                guidance_failures += 1
                compiler_guidance = None
        sample_cache_key = _compiler_ir_metric_sample_cache_key(
            metric_sample,
            codec=codec,
            compiler_guidance=compiler_guidance,
            guidance_top_k=guidance_top_k,
        )
        sample_timeout_cache_key = _compiler_ir_metric_sample_timeout_cache_key(
            metric_sample,
            codec=codec,
        )
        cached_result_payload = _read_metric_disk_cache(
            "compiler_ir_metric_sample",
            sample_cache_key,
        )
        timeout_record = _compiler_ir_metric_sample_timeout_record_from_cache_payload(
            cached_result_payload,
            requested_timeout_seconds=sample_timeout_seconds,
        )
        timeout_cache_kind = "compiler_ir_metric_sample"
        if timeout_record is None:
            timeout_record = _compiler_ir_metric_sample_timeout_record_from_cache_payload(
                _read_metric_disk_cache(
                    "compiler_ir_metric_sample_timeout",
                    sample_timeout_cache_key,
                ),
                requested_timeout_seconds=sample_timeout_seconds,
            )
            timeout_cache_kind = "compiler_ir_metric_sample_timeout"
        if timeout_record is not None:
            result_from_timeout_cache = True
            persistent_sample_cache_hits += 1
            persistent_sample_timeout_cache_hits += 1
            failures += 1
            sample_timeouts += 1
            timeout_fallback_count += 1
            skipped_sample_count += 1
            if len(sample_metric_records) < max(0, int(max_sample_metric_records)):
                cached_record = dict(timeout_record)
                cached_record["persistent_cache_kind"] = timeout_cache_kind
                sample_metric_records.append(cached_record)
            result = _compiler_ir_metric_timeout_fallback_result(
                metric_sample,
                metric_sample_id=metric_sample_id,
                metric_text=metric_text,
                metric_text_length=metric_text_length,
                original_text_length=sample_text_length,
                sample_timeout_seconds=sample_timeout_seconds,
            )
            emit_progress(
                "sample_timeout_cache_hit",
                citation=citation,
                persistent_sample_cache_hits=persistent_sample_cache_hits,
                persistent_sample_cache_misses=persistent_sample_cache_misses,
                persistent_sample_timeout_cache_hits=(
                    persistent_sample_timeout_cache_hits
                ),
                sample_id=sample_id,
                sample_index=sample_index,
                sample_timeout_seconds=sample_timeout_seconds,
                timeout_cache_kind=timeout_cache_kind,
            )
        else:
            result_from_timeout_cache = False
            result = _compiler_ir_metric_result_from_cache_payload(
                cached_result_payload
            )
        if result is None:
            persistent_sample_cache_misses += 1
            emit_progress(
                "sample_cache_miss",
                citation=citation,
                persistent_sample_cache_hits=persistent_sample_cache_hits,
                persistent_sample_cache_misses=persistent_sample_cache_misses,
                sample_id=sample_id,
                sample_index=sample_index,
            )
            try:
                with _compiler_ir_metric_sample_timeout(
                    sample_timeout_seconds
                ) as timeout_guarded:
                    result = codec.encode(
                        metric_sample.text,
                        document_id=metric_sample.sample_id,
                        citation=metric_sample.citation,
                        source=metric_sample.source,
                        source_embedding=metric_sample.embedding_vector,
                        compiler_guidance=compiler_guidance,
                    )
                if sample_timeout_seconds > 0.0 and not timeout_guarded:
                    emit_progress(
                        "sample_timeout_guard_unsupported",
                        citation=citation,
                        metric_sample_id=metric_sample_id,
                        sample_id=sample_id,
                        sample_index=sample_index,
                        sample_timeout_seconds=sample_timeout_seconds,
                    )
            except CompilerIRMetricSampleTimeout:
                failures += 1
                sample_timeouts += 1
                timeout_fallback_count += 1
                skipped_sample_count += 1
                result = _compiler_ir_metric_timeout_fallback_result(
                    metric_sample,
                    metric_sample_id=metric_sample_id,
                    metric_text=metric_text,
                    metric_text_length=metric_text_length,
                    original_text_length=sample_text_length,
                    sample_timeout_seconds=sample_timeout_seconds,
                )
                family_distribution = result.metadata.get(
                    "compiler_ir_metric_timeout_family_distribution"
                )
                sample_record = {
                    "compiler_ir_metric_timeout_fallback": True,
                    "compiler_ir_metric_timeout_fallback_kind": str(
                        result.metadata.get("compiler_ir_metric_timeout_fallback_kind")
                        or ""
                    ),
                    "citation": citation,
                    "metric_sample_id": metric_sample_id,
                    "metric_text_length": metric_text_length,
                    "metric_text_policy": metric_text_policy,
                    "metric_text_truncated": metric_text_truncated,
                    "original_text_length": sample_text_length,
                    "sample_id": sample_id,
                    "sample_timeout_seconds": sample_timeout_seconds,
                    "skip_reason": "sample_timeout",
                    "source_text_preview": re.sub(r"\s+", " ", metric_text).strip()[
                        :240
                    ],
                    "text_length": metric_text_length,
                }
                if isinstance(family_distribution, Mapping):
                    sample_record["compiler_ir_metric_timeout_family_distribution"] = {
                        str(key): float(value)
                        for key, value in family_distribution.items()
                        if isinstance(value, (int, float))
                    }
                if len(sample_metric_records) < max(0, int(max_sample_metric_records)):
                    sample_metric_records.append(sample_record)
                timeout_payload = _compiler_ir_metric_sample_timeout_cache_payload(
                    sample_record
                )
                _write_metric_disk_cache(
                    "compiler_ir_metric_sample",
                    sample_cache_key,
                    timeout_payload,
                )
                _write_metric_disk_cache(
                    "compiler_ir_metric_sample_timeout",
                    sample_timeout_cache_key,
                    timeout_payload,
                )
                emit_progress(
                    "sample_timeout",
                    citation=citation,
                    failures=failures,
                    metric_sample_id=metric_sample_id,
                    metric_text_length=metric_text_length,
                    metric_text_truncated=metric_text_truncated,
                    sample_id=sample_id,
                    sample_index=sample_index,
                    sample_seconds=round(time.time() - sample_started_at, 3),
                    sample_timeout_seconds=sample_timeout_seconds,
                    text_length=metric_text_length,
                )
            except Exception:
                failures += 1
                emit_progress(
                    "sample_failed",
                    citation=citation,
                    failures=failures,
                    sample_id=sample_id,
                    sample_index=sample_index,
                    sample_seconds=round(time.time() - sample_started_at, 3),
                )
                continue
            if not bool(
                getattr(result, "metadata", {}).get(
                    "compiler_ir_metric_timeout_fallback"
                )
            ):
                _write_metric_disk_cache(
                    "compiler_ir_metric_sample",
                    sample_cache_key,
                    _compiler_ir_metric_result_cache_payload(result),
                )
        elif not result_from_timeout_cache:
            persistent_sample_cache_hits += 1
            emit_progress(
                "sample_persistent_cache_hit",
                citation=citation,
                persistent_sample_cache_hits=persistent_sample_cache_hits,
                persistent_sample_cache_misses=persistent_sample_cache_misses,
                sample_id=sample_id,
                sample_index=sample_index,
            )
        for name in losses:
            value = result.losses.get(name)
            if value is not None:
                losses[name].append(float(value))
        formula_counts.append(float(len(result.modal_ir.formulas)))
        frame_candidate_counts.append(float(len(result.frame_candidates)))
        llm_call_counts.append(float(result.metadata.get("llm_call_count", 0.0)))
        sample_record: Dict[str, Any] = {
            "citation": str(getattr(sample, "citation", "") or ""),
            "compiler_guidance_applied": bool(
                result.metadata.get("compiler_guidance_applied")
            ),
            "compiler_guidance_legal_ir_view_gaps": [],
            "compiler_guidance_semantic_overlay_terms": [],
            "compiler_guidance_todo_routes": [],
            "metrics": {
                name: round(float(result.losses[name]), 9)
                for name in COMPILER_GUIDANCE_CANARY_METRICS
                if name in result.losses and result.losses.get(name) is not None
            },
            "metric_sample_id": metric_sample_id,
            "metric_text_length": metric_text_length,
            "metric_text_policy": metric_text_policy,
            "metric_text_truncated": metric_text_truncated,
            "original_text_length": sample_text_length,
            "sample_id": str(getattr(sample, "sample_id", "") or ""),
            "source_text_preview": re.sub(
                r"\s+",
                " ",
                metric_text,
            ).strip()[:240],
            "text_length": metric_text_length,
        }
        if result.metadata.get("compiler_ir_metric_timeout_fallback"):
            sample_record["compiler_ir_metric_timeout_fallback"] = True
            sample_record["compiler_ir_metric_timeout_fallback_kind"] = str(
                result.metadata.get("compiler_ir_metric_timeout_fallback_kind") or ""
            )
            family_distribution = result.metadata.get(
                "compiler_ir_metric_timeout_family_distribution"
            )
            if isinstance(family_distribution, Mapping):
                sample_record["compiler_ir_metric_timeout_family_distribution"] = {
                    str(key): float(value)
                    for key, value in family_distribution.items()
                    if isinstance(value, (int, float))
                }
            sample_record["sample_timeout_seconds"] = float(
                result.metadata.get("sample_timeout_seconds", sample_timeout_seconds)
                or 0.0
            )
            sample_record["skip_reason"] = "sample_timeout"
        structural_preview = str(
            result.metadata.get("modal_decompiler_structural_text") or ""
        )
        if structural_preview:
            sample_record["decompiled_text_preview"] = re.sub(
                r"\s+",
                " ",
                structural_preview,
            ).strip()[:240]
        if result.metadata.get("compiler_guidance_applied"):
            guidance_applied_count += 1
            guidance_frame_boost_counts.append(
                float(result.metadata.get("compiler_guidance_frame_boost_count", 0.0))
            )
            guidance_semantic_overlay_counts.append(
                float(
                    result.metadata.get(
                        "compiler_guidance_semantic_overlay_count",
                        0.0,
                    )
                )
            )
            overlay_terms = result.metadata.get(
                "compiler_guidance_semantic_overlay_terms"
            )
            if isinstance(overlay_terms, Sequence) and not isinstance(
                overlay_terms,
                (str, bytes),
            ):
                for value in overlay_terms:
                    if str(value):
                        guidance_semantic_overlay_terms[str(value)] += 1
                sample_record["compiler_guidance_semantic_overlay_terms"] = [
                    str(value) for value in overlay_terms if str(value)
                ]
            if (
                result.metadata.get("compiler_guidance_selected_frame_before")
                != result.metadata.get("compiler_guidance_selected_frame_after")
            ):
                guidance_frame_changed_count += 1
            slot_texts = compiler_guidance_slot_texts_from_result(result)
            for value in slot_texts.get("compiler_guidance_feature_group", []):
                guidance_feature_groups[str(value)] += 1
            sample_view_gaps = [
                str(value)
                for value in slot_texts.get(
                    "compiler_guidance_legal_ir_view_gap_direction",
                    [],
                )
                if str(value)
            ]
            sample_record["compiler_guidance_legal_ir_view_gaps"] = list(
                dict.fromkeys(sample_view_gaps)
            )
            for value in sample_view_gaps:
                guidance_legal_ir_view_gaps[value] += 1
            for value in slot_texts.get(
                "compiler_guidance_decompiler_surface_template_feature",
                [],
            ):
                guidance_surface_features[str(value)] += 1
            sample_todo_routes = [
                str(value)
                for value in slot_texts.get("compiler_guidance_todo_route", [])
                if str(value)
            ]
            sample_record["compiler_guidance_todo_routes"] = list(
                dict.fromkeys(sample_todo_routes)
            )
            for value in sample_todo_routes:
                guidance_todo_routes[value] += 1
            for route in dict.fromkeys(sample_todo_routes):
                examples = guidance_todo_route_examples.setdefault(route, [])
                if len(examples) >= 3:
                    continue
                text_preview = re.sub(
                    r"\s+",
                    " ",
                        metric_text,
                    ).strip()[:240]
                examples.append(
                    {
                        "citation": str(getattr(sample, "citation", "") or ""),
                        "sample_id": str(getattr(sample, "sample_id", "") or ""),
                        "selected_frame_after": str(
                            result.metadata.get(
                                "compiler_guidance_selected_frame_after",
                                "",
                            )
                            or ""
                        ),
                        "selected_frame_before": str(
                            result.metadata.get(
                                "compiler_guidance_selected_frame_before",
                                "",
                            )
                            or ""
                        ),
                        "text_preview": text_preview,
                    }
                )
        if len(sample_metric_records) < max(0, int(max_sample_metric_records)):
            sample_metric_records.append(sample_record)
        emit_progress(
            "sample_done",
            citation=citation,
            evaluated_count=len(formula_counts),
            failures=failures,
            formula_count=len(result.modal_ir.formulas),
            frame_candidate_count=len(result.frame_candidates),
            metric_sample_id=metric_sample_id,
            metric_text_length=metric_text_length,
            metric_text_truncated=metric_text_truncated,
            sample_id=sample_id,
            sample_index=sample_index,
            sample_seconds=round(time.time() - sample_started_at, 3),
        )

    block: Dict[str, Any] = {
        "autoencoder_guidance_enabled": bool(use_autoencoder_guidance),
        "autoencoder_guidance_applied_count": guidance_applied_count,
        "autoencoder_guidance_empty_count": guidance_empty_count,
        "autoencoder_guidance_failures": guidance_failures,
        "autoencoder_guidance_produced_count": guidance_produced_count,
        "autoencoder_guidance_requested_count": guidance_requested_count,
        "autoencoder_guidance_unapplied_count": max(
            0,
            guidance_produced_count - guidance_applied_count,
        ),
        "compiler_ir_guidance_cache_policy": _COMPILER_IR_GUIDANCE_CACHE_POLICY,
        "evaluated_count": len(formula_counts),
        "max_sample_text_chars": max_sample_text_chars,
        "metric_text_policy": metric_text_policy,
        "metric_failures": failures,
        "persistent_sample_cache_hits": persistent_sample_cache_hits,
        "persistent_sample_cache_misses": persistent_sample_cache_misses,
        "persistent_sample_timeout_cache_hits": persistent_sample_timeout_cache_hits,
        "sample_timeout_cache_policy": _COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY,
        "sample_timeout_seconds": sample_timeout_seconds,
        "sample_timeout_supported": sample_timeout_supported,
        "sample_timeouts": sample_timeouts,
        "sample_count": len(sample_list),
        "skipped_sample_count": skipped_sample_count,
        "text_length_skipped_count": text_length_skipped_count,
        "text_length_truncated_count": text_length_truncated_count,
        "timeout_fallback_count": timeout_fallback_count,
    }
    if use_autoencoder_guidance:
        block["compiler_guidance_diagnostics_version"] = (
            _COMPILER_IR_GUIDANCE_DIAGNOSTICS_VERSION
        )
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
    if guidance_frame_boost_counts:
        block["compiler_guidance_frame_boost_count"] = round(
            sum(guidance_frame_boost_counts) / len(guidance_frame_boost_counts),
            9,
        )
        block["compiler_guidance_frame_changed_count"] = guidance_frame_changed_count
    if guidance_semantic_overlay_counts:
        block["compiler_guidance_semantic_overlay_count"] = round(
            sum(guidance_semantic_overlay_counts)
            / len(guidance_semantic_overlay_counts),
            9,
        )
    if use_autoencoder_guidance or guidance_semantic_overlay_terms:
        block["compiler_guidance_semantic_overlay_terms"] = dict(
            guidance_semantic_overlay_terms.most_common(12)
        )
    if use_autoencoder_guidance or guidance_feature_groups:
        block["compiler_guidance_feature_groups"] = dict(
            guidance_feature_groups.most_common(12)
        )
    if use_autoencoder_guidance or guidance_legal_ir_view_gaps:
        block["compiler_guidance_legal_ir_view_gaps"] = dict(
            guidance_legal_ir_view_gaps.most_common(12)
        )
    if use_autoencoder_guidance or guidance_surface_features:
        block["compiler_guidance_surface_features"] = dict(
            guidance_surface_features.most_common(12)
        )
    if use_autoencoder_guidance or guidance_todo_routes:
        block["compiler_guidance_todo_routes"] = dict(
            guidance_todo_routes.most_common(12)
        )
    if guidance_todo_routes:
        block["compiler_guidance_todo_route_examples"] = {
            route: guidance_todo_route_examples.get(route, [])[:3]
            for route, _ in guidance_todo_routes.most_common(12)
            if guidance_todo_route_examples.get(route)
        }
    if sample_metric_records:
        block["sample_metric_records"] = sample_metric_records
        block["worst_source_decompiled_text_records"] = (
            _worst_source_decompiled_text_records(sample_metric_records)
        )
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
    if "structural_text_reconstruction_loss" in block:
        block["structural_text_reconstruction_similarity"] = round(
            1.0 - float(block["structural_text_reconstruction_loss"]),
            9,
        )
    if "source_decompiled_text_embedding_cosine_loss" in block:
        block["source_decompiled_text_embedding_cosine_gap"] = round(
            float(block["source_decompiled_text_embedding_cosine_loss"]),
            9,
        )
    if persistent_cache_key is not None and sample_timeouts <= 0:
        block["persistent_cache_enabled"] = _metric_disk_cache_enabled()
        block["persistent_cache_hit"] = False
        block["persistent_cache_key"] = persistent_cache_key
        block["persistent_cache_kind"] = "compiler_ir_metric_block"
        _write_metric_disk_cache(
            "compiler_ir_metric_block",
            persistent_cache_key,
            block,
        )
    emit_progress(
        "done",
        evaluated_count=len(formula_counts),
        failures=failures,
        sample_timeouts=sample_timeouts,
        skipped_sample_count=skipped_sample_count,
    )
    return block


def _worst_source_decompiled_text_records(
    records: Sequence[Mapping[str, Any]],
    *,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Return samples with the worst source text -> structural decompiled text gaps."""

    ranked: List[tuple[float, Dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        metrics = record.get("metrics")
        if not isinstance(metrics, Mapping):
            continue
        embedding_gap = _metric_value(
            metrics,
            "source_decompiled_text_embedding_cosine_loss",
            default=max(
                0.0,
                1.0
                - _metric_value(
                    metrics,
                    "source_decompiled_text_embedding_cosine_similarity",
                    default=_metric_value(
                        metrics,
                        "cosine_similarity",
                        default=_metric_value(
                            metrics,
                            "raw_source_embedding_cosine_similarity",
                            default=1.0,
                        ),
                    ),
                ),
            ),
        )
        token_loss = _metric_value(
            metrics,
            "source_decompiled_text_token_loss",
            default=_metric_value(
                metrics,
                "structural_text_reconstruction_loss",
                default=0.0,
            ),
        )
        copy_hack = _metric_value(metrics, "source_copy_reward_hack_penalty", default=0.0)
        structural_loss = _metric_value(
            metrics,
            "structural_text_reconstruction_loss",
            default=0.0,
        )
        score = embedding_gap + token_loss + copy_hack + structural_loss
        if score <= 0.0:
            continue
        ranked.append(
            (
                score,
                {
                    "citation": str(record.get("citation") or ""),
                    "decompiled_text_preview": str(
                        record.get("decompiled_text_preview") or ""
                    ),
                    "source_text_preview": str(record.get("source_text_preview") or ""),
                    "sample_id": str(record.get("sample_id") or ""),
                    "source_decompiled_text_embedding_cosine_loss": round(
                        embedding_gap,
                        9,
                    ),
                    "source_decompiled_text_token_loss": round(token_loss, 9),
                    "source_copy_reward_hack_penalty": round(copy_hack, 9),
                    "structural_text_reconstruction_loss": round(structural_loss, 9),
                },
            )
        )
    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1]["sample_id"],
            item[1]["citation"],
        )
    )
    return [row for _score, row in ranked[: max(0, int(limit))]]


def _metric_value(block: Mapping[str, Any], name: str, default: float = 1.0e12) -> float:
    try:
        value = float(block.get(name, default))
    except (TypeError, ValueError):
        return default
    if value != value:
        return default
    return value


def _metric_optional_value(block: Mapping[str, Any], name: str) -> Optional[float]:
    if name not in block:
        return None
    try:
        value = float(block.get(name))
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value


def _metric_count_value(block: Mapping[str, Any], name: str) -> int:
    try:
        return int(block.get(name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def autoencoder_validation_signal_health(
    *,
    compiler_ir_validation: Mapping[str, Any],
    learned_ir_validation: Mapping[str, Any],
    logic_bridge_validation: Mapping[str, Any],
    validation_metrics: Mapping[str, Any],
    metric_bridge_adapters: Sequence[str] = (),
    diagnostic_bridge_adapters: Sequence[str] = (),
    minimum_validation_samples: int = 8,
) -> Dict[str, Any]:
    """Summarize whether validation/projection signals are actually active."""

    issues: List[str] = []
    recommendations: List[str] = []
    validation_sample_count = _metric_count_value(validation_metrics, "sample_count")
    compiler_sample_count = _metric_count_value(compiler_ir_validation, "sample_count")
    compiler_evaluated_count = _metric_count_value(
        compiler_ir_validation,
        "evaluated_count",
    )
    compiler_sample_timeouts = _metric_count_value(
        compiler_ir_validation,
        "sample_timeouts",
    )
    compiler_skipped_count = _metric_count_value(
        compiler_ir_validation,
        "skipped_sample_count",
    )
    learned_ir_target_count = _metric_count_value(learned_ir_validation, "target_count")
    bridge_adapter_count = _metric_count_value(logic_bridge_validation, "adapter_count")
    bridge_evaluated_count = _metric_count_value(
        logic_bridge_validation,
        "evaluated_count",
    )
    metric_adapter_list = [str(name) for name in metric_bridge_adapters if str(name)]
    diagnostic_adapter_list = [
        str(name) for name in diagnostic_bridge_adapters if str(name)
    ]

    if validation_sample_count and validation_sample_count < max(
        1,
        int(minimum_validation_samples),
    ):
        issues.append("validation_holdout_too_small")
        recommendations.append(
            "increase validation-canary-count or use a stratified held-out manifest"
        )
    if not metric_adapter_list and learned_ir_target_count <= 0:
        issues.append("autoencoder_metric_bridge_adapters_empty")
        recommendations.append(
            "enable cheap LegalIR metric adapters such as modal_frame_logic,deontic_norms"
        )
    if learned_ir_target_count <= 0:
        issues.append("learned_ir_targets_inactive")
        recommendations.append(
            "ensure bridge-backed LegalIR targets are produced before trusting learned IR-view metrics"
        )
    if not diagnostic_adapter_list:
        if learned_ir_target_count > 0:
            recommendations.append(
                "run occasional diagnostic bridge sweeps for syntax/KG/prover coverage"
            )
    elif bridge_adapter_count <= 0:
        issues.append("logic_bridge_metrics_inactive")
        recommendations.append(
            "enable diagnostic bridge adapters so syntax/KG/prover validity is measured"
        )
    elif bridge_evaluated_count <= 0:
        issues.append("logic_bridge_no_samples_evaluated")
        recommendations.append(
            "check bridge sample caps and adapter failures; no bridge samples reached evaluation"
        )
    if compiler_sample_count > 0 and compiler_evaluated_count <= 0:
        if compiler_sample_timeouts >= compiler_sample_count:
            issues.append("compiler_ir_all_samples_timed_out")
            recommendations.append(
                "lower compiler metric sample length, split long samples, or raise the timeout budget"
            )
        elif compiler_skipped_count >= compiler_sample_count:
            issues.append("compiler_ir_all_samples_skipped")
            recommendations.append(
                "rotate smaller compiler metric samples or enable a truncating metric mode"
            )
        else:
            issues.append("compiler_ir_no_samples_evaluated")
            recommendations.append(
                "inspect compiler IR metric sample records for failures before using sentinel CE/cosine"
            )

    blocking_issues = {
        "autoencoder_metric_bridge_adapters_empty",
        "learned_ir_targets_inactive",
        "compiler_ir_all_samples_timed_out",
        "compiler_ir_no_samples_evaluated",
    }
    if diagnostic_adapter_list:
        blocking_issues.add("logic_bridge_metrics_inactive")
    if any(issue in blocking_issues for issue in issues):
        quality_gate = "fail"
    elif issues:
        quality_gate = "warn"
    else:
        quality_gate = "pass"
    return {
        "compiler_ir": {
            "evaluated_count": compiler_evaluated_count,
            "sample_count": compiler_sample_count,
            "sample_timeouts": compiler_sample_timeouts,
            "skipped_sample_count": compiler_skipped_count,
        },
        "diagnostic_bridge_adapters": diagnostic_adapter_list,
        "issues": list(dict.fromkeys(issues)),
        "learned_ir": {
            "target_count": learned_ir_target_count,
        },
        "logic_bridge": {
            "adapter_count": bridge_adapter_count,
            "evaluated_count": bridge_evaluated_count,
        },
        "metric_bridge_adapters": metric_adapter_list,
        "quality_gate": quality_gate,
        "recommendations": list(dict.fromkeys(recommendations)),
        "validation": {
            "minimum_recommended_sample_count": max(
                1,
                int(minimum_validation_samples),
            ),
            "sample_count": validation_sample_count,
        },
    }


def rollout_baseline_snapshot(
    *,
    summary: Mapping[str, Any],
    cycle: int,
    cycle_seconds: float,
    cycle_phase_timings: Mapping[str, Any],
    validation_metrics: Mapping[str, Any],
    compiler_ir_validation: Mapping[str, Any],
    learned_ir_validation: Mapping[str, Any],
    logic_bridge_validation: Mapping[str, Any],
    queue_counts: Mapping[str, Any],
    role_queue_counts: Mapping[str, Any],
    state_telemetry: Mapping[str, Any],
    embedding_report: Mapping[str, Any],
    backend_metadata: Mapping[str, Any],
    host_resource_health: Mapping[str, Any],
    compiler_ir_guided_validation: Optional[Mapping[str, Any]] = None,
    metric_bridge_adapters: Sequence[str] = (),
    diagnostic_bridge_adapters: Sequence[str] = (),
) -> Dict[str, Any]:
    """Return a stable rollout comparison snapshot for autoencoder experiments."""

    compiler_ir_guided_validation = compiler_ir_guided_validation or {}
    state_file = state_telemetry.get("state_file")
    if not isinstance(state_file, Mapping):
        state_file = {}
    low_rank_sidecar = state_telemetry.get("low_rank_sidecar")
    if not isinstance(low_rank_sidecar, Mapping):
        low_rank_sidecar = {}
    status_counts = {str(key): int(value) for key, value in queue_counts.items()}
    failed_validation_count = int(status_counts.get("failed_validation", 0))
    signal_health = autoencoder_validation_signal_health(
        compiler_ir_validation=compiler_ir_validation,
        learned_ir_validation=learned_ir_validation,
        logic_bridge_validation=logic_bridge_validation,
        validation_metrics=validation_metrics,
        metric_bridge_adapters=metric_bridge_adapters,
        diagnostic_bridge_adapters=diagnostic_bridge_adapters,
    )
    return {
        "autoencoder_architecture_version": str(
            summary.get("autoencoder_architecture_version")
            or MODAL_AUTOENCODER_ARCHITECTURE_VERSION
        ),
        "autoencoder_state_schema_version": str(
            summary.get("autoencoder_state_schema_version")
            or MODAL_AUTOENCODER_STATE_SCHEMA_VERSION
        ),
        "backend": dict(backend_metadata),
        "compiler_ir_validation": {
            "cosine_similarity": _metric_optional_value(
                compiler_ir_validation,
                "cosine_similarity",
            ),
            "cross_entropy_excess_loss": _metric_optional_value(
                compiler_ir_validation,
                "cross_entropy_excess_loss",
            ),
            "cross_entropy_loss": _metric_optional_value(
                compiler_ir_validation,
                "cross_entropy_loss",
            ),
            "evaluated_count": _metric_count_value(
                compiler_ir_validation,
                "evaluated_count",
            ),
            "metric_failures": _metric_count_value(
                compiler_ir_validation,
                "metric_failures",
            ),
            "raw_source_embedding_cosine_similarity": _metric_optional_value(
                compiler_ir_validation,
                "raw_source_embedding_cosine_similarity",
            ),
            "sample_count": _metric_count_value(
                compiler_ir_validation,
                "sample_count",
            ),
            "sample_timeouts": _metric_count_value(
                compiler_ir_validation,
                "sample_timeouts",
            ),
            "skipped_sample_count": _metric_count_value(
                compiler_ir_validation,
                "skipped_sample_count",
            ),
            "source_copy_loss": _metric_optional_value(
                compiler_ir_validation,
                "source_copy_loss",
            ),
            "source_copy_reward_hack_penalty": _metric_optional_value(
                compiler_ir_validation,
                "source_copy_reward_hack_penalty",
            ),
            "source_decompiled_text_embedding_cosine_loss": _metric_optional_value(
                compiler_ir_validation,
                "source_decompiled_text_embedding_cosine_loss",
            ),
            "source_decompiled_text_token_loss": _metric_optional_value(
                compiler_ir_validation,
                "source_decompiled_text_token_loss",
            ),
            "text_length_skipped_count": _metric_count_value(
                compiler_ir_validation,
                "text_length_skipped_count",
            ),
        },
        "compiler_ir_guided_validation": {
            "cosine_similarity": _metric_optional_value(
                compiler_ir_guided_validation,
                "cosine_similarity",
            ),
            "cross_entropy_loss": _metric_optional_value(
                compiler_ir_guided_validation,
                "cross_entropy_loss",
            ),
            "source_copy_reward_hack_penalty": _metric_optional_value(
                compiler_ir_guided_validation,
                "source_copy_reward_hack_penalty",
            ),
        },
        "compiler_ir_metric_cache": {
            "guided_validation_block_cache_hit": bool(
                compiler_ir_guided_validation.get("persistent_cache_hit", False)
            ),
            "guided_validation_sample_cache_hits": _metric_count_value(
                compiler_ir_guided_validation,
                "persistent_sample_cache_hits",
            ),
            "guided_validation_sample_cache_misses": _metric_count_value(
                compiler_ir_guided_validation,
                "persistent_sample_cache_misses",
            ),
            "validation_block_cache_hit": bool(
                compiler_ir_validation.get("persistent_cache_hit", False)
            ),
            "validation_sample_cache_hits": _metric_count_value(
                compiler_ir_validation,
                "persistent_sample_cache_hits",
            ),
            "validation_sample_cache_misses": _metric_count_value(
                compiler_ir_validation,
                "persistent_sample_cache_misses",
            ),
        },
        "cycle": int(cycle),
        "cycle_seconds": round(float(cycle_seconds), 3),
        "cycle_phase_timings": {
            str(name): round(float(seconds), 3)
            for name, seconds in sorted(cycle_phase_timings.items())
        },
        "embedding_report": dict(embedding_report),
        "failed_validation_count": failed_validation_count,
        "host_resource_health": dict(host_resource_health),
        "learned_feature_rows": {
            "generalizable_entry_count": _metric_count_value(
                state_telemetry,
                "generalizable_entry_count",
            ),
            "nested_logit_entry_count": _metric_count_value(
                state_telemetry,
                "nested_logit_entry_count",
            ),
            "vector_entry_count": _metric_count_value(
                state_telemetry,
                "vector_entry_count",
            ),
        },
        "learned_ir_view_validation": {
            "family_cross_entropy_excess_loss": _metric_optional_value(
                learned_ir_validation,
                "family_cross_entropy_excess_loss",
            ),
            "target_count": _metric_count_value(
                learned_ir_validation,
                "target_count",
            ),
            "view_cosine_similarity": _metric_optional_value(
                learned_ir_validation,
                "view_cosine_similarity",
            ),
            "view_cross_entropy_loss": _metric_optional_value(
                learned_ir_validation,
                "view_cross_entropy_loss",
            ),
            "worst_family_cosine_gap_loss": _metric_optional_value(
                learned_ir_validation,
                "worst_family_cosine_gap_loss",
            ),
            "worst_family_cross_entropy_excess_loss": _metric_optional_value(
                learned_ir_validation,
                "worst_family_cross_entropy_excess_loss",
            ),
        },
        "logic_bridge_validation": {
            "acceptance_rate": _metric_optional_value(
                logic_bridge_validation,
                "acceptance_rate",
            ),
            "adapter_count": _metric_count_value(
                logic_bridge_validation,
                "adapter_count",
            ),
            "evaluated_count": _metric_count_value(
                logic_bridge_validation,
                "evaluated_count",
            ),
            "metric_failures": _metric_count_value(
                logic_bridge_validation,
                "metric_failures",
            ),
            "proof_failure_ratio": _metric_optional_value(
                logic_bridge_validation,
                "proof_failure_ratio",
            ),
            "sample_count": _metric_count_value(
                logic_bridge_validation,
                "sample_count",
            ),
            "total_loss": _metric_optional_value(
                logic_bridge_validation,
                "total_loss",
            ),
        },
        "metric_schema_version": str(
            summary.get("metric_schema_version") or USCODE_DAEMON_METRIC_SCHEMA_VERSION
        ),
        "queue_counts": status_counts,
        "role_queue_counts": {
            str(role): {
                str(status): int(count)
                for status, count in dict(counts or {}).items()
            }
            for role, counts in role_queue_counts.items()
        },
        "run_id": str(summary.get("run_id") or ""),
        "signal_health": signal_health,
        "state_file": {
            "path": str(state_file.get("path") or summary.get("state_path") or ""),
            "size_bytes": _metric_count_value(state_file, "size_bytes"),
            "size_mb": _metric_optional_value(state_file, "size_mb"),
        },
        "state_low_rank_sidecar": {
            "complete": bool(low_rank_sidecar.get("complete", False)),
            "enabled": bool(low_rank_sidecar.get("enabled", False)),
            "size_mb": _metric_optional_value(
                low_rank_sidecar.get("file", {})
                if isinstance(low_rank_sidecar.get("file"), Mapping)
                else {},
                "size_mb",
            ),
            "status": str(low_rank_sidecar.get("status") or ""),
            "vector_entry_count": _metric_count_value(
                low_rank_sidecar,
                "vector_entry_count",
            ),
        },
        "validation": {
            "cosine_similarity": _metric_optional_value(
                validation_metrics,
                "cosine_similarity",
            ),
            "cross_entropy_excess_loss": _metric_optional_value(
                validation_metrics,
                "cross_entropy_excess_loss",
            ),
            "cross_entropy_loss": _metric_optional_value(
                validation_metrics,
                "cross_entropy_loss",
            ),
            "reconstruction_loss": _metric_optional_value(
                validation_metrics,
                "reconstruction_loss",
            ),
            "sample_count": _metric_count_value(validation_metrics, "sample_count"),
        },
    }


def _record_metric_value(
    record: Mapping[str, Any],
    name: str,
    default: float = 1.0e12,
) -> float:
    metrics = record.get("metrics")
    if not isinstance(metrics, Mapping):
        return default
    try:
        value = float(metrics.get(name, default))
    except (TypeError, ValueError):
        return default
    if value != value:
        return default
    return value


def _sample_metric_records_by_id(
    block: Mapping[str, Any],
) -> Dict[str, Mapping[str, Any]]:
    records = block.get("sample_metric_records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return {}
    keyed: Dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        sample_id = str(record.get("sample_id") or "").strip()
        citation = str(record.get("citation") or "").strip()
        key = sample_id or citation
        if key:
            keyed[key] = record
    return keyed


def _guidance_count_mapping(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    counts: Dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        try:
            count = float(raw_value)
        except (TypeError, ValueError):
            continue
        if count > 0.0 and count == count:
            counts[key] = count
    return counts


def _guidance_record_items(record: Mapping[str, Any], key: str) -> List[str]:
    values = record.get(key)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _record_canary_deltas(
    plain_record: Mapping[str, Any],
    guided_record: Mapping[str, Any],
) -> Dict[str, float]:
    plain_ce = _record_metric_value(plain_record, "cross_entropy_loss")
    guided_ce = _record_metric_value(guided_record, "cross_entropy_loss")
    plain_ce_excess = _record_metric_value(plain_record, "cross_entropy_excess_loss")
    guided_ce_excess = _record_metric_value(guided_record, "cross_entropy_excess_loss")
    plain_cosine = _record_metric_value(plain_record, "cosine_similarity", -1.0)
    guided_cosine = _record_metric_value(guided_record, "cosine_similarity", -1.0)
    plain_copy_hack = _record_metric_value(
        plain_record,
        "source_copy_reward_hack_penalty",
    )
    guided_copy_hack = _record_metric_value(
        guided_record,
        "source_copy_reward_hack_penalty",
    )
    plain_source_copy = _record_metric_value(plain_record, "source_copy_loss")
    guided_source_copy = _record_metric_value(guided_record, "source_copy_loss")
    plain_text_cosine_loss = _record_metric_value(
        plain_record,
        "source_decompiled_text_embedding_cosine_loss",
        default=max(
            0.0,
            1.0
            - _record_metric_value(
                plain_record,
                "source_decompiled_text_embedding_cosine_similarity",
                default=_record_metric_value(
                    plain_record,
                    "cosine_similarity",
                    default=_record_metric_value(
                        plain_record,
                        "raw_source_embedding_cosine_similarity",
                        default=1.0,
                    ),
                ),
            ),
        ),
    )
    guided_text_cosine_loss = _record_metric_value(
        guided_record,
        "source_decompiled_text_embedding_cosine_loss",
        default=max(
            0.0,
            1.0
            - _record_metric_value(
                guided_record,
                "source_decompiled_text_embedding_cosine_similarity",
                default=_record_metric_value(
                    guided_record,
                    "cosine_similarity",
                    default=_record_metric_value(
                        guided_record,
                        "raw_source_embedding_cosine_similarity",
                        default=1.0,
                    ),
                ),
            ),
        ),
    )
    return {
        "ce_delta": plain_ce - guided_ce,
        "ce_excess_delta": plain_ce_excess - guided_ce_excess,
        "copy_hack_delta": plain_copy_hack - guided_copy_hack,
        "cosine_delta": guided_cosine - plain_cosine,
        "source_copy_delta": plain_source_copy - guided_source_copy,
        "source_decompiled_text_cosine_loss_delta": (
            plain_text_cosine_loss - guided_text_cosine_loss
        ),
    }


def _finalize_guidance_attribution(
    stats: Mapping[str, Dict[str, float]],
    *,
    threshold: float,
    limit: int = 12,
) -> Dict[str, Dict[str, Any]]:
    rows: List[tuple[str, Dict[str, Any]]] = []
    for key, values in stats.items():
        count = max(1.0, float(values.get("count", 0.0) or 0.0))
        row = {
            "ce_delta": round(float(values.get("ce_delta", 0.0)) / count, 9),
            "ce_excess_delta": round(
                float(values.get("ce_excess_delta", 0.0)) / count,
                9,
            ),
            "copy_hack_delta": round(
                float(values.get("copy_hack_delta", 0.0)) / count,
                9,
            ),
            "cosine_delta": round(
                float(values.get("cosine_delta", 0.0)) / count,
                9,
            ),
            "count": int(count) if count.is_integer() else round(count, 9),
            "source_copy_delta": round(
                float(values.get("source_copy_delta", 0.0)) / count,
                9,
            ),
            "source_decompiled_text_cosine_loss_delta": round(
                float(
                    values.get(
                        "source_decompiled_text_cosine_loss_delta",
                        0.0,
                    )
                )
                / count,
                9,
            ),
        }
        core = (
            row["ce_delta"],
            row["copy_hack_delta"],
            row["cosine_delta"],
            row["source_decompiled_text_cosine_loss_delta"],
        )
        if any(value < -threshold for value in core):
            gate = "fail"
        elif any(value > threshold for value in core):
            gate = "pass"
        else:
            gate = "warn"
        row["quality_gate"] = gate
        row["objective_delta"] = round(
            float(row["ce_delta"])
            + float(row["copy_hack_delta"])
            + float(row["cosine_delta"])
            + float(row["source_decompiled_text_cosine_loss_delta"]),
            9,
        )
        rows.append((str(key), row))
    rows.sort(
        key=lambda item: (
            -float(item[1].get("objective_delta", 0.0)),
            -float(item[1].get("count", 0.0)),
            item[0],
        )
    )
    return {key: row for key, row in rows[: max(0, int(limit))]}


def _compiler_guidance_canary_attribution(
    deterministic_block: Mapping[str, Any],
    guided_block: Mapping[str, Any],
    canary_block: Mapping[str, Any],
    *,
    threshold: float,
) -> Dict[str, Any]:
    plain_records = _sample_metric_records_by_id(deterministic_block)
    guided_records = _sample_metric_records_by_id(guided_block)
    gap_stats: Dict[str, Dict[str, float]] = {}
    term_stats: Dict[str, Dict[str, float]] = {}
    route_stats: Dict[str, Dict[str, float]] = {}
    matched_count = 0
    for key, guided_record in guided_records.items():
        if not guided_record.get("compiler_guidance_applied"):
            continue
        plain_record = plain_records.get(key)
        if not plain_record:
            continue
        deltas = _record_canary_deltas(plain_record, guided_record)
        matched_count += 1
        for item_key, stats in (
            (
                "compiler_guidance_semantic_overlay_terms",
                term_stats,
            ),
            ("compiler_guidance_legal_ir_view_gaps", gap_stats),
            ("compiler_guidance_todo_routes", route_stats),
        ):
            for item in _guidance_record_items(guided_record, item_key):
                bucket = stats.setdefault(item, {"count": 0.0})
                bucket["count"] = float(bucket.get("count", 0.0)) + 1.0
                for delta_name, delta_value in deltas.items():
                    bucket[delta_name] = float(bucket.get(delta_name, 0.0)) + float(
                        delta_value
                    )

    basis = "sample_records" if matched_count > 0 else "aggregate_counts"
    if matched_count <= 0:
        aggregate_deltas = {
            name: float(canary_block.get(name, 0.0) or 0.0)
            for name in (
                "ce_delta",
                "ce_excess_delta",
                "copy_hack_delta",
                "cosine_delta",
                "source_copy_delta",
            )
        }
        for mapping_name, stats in (
            ("compiler_guidance_semantic_overlay_terms", term_stats),
            ("compiler_guidance_legal_ir_view_gaps", gap_stats),
            ("compiler_guidance_todo_routes", route_stats),
        ):
            for item, count in _guidance_count_mapping(
                guided_block.get(mapping_name)
            ).items():
                bucket = stats.setdefault(item, {"count": 0.0})
                bucket["count"] = float(bucket.get("count", 0.0)) + count
                for delta_name, delta_value in aggregate_deltas.items():
                    bucket[delta_name] = float(bucket.get(delta_name, 0.0)) + (
                        float(delta_value) * count
                    )

    terms = _finalize_guidance_attribution(
        term_stats,
        threshold=threshold,
    )
    routes = _finalize_guidance_attribution(
        route_stats,
        threshold=threshold,
    )
    gaps = _finalize_guidance_attribution(
        gap_stats,
        threshold=threshold,
    )
    return {
        "basis": basis,
        "has_attribution": bool(gaps or terms or routes),
        "legal_ir_view_gaps": gaps,
        "matched_sample_count": matched_count,
        "semantic_overlay_terms": terms,
        "todo_routes": routes,
    }


def _guidance_attribution_summary(attribution: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact pass/warn/fail buckets for TODO prompts and reports."""
    if not isinstance(attribution, Mapping):
        return {}
    summary: Dict[str, Any] = {}
    for source_key, prefix in (
        ("legal_ir_view_gaps", "legal_ir_view_gaps"),
        ("semantic_overlay_terms", "semantic_overlay_terms"),
        ("todo_routes", "todo_routes"),
    ):
        rows = attribution.get(source_key)
        if not isinstance(rows, Mapping):
            continue
        gates: Dict[str, List[str]] = {"fail": [], "pass": [], "warn": []}
        for key, row in rows.items():
            if not isinstance(row, Mapping):
                continue
            gate = str(row.get("quality_gate") or "warn")
            if gate not in gates:
                gate = "warn"
            gates[gate].append(str(key))
        for gate, values in gates.items():
            if values:
                summary[f"{gate}_{prefix}"] = values
    if attribution.get("basis"):
        summary["basis"] = str(attribution.get("basis"))
    if attribution.get("matched_sample_count") is not None:
        summary["matched_sample_count"] = int(
            attribution.get("matched_sample_count") or 0
        )
    return summary


def compiler_guidance_canary_block(
    deterministic_block: Mapping[str, Any],
    guided_block: Mapping[str, Any],
    *,
    plateau_threshold: float = 1.0e-5,
) -> Dict[str, Any]:
    """Compare deterministic compiler IR metrics with guided compiler IR metrics.

    Positive deltas mean guidance improved that metric. This block is intentionally
    scale-aware: raw cross entropy is compared with raw cross entropy, while CE
    excess stays a separate KL-style diagnostic.
    """
    threshold = max(0.0, float(plateau_threshold))
    applied_count = int(guided_block.get("autoencoder_guidance_applied_count", 0) or 0)
    enabled = bool(guided_block.get("autoencoder_guidance_enabled"))
    plain_ce = _metric_value(deterministic_block, "cross_entropy_loss")
    guided_ce = _metric_value(guided_block, "cross_entropy_loss")
    plain_ce_excess = _metric_value(deterministic_block, "cross_entropy_excess_loss")
    guided_ce_excess = _metric_value(guided_block, "cross_entropy_excess_loss")
    plain_cosine = _metric_value(deterministic_block, "cosine_similarity", -1.0)
    guided_cosine = _metric_value(guided_block, "cosine_similarity", -1.0)
    plain_copy_hack = _metric_value(
        deterministic_block,
        "source_copy_reward_hack_penalty",
    )
    guided_copy_hack = _metric_value(
        guided_block,
        "source_copy_reward_hack_penalty",
    )
    plain_source_copy = _metric_value(deterministic_block, "source_copy_loss")
    guided_source_copy = _metric_value(guided_block, "source_copy_loss")
    deltas = {
        "ce_delta": plain_ce - guided_ce,
        "ce_excess_delta": plain_ce_excess - guided_ce_excess,
        "copy_hack_delta": plain_copy_hack - guided_copy_hack,
        "cosine_delta": guided_cosine - plain_cosine,
        "source_copy_delta": plain_source_copy - guided_source_copy,
    }
    core_names = ("ce_delta", "copy_hack_delta", "cosine_delta")
    improved = enabled and applied_count > 0 and any(
        deltas[name] > threshold for name in core_names
    )
    regressed = enabled and applied_count > 0 and any(
        deltas[name] < -threshold for name in core_names
    )
    if not enabled or applied_count <= 0:
        quality_gate = "inactive"
    elif regressed:
        quality_gate = "fail"
    elif improved:
        quality_gate = "pass"
    else:
        quality_gate = "warn"
    block = {
        "applied_count": applied_count,
        "ce_delta": round(deltas["ce_delta"], 9),
        "ce_excess_delta": round(deltas["ce_excess_delta"], 9),
        "copy_hack_delta": round(deltas["copy_hack_delta"], 9),
        "cosine_delta": round(deltas["cosine_delta"], 9),
        "enabled": enabled,
        "frame_boost_count": _metric_value(
            guided_block,
            "compiler_guidance_frame_boost_count",
            0.0,
        ),
        "frame_changed_count": int(
            guided_block.get("compiler_guidance_frame_changed_count", 0) or 0
        ),
        "improved": improved,
        "quality_gate": quality_gate,
        "regressed": regressed,
        "source_copy_delta": round(deltas["source_copy_delta"], 9),
        "threshold": threshold,
    }
    attribution = _compiler_guidance_canary_attribution(
        deterministic_block,
        guided_block,
        block,
        threshold=threshold,
    )
    if attribution.get("has_attribution"):
        block["attribution"] = attribution
    return block


GUIDANCE_ROUTE_TARGET_OVERRIDES = {
    "refine_amendment_operation": "modal.compiler",
    "refine_applicability_scope": "modal.compiler",
    "refine_authority_jurisdiction": "modal.frame_logic",
    "refine_condition_consequence": "modal.compiler",
    "refine_coreference_binding": "modal.compiler",
    "refine_defeasible_priority_scope": "modal.ir_decompiler",
    "refine_definition_grounding": "modal.compiler",
    "refine_discretion_standard": "modal.frame_logic",
    "refine_enforcement_remedy": "deontic.ir",
    "refine_enumeration_hierarchy": "modal.compiler",
    "refine_evidentiary_burden": "modal.ir_decompiler",
    "refine_legal_relation": "deontic.ir",
    "refine_logical_connective": "modal.compiler",
    "refine_mental_state": "modal.compiler",
    "refine_predicate_argument_binding": "modal.compiler",
    "refine_procedural_lifecycle": "CEC.native",
    "refine_quantifier_scope": "modal.compiler",
    "refine_quantitative_crossref_grounding": "modal.compiler",
    "refine_quantitative_formula": "modal.compiler",
    "refine_reference_dependency_graph": "knowledge_graphs.neo4j_compat",
    "refine_status_transition": "CEC.native",
    "refine_temporal_validity": "TDFOL.prover",
}

GUIDANCE_ROUTE_PREFIX_TARGETS = (
    ("repair_deontic", "deontic.ir"),
    ("repair_tdfol", "TDFOL.prover"),
    ("repair_cec", "CEC.native"),
    ("repair_external", "external_provers.router"),
    ("repair_zkp", "zkp.circuits"),
    ("repair_multiview_legal_ir_graph", "knowledge_graphs.neo4j_compat"),
    ("repair_multiview", "bridge.contracts"),
    ("repair_flogic", "modal.frame_logic"),
    ("audit_frame", "modal.frame_logic"),
    ("improve_bm25", "modal.frame_logic"),
    ("improve_flogic", "modal.frame_logic"),
    ("refine_modal_family", "modal.compiler.registry"),
    ("refine_semantic_decompiler", "modal.ir_decompiler"),
    ("refine_typed_ir", "modal.ir_decompiler"),
    ("increase_modal_ir_span", "modal.compiler"),
    ("add_deterministic_parser_rule", "modal.compiler"),
    ("add_or_review_modal_ambiguity", "modal.compiler.ambiguity"),
)


def _normalized_guidance_route(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")


def _top_numeric_items(
    values: Mapping[str, Any],
    *,
    limit: int = 8,
) -> Dict[str, float]:
    items: List[tuple[str, float]] = []
    for raw_key, raw_value in values.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if value <= 0.0 or value != value:
            continue
        items.append((key, value))
    items.sort(key=lambda item: (-item[1], item[0]))
    return {
        key: (int(value) if value.is_integer() else round(value, 9))
        for key, value in items[: max(0, int(limit))]
    }


def _compiler_guidance_fallback_todo_routes(
    *,
    top_feature_groups: Mapping[str, Any],
    top_legal_ir_view_gaps: Optional[Mapping[str, Any]] = None,
    top_surface_features: Mapping[str, Any],
    limit: int = 8,
) -> Dict[str, float]:
    """Infer deterministic repair routes when guidance has features but no route."""
    route_counts: Counter[str] = Counter()
    for route, count in _compiler_guidance_legal_ir_view_gap_todo_routes(
        top_legal_ir_view_gaps or {},
        limit=limit,
    ).items():
        route_counts[str(route)] += float(count)

    surface_total = sum(
        float(value)
        for value in top_surface_features.values()
        if isinstance(value, (float, int)) and float(value) > 0.0
    )
    if surface_total > 0.0:
        route_counts["refine_semantic_decompiler_reconstruction"] += surface_total

    feature_group_counts = {
        str(key): float(value)
        for key, value in top_feature_groups.items()
        if isinstance(value, (float, int)) and float(value) > 0.0
    }
    logic_view_count = feature_group_counts.get("logic_view_contract", 0.0)
    if logic_view_count > 0.0 and not route_counts:
        route_counts["repair_multiview_legal_ir_loss"] += logic_view_count
    compiler_count = max(
        feature_group_counts.get("compiler_contract", 0.0),
        feature_group_counts.get("compiler_latent_profile", 0.0),
    )
    if compiler_count > 0.0 and not route_counts:
        route_counts["refine_modal_family_cue_rules"] += compiler_count
    return _top_numeric_items(route_counts, limit=limit)


def _compiler_guidance_legal_ir_view_gap_todo_routes(
    top_legal_ir_view_gaps: Mapping[str, Any],
    *,
    limit: int = 8,
) -> Dict[str, float]:
    """Route signed learned LegalIR view gaps to concrete compiler scopes."""
    route_counts: Counter[str] = Counter()
    for raw_gap, raw_count in _top_numeric_items(
        top_legal_ir_view_gaps,
        limit=32,
    ).items():
        gap = str(raw_gap or "").strip()
        if not gap:
            continue
        view, _, direction = gap.partition(":")
        route = _compiler_guidance_route_for_legal_ir_view_gap(
            view,
            direction=direction,
        )
        if route:
            route_counts[route] += float(raw_count)
    return _top_numeric_items(route_counts, limit=limit)


def _compiler_guidance_route_for_legal_ir_view_gap(
    view: str,
    *,
    direction: str = "",
) -> str:
    normalized_view = _normalized_guidance_route(view)
    normalized_direction = _normalized_guidance_route(direction)
    if not normalized_view:
        return ""
    if "deontic" in normalized_view or "norm" in normalized_view:
        return "repair_deontic_bridge_quality_gate"
    if "tdfol" in normalized_view or "fol" in normalized_view:
        return "repair_tdfol_bridge_parse"
    if "cec" in normalized_view or "dcec" in normalized_view:
        return "repair_cec_dcec_bridge"
    if "zkp" in normalized_view or "circuit" in normalized_view:
        return "repair_zkp_attestation_bridge"
    if "external" in normalized_view or "prover" in normalized_view:
        return "repair_multiview_legal_ir_prover_gate"
    if (
        "knowledge_graph" in normalized_view
        or "neo4j" in normalized_view
        or normalized_view.endswith("_kg")
    ):
        return "repair_multiview_legal_ir_graph_projection"
    if "frame_logic" in normalized_view or "flogic" in normalized_view:
        return "repair_flogic_ontology_constraints"
    if normalized_direction == "underrepresented":
        return "repair_multiview_legal_ir_view_coverage"
    return "repair_multiview_legal_ir_loss"


def compiler_guidance_route_scope(route: str) -> Dict[str, Any]:
    """Map a learned guidance TODO route into a merge-safe Codex AST scope."""
    normalized = _normalized_guidance_route(route)
    normalized_targets = {
        _normalized_guidance_route(action): target
        for action, target in PROGRAM_SYNTHESIS_ACTION_TARGETS.items()
    }
    target_component = (
        normalized_targets.get(normalized)
        or GUIDANCE_ROUTE_TARGET_OVERRIDES.get(normalized)
    )
    matched_by = "action_target" if normalized in normalized_targets else "override"
    if not target_component:
        matched_by = "prefix"
        for prefix, component in GUIDANCE_ROUTE_PREFIX_TARGETS:
            if normalized.startswith(prefix):
                target_component = component
                break
    if not target_component:
        matched_by = "fallback"
        target_component = normalized or "modal.compiler"
    scope = logic_optimizer_scope_for_component(
        target_component,
        action=normalized,
    )
    return {
        "matched_by": matched_by,
        "route": normalized,
        "scope": scope,
        "target_component": target_component,
    }


def compiler_guidance_scope_hints(
    guided_block: Mapping[str, Any],
    *,
    max_scopes: int = 8,
) -> Dict[str, Any]:
    """Summarize learned guidance routes as Codex worker rebalance hints."""
    todo_routes = guided_block.get("compiler_guidance_todo_routes")
    if not isinstance(todo_routes, Mapping) or not todo_routes:
        feature_groups = guided_block.get("compiler_guidance_feature_groups")
        surface_features = guided_block.get("compiler_guidance_surface_features")
        legal_ir_view_gaps = guided_block.get("compiler_guidance_legal_ir_view_gaps")
        todo_routes = _compiler_guidance_fallback_todo_routes(
            top_feature_groups=_top_numeric_items(
                feature_groups if isinstance(feature_groups, Mapping) else {},
                limit=max_scopes,
            ),
            top_legal_ir_view_gaps=_top_numeric_items(
                legal_ir_view_gaps if isinstance(legal_ir_view_gaps, Mapping) else {},
                limit=max_scopes,
            ),
            top_surface_features=_top_numeric_items(
                surface_features if isinstance(surface_features, Mapping) else {},
                limit=max_scopes,
            ),
            limit=max_scopes,
        )
    if not isinstance(todo_routes, Mapping) or not todo_routes:
        return {
            "recommended_parallel_scopes": [],
            "route_scope_map": {},
            "scope_counts": {},
            "scope_weights": {},
            "target_component_counts": {},
        }

    scope_counts: Counter[str] = Counter()
    target_component_counts: Counter[str] = Counter()
    route_scope_map: Dict[str, Dict[str, Any]] = {}
    for route, count in _top_numeric_items(todo_routes, limit=32).items():
        route_scope = compiler_guidance_route_scope(route)
        scope = str(route_scope["scope"])
        target_component = str(route_scope["target_component"])
        weight = float(count)
        scope_counts[scope] += weight
        target_component_counts[target_component] += weight
        route_scope_map[str(route)] = route_scope

    limited_scope_counts = dict(scope_counts.most_common(max(0, int(max_scopes))))
    total = sum(float(value) for value in limited_scope_counts.values())
    scope_weights = {
        scope: round(float(value) / total, 6)
        for scope, value in limited_scope_counts.items()
        if total > 0.0
    }
    return {
        "recommended_parallel_scopes": list(limited_scope_counts),
        "route_scope_map": route_scope_map,
        "scope_counts": {
            scope: (int(value) if float(value).is_integer() else round(float(value), 9))
            for scope, value in limited_scope_counts.items()
        },
        "scope_weights": scope_weights,
        "target_component_counts": {
            component: (
                int(value) if float(value).is_integer() else round(float(value), 9)
            )
            for component, value in target_component_counts.most_common(max(0, int(max_scopes)))
        },
    }


def compiler_guidance_promotion_gate(
    canary_block: Mapping[str, Any],
    *,
    min_applied_count: int = 1,
) -> Dict[str, Any]:
    """Return whether guided compiler IR is safe to promote into deterministic rules."""
    quality_gate = str(canary_block.get("quality_gate") or "inactive")
    applied_count = int(canary_block.get("applied_count", 0) or 0)
    if applied_count < max(1, int(min_applied_count)):
        reason = "insufficient_guidance_samples"
    elif quality_gate == "pass":
        reason = "quality_gate_pass"
    elif quality_gate == "fail":
        reason = "quality_gate_fail"
    elif quality_gate == "warn":
        reason = "quality_gate_warn"
    else:
        reason = "guidance_inactive"
    promotion_allowed = reason == "quality_gate_pass"
    return {
        "applied_count": applied_count,
        "promotion_allowed": promotion_allowed,
        "promotion_block_reason": "" if promotion_allowed else reason,
        "quality_gate": quality_gate,
        "recommended_mode": (
            "promote_deterministic_rules" if promotion_allowed else "canary_only"
        ),
    }


def compiler_guidance_distillation_candidates(
    guided_block: Mapping[str, Any],
    canary_block: Mapping[str, Any],
    *,
    max_items: int = 8,
) -> Dict[str, Any]:
    """Build the reviewable learned-to-deterministic compiler distillation block."""
    feature_groups = guided_block.get("compiler_guidance_feature_groups")
    surface_features = guided_block.get("compiler_guidance_surface_features")
    legal_ir_view_gaps = guided_block.get("compiler_guidance_legal_ir_view_gaps")
    semantic_overlay_terms = guided_block.get(
        "compiler_guidance_semantic_overlay_terms"
    )
    todo_routes = guided_block.get("compiler_guidance_todo_routes")
    todo_route_examples = guided_block.get("compiler_guidance_todo_route_examples")
    top_feature_groups = _top_numeric_items(
        feature_groups if isinstance(feature_groups, Mapping) else {},
        limit=max_items,
    )
    top_surface_features = _top_numeric_items(
        surface_features if isinstance(surface_features, Mapping) else {},
        limit=max_items,
    )
    top_legal_ir_view_gaps = _top_numeric_items(
        legal_ir_view_gaps if isinstance(legal_ir_view_gaps, Mapping) else {},
        limit=max_items,
    )
    top_todo_routes = _top_numeric_items(
        todo_routes if isinstance(todo_routes, Mapping) else {},
        limit=max_items,
    )
    top_semantic_overlay_terms = _top_numeric_items(
        semantic_overlay_terms if isinstance(semantic_overlay_terms, Mapping) else {},
        limit=max_items,
    )
    todo_routes_inferred_from_features = False
    todo_routes_augmented_from_features = False
    fallback_todo_routes = _compiler_guidance_fallback_todo_routes(
        top_feature_groups=top_feature_groups,
        top_legal_ir_view_gaps=top_legal_ir_view_gaps,
        top_surface_features=top_surface_features,
        limit=max_items,
    )
    if not top_todo_routes:
        top_todo_routes = fallback_todo_routes
        todo_routes_inferred_from_features = bool(top_todo_routes)
    elif fallback_todo_routes:
        merged_routes = Counter(
            {str(route): float(count) for route, count in top_todo_routes.items()}
        )
        for route, count in fallback_todo_routes.items():
            before = float(merged_routes.get(str(route), 0.0))
            merged_routes[str(route)] = max(before, float(count))
            if before <= 0.0:
                todo_routes_augmented_from_features = True
        top_todo_routes = _top_numeric_items(merged_routes, limit=max_items)
    top_todo_route_examples: Dict[str, Any] = {}
    if isinstance(todo_route_examples, Mapping):
        for route in top_todo_routes:
            examples = todo_route_examples.get(route)
            if isinstance(examples, Sequence) and not isinstance(
                examples,
                (str, bytes),
            ):
                top_todo_route_examples[route] = list(examples[:3])
    scope_hints = compiler_guidance_scope_hints(
        {
            **dict(guided_block),
            "compiler_guidance_todo_routes": top_todo_routes,
        },
        max_scopes=max_items,
    )
    guidance_attribution = (
        dict(canary_block.get("attribution"))
        if isinstance(canary_block.get("attribution"), Mapping)
        else {}
    )
    guidance_attribution_summary = _guidance_attribution_summary(
        guidance_attribution
    )
    promotion_gate = compiler_guidance_promotion_gate(canary_block)
    has_candidates = bool(
        top_feature_groups
        or top_legal_ir_view_gaps
        or top_semantic_overlay_terms
        or top_surface_features
        or top_todo_routes
        or scope_hints.get("scope_counts")
    )
    return {
        "has_candidates": has_candidates,
        "promotion_allowed": promotion_gate["promotion_allowed"],
        "promotion_block_reason": promotion_gate["promotion_block_reason"],
        "quality_gate": promotion_gate["quality_gate"],
        "recommended_mode": promotion_gate["recommended_mode"],
        "guidance_attribution": guidance_attribution,
        "guidance_attribution_summary": guidance_attribution_summary,
        "scope_hints": scope_hints,
        "top_semantic_overlay_terms": top_semantic_overlay_terms,
        "top_feature_groups": top_feature_groups,
        "top_legal_ir_view_gaps": top_legal_ir_view_gaps,
        "top_surface_features": top_surface_features,
        "top_todo_route_examples": top_todo_route_examples,
        "top_todo_routes": top_todo_routes,
        "todo_routes_augmented_from_features": todo_routes_augmented_from_features,
        "todo_routes_inferred_from_features": todo_routes_inferred_from_features,
    }


GUIDANCE_SCOPE_TARGET_METRICS = {
    "bridge": (
        "legal_ir_view_cross_entropy_loss",
        "legal_ir_multiview_total_loss",
    ),
    "cec": (
        "cec_dcec_validation_failure_ratio",
        "legal_ir_view_cross_entropy_loss",
    ),
    "compiler_ambiguity": ("cross_entropy_loss", "cosine_similarity"),
    "compiler_parser": (
        "modal_span_coverage_loss",
        "symbolic_validity_penalty",
    ),
    "compiler_registry": ("cross_entropy_loss", "cosine_similarity"),
    "deontic": (
        "deontic_decoder_slot_loss",
        "legal_ir_view_cross_entropy_loss",
    ),
    "external_provers": ("legal_ir_multiview_proof_failure_ratio",),
    "frame_logic": ("flogic_similarity_loss", "ontology_violation_count"),
    "ir_decompiler": (
        "cosine_similarity",
        "source_decompiled_text_embedding_cosine_loss",
        "source_decompiled_text_token_loss",
        "source_copy_reward_hack_penalty",
        "structural_text_reconstruction_loss",
        "text_reconstruction_loss",
    ),
    "knowledge_graphs": ("legal_ir_multiview_graph_failure_penalty",),
    "tdfol": ("tdfol_parse_failure_ratio", "legal_ir_view_cross_entropy_loss"),
    "zkp": ("zkp_verification_failure_ratio", "legal_ir_view_cross_entropy_loss"),
}

GUIDANCE_SCOPE_VALIDATION_TESTS = {
    "bridge": (
        "tests/unit/logic/test_logic_bridge_layer.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ),
    "cec": ("tests/unit/logic/test_logic_bridge_layer.py",),
    "compiler_ambiguity": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "compiler_parser": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "compiler_registry": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "deontic": (
        "tests/unit/logic/test_deontic_graph.py",
        "tests/unit/logic/test_deontic_knowledge_base.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "external_provers": (
        "tests/unit/logic/test_logic_bridge_layer.py",
        "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
    ),
    "frame_logic": (
        "ipfs_datasets_py/logic/test_flogic_optimizer.py",
        "tests/unit/logic/test_flogic_integration.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "ir_decompiler": (
        "tests/unit/optimizers/logic_theorem_optimizer/test_spacy_modal_codec.py",
        "tests/unit_tests/logic/modal/test_modal_codec.py",
    ),
    "knowledge_graphs": ("tests/unit/logic/test_logic_bridge_layer.py",),
    "tdfol": (
        "tests/unit/logic/TDFOL/test_formula_dependency_graph.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
    "zkp": (
        "tests/unit/logic/test_flogic_cache_zkp.py",
        "tests/unit/logic/test_logic_bridge_layer.py",
    ),
}


def _compiler_guidance_target_metrics(route: str, scope: str) -> List[str]:
    metrics = [
        "cross_entropy_loss",
        "cosine_similarity",
        "source_decompiled_text_embedding_cosine_loss",
        "source_copy_reward_hack_penalty",
    ]
    metrics.extend(GUIDANCE_SCOPE_TARGET_METRICS.get(str(scope), ()))
    if "decompiler" in route:
        metrics.extend(
            (
                "source_decompiled_text_embedding_cosine_loss",
                "source_decompiled_text_token_loss",
                "structural_text_reconstruction_loss",
                "text_reconstruction_loss",
            )
        )
    if "multiview" in route or "legal_ir" in route:
        metrics.append("legal_ir_view_cross_entropy_loss")
    return list(dict.fromkeys(str(metric) for metric in metrics if str(metric)))


def _compiler_guidance_validation_commands(scope: str) -> List[str]:
    tests = list(
        GUIDANCE_SCOPE_VALIDATION_TESTS.get(
            str(scope),
            (
                "tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py",
            ),
        )
    )
    tests = list(dict.fromkeys(str(test) for test in tests if str(test)))
    return [f"{sys.executable} -m pytest -q {' '.join(tests)}"] if tests else []


def _compiler_guidance_distillation_todo_id(
    *,
    route: str,
    target_component: str,
    sample_ids: Sequence[str],
) -> str:
    payload = {
        "route": route,
        "sample_ids": sorted(str(sample_id) for sample_id in sample_ids),
        "source": "compiler_guidance_distillation_v1",
        "target_component": target_component,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"guidance-program-{digest}"


def _compiler_guidance_distillation_signature(
    *,
    route: str,
    target_component: str,
    sample_ids: Sequence[str],
) -> str:
    payload = {
        "route": route,
        "sample_ids": sorted(str(sample_id) for sample_id in sample_ids),
        "source": "compiler_guidance_distillation_v1",
        "target_component": target_component,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _compiler_guidance_example_payloads(
    examples: Any,
    *,
    route: str,
    max_examples: int = 8,
) -> tuple[List[str], List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not isinstance(examples, Sequence) or isinstance(examples, (str, bytes)):
        examples = []
    sample_ids: List[str] = []
    citations: List[str] = []
    evidence: List[Dict[str, Any]] = []
    metric_payloads: List[Dict[str, Any]] = []
    for index, raw_example in enumerate(examples[: max(0, int(max_examples))], start=1):
        if not isinstance(raw_example, Mapping):
            continue
        sample_id = str(raw_example.get("sample_id") or "").strip()
        citation = str(raw_example.get("citation") or "").strip()
        text_preview = str(raw_example.get("text_preview") or "").strip()
        selected_before = str(raw_example.get("selected_frame_before") or "").strip()
        selected_after = str(raw_example.get("selected_frame_after") or "").strip()
        if sample_id:
            sample_ids.append(sample_id)
        if citation:
            citations.append(citation)
        evidence.append(
            {
                "citation": citation,
                "compiler_guidance_route": route,
                "evidence_rank": index,
                "sample_id": sample_id,
                "selected_frame_after": selected_after,
                "selected_frame_before": selected_before,
                "text_preview": text_preview,
            }
        )
        if sample_id or text_preview:
            metric_payloads.append(
                {
                    "citation": citation,
                    "sample_id": sample_id or f"compiler-guidance:{route}:{index}",
                    "text": text_preview,
                }
            )
    return (
        list(dict.fromkeys(sample_ids)),
        list(dict.fromkeys(citations)),
        evidence,
        metric_payloads,
    )


def compiler_guidance_distillation_todos(
    candidates: Mapping[str, Any],
    *,
    policy: Optional[ModalOptimizerPolicy] = None,
    max_routes: int = 8,
) -> List[ModalTodo]:
    """Convert passing guidance distillation candidates into normal Codex TODOs."""
    if not candidates.get("promotion_allowed"):
        return []
    route_counts = candidates.get("top_todo_routes")
    if not isinstance(route_counts, Mapping):
        return []
    route_examples = candidates.get("top_todo_route_examples")
    if not isinstance(route_examples, Mapping):
        route_examples = {}
    scope_hints = candidates.get("scope_hints")
    if not isinstance(scope_hints, Mapping):
        scope_hints = {}
    route_scope_map = scope_hints.get("route_scope_map")
    if not isinstance(route_scope_map, Mapping):
        route_scope_map = {}

    optimizer_policy = policy or ModalOptimizerPolicy()
    todos: List[ModalTodo] = []
    for route, raw_count in _top_numeric_items(route_counts, limit=max_routes).items():
        route_scope = route_scope_map.get(route)
        if not isinstance(route_scope, Mapping):
            route_scope = compiler_guidance_route_scope(route)
        action = _normalized_guidance_route(route)
        target_component = str(route_scope.get("target_component") or "")
        scope = str(route_scope.get("scope") or "")
        examples = route_examples.get(route)
        sample_ids, citations, evidence, metric_payloads = (
            _compiler_guidance_example_payloads(examples, route=action)
        )
        if not sample_ids:
            sample_ids = [f"compiler-guidance:{action}"]
        count = float(raw_count)
        metadata = {
            **optimizer_policy.metadata_for(
                action=action,
                loss_name="compiler_guidance_distillation",
            ),
            "compiler_guidance_distillation_count": count,
            "compiler_guidance_quality_gate": candidates.get("quality_gate", ""),
            "compiler_guidance_route": action,
            "compiler_guidance_attribution": dict(
                candidates.get("guidance_attribution")
                if isinstance(candidates.get("guidance_attribution"), Mapping)
                else {}
            ),
            "compiler_guidance_attribution_summary": dict(
                candidates.get("guidance_attribution_summary")
                if isinstance(candidates.get("guidance_attribution_summary"), Mapping)
                else {}
            ),
            "compiler_guidance_legal_ir_view_gaps": dict(
                candidates.get("top_legal_ir_view_gaps")
                if isinstance(candidates.get("top_legal_ir_view_gaps"), Mapping)
                else {}
            ),
            "compiler_guidance_surface_features": dict(
                candidates.get("top_surface_features")
                if isinstance(candidates.get("top_surface_features"), Mapping)
                else {}
            ),
            "compiler_guidance_semantic_overlay_terms": dict(
                candidates.get("top_semantic_overlay_terms")
                if isinstance(candidates.get("top_semantic_overlay_terms"), Mapping)
                else {}
            ),
            "compiler_guidance_todo_routes_augmented_from_features": bool(
                candidates.get("todo_routes_augmented_from_features")
            ),
            "compiler_guidance_todo_routes_inferred_from_features": bool(
                candidates.get("todo_routes_inferred_from_features")
            ),
            "dedupe_signature": _compiler_guidance_distillation_signature(
                route=action,
                target_component=target_component,
                sample_ids=sample_ids,
            ),
            "hint_evidence": evidence,
            "metric_sample_payloads": metric_payloads,
            "program_synthesis_scope": scope,
            "semantic_bundle_key": json.dumps(
                {
                    "program_synthesis_scope": scope,
                    "route": action,
                    "source": "compiler_guidance_distillation_v1",
                    "target_component": target_component,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "source": "compiler_guidance_distillation_v1",
            "support_count": len(sample_ids),
            "target_component": target_component,
            "target_metrics": _compiler_guidance_target_metrics(action, scope),
            "validation_commands": _compiler_guidance_validation_commands(scope),
        }
        todos.append(
            ModalTodo(
                todo_id=_compiler_guidance_distillation_todo_id(
                    route=action,
                    target_component=target_component,
                    sample_ids=sample_ids,
                ),
                action=action,
                objective=(
                    "Promote passing autoencoder compiler-guidance evidence into "
                    f"deterministic {target_component or scope or 'compiler'} rules."
                ),
                sample_ids=sample_ids,
                citations=citations,
                loss_name="compiler_guidance_distillation",
                loss_value=round(count, 9),
                priority=round(250.0 + (25.0 * count), 6),
                metadata=metadata,
            )
        )
    return todos


def _compiler_guidance_activation_todo_id(
    *,
    route: str,
    target_component: str,
    sample_ids: Sequence[str],
) -> str:
    payload = {
        "route": route,
        "sample_ids": sorted(str(sample_id) for sample_id in sample_ids),
        "source": "compiler_guidance_activation_v1",
        "target_component": target_component,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"guidance-activation-{digest}"


def _compiler_guidance_activation_signature(
    *,
    route: str,
    target_component: str,
    sample_ids: Sequence[str],
) -> str:
    payload = {
        "route": route,
        "sample_ids": sorted(str(sample_id) for sample_id in sample_ids),
        "source": "compiler_guidance_activation_v1",
        "target_component": target_component,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def compiler_guidance_activation_todos(
    candidates: Mapping[str, Any],
    canary_block: Mapping[str, Any],
    *,
    policy: Optional[ModalOptimizerPolicy] = None,
    max_routes: int = 4,
) -> List[ModalTodo]:
    """Seed TODOs when learned guidance exists but has no compiler effect yet."""
    if str(canary_block.get("quality_gate") or "") != "warn":
        return []
    if int(canary_block.get("applied_count", 0) or 0) <= 0:
        return []
    if not candidates.get("has_candidates"):
        return []
    route_counts = candidates.get("top_todo_routes")
    if not isinstance(route_counts, Mapping):
        return []
    route_examples = candidates.get("top_todo_route_examples")
    if not isinstance(route_examples, Mapping):
        route_examples = {}
    scope_hints = candidates.get("scope_hints")
    if not isinstance(scope_hints, Mapping):
        scope_hints = {}
    route_scope_map = scope_hints.get("route_scope_map")
    if not isinstance(route_scope_map, Mapping):
        route_scope_map = {}

    optimizer_policy = policy or ModalOptimizerPolicy()
    todos: List[ModalTodo] = []
    for route, raw_count in _top_numeric_items(route_counts, limit=max_routes).items():
        route_scope = route_scope_map.get(route)
        if not isinstance(route_scope, Mapping):
            route_scope = compiler_guidance_route_scope(route)
        action = _normalized_guidance_route(route)
        target_component = str(route_scope.get("target_component") or "")
        scope = str(route_scope.get("scope") or "")
        sample_ids, citations, evidence, metric_payloads = (
            _compiler_guidance_example_payloads(
                route_examples.get(route),
                route=action,
            )
        )
        if not sample_ids:
            sample_ids = [f"compiler-guidance-activation:{action}"]
        count = float(raw_count)
        metadata = {
            **optimizer_policy.metadata_for(
                action=action,
                loss_name="compiler_guidance_activation",
            ),
            "compiler_guidance_activation_count": count,
            "compiler_guidance_activation_reason": (
                "guidance_applied_without_metric_movement"
            ),
            "compiler_guidance_canary": dict(canary_block),
            "compiler_guidance_quality_gate": canary_block.get("quality_gate", ""),
            "compiler_guidance_route": action,
            "compiler_guidance_attribution": dict(
                candidates.get("guidance_attribution")
                if isinstance(candidates.get("guidance_attribution"), Mapping)
                else {}
            ),
            "compiler_guidance_attribution_summary": dict(
                candidates.get("guidance_attribution_summary")
                if isinstance(candidates.get("guidance_attribution_summary"), Mapping)
                else {}
            ),
            "compiler_guidance_legal_ir_view_gaps": dict(
                candidates.get("top_legal_ir_view_gaps")
                if isinstance(candidates.get("top_legal_ir_view_gaps"), Mapping)
                else {}
            ),
            "compiler_guidance_surface_features": dict(
                candidates.get("top_surface_features")
                if isinstance(candidates.get("top_surface_features"), Mapping)
                else {}
            ),
            "compiler_guidance_semantic_overlay_terms": dict(
                candidates.get("top_semantic_overlay_terms")
                if isinstance(candidates.get("top_semantic_overlay_terms"), Mapping)
                else {}
            ),
            "compiler_guidance_todo_routes_augmented_from_features": bool(
                candidates.get("todo_routes_augmented_from_features")
            ),
            "compiler_guidance_todo_routes_inferred_from_features": bool(
                candidates.get("todo_routes_inferred_from_features")
            ),
            "dedupe_signature": _compiler_guidance_activation_signature(
                route=action,
                target_component=target_component,
                sample_ids=sample_ids,
            ),
            "hint_evidence": evidence,
            "metric_sample_payloads": metric_payloads,
            "program_synthesis_scope": scope,
            "semantic_bundle_key": json.dumps(
                {
                    "program_synthesis_scope": scope,
                    "route": action,
                    "source": "compiler_guidance_activation_v1",
                    "target_component": target_component,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "source": "compiler_guidance_activation_v1",
            "support_count": len(sample_ids),
            "target_component": target_component,
            "target_metrics": _compiler_guidance_target_metrics(action, scope),
            "validation_commands": _compiler_guidance_validation_commands(scope),
        }
        todos.append(
            ModalTodo(
                todo_id=_compiler_guidance_activation_todo_id(
                    route=action,
                    target_component=target_component,
                    sample_ids=sample_ids,
                ),
                action=action,
                objective=(
                    "Wire autoencoder compiler-guidance evidence into deterministic "
                    f"{target_component or scope or 'compiler'} behavior so canary "
                    "IR metrics move without relying on diagnostic-only slots."
                ),
                sample_ids=sample_ids,
                citations=citations,
                loss_name="compiler_guidance_activation",
                loss_value=round(count, 9),
                priority=round(175.0 + (15.0 * count), 6),
                metadata=metadata,
            )
        )
    return todos


def _compiler_guidance_guardrail_todo_id(
    *,
    action: str,
    guardrail_reason: str,
    sample_ids: Sequence[str],
    canary_block: Mapping[str, Any],
) -> str:
    payload = {
        "action": action,
        "copy_hack_delta": canary_block.get("copy_hack_delta"),
        "cosine_delta": canary_block.get("cosine_delta"),
        "guardrail_reason": guardrail_reason,
        "sample_ids": sorted(str(sample_id) for sample_id in sample_ids),
        "source": "compiler_guidance_guardrail_v1",
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"guidance-guardrail-{digest}"


def compiler_guidance_guardrail_todos(
    candidates: Mapping[str, Any],
    canary_block: Mapping[str, Any],
    *,
    policy: Optional[ModalOptimizerPolicy] = None,
) -> List[ModalTodo]:
    """Seed guardrail repairs when learned guidance helps one metric but reward-hacks."""
    if str(canary_block.get("quality_gate") or "") != "fail":
        return []
    copy_hack_delta = _metric_value(canary_block, "copy_hack_delta", 0.0)
    cosine_delta = _metric_value(canary_block, "cosine_delta", 0.0)
    ce_delta = _metric_value(canary_block, "ce_delta", 0.0)
    core_deltas = {
        "ce_delta": ce_delta,
        "copy_hack_delta": copy_hack_delta,
        "cosine_delta": cosine_delta,
    }
    if not any(value > 0.0 for value in core_deltas.values()) or not any(
        value < 0.0 for value in core_deltas.values()
    ):
        return []
    if copy_hack_delta < 0.0:
        action = "refine_semantic_decompiler_reconstruction"
        guardrail_reason = "copy_hack_regression_with_useful_guidance"
        target_component = "modal.ir_decompiler"
        scope = "ir_decompiler"
        target_metrics = [
            "source_copy_reward_hack_penalty",
            "source_copy_loss",
            "structural_text_reconstruction_loss",
            "text_reconstruction_loss",
            "cosine_similarity",
        ]
        objective = (
            "Keep the useful autoencoder compiler-guidance signal while reducing "
            "source-copy reward hacking in the IR decompiler."
        )
        loss_value = abs(float(copy_hack_delta))
    elif cosine_delta < 0.0:
        action = "refine_typed_ir_or_decompiler_slots"
        guardrail_reason = "cosine_regression_with_useful_guidance"
        target_component = "modal.ir_decompiler"
        scope = "ir_decompiler"
        target_metrics = [
            "cosine_similarity",
            "reconstruction_loss",
            "source_copy_reward_hack_penalty",
            "structural_text_reconstruction_loss",
        ]
        objective = (
            "Keep useful autoencoder compiler-guidance improvements while preserving "
            "IR cosine similarity and typed decompiler slot alignment."
        )
        loss_value = abs(float(cosine_delta))
    elif ce_delta < 0.0:
        action = "refine_modal_family_cue_rules"
        guardrail_reason = "cross_entropy_regression_with_useful_guidance"
        target_component = "modal.compiler.registry"
        scope = "compiler_registry"
        target_metrics = [
            "cross_entropy_loss",
            "cosine_similarity",
            "source_copy_reward_hack_penalty",
        ]
        objective = (
            "Keep useful autoencoder compiler-guidance improvements while preventing "
            "modal-family cross-entropy regressions."
        )
        loss_value = abs(float(ce_delta))
    else:
        return []
    route_examples = candidates.get("top_todo_route_examples")
    if not isinstance(route_examples, Mapping):
        route_examples = {}
    route_counts = candidates.get("top_todo_routes")
    if not isinstance(route_counts, Mapping):
        route_counts = {}
    sample_ids: List[str] = []
    citations: List[str] = []
    evidence: List[Dict[str, Any]] = []
    metric_payloads: List[Dict[str, Any]] = []
    for route in _top_numeric_items(route_counts, limit=8):
        route_samples, route_citations, route_evidence, route_payloads = (
            _compiler_guidance_example_payloads(
                route_examples.get(route),
                route=_normalized_guidance_route(route),
                max_examples=3,
            )
        )
        sample_ids.extend(route_samples)
        citations.extend(route_citations)
        evidence.extend(route_evidence)
        metric_payloads.extend(route_payloads)
    sample_ids = list(dict.fromkeys(sample_ids)) or ["compiler-guidance:guardrail"]
    citations = list(dict.fromkeys(citations))
    optimizer_policy = policy or ModalOptimizerPolicy()
    metadata = {
        **optimizer_policy.metadata_for(
            action=action,
            loss_name="compiler_guidance_guardrail",
        ),
        "compiler_guidance_canary": dict(canary_block),
        "compiler_guidance_guardrail_reason": guardrail_reason,
        "compiler_guidance_quality_gate": canary_block.get("quality_gate", ""),
        "dedupe_signature": json.dumps(
            {
                "sample_ids": sorted(sample_ids),
                "source": "compiler_guidance_guardrail_v1",
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "hint_evidence": evidence,
        "metric_sample_payloads": metric_payloads,
        "program_synthesis_scope": scope,
        "semantic_bundle_key": json.dumps(
            {
                "program_synthesis_scope": scope,
                "source": "compiler_guidance_guardrail_v1",
                "target_component": target_component,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "source": "compiler_guidance_guardrail_v1",
        "support_count": len(sample_ids),
        "target_component": target_component,
        "target_metrics": target_metrics,
        "validation_commands": _compiler_guidance_validation_commands(scope),
    }
    return [
        ModalTodo(
            todo_id=_compiler_guidance_guardrail_todo_id(
                action=action,
                guardrail_reason=guardrail_reason,
                sample_ids=sample_ids,
                canary_block=canary_block,
            ),
            action=action,
            objective=objective,
            sample_ids=sample_ids,
            citations=citations,
            loss_name="compiler_guidance_guardrail",
            loss_value=loss_value,
            priority=round(150.0 + (float(loss_value) * 100.0), 6),
            metadata=metadata,
        )
    ]


def compiler_guidance_distillation_path(summary_path: Path) -> Path:
    return summary_path.with_name(f"{summary_path.stem}.compiler-guidance-distillation.json")


def save_compiler_guidance_distillation(
    summary_path: Path,
    candidates: Mapping[str, Any],
) -> Optional[Path]:
    if not candidates.get("has_candidates"):
        return None
    artifact_path = compiler_guidance_distillation_path(summary_path)
    artifact_path.write_text(
        json.dumps(dict(candidates), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_path


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
    progress_callback: Optional[Callable[[Mapping[str, Any]], None]] = None,
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

    started_at = time.time()

    def emit_progress(stage: str, **payload: Any) -> None:
        if progress_callback is None:
            return
        event = {
            "adapter_count": len(adapter_names),
            "adapters": list(adapter_names),
            "block": "bridge_ir",
            "elapsed_seconds": round(time.time() - started_at, 3),
            "sample_count": len(sample_list),
            "stage": stage,
        }
        event.update(payload)
        try:
            progress_callback(event)
        except Exception:
            pass

    worker_count = _parallel_worker_count(
        requested=parallel_workers,
        item_count=len(sample_list),
    )
    block["worker_count"] = worker_count
    persistent_cache_key = _bridge_ir_metric_block_cache_key(
        sample_list,
        bridge_names=adapter_names,
        evaluate_provers=evaluate_provers,
    )
    zkp_adapter_present = "zkp_attestation" in set(adapter_names)
    emit_progress(
        "start",
        evaluate_provers=evaluate_provers,
        worker_count=worker_count,
    )
    cached_block = _read_metric_disk_cache(
        "bridge_ir_metric_block",
        persistent_cache_key,
    )
    if cached_block is not None:
        cached = dict(cached_block)
        cached["persistent_cache_enabled"] = True
        cached["persistent_cache_hit"] = True
        cached["persistent_cache_key"] = persistent_cache_key
        cached["persistent_cache_kind"] = "bridge_ir_metric_block"
        cached["worker_count"] = worker_count
        if zkp_adapter_present:
            cached["zkp_attestation_cache"] = {
                "adapter_present": True,
                "cache_key": persistent_cache_key,
                "mode": "persistent_metric_certificate",
                "persistent_cache_hit": True,
            }
        emit_progress(
            "persistent_cache_hit",
            cache_key=persistent_cache_key,
            evaluated_count=cached.get("evaluated_count", 0),
            metric_failures=cached.get("metric_failures", 0),
        )
        return cached
    emit_progress("persistent_cache_miss", cache_key=persistent_cache_key)

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
    cache_hits = 0
    cache_misses = 0
    persistent_sample_cache_hits = 0
    persistent_sample_cache_misses = 0
    legal_ir_target_cache_exports = 0
    legal_ir_target_cache_export_misses = 0
    completed_samples = 0
    evaluation_seconds: List[float] = []
    cache_stats_lock = threading.Lock()

    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    def record_legal_ir_target_cache_export(sample: Any, report: Any) -> bool:
        nonlocal legal_ir_target_cache_exports, legal_ir_target_cache_export_misses
        exported = _export_bridge_report_to_legal_ir_target_cache(
            sample,
            report,
            bridge_names=adapter_names,
            evaluate_provers=evaluate_provers,
        )
        with cache_stats_lock:
            if exported:
                legal_ir_target_cache_exports += 1
            else:
                legal_ir_target_cache_export_misses += 1
        return exported

    def evaluate_sample(sample: Any) -> Any:
        nonlocal cache_hits, cache_misses, completed_samples
        nonlocal persistent_sample_cache_hits, persistent_sample_cache_misses
        started = time.time()
        sample_id = str(getattr(sample, "sample_id", "") or "")
        citation = str(getattr(sample, "citation", "") or "")
        emit_progress(
            "sample_start",
            citation=citation,
            sample_id=sample_id,
        )
        cache_key = _bridge_ir_report_cache_key(
            sample,
            bridge_names=adapter_names,
            evaluate_provers=evaluate_provers,
        )
        with _BRIDGE_IR_REPORT_CACHE_LOCK:
            cached = _BRIDGE_IR_REPORT_CACHE.get(cache_key)
        if cached is not None:
            with cache_stats_lock:
                cache_hits += 1
                evaluation_seconds.append(time.time() - started)
                completed_samples += 1
                completed = completed_samples
                hits = cache_hits
                misses = cache_misses
            emit_progress(
                "sample_cache_hit",
                cache_hits=hits,
                cache_misses=misses,
                citation=citation,
                completed_samples=completed,
                sample_id=sample_id,
                sample_seconds=round(time.time() - started, 3),
            )
            return cached
        disk_cache_key = _bridge_ir_multiview_report_cache_key(
            sample,
            bridge_names=adapter_names,
            evaluate_provers=evaluate_provers,
        )
        cached_report = _read_metric_disk_cache(
            "bridge_ir_multiview_report",
            disk_cache_key,
        )
        if cached_report is not None:
            exported_target = record_legal_ir_target_cache_export(sample, cached_report)
            with _BRIDGE_IR_REPORT_CACHE_LOCK:
                if len(_BRIDGE_IR_REPORT_CACHE) >= BRIDGE_IR_REPORT_CACHE_MAX:
                    _BRIDGE_IR_REPORT_CACHE.pop(next(iter(_BRIDGE_IR_REPORT_CACHE)), None)
                _BRIDGE_IR_REPORT_CACHE[cache_key] = cached_report
            with cache_stats_lock:
                cache_hits += 1
                persistent_sample_cache_hits += 1
                evaluation_seconds.append(time.time() - started)
                completed_samples += 1
                completed = completed_samples
                hits = cache_hits
                misses = cache_misses
                persistent_hits = persistent_sample_cache_hits
                target_exports = legal_ir_target_cache_exports
            emit_progress(
                "sample_persistent_cache_hit",
                cache_hits=hits,
                cache_misses=misses,
                citation=citation,
                completed_samples=completed,
                legal_ir_target_cache_exported=exported_target,
                legal_ir_target_cache_exports=target_exports,
                persistent_sample_cache_hits=persistent_hits,
                sample_id=sample_id,
                sample_seconds=round(time.time() - started, 3),
            )
            return cached_report
        with cache_stats_lock:
            cache_misses += 1
            persistent_sample_cache_misses += 1
            hits = cache_hits
            misses = cache_misses
            persistent_misses = persistent_sample_cache_misses
        emit_progress(
            "sample_cache_miss",
            cache_hits=hits,
            cache_misses=misses,
            citation=citation,
            persistent_sample_cache_misses=persistent_misses,
            sample_id=sample_id,
        )
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
        if hasattr(report, "to_dict"):
            _write_metric_disk_cache(
                "bridge_ir_multiview_report",
                disk_cache_key,
                report.to_dict(),
            )
        exported_target = record_legal_ir_target_cache_export(sample, report)
        with cache_stats_lock:
            evaluation_seconds.append(time.time() - started)
            completed_samples += 1
            completed = completed_samples
            hits = cache_hits
            misses = cache_misses
            target_exports = legal_ir_target_cache_exports
        emit_progress(
            "sample_done",
            cache_hits=hits,
            cache_misses=misses,
            citation=citation,
            completed_samples=completed,
            legal_ir_target_cache_exported=exported_target,
            legal_ir_target_cache_exports=target_exports,
            report_failures=len(getattr(report, "failures", {}) or {}),
            report_view_count=float(getattr(report, "view_count", 0.0) or 0.0),
            sample_id=sample_id,
            sample_seconds=round(time.time() - started, 3),
        )
        return report

    if worker_count <= 1:
        multiview_reports = [evaluate_sample(sample) for sample in sample_list]
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="bridge-ir-metrics",
        ) as executor:
            multiview_reports = list(executor.map(evaluate_sample, sample_list))
    with _BRIDGE_IR_REPORT_CACHE_LOCK:
        cache_size = len(_BRIDGE_IR_REPORT_CACHE)
    block["cache_hits"] = cache_hits
    block["cache_misses"] = cache_misses
    block["cache_size"] = cache_size
    block["evaluation_seconds_max"] = max(evaluation_seconds) if evaluation_seconds else 0.0
    block["evaluation_seconds_mean"] = _mean(evaluation_seconds)
    block["legal_ir_target_cache_export_misses"] = legal_ir_target_cache_export_misses
    block["legal_ir_target_cache_exports"] = legal_ir_target_cache_exports
    block["persistent_sample_cache_hits"] = persistent_sample_cache_hits
    block["persistent_sample_cache_misses"] = persistent_sample_cache_misses

    for multiview in multiview_reports:
        if isinstance(multiview, Mapping):
            canonical_values["acceptance_rate"].append(
                _float_or_zero(multiview.get("acceptance_rate"))
            )
            canonical_values["graph_failure_penalty"].append(
                _float_or_zero(multiview.get("graph_failure_penalty"))
            )
            canonical_values["proof_failure_ratio"].append(
                _float_or_zero(multiview.get("proof_failure_ratio"))
            )
            canonical_values["total_loss"].append(
                _float_or_zero(multiview.get("total_loss"))
            )
            canonical_values["view_coverage_loss"].append(
                _float_or_zero(multiview.get("view_coverage_loss"))
            )
            canonical_values["view_count"].append(_float_or_zero(multiview.get("view_count")))
            training_target = dict(multiview.get("training_target", {}) or {})
            document_hash = str(
                training_target.get("document_hash")
                or multiview.get("document_hash")
                or ""
            )
            if document_hash:
                canonical_hashes.append(document_hash)
            canonical_loss_map = dict(
                multiview.get("canonical_loss_vector")
                or training_target.get("losses")
                or {}
            )
            for name, value in canonical_loss_map.items():
                canonical_loss_values.setdefault(str(name), []).append(float(value))
            view_distribution = dict(
                training_target.get("view_distribution")
                or multiview.get("view_distribution")
                or {}
            )
            for name, value in view_distribution.items():
                canonical_view_distribution_values.setdefault(str(name), []).append(
                    float(value)
                )
            reports = dict(multiview.get("reports", {}) or {})
            for adapter_name, report in reports.items():
                reports_by_adapter.setdefault(str(adapter_name), []).append(
                    _metric_mapping_to_namespace(report)
                )
            for adapter_name in dict(multiview.get("failures", {}) or {}):
                failures_by_adapter[str(adapter_name)] = (
                    failures_by_adapter.get(str(adapter_name), 0) + 1
                )
            continue
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
    block["persistent_cache_enabled"] = _metric_disk_cache_enabled()
    block["persistent_cache_hit"] = False
    block["persistent_cache_key"] = persistent_cache_key
    block["persistent_cache_kind"] = "bridge_ir_metric_block"
    if zkp_adapter_present:
        block["zkp_attestation_cache"] = {
            "adapter_present": True,
            "cache_key": persistent_cache_key,
            "mode": "persistent_metric_certificate",
            "persistent_cache_hit": False,
        }
    _write_metric_disk_cache(
        "bridge_ir_metric_block",
        persistent_cache_key,
        block,
    )
    emit_progress(
        "done",
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        evaluated_count=block["evaluated_count"],
        metric_failures=block["metric_failures"],
        worker_count=worker_count,
    )
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
        for name, value in _metric_mapping_dict(
            getattr(round_trip, "extra_losses", {})
        ).items():
            metric_values.setdefault(str(name), []).append(_float_or_zero(value))

        ir_document = getattr(report, "ir_document", None)
        views = _metric_mapping_dict(getattr(ir_document, "views", {}))
        for view_name, view in views.items():
            view_counts[str(view_name)] = view_counts.get(str(view_name), 0) + 1
            metadata_bucket = view_metadata_values.setdefault(str(view_name), {})
            for key, value in _metric_mapping_dict(
                getattr(view, "metadata", {})
            ).items():
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


def _compiler_ir_metric_block_cache_key(
    samples: Sequence[Any],
    *,
    codec: Any,
    guidance_cache_records: Sequence[Mapping[str, Any]] = (),
    guidance_top_k: int,
    max_sample_text_chars: int,
    max_sample_metric_records: int,
    metric_text_policy: str,
    sample_timeout_seconds: float,
) -> str:
    payload = {
        "block_cache_version": _COMPILER_IR_METRIC_BLOCK_CACHE_VERSION,
        "codec": {
            "config": _metric_cache_object_payload(getattr(codec, "config", None)),
            "type": f"{codec.__class__.__module__}.{codec.__class__.__qualname__}",
        },
        "guidance_diagnostics_version": _COMPILER_IR_GUIDANCE_DIAGNOSTICS_VERSION,
        "guidance_cache_records": _metric_cache_object_payload(
            list(guidance_cache_records)
        ),
        "guidance_top_k": int(guidance_top_k),
        "max_sample_metric_records": int(max_sample_metric_records),
        "max_sample_text_chars": int(max_sample_text_chars),
        "metric_text_policy": _normalise_compiler_ir_metric_text_policy(
            metric_text_policy
        ),
        "samples": [_sample_metric_cache_payload(sample) for sample in samples],
        "successful_result_timeout_policy": "timeout_agnostic",
    }
    return _metric_disk_cache_key("compiler_ir_metric_block", payload)


def _compiler_ir_metric_sample_cache_key(
    sample: Any,
    *,
    codec: Any,
    compiler_guidance: Optional[Mapping[str, Any]],
    guidance_top_k: int,
) -> str:
    payload = {
        "codec": {
            "config": _metric_cache_object_payload(getattr(codec, "config", None)),
            "type": f"{codec.__class__.__module__}.{codec.__class__.__qualname__}",
        },
        "compiler_guidance": _compiler_ir_metric_guidance_cache_payload(
            compiler_guidance
        ),
        "guidance_top_k": int(guidance_top_k),
        "sample": _sample_metric_cache_payload(sample),
    }
    return _compiler_ir_metric_sample_disk_cache_key(payload)


def _compiler_ir_metric_sample_timeout_cache_key(
    sample: Any,
    *,
    codec: Any,
) -> str:
    payload = {
        "codec": {
            "config": _metric_cache_object_payload(getattr(codec, "config", None)),
            "type": f"{codec.__class__.__module__}.{codec.__class__.__qualname__}",
        },
        "sample": _sample_metric_cache_payload(sample),
    }
    return _compiler_ir_metric_sample_timeout_disk_cache_key(payload)


def _compiler_ir_metric_result_cache_payload(result: Any) -> Dict[str, Any]:
    modal_ir = getattr(result, "modal_ir", None)
    frame_candidates = getattr(result, "frame_candidates", ()) or ()
    payload = {
        "decoded_modal_text": str(getattr(result, "decoded_modal_text", "") or ""),
        "frame_candidate_count": len(frame_candidates),
        "losses": _metric_cache_object_payload(getattr(result, "losses", {}) or {}),
        "metadata": _metric_cache_object_payload(getattr(result, "metadata", {}) or {}),
        "modal_formula_count": len(getattr(modal_ir, "formulas", ()) or ()),
    }
    slot_texts = compiler_guidance_slot_texts_from_result(result)
    if slot_texts:
        payload["compiler_guidance_slot_texts"] = _metric_cache_object_payload(
            slot_texts
        )
    return payload


def _compiler_ir_metric_sample_timeout_cache_payload(
    sample_record: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "cache_entry_type": "sample_timeout",
        "record": _metric_cache_object_payload(sample_record),
        "sample_timeout_cache_policy": _COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY,
        "sample_timeout_seconds": _float_or_zero(
            sample_record.get("sample_timeout_seconds")
        ),
    }


def _compiler_ir_metric_sample_timeout_record_from_cache_payload(
    payload: Optional[Mapping[str, Any]],
    *,
    requested_timeout_seconds: float,
) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return None
    if payload.get("cache_entry_type") != "sample_timeout":
        return None
    if (
        payload.get("sample_timeout_cache_policy")
        != _COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY
    ):
        return None
    requested_timeout = max(0.0, float(requested_timeout_seconds or 0.0))
    cached_timeout = _float_or_zero(payload.get("sample_timeout_seconds"))
    if requested_timeout <= 0.0 or cached_timeout + 1.0e-9 < requested_timeout:
        return None
    record = payload.get("record")
    if not isinstance(record, Mapping):
        return None
    cached = dict(record)
    cached["cached_sample_timeout_seconds"] = cached_timeout
    cached["from_persistent_sample_cache"] = True
    cached["sample_timeout_cache_policy"] = _COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY
    cached["sample_timeout_seconds"] = requested_timeout
    cached["skip_reason"] = "sample_timeout"
    return cached


def _compiler_ir_metric_result_from_cache_payload(
    payload: Optional[Mapping[str, Any]],
) -> Optional[Any]:
    if not isinstance(payload, Mapping):
        return None
    losses = payload.get("losses")
    if not isinstance(losses, Mapping):
        return None
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    guidance_slot_texts: Dict[str, List[str]] = {}
    raw_slot_texts = payload.get("compiler_guidance_slot_texts")
    if isinstance(raw_slot_texts, Mapping):
        guidance_slot_texts = {
            str(slot): _metadata_sequence_strings(values)
            for slot, values in sorted(raw_slot_texts.items())
            if str(slot)
        }
        metadata = dict(metadata)
        metadata["_compiler_guidance_slot_texts"] = guidance_slot_texts
    try:
        formula_count = max(0, int(payload.get("modal_formula_count", 0) or 0))
    except (TypeError, ValueError):
        formula_count = 0
    try:
        frame_candidate_count = max(
            0,
            int(payload.get("frame_candidate_count", 0) or 0),
        )
    except (TypeError, ValueError):
        frame_candidate_count = 0
    return SimpleNamespace(
        decoded_modal_text=str(payload.get("decoded_modal_text") or ""),
        frame_candidates=[None] * frame_candidate_count,
        losses={
            str(name): _float_or_zero(value)
            for name, value in losses.items()
        },
        compiler_guidance_slot_texts=guidance_slot_texts,
        metadata=dict(metadata),
        modal_ir=SimpleNamespace(formulas=[None] * formula_count),
    )


def _bridge_ir_metric_block_cache_key(
    samples: Sequence[Any],
    *,
    bridge_names: Sequence[str],
    evaluate_provers: Optional[bool],
) -> str:
    payload = {
        "bridge_names": list(bridge_names),
        "evaluate_provers": evaluate_provers,
        "samples": [_sample_metric_cache_payload(sample) for sample in samples],
    }
    return _metric_disk_cache_key("bridge_ir_metric_block", payload)


def _bridge_ir_multiview_report_cache_key(
    sample: Any,
    *,
    bridge_names: Sequence[str],
    evaluate_provers: Optional[bool],
) -> str:
    payload = {
        "bridge_names": list(bridge_names),
        "evaluate_provers": evaluate_provers,
        "sample": _sample_metric_cache_payload(sample),
    }
    return _metric_disk_cache_key("bridge_ir_multiview_report", payload)


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


def _codex_claim_stale_seconds(args: argparse.Namespace) -> float:
    configured = float(getattr(args, "codex_claim_stale_seconds", 0.0) or 0.0)
    if configured > 0.0:
        return configured
    codex_timeout = max(0.0, float(getattr(args, "codex_timeout_seconds", 900.0) or 0.0))
    apply_lock_timeout = max(
        0.0,
        float(
            getattr(
                args,
                "codex_main_apply_lock_timeout_seconds",
                CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS,
            )
            or 0.0
        ),
    )
    validation_timeout = max(
        0.0,
        float(
            getattr(
                args,
                "codex_validation_timeout_seconds",
                CODEX_APPLY_VALIDATION_TIMEOUT_SECONDS,
            )
            or 0.0
        ),
    )
    target_metric_timeout = 2.0 * CODEX_TARGET_METRIC_TIMEOUT_SECONDS
    return codex_timeout + apply_lock_timeout + (2.0 * validation_timeout) + target_metric_timeout + 120.0


def requeue_stale_program_synthesis_claims(
    *,
    queue_path: Path,
    policy: ModalOptimizerPolicy,
    max_age_seconds: float,
    reason: str,
    claimed_by: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Requeue abandoned program-synthesis claims under the shared queue lock."""
    with queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
        report = queue.requeue_stale_claims(
            max_age_seconds=max_age_seconds,
            optimizer_role=policy.program_synthesis_role,
            reason=reason,
            claimed_by=claimed_by,
        )
        if int(report.get("requeued_count", 0) or 0) > 0:
            queue.save_jsonl(queue_path)
        report["queue_counts"] = queue.status_counts()
        report["role_queue_counts"] = queue.role_status_counts()
    return report


def seed_failed_validation_rescue_todos_for_queue(
    *,
    queue_path: Path,
    policy: Optional[ModalOptimizerPolicy] = None,
    max_clusters: int = 8,
    rescue_max_attempts: int = FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS,
    program_synthesis_scope: Optional[str] = None,
    failure_reason: Optional[str] = None,
    original_action: Optional[str] = None,
) -> Dict[str, Any]:
    """Seed failed-validation rescue TODOs under the shared queue lock."""

    optimizer_policy = policy or ModalOptimizerPolicy()
    report: Dict[str, Any] = {
        "deduped_count": 0,
        "max_clusters": max(0, int(max_clusters)),
        "rescue_max_attempts": max(1, int(rescue_max_attempts)),
        "queue_exists": queue_path.exists(),
        "queue_path": str(queue_path),
        "seeded_count": 0,
        "seeded_todo_ids": [],
        "superseded_count": 0,
    }
    if max(0, int(max_clusters)) < 1:
        report["reason"] = "max_clusters_disabled"
        return report
    if not queue_path.exists():
        report["reason"] = "queue_missing"
        return report

    with queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
        supervisor = ModalTodoSupervisor(queue=queue, policy=optimizer_policy)
        before_todo_ids = {todo.todo_id for todo in queue.all()}
        before_status = supervisor.program_synthesis_status()
        rescue_todos = supervisor.seed_failed_validation_rescue_todos(
            max_clusters=max_clusters,
            rescue_max_attempts=rescue_max_attempts,
            program_synthesis_scope=program_synthesis_scope,
            failure_reason=failure_reason,
            original_action=original_action,
        )
        superseded_count = int(
            getattr(supervisor, "last_failed_validation_superseded_count", 0)
        )
        seeded_todo_ids = [
            todo.todo_id
            for todo in rescue_todos
            if todo.todo_id not in before_todo_ids and queue.get(todo.todo_id) is not None
        ]
        deduped_count = int(supervisor.last_program_synthesis_deduped_count)
        after_status = supervisor.program_synthesis_status()
        if seeded_todo_ids or deduped_count or superseded_count:
            queue.save_jsonl(queue_path)

    report.update(
        {
            "after": after_status,
            "before": before_status,
            "deduped_count": deduped_count,
            "failure_reason": str(failure_reason or ""),
            "original_action": str(original_action or ""),
            "program_synthesis_scope": str(program_synthesis_scope or ""),
            "seeded_count": len(seeded_todo_ids),
            "seeded_todo_ids": seeded_todo_ids,
            "superseded_count": superseded_count,
        }
    )
    if not seeded_todo_ids:
        report["reason"] = (
            "resolved_by_completed_rescue"
            if superseded_count
            else
            "existing_or_exhausted_rescue"
            if deduped_count
            else "no_failed_validation_clusters"
        )
    return report


def _paired_failed_validation_rescue_should_seed(
    program_synthesis_health: Mapping[str, Any],
    *,
    mode: str,
    last_seed_at: float,
    interval_seconds: float,
    backlog_threshold: int = 32,
    now: Optional[float] = None,
) -> bool:
    """Return whether paired supervision should recover failed validation work."""

    rescue_mode = str(mode or "auto").strip().lower()
    if rescue_mode == "off":
        return False
    if not bool(program_synthesis_health.get("queue_exists", False)):
        return False
    failed_validation_count = int(
        program_synthesis_health.get("program_synthesis_failed_validation", 0) or 0
    )
    if failed_validation_count < 1:
        return False
    current_time = time.time() if now is None else float(now)
    interval_ready = (current_time - float(last_seed_at or 0.0)) >= max(
        0.0,
        float(interval_seconds),
    )
    if not interval_ready:
        return False
    pending = int(program_synthesis_health.get("program_synthesis_pending", 0) or 0)
    claimed = int(program_synthesis_health.get("program_synthesis_claimed", 0) or 0)
    if bool(program_synthesis_health.get("codex_queue_starved", False)):
        return pending == 0 and claimed == 0
    if rescue_mode == "starved":
        return pending == 0 and claimed == 0
    if rescue_mode in {"auto", "eager"} and failed_validation_count >= max(
        1,
        int(backlog_threshold),
    ):
        return True
    waiting_workers = int(
        program_synthesis_health.get("codex_workers_waiting_for_todos_count", 0) or 0
    )
    active_workers = int(
        program_synthesis_health.get("codex_workers_active_packet_count", 0) or 0
    )
    worker_count = int(program_synthesis_health.get("codex_worker_summary_count", 0) or 0)
    has_idle_capacity = bool(
        waiting_workers > 0
        or (worker_count > 0 and active_workers < worker_count)
    )
    if rescue_mode in {"auto", "eager"}:
        return has_idle_capacity
    return False


def paired_program_synthesis_health(
    *,
    queue_path: Path,
    codex_summary_paths: Sequence[Path],
    policy: Optional[ModalOptimizerPolicy] = None,
    codex_worker_stale_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Return paired-run queue and Codex-worker health from shared artifacts."""

    optimizer_policy = policy or ModalOptimizerPolicy()
    health: Dict[str, Any] = {
        "codex_claimed_total": 0,
        "codex_execution_count": 0,
        "codex_worker_stale_seconds": max(0.0, float(codex_worker_stale_seconds)),
        "codex_worker_summary_count": 0,
        "codex_workers_active_packet_count": 0,
        "codex_workers_waiting_for_todos_count": 0,
        "queue_exists": queue_path.exists(),
        "queue_path": str(queue_path),
    }
    if queue_path.exists():
        try:
            with queue_file_lock(queue_path):
                queue = ModalTodoQueue.load_jsonl(queue_path)
            status = program_synthesis_status_block(queue, optimizer_policy)
            role_queue_counts = queue.role_status_counts()
            program_role_counts = role_queue_counts.get(
                optimizer_policy.program_synthesis_role,
                {},
            )
            claimed_by_counts: Counter[str] = Counter(
                str(todo.claimed_by or "unknown")
                for todo in queue.claimed(
                    optimizer_role=optimizer_policy.program_synthesis_role
                )
            )
            failed_validation_report = _program_synthesis_failed_validation_report(
                queue,
                optimizer_role=optimizer_policy.program_synthesis_role,
            )
            health.update(
                {
                    "program_synthesis_claimed": int(status.get("claimed", 0)),
                    "program_synthesis_claimed_by_worker": dict(
                        sorted(claimed_by_counts.items())
                    ),
                    "program_synthesis_completed": int(status.get("completed", 0)),
                    "program_synthesis_failed_validation": int(
                        status.get("failed_validation", 0)
                    ),
                    "program_synthesis_failed_validation_reason_counts": (
                        failed_validation_report["reason_counts"]
                    ),
                    "program_synthesis_failed_validation_kind_counts": (
                        failed_validation_report["kind_counts"]
                    ),
                    "program_synthesis_failed_validation_test_counts": (
                        failed_validation_report["test_counts"]
                    ),
                    "program_synthesis_pending": int(status.get("pending", 0)),
                    "program_synthesis_superseded": int(
                        program_role_counts.get("superseded", 0)
                    ),
                    "queue_counts": queue.status_counts(),
                    "role_queue_counts": role_queue_counts,
                }
            )
        except Exception as exc:
            health["queue_error"] = f"{type(exc).__name__}: {exc}"
    else:
        health.update(
            {
                "program_synthesis_claimed": 0,
                "program_synthesis_claimed_by_worker": {},
                "program_synthesis_completed": 0,
                "program_synthesis_failed_validation": 0,
                "program_synthesis_failed_validation_kind_counts": {},
                "program_synthesis_failed_validation_reason_counts": {},
                "program_synthesis_failed_validation_test_counts": {},
                "program_synthesis_pending": 0,
                "program_synthesis_superseded": 0,
                "queue_counts": {},
                "role_queue_counts": {},
            }
        )

    child_health = accelerate_summarize_child_summary_files(
        codex_summary_paths,
        spec=ChildSummaryHealthSpec(
            numeric_total_fields=("codex_claimed_total", "codex_execution_count"),
            scope_field="codex_scope",
            waiting_reasons=frozenset({"waiting_for_program_synthesis_todos"}),
        ),
        stale_seconds=max(0.0, float(codex_worker_stale_seconds)),
    )
    child_numeric_totals = dict(child_health.get("numeric_totals", {}) or {})
    scope_counts = dict(child_health.get("scope_counts", {}) or {})
    worker_waiting = int(child_health.get("waiting_count", 0) or 0)
    worker_claimed_total = int(child_numeric_totals.get("codex_claimed_total", 0) or 0)
    worker_execution_count = int(
        child_numeric_totals.get("codex_execution_count", 0) or 0
    )
    worker_summaries = int(child_health.get("summary_count", 0) or 0)
    worker_summary_age_seconds = dict(
        child_health.get("summary_age_seconds", {}) or {}
    )
    worker_latest_reasons = dict(child_health.get("latest_stop_reasons", {}) or {})
    stale_worker_ids = {
        str(worker_id)
        for worker_id in list(child_health.get("stale_child_ids", []) or [])
        if str(worker_id)
    }
    worker_active_packets = int(child_health.get("active_count", 0) or 0)
    if worker_active_packets <= 0:
        worker_active_packets = _active_codex_packet_summary_count(codex_summary_paths)
    if worker_active_packets > 0 and worker_waiting > 0:
        worker_waiting = max(0, worker_waiting - worker_active_packets)
    pending = int(health.get("program_synthesis_pending", 0) or 0)
    claimed = int(health.get("program_synthesis_claimed", 0) or 0)
    failed_validation = int(health.get("program_synthesis_failed_validation", 0) or 0)
    completed = int(health.get("program_synthesis_completed", 0) or 0)
    superseded = int(health.get("program_synthesis_superseded", 0) or 0)
    claimed_by_workers = set(
        str(worker_id)
        for worker_id in dict(
            health.get("program_synthesis_claimed_by_worker", {}) or {}
        )
        if str(worker_id) and str(worker_id) != "unknown"
    )
    stale_claimed_workers = stale_worker_ids & claimed_by_workers
    stale_idle_workers = stale_worker_ids - claimed_by_workers
    health.update(
        {
            "codex_claimed_total": worker_claimed_total,
            "codex_execution_count": worker_execution_count,
            "codex_queue_open_count": pending + claimed,
            "codex_queue_drained": bool(
                health.get("queue_exists")
                and pending == 0
                and claimed == 0
                and failed_validation == 0
                and (completed > 0 or superseded > 0)
            ),
            "codex_queue_starved": bool(
                health.get("queue_exists")
                and pending == 0
                and claimed == 0
                and failed_validation > 0
            ),
            "codex_scope_worker_counts": dict(sorted(scope_counts.items())),
            "codex_worker_latest_stop_reasons": dict(
                sorted(worker_latest_reasons.items())
            ),
            "codex_workers_active_packet_count": worker_active_packets,
            "codex_idle_worker_stale_count": len(stale_idle_workers),
            "codex_worker_stale_count": len(stale_claimed_workers),
            "codex_worker_summary_count": worker_summaries,
            "codex_worker_summary_age_seconds": dict(
                sorted(worker_summary_age_seconds.items())
            ),
            "codex_workers_waiting_for_todos_count": worker_waiting,
            "stale_claimed_codex_worker_ids": sorted(stale_claimed_workers),
            "stale_idle_codex_worker_ids": sorted(stale_idle_workers),
            "stale_codex_worker_ids": sorted(stale_worker_ids),
        }
    )
    return health


def _program_synthesis_failed_validation_report(
    queue: ModalTodoQueue,
    *,
    optimizer_role: str,
) -> Dict[str, Any]:
    """Summarize failed-validation reasons and concrete failed validation tests."""

    kind_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    test_counts: Counter[str] = Counter()
    for todo in queue.all():
        if todo.status != "failed_validation":
            continue
        metadata = todo.metadata if isinstance(todo.metadata, Mapping) else {}
        todo_role = str(metadata.get("optimizer_role") or "").strip()
        if todo_role and todo_role != optimizer_role:
            continue
        if not todo_role and str(metadata.get("execution_target") or "") not in {
            "codex_program_repair",
            "external_codex_worker",
        }:
            continue
        reason = str(
            metadata.get("failed_validation_reason")
            or metadata.get("failure_reason")
            or ""
        ).strip()
        if not reason:
            reason = "unknown"
        reason_counts[reason] += 1

        report = metadata.get("failed_validation_report")
        kind = str(metadata.get("failed_validation_kind") or "").strip()
        if not kind:
            kind = _program_synthesis_validation_failure_kind(report)
        kind_counts[kind or "unclassified"] += 1
        if not isinstance(report, Mapping):
            continue
        todo_failed_tests: set[str] = set()
        failed_tests = report.get("main_apply_validation_failed_tests") or ()
        if isinstance(failed_tests, (str, bytes)):
            failed_tests = (str(failed_tests),)
        if isinstance(failed_tests, Iterable):
            for test_id in failed_tests:
                test_text = str(test_id or "").strip()
                if test_text:
                    todo_failed_tests.add(test_text)
        failure_tokens = report.get("main_apply_validation_failure_tokens") or ()
        if isinstance(failure_tokens, (str, bytes)):
            failure_tokens = (str(failure_tokens),)
        if isinstance(failure_tokens, Iterable):
            for token in failure_tokens:
                token_text = str(token or "").strip()
                if token_text.startswith("pytest:"):
                    todo_failed_tests.add(token_text.removeprefix("pytest:"))
        for test_text in sorted(todo_failed_tests):
            test_counts[test_text] += 1

    return {
        "kind_counts": dict(sorted(kind_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "test_counts": dict(sorted(test_counts.items())),
    }


def _active_codex_packet_summary_count(paths: Sequence[Path]) -> int:
    """Count Codex summaries that are actively executing a claimed packet."""

    active_count = 0
    for path in paths:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        active_ids = data.get("active_packet_claimed_todo_ids")
        phase = str(data.get("active_packet_phase") or "").strip().lower()
        if (
            isinstance(active_ids, Sequence)
            and not isinstance(active_ids, (str, bytes))
            and len(active_ids) > 0
        ) or phase in {"executing_codex_packet", "applying_codex_packet"}:
            active_count += 1
    return active_count


def _timestamp_age_seconds(timestamp: Any, *, now: Optional[Any] = None) -> Optional[float]:
    """Return timestamp age while supporting deterministic test clocks."""

    if timestamp in (None, ""):
        return None
    if now is None:
        try:
            return accelerate_timestamp_age_seconds(timestamp)
        except TypeError:
            pass
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if isinstance(now, datetime):
        current = now
    elif now is None:
        current = datetime.now(timezone.utc)
    else:
        current = datetime.fromtimestamp(float(now), timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current - parsed).total_seconds())


def paired_autoencoder_child_health(
    summary_path: Path,
    *,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Return paired-run autoencoder heartbeat health from its child summary."""

    now_epoch = time.time() if now is None else now
    health: Dict[str, Any] = {
        "autoencoder_summary_exists": summary_path.exists(),
        "autoencoder_summary_path": str(summary_path),
    }
    if not summary_path.exists():
        return health
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        health["autoencoder_summary_error"] = f"{type(exc).__name__}: {exc}"
        return health

    updated_at = data.get("updated_at")
    active_heartbeat_at = data.get("active_cycle_last_heartbeat_at")
    heartbeat_at = active_heartbeat_at or updated_at
    health.update(
        {
            "autoencoder_active_cycle": data.get("active_cycle"),
            "autoencoder_active_cycle_elapsed_seconds": data.get(
                "active_cycle_elapsed_seconds"
            ),
            "autoencoder_active_cycle_heartbeat_age_seconds": _timestamp_age_seconds(
                active_heartbeat_at,
                now=now_epoch,
            ),
            "autoencoder_active_cycle_last_heartbeat_at": active_heartbeat_at,
            "autoencoder_active_cycle_phase": data.get("active_cycle_phase"),
            "autoencoder_active_cycle_projection_progress": data.get(
                "active_cycle_projection_progress",
                {},
            ),
            "autoencoder_active_cycle_projection_stage": data.get(
                "active_cycle_projection_stage"
            ),
            "autoencoder_cycles": data.get("cycles"),
            "autoencoder_effective_heartbeat_age_seconds": _timestamp_age_seconds(
                heartbeat_at,
                now=now_epoch,
            ),
            "autoencoder_latest_stop_reason": data.get("latest_stop_reason"),
            "autoencoder_summary_final": data.get("final"),
            "autoencoder_summary_age_seconds": _timestamp_age_seconds(
                updated_at,
                now=now_epoch,
            ),
            "autoencoder_summary_updated_at": updated_at,
        }
    )
    return health


def fast_program_synthesis_bootstrap_todos(
    samples: Sequence[Any],
    *,
    policy: Optional[ModalOptimizerPolicy] = None,
    cycle: int = 0,
    actions: Sequence[str] = FAST_BOOTSTRAP_PROGRAM_SYNTHESIS_ACTIONS,
    max_samples: int = 8,
) -> List[ModalTodo]:
    """Seed scope-aware Codex work without running heavy autoencoder introspection."""

    sample_list = list(samples)
    if not sample_list:
        return []
    optimizer_policy = policy or ModalOptimizerPolicy()
    sample_ids: List[str] = []
    samples_by_id: Dict[str, Any] = {}
    citations: List[str] = []
    for index, sample in enumerate(sample_list[: max(1, int(max_samples))]):
        sample_id = str(getattr(sample, "sample_id", "") or f"bootstrap-sample-{index}")
        sample_ids.append(sample_id)
        samples_by_id[sample_id] = sample
        citation = str(
            getattr(sample, "citation", "")
            or getattr(sample, "normalized_citation", "")
            or getattr(sample, "section", "")
            or sample_id
        )
        if citation:
            citations.append(citation)
    sample_ids = list(dict.fromkeys(sample_ids))
    citations = list(dict.fromkeys(citations))
    if not sample_ids:
        return []

    todos: List[ModalTodo] = []
    unique_actions = dict.fromkeys(str(item) for item in actions if str(item))
    for rank, action in enumerate(unique_actions):
        target_component = str(PROGRAM_SYNTHESIS_ACTION_TARGETS.get(action) or "")
        if not target_component:
            continue
        program_synthesis_scope = _program_synthesis_scope(
            action=action,
            target_component=target_component,
        )
        target_metrics = _program_synthesis_target_metrics(
            action=action,
            target_component=target_component,
        )
        validation_commands = _program_synthesis_validation_commands(
            action=action,
            target_component=target_component,
            program_synthesis_scope=program_synthesis_scope,
        )
        metric_sample_payloads = _program_synthesis_sample_payloads(
            sample_ids,
            samples_by_id=samples_by_id,
            max_samples=max_samples,
        )
        dedupe_signature = json.dumps(
            {
                "action": action,
                "cycle": int(cycle),
                "mode": "fast_bootstrap",
                "sample_ids": sample_ids,
                "target_component": target_component,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        semantic_bundle_key = (
            f"fast_bootstrap:{program_synthesis_scope}:{action}:{target_component}"
        )
        hint_evidence = [
            {
                "action": action,
                "cycle": int(cycle),
                "hint_id": f"fast-bootstrap-{program_synthesis_scope}-{rank:02d}",
                "program_synthesis_scope": program_synthesis_scope,
                "sample_id": sample_id,
                "source": "modal_program_synthesis_fast_bootstrap_v1",
                "target_component": target_component,
                "target_metrics": target_metrics,
            }
            for sample_id in sample_ids[:max_samples]
        ]
        metadata = {
            **optimizer_policy.metadata_for(
                action=action,
                loss_name="program_synthesis_bootstrap",
            ),
            "dedupe_signature": dedupe_signature,
            "hint_evidence": hint_evidence,
            "hint_ids": [str(item["hint_id"]) for item in hint_evidence],
            "metric_sample_payloads": metric_sample_payloads,
            "program_synthesis_scope": program_synthesis_scope,
            "residual_cluster_stage": "cycle_bootstrap_fast_seed",
            "residual_signatures": [semantic_bundle_key],
            "semantic_bundle_key": semantic_bundle_key,
            "source": "modal_program_synthesis_fast_bootstrap_v1",
            "support_count": len(sample_ids),
            "target_component": target_component,
            "target_metrics": target_metrics,
            "validation_commands": validation_commands,
        }
        todos.append(
            ModalTodo(
                todo_id=_program_todo_id(
                    action=action,
                    target_component=target_component,
                    sample_ids=sample_ids,
                ),
                action=action,
                objective=(
                    f"Bootstrap the {program_synthesis_scope} Codex lane before "
                    "full autoencoder introspection completes; inspect the supplied "
                    f"samples and improve {target_component} for "
                    f"{', '.join(target_metrics[:3])}."
                ),
                sample_ids=list(sample_ids),
                citations=list(citations),
                loss_name="program_synthesis_bootstrap",
                loss_value=1.0,
                priority=round(1000.0 - float(rank), 6),
                metadata=metadata,
            )
        )
    return sorted(todos, key=lambda todo: (-todo.priority, todo.todo_id))


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


def autoencoder_metric_bridge_adapter_names(
    args: argparse.Namespace,
    bridge_adapters: Sequence[str],
) -> List[str]:
    """Return bridge adapters used for autoencoder-side LegalIR metrics.

    Bridge loss TODO generation can afford to be broader than the synchronous
    autoencoder metric path.  The autoencoder path runs before and after each
    training cycle, so by default it uses a cheap, representative bridge subset.
    Keep that metric subset alive even when bridge-loss TODO generation is
    disabled; otherwise the learned LegalIR-view head has no targets.
    """

    env_raw = os.environ.get("IPFS_DATASETS_AUTOENCODER_METRIC_BRIDGE_ADAPTERS")
    raw_value = getattr(args, "autoencoder_metric_bridge_adapters", None)
    raw = str(raw_value if raw_value is not None else env_raw or "").strip()
    normalized = raw.lower()
    bridge_adapter_list = [
        str(name).strip()
        for name in bridge_adapters
        if str(name).strip()
    ]
    if normalized in {"none", "off", "false"}:
        return []
    if normalized in {"auto", "default"}:
        raw = ""
        normalized = ""
    if normalized in {"all", "bridge", "bridge_loss", "same"}:
        return list(bridge_adapter_list)
    if raw:
        return [
            name
            for name in (part.strip() for part in raw.split(","))
            if name and name.lower() not in {"none", "off", "false"}
        ]
    registered_bridge_adapters = set(DEFAULT_LEGAL_IR_BRIDGE_NAMES)
    default_adapter_list = [
        name
        for name in DEFAULT_AUTOENCODER_METRIC_BRIDGE_ADAPTERS
        if name in registered_bridge_adapters
    ]
    preferred = [
        name
        for name in DEFAULT_AUTOENCODER_METRIC_BRIDGE_ADAPTERS
        if name in bridge_adapter_list
    ]
    if preferred:
        return preferred
    if default_adapter_list:
        return default_adapter_list
    return bridge_adapter_list[:1]


def autoencoder_diagnostic_bridge_adapter_names(
    args: argparse.Namespace,
    bridge_adapters: Sequence[str],
    metric_bridge_adapters: Sequence[str],
) -> List[str]:
    """Return bridge adapters used by synchronous compiler bridge diagnostics."""

    env_raw = os.environ.get("IPFS_DATASETS_AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS")
    raw_value = getattr(args, "autoencoder_diagnostic_bridge_adapters", None)
    raw = str(raw_value if raw_value is not None else env_raw or "").strip()
    normalized = raw.lower()
    bridge_adapter_list = [
        str(name).strip()
        for name in bridge_adapters
        if str(name).strip()
    ]
    metric_adapter_list = [
        str(name).strip()
        for name in metric_bridge_adapters
        if str(name).strip()
    ]
    if raw_value is None and not env_raw:
        return list(DEFAULT_AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS)
    if normalized in {"none", "off", "false"}:
        return []
    if normalized in {"auto", "default"}:
        raw = ""
        normalized = ""
    if normalized in {"all", "bridge", "bridge_loss"}:
        return list(bridge_adapter_list)
    if normalized in {"metric", "metrics", "autoencoder_metric", "same"}:
        return list(metric_adapter_list)
    if raw:
        return [
            name
            for name in (part.strip() for part in raw.split(","))
            if name and name.lower() not in {"none", "off", "false"}
        ]
    preferred = [
        name
        for name in DEFAULT_AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS
        if name in bridge_adapter_list
    ]
    if preferred:
        return preferred
    if metric_adapter_list:
        return metric_adapter_list
    return bridge_adapter_list[:1]


def _paired_autoencoder_bridge_adapter_arg(
    args: argparse.Namespace,
    attr_name: str,
    env_name: str,
    *,
    default_value: str = "default",
) -> str:
    """Return a stable child-process adapter argument for paired runs."""
    raw_value = getattr(args, attr_name, None)
    raw = str(
        raw_value
        if raw_value is not None
        else os.environ.get(env_name, "")
    ).strip()
    if not raw or raw.lower() in _FALSE_ENV_VALUES:
        return default_value
    return raw


def autoencoder_metric_bridge_max_samples(args: argparse.Namespace) -> int:
    """Return sample cap for bridge-backed autoencoder metrics."""

    if getattr(args, "autoencoder_metric_bridge_max_samples", None) is not None:
        return max(0, int(getattr(args, "autoencoder_metric_bridge_max_samples") or 0))
    return _env_int(
        "IPFS_DATASETS_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLES",
        DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLES,
        minimum=0,
    )


def autoencoder_metric_bridge_max_sample_text_chars(args: argparse.Namespace) -> int:
    """Return text cap for bridge-backed autoencoder metric samples."""

    if getattr(args, "autoencoder_metric_bridge_max_sample_text_chars", None) is not None:
        return max(
            0,
            int(getattr(args, "autoencoder_metric_bridge_max_sample_text_chars") or 0),
        )
    return _env_int(
        AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS_ENV,
        DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
        minimum=0,
    )


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
    requested_scope = getattr(args, "codex_scope", None)
    metadata_filter = _codex_scope_filter(requested_scope)
    scope_fallback_enabled = bool(
        getattr(args, "codex_scope_fallback_to_global", True)
    )
    with queue_file_lock(queue_path):
        snapshot_queue = ModalTodoQueue.load_jsonl(queue_path)
        apply_backpressure_report = _codex_main_apply_backpressure_report(
            snapshot_queue,
            args=args,
            policy=policy,
            worker_id=worker_id,
        )
        if apply_backpressure_report.get("blocked"):
            status = update_program_synthesis_summary(
                summary,
                snapshot_queue,
                policy,
                execution_mode=execution_mode,
            )
            vector_report = {
                "mode": "main_apply_backpressure",
                "selected_count": 0,
                "wait_reason": str(
                    apply_backpressure_report.get("reason")
                    or "main_apply_backpressure"
                ),
            }
            vector_report.update(
                {
                    f"main_apply_backpressure_{key}": value
                    for key, value in apply_backpressure_report.items()
                }
            )
            return [], snapshot_queue, status, vector_report
        raw_candidates = [
            todo
            for todo in snapshot_queue.pending(optimizer_role=policy.program_synthesis_role)
            if _metadata_matches(todo, metadata_filter)
        ]
        scoped_candidate_count = len(raw_candidates)
        effective_metadata_filter = metadata_filter
        if (
            not raw_candidates
            and requested_scope
            and scope_fallback_enabled
        ):
            raw_candidates = list(
                snapshot_queue.pending(optimizer_role=policy.program_synthesis_role)
            )
            effective_metadata_filter = None
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
        "requested_scope": str(requested_scope or ""),
        "scope_fallback_enabled": scope_fallback_enabled,
        "scope_fallback_used": bool(effective_metadata_filter is None and metadata_filter is not None),
        "scoped_candidate_count": scoped_candidate_count,
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
            apply_backpressure_report = _codex_main_apply_backpressure_report(
                queue,
                args=args,
                policy=policy,
                worker_id=worker_id,
            )
            if apply_backpressure_report.get("blocked"):
                status = update_program_synthesis_summary(
                    summary,
                    queue,
                    policy,
                    execution_mode=execution_mode,
                )
                vector_report.update(
                    {
                        "mode": "main_apply_backpressure",
                        "selected_count": 0,
                        "wait_reason": str(
                            apply_backpressure_report.get("reason")
                            or "main_apply_backpressure"
                        ),
                        **{
                            f"main_apply_backpressure_{key}": value
                            for key, value in apply_backpressure_report.items()
                        },
                    }
                )
                return [], queue, status, vector_report
            supervisor = ModalTodoSupervisor(queue=queue, policy=policy)
            claimed = supervisor.claim_program_synthesis_batch(
                worker_id=worker_id,
                max_items=args.max_items,
                program_synthesis_scope=(
                    None
                    if effective_metadata_filter is None
                    else requested_scope
                ),
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
        apply_backpressure_report = _codex_main_apply_backpressure_report(
            queue,
            args=args,
            policy=policy,
            worker_id=worker_id,
        )
        if apply_backpressure_report.get("blocked"):
            status = update_program_synthesis_summary(
                summary,
                queue,
                policy,
                execution_mode=execution_mode,
            )
            vector_report.update(
                {
                    "anchor_id": anchor_id,
                    "mode": "main_apply_backpressure",
                    "proposed_selected_count": len(selected),
                    "proposed_selected_ids": selected_ids,
                    "selected_count": 0,
                    "wait_reason": str(
                        apply_backpressure_report.get("reason")
                        or "main_apply_backpressure"
                    ),
                    **{
                        f"main_apply_backpressure_{key}": value
                        for key, value in apply_backpressure_report.items()
                    },
                }
            )
            return [], queue, status, vector_report
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
            metadata_filter=effective_metadata_filter,
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


def _claim_program_synthesis_batch_with_scope_fallback(
    supervisor: ModalTodoSupervisor,
    *,
    worker_id: str,
    max_items: int,
    requested_scope: Optional[str],
    semantic_bundle: bool,
    fallback_to_global: bool,
) -> tuple[List[ModalTodo], Dict[str, Any]]:
    """Claim scoped work first, then borrow global work if that lane is empty."""

    claimed = supervisor.claim_program_synthesis_batch(
        worker_id=worker_id,
        max_items=max_items,
        program_synthesis_scope=requested_scope,
        semantic_bundle=semantic_bundle,
    )
    report: Dict[str, Any] = {
        "borrowed_count": 0,
        "fallback_enabled": bool(fallback_to_global),
        "fallback_used": False,
        "requested_scope": str(requested_scope or ""),
        "worker_id": worker_id,
    }
    if claimed or not requested_scope or not fallback_to_global:
        return claimed, report

    claimed = supervisor.claim_program_synthesis_batch(
        worker_id=worker_id,
        max_items=max_items,
        program_synthesis_scope=None,
        semantic_bundle=semantic_bundle,
    )
    if claimed:
        report.update(
            {
                "borrowed_count": len(claimed),
                "borrowed_scopes": sorted(
                    {
                        str(todo.metadata.get("program_synthesis_scope", "") or "")
                        for todo in claimed
                    }
                ),
                "fallback_used": True,
            }
    )
    return claimed, report


def _codex_main_apply_backpressure_report(
    queue: ModalTodoQueue,
    *,
    args: argparse.Namespace,
    policy: ModalOptimizerPolicy,
    worker_id: str,
) -> Dict[str, Any]:
    """Throttle new apply-to-main packets when the serialized apply lane is full."""
    max_inflight = max(
        0,
        int(getattr(args, "codex_main_apply_max_inflight_packets", 0) or 0),
    )
    apply_mode = str(getattr(args, "codex_apply_mode", "") or "").strip().lower()
    pending_count = len(
        queue.pending(optimizer_role=policy.program_synthesis_role)
    )
    claimed_todos = list(
        queue.claimed(optimizer_role=policy.program_synthesis_role)
    )
    claimed_workers = sorted(
        {
            str(todo.claimed_by or "")
            for todo in claimed_todos
            if str(todo.claimed_by or "")
        }
    )
    active_other_workers = [
        claimed_worker
        for claimed_worker in claimed_workers
        if claimed_worker != str(worker_id)
    ]
    active_packet_count = len(claimed_workers)
    report = {
        "active_packet_count": active_packet_count,
        "active_other_packet_count": len(active_other_workers),
        "active_workers": claimed_workers,
        "blocked": False,
        "enabled": apply_mode == "apply_to_main" and max_inflight > 0,
        "max_inflight_packets": max_inflight,
        "pending_count": pending_count,
        "reason": "",
    }
    if (
        report["enabled"]
        and pending_count > 0
        and active_packet_count >= max_inflight
        and str(worker_id) not in set(claimed_workers)
    ):
        report["blocked"] = True
        report["reason"] = "main_apply_inflight_limit_reached"
    return report


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
        "--codex-validation-timeout-seconds",
        str(getattr(args, "codex_validation_timeout_seconds", CODEX_APPLY_VALIDATION_TIMEOUT_SECONDS)),
        "--codex-claim-stale-seconds",
        str(getattr(args, "codex_claim_stale_seconds", 0.0)),
        "--codex-apply-mode",
        str(getattr(args, "codex_apply_mode", "patch_only")),
        "--codex-commit-mode",
        str(getattr(args, "codex_commit_mode", "none")),
        "--codex-scope-fallback-to-global",
        str(bool(getattr(args, "codex_scope_fallback_to_global", True))).lower(),
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
        "--codex-main-apply-lock-timeout-seconds",
        str(
            getattr(
                args,
                "codex_main_apply_lock_timeout_seconds",
                CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS,
            )
        ),
        "--codex-main-apply-max-inflight-packets",
        str(getattr(args, "codex_main_apply_max_inflight_packets", 0)),
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
        str(getattr(args, "validation_canary_count", DEFAULT_VALIDATION_CANARY_COUNT)),
        "--validation-canary-indices",
        str(getattr(args, "validation_canary_indices", "")),
        "--max-sample-text-chars",
        str(getattr(args, "max_sample_text_chars", 0)),
        "--compiler-ir-metric-max-sample-text-chars",
        str(
            getattr(
                args,
                "compiler_ir_metric_max_sample_text_chars",
                DEFAULT_COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS,
            )
        ),
        "--compiler-ir-metric-text-policy",
        str(
            getattr(
                args,
                "compiler_ir_metric_text_policy",
                DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY,
            )
        ),
        "--compiler-ir-metric-sample-timeout-seconds",
        str(
            getattr(
                args,
                "compiler_ir_metric_sample_timeout_seconds",
                DEFAULT_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS,
            )
        ),
        "--compiler-ir-train-mode",
        str(
            getattr(
                args,
                "compiler_ir_train_mode",
                DEFAULT_COMPILER_IR_TRAIN_MODE,
            )
        ),
        "--compiler-ir-train-every-n-cycles",
        str(
            getattr(
                args,
                "compiler_ir_train_every_n_cycles",
                DEFAULT_COMPILER_IR_TRAIN_EVERY_N_CYCLES,
            )
        ),
        "--compiler-ir-guided-train-mode",
        str(
            getattr(
                args,
                "compiler_ir_guided_train_mode",
                DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE,
            )
        ),
        "--compiler-ir-guided-train-every-n-cycles",
        str(
            getattr(
                args,
                "compiler_ir_guided_train_every_n_cycles",
                DEFAULT_COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES,
            )
        ),
        "--autoencoder-before-train-eval-mode",
        str(
            getattr(
                args,
                "autoencoder_before_train_eval_mode",
                DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE,
            )
        ),
        "--autoencoder-before-train-eval-every-n-cycles",
        str(
            getattr(
                args,
                "autoencoder_before_train_eval_every_n_cycles",
                DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES,
            )
        ),
        "--autoencoder-sample-memory-probe-mode",
        str(
            getattr(
                args,
                "autoencoder_sample_memory_probe_mode",
                DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE,
            )
        ),
        "--autoencoder-sample-memory-probe-every-n-cycles",
        str(
            getattr(
                args,
                "autoencoder_sample_memory_probe_every_n_cycles",
                DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES,
            )
        ),
        "--autoencoder-todo-supervisor-mode",
        str(
            getattr(
                args,
                "autoencoder_todo_supervisor_mode",
                DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE,
            )
        ),
        "--autoencoder-todo-supervisor-min-open",
        str(
            getattr(
                args,
                "autoencoder_todo_supervisor_min_open",
                DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN,
            )
        ),
        "--uscode-embeddings-mode",
        str(getattr(args, "uscode_embeddings_mode", "auto")),
        "--uscode-embeddings-path",
        str(getattr(args, "uscode_embeddings_path", USCODE_EMBEDDINGS_PARQUET)),
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
        str(
            getattr(
                args,
                "bridge_evaluate_provers",
                DEFAULT_BRIDGE_EVALUATE_PROVERS,
            )
        ).lower(),
        "--autoencoder-metric-bridge-adapters",
        _paired_autoencoder_bridge_adapter_arg(
            args,
            "autoencoder_metric_bridge_adapters",
            "IPFS_DATASETS_AUTOENCODER_METRIC_BRIDGE_ADAPTERS",
        ),
        "--autoencoder-diagnostic-bridge-adapters",
        _paired_autoencoder_bridge_adapter_arg(
            args,
            "autoencoder_diagnostic_bridge_adapters",
            "IPFS_DATASETS_AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS",
            default_value="none",
        ),
        "--autoencoder-metric-bridge-max-samples",
        str(
            getattr(
                args,
                "autoencoder_metric_bridge_max_samples",
                DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLES,
            )
            if getattr(args, "autoencoder_metric_bridge_max_samples", None) is not None
            else DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLES
        ),
        "--autoencoder-metric-bridge-max-sample-text-chars",
        str(
            getattr(
                args,
                "autoencoder_metric_bridge_max_sample_text_chars",
                DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
            )
            if getattr(args, "autoencoder_metric_bridge_max_sample_text_chars", None)
            is not None
            else DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS
        ),
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
        "--autoencoder-max-legal-semantic-frame-features",
        str(getattr(args, "autoencoder_max_legal_semantic_frame_features", 64)),
        "--autoencoder-max-normative-polarity-features",
        str(getattr(args, "autoencoder_max_normative_polarity_features", 48)),
        "--autoencoder-max-compiler-contract-features",
        str(getattr(args, "autoencoder_max_compiler_contract_features", 64)),
        "--autoencoder-max-decompiler-surface-template-features",
        str(getattr(args, "autoencoder_max_decompiler_surface_template_features", 48)),
        "--autoencoder-max-canonical-ir-graph-features",
        str(getattr(args, "autoencoder_max_canonical_ir_graph_features", 64)),
        "--autoencoder-max-cycle-consistency-features",
        str(getattr(args, "autoencoder_max_cycle_consistency_features", 64)),
        "--autoencoder-max-equivalence-prototype-features",
        str(getattr(args, "autoencoder_max_equivalence_prototype_features", 48)),
        "--autoencoder-max-contrastive-ir-boundary-features",
        str(getattr(args, "autoencoder_max_contrastive_ir_boundary_features", 64)),
        "--autoencoder-max-repair-plan-features",
        str(getattr(args, "autoencoder_max_repair_plan_features", 64)),
        "--autoencoder-max-logic-view-contract-features",
        str(getattr(args, "autoencoder_max_logic_view_contract_features", 64)),
        "--autoencoder-max-objective-residual-features",
        str(getattr(args, "autoencoder_max_objective_residual_features", 64)),
        "--autoencoder-max-provenance-alignment-features",
        str(getattr(args, "autoencoder_max_provenance_alignment_features", 64)),
        "--autoencoder-max-discourse-flow-features",
        str(getattr(args, "autoencoder_max_discourse_flow_features", 64)),
        "--autoencoder-max-proof-obligation-features",
        str(getattr(args, "autoencoder_max_proof_obligation_features", 64)),
        "--autoencoder-max-entity-binding-features",
        str(getattr(args, "autoencoder_max_entity_binding_features", 64)),
        "--autoencoder-max-defeasible-priority-features",
        str(getattr(args, "autoencoder_max_defeasible_priority_features", 64)),
        "--autoencoder-max-constraint-grounding-features",
        str(getattr(args, "autoencoder_max_constraint_grounding_features", 64)),
        "--autoencoder-max-quantitative-formula-features",
        str(getattr(args, "autoencoder_max_quantitative_formula_features", 64)),
        "--autoencoder-max-definition-grounding-features",
        str(getattr(args, "autoencoder_max_definition_grounding_features", 64)),
        "--autoencoder-max-quantifier-scope-features",
        str(getattr(args, "autoencoder_max_quantifier_scope_features", 64)),
        "--autoencoder-max-procedural-lifecycle-features",
        str(getattr(args, "autoencoder_max_procedural_lifecycle_features", 64)),
        "--autoencoder-max-enforcement-remedy-features",
        str(getattr(args, "autoencoder_max_enforcement_remedy_features", 64)),
        "--autoencoder-max-mental-state-features",
        str(getattr(args, "autoencoder_max_mental_state_features", 64)),
        "--autoencoder-max-reference-dependency-features",
        str(getattr(args, "autoencoder_max_reference_dependency_features", 64)),
        "--autoencoder-max-amendment-operation-features",
        str(getattr(args, "autoencoder_max_amendment_operation_features", 64)),
        "--autoencoder-max-authority-jurisdiction-features",
        str(getattr(args, "autoencoder_max_authority_jurisdiction_features", 64)),
        "--autoencoder-max-discretion-standard-features",
        str(getattr(args, "autoencoder_max_discretion_standard_features", 64)),
        "--autoencoder-max-temporal-validity-features",
        str(getattr(args, "autoencoder_max_temporal_validity_features", 64)),
        "--autoencoder-max-evidentiary-burden-features",
        str(getattr(args, "autoencoder_max_evidentiary_burden_features", 64)),
        "--autoencoder-max-legal-relation-features",
        str(getattr(args, "autoencoder_max_legal_relation_features", 64)),
        "--autoencoder-max-status-transition-features",
        str(getattr(args, "autoencoder_max_status_transition_features", 64)),
        "--autoencoder-max-condition-consequence-features",
        str(getattr(args, "autoencoder_max_condition_consequence_features", 64)),
        "--autoencoder-max-applicability-scope-features",
        str(getattr(args, "autoencoder_max_applicability_scope_features", 64)),
        "--autoencoder-max-coreference-binding-features",
        str(getattr(args, "autoencoder_max_coreference_binding_features", 64)),
        "--autoencoder-max-logical-connective-features",
        str(getattr(args, "autoencoder_max_logical_connective_features", 64)),
        "--autoencoder-max-enumeration-hierarchy-features",
        str(getattr(args, "autoencoder_max_enumeration_hierarchy_features", 64)),
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
        str(getattr(args, "autoencoder_cosine_reconstruction_weight", 0.5)),
        "--autoencoder-max-token-features",
        str(getattr(args, "autoencoder_max_token_features", 48)),
        "--autoencoder-max-token-bigram-features",
        str(getattr(args, "autoencoder_max_token_bigram_features", 24)),
        "--autoencoder-max-token-trigram-features",
        str(getattr(args, "autoencoder_max_token_trigram_features", 12)),
        "--autoencoder-max-codec-feature-keys",
        str(getattr(args, "autoencoder_max_codec_feature_keys", 0)),
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
        str(getattr(args, "generalizable_projection_objective_cosine_gap_weight", 1.5)),
        "--generalizable-projection-objective-legal-ir-weight",
        str(getattr(args, "generalizable_projection_objective_legal_ir_weight", 1.0)),
        "--generalizable-projection-hard-example-fraction",
        str(getattr(args, "generalizable_projection_hard_example_fraction", 1.0)),
        "--generalizable-projection-timeout-seconds",
        str(
            getattr(
                args,
                "generalizable_projection_timeout_seconds",
                DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS,
            )
        ),
        "--generalizable-projection-max-line-search-attempts",
        str(getattr(args, "generalizable_projection_max_line_search_attempts", 0)),
        "--autoencoder-projection-deadband-mode",
        str(
            getattr(
                args,
                "autoencoder_projection_deadband_mode",
                DEFAULT_AUTOENCODER_PROJECTION_DEADBAND_MODE,
            )
        ),
        "--autoencoder-max-ce-deadband",
        str(
            getattr(
                args,
                "autoencoder_max_ce_deadband",
                DEFAULT_AUTOENCODER_MAX_CE_DEADBAND,
            )
        ),
        "--autoencoder-hard-guardrail-metrics",
        str(
            getattr(
                args,
                "autoencoder_hard_guardrail_metrics",
                ",".join(PROJECTION_DEADBAND_DEFAULT_HARD_GUARDRAILS),
            )
        ),
        "--autoencoder-projection-prescreen-mode",
        str(
            getattr(
                args,
                "autoencoder_projection_prescreen_mode",
                DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_MODE,
            )
        ),
        "--autoencoder-projection-prescreen-top-k",
        str(
            getattr(
                args,
                "autoencoder_projection_prescreen_top_k",
                DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_TOP_K,
            )
        ),
        "--autoencoder-projection-periodic-full-search-every-n-cycles",
        str(
            getattr(
                args,
                "autoencoder_projection_periodic_full_search_every_n_cycles",
                DEFAULT_AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES,
            )
        ),
        "--autoencoder-bootstrap-mode",
        str(getattr(args, "autoencoder_bootstrap_mode", "fast")),
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
    if getattr(args, "autoencoder_max_cosine_regression", None) is not None:
        autoencoder_command.extend(
            [
                "--autoencoder-max-cosine-regression",
                str(getattr(args, "autoencoder_max_cosine_regression")),
            ]
        )
    if getattr(args, "sampling_seed", None) is not None and str(
        getattr(args, "sampling_seed")
    ).strip():
        autoencoder_command.extend(
            [
                "--sampling-seed",
                str(getattr(args, "sampling_seed")),
            ]
        )
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
    autoencoder_success: Optional[bool] = None,
    runner_terminated_children: AbstractSet[str],
    stop_requested: bool,
) -> bool:
    """Return whether Codex children finished cleanly for paired-run accounting."""

    if stop_requested:
        return False
    if autoencoder_success is None:
        autoencoder_success = autoencoder_exit_code == 0
    if not codex_exit_codes or not autoencoder_success:
        return False
    return accelerate_supervised_child_group_succeeded(
        codex_exit_codes,
        runner_terminated_child_ids=tuple(runner_terminated_children),
        stop_requested=stop_requested,
        allow_runner_terminated=True,
    )


_PAIRED_AUTOENCODER_MANAGED_STOP_REASONS = frozenset(
    {
        "max_iterations",
        "no_claimed_todos",
        "no_validated_improvement",
        "targets_met",
    }
)


def _paired_autoencoder_health_indicates_managed_stop(
    autoencoder_child_health: Optional[Mapping[str, Any]],
) -> bool:
    """Return whether the LegalIR autoencoder summary reached a useful stop."""

    if not autoencoder_child_health:
        return False
    reason = str(
        autoencoder_child_health.get("autoencoder_latest_stop_reason") or ""
    ).strip().lower()
    try:
        cycles = int(autoencoder_child_health.get("autoencoder_cycles") or 0)
    except (TypeError, ValueError):
        cycles = 0
    final = bool(autoencoder_child_health.get("autoencoder_summary_final", False))
    if cycles <= 0:
        return False
    if reason in _PAIRED_AUTOENCODER_MANAGED_STOP_REASONS:
        return True
    return bool(final and reason.startswith("signal_"))


def _paired_autoencoder_succeeded(
    *,
    autoencoder_run_id: str,
    autoencoder_exit_code: Optional[int],
    autoencoder_child_health: Optional[Mapping[str, Any]] = None,
    runner_terminated_children: AbstractSet[str],
    stop_requested: bool = False,
) -> bool:
    """Return whether the paired autoencoder child reached its own clean stop."""

    runner_terminated = autoencoder_run_id in set(runner_terminated_children)
    if runner_terminated and autoencoder_exit_code == 0:
        return False
    clean_process_stop = accelerate_supervised_child_succeeded(
        child_id=autoencoder_run_id,
        exit_code=autoencoder_exit_code,
        runner_terminated_child_ids=tuple(runner_terminated_children),
        allow_runner_terminated=False,
    )
    if clean_process_stop:
        return True
    if stop_requested:
        return False
    runner_managed_process_stop = accelerate_supervised_child_succeeded(
        child_id=autoencoder_run_id,
        exit_code=autoencoder_exit_code,
        runner_terminated_child_ids=tuple(runner_terminated_children),
        allow_runner_terminated=True,
    )
    return bool(
        runner_managed_process_stop
        and _paired_autoencoder_health_indicates_managed_stop(
            autoencoder_child_health
        )
    )


def _child_summary_latest_stop_reason(summary_path: Path) -> str:
    """Return the latest child stop reason from a Codex/autoencoder summary."""

    try:
        data = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("latest_stop_reason") or data.get("stop_reason") or "")


def _paired_child_exit_should_restart(
    *,
    exit_code: Optional[int],
    latest_stop_reason: str = "",
    restart_count: int,
    restart_limit: int,
    stop_requested: bool = False,
) -> bool:
    """Return whether accelerate-style supervision should replace a dead child."""

    stop_reason = str(latest_stop_reason or "").strip().lower()
    if (
        not stop_requested
        and exit_code == 0
        and stop_reason.startswith("signal_")
        and int(restart_count) < int(restart_limit)
    ):
        return True
    return accelerate_child_exit_should_restart(
        exit_code=exit_code,
        restart_count=restart_count,
        restart_limit=restart_limit,
        stop_requested=stop_requested,
    )


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


def _run_process_group_capture(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Optional[Mapping[str, str]] = None,
    timeout_seconds: float,
) -> Dict[str, Any]:
    """Run a command with a process-group timeout so child workers cannot leak."""
    return dict(
        accelerate_run_process_group_capture(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    )


_PYTEST_FAILURE_LINE_RE = re.compile(r"(?m)^(?:FAILED|ERROR)\s+([^\s]+)")
_PYTEST_BANNER_RE = re.compile(r"(?m)^_+\s+([A-Za-z_][A-Za-z0-9_]*)\s+_+$")
_PYTEST_IN_TEST_RE = re.compile(
    r"(?m)^([^:\n]+\.py):[0-9]+:\s+in\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)
_PYTHON_SYNTAX_LINE_RE = re.compile(
    r'(?m)^\s*File "([^"]+)", line ([0-9]+)|^\s*File ([^,\n]+), line ([0-9]+)'
)


def _codex_validation_text_summary(text: str, *, limit: int = 2000) -> str:
    normalized = _process_text(text)
    return normalized[-max(1, int(limit)) :]


def _codex_validation_failure_details(
    *,
    command: Sequence[str],
    command_index: int,
    status: str,
    exit_code: Optional[int],
    stdout: str,
    stderr: str,
) -> Dict[str, Any]:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    failed_test_ids = list(_PYTEST_FAILURE_LINE_RE.findall(combined))
    banner_names = set(_PYTEST_BANNER_RE.findall(combined))
    for file_path, test_name in _PYTEST_IN_TEST_RE.findall(combined):
        if test_name in banner_names:
            failed_test_ids.append(f"{file_path}::{test_name}")
    failed_tests = sorted(dict.fromkeys(failed_test_ids))
    syntax_locations: List[str] = []
    if "SyntaxError" in combined or "IndentationError" in combined:
        for match in _PYTHON_SYNTAX_LINE_RE.finditer(combined):
            file_path = match.group(1) or match.group(3) or ""
            line_number = match.group(2) or match.group(4) or ""
            if file_path and line_number:
                syntax_locations.append(f"{file_path}:{line_number}")
    syntax_locations = sorted(dict.fromkeys(syntax_locations))
    failure_tokens = [f"pytest:{node_id}" for node_id in failed_tests]
    failure_tokens.extend(f"py_compile:{location}" for location in syntax_locations)
    if status != "passed" and not failure_tokens:
        command_key = shlex.join(str(part) for part in command)
        failure_tokens.append(
            f"command:{command_index}:{command_key}:status:{status}:exit:{exit_code}"
        )
    return {
        "failed_tests": failed_tests,
        "failure_tokens": failure_tokens,
        "syntax_locations": syntax_locations,
        "stderr_tail": _codex_validation_text_summary(stderr),
        "stdout_tail": _codex_validation_text_summary(stdout),
    }


def _codex_apply_validation_failure_tokens(
    validation: Mapping[str, Any],
) -> List[str]:
    tokens: List[str] = []
    for index, command_result in enumerate(validation.get("commands", []) or [], start=1):
        if not isinstance(command_result, Mapping):
            continue
        if str(command_result.get("status") or "") == "passed":
            continue
        command_tokens = [
            str(token)
            for token in command_result.get("failure_tokens", []) or []
            if str(token)
        ]
        if not command_tokens:
            command = [str(part) for part in command_result.get("command", []) or []]
            command_tokens = [
                "command:"
                f"{index}:{shlex.join(command)}:"
                f"status:{command_result.get('status')}:"
                f"exit:{command_result.get('exit_code')}"
            ]
        tokens.extend(command_tokens)
    return sorted(dict.fromkeys(tokens))


def _codex_apply_validation_failure_comparison(
    validation: Mapping[str, Any],
    baseline_validation: Mapping[str, Any],
) -> Dict[str, Any]:
    packet_tokens = set(_codex_apply_validation_failure_tokens(validation))
    baseline_tokens = set(_codex_apply_validation_failure_tokens(baseline_validation))
    shared_tokens = packet_tokens & baseline_tokens
    packet_only_tokens = packet_tokens - baseline_tokens
    baseline_only_tokens = baseline_tokens - packet_tokens
    packet_failed = str(validation.get("status") or "") not in {"passed", "skipped"}
    baseline_failed = str(baseline_validation.get("status") or "") not in {
        "passed",
        "skipped",
    }
    return {
        "baseline_failed": baseline_failed,
        "baseline_failure_tokens": sorted(baseline_tokens),
        "baseline_only_failure_tokens": sorted(baseline_only_tokens),
        "inconclusive_baseline_failed": bool(
            packet_failed and baseline_failed and not packet_only_tokens
        ),
        "packet_failed": packet_failed,
        "packet_failure_tokens": sorted(packet_tokens),
        "packet_only_failure_tokens": sorted(packet_only_tokens),
        "shared_failure_tokens": sorted(shared_tokens),
    }


def _run_codex_apply_validation(
    repo_root: Path,
    packet_dir: Path,
    *,
    validation_commands: Optional[Sequence[Sequence[str]]] = None,
    preflight_python_files: Optional[Sequence[str]] = None,
    timeout_seconds: float = CODEX_APPLY_VALIDATION_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    commands = (
        [list(command) for command in validation_commands]
        if validation_commands is not None
        else _default_codex_apply_validation_commands(repo_root)
    )
    preflight_files = [
        str(path)
        for path in (preflight_python_files or [])
        if str(path).endswith(".py") and (repo_root / str(path)).exists()
    ]
    if preflight_files:
        commands = [[sys.executable, "-m", "py_compile", *preflight_files], *commands]
    if not commands:
        return {"commands": [], "status": "skipped"}

    results: List[Dict[str, Any]] = []
    for index, command in enumerate(commands, start=1):
        stdout_path = packet_dir / f"main-apply-validation-{index}.stdout.log"
        stderr_path = packet_dir / f"main-apply-validation-{index}.stderr.log"
        result = _run_process_group_capture(
            command,
            cwd=repo_root,
            env=_codex_apply_validation_env(),
            timeout_seconds=timeout_seconds,
        )
        stdout_text = str(result.get("stdout") or "")
        stderr_text = str(result.get("stderr") or "")
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")
        timed_out = str(result.get("status") or "") == "timeout"
        exit_code = None if timed_out else int(result.get("exit_code") or 0)
        status = "timeout" if timed_out else "passed" if exit_code == 0 else "failed"
        command_result = {
            "command": command,
            "duration_seconds": float(result.get("duration_seconds") or 0.0),
            "exit_code": exit_code,
            "status": status,
            "stderr_path": str(stderr_path),
            "stdout_path": str(stdout_path),
        }
        if timed_out:
            command_result["timeout_seconds"] = float(timeout_seconds)
        command_result.update(
            _codex_validation_failure_details(
                command=command,
                command_index=index,
                status=status,
                exit_code=exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
            )
        )
        results.append(command_result)
        if command_result["status"] != "passed":
            return {
                "commands": results,
                "failure_tokens": _codex_apply_validation_failure_tokens(
                    {"commands": results}
                ),
                "status": command_result["status"],
            }
    return {"commands": results, "failure_tokens": [], "status": "passed"}


def _codex_packet_metric_sample_payloads(
    packet: Mapping[str, Any],
    *,
    max_samples: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return unique legal sample payloads carried by claimed TODO metadata."""
    sample_limit = (
        _env_int(
            "IPFS_DATASETS_CODEX_TARGET_METRIC_MAX_SAMPLES",
            CODEX_TARGET_METRIC_MAX_SAMPLES,
            minimum=0,
        )
        if max_samples is None
        else max(0, int(max_samples))
    )
    if sample_limit <= 0:
        return []
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
            if len(payloads) >= sample_limit:
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


def _codex_target_metric_bridge_adapter_names(
    target_metrics: Sequence[str],
) -> List[str]:
    """Return the cheapest bridge adapter set needed for target metric checks."""

    mode = str(
        os.environ.get("IPFS_DATASETS_CODEX_TARGET_METRIC_BRIDGE_MODE") or "targeted"
    ).strip().lower()
    if mode in _FALSE_ENV_VALUES:
        return []
    if mode in {"all", "full"}:
        return list(DEFAULT_LEGAL_IR_BRIDGE_NAMES)

    explicit = str(
        os.environ.get("IPFS_DATASETS_CODEX_TARGET_METRIC_BRIDGE_ADAPTERS") or ""
    ).strip()
    if explicit:
        return [
            name
            for name in dict.fromkeys(part.strip() for part in explicit.split(","))
            if name and name.lower() not in _FALSE_ENV_VALUES
        ]

    requested: List[str] = []
    legal_ir_view_requested = False
    for metric in target_metrics:
        normalized = str(metric or "").strip().lower()
        if not normalized:
            continue
        if normalized.startswith("legal_ir_multiview_"):
            return list(DEFAULT_LEGAL_IR_BRIDGE_NAMES)
        if normalized.startswith("legal_ir_view_"):
            legal_ir_view_requested = True
            continue
        if normalized.startswith(("deontic_", "norm_")):
            requested.append("deontic_norms")
            continue
        if normalized.startswith(("tdfol_", "fol_", "first_order_")):
            requested.append("fol_tdfol")
            continue
        if normalized.startswith(("cec_", "dcec_", "event_calculus_")):
            requested.append("cec_dcec")
            continue
        if normalized.startswith(("zkp_", "zero_knowledge_", "attestation_")):
            requested.append("zkp_attestation")
            continue
        if "prover" in normalized or normalized.startswith("proof_"):
            requested.append("external_prover_router")
            continue
        if normalized.startswith(("kg_", "graph_", "knowledge_graph_")):
            requested.extend(("modal_frame_logic", "deontic_norms"))
            continue

    if legal_ir_view_requested and not requested:
        requested.extend(DEFAULT_LEGAL_IR_BRIDGE_NAMES)

    requested_set = set(requested)
    return [name for name in DEFAULT_LEGAL_IR_BRIDGE_NAMES if name in requested_set]


def _codex_packet_target_metric_snapshot(
    packet: Mapping[str, Any],
    repo_root: Path,
    *,
    timeout_seconds: Optional[float] = None,
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
metrics = {}
for key, value in compiler.items():
    if isinstance(value, (int, float)):
        metrics[str(key)] = float(value)
if "cosine_similarity" in metrics:
    metrics["embedding_cosine_similarity"] = metrics["cosine_similarity"]
target_metrics = list(payload.get("target_metrics") or [])
bridge_names = [
    str(name)
    for name in payload.get("bridge_names", []) or []
    if str(name).strip()
]
bridge = {}
if bridge_names:
    bridge = bridge_ir_metric_block(
        samples,
        bridge_names,
        evaluate_provers=False,
        parallel_workers=min(4, max(1, len(samples))),
    )
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
    if (
        "legal_ir_view_cross_entropy_loss" not in metrics
        and "legal_ir_multiview_cross_entropy_loss" in metrics
    ):
        metrics["legal_ir_view_cross_entropy_loss"] = float(
            metrics["legal_ir_multiview_cross_entropy_loss"]
        )
    for adapter_name, adapter_block in dict(bridge.get("adapters", {}) or {}).items():
        if not isinstance(adapter_block, dict):
            continue
        for key, value in adapter_block.items():
            if isinstance(value, (int, float)):
                metrics[str(key)] = float(value)
                metrics[f"{adapter_name}.{key}"] = float(value)
selected = {
    metric: metrics[metric]
    for metric in target_metrics
    if metric in metrics
}
print(json.dumps({
    "compiler": compiler,
    "metric_cache": {
        "bridge_persistent_cache_hit": bool(bridge.get("persistent_cache_hit")),
        "bridge_skipped": not bool(bridge_names),
        "compiler_persistent_cache_hit": bool(compiler.get("persistent_cache_hit")),
    },
    "metric_count": len(selected),
    "metrics": selected,
    "sample_count": len(samples),
    "status": "measured",
    "target_bridge_names": bridge_names,
    "target_metrics": target_metrics,
}, sort_keys=True))
    '''
    payload = {
        "bridge_names": _codex_target_metric_bridge_adapter_names(target_metrics),
        "samples": sample_payloads,
        "target_metrics": target_metrics,
    }
    timeout = (
        _env_float(
            "IPFS_DATASETS_CODEX_TARGET_METRIC_TIMEOUT_SECONDS",
            CODEX_TARGET_METRIC_TIMEOUT_SECONDS,
            minimum=1.0,
        )
        if timeout_seconds is None
        else max(1.0, float(timeout_seconds))
    )
    env = _codex_apply_validation_env()
    metric_cache_dir = _metric_disk_cache_dir()
    if metric_cache_dir is not None:
        env.setdefault(LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV, str(metric_cache_dir))
    result = accelerate_run_process_group_capture(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        input_text=json.dumps(payload, ensure_ascii=True),
        timeout_seconds=timeout,
    )
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    result_status = str(result.get("status") or "")
    if result_status == "failed":
        return {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "failed",
            "stderr_tail": stderr[-500:],
            "stdout_tail": stdout[-500:],
            "target_metrics": target_metrics,
        }
    if result_status == "timeout":
        return {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "timeout",
            "stderr_tail": stderr[-500:],
            "stdout_tail": stdout[-500:],
            "target_metrics": target_metrics,
            "timeout_seconds": float(timeout),
        }
    returncode = result.get("exit_code")
    if returncode != 0:
        return {
            "exit_code": returncode,
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "failed",
            "stderr_tail": stderr[-500:],
            "stdout_tail": stdout[-500:],
            "target_metrics": target_metrics,
        }
    try:
        stdout_lines = [line for line in (stdout or "").splitlines() if line.strip()]
        snapshot = json.loads(stdout_lines[-1] if stdout_lines else "")
    except json.JSONDecodeError:
        return {
            "exit_code": returncode,
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payloads),
            "status": "invalid_json",
            "stderr_tail": stderr[-500:],
            "stdout_tail": stdout[-500:],
            "target_metrics": target_metrics,
        }
    snapshot["stderr_tail"] = stderr[-500:]
    snapshot["timeout_seconds"] = float(timeout)
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
    validation_timeout_seconds: float = CODEX_APPLY_VALIDATION_TIMEOUT_SECONDS,
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
        preflight_python_files=target_files,
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
                preflight_python_files=target_files,
                timeout_seconds=validation_timeout_seconds,
            )
        updated["main_apply_baseline_validation"] = baseline_validation
        validation_comparison = _codex_apply_validation_failure_comparison(
            validation,
            baseline_validation,
        )
        updated["main_apply_validation_comparison"] = validation_comparison
        if baseline_validation["status"] not in {"passed", "skipped"}:
            if (
                rollback.returncode == 0
                and validation_comparison.get("inconclusive_baseline_failed")
            ):
                reapply = _run_git_apply_stdin(source_repo_root, diff_content)
                updated["main_apply_reapply_after_baseline_validation"] = {
                    "exit_code": reapply.returncode,
                    "stderr_tail": (reapply.stderr or "")[-500:],
                    "stdout_tail": (reapply.stdout or "")[-500:],
                }
                if reapply.returncode == 0:
                    updated["main_apply_validation_gate"] = (
                        "inconclusive_baseline_failed"
                    )
                    updated["main_apply_baseline_failure_accepted"] = True
                else:
                    patch_path = _save_codex_packet_diff_patch(
                        updated,
                        diff_content=diff_content,
                        reason="baseline-validation-reapply-failed",
                    )
                    updated["patch_path"] = (
                        str(patch_path) if patch_path is not None else None
                    )
                    updated["patch_status"] = (
                        "main_apply_baseline_validation_failed_reapply_failed"
                    )
                    updated["patch_error"] = (
                        "baseline validation failed and reapplying the packet "
                        "after rollback failed"
                    )
                    updated["main_apply_error"] = updated["patch_error"]
                    _save_packet_if_possible(updated, packet_path)
                    return updated
            else:
                patch_path = _save_codex_packet_diff_patch(
                    updated,
                    diff_content=diff_content,
                    reason="validation-failed",
                )
                updated["patch_path"] = (
                    str(patch_path) if patch_path is not None else None
                )
                updated["patch_status"] = (
                    "main_apply_baseline_validation_failed_rolled_back"
                    if rollback.returncode == 0
                    else "main_apply_baseline_validation_failed_rollback_failed"
                )
                updated["patch_error"] = (
                    f"baseline validation {baseline_validation['status']} "
                    f"after packet validation {validation['status']}"
                )
                updated["main_apply_error"] = updated["patch_error"]
                _save_packet_if_possible(updated, packet_path)
                return updated
        else:
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

    target_metric_after = (
        _codex_packet_target_metric_snapshot(
            updated,
            source_repo_root,
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
    target_metric_status = str(target_metric_validation.get("status") or "").strip().lower()
    if target_metric_status == "regressed":
        rollback = _run_git_apply_stdin(source_repo_root, diff_content, "-R")
        updated["main_apply_rollback"] = {
            "exit_code": rollback.returncode,
            "stderr_tail": (rollback.stderr or "")[-500:],
            "stdout_tail": (rollback.stdout or "")[-500:],
        }
        rollback_reason = "target-metric-regression"
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason=rollback_reason,
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        updated["patch_status"] = (
            "main_apply_target_metric_regression_rolled_back"
            if rollback.returncode == 0
            else "main_apply_target_metric_regression_rollback_failed"
        )
        updated["patch_error"] = rollback_reason.replace("-", " ")
        updated["main_apply_error"] = updated["patch_error"]
        _save_packet_if_possible(updated, packet_path)
        return updated
    if target_metric_status not in {"passed", "skipped"}:
        updated["main_apply_target_metric_gate"] = "diagnostic_unavailable"

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


def _codex_main_apply_lock_timeout_packet(
    packet: Mapping[str, Any],
    exc: BaseException,
) -> Dict[str, Any]:
    """Record a bounded apply-lock wait as transient and keep a rescue patch."""
    packet_path_value = packet.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    try:
        updated = refresh_codex_work_packet_patch(packet)
    except (OSError, RuntimeError, subprocess.SubprocessError, TypeError, ValueError) as patch_exc:
        updated = dict(packet)
        updated["main_apply_patch_refresh_error"] = str(patch_exc)
    updated["codex_apply_mode"] = "apply_to_main"
    updated["main_apply_error"] = str(exc)
    updated["main_apply_status"] = "lock_timeout"
    updated["patch_error"] = str(exc)
    updated["patch_status"] = "main_apply_lock_timeout"
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
    main_apply_lock_timeout_seconds: Optional[float] = None,
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
        try:
            with codex_main_apply_lock(
                updated,
                timeout_seconds=main_apply_lock_timeout_seconds,
            ):
                refreshed = apply_codex_worktree_changes_to_main(
                    updated,
                    commit_mode=commit_mode,
                    merge_repair_attempts=merge_repair_attempts,
                    merge_repair_mode=merge_repair_mode,
                    validation_commands=validation_commands,
                    validation_timeout_seconds=validation_timeout_seconds,
                )
        except TimeoutError as exc:
            refreshed = _codex_main_apply_lock_timeout_packet(updated, exc)
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
            try:
                with codex_main_apply_lock(
                    refreshed,
                    timeout_seconds=main_apply_lock_timeout_seconds,
                ):
                    refreshed = apply_codex_worktree_changes_to_main(
                        refreshed,
                        commit_mode=commit_mode,
                        merge_repair_attempts=merge_repair_attempts,
                        merge_repair_mode=merge_repair_mode,
                        validation_commands=validation_commands,
                        validation_timeout_seconds=validation_timeout_seconds,
                    )
            except TimeoutError as exc:
                refreshed = _codex_main_apply_lock_timeout_packet(refreshed, exc)
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
    accelerate_terminate_process_group(process, signum)


def _terminate_process_with_grace(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float,
    kill_wait_seconds: float = 5.0,
) -> Optional[int]:
    result = accelerate_terminate_process_with_grace(
        process,
        grace_seconds=grace_seconds,
        kill_wait_seconds=kill_wait_seconds,
    )
    return result.final_exit_code


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
    if patch_status == "main_apply_lock_timeout" or main_apply_status == "lock_timeout":
        return True
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
    baseline_failure_accepted = bool(packet.get("main_apply_baseline_failure_accepted"))
    main_validation_status = (
        "passed"
        if baseline_failure_accepted
        else main_validation.get("status")
    )
    failed_command: Dict[str, Any] = {}
    for command_result in main_validation.get("commands", []) or []:
        if not isinstance(command_result, Mapping):
            continue
        if str(command_result.get("status") or "") != "passed":
            failed_command = dict(command_result)
            break
    validation_failure_tokens = [
        str(token)
        for token in main_validation.get("failure_tokens", []) or []
        if str(token)
    ]
    if not validation_failure_tokens and failed_command:
        validation_failure_tokens = [
            str(token)
            for token in failed_command.get("failure_tokens", []) or []
            if str(token)
        ]
    return {
        "baseline_failure_accepted": baseline_failure_accepted,
        "baseline_status": baseline_validation.get("status"),
        "main_apply_validation_failed_command": failed_command.get("command"),
        "main_apply_validation_failed_tests": list(
            failed_command.get("failed_tests", []) or []
        )[:16],
        "main_apply_validation_failure_tokens": validation_failure_tokens[:32],
        "main_apply_validation_stderr_tail": failed_command.get("stderr_tail"),
        "main_apply_validation_stdout_tail": failed_command.get("stdout_tail"),
        "main_apply_validation_syntax_locations": list(
            failed_command.get("syntax_locations", []) or []
        )[:16],
        "main_apply_validation_gate": packet.get("main_apply_validation_gate"),
        "main_apply_validation_status": main_validation_status,
        "main_apply_status": packet.get("main_apply_status"),
        "metric_deltas": dict(packet.get("metric_deltas", {}) or {}),
        "patch_status": packet.get("patch_status"),
        "regressed_metrics": list(target_metric_validation.get("regressed_metrics", []) or []),
        "status": main_validation_status
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
        "Before finishing, run py_compile on any touched Python files or the closest package/test modules.",
        "Run the smallest relevant tests you can before finishing.",
        "Preserve U.S. Code catchline and heading invariants: semicolon-split headings such as `Canals and appurtenant structures; transfer of title; power development` must retain both individual heading spans and the coalesced catchline where existing tests expect them.",
        "Do not weaken, delete, rename, or bypass existing modal codec heading/catchline tests to make a patch pass.",
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
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        dir=str(summary_path.parent),
        encoding="utf-8",
        prefix=f".{summary_path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, summary_path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def path_size_report(path: Path) -> Dict[str, Any]:
    """Return compact file-size telemetry without failing the daemon."""
    try:
        stat = path.stat()
    except OSError:
        return {
            "exists": False,
            "path": str(path),
            "size_bytes": 0,
            "size_mb": 0.0,
        }
    size_bytes = int(stat.st_size)
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024.0 / 1024.0, 3),
    }


def autoencoder_state_telemetry(
    state: ModalAutoencoderTrainingState,
    *,
    state_path: Path,
) -> Dict[str, Any]:
    telemetry = state.telemetry()
    telemetry["low_rank_shadow"] = state.low_rank_shadow_report(
        rank=MODAL_AUTOENCODER_LOW_RANK_DEFAULT_RANK,
        max_vectors=128,
    )
    telemetry["state_file"] = path_size_report(state_path)
    telemetry["low_rank_sidecar"] = autoencoder_low_rank_sidecar_report(
        state,
        state_path=state_path,
    )
    return telemetry


def autoencoder_low_rank_load_report(
    state: ModalAutoencoderTrainingState,
    *,
    state_path: Path,
) -> Dict[str, Any]:
    sidecar_path = ModalAutoencoderTrainingState.low_rank_shadow_sidecar_path(
        state_path
    )
    if not _env_bool(AUTOENCODER_LOW_RANK_LOAD_ENV, False):
        return {
            "enabled": False,
            "overwrite": False,
            "path": str(sidecar_path),
            "reason": "disabled",
        }
    overwrite = _env_bool(AUTOENCODER_LOW_RANK_LOAD_OVERWRITE_ENV, False)
    try:
        report = state.hydrate_low_rank_shadow_json(
            sidecar_path,
            overwrite=overwrite,
        )
    except Exception as exc:
        return {
            "enabled": True,
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "overwrite": overwrite,
            "path": str(sidecar_path),
            "status": "failed",
        }
    report = dict(report)
    report["enabled"] = True
    report["overwrite"] = overwrite
    report.setdefault("path", str(sidecar_path))
    return report


def autoencoder_low_rank_sidecar_report(
    state: ModalAutoencoderTrainingState,
    *,
    state_path: Path,
) -> Dict[str, Any]:
    rank = _env_int(
        AUTOENCODER_LOW_RANK_SIDECAR_RANK_ENV,
        MODAL_AUTOENCODER_LOW_RANK_DEFAULT_RANK,
        minimum=1,
    )
    max_vectors = _env_int(
        AUTOENCODER_LOW_RANK_SIDECAR_MAX_VECTORS_ENV,
        0,
        minimum=0,
    )
    sidecar_path = ModalAutoencoderTrainingState.low_rank_shadow_sidecar_path(
        state_path
    )
    if max_vectors <= 0:
        return {
            "enabled": False,
            "max_vectors": 0,
            "path": str(sidecar_path),
            "rank": rank,
            "reason": "disabled",
        }
    try:
        payload = state.save_low_rank_shadow_json(
            sidecar_path,
            rank=rank,
            max_vectors=max_vectors,
        )
    except Exception as exc:
        return {
            "enabled": True,
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "max_vectors": max_vectors,
            "path": str(sidecar_path),
            "rank": rank,
            "status": "failed",
        }
    return {
        "complete": bool(payload.get("complete", False)),
        "enabled": True,
        "file": path_size_report(sidecar_path),
        "max_vectors": max_vectors,
        "path": str(sidecar_path),
        "rank": rank,
        "status": "saved",
        "vector_entry_count": int(payload.get("vector_entry_count", 0) or 0),
    }


def _read_meminfo_kb() -> Dict[str, int]:
    meminfo: Dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return meminfo
    for line in lines:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        try:
            meminfo[key] = int(parts[0])
        except ValueError:
            continue
    return meminfo


def paired_resource_health() -> Dict[str, Any]:
    """Return lightweight host memory/CPU facts for paired-run admission control."""

    meminfo = _read_meminfo_kb()

    def gib(key: str) -> Optional[float]:
        value = meminfo.get(key)
        if value is None:
            return None
        return round(float(value) / 1024.0 / 1024.0, 3)

    return {
        "cpu_count": os.cpu_count() or 1,
        "memory_available_gb": gib("MemAvailable"),
        "memory_free_gb": gib("MemFree"),
        "memory_total_gb": gib("MemTotal"),
        "swap_free_gb": gib("SwapFree"),
        "swap_total_gb": gib("SwapTotal"),
    }


def _resource_float(
    resource_health: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    value = resource_health.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return float(default)


def _round_robin_codex_children(
    codex_children: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> List[Mapping[str, Any]]:
    """Keep scope coverage when the resource guard trims a parallel Codex pool."""

    if limit <= 0:
        return []
    if len(codex_children) <= limit:
        return [dict(child) for child in codex_children]

    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    scope_order: List[str] = []
    for child in codex_children:
        scope = str(child.get("scope") or "all")
        if scope not in grouped:
            grouped[scope] = []
            scope_order.append(scope)
        grouped[scope].append(child)

    selected: List[Mapping[str, Any]] = []
    while len(selected) < limit:
        added = False
        for scope in scope_order:
            if len(selected) >= limit:
                break
            items = grouped.get(scope) or []
            if not items:
                continue
            selected.append(dict(items.pop(0)))
            added = True
        if not added:
            break
    return selected


def paired_codex_worker_resource_plan(
    args: argparse.Namespace,
    *,
    requested_workers: int,
    resource_health: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the effective Codex worker budget for a paired run."""

    requested_workers = max(0, int(requested_workers))
    health = dict(resource_health or paired_resource_health())
    mode = str(getattr(args, "paired_resource_guard", "auto") or "auto").strip().lower()
    explicit_max = max(0, int(getattr(args, "paired_codex_max_workers", 0) or 0))
    cpu_count = max(1, int(health.get("cpu_count") or os.cpu_count() or 1))
    per_worker_gb = max(
        0.25,
        float(getattr(args, "paired_codex_worker_memory_gb", 2.0) or 2.0),
    )
    reserved_gb = max(
        0.0,
        float(getattr(args, "paired_reserved_memory_gb", 24.0) or 0.0),
    )
    available_gb = _resource_float(health, "memory_available_gb", reserved_gb)
    min_swap_free_gb = max(
        0.0,
        float(getattr(args, "paired_min_swap_free_gb", 1.0) or 0.0),
    )
    swap_free_gb = _resource_float(health, "swap_free_gb", min_swap_free_gb)
    swap_pressure = bool(min_swap_free_gb > 0.0 and swap_free_gb < min_swap_free_gb)
    cpu_cap = max(1, min(12, cpu_count - 2 if cpu_count > 2 else 1))
    memory_cap = max(1, int((available_gb - reserved_gb) // per_worker_gb))
    swap_cap = cpu_cap
    if swap_pressure:
        swap_cap = max(1, min(cpu_cap, cpu_count // 2 if cpu_count > 1 else 1, 8))

    if mode == "off":
        effective_workers = requested_workers
        reason = "resource_guard_off"
    elif mode == "fixed" and explicit_max > 0:
        effective_workers = min(requested_workers, explicit_max)
        reason = "fixed_max_workers"
    else:
        auto_cap = max(1, min(cpu_cap, memory_cap, swap_cap))
        if explicit_max > 0:
            auto_cap = min(auto_cap, explicit_max)
        effective_workers = min(requested_workers, auto_cap)
        reason = "auto_cpu_memory_swap_cap" if swap_pressure else "auto_cpu_memory_cap"

    return {
        "available_memory_gb": available_gb,
        "cpu_cap": cpu_cap,
        "cpu_count": cpu_count,
        "effective_workers": max(0, int(effective_workers)),
        "explicit_max_workers": explicit_max,
        "memory_cap": memory_cap,
        "mode": mode,
        "per_worker_memory_gb": per_worker_gb,
        "reason": reason,
        "requested_workers": requested_workers,
        "reserved_memory_gb": reserved_gb,
        "resource_health": health,
        "swap_cap": swap_cap,
        "swap_free_gb": swap_free_gb,
        "swap_pressure": swap_pressure,
        "min_swap_free_gb": min_swap_free_gb,
    }


def _paired_resource_pressure(
    args: argparse.Namespace,
    *,
    resource_health: Optional[Mapping[str, Any]] = None,
    role: str = "codex",
) -> tuple[bool, Dict[str, Any]]:
    health = dict(resource_health or paired_resource_health())
    normalized_role = str(role or "codex").strip().lower()
    min_available_gb = max(
        0.0,
        float(getattr(args, "paired_min_available_memory_gb", 12.0) or 0.0),
    )
    available_gb = _resource_float(health, "memory_available_gb", min_available_gb)
    memory_pressure = bool(
        min_available_gb > 0.0 and available_gb < min_available_gb
    )
    min_swap_free_gb = max(
        0.0,
        float(getattr(args, "paired_min_swap_free_gb", 1.0) or 0.0),
    )
    swap_free_gb = _resource_float(health, "swap_free_gb", min_swap_free_gb)
    swap_pressure = bool(min_swap_free_gb > 0.0 and swap_free_gb < min_swap_free_gb)
    swap_blocks_restart = bool(normalized_role != "autoencoder")
    pressure = memory_pressure or (swap_pressure and swap_blocks_restart)
    report = {
        "available_memory_gb": available_gb,
        "memory_pressure": memory_pressure,
        "min_available_memory_gb": min_available_gb,
        "min_swap_free_gb": min_swap_free_gb,
        "resource_pressure": pressure,
        "resource_health": health,
        "restart_role": normalized_role,
        "swap_free_gb": swap_free_gb,
        "swap_blocks_restart": swap_blocks_restart,
        "swap_pressure": swap_pressure,
    }
    return pressure, report


def paired_codex_child_env(args: argparse.Namespace) -> Dict[str, str]:
    """Return environment overrides for paired Codex workers."""

    if not bool(getattr(args, "paired_codex_disable_cuda", True)):
        return {}
    return {
        "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_CODEX_TASK_EMBEDDINGS_DEVICE": "cpu",
        "NVIDIA_VISIBLE_DEVICES": "none",
    }


def _clamp_nested_bridge_adapter_parallelism(
    *,
    bridge_parallel_workers: int,
    sample_parallel_workers: Optional[int] = None,
    adapter_count: Optional[int] = None,
    max_nested_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """Budget nested sample-worker x adapter-worker LegalIR evaluation.

    The daemon has two useful levels of parallelism: samples evaluated by the
    autoencoder, and bridge adapters evaluated inside each sample.  The old
    guard collapsed adapter parallelism to one whenever sample parallelism was
    enabled, which protected the host but also serialized small metric batches.
    This version keeps the product bounded while still allowing adapter-level
    parallelism for small sampled metric windows.
    """

    sample_workers = max(
        1,
        int(
            sample_parallel_workers
            if sample_parallel_workers is not None
            else bridge_parallel_workers
        ),
    )
    adapter_limit = max(1, int(adapter_count or 1))
    previous = os.environ.get("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "").strip()
    raw_budget = os.environ.get("IPFS_DATASETS_LEGAL_IR_NESTED_WORKER_BUDGET", "").strip()
    if max_nested_workers is None and raw_budget:
        try:
            max_nested_workers = int(raw_budget)
        except ValueError:
            max_nested_workers = None
    nested_budget = max(1, int(max_nested_workers or bridge_parallel_workers or 1))
    if previous:
        try:
            requested_adapter_workers = int(previous)
        except ValueError:
            requested_adapter_workers = 1
    else:
        requested_adapter_workers = max(
            1,
            min(
                adapter_limit,
                nested_budget,
                bridge_parallel_workers,
            ),
        )
    adapter_budget = max(1, nested_budget // sample_workers)
    adapter_workers = max(
        1,
        min(
            requested_adapter_workers,
            adapter_limit,
            adapter_budget,
        ),
    )
    clamped = adapter_workers != requested_adapter_workers
    os.environ["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] = str(adapter_workers)
    return {
        "adapter_count": adapter_limit,
        "adapter_worker_budget": adapter_budget,
        "bridge_parallel_workers": int(bridge_parallel_workers),
        "clamped": clamped,
        "effective_adapter_workers": adapter_workers,
        "estimated_nested_workers": sample_workers * adapter_workers,
        "nested_worker_budget": nested_budget,
        "previous_adapter_workers": previous,
        "requested_adapter_workers": requested_adapter_workers,
        "sample_parallel_workers": sample_workers,
    }


def _sampling_seed_for_args(args: argparse.Namespace) -> tuple[int, str]:
    raw_seed = getattr(args, "sampling_seed", None)
    if raw_seed is None or str(raw_seed).strip() == "":
        seed_source = str(args.run_id)
    else:
        seed_source = str(raw_seed).strip()
    try:
        seed = int(seed_source, 0)
    except ValueError:
        seed = int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:12], 16)
    return seed, seed_source


def initial_summary(args: argparse.Namespace, *, log_path: Path, queue_path: Path, state_path: Path) -> Dict[str, Any]:
    seed, seed_source = _sampling_seed_for_args(args)
    return {
        "active_cycle_phase_timings": {},
        "autoencoder_architecture_version": MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
        "autoencoder_low_rank_state_schema_version": (
            MODAL_AUTOENCODER_LOW_RANK_STATE_SCHEMA_VERSION
        ),
        "autoencoder_state_schema_version": MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
        "best_validation_ce": 1.0e12,
        "best_validation_cosine": -1.0,
        "best_validation_ir_ce": 1.0e12,
        "best_validation_ir_cosine": -1.0,
        "best_validation_ir_guided_ce": 1.0e12,
        "best_validation_ir_guided_ce_excess": 1.0e12,
        "best_validation_ir_guided_cosine": -1.0,
        "best_validation_ir_guided_source_copy_reward_hack_penalty": 1.0e12,
        "best_validation_ir_reconstruction": 1.0e12,
        "best_validation_ir_source_copy_loss": 1.0e12,
        "best_validation_ir_source_decompiled_text_embedding_cosine_loss": 1.0e12,
        "best_validation_ir_source_decompiled_text_token_loss": 1.0e12,
        "best_validation_ir_structural_text_reconstruction": 1.0e12,
        "best_validation_ir_text_reconstruction": 1.0e12,
        "best_validation_learned_ir_family_ce_excess": 1.0e12,
        "best_validation_learned_ir_view_ce": 1.0e12,
        "best_validation_learned_ir_view_cosine": -1.0,
        "best_validation_learned_ir_worst_family_ce_excess": 1.0e12,
        "best_validation_learned_ir_worst_family_cosine_gap": 1.0e12,
        "best_validation_reconstruction": 1.0e12,
        "best_validation_logic_bridge_acceptance": -1.0,
        "best_validation_logic_bridge_proof_failure_ratio": 1.0e12,
        "best_validation_logic_bridge_total_loss": 1.0e12,
        "bridge_evaluate_provers": bool(
            getattr(
                args,
                "bridge_evaluate_provers",
                DEFAULT_BRIDGE_EVALUATE_PROVERS,
            )
        ),
        "bridge_loss_adapters": bridge_loss_adapter_names(args),
        "bridge_loss_failures": 0,
        "bridge_loss_samples": 0,
        "bridge_loss_signals": 0,
        "bridge_metric_failures": 0,
        "cycles": 0,
        "codex_program_synthesis_execution_mode": "queued_for_external_codex_worker",
        "dataset_id": HF_USCODE_DATASET_ID,
        "embedding_target_report": {
            "embedding_model": "mock:stable-sha256",
            "enabled": False,
            "mode": str(getattr(args, "uscode_embeddings_mode", "auto")),
            "path": str(
                getattr(args, "uscode_embeddings_path", USCODE_EMBEDDINGS_PARQUET)
            ),
        },
        "final": False,
        "laws_path": USCODE_LAWS_PARQUET,
        "log_path": str(log_path),
        "loop_role": getattr(args, "loop_role", "autoencoder"),
        "metric_failures": 0,
        "metric_schema_version": USCODE_DAEMON_METRIC_SCHEMA_VERSION,
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
        "rollout_stage": USCODE_DAEMON_ROLLOUT_STAGE,
        "seed": seed,
        "sampling_seed_source": seed_source,
        "started_at": utc_now(),
        "state_path": str(state_path),
        "test_failures": 0,
        "train_ce_improved_cycles": 0,
        "train_cosine_improved_cycles": 0,
        "uscode_embeddings_mode": str(getattr(args, "uscode_embeddings_mode", "auto")),
        "uscode_embeddings_path": str(
            getattr(args, "uscode_embeddings_path", USCODE_EMBEDDINGS_PARQUET)
        ),
        "validation_ce_improved_cycles": 0,
        "validation_cosine_improved_cycles": 0,
        "latest_autoencoder_state_telemetry": {},
        "latest_cycle_phase_timings": {},
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
        scale *= 0.85 ** float(plateau_streak - 2)
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
        "--sampling-seed",
        default=None,
        help=(
            "Optional integer or string seed for train/validation sampling. "
            "When omitted, the run id is used as before. Hparam sweeps should "
            "share one sampling seed across trials so configs see comparable rows."
        ),
    )
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
        default=DEFAULT_VALIDATION_CANARY_COUNT,
        help=(
            "Sample this many fixed holdout rows once per run and use them for "
            "autoencoder acceptance so validation deltas are comparable across cycles. "
            "Zero keeps the prior rotating-validation behavior."
        ),
    )
    parser.add_argument(
        "--validation-canary-indices",
        default="",
        help=(
            "Optional comma-separated U.S. Code row indices to reuse as the "
            "fixed validation canary set. This makes hyperparameter trials "
            "directly comparable on IR and autoencoder metrics."
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
    parser.add_argument(
        "--compiler-ir-metric-max-sample-text-chars",
        type=int,
        default=_env_int(
            COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS_ENV,
            DEFAULT_COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS,
            minimum=0,
        ),
        help=(
            "Skip deterministic compiler/IR metric samples longer than this many "
            "characters. This does not change autoencoder train/validation "
            "sampling. Zero disables the metric-only text cap."
        ),
    )
    parser.add_argument(
        "--compiler-ir-metric-text-policy",
        choices=COMPILER_IR_METRIC_TEXT_POLICIES,
        default=os.environ.get(
            COMPILER_IR_METRIC_TEXT_POLICY_ENV,
            DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY,
        ),
        help=(
            "How deterministic compiler/IR metrics handle samples above "
            "--compiler-ir-metric-max-sample-text-chars. Use 'skip' for the "
            "legacy full-text-only behavior, or 'truncate' to score a bounded "
            "metric prefix with a metric-only sample id."
        ),
    )
    parser.add_argument(
        "--compiler-ir-metric-sample-timeout-seconds",
        type=float,
        default=_env_float(
            COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS_ENV,
            DEFAULT_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS,
            minimum=0.0,
        ),
        help=(
            "Per-sample wall-clock timeout for deterministic compiler/IR metric "
            "encoding. Timed-out samples are skipped and reported. Zero disables "
            "the timeout."
        ),
    )
    parser.add_argument(
        "--compiler-ir-train-mode",
        choices=("every_cycle", "periodic", "off"),
        default=os.environ.get(
            COMPILER_IR_TRAIN_MODE_ENV,
            DEFAULT_COMPILER_IR_TRAIN_MODE,
        ),
        help=(
            "When to run unguided compiler-IR metrics on train samples. "
            "Validation metrics always run because they drive hparam scoring and "
            "best-run tracking."
        ),
    )
    parser.add_argument(
        "--compiler-ir-train-every-n-cycles",
        type=int,
        default=_env_int(
            COMPILER_IR_TRAIN_EVERY_N_CYCLES_ENV,
            DEFAULT_COMPILER_IR_TRAIN_EVERY_N_CYCLES,
            minimum=1,
        ),
        help=(
            "Cycle cadence for --compiler-ir-train-mode periodic. Ignored for "
            "every_cycle and off."
        ),
    )
    parser.add_argument(
        "--compiler-ir-guided-train-mode",
        choices=("every_cycle", "periodic", "off"),
        default=os.environ.get(
            COMPILER_IR_GUIDED_TRAIN_MODE_ENV,
            DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE,
        ),
        help=(
            "When to run guided compiler-IR metrics on train samples. Guided "
            "validation always runs because it feeds the guidance canary; train "
            "metrics are diagnostic and can be disabled for faster sweeps."
        ),
    )
    parser.add_argument(
        "--compiler-ir-guided-train-every-n-cycles",
        type=int,
        default=_env_int(
            COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES_ENV,
            DEFAULT_COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES,
            minimum=1,
        ),
        help=(
            "Cycle cadence for --compiler-ir-guided-train-mode periodic. Ignored "
            "for every_cycle and off."
        ),
    )
    parser.add_argument(
        "--autoencoder-before-train-eval-mode",
        choices=("every_cycle", "periodic", "off"),
        default=os.environ.get(
            AUTOENCODER_BEFORE_TRAIN_EVAL_MODE_ENV,
            DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE,
        ),
        help=(
            "When to run the diagnostic before-train autoencoder pass. Validation "
            "still runs every cycle; after-train metrics still provide the train "
            "snapshot."
        ),
    )
    parser.add_argument(
        "--autoencoder-before-train-eval-every-n-cycles",
        type=int,
        default=_env_int(
            AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES_ENV,
            DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES,
            minimum=1,
        ),
        help=(
            "Cycle cadence for --autoencoder-before-train-eval-mode periodic. "
            "Ignored for every_cycle and off."
        ),
    )
    parser.add_argument(
        "--autoencoder-sample-memory-probe-mode",
        choices=("every_cycle", "periodic", "off"),
        default=os.environ.get(
            AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE_ENV,
            DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE,
        ),
        help=(
            "When to run diagnostic sample-memory probes. These probes estimate "
            "memorization pressure and are not part of the validation acceptance "
            "signal."
        ),
    )
    parser.add_argument(
        "--autoencoder-sample-memory-probe-every-n-cycles",
        type=int,
        default=_env_int(
            AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES_ENV,
            DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES,
            minimum=1,
        ),
        help=(
            "Cycle cadence for --autoencoder-sample-memory-probe-mode periodic. "
            "Ignored for every_cycle and off."
        ),
    )
    parser.add_argument(
        "--autoencoder-todo-supervisor-mode",
        choices=("every_cycle", "starved", "off"),
        default=os.environ.get(
            AUTOENCODER_TODO_SUPERVISOR_MODE_ENV,
            DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE,
        ),
        help=(
            "When to run the TODO supervisor optimization bridge. starved refreshes "
            "the queue each cycle but skips duplicate optimization while enough "
            "program-synthesis TODOs are already pending or claimed."
        ),
    )
    parser.add_argument(
        "--autoencoder-todo-supervisor-min-open",
        type=int,
        default=_env_int(
            AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN_ENV,
            DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN,
            minimum=1,
        ),
        help=(
            "Minimum pending+claimed program-synthesis TODOs required for "
            "--autoencoder-todo-supervisor-mode starved to skip optimization."
        ),
    )
    parser.add_argument(
        "--uscode-embeddings-mode",
        choices=("auto", "off", "required"),
        default=os.environ.get("IPFS_DATASETS_USCODE_EMBEDDINGS_MODE", "auto"),
        help=(
            "How to load laws_embeddings.parquet for autoencoder targets: "
            "auto falls back to stable mock vectors, required fails fast, "
            "and off always uses mock vectors."
        ),
    )
    parser.add_argument(
        "--uscode-embeddings-path",
        default=os.environ.get(
            "IPFS_DATASETS_USCODE_EMBEDDINGS_PATH",
            USCODE_EMBEDDINGS_PARQUET,
        ),
        help=(
            "Local path or Hugging Face dataset-relative path for U.S. Code "
            "semantic embeddings used by validation cosine/CE targets."
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
        default=1.5,
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
        "--generalizable-projection-timeout-seconds",
        type=float,
        default=DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS,
        help=(
            "Maximum wall-clock seconds for one guarded feature-projection phase. "
            "Zero disables this guard."
        ),
    )
    parser.add_argument(
        "--generalizable-projection-max-line-search-attempts",
        type=int,
        default=0,
        help=(
            "Maximum line-search attempts per projection update. Zero uses auto mode, "
            "which trims expensive refinement attempts for very large warm-start states."
        ),
    )
    parser.add_argument(
        "--autoencoder-projection-deadband-mode",
        choices=("off", "shadow", "enforce"),
        default=os.environ.get(
            AUTOENCODER_PROJECTION_DEADBAND_MODE_ENV,
            DEFAULT_AUTOENCODER_PROJECTION_DEADBAND_MODE,
        ),
        help=(
            "Whether feature-projection acceptance should tolerate tiny CE "
            "regressions: off disables reporting, shadow reports would-accept "
            "decisions without changing training, enforce applies the deadband."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-ce-deadband",
        type=float,
        default=_env_float(
            AUTOENCODER_MAX_CE_DEADBAND_ENV,
            DEFAULT_AUTOENCODER_MAX_CE_DEADBAND,
            minimum=0.0,
        ),
        help=(
            "Maximum CE/CE-excess regression the projection deadband may tolerate "
            "when weighted objective improves."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-cosine-regression",
        type=float,
        default=_env_optional_float(
            AUTOENCODER_MAX_COSINE_REGRESSION_ENV,
            minimum=0.0,
        ),
        help=(
            "Optional explicit hard cosine-regression cap for projection acceptance. "
            "When omitted, --generalizable-projection-max-cosine-regression is used."
        ),
    )
    parser.add_argument(
        "--autoencoder-hard-guardrail-metrics",
        default=os.environ.get(
            AUTOENCODER_HARD_GUARDRAIL_METRICS_ENV,
            ",".join(PROJECTION_DEADBAND_DEFAULT_HARD_GUARDRAILS),
        ),
        help=(
            "Comma-separated metric names or prefix globs that the projection "
            "deadband must never relax, e.g. embedding_cosine_similarity,legal_ir:*."
        ),
    )
    parser.add_argument(
        "--autoencoder-projection-prescreen-mode",
        choices=("off", "shadow", "enforce"),
        default=os.environ.get(
            AUTOENCODER_PROJECTION_PRESCREEN_MODE_ENV,
            DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_MODE,
        ),
        help=(
            "Whether projection candidates should be ranked by cheap train-sample "
            "prescreening before holdout validation: off disables it, shadow reports "
            "rankings, enforce restricts acceptance to the top-k ranked candidates."
        ),
    )
    parser.add_argument(
        "--autoencoder-projection-prescreen-top-k",
        type=int,
        default=_env_int(
            AUTOENCODER_PROJECTION_PRESCREEN_TOP_K_ENV,
            DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_TOP_K,
            minimum=0,
        ),
        help=(
            "Number of projection line-search attempts per update selected by "
            "prescreening. Zero means select all attempts."
        ),
    )
    parser.add_argument(
        "--autoencoder-projection-periodic-full-search-every-n-cycles",
        type=int,
        default=_env_int(
            AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES_ENV,
            DEFAULT_AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES,
            minimum=0,
        ),
        help=(
            "When prescreen enforce mode is active, run a shadow full-search cycle "
            "every N cycles. Zero disables periodic full-search cycles."
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
        default=_env_bool(
            BRIDGE_EVALUATE_PROVERS_ENV,
            DEFAULT_BRIDGE_EVALUATE_PROVERS,
        ),
        help=(
            "Whether bridge scoring should run expensive theorem-prover gates. "
            "Defaults to false so daemon cycles reach projection/Codex quickly; "
            "use true for dedicated prover-heavy validation sweeps."
        ),
    )
    parser.add_argument(
        "--autoencoder-metric-bridge-adapters",
        default=None,
        help=(
            "Comma-separated bridge adapters used inside synchronous autoencoder "
            "LegalIR metric/evaluation phases. Empty uses a cheap representative "
            "subset, 'all' mirrors --bridge-loss-adapters, and 'none' disables "
            "bridge-backed autoencoder metrics."
        ),
    )
    parser.add_argument(
        "--autoencoder-diagnostic-bridge-adapters",
        default=None,
        help=(
            "Comma-separated bridge adapters used for synchronous compiler bridge "
            "diagnostics. Empty mirrors the cheap autoencoder metric ladder, "
            "'all' mirrors --bridge-loss-adapters, and 'none' disables these "
            "diagnostic bridge metrics."
        ),
    )
    parser.add_argument(
        "--autoencoder-metric-bridge-max-samples",
        type=int,
        default=None,
        help=(
            "Maximum train/validation samples per phase that receive bridge-backed "
            "LegalIR autoencoder metrics. Base CE/cosine/reconstruction metrics "
            "still evaluate the full batch. Zero disables sampled bridge metrics."
        ),
    )
    parser.add_argument(
        "--autoencoder-metric-bridge-max-sample-text-chars",
        type=int,
        default=None,
        help=(
            "Maximum text characters per sampled bridge-backed autoencoder metric "
            "sample. Longer samples are evaluated with a metric-only bounded prefix. "
            "Zero disables the metric-only text cap."
        ),
    )
    parser.add_argument(
        "--autoencoder-bootstrap-program-synthesis-todos",
        type=parse_bool_flag,
        default=True,
        help=(
            "Seed a small Codex/program-synthesis queue from autoencoder "
            "introspection immediately after sampling, before bridge-heavy "
            "projection phases can delay the first completed cycle."
        ),
    )
    parser.add_argument(
        "--autoencoder-bootstrap-mode",
        choices=("fast", "introspection"),
        default="fast",
        help=(
            "Use fast scope-aware deterministic bootstrap TODOs at startup, or "
            "run full autoencoder introspection before seeding the initial Codex queue."
        ),
    )
    parser.add_argument(
        "--autoencoder-bootstrap-min-pending",
        type=int,
        default=1,
        help=(
            "Only run the early program-synthesis bootstrap when fewer than this "
            "many program-synthesis TODOs are already pending or claimed."
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
        "--autoencoder-max-legal-semantic-frame-features",
        type=int,
        default=64,
        help=(
            "Maximum canonical legal semantic frame features to expose to the "
            "feature decoder. These map actors, legal acts, objects, "
            "conditions, exceptions, and KG relations into reusable classes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-normative-polarity-features",
        type=int,
        default=48,
        help=(
            "Maximum deontic force and polarity features to expose to the "
            "feature decoder. These distinguish obligation, permission, "
            "prohibition, negated scope, exceptions, and modal operators."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-compiler-contract-features",
        type=int,
        default=64,
        help=(
            "Maximum composite compiler-contract features to expose to the "
            "feature decoder. These combine source semantic frame, deontic "
            "force/polarity/scope, and compiled IR operator shape."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-decompiler-surface-template-features",
        type=int,
        default=48,
        help=(
            "Maximum IR-to-text surface template features to expose to the "
            "feature decoder. These encode role order, force lexeme, negation "
            "placement, scope realizers, and modal operator realization."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-canonical-ir-graph-features",
        type=int,
        default=64,
        help=(
            "Maximum canonical IR graph features to expose to the feature "
            "decoder. These normalize formula nodes, semantic role edges, "
            "condition/exception scope, and KG shape for paraphrase-stable "
            "compiler/decompiler transfer."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-cycle-consistency-features",
        type=int,
        default=64,
        help=(
            "Maximum compiler/decompiler cycle-consistency features to expose "
            "to the feature decoder. These align source roles, modal force, "
            "IR operator shape, condition/exception scope, and KG shape so "
            "round-trip TODOs generalize across paraphrases."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-equivalence-prototype-features",
        type=int,
        default=48,
        help=(
            "Maximum canonical equivalence-prototype features to expose to "
            "the feature decoder. These pool paraphrases that share the same "
            "legal IR role, operator, scope, force, and KG shape into one "
            "learnable latent prototype."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-contrastive-ir-boundary-features",
        type=int,
        default=64,
        help=(
            "Maximum contrastive legal IR boundary features to expose to the "
            "feature decoder. These separate confusable clauses that share "
            "actors and objects but differ in legal force, polarity, scope, "
            "operator, cue, or KG shape."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-repair-plan-features",
        type=int,
        default=64,
        help=(
            "Maximum TODO-oriented repair-plan features to expose to the "
            "feature decoder. These route source/IR residuals into reusable "
            "compiler and decompiler repair axes such as modal parser rules, "
            "condition/exception extractors, KG construction, negation "
            "preservation, and surface templates."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-logic-view-contract-features",
        type=int,
        default=64,
        help=(
            "Maximum typed multiview logic-contract features to expose to "
            "the feature decoder. These bind deontic, TDFOL, CEC/DCEC, "
            "frame/KG, prover, and decompiler slots into one bridge contract "
            "so LegalIR view loss and reconstruction transfer across clauses."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-objective-residual-features",
        type=int,
        default=64,
        help=(
            "Maximum objective-residual features to expose to the feature "
            "decoder. These bind cached LegalIR target losses and bridge-view "
            "distributions to reusable TODO routes so cross entropy, cosine, "
            "and multiview loss updates train through the same residual "
            "contract."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-provenance-alignment-features",
        type=int,
        default=64,
        help=(
            "Maximum provenance-alignment features to expose to the feature "
            "decoder. These bind source span coverage, cue placement, role "
            "anchors, and formula provenance to compiler/decompiler repair "
            "routes such as modal span coverage and semantic reconstruction."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-discourse-flow-features",
        type=int,
        default=64,
        help=(
            "Maximum discourse-flow features to expose to the feature decoder. "
            "These bind source cue order, clause scope, modal operators, and "
            "compiler/decompiler route hints so condition/force/exception/time "
            "choreography transfers across paraphrased legal text."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-proof-obligation-features",
        type=int,
        default=64,
        help=(
            "Maximum proof-obligation features to expose to the feature "
            "decoder. These bind source roles, modal operators, bridge "
            "adapters, external prover routes, and ZKP/proof obligations into "
            "a shared compiler/decompiler proof plan."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-entity-binding-features",
        type=int,
        default=64,
        help=(
            "Maximum entity-binding features to expose to the feature decoder. "
            "These bind source actors, actions, objects, conditions, "
            "exceptions, temporal anchors, predicate arguments, and logical "
            "variable slots into a reusable compiler/decompiler binding graph."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-defeasible-priority-features",
        type=int,
        default=64,
        help=(
            "Maximum defeasible-priority features to expose to the feature "
            "decoder. These bind base norms, conditions, exceptions, provisos, "
            "notwithstanding overrides, and temporal guards into a reusable "
            "priority/decompiler plan."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-constraint-grounding-features",
        type=int,
        default=64,
        help=(
            "Maximum constraint-grounding features to expose to the feature "
            "decoder. These bind numeric deadlines, percentages, monetary "
            "thresholds, cardinalities, and statutory cross-references to "
            "modal operators and decompiler repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-definition-grounding-features",
        type=int,
        default=64,
        help=(
            "Maximum definition-grounding features to expose to the feature "
            "decoder. These bind defined terms, inclusion/exclusion scope, "
            "knowledge-graph definition edges, and decompiler repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-quantitative-formula-features",
        type=int,
        default=64,
        help=(
            "Maximum quantitative-formula features to expose to the feature "
            "decoder. These bind greater-of, lesser-of, caps, floors, "
            "per-period rates, multipliers, and sums to compiler arithmetic "
            "nodes, frame-logic arithmetic slots, KG amount edges, and "
            "decompiler formula repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-quantifier-scope-features",
        type=int,
        default=64,
        help=(
            "Maximum quantifier-scope features to expose to the feature "
            "decoder. These bind universal, existential, negative, unique, "
            "and conditional quantifiers to roles, operators, and decompiler "
            "repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-procedural-lifecycle-features",
        type=int,
        default=64,
        help=(
            "Maximum procedural-lifecycle features to expose to the feature "
            "decoder. These bind filing, notice, hearing, decision, "
            "effective-date, and review stages to event-calculus transitions "
            "and decompiler repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-enforcement-remedy-features",
        type=int,
        default=64,
        help=(
            "Maximum enforcement-remedy features to expose to the feature "
            "decoder. These bind violation triggers, liable parties, "
            "penalties, sanctions, injunctions, enforcement actors, and "
            "decompiler repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-mental-state-features",
        type=int,
        default=64,
        help=(
            "Maximum mental-state features to expose to the feature decoder. "
            "These bind knowingly, willfully, intentionally, recklessly, "
            "negligently, reason-to-know, constructive-knowledge, and "
            "negated-intent/knowledge standards to compiler culpability "
            "gates, frame-logic mental-state slots, KG knowledge edges, and "
            "decompiler mental-state repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-reference-dependency-features",
        type=int,
        default=64,
        help=(
            "Maximum reference-dependency features to expose to the feature "
            "decoder. These bind statutory citations, local references, "
            "exception imports, authority imports, applicability scope, and "
            "decompiler dependency-graph repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-amendment-operation-features",
        type=int,
        default=64,
        help=(
            "Maximum amendment-operation features to expose to the feature "
            "decoder. These bind strike/insert/add/redesignate/repeal edits "
            "to compiler amendment nodes, frame-logic amendment slots, KG "
            "edit edges, and decompiler amendment repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-authority-jurisdiction-features",
        type=int,
        default=64,
        help=(
            "Maximum authority-jurisdiction features to expose to the feature "
            "decoder. These bind delegated powers, rulemaking authority, "
            "jurisdiction, preemption limits, authority instruments, and "
            "decompiler power-scope repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-discretion-standard-features",
        type=int,
        default=64,
        help=(
            "Maximum discretion-standard features to expose to the feature "
            "decoder. These bind discretionary determinations, judicial "
            "findings, good-cause tests, public-interest standards, and "
            "reasonableness/necessity standards to compiler epistemic gates, "
            "frame-logic standard slots, KG evaluative edges, and decompiler "
            "standard repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-temporal-validity-features",
        type=int,
        default=64,
        help=(
            "Maximum temporal-validity features to expose to the feature "
            "decoder. These bind effective dates, sunset and expiration "
            "rules, retroactivity, transition windows, applicability dates, "
            "and decompiler versioning repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-evidentiary-burden-features",
        type=int,
        default=64,
        help=(
            "Maximum evidentiary-burden features to expose to the feature "
            "decoder. These bind burden holders, issues, standards of proof, "
            "presumptions, prima facie evidence, rebuttal burdens, and "
            "decompiler proof-contract repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-legal-relation-features",
        type=int,
        default=64,
        help=(
            "Maximum Hohfeld-style legal-relation features to expose to the "
            "feature decoder. These bind rights, duties, privileges, powers, "
            "liabilities, immunities, correlatives, and decompiler relation "
            "repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-status-transition-features",
        type=int,
        default=64,
        help=(
            "Maximum legal status-transition features to expose to the "
            "feature decoder. These bind authorization, eligibility, validity, "
            "revocation, suspension, expiration, and decompiler state-machine "
            "repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-condition-consequence-features",
        type=int,
        default=64,
        help=(
            "Maximum condition-consequence features to expose to the feature "
            "decoder. These bind if/when/unless/proviso antecedents to "
            "consequents, event-calculus preconditions, frame-logic guard "
            "slots, and decompiler guarded-rule repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-applicability-scope-features",
        type=int,
        default=64,
        help=(
            "Maximum applicability-scope features to expose to the feature "
            "decoder. These bind applies-to, does-not-apply, exempt-from, "
            "for-purposes-of, in-the-case-of, and with-respect-to scopes to "
            "frame-logic domains, KG applicability edges, and decompiler "
            "scope repair routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-coreference-binding-features",
        type=int,
        default=64,
        help=(
            "Maximum coreference-binding features to expose to the feature "
            "decoder. These bind such/that/the-same/thereof/therein/"
            "thereunder references to compiler variables, frame-logic same-as "
            "edges, KG coreference edges, and decompiler reference repair "
            "routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-logical-connective-features",
        type=int,
        default=64,
        help=(
            "Maximum logical-connective features to expose to the feature "
            "decoder. These bind and/or/either-or/neither-nor/both-and/list "
            "connectives to compiler Boolean nodes, frame-logic connective "
            "slots, KG connective edges, and decompiler list/Boolean repair "
            "routes."
        ),
    )
    parser.add_argument(
        "--autoencoder-max-enumeration-hierarchy-features",
        type=int,
        default=64,
        help=(
            "Maximum enumeration-hierarchy features to expose to the feature "
            "decoder. These bind statutory subdivision markers such as "
            "(1), (A), and (i), following-list openings, and paragraph/clause "
            "cross-references to compiler list nodes, frame-logic hierarchy "
            "slots, KG enumeration edges, and decompiler list-scope repair "
            "routes."
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
        default=0.5,
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
        "--autoencoder-max-codec-feature-keys",
        type=int,
        default=0,
        help=(
            "Maximum deterministic codec-provided feature keys per sample in "
            "the adaptive autoencoder. Fallback compiler/legal feature groups "
            "remain governed by their dedicated per-family caps. The default "
            "keeps this disabled because the full deterministic codec feature "
            "path can be much slower than the bounded fallback feature heads."
        ),
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
    parser.add_argument("--codex-model", default="gpt-5.5")
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
        "--codex-scope-fallback-to-global",
        type=parse_bool_flag,
        default=True,
        help=(
            "Allow a scoped Codex worker to borrow any pending program-synthesis "
            "TODO when its own scope is empty. This prevents resource-capped paired "
            "runs from idling workers in empty lanes while other lanes have backlog."
        ),
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
        "--codex-main-apply-lock-timeout-seconds",
        type=float,
        default=CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS,
        help=(
            "Maximum time a Codex worker waits for the serialized main apply lock "
            "before saving a rescue patch and requeueing the TODO as transient."
        ),
    )
    parser.add_argument(
        "--codex-main-apply-max-inflight-packets",
        type=int,
        default=0,
        help=(
            "Maximum claimed Codex packets allowed while using apply_to_main. "
            "Zero disables pre-claim apply backpressure. Use this to prevent "
            "parallel workers from all claiming TODOs and timing out on the "
            "single serialized main-apply validation lane."
        ),
    )
    parser.add_argument(
        "--codex-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    parser.add_argument("--codex-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--codex-validation-timeout-seconds",
        type=float,
        default=CODEX_APPLY_VALIDATION_TIMEOUT_SECONDS,
        help=(
            "Per-command timeout for Codex apply validation. Validation is run "
            "in its own process group so timeout cleanup also kills pytest children."
        ),
    )
    parser.add_argument(
        "--codex-claim-stale-seconds",
        type=float,
        default=0.0,
        help=(
            "Age after which claimed Codex TODOs can be requeued as abandoned. "
            "Zero derives a conservative timeout from Codex/apply/validation limits."
        ),
    )
    parser.add_argument("--autoencoder-run-id", default=None)
    parser.add_argument("--codex-run-id", default=None)
    parser.add_argument("--paired-launch-delay-seconds", type=float, default=0.0)
    parser.add_argument(
        "--paired-codex-launch-stagger-seconds",
        type=float,
        default=1.0,
        help=(
            "Delay between paired Codex child launches. Staggering avoids import "
            "and Codex CLI startup memory spikes when many scope workers start."
        ),
    )
    parser.add_argument(
        "--paired-codex-disable-cuda",
        type=parse_bool_flag,
        default=parse_bool_flag(
            os.environ.get("IPFS_DATASETS_PAIRED_CODEX_DISABLE_CUDA", "true")
        ),
        help=(
            "Hide CUDA devices from paired Codex workers so the autoencoder owns "
            "GPU memory. Use false only when a Codex lane explicitly needs CUDA."
        ),
    )
    parser.add_argument("--paired-poll-seconds", type=float, default=1.0)
    parser.add_argument("--paired-grace-seconds", type=float, default=300.0)
    parser.add_argument(
        "--paired-resource-guard",
        choices=("auto", "fixed", "off"),
        default=os.environ.get("IPFS_DATASETS_PAIRED_RESOURCE_GUARD", "auto"),
        help=(
            "Admission-control mode for paired Codex workers. The auto mode caps "
            "workers by CPU and available memory before launching the pool."
        ),
    )
    parser.add_argument(
        "--paired-codex-max-workers",
        type=int,
        default=int(os.environ.get("IPFS_DATASETS_PAIRED_CODEX_MAX_WORKERS", "0") or 0),
        help=(
            "Maximum paired Codex workers. Zero lets the auto resource guard choose."
        ),
    )
    parser.add_argument(
        "--paired-codex-worker-memory-gb",
        type=float,
        default=float(
            os.environ.get("IPFS_DATASETS_PAIRED_CODEX_WORKER_MEMORY_GB", "2.0") or 2.0
        ),
        help="Estimated host-memory budget per paired Codex worker.",
    )
    parser.add_argument(
        "--paired-reserved-memory-gb",
        type=float,
        default=float(
            os.environ.get("IPFS_DATASETS_PAIRED_RESERVED_MEMORY_GB", "24.0") or 24.0
        ),
        help="Host memory kept free for the OS, editor, CUDA driver, and autoencoder.",
    )
    parser.add_argument(
        "--paired-min-available-memory-gb",
        type=float,
        default=float(
            os.environ.get("IPFS_DATASETS_PAIRED_MIN_AVAILABLE_MEMORY_GB", "12.0")
            or 12.0
        ),
        help=(
            "Do not restart paired children while MemAvailable is below this "
            "threshold. Zero disables restart deferral under memory pressure."
        ),
    )
    parser.add_argument(
        "--paired-min-swap-free-gb",
        type=float,
        default=float(
            os.environ.get("IPFS_DATASETS_PAIRED_MIN_SWAP_FREE_GB", "1.0") or 1.0
        ),
        help=(
            "Do not restart paired children while SwapFree is below this threshold. "
            "Auto worker admission also trims the Codex pool under swap pressure. "
            "Zero disables swap-pressure handling."
        ),
    )
    parser.add_argument(
        "--paired-autoencoder-stale-seconds",
        type=float,
        default=900.0,
        help=(
            "In paired mode, restart the autoencoder child when the Codex queue is "
            "starved and the autoencoder heartbeat is stale for this many seconds. "
            "Zero disables restart-on-stale."
        ),
    )
    parser.add_argument(
        "--paired-autoencoder-restart-limit",
        type=int,
        default=2,
        help="Maximum paired-mode autoencoder child restarts after stale-heartbeat starvation.",
    )
    parser.add_argument(
        "--paired-codex-worker-stale-seconds",
        type=float,
        default=900.0,
        help=(
            "In paired mode, restart Codex children whose summaries stop "
            "heartbeating while they still own claimed program-synthesis TODOs."
        ),
    )
    parser.add_argument(
        "--paired-codex-worker-restart-limit",
        type=int,
        default=3,
        help="Maximum paired-mode restarts for each stale Codex child.",
    )
    parser.add_argument(
        "--paired-supervisor-backend",
        choices=("accelerate_style", "legacy"),
        default="accelerate_style",
        help=(
            "Paired child supervision backend. accelerate_style keeps the desired "
            "autoencoder/Codex worker pool alive by pruning and replacing crashed "
            "children while preserving legal TODO queue semantics."
        ),
    )
    parser.add_argument(
        "--paired-failed-validation-rescue-mode",
        choices=("auto", "eager", "starved", "off"),
        default="auto",
        help=(
            "In paired accelerate-style supervision, seed rescue TODOs when "
            "Codex workers are alive but the program-synthesis queue has "
            "failed_validation terminal items. auto seeds on idle capacity or "
            "large backlogs, eager is more aggressive, and starved waits for a "
            "drained queue."
        ),
    )
    parser.add_argument(
        "--paired-failed-validation-rescue-max-clusters",
        type=int,
        default=8,
        help="Maximum failed-validation clusters to rescue per paired supervisor pass.",
    )
    parser.add_argument(
        "--paired-failed-validation-rescue-interval-seconds",
        type=float,
        default=30.0,
        help="Minimum seconds between paired supervisor failed-validation rescue passes.",
    )
    parser.add_argument(
        "--paired-failed-validation-rescue-backlog-threshold",
        type=int,
        default=32,
        help=(
            "In auto/eager rescue mode, seed failed-validation rescue TODOs even "
            "while ordinary program-synthesis work remains once the failed backlog "
            "reaches this count."
        ),
    )
    parser.add_argument(
        "--paired-failed-validation-rescue-max-attempts",
        type=int,
        default=FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS,
        help="Maximum rescue attempts per failed-validation cluster in paired mode.",
    )
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
    low_rank_load_reports: List[Dict[str, Any]] = []
    missing_paths: List[str] = []
    for path in paths:
        if not path.exists():
            missing_paths.append(str(path))
            continue
        state = ModalAutoencoderTrainingState.load_json(path)
        low_rank_report = autoencoder_low_rank_load_report(state, state_path=path)
        if low_rank_report.get("enabled"):
            low_rank_load_reports.append(low_rank_report)
        loaded_states.append(state.generalizable_copy())
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
        "low_rank_load_reports": low_rank_load_reports,
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
    requested_codex_child_count = len(codex_children)
    resource_plan = paired_codex_worker_resource_plan(
        args,
        requested_workers=requested_codex_child_count,
    )
    effective_codex_child_count = int(resource_plan.get("effective_workers", 0) or 0)
    if effective_codex_child_count < requested_codex_child_count:
        codex_children = _round_robin_codex_children(
            codex_children,
            limit=effective_codex_child_count,
        )
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
    queue_path = root / "workspace" / "todo-queues" / f"{paired['queue_run_id']}.jsonl"
    autoencoder_summary_path = log_dir / f"{paired['autoencoder_run_id']}.summary"
    codex_summary_paths = [
        log_dir / f"{str(child['run_id'])}.summary" for child in codex_child_summaries
    ]
    autoencoder_restart_limit = max(
        0,
        int(getattr(args, "paired_autoencoder_restart_limit", 2) or 0),
    )
    codex_worker_restart_limit = max(
        0,
        int(getattr(args, "paired_codex_worker_restart_limit", 3) or 0),
    )
    autoencoder_stale_seconds = max(
        0.0,
        float(getattr(args, "paired_autoencoder_stale_seconds", 900.0) or 0.0),
    )
    codex_worker_stale_seconds = max(
        0.0,
        float(getattr(args, "paired_codex_worker_stale_seconds", 900.0) or 0.0),
    )
    supervisor_backend = str(
        getattr(args, "paired_supervisor_backend", "accelerate_style")
        or "accelerate_style"
    )
    accelerate_style_supervision = supervisor_backend == "accelerate_style"
    failed_validation_rescue_mode = str(
        getattr(args, "paired_failed_validation_rescue_mode", "auto") or "auto"
    ).strip().lower()
    failed_validation_rescue_max_clusters = max(
        0,
        int(getattr(args, "paired_failed_validation_rescue_max_clusters", 8) or 0),
    )
    failed_validation_rescue_interval_seconds = max(
        0.0,
        float(
            getattr(
                args,
                "paired_failed_validation_rescue_interval_seconds",
                30.0,
            )
            or 0.0
        ),
    )
    failed_validation_rescue_backlog_threshold = max(
        1,
        int(
            getattr(
                args,
                "paired_failed_validation_rescue_backlog_threshold",
                32,
            )
            or 32
        ),
    )
    failed_validation_rescue_max_attempts = max(
        1,
        int(
            getattr(
                args,
                "paired_failed_validation_rescue_max_attempts",
                FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS,
            )
            or FAILED_VALIDATION_RESCUE_MAX_ATTEMPTS
        ),
    )

    summary: Dict[str, Any] = {
        "autoencoder_command": list(paired["autoencoder_command"]),
        "autoencoder_child_health": paired_autoencoder_child_health(
            autoencoder_summary_path
        ),
        "autoencoder_restart_count": 0,
        "autoencoder_restart_limit": autoencoder_restart_limit,
        "autoencoder_run_id": paired["autoencoder_run_id"],
        "autoencoder_stale_seconds": autoencoder_stale_seconds,
        "autoencoder_stderr_path": str(auto_stderr_path),
        "autoencoder_summary_path": str(autoencoder_summary_path),
        "autoencoder_stdout_path": str(auto_stdout_path),
        "codex_command": list(paired["codex_command"]),
        "codex_children": codex_child_summaries,
        "codex_child_count": len(codex_child_summaries),
        "codex_requested_child_count": requested_codex_child_count,
        "codex_worker_exit_restart_counts": {},
        "codex_worker_restart_limit": codex_worker_restart_limit,
        "codex_worker_stale_restart_counts": {},
        "codex_run_id": paired["codex_run_id"],
        "codex_stderr_path": str(codex_stderr_path),
        "codex_stdout_path": str(codex_stdout_path),
        "child_process_group_mode": "start_new_session",
        "duration_seconds": float(args.duration_seconds),
        "final": False,
        "log_path": str(log_path),
        "loop_role": "paired",
        "paired_grace_seconds": float(args.paired_grace_seconds),
        "paired_poll_seconds": float(args.paired_poll_seconds),
        "paired_codex_child_env": paired_codex_child_env(args),
        "paired_codex_disable_cuda": bool(
            getattr(args, "paired_codex_disable_cuda", True)
        ),
        "paired_resource_guard": str(getattr(args, "paired_resource_guard", "auto")),
        "paired_resource_plan": dict(resource_plan),
        "paired_codex_worker_stale_seconds": codex_worker_stale_seconds,
        "paired_failed_validation_rescue_deduped_total": 0,
        "paired_failed_validation_rescue_interval_seconds": (
            failed_validation_rescue_interval_seconds
        ),
        "paired_failed_validation_rescue_max_clusters": (
            failed_validation_rescue_max_clusters
        ),
        "paired_failed_validation_rescue_mode": failed_validation_rescue_mode,
        "paired_failed_validation_rescue_backlog_threshold": (
            failed_validation_rescue_backlog_threshold
        ),
        "paired_failed_validation_rescue_max_attempts": (
            failed_validation_rescue_max_attempts
        ),
        "paired_failed_validation_rescue_seeded_total": 0,
        "paired_supervisor_backend": supervisor_backend,
        "paired_supervisor_features": {
            "bounded_restarts": True,
            "dead_child_pruning": accelerate_style_supervision,
            "failed_validation_rescue": bool(
                accelerate_style_supervision
                and failed_validation_rescue_mode != "off"
                and failed_validation_rescue_max_clusters > 0
            ),
            "process_group_shutdown": True,
            "stale_claim_requeue": True,
        },
        "program_synthesis_health": paired_program_synthesis_health(
            queue_path=queue_path,
            codex_summary_paths=codex_summary_paths,
            codex_worker_stale_seconds=codex_worker_stale_seconds,
        ),
        "program_synthesis_queue_path": str(queue_path),
        "queue_run_id": paired["queue_run_id"],
        "run_id": args.run_id,
        "started_at": utc_now(),
    }
    save_summary(summary_path, summary)

    def request_stop(signum: int, frame: Any) -> None:
        _terminate_active_codex_exec_processes(signal.SIGTERM)

    stop_state = accelerate_install_stop_signal_handlers(on_signal=request_stop)

    append_event(
        log_path,
        args.run_id,
        {
            "event": "paired_runner_started",
            "autoencoder_run_id": paired["autoencoder_run_id"],
            "codex_child_count": len(codex_child_summaries),
            "codex_requested_child_count": requested_codex_child_count,
            "codex_children": [
                {"run_id": child["run_id"], "scope": child.get("scope")}
                for child in codex_child_summaries
            ],
            "codex_run_id": paired["codex_run_id"],
            "paired_resource_plan": dict(resource_plan),
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
    runner_restarted_children: List[Dict[str, Any]] = []
    autoencoder_restart_count = 0
    codex_worker_restart_counts: Dict[str, int] = {}
    codex_worker_exit_restart_counts: Dict[str, int] = {}
    restart_resource_defer_last_at: Dict[str, float] = {}
    last_codex_queue_starved = False
    last_autoencoder_restart_at = 0.0
    last_failed_validation_rescue_at = 0.0
    paired_duration_elapsed = False

    try:
        with ExitStack() as stack:
            auto_stdout = stack.enter_context(auto_stdout_path.open("a", encoding="utf-8"))
            auto_stderr = stack.enter_context(auto_stderr_path.open("a", encoding="utf-8"))

            def start_autoencoder_child(
                *,
                event: str,
                previous_pid: Optional[int] = None,
                restart_count: int = 0,
            ) -> subprocess.Popen[str]:
                process = accelerate_launch_process_child(
                    list(paired["autoencoder_command"]),
                    cwd=root,
                    stdin=None,
                    stdout=auto_stdout,
                    stderr=auto_stderr,
                    start_new_session=True,
                    text=True,
                )
                payload: Dict[str, Any] = {
                    "event": event,
                    "child_role": "autoencoder",
                    "child_pid": process.pid,
                    "child_run_id": paired["autoencoder_run_id"],
                    "restart_count": int(restart_count),
                }
                if previous_pid is not None:
                    payload["previous_pid"] = int(previous_pid)
                append_event(log_path, args.run_id, payload)
                return process

            auto_process = start_autoencoder_child(event="paired_child_started")

            launch_delay = max(0.0, float(args.paired_launch_delay_seconds))
            if launch_delay > 0.0:
                time.sleep(launch_delay)

            def start_codex_child(
                child: Mapping[str, Any],
                *,
                event: str = "paired_child_started",
                previous_pid: Optional[int] = None,
                restart_count: int = 0,
            ) -> subprocess.Popen[str]:
                child_run_id = str(child["run_id"])
                child_stdout = stack.enter_context(
                    Path(str(child["stdout_path"])).open("a", encoding="utf-8")
                )
                child_stderr = stack.enter_context(
                    Path(str(child["stderr_path"])).open("a", encoding="utf-8")
                )
                process = accelerate_launch_process_child(
                    list(child["command"]),
                    cwd=root,
                    env=paired_codex_child_env(args),
                    stdin=None,
                    stdout=child_stdout,
                    stderr=child_stderr,
                    start_new_session=True,
                    text=True,
                )
                payload: Dict[str, Any] = {
                    "event": event,
                    "child_role": "codex",
                    "child_pid": process.pid,
                    "child_run_id": child_run_id,
                    "codex_scope": child.get("scope"),
                    "restart_count": int(restart_count),
                    "worker_id": child.get("worker_id"),
                }
                if previous_pid is not None:
                    payload["previous_pid"] = int(previous_pid)
                append_event(log_path, args.run_id, payload)
                return process

            for child in codex_child_summaries:
                child_run_id = str(child["run_id"])
                codex_processes[child_run_id] = start_codex_child(child)
                stagger = max(
                    0.0,
                    float(getattr(args, "paired_codex_launch_stagger_seconds", 0.0) or 0.0),
                )
                if stagger > 0.0:
                    time.sleep(stagger)

            poll_seconds = max(0.2, float(args.paired_poll_seconds))
            duration_wait = max(0.0, float(args.duration_seconds))
            max_wait = duration_wait + max(0.0, float(args.paired_grace_seconds))
            while True:
                elapsed = time.time() - started
                auto_exit_code = auto_process.poll()
                codex_exit_codes = {
                    run_id: process.poll()
                    for run_id, process in codex_processes.items()
                }
                summary["elapsed_seconds"] = round(elapsed, 3)
                summary["heartbeat_at"] = utc_now()
                summary["paired_resource_health"] = paired_resource_health()
                summary["latest_stop_reason"] = (
                    "paired_duration_elapsed"
                    if paired_duration_elapsed
                    else "running"
                )
                summary["autoencoder_pid"] = auto_process.pid
                summary["codex_pids"] = {
                    run_id: process.pid for run_id, process in codex_processes.items()
                }
                summary["codex_pid"] = next(iter(summary["codex_pids"].values()), None)
                summary["autoencoder_exit_code"] = auto_exit_code
                summary["codex_exit_codes"] = codex_exit_codes
                summary["codex_exit_code"] = next(iter(codex_exit_codes.values()), None)
                if (
                    accelerate_style_supervision
                    and _paired_child_exit_should_restart(
                        exit_code=auto_exit_code,
                        latest_stop_reason=str(
                            paired_autoencoder_child_health(
                                autoencoder_summary_path
                            ).get("autoencoder_latest_stop_reason")
                            or ""
                        ),
                        restart_count=autoencoder_restart_count,
                        restart_limit=autoencoder_restart_limit,
                        stop_requested=stop_state.stop_requested,
                    )
                    and not paired_duration_elapsed
                    and elapsed <= duration_wait
                ):
                    resource_pressure, pressure_report = _paired_resource_pressure(
                        args,
                        role="autoencoder",
                    )
                    if resource_pressure:
                        now = time.time()
                        last_deferred = restart_resource_defer_last_at.get(
                            str(paired["autoencoder_run_id"]),
                            0.0,
                        )
                        if now - last_deferred >= 60.0:
                            restart_resource_defer_last_at[
                                str(paired["autoencoder_run_id"])
                            ] = now
                            append_event(
                                log_path,
                                args.run_id,
                                {
                                    "event": "paired_autoencoder_restart_deferred",
                                    "previous_exit_code": auto_exit_code,
                                    "reason": "resource_pressure",
                                    "resource_pressure": dict(pressure_report),
                                },
                            )
                        summary["latest_restart_deferral"] = {
                            "child_run_id": paired["autoencoder_run_id"],
                            "reason": "resource_pressure",
                            "resource_pressure": dict(pressure_report),
                        }
                        save_summary(summary_path, summary)
                        time.sleep(poll_seconds)
                        continue
                    previous_pid = auto_process.pid
                    previous_exit_code = auto_exit_code
                    autoencoder_restart_count += 1
                    last_autoencoder_restart_at = time.time()
                    runner_restarted_children.append(
                        {
                            "child_role": "autoencoder",
                            "child_run_id": paired["autoencoder_run_id"],
                            "previous_exit_code": previous_exit_code,
                            "previous_pid": previous_pid,
                            "reason": "accelerate_style_dead_child_pruned",
                            "restarted_at": utc_now(),
                            "restart_count": autoencoder_restart_count,
                        }
                    )
                    append_event(
                        log_path,
                        args.run_id,
                        {
                            "event": "paired_autoencoder_dead_child_restarting",
                            "previous_exit_code": previous_exit_code,
                            "previous_pid": previous_pid,
                            "reason": "accelerate_style_dead_child_pruned",
                            "restart_count": autoencoder_restart_count,
                        },
                    )
                    auto_process = start_autoencoder_child(
                        event="paired_child_restarted",
                        previous_pid=previous_pid,
                        restart_count=autoencoder_restart_count,
                    )
                    auto_exit_code = auto_process.poll()
                    summary["autoencoder_pid"] = auto_process.pid
                    summary["autoencoder_exit_code"] = auto_exit_code
                    summary["autoencoder_restart_count"] = autoencoder_restart_count
                    summary["runner_restarted_children"] = list(runner_restarted_children)

                if (
                    accelerate_style_supervision
                    and not stop_state.stop_requested
                    and not paired_duration_elapsed
                ):
                    for child in codex_child_summaries:
                        child_run_id = str(child["run_id"])
                        exit_code = codex_exit_codes.get(child_run_id)
                        restart_count = codex_worker_exit_restart_counts.get(
                            child_run_id,
                            0,
                        )
                        if not _paired_child_exit_should_restart(
                            exit_code=exit_code,
                            latest_stop_reason=_child_summary_latest_stop_reason(
                                log_dir / f"{child_run_id}.summary"
                            ),
                            restart_count=restart_count,
                            restart_limit=codex_worker_restart_limit,
                            stop_requested=stop_state.stop_requested,
                        ):
                            continue
                        if elapsed > duration_wait:
                            continue
                        resource_pressure, pressure_report = _paired_resource_pressure(args)
                        if resource_pressure:
                            now = time.time()
                            last_deferred = restart_resource_defer_last_at.get(
                                child_run_id,
                                0.0,
                            )
                            if now - last_deferred >= 60.0:
                                restart_resource_defer_last_at[child_run_id] = now
                                append_event(
                                    log_path,
                                    args.run_id,
                                    {
                                        "event": "paired_codex_restart_deferred",
                                        "child_run_id": child_run_id,
                                        "codex_scope": child.get("scope"),
                                        "previous_exit_code": exit_code,
                                        "reason": "resource_pressure",
                                        "resource_pressure": dict(pressure_report),
                                        "worker_id": child.get("worker_id"),
                                    },
                                )
                            summary["latest_restart_deferral"] = {
                                "child_run_id": child_run_id,
                                "reason": "resource_pressure",
                                "resource_pressure": dict(pressure_report),
                            }
                            continue
                        process = codex_processes.get(child_run_id)
                        previous_pid = process.pid if process is not None else None
                        restart_count += 1
                        codex_worker_exit_restart_counts[child_run_id] = restart_count
                        runner_restarted_children.append(
                            {
                                "child_role": "codex",
                                "child_run_id": child_run_id,
                                "codex_scope": child.get("scope"),
                                "previous_exit_code": exit_code,
                                "previous_pid": previous_pid,
                                "reason": "accelerate_style_dead_child_pruned",
                                "restarted_at": utc_now(),
                                "restart_count": restart_count,
                                "worker_id": child.get("worker_id"),
                            }
                        )
                        append_event(
                            log_path,
                            args.run_id,
                            {
                                "event": "paired_codex_dead_child_restarting",
                                "child_run_id": child_run_id,
                                "codex_scope": child.get("scope"),
                                "previous_exit_code": exit_code,
                                "previous_pid": previous_pid,
                                "reason": "accelerate_style_dead_child_pruned",
                                "restart_count": restart_count,
                                "worker_id": child.get("worker_id"),
                            },
                        )
                        codex_processes[child_run_id] = start_codex_child(
                            child,
                            event="paired_child_restarted",
                            previous_pid=previous_pid,
                            restart_count=restart_count,
                        )
                        codex_exit_codes[child_run_id] = None
                    if codex_worker_exit_restart_counts:
                        summary["codex_worker_exit_restart_counts"] = dict(
                            sorted(codex_worker_exit_restart_counts.items())
                        )
                        summary["runner_restarted_children"] = list(
                            runner_restarted_children
                        )
                program_synthesis_health = paired_program_synthesis_health(
                    queue_path=queue_path,
                    codex_summary_paths=codex_summary_paths,
                    codex_worker_stale_seconds=codex_worker_stale_seconds,
                )
                autoencoder_health = paired_autoencoder_child_health(
                    autoencoder_summary_path
                )
                summary["program_synthesis_health"] = program_synthesis_health
                summary["autoencoder_child_health"] = autoencoder_health
                for key in (
                    "program_synthesis_pending",
                    "program_synthesis_claimed",
                    "program_synthesis_completed",
                    "program_synthesis_failed_validation",
                    "program_synthesis_superseded",
                    "codex_queue_drained",
                    "codex_queue_open_count",
                    "codex_queue_starved",
                    "codex_workers_active_packet_count",
                    "codex_workers_waiting_for_todos_count",
                    "codex_worker_summary_count",
                    "codex_claimed_total",
                    "codex_execution_count",
                ):
                    if key in program_synthesis_health:
                        summary[key] = program_synthesis_health[key]
                stale_claimed_worker_ids = {
                    str(worker_id)
                    for worker_id in program_synthesis_health.get(
                        "stale_claimed_codex_worker_ids",
                        [],
                    )
                    if str(worker_id)
                }
                codex_worker_restarted = False
                if (
                    stale_claimed_worker_ids
                    and not paired_duration_elapsed
                    and elapsed <= duration_wait
                    and codex_worker_restart_limit > 0
                ):
                    stale_claim_age_seconds = max(
                        1.0,
                        min(
                            _codex_claim_stale_seconds(args),
                            codex_worker_stale_seconds
                            if codex_worker_stale_seconds > 0.0
                            else _codex_claim_stale_seconds(args),
                        ),
                    )
                    for child in codex_child_summaries:
                        worker_id = str(child.get("worker_id") or "")
                        if worker_id not in stale_claimed_worker_ids:
                            continue
                        child_run_id = str(child["run_id"])
                        restart_count = codex_worker_restart_counts.get(child_run_id, 0)
                        if restart_count >= codex_worker_restart_limit:
                            continue
                        resource_pressure, pressure_report = _paired_resource_pressure(args)
                        if resource_pressure:
                            now = time.time()
                            last_deferred = restart_resource_defer_last_at.get(
                                child_run_id,
                                0.0,
                            )
                            if now - last_deferred >= 60.0:
                                restart_resource_defer_last_at[child_run_id] = now
                                append_event(
                                    log_path,
                                    args.run_id,
                                    {
                                        "event": "paired_codex_stale_restart_deferred",
                                        "child_run_id": child_run_id,
                                        "previous_exit_code": (
                                            process.poll()
                                            if (process := codex_processes.get(child_run_id)) is not None
                                            else None
                                        ),
                                        "program_synthesis_health": program_synthesis_health,
                                        "reason": "resource_pressure",
                                        "resource_pressure": dict(pressure_report),
                                        "worker_id": worker_id,
                                    },
                                )
                            summary["latest_restart_deferral"] = {
                                "child_run_id": child_run_id,
                                "reason": "resource_pressure",
                                "resource_pressure": dict(pressure_report),
                            }
                            continue
                        process = codex_processes.get(child_run_id)
                        previous_pid = process.pid if process is not None else None
                        previous_exit_code: Optional[int] = (
                            process.poll() if process is not None else None
                        )
                        if process is not None and process.poll() is None:
                            previous_exit_code = _terminate_process_with_grace(
                                process,
                                grace_seconds=max(
                                    5.0,
                                    min(30.0, poll_seconds * 3.0),
                                ),
                            )
                            runner_terminated_children.add(child_run_id)
                        requeue_report = requeue_stale_program_synthesis_claims(
                            queue_path=queue_path,
                            policy=ModalOptimizerPolicy(),
                            max_age_seconds=stale_claim_age_seconds,
                            reason="stale_codex_worker_heartbeat",
                            claimed_by=[worker_id],
                        )
                        restart_count += 1
                        codex_worker_restart_counts[child_run_id] = restart_count
                        runner_restarted_children.append(
                            {
                                "child_role": "codex",
                                "child_run_id": child_run_id,
                                "previous_exit_code": previous_exit_code,
                                "previous_pid": previous_pid,
                                "requeue_report": dict(requeue_report),
                                "restarted_at": utc_now(),
                                "restart_count": restart_count,
                                "worker_id": worker_id,
                            }
                        )
                        append_event(
                            log_path,
                            args.run_id,
                            {
                                "event": "paired_codex_worker_stale_restarting",
                                "child_run_id": child_run_id,
                                "previous_exit_code": previous_exit_code,
                                "previous_pid": previous_pid,
                                "program_synthesis_health": program_synthesis_health,
                                "reason": "stale_codex_worker_heartbeat_with_claimed_todos",
                                "requeue_report": dict(requeue_report),
                                "restart_count": restart_count,
                                "worker_id": worker_id,
                            },
                        )
                        codex_processes[child_run_id] = start_codex_child(
                            child,
                            event="paired_child_restarted",
                            previous_pid=previous_pid,
                            restart_count=restart_count,
                        )
                        codex_exit_codes[child_run_id] = None
                        codex_worker_restarted = True
                    if codex_worker_restarted:
                        program_synthesis_health = paired_program_synthesis_health(
                            queue_path=queue_path,
                            codex_summary_paths=codex_summary_paths,
                            codex_worker_stale_seconds=codex_worker_stale_seconds,
                        )
                        summary["program_synthesis_health"] = program_synthesis_health
                        summary["codex_worker_restart_counts"] = dict(
                            sorted(codex_worker_restart_counts.items())
                        )
                        summary["codex_worker_stale_restart_counts"] = dict(
                            sorted(codex_worker_restart_counts.items())
                        )
                        summary["runner_restarted_children"] = list(
                            runner_restarted_children
                        )
                codex_queue_starved = bool(
                    program_synthesis_health.get("codex_queue_starved", False)
                )
                codex_queue_missing = not bool(
                    program_synthesis_health.get("queue_exists", False)
                )
                codex_prequeue_blocked = bool(
                    codex_queue_missing
                    and int(
                        program_synthesis_health.get(
                            "codex_workers_waiting_for_todos_count",
                            0,
                        )
                        or 0
                    )
                    > 0
                )
                summary["codex_prequeue_blocked"] = codex_prequeue_blocked
                if codex_queue_starved != last_codex_queue_starved:
                    append_event(
                        log_path,
                        args.run_id,
                        {
                            "event": (
                                "paired_codex_queue_starved"
                                if codex_queue_starved
                                else "paired_codex_queue_resumed"
                            ),
                            "program_synthesis_health": program_synthesis_health,
                            "queue_run_id": paired["queue_run_id"],
                        },
                    )
                    last_codex_queue_starved = codex_queue_starved
                if (
                    accelerate_style_supervision
                    and not paired_duration_elapsed
                    and failed_validation_rescue_max_clusters > 0
                    and _paired_failed_validation_rescue_should_seed(
                        program_synthesis_health,
                        mode=failed_validation_rescue_mode,
                        last_seed_at=last_failed_validation_rescue_at,
                        interval_seconds=failed_validation_rescue_interval_seconds,
                        backlog_threshold=failed_validation_rescue_backlog_threshold,
                    )
                ):
                    last_failed_validation_rescue_at = time.time()
                    rescue_report = seed_failed_validation_rescue_todos_for_queue(
                        queue_path=queue_path,
                        policy=ModalOptimizerPolicy(),
                        max_clusters=failed_validation_rescue_max_clusters,
                        rescue_max_attempts=failed_validation_rescue_max_attempts,
                    )
                    summary["latest_paired_failed_validation_rescue"] = dict(
                        rescue_report
                    )
                    summary["paired_failed_validation_rescue_seeded_total"] = int(
                        summary.get("paired_failed_validation_rescue_seeded_total", 0)
                        or 0
                    ) + int(rescue_report.get("seeded_count", 0) or 0)
                    summary["paired_failed_validation_rescue_deduped_total"] = int(
                        summary.get("paired_failed_validation_rescue_deduped_total", 0)
                        or 0
                    ) + int(rescue_report.get("deduped_count", 0) or 0)
                    append_event(
                        log_path,
                        args.run_id,
                        {
                            "event": (
                                "paired_failed_validation_rescue_seeded"
                                if int(rescue_report.get("seeded_count", 0) or 0) > 0
                                else "paired_failed_validation_rescue_not_seeded"
                            ),
                            "program_synthesis_health": program_synthesis_health,
                            "queue_run_id": paired["queue_run_id"],
                            "rescue_report": dict(rescue_report),
                        },
                    )
                    if (
                        int(rescue_report.get("seeded_count", 0) or 0) > 0
                        or int(rescue_report.get("superseded_count", 0) or 0) > 0
                    ):
                        program_synthesis_health = paired_program_synthesis_health(
                            queue_path=queue_path,
                            codex_summary_paths=codex_summary_paths,
                            codex_worker_stale_seconds=codex_worker_stale_seconds,
                        )
                        summary["program_synthesis_health"] = program_synthesis_health
                        for key in (
                            "program_synthesis_pending",
                            "program_synthesis_claimed",
                            "program_synthesis_completed",
                            "program_synthesis_failed_validation",
                            "program_synthesis_superseded",
                            "codex_queue_drained",
                            "codex_queue_open_count",
                            "codex_queue_starved",
                            "codex_workers_active_packet_count",
                            "codex_workers_waiting_for_todos_count",
                            "codex_worker_summary_count",
                            "codex_claimed_total",
                            "codex_execution_count",
                        ):
                            if key in program_synthesis_health:
                                summary[key] = program_synthesis_health[key]
                        codex_queue_starved = bool(
                            program_synthesis_health.get("codex_queue_starved", False)
                        )
                heartbeat_age = autoencoder_health.get(
                    "autoencoder_effective_heartbeat_age_seconds"
                )
                if heartbeat_age is None and not autoencoder_health.get(
                    "autoencoder_summary_exists", False
                ):
                    heartbeat_reference = max(started, last_autoencoder_restart_at or started)
                    heartbeat_age = max(0.0, time.time() - heartbeat_reference)
                restart_cooldown_seconds = (
                    max(30.0, min(autoencoder_stale_seconds, 300.0))
                    if autoencoder_stale_seconds > 0.0
                    else 0.0
                )
                autoencoder_stale = (
                    isinstance(heartbeat_age, (int, float))
                    and autoencoder_stale_seconds > 0.0
                    and float(heartbeat_age) >= autoencoder_stale_seconds
                )
                restart_cooldown_ready = (
                    last_autoencoder_restart_at <= 0.0
                    or (time.time() - last_autoencoder_restart_at)
                    >= restart_cooldown_seconds
                )
                autoencoder_zero_cycle_stalled = bool(
                    autoencoder_stale
                    and autoencoder_health.get("autoencoder_summary_exists", False)
                    and int(autoencoder_health.get("autoencoder_cycles") or 0) <= 0
                )
                summary["autoencoder_zero_cycle_stalled"] = (
                    autoencoder_zero_cycle_stalled
                )
                stale_autoencoder_blocking_codex = bool(
                    codex_queue_starved
                    or codex_queue_missing
                    or codex_prequeue_blocked
                    or autoencoder_zero_cycle_stalled
                )
                if (
                    stale_autoencoder_blocking_codex
                    and auto_exit_code is None
                    and autoencoder_stale
                    and not paired_duration_elapsed
                    and autoencoder_restart_count < autoencoder_restart_limit
                    and restart_cooldown_ready
                ):
                    resource_pressure, pressure_report = _paired_resource_pressure(
                        args,
                        role="autoencoder",
                    )
                    if resource_pressure:
                        now = time.time()
                        last_deferred = restart_resource_defer_last_at.get(
                            str(paired["autoencoder_run_id"]),
                            0.0,
                        )
                        if now - last_deferred >= 60.0:
                            restart_resource_defer_last_at[
                                str(paired["autoencoder_run_id"])
                            ] = now
                            append_event(
                                log_path,
                                args.run_id,
                                {
                                    "event": "paired_autoencoder_stale_restart_deferred",
                                    "autoencoder_child_health": autoencoder_health,
                                    "autoencoder_stale_seconds": autoencoder_stale_seconds,
                                    "autoencoder_zero_cycle_stalled": (
                                        autoencoder_zero_cycle_stalled
                                    ),
                                    "codex_prequeue_blocked": codex_prequeue_blocked,
                                    "codex_queue_starved": codex_queue_starved,
                                    "previous_pid": auto_process.pid,
                                    "program_synthesis_health": program_synthesis_health,
                                    "reason": "resource_pressure",
                                    "resource_pressure": dict(pressure_report),
                                },
                            )
                        summary["latest_restart_deferral"] = {
                            "child_run_id": paired["autoencoder_run_id"],
                            "reason": "resource_pressure",
                            "resource_pressure": dict(pressure_report),
                        }
                        save_summary(summary_path, summary)
                        time.sleep(poll_seconds)
                        continue
                    previous_pid = auto_process.pid
                    restart_reason = (
                        "stale_autoencoder_heartbeat_before_queue_created"
                        if codex_queue_missing
                        else "stale_autoencoder_heartbeat_before_first_cycle"
                        if autoencoder_zero_cycle_stalled
                        else "stale_autoencoder_heartbeat_while_codex_queue_starved"
                    )
                    append_event(
                        log_path,
                        args.run_id,
                        {
                            "event": "paired_autoencoder_stale_restarting",
                            "autoencoder_child_health": autoencoder_health,
                            "autoencoder_stale_seconds": autoencoder_stale_seconds,
                            "autoencoder_zero_cycle_stalled": (
                                autoencoder_zero_cycle_stalled
                            ),
                            "codex_prequeue_blocked": codex_prequeue_blocked,
                            "codex_queue_starved": codex_queue_starved,
                            "previous_pid": previous_pid,
                            "program_synthesis_health": program_synthesis_health,
                            "reason": restart_reason,
                            "restart_count": autoencoder_restart_count + 1,
                        },
                    )
                    previous_exit_code = _terminate_process_with_grace(
                        auto_process,
                        grace_seconds=max(5.0, min(30.0, poll_seconds * 3.0)),
                    )
                    autoencoder_restart_count += 1
                    last_autoencoder_restart_at = time.time()
                    runner_restarted_children.append(
                        {
                            "child_role": "autoencoder",
                            "child_run_id": paired["autoencoder_run_id"],
                            "previous_exit_code": previous_exit_code,
                            "previous_pid": previous_pid,
                            "restarted_at": utc_now(),
                            "restart_count": autoencoder_restart_count,
                            "reason": restart_reason,
                        }
                    )
                    auto_process = start_autoencoder_child(
                        event="paired_child_restarted",
                        previous_pid=previous_pid,
                        restart_count=autoencoder_restart_count,
                    )
                    auto_exit_code = auto_process.poll()
                    summary["autoencoder_pid"] = auto_process.pid
                    summary["autoencoder_exit_code"] = auto_exit_code
                    summary["autoencoder_restart_count"] = autoencoder_restart_count
                    summary["runner_restarted_children"] = list(runner_restarted_children)
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
                if stop_state.stop_requested:
                    break
                if not paired_duration_elapsed and elapsed >= duration_wait:
                    paired_duration_elapsed = True
                    summary["latest_stop_reason"] = "paired_duration_elapsed"
                    summary["paired_duration_elapsed_at"] = utc_now()
                    append_event(
                        log_path,
                        args.run_id,
                        {
                            "event": "paired_duration_elapsed",
                            "elapsed_seconds": round(elapsed, 3),
                            "paired_grace_seconds": float(args.paired_grace_seconds),
                        },
                    )
                    save_summary(summary_path, summary)
                    time.sleep(poll_seconds)
                    continue
                if (time.time() - started) > max_wait:
                    summary["latest_stop_reason"] = "paired_timeout_grace_exceeded"
                    break
                time.sleep(poll_seconds)
    finally:
        process_labels: List[tuple[str, Optional[subprocess.Popen[str]]]] = [
            (str(paired["autoencoder_run_id"]), auto_process),
            *[(run_id, process) for run_id, process in codex_processes.items()],
        ]
        if paired_duration_elapsed:
            grace_deadline = started + max_wait
            termination_wait_seconds = max(
                5.0,
                min(float(args.paired_grace_seconds), grace_deadline - time.time()),
            )
        else:
            termination_wait_seconds = max(
                10.0,
                float(args.paired_grace_seconds),
            )
        termination_results = accelerate_terminate_processes_with_grace(
            process_labels,
            grace_seconds=termination_wait_seconds,
            kill_wait_seconds=5.0,
        )
        for child_run_id, result in termination_results.items():
            if result.initial_exit_code is None:
                runner_terminated_children.add(child_run_id)
        summary["child_termination_results"] = {
            child_run_id: {
                "final_exit_code": result.final_exit_code,
                "initial_exit_code": result.initial_exit_code,
                "kill_sent": result.kill_sent,
                "pid": result.pid,
                "terminate_sent": result.terminate_sent,
                "timed_out": result.timed_out,
            }
            for child_run_id, result in sorted(termination_results.items())
        }

        if auto_process is not None:
            auto_exit_code = auto_process.poll()
        codex_exit_codes = {
            run_id: process.poll()
            for run_id, process in codex_processes.items()
        }

        if stop_state.stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_state.stop_signal}"
            summary["stopped_by_signal"] = stop_state.stop_signal
        summary["elapsed_seconds"] = round(time.time() - started, 3)
        summary["autoencoder_exit_code"] = auto_exit_code
        summary["codex_exit_codes"] = codex_exit_codes
        summary["codex_exit_code"] = next(iter(codex_exit_codes.values()), None)
        summary["codex_worker_exit_restart_counts"] = dict(
            sorted(codex_worker_exit_restart_counts.items())
        )
        summary["codex_worker_stale_restart_counts"] = dict(
            sorted(codex_worker_restart_counts.items())
        )
        summary["runner_terminated_children"] = sorted(runner_terminated_children)
        summary["runner_restarted_children"] = list(runner_restarted_children)
        program_synthesis_health = paired_program_synthesis_health(
            queue_path=queue_path,
            codex_summary_paths=codex_summary_paths,
            codex_worker_stale_seconds=codex_worker_stale_seconds,
        )
        autoencoder_health = paired_autoencoder_child_health(autoencoder_summary_path)
        summary["program_synthesis_health"] = program_synthesis_health
        summary["autoencoder_child_health"] = autoencoder_health
        for key in (
            "program_synthesis_pending",
            "program_synthesis_claimed",
                "program_synthesis_completed",
                "program_synthesis_failed_validation",
                "program_synthesis_superseded",
                "codex_queue_drained",
                "codex_queue_open_count",
                "codex_queue_starved",
                "codex_workers_active_packet_count",
                "codex_workers_waiting_for_todos_count",
            "codex_worker_summary_count",
            "codex_claimed_total",
            "codex_execution_count",
        ):
            if key in program_synthesis_health:
                summary[key] = program_synthesis_health[key]
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
            autoencoder_child_health=autoencoder_health,
            runner_terminated_children=runner_terminated_children,
            stop_requested=stop_state.stop_requested,
        )
        codex_success = _paired_codex_children_succeeded(
            codex_exit_codes,
            autoencoder_exit_code=auto_exit_code,
            autoencoder_success=autoencoder_success,
            runner_terminated_children=runner_terminated_children,
            stop_requested=stop_state.stop_requested,
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
        stop_state.restore()

    autoencoder_success = _paired_autoencoder_succeeded(
        autoencoder_run_id=str(paired["autoencoder_run_id"]),
        autoencoder_exit_code=auto_exit_code,
        autoencoder_child_health=summary.get("autoencoder_child_health"),
        runner_terminated_children=runner_terminated_children,
        stop_requested=stop_state.stop_requested,
    )
    codex_success = _paired_codex_children_succeeded(
        codex_exit_codes,
        autoencoder_exit_code=auto_exit_code,
        autoencoder_success=autoencoder_success,
        runner_terminated_children=runner_terminated_children,
        stop_requested=stop_state.stop_requested,
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

    stop_state = accelerate_install_stop_signal_handlers()

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
    summary["metric_schema_version"] = USCODE_DAEMON_METRIC_SCHEMA_VERSION
    summary["rollout_stage"] = USCODE_DAEMON_ROLLOUT_STAGE
    summary["autoencoder_architecture_version"] = (
        MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    )
    summary["autoencoder_low_rank_state_schema_version"] = (
        MODAL_AUTOENCODER_LOW_RANK_STATE_SCHEMA_VERSION
    )
    summary["autoencoder_state_schema_version"] = (
        MODAL_AUTOENCODER_STATE_SCHEMA_VERSION
    )
    summary.setdefault("active_cycle_phase_timings", {})
    summary.setdefault("latest_cycle_phase_timings", {})
    summary.setdefault("latest_autoencoder_state_telemetry", {})
    bridge_adapters = bridge_loss_adapter_names(args)
    bridge_evaluate_provers = bool(
        getattr(
            args,
            "bridge_evaluate_provers",
            DEFAULT_BRIDGE_EVALUATE_PROVERS,
        )
    )
    bridge_parallel_workers = max(
        1,
        int(getattr(args, "autoencoder_bridge_workers", 1) or 1),
    )
    metric_bridge_adapters = autoencoder_metric_bridge_adapter_names(args, bridge_adapters)
    diagnostic_bridge_adapters = autoencoder_diagnostic_bridge_adapter_names(
        args,
        bridge_adapters,
        metric_bridge_adapters,
    )
    metric_bridge_max_samples = autoencoder_metric_bridge_max_samples(args)
    metric_bridge_max_sample_text_chars = (
        autoencoder_metric_bridge_max_sample_text_chars(args)
    )
    metric_bridge_parallel_workers = max(
        1,
        min(
            bridge_parallel_workers,
            metric_bridge_max_samples if metric_bridge_max_samples > 0 else 1,
        ),
    )
    os.environ["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"] = str(bridge_parallel_workers)
    bridge_parallelism_report = _clamp_nested_bridge_adapter_parallelism(
        bridge_parallel_workers=bridge_parallel_workers,
        sample_parallel_workers=metric_bridge_parallel_workers,
        adapter_count=max(
            len(metric_bridge_adapters),
            len(diagnostic_bridge_adapters),
            1,
        ),
    )
    summary["bridge_loss_adapters"] = bridge_adapters
    summary["bridge_evaluate_provers"] = bridge_evaluate_provers
    summary["autoencoder_bridge_workers"] = bridge_parallel_workers
    summary["legal_ir_bridge_parallelism"] = dict(bridge_parallelism_report)
    summary["autoencoder_metric_bridge_adapters"] = list(metric_bridge_adapters)
    summary["autoencoder_diagnostic_bridge_adapters"] = list(
        diagnostic_bridge_adapters
    )
    summary["autoencoder_diagnostic_bridge_skipped_adapters"] = [
        name for name in bridge_adapters if name not in set(diagnostic_bridge_adapters)
    ]
    summary["autoencoder_metric_bridge_max_samples"] = metric_bridge_max_samples
    summary["autoencoder_metric_bridge_max_sample_text_chars"] = (
        metric_bridge_max_sample_text_chars
    )
    summary["autoencoder_metric_bridge_parallel_workers"] = metric_bridge_parallel_workers
    generalizable_projection_timeout_seconds = max(
        0.0,
        float(
            getattr(
                args,
                "generalizable_projection_timeout_seconds",
                DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS,
            )
            or 0.0
        ),
    )
    generalizable_projection_max_line_search_attempts = max(
        0,
        int(getattr(args, "generalizable_projection_max_line_search_attempts", 0) or 0),
    )
    projection_max_cosine_regression = getattr(
        args,
        "autoencoder_max_cosine_regression",
        None,
    )
    if projection_max_cosine_regression is None:
        projection_max_cosine_regression = getattr(
            args,
            "generalizable_projection_max_cosine_regression",
            0.005,
        )
    projection_max_cosine_regression = max(
        0.0,
        float(projection_max_cosine_regression or 0.0),
    )
    projection_deadband_mode = str(
        getattr(
            args,
            "autoencoder_projection_deadband_mode",
            DEFAULT_AUTOENCODER_PROJECTION_DEADBAND_MODE,
        )
        or DEFAULT_AUTOENCODER_PROJECTION_DEADBAND_MODE
    ).strip().lower()
    if projection_deadband_mode not in {"off", "shadow", "enforce"}:
        projection_deadband_mode = DEFAULT_AUTOENCODER_PROJECTION_DEADBAND_MODE
    projection_max_ce_deadband = max(
        0.0,
        float(
            getattr(
                args,
                "autoencoder_max_ce_deadband",
                DEFAULT_AUTOENCODER_MAX_CE_DEADBAND,
            )
            or 0.0
        ),
    )
    projection_hard_guardrail_metrics = str(
        getattr(
            args,
            "autoencoder_hard_guardrail_metrics",
            ",".join(PROJECTION_DEADBAND_DEFAULT_HARD_GUARDRAILS),
        )
        or ""
    )
    projection_prescreen_mode = str(
        getattr(
            args,
            "autoencoder_projection_prescreen_mode",
            DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_MODE,
        )
        or DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_MODE
    ).strip().lower()
    if projection_prescreen_mode not in {"off", "shadow", "enforce"}:
        projection_prescreen_mode = DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_MODE
    projection_prescreen_top_k = max(
        0,
        int(
            getattr(
                args,
                "autoencoder_projection_prescreen_top_k",
                DEFAULT_AUTOENCODER_PROJECTION_PRESCREEN_TOP_K,
            )
            or 0
        ),
    )
    projection_periodic_full_search_every_n_cycles = max(
        0,
        int(
            getattr(
                args,
                "autoencoder_projection_periodic_full_search_every_n_cycles",
                DEFAULT_AUTOENCODER_PROJECTION_PERIODIC_FULL_SEARCH_EVERY_N_CYCLES,
            )
            or 0
        ),
    )
    compiler_ir_train_mode = str(
        getattr(
            args,
            "compiler_ir_train_mode",
            DEFAULT_COMPILER_IR_TRAIN_MODE,
        )
        or DEFAULT_COMPILER_IR_TRAIN_MODE
    ).strip().lower()
    if compiler_ir_train_mode not in {"every_cycle", "periodic", "off"}:
        compiler_ir_train_mode = DEFAULT_COMPILER_IR_TRAIN_MODE
    compiler_ir_train_every_n_cycles = max(
        1,
        int(
            getattr(
                args,
                "compiler_ir_train_every_n_cycles",
                DEFAULT_COMPILER_IR_TRAIN_EVERY_N_CYCLES,
            )
            or DEFAULT_COMPILER_IR_TRAIN_EVERY_N_CYCLES
        ),
    )
    compiler_ir_guided_train_mode = str(
        getattr(
            args,
            "compiler_ir_guided_train_mode",
            DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE,
        )
        or DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE
    ).strip().lower()
    if compiler_ir_guided_train_mode not in {"every_cycle", "periodic", "off"}:
        compiler_ir_guided_train_mode = DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE
    compiler_ir_guided_train_every_n_cycles = max(
        1,
        int(
            getattr(
                args,
                "compiler_ir_guided_train_every_n_cycles",
                DEFAULT_COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES,
            )
            or DEFAULT_COMPILER_IR_GUIDED_TRAIN_EVERY_N_CYCLES
        ),
    )
    autoencoder_before_train_eval_mode = str(
        getattr(
            args,
            "autoencoder_before_train_eval_mode",
            DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE,
        )
        or DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE
    ).strip().lower()
    if autoencoder_before_train_eval_mode not in {"every_cycle", "periodic", "off"}:
        autoencoder_before_train_eval_mode = DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE
    autoencoder_before_train_eval_every_n_cycles = max(
        1,
        int(
            getattr(
                args,
                "autoencoder_before_train_eval_every_n_cycles",
                DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES,
            )
            or DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_EVERY_N_CYCLES
        ),
    )
    autoencoder_sample_memory_probe_mode = str(
        getattr(
            args,
            "autoencoder_sample_memory_probe_mode",
            DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE,
        )
        or DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE
    ).strip().lower()
    if autoencoder_sample_memory_probe_mode not in {"every_cycle", "periodic", "off"}:
        autoencoder_sample_memory_probe_mode = (
            DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE
        )
    autoencoder_sample_memory_probe_every_n_cycles = max(
        1,
        int(
            getattr(
                args,
                "autoencoder_sample_memory_probe_every_n_cycles",
                DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES,
            )
            or DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_EVERY_N_CYCLES
        ),
    )
    autoencoder_todo_supervisor_mode = str(
        getattr(
            args,
            "autoencoder_todo_supervisor_mode",
            DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE,
        )
        or DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE
    ).strip().lower()
    if autoencoder_todo_supervisor_mode not in {"every_cycle", "starved", "off"}:
        autoencoder_todo_supervisor_mode = DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE
    autoencoder_todo_supervisor_min_open = max(
        1,
        int(
            getattr(
                args,
                "autoencoder_todo_supervisor_min_open",
                DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN,
            )
            or DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MIN_OPEN
        ),
    )
    summary["generalizable_projection_timeout_seconds"] = (
        generalizable_projection_timeout_seconds
    )
    summary["generalizable_projection_max_line_search_attempts"] = (
        generalizable_projection_max_line_search_attempts
    )
    summary["autoencoder_projection_deadband"] = {
        "hard_guardrail_metrics": [
            value.strip()
            for value in projection_hard_guardrail_metrics.split(",")
            if value.strip()
        ],
        "max_ce_deadband": projection_max_ce_deadband,
        "max_cosine_regression": projection_max_cosine_regression,
        "mode": projection_deadband_mode,
    }
    summary["autoencoder_projection_prescreen"] = {
        "mode": projection_prescreen_mode,
        "periodic_full_search_every_n_cycles": (
            projection_periodic_full_search_every_n_cycles
        ),
        "top_k": projection_prescreen_top_k,
    }
    summary["compiler_ir_train"] = {
        "every_n_cycles": compiler_ir_train_every_n_cycles,
        "mode": compiler_ir_train_mode,
    }
    summary["compiler_ir_guided_train"] = {
        "every_n_cycles": compiler_ir_guided_train_every_n_cycles,
        "mode": compiler_ir_guided_train_mode,
    }
    summary["autoencoder_before_train_eval"] = {
        "every_n_cycles": autoencoder_before_train_eval_every_n_cycles,
        "mode": autoencoder_before_train_eval_mode,
    }
    summary["autoencoder_sample_memory_probe"] = {
        "every_n_cycles": autoencoder_sample_memory_probe_every_n_cycles,
        "mode": autoencoder_sample_memory_probe_mode,
    }
    summary["autoencoder_todo_supervisor"] = {
        "min_open": autoencoder_todo_supervisor_min_open,
        "mode": autoencoder_todo_supervisor_mode,
    }
    summary["autoencoder_bootstrap_program_synthesis_todos"] = bool(
        getattr(args, "autoencoder_bootstrap_program_synthesis_todos", True)
    )
    summary["autoencoder_bootstrap_mode"] = str(
        getattr(args, "autoencoder_bootstrap_mode", "fast")
    )
    summary["autoencoder_bootstrap_min_pending"] = max(
        0,
        int(getattr(args, "autoencoder_bootstrap_min_pending", 1) or 0),
    )
    summary.setdefault("program_synthesis_bootstrap_attempts", 0)
    summary.setdefault("program_synthesis_bootstrap_deduped_total", 0)
    summary.setdefault("program_synthesis_bootstrap_seeded_total", 0)
    summary.setdefault("program_synthesis_bootstrap_semantic_deduped_total", 0)
    summary["active_cycle"] = None
    summary["active_cycle_bridge_loss_adapters"] = []
    summary["active_cycle_metric_bridge_adapters"] = []
    summary["active_cycle_metric_bridge_max_samples"] = 0
    summary["active_cycle_elapsed_seconds"] = 0.0
    summary["active_cycle_last_heartbeat_at"] = None
    summary["active_cycle_metric_progress"] = {}
    summary["active_cycle_phase"] = None
    summary["active_cycle_phase_timings"] = {}
    summary["active_cycle_started_at"] = None
    summary["active_cycle_train_count"] = 0
    summary["active_cycle_validation_count"] = 0
    try:
        bridge_adapter_workers = int(
            os.environ.get("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS", "1") or 1
        )
    except ValueError:
        bridge_adapter_workers = 1
    summary["bridge_adapter_workers"] = max(1, bridge_adapter_workers)
    summary["max_sample_text_chars"] = int(getattr(args, "max_sample_text_chars", 0) or 0)
    compiler_ir_metric_max_sample_text_chars = max(
        0,
        int(
            getattr(
                args,
                "compiler_ir_metric_max_sample_text_chars",
                DEFAULT_COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS,
            )
            or 0
        ),
    )
    compiler_ir_metric_sample_timeout_seconds = max(
        0.0,
        float(
            getattr(
                args,
                "compiler_ir_metric_sample_timeout_seconds",
                DEFAULT_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS,
            )
            or 0.0
        ),
    )
    compiler_ir_metric_text_policy = _normalise_compiler_ir_metric_text_policy(
        getattr(
            args,
            "compiler_ir_metric_text_policy",
            DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY,
        )
    )
    summary["compiler_ir_metric_max_sample_text_chars"] = (
        compiler_ir_metric_max_sample_text_chars
    )
    summary["compiler_ir_metric_text_policy"] = compiler_ir_metric_text_policy
    summary["compiler_ir_metric_sample_timeout_seconds"] = (
        compiler_ir_metric_sample_timeout_seconds
    )
    summary.setdefault("bridge_loss_failures", 0)
    summary.setdefault("bridge_loss_samples", 0)
    summary.setdefault("bridge_loss_signals", 0)
    summary.setdefault("bridge_metric_failures", 0)
    summary.setdefault("best_validation_ir_guided_ce", 1.0e12)
    summary.setdefault("best_validation_ir_guided_ce_excess", 1.0e12)
    summary.setdefault("best_validation_ir_guided_cosine", -1.0)
    summary.setdefault(
        "best_validation_ir_guided_source_copy_reward_hack_penalty",
        1.0e12,
    )
    summary.setdefault("best_validation_ir_source_copy_loss", 1.0e12)
    summary.setdefault(
        "best_validation_ir_source_decompiled_text_embedding_cosine_loss",
        1.0e12,
    )
    summary.setdefault("best_validation_ir_source_decompiled_text_token_loss", 1.0e12)
    summary.setdefault("best_validation_ir_structural_text_reconstruction", 1.0e12)
    summary.setdefault("best_validation_learned_ir_family_ce_excess", 1.0e12)
    summary.setdefault("best_validation_learned_ir_view_ce", 1.0e12)
    summary.setdefault("best_validation_learned_ir_view_cosine", -1.0)
    summary.setdefault("best_validation_learned_ir_worst_family_ce_excess", 1.0e12)
    summary.setdefault("best_validation_learned_ir_worst_family_cosine_gap", 1.0e12)
    summary.setdefault("best_validation_logic_bridge_acceptance", -1.0)
    summary.setdefault("best_validation_logic_bridge_proof_failure_ratio", 1.0e12)
    summary.setdefault("best_validation_logic_bridge_total_loss", 1.0e12)
    started_at = parse_utc(summary["started_at"])
    end_at = started_at + args.duration_seconds
    cycle_start_margin_seconds = 8.0
    summary["autoencoder_cycle_start_margin_seconds"] = cycle_start_margin_seconds
    state = ModalAutoencoderTrainingState.load_json(state_path)
    low_rank_load = autoencoder_low_rank_load_report(state, state_path=state_path)
    summary["autoencoder_low_rank_load"] = low_rank_load
    if low_rank_load.get("dense_state_hydrated"):
        append_event(
            log_path,
            args.run_id,
            {"event": "autoencoder_low_rank_loaded", "low_rank_load": low_rank_load},
        )
    summary["latest_autoencoder_state_telemetry"] = autoencoder_state_telemetry(
        state,
        state_path=state_path,
    )
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
            summary["latest_autoencoder_state_telemetry"] = (
                autoencoder_state_telemetry(state, state_path=state_path)
            )
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
            getattr(args, "autoencoder_cosine_reconstruction_weight", 0.5)
        ),
        max_token_features=int(getattr(args, "autoencoder_max_token_features", 48)),
        max_token_bigram_features=int(
            getattr(args, "autoencoder_max_token_bigram_features", 24)
        ),
        max_token_trigram_features=int(
            getattr(args, "autoencoder_max_token_trigram_features", 12)
        ),
        max_codec_feature_keys=int(
            getattr(args, "autoencoder_max_codec_feature_keys", 0)
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
        max_legal_semantic_frame_features=int(
            getattr(args, "autoencoder_max_legal_semantic_frame_features", 64)
        ),
        max_normative_polarity_features=int(
            getattr(args, "autoencoder_max_normative_polarity_features", 48)
        ),
        max_compiler_contract_features=int(
            getattr(args, "autoencoder_max_compiler_contract_features", 64)
        ),
        max_decompiler_surface_template_features=int(
            getattr(args, "autoencoder_max_decompiler_surface_template_features", 48)
        ),
        max_canonical_ir_graph_features=int(
            getattr(args, "autoencoder_max_canonical_ir_graph_features", 64)
        ),
        max_cycle_consistency_features=int(
            getattr(args, "autoencoder_max_cycle_consistency_features", 64)
        ),
        max_equivalence_prototype_features=int(
            getattr(args, "autoencoder_max_equivalence_prototype_features", 48)
        ),
        max_contrastive_ir_boundary_features=int(
            getattr(args, "autoencoder_max_contrastive_ir_boundary_features", 64)
        ),
        max_repair_plan_features=int(
            getattr(args, "autoencoder_max_repair_plan_features", 64)
        ),
        max_logic_view_contract_features=int(
            getattr(args, "autoencoder_max_logic_view_contract_features", 64)
        ),
        max_objective_residual_features=int(
            getattr(args, "autoencoder_max_objective_residual_features", 64)
        ),
        max_provenance_alignment_features=int(
            getattr(args, "autoencoder_max_provenance_alignment_features", 64)
        ),
        max_discourse_flow_features=int(
            getattr(args, "autoencoder_max_discourse_flow_features", 64)
        ),
        max_proof_obligation_features=int(
            getattr(args, "autoencoder_max_proof_obligation_features", 64)
        ),
        max_entity_binding_features=int(
            getattr(args, "autoencoder_max_entity_binding_features", 64)
        ),
        max_defeasible_priority_features=int(
            getattr(args, "autoencoder_max_defeasible_priority_features", 64)
        ),
        max_constraint_grounding_features=int(
            getattr(args, "autoencoder_max_constraint_grounding_features", 64)
        ),
        max_quantitative_formula_features=int(
            getattr(args, "autoencoder_max_quantitative_formula_features", 64)
        ),
        max_definition_grounding_features=int(
            getattr(args, "autoencoder_max_definition_grounding_features", 64)
        ),
        max_quantifier_scope_features=int(
            getattr(args, "autoencoder_max_quantifier_scope_features", 64)
        ),
        max_procedural_lifecycle_features=int(
            getattr(args, "autoencoder_max_procedural_lifecycle_features", 64)
        ),
        max_enforcement_remedy_features=int(
            getattr(args, "autoencoder_max_enforcement_remedy_features", 64)
        ),
        max_mental_state_features=int(
            getattr(args, "autoencoder_max_mental_state_features", 64)
        ),
        max_reference_dependency_features=int(
            getattr(args, "autoencoder_max_reference_dependency_features", 64)
        ),
        max_amendment_operation_features=int(
            getattr(args, "autoencoder_max_amendment_operation_features", 64)
        ),
        max_authority_jurisdiction_features=int(
            getattr(args, "autoencoder_max_authority_jurisdiction_features", 64)
        ),
        max_discretion_standard_features=int(
            getattr(args, "autoencoder_max_discretion_standard_features", 64)
        ),
        max_temporal_validity_features=int(
            getattr(args, "autoencoder_max_temporal_validity_features", 64)
        ),
        max_evidentiary_burden_features=int(
            getattr(args, "autoencoder_max_evidentiary_burden_features", 64)
        ),
        max_legal_relation_features=int(
            getattr(args, "autoencoder_max_legal_relation_features", 64)
        ),
        max_status_transition_features=int(
            getattr(args, "autoencoder_max_status_transition_features", 64)
        ),
        max_condition_consequence_features=int(
            getattr(args, "autoencoder_max_condition_consequence_features", 64)
        ),
        max_applicability_scope_features=int(
            getattr(args, "autoencoder_max_applicability_scope_features", 64)
        ),
        max_coreference_binding_features=int(
            getattr(args, "autoencoder_max_coreference_binding_features", 64)
        ),
        max_logical_connective_features=int(
            getattr(args, "autoencoder_max_logical_connective_features", 64)
        ),
        max_enumeration_hierarchy_features=int(
            getattr(args, "autoencoder_max_enumeration_hierarchy_features", 64)
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
        getattr(args, "autoencoder_cosine_reconstruction_weight", 0.5)
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
    summary["autoencoder_max_codec_feature_keys"] = int(
        getattr(args, "autoencoder_max_codec_feature_keys", 0)
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
    summary["autoencoder_max_legal_semantic_frame_features"] = int(
        getattr(args, "autoencoder_max_legal_semantic_frame_features", 64)
    )
    summary["autoencoder_max_normative_polarity_features"] = int(
        getattr(args, "autoencoder_max_normative_polarity_features", 48)
    )
    summary["autoencoder_max_compiler_contract_features"] = int(
        getattr(args, "autoencoder_max_compiler_contract_features", 64)
    )
    summary["autoencoder_max_decompiler_surface_template_features"] = int(
        getattr(args, "autoencoder_max_decompiler_surface_template_features", 48)
    )
    summary["autoencoder_max_canonical_ir_graph_features"] = int(
        getattr(args, "autoencoder_max_canonical_ir_graph_features", 64)
    )
    summary["autoencoder_max_cycle_consistency_features"] = int(
        getattr(args, "autoencoder_max_cycle_consistency_features", 64)
    )
    summary["autoencoder_max_equivalence_prototype_features"] = int(
        getattr(args, "autoencoder_max_equivalence_prototype_features", 48)
    )
    summary["autoencoder_max_contrastive_ir_boundary_features"] = int(
        getattr(args, "autoencoder_max_contrastive_ir_boundary_features", 64)
    )
    summary["autoencoder_max_repair_plan_features"] = int(
        getattr(args, "autoencoder_max_repair_plan_features", 64)
    )
    summary["autoencoder_max_logic_view_contract_features"] = int(
        getattr(args, "autoencoder_max_logic_view_contract_features", 64)
    )
    summary["autoencoder_max_objective_residual_features"] = int(
        getattr(args, "autoencoder_max_objective_residual_features", 64)
    )
    summary["autoencoder_max_provenance_alignment_features"] = int(
        getattr(args, "autoencoder_max_provenance_alignment_features", 64)
    )
    summary["autoencoder_max_discourse_flow_features"] = int(
        getattr(args, "autoencoder_max_discourse_flow_features", 64)
    )
    summary["autoencoder_max_proof_obligation_features"] = int(
        getattr(args, "autoencoder_max_proof_obligation_features", 64)
    )
    summary["autoencoder_max_entity_binding_features"] = int(
        getattr(args, "autoencoder_max_entity_binding_features", 64)
    )
    summary["autoencoder_max_defeasible_priority_features"] = int(
        getattr(args, "autoencoder_max_defeasible_priority_features", 64)
    )
    summary["autoencoder_max_constraint_grounding_features"] = int(
        getattr(args, "autoencoder_max_constraint_grounding_features", 64)
    )
    summary["autoencoder_max_quantitative_formula_features"] = int(
        getattr(args, "autoencoder_max_quantitative_formula_features", 64)
    )
    summary["autoencoder_max_definition_grounding_features"] = int(
        getattr(args, "autoencoder_max_definition_grounding_features", 64)
    )
    summary["autoencoder_max_quantifier_scope_features"] = int(
        getattr(args, "autoencoder_max_quantifier_scope_features", 64)
    )
    summary["autoencoder_max_procedural_lifecycle_features"] = int(
        getattr(args, "autoencoder_max_procedural_lifecycle_features", 64)
    )
    summary["autoencoder_max_enforcement_remedy_features"] = int(
        getattr(args, "autoencoder_max_enforcement_remedy_features", 64)
    )
    summary["autoencoder_max_mental_state_features"] = int(
        getattr(args, "autoencoder_max_mental_state_features", 64)
    )
    summary["autoencoder_max_reference_dependency_features"] = int(
        getattr(args, "autoencoder_max_reference_dependency_features", 64)
    )
    summary["autoencoder_max_amendment_operation_features"] = int(
        getattr(args, "autoencoder_max_amendment_operation_features", 64)
    )
    summary["autoencoder_max_authority_jurisdiction_features"] = int(
        getattr(args, "autoencoder_max_authority_jurisdiction_features", 64)
    )
    summary["autoencoder_max_discretion_standard_features"] = int(
        getattr(args, "autoencoder_max_discretion_standard_features", 64)
    )
    summary["autoencoder_max_temporal_validity_features"] = int(
        getattr(args, "autoencoder_max_temporal_validity_features", 64)
    )
    summary["autoencoder_max_evidentiary_burden_features"] = int(
        getattr(args, "autoencoder_max_evidentiary_burden_features", 64)
    )
    summary["autoencoder_max_legal_relation_features"] = int(
        getattr(args, "autoencoder_max_legal_relation_features", 64)
    )
    summary["autoencoder_max_status_transition_features"] = int(
        getattr(args, "autoencoder_max_status_transition_features", 64)
    )
    summary["autoencoder_max_condition_consequence_features"] = int(
        getattr(args, "autoencoder_max_condition_consequence_features", 64)
    )
    summary["autoencoder_max_applicability_scope_features"] = int(
        getattr(args, "autoencoder_max_applicability_scope_features", 64)
    )
    summary["autoencoder_max_coreference_binding_features"] = int(
        getattr(args, "autoencoder_max_coreference_binding_features", 64)
    )
    summary["autoencoder_max_logical_connective_features"] = int(
        getattr(args, "autoencoder_max_logical_connective_features", 64)
    )
    summary["autoencoder_max_enumeration_hierarchy_features"] = int(
        getattr(args, "autoencoder_max_enumeration_hierarchy_features", 64)
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
        bridge_names=metric_bridge_adapters,
        bridge_evaluate_provers=bridge_evaluate_provers,
        bridge_loss_evaluator=bridge_loss_evaluator_for_names(
            bridge_adapters,
            evaluate_provers=bridge_evaluate_provers,
            parallel_workers=bridge_parallel_workers,
        ),
        bridge_metric_max_samples=metric_bridge_max_samples,
        bridge_parallel_workers=metric_bridge_parallel_workers,
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
    embedding_lookup = load_uscode_embedding_lookup(args)
    summary["embedding_target_report"] = embedding_lookup.report()
    save_summary(summary_path, summary)
    append_event(
        log_path,
        args.run_id,
        {
            "embedding_target_report": embedding_lookup.report(),
            "event": "detached_embedding_lookup_loaded",
        },
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
        raw_canary_indices = str(
            getattr(args, "validation_canary_indices", "") or ""
        ).strip()
        if raw_canary_indices:
            for item in raw_canary_indices.split(","):
                try:
                    index = int(item.strip())
                except (TypeError, ValueError):
                    continue
                if 0 <= index < laws_table.num_rows:
                    stored_canary_indices.append(index)
        for raw_index in list(summary.get("validation_canary_indices", []) or []):
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if 0 <= index < laws_table.num_rows and index not in stored_canary_indices:
                stored_canary_indices.append(index)
        for index in stored_canary_indices[:validation_canary_count]:
            row = laws_table.take([index]).to_pylist()[0]
            if not _row_text_within_limit(
                row,
                int(getattr(args, "max_sample_text_chars", 0) or 0),
            ):
                continue
            validation_canary_indices.append(index)
            validation_canary_samples.append(
                row_to_sample(row, embedding_lookup=embedding_lookup)
            )
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
                embedding_lookup=embedding_lookup,
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
        summary["embedding_target_report"] = embedding_lookup.report()
        save_summary(summary_path, summary)
        append_event(
            log_path,
            args.run_id,
            {
                "embedding_target_report": embedding_lookup.report(),
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
    metric_progress_lock = threading.RLock()
    phase_timer_state: Dict[str, Any] = {
        "cycle": None,
        "phase": None,
        "started_at": None,
        "timings": {},
    }

    def rounded_phase_timings() -> Dict[str, float]:
        timings = phase_timer_state.get("timings", {})
        if not isinstance(timings, Mapping):
            return {}
        return {
            str(phase): round(float(seconds), 3)
            for phase, seconds in sorted(timings.items())
        }

    def close_active_phase(*, cycle: int, now: float | None = None) -> Dict[str, float]:
        if phase_timer_state.get("cycle") != int(cycle):
            return rounded_phase_timings()
        timestamp = time.time() if now is None else float(now)
        phase = phase_timer_state.get("phase")
        started = phase_timer_state.get("started_at")
        if phase and started is not None:
            elapsed = max(0.0, timestamp - float(started))
            timings = phase_timer_state.setdefault("timings", {})
            if isinstance(timings, MutableMapping):
                phase_name = str(phase)
                timings[phase_name] = float(timings.get(phase_name, 0.0)) + elapsed
        phase_timer_state["phase"] = None
        phase_timer_state["started_at"] = None
        return rounded_phase_timings()

    def mark_active_autoencoder_cycle(
        *,
        cycle: int,
        cycle_started: float,
        cycle_started_at: str,
        phase: str,
        train_count: int | None = None,
        validation_count: int | None = None,
        train_indices: Sequence[int] | None = None,
        validation_indices: Sequence[int] | None = None,
    ) -> None:
        with metric_progress_lock:
            now = time.time()
            if phase_timer_state.get("cycle") != int(cycle):
                phase_timer_state["cycle"] = int(cycle)
                phase_timer_state["phase"] = None
                phase_timer_state["started_at"] = None
                phase_timer_state["timings"] = {}
            else:
                close_active_phase(cycle=int(cycle), now=now)
            phase_timer_state["cycle"] = int(cycle)
            phase_timer_state["phase"] = str(phase)
            phase_timer_state["started_at"] = now
            summary["active_cycle"] = int(cycle)
            summary["active_cycle_bridge_loss_adapters"] = list(bridge_adapters)
            summary["active_cycle_metric_bridge_adapters"] = list(metric_bridge_adapters)
            summary["active_cycle_diagnostic_bridge_adapters"] = list(
                diagnostic_bridge_adapters
            )
            summary["active_cycle_metric_bridge_max_samples"] = int(
                metric_bridge_max_samples
            )
            summary["active_cycle_elapsed_seconds"] = round(
                time.time() - cycle_started,
                3,
            )
            summary["active_cycle_last_heartbeat_at"] = utc_now()
            summary["active_cycle_phase"] = phase
            summary["active_cycle_phase_timings"] = rounded_phase_timings()
            if phase != "generalizable_projection":
                summary["active_cycle_projection_progress"] = {}
                summary["active_cycle_projection_stage"] = None
            summary["active_cycle_metric_progress"] = {}
            summary["active_cycle_started_at"] = cycle_started_at
            summary["active_cycle_train_count"] = (
                int(args.train_count) if train_count is None else int(train_count)
            )
            summary["active_cycle_validation_count"] = (
                int(args.validation_count)
                if validation_count is None
                else int(validation_count)
            )
            if train_indices is not None:
                summary["active_cycle_train_indices"] = list(train_indices)
            if validation_indices is not None:
                summary["active_cycle_validation_indices"] = list(validation_indices)
            save_summary(summary_path, summary)

    def clear_active_autoencoder_cycle() -> None:
        with metric_progress_lock:
            summary["active_cycle"] = None
            summary["active_cycle_bridge_loss_adapters"] = []
            summary["active_cycle_metric_bridge_adapters"] = []
            summary["active_cycle_diagnostic_bridge_adapters"] = []
            summary["active_cycle_metric_bridge_max_samples"] = 0
            summary["active_cycle_elapsed_seconds"] = 0.0
            summary["active_cycle_last_heartbeat_at"] = None
            summary["active_cycle_metric_progress"] = {}
            summary["active_cycle_phase"] = None
            summary["active_cycle_phase_timings"] = {}
            summary["active_cycle_projection_progress"] = {}
            summary["active_cycle_projection_stage"] = None
            summary["active_cycle_started_at"] = None
            summary["active_cycle_train_count"] = 0
            summary["active_cycle_validation_count"] = 0
            summary["active_cycle_train_indices"] = []
            summary["active_cycle_validation_indices"] = []
            phase_timer_state["cycle"] = None
            phase_timer_state["phase"] = None
            phase_timer_state["started_at"] = None
            phase_timer_state["timings"] = {}

    def apply_queue_summary(queue_snapshot: ModalTodoQueue) -> Dict[str, Any]:
        status = update_program_synthesis_summary(
            summary,
            queue_snapshot,
            supervisor.policy,
            execution_mode="queued_for_external_codex_worker",
        )
        summary["latest_queue_counts"] = queue_snapshot.status_counts()
        summary["latest_role_queue_counts"] = queue_snapshot.role_status_counts()
        return status

    def refresh_queue_summary_from_disk() -> Dict[str, Any]:
        with queue_file_lock(queue_path):
            latest_queue = ModalTodoQueue.load_jsonl(queue_path)
        with metric_progress_lock:
            status = apply_queue_summary(latest_queue)
            summary["active_cycle_queue_refresh"] = {
                "at": utc_now(),
                "mode": "summary_snapshot",
                "queue_counts": latest_queue.status_counts(),
                "role_queue_counts": latest_queue.role_status_counts(),
            }
        return status

    def refresh_supervisor_queue_from_disk(
        target_supervisor: ModalTodoSupervisor,
    ) -> None:
        nonlocal queue
        with queue_file_lock(queue_path):
            latest_queue = ModalTodoQueue.load_jsonl(queue_path)
            latest_queue.merge_from(
                target_supervisor.queue,
                preserve_claimed_role=target_supervisor.policy.program_synthesis_role,
            )
            latest_queue.save_jsonl(queue_path)
            target_supervisor.queue = latest_queue
            queue = latest_queue
        with metric_progress_lock:
            status = apply_queue_summary(target_supervisor.queue)
            summary["active_cycle_queue_refresh"] = {
                "at": utc_now(),
                "mode": "supervisor_merge",
                "program_synthesis_status": status,
                "queue_counts": target_supervisor.queue.status_counts(),
                "role_queue_counts": target_supervisor.queue.role_status_counts(),
            }

    def record_todo_optimizer_progress(progress: Mapping[str, Any]) -> None:
        with metric_progress_lock:
            payload = dict(progress)
            cycle_started_value = summary.get("active_cycle_started_at")
            payload["active_cycle_elapsed_seconds"] = summary.get(
                "active_cycle_elapsed_seconds",
                0.0,
            )
            payload["active_cycle_started_at"] = cycle_started_value
            payload["at"] = utc_now()
            summary["active_cycle_todo_optimizer_progress"] = payload
            summary["active_cycle_last_heartbeat_at"] = payload["at"]
            summary["updated_at"] = payload["at"]
            if "queue_counts" in payload:
                summary["latest_queue_counts"] = dict(payload.get("queue_counts") or {})
            if "role_queue_counts" in payload:
                summary["latest_role_queue_counts"] = dict(
                    payload.get("role_queue_counts") or {}
                )
            save_summary(summary_path, summary)

    @contextmanager
    def active_cycle_heartbeat(
        *,
        cycle: int,
        cycle_started: float,
        phase: str,
        interval_seconds: float = 10.0,
    ) -> Iterator[None]:
        """Refresh the child summary while a long synchronous phase is running."""

        stop_event = threading.Event()
        interval = max(1.0, float(interval_seconds))

        def pulse() -> None:
            while not stop_event.wait(interval):
                with metric_progress_lock:
                    if summary.get("active_cycle") != int(cycle):
                        continue
                    if str(summary.get("active_cycle_phase") or "") != str(phase):
                        continue
                    summary["active_cycle_elapsed_seconds"] = round(
                        time.time() - cycle_started,
                        3,
                    )
                    summary["active_cycle_last_heartbeat_at"] = utc_now()
                    summary["active_cycle_long_phase_heartbeat"] = {
                        "phase": str(phase),
                        "heartbeat_interval_seconds": interval,
                    }
                    try:
                        refresh_queue_summary_from_disk()
                    except Exception as exc:
                        summary["active_cycle_queue_refresh"] = {
                            "at": utc_now(),
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "mode": "summary_snapshot",
                        }
                    save_summary(summary_path, summary)

        thread = threading.Thread(
            target=pulse,
            name=f"{args.run_id}-{phase}-heartbeat",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1.0)
            with metric_progress_lock:
                if (
                    summary.get("active_cycle") == int(cycle)
                    and str(summary.get("active_cycle_phase") or "") == str(phase)
                ):
                    summary["active_cycle_elapsed_seconds"] = round(
                        time.time() - cycle_started,
                        3,
                    )
                    summary["active_cycle_last_heartbeat_at"] = utc_now()
                    summary["active_cycle_long_phase_heartbeat"] = {
                        "phase": str(phase),
                        "heartbeat_interval_seconds": interval,
                        "final": True,
                    }
                    try:
                        refresh_queue_summary_from_disk()
                    except Exception as exc:
                        summary["active_cycle_queue_refresh"] = {
                            "at": utc_now(),
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "mode": "summary_snapshot",
                        }
                    save_summary(summary_path, summary)

    def sampled_bridge_metric_samples(
        samples: Sequence[Any],
        *,
        cycle: int,
    ) -> List[Any]:
        sample_list = list(samples)
        if not sample_list or metric_bridge_max_samples <= 0:
            return []
        if len(sample_list) <= metric_bridge_max_samples:
            return autoencoder_metric_bridge_samples_for_evaluation(
                sample_list,
                max_sample_text_chars=metric_bridge_max_sample_text_chars,
            )
        start = ((max(1, int(cycle)) - 1) * metric_bridge_max_samples) % len(sample_list)
        selected = [
            sample_list[(start + offset) % len(sample_list)]
            for offset in range(metric_bridge_max_samples)
        ]
        return autoencoder_metric_bridge_samples_for_evaluation(
            selected,
            max_sample_text_chars=metric_bridge_max_sample_text_chars,
        )

    def record_metric_progress(
        *,
        cycle: int,
        cycle_started: float,
        phase: str,
        stage: str,
        sample_count: int,
        bridge_sample_count: int = 0,
        bridge_sample_ids: Sequence[str] = (),
        error: Optional[BaseException] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "bridge_adapters": list(metric_bridge_adapters),
            "bridge_sample_count": int(bridge_sample_count),
            "bridge_sample_ids": list(bridge_sample_ids),
            "cycle": int(cycle),
            "elapsed_seconds": round(time.time() - cycle_started, 3),
            "phase": str(phase),
            "sample_count": int(sample_count),
            "stage": str(stage),
        }
        if error is not None:
            payload["error"] = str(error)
            payload["error_type"] = type(error).__name__
        if extra:
            payload.update(dict(extra))
        with metric_progress_lock:
            summary["active_cycle_elapsed_seconds"] = payload["elapsed_seconds"]
            summary["active_cycle_last_heartbeat_at"] = utc_now()
            summary["active_cycle_metric_progress"] = payload
            save_summary(summary_path, summary)

    def metric_progress_callback(
        *,
        cycle: int,
        cycle_started: float,
        phase: str,
        dataset: str,
        sample_count: int,
        bridge_sample_count: int = 0,
        bridge_sample_ids: Sequence[str] = (),
    ) -> Callable[[Mapping[str, Any]], None]:
        def callback(update: Mapping[str, Any]) -> None:
            detail = dict(update)
            stage = str(detail.get("stage") or "update")
            record_metric_progress(
                cycle=cycle,
                cycle_started=cycle_started,
                phase=phase,
                stage=f"{dataset}_{stage}",
                sample_count=sample_count,
                bridge_sample_count=bridge_sample_count,
                bridge_sample_ids=bridge_sample_ids,
                extra={
                    "dataset": dataset,
                    "metric_detail": detail,
                },
            )

        return callback

    def cuda_oom_error(exc: BaseException) -> bool:
        text = f"{type(exc).__module__}.{type(exc).__name__}: {exc}".lower()
        return "cuda" in text and (
            "out of memory" in text
            or "memoryallocation" in text
            or "cuda errormemoryallocation" in text
        )

    def fallback_autoencoder_compute_to_python(
        *,
        cycle: int,
        cycle_started: float,
        phase: str,
        stage: str,
        error: BaseException,
    ) -> None:
        previous_backend = getattr(autoencoder, "compute_backend", "")
        previous_device = str(getattr(autoencoder, "compute_device", None) or "")
        autoencoder._torch = None
        autoencoder.compute_device = None
        autoencoder.compute_backend = "python_cuda_oom_fallback"
        fallback_record = {
            "at": utc_now(),
            "cycle": int(cycle),
            "elapsed_seconds": round(time.time() - cycle_started, 3),
            "error": str(error),
            "error_type": type(error).__name__,
            "phase": str(phase),
            "previous_backend": str(previous_backend),
            "previous_device": previous_device,
            "stage": str(stage),
        }
        summary["autoencoder_compute_fallback"] = fallback_record
        summary["autoencoder_compute_fallback_count"] = int(
            summary.get("autoencoder_compute_fallback_count", 0) or 0
        ) + 1
        summary.update(autoencoder.compute_backend_metadata())
        record_metric_progress(
            cycle=cycle,
            cycle_started=cycle_started,
            phase=phase,
            stage=f"{stage}_cuda_oom_fallback",
            sample_count=int(summary.get("active_cycle_train_count", 0) or 0),
            error=error,
        )
        append_event(
            log_path,
            args.run_id,
            {
                "event": "autoencoder_cuda_oom_fallback",
                **fallback_record,
            },
        )

    def evaluate_autoencoder_cycle_metrics(
        samples: Sequence[Any],
        *,
        cycle: int,
        cycle_started: float,
        phase: str,
        use_sample_memory: bool = True,
    ):
        sample_list = list(samples)
        bridge_samples = (
            sampled_bridge_metric_samples(sample_list, cycle=cycle)
            if metric_bridge_adapters
            else []
        )
        bridge_sample_ids = [
            str(getattr(sample, "sample_id", "") or "")
            for sample in bridge_samples
        ]
        record_metric_progress(
            cycle=cycle,
            cycle_started=cycle_started,
            phase=phase,
            stage="base_evaluation_start",
            sample_count=len(sample_list),
            bridge_sample_count=len(bridge_samples),
            bridge_sample_ids=bridge_sample_ids,
        )
        try:
            base = autoencoder.evaluate(
                sample_list,
                legal_ir_bridge_names=(),
                legal_ir_evaluate_provers=bridge_evaluate_provers,
                legal_ir_parallel_workers=1,
                use_sample_memory=use_sample_memory,
            )
        except Exception as exc:
            if not cuda_oom_error(exc):
                raise
            fallback_autoencoder_compute_to_python(
                cycle=cycle,
                cycle_started=cycle_started,
                phase=phase,
                stage="base_evaluation",
                error=exc,
            )
            base = autoencoder.evaluate(
                sample_list,
                legal_ir_bridge_names=(),
                legal_ir_evaluate_provers=bridge_evaluate_provers,
                legal_ir_parallel_workers=1,
                use_sample_memory=use_sample_memory,
            )
        if not bridge_samples:
            record_metric_progress(
                cycle=cycle,
                cycle_started=cycle_started,
                phase=phase,
                stage="base_evaluation_done",
                sample_count=len(sample_list),
            )
            return base
        record_metric_progress(
            cycle=cycle,
            cycle_started=cycle_started,
            phase=phase,
            stage="bridge_metric_start",
            sample_count=len(sample_list),
            bridge_sample_count=len(bridge_samples),
            bridge_sample_ids=bridge_sample_ids,
        )
        try:
            bridge_evaluation = autoencoder.evaluate(
                bridge_samples,
                legal_ir_bridge_names=metric_bridge_adapters,
                legal_ir_evaluate_provers=bridge_evaluate_provers,
                legal_ir_parallel_workers=metric_bridge_parallel_workers,
                use_sample_memory=use_sample_memory,
            )
        except Exception as exc:
            if cuda_oom_error(exc):
                fallback_autoencoder_compute_to_python(
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase=phase,
                    stage="bridge_metric",
                    error=exc,
                )
                try:
                    bridge_evaluation = autoencoder.evaluate(
                        bridge_samples,
                        legal_ir_bridge_names=metric_bridge_adapters,
                        legal_ir_evaluate_provers=bridge_evaluate_provers,
                        legal_ir_parallel_workers=metric_bridge_parallel_workers,
                        use_sample_memory=use_sample_memory,
                    )
                except Exception as retry_exc:
                    exc = retry_exc
                else:
                    record_metric_progress(
                        cycle=cycle,
                        cycle_started=cycle_started,
                        phase=phase,
                        stage="bridge_metric_done",
                        sample_count=len(sample_list),
                        bridge_sample_count=len(bridge_samples),
                        bridge_sample_ids=bridge_sample_ids,
                    )
                    return replace(
                        base,
                        legal_ir_target_count=bridge_evaluation.legal_ir_target_count,
                        legal_ir_losses=dict(bridge_evaluation.legal_ir_losses),
                        legal_ir_predicted_view_distribution=dict(
                            bridge_evaluation.legal_ir_predicted_view_distribution
                        ),
                        legal_ir_target_hashes=dict(bridge_evaluation.legal_ir_target_hashes),
                        legal_ir_view_distribution=dict(
                            bridge_evaluation.legal_ir_view_distribution
                        ),
                    )
            summary["bridge_metric_failures"] = int(
                summary.get("bridge_metric_failures", 0) or 0
            ) + 1
            record_metric_progress(
                cycle=cycle,
                cycle_started=cycle_started,
                phase=phase,
                stage="bridge_metric_failed",
                sample_count=len(sample_list),
                bridge_sample_count=len(bridge_samples),
                bridge_sample_ids=bridge_sample_ids,
                error=exc,
            )
            return base
        record_metric_progress(
            cycle=cycle,
            cycle_started=cycle_started,
            phase=phase,
            stage="bridge_metric_done",
            sample_count=len(sample_list),
            bridge_sample_count=len(bridge_samples),
            bridge_sample_ids=bridge_sample_ids,
        )
        return replace(
            base,
            legal_ir_target_count=bridge_evaluation.legal_ir_target_count,
            legal_ir_losses=dict(bridge_evaluation.legal_ir_losses),
            legal_ir_predicted_view_distribution=dict(
                bridge_evaluation.legal_ir_predicted_view_distribution
            ),
            legal_ir_target_hashes=dict(bridge_evaluation.legal_ir_target_hashes),
            legal_ir_view_distribution=dict(bridge_evaluation.legal_ir_view_distribution),
        )

    def evaluate_autoencoder_base_probe(
        samples: Sequence[Any],
        *,
        cycle: int,
        cycle_started: float,
        phase: str,
        dataset: str,
        use_sample_memory: bool,
    ):
        sample_list = list(samples)
        record_metric_progress(
            cycle=cycle,
            cycle_started=cycle_started,
            phase=phase,
            stage=f"{dataset}_base_probe_start",
            sample_count=len(sample_list),
        )
        try:
            evaluation = autoencoder.evaluate(
                sample_list,
                legal_ir_bridge_names=(),
                legal_ir_evaluate_provers=False,
                legal_ir_parallel_workers=1,
                use_sample_memory=use_sample_memory,
            )
        except Exception as exc:
            if not cuda_oom_error(exc):
                raise
            fallback_autoencoder_compute_to_python(
                cycle=cycle,
                cycle_started=cycle_started,
                phase=phase,
                stage=f"{dataset}_base_probe",
                error=exc,
            )
            evaluation = autoencoder.evaluate(
                sample_list,
                legal_ir_bridge_names=(),
                legal_ir_evaluate_provers=False,
                legal_ir_parallel_workers=1,
                use_sample_memory=use_sample_memory,
            )
        record_metric_progress(
            cycle=cycle,
            cycle_started=cycle_started,
            phase=phase,
            stage=f"{dataset}_base_probe_done",
            sample_count=len(sample_list),
        )
        return evaluation

    def bootstrap_program_synthesis_todos(
        *,
        cycle: int,
        cycle_started: float,
        cycle_started_at: str,
        train_samples: Sequence[Any],
        train_indices: Sequence[int],
        validation_indices: Sequence[int],
    ) -> Dict[str, Any]:
        """Seed Codex work before bridge-heavy training can delay cycle 1."""
        nonlocal queue
        enabled = bool(
            getattr(args, "autoencoder_bootstrap_program_synthesis_todos", True)
        )
        min_pending = max(
            0,
            int(getattr(args, "autoencoder_bootstrap_min_pending", 1) or 0),
        )
        bootstrap_mode = str(getattr(args, "autoencoder_bootstrap_mode", "fast"))
        status = supervisor.program_synthesis_status(
            execution_mode="queued_for_external_codex_worker"
        )
        open_count = int(status.get("pending", 0) or 0) + int(
            status.get("claimed", 0) or 0
        )
        if not enabled or not train_samples or open_count >= min_pending:
            return {
                "attempted": False,
                "deduped_count": 0,
                "mode": bootstrap_mode,
                "open_count_before": open_count,
                "reason": (
                    "disabled"
                    if not enabled
                    else "no_train_samples"
                    if not train_samples
                    else "open_program_synthesis_queue_already_available"
                ),
                "seeded_count": 0,
                "semantic_deduped_count": 0,
                "todo_ids": [],
            }

        mark_active_autoencoder_cycle(
            cycle=cycle,
            cycle_started=cycle_started,
            cycle_started_at=cycle_started_at,
            phase=(
                "program_synthesis_bootstrap_fast_seed"
                if bootstrap_mode == "fast"
                else "program_synthesis_bootstrap"
            ),
            train_count=len(train_samples),
            validation_count=summary.get("active_cycle_validation_count", 0),
            train_indices=train_indices,
            validation_indices=validation_indices,
        )
        with queue_file_lock(queue_path):
            latest_queue = ModalTodoQueue.load_jsonl(queue_path)
            latest_queue.merge_from(
                supervisor.queue,
                preserve_claimed_role=supervisor.policy.program_synthesis_role,
            )
            supervisor.queue = latest_queue
            before_ids = {todo.todo_id for todo in supervisor.queue.all()}
            if bootstrap_mode == "fast":
                seeded = fast_program_synthesis_bootstrap_todos(
                    train_samples,
                    policy=supervisor.policy,
                    cycle=cycle,
                )
                supervisor.queue.add_many(seeded)
                deduped_count = 0
            else:
                seeded = supervisor.seed_program_synthesis_from_introspection(
                    train_samples,
                    autoencoder=autoencoder,
                    residual_stage="cycle_bootstrap_pre_projection",
                    require_residual_survival=False,
                )
                deduped_count = int(supervisor.last_program_synthesis_deduped_count)
            semantic_deduped_count = supervisor.queue.deduplicate_semantic(
                optimizer_role=supervisor.policy.program_synthesis_role,
                near_duplicate_jaccard=(
                    supervisor.policy.program_synthesis_near_duplicate_jaccard
                ),
            )
            todo_ids = [
                todo.todo_id
                for todo in seeded
                if todo.todo_id not in before_ids
                and supervisor.queue.get(todo.todo_id) is not None
            ]
            if seeded or deduped_count or semantic_deduped_count:
                supervisor.queue.save_jsonl(queue_path)
            queue = supervisor.queue

        update_program_synthesis_summary(
            summary,
            supervisor.queue,
            supervisor.policy,
            execution_mode="queued_for_external_codex_worker",
        )
        summary["program_synthesis_bootstrap_attempts"] = int(
            summary.get("program_synthesis_bootstrap_attempts", 0) or 0
        ) + 1
        summary["program_synthesis_bootstrap_deduped_total"] = int(
            summary.get("program_synthesis_bootstrap_deduped_total", 0) or 0
        ) + deduped_count
        summary["program_synthesis_bootstrap_seeded_total"] = int(
            summary.get("program_synthesis_bootstrap_seeded_total", 0) or 0
        ) + len(todo_ids)
        summary["program_synthesis_bootstrap_semantic_deduped_total"] = int(
            summary.get(
                "program_synthesis_bootstrap_semantic_deduped_total",
                0,
            )
            or 0
        ) + semantic_deduped_count
        summary["latest_program_synthesis_bootstrap"] = {
            "cycle": int(cycle),
            "deduped_count": deduped_count,
            "mode": bootstrap_mode,
            "open_count_before": open_count,
            "seeded_count": len(todo_ids),
            "semantic_deduped_count": int(semantic_deduped_count),
            "todo_ids": list(todo_ids),
        }
        summary["latest_queue_counts"] = supervisor.queue.status_counts()
        summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
        save_summary(summary_path, summary)
        append_event(
            log_path,
            args.run_id,
            {
                "cycle": cycle,
                "deduped_count": deduped_count,
                "event": "program_synthesis_bootstrap_seeded",
                "mode": bootstrap_mode,
                "open_count_before": open_count,
                "seeded_count": len(todo_ids),
                "semantic_deduped_count": int(semantic_deduped_count),
                "todo_ids": list(todo_ids),
            },
        )
        return {
            "attempted": True,
            "deduped_count": deduped_count,
            "mode": bootstrap_mode,
            "open_count_before": open_count,
            "seeded_count": len(todo_ids),
            "semantic_deduped_count": int(semantic_deduped_count),
            "todo_ids": list(todo_ids),
        }

    try:
        while (
            not stop_state.stop_requested
            and time.time() + cycle_start_margin_seconds < end_at
        ):
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            cycle_started_at = utc_now()
            cycle_learning_rate, cycle_lr_policy = _cycle_learning_rate(args, summary)
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="sampling",
            )
            append_event(
                log_path,
                args.run_id,
                {
                    "bridge_loss_adapters": bridge_adapters,
                    "bridge_evaluate_provers": bridge_evaluate_provers,
                    "cycle": cycle,
                    "cycle_started_at": cycle_started_at,
                    "event": "autoencoder_cycle_started",
                    "learning_rate_applied": float(cycle_learning_rate),
                    "learning_rate_policy": cycle_lr_policy,
                    "train_count": int(args.train_count),
                    "validation_count": int(args.validation_count),
                },
            )
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
                embedding_lookup=embedding_lookup,
                max_sample_text_chars=int(getattr(args, "max_sample_text_chars", 0) or 0),
            )
            acceptance_validation_samples = validation_canary_samples or validation_samples
            acceptance_validation_indices = validation_canary_indices or validation_indices
            validation_mode = (
                "fixed_canary"
                if validation_canary_samples
                else "rotating_holdout"
            )
            bootstrap_report = bootstrap_program_synthesis_todos(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                train_samples=train_samples,
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="before_train_evaluation",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            run_before_train_eval = _should_run_cycle_cadence(
                cycle=cycle,
                mode=autoencoder_before_train_eval_mode,
                every_n_cycles=autoencoder_before_train_eval_every_n_cycles,
            )
            before_train = None
            if run_before_train_eval:
                with active_cycle_heartbeat(
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="before_train_evaluation",
                ):
                    before_train = evaluate_autoencoder_cycle_metrics(
                        train_samples,
                        cycle=cycle,
                        cycle_started=cycle_started,
                        phase="before_train_evaluation",
                    )
            else:
                record_metric_progress(
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="before_train_evaluation",
                    stage="before_train_evaluation_skipped",
                    sample_count=len(train_samples),
                    extra={
                        "cadence_every_n_cycles": (
                            autoencoder_before_train_eval_every_n_cycles
                        ),
                        "cadence_mode": autoencoder_before_train_eval_mode,
                        "skip_reason": "before_train_eval_disabled",
                        "skipped": True,
                    },
                )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="before_validation_evaluation",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            with active_cycle_heartbeat(
                cycle=cycle,
                cycle_started=cycle_started,
                phase="before_validation_evaluation",
            ):
                before_validation = evaluate_autoencoder_cycle_metrics(
                    acceptance_validation_samples,
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="before_validation_evaluation",
                    use_sample_memory=False,
                )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="compiler_ir_metrics",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            with active_cycle_heartbeat(
                cycle=cycle,
                cycle_started=cycle_started,
                phase="compiler_ir_metrics",
            ):
                run_compiler_ir_train_metrics = bool(
                    compiler_ir_train_mode == "every_cycle"
                    or (
                        compiler_ir_train_mode == "periodic"
                        and int(cycle)
                        % max(1, int(compiler_ir_train_every_n_cycles))
                        == 0
                    )
                )
                compiler_ir_train_samples = (
                    (
                        sampled_bridge_metric_samples(train_samples, cycle=cycle)
                        or list(train_samples)
                    )
                    if run_compiler_ir_train_metrics
                    else []
                )
                compiler_ir_validation_samples = (
                    sampled_bridge_metric_samples(
                        acceptance_validation_samples,
                        cycle=cycle,
                    )
                    or list(acceptance_validation_samples)
                )
                if run_compiler_ir_train_metrics:
                    compiler_ir_train = compiler_ir_metric_block(
                        compiler_ir_train_samples,
                        feature_codec,
                        max_sample_text_chars=compiler_ir_metric_max_sample_text_chars,
                        metric_text_policy=compiler_ir_metric_text_policy,
                        progress_callback=metric_progress_callback(
                            cycle=cycle,
                            cycle_started=cycle_started,
                            phase="compiler_ir_metrics",
                            dataset="train",
                            sample_count=len(compiler_ir_train_samples),
                            bridge_sample_count=len(compiler_ir_train_samples),
                            bridge_sample_ids=[
                                str(getattr(sample, "sample_id", "") or "")
                                for sample in compiler_ir_train_samples
                            ],
                        ),
                        sample_timeout_seconds=(
                            compiler_ir_metric_sample_timeout_seconds
                        ),
                    )
                else:
                    compiler_ir_train = {
                        "autoencoder_guidance_enabled": False,
                        "compiler_ir_train_every_n_cycles": (
                            compiler_ir_train_every_n_cycles
                        ),
                        "compiler_ir_train_mode": compiler_ir_train_mode,
                        "evaluated_count": 0,
                        "metric_failures": 0,
                        "sample_count": len(train_samples),
                        "skip_reason": "train_metrics_disabled",
                        "skipped": True,
                    }
                compiler_ir_validation = compiler_ir_metric_block(
                    compiler_ir_validation_samples,
                    feature_codec,
                    max_sample_text_chars=compiler_ir_metric_max_sample_text_chars,
                    metric_text_policy=compiler_ir_metric_text_policy,
                    progress_callback=metric_progress_callback(
                        cycle=cycle,
                        cycle_started=cycle_started,
                        phase="compiler_ir_metrics",
                        dataset="validation",
                        sample_count=len(compiler_ir_validation_samples),
                        bridge_sample_count=len(compiler_ir_validation_samples),
                        bridge_sample_ids=[
                            str(getattr(sample, "sample_id", "") or "")
                            for sample in compiler_ir_validation_samples
                        ],
                    ),
                    sample_timeout_seconds=(
                        compiler_ir_metric_sample_timeout_seconds
                    ),
                )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="logic_bridge_metrics",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            with active_cycle_heartbeat(
                cycle=cycle,
                cycle_started=cycle_started,
                phase="logic_bridge_metrics",
            ):
                bridge_metric_train_samples = sampled_bridge_metric_samples(
                    train_samples,
                    cycle=cycle,
                )
                bridge_metric_validation_samples = sampled_bridge_metric_samples(
                    acceptance_validation_samples,
                    cycle=cycle,
                )
                bridge_ir_train = bridge_ir_metric_block(
                    bridge_metric_train_samples,
                    diagnostic_bridge_adapters,
                    evaluate_provers=bridge_evaluate_provers,
                    parallel_workers=metric_bridge_parallel_workers,
                    progress_callback=metric_progress_callback(
                        cycle=cycle,
                        cycle_started=cycle_started,
                        phase="logic_bridge_metrics",
                        dataset="bridge_train",
                        sample_count=len(bridge_metric_train_samples),
                        bridge_sample_count=len(bridge_metric_train_samples),
                        bridge_sample_ids=[
                            str(getattr(sample, "sample_id", "") or "")
                            for sample in bridge_metric_train_samples
                        ],
                    ),
                )
                bridge_ir_train["full_sample_count"] = len(train_samples)
                bridge_ir_train["sampled"] = (
                    len(bridge_metric_train_samples) < len(train_samples)
                )
                bridge_ir_train["bridge_loss_adapters"] = list(bridge_adapters)
                bridge_ir_train["diagnostic_bridge_adapters"] = list(
                    diagnostic_bridge_adapters
                )
                bridge_ir_train["skipped_bridge_loss_adapters"] = [
                    name
                    for name in bridge_adapters
                    if name not in set(diagnostic_bridge_adapters)
                ]
                bridge_ir_validation = bridge_ir_metric_block(
                    bridge_metric_validation_samples,
                    diagnostic_bridge_adapters,
                    evaluate_provers=bridge_evaluate_provers,
                    parallel_workers=metric_bridge_parallel_workers,
                    progress_callback=metric_progress_callback(
                        cycle=cycle,
                        cycle_started=cycle_started,
                        phase="logic_bridge_metrics",
                        dataset="bridge_validation",
                        sample_count=len(bridge_metric_validation_samples),
                        bridge_sample_count=len(bridge_metric_validation_samples),
                        bridge_sample_ids=[
                            str(getattr(sample, "sample_id", "") or "")
                            for sample in bridge_metric_validation_samples
                        ],
                    ),
                )
                bridge_ir_validation["full_sample_count"] = len(
                    acceptance_validation_samples
                )
                bridge_ir_validation["sampled"] = (
                    len(bridge_metric_validation_samples)
                    < len(acceptance_validation_samples)
                )
                bridge_ir_validation["bridge_loss_adapters"] = list(bridge_adapters)
                bridge_ir_validation["diagnostic_bridge_adapters"] = list(
                    diagnostic_bridge_adapters
                )
                bridge_ir_validation["skipped_bridge_loss_adapters"] = [
                    name
                    for name in bridge_adapters
                    if name not in set(diagnostic_bridge_adapters)
                ]
            feature_projection_report: Dict[str, Any] = {}
            generalizable_projection_epochs = max(
                0,
                int(getattr(args, "generalizable_projection_epochs", 0) or 0),
            )
            if generalizable_projection_epochs > 0 and train_samples:
                mark_active_autoencoder_cycle(
                    cycle=cycle,
                    cycle_started=cycle_started,
                    cycle_started_at=cycle_started_at,
                    phase="generalizable_projection",
                    train_count=len(train_samples),
                    validation_count=len(acceptance_validation_samples),
                    train_indices=train_indices,
                    validation_indices=acceptance_validation_indices,
                )
                with metric_progress_lock:
                    summary["active_cycle_projection_progress"] = {
                        "elapsed_seconds": 0.0,
                        "stage": "starting",
                    }
                    summary["active_cycle_projection_stage"] = "starting"
                    save_summary(summary_path, summary)
                projection_progress_last_saved_at = [0.0]

                def record_projection_progress(progress: Mapping[str, Any]) -> None:
                    now = time.time()
                    with metric_progress_lock:
                        projection_progress = dict(progress)
                        projection_progress["cycle"] = int(cycle)
                        summary["active_cycle_elapsed_seconds"] = round(
                            now - cycle_started,
                            3,
                        )
                        summary["active_cycle_last_heartbeat_at"] = utc_now()
                        summary["active_cycle_phase"] = "generalizable_projection"
                        summary["active_cycle_projection_progress"] = projection_progress
                        summary["active_cycle_projection_stage"] = str(
                            projection_progress.get("stage") or ""
                        )
                        force_save = (
                            str(projection_progress.get("stage") or "") == "finished"
                        )
                        if (
                            force_save
                            or now - projection_progress_last_saved_at[0] >= 5.0
                        ):
                            projection_progress_last_saved_at[0] = now
                            save_summary(summary_path, summary)

                with active_cycle_heartbeat(
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="generalizable_projection",
                ):
                    feature_projection_report = autoencoder.train_generalizable_projection(
                        train_samples,
                        validation_samples=acceptance_validation_samples,
                        epochs=generalizable_projection_epochs,
                        learning_rate=cycle_learning_rate,
                        legal_ir_bridge_names=metric_bridge_adapters,
                        legal_ir_bridge_max_samples=metric_bridge_max_samples,
                        legal_ir_bridge_max_sample_text_chars=(
                            metric_bridge_max_sample_text_chars
                        ),
                        legal_ir_evaluate_provers=bridge_evaluate_provers,
                        legal_ir_parallel_workers=metric_bridge_parallel_workers,
                        max_cosine_regression=float(
                            projection_max_cosine_regression
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
                                1.5,
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
                        max_seconds=generalizable_projection_timeout_seconds,
                        max_line_search_attempts=(
                            generalizable_projection_max_line_search_attempts
                        ),
                        projection_deadband_mode=projection_deadband_mode,
                        projection_max_ce_deadband=projection_max_ce_deadband,
                        projection_hard_guardrail_metrics=(
                            projection_hard_guardrail_metrics
                        ),
                        projection_prescreen_mode=projection_prescreen_mode,
                        projection_prescreen_top_k=projection_prescreen_top_k,
                        projection_periodic_full_search_every_n_cycles=(
                            projection_periodic_full_search_every_n_cycles
                        ),
                        projection_cycle=cycle,
                        progress_callback=record_projection_progress,
                    )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="todo_supervisor_optimization",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            run: Optional[ModalOptimizationRun] = None
            todo_supervisor_optimization: Dict[str, Any] = {}
            with active_cycle_heartbeat(
                cycle=cycle,
                cycle_started=cycle_started,
                phase="todo_supervisor_optimization",
            ):
                refresh_supervisor_queue_from_disk(supervisor)
                todo_supervisor_optimization = _todo_supervisor_skip_decision(
                    mode=autoencoder_todo_supervisor_mode,
                    program_synthesis_status=supervisor.program_synthesis_status(),
                    min_open=autoencoder_todo_supervisor_min_open,
                )
                with metric_progress_lock:
                    summary["active_cycle_todo_supervisor_optimization"] = {
                        "at": utc_now(),
                        **todo_supervisor_optimization,
                    }
                if bool(todo_supervisor_optimization.get("skipped")):
                    record_todo_optimizer_progress(
                        {
                            "iteration": 0,
                            "queue_counts": supervisor.queue.status_counts(),
                            "role_queue_counts": supervisor.queue.role_status_counts(),
                            "stage": "todo_supervisor_optimization_skipped",
                            **todo_supervisor_optimization,
                        }
                    )
                else:
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
                        queue_refresh_callback=refresh_supervisor_queue_from_disk,
                        progress_callback=record_todo_optimizer_progress,
                    )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="after_train_evaluation",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            with active_cycle_heartbeat(
                cycle=cycle,
                cycle_started=cycle_started,
                phase="after_train_evaluation",
            ):
                after_train = evaluate_autoencoder_cycle_metrics(
                    train_samples,
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="after_train_evaluation",
                )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="after_validation_evaluation",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            with active_cycle_heartbeat(
                cycle=cycle,
                cycle_started=cycle_started,
                phase="after_validation_evaluation",
            ):
                after_validation = evaluate_autoencoder_cycle_metrics(
                    acceptance_validation_samples,
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="after_validation_evaluation",
                    use_sample_memory=False,
                )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="sample_memory_probe",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            run_sample_memory_probe = _should_run_cycle_cadence(
                cycle=cycle,
                mode=autoencoder_sample_memory_probe_mode,
                every_n_cycles=autoencoder_sample_memory_probe_every_n_cycles,
            )
            after_train_generalized_probe = None
            after_validation_sample_memory_probe = None
            if run_sample_memory_probe:
                with active_cycle_heartbeat(
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="sample_memory_probe",
                ):
                    after_train_generalized_probe = evaluate_autoencoder_base_probe(
                        train_samples,
                        cycle=cycle,
                        cycle_started=cycle_started,
                        phase="sample_memory_probe",
                        dataset="train_generalized",
                        use_sample_memory=False,
                    )
                    after_validation_sample_memory_probe = (
                        evaluate_autoencoder_base_probe(
                            acceptance_validation_samples,
                            cycle=cycle,
                            cycle_started=cycle_started,
                            phase="sample_memory_probe",
                            dataset="validation_sample_memory",
                            use_sample_memory=True,
                        )
                    )
            else:
                record_metric_progress(
                    cycle=cycle,
                    cycle_started=cycle_started,
                    phase="sample_memory_probe",
                    stage="sample_memory_probe_skipped",
                    sample_count=(
                        len(train_samples) + len(acceptance_validation_samples)
                    ),
                    extra={
                        "cadence_every_n_cycles": (
                            autoencoder_sample_memory_probe_every_n_cycles
                        ),
                        "cadence_mode": autoencoder_sample_memory_probe_mode,
                        "skip_reason": "sample_memory_probe_disabled",
                        "skipped": True,
                    },
                )
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="guided_compiler_ir_metrics",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
            )
            with active_cycle_heartbeat(
                cycle=cycle,
                cycle_started=cycle_started,
                phase="guided_compiler_ir_metrics",
            ):
                run_guided_train_metrics = bool(
                    compiler_ir_guided_train_mode == "every_cycle"
                    or (
                        compiler_ir_guided_train_mode == "periodic"
                        and int(cycle)
                        % max(1, int(compiler_ir_guided_train_every_n_cycles))
                        == 0
                    )
                )
                guided_compiler_ir_train_samples = (
                    (
                        sampled_bridge_metric_samples(train_samples, cycle=cycle)
                        or list(train_samples)
                    )
                    if run_guided_train_metrics
                    else []
                )
                guided_compiler_ir_validation_samples = (
                    sampled_bridge_metric_samples(
                        acceptance_validation_samples,
                        cycle=cycle,
                    )
                    or list(acceptance_validation_samples)
                )
                if run_guided_train_metrics:
                    compiler_ir_guided_train = compiler_ir_metric_block(
                        guided_compiler_ir_train_samples,
                        feature_codec,
                        autoencoder=autoencoder,
                        max_sample_text_chars=compiler_ir_metric_max_sample_text_chars,
                        metric_text_policy=compiler_ir_metric_text_policy,
                        use_autoencoder_guidance=True,
                        progress_callback=metric_progress_callback(
                            cycle=cycle,
                            cycle_started=cycle_started,
                            phase="guided_compiler_ir_metrics",
                            dataset="guided_train",
                            sample_count=len(guided_compiler_ir_train_samples),
                            bridge_sample_count=len(guided_compiler_ir_train_samples),
                            bridge_sample_ids=[
                                str(getattr(sample, "sample_id", "") or "")
                                for sample in guided_compiler_ir_train_samples
                            ],
                        ),
                        sample_timeout_seconds=(
                            compiler_ir_metric_sample_timeout_seconds
                        ),
                    )
                else:
                    compiler_ir_guided_train = {
                        "autoencoder_guidance_enabled": True,
                        "compiler_ir_guided_train_every_n_cycles": (
                            compiler_ir_guided_train_every_n_cycles
                        ),
                        "compiler_ir_guided_train_mode": (
                            compiler_ir_guided_train_mode
                        ),
                        "evaluated_count": 0,
                        "metric_failures": 0,
                        "sample_count": len(train_samples),
                        "skip_reason": "guided_train_metrics_disabled",
                        "skipped": True,
                    }
                compiler_ir_guided_validation = compiler_ir_metric_block(
                    guided_compiler_ir_validation_samples,
                    feature_codec,
                    autoencoder=autoencoder,
                    max_sample_text_chars=compiler_ir_metric_max_sample_text_chars,
                    metric_text_policy=compiler_ir_metric_text_policy,
                    use_autoencoder_guidance=True,
                    progress_callback=metric_progress_callback(
                        cycle=cycle,
                        cycle_started=cycle_started,
                        phase="guided_compiler_ir_metrics",
                        dataset="guided_validation",
                        sample_count=len(guided_compiler_ir_validation_samples),
                        bridge_sample_count=len(guided_compiler_ir_validation_samples),
                        bridge_sample_ids=[
                            str(getattr(sample, "sample_id", "") or "")
                            for sample in guided_compiler_ir_validation_samples
                        ],
                    ),
                    sample_timeout_seconds=(
                        compiler_ir_metric_sample_timeout_seconds
                    ),
                )
            if run is None:
                stopped_reason = str(
                    todo_supervisor_optimization.get("skip_reason")
                    or "todo_supervisor_optimization_skipped"
                )
                run = ModalOptimizationRun(
                    steps=[],
                    final_evaluation=after_train,
                    stopped_reason=stopped_reason,
                    validation_final_evaluation=after_validation,
                )
            summary["latest_todo_supervisor_optimization"] = {
                "stopped_reason": run.stopped_reason,
                **todo_supervisor_optimization,
            }
            mark_active_autoencoder_cycle(
                cycle=cycle,
                cycle_started=cycle_started,
                cycle_started_at=cycle_started_at,
                phase="queue_merge_and_state_save",
                train_count=len(train_samples),
                validation_count=len(acceptance_validation_samples),
                train_indices=train_indices,
                validation_indices=acceptance_validation_indices,
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
            latest_state_telemetry = autoencoder_state_telemetry(
                autoencoder.state,
                state_path=state_path,
            )

            before_train_eval_skipped = before_train is None
            if before_train_eval_skipped:
                before_train = after_train
            train_ce_delta = before_train.cross_entropy_loss - after_train.cross_entropy_loss
            validation_ce_delta = before_validation.cross_entropy_loss - after_validation.cross_entropy_loss
            train_cos_delta = after_train.embedding_cosine_similarity - before_train.embedding_cosine_similarity
            validation_cos_delta = (
                after_validation.embedding_cosine_similarity
                - before_validation.embedding_cosine_similarity
            )
            if before_train_eval_skipped:
                before_train_metrics = skipped_autoencoder_metric_block(
                    after_train,
                    cycle=cycle,
                    dataset="train",
                    every_n_cycles=autoencoder_before_train_eval_every_n_cycles,
                    mode=autoencoder_before_train_eval_mode,
                    skip_reason="before_train_eval_disabled",
                )
            else:
                before_train_metrics = metric_block(before_train)
            before_validation_metrics = metric_block(before_validation)
            after_train_metrics = metric_block(after_train)
            after_validation_metrics = metric_block(after_validation)
            sample_memory_probe_skipped = (
                after_train_generalized_probe is None
                or after_validation_sample_memory_probe is None
            )
            if sample_memory_probe_skipped:
                after_train_generalized_probe_metrics = skipped_autoencoder_metric_block(
                    after_train,
                    cycle=cycle,
                    dataset="train_generalized",
                    every_n_cycles=autoencoder_sample_memory_probe_every_n_cycles,
                    mode=autoencoder_sample_memory_probe_mode,
                    skip_reason="sample_memory_probe_disabled",
                )
                after_validation_sample_memory_probe_metrics = (
                    skipped_autoencoder_metric_block(
                        after_validation,
                        cycle=cycle,
                        dataset="validation_sample_memory",
                        every_n_cycles=autoencoder_sample_memory_probe_every_n_cycles,
                        mode=autoencoder_sample_memory_probe_mode,
                        skip_reason="sample_memory_probe_disabled",
                    )
                )
                train_sample_memory_gap = skipped_autoencoder_memory_gap_block(
                    after_train,
                    cycle=cycle,
                    dataset="train",
                    every_n_cycles=autoencoder_sample_memory_probe_every_n_cycles,
                    expected_holdout=False,
                    mode=autoencoder_sample_memory_probe_mode,
                    skip_reason="sample_memory_probe_disabled",
                )
                validation_sample_memory_gap = skipped_autoencoder_memory_gap_block(
                    after_validation,
                    cycle=cycle,
                    dataset="validation",
                    every_n_cycles=autoencoder_sample_memory_probe_every_n_cycles,
                    expected_holdout=True,
                    mode=autoencoder_sample_memory_probe_mode,
                    skip_reason="sample_memory_probe_disabled",
                )
            else:
                after_train_generalized_probe_metrics = metric_block(
                    after_train_generalized_probe
                )
                after_validation_sample_memory_probe_metrics = metric_block(
                    after_validation_sample_memory_probe
                )
                train_sample_memory_gap = autoencoder_memory_gap_block(
                    after_train_generalized_probe,
                    after_train,
                    dataset="train",
                    expected_holdout=False,
                )
                validation_sample_memory_gap = autoencoder_memory_gap_block(
                    after_validation,
                    after_validation_sample_memory_probe,
                    dataset="validation",
                    expected_holdout=True,
                )
            learned_ir_before_train = learned_ir_metric_block(before_train)
            if before_train_eval_skipped:
                learned_ir_before_train["skipped"] = True
                learned_ir_before_train["skip_reason"] = "before_train_eval_disabled"
            learned_ir_before_validation = learned_ir_metric_block(before_validation)
            learned_ir_train = learned_ir_metric_block(after_train)
            learned_ir_validation = learned_ir_metric_block(after_validation)
            latest_compiler_ir_ce = float(
                compiler_ir_validation.get("cross_entropy_loss", 1.0e12)
            )
            latest_compiler_ir_ce_excess = float(
                compiler_ir_validation.get("cross_entropy_excess_loss", 1.0e12)
            )
            latest_compiler_ir_cosine = float(
                compiler_ir_validation.get("cosine_similarity", -1.0)
            )
            latest_compiler_ir_source_copy_loss = float(
                compiler_ir_validation.get("source_copy_loss", 1.0e12)
            )
            latest_compiler_ir_raw_source_embedding_cosine = float(
                compiler_ir_validation.get("raw_source_embedding_cosine_similarity", -1.0)
            )
            latest_source_decompiled_text_embedding_cosine_loss = float(
                compiler_ir_validation.get(
                    "source_decompiled_text_embedding_cosine_loss",
                    max(
                        0.0,
                        1.0
                        - float(
                            compiler_ir_validation.get(
                                "source_decompiled_text_embedding_cosine_similarity",
                                latest_compiler_ir_cosine
                                if latest_compiler_ir_cosine > -1.0
                                else latest_compiler_ir_raw_source_embedding_cosine,
                            )
                        ),
                    ),
                )
            )
            latest_source_decompiled_text_token_loss = float(
                compiler_ir_validation.get(
                    "source_decompiled_text_token_loss",
                    compiler_ir_validation.get(
                        "structural_text_reconstruction_loss",
                        1.0e12,
                    ),
                )
            )
            latest_compiler_ir_source_copy_reward_hack_penalty = float(
                compiler_ir_validation.get("source_copy_reward_hack_penalty", 1.0e12)
            )
            latest_guided_compiler_ir_ce = float(
                compiler_ir_guided_validation.get("cross_entropy_loss", 1.0e12)
            )
            latest_guided_compiler_ir_ce_excess = float(
                compiler_ir_guided_validation.get("cross_entropy_excess_loss", 1.0e12)
            )
            latest_guided_compiler_ir_cosine = float(
                compiler_ir_guided_validation.get("cosine_similarity", -1.0)
            )
            latest_guided_compiler_ir_source_copy_reward_hack_penalty = float(
                compiler_ir_guided_validation.get(
                    "source_copy_reward_hack_penalty",
                    1.0e12,
                )
            )
            guidance_canary = compiler_guidance_canary_block(
                compiler_ir_validation,
                compiler_ir_guided_validation,
                plateau_threshold=float(
                    getattr(args, "learning_rate_plateau_delta", 1.0e-5)
                ),
            )
            guidance_promotion_gate = compiler_guidance_promotion_gate(guidance_canary)
            guidance_scope_hints = compiler_guidance_scope_hints(
                compiler_ir_guided_validation
            )
            guidance_distillation = compiler_guidance_distillation_candidates(
                compiler_ir_guided_validation,
                guidance_canary,
            )
            guidance_distillation_path = save_compiler_guidance_distillation(
                summary_path,
                guidance_distillation,
            )
            guidance_distillation_seeded_count = 0
            guidance_distillation_deduped_count = 0
            guidance_distillation_semantic_deduped_count = 0
            guidance_distillation_todo_ids: List[str] = []
            guidance_activation_seeded_count = 0
            guidance_activation_deduped_count = 0
            guidance_activation_semantic_deduped_count = 0
            guidance_activation_todo_ids: List[str] = []
            guidance_guardrail_seeded_count = 0
            guidance_guardrail_deduped_count = 0
            guidance_guardrail_todo_ids: List[str] = []
            guidance_distillation_todo_candidates = compiler_guidance_distillation_todos(
                guidance_distillation,
                policy=supervisor.policy,
            )
            if guidance_distillation_todo_candidates:
                with queue_file_lock(queue_path):
                    latest_queue = ModalTodoQueue.load_jsonl(queue_path)
                    latest_queue.merge_from(
                        supervisor.queue,
                        preserve_claimed_role=supervisor.policy.program_synthesis_role,
                    )
                    supervisor.queue = latest_queue
                    selected_guidance_todos = supervisor._bounded_new_todos(
                        guidance_distillation_todo_candidates,
                        track_program_deduped=True,
                    )
                    guidance_distillation_deduped_count = int(
                        supervisor.last_program_synthesis_deduped_count
                    )
                    before_guidance_todo_ids = {
                        todo.todo_id for todo in supervisor.queue.all()
                    }
                    guidance_distillation_seeded_count = supervisor.queue.add_many(
                        selected_guidance_todos
                    )
                    guidance_distillation_todo_ids = [
                        todo.todo_id
                        for todo in selected_guidance_todos
                        if todo.todo_id not in before_guidance_todo_ids
                        and supervisor.queue.get(todo.todo_id) is not None
                    ]
                    guidance_distillation_semantic_deduped_count = (
                        supervisor.queue.deduplicate_semantic(
                            optimizer_role=supervisor.policy.program_synthesis_role,
                            near_duplicate_jaccard=(
                                supervisor.policy.program_synthesis_near_duplicate_jaccard
                            ),
                        )
                    )
                    semantic_deduped_count += int(
                        guidance_distillation_semantic_deduped_count
                    )
                    supervisor.queue.save_jsonl(queue_path)
                    queue = supervisor.queue
            guidance_activation_candidates = compiler_guidance_activation_todos(
                guidance_distillation,
                guidance_canary,
                policy=supervisor.policy,
            )
            if guidance_activation_candidates:
                with queue_file_lock(queue_path):
                    latest_queue = ModalTodoQueue.load_jsonl(queue_path)
                    latest_queue.merge_from(
                        supervisor.queue,
                        preserve_claimed_role=supervisor.policy.program_synthesis_role,
                    )
                    supervisor.queue = latest_queue
                    selected_activation_todos = supervisor._bounded_new_todos(
                        guidance_activation_candidates,
                        track_program_deduped=True,
                    )
                    guidance_activation_deduped_count = int(
                        supervisor.last_program_synthesis_deduped_count
                    )
                    before_activation_todo_ids = {
                        todo.todo_id for todo in supervisor.queue.all()
                    }
                    guidance_activation_seeded_count = supervisor.queue.add_many(
                        selected_activation_todos
                    )
                    guidance_activation_todo_ids = [
                        todo.todo_id
                        for todo in selected_activation_todos
                        if todo.todo_id not in before_activation_todo_ids
                        and supervisor.queue.get(todo.todo_id) is not None
                    ]
                    guidance_activation_semantic_deduped_count = (
                        supervisor.queue.deduplicate_semantic(
                            optimizer_role=supervisor.policy.program_synthesis_role,
                            near_duplicate_jaccard=(
                                supervisor.policy.program_synthesis_near_duplicate_jaccard
                            ),
                        )
                    )
                    semantic_deduped_count += int(
                        guidance_activation_semantic_deduped_count
                    )
                    supervisor.queue.save_jsonl(queue_path)
                    queue = supervisor.queue
            guidance_guardrail_candidates = compiler_guidance_guardrail_todos(
                guidance_distillation,
                guidance_canary,
                policy=supervisor.policy,
            )
            if guidance_guardrail_candidates:
                with queue_file_lock(queue_path):
                    latest_queue = ModalTodoQueue.load_jsonl(queue_path)
                    latest_queue.merge_from(
                        supervisor.queue,
                        preserve_claimed_role=supervisor.policy.program_synthesis_role,
                    )
                    supervisor.queue = latest_queue
                    selected_guardrail_todos = supervisor._bounded_new_todos(
                        guidance_guardrail_candidates,
                        track_program_deduped=True,
                    )
                    guidance_guardrail_deduped_count = int(
                        supervisor.last_program_synthesis_deduped_count
                    )
                    before_guardrail_todo_ids = {
                        todo.todo_id for todo in supervisor.queue.all()
                    }
                    guidance_guardrail_seeded_count = supervisor.queue.add_many(
                        selected_guardrail_todos
                    )
                    guidance_guardrail_todo_ids = [
                        todo.todo_id
                        for todo in selected_guardrail_todos
                        if todo.todo_id not in before_guardrail_todo_ids
                        and supervisor.queue.get(todo.todo_id) is not None
                    ]
                    supervisor.queue.save_jsonl(queue_path)
                    queue = supervisor.queue
            failed_validation_rescue_seeded_count = 0
            failed_validation_rescue_deduped_count = 0
            failed_validation_rescue_todo_ids: List[str] = []
            if int(supervisor.queue.status_counts().get("failed_validation", 0)) > 0:
                with queue_file_lock(queue_path):
                    latest_queue = ModalTodoQueue.load_jsonl(queue_path)
                    latest_queue.merge_from(
                        supervisor.queue,
                        preserve_claimed_role=supervisor.policy.program_synthesis_role,
                    )
                    supervisor.queue = latest_queue
                    before_rescue_todo_ids = {
                        todo.todo_id for todo in supervisor.queue.all()
                    }
                    failed_validation_rescue_todos = (
                        supervisor.seed_failed_validation_rescue_todos(max_clusters=8)
                    )
                    failed_validation_rescue_deduped_count = int(
                        supervisor.last_program_synthesis_deduped_count
                    )
                    failed_validation_rescue_todo_ids = [
                        todo.todo_id
                        for todo in failed_validation_rescue_todos
                        if todo.todo_id not in before_rescue_todo_ids
                        and supervisor.queue.get(todo.todo_id) is not None
                    ]
                    failed_validation_rescue_seeded_count = len(
                        failed_validation_rescue_todo_ids
                    )
                    if (
                        failed_validation_rescue_seeded_count
                        or failed_validation_rescue_deduped_count
                    ):
                        supervisor.queue.save_jsonl(queue_path)
                        queue = supervisor.queue
            latest_compiler_ir_guidance_ce_delta = float(guidance_canary["ce_delta"])
            latest_compiler_ir_guidance_cosine_delta = float(
                guidance_canary["cosine_delta"]
            )
            latest_compiler_ir_guidance_copy_hack_delta = float(
                guidance_canary["copy_hack_delta"]
            )
            latest_learned_ir_view_ce = float(
                learned_ir_validation.get("view_cross_entropy_loss", 1.0e12)
            )
            latest_learned_ir_view_cosine = float(
                learned_ir_validation.get("view_cosine_similarity", -1.0)
            )
            latest_learned_ir_family_ce_excess = _metric_value(
                learned_ir_validation,
                "family_cross_entropy_excess_loss",
            )
            latest_learned_ir_worst_family_ce_excess = _metric_value(
                learned_ir_validation,
                "worst_family_cross_entropy_excess_loss",
            )
            latest_learned_ir_worst_family_cosine_gap = _metric_value(
                learned_ir_validation,
                "worst_family_cosine_gap_loss",
            )
            latest_cycle_seconds = round(time.time() - cycle_started, 3)
            latest_cycle_phase_timings = close_active_phase(cycle=cycle)
            clear_active_autoencoder_cycle()
            backend_metadata = autoencoder.compute_backend_metadata()
            host_resource_health = paired_resource_health()
            summary["last_completed_cycle"] = cycle
            summary["cycles"] = cycle
            summary["latest_stop_reason"] = run.stopped_reason
            summary.update(backend_metadata)
            summary["latest_autoencoder_backend"] = dict(backend_metadata)
            summary["latest_host_resource_health"] = dict(host_resource_health)
            summary["latest_queue_counts"] = supervisor.queue.status_counts()
            summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
            summary["latest_feature_projection_report"] = feature_projection_report
            summary["latest_program_synthesis_bootstrap"] = bootstrap_report
            summary["latest_cycle_seconds"] = latest_cycle_seconds
            summary["latest_cycle_phase_timings"] = latest_cycle_phase_timings
            summary["latest_autoencoder_state_telemetry"] = latest_state_telemetry
            summary["embedding_target_report"] = embedding_lookup.report()
            summary["latest_autoencoder_before_train"] = before_train_metrics
            summary["latest_autoencoder_before_validation"] = before_validation_metrics
            summary["latest_autoencoder_train"] = after_train_metrics
            summary["latest_autoencoder_train_generalized_probe"] = (
                after_train_generalized_probe_metrics
            )
            summary["latest_autoencoder_validation"] = after_validation_metrics
            summary["latest_autoencoder_validation_sample_memory_probe"] = (
                after_validation_sample_memory_probe_metrics
            )
            summary["latest_autoencoder_signal_health"] = (
                autoencoder_validation_signal_health(
                    compiler_ir_validation=compiler_ir_validation,
                    learned_ir_validation=learned_ir_validation,
                    logic_bridge_validation=bridge_ir_validation,
                    validation_metrics=after_validation_metrics,
                    metric_bridge_adapters=metric_bridge_adapters,
                    diagnostic_bridge_adapters=diagnostic_bridge_adapters,
                )
            )
            summary["latest_rollout_baseline_snapshot"] = rollout_baseline_snapshot(
                summary=summary,
                cycle=cycle,
                cycle_seconds=latest_cycle_seconds,
                cycle_phase_timings=latest_cycle_phase_timings,
                validation_metrics=after_validation_metrics,
                compiler_ir_validation=compiler_ir_validation,
                compiler_ir_guided_validation=compiler_ir_guided_validation,
                learned_ir_validation=learned_ir_validation,
                logic_bridge_validation=bridge_ir_validation,
                queue_counts=summary["latest_queue_counts"],
                role_queue_counts=summary["latest_role_queue_counts"],
                state_telemetry=latest_state_telemetry,
                embedding_report=embedding_lookup.report(),
                backend_metadata=backend_metadata,
                host_resource_health=host_resource_health,
                metric_bridge_adapters=metric_bridge_adapters,
                diagnostic_bridge_adapters=diagnostic_bridge_adapters,
            )
            summary["latest_train_sample_memory_gap"] = train_sample_memory_gap
            summary["latest_validation_sample_memory_gap"] = (
                validation_sample_memory_gap
            )
            summary["latest_train_ce"] = after_train.cross_entropy_loss
            summary["latest_train_cosine"] = after_train.embedding_cosine_similarity
            summary["latest_train_reconstruction"] = after_train.reconstruction_loss
            summary["latest_validation_ce"] = after_validation.cross_entropy_loss
            summary["latest_validation_cosine"] = after_validation.embedding_cosine_similarity
            summary["latest_validation_reconstruction"] = after_validation.reconstruction_loss
            summary["latest_train_ce_delta"] = train_ce_delta
            summary["latest_train_cosine_delta"] = train_cos_delta
            summary["latest_validation_ce_delta"] = validation_ce_delta
            summary["latest_validation_cosine_delta"] = validation_cos_delta
            summary["latest_compiler_ir_train"] = compiler_ir_train
            summary["latest_compiler_ir_validation"] = compiler_ir_validation
            summary["latest_compiler_ir_guided_train"] = compiler_ir_guided_train
            summary["latest_compiler_ir_guided_validation"] = compiler_ir_guided_validation
            summary["latest_compiler_ir_ce"] = latest_compiler_ir_ce
            summary["latest_compiler_ir_ce_excess"] = latest_compiler_ir_ce_excess
            summary["latest_compiler_ir_cosine"] = latest_compiler_ir_cosine
            summary["latest_compiler_ir_raw_source_embedding_cosine"] = (
                latest_compiler_ir_raw_source_embedding_cosine
            )
            summary["latest_cosine_metric_disagreement"] = {
                "compiler_ir_minus_autoencoder_embedding_cosine": round(
                    latest_compiler_ir_cosine
                    - after_validation.embedding_cosine_similarity,
                    9,
                ),
                "compiler_raw_source_embedding_minus_autoencoder_embedding_cosine": round(
                    latest_compiler_ir_raw_source_embedding_cosine
                    - after_validation.embedding_cosine_similarity,
                    9,
                ),
                "compiler_ir_cosine_metric": (
                    "deterministic compiler/decompiler structural IR round-trip"
                ),
                "compiler_raw_source_embedding_cosine_metric": (
                    "deterministic compiler decoded text embedding vs source embedding"
                ),
                "validation_cosine_metric": (
                    "autoencoder decoded embedding vs source embedding"
                ),
            }
            summary["latest_validation_cosine_bottleneck"] = {
                "autoencoder_embedding_cosine": round(
                    after_validation.embedding_cosine_similarity,
                    9,
                ),
                "autoencoder_embedding_cosine_gap": round(
                    max(0.0, 1.0 - after_validation.embedding_cosine_similarity),
                    9,
                ),
                "autoencoder_reconstruction_loss": round(
                    after_validation.reconstruction_loss,
                    9,
                ),
                "compiler_raw_source_embedding_cosine": round(
                    latest_compiler_ir_raw_source_embedding_cosine,
                    9,
                ),
                "compiler_structural_ir_cosine": round(
                    latest_compiler_ir_cosine,
                    9,
                ),
                "is_embedding_head_bottleneck": bool(
                    after_validation.embedding_cosine_similarity < 0.25
                ),
                "worst_samples": list(
                    after_validation_metrics.get("worst_sample_embedding_metrics", [])
                ),
            }
            summary["latest_compiler_ir_source_copy_loss"] = latest_compiler_ir_source_copy_loss
            summary["latest_compiler_ir_source_copy_reward_hack_penalty"] = (
                latest_compiler_ir_source_copy_reward_hack_penalty
            )
            summary["latest_source_decompiled_text_embedding_cosine_loss"] = (
                latest_source_decompiled_text_embedding_cosine_loss
            )
            summary["latest_source_decompiled_text_token_loss"] = (
                latest_source_decompiled_text_token_loss
            )
            summary["latest_source_decompiled_text_roundtrip_bottleneck"] = {
                "copy_hack_penalty": round(
                    latest_compiler_ir_source_copy_reward_hack_penalty,
                    9,
                ),
                "embedding_cosine_loss": round(
                    latest_source_decompiled_text_embedding_cosine_loss,
                    9,
                ),
                "embedding_cosine_similarity": round(
                    1.0 - latest_source_decompiled_text_embedding_cosine_loss,
                    9,
                ),
                "source_copy_loss": round(latest_compiler_ir_source_copy_loss, 9),
                "token_loss": round(latest_source_decompiled_text_token_loss, 9),
                "token_similarity": round(
                    1.0 - latest_source_decompiled_text_token_loss,
                    9,
                ),
                "worst_samples": list(
                    compiler_ir_validation.get(
                        "worst_source_decompiled_text_records",
                        [],
                    )
                    or []
                )[:8],
            }
            summary["latest_compiler_ir_guided_ce"] = latest_guided_compiler_ir_ce
            summary["latest_compiler_ir_guided_ce_excess"] = (
                latest_guided_compiler_ir_ce_excess
            )
            summary["latest_compiler_ir_guided_cosine"] = latest_guided_compiler_ir_cosine
            summary["latest_compiler_ir_guided_source_copy_reward_hack_penalty"] = (
                latest_guided_compiler_ir_source_copy_reward_hack_penalty
            )
            summary["latest_compiler_ir_guidance_canary"] = guidance_canary
            summary["latest_compiler_ir_guidance_quality_gate"] = guidance_canary[
                "quality_gate"
            ]
            summary["latest_compiler_ir_guidance_promotion"] = (
                guidance_promotion_gate
            )
            summary["latest_compiler_ir_guidance_promotion_allowed"] = bool(
                guidance_promotion_gate["promotion_allowed"]
            )
            summary["latest_compiler_ir_guidance_promotion_block_reason"] = (
                guidance_promotion_gate["promotion_block_reason"]
            )
            summary["latest_compiler_ir_guidance_scope_hints"] = (
                guidance_scope_hints
            )
            summary["latest_compiler_ir_guidance_distillation"] = (
                guidance_distillation
            )
            summary["latest_compiler_ir_guidance_distillation_path"] = (
                str(guidance_distillation_path)
                if guidance_distillation_path is not None
                else ""
            )
            summary["latest_compiler_ir_guidance_distillation_deduped_count"] = int(
                guidance_distillation_deduped_count
            )
            summary[
                "latest_compiler_ir_guidance_distillation_semantic_deduped_count"
            ] = int(guidance_distillation_semantic_deduped_count)
            summary["latest_compiler_ir_guidance_distillation_seeded_count"] = int(
                guidance_distillation_seeded_count
            )
            summary["latest_compiler_ir_guidance_distillation_todo_ids"] = list(
                guidance_distillation_todo_ids
            )
            summary["latest_compiler_ir_guidance_activation_seeded_count"] = int(
                guidance_activation_seeded_count
            )
            summary["latest_compiler_ir_guidance_activation_deduped_count"] = int(
                guidance_activation_deduped_count
            )
            summary[
                "latest_compiler_ir_guidance_activation_semantic_deduped_count"
            ] = int(guidance_activation_semantic_deduped_count)
            summary["latest_compiler_ir_guidance_activation_todo_ids"] = list(
                guidance_activation_todo_ids
            )
            summary["latest_compiler_ir_guidance_guardrail_seeded_count"] = int(
                guidance_guardrail_seeded_count
            )
            summary["latest_compiler_ir_guidance_guardrail_deduped_count"] = int(
                guidance_guardrail_deduped_count
            )
            summary["latest_compiler_ir_guidance_guardrail_todo_ids"] = list(
                guidance_guardrail_todo_ids
            )
            guidance_distillation_seeded_total = int(
                summary.get("compiler_ir_guidance_distillation_seeded_total", 0)
                or 0
            ) + int(guidance_distillation_seeded_count)
            guidance_distillation_deduped_total = int(
                summary.get("compiler_ir_guidance_distillation_deduped_total", 0)
                or 0
            ) + int(guidance_distillation_deduped_count)
            guidance_distillation_semantic_deduped_total = int(
                summary.get(
                    "compiler_ir_guidance_distillation_semantic_deduped_total",
                    0,
                )
                or 0
            ) + int(guidance_distillation_semantic_deduped_count)
            guidance_activation_seeded_total = int(
                summary.get("compiler_ir_guidance_activation_seeded_total", 0)
                or 0
            ) + int(guidance_activation_seeded_count)
            guidance_activation_deduped_total = int(
                summary.get("compiler_ir_guidance_activation_deduped_total", 0)
                or 0
            ) + int(guidance_activation_deduped_count)
            guidance_activation_semantic_deduped_total = int(
                summary.get(
                    "compiler_ir_guidance_activation_semantic_deduped_total",
                    0,
                )
                or 0
            ) + int(guidance_activation_semantic_deduped_count)
            guidance_guardrail_seeded_total = int(
                summary.get("compiler_ir_guidance_guardrail_seeded_total", 0)
                or 0
            ) + int(guidance_guardrail_seeded_count)
            guidance_guardrail_deduped_total = int(
                summary.get("compiler_ir_guidance_guardrail_deduped_total", 0)
                or 0
            ) + int(guidance_guardrail_deduped_count)
            summary["compiler_ir_guidance_distillation_seeded_total"] = int(
                guidance_distillation_seeded_total
            )
            summary["compiler_ir_guidance_distillation_deduped_total"] = int(
                guidance_distillation_deduped_total
            )
            summary[
                "compiler_ir_guidance_distillation_semantic_deduped_total"
            ] = int(guidance_distillation_semantic_deduped_total)
            summary["compiler_ir_guidance_activation_seeded_total"] = int(
                guidance_activation_seeded_total
            )
            summary["compiler_ir_guidance_activation_deduped_total"] = int(
                guidance_activation_deduped_total
            )
            summary["compiler_ir_guidance_activation_semantic_deduped_total"] = int(
                guidance_activation_semantic_deduped_total
            )
            summary["compiler_ir_guidance_guardrail_seeded_total"] = int(
                guidance_guardrail_seeded_total
            )
            summary["compiler_ir_guidance_guardrail_deduped_total"] = int(
                guidance_guardrail_deduped_total
            )
            summary["latest_failed_validation_rescue_seeded_count"] = int(
                failed_validation_rescue_seeded_count
            )
            summary["latest_failed_validation_rescue_deduped_count"] = int(
                failed_validation_rescue_deduped_count
            )
            summary["latest_failed_validation_rescue_todo_ids"] = list(
                failed_validation_rescue_todo_ids
            )
            summary["latest_compiler_ir_guidance_ce_delta"] = (
                latest_compiler_ir_guidance_ce_delta
            )
            summary["latest_compiler_ir_guidance_cosine_delta"] = (
                latest_compiler_ir_guidance_cosine_delta
            )
            summary["latest_compiler_ir_guidance_copy_hack_delta"] = (
                latest_compiler_ir_guidance_copy_hack_delta
            )
            summary["latest_learned_ir_train"] = learned_ir_train
            summary["latest_learned_ir_validation"] = learned_ir_validation
            summary["latest_learned_ir_family_ce_excess"] = (
                latest_learned_ir_family_ce_excess
            )
            summary["latest_learned_ir_view_ce"] = latest_learned_ir_view_ce
            summary["latest_learned_ir_view_cosine"] = latest_learned_ir_view_cosine
            summary["latest_learned_ir_worst_family_ce_excess"] = (
                latest_learned_ir_worst_family_ce_excess
            )
            summary["latest_learned_ir_worst_family_ce_excess_name"] = (
                learned_ir_validation.get("worst_family_cross_entropy_excess_name")
            )
            summary["latest_learned_ir_worst_family_cosine_gap"] = (
                latest_learned_ir_worst_family_cosine_gap
            )
            summary["latest_learned_ir_worst_family_cosine_gap_name"] = (
                learned_ir_validation.get("worst_family_cosine_gap_name")
            )
            summary["latest_validation_signal_separation"] = {
                "autoencoder_generalization": _basic_autoencoder_metric_block(
                    after_validation
                ),
                "deterministic_compiler_ir": {
                    "cross_entropy_excess_loss": round(
                        latest_compiler_ir_ce_excess,
                        9,
                    ),
                    "cross_entropy_loss": round(latest_compiler_ir_ce, 9),
                    "metric_role": (
                        "deterministic compiler/decompiler IR round-trip"
                    ),
                    "raw_source_embedding_cosine_similarity": round(
                        latest_compiler_ir_raw_source_embedding_cosine,
                        9,
                    ),
                    "structural_ir_cosine_similarity": round(
                        latest_compiler_ir_cosine,
                        9,
                    ),
                },
                "learned_ir_view": {
                    "family_cross_entropy_excess_loss": round(
                        latest_learned_ir_family_ce_excess,
                        9,
                    ),
                    "metric_role": (
                        "autoencoder-predicted LegalIR view/family alignment"
                    ),
                    "view_cosine_similarity": round(
                        latest_learned_ir_view_cosine,
                        9,
                    ),
                    "view_cross_entropy_loss": round(
                        latest_learned_ir_view_ce,
                        9,
                    ),
                    "worst_family_cosine_gap_loss": round(
                        latest_learned_ir_worst_family_cosine_gap,
                        9,
                    ),
                    "worst_family_cross_entropy_excess_loss": round(
                        latest_learned_ir_worst_family_ce_excess,
                        9,
                    ),
                },
                "logic_bridge_validation": {
                    "acceptance_rate": round(
                        float(bridge_ir_validation.get("acceptance_rate", 0.0)),
                        9,
                    ),
                    "metric_role": (
                        "syntax/prover/KG bridge checks over diagnostic adapters"
                    ),
                    "proof_failure_ratio": round(
                        float(
                            bridge_ir_validation.get(
                                "proof_failure_ratio",
                                0.0,
                            )
                        ),
                        9,
                    ),
                    "sampled": bool(bridge_ir_validation.get("sampled", False)),
                    "total_loss": round(
                        float(bridge_ir_validation.get("total_loss", 0.0)),
                        9,
                    ),
                },
                "metric_roles": {
                    "autoencoder_generalization": (
                        "held-out samples with sample memory disabled; this is "
                        "the core generalization signal"
                    ),
                    "deterministic_compiler_ir": (
                        "current Python compiler/decompiler IR quality, not the "
                        "learned embedding head"
                    ),
                    "learned_ir_view": (
                        "autoencoder's learned projection into LegalIR view/family "
                        "space"
                    ),
                    "sample_memory_probe": (
                        "same samples with sample-specific memory enabled; a large "
                        "gain indicates memorization pressure"
                    ),
                    "source_copy_guard": (
                        "penalizes decompilers that copy source spans instead of "
                        "round-tripping through useful IR"
                    ),
                },
                "sample_memory_probe": validation_sample_memory_gap,
                "signal_health": summary["latest_autoencoder_signal_health"],
                "source_copy_guard": {
                    "copy_hack_penalty": round(
                        latest_compiler_ir_source_copy_reward_hack_penalty,
                        9,
                    ),
                    "source_copy_loss": round(
                        latest_compiler_ir_source_copy_loss,
                        9,
                    ),
                    "source_decompiled_text_embedding_cosine_loss": round(
                        latest_source_decompiled_text_embedding_cosine_loss,
                        9,
                    ),
                    "source_decompiled_text_token_loss": round(
                        latest_source_decompiled_text_token_loss,
                        9,
                    ),
                },
                "validation_mode": validation_mode,
            }
            summary["validation_mode"] = validation_mode
            program_synthesis_status = update_program_synthesis_summary(
                summary,
                supervisor.queue,
                supervisor.policy,
            )
            program_synthesis_seeded_count = sum(
                step.program_synthesis_seeded_count for step in run.steps
            ) + int(guidance_distillation_seeded_count) + int(
                guidance_activation_seeded_count
            ) + int(
                guidance_guardrail_seeded_count
            ) + int(
                failed_validation_rescue_seeded_count
            )
            summary["program_synthesis_seeded"] = int(
                summary.get("program_synthesis_seeded", 0)
            ) + int(program_synthesis_seeded_count)
            preinsert_deduped_count = sum(
                step.program_synthesis_deduped_count for step in run.steps
            ) + int(guidance_distillation_deduped_count) + int(
                guidance_activation_deduped_count
            ) + int(
                guidance_guardrail_deduped_count
            ) + int(
                failed_validation_rescue_deduped_count
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
            summary["latest_program_synthesis_seeded_count"] = int(
                program_synthesis_seeded_count
            )
            summary["latest_program_synthesis_preinsert_deduped_count"] = int(
                preinsert_deduped_count
            )
            summary["latest_program_synthesis_semantic_deduped_count"] = int(
                semantic_deduped_count
            )
            summary["latest_todo_generation"] = {
                "claimed": int(program_synthesis_status["claimed"]),
                "completed": int(program_synthesis_status["completed"]),
                "deduped_total": int(summary.get("program_synthesis_deduped_total", 0)),
                "execution_mode": program_synthesis_status["execution_mode"],
                "pending": int(program_synthesis_status["pending"]),
                "preinsert_deduped_count": int(preinsert_deduped_count),
                "seeded_count": int(program_synthesis_seeded_count),
                "semantic_deduped_count": int(semantic_deduped_count),
                "compiler_guidance_distillation_deduped_count": int(
                    guidance_distillation_deduped_count
                ),
                "compiler_guidance_distillation_seeded_count": int(
                    guidance_distillation_seeded_count
                ),
                "compiler_guidance_distillation_seeded_total": int(
                    guidance_distillation_seeded_total
                ),
                "compiler_guidance_distillation_deduped_total": int(
                    guidance_distillation_deduped_total
                ),
                "compiler_guidance_distillation_semantic_deduped_total": int(
                    guidance_distillation_semantic_deduped_total
                ),
                "compiler_guidance_activation_deduped_count": int(
                    guidance_activation_deduped_count
                ),
                "compiler_guidance_activation_seeded_count": int(
                    guidance_activation_seeded_count
                ),
                "compiler_guidance_activation_seeded_total": int(
                    guidance_activation_seeded_total
                ),
                "compiler_guidance_activation_deduped_total": int(
                    guidance_activation_deduped_total
                ),
                "compiler_guidance_activation_semantic_deduped_total": int(
                    guidance_activation_semantic_deduped_total
                ),
                "compiler_guidance_guardrail_deduped_count": int(
                    guidance_guardrail_deduped_count
                ),
                "compiler_guidance_guardrail_seeded_count": int(
                    guidance_guardrail_seeded_count
                ),
                "compiler_guidance_guardrail_seeded_total": int(
                    guidance_guardrail_seeded_total
                ),
                "compiler_guidance_guardrail_deduped_total": int(
                    guidance_guardrail_deduped_total
                ),
                "failed_validation_rescue_deduped_count": int(
                    failed_validation_rescue_deduped_count
                ),
                "failed_validation_rescue_seeded_count": int(
                    failed_validation_rescue_seeded_count
                ),
            }
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
                + compiler_ir_guided_train.get("metric_failures", 0)
                + compiler_ir_guided_validation.get("metric_failures", 0)
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
            guidance_improved = bool(guidance_canary.get("improved"))
            summary["compiler_guidance_improved_cycles"] = int(
                summary.get("compiler_guidance_improved_cycles", 0)
            ) + int(guidance_improved)
            guidance_regressed = bool(guidance_canary.get("regressed"))
            if guidance_regressed:
                summary["compiler_guidance_regression_streak"] = int(
                    summary.get("compiler_guidance_regression_streak", 0)
                ) + 1
            else:
                summary["compiler_guidance_regression_streak"] = 0
            summary["learning_rate_applied"] = float(cycle_learning_rate)
            summary["learning_rate_policy"] = cycle_lr_policy
            summary["best_validation_ce"] = min(summary.get("best_validation_ce"), after_validation.cross_entropy_loss)
            summary["best_validation_ir_ce"] = min(
                summary.get("best_validation_ir_ce", 1.0e12),
                latest_compiler_ir_ce,
            )
            summary["best_validation_ir_guided_ce"] = min(
                summary.get("best_validation_ir_guided_ce", 1.0e12),
                latest_guided_compiler_ir_ce,
            )
            summary["best_validation_ir_guided_ce_excess"] = min(
                summary.get("best_validation_ir_guided_ce_excess", 1.0e12),
                latest_guided_compiler_ir_ce_excess,
            )
            summary["best_validation_ir_guided_cosine"] = max(
                summary.get("best_validation_ir_guided_cosine", -1.0),
                latest_guided_compiler_ir_cosine,
            )
            summary["best_validation_ir_guided_source_copy_reward_hack_penalty"] = min(
                summary.get(
                    "best_validation_ir_guided_source_copy_reward_hack_penalty",
                    1.0e12,
                ),
                latest_guided_compiler_ir_source_copy_reward_hack_penalty,
            )
            summary["best_validation_ir_cosine"] = max(
                summary.get("best_validation_ir_cosine", -1.0),
                latest_compiler_ir_cosine,
            )
            summary["best_validation_ir_reconstruction"] = min(
                summary.get("best_validation_ir_reconstruction", 1.0e12),
                float(compiler_ir_validation.get("reconstruction_loss", 1.0e12)),
            )
            summary["best_validation_ir_source_copy_loss"] = min(
                summary.get("best_validation_ir_source_copy_loss", 1.0e12),
                latest_compiler_ir_source_copy_loss,
            )
            summary["best_validation_ir_structural_text_reconstruction"] = min(
                summary.get("best_validation_ir_structural_text_reconstruction", 1.0e12),
                float(
                    compiler_ir_validation.get(
                        "structural_text_reconstruction_loss",
                        1.0e12,
                    )
                ),
            )
            summary["best_validation_ir_text_reconstruction"] = min(
                summary.get("best_validation_ir_text_reconstruction", 1.0e12),
                float(compiler_ir_validation.get("text_reconstruction_loss", 1.0e12)),
            )
            summary["best_validation_ir_source_decompiled_text_embedding_cosine_loss"] = min(
                summary.get(
                    "best_validation_ir_source_decompiled_text_embedding_cosine_loss",
                    1.0e12,
                ),
                latest_source_decompiled_text_embedding_cosine_loss,
            )
            summary["best_validation_ir_source_decompiled_text_token_loss"] = min(
                summary.get(
                    "best_validation_ir_source_decompiled_text_token_loss",
                    1.0e12,
                ),
                latest_source_decompiled_text_token_loss,
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
            summary["best_validation_learned_ir_view_ce"] = min(
                summary.get("best_validation_learned_ir_view_ce", 1.0e12),
                latest_learned_ir_view_ce,
            )
            summary["best_validation_learned_ir_view_cosine"] = max(
                summary.get("best_validation_learned_ir_view_cosine", -1.0),
                latest_learned_ir_view_cosine,
            )
            summary["best_validation_learned_ir_family_ce_excess"] = min(
                summary.get("best_validation_learned_ir_family_ce_excess", 1.0e12),
                latest_learned_ir_family_ce_excess,
            )
            summary["best_validation_learned_ir_worst_family_ce_excess"] = min(
                summary.get(
                    "best_validation_learned_ir_worst_family_ce_excess",
                    1.0e12,
                ),
                latest_learned_ir_worst_family_ce_excess,
            )
            summary["best_validation_learned_ir_worst_family_cosine_gap"] = min(
                summary.get(
                    "best_validation_learned_ir_worst_family_cosine_gap",
                    1.0e12,
                ),
                latest_learned_ir_worst_family_cosine_gap,
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
                    "after_train": after_train_metrics,
                    "after_validation": after_validation_metrics,
                    "applied_count": sum(step.applied_count for step in run.steps),
                    "autoencoder_state_telemetry": latest_state_telemetry,
                    "autoencoder_after_train": after_train_metrics,
                    "autoencoder_after_validation": after_validation_metrics,
                    "autoencoder_before_train": before_train_metrics,
                    "autoencoder_before_validation": before_validation_metrics,
                    "autoencoder_train_generalized_probe": (
                        after_train_generalized_probe_metrics
                    ),
                    "autoencoder_validation_sample_memory_probe": (
                        after_validation_sample_memory_probe_metrics
                    ),
                    "before_train": before_train_metrics,
                    "before_validation": before_validation_metrics,
                    "completed_count": sum(step.completed_count for step in run.steps),
                    "compiler_ir_guided_train": compiler_ir_guided_train,
                    "compiler_ir_guided_validation": compiler_ir_guided_validation,
                    "compiler_ir_guidance_ce_delta": latest_compiler_ir_guidance_ce_delta,
                    "compiler_ir_guidance_copy_hack_delta": (
                        latest_compiler_ir_guidance_copy_hack_delta
                    ),
                    "compiler_ir_guidance_cosine_delta": (
                        latest_compiler_ir_guidance_cosine_delta
                    ),
                    "compiler_ir_guidance_canary": guidance_canary,
                    "compiler_ir_guidance_distillation": guidance_distillation,
                    "compiler_ir_guidance_distillation_deduped_count": int(
                        guidance_distillation_deduped_count
                    ),
                    "compiler_ir_guidance_distillation_seeded_count": int(
                        guidance_distillation_seeded_count
                    ),
                    "compiler_ir_guidance_distillation_seeded_total": int(
                        guidance_distillation_seeded_total
                    ),
                    "compiler_ir_guidance_distillation_deduped_total": int(
                        guidance_distillation_deduped_total
                    ),
                    "compiler_ir_guidance_distillation_semantic_deduped_total": int(
                        guidance_distillation_semantic_deduped_total
                    ),
                    "compiler_ir_guidance_distillation_todo_ids": list(
                        guidance_distillation_todo_ids
                    ),
                    "compiler_ir_guidance_activation_deduped_count": int(
                        guidance_activation_deduped_count
                    ),
                    "compiler_ir_guidance_activation_seeded_count": int(
                        guidance_activation_seeded_count
                    ),
                    "compiler_ir_guidance_activation_seeded_total": int(
                        guidance_activation_seeded_total
                    ),
                    "compiler_ir_guidance_activation_deduped_total": int(
                        guidance_activation_deduped_total
                    ),
                    "compiler_ir_guidance_activation_semantic_deduped_total": int(
                        guidance_activation_semantic_deduped_total
                    ),
                    "compiler_ir_guidance_activation_todo_ids": list(
                        guidance_activation_todo_ids
                    ),
                    "compiler_ir_guidance_guardrail_deduped_count": int(
                        guidance_guardrail_deduped_count
                    ),
                    "compiler_ir_guidance_guardrail_seeded_count": int(
                        guidance_guardrail_seeded_count
                    ),
                    "compiler_ir_guidance_guardrail_seeded_total": int(
                        guidance_guardrail_seeded_total
                    ),
                    "compiler_ir_guidance_guardrail_deduped_total": int(
                        guidance_guardrail_deduped_total
                    ),
                    "compiler_ir_guidance_guardrail_todo_ids": list(
                        guidance_guardrail_todo_ids
                    ),
                    "compiler_ir_guidance_promotion": guidance_promotion_gate,
                    "compiler_ir_guidance_scope_hints": guidance_scope_hints,
                    "compiler_ir_train": compiler_ir_train,
                    "compiler_ir_validation": compiler_ir_validation,
                    "learned_ir_before_train": learned_ir_before_train,
                    "learned_ir_before_validation": learned_ir_before_validation,
                    "learned_ir_train": learned_ir_train,
                    "learned_ir_validation": learned_ir_validation,
                    "logic_bridge_train": bridge_ir_train,
                    "logic_bridge_validation": bridge_ir_validation,
                    "cycle": cycle,
                    "duration_seconds": latest_cycle_seconds,
                    "cycle_phase_timings": latest_cycle_phase_timings,
                    "event": "cycle",
                    "failed_validation_count": sum(step.failed_validation_count for step in run.steps),
                    "failed_validation_rescue_deduped_count": int(
                        failed_validation_rescue_deduped_count
                    ),
                    "failed_validation_rescue_seeded_count": int(
                        failed_validation_rescue_seeded_count
                    ),
                    "failed_validation_rescue_todo_ids": list(
                        failed_validation_rescue_todo_ids
                    ),
                    "feature_projection_report": feature_projection_report,
                    "learning_rate_applied": float(cycle_learning_rate),
                    "learning_rate_policy": cycle_lr_policy,
                    "bridge_loss_failure_count": bridge_loss_failures,
                    "bridge_loss_sample_count": bridge_loss_samples,
                    "bridge_loss_signal_count": bridge_loss_signals,
                    "queue_counts": supervisor.queue.status_counts(),
                    "role_queue_counts": supervisor.queue.role_status_counts(),
                    "train_sample_memory_gap": train_sample_memory_gap,
                    "validation_sample_memory_gap": validation_sample_memory_gap,
                    "stopped_reason": run.stopped_reason,
                    "program_synthesis_claimed_count": program_synthesis_status["claimed"],
                    "program_synthesis_completed_count": program_synthesis_status["completed"],
                    "program_synthesis_execution_mode": program_synthesis_status["execution_mode"],
                    "program_synthesis_pending_count": program_synthesis_status["pending"],
                    "program_synthesis_seeded_count": program_synthesis_seeded_count,
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

            if _should_run_cycle_tests(cycle, args.test_every_cycles):
                test_result = run_tests(root, report_dir, cycle)
                summary["test_failures"] = int(summary.get("test_failures", 0)) + int(test_result["exit_code"] != 0)
                append_event(log_path, args.run_id, test_result)
                save_summary(summary_path, summary)
        if not stop_state.stop_requested and int(summary.get("cycles", 0) or 0) <= 0:
            now = time.time()
            remaining_seconds = max(0.0, end_at - now)
            stop_reason = (
                "startup_budget_exhausted"
                if now + cycle_start_margin_seconds >= end_at
                else "no_autoencoder_cycles"
            )
            summary["latest_stop_reason"] = stop_reason
            summary["remaining_seconds_at_stop"] = round(remaining_seconds, 3)
            summary["startup_seconds"] = round(now - started_at, 3)
            append_event(
                log_path,
                args.run_id,
                {
                    "cycle_start_margin_seconds": cycle_start_margin_seconds,
                    "event": "autoencoder_no_cycle",
                    "remaining_seconds": round(remaining_seconds, 3),
                    "startup_seconds": round(now - started_at, 3),
                    "stop_reason": stop_reason,
                },
            )
            save_summary(summary_path, summary)
    finally:
        if stop_state.stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_state.stop_signal}"
            summary["stopped_by_signal"] = stop_state.stop_signal
        backend_metadata = autoencoder.compute_backend_metadata()
        summary.update(backend_metadata)
        summary["latest_autoencoder_backend"] = dict(backend_metadata)
        summary["latest_host_resource_health"] = paired_resource_health()
        summary["autoencoder_architecture_version"] = (
            MODAL_AUTOENCODER_ARCHITECTURE_VERSION
        )
        summary["autoencoder_low_rank_state_schema_version"] = (
            MODAL_AUTOENCODER_LOW_RANK_STATE_SCHEMA_VERSION
        )
        summary["autoencoder_state_schema_version"] = (
            MODAL_AUTOENCODER_STATE_SCHEMA_VERSION
        )
        summary["latest_autoencoder_state_telemetry"] = autoencoder_state_telemetry(
            autoencoder.state,
            state_path=state_path,
        )
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
        stop_state.restore()
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

    def request_stop(signum: int, frame: Any) -> None:
        _terminate_active_codex_exec_processes(signal.SIGTERM)

    stop_state = accelerate_install_stop_signal_handlers(on_signal=request_stop)

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
            "codex_claim_stale_seconds": _codex_claim_stale_seconds(args),
            "codex_main_apply_lock_timeout_seconds": args.codex_main_apply_lock_timeout_seconds,
            "codex_main_apply_max_inflight_packets": args.codex_main_apply_max_inflight_packets,
            "codex_merge_repair_attempts": args.codex_merge_repair_attempts,
            "codex_merge_repair_mode": args.codex_merge_repair_mode,
            "codex_scope": args.codex_scope,
            "codex_task_embeddings_provider": args.codex_task_embeddings_provider,
            "codex_validation_timeout_seconds": args.codex_validation_timeout_seconds,
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
    summary.setdefault("codex_claim_stale_seconds", _codex_claim_stale_seconds(args))
    summary.setdefault("codex_commit_mode", args.codex_commit_mode)
    summary.setdefault("codex_lane_lock_mode", args.codex_lane_lock_mode)
    summary.setdefault("codex_merge_repair_attempts", args.codex_merge_repair_attempts)
    summary.setdefault("codex_merge_repair_mode", args.codex_merge_repair_mode)
    summary.setdefault("codex_scope", args.codex_scope)
    summary.setdefault("codex_task_embeddings_provider", args.codex_task_embeddings_provider)
    summary.setdefault("codex_validation_timeout_seconds", args.codex_validation_timeout_seconds)
    summary.setdefault("codex_vector_index_path", str(_codex_vector_index_path(args, queue_path)))
    summary.setdefault("codex_vector_max_bundle_wait_seconds", args.codex_vector_max_bundle_wait_seconds)
    summary.setdefault("codex_vector_min_bundle_size", args.codex_vector_min_bundle_size)
    summary.setdefault("codex_vector_min_similarity", args.codex_vector_min_similarity)
    summary.setdefault("codex_main_apply_count", 0)
    summary.setdefault("codex_main_apply_failure_count", 0)
    summary.setdefault("codex_main_apply_backpressure_wait_count", 0)
    summary.setdefault("codex_main_apply_repair_count", 0)
    summary.setdefault(
        "codex_main_apply_max_inflight_packets",
        args.codex_main_apply_max_inflight_packets,
    )
    summary.setdefault("codex_stale_claim_requeue_count", 0)
    summary.setdefault("codex_transient_requeue_count", 0)

    started_at = parse_utc(summary["started_at"])
    end_at = started_at + args.duration_seconds
    policy = ModalOptimizerPolicy()

    @contextmanager
    def active_codex_packet_heartbeat(
        claimed_todos: Sequence[ModalTodo],
        *,
        cycle: int,
    ) -> Iterator[Dict[str, Any]]:
        active_packet: Dict[str, Any] = {}
        stop_event = threading.Event()
        claimed_ids = [todo.todo_id for todo in claimed_todos]
        claimed_scopes = sorted(
            {
                str(todo.metadata.get("program_synthesis_scope") or "")
                for todo in claimed_todos
                if todo.metadata.get("program_synthesis_scope")
            }
        )

        def write_heartbeat(*, phase: str) -> None:
            heartbeat_at = utc_now()
            summary["active_packet_cycle"] = int(cycle)
            summary["active_packet_phase"] = phase
            summary["active_packet_last_heartbeat_at"] = heartbeat_at
            summary["active_packet_claimed_todo_ids"] = list(claimed_ids)
            summary["active_packet_scopes"] = list(claimed_scopes)
            summary["active_packet_worker_id"] = worker_id
            summary["heartbeat_at"] = heartbeat_at
            summary["latest_stop_reason"] = phase
            summary["updated_at"] = heartbeat_at
            if active_packet.get("packet_id"):
                summary["active_packet_id"] = active_packet["packet_id"]
            if active_packet.get("packet_path"):
                summary["active_packet_path"] = active_packet["packet_path"]
            save_summary(summary_path, summary)

        def heartbeat_loop() -> None:
            while not stop_event.wait(10.0):
                write_heartbeat(phase="executing_codex_packet")

        write_heartbeat(phase="claimed_program_synthesis_todos")
        thread = threading.Thread(
            target=heartbeat_loop,
            name=f"codex-packet-heartbeat-{worker_id}",
            daemon=True,
        )
        thread.start()
        try:
            yield active_packet
        finally:
            stop_event.set()
            thread.join(timeout=2.0)
            summary["active_packet_completed_at"] = utc_now()
            summary["active_packet_phase"] = "idle"
            summary["active_packet_claimed_todo_ids"] = []
            summary["active_packet_scopes"] = []
            summary.pop("active_packet_id", None)
            summary.pop("active_packet_path", None)
            save_summary(summary_path, summary)

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
        while not stop_state.stop_requested and time.time() < end_at:
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            packet: Dict[str, Any] = {}
            vector_claim_report: Dict[str, Any] = {}
            bundle_mode = str(getattr(args, "codex_bundle_mode", "semantic")).strip().lower()
            stale_claim_report = requeue_stale_program_synthesis_claims(
                queue_path=queue_path,
                policy=policy,
                max_age_seconds=_codex_claim_stale_seconds(args),
                reason="codex_claim_timeout",
            )
            if int(stale_claim_report.get("requeued_count", 0) or 0) > 0:
                summary["latest_stale_claim_requeue"] = dict(stale_claim_report)
                summary["codex_stale_claim_requeue_count"] = int(
                    summary.get("codex_stale_claim_requeue_count", 0) or 0
                ) + int(stale_claim_report.get("requeued_count", 0) or 0)
            with queue_file_lock(queue_path):
                backpressure_queue = ModalTodoQueue.load_jsonl(queue_path)
                apply_backpressure_report = _codex_main_apply_backpressure_report(
                    backpressure_queue,
                    args=args,
                    policy=policy,
                    worker_id=worker_id,
                )
                status = update_program_synthesis_summary(
                    summary,
                    backpressure_queue,
                    policy,
                    execution_mode=execution_mode,
                )
            summary["latest_codex_main_apply_backpressure"] = dict(
                apply_backpressure_report
            )
            if apply_backpressure_report.get("blocked"):
                summary["cycles"] = cycle
                summary["codex_main_apply_backpressure_wait_count"] = int(
                    summary.get("codex_main_apply_backpressure_wait_count", 0) or 0
                ) + 1
                summary["latest_stop_reason"] = str(
                    apply_backpressure_report.get("reason")
                    or "main_apply_backpressure"
                )
                summary["updated_at"] = utc_now()
                summary["heartbeat_at"] = summary["updated_at"]
                save_summary(summary_path, summary)
                append_event(
                    log_path,
                    args.run_id,
                    {
                        "event": "codex_main_apply_backpressure_wait",
                        "report": dict(apply_backpressure_report),
                        "worker_id": worker_id,
                    },
                )
                time.sleep(max(1.0, float(args.poll_seconds)))
                continue
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
                    requested_scope = getattr(args, "codex_scope", None)
                    apply_backpressure_report = _codex_main_apply_backpressure_report(
                        queue,
                        args=args,
                        policy=policy,
                        worker_id=worker_id,
                    )
                    if apply_backpressure_report.get("blocked"):
                        claimed = []
                        fallback_report = {}
                        vector_claim_report = {
                            "mode": "main_apply_backpressure",
                            "selected_count": 0,
                            "wait_reason": str(
                                apply_backpressure_report.get("reason")
                                or "main_apply_backpressure"
                            ),
                            **{
                                f"main_apply_backpressure_{key}": value
                                for key, value in apply_backpressure_report.items()
                            },
                        }
                        status = update_program_synthesis_summary(
                            summary,
                            queue,
                            policy,
                            execution_mode=execution_mode,
                        )
                    else:
                        claimed, fallback_report = (
                            _claim_program_synthesis_batch_with_scope_fallback(
                                supervisor,
                                worker_id=worker_id,
                                max_items=args.max_items,
                                requested_scope=requested_scope,
                                semantic_bundle=(bundle_mode == "semantic"),
                                fallback_to_global=bool(
                                    getattr(args, "codex_scope_fallback_to_global", True)
                                ),
                            )
                        )
                        if fallback_report.get("fallback_used"):
                            summary["latest_codex_scope_fallback_claim"] = dict(
                                fallback_report
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
                with active_codex_packet_heartbeat(
                    claimed,
                    cycle=cycle,
                ) as active_packet:
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
                    active_packet.update(
                        {
                            "packet_id": packet.get("packet_id"),
                            "packet_path": packet.get("packet_path"),
                        }
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
                            main_apply_lock_timeout_seconds=args.codex_main_apply_lock_timeout_seconds,
                            validation_commands=_codex_validation_commands_for_todos(claimed),
                            validation_timeout_seconds=args.codex_validation_timeout_seconds,
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
            if not stop_state.stop_requested:
                time.sleep(sleep_seconds)
    finally:
        if stop_state.stop_requested:
            summary["latest_stop_reason"] = f"signal_{stop_state.stop_signal}"
            summary["stopped_by_signal"] = stop_state.stop_signal
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
        stop_state.restore()
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
