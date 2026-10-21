"""Simulated control-flow contracts for the new budget-runtime adapter.

Only this NEW module's _owners and _operation seams are replaced. All producers,
logits and model objects below are authored simulations: no checkpoint, numerical
model, original owner, legal prediction, source custody or semantic qualification
is exercised or established by these tests.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_role_budget_runtime_v1 as subject


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


class AuthoredSimulation:
    """Finite scripted producer; deliberately not a model or syntax oracle."""
    def __init__(self, monkeypatch, *, emitted=(3, 2), infeasible=False,
                 forward_error=None, selection_error=None, disagreement=None):
        self.emitted = emitted
        self.infeasible = infeasible
        self.forward_error = forward_error
        self.selection_error = selection_error
        self.disagreement = disagreement
        self.events = []
        self.allocations = self.forwards = self.closes = self.guards = 0
        self.checked = self.decoded = self.input_checks = 0
        self.scope_pins = [dict(path="/authored/legal_compact_content_scope_filter_v1.py", sha256="a" * 64),
                           dict(path="/authored/legal_compact_content_completion_budget_v1.py", sha256="b" * 64)]
        self.context_hash = hashlib.sha256(b"authored context").hexdigest()
        self.codec_hash = "c" * 64
        self.value = dict(codec={"authored": "not a real codec"}, codec_sha256=self.codec_hash,
                          runtime={"authored": "not a numerical runtime"})
        self.legacy_scope = SimpleNamespace(POLICY="authored-scope-policy", _owners=lambda: (None, None, self.scope_pins[:1]))
        self.budget = SimpleNamespace(POLICY="authored-budget-policy", PREFIX_SCHEMA="authored-budget-prefix",
            SELECTION_SCHEMA="authored-budget-selection", allowed_token_ids=self.allowed,
            select_token=self.select, _owners=lambda: (self.legacy_scope, None, None, self.scope_pins))
        self.helper = SimpleNamespace(_fingerprint=wire, _digest=digest,
            _producer_rows=lambda *_args: None, _PreparedModel=self.allocate)
        self.legacy = SimpleNamespace(_inputs=self.inputs, _checked=self.check,
            _serving=lambda *_args: dict(schema=subject.SERVING_SCHEMA, authored=True),
            _identity=lambda *_args: dict(authored_simulation=True), _LIMITATIONS=["Authored simulation only"])
        self.loaded = (Path("/authored/source/ipfs_datasets_py"), None,
            {"tokens": SimpleNamespace(decode_compact_content_tokens_v1=self.decode),
             "legacy_head": SimpleNamespace(_finish=self.finish)})
        monkeypatch.setattr(subject, "_owners", lambda: (self.legacy, self.budget, [], None))
        monkeypatch.setattr(subject, "_operation", self.operation)

    def operation(self, original, work):
        return work(deepcopy(original), dict(prepared=self.helper, scope=self.budget, role=object()),
                    {}, self.loaded, deepcopy(self.scope_pins), deepcopy(self.scope_pins), self.guard)

    def guard(self):
        self.guards += 1

    def inputs(self, data, helper, role):
        self.input_checks += 1
        assert data["prefixes_ids"] == [data["prefix_ids"]]

    def check(self, *_args):
        self.checked += 1
        return deepcopy(self.value)

    def report(self, ids, remaining):
        complete = len(ids) > 1 and ids[-1] == 2
        index = len(ids) - 1
        choices = [] if complete or self.infeasible or remaining == 0 else [self.emitted[index]]
        status = "complete" if complete else "prefix" if choices else "budget_exhausted"
        baseline = dict(allowed_token_ids=list(choices), authored_prefix=list(ids))
        return dict(schema=self.budget.PREFIX_SCHEMA, policy=self.budget.POLICY,
            owner_pins=deepcopy(self.scope_pins), authority={"accepted": False},
            training_mask=0, evaluation_gold_mask=0, baseline_prefix_report=baseline,
            offered_ids=list(ids), allowed_token_ids=choices,
            context_raw_sha256=self.context_hash, context_sha256=self.context_hash,
            codec_sha256=self.codec_hash, status=status,
            reason=None if complete or choices else "no_scope_continuation_within_remaining_budget",
            remaining_new_tokens=remaining)

    def allowed(self, ids, raw, *, remaining_new_tokens, **kwargs):
        self.events.append(("allowed", remaining_new_tokens, list(ids)))
        assert raw == b"authored context" and kwargs["expected_context_sha256"] == self.context_hash
        return self.report(ids, remaining_new_tokens)

    def select(self, logits, ids, raw, *, remaining_new_tokens, **kwargs):
        self.events.append(("select", remaining_new_tokens, list(ids)))
        if self.selection_error is not None:
            raise self.selection_error
        report = self.report(ids, remaining_new_tokens)
        picked = report["allowed_token_ids"][0]
        result = dict(schema=self.budget.SELECTION_SCHEMA, policy=self.budget.POLICY,
            owner_pins=deepcopy(self.scope_pins), authority={"accepted": False},
            training_mask=0, evaluation_gold_mask=0, selection_performed=True,
            baseline_selection={"prefix_report": deepcopy(report["baseline_prefix_report"])},
            prefix_report=report, offered_prefix_ids=list(ids), logits=list(logits),
            logits_sha256=digest(logits), selected_token_id=picked, next_prefix_ids=list(ids) + [picked])
        if self.disagreement == "budget":
            result["prefix_report"]["remaining_new_tokens"] += 1
        elif self.disagreement == "baseline":
            result["baseline_selection"]["prefix_report"]["allowed_token_ids"] = []
        elif self.disagreement == "logits":
            result["logits"][0] += 1.0
        elif self.disagreement == "next_prefix":
            result["next_prefix_ids"] = list(ids) + [99]
        return result

    def allocate(self, view, conditioning, loaded, fence):
        self.allocations += 1
        assert view == {"schema": subject.SERVING_SCHEMA, "authored": True}
        outer = self
        class Session:
            def _guard(self):
                fence()

            def forward(self, ids):
                outer.forwards += 1
                if outer.forward_error is not None:
                    raise outer.forward_error
                return dict(logits=[0.0] * 537, runtime=deepcopy(outer.value["runtime"]),
                            output_shape=[1, len(ids), 537])

            def close(self):
                outer.closes += 1
        return Session()

    def decode(self, ids, raw, **kwargs):
        self.decoded += 1
        return dict(generated_ids=list(ids), context_raw_sha256=self.context_hash,
            context_sha256=self.context_hash, codec_sha256=self.codec_hash,
            status="valid_candidate" if len(ids) > 1 and ids[-1] == 2 else "authored_incomplete")

    @staticmethod
    def finish(failure, close):
        try:
            close()
        except BaseException:
            if failure is None:
                raise

    def generate(self, *, prefix_ids=None, max_new_tokens=2):
        return subject.generate({"authored": "not a checkpoint"}, [0.5],
            [1] if prefix_ids is None else prefix_ids, b"authored context",
            expected_checkpoint_sha256="d" * 64, expected_policy_sha256="e" * 64,
            expected_context_sha256=self.context_hash, max_new_tokens=max_new_tokens,
            prefix_origin="authored_fixture", context_origin="authored_fixture")


def test_infeasible_initial_budget_refuses_before_simulated_allocation_or_forward(monkeypatch):
    sim = AuthoredSimulation(monkeypatch, infeasible=True)
    result = sim.generate()
    assert result["status"] == "budget_infeasible"
    assert sim.allocations == sim.forwards == sim.closes == 0
    assert sim.checked == sim.decoded == sim.input_checks == 1
    assert result["model_restore_count"] == result["numerical_forward_count"] == 0
    assert result["generated_ids"] == [1] and result["selected_token_ids"] == []
    assert result["model_executed"] is False and result["trace"] == []
    assert sim.events == [("allowed", 2, [1])]


def test_remaining_budget_is_identical_for_prefix_and_selection_and_counts_eos(monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    result = sim.generate()
    assert sim.events == [("allowed", 2, [1]), ("select", 2, [1]),
                          ("allowed", 1, [1, 3]), ("select", 1, [1, 3]),
                          ("allowed", 0, [1, 3, 2])]
    assert result["status"] == "complete" and result["generated_ids"] == [1, 3, 2]
    assert result["selected_token_ids"] == [3, 2] and result["emitted_token_count"] == 2
    assert sim.allocations == sim.closes == 1 and sim.forwards == 2
    assert result["model_restore_count"] == 1 and result["numerical_forward_count"] == 2
    assert [row["model_restore_performed"] for row in result["trace"]] == [True, False]
    assert result["settings"]["eos_counted_in_new_token_budget"] is True
    assert result["settings"]["max_new_tokens"] == 2


def test_initial_complete_prefix_avoids_simulated_model(monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    result = sim.generate(prefix_ids=[1, 2])
    assert result["status"] == "supplied_complete" and result["generated_ids"] == [1, 2]
    assert sim.allocations == sim.forwards == sim.closes == 0
    assert result["emitted_token_count"] == 0 and result["trace"] == []


@pytest.mark.parametrize("phase", ["forward", "selection"])
@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt])
def test_simulated_model_session_closes_and_original_error_survives(phase, exception, monkeypatch):
    failure = exception("authored runtime fault")
    kwargs = {phase + "_error": failure}
    sim = AuthoredSimulation(monkeypatch, **kwargs)
    with pytest.raises(exception) as raised:
        sim.generate()
    assert raised.value is failure
    assert sim.allocations == sim.forwards == sim.closes == 1
    assert sim.decoded == 0


@pytest.mark.parametrize("disagreement", ["budget", "baseline", "logits", "next_prefix"])
def test_mismatched_selection_receipt_refuses_and_closes_simulated_session(disagreement, monkeypatch):
    sim = AuthoredSimulation(monkeypatch, disagreement=disagreement)
    with pytest.raises(ValueError):
        sim.generate()
    assert sim.allocations == sim.forwards == sim.closes == 1
    assert sim.decoded == 0


@pytest.mark.parametrize("maximum", [0, 65, True, 1.0, None])
def test_invalid_new_token_limit_refuses_before_simulated_model(maximum, monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    with pytest.raises(ValueError):
        sim.generate(max_new_tokens=maximum)
    assert sim.allocations == sim.forwards == sim.closes == sim.checked == 0


def test_budget_exhaustion_after_one_simulated_step_avoids_an_extra_forward(monkeypatch):
    sim = AuthoredSimulation(monkeypatch, emitted=(3, 4, 2))
    result = sim.generate(max_new_tokens=1)
    assert result["status"] == "budget_infeasible"
    assert result["generated_ids"] == [1, 3] and result["selected_token_ids"] == [3]
    assert sim.allocations == sim.forwards == sim.closes == 1
    assert sim.events == [("allowed", 1, [1]), ("select", 1, [1]), ("allowed", 0, [1, 3])]


def test_simulated_result_never_grants_semantic_or_native_authority(monkeypatch):
    result = AuthoredSimulation(monkeypatch).generate()
    assert result["authored_simulation"] is True
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert result["training_executed"] is False and result["optimizer_constructed"] is False
    assert result["checkpoint_training_grammar_unchanged"] is True
    assert result["serving_view_contains_training_targets"] is False
    assert result["serving_view_contains_optimizer_state"] is False
