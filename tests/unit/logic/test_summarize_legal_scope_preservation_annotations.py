"""Pure annotation fixtures use current admitted tuning and fictional old TRAIN.

No current fresh renderer, target, pair, ledger or exposure file is read.
"""
from copy import deepcopy
from pathlib import Path
import random
import pytest
from scripts.ops.legal_ir import prepare_legal_scope_preservation_corpus as corpus
from scripts.ops.legal_ir import summarize_legal_scope_preservation_annotations as audit
# Initialize the legacy validator before the pure-call no-I/O assertion.
from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs


def rename(value):
    if isinstance(value,dict):return {k:rename(v) for k,v in value.items()}
    if isinstance(value,list):return [rename(v) for v in value]
    if isinstance(value,str):return value.replace('Mapleharbor','Novelharbor').replace('mapleharbor','novelharbor')
    return value


def fictional_pair(case):
    rows,pair,labels=[rename(v) for v in corpus.adapter.make_pair('train',case)]
    group='case-'+corpus.sha(('fictional-preservation/'+pair['case_group']).encode())
    remap={}
    for row,a in zip(rows,labels,strict=True):
        old=row['candidate_id'];row['source_sha256']=corpus.sha(row['source_text'].encode())
        row['candidate_id']='scope-'+row['source_sha256'];remap[old]=row['candidate_id']
        a.update(candidate_id=row['candidate_id'],source_sha256=row['source_sha256'],panel='fresh',case_group=group)
        for o in a['local_clause_coordinates']:o['source_sha256']=corpus.sha(o['source_text'].encode())
    pair.update(pair_id='pair-'+corpus.sha(group.encode()),case_group=group,
        independent_id=remap[pair['independent_id']],nested_id=remap[pair['nested_id']],
        local_clause_body_sha256=[o['source_sha256'] for o in labels[0]['local_clause_coordinates']])
    return rows,pair,labels


@pytest.fixture(scope='module')
def bundle():
    panels,pairs,annotations={}, {}, []
    fictional_cases=[i for i,f in enumerate(corpus.adapter.factor_schedule('train'))
        if (f['first_CE_mask']+list(corpus.HEADINGS).index(f['heading'])+corpus.TIME_KINDS.index(f['child_time_kind'])
            +'OPF'.index(f['first_modality'])+f['clause_count'])%2==0]
    assert len(fictional_cases)==96
    for panel,cases in (('tuning',range(48)),('fresh',fictional_cases)):
        panels[panel],pairs[panel]=[],[]
        for case in cases:
            rows,pair,labels=corpus.make_pair('tuning',case) if panel=='tuning' else fictional_pair(case)
            panels[panel].extend(rows);pairs[panel].append(pair);annotations.extend(labels)
        random.Random(corpus.SHUFFLE_SEED+list(corpus.COUNTS).index(panel)).shuffle(panels[panel])
    ledger={'schema':'legal-scope-preservation-annotations/v1','document_rows':annotations}
    history=corpus.historical_inventory()
    old_adapter=history['prior_adapter_manifest'];old_config=corpus.read_ref(history['prior_adapter_config_ref'])
    old_scope=corpus.read_ref(old_adapter['inputs']['prior_scope_corpus'])
    old_condition=corpus.read_ref(old_adapter['inputs']['prior_condition_corpus'])
    exposure=corpus.exposure_payload(history,panels,ledger)
    parent_pairs=corpus.read_ref(old_adapter['artifacts']['training_pairs'])
    manifest={'schema':corpus.SCHEMA,'training_reused_without_changes':True,'new_training_documents':0,'training_documents':1152,
        'inputs':{'prior_adapter_corpus':history['prior_adapter_manifest_ref']},
        'artifacts':history['training_references'],'replay_references':history['replay_references'],
        'retention_target_references':history['retention_target_references']}
    inputs={'manifest':manifest,'new_train':history['pools']['prior_adapter_train'],'training_pairs':parent_pairs,
        'replay':{name:history['pools'][name] for name in history['replay_references']},
        'tuning_pairs':pairs['tuning'],
        'tuning':{**{name:corpus.read_ref(pin) for name,pin in history['retention_target_references'].items()},'scope_new':panels['tuning']},
        'sources':{'scope_fresh':[corpus.source_row(r) for r in panels['fresh']]}}
    kwargs={'historical_documents':{name:{'reference':pin,'rows':history['pools'][name]} for name,pin in history['document_references'].items()},
        'prior_annotation_ledgers':{
            'prior_scope':{'reference':history['prior_scope_annotation_reference'],'ledger':corpus.read_ref(history['prior_scope_annotation_reference'])},
            'prior_adapter':{'reference':history['prior_adapter_annotation_reference'],'ledger':corpus.read_ref(history['prior_adapter_annotation_reference'])}},
        'historical_source_inventory':{'source_texts':sorted(history['excluded_sources']),
            'prior_source_references':history['prior_source_references'],'condition_single_references':history['condition_single_references'],
            'real_exposed_views':86},
        'historical_manifests':{'prior_scope':old_scope,'prior_condition':old_condition,'prior_adapter':old_adapter,'prior_adapter_config':old_config},
        'prior_training_pairs':{'reference':old_adapter['artifacts']['training_pairs'],'rows':parent_pairs}}
    return (inputs,panels['fresh'],pairs['fresh'],ledger,exposure),kwargs


def test_new288_evaluation_pairs_and_reused1152_train_independently_verified_without_io(bundle,monkeypatch):
    args,kwargs=bundle
    def forbidden(*args,**kwargs):raise AssertionError('pure helper opened a file')
    monkeypatch.setattr(Path,'open',forbidden)
    result=audit.audit_scope_annotations(*args,**kwargs)
    assert result['new_evaluation_documents']==288 and result['new_scope_pairs']==144
    assert result['unchanged_training_documents']==1152 and result['unchanged_training_pairs']==192
    assert result['prior_training_content_order_and_reference_binding_verified']
    assert result['panels']['fresh']['heading_literals']=={'dash':96,'period_bracket':96}
    assert result['fresh_matching_reused_training_layout']==192
    assert result['historical_layout_counts']['prior_adapter_fresh']==192
    assert not result['helper_opens_files'] and not result['statutory_gold_available']


@pytest.mark.parametrize('change',['train_order','train_pair_order','train_pin','replay_order','retention_drop','retention_order',
    'missing_annotation','class_id','pair_case','heading','time_position','role_atom','scope_attachment','flatten_nested',
    'fresh_source_order','source_metadata','layout','layout_pool','old_annotation','old_reference','history_source_omission',
    'history_source_commitment','overlap_claim','new_train_claim'])
def test_training_preservation_source_coordinates_and_exposure_tampering_rejected(bundle,change):
    args,kwargs=deepcopy(bundle);inputs,targets,pairs,ledger,exposure=args
    # deepcopy preserves aliases; separate intentionally for adversarial caller mutation.
    inputs=deepcopy(inputs);args=(inputs,targets,pairs,ledger,exposure)
    lookup={a['candidate_id']:a for a in ledger['document_rows']}
    row=next(r for r in targets if r['supported'] and lookup[r['candidate_id']]['factors']['child_time_kind']=='hours')
    a=lookup[row['candidate_id']];child=a['local_clause_coordinates'][1]
    if change=='train_order':inputs['new_train'].reverse()
    elif change=='train_pair_order':inputs['training_pairs'].reverse()
    elif change=='train_pin':inputs['manifest']['artifacts']['new_training_targets']['sha256']='0'*64
    elif change=='replay_order':inputs['replay']['original'].reverse()
    elif change=='retention_drop':del inputs['tuning']['prior_adapter_fresh']
    elif change=='retention_order':inputs['tuning']['prior_adapter_tuning'].reverse()
    elif change=='missing_annotation':ledger['document_rows'].pop()
    elif change=='class_id':targets[0]['candidate_id']+='-nested'
    elif change=='pair_case':a['case_group']='other'
    elif change=='heading':a['factors']['heading']=next(k for k in corpus.HEADINGS if k!=a['family'])
    elif change=='time_position':child['facet_spans']['temporal'][0]+=1
    elif change=='role_atom':child['rule']['actor']='Another actor'
    elif change=='scope_attachment':
        negative=next(r for r in targets if not r['supported']);lookup[negative['candidate_id']]['scope_attachment']['child_occurrence']=0
    elif change=='flatten_nested':next(r for r in targets if not r['supported'])['clauses']=deepcopy(row['clauses'])
    elif change=='fresh_source_order':inputs['sources']['scope_fresh'].reverse()
    elif change=='source_metadata':inputs['sources']['scope_fresh'][0]['supported']=True
    elif change=='layout':exposure['rows'][0]['role_masked_layout']+='invented'
    elif change=='layout_pool':exposure['rows'][0]['matching_pools']=[]
    elif change=='old_annotation':kwargs['prior_annotation_ledgers']['prior_adapter']['ledger']['document_rows'][0]['local_clause_coordinates'][0]['facet_spans']['actor'][0]+=1
    elif change=='old_reference':exposure['historical_document_references']['prior_adapter_fresh']['sha256']='0'*64
    elif change=='history_source_omission':kwargs['historical_source_inventory']['source_texts']=[]
    elif change=='history_source_commitment':exposure['historical_source_inventory_sha256']='0'*64
    elif change=='overlap_claim':exposure['new_source_overlap_count']=1
    else:inputs['manifest']['new_training_documents']=384
    with pytest.raises(ValueError):audit.audit_scope_annotations(*args,**kwargs)
