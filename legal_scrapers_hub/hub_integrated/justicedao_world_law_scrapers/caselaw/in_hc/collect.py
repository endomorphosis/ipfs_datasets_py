# IN High Courts: AWS Open Data s3://indian-high-court-judgments (CC-BY-4.0), keyless S3 HTTPS.
# Streams tar parts, extracts PDF text in memory with pdftotext (PDFs never written to disk), joins metadata.parquet.
# Resumable (state.json), 2,000-row zstd parquet parts, guards from common/guard.py (MALLOC_ARENA_MAX=2, mem 3.2G, disk 20G).
import os; os.environ.setdefault('MALLOC_ARENA_MAX','2')
import sys,io,re,json,time,tarfile,subprocess,datetime,requests,concurrent.futures as cf
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','common'))
from guard import *
import pyarrow.parquet as pq
B=os.environ.get('CASELAW_ROOT',os.environ.get("CASELAW_ROOT", os.path.expanduser("~/.ipfs_datasets/caselaw")) + ''); S3='https://indian-high-court-judgments.s3.amazonaws.com'
OUT=B+'/staging/ipfs_india_caselaw'; LOG=B+'/logs/in_hc.log'
LIC='CC-BY-4.0 (AWS Open Data: indian-high-court-judgments, from eCourts High Court services)'
os.makedirs(OUT,exist_ok=True); st=State(OUT+'/state_in_hc.json',{'done':[],'cur':{}})
H={'User-Agent':'justicedao-caselaw-research/1.0'}
def get(u,**k):
    for a in range(6):
        try:
            r=requests.get(u,headers=H,timeout=180,**k)
            if r.status_code==404: return None
            r.raise_for_status(); return r
        except Exception as e: log(LOG,'retry',a,u,e); time.sleep(10*(a+1))
    raise RuntimeError(u)
def ls(prefix):
    out=[];tok=None
    while True:
        p={'list-type':'2','prefix':prefix,'delimiter':'/','max-keys':'1000'}
        if tok: p['continuation-token']=tok
        x=get(S3+'/',params=p).text
        out+=re.findall(r'<Prefix>([^<]+/)</Prefix>',x)[1:] if prefix else re.findall(r'<Prefix>([^<]+/)</Prefix>',x)
        m=re.search(r'<NextContinuationToken>([^<]+)<',x)
        if not m: return [o for o in out if o!=prefix]
        tok=m.group(1)
def pdftext(data):
    try: return subprocess.run(['pdftotext','-enc','UTF-8','-layout','-','-'],input=data,capture_output=True,timeout=120).stdout.decode('utf-8','replace')
    except Exception: return None
def s(v): return None if v is None else str(v)
w=PartWriter(OUT+'/in_hc','in_hc',st,'in_hc'); pool=cf.ThreadPoolExecutor(3)
years=sorted([int(re.search(r'year=(\d+)',p).group(1)) for p in ls('data/tar/')],reverse=True)
log(LOG,'start years',len(years),'rows so far',st.d['rows'].get('in_hc'))
for y in years:
    for cp in ls(f'data/tar/year={y}/'):
        for bp in ls(cp):
            key=bp[len('data/tar/'):]
            if key in st.d['done']: continue
            ok,m,d=guard_ok()
            if not ok: w.flush(); log(LOG,'GUARD STOP',key,m,d); sys.exit(3)
            ir=get(S3+'/'+bp+'data.index.json'); idx=ir.json() if ir is not None else {'parts':[{'name':'data.tar'}]}
            meta={}; mr=get(S3+'/metadata/parquet/'+key+'metadata.parquet')
            if mr is not None:
                try:
                    t=pq.read_table(io.BytesIO(mr.content),columns=None); t=t.drop_columns([c for c in ['raw_html'] if c in t.schema.names])
                    for r in t.to_pylist(): meta[os.path.basename(r.get('pdf_link') or '')]=r
                    del t
                except Exception as e: log(LOG,'meta fail',key,e)
            del mr
            cur=st.d['cur'].get(key,[]); done=set(cur)
            for part in idx.get('parts',[]):
                r=get(f"{S3}/{bp}{part['name']}",stream=True)
                if r is None: continue
                tf=tarfile.open(fileobj=r.raw,mode='r|'); batch=[]
                def drain():
                    for nm,fut in batch:
                        txt=fut.result(); md=meta.get(nm,{})
                        row=dict(jurisdiction='IN',config='in_hc',court=md.get('court'),court_id=None,chamber=None,ecli=None,
                            date=s(md.get('decision_date'))[:10] if md.get('decision_date') is not None else (re.search(r'(\d{4}-\d{2}-\d{2})',nm).group(1) if re.search(r'(\d{4}-\d{2}-\d{2})',nm) else None),
                            number=md.get('cnr') or nm.split('_')[0],title=md.get('title'),text=txt,
                            source_url=f'{S3}/data/pdf/year={y}/{key.split("/",1)[1]}{nm}' ,licence=LIC,licence_flag='attribution_required',
                            is_archive=False,archive_name=f"{bp}{part['name']}",retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            text_extraction='pdftotext',in_court_code=md.get('court_code'),in_bench=key.split('bench=')[1].rstrip('/'),
                            in_cnr=md.get('cnr'),in_judge=md.get('judge'),in_description=md.get('description'),
                            in_disposal_nature=md.get('disposal_nature'),in_date_of_registration=md.get('date_of_registration'),
                            in_pdf_link=md.get('pdf_link'),pdf_member=nm)
                        cur.append(nm)
                        if w.add(row):
                            w.flush(lambda: st.d['cur'].__setitem__(key,cur)); log(LOG,key,'rows',st.d['rows']['in_hc'])
                            ok,m,d=guard_ok()
                            if not ok: log(LOG,'GUARD STOP',key,m,d); sys.exit(3)
                    batch.clear()
                for mem in tf:
                    if not mem.isfile() or not mem.name.lower().endswith('.pdf'): continue
                    nm=os.path.basename(mem.name)
                    if nm in done: continue
                    data=tf.extractfile(mem).read(); batch.append((nm,pool.submit(pdftext,data))); del data
                    if len(batch)>=12: drain()
                drain(); r.close()
            w.flush(lambda: (st.d['done'].append(key), st.d['cur'].pop(key,None))); log(LOG,'bench done',key,'rows',st.d['rows']['in_hc'])
log(LOG,'ALL DONE',st.d['rows']['in_hc'])
