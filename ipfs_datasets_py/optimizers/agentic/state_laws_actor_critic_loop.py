"""Actor/critic multi-agent optimization loop for state law scraping.

This module runs iterative state-law scrape trials with multiple actor policies,
scores outcomes using verifier diagnostics, and mutates policies until stopping
criteria are met. It is designed to drive practical scraper/parser hardening
workflows and produce patch-target guidance artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import py_compile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    US_STATES,
    scrape_state_laws,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_verifier import (
    _build_operational_diagnostics,
)


@dataclass
class ActorPolicyConfig:
    """Configuration an actor uses for a scrape/parsing trial."""

    name: str
    parallel_workers: int = 6
    per_state_retry_attempts: int = 1
    rate_limit_delay: float = 1.0
    min_full_text_chars: int = 300
    hydrate_statute_text: bool = True


@dataclass
class TrialOutcome:
    """Result from one actor trial in a given round."""

    round_index: int
    actor_name: str
    config: Dict[str, Any]
    status: str
    critic_score: float
    diagnostics: Dict[str, Any]
    passed: bool
    recommended_patch_targets: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopConfig:
    """Control settings for actor/critic optimization loop."""

    target_score: float = 0.92
    max_rounds: int = 6
    actors_per_round: int = 3
    actor_concurrency: int = 2
    max_statutes: int = 0
    top_n_diagnostics: int = 8
    emit_patch_plan: bool = False
    apply_patch_plan: bool = False
    patch_plan_limit: int = 20
    execute_apply_plan: bool = False
    apply_plan_file: str = ""
    execution_max_tasks: int = 5
    auto_patch: bool = False
    auto_patch_max_tasks: int = 3
    auto_patch_dry_run: bool = True


class StateLawsActorCriticLoop:
    """Run iterative actor/critic optimization for state scraper quality."""

    def __init__(
        self,
        *,
        states: Optional[Sequence[str]] = None,
        loop_config: Optional[LoopConfig] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        selected = [str(s).upper() for s in (states or list(US_STATES.keys())) if str(s).upper() in US_STATES]
        self.states = selected if selected else list(US_STATES.keys())
        self.loop_config = loop_config or LoopConfig()

        root = output_dir or (Path.home() / ".ipfs_datasets" / "state_laws" / "actor_critic_loop")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path(root).expanduser().resolve() / timestamp
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.round_history: List[Dict[str, Any]] = []
        self.best_outcome: Optional[TrialOutcome] = None
        self._all_outcomes: List[TrialOutcome] = []

    async def run(self) -> Dict[str, Any]:
        """Execute optimization rounds and return final summary."""

        actor_pool = self._initial_actors()
        for round_index in range(1, int(self.loop_config.max_rounds) + 1):
            outcomes = await self._evaluate_round(round_index, actor_pool)
            if not outcomes:
                break

            outcomes_sorted = sorted(outcomes, key=lambda item: item.critic_score, reverse=True)
            self._all_outcomes.extend(outcomes_sorted)
            best = outcomes_sorted[0]
            if self.best_outcome is None or best.critic_score > self.best_outcome.critic_score:
                self.best_outcome = best

            patch_plan_file: Optional[str] = None
            patch_plan_top: Optional[List[Dict[str, Any]]] = None
            if bool(self.loop_config.emit_patch_plan):
                round_patch_plan = self._build_patch_plan(outcomes_sorted)
                patch_plan_file = f"round_patch_plan_{round_index:02d}.json"
                (self.run_dir / patch_plan_file).write_text(
                    json.dumps(
                        {
                            "round": round_index,
                            "states": self.states,
                            "generated_at": datetime.now().isoformat(),
                            "patch_plan": round_patch_plan,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                patch_plan_top = round_patch_plan[:5]

            round_payload = {
                "round": round_index,
                "states": self.states,
                "best_actor": best.actor_name,
                "best_score": round(best.critic_score, 4),
                "best_passed": bool(best.passed),
                "outcomes": [asdict(outcome) for outcome in outcomes_sorted],
                "patch_plan_file": patch_plan_file,
                "patch_plan_top": patch_plan_top,
            }
            self.round_history.append(round_payload)
            (self.run_dir / f"round_{round_index:02d}.json").write_text(
                json.dumps(round_payload, indent=2), encoding="utf-8"
            )

            if best.passed:
                break

            actor_pool = self._mutate_from_best(best)

        final_patch_plan_file: Optional[str] = None
        final_patch_plan: List[Dict[str, Any]] = []
        if bool(self.loop_config.emit_patch_plan) or bool(self.loop_config.apply_patch_plan):
            final_patch_plan = self._build_patch_plan(self._all_outcomes)
            final_patch_plan_file = "final_patch_plan.json"
            (self.run_dir / final_patch_plan_file).write_text(
                json.dumps(
                    {
                        "states": self.states,
                        "generated_at": datetime.now().isoformat(),
                        "rounds_executed": len(self.round_history),
                        "patch_plan": final_patch_plan,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        apply_patch_plan_files: Optional[Dict[str, str]] = None
        execution_report_file: Optional[str] = None
        auto_patch_report_file: Optional[str] = None
        if bool(self.loop_config.apply_patch_plan):
            apply_tasks = self._build_apply_patch_tasks(
                final_patch_plan,
                limit=max(1, int(self.loop_config.patch_plan_limit or 1)),
            )
            apply_patch_plan_files = self._write_apply_patch_artifacts(apply_tasks)

        if bool(self.loop_config.execute_apply_plan):
            preferred_plan_file = str(self.loop_config.apply_plan_file or "").strip()
            if preferred_plan_file:
                plan_path = Path(preferred_plan_file).expanduser().resolve()
            elif apply_patch_plan_files and apply_patch_plan_files.get("tasks_jsonl"):
                plan_path = Path(str(apply_patch_plan_files["tasks_jsonl"]))
            else:
                plan_path = self.run_dir / "apply_patch_plan_tasks.jsonl"

            execution_report = self._execute_apply_plan(
                plan_path,
                max_tasks=max(1, int(self.loop_config.execution_max_tasks or 1)),
            )
            execution_report_file = "apply_patch_execution_report.json"
            (self.run_dir / execution_report_file).write_text(
                json.dumps(execution_report, indent=2),
                encoding="utf-8",
            )

            if bool(self.loop_config.auto_patch):
                auto_patch_report = self._run_auto_patch(
                    execution_report,
                    max_tasks=max(1, int(self.loop_config.auto_patch_max_tasks or 1)),
                    dry_run=bool(self.loop_config.auto_patch_dry_run),
                )
                auto_patch_report_file = "auto_patch_report.json"
                (self.run_dir / auto_patch_report_file).write_text(
                    json.dumps(auto_patch_report, indent=2),
                    encoding="utf-8",
                )

        final_summary = {
            "run_dir": str(self.run_dir),
            "states": self.states,
            "rounds_executed": len(self.round_history),
            "target_score": self.loop_config.target_score,
            "best": asdict(self.best_outcome) if self.best_outcome else None,
            "converged": bool(self.best_outcome and self.best_outcome.passed),
            "history_files": [f"round_{idx + 1:02d}.json" for idx in range(len(self.round_history))],
            "patch_plan_file": final_patch_plan_file,
            "apply_patch_plan_files": apply_patch_plan_files,
            "execution_report_file": execution_report_file,
            "auto_patch_report_file": auto_patch_report_file,
        }
        (self.run_dir / "final_summary.json").write_text(json.dumps(final_summary, indent=2), encoding="utf-8")
        return final_summary

    def _build_patch_plan(self, outcomes: List[TrialOutcome]) -> List[Dict[str, Any]]:
        file_scores: Dict[str, float] = {}
        file_reasons: Dict[str, set[str]] = {}
        file_states: Dict[str, set[str]] = {}

        core_files = {
            "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/base_scraper.py",
            "ipfs_datasets_py/processors/legal_scrapers/state_laws_verifier.py",
        }

        for outcome in outcomes:
            score_deficit = max(0.0, 1.0 - float(outcome.critic_score or 0.0))
            diagnostics = outcome.diagnostics or {}
            coverage = diagnostics.get("coverage") or {}
            fetch = diagnostics.get("fetch") or {}
            etl = diagnostics.get("etl_readiness") or {}
            quality = diagnostics.get("quality") or {}

            reason_states: Dict[str, set[str]] = {}

            for state in coverage.get("coverage_gap_states") or []:
                state_code = str(state).upper()
                reason_states.setdefault(state_code, set()).add("coverage_gap")
            for state in fetch.get("no_attempt_states") or []:
                state_code = str(state).upper()
                reason_states.setdefault(state_code, set()).add("fetch_no_attempt")
            for row in fetch.get("weak_states") or []:
                if isinstance(row, dict):
                    state_code = str(row.get("state") or "").upper()
                    if state_code:
                        reason_states.setdefault(state_code, set()).add("fetch_weak")
            for row in quality.get("weak_states") or []:
                if isinstance(row, dict):
                    state_code = str(row.get("state") or "").upper()
                    if state_code:
                        reason_states.setdefault(state_code, set()).add("quality_weak")

            global_reasons: set[str] = set()
            if not bool(etl.get("ready_for_kg_etl")):
                global_reasons.add("etl_not_ready")
            if coverage.get("coverage_gap_states"):
                global_reasons.add("coverage_gaps_present")
            if fetch.get("no_attempt_states"):
                global_reasons.add("no_attempt_states_present")

            candidate_files = set(outcome.recommended_patch_targets or [])
            for state_code, reasons in reason_states.items():
                scraper_file = self._state_code_to_scraper_file(state_code)
                if scraper_file:
                    candidate_files.add(scraper_file)
                    file_states.setdefault(scraper_file, set()).add(state_code)
                    file_reasons.setdefault(scraper_file, set()).update(reasons)

            for file_path in candidate_files:
                file_scores[file_path] = float(file_scores.get(file_path, 0.0) or 0.0) + score_deficit
                file_reasons.setdefault(file_path, set())
                if file_path in core_files:
                    file_reasons[file_path].update(global_reasons)

        ranked = sorted(file_scores.items(), key=lambda item: item[1], reverse=True)
        plan: List[Dict[str, Any]] = []
        for file_path, score in ranked:
            reasons = sorted(file_reasons.get(file_path, set()))
            states = sorted(file_states.get(file_path, set()))
            plan.append(
                {
                    "path": file_path,
                    "priority_score": round(float(score), 4),
                    "reasons": reasons,
                    "states": states,
                }
            )

        return plan

    def _build_apply_patch_tasks(self, patch_plan: List[Dict[str, Any]], *, limit: int = 20) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        top_items = list(patch_plan)[: max(1, int(limit or 1))]

        for idx, item in enumerate(top_items, start=1):
            if not isinstance(item, dict):
                continue

            path = str(item.get("path") or "")
            reasons = list(item.get("reasons") or [])
            states = list(item.get("states") or [])
            priority_score = float(item.get("priority_score", 0.0) or 0.0)

            task = {
                "task_id": f"patch-task-{idx:03d}",
                "path": path,
                "priority_score": round(priority_score, 4),
                "reasons": reasons,
                "states": states,
                "suggested_actions": self._suggest_actions_for_path(path, reasons, states),
            }
            tasks.append(task)

        return tasks

    def _write_apply_patch_artifacts(self, tasks: List[Dict[str, Any]]) -> Dict[str, str]:
        jsonl_file = self.run_dir / "apply_patch_plan_tasks.jsonl"
        md_file = self.run_dir / "apply_patch_plan_todo.md"

        with jsonl_file.open("w", encoding="utf-8") as handle:
            for row in tasks:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        lines: List[str] = [
            "# Apply Patch Plan TODO",
            "",
            f"Generated at: {datetime.now().isoformat()}",
            "",
        ]
        for idx, task in enumerate(tasks, start=1):
            lines.append(f"## {idx}. `{task.get('path', '')}`")
            lines.append(f"- Priority Score: {task.get('priority_score', 0.0)}")
            lines.append(f"- Reasons: {', '.join(task.get('reasons') or [])}")
            states = task.get("states") or []
            lines.append(f"- States: {', '.join(states) if states else 'n/a'}")
            lines.append("- Suggested Actions:")
            for action in task.get("suggested_actions") or []:
                lines.append(f"  - {action}")
            lines.append("")

        md_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return {
            "tasks_jsonl": str(jsonl_file),
            "todo_markdown": str(md_file),
        }

    def _execute_apply_plan(self, tasks_file: Path, *, max_tasks: int = 5) -> Dict[str, Any]:
        tasks = self._load_apply_tasks(tasks_file)
        selected = tasks[: max(1, int(max_tasks or 1))]

        execution_items: List[Dict[str, Any]] = []
        ready_count = 0
        repo_root = Path(__file__).resolve().parents[3]

        for idx, task in enumerate(selected, start=1):
            rel_path = str(task.get("path") or "")
            abs_path = repo_root / rel_path
            exists = abs_path.exists()
            compile_ok = None
            compile_error = None

            if exists and abs_path.suffix == ".py":
                try:
                    py_compile.compile(str(abs_path), doraise=True)
                    compile_ok = True
                except Exception as exc:  # pragma: no cover - defensive
                    compile_ok = False
                    compile_error = str(exc)

            tests = self._suggest_tests_for_path(rel_path)
            next_commands = self._suggest_execution_commands(rel_path, tests)
            status = "ready_for_patch" if exists and (compile_ok in {True, None}) else "blocked"
            if status == "ready_for_patch":
                ready_count += 1

            execution_items.append(
                {
                    "rank": idx,
                    "task_id": str(task.get("task_id") or f"patch-task-{idx:03d}"),
                    "path": rel_path,
                    "abs_path": str(abs_path),
                    "exists": exists,
                    "compile_ok": compile_ok,
                    "compile_error": compile_error,
                    "reasons": list(task.get("reasons") or []),
                    "states": list(task.get("states") or []),
                    "status": status,
                    "suggested_tests": tests,
                    "next_commands": next_commands,
                }
            )

        queue_jsonl = self.run_dir / "apply_patch_execution_queue.jsonl"
        with queue_jsonl.open("w", encoding="utf-8") as handle:
            for item in execution_items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

        return {
            "tasks_file": str(tasks_file),
            "selected_count": len(selected),
            "ready_count": ready_count,
            "blocked_count": max(0, len(selected) - ready_count),
            "execution_queue_jsonl": str(queue_jsonl),
            "items": execution_items,
        }

    @staticmethod
    def _load_apply_tasks(tasks_file: Path) -> List[Dict[str, Any]]:
        if not tasks_file.exists():
            return []
        out: List[Dict[str, Any]] = []
        for line in tasks_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                out.append(payload)
        return out

    @staticmethod
    def _suggest_tests_for_path(path: str) -> List[str]:
        if path.endswith("state_laws_verifier.py"):
            return [
                "tests/unit/legal_scrapers/test_state_laws_verifier_operational.py",
            ]
        if path.endswith("state_laws_scraper.py"):
            return [
                "tests/unit/legal_scrapers/test_state_scraper_jsonld_enrichment.py",
            ]
        if "state_scrapers/" in path:
            return [
                "tests/unit/legal_scrapers/test_state_scraper_jsonld_enrichment.py",
            ]
        return []

    @staticmethod
    def _suggest_execution_commands(path: str, tests: List[str]) -> List[str]:
        commands = [
            f"python -m py_compile {path}",
        ]
        if tests:
            commands.append("python -m pytest -q " + " ".join(tests))
        commands.append(f"git --no-pager diff -- {path}")
        return commands

    def _run_auto_patch(self, execution_report: Dict[str, Any], *, max_tasks: int, dry_run: bool) -> Dict[str, Any]:
        items = list(execution_report.get("items") or [])
        ready_items = [item for item in items if isinstance(item, dict) and item.get("status") == "ready_for_patch"]
        selected = ready_items[: max(1, int(max_tasks or 1))]

        attempts: List[Dict[str, Any]] = []
        applied_count = 0
        skipped_count = 0
        error_count = 0

        for item in selected:
            rel_path = str(item.get("path") or "")
            try:
                result = self._auto_patch_single(rel_path, dry_run=dry_run)
                attempts.append(result)
                if result.get("status") == "applied":
                    applied_count += 1
                elif result.get("status") == "skipped":
                    skipped_count += 1
                else:
                    error_count += 1
            except Exception as exc:  # pragma: no cover - defensive
                attempts.append(
                    {
                        "path": rel_path,
                        "status": "error",
                        "reason": f"auto-patch-exception: {exc}",
                    }
                )
                error_count += 1

        return {
            "dry_run": bool(dry_run),
            "selected_ready_tasks": len(selected),
            "applied_count": applied_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "attempts": attempts,
        }

    def _auto_patch_single(self, rel_path: str, *, dry_run: bool) -> Dict[str, Any]:
        # Guarded strategy registry: only explicit safe transformations are applied.
        strategy = self._resolve_auto_patch_strategy(rel_path)
        if strategy is None:
            return {
                "path": rel_path,
                "status": "skipped",
                "reason": "no-registered-strategy",
            }

        if dry_run:
            return {
                "path": rel_path,
                "status": "skipped",
                "reason": f"dry-run:{strategy}",
            }

        repo_root = Path(__file__).resolve().parents[3]
        abs_path = repo_root / rel_path
        if not abs_path.exists():
            return {
                "path": rel_path,
                "status": "error",
                "reason": "target-file-missing",
            }

        original = abs_path.read_text(encoding="utf-8")
        updated = self._apply_text_strategy(original, strategy)
        if updated == original:
            return {
                "path": rel_path,
                "status": "skipped",
                "reason": "no-op",
            }
        abs_path.write_text(updated, encoding="utf-8")
        return {
            "path": rel_path,
            "status": "applied",
            "reason": strategy,
        }

        return {
            "path": rel_path,
            "status": "skipped",
            "reason": f"unknown-strategy:{strategy}",
        }

    @staticmethod
    def _resolve_auto_patch_strategy(rel_path: str) -> Optional[str]:
        if rel_path.endswith(".py") and "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/" in rel_path:
            return "normalize-wayback-scheme-http"
        if rel_path.endswith(".py") and "ipfs_datasets_py/processors/legal_scrapers/" in rel_path:
            return "normalize-trailing-whitespace"
        return None

    @staticmethod
    def _apply_text_strategy(original: str, strategy: str) -> str:
        if strategy == "normalize-trailing-whitespace":
            normalized_lines = [line.rstrip() for line in original.splitlines()]
            updated = "\n".join(normalized_lines)
            if original.endswith("\n"):
                updated += "\n"
            return updated

        if strategy == "normalize-wayback-scheme-http":
            return original.replace("https://web.archive.org/", "http://web.archive.org/")

        return original

    @staticmethod
    def _suggest_actions_for_path(path: str, reasons: List[str], states: List[str]) -> List[str]:
        actions: List[str] = []
        if "state_scrapers" in path:
            actions.append("Review state-specific link discovery and archival fallback seeds.")
            actions.append("Harden anti-bot/challenge rejection and statute-only extraction filters.")
        if path.endswith("state_laws_scraper.py"):
            actions.append("Tune strict filtering thresholds and retry orchestration for low-coverage states.")
        if path.endswith("base_scraper.py"):
            actions.append("Adjust unified fetch fallback order and provider telemetry on no-attempt states.")
        if path.endswith("state_laws_verifier.py"):
            actions.append("Tighten operational thresholds and ensure diagnostics cover observed failure modes.")

        if "fetch_no_attempt" in reasons:
            actions.append("Add deterministic source URL seeds for states with zero hydration attempts.")
        if "coverage_gap" in reasons:
            actions.append("Add fallback index/source discovery to close coverage gaps.")
        if "quality_weak" in reasons:
            actions.append("Improve semantic quality gating to reject scaffold/nav contamination.")
        if "etl_not_ready" in reasons:
            actions.append("Improve structured extraction completeness for JSON-LD and citation fields.")
        if states:
            actions.append(f"Prioritize validation for states: {', '.join(states)}.")

        if not actions:
            actions.append("Inspect diagnostics and add targeted scraper/parser hardening for this file.")
        return actions

    async def _evaluate_round(self, round_index: int, actor_pool: List[ActorPolicyConfig]) -> List[TrialOutcome]:
        semaphore = asyncio.Semaphore(max(1, int(self.loop_config.actor_concurrency or 1)))

        async def _run_one(actor_cfg: ActorPolicyConfig) -> TrialOutcome:
            async with semaphore:
                return await self._run_actor_trial(round_index, actor_cfg)

        return await asyncio.gather(*[_run_one(cfg) for cfg in actor_pool])

    async def _run_actor_trial(self, round_index: int, actor_cfg: ActorPolicyConfig) -> TrialOutcome:
        result = await scrape_state_laws(
            states=list(self.states),
            output_format="json",
            include_metadata=True,
            strict_full_text=True,
            min_full_text_chars=int(actor_cfg.min_full_text_chars),
            hydrate_statute_text=bool(actor_cfg.hydrate_statute_text),
            parallel_workers=max(1, int(actor_cfg.parallel_workers)),
            per_state_retry_attempts=max(0, int(actor_cfg.per_state_retry_attempts)),
            retry_zero_statute_states=True,
            rate_limit_delay=max(0.0, float(actor_cfg.rate_limit_delay)),
            max_statutes=(int(self.loop_config.max_statutes) if int(self.loop_config.max_statutes) > 0 else None),
            write_jsonld=True,
            use_state_specific_scrapers=True,
        )

        metadata = result.get("metadata") or {}
        diagnostics = _build_operational_diagnostics(metadata, top_n=int(self.loop_config.top_n_diagnostics or 8))
        score = self._critic_score(diagnostics)
        passed = self._is_success(diagnostics, score)
        patch_targets = self._recommend_patch_targets(diagnostics)

        return TrialOutcome(
            round_index=round_index,
            actor_name=actor_cfg.name,
            config=asdict(actor_cfg),
            status=str(result.get("status") or "unknown"),
            critic_score=score,
            diagnostics=diagnostics,
            passed=passed,
            recommended_patch_targets=patch_targets,
            metadata=metadata,
        )

    def _critic_score(self, diagnostics: Dict[str, Any]) -> float:
        coverage = diagnostics.get("coverage") or {}
        fetch = diagnostics.get("fetch") or {}
        etl = diagnostics.get("etl_readiness") or {}
        quality = diagnostics.get("quality") or {}

        targeted = int(coverage.get("states_targeted", 0) or 0)
        nonzero = int(coverage.get("states_with_nonzero_statutes", 0) or 0)
        coverage_score = (float(nonzero) / float(targeted)) if targeted > 0 else 0.0

        full_text_ratio = float(etl.get("full_text_ratio", 0.0) or 0.0)
        jsonld_ratio = float(etl.get("jsonld_ratio", 0.0) or 0.0)
        citation_ratio = float(etl.get("citation_ratio", 0.0) or 0.0)
        etl_score = (0.4 * full_text_ratio) + (0.4 * jsonld_ratio) + (0.2 * citation_ratio)

        fetch_success_ratio = float(fetch.get("success_ratio", 0.0) or 0.0)
        no_attempt_states = list(fetch.get("no_attempt_states") or [])
        no_attempt_penalty = (len(no_attempt_states) / max(1, len(self.states))) * 0.25
        fetch_score = max(0.0, fetch_success_ratio - no_attempt_penalty)

        weak_quality = list((quality.get("weak_states") or []))
        if weak_quality:
            risk_values: List[float] = []
            for row in weak_quality:
                if not isinstance(row, dict):
                    continue
                scaffold = float(row.get("scaffold_ratio", 0.0) or 0.0)
                nav_like = float(row.get("nav_like_ratio", 0.0) or 0.0)
                fallback = float(row.get("fallback_section_ratio", 0.0) or 0.0)
                risk_values.append((0.6 * scaffold) + (0.3 * nav_like) + (0.1 * fallback))
            quality_score = max(0.0, 1.0 - (sum(risk_values) / max(1, len(risk_values))))
        else:
            quality_score = 1.0

        score = (0.40 * coverage_score) + (0.35 * etl_score) + (0.15 * fetch_score) + (0.10 * quality_score)
        if bool(etl.get("ready_for_kg_etl")):
            score += 0.05

        return round(max(0.0, min(1.0, score)), 4)

    def _is_success(self, diagnostics: Dict[str, Any], score: float) -> bool:
        coverage = diagnostics.get("coverage") or {}
        etl = diagnostics.get("etl_readiness") or {}
        fetch = diagnostics.get("fetch") or {}

        coverage_gaps = list(coverage.get("coverage_gap_states") or [])
        no_attempt_states = list(fetch.get("no_attempt_states") or [])

        return bool(
            score >= float(self.loop_config.target_score)
            and bool(etl.get("ready_for_kg_etl"))
            and len(coverage_gaps) == 0
            and len(no_attempt_states) == 0
        )

    def _mutate_from_best(self, best: TrialOutcome) -> List[ActorPolicyConfig]:
        base = ActorPolicyConfig(**best.config)
        diagnostics = best.diagnostics or {}
        fetch = diagnostics.get("fetch") or {}
        etl = diagnostics.get("etl_readiness") or {}
        quality = diagnostics.get("quality") or {}

        has_no_attempt = len(list(fetch.get("no_attempt_states") or [])) > 0
        weak_fetch = len(list(fetch.get("weak_states") or [])) > 0
        weak_quality = len(list(quality.get("weak_states") or [])) > 0
        etl_ready = bool(etl.get("ready_for_kg_etl"))

        candidates: List[ActorPolicyConfig] = []

        def _add(cfg: ActorPolicyConfig) -> None:
            key = (
                cfg.parallel_workers,
                cfg.per_state_retry_attempts,
                round(cfg.rate_limit_delay, 2),
                cfg.min_full_text_chars,
                cfg.hydrate_statute_text,
            )
            seen = {
                (
                    c.parallel_workers,
                    c.per_state_retry_attempts,
                    round(c.rate_limit_delay, 2),
                    c.min_full_text_chars,
                    c.hydrate_statute_text,
                )
                for c in candidates
            }
            if key not in seen:
                candidates.append(cfg)

        # Resilience-focused mutation for fetch/no-attempt failures.
        if has_no_attempt or weak_fetch:
            _add(
                ActorPolicyConfig(
                    name="resilience_retry",
                    parallel_workers=max(2, base.parallel_workers - 1),
                    per_state_retry_attempts=min(6, base.per_state_retry_attempts + 1),
                    rate_limit_delay=min(3.0, base.rate_limit_delay + 0.25),
                    min_full_text_chars=base.min_full_text_chars,
                    hydrate_statute_text=True,
                )
            )

        # Recall-focused mutation when ETL readiness is weak.
        if not etl_ready:
            _add(
                ActorPolicyConfig(
                    name="parser_recall",
                    parallel_workers=base.parallel_workers,
                    per_state_retry_attempts=base.per_state_retry_attempts,
                    rate_limit_delay=base.rate_limit_delay,
                    min_full_text_chars=max(180, base.min_full_text_chars - 40),
                    hydrate_statute_text=True,
                )
            )

        # Precision-focused mutation when quality signals are weak.
        if weak_quality:
            _add(
                ActorPolicyConfig(
                    name="parser_precision",
                    parallel_workers=base.parallel_workers,
                    per_state_retry_attempts=base.per_state_retry_attempts,
                    rate_limit_delay=base.rate_limit_delay,
                    min_full_text_chars=min(500, base.min_full_text_chars + 50),
                    hydrate_statute_text=True,
                )
            )

        # Throughput-oriented exploratory mutation.
        _add(
            ActorPolicyConfig(
                name="throughput_explore",
                parallel_workers=min(16, base.parallel_workers + 2),
                per_state_retry_attempts=max(0, base.per_state_retry_attempts),
                rate_limit_delay=max(0.2, base.rate_limit_delay - 0.2),
                min_full_text_chars=base.min_full_text_chars,
                hydrate_statute_text=base.hydrate_statute_text,
            )
        )

        # Conservative baseline keeps best known settings.
        _add(
            ActorPolicyConfig(
                name="best_baseline",
                parallel_workers=base.parallel_workers,
                per_state_retry_attempts=base.per_state_retry_attempts,
                rate_limit_delay=base.rate_limit_delay,
                min_full_text_chars=base.min_full_text_chars,
                hydrate_statute_text=base.hydrate_statute_text,
            )
        )

        limit = max(1, int(self.loop_config.actors_per_round or 1))
        return candidates[:limit]

    def _initial_actors(self) -> List[ActorPolicyConfig]:
        seeds = [
            ActorPolicyConfig(name="baseline_balanced", parallel_workers=6, per_state_retry_attempts=1, rate_limit_delay=1.0, min_full_text_chars=300),
            ActorPolicyConfig(name="resilience_seed", parallel_workers=4, per_state_retry_attempts=2, rate_limit_delay=1.4, min_full_text_chars=280),
            ActorPolicyConfig(name="throughput_seed", parallel_workers=10, per_state_retry_attempts=1, rate_limit_delay=0.6, min_full_text_chars=320),
        ]
        return seeds[: max(1, int(self.loop_config.actors_per_round or 1))]

    def _recommend_patch_targets(self, diagnostics: Dict[str, Any]) -> List[str]:
        patch_targets: List[str] = [
            "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/base_scraper.py",
            "ipfs_datasets_py/processors/legal_scrapers/state_laws_verifier.py",
        ]

        coverage = diagnostics.get("coverage") or {}
        fetch = diagnostics.get("fetch") or {}
        quality = diagnostics.get("quality") or {}

        state_candidates = set(coverage.get("coverage_gap_states") or [])
        state_candidates.update(fetch.get("no_attempt_states") or [])
        for row in list(fetch.get("weak_states") or []) + list(quality.get("weak_states") or []):
            if isinstance(row, dict):
                state_candidates.add(str(row.get("state") or "").upper())

        for state_code in sorted({code for code in state_candidates if code in US_STATES}):
            scraper_file = self._state_code_to_scraper_file(state_code)
            if scraper_file is not None:
                patch_targets.append(scraper_file)

        # Stable unique order
        seen = set()
        ordered: List[str] = []
        for path in patch_targets:
            if path not in seen:
                ordered.append(path)
                seen.add(path)
        return ordered

    @staticmethod
    def _state_code_to_scraper_file(state_code: str) -> Optional[str]:
        state_name = US_STATES.get(state_code)
        if not state_name:
            return None

        slug = state_name.lower().replace(" ", "_").replace("-", "_")
        if state_code == "DC":
            slug = "district_of_columbia"

        rel = Path("ipfs_datasets_py/processors/legal_scrapers/state_scrapers") / f"{slug}.py"
        abs_path = Path(__file__).resolve().parents[2] / "processors" / "legal_scrapers" / "state_scrapers" / f"{slug}.py"
        if abs_path.exists():
            return str(rel)
        return None


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multi-agent actor/critic loop to optimize state law scraping and KG ETL readiness."
    )
    parser.add_argument(
        "--states",
        type=str,
        default="all",
        help="Comma-separated state codes or 'all'.",
    )
    parser.add_argument("--max-rounds", type=int, default=6, help="Maximum actor/critic rounds.")
    parser.add_argument("--actors-per-round", type=int, default=3, help="How many actor policies per round.")
    parser.add_argument("--actor-concurrency", type=int, default=2, help="Concurrent actor trials per round.")
    parser.add_argument("--target-score", type=float, default=0.92, help="Critic score threshold to converge.")
    parser.add_argument("--max-statutes", type=int, default=0, help="Cap statutes per actor trial (0 = unlimited).")
    parser.add_argument("--top-n-diagnostics", type=int, default=8, help="Top-N weak states tracked in diagnostics.")
    parser.add_argument(
        "--emit-patch-plan",
        action="store_true",
        help="Emit ranked round/final patch-plan artifacts with file priorities and reasons.",
    )
    parser.add_argument(
        "--apply-patch-plan",
        action="store_true",
        help="Emit actionable patch-task artifacts (JSONL + TODO markdown) from final patch plan.",
    )
    parser.add_argument(
        "--patch-plan-limit",
        type=int,
        default=20,
        help="Max number of top-ranked files to include in apply-patch artifacts.",
    )
    parser.add_argument(
        "--execute-apply-plan",
        action="store_true",
        help="Build execution queue/report from apply-patch tasks with precheck results.",
    )
    parser.add_argument(
        "--apply-plan-file",
        type=str,
        default="",
        help="Optional path to an existing apply_patch_plan_tasks.jsonl to execute.",
    )
    parser.add_argument(
        "--execution-max-tasks",
        type=int,
        default=5,
        help="Max tasks to include in execution queue/report when execute mode is enabled.",
    )
    parser.add_argument(
        "--auto-patch",
        action="store_true",
        help="Attempt guarded auto-patching for top ready tasks from execution report.",
    )
    parser.add_argument(
        "--auto-patch-max-tasks",
        type=int,
        default=3,
        help="Max number of ready tasks to attempt in auto-patch mode.",
    )
    parser.add_argument(
        "--auto-patch-no-dry-run",
        action="store_true",
        help="Disable dry-run for auto-patch mode and apply registered transformations.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="",
        help="Optional output directory root for round artifacts.",
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    states: Optional[List[str]]
    if str(args.states).strip().lower() == "all":
        states = None
    else:
        states = [item.strip().upper() for item in str(args.states).split(",") if item.strip()]

    loop = StateLawsActorCriticLoop(
        states=states,
        loop_config=LoopConfig(
            target_score=float(args.target_score),
            max_rounds=max(1, int(args.max_rounds)),
            actors_per_round=max(1, int(args.actors_per_round)),
            actor_concurrency=max(1, int(args.actor_concurrency)),
            max_statutes=max(0, int(args.max_statutes)),
            top_n_diagnostics=max(1, int(args.top_n_diagnostics)),
            emit_patch_plan=bool(args.emit_patch_plan),
            apply_patch_plan=bool(args.apply_patch_plan),
            patch_plan_limit=max(1, int(args.patch_plan_limit)),
            execute_apply_plan=bool(args.execute_apply_plan),
            apply_plan_file=str(args.apply_plan_file or ""),
            execution_max_tasks=max(1, int(args.execution_max_tasks)),
            auto_patch=bool(args.auto_patch),
            auto_patch_max_tasks=max(1, int(args.auto_patch_max_tasks)),
            auto_patch_dry_run=not bool(args.auto_patch_no_dry_run),
        ),
        output_dir=Path(args.output_dir).expanduser().resolve() if str(args.output_dir).strip() else None,
    )

    final_summary = await loop.run()
    print(json.dumps(final_summary, indent=2))

    converged = bool(final_summary.get("converged"))
    return 0 if converged else 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
