#!/usr/bin/env python3
"""Resume: KS (skip done URLs), NE (remaining candidates), DE (one more parser look). Stage only."""
import sys,os,json,re,urllib.parse
sys.path.insert(0,'/workspace/courts/collector')
import us_fed as U, state_rules3 as S3
from us_fed import log,fetch,sid,now
O='/workspace/courts/staging/state_rules_rerun';OFF='/workspace/courts/staging/state_rules/official'
RULE=re.compile(r'rule|court-rules|courtrules|procedure|\.pdf',re.I)
def ids(*fs):
  s=set()
  for f in fs:
    if os.path.exists(f):
      for l in open(f):
        r=json.loads(l);s.add(r['rule_id']);s.add(r.get('file_url',''))
  return s
def run(st,idx,skip):
  r=fetch(idx,delay=10)
  if not r:log('STATE_FAIL',st);open(O+'/skips.jsonl','a').write(json.dumps(dict(state=st,url=idx,reason='index fetch fail/robots (resume)'))+'\n');return
  host=urllib.parse.urlsplit(r[0]).netloc
  cand=list(dict.fromkeys(h.split('#')[0] for h,t in S3.safe_links(r[0],r[1]) if h.startswith('https://') and urllib.parse.urlsplit(h).netloc==host and RULE.search(h+' '+t) and h.split('#')[0]!=r[0]))
  tmap={h.split('#')[0]:t for h,t in S3.safe_links(r[0],r[1])}
  todo=[h for h in cand if sid(st,h) not in skip and h not in skip]
  log('STATE',st,'candidates',len(cand),'already_done',len(cand)-len(todo),'todo',len(todo))
  if st=='DE' and not cand:
    open(O+'/skips.jsonl','a').write(json.dumps(dict(state='DE',url=idx,reason='no_static_links'))+'\n');return
  n=0
  with open(f'{O}/{st}_resume.jsonl','a') as o:
    for h in todo:
      fn=f'{O}/files/{st}_{sid(h)}';g=fetch(h,delay=10,stream_to=fn)
      if not g:continue
      fu,sha,nb=g
      o.write(json.dumps(dict(rule_id=sid(st,h),rule_set=f'{st} court rules',citation='',title=tmap.get(h,''),text=None,court_id=None,subdivision_iso='US-'+st,effective_date=None,version='',file_url=fu,file_sha256=sha,file_bytes=nb,local_path=fn,content_sha256=sha,source_url=r[0],fetched_at=now(),archive_source='live',archive_timestamp=None,license='see source terms (state-specific)',terms_note='',robots_note='robots.txt honored',transport='https'))+'\n');o.flush();n+=1
  log('STATE',st,'resume rows',n)
if __name__=='__main__':
  log('STATE_RULES4 START pid',os.getpid())
  for st,u in [('NE','https://nebraskajudicial.gov/supreme-court-rules'),('DE','https://courts.delaware.gov/rules/'),('KS','https://www.kscourts.gov/Rules-Orders/Rules')]:
    try:run(st,u,ids(f'{OFF}/{st}.jsonl',f'{O}/{st}.jsonl',f'{O}/{st}_resume.jsonl'))
    except SystemExit:raise
    except Exception as e:log('STATE_ERR',st,repr(e)[:200])
  log('STATE_RULES4 DONE')
