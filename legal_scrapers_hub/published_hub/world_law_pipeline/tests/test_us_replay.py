"""Offline equivalence regression: old builder vs US disk-backed replay, no Hub calls."""
import sys, tempfile, shutil, resource, hashlib
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import run_loop as R
import us_replay
from test_hold_policy import base,w
import pyarrow.parquet as pq

def main():
    root=Path(tempfile.mkdtemp(prefix='us_replay_regression_')); peak=0
    def row(d,**kw): return base(d,place_id='iso:US',country_code='US',language='en',**kw)
    def run(label,rows,full=False,overrides=None,seed=None,plan=None):
        nonlocal peak
        out=root/label/'out'; work=root/label/'work'; work.mkdir(parents=True)
        state=root/label/'state'; state.mkdir()
        if seed: shutil.copytree(seed,out)
        source=root/label/'stage/regs/US/iso_US.20261101T000000Zp0001.jsonl'
        w(source,rows)
        checksum=hashlib.sha256(source.read_bytes()).digest()
        st=source.stat()
        job=dict(cc='US',key='iso_US',out_dir=str(out),scratch=str(work),quarantine=str(root/label/'q'),held=str(root/label/'held'),run_id='fixture',overrides=overrides or {},hub_files=[],hub_download=False,repo='test/offline',state=str(state),primary_index=None,
                 files=[dict(path=str(source),rel='regs/US/'+source.name,bot='regs',sha256=R.sha256_file(source),order=R.batch_order('20261101T000000Zp0001',st.st_mtime,source.name),mtime=st.st_mtime,full=full)])
        if isinstance(full, list):
            job['files']=[]
            for seq,(batch_rows,is_full) in enumerate(full):
                fp=source.with_name(f'iso_US.20261101T{seq:02d}0000Z.jsonl')
                w(fp,batch_rows)
                fs=fp.stat()
                job['files'].append(dict(path=str(fp),rel='regs/US/'+fp.name,bot='regs',sha256=R.sha256_file(fp),
                                         order=R.batch_order(f'20261101T{seq:02d}0000Z',fs.st_mtime,fp.name),mtime=fs.st_mtime,full=is_full))
        if plan: job['xdedup']=dict(cfg={'cross_place':'pointer'},plan=plan)
        result=R.build_place(job)
        assert not result['error'],result.get('traceback')
        data=[]
        for rel,_ in result['written']: data.extend(pq.read_table(out/rel).to_pylist())
        assert hashlib.sha256(source.read_bytes()).digest()==checksum
        if result['written']: R.write_metadata(out,'US','iso_US',result,1700000000000)
        peak=max(peak,result['stats'].get('us_transient_peak_bytes',0))
        return result,data,out
    def pair(name,rows,**kw):
        old=R.US_FEDERAL_KEY
        R.US_FEDERAL_KEY='disabled_offline_reference'
        try: a,expected,_=run(name+'_old',rows,**kw)
        finally: R.US_FEDERAL_KEY=old
        b,actual,out=run(name+'_new',rows,**kw)
        assert expected==actual,name
        assert a.get('doc_stats')==b.get('doc_stats'),name
        assert [(f.get('rows'),f.get('held'),f.get('rejected'),f.get('full_dropped_docs')) for f in a['files']]==[(f.get('rows'),f.get('held'),f.get('rejected'),f.get('full_dropped_docs')) for f in b['files']],name
        return b,actual,out
    try:
        _,_,seed=pair('ordinary',[row('a'),row('b'),row('a',html='<p>new a</p>')])
        pair('append',[row('c'),row('b',html='<p>changed b</p>')],seed=seed)
        pair('full',[row('replacement')],seed=seed,full=True)
        pair('override',[row('a'),row('c')],seed=seed,overrides={('US','iso_US','a'):'fixture override'})
        pair('oldest_newest_full',[],seed=seed,full=[([row('c')],False),([row('replacement'),row('d')],True),([row('d',html='<p>latest d</p>'),row('new')],False)])
        pair('held',[row('a',source_policy='robots_disallowed'),row('c')],seed=seed)
        h=dict(duplicate_of='ZZ/wd_Q1/other',duplicate_key='text')
        pair('neverempty',[row('d')],plan={'d':h})
        pair('pointer',[row('d'),row('unique')],plan={'d':h})
        # Force many small compressed chunks + shard rotation to exercise release while output is written.
        oldchunk=us_replay.Store.CHUNK; oldrows=R.S.SHARD_MAX_ROWS
        us_replay.Store.CHUNK=1024; R.S.SHARD_MAX_ROWS=13
        try: pair('chunks',[row(str(i),html=f'<p>law {i} '+('abc '*100)+'</p>') for i in range(180)])
        finally: us_replay.Store.CHUNK=oldchunk; R.S.SHARD_MAX_ROWS=oldrows
        print('PASS ordinary/append/full/duplicate/override/hold/neverempty/pointer/chunk-release equivalence')
        print('MEASURED peak aggregate transient (DB+chunks+parquet):',peak,'bytes; stat-checked on every guarded write and SQLite mutation')
        print('MEASURED process ru_maxrss:',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'KiB (includes both reference and replay tests)')
    finally: shutil.rmtree(root)
if __name__=='__main__': main()
