"""Comprehensive daemon for Bluebook-driven legal scraper maintenance.

This daemon coordinates the legal-data system's major self-healing loops:

- Bluebook citation fuzzing and source recovery
- State-law corpus refresh and canonical parquet publication
- Agentic state corpus scraper cycles for laws, admin rules, and court rules

It is intentionally conservative. Hugging Face publication and live search are
opt-in so operators can run local audits without accidentally spending search
quota or publishing incomplete corpora.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence


STATE_CODES_50: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

SUPPORTED_CORPORA = ("state_laws", "state_admin_rules", "state_court_rules")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_states(value: str | Sequence[str] | None, *, include_dc: bool = False) -> List[str]:
    if value is None:
        raw_items = ["all"]
    elif isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()] or ["all"]
    else:
        raw_items = [str(item).strip() for item in value if str(item).strip()] or ["all"]

    if any(item.lower() == "all" for item in raw_items):
        states = list(STATE_CODES_50)
        if include_dc:
            states.append("DC")
        return states

    states: List[str] = []
    valid = set(STATE_CODES_50)
    if include_dc:
        valid.add("DC")
    for item in raw_items:
        state = item.upper()
        if state not in valid:
            raise ValueError(f"Unknown or disabled state code: {state}")
        if state not in states:
            states.append(state)
    return states


def _normalize_corpora(value: str | Sequence[str] | None) -> List[str]:
    aliases = {
        "all": list(SUPPORTED_CORPORA),
        "laws": ["state_laws"],
        "state": ["state_laws"],
        "admin": ["state_admin_rules"],
        "rules": ["state_admin_rules"],
        "court": ["state_court_rules"],
        "procedure": ["state_court_rules"],
        "procedural": ["state_court_rules"],
    }
    if value is None:
        raw_items = ["all"]
    elif isinstance(value, str):
        raw_items = [item.strip().lower() for item in value.split(",") if item.strip()] or ["all"]
    else:
        raw_items = [str(item).strip().lower() for item in value if str(item).strip()] or ["all"]

    corpora: List[str] = []
    for item in raw_items:
        expanded = aliases.get(item, [item])
        for corpus in expanded:
            if corpus not in SUPPORTED_CORPORA:
                raise ValueError(f"Unsupported corpus: {corpus}")
            if corpus not in corpora:
                corpora.append(corpus)
    return corpora


@dataclass
class BluebookDaemonConfig:
    enabled: bool = True
    samples: int = 50
    corpora: List[str] = field(default_factory=lambda: ["state_laws"])
    seed_from_corpora: bool = False
    seed_only: bool = False
    allow_hf_fallback: bool = True
    exhaustive: bool = False
    enable_recovery: bool = True
    recovery_max_candidates: int = 4
    recovery_archive_top_k: int = 0
    publish_to_hf: bool = False
    merge_recovered_rows: bool = False
    skip_live_search: bool = True
    max_acceptable_failure_rate: float = 0.05
    min_actionable_failures: int = 1


@dataclass
class StateRefreshDaemonConfig:
    enabled: bool = True
    scrape: bool = False
    merge_hf_existing: bool = False
    publish_to_hf: bool = False
    verify_publish: bool = False
    allow_incomplete_publish: bool = False
    max_statutes: int = 0
    rate_limit_delay: float = 1.0
    parallel_workers: int = 4
    per_state_timeout_seconds: float = 900.0
    per_state_retry_attempts: int = 1
    strict_full_text: bool = False
    hydrate_statute_text: bool = True


@dataclass
class AgenticCorpusDaemonConfig:
    enabled: bool = False
    corpora: List[str] = field(default_factory=lambda: list(SUPPORTED_CORPORA))
    max_cycles: int = 1
    cycle_interval_seconds: float = 900.0
    max_statutes: int = 0
    target_score: float = 0.92
    stop_on_target_score: bool = False
    per_state_timeout_seconds: float = 86400.0
    scrape_timeout_seconds: float = 0.0


@dataclass
class LegalScraperDaemonConfig:
    states: List[str] = field(default_factory=lambda: list(STATE_CODES_50))
    include_dc: bool = False
    output_dir: str = str(Path.home() / ".ipfs_datasets" / "legal_scraper_daemon")
    cycle_interval_seconds: float = 3600.0
    max_cycles: int = 1
    dry_run: bool = False
    hf_token: Optional[str] = None
    bluebook: BluebookDaemonConfig = field(default_factory=BluebookDaemonConfig)
    state_refresh: StateRefreshDaemonConfig = field(default_factory=StateRefreshDaemonConfig)
    agentic_corpora: AgenticCorpusDaemonConfig = field(default_factory=AgenticCorpusDaemonConfig)


BluebookRunner = Callable[..., Awaitable[Any]]
StateRefreshRunner = Callable[[argparse.Namespace], Awaitable[Dict[str, Any]]]
AgenticRunner = Callable[..., Awaitable[Dict[str, Any]]]


def _load_refresh_state_laws_module() -> Any:
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "ops" / "legal_data" / "refresh_state_laws_corpus.py"
    spec = importlib.util.spec_from_file_location("refresh_state_laws_corpus", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load refresh_state_laws_corpus from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bluebook_run_to_dict(run: Any) -> Dict[str, Any]:
    if hasattr(run, "to_dict") and callable(run.to_dict):
        return dict(run.to_dict())
    if isinstance(run, dict):
        return dict(run)
    return {"status": "completed", "result": str(run)}


class LegalScraperDaemon:
    """Coordinate legal scraper self-healing and publication phases."""

    def __init__(
        self,
        config: Optional[LegalScraperDaemonConfig] = None,
        *,
        bluebook_runner: Optional[BluebookRunner] = None,
        state_refresh_runner: Optional[StateRefreshRunner] = None,
        agentic_runner: Optional[AgenticRunner] = None,
    ) -> None:
        self.config = config or LegalScraperDaemonConfig()
        self.states = _normalize_states(self.config.states, include_dc=self.config.include_dc)
        self.output_dir = Path(self.config.output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cycles_dir = self.output_dir / "cycles"
        self.cycles_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output_dir / "daemon_state.json"
        self.latest_path = self.output_dir / "latest_cycle.json"
        self.bluebook_runner = bluebook_runner
        self.state_refresh_runner = state_refresh_runner
        self.agentic_runner = agentic_runner

    def build_plan(self) -> Dict[str, Any]:
        return {
            "states": list(self.states),
            "state_count": len(self.states),
            "output_dir": str(self.output_dir),
            "dry_run": bool(self.config.dry_run),
            "phases": {
                "bluebook": asdict(self.config.bluebook),
                "state_refresh": asdict(self.config.state_refresh),
                "agentic_corpora": asdict(self.config.agentic_corpora),
            },
        }

    async def run(self) -> Dict[str, Any]:
        cycles: List[Dict[str, Any]] = []
        max_cycles = max(1, int(self.config.max_cycles or 1))
        for cycle_index in range(1, max_cycles + 1):
            cycle = await self.run_cycle(cycle_index=cycle_index)
            cycles.append(cycle)
            if cycle_index < max_cycles:
                await asyncio.sleep(max(0.0, float(self.config.cycle_interval_seconds or 0.0)))
        summary = {
            "status": "completed",
            "started_at": cycles[0]["started_at"] if cycles else _utc_now(),
            "finished_at": _utc_now(),
            "cycle_count": len(cycles),
            "latest_cycle_path": str(self.latest_path),
            "cycles": cycles,
        }
        self.state_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        return summary

    async def run_cycle(self, *, cycle_index: int) -> Dict[str, Any]:
        cycle_dir = self.cycles_dir / f"cycle_{cycle_index:04d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        cycle = {
            "cycle": cycle_index,
            "started_at": _utc_now(),
            "states": list(self.states),
            "status": "running",
            "plan": self.build_plan(),
            "phases": {},
        }
        self._write_cycle(cycle)

        if self.config.dry_run:
            cycle["status"] = "dry_run"
            cycle["finished_at"] = _utc_now()
            self._write_cycle(cycle)
            return cycle

        if self.config.bluebook.enabled:
            cycle["phases"]["bluebook"] = await self._run_bluebook_phase(cycle_dir)
            self._write_cycle(cycle)

        if self.config.state_refresh.enabled:
            cycle["phases"]["state_refresh"] = await self._run_state_refresh_phase(cycle_dir)
            self._write_cycle(cycle)

        if self.config.agentic_corpora.enabled:
            cycle["phases"]["agentic_corpora"] = await self._run_agentic_corpora_phase(cycle_dir)
            self._write_cycle(cycle)

        cycle["status"] = self._cycle_status(cycle["phases"])
        cycle["finished_at"] = _utc_now()
        self._write_cycle(cycle)
        return cycle

    def _write_cycle(self, cycle: Dict[str, Any]) -> None:
        cycle_index = int(cycle.get("cycle") or 0)
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}.json"
        cycle_path.write_text(json.dumps(cycle, indent=2, sort_keys=True, default=str), encoding="utf-8")
        self.latest_path.write_text(json.dumps(cycle, indent=2, sort_keys=True, default=str), encoding="utf-8")

    @staticmethod
    def _cycle_status(phases: Dict[str, Any]) -> str:
        statuses = [str((phase or {}).get("status") or "").lower() for phase in phases.values() if isinstance(phase, dict)]
        if any(status == "error" for status in statuses):
            return "error"
        if any(status == "partial_success" for status in statuses):
            return "partial_success"
        return "success"

    async def _run_bluebook_phase(self, cycle_dir: Path) -> Dict[str, Any]:
        config = self.config.bluebook
        output_dir = cycle_dir / "bluebook_fuzz"
        if self.bluebook_runner is not None:
            runner = self.bluebook_runner
        else:
            from ipfs_datasets_py.processors.legal_data.bluebook_linker_fuzz_harness import (
                run_bluebook_linker_fuzz_harness,
            )

            runner = run_bluebook_linker_fuzz_harness

        if config.skip_live_search:
            import os

            os.environ["LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH"] = "1"

        try:
            run = await runner(
                sample_count=max(1, int(config.samples)),
                corpus_keys=list(config.corpora or []),
                state_codes=list(self.states),
                allow_hf_fallback=bool(config.allow_hf_fallback),
                exhaustive=bool(config.exhaustive),
                enable_recovery=bool(config.enable_recovery),
                recovery_max_candidates=max(1, int(config.recovery_max_candidates)),
                recovery_archive_top_k=max(0, int(config.recovery_archive_top_k)),
                publish_to_hf=bool(config.publish_to_hf),
                hf_token=self.config.hf_token,
                merge_recovered_rows=bool(config.merge_recovered_rows),
                seed_from_corpora=bool(config.seed_from_corpora),
                seed_only=bool(config.seed_only),
                max_acceptable_failure_rate=float(config.max_acceptable_failure_rate),
                min_actionable_failures=max(1, int(config.min_actionable_failures)),
                output_dir=output_dir,
            )
            payload = _bluebook_run_to_dict(run)
            summary = dict(payload.get("summary") or {})
            return {
                "status": "success",
                "output_dir": str(output_dir),
                "summary": summary,
                "artifact_path": str(output_dir / "bluebook_linker_fuzz_run.json"),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc), "output_dir": str(output_dir)}

    async def _run_state_refresh_phase(self, cycle_dir: Path) -> Dict[str, Any]:
        config = self.config.state_refresh
        output_root = cycle_dir / "state_laws_refresh"
        if self.state_refresh_runner is not None:
            runner = self.state_refresh_runner
        else:
            module = _load_refresh_state_laws_module()
            runner = module.refresh_state_laws_corpus

        args = SimpleNamespace(
            states=",".join(self.states),
            include_dc=self.config.include_dc,
            output_root=str(output_root),
            jsonld_dir="",
            parquet_dir="",
            scrape=bool(config.scrape),
            max_statutes=int(config.max_statutes or 0),
            rate_limit_delay=float(config.rate_limit_delay),
            parallel_workers=int(config.parallel_workers),
            per_state_retry_attempts=int(config.per_state_retry_attempts),
            per_state_timeout_seconds=float(config.per_state_timeout_seconds),
            strict_full_text=bool(config.strict_full_text),
            min_full_text_chars=300,
            no_hydrate_statute_text=not bool(config.hydrate_statute_text),
            allow_justia_fallback=False,
            no_merge_existing_local=False,
            merge_hf_existing=bool(config.merge_hf_existing),
            publish_to_hf=bool(config.publish_to_hf),
            allow_incomplete_publish=bool(config.allow_incomplete_publish),
            repo_id="justicedao/ipfs_state_laws",
            hf_token=self.config.hf_token or "",
            create_repo=False,
            verify=bool(config.verify_publish),
            commit_message="Refresh canonical state laws corpus from legal scraper daemon",
            dry_run=False,
            json=True,
        )
        try:
            result = await runner(args)
            return dict(result)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "output_root": str(output_root)}

    async def _run_agentic_corpora_phase(self, cycle_dir: Path) -> Dict[str, Any]:
        config = self.config.agentic_corpora
        corpora = _normalize_corpora(config.corpora)
        results: Dict[str, Any] = {}
        for corpus in corpora:
            results[corpus] = await self._run_agentic_corpus(corpus=corpus, cycle_dir=cycle_dir)
        status = "success"
        if any(str((value or {}).get("status") or "").lower() == "error" for value in results.values() if isinstance(value, dict)):
            status = "error"
        elif any(str((value or {}).get("status") or "").lower() == "partial_success" for value in results.values() if isinstance(value, dict)):
            status = "partial_success"
        return {"status": status, "corpora": results}

    async def _run_agentic_corpus(self, *, corpus: str, cycle_dir: Path) -> Dict[str, Any]:
        config = self.config.agentic_corpora
        output_dir = cycle_dir / "agentic_corpora" / corpus
        output_dir.mkdir(parents=True, exist_ok=True)
        if self.agentic_runner is not None:
            return await self.agentic_runner(corpus=corpus, states=list(self.states), output_dir=str(output_dir))
        try:
            from ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon import (
                StateLawsAgenticDaemon,
                StateLawsAgenticDaemonConfig,
            )

            daemon = StateLawsAgenticDaemon(
                StateLawsAgenticDaemonConfig(
                    corpus_key=corpus,
                    states=list(self.states),
                    output_dir=str(output_dir),
                    max_cycles=max(1, int(config.max_cycles)),
                    cycle_interval_seconds=float(config.cycle_interval_seconds),
                    max_statutes=int(config.max_statutes or 0),
                    target_score=float(config.target_score),
                    stop_on_target_score=bool(config.stop_on_target_score),
                    per_state_timeout_seconds=float(config.per_state_timeout_seconds),
                    scrape_timeout_seconds=float(config.scrape_timeout_seconds),
                )
            )
            summary = await daemon.run()
            return {"status": "success", "output_dir": str(output_dir), "summary": summary}
        except Exception as exc:
            return {"status": "error", "error": str(exc), "output_dir": str(output_dir)}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the comprehensive legal scraper daemon")
    parser.add_argument("--states", default="all")
    parser.add_argument("--include-dc", action="store_true")
    parser.add_argument("--output-dir", default=str(Path.home() / ".ipfs_datasets" / "legal_scraper_daemon"))
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--cycle-interval-seconds", type=float, default=3600.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hf-token", default="")

    parser.add_argument("--disable-bluebook", action="store_true")
    parser.add_argument("--bluebook-samples", type=int, default=50)
    parser.add_argument("--bluebook-corpora", default="state_laws")
    parser.add_argument("--bluebook-seed-from-corpora", action="store_true")
    parser.add_argument("--bluebook-seed-only", action="store_true")
    parser.add_argument("--bluebook-publish-to-hf", action="store_true")
    parser.add_argument("--bluebook-live-search", action="store_true")

    parser.add_argument("--disable-state-refresh", action="store_true")
    parser.add_argument("--state-refresh-scrape", action="store_true")
    parser.add_argument("--state-refresh-merge-hf-existing", action="store_true")
    parser.add_argument("--state-refresh-publish-to-hf", action="store_true")
    parser.add_argument("--state-refresh-verify", action="store_true")
    parser.add_argument("--allow-incomplete-publish", action="store_true")
    parser.add_argument("--max-statutes", type=int, default=0)

    parser.add_argument("--enable-agentic-corpora", action="store_true")
    parser.add_argument("--agentic-corpora", default="all")
    parser.add_argument("--agentic-max-cycles", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    return parser


def config_from_args(args: argparse.Namespace) -> LegalScraperDaemonConfig:
    states = _normalize_states(args.states, include_dc=bool(args.include_dc))
    return LegalScraperDaemonConfig(
        states=states,
        include_dc=bool(args.include_dc),
        output_dir=str(args.output_dir),
        cycle_interval_seconds=float(args.cycle_interval_seconds),
        max_cycles=max(1, int(args.max_cycles)),
        dry_run=bool(args.dry_run),
        hf_token=str(args.hf_token or "").strip() or None,
        bluebook=BluebookDaemonConfig(
            enabled=not bool(args.disable_bluebook),
            samples=max(1, int(args.bluebook_samples)),
            corpora=_normalize_corpora(args.bluebook_corpora),
            seed_from_corpora=bool(args.bluebook_seed_from_corpora),
            seed_only=bool(args.bluebook_seed_only),
            publish_to_hf=bool(args.bluebook_publish_to_hf),
            skip_live_search=not bool(args.bluebook_live_search),
        ),
        state_refresh=StateRefreshDaemonConfig(
            enabled=not bool(args.disable_state_refresh),
            scrape=bool(args.state_refresh_scrape),
            merge_hf_existing=bool(args.state_refresh_merge_hf_existing),
            publish_to_hf=bool(args.state_refresh_publish_to_hf),
            verify_publish=bool(args.state_refresh_verify),
            allow_incomplete_publish=bool(args.allow_incomplete_publish),
            max_statutes=max(0, int(args.max_statutes)),
        ),
        agentic_corpora=AgenticCorpusDaemonConfig(
            enabled=bool(args.enable_agentic_corpora),
            corpora=_normalize_corpora(args.agentic_corpora),
            max_cycles=max(1, int(args.agentic_max_cycles)),
            max_statutes=max(0, int(args.max_statutes)),
        ),
    )


async def _main_async(args: argparse.Namespace) -> int:
    daemon = LegalScraperDaemon(config_from_args(args))
    result = await daemon.run()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Status: {result.get('status')}")
        print(f"Cycles: {result.get('cycle_count')}")
        print(f"Latest: {result.get('latest_cycle_path')}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
