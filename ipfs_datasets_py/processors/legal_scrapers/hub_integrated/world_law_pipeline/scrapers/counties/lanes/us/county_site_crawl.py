"""Shallow, polite crawl of county-government sites for codes/ordinances (HTML+text PDFs).
robots.txt fail-closed (polite.py), >=3 s/host, TLS verified, stops on challenge/login walls (no bypass).
Usage: county_site_crawl.py MAX_SECONDS MAX_BYTES"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,re,json,time,hashlib,subprocess,urllib.parse
sys.path.insert(0, _ipfs_os.path.dirname(_ipfs_os.path.abspath(__file__))); import polite
from bs4 import BeautifulSoup
B=(str(_CORPORA) + '/county/US'); RAW=B+'/raw/county_sites'; os.makedirs(RAW+'/pdf',exist_ok=True)
MAXS=float(sys.argv[1]); MAXB=float(sys.argv[2]); T0=time.time()
KW=re.compile(r'ordinance|code of|county code|codified|regulation|resolution|orders?\b|subdivision|floodplain|burn ban|charter|bylaw|rules|zoning|policy|policies',re.I)
BAD=re.compile(r'agenda|minutes|bid|rfp|employment|job|calendar|newsletter|press|form\b|application|budget|audit|facebook|twitter|mailto:|tel:|javascript:|login|signin|payment|permit-fee',re.I)
done=set(open(B+'/raw/county_sites/done.txt').read().split()) if os.path.exists(B+'/raw/county_sites/done.txt') else set()
order={'TX':0,'MO':1,'KY':2}
T=sorted(json.load(open(B+'/raw/targets_tx_mo_ky_wikidata.json')),key=lambda x:(order[x['state']],x['geoid']))
def dirbytes():
    n=0
    for r,_,fs in os.walk(RAW):
        for f in fs: n+=os.path.getsize(os.path.join(r,f))
    return n
def log(*a): print(time.strftime('%H:%M:%S'),*a,flush=True)
def challenged(r):
    h=r.headers
    return 'cf-mitigated' in h or r.status_code in (401,) or (r.status_code in (403,503) and re.search(r'just a moment|captcha|cf-chl|attention required|access denied',r.text[:3000],re.I)) or 'login' in r.url.lower().split('?')[0].rsplit('/',1)[-1]
def terms_for(host):
    p=f'{_CORPORA}/county/_state/robots_{host}.txt'; sig=''
    if os.path.exists(p):
        t=open(p,errors='ignore').read(); m=re.findall(r'(?im)^\s*content-signal\s*:\s*(.+)$',t); sig='; '.join(m)
    return sig
def fetch(url):
    try: r=polite.get(url,min_delay=3.0)
    except PermissionError as e: return None,'robots'
    except SystemExit: raise
    except Exception as e: return None,str(e)[:80]
    if challenged(r): return None,'challenge/login'
    if r.status_code!=200: return None,f'http{r.status_code}'
    return r,''
def html_text(h):
    s=BeautifulSoup(h,'lxml')
    for t in s(['script','style','nav','footer','header','form','noscript']): t.decompose()
    return re.sub(r'\n\s*\n+','\n\n',s.get_text('\n')).strip(), (s.title.string.strip() if s.title and s.title.string else '')
def links(h,base):
    s=BeautifulSoup(h,'lxml'); out={}
    for a in s.find_all('a',href=True):
        u=urllib.parse.urljoin(base,a['href']).split('#')[0]; t=' '.join(a.get_text().split())
        if not u.startswith('http'): continue
        if KW.search(t+' '+u) and not BAD.search(t+' '+u): out.setdefault(u,t)
    return out
docs=open(RAW+'/docs.jsonl','a'); skips=open(RAW+'/skips.jsonl','a')
for c in T:
    if c['geoid'] in done: continue
    if time.time()-T0>MAXS or dirbytes()>MAXB: log('checkpoint stop'); break
    if not c['sites']: skips.write(json.dumps(dict(geoid=c['geoid'],reason='no website in wikidata'))+'\n'); open(RAW+'/done.txt','a').write(c['geoid']+'\n'); continue
    site=c['sites'][0]; host=urllib.parse.urlparse(site).netloc; n=0; seen=set()
    r,err=fetch(site)
    if r is None:
        skips.write(json.dumps(dict(geoid=c['geoid'],site=site,reason=err))+'\n'); skips.flush(); open(RAW+'/done.txt','a').write(c['geoid']+'\n'); log(c['geoid'],c['name'],'SKIP',err); continue
    cap=3 if polite._delay.get(f"{urllib.parse.urlparse(site).scheme}://{host}",0)>60 else 15
    sig=terms_for(host); home=links(r.text,r.url); queue=[(u,t,1) for u,t in list(home.items())[:12]]
    while queue and n<cap and time.time()-T0<MAXS:
        u,t,depth=queue.pop(0)
        if u in seen: continue
        seen.add(u); rr,err=fetch(u)
        if rr is None: skips.write(json.dumps(dict(geoid=c['geoid'],url=u,reason=err))+'\n'); continue
        ct=rr.headers.get('content-type','').lower(); h=hashlib.sha256(u.encode()).hexdigest()[:12]
        if 'pdf' in ct or u.lower().split('?')[0].endswith('.pdf'):
            if len(rr.content)>25e6: skips.write(json.dumps(dict(geoid=c['geoid'],url=u,reason='pdf>25MB'))+'\n'); continue
            pp=f'{RAW}/pdf/{c["geoid"]}_{h}.pdf'; open(pp,'wb').write(rr.content)
            txt=subprocess.run(['pdftotext','-layout',pp,'-'],capture_output=True,text=True).stdout.strip()
            title=t; kind='pdf'
            if len(txt)<200: skips.write(json.dumps(dict(geoid=c['geoid'],url=u,reason='image-only pdf (ocr pending)',pdf=pp))+'\n'); continue
        elif 'html' in ct:
            txt,title=html_text(rr.text); title=t or title; kind='html'
            if depth==1 and len(txt)<1500 or depth==1:
                for u2,t2 in list(links(rr.text,rr.url).items())[:10]:
                    if u2 not in seen and urllib.parse.urlparse(u2).netloc==host: queue.append((u2,t2,2))
            if len(txt)<500: continue
        else: continue
        docs.write(json.dumps(dict(geoid=c['geoid'],gnis=c['gnis'],state=c['state'],county=c['name'],qid=c['qid'],url=u,title=title,kind=kind,text=txt,fetched=time.strftime('%Y-%m-%dT%H:%M:%S%z'),site=site,content_signal=sig,pdf=(pp if kind=='pdf' else '')))+'\n'); docs.flush(); n+=1
    open(RAW+'/done.txt','a').write(c['geoid']+'\n'); log(c['geoid'],c['name'],'docs',n)
log('end')
