"""New authored evaluation wording and explicit all-prior literal exclusions."""
from collections import Counter
from copy import deepcopy
import json
import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import authored_modality_holdout_v3 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import fresh_scalar_source_inputs as source
from .test_authored_modality_holdout_v2 import inputs as old_inputs

def inputs():
    args=old_inputs();args['family_roles']['exposed']+=args['family_roles']['evaluation']
    args['family_roles']['evaluation']=list(subject.FAMILIES)
    return args

@pytest.mark.parametrize('family',subject.FAMILIES)
@pytest.mark.parametrize('modality',subject.MODALITIES)
def test_explicit_normative_morphology(family,modality):
    text=subject._sentence(family,'registrar','approve','notice',modality)
    assert text.endswith('.') and 'registrar' in text and 'notice' in text
    expected={'O':['obligated','obligation'],'P':['authorized','permission'],'F':['barred','prohibition','prohibited']}[modality]
    assert any(word in text.lower() for word in expected)

def test_balanced_closed_source_reference_inventory_and_no_prior_change():
    args=inputs();before=deepcopy(args);value=subject.build_holdout(**args)
    assert args==before and len(value['source_rows'])==len(value['references'])==48
    assert Counter(r['clause_count'] for r in value['references'])=={1:12,2:12,4:12,8:12}
    assert len({text for row in value['source_rows'] for text in row['source_text'].split('\n\n')})==180
    for row,ref in zip(value['source_rows'],value['references']):
        assert set(row)=={'id','source_text'} and ref['source_text']==row['source_text']
        assert json.loads(''.join(subject.VOCABULARY[i] for i in ref['target_ids'][1:-1]))==ref['target']
        assert len(ref['target_ids'])<=512
        for text,rule in zip(row['source_text'].split('\n\n'),ref['target']['rules']):
            assert text==subject._sentence(ref['template_family'],rule['actor'],rule['action'],rule['object'],rule['modality'])
    plan=source.source_plan(value['source_rows'],expected_source_rows_sha256=value['receipt']['source_rows_sha256'],sealed_comparison_sha256='a'*64)
    assert plan['unique_sources']==216 and plan['target_access'] is False
    assert all(value['receipt'][k] is False for k in subject.FALSE)

@pytest.mark.parametrize('split',['train','validation','test','canary','exposed_r6','exposed_r8'])
def test_every_prior_inventory_rejects_matching_clause(split):
    args=inputs();row=subject.build_holdout(**args)['source_rows'][0]
    args['prior_sources_by_dataset'].setdefault(split,[]).append(dict(id='collision',source_text=row['source_text'].split('\n\n')[0]))
    with pytest.raises(ValueError,match='overlaps prior blacklist'):subject.build_holdout(**args)

def test_missing_full_vocabulary_or_overlapping_family_fails_closed():
    args=inputs();args['codec']['target_vocabulary'].pop()
    with pytest.raises(ValueError):subject.build_holdout(**args)
    args=inputs();args['family_roles']['training'].append(subject.FAMILIES[0])
    with pytest.raises(ValueError):subject.build_holdout(**args)
