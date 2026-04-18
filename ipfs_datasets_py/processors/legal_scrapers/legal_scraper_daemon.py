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
import os
import sys
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


def _decode_json_from_mixed_output(text: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object found")


def _agentic_subprocess_status(*, returncode: Optional[int], summary: Dict[str, Any]) -> str:
    summary_status = str((summary or {}).get("status") or "").lower()
    latest_cycle_status = str((((summary or {}).get("latest_cycle") or {}) or {}).get("status") or "").lower()
    if int(returncode or 0) != 0:
        return "error"
    if summary_status in {"error", "partial_success"}:
        return "error"
    if latest_cycle_status in {"error", "partial_success"}:
        return "error"
    return "success"


@dataclass
class BluebookDaemonConfig:
    enabled: bool = True
    samples: int = 50
    corpora: List[str] = field(default_factory=lambda: ["state_laws"])
    seed_from_corpora: bool = False
    seed_only: bool = False
    seed_examples_per_corpus: int = 2
    max_seed_examples_per_state: int = 0
    max_seed_examples_per_source: int = 0
    sampling_shuffle_seed: int = 0
    allow_hf_fallback: bool = True
    prefer_hf_corpora: bool = False
    primary_corpora_only: bool = False
    exact_state_partitions_only: bool = False
    materialize_hf_corpora: bool = False
    exhaustive: bool = False
    enable_recovery: bool = True
    recovery_max_candidates: int = 4
    recovery_archive_top_k: int = 0
    publish_to_hf: bool = False
    merge_recovered_rows: bool = False
    hydrate_merge_from_hf: bool = False
    publish_merged_parquet_to_hf: bool = False
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
    hydrate_timeout_seconds: float = 25.0


@dataclass
class AgenticCorpusDaemonConfig:
    enabled: bool = False
    corpora: List[str] = field(default_factory=lambda: list(SUPPORTED_CORPORA))
    max_cycles: int = 1
    cycle_interval_seconds: float = 900.0
    max_statutes: int = 0
    archive_warmup_urls: int = 0
    target_score: float = 0.92
    stop_on_target_score: bool = False
    per_state_timeout_seconds: float = 86400.0
    scrape_timeout_seconds: float = 0.0
    admin_agentic_max_candidates_per_state: int = 1000
    admin_agentic_max_fetch_per_state: int = 1000
    admin_agentic_max_results_per_domain: int = 1000
    admin_agentic_max_hops: int = 4
    admin_agentic_max_pages: int = 1000
    admin_parallel_assist_enabled: bool = True
    admin_parallel_assist_state_limit: int = 6
    admin_parallel_assist_max_urls_per_domain: int = 20
    admin_parallel_assist_timeout_seconds: float = 86400.0


@dataclass
class CacheDaemonConfig:
    enabled: bool = True
    fetch_cache_enabled: bool = True
    search_cache_enabled: bool = True
    cache_dir: str = ""
    mirror_to_ipfs: bool = False


@dataclass
class LegalScraperDaemonConfig:
    full_corpus: bool = False
    states: List[str] = field(default_factory=lambda: list(STATE_CODES_50))
    include_dc: bool = False
    output_dir: str = str(Path.home() / ".ipfs_datasets" / "legal_scraper_daemon")
    cycle_interval_seconds: float = 3600.0
    max_cycles: int = 1
    dry_run: bool = False
    resume: bool = True
    hf_token: Optional[str] = None
    cache: CacheDaemonConfig = field(default_factory=CacheDaemonConfig)
    bluebook: BluebookDaemonConfig = field(default_factory=BluebookDaemonConfig)
    state_refresh: StateRefreshDaemonConfig = field(default_factory=StateRefreshDaemonConfig)
    agentic_corpora: AgenticCorpusDaemonConfig = field(default_factory=AgenticCorpusDaemonConfig)


BluebookRunner = Callable[..., Awaitable[Any]]
StateRefreshRunner = Callable[[argparse.Namespace], Awaitable[Dict[str, Any]]]
AgenticRunner = Callable[..., Awaitable[Dict[str, Any]]]


def _load_refresh_state_laws_module() -> Any:
    package_root = Path(__file__).resolve().parents[3]
    outer_root = Path(__file__).resolve().parents[4]
    script_path = package_root / "scripts" / "ops" / "legal_data" / "refresh_state_laws_corpus.py"
    if not script_path.exists():
        script_path = outer_root / "scripts" / "ops" / "legal_data" / "refresh_state_laws_corpus.py"
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
        self.configure_cache_environment()

    def build_plan(self) -> Dict[str, Any]:
        return {
            "states": list(self.states),
            "state_count": len(self.states),
            "full_corpus": bool(self.config.full_corpus),
            "output_dir": str(self.output_dir),
            "dry_run": bool(self.config.dry_run),
            "resume": bool(self.config.resume),
            "cache": self.cache_plan(),
            "preflight": self.build_preflight_report(),
            "target_manifest": self.build_target_manifest(),
            "phases": {
                "bluebook": asdict(self.config.bluebook),
                "state_refresh": asdict(self.config.state_refresh),
                "agentic_corpora": asdict(self.config.agentic_corpora),
            },
        }

    def build_preflight_payload(self) -> Dict[str, Any]:
        plan = self.build_plan()
        preflight = plan.get("preflight") if isinstance(plan.get("preflight"), dict) else {}
        target_manifest = plan.get("target_manifest") if isinstance(plan.get("target_manifest"), dict) else {}
        status = str(preflight.get("status") or "unknown")
        payload = {
            "status": status,
            "generated_at": _utc_now(),
            "output_dir": str(self.output_dir),
            "plan": plan,
            "preflight": preflight,
            "target_manifest": target_manifest,
        }
        payload["preflight_path"] = str(self.output_dir / "preflight_plan.json")
        payload["target_manifest_path"] = str(self.output_dir / "target_manifest.json")
        return payload

    def write_preflight_artifacts(self) -> Dict[str, Any]:
        payload = self.build_preflight_payload()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        preflight_path = Path(str(payload["preflight_path"]))
        target_manifest_path = Path(str(payload["target_manifest_path"]))
        preflight_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        target_manifest_path.write_text(
            json.dumps(payload.get("target_manifest") or {}, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return payload

    def build_preflight_report(self) -> Dict[str, Any]:
        """Build cheap local checks that predict whether a full-corpus run can cover every target."""
        try:
            from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import get_canonical_legal_corpus
            from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import StateScraperRegistry

            registered_states = sorted(str(item).upper() for item in StateScraperRegistry.get_all_registered_states())
            state_registry_error = ""
        except Exception as exc:
            get_canonical_legal_corpus = None  # type: ignore[assignment]
            registered_states = []
            state_registry_error = str(exc)

        missing_state_scrapers = [
            state for state in self.states if registered_states and state not in set(registered_states)
        ]
        extra_registered_states = [
            state for state in registered_states if state not in set(self.states)
        ]

        hf_datasets: Dict[str, str] = {}
        if get_canonical_legal_corpus is not None:
            for corpus in SUPPORTED_CORPORA:
                try:
                    hf_datasets[corpus] = get_canonical_legal_corpus(corpus).hf_dataset_id
                except Exception:
                    hf_datasets[corpus] = ""

        invariants = {
            "all_supported_corpora_requested": set(self.config.agentic_corpora.corpora or []) >= set(SUPPORTED_CORPORA)
            and set(self.config.bluebook.corpora or []) >= set(SUPPORTED_CORPORA),
            "state_refresh_scrape_enabled": bool(self.config.state_refresh.scrape),
            "state_refresh_unbounded": int(self.config.state_refresh.max_statutes or 0) == 0,
            "state_refresh_hf_merge_enabled": bool(self.config.state_refresh.merge_hf_existing),
            "agentic_corpora_enabled": bool(self.config.agentic_corpora.enabled),
            "agentic_corpora_unbounded": int(self.config.agentic_corpora.max_statutes or 0) == 0,
            "publication_opt_in": not bool(self.config.state_refresh.publish_to_hf)
            and not bool(self.config.bluebook.publish_to_hf)
            and not bool(self.config.bluebook.publish_merged_parquet_to_hf),
        }
        blocking_invariants = {
            key: value
            for key, value in invariants.items()
            if key != "publication_opt_in" and not bool(value)
        }
        status = "ready"
        if state_registry_error or missing_state_scrapers or blocking_invariants:
            status = "blocked"
        elif extra_registered_states:
            status = "partial"

        return {
            "status": status,
            "full_corpus": bool(self.config.full_corpus),
            "target_state_count": len(self.states),
            "registered_state_count": len(registered_states),
            "registered_states": registered_states,
            "missing_state_scrapers": missing_state_scrapers,
            "extra_registered_states_not_targeted": extra_registered_states,
            "state_registry_error": state_registry_error,
            "supported_corpora": list(SUPPORTED_CORPORA),
            "hf_datasets": hf_datasets,
            "invariants": invariants,
            "blocking_invariants": blocking_invariants,
        }

    def build_target_manifest(self) -> Dict[str, Any]:
        """Describe every corpus/state artifact a full-corpus run is expected to retrieve."""
        try:
            from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import get_canonical_legal_corpus
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "states": list(self.states),
                "corpora": {},
            }

        corpora: Dict[str, Any] = {}
        for corpus_key in SUPPORTED_CORPORA:
            try:
                corpus = get_canonical_legal_corpus(corpus_key)
            except Exception as exc:
                corpora[corpus_key] = {"status": "error", "error": str(exc), "state_shards": []}
                continue
            parquet_prefix = corpus.parquet_dir_name.strip("/")
            jsonld_prefix = corpus.jsonld_dir_name.strip("/")
            state_shards = []
            for state in self.states:
                state_parquet = corpus.state_parquet_filename(state)
                state_shards.append(
                    {
                        "state": state,
                        "hf_parquet_path": f"{parquet_prefix}/{state_parquet}" if parquet_prefix else state_parquet,
                        "jsonld_filename": f"STATE-{state}.jsonld",
                        "jsonld_path": f"{jsonld_prefix}/STATE-{state}.jsonld" if jsonld_prefix else f"STATE-{state}.jsonld",
                        "parquet_filename": state_parquet,
                    }
                )
            corpora[corpus_key] = {
                "status": "planned",
                "hf_dataset_id": corpus.hf_dataset_id,
                "parquet_dir": corpus.parquet_dir_name,
                "jsonld_dir": corpus.jsonld_dir_name,
                "combined_parquet_path": corpus.combined_parquet_path(),
                "combined_embeddings_path": corpus.combined_embeddings_path(),
                "state_shard_count": len(state_shards),
                "state_shards": state_shards,
            }

        return {
            "status": "planned",
            "states": list(self.states),
            "state_count": len(self.states),
            "corpora": corpora,
            "corpus_count": len(corpora),
            "state_shard_count": sum(int((entry or {}).get("state_shard_count", 0) or 0) for entry in corpora.values()),
            "combined_artifact_count": len(corpora),
        }

    def cache_plan(self) -> Dict[str, Any]:
        config = self.config.cache
        cache_root = self._cache_root()
        return {
            **asdict(config),
            "cache_dir": str(cache_root),
            "fetch_cache_dir": str(cache_root / "fetch"),
            "search_cache_dir": str(cache_root / "search"),
        }

    def _cache_root(self) -> Path:
        configured = str(self.config.cache.cache_dir or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return self.output_dir / "cache"

    def configure_cache_environment(self) -> Dict[str, str]:
        config = self.config.cache
        cache_root = self._cache_root()
        fetch_dir = cache_root / "fetch"
        search_dir = cache_root / "search"
        cache_root.mkdir(parents=True, exist_ok=True)
        if config.fetch_cache_enabled:
            fetch_dir.mkdir(parents=True, exist_ok=True)
        if config.search_cache_enabled:
            search_dir.mkdir(parents=True, exist_ok=True)

        bool_text = lambda value: "1" if value else "0"
        env = {
            "IPFS_DATASETS_LEGAL_FETCH_CACHE_ENABLED": bool_text(config.enabled and config.fetch_cache_enabled),
            "LEGAL_SCRAPER_FETCH_CACHE_ENABLED": bool_text(config.enabled and config.fetch_cache_enabled),
            "IPFS_DATASETS_LEGAL_FETCH_CACHE_DIR": str(fetch_dir),
            "LEGAL_SCRAPER_FETCH_CACHE_DIR": str(fetch_dir),
            "IPFS_DATASETS_LEGAL_FETCH_CACHE_IPFS_MIRROR": bool_text(config.enabled and config.mirror_to_ipfs),
            "LEGAL_SCRAPER_FETCH_CACHE_IPFS_MIRROR": bool_text(config.enabled and config.mirror_to_ipfs),
            "IPFS_DATASETS_SEARCH_CACHE_ENABLED": bool_text(config.enabled and config.search_cache_enabled),
            "LEGAL_SCRAPER_SEARCH_CACHE_ENABLED": bool_text(config.enabled and config.search_cache_enabled),
            "IPFS_DATASETS_SEARCH_CACHE_DIR": str(search_dir),
            "LEGAL_SCRAPER_SEARCH_CACHE_DIR": str(search_dir),
            "IPFS_DATASETS_SEARCH_CACHE_IPFS_MIRROR": bool_text(config.enabled and config.mirror_to_ipfs),
            "LEGAL_SCRAPER_SEARCH_CACHE_IPFS_MIRROR": bool_text(config.enabled and config.mirror_to_ipfs),
        }
        os.environ.update(env)
        return env

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
            cycle["phases"]["bluebook"] = await self._run_or_resume_phase(
                "bluebook",
                cycle_dir,
                lambda: self._run_bluebook_phase(cycle_dir),
            )
            self._write_cycle(cycle)

        if self.config.state_refresh.enabled:
            cycle["phases"]["state_refresh"] = await self._run_or_resume_phase(
                "state_refresh",
                cycle_dir,
                lambda: self._run_state_refresh_phase(cycle_dir),
            )
            self._write_cycle(cycle)

        if self.config.agentic_corpora.enabled:
            cycle["phases"]["agentic_corpora"] = await self._run_or_resume_phase(
                "agentic_corpora",
                cycle_dir,
                lambda: self._run_agentic_corpora_phase(cycle_dir),
            )
            self._write_cycle(cycle)

        if self.config.full_corpus:
            cycle["corpus_completeness"] = self._full_corpus_completeness(cycle["phases"])

        cycle["status"] = self._cycle_status(cycle["phases"], cycle.get("corpus_completeness"))
        cycle["finished_at"] = _utc_now()
        self._write_cycle(cycle)
        return cycle

    def _write_cycle(self, cycle: Dict[str, Any]) -> None:
        cycle_index = int(cycle.get("cycle") or 0)
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}.json"
        cycle_path.write_text(json.dumps(cycle, indent=2, sort_keys=True, default=str), encoding="utf-8")
        self.latest_path.write_text(json.dumps(cycle, indent=2, sort_keys=True, default=str), encoding="utf-8")

    def _phase_path(self, cycle_dir: Path, phase_name: str) -> Path:
        return cycle_dir / f"{phase_name}_phase.json"

    def _load_resumable_phase(self, cycle_dir: Path, phase_name: str) -> Optional[Dict[str, Any]]:
        if not self.config.resume:
            return None
        path = self._phase_path(cycle_dir, phase_name)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        status = str(payload.get("status") or "").lower()
        if status in {"", "running", "error"}:
            return None
        if payload.get("_resume_context") != self._phase_resume_context(phase_name):
            return None
        payload = dict(payload)
        payload["resumed_from"] = str(path)
        return payload

    def _write_phase_result(self, cycle_dir: Path, phase_name: str, result: Dict[str, Any]) -> None:
        path = self._phase_path(cycle_dir, phase_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(result)
        payload["_resume_context"] = self._phase_resume_context(phase_name)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")

    def _write_phase_checkpoint(self, cycle_dir: Path, phase_name: str, payload: Dict[str, Any]) -> None:
        checkpoint = dict(payload)
        checkpoint.setdefault("status", "running")
        checkpoint["phase"] = phase_name
        checkpoint["updated_at"] = _utc_now()
        checkpoint["_resume_context"] = self._phase_resume_context(phase_name)
        self._phase_path(cycle_dir, phase_name).write_text(
            json.dumps(checkpoint, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def _phase_resume_context(self, phase_name: str) -> Dict[str, Any]:
        phase_config: Dict[str, Any] = {}
        if phase_name == "bluebook":
            phase_config = asdict(self.config.bluebook)
        elif phase_name == "state_refresh":
            phase_config = asdict(self.config.state_refresh)
        elif phase_name == "agentic_corpora":
            phase_config = asdict(self.config.agentic_corpora)
        return {
            "phase": phase_name,
            "states": list(self.states),
            "include_dc": bool(self.config.include_dc),
            "phase_config": phase_config,
        }

    async def _run_or_resume_phase(
        self,
        phase_name: str,
        cycle_dir: Path,
        runner: Callable[[], Awaitable[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        cached = self._load_resumable_phase(cycle_dir, phase_name)
        if cached is not None:
            return cached
        started_at = _utc_now()
        self._write_phase_checkpoint(
            cycle_dir,
            phase_name,
            {"status": "running", "started_at": started_at, "heartbeat_count": 0},
        )
        heartbeat_seconds = max(0.0, float(os.getenv("LEGAL_SCRAPER_DAEMON_HEARTBEAT_SECONDS", "15") or 0.0))
        stop_heartbeat = asyncio.Event()

        async def _heartbeat() -> None:
            count = 0
            while not stop_heartbeat.is_set():
                try:
                    await asyncio.wait_for(stop_heartbeat.wait(), timeout=heartbeat_seconds)
                    break
                except asyncio.TimeoutError:
                    count += 1
                    self._write_phase_checkpoint(
                        cycle_dir,
                        phase_name,
                        {
                            "status": "running",
                            "started_at": started_at,
                            "heartbeat_count": count,
                            "message": f"{phase_name} phase still running",
                        },
                    )

        heartbeat_task = None
        if heartbeat_seconds > 0:
            heartbeat_task = asyncio.create_task(_heartbeat())
        try:
            result = await runner()
        finally:
            stop_heartbeat.set()
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        self._write_phase_result(cycle_dir, phase_name, result)
        return result

    def _full_corpus_completeness(self, phases: Dict[str, Any]) -> Dict[str, Any]:
        required_states = list(self.states)
        required_corpora = list(SUPPORTED_CORPORA)
        state_refresh = phases.get("state_refresh") if isinstance(phases.get("state_refresh"), dict) else {}
        agentic = phases.get("agentic_corpora") if isinstance(phases.get("agentic_corpora"), dict) else {}

        scrape_gap_states = sorted(set(str(item).upper() for item in list(state_refresh.get("scrape_gap_states") or []) if str(item).strip()))
        build_gap_states = sorted(set(str(item).upper() for item in list(state_refresh.get("build_gap_states") or []) if str(item).strip()))
        build = state_refresh.get("build") if isinstance(state_refresh.get("build"), dict) else {}
        missing_jsonld_states = sorted(set(str(item).upper() for item in list(build.get("missing_jsonld_states") or []) if str(item).strip()))
        built_states = {
            str(item).upper()
            for item in list(build.get("states") or [])
            if str(item).strip()
        }
        missing_built_states = [] if not built_states else [state for state in required_states if state not in built_states]
        if not state_refresh:
            missing_built_states = list(required_states)
        state_report_artifact_gaps = []
        for report in list(build.get("state_reports") or []):
            if not isinstance(report, dict):
                continue
            state = str(report.get("state") or "").upper().strip()
            if not state:
                continue
            parquet_path = str(report.get("parquet_path") or "").strip()
            merged_count = int(report.get("merged_row_count", 0) or 0)
            if not parquet_path or not Path(parquet_path).exists() or merged_count <= 0:
                state_report_artifact_gaps.append(state)
        missing_state_refresh_states = sorted(set(scrape_gap_states + build_gap_states + missing_jsonld_states + missing_built_states + state_report_artifact_gaps))

        agentic_results = agentic.get("corpora") if isinstance(agentic.get("corpora"), dict) else {}
        missing_agentic_corpora = [corpus for corpus in required_corpora if corpus not in agentic_results]
        missing_agentic_states_by_corpus: Dict[str, List[str]] = {}
        errored_agentic_corpora = [
            corpus
            for corpus, result in sorted(agentic_results.items())
            if isinstance(result, dict) and str(result.get("status") or "").lower() == "error"
        ]
        for corpus in required_corpora:
            result = agentic_results.get(corpus)
            if not isinstance(result, dict):
                continue
            summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            processed_states = {
                str(item).upper()
                for item in list(summary.get("states") or [])
                if str(item).strip()
            }
            latest_cycle = summary.get("latest_cycle") if isinstance(summary.get("latest_cycle"), dict) else {}
            diagnostics = latest_cycle.get("diagnostics") if isinstance(latest_cycle.get("diagnostics"), dict) else {}
            coverage = diagnostics.get("coverage") if isinstance(diagnostics.get("coverage"), dict) else {}
            coverage_gap_states = {
                str(item).upper()
                for item in list(coverage.get("coverage_gap_states") or [])
                if str(item).strip()
            }
            missing_processed_states = (
                [state for state in required_states if state not in processed_states]
                if processed_states
                else list(required_states)
            )
            missing_states = sorted(set(missing_processed_states) | coverage_gap_states)
            if missing_states:
                missing_agentic_states_by_corpus[corpus] = missing_states

        status = "complete"
        if (
            missing_state_refresh_states
            or missing_agentic_corpora
            or missing_agentic_states_by_corpus
            or errored_agentic_corpora
        ):
            status = "incomplete"
        if str(state_refresh.get("status") or "").lower() == "error" or str(agentic.get("status") or "").lower() == "error":
            status = "error"

        return {
            "status": status,
            "required_state_count": len(required_states),
            "required_states": required_states,
            "required_corpora": required_corpora,
            "state_refresh_status": str(state_refresh.get("status") or "disabled"),
            "missing_state_refresh_states": missing_state_refresh_states,
            "missing_state_refresh_artifact_states": sorted(set(state_report_artifact_gaps)),
            "agentic_status": str(agentic.get("status") or "disabled"),
            "missing_agentic_corpora": missing_agentic_corpora,
            "missing_agentic_states_by_corpus": missing_agentic_states_by_corpus,
            "errored_agentic_corpora": errored_agentic_corpora,
        }

    @staticmethod
    def _cycle_status(phases: Dict[str, Any], corpus_completeness: Optional[Dict[str, Any]] = None) -> str:
        statuses = [str((phase or {}).get("status") or "").lower() for phase in phases.values() if isinstance(phase, dict)]
        completeness_status = str((corpus_completeness or {}).get("status") or "").lower()
        if completeness_status == "error":
            return "error"
        if completeness_status == "incomplete":
            return "partial_success"
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

        previous_skip_live_search = os.environ.get("LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH")
        if config.skip_live_search:
            os.environ["LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH"] = "1"

        try:
            run = await runner(
                sample_count=max(1, int(config.samples)),
                corpus_keys=list(config.corpora or []),
                state_codes=list(self.states),
                allow_hf_fallback=bool(config.allow_hf_fallback),
                prefer_hf_corpora=bool(config.prefer_hf_corpora),
                primary_corpora_only=bool(config.primary_corpora_only),
                exact_state_partitions_only=bool(config.exact_state_partitions_only),
                materialize_hf_corpora=bool(config.materialize_hf_corpora),
                exhaustive=bool(config.exhaustive),
                enable_recovery=bool(config.enable_recovery),
                recovery_max_candidates=max(1, int(config.recovery_max_candidates)),
                recovery_archive_top_k=max(0, int(config.recovery_archive_top_k)),
                publish_to_hf=bool(config.publish_to_hf),
                hf_token=self.config.hf_token,
                merge_recovered_rows=bool(config.merge_recovered_rows),
                hydrate_merge_from_hf=bool(config.hydrate_merge_from_hf or config.publish_merged_parquet_to_hf),
                publish_merged_parquet_to_hf=bool(config.publish_merged_parquet_to_hf),
                seed_from_corpora=bool(config.seed_from_corpora),
                seed_only=bool(config.seed_only),
                seed_examples_per_corpus=max(1, int(config.seed_examples_per_corpus)),
                max_seed_examples_per_state=(
                    max(1, int(config.max_seed_examples_per_state))
                    if int(config.max_seed_examples_per_state or 0) > 0
                    else None
                ),
                max_seed_examples_per_source=(
                    max(1, int(config.max_seed_examples_per_source))
                    if int(config.max_seed_examples_per_source or 0) > 0
                    else None
                ),
                sampling_shuffle_seed=int(config.sampling_shuffle_seed),
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
        finally:
            if config.skip_live_search:
                if previous_skip_live_search is None:
                    os.environ.pop("LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH", None)
                else:
                    os.environ["LEGAL_SOURCE_RECOVERY_SKIP_LIVE_SEARCH"] = previous_skip_live_search

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
        old_hydrate_timeout = os.environ.get("STATE_SCRAPER_HYDRATE_TIMEOUT_SECONDS")
        os.environ["STATE_SCRAPER_HYDRATE_TIMEOUT_SECONDS"] = str(max(1.0, float(config.hydrate_timeout_seconds or 25.0)))
        try:
            result = await runner(args)
            return dict(result)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "output_root": str(output_root)}
        finally:
            if old_hydrate_timeout is None:
                os.environ.pop("STATE_SCRAPER_HYDRATE_TIMEOUT_SECONDS", None)
            else:
                os.environ["STATE_SCRAPER_HYDRATE_TIMEOUT_SECONDS"] = old_hydrate_timeout

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
        return await self._run_agentic_corpus_subprocess(corpus=corpus, output_dir=output_dir)

    async def _run_agentic_corpus_subprocess(self, *, corpus: str, output_dir: Path) -> Dict[str, Any]:
        config = self.config.agentic_corpora
        command = [
            sys.executable,
            "-m",
            "ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon",
            "--corpus",
            str(corpus),
            "--states",
            ",".join(self.states),
            "--output-dir",
            str(output_dir),
            "--max-cycles",
            str(max(1, int(config.max_cycles))),
            "--max-statutes",
            str(int(config.max_statutes or 0)),
            "--archive-warmup-urls",
            str(max(0, int(config.archive_warmup_urls))),
            "--per-state-timeout-seconds",
            str(float(config.per_state_timeout_seconds)),
            "--scrape-timeout-seconds",
            str(float(config.scrape_timeout_seconds)),
            "--admin-agentic-max-candidates-per-state",
            str(max(1, int(config.admin_agentic_max_candidates_per_state))),
            "--admin-agentic-max-fetch-per-state",
            str(max(1, int(config.admin_agentic_max_fetch_per_state))),
            "--admin-agentic-max-results-per-domain",
            str(max(1, int(config.admin_agentic_max_results_per_domain))),
            "--admin-agentic-max-hops",
            str(max(0, int(config.admin_agentic_max_hops))),
            "--admin-agentic-max-pages",
            str(max(1, int(config.admin_agentic_max_pages))),
            "--admin-parallel-assist-state-limit",
            str(max(0, int(config.admin_parallel_assist_state_limit))),
            "--admin-parallel-assist-max-urls-per-domain",
            str(max(1, int(config.admin_parallel_assist_max_urls_per_domain))),
            "--admin-parallel-assist-timeout-seconds",
            str(max(1.0, float(config.admin_parallel_assist_timeout_seconds))),
            "--target-score",
            str(float(config.target_score)),
        ]
        if not bool(config.admin_parallel_assist_enabled):
            command.append("--no-admin-parallel-assist-enabled")
        if bool(config.stop_on_target_score):
            command.append("--stop-on-target-score")

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout = float(config.scrape_timeout_seconds or 0.0)
        supervisor_timeout = 0.0
        if timeout > 0:
            supervisor_timeout = timeout + min(60.0, max(10.0, timeout * 0.25))
        try:
            if timeout > 0:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=supervisor_timeout)
            else:
                stdout, stderr = await process.communicate()
        except asyncio.TimeoutError:
            process.terminate()
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            except asyncio.TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
            return {
                "status": "error",
                "error": f"agentic corpus subprocess exceeded supervisor timeout after {supervisor_timeout:.1f}s",
                "exception_type": "TimeoutError",
                "output_dir": str(output_dir),
                "command": command,
                "scrape_timeout_seconds": timeout,
                "supervisor_timeout_seconds": supervisor_timeout,
                "stdout_tail": stdout.decode("utf-8", errors="replace")[-4000:],
                "stderr_tail": stderr.decode("utf-8", errors="replace")[-4000:],
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc), "output_dir": str(output_dir)}
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        summary: Dict[str, Any]
        try:
            summary = _decode_json_from_mixed_output(stdout_text)
        except Exception:
            summary = {
                "status": "error",
                "error": "agentic corpus subprocess did not return valid JSON",
                "stdout_tail": stdout_text[-4000:],
                "stderr_tail": stderr_text[-4000:],
            }
        status = _agentic_subprocess_status(returncode=process.returncode, summary=summary)
        return {
            "status": status,
            "output_dir": str(output_dir),
            "summary": summary,
            "returncode": process.returncode,
            "stderr_tail": stderr_text[-4000:],
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the comprehensive legal scraper daemon")
    parser.add_argument("--states", default="all")
    parser.add_argument("--include-dc", action="store_true")
    parser.add_argument("--output-dir", default=str(Path.home() / ".ipfs_datasets" / "legal_scraper_daemon"))
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--cycle-interval-seconds", type=float, default=3600.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Write the preflight plan and target manifest, then exit without running scraper phases.",
    )
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--full-corpus",
        action="store_true",
        help=(
            "Use overnight/full-corpus retrieval defaults: all states, unbounded state-law scraping, "
            "HF merge hydration, all supported Bluebook/agentic corpora, and longer per-state budgets. "
            "Publishing still requires the explicit publish flags."
        ),
    )
    parser.add_argument("--hf-token", default="")
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--no-fetch-cache", action="store_true")
    parser.add_argument("--no-search-cache", action="store_true")
    parser.add_argument("--cache-to-ipfs", action="store_true")

    parser.add_argument("--disable-bluebook", action="store_true")
    parser.add_argument("--bluebook-samples", type=int, default=50)
    parser.add_argument("--bluebook-corpora", default="state_laws")
    parser.add_argument("--bluebook-seed-from-corpora", action="store_true")
    parser.add_argument("--bluebook-seed-only", action="store_true")
    parser.add_argument("--bluebook-seed-examples-per-corpus", type=int, default=2)
    parser.add_argument("--bluebook-max-seed-examples-per-state", type=int, default=0)
    parser.add_argument("--bluebook-max-seed-examples-per-source", type=int, default=0)
    parser.add_argument("--bluebook-sampling-shuffle-seed", type=int, default=0)
    parser.add_argument("--bluebook-prefer-hf-corpora", action="store_true")
    parser.add_argument("--bluebook-primary-corpora-only", action="store_true")
    parser.add_argument("--bluebook-exact-state-partitions-only", action="store_true")
    parser.add_argument("--bluebook-materialize-hf-corpora", action="store_true")
    parser.add_argument("--bluebook-merge-recovered-rows", action="store_true")
    parser.add_argument("--bluebook-hydrate-merge-from-hf", action="store_true")
    parser.add_argument("--bluebook-publish-merged-parquet-to-hf", action="store_true")
    parser.add_argument("--bluebook-publish-to-hf", action="store_true")
    parser.add_argument("--bluebook-live-search", action="store_true")

    parser.add_argument("--disable-state-refresh", action="store_true")
    parser.add_argument("--state-refresh-scrape", action="store_true")
    parser.add_argument("--state-refresh-merge-hf-existing", action="store_true")
    parser.add_argument("--state-refresh-publish-to-hf", action="store_true")
    parser.add_argument("--state-refresh-verify", action="store_true")
    parser.add_argument("--allow-incomplete-publish", action="store_true")
    parser.add_argument("--max-statutes", type=int, default=0)
    parser.add_argument("--parallel-workers", type=int, default=4)
    parser.add_argument("--per-state-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--per-state-retry-attempts", type=int, default=1)
    parser.add_argument("--no-hydrate-state-text", action="store_true")
    parser.add_argument("--state-refresh-hydrate-timeout-seconds", type=float, default=25.0)

    parser.add_argument("--enable-agentic-corpora", action="store_true")
    parser.add_argument("--agentic-corpora", default="all")
    parser.add_argument("--agentic-max-cycles", type=int, default=1)
    parser.add_argument("--agentic-archive-warmup-urls", type=int, default=0)
    parser.add_argument("--agentic-per-state-timeout-seconds", type=float, default=86400.0)
    parser.add_argument("--agentic-scrape-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--agentic-admin-max-candidates-per-state", type=int, default=1000)
    parser.add_argument("--agentic-admin-max-fetch-per-state", type=int, default=1000)
    parser.add_argument("--agentic-admin-max-results-per-domain", type=int, default=1000)
    parser.add_argument("--agentic-admin-max-hops", type=int, default=4)
    parser.add_argument("--agentic-admin-max-pages", type=int, default=1000)
    parser.add_argument("--disable-agentic-admin-parallel-assist", action="store_true")
    parser.add_argument("--agentic-admin-parallel-assist-state-limit", type=int, default=6)
    parser.add_argument("--agentic-admin-parallel-assist-max-urls-per-domain", type=int, default=20)
    parser.add_argument("--agentic-admin-parallel-assist-timeout-seconds", type=float, default=86400.0)
    parser.add_argument("--json", action="store_true")
    return parser


def config_from_args(args: argparse.Namespace) -> LegalScraperDaemonConfig:
    full_corpus = bool(getattr(args, "full_corpus", False))
    states = _normalize_states("all" if full_corpus else args.states, include_dc=bool(args.include_dc or full_corpus))
    bluebook_corpora = _normalize_corpora("all" if full_corpus else args.bluebook_corpora)
    agentic_corpora = _normalize_corpora("all" if full_corpus else args.agentic_corpora)
    return LegalScraperDaemonConfig(
        full_corpus=full_corpus,
        states=states,
        include_dc=bool(args.include_dc or full_corpus),
        output_dir=str(args.output_dir),
        cycle_interval_seconds=float(args.cycle_interval_seconds),
        max_cycles=max(1, int(args.max_cycles)),
        dry_run=bool(args.dry_run),
        resume=not bool(args.no_resume),
        hf_token=str(args.hf_token or "").strip() or None,
        cache=CacheDaemonConfig(
            enabled=not bool(args.no_cache),
            fetch_cache_enabled=not bool(args.no_fetch_cache),
            search_cache_enabled=not bool(args.no_search_cache),
            cache_dir=str(args.cache_dir or ""),
            mirror_to_ipfs=bool(args.cache_to_ipfs),
        ),
        bluebook=BluebookDaemonConfig(
            enabled=not bool(args.disable_bluebook),
            samples=max(1, int(args.bluebook_samples)),
            corpora=bluebook_corpora,
            seed_from_corpora=bool(args.bluebook_seed_from_corpora or full_corpus),
            seed_only=bool(args.bluebook_seed_only),
            seed_examples_per_corpus=max(1, int(args.bluebook_seed_examples_per_corpus)),
            max_seed_examples_per_state=max(0, int(args.bluebook_max_seed_examples_per_state)),
            max_seed_examples_per_source=max(0, int(args.bluebook_max_seed_examples_per_source)),
            sampling_shuffle_seed=int(args.bluebook_sampling_shuffle_seed),
            prefer_hf_corpora=bool(args.bluebook_prefer_hf_corpora or full_corpus),
            primary_corpora_only=bool(args.bluebook_primary_corpora_only or full_corpus),
            exact_state_partitions_only=bool(args.bluebook_exact_state_partitions_only or full_corpus),
            materialize_hf_corpora=bool(args.bluebook_materialize_hf_corpora or full_corpus),
            merge_recovered_rows=bool(args.bluebook_merge_recovered_rows),
            hydrate_merge_from_hf=bool(args.bluebook_hydrate_merge_from_hf or args.bluebook_publish_merged_parquet_to_hf),
            publish_merged_parquet_to_hf=bool(args.bluebook_publish_merged_parquet_to_hf),
            publish_to_hf=bool(args.bluebook_publish_to_hf),
            skip_live_search=not bool(args.bluebook_live_search),
        ),
        state_refresh=StateRefreshDaemonConfig(
            enabled=not bool(args.disable_state_refresh),
            scrape=bool(args.state_refresh_scrape or full_corpus),
            merge_hf_existing=bool(args.state_refresh_merge_hf_existing or full_corpus),
            publish_to_hf=bool(args.state_refresh_publish_to_hf),
            verify_publish=bool(args.state_refresh_verify),
            allow_incomplete_publish=bool(args.allow_incomplete_publish),
            max_statutes=0 if full_corpus else max(0, int(args.max_statutes)),
            parallel_workers=max(1, int(args.parallel_workers)),
            per_state_timeout_seconds=max(
                86400.0 if full_corpus else 1.0,
                float(args.per_state_timeout_seconds),
            ),
            per_state_retry_attempts=max(2 if full_corpus else 0, int(args.per_state_retry_attempts)),
            hydrate_statute_text=not bool(args.no_hydrate_state_text),
            hydrate_timeout_seconds=max(60.0 if full_corpus else 1.0, float(args.state_refresh_hydrate_timeout_seconds)),
        ),
        agentic_corpora=AgenticCorpusDaemonConfig(
            enabled=bool(args.enable_agentic_corpora or full_corpus),
            corpora=agentic_corpora,
            max_cycles=max(1, int(args.agentic_max_cycles)),
            max_statutes=0 if full_corpus else max(0, int(args.max_statutes)),
            archive_warmup_urls=max(0, int(args.agentic_archive_warmup_urls)),
            per_state_timeout_seconds=max(
                86400.0 if full_corpus else 1.0,
                float(args.agentic_per_state_timeout_seconds),
            ),
            scrape_timeout_seconds=max(0.0, float(args.agentic_scrape_timeout_seconds)),
            admin_agentic_max_candidates_per_state=max(1, int(args.agentic_admin_max_candidates_per_state)),
            admin_agentic_max_fetch_per_state=max(1, int(args.agentic_admin_max_fetch_per_state)),
            admin_agentic_max_results_per_domain=max(1, int(args.agentic_admin_max_results_per_domain)),
            admin_agentic_max_hops=max(0, int(args.agentic_admin_max_hops)),
            admin_agentic_max_pages=max(1, int(args.agentic_admin_max_pages)),
            admin_parallel_assist_enabled=not bool(args.disable_agentic_admin_parallel_assist),
            admin_parallel_assist_state_limit=max(0, int(args.agentic_admin_parallel_assist_state_limit)),
            admin_parallel_assist_max_urls_per_domain=max(
                1,
                int(args.agentic_admin_parallel_assist_max_urls_per_domain),
            ),
            admin_parallel_assist_timeout_seconds=max(1.0, float(args.agentic_admin_parallel_assist_timeout_seconds)),
        ),
    )


async def _main_async(args: argparse.Namespace) -> int:
    daemon = LegalScraperDaemon(config_from_args(args))
    result = daemon.write_preflight_artifacts() if bool(getattr(args, "preflight_only", False)) else await daemon.run()
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
