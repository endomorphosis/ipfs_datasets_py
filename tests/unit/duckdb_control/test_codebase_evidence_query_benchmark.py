"""No native execution: workload controls and qualification protocol failures."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

BENCHMARKS = Path(__file__).resolve().parents[3] / "benchmarks"
sys.path.insert(0, str(BENCHMARKS))
import bench_codebase_evidence_queries as bench


def test_fixture_has_distinct_sources_and_explicit_proved_refuted_vacuous_controls():
    rows = bench.fixture_units()
    assert len(rows) == len({row.path for row in rows}) == len({row.source for row in rows}) == 8
    assert all(len(row.source) < 128 for row in rows)
    assert sum(row.expected_status == "recorded_conditional_proved" for row in rows) == 6
    assert rows[6].requested_offset != rows[6].body_offset and rows[6].domain_predicate == "True"
    assert rows[7].requested_offset == rows[7].body_offset and rows[7].domain_predicate == "False"
    assert all(row.native()[0].function_name == row.native()[1].function_name == "increment" for row in rows)


def test_fixture_compiles_all_eight_exact_captured_sources_without_execution(monkeypatch):
    from ipfs_datasets_py.logic.software_verification.pipeline import SourceToVerificationPipeline
    monkeypatch.setattr(bench.subprocess, "Popen", lambda *a, **kw: pytest.fail("compile-only fixture launched a process"))
    for unit in bench.fixture_units():
        contract, _ = unit.native()
        result = SourceToVerificationPipeline(execute_solvers=False, include_supervisor_evidence=False).run(
            unit.source.decode(), path=unit.path, language="python", contracts=[contract], revision="fixture:1")
        assert result.program is not None
        assert len(result.contracts) == len(result.vc_sets) == 1


@pytest.mark.parametrize("argv,kind", [
    (["/usr/bin/z3", "-in", "-smt2"], "solver_query"),
    (["/usr/bin/z3", "--version"], "version"),
    (["/tools/cvc5", "--lang=smt2"], "solver_query"),
    (["/tools/cvc5", "--version"], "version"),
    (["git", "status", "--porcelain"], "git"),
])
def test_audit_distinguishes_actual_query_and_version_launches(argv, kind):
    audit = bench.ProcessAudit()
    with audit.scope("production"):
        audit.observe("subprocess.Popen", (argv[0], argv, None, {}))
    assert audit.counts == {"production:" + kind: 1}
    assert audit.events[0]["argv"] == argv


@pytest.mark.parametrize("argv", [["z3", "-in"], ["cvc5", "--version"], ["/usr/bin/prlimit", "--", "z3"]])
def test_solver_free_guard_refuses_any_non_git_launcher_and_restores_scope(argv):
    audit = bench.ProcessAudit()
    with pytest.raises(AssertionError, match="non-Git"):
        with audit.scope("lookup", only_git=True):
            audit.observe("subprocess.Popen", (argv[0], argv, None, {}))
    assert (audit.stage, audit.only_git) == ("startup", False)
    assert audit.events[0]["stage"] == "lookup"


class Projection:
    verification = SimpleNamespace(observed_live=False)
    applicability = None

    def to_dict(self):
        return {"authority": {"historical_conditional_evidence": True, "kernel_checked": False}}


class Cursor:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return {"position": self.value}


def page(ids, *, inventory="inventory:1", epoch=1, next_cursor=None, complete=True, start_cursor=None):
    return SimpleNamespace(entries=tuple(SimpleNamespace(entry_id=item, projection=Projection()) for item in ids),
        complete=complete, next_cursor=next_cursor, inventory_cid=inventory, epoch=epoch,
        to_dict=lambda: {"inventory_cid": inventory, "epoch": epoch, "entries": ids,
                         "start_cursor": None if start_cursor is None else start_cursor.to_dict()})


def traverse(pages):
    pending = iter(pages)
    catalog = SimpleNamespace(query_current=lambda *args, **kwargs: next(pending))
    return bench.traverse(catalog, "repository", "head", "selector", SimpleNamespace(options=lambda: {}), page_size=3)


def test_pages_require_stable_complete_sorted_unique_inventory():
    rows, receipts = traverse([page(["a", "b", "c"], next_cursor=Cursor(1), complete=False),
                              page(["d"], start_cursor=Cursor(1))])
    assert rows == ["a", "b", "c", "d"] and len(receipts) == 2


@pytest.mark.parametrize("pages,message", [
    ([page(["a"], next_cursor=Cursor(1), complete=False), page(["a"], start_cursor=Cursor(1))], "repeated"),
    ([page(["b"], next_cursor=Cursor(1), complete=False), page(["a"], start_cursor=Cursor(1))], "reordered"),
    ([page(["a"], next_cursor=Cursor(1), complete=False), page(["b"], epoch=2, start_cursor=Cursor(1))], "inventory drift"),
    ([page([], next_cursor=Cursor(1), complete=False)], "nonterminal empty"),
    ([page(["a"], next_cursor=Cursor(1), complete=True)], "terminal page"),
    ([page(["a", "b", "c", "d"])], "requested bound"),
    ([page(["a"], next_cursor=Cursor(1), complete=False), page(["b"])], "starting range"),
])
def test_broken_paging_cannot_produce_qualification_success(pages, message):
    with pytest.raises(AssertionError, match=message):
        traverse(pages)


def test_cancelled_overall_deadline_prevents_new_admission():
    deadline = bench.Deadline(10, 2)
    try:
        assert deadline.options()["timeout_seconds"] <= 2
        deadline.cancelled.set()
        with pytest.raises(AssertionError, match="deadline"):
            deadline.options()
    finally:
        deadline.close()
