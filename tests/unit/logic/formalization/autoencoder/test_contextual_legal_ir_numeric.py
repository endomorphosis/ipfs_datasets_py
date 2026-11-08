"""Synthetic restoration/source-only boundaries, without retained asset files."""
from copy import deepcopy
import hashlib
import json

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_numeric as subject


@pytest.fixture(autouse=True)
def one_cpu():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture
def packet():
    core, persistent, native, projected, clauses, action, ordered, contexts = subject._owners()
    dimension = 384
    strings = ("actor", "action", "modality", "object", "conditions", "exceptions",
               "temporal", "rules", "O", "P", "F", "agency", "save", "report")
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"]
        + sorted({json.dumps(value) for value in strings} | set("{}[],:")))
    config = dict(seed=1729, hidden_size=8, token_embedding_dim=16, projection_width=2)
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(config["seed"])
        fixture = torch.nn.Module()
        fixture.projection_down = torch.nn.Linear(384, 2)
        fixture.projection_up = torch.nn.Linear(2, 384)
        fixture.condition = torch.nn.Linear(384, 8)
        fixture.target_embedding = torch.nn.Embedding(len(codec["target_vocabulary"]), 16, padding_idx=0)
        fixture.decoder = torch.nn.GRU(16, 8, batch_first=True)
        fixture.output = torch.nn.Linear(8, len(codec["target_vocabulary"]))
        donor = dict(codec=codec, config=config,
                     model_state={name: value.tolist() for name, value in fixture.state_dict().items()})
        raw = subject._raw_donor(torch, donor)
        body, initializer = native.bind_dimension_native_body(raw, dimension=dimension)
        feature_rows = [dict(id=f"train-{i}", source_sha256=hashlib.sha256(str(i).encode()).hexdigest(),
            features=[float(index == i) for index in range(dimension)]) for i in range(4)]
        keywords = dict(expected_training_ids=[row["id"] for row in feature_rows],
            forbidden_validation_ids=["validation"], training_rows_sha256="a" * 64)
        normalization = projected.fit_source_normalization(feature_rows, kind="center_rms", **keywords)
        count_rows = [{key: row[key] for key in ("id", "source_sha256")} | dict(count=i+1)
                      for i, row in enumerate(feature_rows)]
        prior = projected.fit_source_count_prior(count_rows, **keywords)
        clause_features = [{**row, "id": "clause:" + row["source_sha256"]} for row in feature_rows]
        clause_normalization = projected.fit_source_normalization(clause_features,
            kind="center_rms", expected_training_ids=[row["id"] for row in clause_features],
            forbidden_validation_ids=["clause:" + "c" * 64], training_rows_sha256="a" * 64)
        clause_normalization["training_contexts_sha256"] = "b" * 64
        clause_normalization["receipt_sha256"] = core.digest({k: v for k, v in clause_normalization.items()
                                                              if k != "receipt_sha256"})
        transform = dict(mode="center_rms", mean=[.1] * dimension, scale=2., origin="training_only")
        preprocessing = dict(initializer=initializer, input_transform=transform,
            paragraph_normalization=normalization, clause_normalization=clause_normalization,
            count_prior=prior)
        model = persistent.bind_persistent_model(body, dimension=dimension)
        model = projected.bind_projected_source_model(model, codec=codec,
            normalization_receipt=normalization, count_prior_receipt=prior,
            guide_boundary=True, scalar_guidance=True)
        model = clauses.bind_clause_source_model(model, head_seed=1729,
                                                 clause_normalization_receipt=clause_normalization)
        model = action.bind_action_factorized_clause_model(model, codec=codec)
        model = ordered.bind_ordered_clause_recurrent_model(model, codec=codec)
        architecture = model.describe()
        with torch.no_grad():
            model.body.body.body.output.weight.zero_()
            model.body.body.body.output.bias.zero_()
            model.body.body.body.output.bias[2] = 100.
        serialized = {name: value.tolist() for name, value in model.state_dict().items()}
        checkpoint = dict(schema="private-native-dimension-source-state/v1", dimension=dimension,
            selected=True, role="selected", codec=codec, input_transform=transform,
            initializer_receipt=initializer, architecture=architecture, model_state=serialized,
            weights_sha256=core.digest(serialized), tensor_sha256=core.tensor_digest(model),
            qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False)
    rows = [dict(id="source-1", source_text="agency saves report", input=[1.] + [0.] * 383)]
    context = contexts.build_source_contexts(
        [dict(id=rows[0]["id"], source_text=rows[0]["source_text"])], rows)
    return dict(checkpoint=checkpoint, preprocessing=preprocessing, donor_checkpoint=donor), {
        "rows": rows, "contexts": context}


def test_complete_restore_generation_preserves_rng_weights_and_inputs_without_fit_or_optimizer(packet, monkeypatch):
    prepared, inputs = packet
    saved = deepcopy((prepared, inputs))
    owners = subject._owners()

    def forbidden(*args, **kwargs):
        raise AssertionError("training/fitting path invoked")

    monkeypatch.setattr(owners[3], "fit_source_normalization", forbidden)
    monkeypatch.setattr(owners[3], "fit_source_count_prior", forbidden)
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(torch.optim, "AdamW", forbidden)
    rng = torch.get_rng_state().clone()
    restored = subject.restore_contextual_legal_model(prepared)
    assert torch.equal(rng, torch.get_rng_state())
    report = subject.infer_contextual_legal_model(restored, inputs)
    assert report["predictions"] == [dict(id="source-1", token_ids=[], eos_reached=True,
                                          generation_status="eos")]
    assert report["completed"] and report["ambient_rng_preserved"] and report["weights_unchanged"]
    assert all(report[key] is False for key in subject._FALSE)
    assert (prepared, inputs) == saved
    assert report["model_tensor_sha256_before"] == report["model_tensor_sha256_after"]
    assert torch.equal(rng, torch.get_rng_state())


def test_nested_projection_preflight_refuses_mutation_even_with_updated_serialized_digest(packet):
    prepared, _ = packet
    core = subject._owners()[0]
    prepared["checkpoint"]["model_state"]["body.body.body.projection_up.bias"][0] = .25
    prepared["checkpoint"]["weights_sha256"] = core.digest(prepared["checkpoint"]["model_state"])
    rng = torch.get_rng_state().clone()
    with pytest.raises(ValueError, match="frozen native projection differs"):
        subject.restore_contextual_legal_model(prepared)
    assert torch.equal(rng, torch.get_rng_state())


def test_restoration_uses_explicit_cpu_float32_without_changing_caller_default_dtype(packet):
    prepared, inputs = packet
    before = torch.get_default_dtype()
    try:
        torch.set_default_dtype(torch.float64)
        restored = subject.restore_contextual_legal_model(prepared)
        assert all(value.device.type == "cpu" and
                   (not value.is_floating_point() or value.dtype == torch.float32)
                   for value in restored.model.state_dict().values())
        subject.infer_contextual_legal_model(restored, inputs)
        assert torch.get_default_dtype() == torch.float64
    finally:
        torch.set_default_dtype(before)


@pytest.mark.parametrize("mutation", ["missing", "boolean_seed", "wrong_seed", "donor"])
def test_strict_state_donor_and_integer_scalar_restore(packet, mutation):
    prepared, _ = packet
    core = subject._owners()[0]
    if mutation == "missing":
        prepared["checkpoint"]["model_state"].pop("ordered_clause_recurrent_version")
    elif mutation == "boolean_seed":
        prepared["checkpoint"]["model_state"]["head_initialization_seed"] = True
    elif mutation == "wrong_seed":
        prepared["checkpoint"]["model_state"]["head_initialization_seed"] = 1728
    else:
        prepared["donor_checkpoint"]["model_state"]["output.bias"][0] += .1
    prepared["checkpoint"]["weights_sha256"] = core.digest(prepared["checkpoint"]["model_state"])
    with pytest.raises(ValueError):
        subject.restore_contextual_legal_model(prepared)


@pytest.mark.parametrize("mutation", ["target", "reference", "extra_context", "mixed_width", "bad_offset"])
def test_closed_source_only_input_refuses_targets_and_broken_cache_binding(packet, mutation):
    prepared, inputs = packet
    restored = subject.restore_contextual_legal_model(prepared)
    if mutation == "target":
        inputs["rows"][0]["target_ids"] = [1, 2]
    elif mutation == "reference":
        inputs["reference"] = {"rules": []}
    elif mutation == "extra_context":
        inputs["contexts"]["extra"] = deepcopy(inputs["contexts"]["source-1"])
    elif mutation == "mixed_width":
        inputs["rows"][0]["input"].append(0.)
    else:
        inputs["contexts"]["source-1"]["segments"][0]["char_end"] += 1
    with pytest.raises(ValueError):
        subject.infer_contextual_legal_model(restored, inputs)


def test_transform_real_clauses_before_zero_padding_and_internal_feature_normalization(packet, monkeypatch):
    prepared, inputs = packet
    restored = subject.restore_contextual_legal_model(prepared)
    core = subject._owners()[0]
    original = core._greedy

    def observe(torch_arg, model, data, *args, source_context, **kwargs):
        expected = (torch.tensor(inputs["rows"][0]["input"]) - .1) / 2.
        assert torch.equal(data[0], expected)
        assert torch.equal(source_context["vectors"][0, 0], expected)
        assert not bool(source_context["vectors"][0, 1:].any())
        assert source_context["mask"].dtype == torch.bool
        assert source_context["mask"].tolist() == [[True] + [False] * 7]
        return original(torch_arg, model, data, *args, source_context=source_context, **kwargs)

    monkeypatch.setattr(core, "_greedy", observe)
    subject.infer_contextual_legal_model(restored, inputs)


def test_deadline_reports_raw_unfinished_rows_and_mutated_model_refused(packet, monkeypatch):
    prepared, inputs = packet
    restored = subject.restore_contextual_legal_model(prepared)
    ticks = iter([0., 1., 2.])
    monkeypatch.setattr(subject.time, "monotonic", lambda: next(ticks))
    report = subject.infer_contextual_legal_model(restored, inputs, deadline_seconds=.01)
    assert report["predictions"][0]["generation_status"] == "deadline"
    assert not report["completed"] and not report["predictions"][0]["eos_reached"]
    with torch.no_grad():
        restored.model.action_head.field_readout.bias[0] += 1.
    with pytest.raises(ValueError, match="model changed before inference"):
        subject.infer_contextual_legal_model(restored, inputs)


# Focused additive sensitivity controls. Historical restore/generation tests above
# remain intact and are not selected for this qualification.
def _sensitivity_test_packet(clause_counts=(1,)):
    _, _, _, _, _, _, _, contexts_owner = subject._owners()
    rows, contexts = [], {}
    for index,count in enumerate(clause_counts):
        identifier = 'sensitivity-row-'+str(index)
        text = '\n\n'.join('row '+str(index)+' clause '+str(slot) for slot in range(count))
        vector = [1.]+[0.]*383
        clauses = [[float(coordinate == (slot+2)%384) for coordinate in range(384)] for slot in range(count)]
        rows.append(dict(id=identifier,source_text=text,input=vector))
        contexts[identifier] = contexts_owner._descriptor(text,clauses)
    return dict(rows=rows,contexts=contexts)


def _sensitivity_test_reseal(prepared, model):
    result = deepcopy(prepared);core = subject._owners()[0]
    state = {name:value.detach().tolist() for name,value in model.state_dict().items()}
    result['checkpoint']['model_state'] = state
    result['checkpoint']['weights_sha256'] = core.digest(state)
    result['checkpoint']['tensor_sha256'] = core.tensor_digest(model)
    return result,subject.restore_contextual_legal_model(result)


@pytest.fixture
def sensitivity_case(packet):
    prepared,_ = packet
    handle = subject.restore_contextual_legal_model(prepared)
    # A declared synthetic fitted state with a strong analytic paragraph signal.
    # No optimizer, backward pass or retained asset is used.
    raw = handle.model.body.body.body
    with torch.no_grad():
        raw.condition.weight.zero_();raw.condition.bias.zero_();raw.condition.weight[0,0] = 1.
        for parameter in raw.decoder.parameters():parameter.zero_()
        # Preserve a live recurrent input channel: initial BOS routes real clause0,
        # so a first-clause change can affect its one-step logit point.
        raw.decoder.weight_ih_l0[2*raw.decoder.hidden_size,0] = 1.
        raw.target_embedding.weight.zero_();handle.model.body.body.source_to_embedding.weight.zero_()
        raw.output.weight.zero_();raw.output.bias.zero_()
        raw.output.weight[0,0] = 1.;raw.output.weight[1,0] = -1.
        handle.model.body.count_head.weight.zero_();handle.model.body.count_head.weight[0,0] = 1.
        for head in (handle.model.non_action_head,handle.model.action_head):
            head.field_readout.weight.zero_();head.field_readout.bias.zero_()
            for index in range(min(head.field_readout.weight.shape)):head.field_readout.weight[index,index] = 1.
        handle.model.clause_to_embedding.weight.zero_();handle.model.clause_to_embedding.weight[0,0] = 1.
    prepared,handle = _sensitivity_test_reseal(prepared,handle.model)
    return prepared,handle,_sensitivity_test_packet()


def _sensitivity_test_rows(report,stage):
    return [row for part in report['stage_comparisons'][stage]['drift_reports'] for row in part['rows']]


def _sensitivity_test_changed_clause(packet,slot=0):
    result = deepcopy(packet);core = subject._owners()[0]
    segment = result['contexts'][result['rows'][0]['id']]['segments'][slot]
    segment['vector'] = [float(index == 31) for index in range(384)]
    segment['embedding_sha256'] = core.digest(segment['vector'])
    return result


def test_source_sensitivity_identical_arms_and_no_generation_or_fit(sensitivity_case,monkeypatch):
    _,handle,inputs = sensitivity_case;owners = subject._owners()
    def forbidden(*args,**kwargs):raise AssertionError('generation/fitting/optimizer called')
    monkeypatch.setattr(owners[0],'_greedy',forbidden)
    monkeypatch.setattr(owners[3],'fit_source_normalization',forbidden)
    monkeypatch.setattr(owners[3],'fit_source_count_prior',forbidden)
    monkeypatch.setattr(torch.optim,'Adam',forbidden);monkeypatch.setattr(torch.optim,'AdamW',forbidden)
    saved = deepcopy(inputs);rng = torch.get_rng_state().clone()
    report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))
    assert 'compare_contextual_source_sensitivity_v1' in subject.__all__
    assert len(report['stage_comparisons']) == 11
    for stage in report['stage_comparisons'].values():
        assert sum(part['counts']['exact_bitwise_rows'] for part in stage['drift_reports']) == stage['observations']
    assert report['model_inference_executed'] is report['fixed_BOS_forward_executed'] is True
    assert report['generation_executed'] is False and report['acceptance_tolerance'] is None
    assert all(report[key] is False for key in subject._FALSE)
    assert report['physical_role_uses'] == 2 and report['padded_clause_cells'] == 7
    assert report['run_counts']['fixed_BOS_next_logits_calls'] == 2
    assert all(row['updated_position'] == 1 and row['updated_grammar'] == [1,0,0,0,0,0] for row in report['padding_audit'])
    assert report['weights_unchanged'] and report['source_inputs_unchanged'] and report['ambient_rng_preserved']
    assert inputs == saved and torch.equal(rng,torch.get_rng_state())


def test_source_sensitivity_nontrivial_paragraph_response(sensitivity_case):
    _,handle,inputs = sensitivity_case;new = deepcopy(inputs)
    new['rows'][0]['input'] = [0.,1.]+[0.]*382
    report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,new)
    row = _sensitivity_test_rows(report,'BOS.raw_logits')[0]
    assert row['max_absolute_error'] > .1
    assert report['BOS_points']['argmax_agree_rows'] == 0
    assert len(report['BOS_points']['stable_centered_deltas']) == 1


def test_source_sensitivity_clause0_changes_state_and_BOS(sensitivity_case):
    _,handle,inputs = sensitivity_case;new = _sensitivity_test_changed_clause(inputs)
    report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,new)
    assert not _sensitivity_test_rows(report,'BOS.raw_logits')[0]['bitwise_equal']
    assert not _sensitivity_test_rows(report,'initial_state.recurrent_clause_features.real_clause')[0]['bitwise_equal']
    assert not _sensitivity_test_rows(report,'initial_state.scalar_logits.real_clause')[0]['bitwise_equal']
    assert 'real clause0' in report['BOS_points']['clause_route']


def test_source_sensitivity_slot7_is_real_and_slot8_is_not(sensitivity_case):
    _,handle,_ = sensitivity_case;inputs = _sensitivity_test_packet((8,));new = _sensitivity_test_changed_clause(inputs,7)
    report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,new)
    assert report['real_clause_roles'] == 8 and report['padded_clause_cells'] == 0
    assert [row['slot'] for row in report['identity_map']['clause']] == list(range(8))
    changed = [row for row in _sensitivity_test_rows(report,'clause_feature_normalization.real_clause') if not row['bitwise_equal']]
    assert len(changed) == 1 and changed[0]['id'].endswith(':clause:7')
    assert not _sensitivity_test_rows(report,'initial_state.recurrent_clause_features.real_clause')[-1]['bitwise_equal']
    assert _sensitivity_test_rows(report,'BOS.raw_logits')[0]['bitwise_equal']
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,_sensitivity_test_packet((9,)),_sensitivity_test_packet((9,)))


def test_source_sensitivity_mixed_masks_keep_padding_out_of_metrics(sensitivity_case):
    _,handle,_ = sensitivity_case;inputs = _sensitivity_test_packet((1,8))
    report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))
    assert report['real_clause_roles'] == 9 and report['physical_role_uses'] == 11 and report['padded_clause_cells'] == 7
    assert report['padding_audit'][0]['mask'] == [True]+[False]*7
    assert report['padding_audit'][1]['mask'] == [True]*8
    assert report['stage_comparisons']['clause_feature_normalization.real_clause']['observations'] == 9
    assert report['padding_counted_as_metric_observations'] is False
    assert any(item['any_nonzero'] for item in report['padding_audit'][0]['normalized_padding'])
    assert all(row['scalar_and_recurrent_padding_zero'] for row in report['padding_audit'])


def test_source_sensitivity_explicit_float32_under_ambient_float64(sensitivity_case):
    _,handle,inputs = sensitivity_case;before = torch.get_default_dtype();precision = torch.get_float32_matmul_precision()
    try:
        torch.set_default_dtype(torch.float64)
        report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))
        assert report['model_math_dtype'] == 'torch.float32' and report['caller_default_dtype'] == 'torch.float64'
        assert report['float32_matmul_precision'] == 'highest' and not report['CPU_autocast_enabled']
        assert all(row['bitwise_equal'] for stage in report['stage_comparisons'] for row in _sensitivity_test_rows(report,stage))
        with torch.autocast('cpu',dtype=torch.bfloat16):
            with pytest.raises(ValueError,match='autocast'):subject.compare_contextual_source_sensitivity_v1(handle,inputs,inputs)
            assert torch.is_autocast_enabled('cpu')
        torch.set_float32_matmul_precision('high')
        with pytest.raises(ValueError,match='highest'):subject.compare_contextual_source_sensitivity_v1(handle,inputs,inputs)
        assert torch.get_float32_matmul_precision() == 'high' and torch.get_default_dtype() == torch.float64
    finally:
        torch.set_default_dtype(before);torch.set_float32_matmul_precision(precision)


def test_source_sensitivity_native_batch_bound_preserves_every_row(sensitivity_case):
    _,handle,_ = sensitivity_case;inputs = _sensitivity_test_packet((8,)*17)
    report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs),batch_size=16)
    assert report['row_count'] == 17 and report['real_clause_roles'] == 136
    assert report['run_counts']['paired_batches'] == 2 and report['run_counts']['fixed_BOS_next_logits_calls'] == 4
    assert report['stage_comparisons']['clause_feature_normalization.real_clause']['observations'] == 136
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,inputs,batch_size=17)


def test_source_sensitivity_zero_margin_ties_are_descriptive(sensitivity_case):
    prepared,handle,inputs = sensitivity_case
    with torch.no_grad():handle.model.body.body.body.output.weight.zero_();handle.model.body.body.body.output.bias.zero_()
    _,handle = _sensitivity_test_reseal(prepared,handle.model)
    report = subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))
    for arm in ('original','successor'):
        row = report['BOS_points'][arm][0]
        assert row['top1_token_id'] == 0 and row['top2_token_id'] == 1 and row['top1_top2_margin'] == 0. and row['tie_at_top']
    assert report['acceptance_tolerance'] is None and not report['conditioning_or_head_compatibility_qualified']


def test_source_sensitivity_closed_fields_and_reordered_pair_refuse(sensitivity_case):
    _,handle,inputs = sensitivity_case;bad = deepcopy(inputs);bad['rows'][0]['target'] = []
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,bad)
    original = _sensitivity_test_packet((1,1));new = deepcopy(original);new['rows'].reverse()
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,original,new)


def test_source_sensitivity_source_metadata_and_vector_digest_refuse(sensitivity_case):
    _,handle,inputs = sensitivity_case
    for field in ('char_end','embedding_sha256'):
        bad = deepcopy(inputs);segment = bad['contexts'][bad['rows'][0]['id']]['segments'][0]
        segment[field] = 999 if field == 'char_end' else '0'*64
        with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,bad)


def test_source_sensitivity_nonbinary32_nonfinite_and_integer_refuse(sensitivity_case):
    _,handle,inputs = sensitivity_case
    for value in (1.+2.**-40,float('inf'),1):
        bad = deepcopy(inputs);bad['rows'][0]['input'][0] = value
        with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,bad)


def test_source_sensitivity_requires_eval_and_no_gradients(sensitivity_case):
    _,handle,inputs = sensitivity_case;handle.model.train()
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,inputs)
    handle.model.eval();parameter = next(handle.model.parameters());parameter.grad = torch.zeros_like(parameter)
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,inputs)


def test_source_sensitivity_model_mutation_during_forward_refuses(sensitivity_case,monkeypatch):
    _,handle,inputs = sensitivity_case;actual = handle.model.next_logits
    def mutate(tokens,state):
        value = actual(tokens,state)
        with torch.no_grad():next(handle.model.parameters()).add_(.125)
        return value
    monkeypatch.setattr(handle.model,'next_logits',mutate)
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))


def test_source_sensitivity_rng_mutation_during_forward_refuses(sensitivity_case,monkeypatch):
    _,handle,inputs = sensitivity_case;actual = handle.model.next_logits
    def mutate(tokens,state):
        value = actual(tokens,state);torch.rand(1);return value
    monkeypatch.setattr(handle.model,'next_logits',mutate)
    with torch.random.fork_rng(devices=[]),pytest.raises(ValueError):
        subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))


def test_source_sensitivity_input_mutation_during_forward_refuses(sensitivity_case,monkeypatch):
    _,handle,inputs = sensitivity_case;actual = handle.model.next_logits
    def mutate(tokens,state):
        value = actual(tokens,state);inputs['rows'][0]['source_text'] += ' changed';return value
    monkeypatch.setattr(handle.model,'next_logits',mutate)
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))


def test_source_sensitivity_nonfinite_head_return_refuses(sensitivity_case,monkeypatch):
    _,handle,inputs = sensitivity_case;actual = handle.model.next_logits
    def nonfinite(tokens,state):
        logits,updated = actual(tokens,state);logits = logits.clone();logits[0,0,0] = float('nan');return logits,updated
    monkeypatch.setattr(handle.model,'next_logits',nonfinite)
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))


def test_source_sensitivity_initial_Long_and_float_state_mutation_refuse(sensitivity_case,monkeypatch):
    _,handle,inputs = sensitivity_case;actual = handle.model.next_logits
    for index in (2,0):
        def mutate(tokens,state,index=index):
            value = actual(tokens,state);state[index].add_(1);return value
        monkeypatch.setattr(handle.model,'next_logits',mutate)
        with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,deepcopy(inputs))


def test_source_sensitivity_validator_mutation_cannot_be_adopted(sensitivity_case,monkeypatch):
    _,handle,inputs = sensitivity_case;new = deepcopy(inputs);contexts_owner = subject._owners()[-1]
    actual = contexts_owner.validate_context
    def mutate(row,descriptor):
        value = actual(row,descriptor)
        for packet in (inputs,new):packet['rows'][0]['input'] = [0.,1.]+[0.]*382
        return value
    monkeypatch.setattr(contexts_owner,'validate_context',mutate)
    with pytest.raises(ValueError):subject.compare_contextual_source_sensitivity_v1(handle,inputs,new)


def test_source_sensitivity_stable_centered_delta_ignores_constant_shift():
    before = [100000.,100001.,100002.,100003.]
    result = subject._sensitivity_centered_logit_delta(before,[value+7. for value in before])
    assert result['mean_delta'] == 7.
    assert result['centered_max_absolute'] == result['centered_l2'] == result['centered_rms'] == 0.


def test_source_sensitivity_stable_centered_delta_retains_tiny_perturbation():
    epsilon = 2.**-23
    result = subject._sensitivity_centered_logit_delta([1.]*4,[1.+epsilon,1.,1.,1.])
    assert result['mean_delta'] == epsilon/4 and result['centered_max_absolute'] == 3*epsilon/4
    assert result['centered_l2'] == pytest.approx(3.**.5*epsilon/2,rel=1e-12)
    assert result['centered_rms'] == pytest.approx(3.**.5*epsilon/4,rel=1e-12)
    assert result['acceptance_tolerance'] is None



def test_source_sensitivity_repeated_clause_occurrences_keep_distinct_vectors(sensitivity_case):
    _,handle,_ = sensitivity_case;contexts_owner = subject._owners()[-1];core = subject._owners()[0]
    texts = ('shared clause\n\nshared clause','other clause\n\nshared clause')
    rows,contexts = [],{}
    for index,text in enumerate(texts):
        identifier = 'repeated-source-'+str(index)
        rows.append(dict(id=identifier,source_text=text,input=[1.]+[0.]*383))
        vectors = [[float(coordinate == 2+2*index+slot) for coordinate in range(384)] for slot in range(2)]
        contexts[identifier] = contexts_owner._descriptor(text,vectors)
    original = dict(rows=rows,contexts=contexts)
    # Its old training-cache contract deliberately rejects one text with several
    # vectors. The new diagnostic binds those records to physical row/slot uses.
    with pytest.raises(ValueError):contexts_owner.validate_contexts(rows,contexts)
    identical = subject.compare_contextual_source_sensitivity_v1(handle,original,deepcopy(original))
    receipt = identical['context_receipts']['original'];inventory = receipt['clause_occurrence_inventory']
    assert receipt['global_text_to_single_cached_vector_asserted'] is False
    assert receipt['per_row_validator_returns'] == [384,384]
    assert len(inventory) == len({(entry['id'],entry['slot']) for entry in inventory}) == 4
    shared_sha = hashlib.sha256(b'shared clause').hexdigest()
    shared = [entry for entry in inventory if entry['source_sha256'] == shared_sha]
    assert len(shared) == len({entry['embedding_sha256'] for entry in shared}) == 3
    assert all(row['bitwise_equal'] for row in _sensitivity_test_rows(identical,'clause_feature_normalization.real_clause'))
    successor = deepcopy(original);segment = successor['contexts']['repeated-source-1']['segments'][1]
    segment['vector'] = [float(coordinate == 31) for coordinate in range(384)]
    segment['embedding_sha256'] = core.digest(segment['vector'])
    report = subject.compare_contextual_source_sensitivity_v1(handle,original,successor)
    changed = [row for row in _sensitivity_test_rows(report,'clause_feature_normalization.real_clause') if not row['bitwise_equal']]
    expected = [entry['id'] for entry in report['identity_map']['clause'] if entry['source_row_id'] == 'repeated-source-1' and entry['slot'] == 1]
    assert [row['id'] for row in changed] == expected and len(changed) == 1
    assert report['real_clause_roles'] == 4 and report['physical_role_uses'] == 6
    assert all(row['bitwise_equal'] for row in _sensitivity_test_rows(report,'BOS.raw_logits'))


# Versioned occurrence-inference controls. The complete historical test prefix,
# including the separately qualified21-case sensitivity cohort, is unchanged.
def test_occurrence_inference_genuine_legacy_parity_and_no_training(packet,monkeypatch):
    prepared,inputs = packet;core,_,_,projected,*_ = subject._owners()
    def forbidden(*args,**kwargs):raise AssertionError('fitting or optimizer path invoked')
    monkeypatch.setattr(projected,'fit_source_normalization',forbidden)
    monkeypatch.setattr(projected,'fit_source_count_prior',forbidden)
    monkeypatch.setattr(torch.optim,'Adam',forbidden);monkeypatch.setattr(torch.optim,'AdamW',forbidden)
    handle = subject.restore_contextual_legal_model(prepared);saved = deepcopy(inputs)
    legacy = subject.infer_contextual_legal_model(handle,inputs)
    actual = subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)
    assert 'infer_contextual_legal_model_occurrences_v1' in subject.__all__
    assert actual['predictions'] == legacy['predictions'] == [dict(id='source-1',token_ids=[],eos_reached=True,generation_status='eos')]
    for key in ('model_tensor_sha256','source_inputs_sha256','source_contexts_sha256','row_count','codec_sha256'):
        assert actual[key] == legacy[key]
    assert actual['schema'] == 'contextual-legal-ir-occurrence-inference/v1' and 'completed' not in actual
    assert actual['execution_completed'] and actual['eos_completed']
    assert actual['decoded_IR_valid'] is actual['task_satisfied'] is None
    assert actual['greedy_calls_started'] == actual['greedy_calls_returned'] == 1
    assert actual['model_inference_executed'] and actual['greedy_generation_executed']
    assert not actual['legacy_inference_and_training_contracts_changed']
    assert all(actual[key] is False for key in subject._FALSE) and inputs == saved


def test_occurrence_inference_repeated_paragraphs_and_clauses_preserve_uses(packet):
    prepared,_ = packet;handle = subject.restore_contextual_legal_model(prepared)
    contexts_owner = subject._owners()[-1]
    rows = [dict(id='physical-'+str(index),source_text='shared α\n\nshared α',input=[float(j == index) for j in range(384)]) for index in range(2)]
    contexts = {row['id']:contexts_owner._descriptor(row['source_text'],
        [[float(j == 2+2*index+slot) for j in range(384)] for slot in range(2)]) for index,row in enumerate(rows)}
    inputs = dict(rows=rows,contexts=contexts)
    with pytest.raises(ValueError,match='duplicate normalized paragraph'):
        subject.infer_contextual_legal_model(handle,inputs)
    actual = subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)
    receipt = actual['context_receipt'];clauses = receipt['clause_occurrence_inventory']
    assert [row['id'] for row in actual['predictions']] == [row['id'] for row in rows]
    assert receipt['schema'] == 'contextual-source-inference-occurrences/v1'
    assert receipt['per_row_validator_returns'] == [384,384]
    assert len(receipt['paragraph_occurrence_inventory']) == 2 and len(clauses) == 4
    assert [(row['id'],row['row_index'],row['slot']) for row in clauses] == [('physical-0',0,0),('physical-0',0,1),('physical-1',1,0),('physical-1',1,1)]
    assert len({row['embedding_sha256'] for row in clauses}) == 4
    assert clauses[0]['byte_end'] > clauses[0]['char_end']
    assert receipt['paragraph_text_uniqueness_asserted'] is receipt['global_text_to_single_cached_vector_asserted'] is False
    # Unique paragraph text still retains the old conflicting-text refusal.
    distinct = deepcopy(inputs);distinct['rows'][1]['source_text'] = 'other α\n\nshared α'
    distinct['contexts']['physical-1'] = contexts_owner._descriptor(distinct['rows'][1]['source_text'],
        [segment['vector'] for segment in contexts['physical-1']['segments']])
    with pytest.raises(ValueError,match='inconsistent cached vector'):
        subject.infer_contextual_legal_model(handle,distinct)
    with pytest.raises(ValueError,match='inconsistent cached vector'):
        contexts_owner.validate_contexts(distinct['rows'],distinct['contexts'])
    assert subject.infer_contextual_legal_model_occurrences_v1(handle,distinct)['clause_occurrences'] == 4


def test_occurrence_inference_exact_transform_padding_and_bounded_batches(packet,monkeypatch):
    prepared,_ = packet;handle = subject.restore_contextual_legal_model(prepared)
    inputs = _sensitivity_test_packet((1,8)*8+(1,));core = subject._owners()[0];actual = core._greedy;seen = []
    def observe(torch_arg,model,data,cap,size,deadline,*,source_context):
        offset = sum(seen);part = inputs['rows'][offset:offset+len(data)];seen.append(len(data))
        assert data.dtype == torch.float32 and source_context['vectors'].dtype == torch.float32
        for index,row in enumerate(part):
            segments = inputs['contexts'][row['id']]['segments'];count = len(segments)
            assert torch.equal(data[index],(torch.tensor(row['input'],dtype=torch.float32)-.1)/2.)
            assert torch.equal(source_context['vectors'][index,:count],(torch.tensor([v['vector'] for v in segments],dtype=torch.float32)-.1)/2.)
            assert not bool(source_context['vectors'][index,count:].any())
            assert source_context['mask'][index].tolist() == [True]*count+[False]*(8-count)
        return actual(torch_arg,model,data,cap,size,deadline,source_context=source_context)
    monkeypatch.setattr(core,'_greedy',observe)
    report = subject.infer_contextual_legal_model_occurrences_v1(handle,inputs,batch_size=16)
    assert seen == [16,1] and report['clause_occurrences'] == 73
    assert report['greedy_calls_started'] == report['greedy_calls_returned'] == 2
    assert [row['id'] for row in report['predictions']] == [row['id'] for row in inputs['rows']]
    with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs,batch_size=17)


def test_occurrence_inference_identity_membership_and_closed_fields_refuse(packet,monkeypatch):
    prepared,_ = packet;handle = subject.restore_contextual_legal_model(prepared);base = _sensitivity_test_packet((1,1))
    core = subject._owners()[0]
    def forbidden(*args,**kwargs):raise AssertionError('generation ran before source refusal')
    monkeypatch.setattr(core,'_greedy',forbidden)
    for mutation in ('duplicate_id','missing','extra','target','reference','prefix','segment_target'):
        inputs = deepcopy(base)
        if mutation == 'duplicate_id':inputs['rows'][1]['id'] = inputs['rows'][0]['id']
        elif mutation == 'missing':inputs['contexts'].pop(inputs['rows'][0]['id'])
        elif mutation == 'extra':inputs['contexts']['extra'] = deepcopy(next(iter(inputs['contexts'].values())))
        elif mutation == 'target':inputs['rows'][0]['target_ids'] = [1,2]
        elif mutation == 'reference':inputs['reference'] = {}
        elif mutation == 'prefix':inputs['prefix_ids'] = [1,3]
        else:inputs['contexts'][inputs['rows'][0]['id']]['segments'][0]['target'] = {}
        with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)


def test_occurrence_inference_digest_geometry_and_exact_f32_refuse(packet):
    prepared,base = packet;handle = subject.restore_contextual_legal_model(prepared)
    for mutation in ('source','embedding','offset','boolean_offset','nonf32','nonfinite','integer','width','norm'):
        inputs = deepcopy(base);segment = inputs['contexts']['source-1']['segments'][0]
        if mutation == 'source':segment['source_sha256'] = 'a'*64
        elif mutation == 'embedding':segment['embedding_sha256'] = 'a'*64
        elif mutation == 'offset':segment['byte_end'] += 1
        elif mutation == 'boolean_offset':segment['char_start'] = False
        elif mutation == 'nonf32':inputs['rows'][0]['input'][0] = .1
        elif mutation == 'nonfinite':segment['vector'][0] = float('nan')
        elif mutation == 'integer':segment['vector'][0] = 1
        elif mutation == 'width':segment['vector'].pop()
        else:inputs['rows'][0]['input'][0] = 2.
        with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)


def test_occurrence_inference_validator_mutation_cannot_be_adopted(packet,monkeypatch):
    prepared,base = packet;owner = subject._owners()[-1];actual = owner.validate_context
    for target in ('caller','working','metadata','model_binding','codec_binding','transform_binding',
                   'dimension','tensor_sha','vocabulary_binding','mean_binding','requires_grad','method_binding'):
        inputs = deepcopy(base);handle = subject.restore_contextual_legal_model(prepared)
        def mutate(row,descriptor):
            result = actual(row,descriptor)
            if target == 'caller':inputs['rows'][0]['input'] = [0.,1.]+[0.]*382
            elif target == 'working':row['input'] = [0.,1.]+[0.]*382
            elif target == 'metadata':handle.input_transform['scale'] = 3.
            elif target == 'model_binding':object.__setattr__(handle,'model',deepcopy(handle.model))
            elif target == 'codec_binding':object.__setattr__(handle,'codec',deepcopy(handle.codec))
            elif target == 'transform_binding':object.__setattr__(handle,'input_transform',deepcopy(handle.input_transform))
            elif target == 'dimension':object.__setattr__(handle,'dimension',768)
            elif target == 'tensor_sha':object.__setattr__(handle,'tensor_sha256','a'*64)
            elif target == 'vocabulary_binding':handle.codec['target_vocabulary'] = list(handle.codec['target_vocabulary'])
            elif target == 'mean_binding':handle.input_transform['mean'] = list(handle.input_transform['mean'])
            elif target == 'requires_grad':
                parameter = next(handle.model.parameters());parameter.requires_grad_(not parameter.requires_grad)
            else:monkeypatch.setattr(handle.model,'next_logits',lambda *args:None)
            return result
        monkeypatch.setattr(owner,'validate_context',mutate)
        with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)


def test_occurrence_inference_explicit_f32_and_precision_policy(packet,monkeypatch):
    prepared,inputs = packet;handle = subject.restore_contextual_legal_model(prepared);core = subject._owners()[0]
    actual = core._greedy;before = torch.get_default_dtype();precision = torch.get_float32_matmul_precision()
    def observe(torch_arg,model,data,*args,source_context,**kwargs):
        assert data.dtype == source_context['vectors'].dtype == torch.float32
        return actual(torch_arg,model,data,*args,source_context=source_context,**kwargs)
    monkeypatch.setattr(core,'_greedy',observe)
    try:
        torch.set_default_dtype(torch.float64)
        assert subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)['caller_default_dtype_preserved']
        assert torch.get_default_dtype() == torch.float64
        with torch.autocast(device_type='cpu',dtype=torch.bfloat16):
            with pytest.raises(ValueError,match='autocast'):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)
        torch.set_float32_matmul_precision('high')
        with pytest.raises(ValueError,match='highest'):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)
    finally:torch.set_default_dtype(before);torch.set_float32_matmul_precision(precision)


def test_occurrence_inference_frozen_model_preflight_and_parameter_mutation(packet,monkeypatch):
    prepared,inputs = packet
    for kind in ('training','gradient','parameter'):
        handle = subject.restore_contextual_legal_model(prepared)
        if kind == 'training':handle.model.train()
        elif kind == 'gradient':next(handle.model.parameters()).grad = torch.zeros_like(next(handle.model.parameters()))
        else:
            actual = handle.model.next_logits
            def mutate(*args):
                value = actual(*args)
                with torch.no_grad():handle.model.action_head.field_readout.bias[0] += 1.
                return value
            monkeypatch.setattr(handle.model,'next_logits',mutate)
        with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)


def test_occurrence_inference_rng_source_metadata_and_working_tensors_guarded(packet,monkeypatch):
    prepared,base = packet;core = subject._owners()[0];actual = core._greedy
    for kind in ('rng','source','metadata','data','packet','mask'):
        inputs = deepcopy(base);handle = subject.restore_contextual_legal_model(prepared)
        def mutate(torch_arg,model,data,*args,source_context,**kwargs):
            value = actual(torch_arg,model,data,*args,source_context=source_context,**kwargs)
            if kind == 'rng':torch.rand(1)
            elif kind == 'source':inputs['rows'][0]['input'] = [0.,1.]+[0.]*382
            elif kind == 'metadata':handle.codec['target_vocabulary'].append('changed')
            elif kind == 'data':data[0,0] += 1.
            elif kind == 'packet':source_context['vectors'][0,0,0] += 1.
            else:source_context['mask'][0,0] = False
            return value
        monkeypatch.setattr(core,'_greedy',mutate)
        with torch.random.fork_rng(devices=[]):
            with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs)


def test_occurrence_inference_deadline_and_argument_bounds_preserve_rows(packet,monkeypatch):
    prepared,_ = packet;handle = subject.restore_contextual_legal_model(prepared);inputs = _sensitivity_test_packet((1,1,1))
    ticks = iter([0.,1.,2.,3.]);monkeypatch.setattr(subject.time,'monotonic',lambda:next(ticks))
    report = subject.infer_contextual_legal_model_occurrences_v1(handle,inputs,deadline_seconds=.01,batch_size=2)
    assert report['predictions'] == [dict(id=row['id'],token_ids=[],eos_reached=False,generation_status='deadline') for row in inputs['rows']]
    assert not report['execution_completed'] and not report['eos_completed']
    assert report['greedy_calls_started'] == report['greedy_calls_returned'] == 0
    assert report['model_inference_executed'] is report['greedy_generation_executed'] is False
    for kwargs in (dict(output_cap=True),dict(output_cap=3),dict(output_cap=513),dict(batch_size=True),dict(deadline_seconds=0.),dict(deadline_seconds=float('inf'))):
        with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs,**kwargs)


def test_occurrence_inference_raw_status_taxonomy(packet,monkeypatch):
    prepared,inputs = packet;handle = subject.restore_contextual_legal_model(prepared);core = subject._owners()[0]
    # Explicit consumer-taxonomy doubles; genuine model/EOS parity is separate.
    for status,tokens in (('eos',[3]),('invalid_special_token',[3]),('output_limit',[3,3,3]),('deadline',[])):
        def taxonomy(torch_arg,model,data,cap,size,deadline,*,source_context):
            return data.clone(),[list(tokens)],[status]
        monkeypatch.setattr(core,'_greedy',taxonomy)
        report = subject.infer_contextual_legal_model_occurrences_v1(handle,inputs,output_cap=4)
        assert report['predictions'] == [dict(id='source-1',token_ids=tokens,eos_reached=status=='eos',generation_status=status)]
        assert report['execution_completed'] is (status != 'deadline') and report['eos_completed'] is (status == 'eos')
        assert report['decoded_IR_valid'] is report['task_satisfied'] is None
    def no_batch(*args,**kwargs):return None
    monkeypatch.setattr(core,'_greedy',no_batch)
    report = subject.infer_contextual_legal_model_occurrences_v1(handle,inputs,output_cap=4)
    assert report['greedy_calls_started'] == report['greedy_calls_returned'] == 1
    assert report['predictions'][0]['generation_status'] == 'deadline'


def test_occurrence_inference_malformed_generation_return_refuses(packet,monkeypatch):
    prepared,inputs = packet;handle = subject.restore_contextual_legal_model(prepared);core = subject._owners()[0]
    for mutation in ('cardinality','status','boolean_token','special_token','outside_vocab','short_limit','late_eos','deadline_tokens','nonfinite_projection'):
        def malformed(torch_arg,model,data,cap,size,deadline,*,source_context):
            projected = data.clone();tokens = [[3]];statuses = ['eos']
            if mutation == 'cardinality':tokens = []
            elif mutation == 'status':statuses = ['complete']
            elif mutation == 'boolean_token':tokens = [[True]]
            elif mutation == 'special_token':tokens = [[2]]
            elif mutation == 'outside_vocab':tokens = [[size]]
            elif mutation == 'short_limit':statuses = ['output_limit']
            elif mutation == 'late_eos':tokens = [[3,3,3]]
            elif mutation == 'deadline_tokens':statuses = ['deadline']
            else:projected[0,0] = float('nan')
            return projected,tokens,statuses
        monkeypatch.setattr(core,'_greedy',malformed)
        with pytest.raises(ValueError):subject.infer_contextual_legal_model_occurrences_v1(handle,inputs,output_cap=4)
