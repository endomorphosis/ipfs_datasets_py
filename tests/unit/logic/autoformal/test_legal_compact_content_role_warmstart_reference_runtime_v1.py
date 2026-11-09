"""Historical authored contracts plus a separately bounded predicate panel.

The first23 published controls retain their explicit checkpoint/session/tensor
doubles. Their only assertion extension is the additional public API export.
The appended predicate controls use genuine retained state/reference packets;
exactly four labelled cases construct models and compare full teacher-forced
score matrices against the successful earlier training captures. Other added
controls refuse before model allocation or use explicitly labelled sessions.
No Adam, backward, update, generation, learning or legal authority is allowed.
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
    assert subject.__all__ == ["ReferenceScoreError", "score_reference", "score_predicate_reference"]
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


# These additions do not turn the published doubles above into numerical tests.
# Only the four explicit cases below may enter a genuine prepared model.
import os


PREDICATE_NUMERICAL_TEST = "test_predicate_reference_four_saved_full_matrices"
PREDICATE_CASES = (
    ("full537", "initial.json", 0, "step-1-report.json", "full537-initial-row0"),
    ("full537", "step-1.json", 1, "step-2-report.json", "full537-step1-row1"),
    ("scope_conditional", "initial.json", 0, "step-1-report.json", "scope_conditional-initial-row0"),
    ("scope_conditional", "step-1.json", 1, "step-2-report.json", "scope_conditional-step1-row1"),
)
PREDICATE_PRIOR_QUALIFICATION_SHA256 = "89f0c6dc11d3ea044992e1dbd83fd474c6622343210bc7a72eecc47b59a4b2a0"
PREDICATE_OLD_FILES = {
    "full537-step-0.json": (2704855, "599da742ac6bb76c59ae38ac3274fbe37e8064bfa22be5eb3493baea5916fbf3"),
    "full537-step-1.json": (3228182, "155497cfafe703c7c99b44df7d44a525099655a76000ed6dd75f24fe7f386b25"),
    "scope_conditional-step-0.json": (2704885, "5458464a4ebadef9820247d9dd025e255d498c508b3c039c2afdff8e03d7fc23"),
    "scope_conditional-step-1.json": (3052648, "2823d625237dda8d51e57a7d370fd0baac45a5e0085482a4aa92fa4a85b8f398"),
}
PREDICATE_SAVED_FILES = {
    "full537-initial.json": (340468, "dd1b7ae18d81545f528c9ebc8a7561416efef41ad25fbb7308d2857ac0762879"),
    "full537-step-1.json": (863770, "a4fc707ab59f4fc44a0ae931f5337ddedc8ea821e9abc04caaff26fe39b99718"),
    "full537-step-1-report.json": (1595399, "2e55b0a7245eb4e5e21095c20f00fb73e8c2b26fad622147bcd396d4e33bbad7"),
    "full537-step-2-report.json": (1595434, "c5b9975826b218a7b9a248172b36a8892e320b0cacfd1608d971a0c5b7053590"),
    "scope_conditional-initial.json": (340498, "e6166351d14aec13871870d4b652f0b0282953bb09fd247404af1bb5ae44582d"),
    "scope_conditional-step-1.json": (688226, "a024c0db96e030d74a08f1bd1dfe34f2efc34fedb90819c8231041f03b3a5cd5"),
    "scope_conditional-step-1-report.json": (962104, "c1da9b6e3d2b55541d6cf44daf5bbb0d4799d3fb6668c94b4813f5c993d9119d"),
    "scope_conditional-step-2-report.json": (962017, "0e1152780ab5ab9a3c1397fde727dcbbcd37fb349a1e5f37ff0c3fe240a6abe7"),
}


def _predicate_wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()


def _predicate_digest(value):
    return hashlib.sha256(_predicate_wire(value)).hexdigest()


@pytest.fixture(scope="session")
def predicate_retained():
    root = Path(__file__).parents[4]
    original_root = Path(os.environ.get("LEGAL_IR_CP128_EXPORTS", root /
        "workspace/test-logs/federal-corpus-audits/owned-validation-runs/"
        "cp128-warmstart-qualification-v01-cp128-warmstart-mechanics/exports"))
    saved_root = Path(os.environ.get("LEGAL_IR_PREDICATE_TRAINING_EXPORTS", root /
        "workspace/test-logs/federal-corpus-audits/owned-validation-runs/"
        "legal-ir-predicate-training-20261023-04/exports"))
    if ("LEGAL_IR_CP128_EXPORTS" not in os.environ
            or "LEGAL_IR_PREDICATE_TRAINING_EXPORTS" not in os.environ) and (
            not all((original_root / name).is_file() for name in PREDICATE_OLD_FILES)
            or not all((saved_root / name).is_file() for name in PREDICATE_SAVED_FILES)):
        pytest.skip("retained predicate/reference evidence is not installed in this checkout")
    values, descriptors, originals, original_descriptors = {}, {}, {}, {}
    for base, table, selected_values, selected_descriptors in (
            (original_root, PREDICATE_OLD_FILES, originals, original_descriptors),
            (saved_root, PREDICATE_SAVED_FILES, values, descriptors)):
        assert base.is_absolute() and base.resolve(strict=True) == base
        for name, (size, pin) in table.items():
            path = base / name
            assert path.resolve(strict=True) == path
            raw = path.read_bytes()
            assert len(raw) == size and hashlib.sha256(raw).hexdigest() == pin
            assert name not in selected_values
            selected_values[name] = json.loads(raw)
            selected_descriptors[name] = dict(path=str(path), bytes=size, sha256=pin)
    for kind, checkpoint_name, row_index, report_name, _case_id in PREDICATE_CASES:
        checkpoint = values[kind + "-" + checkpoint_name]
        oracle = values[kind + "-" + report_name]
        assert _predicate_digest(checkpoint) == oracle["checkpoint_before_sha256"]
        assert oracle["row_index"] == row_index and oracle["objective_kind"] == kind
        assert _predicate_digest(oracle["logits"]) == oracle["logits_sha256"]
    return values, descriptors, originals, original_descriptors


def _predicate_offer(retained, kind="full537", checkpoint_name="initial.json", row_index=0):
    values, _descriptors, originals, _original_descriptors = retained
    checkpoint = deepcopy(values[kind + "-" + checkpoint_name])
    references = {"row" + str(i): deepcopy(originals[kind + "-step-" + str(i) + ".json"])
                  for i in (0, 1)}
    parent = references["row" + str(row_index)]["warmstart_parent_checkpoint"]
    row = parent["basis_checkpoint"]["rows_utf8"][row_index]
    ids = deepcopy(parent["role_inventories"][row_index]["target_ids"])
    raw = row["context_utf8"].encode()
    return dict(checkpoint=checkpoint, conditioning=deepcopy(row["conditioning"]),
        reference_ids=ids, context_raw=raw, reference_inputs=references,
        expected_checkpoint_sha256=_predicate_digest(checkpoint),
        expected_policy_sha256=checkpoint["objective_policy_sha256"],
        expected_context_sha256=hashlib.sha256(raw).hexdigest(),
        expected_reference_sha256=_predicate_digest(ids), row_index=row_index,
        context_origin="target_derived_label")


def _predicate_snapshot(offered):
    return (_predicate_wire({key: value for key, value in offered.items() if key != "context_raw"}),
            offered["context_raw"])


@pytest.fixture(autouse=True)
def predicate_no_training(request, monkeypatch):
    if not request.node.originalname.startswith("test_predicate_reference_"):
        return
    torch = pytest.importorskip("torch")
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        legal_compact_content_predicate_training_v1 as predicate,
        legal_compact_content_role_warmstart_training_v1 as legacy_training,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical

    def forbidden(*_args, **_kwargs):
        raise AssertionError("undeclared optimizer/training/numerical lifecycle in predicate reference case")

    for target, name in ((torch.optim.Adam, "__init__"), (torch.optim.Optimizer, "__init__"),
            (torch.optim.Adam, "step"), (torch.autograd, "backward"), (torch.autograd, "grad"),
            (torch.Tensor, "backward"), (torch.nn.utils, "clip_grad_norm_"),
            (torch, "save"), (torch, "load")):
        monkeypatch.setattr(target, name, forbidden)
    for module in (predicate, legacy_training):
        for name in ("create", "restore", "training_row", "objective", "pack"):
            monkeypatch.setattr(module, name, forbidden)
    if request.node.originalname != PREDICATE_NUMERICAL_TEST:
        monkeypatch.setattr(numerical, "_model", forbidden)


class PredicateModelTrace:
    """Observe genuine calls, without replacing validation or score arithmetic."""
    def __init__(self, monkeypatch, torch, offered):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
        self.torch, self.offered = torch, offered
        self.models, self.sessions, self.handles = [], [], []
        self.scores = None
        self.counts = dict(model_factories=0, prepared_inits=0, state_loads=0,
            evals=0, forwards=0, gru_forwards=0, closes=0)
        self.views = []
        model_factory, init = numerical._model, prepared._PreparedModel.__init__
        load_state, evaluate = torch.nn.Module.load_state_dict, torch.nn.Module.eval
        gru, close = torch.nn.GRU.forward, prepared._PreparedModel.close
        trace = self

        def factory(*args, **kwargs):
            model = model_factory(*args, **kwargs)
            trace.models.append(model)
            trace.counts["model_factories"] += 1
            trace.handles.extend((model.register_forward_pre_hook(trace.before_forward),
                                  model.register_forward_hook(trace.after_forward)))
            return model

        def initialize(session, view, conditioning, loaded, fence):
            trace.views.append(deepcopy(view))
            result = init(session, view, conditioning, loaded, fence)
            trace.sessions.append(session)
            trace.counts["prepared_inits"] += 1
            return result

        def loaded(model, *args, **kwargs):
            result = load_state(model, *args, **kwargs)
            if any(model is known for known in trace.models):
                trace.counts["state_loads"] += 1
                assert {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()} \
                    == trace.offered["checkpoint"]["model_state"]
            return result

        def evaluated(model, *args, **kwargs):
            result = evaluate(model, *args, **kwargs)
            if any(model is known for known in trace.models):
                trace.counts["evals"] += 1
            return result

        def recurrent(module, *args, **kwargs):
            assert len(trace.models) == 1 and module is trace.models[0].decoder
            trace.counts["gru_forwards"] += 1
            return gru(module, *args, **kwargs)

        def closed(session):
            trace.counts["closes"] += 1
            return close(session)

        for target, name, replacement in ((numerical, "_model", factory),
                (prepared._PreparedModel, "__init__", initialize),
                (torch.nn.Module, "load_state_dict", loaded), (torch.nn.Module, "eval", evaluated),
                (torch.nn.GRU, "forward", recurrent), (prepared._PreparedModel, "close", closed)):
            monkeypatch.setattr(target, name, replacement)

    def before_forward(self, model, inputs):
        torch = self.torch
        assert len(self.models) == 1 and model is self.models[0]
        assert torch.is_inference_mode_enabled() and not torch.is_grad_enabled()
        assert all(module.training is False for module in model.modules())
        assert all(parameter.grad is None for parameter in model.parameters())
        vector, prefix = inputs
        assert list(vector.shape) == [1, 384] and vector.dtype is torch.float32 and vector.device.type == "cpu"
        assert list(prefix.shape) == [1, 46] and prefix.dtype is torch.long and prefix.device.type == "cpu"
        assert torch.equal(vector, torch.tensor([self.offered["conditioning"]], dtype=torch.float32, device="cpu"))
        assert prefix.detach().tolist() == [self.offered["reference_ids"][:-1]]
        self.counts["forwards"] += 1

    def after_forward(self, _model, _inputs, outputs):
        projected, logits = outputs
        torch = self.torch
        assert torch.is_inference_mode_enabled() and not torch.is_grad_enabled()
        assert list(projected.shape) == [1, 384] and list(logits.shape) == [1, 46, 537]
        for value in (projected, logits):
            assert value.dtype is torch.float32 and value.device.type == "cpu"
            assert not value.requires_grad and value.grad_fn is None and bool(torch.isfinite(value).all())
        self.scores = logits.detach().tolist()

    def finish(self):
        for handle in self.handles:
            handle.remove()


def _predicate_save_capture(root, name, value):
    assert root.is_absolute() and root.resolve(strict=True) == root and Path(name).name == name
    raw = _predicate_wire(value) + b"\n"
    assert len(raw) <= 4 * 1024**2
    path = root / name
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("kind,checkpoint_name,row_index,report_name,case_id", PREDICATE_CASES,
    ids=[case[-1] for case in PREDICATE_CASES])
def test_predicate_reference_four_saved_full_matrices(
        predicate_retained, monkeypatch, tmp_path, kind, checkpoint_name, row_index, report_name, case_id):
    torch = pytest.importorskip("torch")
    offered = _predicate_offer(predicate_retained, kind, checkpoint_name, row_index)
    before = _predicate_snapshot(offered)
    rng = torch.get_rng_state().clone()
    trace = PredicateModelTrace(monkeypatch, torch, offered)
    try:
        report = subject.score_predicate_reference(**offered)
        assert trace.counts == dict(model_factories=1, prepared_inits=1, state_loads=1,
            evals=1, forwards=1, gru_forwards=1, closes=1)
        assert len(trace.sessions) == len(trace.models) == 1 and trace.sessions[0].closed is True
        assert trace.sessions[0].model is trace.sessions[0].vector is trace.sessions[0].states is None
        assert all(parameter.grad is None for parameter in trace.models[0].parameters())
        assert _predicate_snapshot(offered) == before and torch.equal(rng, torch.get_rng_state())
        view = trace.views[0]
        assert view["schema"] == "legal-predicate-model-serving-view/v1"
        assert view["checkpoint_schema"] == offered["checkpoint"]["schema"]
        assert view["model_state"] == offered["checkpoint"]["model_state"]
        assert view["parameter_order"] == offered["checkpoint"]["parameter_order"]
        assert set(view) == set(warm._MODEL_FIELDS) | {
            "schema", "checkpoint_sha256", "checkpoint_schema", "objective_kind", "objective_policy_sha256"}
        assert not {"reference_inputs", "warmstart_parent_checkpoint", "optimizer_state", "reference_commitments",
            "basis_checkpoint", "role_inventories", "target_ids", "context_utf8"}.intersection(view)
        assert report["schema"] == "legal-predicate-reference-scores/v1"
        assert report["profile"] == "authored384-fixed537-predicate-sum70-reference46/v1"
        assert report["checkpoint_sha256"] == offered["expected_checkpoint_sha256"]
        assert report["checkpoint_schema"] == offered["checkpoint"]["schema"]
        assert report["checkpoint_profile"] == offered["checkpoint"]["profile"]
        assert report["objective_kind"] == kind
        assert report["objective_policy_sha256"] == offered["expected_policy_sha256"]
        assert report["weights_sha256"] == offered["checkpoint"]["weights_sha256"]
        assert report["codec_sha256"] == offered["checkpoint"]["codec_sha256"]
        assert report["progress"] == offered["checkpoint"]["progress"]
        assert report["checkpoint_schema_conversion_performed"] is False
        assert report["serving_view_sha256"] == _predicate_digest(view)
        assert report["serving_view_fields"] == sorted(view)
        assert report["row_index"] == row_index and report["progress_cursor_used_for_selection"] is False
        assert report["reference_context_not_current_model_state"] is True
        assert report["reference_checkpoint_sha256"] == offered["checkpoint"]["reference_commitments"]["row" + str(row_index)]["checkpoint_sha256"]
        assert report["reference_ids"] == offered["reference_ids"]
        assert report["reference_prefix_ids"] == offered["reference_ids"][:-1]
        assert report["label_ids"] == offered["reference_ids"][1:]
        assert report["reference_sha256"] == offered["expected_reference_sha256"]
        assert report["reference_prefix_sha256"] == _predicate_digest(offered["reference_ids"][:-1])
        assert report["reference_origin"] == subject.REFERENCE_ORIGIN
        assert report["context_raw_sha256"] == offered["expected_context_sha256"]
        assert report["context_origin"] == "target_derived_label"
        assert report["conditioning_sha256"] == _predicate_digest(offered["conditioning"])
        assert report["actual_model_inputs"] == ["conditioning_vector", "reference_ids_without_terminal_EOS"]
        assert all(report[key] is True for key in ("target_access_for_checkpoint_validation",
            "reference_bank_target_access_for_validation", "reference_bank_Adam_metadata_read_for_validation",
            "supplied_reference_target_access_declared", "supplied_context_target_access_declared"))
        assert all(report[key] is False for key in ("serving_view_contains_training_targets",
            "serving_view_contains_optimizer_state", "serving_view_contains_reference_bank",
            "optimizer_constructed", "optimizer_state_restored", "training_executed", "backward_performed",
            "token_selection_performed", "generation_performed", "causal_gradient_history_attested"))
        assert report["checkpoint_inspection_count"] == report["model_restore_count"] == report["numerical_forward_count"] == 1
        assert report["status"] == "scored" and report["model_executed"] is report["runtime_verified"] is True
        assert report["output_shape"] == [1, 46, 537] and report["logits"] == trace.scores
        assert report["logits_sha256"] == _predicate_digest(trace.scores)
        assert report["settings"]["raw_unmasked_scores"] is report["settings"]["full_prefix_once"] is True
        assert report["settings"]["cross_call_model_cache"] is report["settings"]["incremental_hidden_state"] is False
        assert not {"generated_ids", "selected_token_ids", "selection", "allowed_token_ids", "trace"}.intersection(report)
        assert all(value is False for value in report["authority"].values())
        assert type(report["training_mask"]) is type(report["evaluation_gold_mask"]) is int
        assert report["training_mask"] == report["evaluation_gold_mask"] == 0
        oracle = predicate_retained[0][kind + "-" + report_name]
        expected = oracle["logits"]
        assert len(trace.scores) == len(expected) == 1 and len(trace.scores[0]) == len(expected[0]) == 46
        compared, exact, maximum = 0, 0, 0.0
        for actual_row, expected_row in zip(trace.scores[0], expected[0]):
            assert len(actual_row) == len(expected_row) == 537
            for actual, wanted in zip(actual_row, expected_row):
                assert type(actual) is type(wanted) is float and math.isfinite(actual) and math.isfinite(wanted)
                assert math.isclose(actual, wanted, rel_tol=2e-6, abs_tol=2e-6)
                compared += 1
                exact += int(actual == wanted)
                maximum = max(maximum, abs(actual - wanted))
        assert compared == 24702
        # BOS is an explicitly included537-coordinate subset, not a fifth forward.
        assert all(math.isclose(a, b, rel_tol=2e-6, abs_tol=2e-6)
            for a, b in zip(trace.scores[0][0], expected[0][0]))
        parity = dict(schema="legal-ir-predicate-reference-parity/v1", case_id=case_id,
            objective_kind=kind, row_index=row_index, checkpoint_sha256=offered["expected_checkpoint_sha256"],
            objective_policy_sha256=offered["expected_policy_sha256"],
            prior_training_qualification_sha256=PREDICATE_PRIOR_QUALIFICATION_SHA256,
            oracle_report=predicate_retained[1][kind + "-" + report_name],
            oracle_logits_sha256=oracle["logits_sha256"], actual_logits_sha256=report["logits_sha256"],
            output_shape=[1, 46, 537], compared_coordinates=compared, first_position_coordinates=537,
            first_position_is_subset=True, relative_tolerance=2e-6, absolute_tolerance=2e-6,
            maximum_absolute_error=maximum, exact_equal_coordinates=exact, all_within_tolerance=True,
            observed_counts=trace.counts, source_and_reference_inputs_unchanged=True, final_rng_unchanged=True,
            teacher_forced_reference_exposure_declared=True, context_origin=offered["context_origin"],
            causal_gradient_history_attested=False, learning_or_convergence_claimed=False,
            training_mask=0, evaluation_gold_mask=0)
        root = Path(os.environ.get("LEGAL_IR_PREDICATE_REFERENCE_CAPTURES", tmp_path))
        _predicate_save_capture(root, case_id + "-scores.json", report)
        _predicate_save_capture(root, case_id + "-parity.json", parity)
    finally:
        trace.finish()


PREDICATE_REFUSALS = (
    "checkpoint-pin", "policy-pin", "context-pin", "reference-pin",
    "row-bool", "row-negative", "row-out-of-range",
    "reference-short", "reference-bool", "reference-oov",
    "wrong-row-reference", "wrong-row-context", "wrong-row-conditioning",
    "missing-reference", "foreign-domain-reference", "old-checkpoint-new-route",
    "new-checkpoint-old-route", "resealed-authority",
)


@pytest.mark.parametrize("damage", PREDICATE_REFUSALS)
def test_predicate_reference_genuine_refusals_precede_any_model(predicate_retained, monkeypatch, damage):
    offered = _predicate_offer(predicate_retained)
    if damage.endswith("-pin"):
        key = {"checkpoint-pin": "expected_checkpoint_sha256", "policy-pin": "expected_policy_sha256",
               "context-pin": "expected_context_sha256", "reference-pin": "expected_reference_sha256"}[damage]
        offered[key] = "0" * 64
    elif damage.startswith("row-"):
        offered["row_index"] = {"row-bool": True, "row-negative": -1, "row-out-of-range": 2}[damage]
    elif damage.startswith("reference-"):
        if damage == "reference-short": offered["reference_ids"].pop()
        elif damage == "reference-bool": offered["reference_ids"][1] = True
        else: offered["reference_ids"][1] = 537
        offered["expected_reference_sha256"] = _predicate_digest(offered["reference_ids"])
    elif damage.startswith("wrong-row-"):
        other = _predicate_offer(predicate_retained, row_index=1)
        if damage == "wrong-row-reference":
            offered["reference_ids"] = other["reference_ids"]
            offered["expected_reference_sha256"] = other["expected_reference_sha256"]
        elif damage == "wrong-row-context":
            offered["context_raw"] = other["context_raw"]
            offered["expected_context_sha256"] = other["expected_context_sha256"]
        else: offered["conditioning"] = other["conditioning"]
    elif damage == "missing-reference":
        offered["reference_inputs"].pop("row1")
    elif damage == "foreign-domain-reference":
        offered["reference_inputs"] = _predicate_offer(predicate_retained, kind="scope_conditional")["reference_inputs"]
    elif damage == "old-checkpoint-new-route":
        offered["checkpoint"] = deepcopy(offered["reference_inputs"]["row0"])
        offered["expected_checkpoint_sha256"] = _predicate_digest(offered["checkpoint"])
    elif damage == "resealed-authority":
        key = next(iter(offered["checkpoint"]["authority"]))
        offered["checkpoint"]["authority"][key] = True
        offered["expected_checkpoint_sha256"] = _predicate_digest(offered["checkpoint"])
    before = _predicate_snapshot(offered)
    allocations = []

    def forbidden_factory(*_args, **_kwargs):
        allocations.append(True)
        raise AssertionError("invalid predicate intake reached a model session")

    monkeypatch.setattr(subject, "_reference_session_class", forbidden_factory)
    with pytest.raises(ValueError):
        if damage == "new-checkpoint-old-route":
            subject.score_reference(**{key: value for key, value in offered.items() if key != "reference_inputs"})
        else:
            subject.score_predicate_reference(**offered)
    assert allocations == [] and _predicate_snapshot(offered) == before


def _predicate_poison_observation(monkeypatch, predicate):
    source = predicate._source

    def changed(path, expected):
        value = source(path, expected)
        if path == predicate._SELF_PATH:
            metadata, identity = value
            return dict(metadata, sha256="0" * 64), identity
        return value

    monkeypatch.setattr(predicate, "_source", changed)


def test_predicate_reference_row_selector_and_primary_error_survive_closing_failure(
        predicate_retained, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_predicate_training_v1 as predicate
    offered = _predicate_offer(predicate_retained, checkpoint_name="step-1.json", row_index=0)
    assert offered["checkpoint"]["progress"]["row_cursor"] == 1
    before, selected, factories = _predicate_snapshot(offered), [], []
    bound, operation = subject._bound_row, subject._operation
    original = RuntimeError("labelled stop before actual prepared-model allocation")

    def genuine_bound(value, data, helper):
        row = bound(value, data, helper)
        selected.append((data["row_index"], row["id"]))
        return row

    class StopBeforeAllocation:
        def __init__(self, view, conditioning, _loaded, _fence):
            factories.append(True)
            assert view["model_state"] == offered["checkpoint"]["model_state"]
            assert conditioning == offered["conditioning"]
            raise original

    def closing_operation(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        finally:
            if factories:
                _predicate_poison_observation(monkeypatch, predicate)

    monkeypatch.setattr(subject, "_bound_row", genuine_bound)
    monkeypatch.setattr(subject, "_reference_session_class", lambda _helper: StopBeforeAllocation)
    monkeypatch.setattr(subject, "_operation", closing_operation)
    with pytest.raises(RuntimeError) as raised:
        subject.score_predicate_reference(**offered)
    assert raised.value is original and factories == [True] and len(selected) == 1 and selected[0][0] == 0
    assert any("final predicate reference custody check" in note.lower()
        for note in getattr(original, "__notes__", ()))
    assert _predicate_snapshot(offered) == before


@pytest.mark.parametrize("damage", ("source-observation", "loaded-origin"))
def test_predicate_reference_final_wire_rechecks_new_owner_without_numerics(
        predicate_retained, monkeypatch, damage):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_predicate_training_v1 as predicate
    offered = _predicate_offer(predicate_retained)
    before, completed, sessions = _predicate_snapshot(offered), [], []
    operation = subject._operation

    class ExplicitAuthoredSession:
        """A model-free producer solely to reach the final metadata boundary."""
        def __init__(self, view, conditioning, _loaded, fence):
            self.view, self.conditioning, self.fence = view, conditioning, fence
            self.closed, self.closes = False, 0
            sessions.append(self)

        def _guard(self):
            assert self.closed is False, "the outer closing check must not call a closed session"
            self.fence()

        def forward_reference(self, prefix):
            self._guard()
            assert prefix == offered["reference_ids"][:-1]
            return dict(logits=[[[0.125] * 537 for _ in range(46)]],
                numeric_conditioning=list(self.conditioning), output_shape=[1, 46, 537],
                runtime=deepcopy(offered["checkpoint"]["runtime"]))

        def close(self):
            self._guard()
            self.closes += 1
            self.closed = True

    def final_wire(*args, **kwargs):
        result = operation(*args, **kwargs)
        completed.append(True)
        # This occurs only after genuine validation, session close and the old
        # operation's complete final serialization/detached-return boundary.
        if damage == "source-observation":
            _predicate_poison_observation(monkeypatch, predicate)
        else:
            monkeypatch.setattr(predicate, "__file__", str(Path(predicate.__file__).with_name("foreign.py")))
        return result

    monkeypatch.setattr(subject, "_reference_session_class", lambda _helper: ExplicitAuthoredSession)
    monkeypatch.setattr(subject, "_operation", final_wire)
    with pytest.raises(ValueError):
        subject.score_predicate_reference(**offered)
    assert completed == [True] and len(sessions) == 1
    assert sessions[0].closed is True and sessions[0].closes == 1
    assert _predicate_snapshot(offered) == before

