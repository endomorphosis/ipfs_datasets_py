"""Verify retained execution evidence with class-aware JUnit module coverage.

The execution receipt is preserved unchanged, including its incorrect coverage
flag. Only the coordinator's coverage calculation is corrected. This performs
no pytest, product import, source replay, model, signature or network operation.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    phase = Path(__file__).resolve().parent
    run = phase / "qualification-v02"
    current_driver = phase / "qualification_runner.py"
    current = runpy.run_path(str(current_driver))
    original = runpy.run_path(str(run / "execution-runner.py.txt"))
    assert current["TEST_MODULES"] == original["TEST_MODULES"]
    binding = current["binding"]
    receipt = json.loads((run / "receipt.json").read_text())
    inputs = json.loads((run / "run-inputs.json").read_text())
    assert inputs == {key: receipt[key] for key in ("head", "index_tree", "input_inventory")}
    assert receipt["exit_code"] == 0 and receipt["stop_reason"] is None
    assert receipt["inputs_unchanged"] is True and receipt["junit_present"] is True
    assert receipt["all_target_modules_covered"] is False and receipt["receipt_passed"] is False
    assert receipt["unique_cases"] is True
    for name, expected in receipt["outputs"].items():
        assert binding(run / name) == expected, name
    driver_name = str(current_driver.relative_to(root))
    for name, expected in receipt["input_inventory"].items():
        path = run / "execution-runner.py.txt" if name == driver_name else root / name
        assert binding(path) == expected, name
    subprocess.run(["git", "merge-base", "--is-ancestor", receipt["head"], "HEAD"], check=True)
    cases = list(ET.parse(run / "junit.xml").getroot().iter("testcase"))
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    assert len(cases) == len(set(identities)) == receipt["test_cases"] == 1565
    counts = {kind: sum(case.find(kind) is not None for case in cases) for kind in ("failure", "error", "skipped")}
    assert counts == receipt["counts"] == {"failure": 0, "error": 0, "skipped": 0}
    assert current["all_modules_covered"](cases) is True
    by_class = dict(collections.Counter(case.get("classname") for case in cases))
    assert by_class == receipt["cases_by_class"]
    by_module = {}
    for name in current["TEST_MODULES"]:
        prefix = "tests.unit.logic.autoformal.test_" + name
        by_module[name] = sum(count for classname, count in by_class.items()
                              if classname == prefix or classname.startswith(prefix + "."))
    assert sum(by_module[name] for name in current["TEST_MODULES"][:5]) == 982
    assert by_class["tests.unit.logic.autoformal.test_corpus_source.SourceCorpusTests"] == 15
    result = {"schema": "legal-source-review-stack-recount/v1", "execution_head": receipt["head"],
        "test_cases": len(cases), "unique_cases": True, "counts": counts,
        "cases_by_module": by_module, "all13_target_modules_covered": True,
        "new_stack_cases": 982, "current_product_and_test_inputs_match_execution": True,
        "original_execution_driver_matches_pinned_snapshot": True,
        "original_execution_inputs_unchanged": True,
        "execution_receipt": binding(run / "receipt.json"),
        "raw_outputs": receipt["outputs"],
        "corrected_driver": binding(current_driver), "recount_driver": binding(Path(__file__)),
        "correction": "JUnit may append a unittest class; use exact module or module-dot prefix, preserving the original false coverage receipt",
        "tests_rerun_for_accounting_correction": False, "receipt_passed": True,
        "authority": {"real_statutory_review_completed": False, "source_semantics_verified": False,
                      "training_qualified": False, "proof_authority": False, "published": False}}
    target = run / "recount.json"
    if args.check:
        assert json.loads(target.read_text()) == result
    else:
        with target.open("x") as stream:
            stream.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("test_cases", "counts", "all13_target_modules_covered", "receipt_passed")}))


if __name__ == "__main__":
    main()
