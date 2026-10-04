from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.query_stats import GraphRAGQueryStats


def test_query_stats_records_timing_and_average() -> None:
    stats = GraphRAGQueryStats()

    stats.record_query_time(0.2)
    stats.record_query_time(0.8)

    assert stats.query_count == 2
    assert abs(stats.avg_query_time - 0.5) < 1e-9


def test_query_stats_cache_hit_updates_rate() -> None:
    stats = GraphRAGQueryStats()

    stats.record_query_time(0.5)
    stats.record_cache_hit()

    assert stats.query_count == 2
    assert stats.cache_hits == 1
    assert abs(stats.cache_hit_rate - 0.5) < 1e-9


def test_query_stats_records_and_returns_common_patterns() -> None:
    stats = GraphRAGQueryStats()

    pattern = {"max_vector_results": 5, "max_traversal_depth": 2}
    stats.record_query_pattern(pattern)
    stats.record_query_pattern(pattern)
    stats.record_query_pattern({"max_vector_results": 3})

    common = stats.get_common_patterns(top_n=1)

    assert len(common) == 1
    assert common[0][0]["max_vector_results"] == 5
    assert common[0][1] == 2


def test_query_stats_performance_summary_contains_expected_fields() -> None:
    stats = GraphRAGQueryStats()

    stats.record_query_time(0.25)
    stats.record_query_pattern({"edge_types": ["related_to"]})

    summary = stats.get_performance_summary()

    assert summary["query_count"] == 1
    assert "cache_hit_rate" in summary
    assert "avg_query_time" in summary
    assert "common_patterns" in summary


def test_query_stats_reset_clears_all_state() -> None:
    stats = GraphRAGQueryStats()

    stats.record_query_time(0.3)
    stats.record_cache_hit()
    stats.record_query_pattern({"x": 1})
    stats.reset()

    assert stats.query_count == 0
    assert stats.cache_hits == 0
    assert stats.total_query_time == 0.0
    assert stats.query_times == []
    assert stats.query_timestamps == []
    assert list(stats.query_patterns.items()) == []
