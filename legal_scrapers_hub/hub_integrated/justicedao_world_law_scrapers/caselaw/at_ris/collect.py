# AT: RIS OGD API v2.6 Judikatur (keyless, CC BY 4.0). 0.5 req/s, only weekdays 12:00-21:00 America/Los_Angeles (box tz); sleeps outside window.
import sys,os,time,datetime,requests,lxml.html;sys.path.insert(0,os.environ.get("CASELAW_ROOT", os.path.expanduser("~/.ipfs_datasets/caselaw")) + '/scrapers/common')
from guard import *
B=os.environ.get("CASELAW_ROOT", os.path.expanduser("~/.ipfs_datasets/caselaw")) + ''; API='https://data.bka.gv.at/ris/api/v2.6/Judikatur'; OUT=B+'/staging/ipfs_austria_caselaw'; LOG=B+'/logs/at_ris.log'
LIC='CC BY 4.0 (RIS OGD, Bundeskanzleramt Österreich, data.gv.at)'
APPS=['Vfgh','Vwgh','Justiz','Bvwg','Lvwg','Dsk','Gbk','Pvak','Umse','Bks','Verg','Ubas','Dok']
os.makedirs(OUT,exist_ok=True); st=State(OUT+'/state.json',{'page':{},'done_apps':[]})
H={'User-Agent':'justicedao-caselaw-research/1.0 (polite 0.5 req/s)'}; last=[0.0]
def in_window():
    n=datetime.datetime.now(); return n.weekday()<5 and 12<=n.hour<21
def wait_window():
    while not in_window():
        log(LOG,'outside window, paused'); time.sleep(600)
def get(u,params=None):
    for a in range(6):
        wait_window(); dt=time.time()-last[0]
        if dt<2.0: time.sleep(2.0-dt)
        last[0]=time.time()
        try:
            r=requests.get(u,params=params,headers=H,timeout=60)
            if 'Security Check' in r.text[:3000]: log(LOG,'WAF page, stopping (no bypass)',u); sys.exit(4)
            if r.status_code in(429,503): time.sleep(60*(a+1)); continue
            r.raise_for_status(); return r
        except requests.RequestException as e: log(LOG,'retry',a,u,e); time.sleep(20*(a+1))
    return None
def L(x): return x if isinstance(x,list) else ([] if x is None else [x])
def items(x): return [i for i in L(x.get('item') if isinstance(x,dict) else x)] if x else []
for app in APPS:
    if app in st.d['done_apps']: continue
    cfg='at_'+app.lower(); w=PartWriter(f'{OUT}/{cfg}',cfg,st,cfg); page=st.d['page'].get(app,0)
    while True:
        ok,m,d=guard_ok()
        if not ok: log(LOG,'GUARD STOP',app,page,m,d); sys.exit(3)
        r=get(API,{'Applikation':app,'DokumenteProSeite':'OneHundred','Seitennummer':page+1})
        if r is None: log(LOG,'list failed',app,page); sys.exit(5)
        res=r.json()['OgdSearchResult']
        refs=L(res.get('OgdDocumentResults',{}).get('OgdDocumentReference'))
        if not refs: break
        for ref in refs:
            D=ref['Data']; M=D['Metadaten']; T=M['Technisch']; A=M.get('Allgemein',{}); J=M.get('Judikatur',{})
            urls=L(D.get('Dokumentliste',{}).get('ContentReference')); hu=None
            for cr in urls:
                if cr.get('ContentType')=='MainDocument':
                    for cu in L(cr['Urls']['ContentUrl']):
                        if cu['DataType']=='Html': hu=cu['Url']
            txt=None
            if hu:
                hr=get(hu)
                if hr is not None:
                    try: txt=lxml.html.fromstring(hr.content).text_content()
                    except Exception: txt=None
            gz=J.get('Geschaeftszahl'); gz='; '.join(map(str,items(gz))) if isinstance(gz,dict) else gz
            row=dict(jurisdiction='AT',court=T.get('Organ') or app,config=cfg,ecli=J.get('EuropeanCaseLawIdentifier'),court_id=None,chamber=None,
                date=J.get('Entscheidungsdatum'),number=gz,title=None,text=txt,source_url=hu or A.get('DokumentUrl'),licence=LIC,licence_flag='attribution_required',
                is_archive=False,archive_name=None,retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ris_id=T.get('ID'),ris_app=app,doc_type=J.get('Dokumenttyp'),published=A.get('Veroeffentlicht'),changed=A.get('Geaendert'),
                normen='; '.join(map(str,items(J.get('Normen')))),schlagworte=J.get('Schlagworte'))
            if w.add(row): w.flush(); log(LOG,app,'page',page,'rows',st.d['rows'][cfg])
        page+=1; st.d['page'][app]=page
        if page%5==0: log(LOG,app,'page',page)
        # state page only advances with flushed rows: flush on page boundary when buffer big enough handled above; persist page after flush
        if not w.buf: st.save()
    w.flush(); st.d['done_apps'].append(app); st.save(); log(LOG,'app done',app,st.d['rows'][cfg])
st.d['done']=True; st.save(); log(LOG,'ALL DONE',st.d['rows'])
