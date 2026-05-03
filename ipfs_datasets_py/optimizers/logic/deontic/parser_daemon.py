"""Agentic daemon for deterministic legal parser parity work.

The daemon runs bounded optimization cycles against the deterministic deontic
legal parser.  Each cycle:

1. evaluates parser quality on a representative probe corpus;
2. reads the two deterministic-parser roadmap documents;
3. asks ``llm_router`` for a strict JSON improvement proposal using a pinned
   model, defaulting to ``gpt-5.5``;
4. stores the proposal and unified diff as cycle artifacts;
5. optionally applies the diff and runs validation tests.

The default mode is patch-only.  This keeps unattended runs auditable and avoids
mutating the working tree unless the operator passes ``--apply-patches``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import traceback
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
from ipfs_datasets_py.logic.deontic.exports import active_repair_details_from_parser_elements
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    build_deontic_formula,
    extract_normative_elements,
)
from ipfs_datasets_py.optimizers.agentic.base import OptimizationMethod
from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig,
)


DEFAULT_PROBE_CORPUS: List[Dict[str, str]] = [
    {"id": "simple_obligation", "text": "The tenant must pay rent monthly."},
    {"id": "simple_permission", "text": "The permittee may appeal the decision."},
    {"id": "simple_prohibition", "text": "No person may discharge pollutants into the sewer."},
    {"id": "passive_duty", "text": "The notice shall be published by the Bureau."},
    {"id": "definition", "text": 'In this section, the term "food cart" means a mobile food vending unit.'},
    {"id": "conditional", "text": "The Director shall issue a permit if all requirements are met."},
    {"id": "exception", "text": "The applicant shall obtain a permit unless approval is denied."},
    {"id": "override", "text": "Notwithstanding section 5.01.020, the Director may issue a variance."},
    {"id": "temporal", "text": "The Director shall issue a permit within 10 days after application."},
    {"id": "procedure", "text": "Upon receipt of an application, the Bureau shall inspect the premises before approval."},
    {"id": "penalty", "text": "A violation is punishable by a civil fine of not less than $100 and not more than $500 per violation."},
    {"id": "applicability", "text": "This section applies to food carts and mobile vendors."},
    {"id": "exemption", "text": "A permit is not required for emergency work."},
    {"id": "lifecycle_valid", "text": "The license is valid for 30 days."},
    {"id": "lifecycle_expiry", "text": "The permit expires one year after issuance."},
    {"id": "enumerated", "text": "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records."},
    {"id": "cross_reference", "text": "The Secretary shall publish the notice except as provided in section 552."},
]

LEGAL_PARSER_RECOVERY_TARGETS: Tuple[str, ...] = (
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/exports.py",
    "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
    "tests/unit_tests/logic/deontic/test_deontic_converter.py",
    "tests/unit_tests/logic/deontic/test_deontic_exports.py",
)


@dataclass
class LegalParserDaemonConfig:
    """Configuration for legal parser optimization cycles."""

    repo_root: Path = field(default_factory=lambda: Path.cwd())
    output_dir: Path = field(default_factory=lambda: Path("artifacts/legal_parser_optimizer_daemon"))
    model_name: str = "gpt-5.5"
    provider: Optional[str] = None
    max_cycles: int = 1
    cycle_interval_seconds: float = 0.0
    error_backoff_seconds: float = 30.0
    target_score: float = 0.98
    min_score_improvement: float = 0.001
    apply_patches: bool = False
    commit_accepted_patches: bool = False
    require_clean_touched_files: bool = True
    run_tests: bool = True
    test_command: Tuple[str, ...] = ("pytest", "tests/unit_tests/logic/deontic")
    llm_max_tokens: int = 6000
    llm_temperature: float = 0.1
    llm_timeout_seconds: int = 900
    llm_proposal_attempts: int = 3
    heartbeat_interval_seconds: float = 15.0
    test_timeout_seconds: int = 600
    require_production_and_tests: bool = True
    docs: Tuple[str, ...] = (
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md",
        "docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md",
    )
    target_files: Tuple[str, ...] = (
        "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
        "ipfs_datasets_py/logic/deontic/ir.py",
        "ipfs_datasets_py/logic/deontic/formula_builder.py",
        "ipfs_datasets_py/logic/deontic/converter.py",
        "ipfs_datasets_py/logic/deontic/exports.py",
        "ipfs_datasets_py/logic/deontic",
        "tests/unit_tests/logic/deontic/test_deontic_formula_builder.py",
        "tests/unit_tests/logic/deontic/test_deontic_converter.py",
        "tests/unit_tests/logic/deontic/test_deontic_exports.py",
        "tests/unit_tests/logic/deontic",
    )

    def resolved_output_dir(self) -> Path:
        return _resolve_path(self.repo_root, self.output_dir)

    def provider_label(self) -> str:
        """Return the human-facing provider label used in daemon status files."""

        provider = str(self.provider or "").strip()
        return provider or "llm_router"

    def llm_router_provider(self) -> Optional[str]:
        """Return the concrete provider argument for ``llm_router.generate_text``.

        ``llm_router`` is a supervisor-facing alias meaning: call the router and
        let its normal env/default backend selection choose the concrete provider.
        """

        provider = str(self.provider or "").strip()
        if not provider or provider.lower() in {"llm_router", "router", "auto"}:
            return None
        return provider


@dataclass
class LegalParserCycleProposal:
    """LLM-proposed patch plus metadata."""

    summary: str = ""
    focus_area: str = ""
    requirements_addressed: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    expected_metric_gain: Dict[str, Any] = field(default_factory=dict)
    tests_to_run: List[str] = field(default_factory=list)
    unified_diff: str = ""
    raw_response: str = ""
    parse_error: str = ""


class LegalParserParityOptimizer(BaseOptimizer):
    """Optimizer that critiques and improves deterministic legal parser parity."""

    def __init__(
        self,
        config: Optional[OptimizerConfig] = None,
        llm_backend: Optional[Any] = None,
        daemon_config: Optional[LegalParserDaemonConfig] = None,
    ) -> None:
        self.daemon_config = daemon_config or LegalParserDaemonConfig()
        self.daemon_config.repo_root = self.daemon_config.repo_root.resolve()
        super().__init__(config=config or OptimizerConfig(), llm_backend=llm_backend)
        self.llm_backend = llm_backend

    def generate(self, input_data: Any, context: OptimizationContext) -> Dict[str, Any]:
        return self.evaluate_current_parser()

    def critique(self, artifact: Any, context: OptimizationContext) -> Tuple[float, List[str]]:
        metrics = artifact.get("metrics", {}) if isinstance(artifact, dict) else {}
        score = float(metrics.get("parity_score", 0.0) or 0.0)
        feedback = list(metrics.get("coverage_gaps", []) or [])
        return score, feedback

    def optimize(
        self,
        artifact: Any,
        score: float,
        feedback: List[str],
        context: OptimizationContext,
    ) -> LegalParserCycleProposal:
        return self.request_llm_patch(
            cycle_index=int(context.metadata.get("cycle_index", 1)),
            evaluation=artifact if isinstance(artifact, dict) else {},
            feedback=feedback,
        )

    def validate(self, artifact: Any, context: OptimizationContext) -> bool:
        if not isinstance(artifact, LegalParserCycleProposal):
            return False
        if not artifact.unified_diff.strip():
            return False
        return self.check_patch(artifact.unified_diff)["valid"]

    def evaluate_current_parser(self) -> Dict[str, Any]:
        """Evaluate deterministic parser coverage on the probe corpus."""

        samples: List[Dict[str, Any]] = []
        all_elements: List[Dict[str, Any]] = []
        unparsed: List[str] = []
        formula_errors: List[Dict[str, str]] = []

        for sample in DEFAULT_PROBE_CORPUS:
            text = sample["text"]
            try:
                elements = extract_normative_elements(text, expand_enumerations=True)
            except Exception as exc:
                elements = []
                formula_errors.append({"id": sample["id"], "error": str(exc)})
            if not elements:
                unparsed.append(sample["id"])
            formulas: List[str] = []
            for element in elements:
                element = dict(element)
                element["_probe_sample_id"] = sample["id"]
                all_elements.append(element)
                try:
                    formulas.append(build_deontic_formula(element))
                except Exception as exc:
                    formula_errors.append({"id": sample["id"], "error": str(exc)})
            samples.append(
                {
                    "id": sample["id"],
                    "text": text,
                    "element_count": len(elements),
                    "formulas": formulas,
                    "proof_ready": sum(1 for element in elements if element.get("promotable_to_theorem") is True),
                    "warnings": [element.get("parser_warnings", []) for element in elements],
                }
            )

        summary = summarize_parser_elements(all_elements)
        repair_required_details = active_repair_details_from_parser_elements(all_elements)
        repair_required = [
            str(detail.get("source_id") or detail.get("sample_id") or "") for detail in repair_required_details
        ]
        sample_count = len(DEFAULT_PROBE_CORPUS)
        parsed_rate = (sample_count - len(unparsed)) / max(1, sample_count)
        proof_ready_rate = float(summary.get("proof_ready_rate", 0.0) or 0.0)
        schema_valid_rate = float(summary.get("schema_valid_rate", 0.0) or 0.0)
        repair_rate = float(summary.get("repair_required_rate", 0.0) or 0.0)
        formula_error_rate = len(formula_errors) / max(1, sample_count)
        parity_score = max(
            0.0,
            min(
                1.0,
                (0.30 * parsed_rate)
                + (0.25 * schema_valid_rate)
                + (0.25 * proof_ready_rate)
                + (0.20 * (1.0 - repair_rate))
                - (0.20 * formula_error_rate),
            ),
        )

        coverage_gaps: List[str] = []
        if unparsed:
            coverage_gaps.append(f"unparsed_probe_categories: {', '.join(unparsed)}")
        if repair_required:
            coverage_gaps.append(f"repair_required_count: {len(repair_required)}")
        if formula_errors:
            coverage_gaps.append(f"formula_error_count: {len(formula_errors)}")
        if proof_ready_rate < 0.90:
            coverage_gaps.append(f"proof_ready_rate_below_target: {proof_ready_rate:.3f}")

        return {
            "status": "evaluated",
            "metrics": {
                **summary,
                "probe_sample_count": sample_count,
                "parsed_rate": round(parsed_rate, 4),
                "formula_error_rate": round(formula_error_rate, 4),
                "parity_score": round(parity_score, 4),
                "coverage_gaps": coverage_gaps,
            },
            "samples": samples,
            "unparsed": unparsed,
            "repair_required": repair_required,
            "repair_required_details": repair_required_details,
            "formula_errors": formula_errors,
        }

    def request_llm_patch(
        self,
        *,
        cycle_index: int,
        evaluation: Dict[str, Any],
        feedback: Sequence[str],
    ) -> LegalParserCycleProposal:
        """Ask llm_router for a legal-parser improvement patch."""

        prompt = self.build_patch_prompt(cycle_index=cycle_index, evaluation=evaluation, feedback=feedback)
        pre_llm_diff = self._working_tree_diff()
        try:
            with self._read_only_codex_cli_generation():
                if self.llm_backend is not None:
                    raw_response = self.llm_backend.generate(
                        prompt,
                        method=OptimizationMethod.TEST_DRIVEN,
                        max_tokens=self.daemon_config.llm_max_tokens,
                        temperature=self.daemon_config.llm_temperature,
                        router_kwargs={
                            "provider": self.daemon_config.llm_router_provider(),
                            "provider_label": self.daemon_config.provider_label(),
                            "model_name": self.daemon_config.model_name,
                            "allow_local_fallback": False,
                            "disable_model_retry": True,
                            "timeout": self.daemon_config.llm_timeout_seconds,
                            "sandbox": "read-only",
                        },
                    )
                else:
                    from ipfs_datasets_py import llm_router

                    raw_response = llm_router.generate_text(
                        prompt,
                        provider=self.daemon_config.llm_router_provider(),
                        model_name=self.daemon_config.model_name,
                        max_tokens=self.daemon_config.llm_max_tokens,
                        temperature=self.daemon_config.llm_temperature,
                        timeout=self.daemon_config.llm_timeout_seconds,
                        allow_local_fallback=False,
                        disable_model_retry=True,
                    )
        finally:
            restore_result = self._restore_working_tree_diff(pre_llm_diff)
            if not restore_result.get("valid"):
                legal_target_status = self._dirty_legal_parser_target_status()
                if not legal_target_status.get("valid") or legal_target_status.get("paths"):
                    raise RuntimeError(
                        "llm proposal generation changed legal-parser targets and automatic restore failed: "
                        + str(
                            {
                                "restore": restore_result,
                                "dirty_legal_parser_targets": legal_target_status,
                            }
                        )
                    )
        return parse_cycle_proposal(raw_response)

    def _read_only_codex_cli_generation(self) -> "_TemporaryEnv":
        provider = str(self.daemon_config.provider or "").strip().lower()
        if provider and provider not in {"codex", "codex_cli", "llm_router", "router", "auto"}:
            return _TemporaryEnv({})
        return _TemporaryEnv({"IPFS_DATASETS_PY_CODEX_SANDBOX": "read-only"})

    def _working_tree_diff(self) -> str:
        result = _run_command(
            ["git", "diff", "--binary"],
            cwd=self.daemon_config.repo_root,
            timeout=60,
        )
        return str(result.get("stdout") or "")

    def _restore_working_tree_diff(self, expected_diff: str) -> Dict[str, Any]:
        current_diff = self._working_tree_diff()
        if current_diff == expected_diff:
            return {"valid": True, "changed": False, "reason": "working_tree_unchanged"}
        reverse_result = _run_command(
            ["git", "apply", "-R", "-"],
            cwd=self.daemon_config.repo_root,
            input_text=current_diff,
            timeout=60,
        )
        if not reverse_result.get("valid"):
            return {"valid": False, "changed": False, "reverse": reverse_result}
        result: Dict[str, Any] = {
            "valid": True,
            "changed": True,
            "reason": "restored_after_llm_side_effects",
            "reverse": reverse_result,
        }
        if expected_diff.strip():
            reapply_result = _run_command(
                ["git", "apply", "-"],
                cwd=self.daemon_config.repo_root,
                input_text=expected_diff,
                timeout=60,
            )
            result["reapply_preexisting"] = reapply_result
            result["valid"] = bool(reapply_result.get("valid"))
        return result

    def _dirty_legal_parser_target_status(self) -> Dict[str, Any]:
        """Return dirty legal-parser files after an LLM-generation side effect."""

        result = _run_command(
            ["git", "status", "--porcelain", "--", *LEGAL_PARSER_RECOVERY_TARGETS],
            cwd=self.daemon_config.repo_root,
            timeout=30,
        )
        checked_at = _utc_now()
        if not result.get("valid"):
            stderr = str(result.get("stderr") or "").strip()
            return {
                "valid": False,
                "paths": [],
                "source": "fresh_git_status_porcelain",
                "checked_at": checked_at,
                "fingerprint": "",
                "error": {
                    "returncode": result.get("returncode"),
                    "stderr_tail": stderr[-1000:],
                },
            }
        stdout = str(result.get("stdout") or "")
        paths = _paths_from_git_status_porcelain(stdout)
        return {
            "valid": True,
            "paths": paths,
            "source": "fresh_git_status_porcelain",
            "checked_at": checked_at,
            "fingerprint": _dirty_target_fingerprint(
                repo_root=self.daemon_config.repo_root,
                status_stdout=stdout,
                paths=paths,
            ),
            "error": {},
        }

    def build_patch_prompt(
        self,
        *,
        cycle_index: int,
        evaluation: Dict[str, Any],
        feedback: Sequence[str],
    ) -> str:
        docs_payload = {path: _read_text(self.daemon_config.repo_root / path, limit=24000) for path in self.daemon_config.docs}
        recent_cycle_history = self._recent_cycle_history(limit=5)
        patch_stability_mode = self._patch_stability_mode(recent_cycle_history)
        recent_failed_patch_files = self._recent_failed_patch_files(recent_cycle_history)
        recent_test_failures = self._recent_test_failures(recent_cycle_history)
        recent_test_failed_files = self._recent_test_failed_files(recent_test_failures)
        recent_metric_stall_failures = self._recent_metric_stall_failures(recent_cycle_history)
        recent_metric_stall_failed_files = self._recent_metric_stall_failed_files(recent_metric_stall_failures)
        expanded_snapshot_files = (
            set(recent_failed_patch_files)
            | set(recent_test_failed_files)
            | set(recent_metric_stall_failed_files)
        )
        test_failure_recovery_mode = bool(recent_test_failures)
        metric_no_progress_recovery_mode = bool(recent_metric_stall_failures)
        file_payload = {
            path: _read_text(
                self.daemon_config.repo_root / path,
                limit=70000 if path in expanded_snapshot_files else 20000,
            )
            for path in self.daemon_config.target_files
            if (self.daemon_config.repo_root / path).is_file()
        }
        progress_payload = self._progress_snapshot()
        metric_stall_mode = self._metric_stall_mode(progress_payload)
        roadmap_pivot_mode = self._roadmap_pivot_mode(progress_payload)
        irreducible_repair_blockers = self._irreducible_repair_blockers(evaluation)
        irreducible_residual_mode = metric_stall_mode and bool(irreducible_repair_blockers)
        slice_scale_contract = self._slice_scale_contract(
            progress_payload=progress_payload,
            patch_stability_mode=patch_stability_mode,
            metric_stall_mode=metric_stall_mode,
            roadmap_pivot_mode=roadmap_pivot_mode,
            test_failure_recovery_mode=test_failure_recovery_mode,
            metric_no_progress_recovery_mode=metric_no_progress_recovery_mode,
        )
        payload = {
            "cycle_index": cycle_index,
            "objective": (
                "Improve the deterministic legal parser toward parity with the LLM-based legal text "
                "to formal logic parser while preserving the no-LLM contract for proof-ready clauses."
            ),
            "hard_constraints": [
                "Return strict JSON only.",
                "Use a unified_diff patch rooted at the repository root.",
                "Do not remove deterministic quality gates or no-LLM tests.",
                "Add or update tests for every parser behavior change.",
                "Prefer deterministic source-grounded parsing over broad opaque heuristics.",
                "Keep existing public APIs backward compatible unless the docs explicitly require a migration.",
                "Choose a coherent implementation slice large enough to matter: parser behavior, IR/export/formula handling, and focused tests should advance together when the roadmap calls for it.",
                "Follow slice_scale_contract. Normal progress must cover a family of related legal constructions, not one synonym, one predicate spelling, or a single narrow example.",
                "In expanded_slice mode, target 3+ related constructions with 6-10 focused examples/assertions and a real production parser/formula/IR/export change.",
                "In patch_stability_family mode, stay within one production file plus one matching test file when possible, but still implement a family-sized change with 3+ related constructions.",
                "Avoid cosmetic churn, one-line metric gaming, and isolated test-only patches.",
                "If recent_cycle_history shows patch_check_failure_tail, regenerate the patch against relevant_file_snapshots exactly; do not repeat hunks from stale file versions.",
                "When patch_stability_mode is true, prefer one production file plus one matching test file; broad four-file patches are likely to be rejected before apply, but single-phrase micro-patches are also rejected.",
                "When metric_stall_mode is true, target a named unresolved repair_required_details item or coverage gap and set expected_metric_gain for a real metric such as repair_required_count, proof_ready_rate, cross_reference_resolution_rate, or parity_score.",
                "When progress_snapshot shows repeated metric_stall_no_metric_progress rollbacks, change the parser capability that produces the measured slot/formula/export instead of adding surrounding tests, docs, or export-only context.",
                "When irreducible_residual_mode is true, the remaining repair_required_count is a protected legal-reference blocker; do not try to clear it. Instead implement a roadmap parser capability with focused tests and set expected_metric_gain to deterministic_coverage, parser_capability, or coverage_expansion.",
                "When roadmap_pivot_mode is true, stop adding narrow procedural trigger/export variants. Prioritize Phase 8 encoder/decoder reconstruction or local theorem-prover syntax validation for frame logic, deontic CEC, FOL, deontic FOL, and deontic temporal FOL.",
                "When test_failure_recovery_mode is true, first address the named recent_test_failures and avoid repeating a patch shape that rolled back on the same exception.",
                "When recent_test_failures has failure_phase=candidate_post_apply_validation, the prior patch failed before retention; fix the focused test, collection, or py_compile signature shown there before broadening the slice.",
                "When recent_test_failures include py_compile, SyntaxError, or pytest collection failures, make the next patch compile-safe first: fix the exact file and line pattern shown in validation_failure_tail before adding new behavior.",
                "Preserve source-grounded parser slots that already extract facts such as mental_state, action, actor, modality, temporal constraints, and references; do not add tests that assert an extracted legal fact should become empty.",
                "When metric_no_progress_recovery_mode is true, do not repeat patches that only add context recovery around exports; change the actual parser/formula/IR behavior needed to move the shown pre/post metrics.",
                "Do not move metrics by clearing repair for unresolved, absent, mismatched, partial, or external numbered legal references; those must stay blocked unless exact same-document evidence is present.",
            ],
            "patch_stability_mode": patch_stability_mode,
            "metric_stall_mode": metric_stall_mode,
            "roadmap_pivot_mode": roadmap_pivot_mode,
            "irreducible_residual_mode": irreducible_residual_mode,
            "irreducible_repair_blockers": irreducible_repair_blockers,
            "test_failure_recovery_mode": test_failure_recovery_mode,
            "metric_no_progress_recovery_mode": metric_no_progress_recovery_mode,
            "slice_scale_contract": slice_scale_contract,
            "recent_failed_patch_files": recent_failed_patch_files,
            "recent_test_failed_files": recent_test_failed_files,
            "recent_test_failures": recent_test_failures,
            "recent_metric_stall_failed_files": recent_metric_stall_failed_files,
            "recent_metric_stall_failures": recent_metric_stall_failures,
            "docs": docs_payload,
            "evaluation": evaluation,
            "feedback": list(feedback),
            "progress_snapshot": progress_payload,
            "recent_cycle_history": recent_cycle_history,
            "target_files": list(self.daemon_config.target_files),
            "relevant_file_snapshots": file_payload,
            "required_json_schema": {
                "summary": "string",
                "focus_area": "parser|ir|formula|converter|exports|tests|daemon",
                "requirements_addressed": ["string"],
                "acceptance_criteria": ["string"],
                "changed_files": ["string"],
                "expected_metric_gain": {"string": "number|string|boolean"},
                "tests_to_run": ["string"],
                "unified_diff": "string",
            },
        }
        return (
            "You are an expert legal-formal-logic parser engineer. "
            "Propose one coherent, safe, test-driven implementation slice that advances the deterministic parser roadmap. "
            "The slice should be large enough to materially improve parser coverage, IR/export correctness, formula quality, or parity metrics, "
            "while remaining reviewable and fully covered by tests. "
            "The diff must normally touch at least one production parser/export file and at least one deontic test file. "
            "If patch_stability_mode is true, make the smallest useful patch that can apply cleanly against the provided snapshots. "
            "Smallest useful still means family-sized: 3+ related constructions and 6-10 focused assertions unless the prompt is explicitly in repair-only mode. "
            "If metric_stall_mode is true, do not propose harmless refactors; pick a concrete repair-required sample and name the metric expected to move. "
            "If irreducible_residual_mode is true, stop chasing repair_required_count and make a tested deterministic coverage improvement from the roadmap instead. "
            "If roadmap_pivot_mode is true, implement a Phase 8 encoder/decoder/prover-syntax slice instead of another procedural trigger/export synonym. "
            "If test_failure_recovery_mode is true, use recent_test_failures as regression constraints and include a focused fix for that failure mode; py_compile and pytest collection failures are blockers that must be fixed before semantic expansion. "
            "If metric_no_progress_recovery_mode is true, use recent_metric_stall_failures as hard evidence of what already failed to move metrics. "
            "Prioritize unresolved repair-required probes only when irreducible_residual_mode is false. "
            "Return JSON matching required_json_schema and nothing else.\n"
            + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )

    def _slice_scale_contract(
        self,
        *,
        progress_payload: Mapping[str, Any],
        patch_stability_mode: bool,
        metric_stall_mode: bool,
        roadmap_pivot_mode: bool,
        test_failure_recovery_mode: bool,
        metric_no_progress_recovery_mode: bool,
    ) -> Dict[str, Any]:
        """Describe how large the next autonomous implementation slice should be."""

        try:
            score = float(progress_payload.get("current_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            stalled_cycles = int(progress_payload.get("cycles_since_meaningful_progress", 0) or 0)
        except (TypeError, ValueError):
            stalled_cycles = 0
        expanded = metric_stall_mode or metric_no_progress_recovery_mode or score >= 0.95 or stalled_cycles >= 3

        if test_failure_recovery_mode:
            if expanded or roadmap_pivot_mode:
                return {
                    "mode": "repair_with_material_followthrough",
                    "minimum_related_constructions": 2,
                    "minimum_focused_examples_or_assertions": 4,
                    "target_focused_examples_or_assertions": "4-6",
                    "file_scope": "the failing production/test files plus the same capability family",
                    "instruction": (
                        "Fix the concrete validation failure first, then keep the patch in the same "
                        "file pair and add enough same-family assertions or examples to prevent the "
                        "failure from collapsing into a one-off micro-fix."
                    ),
                }
            return {
                "mode": "repair_first",
                "minimum_related_constructions": 1,
                "minimum_focused_examples_or_assertions": 2,
                "file_scope": "the failing production/test files named in recent_test_failures",
                "instruction": (
                    "Fix the concrete validation failure first; after it compiles, fold in only "
                    "nearby assertions needed to prevent the same failure."
                ),
            }
        if roadmap_pivot_mode:
            return {
                "mode": "phase8_cross_stack_slice",
                "minimum_related_constructions": 2,
                "minimum_focused_examples_or_assertions": 6,
                "file_scope": "encoder/decoder/prover syntax production code plus matching tests",
                "instruction": (
                    "Implement an encoder/decoder or theorem-prover syntax-check path that can "
                    "round-trip IR and exercise frame logic, deontic CEC, FOL, deontic FOL, or "
                    "deontic temporal FOL."
                ),
            }
        if patch_stability_mode:
            return {
                "mode": "patch_stability_family",
                "minimum_related_constructions": 3,
                "minimum_focused_examples_or_assertions": 6,
                "file_scope": "prefer one production file and one matching test file",
                "instruction": (
                    "Keep the patch easy to apply, but do not shrink it to one synonym or one "
                    "predicate spelling; cover a legal-construction family in the chosen file pair."
                ),
            }
        if expanded:
            return {
                "mode": "expanded_slice",
                "minimum_related_constructions": 3,
                "minimum_focused_examples_or_assertions": 6,
                "target_focused_examples_or_assertions": "6-10",
                "file_scope": "one to three production files plus matching deontic tests",
                "instruction": (
                    "Make one material capability advance, such as a parser/formula/IR/export family "
                    "or encoder/decoder/prover-syntax integration, with enough examples to move metrics."
                ),
            }
        return {
            "mode": "standard_material_slice",
            "minimum_related_constructions": 2,
            "minimum_focused_examples_or_assertions": 4,
            "file_scope": "at least one production file plus matching deontic tests",
            "instruction": (
                "Implement a coherent parser capability rather than a cosmetic or isolated single-case patch."
            ),
        }

    def _progress_snapshot(self) -> Dict[str, Any]:
        progress_path = self.daemon_config.resolved_output_dir() / "progress_summary.json"
        if not progress_path.exists():
            return {}
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            "total_cycles": progress.get("total_cycles", 0),
            "accepted_patch_count": progress.get("accepted_patch_count", 0),
            "rolled_back_count": progress.get("rolled_back_count", 0),
            "rolled_back_reason_counts": progress.get("rolled_back_reason_counts", {}),
            "rolled_back_since_meaningful_progress": progress.get("rolled_back_since_meaningful_progress", 0),
            "rolled_back_reasons_since_meaningful_progress": progress.get(
                "rolled_back_reasons_since_meaningful_progress", {}
            ),
            "rejected_patch_count": progress.get("rejected_patch_count", 0),
            "current_score": progress.get("current_score"),
            "score_delta": progress.get("score_delta"),
            "current_feedback": progress.get("current_feedback", []),
            "accepted_change_summaries": progress.get("accepted_change_summaries", [])[-8:],
            "stalled_metric_cycles": progress.get("stalled_metric_cycles", 0),
            "cycles_since_meaningful_progress": progress.get("cycles_since_meaningful_progress", 0),
            "meaningful_progress_definition": progress.get("meaningful_progress_definition", ""),
            "recent_rejections": progress.get("recent_rejections", [])[-8:],
            "repeated_rejection_family": progress.get("repeated_rejection_family", {}),
            "candidate_post_apply_validation_rejection_count": progress.get(
                "candidate_post_apply_validation_rejection_count", 0
            ),
            "latest_candidate_post_apply_validation_failure": progress.get(
                "latest_candidate_post_apply_validation_failure", {}
            ),
        }

    def _metric_stall_mode(self, progress_payload: Dict[str, Any]) -> bool:
        try:
            return int(progress_payload.get("stalled_metric_cycles", 0) or 0) >= 3
        except (TypeError, ValueError):
            return False

    def _roadmap_pivot_mode(self, progress_payload: Dict[str, Any]) -> bool:
        """Detect when accepted micro-coverage patches should yield to roadmap work."""

        try:
            stalled_metric_cycles = int(progress_payload.get("stalled_metric_cycles", 0) or 0)
        except (TypeError, ValueError):
            stalled_metric_cycles = 0
        summaries = progress_payload.get("accepted_change_summaries") or []
        if len(summaries) < 4:
            return False
        recent_text = " ".join(
            str(item.get("summary") or "") + " " + str(item.get("focus_area") or "")
            for item in summaries[-8:]
            if isinstance(item, Mapping)
        ).lower()
        phase8_terms = ("encoder", "decoder", "reconstruction", "prover syntax", "prover_syntax")
        if any(term in recent_text for term in phase8_terms):
            return False
        micro_terms = ("procedural", "trigger", "export coverage", "proof prerequisite")
        micro_signal_count = sum(1 for term in micro_terms if term in recent_text)
        if stalled_metric_cycles >= 40 and micro_signal_count >= 2:
            return True
        try:
            current_score = float(progress_payload.get("current_score") or 0.0)
        except (TypeError, ValueError):
            current_score = 0.0
        return current_score >= 0.97 and micro_signal_count >= 3

    def _irreducible_repair_blockers(self, evaluation: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Return repair details that should remain blocked without source evidence."""

        details = evaluation.get("repair_required_details")
        if not isinstance(details, list) or not details:
            return []

        blockers: List[Dict[str, Any]] = []
        for detail in details:
            if not isinstance(detail, Mapping):
                return []
            warnings = {str(item) for item in detail.get("parser_warnings") or []}
            text = str(detail.get("text") or detail.get("source_text") or "").strip()
            if "cross_reference_requires_resolution" not in warnings:
                return []
            if not re.search(r"\bsection\s+[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*\b", text, re.IGNORECASE):
                return []
            llm_repair = detail.get("llm_repair")
            deterministic_resolution = (
                llm_repair.get("deterministic_resolution")
                if isinstance(llm_repair, Mapping)
                else {}
            )
            if deterministic_resolution:
                return []
            blockers.append(
                {
                    "sample_id": detail.get("sample_id", ""),
                    "source_id": detail.get("source_id", ""),
                    "parser_warnings": sorted(warnings),
                    "text": text,
                    "reason": "numbered reference lacks exact same-document evidence and must remain active repair",
                }
            )
        return blockers

    def _recent_cycle_history(self, *, limit: int = 3) -> List[Dict[str, Any]]:
        cycles_dir = self.daemon_config.resolved_output_dir() / "cycles"
        if not cycles_dir.exists():
            return []
        epoch_started_at = self._goal_epoch_started_at()
        summaries: List[Dict[str, Any]] = []
        for summary_path in sorted(cycles_dir.glob("cycle_*/cycle_summary.json"), reverse=True):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if epoch_started_at and not _cycle_in_epoch(summary, epoch_started_at):
                continue
            proposal_path = Path(str(summary.get("proposal_path") or ""))
            proposal_summary = ""
            proposal_requirements: List[str] = []
            if proposal_path.is_file():
                try:
                    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
                    proposal_summary = str(proposal.get("summary") or "")
                    proposal_requirements = [
                        str(item) for item in proposal.get("requirements_addressed") or []
                    ]
                except (OSError, json.JSONDecodeError):
                    pass
            tests = dict(summary.get("tests") or {})
            tests_stdout = str(tests.get("stdout") or "")
            test_failure_summary = _summarize_test_failure(tests_stdout)
            post_apply_validation = dict(summary.get("post_apply_validation") or {})
            validation_failure_summary = _summarize_post_apply_validation_failure(post_apply_validation)
            candidate_validation_failure = _latest_candidate_validation_failure(
                summary.get("proposal_attempts") or []
            )
            patch_check = dict(summary.get("patch_check") or {})
            apply_result = dict(summary.get("apply_result") or {})
            metric_progress = dict(
                apply_result.get("metric_progress")
                or (summary.get("retained_change") or {}).get("metric_progress")
                or {}
            )
            proposal_quality = dict(summary.get("proposal_quality") or {})
            summaries.append(
                {
                    "cycle_index": summary.get("cycle_index"),
                    "score": summary.get("score"),
                    "feedback": summary.get("feedback"),
                    "proposal_summary": proposal_summary,
                    "proposal_requirements": proposal_requirements[:6],
                    "patch_valid": patch_check.get("valid"),
                    "patch_failure_tail": str(patch_check.get("stderr") or "")[-4000:]
                    if not patch_check.get("valid")
                    else "",
                    "proposal_quality_valid": proposal_quality.get("valid"),
                    "proposal_quality_reasons": proposal_quality.get("reasons", []),
                    "apply_reason": apply_result.get("reason"),
                    "metric_progress": metric_progress,
                    "changed_files": summary.get("changed_files", []),
                    "applied": apply_result.get("applied"),
                    "rolled_back": apply_result.get("rolled_back", False),
                    "tests_valid": tests.get("valid"),
                    "post_apply_validation_valid": post_apply_validation.get("valid"),
                    "validation_failure_summary": validation_failure_summary,
                    "validation_failure_tail": validation_failure_summary.get("failure_head", ""),
                    "candidate_validation_valid": candidate_validation_failure.get("valid"),
                    "candidate_validation_failure_summary": candidate_validation_failure.get("summary", {}),
                    "candidate_validation_failure_reasons": candidate_validation_failure.get("reasons", []),
                    "candidate_validation_failure_attempt": candidate_validation_failure.get("attempt"),
                    "test_failure_summary": test_failure_summary if not tests.get("valid") else {},
                    "test_failure_tail": tests_stdout[-4000:] if not tests.get("valid") else "",
                }
            )
            if len(summaries) >= limit:
                break
        return summaries

    def _goal_epoch_started_at(self) -> str:
        current_run_path = self.daemon_config.resolved_output_dir() / "current_run.json"
        try:
            current_run = json.loads(current_run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(current_run.get("started_at") or "")

    def _patch_stability_mode(self, recent_cycle_history: Sequence[Dict[str, Any]]) -> bool:
        failures = [
            item
            for item in recent_cycle_history
            if item.get("patch_valid") is False
            and str(item.get("apply_reason") or "").startswith("patch_check_failed")
        ]
        return len(failures) >= 3

    def _recent_failed_patch_files(self, recent_cycle_history: Sequence[Dict[str, Any]]) -> List[str]:
        files: List[str] = []
        for item in recent_cycle_history:
            if item.get("patch_valid") is not False:
                continue
            for path in item.get("changed_files") or []:
                text = str(path)
                if text and text not in files:
                    files.append(text)
        return files[:8]

    def _recent_test_failures(self, recent_cycle_history: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        failures: List[Dict[str, Any]] = []
        for item in recent_cycle_history:
            validation_failed = item.get("post_apply_validation_valid") is False
            candidate_validation_failed = item.get("candidate_validation_valid") is False
            tests_failed = item.get("tests_valid") is False
            if not tests_failed and not validation_failed and not candidate_validation_failed:
                continue
            summary = dict(item.get("test_failure_summary") or {})
            if not _failure_summary_has_content(summary):
                summary = _summarize_test_failure(str(item.get("test_failure_tail") or ""))
            if not _failure_summary_has_content(summary) and validation_failed:
                summary = dict(item.get("validation_failure_summary") or {})
            if not _failure_summary_has_content(summary) and candidate_validation_failed:
                summary = dict(item.get("candidate_validation_failure_summary") or {})
            failures.append(
                {
                    "cycle_index": item.get("cycle_index"),
                    "changed_files": item.get("changed_files", []),
                    "rolled_back": item.get("rolled_back", False),
                    "failure_phase": (
                        "post_apply_validation"
                        if validation_failed
                        else "candidate_post_apply_validation"
                        if candidate_validation_failed
                        else "tests"
                    ),
                    "candidate_attempt": item.get("candidate_validation_failure_attempt"),
                    "failed_tests": summary.get("failed_tests", [])[:12],
                    "exception_types": summary.get("exception_types", [])[:8],
                    "failure_head": summary.get("failure_head", ""),
                    "candidate_validation_reasons": item.get("candidate_validation_failure_reasons", []),
                }
            )
        return failures[:5]

    def _recent_test_failed_files(self, recent_test_failures: Sequence[Dict[str, Any]]) -> List[str]:
        files: List[str] = []
        for item in recent_test_failures:
            for path in item.get("changed_files") or []:
                text = str(path)
                if text and text not in files:
                    files.append(text)
        return files[:8]

    def _recent_metric_stall_failures(self, recent_cycle_history: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        failures: List[Dict[str, Any]] = []
        for item in recent_cycle_history:
            if item.get("apply_reason") != "metric_stall_no_metric_progress":
                continue
            metric_progress = dict(item.get("metric_progress") or {})
            failures.append(
                {
                    "cycle_index": item.get("cycle_index"),
                    "changed_files": item.get("changed_files", []),
                    "proposal_summary": item.get("proposal_summary", ""),
                    "expected_metric_gain": metric_progress.get("expected_metric_gain", {}),
                    "pre_metrics": metric_progress.get("pre_metrics", {}),
                    "post_metrics": metric_progress.get("post_metrics", {}),
                    "moved_expected_metrics": metric_progress.get("moved_expected_metrics", {}),
                    "score_delta": metric_progress.get("score_delta"),
                    "feedback_reduced": metric_progress.get("feedback_reduced"),
                    "reasons": metric_progress.get("reasons", []),
                }
            )
        return failures[:5]

    def _recent_metric_stall_failed_files(
        self,
        recent_metric_stall_failures: Sequence[Dict[str, Any]],
    ) -> List[str]:
        files: List[str] = []
        for item in recent_metric_stall_failures:
            for path in item.get("changed_files") or []:
                text = str(path)
                if text and text not in files:
                    files.append(text)
        return files[:8]

    def check_patch(self, unified_diff: str) -> Dict[str, Any]:
        if not unified_diff.strip():
            return {"valid": False, "returncode": 1, "stdout": "", "stderr": "empty unified diff"}
        return _run_command(
            ["git", "apply", "--check", "--recount", "-"],
            cwd=self.daemon_config.repo_root,
            input_text=unified_diff,
            timeout=30,
        )

    def apply_patch(self, unified_diff: str) -> Dict[str, Any]:
        check = self.check_patch(unified_diff)
        if not check["valid"]:
            return {"applied": False, "check": check, "apply": None}
        apply_result = _run_command(
            ["git", "apply", "--recount", "-"],
            cwd=self.daemon_config.repo_root,
            input_text=unified_diff,
            timeout=30,
        )
        return {"applied": bool(apply_result["valid"]), "check": check, "apply": apply_result}

    def run_tests(self) -> Dict[str, Any]:
        if not self.daemon_config.run_tests:
            return {"valid": True, "skipped": True, "command": list(self.daemon_config.test_command)}
        timeout = self.effective_test_timeout_seconds()
        result = _run_command(
            list(self.daemon_config.test_command),
            cwd=self.daemon_config.repo_root,
            timeout=timeout,
        )
        result["timeout_seconds"] = timeout
        return result

    def effective_test_timeout_seconds(self) -> int:
        """Scale full-suite validation timeout as the daemon adds tests."""

        configured_timeout = max(1, int(self.daemon_config.test_timeout_seconds))
        recent_durations = self._recent_test_durations(limit=8)
        if not recent_durations:
            return configured_timeout
        observed_timeout = int(max(recent_durations) * 2) + 60
        return min(3600, max(configured_timeout, observed_timeout))

    def _recent_test_durations(self, *, limit: int) -> List[float]:
        cycles_dir = self.daemon_config.resolved_output_dir() / "cycles"
        if not cycles_dir.exists():
            return []
        durations: List[float] = []
        for summary_path in sorted(cycles_dir.glob("cycle_*/cycle_summary.json"), reverse=True):
            if len(durations) >= limit:
                break
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            tests = payload.get("tests")
            if not isinstance(tests, dict) or tests.get("skipped"):
                continue
            duration = _as_float(tests.get("duration_seconds"))
            if duration and duration > 0:
                durations.append(duration)
        return durations


class LegalParserOptimizerDaemon:
    """Persistent bounded daemon around :class:`LegalParserParityOptimizer`."""

    def __init__(
        self,
        config: Optional[LegalParserDaemonConfig] = None,
        optimizer: Optional[LegalParserParityOptimizer] = None,
    ) -> None:
        self.config = config or LegalParserDaemonConfig()
        self.config.repo_root = self.config.repo_root.resolve()
        self.output_dir = self.config.resolved_output_dir()
        self.cycles_dir = self.output_dir / "cycles"
        self.cycles_dir.mkdir(parents=True, exist_ok=True)
        self.latest_file = self.output_dir / "latest_summary.json"
        self.state_file = self.output_dir / "daemon_state.json"
        self.status_file = self.output_dir / "current_status.json"
        self.optimizer = optimizer or LegalParserParityOptimizer(daemon_config=self.config)
        self._state = self._load_state()
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_started_at = _utc_now()
        self.run_baseline_head = self._current_head()
        self._status_lock = threading.Lock()
        self._status_payload: Dict[str, Any] = {}
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._write_run_manifest()
        self._sync_progress_from_existing_cycles()

    async def run(self) -> Dict[str, Any]:
        summaries: List[Dict[str, Any]] = []
        cycles_executed = 0
        self._start_heartbeat()
        try:
            while self.config.max_cycles <= 0 or cycles_executed < self.config.max_cycles:
                cycle_index = int(self._state.get("cycle_index", 0)) + 1
                try:
                    cycle = self.run_cycle(cycle_index=cycle_index)
                except KeyboardInterrupt:
                    raise
                except BaseException as exc:
                    cycle = self._record_cycle_exception(cycle_index=cycle_index, exc=exc)
                summaries.append(cycle)
                cycles_executed += 1
                if cycle.get("status") == "cycle_error":
                    await asyncio.sleep(max(0.0, float(self.config.error_backoff_seconds)))
                    continue
                if cycle.get("metrics", {}).get("parity_score", 0.0) >= self.config.target_score:
                    break
                if self.config.max_cycles > 0 and cycles_executed >= self.config.max_cycles:
                    break
                await asyncio.sleep(max(0.0, float(self.config.cycle_interval_seconds)))

            summary = {
                "status": "success",
                "output_dir": str(self.output_dir),
                "cycles_executed": cycles_executed,
                "latest_cycle": summaries[-1] if summaries else None,
            }
            self.latest_file.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            return summary
        finally:
            self._stop_heartbeat()

    def run_cycle(self, *, cycle_index: int) -> Dict[str, Any]:
        started = _utc_now()
        cycle_dir = self.cycles_dir / f"cycle_{cycle_index:04d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        self._write_cycle_started(cycle_dir=cycle_dir, cycle_index=cycle_index, started=started)
        self._write_current_status(
            status="running",
            phase="evaluating_parser",
            cycle_index=cycle_index,
            cycle_dir=cycle_dir,
            started_at=started,
        )

        context = OptimizationContext(
            session_id=f"legal-parser-daemon-{cycle_index:04d}",
            input_data={},
            domain="legal_parser",
            metadata={"cycle_index": cycle_index},
        )
        evaluation = self.optimizer.generate({}, context)
        score, feedback = self.optimizer.critique(evaluation, context)
        proposal_attempts: List[Dict[str, Any]] = []
        proposal = LegalParserCycleProposal(summary="llm_router proposal failed")
        max_attempts = max(1, int(self.config.llm_proposal_attempts))
        attempt_feedback = list(feedback)
        patch_stability_mode = self._patch_stability_mode()
        metric_stall_mode = self._metric_stall_mode()
        roadmap_pivot_mode = self._roadmap_pivot_mode()
        irreducible_residual_mode = bool(
            self.optimizer._irreducible_repair_blockers(evaluation)
            if isinstance(self.optimizer, LegalParserParityOptimizer)
            else []
        )
        test_failure_recovery_mode = self._test_failure_recovery_mode()
        metric_no_progress_recovery_mode = self._metric_no_progress_recovery_mode()
        repair_phase_feedback = self._repair_phase_feedback()
        if repair_phase_feedback:
            attempt_feedback = list(feedback) + repair_phase_feedback
            test_failure_recovery_mode = True
        slice_scale_contract = self._slice_scale_contract(
            patch_stability_mode=patch_stability_mode,
            metric_stall_mode=metric_stall_mode,
            roadmap_pivot_mode=roadmap_pivot_mode,
            test_failure_recovery_mode=test_failure_recovery_mode,
            metric_no_progress_recovery_mode=metric_no_progress_recovery_mode,
        )
        final_retry_reason = ""
        for attempt_index in range(1, max_attempts + 1):
            context.metadata["proposal_attempt"] = attempt_index
            self._write_current_status(
                status="running",
                phase="repairing_failed_patch" if repair_phase_feedback else "requesting_llm_patch",
                cycle_index=cycle_index,
                cycle_dir=cycle_dir,
                started_at=started,
                score=score,
                feedback=attempt_feedback,
                repair_phase_feedback=repair_phase_feedback,
                proposal_attempt=attempt_index,
                proposal_attempts=max_attempts,
                patch_stability_mode=patch_stability_mode,
                metric_stall_mode=metric_stall_mode,
                roadmap_pivot_mode=roadmap_pivot_mode,
                irreducible_residual_mode=irreducible_residual_mode,
                test_failure_recovery_mode=test_failure_recovery_mode,
                metric_no_progress_recovery_mode=metric_no_progress_recovery_mode,
                slice_scale_contract=slice_scale_contract,
            )
            try:
                proposal = self.optimizer.optimize(evaluation, score, attempt_feedback, context)
            except Exception as exc:
                proposal = LegalParserCycleProposal(
                    summary="llm_router proposal failed",
                    raw_response="",
                    parse_error=f"{type(exc).__name__}: {exc}",
                )
            retry_reason = self._proposal_retry_reason(proposal)
            attempt_record: Dict[str, Any] = {
                "attempt": attempt_index,
                "retry_reason": retry_reason,
                "parse_error": proposal.parse_error,
                "summary": proposal.summary,
                "raw_response_chars": len(proposal.raw_response or ""),
                "diff_chars": len(proposal.unified_diff or ""),
            }
            if not retry_reason:
                candidate_patch_check = self.optimizer.check_patch(proposal.unified_diff)
                candidate_changed_files = _paths_from_unified_diff(proposal.unified_diff)
                candidate_patch_stats = _unified_diff_stats(proposal.unified_diff)
                candidate_quality = self._assess_proposal_quality(proposal, candidate_changed_files)
                if patch_stability_mode:
                    candidate_quality = self._enforce_patch_stability_quality(
                        proposal_quality=candidate_quality,
                        changed_files=candidate_changed_files,
                    )
                candidate_quality = self._enforce_material_slice_quality(
                    proposal_quality=candidate_quality,
                    patch_stats=candidate_patch_stats,
                    patch_stability_mode=patch_stability_mode,
                    slice_scale_mode=str(slice_scale_contract.get("mode") or ""),
                    test_failure_recovery_mode=test_failure_recovery_mode,
                    material_slice_gate_active=self._material_slice_gate_active(slice_scale_contract),
                )
                if metric_stall_mode:
                    candidate_quality = self._enforce_metric_stall_quality(
                        proposal=proposal,
                        proposal_quality=candidate_quality,
                        irreducible_residual_mode=irreducible_residual_mode,
                    )
                if metric_no_progress_recovery_mode:
                    candidate_quality = self._enforce_metric_no_progress_recovery_quality(
                        proposal=proposal,
                        proposal_quality=candidate_quality,
                        changed_files=candidate_changed_files,
                    )
                if roadmap_pivot_mode:
                    candidate_quality = self._enforce_roadmap_pivot_quality(
                        proposal=proposal,
                        proposal_quality=candidate_quality,
                        changed_files=candidate_changed_files,
                    )
                candidate_dirty_touched = self._dirty_touched_files(candidate_changed_files)
                if self.config.require_clean_touched_files and candidate_dirty_touched:
                    candidate_quality = {
                        **candidate_quality,
                        "valid": False,
                        "reasons": list(candidate_quality.get("reasons", []))
                        + [
                            "patch touches files with pre-existing uncommitted changes: "
                            + ", ".join(candidate_dirty_touched)
                        ],
                        "dirty_touched_files": candidate_dirty_touched,
                    }
                retry_reason = self._candidate_patch_retry_reason(
                    patch_check=candidate_patch_check,
                    proposal_quality=candidate_quality,
                )
                candidate_validation: Dict[str, Any] = {
                    "valid": True,
                    "skipped": True,
                    "reason": "candidate_not_ready_for_validation",
                }
                candidate_validation_summary: Dict[str, Any] = {}
                if (
                    not retry_reason
                    and self.config.apply_patches
                    and candidate_changed_files
                    and any(path.endswith(".py") for path in candidate_changed_files)
                ):
                    candidate_validation = self._candidate_post_apply_validation(
                        proposal.unified_diff,
                        candidate_changed_files,
                    )
                    if not candidate_validation.get("valid"):
                        retry_reason = self._candidate_validation_retry_reason(candidate_validation)
                        candidate_validation_summary = _summarize_post_apply_validation_failure(
                            candidate_validation
                        )
                attempt_record.update(
                    {
                        "retry_reason": retry_reason,
                        "patch_valid": candidate_patch_check.get("valid"),
                        "patch_stderr_tail": str(candidate_patch_check.get("stderr") or "")[-2000:],
                        "proposal_quality_valid": candidate_quality.get("valid"),
                        "proposal_quality_reasons": candidate_quality.get("reasons", []),
                        "slice_scale_contract": slice_scale_contract,
                        "candidate_validation_valid": candidate_validation.get("valid"),
                        "candidate_validation_reasons": candidate_validation.get("reasons", []),
                        "candidate_validation_summary": candidate_validation_summary,
                        "changed_files": candidate_changed_files,
                    }
                )
            proposal_attempts.append(attempt_record)
            final_retry_reason = retry_reason
            if not retry_reason:
                break
            if attempt_index < max_attempts:
                retry_instruction = (
                    " Regenerate a unified diff against the exact current relevant_file_snapshots; "
                    "do not reuse stale hunk context."
                )
                if irreducible_residual_mode:
                    retry_instruction += (
                        " The residual repair-required gap is protected; pivot away from clearing "
                        "numbered references and propose deterministic_coverage, parser_capability, "
                        "or coverage_expansion work instead."
                    )
                if roadmap_pivot_mode:
                    retry_instruction += (
                        " Roadmap pivot mode is active; propose Phase 8 encoder/decoder "
                        "reconstruction or local theorem-prover syntax validation work, not another "
                        "procedural trigger/export synonym."
                    )
                if "material_slice_too_small" in retry_reason:
                    retry_instruction += (
                        " Enlarge the slice: cover the slice_scale_contract family with 3+ related "
                        "legal constructions and 6-10 focused assertions, while preserving clean hunks."
                    )
                attempt_feedback = list(feedback) + repair_phase_feedback + [
                    (
                        f"previous proposal attempt {attempt_index} was rejected before apply: "
                        f"{retry_reason}.{retry_instruction}"
                    )
                ]
                self._write_current_status(
                    status="running",
                    phase="retrying_llm_patch",
                    cycle_index=cycle_index,
                    cycle_dir=cycle_dir,
                    started_at=started,
                    proposal_attempt=attempt_index,
                    retry_reason=retry_reason,
                    repair_phase_feedback=repair_phase_feedback,
                    last_parse_error=proposal.parse_error,
                )

        proposal_path = cycle_dir / "proposal.json"
        proposal_path.write_text(json.dumps(asdict(proposal), indent=2, default=str), encoding="utf-8")
        patch_path = cycle_dir / "proposal.patch"
        patch_path.write_text(proposal.unified_diff, encoding="utf-8")
        self._write_current_status(
            status="running",
            phase="checking_patch",
            cycle_index=cycle_index,
            cycle_dir=cycle_dir,
            started_at=started,
            proposal_path=proposal_path,
            patch_path=patch_path,
        )

        patch_check = self.optimizer.check_patch(proposal.unified_diff)
        changed_files = _paths_from_unified_diff(proposal.unified_diff)
        patch_stats = _unified_diff_stats(proposal.unified_diff)
        proposal_quality = self._assess_proposal_quality(proposal, changed_files)
        if final_retry_reason.startswith("candidate_post_apply_validation_failed"):
            proposal_quality = {
                **proposal_quality,
                "valid": False,
                "reasons": list(proposal_quality.get("reasons", []))
                + [f"all proposal attempts exhausted; last rejection: {final_retry_reason}"],
            }
        if patch_stability_mode:
            proposal_quality = self._enforce_patch_stability_quality(
                proposal_quality=proposal_quality,
                changed_files=changed_files,
            )
        proposal_quality = self._enforce_material_slice_quality(
            proposal_quality=proposal_quality,
            patch_stats=patch_stats,
            patch_stability_mode=patch_stability_mode,
            slice_scale_mode=str(slice_scale_contract.get("mode") or ""),
            test_failure_recovery_mode=test_failure_recovery_mode,
            material_slice_gate_active=self._material_slice_gate_active(slice_scale_contract),
        )
        if metric_stall_mode:
            proposal_quality = self._enforce_metric_stall_quality(
                proposal=proposal,
                proposal_quality=proposal_quality,
                irreducible_residual_mode=irreducible_residual_mode,
            )
        if metric_no_progress_recovery_mode:
            proposal_quality = self._enforce_metric_no_progress_recovery_quality(
                proposal=proposal,
                proposal_quality=proposal_quality,
                changed_files=changed_files,
            )
        if roadmap_pivot_mode:
            proposal_quality = self._enforce_roadmap_pivot_quality(
                proposal=proposal,
                proposal_quality=proposal_quality,
                changed_files=changed_files,
            )
        dirty_touched_files = self._dirty_touched_files(changed_files)
        if self.config.require_clean_touched_files and dirty_touched_files:
            proposal_quality = {
                **proposal_quality,
                "valid": False,
                "reasons": list(proposal_quality.get("reasons", []))
                + [f"patch touches files with pre-existing uncommitted changes: {', '.join(dirty_touched_files)}"],
                "dirty_touched_files": dirty_touched_files,
            }
        if patch_check.get("valid") and not proposal_quality.get("valid"):
            patch_check = {
                **patch_check,
                "valid": False,
                "quality_valid": False,
                "stderr": str(patch_check.get("stderr") or "")
                + ("\n" if patch_check.get("stderr") else "")
                + "; ".join(proposal_quality.get("reasons", [])),
            }
        if not self.config.apply_patches:
            apply_result: Dict[str, Any] = {"applied": False, "reason": "apply_patches_disabled"}
        elif not patch_check.get("valid"):
            reason = "proposal_quality_failed" if proposal_quality.get("valid") is False else "patch_check_failed"
            apply_result = {"applied": False, "reason": reason, "check": patch_check}
        else:
            apply_result = {"applied": False, "reason": "not_applied_yet"}
        tests_result: Dict[str, Any] = {"valid": True, "skipped": True, "reason": "patch_not_applied"}
        post_apply_validation: Dict[str, Any] = {
            "valid": True,
            "skipped": True,
            "reason": "patch_not_applied",
        }
        post_evaluation: Dict[str, Any] = {}
        retained_change: Dict[str, Any] = {
            "has_retained_changes": False,
            "changed_files": [],
            "reason": "patch_not_applied",
        }
        commit_result: Dict[str, Any] = {"committed": False, "reason": "commit_accepted_patches_disabled"}

        if self.config.apply_patches and patch_check.get("valid"):
            self._write_current_status(
                status="running",
                phase="applying_patch",
                cycle_index=cycle_index,
                cycle_dir=cycle_dir,
                started_at=started,
                changed_files=changed_files,
            )
            pre_apply_diff = self._working_tree_diff()
            pre_apply_files = self._snapshot_patch_paths(proposal.unified_diff)
            apply_result = self.optimizer.apply_patch(proposal.unified_diff)
            if apply_result.get("applied"):
                self._write_current_status(
                    status="running",
                    phase="post_apply_validation",
                    cycle_index=cycle_index,
                    cycle_dir=cycle_dir,
                    started_at=started,
                    changed_files=changed_files,
                )
                post_apply_validation = self._post_apply_validation(changed_files)
                if not post_apply_validation.get("valid"):
                    rollback = self._restore_patch_paths(pre_apply_files)
                    if not rollback.get("valid"):
                        rollback["diff_restore"] = self._restore_working_tree_diff(pre_apply_diff)
                    apply_result["rolled_back"] = True
                    apply_result["rollback"] = rollback
                    apply_result["reason"] = "post_apply_validation_failed"
                    retained_change = {
                        "has_retained_changes": False,
                        "changed_files": [],
                        "reason": "post_apply_validation_failed",
                    }
                    tests_result = {
                        "valid": False,
                        "skipped": True,
                        "reason": "post_apply_validation_failed",
                    }
                else:
                    self._write_current_status(
                        status="running",
                        phase="running_tests",
                        cycle_index=cycle_index,
                        cycle_dir=cycle_dir,
                        started_at=started,
                        changed_files=changed_files,
                    )
                    tests_result = self.optimizer.run_tests()
                    if tests_result.get("valid"):
                        self._write_current_status(
                            status="running",
                            phase="evaluating_retained_change",
                            cycle_index=cycle_index,
                            cycle_dir=cycle_dir,
                            started_at=started,
                            changed_files=changed_files,
                        )
                        post_evaluation = self.optimizer.evaluate_current_parser()
                        metric_progress = self._metric_stall_retention_result(
                            proposal=proposal,
                            evaluation=evaluation,
                            post_evaluation=post_evaluation,
                            metric_stall_mode=metric_stall_mode,
                            irreducible_residual_mode=irreducible_residual_mode,
                        )
                        if not metric_progress.get("valid"):
                            self._write_current_status(
                                status="running",
                                phase="rolling_back_metric_stall_no_progress",
                                cycle_index=cycle_index,
                                cycle_dir=cycle_dir,
                                started_at=started,
                                changed_files=changed_files,
                                metric_progress=metric_progress,
                            )
                            rollback = self._restore_patch_paths(pre_apply_files)
                            if not rollback.get("valid"):
                                rollback["diff_restore"] = self._restore_working_tree_diff(pre_apply_diff)
                            apply_result["rolled_back"] = True
                            apply_result["rollback"] = rollback
                            apply_result["reason"] = "metric_stall_no_metric_progress"
                            apply_result["metric_progress"] = metric_progress
                            retained_change = {
                                "has_retained_changes": False,
                                "changed_files": [],
                                "reason": "metric_stall_no_metric_progress",
                                "metric_progress": metric_progress,
                            }
                            commit_result = {"committed": False, "reason": "metric_stall_no_metric_progress"}
                        else:
                            retained_change = self._retained_change_summary(pre_apply_files)
                            retained_patch_path = cycle_dir / "retained.patch"
                            retained_patch_path.write_text(
                                self._retained_patch_for_paths(pre_apply_files),
                                encoding="utf-8",
                            )
                            retained_change["patch_path"] = str(retained_patch_path)
                            retained_change["metric_progress"] = metric_progress
                            if self.config.commit_accepted_patches and retained_change.get("has_retained_changes"):
                                commit_result = self._commit_retained_change(cycle_index, proposal, retained_change)
                    else:
                        rollback = self._restore_patch_paths(pre_apply_files)
                        if not rollback.get("valid"):
                            rollback["diff_restore"] = self._restore_working_tree_diff(pre_apply_diff)
                        apply_result["rolled_back"] = True
                        apply_result["rollback"] = rollback
                        retained_change = {
                            "has_retained_changes": False,
                            "changed_files": [],
                            "reason": "rolled_back_after_failed_tests",
                        }
        elif self.config.run_tests and not self.config.apply_patches:
            self._write_current_status(
                status="running",
                phase="running_tests_patch_only",
                cycle_index=cycle_index,
                cycle_dir=cycle_dir,
                started_at=started,
            )
            tests_result = self.optimizer.run_tests()

        finished = _utc_now()
        cycle_payload = {
            "cycle_index": cycle_index,
            "started_at": started,
            "finished_at": finished,
            "duration_seconds": round(_parse_utc(finished) - _parse_utc(started), 3),
            "run_id": self.run_id,
            "run_baseline_head": self.run_baseline_head,
            "model_name": self.config.model_name,
            "provider": self.config.provider_label(),
            "apply_patches": self.config.apply_patches,
            "metrics": evaluation.get("metrics", {}),
            "score": score,
            "feedback": feedback,
            "proposal_path": str(proposal_path),
            "patch_path": str(patch_path),
            "changed_files": changed_files,
            "production_files": _production_files(changed_files),
            "test_files": _test_files(changed_files),
            "patch_stats": patch_stats,
            "proposal_attempts": proposal_attempts,
            "proposal_quality": proposal_quality,
            "retained_change": retained_change,
            "commit_result": commit_result,
            "patch_check": patch_check,
            "apply_result": apply_result,
            "post_apply_validation": post_apply_validation,
            "tests": tests_result,
            "post_evaluation": post_evaluation,
        }
        (cycle_dir / "cycle_summary.json").write_text(
            json.dumps(cycle_payload, indent=2, default=str),
            encoding="utf-8",
        )
        self._state.update(
            {
                "cycle_index": cycle_index,
                "latest_score": evaluation.get("metrics", {}).get("parity_score"),
                "latest_cycle_dir": str(cycle_dir),
                "updated_at": finished,
            }
        )
        self.state_file.write_text(json.dumps(self._state, indent=2, default=str), encoding="utf-8")
        self.latest_file.write_text(json.dumps(cycle_payload, indent=2, default=str), encoding="utf-8")
        self._record_progress(cycle_payload)
        self._write_current_status(
            status="running",
            phase="cycle_completed",
            cycle_index=cycle_index,
            cycle_dir=cycle_dir,
            started_at=started,
            finished_at=finished,
            patch_valid=patch_check.get("valid"),
            apply_result=apply_result,
            tests_result=tests_result,
            retained_change=retained_change,
            commit_result=commit_result,
        )
        return cycle_payload

    def _write_cycle_started(self, *, cycle_dir: Path, cycle_index: int, started: str) -> None:
        marker = {
            "status": "running",
            "cycle_index": cycle_index,
            "started_at": started,
            "pid": os.getpid(),
            "model_name": self.config.model_name,
            "provider": self.config.provider_label(),
            "apply_patches": self.config.apply_patches,
        }
        (cycle_dir / "cycle_started.json").write_text(
            json.dumps(marker, indent=2, default=str),
            encoding="utf-8",
        )

    def _write_current_status(
        self,
        *,
        status: str,
        phase: str,
        cycle_index: int,
        cycle_dir: Path,
        started_at: str,
        **details: Any,
    ) -> None:
        now = _utc_now()
        phase_key = self._status_phase_key(phase=phase, cycle_index=cycle_index, details=details)
        previous_payload = dict(self._status_payload)
        previous_phase_started_at = str(previous_payload.get("phase_started_at") or "")
        previous_phase_key = str(previous_payload.get("phase_key") or "")
        phase_started_at = previous_phase_started_at if previous_phase_key == phase_key else now
        dirty_target_status = self._dirty_legal_parser_target_status()
        payload = {
            "status": status,
            "phase": phase,
            "phase_key": phase_key,
            "phase_started_at": phase_started_at,
            "phase_updated_at": now,
            **self._phase_stall_budget(phase),
            "cycle_index": cycle_index,
            "cycle_dir": str(cycle_dir),
            "started_at": started_at,
            "updated_at": now,
            "pid": os.getpid(),
            "run_id": self.run_id,
            "baseline_head": self.run_baseline_head,
            "model_name": self.config.model_name,
            "provider": self.config.provider_label(),
            "apply_patches": self.config.apply_patches,
            "commit_accepted_patches": self.config.commit_accepted_patches,
            "heartbeat_interval_seconds": self.config.heartbeat_interval_seconds,
            "dirty_legal_parser_targets": dirty_target_status["paths"],
            "dirty_legal_parser_targets_valid": dirty_target_status["valid"],
            "dirty_legal_parser_targets_error": dirty_target_status["error"],
            "dirty_legal_parser_targets_source": dirty_target_status["source"],
            "dirty_legal_parser_targets_checked_at": dirty_target_status["checked_at"],
            "dirty_legal_parser_targets_fingerprint": dirty_target_status["fingerprint"],
            **{key: _json_safe(value) for key, value in details.items()},
        }
        with self._status_lock:
            self._status_payload = dict(payload)
            self._write_status_file_atomic(payload)

    def _phase_stall_budget(self, phase: str) -> Dict[str, Any]:
        """Return the supervisor-facing stale budget for the current phase."""

        llm_timeout = max(1, int(self.config.llm_timeout_seconds))
        test_timeout = max(1, int(self.config.test_timeout_seconds))
        effective_test_timeout = test_timeout
        if hasattr(self.optimizer, "effective_test_timeout_seconds"):
            effective_test_timeout = max(test_timeout, int(self.optimizer.effective_test_timeout_seconds()))
        heartbeat_interval = max(1, int(float(self.config.heartbeat_interval_seconds) or 1))
        slack = max(60, heartbeat_interval * 3)
        if phase in {"requesting_llm_patch", "retrying_llm_patch", "repairing_failed_patch"}:
            budget = llm_timeout + slack
            reason = "llm_timeout_seconds_plus_heartbeat_slack"
        elif phase in {"running_tests", "running_tests_patch_only"}:
            budget = effective_test_timeout + slack
            reason = "effective_test_timeout_seconds_plus_heartbeat_slack"
        elif phase in {"post_apply_validation", "evaluating_retained_change"}:
            budget = min(max(180, test_timeout), 600) + slack
            reason = "fast_validation_budget_plus_heartbeat_slack"
        else:
            budget = 0
            reason = "supervisor_default_cycle_stall_seconds"
        return {
            "phase_stale_after_seconds": budget,
            "phase_stale_after_reason": reason,
        }

    def _status_phase_key(self, *, phase: str, cycle_index: int, details: Mapping[str, Any]) -> str:
        """Return a stable key for supervisor phase-age accounting."""

        attempt = details.get("proposal_attempt")
        retry_reason = details.get("retry_reason")
        key_parts = [str(cycle_index), phase]
        if attempt is not None:
            key_parts.append(f"attempt={attempt}")
        if retry_reason:
            key_parts.append(f"retry={str(retry_reason)[:80]}")
        return "|".join(key_parts)

    def _write_status_file_atomic(self, payload: Mapping[str, Any]) -> None:
        """Write current status JSON without exposing a truncated file."""

        tmp_path = self.status_file.with_name(
            f".{self.status_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            tmp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            tmp_path.replace(self.status_file)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _start_heartbeat(self) -> None:
        interval = float(self.config.heartbeat_interval_seconds)
        if interval <= 0 or self._heartbeat_thread is not None:
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="legal-parser-daemon-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None:
            thread.join(timeout=2)
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        interval = max(0.1, float(self.config.heartbeat_interval_seconds))
        while not self._heartbeat_stop.wait(interval):
            with self._status_lock:
                if not self._status_payload:
                    continue
                payload = dict(self._status_payload)
                payload["updated_at"] = _utc_now()
                payload["heartbeat_at"] = payload["updated_at"]
                payload["heartbeat_pid"] = os.getpid()
                payload["heartbeat_thread"] = "legal-parser-daemon-heartbeat"
                self._status_payload = payload
                self._write_status_file_atomic(payload)

    def _record_cycle_exception(self, *, cycle_index: int, exc: Exception) -> Dict[str, Any]:
        finished = _utc_now()
        cycle_dir = self.cycles_dir / f"cycle_{cycle_index:04d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        cycle_payload = {
            "status": "cycle_error",
            "cycle_index": cycle_index,
            "started_at": finished,
            "finished_at": finished,
            "duration_seconds": 0.0,
            "run_id": self.run_id,
            "run_baseline_head": self.run_baseline_head,
            "model_name": self.config.model_name,
            "provider": self.config.provider_label(),
            "apply_patches": self.config.apply_patches,
            "metrics": {},
            "score": 0.0,
            "feedback": [f"{type(exc).__name__}: {exc}"],
            "patch_check": {"valid": False, "stderr": "cycle failed before patch check"},
            "apply_result": {"applied": False, "reason": "cycle_exception"},
            "tests": {"valid": False, "skipped": True, "reason": "cycle_exception"},
            "post_evaluation": {},
            "exception": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        }
        (cycle_dir / "cycle_summary.json").write_text(
            json.dumps(cycle_payload, indent=2, default=str),
            encoding="utf-8",
        )
        self._state.update(
            {
                "cycle_index": cycle_index,
                "latest_score": None,
                "latest_cycle_dir": str(cycle_dir),
                "updated_at": finished,
            }
        )
        self.state_file.write_text(json.dumps(self._state, indent=2, default=str), encoding="utf-8")
        self.latest_file.write_text(json.dumps(cycle_payload, indent=2, default=str), encoding="utf-8")
        self._record_progress(cycle_payload)
        self._write_current_status(
            status="running",
            phase="cycle_error_recorded",
            cycle_index=cycle_index,
            cycle_dir=cycle_dir,
            started_at=finished,
            finished_at=finished,
            exception=cycle_payload["exception"],
        )
        return cycle_payload

    def _assess_proposal_quality(
        self,
        proposal: LegalParserCycleProposal,
        changed_files: Sequence[str],
    ) -> Dict[str, Any]:
        reasons: List[str] = []
        production_files = _production_files(changed_files)
        test_files = _test_files(changed_files)
        if proposal.parse_error:
            reasons.append(f"proposal parse_error: {proposal.parse_error}")
        if not proposal.summary.strip():
            reasons.append("proposal summary is empty")
        if not proposal.acceptance_criteria:
            reasons.append("proposal omitted acceptance_criteria")
        if not proposal.unified_diff.strip():
            reasons.append("proposal unified_diff is empty")
        if self.config.require_production_and_tests:
            if not production_files:
                reasons.append("patch must touch at least one production deontic parser/export file")
            if not test_files:
                reasons.append("patch must touch at least one deontic parser test file")
        reasons.extend(self._source_slot_erasure_reasons(proposal))
        return {
            "valid": not reasons,
            "reasons": reasons,
            "declared_changed_files": list(proposal.changed_files),
            "changed_files": list(changed_files),
            "production_files": production_files,
            "test_files": test_files,
        }

    def _source_slot_erasure_reasons(self, proposal: LegalParserCycleProposal) -> List[str]:
        """Reject generated tests that erase source-grounded facts already parsed.

        The optimizer occasionally proposes a useful implementation idea with a
        contradictory test, for example asserting that ``mental_state`` is empty
        for text that explicitly says "knowingly". Catch that before the full
        suite spends a cycle applying and rolling the patch back.
        """

        diff = proposal.unified_diff or ""
        added_lines = [
            line[1:]
            for line in diff.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        added_text = "\n".join(added_lines).lower()
        mental_state_terms = {
            "intentionally",
            "knowingly",
            "recklessly",
            "willfully",
            "purposely",
            "negligently",
        }
        if not any(term in added_text for term in mental_state_terms):
            return []
        empty_mental_state_assertion = re.compile(
            r"assert\s+.*(?:mental_state|\\[\"mental_state\"\\]|\\['mental_state'\\]).*==\s*['\"]{2}"
        )
        if any(empty_mental_state_assertion.search(line) for line in added_lines):
            return [
                "tests must not assert empty mental_state for source text containing explicit mens rea"
            ]
        return []

    def _patch_stability_mode(self) -> bool:
        if not isinstance(self.optimizer, LegalParserParityOptimizer):
            return False
        history = self.optimizer._recent_cycle_history(limit=5)
        return self.optimizer._patch_stability_mode(history)

    def _metric_stall_mode(self) -> bool:
        if not isinstance(self.optimizer, LegalParserParityOptimizer):
            return False
        return self.optimizer._metric_stall_mode(self.optimizer._progress_snapshot())

    def _roadmap_pivot_mode(self) -> bool:
        if not isinstance(self.optimizer, LegalParserParityOptimizer):
            return False
        return self.optimizer._roadmap_pivot_mode(self.optimizer._progress_snapshot())

    def _test_failure_recovery_mode(self) -> bool:
        if not isinstance(self.optimizer, LegalParserParityOptimizer):
            return False
        history = self.optimizer._recent_cycle_history(limit=5)
        return bool(self.optimizer._recent_test_failures(history))

    def _repair_phase_feedback(self) -> List[str]:
        if not isinstance(self.optimizer, LegalParserParityOptimizer):
            return []
        history = self.optimizer._recent_cycle_history(limit=5)
        failures = self.optimizer._recent_test_failures(history)
        if not failures:
            return []
        feedback: List[str] = [
            "repair_phase: previous retained candidate failed validation/tests; repair the named failure before adding new behavior."
        ]
        for failure in failures[:3]:
            phase = str(failure.get("failure_phase") or "tests")
            files = ", ".join(str(path) for path in failure.get("changed_files") or []) or "unknown files"
            failed_tests = ", ".join(str(item) for item in failure.get("failed_tests") or [])
            exception_types = ", ".join(str(item) for item in failure.get("exception_types") or [])
            head = " ".join(str(failure.get("failure_head") or "").split())
            parts = [
                f"cycle={failure.get('cycle_index')}",
                f"phase={phase}",
                f"files={files}",
            ]
            if failed_tests:
                parts.append(f"failed_tests={failed_tests}")
            if exception_types:
                parts.append(f"exceptions={exception_types}")
            if head:
                parts.append(f"failure_head={head[:1200]}")
            feedback.append("repair_phase_failure: " + "; ".join(parts))
        return feedback

    def _metric_no_progress_recovery_mode(self) -> bool:
        if not isinstance(self.optimizer, LegalParserParityOptimizer):
            return False
        history = self.optimizer._recent_cycle_history(limit=5)
        return bool(self.optimizer._recent_metric_stall_failures(history))

    def _slice_scale_contract(
        self,
        *,
        patch_stability_mode: bool,
        metric_stall_mode: bool,
        roadmap_pivot_mode: bool,
        test_failure_recovery_mode: bool,
        metric_no_progress_recovery_mode: bool,
    ) -> Dict[str, Any]:
        if not isinstance(self.optimizer, LegalParserParityOptimizer):
            return {"mode": "standard_material_slice"}
        return self.optimizer._slice_scale_contract(
            progress_payload=self.optimizer._progress_snapshot(),
            patch_stability_mode=patch_stability_mode,
            metric_stall_mode=metric_stall_mode,
            roadmap_pivot_mode=roadmap_pivot_mode,
            test_failure_recovery_mode=test_failure_recovery_mode,
            metric_no_progress_recovery_mode=metric_no_progress_recovery_mode,
        )

    def _enforce_patch_stability_quality(
        self,
        *,
        proposal_quality: Dict[str, Any],
        changed_files: Sequence[str],
    ) -> Dict[str, Any]:
        if len(changed_files) <= 2:
            return proposal_quality
        return {
            **proposal_quality,
            "valid": False,
            "reasons": list(proposal_quality.get("reasons", []))
            + [
                "patch stability mode allows at most two changed files after repeated patch-check failures"
            ],
            "patch_stability_mode": True,
        }

    def _enforce_material_slice_quality(
        self,
        *,
        proposal_quality: Dict[str, Any],
        patch_stats: Mapping[str, Any],
        patch_stability_mode: bool,
        slice_scale_mode: str,
        test_failure_recovery_mode: bool,
        material_slice_gate_active: bool,
    ) -> Dict[str, Any]:
        if not material_slice_gate_active:
            return proposal_quality
        if test_failure_recovery_mode and slice_scale_mode == "repair_first":
            return proposal_quality
        try:
            insertions = int(patch_stats.get("insertions", 0) or 0)
            deletions = int(patch_stats.get("deletions", 0) or 0)
        except (TypeError, ValueError):
            insertions = 0
            deletions = 0
        changed_files = list(patch_stats.get("changed_files") or [])
        if not changed_files:
            return proposal_quality
        if slice_scale_mode == "repair_with_material_followthrough":
            minimum_insertions = 24
        elif patch_stability_mode:
            minimum_insertions = 18
        else:
            minimum_insertions = 30
        if insertions >= minimum_insertions and insertions + deletions >= minimum_insertions:
            return proposal_quality
        return {
            **proposal_quality,
            "valid": False,
            "reasons": list(proposal_quality.get("reasons", []))
            + [
                (
                    "material_slice_too_small: autonomous parser progress must cover a family-sized "
                    f"change; got {insertions} insertions/{deletions} deletions across "
                    f"{len(changed_files)} file(s), expected at least {minimum_insertions} insertions "
                    "with 3+ related legal constructions and focused tests"
                )
            ],
            "material_slice_quality": {
                "valid": False,
                "minimum_insertions": minimum_insertions,
                "insertions": insertions,
                "deletions": deletions,
                "changed_files": changed_files,
                "patch_stability_mode": patch_stability_mode,
            },
        }

    def _material_slice_gate_active(self, slice_scale_contract: Mapping[str, Any]) -> bool:
        return str(slice_scale_contract.get("mode") or "") in {
            "expanded_slice",
            "patch_stability_family",
            "phase8_cross_stack_slice",
            "repair_with_material_followthrough",
        }

    def _enforce_metric_stall_quality(
        self,
        *,
        proposal: LegalParserCycleProposal,
        proposal_quality: Dict[str, Any],
        irreducible_residual_mode: bool = False,
    ) -> Dict[str, Any]:
        gain_keys = {str(key) for key in (proposal.expected_metric_gain or {})}
        accepted_metric_keys = {
            "parity_score",
            "repair_required_count",
            "repair_required_rate",
            "proof_ready_rate",
            "cross_reference_resolution_rate",
            "formula_error_rate",
            "parsed_rate",
            "schema_valid_rate",
        }
        if irreducible_residual_mode:
            accepted_metric_keys = accepted_metric_keys | {
                "coverage_expansion",
                "deterministic_coverage",
                "parser_capability",
                "encoder_decoder_reconstruction",
                "prover_syntax_coverage",
                "reconstruction_quality",
            }
        if gain_keys & accepted_metric_keys:
            return proposal_quality
        return {
            **proposal_quality,
            "valid": False,
            "reasons": list(proposal_quality.get("reasons", []))
            + [
                (
                    "irreducible residual mode requires expected_metric_gain to name "
                    "deterministic_coverage, parser_capability, coverage_expansion, or a real parser metric"
                    if irreducible_residual_mode
                    else "metric stall mode requires expected_metric_gain to name a real parser metric"
                )
            ],
            "metric_stall_mode": True,
            "irreducible_residual_mode": irreducible_residual_mode,
        }

    def _enforce_metric_no_progress_recovery_quality(
        self,
        *,
        proposal: LegalParserCycleProposal,
        proposal_quality: Dict[str, Any],
        changed_files: Sequence[str],
    ) -> Dict[str, Any]:
        production_files = _production_files(changed_files)
        non_exports_production = [
            path
            for path in production_files
            if path != "ipfs_datasets_py/logic/deontic/exports.py"
        ]
        if non_exports_production:
            invariant_reasons = self._protected_reference_repair_invariant_reasons(proposal)
            if not invariant_reasons:
                return proposal_quality
            return {
                **proposal_quality,
                "valid": False,
                "reasons": list(proposal_quality.get("reasons", [])) + invariant_reasons,
                "metric_no_progress_recovery_mode": True,
            }
        return {
            **proposal_quality,
            "valid": False,
            "reasons": list(proposal_quality.get("reasons", []))
            + [
                "metric no-progress recovery requires a non-exports production parser, IR, formula, or converter change"
            ],
            "metric_no_progress_recovery_mode": True,
        }

    def _enforce_roadmap_pivot_quality(
        self,
        *,
        proposal: LegalParserCycleProposal,
        proposal_quality: Dict[str, Any],
        changed_files: Sequence[str],
    ) -> Dict[str, Any]:
        proposal_text = " ".join(
            [
                proposal.summary or "",
                " ".join(proposal.requirements_addressed or []),
                " ".join(proposal.acceptance_criteria or []),
                " ".join(str(key) for key in (proposal.expected_metric_gain or {}).keys()),
                " ".join(str(value) for value in (proposal.expected_metric_gain or {}).values()),
                " ".join(changed_files),
            ]
        ).lower()
        phase8_terms = (
            "encoder",
            "decoder",
            "reconstruction",
            "round-trip",
            "roundtrip",
            "prover_syntax",
            "prover syntax",
            "theorem-prover",
            "frame logic",
            "deontic cec",
            "deontic cognitive event calculus",
            "deontic temporal first-order logic",
        )
        if any(term in proposal_text for term in phase8_terms):
            return proposal_quality
        procedural_micro_terms = (
            "procedural trigger",
            "triggered_by_",
            "export coverage",
            "proof prerequisite",
            "procedure.event_relations",
            "timeline coverage",
        )
        if any(term in proposal_text for term in procedural_micro_terms):
            reason = (
                "roadmap pivot mode rejects additional procedural-trigger/export synonym patches; "
                "implement Phase 8 encoder/decoder reconstruction or local theorem-prover syntax validation"
            )
        else:
            reason = (
                "roadmap pivot mode requires a Phase 8 encoder/decoder reconstruction or "
                "local theorem-prover syntax validation slice"
            )
        return {
            **proposal_quality,
            "valid": False,
            "reasons": list(proposal_quality.get("reasons", [])) + [reason],
            "roadmap_pivot_mode": True,
        }

    def _protected_reference_repair_invariant_reasons(
        self,
        proposal: LegalParserCycleProposal,
    ) -> List[str]:
        text = " ".join(
            [
                proposal.summary,
                proposal.focus_area,
                " ".join(proposal.requirements_addressed),
                " ".join(proposal.acceptance_criteria),
            ]
        ).lower()
        if not text:
            return []
        clear_terms = (
            "clear",
            "reclassif",
            "not active repair",
            "inactive repair",
            "stop counting",
            "reduce repair",
            "repair_required_count",
            "repair-required metric",
            "validation blocker rather than active",
            "not llm repair",
        )
        protected_terms = (
            "unresolved",
            "absent",
            "mismatched",
            "external",
            "partial",
            "numbered reference",
            "numbered-section",
            "numbered section",
            "cross_reference repair",
            "reference-only exception",
        )
        exact_evidence_terms = (
            "exact same-document",
            "same-document evidence",
            "target section exists",
            "matching section context",
        )
        if not any(term in text for term in clear_terms):
            return []
        if not any(term in text for term in protected_terms):
            return []
        if any(term in text for term in exact_evidence_terms) and not any(
            term in text for term in ("unresolved", "absent", "mismatched", "external", "partial")
        ):
            return []
        return [
            "metric no-progress recovery cannot clear active repair for unresolved, absent, mismatched, partial, or external numbered references"
        ]

    def _metric_stall_retention_result(
        self,
        *,
        proposal: LegalParserCycleProposal,
        evaluation: Dict[str, Any],
        post_evaluation: Dict[str, Any],
        metric_stall_mode: bool,
        irreducible_residual_mode: bool = False,
    ) -> Dict[str, Any]:
        pre_metrics = dict(evaluation.get("metrics") or {})
        post_metrics = dict((post_evaluation.get("metrics") or {}) if isinstance(post_evaluation, dict) else {})
        result = {
            "valid": True,
            "metric_stall_mode": metric_stall_mode,
            "irreducible_residual_mode": irreducible_residual_mode,
            "expected_metric_gain": dict(proposal.expected_metric_gain or {}),
            "pre_metrics": self._selected_metric_snapshot(pre_metrics),
            "post_metrics": self._selected_metric_snapshot(post_metrics),
            "reasons": [],
        }
        if not metric_stall_mode:
            return result

        moved_metrics = self._moved_expected_metrics(proposal.expected_metric_gain or {}, pre_metrics, post_metrics)
        pre_score = _as_float(pre_metrics.get("parity_score"))
        post_score = _as_float(post_metrics.get("parity_score"))
        score_delta = None if pre_score is None or post_score is None else post_score - pre_score
        feedback_reduced = self._coverage_feedback_reduced(pre_metrics, post_metrics)
        result.update(
            {
                "moved_expected_metrics": moved_metrics,
                "score_delta": score_delta,
                "feedback_reduced": feedback_reduced,
            }
        )
        if moved_metrics or feedback_reduced:
            return result
        if score_delta is not None and score_delta >= self.config.min_score_improvement:
            return result
        if irreducible_residual_mode and self._claims_deterministic_coverage_gain(proposal):
            result["accepted_without_metric_delta"] = True
            result["reasons"] = [
                "accepted tested deterministic coverage work while residual repair-required gap is irreducible"
            ]
            return result

        result["valid"] = False
        result["reasons"] = [
            "metric-stall patch passed tests but did not improve claimed metrics, score, or coverage gaps"
        ]
        return result

    def _claims_deterministic_coverage_gain(self, proposal: LegalParserCycleProposal) -> bool:
        gain_keys = {str(key) for key in (proposal.expected_metric_gain or {})}
        return bool(gain_keys & {"coverage_expansion", "deterministic_coverage", "parser_capability"})

    def _selected_metric_snapshot(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "parity_score",
            "repair_required_count",
            "repair_required_rate",
            "proof_ready_rate",
            "cross_reference_resolution_rate",
            "formula_error_rate",
            "parsed_rate",
            "schema_valid_rate",
            "coverage_gaps",
        ]
        return {key: metrics.get(key) for key in keys if key in metrics}

    def _moved_expected_metrics(
        self,
        expected_metric_gain: Dict[str, Any],
        pre_metrics: Dict[str, Any],
        post_metrics: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        moved: Dict[str, Dict[str, Any]] = {}
        lower_is_better = {"repair_required_count", "repair_required_rate", "formula_error_rate"}
        for key, expected in expected_metric_gain.items():
            metric = str(key)
            before = _as_float(pre_metrics.get(metric))
            after = _as_float(post_metrics.get(metric))
            if before is None or after is None:
                continue
            expected_value = _as_float(expected)
            if expected_value is not None and expected_value < 0:
                improved = after < before
            elif expected_value is not None and expected_value > 0:
                improved = after > before
            elif metric in lower_is_better:
                improved = after < before
            else:
                improved = after > before
            if improved:
                moved[metric] = {"before": before, "after": after, "expected_gain": expected}
        return moved

    def _coverage_feedback_reduced(self, pre_metrics: Dict[str, Any], post_metrics: Dict[str, Any]) -> bool:
        pre_gaps = {str(item) for item in pre_metrics.get("coverage_gaps") or []}
        post_gaps = {str(item) for item in post_metrics.get("coverage_gaps") or []}
        return bool(pre_gaps) and post_gaps < pre_gaps

    def _proposal_retry_reason(self, proposal: LegalParserCycleProposal) -> str:
        if proposal.parse_error:
            return f"parse_error: {proposal.parse_error}"
        if not proposal.raw_response.strip():
            return "empty_llm_response"
        if not proposal.summary.strip():
            return "proposal_summary_empty"
        if not proposal.acceptance_criteria:
            return "proposal_acceptance_criteria_empty"
        if not proposal.unified_diff.strip():
            return "proposal_unified_diff_empty"
        return ""

    def _candidate_patch_retry_reason(
        self,
        *,
        patch_check: Dict[str, Any],
        proposal_quality: Dict[str, Any],
    ) -> str:
        if proposal_quality.get("valid") is False:
            reasons = "; ".join(str(item) for item in proposal_quality.get("reasons", [])[:3])
            return f"proposal_quality_failed:{reasons}" if reasons else "proposal_quality_failed"
        if patch_check.get("valid") is False:
            stderr_lines = str(patch_check.get("stderr") or "").strip().splitlines()
            first_line = stderr_lines[0] if stderr_lines else "patch_check_failed"
            return f"patch_check_failed:{first_line}"
        return ""

    def _candidate_post_apply_validation(
        self,
        unified_diff: str,
        changed_files: Sequence[str],
    ) -> Dict[str, Any]:
        pre_apply_diff = self._working_tree_diff()
        pre_apply_files = self._snapshot_patch_paths(unified_diff)
        apply_result = self.optimizer.apply_patch(unified_diff)
        if not apply_result.get("applied"):
            rollback = self._restore_patch_paths(pre_apply_files)
            if not rollback.get("valid"):
                rollback["diff_restore"] = self._restore_working_tree_diff(pre_apply_diff)
            return {
                "valid": False,
                "reason": "candidate_apply_failed",
                "apply": apply_result,
                "rollback": rollback,
                "reasons": ["candidate patch failed to apply during validation"],
            }
        validation = self._post_apply_validation(changed_files)
        rollback = self._restore_patch_paths(pre_apply_files)
        if not rollback.get("valid"):
            rollback["diff_restore"] = self._restore_working_tree_diff(pre_apply_diff)
        return {
            **validation,
            "rollback": rollback,
            "reason": "candidate_post_apply_validation",
        }

    def _candidate_validation_retry_reason(self, validation: Mapping[str, Any]) -> str:
        summary = _summarize_post_apply_validation_failure(validation)
        head = " ".join(str(summary.get("failure_head") or "").split())
        exceptions = ", ".join(str(item) for item in summary.get("exception_types") or [])
        if head:
            return f"candidate_post_apply_validation_failed:{head[:500]}"
        if exceptions:
            return f"candidate_post_apply_validation_failed:{exceptions}"
        reasons = "; ".join(str(item) for item in validation.get("reasons") or [])
        return f"candidate_post_apply_validation_failed:{reasons}" if reasons else "candidate_post_apply_validation_failed"

    def _record_progress(self, cycle_payload: Dict[str, Any]) -> None:
        accepted = _cycle_was_kept(cycle_payload)
        if accepted:
            self._append_accepted_change(cycle_payload)
        progress = self._build_progress_summary(latest_cycle=cycle_payload)
        progress_path = self.output_dir / "progress_summary.json"
        progress_path.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")
        self._write_progress_report(progress)

    def _sync_progress_from_existing_cycles(self) -> None:
        cycles = self._read_cycle_summaries()
        if not cycles:
            return
        ledger_path = self.output_dir / "accepted_changes.jsonl"
        accepted_records = [
            self._accepted_change_record(cycle)
            for cycle in cycles
            if _cycle_was_kept(cycle)
        ]
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            "".join(json.dumps(record, default=str, sort_keys=True) + "\n" for record in accepted_records),
            encoding="utf-8",
        )
        progress = self._build_progress_summary(latest_cycle=cycles[-1])
        (self.output_dir / "progress_summary.json").write_text(
            json.dumps(progress, indent=2, default=str),
            encoding="utf-8",
        )
        self._write_progress_report(progress)

    def _append_accepted_change(self, cycle_payload: Dict[str, Any]) -> None:
        _append_jsonl(self.output_dir / "accepted_changes.jsonl", self._accepted_change_record(cycle_payload))

    def _accepted_change_record(self, cycle_payload: Dict[str, Any]) -> Dict[str, Any]:
        proposal = {}
        proposal_path = Path(str(cycle_payload.get("proposal_path") or ""))
        if proposal_path.is_file():
            try:
                proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                proposal = {}
        return {
            "cycle_index": cycle_payload.get("cycle_index"),
            "finished_at": cycle_payload.get("finished_at"),
            "summary": proposal.get("summary", ""),
            "focus_area": proposal.get("focus_area", ""),
            "requirements_addressed": proposal.get("requirements_addressed", []),
            "acceptance_criteria": proposal.get("acceptance_criteria", []),
            "changed_files": cycle_payload.get("changed_files", []),
            "production_files": cycle_payload.get("production_files", []),
            "test_files": cycle_payload.get("test_files", []),
            "patch_stats": cycle_payload.get("patch_stats", {}),
            "retained_change": cycle_payload.get("retained_change", {}),
            "commit_result": cycle_payload.get("commit_result", {}),
            "pre_score": cycle_payload.get("score"),
            "post_score": (cycle_payload.get("post_evaluation") or {}).get("metrics", {}).get("parity_score"),
            "tests": cycle_payload.get("tests", {}),
        }

    def _read_cycle_summaries(self) -> List[Dict[str, Any]]:
        cycles: List[Dict[str, Any]] = []
        for summary_path in sorted(self.cycles_dir.glob("cycle_*/cycle_summary.json")):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            cycles.append(summary)
        return cycles

    def _build_progress_summary(self, *, latest_cycle: Dict[str, Any]) -> Dict[str, Any]:
        cycles = self._read_cycle_summaries()
        latest_index = latest_cycle.get("cycle_index")
        if latest_index is not None and all(cycle.get("cycle_index") != latest_index for cycle in cycles):
            cycles.append(latest_cycle)
        epoch_started_at = self.run_started_at
        epoch_cycles = [cycle for cycle in cycles if _cycle_in_epoch(cycle, epoch_started_at)]
        if not epoch_cycles:
            epoch_cycles = [latest_cycle]

        accepted_cycles = [cycle for cycle in cycles if _cycle_was_kept(cycle)]
        epoch_accepted_cycles = [cycle for cycle in epoch_cycles if _cycle_was_kept(cycle)]
        rolled_back = [
            cycle for cycle in cycles if (cycle.get("apply_result") or {}).get("rolled_back", False)
        ]
        rolled_back_reason_counts: Dict[str, int] = {}
        for cycle in rolled_back:
            reason = _cycle_rejection_reason(cycle)
            rolled_back_reason_counts[reason] = rolled_back_reason_counts.get(reason, 0) + 1
        rejected = [
            cycle
            for cycle in cycles
            if not (cycle.get("patch_check") or {}).get("valid")
            or not (cycle.get("proposal_quality") or {"valid": True}).get("valid", True)
        ]
        epoch_rejected = [
            cycle
            for cycle in epoch_cycles
            if not (cycle.get("patch_check") or {}).get("valid")
            or not (cycle.get("proposal_quality") or {"valid": True}).get("valid", True)
        ]
        first_score = None
        for cycle in epoch_cycles:
            score = cycle.get("score")
            if isinstance(score, (int, float)):
                first_score = float(score)
                break
        current_metrics = latest_cycle.get("metrics", {})
        post_metrics = (latest_cycle.get("post_evaluation") or {}).get("metrics") or {}
        current_score = post_metrics.get("parity_score", current_metrics.get("parity_score"))
        current_feedback = post_metrics.get(
            "coverage_gaps",
            current_metrics.get("coverage_gaps", latest_cycle.get("feedback", [])),
        )

        accepted_summaries: List[Dict[str, Any]] = []
        for cycle in accepted_cycles[-20:]:
            proposal_path = Path(str(cycle.get("proposal_path") or ""))
            proposal_summary = ""
            focus_area = ""
            if proposal_path.is_file():
                try:
                    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
                    proposal_summary = str(proposal.get("summary") or "")
                    focus_area = str(proposal.get("focus_area") or "")
                except (OSError, json.JSONDecodeError):
                    pass
            accepted_summaries.append(
                {
                    "cycle_index": cycle.get("cycle_index"),
                    "summary": proposal_summary,
                    "focus_area": focus_area,
                    "changed_files": cycle.get("changed_files", []),
                }
            )

        recent_rejections = [
            {
                "cycle_index": cycle.get("cycle_index"),
                "reason": _cycle_rejection_reason(cycle),
                "changed_files": cycle.get("changed_files", []),
                "patch_stderr_tail": str((cycle.get("patch_check") or {}).get("stderr") or "")[-1000:],
                "proposal_quality_reasons": (cycle.get("proposal_quality") or {}).get("reasons", []),
                "dirty_touched_files": (cycle.get("proposal_quality") or {}).get("dirty_touched_files", []),
                "latest_candidate_validation_failure": _latest_candidate_validation_failure(
                    cycle.get("proposal_attempts") or []
                ),
            }
            for cycle in epoch_cycles[-10:]
            if not _cycle_was_kept(cycle)
        ]
        candidate_validation_failures = [
            failure
            for failure in (
                item.get("latest_candidate_validation_failure") for item in recent_rejections
            )
            if isinstance(failure, Mapping) and failure.get("valid") is False
        ]
        repeated_rejection_family = _repeated_rejection_family(recent_rejections)
        dirty_rejection_files = _dirty_files_from_rejections(recent_rejections)
        active_dirty_touched_files = self._dirty_touched_files(dirty_rejection_files)

        stalled_metric_cycles = 0
        cycles_since_meaningful_progress = 0
        rolled_back_since_meaningful_progress = 0
        rolled_back_reasons_since_meaningful_progress: Dict[str, int] = {}
        current_score_value = _as_float(current_score)
        for cycle in reversed(epoch_cycles):
            if _cycle_was_kept(cycle):
                break
            cycle_score = _cycle_effective_score(cycle)
            if (
                current_score_value is not None
                and cycle_score is not None
                and abs(cycle_score - current_score_value) <= 1e-9
            ):
                stalled_metric_cycles += 1
            else:
                break
        for cycle in reversed(epoch_cycles):
            if _cycle_was_kept(cycle):
                break
            cycle_score = _cycle_effective_score(cycle)
            if (
                current_score_value is not None
                and cycle_score is not None
                and abs(cycle_score - current_score_value) <= 1e-9
            ):
                cycles_since_meaningful_progress += 1
                apply_result = cycle.get("apply_result") or {}
                if apply_result.get("rolled_back", False):
                    reason = _cycle_rejection_reason(cycle)
                    rolled_back_since_meaningful_progress += 1
                    rolled_back_reasons_since_meaningful_progress[reason] = (
                        rolled_back_reasons_since_meaningful_progress.get(reason, 0) + 1
                    )
            else:
                break
        dirty_target_status = self._dirty_legal_parser_target_status()
        return {
            "updated_at": _utc_now(),
            "total_cycles": len(cycles),
            "goal_epoch_started_at": epoch_started_at,
            "goal_epoch_cycle_count": len(epoch_cycles),
            "latest_cycle_index": latest_cycle.get("cycle_index"),
            "accepted_patch_count": len(accepted_cycles),
            "goal_epoch_accepted_patch_count": len(epoch_accepted_cycles),
            "retained_accepted_patch_count": sum(
                1
                for cycle in accepted_cycles
                if (cycle.get("retained_change") or {"has_retained_changes": True}).get(
                    "has_retained_changes", True
                )
            ),
            "rolled_back_count": len(rolled_back),
            "rolled_back_reason_counts": rolled_back_reason_counts,
            "rolled_back_since_meaningful_progress": rolled_back_since_meaningful_progress,
            "rolled_back_reasons_since_meaningful_progress": rolled_back_reasons_since_meaningful_progress,
            "rejected_patch_count": len(rejected),
            "goal_epoch_rejected_patch_count": len(epoch_rejected),
            "current_score": current_score,
            "initial_score": first_score,
            "score_delta": (
                round(float(current_score) - float(first_score), 6)
                if isinstance(current_score, (int, float)) and isinstance(first_score, float)
                else None
            ),
            "current_feedback": current_feedback,
            "stalled_metric_cycles": stalled_metric_cycles,
            "cycles_since_meaningful_progress": cycles_since_meaningful_progress,
            "meaningful_progress_definition": (
                "retained accepted patch or parser metric score change; retained changes reset "
                "stall accounting even when parity_score is unchanged"
            ),
            "git_retained_work": self._git_retained_work_snapshot(),
            "dirty_legal_parser_targets": dirty_target_status["paths"],
            "dirty_legal_parser_targets_valid": dirty_target_status["valid"],
            "dirty_legal_parser_targets_error": dirty_target_status["error"],
            "dirty_legal_parser_targets_source": dirty_target_status["source"],
            "dirty_legal_parser_targets_checked_at": dirty_target_status["checked_at"],
            "dirty_legal_parser_targets_fingerprint": dirty_target_status["fingerprint"],
            "run": {
                "run_id": self.run_id,
                "started_at": self.run_started_at,
                "baseline_head": self.run_baseline_head,
            },
            "accepted_change_summaries": accepted_summaries,
            "recent_rejections": recent_rejections,
            "repeated_rejection_family": repeated_rejection_family,
            "dirty_touched_file_rejection_count": sum(
                1 for item in recent_rejections if item.get("dirty_touched_files")
            ),
            "active_dirty_touched_files": active_dirty_touched_files,
            "candidate_post_apply_validation_rejection_count": len(candidate_validation_failures),
            "latest_candidate_post_apply_validation_failure": (
                candidate_validation_failures[-1] if candidate_validation_failures else {}
            ),
            "latest_cycle": {
                "cycle_index": latest_cycle.get("cycle_index"),
                "status": latest_cycle.get("status", "ok"),
                "changed_files": latest_cycle.get("changed_files", []),
                "patch_valid": (latest_cycle.get("patch_check") or {}).get("valid"),
                "proposal_quality": latest_cycle.get("proposal_quality", {}),
                "retained_change": latest_cycle.get("retained_change", {}),
                "commit_result": latest_cycle.get("commit_result", {}),
                "applied": (latest_cycle.get("apply_result") or {}).get("applied"),
                "rolled_back": (latest_cycle.get("apply_result") or {}).get("rolled_back", False),
                "tests_valid": (latest_cycle.get("tests") or {}).get("valid"),
            },
        }

    def _write_run_manifest(self) -> None:
        manifest = {
            "run_id": self.run_id,
            "started_at": self.run_started_at,
            "baseline_head": self.run_baseline_head,
            "model_name": self.config.model_name,
            "provider": self.config.provider_label(),
            "apply_patches": self.config.apply_patches,
            "commit_accepted_patches": self.config.commit_accepted_patches,
            "require_clean_touched_files": self.config.require_clean_touched_files,
            "test_command": list(self.config.test_command),
        }
        (self.output_dir / "current_run.json").write_text(
            json.dumps(manifest, indent=2, default=str),
            encoding="utf-8",
        )

    def _write_progress_report(self, progress: Dict[str, Any]) -> None:
        (self.output_dir / "PROGRESS.md").write_text(
            self._format_progress_report(progress),
            encoding="utf-8",
        )

    def _format_progress_report(self, progress: Dict[str, Any]) -> str:
        git_work = progress.get("git_retained_work") or {}
        run = progress.get("run") or {}
        commits_since_start = git_work.get("commits_since_run_start") or []
        uncommitted_files = git_work.get("uncommitted_files") or []
        visible_status = "visible"
        if not commits_since_start and not uncommitted_files:
            visible_status = "no visible parser delta since this daemon run started"

        lines = [
            "# Legal Parser Optimizer Progress",
            "",
            f"- Updated: `{progress.get('updated_at', '')}`",
            f"- Run ID: `{run.get('run_id', self.run_id)}`",
            f"- Run baseline: `{run.get('baseline_head', self.run_baseline_head)}`",
            f"- Current HEAD: `{git_work.get('head', '')}`",
            f"- Visible work status: `{visible_status}`",
            f"- Total cycles: `{progress.get('total_cycles', 0)}`",
            f"- Goal epoch started: `{progress.get('goal_epoch_started_at', '')}`",
            f"- Goal epoch cycles: `{progress.get('goal_epoch_cycle_count', 0)}`",
            f"- Accepted retained patches: `{progress.get('retained_accepted_patch_count', 0)}`",
            f"- Goal epoch accepted patches: `{progress.get('goal_epoch_accepted_patch_count', 0)}`",
            f"- Rolled back patches: `{progress.get('rolled_back_count', 0)}`",
            f"- Rolled back since meaningful progress: `{progress.get('rolled_back_since_meaningful_progress', 0)}`",
            f"- Rejected patches: `{progress.get('rejected_patch_count', 0)}`",
            f"- Goal epoch rejected patches: `{progress.get('goal_epoch_rejected_patch_count', 0)}`",
            f"- Current score: `{progress.get('current_score')}`",
            f"- Score delta: `{progress.get('score_delta')}`",
            f"- Stalled metric cycles: `{progress.get('stalled_metric_cycles', 0)}`",
            f"- Cycles since meaningful progress: `{progress.get('cycles_since_meaningful_progress', 0)}`",
            "",
            "## Visible Git Work",
            "",
        ]
        if commits_since_start:
            lines.append("Commits since this daemon run started:")
            lines.extend(f"- `{commit}`" for commit in commits_since_start)
        else:
            lines.append("No deontic parser commits have been created since this daemon run started.")
        lines.append("")
        if uncommitted_files:
            lines.append("Uncommitted deontic parser files:")
            lines.extend(f"- `{path}`" for path in uncommitted_files)
        else:
            lines.append("No uncommitted deontic parser files are currently visible.")
        diff_stat = str(git_work.get("diff_since_run_start_stat") or git_work.get("diff_stat") or "").strip()
        if diff_stat:
            lines.extend(["", "Diff stat:", "", "```text", diff_stat, "```"])
        lines.extend(["", "## Recent Accepted Changes", ""])
        accepted = progress.get("accepted_change_summaries") or []
        if accepted:
            for item in accepted[-10:]:
                files = ", ".join(item.get("changed_files") or [])
                lines.append(f"- Cycle `{item.get('cycle_index')}`: {item.get('summary') or '(no summary)'}")
                if files:
                    lines.append(f"  Files: `{files}`")
        else:
            lines.append("No accepted retained changes are recorded yet.")
        lines.extend(["", "## Current Blockers", ""])
        feedback = progress.get("current_feedback") or []
        if feedback:
            lines.extend(f"- `{item}`" for item in feedback)
        else:
            lines.append("No current feedback items recorded.")
        active_dirty = progress.get("active_dirty_touched_files") or []
        if active_dirty:
            lines.extend(["", "Active dirty touched files blocking proposals:"])
            lines.extend(f"- `{path}`" for path in active_dirty)
        candidate_failure = progress.get("latest_candidate_post_apply_validation_failure") or {}
        if candidate_failure:
            summary = candidate_failure.get("summary") or {}
            lines.extend(["", "Latest candidate post-apply validation failure:"])
            attempt = candidate_failure.get("attempt")
            if attempt is not None:
                lines.append(f"- attempt: `{attempt}`")
            failed_tests = summary.get("failed_tests") or []
            if failed_tests:
                lines.append("- failed tests: " + ", ".join(f"`{name}`" for name in failed_tests[:6]))
            exception_types = summary.get("exception_types") or []
            if exception_types:
                lines.append("- exception types: " + ", ".join(f"`{name}`" for name in exception_types[:6]))
            reasons = candidate_failure.get("reasons") or []
            if reasons:
                lines.append("- reasons: " + "; ".join(str(reason) for reason in reasons[:3]))
            failure_head = str(summary.get("failure_head") or "").strip()
            if failure_head:
                lines.extend(["", "```text", failure_head[:1200], "```"])
        repeated_rejection = progress.get("repeated_rejection_family") or {}
        if repeated_rejection and int(repeated_rejection.get("count") or 0) >= 2:
            lines.extend(["", "Repeated rejection family:"])
            lines.append(f"- reason: `{repeated_rejection.get('reason') or 'unknown'}`")
            lines.append(f"- count: `{repeated_rejection.get('count')}`")
            cycle_indexes = repeated_rejection.get("cycle_indexes") or []
            if cycle_indexes:
                lines.append("- cycles: " + ", ".join(f"`{index}`" for index in cycle_indexes[:10]))
            changed_files = repeated_rejection.get("changed_files") or []
            if changed_files:
                lines.append("- files: " + ", ".join(f"`{path}`" for path in changed_files[:8]))
            latest_candidate = repeated_rejection.get("latest_candidate_validation_failure") or {}
            latest_summary = latest_candidate.get("summary") or {}
            latest_head = str(latest_summary.get("failure_head") or "").strip()
            if latest_head:
                lines.extend(["", "```text", latest_head[:1200], "```"])
        dirty_parser_targets = progress.get("dirty_legal_parser_targets") or []
        if dirty_parser_targets:
            lines.extend(["", "Dirty legal-parser recovery targets:"])
            lines.extend(f"- `{path}`" for path in dirty_parser_targets)
        if progress.get("dirty_legal_parser_targets_valid") is False:
            error = progress.get("dirty_legal_parser_targets_error") or {}
            lines.extend(
                [
                    "",
                    "Dirty legal-parser target detection failed:",
                    f"- returncode: `{error.get('returncode')}`",
                ]
            )
            stderr_tail = str(error.get("stderr_tail") or "").strip()
            if stderr_tail:
                lines.append(f"- stderr tail: `{stderr_tail}`")
        rollback_reasons = progress.get("rolled_back_reasons_since_meaningful_progress") or {}
        if rollback_reasons:
            lines.extend(["", "Rollback reasons since meaningful progress:"])
            lines.extend(
                f"- `{reason}`: `{count}`"
                for reason, count in sorted(rollback_reasons.items(), key=lambda item: (-int(item[1]), item[0]))
            )
        lines.extend(["", "## Recent Rejections", ""])
        recent_rejections = progress.get("recent_rejections") or []
        if recent_rejections:
            for item in recent_rejections[-10:]:
                reason = item.get("reason") or "unknown"
                files = ", ".join(item.get("changed_files") or [])
                lines.append(f"- Cycle `{item.get('cycle_index')}`: `{reason}`")
                if files:
                    lines.append(f"  Files: `{files}`")
        else:
            lines.append("No recent rejected cycles recorded.")
        lines.append("")
        return "\n".join(lines)

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"cycle_index": 0}
        try:
            loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {"cycle_index": 0}
        except (OSError, json.JSONDecodeError):
            return {"cycle_index": 0}

    def _working_tree_diff(self) -> str:
        result = _run_command(
            ["git", "diff", "--binary"],
            cwd=self.config.repo_root,
            timeout=60,
        )
        return str(result.get("stdout") or "")

    def _restore_working_tree_diff(self, pre_apply_diff: str) -> Dict[str, Any]:
        current_diff = self._working_tree_diff()
        if current_diff == pre_apply_diff:
            return {"valid": True, "changed": False, "reason": "working_tree_already_restored"}
        reverse_result = _run_command(
            ["git", "apply", "-R", "-"],
            cwd=self.config.repo_root,
            input_text=current_diff,
            timeout=60,
        )
        if not reverse_result.get("valid"):
            return {"valid": False, "changed": False, "reverse": reverse_result}
        restore_result = {"valid": True, "changed": True, "reverse": reverse_result}
        if pre_apply_diff.strip():
            reapply_result = _run_command(
                ["git", "apply", "-"],
                cwd=self.config.repo_root,
                input_text=pre_apply_diff,
                timeout=60,
            )
            restore_result["reapply_preexisting"] = reapply_result
            restore_result["valid"] = bool(reapply_result.get("valid"))
        return restore_result

    def _snapshot_patch_paths(self, unified_diff: str) -> Dict[str, Optional[str]]:
        snapshots: Dict[str, Optional[str]] = {}
        for rel_path in _paths_from_unified_diff(unified_diff):
            path = self.config.repo_root / rel_path
            try:
                snapshots[rel_path] = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                snapshots[rel_path] = None
            except OSError as exc:
                snapshots[rel_path] = f"__SNAPSHOT_ERROR__:{exc}"
        return snapshots

    def _restore_patch_paths(self, snapshots: Dict[str, Optional[str]]) -> Dict[str, Any]:
        errors: List[str] = []
        restored: List[str] = []
        for rel_path, content in snapshots.items():
            path = self.config.repo_root / rel_path
            try:
                if isinstance(content, str) and content.startswith("__SNAPSHOT_ERROR__:"):
                    errors.append(f"{rel_path}: {content}")
                    continue
                if content is None:
                    if path.exists():
                        path.unlink()
                        restored.append(rel_path)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                restored.append(rel_path)
            except OSError as exc:
                errors.append(f"{rel_path}: {exc}")
        return {"valid": not errors, "restored": restored, "errors": errors}

    def _retained_change_summary(self, snapshots: Dict[str, Optional[str]]) -> Dict[str, Any]:
        changed_files: List[str] = []
        deleted_files: List[str] = []
        created_files: List[str] = []
        for rel_path, before in snapshots.items():
            if isinstance(before, str) and before.startswith("__SNAPSHOT_ERROR__:"):
                continue
            path = self.config.repo_root / rel_path
            try:
                after: Optional[str] = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                after = None
            except OSError:
                continue
            if before != after:
                changed_files.append(rel_path)
                if before is None and after is not None:
                    created_files.append(rel_path)
                elif before is not None and after is None:
                    deleted_files.append(rel_path)
        return {
            "has_retained_changes": bool(changed_files),
            "changed_files": changed_files,
            "created_files": created_files,
            "deleted_files": deleted_files,
            "reason": "content_changed" if changed_files else "no_file_content_changed_after_apply",
        }

    def _retained_patch_for_paths(self, snapshots: Dict[str, Optional[str]]) -> str:
        paths = [path for path in snapshots if path]
        if not paths:
            return ""
        result = _run_command(
            ["git", "diff", "--binary", "--", *paths],
            cwd=self.config.repo_root,
            timeout=60,
        )
        return str(result.get("stdout") or "")

    def _dirty_touched_files(self, changed_files: Sequence[str]) -> List[str]:
        dirty: List[str] = []
        for rel_path in changed_files:
            result = _run_command(
                ["git", "status", "--porcelain", "--", rel_path],
                cwd=self.config.repo_root,
                timeout=30,
            )
            status_paths = _paths_from_git_status_porcelain(str(result.get("stdout") or ""))
            if status_paths:
                dirty_path = status_paths[-1] if len(status_paths) == 1 else rel_path
                if dirty_path not in dirty:
                    dirty.append(dirty_path)
        return dirty

    def _dirty_legal_parser_targets(self) -> List[str]:
        """Return dirty files in the legal-parser target set tracked by recovery."""

        return self._dirty_legal_parser_target_status()["paths"]

    def _dirty_legal_parser_target_status(self) -> Dict[str, Any]:
        """Return dirty legal-parser targets plus status-command health."""

        result = _run_command(
            ["git", "status", "--porcelain", "--", *LEGAL_PARSER_RECOVERY_TARGETS],
            cwd=self.config.repo_root,
            timeout=30,
        )
        checked_at = _utc_now()
        if not result.get("valid"):
            stderr = str(result.get("stderr") or "").strip()
            return {
                "valid": False,
                "paths": [],
                "source": "fresh_git_status_porcelain",
                "checked_at": checked_at,
                "fingerprint": "",
                "error": {
                    "returncode": result.get("returncode"),
                    "stderr_tail": stderr[-1000:],
                },
            }
        stdout = str(result.get("stdout") or "")
        paths = _paths_from_git_status_porcelain(stdout)
        return {
            "valid": True,
            "paths": paths,
            "source": "fresh_git_status_porcelain",
            "checked_at": checked_at,
            "fingerprint": _dirty_target_fingerprint(
                repo_root=self.config.repo_root,
                status_stdout=stdout,
                paths=paths,
            ),
            "error": {},
        }

    def _dirty_target_fingerprint(self, *, status_stdout: str, paths: Sequence[str]) -> str:
        """Return a content-sensitive fingerprint for stranded parser target diffs."""

        return _dirty_target_fingerprint(
            repo_root=self.config.repo_root,
            status_stdout=status_stdout,
            paths=paths,
        )

    def _post_apply_validation(self, changed_files: Sequence[str]) -> Dict[str, Any]:
        """Run fast structural checks before expensive tests or retention."""

        existing_python_files = [
            path
            for path in changed_files
            if path.endswith(".py") and (self.config.repo_root / path).exists()
        ]
        compile_result: Dict[str, Any] = {
            "valid": True,
            "skipped": True,
            "reason": "no_changed_python_files",
        }
        if existing_python_files:
            compile_result = _run_command(
                [sys.executable, "-m", "py_compile", *existing_python_files],
                cwd=self.config.repo_root,
                timeout=min(60, max(10, int(self.config.test_timeout_seconds))),
            )

        changed_test_files = [
            path
            for path in existing_python_files
            if path.startswith("tests/unit_tests/logic/deontic/")
        ]
        collect_result: Dict[str, Any] = {
            "valid": True,
            "skipped": True,
            "reason": "no_changed_deontic_test_files",
        }
        if compile_result.get("valid") and changed_test_files:
            collect_result = _run_command(
                ["pytest", "--collect-only", "-q", *changed_test_files],
                cwd=self.config.repo_root,
                timeout=min(90, max(20, int(self.config.test_timeout_seconds))),
            )

        focused_tests_result: Dict[str, Any] = {
            "valid": True,
            "skipped": True,
            "reason": "no_changed_deontic_test_files",
        }
        if compile_result.get("valid") and collect_result.get("valid") and changed_test_files:
            focused_tests_result = _run_command(
                ["pytest", "-q", *changed_test_files],
                cwd=self.config.repo_root,
                timeout=min(120, max(30, int(self.config.test_timeout_seconds))),
            )

        valid = (
            bool(compile_result.get("valid"))
            and bool(collect_result.get("valid"))
            and bool(focused_tests_result.get("valid"))
        )
        reasons: List[str] = []
        if not compile_result.get("valid"):
            reasons.append("changed Python files failed py_compile")
        if not collect_result.get("valid"):
            reasons.append("changed deontic tests failed pytest collection")
        if not focused_tests_result.get("valid"):
            reasons.append("changed deontic tests failed focused pytest")
        return {
            "valid": valid,
            "changed_python_files": existing_python_files,
            "changed_test_files": changed_test_files,
            "compile": compile_result,
            "collect": collect_result,
            "focused_tests": focused_tests_result,
            "reasons": reasons,
        }

    def _commit_retained_change(
        self,
        cycle_index: int,
        proposal: LegalParserCycleProposal,
        retained_change: Dict[str, Any],
    ) -> Dict[str, Any]:
        changed_files = [str(path) for path in retained_change.get("changed_files") or []]
        if not changed_files:
            return {"committed": False, "reason": "no_retained_changed_files"}
        add_result = _run_command(["git", "add", "--", *changed_files], cwd=self.config.repo_root, timeout=60)
        if not add_result.get("valid"):
            return {"committed": False, "reason": "git_add_failed", "add": add_result}
        summary = proposal.summary.strip() or "Improve deterministic legal parser"
        subject = f"legal-parser-daemon: cycle {cycle_index} retained parser improvement"
        body = "\n".join(
            [
                summary,
                "",
                f"Focus area: {proposal.focus_area or 'unspecified'}",
                "Changed files:",
                *[f"- {path}" for path in changed_files],
            ]
        )
        commit_result = _run_command(
            ["git", "commit", "-m", subject, "-m", body],
            cwd=self.config.repo_root,
            timeout=120,
        )
        head_result = _run_command(["git", "rev-parse", "--short", "HEAD"], cwd=self.config.repo_root, timeout=30)
        return {
            "committed": bool(commit_result.get("valid")),
            "commit": str(head_result.get("stdout") or "").strip() if commit_result.get("valid") else "",
            "changed_files": changed_files,
            "commit_command": commit_result,
        }

    def _git_retained_work_snapshot(self) -> Dict[str, Any]:
        target_paths = [
            "ipfs_datasets_py/logic/deontic",
            "tests/unit_tests/logic/deontic",
            "ipfs_datasets_py/optimizers/logic/deontic",
        ]
        head = _run_command(["git", "rev-parse", "--short", "HEAD"], cwd=self.config.repo_root, timeout=30)
        status = _run_command(["git", "status", "--short", "--", *target_paths], cwd=self.config.repo_root, timeout=30)
        diff_stat = _run_command(["git", "diff", "--stat", "--", *target_paths], cwd=self.config.repo_root, timeout=30)
        recent_commits = _run_command(
            ["git", "log", "--oneline", "-5", "--", *target_paths],
            cwd=self.config.repo_root,
            timeout=30,
        )
        commits_since_run_start = _run_command(
            ["git", "log", "--oneline", f"{self.run_baseline_head}..HEAD", "--", *target_paths],
            cwd=self.config.repo_root,
            timeout=30,
        )
        diff_since_run_start = _run_command(
            ["git", "diff", "--stat", f"{self.run_baseline_head}..HEAD", "--", *target_paths],
            cwd=self.config.repo_root,
            timeout=30,
        )
        uncommitted_files = [
            line.strip()
            for line in str(status.get("stdout") or "").splitlines()
            if line.strip()
        ]
        return {
            "head": str(head.get("stdout") or "").strip(),
            "uncommitted_file_count": len(uncommitted_files),
            "uncommitted_files": uncommitted_files,
            "diff_stat": str(diff_stat.get("stdout") or "").strip(),
            "run_baseline_head": self.run_baseline_head,
            "commits_since_run_start": [
                line.strip()
                for line in str(commits_since_run_start.get("stdout") or "").splitlines()
                if line.strip()
            ],
            "diff_since_run_start_stat": str(diff_since_run_start.get("stdout") or "").strip(),
            "recent_commits": [
                line.strip()
                for line in str(recent_commits.get("stdout") or "").splitlines()
                if line.strip()
            ],
        }

    def _current_head(self) -> str:
        result = _run_command(["git", "rev-parse", "--short", "HEAD"], cwd=self.config.repo_root, timeout=30)
        return str(result.get("stdout") or "").strip()


def parse_cycle_proposal(raw_response: str) -> LegalParserCycleProposal:
    """Parse strict JSON proposal text, with fenced JSON fallback."""

    proposal = LegalParserCycleProposal(raw_response=raw_response)
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, flags=re.DOTALL)
        if not match:
            proposal.parse_error = "response was not JSON and no fenced JSON object was found"
            return proposal
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            proposal.parse_error = str(exc)
            return proposal

    if not isinstance(payload, dict):
        proposal.parse_error = "proposal JSON was not an object"
        return proposal
    proposal.summary = str(payload.get("summary") or "")
    proposal.focus_area = str(payload.get("focus_area") or "")
    proposal.requirements_addressed = [str(item) for item in payload.get("requirements_addressed") or []]
    proposal.acceptance_criteria = [str(item) for item in payload.get("acceptance_criteria") or []]
    proposal.changed_files = [str(item) for item in payload.get("changed_files") or []]
    proposal.expected_metric_gain = dict(payload.get("expected_metric_gain") or {})
    proposal.tests_to_run = [str(item) for item in payload.get("tests_to_run") or []]
    proposal.unified_diff = str(payload.get("unified_diff") or "")
    return proposal


def _read_text(path: Path, *, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"[unavailable: {exc}]"
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-(limit // 2) :]
    return f"{head}\n\n[... truncated ...]\n\n{tail}"


def _summarize_test_failure(stdout: str) -> Dict[str, Any]:
    failed_tests: List[str] = []
    for match in re.finditer(r"FAILED\s+([^\s]+)", stdout):
        name = match.group(1).strip()
        if name == "[" or "::" not in name:
            continue
        if name and name not in failed_tests:
            failed_tests.append(name)

    exception_types: List[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", stdout):
        name = match.group(1)
        if name and name not in exception_types:
            exception_types.append(name)

    interesting_lines: List[str] = []
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if (
            text.startswith("FAILED ")
            or text.startswith("E   ")
            or "Recursion detected" in text
            or "short test summary info" in text
        ):
            interesting_lines.append(text)
        if len(interesting_lines) >= 10:
            break

    return {
        "failed_tests": failed_tests,
        "exception_types": exception_types,
        "failure_head": "\n".join(interesting_lines)[:2000],
    }


def _summarize_post_apply_validation_failure(validation: Mapping[str, Any]) -> Dict[str, Any]:
    if not validation or validation.get("valid") is not False:
        return {}

    failed_tests: List[str] = []
    exception_types: List[str] = []
    interesting_lines: List[str] = []
    for check_name in ("compile", "collect", "focused_tests"):
        check = dict(validation.get(check_name) or {})
        if check.get("valid") is not False:
            continue
        stderr = str(check.get("stderr") or "")
        stdout = str(check.get("stdout") or "")
        if check_name == "compile" and "py_compile" not in exception_types:
            exception_types.append("py_compile")
        for match in re.finditer(r"FAILED\s+([^\s]+)", stderr + "\n" + stdout):
            name = match.group(1).strip()
            if name == "[" or "::" not in name:
                continue
            if name and name not in failed_tests:
                failed_tests.append(name)
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", stderr + "\n" + stdout):
            name = match.group(1)
            if name and name not in exception_types:
                exception_types.append(name)
        for line in (stderr + "\n" + stdout).splitlines():
            text = line.strip()
            if not text:
                continue
            if (
                text.startswith("File ")
                or text.startswith("E   ")
                or "SyntaxError" in text
                or "IndentationError" in text
                or "pytest" in text
                or "FAILED " in text
            ):
                interesting_lines.append(f"{check_name}: {text}")
            if len(interesting_lines) >= 12:
                break

    if not interesting_lines:
        interesting_lines = [str(reason) for reason in validation.get("reasons") or []]

    return {
        "failed_tests": failed_tests[:12],
        "exception_types": exception_types[:8],
        "failure_head": "\n".join(interesting_lines)[:2000],
    }


def _latest_candidate_validation_failure(attempts: Sequence[Any]) -> Dict[str, Any]:
    """Return the newest failed candidate preflight from proposal attempts."""

    for item in reversed(list(attempts)):
        if not isinstance(item, Mapping):
            continue
        if item.get("candidate_validation_valid") is not False:
            continue
        summary = dict(item.get("candidate_validation_summary") or {})
        if not _failure_summary_has_content(summary):
            retry_reason = str(item.get("retry_reason") or "")
            reasons = [str(reason) for reason in item.get("candidate_validation_reasons") or []]
            summary = {
                "failed_tests": [],
                "exception_types": [
                    match.group(1)
                    for match in re.finditer(
                        r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b",
                        retry_reason + "\n" + "\n".join(reasons),
                    )
                ][:8],
                "failure_head": retry_reason or "; ".join(reasons),
            }
        return {
            "valid": False,
            "attempt": item.get("attempt"),
            "changed_files": item.get("changed_files", []),
            "reasons": item.get("candidate_validation_reasons", []),
            "summary": summary,
        }
    return {"valid": True, "skipped": True, "reason": "no_failed_candidate_validation"}


def _failure_summary_has_content(summary: Mapping[str, Any]) -> bool:
    return bool(
        summary.get("failed_tests")
        or summary.get("exception_types")
        or str(summary.get("failure_head") or "").strip()
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class _TemporaryEnv:
    """Temporarily set environment variables for a narrow call boundary."""

    def __init__(self, updates: Mapping[str, str]) -> None:
        self._updates = dict(updates)
        self._previous: Dict[str, Optional[str]] = {}

    def __enter__(self) -> "_TemporaryEnv":
        for key, value in self._updates.items():
            self._previous[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for key, previous in self._previous.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _run_command(
    cmd: Sequence[str],
    *,
    cwd: Path,
    input_text: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "valid": proc.returncode == 0,
            "returncode": proc.returncode,
            "command": list(cmd),
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-12000:],
            "duration_seconds": round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "valid": False,
            "returncode": None,
            "command": list(cmd),
            "stdout": str(exc.stdout or "")[-12000:],
            "stderr": f"timeout after {timeout}s",
            "duration_seconds": round(time.time() - started, 3),
        }


def _paths_from_git_status_porcelain(stdout: str) -> List[str]:
    """Return unique paths from plain ``git status --porcelain`` output."""

    paths: List[str] = []
    for line in stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1].strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def _paths_from_unified_diff(unified_diff: str) -> List[str]:
    paths: List[str] = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", unified_diff, flags=re.MULTILINE):
        for candidate in (match.group(1), match.group(2)):
            if candidate == "/dev/null":
                continue
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _production_files(paths: Sequence[str]) -> List[str]:
    return [
        path
        for path in paths
        if path.startswith("ipfs_datasets_py/logic/deontic/")
        and not path.startswith("ipfs_datasets_py/logic/deontic/__pycache__/")
    ]


def _test_files(paths: Sequence[str]) -> List[str]:
    return [path for path in paths if path.startswith("tests/unit_tests/logic/deontic/")]


def _dirty_target_fingerprint(*, repo_root: Path, status_stdout: str, paths: Sequence[str]) -> str:
    """Return a content-sensitive fingerprint for stranded parser target diffs."""

    if not paths:
        return ""
    digest = hashlib.sha256()
    digest.update(status_stdout.encode("utf-8", errors="replace"))
    diff_result = _run_command(
        ["git", "diff", "--binary", "--", *paths],
        cwd=repo_root,
        timeout=60,
    )
    digest.update(str(diff_result.get("stdout") or "").encode("utf-8", errors="replace"))
    for rel_path in sorted(paths):
        path = repo_root / rel_path
        digest.update(rel_path.encode("utf-8", errors="replace"))
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"__missing__")
        except OSError as exc:
            digest.update(f"__error__:{exc}".encode("utf-8", errors="replace"))
    return digest.hexdigest()


def _unified_diff_stats(unified_diff: str) -> Dict[str, Any]:
    files = _paths_from_unified_diff(unified_diff)
    insertions = 0
    deletions = 0
    for line in unified_diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1
    return {
        "files_changed": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "changed_files": files,
    }


def _cycle_was_kept(cycle_payload: Dict[str, Any]) -> bool:
    apply_result = cycle_payload.get("apply_result") or {}
    tests = cycle_payload.get("tests") or {}
    retained = cycle_payload.get("retained_change")
    retained_ok = True
    if isinstance(retained, dict):
        retained_ok = bool(retained.get("has_retained_changes"))
    return bool(
        apply_result.get("applied")
        and not apply_result.get("rolled_back", False)
        and tests.get("valid") is True
        and retained_ok
    )


def _cycle_in_epoch(cycle_payload: Mapping[str, Any], epoch_started_at: str) -> bool:
    if not epoch_started_at:
        return True
    cycle_started_at = str(cycle_payload.get("started_at") or cycle_payload.get("finished_at") or "")
    if not cycle_started_at:
        return True
    try:
        return _parse_utc(cycle_started_at) >= _parse_utc(epoch_started_at)
    except Exception:
        return True


def _cycle_effective_score(cycle_payload: Dict[str, Any]) -> Optional[float]:
    post_metrics = (cycle_payload.get("post_evaluation") or {}).get("metrics") or {}
    post_score = _as_float(post_metrics.get("parity_score"))
    if post_score is not None:
        return post_score
    metrics = cycle_payload.get("metrics") or {}
    metric_score = _as_float(metrics.get("parity_score"))
    if metric_score is not None:
        return metric_score
    return _as_float(cycle_payload.get("score"))


def _cycle_rejection_reason(cycle_payload: Dict[str, Any]) -> str:
    if cycle_payload.get("status") == "cycle_error":
        exception = cycle_payload.get("exception") or {}
        return f"cycle_error:{exception.get('type') or 'unknown'}"
    proposal_quality = cycle_payload.get("proposal_quality") or {}
    if proposal_quality.get("valid") is False:
        reasons = proposal_quality.get("reasons") or []
        if reasons:
            return "proposal_quality_failed:" + "; ".join(str(item) for item in reasons[:3])
        return "proposal_quality_failed"
    patch_check = cycle_payload.get("patch_check") or {}
    if patch_check.get("valid") is False:
        stderr = str(patch_check.get("stderr") or "").strip().splitlines()
        first_line = stderr[0] if stderr else "patch_check_failed"
        return f"patch_check_failed:{first_line}"
    apply_result = cycle_payload.get("apply_result") or {}
    if not apply_result.get("applied"):
        return str(apply_result.get("reason") or "patch_not_applied")
    if apply_result.get("rolled_back"):
        return str(apply_result.get("reason") or "rolled_back_after_failed_tests")
    tests = cycle_payload.get("tests") or {}
    if tests.get("valid") is False:
        return "tests_failed"
    retained = cycle_payload.get("retained_change") or {}
    if retained.get("has_retained_changes") is False:
        return str(retained.get("reason") or "no_retained_changes")
    return "unknown"


def _rejection_family_reason(reason: str) -> str:
    """Return a stable family key for repeated autonomous rejection loops."""

    text = str(reason or "").strip()
    if not text:
        return "unknown"
    if "candidate_post_apply_validation_failed" in text:
        return "candidate_post_apply_validation_failed"
    if "patch touches files with pre-existing uncommitted changes" in text:
        return "dirty_touched_files"
    if text.startswith("proposal_quality_failed:"):
        first_detail = text.split(":", 1)[1].split(";", 1)[0].strip()
        return f"proposal_quality_failed:{first_detail}" if first_detail else "proposal_quality_failed"
    if text.startswith("patch_check_failed:"):
        return "patch_check_failed"
    return text.split(":", 1)[0]


def _repeated_rejection_family(rejections: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Summarize the largest repeated rejection family in recent progress."""

    families: Dict[str, Dict[str, Any]] = {}
    for item in rejections:
        if not isinstance(item, Mapping):
            continue
        candidate_failure = item.get("latest_candidate_validation_failure")
        reason = (
            "candidate_post_apply_validation_failed"
            if isinstance(candidate_failure, Mapping) and candidate_failure.get("valid") is False
            else _rejection_family_reason(str(item.get("reason") or ""))
        )
        family = families.setdefault(
            reason,
            {
                "reason": reason,
                "count": 0,
                "cycle_indexes": [],
                "changed_files": [],
                "dirty_touched_files": [],
                "latest_candidate_validation_failure": {},
            },
        )
        family["count"] += 1
        cycle_index = item.get("cycle_index")
        if cycle_index is not None:
            family["cycle_indexes"].append(cycle_index)
        for key in ("changed_files", "dirty_touched_files"):
            for path in item.get(key) or []:
                text = str(path).strip()
                if text and text not in family[key]:
                    family[key].append(text)
        if isinstance(candidate_failure, Mapping) and candidate_failure.get("valid") is False:
            family["latest_candidate_validation_failure"] = dict(candidate_failure)

    if not families:
        return {}
    return max(
        families.values(),
        key=lambda item: (
            int(item.get("count") or 0),
            len(item.get("cycle_indexes") or []),
            str(item.get("reason") or ""),
        ),
    )


def _dirty_files_from_rejections(rejections: Sequence[Mapping[str, Any]]) -> List[str]:
    files: List[str] = []
    for item in rejections:
        dirty_files = item.get("dirty_touched_files") or []
        if not dirty_files:
            continue
        for path in dirty_files:
            text = str(path).strip()
            if text and text not in files:
                files.append(text)
    return files


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")


def _resolve_path(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else (root / value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic legal parser optimizer daemon.")
    parser.add_argument("--repo-root", default=".", help="Repository root for ipfs_datasets_py.")
    parser.add_argument("--output-dir", default="artifacts/legal_parser_optimizer_daemon")
    parser.add_argument("--model-name", default=os.environ.get("LEGAL_PARSER_DAEMON_MODEL", "gpt-5.5"))
    parser.add_argument("--provider", default=os.environ.get("LEGAL_PARSER_DAEMON_PROVIDER") or "llm_router")
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--cycle-interval-seconds", type=float, default=0.0)
    parser.add_argument("--error-backoff-seconds", type=float, default=30.0)
    parser.add_argument("--llm-timeout-seconds", type=int, default=900)
    parser.add_argument("--llm-proposal-attempts", type=int, default=3)
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=15.0)
    parser.add_argument("--test-timeout-seconds", type=int, default=600)
    parser.add_argument(
        "--allow-patches-without-tests",
        action="store_true",
        help="Do not reject valid patches that lack a deontic test-file change.",
    )
    parser.add_argument("--target-score", type=float, default=0.98)
    parser.add_argument("--apply-patches", action="store_true", help="Apply LLM-generated patches after git apply --check.")
    parser.add_argument(
        "--commit-accepted-patches",
        action="store_true",
        help="Commit each retained patch after tests pass, staging only files touched by that patch.",
    )
    parser.add_argument(
        "--allow-dirty-touched-files",
        action="store_true",
        help="Allow patches to touch files that already have uncommitted changes.",
    )
    parser.add_argument("--no-tests", action="store_true", help="Skip pytest validation.")
    parser.add_argument(
        "--test-command",
        nargs=argparse.REMAINDER,
        default=None,
        help="Validation command. Defaults to: pytest tests/unit_tests/logic/deontic",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> LegalParserDaemonConfig:
    test_command = tuple(args.test_command) if args.test_command else ("pytest", "tests/unit_tests/logic/deontic")
    return LegalParserDaemonConfig(
        repo_root=Path(args.repo_root),
        output_dir=Path(args.output_dir),
        model_name=str(args.model_name),
        provider=str(args.provider) if args.provider else None,
        max_cycles=int(args.max_cycles),
        cycle_interval_seconds=float(args.cycle_interval_seconds),
        error_backoff_seconds=float(args.error_backoff_seconds),
        llm_timeout_seconds=int(args.llm_timeout_seconds),
        llm_proposal_attempts=int(args.llm_proposal_attempts),
        heartbeat_interval_seconds=float(args.heartbeat_interval_seconds),
        test_timeout_seconds=int(args.test_timeout_seconds),
        require_production_and_tests=not bool(args.allow_patches_without_tests),
        target_score=float(args.target_score),
        apply_patches=bool(args.apply_patches),
        commit_accepted_patches=bool(args.commit_accepted_patches),
        require_clean_touched_files=not bool(args.allow_dirty_touched_files),
        run_tests=not bool(args.no_tests),
        test_command=test_command,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    daemon = LegalParserOptimizerDaemon(config_from_args(args))
    summary = asyncio.run(daemon.run())
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
