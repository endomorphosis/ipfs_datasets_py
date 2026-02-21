"""Unit tests for BaseSession — covering all properties and edge cases."""

from __future__ import annotations

import pytest
from ipfs_datasets_py.optimizers.common.base_session import BaseSession


def _make_session(scores: list[float] = (), session_id: str = "test-1") -> BaseSession:
    s = BaseSession(session_id=session_id)
    for score in scores:
        s.record_round(score)
    return s


class TestBaseSessionProperties:
    """Property tests for BaseSession."""

    # --- best_score ---

    def test_best_score_empty(self):
        s = _make_session()
        assert s.best_score == 0.0

    def test_best_score_single(self):
        s = _make_session([0.7])
        assert s.best_score == 0.7

    def test_best_score_ascending(self):
        s = _make_session([0.3, 0.5, 0.8])
        assert s.best_score == 0.8

    def test_best_score_descending(self):
        s = _make_session([0.9, 0.7, 0.5])
        assert s.best_score == 0.9

    def test_best_score_non_monotone(self):
        s = _make_session([0.4, 0.9, 0.6, 0.85])
        assert s.best_score == 0.9

    # --- latest_score ---

    def test_latest_score_empty(self):
        s = _make_session()
        assert s.latest_score == 0.0

    def test_latest_score_tracks_last(self):
        s = _make_session([0.3, 0.7, 0.5])
        assert s.latest_score == 0.5

    # --- trend ---

    def test_trend_no_rounds(self):
        s = _make_session()
        assert s.trend == "insufficient_data"

    def test_trend_one_round(self):
        s = _make_session([0.5])
        assert s.trend == "insufficient_data"

    def test_trend_improving(self):
        s = _make_session([0.5, 0.7])
        assert s.trend == "improving"

    def test_trend_degrading(self):
        s = _make_session([0.8, 0.6])
        assert s.trend == "degrading"

    def test_trend_stable(self):
        s = _make_session([0.75, 0.77])
        assert s.trend == "stable"

    def test_trend_uses_first_and_last(self):
        # Middle rounds don't matter for trend
        s = _make_session([0.5, 0.9, 0.1, 0.65])
        assert s.trend == "improving"  # 0.65 - 0.5 = 0.15 > 0.05

    # --- score_delta ---

    def test_score_delta_empty(self):
        s = _make_session()
        assert s.score_delta == 0.0

    def test_score_delta_single(self):
        s = _make_session([0.7])
        assert s.score_delta == 0.0

    def test_score_delta_positive(self):
        s = _make_session([0.4, 0.8])
        assert abs(s.score_delta - 0.4) < 1e-9

    def test_score_delta_negative(self):
        s = _make_session([0.9, 0.6])
        assert abs(s.score_delta - (-0.3)) < 1e-9

    # --- avg_score ---

    def test_avg_score_empty(self):
        s = _make_session()
        assert s.avg_score == 0.0

    def test_avg_score_single(self):
        s = _make_session([0.7])
        assert abs(s.avg_score - 0.7) < 1e-9

    def test_avg_score_multiple(self):
        s = _make_session([0.4, 0.6, 0.8])
        assert abs(s.avg_score - 0.6) < 1e-9

    # --- regression_count ---

    def test_regression_count_empty(self):
        s = _make_session()
        assert s.regression_count == 0

    def test_regression_count_none(self):
        s = _make_session([0.5, 0.6, 0.7])
        assert s.regression_count == 0

    def test_regression_count_all(self):
        s = _make_session([0.9, 0.7, 0.5])
        assert s.regression_count == 2

    def test_regression_count_mixed(self):
        s = _make_session([0.5, 0.7, 0.6, 0.8])  # 0.7→0.6 is regression
        assert s.regression_count == 1


class TestBaseSessionToDict:
    """Tests for to_dict() output."""

    def test_to_dict_keys_present(self):
        s = _make_session([0.5, 0.7])
        d = s.to_dict()
        for key in ("session_id", "domain", "best_score", "current_round",
                    "score_delta", "avg_score", "regression_count"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_values_consistent(self):
        s = _make_session([0.4, 0.8])
        d = s.to_dict()
        assert abs(d["best_score"] - 0.8) < 1e-9
        assert d["current_round"] == 2
        assert abs(d["score_delta"] - 0.4) < 1e-9
        assert abs(d["avg_score"] - 0.6) < 1e-9
        assert d["regression_count"] == 0


class TestBaseSessionAddRound:
    """Tests for record_round()."""

    def test_add_round_increments_current_round(self):
        s = _make_session()
        assert s.current_round == 0
        s.record_round(0.5)
        assert s.current_round == 1

    def test_add_round_stores_artifact(self):
        s = _make_session()
        artifact = {"entities": [{"id": "e1"}]}
        s.record_round(0.7, artifact_snapshot=artifact)
        assert s.rounds[-1].artifact_snapshot is artifact

    def test_add_round_duration_ms_is_non_negative(self):
        s = _make_session()
        s.record_round(0.7)
        assert s.rounds[-1].duration_ms >= 0.0

    def test_total_duration_ms_is_sum(self):
        s = _make_session()
        s.record_round(0.5)
        s.record_round(0.6)
        assert s.total_duration_ms >= 0.0
        assert abs(s.total_duration_ms - sum(r.duration_ms for r in s.rounds)) < 1e-9


# ── JSON serialization round-trips ─────────────────────────────────────────

class TestBaseSessionJSONRoundTrip:
    def _session_with_rounds(self):
        s = BaseSession(session_id="rt-1", domain="legal", max_rounds=5)
        for score in [0.5, 0.6, 0.7]:
            s.start_round()
            s.record_round(score=score, feedback={"hint": "ok"}, metadata={})
        s.finish()
        return s

    def test_to_json_returns_string(self):
        s = self._session_with_rounds()
        j = s.to_json()
        assert isinstance(j, str) and len(j) > 0

    def test_to_json_indent_is_valid_json(self):
        import json
        s = self._session_with_rounds()
        j = s.to_json(indent=2)
        data = json.loads(j)
        assert data["session_id"] == "rt-1"

    def test_from_json_restores_scores(self):
        s = self._session_with_rounds()
        s2 = BaseSession.from_json(s.to_json())
        assert s2.best_score == pytest.approx(0.7)
        assert len(s2.scores) == 3

    def test_from_json_restores_domain(self):
        s = self._session_with_rounds()
        assert BaseSession.from_json(s.to_json()).domain == "legal"

    def test_from_json_restores_session_id(self):
        s = self._session_with_rounds()
        assert BaseSession.from_json(s.to_json()).session_id == "rt-1"

    def test_from_dict_empty_rounds(self):
        s = BaseSession(session_id="empty", domain="general")
        s2 = BaseSession.from_dict(s.to_dict())
        assert s2.session_id == "empty"
        assert len(s2.scores) == 0
