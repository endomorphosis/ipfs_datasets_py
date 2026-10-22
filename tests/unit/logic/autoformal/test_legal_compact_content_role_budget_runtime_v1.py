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


# The appended BOS controls use authored scores and session objects. The grammar
# integration below additionally calls the genuine token/scope/budget owners;
# neither group restores a checkpoint, executes Torch or measures a learned law.
class BOSControlSimulation(AuthoredSimulation):
    """Scripted scores with genuine bounded-copy and role-input helpers."""

    def __init__(self, monkeypatch, *, emitted=(3, 2), infeasible=False,
                 real_inputs=False, interrupt_phase=None, interrupt_kind=None):
        from ipfs_datasets_py.logic.formalization.autoencoder import (
            legal_compact_content_prepared_runtime_v3 as prepared,
            legal_compact_content_role_training_v1 as role,
            legal_compact_content_role_trained_runtime_v1 as role_runtime,
        )
        self.prepared, self.role, self.role_runtime = prepared, role, role_runtime
        self.real_inputs = real_inputs
        self.interrupt_phase, self.interrupt_kind = interrupt_phase, interrupt_kind
        self.interruption = None
        self.on_forward = None
        self.forward_prefixes, self.serving_views = [], []
        self.operation_original = self.operation_snapshot = self.operation_fingerprint = None
        super().__init__(monkeypatch, emitted=emitted, infeasible=infeasible)
        self.helper._fingerprint = prepared._fingerprint
        self.helper._digest = prepared._digest

    def operation(self, original, work):
        # The outer operation seam remains simulated. These actual pure helpers
        # let its fence distinguish original inputs from a detached bounded copy.
        snapshot = self.prepared._copy(original, self.prepared.MAX_INPUT_BYTES, allow_bytes=True)
        self.operation_original, self.operation_snapshot = original, snapshot
        self.operation_fingerprint = self.prepared._fingerprint(snapshot)
        self.guard()
        result = work(snapshot, dict(prepared=self.helper, scope=self.budget, role=self.role),
            {}, self.loaded, deepcopy(self.scope_pins), deepcopy(self.scope_pins), self.guard)
        self.guard()
        return result

    def guard(self):
        self.guards += 1
        if self.operation_fingerprint is not None:
            if (self.prepared._fingerprint(self.operation_original) != self.operation_fingerprint
                    or self.prepared._fingerprint(self.operation_snapshot) != self.operation_fingerprint):
                raise ValueError("authored operation original or detached inputs changed")

    def inputs(self, data, helper, role):
        self.input_checks += 1
        assert data["prefixes_ids"] == [data["prefix_ids"]] == [[1]]
        assert data["prefix_origin"] == "bos_seed"
        if self.real_inputs:
            self.role_runtime._inputs(data, self.prepared, self.role)

    def _interrupt(self, phase, ids):
        if self.interrupt_phase == phase and len(ids) == 80:
            self.interruption = self.interrupt_kind("authored fault after 79 emissions")
            raise self.interruption

    def logits(self, ids):
        return [0.0] * 537

    def select(self, logits, ids, raw, *, remaining_new_tokens, **kwargs):
        self._interrupt("selection", ids)
        return super().select(logits, ids, raw, remaining_new_tokens=remaining_new_tokens, **kwargs)

    def allocate(self, view, conditioning, loaded, fence):
        self.allocations += 1
        self.serving_views.append(deepcopy(view))
        assert loaded is self.loaded
        outer = self

        class Session:
            def _guard(self):
                fence()

            def forward(self, ids):
                outer.forwards += 1
                outer.forward_prefixes.append(list(ids))
                outer._interrupt("forward", ids)
                if outer.on_forward is not None:
                    outer.on_forward(view, conditioning, ids)
                return dict(logits=outer.logits(ids), runtime=deepcopy(outer.value["runtime"]),
                            output_shape=[1, len(ids), 537])

            def close(self):
                outer.closes += 1

        return Session()

    def bos(self, *, max_new_tokens=100, checkpoint=None, conditioning=None,
            context_raw=None, expected_context_sha256=None, context_origin="authored_fixture"):
        return subject.generate_from_bos_v2(
            {"authored": "not a checkpoint"} if checkpoint is None else checkpoint,
            ([0.5] * 384 if self.real_inputs else [0.5]) if conditioning is None else conditioning,
            b"authored context" if context_raw is None else context_raw,
            expected_checkpoint_sha256="d" * 64, expected_policy_sha256="e" * 64,
            expected_context_sha256=self.context_hash if expected_context_sha256 is None else expected_context_sha256,
            max_new_tokens=max_new_tokens, context_origin=context_origin)


def test_bos_v2_api_has_fixed_seed_and_no_prefix_target_or_reference_argument():
    import inspect
    parameters = inspect.signature(subject.generate_from_bos_v2).parameters
    assert set(parameters) == {"checkpoint", "conditioning", "context_raw",
        "expected_checkpoint_sha256", "expected_policy_sha256", "expected_context_sha256",
        "max_new_tokens", "context_origin"}
    assert all(parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in
        ("expected_checkpoint_sha256", "expected_policy_sha256", "expected_context_sha256",
         "max_new_tokens", "context_origin"))


@pytest.mark.parametrize("maximum", [64, 65, 100, 511])
def test_bos_v2_accepts_declared_extended_allowance_and_stops_after_scripted_eos(maximum, monkeypatch):
    sim = BOSControlSimulation(monkeypatch)
    result = sim.bos(max_new_tokens=maximum)
    assert result["schema"] != subject.SCHEMA and result["profile"] != subject.PROFILE
    assert result["schema"].endswith("/v2") and result["profile"].endswith("/v2")
    assert result["initial_prefix_ids"] == [1] and result["prefix_origin"] == "bos_seed"
    assert result["status"] == "complete" and result["generated_ids"] == [1, 3, 2]
    assert result["settings"]["max_new_tokens"] == maximum
    assert result["settings"]["max_total_ids"] == 512
    assert result["emitted_token_count"] == sim.forwards == 2
    assert sim.allocations == sim.closes == 1


@pytest.mark.parametrize("maximum", [True, False, 0, -1, 512, 1.0, None, "100", [], {}],
                         ids=["true", "false", "zero", "negative", "512", "float", "none", "text", "list", "dict"])
def test_bos_v2_invalid_allowance_refuses_before_checkpoint_check_or_simulated_model(maximum, monkeypatch):
    sim = BOSControlSimulation(monkeypatch)
    with pytest.raises(ValueError):
        sim.bos(max_new_tokens=maximum)
    assert sim.checked == sim.allocations == sim.forwards == sim.closes == 0


@pytest.mark.parametrize("maximum", [65, 100, 511])
def test_bos_v2_does_not_expand_original_v1_api_limit(maximum, monkeypatch):
    sim = AuthoredSimulation(monkeypatch)
    with pytest.raises(ValueError):
        sim.generate(max_new_tokens=maximum)
    assert sim.checked == sim.allocations == sim.forwards == sim.closes == 0


def test_bos_v2_scripted_101_id_trajectory_has_one_lifetime_and_exact_remaining_budget(monkeypatch):
    sim = BOSControlSimulation(monkeypatch, emitted=(3,) * 99 + (2,))
    result = sim.bos(max_new_tokens=100)
    assert result["status"] == "complete"
    assert result["generated_ids"] == [1] + [3] * 99 + [2]
    assert result["total_token_count"] == 101 and result["emitted_token_count"] == 100
    assert result["selected_token_ids"] == [3] * 99 + [2]
    assert sim.allocations == sim.closes == result["model_restore_count"] == 1
    assert sim.forwards == result["numerical_forward_count"] == 100
    assert [len(ids) for ids in sim.forward_prefixes] == list(range(1, 101))
    assert [event[1] for event in sim.events if event[0] == "allowed"] == list(range(100, -1, -1))
    assert [event[1] for event in sim.events if event[0] == "select"] == list(range(100, 0, -1))
    assert [row["model_restore_performed"] for row in result["trace"]] == [True] + [False] * 99
    assert result["settings"]["eos_counted_in_new_token_budget"] is True
    assert result["actual_model_inputs"] == ["conditioning_vector", "supplied_or_generated_prefix_ids"]
    assert result["training_executed"] is result["optimizer_constructed"] is False
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("maximum", [99, 100, 101])
def test_bos_v2_scripted_eos_consumes_one_budget_slot_without_extra_forward(maximum, monkeypatch):
    sim = BOSControlSimulation(monkeypatch, emitted=(3,) * 99 + (2,))
    result = sim.bos(max_new_tokens=maximum)
    expected = min(maximum, 100)
    assert sim.forwards == result["emitted_token_count"] == expected
    assert sim.allocations == sim.closes == 1
    if maximum == 99:
        assert result["status"] == "budget_infeasible" and result["generated_ids"][-1] != 2
        assert result["generated_ids"] == [1] + [3] * 99
    else:
        assert result["status"] == "complete" and result["generated_ids"][-1] == 2
    assert sim.events[-1][0:2] == ("allowed", maximum - expected)


def test_bos_v2_initial_infeasibility_does_not_allocate_simulated_model(monkeypatch):
    sim = BOSControlSimulation(monkeypatch, infeasible=True)
    result = sim.bos(max_new_tokens=100)
    assert result["status"] == "budget_infeasible" and result["trace"] == []
    assert sim.allocations == sim.forwards == sim.closes == 0
    assert sim.checked == sim.input_checks == sim.decoded == 1


@pytest.mark.parametrize("phase", ["forward", "selection"])
@pytest.mark.parametrize("kind", [RuntimeError, KeyboardInterrupt], ids=["runtime", "interrupt"])
def test_bos_v2_long_scripted_failure_closes_one_session_and_preserves_exception(phase, kind, monkeypatch):
    sim = BOSControlSimulation(monkeypatch, emitted=(3,) * 99 + (2,),
                               interrupt_phase=phase, interrupt_kind=kind)
    with pytest.raises(kind) as raised:
        sim.bos(max_new_tokens=100)
    assert raised.value is sim.interruption
    assert sim.allocations == sim.closes == 1 and sim.forwards == 80
    assert sim.decoded == 0 and len(sim.forward_prefixes[-1]) == 80


@pytest.mark.parametrize("damage", ["context_pin", "context_origin", "context_type", "conditioning_dimension", "conditioning_nonfinite"])
def test_bos_v2_reuses_real_role_input_validation_before_simulated_checkpoint_or_model(damage, monkeypatch):
    sim = BOSControlSimulation(monkeypatch, real_inputs=True)
    kwargs = {}
    if damage == "context_pin":
        kwargs["expected_context_sha256"] = "0" * 64
    elif damage == "context_origin":
        kwargs["context_origin"] = "unrecognized-context-origin"
    elif damage == "context_type":
        kwargs["context_raw"] = "authored context"
    elif damage == "conditioning_dimension":
        kwargs["conditioning"] = [0.5] * 383
    else:
        kwargs["conditioning"] = [float("nan")] + [0.5] * 383
    with pytest.raises(ValueError):
        sim.bos(**kwargs)
    assert sim.checked == sim.allocations == sim.forwards == sim.closes == 0


def _install_authored_role_projection(sim):
    """Use the real serving projection, with visibly non-checkpoint field values."""
    sim.value = dict(schema="authored-role-checkpoint-simulation", profile="authored-profile",
        objective_policy={"weighting": "authored-weighting"}, basis_checkpoint_sha256="1" * 64,
        basis_policy_sha256="2" * 64, role_inventories_sha256="3" * 64,
        weights_sha256="4" * 64, codec_sha256=sim.codec_hash, initial_weights_sha256="5" * 64,
        initial_checkpoint_sha256="6" * 64, parent_checkpoint_sha256="7" * 64,
        progress={"optimizer_steps": 128}, optimizer_state_sha256="8" * 64,
        runtime={"authored": "not a numerical runtime"}, config={"authored": True},
        codec={"authored": "not a real codec"}, parameter_order=["authored_parameter"],
        model_state={"authored_parameter": [0.0]},
        basis_checkpoint={"target_rows": ["EXPOSED_TARGET_CANARY"]},
        optimizer_state={"moments": ["ADAM_TENSOR_CANARY"]})
    sim.legacy._serving = sim.role_runtime._serving
    sim.legacy._identity = sim.role_runtime._identity


def test_bos_v2_real_serving_projection_preserves_lineage_and_excludes_targets_and_adam(monkeypatch):
    sim = BOSControlSimulation(monkeypatch, real_inputs=True)
    _install_authored_role_projection(sim)
    checkpoint = {"authored": "not a checkpoint", "basis_targets": ["EXPOSED_TARGET_CANARY"]}
    conditioning = [0.5] * 384
    before = deepcopy((checkpoint, conditioning, sim.value))
    result = sim.bos(checkpoint=checkpoint, conditioning=conditioning)
    assert (checkpoint, conditioning, sim.value) == before
    view = sim.serving_views[0]
    assert view["schema"] == sim.role_runtime.SERVING_SCHEMA
    assert set(view) == {"schema", *sim.role_runtime._identity(sim.value, sim.operation_snapshot),
                         *sim.role_runtime._MODEL_FIELDS}
    assert b"EXPOSED_TARGET_CANARY" not in wire(view) and b"ADAM_TENSOR_CANARY" not in wire(view)
    assert result["basis_checkpoint_sha256"] == "1" * 64
    assert result["parent_checkpoint_sha256"] == "7" * 64
    assert result["progress"] == {"optimizer_steps": 128}
    assert result["historical_optimizer_state_sha256"] == "8" * 64
    assert result["checkpoint_schema_conversion_performed"] is False
    assert result["serving_view_contains_training_targets"] is False
    assert result["serving_view_contains_optimizer_state"] is False
    assert result["target_access_for_checkpoint_validation"] is True
    assert result["optimizer_state_restored"] is False
    result["conditioning"][0] = 9.0
    assert conditioning == before[1] and sim.value == before[2]


def test_bos_v2_serving_view_mutation_refuses_and_closes_scripted_session(monkeypatch):
    sim = BOSControlSimulation(monkeypatch, real_inputs=True)
    _install_authored_role_projection(sim)
    sim.on_forward = lambda view, _conditioning, _ids: view["model_state"]["authored_parameter"].append(1.0)
    with pytest.raises(ValueError, match="target-free serving view changed"):
        sim.bos()
    assert sim.allocations == sim.forwards == sim.closes == 1 and sim.decoded == 0


@pytest.mark.parametrize("field", ["checkpoint", "conditioning"])
def test_bos_v2_caller_mutation_cannot_return_scripted_success(field, monkeypatch):
    sim = BOSControlSimulation(monkeypatch, real_inputs=True)
    checkpoint, conditioning = {"authored": ["not a checkpoint"]}, [0.5] * 384
    def mutate(_view, _conditioning, _ids):
        if field == "checkpoint":
            checkpoint["authored"].append("changed during forward")
        else:
            conditioning[0] = 1.0
    sim.on_forward = mutate
    with pytest.raises(ValueError, match="original or detached inputs changed"):
        sim.bos(checkpoint=checkpoint, conditioning=conditioning)
    assert sim.allocations == sim.forwards == sim.closes == 1 and sim.decoded == 0


def _authored_101_id_grammar_inputs():
    """Independent fictional formula and lexical oracle; no statute or target import."""
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
    import re
    obj = dict(arguments=[], kind="atomic", name="Object", schema_version="syntax-logic-sort/v1")
    boolean = dict(arguments=[], kind="bool", name="Bool", schema_version="syntax-logic-sort/v1")
    def identity(namespace, value):
        return dict(interface="LogicIdentityNamespaces@1", namespace=namespace,
                    schema_version="logic-identity-namespaces/v1", value=value, version="1.0.0")
    names = ["FixtureHand", "FixtureTake", "FixtureMark"]
    symbols = [dict(domain=[deepcopy(obj), deepcopy(obj)], kind="predicate", metadata={}, name=name,
        range=deepcopy(boolean), schema_version="syntax-symbol-declaration/v1") for name in names]
    context = dict(schema="legal-relational-compact-context/v1",
        argument_roles=[dict(symbol=name, roles=["first", "second"]) for name in names],
        signature=dict(family=identity("family", "tdfol"), features=[], interface="LogicSignature@1",
            metadata={}, profile=identity("profile", "tdfol_default"),
            schema_version="syntax-logic-signature/v1", sorts=[boolean, obj], symbols=symbols))
    def atom(index, left, right):
        return ["predicate", index, [["variable", left], ["variable", right]]]
    document = dict(schema="legal-relational-compact-content/v1", tree=["forall", 0,
        ["exists", 1, ["forall", 2, ["and", ["extension", "F", ["implies",
            atom(0, 0, 1), atom(1, 1, 0)]], atom(2, 2, 1)]]]])
    raw = wire(document).decode("utf-8")
    pieces = re.findall(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]', raw)
    assert "".join(pieces) == raw
    codec = tokens.build_compact_content_token_codec_v1()
    positions = {spelling: index for index, spelling in enumerate(codec["vocabulary"])}
    ids = [codec["bos_id"], *(positions[spelling] for spelling in pieces), codec["eos_id"]]
    assert len(pieces) == 99 and len(ids) == 101
    return tokens, codec, wire(context), document, ids


class GenuineGrammarBOSSimulation(BOSControlSimulation):
    """Real pinned grammar/selector owners; scripted scores and checkpoint check."""

    def __init__(self, monkeypatch):
        super().__init__(monkeypatch, real_inputs=True)
        from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as budget
        tokens, codec, self.context_raw, self.authored_document, self.scripted_ids = _authored_101_id_grammar_inputs()
        self.budget = budget
        scope, _, owner_tokens, pins = budget._owners()
        assert owner_tokens is tokens
        self.scope_pins = deepcopy(pins)
        # Budget pins describe its own selector/scope ancestry. Token-prefix and
        # decoding reports separately commit the token and content owners.
        self.token_producer_pins = deepcopy(tokens._owner()[1])
        self.loaded = (Path(tokens.__file__).absolute().parents[3], None,
                      {"tokens": tokens, "legacy_head": SimpleNamespace(_finish=self.finish)})
        self.context_hash = hashlib.sha256(self.context_raw).hexdigest()
        self.codec_hash = tokens.compact_content_token_codec_sha256(codec)
        self.value = dict(codec=codec, codec_sha256=self.codec_hash,
                          runtime={"authored": "not a numerical runtime"})
        self.helper._producer_rows = self.verify_real_producer_rows
        self.real_scope = scope

    def verify_real_producer_rows(self, report, loaded, expected_paths):
        assert loaded is self.loaded
        actual = {pin["path"]: pin for pin in report["owner_pins"]}
        retained = {pin["path"]: pin for pin in self.token_producer_pins}
        assert len(actual) == len(report["owner_pins"])
        assert len(retained) == len(self.token_producer_pins)
        assert set(actual) == set(retained) == expected_paths
        assert actual == retained
        assert loaded[2]["tokens"]._owner()[1] == self.token_producer_pins

    def logits(self, ids):
        # Deliberately an exposed scripted score oracle, never a learned model.
        assert ids == self.scripted_ids[:len(ids)]
        scores = [-1.0] * 537
        scores[self.scripted_ids[len(ids)]] = 1.0
        return scores

    def bos(self, *, max_new_tokens=100):
        return super().bos(max_new_tokens=max_new_tokens, context_raw=self.context_raw)


@pytest.mark.parametrize("maximum", [100, 511])
def test_bos_v2_genuine_grammar_accepts_authored_101_ids_from_scripted_scores(maximum, monkeypatch):
    sim = GenuineGrammarBOSSimulation(monkeypatch)
    result = sim.bos(max_new_tokens=maximum)
    assert result["status"] == "complete" and result["generated_ids"] == sim.scripted_ids
    assert result["final_decoding"]["status"] == "valid_candidate"
    assert result["final_decoding"]["prediction"]["content"] == sim.authored_document
    assert sim.allocations == sim.closes == 1 and sim.forwards == 100
    assert result["emitted_token_count"] == 100 and result["total_token_count"] == 101
    assert result["budget_owner_pins"] == sim.scope_pins
    assert result["scope_policy"] == sim.real_scope.POLICY
    # This syntax integration keeps the authored identity seam. The actual role
    # identity/projection is tested separately; public token reports bind codec
    # and context here rather than inventing a field on the simulated identity.
    assert result["context_raw_sha256"] == sim.context_hash
    assert result["final_decoding"]["context_raw_sha256"] == sim.context_hash
    assert result["final_decoding"]["codec_sha256"] == sim.codec_hash
    assert result["final_prefix_report"]["codec_sha256"] == sim.codec_hash
    assert result["context_sha256"] == result["final_decoding"]["context_sha256"]
    assert result["context_sha256"] == result["final_prefix_report"]["context_sha256"]
    for index, row in enumerate(result["trace"]):
        assert row["prefix_ids"] == sim.scripted_ids[:index + 1]
        assert row["next_prefix_ids"] == sim.scripted_ids[:index + 2]
        assert row["prefix_report"]["remaining_new_tokens"] == maximum - index
        assert row["selection"]["prefix_report"] == row["prefix_report"]
        assert row["selection"]["selected_token_id"] == sim.scripted_ids[index + 1]
        assert row["logits"][sim.scripted_ids[index + 1]] == 1.0
        assert all(value is False for value in row["prefix_report"]["authority"].values())
    assert result["final_prefix_report"]["remaining_new_tokens"] == maximum - 100
    assert result["final_prefix_report"]["status"] == "complete"
    assert result["final_prefix_report"]["allowed_token_ids"] == []
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert result["training_executed"] is result["optimizer_constructed"] is False
    assert result["supplied_context_target_access_declared"] is False
    # The declared context origin does not authenticate the scripted score oracle.
    assert all(value is False for value in result["authority"].values())


def test_bos_v2_genuine_budget_infeasibility_avoids_scripted_model_allocation(monkeypatch):
    sim = GenuineGrammarBOSSimulation(monkeypatch)
    result = sim.bos(max_new_tokens=1)
    assert result["status"] == "budget_infeasible"
    assert result["reason"] == "no_scope_continuation_within_remaining_budget"
    assert result["generated_ids"] == [1] and result["trace"] == []
    assert sim.allocations == sim.forwards == sim.closes == 0
    assert result["budget_owner_pins"] == sim.scope_pins


def test_bos_v2_actual_owner_factory_preserves_exact_sources_without_numerical_dispatch(monkeypatch):
    """Actual source factory and grammar ownership; no checkpoint or model call."""
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        legal_compact_content_role_trained_runtime_v1 as legacy,
        legal_compact_content_completion_budget_v1 as budget,
        legal_compact_content_prepared_runtime_v3 as prepared,
    )
    def forbidden(*_args, **_kwargs):
        pytest.fail("source factory must not enter checkpoint validation or numerical dispatch")
    monkeypatch.setattr(legacy, "_operation", forbidden)
    monkeypatch.setattr(legacy, "_checked", forbidden)
    monkeypatch.setattr(prepared, "_PreparedModel", forbidden)
    actual_legacy, actual_budget, observed, scope_owners = subject._owners()
    assert actual_legacy is legacy and actual_budget is budget
    assert Path(subject.__file__).absolute() == subject._SELF_PATH
    expected = [(subject._SELF_PATH, subject._SELF_SHA),
        (subject._SELF_PATH.with_name("legal_compact_content_role_trained_runtime_v1.py"), subject._LEGACY_SHA),
        (subject._SELF_PATH.with_name("legal_compact_content_completion_budget_v1.py"), subject._BUDGET_SHA)]
    assert Path(legacy.__file__).absolute() == expected[1][0]
    assert Path(budget.__file__).absolute() == expected[2][0]
    assert len(observed) == 3
    for (pin, witness), (path, expected_sha) in zip(observed, expected):
        raw = path.read_bytes()
        assert pin == dict(path=str(path), bytes=len(raw), sha256=expected_sha)
        assert hashlib.sha256(raw).hexdigest() == expected_sha
        assert type(witness) is tuple and witness
    fresh = budget._owners()
    assert scope_owners[:3] == fresh[:3] and scope_owners[3] == fresh[3]
    assert any(pin["path"].endswith("legal_compact_content_scope_filter_v1.py") for pin in fresh[3])
    assert any(pin["path"].endswith("legal_compact_content_tokens_v1.py") for pin in fresh[3])


@pytest.mark.parametrize("field", ["_SELF_SHA", "_LEGACY_SHA", "_BUDGET_SHA"])
def test_bos_v2_actual_owner_factory_refuses_changed_pins_without_changing_files(field, monkeypatch):
    paths = [subject._SELF_PATH,
        subject._SELF_PATH.with_name("legal_compact_content_role_trained_runtime_v1.py"),
        subject._SELF_PATH.with_name("legal_compact_content_completion_budget_v1.py")]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert getattr(subject, field) != "0" * 64
    monkeypatch.setattr(subject, field, "0" * 64)
    with pytest.raises(ValueError):
        subject._owners()
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before
