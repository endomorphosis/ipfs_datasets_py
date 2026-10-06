"""Occurrence transport, integrity and zero-admission boundaries."""
from copy import deepcopy
from hashlib import sha256

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_proposal as adapter
from ipfs_datasets_py.logic.legal_ir import canonical_statement_scope as scope

SOURCE = 'The Régisseur shall submit notice if notice arrives.'


def occurrence(text, start=0):
    at = SOURCE.index(text, start)
    return [at, at + len(text)]


def prediction(attachment='rule', *, with_object=True, with_condition=True):
    return {'schema': adapter.PREDICTION_SCHEMA, 'interpretation_profile': adapter.INTERPRETATION_PROFILE,
        'modality': 'O', 'spans': {'modality': occurrence('shall'), 'actor': occurrence('Régisseur'),
            'action': occurrence('submit'), 'object': occurrence('notice') if with_object else None,
            'condition': occurrence('notice arrives') if with_condition else None},
        'condition_attachment': attachment if with_condition else None}


def propose(value=None, text=SOURCE, expected=None):
    return adapter.propose_scope_from_spans(text, value if value is not None else prediction(),
        expected_source_sha256=expected if expected is not None else sha256(text.encode()).hexdigest())


@pytest.mark.parametrize('attachment', ['rule', 'statement'])
@pytest.mark.parametrize('with_object', [False, True])
@pytest.mark.parametrize('with_condition', [False, True])
def test_declared_spans_reuse_exact_scope_owner_and_keep_all_masks_zero(attachment, with_object, with_condition):
    value = prediction(attachment, with_object=with_object, with_condition=with_condition)
    result = propose(value)
    declaration = result['declaration']
    checked = scope.validate_scope_declaration(declaration['input'], declaration,
        expected_input_sha256=declaration['input_sha256'])
    assert checked == result['validation']
    assert declaration['schema'] == scope.SCHEMA and declaration['binders'] == []
    assert result['masks'] == dict.fromkeys(scope.MASKS, 0)
    assert declaration['coverage'] == {'declared_status': 'unassessed', 'segments': []}
    assert declaration['input']['context']['role'] == 'required_unavailable'
    assert declaration['unresolved'][0]['span']['text'] == SOURCE
    expected_structure = 'attach' if with_condition and attachment == 'statement' else 'rule'
    assert declaration['statement_structure']['op'] == expected_structure
    assert (declaration['rules'][0]['qualifiers']['conditions'] is not None) == (with_condition and attachment == 'rule')
    for item in declaration['occurrences']:
        anchor = item['anchor']
        assert SOURCE[anchor['start']:anchor['end']] == anchor['text']
        assert anchor['offset_unit'] == 'unicode_character_half_open'
    for flag in ('qualified', 'accepted', 'formalized', 'proof_ready', 'source_semantics_verified',
                 'model_executed', 'training_executed', 'target_access', 'source_coverage_assessed', 'context_resolved',
                 'source_fidelity_established', 'semantic_equivalence_assessed', 'proof_authority',
                 'lowering_authorized', 'normalization_approved', 'binder_terms_typechecked'):
        assert result[flag] is False
    assert result['formal_output'] is None and result['model_calls'] == result['prover_calls'] == 0


def test_repeated_equal_text_keeps_explicit_occurrence_coordinates():
    value = prediction()
    value['spans']['condition'] = occurrence('notice', occurrence('notice')[1])
    declaration = propose(value)['declaration']
    selected = [o for o in declaration['occurrences'] if o['facet'] in {'object', 'conditions'}]
    assert len(selected) == 2 and selected[0]['canonical_symbol'] == selected[1]['canonical_symbol'] == 'notice'
    assert selected[0]['occurrence_id'] != selected[1]['occurrence_id']
    assert selected[0]['anchor']['start'] != selected[1]['anchor']['start']


@pytest.mark.parametrize('modality', ['O', 'P', 'F'])
def test_modality_is_an_unreviewed_declaration_not_a_keyword_inference(modality):
    value = prediction(); value['modality'] = modality
    result = propose(value)
    item = next(o for o in result['declaration']['occurrences'] if o['facet'] == 'modality')
    assert item['canonical_symbol'] == modality and item['anchor']['text'] == 'shall'
    assert result['source_semantics_verified'] is False and all(v == 0 for v in result['masks'].values())


@pytest.mark.parametrize('facet,bad', [('actor', [True, 12]), ('actor', (4, 13)),
    ('actor', [-1, 13]), ('actor', [4, 99999]), ('actor', [5, 13]),
    ('action', None), ('modality', 'shall'), ('condition', []), ('object', [2.0, 3.0])])
def test_invalid_or_unanchored_occurrences_reject_without_repair(facet, bad):
    value = prediction(); value['spans'][facet] = bad
    with pytest.raises(ValueError):
        propose(value)


def test_overlap_digest_mismatch_and_stale_source_reject():
    value = prediction(); value['spans']['condition'] = value['spans']['object'].copy()
    with pytest.raises(ValueError, match='overlap'):
        propose(value)
    with pytest.raises(ValueError, match='digest'):
        propose(expected='0' * 64)
    with pytest.raises(ValueError, match='digest'):
        propose(text=SOURCE + '!', expected=sha256(SOURCE.encode()).hexdigest())


@pytest.mark.parametrize('location,extra', [('prediction', 'target'), ('prediction', 'formalized'),
    ('spans', 'exceptions'), ('spans', 'source_labels')])
def test_closed_schema_rejects_labels_extra_facets_and_authority(location, extra):
    value = prediction()
    (value if location == 'prediction' else value['spans'])[extra] = True
    with pytest.raises(ValueError, match='closed'):
        propose(value)


@pytest.mark.parametrize('present,attachment', [(False, 'rule'), (True, None), (True, 'guess')])
def test_condition_attachment_is_required_and_never_guessed(present, attachment):
    value = prediction(with_condition=present); value['condition_attachment'] = attachment
    with pytest.raises(ValueError, match='attachment'):
        propose(value)


@pytest.mark.parametrize('text', ['', '   ', 'bad\x00source', '\ud800', 'x' * 8193])
def test_source_bounds_and_utf8_reject(text):
    with pytest.raises(ValueError):
        adapter.propose_scope_from_spans(text, prediction(), expected_source_sha256='0' * 64)


def test_parser_teacher_and_family_exporters_are_not_consulted(monkeypatch):
    import importlib
    import sys
    from ipfs_datasets_py.logic.deontic.utils import deontic_parser

    def forbidden(*args, **kwargs):
        raise AssertionError('Parser or teacher used to fill an occurrence')

    for name in ('extract_normative_elements', 'analyze_normative_sentence', 'classify_modal'):
        monkeypatch.setattr(deontic_parser, name, forbidden)
        with pytest.raises(AssertionError):
            getattr(deontic_parser, name)()
    module = 'ipfs_datasets_py.logic.autoformal.family_qualification'
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)
    assert propose()['validation']['status'] == 'validated_scope_transport_only'


def test_mutable_wire_copies_do_not_change_later_proposals():
    value = prediction(); before = deepcopy(value)
    first = propose(value); first['declaration']['occurrences'].clear()
    assert value == before
    assert propose(value)['declaration']['occurrences']
