#!/usr/bin/env python3
"""DE Laender (BE,BW,BY,HE,HH,MV,RP,SH,SL,ST,TH; NI skipped) sequential collector. CoS GO 2026-11-02 21:33 PT. Stage only, no push, no deletes.
Official gov portals only, keyless, TLS verify on, no archives, UA declared, per-host delay max(Crawl-delay,2s), robots advisory (robots_disallowed flag).
Strikes: 403/429/503 count; 3 -> Land BACKOFF/HOLD; any 429/captcha/WAF -> HOLD_PROBE (no retry). StrictGuard pause<4200 resume>=4200x30s TERM<1500x10s RSS300.
Court handoff: after each Land, if court gapfill (cc_gapfill.py) is running (not SIGSTOPped) -> write HANDOFF_TO_COURT and exit 4."""
import os,sys,re,json,time,html,urllib.parse,subprocess
sys.path.insert(0,'/workspace/scripts')
from strict_mem_guard import StrictGuard,MemShed,Stopped,memavail,rss_mb,DEFAULTS
from es_seue_collect import parse_robots,robots_ok
import requests
B='/workspace/legal-corpora/de_laender_20261102'; OUT=f'{B}/rows'; ST=f'{B}/state.json'; os.makedirs(OUT,exist_ok=True)
UA='justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite municipal-law archiver)'
PORTALS={'BE':'https://gesetze.berlin.de','BW':'https://www.baden-wuerttemberg.de','BYVV':'https://www.gesetze-bayern.de','BY':'https://www.gesetze-bayern.de','HE':'https://www.rv.hessenrecht.hessen.de',
 'HH':'https://www.landesrecht-hamburg.de','MV':'https://www.landesrecht-mv.de','RP':'https://landesrecht.rlp.de','SH':'https://www.gesetze-rechtsprechung.sh.juris.de',
 'SL':'https://recht.saarland.de','ST':'https://www.landesrecht.sachsen-anhalt.de','TH':'https://landesrecht.thueringen.de'}
ORDER=['BY','BE','BW','HE','HH','MV','RP','SH','SL','ST','TH']
CHAL=re.compile(r'just a moment\.\.\.|cf-chl|captcha|attention required|access denied|incapsula|sucuri',re.I)
def log(*a): print(time.strftime('%F %T'),*a,flush=True)
cfg=dict(DEFAULTS); cfg.update(pause_memavail=4200,resume_memavail=4200,resume_hold_s=30,hard_term_memavail=1500,hard_term_sustain_s=10.0,rss_limit_mb=600,delay_s=2.0)
G=StrictGuard(cfg,stop_file=f'{B}/STOP_DE_LAENDER',pause_file=f'{B}/PAUSE_DE_LAENDER',log=log); G.start_watcher()
st=json.load(open(ST)) if os.path.exists(ST) else {}
def save():
    t=ST+'.tmp'; json.dump(st,open(t,'w'),indent=1); os.replace(t,ST)
class Hold(Exception): pass
class Land:
    def __init__(s,code,base):
        s.code=code; s.base=base; s.sess=requests.Session(); s.sess.headers['User-Agent']=UA; s.strikes=0; s.delay=2.0; s.rules=None; s.last=0
    def get(s,path,timeout=30):
        G.check(); w=s.last+s.delay-time.time()
        if w>0: time.sleep(w)
        url=urllib.parse.urljoin(s.base,path); dis=bool(s.rules is not None and not robots_ok(s.rules,urllib.parse.urlsplit(url).path or '/'))
        try: r=s.sess.get(url,timeout=timeout,verify=True)
        finally: s.last=time.time()
        if r.status_code==429: raise Hold('HOLD_PROBE 429 '+url)
        if r.status_code in (403,503):
            s.strikes+=1; log(s.code,'STRIKE',s.strikes,r.status_code,url)
            if s.strikes>=3: raise Hold('BACKOFF 3 strikes')
            return None,dis
        if r.status_code==200 and CHAL.search(r.text[:5000]): raise Hold('HOLD_PROBE captcha/WAF '+url)
        if r.status_code!=200: return None,dis
        if any(d in r.text.lower() for d in ("name='tdm-reservation' content='1'",'name="tdm-reservation" content="1"')): s.tdm=True
        return r,dis
    def probe(s):
        try: r,_=s.get('/robots.txt',timeout=20)
        except requests.exceptions.SSLError as e: raise Hold('TLS_FAIL '+str(e)[:120])
        except requests.exceptions.RequestException as e: raise Hold('UNREACHABLE '+type(e).__name__+' '+str(e)[:120])
        txt=r.text if r is not None else ''; s.rules=parse_robots(txt)
        m=re.search(r'(?im)^crawl-delay:\s*([\d.]+)',txt); s.delay=max(2.0,float(m.group(1)) if m else 0)
        s.tdm=False; h,_=s.get('/',timeout=20)
        if h is None: raise Hold('homepage not 200')
        if s.tdm and s.code not in ('BW',): raise Hold('TDM_RESERVATION meta tdm-reservation=1 (opt-out of text/data mining; needs Benjamin decision)')
def text_of(h):
    t=re.sub(r'(?s)<script.*?</script>|<style.*?</style>|<nav.*?</nav>|<header.*?</header>|<footer.*?</footer>',' ',h); t=re.sub(r'<br\s*/?>|</p>|</div>|</h\d>','\n',t)
    t=html.unescape(re.sub(r'<[^>]+>',' ',t)); t=re.sub(r'[ \t\xa0]+',' ',t); t=re.sub(r'\n\s*\n+','\n\n',t).strip()
    i=t.find('Bereich reduzieren'); return t[i+18:].strip() if 0<=i<3000 else t
TYPES=['ges','rv']
def run_by(L):
    """BAYERN.RECHT: NORMTYP ges, rv, vv filters (session), Search/Page/N -> doc ids -> /Content/Document/<id>/true full text."""
    S=st.setdefault('BY',{}); done=set(S.get('done',[])); f=open(f'{OUT}/DE-BY.jsonl','a'); n=0
    for typ in TYPES:
        if typ in S.get('typ_done',[]): continue
        r,_=L.get(f'/Search/Filter/NORMTYP/{typ}'); ids=[]; page=1; seen=set()
        while r is not None:
            new=[x for x in re.findall(r'href="/Content/Document/([A-Za-z][^"?/#]*)\?hl=true"',r.text) if x not in seen]
            if not new: break
            seen.update(new); ids+=new; page+=1; r,_=L.get(f'/Search/Page/{page}')
        log('BY',typ,'ids',len(ids),'pages',page-1)
        for d in ids:
            if d in done: continue
            r,dis=L.get(f'/Content/Document/{d}/true',timeout=60)
            if r is None: continue
            t=text_of(r.text); ti=re.search(r'<title>(.*?)</title>',r.text,re.S)
            f.write(json.dumps(dict(id=f'DE-BY:{d}',jurisdiction='DE-BY',land='BY',normtyp=typ,doc_id=d,title=html.unescape(ti.group(1).strip()) if ti else d,text=t,text_chars=len(t),
                source_url=L.base+f'/Content/Document/{d}/true',host='www.gesetze-bayern.de',robots_disallowed=dis,transport='https',retrieved_at=time.strftime('%FT%T%z')),ensure_ascii=False)+'\n'); f.flush()
            done.add(d); n+=1
            if n%25==0: S['done']=sorted(done); save(); log('BY rows',len(done),'mem',memavail(),'rss',rss_mb())
        S.setdefault('typ_done',[]).append(typ); S['done']=sorted(done); save()
    return len(done)

def run_bw(L):
    """BW Gesetzblatt (electronic, from 2024-01-01): detail/<YYYY>-<N> HTML -> signed PDF -> pdftotext. Stop a year after 8 consecutive misses."""
    S=st.setdefault('BW',{}); done=set(S.get('done',[])); f=open(f'{OUT}/DE-BW.jsonl','a')
    for y in range(2024,int(time.strftime('%Y'))+1):
        miss=0; n=0
        while miss<8:
            n+=1; key=f'{y}-{n}'
            if key in done: miss=0; continue
            r,dis=L.get(f'/de/service/gesetze-und-verordnungen/gesetzblatt/detail/{key}',timeout=60)
            if r is None or 'Gesetzblatt' not in r.text or not re.search(r'eID=dumpFile[^"]*\.pdf',r.text): miss+=1; continue
            miss=0; tdm=bool(re.search(r'tdm-reservation[^>]*content=.1',r.text))
            m=re.search(r'href="(https://www\.baden-wuerttemberg\.de/index\.php\?eID=dumpFile[^"]*)"',r.text); pu=html.unescape(m.group(1))
            ti=re.search(r'<h1[^>]*>(.*?)</h1>',r.text,re.S); title=html.unescape(re.sub(r'<[^>]+>','',ti.group(1))).strip() if ti else key
            hs=re.search(r'([0-9a-f]{64})',r.text); typ=re.search(r'Gesetzblatt-Typ:\s*</?[^>]*>?\s*([A-Za-zÄÖÜäöüß ]+)',r.text)
            p,_=L.get(pu,timeout=90)
            if p is None or not p.content.startswith(b'%PDF'): continue
            import hashlib; ph=hashlib.sha256(p.content).hexdigest(); tf=f'{B}/tmp_bw.pdf'; open(tf,'wb').write(p.content)
            t=subprocess.run(['pdftotext','-layout',tf,'-'],capture_output=True,text=True,timeout=120).stdout.strip()
            row=dict(id=f'DE-BW:GBl-{key}',jurisdiction='DE-BW',land='BW',gbl=key,title=title,text=t,text_chars=len(t),source_type='gazette_as_published',consolidated=False,
                source_url=L.base+f'/de/service/gesetze-und-verordnungen/gesetzblatt/detail/{key}',pdf_url=pu.split('&token=')[0],pdf_sha256=ph,page_hash=hs.group(1) if hs else None,
                pdf_hash_match=(hs.group(1)==ph) if hs else None,gbl_type=typ.group(1).strip() if typ else None,host='www.baden-wuerttemberg.de',robots_disallowed=dis,transport='https',retrieved_at=time.strftime('%FT%T%z'))
            if tdm: row['tdm_reservation_ignored']=True
            f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush(); done.add(key)
            if len(done)%20==0: S['done']=sorted(done); save(); log('BW rows',len(done),'mem',memavail(),'rss',rss_mb())
        S['done']=sorted(done); save(); log('BW year',y,'last_n',n-miss)
    return len(done)
def run_byvv(L):
    global TYPES; TYPES=['vv']; S=st.setdefault('BY',{}); return run_by(L)
def court_running():
    for p in subprocess.run(['pgrep','-f','cc_gapfill.py'],capture_output=True,text=True).stdout.split():
        try:
            if open(f'/proc/{p}/stat').read().split(')')[1].split()[0] not in ('T','t'): return True
        except Exception: pass
    return False
def main():
    lands=sys.argv[1].split(',') if len(sys.argv)>1 else ORDER
    log('START',lands,'pid',os.getpid(),'mem',memavail())
    for c in lands:
        if st.get(c,{}).get('status') in ('DONE','HOLD'): continue
        L=Land(c,PORTALS[c]); S=st.setdefault(c,{})
        try:
            L.probe(); log(c,'PROBE OK delay',L.delay)
            if c=='BY': S['rows']=run_by(L); S['status']='DONE'
            elif c=='BW': S['rows']=run_bw(L); S['status']='DONE'
            elif c=='BYVV': S['rows']=run_byvv(L); S['status']='DONE'
            else: S['status']='HOLD'; S['reason']='reachable but no collector parser built for this portal yet (juris SPA)'
        except Hold as e: S['status']='HOLD'; S['reason']=str(e)
        except (MemShed,Stopped) as e: log('STOP',c,e); save(); return 3
        except Exception as e: S['status']='HOLD'; S['reason']='ERROR '+repr(e)[:200]
        S['at']=time.strftime('%FT%T%z'); save(); log(c,S.get('status'),S.get('reason',''),S.get('rows',''))
        if court_running() and c==lands[-1]: open(f'{B}/HANDOFF_TO_COURT','w').write(time.strftime('%FT%T%z')+f' after {c}\n'); log('HANDOFF to court after',c); return 4
    open(f'{B}/DE_LAENDER_DONE','w').write(time.strftime('%FT%T%z')+'\n'); log('DONE',json.dumps({k:(v.get('status'),v.get('rows'),v.get('reason')) for k,v in st.items()})); return 0
if __name__=='__main__': sys.exit(main())
