"""Source/attachment provenance tests for the new authored ownership corpus."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_corpus as c


@pytest.mark.parametrize('split', list(c.COUNTS))
def test_complete_factor_counts_and_exact_annotation_replay(split):
    rows, groups = c.make_panel(split)
    c.validate_panel(rows, groups, split)
    assert Counter(row['label'] for row in rows) == {label: c.COUNTS[split]//4 for label in c.LABELS}
    assert Counter(row['annotation']['modality'] for row in rows) == {modal:c.COUNTS[split]//3 for modal in 'OPF'}
    for label in c.LABELS:
        assert Counter(row['annotation']['time_form'] for row in rows if row['label']==label) == {
            form:c.COUNTS[split]//16 for form in c.TIME_FORMS}
    for row in rows:
        a=row['annotation'];text=row['source_text'];t=a['time_span']
        assert text[t['char_start']:t['char_end']]==t['text']
        for owner in a['owner_candidates']:
            for name in ('anchor_span','scope_span'):
                s=owner[name];assert text[s['char_start']:s['char_end']]==s['text']
        assert a['legal_gold'] is False and a['independently_reviewed'] is False


def test_quartets_share_exact_time_entity_factors_without_paired_wrong_labels():
    for case in range(c.GROUP_COUNTS['train']):
        rows=c.make_group('train',case)
        assert {row['label'] for row in rows}==set(c.LABELS)
        assert len({row['annotation']['time_span']['text'] for row in rows})==1
        assert len({row['annotation']['modality'] for row in rows})==1
        assert len({row['annotation']['heading_span']['text'] for row in rows})==1
        assert len({row['annotation']['lexical_spans'][0]['span']['text'] for row in rows})==1


def test_every_main_deadline_placement_realized_balanced():
    for split in ('train','tuning','fresh'):
        rows,_=c.make_panel(split)
        assert Counter(row['annotation']['construction_family'] for row in rows)=={
            family:c.COUNTS[split]//3 for family in c.FAMILIES}
        for row in rows:
            if row['label']!='norm':continue
            a=row['annotation'];t=a['time_span'];actor=a['lexical_spans'][0]['span'];action=a['lexical_spans'][1]['span']
            if a['construction_family']=='fronted_deadline':assert t['char_end']<actor['char_start']
            elif a['construction_family']=='modal_interposed_deadline':assert actor['char_end']<t['char_start']<action['char_start']
            else:assert action['char_end']<t['char_start']


def test_dual_queries_share_source_but_have_distinct_owners_and_intervals():
    rows,groups=c.make_panel('multi_fresh');byid={r['id']:r for r in rows}
    assert len({r['source_sha256'] for r in rows})==48
    for group in groups:
        a,b=[byid[x] for x in group['query_ids']]
        assert a['source_text']==b['source_text'] and a['label']!=b['label']
        assert a['proposed_time_span']!=b['proposed_time_span']
        assert a['annotation']['time_span']['text']==b['annotation']['time_span']['text']
        assert len(c.propose_time_spans(a['source_text']))==2
    assert Counter(tuple(sorted(byid[q]['label'] for q in group['query_ids'])) for group in groups)=={
        tuple(sorted(pair)):8 for pair in __import__('itertools').combinations(c.LABELS,2)}


def test_source_files_contain_no_labels_owner_spans_or_group_features():
    rows,_=c.make_panel('multi_fresh')
    for row in rows:
        source=c.source_row(row)
        assert set(source)==c.SOURCE_KEYS
        assert source['id'].startswith('occ-') and len(source['id'])==68
        assert all(label not in source['id'] for label in c.LABELS)
        assert 'group' not in c.wire({k:v for k,v in source.items() if k!='source_text'})


def test_proposer_preserves_month_comma_and_enumerates_repeated_occurrences():
    text='Office shall, before September 12, 2044, file if an application was received before September 12, 2044.'
    spans=c.propose_time_spans(text)
    assert [text[s['char_start']:s['char_end']] for s in spans]==['before September 12, 2044']*2
    assert spans[0]!=spans[1]


@pytest.mark.parametrize('text', ['before 2041-02-30','before September 31, 2044'])
def test_proposer_rejects_impossible_calendar_dates(text):
    with pytest.raises(ValueError):c.propose_time_spans(text)


def test_partial_occurrence_not_admitted_even_with_repaired_identity():
    row=c.source_row(c.make_group('train',0)[0]);row['proposed_time_span']['char_end']-=3
    row['id']=c.query(row['source_text'],row['proposed_time_span'])['id']
    with pytest.raises(ValueError,match='complete lexical'):c.validate_source_query(row)


@pytest.mark.parametrize('value',[True,1.0])
def test_coordinate_type_is_strict(value):
    row=c.source_row(c.make_group('train',0)[0]);row['proposed_time_span']['char_start']=value
    with pytest.raises(ValueError,match='integer time interval'):c.validate_source_query(row)


@pytest.mark.parametrize('change',['label','owner_span','cue_span','source','factor_type','authority','countermodel'])
def test_repaired_hashes_cannot_relabel_or_expand_owner_scope(change):
    row=deepcopy(c.make_group('train',0)[3]);a=row['annotation']
    if change=='label':row['label']='norm'
    elif change=='owner_span':a['owner_candidates'][0]['anchor_span']=deepcopy(a['heading_span'])
    elif change=='cue_span':a['time_cue_span']['text']='if'
    elif change=='source':
        row['source_text']=row['source_text'].replace(' is valid',' was received')
        row['source_sha256']=c.sha(row['source_text']);row['id']=c.query(row['source_text'],row['proposed_time_span'])['id']
    elif change=='factor_type':a['case_index']=0.0
    elif change=='authority':a['independently_reviewed']=True
    else:a['countermodels']['worlds'][0]['norm_attachment_time_test']=False
    with pytest.raises(ValueError):c.validate_target(row)


def test_ambiguous_copular_tail_retains_two_countermodels_without_unique_truth():
    for case in range(12):
        row=c.make_group('train',case)[3];a=row['annotation'];models=a['countermodels']
        assert row['label']=='ambiguous' and a['unique_owner_asserted'] is False
        assert {x['owner'] for x in a['owner_candidates']} in ({'norm','condition'},{'norm','exception'})
        assert models['legal_truth_verified'] is False
        assert [(w['norm_attachment_time_test'],w['qualifier_attachment_time_test']) for w in models['worlds']]==[(True,False),(False,True)]
        local=a['owner_candidates'][1]['scope_span']['text']
        assert (' is active ' in local or ' is valid ' in local) and ',' not in local.replace(a['time_span']['text'],'[TIME]')


def test_complete_receipt_predicates_are_inside_declared_qualifier_scope():
    for case in range(12):
        for row in c.make_group('train',case)[1:3]:
            a=row['annotation'];owner=a['owner_candidates'][0];scope=owner['scope_span'];time=a['time_span']
            assert owner['owner']==row['label']
            assert scope['char_start']<time['char_start']<time['char_end']<=scope['char_end']
            assert ' was ' in scope['text'] and a['countermodels'] is None


def test_groups_reject_duplicate_query_missing_class_and_wrong_join():
    rows,groups=c.make_panel('tuning')
    bad=deepcopy(rows);bad[-1]=deepcopy(bad[0])
    with pytest.raises(ValueError,match='duplicate'):c.validate_panel(bad,groups,'tuning')
    bad=deepcopy(groups);bad[0]['query_ids'][0]=bad[1]['query_ids'][0]
    with pytest.raises(ValueError):c.validate_panel(rows,bad,'tuning')


def test_same_source_requires_all_distinct_occurrence_queries():
    rows=[c.source_row(r) for r in c.make_group('multi_fresh',0)]
    c.validate_query_inventory(rows)
    with pytest.raises(ValueError,match='omits'):c.validate_query_inventory(rows[:1])
    with pytest.raises(ValueError,match='duplicate'):c.validate_query_inventory(rows+[rows[0]])


def test_split_content_and_section_style_inventories_are_declared_disjoint():
    splits=list(c.COUNTS)
    for i,a in enumerate(splits):
        for b in splits[i+1:]:
            for key in c.LEXICONS[a]:assert not set(c.LEXICONS[a][key]).intersection(c.LEXICONS[b][key])
            assert not set(c.STYLES[a]).intersection(c.STYLES[b])
    panels={split:c.make_panel(split) for split in splits}
    audit=c.exposure_audit(panels,[])
    assert audit['prospective_source_overlap']==0 and audit['shared_attachment_grammar'] is True
    assert audit['historical_source_packs']==[]


def test_historical_exclusion_accepts_only_source_rows_and_rejects_overlap(tmp_path):
    panels={'train':c.make_panel('train')};row=panels['train'][0][0]
    pack=tmp_path/'source.json'
    c.write_new(pack,[{'candidate_id':'old','source_text':row['source_text'],'source_sha256':row['source_sha256']}])
    with pytest.raises(ValueError,match='duplicates'):c.exposure_audit(panels,[pack])
    other=tmp_path/'targets.json';c.write_new(other,[row])
    with pytest.raises(ValueError,match='source-only'):c.exposure_audit(panels,[other])


def test_actual_tokenizer_alignment_and_256_token_budget():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    for split in c.COUNTS:
        rows,_=c.make_panel(split)
        for row in rows:
            tokens=span.tokenize_source(row['source_text']);s=row['proposed_time_span']
            assert len(tokens)<=256
            assert s['char_start'] in {t['start'] for t in tokens}
            assert s['char_end'] in {t['end'] for t in tokens}


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    output=tmp_path_factory.mktemp('ownership')/'corpus'
    ref=c.build_corpus(output,[])
    return Path(ref['path'])


def test_materialized_source_order_and_references(built):
    loaded=c.load_training_inputs(built)
    assert len(loaded['train'])==768 and len(loaded['tuning'])==144
    assert len(loaded['fresh_sources'])==192 and len(loaded['multi_fresh_sources'])==96
    assert len(loaded['train_groups'])==192 and len(loaded['tuning_groups'])==36
    assert [r['label'] for r in loaded['train'][:4]]!=list(c.LABELS)
    assert set(loaded['manifest']['sealed_artifacts'])==set(c.SEALED)


def test_loader_makes_zero_fresh_reference_opens(built,tmp_path):
    program='''
import json,sys
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_corpus as c
p=Path(sys.argv[1]);m=json.loads(p.read_text());blocked={str(Path(m['artifacts'][k]['path']).resolve()) for k in c.SEALED}
attempts=[]
def guard(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        name=str(Path(args[0]).resolve())
        if name in blocked:attempts.append(name);raise AssertionError('sealed reference opened')
sys.addaudithook(guard)
x=c.load_training_inputs(p)
assert not attempts and len(x['train'])==768 and len(x['fresh_sources'])==192
print('zero sealed reads')
'''
    result=subprocess.run([sys.executable,'-c',program,str(built)],capture_output=True,text=True,cwd=Path(__file__).resolve().parents[4])
    assert result.returncode==0,result.stderr
    assert 'zero sealed reads' in result.stdout


@pytest.mark.parametrize('change',['counts_float','true_authority','artifact_alias','new_manifest_key','producer_bytes_float','artifact_path_type','artifact_sha_type'])
def test_manifest_repairs_cannot_weaken_closed_contract(built,tmp_path,change):
    manifest=json.loads(built.read_text())
    if change=='counts_float':manifest['counts']['train']=768.0
    elif change=='true_authority':manifest['independent_legal_gold']=True
    elif change=='artifact_alias':manifest['artifacts']['fresh_targets']=manifest['artifacts']['train_targets']
    elif change=='producer_bytes_float':manifest['producer_files'][0]['bytes']=float(manifest['producer_files'][0]['bytes'])
    elif change=='artifact_path_type':manifest['artifacts']['fresh_targets']['path']=7
    elif change=='artifact_sha_type':manifest['artifacts']['fresh_targets']['sha256']=True
    else:manifest['extra']=True
    p=tmp_path/'manifest.json';c.write_new(p,manifest)
    with pytest.raises(ValueError):c.load_training_inputs(p)


def test_no_existing_corpus_overwrite(built):
    with pytest.raises(ValueError,match='new corpus'):c.build_corpus(built.parent,[])


def test_duplicate_json_keys_and_nonfinite_values_rejected():
    for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
        with pytest.raises(ValueError):c.strict_json(raw)
