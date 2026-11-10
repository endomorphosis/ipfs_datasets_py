#!/usr/bin/env python3
"""Resume CC archive recovery from state: cached CDX per state, skip URLs already staged. Stage only."""
import sys,os,json,re,datetime
sys.path.insert(0,'/workspace/courts/collector')
import archive_rules as A
from us_fed import log,sid,now
O=A.O;ST=O+'/resume_state.json';C=O+'/cdx_cache'
os.makedirs(C,exist_ok=True)
def save(s):json.dump(s,open(ST+'.tmp','w'),indent=1);os.replace(ST+'.tmp',ST)
s=json.load(open(ST)) if os.path.exists(ST) else dict(done=['TN','LA','MI','SD','OK'],todo=['DE','WY'])
save(s)
log('RESUME START pid',os.getpid(),s)
for st in list(s['todo']):
  cf=f'{C}/{st}.json'
  if os.path.exists(cf):best=json.load(open(cf));log('STATE',st,'cdx from cache',len(best))
  else:
    best={};complete=True
    for idx in A.IDX:
      for pat in A.STATES[st]:
        got=False
        for c in A.cdx(idx,pat):
          got=True;u=c['url']
          if not u.startswith('https://'):continue
          if not re.search(r'rule|pdf|download|Statutes|STOKRU|DocumentID',u,re.I):continue
          k=u.split('#')[0]
          if k not in best or c['timestamp']>best[k]['timestamp']:best[k]=dict(c,_idx=idx)
    if best:json.dump(best,open(cf,'w'))
    log('STATE',st,'cdx unique urls',len(best),'cached')
  if not best:
    open(O+'/skips.jsonl','a').write(json.dumps(dict(state=st,reason='no Common Crawl captures matched'))+'\n')
  have=set()
  if os.path.exists(f'{O}/{st}.jsonl'):
    for l in open(f'{O}/{st}.jsonl'):
      try:have.add(json.loads(l)['original_url'])
      except Exception:pass
  n=0
  with open(f'{O}/{st}.jsonl','a') as o:
    for k,c in sorted(best.items())[:A.CAP]:
      if k in have:continue
      fn=f'{O}/files/{st}_{sid(k)}';g=A.fetch_warc(c,fn)
      if not g:continue
      sha,nb=g;cap=datetime.datetime.strptime(c['timestamp'],'%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc).isoformat()
      o.write(json.dumps(dict(rule_id=sid(st,k),rule_set=f'{st} court rules',citation='',title='',text=None,court_id=None,subdivision_iso='US-'+st,effective_date=None,version='',file_url=k,original_url=k,file_sha256=sha,file_bytes=nb,mime=c.get('mime'),local_path=fn,content_sha256=sha,source='archive',source_url=k,fetched_at=now(),archive_source='commoncrawl',archive_timestamp=cap,archive_index=c['_idx'],warc_filename=c['filename'],warc_offset=int(c['offset']),warc_length=int(c['length']),cc_digest=c.get('digest'),license='see source terms (state-specific; archived copy)',terms_note='Common Crawl terms of use apply to archive access',robots_note='archive fetch (CC); original site robots not applicable',transport='https'))+'\n');o.flush();n+=1;have.add(k)
  log('STATE',st,'new rows',n,'total',len(have))
  s['todo'].remove(st);s['done'].append(st);save(s)
log('ARCHIVE RESUME DONE')
