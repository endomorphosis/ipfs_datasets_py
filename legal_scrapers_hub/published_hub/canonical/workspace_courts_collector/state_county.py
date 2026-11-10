#!/usr/bin/env python3
"""State+county courthouses/courts/judges/forms collector. Phases 0,1,2 (+FL in 2; SC deferred).
Locked limits: HTTPS only, TLS verify, keyless, max(10s,crawl-delay)/host, stop host on first 403/429/challenge,
memguard <4.2G pause / 3 strikes stop (exit 3), disk free<12G or staging>2G stop (exit 4). PDFs: url+sha256 only."""
import os, sys, re, json, time, csv, hashlib, threading, shutil, datetime, urllib.parse as up
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
BASE='/workspace/courts'; ST_DIR=f'{BASE}/staging/state_county'; RV=f'{BASE}/review_state_county'
LOG=open(f'{BASE}/logs/state_county.log','a',buffering=1)
UA='Mozilla/5.0 (compatible; justicedao-court-research/0.2; +https://huggingface.co/justicedao)'
PH1='AK AZ CA CT GA HI IL IN MD ME MT NE OH OR PA RI TX UT VA WA WI WV DE AR AL KS ND'.split()
PH2='CO KY WY NM ID NV MN MS IA FL'.split()
DEFERRED={'SC':'deferred-by-crawl-delay: robots Crawl-delay 120000s (~33.3h/request); not fetched'}
NEVER=set('CA IL OR WA WI CT VA KS'.split())
LIC='see source terms (US state government judiciary website)'
MAXP={'courthouses':40,'judges':40,'forms':30}; MAXFILES=250; MAXFILEBYTES=40*2**20; MAXHTMLBYTES=5*2**20; TIMEOUT=(15,30)
CHALL=['cf-chl','challenge-platform','just a moment...','g-recaptcha','hcaptcha','cf-turnstile','leastfactor','_incapsula_','access denied','attention required','px-captcha']
STOP=threading.Event(); STOPRC=[0]; strikes=[0]; mlock=threading.Lock()
def now(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
def log(*a): LOG.write(now()+' '+' '.join(map(str,a))+'\n')
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])/2**20
def du(p):
    t=0
    for r,_,fs in os.walk(p):
        for f in fs:
            try: t+=os.path.getsize(os.path.join(r,f))
            except OSError: pass
    return t
def memstrike_top5():
    try:
        rows=[]
        for d in os.listdir('/proc'):
            if not d.isdigit(): continue
            try:
                rss=0
                for l in open(f'/proc/{d}/status'):
                    if l.startswith('VmRSS'): rss=int(l.split()[1]); break
                cmd=open(f'/proc/{d}/cmdline','rb').read().replace(b'\0',b' ').decode('utf-8','replace').strip()
                rows.append((rss,d,cmd))
            except OSError: pass
        rows.sort(reverse=True)
        for rss,pid,cmd in rows[:5]: log(f'MEMSTRIKE strike={strikes[0]} pid={pid} rss={rss/1024:.0f}MB cmd={cmd[:160]}')
    except Exception as e: log('MEMSTRIKE err',repr(e)[:200])
MEMFLOOR=float(os.environ.get('SC_MEMFLOOR','4.2')); MAXSTRIKES=int(os.environ.get('SC_MAXSTRIKES','3')); STRIKEGAP=float(os.environ.get('SC_STRIKEGAP_S','0'))
lastcounted=[0.0]; MYPID=os.getpid()
def ours(pid,cmd):
    if '/workspace/courts' in cmd: return True
    try:
        p=int(pid)
        while p>1:
            if p==MYPID: return True
            p=int(open(f'/proc/{p}/stat').read().rsplit(')',1)[1].split()[1])
    except Exception: pass
    return False
def memstrike_top5():
    try:
        rows=[]
        for d in os.listdir('/proc'):
            if not d.isdigit(): continue
            try:
                rss=0
                for l in open(f'/proc/{d}/status'):
                    if l.startswith('VmRSS'): rss=int(l.split()[1]); break
                cmd=open(f'/proc/{d}/cmdline','rb').read().replace(b'\0',b' ').decode('utf-8','replace').strip()
                rows.append((rss,d,cmd))
            except OSError: pass
        rows.sort(reverse=True)
        for rss,pid,cmd in rows[:5]: log(f'MEMSTRIKE strike={strikes[0]} pid={pid} rss={rss/1024:.0f}MB cmd={cmd[:160]}')
        if rows and ours(rows[0][1],rows[0][2]): return 'courts_top_rss'
    except Exception as e: log('MEMSTRIKE err',repr(e)[:200])
    return None
def guards():
    if STOP.is_set(): return False
    with mlock:
        if shutil.disk_usage('/workspace').free/2**30<12 or du(ST_DIR)>2*2**30:
            log('DISKGUARD stop'); STOPRC[0]=4; STOP.set(); return False
        m=memavail()
        if m<MEMFLOOR:
            t=time.time(); counted=(strikes[0]==0 or t-lastcounted[0]>=STRIKEGAP)
            if counted: strikes[0]+=1; lastcounted[0]=t
            log(f'MEMGUARD strike {strikes[0]} memavail={m:.2f}G counted={counted} floor={MEMFLOOR} max={MAXSTRIKES} gap={STRIKEGAP}s')
            if memstrike_top5()=='courts_top_rss':
                log('MEMGUARD courts_top_rss stop'); STOPRC[0]=5; STOP.set(); return False
            if strikes[0]>=MAXSTRIKES: STOPRC[0]=3; STOP.set(); return False
            for _ in range(60):
                time.sleep(10)
                if memavail()>=MEMFLOOR: break
            else: STOPRC[0]=3; STOP.set(); return False
    return True
class HostBlocked(Exception): pass
class Host:
    def __init__(s,host): s.host=host; s.delay=10; s.last=0; s.blocked=None; s.n=0; s.robots=None; s.lock=threading.Lock()
HOSTS={}; HL=threading.Lock()
SESS=requests.Session(); SESS.headers['User-Agent']=UA
BLF=f'{ST_DIR}/blocked_hosts.json'
def save_block(h,why):
    with HL:
        d=json.load(open(BLF)) if os.path.exists(BLF) else {}
        d[h]={'reason':why,'at':now()}; json.dump(d,open(BLF,'w'),indent=1)
def load_blocks():
    if os.path.exists(BLF):
        for h,v in json.load(open(BLF)).items(): gethost(h).blocked=v['reason']+' (persisted)'
def gethost(h):
    with HL:
        if h not in HOSTS: HOSTS[h]=Host(h)
        return HOSTS[h]
def is_chall(r,body):
    if r.status_code in (403,429): return f'http {r.status_code}'
    b=body[:30000].lower()
    for m in CHALL:
        if m in b: return f'challenge marker {m!r} (http {r.status_code})'
    return None
def fetch(url,stream=False):
    """returns (resp, body_bytes or None, sha256, nbytes). Raises HostBlocked."""
    p=up.urlparse(url)
    if p.scheme!='https': return None
    H=gethost(p.netloc)
    with H.lock:
        if H.blocked: raise HostBlocked(H.blocked)
        if H.robots is None: _robots(H)
        if not guards(): raise HostBlocked('guard stop')
        w=H.last+H.delay-time.time()
        if w>0: time.sleep(w)
        H.last=time.time(); H.n+=1
        try:
            r=SESS.get(url,timeout=TIMEOUT,stream=True,allow_redirects=True)
        except requests.RequestException as e:
            log('ERR',url,repr(e)[:200]); return None
        if up.urlparse(r.url).scheme!='https': r.close(); return None
        ct=r.headers.get('content-type','')
        keep=(not stream) and ('html' in ct.lower() or 'xml' in ct.lower() or r.status_code in (403,429))  # buffer HTML only; forms/PDFs hashed on the fly
        h=hashlib.sha256(); n=0; chunks=[]
        try:
            for c in r.iter_content(65536):
                h.update(c); n+=len(c)
                if keep:
                    if n>MAXHTMLBYTES: log('HTMLCAP',url); keep=False; chunks=[]; break
                    chunks.append(c)
                if n>MAXFILEBYTES: log('TOOBIG',url); break
        except requests.RequestException as e: log('ERR read',url,repr(e)[:200])
        finally: r.close()
        H.last=time.time()
        body=b''.join(chunks) if (not stream and chunks) else (b'' if not stream else None)
        if r.status_code in (403,429) or ('html' in ct and body is not None):
            c=is_chall(r,(body or b'').decode('utf-8','replace'))
            if c:
                H.blocked=f'{c} at {url}'; log('BLOCK',p.netloc,H.blocked); save_block(p.netloc,H.blocked); raise HostBlocked(H.blocked)
        log('GET',r.status_code,n,url)
        return r,body,h.hexdigest(),n
def _robots(H):
    H.robots=''
    try:
        w=H.last+H.delay-time.time()
        if w>0: time.sleep(w)
        r=SESS.get(f'https://{H.host}/robots.txt',timeout=TIMEOUT); H.last=time.time(); H.n+=1
        if r.status_code==200 and 'html' not in r.headers.get('content-type',''):
            H.robots=r.text[:200000]
            ua=None
            for l in H.robots.splitlines():
                l=l.split('#')[0].strip(); k,_,v=l.partition(':'); k=k.strip().lower(); v=v.strip()
                if k=='user-agent': ua=v
                elif k=='crawl-delay' and ua=='*':
                    try: H.delay=max(H.delay,float(v))
                    except ValueError: pass
        log('ROBOTS',H.host,r.status_code,'delay',H.delay)
    except requests.RequestException as e: log('ERR robots',H.host,repr(e)[:200])
KW={'courthouses':['court directory','court locations','find a court','find your court','courts by county','courthouse','court location','directory','locations','county court','district court','circuit court','courts'],
    'judges':['judicial directory','judge directory','judicial officers','judges','justices','meet the','magistrates','judicial officer','bench'],
    'forms':['forms','self-help forms','court forms','form','self help','self-represented','pro se']}
NEG=['opinion','calendar','docket','job','career','employ','news','press','rule','fee','pay','efil','e-fil','login','sign in','search case','case search','jury','media','event','bid','procure','budget','report','vacanc','select','elect','retention','insurance','liability','notice','petition','evaluation','discipline','conduct','closure','emergency','federal','tribal','translated','contact']
def links(base,soup):
    out=[]
    for a in soup.find_all('a',href=True):
        try: u=up.urljoin(base,a['href'].strip()).split('#')[0]
        except ValueError: continue
        if not u.startswith(('http://','https://')): continue
        out.append((u,' '.join(a.get_text(' ').split())[:200]))
    return out
def score(cat,u,t):
    s=(t+' '+up.unquote(u)).lower(); sc=0
    for i,k in enumerate(KW[cat]):
        if k in s: sc+=10-min(i,8)
    if any(n in s for n in NEG): sc-=6
    return sc
def samesite(u,root):
    a=up.urlparse(u).netloc.lower(); b=root.lower()
    reg=lambda h:'.'.join(h.split('.')[-2:])
    return a==b or reg(a)==reg(b)
def landing_urls():
    d={}
    for r in csv.DictReader(open(f'{BASE}/state_county_source_inventory.csv')): d.setdefault(r['state'],r['url'])
    return d
ISO=json.load(open(f'{BASE}/collector/us_iso.json'))
NAMES={v:k[3:] for k,v in ISO.items()}
def prov(url,sha,extra=None):
    d={'source_url':url,'fetched_at':now(),'archive_source':'live','archive_timestamp':None,'license':LIC,
       'terms_note':'official state judiciary site; public record; cite source','robots_note':'robots advisory (official gov host); crawl-delay honored',
       'transport':'https','content_sha256':sha}
    if extra: d.update(extra)
    return d
def sid(*a): return hashlib.sha1('|'.join(map(str,a)).encode()).hexdigest()[:16]
# ---------------- Phase 0 ----------------
def phase0_state(st):
    out=f'{ST_DIR}/phase0/{st}.json'
    if os.path.exists(out): return
    res={'state':st,'subdivision_iso':f'US-{st}','landing':None,'candidates':{},'chosen':{},'status':'ok','notes':[]}
    if st in DEFERRED:
        res['status']='deferred'; res['notes'].append(DEFERRED[st]); json.dump(res,open(out,'w'),indent=1); return
    url=landing_urls()[st]; res['landing']=url
    try:
        f=fetch(url)
        if not f or f[0].status_code!=200: res['status']=f'landing fail {f[0].status_code if f else "neterr/http"}'
        else:
            r,b,sha,n=f; base=r.url; soup=BeautifulSoup(b,'lxml'); L=links(base,soup)
            if len(L)<8: res['notes'].append(f'only {len(L)} links in static HTML (JS-rendered?)')
            for cat in KW:
                c=sorted({(score(cat,u,t),u,t) for u,t in L if samesite(u,up.urlparse(base).netloc) and score(cat,u,t)>0 and not up.urlparse(u).path.lower().endswith(FILEEXT)},reverse=True)[:5]
                res['candidates'][cat]=[{'score':s,'url':u,'text':t} for s,u,t in c]
            for cat in KW:  # verify top https candidate (1 req per category)
                for cand in res['candidates'][cat]:
                    if not cand['url'].startswith('https://'): res['notes'].append(f'{cat}: http-only {cand["url"]} (transport=http, not fetched)'); continue
                    if cand['url'] in res['chosen'].values():
                        res['chosen'][cat]=cand['url']; break
                    g=fetch(cand['url'])
                    if g and g[0].status_code==200: res['chosen'][cat]=g[0].url; break
                    res['notes'].append(f'{cat}: {cand["url"]} -> {g[0].status_code if g else "err"}')
                    if len([x for x in res['notes'] if x.startswith(cat+':')])>=2: break
    except HostBlocked as e: res['status']=f'blocked: {e}'
    json.dump(res,open(out,'w'),indent=1); log('P0',st,res['status'],res['chosen'])
# ---------------- extraction ----------------
TITLES=r'(Chief Justice|Associate Justice|Justice|Chief Judge|Presiding Judge|Senior Judge|Associate Judge|District Judge|Circuit Judge|Superior Court Judge|County Judge|Probate Judge|Family Court Judge|Judge|Magistrate Judge|Chief Magistrate|Magistrate|Commissioner|Associate Circuit Judge)'
NM=r"([A-Z][a-zA-Z\.'\-]+(?:\s+[A-Z][a-zA-Z\.'\-]*\.?){1,4}(?:,?\s+(?:Jr\.|Sr\.|II|III|IV))?)"
J1=re.compile(r'^(?:The\s+)?(?:Hon(?:orable|\.)\s+)?'+TITLES+r'\s+'+NM+r'$')
J2=re.compile(r'^(?:The\s+)?(?:Hon(?:orable|\.)\s+)?'+NM+r',?\s+[-–]?\s*'+TITLES+r'$')
J3=re.compile(r'^(?:The\s+)?Hon(?:orable|\.)\s+'+NM+r'$')
BADW=re.compile(r'\b(Court|County|Rules?|Office|Clerk|Division|District|Department|Circuit|Judicial|Contact|Directory|Search|Forms?|Home|Menu|Program|Services?|Center|Information|Opinions?|Calendar|Online|Click|More|View|Page|Map|Phone|Fax|Email)\b')
def lines_with_ctx(soup):
    for t in soup(['script','style','noscript','nav','footer','header']): t.decompose()
    out=[]; head=None
    title=(soup.title.get_text(' ').strip() if soup.title else '')
    for el in soup.find_all(['h1','h2','h3','h4','h5','p','li','td','th','div','span','strong','b','address','dt','dd','a']):
        if el.name in('h1','h2','h3','h4','h5'):
            head=' '.join(el.get_text(' ').split())[:200]
    text=soup.get_text('\n')
    cur=title; res=[]
    hs={' '.join(h.get_text(' ').split()) for h in soup.find_all(['h1','h2','h3','h4','h5'])}
    for l in text.split('\n'):
        l=' '.join(l.split())
        if not l: continue
        if l in hs: cur=l
        res.append((l,cur))
    return res,title
def ext_judges(st,url,sha,soup):
    rows=[]; L,title=lines_with_ctx(soup); seen=set()
    for l,ctx in L:
        if len(l)>90: continue
        m=J1.match(l); name=title_=None
        if m: title_,name=m.group(1),m.group(2)
        else:
            m=J2.match(l)
            if m: name,title_=m.group(1),m.group(2)
            else:
                m=J3.match(l)
                if m: name,title_=m.group(1),'Judge (Honorable)'
        if not name: continue
        name=name.strip(' ,'); 
        if BADW.search(name) or len(name.split())<2 or len(name)>60: continue
        court=ctx if ctx and 'court' in ctx.lower() else (title if 'court' in title.lower() else ctx or title)
        k=(name,title_,court)
        if k in seen: continue
        seen.add(k)
        rows.append(dict(judge_id=sid(st,name,court),full_name=name,court_id=sid(st,'court',court) if court else None,court_name=court,
            title=title_,subdivision_iso=f'US-{st}',as_of=datetime.date.today().isoformat(),roster_url=url,
            _privacy='official public roster only: name, court, title',**prov(url,sha)))
    return rows
CITY=lambda st: re.compile(r"^([A-Z][A-Za-z\.'\- ]{1,40}),?\s+(?:"+st+'|'+re.escape(ISO[f'US-{st}'])+r")\.?,?\s+(\d{5})(?:-\d{4})?$")
STREET=re.compile(r'^(\d{1,6}\s+\S.{2,80}|P\.?\s?O\.?\s+Box\s+\d+.*)$',re.I)
NAMEOK=re.compile(r'(Court|Courthouse|Justice Center|Judicial|Clerk|Hall of Justice|Building|Magistrate|Center|Complex)',re.I)
def ext_courthouses(st,url,sha,soup):
    rows=[]; L,title=lines_with_ctx(soup); cre=CITY(st); seen=set()
    for i,(l,ctx) in enumerate(L):
        m=cre.match(l)
        if not m or i==0: continue
        street=L[i-1][0]
        if not STREET.match(street):
            # street and city on one line?
            continue
        name=None
        for j in range(i-2,max(-1,i-5),-1):
            c=L[j][0]
            if NAMEOK.search(c) and len(c)<120 and not STREET.match(c): name=c; break
        name=name or (ctx if ctx and NAMEOK.search(ctx) else None)
        if not name: continue
        k=(name,street)
        if k in seen: continue
        seen.add(k)
        rows.append(dict(courthouse_id=sid(st,name,street),court_id=sid(st,'court',name) if 'court' in name.lower() else None,name=name,
            address_line=street,locality=m.group(1).strip(),postal_code=m.group(2),country='US',subdivision_iso=f'US-{st}',
            lat=None,lon=None,**prov(url,sha)))
    return rows
FILEEXT=('.pdf','.doc','.docx','.rtf','.dot','.dotx','.xls','.xlsx','.odt')
FNUM=re.compile(r'\b([A-Z]{1,6}[- ]?\d{1,5}(?:[-.]\d{1,4})?[A-Z]?)\b')
def ext_formlinks(base,soup):
    out=[]
    for u,t in links(base,soup):
        path=up.urlparse(u).path.lower()
        if path.endswith(FILEEXT): out.append((u,t))
    return out
def classify_level(name):
    n=name.lower()
    for k,v in [('supreme','state'),('appeal','state'),('appellate','state'),('county','county'),('municipal','municipal'),('city','municipal'),('district','district'),('circuit','district'),('superior','county'),('probate','county'),('magistrate','county'),('justice','municipal'),('family','county')]:
        if k in n: return v
    return 'state'
# ---------------- Phase 1/2 per state ----------------
def collect_state(ph,st):
    d=f'{ST_DIR}/phase{ph}/{st}'; os.makedirs(d,exist_ok=True)
    if os.path.exists(f'{d}/DONE'): return
    if st in NEVER: log('SKIP never-retry state',st); return
    disc=json.load(open(f'{ST_DIR}/phase0/{st}.json')) if os.path.exists(f'{ST_DIR}/phase0/{st}.json') else {}
    status={'state':st,'status':'ok','notes':[],'pages':{},'skips':[]}
    if st in DEFERRED: status['status']='deferred'; status['notes'].append(DEFERRED[st])
    elif str(disc.get('status','')).startswith('blocked'): status['status']='host stopped in phase0: '+disc['status']
    elif not disc.get('chosen') and not disc.get('landing'): status['status']='no discovery'
    tables={k:[] for k in ('judges','courthouses','forms')}
    ck=f'{d}/ckpt.json'; ckd=json.load(open(ck)) if os.path.exists(ck) else {}
    if status['status']=='ok':
      try:
        for cat in ('courthouses','judges','forms'):
            if cat in ckd: tables[cat]=[json.loads(l) for l in open(f'{d}/{cat}.jsonl')]; continue
            start=disc.get('chosen',{}).get(cat)
            if not start: status['skips'].append({'table':cat,'reason':'no candidate page found in static landing HTML'}); ckd[cat]=0; continue
            root=up.urlparse(start).netloc; q=[start]; seen={start}; npg=0; files=[]
            while q and npg<MAXP[cat] and not STOP.is_set():
                u=q.pop(0); f=fetch(u)
                if not f: status['skips'].append({'url':u,'reason':'http-only or network error','transport':'http' if u.startswith('http:') else 'https'}); continue
                r,b,sha,n=f; npg+=1
                if r.status_code!=200 or 'html' not in r.headers.get('content-type',''): continue
                soup=BeautifulSoup(b,'lxml'); L=links(r.url,soup)
                if cat=='forms':
                    for fu,ft in ext_formlinks(r.url,soup):
                        if fu not in {x[0] for x in files}: files.append((fu,ft,r.url))
                for lu,lt in L:
                    if lu in seen or not samesite(lu,root) or up.urlparse(lu).path.lower().endswith(FILEEXT): continue
                    if score(cat,lu,lt)>0 or (cat!='forms' and re.search(r'county|district|circuit|court',lt,re.I) and up.urlparse(lu).path.startswith(up.urlparse(start).path.rsplit('/',1)[0])):
                        seen.add(lu)
                        if lu.startswith('https://'): q.append(lu)
                        else: status['skips'].append({'url':lu,'reason':'http-only link not fetched','transport':'http'})
                if cat=='judges': tables['judges']+=ext_judges(st,r.url,sha,soup)
                if cat=='courthouses': tables['courthouses']+=ext_courthouses(st,r.url,sha,soup)
                # courthouse/judge info often co-located
                if cat=='courthouses': tables['judges']+=[]
            status['pages'][cat]=npg
            if cat=='forms':
                for fu,ft,src in files[:MAXFILES]:
                    if STOP.is_set(): break
                    if not fu.startswith('https://'): status['skips'].append({'url':fu,'reason':'http-only form not fetched','transport':'http'}); continue
                    g=fetch(fu,stream=True)
                    if not g or g[0].status_code!=200: status['skips'].append({'url':fu,'reason':f'form fetch {g[0].status_code if g else "err"}'}); continue
                    r,_,sha,n=g; fn=up.unquote(up.urlparse(fu).path.rsplit('/',1)[-1])
                    m=FNUM.search(ft) or FNUM.search(fn.rsplit('.',1)[0].upper())
                    lang='es' if re.search(r'spanish|espa[nñ]ol',ft+fn,re.I) else 'en'
                    tables['forms'].append(dict(form_id=sid(st,fu),form_number=m.group(1) if m else None,title=ft or fn,court_id=None,
                        subdivision_iso=f'US-{st}',language=lang,file_url=r.url,file_format=fn.rsplit('.',1)[-1].lower() if '.' in fn else None,
                        file_sha256=sha,file_cid=None,file_bytes=n,effective_date=None,last_modified=r.headers.get('last-modified'),**prov(src,sha,{'file_stored':False})))
                if len(files)>MAXFILES: status['notes'].append(f'forms capped at {MAXFILES} of {len(files)} file links')
            if STOP.is_set(): break
            # dedupe + checkpoint
            k={'judges':'judge_id','courthouses':'courthouse_id','forms':'form_id'}[cat]
            u={}; [u.setdefault(x[k],x) for x in tables[cat]]; tables[cat]=list(u.values())
            with open(f'{d}/{cat}.jsonl','w') as fo:
                for x in tables[cat]: fo.write(json.dumps(x)+'\n')
            ckd[cat]=len(tables[cat]); json.dump(ckd,open(ck,'w'))
      except HostBlocked as e:
        status['status']=f'host stopped: {e}'; status['skips'].append({'reason':str(e)})
    if STOP.is_set() and status['status']=='ok': return  # leave for resume
    # judges also: dedupe; write partials if blocked
    for cat in ('courthouses','judges','forms'):
        if not os.path.exists(f'{d}/{cat}.jsonl') or cat not in ckd:
            with open(f'{d}/{cat}.jsonl','w') as fo:
                for x in tables[cat]: fo.write(json.dumps(x)+'\n')
    # courts derived from courthouse + judge court names
    courts={}
    for x in tables['courthouses']+tables['judges']:
        nm=x.get('name') if 'courthouse_id' in x else x.get('court_name')
        cid=x.get('court_id')
        if not cid or not nm or 'court' not in nm.lower(): continue
        courts.setdefault(cid,dict(court_id=cid,name=nm,name_local=nm,country='US',subdivision_iso=f'US-{st}',level=classify_level(nm),
            court_type=None,parent_court_id=None,url=x['source_url'],**{k:x[k] for k in ('source_url','fetched_at','archive_source','archive_timestamp','license','terms_note','robots_note','transport','content_sha256')}))
    with open(f'{d}/courts.jsonl','w') as fo:
        for x in courts.values(): fo.write(json.dumps(x)+'\n')
    status['counts']={'courts':len(courts),**{k:len(v) for k,v in tables.items()}}
    json.dump(status,open(f'{d}/status.json','w'),indent=1)
    if 'guard stop' not in str(status['status']) and not STOP.is_set(): open(f'{d}/DONE','w').write(now())
    log('STATE DONE',ph,st,status['status'],status.get('counts'))
def review(ph,states):
    out=f'{RV}/phase{ph}'; os.makedirs(out,exist_ok=True)
    mat=json.load(open('/workspace/coverage/subnational_state_matrix_20261025.json'))['rows']
    fk={r.get('iso_3166_2') for r in mat}|{r.get('iso') for r in mat if r.get('iso')}
    rep={'phase':ph,'generated':now(),'states':{},'validation':{},'skips':{}}
    man=[]
    if ph==0:
        for st in states:
            p=f'{ST_DIR}/phase0/{st}.json'
            if os.path.exists(p): j=json.load(open(p)); rep['states'][st]={'status':j['status'],'chosen':j['chosen'],'notes':j['notes']}; man.append(p)
    else:
        req={'courts':['court_id','name','subdivision_iso','source_url','content_sha256'],'courthouses':['courthouse_id','name','address_line','locality','postal_code','subdivision_iso','source_url','content_sha256'],
             'judges':['judge_id','full_name','title','roster_url','subdivision_iso','source_url','content_sha256'],'forms':['form_id','title','file_url','file_sha256','subdivision_iso','source_url']}
        val={t:{'rows':0,'missing_required':0,'bad_fk':0,'dup_ids':0,'non_https':0} for t in req}
        samples={t:[] for t in req}
        for st in states:
            d=f'{ST_DIR}/phase{ph}/{st}'
            if not os.path.exists(f'{d}/status.json'): rep['states'][st]={'status':'not finished'}; continue
            s=json.load(open(f'{d}/status.json')); rep['states'][st]={'status':s['status'],'counts':s.get('counts'),'pages':s.get('pages'),'notes':s['notes']}
            rep['skips'][st]=s['skips'][:50]
            for t in req:
                p=f'{d}/{t}.jsonl'
                if not os.path.exists(p): continue
                man.append(p); ids=set(); pk=req[t][0]
                for l in open(p):
                    x=json.loads(l); v=val[t]; v['rows']+=1
                    if any(x.get(k) in (None,'') for k in req[t]): v['missing_required']+=1
                    if x.get('subdivision_iso') not in fk: v['bad_fk']+=1
                    if x[pk] in ids: v['dup_ids']+=1
                    ids.add(x[pk])
                    if x.get('transport')!='https': v['non_https']+=1
                    if len(samples[t])<15 and (len(samples[t])<3 or hash(x[pk])%7==0): samples[t].append(x)
        rep['validation']=val
        json.dump(samples,open(f'{out}/samples.json','w'),indent=1)
    rep['hosts']={h:{'requests':H.n,'delay_s':H.delay,'blocked':H.blocked} for h,H in HOSTS.items()}
    json.dump(rep,open(f'{out}/report.json','w'),indent=1)
    with open(f'{out}/MANIFEST.sha256','w') as fo:
        for p in man: fo.write(hashlib.sha256(open(p,'rb').read()).hexdigest()+'  '+os.path.relpath(p,BASE)+'\n')
    open(f'{out}/REVIEW_READY','w').write(now()); log('REVIEW_READY',ph)
def run_pool(fn,states,ph=None):
    with ThreadPoolExecutor(1) as ex:
        list(ex.map(lambda s:(fn(ph,s) if ph is not None else fn(s)),states))
def main():
    os.makedirs(f'{ST_DIR}/phase0',exist_ok=True)
    allst=PH1+PH2+list(DEFERRED)
    log('START pid',os.getpid(),f'memfloor={MEMFLOOR} maxstrikes={MAXSTRIKES} strikegap={STRIKEGAP}s')
    if not os.path.exists(BLF):
        for st in allst:
            p=f'{ST_DIR}/phase0/{st}.json'
            if os.path.exists(p):
                m=re.search(r'blocked: (.*) at (https://[^/]+)/',json.load(open(p))['status'])
                if m: save_block(up.urlparse(m.group(2)).netloc,m.group(0))
    load_blocks()
    if not os.path.exists(f'{BASE}/PHASE0_DONE'):
        run_pool(phase0_state,allst)
        if STOP.is_set(): return STOPRC[0]
        review(0,allst); open(f'{BASE}/PHASE0_DONE','w').write(now())
    for ph,sts in ((1,PH1),(2,PH2)):
        if os.path.exists(f'{BASE}/PHASE{ph}_DONE'): continue
        run_pool(collect_state,sts,ph)
        if STOP.is_set(): return STOPRC[0]
        review(ph,sts); open(f'{BASE}/PHASE{ph}_DONE','w').write(now())
    return 0
if __name__=='__main__':
    try: rc=main()
    except Exception as e:
        import traceback; log('CRASH',traceback.format_exc()); rc=1
    log('EXIT rc',rc); sys.exit(rc)
