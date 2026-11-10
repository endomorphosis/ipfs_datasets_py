"""Bounded synthetic US build regression tests; no Hub access."""
import sys, tempfile, shutil, pickle
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import run_loop as R
from test_hold_policy import base, w
import pyarrow.parquet as pq

def main():
    root=Path(tempfile.mkdtemp(prefix='us_guard_test_'))
    try:
        paths=[]
        g=R.USTransientGuard(lambda: paths, cap=4096, free=lambda: 50*1024**3)
        a=root/'a'; b=root/'b'; paths.extend([a,b])
        with g.open(a) as f: f.write(b'x'*2048)
        with g.open(b) as f:
            f.write(b'x'*2048)
            try: f.write(b'x'); assert False
            except RuntimeError as e: assert 'TMP_CAP' in str(e)
        assert g.peak==4096
        print('MEASURED aggregate quota fixture peak',g.peak,'bytes; synchronous stat after every raw write')
        low=R.USTransientGuard(lambda: [], free=lambda: R.USTransientGuard.FLOOR)
        try: low.pickle_size({'html':'x'*100}); assert False
        except RuntimeError as e: assert 'DISK_FLOOR' in str(e)

        state=root/'state'; state.mkdir()
        source=root/'staging/regs/US/iso_US.fixture.jsonl'
        rows=[base(str(i%35),place_id='iso:US',country_code='US',language='en',html=f'<p>law {i}</p>') for i in range(80)]
        w(source, rows)
        def build(label, full=False):
            out=root/label; scratch=root/(label+'_work'); scratch.mkdir()
            st=source.stat()
            job=dict(cc='US',key='iso_US',out_dir=str(out),scratch=str(scratch),quarantine=str(root/'q'),held=str(root/'held'),run_id='fixture',overrides={},hub_files=[],hub_download=False,repo='test/offline',state=str(state),primary_index=None,
                     files=[dict(path=str(source),rel='regs/US/iso_US.fixture.jsonl',bot='regs',sha256=R.sha256_file(source),order=R.batch_order('fixture',st.st_mtime,source.name),mtime=st.st_mtime,full=full)])
            result=R.build_place(job)
            data=[]
            for rel,_ in result['written']: data.extend(pq.read_table(out/rel).to_pylist())
            return result,data
        baseline_key=R.US_FEDERAL_KEY
        R.US_FEDERAL_KEY='disabled_for_equivalence'
        baseline,expected=build('baseline')
        R.US_FEDERAL_KEY=baseline_key
        actual,got=build('guarded')
        assert not actual['error'],actual.get('traceback')
        assert expected==got and len(got)==35
        full,fullgot=build('full',True)
        assert not full['error'] and fullgot==got
        print('MEASURED guarded synthetic build peak',actual['stats']['us_transient_peak_bytes'],'bytes; spool + all parquet parts after each raw write')
        old=R.US_NATIONAL_TMP_CAP_BYTES
        R.US_NATIONAL_TMP_CAP_BYTES=1024
        try: blocked,_=build('blocked')
        finally: R.US_NATIONAL_TMP_CAP_BYTES=old
        assert 'TMP_CAP' in blocked['error'] and source.exists()
        assert not list((root/'blocked_work').rglob('*.pkl'))
        assert not list((root/'blocked').rglob('*.tmp'))
        floor=R.USTransientGuard.FLOOR
        R.USTransientGuard.FLOOR=10**20
        try: blocked,_=build('floor')
        finally: R.USTransientGuard.FLOOR=floor
        assert 'DISK_FLOOR' in blocked['error'] and source.exists()
        print('PASS cap exceeded, floor guard, output equivalence, full snapshot, duplicate IDs, staged retention')
    finally: shutil.rmtree(root)
if __name__=='__main__': main()
