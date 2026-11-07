import json,glob,os,hashlib,csv,collections
O='/workspace/courts/staging/state_rules_rerun';OFF='/workspace/courts/staging/state_rules/official';RV='/workspace/courts/review_state_rules_rerun';os.makedirs(RV,exist_ok=True)
S=[k for k in json.load(open('/workspace/courts/schema.json'))['tables']['rules'] if not k.startswith('_')]
def rows(f):return [json.loads(l) for l in open(f)] if os.path.exists(f) else []
orig={st:{r['file_sha256'] for r in rows(f'{OFF}/{st}.jsonl')}|{r['rule_id'] for r in rows(f'{OFF}/{st}.jsonl')} for st in ['KS','NE','DE']}
cnt={};dd={};miss=collections.Counter();samp={}
for st in ['KS','NE','DE']:
  allr=rows(f'{O}/{st}.jsonl')+rows(f'{O}/{st}_resume.jsonl');seen=set();uniq=[];dup_orig=dup_int=0
  for r in allr:
    miss.update(k for k in S if k not in r)
    if r['rule_id'] in orig[st] or r['file_sha256'] in orig[st]:dup_orig+=1;continue
    if r['file_sha256'] in seen:dup_int+=1;continue
    seen.add(r['file_sha256']);uniq.append(r)
  with open(f'{RV}/{st}_new_unique.jsonl','w') as o:
    for r in uniq:o.write(json.dumps(r)+'\n')
  cnt[st]=len(allr);dd[st]=dict(staged=len(allr),dup_vs_original=dup_orig,dup_internal=dup_int,new_unique=len(uniq));samp[st]=uniq[:2]
w=csv.writer(open(RV+'/sha256_manifest.csv','w'));w.writerow(['path','bytes','sha256'])
for p in sorted(glob.glob(O+'/**/*',recursive=True)+glob.glob(RV+'/*_new_unique.jsonl')):
  if os.path.isfile(p):
    h=hashlib.sha256()
    with open(p,'rb') as fh:
      for c in iter(lambda:fh.read(1<<20),b''):h.update(c)
    w.writerow([p,os.path.getsize(p),h.hexdigest()])
sk=rows(O+'/skips.jsonl')
for k,v in [('row_counts',cnt),('dedupe',dd),('samples',samp),('schema_validation',dict(missing=dict(miss),ok=not miss)),('skips',sk)]:json.dump(v,open(f'{RV}/{k}.json','w'),indent=1)
open(RV+'/REVIEW.md','w').write('# State rules rerun + resume (NE, DE, KS) review\nStage only, not pushed. Licence: see source terms.\n## Dedupe (vs original official run, then internal by sha256)\n'+'\n'.join(f'- {k}: {v}' for k,v in dd.items())+f'\n## Schema: {"OK" if not miss else "MISSING "+str(dict(miss))}\n## Skips\n'+'\n'.join(f"- {s.get('state')}: {s.get('reason')}" for s in sk)+'\nMerge candidates: *_new_unique.jsonl\n')
