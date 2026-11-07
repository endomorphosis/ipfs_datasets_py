"""Bounded giant-law spills, exact content, quota/floor failures; owned synthetic files only."""
import sys,tempfile,shutil,base64,os,hashlib,gc
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import us_replay as U,run_loop as R
from test_hold_policy import base,w
import pyarrow.parquet as pq

def main():
    root=Path(tempfile.mkdtemp(prefix='us_oversize_test_'))
    try:
        for name,field in [('compressible','X'*(17*1024**2)),('noncompressible',base64.b64encode(os.urandom(13*1024**2)).decode())]:
            owned=root/name;owned.mkdir()
            guard=R.USTransientGuard(lambda:list(owned.glob('*')),free=lambda:50*1024**3)
            store=U.Store(owned,guard)
            row={'doc_id':'giant-'+name,'html':field,'text':field,'doc_order':1}
            expected=hashlib.sha256(field.encode()).hexdigest()
            off,n=store.append(row);assert n<0
            restored=store.read(off,n)
            assert restored==row and hashlib.sha256(restored['html'].encode()).hexdigest()==expected
            assert len(restored['html'])==len(field)
            print(name,'serialized_bytes',-n,'spill_bytes',(owned/f'chunk{off//2**40:06d}.z').stat().st_size,'peak',guard.peak)
            # Quota/floor errors must remove only the attempted incomplete spill.
            before=set(owned.glob('chunk*.z'))
            guard.cap=guard.used()+1000
            try:store.append(row);assert False
            except RuntimeError as e:assert 'TMP_CAP' in str(e)
            assert set(owned.glob('chunk*.z'))==before
            guard.cap=4*1024**3;guard.free=lambda:R.USTransientGuard.FLOOR
            try:store.append(row);assert False
            except RuntimeError as e:assert 'DISK_FLOOR' in str(e)
            assert set(owned.glob('chunk*.z'))==before
            guard.free=lambda:50*1024**3
            old_limit=store.RSS_LIMIT;store.RSS_LIMIT=1
            try:store.append(row);assert False
            except RuntimeError as e:assert 'ROW_MEMORY_CAP' in str(e)
            finally:store.RSS_LIMIT=old_limit
            store.close();del restored,row,field;gc.collect()
        # Actual writer retains one giant law as one public Arrow/parquet row.
        state=root/'state';state.mkdir();out=root/'out';scratch=root/'work';scratch.mkdir()
        path=root/'stage/regs/US/iso_US.giant.jsonl'
        text='Y'*(17*1024**2)
        noise=base64.b64encode(os.urandom(13*1024**2)).decode()
        w(path,[base('giant',place_id='iso:US',country_code='US',language='en',html=None,text=text),base('giant-noise',place_id='iso:US',country_code='US',language='en',html=None,text=noise)])
        st=path.stat()
        job=dict(cc='US',key='iso_US',out_dir=str(out),scratch=str(scratch),quarantine=str(root/'q'),held=str(root/'held'),run_id='test',overrides={},hub_files=[],hub_download=False,repo='test/offline',state=str(state),primary_index=None,
                 files=[dict(path=str(path),rel='regs/US/'+path.name,bot='regs',sha256=R.sha256_file(path),order=R.batch_order('giant',st.st_mtime,path.name),mtime=st.st_mtime,full=False)])
        r=R.build_place(job);assert not r['error'],r.get('traceback')
        rows=[row for rel,_ in r['written'] for row in pq.read_table(out/rel).to_pylist()]
        assert len(rows)==2
        byid={r['doc_id']:r for r in rows}
        assert byid['giant']['text']==text and byid['giant-noise']['text']==noise
        assert hashlib.sha256(byid['giant-noise']['text'].encode()).digest()==hashlib.sha256(noise.encode()).digest()
        assert hashlib.sha256(rows[0]['text'].encode()).digest()==hashlib.sha256(text.encode()).digest()
        assert path.exists()
        print('PASS giant public row/schema/content/hash retained without splitting; spill quota/floor and failure cleanup')
    finally:shutil.rmtree(root)
if __name__=='__main__':main()
