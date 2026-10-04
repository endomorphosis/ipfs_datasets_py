"""Synthetic controls for the additive path, not corpus/fidelity evidence."""
from copy import deepcopy
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as old
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def body(dimension=384):
    return numerical._model({"dimension": dimension}, {"target_vocabulary": ["<pad>", "<bos>", "<eos>", "a", "b"]},
        dict(seed=2026, hidden_size=8, token_embedding_dim=8, projection_width=2))


def data(dimension=384):
    generator = torch.Generator().manual_seed(722)
    return torch.randn((3, dimension), generator=generator), torch.tensor([[1, 3, 4, 2], [1, 4, 2, 0], [1, 3, 3, 2]])


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("conditioning", ["first_step", "every_step"])
def test_zero_adapter_preserves_exact_full_prefix_logits_and_inherited_tensors(dimension, conditioning):
    source = body(dimension)
    before = old.tensor_digest(source)
    rng = torch.get_rng_state().clone()
    student = subject.bind_persistent_model(source, dimension=dimension, conditioning=conditioning)
    assert torch.equal(rng, torch.get_rng_state())
    assert old.tensor_digest(source) == old.tensor_digest(student.body) == before
    assert next(source.parameters()).data_ptr() != next(student.body.parameters()).data_ptr()
    inputs, prefix = data(dimension)
    expected_projected, expected_logits = source(inputs, prefix)
    projected, logits = student(inputs, prefix)
    assert torch.equal(expected_projected, projected)
    assert torch.equal(expected_logits, logits)
    record = student.describe()
    assert record["current_adapter_is_zero"]
    assert record["added_parameter_count"] == dimension*8
    assert all(record[key] is False for key in subject.FALSE)
    assert set(student.state_dict()) == {"body."+key for key in source.state_dict()} | {"source_to_embedding.weight"}


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_initial_target_free_sequences_and_reconstruction_equal_baseline(dimension):
    source = body(dimension)
    baseline = old.bind_model(source, dimension=dimension)
    student = subject.bind_persistent_model(source, dimension=dimension)
    inputs, _ = data(dimension)
    with torch.inference_mode():
        expected = old._greedy(torch, baseline, inputs, 32, 5, time.monotonic()+10)
        actual = old._greedy(torch, student, inputs, 32, 5, time.monotonic()+10)
    assert torch.equal(expected[0], actual[0])
    assert expected[1:] == actual[1:]


@pytest.mark.parametrize("nonzero", [False, True])
@pytest.mark.parametrize("conditioning", ["first_step", "every_step"])
def test_full_prefix_and_one_token_recurrence_agree(nonzero, conditioning):
    student = subject.bind_persistent_model(body(), dimension=384, conditioning=conditioning)
    if nonzero:
        with torch.no_grad():
            student.source_to_embedding.weight.fill_(.007)
    inputs, prefix = data()
    projected = student.project(inputs)
    initial = student.start(projected)
    full, full_state = student.next_logits(prefix, initial)
    state, parts = initial, []
    for index in range(prefix.shape[1]):
        output, state = student.next_logits(prefix[:, index:index+1], state)
        parts.append(output)
    # GRU GEMM batching may round differently for one step versus a full prefix.
    assert torch.allclose(full, torch.cat(parts, dim=1), atol=1e-7, rtol=1e-6)
    assert torch.allclose(full_state[0], state[0], atol=1e-7, rtol=1e-6)
    assert state[1] is initial[1] is full_state[1] is projected
    assert torch.equal(state[2], full_state[2]) and state[2].tolist() == [prefix.shape[1]]*3
    assert initial[2].tolist() == [0]*3


@pytest.mark.parametrize("conditioning", ["first_step", "every_step"])
def test_zero_adapter_receives_real_nonzero_gradients_without_changing_teacher(conditioning):
    source = body()
    before = old.tensor_digest(source)
    student = subject.bind_persistent_model(source, dimension=384, conditioning=conditioning)
    inputs, prefix = data()
    _, logits = student(inputs, prefix[:, :-1])
    loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 5), prefix[:, 1:].reshape(-1), ignore_index=0)
    loss.backward()
    gradient = student.source_to_embedding.weight.grad
    assert gradient is not None and bool(torch.isfinite(gradient).all()) and float(gradient.abs().sum()) > 0
    assert all(parameter.grad is None for parameter in source.parameters())
    assert old.tensor_digest(source) == before
    optimizer = torch.optim.AdamW(student.parameters(), lr=.001)
    optimizer.step()
    assert student.describe()["current_adapter_is_zero"] is False


def test_persistent_source_is_not_only_an_initial_hidden_effect():
    student = subject.bind_persistent_model(body(), dimension=384)
    with torch.no_grad():
        student.source_to_embedding.weight[:, 0] = .5
    hidden = torch.zeros((1, 1, 8))
    source_a = torch.zeros((1, 384)); source_b = source_a.clone(); source_b[0, 0] = 1.
    prefix = torch.tensor([[1, 3, 4]])
    position = torch.zeros(1, dtype=torch.long)
    first, _ = student.next_logits(prefix, (hidden.clone(), source_a, position))
    second, _ = student.next_logits(prefix, (hidden.clone(), source_b, position))
    assert not torch.equal(first[:, -1], second[:, -1])


def test_interleaved_sequences_have_no_cross_request_source_cache_or_state_mutation():
    student = subject.bind_persistent_model(body(), dimension=384)
    with torch.no_grad():
        student.source_to_embedding.weight.fill_(.002)
    inputs, _ = data()
    state_a = student.start(student.project(inputs[:1]))
    state_b = student.start(student.project(inputs[1:2]))
    old_a, old_b = tuple(x.clone() for x in state_a), tuple(x.clone() for x in state_b)
    token = torch.tensor([[1]])
    first_a, next_a = student.next_logits(token, state_a)
    _, next_b = student.next_logits(token, state_b)
    second_a, next_next_a = student.next_logits(torch.tensor([[3]]), next_a)
    expected_a, expected_state = student.next_logits(torch.tensor([[1, 3]]), state_a)
    assert torch.allclose(first_a, expected_a[:, :1], atol=1e-7, rtol=1e-6)
    assert torch.allclose(second_a, expected_a[:, 1:], atol=1e-7, rtol=1e-6)
    assert torch.allclose(next_next_a[0], expected_state[0], atol=1e-7, rtol=1e-6)
    assert all(torch.equal(x, y) for x, y in zip(state_a, old_a))
    assert all(torch.equal(x, y) for x, y in zip(state_b, old_b))
    assert next_b[1] is state_b[1] and next_next_a[1] is state_a[1]
    assert not any("cache" in key or "source_context" in key for key in vars(student))


def test_projection_trainability_and_exact_original_shape_are_preserved():
    source = body()
    for name, parameter in source.named_parameters():
        if name.startswith("projection_"):
            parameter.requires_grad_(False)
    student = subject.bind_persistent_model(source, dimension=384)
    original_flags = {name: parameter.requires_grad for name, parameter in source.named_parameters()}
    assert {name: parameter.requires_grad for name, parameter in student.body.named_parameters()} == original_flags
    assert student.source_to_embedding.weight.requires_grad
    assert student.body.decoder.input_size == source.decoder.input_size
    assert {name: tensor.shape for name, tensor in source.state_dict().items()} == {
        name: tensor.shape for name, tensor in student.body.state_dict().items()}


def test_adapter_state_roundtrip_requires_separate_architecture():
    original = body()
    student = subject.bind_persistent_model(original, dimension=384)
    with torch.no_grad():
        student.source_to_embedding.weight.fill_(.03)
    state = deepcopy(student.state_dict())
    reloaded = subject.bind_persistent_model(original, dimension=384)
    reloaded.load_state_dict(state, strict=True)
    assert old.tensor_digest(student) == old.tensor_digest(reloaded)
    with pytest.raises(RuntimeError):
        original.load_state_dict(state, strict=True)


@pytest.mark.parametrize("wrong_dimension", [8, 16, 768, True])
def test_actual_projection_width_must_match_declared_input_dimension(wrong_dimension):
    with pytest.raises(ValueError):
        subject.bind_persistent_model(body(), dimension=wrong_dimension)


def test_wrapped_body_and_changed_gru_geometry_are_rejected():
    original = body()
    with pytest.raises(ValueError, match="unwrapped"):
        subject.bind_persistent_model(old.bind_model(original, dimension=384), dimension=384)
    original.decoder = torch.nn.GRU(16, 8, batch_first=True)
    with pytest.raises(ValueError, match="original GRU input geometry"):
        subject.bind_persistent_model(original, dimension=384)


@pytest.mark.parametrize("case", ["tuple", "batch", "hidden", "token", "source_dtype", "source_nonfinite", "too_long",
    "negative_position", "floating_position", "position_batch", "position_overflow", "position_int64_overflow", "missing_bos"])
def test_explicit_state_and_prefix_contracts_fail_closed(case):
    student = subject.bind_persistent_model(body(), dimension=384)
    inputs, prefix = data()
    state = student.start(student.project(inputs))
    if case == "tuple": state = state[0]
    if case == "batch": state = (state[0], state[1][:1], state[2])
    if case == "hidden": state = (state[0][:, :, :1], state[1], state[2])
    if case == "token": prefix[0, 0] = 99
    if case == "source_dtype": state = (state[0], state[1].double(), state[2])
    if case == "source_nonfinite": state[1][0, 0] = float("inf")
    if case == "too_long": prefix = torch.ones((3, 1024), dtype=torch.long)
    if case == "negative_position": state = (*state[:2], torch.full((3,), -1, dtype=torch.long))
    if case == "floating_position": state = (*state[:2], state[2].float())
    if case == "position_batch": state = (*state[:2], state[2][:1])
    if case == "position_overflow": state = (*state[:2], torch.full((3,), 1023, dtype=torch.long))
    if case == "position_int64_overflow": state = (*state[:2], torch.full((3,), 2**63-1, dtype=torch.long))
    if case == "missing_bos": prefix[:, 0] = 3
    with pytest.raises(ValueError):
        student.next_logits(prefix, state)


def test_existing_experiment_protocol_accepts_tuple_state_and_keeps_teacher_frozen():
    original = body(8)
    teacher = old.bind_model(original, dimension=8)
    student = subject.bind_persistent_model(original, dimension=8)
    codec = {"schema": "synthetic-only/v1", "target_vocabulary": ["<pad>", "<bos>", "<eos>", "a", "b"]}
    def rows(split):
        return [dict(id=split+str(i), source_text=split+" synthetic row "+str(i),
            input=[.2+i*.1]+[0.]*7, target_ids=[1, 3+i, 2]) for i in range(2)]
    result = subject.run_trial(teacher, rows("train"), rows("validation"), student=student, codec=codec,
        input_transform=dict(mode="none", mean=[0.]*8, scale=1., origin="training_only"),
        lineage=dict(teacher_checkpoint_sha256="a"*64, teacher_codec_sha256=old.digest(codec),
            input_provenance_sha256="b"*64, domain="legal_ir", teacher_lineage="synthetic",
            student_lineage="synthetic-persistent", teacher_output_limit=64, student_role="learned_formula_sidecar"),
        config=dict(epochs=1, max_optimizer_steps=1, max_seconds=10., max_target_tokens=8, alpha=.25))
    assert result["report"]["optimizer_steps"] == 1
    assert result["report"]["teacher_frozen_verified"]
    assert "source_to_embedding.weight" in result["report"]["trainable_parameter_names"]
    assert len(result["predictions"]) == 2
    assert subject.run_trial is old.run_trial and subject.evaluate_model is old.evaluate_model


@pytest.mark.parametrize("kind", ["raw", "initial", "persistent"])
def test_zero_condition_control_removes_all_source_paths_but_keeps_projection(kind):
    original = body()
    if kind == "initial": original = old.bind_model(original, dimension=384)
    if kind == "persistent":
        original = subject.bind_persistent_model(original, dimension=384)
        with torch.no_grad(): original.source_to_embedding.weight.fill_(.05)
    before = old.tensor_digest(original)
    modes = [part.training for part in original.modules()]
    control = subject.bind_zero_condition_model(original, dimension=384)
    inputs, prefix = data()
    same_prefix = prefix[:1].expand(3, -1)
    projected, logits = control(inputs, same_prefix)
    assert torch.equal(projected, original.project(inputs))
    assert not torch.equal(projected[0], projected[1])
    assert torch.equal(logits[0], logits[1]) and torch.equal(logits[1], logits[2])
    state = control.start(projected)
    tensors = (state,) if isinstance(state, torch.Tensor) else state[:2]
    assert all(torch.count_nonzero(value) == 0 for value in tensors)
    _, advanced = control.next_logits(same_prefix, state)
    advanced_hidden = advanced[0] if type(advanced) is tuple else advanced
    assert torch.count_nonzero(advanced_hidden) > 0
    if type(advanced) is tuple: assert torch.count_nonzero(advanced[1]) == 0
    assert old.tensor_digest(original) == before
    assert modes == [part.training for part in original.modules()]
    assert all(parameter.grad is None for parameter in original.parameters())


def test_zero_condition_control_has_same_target_free_outputs_for_different_sources():
    original = subject.bind_persistent_model(body(), dimension=384)
    with torch.no_grad(): original.source_to_embedding.weight.fill_(.05)
    control = subject.bind_zero_condition_model(original, dimension=384)
    inputs, _ = data()
    with torch.inference_mode():
        _, tokens, statuses = old._greedy(torch, control, inputs, 32, 5, time.monotonic()+5)
    assert tokens[0] == tokens[1] == tokens[2]
    assert statuses[0] == statuses[1] == statuses[2]


def test_zero_condition_control_rejects_mismatched_bound_dimension():
    original = subject.bind_persistent_model(body(), dimension=384)
    with pytest.raises(ValueError, match="dimension differs"):
        subject.bind_zero_condition_model(original, dimension=8)


def test_first_and_every_step_have_identical_initial_parameters_and_trainability():
    original = body()
    first = subject.bind_persistent_model(original, dimension=384, conditioning="first_step")
    every = subject.bind_persistent_model(original, dimension=384, conditioning="every_step")
    assert old.tensor_digest(first) == old.tensor_digest(every)
    assert [(name, p.numel(), p.requires_grad) for name, p in first.named_parameters()] == [
        (name, p.numel(), p.requires_grad) for name, p in every.named_parameters()]
    assert first.describe()["conditioning"] == "first_step"
    assert every.describe()["conditioning"] == "every_step"
    assert first.describe()["state_layout"] == every.describe()["state_layout"]


def test_first_step_residual_excludes_later_positions_and_every_step_does_not():
    source_a = torch.zeros((1, 384)); source_b = source_a.clone(); source_b[0, 0] = 1.
    hidden = torch.zeros((1, 1, 8))
    prefix = torch.tensor([[3, 4]])
    position = torch.tensor([2])
    for mode in ("first_step", "every_step"):
        student = subject.bind_persistent_model(body(), dimension=384, conditioning=mode)
        with torch.no_grad(): student.source_to_embedding.weight[:, 0] = .5
        first, first_state = student.next_logits(prefix, (hidden.clone(), source_a, position))
        second, second_state = student.next_logits(prefix, (hidden.clone(), source_b, position))
        assert torch.equal(first, second) is (mode == "first_step")
        assert first_state[2].tolist() == second_state[2].tolist() == [4]
        assert position.tolist() == [2]


def test_first_step_batched_different_positions_remain_per_sequence():
    student = subject.bind_persistent_model(body(), dimension=384, conditioning="first_step")
    with torch.no_grad(): student.source_to_embedding.weight.fill_(.01)
    source = torch.ones((2, 384))
    hidden = torch.zeros((1, 2, 8))
    position = torch.tensor([0, 7])
    tokens = torch.tensor([[1, 3], [4, 3]])
    batched, state = student.next_logits(tokens, (hidden, source, position))
    for index in range(2):
        independent, _ = student.next_logits(tokens[index:index+1],
            (hidden[:, index:index+1], source[index:index+1], position[index:index+1]))
        assert torch.allclose(batched[index:index+1], independent, atol=1e-7, rtol=1e-6)
    assert state[2].tolist() == [2, 9] and position.tolist() == [0, 7]


@pytest.mark.parametrize("mode", ["first_step", "every_step"])
def test_zero_source_control_keeps_prefix_counters_and_matches_between_modes(mode):
    model = subject.bind_persistent_model(body(), dimension=384, conditioning=mode)
    with torch.no_grad(): model.source_to_embedding.weight.fill_(.2)
    zero = subject.bind_zero_condition_model(model, dimension=384)
    inputs, prefix = data()
    state = zero.start(zero.project(inputs))
    assert state[2].dtype == torch.long and state[2].tolist() == [0, 0, 0]
    _, next_state = zero.next_logits(prefix, state)
    assert next_state[2].tolist() == [4, 4, 4]
    assert torch.count_nonzero(next_state[1]) == 0
    assert state[2].tolist() == [0, 0, 0]


def test_unknown_conditioning_mode_is_rejected():
    with pytest.raises(ValueError, match="conditioning mode"):
        subject.bind_persistent_model(body(), dimension=384, conditioning="sometimes")
