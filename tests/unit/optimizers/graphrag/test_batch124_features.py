"""Batch-124 feature tests.

Methods under test:
  - OntologyOptimizer.history_slice(start, end)
  - OntologyOptimizer.score_above_count(threshold)
  - OntologyOptimizer.first_entry_above(threshold)
  - OntologyOptimizer.last_entry_above(threshold)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"
        self.best_ontology = {}
        self.worst_ontology = {}
        self.metadata = {}


def _push(opt, avg):
    opt._history.append(_FakeEntry(avg))


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_slice
# ---------------------------------------------------------------------------

class TestHistorySlice:
    @pytest.mark.parametrize(
        "scores,start,end,expected_len,expected_first",
        [
            ([], 0, 5, 0, None),
            ([0.1, 0.2, 0.3, 0.4, 0.5], 0, 5, 5, 0.1),
            ([0.1, 0.2, 0.3], 1, 3, 2, 0.2),
        ],
    )
    def test_history_slice_scenarios(
        self, scores, start, end, expected_len, expected_first
    ):
        o = _make_optimizer()
        for v in scores:
            _push(o, v)
        slc = o.history_slice(start, end)
        assert len(slc) == expected_len
        if expected_first is not None:
            assert slc[0].average_score == pytest.approx(expected_first)

    def test_empty_range(self):
        o = _make_optimizer()
        _push(o, 0.5)
        assert o.history_slice(2, 5) == []


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_above_count
# ---------------------------------------------------------------------------

class TestScoreAboveCount:
    @pytest.mark.parametrize(
        "scores,threshold,expected",
        [
            ([], 0.5, 0),
            ([0.7, 0.8, 0.9], 0.6, 3),
            ([0.1, 0.2], 0.6, 0),
            ([0.4, 0.7, 0.9], 0.6, 2),
        ],
    )
    def test_score_above_count_scenarios(self, scores, threshold, expected):
        o = _make_optimizer()
        for v in scores:
            _push(o, v)
        assert o.score_above_count(threshold) == expected


# ---------------------------------------------------------------------------
# OntologyOptimizer.first_entry_above
# ---------------------------------------------------------------------------

class TestFirstEntryAbove:
    def test_empty_returns_none(self):
        o = _make_optimizer()
        assert o.first_entry_above(0.5) is None

    def test_no_match_returns_none(self):
        o = _make_optimizer()
        for v in [0.1, 0.2]:
            _push(o, v)
        assert o.first_entry_above(0.5) is None

    def test_returns_first(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.9]:
            _push(o, v)
        entry = o.first_entry_above(0.6)
        assert entry.average_score == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# OntologyOptimizer.last_entry_above
# ---------------------------------------------------------------------------

class TestLastEntryAbove:
    @pytest.mark.parametrize(
        "scores,threshold,expected_score",
        [
            ([], 0.5, None),
            ([0.1, 0.2], 0.5, None),
            ([0.7, 0.8, 0.3], 0.6, 0.8),
            ([0.3, 0.9, 0.2], 0.7, 0.9),
        ],
    )
    def test_last_entry_above_scenarios(self, scores, threshold, expected_score):
        o = _make_optimizer()
        for v in scores:
            _push(o, v)
        entry = o.last_entry_above(threshold)
        if expected_score is None:
            assert entry is None
        else:
            assert entry is not None
            assert entry.average_score == pytest.approx(expected_score)
