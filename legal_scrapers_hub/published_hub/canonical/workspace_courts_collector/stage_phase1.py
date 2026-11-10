import json,glob,os,re,hashlib,collections,unicodedata
B='/workspace/courts';S=B+'/staging/state_county/phase1';H=B+'/hf_stage';O=B+'/review_state_county/phase1_push'
GAPS={'DE':'phase1 ran; official pages yielded no usable static rows','MT':'no candidate directory/judges/forms page in static landing HTML (site errors)',
 'CT':'blocked in phase0: HTTP 403 (jud.ct.gov)','VA':'blocked in phase0: HTTP 403 (vacourts.gov)','KS':'blocked in phase0: challenge page (challenge-platform)',
 'WA':'host stopped on first request: HTTP 403 (courts.wa.gov)','WI':'host stopped: hCaptcha challenge (wicourts.gov)','ND':'host stopped: HTTP 403 (ndcourts.gov), no rows'}
def cov(st):
  s=st['status']
  if s=='ok':return 'complete'
  if 'guard stop' in s:return 'partial_guard_stop'
  if 'phase0' in s or sum(st['counts'].values())==0:return 'blocked'
  return 'partial_host_stopped'
def nz(x):
  x=unicodedata.normalize('NFKD',x or '').encode('ascii','ignore').decode().lower()
  return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',x)).strip()
T=['courts','courthouses','judges','forms']
hub={t:[json.loads(l) for l in open(f'{H}/data/{t}.jsonl')] for t in T}
URL={'courts':'url','courthouses':None,'judges':None,'forms':'file_url'}
def nkey(t,r):
  st=r.get('subdivision_iso')
  if t=='judges':return (nz(r.get('full_name')),nz(r.get('court_name')),st)
  if t=='forms':return (nz(r.get('title')),st,r.get('file_sha256'))
  if t=='courthouses':return (nz(r.get('name')),st,nz(r.get('address_line')))
  return (nz(r.get('name')),st)
states={};flags={'forms_cap250':{},'transport_http_rows':collections.Counter(),'transport_http_skipped_links':collections.Counter()}
for d in sorted(glob.glob(S+'/*/status.json')):
  st=json.load(open(d));states[st['state']]=st
  for n in st.get('notes',[]):
    if 'capped at 250' in n:flags['forms_cap250'][st['state']]=n
  flags['transport_http_skipped_links'][st['state']]=sum(1 for k in st.get('skips',[]) if k.get('transport')=='http')
covmap={s:cov(v) for s,v in states.items()}
rep={'tables':{},'coverage':covmap,'gaps':GAPS,'heuristic':{'url_key':URL,'name_key':'courts: norm(name)+state; courthouses: norm(name)+state+norm(address_line); judges: norm(full_name)+norm(court_name)+state; forms: norm(title)+state+file_sha256 (title alone collides across distinct files)'}}
idremap={};out={};keptU={};keptN={}
for t in T:
  seenU={r[URL[t]] for r in hub[t] if URL[t] and r.get(URL[t])};seenN={nkey(t,r) for r in hub[t]}
  hubN={nkey(t,r):r for r in hub[t]};hubU={r.get(URL[t]):r for r in hub[t]} if URL[t] else {}
  c=collections.Counter();new=[]
  for s in sorted(states):
    if s in GAPS:
      c['excluded_gap_state']+=sum(1 for _ in open(f'{S}/{s}/{t}.jsonl')) if os.path.exists(f'{S}/{s}/{t}.jsonl') else 0;continue
    f=f'{S}/{s}/{t}.jsonl'
    if not os.path.exists(f):continue
    for l in open(f):
      r=json.loads(l);c['staged']+=1
      if r.get('court_id') in idremap:r['court_id']=idremap[r['court_id']]
      u=r.get(URL[t]) if URL[t] else None;k=nkey(t,r)
      if u and u in hubU or k in hubN:
        c['dupe_hub']+=1
        if t=='courts':idremap[r['court_id']]=(hubU.get(u) or hubN[k])['court_id']
        continue
      if (u and u in seenU) or k in seenN:
        c['dupe_within_phase1']+=1
        if t=='courts':idremap[r['court_id']]=keptU.get(u) or keptN[k]
        continue
      if t=='courts':
        keptN[k]=r['court_id']
        if u:keptU[u]=r['court_id']
      if u:seenU.add(u)
      seenN.add(k)
      if t=='judges':
        if r.get('court_id') not in ({x['court_id'] for x in hub['courts']}|{x['court_id'] for x in out['courts']}):
          r['court_id']=None;c['court_id_nulled_unmatched']+=1
        for x in list(r):
          if x not in {'judge_id','full_name','title','court_id','court_name','roster_url','subdivision_iso','as_of','_privacy','source_url','fetched_at','archive_source','archive_timestamp','license','terms_note','robots_note','transport','content_sha256'}:r.pop(x)
      r['coverage']=covmap[s];r['source_collection']='official_state_judiciary_sites_phase1_20261028'
      if r.get('transport')=='http':flags['transport_http_rows'][f'{t}:{s}']+=1
      new.append(r)
  out[t]=new;c['added']=len(new);c['before']=len(hub[t]);c['final']=len(hub[t])+len(new);rep['tables'][t]=dict(c)
# validate
iso=json.load(open(B+'/collector/us_iso.json'));isos=set(iso)
cids={r['court_id'] for r in hub['courts']+out['courts']};err=collections.Counter()
for t in T:
  pk={'courts':'court_id','courthouses':'courthouse_id','judges':'judge_id','forms':'form_id'}[t]
  ids=[r[pk] for r in hub[t]+out[t]]
  if len(ids)!=len(set(ids)):err[t+':dup_pk']+=len(ids)-len(set(ids))
  for r in out[t]:
    if not (r.get('subdivision_iso') or '').startswith('US-'):err[t+':bad_iso']+=1
    if r['subdivision_iso'] not in isos:err[t+':iso_not_in_fk']+=1
    for x in ['source_url','fetched_at','archive_source','license','robots_note','transport']:
      if r.get(x) in (None,''):err[t+':missing_'+x]+=1
    if t in('courthouses','judges') and r.get('court_id') and r['court_id'] not in cids:err[t+':dangling_court_id']+=1
    if t=='forms' and (not r.get('file_sha256') or r.get('file_stored')):err['forms:sha_or_stored']+=1
    if r['coverage'] not in('complete','partial_host_stopped','partial_guard_stop','blocked'):err['bad_cov']+=1
rep['validation_errors']=dict(err);rep['flags']={k:dict(v) for k,v in flags.items()}
# unify keys
for t in T:
  rows=hub[t]+out[t];keys=[]
  for r in rows:
    for k in r:
      if k not in keys:keys.append(k)
  with open(f'{H}/data/{t}.jsonl','w') as fh:
    for r in rows:fh.write(json.dumps({k:r.get(k) for k in keys},ensure_ascii=False)+'\n')
json.dump(rep,open(O+'/report.json','w'),indent=1);print(json.dumps(rep,indent=1))
