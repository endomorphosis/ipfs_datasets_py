#!/usr/bin/env python3

import argparse
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional


def _bootstrap_symai_env_for_benchmark(*, base_env: Dict[str, str], model: str, provider: str | None, log) -> None:
    """Best-effort SyMAI environment bootstrap.

    The SymbolicAI (`symai`) package may try to run an interactive setup wizard
    if its venv-local config is missing/incomplete. Additionally, some of our
    tests (e.g. top_level_dir_tests) expect Codex routing env vars.

    This function is intentionally best-effort: failures should not abort the benchmark.
    """

    try:
        from ipfs_datasets_py.utils.symai_config import ensure_symai_config
    except Exception as exc:
        log(f"SyMAI bootstrap: unable to import ensure_symai_config ({exc})")
        return

    provider_value = (provider or "").strip()
    use_codex_for_symai = provider_value == "codex_cli"

    # Keep benchmarks deterministic and fast by default.
    # Set IPFS_DATASETS_PY_BENCHMARK_SYMAI_LIVE=1 to allow real external calls.
    if not _truthy(base_env.get("IPFS_DATASETS_PY_BENCHMARK_SYMAI_LIVE")):
        base_env.setdefault("IPFS_DATASETS_PY_SYMAI_ROUTER_DRY_RUN", "1")

    if use_codex_for_symai:
        # Ensure the spawned test process registers SyMAI engines via ipfs_datasets_py/sitecustomize.py.
        base_env.setdefault("IPFS_DATASETS_PY_SYMAI_SITEBOOT", "1")
        base_env.setdefault("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI", "1")
        base_env.setdefault("IPFS_DATASETS_PY_CODEX_MODEL", str(model))
        # Help tests that directly inspect these env vars.
        base_env.setdefault("NEUROSYMBOLIC_ENGINE_MODEL", f"codex:{model}")
        base_env.setdefault("NEUROSYMBOLIC_ENGINE_API_KEY", "codex")

        config_path = ensure_symai_config(
            neurosymbolic_model=f"codex:{model}",
            neurosymbolic_api_key="codex",
            force=True,
            apply_engine_router=False,
        )
        if config_path:
            log(f"SyMAI bootstrap: ensured config at {config_path}")

        # NOTE: EngineRepository registration must happen inside the test subprocess.
        # We rely on `ipfs_datasets_py/sitecustomize.py` (gated by IPFS_DATASETS_PY_SYMAI_SITEBOOT)
        # to register the neurosymbolic engine before tests call Expression.prompt.
        log("SyMAI bootstrap: enabled sitecustomize engine registration")
        return

    # Default to routing SyMAI through our engine router when possible.
    base_env.setdefault("IPFS_DATASETS_PY_SYMAI_SITEBOOT", "1")
    base_env.setdefault("IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER", "1")
    base_env.setdefault("NEUROSYMBOLIC_ENGINE_MODEL", base_env.get("NEUROSYMBOLIC_ENGINE_MODEL") or "ipfs:default")
    base_env.setdefault("NEUROSYMBOLIC_ENGINE_API_KEY", base_env.get("NEUROSYMBOLIC_ENGINE_API_KEY") or "ipfs")

    config_path = ensure_symai_config(
        neurosymbolic_model=base_env["NEUROSYMBOLIC_ENGINE_MODEL"],
        neurosymbolic_api_key=base_env["NEUROSYMBOLIC_ENGINE_API_KEY"],
        force=False,
        apply_engine_router=True,
    )
    if config_path:
        log(f"SyMAI bootstrap: ensured config at {config_path}")


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _disable_ipfs_kit_stack_if_needed() -> None:
    enable_ipfs_kit = _truthy(os.environ.get("IPFS_DATASETS_PY_BENCHMARK_ENABLE_IPFS_KIT"))
    if enable_ipfs_kit:
        return

    os.environ.setdefault("IPFS_KIT_DISABLE", "1")
    os.environ.setdefault("IPFS_KIT_DISABLE_LIBP2P", "1")
    os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")
    os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_LOTUS_DEPS", "0")
    os.environ.setdefault("IPFS_STORAGE_ENABLED", "0")
    os.environ.setdefault("IPFS_DATASETS_PY_BENCHMARK", "1")


def _env_int(*names: str, default: int) -> int:
    for name in names:
        value = os.environ.get(name)
        if value is None:
            continue
        try:
            return int(value)
        except Exception:
            continue
    return default


def _line_has_rate_limit(line: str) -> bool:
    if not line:
        return False
    needles = [
        "usage_limit_reached",
        "Too Many Requests",
        "error=http 429",
        "HTTP 429",
        "You've hit your usage limit",
    ]
    return any(needle in line for needle in needles)


def _parse_summary(output: str) -> Dict[str, int]:
    passed = 0
    total = 0

    # Legacy format printed by some top-level test scripts.
    for line in output.splitlines():
        if "Summary:" in line and "/" in line:
            parts = line.split("Summary:")[-1].strip().split()[0]
            if "/" in parts:
                left, right = parts.split("/", 1)
                if left.isdigit() and right.isdigit():
                    passed = max(passed, int(left))
                    total = max(total, int(right))

        # Script-style summary (LogicMCPToolsTester)
        if "Total Tests:" in line:
            value = line.split("Total Tests:", 1)[-1].strip()
            if value.isdigit():
                total = max(total, int(value))
        if line.strip().startswith("Passed:"):
            value = line.split("Passed:", 1)[-1].strip()
            if value.isdigit():
                passed = max(passed, int(value))

    # Pytest format (best-effort): "11 passed in 6.49s" / "10 passed, 1 failed".
    for line in output.splitlines()[::-1]:
        if " passed" not in line:
            continue
        tokens = line.replace("=", " ").replace(",", " ").split()
        for idx, token in enumerate(tokens):
            if token.isdigit() and idx + 1 < len(tokens) and tokens[idx + 1] == "passed":
                passed = max(passed, int(token))
        if total < passed:
            total = passed
        if passed:
            break

    return {"passed": passed, "total": total}


def _command_for_test(workspace: Path, test_path: Path, *, symai_debug_runpy: bool) -> List[str]:
    rel = str(test_path.relative_to(workspace))
    base = test_path.name

    # pytest-style tests
    if rel.startswith("tests/") and base.startswith("test_"):
        return [sys.executable, "-m", "pytest", "-q", rel]

    # legacy pytest tests living under the package tree
    if "/old_tests/" in rel and (base.startswith("test_") or base.startswith("_test_")):
        return [sys.executable, "-m", "pytest", "-q", rel]

    # standalone scripts (including tests/unit/_test_*.py)
    if not symai_debug_runpy:
        return [sys.executable, rel]

    # Historical benchmark behavior: import module to show source location, then run via runpy.
    code = (
        "import importlib, runpy; "
        "sc = importlib.import_module('ipfs_datasets_py.logic_integration.symbolic_contracts'); "
        "print(f'SYMAI_DEBUG symbolic_contracts={sc.__file__}'); "
        f"runpy.run_path({rel!r}, run_name='__main__')"
    )
    return [sys.executable, "-c", code]


def _collect_tests(workspace: Path, test_glob: str) -> List[Path]:
    if not test_glob:
        return []
    return sorted(workspace.glob(test_glob))


def _run_test(
    *,
    workspace: Path,
    test_path: Path,
    env: Dict[str, str],
    log,
    heartbeat_seconds: int,
    timeout_seconds: int,
    symai_debug_runpy: bool,
) -> Dict[str, object]:
    output_lines: List[str] = []
    saw_rate_limit = False
    timed_out = False

    cmd = _command_for_test(workspace, test_path, symai_debug_runpy=symai_debug_runpy)
    log(f"cmd: {' '.join(cmd)}")

    start_time = time.monotonic()
    last_heartbeat = start_time

    proc = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=1,
        cwd=str(workspace),
    )

    if proc.stdout:
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if ready:
                line = proc.stdout.readline()
                if line:
                    output_lines.append(line)
                    if _line_has_rate_limit(line):
                        saw_rate_limit = True
                    log(f"  | {line.rstrip()}")
                elif proc.poll() is not None:
                    break
            else:
                if proc.poll() is not None:
                    break

            now = time.monotonic()
            if heartbeat_seconds > 0 and now - last_heartbeat >= heartbeat_seconds:
                log(f"  | ... still running ({now - start_time:.0f}s elapsed)")
                last_heartbeat = now
            if timeout_seconds > 0 and now - start_time >= timeout_seconds:
                timed_out = True
                log(f"  | ... timeout after {timeout_seconds}s, terminating")
                try:
                    proc.terminate()
                except Exception:
                    pass
                break

        remainder = proc.stdout.read()
        if remainder:
            output_lines.append(remainder)
            for line in remainder.splitlines():
                if _line_has_rate_limit(line):
                    saw_rate_limit = True
                log(f"  | {line}")

    if timed_out:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            proc.wait()
    else:
        proc.wait()

    output = "".join(output_lines)
    summary = _parse_summary(output)

    exit_code = proc.returncode
    if timed_out and (exit_code is None or exit_code == 0):
        exit_code = 124

    return {
        "exit_code": exit_code,
        "passed": summary["passed"],
        "total": summary["total"],
        "output": output[-4000:],
        "rate_limited": saw_rate_limit,
        "timed_out": timed_out,
    }


def main(argv: Optional[List[str]] = None) -> int:
    _disable_ipfs_kit_stack_if_needed()

    parser = argparse.ArgumentParser(
        description="Temporal/Deontic logic benchmark suite (single model)"
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model name (passed via env to llm_router). If omitted, uses "
            "IPFS_DATASETS_PY_LLM_MODEL, then NEUROSYMBOLIC_ENGINE_MODEL, then 'gpt-5-mini'."
        ),
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Optional llm_router provider to force via env (e.g. hf, openrouter, codex_cli).",
    )
    parser.add_argument(
        "--require-lean",
        action="store_true",
        help="Fail the run if Lean is not installed (enforces symbolic proof execution).",
    )
    parser.add_argument(
        "--require-coq",
        action="store_true",
        help="Fail the run if Coq is not installed (enforces symbolic proof execution).",
    )
    parser.add_argument(
        "--tests",
        default=None,
        help=(
            "Comma-separated list of test/script paths relative to ipfs_datasets_py. "
            "Default runs temporal deontic RAG tests + logic tool verification scripts."
        ),
    )
    parser.add_argument(
        "--tests-glob",
        default=None,
        help=(
            "Glob of tests/scripts relative to ipfs_datasets_py (historical benchmark style). "
            "Example: tests/top_level_dir_tests/_test_symbolicai_*.py"
        ),
    )
    parser.add_argument(
        "--symai-debug-runpy",
        action="store_true",
        help=(
            "For standalone scripts, run via runpy and print the imported "
            "ipfs_datasets_py.logic_integration.symbolic_contracts path (historical benchmark style)."
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=_env_int(
            "IPFS_DATASETS_PY_LOGIC_BENCHMARK_RUNS",
            "IPFS_DATASETS_PY_CODEX_BENCHMARK_RUNS",
            default=1,
        ),
    )
    parser.add_argument(
        "--heartbeat",
        type=int,
        default=_env_int(
            "IPFS_DATASETS_PY_LOGIC_BENCHMARK_HEARTBEAT",
            "IPFS_DATASETS_PY_CODEX_BENCHMARK_HEARTBEAT",
            default=30,
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=_env_int(
            "IPFS_DATASETS_PY_LOGIC_BENCHMARK_TEST_TIMEOUT",
            "IPFS_DATASETS_PY_CODEX_BENCHMARK_TEST_TIMEOUT",
            default=900,
        ),
    )
    parser.add_argument(
        "--remote-cache-network",
        action="store_true",
        help=(
            "Enable distributed mapping-cache networking for remote router caches "
            "in subprocesses (sets IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK=1)."
        ),
    )

    args = parser.parse_args(argv)

    model = str(
        (args.model or "").strip()
        or (os.environ.get("IPFS_DATASETS_PY_LLM_MODEL") or "").strip()
        or (os.environ.get("NEUROSYMBOLIC_ENGINE_MODEL") or "").strip()
        or "gpt-5-mini"
    )

    symai_debug_runpy = bool(
        args.symai_debug_runpy or _truthy(os.environ.get("IPFS_DATASETS_PY_BENCHMARK_SYMAI_DEBUG_RUNPY"))
    )

    workspace = Path(__file__).resolve().parents[1]
    outputs_dir = workspace / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    log_path = Path(
        os.environ.get(
            "IPFS_DATASETS_PY_LOGIC_BENCHMARK_LOG",
            os.environ.get(
                "IPFS_DATASETS_PY_CODEX_BENCHMARK_LOG",
                outputs_dir / "temporal_deontic_benchmark.log",
            ),
        )
    )
    tee_log_path = Path(
        os.environ.get(
            "IPFS_DATASETS_PY_LOGIC_BENCHMARK_TEE_LOG",
            os.environ.get(
                "IPFS_DATASETS_PY_CODEX_BENCHMARK_TEE_LOG",
                workspace.parent / "outputs" / "last_run.log",
            ),
        )
    )
    out_path = Path(
        os.environ.get(
            "IPFS_DATASETS_PY_LOGIC_BENCHMARK_OUTPUT",
            os.environ.get(
                "IPFS_DATASETS_PY_CODEX_BENCHMARK_OUTPUT",
                outputs_dir / "temporal_deontic_benchmark.json",
            ),
        )
    )

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    def log(message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass
        try:
            tee_log_path.parent.mkdir(parents=True, exist_ok=True)
            with tee_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass

    tests: List[Path]
    test_items: List[str]

    if args.tests:
        test_items = [t.strip() for t in str(args.tests).split(",") if t.strip()]
        tests = [workspace / t for t in test_items]
    else:
        env_glob = os.environ.get("IPFS_DATASETS_PY_CODEX_BENCHMARK_TESTS")
        test_glob = str(args.tests_glob or env_glob or "").strip()
        if test_glob:
            tests = _collect_tests(workspace, test_glob)
            test_items = [str(p.relative_to(workspace)) for p in tests]
        else:
            test_items = [
                "tests/test_temporal_deontic_rag.py",
                "tests/top_level_dir_tests/_test_symbolicai_engine.py",
                "scripts/verify_logic_tools_final.py",
                "scripts/verify_lean_proof_execution.py",
                "scripts/verify_coq_proof_execution.py",
                "tests/unit/_test_logic_mcp_tools.py",
            ]
            tests = [workspace / t for t in test_items]
    missing = [str(p) for p in tests if not p.exists()]
    if missing:
        log(f"Missing tests/scripts: {missing}")
        return 2

    base_env = os.environ.copy()
    base_env["PYTHONUNBUFFERED"] = "1"
    base_env.setdefault("LOG_LEVEL", "INFO")
    base_env["IPFS_DATASETS_PY_LOG_DEDUP"] = base_env.get("IPFS_DATASETS_PY_LOG_DEDUP", "1")
    base_env["IPFS_DATASETS_PY_LLM_MODEL"] = model
    if args.provider:
        base_env["IPFS_DATASETS_PY_LLM_PROVIDER"] = str(args.provider)
    if args.remote_cache_network:
        base_env["IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK"] = "1"
    if args.require_lean:
        base_env["IPFS_DATASETS_PY_REQUIRE_LEAN"] = "1"
    if args.require_coq:
        base_env["IPFS_DATASETS_PY_REQUIRE_COQ"] = "1"
    base_env.setdefault("IPFS_DATASETS_PY_PROOF_PROVER", "lean")
    base_env.setdefault("IPFS_DATASETS_PY_PROOF_TIMEOUT", str(int(args.timeout)))

    # Ensure SyMAI doesn't prompt/exit and that tests can route via Codex/IPFS.
    _bootstrap_symai_env_for_benchmark(base_env=base_env, model=model, provider=args.provider, log=log)

    # Mirror historical benchmark behavior: ensure local ipfs_kit_py + workspace are
    # on PYTHONPATH for subprocesses, without requiring installation.
    ipfs_kit_root = workspace / "ipfs_kit_py"
    local_pythonpath = os.pathsep.join([str(ipfs_kit_root), str(workspace)])
    existing_pythonpath = base_env.get("PYTHONPATH", "")
    if existing_pythonpath:
        base_env["PYTHONPATH"] = os.pathsep.join([local_pythonpath, existing_pythonpath])
    else:
        base_env["PYTHONPATH"] = local_pythonpath

    results = {
        "model": model,
        "provider": args.provider or "auto",
        "tests": [str(p.relative_to(workspace)) for p in tests],
        "runs": int(args.runs),
        "timeout": int(args.timeout),
        "heartbeat": int(args.heartbeat),
        "entries": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    log(f"Starting temporal/deontic benchmark model={model} provider={args.provider or 'auto'}")

    for run_idx in range(max(1, int(args.runs))):
        log(f"Run {run_idx + 1}/{args.runs}")
        run_entry = {"index": run_idx, "tests": [], "elapsed_s": 0.0}
        run_start = time.monotonic()

        # Reused from historical codex benchmark: exponential backoff when rate
        # limiting is detected.
        backoff_base = _env_int("IPFS_DATASETS_PY_CODEX_BACKOFF_BASE", default=30)
        backoff_max = _env_int("IPFS_DATASETS_PY_CODEX_BACKOFF_MAX", default=600)
        rate_limit_hits = 0

        for test_path in tests:
            rel = str(test_path.relative_to(workspace))
            log(f"- {rel}")
            start = time.monotonic()
            test_result = _run_test(
                workspace=workspace,
                test_path=test_path,
                env=base_env,
                log=log,
                heartbeat_seconds=int(args.heartbeat),
                timeout_seconds=int(args.timeout),
                symai_debug_runpy=symai_debug_runpy,
            )
            elapsed = time.monotonic() - start
            log(
                f"  exit={test_result['exit_code']} passed={test_result['passed']} "
                f"total={test_result['total']} time={elapsed:.1f}s"
            )
            run_entry["tests"].append({"path": rel, "elapsed_s": elapsed, **test_result})

            if test_result.get("rate_limited"):
                delay = min(backoff_max, backoff_base * (2**rate_limit_hits))
                log(f"Rate limit detected; backing off for {delay}s")
                time.sleep(delay)
                rate_limit_hits += 1
            else:
                rate_limit_hits = 0

        run_entry["elapsed_s"] = time.monotonic() - run_start
        results["entries"].append(run_entry)

    results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log(f"Wrote benchmark results to {out_path}")
    log(f"Wrote benchmark log to {log_path}")

    # Overall exit code: fail if any test failed.
    for entry in results["entries"]:
        for t in entry["tests"]:
            if int(t.get("exit_code", 0)) != 0:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
