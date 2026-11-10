# CA: a2aj/canadian-case-law (public HF, keyless). Stage-only. Resumable.
import sys,os,time,datetime;sys.path.insert(0,os.environ.get("CASELAW_ROOT", os.path.expanduser("~/.ipfs_datasets/caselaw")) + '/scrapers/common')
from guard import *
import guard; guard.DISK_STOP=20e9  # CoS: CA pauses (resumable) below 20G free
import pyarrow.parquet as pq
from huggingface_hub import HfApi,hf_hub_download
B=os.environ.get("CASELAW_ROOT", os.path.expanduser("~/.ipfs_datasets/caselaw")) + ''; REPO='a2aj/canadian-case-law'; OUT=B+'/staging/ipfs_canada_caselaw'; LOG=B+'/logs/ca_a2aj.log'
st=State(OUT+'/state.json',{'done_courts':[],'offset':{}}); os.makedirs(OUT,exist_ok=True)
api=HfApi(token=False); rev=st.d.setdefault('revision',api.dataset_info(REPO).sha); st.save()
courts=sorted({f.split('/')[0] for f in api.list_repo_files(REPO,repo_type='dataset',revision=rev) if f.endswith('train.parquet')})
log(LOG,'start rev',rev,'courts',len(courts),'done',len(st.d['done_courts']))
def lic_flag(l):
    l=(l or '').lower(); f=[]
    if 'non-commercial' in l or 'noncommercial' in l or 'non commercial' in l: f.append('non_commercial')
    if 'artificial intelligence' in l or ' ai ' in l or 'machine learning' in l: f.append('ai_terms_check')
    return ';'.join(f) or 'see_upstream_license'
for c in courts:
    if c in st.d['done_courts']: continue
    ok,m,d=guard_ok()
    if not ok: log(LOG,'GUARD STOP before',c,m,d); sys.exit(3)
    p=hf_hub_download(REPO,f'{c}/train.parquet',repo_type='dataset',revision=rev,token=False,cache_dir=B+'/work/ca_hfcache')
    cfg='ca_'+c.lower(); w=PartWriter(f'{OUT}/{cfg}',cfg,st,cfg); off=st.d['offset'].get(c,0); i=0
    pf=pq.ParquetFile(p,buffer_size=1<<20,pre_buffer=False)
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    for b in pf.iter_batches(batch_size=200):
        for r in b.to_pylist():
            i+=1
            if i<=off: continue
            lic=r.get('upstream_license')
            row=dict(jurisdiction='CA',court=c,config=cfg,ecli=None,court_id=None,chamber=None,
                date=str(r.get('document_date_en') or r.get('document_date_fr') or '')[:10] or None,
                number=r.get('citation_en') or r.get('citation_fr'),title=r.get('name_en') or r.get('name_fr'),
                text=r.get('unofficial_text_en') or r.get('unofficial_text_fr'),
                source_url=r.get('url_en') or r.get('url_fr'),licence=('A2AJ compilation MIT; upstream: '+(lic or '')),licence_flag=lic_flag(lic),
                is_archive=False,archive_name=None,retrieved_at=now,source_dataset=f'{REPO}@{rev}')
            for k,v in r.items():
                if k.startswith(('citation','name_','url_','unofficial_text','document_date','scraped')): row['a2aj_'+k]=v
            row['a2aj_cases_cited_en']=r.get('cases_cited_en'); row['a2aj_citing_cases_count']=r.get('citing_cases_count')
            if w.add(row):
                w.flush(lambda: st.d['offset'].__setitem__(c,i)); log(LOG,c,'rows',i,'total',sum(st.d['rows'].values()))
                ok,m,d=guard_ok()
                if not ok: log(LOG,'GUARD STOP',c,i,m,d); sys.exit(3)
    w.flush(lambda: st.d['offset'].__setitem__(c,i)); st.d['done_courts'].append(c); st.save()
    os.remove(os.path.realpath(p)); log(LOG,'done',c,i)
st.d['done']=True; st.save(); log(LOG,'ALL DONE',st.d['rows'])
