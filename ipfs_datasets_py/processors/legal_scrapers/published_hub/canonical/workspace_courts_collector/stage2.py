#!/usr/bin/env python3
"""Chained after us_fed.py (same slot): courts retry, courthouses, state rules, review package."""
import os,sys,time,json,re,glob,hashlib,collections,asyncio,urllib.parse
sys.path.insert(0,'/workspace/courts/collector')
import us_fed as U
from us_fed import log,fetch,links,prov,sid,ST,memguard
WAIT=int(sys.argv[1]) if __name__=="__main__" and len(sys.argv)>1 else 0
def wait():
  while WAIT and os.path.exists(f'/proc/{WAIT}'):time.sleep(30)
  log('predecessor done',WAIT)
def courts_retry():
  u='https://www.uscourts.gov/about-federal-courts/court-role-and-structure/court-website-links'
  r=fetch(u,timeout=180)
  if not r:log('COURTS_RETRY_FAIL');return []
  out=open(f'{ST}/courts.jsonl','w');rows=[];seen=set()
  for h,t in links(r[0],r[1]):
    if not re.search(r'\.uscourts\.gov',h) or 'www.uscourts.gov' in h or not t:continue
    root=urllib.parse.urlsplit(h);root=f'{root.scheme}://{root.netloc}/'
    if root in seen:continue
    seen.add(root);rec=dict(court_id=sid('url',root),name=t,name_local=t,country='US',subdivision_iso=None,level='federal',court_type='',parent_court_id=None,url=root,**prov(r[0]))
    if root.startswith('http://'):rec['transport']='http_unreachable'
    out.write(json.dumps(rec)+'\n');rows.append(rec)
  out.close();log('courts rows',len(rows));return rows
ADDR=re.compile(r'(\d{1,6}\s+[A-Z0-9][\w .\'-]{2,60}?(?:Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Drive|Dr\.?|Way|Place|Pl\.?|Square|Plaza|Lane|Ln\.?|Court|Ct\.?|Parkway|Pkwy\.?|Mall|Center)\b[\w .,#-]{0,40}?),?\s+([A-Z][A-Za-z .\'-]{1,40}),\s+([A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)\.?\s+(\d{5}(?:-\d{4})?)')
ST2=json.load(open('/workspace/courts/collector/us_iso.json'))
AB={k.split('-')[1]:k for k in ST2};NM={v.lower():k for k,v in ST2.items()}
def text(b):
  s=re.sub(r'(?is)<(script|style).*?</\1>',' ',b.decode('utf-8','ignore'));s=re.sub(r'<br\s*/?>',', ',s);s=re.sub(r'<[^>]+>',' ',s);import html;return ' '.join(html.unescape(s).split())
def courthouses(courts):
  out=open(f'{ST}/courthouses.jsonl','a');sk=open(f'{ST}/skips.jsonl','a');n=0
  for c in courts:
    if c['url'].startswith('http://'):sk.write(json.dumps(dict(url=c['url'],reason='transport=http_unreachable'))+'\n');continue
    r=fetch(c['url'],delay=5)
    if not r:sk.write(json.dumps(dict(url=c['url'],reason='fetch_fail_or_robots'))+'\n');continue
    pages=[r]+[None]*0;cand=[h for h,t in links(r[0],r[1]) if re.search(r'locat|contact|courthouse|address|divisions|offices',h+' '+t,re.I) and urllib.parse.urlsplit(h).netloc==urllib.parse.urlsplit(r[0]).netloc][:3]
    for h in dict.fromkeys(cand):
      if not h.startswith('https://'):continue
      x=fetch(h,delay=5)
      if x:pages.append(x)
    seen=set()
    for pu,b in pages:
      for m in ADDR.finditer(text(b)):
        st=m.group(3);iso=AB.get(st) or NM.get(st.lower())
        if not iso:continue
        key=(m.group(1).lower()[:30],m.group(4))
        if key in seen:continue
        seen.add(key)
        out.write(json.dumps(dict(courthouse_id=sid(c['court_id'],*key),court_id=c['court_id'],name=c['name'],address_line=m.group(1).strip(' ,'),locality=m.group(2).strip(),postal_code=m.group(4),country='US',subdivision_iso=iso,lat=None,lon=None,content_sha256=hashlib.sha256(b).hexdigest(),**prov(pu)))+'\n');n+=1
    out.flush();sk.flush()
  out.close();log('courthouses rows',n)
SUPP=['AL','AR','GA','IA','IL','IN','LA','MA','MS','NC','PA','TN','TX','VA','WY']
def state_rules():
  d='/workspace/courts/staging/state_rules';os.makedirs(d,exist_ok=True)
  os.environ['HOME']=d+'/_home'
  sys.path[:0]=['/workspace/courts/pydeps','/workspace/ipfs_datasets_py_latest']
  from ipfs_datasets_py.processors.legal_scrapers.state_procedure_rules_scraper import scrape_state_procedure_rules as S
  memguard()
  res=asyncio.run(S(states=SUPP,max_rules=100000,include_metadata=True,rate_limit_delay=10.0,output_dir=d,write_jsonld=True,hydrate_rule_text=True,parallel_workers=1,per_state_retry_attempts=1,retry_zero_rule_states=False,per_state_timeout_seconds=7200.0))
  json.dump(res.get('metadata',{}) if isinstance(res,dict) else {},open(d+'/_run_metadata.json','w'),indent=1,default=str)
  log('state_rules done',str((res or {}).get('status'))[:100])
if __name__=='__main__':
  log('STAGE2 START pid',os.getpid());wait()
  for f in [lambda:courthouses(courts_retry()),state_rules]:
    try:f()
    except SystemExit:raise
    except Exception as e:log('STAGE_ERR',repr(e)[:300])
  import review;review.build();log('STAGE2 DONE')
