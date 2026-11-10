import json,os,glob,shutil,hashlib,sys,datetime
B='/workspace/courts';P2=B+'/staging/state_county/phase2';RV=B+'/review_state_county/phase2'
SRC=B+'/hf_stage_fixup';OUT=B+'/hf_stage_phase2';SC='official_state_judiciary_sites_phase2_20261028'
COV={'KY':'complete','WY':'complete','ID':'complete','NV':'partial_host_stopped','MN':'partial_host_stopped','IA':'partial_rows_dropped'}
now=datetime.datetime.now().astimezone().isoformat()
hub={c:[json.loads(l) for l in open(f'{SRC}/data/{c}.jsonl')] for c in ['courts','courthouses','judges','forms']}
keys={c:list(hub[c][0]) for c in hub}
PK={'courts':'court_id','courthouses':'courthouse_id','judges':'judge_id','forms':'form_id'}
new={c:[] for c in hub}
for st in sorted(COV):
  for c in hub:
    f=f'{P2}/{st}/{c}.jsonl'
    for l in open(f):
      if l.strip(): new[c].append(json.loads(l))
# 1) drop IA judges
ia=[r for r in new['judges'] if r['subdivision_iso']=='US-IA']
with open(RV+'/removed_ia_judges.jsonl','w') as fh:
  for r in ia: fh.write(json.dumps(dict(r,_removed_reason='CoS 2026-10-29: IA roster parse garbage (court_name from In Memoriam/staff pages), no IA courts row to link; dropped',_removed_at=now))+'\n')
new['judges']=[r for r in new['judges'] if r['subdivision_iso']!='US-IA']
# merge IA courthouses
iac=[r for r in new['courthouses'] if r['subdivision_iso']=='US-IA']
assert len(iac)==3 and len({r['postal_code'] for r in iac})==1
keep=iac[0];keep['name']='Iowa Judicial Branch Building'
with open(RV+'/merged_ia_courthouses.jsonl','w') as fh:
  fh.write(json.dumps({'kept_courthouse_id':keep['courthouse_id'],'merged_ids':[r['courthouse_id'] for r in iac[1:]],'reason':'same building, 1111 East Court Avenue, Des Moines 50319 (name/abbrev variants)','variants':iac,'merged_at':now})+'\n')
drop={r['courthouse_id'] for r in iac[1:]}
new['courthouses']=[r for r in new['courthouses'] if r['courthouse_id'] not in drop]
# normalize fields
for c in new:
  for r in new[c]:
    r['coverage']=COV[r['subdivision_iso'][3:]];r['source_collection']=SC
    if c=='courts': r.setdefault('content_sha256_note',None)
  new[c]=[{k:r.get(k) for k in keys[c]} for r in new[c]]
# validate strict
iso=set();m=json.load(open('/workspace/coverage/subnational_state_matrix_20261025.json'))
for r in m['rows']: iso.add(r.get('iso_3166_2') or r.get('iso'))
courtids={r['court_id'] for r in hub['courts']+new['courts']}
REQ={'courts':['court_id','name','country','source_url'],'courthouses':['courthouse_id','name','source_url'],'judges':['judge_id','full_name','source_url'],'forms':['form_id','title','file_url','file_sha256']}
val={}
for c in new:
  ids=[r[PK[c]] for r in new[c]];hids={r[PK[c]] for r in hub[c]}
  v={'rows':len(new[c]),'dup_ids':len(ids)-len(set(ids)),'dup_vs_hub':sum(i in hids for i in ids),
     'fk_court_missing':sum(1 for r in new[c] if r.get('court_id') and r['court_id'] not in courtids)+(sum(1 for r in new[c] if r.get('parent_court_id') and r['parent_court_id'] not in courtids) if c=='courts' else 0),
     'fk_iso_bad':sum(1 for r in new[c] if r.get('subdivision_iso') not in iso),
     'missing_required':sum(1 for r in new[c] for k in REQ[c] if not r.get(k)),
     'non_https':sum(1 for r in new[c] for k in ('source_url','url','file_url','roster_url') if r.get(k) and not r[k].startswith('https://'))+sum(r.get('transport')!='https' for r in new[c])}
  if c=='judges': v['fk_court_null']=sum(1 for r in new[c] if not r.get('court_id'))
  val[c]=v
bad=sum(v['dup_ids']+v['dup_vs_hub']+v['fk_court_missing']+v['fk_iso_bad']+v['missing_required']+v['non_https'] for v in val.values())
json.dump({'generated':now,'strict_fk':True,'iso_matrix_size':len(iso),'validation':val,'total_problems':bad},open(RV+'/validation_final.json','w'),indent=1)
print(json.dumps(val,indent=1),'TOTAL_PROBLEMS',bad)
if bad or '--build' not in sys.argv: sys.exit(1 if bad else 0)
bak=B+'/hf_stage_fixup_bak_20261029_pre_phase2'
if not os.path.exists(bak): shutil.copytree(SRC,bak)
if os.path.exists(OUT): shutil.rmtree(OUT)
shutil.copytree(SRC,OUT)
for c in new:
  with open(f'{OUT}/data/{c}.jsonl','a') as fh:
    for r in new[c]: fh.write(json.dumps(r,ensure_ascii=False)+'\n')
s=json.load(open(OUT+'/schema.json'))
for t in s['tables'].values():
  if 'coverage' in t: t['coverage']=t['coverage'].replace('partial_guard_stop,blocked','partial_guard_stop,partial_rows_dropped,blocked')
json.dump(s,open(OUT+'/schema.json','w'),indent=1)
with open(OUT+'/README.md','a') as fh: fh.write(open(RV+'/CARD_PHASE2.md').read())
rc={c:sum(1 for _ in open(f'{OUT}/data/{c}.jsonl')) for c in ['courthouses','courts','forms','judges','rules','state_rules']}
open(OUT+'/ROWCOUNTS.txt','w').write(''.join(f'data/{c}.jsonl {n}\n' for c,n in rc.items()))
def sh(p):
  h=hashlib.sha256();h.update(open(p,'rb').read());return h.hexdigest()
fs=['README.md','ROWCOUNTS.txt','schema.json']+[f'data/{c}.jsonl' for c in rc]
open(OUT+'/MANIFEST.sha256','w').write(''.join(f'{sh(OUT+"/"+f)}  {f}\n' for f in fs))
print('BUILT',rc,{c:len(new[c]) for c in new})
