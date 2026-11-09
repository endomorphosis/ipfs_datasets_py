# IN: AWS Open Data indian-supreme-court-judgments (CC-BY-4.0), keyless S3 HTTPS. PDFs streamed, text extracted in-memory, never stored.
import sys,os,io,re,json,time,tarfile,subprocess,datetime,requests;sys.path.insert(0,'/workspace/caselaw/scrapers/common')
from guard import *
import pyarrow.parquet as pq
B='/workspace/caselaw'; S3='https://indian-supreme-court-judgments.s3.amazonaws.com'; OUT=B+'/staging/ipfs_india_caselaw'; LOG=B+'/logs/in_aws.log'
LIC='CC-BY-4.0 (AWS Open Data: indian-supreme-court-judgments, from ecourts/SCI)'
os.makedirs(OUT,exist_ok=True); st=State(OUT+'/state.json',{'done':[],'members_done':{}})
H={'User-Agent':'justicedao-caselaw-research/1.0'}
def get(u,**k):
    for a in range(6):
        try:
            r=requests.get(u,headers=H,timeout=120,**k); r.raise_for_status(); return r
        except Exception as e: log(LOG,'retry',a,u,e); time.sleep(10*(a+1))
    raise RuntimeError(u)
years=list(range(1950,datetime.date.today().year+1))
w=PartWriter(OUT+'/in_sc','in_sc',st,'in_sc')
for y in years:
    key=f'{y}/english'
    if key in st.d['done']: continue
    ok,m,d=guard_ok()
    if not ok: log(LOG,'GUARD STOP',y,m,d); sys.exit(3)
    try: idx=get(f'{S3}/data/tar/year={y}/english/english.index.json').json()
    except Exception: log(LOG,'no index',y); st.d['done'].append(key); st.save(); continue
    meta={}
    try:
        t=pq.read_table(io.BytesIO(get(f'{S3}/metadata/parquet/year={y}/metadata.parquet').content))
        for r in t.drop_columns([c for c in ['raw_html'] if c in t.schema.names]).to_pylist(): meta[r.get('path')]=r
    except Exception as e: log(LOG,'no meta',y,e)
    done=set(st.d['members_done'].get(key,[]))
    for part in idx.get('parts',[{'name':'english.tar'}]):
        u=f"{S3}/data/tar/year={y}/english/{part['name']}"
        r=get(u,stream=True); tf=tarfile.open(fileobj=r.raw,mode='r|')
        for mem in tf:
            if not mem.isfile() or not mem.name.lower().endswith('.pdf'): continue
            nm=os.path.basename(mem.name)
            if nm in done: continue
            data=tf.extractfile(mem).read()
            try: txt=subprocess.run(['pdftotext','-enc','UTF-8','-layout','-','-'],input=data,capture_output=True,timeout=120).stdout.decode('utf-8','replace')
            except Exception as e: txt=None; log(LOG,'pdftotext fail',nm,e)
            del data
            pth=re.sub(r'_EN\.pdf$','',nm,flags=re.I); md=meta.get(pth,{})
            row=dict(jurisdiction='IN',court='Supreme Court of India',config='in_sc',ecli=None,court_id=None,chamber=None,
                date=md.get('decision_date'),number=md.get('case_id') or md.get('citation'),title=md.get('title'),text=txt,
                source_url=f'{u}#{nm}',licence=LIC,licence_flag='attribution_required',is_archive=False,archive_name=part['name'],
                retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),pdf_member=nm,text_extraction='pdftotext',
                **{'in_'+k:v for k,v in md.items() if k not in('title','year')})
            done.add(nm)
            if w.add(row):
                w.flush(lambda: st.d['members_done'].__setitem__(key,sorted(done))); log(LOG,y,'rows total',st.d['rows']['in_sc'])
                ok,m,d=guard_ok()
                if not ok: log(LOG,'GUARD STOP',y,m,d); sys.exit(3)
        r.close()
    w.flush(lambda: st.d['members_done'].__setitem__(key,sorted(done))); st.d['done'].append(key); st.d['members_done'].pop(key,None); st.save(); log(LOG,'year done',y,len(done))
st.d['all_done']=True; st.save(); log(LOG,'ALL DONE',st.d['rows'])
