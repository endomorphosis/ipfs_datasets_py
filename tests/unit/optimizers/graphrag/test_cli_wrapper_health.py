from __future__ import annotations

import json


def test_cli_health_command_returns_zero(capsys):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    cli = GraphRAGOptimizerCLI()
    code = cli.run(["health", "--window", "25"])

    out = capsys.readouterr().out
    assert code == 0
    assert "GraphRAG Query Optimizer Health" in out
    assert '"window_size": 25' in out


def test_cli_health_command_writes_output_file(tmp_path):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    output_path = tmp_path / "health.json"

    cli = GraphRAGOptimizerCLI()
    code = cli.run(["health", "--window", "10", "--output", str(output_path)])

    assert code == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text())
    assert payload["window_size"] == 10
    assert "memory_usage_bytes" in payload
    assert "error_rate_last_100" in payload
