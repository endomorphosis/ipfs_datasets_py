"""Synthetic hourly-path resume equivalence and publication gating, no network calls."""
import sys,tempfile,shutil
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import run_loop as R,us_checkpoint as C
from test_hold_policy import base,w
import pyarrow.parquet as pq

def main():
    root=Path(tempfile.mkdtemp(prefix='us_checkpoint_build_'))
    old_available=C.available;old_check=C.Checkpoint.memory_check;old_shard=R.S.SHARD_MAX_ROWS
    C.available=lambda:4*1024**3;R.S.SHARD_MAX_ROWS=10
    try:
        stage=root/'stage/regs/US/iso_US.fixture.jsonl'
        w(stage,[base(str(i),place_id='iso:US',country_code='US',language='en',html=f'<p>law {i}</p>') for i in range(40)])
        def job(label,files=[],checkpoint=True):
            state=root/label/'state';state.mkdir(parents=True,exist_ok=True)
            scratch=root/label/'work';scratch.mkdir(exist_ok=True)
            out=root/label/'out'
            return dict(cc='US',key='iso_US',out_dir=str(out),scratch=str(scratch),quarantine=str(root/label/'q'),held=str(root/label/'held'),run_id='fixture',overrides={},hub_files=[],hub_download=False,repo='test/offline',state=str(state),primary_index=None,files=files,
                        us_checkpoint_root=str(state/'cp') if checkpoint else None)
        fs=stage.stat()
        files=[dict(path=str(stage),rel='regs/US/'+stage.name,bot='regs',sha256=R.sha256_file(stage),order=R.batch_order('fixture',fs.st_mtime,stage.name),mtime=fs.st_mtime,full=False)]
        seedjob=job('seed',files,False);seed=R.build_place(seedjob);assert not seed['error'],seed.get('traceback')
        def prepare(label):
            j=job(label);shutil.copytree(Path(seedjob['out_dir']),j['out_dir']);return j
        reference=prepare('reference');reference['us_checkpoint_root']=None
        ref=R.build_place(reference);assert not ref['error']
        expected=[x for rel,_ in ref['written'] for x in pq.read_table(Path(reference['out_dir'])/rel).to_pylist()]
        j=prepare('resume')
        before={str(p):p.read_bytes() for p in Path(j['out_dir']).rglob('*.parquet')}
        def pause_after_first(self):
            if self.done==1:raise C.Pause('US_MEMORY_PAUSE injected between shards')
            return old_check(self)
        C.Checkpoint.memory_check=pause_after_first
        paused=R.build_place(j)
        assert 'US_MEMORY_PAUSE' in paused['error'] and not paused['written'] and not paused['files']
        assert all(Path(p).read_bytes()==b for p,b in before.items()) and stage.exists()
        C.Checkpoint.memory_check=old_check
        resumed=R.build_place(j);assert not resumed['error'],resumed.get('traceback')
        got=[x for rel,_ in resumed['written'] for x in pq.read_table(Path(j['out_dir'])/rel).to_pylist()]
        assert got==expected and resumed['rows']==40
        # Writer pause preserves whole-shard checkpoint and restarts rendering without re-reading source.
        j2=prepare('writer')
        def writer_pause(self):
            if list(Path(j2['out_dir']).rglob('*.tmp')):raise C.Pause('US_MEMORY_PAUSE injected writer')
            return old_check(self)
        C.Checkpoint.memory_check=writer_pause
        paused=R.build_place(j2);assert 'US_MEMORY_PAUSE' in paused['error'] and not paused['written']
        C.Checkpoint.memory_check=old_check
        resumed=R.build_place(j2);assert not resumed['error'],resumed.get('traceback')
        got=[x for rel,_ in resumed['written'] for x in pq.read_table(Path(j2['out_dir'])/rel).to_pylist()]
        assert got==expected
        assert stage.exists() and not list(root.rglob('ledger.jsonl'))
        print('PASS ordinary build-path source pause/restart and writer pause/restart exact equivalence; staged/cache preserved on pause; no ledger/publication advancement')
    finally:
        C.available=old_available;C.Checkpoint.memory_check=old_check;R.S.SHARD_MAX_ROWS=old_shard;shutil.rmtree(root)
if __name__=='__main__':main()
