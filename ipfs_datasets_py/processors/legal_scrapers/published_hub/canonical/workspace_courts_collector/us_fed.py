#!/usr/bin/env python3
"""US federal court collector: stage only (no HF push). Keyless, TLS verified, robots honored."""
import csv,io,json,hashlib,re,sys,time,os,urllib.request,urllib.robotparser,urllib.parse,datetime
from html.parser import HTMLParser
ST='/workspace/courts/staging'; UA='Mozilla/5.0 (compatible; court-research-collector/0.1)'
US=json.load(open('/workspace/courts/collector/us_iso.json')) if os.path.exists('/workspace/courts/collector/us_iso.json') else {}
NAME2ISO={v.lower():k for k,v in US.items()}
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def log(*a):print(now(),*a,flush=True)
strikes=0
def memguard():
  global strikes
  while True:
    ma=int(re.search(r'MemAvailable:\s+(\d+)',open('/proc/meminfo').read()).group(1))*1024
    if ma>=2.5*2**30:return
    strikes+=1;log(f'MEMGUARD strike {strikes} MemAvailable={ma/2**30:.2f}G')
    if strikes>=3:log('MEMGUARD 3 strikes: clean stop');sys.exit(3)
    time.sleep(60)
RP={};LAST={}
def allowed(u):
  h=urllib.parse.urlsplit(u);base=f'{h.scheme}://{h.netloc}'
  if base not in RP:
    rp=urllib.robotparser.RobotFileParser();
    try:
      rq=urllib.request.Request(base+'/robots.txt',headers={'User-Agent':UA});rp.parse(urllib.request.urlopen(rq,timeout=30).read().decode('utf-8','ignore').splitlines())
    except Exception as e:log('robots fail',base,e);rp.parse([])
    RP[base]=rp
  return RP[base]
def fetch(u,delay=2,stream_to=None,timeout=60):
  memguard();rp=allowed(u)
  if not rp.can_fetch(UA,u):log('ROBOTS_DISALLOW',u);return None
  base=urllib.parse.urlsplit(u).netloc;d=max(delay,rp.crawl_delay(UA) or 0)
  w=LAST.get(base,0)+d-time.time()
  if w>0:time.sleep(w)
  LAST[base]=time.time()
  try:
    r=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':UA}),timeout=timeout)
    if stream_to:
      h=hashlib.sha256();n=0
      with open(stream_to,'wb') as f:
        while (c:=r.read(65536)):h.update(c);f.write(c);n+=len(c)
      return r.geturl(),h.hexdigest(),n
    b=r.read();return r.geturl(),b
  except Exception as e:log('FETCH_ERR',u,e);return None
class L(HTMLParser):
  def __init__(s):super().__init__();s.links=[];s.h=None;s.t=''
  def handle_starttag(s,t,a):
    if t=='a':s.h=dict(a).get('href');s.t=''
  def handle_data(s,d):
    if s.h is not None:s.t+=d
  def handle_endtag(s,t):
    if t=='a' and s.h:s.links.append((s.h,' '.join(s.t.split())));s.h=None
def links(base,b):
  p=L();p.feed(b.decode('utf-8','ignore'));return [(urllib.parse.urljoin(base,h),t) for h,t in p.links]
def prov(u,lic='public domain (US gov work)'):return dict(source_url=u,fetched_at=now(),archive_source='live',archive_timestamp=None,license=lic,terms_note='',robots_note='robots.txt honored',transport=urllib.parse.urlsplit(u).scheme)
def W(name):return open(f'{ST}/{name}.jsonl','a')
def sid(*a):return hashlib.sha1('|'.join(a).encode()).hexdigest()[:16]
def judges():
  u='https://www.fjc.gov/sites/default/files/history/judges.csv';r=fetch(u)
  if not r:return
  rd=csv.DictReader(io.StringIO(r[1].decode('utf-8-sig','ignore')));n=0;out=W('judges');P=prov(r[0])
  for row in rd:
    name=' '.join(x for x in [row.get('First Name'),row.get('Middle Name'),row.get('Last Name'),row.get('Suffix')] if x)
    for k in range(1,7):
      c=row.get(f'Court Name ({k})');
      if not c:continue
      t=row.get(f'Appointment Title ({k})','');term=row.get(f'Termination ({k})','')
      out.write(json.dumps(dict(judge_id=sid(row.get('jid',''),str(k)),full_name=name,court_id=sid('court',c),court_name=c,title=t,subdivision_iso=None,status='active' if not term else 'terminated',as_of=P['fetched_at'][:10],content_sha256=hashlib.sha256(r[1]).hexdigest(),**P))+'\n');n+=1
    if n%500==0:out.flush()
  out.close();log('judges rows',n)
def courts():
  u='https://www.uscourts.gov/about-federal-courts/federal-courts-public/court-website-links';r=fetch(u)
  if not r:return
  out=W('courts');n=0;seen=set()
  for h,t in links(r[0],r[1]):
    if re.search(r'\.uscourts\.gov',h) and 'www.uscourts.gov' not in h and h not in seen and t:
      seen.add(h);out.write(json.dumps(dict(court_id=sid('url',h),name=t,name_local=t,country='US',subdivision_iso=None,level='federal',court_type='',parent_court_id=None,url=h,**prov(r[0])))+'\n');n+=1
  out.close();log('courts rows',n,'(courthouse addresses: court finder is JS app; addresses TODO from per-court pages)')
def docs(index,kind,maxpages=80):
  r=fetch(index)
  if not r:return
  pages=[index]+[h for h,t in links(r[0],r[1]) if h.startswith(index.rstrip('/')+'/') ][:maxpages]
  seen=set();n=0;out=W(kind)
  for pg in dict.fromkeys(pages):
    rr=r if pg==index else fetch(pg)
    if not rr:continue
    for h,t in links(rr[0],rr[1]):
      if not re.search(r'\.pdf($|\?)',h,re.I) or h in seen:continue
      seen.add(h);fn=f'{ST}/files/{kind}_{sid(h)}.pdf';g=fetch(h,stream_to=fn)
      if not g:continue
      _,sha,nb=g;P=prov(pg)
      if kind=='forms':rec=dict(form_id=sid(h),form_number=(re.search(r'([A-Z]{1,4}[ -]?\d{1,4}[A-Z]?)',t) or [''])[0],title=t,court_id=None,subdivision_iso=None,language='en',file_url=h,file_format='pdf',file_sha256=sha,file_cid=None,file_bytes=nb,effective_date=None,local_path=fn,content_sha256=sha,**P)
      else:rec=dict(rule_id=sid(h),rule_set=pg.rsplit('/',1)[-1],citation='',title=t,text=None,court_id=None,subdivision_iso=None,effective_date=None,version='',file_url=h,file_sha256=sha,file_bytes=nb,local_path=fn,content_sha256=sha,**P)
      out.write(json.dumps(rec)+'\n');out.flush();n+=1
  out.close();log(kind,'rows',n)
def ncsc():
  r=fetch('https://www.ncsc.org/information-and-resources/state-court-websites',delay=10)
  if not r:return
  out=W('ncsc_state_links');n=0
  for h,t in links(r[0],r[1]):
    iso=NAME2ISO.get(t.lower().strip())
    if iso and 'ncsc.org' not in h:
      out.write(json.dumps(dict(subdivision_iso=iso,state=t,judiciary_url=h,**prov(r[0],'NCSC; link list, cite')))+'\n');n+=1
  out.close();log('ncsc state links',n,'final_url',r[0])
if __name__=='__main__':
  log('START pid',os.getpid())
  for f in [judges,courts,lambda:docs('https://www.uscourts.gov/forms-rules/forms','forms'),lambda:docs('https://www.uscourts.gov/forms-rules/current-rules-practice-procedure','rules'),ncsc]:
    try:f()
    except SystemExit:raise
    except Exception as e:log('STAGE_ERR',e)
  log('DONE')
