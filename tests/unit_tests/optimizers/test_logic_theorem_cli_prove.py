import argparse


def test_cmd_prove_success(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import LogicTheoremOptimizer

    captured = {}

    def fake_validate_statements(self, statements, context=None, timeout=None):
        captured["statements"] = list(statements)

        class Result:
            all_valid = True
            provers_used = ["fake"]
            errors = []

        return Result()

    monkeypatch.setattr(
        LogicTheoremOptimizer,
        "validate_statements",
        fake_validate_statements,
        raising=True,
    )

    cli = LogicOptimizerCLI()
    args = argparse.Namespace(
        theorem="A implies B",
        premises=["A"],
        goal="B",
        prover="z3",
    )

    rc = cli.cmd_prove(args)
    out = capsys.readouterr().out

    assert rc == 0
    assert captured["statements"] == ["A", "B"]
    assert "Theorem proven successfully" in out


def test_cmd_prove_failure(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import LogicTheoremOptimizer

    def fake_validate_statements(self, statements, context=None, timeout=None):
        class Result:
            all_valid = False
            provers_used = ["fake"]
            errors = ["could not verify"]

        return Result()

    monkeypatch.setattr(
        LogicTheoremOptimizer,
        "validate_statements",
        fake_validate_statements,
        raising=True,
    )

    cli = LogicOptimizerCLI()
    args = argparse.Namespace(
        theorem="A implies B",
        premises=["A"],
        goal="B",
        prover="z3",
    )

    rc = cli.cmd_prove(args)
    out = capsys.readouterr().out

    assert rc == 1
    assert "Theorem could not be proven" in out
    assert "could not verify" in out
