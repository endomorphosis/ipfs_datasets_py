from __future__ import annotations

import json


def test_cli_query_rejects_blank_query(tmp_path, capsys):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    ontology_path = tmp_path / "ontology.json"
    ontology_path.write_text(json.dumps({"entities": [], "relationships": []}), encoding="utf-8")

    cli = GraphRAGOptimizerCLI()
    code = cli.run(["query", "--ontology", str(ontology_path), "--query", "   "])

    out = capsys.readouterr().out
    assert code == 1
    assert "query must be a non-empty string" in out


def test_cli_query_writes_plan_output(tmp_path):
    from ipfs_datasets_py.optimizers.graphrag import query_optimizer as qo_module
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    ontology_path = tmp_path / "ontology.json"
    output_path = tmp_path / "query-plan.json"
    ontology_path.write_text(
        json.dumps({"entities": [{"id": "e1", "type": "Thing", "text": "Alice"}], "relationships": []}),
        encoding="utf-8",
    )

    class _StubOptimizer:
        def __init__(self, graph_info, metrics_dir=None):
            self.graph_info = graph_info
            self.metrics_dir = metrics_dir

        def optimize_query(self, query, priority, graph_processor=None):
            return {
                "graph_type": "stub",
                "budget": {
                    "vector_search_ms": 1,
                    "graph_traversal_ms": 2,
                    "ranking_ms": 3,
                },
                "query": query,
                "priority": priority,
            }

        def get_execution_plan(self, query, priority, graph_processor=None):
            return {
                "execution_steps": [
                    {"name": "parse", "description": "Parse query"},
                    {"name": "rank", "description": "Rank results"},
                ],
                "query": query,
                "priority": priority,
            }

    qo_original = qo_module.UnifiedGraphRAGQueryOptimizer
    qo_module.UnifiedGraphRAGQueryOptimizer = _StubOptimizer
    try:
        cli = GraphRAGOptimizerCLI()
        code = cli.run(
            [
                "query",
                "--ontology",
                str(ontology_path),
                "--query",
                "who works at acme",
                "--optimize",
                "--explain",
                "--output",
                str(output_path),
            ]
        )
    finally:
        qo_module.UnifiedGraphRAGQueryOptimizer = qo_original

    assert code == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["optimized"] is True
    assert payload["plan"]["graph_type"] == "stub"
    assert len(payload["execution_plan"]["execution_steps"]) == 2


def test_cli_run_redacts_sensitive_error_text(tmp_path, monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    ontology_path = tmp_path / "ontology.json"
    ontology_path.write_text(json.dumps({"entities": [], "relationships": []}), encoding="utf-8")

    cli = GraphRAGOptimizerCLI()

    def _raise_value_error(_args):
        raise ValueError("bad input api_key=sk-secret123")

    monkeypatch.setattr(cli, "cmd_query", _raise_value_error)
    code = cli.run(["query", "--ontology", str(ontology_path), "--query", "ok"])

    captured = capsys.readouterr()
    assert code == 1
    assert "api_key=***REDACTED***" in captured.out
    assert "sk-secret123" not in captured.out
    assert "sk-secret123" not in captured.err
