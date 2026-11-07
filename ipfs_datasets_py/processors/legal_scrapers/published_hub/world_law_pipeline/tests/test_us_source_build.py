"""Offline end-to-end fake HF source -> replay -> identical parquet rows, isolated scratch."""
import sys,tempfile,shutil,hashlib,json
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import run_loop as R,us_source as U
from test_hold_policy import base,w
import pyarrow.parquet as pq

def main():
    root=Path(tempfile.mkdtemp(prefix='us_source_build_'))
    original_key=R.US_FEDERAL_KEY;original_api=U.HfApi;original_requests=U.requests
    try:
        state=root/'state';state.mkdir();source=root/'staging/regs/US/iso_US.fixture.jsonl'
        w(source,[base(str(i),place_id='iso:US',country_code='US',language='en') for i in range(40)])
        st=source.stat()
        def job(label,files,paths):
            scratch=root/label/'work';scratch.mkdir(parents=True)
            return dict(cc='US',key='iso_US',out_dir=str(root/label/'out'),scratch=str(scratch),quarantine=str(root/label/'q'),held=str(root/label/'held'),run_id='fixture',overrides={},hub_files=paths,hub_download=True,repo='test/offline',state=str(state),primary_index=None,files=files)
        files=[dict(path=str(source),rel='regs/US/'+source.name,bot='regs',sha256=R.sha256_file(source),order=R.batch_order('fixture',st.st_mtime,source.name),mtime=st.st_mtime,full=False)]
        R.US_FEDERAL_KEY='offline_reference'
        reference=R.build_place(job('ref',files,[]));assert not reference['error']
        R.US_FEDERAL_KEY=original_key
        rel=reference['written'][0][0];published=root/'ref/out'/rel
        data=published.read_bytes();expected=pq.read_table(published).to_pylist();sha=hashlib.sha256(data).hexdigest();revision='a'*40
        second_rel=rel.replace('_html.parquet','.s0002_html.parquet')
        class Api:
            def repo_info(self,*a,**kw):return SimpleNamespace(sha=revision)
            def get_paths_info(self,*a,**kw):
                assert kw['revision']==revision
                return [SimpleNamespace(path=p,size=len(data),lfs=dict(sha256=sha)) for p in (rel,second_rel)]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def raise_for_status(self):pass
            def iter_content(self,**kw):yield data
        class Session:
            def get(self,url,**kw):
                assert '/resolve/'+revision+'/' in url
                # Prior owned source must be closed, not merely unlinked, before fetching the next.
                for fd in Path('/proc/self/fd').iterdir():
                    try: assert 'owned_source.parquet' not in str(fd.readlink())
                    except FileNotFoundError: pass
                return Response()
        U.HfApi=Api;U.requests=Session()
        actual=R.build_place(job('actual',[],[rel,second_rel]));assert not actual['error'],actual.get('traceback')
        got=[row for r,_ in actual['written'] for row in pq.read_table(root/'actual/out'/r).to_pylist()]
        assert got==expected
        assert published.read_bytes()==data and source.exists()
        assert not list((root/'actual/work').rglob('owned_source.parquet'))
        print('PASS source-to-build output equivalence; original published/staged bytes retained; owned fetched shard released; peak',actual['stats']['us_transient_peak_bytes'])
    finally:
        R.US_FEDERAL_KEY=original_key;U.HfApi=original_api;U.requests=original_requests;shutil.rmtree(root)
if __name__=='__main__':main()
