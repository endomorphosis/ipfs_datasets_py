#!/usr/bin/env python3
"""Phase3 gap collector: reuses state_county.py; sitemap-assisted discovery for JS-rendered/thin states. Stage only. GO: COS_GO_COURTS_PHASE3GAP_20261103"""
import sys,os,re,json,urllib.parse as up
sys.path.insert(0,'/workspace/courts/collector')
import state_county as m
from bs4 import BeautifulSoup
B=m.BASE; m.ST_DIR=f'{B}/staging/state_county_phase3gap'; m.RV=f'{B}/review_state_county_phase3gap'
m.LOG=open(f'{B}/logs/phase3gap.log','a',buffering=1); m.BLF=f'{m.ST_DIR}/blocked_hosts.json'
m.NEVER|=set('CO MS ND NV MN DC MA NC NH NJ NY LA PR TN MO OK'.split())
STATES='MI SD VT DE MT FL NM GA IN'.split()
def phase0(st):
    out=f'{m.ST_DIR}/phase0/{st}.json'
    if os.path.exists(out): return
    url=m.landing_urls()[st]; host=up.urlparse(url).netloc
    res={'state':st,'subdivision_iso':f'US-{st}','landing':url,'candidates':{},'chosen':{},'status':'ok','notes':['sitemap-assisted discovery']}
    try:
        L=[]
        f=m.fetch(url)
        if f and f[0].status_code==200 and f[1]:
            L+=m.links(f[0].url,BeautifulSoup(f[1],'lxml')); host=up.urlparse(f[0].url).netloc
        sms=[f'https://{host}/sitemap.xml']
        H=m.gethost(host)
        sms=[l.split(':',1)[1].strip() for l in (H.robots or '').splitlines() if l.lower().startswith('sitemap:')][:2] or sms
        n=0
        while sms and n<4:
            s=sms.pop(0); n+=1; g=m.fetch(s)
            if not g or g[0].status_code!=200: res['notes'].append(f'sitemap {s} unavailable'); continue
            g2=m.fetch(s) if False else g
            body=(g2[1] or b'').decode('utf-8','ignore')
            if not body:
                continue
            locs=re.findall(r'<loc>\s*([^<\s]+)\s*</loc>',body)
            if '<sitemapindex' in body: sms+=[x for x in locs if re.search(r'page|post|content|court',x,re.I)][:3]; continue
            L+=[(x,up.unquote(up.urlparse(x).path).replace('-',' ').replace('/',' ')) for x in locs]
        res['notes'].append(f'{len(L)} candidate links')
        for cat in m.KW:
            c=sorted({(m.score(cat,u,t),u,t) for u,t in L if m.samesite(u,host) and m.score(cat,u,t)>0 and not up.urlparse(u).path.lower().endswith(m.FILEEXT)},reverse=True)[:5]
            res['candidates'][cat]=[{'score':s,'url':u,'text':t} for s,u,t in c]
            for cand in res['candidates'][cat][:2]:
                if not cand['url'].startswith('https://'): continue
                g=m.fetch(cand['url'])
                if g and g[0].status_code==200: res['chosen'][cat]=g[0].url; break
    except m.HostBlocked as e: res['status']=f'blocked: {e}'
    json.dump(res,open(out,'w'),indent=1); m.log('P3G P0',st,res['status'],res['chosen'])
def main():
    m.load_blocks(); m.log('P3G START pid',os.getpid(),STATES)
    for st in STATES:
        if m.STOP.is_set(): return m.STOPRC[0]
        phase0(st)
        if m.STOP.is_set(): return m.STOPRC[0]
        m.collect_state(3,st)
    if m.STOP.is_set(): return m.STOPRC[0]
    m.review(3,STATES); return 0
if __name__=='__main__':
    try: rc=main()
    except Exception:
        import traceback; m.log('CRASH',traceback.format_exc()); rc=1
    m.log('P3G EXIT rc',rc); sys.exit(rc)
