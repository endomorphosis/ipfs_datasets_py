"""Authored temporal placement contrasts; no statutory ownership certification.

All labels and ambiguity alternatives are author declarations. Reference-only
owner candidates never enter the four-field numerical source-query interface.
"""
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
import random
import re
from . import legal_paired_temporal_ownership_corpus as previous

old=previous.old
require,wire,sha,digest,file_ref,read_ref,write_new=(getattr(previous,k) for k in
 ('require','wire','sha','digest','file_ref','read_ref','write_new'))
query,validate_source_query,propose_time_spans,validate_query_inventory=(getattr(previous,k) for k in
 ('query','validate_source_query','propose_time_spans','validate_query_inventory'))
SOURCE_KEYS=previous.SOURCE_KEYS
TARGET_KEYS=SOURCE_KEYS|{'label','group_id','annotation'}
LABELS=previous.LABELS
TIME_FORMS=previous.TIME_FORMS
COUNTS={'train':864,'tuning':288,'fresh_lexical':144,'fresh_structural':144}
UNITS={'train':72,'tuning':24,'fresh_lexical':12,'fresh_structural':12}
SEALED=('fresh_lexical_targets','fresh_structural_targets','fresh_annotation_ledger','exposure_audit')
SCHEMA='authored-temporal-placement-corpus/v1'
ANNOTATION_SCHEMA='authored-temporal-placement-annotation/v1'
AUTHORITY='prospectively_authored_owner_type_not_independent_legal_gold'
PLACEMENTS=('before_actor','after_modal','after_action')
LAYOUTS=('norm_condition_exception','condition_norm_exception','exception_norm_condition',
 'norm_exception_condition','exception_condition_norm','condition_exception_norm')
STRUCTURAL_LAYOUTS=('norm_condition_exception','condition_exception_norm','norm_exception_condition','exception_condition_norm')
VOCAB={
 'train':{'names':('Alder','Birch','Cedar','Dogwood'),'actions':('file','record','register','archive'),'objects':('dossier','ledger','folder','notice')},
 'tuning':{'names':('Elm','Fir','Ginkgo','Hemlock'),'actions':('submit','deliver','catalog','log'),'objects':('journal','packet','folio','chart')},
 'fresh_lexical':{'names':('Juniper','Larch','Maple','Oak'),'actions':('transmit','dispatch','retain','present'),'objects':('schedule','return','brief','report')},
 'fresh_structural':{'names':('Pine','Redwood','Spruce','Tamarack'),'actions':('publish','forward','store','issue'),'objects':('record','sheet','certificate','statement')},
}
HEADINGS={
 'train':('Duty {n}. — ','[Rule {n}] ','Section {n}: '),
 'tuning':('Article ({n}) / ','Requirement [{n}]. ','Provision {n} — '),
 'fresh_lexical':('SUBPART {n}: Duties. ','({n})(b) Records — ','Schedule {n} / '),
 'fresh_structural':('Item {n} :: Timing. ','§{n} [Review] — ','Part({n}): Performance. '),
}
RETENTION=('single_tuning','prior_paired_tuning','old_single_fresh','old_multi_fresh','prior_fresh_lexical','prior_fresh_structural')
RELEASE_RULE='Fresh ownership targets, reference-only candidate ledger and exposure audit remain sealed until selection, source generation and independent replay freeze.'


def source_row(row):return validate_source_query({k:deepcopy(row[k]) for k in SOURCE_KEYS})


def factors(split,unit,source):
 require(split in UNITS and type(unit) is int and 0<=unit<UNITS[split] and type(source) is int and 0<=source<5,'bounded authored factors required')
 labels,form,modality,_,pattern,rotation=previous.factors(split,unit,source)
 placement=PLACEMENTS[unit%3]
 if split=='fresh_structural':layout=STRUCTURAL_LAYOUTS[(unit+source)%4];enclosure='joint_qualifiers'
 else:layout=LAYOUTS[(unit+source)%6];enclosure=('none','condition_only','exception_only')[(unit//3+source)%3]
 return labels,form,modality,placement,layout,enclosure,pattern,rotation


def literal(split,unit,form):
 index=list(UNITS).index(split);amount=401+index*100+unit;year=2081+index;day=unit%28+1
 return {'days':f'within {amount} days of notice','hours':f'within {amount} hours of notice',
  'iso_date':f'before {year}-09-{day:02d}','month_date':f'before September {day}, {year}'}[form]


def render_source(split,unit,source):
 labels,form,modality,placement,layout,enclosure,pattern,rotation=factors(split,unit,source)
 case=unit*5+source;v=VOCAB[split];timing=literal(split,unit,form);w=old.Writer()
 heading=w.add(HEADINGS[split][case%3].format(n=case+1));roles=[];modals=[];blocks={};queries={};owners=[];norms=[]
 norm_slots=[i for i,label in enumerate(labels) if label=='norm'];local={'condition':[],'exception':[]}
 for slot,label in enumerate(labels):
  if label in local:local[label].append((slot,label))
 for index,slot in enumerate(i for i,label in enumerate(labels) if label=='ambiguous'):
  if labels.count('ambiguous')==1 and 'condition' in labels and 'exception' not in labels:owner='exception'
  elif labels.count('ambiguous')==1 and 'exception' in labels and 'condition' not in labels:owner='condition'
  else:owner=('condition','exception')[(case+index)%2]
  local[owner].append((slot,'ambiguous'))
 def role(text,kind):
  span=w.add(text);roles.append({'role':kind,'span':deepcopy(span)});return span
 def emit_time(slot):
  require(slot not in queries,'one exact insertion per query required');queries[slot]=w.add(timing)
 def norm_block():
  start=len(w.text)
  for index,slot in enumerate(norm_slots or [None]):
   if index:w.add('; ')
   begin=len(w.text)
   if slot is not None and placement=='before_actor':emit_time(slot);w.add(', ')
   role(f"the {v['names'][case%4]} bureau {80000+case}",'actor');w.add(' ')
   cue=w.add(previous.MODALS[modality]);modals.append(deepcopy(cue))
   if slot is not None and placement=='after_modal':w.add(', ');emit_time(slot);w.add(', ')
   else:w.add(' ')
   anchor=role(f"{v['actions'][(case+index)%4]} the {v['objects'][(case+index)%4]} {80000+case}-{index+1}",'action')
   if slot is not None and placement=='after_action':w.add(', ');emit_time(slot)
   norms.append({'owner_type':'norm','anchor_span':anchor,'scope_span':w.span(begin,len(w.text)),
     'cue_span':cue,'query_slot':slot,'atom_ordinal':index+1})
  blocks['norm']=w.span(start,len(w.text))
 def qualifier_block(owner):
  start=len(w.text);wrapped=enclosure==owner+'_only'
  if wrapped:w.add('(')
  cue=w.add('if' if owner=='condition' else 'unless');w.add(' ')
  # Three actual predicate atoms always occur, including untimed controls.
  rotation=(case+(owner=='exception'))%3;positions=[(j+rotation)%3 for j in range(3)]
  entries={position:value for position,value in zip(positions,local[owner])}
  for index in range(3):
   if index:w.add(' and ' if owner=='condition' else ' or ')
   slot,label=entries.get(index,(None,None));subject=f"the {'application' if owner=='condition' else 'waiver'} {80000+case}-{index+1}"
   predicate=(' was received' if owner=='condition' else ' was issued') if label==owner else (' is valid' if owner=='condition' else ' is active')
   anchor=role(subject+predicate,owner+'_predicate')
   if slot is not None:w.add(' ');emit_time(slot)
   owners.append({'owner_type':owner,'anchor_span':anchor,'scope_span':None,'cue_span':cue,
     'query_slot':slot,'query_label':label,'atom_ordinal':index+1})
  if wrapped:w.add(')')
  blocks[owner]=w.span(start,len(w.text))
  for item in owners:
   if item['owner_type']==owner:item['scope_span']=deepcopy(blocks[owner])
 sequence=layout.split('_');qualifiers=[x for x in sequence if x!='norm'];joint_start=sequence.index(qualifiers[0]);joint_end=sequence.index(qualifiers[-1])
 for index,block in enumerate(sequence):
  if index:w.add(', ' if sequence[index-1]!='norm' or block=='norm' else ' ')
  if enclosure=='joint_qualifiers' and index==joint_start:w.add('(')
  norm_block() if block=='norm' else qualifier_block(block)
  if enclosure=='joint_qualifiers' and index==joint_end:w.add(')')
 body=w.span(heading['char_end'],len(w.text));w.add('.')
 require(set(queries)==set(range(len(labels))),'all query slots realized')
 proposed=propose_time_spans(w.text)
 require([(s['char_start'],s['char_end']) for s in proposed]==sorted((s['char_start'],s['char_end']) for s in queries.values()),'all lexical time occurrences required')
 unit_id='unit-'+digest([SCHEMA,split,unit]);source_sha=sha(w.text)
 for item in norms+owners:item['owner_occurrence_id']=previous.owner_identity(source_sha,item['owner_type'],item['anchor_span'])
 outputs=[]
 for slot,label in enumerate(labels):
  if label=='norm':target=next(v for v in norms if v['query_slot']==slot);selected=[target];countermodels=None
  else:
   target=next(v for v in owners if v['query_slot']==slot);selected=norms+[target] if label=='ambiguous' else [target]
   countermodels=old.ambiguity_countermodels(target['owner_type']) if label=='ambiguous' else None
  candidates=[{k:deepcopy(item[k]) for k in ('owner_type','owner_occurrence_id','anchor_span','scope_span')} for item in selected]
  if label=='ambiguous':
   for candidate in candidates:
    if candidate['owner_type']=='norm':candidate['scope_span']=deepcopy(body)
  a={'schema':ANNOTATION_SCHEMA,'split':split,'unit_index':unit,'source_index':source,'unit_id':unit_id,
   'cardinality':len(labels),'unit_pattern':pattern,'label_rotation':rotation,'layout_family':layout,'enclosure_family':enclosure,
   'norm_time_placement':placement,'time_form':form,'modality':modality,'heading_span':heading,'body_span':body,
   'time_span':queries[slot],'time_cue_span':w.span(queries[slot]['char_start'],queries[slot]['char_start']+len(timing.split()[0])),
   'source_role_spans':roles,'modal_spans':modals,'block_spans':blocks,'condition_atom_count':3,'exception_atom_count':3,
   'qualifier_order':qualifiers,'source_occurrence_ordinal':next(i+1 for i,s in enumerate(proposed) if s['char_start']==queries[slot]['char_start']),
   'authored_local_owner_type':target['owner_type'],'local_atom_ordinal':target['atom_ordinal'],
   'same_time_literal_for_all_source_occurrences':True,'owner_candidates':candidates,
   'attachment_cue_spans':[{'owner_occurrence_id':item['owner_occurrence_id'],'span':deepcopy(item['cue_span'])} for item in selected],
   'candidate_scope_semantics':'structural_enclosing_extent_not_semantic_closure',
   'gold_filtered_owner_candidates':True,'candidate_inventory_usage':'reference_only_not_inference_inputs',
   'unique_owner_type_asserted':label!='ambiguous','unique_owner_occurrence_asserted':label!='ambiguous',
   'countermodels':countermodels,'annotation_authority':AUTHORITY,'independently_reviewed':False,
   'source_semantics_verified':False,'legal_gold':False,'flat_logic_profile_admission':False}
  outputs.append({**query(w.text,{k:queries[slot][k] for k in ('char_start','char_end')}),'label':label,
                 'group_id':'source-'+source_sha,'annotation':deepcopy(a)})
 return outputs


def candidate_coordinate_inputs(row):return previous.candidate_coordinate_inputs(row)


def make_panel(split):
 rows=[];units=[]
 for unit in range(UNITS[split]):
  values=[r for source in range(5) for r in render_source(split,unit,source)];rows.extend(values)
  units.append({'unit_id':values[0]['annotation']['unit_id'],'query_ids':sorted(r['id'] for r in values)})
 random.Random(110401+list(UNITS).index(split)).shuffle(rows)
 return rows,units


def validate_target(row):
 require(type(row) is dict and set(row)==TARGET_KEYS,'closed placement target required');validate_source_query(source_row(row))
 a=row['annotation'];require(type(a) is dict,'annotation required')
 expected=render_source(a.get('split'),a.get('unit_index'),a.get('source_index'))
 matches=[r for r in expected if r['id']==row['id']]
 require(len(matches)==1 and wire(matches[0])==wire(row),'target differs from exact insertion provenance')
 return row


def validate_units(rows,units,split,reconstruct=True):
 # Frozen unit checker accepts the same public shape with reconstruction off.
 previous.validate_units(rows,units,split,reconstruct=False)
 if reconstruct:
  for row in rows:validate_target(row)
 require(Counter(r['annotation']['norm_time_placement'] for r in rows)==Counter({x:len(rows)//3 for x in PLACEMENTS}),'placement margin differs')
 return rows


def body_layout(row):
 text=row['source_text'];a=row['annotation'];start=a['heading_span']['char_end']
 spans=[(item['span']['char_start'],item['span']['char_end'],'['+item['role']+']') for item in a['source_role_spans']]
 spans += [(s['char_start'],s['char_end'],'[TIME]') for s in propose_time_spans(text)]
 spans += [(s['char_start'],s['char_end'],'[MODAL]') for s in a['modal_spans']]
 cursor=start;parts=[]
 for lo,hi,marker in sorted(spans):
  require(cursor<=lo<hi<=len(text),'nonoverlapping body masks required');parts.extend((text[cursor:lo],marker));cursor=hi
 return ''.join(parts)+text[cursor:]


def _prior_retention(prior):
 m=prior['manifest'];a=m['artifacts'];reg=m['regression_references']
 targets={'single_tuning':prior['single_tuning'],'prior_paired_tuning':prior['paired_tuning'],
  'old_single_fresh':read_ref(reg['single_targets']),'old_multi_fresh':read_ref(reg['multi_targets']),
  'prior_fresh_lexical':read_ref(a['fresh_lexical_targets']),'prior_fresh_structural':read_ref(a['fresh_structural_targets'])}
 for panel in ('old_single_fresh','old_multi_fresh'):
  for row in targets[panel]:old.validate_target(row)
 ledger=read_ref(a['fresh_annotation_ledger'])
 for panel,split in [('prior_fresh_lexical','fresh_lexical'),('prior_fresh_structural','fresh_structural')]:
  previous.validate_units(targets[panel],ledger['units'][split],split)
 return targets


def exposure_audit(panels,prior,retention):
 old_manifest=read_ref(prior['manifest']['prior_corpus']);historical=set();pins=old_manifest['historical_source_packs']
 for pin in pins:
  for row in read_ref(pin):
   require(set(row)=={'candidate_id','source_text','source_sha256'} and row['source_sha256']==sha(row['source_text']),'historical source binding differs')
   historical.add(old.normalized_source(row['source_text']))
 old_pools={'single_training':prior['single_training'],'prior_paired_training':prior['paired_training'],**retention}
 for rows in old_pools.values():historical.update(old.normalized_source(r['source_text']) for r in rows)
 prior_layouts={previous.body_layout(r) for key,rows in old_pools.items() if key in ('prior_paired_training','prior_paired_tuning','prior_fresh_lexical','prior_fresh_structural') for r in rows}
 result={};seen=set();groups_seen=set();literals_seen=set();layout_sets={}
 for split,(rows,units) in panels.items():
  sources={old.normalized_source(r['source_text']) for r in rows};groups={r['group_id'] for r in rows};literals={r['annotation']['time_span']['text'] for r in rows}
  require(not sources&historical and not sources&seen and not groups&groups_seen and not literals&literals_seen,'historical/cross-split overlap')
  seen.update(sources);groups_seen.update(groups);literals_seen.update(literals)
  layouts=[body_layout(r) for r in rows];layout_sets[split]=set(layouts);by_source=defaultdict(list)
  for row in rows:by_source[row['source_sha256']].append(row)
  third_condition=sum(r['label']=='condition' and r['annotation']['local_atom_ordinal']==3 and
                      r['annotation']['qualifier_order']==['condition','exception'] and
                      r['annotation']['layout_family'].split('_').index('exception')==r['annotation']['layout_family'].split('_').index('condition')+1 for r in rows)
  result[split]={'queries':len(rows),'sources':len(by_source),'units':len(units),'class_counts':dict(Counter(r['label'] for r in rows)),
   'placement_by_class':{label:dict(Counter(r['annotation']['norm_time_placement'] for r in rows if r['label']==label)) for label in LABELS},
   'modality_by_class':{label:dict(Counter(r['annotation']['modality'] for r in rows if r['label']==label)) for label in LABELS},
   'time_form_by_class':{label:dict(Counter(r['annotation']['time_form'] for r in rows if r['label']==label)) for label in LABELS},
   'source_cardinality_and_distinct_owner_types':dict(Counter(f"{len(v)}occ/{len({r['label'] for r in v})}types" for v in by_source.values())),
   'third_condition_before_unless_queries':third_condition,'normalized_body_layouts':sorted(set(layouts)),
   'matches_new_train_body_layout_queries':sum(v in layout_sets['train'] for v in layouts),
   'matches_new_train_or_tuning_body_layout_queries':sum(v in layout_sets['train']|layout_sets.get('tuning',set()) for v in layouts),
   'matches_prior_paired_body_layout_queries':sum(v in prior_layouts for v in layouts),'source_hashes':sorted(by_source),'time_literals':sorted(literals)}
 require(not layout_sets['fresh_structural']&(layout_sets['train']|layout_sets['tuning']|prior_layouts),'structural joint-enclosure holdout collapsed')
 return {'schema':'temporal-placement-exposure/v1','panels':result,'prior_corpus':prior['manifest_ref'],'historical_source_packs':pins,
  'historical_unique_sources_checked':len(historical),'prior_paired_normalized_body_layout_count':len(prior_layouts),
  'historical_source_overlap':0,'cross_split_source_overlap':0,'cross_split_group_overlap':0,'cross_split_literal_overlap':0,
  'prospective_enclosure_partition':{'train_tuning_lexical':['none','condition_only','exception_only'],'fresh_structural':['joint_qualifiers']},
  'shared_basic_cues_and_temporal_placements':True,'selected_vocabulary':VOCAB,'heading_renderers':HEADINGS,
  'independent_legal_gold':False,'candidate_inventory_usage':'reference_only_not_inference_inputs',
  'limits':['Joint qualifier enclosure is a held-out authored layout; legal attachment is not independently established.',
   'Body-layout novelty is checked against new admitted panels and prior annotated paired panels, not all possible legal texts.',
   'Old exposed references are retention targets only, never new training labels.']}


def producers():
 root=Path(__file__).resolve().parents[3]
 return [file_ref(__file__),file_ref(root/'scripts/ops/legal_ir/prepare_legal_temporal_placement_corpus.py'),file_ref(previous.__file__),file_ref(old.__file__)]


def build_corpus(output,prior_manifest_path):
 output=Path(output).resolve();require(not output.exists(),'new corpus output required')
 prior=previous.load_training_inputs(prior_manifest_path);retention=_prior_retention(prior)
 panels={split:make_panel(split) for split in COUNTS}
 for split,(rows,units) in panels.items():validate_units(rows,units,split)
 audit=exposure_audit(panels,prior,retention);output.mkdir(parents=True);artifacts={}
 for split in ('train','tuning'):
  rows,units=panels[split];artifacts[split+'_targets']=write_new(output/(split+'-targets.json'),rows)
  artifacts[split+'_units']=write_new(output/(split+'-units.json'),units)
 for split in ('fresh_lexical','fresh_structural'):
  rows,_=panels[split];artifacts[split+'_sources']=write_new(output/(split+'-sources.json'),[source_row(r) for r in rows])
  artifacts[split+'_targets']=write_new(output/(split+'-targets.json'),rows)
 artifacts['fresh_annotation_ledger']=write_new(output/'fresh-annotation-ledger.json',{
  'schema':'temporal-placement-reference-ledger/v1','candidate_inventory_usage':'reference_only_not_inference_inputs',
  'units':{split:panels[split][1] for split in ('fresh_lexical','fresh_structural')},
  'annotations':{split:[{k:r[k] for k in ('id','source_sha256','group_id','label','annotation')} for r in panels[split][0]] for split in ('fresh_lexical','fresh_structural')}})
 artifacts['exposure_audit']=write_new(output/'exposure-audit.json',audit)
 m={'schema':SCHEMA,'counts':COUNTS,'unit_counts':UNITS,'labels':list(LABELS),'source_query_keys':sorted(SOURCE_KEYS),
  'artifacts':artifacts,'sealed_artifacts':list(SEALED),'prior_corpus':prior['manifest_ref'],'producer_files':producers(),
  'retention_panels':list(RETENTION),'reused_training_counts':{'single':768,'paired':864},'new_training_queries':864,
  'sampling_unit_queries':12,'queries_per_class_per_unit':3,'scope':'authored_owner_type_only',
  'gold_filtered_owner_candidates':'reference_only_not_inference_inputs','source_offsets_supplied':True,
  'fresh_structural_joint_enclosure_disjoint':True,'shared_basic_cues_and_temporal_placements':True,
  'independent_legal_gold':False,'flat_logic_profile_admission':False,'release_rule':RELEASE_RULE}
 return write_new(output/'manifest.json',m)


def load_training_inputs(manifest_path):
 pin=file_ref(manifest_path);m=read_ref(pin)
 expected={'schema','counts','unit_counts','labels','source_query_keys','artifacts','sealed_artifacts','prior_corpus','producer_files',
  'retention_panels','reused_training_counts','new_training_queries','sampling_unit_queries','queries_per_class_per_unit','scope',
  'gold_filtered_owner_candidates','source_offsets_supplied','fresh_structural_joint_enclosure_disjoint',
  'shared_basic_cues_and_temporal_placements','independent_legal_gold','flat_logic_profile_admission','release_rule'}
 require(type(m) is dict and set(m)==expected and m['schema']==SCHEMA,'closed placement manifest required')
 for key,value in {'counts':COUNTS,'unit_counts':UNITS,'labels':list(LABELS),'source_query_keys':sorted(SOURCE_KEYS),
  'sealed_artifacts':list(SEALED),'producer_files':producers(),'retention_panels':list(RETENTION),
  'reused_training_counts':{'single':768,'paired':864},'new_training_queries':864,'sampling_unit_queries':12,'queries_per_class_per_unit':3,
  'scope':'authored_owner_type_only','gold_filtered_owner_candidates':'reference_only_not_inference_inputs','source_offsets_supplied':True,
  'fresh_structural_joint_enclosure_disjoint':True,'shared_basic_cues_and_temporal_placements':True,'independent_legal_gold':False,
  'flat_logic_profile_admission':False,'release_rule':RELEASE_RULE}.items():require(wire(m[key])==wire(value),'manifest contract differs: '+key)
 keys={'train_targets','train_units','tuning_targets','tuning_units','fresh_lexical_sources','fresh_structural_sources',*SEALED}
 require(type(m['artifacts']) is dict and set(m['artifacts'])==keys,'complete artifact inventory required')
 for ref in m['artifacts'].values():
  require(type(ref) is dict and set(ref)=={'path','bytes','sha256'} and type(ref['path']) is str and Path(ref['path']).is_absolute()
   and type(ref['sha256']) is str and re.fullmatch('[0-9a-f]{64}',ref['sha256']) and type(ref['bytes']) is int
   and 0<=ref['bytes']<=old.MAX_FILE_BYTES,'closed artifact reference required')
 require(len({p['path'] for p in m['artifacts'].values()})==len(keys),'artifact aliases rejected')
 read_ref(m['prior_corpus']);prior=previous.load_training_inputs(m['prior_corpus']['path']);retention=_prior_retention(prior)
 result={'manifest':m,'manifest_ref':pin,'legacy':prior,'single_training':prior['single_training'],
  'prior_paired_training':prior['paired_training'],'prior_sampling_units':prior['sampling_units'],
  'single_tuning':prior['single_tuning'],'prior_paired_tuning':prior['paired_tuning'],'retention_targets':retention,
  'retention_sources':{name:[source_row(r) for r in rows] for name,rows in retention.items()}}
 seen={old.normalized_source(r['source_text']) for rows in [prior['single_training'],prior['paired_training'],*retention.values()] for r in rows}
 for split,rows_key,units_key in [('train','placement_training','sampling_units'),('tuning','placement_tuning','tuning_units')]:
  rows=read_ref(m['artifacts'][split+'_targets']);units=read_ref(m['artifacts'][split+'_units']);validate_units(rows,units,split)
  sources={old.normalized_source(r['source_text']) for r in rows};require(not seen&sources,'admitted source overlap');seen.update(sources)
  result[rows_key]=rows;result[units_key]=units
 for split in ('fresh_lexical','fresh_structural'):
  rows=read_ref(m['artifacts'][split+'_sources']);validate_query_inventory(rows,expected=COUNTS[split])
  sources={old.normalized_source(r['source_text']) for r in rows};require(not seen&sources,'fresh source overlap');seen.update(sources)
  result[split+'_sources']=rows
 return result
