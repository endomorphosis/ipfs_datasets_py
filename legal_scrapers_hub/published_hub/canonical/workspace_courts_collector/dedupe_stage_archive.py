import json,hashlib,collections,glob
B='/workspace/courts';RV=f'{B}/review_state_rules_archive';H=f'{B}/hf_stage/data/state_rules.jsonl'
nu=lambda u:(u or '').strip().lower().split('#')[0].rstrip('/').replace('http://','https://')
sh=set();urls=set();th=set()
for l in open(H):
  r=json.loads(l);rec=r['record']
  for k in('content_sha256','file_sha256'):
    if rec.get(k):sh.add(rec[k])
  for k in('file_url','original_url'):
    if rec.get(k):urls.add(nu(rec[k]))
  if rec.get('file_url') is None and rec.get('source_url'):urls.add(nu(rec['source_url']))  # page-level rows
  t=rec.get('full_text') or rec.get('text')
  if t:th.add(hashlib.sha256(t.encode()).hexdigest())
seen=set();out=[];log=[];c=collections.Counter()
for l in open(f'{RV}/filter_survivors.jsonl'):
  r=json.loads(l);st=r['subdivision_iso'][3:];u=nu(r['original_url'])
  why=('dup_hf_sha256' if r['content_sha256'] in sh or r['file_sha256'] in sh else
       'dup_hf_url' if u in urls or nu(r['source_url']) in urls else
       'dup_hf_text_sha256' if r['text_sha256'] in th else
       'dup_within_batch' if r['content_sha256'] in seen or r['text_sha256'] in seen else None)
  c[(st,why or 'kept')]+=1;log.append(dict(rule_id=r['rule_id'],state=st,original_url=r['original_url'],result=why or 'kept'))
  if why:continue
  seen|={r['content_sha256'],r['text_sha256']}
  rec={k:v for k,v in r.items() if k!='local_path'}
  out.append(dict(subdivision_iso=r['subdivision_iso'],license='see source terms',archive_source='commoncrawl',source_collection='commoncrawl_archive_20261028',record=rec))
with open(f'{RV}/dedupe_log.jsonl','w') as f:
  for x in log:f.write(json.dumps(x)+'\n')
with open(f'{RV}/archive_new_unique.jsonl','w') as f:
  for x in out:f.write(json.dumps(x)+'\n')
print(dict(c),len(out))
