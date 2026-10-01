"""Driver exit semantics, source pins and real frozen-model diagnostic evaluation."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from .test_codebase_autoencoder_transfer import teacher, fork, joint_inputs  # noqa: F401
from .test_security_autoencoder_checkpoint import trained, package  # noqa: F401


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[5] / "scripts/evaluation/security_autoencoder_formalization.py"
    spec = importlib.util.spec_from_file_location("security_formalization_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def invocation(tmp_path):
    repository = tmp_path / "repository"; repository.mkdir()
    raw = b"def authored(value):\n    return value + 1\n"
    (repository / "authored.py").write_bytes(raw)
    ledger = tmp_path / "sources.json"
    ledger.write_text(json.dumps({"authored.py": hashlib.sha256(raw).hexdigest()}))
    descriptor = tmp_path / "checkpoint-descriptor.json"; descriptor.write_text("{}")
    output = tmp_path / "evaluation"
    argv = ["--repository", str(repository), "--source-ledger", str(ledger),
        "--checkpoint-descriptor", str(descriptor), "--output", str(output)]
    return argv, repository, ledger, descriptor, output


def _report(output, passed=False):
    result = {"schema": "authored-evaluator-fixture@1", "summary": {"sample_count": 1,
        "program_ir_count": 2, "learned_formula_count": 1 if passed else 0,
        "learned_formula_generation_passed": passed,
        "missing_capabilities": [] if passed else ["learned_formula_decoder"]}}
    output.mkdir()
    (output / "evaluation.json").write_text(json.dumps(result))
    return result


@pytest.mark.parametrize("diagnostic", [False, True])
def test_always_evaluates_and_preserves_failed_capability_in_diagnostic_mode(cli, invocation, monkeypatch, capsys, diagnostic):
    argv, repository, ledger, descriptor, output = invocation
    calls = []
    def evaluate(**kwargs):
        calls.append(kwargs)
        return _report(output)
    monkeypatch.setattr(cli, "_evaluate", evaluate)
    result = cli.main(argv + (["--allow-diagnostic-only"] if diagnostic else []))
    status = json.loads(capsys.readouterr().out)
    assert len(calls) == 1 and calls[0]["paths"] == ["authored.py"]
    assert calls[0]["source_hashes"] == json.loads(ledger.read_text())
    assert result == (0 if diagnostic else 2)
    assert status["capability_check"] == "failed" and status["learned_formula_generation_passed"] is False
    assert status["learned_formula_count"] == 0 and status["program_ir_count"] == 2
    assert status["mode"] == ("diagnostic_only" if diagnostic else "required_learned_formulas")
    assert json.loads((output / "cli-receipt.json").read_text()) == status
    assert status["checkpoint_descriptor_sha256"] == hashlib.sha256(descriptor.read_bytes()).hexdigest()


def test_exit_zero_requires_successful_learned_formula_capability(cli, invocation, monkeypatch, capsys):
    argv, _, _, _, output = invocation
    monkeypatch.setattr(cli, "_evaluate", lambda **_: _report(output, passed=True))
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["capability_check"] == "passed"


def test_report_with_missing_capability_cannot_claim_success(cli, invocation, monkeypatch, capsys):
    argv, _, _, _, output = invocation
    def evaluate(**kwargs):
        result = _report(output, passed=True)
        result["summary"]["missing_capabilities"] = ["learned_formula_decoder"]
        (output / "evaluation.json").write_text(json.dumps(result))
        return result
    monkeypatch.setattr(cli, "_evaluate", evaluate)
    assert cli.main(argv + ["--allow-diagnostic-only"]) == 2
    assert json.loads(capsys.readouterr().out)["capability_check"] == "not_established"
    assert not (output / "cli-receipt.json").exists()


def test_complete_report_may_exceed_default_model_metadata_bound(cli, invocation, monkeypatch, capsys):
    argv, _, _, _, output = invocation
    def evaluate(**kwargs):
        result = _report(output)
        result["authored_bulk_evidence"] = "a" * (9 * 1024 * 1024)
        (output / "evaluation.json").write_text(json.dumps(result))
        return result
    monkeypatch.setattr(cli, "_evaluate", evaluate)
    assert cli.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["capability_check"] == "failed"
    assert (output / "cli-receipt.json").is_file()


def test_source_drift_fails_before_model_evaluation(cli, invocation, monkeypatch, capsys):
    argv, repository, _, _, output = invocation
    (repository / "authored.py").write_text("changed source")
    monkeypatch.setattr(cli, "_evaluate", lambda **_: pytest.fail("drift must fail before evaluation"))
    assert cli.main(argv + ["--allow-diagnostic-only"]) == 2
    assert json.loads(capsys.readouterr().out)["capability_check"] == "not_established"
    assert not output.exists()


@pytest.mark.parametrize("change", ["ledger", "descriptor", "returned_report"])
def test_input_or_result_drift_cannot_produce_success_receipt(cli, invocation, monkeypatch, capsys, change):
    argv, _, ledger, descriptor, output = invocation
    def evaluate(**kwargs):
        result = _report(output, passed=True)
        if change == "returned_report": result["summary"]["program_ir_count"] += 1
        else:
            path = ledger if change == "ledger" else descriptor
            path.write_bytes(path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(cli, "_evaluate", evaluate)
    assert cli.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["capability_check"] == "not_established"
    assert not (output / "cli-receipt.json").exists()


def test_real_frozen_model_diagnostic_does_not_claim_learned_formulas(cli, package, tmp_path, capsys):
    inputs, _, checkpoint = package
    ledger = tmp_path / "real-sources.json"; ledger.write_text(json.dumps(inputs["source_hashes"]))
    descriptor = tmp_path / "real-checkpoint.json"; descriptor.write_text(json.dumps(checkpoint))
    output = tmp_path / "actual-model-evaluation"
    result = cli.main(["--repository", str(inputs["repository"]), "--source-ledger", str(ledger),
        "--checkpoint-descriptor", str(descriptor), "--output", str(output)])
    status = json.loads(capsys.readouterr().out)
    assert result == 2 and status["capability_check"] == "failed", status
    assert status["sample_count"] > 0 and status["learned_formula_count"] == 0
    assert status["missing_capabilities"] and status["learned_formula_generation_passed"] is False
    assert (output / "evaluation.json").is_file()
