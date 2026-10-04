"""Large Git audit retention stays bounded without hiding refused launches."""
from collections import Counter
import gzip
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "benchmarks"))
import bench_codebase_query_many as benchmark


def test_audit_retains_full_order_beyond_previous_in_memory_ceiling(tmp_path):
    audit = benchmark.ProcessAudit(tmp_path / "audit.jsonl.gz")
    with audit.scope("lookup", only_git=True):
        for index in range(17000):
            audit.observe("subprocess.Popen", ("git", ["git", "cat-file", "blob", str(index)], "/fixture", None))
    result = audit.finish()
    assert len(result["events"]) == 32
    assert result["counts"] == {"lookup:git": 17000}
    assert result["ledger"]["records"] == 17000
    counts, raw_bytes = Counter(), 0
    with gzip.open(result["ledger"]["path"], "rb") as stream:
        for index, raw in enumerate(stream):
            row = json.loads(raw)
            assert row["argv"][-1] == str(index)
            assert row["stage"] == "lookup"
            counts[row["kind"]] += 1
            raw_bytes += len(raw)
    assert counts == {"git": 17000}
    assert raw_bytes == result["ledger"]["uncompressed_bytes"]


def test_solver_refusal_remains_visible_in_compressed_audit(tmp_path):
    audit = benchmark.ProcessAudit(tmp_path / "audit.jsonl.gz")
    with pytest.raises(AssertionError, match="non-Git"):
        with audit.scope("lookup", only_git=True):
            audit.observe("subprocess.Popen", ("prlimit", ["prlimit", "--", "z3", "-in"], "/fixture", None))
    result = audit.finish()
    assert result["counts"] == {"lookup:solver_query": 1}
    assert result["events"][0]["kind"] == "solver_query"
    with gzip.open(result["ledger"]["path"], "rt") as stream:
        assert [json.loads(line) for line in stream] == result["events"]


@pytest.mark.parametrize("bound", ["max_records", "max_bytes"])
def test_ledger_bound_refuses_before_retaining_another_event(tmp_path, bound):
    audit = benchmark.ProcessAudit(tmp_path / "audit.jsonl.gz")
    setattr(audit, bound, 0)
    try:
        with pytest.raises(AssertionError, match="ledger input bound"):
            audit.observe("subprocess.Popen", ("git", ["git", "status"], "/fixture", None))
        assert audit.records == 0 and audit.raw_bytes == 0
    finally:
        audit.finish()
    with gzip.open(audit.path, "rb") as stream:
        assert stream.read() == b""
