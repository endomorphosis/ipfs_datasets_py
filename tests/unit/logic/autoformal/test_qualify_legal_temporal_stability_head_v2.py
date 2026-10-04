"""Narrow postrelease corpus-digest correction retains the old replay boundary."""
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from scripts.ops.legal_ir import qualify_legal_temporal_stability_head_v2 as q


def test_unicode_corpus_rows_have_utf8_commitment_without_changing_runtime_digest():
    rows=[{'source_text':'Rule 731.— Registry shall file.','annotation':{'text':'“α”'}}]
    expected=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,separators=(',', ':')).encode('utf-8')).hexdigest()
    assert q.corpus_rows_digest(rows)==expected==q.corpus.digest(rows)
    assert q.digest(rows)==q.original.digest(rows)!=expected


def test_ascii_rows_keep_identical_commitment():
    rows=[{'source_text':'Registry shall file.','nested':[False,None,17]}]
    assert q.corpus_rows_digest(rows)==q.digest(rows)


@pytest.mark.parametrize('mutate',[
    lambda rows:rows[0].update(source_text='Heading— changed.'),
    lambda rows:rows[0]['annotation'].update(char_start=2),
    lambda rows:rows.reverse(),
])
def test_utf8_commitment_still_binds_exact_text_offsets_and_order(mutate):
    rows=[{'source_text':'Heading— unchanged.','annotation':{'char_start':1}}, {'id':'second'}]
    before=q.corpus_rows_digest(rows);mutate(rows)
    assert q.corpus_rows_digest(rows)!=before


def test_nonfinite_annotation_values_remain_rejected():
    with pytest.raises(ValueError):q.corpus_rows_digest([{'value':float('nan')}])


def test_exposure_function_changes_only_the_explicit_corpus_row_digest():
    before=inspect.getsource(q.original.exposure_audit)
    expected=before.replace("'rows_sha256':digest(rows)","'rows_sha256':corpus_rows_digest(rows)")
    assert before!=expected
    assert ast.dump(ast.parse(inspect.getsource(q.exposure_audit)),include_attributes=False)==ast.dump(ast.parse(expected),include_attributes=False)


def test_original_replay_inventory_and_selection_are_reused_exactly():
    assert q.check_replay is q.original.check_replay
    assert q.inventory is q.original.inventory
    assert q.score_admitted is q.original.score_admitted
    assert q.body_layout is q.original.body_layout
    assert not hasattr(q,'replay')


@pytest.fixture
def correction(tmp_path):
    def save(name,value):return q.write(tmp_path/(name+'.json'),value)
    original_freeze=save('original-freeze',{'source':q.reference(q.original.__file__),
        'producer_files':q.original.producer_pins(),'tests':q.reference(__file__)})
    gen=save('generation',{});replay=save('replay',{});note=save('note',{})
    value={'schema':'legal-temporal-stability-corpus-digest-correction/v1',
        'verification_change':'historical_corpus_rows_sha256_uses_utf8_json',
        'neural_replay_reused_without_reexecution':True,'training_model_selection_and_gates_changed':False,
        'correction_made_after_authorized_reference_release':True,'fresh_reference_release_already_authorized':True,
        'generation_freeze':gen,'original_numerical_replay':replay,'original_implementation_freeze':original_freeze,
        'corrected_source':q.reference(q.__file__),'corrected_producer_files':q.producer_pins(),'corrected_tests':q.reference(__file__),
        **{key:note for key in ('failed_score_log','encoding_diagnosis','focused_test_xml','focused_test_log')}}
    return value,gen,replay,save


def test_versioned_correction_binds_both_source_closures_and_original_evidence(correction):
    value,gen,replay,save=correction;pin=save('correction',value)
    assert q.verify_correction(gen['path'],replay['path'],pin['path'])==pin


@pytest.mark.parametrize('mutation',[
    lambda v:v.update(verification_change='relax_retention_gates'),
    lambda v:v.update(training_model_selection_and_gates_changed=True),
    lambda v:v.update(correction_made_after_authorized_reference_release=False),
    lambda v:v.update(neural_replay_reused_without_reexecution=False),
    lambda v:v['original_numerical_replay'].update(sha256='0'*64),
    lambda v:v['corrected_source'].update(sha256='0'*64),
    lambda v:v['corrected_producer_files'].pop(),
])
def test_repaired_outer_pin_cannot_hide_invalid_correction_scope_or_provenance(correction,mutation):
    value,gen,replay,save=correction;value=deepcopy(value);mutation(value);pin=save('correction',value)
    with pytest.raises(ValueError):q.verify_correction(gen['path'],replay['path'],pin['path'])


def test_correction_failure_precedes_any_data_or_reference_loader(correction,monkeypatch,tmp_path):
    value,gen,replay,save=correction;value['training_model_selection_and_gates_changed']=True;pin=save('correction',value)
    monkeypatch.setattr(q,'load_inputs',lambda *a:pytest.fail('loader reached before correction validation'))
    with pytest.raises(ValueError):q.score(gen['path'],replay['path'],tmp_path/'scores.json',pin['path'])
    assert not (tmp_path/'scores.json').exists()
