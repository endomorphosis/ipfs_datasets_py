"""Unmasked three-form observations of unchanged seeded counted28 weights."""
from copy import deepcopy
import hashlib
import inspect
import json
import math

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_counted_threshold_numerical_view_v2 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_counted_content_head_v1 as host
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as base
from ipfs_datasets_py.logic.autoformal import legal_counted_threshold_codec_v2 as codec_owner
from ipfs_datasets_py.logic.autoformal import legal_counted_frame_threshold_v2 as factory

CONFIG = dict(hidden_size=8, token_embedding_dim=8, projection_width=4, seed=1729)
VECTOR = [1.] + [0.] * 383


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def forbidden(*args, **kwargs):
    pytest.fail("invalid input reached numerical forward or forbidden optimizer/backward")


@pytest.fixture(scope="module", autouse=True)
def cpu_scope():
    previous = torch.get_num_threads()
    rng = torch.get_rng_state().clone()
    torch.set_num_threads(1)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(torch.optim, "Adam", forbidden)
            patch.setattr(torch.optim.Optimizer, "__init__", forbidden)
            patch.setattr(torch.Tensor, "backward", forbidden)
            patch.setattr(torch.autograd, "backward", forbidden)
            yield
        assert torch.equal(rng, torch.get_rng_state())
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def checkpoint():
    return host.create_counted_content_head_v1(config=CONFIG)


@pytest.fixture(scope="module")
def view():
    return subject.build_counted_threshold_numerical_view_v2()


@pytest.fixture(scope="module")
def labels(view):
    codec = view["observation_codec"]
    codec_sha = codec_owner.counted_threshold_token_codec_sha256(codec)
    rows = []
    for maximum in (1, 2, 3):
        raw = wire(factory.authored_counted_threshold_request_v2(maximum))
        encoding = codec_owner.encode_counted_threshold_tokens_v2(raw,
            expected_request_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha)
        rows.append(dict(maximum=maximum, request_raw=raw, encoding=encoding,
            context_raw=encoding["context_raw_utf8"].encode()))
    return rows


def score(checkpoint, view, *, vector=None, prefix=None, **changes):
    options = dict(expected_checkpoint_sha256=digest(checkpoint), view=view, expected_view_sha256=digest(view))
    options.update(changes)
    return subject.score_counted_threshold_numerical_view_v2(checkpoint,
        VECTOR if vector is None else vector, [1] if prefix is None else prefix, **options)


def evaluate(checkpoint, view, case, *, vector=None, ids=None, context=None, **changes):
    raw = case["context_raw"] if context is None else context
    options = dict(expected_checkpoint_sha256=digest(checkpoint), expected_context_sha256=sha(raw),
                   view=view, expected_view_sha256=digest(view))
    options.update(changes)
    return subject.evaluate_counted_threshold_numerical_view_v2(checkpoint,
        VECTOR if vector is None else vector,
        case["encoding"]["target_ids"] if ids is None else ids, raw, **options)


def direct_rows(checkpoint, vector, ids):
    """Use the original host's actual strict restore and forward, not a kernel copy."""
    def work(data, loaded, original_base, modules):
        value = host._checkpoint(data, original_base, modules)
        numeric = original_base._conditioning(data["conditioning"])
        host._prefix(original_base, data["prefix_ids"])
        return host._forward(value, numeric, data["prefix_ids"], loaded, original_base)
    return host._operation(dict(checkpoint=checkpoint, conditioning=vector, prefix_ids=ids,
        expected_checkpoint_sha256=digest(checkpoint)), work, numeric=True)


def python_losses(logits, labels):
    assert len(logits) == len(labels)
    values = []
    for row, label in zip(logits, labels, strict=True):
        assert len(row) == 28 and all(type(x) is float and math.isfinite(x) for x in row)
        maximum = max(row)
        values.append(maximum + math.log(math.fsum(math.exp(x-maximum) for x in row))-row[label])
    return values


def no_authority(report):
    assert report["authority"] and all(flag is False for flag in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    for flag in ("checkpoint_rewritten", "weights_modified", "new_checkpoint_created"):
        assert report[flag] is False


@pytest.fixture(scope="module")
def recorded_evaluations(checkpoint, view, labels):
    rows = []
    actual_model, actual_forward = host._model, host._forward
    active = None
    def observed_model(*args, **kwargs):
        active["model_restore_calls"] += 1
        return actual_model(*args, **kwargs)
    def observed_forward(value, numeric, ids, loaded, original_base):
        active["gru_forward_calls"] += 1
        active["forward_input_lengths"].append(len(ids))
        return actual_forward(value, numeric, ids, loaded, original_base)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(host, "_model", observed_model)
        patch.setattr(host, "_forward", observed_forward)
        for case in labels:
            active = dict(maximum=case["maximum"], model_restore_calls=0, gru_forward_calls=0,
                forward_input_lengths=[], scope="one public consumer evaluation; independent test oracles excluded")
            report = evaluate(checkpoint, view, case)
            assert active["model_restore_calls"] == active["gru_forward_calls"] == 1
            assert active["forward_input_lengths"] == [len(case["encoding"]["target_ids"])-1]
            rows.append(dict(evaluation=report, execution_scope=active))
    return rows


@pytest.fixture(scope="module")
def observations(recorded_evaluations):
    return [row["evaluation"] for row in recorded_evaluations]


def test_view_declares_exact_identity_numeric_ids_and_one_explicit_schema_relabel(view, checkpoint):
    assert view["schema"] == "legal-counted-threshold-numerical-view/v2"
    assert view["profile"] == "seeded-counted28-three-form-vocabulary-view-384/v2"
    assert view["model_head_profile"] == checkpoint["profile"] == host.PROFILE
    assert view["model_codec_sha256"] == checkpoint["codec_sha256"]
    assert view["observation_codec_sha256"] == codec_owner.counted_threshold_token_codec_sha256(view["observation_codec"])
    assert view["observation_to_model_ids"] == list(range(28))
    assert view["numeric_id_mapping_is_identity"] is True
    assert view["exact_spelling_count"] == 27 and view["explicit_schema_relabel_count"] == 1
    rows = view["lexical_rows"]
    assert len(rows) == 28 and [row["token_id"] for row in rows] == list(range(28))
    assert [row["model_token_id"] for row in rows] == list(range(28))
    assert [row["token"] for row in rows] == view["observation_codec"]["vocabulary"]
    changed = [row for row in rows if row["token"] != row["model_token"]]
    assert changed == [dict(token_id=10, token='"legal-counted-threshold-content/v2"', model_token_id=10,
        model_token='"legal-counted-compact-content/v1"', policy="explicit_schema_role_relabel")]
    assert all(row["policy"] == "exact_spelling" for row in rows if row["token_id"] != 10)
    assert {"model_state", "optimizer_state", "checkpoint"}.isdisjoint(view)
    assert view["input_dimension"] == 384 and view["admissible_content_count"] == 3
    assert subject.counted_threshold_numerical_view_sha256(view) == digest(view)
    no_authority(view)


def test_view_metadata_build_and_hash_do_not_restore_or_forward(view, monkeypatch):
    monkeypatch.setattr(host, "_model", forbidden)
    monkeypatch.setattr(host, "_forward", forbidden)
    assert subject.build_counted_threshold_numerical_view_v2() == view
    assert subject.counted_threshold_numerical_view_sha256(view) == digest(view)


@pytest.mark.parametrize("index,prediction_rows", [(0, 116), (1, 194), (2, 292)],
    ids=["maximum_one_116_rows", "maximum_two_194_rows", "maximum_three_292_rows"])
def test_view_dense_teacher_forcing_matches_python_loss_and_original_host_rows(
        checkpoint, view, labels, observations, index, prediction_rows):
    original = wire(checkpoint)
    rng = torch.get_rng_state().clone()
    case, report = labels[index], observations[index]
    ids = case["encoding"]["target_ids"]
    assert report["target_ids"] == ids and report["input_ids"] == report["model_input_ids"] == ids[:-1]
    assert report["label_ids"] == ids[1:] and report["label_ids"][-1] == 2
    assert report["output_shape"] == [1, prediction_rows, 28]
    assert len(report["logits"]) == report["predicted_tokens"] == prediction_rows
    losses = python_losses(report["logits"], ids[1:])
    assert report["token_losses"] == pytest.approx(losses, rel=1e-12, abs=1e-12)
    assert report["mean_cross_entropy"] == pytest.approx(math.fsum(losses)/len(losses), rel=1e-12, abs=1e-12)
    predictions = [max(range(28), key=lambda item:row[item]) for row in report["logits"]]
    assert report["prediction_ids"] == predictions
    assert report["exact_teacher_forced_token_matches"] == sum(a == b for a, b in zip(predictions, ids[1:]))
    assert report["logits"] == direct_rows(checkpoint, VECTOR, ids[:-1])
    baseline = host.score_counted_content_head_v1(checkpoint, VECTOR, ids[:-1],
        expected_checkpoint_sha256=digest(checkpoint))
    assert baseline["logits"] == report["logits"][-1]
    assert report["decoded_maximum"] == case["maximum"]
    assert report["target_context_role"] == "label_validation_only_unreviewed_cap_free_signature"
    assert report["canonical_context_sha256"] == sha(case["context_raw"])
    assert report["context_raw_sha256"] == sha(case["context_raw"])
    assert report["eos_included_in_loss"] is True and report["grammar_mask_applied"] is False
    assert report["numerical_forward_executed"] is True and report["model_restore_performed"] is True
    assert report["optimizer_executed"] is False and report["generation_executed"] is False
    assert report["exposed_labels_in_this_evaluation"] == 1 and report["admissible_content_count"] == 3
    assert report["source_dependence_established"] is False
    assert report["checkpoint_profile"] == checkpoint["profile"]
    assert report["weights_sha256"] == checkpoint["weights_sha256"]
    assert report["observation_to_model_ids"] == list(range(28))
    assert torch.equal(rng, torch.get_rng_state()) and wire(checkpoint) == original
    no_authority(report)


def test_view_raw_scores_are_condition_sensitive_and_equal_original_public_host(checkpoint, view):
    before, rng = wire(checkpoint), torch.get_rng_state().clone()
    positive = score(checkpoint, view)
    negative = score(checkpoint, view, vector=[-1.]+[0.]*383)
    assert positive["logits"] != negative["logits"]
    assert positive["logits"] == host.score_counted_content_head_v1(checkpoint, VECTOR, [1],
        expected_checkpoint_sha256=digest(checkpoint))["logits"]
    assert positive["model_prefix_ids"] == positive["prefix_ids"] == [1]
    assert positive["output_shape"] == [1, 1, 28] and len(positive["logits"]) == 28
    assert positive["grammar_mask_applied"] is False and positive["grammatical_prefix_verified"] is False
    assert wire(checkpoint) == before and torch.equal(rng, torch.get_rng_state())
    no_authority(positive)


def test_view_unmasked_scoring_does_not_require_a_grammatical_prefix(checkpoint, view, labels):
    context = labels[0]["context_raw"]
    codec = view["observation_codec"]
    assert codec_owner.inspect_counted_threshold_prefix_v2([1, 3, 3], context,
        expected_context_sha256=sha(context), codec=codec,
        expected_codec_sha256=view["observation_codec_sha256"])["status"] == "rejected"
    observed = score(checkpoint, view, prefix=[1, 3, 3])
    assert observed["output_shape"] == [1, 3, 28] and len(observed["logits"]) == 28
    assert observed["grammatical_prefix_verified"] is False


def test_view_original_checkpoint_json_roundtrip_keeps_exact_scores(checkpoint, view):
    restored = json.loads(wire(checkpoint))
    assert restored == checkpoint and score(restored, view) == score(checkpoint, view)
    assert restored["schema"] == host.SCHEMA and restored["profile"] == host.PROFILE
    assert restored["optimizer_state_included"] is False and len(restored["model_state"]) == 13


def test_view_score_has_no_target_or_context_input_and_exposes_only_four_public_apis():
    assert set(inspect.signature(subject.score_counted_threshold_numerical_view_v2).parameters) == {
        "checkpoint", "conditioning", "prefix_ids", "expected_checkpoint_sha256", "view", "expected_view_sha256"}
    assert set(subject.__all__) == {"build_counted_threshold_numerical_view_v2",
        "counted_threshold_numerical_view_sha256", "score_counted_threshold_numerical_view_v2",
        "evaluate_counted_threshold_numerical_view_v2"}


@pytest.mark.parametrize("damage", ["mapping", "bool_mapping", "identity_claim", "row_policy", "row_ten", "schema", "authority"],
    ids=["mapping", "bool_mapping", "identity_claim", "row_policy", "row_ten", "schema", "authority"])
def test_view_resealed_map_or_claim_cannot_replace_rebuilt_exact_view(checkpoint, view, monkeypatch, damage):
    offered = deepcopy(view)
    if damage == "mapping": offered["observation_to_model_ids"][3:5] = [4, 3]
    elif damage == "bool_mapping": offered["observation_to_model_ids"][1] = True
    elif damage == "identity_claim": offered["numeric_id_mapping_is_identity"] = 1
    elif damage == "row_policy": offered["lexical_rows"][10]["policy"] = "exact_spelling"
    elif damage == "row_ten": offered["lexical_rows"][10]["model_token_id"] = 11
    elif damage == "schema": offered["schema"] = host.SCHEMA
    else: offered["authority"]["checkpoint_compatibility_verified"] = True
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError): subject.counted_threshold_numerical_view_sha256(offered)
    with pytest.raises(ValueError): score(checkpoint, offered)


@pytest.mark.parametrize("damage", ["profile", "codec", "missing_tensor", "integer_scalar", "optimizer", "bool_mask"],
    ids=["profile", "codec", "missing_tensor", "integer_scalar", "optimizer", "bool_mask"])
def test_view_resealed_invalid_original_checkpoint_is_refused_before_forward(checkpoint, view, monkeypatch, damage):
    value = deepcopy(checkpoint)
    if damage == "profile": value["profile"] = "validated537-to-counted28-content-head-384/v1"
    elif damage == "codec": value["codec"] = deepcopy(view["observation_codec"]); value["codec_sha256"] = digest(value["codec"])
    elif damage == "missing_tensor": del value["model_state"]["condition.bias"]
    elif damage == "integer_scalar": value["model_state"]["condition.bias"][0] = 0
    elif damage == "optimizer": value["optimizer_state_included"] = True
    else: value["training_mask"] = False
    value["weights_sha256"] = digest(value["model_state"])
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError): score(value, view)


@pytest.mark.parametrize("damage", ["empty", "bool", "eos", "oov", "budget"],
    ids=["empty", "bool", "eos", "oov", "budget"])
def test_view_invalid_nonterminal_prefix_is_refused_before_forward(checkpoint, view, monkeypatch, damage):
    ids = {"empty":[], "bool":[True], "eos":[1, 2], "oov":[1, 28], "budget":[1]+[3]*511}[damage]
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError): score(checkpoint, view, prefix=ids)


@pytest.mark.parametrize("damage", ["short", "bool", "nan", "overflow"], ids=["short", "bool", "nan", "overflow"])
def test_view_invalid_conditioning_is_refused_before_forward(checkpoint, view, monkeypatch, damage):
    vector = [0.]*383 if damage == "short" else [True if damage == "bool" else float("nan") if damage == "nan" else 1e100]+[0.]*383
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError): score(checkpoint, view, vector=vector)


@pytest.mark.parametrize("damage", ["truncated", "bool", "other_form", "context", "context_pin"],
    ids=["truncated", "bool", "other_form", "context", "context_pin"])
def test_view_complete_labels_and_context_must_pass_genuine_decoder_before_forward(checkpoint, view, labels, monkeypatch, damage):
    case = labels[1]
    ids, context, changes = list(case["encoding"]["target_ids"]), case["context_raw"], {}
    if damage == "truncated": ids.pop()
    elif damage == "bool": ids[0] = True
    elif damage == "other_form": ids[1] = 3
    elif damage == "context": context = b"{}"
    else: changes["expected_context_sha256"] = "0"*64
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError): evaluate(checkpoint, view, case, ids=ids, context=context, **changes)


@pytest.mark.parametrize("pin", ["view", "checkpoint", "context"], ids=["view_pin", "checkpoint_pin", "context_pin"])
def test_view_independent_hashes_are_required_before_forward(checkpoint, view, labels, monkeypatch, pin):
    monkeypatch.setattr(host, "_forward", forbidden)
    if pin == "context":
        with pytest.raises(ValueError): evaluate(checkpoint, view, labels[0], expected_context_sha256="0"*64)
    else:
        field = "expected_view_sha256" if pin == "view" else "expected_checkpoint_sha256"
        with pytest.raises(ValueError): score(checkpoint, view, **{field:"0"*64})


@pytest.mark.parametrize("operation", ["score", "evaluate"], ids=["prefix_capture", "target_capture"])
def test_view_captured_boolean_ids_are_refused_before_forward(checkpoint, view, labels, monkeypatch, operation):
    offered = [1] if operation == "score" else list(labels[0]["encoding"]["target_ids"])
    actual, changed = base._copy, []
    field = "prefix_ids" if operation == "score" else "target_ids"
    def before_capture(value, *args, **kwargs):
        if type(value) is dict and value.get(field) is offered and not changed:
            changed.append(True); offered[0] = True
        return actual(value, *args, **kwargs)
    monkeypatch.setattr(base, "_copy", before_capture)
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError):
        if operation == "score": score(checkpoint, view, prefix=offered)
        else: evaluate(checkpoint, view, labels[0], ids=offered)
    assert changed and offered[0] is True


@pytest.mark.parametrize("damage", ["caller", "source"], ids=["late_caller_change", "late_source_change"])
def test_view_pre_forward_fence_refuses_late_caller_or_source_change(checkpoint, view, monkeypatch, damage):
    vector = list(VECTOR)
    actual, changed = host._checkpoint, []
    def mutation(*args, **kwargs):
        value = actual(*args, **kwargs)
        changed.append(True)
        if damage == "caller": vector[0] = -1.
        else: monkeypatch.setattr(subject, "_SELF_SHA", "0"*64)
        return value
    monkeypatch.setattr(host, "_checkpoint", mutation)
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError): score(checkpoint, view, vector=vector)
    assert changed


@pytest.mark.parametrize("field", ["_SELF_SHA", "_HOST_SHA"], ids=["consumer_source", "original_host_source"])
def test_view_metadata_refuses_changed_source_generation(view, monkeypatch, field):
    monkeypatch.setattr(subject, field, "0"*64)
    monkeypatch.setattr(host, "_forward", forbidden)
    with pytest.raises(ValueError): subject.counted_threshold_numerical_view_sha256(view)


def test_view_panel_retains_unchanged_host_and_complete_unmasked_observations(
        checkpoint, view, labels, observations, recorded_evaluations, tmp_path):
    original, rng = wire(checkpoint), torch.get_rng_state().clone()
    cases = []
    for case, report, recorded in zip(labels, observations, recorded_evaluations, strict=True):
        ids = case["encoding"]["target_ids"]
        direct = direct_rows(checkpoint, VECTOR, ids[:-1])
        losses = python_losses(report["logits"], ids[1:])
        assert direct == report["logits"]
        assert report["token_losses"] == pytest.approx(losses, rel=1e-12, abs=1e-12)
        no_authority(report)
        cases.append(dict(maximum=case["maximum"], request=json.loads(case["request_raw"]),
            request_raw_utf8=case["request_raw"].decode(), request_sha256=sha(case["request_raw"]),
            encoding=case["encoding"], target_ids=ids, context_raw_utf8=case["context_raw"].decode(),
            context_sha256=sha(case["context_raw"]), evaluation=report,
            evaluation_execution_scope=recorded["execution_scope"],
            reference=dict(direct_host_all_rows_sha256=digest(direct), exact_rows_equal=True,
                python_token_losses_sha256=digest(losses), python_mean_cross_entropy=math.fsum(losses)/len(losses),
                eos_label_included=True)))
    last_ids = labels[2]["encoding"]["target_ids"][:-1]
    direct_baseline = host.score_counted_content_head_v1(checkpoint, VECTOR, last_ids,
        expected_checkpoint_sha256=digest(checkpoint))
    assert direct_baseline["logits"] == observations[2]["logits"][-1]
    positive_score = score(checkpoint, view)
    negative_score = score(checkpoint, view, vector=[-1.]+[0.]*383)
    assert positive_score["logits"] != negative_score["logits"]
    assert wire(checkpoint) == original and torch.equal(rng, torch.get_rng_state())
    panel = dict(schema="legal-authored-counted-threshold-numerical-view-panel/v2",
        checkpoint=checkpoint, checkpoint_sha256=digest(checkpoint), view=view, view_sha256=digest(view),
        conditioning=VECTOR, cases=cases, direct_baseline_score=direct_baseline,
        conditioning_score_controls=dict(positive=positive_score, negative=negative_score),
        source_truths=dict(original_seeded_host_profile_preserved=True, unchanged_tensor_count=13,
            checkpoint_unchanged=True, cpu_rng_unchanged=True, exact_spelling_count=27,
            explicit_schema_relabel_count=1, relabeled_row_id=10, numeric_ids_identity=True,
            nonidentity_permutation_observed=False, optimizer_constructed=False,
            optimizer_steps=0, new_checkpoint_created_by_consumer=False, weights_modified=False,
            donor_transfer_performed=False, grammar_mask_applied=False, generation_executed=False),
        model_forward_observed=True, training_executed=False, native_build_executed=False,
        source_dependence_established=False, training_mask=0, evaluation_gold_mask=0,
        authority={key:False for key in observations[0]["authority"]})
    payload = wire(panel)
    assert len(payload) < 4*1024**2
    path = tmp_path/"authored-threshold-numerical-view-panel-v2.json"
    path.write_bytes(payload)
    assert path.read_bytes() == payload
