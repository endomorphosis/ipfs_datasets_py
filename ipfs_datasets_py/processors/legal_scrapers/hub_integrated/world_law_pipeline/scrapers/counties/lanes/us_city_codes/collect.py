#!/usr/bin/env python3
"""Open-source municipal code collector (official city/county sites only). Resumable, resource-gated, robots-honouring."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
_COLLECTORS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors")))
_CITY = _ipfs_Path(_ipfs_os.environ.get("US_CITY_CODES_ROOT", str(_LEGAL_WS / "us_city_codes")))
_CASE = _ipfs_Path(_ipfs_os.environ.get("CASE_LAW_ROOT", str(_LEGAL_WS / "case_law")))
import json,re,os,sys,time,hashlib,threading,subprocess,collections,urllib.parse,urllib.robotparser,datetime,random,glob
import concurrent.futures as cf
import requests
from bs4 import BeautifulSoup
import pyarrow as pa, pyarrow.parquet as pq

BASE=str(_CITY)
UA='world-laws-municipal-collector/0.1 (research on open US municipal codes; contact via benjamin barber)'
MIN_MEM_KB=int(4.5*1024*1024); MIN_DISK_GB=22
def _cli_args(argv):
    # Ignore non-numeric args (e.g. pytest's -q) so importing under test is safe.
    nums=[a for a in argv[1:] if re.fullmatch(r"\d+(?:\.\d+)?", a)]
    wall=float(nums[0])*60 if nums else 60*60
    workers=int(float(nums[1])) if len(nums)>1 else 6
    return wall, workers
WALL, WORKERS = _cli_args(sys.argv)
HOST_DELAY=2.0; MAX_REQ_SITE=45; MAX_DOCS=30; MAX_PDF=20*1024*1024; MAX_HTML=3*1024*1024; MAX_TEXT=2_000_000
GATED=('municode.com','amlegal.com','ecode360.com','codepublishing.com','municipal.codes','qcode.us','franklinlegal.net','generalcode.com','sterlingcodifiers.com','municipalcodeonline.com','citycode.net')
SKIP_TLD_HOSTS=('facebook.com','twitter.com','youtube.com','instagram.com','linkedin.com','google.com','wikipedia.org')
STRONG=re.compile(r'code of ordinances|municipal code|city code|town code|village code|borough code|county code|codified ordinances|code of the (city|town|village|county)|revised ordinances|ordinance code|zoning (code|ordinance|regulations)|land development (code|regulations)|unified development|subdivision (ordinance|regulations)|development code|(city|town|village|county) charter|\bordinances\b',re.I)
WEAK=re.compile(r'ordinance|\bcode\b|regulation|bylaw|by-law|charter',re.I)
NEG=re.compile(r'agenda|minutes|meeting|news|calendar|bid|rfp|budget|employ|job|career|facebook|twitter|login|sitemap|search|event|permit application|form\b|\bcontact|staff|payment|pay online|utility bill|\.(jpg|png|gif|docx?|xlsx?|zip|mp[34])($|\?)',re.I)
MARK=re.compile(r'§|\bSec(?:tion|\.)\s*\d|\bChapter\s+\d|\bArticle\s+[IVX\d]+',re.I)

def mem_kb():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])
def disk_gb():
    s=os.statvfs('/'); return s.f_bavail*s.f_frsize/2**30
def resources_ok():
    m=mem_kb(); d=disk_gb()
    return (m>=MIN_MEM_KB and d>=MIN_DISK_GB),m/1048576,d

def etld(host):
    p=host.lower().split('.')
    if len(p)>=3 and p[-2] in('co','com','org','gov','net','ci','city','town','us','state','tx','va') and len(p[-1])==2 and p[-1]!='us': return '.'.join(p[-3:])
    if len(p)>=3 and p[-1]=='us': return '.'.join(p[-3:])
    return '.'.join(p[-2:])

class Hosts:
    def __init__(s): s.lock=threading.Lock(); s.last={}; s.robots={}; s.delay={}
    def wait(s,host):
        with s.lock:
            now=time.time(); t=max(now,s.last.get(host,0)+s.delay.get(host,HOST_DELAY)); s.last[host]=t
        if t>now: time.sleep(t-now)
H=Hosts()
S=requests.Session(); S.headers.update({'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5','Accept-Language':'en-US,en;q=0.8'})
adapter=requests.adapters.HTTPAdapter(pool_connections=20,pool_maxsize=20); S.mount('http://',adapter); S.mount('https://',adapter)

class Fail(Exception):
    def __init__(s,reason): s.reason=reason
def robots_for(scheme,host):
    key=(scheme,host)
    with H.lock:
        if key in H.robots: return H.robots[key]
    rp=urllib.robotparser.RobotFileParser(); state='ok'
    try:
        H.wait(host)
        r=S.get(f'{scheme}://{host}/robots.txt',timeout=(8,15),allow_redirects=True)
        if r.status_code==200 and 'html' not in r.headers.get('content-type','').lower()[:20]+'' or (r.status_code==200 and r.text.lstrip().lower().startswith(('user-agent','#','sitemap','disallow','allow'))):
            rp.parse(r.text.splitlines())
            cd=rp.crawl_delay(UA) or rp.crawl_delay('*')
            if cd: H.delay[host]=min(float(cd),10)
        elif r.status_code in(401,403) : state='disallow'
        elif r.status_code>=500: state='unavailable'
        else: rp.parse([])
    except requests.exceptions.SSLError: state='ssl'
    except Exception: state='unavailable'
    with H.lock: H.robots[key]=(rp,state)
    return rp,state
def get(url,counter,maxbytes=MAX_HTML,allow_pdf=True):
    if counter['n']>=MAX_REQ_SITE: raise Fail('request_cap')
    p=urllib.parse.urlparse(url)
    if p.scheme=='http': url=urllib.parse.urlunparse(p._replace(scheme='https')); p=urllib.parse.urlparse(url)  # egress proxy only supports https
    if p.scheme not in('http','https'): raise Fail('bad_scheme')
    if any(p.netloc.lower().endswith(g) for g in GATED): raise Fail('gated_platform:'+p.netloc.lower())
    rp,state=robots_for(p.scheme,p.netloc.lower())
    if state=='disallow': raise Fail('robots_disallow')
    if state=='ssl': raise Fail('ssl_error')
    if state=='unavailable': raise Fail('robots_unavailable')
    if not rp.can_fetch(UA,url): raise Fail('robots_disallow')
    for att in range(2):
        H.wait(p.netloc.lower()); counter['n']+=1
        try:
            r=S.get(url,timeout=(10,25),stream=True,allow_redirects=True)
        except requests.exceptions.SSLError: raise Fail('ssl_error')
        except requests.exceptions.ConnectionError as e:
            if 'Name or service not known' in str(e) or 'NameResolution' in str(e) or 'Failed to resolve' in str(e): raise Fail('dns')
            raise Fail('connection_error')
        except requests.exceptions.Timeout: raise Fail('timeout')
        except Exception: raise Fail('other_fetch_error')
        if r.status_code>=500 and att==0: r.close(); time.sleep(3); continue
        break
    if r.status_code>=400: r.close(); raise Fail(f'http_{r.status_code}')
    fu=r.url; fp=urllib.parse.urlparse(fu)
    if any(fp.netloc.lower().endswith(g) for g in GATED): r.close(); raise Fail('gated_platform:'+fp.netloc.lower())
    if fp.netloc.lower()!=p.netloc.lower():
        rp2,st2=robots_for(fp.scheme,fp.netloc.lower())
        if st2!='ok' or not rp2.can_fetch(UA,fu): r.close(); raise Fail('robots_disallow')
    ct=r.headers.get('content-type','').lower()
    ispdf='pdf' in ct or fu.lower().split('?')[0].endswith('.pdf')
    if ispdf and not allow_pdf: r.close(); raise Fail('skip_pdf')
    lim=MAX_PDF if ispdf else maxbytes
    cl=r.headers.get('content-length')
    if cl and cl.isdigit() and int(cl)>lim: r.close(); raise Fail('too_large')
    buf=bytearray()
    for ch in r.iter_content(65536):
        buf+=ch
        if len(buf)>lim: r.close(); raise Fail('too_large')
    return fu,ct,bytes(buf),ispdf

def pdf_text(b):
    try:
        p=subprocess.run(['pdftotext','-q','-enc','UTF-8','-','-'],input=b,capture_output=True,timeout=120)
        return p.stdout.decode('utf-8','ignore')
    except Exception: return ''
def html_text(b):
    soup=BeautifulSoup(b,'lxml')
    for t in soup(['script','style','nav','footer','header','noscript','form','svg','iframe']): t.decompose()
    main=soup.find('main') or soup.find(id=re.compile('content|main',re.I)) or soup.body or soup
    txt=main.get_text('\n',strip=True)
    title=(soup.title.string.strip() if soup.title and soup.title.string else '')
    return title,re.sub(r'\n{3,}','\n\n',txt)
def links(html_bytes,base):
    soup=BeautifulSoup(html_bytes,'lxml'); out=[]
    for a in soup.find_all('a',href=True):
        h=a['href'].strip()
        if h.startswith(('#','mailto:','tel:','javascript:')): continue
        u=urllib.parse.urldefrag(urllib.parse.urljoin(base,h))[0]
        out.append((u,' '.join(a.get_text(' ',strip=True).split())[:160]))
    return out
def score(u,t):
    s=0; txt=t+' '+urllib.parse.unquote(u)
    if STRONG.search(t): s+=5
    if STRONG.search(urllib.parse.unquote(urllib.parse.urlparse(u).path)): s+=3
    if WEAK.search(txt): s+=1
    if NEG.search(txt): s-=6
    if u.lower().split('?')[0].endswith('.pdf'): s+=1
    return s

def process(tg):
    """tg: dict(key,name,state,qid,gnis,type,url). returns (result dict, rows list)"""
    ctr={'n':0}; rows=[]; seen=set(); gated=set(); docs=0; nbytes=0
    res={'key':tg['key'],'name':tg['name'],'state':tg['state'],'url':tg['url'],'status':'','reason':'','docs':0,'bytes':0,'requests':0}
    try:
        try: fu,ct,b,ispdf=get(tg['url'],ctr,allow_pdf=False)
        except Fail as e:
            if e.reason.startswith('http_') and tg['url'].startswith('http://'): raise
            raise
        home=fu; hl=links(b,fu); ehost=etld(urllib.parse.urlparse(fu).netloc)
        def ok_host(u):
            h=urllib.parse.urlparse(u).netloc.lower()
            return etld(h)==ehost or h.endswith('encodeplus.com')
        cands=[]
        for u,t in hl:
            h=urllib.parse.urlparse(u).netloc.lower()
            if any(h.endswith(g) for g in GATED): 
                if STRONG.search(t) or WEAK.search(t) or WEAK.search(u): gated.add(h)
                continue
            if any(h.endswith(g) for g in SKIP_TLD_HOSTS): continue
            if not ok_host(u): continue
            sc=score(u,t)
            if sc>=3: cands.append((sc,u,t))
        cands.sort(key=lambda x:-x[0]); queue=[]; qs=set()
        for sc,u,t in cands:
            if u not in qs and u!=home: qs.add(u); queue.append((u,t,0))
        queue=queue[:8]
        if not queue:
            res['status']='fail'; res['reason']='gated_platform:'+','.join(sorted(gated)) if gated else 'no_code_links'; res['requests']=ctr['n']; return res,rows
        i=0
        while i<len(queue) and docs<MAX_DOCS:
            u,t,d=queue[i]; i+=1
            if u in seen: continue
            seen.add(u)
            try: fu2,ct2,b2,ispdf2=get(u,ctr)
            except Fail as e:
                if e.reason=='request_cap': break
                if e.reason.startswith('gated_platform'): gated.add(e.reason.split(':',1)[1])
                res.setdefault('sub_fail',collections.Counter())[e.reason]+=1; continue
            if ispdf2: title='';txt=pdf_text(b2); st='pdf'
            else:
                title,txt=html_text(b2); st='html'
            if len(txt)>MAX_TEXT: txt=txt[:MAX_TEXT]
            nm=len(MARK.findall(txt))
            if len(txt)>=1500 and nm>=5:
                sha=hashlib.sha256(txt.encode()).hexdigest()
                if sha not in seen:
                    seen.add(sha); docs+=1; nbytes+=len(txt.encode())
                    rows.append(dict(url=fu2,title=title or t,text=txt,st=st,sha=sha,bytes=len(b2),nm=nm))
            elif ispdf2 and len(txt.strip())<200 and len(b2)>20000:
                res.setdefault('sub_fail',collections.Counter())['pdf_no_text_ocr_needed']+=1
            # expand one level from landing pages
            if not ispdf2 and d==0 and len(queue)<25:
                for u3,t3 in links(b2,fu2):
                    if u3 in qs or u3 in seen: continue
                    h3=urllib.parse.urlparse(u3).netloc.lower()
                    if any(h3.endswith(g) for g in GATED): gated.add(h3); continue
                    if not ok_host(u3): continue
                    if score(u3,t3)>=2 or (u3.lower().split('?')[0].endswith('.pdf') and score(u3,t3)>=0 and STRONG.search(t3+u3)):
                        qs.add(u3); queue.append((u3,t3,1))
                        if len(queue)>=25: break
        res['requests']=ctr['n']; res['docs']=docs; res['bytes']=nbytes
        if docs: res['status']='ok'
        else:
            res['status']='fail'
            sf=res.get('sub_fail')
            if gated and not sf: res['reason']='gated_platform:'+','.join(sorted(gated))
            elif sf and 'pdf_no_text_ocr_needed' in sf: res['reason']='pdf_no_text_ocr_needed'
            else: res['reason']='no_legal_text'
        if 'sub_fail' in res: res['sub_fail']=dict(res['sub_fail'])
        if gated: res['gated_hosts']=sorted(gated)
    except Fail as e:
        res['status']='fail'; res['reason']=e.reason; res['requests']=ctr['n']
    except Exception as e:
        res['status']='fail'; res['reason']='exception:'+type(e).__name__; res['requests']=ctr['n']
    return res,rows

SCHEMA=pa.schema([(n,pa.string()) for n in ['id','title','text','source_url','source_type','jurisdiction','country','language','eli','date','date_issued','retrieved_at','license','law_status','identifier','official_identifier']]+[('article_count',pa.int32())]+[(n,pa.string()) for n in ['json_path','metadata_json','municipality_id','municipality_name','wikidata_qid']])
def to_table(items):
    cols={n:[] for n in SCHEMA.names}
    now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    for tg,r in items:
        k=tg['gnis'] or tg['qid']
        meta=dict(admin_level=tg['type'],state=tg['state'],gnis=tg['gnis'],qid=tg['qid'],source_site=tg['url'],content_kind=r['st'],text_sha256=r['sha'],bytes_fetched=r['bytes'],legal_markers=r['nm'],fetch_via='requests',user_agent=UA,robots_checked=True,terms='official government website; terms not reviewed',pipeline='world-laws us_city_codes collect.py 0.1')
        row=dict(id=f"us-{tg['type']}-{k}-{r['sha'][:10]}",title=r['title'][:500],text=r['text'],source_url=r['url'],source_type=r['st'],jurisdiction=tg['name'],country='US',language='en',eli='',date='',date_issued='',retrieved_at=now,license='unreviewed-public-record',law_status='unknown',identifier='',official_identifier='',article_count=0,json_path='',metadata_json=json.dumps(meta),municipality_id=f"us-{tg['type']}-{k}",municipality_name=tg['name'],wikidata_qid=tg['qid'])
        for n in SCHEMA.names: cols[n].append(row[n])
    return pa.table(cols,schema=SCHEMA)

def build_targets():
    c=json.load(open(R+'cand_seed.json'))
    wd={}
    for l in open(OUT+'/wikidata_resolved.jsonl'):
        d=json.loads(l); wd[d['qid']]=d
    covg=set()
    import re as _re
    for s in json.load(open(R+'aml.json'))['siblings']:
        m=_re.match(r'american_law/data(_\d+)?/(\d+)_html\.parquet$',s['rfilename'])
        if m: covg.add(m.group(2))
    t=json.load(open(R+'county/county_covered.json')); fips={k.replace('us-county-','') for k in t}
    tg=[];seen_key=set();seen_host=set();dropped=collections.Counter()
    for o in c:
        if o['already_covered']!='no' or o['type'] not in('municipality','county'): continue
        w=wd.get(o['qid'],{})
        gn=o['gnis'] or ''
        gs=set([gn] if gn else [])|set(w.get('gnis',[]))
        if gs&covg: dropped['covered_after_wikidata_gnis']+=1; continue
        if o['type']=='county' and o['census_geoid'] in fips: dropped['county_pack']+=1; continue
        st=o['state'] or w.get('state','')
        url=o['source_url'] or (w.get('site') or [''])[0]
        if not url: dropped['no_url']+=1; continue
        if st and st in ('PR','GU','VI','AS','MP'): dropped['territory']+=1; continue
        if any(g in url.lower() for g in GATED): dropped['gated_host_url']+=1; continue
        key=o['qid'] or o['gnis'] or o['jurisdiction']
        host=urllib.parse.urlparse(url).netloc.lower().replace('www.','')
        if key in seen_key: dropped['dup_key']+=1; continue
        if host in seen_host: dropped['dup_host']+=1; continue
        seen_key.add(key); seen_host.add(host)
        pri=(0 if st else 1, 0 if gn or w.get('gnis') else 1)
        tg.append(dict(key=key,name=o['jurisdiction'],state=st,qid=o['qid'],gnis=gn or (sorted(w.get('gnis',[''])) or [''])[0],type=o['type'],url=url,pri=pri))
    tg.sort(key=lambda x:(x['pri'],x['state'],x['name']))
    random.Random(11).shuffle(tg)  # spread load across hosts/states
    tg.sort(key=lambda x:x['pri'])
    return tg,dropped

def main():
    t0=time.time(); os.makedirs(OUT,exist_ok=True)
    ck=OUT+'/checkpoint.jsonl'
    done=set()
    if os.path.exists(ck):
        for l in open(ck): done.add(json.loads(l)['key'])
    tg,dropped=build_targets()
    json.dump({'targets':len(tg),'dropped':dropped},open(OUT+'/targets_summary.json','w'))
    todo=[x for x in tg if x['key'] not in done]
    print(f'targets {len(tg)} done {len(done)} todo {len(todo)} dropped {dict(dropped)}',flush=True)
    shard_n=len(glob.glob(OUT+'/laws-*.parquet'))
    buf=[]; lastchk=0; nres=0
    def flush():
        nonlocal shard_n,buf
        if buf:
            shard_n+=1; pq.write_table(to_table(buf),OUT+f'/laws-{shard_n:05d}.parquet',compression='zstd'); buf=[]
    paused=False
    ex=cf.ThreadPoolExecutor(WORKERS); futs=set(); it=iter(todo); lock=threading.Lock()
    pending={}
    def submit_more():
        while len(futs)<WORKERS*2:
            try: tgt=next(it)
            except StopIteration: return False
            f=ex.submit(process,tgt); pending[f]=tgt; futs.add(f)
        return True
    more=True; stop=False
    while True:
        ok,m,d=resources_ok()
        if not ok and not paused:
            paused=True; stop=True
            print(f'PAUSE: resources low mem={m:.1f}Gi disk={d:.1f}G',flush=True)
            open(OUT+'/PAUSED','w').write(f'{datetime.datetime.now().isoformat()} mem={m:.1f}Gi disk={d:.1f}G\n')
        if time.time()-t0>WALL: stop=True
        if not stop and more: more=submit_more()
        if not futs: break
        dn,_=cf.wait(futs,timeout=5,return_when=cf.FIRST_COMPLETED)
        for f in dn:
            futs.discard(f); tgt=pending.pop(f)
            try: res,rows=f.result()
            except Exception as e: res={'key':tgt['key'],'name':tgt['name'],'state':tgt['state'],'url':tgt['url'],'status':'fail','reason':'exception:'+type(e).__name__,'docs':0,'bytes':0,'requests':0}; rows=[]
            for r in rows: buf.append((tgt,r))
            res['ts']=datetime.datetime.now().isoformat(timespec='seconds')
            with open(ck,'a') as fh: fh.write(json.dumps(res)+'\n')
            nres+=1
            if len(buf)>=150 or (nres%25==0 and buf): flush()
        if nres-lastchk>=100:
            lastchk=nres; print(f'{time.strftime("%H:%M:%S")} processed {nres} mem={m:.1f}Gi disk={d:.1f}G elapsed={(time.time()-t0)/60:.1f}m',flush=True)
    flush()
    print('finished' if not paused else 'paused', 'processed',nres,flush=True)
    open(OUT+'/RUN_STATE','w').write(json.dumps({'ended':datetime.datetime.now().isoformat(),'paused_for_resources':paused,'processed_this_run':nres,'wall_limit_hit':time.time()-t0>WALL}))
    sys.exit(3 if paused else 0)
if __name__=='__main__': main()
