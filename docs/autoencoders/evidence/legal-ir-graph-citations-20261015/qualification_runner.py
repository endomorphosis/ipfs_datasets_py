"""Bounded, offline citation regression and affected-suite receipts.

Run from the repository root with an exclusive output directory. Baseline is
expected to fail exactly the new writer-to-reader regression; qualification
must pass every collected case with no skips. Inventories bind the listed
inputs only, not an exhaustive Python import closure or production dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

BASELINE = ["tests/unit/logic/test_kg_graph_citation_identity.py::test_current_wrapped_graph_parquet_preserves_exact_citation_identity"]
QUALIFICATION = [
    "tests/unit/logic/test_kg_graph_citation_identity.py",
    "tests/unit/logic/autoformal/test_legal_primary_graph_records.py",
    "tests/unit/logic/autoformal/test_legal_primary_graph_manifest.py",
    "tests/unit/logic/autoformal/test_legal_primary_graph_reconstruction.py",
    "tests/unit/logic/autoformal/test_legal_source_sampling.py",
    "tests/unit/logic/test_ingest_ipfs_uscode_entities.py",
    "tests/unit/logic/test_entity_cache.py",
    "tests/unit/logic/test_meta_ontology.py",
    "tests/unit/logic/test_law_package.py",
    "tests/unit/processors/legal_data/test_uscode_hf_release.py",
    "tests/security/test_uscode_hf_release.py",
]
OWNERS = [
    "scripts/ops/legal_ir/publish_kg_meta_ontology.py",
    "scripts/ops/legal_ir/ingest_ipfs_uscode_entities.py",
    "ipfs_datasets_py/logic/autoformal/legal_primary_graph_records.py",
    "ipfs_datasets_py/logic/autoformal/legal_primary_graph_manifest.py",
    "ipfs_datasets_py/logic/autoformal/legal_primary_graph_reconstruction.py",
    "ipfs_datasets_py/processors/legal_data/uscode_hf_release.py",
    "ipfs_datasets_py/processors/legal_data/uscode_release_schema.py",
    "tests/conftest.py", "pytest.ini",
]


def digest(path):
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("baseline", "qualification"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    targets = BASELINE if args.profile == "baseline" else QUALIFICATION
    paths = sorted(set(OWNERS + [target.split("::")[0] for target in targets]
                       + [str(Path(__file__).resolve().relative_to(root))]
                       + ([] if args.profile == "baseline" else [
                           "ipfs_datasets_py/logic/autoformal/legal_source_sampling.py",
                           "docs/autoencoders/legal_source_sampling.md"])))
    before = {path: digest(root / path) for path in paths}
    head, index = git("rev-parse", "HEAD"), git("write-tree")
    # Preserve the original regression independently of later added cases.
    if args.profile == "baseline":
        (output / "regression.py.txt").write_bytes((root / BASELINE[0].split("::")[0]).read_bytes())
    private = output / "private"
    private.mkdir()
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH") if key in os.environ}
    env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "GITHUB_TOKEN": "offline-test-sentinel-not-a-credential",
        "TMPDIR": str(private), "XDG_CACHE_HOME": str(private / "cache"),
        "HF_HOME": str(private / "hf"), "PYTHONPATH": str(root)})
    command = [sys.executable, "-m", "pytest", "-o",
        "addopts=-v --tb=short --strict-markers --import-mode=importlib",
        "-o", "cache_dir=" + str(private / "pytest-cache"),
        "--basetemp=" + str(private / "tmp"), "--junitxml=" + str(output / "junit.xml"), *targets]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=600)
    (output / "stdout.txt").write_bytes(result.stdout)
    (output / "stderr.txt").write_bytes(result.stderr)
    after = {path: digest(root / path) for path in paths}
    cases = list(ET.parse(output / "junit.xml").getroot().iter("testcase"))
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    counts = {key: sum(case.find(key) is not None for case in cases) for key in ("failure", "error", "skipped")}
    guards = before == after and git("rev-parse", "HEAD") == head and git("write-tree") == index
    unique = len(identities) == len(set(identities))
    expected = (result.returncode == 1 and len(cases) == 1 and counts == {"failure": 1, "error": 0, "skipped": 0}
        and cases[0].get("name") == BASELINE[0].split("::")[1]
        and "source_legal_id" in (cases[0].find("failure").text or "")) if args.profile == "baseline" else (
        result.returncode == 0 and len(cases) > 0 and not any(counts.values()))
    report = {"schema": "legal-graph-citation-qualification/v1", "profile": args.profile,
        "head": head, "index_tree": index, "command": command, "exit_code": result.returncode,
        "input_inventory": before, "inputs_unchanged": guards, "unique_cases": unique,
        "test_cases": len(cases), "counts": counts, "expected_result_observed": expected,
        "receipt_passed": guards and unique and expected,
        "scope": "listed local inputs and synthetic private files; no production cache or model qualification",
        "authority": {"legal_semantics_verified": False, "proof_authority": False,
                      "training_qualified": False, "production_graph_repaired": False, "published": False}}
    report["outputs"] = {name: digest(output / name) for name in ("stdout.txt", "stderr.txt", "junit.xml")}
    (output / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("profile", "test_cases", "counts", "receipt_passed")}))
    return 0 if report["receipt_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
