"""Versioned source routing reaches learned productions, typed IR and projections."""
import hashlib

from .test_security_formula_decoder_v2 import expanded_checkpoint, parent_checkpoint
from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formula_source_units import (
    decode_security_source_units, validate_security_source_units)


SOURCE = 'def select(value, other):\n    return value if value > other else other\n'


def test_v2_document_routes_actual_model_to_typed_native_and_smt_views(expanded_checkpoint):
    report = prepare_source_document(SOURCE, source_path='example.py', source_format='code',
        language='python', security_checkpoint=expanded_checkpoint)
    assert report['counts']['security_typed_ir_candidates'] == 1
    assert report['counts']['security_program_candidates'] == 1
    assert report['counts']['security_logic_projections'] == 3
    assert report['counts']['security_neural_forwards'] == 2
    projection = report['security_regions'][0]['equations'][0]['projection']
    assert projection['decode']['validation']['source_AST_equivalent']
    assert projection['typed_ir']['result']['op'] == 'if'
    assert {p['family_id'] for p in projection['projections']} == {'program', 'smt'}
    assert all(p['bridge']['preservation'] == 'exact' and p['bridge']['status'] == 'ok'
               and not p['bridge']['losses'] and not p['bridge']['unsupported']
               for p in projection['projections'] if p['family_id'] == 'program')
    assert not report['source_semantics_verified'] and report['counts']['lake_attempts'] == 0


def test_v2_fenced_code_keeps_original_provenance_and_explicit_recovery(expanded_checkpoint):
    text = '# café\n\n```python\n' + SOURCE + '```\n'
    start = text.index('return')
    args = dict(source_path='guide.md', source_format='markdown', security_checkpoint=expanded_checkpoint,
                start_char=start, end_char=start+6)
    direct = prepare_source_document(text, **args)
    assert not direct['candidates']
    recovered = prepare_source_document(text, recover_context=True, **args)
    assert recovered['counts']['security_typed_ir_candidates'] == 1
    assert recovered['counts']['equation_candidates_using_recovered_context'] == 1
    item = recovered['candidates'][0]
    assert text.encode()[item['start_byte']:item['end_byte']] == SOURCE.rstrip().encode()
    assert item['typed_ir_available'] and item['context_recovered']


def test_v2_source_units_replay_and_model_ablation_preserve_no_fallback(expanded_checkpoint):
    raw = SOURCE.encode()
    args = dict(source_bytes=raw, source_sha256=hashlib.sha256(raw).hexdigest(),
                source_path='example.py', checkpoint=expanded_checkpoint)
    report = decode_security_source_units(**args)
    assert report['counts']['source_AST_equivalent_functions'] == 1
    assert validate_security_source_units(report, source_bytes=raw, checkpoint=expanded_checkpoint) == report
    for changes in ({'model_enabled':False}, {'weight_ablation':'zero_production_heads'}):
        denied = decode_security_source_units(**args, **changes)
        assert denied['counts']['source_AST_equivalent_functions'] == 0
        assert denied['counts']['learned_formula_count'] == 0


def test_v1_checkpoint_does_not_silently_receive_v2_grammar(parent_checkpoint):
    result = prepare_source_document(SOURCE, source_path='example.py', source_format='code',
        language='python', security_checkpoint=parent_checkpoint)
    assert result['counts']['security_typed_ir_candidates'] == 0
    assert result['counts']['security_equation_candidates'] == 0
    assert result['security_regions'][0]['report']['units'][0]['decode']['status'] == 'unsupported'


def test_security_backend_is_distinct_from_canonical_logic_family(expanded_checkpoint):
    report = prepare_source_document(SOURCE, source_path='example.py', source_format='code',
        language='python', security_checkpoint=expanded_checkpoint, project_logic_families=True)
    equation = report['security_regions'][0]['equations'][0]
    assert report['counts']['security_program_candidates'] == report['counts']['security_equation_candidates'] == 1
    assert {p['family_id'] for p in equation['family_views']} == {'program', 'first_order', 'higher_order'}
    assert any(p['backend'] == 'smt' and p['family_id'] == 'first_order' for p in equation['family_views'])
    assert any(p['backend'] == 'lean4' and p['family_id'] == 'higher_order' for p in equation['family_views'])
    assert all(not p['proof_authority'] for p in equation['family_views'])
    # The frozen versioned decoder output is not renamed or rewritten.
    assert {p['family_id'] for p in equation['projection']['projections']} == {'program', 'smt'}
