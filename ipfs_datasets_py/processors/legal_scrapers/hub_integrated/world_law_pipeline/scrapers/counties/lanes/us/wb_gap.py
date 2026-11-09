"""Wayback Machine gap fill for TX/MO/KY counties (missing from HF american_municipal_law) with docs=0 from the direct site crawl.
ONLY web.archive.org CDX + raw (id_) snapshot reads via scrapers/wb.py (<=1 req/s total, TLS verified, backoff on 429/503).
Never contacts county origin sites except a single live robots.txt read per host (explicit disallow for our UA/'*'/ia_archiver -> skip;
unreachable -> robots_live='unverified'). Consolidated city-counties (e.g. KY 21111 Louisville/Jefferson) excluded (municipal bot scope).
Resumable: raw/wayback/done.txt, CDX cache raw/wayback/cdx/. Tolerant of truncated jsonl lines. Usage: wb_gap.py MAX_SECONDS MAX_BYTES"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,re,json,time,hashlib,subprocess,urllib.parse,urllib.robotparser,requests
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import wb
from bs4 import BeautifulSoup
B=(str(_CORPORA) + '/county/US'); RAW=B+'/raw/wayback'; os.makedirs(RAW+'/pdf',exist_ok=True); os.makedirs(RAW+'/cdx',exist_ok=True)
MAXS=float(sys.argv[1]); MAXB=float(sys.argv[2]); T0=time.time()
UA="Mozilla/5.0 (compatible; EndomorphosisCountyLawsBot/1.0; +https://huggingface.co/endomorphosis)"
EXCLUDE={'21111','21067','29510'}  # city-county consolidations / independent city -> municipal bot
KW=re.compile(r'ordinance|code-of|code_of|codeof|county-code|codified|regulation|resolution|court-?order|order|subdivision|floodplain|flood-?plain|burn-?ban|charter|bylaw|rules|zoning|policy|policies|septic|on-?site|sewage|fireworks|animal-?control',re.I)
BAD=re.compile(r'agenda|minutes|bid|rfp|employ|job|calendar|newsletter|press|application|budget|audit|facebook|twitter|login|signin|payment|\.(jpg|jpeg|png|gif|css|js|ico|svg|woff2?|xml|zip|docx?|xlsx?)(\?|$)|/wp-(json|includes|content/themes)|/feed/?$|robots\.txt',re.I)
ORX='original:(?i).*(ordinance|code|regulation|resolution|order|subdivision|flood|burn|charter|bylaw|rules|zoning|polic|septic|sewage|fireworks|animal).*'
PER_COUNTY_DOCS=15; PER_COUNTY_FETCH=30
def log(*a): print(time.strftime('%H:%M:%S'),*a,flush=True)
def free_gib(): s=os.statvfs('/'); return s.f_bavail*s.f_frsize/2**30
def dirbytes():
    n=0
    for r,_,fs in os.walk(RAW):
        for f in fs: n+=os.path.getsize(os.path.join(r,f))
    return n
def read_jsonl(p):
    out=[]
    for i,l in enumerate(open(p,errors='replace')):
        if not l.strip(): continue
        try: out.append(json.loads(l))
        except ValueError as e: log('WARN corrupt jsonl line skipped',os.path.basename(p),'line',i+1,str(e)[:60])
    return out
def cdx(host,geoid):
    p=f'{RAW}/cdx/{geoid}_{host.replace("/","_")}.json'
    if os.path.exists(p):
        try: return json.load(open(p))
        except ValueError: log('WARN corrupt cdx cache ignored',p)
    rows=wb.cdx(host.rstrip('/')+'/',matchType='prefix',filter=['statuscode:200',ORX],collapse='urlkey',limit='5000',
                fl='timestamp,original,statuscode,mimetype,length')
    if rows is None: raise RuntimeError('wayback cdx unavailable')
    tmp=p+'.part'; json.dump(rows,open(tmp,'w')); os.replace(tmp,p)
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
    return (rp.can_fetch(UA,url) and rp.can_fetch('*',url) and rp.can_fetch('ia_archiver',url)),st,sig
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
miss={r['geoid'] for r in json.load(open((str(_CORPORA) + '/county/_ref/us_counties_missing_from_aml_20261027.json')))}
T=sorted([t for t in json.load(open(B+'/raw/targets_tx_mo_ky_wikidata.json')) if t['geoid'] not in have and t['geoid'] in miss and t['geoid'] not in EXCLUDE],key=lambda x:(order[x['state']],x['geoid']))
docs=open(RAW+'/docs.jsonl','a'); skips=open(RAW+'/skips.jsonl','a')
def skip(**k): skips.write(json.dumps(k)+'\n'); skips.flush()
log('targets',len(T),'done',len(done))
for c in T:
    if c['geoid'] in done: continue
    if time.time()-T0>MAXS or dirbytes()>MAXB: log('checkpoint stop'); break
    if free_gib()<10.5: log('DISK FLOOR stop'); break
    if not c['sites']: skip(geoid=c['geoid'],reason='no website'); open(RAW+'/done.txt','a').write(c['geoid']+'\n'); continue
    cand={}
    try:
        for site in c['sites']:
            pu=urllib.parse.urlparse(site); host=pu.netloc.lower(); host=host[4:] if host.startswith('www.') else host
            if pu.path.strip('/'): host=host+'/'+pu.path.strip('/')+'/'
            for x in cdx(host,c['geoid']):
                if len(x)<5: continue
                ts,u,stc,mime,ln=x[:5]; mime=(mime or '').lower(); q=urllib.parse.urlparse(u); path=q.path+'?'+q.query
                if not ('html' in mime or 'pdf' in mime): continue
                if not KW.search(path) or BAD.search(path): continue
                k=u.split('#')[0].replace('http://','https://').replace('://www.','://').replace(':80/','/')
                if k not in cand or ts>cand[k]['ts']: cand[k]=dict(ts=ts,url=u,mime=mime)
    except RuntimeError as e:
        log(c['geoid'],c['name'],'CDX FAIL',e); skip(geoid=c['geoid'],reason=str(e)); continue  # not marked done -> retried
    ranked=sorted(cand.values(),key=lambda x:(0 if 'pdf' in x['mime'] else 1,-len(KW.findall(x['url'])),len(x['url'])))
    n=0; f=0
    for x in ranked:
        if n>=PER_COUNTY_DOCS or f>=PER_COUNTY_FETCH: break
        ok,rst,sig=allowed(x['url'])
        if not ok: skip(geoid=c['geoid'],url=x['url'],reason='robots (live) disallow'); continue
        f+=1; r=wb.snap(x['ts'],x['url'])
        if r is None or r.status_code!=200: skip(geoid=c['geoid'],url=x['url'],reason='wayback fetch failed '+str(getattr(r,'status_code',None))); continue
        body=r.content; ct=r.headers.get('content-type','').lower(); h=hashlib.sha256(x['url'].encode()).hexdigest()[:12]
        if 'pdf' in ct or body[:5]==b'%PDF-':
            if len(body)>25*2**20: skip(geoid=c['geoid'],url=x['url'],reason='pdf>25MB'); continue
            pp=f'{RAW}/pdf/{c["geoid"]}_{h}.pdf'; open(pp,'wb').write(body)
            txt=subprocess.run(['pdftotext','-layout',pp,'-'],capture_output=True,text=True).stdout.strip(); kind='pdf'; title=''
            if len(txt)<200: skip(geoid=c['geoid'],url=x['url'],reason='image-only pdf (ocr pending)',pdf=pp); continue
        elif 'html' in ct:
            txt,title=html_text(body); kind='html'; pp=''
            if len(txt)<500: continue
        else: continue
        docs.write(json.dumps(dict(geoid=c['geoid'],gnis=c['gnis'],state=c['state'],county=c['name'],qid=c['qid'],url=x['url'],title=title or urllib.parse.unquote(x['url'].rstrip('/').rsplit('/',1)[-1]),kind=kind,text=txt,
            fetched=time.strftime('%Y-%m-%dT%H:%M:%S%z'),site=c['sites'][0],content_signal=sig,pdf=pp,fetch_via='wayback',wb_timestamp=x['ts'],
            wb_url=f'https://web.archive.org/web/{x["ts"]}/{x["url"]}',robots_live=rst))+'\n'); docs.flush(); n+=1
    open(RAW+'/done.txt','a').write(c['geoid']+'\n'); log(c['geoid'],c['state'],c['name'],'cand',len(cand),'fetched',f,'docs',n)
log('end')
