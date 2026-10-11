"""Inert hook-contract tests; tensor/model objects below are diagnostic doubles.

No tensor library, genuine model, encoder, optimizer or inference runs here.
Manual callback delivery tests the copy/join contract, not native execution.
"""
from copy import deepcopy
import hashlib
import json
import re
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import retained_span_score_capture as capture


class TensorDouble:
    def __init__(self, values, shape, *, dtype="torch.float32", device="cpu", grad=False):
        self.values, self.shape, self.dtype = deepcopy(values), shape, dtype
        self.device, self.requires_grad = SimpleNamespace(type=device), grad
        self.copy_calls = []

    def detach(self):
        self.copy_calls.append("detach")
        return self

    def cpu(self):
        self.copy_calls.append("cpu")
        return self

    def tolist(self):
        self.copy_calls.append("tolist")
        return deepcopy(self.values)


class ModelDouble:
    def __init__(self):
        self._forward_hooks, self._forward_pre_hooks = {}, {}
        self.register_calls, self.remove_calls = 0, 0

    def register_forward_hook(self, callback):
        self.register_calls += 1
        self._forward_hooks[0] = callback

        def remove():
            self.remove_calls += 1
            self._forward_hooks.pop(0)

        return SimpleNamespace(remove=remove)

    def deliver_diagnostic_output(self, inputs, output):
        for callback in list(self._forward_hooks.values()):
            assert callback(self, inputs, output) is None
        return output


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode()


def fixture(*, overlap=False, duplicate=False):
    text = "Officer shall file records."
    tokens = [{"text": match.group(), "start": match.start(), "end": match.end()}
        for match in re.finditer(r"\w+|[^\w\s]", text)]
    size = len(tokens)
    locations = dict(actor=0, action=0 if overlap else 2, object=3, conditions=1, exceptions=1, temporal=1)
    start = [[10. if index == locations[field] else 0. for index in range(size)]
        for field in capture.SPAN_FIELDS]
    presence = [[-1., 1.], [1., -1.], [1., -1.], [1., -1.]]
    output = {"modality": TensorDouble([[3., 1., 0.]], (1, 3)),
        "presence": TensorDouble([presence], (1, 4, 2)),
        "start": TensorDouble([start], (1, 6, size)),
        "end": TensorDouble([start], (1, 6, size))}
    inputs = (TensorDouble([], (1, size, 1)), TensorDouble([], (1, size)),
        TensorDouble([size], (1,)), TensorDouble([], (1, 384)))
    facets = {}
    for field in capture.SPAN_FIELDS:
        present = field not in ("conditions", "exceptions", "temporal")
        diagnostic = dict(present=present, presence_logit_margin=2. if field in capture.OPTIONAL_FIELDS else None,
            token_start=None, token_end_inclusive=None, char_start=None, char_end=None, text=None,
            span_logit_margin=None)
        if present:
            index = locations[field]
            token = tokens[index]
            diagnostic.update(token_start=index, token_end_inclusive=index, char_start=token["start"],
                char_end=token["end"], text=token["text"], span_logit_margin=10.)
        facets[field] = diagnostic
        if overlap and field == "action":
            break
    sha = hashlib.sha256(text.encode()).hexdigest()
    raw = dict(source_sha256=sha, latent_sha256="a" * 64, latent_input_enabled=True,
        status="abstained" if overlap else "decoded", reason="copied_spans_overlap" if overlap else None,
        canonical_ir=None if overlap else {"rules": [{"modality": "O", "actor": "Officer", "action": "file",
            "object": "records", "conditions": [], "exceptions": [], "temporal": []}]},
        span_diagnostics=dict(tokens=tokens, facets=facets, modality_logits=[3., 1., 0.]))
    if not overlap:
        raw["minimum_decision_logit_margin"] = 2.
    source_rows = [{"id": "physical-1", "source_text": text}]
    rows = [dict(id="physical-1", position=0, source_sha256=sha, decoder_row=raw,
        outcome="decoder_abstained" if overlap else "decoder_proposal", effective_latent_sha256="a" * 64,
        latent_input_enabled=True, latent_donor_id="physical-1", latent_donor_position=0)]
    if duplicate:
        source_rows.append({"id": "physical-2", "source_text": text})
        rows.append(dict(id="physical-2", position=1, source_sha256=sha, decoder_row=None,
            outcome="source_blocked", effective_latent_sha256="b" * 64,
            latent_input_enabled=True, latent_donor_id="physical-2", latent_donor_position=1))
    report = dict(schema="arbitrary-native-retained-span-inference/v1",
        decoder_contract_id="arbitrary-raw-gte384-retained-span/v1", checkpoint_metadata={"checkpoint_sha256": "c"*64},
        control="none", rows=rows, input_count=len(rows), eligible_count=1, submitted_positions=[0],
        custody_scope="diagnostic double", outcome_counts={},
        raw_owner_report={"rows": [deepcopy(raw)], "latent_ablation": "none", "checkpoint_sha256": "c"*64},
        decoder_calls=1, optimizer_steps_executed=0, numerical_custody_checked=True,
        weights_unchanged=True, ambient_CPU_RNG_preserved=True, authority={"qualified": False})
    return source_rows, inputs, output, report


def deliver(source_rows, inputs, output, report):
    model = ModelDouble()
    owner = capture.RetainedSpanScoreCapture(source_rows, submitted_positions=[0])
    with owner.attach(model):
        assert model.deliver_diagnostic_output(inputs, output) is output
    return owner.finalize(report), owner, model


def test_same_callback_copies_full_heads_preserving_raw_output_and_partial_refusal():
    sources, inputs, output, report = fixture(overlap=True, duplicate=True)
    before = wire(report)
    sidecar, owner, model = deliver(sources, inputs, output, report)
    assert wire(report) == before
    assert sidecar["raw_report_sha256"] == hashlib.sha256(before).hexdigest()
    assert sidecar["input_count"] == 2 and sidecar["captured_forward_count"] == 1
    assert sidecar["additional_model_forwards"] == 0 and sidecar["original_outputs_modified"] is False
    assert sidecar["rows"][1]["scores"] is None
    assert sidecar["rows"][0]["raw_reason"] == "copied_spans_overlap"
    assert set(sidecar["rows"][0]["scores"]["start_logits"]) == set(capture.SPAN_FIELDS)
    assert set(report["rows"][0]["decoder_row"]["span_diagnostics"]["facets"]) == {"actor", "action"}
    assert set(sidecar["rows"][0]["scores"]["presence_logits"]) == set(capture.OPTIONAL_FIELDS)
    assert all(value is False for value in sidecar["authority"].values())
    assert model.register_calls == model.remove_calls == 1 and not model._forward_hooks
    for value in output.values():
        assert value.copy_calls == ["detach", "cpu", "tolist"]
    assert owner._state == "finalized"


def test_complete_greedy_and_optional_absence_are_checked():
    sidecar, _, _ = deliver(*fixture())
    assert sidecar["rows"][0]["raw_status"] == "decoded"
    assert sidecar["raw_greedy_verification_count"] == 1
    scores = sidecar["rows"][0]["scores"]
    assert scores["presence_logits"]["conditions"] == [1., -1.]
    assert set(scores) == {"schema", "tokens", "modality_logits", "presence_logits", "start_logits", "end_logits"}


@pytest.mark.parametrize("head", ["modality", "presence", "span"])
def test_original_ambiguity_stays_refused_with_exact_early_diagnostics(head):
    sources, inputs, output, report = fixture()
    raw = report["rows"][0]["decoder_row"]
    raw.update(status="abstained", reason="ambiguous_decoder_scores", canonical_ir=None)
    raw.pop("minimum_decision_logit_margin")
    if head == "modality":
        output["modality"].values = [[1., 1., 0.]]
        raw["span_diagnostics"]["modality_logits"] = [1., 1., 0.]
        raw["span_diagnostics"]["facets"] = {}
    elif head == "presence":
        output["presence"].values[0][0] = [1., 1.]
        raw["span_diagnostics"]["facets"] = {field: raw["span_diagnostics"]["facets"][field]
            for field in ("actor", "action")}
    else:
        output["start"].values[0][1] = [0.] * 5
        output["end"].values[0][1] = [0.] * 5
        raw["span_diagnostics"]["facets"] = {"actor": raw["span_diagnostics"]["facets"]["actor"]}
    report["raw_owner_report"]["rows"][0] = deepcopy(raw)
    report["rows"][0]["outcome"] = "decoder_abstained"
    sidecar, _, _ = deliver(sources, inputs, output, report)
    assert sidecar["rows"][0]["raw_reason"] == "ambiguous_decoder_scores"
    assert len(sidecar["rows"][0]["scores"]["start_logits"]) == 6


def test_hook_removed_when_caller_raises():
    sources, _, _, _ = fixture()
    model = ModelDouble()
    owner = capture.RetainedSpanScoreCapture(sources, submitted_positions=[0])
    with pytest.raises(RuntimeError, match="caller refused"):
        with owner.attach(model):
            raise RuntimeError("caller refused")
    assert not model._forward_hooks and model.remove_calls == 1
    with pytest.raises(ValueError, match="counts differ"):
        owner.finalize(fixture()[3])


@pytest.mark.parametrize("change", ["dtype", "device", "grad", "shape", "nonfinite", "not_float32", "bool", "unknown_head"])
def test_strict_output_refuses_bad_numeric_or_geometry_and_removes_hook(change):
    sources, inputs, output, _ = fixture()
    if change == "dtype":
        output["start"].dtype = "torch.float64"
    elif change == "device":
        output["start"].device.type = "cuda"
    elif change == "grad":
        output["start"].requires_grad = True
    elif change == "shape":
        output["start"].shape = (2, 6, 5)
    elif change == "unknown_head":
        output["target"] = output["start"]
    else:
        output["start"].values[0][0][0] = {"nonfinite": float("nan"), "not_float32": .1, "bool": True}[change]
    model = ModelDouble()
    owner = capture.RetainedSpanScoreCapture(sources, submitted_positions=[0])
    with pytest.raises(ValueError):
        with owner.attach(model):
            model.deliver_diagnostic_output(inputs, output)
    assert owner._failed and not model._forward_hooks


@pytest.mark.parametrize("change", ["source", "position", "latent", "donor", "raw", "margin", "control", "authority", "count", "new_key"])
def test_final_join_rejects_source_raw_and_recipe_mutations(change):
    sources, inputs, output, report = fixture(overlap=True)
    owner = capture.RetainedSpanScoreCapture(sources, submitted_positions=[0])
    with owner.attach(ModelDouble()) as attached:
        attached._model.deliver_diagnostic_output(inputs, output)
    if change == "source":
        report["rows"][0]["source_sha256"] = "f"*64
    elif change == "position":
        report["rows"][0]["position"] = 1
    elif change == "latent":
        report["rows"][0]["effective_latent_sha256"] = "f"*64
    elif change == "donor":
        report["rows"][0]["latent_donor_id"] = "other-occurrence"
    elif change == "raw":
        report["raw_owner_report"]["rows"][0]["reason"] = "different"
    elif change == "margin":
        for raw in (report["rows"][0]["decoder_row"], report["raw_owner_report"]["rows"][0]):
            raw["span_diagnostics"]["facets"]["actor"]["span_logit_margin"] = 9.
    elif change == "control":
        report["control"] = "disabled"
    elif change == "authority":
        report["authority"]["qualified"] = True
    elif change == "count":
        report["eligible_count"] = True
    else:
        report["targets"] = []
    with pytest.raises(ValueError):
        owner.finalize(report)


def test_zero_eligible_preserves_all_rows_without_hook_or_model():
    sources, _, _, report = fixture()
    report.update(eligible_count=0, submitted_positions=[], raw_owner_report=None,
        decoder_calls=0, numerical_custody_checked=False, weights_unchanged=None, ambient_CPU_RNG_preserved=None)
    report["rows"][0].update(decoder_row=None, outcome="source_blocked")
    owner = capture.RetainedSpanScoreCapture(sources, submitted_positions=[])
    with owner.attach(None):
        pass
    sidecar = owner.finalize(report)
    assert sidecar["captured_forward_count"] == 0 and sidecar["rows"][0]["scores"] is None


def test_f32_addition_and_subtraction_match_owner_rounding_not_python_double():
    value = capture._f32(1e-7)
    assert capture._f32(1. + value) == 1.0000001192092896
    assert capture._f32(capture._f32(1. + value) - 1.) > 1e-7
    assert capture._f32(1. + value / 2.) == 1.
    winner, margin = capture._pair_winners([1., 0.], [value, 0.])
    assert winner == (1.0000001192092896, 0, 0)
    assert margin == 1.1920928955078125e-7


def test_float32_tied_pair_uses_original_row_major_order():
    winner, margin = capture._pair_winners([1., 1.], [2., 2.])
    assert winner == (3., 0, 0) and margin == 0.


def test_one_use_extra_callbacks_and_existing_hooks_refused():
    sources, inputs, output, report = fixture()
    owner = capture.RetainedSpanScoreCapture(sources, submitted_positions=[0])
    model = ModelDouble()
    model._forward_pre_hooks[0] = object()
    with pytest.raises(ValueError, match="registry"):
        with owner.attach(model):
            pass
    model._forward_pre_hooks.clear()
    with owner.attach(model):
        model.deliver_diagnostic_output(inputs, output)
        with pytest.raises(ValueError, match="unexpected"):
            model.deliver_diagnostic_output(inputs, output)
    assert not model._forward_hooks
    with pytest.raises(ValueError, match="successful"):
        owner.finalize(report)
    with pytest.raises(ValueError, match="one-use"):
        with owner.attach(model):
            pass


@pytest.mark.parametrize("sources,positions", [([], []), ([{"id": "a", "source_text": "x", "target": {}}], []),
    ([{"id": "a", "source_text": "x"}], [True]), ([{"id": "a", "source_text": "x"}], [0, 0])])
def test_closed_source_only_constructor(sources, positions):
    with pytest.raises(ValueError):
        capture.RetainedSpanScoreCapture(sources, submitted_positions=positions)
