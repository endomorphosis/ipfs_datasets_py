"""Prospective placement source coverage, annotation integrity, and seal tests."""
from collections import Counter,defaultdict
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from ipfs_datasets_py.logic.autoformal import legal_temporal_placement_corpus as c
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_candidates as candidates


@pytest.fixture(scope='module')
def panels():return {split:c.make_panel(split) for split in c.COUNTS}


@pytest.mark.parametrize('split',list(c.COUNTS))
def test_full_balanced_source_complete_units(panels,split):
 rows,units=panels[split];c.validate_units(rows,units,split)
 assert len({r['source_sha256'] for r in rows})==c.UNITS[split]*5
 for label in c.LABELS:
  selected=[r for r in rows if r['label']==label]
  assert len(selected)==len(rows)//4
  assert Counter(r['annotation']['modality'] for r in selected)=={k:len(rows)//12 for k in 'OPF'}
  assert Counter(r['annotation']['time_form'] for r in selected)=={k:len(rows)//16 for k in c.TIME_FORMS}
  assert Counter(r['annotation']['norm_time_placement'] for r in selected)=={k:len(rows)//12 for k in c.PLACEMENTS}


def test_actual_norm_deadline_positions_bound_to_each_action(panels):
 for rows,_ in panels.values():
  for row in rows:
   if row['label']!='norm':continue
   a=row['annotation'];time=a['time_span'];owner=a['owner_candidates'][0];anchor=owner['anchor_span']
   cue=a['attachment_cue_spans'][0]['span'];actors=[r['span'] for r in a['source_role_spans'] if r['role']=='actor' and r['span']['char_end']<cue['char_start']]
   actor=max(actors,key=lambda r:r['char_start'])
   if a['norm_time_placement']=='before_actor':assert time['char_end']<actor['char_start']<cue['char_start']<anchor['char_start']
   elif a['norm_time_placement']=='after_modal':assert cue['char_end']<time['char_start']<time['char_end']<anchor['char_start']
   else:assert cue['char_end']<anchor['char_start']<anchor['char_end']<time['char_start']


@pytest.mark.parametrize('split',list(c.COUNTS))
def test_three_predicates_and_third_timed_transition_are_real(panels,split):
 rows,_=panels[split];found=Counter()
 for row in rows:
  a=row['annotation'];roles=a['source_role_spans'];source=row['source_text']
  assert sum(r['role']=='condition_predicate' for r in roles)==3
  assert sum(r['role']=='exception_predicate' for r in roles)==3
  if row['label'] not in ('condition','exception') or a['local_atom_ordinal']!=3:continue
  owner=row['label'];other='exception' if owner=='condition' else 'condition';seq=a['layout_family'].split('_')
  if seq.index(other)!=seq.index(owner)+1:continue
  after=source[a['time_span']['char_end']:a['block_spans'][other]['char_start']]
  assert set(after)<=set(', ()')
  found[owner]+=1
 assert found['condition']>0 and found['exception']>0


def test_all_reference_candidates_pass_independent_coordinate_contract(panels):
 for rows,_ in panels.values():
  for row in rows:
   report=candidates.prepare_owner_candidates(c.source_row(row),c.candidate_coordinate_inputs(row))
   assert report['owner_occurrence_resolved'] is False and report['candidate_inventory_complete'] is False
   assert row['annotation']['candidate_inventory_usage']=='reference_only_not_inference_inputs'


def test_same_type_distinct_anchor_pairs_triples_and_mixed_sources(panels):
 for rows,_ in panels.values():
  groups=defaultdict(list)
  for row in rows:groups[row['source_sha256']].append(row)
  for cardinality in (2,3):
   for label in c.LABELS:
    matches=[v for v in groups.values() if len(v)==cardinality and {r['label'] for r in v}=={label}]
    assert matches
    if label!='ambiguous':
     assert all(len({r['annotation']['owner_candidates'][0]['owner_occurrence_id'] for r in v})==cardinality for v in matches)
  assert any(len({r['label'] for r in v})==3 for v in groups.values())


def test_completed_event_and_copular_ambiguity_annotated_without_truth_claim(panels):
 for rows,_ in panels.values():
  for row in rows:
   a=row['annotation'];assert a['legal_gold'] is False and a['flat_logic_profile_admission'] is False
   if row['label']=='ambiguous':
    assert a['unique_owner_type_asserted'] is False and a['countermodels']['legal_truth_verified'] is False
    local=next(v for v in a['owner_candidates'] if v['owner_type']!='norm')
    assert ' is valid' in local['anchor_span']['text'] or ' is active' in local['anchor_span']['text']
   elif row['label'] in ('condition','exception'):
    assert ' was received' in a['owner_candidates'][0]['anchor_span']['text'] or ' was issued' in a['owner_candidates'][0]['anchor_span']['text']


def test_no_reference_metadata_in_queries_and_full_proposal_inventory(panels):
 for rows,_ in panels.values():
  source=[c.source_row(r) for r in rows];c.validate_query_inventory(source)
  assert all(set(r)==c.SOURCE_KEYS and len(r['id'])==68 for r in source)
  with pytest.raises(ValueError):c.validate_query_inventory(source[:-1])


def test_encoder_token_budget_and_month_comma_proposals(panels):
 from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
 for rows,_ in panels.values():
  for row in rows:
   tokens=span.tokenize_source(row['source_text']);q=row['proposed_time_span']
   assert len(tokens)<=256
   assert q['char_start'] in {t['start'] for t in tokens} and q['char_end'] in {t['end'] for t in tokens}
   if row['annotation']['time_form']=='month_date':assert ', ' in row['source_text'][q['char_start']:q['char_end']]


@pytest.mark.parametrize('change',['label','source','scope','cue','owner_id','unit_float','placement','atom_ordinal','authority','modal_span'])
def test_repaired_reference_mutations_rejected(change):
 row=deepcopy(c.render_source('train',0,0)[0]);a=row['annotation']
 if change=='label':row['label']='norm'
 elif change=='source':
  row['source_text']=row['source_text'].replace(' was received',' was issued');row['source_sha256']=c.sha(row['source_text'])
  row['id']=c.query(row['source_text'],row['proposed_time_span'])['id']
 elif change=='scope':a['owner_candidates'][0]['scope_span']=deepcopy(a['body_span'])
 elif change=='cue':a['attachment_cue_spans'][0]['span']=deepcopy(a['time_cue_span'])
 elif change=='owner_id':a['owner_candidates'][0]['owner_occurrence_id']='owner-'+'0'*64
 elif change=='unit_float':a['unit_index']=0.0
 elif change=='placement':a['norm_time_placement']='after_action'
 elif change=='atom_ordinal':a['local_atom_ordinal']=4
 elif change=='authority':a['legal_gold']=True
 else:a['modal_spans'][0]=deepcopy(a['time_cue_span'])
 with pytest.raises(ValueError):c.validate_target(row)


@pytest.mark.parametrize('change',['duplicate_query','missing_query','duplicate_unit','cross_unit','unbalanced_label'])
def test_broken_sampling_units_rejected(panels,change):
 rows,units=deepcopy(panels['tuning'])
 if change=='duplicate_query':rows[-1]=deepcopy(rows[0])
 elif change=='missing_query':rows.pop()
 elif change=='duplicate_unit':units[0]=deepcopy(units[1])
 elif change=='cross_unit':units[0]['query_ids'][0]=units[1]['query_ids'][0];units[0]['query_ids'].sort()
 else:rows[0]['label']='different'
 with pytest.raises(ValueError):c.validate_units(rows,units,'tuning')


@pytest.fixture(scope='module')
def built(tmp_path_factory):
 base=tmp_path_factory.mktemp('placement')
 old=c.old.build_corpus(base/'old',[])
 paired=c.previous.build_corpus(base/'paired',old['path'])
 ref=c.build_corpus(base/'current',paired['path'])
 return Path(ref['path'])


def test_actual_layout_exposure_is_joint_enclosure_holdout(built):
 m=c.read_ref(c.file_ref(built));audit=c.read_ref(m['artifacts']['exposure_audit'])
 fresh=audit['panels']['fresh_structural'];lex=audit['panels']['fresh_lexical']
 assert fresh['matches_new_train_or_tuning_body_layout_queries']==0 and fresh['matches_prior_paired_body_layout_queries']==0
 assert lex['matches_new_train_body_layout_queries']>0
 assert audit['historical_source_overlap']==0 and audit['shared_basic_cues_and_temporal_placements'] is True
 for values in audit['panels'].values():assert values['third_condition_before_unless_queries']>0


def test_new_training_separate_from_all_retention_and_replay(built):
 loaded=c.load_training_inputs(built)
 for key,count in {'single_training':768,'prior_paired_training':864,'prior_sampling_units':72,'placement_training':864,
                   'sampling_units':72,'placement_tuning':288,'tuning_units':24,'fresh_lexical_sources':144,'fresh_structural_sources':144}.items():assert len(loaded[key])==count
 assert set(loaded['retention_targets'])==set(c.RETENTION)
 assert {k:len(v) for k,v in loaded['retention_targets'].items()}=={
  'single_tuning':144,'prior_paired_tuning':288,'old_single_fresh':192,'old_multi_fresh':96,'prior_fresh_lexical':144,'prior_fresh_structural':144}
 old={r['source_sha256'] for values in [loaded['single_training'],loaded['prior_paired_training'],*loaded['retention_targets'].values()] for r in values}
 assert not old&{r['source_sha256'] for r in loaded['placement_training']}
 for name,rows in loaded['retention_targets'].items():assert [c.source_row(r) for r in rows]==loaded['retention_sources'][name]


def test_loader_zero_current_sealed_opens(built):
 program='''
import sys,json
from pathlib import Path
from ipfs_datasets_py.logic.autoformal import legal_temporal_placement_corpus as c
p=Path(sys.argv[1]);m=json.loads(p.read_text());blocked={str(Path(m['artifacts'][k]['path']).resolve()) for k in c.SEALED};attempts=[]
def guard(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)) and str(Path(args[0]).resolve()) in blocked:
  attempts.append(str(args[0]));raise RuntimeError('sealed')
sys.addaudithook(guard)
x=c.load_training_inputs(p)
assert len(x['placement_training'])==864 and len(x['retention_targets'])==6 and not attempts
print('zero current semantic reads')
'''
 p=subprocess.run([sys.executable,'-c',program,str(built)],capture_output=True,text=True,cwd=Path(__file__).resolve().parents[4])
 assert p.returncode==0,p.stderr
 assert 'zero current semantic reads' in p.stdout


@pytest.mark.parametrize('change',['counts_float','producer_float','authority','extra','alias','reference_bool'])
def test_repaired_manifest_cannot_weaken_protocol(built,tmp_path,change):
 m=json.loads(built.read_text())
 if change=='counts_float':m['counts']['train']=864.0
 elif change=='producer_float':m['producer_files'][0]['bytes']=float(m['producer_files'][0]['bytes'])
 elif change=='authority':m['independent_legal_gold']=True
 elif change=='extra':m['newflag']=True
 elif change=='alias':m['artifacts']['fresh_lexical_targets']=m['artifacts']['train_targets']
 else:m['artifacts']['fresh_lexical_targets']['bytes']=True
 pin=c.write_new(tmp_path/'manifest.json',m)
 with pytest.raises(ValueError):c.load_training_inputs(pin['path'])


def test_corpus_cannot_overwrite_prior_materialization(built):
 with pytest.raises(ValueError,match='new corpus'):c.build_corpus(built.parent,built)
