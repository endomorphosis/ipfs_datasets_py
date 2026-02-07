#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _disable_ipfs_kit_stack_if_needed() -> None:
    enable_ipfs_kit = _truthy(os.environ.get("IPFS_DATASETS_PY_BENCHMARK_ENABLE_IPFS_KIT"))
    if enable_ipfs_kit:
        return

    # Keep benchmarks hermetic/quiet unless explicitly enabled.
    os.environ.setdefault("IPFS_KIT_DISABLE", "1")
    os.environ.setdefault("IPFS_KIT_DISABLE_LIBP2P", "1")
    os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")
    os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_LOTUS_DEPS", "0")
    os.environ.setdefault("IPFS_STORAGE_ENABLED", "0")
    os.environ.setdefault("IPFS_DATASETS_PY_BENCHMARK", "1")


def _default_prompts() -> List[str]:
    return [
        "Reply with OK only.",
        "What is 1+1? Answer with just the number.",
        "Return a JSON object with a single key 'status' set to 'ok'.",
    ]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _open_log_file(workspace: Path) -> Optional[Path]:
    value = os.environ.get("IPFS_DATASETS_PY_SYMAI_BENCHMARK_LOG", "").strip()
    if value:
        return Path(value)
    return workspace / "outputs" / "symai_benchmark.log"


def main(argv: Optional[List[str]] = None) -> int:
    _disable_ipfs_kit_stack_if_needed()

    parser = argparse.ArgumentParser(description="Benchmark SyMAI routing via ipfs_datasets_py.llm_router")
    parser.add_argument(
        "--model",
        required=True,
        help="Model name to pass to llm_router.generate_text(model_name=...).",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Optional llm_router provider (e.g. openrouter, codex_cli, copilot_cli). Default: auto.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=int(os.environ.get("IPFS_DATASETS_PY_SYMAI_BENCHMARK_RUNS", "1")),
        help="Number of times to run the prompt set.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("IPFS_DATASETS_PY_SYMAI_BENCHMARK_TIMEOUT", "120")),
        help="Per prompt timeout, forwarded to providers that support it.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path. Default: ipfs_datasets_py/outputs/symai_benchmark.json",
    )
    parser.add_argument(
        "--remote-cache-network",
        action="store_true",
        help=(
            "Enable distributed mapping-cache networking for remote router caches "
            "(sets IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK=1 and configures deps.remote_cache)."
        ),
    )

    args = parser.parse_args(argv)

    if args.remote_cache_network:
        # Used by ipfs_datasets_py.caching.router_remote_cache to opt-in to peer networking.
        os.environ["IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK"] = "1"

    workspace = Path(__file__).resolve().parents[1]
    output_path = Path(args.output) if args.output else (workspace / "outputs" / "symai_benchmark.json")
    log_path = _open_log_file(workspace)

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    def log(message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        if log_path is None:
            return
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass

    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py import llm_router

    deps = RouterDeps()
    if args.remote_cache_network:
        try:
            from ipfs_datasets_py.caching.router_remote_cache import make_ipfs_remote_cache

            deps.remote_cache = make_ipfs_remote_cache(deps=deps)
        except Exception:
            # Best-effort: benchmark should still run without remote caching.
            deps.remote_cache = None
    prompts = _default_prompts()

    provider_instance = None
    provider_resolution_error = ""
    # Warm provider resolution once to capture router caching when possible,
    # but keep the benchmark runnable even when providers are unavailable.
    try:
        provider_instance = llm_router.get_llm_provider(args.provider, deps=deps)
    except Exception as exc:
        provider_resolution_error = str(exc)

    log(f"Benchmark start provider={args.provider or 'auto'} model={args.model} runs={args.runs}")
    if provider_resolution_error:
        log(f"Provider resolution error: {provider_resolution_error}")

    results: Dict[str, Any] = {
        "provider": args.provider or "auto",
        "model": args.model,
        "runs": args.runs,
        "prompts": prompts,
        "provider_resolution_error": provider_resolution_error,
        "entries": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    for run_idx in range(max(1, int(args.runs))):
        run_entry: Dict[str, Any] = {"index": run_idx, "items": [], "elapsed_s": 0.0}
        run_start = time.monotonic()

        for prompt in prompts:
            item_start = time.monotonic()
            ok = True
            text: str = ""
            error: str = ""

            log(f"Prompt: {prompt}")

            try:
                text = llm_router.generate_text(
                    prompt,
                    model_name=args.model,
                    provider=args.provider,
                    provider_instance=provider_instance,
                    deps=deps,
                    timeout=args.timeout,
                )
            except Exception as exc:
                ok = False
                error = str(exc)

            elapsed = time.monotonic() - item_start
            preview = (text or "").strip().replace("\n", " ")
            if len(preview) > 240:
                preview = preview[:240] + "…"
            if ok:
                log(f"Result: ok elapsed={elapsed:.2f}s chars={len(text or '')}")
            else:
                log(f"Result: FAIL elapsed={elapsed:.2f}s error={error}")
            run_entry["items"].append(
                {
                    "prompt": prompt,
                    "ok": ok,
                    "elapsed_s": elapsed,
                    "output_chars": len(text or ""),
                    "output_preview": preview,
                    "error": error,
                }
            )

        run_entry["elapsed_s"] = time.monotonic() - run_start
        results["entries"].append(run_entry)

    results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_json(output_path, results)

    log(f"Wrote benchmark results to: {output_path}")
    if log_path is not None:
        log(f"Wrote benchmark log to: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
