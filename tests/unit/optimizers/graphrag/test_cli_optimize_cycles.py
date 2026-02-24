from __future__ import annotations


def test_cli_optimize_rejects_zero_cycles(tmp_path, capsys):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    input_path = tmp_path / "input.txt"
    input_path.write_text("Some ontology seed text", encoding="utf-8")

    cli = GraphRAGOptimizerCLI()
    code = cli.run(["optimize", "--input", str(input_path), "--cycles", "0"])

    out = capsys.readouterr().out
    assert code == 1
    assert "cycles must be greater than 0" in out


def test_cli_optimize_rejects_negative_cycles(tmp_path, capsys):
    from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI

    input_path = tmp_path / "input.txt"
    input_path.write_text("Some ontology seed text", encoding="utf-8")

    cli = GraphRAGOptimizerCLI()
    code = cli.run(["optimize", "--input", str(input_path), "--cycles", "-2"])

    out = capsys.readouterr().out
    assert code == 1
    assert "cycles must be greater than 0" in out
