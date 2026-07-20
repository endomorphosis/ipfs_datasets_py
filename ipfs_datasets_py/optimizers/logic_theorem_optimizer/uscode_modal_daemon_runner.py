"""Guarded U.S. Code modal TODO daemon runner.

This module owns the production runner used by the optimizer experiments.  It
keeps validation clean by ignoring sample-specific memorization, rolling back
failed validation updates through ``ModalTodoSupervisor``, and avoiding
validation rows that already have sample-memory entries in the current state.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
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
from typing import AbstractSet, Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence

import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION,
    LegalIRHammerConfig,
    attach_legal_ir_contract_telemetry,
    collect_legal_ir_contract_telemetry,
    generate_legal_ir_proof_obligations,
    run_legal_ir_hammer,
    summarize_legal_ir_contract_telemetry,
)
from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    IntrospectionPacketExportConfig,
    MODAL_INTROSPECTION_MODES,
    ModalLogicCodecConfig,
    append_disagreement_packets_jsonl,
    decoded_modal_phrase_slot_text_map,
    export_introspection_packet,
    introspection_export_mode_enabled,
    modal_text_token_similarity,
)
from ipfs_datasets_py.logic.modal.codec import stable_mock_embedding
from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES
from ipfs_datasets_py.logic.submodule_registry import (
    logic_optimizer_scope_for_component,
    logic_optimizer_target_file_hints,
    logic_submodule_specs,
)
from ipfs_datasets_py.optimizers.agentic.patch_control import PatchManager, WorktreeManager
from ipfs_datasets_py.optimizers.common.llm_defaults import DEFAULT_CODEX_MODEL
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    AutoencoderEvaluation,
    HAMMER_GUIDANCE_METRIC_SCHEMA_VERSION,
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
    ModalAutoencoderTrainingState,
    evaluate_modal_prover_compilation,
    hammer_guidance_metric_block,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_reporting import (
    build_modal_supervisor_health_report,
    state_to_compiler_patch_lag,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    LeanstralTodoProjectionConfig,
    ModalOptimizationRun,
    ModalOptimizerPolicy,
    ModalTodo,
    ModalTodoQueue,
    ModalTodoSupervisor,
    PROGRAM_SYNTHESIS_ROLE,
    PROGRAM_SYNTHESIS_ACTION_TARGETS,
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
BRIDGE_EVALUATE_PROVERS_ENV = "IPFS_DATASETS_BRIDGE_EVALUATE_PROVERS"
_TRUE_ENV_VALUES = {"1", "true", "yes", "y", "on"}
DEFAULT_BRIDGE_EVALUATE_PROVERS = (
    str(os.environ.get(BRIDGE_EVALUATE_PROVERS_ENV) or "").strip().lower()
    in _TRUE_ENV_VALUES
)
AUTOENCODER_METRIC_BRIDGE_ADAPTERS_ENV = (
    "IPFS_DATASETS_AUTOENCODER_METRIC_BRIDGE_ADAPTERS"
)
AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS_ENV = (
    "IPFS_DATASETS_AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS"
)
DEFAULT_AUTOENCODER_METRIC_BRIDGE_ADAPTERS = (
    "modal_frame_logic",
    "deontic_norms",
)
DEFAULT_VALIDATION_CANARY_COUNT = 4
DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS = 400
DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS = 600.0
DEFAULT_GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS = 3
DEFAULT_COMPILER_IR_TRAIN_MODE = "periodic"
DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE = "periodic"
DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE = "periodic"
DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE = "periodic"
DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE = "starved"
DEFAULT_CANONICAL_AUTOENCODER_STATE_NAME = "legal-ir-autoencoder-canonical.state.json"
DEFAULT_AUTOENCODER_INTROSPECTION_MODE = "off"
DEFAULT_AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES = 4
DEFAULT_AUTOENCODER_INTROSPECTION_MIN_EXPORT_SAMPLES = 0
AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION = "legal-ir-daemon-metrics-v2"
DAEMON_HAMMER_GUIDANCE_CYCLE_SCHEMA_VERSION = "legal-ir-daemon-hammer-guidance-cycle-v1"
DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_SAMPLES_PER_CYCLE = 2
DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_OBLIGATIONS_PER_SAMPLE = 8
DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_PREMISES = 128
DEFAULT_DAEMON_HAMMER_GUIDANCE_TIMEOUT_SECONDS = 1.0
DEFAULT_DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS = 2
AUTOENCODER_CANONICAL_WARM_START_ENV = "IPFS_DATASETS_AUTOENCODER_CANONICAL_WARM_START"
AUTOENCODER_CANONICAL_WARM_START_STATE_ENV = (
    "IPFS_DATASETS_AUTOENCODER_CANONICAL_WARM_START_STATE"
)
AUTOENCODER_CANONICAL_WARM_START_MODES = frozenset({"auto", "off", "require"})


def _default_bridge_evaluate_provers() -> bool:
    return (
        str(os.environ.get(BRIDGE_EVALUATE_PROVERS_ENV) or "").strip().lower()
        in _TRUE_ENV_VALUES
    )


def _default_canonical_warm_start_mode() -> str:
    value = str(os.environ.get(AUTOENCODER_CANONICAL_WARM_START_ENV) or "auto").strip().lower()
    if value in {"0", "false", "no", "off", "none", "disabled"}:
        return "off"
    if value in {"1", "true", "yes", "y", "on", "auto"}:
        return "auto"
    if value == "require":
        return "require"
    return "auto"

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
COMPILER_IR_METRIC_PROFILE_VERSION = "compiler-ir-metric-profile-v2-bounded-real"
CODEX_TARGET_METRIC_TIMEOUT_SECONDS_ENV = (
    "IPFS_DATASETS_CODEX_TARGET_METRIC_TIMEOUT_SECONDS"
)
DEFAULT_CODEX_TARGET_METRIC_TIMEOUT_SECONDS = 300.0
CODEX_TARGET_METRIC_TRADEOFF_POLICY_VERSION = "target-metric-tradeoff-v2-hard-hammer-guardrails"
BRIDGE_IR_REPORT_CACHE_MAX = 4096
LEGAL_IR_METRIC_DISK_CACHE_VERSION = "legal-ir-metric-disk-cache-v1"
LEGAL_IR_METRIC_DISK_CACHE_DIR_ENV = "IPFS_DATASETS_LEGAL_IR_METRIC_CACHE_DIR"
LEGAL_IR_METRIC_DISK_CACHE_ENABLED_ENV = "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"
_FALSE_ENV_VALUES = {"0", "false", "no", "off", "none", "disabled"}
_BRIDGE_IR_REPORT_CACHE_LOCK = threading.Lock()


def _default_compiler_ir_metric_max_sample_text_chars() -> int:
    raw = str(
        os.environ.get(COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS_ENV) or ""
    ).strip()
    if not raw:
        return DEFAULT_COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_COMPILER_IR_METRIC_MAX_SAMPLE_TEXT_CHARS
_BRIDGE_IR_REPORT_CACHE: Dict[str, Any] = {}
_METRIC_CODE_FINGERPRINT_LOCK = threading.Lock()
_METRIC_CODE_FINGERPRINT_SIGNATURE: Optional[str] = None
_METRIC_CODE_FINGERPRINT_VALUE: Optional[str] = None
_COMPILER_IR_METRIC_BLOCK_CACHE_VERSION = "compiler-ir-metric-block-cache-v9"
_COMPILER_IR_GUIDANCE_CACHE_POLICY = "codec-output-contract-v1"
_COMPILER_IR_GUIDANCE_DIAGNOSTICS_VERSION = "compiler-guidance-diagnostics-v3"
_COMPILER_IR_SAMPLE_CACHE_VERSION = "compiler-ir-metric-sample-cache-v8"
_COMPILER_IR_SAMPLE_TIMEOUT_CACHE_POLICY = "timeout_surface_fallback_per_sample_budget_v2"
_COMPILER_IR_SAMPLE_CODE_FINGERPRINT_LOCK = threading.Lock()
_COMPILER_IR_SAMPLE_CODE_FINGERPRINT_SIGNATURE: Optional[str] = None
_COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE: Optional[str] = None
_ACTIVE_CODEX_EXEC_PROCESSES: List[subprocess.Popen[str]] = []
CODEX_WORKTREE_ARTIFACT_FILENAMES = {"changes.patch"}
COMPILER_IR_METRIC_ALIASES = {
    "cosine_similarity": "compiler_ir_cosine_similarity",
    "cross_entropy_loss": "compiler_ir_cross_entropy_loss",
    "hammer_premise_selection_hit_rate": "compiler_ir_hammer_premise_selection_hit_rate",
    "hammer_proof_failure_ratio": "compiler_ir_hammer_proof_failure_ratio",
    "hammer_proof_success_rate": "compiler_ir_hammer_proof_success_rate",
    "hammer_reconstruction_success_rate": (
        "compiler_ir_hammer_reconstruction_success_rate"
    ),
    "hammer_source_copy_penalty": "compiler_ir_hammer_source_copy_penalty",
    "modal_span_coverage_loss": "compiler_ir_modal_span_coverage_loss",
    "reconstruction_loss": "compiler_ir_reconstruction_loss",
    "source_copy_penalty": "compiler_ir_source_copy_penalty",
    "source_copy_reward_hack_penalty": "compiler_ir_source_copy_reward_hack_penalty",
    "source_decompiled_text_embedding_cosine_loss": (
        "compiler_ir_source_decompiled_text_embedding_cosine_loss"
    ),
    "source_decompiled_text_token_loss": "compiler_ir_source_decompiled_text_token_loss",
    "structural_text_reconstruction_loss": (
        "compiler_ir_structural_text_reconstruction_loss"
    ),
    "symbolic_validity_penalty": "compiler_ir_symbolic_validity_penalty",
    "symbolic_validity_success_rate": "compiler_ir_symbolic_validity_success_rate",
    "text_reconstruction_loss": "compiler_ir_text_reconstruction_loss",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_metric_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _add_compiler_ir_metric_aliases(block: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a compiler metric block with explicit compiler_ir_* aliases."""

    aliased = dict(block)
    for source_name, alias_name in COMPILER_IR_METRIC_ALIASES.items():
        if alias_name in aliased or source_name not in aliased:
            continue
        value = aliased[source_name]
        if isinstance(value, (int, float)):
            aliased[alias_name] = value
    return aliased


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


def _code_fingerprint_from_candidates(
    package_root: Path,
    candidates: Sequence[Path],
) -> tuple[str, str]:
    tokens: List[str] = []
    for candidate in candidates:
        paths = sorted(candidate.rglob("*.py")) if candidate.is_dir() else [candidate]
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
    signature = "\n".join(tokens)
    fingerprint = hashlib.sha256(signature.encode("utf-8")).hexdigest() if tokens else "unknown"
    return signature, fingerprint


def _metric_code_fingerprint() -> str:
    global _METRIC_CODE_FINGERPRINT_SIGNATURE, _METRIC_CODE_FINGERPRINT_VALUE
    with _METRIC_CODE_FINGERPRINT_LOCK:
        try:
            package_root = Path(__file__).resolve().parents[2]
        except (IndexError, OSError, RuntimeError):
            package_root = Path.cwd()
        candidates = [
            Path(__file__),
            package_root / "logic" / "bridge",
            package_root / "logic" / "modal",
            package_root / "knowledge_graphs" / "neo4j_compat" / "legal_ir_projection.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "frame_bm25_selector.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "legal_modal_parser.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "modal_ir.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "modal_registry.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "spacy_modal_codec.py",
        ]
        signature, fingerprint = _code_fingerprint_from_candidates(package_root, candidates)
        if (
            _METRIC_CODE_FINGERPRINT_SIGNATURE == signature
            and _METRIC_CODE_FINGERPRINT_VALUE
        ):
            return _METRIC_CODE_FINGERPRINT_VALUE
        _METRIC_CODE_FINGERPRINT_SIGNATURE = signature
        _METRIC_CODE_FINGERPRINT_VALUE = fingerprint
        return _METRIC_CODE_FINGERPRINT_VALUE


def _compiler_ir_sample_code_fingerprint() -> str:
    global _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_SIGNATURE
    global _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE
    with _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_LOCK:
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
            package_root / "optimizers" / "logic_theorem_optimizer" / "modal_registry.py",
            package_root / "optimizers" / "logic_theorem_optimizer" / "spacy_modal_codec.py",
        ]
        signature, fingerprint = _code_fingerprint_from_candidates(package_root, candidates)
        if (
            _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_SIGNATURE == signature
            and _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE
        ):
            return _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE
        _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_SIGNATURE = signature
        _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE = fingerprint
        return _COMPILER_IR_SAMPLE_CODE_FINGERPRINT_VALUE


def _compiler_ir_metric_sample_disk_cache_key(payload: Mapping[str, Any]) -> str:
    wrapper = {
        "code_fingerprint": _compiler_ir_sample_code_fingerprint(),
        "kind": "compiler_ir_metric_sample",
        "payload": payload,
        "version": _COMPILER_IR_SAMPLE_CACHE_VERSION,
    }
    return hashlib.sha256(_stable_metric_json(wrapper).encode("utf-8")).hexdigest()


def _compiler_ir_metric_sample_timeout_disk_cache_key(payload: Mapping[str, Any]) -> str:
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
        return {
            str(key): _metric_cache_object_payload(item)
            for key, item in value.items()
        }
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
def codex_main_apply_lock(
    packet: Mapping[str, Any],
    *,
    timeout_seconds: Optional[float] = None,
    poll_seconds: float = 0.1,
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
    with lock_path.open("w", encoding="utf-8") as handle:
        deadline: Optional[float] = None
        if timeout_seconds is not None:
            deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out acquiring Codex main apply lock: {lock_path}"
                    ) from exc
                if deadline is None:
                    sleep_seconds = max(0.01, float(poll_seconds))
                else:
                    sleep_seconds = min(
                        max(0.01, float(poll_seconds)),
                        max(0.0, deadline - time.monotonic()),
                    )
                time.sleep(sleep_seconds)
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


def autoencoder_memory_gap_block(
    generalized: Any,
    sample_memory: Any,
    *,
    dataset: str,
    expected_holdout: bool = False,
) -> Dict[str, Any]:
    """Compare generalizable evaluation against sample-memory evaluation."""

    cosine_gain = float(
        getattr(sample_memory, "embedding_cosine_similarity", 0.0) or 0.0
    ) - float(getattr(generalized, "embedding_cosine_similarity", 0.0) or 0.0)
    reconstruction_gain = float(
        getattr(generalized, "reconstruction_loss", 0.0) or 0.0
    ) - float(getattr(sample_memory, "reconstruction_loss", 0.0) or 0.0)
    advantage = cosine_gain > 1e-9 or reconstruction_gain > 1e-9
    return {
        "cosine_gain_from_sample_memory": round(cosine_gain, 9),
        "dataset": str(dataset),
        "expected_holdout": bool(expected_holdout),
        "generalized_label": "sample_memory_disabled",
        "generalized_metrics": metric_block(generalized),
        "reconstruction_gain_from_sample_memory": round(reconstruction_gain, 9),
        "sample_memory_advantage_detected": bool(advantage),
        "sample_memory_label": "sample_memory_enabled",
        "sample_memory_metrics": metric_block(sample_memory),
        "unexpected_holdout_memory_advantage": bool(expected_holdout and advantage),
    }


def _file_telemetry(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {"exists": False, "path": None, "size_bytes": 0}
    target = Path(path)
    try:
        stat = target.stat()
    except OSError:
        return {"exists": False, "path": str(target), "size_bytes": 0}
    return {
        "exists": target.exists(),
        "path": str(target),
        "size_bytes": int(stat.st_size),
    }


def autoencoder_state_telemetry(
    state: ModalAutoencoderTrainingState,
    *,
    state_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return state telemetry plus low-rank shadow rollout diagnostics."""

    telemetry = state.telemetry()
    path = Path(state_path) if state_path is not None else None
    telemetry["state_file"] = _file_telemetry(path)
    rank = int(os.environ.get("IPFS_DATASETS_AUTOENCODER_LOW_RANK_RANK", "16") or 16)
    telemetry["low_rank_shadow"] = state.low_rank_shadow_report(rank=rank)
    raw_max_vectors = str(
        os.environ.get("IPFS_DATASETS_AUTOENCODER_LOW_RANK_SIDECAR_MAX_VECTORS") or ""
    ).strip()
    sidecar: Dict[str, Any] = {
        "enabled": bool(raw_max_vectors) and raw_max_vectors.lower() not in _FALSE_ENV_VALUES,
    }
    if not sidecar["enabled"] or path is None:
        telemetry["low_rank_sidecar"] = sidecar
        return telemetry
    try:
        max_vectors = max(0, int(raw_max_vectors))
        sidecar_path = ModalAutoencoderTrainingState.low_rank_shadow_sidecar_path(path)
        payload = state.save_low_rank_shadow_json(
            sidecar_path,
            rank=rank,
            max_vectors=max_vectors,
        )
        sidecar.update(
            {
                "complete": bool(payload.get("complete", False)),
                "file": _file_telemetry(sidecar_path),
                "path": str(sidecar_path),
                "status": "saved",
                "vector_entry_count": int(payload.get("vector_entry_count", 0) or 0),
            }
        )
    except (OSError, RuntimeError, ValueError) as exc:
        sidecar.update({"error": str(exc), "status": "failed"})
    telemetry["low_rank_sidecar"] = sidecar
    return telemetry


def autoencoder_canonical_state_hash(state: ModalAutoencoderTrainingState) -> str:
    """Return the canonical hash exported in disagreement packets."""

    return hashlib.sha256(state.to_json().encode("utf-8")).hexdigest()


def _compiler_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = (result.stdout or "").strip()
    return commit if result.returncode == 0 and commit else "unknown"


def introspection_disagreement_export_path(summary_path: Path) -> Path:
    return summary_path.with_name(
        f"{summary_path.stem}.canonical-disagreements.jsonl"
    )


def introspection_reference_example_export_path(summary_path: Path) -> Path:
    return summary_path.with_name(f"{summary_path.stem}.reference-examples.json")


def write_introspection_reference_examples(
    *,
    cycle: int,
    run_id: str,
    samples: Sequence[Any],
    state_hash: str,
    summary_path: Path,
    validation_indices: Sequence[int],
    validation_mode: str,
) -> Dict[str, Any]:
    """Write local-only source text used by the verifier, never the LLM prompt."""

    path = introspection_reference_example_export_path(summary_path)
    examples: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for position, sample in enumerate(samples):
        sample_id = str(getattr(sample, "sample_id", "") or "").strip()
        text = str(getattr(sample, "text", "") or "")
        if not sample_id or not text or sample_id in seen:
            continue
        seen.add(sample_id)
        examples.append(
            {
                "citation": str(getattr(sample, "citation", "") or ""),
                "example_id": sample_id,
                "sample_id": sample_id,
                "section": str(getattr(sample, "section", "") or ""),
                "source": str(getattr(sample, "source", "") or ""),
                "source_text": text,
                "text": text,
                "title": str(getattr(sample, "title", "") or ""),
                "validation_index": (
                    int(validation_indices[position])
                    if position < len(validation_indices)
                    else None
                ),
            }
        )
    payload = {
        "cycle": int(cycle),
        "example_count": len(examples),
        "examples": examples,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run_id),
        "schema_version": "legal-ir-leanstral-reference-examples-v1",
        "source_policy": "local_verifier_only_not_prompt_evidence",
        "state_hash": str(state_hash),
        "validation_mode": str(validation_mode or ""),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(path),
        "reference_example_count": len(examples),
        "schema_version": payload["schema_version"],
        "source_policy": payload["source_policy"],
    }


def _sample_metric_records_by_sample_id(block: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    records = block.get("sample_metric_records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return {}
    indexed: Dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        for key in ("sample_id", "metric_sample_id"):
            sample_id = str(record.get(key) or "")
            if sample_id and sample_id not in indexed:
                indexed[sample_id] = record
    return indexed


def _canary_set_hash(
    *,
    validation_mode: str,
    validation_indices: Sequence[int],
    validation_samples: Sequence[Any],
) -> str:
    payload = {
        "sample_ids": [
            str(getattr(sample, "sample_id", "") or "")
            for sample in validation_samples
        ],
        "validation_indices": [int(index) for index in validation_indices],
        "validation_mode": str(validation_mode or ""),
    }
    return hashlib.sha256(_stable_metric_json(payload).encode("utf-8")).hexdigest()


def _frozen_canary_identity(
    sample: Any,
    *,
    index: Optional[int],
    validation_mode: str,
    canary_set_hash: str,
) -> Dict[str, Any]:
    is_canary = str(validation_mode or "") == "fixed_canary"
    return {
        "canary_set_hash": canary_set_hash if is_canary else "",
        "enabled": is_canary,
        "index": int(index) if index is not None and is_canary else None,
        "sample_id": str(getattr(sample, "sample_id", "") or "") if is_canary else "",
    }


def export_canonical_state_disagreement_packets(
    *,
    autoencoder: AdaptiveModalAutoencoder,
    compiler_ir_validation: Mapping[str, Any],
    compiler_ir_guided_validation: Mapping[str, Any],
    cycle: int,
    export_mode: str,
    root: Path,
    run_id: str,
    samples: Sequence[Any],
    state: ModalAutoencoderTrainingState,
    summary_path: Path,
    validation_indices: Sequence[int],
    validation_mode: str,
    evaluate_provers: bool = False,
    top_k: int = 16,
) -> Dict[str, Any]:
    """Export real canonical autoencoder/compiler disagreements for one cycle."""

    if not introspection_export_mode_enabled(export_mode):
        path = introspection_disagreement_export_path(summary_path)
        return {
            "enabled": False,
            "elapsed_seconds": 0.0,
            "export_mode": str(export_mode or "off"),
            "packet_count": 0,
            "path": str(path),
            "paths": [],
            "schema_failure_count": 0,
            "schema_failures": [],
        }
    started_at = time.time()
    path = introspection_disagreement_export_path(summary_path)
    state_hash = autoencoder_canonical_state_hash(state)
    commit = _compiler_commit(root)
    canary_hash = _canary_set_hash(
        validation_mode=validation_mode,
        validation_indices=validation_indices,
        validation_samples=samples,
    )
    sample_indices = list(validation_indices)
    reference_export = write_introspection_reference_examples(
        cycle=cycle,
        run_id=run_id,
        samples=samples,
        state_hash=state_hash,
        summary_path=summary_path,
        validation_indices=sample_indices,
        validation_mode=validation_mode,
    )
    by_role = (
        ("unguided", compiler_ir_validation),
        ("guided", compiler_ir_guided_validation),
    )
    packets = []
    export_failures: List[Dict[str, Any]] = []
    sample_analysis_cache: Dict[int, tuple[Any, Any, Any]] = {}
    sample_analysis_cache_hits = 0
    for evaluation_role, compiler_block in by_role:
        if not compiler_block:
            continue
        metric_records = _sample_metric_records_by_sample_id(compiler_block)
        for sample_position, sample in enumerate(samples):
            sample_id = str(getattr(sample, "sample_id", "") or "")
            try:
                if sample_position in sample_analysis_cache:
                    introspection, guidance, prover_signal = sample_analysis_cache[
                        sample_position
                    ]
                    sample_analysis_cache_hits += 1
                else:
                    introspection = autoencoder.introspect_sample(
                        sample,
                        use_sample_memory=False,
                        top_k=top_k,
                        include_causal_attribution=False,
                    )
                    guidance = autoencoder.compiler_guidance_for_sample(
                        sample,
                        use_sample_memory=False,
                        top_k=top_k,
                        include_causal_attribution=False,
                        introspection=introspection,
                    )
                    prover_signal = (
                        evaluate_modal_prover_compilation(sample)
                        if evaluate_provers
                        else None
                    )
                    sample_analysis_cache[sample_position] = (
                        introspection,
                        guidance,
                        prover_signal,
                    )
                compiler_metrics = metric_records.get(sample_id) or {}
                packet = export_introspection_packet(
                    sample,
                    introspection,
                    compiler_guidance=guidance,
                    compiler_metrics=compiler_metrics,
                    config=IntrospectionPacketExportConfig(),
                    export_context={
                        "aggregate_compiler_metrics": dict(compiler_block),
                        "compiler_commit": commit,
                        "cycle": int(cycle),
                        "evaluation_role": evaluation_role,
                        "export_mode": str(export_mode or ""),
                        "frozen_canary": _frozen_canary_identity(
                            sample,
                            index=(
                                sample_indices[sample_position]
                                if sample_position < len(sample_indices)
                                else None
                            ),
                            validation_mode=validation_mode,
                            canary_set_hash=canary_hash,
                        ),
                        "run_id": run_id,
                        "sample_role": (
                            "frozen_canary"
                            if validation_mode == "fixed_canary"
                            else "validation_holdout"
                        ),
                        "state_hash": state_hash,
                    },
                    prover_signal=prover_signal,
                    state_version=MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
                    extra_versions={
                        "daemon_metric_schema_version": AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION,
                    },
                )
                packets.append(packet)
            except Exception as exc:
                export_failures.append(
                    {
                        "evaluation_role": evaluation_role,
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                        "sample_id": sample_id,
                    }
                )
    append_report = append_disagreement_packets_jsonl(path, packets)
    elapsed = round(time.time() - started_at, 6)
    return {
        **append_report,
        "enabled": True,
        "elapsed_seconds": elapsed,
        "export_failure_count": len(export_failures),
        "export_failures": export_failures[:16],
        "export_mode": str(export_mode or ""),
        "paths": [str(path)] if append_report.get("packet_count", 0) else [],
        "reference_example_count": int(
            reference_export.get("reference_example_count", 0) or 0
        ),
        "reference_example_path": str(reference_export.get("path") or ""),
        "reference_example_source_policy": str(
            reference_export.get("source_policy") or ""
        ),
        "requested_packet_count": len(packets),
        "shared_sample_analysis_count": len(sample_analysis_cache),
        "shared_sample_analysis_cache_hit_count": sample_analysis_cache_hits,
        "state_hash": state_hash,
    }


def autoencoder_low_rank_load_report(
    state: ModalAutoencoderTrainingState,
    *,
    state_path: Path,
) -> Dict[str, Any]:
    """Optionally hydrate dense state from a low-rank shadow sidecar."""

    enabled = str(
        os.environ.get("IPFS_DATASETS_AUTOENCODER_LOW_RANK_LOAD") or ""
    ).strip().lower() in _TRUE_ENV_VALUES
    sidecar_path = ModalAutoencoderTrainingState.low_rank_shadow_sidecar_path(state_path)
    if not enabled:
        return {
            "dense_state_hydrated": False,
            "enabled": False,
            "path": str(sidecar_path),
            "status": "disabled",
        }
    report = state.hydrate_low_rank_shadow_json(sidecar_path, overwrite=False)
    report["enabled"] = True
    return report


def _legal_ir_family_from_view(view: str) -> str:
    normalized = str(view or "").strip().lower().replace("-", "_").replace("/", ".")
    if normalized.startswith("deontic") or "norm" in normalized:
        return "deontic"
    if "frame_logic" in normalized or "flogic" in normalized:
        return "frame_logic"
    if normalized.startswith("tdfol") or normalized.startswith("fol.") or "tdfol" in normalized:
        return "tdfol"
    if normalized.startswith(("kg", "knowledge_graph")) or "neo4j" in normalized:
        return "kg"
    if normalized.startswith(("cec", "dcec")) or "event_calculus" in normalized:
        return "cec"
    if "prover" in normalized or "router" in normalized:
        return "prover"
    if normalized.startswith("zkp") or "zero_knowledge" in normalized:
        return "zkp"
    return "other"


def _family_distribution(distribution: Mapping[str, Any]) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for view, value in dict(distribution or {}).items():
        weight = max(0.0, _float_or_zero(value))
        if weight <= 0.0:
            continue
        family = _legal_ir_family_from_view(str(view))
        totals[family] = totals.get(family, 0.0) + weight
    total = sum(totals.values())
    if total <= 0.0:
        return {}
    return {family: round(value / total, 9) for family, value in sorted(totals.items())}


def learned_ir_metric_block(evaluation: Any) -> Dict[str, Any]:
    """Return the learned LegalIR-view alignment metrics as a stable block."""

    losses = dict(getattr(evaluation, "legal_ir_losses", {}) or {})
    target_distribution = dict(getattr(evaluation, "legal_ir_view_distribution", {}) or {})
    predicted_distribution = dict(
        getattr(evaluation, "legal_ir_predicted_view_distribution", {}) or {}
    )
    family_excess = {
        name.removeprefix("legal_ir_view_family_").removesuffix(
            "_cross_entropy_excess_loss"
        ): float(value)
        for name, value in losses.items()
        if name.startswith("legal_ir_view_family_")
        and name.endswith("_cross_entropy_excess_loss")
        and name != "legal_ir_view_family_cross_entropy_excess_loss"
    }
    family_cosine_gaps = {
        name.removeprefix("legal_ir_view_family_").removesuffix("_cosine_gap_loss"): float(
            value
        )
        for name, value in losses.items()
        if name.startswith("legal_ir_view_family_")
        and name.endswith("_cosine_gap_loss")
        and name != "legal_ir_view_family_cosine_gap_loss"
    }
    worst_family = max(family_excess, key=family_excess.get) if family_excess else ""
    worst_cosine_family = (
        max(family_cosine_gaps, key=family_cosine_gaps.get) if family_cosine_gaps else ""
    )
    view_cosine = max(
        0.0,
        1.0 - float(losses.get("legal_ir_view_family_cosine_gap_loss", 0.0) or 0.0),
    )
    return {
        "family_cross_entropy_excess_by_family": {
            name: round(value, 9) for name, value in sorted(family_excess.items())
        },
        "family_cross_entropy_excess_loss": round(
            float(losses.get("legal_ir_view_family_cross_entropy_excess_loss", 0.0) or 0.0),
            9,
        ),
        "predicted_family_distribution": _family_distribution(predicted_distribution),
        "predicted_view_distribution": {
            name: round(float(value), 9)
            for name, value in sorted(predicted_distribution.items())
        },
        "target_count": int(getattr(evaluation, "legal_ir_target_count", 0) or 0),
        "target_family_distribution": _family_distribution(target_distribution),
        "target_view_distribution": {
            name: round(float(value), 9) for name, value in sorted(target_distribution.items())
        },
        "view_cosine_similarity": round(view_cosine, 9),
        "view_cross_entropy_loss": round(
            float(losses.get("legal_ir_view_cross_entropy_loss", 0.0) or 0.0),
            9,
        ),
        "worst_family_cosine_gap_loss": round(
            float(family_cosine_gaps.get(worst_cosine_family, 0.0) or 0.0),
            9,
        ),
        "worst_family_cosine_gap_name": worst_cosine_family,
        "worst_family_cross_entropy_excess_loss": round(
            float(family_excess.get(worst_family, 0.0) or 0.0),
            9,
        ),
        "worst_family_cross_entropy_excess_name": worst_family,
    }


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
    if isinstance(cached_slot_texts, Mapping) and cached_slot_texts:
        return {
            str(slot): _metadata_sequence_strings(values)
            for slot, values in sorted(cached_slot_texts.items())
            if str(slot)
        }
    decoded = getattr(result, "decoded_modal_text", None)
    slot_texts: Dict[str, List[str]] = {}
    if hasattr(decoded, "phrases"):
        slot_texts.update(decoded_modal_phrase_slot_text_map(decoded))
    metadata = dict(getattr(result, "metadata", {}) or {})
    cached_metadata_slot_texts = metadata.get("_compiler_guidance_slot_texts")
    if isinstance(cached_metadata_slot_texts, Mapping) and cached_metadata_slot_texts:
        return {
            str(slot): _metadata_sequence_strings(values)
            for slot, values in sorted(cached_metadata_slot_texts.items())
            if str(slot)
        }

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
    elif _float_or_zero(metadata.get("compiler_guidance_feature_count")) > 0.0:
        add("compiler_guidance_feature_group", "decompiler_surface_template")
        for term in _metadata_sequence_strings(
            metadata.get("compiler_guidance_semantic_overlay_terms")
        ):
            safe_term = _guidance_slot_safe_key(term)
            if safe_term:
                add(
                    "compiler_guidance_decompiler_surface_template_feature",
                    f"semantic-overlay:{safe_term}",
                )

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
    else:
        gap_distribution = metadata.get("compiler_guidance_legal_ir_view_gap_distribution")
        if isinstance(gap_distribution, Mapping):
            for view, raw_value in sorted(gap_distribution.items()):
                safe_view = _guidance_slot_safe_key(view)
                if not safe_view:
                    continue
                value = _float_or_zero(raw_value)
                if value > 0.0:
                    add("compiler_guidance_legal_ir_view_gap", safe_view)
                    add(
                        "compiler_guidance_legal_ir_view_gap_direction",
                        f"{safe_view}:underrepresented",
                    )
                elif value < 0.0:
                    add("compiler_guidance_legal_ir_view_gap", safe_view)
                    add(
                        "compiler_guidance_legal_ir_view_gap_direction",
                        f"{safe_view}:overrepresented",
                    )

    for route in _metadata_sequence_strings(metadata.get("compiler_guidance_todo_routes")):
        add("compiler_guidance_todo_route", route)
    return slot_texts


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
    original_text = str(getattr(sample, "text", "") or "")
    if str(metric_text) == original_text:
        return sample
    sample_id = str(getattr(sample, "sample_id", "") or "sample")
    digest = hashlib.sha256(str(metric_text).encode("utf-8")).hexdigest()[:12]
    dimensions = len(list(getattr(sample, "embedding_vector", []) or [])) or 8
    embedding_model = str(getattr(sample, "embedding_model", "") or "")
    payload = {
        "embedding_model": (
            f"metric-prefix:{embedding_model}" if embedding_model else "metric-prefix:mock"
        ),
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
    selected = [part for part in clauses if cue_re.search(part)] or clauses[:2]
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
        "metric_text_length": int(metric_text_length),
        "modal_decompiler_structural_text": structural_text,
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


def _compiler_guidance_legal_ir_gap_family(gap_name: str) -> str:
    view = str(gap_name or "").split(":", 1)[0]
    normalized = _guidance_slot_safe_key(view)
    if "deontic" in normalized:
        return "deontic"
    if "frame" in normalized or "flogic" in normalized:
        return "frame_logic"
    if "tdfol" in normalized or "first_order" in normalized:
        return "tdfol"
    if "knowledge_graph" in normalized or normalized in {"kg", "neo4j"} or "_kg" in normalized:
        return "knowledge_graph"
    if "cec" in normalized or "event_calculus" in normalized or "dcec" in normalized:
        return "cec"
    if "prover" in normalized:
        return "prover"
    if "zkp" in normalized or "zero_knowledge" in normalized:
        return "zkp"
    return normalized or "unknown"


def _compiler_guidance_legal_ir_family_gap(gap_name: str) -> str:
    direction = "gap"
    if ":" in str(gap_name):
        direction = str(gap_name).rsplit(":", 1)[-1] or "gap"
    return f"{_compiler_guidance_legal_ir_gap_family(gap_name)}:{direction}"


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
            "metric_profile_version": COMPILER_IR_METRIC_PROFILE_VERSION,
            "metric_failures": 0,
            "sample_count": 0,
        }

    started_at = time.time()
    max_sample_text_chars = max(0, int(max_sample_text_chars or 0))
    metric_text_policy = _normalise_compiler_ir_metric_text_policy(metric_text_policy)
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
                    include_causal_attribution=False,
                )
                if compiler_guidance:
                    guidance_produced_count += 1
                else:
                    guidance_empty_count += 1
            except Exception as exc:
                guidance_failures += 1
                guidance_error = f"{type(exc).__name__}: {str(exc)[:240]}"
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
            cached["metric_profile_version"] = COMPILER_IR_METRIC_PROFILE_VERSION
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
            cached = _add_compiler_ir_metric_aliases(cached)
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
        "source_copy_loss": [],
        "source_copy_reward_hack_penalty": [],
        "source_decompiled_text_embedding_cosine_loss": [],
        "source_decompiled_text_embedding_cosine_similarity": [],
        "source_decompiled_text_token_loss": [],
        "source_decompiled_text_token_similarity": [],
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
    skipped_sample_count = 0
    text_length_skipped_count = 0
    text_length_truncated_count = 0
    timeout_fallback_count = 0
    persistent_sample_cache_hits = 0
    persistent_sample_cache_misses = 0
    persistent_sample_timeout_cache_hits = 0
    guidance_frame_boost_counts: List[float] = []
    guidance_frame_changed_count = 0
    guidance_feature_groups: Counter[str] = Counter()
    guidance_legal_ir_view_gaps: Counter[str] = Counter()
    guidance_legal_ir_view_family_gaps: Counter[str] = Counter()
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
        emit_progress(
            "sample_start",
            citation=citation,
            sample_id=sample_id,
            sample_index=sample_index,
            text_length=sample_text_length,
        )

        metric_text = sample_text
        metric_text_truncated = False
        if max_sample_text_chars > 0 and sample_text_length > max_sample_text_chars:
            if metric_text_policy == "skip":
                skipped_sample_count += 1
                text_length_skipped_count += 1
                sample_record = {
                    "citation": citation,
                    "max_sample_text_chars": max_sample_text_chars,
                    "metric_text_policy": metric_text_policy,
                    "sample_id": sample_id,
                    "skip_reason": "text_length_limit",
                    "source_text_preview": re.sub(r"\s+", " ", sample_text).strip()[:240],
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
            metric_text_truncated = len(metric_text) < sample_text_length
            if metric_text_truncated:
                text_length_truncated_count += 1
                emit_progress(
                    "sample_text_truncated",
                    citation=citation,
                    metric_text_length=len(metric_text),
                    sample_id=sample_id,
                    sample_index=sample_index,
                    text_length=sample_text_length,
                )

        metric_sample = _compiler_ir_metric_sample_for_text(
            sample,
            metric_text=metric_text,
        )
        metric_sample_id = str(getattr(metric_sample, "sample_id", "") or sample_id)
        metric_text_length = len(str(getattr(metric_sample, "text", "") or ""))

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
                    include_causal_attribution=False,
                )
                if compiler_guidance:
                    guidance_produced_count += 1
                else:
                    guidance_empty_count += 1
            except Exception:
                guidance_failures += 1

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

        result_from_timeout_cache = False
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
                persistent_sample_timeout_cache_hits=persistent_sample_timeout_cache_hits,
                sample_id=sample_id,
                sample_index=sample_index,
                sample_timeout_seconds=sample_timeout_seconds,
                timeout_cache_kind=timeout_cache_kind,
            )
        else:
            result = _compiler_ir_metric_result_from_cache_payload(cached_result_payload)

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
                    try:
                        result = codec.encode(
                            metric_sample.text,
                            document_id=metric_sample.sample_id,
                            citation=metric_sample.citation,
                            source=metric_sample.source,
                            source_embedding=metric_sample.embedding_vector,
                            compiler_guidance=compiler_guidance,
                        )
                    except TypeError:
                        result = codec.encode(
                            metric_sample.text,
                            document_id=metric_sample.sample_id,
                            citation=metric_sample.citation,
                            source=metric_sample.source,
                            source_embedding=metric_sample.embedding_vector,
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
                    "source_text_preview": re.sub(r"\s+", " ", metric_text).strip()[:240],
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
        formula_counts.append(float(len(getattr(result.modal_ir, "formulas", ()) or ())))
        frame_candidate_counts.append(float(len(getattr(result, "frame_candidates", ()) or ())))
        metadata = dict(getattr(result, "metadata", {}) or {})
        llm_call_counts.append(float(metadata.get("llm_call_count", 0.0)))

        sample_record: Dict[str, Any] = {
            "citation": citation,
            "compiler_guidance_applied": bool(metadata.get("compiler_guidance_applied")),
            "compiler_guidance_legal_ir_view_family_gaps": [],
            "compiler_guidance_legal_ir_view_gaps": [],
            "compiler_guidance_semantic_overlay_terms": [],
            "compiler_guidance_todo_routes": [],
            "metric_sample_id": metric_sample_id,
            "metric_text_length": metric_text_length,
            "metric_text_policy": metric_text_policy,
            "metric_text_truncated": metric_text_truncated,
            "metrics": {
                name: round(float(result.losses[name]), 9)
                for name in COMPILER_GUIDANCE_CANARY_METRICS
                if name in result.losses and result.losses.get(name) is not None
            },
            "original_text_length": sample_text_length,
            "sample_id": sample_id,
            "source_text_preview": re.sub(r"\s+", " ", metric_text).strip()[:240],
            "text_length": metric_text_length,
        }
        if metadata.get("compiler_ir_metric_timeout_fallback"):
            sample_record["compiler_ir_metric_timeout_fallback"] = True
            sample_record["compiler_ir_metric_timeout_fallback_kind"] = str(
                metadata.get("compiler_ir_metric_timeout_fallback_kind") or ""
            )
            sample_record["sample_timeout_seconds"] = float(
                metadata.get("sample_timeout_seconds", sample_timeout_seconds) or 0.0
            )
            sample_record["skip_reason"] = "sample_timeout"
            family_distribution = metadata.get(
                "compiler_ir_metric_timeout_family_distribution"
            )
            if isinstance(family_distribution, Mapping):
                sample_record["compiler_ir_metric_timeout_family_distribution"] = {
                    str(key): float(value)
                    for key, value in family_distribution.items()
                    if isinstance(value, (int, float))
                }
        structural_preview = str(metadata.get("modal_decompiler_structural_text") or "")
        if structural_preview:
            sample_record["decompiled_text_preview"] = re.sub(
                r"\s+",
                " ",
                structural_preview,
            ).strip()[:240]

        if metadata.get("compiler_guidance_applied"):
            guidance_applied_count += 1
            guidance_frame_boost_counts.append(
                float(metadata.get("compiler_guidance_frame_boost_count", 0.0))
            )
            guidance_semantic_overlay_counts.append(
                float(metadata.get("compiler_guidance_semantic_overlay_count", 0.0))
            )
            overlay_terms = metadata.get("compiler_guidance_semantic_overlay_terms")
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
                metadata.get("compiler_guidance_selected_frame_before")
                != metadata.get("compiler_guidance_selected_frame_after")
            ):
                guidance_frame_changed_count += 1
            slot_texts = compiler_guidance_slot_texts_from_result(result)
            for value in slot_texts.get("compiler_guidance_feature_group", []):
                guidance_feature_groups[str(value)] += 1
            sample_view_gaps = list(
                dict.fromkeys(
                    str(value)
                    for value in slot_texts.get(
                        "compiler_guidance_legal_ir_view_gap_direction",
                        [],
                    )
                    if str(value)
                )
            )
            sample_record["compiler_guidance_legal_ir_view_gaps"] = list(
                dict.fromkeys(sample_view_gaps)
            )
            sample_family_gaps = [
                _compiler_guidance_legal_ir_family_gap(value)
                for value in sample_view_gaps
            ]
            sample_record["compiler_guidance_legal_ir_view_family_gaps"] = list(
                dict.fromkeys(sample_family_gaps)
            )
            for value in sample_view_gaps:
                guidance_legal_ir_view_gaps[value] += 1
            for value in sample_family_gaps:
                guidance_legal_ir_view_family_gaps[value] += 1
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
                examples.append(
                    {
                        "citation": citation,
                        "sample_id": sample_id,
                        "selected_frame_after": str(
                            metadata.get("compiler_guidance_selected_frame_after", "")
                            or ""
                        ),
                        "selected_frame_before": str(
                            metadata.get("compiler_guidance_selected_frame_before", "")
                            or ""
                        ),
                        "text_preview": re.sub(r"\s+", " ", metric_text).strip()[:240],
                    }
                )
        if len(sample_metric_records) < max(0, int(max_sample_metric_records)):
            sample_metric_records.append(sample_record)
        emit_progress(
            "sample_done",
            citation=citation,
            evaluated_count=len(formula_counts),
            failures=failures,
            formula_count=int(formula_counts[-1]) if formula_counts else 0,
            frame_candidate_count=int(frame_candidate_counts[-1]) if frame_candidate_counts else 0,
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
        "metric_profile_version": COMPILER_IR_METRIC_PROFILE_VERSION,
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
    if use_autoencoder_guidance or guidance_legal_ir_view_family_gaps:
        block["compiler_guidance_legal_ir_view_family_gaps"] = dict(
            guidance_legal_ir_view_family_gaps.most_common(12)
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
    hammer_metrics = hammer_guidance_metric_block(precomputed_guidance)
    if int(hammer_metrics.get("hammer_artifact_count", 0) or 0) > 0:
        block["hammer_guidance_metric_schema_version"] = (
            HAMMER_GUIDANCE_METRIC_SCHEMA_VERSION
        )
        block["hammer_guidance_metrics"] = hammer_metrics
        for name, value in hammer_metrics.items():
            if isinstance(value, (int, float)):
                block[name] = round(float(value), 9)
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
    block = _add_compiler_ir_metric_aliases(block)
    if persistent_cache_key is not None and sample_timeouts <= 0:
        block["persistent_cache_enabled"] = _metric_disk_cache_enabled()
        block["persistent_cache_hit"] = False
        block["persistent_cache_key"] = persistent_cache_key
        block["persistent_cache_kind"] = "compiler_ir_metric_block"
        _write_metric_disk_cache("compiler_ir_metric_block", persistent_cache_key, block)
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
    """Return samples with the worst source text to structural decompiled text gaps."""

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
        copy_hack = _metric_value(
            metrics,
            "source_copy_reward_hack_penalty",
            default=0.0,
        )
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
        "guidance_cache_records": _metric_cache_object_payload(
            list(guidance_cache_records)
        ),
        "guidance_diagnostics_version": _COMPILER_IR_GUIDANCE_DIAGNOSTICS_VERSION,
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
        losses={str(name): _float_or_zero(value) for name, value in losses.items()},
        compiler_guidance_slot_texts=guidance_slot_texts,
        metadata=dict(metadata),
        modal_ir=SimpleNamespace(formulas=[None] * formula_count),
    )


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
    max_sample_text_chars: int = 0,
) -> Dict[str, Any]:
    """Aggregate bridge-level compiler/prover/KG diagnostics by adapter."""

    sample_list = autoencoder_metric_bridge_samples_for_evaluation(
        list(samples),
        max_sample_text_chars=max_sample_text_chars,
    )
    adapter_names = [
        name
        for name in dict.fromkeys(str(name).strip() for name in bridge_names)
        if name and name.lower() not in {"none", "off", "false"}
    ]
    started_at = time.time()

    def emit_progress(stage: str, **payload: Any) -> None:
        if progress_callback is None:
            return
        event = {
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

    block_payload = {
        "bridge_names": adapter_names,
        "evaluate_provers": evaluate_provers,
        "samples": [_sample_metric_cache_payload(sample) for sample in sample_list],
    }
    persistent_cache_key = _metric_disk_cache_key(
        "bridge_ir_metric_block",
        block_payload,
    )
    cached_block = _read_metric_disk_cache("bridge_ir_metric_block", persistent_cache_key)
    if cached_block is not None:
        cached = dict(cached_block)
        cached["persistent_cache_enabled"] = True
        cached["persistent_cache_hit"] = True
        cached["persistent_cache_key"] = persistent_cache_key
        cached["persistent_cache_kind"] = "bridge_ir_metric_block"
        emit_progress("persistent_cache_hit", cache_key=persistent_cache_key)
        return cached

    block: Dict[str, Any] = {
        "adapter_count": len(adapter_names),
        "adapters": {},
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_size": 0,
        "evaluation_seconds_max": 0.0,
        "evaluated_count": 0,
        "metric_failures": 0,
        "persistent_cache_enabled": _metric_disk_cache_enabled(),
        "persistent_cache_hit": False,
        "persistent_cache_key": persistent_cache_key,
        "persistent_cache_kind": "bridge_ir_metric_block",
        "persistent_sample_cache_hits": 0,
        "max_sample_text_chars": max(0, int(max_sample_text_chars or 0)),
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
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
        _legal_ir_target_cache_key,
        _read_legal_ir_target_disk_cache,
        _write_legal_ir_target_disk_cache,
    )

    class _CachedBridgeMultiviewReport:
        def __init__(self, target: Any) -> None:
            self._target = target
            self.acceptance_rate = 1.0 if bool(getattr(target, "accepted", False)) else 0.0
            losses = dict(getattr(target, "losses", {}) or {})
            self.graph_failure_penalty = float(
                losses.get("legal_ir_multiview_graph_failure_penalty", 0.0) or 0.0
            )
            self.proof_failure_ratio = float(
                losses.get("legal_ir_multiview_proof_failure_ratio", 0.0) or 0.0
            )
            self.reports = {}
            self.failures = {}
            self.total_loss = float(
                losses.get(
                    "legal_ir_multiview_total_loss",
                    getattr(target, "total_loss", 0.0),
                )
                or 0.0
            )
            self.view_count = max(
                0,
                len(dict(getattr(target, "view_distribution", {}) or {})),
            )
            self.document = getattr(
                target,
                "document",
                SimpleNamespace(canonical_hash=lambda: "cached-legal-ir-target"),
            )

        def training_target(self) -> Any:
            return self._target

        def view_coverage_loss(self) -> float:
            losses = dict(getattr(self._target, "losses", {}) or {})
            return float(losses.get("legal_ir_multiview_view_coverage_loss", 0.0) or 0.0)

    def evaluate_sample(sample: Any) -> Any:
        sample_started = time.time()
        cache_key = _bridge_ir_report_cache_key(
            sample,
            bridge_names=adapter_names,
            evaluate_provers=evaluate_provers,
        )
        with _BRIDGE_IR_REPORT_CACHE_LOCK:
            cached = _BRIDGE_IR_REPORT_CACHE.get(cache_key)
        if cached is not None:
            return cached, "memory", time.time() - sample_started
        target_cache_key = _legal_ir_target_cache_key(
            sample,
            bridge_names=adapter_names,
            evaluate_provers=evaluate_provers,
        )
        cached_target = _read_legal_ir_target_disk_cache(target_cache_key)
        if cached_target is not None:
            report = _CachedBridgeMultiviewReport(cached_target)
            with _BRIDGE_IR_REPORT_CACHE_LOCK:
                if len(_BRIDGE_IR_REPORT_CACHE) >= BRIDGE_IR_REPORT_CACHE_MAX:
                    _BRIDGE_IR_REPORT_CACHE.pop(next(iter(_BRIDGE_IR_REPORT_CACHE)), None)
                _BRIDGE_IR_REPORT_CACHE[cache_key] = report
            return report, "persistent_target", time.time() - sample_started
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
        try:
            target = report.training_target()
            if getattr(target, "document", None) is None:
                target = SimpleNamespace(
                    accepted=bool(getattr(report, "acceptance_rate", 0.0)),
                    adapter_losses={},
                    bridge_names=tuple(adapter_names),
                    document=getattr(report, "document", None),
                    losses=dict(getattr(target, "losses", {}) or {}),
                    view_distribution=dict(
                        getattr(target, "view_distribution", {}) or {}
                    ),
                )
            _write_legal_ir_target_disk_cache(target_cache_key, target)
        except Exception:
            pass
        return report, "miss", time.time() - sample_started

    worker_count = _parallel_worker_count(
        requested=parallel_workers,
        item_count=len(sample_list),
    )
    block["worker_count"] = worker_count
    emit_progress("start", adapter_count=len(adapter_names), worker_count=worker_count)
    if worker_count <= 1:
        sample_results = []
        for sample_index, sample in enumerate(sample_list, start=1):
            emit_progress(
                "sample_start",
                sample_id=str(getattr(sample, "sample_id", "") or ""),
                sample_index=sample_index,
            )
            result = evaluate_sample(sample)
            emit_progress(
                "sample_done" if result[1] == "miss" else "sample_cache_hit",
                cache_source=result[1],
                sample_id=str(getattr(sample, "sample_id", "") or ""),
                sample_index=sample_index,
            )
            sample_results.append(result)
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="bridge-ir-metrics",
        ) as executor:
            sample_results = list(executor.map(evaluate_sample, sample_list))

    multiview_reports = [result[0] for result in sample_results]
    cache_sources = [str(result[1]) for result in sample_results]
    evaluation_seconds = [float(result[2]) for result in sample_results]
    block["cache_hits"] = sum(1 for source in cache_sources if source == "memory")
    block["cache_misses"] = sum(1 for source in cache_sources if source == "miss")
    block["persistent_sample_cache_hits"] = sum(
        1 for source in cache_sources if source == "persistent_target"
    )
    block["evaluation_seconds_max"] = round(max(evaluation_seconds or [0.0]), 9)
    with _BRIDGE_IR_REPORT_CACHE_LOCK:
        block["cache_size"] = len(_BRIDGE_IR_REPORT_CACHE)

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
    if "zkp_attestation" in adapter_names:
        block["zkp_attestation_cache"] = {
            "mode": (
                "persistent_metric_certificate"
                if _metric_disk_cache_enabled()
                else "memory_metric_certificate"
            )
        }
    block["legal_ir_target_cache_exports"] = (
        block["cache_misses"] + block["persistent_sample_cache_hits"]
    )
    if block["persistent_cache_enabled"]:
        _write_metric_disk_cache("bridge_ir_metric_block", persistent_cache_key, block)
    emit_progress("done", evaluated_count=block["evaluated_count"])
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


def leanstral_rule_gap_report_path(args: argparse.Namespace, *, root: Path) -> Path:
    """Return the production rule-gap report path for this daemon run."""
    explicit = str(getattr(args, "leanstral_rule_gap_report_path", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return (
        root
        / "workspace"
        / "leanstral-audit-worker"
        / f"{getattr(args, 'run_id', 'default')}.rule-gaps.json"
    )


def leanstral_direct_guidance_paths(
    args: argparse.Namespace,
    *,
    root: Path,
    artifact_paths: Optional[Sequence[str | Path]] = None,
) -> List[Path]:
    """Return direct Leanstral guidance artifact paths to scan this cycle."""

    values: List[str | Path] = []
    explicit = getattr(args, "leanstral_direct_guidance_path", "")
    if not explicit:
        explicit = getattr(args, "leanstral_guidance_path", "")
    values.extend(_split_path_values(explicit))
    values.extend(path for path in (artifact_paths or []) if str(path).strip())
    paths: List[Path] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def load_leanstral_direct_guidance_artifacts(
    paths: Sequence[str | Path],
    *,
    max_files: int = 512,
    max_items: int = 512,
) -> Dict[str, Any]:
    """Load trusted-guidance candidates from JSON/JSONL autoencoder artifacts."""

    files = _expand_leanstral_guidance_files(paths, max_files=max_files)
    result: Dict[str, Any] = {
        "artifact_count": len(files),
        "guidance_count": 0,
        "guidance_ids": [],
        "guidance_items": [],
        "invalid_artifact_count": 0,
        "invalid_artifacts": [],
        "paths": [str(path) for path in files],
    }
    seen: set[str] = set()
    for path in files:
        try:
            payloads = _read_leanstral_guidance_payloads(path, max_payloads=max_items)
        except (OSError, json.JSONDecodeError) as exc:
            result["invalid_artifact_count"] = int(result["invalid_artifact_count"]) + 1
            result["invalid_artifacts"].append(
                {
                    "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                    "path": str(path),
                }
            )
            continue
        for payload in payloads:
            for guidance in _leanstral_guidance_items_from_payload(payload):
                guidance_id = str(
                    guidance.get("guidance_id")
                    or guidance.get("task_id")
                    or guidance.get("modal_ir_hash")
                    or ""
                ).strip()
                dedupe_key = guidance_id or hashlib.sha256(
                    json.dumps(
                        guidance,
                        ensure_ascii=True,
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                result["guidance_items"].append(guidance)
                if guidance_id:
                    result["guidance_ids"].append(guidance_id)
                if len(result["guidance_items"]) >= max(0, int(max_items)):
                    break
            if len(result["guidance_items"]) >= max(0, int(max_items)):
                break
        if len(result["guidance_items"]) >= max(0, int(max_items)):
            break
    result["guidance_count"] = len(result["guidance_items"])
    result["guidance_ids"] = list(dict.fromkeys(result["guidance_ids"]))[:64]
    result["invalid_artifacts"] = result["invalid_artifacts"][:16]
    return result


def project_verified_leanstral_guidance_artifacts_into_queue(
    *,
    args: argparse.Namespace,
    queue_path: Path,
    root: Path,
    supervisor: ModalTodoSupervisor,
    artifact_paths: Optional[Sequence[str | Path]] = None,
    autoencoder: Optional[AdaptiveModalAutoencoder] = None,
    samples_by_id: Optional[Mapping[str, Any]] = None,
    worker_health: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Load direct Leanstral draft-guidance artifacts and seed Codex TODOs."""

    paths = leanstral_direct_guidance_paths(
        args,
        root=root,
        artifact_paths=artifact_paths,
    )
    result: Dict[str, Any] = {
        "artifact_count": 0,
        "enabled": bool(
            getattr(args, "leanstral_direct_guidance_projection_enabled", True)
        ),
        "guidance_count": 0,
        "guidance_ids": [],
        "invalid_artifact_count": 0,
        "path_count": len(paths),
        "paths": [str(path) for path in paths],
        "projection_source": "direct_guidance",
        "report_loaded": False,
        "seeded_count": 0,
        "deduped_count": 0,
        "stale_count": 0,
        "budget_blocked_count": 0,
        "report_only_count": 0,
        "seeded_todo_ids": [],
        "autoencoder_training": {
            "enabled": bool(
                getattr(args, "leanstral_direct_guidance_train_autoencoder", True)
            ),
            "status": "not_run",
        },
    }
    if not result["enabled"]:
        result["status"] = "disabled"
        return result
    if not paths:
        result["status"] = "no_paths"
        return result
    load_report = load_leanstral_direct_guidance_artifacts(paths)
    result.update(
        {
            "artifact_count": int(load_report.get("artifact_count", 0) or 0),
            "guidance_count": int(load_report.get("guidance_count", 0) or 0),
            "guidance_ids": list(load_report.get("guidance_ids", []) or []),
            "invalid_artifact_count": int(
                load_report.get("invalid_artifact_count", 0) or 0
            ),
            "invalid_artifacts": list(load_report.get("invalid_artifacts", []) or []),
            "loaded_paths": list(load_report.get("paths", []) or []),
        }
    )
    if not result["artifact_count"]:
        result["status"] = "missing_artifacts"
        return result
    guidance_items = [
        dict(item)
        for item in load_report.get("guidance_items", [])
        if isinstance(item, Mapping)
    ]
    if not guidance_items:
        result["status"] = "no_guidance"
        result["report_loaded"] = True
        return result

    result["report_loaded"] = True
    config = LeanstralTodoProjectionConfig(
        max_audits_per_cycle=max(
            0,
            int(getattr(args, "autoencoder_max_audits_per_cycle", 0) or 0),
        ),
        max_todos_per_cycle=max(
            0,
            int(getattr(args, "autoencoder_max_todos_per_cycle", 0) or 0),
        ),
        max_todos_per_scope=max(
            1,
            int(
                getattr(
                    args,
                    "leanstral_direct_guidance_max_todos_per_scope",
                    getattr(args, "leanstral_rule_gap_max_todos_per_scope", 2),
                )
                or 2
            ),
        ),
        max_program_synthesis_pending=max(
            0,
            int(getattr(args, "max_program_synthesis_pending", 512) or 512),
        ),
        require_verified_support=True,
        require_executor_available=bool(
            getattr(
                args,
                "leanstral_direct_guidance_require_executor_available",
                getattr(args, "leanstral_rule_gap_require_executor_available", True),
            )
        ),
        target_scope_filters=autoencoder_target_scope_filters(args),
        worker_health=dict(worker_health or {}),
    )
    with queue_file_lock(queue_path):
        latest_queue = ModalTodoQueue.load_jsonl(queue_path)
        latest_queue.merge_from(
            supervisor.queue,
            preserve_claimed_role=supervisor.policy.program_synthesis_role,
        )
        supervisor.queue = latest_queue
        backfill_report = supervisor.backfill_leanstral_patch_feedback_evidence()
        projection = supervisor.seed_program_synthesis_from_leanstral_guidance(
            guidance_items,
            config=config,
        )
        hammer_failure_todos: List[ModalTodo] = []
        hammer_failure_projection: Dict[str, Any] = {
            "deduped_count": 0,
            "enabled": True,
            "generated_count": 0,
            "min_support": 2,
            "seeded_count": 0,
            "seeded_todo_ids": [],
            "status": "not_run",
        }
        if projection.seed_block_reasons:
            hammer_failure_projection["seed_block_reasons"] = list(
                projection.seed_block_reasons
            )
            hammer_failure_projection["status"] = "seed_gate_blocked"
        else:
            hammer_failure_todos = hammer_failure_projection_todos(
                guidance_items,
                policy=supervisor.policy,
                min_support=2,
                max_todos_per_cycle=max(
                    0,
                    int(getattr(args, "autoencoder_max_todos_per_cycle", 0) or 0),
                )
                or 5,
                max_todos_per_scope=max(
                    1,
                    int(
                        getattr(
                            args,
                            "leanstral_direct_guidance_max_todos_per_scope",
                            getattr(args, "leanstral_rule_gap_max_todos_per_scope", 2),
                        )
                        or 2
                    ),
                ),
            )
            before_ids = {todo.todo_id for todo in supervisor.queue.all()}
            added_count = supervisor.queue.add_many(hammer_failure_todos)
            seeded_todo_ids = [
                todo.todo_id
                for todo in hammer_failure_todos
                if todo.todo_id not in before_ids and supervisor.queue.get(todo.todo_id)
            ]
            hammer_failure_projection.update(
                {
                    "deduped_count": max(0, len(hammer_failure_todos) - added_count),
                    "generated_count": len(hammer_failure_todos),
                    "seeded_count": added_count,
                    "seeded_todo_ids": seeded_todo_ids,
                    "status": "projected"
                    if hammer_failure_todos
                    else "no_recurring_failures",
                }
            )
        supervisor.queue.save_jsonl(queue_path)
    result.update(projection.to_dict())
    result["hammer_failure_projection"] = hammer_failure_projection
    if hammer_failure_projection.get("seeded_count"):
        result["seeded_count"] = int(result.get("seeded_count", 0) or 0) + int(
            hammer_failure_projection.get("seeded_count", 0) or 0
        )
        result["seeded_todo_ids"] = _hammer_projection_unique_strings(
            [
                *list(result.get("seeded_todo_ids", []) or []),
                *list(hammer_failure_projection.get("seeded_todo_ids", []) or []),
            ]
        )
    if hammer_failure_projection.get("deduped_count"):
        result["deduped_count"] = int(result.get("deduped_count", 0) or 0) + int(
            hammer_failure_projection.get("deduped_count", 0) or 0
        )
    result["feedback_backfill"] = dict(backfill_report)
    if bool(getattr(args, "leanstral_direct_guidance_train_autoencoder", True)):
        if autoencoder is None:
            result["autoencoder_training"] = {
                "enabled": True,
                "status": "missing_autoencoder",
            }
        else:
            result["autoencoder_training"] = autoencoder.apply_leanstral_guidance(
                guidance_items,
                samples_by_id=samples_by_id or {},
                learning_rate=float(
                    getattr(args, "leanstral_direct_guidance_learning_rate", 0.05)
                    or 0.0
                ),
                allow_global_updates=bool(
                    getattr(
                        args,
                        "leanstral_direct_guidance_train_missing_samples",
                        False,
                    )
                ),
                max_items=max(
                    0,
                    int(getattr(args, "leanstral_direct_guidance_max_training_items", 64) or 64),
                ),
                require_trusted=True,
            )
    result["status"] = "projected"
    return result


def combine_leanstral_projection_results(
    *projections: Mapping[str, Any],
) -> Dict[str, Any]:
    """Combine rule-gap and direct-guidance projection telemetry for summaries."""

    sources = [
        dict(projection)
        for projection in projections
        if isinstance(projection, Mapping) and projection
    ]
    combined: Dict[str, Any] = {
        "budget_blocked_count": 0,
        "deduped_count": 0,
        "enabled": any(bool(item.get("enabled")) for item in sources),
        "projection_sources": sources,
        "report_only_count": 0,
        "seeded_count": 0,
        "seeded_todo_ids": [],
        "stale_count": 0,
        "status": "no_projection_sources" if not sources else "combined",
    }
    todo_ids: List[str] = []
    for item in sources:
        for key in (
            "budget_blocked_count",
            "deduped_count",
            "report_only_count",
            "seeded_count",
            "stale_count",
        ):
            combined[key] = int(combined.get(key, 0) or 0) + int(
                item.get(key, 0) or 0
            )
        for todo_id in item.get("seeded_todo_ids", []) or []:
            text = str(todo_id).strip()
            if text and text not in todo_ids:
                todo_ids.append(text)
    combined["seeded_todo_ids"] = todo_ids
    combined["source_statuses"] = [
        str(item.get("status") or "") for item in sources if item.get("status")
    ]
    return combined


def _split_path_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        raw_values: Iterable[Any] = str(value).split(",")
    else:
        raw_values = value
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _expand_leanstral_guidance_files(
    paths: Sequence[str | Path],
    *,
    max_files: int,
) -> List[Path]:
    files: List[Path] = []
    seen: set[str] = set()
    limit = max(0, int(max_files))
    for raw_path in paths:
        if len(files) >= limit:
            break
        path = Path(raw_path).expanduser()
        candidates: List[Path]
        if path.is_dir():
            candidates = sorted(
                [
                    *path.rglob("*.json"),
                    *path.rglob("*.jsonl"),
                ],
                key=lambda item: str(item),
            )
        elif path.is_file():
            candidates = [path]
        else:
            candidates = []
        for candidate in candidates:
            if len(files) >= limit:
                break
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            files.append(candidate)
    return files


def _read_leanstral_guidance_payloads(
    path: Path,
    *,
    max_payloads: int,
) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        payloads: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if len(payloads) >= max(0, int(max_payloads)):
                    break
                raw = line.strip()
                if not raw:
                    continue
                payload = json.loads(raw)
                if isinstance(payload, Mapping):
                    payloads.append(dict(payload))
        return payloads
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        payloads = []
        for item in payload:
            if len(payloads) >= max(0, int(max_payloads)):
                break
            if isinstance(item, Mapping):
                payloads.append(dict(item))
        return payloads
    return [dict(payload)] if isinstance(payload, Mapping) else []


def _leanstral_guidance_items_from_payload(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            items: List[Dict[str, Any]] = []
            for item in value:
                items.extend(_leanstral_guidance_items_from_payload(item))
            return items
        return []
    payload = dict(value)
    if (
        payload.get("schema_version") == "legal-ir-leanstral-draft-guidance-v1"
        or str(payload.get("schema_version") or "").startswith("legal-ir-hammer-")
        or payload.get("guidance_id")
        and (
            "drafted_logic_candidates" in payload
            or payload.get("source") == "hammer_verified_guidance"
            or payload.get("source") == "leanstral_shadow_proof"
        )
    ):
        return [payload]

    items: List[Dict[str, Any]] = []
    for key in (
        "leanstral_guidance",
        "latest_leanstral_guidance",
        "guidance",
    ):
        nested = payload.get(key)
        if nested:
            items.extend(_leanstral_guidance_items_from_payload(nested))
    for key in ("external_guidance", "guidance_items", "items"):
        nested_items = payload.get(key)
        if nested_items:
            items.extend(_leanstral_guidance_items_from_payload(nested_items))
    for key in ("hammer_guidance_artifacts", "verified_guidance"):
        nested_items = payload.get(key)
        if nested_items:
            items.extend(_leanstral_guidance_items_from_payload(nested_items))
    candidate_results = payload.get("candidate_results")
    if isinstance(candidate_results, Sequence) and not isinstance(
        candidate_results,
        (str, bytes),
    ):
        for candidate_result in candidate_results:
            if not isinstance(candidate_result, Mapping):
                continue
            items.extend(
                _leanstral_guidance_items_from_payload(
                    candidate_result.get("verified_guidance")
                )
            )
            hammer_report = candidate_result.get("hammer_report")
            if isinstance(hammer_report, Mapping):
                items.extend(
                    _leanstral_guidance_items_from_payload(
                        hammer_report.get("artifacts")
                    )
                )
    for key in ("compiler_guidance", "leanstral_shadow"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            items.extend(_leanstral_guidance_items_from_payload(nested))
    return items


def daemon_hammer_guidance_artifact_path(
    args: argparse.Namespace,
    *,
    root: Path,
    cycle: int,
) -> Path:
    """Return the per-cycle hammer guidance artifact path used by the daemon."""

    explicit = str(getattr(args, "daemon_hammer_guidance_output_dir", "") or "").strip()
    output_dir = Path(explicit).expanduser() if explicit else root / "workspace" / "legal-ir-hammer-guidance"
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    run_id = str(getattr(args, "run_id", "default") or "default")
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", run_id).strip("-") or "default"
    return output_dir / f"{safe_run_id}.cycle-{max(0, int(cycle)):06d}.hammer-guidance.json"


def _daemon_hammer_config_payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "max_obligations": max(
            0,
            int(
                getattr(
                    args,
                    "daemon_hammer_guidance_max_obligations_per_sample",
                    DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_OBLIGATIONS_PER_SAMPLE,
                )
                or 0
            ),
        ),
        "max_premises": max(
            1,
            int(
                getattr(
                    args,
                    "daemon_hammer_guidance_max_premises",
                    DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_PREMISES,
                )
                or DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_PREMISES
            ),
        ),
        "parallel_workers": max(
            1,
            int(
                getattr(
                    args,
                    "daemon_hammer_guidance_parallel_workers",
                    DEFAULT_DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS,
                )
                or DEFAULT_DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS
            ),
        ),
        "timeout_seconds": max(
            0.001,
            float(
                getattr(
                    args,
                    "daemon_hammer_guidance_timeout_seconds",
                    DEFAULT_DAEMON_HAMMER_GUIDANCE_TIMEOUT_SECONDS,
                )
                or DEFAULT_DAEMON_HAMMER_GUIDANCE_TIMEOUT_SECONDS
            ),
        ),
        "trusted_requires_reconstruction": bool(
            getattr(args, "daemon_hammer_guidance_trusted_requires_reconstruction", False)
        ),
        "verify_reconstruction": bool(
            getattr(args, "daemon_hammer_guidance_verify_reconstruction", False)
        ),
    }


def _daemon_hammer_config(args: argparse.Namespace) -> LegalIRHammerConfig:
    payload = _daemon_hammer_config_payload(args)
    return LegalIRHammerConfig(
        max_obligations=int(payload["max_obligations"]),
        max_premises=int(payload["max_premises"]),
        parallel_workers=int(payload["parallel_workers"]),
        timeout_seconds=float(payload["timeout_seconds"]),
        trusted_requires_reconstruction=bool(payload["trusted_requires_reconstruction"]),
        verify_reconstruction=bool(payload["verify_reconstruction"]),
    )


def _daemon_hammer_sample_id(sample: Any) -> str:
    if isinstance(sample, Mapping):
        return str(sample.get("sample_id") or sample.get("id") or "").strip()
    return str(getattr(sample, "sample_id", "") or "").strip()


def _daemon_hammer_sample_citation(sample: Any) -> str:
    if isinstance(sample, Mapping):
        return str(
            sample.get("citation")
            or sample.get("citation_text")
            or sample.get("normalized_citation")
            or ""
        ).strip()
    return str(
        getattr(sample, "citation", "")
        or getattr(sample, "citation_text", "")
        or getattr(sample, "normalized_citation", "")
        or ""
    ).strip()


def _daemon_hammer_report_dict(report: Any) -> Dict[str, Any]:
    if isinstance(report, Mapping):
        return dict(report)
    to_dict = getattr(report, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, Mapping) else {}
    return {}


def _daemon_hammer_report_artifacts(report: Any) -> List[Dict[str, Any]]:
    report_dict = _daemon_hammer_report_dict(report)
    artifacts = report_dict.get("artifacts")
    if isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes)):
        return [dict(item) for item in artifacts if isinstance(item, Mapping)]
    raw_artifacts = getattr(report, "artifacts", None)
    if isinstance(raw_artifacts, Sequence) and not isinstance(raw_artifacts, (str, bytes)):
        results: List[Dict[str, Any]] = []
        for artifact in raw_artifacts:
            if isinstance(artifact, Mapping):
                results.append(dict(artifact))
                continue
            to_dict = getattr(artifact, "to_dict", None)
            if callable(to_dict):
                payload = to_dict()
                if isinstance(payload, Mapping):
                    results.append(dict(payload))
        return results
    return []


def _leanstral_hammer_candidate_count(value: Any) -> int:
    if isinstance(value, Mapping):
        count = 0
        candidates = value.get("drafted_logic_candidates")
        if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)):
            count += sum(1 for item in candidates if isinstance(item, Mapping))
        for key in (
            "candidate_results",
            "compiler_guidance",
            "external_guidance",
            "guidance",
            "guidance_items",
            "hammer_guidance_artifacts",
            "items",
            "leanstral_guidance",
            "latest_leanstral_guidance",
            "verified_guidance",
        ):
            nested = value.get(key)
            if nested:
                count += _leanstral_hammer_candidate_count(nested)
        hammer_report = value.get("hammer_report")
        if isinstance(hammer_report, Mapping):
            count += _leanstral_hammer_candidate_count(hammer_report.get("artifacts"))
        return count
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return sum(_leanstral_hammer_candidate_count(item) for item in value)
    return 0


def _daemon_hammer_cache_payload_compatible(
    payload: Mapping[str, Any],
    *,
    config_payload: Mapping[str, Any],
    sample_ids: Sequence[str],
) -> bool:
    return (
        str(payload.get("schema_version") or "")
        == DAEMON_HAMMER_GUIDANCE_CYCLE_SCHEMA_VERSION
        and list(payload.get("sample_ids", []) or []) == list(sample_ids)
        and dict(payload.get("hammer_config") or {}) == dict(config_payload)
    )


def _daemon_hammer_loaded_guidance(
    *,
    args: argparse.Namespace,
    root: Path,
    artifact_paths: Sequence[str | Path],
) -> Dict[str, Any]:
    paths = leanstral_direct_guidance_paths(
        args,
        root=root,
        artifact_paths=artifact_paths,
    )
    if not paths:
        return {
            "artifact_count": 0,
            "candidate_count": 0,
            "guidance_count": 0,
            "guidance_items": [],
            "paths": [],
            "status": "skipped_no_guidance_paths",
        }
    loaded = load_leanstral_direct_guidance_artifacts(paths)
    items = [
        dict(item)
        for item in loaded.get("guidance_items", []) or []
        if isinstance(item, Mapping)
    ]
    candidate_count = _leanstral_hammer_candidate_count(items)
    status = "drafts_loaded" if candidate_count else "skipped_no_drafted_candidates"
    if int(loaded.get("artifact_count", 0) or 0) <= 0:
        status = "skipped_no_guidance_artifacts"
    return {
        **dict(loaded),
        "candidate_count": int(candidate_count),
        "guidance_items": items,
        "status": status,
    }


def run_daemon_hammer_guidance_cycle(
    *,
    args: argparse.Namespace,
    root: Path,
    cycle: int,
    samples: Sequence[Any],
    autoencoder: Optional[AdaptiveModalAutoencoder] = None,
    samples_by_id: Optional[Mapping[str, Any]] = None,
    artifact_paths: Optional[Sequence[str | Path]] = None,
) -> Dict[str, Any]:
    """Run the daemon-local hammer guidance phase with fail-closed skip records."""

    enabled = bool(getattr(args, "daemon_hammer_guidance_enabled", True))
    config_payload = _daemon_hammer_config_payload(args)
    max_samples = max(
        0,
        int(
            getattr(
                args,
                "daemon_hammer_guidance_max_samples_per_cycle",
                DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_SAMPLES_PER_CYCLE,
            )
            or 0
        ),
    )
    selected_samples = list(samples)[:max_samples] if max_samples else []
    sample_ids = [_daemon_hammer_sample_id(sample) for sample in selected_samples]
    contract_telemetry_records = [
        collect_legal_ir_contract_telemetry(sample) for sample in selected_samples
    ]
    contract_telemetry_by_sample = {
        record.sample_id: record for record in contract_telemetry_records
    }
    contract_telemetry_summary = summarize_legal_ir_contract_telemetry(
        contract_telemetry_records
    )
    output_path = daemon_hammer_guidance_artifact_path(args, root=root, cycle=cycle)
    result: Dict[str, Any] = {
        "artifact_paths": [],
        "cache_hit": False,
        "cycle": int(cycle),
        "enabled": enabled,
        "hammer_artifact_count": 0,
        "hammer_config": config_payload,
        "hammer_projected_todo_count": 0,
        "hammer_reports": [],
        "leanstral_hammer_candidate_count": 0,
        "obligation_count": 0,
        "output_path": str(output_path),
        "sample_count": len(selected_samples),
        "sample_ids": sample_ids,
        "schema_version": DAEMON_HAMMER_GUIDANCE_CYCLE_SCHEMA_VERSION,
        "status": "not_run",
        "trusted_hammer_guidance_count": 0,
        "legal_ir_contract_telemetry": [
            record.to_dict() for record in contract_telemetry_records
        ],
        **contract_telemetry_summary,
    }
    loaded_guidance = _daemon_hammer_loaded_guidance(
        args=args,
        root=root,
        artifact_paths=list(artifact_paths or []),
    )
    result["leanstral_drafting"] = {
        "artifact_count": int(loaded_guidance.get("artifact_count", 0) or 0),
        "candidate_count": int(loaded_guidance.get("candidate_count", 0) or 0),
        "guidance_count": int(loaded_guidance.get("guidance_count", 0) or 0),
        "path_count": len(loaded_guidance.get("paths", []) or []),
        "paths": list(loaded_guidance.get("paths", []) or []),
        "status": str(loaded_guidance.get("status") or "not_run"),
    }
    result["leanstral_hammer_candidate_count"] = int(
        loaded_guidance.get("candidate_count", 0) or 0
    )
    if not enabled:
        result["status"] = "disabled"
        result["hammer_metrics"] = hammer_guidance_metric_block(
            loaded_guidance.get("guidance_items", [])
        )
        return result
    if not selected_samples:
        result["status"] = "skipped_no_samples"
        result["hammer_metrics"] = hammer_guidance_metric_block(
            loaded_guidance.get("guidance_items", [])
        )
        return result

    cache_enabled = bool(getattr(args, "daemon_hammer_guidance_cache_enabled", True))
    cached_artifacts: List[Dict[str, Any]] = []
    if cache_enabled and output_path.is_file():
        try:
            cached_payload = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(cached_payload, Mapping) and _daemon_hammer_cache_payload_compatible(
                cached_payload,
                config_payload=config_payload,
                sample_ids=sample_ids,
            ):
                cached_artifacts = [
                    dict(item)
                    for item in cached_payload.get("hammer_guidance_artifacts", []) or []
                    if isinstance(item, Mapping)
                ]
                result.update(dict(cached_payload))
                result["cache_hit"] = True
                result["status"] = "cache_hit"
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            result["cache_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"

    hammer_artifacts: List[Dict[str, Any]] = []
    for cached_artifact in cached_artifacts:
        cached_metadata = dict(cached_artifact.get("metadata") or {})
        embedded_telemetry = dict(
            cached_artifact.get("legal_ir_contract_telemetry") or {}
        )
        cached_sample_id = str(
            embedded_telemetry.get("sample_id")
            or cached_metadata.get("sample_id")
            or ""
        )
        telemetry = contract_telemetry_by_sample.get(cached_sample_id)
        if telemetry is None and len(contract_telemetry_records) == 1:
            telemetry = contract_telemetry_records[0]
        if telemetry is None:
            hammer_artifacts.append(cached_artifact)
        else:
            hammer_artifacts.extend(
                attach_legal_ir_contract_telemetry([cached_artifact], telemetry)
            )
    hammer_reports: List[Dict[str, Any]] = [
        dict(item)
        for item in result.get("hammer_reports", []) or []
        if isinstance(item, Mapping)
    ] if result.get("cache_hit") else []
    obligation_failures: List[Dict[str, Any]] = []
    hammer_failures: List[Dict[str, Any]] = []
    if not result.get("cache_hit"):
        hammer_config = _daemon_hammer_config(args)
        for sample in selected_samples:
            sample_id = _daemon_hammer_sample_id(sample)
            try:
                obligations = generate_legal_ir_proof_obligations(sample)
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                obligation_failures.append(
                    {
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                        "sample_id": sample_id,
                    }
                )
                obligations = []
            if hammer_config.max_obligations > 0:
                obligations = obligations[: hammer_config.max_obligations]
            result["obligation_count"] = int(result.get("obligation_count", 0) or 0) + len(obligations)
            if not obligations:
                continue
            try:
                report = run_legal_ir_hammer(
                    sample,
                    obligations=obligations,
                    config=hammer_config,
                )
            except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
                hammer_failures.append(
                    {
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                        "sample_id": sample_id,
                    }
                )
                continue
            report_dict = _daemon_hammer_report_dict(report)
            if sample_id:
                report_dict.setdefault("sample_id", sample_id)
            citation = _daemon_hammer_sample_citation(sample)
            if citation:
                report_dict.setdefault("citation", citation)
            sample_artifacts = _daemon_hammer_report_artifacts(report)
            telemetry = contract_telemetry_by_sample.get(sample_id)
            if telemetry is not None:
                sample_artifacts = attach_legal_ir_contract_telemetry(
                    sample_artifacts, telemetry
                )
            report_dict["artifacts"] = sample_artifacts
            if telemetry is not None:
                report_dict["legal_ir_contract_telemetry"] = (
                    telemetry.guidance_projection()
                )
            hammer_reports.append(report_dict)
            hammer_artifacts.extend(sample_artifacts)

    combined_guidance = [
        *list(loaded_guidance.get("guidance_items", []) or []),
        *hammer_artifacts,
    ]
    hammer_metrics = hammer_guidance_metric_block(combined_guidance)
    result.update(
        {
            "artifact_paths": [str(output_path)] if hammer_artifacts else [],
            "hammer_artifact_count": len(hammer_artifacts),
            "hammer_guidance_artifacts": hammer_artifacts,
            "hammer_guidance_metric_schema_version": HAMMER_GUIDANCE_METRIC_SCHEMA_VERSION,
            "hammer_metrics": hammer_metrics,
            "hammer_reports": hammer_reports[:16],
            "obligation_failure_count": len(obligation_failures),
            "obligation_failures": obligation_failures[:16],
            "runtime_failure_count": len(hammer_failures),
            "runtime_failures": hammer_failures[:16],
            "trusted_hammer_guidance_count": int(
                hammer_metrics.get("trusted_hammer_guidance_count", 0) or 0
            ),
        }
    )
    if not result.get("cache_hit"):
        result["status"] = "completed" if hammer_artifacts else "completed_no_hammer_artifacts"
        persisted = {
            key: value
            for key, value in result.items()
            if key
            not in {
                "leanstral_drafting",
            }
        }
        persisted["leanstral_drafting"] = dict(result.get("leanstral_drafting") or {})
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(persisted, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            result["artifact_paths"] = []
            result["persist_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
            result["status"] = "completed_persist_failed"

    training_enabled = bool(getattr(args, "daemon_hammer_guidance_train_autoencoder", True))
    result["autoencoder_training"] = {
        "enabled": training_enabled,
        "status": "not_run",
    }
    if training_enabled:
        if autoencoder is None:
            result["autoencoder_training"] = {
                "enabled": True,
                "status": "missing_autoencoder",
            }
        else:
            sample_lookup = dict(samples_by_id or {})
            for sample in selected_samples:
                sample_id = _daemon_hammer_sample_id(sample)
                if sample_id:
                    sample_lookup.setdefault(sample_id, sample)
            result["autoencoder_training"] = autoencoder.apply_leanstral_guidance(
                combined_guidance,
                samples_by_id=sample_lookup,
                learning_rate=float(
                    getattr(args, "daemon_hammer_guidance_learning_rate", 0.03)
                    or 0.0
                ),
                allow_global_updates=bool(
                    getattr(args, "daemon_hammer_guidance_train_missing_samples", False)
                ),
                max_items=max(
                    0,
                    int(getattr(args, "daemon_hammer_guidance_max_training_items", 64) or 64),
                ),
                require_trusted=True,
            )
    return result


def _hammer_projected_count_from_projection(projection: Mapping[str, Any]) -> int:
    count = 0
    sources = projection.get("projection_sources")
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        for source in sources:
            if isinstance(source, Mapping):
                count += _hammer_projected_count_from_projection(source)
    failure_projection = projection.get("hammer_failure_projection")
    if isinstance(failure_projection, Mapping):
        count += int(failure_projection.get("seeded_count", 0) or 0)
    return count


def update_daemon_hammer_guidance_summary(
    summary: Dict[str, Any],
    cycle_report: Mapping[str, Any],
    *,
    projection: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Expose hammer/Leanstral cycle telemetry under stable daemon keys."""

    report = dict(cycle_report or {})
    projection = dict(projection or {})
    hammer_metrics = dict(report.get("hammer_metrics") or {})
    hammer_projected_todo_count = _hammer_projected_count_from_projection(projection)
    if hammer_projected_todo_count <= 0:
        hammer_projected_todo_count = int(report.get("hammer_projected_todo_count", 0) or 0)
    report["hammer_projected_todo_count"] = hammer_projected_todo_count
    summary["latest_daemon_hammer_guidance"] = report
    summary["hammer_proof_success_rate"] = float(
        hammer_metrics.get("hammer_proof_success_rate", 0.0) or 0.0
    )
    summary["hammer_reconstruction_success_rate"] = float(
        hammer_metrics.get("hammer_reconstruction_success_rate", 0.0) or 0.0
    )
    summary["leanstral_hammer_candidate_count"] = int(
        report.get("leanstral_hammer_candidate_count", 0) or 0
    )
    summary["trusted_hammer_guidance_count"] = int(
        hammer_metrics.get(
            "trusted_hammer_guidance_count",
            report.get("trusted_hammer_guidance_count", 0),
        )
        or 0
    )
    summary["hammer_projected_todo_count"] = int(hammer_projected_todo_count)
    summary["hammer_guidance_artifact_count"] = int(
        hammer_metrics.get("hammer_artifact_count", report.get("hammer_artifact_count", 0))
        or 0
    )
    summary["contract_telemetry_schema_version"] = str(
        report.get("contract_telemetry_schema_version")
        or LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION
    )
    summary["legal_ir_contract_coverage"] = float(
        report.get("legal_ir_contract_coverage", 0.0) or 0.0
    )
    summary["legal_ir_contract_failure_counts"] = dict(
        report.get("legal_ir_contract_failure_counts") or {}
    )
    summary["legal_ir_contract_view_family_gaps"] = dict(
        report.get("legal_ir_contract_view_family_gaps") or {}
    )
    summary["latest_legal_ir_contract_telemetry"] = list(
        report.get("legal_ir_contract_telemetry") or []
    )
    for key in (
        "hammer_guidance_artifact_count",
        "hammer_projected_todo_count",
        "leanstral_hammer_candidate_count",
        "trusted_hammer_guidance_count",
    ):
        total_key = f"{key}_total"
        summary[total_key] = int(summary.get(total_key, 0) or 0) + int(
            summary.get(key, 0) or 0
        )
    return summary


def project_verified_leanstral_rule_gaps_into_queue(
    *,
    args: argparse.Namespace,
    queue_path: Path,
    root: Path,
    supervisor: ModalTodoSupervisor,
    worker_health: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Load a verified Leanstral rule-gap report and seed the shared TODO queue."""
    report_path = leanstral_rule_gap_report_path(args, root=root)
    result: Dict[str, Any] = {
        "enabled": bool(getattr(args, "leanstral_rule_gap_projection_enabled", True)),
        "path": str(report_path),
        "report_loaded": False,
        "seeded_count": 0,
        "deduped_count": 0,
        "stale_count": 0,
        "budget_blocked_count": 0,
        "report_only_count": 0,
        "seeded_todo_ids": [],
    }
    if not result["enabled"]:
        result["status"] = "disabled"
        return result
    if not report_path.is_file():
        result["status"] = "missing_report"
        return result
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["status"] = "invalid_report"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return result
    result["report_loaded"] = True
    config = LeanstralTodoProjectionConfig(
        max_audits_per_cycle=max(
            0,
            int(getattr(args, "autoencoder_max_audits_per_cycle", 0) or 0),
        ),
        max_todos_per_cycle=max(
            0,
            int(getattr(args, "autoencoder_max_todos_per_cycle", 0) or 0),
        ),
        max_todos_per_scope=max(
            1,
            int(getattr(args, "leanstral_rule_gap_max_todos_per_scope", 2) or 2),
        ),
        max_program_synthesis_pending=max(
            0,
            int(getattr(args, "max_program_synthesis_pending", 512) or 512),
        ),
        require_verified_support=True,
        require_executor_available=bool(
            getattr(args, "leanstral_rule_gap_require_executor_available", True)
        ),
        expected_compiler_commit=str(
            getattr(args, "leanstral_rule_gap_expected_compiler_commit", "")
            or ""
        ),
        expected_state_hash=str(
            getattr(args, "leanstral_rule_gap_expected_state_hash", "")
            or ""
        ),
        max_report_age_seconds=(
            float(getattr(args, "leanstral_rule_gap_max_report_age_seconds"))
            if getattr(args, "leanstral_rule_gap_max_report_age_seconds", None)
            is not None
            else None
        ),
        target_scope_filters=autoencoder_target_scope_filters(args),
        worker_health=dict(worker_health or {}),
    )
    with queue_file_lock(queue_path):
        latest_queue = ModalTodoQueue.load_jsonl(queue_path)
        latest_queue.merge_from(
            supervisor.queue,
            preserve_claimed_role=supervisor.policy.program_synthesis_role,
        )
        supervisor.queue = latest_queue
        backfill_report = supervisor.backfill_leanstral_patch_feedback_evidence()
        projection = supervisor.seed_program_synthesis_from_leanstral_rule_gap_report(
            report,
            config=config,
        )
        supervisor.queue.save_jsonl(queue_path)
    result.update(projection.to_dict())
    result["feedback_backfill"] = dict(backfill_report)
    result["status"] = "projected"
    result["report_schema_version"] = str(report.get("schema_version") or "")
    return result


def update_leanstral_projection_summary(
    summary: Dict[str, Any],
    projection: Mapping[str, Any],
) -> Dict[str, Any]:
    """Accumulate production Leanstral projection counters in daemon summary."""
    summary["latest_leanstral_projection"] = dict(projection)
    for key in (
        "seeded",
        "deduped",
        "stale",
        "budget_blocked",
        "report_only",
    ):
        latest_key = f"latest_leanstral_projection_{key}_count"
        source_key = f"{key}_count"
        summary[latest_key] = int(projection.get(source_key, 0) or 0)
        total_key = f"leanstral_projection_{key}_total"
        summary[total_key] = int(summary.get(total_key, 0) or 0) + int(
            projection.get(source_key, 0) or 0
        )
    summary["latest_leanstral_projection_todo_ids"] = list(
        projection.get("seeded_todo_ids", []) or []
    )
    training_reports = [
        dict(item.get("autoencoder_training") or {})
        for item in projection.get("projection_sources", []) or []
        if isinstance(item, Mapping) and item.get("autoencoder_training")
    ]
    if training_reports:
        latest_training = training_reports[-1]
        summary["latest_leanstral_direct_guidance_autoencoder_training"] = (
            latest_training
        )
        for key in (
            "applied",
            "duplicate",
            "sample_aware_update",
            "skipped_missing_sample",
            "skipped_untrusted",
        ):
            source_key = f"{key}_count"
            latest_key = f"latest_leanstral_direct_guidance_training_{source_key}"
            total_key = f"leanstral_direct_guidance_training_{source_key}_total"
            value = int(latest_training.get(source_key, 0) or 0)
            summary[latest_key] = value
            summary[total_key] = int(summary.get(total_key, 0) or 0) + value
    return summary


def _sampling_seed_for_args(args: argparse.Namespace) -> tuple[int, str]:
    raw = getattr(args, "sampling_seed", None)
    if raw is not None and str(raw).strip():
        text = str(raw).strip()
        try:
            return int(text), text
        except ValueError:
            return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16), text
    run_id = str(getattr(args, "run_id", "") or "default")
    return int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12], 16), "run_id"


def _should_run_cycle_cadence(*, cycle: int, mode: str, every_n_cycles: int) -> bool:
    normalized = str(mode or "every_cycle").strip().lower()
    if normalized in {"off", "none", "false"}:
        return False
    if normalized in {"every_cycle", "always"}:
        return True
    if normalized == "periodic":
        cadence = int(every_n_cycles or 0)
        return cadence > 0 and int(cycle) % cadence == 0
    return True


def _should_run_cycle_tests(cycle: int, every_n_cycles: int) -> bool:
    cadence = int(every_n_cycles or 0)
    return cadence > 0 and int(cycle) % cadence == 0


def _todo_supervisor_skip_decision(
    *,
    mode: str,
    program_synthesis_status: Mapping[str, Any],
    min_open: int,
) -> Dict[str, Any]:
    normalized = str(mode or "starved").strip().lower()
    pending = int(program_synthesis_status.get("pending", 0) or 0)
    claimed = int(program_synthesis_status.get("claimed", 0) or 0)
    open_count = pending + claimed
    if normalized in {"off", "none", "false"}:
        return {
            "open_count": open_count,
            "skip_reason": "todo_supervisor_disabled",
            "skipped": True,
        }
    if normalized == "starved" and open_count >= int(min_open):
        return {
            "open_count": open_count,
            "skip_reason": "program_synthesis_queue_sufficient",
            "skipped": True,
        }
    return {"open_count": open_count, "skip_reason": "", "skipped": False}


def paired_codex_child_env(args: argparse.Namespace) -> Dict[str, str]:
    if not bool(getattr(args, "paired_codex_disable_cuda", True)):
        return {}
    return {
        "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_CODEX_TASK_EMBEDDINGS_DEVICE": "cpu",
        "NVIDIA_VISIBLE_DEVICES": "none",
    }


def _round_robin_codex_children(
    children: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Mapping[str, Any]]] = {}
    for child in children:
        buckets.setdefault(str(child.get("scope") or ""), []).append(child)
    selected: List[Dict[str, Any]] = []
    while len(selected) < max(0, int(limit)) and any(buckets.values()):
        for scope in sorted(list(buckets)):
            bucket = buckets.get(scope) or []
            if not bucket:
                continue
            selected.append(dict(bucket.pop(0)))
            if len(selected) >= max(0, int(limit)):
                break
    return selected


def _claim_program_synthesis_batch_with_scope_fallback(
    supervisor: ModalTodoSupervisor,
    *,
    worker_id: str,
    max_items: int,
    requested_scope: Optional[str],
    semantic_bundle: bool = False,
    fallback_to_global: bool = True,
) -> tuple[List[ModalTodo], Dict[str, Any]]:
    claimed = supervisor.claim_program_synthesis_batch(
        worker_id=worker_id,
        max_items=max_items,
        program_synthesis_scope=requested_scope,
        semantic_bundle=semantic_bundle,
    )
    if claimed or not fallback_to_global or not requested_scope:
        return claimed, {
            "borrowed_scopes": [],
            "fallback_used": False,
            "requested_scope": requested_scope,
        }
    claimed = supervisor.claim_program_synthesis_batch(
        worker_id=worker_id,
        max_items=max_items,
        program_synthesis_scope=None,
        semantic_bundle=semantic_bundle,
    )
    borrowed = list(
        dict.fromkeys(
            str(todo.metadata.get("program_synthesis_scope") or "")
            for todo in claimed
            if str(todo.metadata.get("program_synthesis_scope") or "")
        )
    )
    return claimed, {
        "borrowed_scopes": borrowed,
        "fallback_used": bool(claimed),
        "requested_scope": requested_scope,
    }


def _clamp_nested_bridge_adapter_parallelism(
    *,
    bridge_parallel_workers: int,
    sample_parallel_workers: int,
    adapter_count: int,
) -> Dict[str, Any]:
    requested = os.environ.get("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS")
    requested_workers = (
        int(requested)
        if requested is not None and str(requested).strip().isdigit()
        else max(1, int(adapter_count or 1))
    )
    budget = max(1, int(bridge_parallel_workers or 1))
    sample_workers = max(1, int(sample_parallel_workers or 1))
    adapter_workers = max(1, min(requested_workers, int(adapter_count or 1)))
    effective = max(1, min(adapter_workers, max(1, budget // sample_workers)))
    os.environ["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] = str(effective)
    return {
        "adapter_count": int(adapter_count or 0),
        "bridge_parallel_workers": int(bridge_parallel_workers or 0),
        "clamped": effective != requested_workers,
        "effective_adapter_workers": effective,
        "estimated_nested_workers": effective * sample_workers,
        "nested_worker_budget": budget,
        "requested_adapter_workers": requested_workers,
        "sample_parallel_workers": sample_workers,
    }


def _codex_validation_failure_details(
    *,
    command: Sequence[str],
    command_index: int,
    status: str,
    exit_code: Optional[int],
    stdout: str,
    stderr: str,
) -> Dict[str, Any]:
    text = f"{stdout}\n{stderr}"
    failed_tests: List[str] = []
    failure_tokens: List[str] = []
    syntax_locations: List[Dict[str, Any]] = []
    for match in re.finditer(r"\bFAILED\s+([A-Za-z0-9_./\\-]+\.py::[^\s]+)", text):
        node_id = match.group(1).strip()
        if node_id and node_id not in failed_tests:
            failed_tests.append(node_id)
    for match in re.finditer(r"([\w./-]+\.py):\d+:\s+in\s+([A-Za-z_][\w]*)", text):
        node_id = f"{match.group(1)}::{match.group(2)}"
        if node_id not in failed_tests:
            failed_tests.append(node_id)
    for node_id in failed_tests:
        token = f"pytest:{node_id}"
        if token not in failure_tokens:
            failure_tokens.append(token)
    for match in re.finditer(r'File "([^"]+\.py)", line (\d+)', text):
        path = match.group(1)
        try:
            line = int(match.group(2))
        except (TypeError, ValueError):
            line = 0
        syntax_locations.append({"line": line, "path": path})
    if "-m" in command and "py_compile" in command:
        for part in command:
            if str(part).endswith(".py"):
                token = f"py_compile:{part}"
                if token not in failure_tokens:
                    failure_tokens.append(token)
                if not any(location.get("path") == part for location in syntax_locations):
                    syntax_locations.append({"line": 0, "path": str(part)})
    return {
        "command": list(command),
        "command_index": int(command_index),
        "exit_code": exit_code,
        "failed_tests": failed_tests,
        "failure_tokens": failure_tokens,
        "status": status,
        "syntax_locations": syntax_locations,
    }


def paired_program_synthesis_health(
    *,
    queue_path: Path,
    codex_summary_paths: Sequence[Path],
    codex_worker_stale_seconds: float = 300.0,
) -> Dict[str, Any]:
    queue_exists = queue_path.exists()
    queue = ModalTodoQueue.load_jsonl(queue_path) if queue_exists else ModalTodoQueue()
    status = queue.role_status_counts().get("program_synthesis", {})
    transient_counts = queue.transient_failure_counts(
        optimizer_role="program_synthesis"
    )
    active_transient_counts = queue.transient_failure_counts(
        optimizer_role="program_synthesis",
        statuses=("pending", "claimed"),
    )
    failed_reason_counts: Counter[str] = Counter()
    failed_kind_counts: Counter[str] = Counter()
    failed_test_counts: Counter[str] = Counter()
    claimed_by_worker: Counter[str] = Counter()
    for todo in queue.all():
        if todo.status == "claimed" and todo.claimed_by:
            claimed_by_worker[str(todo.claimed_by)] += 1
        if todo.status != "failed_validation":
            continue
        reason = str(todo.metadata.get("failed_validation_reason") or "")
        if reason:
            failed_reason_counts[reason] += 1
        report = todo.metadata.get("failed_validation_report")
        if isinstance(report, Mapping):
            tests = list(report.get("main_apply_validation_failed_tests", []) or [])
            tokens = list(report.get("main_apply_validation_failure_tokens", []) or [])
            if tests or tokens:
                failed_kind_counts["pytest"] += 1
            for test in tests:
                failed_test_counts[str(test)] += 1

    waiting = 0
    active = 0
    claimed_total = 0
    transient_requeue_total = 0
    execution_count = 0
    idle_stale = 0
    stale_claimed_worker_ids: List[str] = []
    stale_idle_worker_ids: List[str] = []
    summary_count = 0
    now = time.time()
    for path in codex_summary_paths:
        if not Path(path).is_file():
            continue
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary_count += 1
        claimed_total += int(payload.get("codex_claimed_total", 0) or 0)
        child_execution_count = int(payload.get("codex_execution_count", 0) or 0)
        execution_count += child_execution_count
        transient_requeue_total += int(payload.get("codex_transient_requeue_count", 0) or 0)
        worker_id = str(payload.get("worker_id") or payload.get("codex_scope") or path.stem)
        heartbeat_age = 0.0
        if payload.get("heartbeat_at"):
            try:
                heartbeat_age = max(0.0, now - parse_utc(str(payload.get("heartbeat_at"))))
            except Exception:
                heartbeat_age = 0.0
        stale = heartbeat_age > float(codex_worker_stale_seconds)
        if payload.get("active_packet_claimed_todo_ids") or payload.get("active_packet_phase"):
            active += 1
        elif str(payload.get("latest_stop_reason") or "") == "waiting_for_program_synthesis_todos":
            waiting += 1
            if stale:
                idle_stale += 1
                stale_idle_worker_ids.append(worker_id)
        elif str(payload.get("latest_stop_reason") or "") == "claimed_program_synthesis_todos":
            if stale:
                stale_claimed_worker_ids.append(worker_id)
    pending = int(status.get("pending", 0) or 0)
    claimed = int(status.get("claimed", 0) or 0)
    failed_validation = int(status.get("failed_validation", 0) or 0)
    superseded = int(status.get("superseded", 0) or 0)
    transient_attempt_count = max(
        int(transient_counts.get("transient_attempt_count", 0)),
        int(transient_requeue_total),
    )
    transient_todo_count = int(transient_counts.get("transient_todo_count", 0))
    active_transient_attempt_count = int(
        active_transient_counts.get("transient_attempt_count", 0)
    )
    active_transient_todo_count = int(
        active_transient_counts.get("transient_todo_count", 0)
    )
    transient_failure_rate = (
        float(transient_attempt_count) / float(execution_count)
        if execution_count > 0
        else queue.transient_failure_rate(optimizer_role="program_synthesis")
    )
    starved = pending == 0 and claimed == 0 and waiting > 0
    drained = pending == 0 and claimed == 0 and failed_validation == 0
    executor_available = summary_count > 0 and len(stale_claimed_worker_ids) < summary_count
    executor_throttled = bool(transient_failure_rate >= 0.5 and transient_attempt_count > 0)
    return {
        "codex_claimed_total": claimed_total,
        "codex_execution_count": execution_count,
        "codex_idle_worker_stale_count": idle_stale,
        "codex_queue_starved": starved,
        "codex_queue_drained": drained,
        "codex_worker_summary_count": summary_count,
        "codex_worker_stale_count": len(stale_claimed_worker_ids),
        "codex_workers_active_packet_count": active,
        "codex_workers_waiting_for_todos_count": waiting,
        "codex_executor_available": executor_available,
        "codex_executor_throttled": executor_throttled,
        "codex_transient_requeue_count": transient_attempt_count,
        "codex_transient_failure_rate": round(transient_failure_rate, 6),
        "codex_active_transient_failure_count": active_transient_attempt_count,
        "program_synthesis_claimed": claimed,
        "program_synthesis_claimed_by_worker": dict(claimed_by_worker),
        "program_synthesis_completed": int(status.get("completed", 0) or 0),
        "program_synthesis_failed_validation": failed_validation,
        "program_synthesis_failed_validation_kind_counts": dict(failed_kind_counts),
        "program_synthesis_failed_validation_reason_counts": dict(failed_reason_counts),
        "program_synthesis_failed_validation_test_counts": dict(failed_test_counts),
        "program_synthesis_pending": pending,
        "program_synthesis_superseded": superseded,
        "program_synthesis_transient_failure_count": transient_todo_count,
        "program_synthesis_transient_failure_attempts": transient_attempt_count,
        "program_synthesis_transient_failure_rate": round(transient_failure_rate, 6),
        "program_synthesis_active_transient_failure_attempts": (
            active_transient_attempt_count
        ),
        "program_synthesis_active_transient_failure_count": (
            active_transient_todo_count
        ),
        "queue_exists": queue_exists,
        "stale_claimed_codex_worker_ids": stale_claimed_worker_ids,
        "stale_idle_codex_worker_ids": stale_idle_worker_ids,
    }


def _program_synthesis_queue_pressure(
    health: Mapping[str, Any],
    *,
    pending_cap: int,
) -> float:
    cap = max(0, int(pending_cap or 0))
    pending = int(health.get("program_synthesis_pending", 0) or 0)
    return (float(pending) / float(cap)) if cap > 0 else 0.0


def _paired_failed_validation_rescue_should_seed(
    health: Mapping[str, Any],
    *,
    mode: str,
    last_seed_at: float,
    interval_seconds: float,
    now: float,
    backlog_threshold: int = 16,
) -> bool:
    if str(mode or "auto").strip().lower() in {"off", "none", "false"}:
        return False
    if not bool(health.get("queue_exists", False)):
        return False
    if float(now) - float(last_seed_at) < float(interval_seconds):
        return False
    failed = int(health.get("program_synthesis_failed_validation", 0) or 0)
    pending = int(health.get("program_synthesis_pending", 0) or 0)
    claimed = int(health.get("program_synthesis_claimed", 0) or 0)
    if failed <= 0:
        return False
    normalized_mode = str(mode or "auto").strip().lower()
    if normalized_mode == "starved" and not bool(health.get("codex_queue_starved")):
        return False
    if bool(health.get("codex_queue_starved")):
        return pending == 0 and claimed == 0
    waiting = int(health.get("codex_workers_waiting_for_todos_count", 0) or 0)
    active = int(health.get("codex_workers_active_packet_count", 0) or 0)
    if pending == 0:
        return True
    if claimed > 0 and waiting > 0:
        return True
    if active > 0 and failed >= int(backlog_threshold):
        return True
    return failed >= int(backlog_threshold)


def seed_failed_validation_rescue_todos_for_queue(
    *,
    queue_path: Path,
    max_clusters: int = 8,
    policy: Optional[ModalOptimizerPolicy] = None,
) -> Dict[str, Any]:
    """Seed rescue TODOs for failed validation rows in a queue file."""

    active_policy = policy or ModalOptimizerPolicy()
    with queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
        before = queue.status_counts()
        supervisor = ModalTodoSupervisor(queue=queue, policy=active_policy)
        rescue_todos = supervisor.seed_failed_validation_rescue_todos(
            max_clusters=max_clusters,
        )
        after = queue.status_counts()
        queue.save_jsonl(queue_path)
    superseded_count = int(supervisor.last_failed_validation_superseded_count)
    seeded_ids = [todo.todo_id for todo in rescue_todos]
    deduped_count = int(supervisor.last_program_synthesis_deduped_count)
    report: Dict[str, Any] = {
        "after": after,
        "before": before,
        "deduped_count": deduped_count,
        "max_clusters": int(max_clusters),
        "queue_path": str(queue_path),
        "seeded_count": len(seeded_ids),
        "seeded_todo_ids": seeded_ids,
        "superseded_count": superseded_count,
    }
    if superseded_count and not seeded_ids:
        report["reason"] = "resolved_by_completed_rescue"
    elif deduped_count and not seeded_ids:
        report["reason"] = "duplicate_rescue_already_pending"
    elif seeded_ids:
        report["reason"] = "seeded_failed_validation_rescue"
    else:
        report["reason"] = "no_failed_validation_rescue_needed"
    return report


def persist_supervisor_queue_for_external_workers(
    *,
    queue_path: Path,
    supervisor: ModalTodoSupervisor,
) -> Dict[str, Any]:
    """Flush in-memory supervisor TODOs to the JSONL queue Codex workers read."""

    with queue_file_lock(queue_path):
        latest_queue = ModalTodoQueue.load_jsonl(queue_path)
        before = latest_queue.status_counts()
        latest_queue.merge_from(
            supervisor.queue,
            preserve_claimed_role=supervisor.policy.program_synthesis_role,
        )
        semantic_deduped_count = latest_queue.deduplicate_semantic(
            optimizer_role=supervisor.policy.program_synthesis_role,
            near_duplicate_jaccard=(
                supervisor.policy.program_synthesis_near_duplicate_jaccard
            ),
        )
        latest_queue.save_jsonl(queue_path)
        supervisor.queue = latest_queue
        after = latest_queue.status_counts()
        role_after = latest_queue.role_status_counts()
    return {
        "after": after,
        "before": before,
        "queue_path": str(queue_path),
        "role_after": role_after,
        "semantic_deduped_count": int(semantic_deduped_count),
    }


def _codex_main_apply_backpressure_report(
    queue: ModalTodoQueue,
    *,
    args: argparse.Namespace,
    policy: ModalOptimizerPolicy,
    worker_id: str,
) -> Dict[str, Any]:
    """Return whether apply-to-main should serialize new packet claims."""

    apply_mode = str(getattr(args, "codex_apply_mode", "patch_only") or "patch_only")
    max_inflight = int(getattr(args, "codex_main_apply_max_inflight_packets", 0) or 0)
    pending = queue.pending(optimizer_role=policy.program_synthesis_role)
    claimed = queue.claimed(optimizer_role=policy.program_synthesis_role)
    active = [
        todo
        for todo in claimed
        if str(todo.claimed_by or "") and str(todo.claimed_by or "") != str(worker_id)
    ]
    active_workers = sorted(
        dict.fromkeys(str(todo.claimed_by) for todo in active if todo.claimed_by)
    )
    enabled = apply_mode == "apply_to_main" and max_inflight > 0
    blocked = bool(enabled and len(active) >= max_inflight and pending)
    reason = "main_apply_inflight_limit_reached" if blocked else ""
    if not enabled:
        reason = "main_apply_backpressure_disabled"
    elif not pending:
        reason = "no_pending_program_synthesis_todos"
    elif not blocked:
        reason = "main_apply_inflight_capacity_available"
    return {
        "active_packet_count": len(active),
        "active_workers": active_workers,
        "blocked": blocked,
        "max_inflight_packets": max_inflight,
        "pending_count": len(pending),
        "reason": reason,
    }


def rollout_baseline_snapshot(
    *,
    summary: Mapping[str, Any],
    cycle: int,
    cycle_seconds: float,
    cycle_phase_timings: Mapping[str, float],
    validation_metrics: Mapping[str, Any],
    compiler_ir_validation: Mapping[str, Any],
    compiler_ir_guided_validation: Optional[Mapping[str, Any]] = None,
    learned_ir_validation: Optional[Mapping[str, Any]] = None,
    logic_bridge_validation: Optional[Mapping[str, Any]] = None,
    queue_counts: Optional[Mapping[str, int]] = None,
    role_queue_counts: Optional[Mapping[str, Any]] = None,
    failed_validation_count: int = 0,
    state_report: Optional[Mapping[str, Any]] = None,
    state_telemetry: Optional[Mapping[str, Any]] = None,
    embedding_report: Optional[Mapping[str, Any]] = None,
    backend_metadata: Optional[Mapping[str, Any]] = None,
    host_resource_health: Optional[Mapping[str, Any]] = None,
    metric_bridge_adapters: Sequence[str] = (),
    diagnostic_bridge_adapters: Sequence[str] = (),
) -> Dict[str, Any]:
    state_payload = dict(state_report or state_telemetry or {})
    guided_validation = dict(compiler_ir_guided_validation or {})
    learned_payload = dict(learned_ir_validation or {})
    bridge_payload = dict(logic_bridge_validation or {})
    validation_payload = dict(validation_metrics or {})
    compiler_payload = dict(compiler_ir_validation or {})
    signal_health = autoencoder_validation_signal_health(
        compiler_ir_validation=compiler_payload,
        learned_ir_validation=learned_payload,
        logic_bridge_validation=bridge_payload,
        validation_metrics=validation_payload,
        metric_bridge_adapters=metric_bridge_adapters,
        diagnostic_bridge_adapters=diagnostic_bridge_adapters,
    )
    resolved_failed_validation_count = int(
        failed_validation_count
        or dict(queue_counts or {}).get("failed_validation", 0)
        or 0
    )
    return {
        "backend": dict(backend_metadata or {}),
        "compiler_ir_metric_cache": {
            "validation_sample_cache_hits": compiler_payload.get(
                "persistent_sample_cache_hits",
                0,
            ),
            "validation_sample_cache_misses": compiler_payload.get(
                "persistent_sample_cache_misses",
                0,
            ),
            "guided_validation_block_cache_hit": compiler_payload.get(
                "persistent_cache_hit",
                guided_validation.get("persistent_cache_hit", False),
            ),
        },
        "compiler_ir_guided_validation": guided_validation,
        "compiler_ir_validation": compiler_payload,
        "cycle": int(cycle),
        "cycle_phase_timings": dict(cycle_phase_timings),
        "cycle_seconds": round(float(cycle_seconds), 3),
        "embedding": dict(embedding_report or {}),
        "failed_validation_count": resolved_failed_validation_count,
        "host_resource_health": dict(host_resource_health or {}),
        "learned_feature_rows": state_payload,
        "learned_ir_view_validation": learned_payload,
        "logic_bridge_validation": bridge_payload,
        "metric_schema_version": summary.get("metric_schema_version"),
        "queue_counts": dict(queue_counts or {}),
        "role_queue_counts": dict(role_queue_counts or {}),
        "run_id": summary.get("run_id"),
        "signal_health": signal_health,
        "state_file": dict(state_payload.get("state_file", {}) or {}),
        "validation": dict(validation_metrics),
    }


def _sample_payloads_for_codex_metrics(
    samples: Sequence[Any],
    *,
    max_samples: int = 8,
) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for sample in list(samples)[: max(0, int(max_samples))]:
        payloads.append(
            {
                "citation": str(getattr(sample, "citation", "") or ""),
                "embedding_model": str(getattr(sample, "embedding_model", "") or ""),
                "embedding_vector": [
                    float(value)
                    for value in list(getattr(sample, "embedding_vector", []) or [])
                ],
                "sample_id": str(getattr(sample, "sample_id", "") or ""),
                "section": str(getattr(sample, "section", "") or ""),
                "source": str(getattr(sample, "source", "") or ""),
                "text": str(getattr(sample, "text", "") or ""),
                "title": str(getattr(sample, "title", "") or ""),
            }
        )
    return payloads


def _bootstrap_target_metrics_for_scope(scope: str) -> List[str]:
    scope_metrics = {
        "bridge": ["legal_ir_multiview_total_loss", "legal_ir_view_cross_entropy_loss"],
        "cec": ["cec_dcec_validation_failure_ratio"],
        "compiler_ambiguity": ["cross_entropy_loss"],
        "compiler_parser": ["symbolic_validity_penalty", "modal_span_coverage_loss"],
        "compiler_registry": ["cross_entropy_loss"],
        "deontic": ["deontic_decoder_slot_loss", "legal_ir_multiview_total_loss"],
        "external_provers": ["legal_ir_multiview_proof_failure_ratio"],
        "frame_logic": ["flogic_similarity_loss", "ontology_violation_count"],
        "ir_decompiler": [
            "embedding_cosine_similarity",
            "source_copy_reward_hack_penalty",
            "text_reconstruction_loss",
        ],
        "knowledge_graphs": ["legal_ir_multiview_graph_failure_penalty"],
        "tdfol": ["tdfol_parse_failure_ratio"],
        "zkp": ["zkp_verification_failure_ratio"],
    }
    return list(scope_metrics.get(scope, ["cross_entropy_loss"]))


def fast_program_synthesis_bootstrap_todos(
    samples: Sequence[Any],
    *,
    policy: Optional[ModalOptimizerPolicy] = None,
    cycle: int = 0,
) -> List[ModalTodo]:
    """Seed parallel Codex scopes before enough residual clusters accumulate."""

    resolved_policy = policy or ModalOptimizerPolicy()
    sample_list = list(samples)
    sample_ids = [
        str(getattr(sample, "sample_id", "") or "")
        for sample in sample_list
        if str(getattr(sample, "sample_id", "") or "")
    ]
    citations = [
        str(getattr(sample, "citation", "") or "")
        for sample in sample_list
        if str(getattr(sample, "citation", "") or "")
    ]
    metric_payloads = _sample_payloads_for_codex_metrics(sample_list)
    scope_actions = {
        "bridge": ("repair_multiview_legal_ir_loss", "bridge.contracts"),
        "cec": ("repair_cec_dcec_bridge", "CEC.native"),
        "compiler_ambiguity": (
            "add_or_review_modal_ambiguity_policy",
            "modal.compiler.ambiguity",
        ),
        "compiler_parser": ("add_deterministic_parser_rule", "modal.compiler"),
        "compiler_registry": ("refine_modal_family_cue_rules", "modal.compiler.registry"),
        "deontic": ("repair_deontic_bridge_quality_gate", "deontic.ir"),
        "external_provers": ("repair_external_prover_router", "external_provers.router"),
        "frame_logic": ("improve_flogic_frame_alignment", "modal.frame_logic"),
        "ir_decompiler": (
            "refine_semantic_decompiler_reconstruction",
            "modal.ir_decompiler",
        ),
        "knowledge_graphs": (
            "repair_multiview_legal_ir_graph_projection",
            "knowledge_graphs.neo4j_compat",
        ),
        "tdfol": ("repair_tdfol_bridge_parse", "TDFOL.prover"),
        "zkp": ("repair_zkp_attestation_bridge", "zkp.circuits"),
    }
    todos: List[ModalTodo] = []
    for scope, (action, target_component) in sorted(scope_actions.items()):
        signature_payload = {
            "cycle": int(cycle),
            "sample_ids": sample_ids,
            "scope": scope,
            "source": "modal_program_synthesis_fast_bootstrap_v1",
            "target_component": target_component,
        }
        signature = hashlib.sha256(
            _stable_metric_json(signature_payload).encode("utf-8")
        ).hexdigest()
        metadata = {
            **resolved_policy.metadata_for(
                action=action,
                loss_name="program_synthesis_bootstrap",
            ),
            "dedupe_signature": f"fast-bootstrap:{scope}:{signature}",
            "hint_evidence": [
                {
                    "cycle": int(cycle),
                    "evidence_kind": "fast_bootstrap_scope",
                    "scope": scope,
                    "target_component": target_component,
                }
            ],
            "metric_sample_payloads": metric_payloads,
            "program_synthesis_scope": scope,
            "semantic_bundle_key": f"fast-bootstrap:{scope}:{signature}",
            "source": "modal_program_synthesis_fast_bootstrap_v1",
            "support_count": len(sample_list),
            "target_component": target_component,
            "target_metrics": _bootstrap_target_metrics_for_scope(scope),
            "validation_commands": [
                f"{sys.executable} -m pytest -q tests/unit/optimizers/logic_theorem_optimizer/test_modal_todo_daemon.py"
            ],
        }
        todos.append(
            ModalTodo(
                todo_id=f"program-synthesis-fast-bootstrap-{scope}-{signature[:16]}",
                action=action,
                objective=(
                    "Bootstrap deterministic legal IR compiler/decompiler repairs "
                    f"for the {scope} scope."
                ),
                sample_ids=sample_ids,
                citations=citations,
                loss_name="program_synthesis_bootstrap",
                loss_value=1.0,
                priority=round(100.0 + len(sample_list), 6),
                metadata=metadata,
            )
        )
    return todos


def _hammer_projection_unique_strings(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray, str)):
        raw_values = values
    else:
        raw_values = [values]
    return list(dict.fromkeys(str(value).strip() for value in raw_values if str(value).strip()))


def _hammer_projection_normalize_item(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            value = value.to_dict()
        except (TypeError, ValueError):
            return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in dict(value).items()}
    return {}


def _hammer_projection_items(value: Any) -> List[Mapping[str, Any]]:
    normalized = _hammer_projection_normalize_item(value)
    if normalized:
        nested: List[Mapping[str, Any]] = []
        for key in (
            "artifacts",
            "hammer_guidance_artifacts",
            "verified_guidance",
            "guidance_items",
            "items",
        ):
            if key in normalized:
                nested.extend(_hammer_projection_items(normalized.get(key)))
        candidate_results = normalized.get("candidate_results")
        if isinstance(candidate_results, Sequence) and not isinstance(
            candidate_results,
            (bytes, bytearray, str),
        ):
            for candidate_result in candidate_results:
                if not isinstance(candidate_result, Mapping):
                    continue
                nested.extend(_hammer_projection_items(candidate_result.get("verified_guidance")))
                nested.extend(
                    _hammer_projection_items(
                        candidate_result.get("hammer_guidance_artifacts")
                    )
                )
                hammer_report = candidate_result.get("hammer_report")
                if isinstance(hammer_report, Mapping):
                    nested.extend(_hammer_projection_items(hammer_report.get("artifacts")))
        if nested:
            return nested
        if _hammer_projection_is_hammer_item(normalized):
            return [normalized]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        items: List[Mapping[str, Any]] = []
        for item in value:
            items.extend(_hammer_projection_items(item))
        return items
    return []


def _hammer_projection_is_hammer_item(item: Mapping[str, Any]) -> bool:
    schema_version = str(item.get("schema_version") or "").strip().lower()
    source = str(item.get("source") or "").strip().lower()
    return (
        schema_version.startswith("legal-ir-hammer-")
        or source == "hammer_verified_guidance"
        or bool(item.get("backend_statuses"))
        or "proved" in item
        or "proof_checked" in item
    )


def _hammer_projection_metadata(item: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = item.get("metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _hammer_projection_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "verified"}


def _hammer_projection_failure_reason(item: Mapping[str, Any]) -> str:
    rejection_reasons = _hammer_projection_unique_strings(item.get("rejection_reasons"))
    if any("copy" in reason.lower() for reason in rejection_reasons):
        return "source_copy_rejected"
    failure_reason = str(item.get("failure_reason") or "").strip()
    if failure_reason:
        return re.sub(r"[^a-z0-9_]+", "_", failure_reason.lower()).strip("_")
    reconstruction_status = str(item.get("reconstruction_status") or "").strip().lower()
    if _hammer_projection_truthy(item.get("proved")) and reconstruction_status not in {
        "",
        "checked",
        "proof_checked",
        "reconstructed",
        "success",
        "verified",
    }:
        return "reconstruction_failed"
    backend_statuses = item.get("backend_statuses")
    if isinstance(backend_statuses, Mapping):
        statuses = [
            str(status).strip().lower()
            for status in backend_statuses.values()
            if str(status).strip()
        ]
        if statuses and all(status == "unavailable" for status in statuses):
            return "backend_unavailable"
    if not _hammer_projection_truthy(item.get("proved")):
        return "hammer_unproved"
    if not _hammer_projection_truthy(item.get("trusted")):
        return "untrusted_hammer_guidance"
    return ""


def _hammer_projection_route_for_view(view: str) -> tuple[str, str]:
    normalized = str(view or "").lower()
    if "deontic" in normalized:
        return "repair_deontic_bridge_quality_gate", "deontic.ir"
    if "tdfol" in normalized or "fol" in normalized:
        return "repair_tdfol_bridge_parse", "TDFOL.prover"
    if "cec" in normalized or "event" in normalized:
        return "repair_cec_dcec_bridge", "CEC.native"
    if "knowledge_graph" in normalized or "neo4j" in normalized or "kg" in normalized:
        return "repair_multiview_legal_ir_graph_projection", "knowledge_graphs.neo4j_compat"
    if "external" in normalized or "prover" in normalized:
        return "repair_external_prover_router", "external_provers.router"
    return "repair_flogic_ontology_constraints", "modal.frame_logic"


def _hammer_projection_scope_for_target(target_component: str) -> str:
    scope = str(logic_optimizer_scope_for_component(target_component) or "").strip()
    if scope:
        return scope
    normalized = str(target_component or "").lower()
    if "deontic" in normalized:
        return "deontic"
    if "tdfol" in normalized or "fol" in normalized:
        return "tdfol"
    if "cec" in normalized:
        return "cec"
    if "knowledge_graph" in normalized or "neo4j" in normalized:
        return "knowledge_graphs"
    if "external" in normalized or "prover" in normalized:
        return "external_provers"
    if "decompiler" in normalized:
        return "ir_decompiler"
    return "frame_logic"


def _hammer_projection_allowed_paths(
    *,
    action: str,
    target_component: str,
) -> List[str]:
    paths = [
        *CODEX_TARGET_FILE_HINTS.get(target_component, []),
        *CODEX_ACTION_FILE_HINTS.get(action, []),
    ]
    return _hammer_projection_unique_strings(paths)[:8]


def _hammer_projection_todo_id(dedupe_signature: str) -> str:
    digest = hashlib.sha256(str(dedupe_signature or "").encode("utf-8")).hexdigest()
    return f"hammer-failure-{digest[:20]}"


def _hammer_projection_target_metrics(
    *,
    action: str,
    failure_reason: str,
    scope: str,
    target_component: str,
) -> List[str]:
    metrics = [
        "hammer_proof_success_rate",
        "hammer_proof_failure_ratio",
        "hammer_reconstruction_success_rate",
        "symbolic_validity_penalty",
    ]
    if failure_reason == "source_copy_rejected":
        metrics.extend(["hammer_source_copy_penalty", "source_copy_penalty"])
    if target_component == "knowledge_graphs.neo4j_compat":
        metrics.append("legal_ir_multiview_graph_failure_penalty")
    if target_component == "external_provers.router":
        metrics.append("legal_ir_multiview_proof_failure_ratio")
    metrics.extend(_compiler_guidance_target_metrics(action, scope))
    return _hammer_projection_unique_strings(metrics)


def hammer_failure_projection_todos(
    guidance: Any,
    *,
    policy: Optional[ModalOptimizerPolicy] = None,
    min_support: int = 2,
    max_todos_per_cycle: int = 5,
    max_todos_per_scope: int = 2,
) -> List[ModalTodo]:
    """Create bounded Codex TODOs from repeated hammer-verified failures."""

    resolved_policy = policy or ModalOptimizerPolicy()
    groups: Dict[tuple[str, str, str], List[Mapping[str, Any]]] = {}
    for item in _hammer_projection_items(guidance):
        reason = _hammer_projection_failure_reason(item)
        if not reason:
            continue
        metadata = _hammer_projection_metadata(item)
        view = str(
            item.get("legal_ir_view")
            or item.get("target_view")
            or item.get("target_component")
            or metadata.get("legal_ir_view")
            or "modal.frame_logic"
        ).strip()
        obligation_kind = str(
            item.get("obligation_kind")
            or metadata.get("obligation_kind")
            or item.get("logic_family")
            or "legal_ir_obligation"
        ).strip()
        action, target_component = _hammer_projection_route_for_view(view)
        scope = _hammer_projection_scope_for_target(target_component)
        groups.setdefault((scope, reason, obligation_kind), []).append(item)

    todos: List[ModalTodo] = []
    scope_counts: Counter[str] = Counter()
    for (scope, reason, obligation_kind), items in sorted(
        groups.items(),
        key=lambda entry: (-len(entry[1]), entry[0]),
    ):
        support_count = len(items)
        if support_count < max(1, int(min_support)):
            continue
        if len(todos) >= max(0, int(max_todos_per_cycle)):
            break
        if scope_counts[scope] >= max(1, int(max_todos_per_scope)):
            continue
        representative = items[0]
        view = str(
            representative.get("legal_ir_view")
            or representative.get("target_view")
            or representative.get("target_component")
            or "modal.frame_logic"
        ).strip()
        action, target_component = _hammer_projection_route_for_view(view)
        allowed_paths = _hammer_projection_allowed_paths(
            action=action,
            target_component=target_component,
        )
        if not allowed_paths:
            continue
        sample_ids = _hammer_projection_unique_strings(
            [
                item.get("sample_id") or _hammer_projection_metadata(item).get("sample_id")
                for item in items
            ]
        )
        citations = _hammer_projection_unique_strings(
            [
                item.get("citation") or _hammer_projection_metadata(item).get("citation")
                for item in items
            ]
        )
        proof_obligation_ids = _hammer_projection_unique_strings(
            [
                proof_id
                for item in items
                for proof_id in _hammer_projection_unique_strings(
                    item.get("proof_obligation_ids") or item.get("obligation_id")
                )
            ]
        )
        failure_examples = [
            {
                "failure_reason": reason,
                "guidance_id": str(item.get("guidance_id") or ""),
                "legal_ir_view": str(
                    item.get("legal_ir_view")
                    or item.get("target_view")
                    or item.get("target_component")
                    or ""
                ),
                "obligation_id": str(item.get("obligation_id") or ""),
                "reconstruction_status": str(item.get("reconstruction_status") or ""),
                "sample_id": str(
                    item.get("sample_id")
                    or _hammer_projection_metadata(item).get("sample_id")
                    or ""
                ),
                "winner_backend": str(item.get("winner_backend") or ""),
            }
            for item in items[:8]
        ]
        dedupe_payload = {
            "obligation_kind": obligation_kind,
            "reason": reason,
            "scope": scope,
            "source": "hammer_failure_projection_v1",
            "target_component": target_component,
        }
        dedupe_signature = "hammer-failure:" + hashlib.sha256(
            json.dumps(dedupe_payload, ensure_ascii=True, sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        target_metrics = _hammer_projection_target_metrics(
            action=action,
            failure_reason=reason,
            scope=scope,
            target_component=target_component,
        )
        validation_commands = _compiler_guidance_validation_commands(scope)
        validation_commands = _hammer_projection_unique_strings(
            [
                *validation_commands,
                (
                    f"{sys.executable} -m pytest -q "
                    "tests/unit/logic/integration/test_legal_ir_hammer_pipeline.py"
                ),
            ]
        )
        metadata = {
            **resolved_policy.metadata_for(
                action=action,
                loss_name="hammer_verified_failure",
            ),
            "allowed_paths": allowed_paths,
            "dedupe_signature": dedupe_signature,
            "expected_failure_mode": reason,
            "failure_reason": reason,
            "hammer_failure_examples": failure_examples,
            "hammer_failure_group_key": f"{scope}:{reason}:{obligation_kind}",
            "hammer_projection": True,
            "leanstral_projection": True,
            "owned_ast_scope": scope,
            "program_synthesis_scope": scope,
            "proof_obligation_ids": proof_obligation_ids,
            "semantic_bundle_key": dedupe_signature,
            "source": "hammer_failure_projection_v1",
            "support_count": support_count,
            "target_component": target_component,
            "target_metrics": target_metrics,
            "validation_commands": validation_commands,
            "validation_set": {
                "allowed_paths": allowed_paths,
                "expected_failure_mode": reason,
                "held_out_compiler_ir_metrics": target_metrics,
                "proof_obligation_ids": proof_obligation_ids,
                "target_file_lane": scope,
            },
        }
        todos.append(
            ModalTodo(
                todo_id=_hammer_projection_todo_id(dedupe_signature),
                action=action,
                objective=(
                    "Repair repeated hammer-verified Legal IR failure "
                    f"{reason!r} for {target_component} obligations."
                ),
                sample_ids=sample_ids,
                citations=citations,
                loss_name="hammer_verified_failure",
                loss_value=round(float(support_count), 12),
                priority=round(80.0 + float(support_count), 6),
                metadata=metadata,
            )
        )
        scope_counts[scope] += 1
    return todos


def _metric_value(block: Mapping[str, Any], name: str, default: float = 1.0e12) -> float:
    try:
        value = float(block.get(name, default))
    except (TypeError, ValueError):
        return default
    if value != value:
        return default
    return value


def _compiler_guidance_record_metric(
    record: Mapping[str, Any],
    name: str,
    default: float = 1.0e12,
) -> float:
    metrics = record.get("metrics")
    if isinstance(metrics, Mapping):
        return _metric_value(metrics, name, default)
    return _metric_value(record, name, default)


def _compiler_guidance_delta_quality_gate(
    *,
    ce_delta: float,
    copy_hack_delta: float,
    cosine_delta: float,
    threshold: float,
) -> str:
    core_deltas = (ce_delta, copy_hack_delta, cosine_delta)
    if any(delta < -threshold for delta in core_deltas):
        return "fail"
    if any(delta > threshold for delta in core_deltas):
        return "pass"
    return "warn"


def _compiler_guidance_mean_delta_block(
    deltas: Sequence[Mapping[str, float]],
    *,
    threshold: float,
) -> Dict[str, Any]:
    if not deltas:
        return {
            "ce_delta": 0.0,
            "copy_hack_delta": 0.0,
            "cosine_delta": 0.0,
            "count": 0,
            "quality_gate": "inactive",
        }
    ce_delta = _mean([float(delta.get("ce_delta", 0.0)) for delta in deltas])
    copy_hack_delta = _mean(
        [float(delta.get("copy_hack_delta", 0.0)) for delta in deltas]
    )
    cosine_delta = _mean(
        [float(delta.get("cosine_delta", 0.0)) for delta in deltas]
    )
    return {
        "ce_delta": ce_delta,
        "copy_hack_delta": copy_hack_delta,
        "cosine_delta": cosine_delta,
        "count": len(deltas),
        "quality_gate": _compiler_guidance_delta_quality_gate(
            ce_delta=ce_delta,
            copy_hack_delta=copy_hack_delta,
            cosine_delta=cosine_delta,
            threshold=threshold,
        ),
    }


def _compiler_guidance_canary_attribution(
    deterministic_block: Mapping[str, Any],
    guided_block: Mapping[str, Any],
    *,
    threshold: float,
) -> Dict[str, Any]:
    deterministic_records = deterministic_block.get("sample_metric_records")
    guided_records = guided_block.get("sample_metric_records")
    if not isinstance(deterministic_records, Sequence) or isinstance(
        deterministic_records,
        (str, bytes),
    ):
        deterministic_records = []
    if not isinstance(guided_records, Sequence) or isinstance(
        guided_records,
        (str, bytes),
    ):
        guided_records = []
    deterministic_by_sample = {
        str(record.get("sample_id") or ""): record
        for record in deterministic_records
        if isinstance(record, Mapping) and str(record.get("sample_id") or "")
    }
    buckets: Dict[str, Dict[str, List[Dict[str, float]]]] = {
        "legal_ir_view_family_gaps": {},
        "legal_ir_view_gaps": {},
        "semantic_overlay_terms": {},
        "todo_routes": {},
    }
    matched_sample_count = 0
    for guided_record in guided_records:
        if not isinstance(guided_record, Mapping):
            continue
        sample_id = str(guided_record.get("sample_id") or "")
        deterministic_record = deterministic_by_sample.get(sample_id)
        if deterministic_record is None:
            continue
        matched_sample_count += 1
        delta = {
            "ce_delta": _compiler_guidance_record_metric(
                deterministic_record,
                "cross_entropy_loss",
            )
            - _compiler_guidance_record_metric(guided_record, "cross_entropy_loss"),
            "copy_hack_delta": _compiler_guidance_record_metric(
                deterministic_record,
                "source_copy_reward_hack_penalty",
            )
            - _compiler_guidance_record_metric(
                guided_record,
                "source_copy_reward_hack_penalty",
            ),
            "cosine_delta": _compiler_guidance_record_metric(
                guided_record,
                "cosine_similarity",
                -1.0,
            )
            - _compiler_guidance_record_metric(
                deterministic_record,
                "cosine_similarity",
                -1.0,
            ),
        }
        for output_name, record_key in (
            (
                "legal_ir_view_family_gaps",
                "compiler_guidance_legal_ir_view_family_gaps",
            ),
            ("legal_ir_view_gaps", "compiler_guidance_legal_ir_view_gaps"),
            ("semantic_overlay_terms", "compiler_guidance_semantic_overlay_terms"),
            ("todo_routes", "compiler_guidance_todo_routes"),
        ):
            values = guided_record.get(record_key)
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                values = []
            for value in values:
                key = str(value or "").strip()
                if not key:
                    continue
                buckets[output_name].setdefault(key, []).append(dict(delta))
    attribution: Dict[str, Any] = {
        "basis": "sample_records",
        "matched_sample_count": matched_sample_count,
    }
    for output_name, output_buckets in buckets.items():
        attribution[output_name] = {
            key: _compiler_guidance_mean_delta_block(deltas, threshold=threshold)
            for key, deltas in sorted(output_buckets.items())
        }
    return attribution


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
    attribution = _compiler_guidance_canary_attribution(
        deterministic_block,
        guided_block,
        threshold=threshold,
    )
    return {
        "applied_count": applied_count,
        "attribution": attribution,
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
    top_surface_features: Mapping[str, Any],
    limit: int = 8,
) -> Dict[str, float]:
    """Infer deterministic repair routes when guidance has features but no route."""
    route_counts: Counter[str] = Counter()
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


def _compiler_guidance_legal_ir_view_gap_route(gap_name: str) -> str:
    normalized = _normalized_guidance_route(gap_name)
    if "deontic" in normalized:
        return "repair_deontic_bridge_quality_gate"
    if "frame" in normalized or "flogic" in normalized:
        return "repair_flogic_ontology_constraints"
    if "tdfol" in normalized or "first_order" in normalized:
        return "repair_tdfol_bridge_parse"
    if "cec" in normalized or "event_calculus" in normalized:
        return "repair_cec_dcec_bridge"
    if "knowledge_graph" in normalized or normalized.startswith("kg_"):
        return "repair_multiview_legal_ir_graph_projection"
    if "prover" in normalized:
        return "repair_external_prover_router"
    if "zkp" in normalized or "zero_knowledge" in normalized:
        return "repair_zkp_attestation_bridge"
    return "repair_multiview_legal_ir_loss"


def _compiler_guidance_todo_routes_from_legal_ir_view_gaps(
    view_gaps: Mapping[str, Any],
    *,
    limit: int = 8,
) -> Dict[str, float]:
    route_counts: Counter[str] = Counter()
    for gap_name, count in _top_numeric_items(view_gaps, limit=32).items():
        route_counts[_compiler_guidance_legal_ir_view_gap_route(gap_name)] += float(
            count
        )
    return _top_numeric_items(route_counts, limit=limit)


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
        legal_ir_view_gaps = guided_block.get("compiler_guidance_legal_ir_view_gaps")
        legal_ir_view_family_gaps = guided_block.get(
            "compiler_guidance_legal_ir_view_family_gaps"
        )
        route_view_gaps: Mapping[str, Any] = {}
        if isinstance(legal_ir_view_gaps, Mapping) and legal_ir_view_gaps:
            route_view_gaps = legal_ir_view_gaps
        elif isinstance(legal_ir_view_family_gaps, Mapping):
            route_view_gaps = legal_ir_view_family_gaps
        if route_view_gaps:
            todo_routes = _compiler_guidance_todo_routes_from_legal_ir_view_gaps(
                route_view_gaps,
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


def _compiler_guidance_attribution_summary(
    attribution: Mapping[str, Any],
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "basis": str(attribution.get("basis") or ""),
        "matched_sample_count": int(attribution.get("matched_sample_count", 0) or 0),
    }
    for group_name in (
        "legal_ir_view_family_gaps",
        "legal_ir_view_gaps",
        "semantic_overlay_terms",
        "todo_routes",
    ):
        group = attribution.get(group_name)
        if not isinstance(group, Mapping):
            continue
        for gate in ("pass", "warn", "fail"):
            keys = [
                str(key)
                for key, block in sorted(group.items())
                if isinstance(block, Mapping)
                and str(block.get("quality_gate") or "") == gate
            ]
            if keys:
                summary[f"{gate}_{group_name}"] = keys
    return summary


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
    legal_ir_view_family_gaps = guided_block.get(
        "compiler_guidance_legal_ir_view_family_gaps"
    )
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
    top_legal_ir_view_family_gaps = _top_numeric_items(
        legal_ir_view_family_gaps
        if isinstance(legal_ir_view_family_gaps, Mapping)
        else {},
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
    legal_ir_view_gap_todo_routes = _compiler_guidance_todo_routes_from_legal_ir_view_gaps(
        top_legal_ir_view_gaps or top_legal_ir_view_family_gaps,
        limit=max_items,
    )
    fallback_todo_routes = _compiler_guidance_fallback_todo_routes(
        top_feature_groups=top_feature_groups,
        top_surface_features=top_surface_features,
        limit=max_items,
    )
    if not top_todo_routes:
        top_todo_routes = legal_ir_view_gap_todo_routes or fallback_todo_routes
        todo_routes_inferred_from_features = bool(top_todo_routes)
    elif legal_ir_view_gap_todo_routes or fallback_todo_routes:
        merged_routes = Counter(
            {str(route): float(count) for route, count in top_todo_routes.items()}
        )
        for route, count in {
            **legal_ir_view_gap_todo_routes,
            **fallback_todo_routes,
        }.items():
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
    promotion_gate = compiler_guidance_promotion_gate(canary_block)
    guidance_attribution = (
        dict(canary_block.get("attribution"))
        if isinstance(canary_block.get("attribution"), Mapping)
        else {}
    )
    has_candidates = bool(
        top_feature_groups
        or top_legal_ir_view_family_gaps
        or top_legal_ir_view_gaps
        or top_semantic_overlay_terms
        or top_surface_features
        or top_todo_routes
        or scope_hints.get("scope_counts")
    )
    return {
        "has_candidates": has_candidates,
        "guidance_attribution": guidance_attribution,
        "guidance_attribution_summary": _compiler_guidance_attribution_summary(
            guidance_attribution
        ),
        "promotion_allowed": promotion_gate["promotion_allowed"],
        "promotion_block_reason": promotion_gate["promotion_block_reason"],
        "quality_gate": promotion_gate["quality_gate"],
        "recommended_mode": promotion_gate["recommended_mode"],
        "scope_hints": scope_hints,
        "top_semantic_overlay_terms": top_semantic_overlay_terms,
        "top_feature_groups": top_feature_groups,
        "top_legal_ir_view_family_gaps": top_legal_ir_view_family_gaps,
        "top_legal_ir_view_gaps": top_legal_ir_view_gaps,
        "top_surface_features": top_surface_features,
        "top_todo_route_examples": top_todo_route_examples,
        "top_todo_routes": top_todo_routes,
        "todo_routes_augmented_from_features": todo_routes_augmented_from_features,
        "todo_routes_inferred_from_features": todo_routes_inferred_from_features,
    }


def compiler_guidance_distillation_path(summary_path: Path) -> Path:
    return summary_path.with_name(
        f"{summary_path.stem}.compiler-guidance-distillation.json"
    )


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


GUIDANCE_SCOPE_TARGET_METRICS = {
    "bridge": (
        "legal_ir_view_cross_entropy_loss",
        "legal_ir_multiview_total_loss",
    ),
    "cec": (
        "cec_dcec_validation_failure_ratio",
        "legal_ir_view_cross_entropy_loss",
    ),
    "compiler_ambiguity": (
        "cross_entropy_loss",
        "cosine_similarity",
        "compiler_ir_cross_entropy_loss",
        "compiler_ir_cosine_similarity",
        "compiler_ir_reconstruction_loss",
    ),
    "compiler_parser": (
        "modal_span_coverage_loss",
        "symbolic_validity_penalty",
        "compiler_ir_modal_span_coverage_loss",
        "compiler_ir_symbolic_validity_penalty",
    ),
    "compiler_registry": (
        "cross_entropy_loss",
        "cosine_similarity",
        "compiler_ir_cross_entropy_loss",
        "compiler_ir_cosine_similarity",
        "compiler_ir_reconstruction_loss",
    ),
    "deontic": (
        "deontic_decoder_slot_loss",
        "legal_ir_view_cross_entropy_loss",
    ),
    "external_provers": ("legal_ir_multiview_proof_failure_ratio",),
    "frame_logic": ("flogic_similarity_loss", "ontology_violation_count"),
    "ir_decompiler": (
        "cosine_similarity",
        "compiler_ir_cosine_similarity",
        "compiler_ir_cross_entropy_loss",
        "compiler_ir_reconstruction_loss",
        "compiler_ir_source_decompiled_text_embedding_cosine_loss",
        "compiler_ir_source_decompiled_text_token_loss",
        "compiler_ir_source_copy_reward_hack_penalty",
        "compiler_ir_structural_text_reconstruction_loss",
        "compiler_ir_text_reconstruction_loss",
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
        "compiler_ir_cross_entropy_loss",
        "compiler_ir_cosine_similarity",
        "source_copy_reward_hack_penalty",
    ]
    metrics.extend(GUIDANCE_SCOPE_TARGET_METRICS.get(str(scope), ()))
    if "decompiler" in route:
        metrics.extend(
            (
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
            "compiler_guidance_legal_ir_view_family_gaps": dict(
                candidates.get("top_legal_ir_view_family_gaps")
                if isinstance(candidates.get("top_legal_ir_view_family_gaps"), Mapping)
                else {}
            ),
            "compiler_guidance_quality_gate": candidates.get("quality_gate", ""),
            "compiler_guidance_route": action,
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
            "compiler_guidance_canary": dict(canary_block),
            "compiler_guidance_legal_ir_view_gaps": dict(
                candidates.get("top_legal_ir_view_gaps")
                if isinstance(candidates.get("top_legal_ir_view_gaps"), Mapping)
                else {}
            ),
            "compiler_guidance_legal_ir_view_family_gaps": dict(
                candidates.get("top_legal_ir_view_family_gaps")
                if isinstance(candidates.get("top_legal_ir_view_family_gaps"), Mapping)
                else {}
            ),
            "compiler_guidance_quality_gate": canary_block.get("quality_gate", ""),
            "compiler_guidance_route": action,
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
        "compiler_guidance_canary": dict(canary_block),
        "compiler_guidance_guardrail_reason": guardrail_reason,
        "compiler_guidance_legal_ir_view_gaps": dict(
            candidates.get("top_legal_ir_view_gaps")
            if isinstance(candidates.get("top_legal_ir_view_gaps"), Mapping)
            else {}
        ),
        "compiler_guidance_legal_ir_view_family_gaps": dict(
            candidates.get("top_legal_ir_view_family_gaps")
            if isinstance(candidates.get("top_legal_ir_view_family_gaps"), Mapping)
            else {}
        ),
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

def cleanup_program_synthesis_terminal_queue(
    *,
    queue_path: str | Path,
    archive_dir: Optional[str | Path] = None,
    policy: Optional[ModalOptimizerPolicy] = None,
    statuses: Sequence[str] = ("superseded",),
    supersede_rescued_failed_validations: bool = True,
) -> Dict[str, Any]:
    """Archive terminal program-synthesis history out of an active queue."""

    queue_path = Path(queue_path)
    policy = policy or ModalOptimizerPolicy()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
        before = queue.status_counts()
        superseded_report: Dict[str, Any] = {}
        if supersede_rescued_failed_validations:
            superseded_report = queue.supersede_rescued_failed_validations(
                optimizer_role=policy.program_synthesis_role,
            )
        archived = queue.pop_terminal_history(
            optimizer_role=policy.program_synthesis_role,
            statuses=statuses,
        )
        archived_status_counts: Dict[str, int] = {}
        for todo in archived:
            archived_status_counts[todo.status] = (
                archived_status_counts.get(todo.status, 0) + 1
            )

        backup_path: Optional[Path] = None
        archive_path: Optional[Path] = None
        changed = bool(archived) or bool(superseded_report.get("superseded_count"))
        if changed:
            if queue_path.exists():
                backup_path = queue_path.with_name(
                    f"{queue_path.name}.pre-terminal-cleanup-{timestamp}.bak"
                )
                shutil.copy2(queue_path, backup_path)
            if archived:
                destination_dir = (
                    Path(archive_dir) if archive_dir is not None else queue_path.parent / "archive"
                )
                destination_dir.mkdir(parents=True, exist_ok=True)
                archive_path = destination_dir / (
                    f"{queue_path.stem}.terminal-history-{timestamp}.jsonl"
                )
                archive_path.write_text(
                    "\n".join(todo.to_json() for todo in archived) + "\n",
                    encoding="utf-8",
                )
            queue.save_jsonl(queue_path)
        after = queue.status_counts()

    return {
        "archive_path": str(archive_path) if archive_path is not None else None,
        "archived_count": len(archived),
        "archived_status_counts": dict(sorted(archived_status_counts.items())),
        "backup_path": str(backup_path) if backup_path is not None else None,
        "before": before,
        "after": after,
        "changed": changed,
        "queue_path": str(queue_path),
        "statuses": list(statuses),
        "superseded_report": superseded_report,
    }


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


def _adapter_names_from_raw(raw: Any) -> List[str]:
    text = str(raw or "").strip()
    if text.lower() in {"", "none", "off", "false"}:
        return []
    return [
        name
        for name in (part.strip() for part in text.split(","))
        if name and name.lower() not in {"none", "off", "false"}
    ]


def autoencoder_metric_bridge_adapter_names(
    args: argparse.Namespace,
    bridge_adapters: Sequence[str],
) -> List[str]:
    """Return lightweight bridge adapters used for validation metrics.

    Metric bridge adapters are deliberately independent from bridge-loss
    adapters so disabling bridge losses does not also blind LegalIR validation.
    """

    raw = getattr(args, "autoencoder_metric_bridge_adapters", None)
    if raw is None:
        raw = os.environ.get(AUTOENCODER_METRIC_BRIDGE_ADAPTERS_ENV)
    if raw is None or str(raw).strip().lower() == "default":
        return list(DEFAULT_AUTOENCODER_METRIC_BRIDGE_ADAPTERS)
    if str(raw).strip().lower() == "same":
        return list(bridge_adapters)
    return _adapter_names_from_raw(raw)


def autoencoder_diagnostic_bridge_adapter_names(
    args: argparse.Namespace,
    *,
    bridge_adapters: Sequence[str],
    metric_bridge_adapters: Sequence[str],
) -> List[str]:
    """Return occasional diagnostic bridge adapters for syntax/KG/prover coverage."""

    raw = getattr(args, "autoencoder_diagnostic_bridge_adapters", None)
    if raw is None:
        raw = os.environ.get(AUTOENCODER_DIAGNOSTIC_BRIDGE_ADAPTERS_ENV)
    if raw is None:
        return []
    normalized = str(raw).strip().lower()
    if normalized == "default":
        return list(metric_bridge_adapters)
    if normalized == "same":
        return list(bridge_adapters)
    return _adapter_names_from_raw(raw)


def autoencoder_metric_bridge_samples_for_evaluation(
    samples: Sequence[Any],
    *,
    max_sample_text_chars: int,
) -> List[Any]:
    """Return samples with bounded text for expensive bridge metric evaluation."""

    limit = max(0, int(max_sample_text_chars or 0))
    if limit <= 0:
        return list(samples)
    bounded_samples: List[Any] = []
    for sample in samples:
        text = str(getattr(sample, "text", "") or "")
        if len(text) <= limit:
            bounded_samples.append(sample)
            continue
        bounded_text = _compiler_ir_metric_bounded_text(text, limit)
        bounded_samples.append(
            _compiler_ir_metric_sample_for_text(
                sample,
                metric_text=bounded_text,
            )
        )
    return bounded_samples


def evaluate_autoencoder_with_bounded_metric_bridges(
    autoencoder: AdaptiveModalAutoencoder,
    samples: Sequence[Any],
    *,
    legal_ir_bridge_names: Sequence[str],
    legal_ir_evaluate_provers: Optional[bool],
    legal_ir_parallel_workers: Optional[int],
    max_bridge_sample_text_chars: int,
    use_sample_memory: bool,
) -> AutoencoderEvaluation:
    """Evaluate full text embeddings while bounding expensive bridge targets."""

    sample_list = list(samples)
    bridge_names = [str(name) for name in legal_ir_bridge_names if str(name)]
    if not sample_list or not bridge_names:
        return autoencoder.evaluate(
            sample_list,
            legal_ir_bridge_names=(),
            legal_ir_evaluate_provers=legal_ir_evaluate_provers,
            legal_ir_parallel_workers=legal_ir_parallel_workers,
            use_sample_memory=use_sample_memory,
        )
    bridge_samples = autoencoder_metric_bridge_samples_for_evaluation(
        sample_list,
        max_sample_text_chars=max_bridge_sample_text_chars,
    )
    bridge = autoencoder.evaluate(
        bridge_samples,
        legal_ir_bridge_names=bridge_names,
        legal_ir_evaluate_provers=legal_ir_evaluate_provers,
        legal_ir_parallel_workers=legal_ir_parallel_workers,
        use_sample_memory=use_sample_memory,
    )
    alias_targets = getattr(autoencoder, "alias_cached_legal_ir_targets", None)
    if callable(alias_targets):
        alias_targets(sample_list, bridge_samples)
    base = autoencoder.evaluate(
        sample_list,
        legal_ir_bridge_names=(),
        legal_ir_evaluate_provers=legal_ir_evaluate_provers,
        legal_ir_parallel_workers=legal_ir_parallel_workers,
        use_sample_memory=use_sample_memory,
    )
    if not isinstance(base, AutoencoderEvaluation):
        # Preserve compatibility with lightweight evaluator adapters that only
        # implement the reconstruction metrics used by older runner plugins.
        return base
    return replace(
        base,
        legal_ir_target_count=int(getattr(bridge, "legal_ir_target_count", 0) or 0),
        legal_ir_losses=dict(getattr(bridge, "legal_ir_losses", {}) or {}),
        legal_ir_predicted_view_distribution=dict(
            getattr(bridge, "legal_ir_predicted_view_distribution", {}) or {}
        ),
        legal_ir_target_hashes=dict(
            getattr(bridge, "legal_ir_target_hashes", {}) or {}
        ),
        legal_ir_view_distribution=dict(
            getattr(bridge, "legal_ir_view_distribution", {}) or {}
        ),
    )


def _todo_supervisor_precomputed_evaluations(
    *,
    feature_projection_report: Mapping[str, Any],
    train_samples: Sequence[Any],
    validation_samples: Sequence[Any],
    before_train: AutoencoderEvaluation,
    before_validation: AutoencoderEvaluation,
) -> tuple[Optional[AutoencoderEvaluation], Optional[AutoencoderEvaluation]]:
    """Reuse only evaluations that describe the state entering TODO training."""

    def matches_samples(
        evaluation: Optional[AutoencoderEvaluation],
        samples: Sequence[Any],
    ) -> bool:
        if evaluation is None or evaluation.sample_count != len(samples):
            return False
        expected_ids = {
            str(getattr(sample, "sample_id", "") or "")
            for sample in samples
        }
        evaluated_ids = set(evaluation.decoded_embeddings)
        return not evaluated_ids or evaluated_ids == expected_ids

    accepted_epochs = int(feature_projection_report.get("accepted_epochs", 0) or 0)
    if accepted_epochs <= 0:
        return (
            before_train if matches_samples(before_train, train_samples) else None,
            (
                before_validation
                if matches_samples(before_validation, validation_samples)
                else None
            ),
        )

    projection_validation: Optional[AutoencoderEvaluation] = None
    after_payload = feature_projection_report.get("after")
    if isinstance(after_payload, Mapping):
        try:
            projection_validation = AutoencoderEvaluation(**dict(after_payload))
        except (TypeError, ValueError):
            projection_validation = None
    if not matches_samples(projection_validation, validation_samples):
        projection_validation = None
    return None, projection_validation


def autoencoder_validation_signal_health(
    *,
    compiler_ir_validation: Mapping[str, Any],
    learned_ir_validation: Mapping[str, Any],
    logic_bridge_validation: Mapping[str, Any],
    validation_metrics: Mapping[str, Any],
    metric_bridge_adapters: Sequence[str],
    diagnostic_bridge_adapters: Sequence[str],
) -> Dict[str, Any]:
    """Summarize whether validation metrics are active enough to trust."""

    issues: List[str] = []
    recommendations: List[str] = []
    compiler_sample_count = int(compiler_ir_validation.get("sample_count", 0) or 0)
    compiler_evaluated_count = int(compiler_ir_validation.get("evaluated_count", 0) or 0)
    compiler_timeouts = int(compiler_ir_validation.get("sample_timeouts", 0) or 0)
    validation_sample_count = int(validation_metrics.get("sample_count", 0) or 0)
    learned_target_count = int(learned_ir_validation.get("target_count", 0) or 0)
    bridge_adapter_count = int(logic_bridge_validation.get("adapter_count", 0) or 0)
    bridge_evaluated_count = int(logic_bridge_validation.get("evaluated_count", 0) or 0)

    if learned_target_count <= 0:
        issues.append("learned_ir_targets_inactive")
    if compiler_sample_count > 0 and compiler_timeouts >= compiler_sample_count:
        issues.append("compiler_ir_all_samples_timed_out")
    if compiler_sample_count > 0 and compiler_evaluated_count <= 0:
        issues.append("compiler_ir_metrics_inactive")
    if validation_sample_count < 8:
        issues.append("validation_holdout_too_small")
    if metric_bridge_adapters and bridge_adapter_count > 0 and bridge_evaluated_count <= 0:
        issues.append("logic_bridge_metrics_inactive")
    if metric_bridge_adapters and not diagnostic_bridge_adapters:
        recommendations.append(
            "run occasional diagnostic bridge sweeps for syntax/KG/prover coverage"
        )

    hard_failures = {
        "compiler_ir_all_samples_timed_out",
        "compiler_ir_metrics_inactive",
        "learned_ir_targets_inactive",
    }
    if any(issue in hard_failures for issue in issues):
        quality_gate = "fail"
    elif issues:
        quality_gate = "warn"
    else:
        quality_gate = "pass"

    return {
        "compiler_ir": {
            "evaluated_count": compiler_evaluated_count,
            "sample_count": compiler_sample_count,
            "sample_timeouts": compiler_timeouts,
        },
        "diagnostic_bridge_adapters": list(diagnostic_bridge_adapters),
        "issues": issues,
        "learned_ir": {"target_count": learned_target_count},
        "logic_bridge": {
            "adapter_count": bridge_adapter_count,
            "evaluated_count": bridge_evaluated_count,
        },
        "metric_bridge_adapters": list(metric_bridge_adapters),
        "quality_gate": quality_gate,
        "recommendations": recommendations,
        "validation": {"sample_count": validation_sample_count},
    }


def parse_bool_flag(value: Any) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean flag, got {value!r}")


def autoencoder_introspection_mode(args: argparse.Namespace) -> str:
    """Return the normalized reversible introspection rollout mode."""

    mode = str(
        getattr(args, "autoencoder_introspection_mode", DEFAULT_AUTOENCODER_INTROSPECTION_MODE)
        or DEFAULT_AUTOENCODER_INTROSPECTION_MODE
    ).strip().lower()
    if mode in {"0", "false", "no", "none", "disabled"}:
        return "off"
    if mode not in MODAL_INTROSPECTION_MODES:
        return DEFAULT_AUTOENCODER_INTROSPECTION_MODE
    return mode


def autoencoder_target_scope_filters(args: argparse.Namespace) -> List[str]:
    raw = getattr(args, "autoencoder_target_scope_filters", "")
    if raw is None:
        raw = getattr(args, "autoencoder_target_scope_filter", "")
    if isinstance(raw, str):
        values: Iterable[str] = raw.split(",")
    else:
        values = raw
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value).strip()
            and str(value).strip().lower() not in {"all", "none", "off", "false"}
        )
    )


def autoencoder_rollout_control(args: argparse.Namespace) -> Dict[str, Any]:
    mode = autoencoder_introspection_mode(args)
    return {
        "export_every_n_cycles": max(
            1,
            int(
                getattr(
                    args,
                    "autoencoder_introspection_every_n_cycles",
                    DEFAULT_AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES,
                )
                or DEFAULT_AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES
            ),
        ),
        "introspection_mode": mode,
        "min_export_samples": max(
            0,
            int(
                getattr(
                    args,
                    "autoencoder_introspection_min_export_samples",
                    DEFAULT_AUTOENCODER_INTROSPECTION_MIN_EXPORT_SAMPLES,
                )
                or 0
            ),
        ),
        "max_audits_per_cycle": max(
            0,
            int(getattr(args, "autoencoder_max_audits_per_cycle", 0) or 0),
        ),
        "max_todos_per_cycle": max(
            0,
            int(getattr(args, "autoencoder_max_todos_per_cycle", 0) or 0),
        ),
        "require_prover_confirmation": bool(
            getattr(args, "autoencoder_require_prover_confirmation", True)
        ),
        "target_scope_filters": autoencoder_target_scope_filters(args),
    }


def autoencoder_introspection_export_due(
    rollout_control: Mapping[str, Any],
    *,
    cycle: int,
) -> bool:
    """Return whether full Leanstral disagreement evidence is due this cycle."""

    mode = str(rollout_control.get("introspection_mode") or "off")
    if not introspection_export_mode_enabled(mode):
        return False
    cadence = max(
        1,
        int(
            rollout_control.get("export_every_n_cycles")
            or DEFAULT_AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES
        ),
    )
    cycle_number = max(1, int(cycle))
    return cycle_number == 1 or cycle_number % cadence == 0


def skipped_introspection_export_report(
    *,
    cycle: int,
    rollout_control: Mapping[str, Any],
    summary_path: Path,
) -> Dict[str, Any]:
    """Return stable telemetry when a costly evidence export is not due."""

    mode = str(rollout_control.get("introspection_mode") or "off")
    cadence = max(
        1,
        int(
            rollout_control.get("export_every_n_cycles")
            or DEFAULT_AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES
        ),
    )
    cycle_number = max(1, int(cycle))
    remainder = cycle_number % cadence
    next_due_cycle = cycle_number + (cadence - remainder if remainder else cadence)
    return {
        "enabled": introspection_export_mode_enabled(mode),
        "elapsed_seconds": 0.0,
        "export_mode": mode,
        "export_every_n_cycles": cadence,
        "next_due_cycle": next_due_cycle,
        "packet_count": 0,
        "path": str(introspection_disagreement_export_path(summary_path)),
        "paths": [],
        "requested_packet_count": 0,
        "schema_failure_count": 0,
        "schema_failures": [],
        "skip_reason": (
            "cadence" if introspection_export_mode_enabled(mode) else "mode_off"
        ),
        "skipped": True,
    }


def autoencoder_enforce_fail_closed_reason(
    rollout_control: Mapping[str, Any],
    *,
    bridge_evaluate_provers: bool,
) -> str:
    if str(rollout_control.get("introspection_mode") or "off") != "enforce":
        return ""
    if bool(rollout_control.get("require_prover_confirmation", True)) and not bridge_evaluate_provers:
        return "enforce_requires_prover_confirmation"
    if int(rollout_control.get("max_audits_per_cycle", 0) or 0) <= 0:
        return "enforce_requires_positive_audit_budget"
    return ""


def _sample_matches_target_scope(sample: Any, scope_filters: Sequence[str]) -> bool:
    filters = {str(value).strip() for value in scope_filters if str(value).strip()}
    if not filters:
        return True
    scopes = {
        str(getattr(sample, "source", "") or ""),
        str(getattr(sample, "title", "") or ""),
        str(getattr(sample, "section", "") or ""),
        str(getattr(sample, "selected_frame", "") or ""),
    }
    modal_ir = getattr(sample, "modal_ir", None)
    if modal_ir is not None:
        for formula in getattr(modal_ir, "formulas", ()) or ():
            operator = getattr(formula, "operator", None)
            family = str(getattr(operator, "family", "") or "")
            if family:
                scopes.add(family)
                scopes.add(f"modal.{family}")
    return bool(filters & {scope for scope in scopes if scope})


def _budgeted_audit_samples(
    samples: Sequence[Any],
    rollout_control: Mapping[str, Any],
) -> List[Any]:
    mode = str(rollout_control.get("introspection_mode") or "off")
    if mode == "off":
        return list(samples)
    scope_filters = [
        str(value)
        for value in rollout_control.get("target_scope_filters", []) or []
        if str(value)
    ]
    filtered = [
        sample
        for sample in samples
        if _sample_matches_target_scope(sample, scope_filters)
    ]
    max_audits = int(rollout_control.get("max_audits_per_cycle", 0) or 0)
    if max_audits <= 0:
        return []
    return filtered[:max_audits]


def _budgeted_audit_samples_with_indices(
    samples: Sequence[Any],
    indices: Sequence[int],
    rollout_control: Mapping[str, Any],
) -> tuple[List[Any], List[int]]:
    """Apply the audit budget while preserving frozen-canary index identity."""

    selected = _budgeted_audit_samples(samples, rollout_control)
    selected_object_ids = {id(sample) for sample in selected}
    selected_indices = [
        int(indices[position])
        for position, sample in enumerate(samples)
        if id(sample) in selected_object_ids and position < len(indices)
    ]
    return selected, selected_indices


def _introspection_export_samples_with_indices(
    samples: Sequence[Any],
    indices: Sequence[int],
    rollout_control: Mapping[str, Any],
) -> tuple[List[Any], List[int]]:
    """Select validation samples for packet export without raising TODO budget."""

    mode = str(rollout_control.get("introspection_mode") or "off")
    if mode == "off":
        return list(samples), [int(index) for index in indices]
    scope_filters = [
        str(value)
        for value in rollout_control.get("target_scope_filters", []) or []
        if str(value)
    ]
    max_audits = max(0, int(rollout_control.get("max_audits_per_cycle", 0) or 0))
    min_export_samples = max(
        0,
        int(rollout_control.get("min_export_samples", 0) or 0),
    )
    export_budget = max(max_audits, min_export_samples)
    if export_budget <= 0:
        return [], []
    selected_samples: List[Any] = []
    selected_indices: List[int] = []
    for position, sample in enumerate(samples):
        if not _sample_matches_target_scope(sample, scope_filters):
            continue
        selected_samples.append(sample)
        if position < len(indices):
            selected_indices.append(int(indices[position]))
        if len(selected_samples) >= export_budget:
            break
    return selected_samples, selected_indices


def _effective_todo_budget(default_max_items: int, rollout_control: Mapping[str, Any]) -> int:
    mode = str(rollout_control.get("introspection_mode") or "off")
    default_budget = max(0, int(default_max_items or 0))
    if mode == "off":
        return default_budget
    max_todos = max(0, int(rollout_control.get("max_todos_per_cycle", 0) or 0))
    if max_todos <= 0:
        return 0
    return min(default_budget, max_todos) if default_budget > 0 else max_todos


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
    with queue_file_lock(queue_path):
        queue = ModalTodoQueue.load_jsonl(queue_path)
        backpressure = _codex_main_apply_backpressure_report(
            queue,
            args=args,
            policy=policy,
            worker_id=worker_id,
        )
        if bool(backpressure.get("blocked", False)):
            status = update_program_synthesis_summary(
                summary,
                queue,
                policy,
                execution_mode=execution_mode,
            )
            vector_report["mode"] = "main_apply_backpressure"
            vector_report["main_apply_backpressure"] = backpressure
            vector_report["main_apply_backpressure_active_workers"] = list(
                backpressure.get("active_workers", []) or []
            )
            vector_report["selected_count"] = 0
            return [], queue, status, vector_report

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
        "--codex-main-apply-lock-timeout-seconds",
        str(getattr(args, "codex_main_apply_lock_timeout_seconds", 300.0)),
        "--codex-main-apply-max-inflight-packets",
        str(getattr(args, "codex_main_apply_max_inflight_packets", 1)),
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
        "--max-sample-text-chars",
        str(getattr(args, "max_sample_text_chars", 0)),
        "--max-inner-iterations",
        str(args.max_inner_iterations),
        "--max-items",
        str(args.max_items),
        "--program-synthesis-min-support",
        str(getattr(args, "program_synthesis_min_support", 2)),
        "--max-program-synthesis-pending",
        str(getattr(args, "max_program_synthesis_pending", 512)),
        "--program-synthesis-min-residual-occurrences",
        str(getattr(args, "program_synthesis_min_residual_occurrences", 1)),
        "--program-synthesis-min-residual-survival-score",
        str(getattr(args, "program_synthesis_min_residual_survival_score", 0.0)),
        "--learning-rate",
        str(args.learning_rate),
        "--generalizable-projection-epochs",
        str(getattr(args, "generalizable_projection_epochs", 1)),
        "--sampling-seed",
        str(getattr(args, "sampling_seed", getattr(args, "run_id", "default"))),
        "--autoencoder-bootstrap-mode",
        str(getattr(args, "autoencoder_bootstrap_mode", "fast")),
        "--autoencoder-metric-bridge-adapters",
        str(getattr(args, "autoencoder_metric_bridge_adapters", "default")),
        "--autoencoder-diagnostic-bridge-adapters",
        str(getattr(args, "autoencoder_diagnostic_bridge_adapters", "none")),
        "--autoencoder-metric-bridge-max-sample-text-chars",
        str(
            getattr(
                args,
                "autoencoder_metric_bridge_max_sample_text_chars",
                DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
            )
        ),
        "--compiler-ir-metric-text-policy",
        str(getattr(args, "compiler_ir_metric_text_policy", DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY)),
        "--compiler-ir-metric-max-sample-text-chars",
        str(
            getattr(
                args,
                "compiler_ir_metric_max_sample_text_chars",
                _default_compiler_ir_metric_max_sample_text_chars(),
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
        "--generalizable-projection-timeout-seconds",
        str(
            getattr(
                args,
                "generalizable_projection_timeout_seconds",
                DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS,
            )
        ),
        "--generalizable-projection-max-line-search-attempts",
        str(
            getattr(
                args,
                "generalizable_projection_max_line_search_attempts",
                DEFAULT_GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS,
            )
        ),
        "--bridge-loss-adapters",
        str(getattr(args, "bridge_loss_adapters", DEFAULT_BRIDGE_LOSS_ADAPTERS)),
        "--bridge-evaluate-provers",
        str(getattr(args, "bridge_evaluate_provers", _default_bridge_evaluate_provers())).lower(),
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
        "--autoencoder-max-definition-grounding-features",
        str(getattr(args, "autoencoder_max_definition_grounding_features", 64)),
        "--autoencoder-max-quantifier-scope-features",
        str(getattr(args, "autoencoder_max_quantifier_scope_features", 64)),
        "--autoencoder-max-procedural-lifecycle-features",
        str(getattr(args, "autoencoder_max_procedural_lifecycle_features", 64)),
        "--autoencoder-max-enforcement-remedy-features",
        str(getattr(args, "autoencoder_max_enforcement_remedy_features", 64)),
        "--autoencoder-max-reference-dependency-features",
        str(getattr(args, "autoencoder_max_reference_dependency_features", 64)),
        "--autoencoder-max-authority-jurisdiction-features",
        str(getattr(args, "autoencoder_max_authority_jurisdiction_features", 64)),
        "--autoencoder-max-temporal-validity-features",
        str(getattr(args, "autoencoder_max_temporal_validity_features", 64)),
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
        "--autoencoder-max-codec-feature-keys",
        str(getattr(args, "autoencoder_max_codec_feature_keys", 64)),
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
        "--autoencoder-projection-deadband-mode",
        str(getattr(args, "autoencoder_projection_deadband_mode", "shadow")),
        "--autoencoder-max-ce-deadband",
        str(getattr(args, "autoencoder_max_ce_deadband", 0.0001)),
        "--autoencoder-hard-guardrail-metrics",
        str(
            getattr(
                args,
                "autoencoder_hard_guardrail_metrics",
                "compiler_ir_cosine,structural_validity,source_copy_penalty",
            )
        ),
        "--autoencoder-projection-prescreen-mode",
        str(getattr(args, "autoencoder_projection_prescreen_mode", "off")),
        "--autoencoder-projection-prescreen-top-k",
        str(getattr(args, "autoencoder_projection_prescreen_top_k", 3)),
        "--autoencoder-projection-periodic-full-search-every-n-cycles",
        str(getattr(args, "autoencoder_projection_periodic_full_search_every_n_cycles", 8)),
        "--compiler-ir-train-mode",
        str(getattr(args, "compiler_ir_train_mode", DEFAULT_COMPILER_IR_TRAIN_MODE)),
        "--compiler-ir-train-every-n-cycles",
        str(getattr(args, "compiler_ir_train_every_n_cycles", 4)),
        "--compiler-ir-guided-train-mode",
        str(getattr(args, "compiler_ir_guided_train_mode", DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE)),
        "--compiler-ir-guided-train-every-n-cycles",
        str(getattr(args, "compiler_ir_guided_train_every_n_cycles", 4)),
        "--autoencoder-before-train-eval-mode",
        str(getattr(args, "autoencoder_before_train_eval_mode", DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE)),
        "--autoencoder-before-train-eval-every-n-cycles",
        str(getattr(args, "autoencoder_before_train_eval_every_n_cycles", 4)),
        "--autoencoder-sample-memory-probe-mode",
        str(getattr(args, "autoencoder_sample_memory_probe_mode", DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE)),
        "--autoencoder-sample-memory-probe-every-n-cycles",
        str(getattr(args, "autoencoder_sample_memory_probe_every_n_cycles", 4)),
        "--autoencoder-todo-supervisor-mode",
        str(getattr(args, "autoencoder_todo_supervisor_mode", DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE)),
        "--autoencoder-todo-supervisor-min-open",
        str(getattr(args, "autoencoder_todo_supervisor_min_open", 12)),
        "--autoencoder-introspection-mode",
        str(
            getattr(
                args,
                "autoencoder_introspection_mode",
                DEFAULT_AUTOENCODER_INTROSPECTION_MODE,
            )
        ),
        "--autoencoder-introspection-every-n-cycles",
        str(
            getattr(
                args,
                "autoencoder_introspection_every_n_cycles",
                DEFAULT_AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES,
            )
        ),
        "--autoencoder-introspection-min-export-samples",
        str(
            getattr(
                args,
                "autoencoder_introspection_min_export_samples",
                DEFAULT_AUTOENCODER_INTROSPECTION_MIN_EXPORT_SAMPLES,
            )
        ),
        "--autoencoder-max-audits-per-cycle",
        str(getattr(args, "autoencoder_max_audits_per_cycle", 0)),
        "--autoencoder-max-todos-per-cycle",
        str(getattr(args, "autoencoder_max_todos_per_cycle", 0)),
        "--leanstral-rule-gap-projection-enabled",
        str(getattr(args, "leanstral_rule_gap_projection_enabled", True)).lower(),
        "--leanstral-rule-gap-report-path",
        str(getattr(args, "leanstral_rule_gap_report_path", "")),
        "--leanstral-rule-gap-max-todos-per-scope",
        str(getattr(args, "leanstral_rule_gap_max_todos_per_scope", 2)),
        "--leanstral-rule-gap-require-executor-available",
        str(
            getattr(args, "leanstral_rule_gap_require_executor_available", True)
        ).lower(),
        "--leanstral-rule-gap-expected-compiler-commit",
        str(getattr(args, "leanstral_rule_gap_expected_compiler_commit", "")),
        "--leanstral-rule-gap-expected-state-hash",
        str(getattr(args, "leanstral_rule_gap_expected_state_hash", "")),
        "--leanstral-direct-guidance-projection-enabled",
        str(
            getattr(args, "leanstral_direct_guidance_projection_enabled", True)
        ).lower(),
        "--leanstral-direct-guidance-path",
        str(getattr(args, "leanstral_direct_guidance_path", "")),
        "--leanstral-direct-guidance-max-todos-per-scope",
        str(getattr(args, "leanstral_direct_guidance_max_todos_per_scope", 2)),
        "--leanstral-direct-guidance-require-executor-available",
        str(
            getattr(
                args,
                "leanstral_direct_guidance_require_executor_available",
                True,
            )
        ).lower(),
        "--leanstral-direct-guidance-train-autoencoder",
        str(
            getattr(args, "leanstral_direct_guidance_train_autoencoder", True)
        ).lower(),
        "--leanstral-direct-guidance-learning-rate",
        str(getattr(args, "leanstral_direct_guidance_learning_rate", 0.05)),
        "--leanstral-direct-guidance-train-missing-samples",
        str(
            getattr(args, "leanstral_direct_guidance_train_missing_samples", False)
        ).lower(),
        "--leanstral-direct-guidance-max-training-items",
        str(getattr(args, "leanstral_direct_guidance_max_training_items", 64)),
        "--daemon-hammer-guidance-enabled",
        str(getattr(args, "daemon_hammer_guidance_enabled", True)).lower(),
        "--daemon-hammer-guidance-cache-enabled",
        str(getattr(args, "daemon_hammer_guidance_cache_enabled", True)).lower(),
        "--daemon-hammer-guidance-output-dir",
        str(getattr(args, "daemon_hammer_guidance_output_dir", "")),
        "--daemon-hammer-guidance-max-samples-per-cycle",
        str(
            getattr(
                args,
                "daemon_hammer_guidance_max_samples_per_cycle",
                DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_SAMPLES_PER_CYCLE,
            )
        ),
        "--daemon-hammer-guidance-max-obligations-per-sample",
        str(
            getattr(
                args,
                "daemon_hammer_guidance_max_obligations_per_sample",
                DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_OBLIGATIONS_PER_SAMPLE,
            )
        ),
        "--daemon-hammer-guidance-max-premises",
        str(
            getattr(
                args,
                "daemon_hammer_guidance_max_premises",
                DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_PREMISES,
            )
        ),
        "--daemon-hammer-guidance-timeout-seconds",
        str(
            getattr(
                args,
                "daemon_hammer_guidance_timeout_seconds",
                DEFAULT_DAEMON_HAMMER_GUIDANCE_TIMEOUT_SECONDS,
            )
        ),
        "--daemon-hammer-guidance-parallel-workers",
        str(
            getattr(
                args,
                "daemon_hammer_guidance_parallel_workers",
                DEFAULT_DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS,
            )
        ),
        "--daemon-hammer-guidance-verify-reconstruction",
        str(
            getattr(args, "daemon_hammer_guidance_verify_reconstruction", False)
        ).lower(),
        "--daemon-hammer-guidance-trusted-requires-reconstruction",
        str(
            getattr(
                args,
                "daemon_hammer_guidance_trusted_requires_reconstruction",
                False,
            )
        ).lower(),
        "--daemon-hammer-guidance-train-autoencoder",
        str(getattr(args, "daemon_hammer_guidance_train_autoencoder", True)).lower(),
        "--daemon-hammer-guidance-learning-rate",
        str(getattr(args, "daemon_hammer_guidance_learning_rate", 0.03)),
        "--daemon-hammer-guidance-train-missing-samples",
        str(
            getattr(args, "daemon_hammer_guidance_train_missing_samples", False)
        ).lower(),
        "--daemon-hammer-guidance-max-training-items",
        str(getattr(args, "daemon_hammer_guidance_max_training_items", 64)),
        "--autoencoder-target-scope-filters",
        str(getattr(args, "autoencoder_target_scope_filters", "")),
        "--autoencoder-require-prover-confirmation",
        str(getattr(args, "autoencoder_require_prover_confirmation", True)).lower(),
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
        "--autoencoder-canonical-warm-start",
        str(
            getattr(
                args,
                "autoencoder_canonical_warm_start",
                "auto",
            )
        ),
    ]
    max_cycles = max(0, int(getattr(args, "max_cycles", 0) or 0))
    if max_cycles > 0:
        autoencoder_command.extend(["--max-cycles", str(max_cycles)])
    leanstral_max_report_age_seconds = getattr(
        args,
        "leanstral_rule_gap_max_report_age_seconds",
        None,
    )
    if leanstral_max_report_age_seconds is not None:
        autoencoder_command.extend(
            [
                "--leanstral-rule-gap-max-report-age-seconds",
                str(leanstral_max_report_age_seconds),
            ]
        )
    canonical_warm_start_state = getattr(args, "canonical_warm_start_state", None)
    if canonical_warm_start_state:
        autoencoder_command.extend(
            ["--canonical-warm-start-state", str(canonical_warm_start_state)]
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

    auto_ok = (
        bool(autoencoder_success)
        if autoencoder_success is not None
        else autoencoder_exit_code == 0
    )
    if not codex_exit_codes or not auto_ok:
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
    autoencoder_child_health: Optional[Mapping[str, Any]] = None,
    runner_terminated_children: AbstractSet[str],
    stop_requested: bool = False,
) -> bool:
    """Return whether the paired autoencoder child reached its own clean stop."""

    if stop_requested:
        return False
    runner_stopped_child = autoencoder_run_id in runner_terminated_children
    if autoencoder_exit_code == 0:
        if not runner_stopped_child:
            return True
        health = dict(autoencoder_child_health or {})
        try:
            cycles = int(health.get("autoencoder_cycles", 0) or 0)
        except (TypeError, ValueError):
            cycles = 0
        return bool(health.get("autoencoder_summary_final", False)) or cycles > 0
    runner_stopped_by_signal = (
        runner_stopped_child
        and autoencoder_exit_code in {-signal.SIGTERM, -signal.SIGKILL}
    )
    if not runner_stopped_by_signal:
        return False
    health = dict(autoencoder_child_health or {})
    try:
        cycles = int(health.get("autoencoder_cycles", 0) or 0)
    except (TypeError, ValueError):
        cycles = 0
    summary_final = bool(health.get("autoencoder_summary_final", False))
    return summary_final or cycles > 0


def _paired_child_exit_should_restart(
    *,
    exit_code: Optional[int],
    restart_count: int,
    restart_limit: int,
    latest_stop_reason: str = "",
    stop_requested: bool = False,
) -> bool:
    """Return whether an accelerate-style paired child should be relaunched."""

    if stop_requested or exit_code is None:
        return False
    if int(restart_count) >= int(restart_limit):
        return False
    if exit_code != 0:
        return True
    return str(latest_stop_reason or "").startswith("signal_")


def _host_resource_health() -> Dict[str, float]:
    """Return lightweight host resource health without requiring psutil."""

    health: Dict[str, float] = {"cpu_count": float(os.cpu_count() or 1)}
    try:
        meminfo: Dict[str, float] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            parts = raw_value.strip().split()
            if not parts:
                continue
            meminfo[key] = float(parts[0]) / (1024.0 * 1024.0)
        if "MemAvailable" in meminfo:
            health["memory_available_gb"] = meminfo["MemAvailable"]
        if "MemTotal" in meminfo:
            health["memory_total_gb"] = meminfo["MemTotal"]
        if "SwapFree" in meminfo:
            health["swap_free_gb"] = meminfo["SwapFree"]
        if "SwapTotal" in meminfo:
            health["swap_total_gb"] = meminfo["SwapTotal"]
    except OSError:
        pass
    return health


def paired_codex_worker_resource_plan(
    args: argparse.Namespace,
    *,
    requested_workers: int,
    resource_health: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan a Codex worker count from CPU, memory, and swap pressure."""

    health = dict(resource_health or _host_resource_health())
    requested = max(1, int(requested_workers or 1))
    guard = str(getattr(args, "paired_resource_guard", "auto") or "auto").lower()
    cpu_count = max(1, int(float(health.get("cpu_count", os.cpu_count() or 1) or 1)))
    cpu_cap = max(1, int(cpu_count * 0.6))
    available_gb = float(health.get("memory_available_gb", 0.0) or 0.0)
    reserved_gb = max(0.0, float(getattr(args, "paired_reserved_memory_gb", 0.0) or 0.0))
    worker_gb = max(0.001, float(getattr(args, "paired_codex_worker_memory_gb", 1.0) or 1.0))
    memory_cap = max(1, int((available_gb - reserved_gb) // worker_gb)) if available_gb else requested
    min_swap_free_gb = max(0.0, float(getattr(args, "paired_min_swap_free_gb", 0.0) or 0.0))
    swap_free_gb = float(health.get("swap_free_gb", min_swap_free_gb) or 0.0)
    swap_pressure = bool(min_swap_free_gb > 0.0 and swap_free_gb < min_swap_free_gb)
    swap_cap = max(1, int(cpu_cap * (2.0 / 3.0))) if swap_pressure else requested

    caps = [requested]
    reason_parts: List[str] = []
    if guard == "auto":
        caps.extend([cpu_cap, memory_cap])
        reason_parts.extend(["cpu", "memory"])
        if swap_pressure:
            caps.append(swap_cap)
            reason_parts.append("swap")
    effective = max(1, min(caps))
    reason = "unlimited" if guard in _FALSE_ENV_VALUES else f"auto_{'_'.join(reason_parts)}_cap"
    return {
        "cpu_cap": cpu_cap,
        "effective_workers": effective,
        "memory_available_gb": available_gb,
        "memory_cap": memory_cap,
        "reason": reason,
        "requested_workers": requested,
        "swap_cap": swap_cap,
        "swap_free_gb": swap_free_gb,
        "swap_pressure": swap_pressure,
    }


def _paired_resource_pressure(
    args: argparse.Namespace,
    *,
    role: str = "codex",
    resource_health: Optional[Mapping[str, Any]] = None,
) -> tuple[bool, Dict[str, Any]]:
    """Report whether resource pressure should block paired child restarts."""

    health = dict(resource_health or _host_resource_health())
    min_memory_gb = max(
        0.0,
        float(getattr(args, "paired_min_available_memory_gb", 0.0) or 0.0),
    )
    min_swap_gb = max(0.0, float(getattr(args, "paired_min_swap_free_gb", 0.0) or 0.0))
    memory_available_gb = float(health.get("memory_available_gb", 0.0) or 0.0)
    swap_free_gb = float(health.get("swap_free_gb", min_swap_gb) or 0.0)
    memory_pressure = bool(min_memory_gb > 0.0 and memory_available_gb < min_memory_gb)
    swap_pressure = bool(min_swap_gb > 0.0 and swap_free_gb < min_swap_gb)
    restart_role = str(role or "codex")
    swap_blocks_restart = swap_pressure and restart_role != "autoencoder"
    resource_pressure = memory_pressure or swap_blocks_restart
    report = {
        "memory_available_gb": memory_available_gb,
        "memory_pressure": memory_pressure,
        "memory_total_gb": float(health.get("memory_total_gb", 0.0) or 0.0),
        "min_available_memory_gb": min_memory_gb,
        "min_swap_free_gb": min_swap_gb,
        "resource_pressure": resource_pressure,
        "restart_role": restart_role,
        "swap_blocks_restart": swap_blocks_restart,
        "swap_free_gb": swap_free_gb,
        "swap_pressure": swap_pressure,
        "swap_total_gb": float(health.get("swap_total_gb", 0.0) or 0.0),
    }
    return resource_pressure, report


def paired_autoencoder_child_health(
    summary_path: Path,
    *,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Summarize autoencoder child heartbeat state for paired-run accounting."""

    current = float(now if now is not None else time.time())
    path = Path(summary_path)
    health: Dict[str, Any] = {
        "autoencoder_active_cycle": 0,
        "autoencoder_active_cycle_heartbeat_age_seconds": None,
        "autoencoder_active_cycle_phase": "",
        "autoencoder_cycles": 0,
        "autoencoder_effective_heartbeat_age_seconds": None,
        "autoencoder_latest_stop_reason": "",
        "autoencoder_summary_age_seconds": None,
        "autoencoder_summary_exists": path.exists(),
        "autoencoder_summary_final": False,
    }
    if not path.exists():
        return health
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        health["autoencoder_summary_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return health

    def age_seconds(value: Any) -> Optional[float]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return max(0.0, current - parse_utc(text))
        except (TypeError, ValueError):
            return None

    try:
        health["autoencoder_cycles"] = int(data.get("cycles", 0) or 0)
    except (TypeError, ValueError):
        health["autoencoder_cycles"] = 0
    try:
        health["autoencoder_active_cycle"] = int(data.get("active_cycle", 0) or 0)
    except (TypeError, ValueError):
        health["autoencoder_active_cycle"] = 0
    health["autoencoder_active_cycle_phase"] = str(
        data.get("active_cycle_phase", "") or ""
    )
    health["autoencoder_active_cycle_projection_stage"] = str(
        data.get("active_cycle_projection_stage", "") or ""
    )
    health["autoencoder_latest_stop_reason"] = str(
        data.get("latest_stop_reason", "") or ""
    )
    health["autoencoder_summary_final"] = bool(data.get("final", False))
    supervisor_health = (
        data.get("supervisor_health")
        if isinstance(data.get("supervisor_health"), Mapping)
        else build_modal_supervisor_health_report(data).to_dict()
    )
    health["autoencoder_supervisor_health"] = dict(supervisor_health)
    health["autoencoder_alive"] = bool(supervisor_health.get("alive", False))
    health["autoencoder_productive"] = bool(supervisor_health.get("productive", False))
    health["state_to_compiler_patch_lag"] = dict(
        data.get("state_to_compiler_patch_lag")
        if isinstance(data.get("state_to_compiler_patch_lag"), Mapping)
        else state_to_compiler_patch_lag(data)
    )
    summary_age = age_seconds(data.get("updated_at"))
    heartbeat_age = age_seconds(data.get("active_cycle_last_heartbeat_at"))
    health["autoencoder_summary_age_seconds"] = summary_age
    health["autoencoder_active_cycle_heartbeat_age_seconds"] = heartbeat_age
    effective_ages = [
        age for age in (summary_age, heartbeat_age) if age is not None
    ]
    health["autoencoder_effective_heartbeat_age_seconds"] = (
        max(effective_ages) if effective_ages else None
    )
    return health


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


def _codex_packet_main_apply_lock_timeout(
    packet: Mapping[str, Any],
    exc: BaseException,
) -> Dict[str, Any]:
    """Finalize a packet whose worktree diff could not acquire the main apply lock."""
    updated = dict(packet)
    packet_path_value = updated.get("packet_path")
    packet_path = Path(str(packet_path_value)) if packet_path_value else None
    worktree_value = updated.get("worktree_path")
    updated["main_apply_status"] = "lock_timeout"
    updated["main_apply_error"] = str(exc)
    updated["patch_status"] = "main_apply_lock_timeout"
    updated["patch_error"] = str(exc)
    updated["patch_path"] = None
    if worktree_value:
        try:
            diff_info = _codex_worktree_diff(Path(str(worktree_value)))
            diff_content = str(diff_info.get("diff_content") or "")
            updated["main_apply_target_files"] = [
                str(path) for path in diff_info.get("target_files", [])
            ]
            updated["main_apply_untracked_paths"] = [
                str(path) for path in diff_info.get("untracked_paths", [])
            ]
            updated["main_apply_ignored_artifact_paths"] = [
                str(path) for path in diff_info.get("ignored_artifact_paths", [])
            ]
            if diff_content.strip():
                patch_path = _save_codex_packet_diff_patch(
                    updated,
                    diff_content=diff_content,
                    reason="main-apply-lock-timeout",
                )
                updated["patch_path"] = str(patch_path) if patch_path else None
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as diff_exc:
            updated["main_apply_diff_error"] = str(diff_exc)
    _save_packet_if_possible(updated, packet_path)
    return updated


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


def cleanup_codex_packet_worktree(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Remove a packet worktree after its patch/apply artifacts are recorded."""
    worktree_value = packet.get("worktree_path")
    if not worktree_value:
        return {"status": "skipped", "reason": "missing_worktree_path"}
    worktree_path = Path(str(worktree_value))
    if not worktree_path.exists():
        return {"status": "skipped", "reason": "worktree_missing"}

    result = subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        shutil.rmtree(worktree_path, ignore_errors=True)
        return {
            "status": "forced_removed",
            "stderr": result.stderr[-4000:],
        }
    return {"status": "removed"}


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


def _repair_python_syntax_preflight(
    repair_worktree: Path,
    *,
    target_files: Sequence[str],
) -> Dict[str, Any]:
    """Return a py_compile preflight report for repaired Python targets."""
    python_targets = [
        str(path)
        for path in target_files
        if str(path).endswith(".py") and (repair_worktree / str(path)).exists()
    ]
    if not python_targets:
        return {"status": "skipped", "reason": "no_python_targets"}
    command = [sys.executable, "-m", "py_compile", *python_targets]
    result = subprocess.run(
        command,
        cwd=repair_worktree,
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    return {
        "command": command,
        "exit_code": result.returncode,
        "status": "passed" if result.returncode == 0 else "failed",
        "stderr_tail": (result.stderr or "")[-1000:],
        "stdout_tail": (result.stdout or "")[-1000:],
        "target_files": python_targets,
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
        syntax_preflight = _repair_python_syntax_preflight(
            repair_worktree,
            target_files=repaired_targets,
        )
        report["python_syntax_preflight"] = dict(syntax_preflight)
        if syntax_preflight.get("status") == "failed":
            report["status"] = "repaired_python_syntax_failed"
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
        syntax_preflight = _repair_python_syntax_preflight(
            repair_worktree,
            target_files=report["target_files"],
        )
        report["python_syntax_preflight"] = dict(syntax_preflight)
        if syntax_preflight.get("status") == "failed":
            report["status"] = "repaired_python_syntax_failed"
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


def accelerate_run_process_group_capture(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Optional[Mapping[str, str]] = None,
    input_text: str = "",
    timeout_seconds: float = 120.0,
) -> Dict[str, Any]:
    """Small local shim for the accelerate-style process capture contract."""

    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            input=input_text,
            capture_output=True,
            env=dict(env or os.environ),
            text=True,
            timeout=max(1.0, float(timeout_seconds)),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "status": "timeout",
            "stderr": _process_text(exc.stderr),
            "stdout": _process_text(exc.stdout),
            "timeout_seconds": float(timeout_seconds),
        }
    return {
        "exit_code": result.returncode,
        "status": "completed" if result.returncode == 0 else "failed",
        "stderr": result.stderr or "",
        "stdout": result.stdout or "",
    }


def _run_codex_apply_validation(
    repo_root: Path,
    packet_dir: Path,
    *,
    target_files: Optional[Sequence[str]] = None,
    validation_commands: Optional[Sequence[Sequence[str]]] = None,
    timeout_seconds: float = 300.0,
) -> Dict[str, Any]:
    commands = (
        [list(command) for command in validation_commands]
        if validation_commands is not None
        else _default_codex_apply_validation_commands(repo_root)
    )
    python_targets = [
        str(path)
        for path in (target_files or [])
        if str(path).endswith(".py") and (repo_root / str(path)).exists()
    ]
    if python_targets:
        commands = [[sys.executable, "-m", "py_compile", *python_targets], *commands]
    if not commands:
        return {"commands": [], "status": "skipped"}

    results: List[Dict[str, Any]] = []
    failed_tests: List[str] = []
    failure_tokens: List[str] = []
    syntax_locations: List[Dict[str, Any]] = []
    for index, command in enumerate(commands, start=1):
        stdout_path = packet_dir / f"main-apply-validation-{index}.stdout.log"
        stderr_path = packet_dir / f"main-apply-validation-{index}.stderr.log"
        started = time.time()
        stdout_text = ""
        stderr_text = ""
        try:
            result = subprocess.run(
                command,
                cwd=repo_root,
                capture_output=True,
                env=_codex_apply_validation_env(),
                text=True,
                timeout=max(1.0, float(timeout_seconds)),
            )
            stdout_text = result.stdout or ""
            stderr_text = result.stderr or ""
            stdout_path.write_text(stdout_text, encoding="utf-8")
            stderr_path.write_text(stderr_text, encoding="utf-8")
            command_result = {
                "command": command,
                "duration_seconds": round(time.time() - started, 3),
                "exit_code": result.returncode,
                "status": "passed" if result.returncode == 0 else "failed",
                "stderr_path": str(stderr_path),
                "stdout_path": str(stdout_path),
            }
        except subprocess.TimeoutExpired as exc:
            stdout_text = _process_text(exc.stdout)
            stderr_text = _process_text(exc.stderr)
            stdout_path.write_text(stdout_text, encoding="utf-8")
            stderr_path.write_text(stderr_text, encoding="utf-8")
            command_result = {
                "command": command,
                "duration_seconds": round(time.time() - started, 3),
                "exit_code": None,
                "status": "timeout",
                "stderr_path": str(stderr_path),
                "stdout_path": str(stdout_path),
                "timeout_seconds": float(timeout_seconds),
            }
        if command_result["status"] != "passed":
            details = _codex_validation_failure_details(
                command=command,
                command_index=index,
                status=str(command_result["status"]),
                exit_code=command_result.get("exit_code"),
                stdout=stdout_text,
                stderr=stderr_text,
            )
            command_result.update(
                {
                    "failed_tests": list(details.get("failed_tests", []) or []),
                    "failure_tokens": list(details.get("failure_tokens", []) or []),
                    "syntax_locations": list(details.get("syntax_locations", []) or []),
                }
            )
            for test in command_result["failed_tests"]:
                if test not in failed_tests:
                    failed_tests.append(str(test))
            for token in command_result["failure_tokens"]:
                if token not in failure_tokens:
                    failure_tokens.append(str(token))
            for location in command_result["syntax_locations"]:
                if location not in syntax_locations:
                    syntax_locations.append(dict(location))
        results.append(command_result)
        if command_result["status"] != "passed":
            return {
                "commands": results,
                "failed_tests": failed_tests,
                "failure_tokens": failure_tokens,
                "status": command_result["status"],
                "syntax_locations": syntax_locations,
            }
    return {
        "commands": results,
        "failed_tests": failed_tests,
        "failure_tokens": failure_tokens,
        "status": "passed",
        "syntax_locations": syntax_locations,
    }


def _codex_packet_metric_sample_payloads(
    packet: Mapping[str, Any],
    *,
    max_samples: int = 8,
    payload_keys: Sequence[str] = ("metric_sample_payloads",),
) -> List[Dict[str, Any]]:
    """Return unique legal sample payloads carried by claimed TODO metadata."""
    payloads: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for todo in packet.get("todos", []):
        if not isinstance(todo, Mapping):
            continue
        metadata = dict(todo.get("metadata", {}) or {})
        for payload_key in payload_keys:
            for payload in metadata.get(str(payload_key), []) or []:
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


def _codex_packet_validation_metric_sample_payloads(
    packet: Mapping[str, Any],
    *,
    max_samples: int = 8,
) -> List[Dict[str, Any]]:
    """Return held-out validation sample payloads carried by claimed TODO metadata."""

    return _codex_packet_metric_sample_payloads(
        packet,
        max_samples=max_samples,
        payload_keys=("validation_metric_sample_payloads",),
    )


def _codex_packet_target_metric_names(packet: Mapping[str, Any]) -> List[str]:
    """Return target metrics declared by claimed TODO metadata."""
    metrics: List[str] = []
    for todo in packet.get("todos", []):
        if not isinstance(todo, Mapping):
            continue
        metadata = dict(todo.get("metadata", {}) or {})
        metrics.extend(str(metric) for metric in metadata.get("target_metrics", []) or [])
    return list(dict.fromkeys(metric for metric in metrics if metric))


def _codex_target_metric_bridge_adapter_names(metrics: Sequence[str]) -> List[str]:
    """Return bridge adapters needed to measure target metric names."""

    selected: List[str] = []

    def add(name: str) -> None:
        if name not in selected:
            selected.append(name)

    metric_names = [str(metric) for metric in metrics if str(metric)]
    for metric in metric_names:
        if metric.startswith("deontic_"):
            add("deontic_norms")
        elif metric.startswith("tdfol_"):
            add("fol_tdfol")
        elif metric.startswith("cec_"):
            add("cec_dcec")
        elif metric.startswith("zkp_"):
            add("zkp_attestation")
        elif metric.startswith("external_prover_") or "proof_failure_ratio" in metric:
            add("external_prover_router")
        elif "graph_failure_penalty" in metric:
            add("modal_frame_logic")
    if selected:
        return selected
    if any(metric.startswith("legal_ir_") for metric in metric_names):
        return list(DEFAULT_LEGAL_IR_BRIDGE_NAMES)
    return []


def _codex_packet_target_metric_snapshot(
    packet: Mapping[str, Any],
    repo_root: Path,
    *,
    sample_payloads: Optional[Sequence[Mapping[str, Any]]] = None,
    sample_role: str = "evidence",
    timeout_seconds: float = 120.0,
) -> Dict[str, Any]:
    """Measure target metrics in a fresh subprocess using packet sample payloads."""
    sample_payload_list = (
        [dict(payload) for payload in sample_payloads]
        if sample_payloads is not None
        else _codex_packet_metric_sample_payloads(packet)
    )
    target_metrics = _codex_packet_target_metric_names(packet)
    bridge_names = _codex_target_metric_bridge_adapter_names(target_metrics)
    if not sample_payload_list or not target_metrics:
        return {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payload_list),
            "sample_role": sample_role,
            "status": "skipped",
            "target_metrics": target_metrics,
        }
    script = r'''
import json
import sys

from ipfs_datasets_py.logic.bridge import DEFAULT_LEGAL_IR_BRIDGE_NAMES
from ipfs_datasets_py.logic.integration.reasoning import LegalIRHammerConfig, run_legal_ir_hammer
from ipfs_datasets_py.logic.modal import DeterministicModalLogicCodec, ModalLogicCodecConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import hammer_guidance_metric_block
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    _add_compiler_ir_metric_aliases,
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
    payload.get("bridge_names") or [],
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
hammer_requested = any(
    str(metric).startswith(("hammer_", "compiler_ir_hammer_"))
    or "symbolic_validity" in str(metric)
    or str(metric) in {
        "compiler_ir_source_copy_penalty",
        "hammer_source_copy_penalty",
        "source_copy_penalty",
    }
    for metric in target_metrics
)
if hammer_requested:
    hammer_artifacts = []
    hammer_reports = []
    for sample in samples:
        try:
            report = run_legal_ir_hammer(
                sample,
                config=LegalIRHammerConfig(
                    max_obligations=4,
                    max_premises=64,
                    parallel_workers=1,
                    timeout_seconds=2.0,
                    verify_reconstruction=False,
                ),
            ).to_dict()
        except Exception as exc:
            report = {
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                "status": "failed",
            }
        hammer_reports.append(report)
        for artifact in report.get("artifacts", []) or []:
            if isinstance(artifact, dict):
                hammer_artifacts.append(artifact)
    hammer_metrics = hammer_guidance_metric_block(
        {"hammer_guidance_artifacts": hammer_artifacts}
    )
    for key, value in hammer_metrics.items():
        if isinstance(value, (int, float)):
            metrics[str(key)] = float(value)
    compiler["hammer_guidance_metrics"] = hammer_metrics
    compiler["hammer_reports"] = hammer_reports[:8]
metrics = {
    str(key): float(value)
    for key, value in _add_compiler_ir_metric_aliases(metrics).items()
    if isinstance(value, (int, float))
}
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
    payload = {
        "bridge_names": bridge_names,
        "samples": sample_payload_list,
        "target_metrics": target_metrics,
    }
    result = accelerate_run_process_group_capture(
        [sys.executable, "-c", script],
        cwd=repo_root,
        input_text=json.dumps(payload, ensure_ascii=True),
        env=_codex_apply_validation_env(),
        timeout_seconds=max(1.0, float(timeout_seconds)),
    )
    if str(result.get("status") or "") == "timeout":
        return {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payload_list),
            "sample_role": sample_role,
            "status": "timeout",
            "stderr_tail": str(result.get("stderr") or "")[-500:],
            "stdout_tail": str(result.get("stdout") or "")[-500:],
            "target_bridge_names": bridge_names,
            "target_metrics": target_metrics,
            "timeout_seconds": float(timeout_seconds),
        }
    if int(result.get("exit_code") or 0) != 0:
        return {
            "exit_code": result.get("exit_code"),
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payload_list),
            "sample_role": sample_role,
            "status": "failed",
            "stderr_tail": str(result.get("stderr") or "")[-500:],
            "stdout_tail": str(result.get("stdout") or "")[-500:],
            "target_bridge_names": bridge_names,
            "target_metrics": target_metrics,
        }
    try:
        stdout_lines = [
            line for line in str(result.get("stdout") or "").splitlines() if line.strip()
        ]
        snapshot = json.loads(stdout_lines[-1] if stdout_lines else "")
    except json.JSONDecodeError:
        return {
            "exit_code": result.get("exit_code"),
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(sample_payload_list),
            "sample_role": sample_role,
            "status": "invalid_json",
            "stderr_tail": str(result.get("stderr") or "")[-500:],
            "stdout_tail": str(result.get("stdout") or "")[-500:],
            "target_bridge_names": bridge_names,
            "target_metrics": target_metrics,
        }
    snapshot["stderr_tail"] = str(result.get("stderr") or "")[-500:]
    snapshot["sample_role"] = sample_role
    snapshot["target_bridge_names"] = list(
        snapshot.get("target_bridge_names") or bridge_names
    )
    snapshot["timeout_seconds"] = float(timeout_seconds)
    return snapshot


def _codex_target_metric_timeout_seconds(validation_timeout_seconds: float) -> float:
    """Return the subprocess budget for Codex target metric snapshots."""

    try:
        requested = float(validation_timeout_seconds)
    except (TypeError, ValueError):
        requested = DEFAULT_CODEX_TARGET_METRIC_TIMEOUT_SECONDS
    raw_cap = str(os.environ.get(CODEX_TARGET_METRIC_TIMEOUT_SECONDS_ENV) or "").strip()
    try:
        cap = float(raw_cap) if raw_cap else DEFAULT_CODEX_TARGET_METRIC_TIMEOUT_SECONDS
    except ValueError:
        cap = DEFAULT_CODEX_TARGET_METRIC_TIMEOUT_SECONDS
    return max(1.0, min(max(1.0, requested), max(1.0, cap)))


def _call_codex_packet_target_metric_snapshot(
    packet: Mapping[str, Any],
    repo_root: Path,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Call target metric snapshot while tolerating older two-arg monkeypatches."""

    try:
        signature = inspect.signature(_codex_packet_target_metric_snapshot)
        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        unsupported = [
            name
            for name in kwargs
            if name not in signature.parameters and not accepts_var_kwargs
        ]
        if unsupported:
            return _codex_packet_target_metric_snapshot(packet, repo_root)
    except (TypeError, ValueError):
        pass
    return _codex_packet_target_metric_snapshot(packet, repo_root, **kwargs)


def _codex_packet_should_measure_target_metrics(
    packet: Mapping[str, Any],
    *,
    target_files: Sequence[str],
) -> bool:
    """Return true when packet metadata and changed files justify metric checks."""
    if not (
        _codex_packet_metric_sample_payloads(packet)
        or _codex_packet_validation_metric_sample_payloads(packet)
    ):
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
    deadband_by_metric: Dict[str, float] = {}
    metric_deltas: Dict[str, float] = {}
    metric_weights: Dict[str, float] = {}
    improved_metrics: List[str] = []
    raw_regressed_metrics: List[str] = []
    hard_regressed_metrics: List[str] = []
    hard_guardrail_metrics: List[str] = []
    tolerated_regressed_metrics: List[str] = []
    missing_metrics: List[str] = []
    objective_delta = 0.0
    weighted_metric_deltas: Dict[str, float] = {}
    for metric in target_metrics:
        if metric not in before_metrics or metric not in after_metrics:
            missing_metrics.append(str(metric))
            continue
        metric_name = str(metric)
        delta = _target_metric_improvement_delta(
            metric_name,
            before_value=float(before_metrics[metric]),
            after_value=float(after_metrics[metric]),
        )
        weight = _codex_target_metric_weight(metric_name)
        weighted_delta = delta * weight
        objective_delta += weighted_delta
        deadband = _codex_target_metric_deadband(metric_name)
        deadband_by_metric[metric_name] = round(deadband, 9)
        metric_deltas[metric_name] = round(delta, 9)
        metric_weights[metric_name] = round(weight, 6)
        weighted_metric_deltas[metric_name] = round(weighted_delta, 9)
        hard_guardrail = _codex_target_metric_is_hard_guardrail(metric_name)
        if hard_guardrail:
            hard_guardrail_metrics.append(metric_name)
        if delta > 0.0:
            improved_metrics.append(metric_name)
        elif delta < 0.0:
            raw_regressed_metrics.append(metric_name)
            if hard_guardrail:
                hard_regressed_metrics.append(metric_name)
            elif abs(delta) <= deadband:
                tolerated_regressed_metrics.append(metric_name)
            else:
                hard_regressed_metrics.append(metric_name)
    before_status = str(before.get("status") or "")
    after_status = str(after.get("status") or "")
    if before_status == "skipped" or after_status == "skipped":
        status = "skipped"
    elif before_status != "measured" or after_status != "measured":
        status = "unavailable"
    elif hard_regressed_metrics:
        status = "regressed"
    elif raw_regressed_metrics:
        status = "passed_with_tradeoff" if objective_delta > 0.0 else "regressed"
        if status == "regressed":
            hard_regressed_metrics = list(raw_regressed_metrics)
            tolerated_regressed_metrics = []
    else:
        status = "passed"
    return {
        "after": dict(after),
        "before": dict(before),
        "deadband_by_metric": deadband_by_metric,
        "gate_policy": CODEX_TARGET_METRIC_TRADEOFF_POLICY_VERSION,
        "hard_guardrail_metrics": hard_guardrail_metrics,
        "hard_regressed_metrics": hard_regressed_metrics,
        "improved_metrics": improved_metrics,
        "metric_deltas": metric_deltas,
        "metric_weights": metric_weights,
        "missing_metrics": missing_metrics,
        "objective_delta": round(objective_delta, 9),
        "raw_regressed_metrics": raw_regressed_metrics,
        "regressed_metrics": hard_regressed_metrics,
        "status": status,
        "target_metrics": target_metrics,
        "tolerated_regressed_metrics": tolerated_regressed_metrics,
        "weighted_metric_deltas": weighted_metric_deltas,
    }


def _codex_target_metric_is_hard_guardrail(metric_name: str) -> bool:
    """Return true when a metric cannot be traded off against cosmetic gains."""

    normalized = str(metric_name)
    lower = normalized.lower()
    if "source_copy" in lower or "copy_reward_hack" in lower:
        return True
    if "symbolic_validity" in lower:
        return True
    if lower.startswith("hammer_") or "_hammer_" in lower:
        return True
    if lower.startswith("compiler_ir_hammer_"):
        return True
    if lower in {
        "legal_ir_multiview_graph_failure_penalty",
        "legal_ir_multiview_proof_failure_ratio",
    }:
        return True
    if lower.startswith(("deontic_", "tdfol_", "cec_", "external_prover_")) and (
        "failure" in lower or "validity" in lower or "proof" in lower
    ):
        return True
    return False


def _codex_target_metric_deadband(metric_name: str) -> float:
    """Return the tolerated negative delta for noisy target metrics."""

    normalized = str(metric_name)
    if _codex_target_metric_is_hard_guardrail(normalized):
        return 0.0
    if normalized in {
        "source_decompiled_text_token_loss",
        "structural_text_reconstruction_loss",
    } or normalized.endswith(
        (
            "source_decompiled_text_token_loss",
            "structural_text_reconstruction_loss",
        )
    ):
        return 0.005
    if normalized == "source_copy_reward_hack_penalty" or normalized.endswith(
        "source_copy_reward_hack_penalty"
    ):
        return 0.002
    if (
        normalized in {"embedding_cosine_similarity", "cosine_similarity"}
        or normalized.endswith("_similarity")
        or normalized.endswith("_score")
        or normalized.endswith("_rate")
    ) and not normalized.endswith("_loss"):
        return 0.002
    if "cosine" in normalized and normalized.endswith("_loss"):
        return 0.0001
    if normalized == "cross_entropy_loss" or normalized.endswith("_cross_entropy_loss"):
        return 0.0001
    if normalized in {"reconstruction_loss", "text_reconstruction_loss"}:
        return 0.001
    if normalized.endswith("_reconstruction_loss"):
        return 0.001
    return 0.0


def _codex_target_metric_weight(metric_name: str) -> float:
    """Return the weighted objective contribution for a target metric."""

    normalized = str(metric_name)
    if _codex_target_metric_is_hard_guardrail(normalized):
        return 6.0
    if normalized in {
        "cross_entropy_loss",
        "compiler_ir_cross_entropy_loss",
        "legal_ir_view_cross_entropy_loss",
    } or normalized.endswith("_cross_entropy_loss"):
        return 4.0
    if (
        normalized in {"embedding_cosine_similarity", "cosine_similarity"}
        or normalized.endswith("_similarity")
        or normalized.endswith("_score")
        or normalized.endswith("_rate")
    ) and not normalized.endswith("_loss"):
        return 4.0
    if normalized == "source_decompiled_text_embedding_cosine_loss" or normalized.endswith(
        "source_decompiled_text_embedding_cosine_loss"
    ):
        return 4.0
    if "legal_ir" in normalized and "cosine" in normalized:
        return 3.0
    if normalized == "source_copy_reward_hack_penalty" or normalized.endswith(
        "source_copy_reward_hack_penalty"
    ):
        return 3.0
    if normalized in {"reconstruction_loss", "legal_ir_multiview_reconstruction_loss"}:
        return 2.0
    if normalized == "compiler_ir_reconstruction_loss":
        return 2.0
    if normalized.startswith(("deontic_", "tdfol_", "cec_", "zkp_", "external_prover_")):
        return 2.0
    return 1.0


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


def _target_metric_improvement_delta_map(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    target_metrics: Sequence[str],
) -> Dict[str, float]:
    """Return rounded positive-is-better deltas for comparable metric mappings."""

    before_metrics = dict(before or {})
    after_metrics = dict(after or {})
    deltas: Dict[str, float] = {}
    for metric in target_metrics:
        metric_name = str(metric)
        if metric_name not in before_metrics or metric_name not in after_metrics:
            continue
        before_value = before_metrics[metric_name]
        after_value = after_metrics[metric_name]
        if not isinstance(before_value, (int, float)) or not isinstance(
            after_value, (int, float)
        ):
            continue
        deltas[metric_name] = round(
            _target_metric_improvement_delta(
                metric_name,
                before_value=float(before_value),
                after_value=float(after_value),
            ),
            9,
        )
    return deltas


def _codex_validation_failure_tokens(validation: Mapping[str, Any]) -> List[str]:
    tokens = [str(token) for token in validation.get("failure_tokens", []) or [] if str(token)]
    if tokens:
        return list(dict.fromkeys(tokens))
    extracted: List[str] = []
    for command in validation.get("commands", []) or []:
        if not isinstance(command, Mapping):
            continue
        for token in command.get("failure_tokens", []) or []:
            if str(token):
                extracted.append(str(token))
    return list(dict.fromkeys(extracted))


def _codex_validation_comparison(
    packet_validation: Mapping[str, Any],
    baseline_validation: Mapping[str, Any],
) -> Dict[str, Any]:
    packet_tokens = _codex_validation_failure_tokens(packet_validation)
    baseline_tokens = _codex_validation_failure_tokens(baseline_validation)
    packet_set = set(packet_tokens)
    baseline_set = set(baseline_tokens)
    return {
        "baseline_failure_tokens": baseline_tokens,
        "baseline_only_failure_tokens": [
            token for token in baseline_tokens if token not in packet_set
        ],
        "packet_failure_tokens": packet_tokens,
        "packet_only_failure_tokens": [
            token for token in packet_tokens if token not in baseline_set
        ],
        "shared_failure_tokens": [
            token for token in packet_tokens if token in baseline_set
        ],
    }


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
    validation_metric_payloads = _codex_packet_validation_metric_sample_payloads(updated)
    target_metric_timeout_seconds = _codex_target_metric_timeout_seconds(
        validation_timeout_seconds
    )
    target_metric_before = (
        _call_codex_packet_target_metric_snapshot(
            updated,
            source_repo_root,
            sample_role="evidence",
            timeout_seconds=target_metric_timeout_seconds,
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
    holdout_target_metric_before = (
        _call_codex_packet_target_metric_snapshot(
            updated,
            source_repo_root,
            sample_payloads=validation_metric_payloads,
            sample_role="holdout",
            timeout_seconds=target_metric_timeout_seconds,
        )
        if measure_target_metrics and validation_metric_payloads
        else {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(validation_metric_payloads),
            "sample_role": "holdout",
            "status": "skipped",
            "target_metrics": _codex_packet_target_metric_names(updated),
        }
    )
    updated["holdout_target_metric_baseline"] = holdout_target_metric_before

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
        target_files=target_files,
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
                target_files=target_files,
                validation_commands=validation_commands,
                timeout_seconds=validation_timeout_seconds,
            )
        updated["main_apply_baseline_validation"] = baseline_validation
        if baseline_validation["status"] not in {"passed", "skipped"}:
            comparison = _codex_validation_comparison(validation, baseline_validation)
            updated["main_apply_validation_comparison"] = comparison
            if rollback.returncode == 0 and not comparison["packet_only_failure_tokens"]:
                reapply = _run_git_apply_stdin(source_repo_root, diff_content)
                updated["main_apply_reapply_after_baseline_validation"] = {
                    "exit_code": reapply.returncode,
                    "stderr_tail": (reapply.stderr or "")[-500:],
                    "stdout_tail": (reapply.stdout or "")[-500:],
                }
                if reapply.returncode == 0:
                    updated["main_apply_baseline_failure_accepted"] = True
                    updated["main_apply_validation_gate"] = "inconclusive_baseline_failed"
                    if str(commit_mode).strip().lower() == "commit_applied":
                        try:
                            commit = _commit_codex_main_changes(
                                source_repo_root,
                                packet=updated,
                                target_files=target_files,
                            )
                        except (
                            OSError,
                            RuntimeError,
                            subprocess.SubprocessError,
                            ValueError,
                        ) as exc:
                            commit = {
                                "status": "failed",
                                "error": str(exc),
                                "step": "commit",
                            }
                        updated["main_commit"] = commit
                        if commit["status"] != "committed":
                            subprocess.run(
                                ["git", "reset", "--", *target_files],
                                cwd=source_repo_root,
                                capture_output=True,
                                text=True,
                                timeout=60.0,
                            )
                            rollback = _run_git_apply_stdin(
                                source_repo_root,
                                diff_content,
                                "-R",
                            )
                            updated["main_apply_rollback"] = {
                                "exit_code": rollback.returncode,
                                "stderr_tail": (rollback.stderr or "")[-500:],
                                "stdout_tail": (rollback.stdout or "")[-500:],
                            }
                            patch_path = _save_codex_packet_diff_patch(
                                updated,
                                diff_content=diff_content,
                                reason="baseline-accepted-commit-failed",
                            )
                            updated["patch_path"] = (
                                str(patch_path) if patch_path is not None else None
                            )
                            updated["patch_status"] = (
                                "main_apply_baseline_accepted_commit_failed_rolled_back"
                                if rollback.returncode == 0
                                else "main_apply_baseline_accepted_commit_failed_rollback_failed"
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
            patch_path = _save_codex_packet_diff_patch(
                updated,
                diff_content=diff_content,
                reason="validation-failed",
            )
            updated["patch_path"] = str(patch_path) if patch_path is not None else None
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
        _call_codex_packet_target_metric_snapshot(
            updated,
            source_repo_root,
            sample_role="evidence",
            timeout_seconds=target_metric_timeout_seconds,
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
    holdout_target_metric_after = (
        _call_codex_packet_target_metric_snapshot(
            updated,
            source_repo_root,
            sample_payloads=validation_metric_payloads,
            sample_role="holdout",
            timeout_seconds=target_metric_timeout_seconds,
        )
        if measure_target_metrics and validation_metric_payloads
        else {
            "metric_count": 0,
            "metrics": {},
            "sample_count": len(validation_metric_payloads),
            "sample_role": "holdout",
            "status": "skipped",
            "target_metrics": _codex_packet_target_metric_names(updated),
        }
    )
    holdout_target_metric_validation = _codex_target_metric_validation_report(
        before=holdout_target_metric_before,
        after=holdout_target_metric_after,
    )
    updated["target_metric_validation"] = target_metric_validation
    updated["holdout_target_metric_validation"] = holdout_target_metric_validation
    updated["metric_deltas"] = dict(target_metric_validation.get("metric_deltas", {}))
    updated["holdout_metric_deltas"] = dict(
        holdout_target_metric_validation.get("metric_deltas", {})
    )
    if (
        target_metric_validation["status"] == "unavailable"
        or holdout_target_metric_validation["status"] == "unavailable"
    ):
        updated["main_apply_target_metric_gate"] = "diagnostic_unavailable"
    elif (
        target_metric_validation["status"] == "skipped"
        and holdout_target_metric_validation["status"] == "skipped"
    ):
        updated["main_apply_target_metric_gate"] = "skipped"
    elif (
        target_metric_validation["status"] == "passed_with_tradeoff"
        or holdout_target_metric_validation["status"] == "passed_with_tradeoff"
    ):
        updated["main_apply_target_metric_gate"] = "passed_with_tradeoff"
    else:
        updated["main_apply_target_metric_gate"] = "passed"
    if (
        target_metric_validation["status"] == "regressed"
        or holdout_target_metric_validation["status"] == "regressed"
    ):
        updated["main_apply_target_metric_gate"] = "regressed"
        rollback = _run_git_apply_stdin(source_repo_root, diff_content, "-R")
        updated["main_apply_rollback"] = {
            "exit_code": rollback.returncode,
            "stderr_tail": (rollback.stderr or "")[-500:],
            "stdout_tail": (rollback.stdout or "")[-500:],
        }
        patch_path = _save_codex_packet_diff_patch(
            updated,
            diff_content=diff_content,
            reason=(
                "holdout-target-metric-regression"
                if holdout_target_metric_validation["status"] == "regressed"
                else "target-metric-regression"
            ),
        )
        updated["patch_path"] = str(patch_path) if patch_path is not None else None
        updated["patch_status"] = (
            "main_apply_target_metric_regression_rolled_back"
            if rollback.returncode == 0
            else "main_apply_target_metric_regression_rollback_failed"
        )
        updated["patch_error"] = (
            "holdout target metric regression"
            if holdout_target_metric_validation["status"] == "regressed"
            else "target metric regression"
        )
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
    main_apply_lock_timeout_seconds: Optional[float] = None,
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
            refreshed = _codex_packet_main_apply_lock_timeout(updated, exc)
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
                refreshed = _codex_packet_main_apply_lock_timeout(refreshed, exc)
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

    normalized_patch_status = patch_status.strip().lower()
    if normalized_patch_status in CODEX_COMPLETED_WORK_STATUSES:
        return False
    if normalized_patch_status == "main_apply_lock_timeout":
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
    holdout_target_metric_validation = dict(
        packet.get("holdout_target_metric_validation", {}) or {}
    )
    baseline_failure_accepted = bool(packet.get("main_apply_baseline_failure_accepted"))
    validation_status = (
        "passed"
        if baseline_failure_accepted
        else main_validation.get("status")
        or packet.get("main_apply_status")
        or packet.get("patch_status")
        or "not_measured"
    )
    failed_command: List[str] = []
    for command in main_validation.get("commands", []) or []:
        if isinstance(command, Mapping) and command.get("status") not in {
            "passed",
            None,
        }:
            failed_command = [str(part) for part in command.get("command", []) or []]
            break
    return {
        "baseline_failure_accepted": baseline_failure_accepted,
        "baseline_status": baseline_validation.get("status"),
        "holdout_hard_regressed_metrics": list(
            holdout_target_metric_validation.get("hard_regressed_metrics", []) or []
        ),
        "holdout_metric_deltas": dict(packet.get("holdout_metric_deltas", {}) or {}),
        "holdout_objective_delta": holdout_target_metric_validation.get("objective_delta"),
        "holdout_raw_regressed_metrics": list(
            holdout_target_metric_validation.get("raw_regressed_metrics", []) or []
        ),
        "holdout_regressed_metrics": list(
            holdout_target_metric_validation.get("regressed_metrics", []) or []
        ),
        "holdout_target_metric_status": holdout_target_metric_validation.get("status"),
        "holdout_tolerated_regressed_metrics": list(
            holdout_target_metric_validation.get("tolerated_regressed_metrics", []) or []
        ),
        "main_apply_validation_gate": packet.get("main_apply_validation_gate"),
        "main_apply_validation_failed_command": failed_command,
        "main_apply_validation_failed_tests": list(
            main_validation.get("failed_tests", []) or []
        ),
        "main_apply_validation_failure_tokens": _codex_validation_failure_tokens(
            main_validation
        ),
        "main_apply_validation_syntax_locations": list(
            main_validation.get("syntax_locations", []) or []
        ),
        "main_apply_status": packet.get("main_apply_status"),
        "metric_deltas": dict(packet.get("metric_deltas", {}) or {}),
        "objective_delta": target_metric_validation.get("objective_delta"),
        "patch_status": packet.get("patch_status"),
        "raw_regressed_metrics": list(
            target_metric_validation.get("raw_regressed_metrics", []) or []
        ),
        "regressed_metrics": list(target_metric_validation.get("regressed_metrics", []) or []),
        "target_metric_gate_policy": target_metric_validation.get("gate_policy"),
        "target_metric_hard_regressed_metrics": list(
            target_metric_validation.get("hard_regressed_metrics", []) or []
        ),
        "status": validation_status,
        "target_metric_status": target_metric_validation.get("status"),
        "tolerated_regressed_metrics": list(
            target_metric_validation.get("tolerated_regressed_metrics", []) or []
        ),
    }


def _target_metric_report_sample_count(report: Mapping[str, Any]) -> Optional[int]:
    for side in ("after", "before"):
        side_value = report.get(side)
        if not isinstance(side_value, Mapping):
            continue
        compiler = side_value.get("compiler")
        if not isinstance(compiler, Mapping):
            continue
        value = compiler.get("sample_count")
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _codex_packet_metric_event_fields(packet: Mapping[str, Any]) -> Dict[str, Any]:
    target_report = dict(packet.get("target_metric_validation", {}) or {})
    holdout_report = dict(packet.get("holdout_target_metric_validation", {}) or {})
    fields: Dict[str, Any] = {
        "holdout_metric_deltas": dict(packet.get("holdout_metric_deltas", {}) or {}),
        "holdout_target_metric_hard_regressed_metrics": list(
            holdout_report.get("hard_regressed_metrics", []) or []
        ),
        "holdout_target_metric_objective_delta": holdout_report.get("objective_delta"),
        "holdout_target_metric_regressed_metrics": list(
            holdout_report.get("regressed_metrics", []) or []
        ),
        "holdout_target_metric_sample_count": _target_metric_report_sample_count(
            holdout_report
        ),
        "holdout_target_metric_status": holdout_report.get("status"),
        "main_apply_target_metric_gate": packet.get("main_apply_target_metric_gate"),
        "metric_deltas": dict(packet.get("metric_deltas", {}) or {}),
        "target_metric_hard_regressed_metrics": list(
            target_report.get("hard_regressed_metrics", []) or []
        ),
        "target_metric_objective_delta": target_report.get("objective_delta"),
        "target_metric_regressed_metrics": list(
            target_report.get("regressed_metrics", []) or []
        ),
        "target_metric_sample_count": _target_metric_report_sample_count(target_report),
        "target_metric_status": target_report.get("status"),
    }
    return {
        key: value
        for key, value in fields.items()
        if value not in ({}, [], None, "")
    }


def _program_synthesis_metric_feedback_report(
    queue: ModalTodoQueue,
    *,
    compiler_ir_validation_sample_ids: Sequence[str],
) -> Dict[str, Any]:
    """Summarize whether program-synthesis work is visible to compiler-IR canaries."""
    canary_ids = {
        str(sample_id)
        for sample_id in compiler_ir_validation_sample_ids
        if str(sample_id).strip()
    }
    status_counts: Counter[str] = Counter()
    status_unique_samples: Dict[str, set[str]] = {}
    status_canary_overlap_samples: Dict[str, set[str]] = {}
    status_canary_overlap_todos: Counter[str] = Counter()
    completed_target_status: Counter[str] = Counter()
    completed_holdout_status: Counter[str] = Counter()
    failed_reasons: Counter[str] = Counter()
    completed_metric_delta_sums: Counter[str] = Counter()
    completed_holdout_metric_delta_sums: Counter[str] = Counter()

    for todo in queue.all():
        if str(todo.metadata.get("optimizer_role") or "") != PROGRAM_SYNTHESIS_ROLE:
            continue
        status = str(todo.status or "unknown")
        status_counts[status] += 1
        sample_ids = {
            str(sample_id)
            for sample_id in list(todo.sample_ids or [])
            if str(sample_id).strip()
        }
        status_unique_samples.setdefault(status, set()).update(sample_ids)
        overlap = sample_ids & canary_ids
        status_canary_overlap_samples.setdefault(status, set()).update(overlap)
        if overlap:
            status_canary_overlap_todos[status] += 1

        if status == "completed":
            completed_report = todo.metadata.get("completed_validation_report")
            if isinstance(completed_report, Mapping):
                target_status = str(
                    completed_report.get("target_metric_status") or ""
                ).strip()
                holdout_status = str(
                    completed_report.get("holdout_target_metric_status") or ""
                ).strip()
                if target_status:
                    completed_target_status[target_status] += 1
                if holdout_status:
                    completed_holdout_status[holdout_status] += 1
                for metric, value in dict(
                    completed_report.get("metric_deltas", {}) or {}
                ).items():
                    if isinstance(value, (int, float)) and math.isfinite(float(value)):
                        completed_metric_delta_sums[str(metric)] += float(value)
                for metric, value in dict(
                    completed_report.get("holdout_metric_deltas", {}) or {}
                ).items():
                    if isinstance(value, (int, float)) and math.isfinite(float(value)):
                        completed_holdout_metric_delta_sums[str(metric)] += float(value)
        elif status == "failed_validation":
            reason = str(
                todo.metadata.get("failed_validation_reason")
                or todo.metadata.get("failure_reason")
                or "unknown"
            ).strip()
            failed_reasons[reason or "unknown"] += 1

    def rounded_counter(counter: Counter[str]) -> Dict[str, float]:
        return {
            str(key): round(float(value), 9)
            for key, value in sorted(counter.items())
        }

    report: Dict[str, Any] = {
        "canary_sample_count": len(canary_ids),
        "canary_sample_ids": sorted(canary_ids),
        "completed_canary_blind": bool(
            status_unique_samples.get("completed")
            and not status_canary_overlap_samples.get("completed")
        ),
        "completed_holdout_target_metric_status_counts": dict(
            sorted(completed_holdout_status.items())
        ),
        "completed_metric_delta_sums": rounded_counter(
            completed_metric_delta_sums
        ),
        "completed_target_metric_status_counts": dict(
            sorted(completed_target_status.items())
        ),
        "failed_validation_reason_counts": dict(sorted(failed_reasons.items())),
        "status_counts": dict(sorted(status_counts.items())),
    }
    for status in sorted(status_counts):
        unique_samples = status_unique_samples.get(status, set())
        overlap_samples = status_canary_overlap_samples.get(status, set())
        report[f"{status}_unique_sample_count"] = len(unique_samples)
        report[f"{status}_canary_overlap_sample_count"] = len(overlap_samples)
        report[f"{status}_canary_overlap_todo_count"] = int(
            status_canary_overlap_todos.get(status, 0)
        )
        if overlap_samples:
            report[f"{status}_canary_overlap_sample_ids"] = sorted(overlap_samples)
    holdout_delta_sums = rounded_counter(completed_holdout_metric_delta_sums)
    if holdout_delta_sums:
        report["completed_holdout_metric_delta_sums"] = holdout_delta_sums
    return report


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
    holdout_sample_count = 0
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
        holdout_sample_count += len(
            [
                payload
                for payload in _metadata_sequence(
                    todo.metadata.get("validation_metric_sample_payloads", [])
                )
                if isinstance(payload, Mapping)
            ]
        )
    unique_metrics = list(dict.fromkeys(target_metrics))
    if not unique_metrics and not sample_count and not holdout_sample_count:
        return []
    lines = [
        "## Metric Guard",
        "The daemon remeasures these target metrics before and after applying the worktree diff.",
        "Hard target-metric regressions are rolled back; tiny noisy text-metric regressions may pass only when the weighted compiler/IR objective improves.",
    ]
    if unique_metrics:
        lines.append(f"- Target metrics: `{', '.join(unique_metrics)}`")
    if sample_count:
        lines.append(f"- Metric sample payloads: `{sample_count}` across claimed TODOs")
    if holdout_sample_count:
        lines.append(
            f"- Holdout metric sample payloads: `{holdout_sample_count}` across claimed TODOs"
        )
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
    seed, seed_source = _sampling_seed_for_args(args)
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
        "bridge_evaluate_provers": bool(
            getattr(args, "bridge_evaluate_provers", _default_bridge_evaluate_provers())
        ),
        "bridge_loss_adapters": bridge_loss_adapter_names(args),
        "bridge_loss_failures": 0,
        "bridge_loss_samples": 0,
        "bridge_loss_signals": 0,
        "bridge_metric_failures": 0,
        "contract_telemetry_schema_version": LEGAL_IR_CONTRACT_TELEMETRY_SCHEMA_VERSION,
        "legal_ir_contract_coverage": 0.0,
        "legal_ir_contract_failure_counts": {},
        "legal_ir_contract_view_family_gaps": {},
        "cycles": 0,
        "codex_program_synthesis_execution_mode": "queued_for_external_codex_worker",
        "dataset_id": HF_USCODE_DATASET_ID,
        "final": False,
        "laws_path": USCODE_LAWS_PARQUET,
        "log_path": str(log_path),
        "loop_role": getattr(args, "loop_role", "autoencoder"),
        "max_cycles": max(0, int(getattr(args, "max_cycles", 0) or 0)),
        "metric_schema_version": AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION,
        "autoencoder_architecture_version": MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
        "autoencoder_state_schema_version": MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
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
        "sampling_seed_source": seed_source,
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
        scale *= 0.9 ** float(plateau_streak - 2)
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
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="Stop after this many completed cycles; zero is duration-only.",
    )
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
    parser.add_argument("--sampling-seed", default=None)
    parser.add_argument("--autoencoder-bootstrap-mode", default="fast")
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
        "--generalizable-projection-timeout-seconds",
        type=float,
        default=DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--generalizable-projection-max-line-search-attempts",
        type=int,
        default=DEFAULT_GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS,
    )
    parser.add_argument("--autoencoder-projection-deadband-mode", default="shadow")
    parser.add_argument("--autoencoder-max-ce-deadband", type=float, default=0.0001)
    parser.add_argument(
        "--autoencoder-hard-guardrail-metrics",
        default="compiler_ir_cosine,structural_validity,source_copy_penalty",
    )
    parser.add_argument("--autoencoder-projection-prescreen-mode", default="off")
    parser.add_argument("--autoencoder-projection-prescreen-top-k", type=int, default=3)
    parser.add_argument(
        "--autoencoder-projection-periodic-full-search-every-n-cycles",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--autoencoder-metric-bridge-adapters",
        default="default",
    )
    parser.add_argument(
        "--autoencoder-diagnostic-bridge-adapters",
        default="none",
    )
    parser.add_argument(
        "--autoencoder-metric-bridge-max-sample-text-chars",
        type=int,
        default=DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
    )
    parser.add_argument(
        "--compiler-ir-metric-text-policy",
        choices=COMPILER_IR_METRIC_TEXT_POLICIES,
        default=DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY,
    )
    parser.add_argument(
        "--compiler-ir-metric-max-sample-text-chars",
        type=int,
        default=_default_compiler_ir_metric_max_sample_text_chars(),
        help=(
            "Dedicated deterministic compiler metric text budget. This does not "
            "truncate the autoencoder training sample itself."
        ),
    )
    parser.add_argument(
        "--compiler-ir-metric-sample-timeout-seconds",
        type=float,
        default=DEFAULT_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS,
    )
    parser.add_argument("--compiler-ir-train-mode", default=DEFAULT_COMPILER_IR_TRAIN_MODE)
    parser.add_argument("--compiler-ir-train-every-n-cycles", type=int, default=4)
    parser.add_argument(
        "--compiler-ir-guided-train-mode",
        default=DEFAULT_COMPILER_IR_GUIDED_TRAIN_MODE,
    )
    parser.add_argument("--compiler-ir-guided-train-every-n-cycles", type=int, default=4)
    parser.add_argument(
        "--autoencoder-before-train-eval-mode",
        default=DEFAULT_AUTOENCODER_BEFORE_TRAIN_EVAL_MODE,
    )
    parser.add_argument("--autoencoder-before-train-eval-every-n-cycles", type=int, default=4)
    parser.add_argument(
        "--autoencoder-sample-memory-probe-mode",
        default=DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE,
    )
    parser.add_argument("--autoencoder-sample-memory-probe-every-n-cycles", type=int, default=4)
    parser.add_argument(
        "--autoencoder-todo-supervisor-mode",
        default=DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE,
    )
    parser.add_argument("--autoencoder-todo-supervisor-min-open", type=int, default=12)
    parser.add_argument(
        "--autoencoder-introspection-mode",
        choices=tuple(sorted(MODAL_INTROSPECTION_MODES)),
        default=DEFAULT_AUTOENCODER_INTROSPECTION_MODE,
        help=(
            "Reversible LegalIR introspection rollout mode. 'off' is inert, "
            "'export' emits evidence, 'shadow' observes, 'seed' may create "
            "bounded TODOs, and 'enforce' fails closed when proof/budget gates fail."
        ),
    )
    parser.add_argument(
        "--autoencoder-introspection-every-n-cycles",
        type=int,
        default=DEFAULT_AUTOENCODER_INTROSPECTION_EVERY_N_CYCLES,
        help=(
            "Run full disagreement introspection on cycle one and then at this "
            "cadence; verified Leanstral report projection still runs every cycle."
        ),
    )
    parser.add_argument(
        "--autoencoder-introspection-min-export-samples",
        type=int,
        default=DEFAULT_AUTOENCODER_INTROSPECTION_MIN_EXPORT_SAMPLES,
        help=(
            "Minimum validation samples to export as canonical disagreement "
            "packets when introspection export is due. This can be higher than "
            "--autoencoder-max-audits-per-cycle because it does not increase "
            "the Codex TODO audit budget."
        ),
    )
    parser.add_argument("--autoencoder-max-audits-per-cycle", type=int, default=0)
    parser.add_argument("--autoencoder-max-todos-per-cycle", type=int, default=0)
    parser.add_argument(
        "--leanstral-rule-gap-projection-enabled",
        type=parse_bool_flag,
        default=True,
        help="Seed Codex TODOs from verified Leanstral rule-gap reports.",
    )
    parser.add_argument(
        "--leanstral-rule-gap-report-path",
        default="",
        help=(
            "Verified Leanstral rule-gap JSON report. Defaults to "
            "workspace/leanstral-audit-worker/<run-id>.rule-gaps.json."
        ),
    )
    parser.add_argument(
        "--leanstral-rule-gap-max-todos-per-scope",
        type=int,
        default=2,
        help="Maximum active Leanstral-seeded TODOs per owned compiler/AST scope.",
    )
    parser.add_argument(
        "--leanstral-rule-gap-require-executor-available",
        type=parse_bool_flag,
        default=True,
        help="Block Leanstral TODO seeding when Codex executor health is unavailable.",
    )
    parser.add_argument(
        "--leanstral-rule-gap-expected-compiler-commit",
        default="",
        help="Optional compiler commit hash required on the rule-gap report.",
    )
    parser.add_argument(
        "--leanstral-rule-gap-expected-state-hash",
        default="",
        help="Optional autoencoder state hash required on the rule-gap report.",
    )
    parser.add_argument(
        "--leanstral-rule-gap-max-report-age-seconds",
        type=float,
        default=None,
        help="Optional freshness cap for verified rule-gap report timestamps.",
    )
    parser.add_argument(
        "--leanstral-direct-guidance-projection-enabled",
        type=parse_bool_flag,
        default=True,
        help=(
            "Seed Codex TODOs from direct Leanstral draft-guidance artifacts "
            "exported by the autoencoder/Leanstral shadow lane."
        ),
    )
    parser.add_argument(
        "--leanstral-direct-guidance-path",
        default="",
        help=(
            "Comma-separated JSON/JSONL files or directories containing direct "
            "Leanstral guidance. Directories are scanned recursively for .json "
            "and .jsonl artifacts."
        ),
    )
    parser.add_argument(
        "--leanstral-direct-guidance-max-todos-per-scope",
        type=int,
        default=2,
        help="Maximum active direct-guidance TODOs per owned compiler/AST scope.",
    )
    parser.add_argument(
        "--leanstral-direct-guidance-require-executor-available",
        type=parse_bool_flag,
        default=True,
        help="Block direct Leanstral guidance seeding when Codex executor health is unavailable.",
    )
    parser.add_argument(
        "--leanstral-direct-guidance-train-autoencoder",
        type=parse_bool_flag,
        default=True,
        help=(
            "Apply trusted direct Leanstral guidance as LegalIR-view training "
            "signal for the autoencoder."
        ),
    )
    parser.add_argument(
        "--leanstral-direct-guidance-learning-rate",
        type=float,
        default=0.05,
        help="Learning rate for trusted direct Leanstral guidance autoencoder updates.",
    )
    parser.add_argument(
        "--leanstral-direct-guidance-train-missing-samples",
        type=parse_bool_flag,
        default=False,
        help=(
            "Allow direct Leanstral guidance to update global LegalIR view logits "
            "when its sample is not in the current training batch."
        ),
    )
    parser.add_argument(
        "--leanstral-direct-guidance-max-training-items",
        type=int,
        default=64,
        help="Maximum direct Leanstral guidance records applied to autoencoder training per cycle.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-enabled",
        type=parse_bool_flag,
        default=True,
        help="Run the bounded per-cycle Legal IR hammer guidance phase.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-cache-enabled",
        type=parse_bool_flag,
        default=True,
        help="Reuse a matching per-cycle hammer guidance artifact when present.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-output-dir",
        default="",
        help=(
            "Directory for per-cycle hammer guidance artifacts. Defaults to "
            "workspace/legal-ir-hammer-guidance."
        ),
    )
    parser.add_argument(
        "--daemon-hammer-guidance-max-samples-per-cycle",
        type=int,
        default=DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_SAMPLES_PER_CYCLE,
        help="Maximum validation samples checked by the daemon hammer phase per cycle.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-max-obligations-per-sample",
        type=int,
        default=DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_OBLIGATIONS_PER_SAMPLE,
        help="Maximum proof obligations sent to hammer backends per sample.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-max-premises",
        type=int,
        default=DEFAULT_DAEMON_HAMMER_GUIDANCE_MAX_PREMISES,
        help="Maximum selected premises per hammer goal.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-timeout-seconds",
        type=float,
        default=DEFAULT_DAEMON_HAMMER_GUIDANCE_TIMEOUT_SECONDS,
        help="Per-backend timeout for daemon hammer guidance checks.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-parallel-workers",
        type=int,
        default=DEFAULT_DAEMON_HAMMER_GUIDANCE_PARALLEL_WORKERS,
        help="Parallel solver workers used by the daemon hammer phase.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-verify-reconstruction",
        type=parse_bool_flag,
        default=False,
        help="Ask the hammer phase to run native proof reconstruction when configured.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-trusted-requires-reconstruction",
        type=parse_bool_flag,
        default=False,
        help="Require proof reconstruction before hammer guidance becomes trusted.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-train-autoencoder",
        type=parse_bool_flag,
        default=True,
        help="Apply trusted daemon hammer guidance to the autoencoder each cycle.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-learning-rate",
        type=float,
        default=0.03,
        help="Learning rate for trusted daemon hammer guidance updates.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-train-missing-samples",
        type=parse_bool_flag,
        default=False,
        help="Allow daemon hammer guidance to update global logits without a current sample match.",
    )
    parser.add_argument(
        "--daemon-hammer-guidance-max-training-items",
        type=int,
        default=64,
        help="Maximum daemon hammer guidance records applied to autoencoder training per cycle.",
    )
    parser.add_argument(
        "--autoencoder-target-scope-filters",
        default="",
        help="Comma-separated target scopes eligible for introspection audits/TODOs.",
    )
    parser.add_argument(
        "--autoencoder-require-prover-confirmation",
        type=parse_bool_flag,
        default=True,
        help="Require theorem-prover confirmation before productive introspection modes.",
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
        default=_default_bridge_evaluate_provers(),
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
        "--autoencoder-max-codec-feature-keys",
        type=int,
        default=64,
        help=(
            "Maximum deterministic spaCy/modal codec feature keys retained per "
            "sample for learnable cross-sample projection."
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
    parser.add_argument(
        "--program-synthesis-min-support",
        type=int,
        default=2,
        help=(
            "Minimum distinct sample support required before seeding a Codex "
            "program-synthesis TODO from autoencoder residual hints."
        ),
    )
    parser.add_argument(
        "--max-program-synthesis-pending",
        type=int,
        default=512,
        help="Maximum pending Codex/program-synthesis TODOs retained in the queue.",
    )
    parser.add_argument(
        "--program-synthesis-min-residual-occurrences",
        type=int,
        default=1,
        help=(
            "Minimum repeated residual-signature count before a post-SGD residual "
            "can be considered persistent."
        ),
    )
    parser.add_argument(
        "--program-synthesis-min-residual-survival-score",
        type=float,
        default=0.0,
        help=(
            "Minimum post-SGD residual survival score required when the survival "
            "gate is active."
        ),
    )
    parser.add_argument("--worker-id", default=None)
    parser.add_argument(
        "--codex-exec-mode",
        choices=("packet_only", "codex_cli"),
        default="packet_only",
        help="For the Codex loop, either only create work packets or run codex exec in each packet worktree.",
    )
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument(
        "--codex-model",
        default=os.environ.get("IPFS_DATASETS_PY_CODEX_MODEL", DEFAULT_CODEX_MODEL),
    )
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
        "--codex-main-apply-lock-timeout-seconds",
        type=float,
        default=float(
            os.environ.get("IPFS_DATASETS_CODEX_MAIN_APPLY_LOCK_TIMEOUT_SECONDS", "300")
            or 300
        ),
        help=(
            "Maximum seconds a Codex packet waits for the serialized main apply "
            "lock before preserving its patch and requeueing as transient."
        ),
    )
    parser.add_argument(
        "--codex-main-apply-max-inflight-packets",
        type=int,
        default=int(
            os.environ.get("IPFS_DATASETS_CODEX_MAIN_APPLY_MAX_INFLIGHT_PACKETS", "1")
            or 1
        ),
        help=(
            "Maximum active apply_to_main Codex packets before new claims are "
            "backpressured. Use 0 to disable this claim-time guard."
        ),
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
        "--paired-codex-disable-cuda",
        type=parse_bool_flag,
        default=True,
    )
    parser.add_argument(
        "--paired-supervisor-backend",
        choices=("simple", "accelerate_style"),
        default="accelerate_style",
        help="Supervisor accounting style for paired autoencoder/Codex children.",
    )
    parser.add_argument(
        "--paired-resource-guard",
        choices=("off", "auto"),
        default="auto",
        help="Cap paired Codex workers from host CPU/memory/swap health.",
    )
    parser.add_argument("--paired-reserved-memory-gb", type=float, default=24.0)
    parser.add_argument("--paired-codex-worker-memory-gb", type=float, default=2.0)
    parser.add_argument("--paired-min-available-memory-gb", type=float, default=0.0)
    parser.add_argument("--paired-min-swap-free-gb", type=float, default=0.0)
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
    parser.add_argument(
        "--autoencoder-canonical-warm-start",
        choices=tuple(sorted(AUTOENCODER_CANONICAL_WARM_START_MODES)),
        default=_default_canonical_warm_start_mode(),
        help=(
            "Automatically warm-start autoencoder runs from the canonical "
            "feature-level state when available."
        ),
    )
    parser.add_argument(
        "--canonical-warm-start-state",
        type=Path,
        default=Path(
            os.environ.get(AUTOENCODER_CANONICAL_WARM_START_STATE_ENV)
            or DEFAULT_CANONICAL_AUTOENCODER_STATE_NAME
        ),
        help="Canonical feature-level autoencoder state path, relative to queue dir unless absolute.",
    )
    return parser


def resolve_warm_start_state_paths(args: argparse.Namespace, queue_dir: Path) -> List[Path]:
    """Resolve explicit warm-start state paths and prior run ids."""
    paths: List[Path] = []
    seen: set[str] = set()

    def append_once(path: Path, *, base_dir: Optional[Path] = None) -> None:
        resolved = path if path.is_absolute() or base_dir is None else base_dir / path
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        paths.append(resolved)

    canonical_mode = str(
        getattr(args, "autoencoder_canonical_warm_start", _default_canonical_warm_start_mode())
        or "auto"
    ).strip().lower()
    if canonical_mode not in AUTOENCODER_CANONICAL_WARM_START_MODES:
        canonical_mode = "auto"
    if canonical_mode != "off":
        canonical_path = Path(
            getattr(
                args,
                "canonical_warm_start_state",
                DEFAULT_CANONICAL_AUTOENCODER_STATE_NAME,
            )
        )
        canonical_path = canonical_path if canonical_path.is_absolute() else queue_dir / canonical_path
        if canonical_path.exists() or canonical_mode == "require":
            append_once(canonical_path)
        if canonical_mode == "require" and not canonical_path.exists():
            raise FileNotFoundError(
                f"required canonical autoencoder warm-start state not found: {canonical_path}"
            )

    for path in getattr(args, "warm_start_state", []):
        append_once(Path(path))
    for run_id in getattr(args, "warm_start_run_id", []):
        append_once(Path(f"{run_id}.state.json"), base_dir=queue_dir)
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
    paired_queue_path = root / "workspace" / "todo-queues" / f"{paired['queue_run_id']}.jsonl"
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
                program_health = paired_program_synthesis_health(
                    queue_path=paired_queue_path,
                    codex_summary_paths=[
                        log_dir / f"{child['run_id']}.summary"
                        for child in codex_child_summaries
                    ],
                    codex_worker_stale_seconds=float(
                        getattr(args, "codex_worker_stale_seconds", 300.0)
                    ),
                )
                summary["program_synthesis_health"] = program_health
                summary["program_synthesis_executor_health"] = program_health
                summary["program_synthesis_queue_pressure"] = _program_synthesis_queue_pressure(
                    program_health,
                    pending_cap=int(getattr(args, "max_program_synthesis_pending", 512) or 512),
                )
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
        program_health = paired_program_synthesis_health(
            queue_path=paired_queue_path,
            codex_summary_paths=[
                log_dir / f"{child['run_id']}.summary"
                for child in codex_child_summaries
            ],
            codex_worker_stale_seconds=float(
                getattr(args, "codex_worker_stale_seconds", 300.0)
            ),
        )
        summary["program_synthesis_health"] = program_health
        summary["program_synthesis_executor_health"] = program_health
        summary["program_synthesis_queue_pressure"] = _program_synthesis_queue_pressure(
            program_health,
            pending_cap=int(getattr(args, "max_program_synthesis_pending", 512) or 512),
        )
        summary["finished_at"] = utc_now()
        autoencoder_child_health = paired_autoencoder_child_health(
            log_dir / f"{paired['autoencoder_run_id']}.summary"
        )
        summary["autoencoder_child_health"] = autoencoder_child_health
        autoencoder_runner_terminated = (
            str(paired["autoencoder_run_id"]) in runner_terminated_children
        )
        autoencoder_success = _paired_autoencoder_succeeded(
            autoencoder_run_id=str(paired["autoencoder_run_id"]),
            autoencoder_exit_code=auto_exit_code,
            autoencoder_child_health=autoencoder_child_health,
            runner_terminated_children=runner_terminated_children,
            stop_requested=stop_requested,
        )
        codex_success = _paired_codex_children_succeeded(
            codex_exit_codes,
            autoencoder_exit_code=auto_exit_code,
            autoencoder_success=autoencoder_success,
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

    autoencoder_success = _paired_autoencoder_succeeded(
        autoencoder_run_id=str(paired["autoencoder_run_id"]),
        autoencoder_exit_code=auto_exit_code,
        autoencoder_child_health=paired_autoencoder_child_health(
            log_dir / f"{paired['autoencoder_run_id']}.summary"
        ),
        runner_terminated_children=runner_terminated_children,
        stop_requested=stop_requested,
    )
    codex_success = _paired_codex_children_succeeded(
        codex_exit_codes,
        autoencoder_exit_code=auto_exit_code,
        autoencoder_success=autoencoder_success,
        runner_terminated_children=runner_terminated_children,
        stop_requested=stop_requested,
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
    bridge_evaluate_provers = bool(
        getattr(args, "bridge_evaluate_provers", _default_bridge_evaluate_provers())
    )
    rollout_control = autoencoder_rollout_control(args)
    bridge_parallel_workers = max(
        1,
        int(getattr(args, "autoencoder_bridge_workers", 1) or 1),
    )
    metric_bridge_adapters = autoencoder_metric_bridge_adapter_names(
        args,
        bridge_adapters,
    )
    diagnostic_bridge_adapters = autoencoder_diagnostic_bridge_adapter_names(
        args,
        bridge_adapters=bridge_adapters,
        metric_bridge_adapters=metric_bridge_adapters,
    )
    bridge_metric_adapters = diagnostic_bridge_adapters or metric_bridge_adapters
    os.environ["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"] = str(bridge_parallel_workers)
    summary["metric_schema_version"] = AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION
    summary["autoencoder_architecture_version"] = MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    summary["autoencoder_state_schema_version"] = MODAL_AUTOENCODER_STATE_SCHEMA_VERSION
    summary["bridge_loss_adapters"] = bridge_adapters
    summary["autoencoder_metric_bridge_adapters"] = metric_bridge_adapters
    summary["autoencoder_diagnostic_bridge_adapters"] = diagnostic_bridge_adapters
    summary["bridge_evaluate_provers"] = bridge_evaluate_provers
    summary["autoencoder_introspection"] = dict(rollout_control)
    summary["autoencoder_introspection_mode"] = str(
        rollout_control["introspection_mode"]
    )
    summary["autoencoder_introspection_every_n_cycles"] = int(
        rollout_control["export_every_n_cycles"]
    )
    summary["autoencoder_introspection_min_export_samples"] = int(
        rollout_control["min_export_samples"]
    )
    summary["autoencoder_max_audits_per_cycle"] = int(
        rollout_control["max_audits_per_cycle"]
    )
    summary["autoencoder_max_todos_per_cycle"] = int(
        rollout_control["max_todos_per_cycle"]
    )
    summary["autoencoder_target_scope_filters"] = list(
        rollout_control["target_scope_filters"]
    )
    summary["autoencoder_require_prover_confirmation"] = bool(
        rollout_control["require_prover_confirmation"]
    )
    summary["autoencoder_bridge_workers"] = bridge_parallel_workers
    summary["legal_ir_bridge_parallelism"] = {
        "bridge_loss_adapters": list(bridge_adapters),
        "diagnostic_bridge_adapters": list(diagnostic_bridge_adapters),
        "metric_bridge_adapters": list(metric_bridge_adapters),
        "parallel_workers": int(bridge_parallel_workers),
        "prover_evaluation_enabled": bool(bridge_evaluate_provers),
    }
    summary["max_sample_text_chars"] = int(getattr(args, "max_sample_text_chars", 0) or 0)
    summary.setdefault("bridge_loss_failures", 0)
    summary.setdefault("bridge_loss_samples", 0)
    summary.setdefault("bridge_loss_signals", 0)
    summary.setdefault("bridge_metric_failures", 0)
    summary.setdefault("best_validation_logic_bridge_acceptance", -1.0)
    summary.setdefault("best_validation_logic_bridge_proof_failure_ratio", 1.0e12)
    summary.setdefault("best_validation_logic_bridge_total_loss", 1.0e12)
    enforce_block_reason = autoencoder_enforce_fail_closed_reason(
        rollout_control,
        bridge_evaluate_provers=bridge_evaluate_provers,
    )
    if enforce_block_reason:
        summary["autoencoder_introspection_enforce_allowed"] = False
        summary["autoencoder_introspection_enforce_block_reason"] = enforce_block_reason
        summary["supervisor_health"] = build_modal_supervisor_health_report(
            summary
        ).to_dict()
        save_summary(summary_path, summary, final=True)
        append_event(
            log_path,
            args.run_id,
            {
                "event": "autoencoder_introspection_enforce_blocked",
                "reason": enforce_block_reason,
            },
        )
        return 2
    summary["autoencoder_introspection_enforce_allowed"] = True
    summary["autoencoder_introspection_enforce_block_reason"] = ""
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
        max_codec_feature_keys=int(
            getattr(args, "autoencoder_max_codec_feature_keys", 64)
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
        max_reference_dependency_features=int(
            getattr(args, "autoencoder_max_reference_dependency_features", 64)
        ),
        max_authority_jurisdiction_features=int(
            getattr(args, "autoencoder_max_authority_jurisdiction_features", 64)
        ),
        max_temporal_validity_features=int(
            getattr(args, "autoencoder_max_temporal_validity_features", 64)
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
    summary["autoencoder_max_codec_feature_keys"] = int(
        getattr(args, "autoencoder_max_codec_feature_keys", 64)
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
    summary["autoencoder_max_reference_dependency_features"] = int(
        getattr(args, "autoencoder_max_reference_dependency_features", 64)
    )
    summary["autoencoder_max_authority_jurisdiction_features"] = int(
        getattr(args, "autoencoder_max_authority_jurisdiction_features", 64)
    )
    summary["autoencoder_max_temporal_validity_features"] = int(
        getattr(args, "autoencoder_max_temporal_validity_features", 64)
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
        policy=ModalOptimizerPolicy(
            program_synthesis_min_support=max(
                1,
                int(getattr(args, "program_synthesis_min_support", 2) or 2),
            ),
            max_program_synthesis_pending=max(
                0,
                int(getattr(args, "max_program_synthesis_pending", 512) or 512),
            ),
            program_synthesis_min_residual_occurrences=max(
                1,
                int(
                    getattr(
                        args,
                        "program_synthesis_min_residual_occurrences",
                        1,
                    )
                    or 1
                ),
            ),
            program_synthesis_min_residual_survival_score=max(
                0.0,
                float(
                    getattr(
                        args,
                        "program_synthesis_min_residual_survival_score",
                        0.0,
                    )
                    or 0.0
                ),
            ),
        ),
        bridge_names=bridge_adapters,
        bridge_evaluate_provers=bridge_evaluate_provers,
        bridge_parallel_workers=bridge_parallel_workers,
        bridge_loss_evaluator=bridge_loss_evaluator_for_names(
            bridge_adapters,
            evaluate_provers=bridge_evaluate_provers,
            parallel_workers=bridge_parallel_workers,
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
            max_cycles = max(0, int(getattr(args, "max_cycles", 0) or 0))
            if max_cycles > 0 and int(summary.get("cycles", 0) or 0) >= max_cycles:
                summary["latest_stop_reason"] = "max_cycles"
                break
            cycle = int(summary.get("cycles", 0)) + 1
            cycle_started = time.time()
            cycle_phase_timings: Dict[str, float] = {}
            active_phase = {"name": "", "started_at": cycle_started}

            def mark_cycle_phase(phase: str, **payload: Any) -> None:
                now = time.time()
                previous = str(active_phase.get("name") or "")
                if previous:
                    cycle_phase_timings[previous] = (
                        cycle_phase_timings.get(previous, 0.0)
                        + max(0.0, now - float(active_phase["started_at"]))
                    )
                active_phase["name"] = str(phase)
                active_phase["started_at"] = now
                summary["active_cycle"] = cycle
                summary["active_cycle_phase"] = str(phase)
                summary["active_cycle_bridge_loss_adapters"] = list(bridge_adapters)
                summary["active_cycle_metric_bridge_adapters"] = list(
                    metric_bridge_adapters
                )
                summary["active_cycle_diagnostic_bridge_adapters"] = list(
                    diagnostic_bridge_adapters
                )
                summary["active_cycle_metric_bridge_max_sample_text_chars"] = int(
                    getattr(
                        args,
                        "autoencoder_metric_bridge_max_sample_text_chars",
                        DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
                    )
                    or 0
                )
                summary["active_cycle_last_heartbeat_at"] = utc_now()
                summary["active_cycle_phase_payload"] = dict(payload)
                summary["active_cycle_phase_timings"] = {
                    name: round(seconds, 3)
                    for name, seconds in sorted(cycle_phase_timings.items())
                }
                save_summary(summary_path, summary)
                append_event(
                    log_path,
                    args.run_id,
                    {
                        "cycle": cycle,
                        "event": "cycle_phase",
                        "phase": str(phase),
                        **payload,
                    },
                )

            def finish_cycle_phase() -> None:
                now = time.time()
                previous = str(active_phase.get("name") or "")
                if previous:
                    cycle_phase_timings[previous] = (
                        cycle_phase_timings.get(previous, 0.0)
                        + max(0.0, now - float(active_phase["started_at"]))
                    )
                summary["active_cycle_phase_timings"] = {
                    name: round(seconds, 3)
                    for name, seconds in sorted(cycle_phase_timings.items())
                }

            def projection_progress_callback(progress: Mapping[str, Any]) -> None:
                payload = dict(progress)
                summary["active_cycle"] = cycle
                summary["active_cycle_phase"] = "projection_training"
                summary["active_cycle_projection_stage"] = str(
                    payload.get("stage") or ""
                )
                summary["active_cycle_projection_progress"] = payload
                summary["active_cycle_last_heartbeat_at"] = utc_now()
                save_summary(summary_path, summary)
                append_event(
                    log_path,
                    args.run_id,
                    {
                        "cycle": cycle,
                        "event": "projection_progress",
                        "progress": payload,
                    },
                )

            def metric_progress_callback(dataset: str) -> Callable[[Mapping[str, Any]], None]:
                def record_metric_progress(progress: Mapping[str, Any]) -> None:
                    payload = dict(progress)
                    payload["cycle"] = cycle
                    payload["dataset"] = str(dataset)
                    summary["active_cycle"] = cycle
                    summary["active_cycle_metric_progress"] = payload
                    summary["active_cycle_last_heartbeat_at"] = utc_now()
                    save_summary(summary_path, summary)
                    append_event(
                        log_path,
                        args.run_id,
                        {
                            "cycle": cycle,
                            "event": "metric_progress",
                            "progress": payload,
                        },
                    )

                return record_metric_progress

            def todo_progress_callback(progress: Mapping[str, Any]) -> None:
                payload = dict(progress)
                summary["active_cycle"] = cycle
                summary["active_cycle_phase"] = "todo_supervisor_optimize"
                summary["active_cycle_todo_supervisor_progress"] = payload
                summary["active_cycle_last_heartbeat_at"] = utc_now()
                save_summary(summary_path, summary)
                append_event(
                    log_path,
                    args.run_id,
                    {
                        "cycle": cycle,
                        "event": "todo_supervisor_progress",
                        "progress": payload,
                    },
                )

            cycle_learning_rate, cycle_lr_policy = _cycle_learning_rate(args, summary)
            mark_cycle_phase("sampling")
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
            audited_train_samples = _budgeted_audit_samples(
                train_samples,
                rollout_control,
            )
            (
                audited_validation_samples,
                audited_validation_indices,
            ) = _budgeted_audit_samples_with_indices(
                acceptance_validation_samples,
                acceptance_validation_indices,
                rollout_control,
            )
            (
                introspection_export_validation_samples,
                introspection_export_validation_indices,
            ) = _introspection_export_samples_with_indices(
                acceptance_validation_samples,
                acceptance_validation_indices,
                rollout_control,
            )
            effective_max_items = _effective_todo_budget(
                int(args.max_items),
                rollout_control,
            )
            requested_max_items = effective_max_items
            todo_supervisor_mode = str(
                getattr(
                    args,
                    "autoencoder_todo_supervisor_mode",
                    DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE,
                )
                or DEFAULT_AUTOENCODER_TODO_SUPERVISOR_MODE
            )
            todo_supervisor_min_open = max(
                0,
                int(
                    getattr(args, "autoencoder_todo_supervisor_min_open", 12)
                    or 0
                ),
            )
            program_synthesis_status = supervisor.queue.role_status_counts().get(
                supervisor.policy.program_synthesis_role,
                {},
            )
            todo_supervisor_control = _todo_supervisor_skip_decision(
                mode=todo_supervisor_mode,
                program_synthesis_status=program_synthesis_status,
                min_open=todo_supervisor_min_open,
            )
            if todo_supervisor_control["skipped"]:
                effective_max_items = 0
            todo_supervisor_control.update(
                {
                    "effective_max_items": effective_max_items,
                    "minimum_open_program_synthesis_count": (
                        todo_supervisor_min_open
                    ),
                    "mode": todo_supervisor_mode,
                    "requested_max_items": requested_max_items,
                }
            )
            if (
                str(rollout_control.get("introspection_mode") or "off") != "off"
                and effective_max_items <= 0
            ):
                audited_train_samples = []
            summary["active_cycle_introspection"] = {
                **dict(rollout_control),
                "eligible_audit_sample_count": len(audited_train_samples),
                "eligible_validation_audit_sample_count": len(
                    audited_validation_samples
                ),
                "eligible_validation_export_sample_count": len(
                    introspection_export_validation_samples
                ),
                "effective_max_items": effective_max_items,
            }
            summary["active_cycle_todo_supervisor"] = todo_supervisor_control
            metric_bridge_text_cap = int(
                getattr(
                    args,
                    "autoencoder_metric_bridge_max_sample_text_chars",
                    DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
                )
                or 0
            )

            def evaluate_cycle_samples(
                rows: Sequence[Any],
                *,
                use_sample_memory: bool,
            ) -> AutoencoderEvaluation:
                return evaluate_autoencoder_with_bounded_metric_bridges(
                    autoencoder,
                    rows,
                    legal_ir_bridge_names=metric_bridge_adapters,
                    legal_ir_evaluate_provers=bridge_evaluate_provers,
                    legal_ir_parallel_workers=bridge_parallel_workers,
                    max_bridge_sample_text_chars=metric_bridge_text_cap,
                    use_sample_memory=use_sample_memory,
                )
            mark_cycle_phase(
                "before_train_eval",
                sample_count=len(train_samples),
            )
            before_train = evaluate_cycle_samples(
                train_samples,
                use_sample_memory=True,
            )
            mark_cycle_phase(
                "before_validation_eval",
                sample_count=len(acceptance_validation_samples),
                validation_mode=validation_mode,
            )
            before_validation = evaluate_cycle_samples(
                acceptance_validation_samples,
                use_sample_memory=False,
            )
            compiler_ir_metric_kwargs = {
                "max_sample_text_chars": int(
                    getattr(
                        args,
                        "compiler_ir_metric_max_sample_text_chars",
                        _default_compiler_ir_metric_max_sample_text_chars(),
                    )
                    or 0
                ),
                "metric_text_policy": str(
                    getattr(
                        args,
                        "compiler_ir_metric_text_policy",
                        DEFAULT_COMPILER_IR_METRIC_TEXT_POLICY,
                    )
                ),
                "sample_timeout_seconds": float(
                    getattr(
                        args,
                        "compiler_ir_metric_sample_timeout_seconds",
                        DEFAULT_COMPILER_IR_METRIC_SAMPLE_TIMEOUT_SECONDS,
                    )
                    or 0.0
                ),
            }
            mark_cycle_phase("compiler_ir_train", sample_count=len(train_samples))
            compiler_ir_train = compiler_ir_metric_block(
                train_samples,
                feature_codec,
                progress_callback=metric_progress_callback("compiler_ir_train"),
                **compiler_ir_metric_kwargs,
            )
            mark_cycle_phase(
                "compiler_ir_validation",
                sample_count=len(acceptance_validation_samples),
            )
            compiler_ir_validation = compiler_ir_metric_block(
                acceptance_validation_samples,
                feature_codec,
                progress_callback=metric_progress_callback("compiler_ir_validation"),
                **compiler_ir_metric_kwargs,
            )
            compiler_ir_validation_sample_ids = [
                str(getattr(sample, "sample_id", "") or "")
                for sample in acceptance_validation_samples
            ]
            compiler_ir_validation_metrics = {
                str(key): float(value)
                for key, value in compiler_ir_validation.items()
                if isinstance(value, (int, float))
            }
            compiler_ir_validation_profile = {
                "max_sample_text_chars": int(
                    compiler_ir_validation.get("max_sample_text_chars", 0) or 0
                ),
                "metric_profile_version": str(
                    compiler_ir_validation.get("metric_profile_version", "") or ""
                ),
                "metric_text_policy": str(
                    compiler_ir_validation.get("metric_text_policy", "") or ""
                ),
                "sample_timeout_cache_policy": str(
                    compiler_ir_validation.get("sample_timeout_cache_policy", "") or ""
                ),
                "sample_timeout_seconds": float(
                    compiler_ir_validation.get("sample_timeout_seconds", 0.0) or 0.0
                ),
            }
            previous_compiler_ir_validation_sample_ids = [
                str(sample_id)
                for sample_id in summary.get(
                    "latest_compiler_ir_validation_sample_ids",
                    [],
                )
                or []
            ]
            previous_compiler_ir_validation_metrics = dict(
                summary.get("latest_compiler_ir_validation_metrics", {}) or {}
            )
            previous_compiler_ir_validation_profile = dict(
                summary.get("latest_compiler_ir_validation_profile", {}) or {}
            )
            compiler_ir_validation_comparable = (
                bool(previous_compiler_ir_validation_metrics)
                and previous_compiler_ir_validation_profile
                == compiler_ir_validation_profile
                and previous_compiler_ir_validation_sample_ids
                == compiler_ir_validation_sample_ids
            )
            compiler_ir_validation_delta = (
                _target_metric_improvement_delta_map(
                    before=previous_compiler_ir_validation_metrics,
                    after=compiler_ir_validation_metrics,
                    target_metrics=(
                        "cross_entropy_loss",
                        "compiler_ir_cross_entropy_loss",
                        "cosine_similarity",
                        "compiler_ir_cosine_similarity",
                        "reconstruction_loss",
                        "compiler_ir_reconstruction_loss",
                        "text_reconstruction_loss",
                        "compiler_ir_text_reconstruction_loss",
                        "source_decompiled_text_embedding_cosine_loss",
                        "compiler_ir_source_decompiled_text_embedding_cosine_loss",
                        "source_decompiled_text_token_loss",
                        "compiler_ir_source_decompiled_text_token_loss",
                        "source_copy_reward_hack_penalty",
                        "compiler_ir_source_copy_reward_hack_penalty",
                        "structural_text_reconstruction_loss",
                        "compiler_ir_structural_text_reconstruction_loss",
                    ),
                )
                if compiler_ir_validation_comparable
                else {}
            )
            mark_cycle_phase(
                "pre_todo_introspection_disagreement_export",
                sample_count=len(introspection_export_validation_samples),
            )
            if autoencoder_introspection_export_due(rollout_control, cycle=cycle):
                pre_todo_introspection_export = export_canonical_state_disagreement_packets(
                    autoencoder=autoencoder,
                    compiler_ir_validation=compiler_ir_validation,
                    compiler_ir_guided_validation={},
                    cycle=cycle,
                    export_mode=str(
                        rollout_control.get("introspection_mode") or "off"
                    ),
                    root=root,
                    run_id=args.run_id,
                    samples=introspection_export_validation_samples,
                    state=autoencoder.state,
                    summary_path=summary_path,
                    validation_indices=introspection_export_validation_indices,
                    validation_mode=validation_mode,
                    evaluate_provers=bridge_evaluate_provers,
                )
            else:
                pre_todo_introspection_export = skipped_introspection_export_report(
                    cycle=cycle,
                    rollout_control=rollout_control,
                    summary_path=summary_path,
                )
            summary["latest_pre_todo_introspection_disagreement_export"] = (
                dict(pre_todo_introspection_export)
            )
            save_summary(summary_path, summary)
            mark_cycle_phase("bridge_ir_train", sample_count=len(train_samples))
            bridge_ir_train = bridge_ir_metric_block(
                train_samples,
                bridge_metric_adapters,
                evaluate_provers=bridge_evaluate_provers,
                parallel_workers=bridge_parallel_workers,
                progress_callback=metric_progress_callback("bridge_ir_train"),
                max_sample_text_chars=metric_bridge_text_cap,
            )
            bridge_ir_train["bridge_loss_adapters"] = list(bridge_adapters)
            bridge_ir_train["diagnostic_bridge_adapters"] = list(
                diagnostic_bridge_adapters
            )
            bridge_ir_train["metric_bridge_adapters"] = list(metric_bridge_adapters)
            mark_cycle_phase(
                "bridge_ir_validation",
                sample_count=len(acceptance_validation_samples),
            )
            bridge_ir_validation = bridge_ir_metric_block(
                acceptance_validation_samples,
                bridge_metric_adapters,
                evaluate_provers=bridge_evaluate_provers,
                parallel_workers=bridge_parallel_workers,
                progress_callback=metric_progress_callback("bridge_ir_validation"),
                max_sample_text_chars=metric_bridge_text_cap,
            )
            bridge_ir_validation["bridge_loss_adapters"] = list(bridge_adapters)
            bridge_ir_validation["diagnostic_bridge_adapters"] = list(
                diagnostic_bridge_adapters
            )
            bridge_ir_validation["metric_bridge_adapters"] = list(metric_bridge_adapters)
            feature_projection_report: Dict[str, Any] = {}
            generalizable_projection_epochs = max(
                0,
                int(getattr(args, "generalizable_projection_epochs", 0) or 0),
            )
            if generalizable_projection_epochs > 0 and train_samples:
                mark_cycle_phase(
                    "projection_training",
                    epoch_count=generalizable_projection_epochs,
                    train_sample_count=len(train_samples),
                    validation_sample_count=len(acceptance_validation_samples),
                )
                feature_projection_report = autoencoder.train_generalizable_projection(
                    train_samples,
                    validation_samples=acceptance_validation_samples,
                    epochs=generalizable_projection_epochs,
                    learning_rate=cycle_learning_rate,
                    legal_ir_bridge_names=metric_bridge_adapters,
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
                    max_seconds=float(
                        getattr(
                            args,
                            "generalizable_projection_timeout_seconds",
                            DEFAULT_GENERALIZABLE_PROJECTION_TIMEOUT_SECONDS,
                        )
                        or 0.0
                    ),
                    max_line_search_attempts=int(
                        getattr(
                            args,
                            "generalizable_projection_max_line_search_attempts",
                            DEFAULT_GENERALIZABLE_PROJECTION_MAX_LINE_SEARCH_ATTEMPTS,
                        )
                        or 0
                    ),
                    legal_ir_bridge_max_sample_text_chars=int(
                        getattr(
                            args,
                            "autoencoder_metric_bridge_max_sample_text_chars",
                            DEFAULT_AUTOENCODER_METRIC_BRIDGE_MAX_SAMPLE_TEXT_CHARS,
                        )
                        or 0
                    ),
                    projection_deadband_mode=str(
                        getattr(args, "autoencoder_projection_deadband_mode", "shadow")
                    ),
                    projection_max_ce_deadband=float(
                        getattr(args, "autoencoder_max_ce_deadband", 0.0001) or 0.0
                    ),
                    projection_hard_guardrail_metrics=str(
                        getattr(
                            args,
                            "autoencoder_hard_guardrail_metrics",
                            "compiler_ir_cosine,structural_validity,source_copy_penalty",
                        )
                    ),
                    projection_prescreen_mode=str(
                        getattr(args, "autoencoder_projection_prescreen_mode", "off")
                    ),
                    projection_prescreen_top_k=int(
                        getattr(args, "autoencoder_projection_prescreen_top_k", 3) or 0
                    ),
                    projection_periodic_full_search_every_n_cycles=int(
                        getattr(
                            args,
                            "autoencoder_projection_periodic_full_search_every_n_cycles",
                            8,
                        )
                        or 0
                    ),
                    projection_cycle=cycle,
                    precomputed_holdout_evaluation=before_validation,
                    precomputed_training_evaluation=before_train,
                    progress_callback=projection_progress_callback,
                )
            mark_cycle_phase(
                "todo_supervisor_optimize",
                max_inner_iterations=args.max_inner_iterations,
                max_items=effective_max_items,
                audit_sample_count=len(audited_train_samples),
            )
            (
                todo_precomputed_train,
                todo_precomputed_validation,
            ) = _todo_supervisor_precomputed_evaluations(
                feature_projection_report=feature_projection_report,
                train_samples=audited_train_samples,
                validation_samples=acceptance_validation_samples,
                before_train=before_train,
                before_validation=before_validation,
            )
            if effective_max_items <= 0 or not audited_train_samples:
                run = ModalOptimizationRun(
                    steps=[],
                    final_evaluation=before_train,
                    stopped_reason="todo_budget_disabled",
                    validation_final_evaluation=before_validation,
                )
            else:
                run = supervisor.optimize(
                    audited_train_samples,
                    validation_samples=acceptance_validation_samples,
                    autoencoder=autoencoder,
                    precomputed_train_evaluation=todo_precomputed_train,
                    precomputed_validation_evaluation=todo_precomputed_validation,
                    evaluation_callback=evaluate_cycle_samples,
                    worker_id="random-uscode-daemon-detached",
                    max_items=effective_max_items,
                    learning_rate=cycle_learning_rate,
                    max_iterations=args.max_inner_iterations,
                    target_cross_entropy_loss=0.001,
                    target_cosine_similarity=0.999999,
                    progress_callback=todo_progress_callback,
                )
            mark_cycle_phase("todo_supervisor_queue_flush")
            todo_supervisor_queue_persist = (
                persist_supervisor_queue_for_external_workers(
                    queue_path=queue_path,
                    supervisor=supervisor,
                )
            )
            queue = supervisor.queue
            summary["active_cycle_todo_supervisor_queue_flush"] = (
                todo_supervisor_queue_persist
            )
            save_summary(summary_path, summary)
            append_event(
                log_path,
                args.run_id,
                {
                    "cycle": cycle,
                    "event": "todo_supervisor_queue_flushed",
                    "queue_persist": todo_supervisor_queue_persist,
                },
            )
            mark_cycle_phase("after_train_eval", sample_count=len(train_samples))
            after_train = evaluate_cycle_samples(
                train_samples,
                use_sample_memory=True,
            )
            mark_cycle_phase(
                "after_validation_eval",
                sample_count=len(acceptance_validation_samples),
                validation_mode=validation_mode,
            )
            after_validation = evaluate_cycle_samples(
                acceptance_validation_samples,
                use_sample_memory=False,
            )
            sample_memory_probe_mode = str(
                getattr(
                    args,
                    "autoencoder_sample_memory_probe_mode",
                    DEFAULT_AUTOENCODER_SAMPLE_MEMORY_PROBE_MODE,
                )
            )
            sample_memory_probe_every_n_cycles = int(
                getattr(
                    args,
                    "autoencoder_sample_memory_probe_every_n_cycles",
                    4,
                )
                or 0
            )
            sample_memory_probe_enabled = _should_run_cycle_cadence(
                cycle=cycle,
                mode=sample_memory_probe_mode,
                every_n_cycles=sample_memory_probe_every_n_cycles,
            )
            mark_cycle_phase(
                "sample_memory_probe",
                sample_count=len(train_samples),
                enabled=sample_memory_probe_enabled,
                mode=sample_memory_probe_mode,
                every_n_cycles=sample_memory_probe_every_n_cycles,
            )
            after_train_generalized_probe = None
            after_validation_sample_memory_probe = None
            if sample_memory_probe_enabled:
                after_train_generalized_probe = evaluate_cycle_samples(
                    train_samples,
                    use_sample_memory=False,
                )
                after_validation_sample_memory_probe = evaluate_cycle_samples(
                    acceptance_validation_samples,
                    use_sample_memory=True,
                )
            mark_cycle_phase("compiler_ir_guided_train", sample_count=len(train_samples))
            compiler_ir_guided_train = compiler_ir_metric_block(
                train_samples,
                feature_codec,
                autoencoder=autoencoder,
                use_autoencoder_guidance=True,
                progress_callback=metric_progress_callback("compiler_ir_guided_train"),
                **compiler_ir_metric_kwargs,
            )
            mark_cycle_phase(
                "compiler_ir_guided_validation",
                sample_count=len(acceptance_validation_samples),
            )
            compiler_ir_guided_validation = compiler_ir_metric_block(
                acceptance_validation_samples,
                feature_codec,
                autoencoder=autoencoder,
                use_autoencoder_guidance=True,
                progress_callback=metric_progress_callback("compiler_ir_guided_validation"),
                **compiler_ir_metric_kwargs,
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
            mark_cycle_phase(
                "introspection_disagreement_export",
                sample_count=len(introspection_export_validation_samples),
            )
            if (
                pre_todo_introspection_export.get("enabled")
                and not pre_todo_introspection_export.get("skipped")
            ):
                introspection_export = dict(pre_todo_introspection_export)
                introspection_export["reused_pre_todo_export"] = True
                introspection_export["reuse_reason"] = (
                    "pre_todo_export_already_written"
                )
            elif autoencoder_introspection_export_due(rollout_control, cycle=cycle):
                introspection_export = export_canonical_state_disagreement_packets(
                    autoencoder=autoencoder,
                    compiler_ir_validation=compiler_ir_validation,
                    compiler_ir_guided_validation=compiler_ir_guided_validation,
                    cycle=cycle,
                    export_mode=str(
                        rollout_control.get("introspection_mode") or "off"
                    ),
                    root=root,
                    run_id=args.run_id,
                    samples=introspection_export_validation_samples,
                    state=autoencoder.state,
                    summary_path=summary_path,
                    validation_indices=introspection_export_validation_indices,
                    validation_mode=validation_mode,
                    evaluate_provers=bridge_evaluate_provers,
                )
            else:
                introspection_export = skipped_introspection_export_report(
                    cycle=cycle,
                    rollout_control=rollout_control,
                    summary_path=summary_path,
                )
            mark_cycle_phase(
                "hammer_guidance_cycle",
                sample_count=len(acceptance_validation_samples),
            )
            daemon_hammer_guidance_cycle = run_daemon_hammer_guidance_cycle(
                args=args,
                root=root,
                cycle=cycle,
                samples=acceptance_validation_samples,
                autoencoder=autoencoder,
                samples_by_id={
                    sample.sample_id: sample
                    for sample in [*train_samples, *acceptance_validation_samples]
                },
                artifact_paths=[
                    str(path)
                    for path in introspection_export.get("paths", []) or []
                    if str(path)
                ],
            )
            summary["active_cycle_hammer_guidance"] = dict(
                daemon_hammer_guidance_cycle
            )
            save_summary(summary_path, summary)
            guidance_todo_candidates_by_kind = {
                "activation": compiler_guidance_activation_todos(
                    guidance_distillation,
                    guidance_canary,
                    policy=supervisor.policy,
                ),
                "distillation": compiler_guidance_distillation_todos(
                    guidance_distillation,
                    policy=supervisor.policy,
                ),
                "guardrail": compiler_guidance_guardrail_todos(
                    guidance_distillation,
                    guidance_canary,
                    policy=supervisor.policy,
                ),
            }
            guidance_todo_counts: Dict[str, int] = {
                "activation_deduped_count": 0,
                "activation_seeded_count": 0,
                "activation_semantic_deduped_count": 0,
                "distillation_deduped_count": 0,
                "distillation_seeded_count": 0,
                "distillation_semantic_deduped_count": 0,
                "guardrail_deduped_count": 0,
                "guardrail_seeded_count": 0,
                "guardrail_semantic_deduped_count": 0,
            }
            guidance_todo_ids: Dict[str, List[str]] = {
                "activation": [],
                "distillation": [],
                "guardrail": [],
            }
            semantic_deduped_count = int(
                todo_supervisor_queue_persist.get("semantic_deduped_count", 0)
                or 0
            )
            leanstral_projection: Dict[str, Any] = {}
            leanstral_rule_gap_projection: Dict[str, Any] = {}
            leanstral_direct_guidance_projection: Dict[str, Any] = {}
            blocked_validation_sample_ids.update(sample.sample_id for sample in train_samples)
            mark_cycle_phase("queue_merge")
            with queue_file_lock(queue_path):
                latest_queue = ModalTodoQueue.load_jsonl(queue_path)
                latest_queue.merge_from(
                    supervisor.queue,
                    preserve_claimed_role=supervisor.policy.program_synthesis_role,
                )
                semantic_deduped_count += latest_queue.deduplicate_semantic(
                    optimizer_role=supervisor.policy.program_synthesis_role,
                    near_duplicate_jaccard=supervisor.policy.program_synthesis_near_duplicate_jaccard,
                )
                latest_queue.save_jsonl(queue_path)
                supervisor.queue = latest_queue
                queue = latest_queue
            for guidance_kind, guidance_todo_candidates in (
                guidance_todo_candidates_by_kind.items()
            ):
                if not guidance_todo_candidates:
                    continue
                with queue_file_lock(queue_path):
                    latest_queue = ModalTodoQueue.load_jsonl(queue_path)
                    latest_queue.merge_from(
                        supervisor.queue,
                        preserve_claimed_role=(
                            supervisor.policy.program_synthesis_role
                        ),
                    )
                    supervisor.queue = latest_queue
                    selected_guidance_todos = supervisor._bounded_new_todos(
                        guidance_todo_candidates,
                        track_program_deduped=True,
                    )
                    deduped_count = int(
                        supervisor.last_program_synthesis_deduped_count
                    )
                    before_guidance_todo_ids = {
                        todo.todo_id for todo in supervisor.queue.all()
                    }
                    seeded_count = supervisor.queue.add_many(selected_guidance_todos)
                    guidance_todo_ids[guidance_kind] = [
                        todo.todo_id
                        for todo in selected_guidance_todos
                        if todo.todo_id not in before_guidance_todo_ids
                        and supervisor.queue.get(todo.todo_id) is not None
                    ]
                    guidance_semantic_deduped_count = (
                        supervisor.queue.deduplicate_semantic(
                            optimizer_role=(
                                supervisor.policy.program_synthesis_role
                            ),
                            near_duplicate_jaccard=(
                                supervisor
                                .policy
                                .program_synthesis_near_duplicate_jaccard
                            ),
                        )
                    )
                    semantic_deduped_count += int(guidance_semantic_deduped_count)
                    guidance_todo_counts[
                        f"{guidance_kind}_deduped_count"
                    ] = deduped_count
                    guidance_todo_counts[
                        f"{guidance_kind}_seeded_count"
                    ] = int(seeded_count)
                    guidance_todo_counts[
                        f"{guidance_kind}_semantic_deduped_count"
                    ] = int(guidance_semantic_deduped_count)
                    supervisor.queue.save_jsonl(queue_path)
                    queue = supervisor.queue
            mark_cycle_phase("leanstral_rule_gap_projection")
            leanstral_rule_gap_projection = project_verified_leanstral_rule_gaps_into_queue(
                args=args,
                queue_path=queue_path,
                root=root,
                supervisor=supervisor,
                worker_health={},
            )
            queue = supervisor.queue
            mark_cycle_phase("leanstral_direct_guidance_projection")
            leanstral_direct_guidance_projection = (
                project_verified_leanstral_guidance_artifacts_into_queue(
                    args=args,
                    queue_path=queue_path,
                    root=root,
                    supervisor=supervisor,
                    artifact_paths=[
                        *[
                            str(path)
                            for path in introspection_export.get("paths", []) or []
                            if str(path)
                        ],
                        *[
                            str(path)
                            for path in daemon_hammer_guidance_cycle.get(
                                "artifact_paths",
                                [],
                            )
                            or []
                            if str(path)
                        ],
                    ],
                    autoencoder=autoencoder,
                    samples_by_id={
                        sample.sample_id: sample for sample in train_samples
                    },
                    worker_health={},
                )
            )
            queue = supervisor.queue
            leanstral_projection = combine_leanstral_projection_results(
                leanstral_rule_gap_projection,
                leanstral_direct_guidance_projection,
            )
            mark_cycle_phase("state_save")
            autoencoder.state.save_json(state_path)
            run.save_json(run_json_path)
            finish_cycle_phase()

            train_ce_delta = before_train.cross_entropy_loss - after_train.cross_entropy_loss
            validation_ce_delta = before_validation.cross_entropy_loss - after_validation.cross_entropy_loss
            train_cos_delta = after_train.embedding_cosine_similarity - before_train.embedding_cosine_similarity
            validation_cos_delta = (
                after_validation.embedding_cosine_similarity
                - before_validation.embedding_cosine_similarity
            )
            before_train_metrics = metric_block(before_train)
            before_validation_metrics = metric_block(before_validation)
            after_train_metrics = metric_block(after_train)
            skipped_sample_memory_probe_metrics = {
                "every_n_cycles": sample_memory_probe_every_n_cycles,
                "mode": sample_memory_probe_mode,
                "skipped": True,
            }
            after_train_generalized_probe_metrics = (
                metric_block(after_train_generalized_probe)
                if after_train_generalized_probe is not None
                else dict(skipped_sample_memory_probe_metrics)
            )
            after_validation_metrics = metric_block(after_validation)
            after_validation_sample_memory_probe_metrics = (
                metric_block(after_validation_sample_memory_probe)
                if after_validation_sample_memory_probe is not None
                else dict(skipped_sample_memory_probe_metrics)
            )
            train_sample_memory_gap = (
                autoencoder_memory_gap_block(
                    after_train_generalized_probe,
                    after_train,
                    dataset="train",
                    expected_holdout=False,
                )
                if after_train_generalized_probe is not None
                else {
                    **skipped_sample_memory_probe_metrics,
                    "dataset": "train",
                    "expected_holdout": False,
                }
            )
            validation_sample_memory_gap = (
                autoencoder_memory_gap_block(
                    after_validation,
                    after_validation_sample_memory_probe,
                    dataset="validation",
                    expected_holdout=True,
                )
                if after_validation_sample_memory_probe is not None
                else {
                    **skipped_sample_memory_probe_metrics,
                    "dataset": "validation",
                    "expected_holdout": True,
                }
            )
            learned_ir_before_train = learned_ir_metric_block(before_train)
            learned_ir_before_validation = learned_ir_metric_block(before_validation)
            learned_ir_train = learned_ir_metric_block(after_train)
            learned_ir_validation = learned_ir_metric_block(after_validation)
            latest_compiler_ir_ce = _metric_value(
                compiler_ir_validation,
                "cross_entropy_loss",
                1.0e12,
            )
            latest_compiler_ir_ce_excess = _metric_value(
                compiler_ir_validation,
                "cross_entropy_excess_loss",
                1.0e12,
            )
            latest_compiler_ir_cosine = _metric_value(
                compiler_ir_validation,
                "cosine_similarity",
                -1.0,
            )
            latest_compiler_ir_raw_source_embedding_cosine = _metric_value(
                compiler_ir_validation,
                "raw_source_embedding_cosine_similarity",
                -1.0,
            )
            latest_compiler_ir_source_copy_loss = _metric_value(
                compiler_ir_validation,
                "source_copy_loss",
                1.0e12,
            )
            latest_compiler_ir_source_copy_reward_hack_penalty = _metric_value(
                compiler_ir_validation,
                "source_copy_reward_hack_penalty",
                1.0e12,
            )
            latest_source_decompiled_text_embedding_cosine_loss = _metric_value(
                compiler_ir_validation,
                "source_decompiled_text_embedding_cosine_loss",
                1.0e12,
            )
            latest_source_decompiled_text_token_loss = _metric_value(
                compiler_ir_validation,
                "source_decompiled_text_token_loss",
                1.0e12,
            )
            latest_guided_compiler_ir_ce = _metric_value(
                compiler_ir_guided_validation,
                "cross_entropy_loss",
                1.0e12,
            )
            latest_guided_compiler_ir_ce_excess = _metric_value(
                compiler_ir_guided_validation,
                "cross_entropy_excess_loss",
                1.0e12,
            )
            latest_guided_compiler_ir_cosine = _metric_value(
                compiler_ir_guided_validation,
                "cosine_similarity",
                -1.0,
            )
            latest_guided_compiler_ir_source_copy_reward_hack_penalty = _metric_value(
                compiler_ir_guided_validation,
                "source_copy_reward_hack_penalty",
                1.0e12,
            )
            latest_compiler_ir_guidance_ce_delta = float(guidance_canary["ce_delta"])
            latest_compiler_ir_guidance_cosine_delta = float(
                guidance_canary["cosine_delta"]
            )
            latest_compiler_ir_guidance_copy_hack_delta = float(
                guidance_canary["copy_hack_delta"]
            )
            latest_learned_ir_view_ce = _metric_value(
                learned_ir_validation,
                "view_cross_entropy_loss",
                1.0e12,
            )
            latest_learned_ir_view_cosine = _metric_value(
                learned_ir_validation,
                "view_cosine_similarity",
                -1.0,
            )
            latest_cycle_seconds = round(time.time() - cycle_started, 3)
            latest_state_telemetry = autoencoder_state_telemetry(
                autoencoder.state,
                state_path=state_path,
            )
            backend_metadata = autoencoder.compute_backend_metadata()
            host_resource_health = _host_resource_health()
            summary["cycles"] = cycle
            summary["latest_stop_reason"] = run.stopped_reason
            summary.update(backend_metadata)
            summary["latest_autoencoder_backend"] = dict(backend_metadata)
            summary["latest_host_resource_health"] = dict(host_resource_health)
            summary["latest_queue_counts"] = supervisor.queue.status_counts()
            summary["latest_role_queue_counts"] = supervisor.queue.role_status_counts()
            summary["latest_feature_projection_report"] = feature_projection_report
            summary["latest_cycle_seconds"] = latest_cycle_seconds
            summary["latest_cycle_phase_timings"] = {
                name: round(seconds, 3)
                for name, seconds in sorted(cycle_phase_timings.items())
            }
            summary["latest_autoencoder_state_telemetry"] = latest_state_telemetry
            summary["latest_autoencoder_train"] = after_train_metrics
            summary["latest_autoencoder_train_generalized_probe"] = (
                after_train_generalized_probe_metrics
            )
            summary["latest_autoencoder_validation"] = after_validation_metrics
            summary["latest_autoencoder_validation_sample_memory_probe"] = (
                after_validation_sample_memory_probe_metrics
            )
            summary["latest_autoencoder_before_validation"] = before_validation_metrics
            summary["latest_train_sample_memory_gap"] = train_sample_memory_gap
            summary["latest_validation_sample_memory_gap"] = validation_sample_memory_gap
            summary["latest_train_ce"] = after_train.cross_entropy_loss
            summary["latest_train_cosine"] = after_train.embedding_cosine_similarity
            summary["latest_train_reconstruction"] = after_train.reconstruction_loss
            summary["latest_validation_ce"] = after_validation.cross_entropy_loss
            summary["latest_validation_cosine"] = (
                after_validation.embedding_cosine_similarity
            )
            summary["latest_validation_reconstruction"] = (
                after_validation.reconstruction_loss
            )
            summary["latest_train_ce_delta"] = train_ce_delta
            summary["latest_train_cosine_delta"] = train_cos_delta
            summary["latest_validation_ce_delta"] = validation_ce_delta
            summary["latest_validation_cosine_delta"] = validation_cos_delta
            summary["latest_compiler_ir_train"] = compiler_ir_train
            summary["latest_compiler_ir_validation"] = compiler_ir_validation
            summary["latest_compiler_ir_guided_train"] = compiler_ir_guided_train
            summary["latest_compiler_ir_guided_validation"] = (
                compiler_ir_guided_validation
            )
            summary["latest_compiler_ir_ce"] = latest_compiler_ir_ce
            summary["latest_compiler_ir_ce_excess"] = latest_compiler_ir_ce_excess
            summary["latest_compiler_ir_cosine"] = latest_compiler_ir_cosine
            summary["latest_compiler_ir_raw_source_embedding_cosine"] = (
                latest_compiler_ir_raw_source_embedding_cosine
            )
            summary["latest_cosine_metric_disagreement"] = {
                "compiler_ir_cosine_metric": (
                    "deterministic compiler/decompiler structural IR round-trip"
                ),
                "compiler_ir_minus_autoencoder_embedding_cosine": round(
                    latest_compiler_ir_cosine
                    - after_validation.embedding_cosine_similarity,
                    9,
                ),
                "compiler_raw_source_embedding_cosine_metric": (
                    "deterministic compiler decoded text embedding vs source embedding"
                ),
                "compiler_raw_source_embedding_minus_autoencoder_embedding_cosine": round(
                    latest_compiler_ir_raw_source_embedding_cosine
                    - after_validation.embedding_cosine_similarity,
                    9,
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
                    or []
                ),
            }
            summary["latest_compiler_ir_source_copy_loss"] = (
                latest_compiler_ir_source_copy_loss
            )
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
            summary["latest_compiler_ir_guided_cosine"] = (
                latest_guided_compiler_ir_cosine
            )
            summary[
                "latest_compiler_ir_guided_source_copy_reward_hack_penalty"
            ] = latest_guided_compiler_ir_source_copy_reward_hack_penalty
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
            summary["latest_introspection_disagreement_export"] = (
                introspection_export
            )
            summary["introspection_disagreement_export_packet_count"] = int(
                summary.get("introspection_disagreement_export_packet_count", 0)
            ) + int(introspection_export.get("packet_count", 0) or 0)
            summary["introspection_disagreement_export_schema_failure_count"] = int(
                summary.get(
                    "introspection_disagreement_export_schema_failure_count",
                    0,
                )
            ) + int(introspection_export.get("schema_failure_count", 0) or 0)
            summary["introspection_disagreement_export_failure_count"] = int(
                summary.get("introspection_disagreement_export_failure_count", 0)
            ) + int(introspection_export.get("export_failure_count", 0) or 0)
            export_paths = [
                str(path)
                for path in summary.get(
                    "introspection_disagreement_export_paths",
                    [],
                )
                or []
                if str(path)
            ]
            for export_path in introspection_export.get("paths", []) or []:
                if str(export_path) and str(export_path) not in export_paths:
                    export_paths.append(str(export_path))
            summary["introspection_disagreement_export_paths"] = export_paths
            summary["latest_compiler_ir_guidance_ce_delta"] = (
                latest_compiler_ir_guidance_ce_delta
            )
            summary["latest_compiler_ir_guidance_cosine_delta"] = (
                latest_compiler_ir_guidance_cosine_delta
            )
            summary["latest_compiler_ir_guidance_copy_hack_delta"] = (
                latest_compiler_ir_guidance_copy_hack_delta
            )
            summary["latest_learned_ir_before_train"] = learned_ir_before_train
            summary["latest_learned_ir_before_validation"] = (
                learned_ir_before_validation
            )
            summary["latest_learned_ir_train"] = learned_ir_train
            summary["latest_learned_ir_validation"] = learned_ir_validation
            summary["latest_learned_ir_view_ce"] = latest_learned_ir_view_ce
            summary["latest_learned_ir_view_cosine"] = latest_learned_ir_view_cosine
            summary["latest_rollout_baseline_snapshot"] = rollout_baseline_snapshot(
                summary=summary,
                cycle=cycle,
                cycle_seconds=latest_cycle_seconds,
                cycle_phase_timings=summary["latest_cycle_phase_timings"],
                validation_metrics=after_validation_metrics,
                compiler_ir_validation=compiler_ir_validation,
                compiler_ir_guided_validation=compiler_ir_guided_validation,
                learned_ir_validation=learned_ir_validation,
                logic_bridge_validation=bridge_ir_validation,
                queue_counts=summary["latest_queue_counts"],
                role_queue_counts=summary["latest_role_queue_counts"],
                state_telemetry=latest_state_telemetry,
                backend_metadata=backend_metadata,
                host_resource_health=host_resource_health,
                metric_bridge_adapters=metric_bridge_adapters,
                diagnostic_bridge_adapters=diagnostic_bridge_adapters,
            )
            summary["state_to_compiler_patch_lag"] = state_to_compiler_patch_lag(
                summary
            )
            summary["supervisor_health"] = build_modal_supervisor_health_report(
                summary
            ).to_dict()
            summary["validation_mode"] = validation_mode
            program_synthesis_status = update_program_synthesis_summary(
                summary,
                supervisor.queue,
                supervisor.policy,
            )
            summary["program_synthesis_transient_failure"] = (
                supervisor.queue.transient_failure_counts(
                    optimizer_role=supervisor.policy.program_synthesis_role
                )
            )
            summary["program_synthesis_transient_failure_rate"] = (
                supervisor.queue.transient_failure_rate(
                    optimizer_role=supervisor.policy.program_synthesis_role
                )
            )
            summary["program_synthesis_queue_pressure"] = (
                _program_synthesis_queue_pressure(
                    program_synthesis_status,
                    pending_cap=int(supervisor.policy.max_program_synthesis_pending),
                )
            )
            summary["program_synthesis_metric_feedback"] = (
                _program_synthesis_metric_feedback_report(
                    supervisor.queue,
                    compiler_ir_validation_sample_ids=compiler_ir_validation_sample_ids,
                )
            )
            summary["program_synthesis_seeded"] = int(
                summary.get("program_synthesis_seeded", 0)
            ) + sum(step.program_synthesis_seeded_count for step in run.steps) + sum(
                value
                for key, value in guidance_todo_counts.items()
                if key.endswith("_seeded_count")
            ) + int(leanstral_projection.get("seeded_count", 0) or 0)
            preinsert_deduped_count = sum(
                step.program_synthesis_deduped_count for step in run.steps
            ) + sum(
                value
                for key, value in guidance_todo_counts.items()
                if key.endswith("_deduped_count")
                and not key.endswith("_semantic_deduped_count")
            ) + int(leanstral_projection.get("deduped_count", 0) or 0)
            summary["latest_program_synthesis_seeded_count"] = sum(
                step.program_synthesis_seeded_count for step in run.steps
            ) + sum(
                value
                for key, value in guidance_todo_counts.items()
                if key.endswith("_seeded_count")
            ) + int(leanstral_projection.get("seeded_count", 0) or 0)
            summary["latest_program_synthesis_preinsert_deduped_count"] = int(
                preinsert_deduped_count
            )
            summary["latest_program_synthesis_semantic_deduped_count"] = int(
                semantic_deduped_count
            )
            for guidance_kind in ("activation", "distillation", "guardrail"):
                summary[
                    f"latest_compiler_ir_guidance_{guidance_kind}_deduped_count"
                ] = int(guidance_todo_counts[f"{guidance_kind}_deduped_count"])
                summary[
                    f"latest_compiler_ir_guidance_{guidance_kind}_seeded_count"
                ] = int(guidance_todo_counts[f"{guidance_kind}_seeded_count"])
                summary[
                    "latest_compiler_ir_guidance_"
                    f"{guidance_kind}_semantic_deduped_count"
                ] = int(
                    guidance_todo_counts[
                        f"{guidance_kind}_semantic_deduped_count"
                    ]
                )
                summary[
                    f"latest_compiler_ir_guidance_{guidance_kind}_todo_ids"
                ] = list(guidance_todo_ids[guidance_kind])
                summary[
                    f"compiler_ir_guidance_{guidance_kind}_seeded_total"
                ] = int(
                    summary.get(
                        f"compiler_ir_guidance_{guidance_kind}_seeded_total",
                        0,
                    )
                ) + int(guidance_todo_counts[f"{guidance_kind}_seeded_count"])
                summary[
                    f"compiler_ir_guidance_{guidance_kind}_deduped_total"
                ] = int(
                    summary.get(
                        f"compiler_ir_guidance_{guidance_kind}_deduped_total",
                        0,
                    )
                ) + int(guidance_todo_counts[f"{guidance_kind}_deduped_count"])
                summary[
                    "compiler_ir_guidance_"
                    f"{guidance_kind}_semantic_deduped_total"
                ] = int(
                    summary.get(
                        "compiler_ir_guidance_"
                        f"{guidance_kind}_semantic_deduped_total",
                        0,
                    )
                ) + int(
                    guidance_todo_counts[
                        f"{guidance_kind}_semantic_deduped_count"
                    ]
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
            update_leanstral_projection_summary(summary, leanstral_projection)
            update_daemon_hammer_guidance_summary(
                summary,
                daemon_hammer_guidance_cycle,
                projection=leanstral_projection,
            )
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
            summary["latest_compiler_ir_validation_metrics"] = (
                compiler_ir_validation_metrics
            )
            summary["latest_compiler_ir_validation_profile"] = (
                compiler_ir_validation_profile
            )
            summary["latest_compiler_ir_validation_sample_count"] = len(
                compiler_ir_validation_sample_ids
            )
            summary["latest_compiler_ir_validation_sample_ids"] = (
                compiler_ir_validation_sample_ids
            )
            summary["compiler_ir_validation_comparable_to_previous_cycle"] = bool(
                compiler_ir_validation_comparable
            )
            summary["compiler_ir_validation_last_delta"] = compiler_ir_validation_delta
            if compiler_ir_validation_comparable:
                summary["compiler_ir_validation_ce_improved_cycles"] = int(
                    summary.get("compiler_ir_validation_ce_improved_cycles", 0)
                ) + int(compiler_ir_validation_delta.get("cross_entropy_loss", 0.0) > 0.0)
                summary["compiler_ir_validation_cosine_improved_cycles"] = int(
                    summary.get("compiler_ir_validation_cosine_improved_cycles", 0)
                ) + int(compiler_ir_validation_delta.get("cosine_similarity", 0.0) > 0.0)
            seen_compiler_ir_sample_ids = [
                str(sample_id)
                for sample_id in summary.get(
                    "compiler_ir_validation_sample_ids_seen",
                    [],
                )
                or []
            ]
            for sample_id in compiler_ir_validation_sample_ids:
                if sample_id and sample_id not in seen_compiler_ir_sample_ids:
                    seen_compiler_ir_sample_ids.append(sample_id)
            summary["compiler_ir_validation_sample_ids_seen"] = (
                seen_compiler_ir_sample_ids[-512:]
            )
            summary["compiler_ir_validation_unique_sample_count_seen"] = len(
                set(seen_compiler_ir_sample_ids)
            )
            summary["compiler_ir_validation_min_recommended_canaries"] = (
                DEFAULT_VALIDATION_CANARY_COUNT
            )
            summary["compiler_ir_validation_low_sample_warning"] = (
                validation_mode == "fixed_canary"
                and len(compiler_ir_validation_sample_ids)
                < DEFAULT_VALIDATION_CANARY_COUNT
            )
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
            summary[
                "best_validation_ir_guided_source_copy_reward_hack_penalty"
            ] = min(
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
            summary["best_validation_ir_text_reconstruction"] = min(
                summary.get("best_validation_ir_text_reconstruction", 1.0e12),
                float(compiler_ir_validation.get("text_reconstruction_loss", 1.0e12)),
            )
            summary["best_validation_ir_source_copy_loss"] = min(
                summary.get("best_validation_ir_source_copy_loss", 1.0e12),
                latest_compiler_ir_source_copy_loss,
            )
            summary["best_validation_ir_structural_text_reconstruction"] = min(
                summary.get(
                    "best_validation_ir_structural_text_reconstruction",
                    1.0e12,
                ),
                float(
                    compiler_ir_validation.get(
                        "structural_text_reconstruction_loss",
                        1.0e12,
                    )
                ),
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
            summary["best_validation_learned_ir_view_ce"] = min(
                summary.get("best_validation_learned_ir_view_ce", 1.0e12),
                latest_learned_ir_view_ce,
            )
            summary["best_validation_learned_ir_view_cosine"] = max(
                summary.get("best_validation_learned_ir_view_cosine", -1.0),
                latest_learned_ir_view_cosine,
            )
            summary["state_to_compiler_patch_lag"] = state_to_compiler_patch_lag(
                summary
            )
            summary["supervisor_health"] = build_modal_supervisor_health_report(
                summary
            ).to_dict()
            append_event(
                log_path,
                args.run_id,
                {
                    "after_train": after_train_metrics,
                    "after_validation": after_validation_metrics,
                    "applied_count": sum(step.applied_count for step in run.steps),
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
                    "compiler_ir_guidance_activation_deduped_count": int(
                        guidance_todo_counts["activation_deduped_count"]
                    ),
                    "compiler_ir_guidance_activation_seeded_count": int(
                        guidance_todo_counts["activation_seeded_count"]
                    ),
                    "compiler_ir_guidance_activation_todo_ids": list(
                        guidance_todo_ids["activation"]
                    ),
                    "compiler_ir_guidance_canary": guidance_canary,
                    "compiler_ir_guidance_ce_delta": (
                        latest_compiler_ir_guidance_ce_delta
                    ),
                    "compiler_ir_guidance_copy_hack_delta": (
                        latest_compiler_ir_guidance_copy_hack_delta
                    ),
                    "compiler_ir_guidance_cosine_delta": (
                        latest_compiler_ir_guidance_cosine_delta
                    ),
                    "compiler_ir_guidance_distillation": guidance_distillation,
                    "introspection_disagreement_export": introspection_export,
                    "compiler_ir_guidance_distillation_deduped_count": int(
                        guidance_todo_counts["distillation_deduped_count"]
                    ),
                    "compiler_ir_guidance_distillation_seeded_count": int(
                        guidance_todo_counts["distillation_seeded_count"]
                    ),
                    "compiler_ir_guidance_distillation_todo_ids": list(
                        guidance_todo_ids["distillation"]
                    ),
                    "compiler_ir_guidance_guardrail_deduped_count": int(
                        guidance_todo_counts["guardrail_deduped_count"]
                    ),
                    "compiler_ir_guidance_guardrail_seeded_count": int(
                        guidance_todo_counts["guardrail_seeded_count"]
                    ),
                    "compiler_ir_guidance_guardrail_todo_ids": list(
                        guidance_todo_ids["guardrail"]
                    ),
                    "leanstral_projection": leanstral_projection,
                    "leanstral_direct_guidance_projection": (
                        leanstral_direct_guidance_projection
                    ),
                    "leanstral_rule_gap_projection": leanstral_rule_gap_projection,
                    "leanstral_projection_budget_blocked_count": int(
                        leanstral_projection.get("budget_blocked_count", 0) or 0
                    ),
                    "leanstral_projection_deduped_count": int(
                        leanstral_projection.get("deduped_count", 0) or 0
                    ),
                    "leanstral_projection_report_only_count": int(
                        leanstral_projection.get("report_only_count", 0) or 0
                    ),
                    "leanstral_projection_seeded_count": int(
                        leanstral_projection.get("seeded_count", 0) or 0
                    ),
                    "leanstral_projection_stale_count": int(
                        leanstral_projection.get("stale_count", 0) or 0
                    ),
                    "compiler_ir_guidance_promotion": guidance_promotion_gate,
                    "compiler_ir_guidance_scope_hints": guidance_scope_hints,
                    "compiler_ir_train": compiler_ir_train,
                    "compiler_ir_validation": compiler_ir_validation,
                    "daemon_hammer_guidance": daemon_hammer_guidance_cycle,
                    "compiler_ir_validation_comparable_to_previous_cycle": bool(
                        compiler_ir_validation_comparable
                    ),
                    "compiler_ir_validation_delta": compiler_ir_validation_delta,
                    "compiler_ir_validation_sample_count": len(
                        compiler_ir_validation_sample_ids
                    ),
                    "compiler_ir_validation_sample_ids": (
                        compiler_ir_validation_sample_ids[:32]
                    ),
                    "logic_bridge_train": bridge_ir_train,
                    "logic_bridge_validation": bridge_ir_validation,
                    "learned_ir_before_train": learned_ir_before_train,
                    "learned_ir_before_validation": learned_ir_before_validation,
                    "learned_ir_train": learned_ir_train,
                    "learned_ir_validation": learned_ir_validation,
                    "train_sample_memory_gap": train_sample_memory_gap,
                    "validation_sample_memory_gap": validation_sample_memory_gap,
                    "cycle": cycle,
                    "duration_seconds": latest_cycle_seconds,
                    "event": "cycle",
                    "failed_validation_count": sum(step.failed_validation_count for step in run.steps),
                    "feature_projection_report": feature_projection_report,
                    "state_to_compiler_patch_lag": summary.get(
                        "state_to_compiler_patch_lag",
                        {},
                    ),
                    "supervisor_health": summary.get("supervisor_health", {}),
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
                    )
                    + sum(
                        value
                        for key, value in guidance_todo_counts.items()
                        if key.endswith("_seeded_count")
                    )
                    + int(leanstral_projection.get("seeded_count", 0) or 0),
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
        summary["program_synthesis_transient_failure"] = (
            supervisor.queue.transient_failure_counts(
                optimizer_role=supervisor.policy.program_synthesis_role
            )
        )
        summary["program_synthesis_transient_failure_rate"] = (
            supervisor.queue.transient_failure_rate(
                optimizer_role=supervisor.policy.program_synthesis_role
            )
        )
        summary["program_synthesis_queue_pressure"] = _program_synthesis_queue_pressure(
            summary,
            pending_cap=int(supervisor.policy.max_program_synthesis_pending),
        )
        summary["state_to_compiler_patch_lag"] = state_to_compiler_patch_lag(summary)
        summary["supervisor_health"] = build_modal_supervisor_health_report(
            summary
        ).to_dict()
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
            "codex_main_apply_lock_timeout_seconds": (
                args.codex_main_apply_lock_timeout_seconds
            ),
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
    summary.setdefault(
        "codex_main_apply_lock_timeout_seconds",
        args.codex_main_apply_lock_timeout_seconds,
    )
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
            "codex_main_apply_lock_timeout_seconds": (
                args.codex_main_apply_lock_timeout_seconds
            ),
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
                        main_apply_lock_timeout_seconds=(
                            args.codex_main_apply_lock_timeout_seconds
                        ),
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
            summary["heartbeat_at"] = utc_now()
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
            summary["codex_transient_failure_rate"] = (
                round(
                    float(summary.get("codex_transient_requeue_count", 0) or 0)
                    / float(max(1, int(summary.get("codex_execution_count", 0) or 0))),
                    6,
                )
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
            worktree_cleanup = (
                cleanup_codex_packet_worktree(packet)
                if packet.get("worktree_path")
                else {"status": "skipped", "reason": "missing_worktree_path"}
            )
            if packet.get("packet_path"):
                packet["worktree_cleanup"] = dict(worktree_cleanup)
                _save_packet_if_possible(
                    packet,
                    Path(str(packet["packet_path"])),
                )
            summary["elapsed_seconds"] = round(time.time() - started_at, 3)
            summary["latest_queue_counts"] = queue.status_counts()
            summary["latest_role_queue_counts"] = queue.role_status_counts()
            summary["program_synthesis_transient_failure"] = queue.transient_failure_counts(
                optimizer_role=policy.program_synthesis_role
            )
            summary["program_synthesis_transient_failure_rate"] = (
                queue.transient_failure_rate(
                    optimizer_role=policy.program_synthesis_role
                )
            )
            if vector_claim_report:
                summary["latest_codex_vector_claim_report"] = dict(vector_claim_report)
            summary["latest_stop_reason"] = (
                "claimed_program_synthesis_todos"
                if claimed
                else "waiting_for_program_synthesis_todos"
            )
            metric_event_fields = _codex_packet_metric_event_fields(packet)
            if metric_event_fields:
                summary["latest_codex_target_metric_event"] = dict(metric_event_fields)
            event_payload = {
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
                    "worktree_cleanup": worktree_cleanup,
            }
            event_payload.update(metric_event_fields)
            append_event(
                log_path,
                args.run_id,
                event_payload,
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
        summary["heartbeat_at"] = utc_now()
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
            summary["program_synthesis_transient_failure"] = queue.transient_failure_counts(
                optimizer_role=policy.program_synthesis_role
            )
            summary["program_synthesis_transient_failure_rate"] = (
                queue.transient_failure_rate(
                    optimizer_role=policy.program_synthesis_role
                )
            )
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
