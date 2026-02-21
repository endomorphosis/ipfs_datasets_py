"""Batch-134 feature tests.

Methods under test:
  - OntologyOptimizer.export_history_csv(filepath)
  - OntologyOptimizer.history_as_dicts()
  - OntologyPipeline.stabilization_index(window)
  - OntologyPipeline.run_improvement()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg, trend="stable"):
        self.average_score = avg
        self.trend = trend
        self.best_ontology = {}
        self.worst_ontology = {}
        self.metadata = {}


def _push_opt(opt, avg):
    opt._history.append(_FakeEntry(avg))


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, overall):
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    p._run_history.append(run)


# ---------------------------------------------------------------------------
# OntologyOptimizer.export_history_csv
# ---------------------------------------------------------------------------

class TestExportHistoryCsv:
    def test_empty_returns_header_only(self):
        o = _make_optimizer()
        csv = o.export_history_csv()
        assert "batch_from" in csv or "index" in csv  # any header is fine

    def test_returns_string_when_no_path(self):
        o = _make_optimizer()
        for v in [0.3, 0.6, 0.9]:
            _push_opt(o, v)
        result = o.export_history_csv()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_writes_to_file(self, tmp_path):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        _push_opt(o, 0.7)
        fpath = str(tmp_path / "hist.csv")
        returned = o.export_history_csv(fpath)
        # External implementation returns None when writing to file
        assert returned is None
        with open(fpath) as f:
            content = f.read()
        assert len(content) > 0

    def test_pairwise_rows(self):
        o = _make_optimizer()
        for v in [0.3, 0.6, 0.9]:
            _push_opt(o, v)
        csv_str = o.export_history_csv()
        lines = [l for l in csv_str.strip().split("\n") if l]
        # header + 2 pairs for 3 entries
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_as_dicts
# ---------------------------------------------------------------------------

class TestHistoryAsDicts:
    def test_empty(self):
        o = _make_optimizer()
        assert o.history_as_dicts() == []

    def test_returns_list_of_dicts(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        result = o.history_as_dicts()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_contains_expected_keys(self):
        o = _make_optimizer()
        _push_opt(o, 0.6)
        d = o.history_as_dicts()[0]
        assert "index" in d
        assert "average_score" in d
        assert "trend" in d

    def test_values_correct(self):
        o = _make_optimizer()
        _push_opt(o, 0.75)
        d = o.history_as_dicts()[0]
        assert d["index"] == 0
        assert d["average_score"] == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# OntologyPipeline.stabilization_index
# ---------------------------------------------------------------------------

class TestStabilizationIndex:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.stabilization_index() == 0.0

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.stabilization_index() == 0.0

    def test_stable_runs_near_one(self):
        p = _make_pipeline()
        for v in [0.8, 0.8, 0.8]:
            _push_run(p, v)
        assert p.stabilization_index() == pytest.approx(1.0)

    def test_volatile_runs_lower(self):
        p = _make_pipeline()
        for v in [0.0, 1.0, 0.0, 1.0]:
            _push_run(p, v)
        assert p.stabilization_index() < 0.5

    def test_bounded_zero_to_one(self):
        p = _make_pipeline()
        for v in [0.0, 1.0]:
            _push_run(p, v)
        idx = p.stabilization_index()
        assert 0.0 <= idx <= 1.0


# ---------------------------------------------------------------------------
# OntologyPipeline.run_improvement
# ---------------------------------------------------------------------------

class TestRunImprovement:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_improvement() == 0.0

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_improvement() == 0.0

    def test_positive_improvement(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.7)
        assert p.run_improvement() == pytest.approx(0.4)

    def test_negative_improvement(self):
        p = _make_pipeline()
        _push_run(p, 0.9)
        _push_run(p, 0.5)
        assert p.run_improvement() == pytest.approx(-0.4)
