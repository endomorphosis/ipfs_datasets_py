"""Tests for the GraphRAG metrics-export helpers."""

import json

from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI


def write_json(path, payload):
    """Write a JSON payload to a path."""
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_collect_state_runs_extracts_metrics(tmp_path):
    """Should extract score and counts from checkpoint payloads."""
    file_a = tmp_path / "run_a.json"
    file_b = tmp_path / "run_b.json"

    write_json(
        file_a,
        {
            "critic_score": {"overall": 0.72},
            "ontology": {
                "entities": [{"id": "e1"}],
                "relationships": [],
            },
        },
    )
    write_json(
        file_b,
        {
            "quality_score": 0.41,
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"id": "r1"}],
        },
    )

    cli = GraphRAGOptimizerCLI()
    runs, failures = cli._collect_state_runs(tmp_path)

    assert failures == []
    assert len(runs) == 2

    scores = sorted(run["score"] for run in runs)
    assert scores == [0.41, 0.72]

    entities = sorted(run["entities"] for run in runs)
    relationships = sorted(run["relationships"] for run in runs)
    assert entities == [1, 2]
    assert relationships == [0, 1]


def test_summarize_state_runs_tracks_averages(tmp_path):
    """Summary should include averages across runs."""
    file_a = tmp_path / "run_a.json"
    file_b = tmp_path / "run_b.json"

    write_json(file_a, {"score": 0.2, "entities": [], "relationships": []})
    write_json(file_b, {"score": 0.6, "entities": [{"id": "e1"}], "relationships": []})

    cli = GraphRAGOptimizerCLI()
    runs, failures = cli._collect_state_runs(tmp_path)
    summary = cli._summarize_state_runs(runs, failures, total_files=2)

    assert summary["total_files"] == 2
    assert summary["parsed_files"] == 2
    assert summary["failed_files"] == 0
    assert summary["average_score"] == 0.4
    assert summary["average_entities"] == 0.5
    assert summary["average_relationships"] == 0.0
