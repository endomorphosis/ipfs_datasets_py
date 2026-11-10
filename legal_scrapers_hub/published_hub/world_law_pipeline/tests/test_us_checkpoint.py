"""Owned synthetic SQLite/chunk checkpoints, no Hub requests or publication."""
import sys,tempfile,shutil,json
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
import us_checkpoint as C,us_replay as U,run_loop as R
GiB=1024**3

def main():
    tmp=Path(tempfile.mkdtemp(prefix='us_checkpoint_test_'));root=tmp/'cp';status=tmp/'status.json'
    mem=[4*GiB]
    identity=dict(revision='a'*40,sources=[dict(path='a',sha256='x'),dict(path='b',sha256='y')],staging_fingerprint='stageA',staging_full=False,staging_context='ctx',code='schema')
    def guard():return R.USTransientGuard(lambda:[p for p in tmp.rglob('*') if p.is_file()],free=lambda:50*GiB)
    def start(ident=identity):
        g=guard();cp=C.Checkpoint(root,status,ident,g,memory=lambda:mem[0]);g.memory_check=cp.memory_check
        store=U.Store(root,g);stats={};cp.bind(store,stats);index=store.mapping();return cp,store,stats,index,g
    try:
        cp,s,st,ix,g=start()
        row=dict(doc_id='a',doc_order=1,html='exact')
        off,n=s.append(row);ix['a']=(off,n,1);st.update(rows_existing=1,us_source_input_rows_attempted=1)
        cp.commit_shard(st)
        # Mid-next-shard overwrites a live ID and appends a new record; no complete-shard commit.
        off,n=s.append(dict(doc_id='a',doc_order=1,html='partial'));ix['a']=(off,n,1)
        off,n=s.append(dict(doc_id='b',doc_order=2,html='partial'));ix['b']=(off,n,2)
        mem[0]=GiB
        try:g.check(1);assert False
        except C.Pause:pass
        s.close();g.memory_check=None;cp.finish_attempt(st,'US_MEMORY_PAUSE')
        paused=json.loads(status.read_text());assert paused['publication_verified'] is False and paused['completed_source_shards']==1
        mem[0]=4*GiB
        cp,s,st,ix,g=start()
        assert cp.done==1 and set(ix)=={'a'} and s.read(*ix['a'][:2])==row
        off,n=s.append(dict(doc_id='b',doc_order=2,html='final'));ix['b']=(off,n,2);st.update(rows_existing=2,us_source_input_rows_attempted=2)
        cp.commit_shard(st)
        assert [s.read(*v[:2]) for _,v in ix.ordered()]==[row,dict(doc_id='b',doc_order=2,html='final')]
        # Persistent checkpoint bytes are included, even with no in-flight parquet.
        g.cap=g.used()+1
        try:g.check(2);assert False
        except RuntimeError as e:assert 'TMP_CAP' in str(e)
        g.cap=4*GiB;g.free=lambda:11*GiB
        try:g.check(1);assert False
        except RuntimeError as e:assert 'DISK_FLOOR' in str(e)
        g.free=lambda:50*GiB;s.close();g.memory_check=None;cp.finish_attempt(st,None)
        # Revision-only or append-only staging changes reconcile identical verified base contents.
        changed={**identity,'revision':'b'*40,'staging_fingerprint':'stageB'}
        cp,s,st,ix,g=start(changed);assert cp.done==2;s.close();g.memory_check=None;cp.finish_attempt(st,None)
        # Full snapshot/context or actual source hash changes discard ONLY owned intermediates.
        outside=tmp/'staging.jsonl';outside.write_text('KEEP')
        changed={**changed,'sources':[dict(path='a',sha256='changed')]}
        cp,s,st,ix,g=start(changed);assert cp.done==0 and not ix and outside.read_text()=='KEEP'
        s.close();g.memory_check=None;cp.finish_attempt({},'source_changed')
        changed={**changed,'staging_full':True,'staging_fingerprint':'fullC'}
        cp,s,st,ix,g=start(changed);assert cp.done==0 and not ix and outside.read_text()=='KEEP'
        off,n=s.append(row);ix['a']=(off,n,1);cp.commit_shard({'rows_existing':1})
        s.close();g.memory_check=None;cp.finish_attempt({},'pause')
        manifest=json.loads((root/'manifest.json').read_text())
        next(iter(manifest['chunks']))
        (root/next(iter(manifest['chunks']))).write_bytes(b'CORRUPT')
        try:start(changed);assert False
        except C.Corrupt:pass
        assert outside.read_text()=='KEEP'
        print('PASS pause/restart exact rows, mid-shard rollback, append/revision reconciliation, full invalidation, aggregate quota/floor, corruption, no publication advancement')
    finally:shutil.rmtree(tmp)
if __name__=='__main__':main()
