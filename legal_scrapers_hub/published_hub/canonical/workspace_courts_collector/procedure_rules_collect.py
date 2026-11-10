#!/usr/bin/env python3
"""Memsafe wrapper for state_procedure_rules_scraper source registry (CoS GO 2026-11-04).
Reads the scraper's per-state source tables via AST (no import: no fallbacks, no scrape_state_laws,
no IPFS cache, no curl). Single worker, HTTPS only, TLS verify on, robots honored, >=10s/host,
stop host on first 403/429/challenge, no retries. Stores url+sha256+metadata only."""
import ast,hashlib,json,os,re,shutil,sys,threading,time,urllib.parse as up,urllib.robotparser as rp
from datetime import datetime
import requests
SRC='/workspace/ipfs_datasets_py_latest/ipfs_datasets_py/processors/legal_scrapers/state_procedure_rules_scraper.py'
OUT=os.environ.get('PR_OUT','/workspace/courts/staging/procedure_rules'); os.makedirs(OUT,exist_ok=True)
LOG=open(os.environ.get('PR_LOG','/workspace/courts/logs/procedure_rules.log'),'a',buffering=1)
UA='justicedao-courts-collector/1.0 (public court data; polite 1 req/10s)'
EXCL=set('CA IL OR WA WI CT VA KS CO MS ND NV MN SC DC MA NC NH NJ NY LA PR TN MO OK'.split())
PRIVATE=('westlaw.com','lexis','casetext','justia.com','findlaw','fastcase')
MEMFLOOR=float(os.environ.get('SC_MEMFLOOR','4.2')); MAXSTRIKES=int(os.environ.get('SC_MAXSTRIKES','3')); DISKFLOOR=float(os.environ.get('CC_DISKFLOOR_G','20'))
MINDELAY=10.0; STOP=threading.Event(); RC=[0]
def now(): return datetime.now().astimezone().isoformat(timespec='seconds')
def log(*a): LOG.write(now()+' '+' '.join(map(str,a))+'\n')
def memavail(): return int(next(l for l in open('/proc/meminfo') if l.startswith('MemAvailable')).split()[1])/1048576
def guard():
  s=0
  while not STOP.is_set():
    m=memavail(); d=shutil.disk_usage('/workspace').free/2**30
    if d<DISKFLOOR: log('DISKGUARD',f'{d:.1f}G'); RC[0]=4; STOP.set(); return
    if m<MEMFLOOR: s+=1; log('MEMGUARD strike',s,f'{m:.2f}G')
    else: s=0
    if s>=MAXSTRIKES: log('MEMGUARD 3 strikes: clean stop'); RC[0]=3; STOP.set(); return
    time.sleep(20)
def sources():
  t=ast.parse(open(SRC).read()); res={}
  for n in t.body:
    tg=n.targets[0] if isinstance(n,ast.Assign) else (n.target if isinstance(n,ast.AnnAssign) else None)
    if not isinstance(tg,ast.Name) or n.value is None: continue
    mm=re.match(r'_([A-Z]{2})_',tg.id)
    if not mm: continue
    try: v=ast.literal_eval(n.value)
    except Exception: continue
    st=mm.group(1); items=[]
    if isinstance(v,str) and v.startswith('http'): items=[{'name':tg.id,'url':v}]
    elif isinstance(v,list): items=[dict(x,_var=tg.id) for x in v if isinstance(x,dict) and isinstance(x.get('url'),str)]
    for it in items: res.setdefault(st,[]).append(it)
  return res
HOSTS={}; BLK=f'{OUT}/blocked_hosts.json'
blocked=json.load(open(BLK)) if os.path.exists(BLK) else {}
def hostinfo(h):
  if h in HOSTS: return HOSTS[h]
  H={'last':0,'delay':MINDELAY,'rp':None}; HOSTS[h]=H
  wait(H)
  try:
    r=requests.get(f'https://{h}/robots.txt',headers={'User-Agent':UA},timeout=30); H['last']=time.time()
    log('ROBOTS',h,r.status_code)
    if r.status_code in (403,429): block(h,f'robots {r.status_code}')
    elif r.status_code==200:
      p=rp.RobotFileParser(); p.parse(r.text.splitlines()); H['rp']=p
      cd=p.crawl_delay(UA) or p.crawl_delay('*')
      if cd: H['delay']=max(MINDELAY,float(cd))
  except requests.RequestException as e: H['last']=time.time(); log('ROBOTSERR',h,type(e).__name__)
  return H
def wait(H):
  dt=H['last']+H['delay']-time.time()
  while dt>0 and not STOP.is_set(): time.sleep(min(dt,5)); dt=H['last']+H['delay']-time.time()
def block(h,why): blocked[h]=why; json.dump(blocked,open(BLK,'w'),indent=1); log('BLOCK',h,why)
CHAL=re.compile(rb'captcha|cf-challenge|challenge-platform|Just a moment|Access Denied|Request Rejected|incapsula|px-captcha',re.I)
def fetch(url):
  p=up.urlparse(url); h=p.netloc.lower()
  if p.scheme!='https': return None,'non_https_skipped'
  if any(x in h for x in PRIVATE): return None,'private_publisher_skipped'
  if h in blocked: return None,'host_blocked'
  H=hostinfo(h)
  if h in blocked: return None,'host_blocked'
  if H['rp'] and not H['rp'].can_fetch(UA,url): return None,'robots_disallow'
  wait(H)
  if STOP.is_set(): return None,'stopped'
  try:
    r=requests.get(url,headers={'User-Agent':UA},timeout=90,stream=True,verify=True); H['last']=time.time()
    sha=hashlib.sha256(); n=0; head=b''
    for c in r.iter_content(65536):
      sha.update(c); n+=len(c)
      if len(head)<20000: head+=c[:20000-len(head)]
      if n>80*2**20: break
    r.close()
  except requests.RequestException as e: H['last']=time.time(); log('NETERR',url,type(e).__name__); return None,'neterr'
  log('GET',r.status_code,n,url)
  if r.status_code in (403,429) or (r.status_code!=200 and CHAL.search(head)) or (b'<html' in head[:2000].lower() and CHAL.search(head) and n<30000):
    block(h,f'{r.status_code} at {url}'); return None,f'blocked_{r.status_code}'
  if r.status_code!=200: return None,f'http_{r.status_code}'
  return {'final_url':r.url,'sha256':sha.hexdigest(),'bytes':n,'content_type':r.headers.get('content-type','').split(';')[0],'last_modified':r.headers.get('last-modified')},'ok'
def fam(it):
  s=(it.get('name','')+' '+it.get('_var','')+' '+it['url']).lower()
  return 'criminal' if re.search(r'crim|crr|crp',s) else 'civil' if re.search(r'civ|\bcr\b|rcp|cp-',s) else 'court_rules'
def main(states):
  srcs=sources(); ck=f'{OUT}/ckpt.json'; C=json.load(open(ck)) if os.path.exists(ck) else {'done':[]}
  allst=sorted(srcs); inc=[s for s in allst if s not in EXCL]; exc=[s for s in allst if s in EXCL]
  if states: inc=[s for s in states if s in inc]
  json.dump({'included':inc,'excluded_policy':exc,'private_skipped':PRIVATE},open(f'{OUT}/plan.json','w'),indent=1)
  log('PR START pid',os.getpid(),'states',inc,'excluded',exc)
  threading.Thread(target=guard,daemon=True).start()
  for st in inc:
    if STOP.is_set(): break
    if st in C['done']: continue
    rows=[];cnt={}
    for it in srcs[st]:
      if STOP.is_set(): break
      meta,status=fetch(it['url']); cnt[status]=cnt.get(status,0)+1
      if meta: rows.append({'state':st,'jurisdiction':f'US-{st}','rule_set':it.get('name') or it.get('title') or it['_var'],'family':fam(it),'source_url':it['url'],**meta,'source':'official','transport':'https','fetched_at':now(),'registry':'state_procedure_rules_scraper.'+it.get('_var','')})
    if STOP.is_set(): log('STATE',st,'interrupted',cnt); break
    with open(f'{OUT}/{st}.jsonl','w') as f:
      for r in rows: f.write(json.dumps(r,sort_keys=True)+'\n')
    C['done'].append(st); C[st]=cnt; json.dump(C,open(ck,'w'),indent=1); log('STATE',st,'DONE',cnt)
  STOP.set(); return RC[0]
if __name__=='__main__': sys.exit(main(sys.argv[1:]))
