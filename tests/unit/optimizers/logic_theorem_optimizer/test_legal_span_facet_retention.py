"""Numerical warm-start, resume and receipt checks for the new child runtime."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as previous
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as runtime

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_legal_span_consistency.py")))
rows_and_pairs = HELPERS["rows_and_pairs"]


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    before = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture(scope="module")
def parents():
    mixed = HELPERS["parent"].__wrapped__()
    rows, pairs = rows_and_pairs("consistency-parent")
    return {enabled: previous.train_decoder(previous.build_checkpoint(parent, rows, [], pairs,
        objective="consistency", seed=1729), rows, [], pairs, max_steps=2, max_seconds=30)["checkpoint"]
        for enabled, parent in mixed.items()}


def child(parent, objective="facet_retention"):
    rows, pairs = rows_and_pairs("facet-fit")
    return runtime.build_checkpoint(parent, rows, [], pairs, objective=objective, seed=1729)


@pytest.mark.parametrize("enabled", [False, True])
def test_exact_consistency_weights_inference_and_explicit_new_optimizer(parents, enabled):
    parent = parents[enabled]; checkpoint = child(parent)
    assert checkpoint["consistency_parent_checkpoint"] == parent
    assert checkpoint["model_state"] == parent["model_state"]
    assert checkpoint["optimizer_state"]["parameters"] == {}
    assert runtime.optimizer_steps(checkpoint) == 0 and checkpoint["consistency_parent_optimizer_steps"] == 2
    texts = [row["source_text"] for row in rows_and_pairs("probe")[0][-4:]]
    decoder = runtime.FacetRetentionDecoder(checkpoint)
    assert decoder.decode_formal_logic(texts)["rows"] == previous.ConsistencyDecoder(parent).decode_formal_logic(texts)["rows"]
    checkpoint["model_state"] = {}
    assert decoder.checkpoint["model_state"] == parent["model_state"]


@pytest.mark.parametrize("enabled", [False, True])
def test_staged_training_retains_exact_moments_order_and_numerical_results(parents, enabled):
    cp = child(parents[enabled]); rows, pairs = rows_and_pairs("facet-fit")
    full = runtime.train_decoder(cp, rows, [], pairs, max_steps=4, max_seconds=30)
    first = runtime.train_decoder(cp, rows, [], pairs, max_steps=2, max_seconds=30)
    second = runtime.train_decoder(first["checkpoint"], rows, [], pairs, max_steps=2, max_seconds=30)
    for key in ("model_state", "optimizer_state", "progress"):
        assert full["checkpoint"][key] == second["checkpoint"][key]
    for key in ("batch_losses", "batch_loss_components", "batch_exposures"):
        assert full["report"][key] == first["report"][key] + second["report"][key]
    assert runtime.optimizer_steps(second["checkpoint"]) == 4
    for row in full["report"]["batch_loss_components"]:
        assert row["total"] == pytest.approx(row["base_ce"] + .25 * row["consistency_js"] + .5 * row["teacher_kl"] + .1 * row["span_overlap"], abs=1e-6)
        assert 0 <= row['span_overlap'] <= 1 and 0 <= row['teacher_presence_terms'] <= 24
        assert 0 <= row['teacher_endpoint_terms'] <= 36 and 0 <= row['overlap_facet_pairs'] <= 180
    if not enabled:
        assert all(value == 0 for value in full["report"]["auxiliary_gradient_norm_max"].values())


def test_missing_trained_predecessor_hash_is_rejected(parents):
    cp = child(parents[True]); rows, pairs = rows_and_pairs("facet-fit")
    trained = runtime.train_decoder(cp, rows, [], pairs, max_steps=1, max_seconds=30)["checkpoint"]
    trained["parent_checkpoint_sha256"] = None
    with pytest.raises(ValueError, match="trained checkpoint lacks preceding hash"):
        runtime.validate_checkpoint(trained)


def test_manifest_pair_and_budget_changes_cannot_continue_checkpoint(parents):
    cp = child(parents[True]); rows, pairs = rows_and_pairs("facet-fit")
    with pytest.raises(ValueError, match="max_steps"):
        runtime.train_decoder(cp, rows, [], pairs, max_steps=801, max_seconds=30)
    changed = deepcopy(pairs); changed[0].reverse()
    with pytest.raises(ValueError, match="manifest"):
        runtime.train_decoder(cp, rows, [], changed, max_steps=1, max_seconds=30)
    bad = deepcopy(cp); bad["progress"]["optimizer_steps"] = 801
    with pytest.raises(ValueError, match="progress"):
        runtime.validate_checkpoint(bad)


def test_changed_parent_or_objective_and_inference_weights_are_rejected(parents):
    rows, pairs = rows_and_pairs("facet-fit")
    with pytest.raises(ValueError, match="known matched training objective"):
        runtime.build_checkpoint(parents[True], rows, [], pairs, objective="ce", seed=1729)
    cp = child(parents[True]); cp["consistency_parent_checkpoint_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="parent hash"):
        runtime.validate_checkpoint(cp)
    decoder = runtime.FacetRetentionDecoder(child(parents[True]))
    with torch.no_grad(): next(decoder.model.parameters()).add_(1)
    with pytest.raises(ValueError, match="model state changed"):
        decoder.decode_formal_logic([rows[0]["source_text"]])


def test_owned_checkpoint_file_roundtrip_preserves_exact_child_and_parent(parents, tmp_path):
    cp = child(parents[True]); reference = runtime.save_checkpoint(cp, tmp_path / "checkpoint.json")
    assert runtime.load_checkpoint(reference["path"], expected_sha256=reference["sha256"]) == cp
    with pytest.raises(FileExistsError): runtime.save_checkpoint(cp, tmp_path / "checkpoint.json")
    with pytest.raises(ValueError, match="hash"):
        runtime.load_checkpoint(reference["path"], expected_sha256="0" * 64)


@pytest.mark.parametrize('enabled', [False, True])
def test_base_arm_is_exact_frozen_consistency_loss_and_matched_schedule(parents, enabled):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_curriculum as prior_role
    rows, pairs = rows_and_pairs('facet-fit'); parent = parents[enabled]
    a = runtime.train_decoder(child(parent, 'base'), rows, [], pairs, max_steps=2, max_seconds=30)
    b = prior_role.train_decoder(prior_role.build_checkpoint(parent, rows, [], pairs,
        objective='consistency', seed=1729), rows, [], pairs, max_steps=2, max_seconds=30)
    c = runtime.train_decoder(child(parent), rows, [], pairs, max_steps=2, max_seconds=30)
    assert a['checkpoint']['model_state'] == b['checkpoint']['model_state']
    assert a['checkpoint']['optimizer_state'] == b['checkpoint']['optimizer_state']
    assert a['report']['batch_losses'] == b['report']['batch_losses']
    assert a['report']['batch_exposures'] == c['report']['batch_exposures']
    assert a['report']['teacher_state_unchanged'] and c['report']['teacher_gradients_disabled']
    assert all(r['weighted_teacher'] == r['weighted_overlap'] == 0 for r in a['report']['batch_loss_components'])


def fake_output(batch=1, tokens=3):
    return {'modality': torch.randn(batch, 3, requires_grad=True),
        'presence': torch.randn(batch, 4, 2, requires_grad=True),
        'start': torch.randn(batch, 6, tokens, requires_grad=True),
        'end': torch.randn(batch, 6, tokens, requires_grad=True)}


def teacher_fixture():
    student = fake_output(); teacher = fake_output()
    record = {'tokens': [0, 1, 2], 'labels': {'presence': [True, True, False, True, False, False],
        'spans': [(0, 0), (2, 2), (-100, -100), (1, 1), (-100, -100), (-100, -100)]}}
    with torch.no_grad():
        teacher['presence'][:] = torch.tensor([[[5., -5.], [-5., 5.], [5., -5.], [5., -5.]]])
        teacher['start'][0, 3] = torch.tensor([-5., 5., -5.])
        teacher['end'][0, 3] = torch.tensor([-5., 5., -5.])
    return student, teacher, record


def test_correct_facet_teacher_detached_and_student_receives_gradients():
    student, teacher, record = teacher_fixture()
    loss, parts = runtime._teacher_loss(torch, student, teacher, [record], (0,))
    assert parts['teacher_presence_terms'] == 4 and parts['teacher_endpoint_terms'] == 2
    loss.backward()
    assert student['presence'].grad.abs().sum() > 0 and student['start'].grad.abs().sum() > 0
    assert all(v.grad is None for v in teacher.values())


@pytest.mark.parametrize('error', ['wrong_presence', 'wrong_span', 'span_tie', 'presence_tie', 'absent'])
def test_ineligible_teacher_qualifier_endpoints_are_masked(error):
    student, teacher, record = teacher_fixture()
    with torch.no_grad():
        if error == 'wrong_presence': teacher['presence'][0, 1] = torch.tensor([5., -5.])
        elif error == 'wrong_span':
            teacher['start'][0, 3] = torch.tensor([5., -5., -5.]); teacher['end'][0, 3] = torch.tensor([5., -5., -5.])
        elif error == 'span_tie': teacher['start'][0, 3].zero_(); teacher['end'][0, 3].zero_()
        elif error == 'presence_tie': teacher['presence'][0, 1].zero_()
        else:
            record['labels']['presence'][3] = False; record['labels']['spans'][3] = (-100, -100)
            teacher['presence'][0, 1] = torch.tensor([5., -5.])
    loss, parts = runtime._teacher_loss(torch, student, teacher, [record], (0,))
    assert parts['teacher_endpoint_terms'] == 0
    loss.backward()
    assert student['start'].grad is None and student['end'].grad is None
    assert all(v.grad is None for v in teacher.values())


def test_empty_teacher_masks_produce_finite_differentiable_zero():
    student, teacher, record = teacher_fixture()
    with torch.no_grad(): teacher['presence'].zero_()
    loss, parts = runtime._teacher_loss(torch, student, teacher, [record], (0,))
    assert loss == 0 and torch.isfinite(loss)
    assert parts['teacher_presence_terms'] == parts['teacher_endpoint_terms'] == 0
    loss.backward()


def test_no_new_pair_teacher_distillation():
    student, teacher = fake_output(12), fake_output(12)
    _, _, row = teacher_fixture(); records = [deepcopy(row) for _ in range(12)]
    a, counts = runtime._teacher_loss(torch, student, teacher, records)
    with torch.no_grad():
        for key in teacher: teacher[key][6:] = torch.randn_like(teacher[key][6:]) * 100
    b, changed_counts = runtime._teacher_loss(torch, student, teacher, records)
    assert a == b and counts == changed_counts


def test_overlap_probability_matches_bruteforce_complete_valid_span_space():
    torch.manual_seed(917)
    left = runtime._valid_span_distribution(torch, torch.randn(4), torch.randn(4))
    right = runtime._valid_span_distribution(torch, torch.randn(4), torch.randn(4))
    brute = sum(left[a, b] * right[c, d] for a in range(4) for b in range(a, 4)
        for c in range(4) for d in range(c, 4) if max(a, c) <= min(b, d))
    assert runtime._pair_overlap_probability(left, right) == pytest.approx(float(brute), abs=1e-6)
    assert runtime._pair_overlap_probability(right, left) == pytest.approx(float(brute), abs=1e-6)


def test_invalid_reverse_span_mass_cannot_escape_and_overlap_has_gradient():
    start = torch.tensor([-20., -20., 20.], requires_grad=True)
    end = torch.tensor([20., -20., -20.], requires_grad=True)
    joint = runtime._valid_span_distribution(torch, start, end)
    assert float(joint.sum().detach()) == pytest.approx(1.) and joint[2, 0] == 0
    overlap = runtime._pair_overlap_probability(joint, joint)
    assert 0 <= overlap <= 1
    overlap.backward()
    assert start.grad.abs().sum() > 0 and end.grad.abs().sum() > 0


def test_overlap_uses_gold_presence_not_student_absence_and_empty_pairs_zero():
    student, _, record = teacher_fixture()
    a, terms = runtime._overlap_loss(torch, student, [record])
    with torch.no_grad(): student['presence'][:] = torch.tensor([100., -100.])
    b, same = runtime._overlap_loss(torch, student, [record])
    assert a == b and terms == same and terms['overlap_facet_pairs'] == 3
    record['labels']['presence'] = [True, False, False, False, False, False]
    zero, terms = runtime._overlap_loss(torch, student, [record])
    assert zero == 0 and terms['overlap_facet_pairs'] == 0 and torch.isfinite(zero)
