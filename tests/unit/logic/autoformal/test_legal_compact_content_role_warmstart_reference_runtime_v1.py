"""Finite authored controls for the separate reference-score diagnostic.

The checkpoint, model sessions, tensors and scores below are explicit authored
doubles. Existing pure input, snapshot, hashing and whole-report helpers are
used. No test reads a saved checkpoint/vector/matrix, restores a Torch model,
constructs Adam, runs a genuine numerical forward or supplies legal authority.
The source-only factory tests use original canonical owners. A separately
admitted genuine checkpoint/matrix cohort is still required for numerical
qualification; these controls cannot establish it.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_content_role_warmstart_reference_runtime_v1 as subject,
    legal_compact_content_role_warmstart_runtime_v1 as warm,
    legal_compact_content_prepared_runtime_v3 as prepared,
    legal_compact_content_role_training_v1 as role,
    legal_compact_content_role_trained_runtime_v1 as old_runtime,
)


def finish(failure, close):
    try:
        close()
    except BaseException:
        if failure is None:
            raise


class AuthoredReferenceSimulation:
    """Replace only new diagnostic seams; keep original pure helpers."""

    def __init__(self, monkeypatch, *, objective_kind="full537"):
        self.allocations = self.forwards = self.closes = self.checked = 0
        self.forward_error = self.close_error = self.on_forward = None
        self.damage = None
        self.seen_prefixes, self.views = [], []
        self.contexts = [b"authored row zero context", b"authored row one context"]
        self.vectors = [[0.25] * 384, [-0.75] * 384]
        self.references = [[1] + [3] * 45 + [2], [1] + [4] * 45 + [2]]
        parameters = ["authored_parameter_" + str(index) for index in range(13)]
        rows = [dict(id="authored-row-" + str(index), context_utf8=raw.decode(),
                     conditioning=list(self.vectors[index]), target_utf8="authored target marker")
                for index, raw in enumerate(self.contexts)]
        parent = dict(basis_checkpoint=dict(rows_utf8=rows),
                      role_inventories=[dict(target_ids=list(ids)) for ids in self.references])
        self.value = dict(schema="legal-compact-role-warmstart-training-checkpoint/v1",
            profile="authored-checkpoint-double-not-a-real-checkpoint",
            objective_policy=dict(objective_kind=objective_kind, weighting="semantic_priority"),
            weights_sha256="1" * 64, codec_sha256="c" * 64,
            progress=dict(optimizer_steps=2, epochs_completed=1, row_cursor=0),
            warmstart_parent_checkpoint_sha256="2" * 64, warmstart_parent_policy_sha256="3" * 64,
            historical_parent_optimizer_state_sha256="4" * 64,
            initial_checkpoint_sha256="5" * 64, parent_checkpoint_sha256="6" * 64,
            runtime=dict(authored_simulation="not a numerical runtime"), config=dict(authored=True),
            codec=dict(authored="not a real codec"), parameter_order=parameters,
            model_state={name: [float(index)] for index, name in enumerate(parameters)},
            warmstart_parent_checkpoint=parent, optimizer_state=dict(optimizer_marker="excluded Adam"))
        self.helper = SimpleNamespace(_fingerprint=prepared._fingerprint, _digest=prepared._digest,
            _wire=prepared._wire, _copy=prepared._copy,
            PREFIX_ORIGINS=prepared.PREFIX_ORIGINS, CONTEXT_ORIGINS=prepared.CONTEXT_ORIGINS)
        self.warm = SimpleNamespace(_owners=lambda: (None, old_runtime), _serving=warm._serving,
                                    _identity=warm._identity, SERVING_SCHEMA=warm.SERVING_SCHEMA)
        self.loaded = (Path("/authored/ipfs_datasets_py"), None,
                       dict(legacy_head=SimpleNamespace(_finish=finish, _conditioning=list)))
        self.original = self.snapshot = self.fingerprint = None
        monkeypatch.setattr(subject, "_operation", self.operation)
        monkeypatch.setattr(subject, "_checked", self.check)
        monkeypatch.setattr(subject, "_reference_session_class", lambda _helper: self.allocate)

    def operation(self, original, work):
        self.original = original
        self.snapshot = prepared._copy(original, prepared.MAX_INPUT_BYTES, allow_bytes=True)
        self.fingerprint = prepared._fingerprint(self.snapshot)
        self.fence()
        result = work(self.snapshot,
            dict(prepared=self.helper, role=role, reference_warmstart=self.warm), {}, self.loaded,
            [dict(path="/authored/source.py", sha256="a" * 64)], self.fence)
        raw = prepared._wire(result, subject.MAX_REPORT_BYTES)
        self.fence()
        return json.loads(raw)

    def fence(self):
        if self.fingerprint is not None:
            if (prepared._fingerprint(self.original) != self.fingerprint
                    or prepared._fingerprint(self.snapshot) != self.fingerprint):
                raise ValueError("authored original/captured input changed")

    def check(self, *_args):
        self.checked += 1
        return deepcopy(self.value)

    def scores(self):
        return [[[float(position * 1000 + token) for token in range(537)] for position in range(46)]]

    def allocate(self, view, conditioning, loaded, fence):
        assert loaded is self.loaded and len(conditioning) == 384
        self.allocations += 1
        self.views.append(deepcopy(view))
        outer = self

        class Session:
            def _guard(self):
                fence()

            def forward_reference(self, ids):
                outer.forwards += 1
                outer.seen_prefixes.append(list(ids))
                if outer.forward_error is not None:
                    raise outer.forward_error
                if outer.on_forward is not None:
                    outer.on_forward(view, conditioning, ids)
                result = dict(logits=outer.scores(), runtime=deepcopy(outer.value["runtime"]),
                              numeric_conditioning=list(conditioning), output_shape=[1, 46, 537])
                if outer.damage == "shape": result["output_shape"][-1] = 536
                elif outer.damage == "runtime": result["runtime"] = dict(changed=True)
                elif outer.damage == "conditioning": result["numeric_conditioning"][0] += 1.0
                elif outer.damage == "short_matrix": result["logits"][0].pop()
                elif outer.damage == "nonfinite": result["logits"][0][0][0] = float("nan")
                elif outer.damage == "integer_score": result["logits"][0][0][0] = 0
                return result

            def close(self):
                outer.closes += 1
                if outer.close_error is not None:
                    raise outer.close_error
                fence()

        return Session()

    def call(self, row_index=0, **overrides):
        selected = row_index if type(row_index) is int and row_index in (0, 1) else 0
        options = dict(checkpoint=dict(authored="not a checkpoint"),
            conditioning=list(self.vectors[selected]), reference_ids=list(self.references[selected]),
            context_raw=self.contexts[selected], expected_checkpoint_sha256="d" * 64,
            expected_policy_sha256="e" * 64,
            expected_context_sha256=hashlib.sha256(self.contexts[selected]).hexdigest(),
            expected_reference_sha256=prepared._digest(self.references[selected]),
            row_index=row_index, context_origin="authored_fixture")
        options.update(overrides)
        return subject.score_reference(**options)


def test_separate_reference_surface_preserves_original_bos_signatures():
    assert subject.__all__ == ["ReferenceScoreError", "score_reference"]
    for api in (warm.score_from_bos, warm.generate_from_bos):
        assert not {"reference_ids", "row_index", "expected_reference_sha256"}.intersection(inspect.signature(api).parameters)
    assert {"reference_ids", "row_index", "expected_reference_sha256"} <= set(inspect.signature(subject.score_reference).parameters)


def test_original_metadata_factory_and_new_source_custody_without_model():
    def work(data, owners, modules, loaded, pins, fence):
        assert data == dict(metadata_only=True)
        assert owners["reference_warmstart"] is warm and owners["prepared"] is prepared
        assert owners["reference_warmstart"]._checked is warm._checked
        names = {Path(row["path"]).name for row in pins}
        assert {"legal_compact_content_role_warmstart_reference_runtime_v1.py",
                "legal_compact_content_role_warmstart_runtime_v1.py",
                "legal_compact_content_prepared_runtime_v3.py"} <= names
        assert len({row["path"] for row in pins}) == len(pins)
        fence()
        return dict(metadata_only=True, numerical_session_requested=False)
    assert subject._operation(dict(metadata_only=True), work) == dict(metadata_only=True, numerical_session_requested=False)


def test_original_metadata_operation_enforces_complete_report_bound():
    with pytest.raises(ValueError):
        subject._operation(dict(metadata_only=True), lambda *_args: dict(too_large="x" * (subject.MAX_REPORT_BYTES + 1)))


def test_independent_self_source_commitment_refuses_before_work(monkeypatch):
    monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
    with pytest.raises(ValueError):
        subject._operation(dict(metadata_only=True), lambda *_args: pytest.fail("source refusal must precede work"))


def test_both_objective_identities_use_one_restore_full_reference_and_close(monkeypatch):
    for kind in ("full537", "scope_conditional"):
        sim = AuthoredReferenceSimulation(monkeypatch, objective_kind=kind)
        result = sim.call()
        assert result["schema"] == subject.SCORE_SCHEMA and result["profile"] == subject.PROFILE
        assert result["objective_kind"] == kind and result["output_shape"] == [1, 46, 537]
        assert result["logits"] == sim.scores() and result["logits"][0][45][536] == 45536.0
        assert sim.allocations == sim.forwards == sim.closes == sim.checked == 1
        assert sim.seen_prefixes == [sim.references[0][:-1]]
        assert result["reference_ids"] == sim.references[0] and result["label_ids"] == sim.references[0][1:]
        assert result["model_restore_count"] == result["numerical_forward_count"] == 1


def test_explicit_row_selection_is_independent_of_training_progress(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    assert sim.value["progress"]["row_cursor"] == 0
    result = sim.call(row_index=1)
    assert result["row_index"] == 1 and result["row_id"] == "authored-row-1"
    assert result["progress"]["row_cursor"] == 0 and result["progress_cursor_used_for_selection"] is False
    assert sim.seen_prefixes == [sim.references[1][:-1]]


def test_real_serving_projection_omits_historical_labels_and_optimizer(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    result = sim.call()
    view = sim.views[0]
    assert view["model_state"] == sim.value["model_state"] and len(view["parameter_order"]) == 13
    assert not {"warmstart_parent_checkpoint", "basis_checkpoint", "role_inventories", "optimizer_state"}.intersection(view)
    assert b"authored target marker" not in prepared._wire(view)
    assert b"excluded Adam" not in prepared._wire(view)
    assert result["serving_view_contains_training_targets"] is False
    assert result["serving_view_contains_optimizer_state"] is False
    assert result["checkpoint_schema_conversion_performed"] is False


def test_reference_hash_geometry_and_plain_types_refuse_before_allocation(monkeypatch):
    for change in (dict(expected_reference_sha256="0" * 64), dict(row_index=True), dict(row_index=2),
                   dict(reference_ids=[1, 3, 2]), dict(reference_ids=[1] + [True] * 45 + [2]),
                   dict(reference_ids=[1] + [537] * 45 + [2]), dict(reference_ids=[1, 2] + [3] * 44 + [2])):
        sim = AuthoredReferenceSimulation(monkeypatch)
        with pytest.raises(ValueError): sim.call(**change)
        assert sim.allocations == sim.forwards == sim.closes == 0


def test_real_context_and_vector_input_checks_refuse_before_allocation(monkeypatch):
    for change in (dict(expected_context_sha256="0" * 64), dict(context_origin="undeclared"),
                   dict(conditioning=[0.25]), dict(conditioning=[float("inf")] * 384)):
        sim = AuthoredReferenceSimulation(monkeypatch)
        with pytest.raises(ValueError): sim.call(**change)
        assert sim.allocations == sim.forwards == sim.closes == 0


def test_reference_context_and_conditioning_must_match_same_checkpoint_row(monkeypatch):
    for which in ("reference", "context", "conditioning"):
        sim = AuthoredReferenceSimulation(monkeypatch)
        change = dict(reference_ids=sim.references[1], expected_reference_sha256=prepared._digest(sim.references[1])) if which == "reference" else (
            dict(context_raw=sim.contexts[1], expected_context_sha256=hashlib.sha256(sim.contexts[1]).hexdigest()) if which == "context" else dict(conditioning=sim.vectors[1]))
        with pytest.raises(ValueError): sim.call(**change)
        assert sim.checked == 1 and sim.allocations == sim.forwards == sim.closes == 0


def test_missing_original_population_is_not_silently_reconstructed(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    sim.value["warmstart_parent_checkpoint"]["basis_checkpoint"]["rows_utf8"].pop()
    with pytest.raises(ValueError): sim.call()
    assert sim.checked == 1 and sim.allocations == 0


def test_full_matrix_runtime_geometry_conditioning_and_finiteness_refuse_and_close(monkeypatch):
    for damage in ("shape", "runtime", "conditioning", "short_matrix", "nonfinite", "integer_score"):
        sim = AuthoredReferenceSimulation(monkeypatch)
        sim.damage = damage
        with pytest.raises(ValueError): sim.call()
        assert sim.allocations == sim.forwards == sim.closes == 1


def test_original_caller_mutation_cannot_return_success(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    offered = dict(authored="not a checkpoint")
    sim.on_forward = lambda *_args: offered.update(changed=True)
    with pytest.raises(ValueError): sim.call(checkpoint=offered)
    assert sim.allocations == sim.forwards == sim.closes == 1


def test_serving_view_or_reference_prefix_mutation_cannot_return_success(monkeypatch):
    for what in ("view", "prefix"):
        sim = AuthoredReferenceSimulation(monkeypatch)
        sim.on_forward = (lambda view, *_args: view["model_state"].update(changed=[1.0])) if what == "view" else (
            lambda _view, _conditioning, ids: ids.append(2))
        with pytest.raises(ValueError): sim.call()
        assert sim.allocations == sim.forwards == sim.closes == 1


def test_forward_interruption_preserves_original_error_and_closes(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    error = KeyboardInterrupt("authored interrupted reference forward")
    sim.forward_error = error
    with pytest.raises(KeyboardInterrupt) as raised: sim.call()
    assert raised.value is error and sim.allocations == sim.forwards == sim.closes == 1


def test_close_failure_cannot_return_a_success_or_replace_existing_failure(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    sim.close_error = RuntimeError("authored close failure")
    with pytest.raises(RuntimeError, match="authored close failure"): sim.call()
    sim = AuthoredReferenceSimulation(monkeypatch)
    original = KeyboardInterrupt("authored original failure")
    sim.forward_error, sim.close_error = original, RuntimeError("authored closing failure")
    with pytest.raises(KeyboardInterrupt) as raised: sim.call()
    assert raised.value is original and sim.closes == 1


def test_calls_do_not_share_or_expose_model_sessions(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    first, second = sim.call(), sim.call(row_index=1)
    assert sim.allocations == sim.forwards == sim.closes == 2
    assert first["settings"]["cross_call_model_cache"] is second["settings"]["incremental_hidden_state"] is False
    assert "session" not in first and "session" not in second


def test_reference_access_raw_scores_and_all_authority_limits_remain_explicit(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    result = sim.call(context_origin="target_derived_label")
    assert result["supplied_reference_target_access_declared"] is result["supplied_context_target_access_declared"] is True
    assert result["reference_origin"] == subject.REFERENCE_ORIGIN and result["settings"]["raw_unmasked_scores"] is True
    assert result["actual_model_inputs"] == ["conditioning_vector", "reference_ids_without_terminal_EOS"]
    assert not {"generated_ids", "selection", "allowed_token_ids"}.intersection(result)
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    for name in ("optimizer_constructed", "optimizer_state_restored", "training_executed", "backward_performed", "token_selection_performed", "generation_performed"):
        assert result[name] is False


class AuthoredTensor:
    def __init__(self, values, shape, dtype="float32", device="cpu"):
        self.values, self.shape, self.dtype, self.device = values, tuple(shape), dtype, SimpleNamespace(type=device)

    def detach(self): return self
    def tolist(self): return deepcopy(self.values)


def flattened(value):
    if isinstance(value, list):
        return [item for child in value for item in flattened(child)]
    return [value]


class AuthoredPreparedBase:
    def __init__(self):
        self.guards = self.calls = self.closes = 0
        self.active = False
        self.numeric_conditioning = [0.25] * 384
        self.runtime = dict(authored="not Torch")
        self.vector = "authored vector marker"
        self.damage = None
        outer = self

        @contextmanager
        def inference_mode():
            outer.active = True
            try: yield
            finally: outer.active = False

        self.torch = SimpleNamespace(float32="float32", long="long", inference_mode=inference_mode,
            tensor=lambda values, dtype, device: AuthoredTensor(values, [len(values), len(values[0])], dtype, device),
            isfinite=lambda tensor: SimpleNamespace(all=lambda: all(math.isfinite(x) for x in flattened(tensor.values))))
        self.head = SimpleNamespace(_finish=finish)

    def _guard(self): self.guards += 1
    def close(self): self.closes += 1
    def forward(self, _ids): raise AssertionError("the original last-position method was not requested")

    def model(self, vector, prefix):
        assert self.active and vector == self.vector and prefix.dtype == "long"
        assert prefix.tolist() == [[3] * 46]
        self.calls += 1
        projected = AuthoredTensor([[0.25] * 384], [1, 384])
        scores = [[[float(i * 1000 + j) for j in range(537)] for i in range(46)]]
        logits = AuthoredTensor(scores, [1, 46, 537])
        if self.damage == "logit_shape": logits.shape = (1, 45, 537)
        elif self.damage == "projected_shape": projected.shape = (1, 383)
        elif self.damage == "dtype": logits.dtype = "float64"
        elif self.damage == "device": logits.device.type = "cuda"
        elif self.damage == "logit_nonfinite": logits.values[0][0][0] = float("inf")
        elif self.damage == "projected_nonfinite": projected.values[0][0] = float("nan")
        return projected, logits


def test_reference_extension_inherits_original_restore_guard_forward_and_close():
    cls = subject._reference_session_class(SimpleNamespace(_PreparedModel=AuthoredPreparedBase))
    for name in ("__init__", "_guard", "forward", "close"):
        assert getattr(cls, name) is getattr(AuthoredPreparedBase, name)
    assert set(cls.__dict__) - {"__module__", "__doc__"} == {"forward_reference"}


def test_reference_extension_observes_complete_matrix_once_under_inference_mode():
    cls = subject._reference_session_class(SimpleNamespace(_PreparedModel=AuthoredPreparedBase))
    session = cls()
    result = session.forward_reference([3] * 46)
    assert session.calls == 1 and session.guards >= 3 and session.active is False
    assert result["output_shape"] == [1, 46, 537]
    assert len(result["logits"][0]) == 46 and result["logits"][0][0][536] == 536.0
    assert result["logits"][0][45][536] == 45536.0
    assert result["numeric_conditioning"] == session.numeric_conditioning and result["runtime"] == session.runtime
    session.close()
    assert session.closes == 1


def test_reference_extension_rejects_tensor_shape_dtype_device_and_nonfinite_values():
    cls = subject._reference_session_class(SimpleNamespace(_PreparedModel=AuthoredPreparedBase))
    for damage in ("logit_shape", "projected_shape", "dtype", "device", "logit_nonfinite", "projected_nonfinite"):
        session = cls()
        session.damage = damage
        try:
            with pytest.raises(ValueError): session.forward_reference([3] * 46)
        finally:
            session.close()
        assert session.calls == session.closes == 1 and session.active is False and session.guards >= 2


def test_intact_validator_refusal_prevents_numerical_allocation(monkeypatch):
    sim = AuthoredReferenceSimulation(monkeypatch)
    def refuse(*_args):
        sim.checked += 1
        raise ValueError("authored intact validator refusal")
    monkeypatch.setattr(subject, "_checked", refuse)
    with pytest.raises(ValueError, match="authored intact validator refusal"):
        sim.call()
    assert sim.checked == 1 and sim.allocations == sim.forwards == sim.closes == 0


def test_closing_self_source_commitment_refusal_cannot_return_success(monkeypatch):
    entered = []
    def work(*_args):
        entered.append(True)
        monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
        return dict(authored_metadata_only=True)
    with pytest.raises(ValueError):
        subject._operation(dict(metadata_only=True), work)
    assert entered == [True]


SIMULATION_TEST_NAMES = (
    "test_intact_validator_refusal_prevents_numerical_allocation",
    "test_closing_self_source_commitment_refusal_cannot_return_success",
    "test_separate_reference_surface_preserves_original_bos_signatures",
    "test_original_metadata_factory_and_new_source_custody_without_model",
    "test_original_metadata_operation_enforces_complete_report_bound",
    "test_independent_self_source_commitment_refuses_before_work",
    "test_both_objective_identities_use_one_restore_full_reference_and_close",
    "test_explicit_row_selection_is_independent_of_training_progress",
    "test_real_serving_projection_omits_historical_labels_and_optimizer",
    "test_reference_hash_geometry_and_plain_types_refuse_before_allocation",
    "test_real_context_and_vector_input_checks_refuse_before_allocation",
    "test_reference_context_and_conditioning_must_match_same_checkpoint_row",
    "test_missing_original_population_is_not_silently_reconstructed",
    "test_full_matrix_runtime_geometry_conditioning_and_finiteness_refuse_and_close",
    "test_original_caller_mutation_cannot_return_success",
    "test_serving_view_or_reference_prefix_mutation_cannot_return_success",
    "test_forward_interruption_preserves_original_error_and_closes",
    "test_close_failure_cannot_return_a_success_or_replace_existing_failure",
    "test_calls_do_not_share_or_expose_model_sessions",
    "test_reference_access_raw_scores_and_all_authority_limits_remain_explicit",
    "test_reference_extension_inherits_original_restore_guard_forward_and_close",
    "test_reference_extension_observes_complete_matrix_once_under_inference_mode",
    "test_reference_extension_rejects_tensor_shape_dtype_device_and_nonfinite_values",
)

