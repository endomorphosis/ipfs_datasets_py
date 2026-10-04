"""Source-complete paired temporal ownership contrasts with explicit ambiguity.

This is an authored owner-TYPE task. Coordinated events are not admissions to
any existing flat logic profile. Gold-filtered owner candidates are references
only and must never become an inference candidate inventory or model feature.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import itertools
from pathlib import Path
import random
import re

from . import legal_temporal_ownership_corpus as old

require,wire,sha,digest,file_ref,read_ref,write_new=(getattr(old,k) for k in
    ('require','wire','sha','digest','file_ref','read_ref','write_new'))
query,validate_source_query,propose_time_spans,validate_query_inventory=(getattr(old,k) for k in
    ('query','validate_source_query','propose_time_spans','validate_query_inventory'))
SCHEMA='authored-paired-temporal-ownership-corpus/v1'
ANNOTATION_SCHEMA='authored-paired-temporal-ownership-annotation/v1'
LABELS=old.LABELS
COUNTS={'train':864,'tuning':288,'fresh_lexical':144,'fresh_structural':144}
UNITS={'train':72,'tuning':24,'fresh_lexical':12,'fresh_structural':12}
SOURCE_KEYS=old.SOURCE_KEYS
TARGET_KEYS=SOURCE_KEYS|{'label','group_id','annotation'}
SEALED=('fresh_lexical_targets','fresh_structural_targets','fresh_annotation_ledger','exposure_audit')
AUTHORITY='prospectively_authored_owner_type_not_independent_legal_gold'
TRAIN_LAYOUTS=('norm_condition_exception','condition_norm_exception','exception_norm_condition')
STRUCTURAL_LAYOUTS=('condition_exception_norm','exception_condition_norm','norm_exception_condition')
TIME_FORMS=old.TIME_FORMS
# Each pattern has three2-query sources followed by two3-query sources.
PATTERNS=(
    (('condition','condition'),('ambiguous','ambiguous'),('norm','exception'),('norm','norm','condition'),('exception','exception','ambiguous')),
    (('norm','ambiguous'),('norm','ambiguous'),('condition','exception'),('norm','condition','exception'),('condition','exception','ambiguous')),
    (('exception','ambiguous'),('exception','ambiguous'),('exception','ambiguous'),('norm','norm','norm'),('condition','condition','condition')),
)
VOCAB={
 'train':{'names':('Aster','Bramble','Clover','Dahlia'),'actions':('file','record','register','archive'),'objects':('permit dossier','license folder','application ledger','notice bundle')},
 'tuning':{'names':('Elder','Fennel','Gardenia','Hyssop'),'actions':('submit','deliver','catalog','log'),'objects':('review journal','request packet','service folio','approval chart')},
 'fresh_lexical':{'names':('Iris','Jasmine','Kalmia','Lavender'),'actions':('transmit','dispatch','retain','present'),'objects':('inspection register','appeal schedule','audit return','clearance brief')},
 'fresh_structural':{'names':('Magnolia','Nettle','Orchid','Peony'),'actions':('publish','forward','store','issue'),'objects':('assessment record','compliance sheet','registration certificate','authorization statement')},
}
HEADINGS={
 'train':('Section {n}. Attachment duties.— ','[Provision {n}] ','Rule {n}: '),
 'tuning':('ARTICLE {n} — Timing. ','(Duty {n}) ','Requirement {n}. '),
 'fresh_lexical':('§ {n}(c) [Performance]. ','Subpart {n} :: Actions. ','{{{n}}} Records / '),
 'fresh_structural':('Part {n} / Operations: ','({n})(iv)— Timing. ','Schedule [{n}]: Application. '),
}
MODALS={'O':'shall','P':'may','F':'shall not'}
RELEASE_RULE='Fresh ownership targets, reference-only candidate ledger and exposure audit remain sealed until selection, generation and independent replay freeze.'


def source_row(row):return validate_source_query({key:deepcopy(row[key]) for key in SOURCE_KEYS})


def factors(split,unit,source):
 require(split in UNITS and type(unit) is int and 0<=unit<UNITS[split] and type(source) is int and 0<=source<5,'bounded authored factors required')
 block,rotation=divmod(unit,4);pattern=block%3
 labels=PATTERNS[pattern][source]
 labels=tuple(LABELS[(LABELS.index(label)+rotation)%4] for label in labels)
 # All12 queries/unit share the exact literal, so time values cannot identify a label.
 form=TIME_FORMS[(block+rotation)%4]
 modality='OPF'[(block+block//3)%3]
 layouts=STRUCTURAL_LAYOUTS if split=='fresh_structural' else TRAIN_LAYOUTS
 return labels,form,modality,layouts[(unit+source)%3],pattern,rotation


def literal(split,unit,form):
 index=list(UNITS).index(split);amount=11+index*100+unit
 year=2071+index;day=unit%28+1
 return {'days':f'within {amount} days of notice','hours':f'within {amount} hours of notice',
  'iso_date':f'before {year}-09-{day:02d}','month_date':f'before September {day}, {year}'}[form]


def owner_identity(source_sha,owner_type,anchor):
 return 'owner-'+digest([source_sha,owner_type,anchor['char_start'],anchor['char_end']])


def render_source(split,unit,source):
 labels,form,modality,layout,pattern,rotation=factors(split,unit,source)
 case=unit*5+source;v=VOCAB[split];time_text=literal(split,unit,form)
 writer=old.Writer();heading=writer.add(HEADINGS[split][case%3].format(n=case+1))
 roles=[];queries={};records=[];body_cues={};block_spans={};norm_owners=[]
 actor=f"the {v['names'][case%4]} office {10000+case}"
 norm_slots=[i for i,label in enumerate(labels) if label=='norm']
 local={'condition':[],'exception':[]}
 for slot,label in enumerate(labels):
  if label in local:local[label].append((slot,label))
 ambiguities=[i for i,label in enumerate(labels) if label=='ambiguous']
 for index,slot in enumerate(ambiguities):
  if len(ambiguities)==1 and 'condition' in labels and 'exception' not in labels:owner='exception'
  elif len(ambiguities)==1 and 'exception' in labels and 'condition' not in labels:owner='condition'
  else:owner=('condition','exception')[(case+index)%2]
  local[owner].append((slot,'ambiguous'))
 for owner in local:
  if not local[owner]:local[owner]=[(None,None)]

 def add_role(text,role):
  result=writer.add(text);roles.append({'role':role,'span':deepcopy(result)});return result
 def emit_time(slot):
  require(slot not in queries,'unique query slot required');queries[slot]=writer.add(time_text)
 def norm_block():
  start=len(writer.text);actor_span=add_role(actor,'actor');writer.add(' ');body_cues['norm']=writer.add(MODALS[modality])
  entries=norm_slots or [None]
  for index,slot in enumerate(entries):
   if index:writer.add(' and')
   if slot is not None:writer.add(', ');emit_time(slot);writer.add(', ')
   else:writer.add(' ')
   text=f"{v['actions'][(case+index)%4]} the {v['objects'][(case+index)%4]} {10000+case}-{index+1}"
   anchor=add_role(text,'action');norm_owners.append({'owner_type':'norm','anchor_span':anchor,'scope_span':None,'query_slot':slot,'cue_span':body_cues['norm']})
  block_spans['norm']=writer.span(start,len(writer.text))
  for item in norm_owners:item['scope_span']=deepcopy(block_spans['norm'])
 def qualifier_block(owner):
  start=len(writer.text);cue=writer.add('if' if owner=='condition' else 'unless');body_cues[owner]=cue;writer.add(' ')
  for index,(slot,label) in enumerate(local[owner]):
   if index:writer.add(' and ' if owner=='condition' else ' or ')
   atom_start=len(writer.text)
   subject=f"the {v['names'][(case+index+1)%4].lower()} {'application' if owner=='condition' else 'waiver'} {10000+case}-{index+1}"
   predicate=(' was received' if owner=='condition' else ' was issued') if label==owner else (' is valid' if owner=='condition' else ' is active')
   anchor=add_role(subject+predicate,owner+'_predicate')
   if slot is not None:writer.add(' ');emit_time(slot)
   records.append({'owner_type':owner,'anchor_span':anchor,'scope_span':writer.span(atom_start,len(writer.text)),
                   'query_slot':slot,'query_label':label,'cue_span':cue})
  block_spans[owner]=writer.span(start,len(writer.text))
 sequence=layout.split('_')
 for index,block in enumerate(sequence):
  if index:writer.add(', ' if sequence[index-1]!='norm' or block=='norm' else ' ')
  norm_block() if block=='norm' else qualifier_block(block)
 writer.add('.')
 require(set(queries)==set(range(len(labels))),'every authored query inserted')
 proposed=propose_time_spans(writer.text)
 require([(p['char_start'],p['char_end']) for p in proposed]==sorted((s['char_start'],s['char_end']) for s in queries.values()),'all lexical time occurrences must be accounted')
 source_sha=sha(writer.text);source_group='source-'+source_sha;unit_id='unit-'+digest([SCHEMA,split,unit])
 all_owners=norm_owners+records
 for item in all_owners:item['owner_occurrence_id']=owner_identity(source_sha,item['owner_type'],item['anchor_span'])
 require(len({r['owner_occurrence_id'] for r in all_owners})==len(all_owners),'distinct source owner anchors required')
 outputs=[]
 for slot,label in enumerate(labels):
  if label=='norm':selected=[next(r for r in norm_owners if r['query_slot']==slot)];countermodels=None
  else:
   target=next(r for r in records if r['query_slot']==slot)
   selected=norm_owners+[target] if label=='ambiguous' else [target]
   countermodels=old.ambiguity_countermodels(target['owner_type']) if label=='ambiguous' else None
  candidates=[{key:deepcopy(item[key]) for key in ('owner_type','owner_occurrence_id','anchor_span','scope_span')} for item in selected]
  annotations={'schema':ANNOTATION_SCHEMA,'split':split,'unit_index':unit,'source_index':source,'unit_id':unit_id,
   'cardinality':len(labels),'unit_pattern':pattern,'label_rotation':rotation,'layout_family':layout,
   'time_form':form,'modality':modality,'heading_span':heading,'time_span':queries[slot],
   'time_cue_span':writer.span(queries[slot]['char_start'],queries[slot]['char_start']+len(time_text.split()[0])),
   'source_role_spans':deepcopy(roles),'block_spans':deepcopy(block_spans),
   'owner_candidates':candidates,'attachment_cue_spans':[{'owner_occurrence_id':item['owner_occurrence_id'],'span':deepcopy(item['cue_span'])} for item in selected],
   'gold_filtered_owner_candidates':True,'candidate_inventory_usage':'reference_only_not_inference_inputs',
   'unique_owner_type_asserted':label!='ambiguous','unique_owner_occurrence_asserted':label!='ambiguous',
   'countermodels':countermodels,'annotation_authority':AUTHORITY,'independently_reviewed':False,
   'source_semantics_verified':False,'legal_gold':False,'flat_logic_profile_admission':False}
  q=query(writer.text,{key:queries[slot][key] for key in ('char_start','char_end')})
  outputs.append({**q,'label':label,'group_id':source_group,'annotation':annotations})
 return deepcopy(outputs)


def make_panel(split):
 rows=[];units=[]
 for unit in range(UNITS[split]):
  selected=[r for source in range(5) for r in render_source(split,unit,source)]
  require(Counter(r['label'] for r in selected)==Counter({x:3 for x in LABELS}),'balanced12-query unit required')
  rows.extend(selected);units.append({'unit_id':selected[0]['annotation']['unit_id'],'query_ids':sorted(r['id'] for r in selected)})
 random.Random(904071+list(UNITS).index(split)).shuffle(rows)
 return rows,units


def validate_target(row):
 require(type(row) is dict and set(row)==TARGET_KEYS,'closed paired target required');validate_source_query(source_row(row))
 a=row['annotation'];require(type(a) is dict,'annotation object required')
 expected=render_source(a.get('split'),a.get('unit_index'),a.get('source_index'))
 matches=[r for r in expected if r['id']==row['id']]
 require(len(matches)==1 and wire(matches[0])==wire(row),'target differs from insertion-owned provenance')
 return row


def validate_units(rows,units,split,reconstruct=True):
 require(type(rows) is list and type(units) is list and len(rows)==COUNTS[split] and len(units)==UNITS[split],'complete paired inventory required')
 lookup={r['id']:r for r in rows};require(len(lookup)==len(rows),'duplicate occurrence');seen=set();seen_sources=set();unit_ids=set()
 for item in units:
  require(type(item) is dict and set(item)=={'unit_id','query_ids'} and type(item['query_ids']) is list
   and len(item['query_ids'])==len(set(item['query_ids']))==12 and item['query_ids']==sorted(item['query_ids'])
   and set(item['query_ids'])<=set(lookup) and item['unit_id'] not in unit_ids and not seen.intersection(item['query_ids']),'closed unique complete sampling unit required')
  selected=[lookup[q] for q in item['query_ids']];by_source=defaultdict(list)
  for r in selected:
   require(r['annotation']['unit_id']==item['unit_id'] and r['annotation']['split']==split,'unit annotation join differs')
   by_source[r['source_sha256']].append(r)
  require(Counter(len(v) for v in by_source.values())==Counter({2:3,3:2}),'unit must contain three pairs and two triples')
  require(not seen_sources.intersection(by_source),'whole source crosses units')
  require(Counter(r['label'] for r in selected)==Counter({x:3 for x in LABELS}),'unit must have3queries/class')
  require(len({r['annotation']['time_span']['text'] for r in selected})==1,'time lexeme must match across all unit classes')
  for values in by_source.values():validate_query_inventory([source_row(r) for r in values])
  seen.update(item['query_ids']);seen_sources.update(by_source);unit_ids.add(item['unit_id'])
 require(seen==set(lookup),'unassigned query')
 for r in rows:
  if reconstruct:validate_target(r)
  else:validate_source_query(source_row(r))
 require(Counter(r['annotation']['modality'] for r in rows)==Counter({x:len(rows)//3 for x in 'OPF'}),'modality margins differ')
 require(Counter(r['annotation']['time_form'] for r in rows)==Counter({x:len(rows)//4 for x in TIME_FORMS}),'time-form margins differ')
 return rows


def body_layout(row):
 a=row['annotation'];source=row['source_text'];start=a['heading_span']['char_end']
 spans=[(r['span']['char_start'],r['span']['char_end'],'['+r['role']+']') for r in a['source_role_spans']]
 spans += [(s['char_start'],s['char_end'],'[TIME]') for s in propose_time_spans(source)]
 # Modal words are neutralized so an O/P/F difference cannot masquerade as a new layout.
 norm=a['block_spans']['norm'];actor=next(r['span'] for r in a['source_role_spans'] if r['role']=='actor')
 m=re.match(r' (shall not|shall|may)(?=[, ])',source[actor['char_end']:]);require(m is not None,'authored modal missing')
 spans.append((actor['char_end']+1,actor['char_end']+1+len(m.group(1)),'[MODAL]'))
 for lo,hi,marker in sorted(spans,reverse=True):source=source[:lo]+marker+source[hi:]
 return source[start:]


def exposure_audit(panels,prior_inputs,history_source_refs):
 historical=set();history_pins=[]
 for pin in history_source_refs:
  values=read_ref(pin);require(type(values) is list,'historical source pack must be list')
  for row in values:
   require(type(row) is dict and set(row)=={'candidate_id','source_text','source_sha256'} and row['source_sha256']==sha(row['source_text']),'closed historical source pack required')
   historical.add(old.normalized_source(row['source_text']))
  history_pins.append(pin)
 for key in ('train','tuning','fresh_sources','multi_fresh_sources'):
  historical.update(old.normalized_source(r['source_text']) for r in prior_inputs[key])
 seen_sources=set();seen_groups=set();seen_literals=set();result={};layout_sets={}
 for split,(rows,units) in panels.items():
  sources={old.normalized_source(r['source_text']) for r in rows};groups={r['group_id'] for r in rows};literals={r['annotation']['time_span']['text'] for r in rows}
  require(not sources&historical and not sources&seen_sources and not groups&seen_groups and not literals&seen_literals,'historical/cross-split source,group or literal overlap')
  seen_sources.update(sources);seen_groups.update(groups);seen_literals.update(literals)
  layouts={body_layout(r) for r in rows};layout_sets[split]=layouts
  by_source=defaultdict(list)
  for r in rows:by_source[r['source_sha256']].append(r)
  pattern_counts=Counter(f"{len(v)}occ/{len({r['label'] for r in v})}types" for v in by_source.values())
  result[split]={'queries':len(rows),'sources':len(sources),'units':len(units),'class_counts':dict(Counter(r['label'] for r in rows)),
   'modality_by_class':{label:dict(Counter(r['annotation']['modality'] for r in rows if r['label']==label)) for label in LABELS},
   'time_form_by_class':{label:dict(Counter(r['annotation']['time_form'] for r in rows if r['label']==label)) for label in LABELS},
   'source_cardinality_and_distinct_owner_types':dict(pattern_counts),'normalized_body_layouts':sorted(layouts),
   'matches_train_body_layout_queries':sum(body_layout(r) in layout_sets['train'] for r in rows),
   'matches_train_or_tuning_body_layout_queries':sum(body_layout(r) in (layout_sets['train']|layout_sets.get('tuning',set())) for r in rows),
   'source_hashes':sorted(by_source),'time_literals':sorted(literals)}
 require(not layout_sets['fresh_structural']&(layout_sets['train']|layout_sets['tuning']),'structural fresh layout collapsed into admitted layout')
 return {'schema':'paired-temporal-ownership-exposure/v1','panels':result,'historical_source_packs':history_pins,
  'prior_corpus_manifest':prior_inputs['manifest_ref'],'historical_unique_sources_checked':len(historical),
  'historical_source_overlap':0,'cross_split_source_overlap':0,'cross_split_group_overlap':0,'cross_split_literal_overlap':0,
  'prospective_layout_partition':{'train_and_tuning':list(TRAIN_LAYOUTS),'fresh_lexical':list(TRAIN_LAYOUTS),'fresh_structural':list(STRUCTURAL_LAYOUTS)},
  'selected_vocabulary':VOCAB,'heading_renderers':HEADINGS,'shared_local_attachment_grammar':True,'independent_legal_gold':False,
  'candidate_inventory_usage':'Gold-filtered owner candidates are reference-side evidence only; no inference candidate enumerator is certified.',
  'limits':['Structural novelty is relative to the pinned admitted normalized body layouts, not all legal language.',
   'Repeated same-type coordinated events are an authored owner-type task, not expansion of flat logic-profile support.',
   'Temporal offsets are proposed lexical inputs; exact owner occurrences remain reference annotations, not model outputs.']}


def producers():
 root=Path(__file__).resolve().parents[3]
 return [file_ref(__file__),file_ref(root/'scripts/ops/legal_ir/prepare_legal_paired_temporal_ownership_corpus.py'),file_ref(old.__file__)]


def build_corpus(output,prior_manifest_path):
 output=Path(output).resolve();require(not output.exists(),'new corpus output required')
 prior=old.load_training_inputs(prior_manifest_path)
 panels={split:make_panel(split) for split in COUNTS}
 for split,(rows,units) in panels.items():validate_units(rows,units,split)
 audit=exposure_audit(panels,prior,prior['manifest']['historical_source_packs'])
 output.mkdir(parents=True);artifacts={}
 for split in ('train','tuning'):
  rows,units=panels[split];artifacts[split+'_targets']=write_new(output/(split+'-targets.json'),rows)
  artifacts[split+'_units']=write_new(output/(split+'-units.json'),units)
 for split in ('fresh_lexical','fresh_structural'):
  rows,units=panels[split]
  artifacts[split+'_sources']=write_new(output/(split.replace('_','-')+'-sources.json'),[source_row(r) for r in rows])
  artifacts[split+'_targets']=write_new(output/(split.replace('_','-')+'-targets.json'),rows)
 artifacts['fresh_annotation_ledger']=write_new(output/'fresh-annotation-ledger.json',{
  'schema':'paired-temporal-ownership-reference-ledger/v1','candidate_inventory_usage':'reference_only_not_inference_inputs',
  'units':{split:panels[split][1] for split in ('fresh_lexical','fresh_structural')},
  'annotations':{split:[{k:r[k] for k in ('id','source_sha256','group_id','label','annotation')} for r in panels[split][0]] for split in ('fresh_lexical','fresh_structural')}})
 artifacts['exposure_audit']=write_new(output/'exposure-audit.json',audit)
 m={'schema':SCHEMA,'counts':COUNTS,'unit_counts':UNITS,'source_query_keys':sorted(SOURCE_KEYS),'labels':list(LABELS),
  'artifacts':artifacts,'sealed_artifacts':list(SEALED),'prior_corpus':prior['manifest_ref'],'producer_files':producers(),
  'regression_references':{'single_sources':prior['manifest']['artifacts']['fresh_sources'],'single_targets':prior['manifest']['artifacts']['fresh_targets'],
   'multi_sources':prior['manifest']['artifacts']['multi_fresh_sources'],'multi_targets':prior['manifest']['artifacts']['multi_fresh_targets']},
  'sampling_unit_queries':12,'queries_per_class_per_unit':3,'old_training_rows_reused':768,'old_tuning_rows_reused':144,
  'scope':'authored_owner_type_only','gold_filtered_owner_candidates':'reference_only_not_inference_inputs','source_offsets_supplied':True,
  'fresh_structural_layouts_disjoint_from_train_tuning':True,'shared_local_attachment_grammar':True,
  'independent_legal_gold':False,'flat_logic_profile_admission':False,'release_rule':RELEASE_RULE}
 return write_new(output/'manifest.json',m)


def load_training_inputs(manifest_path):
 pin=file_ref(manifest_path);m=read_ref(pin)
 required={'schema','counts','unit_counts','source_query_keys','labels','artifacts','sealed_artifacts','prior_corpus','producer_files','regression_references',
  'sampling_unit_queries','queries_per_class_per_unit','old_training_rows_reused','old_tuning_rows_reused','scope','gold_filtered_owner_candidates',
  'source_offsets_supplied','fresh_structural_layouts_disjoint_from_train_tuning','shared_local_attachment_grammar','independent_legal_gold','flat_logic_profile_admission','release_rule'}
 require(type(m) is dict and set(m)==required and m['schema']==SCHEMA,'closed paired manifest required')
 require(wire(m['counts'])==wire(COUNTS) and wire(m['unit_counts'])==wire(UNITS) and m['labels']==list(LABELS)
  and m['source_query_keys']==sorted(SOURCE_KEYS) and m['sealed_artifacts']==list(SEALED),'manifest count/input/schema changed')
 require(wire(m['producer_files'])==wire(producers()),'producer pins changed')
 for key,wanted in {'sampling_unit_queries':12,'queries_per_class_per_unit':3,'old_training_rows_reused':768,'old_tuning_rows_reused':144}.items():
  require(type(m[key]) is int and m[key]==wanted,'manifest integer contract differs')
 require(m['scope']=='authored_owner_type_only' and m['gold_filtered_owner_candidates']=='reference_only_not_inference_inputs'
  and m['source_offsets_supplied'] is True and m['fresh_structural_layouts_disjoint_from_train_tuning'] is True
  and m['shared_local_attachment_grammar'] is True and m['independent_legal_gold'] is False
  and m['flat_logic_profile_admission'] is False and m['release_rule']==RELEASE_RULE,'manifest authority/release changed')
 expected={'train_targets','train_units','tuning_targets','tuning_units','fresh_lexical_sources','fresh_structural_sources',*SEALED}
 require(type(m['artifacts']) is dict and set(m['artifacts'])==expected,'artifact inventory differs')
 for r in m['artifacts'].values():
  require(type(r) is dict and set(r)=={'path','sha256','bytes'} and type(r['path']) is str and Path(r['path']).is_absolute()
   and type(r['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',r['sha256']) and type(r['bytes']) is int and 0<=r['bytes']<=old.MAX_FILE_BYTES,'closed artifact pin required')
 require(len({r['path'] for r in m['artifacts'].values()})==len(expected),'artifact paths must be distinct')
 read_ref(m['prior_corpus']);prior=old.load_training_inputs(m['prior_corpus']['path'])
 expected_reg={'single_sources':prior['manifest']['artifacts']['fresh_sources'],'single_targets':prior['manifest']['artifacts']['fresh_targets'],
               'multi_sources':prior['manifest']['artifacts']['multi_fresh_sources'],'multi_targets':prior['manifest']['artifacts']['multi_fresh_targets']}
 require(wire(m['regression_references'])==wire(expected_reg),'exposed regression references changed')
 loaded={'manifest':m,'manifest_ref':pin,'single_training':prior['train'],'single_tuning':prior['tuning'],
  'regression_sources':{'single':prior['fresh_sources'],'multi':prior['multi_fresh_sources']}}
 seen={old.normalized_source(r['source_text']) for key in ('train','tuning','fresh_sources','multi_fresh_sources') for r in prior[key]}
 for split,rows_key,unit_key in [('train','paired_training','sampling_units'),('tuning','paired_tuning','tuning_units')]:
  rows=read_ref(m['artifacts'][split+'_targets']);units=read_ref(m['artifacts'][split+'_units']);validate_units(rows,units,split)
  values={old.normalized_source(r['source_text']) for r in rows};require(not seen&values,'paired admitted source overlap');seen.update(values)
  loaded[rows_key]=rows;loaded[unit_key]=units
 for split in ('fresh_lexical','fresh_structural'):
  rows=read_ref(m['artifacts'][split+'_sources']);validate_query_inventory(rows,expected=COUNTS[split])
  values={old.normalized_source(r['source_text']) for r in rows};require(not seen&values,'paired evaluation source overlap');seen.update(values)
  loaded[split+'_sources']=rows
 return loaded
