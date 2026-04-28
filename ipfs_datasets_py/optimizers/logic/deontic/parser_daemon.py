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
import json
import traceback
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
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


@dataclass
class LegalParserDaemonConfig:
    """Configuration for legal parser optimization cycles."""

    repo_root: Path = field(default_factory=lambda: Path.cwd())
    output_dir: Path = field(default_factory=lambda: Path("artifacts/legal_parser_optimizer_daemon"))
    model_name: str = "gpt-5.5"
    provider: str = "codex_cli"
    max_cycles: int = 1
    cycle_interval_seconds: float = 0.0
    error_backoff_seconds: float = 30.0
    target_score: float = 0.98
    min_score_improvement: float = 0.001
    apply_patches: bool = False
    run_tests: bool = True
    test_command: Tuple[str, ...] = ("pytest", "tests/unit_tests/logic/deontic")
    llm_max_tokens: int = 6000
    llm_temperature: float = 0.1
    llm_timeout_seconds: int = 900
    test_timeout_seconds: int = 180
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
        repair_required: List[str] = []
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
                all_elements.append(element)
                if (element.get("llm_repair") or {}).get("required"):
                    repair_required.append(str(element.get("source_id") or sample["id"]))
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
        if self.llm_backend is not None:
            raw_response = self.llm_backend.generate(
                prompt,
                method=OptimizationMethod.TEST_DRIVEN,
                max_tokens=self.daemon_config.llm_max_tokens,
                temperature=self.daemon_config.llm_temperature,
                router_kwargs={
                    "provider": self.daemon_config.provider,
                    "model_name": self.daemon_config.model_name,
                    "allow_local_fallback": False,
                    "timeout": self.daemon_config.llm_timeout_seconds,
                },
            )
        else:
            from ipfs_datasets_py import llm_router

            raw_response = llm_router.generate_text(
                prompt,
                provider=self.daemon_config.provider,
                model_name=self.daemon_config.model_name,
                max_tokens=self.daemon_config.llm_max_tokens,
                temperature=self.daemon_config.llm_temperature,
                timeout=self.daemon_config.llm_timeout_seconds,
                allow_local_fallback=False,
            )
        return parse_cycle_proposal(raw_response)

    def build_patch_prompt(
        self,
        *,
        cycle_index: int,
        evaluation: Dict[str, Any],
        feedback: Sequence[str],
    ) -> str:
        docs_payload = {path: _read_text(self.daemon_config.repo_root / path, limit=24000) for path in self.daemon_config.docs}
        file_payload = {
            path: _read_text(self.daemon_config.repo_root / path, limit=20000)
            for path in self.daemon_config.target_files
            if (self.daemon_config.repo_root / path).is_file()
        }
        progress_payload = self._progress_snapshot()
        recent_cycle_history = self._recent_cycle_history(limit=3)
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
                "Avoid cosmetic churn, one-line metric gaming, and isolated test-only patches.",
            ],
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
            "Prioritize the unresolved repair-required probes before adding more aliases or bookkeeping. "
            "Return JSON matching required_json_schema and nothing else.\n"
            + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )

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
            "rejected_patch_count": progress.get("rejected_patch_count", 0),
            "current_score": progress.get("current_score"),
            "score_delta": progress.get("score_delta"),
            "current_feedback": progress.get("current_feedback", []),
            "accepted_change_summaries": progress.get("accepted_change_summaries", [])[-8:],
            "stalled_metric_cycles": progress.get("stalled_metric_cycles", 0),
        }

    def _recent_cycle_history(self, *, limit: int = 3) -> List[Dict[str, Any]]:
        cycles_dir = self.daemon_config.resolved_output_dir() / "cycles"
        if not cycles_dir.exists():
            return []
        summaries: List[Dict[str, Any]] = []
        for summary_path in sorted(cycles_dir.glob("cycle_*/cycle_summary.json"), reverse=True)[:limit]:
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
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
            summaries.append(
                {
                    "cycle_index": summary.get("cycle_index"),
                    "score": summary.get("score"),
                    "feedback": summary.get("feedback"),
                    "proposal_summary": proposal_summary,
                    "proposal_requirements": proposal_requirements[:6],
                    "patch_valid": (summary.get("patch_check") or {}).get("valid"),
                    "applied": (summary.get("apply_result") or {}).get("applied"),
                    "rolled_back": (summary.get("apply_result") or {}).get("rolled_back", False),
                    "tests_valid": tests.get("valid"),
                    "test_failure_tail": tests_stdout[-4000:] if not tests.get("valid") else "",
                }
            )
        return summaries

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
        return _run_command(
            list(self.daemon_config.test_command),
            cwd=self.daemon_config.repo_root,
            timeout=self.daemon_config.test_timeout_seconds,
        )


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
        self.optimizer = optimizer or LegalParserParityOptimizer(daemon_config=self.config)
        self._state = self._load_state()
        self._sync_progress_from_existing_cycles()

    async def run(self) -> Dict[str, Any]:
        summaries: List[Dict[str, Any]] = []
        cycles_executed = 0
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

    def run_cycle(self, *, cycle_index: int) -> Dict[str, Any]:
        started = _utc_now()
        cycle_dir = self.cycles_dir / f"cycle_{cycle_index:04d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        self._write_cycle_started(cycle_dir=cycle_dir, cycle_index=cycle_index, started=started)

        context = OptimizationContext(
            session_id=f"legal-parser-daemon-{cycle_index:04d}",
            input_data={},
            domain="legal_parser",
            metadata={"cycle_index": cycle_index},
        )
        evaluation = self.optimizer.generate({}, context)
        score, feedback = self.optimizer.critique(evaluation, context)
        try:
            proposal = self.optimizer.optimize(evaluation, score, feedback, context)
        except Exception as exc:
            proposal = LegalParserCycleProposal(
                summary="llm_router proposal failed",
                raw_response="",
                parse_error=f"{type(exc).__name__}: {exc}",
            )

        proposal_path = cycle_dir / "proposal.json"
        proposal_path.write_text(json.dumps(asdict(proposal), indent=2, default=str), encoding="utf-8")
        patch_path = cycle_dir / "proposal.patch"
        patch_path.write_text(proposal.unified_diff, encoding="utf-8")

        patch_check = self.optimizer.check_patch(proposal.unified_diff)
        changed_files = _paths_from_unified_diff(proposal.unified_diff)
        patch_stats = _unified_diff_stats(proposal.unified_diff)
        proposal_quality = self._assess_proposal_quality(proposal, changed_files)
        if patch_check.get("valid") and not proposal_quality.get("valid"):
            patch_check = {
                **patch_check,
                "valid": False,
                "quality_valid": False,
                "stderr": str(patch_check.get("stderr") or "")
                + ("\n" if patch_check.get("stderr") else "")
                + "; ".join(proposal_quality.get("reasons", [])),
            }
        apply_result: Dict[str, Any] = {"applied": False, "reason": "apply_patches_disabled"}
        tests_result: Dict[str, Any] = {"valid": True, "skipped": True}
        post_evaluation: Dict[str, Any] = {}

        if self.config.apply_patches and patch_check.get("valid"):
            pre_apply_diff = self._working_tree_diff()
            pre_apply_files = self._snapshot_patch_paths(proposal.unified_diff)
            apply_result = self.optimizer.apply_patch(proposal.unified_diff)
            if apply_result.get("applied"):
                tests_result = self.optimizer.run_tests()
                if tests_result.get("valid"):
                    post_evaluation = self.optimizer.evaluate_current_parser()
                else:
                    rollback = self._restore_patch_paths(pre_apply_files)
                    if not rollback.get("valid"):
                        rollback["diff_restore"] = self._restore_working_tree_diff(pre_apply_diff)
                    apply_result["rolled_back"] = True
                    apply_result["rollback"] = rollback
        elif self.config.run_tests and not self.config.apply_patches:
            tests_result = self.optimizer.run_tests()

        finished = _utc_now()
        cycle_payload = {
            "cycle_index": cycle_index,
            "started_at": started,
            "finished_at": finished,
            "duration_seconds": round(_parse_utc(finished) - _parse_utc(started), 3),
            "model_name": self.config.model_name,
            "provider": self.config.provider,
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
            "proposal_quality": proposal_quality,
            "patch_check": patch_check,
            "apply_result": apply_result,
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
        return cycle_payload

    def _write_cycle_started(self, *, cycle_dir: Path, cycle_index: int, started: str) -> None:
        marker = {
            "status": "running",
            "cycle_index": cycle_index,
            "started_at": started,
            "pid": os.getpid(),
            "model_name": self.config.model_name,
            "provider": self.config.provider,
            "apply_patches": self.config.apply_patches,
        }
        (cycle_dir / "cycle_started.json").write_text(
            json.dumps(marker, indent=2, default=str),
            encoding="utf-8",
        )

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
            "model_name": self.config.model_name,
            "provider": self.config.provider,
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
        return cycle_payload

    def _assess_proposal_quality(
        self,
        proposal: LegalParserCycleProposal,
        changed_files: Sequence[str],
    ) -> Dict[str, Any]:
        reasons: List[str] = []
        production_files = _production_files(changed_files)
        test_files = _test_files(changed_files)
        if not proposal.summary.strip():
            reasons.append("proposal summary is empty")
        if not proposal.acceptance_criteria:
            reasons.append("proposal omitted acceptance_criteria")
        if self.config.require_production_and_tests:
            if not production_files:
                reasons.append("patch must touch at least one production deontic parser/export file")
            if not test_files:
                reasons.append("patch must touch at least one deontic parser test file")
        return {
            "valid": not reasons,
            "reasons": reasons,
            "declared_changed_files": list(proposal.changed_files),
            "changed_files": list(changed_files),
            "production_files": production_files,
            "test_files": test_files,
        }

    def _record_progress(self, cycle_payload: Dict[str, Any]) -> None:
        accepted = _cycle_was_kept(cycle_payload)
        if accepted:
            self._append_accepted_change(cycle_payload)
        progress = self._build_progress_summary(latest_cycle=cycle_payload)
        progress_path = self.output_dir / "progress_summary.json"
        progress_path.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")

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

        accepted_cycles = [cycle for cycle in cycles if _cycle_was_kept(cycle)]
        rolled_back = [
            cycle for cycle in cycles if (cycle.get("apply_result") or {}).get("rolled_back", False)
        ]
        rejected = [
            cycle
            for cycle in cycles
            if not (cycle.get("patch_check") or {}).get("valid")
            or not (cycle.get("proposal_quality") or {"valid": True}).get("valid", True)
        ]
        first_score = None
        for cycle in cycles:
            score = cycle.get("score")
            if isinstance(score, (int, float)):
                first_score = float(score)
                break
        current_metrics = latest_cycle.get("metrics", {})
        post_metrics = (latest_cycle.get("post_evaluation") or {}).get("metrics") or {}
        current_score = post_metrics.get("parity_score", current_metrics.get("parity_score"))
        current_feedback = current_metrics.get("coverage_gaps", latest_cycle.get("feedback", []))

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

        unchanged_tail = 0
        for cycle in reversed(cycles):
            score = cycle.get("score")
            if score == current_score:
                unchanged_tail += 1
            else:
                break
        return {
            "updated_at": _utc_now(),
            "total_cycles": len(cycles),
            "latest_cycle_index": latest_cycle.get("cycle_index"),
            "accepted_patch_count": len(accepted_cycles),
            "rolled_back_count": len(rolled_back),
            "rejected_patch_count": len(rejected),
            "current_score": current_score,
            "initial_score": first_score,
            "score_delta": (
                round(float(current_score) - float(first_score), 6)
                if isinstance(current_score, (int, float)) and isinstance(first_score, float)
                else None
            ),
            "current_feedback": current_feedback,
            "stalled_metric_cycles": unchanged_tail,
            "accepted_change_summaries": accepted_summaries,
            "latest_cycle": {
                "cycle_index": latest_cycle.get("cycle_index"),
                "status": latest_cycle.get("status", "ok"),
                "changed_files": latest_cycle.get("changed_files", []),
                "patch_valid": (latest_cycle.get("patch_check") or {}).get("valid"),
                "proposal_quality": latest_cycle.get("proposal_quality", {}),
                "applied": (latest_cycle.get("apply_result") or {}).get("applied"),
                "rolled_back": (latest_cycle.get("apply_result") or {}).get("rolled_back", False),
                "tests_valid": (latest_cycle.get("tests") or {}).get("valid"),
            },
        }

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
    return bool(
        apply_result.get("applied")
        and not apply_result.get("rolled_back", False)
        and tests.get("valid") is True
    )


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
    parser.add_argument("--provider", default=os.environ.get("LEGAL_PARSER_DAEMON_PROVIDER", "codex_cli"))
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--cycle-interval-seconds", type=float, default=0.0)
    parser.add_argument("--error-backoff-seconds", type=float, default=30.0)
    parser.add_argument("--llm-timeout-seconds", type=int, default=900)
    parser.add_argument("--test-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--allow-patches-without-tests",
        action="store_true",
        help="Do not reject valid patches that lack a deontic test-file change.",
    )
    parser.add_argument("--target-score", type=float, default=0.98)
    parser.add_argument("--apply-patches", action="store_true", help="Apply LLM-generated patches after git apply --check.")
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
        provider=str(args.provider),
        max_cycles=int(args.max_cycles),
        cycle_interval_seconds=float(args.cycle_interval_seconds),
        error_backoff_seconds=float(args.error_backoff_seconds),
        llm_timeout_seconds=int(args.llm_timeout_seconds),
        test_timeout_seconds=int(args.test_timeout_seconds),
        require_production_and_tests=not bool(args.allow_patches_without_tests),
        target_score=float(args.target_score),
        apply_patches=bool(args.apply_patches),
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
