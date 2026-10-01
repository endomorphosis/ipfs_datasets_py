"""Development selection and target-access guards; no optimization is run here."""
import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/compare_actor_optimizer_rates.py"
    spec = importlib.util.spec_from_file_location("actor_optimizer_development_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate(runner, *, exact=0, actor=1, other=2, loss=.2):
    return {"generation": {"tuning": {"valid_evaluation": True, "operational_complete": True,
        "exact_reconstruction": {"matched": exact},
        "facets": {field: {"matched": actor if field == "actor" else other} for field in runner.FACETS}}},
        "report": {"tuning": {"complete": True, "rows_evaluated": 6, "token_cross_entropy": loss}}}


@pytest.mark.parametrize("partition", ["sealed_evaluation", "evaluation", "holdout"])
def test_evaluation_target_request_is_rejected_before_read(runner, monkeypatch, partition):
    monkeypatch.setattr(runner.ablation, "read_reference", lambda ref: pytest.fail("evaluation file opened"))
    with pytest.raises(RuntimeError, match="only training/tuning"):
        runner.read_development_targets({"files": {}}, partition)


def test_disguised_evaluation_reference_is_not_opened(runner, monkeypatch):
    prepared = {"files": {"training": {"path": "/tmp/targets-sealed_evaluation.json"}}}
    monkeypatch.setattr(runner.ablation, "read_reference", lambda ref: pytest.fail("disguised target opened"))
    with pytest.raises(RuntimeError, match="another partition"):
        runner.read_development_targets(prepared, "training")


def test_allowed_target_reference_still_requires_exact_artifact_bytes(runner, tmp_path):
    path = tmp_path / "targets-tuning.json"
    reference = runner.write(path, [{"id": "tuning"}])
    prepared = {"files": {"tuning": reference}}
    assert runner.read_development_targets(prepared, "tuning") == [{"id": "tuning"}]
    path.write_text("changed after preparation")
    with pytest.raises(RuntimeError, match="artifact changed"):
        runner.read_development_targets(prepared, "tuning")


def test_selection_prioritizes_generated_rules_then_actor_over_low_loss(runner):
    results = dict(zip(runner.SELECTION_ORDER, [candidate(runner, exact=0, actor=6, other=6, loss=.001),
        candidate(runner, exact=1, actor=2, other=5, loss=.5),
        candidate(runner, exact=1, actor=3, other=3, loss=.9)]))
    assert runner.choose_development_candidate(results) == "lr_0p002"


def test_facet_matches_precede_loss_and_exact_tie_retains_reference(runner):
    first = candidate(runner, other=4, loss=.5)
    results = {name: copy.deepcopy(first) for name in runner.SELECTION_ORDER}
    results["lr_0p005"] = candidate(runner, other=3, loss=.001)
    assert runner.choose_development_candidate(results) == "reference_lr_0p02"
    results["lr_0p002"]["report"]["tuning"]["token_cross_entropy"] = .4
    assert runner.choose_development_candidate(results) == "lr_0p002"


@pytest.mark.parametrize("change", ["partial", "nonfinite", "unverifiable"])
def test_incomplete_candidate_cannot_be_silently_dropped_from_selection(runner, change):
    results = {name: candidate(runner) for name in runner.SELECTION_ORDER}
    selected = results["lr_0p002"]
    if change == "partial":
        selected["report"]["tuning"]["rows_evaluated"] = 5
    elif change == "nonfinite":
        selected["report"]["tuning"]["token_cross_entropy"] = float("nan")
    else:
        selected["generation"]["tuning"]["valid_evaluation"] = False
    with pytest.raises(RuntimeError):
        runner.choose_development_candidate(results)
    del results["lr_0p002"]
    with pytest.raises(RuntimeError, match="all predeclared"):
        runner.choose_development_candidate(results)
