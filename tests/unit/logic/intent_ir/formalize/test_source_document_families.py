"""Source routing retains learned inference and requested typed family evidence."""
from pathlib import Path

import pytest

from .test_copy_roundtrip import checkpoint
from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document


def test_intent_family_mode_reuses_decoder_report_without_changing_candidates(checkpoint):
    options = dict(source_path='instruction.md', source_format='intent', intent_checkpoint=checkpoint[0])
    text = checkpoint[2][1]['instruction']
    baseline = prepare_source_document(text, **options)
    report = prepare_source_document(text, project_logic_families=True, **options)
    assert baseline['intent_family_projection'] is None
    assert baseline['intent'] == report['intent']
    assert baseline['candidates'] == report['candidates']
    assert report['counts']['intent_typed_fixtures'] == 1
    assert report['counts']['intent_logic_families'] == 11
    assert 'document_report' not in report['intent_family_projection']
    assert not report['whole_document_formalized'] and not report['source_semantics_verified']


def test_intent_family_route_counts_actual_lake_build_and_replayed_inference(checkpoint):
    executables = sorted((Path.home()/'.elan/toolchains').glob('*/bin/lake'))
    if not executables:
        pytest.skip('installed native Lake required')
    report = prepare_source_document(checkpoint[2][1]['instruction'], source_path='instruction.md',
        source_format='intent', intent_checkpoint=checkpoint[0], project_logic_families=True,
        lake_executable=str(executables[-1]))
    assert report['counts']['lake_attempts'] == report['counts']['lake_passes'] == 1
    assert report['counts']['intent_validation_inference_replays'] == 1
    assert report['counts']['intent_validation_encoder_executions'] >= 1
    assert report['intent_family_validation']['status'] == 'passed'
    assert not report['lake_checks'][0]['receipt']['claim_proved']


def test_family_route_without_checkpoint_cannot_fabricate_ir():
    report = prepare_source_document('The person must validate input.', source_path='instruction.md',
        source_format='intent', project_logic_families=True)
    assert report['counts']['intent_logic_families'] == report['counts']['intent_typed_fixtures'] == 0
    assert report['candidates'] == []


@pytest.mark.parametrize('options', [
    {'intent_family_context': {}}, {'requested_intent_families': ['dcec']},
    {'project_logic_families': True, 'source_format': 'code', 'intent_family_context': {}}])
def test_family_context_needs_correct_explicit_route(options):
    with pytest.raises(ValueError, match='Intent family context'):
        prepare_source_document('instruction', source_path='instruction.md',
            **{'source_format': 'intent', **options})
