"""Common Crawl gap fill for TX/MO/KY counties with docs=0 from the direct site crawl.
ONLY index.commoncrawl.org CDX lookups (cached per county/crawl) + single-record ranged WARC reads from data.commoncrawl.org.
Polite: >=3 s between CDX queries, >=1.5 s between WARC reads, backoff on 503/429. TLS verified. No bulk downloads.
Robots: live robots.txt of the county host fetched once; URLs explicitly disallowed for our UA, '*' or CCBot are skipped;
if robots unreachable the row is marked robots_live='unverified' (CCBot honored robots at crawl time).
Resumable: raw/commoncrawl/done.txt, cdx cache raw/commoncrawl/cdx/. Usage: cc_gap.py MAX_SECONDS MAX_BYTES"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,re,json,time,gzip,hashlib,subprocess,urllib.parse,urllib.robotparser,requests
from bs4 import BeautifulSoup
B=(str(_CORPORA) + '/county/US'); RAW=B+'/raw/commoncrawl'; os.makedirs(RAW+'/pdf',exist_ok=True); os.makedirs(RAW+'/cdx',exist_ok=True)
MAXS=float(sys.argv[1]); MAXB=float(sys.argv[2]); T0=time.time()
UA="Mozilla/5.0 (compatible; EndomorphosisCountyLawsBot/1.0; +https://huggingface.co/endomorphosis)"
CRAWLS=['CC-MAIN-2026-43','CC-MAIN-2026-39','CC-MAIN-2026-34','CC-MAIN-2026-30']
KW=re.compile(r'ordinance|code-of|code_of|codeof|county-code|codified|regulation|resolution|court-?order|order|subdivision|floodplain|flood-?plain|burn-?ban|charter|bylaw|rules|zoning|policy|policies|septic|on-?site|sewage|fireworks|animal-?control',re.I)
BAD=re.compile(r'agenda|minutes|bid|rfp|employ|job|calendar|newsletter|press|application|budget|audit|facebook|twitter|login|signin|payment|\.(jpg|jpeg|png|gif|css|js|ico|svg|woff2?|xml|zip|docx?|xlsx?)(\?|$)|/wp-(json|includes|content/themes)|/feed/?$|robots\.txt',re.I)
URLRX='~url:(?i).*(ordinance|code|regulation|resolution|order|subdivision|flood|burn|charter|bylaw|rules|zoning|polic|septic|sewage|fireworks|animal).*'
PER_COUNTY_DOCS=15; PER_COUNTY_FETCH=30
S=requests.Session(); S.headers['User-Agent']=UA
def log(*a): print(time.strftime('%H:%M:%S'),*a,flush=True)
def free_gib(): s=os.statvfs('/'); return s.f_bavail*s.f_frsize/2**30
def dirbytes():
    n=0
    for r,_,fs in os.walk(RAW):
        for f in fs: n+=os.path.getsize(os.path.join(r,f))
    return n
_last={}
def wait(k,d):
    w=_last.get(k,0)+d-time.time()
    if w>0: time.sleep(w)
    _last[k]=time.time()
def cc_get(url,key,delay,**kw):
    for i in range(6):
        wait(key,delay)
        try: r=S.get(url,timeout=90,**kw)
        except Exception as e: log('neterr',key,str(e)[:80]); time.sleep(20*(i+1)); continue
        _last[key]=time.time()
        if r.status_code in (429,500,502,503,504): log('backoff',key,r.status_code); time.sleep(30*(i+1)); continue
        return r
    return None
def read_jsonl(p):
    """Tolerant jsonl reader: skips (and logs) corrupt/truncated lines instead of crashing."""
    out=[]
    for i,l in enumerate(open(p,errors='replace')):
        if not l.strip(): continue
        try: out.append(json.loads(l))
        except ValueError as e: log('WARN corrupt jsonl line skipped',os.path.basename(p),'line',i+1,str(e)[:60])
    return out
def parse_cdx_body(text):
    rows=[]; bad=0; lines=[l for l in text.splitlines() if l.strip()]
    for i,l in enumerate(lines):
        try: rows.append(json.loads(l))
        except ValueError: bad+=1
    return rows,bad,len(lines)
def cdx(host,crawl,geoid):
    p=f'{RAW}/cdx/{geoid}_{crawl}_{host.replace("/","_")}_v2.jsonl'
    if os.path.exists(p): return read_jsonl(p)
    q=dict(url=host.rstrip('/')+'/*',output='json',limit='8000')  # SURT prefix: covers www/non-www; filtering client-side
    q=urllib.parse.urlencode(q,doseq=True)
    for attempt in range(3):
        r=cc_get(f'https://index.commoncrawl.org/{crawl}-index?{q}','cdx',3.0)
        if r is None: raise RuntimeError('cdx unavailable')
        if r.status_code==404: rows=[]; break
        elif r.status_code!=200: raise RuntimeError(f'cdx http{r.status_code}')
        rows,bad,nl=parse_cdx_body(r.text)
        if not bad: break
        # truncated/garbled live CDX body (server closed connection mid-stream): never cache a partial result
        log('WARN cdx body truncated/corrupt',geoid,crawl,f'{bad}/{nl} bad lines; retry',attempt+1); time.sleep(30*(attempt+1))
    else: raise RuntimeError('cdx body truncated')  # county not marked done -> retried later
    tmp=p+'.part'  # atomic write (same dir, not /tmp) so a restart can't leave a truncated cache file
    with open(tmp,'w') as f:
        for x in rows: f.write(json.dumps(x)+'\n')
    os.replace(tmp,p)
    return rows
_robots={}
def robots(base):
    if base in _robots: return _robots[base]
    rp=urllib.robotparser.RobotFileParser(); st='unverified'; sig=''
    try:
        r=requests.get(base+'/robots.txt',headers={'User-Agent':UA},timeout=20)
        if r.status_code==200 and '<html' not in r.text[:500].lower(): rp.parse(r.text.splitlines()); st='checked'; sig='; '.join(re.findall(r'(?im)^\s*content-signal\s*:\s*(.+)$',r.text))
        elif r.status_code in (404,410): rp.parse([]); st='none(404)'
        else: rp=None
    except Exception: rp=None
    _robots[base]=(rp,st,sig); return _robots[base]
def allowed(url):
    p=urllib.parse.urlparse(url); rp,st,sig=robots(f'{p.scheme}://{p.netloc}')
    if rp is None: return True,'unverified',sig
    ok=rp.can_fetch(UA,url) and rp.can_fetch('*',url) and rp.can_fetch('CCBot',url)
    return ok,st,sig
def warc(rec):
    off=int(rec['offset']); ln=int(rec['length'])
    r=cc_get('https://data.commoncrawl.org/'+rec['filename'],'warc',1.5,headers={'Range':f'bytes={off}-{off+ln-1}'})
    if r is None or r.status_code!=206: return None
    raw=gzip.decompress(r.content); wh,_,rest=raw.partition(b'\r\n\r\n'); hh,_,body=rest.partition(b'\r\n\r\n')
    return wh.decode('latin-1'),hh.decode('latin-1'),body
def html_text(h):
    s=BeautifulSoup(h,'lxml')
    for t in s(['script','style','nav','footer','header','form','noscript']): t.decompose()
    return re.sub(r'\n\s*\n+','\n\n',s.get_text('\n')).strip(), (s.title.string.strip() if s.title and s.title.string else '')
done=set(open(RAW+'/done.txt').read().split()) if os.path.exists(RAW+'/done.txt') else set()
PRIV_ONLY=re.compile(r'privacy|terms of (use|service)|cookie',re.I)
def _nonpriv_have():
    by={}
    for d in read_jsonl(B+'/raw/county_sites/docs.jsonl'):
        by.setdefault(d['geoid'],[]).append(d)
    out=set()
    for g,rows in by.items():
        if any(not PRIV_ONLY.search(((r.get('title') or '')+' '+(r.get('url') or '')).lower()) for r in rows):
            out.add(g)
    return out
have=_nonpriv_have()
order={'TX':0,'MO':1,'KY':2}
T=sorted([t for t in json.load(open(B+'/raw/targets_tx_mo_ky_wikidata.json')) if t['geoid'] not in have],key=lambda x:(order[x['state']],x['geoid']))
miss={r['geoid'] for r in json.load(open((str(_CORPORA) + '/county/_ref/us_counties_missing_from_aml_20261027.json')))}
docs=open(RAW+'/docs.jsonl','a'); skips=open(RAW+'/skips.jsonl','a')
def skip(**k): skips.write(json.dumps(k)+'\n'); skips.flush()
log('targets',len(T),'done',len(done))
for c in T:
    if c['geoid'] in done or c['geoid'] not in miss: continue
    if time.time()-T0>MAXS or dirbytes()>MAXB: log('checkpoint stop'); break
    if free_gib()<10.5: log('DISK FLOOR stop'); break
    if not c['sites']: skip(geoid=c['geoid'],reason='no website'); open(RAW+'/done.txt','a').write(c['geoid']+'\n'); continue
    cand={}
    try:
        for site in c['sites']:
            pu=urllib.parse.urlparse(site); host=pu.netloc.lower(); host=host[4:] if host.startswith('www.') else host
            if pu.path.strip('/'): host=host+'/'+pu.path.strip('/')+'/'
            for crawl in CRAWLS:
                for x in cdx(host,crawl,c['geoid']):
                    u=x['url']; path=urllib.parse.urlparse(u).path+'?'+urllib.parse.urlparse(u).query
                    if x.get('status')!='200': continue
                    mime=(x.get('mime-detected') or x.get('mime') or '').lower()
                    if not ('html' in mime or 'pdf' in mime): continue
                    if not KW.search(path) or BAD.search(path): continue
                    k=u.split('#')[0].replace('http://','https://').replace('://www.','://')
                    if k not in cand or x['timestamp']>cand[k]['timestamp']: x['crawl']=crawl; cand[k]=x
                if len(cand)>=PER_COUNTY_FETCH*2: break
    except RuntimeError as e:
        log(c['geoid'],c['name'],'CDX FAIL',e); skip(geoid=c['geoid'],reason='cdx '+str(e)); continue  # not marked done -> retried on restart
    ranked=sorted(cand.values(),key=lambda x:(0 if 'pdf' in (x.get('mime-detected') or x.get('mime','')) else 1, -len(KW.findall(x['url'])), len(x['url'])))
    n=0; f=0
    for x in ranked:
        if n>=PER_COUNTY_DOCS or f>=PER_COUNTY_FETCH: break
        ok,rst,sig=allowed(x['url'])
        if not ok: skip(geoid=c['geoid'],url=x['url'],reason='robots (live) disallow'); continue
        f+=1; w=warc(x)
        if w is None: skip(geoid=c['geoid'],url=x['url'],reason='warc read failed'); continue
        wh,hh,body=w; h=hashlib.sha256(x['url'].encode()).hexdigest()[:12]
        trunc=re.search(r'(?im)^WARC-Truncated:\s*(\S+)',wh)
        ct=(re.search(r'(?im)^content-type:\s*([^\r\n]+)',hh) or [None,''])[1].lower()
        if 'pdf' in ct or body[:5]==b'%PDF-':
            if trunc: skip(geoid=c['geoid'],url=x['url'],reason='cc truncated pdf ('+trunc.group(1)+')'); continue
            pp=f'{RAW}/pdf/{c["geoid"]}_{h}.pdf'; open(pp,'wb').write(body)
            txt=subprocess.run(['pdftotext','-layout',pp,'-'],capture_output=True,text=True).stdout.strip(); kind='pdf'; title=''
            if len(txt)<200: skip(geoid=c['geoid'],url=x['url'],reason='image-only pdf (ocr pending)',pdf=pp); continue
        elif 'html' in ct:
            txt,title=html_text(body); kind='html'; pp=''
            if len(txt)<500: continue
        else: continue
        docs.write(json.dumps(dict(geoid=c['geoid'],gnis=c['gnis'],state=c['state'],county=c['name'],qid=c['qid'],url=x['url'],title=title or urllib.parse.unquote(x['url'].rstrip('/').rsplit('/',1)[-1]),kind=kind,text=txt,
            fetched=time.strftime('%Y-%m-%dT%H:%M:%S%z'),site=c['sites'][0],content_signal=sig,pdf=pp,fetch_via='commoncrawl',cc_crawl=x['crawl'],cc_timestamp=x['timestamp'],
            warc_filename=x['filename'],warc_offset=x['offset'],warc_length=x['length'],robots_live=rst,warc_truncated=bool(trunc)))+'\n'); docs.flush(); n+=1
    open(RAW+'/done.txt','a').write(c['geoid']+'\n'); log(c['geoid'],c['state'],c['name'],'cand',len(cand),'fetched',f,'docs',n)
log('end')
