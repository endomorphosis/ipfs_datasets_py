"""Genuine grammar-search recovery and independently checked report contracts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_decoder as direct
from ipfs_datasets_py.logic.intent_ir.formalize import rich_search_decoder as searched
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar

SOURCE = 'Check availability across date range.'


@pytest.fixture(scope='module')
def checkpoint():
    import torch
    torch.set_num_threads(1)
    path = Path(__file__).resolve().parents[7] / 'artifacts/intent-rich-decoder-20261002/training-03/descriptor.json'
    if not path.is_file():
        pytest.skip('installed leaf continuation checkpoint required')
    result = json.loads(path.read_text())
    direct.load_rich_intent_checkpoint(result)
    return result


@pytest.fixture(scope='module')
def recovery(checkpoint):
    before = direct.prepare_rich_intent_instruction(SOURCE, checkpoint, beam_width=16)
    assert before['rich_ir'] is None
    after = searched.prepare_searched_rich_intent(SOURCE, checkpoint)
    assert after['status'] == 'source_supported_grammar_searched_candidate', after.get('reason')
    return before, after


def test_actual_search_repairs_inverse_without_repeating_encoder(recovery, checkpoint):
    before, after = recovery
    assert after['rich_ir']['ast'] == grammar.parse_instruction(SOURCE)
    assert after['encoder_candidate_origin'] == 'fresh_direct_search'
    assert after['encoder_search'] is None
    assert after['phase_counts']['grammar_search'] == {'encoder_executions': 0, 'decoder_executions': 1}
    assert after['counts']['encoder_executions'] == before['counts']['encoder_executions']
    assert after['counts']['decoder_executions'] == before['counts']['decoder_executions'] + 1
    weights = direct.load_rich_intent_checkpoint(checkpoint)['backend']['training']['final_state_sha256']
    assert after['learned']['encoder']['checkpoint_weights_sha256'] == weights
    assert after['learned']['decoder']['checkpoint_weights_sha256'] == weights
    assert after['learned']['decoder']['grammar_constraints_applied']
    assert not after['learned']['decoder']['probabilities_renormalized_after_grammar_mask']
    assert after['executed_here_counts'] == after['counts']
    assert not after['constraint_receives_source_or_expected_AST']
    assert not after['source_semantics_verified'] and not after['proof_authority']
    assert after['training_steps'] == after['llm_calls'] == 0


def test_actual_search_report_numerically_replays(recovery, checkpoint):
    assert searched.validate_searched_rich_intent(recovery[1], instruction=SOURCE, checkpoint=checkpoint) == recovery[1]


def test_forged_cached_metrics_rejected_by_complete_numerical_replay(recovery, checkpoint):
    before, _ = recovery
    forged = deepcopy(before)
    forged['counts']['encoder_executions'] += 1
    forged['report_sha256'] = direct.sha(direct.wire({k:v for k,v in forged.items() if k != 'report_sha256'}))
    # Cached failed stages cannot grant acceptance. Their diagnostic cost
    # remains untrusted until complete numerical replay, which rejects this.
    candidate = searched.prepare_searched_rich_intent(SOURCE, checkpoint, base_report=forged)
    with pytest.raises(ValueError, match='numerical replay'):
        searched.validate_searched_rich_intent(candidate, instruction=SOURCE, checkpoint=checkpoint)


def test_resigned_cached_prediction_cannot_replace_actual_forward_inference(checkpoint):
    instruction = 'Fetch the activation package.'
    base = direct.prepare_rich_intent_instruction(instruction, checkpoint, beam_width=16)
    assert base['rich_ir'] is None
    forged = deepcopy(base)
    ast = grammar.parse_instruction(instruction)
    forged['learned']['encoder']['generated_text'] = grammar.ast_to_sequence(ast)
    forged['report_sha256'] = direct.sha(direct.wire({k:v for k,v in forged.items() if k != 'report_sha256'}))
    result = searched.prepare_searched_rich_intent(instruction, checkpoint, base_report=forged)
    assert result['encoder_search'] is not None
    assert result['phase_counts']['grammar_search']['encoder_executions'] == 1
    assert result['cached_encoder_predictions_consumed'] is False
    assert result['rich_ir'] is None


@pytest.mark.parametrize('changed', [
    {'instruction_sha256': '0'*64}, {'beam_width': 8}, {'context': {}},
    {'checkpoint': {'schema':'incorrect'}}, {'counts': {'encoder_executions': True, 'decoder_executions': 2}},
])
def test_cached_stage_must_match_all_source_options(recovery, checkpoint, changed):
    before, _ = recovery
    forged = deepcopy(before)
    forged.update(changed)
    forged['report_sha256'] = direct.sha(direct.wire({k:v for k,v in forged.items() if k != 'report_sha256'}))
    with pytest.raises(ValueError):
        searched.prepare_searched_rich_intent(SOURCE, checkpoint, base_report=forged, beam_width=16)


@pytest.mark.parametrize('width', [True, 0, -1, 17, 1.5])
def test_search_options_are_bounded(width):
    with pytest.raises(ValueError):
        searched.prepare_searched_rich_intent(SOURCE, beam_width=width)


@pytest.mark.parametrize('instruction', ['inspect every file.', 'if it is ready, inspect cache.', 'inspect cache and update it.'])
def test_unsupported_source_does_not_reach_constrained_inference(instruction):
    report = searched.prepare_searched_rich_intent(instruction)
    assert report['rich_ir'] is None
    assert report['counts'] == {'encoder_executions': 0, 'decoder_executions': 0}


def test_missing_checkpoint_remains_fail_open():
    report = searched.prepare_searched_rich_intent(SOURCE)
    assert report['status'] == 'fail_open_no_checkpoint'
    assert report['continue_planning'] and report['raw_instruction_preserved']
    assert not report['rich_ir']
