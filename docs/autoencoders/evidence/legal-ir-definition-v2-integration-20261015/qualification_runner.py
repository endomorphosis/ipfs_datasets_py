"""Qualify the V2 definition integration and affected legacy/corpus boundaries.

Run from the repository root with an exclusive artifact directory. Native build
gates use the suites' explicit process stubs; no real Lean build is claimed.
The inventory is listed local source/test inputs, not a complete import closure.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

TEST_MODULES = (
    "legal_source_definition_bridge_v2", "corpus_definition_adapter_v2",
    "legal_source_definition_bridge", "legal_source_definition_norm_bridge",
    "corpus_definition_norm_adapter", "corpus_definition_review",
    "legal_source_definition_lake", "legal_source_definition_norm_lake",
    "legal_corpus_lake", "legal_corpus_shared_lake", "legal_corpus_incremental",
    "corpus_imports", "legal_source_sampling", "legal_statutory_context_v2",
    "legal_official_document_views", "legal_official_source_custody",
    "corpus_source", "corpus_contracts", "corpus_graph", "corpus_graph_exchange",
    "legal_source_representability", "legal_context_representability_integration",
    "definition_v2_graph_exchange",
)


def binding(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def coverage(cases):
    expected = {"tests.unit.logic.autoformal.test_" + name for name in TEST_MODULES}
    observed = set()
    for case in cases:
        classname = case.get("classname") or ""
        matches = {name for name in expected if classname == name or classname.startswith(name + ".")}
        if len(matches) != 1:
            return False
        observed.update(matches)
    return observed == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    targets = ["tests/unit/logic/autoformal/test_" + name + ".py" for name in TEST_MODULES]
    assert all((root / name).is_file() for name in targets), "complete target test population required"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir()
    paths = set()
    for directory in ("ipfs_datasets_py/logic/autoformal", "tests/unit/logic/autoformal",
                      "ipfs_datasets_py/logic/TDFOL", "ipfs_datasets_py/logic/FOL",
                      "ipfs_datasets_py/logic/intent_ir/formalize", "ipfs_datasets_py/logic/backends"):
        paths.update(root.glob(directory + "/*.py"))
    paths.update(root / name for name in ("ipfs_datasets_py/logic/profile_g.py",
        "ipfs_datasets_py/utils/cid_utils.py", "ipfs_datasets_py/__init__.py",
        "ipfs_datasets_py/logic/__init__.py", "tests/conftest.py", "pytest.ini",
        "scripts/ops/legal_ir/check_legal_definition_norm_binding.py"))
    paths.add(Path(__file__).resolve())
    names = sorted(str(path.relative_to(root)) for path in paths)
    before = {name: binding(root / name) for name in names}
    head, index = git("rev-parse", "HEAD"), git("write-tree")
    (output / "run-inputs.json").write_text(json.dumps({"head": head, "index_tree": index,
        "input_inventory": before}, indent=2, sort_keys=True) + "\n")
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH") if key in os.environ}
    env.update({"PYTHONHASHSEED": "0", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "GITHUB_TOKEN": "offline-test-sentinel-not-a-credential", "PYTHONPATH": str(root),
        "TMPDIR": str(private), "XDG_CACHE_HOME": str(private / "cache"), "HF_HOME": str(private / "hf")})
    command = [sys.executable, "-m", "pytest", "-o",
        "addopts=-v --tb=short --strict-markers --import-mode=importlib",
        "-p", "xdist.plugin", "-n", "3", "--dist=loadfile",
        "-o", "cache_dir=" + str(private / "pytest-cache"),
        "--basetemp=" + str(private / "tmp"), "--junitxml=" + str(output / "junit.xml"), *targets]
    started = time.monotonic()
    stop_reason = None
    with (output / "stdout.txt").open("xb") as stdout, (output / "stderr.txt").open("xb") as stderr:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=stdout, stderr=stderr,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            exit_code = process.wait(timeout=1200)
        except subprocess.TimeoutExpired:
            stop_reason = "bounded_1200_second_test_timeout"
            os.killpg(process.pid, signal.SIGTERM)
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                exit_code = process.wait()
    after = {name: binding(root / name) for name in names}
    junit_present = (output / "junit.xml").is_file()
    cases = list(ET.parse(output / "junit.xml").getroot().iter("testcase")) if junit_present else []
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    counts = {kind: sum(case.find(kind) is not None for case in cases) for kind in ("failure", "error", "skipped")}
    unchanged = before == after and git("rev-parse", "HEAD") == head and git("write-tree") == index
    unique = len(identities) == len(set(identities))
    covered = coverage(cases)
    report = {"schema": "legal-definition-v2-integration-qualification/v1", "head": head,
        "index_tree": index, "command": command, "exit_code": exit_code,
        "elapsed_seconds": time.monotonic() - started, "stop_reason": stop_reason,
        "junit_present": junit_present, "workers": 3, "distribution": "loadfile", "python_hash_seed": 0,
        "versions": {name: version(name) for name in ("pytest", "pytest-xdist", "cryptography", "pyarrow")},
        "input_inventory": before, "inputs_unchanged": unchanged,
        "test_cases": len(cases), "unique_cases": unique, "counts": counts,
        "cases_by_class": dict(collections.Counter(case.get("classname") for case in cases)),
        "all_target_modules_covered": covered,
        "receipt_passed": exit_code == 0 and stop_reason is None and bool(cases) and unique and covered and unchanged and not any(counts.values()),
        "scope": "authored V2/legacy/source/corpus fixtures and explicitly stubbed build gates",
        "authority": {"real_statutory_review_completed": False, "training_qualified": False,
                      "Lean_execution_qualified": False, "source_semantics_verified": False, "published": False}}
    report["outputs"] = {name: binding(output / name) for name in ("stdout.txt", "stderr.txt", "junit.xml", "run-inputs.json") if (output / name).is_file()}
    (output / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("test_cases", "counts", "inputs_unchanged", "receipt_passed")}))
    return 0 if report["receipt_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
