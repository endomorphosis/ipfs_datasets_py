"""Offline download regression, fake official resolve responses, no token required."""
import sys,tempfile,hashlib,shutil
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
import us_source as U,run_loop as R,us_checkpoint as C

def snapshot():
    root=Path.home()/'.cache/huggingface'
    return {str(p.relative_to(root)):(p.stat().st_size,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}

def main():
    before=snapshot(); root=Path(tempfile.mkdtemp(prefix='us_source_test_'))
    data=b'PARQUET_FIXTURE_BYTES'*300; rev='a'*40; sha=hashlib.sha256(data).hexdigest()
    spec=dict(path='world_law/data/US/iso_US.s0001_html.parquet',size=len(data),sha256=sha)
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def raise_for_status(self): pass
        def iter_content(self,**kw):
            yield data[:100]
            if self.fail: raise IOError('synthetic mid-download failure')
            yield data[100:]
    class Session:
        fail=False
        def get(self,url,**kw):
            assert '/resolve/'+rev+'/' in url
            out=Response();out.fail=self.fail;return out
    class Api:
        def repo_info(self,*args,**kw): return SimpleNamespace(sha=rev)
        def get_paths_info(self,*args,**kw):
            assert kw['revision']==rev
            return [SimpleNamespace(path=spec['path'],size=len(data),lfs=dict(sha256=sha))]
    p=root/'source.parquet'; guard=R.USTransientGuard(lambda:list(root.glob('*')),cap=10000,free=lambda:50*1024**3)
    try:
        assert U.specs('test/repo',[spec['path']],api=Api())==(rev,[spec])
        U.fetch('test/repo',rev,spec,p,guard,Session()); assert p.read_bytes()==data
        # Source file counts against same quota as every other artifact.
        q=root/'chunks'
        with guard.open(q) as out:
            try: out.write(b'x'*4000);assert False
            except RuntimeError as e: assert 'TMP_CAP' in str(e)
        assert p.stat().st_size==len(data) and q.stat().st_size==0
        p.unlink();q.unlink()
        session=Session();session.fail=True
        try: U.fetch('test/repo',rev,spec,p,guard,session);assert False
        except IOError: pass
        assert not p.exists()
        retained=root/'checkpoint-sentinel';retained.write_bytes(b'KEEP')
        low=[False]
        def memory_check():
            if low[0]:raise C.Pause('US_MEMORY_PAUSE download')
        class PauseResponse(Response):
            def iter_content(self,**kw):
                yield data[:100]
                low[0]=True
                yield data[100:]
        class PauseSession(Session):
            def get(self,*args,**kw):return PauseResponse()
        guard.memory_check=memory_check
        try: U.fetch('test/repo',rev,spec,p,guard,PauseSession());assert False
        except C.Pause:pass
        guard.memory_check=None
        assert not p.exists() and retained.read_bytes()==b'KEEP'
        retained.unlink()
        wrong=dict(spec,sha256='0'*64)
        try: U.fetch('test/repo',rev,wrong,p,guard,Session());assert False
        except ValueError: pass
        assert not p.exists()
        stats={}
        it=U.sources('test/repo',[spec['path']],root,guard,stats,api=Api(),session=Session(),token=False)
        owned=next(it);assert owned.read_bytes()==data;it.close();assert not owned.exists()
        assert snapshot()==before
        print('PASS pinned revision, byte equivalence, aggregate source quota, partial-failure/hash-failure cleanup, owned release, shared-cache delta=0')
    finally:shutil.rmtree(root)
if __name__=='__main__':main()
