#!/usr/bin/env python3
"""GR national: official Government Gazette (FEK, Εθνικό Τυπογραφείο) issue A PDFs from the public blob storage used by search.et.gr
(https://ia37rg02wpsa01.blob.core.windows.net/fek/01/<YYYY>/<YYYY>01<NNNNN>.pdf). Keyless, TLS verify, declared UA, 2s delay, streamed PDFs (<=50MB),
404 = not published; 403/503 strikes (3 -> BACKOFF); 429/captcha -> HOLD_PROBE (no retry). StrictGuard RSS300. Stage only. Diavgeia separate.
Usage: gr_fek_collect.py [smoke] [years e.g. 2026-2000]"""
import os,sys,re,json,time,hashlib,subprocess
sys.path.insert(0,'/workspace/scripts')
from strict_mem_guard import StrictGuard,MemShed,Stopped,memavail,rss_mb,DEFAULTS
import requests
B='/workspace/legal-corpora/gr_national_20261103'; OUT=f'{B}/rows'; ST=f'{B}/state.json'; os.makedirs(OUT,exist_ok=True)
UA='justicedao-legal-corpus/1.0 (+https://huggingface.co/justicedao; polite law archiver)'
BLOB='https://ia37rg02wpsa01.blob.core.windows.net/fek'
def log(*a): print(time.strftime('%F %T'),*a,flush=True)
cfg=dict(DEFAULTS); cfg.update(pause_memavail=4200,resume_memavail=4200,resume_hold_s=30,hard_term_memavail=1500,hard_term_sustain_s=10.0,rss_limit_mb=300,delay_s=2.0)
G=StrictGuard(cfg,stop_file=f'{B}/STOP_GR',pause_file=f'{B}/PAUSE_GR',log=log); G.start_watcher()
st=json.load(open(ST)) if os.path.exists(ST) else {}
def save(): t=ST+'.tmp'; json.dump(st,open(t,'w'),indent=1); os.replace(t,ST)
class Hold(Exception): pass
S=requests.Session(); S.headers['User-Agent']=UA; last=[0]; strikes=[0]; neterr_skip=[]
# resume: rows already in jsonl count as done
_prev={}
if os.path.exists(f'{OUT}/GR-FEK-A.jsonl'):
    for _l in open(f'{OUT}/GR-FEK-A.jsonl'):
        try: _r=json.loads(_l); _prev.setdefault(str(_r['fek_year']),set()).add(int(_r['fek_number']))
        except Exception: pass
def fetch(url,tf):
    G.check(); w=last[0]+2.0-time.time()
    if w>0: time.sleep(w)
    r=None
    for k in range(3):
        try: r=S.get(url,timeout=(30,120),verify=True,stream=True); break
        except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as e:
            log('NETERR try',k+1,type(e).__name__,url)
            if k<2: time.sleep(10*(2**k)); G.check()
        finally: last[0]=time.time()
    if r is None: neterr_skip.append(url); log('NETERR SKIP after 3',url); return 'neterr_skip',None,0
    try:
        if r.status_code==429: raise Hold('HOLD_PROBE 429 '+url)
        if r.status_code in (403,503):
            strikes[0]+=1; log('STRIKE',strikes[0],r.status_code,url)
            if strikes[0]>=3: raise Hold('BACKOFF 3 strikes')
            return 'strike',None,0
        if r.status_code==404: return 'missing',None,0
        if r.status_code!=200: return f'http{r.status_code}',None,0
        h=hashlib.sha256(); n=0
        try:
          with open(tf,'wb') as fo:
            for ch in r.iter_content(1<<20):
                n+=len(ch)
                if n>50_000_000: return 'large',None,n
                h.update(ch); fo.write(ch)
        except (requests.exceptions.RequestException,OSError) as e:
            log('NETERR body',type(e).__name__,url); neterr_skip.append(url); return 'neterr_skip',None,n
        if not open(tf,'rb').read(5).startswith(b'%PDF'):
            if re.search(rb'captcha|cf-chl|access denied',open(tf,'rb').read(4000),re.I): raise Hold('HOLD_PROBE WAF '+url)
            return 'not_pdf',None,n
        return 'ok',h.hexdigest(),n
    finally: r.close()
def run(years,smoke=False):
    f=open(f'{OUT}/GR-FEK-A.jsonl','a'); tf=f'{B}/tmp.pdf'; got=0
    for y in years:
        Y=st.setdefault(str(y),{}); done=set(Y.get('done',[]))|_prev.get(str(y),set())
        if Y.get('status')=='DONE': continue
        n=0; miss=0
        while miss<(3 if smoke else 15):
            n+=1
            if smoke and n>3: break
            if n in done: miss=0; continue
            url=f'{BLOB}/01/{y}/{y}01{n:05d}.pdf'; s,ph,size=fetch(url,tf)
            if s in ('missing','not_pdf','http400'): miss+=1; continue
            if s=='neterr_skip': miss=0; continue
            miss=0
            row=dict(id=f'GR:FEK-A-{y}-{n}',jurisdiction='GR',fek_issue='A',fek_year=y,fek_number=n,source_type='gazette_as_published',consolidated=False,pdf_url=url,
                     host='ia37rg02wpsa01.blob.core.windows.net (et.gr official storage)',transport='https',robots_disallowed=False,retrieved_at=time.strftime('%FT%T%z'),pdf_bytes=size,status=s)
            if s=='ok':
                t=subprocess.run(['pdftotext','-layout',tf,'-'],capture_output=True,timeout=300).stdout.decode('utf-8','replace').strip()
                row.update(pdf_sha256=ph,text=t,text_chars=len(t),text_status='pdf' if t else 'empty')
            else: row.update(text=None,text_status=s)
            f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush(); done.add(n); got+=1
            if got%20==0: Y['done']=sorted(done); save(); log('GR',y,'n',n,'rows',got,'mem',memavail(),'rss',rss_mb())
        Y['done']=sorted(done)
        if not smoke: Y['status']='DONE'; Y['last_n']=n-miss
        save(); log('GR year',y,'last_n',n-miss,'rows_total',got)
    return got
def main():
    smoke='smoke' in sys.argv; a=[x for x in sys.argv[1:] if x!='smoke']
    y0,y1=(a[0].split('-') if a else ['2026','2000']); years=range(int(y0),int(y1)-1,-1)
    log('START',list(years)[:3],'...','smoke',smoke,'pid',os.getpid(),'mem',memavail())
    try: n=run(years,smoke); log('DONE rows',n,'strikes',strikes[0],'neterr_skipped',len(neterr_skip),neterr_skip[:50]); return 0
    except Hold as e: st['HOLD']=str(e); save(); log('HOLD',e); return 2
    except (MemShed,Stopped) as e: save(); log('STOP',e); return 3
if __name__=='__main__': sys.exit(main())
