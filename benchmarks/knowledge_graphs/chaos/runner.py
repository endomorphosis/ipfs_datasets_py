"""Run the isolated chaos suite and emit a content-addressed receipt."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.knowledge_graphs.receipt import capture_environment, content_digest

JSONDict = dict[str, Any]
CHAOS_RECEIPT_SCHEMA = "ipfs-datasets.knowledge-graphs.chaos-receipt.v1"
CHAOS_RECEIPT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ChaosRunResult:
    status: str
    returncode: int
    receipt_path: Path
    junit_path: Path
    receipt: JSONDict


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _junit_summary(path: Path) -> JSONDict:
    if not path.is_file():
        return {
            "tests": 0,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "duration_s": 0.0,
            "problem_tests": [],
        }
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    summary: JSONDict = {
        "tests": sum(int(s.get("tests", "0")) for s in suites),
        "failures": sum(int(s.get("failures", "0")) for s in suites),
        "errors": sum(int(s.get("errors", "0")) for s in suites),
        "skipped": sum(int(s.get("skipped", "0")) for s in suites),
        "duration_s": sum(float(s.get("time", "0")) for s in suites),
        "problem_tests": [],
    }
    problems = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            problems.append(
                "::".join(
                    part
                    for part in (case.get("classname"), case.get("name"))
                    if part
                )
            )
    summary["problem_tests"] = problems[:100]
    return summary


def run_chaos_suite(
    *,
    repo_root: Path | str,
    work_dir: Path | str,
    receipt_path: Path | str,
    environment_id: str,
    timeout_s: float = 900.0,
    pytest_args: Sequence[str] = (),
) -> ChaosRunResult:
    """Execute only ``tests/chaos/knowledge_graphs`` and retain its evidence."""
    env_id = str(environment_id).strip()
    if not env_id or env_id.lower() in {"unknown", "unlabelled", "unlabeled", "none"}:
        raise ValueError("environment_id must be a non-empty labelled environment")
    root = Path(repo_root).resolve()
    work = Path(work_dir).resolve()
    output = Path(receipt_path).resolve()
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    junit = work / "chaos-junit.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/chaos/knowledge_graphs",
        "--junitxml",
        str(junit),
        *list(pytest_args),
    ]
    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
            check=False,
        )
        returncode = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = (
            exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        )
        stderr = (
            exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
        )
    elapsed = time.time() - started
    summary = _junit_summary(junit)
    status = (
        "success"
        if (
            returncode == 0
            and summary["tests"] > 0
            and summary["failures"] == 0
            and summary["errors"] == 0
        )
        else "failed"
    )
    receipt: JSONDict = {
        "schema": CHAOS_RECEIPT_SCHEMA,
        "schema_version": CHAOS_RECEIPT_SCHEMA_VERSION,
        "created_at": started,
        "environment_id": env_id,
        "environment": capture_environment(repo_root=root),
        "suite": "tests/chaos/knowledge_graphs",
        "command": command,
        "timeout_s": float(timeout_s),
        "timed_out": timed_out,
        "elapsed_s": elapsed,
        "returncode": returncode,
        "summary": summary,
        "junit_path": str(junit),
        "junit_sha256": _file_sha256(junit),
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "status": status,
    }
    receipt["digest"] = content_digest(receipt)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return ChaosRunResult(
        status=status,
        returncode=returncode,
        receipt_path=output,
        junit_path=junit,
        receipt=receipt,
    )
