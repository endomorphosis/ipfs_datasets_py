from copy import deepcopy
import pytest

from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as subject
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as experiment


def source(text):
    return {"candidate_id": "boundary-fixture", "source_text": text, "source_sha256": subject.text_sha(text)}


def test_complete_nonwhite_coverage_preserves_three_occurrences_including_duplicate():
    first, second = "Fixture Board must retain reports.", "Fixture Council may publish notices."
    text = first + "\n" + second + "  " + first
    tokens = subject.tokenize(text)
    ends = [i for i, t in enumerate(tokens) if t["text"] == "."]
    plan = subject.source_plan(source(text), tokens, ends)
    assert plan["clause_count"] == 3
    assert [r["source_text"] for r in plan["clauses"]] == [first, second, first]
    assert plan["clauses"][0]["source_sha256"] == plan["clauses"][2]["source_sha256"]
    assert plan["clauses"][0]["clause_id"] != plan["clauses"][2]["clause_id"]
    assert plan["coverage"] == "all_non_whitespace_source_characters_accounted_for"


@pytest.mark.parametrize("ends", [[3], [7, 7], [7, 3], [-1, 7], []])
def test_rejects_missing_terminal_duplicate_reordered_or_negative_boundaries(ends):
    text = "One must retain reports. Two may publish notices."
    with pytest.raises(ValueError):
        subject.source_plan(source(text), subject.tokenize(text), ends)


def test_original_unicode_offsets_and_abbreviation_tokens_are_retained():
    text = "  Élan Dept. must retain records under section 19.7.\nΩmega Board may publish notices. "
    tokens = subject.tokenize(text)
    first_end = text.index(".\n") + 1
    ends = [i for i, row in enumerate(tokens) if row['char_end'] in (first_end, len(text.rstrip()))]
    plan = subject.source_plan(source(text), tokens, ends)
    assert [row['source_text'] for row in plan['clauses']] == [text[2:first_end], text[first_end + 1:].strip()]
    assert len([t for t in tokens if t['text'] == '.']) > len(ends)


def test_plan_rejects_replaced_token_offsets_even_with_same_text():
    text = "Fixture Board must retain reports."
    tokens = subject.tokenize(text)
    tokens[0]['char_start'] += 1
    with pytest.raises(ValueError, match='coordinates'):
        subject.source_plan(source(text), tokens, [len(tokens) - 1])


@pytest.fixture(scope='module')
def checkpoint():
    import torch
    torch.set_num_threads(1); torch.manual_seed(subject.CONFIG['seed'])
    return subject.checkpoint(subject.model(torch), steps=0,
        training_manifest_sha256='a' * 64, tuning_manifest_sha256='b' * 64)


def test_decode_rejects_reference_field_and_invalid_profile(checkpoint):
    decoder = subject.ClauseBoundaryDecoder(checkpoint)
    row = source("Fixture Board must retain reports.")
    with pytest.raises(ValueError, match='closed source-only'):
        decoder.decode([{**row, 'clauses': []}])
    with pytest.raises(ValueError, match='profile'):
        decoder.decode([row], source_profile='nested-shared-scope')


def test_declared_unsupported_scope_abstains_without_partial_document(checkpoint):
    decoder = subject.ClauseBoundaryDecoder(checkpoint)
    result = decoder.decode([source("Both following rules apply: Fixture Board must retain reports. Fixture Council may publish notices.")])
    row = result['rows'][0]
    assert row['status'] == 'abstained' and row['plan'] is None
    assert row['reason'] == 'declared_surface_policy_unsupported_scope'
    assert row['independent_scope_verified'] is False


def test_checkpoint_validation_rejects_tensor_shape_and_source_contract_corruption(checkpoint):
    changed = deepcopy(checkpoint)
    changed['model_state']['boundary.bias'].append(0.)
    with pytest.raises(ValueError, match='tensor shape'):
        subject.restore(changed)
    changed = deepcopy(checkpoint); changed['implementation_sha256'] = 'c' * 64
    with pytest.raises(ValueError, match='producer'):
        subject.restore(changed)


def test_fresh_model_roundtrip_replays_actual_logits_and_receipts(checkpoint):
    rows = [source("Fixture Board must retain reports. Fixture Council may publish notices.")]
    first = subject.ClauseBoundaryDecoder(checkpoint).decode(rows)
    second = subject.ClauseBoundaryDecoder(deepcopy(checkpoint)).decode(rows)
    assert first == second and len(first['rows'][0]['boundary_logits']) == len(subject.tokenize(rows[0]['source_text']))


def test_one_real_optimizer_step_updates_boundary_encoder_and_scope_heads():
    import torch
    torch.set_num_threads(1); torch.manual_seed(subject.CONFIG['seed'])
    network = subject.model(torch)
    initial = {k: v.detach().clone() for k, v in network.state_dict().items()}
    rows = [experiment.authored_document('train', i) for i in range(8)]
    ids, features, lengths, labels, scopes, mask = subject.tensor_batch(torch, rows, labels=True)
    boundaries, scope = network(ids, features, lengths)
    eligible = mask & scopes.bool()[:, None]
    loss = torch.nn.functional.binary_cross_entropy_with_logits(boundaries[eligible], labels[eligible]) + torch.nn.functional.cross_entropy(scope, scopes)
    optimizer = torch.optim.Adam(network.parameters(), lr=.01)
    loss.backward(); optimizer.step()
    for name in ('encoder.weight_ih_l0', 'boundary.weight', 'scope.weight'):
        assert not torch.equal(initial[name], network.state_dict()[name])


def test_new_corpus_sources_and_construction_families_are_disjoint_from_fixtures():
    splits = {name: [experiment.authored_document(name, i) for i in range(count)] for name, count in experiment.SPLIT_COUNTS.items()}
    fixtures = [{'source_text': 'Unit Fixture Council must retain reports.'}]
    result = experiment.validate_corpus(splits, fixtures)
    assert result['source_hashes_disjoint'] and result['construction_families_disjoint'] and result['fixture_sources_disjoint']
    with pytest.raises(ValueError, match='fixtures overlap'):
        experiment.validate_corpus(splits, [{'source_text': splits['test'][0]['source_text']}])
    splits['test'][0] = deepcopy(splits['train'][0])
    with pytest.raises(ValueError, match='crossed split'):
        experiment.validate_corpus(splits, fixtures)


def test_punctuation_baseline_scores_internal_abbreviations_as_false_boundaries():
    row = experiment.authored_document('test', 0)
    measured = experiment.punctuation_baseline([row])
    assert measured['supported_documents'] == 1
    assert measured['false_positive'] > 0 and measured['boundary_document_exact'] == 0


def test_metrics_keep_supported_abstention_in_boundary_and_document_denominators(checkpoint):
    row = experiment.authored_document('test', 0)
    prediction = subject.ClauseBoundaryDecoder(checkpoint).decode(experiment.source_rows([row]))
    prediction['rows'][0].update(status='abstained', plan=None, reason='learned_scope_abstention', boundary_token_indices=[], predicted_rule_count=0)
    measured = experiment.evaluate(prediction, [row])
    assert measured['documents'] == measured['supported_documents'] == measured['abstained'] == 1
    assert measured['exact_supported_segmentation'] == measured['raw_boundary_document_exact'] == 0
    assert measured['raw_boundary_false_negative'] == len(row['clauses'])
