import os
os.environ.setdefault("MALLOC_ARENA_MAX","2")  # memsafe default for all caselaw collectors
import json,shutil,time,datetime,pyarrow as pa,pyarrow.parquet as pq
def _gb(v):
    v=float(v); return v*1e9 if v<1e6 else v   # accept GB (3.2) or bytes (3.2e9)
MEM_STOP=_gb(os.environ.get("CASELAW_MEM_STOP","3.2"))    # stop below 3.2G MemAvailable
DISK_STOP=_gb(os.environ.get("CASELAW_DISK_STOP","20.0")) # stop below 20G free disk
def mem_avail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1])*1024
def guard_ok():
    m=mem_avail(); d=shutil.disk_usage('/workspace').free
    return (m>=MEM_STOP and d>=DISK_STOP), m, d
def log(path,*a):
    with open(path,'a') as f: f.write(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S ')+' '.join(map(str,a))+'\n')
class State:
    def __init__(s,path,default):
        s.path=path; s.d=json.load(open(path)) if os.path.exists(path) else default
    def save(s):
        t=s.path+'.tmp'; json.dump(s.d,open(t,'w'),indent=1); os.replace(t,s.path)
class PartWriter:
    """2000-row zstd parquet parts; all columns string except bools."""
    def __init__(s,outdir,prefix,state,key):
        os.makedirs(outdir,exist_ok=True); s.outdir=outdir; s.prefix=prefix; s.st=state; s.key=key; s.buf=[]
        s.st.d.setdefault('parts',{}).setdefault(key,0); s.st.d.setdefault('rows',{}).setdefault(key,0)
    def add(s,row):
        s.buf.append(row)
        return len(s.buf)>=2000
    def flush(s,extra_state=None):
        if not s.buf: 
            if extra_state: extra_state(); s.st.save()
            return
        n=s.st.d['parts'][s.key]; p=f'{s.outdir}/{s.prefix}.part{n:05d}.parquet'
        cols=sorted({k for r in s.buf for k in r})
        t=pa.table({c:pa.array([None if r.get(c) is None else (r[c] if isinstance(r[c],bool) else str(r[c])) for r in s.buf]) for c in cols})
        pq.write_table(t,p+'.tmp',compression='zstd'); os.replace(p+'.tmp',p)
        s.st.d['parts'][s.key]=n+1; s.st.d['rows'][s.key]+=len(s.buf); s.buf=[]
        if extra_state: extra_state()
        s.st.save()
