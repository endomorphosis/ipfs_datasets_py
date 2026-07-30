"""Cross-language parity for RuntimeMTLMonitor@1 (Python ↔ TypeScript)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
    RUNTIME_MTL_INTERFACE,
    MonitorAuthority,
    MonitorEvaluation,
    RuntimeMTLMonitor,
    evaluate_case,
    evaluate_portable,
    golden_fixtures,
)

REPO_IPFS_DATASETS = Path(__file__).resolve().parents[3]
TS_PACKAGE = REPO_IPFS_DATASETS / "typescript" / "logic-runtime-mtl"
TS_INDEX = TS_PACKAGE / "dist" / "src" / "index.js"


def _ensure_typescript_built() -> Path:
    if not TS_PACKAGE.is_dir():
        pytest.skip(f"TypeScript package missing: {TS_PACKAGE}")
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        pytest.skip("node/npm required for TypeScript parity")
    if not (TS_PACKAGE / "node_modules").is_dir():
        install = subprocess.run(
            [npm, "install", "--no-fund", "--no-audit"],
            cwd=TS_PACKAGE,
            capture_output=True,
            text=True,
            check=False,
        )
        if install.returncode != 0:
            pytest.fail(
                "npm install failed for logic-runtime-mtl:\n"
                f"{install.stdout}\n{install.stderr}"
            )
    build = subprocess.run(
        [npm, "run", "build"],
        cwd=TS_PACKAGE,
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0 or not TS_INDEX.is_file():
        pytest.fail(
            "TypeScript build failed for logic-runtime-mtl:\n"
            f"{build.stdout}\n{build.stderr}"
        )
    return TS_INDEX


def _evaluate_typescript(case: dict) -> dict:
    index = _ensure_typescript_built()
    payload = {
        "case_id": case.get("case_id"),
        "formula": case["formula"],
        "trace": case["trace"],
        "position": case.get("position", 0),
        "schema_version": case.get("schema_version"),
        "interface": case.get("interface", RUNTIME_MTL_INTERFACE),
    }
    # Import the built package entrypoint (cwd = package root).
    del index  # ensured above; import uses package-relative path
    script = """
import { evaluateCase } from './dist/src/index.js';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
process.stdout.write(JSON.stringify(evaluateCase(payload)));
"""
    proc = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=TS_PACKAGE,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"TypeScript evaluate failed for {case.get('case_id')}:\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
    return json.loads(proc.stdout)


def _assert_expected(result: dict, expected: dict, case_id: str) -> None:
    for key, value in expected.items():
        assert result[key] == value, f"{case_id}: field {key} expected {value!r} got {result.get(key)!r}"
    assert result["authority"] == MonitorAuthority.MONITOR.value
    assert result["authorizes_global_proof"] is False
    assert result["interface"] == RUNTIME_MTL_INTERFACE


def test_python_golden_fixtures() -> None:
    for case in golden_fixtures():
        result = evaluate_case(
            {
                "formula": case["formula"],
                "trace": case["trace"],
                "position": case.get("position", 0),
            }
        )
        _assert_expected(result, case["expected"], case["case_id"])
        restored = MonitorEvaluation.from_dict(result)
        assert restored.to_dict() == result


def test_clean_prefix_never_becomes_proof() -> None:
    case = next(c for c in golden_fixtures() if c["case_id"] == "prefix-always-inconclusive")
    result = evaluate_portable(case["formula"], case["trace"])
    assert result.verdict.value == "inconclusive"
    assert result.status.value == "unknown"
    assert result.authority is MonitorAuthority.MONITOR
    assert result.authorizes_global_proof is False
    with pytest.raises(Exception):
        # authorizes_global_proof is frozen false; constructing proof-true fails
        MonitorEvaluation(
            verdict=result.verdict,
            status=result.status,
            authority=MonitorAuthority.MONITOR,
            logic=result.logic,
            trace_kind=result.trace_kind,
            monitorability=result.monitorability,
            position=result.position,
            reason=result.reason,
            authorizes_global_proof=True,
        )


def test_interval_boundary_and_late_event_semantics() -> None:
    closed = next(
        c for c in golden_fixtures() if c["case_id"] == "mtl-closed-interval-includes-boundary"
    )
    open_upper = next(
        c for c in golden_fixtures() if c["case_id"] == "mtl-open-upper-excludes-boundary"
    )
    late = next(c for c in golden_fixtures() if c["case_id"] == "late-event-malformed")
    assert evaluate_case(closed)["verdict"] == "true"
    assert evaluate_case(open_upper)["verdict"] == "false"
    late_result = evaluate_case(late)
    assert late_result["status"] == "malformed"
    assert late_result["late_events"] is True
    assert late_result["authority"] == "monitor"


def test_monitor_serialization_roundtrip() -> None:
    case = golden_fixtures()[0]
    monitor = RuntimeMTLMonitor.from_dict(
        {
            "formula": case["formula"],
            "position": 0,
            "interface": RUNTIME_MTL_INTERFACE,
        }
    )
    wire = monitor.to_dict()
    assert wire["interface"] == RUNTIME_MTL_INTERFACE
    again = RuntimeMTLMonitor.from_dict(wire)
    assert again.evaluate(case["trace"]).to_dict() == monitor.evaluate(case["trace"]).to_dict()


def test_python_typescript_parity_on_golden_fixtures() -> None:
    _ensure_typescript_built()
    for case in golden_fixtures():
        py_result = evaluate_case(
            {
                "formula": case["formula"],
                "trace": case["trace"],
                "position": case.get("position", 0),
            }
        )
        ts_result = _evaluate_typescript(case)
        # Full portable result equality (keys sorted for stable compare of optional fields).
        assert set(py_result) == set(ts_result), case["case_id"]
        for key in sorted(py_result):
            assert py_result[key] == ts_result[key], (
                f"{case['case_id']}: mismatch on {key}: "
                f"python={py_result[key]!r} typescript={ts_result[key]!r}"
            )
        _assert_expected(ts_result, case["expected"], f"ts:{case['case_id']}")


def test_typescript_package_layout() -> None:
    required = [
        TS_PACKAGE / "package.json",
        TS_PACKAGE / "tsconfig.json",
        TS_PACKAGE / "src" / "index.ts",
        TS_PACKAGE / "test" / "runtime_mtl.test.ts",
    ]
    for path in required:
        assert path.is_file(), f"missing TypeScript evidence path: {path}"
    package = json.loads((TS_PACKAGE / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == "@ipfs-datasets/logic-runtime-mtl"
    assert "test" in package["scripts"]


if __name__ == "__main__":
    # Allow ad-hoc: python -m pytest ... or direct execution for smoke.
    sys.exit(pytest.main([__file__, "-q"]))
