import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


DEFAULT_MODELS = [
    "gpt-5.2-codex",
    "gpt-5.1-codex-mini",
    "gpt-5.1-codex-max",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5.1-codex",
    "gpt-5-codex",
    "gpt-5-codex-mini",
    "gpt-5",
]


def _parse_model_list(value: str) -> List[str]:
    if not value:
        return []
    models = [item.strip() for item in value.split(",")]
    return [m for m in models if m]


def _parse_summary(output: str) -> Dict[str, int]:
    passed = 0
    total = 0
    for line in output.splitlines():
        if "Summary:" in line and "/" in line:
            parts = line.split("Summary:")[-1].strip().split()[0]
            if "/" in parts:
                left, right = parts.split("/", 1)
                if left.isdigit() and right.isdigit():
                    passed = max(passed, int(left))
                    total = max(total, int(right))
    return {"passed": passed, "total": total}


def _run_test(test_path: Path, env: Dict[str, str]) -> Dict[str, object]:
    proc = subprocess.run(
        [sys.executable, str(test_path)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    summary = _parse_summary(output)
    return {
        "exit_code": proc.returncode,
        "passed": summary["passed"],
        "total": summary["total"],
        "output": output[-4000:],
    }


def _collect_tests(workspace: Path) -> List[Path]:
    test_glob = os.environ.get(
        "IPFS_DATASETS_PY_CODEX_BENCHMARK_TESTS",
        "tests/top_level_dir_tests/_test_symbolicai_*.py",
    )
    return sorted(workspace.glob(test_glob))


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    env_models = _parse_model_list(os.environ.get("IPFS_DATASETS_PY_CODEX_MODEL_LIST", ""))
    models = env_models or DEFAULT_MODELS

    tests = _collect_tests(workspace)
    if not tests:
        print("No tests found to run.")
        return 1

    runs = int(os.environ.get("IPFS_DATASETS_PY_CODEX_BENCHMARK_RUNS", "1"))
    results = {
        "models": models,
        "tests": [str(p) for p in tests],
        "runs": runs,
        "entries": [],
    }

    base_env = os.environ.copy()
    base_env["IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI"] = "1"

    for model in models:
        model_entry = {
            "model": model,
            "runs": [],
        }
        for run_idx in range(runs):
            run_entry = {
                "index": run_idx,
                "tests": [],
                "exit_code": 0,
                "passed": 0,
                "total": 0,
                "failures": 0,
            }
            env = base_env.copy()
            env["IPFS_DATASETS_PY_CODEX_MODEL"] = model

            for test_path in tests:
                test_result = _run_test(test_path, env)
                run_entry["tests"].append(
                    {
                        "path": str(test_path),
                        **test_result,
                    }
                )
                run_entry["exit_code"] |= int(test_result["exit_code"] != 0)
                run_entry["passed"] += test_result["passed"]
                run_entry["total"] += test_result["total"]
                if test_result["exit_code"] != 0:
                    run_entry["failures"] += 1

            model_entry["runs"].append(run_entry)

        results["entries"].append(model_entry)

    output_path = Path(os.environ.get(
        "IPFS_DATASETS_PY_CODEX_BENCHMARK_OUTPUT",
        workspace / "outputs" / "codex_model_benchmark.json",
    ))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"Wrote benchmark results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
