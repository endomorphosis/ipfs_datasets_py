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

    async def run(self) -> Dict[str, Any]:
        """Execute optimization rounds and return final summary."""

        actor_pool = self._initial_actors()
        for round_index in range(1, int(self.loop_config.max_rounds) + 1):
            outcomes = await self._evaluate_round(round_index, actor_pool)
            if not outcomes:
                break

            outcomes_sorted = sorted(outcomes, key=lambda item: item.critic_score, reverse=True)
            best = outcomes_sorted[0]
            if self.best_outcome is None or best.critic_score > self.best_outcome.critic_score:
                self.best_outcome = best

            round_payload = {
                "round": round_index,
                "states": self.states,
                "best_actor": best.actor_name,
                "best_score": round(best.critic_score, 4),
                "best_passed": bool(best.passed),
                "outcomes": [asdict(outcome) for outcome in outcomes_sorted],
            }
            self.round_history.append(round_payload)
            (self.run_dir / f"round_{round_index:02d}.json").write_text(
                json.dumps(round_payload, indent=2), encoding="utf-8"
            )

            if best.passed:
                break

            actor_pool = self._mutate_from_best(best)

        final_summary = {
            "run_dir": str(self.run_dir),
            "states": self.states,
            "rounds_executed": len(self.round_history),
            "target_score": self.loop_config.target_score,
            "best": asdict(self.best_outcome) if self.best_outcome else None,
            "converged": bool(self.best_outcome and self.best_outcome.passed),
            "history_files": [f"round_{idx + 1:02d}.json" for idx in range(len(self.round_history))],
        }
        (self.run_dir / "final_summary.json").write_text(json.dumps(final_summary, indent=2), encoding="utf-8")
        return final_summary

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
