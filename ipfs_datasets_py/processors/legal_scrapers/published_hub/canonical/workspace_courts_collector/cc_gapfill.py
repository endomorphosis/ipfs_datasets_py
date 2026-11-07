#!/usr/bin/env python3
"""CC gap-fill for state/county courthouse data: AL ND WV PA. CDX + WARC range fetch only (index.commoncrawl.org, data.commoncrawl.org).
Stage only, no push. memguard 4.2G/3 strikes -> exit 3. disk free<12G -> exit 4. Every row: source=archive, archive_source=commoncrawl."""
import sys,os,json,re,time,zlib,hashlib,datetime,urllib.parse as up,collections
sys.path.insert(0,'/workspace/courts/collector')
import requests
from bs4 import BeautifulSoup
import state_county as S
B='/workspace/courts';O=f'{B}/staging/state_county_cc';os.makedirs(O,exist_ok=True)
S.LOG=open(f'{B}/logs/cc_gapfill.log','a',buffering=1);log=S.log
HL=open(f'{O}/page_filter_log.jsonl','a',buffering=1)
IDX=['CC-MAIN-2026-43','CC-MAIN-2026-30','CC-MAIN-2025-51']
HOSTS={'AL':['judicial.alabama.gov','www.alacourt.gov','alacourt.gov'],'ND':['www.ndcourts.gov','ndcourts.gov'],
       'WV':['www.courtswv.gov','courtswv.gov'],'PA':['www.pacourts.us','pacourts.us'],
       'CO':['www.coloradojudicial.gov','coloradojudicial.gov'],'MS':['courts.ms.gov','www.courts.ms.gov'],'MN':['mncourts.gov','www.mncourts.gov'],
       'NM':['nmcourts.gov','www.nmcourts.gov'],'FL':['www.flcourts.gov','flcourts.gov']}
STATES=sys.argv[1:] or ['AL','ND','WV','PA']
CAP_HTML=int(os.environ.get('CC_CAP_HTML','120'));CAP_FORMS=250;MAXB=5*2**20;DELAY=10;MEMFLOOR=float(os.environ.get('SC_MEMFLOOR','4.2'));MAXSTRIKES=int(os.environ.get('SC_MAXSTRIKES','3'));last=[0];strikes=[0]
sess=requests.Session();sess.headers['User-Agent']='Mozilla/5.0 (compatible; justicedao-court-research/0.2; archive gap-fill)'
def guard():
  while True:
    ma=S.memavail()
    if ma>=MEMFLOOR: break
    strikes[0]+=1;S.strikes[0]=strikes[0];log(f'MEMGUARD strike {strikes[0]} MemAvailable={ma:.2f}G');S.memstrike_top5()
    if strikes[0]>=MAXSTRIKES: log(f'MEMGUARD {MAXSTRIKES} strikes: clean stop');sys.exit(3)
    time.sleep(60)
  st=os.statvfs(B)
  if st.f_bavail*st.f_frsize<float(os.environ.get('CC_DISKFLOOR_G','12'))*2**30: log('DISKGUARD free<floor stop');sys.exit(4)
def get(u,rng=None,stream=False):
  for i in range(6):
    guard();w=last[0]+DELAY-time.time()
    if w>0: time.sleep(w)
    last[0]=time.time();h={'Range':rng} if rng else {}
    try:
      r=sess.get(u,headers=h,stream=stream,timeout=(15,60))
      if r.status_code in (429,500,502,503,504):
        b=min(60*2**i,1800);log('BACKOFF',r.status_code,b,u[:110]);r.close();time.sleep(b);continue
      if r.status_code not in (200,206): log('HTTP',r.status_code,u[:110]);r.close();return None
      return r
    except requests.RequestException as e:
      b=min(30*2**i,900);log('NETERR',repr(e)[:100],'sleep',b);time.sleep(b)
  log('GIVEUP',u[:110]);return None
FORM_RX=re.compile(r'\.(pdf|docx?|rtf|xlsx?|odt)$',re.I)
FORM_HINT=re.compile(r'form',re.I)
TAB_RX={'judges':re.compile(r'judge|justice|magistrate|roster|bench|biograph',re.I),
        'courthouses':re.compile(r'courthouse|location|directory|county|contact|address|find-?a-?court|district|circuit|magisterial',re.I)}
NEG=re.compile(r'opinion|calendar|docket|news|press|career|job|employ|search|login|event|rule|order|\?.*page=',re.I)
def cdx(host):
  best={}
  for idx in IDX:
    u=f'https://index.commoncrawl.org/{idx}-index?'+up.urlencode(dict(url=host+'/*',output='json',filter='status:200',limit='20000'))
    r=get(u,stream=True)
    if not r: continue
    try:
     for l in r.iter_lines():
      try:c=json.loads(l)
      except Exception:continue
      k=c['url'].split('#')[0]
      if not k.startswith('https://'): continue
      if k not in best or c['timestamp']>best[k]['timestamp']: best[k]=dict(c,_idx=idx)
    except Exception as e: log('CDXSTREAMERR',idx,host,repr(e)[:120],'kept partial',len(best))
    r.close()
  return best
def warc_body(c,limit=None,sink=None):
  off,ln=int(c['offset']),int(c['length'])
  r=get('https://data.commoncrawl.org/'+c['filename'],rng=f'bytes={off}-{off+ln-1}',stream=True)
  if not r: return None
  d=zlib.decompressobj(16+zlib.MAX_WBITS);buf=b'';hd=False;h=hashlib.sha256();n=0;keep=[]
  for ch in r.iter_content(65536):
    x=d.decompress(ch)
    if not hd:
      buf+=x;p=buf.find(b'\r\n\r\n');q=buf.find(b'\r\n\r\n',p+4) if p>=0 else -1
      if q<0: continue
      x=buf[q+4:];hd=True;buf=b''
    h.update(x);n+=len(x)
    if limit is not None and n<=limit: keep.append(x)
  r.close();return h.hexdigest(),n,b''.join(keep)
def arch(c,sha):
  ts=datetime.datetime.strptime(c['timestamp'],'%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc).isoformat()
  u=c['url'].split('#')[0]
  return dict(source='archive',source_url=u,original_url=u,fetched_at=S.now(),archive_source='commoncrawl',archive_timestamp=ts,
    archive_index=c['_idx'],warc_filename=c['filename'],warc_offset=int(c['offset']),warc_length=int(c['length']),cc_digest=c.get('digest'),
    license=S.LIC+'; archived copy',terms_note='Common Crawl terms of use apply to archive access',robots_note='archive fetch (CC); original host not contacted',
    transport='https',content_sha256=sha,sha256=sha,coverage='archive_gapfill')
def page_decision(soup,nrows):
  for x in soup(['script','style','noscript','nav','header','footer']): x.decompose()
  t=soup.get_text(' ');tw=len(t.split()) or 1;aw=sum(len(a.get_text().split()) for a in soup.find_all('a'));ld=aw/tw
  if tw<80: return False,'too_short(<80 words)',tw,ld
  if nrows==0: return False,'no_extractable_rows',tw,ld
  if ld>0.5 and nrows<3: return False,'navigation(link_density>0.5 and <3 rows)',tw,ld
  return True,'kept(rows>0, not nav)',tw,ld
STF=f'{O}/state.json'
state=json.load(open(STF)) if os.path.exists(STF) else {'done':[]}
log('CC GAPFILL START pid',os.getpid(),STATES,'done',state['done'])
for st in STATES:
  if st in state['done']: continue
  cf=f'{O}/cdx_{st}.json'
  if os.path.exists(cf): best=json.load(open(cf))
  else:
    best={}
    for h in HOSTS[st]: best.update(cdx(h))
    json.dump(best,open(cf,'w'))
  log('STATE',st,'cdx unique https urls',len(best))
  forms=[(k,c) for k,c in sorted(best.items()) if FORM_RX.search(up.urlparse(k).path) and FORM_HINT.search(k)][:CAP_FORMS]
  html=[]
  for k,c in sorted(best.items()):
    if 'html' not in (c.get('mime') or '') or NEG.search(k): continue
    if TAB_RX['judges'].search(k) or TAB_RX['courthouses'].search(k): html.append((k,c))
  html=html[:CAP_HTML]
  out={t:open(f'{O}/{st}_{t}.jsonl','w') for t in ('courts','courthouses','judges','forms')}
  cnt=collections.Counter();courts={}
  for k,c in html:
    g=warc_body(c,limit=MAXB)
    if not g: continue
    sha,n,body=g
    if n>MAXB: HL.write(json.dumps(dict(state=st,url=k,keep=False,reason='too_large(>5MB)'))+'\n');continue
    soup=BeautifulSoup(body,'html.parser');A=arch(c,sha)
    js=S.ext_judges(st,k,sha,soup);ch=S.ext_courthouses(st,k,sha,soup)
    keep,why,tw,ld=page_decision(BeautifulSoup(body,'html.parser'),len(js)+len(ch))
    HL.write(json.dumps(dict(state=st,url=k,archive_timestamp=A['archive_timestamp'],keep=keep,reason=why,words=tw,link_density=round(ld,3),judges=len(js),courthouses=len(ch)))+'\n')
    if not keep: cnt['pages_dropped']+=1;continue
    cnt['pages_kept']+=1
    for t,rs in (('judges',js),('courthouses',ch)):
      for r in rs:
        r.update(A);r['role_type']='justice' if 'justice' in (r.get('title') or '').lower() else ('magistrate' if re.search('magistrate|commissioner',r.get('title') or '',re.I) else ('judge' if t=='judges' else None))
        if t!='judges': r.pop('role_type')
        out[t].write(json.dumps(r,ensure_ascii=False)+'\n');cnt[t]+=1
        nm=r.get('court_name') if t=='judges' else r.get('name')
        if r.get('court_id') and nm and r['court_id'] not in courts:
          courts[r['court_id']]=dict(court_id=r['court_id'],name=nm,name_local=nm,country='US',subdivision_iso=f'US-{st}',level=S.classify_level(nm),court_type=None,parent_court_id=None,url=k,**A)
  for r in courts.values(): out['courts'].write(json.dumps(r,ensure_ascii=False)+'\n');cnt['courts']+=1
  for k,c in forms:
    g=warc_body(c,limit=0)
    if not g: continue
    sha,n,_=g;A=arch(c,sha);fn=up.unquote(up.urlparse(k).path.rsplit('/',1)[-1]);m=S.FNUM.search(fn)
    out['forms'].write(json.dumps(dict(form_id=S.sid(st,k),form_number=m.group(1) if m else None,title=re.sub(r'\.[a-z]+$','',fn,flags=re.I),court_id=None,subdivision_iso=f'US-{st}',language='en',
      file_url=k,file_format=fn.rsplit('.',1)[-1].lower(),file_sha256=sha,file_cid=None,file_bytes=n,effective_date=None,last_modified=None,file_stored=False,**A),ensure_ascii=False)+'\n');cnt['forms']+=1
  for f in out.values(): f.close()
  log('STATE',st,'DONE',dict(cnt));state['done'].append(st);state[st]=dict(cnt)
  json.dump(state,open(STF+'.tmp','w'));os.replace(STF+'.tmp',STF)
log('CC GAPFILL DONE',state)
