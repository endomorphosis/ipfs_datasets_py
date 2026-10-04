"""Synthetic training objectives; no donor or target-model qualification."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_distillation.py"
SPEC = importlib.util.spec_from_file_location("gte_distillation_test_subject", MODULE)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def contract(codec="a", prefix="b", **changes):
    result = {
        "student_codec_sha256": codec * 64, "teacher_codec_sha256": codec * 64,
        "student_prefix_sha256": prefix * 64, "teacher_prefix_sha256": prefix * 64,
        "prefix_policy": "reference_prefix", "distribution": "raw",
        "teacher_checkpoint_sha256": "c" * 64, "teacher_qualification_sha256": "d" * 64,
        "teacher_scope_id": "legal:reviewed-single-norm/v1",
    }
    result.update(changes)
    return result


def case():
    student = torch.tensor([
        [[.1, -.3, .7], [.9, .2, -.5]],
        [[-.2, .8, .3], [.4, -.7, .5]],
    ], dtype=torch.float32, requires_grad=True)
    teacher = torch.tensor([
        [[.9, .2, -.3], [.1, -.4, .5]],
        [[.6, .1, -.5], [-.2, .8, .3]],
    ], dtype=torch.float32, requires_grad=True)
    mask = torch.tensor([[True, False], [True, False]], dtype=torch.bool)
    return student, teacher, mask


def evaluate(values=None, **changes):
    student, teacher, mask = values or case()
    arguments = {"token_mask": mask, "temperature": 2., "alignment_contract": contract()}
    arguments.update(changes)
    return subject.masked_teacher_kl(student, teacher, **arguments)


def test_pure_import_does_not_load_numerical_dependencies():
    program = """import importlib.util, sys
spec = importlib.util.spec_from_file_location('isolated_kd', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch', 'numpy', 'transformers'))
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(MODULE)], check=True)


def test_t_squared_normalization_matches_independent_formula_and_gradient():
    student, teacher, mask = values = case()
    result = evaluate(values)
    q = torch.softmax(teacher.detach()[mask] / 2., dim=-1)
    p = torch.softmax(student.detach()[mask] / 2., dim=-1)
    expected = (q * (q.log() - p.log())).sum(dim=-1).mean() * 4.
    assert torch.allclose(result["loss"].detach(), expected, atol=1e-6)
    result["loss"].backward()
    assert torch.allclose(student.grad[mask], 2. * (p - q) / 2, atol=1e-7)
    assert torch.equal(student.grad[~mask], torch.zeros_like(student.grad[~mask]))
    assert teacher.grad is None
    assert result["valid_token_count"] == 2 and result["excluded_token_count"] == 2
    assert result["vocabulary_size"] == 3 and result["temperature"] == 2.
    assert result["teacher_logits_detached"] is True
    assert result["qualification_authenticated"] is False
    assert result["training_performed"] is False and result["proof_authority"] is False


def test_masked_positions_do_not_change_loss_or_receive_gradients():
    first = case()
    original = evaluate(first)["loss"].detach()
    student, teacher, mask = second = case()
    with torch.no_grad():
        student[~mask] = 1000.
        teacher[~mask] = -1000.
    result = evaluate(second)
    assert torch.equal(original, result["loss"].detach())
    result["loss"].backward()
    assert bool((student.grad[mask] != 0).any())
    assert torch.equal(student.grad[~mask], torch.zeros_like(student.grad[~mask]))


def test_all_masked_returns_differentiable_zero_without_teacher_gradient():
    student, teacher, mask = values = case()
    mask.zero_()
    result = evaluate(values)
    assert result["valid_token_count"] == 0 and result["excluded_token_count"] == 4
    assert result["loss"].requires_grad and result["loss"].item() == 0.
    result["loss"].backward()
    assert torch.equal(student.grad, torch.zeros_like(student))
    assert teacher.grad is None


def test_all_masked_avoids_overflowing_sum_of_finite_logits():
    student = torch.full((1, 2, 3), torch.finfo(torch.float32).max, requires_grad=True)
    teacher = student.detach().clone().requires_grad_()
    result = evaluate((student, teacher, torch.zeros((1, 2), dtype=torch.bool)))
    assert result["loss"].item() == 0.
    result["loss"].backward()
    assert torch.equal(student.grad, torch.zeros_like(student)) and teacher.grad is None


def test_existing_teacher_gradients_are_preserved_and_inputs_not_mutated():
    student, teacher, mask = values = case()
    teacher.grad = torch.full_like(teacher, 7.)
    saved = [tensor.detach().clone() for tensor in values]
    before_grad = teacher.grad.clone()
    evaluate(values)["loss"].backward()
    assert torch.equal(teacher.grad, before_grad)
    assert all(torch.equal(value.detach(), old) for value, old in zip(values, saved))


def test_identical_distributions_have_exact_zero_kl():
    student = torch.tensor([[[.4, .2, -.7]]], requires_grad=True)
    teacher = student.detach().clone().requires_grad_()
    result = evaluate((student, teacher, torch.tensor([[True]])))
    assert result["loss"].item() == 0.
    result["loss"].backward()
    assert torch.allclose(student.grad, torch.zeros_like(student), atol=1e-7)
    assert teacher.grad is None


@pytest.mark.parametrize("temperature", [0, -.1, .001, 101, 10**1000, float("nan"), float("inf"), True, "2", None])
def test_invalid_temperature_rejected(temperature):
    with pytest.raises(ValueError):
        evaluate(temperature=temperature)


@pytest.mark.parametrize("temperature", [.01, 1, 2., 100.])
def test_bounded_temperature_profiles_are_explicit(temperature):
    assert evaluate(temperature=temperature)["temperature"] == float(temperature)


@pytest.mark.parametrize("changes", [
    {"teacher_codec_sha256": "e" * 64}, {"teacher_prefix_sha256": "e" * 64},
    {"student_codec_sha256": "A" * 64}, {"teacher_checkpoint_sha256": "short"},
    {"teacher_qualification_sha256": None}, {"teacher_prefix_sha256": 1},
    {"prefix_policy": "teacher_generated_prefix"}, {"distribution": "blended"},
    {"teacher_scope_id": ""}, {"teacher_scope_id": " unreviewed "},
    {"teacher_scope_id": "bad\nidentity"}, {"teacher_scope_id": "x" * 257},
    {"unknown_field": False},
])
def test_contract_mismatch_or_malformed_evidence_rejected(changes):
    with pytest.raises(ValueError):
        evaluate(alignment_contract=contract(**changes))


def test_missing_contract_field_and_non_dict_rejected():
    incomplete = contract()
    incomplete.pop("teacher_scope_id")
    for value in (incomplete, None, []):
        with pytest.raises(ValueError):
            evaluate(alignment_contract=value)


def test_contract_is_private_and_digested_but_not_authenticated():
    declaration = contract(distribution="grammar_masked")
    result = evaluate(alignment_contract=declaration)
    before = deepcopy(declaration)
    declaration["teacher_scope_id"] = "changed"
    assert result["alignment_contract"] == before
    assert len(result["alignment_contract_sha256"]) == 64
    assert result["qualification_authenticated"] is False


@pytest.mark.parametrize("which", ["student", "teacher"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_logits_rejected_even_at_excluded_positions(which, value):
    student, teacher, mask = values = case()
    with torch.no_grad():
        (student if which == "student" else teacher)[0, 1, 0] = value
    with pytest.raises(ValueError, match="nonfinite"):
        evaluate(values)


@pytest.mark.parametrize("kind", ["integer", "float", "list", "wrong_shape", "meta", "sparse"])
def test_mask_requires_explicit_cpu_boolean_tensor(kind):
    student, teacher, mask = case()
    malformed = {
        "integer": mask.long(), "float": mask.float(), "list": mask.tolist(),
        "wrong_shape": torch.ones((2, 2, 1), dtype=torch.bool),
        "meta": torch.empty((2, 2), dtype=torch.bool, device="meta"),
        "sparse": mask.to_sparse(),
    }[kind]
    with pytest.raises(ValueError):
        evaluate((student, teacher, malformed))


@pytest.mark.parametrize("kind", ["float64", "integer", "list", "2d", "meta", "mismatch", "sparse"])
def test_per_head_logits_geometry_dtype_and_device_are_strict(kind):
    student, teacher, mask = case()
    malformed = {
        "float64": teacher.double(), "integer": teacher.long(), "list": teacher.tolist(),
        "2d": teacher.reshape(4, 3), "meta": torch.empty((2, 2, 3), device="meta"),
        "mismatch": teacher[:, :1],
        "sparse": teacher.to_sparse(),
    }[kind]
    with pytest.raises(ValueError):
        evaluate((student, malformed, mask))


@pytest.mark.parametrize("shape", [(0, 2, 3), (257, 1, 2), (1, 0, 3), (1, 1025, 2), (1, 1, 1), (1, 1, 4097)])
def test_logits_geometry_bounds(shape):
    student = torch.zeros(shape, requires_grad=True)
    teacher = torch.zeros(shape)
    mask = torch.ones(shape[:2], dtype=torch.bool)
    with pytest.raises(ValueError):
        evaluate((student, teacher, mask))


def test_logit_element_budget(monkeypatch):
    monkeypatch.setattr(subject, "MAX_LOGIT_ELEMENTS", 5)
    with pytest.raises(ValueError):
        evaluate()


def test_student_needs_gradient_and_context_cannot_be_inference():
    student, teacher, mask = case()
    with pytest.raises(ValueError):
        evaluate((student.detach(), teacher, mask))
    with torch.no_grad(), pytest.raises(ValueError):
        evaluate((student, teacher, mask))
    with torch.inference_mode(), pytest.raises(ValueError):
        evaluate((student, teacher, mask))


def test_extreme_finite_valid_logits_reject_nonfinite_scaled_probabilities():
    student = torch.tensor([[[3e38, -3e38]]], dtype=torch.float32, requires_grad=True)
    teacher = torch.tensor([[[0., 1.]]], dtype=torch.float32)
    with pytest.raises(ValueError, match="nonfinite"):
        evaluate((student, teacher, torch.tensor([[True]])), temperature=.01)


def head_results():
    student, teacher, mask = values = case()
    main = evaluate(values)
    auxiliary_student = torch.tensor([[[.3, .1, -.2, .6]]], requires_grad=True)
    auxiliary_teacher = torch.tensor([[[.7, .2, .1, -.5]]], requires_grad=True)
    aux = evaluate((auxiliary_student, auxiliary_teacher, torch.tensor([[True]])),
                   temperature=1., alignment_contract=contract(codec="e", prefix="f", distribution="grammar_masked"))
    return {"typed_json": main, "legacy_formula": aux}, (student, teacher, auxiliary_student, auxiliary_teacher)


def test_multiteacher_weights_separate_vocabularies_and_time_normalization():
    heads, (student, teacher, auxiliary_student, auxiliary_teacher) = head_results()
    result = subject.combine_multiteacher_losses(heads, weights={"typed_json": .7, "legacy_formula": .3})
    expected = .7 * heads["typed_json"]["loss"] + .3 * heads["legacy_formula"]["loss"]
    assert torch.equal(result["loss"], expected)
    assert result["heads"]["typed_json"]["valid_token_count"] == 2
    assert result["heads"]["legacy_formula"]["valid_token_count"] == 1
    assert result["heads"]["typed_json"]["vocabulary_size"] == 3
    assert result["heads"]["legacy_formula"]["vocabulary_size"] == 4
    assert result["logits_combined"] is False
    assert result["head_normalization"] == "eligible_tokens_within_each_head"
    result["loss"].backward()
    assert bool((student.grad != 0).any()) and bool((auxiliary_student.grad != 0).any())
    assert teacher.grad is None and auxiliary_teacher.grad is None


def test_zero_weight_disables_auxiliary_gradients_and_keeps_accounting():
    heads, (_, _, auxiliary_student, _) = head_results()
    result = subject.combine_multiteacher_losses(heads, weights={"typed_json": 1., "legacy_formula": 0.})
    result["loss"].backward()
    assert torch.equal(auxiliary_student.grad, torch.zeros_like(auxiliary_student))
    assert result["heads"]["legacy_formula"]["weight"] == 0.
    assert result["heads"]["legacy_formula"]["valid_token_count"] == 1


@pytest.mark.parametrize("weights", [
    {"typed_json": 1.}, {"typed_json": 1., "legacy_formula": 1., "extra": 1.},
    {"typed_json": -1., "legacy_formula": 1.}, {"typed_json": 0., "legacy_formula": 0.},
    {"typed_json": True, "legacy_formula": 1.}, {"typed_json": float("nan"), "legacy_formula": 1.},
    {"typed_json": float("inf"), "legacy_formula": 1.}, {"typed_json": 101., "legacy_formula": 1.},
    {"typed_json": 10**1000, "legacy_formula": 1.},
])
def test_invalid_multiteacher_weights_rejected(weights):
    heads, _ = head_results()
    with pytest.raises(ValueError):
        subject.combine_multiteacher_losses(heads, weights=weights)


@pytest.mark.parametrize("kind", ["extra", "schema", "counts", "digest", "qualification", "detached", "dtype"])
def test_malformed_head_result_rejected(kind):
    heads, _ = head_results()
    bad = dict(heads["typed_json"])
    if kind == "extra":
        bad["unknown"] = False
    elif kind == "schema":
        bad["schema"] = "other"
    elif kind == "counts":
        bad["valid_token_count"] = True
    elif kind == "digest":
        bad["alignment_contract_sha256"] = "a" * 64
    elif kind == "qualification":
        bad["qualification_authenticated"] = True
    elif kind == "detached":
        bad["loss"] = bad["loss"].detach()
    elif kind == "dtype":
        bad["loss"] = bad["loss"].double()
    with pytest.raises(ValueError):
        subject.combine_multiteacher_losses({"typed_json": bad}, weights={"typed_json": 1.})


def test_combination_does_not_mutate_head_contracts_or_require_same_codecs():
    heads, _ = head_results()
    before = {name: deepcopy(result["alignment_contract"]) for name, result in heads.items()}
    result = subject.combine_multiteacher_losses(heads, weights={"typed_json": 1., "legacy_formula": .2})
    result["heads"]["typed_json"]["alignment_contract"]["teacher_scope_id"] = "changed"
    assert {name: head["alignment_contract"] for name, head in heads.items()} == before
    assert before["typed_json"]["student_codec_sha256"] != before["legacy_formula"]["student_codec_sha256"]


def test_combination_rejects_empty_or_unbounded_names_and_inference_context():
    heads, _ = head_results()
    for malformed, weights in (({}, {}), ({"bad-name": heads["typed_json"]}, {"bad-name": 1.}),
                               ({"Typed": heads["typed_json"]}, {"Typed": 1.})):
        with pytest.raises(ValueError):
            subject.combine_multiteacher_losses(malformed, weights=weights)
    with torch.no_grad(), pytest.raises(ValueError):
        subject.combine_multiteacher_losses(heads, weights={"typed_json": 1., "legacy_formula": 1.})
