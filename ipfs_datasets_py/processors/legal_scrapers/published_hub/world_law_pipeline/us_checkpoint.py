"""Owned, bounded US replay checkpoints. No network/publication; immutable shard generations."""
import json,hashlib,pickle,os,shutil,time,resource
from pathlib import Path

class Pause(RuntimeError): pass
class Corrupt(RuntimeError): pass

def available():
    return int(next(x for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')).split()[1])*1024

def digest_file(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def fingerprint(job):
    # Discovery already calculated source hashes; revalidate before checkpoint reuse.
    files=[]
    for f in job['files']:
        p=Path(f['path'])
        sha=digest_file(p)
        if sha!=f['sha256']:raise Pause('US_CHECKPOINT staging changed since discovery; stays staged')
        files.append((f['rel'],sha,f['full'],f['order']))
    class HashSink:
        def __init__(self):self.h=hashlib.sha256()
        def write(self,b):self.h.update(b);return len(b)
    h=HashSink()
    pickle.Pickler(h,5).dump((job.get('overrides'),job.get('primary_index'),job.get('xdedup')))
    sf=HashSink();pickle.Pickler(sf,5).dump(files)
    code={p.name:digest_file(p) for p in (Path(__file__).parent/n for n in ('run_loop.py','us_replay.py','us_source.py','us_checkpoint.py','schema.py'))}
    return dict(staging_context=h.h.hexdigest(),staging_fingerprint=sf.h.hexdigest(),staging_full=any(f[2] for f in files),code=code)

class Checkpoint:
    VERSION=1
    def __init__(self,root,status,identity,guard,memory=None):
        self.root=Path(root);self.status=Path(status);self.guard=guard;self.memory=memory or available
        self.root.mkdir(parents=True,exist_ok=True)
        marker=self.root/'.owner'
        if not marker.exists():
            if any(self.root.iterdir()):raise Corrupt('US_CHECKPOINT unowned directory; no deletion')
            with self.guard.open(marker) as f:f.write(b'world_law_us_checkpoint_v1')
        if marker.read_text()!='world_law_us_checkpoint_v1':raise Corrupt('US_CHECKPOINT invalid ownership marker')
        self.manifest=self.root/'manifest.json';self.identity=identity;self.data=None;self.store=None
        if self.manifest.exists():
            try:
                self.data=json.loads(self.manifest.read_text())
                if self.data['version']!=self.VERSION:raise ValueError('schema version')
                if self.data['identity']!=identity:
                    # Safe reconciliation across unrelated Hub commits only with identical source hashes,
                    # ordered staged fingerprint and code/context. Otherwise discard owned intermediates.
                    old=dict(self.data['identity']);new=dict(identity)
                    old.pop('revision',None);new.pop('revision',None)
                    if not old.get('staging_full') and not new.get('staging_full'):
                        old.pop('staging_fingerprint',None);new.pop('staging_fingerprint',None)
                    if old!=new:self.reset();self.data=None
                    else:self.data['identity']=identity
                if self.data:
                    if self.memory()<int(2.5*1024**3):
                        raise Pause('US_MEMORY_PAUSE admission <2.5 GiB; checkpoint retained')
                    self.validate()
            except (Pause,Corrupt):raise
            except Exception as e:raise Corrupt('US_CHECKPOINT corrupt manifest/checkpoint; retained, publishing blocked') from e
        self.done=self.data['completed'] if self.data else 0
        self.start_rows=(self.data or {}).get('stats',{}).get('us_source_input_rows_attempted',0)
        self.clean_work()
        self.block('ready')
        if self.memory()<int(2.5*1024**3):
            self.block('memory_admission_below_2.5GiB');raise Pause('US_MEMORY_PAUSE admission <2.5 GiB')
        self.guard.check()
        if self.data:
            self.data['identity']=self.identity
            self.atomic(self.manifest,self.data)
        if self.data:
            base=self.root/self.data['base'];self.guard.check(base.stat().st_size+1024**2)
            shutil.copyfile(base,self.root/'dedup.sqlite');self.guard.check()

    def reset(self):
        for p in self.root.iterdir():
            if p.name!='.owner':
                if not p.is_file():raise Corrupt('US_CHECKPOINT unexpected directory; no recursive deletion')
                p.unlink()

    def validate(self):
        d=self.data
        if not isinstance(d['completed'],int) or not 0<d['completed']<=len(self.identity['sources']):raise ValueError('completed')
        if d['base']!=f"base-{d['completed']:05d}.sqlite":raise ValueError('generation mismatch')
        if not isinstance(d['next_chunk'],int) or d['next_chunk']<0:raise ValueError('next chunk')
        if any(int(Path(n).stem[5:])>=d['next_chunk'] for n in d['chunks']):raise ValueError('unsealed chunk')
        for name,info in {d['base']:d['base_info'],**d['chunks']}.items():
            self.memory_check()
            if Path(name).name!=name or not (name.startswith('base-') or name.startswith('chunk')):raise ValueError('unsafe filename')
            p=self.root/name
            if not p.is_file() or p.stat().st_size!=info['size'] or digest_file(p)!=info['sha256']:raise ValueError('checkpoint hash mismatch')
        import sqlite3
        db=sqlite3.connect(f'file:{self.root/d["base"]}?mode=ro',uri=True)
        try:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity')
        finally:db.close()

    def clean_work(self):
        # The durable manifest wins if interrupted between atomic replacement and in-memory update.
        if self.manifest.exists():
            durable=json.loads(self.manifest.read_text())
            names=[durable['base'],*durable['chunks']]
            if any(Path(n).name!=n for n in names):raise Corrupt('unsafe durable checkpoint names; retained')
            self.data=durable;self.done=durable['completed']
        keep={'.owner','manifest.json'}
        if self.data:keep.update([self.data['base'],*self.data['chunks']])
        for p in self.root.iterdir():
            if p.name not in keep:
                if not p.is_file():raise Corrupt('US_CHECKPOINT unexpected child directory')
                p.unlink()

    def memory_check(self):
        if self.memory()<int(1.5*1024**3):raise Pause('US_MEMORY_PAUSE available <1.5 GiB; verified checkpoint retained')

    def bind(self,store,stats):
        self.store=store;store.keep_chunks=True
        if self.data:
            store.chunk=self.data['next_chunk']
            stats.update(self.data['stats'])

    def atomic(self,path,value):
        tmp=path.with_name(path.name+'.next')
        b=json.dumps(value,sort_keys=True).encode()
        old_mode=getattr(self.guard,'metadata_mode',False);self.guard.metadata_mode=True
        try:
            self.guard.check(len(b)+4096)
            with self.guard.open(tmp) as f:f.write(b);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:self.guard.metadata_mode=old_mode
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def commit_shard(self,stats):
        self.memory_check();self.store.db.commit()
        generation=self.done+1
        base=self.root/f'base-{generation:05d}.sqlite'
        dbpath=self.store.dbpath
        self.guard.check(dbpath.stat().st_size+1024**2)
        # SQLite backup produces a committed snapshot; manifest remains on old generation until durable.
        import sqlite3
        backup=sqlite3.connect(base)
        try:self.store.db.backup(backup);backup.commit()
        finally:backup.close()
        with base.open('rb') as f:os.fsync(f.fileno())
        self.guard.check()
        chunks=dict(self.data['chunks']) if self.data else {}
        for p in self.root.glob('chunk*.z'):
            if p.name not in chunks:
                with p.open('rb') as f:os.fsync(f.fileno())
                chunks[p.name]=dict(size=p.stat().st_size,sha256=digest_file(p))
        metrics=self.metrics()
        d=dict(version=self.VERSION,identity=self.identity,completed=generation,base=base.name,
               base_info=dict(size=base.stat().st_size,sha256=digest_file(base)),chunks=chunks,
               next_chunk=self.store.chunk+1,stats=dict(stats),metrics=metrics)
        self.atomic(self.manifest,d)
        old=self.data;self.data=d;self.done=generation;self.store.chunk=d['next_chunk']
        if old:(self.root/old['base']).unlink(missing_ok=True)
        self.block('checkpointed')

    def wrap(self,paths,stats):
        for path in paths:
            self.memory_check()
            spec=self.identity['sources'][self.done]
            p=Path(path)
            if p.stat().st_size!=spec['size'] or digest_file(p)!=spec['sha256']:
                raise Corrupt('US_CHECKPOINT source differs from pinned metadata; retained, stays staged')
            self.memory_check()
            yield path
            self.commit_shard(stats) # only after caller exhausted and closed entire verified source shard

    def metrics(self):
        old=(self.data or {}).get('metrics',{})
        try:previous=json.loads(self.status.read_text()).get('metrics',{})
        except (ValueError,FileNotFoundError):previous={}
        return dict(peak_rss_kib=max(old.get('peak_rss_kib',0),previous.get('peak_rss_kib',0),getattr(self.guard,'peak_rss_kib',0)),
                    rss_method='VmRSS sampled at US guarded writes',
                    process_lifetime_peak_rss_kib=max(old.get('process_lifetime_peak_rss_kib',0),previous.get('process_lifetime_peak_rss_kib',0),resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
                    aggregate_peak_bytes=max(old.get('aggregate_peak_bytes',0),previous.get('aggregate_peak_bytes',0),self.guard.peak))

    def block(self,reason):
        try:d=json.loads(self.status.read_text())
        except (FileNotFoundError,ValueError):d={}
        now=time.time();d.setdefault('blocked_since',now)
        d.update(reason=reason,updated_at=now,blocked_over_24h=now-d['blocked_since']>=86400,
                 completed_source_shards=getattr(self,'done',0),revision=self.identity.get('revision'),
                 metrics=self.metrics() if hasattr(self,'data') else {})
        # status is small, outside checkpoint; quota reserve covers both temporary and destination bytes.
        self.atomic(self.status,d)

    def finish_attempt(self,stats,error):
        # Store must be CLOSED first. Roll back to immutable last whole-shard checkpoint.
        self.clean_work() # reclaim ONLY uncommitted owned work before quota-guarded status writes
        self.block(error or 'awaiting_verified_publication')
        d=json.loads(self.status.read_text())
        d['cumulative_attempted_input_rows']=d.get('cumulative_attempted_input_rows',0)+max(0,stats.get('us_source_input_rows_attempted',0)-self.start_rows)+stats.get('us_stage_input_rows_attempted',0)
        d['committed_source_input_rows']=(self.data or {}).get('stats',{}).get('us_source_input_rows_attempted',0)
        d['cumulative_attempted_output_rows']=d.get('cumulative_attempted_output_rows',0)+stats.get('us_checkpoint_output_rows_attempted',0)
        d['candidate_output_rows']=stats.get('us_checkpoint_output_rows')
        d['candidate_input_rows']=(stats.get('us_source_input_rows_attempted',0)+stats.get('us_stage_input_rows_attempted',0)) if d['candidate_output_rows'] is not None else None
        d['candidate_stats']=dict(stats) if d['candidate_output_rows'] is not None else None
        d['candidate_attempt_id']=getattr(self,'attempt_id',None) if d['candidate_output_rows'] is not None else None
        d['publication_verified']=False
        self.atomic(self.status,d)
        self.clean_work()

def mark_admission_blocked(status,guard,reason="memory_admission_below_2.5GiB"):
    status=Path(status)
    try:d=json.loads(status.read_text())
    except (FileNotFoundError,ValueError):d={}
    now=time.time();d.setdefault('blocked_since',now)
    d.update(reason=reason,updated_at=now,blocked_over_24h=now-d['blocked_since']>=86400,publication_verified=False)
    b=json.dumps(d).encode();guard.check(len(b)+4096)
    tmp=status.with_name(status.name+'.next')
    with guard.open(tmp) as f:f.write(b);f.flush();os.fsync(f.fileno())
    os.replace(tmp,status)

def verified_publication(root,status,ids,guard,expected_attempt=None):
    """Called ONLY after existing eviction independently matched US Hub hashes + metadata."""
    root=Path(root);status=Path(status)
    if not status.exists():return
    d=json.loads(status.read_text())
    if d.get('candidate_output_rows') is None or (expected_attempt is not None and d.get('candidate_attempt_id')!=expected_attempt):
        raise Corrupt('US verified upload lacks matching candidate counts; report withheld, checkpoint retained')
    d.update(publication_verified=True,reason='verified_us_commit',verified_at=time.time(),commit_ids=list(ids),
             verified_output_rows=d.get('candidate_output_rows'),blocked_over_24h=False)
    d.pop('blocked_since',None)
    b=json.dumps(d,sort_keys=True).encode();guard.check(len(b)+4096)
    nxt=status.with_name(status.name+'.next')
    with guard.open(nxt) as f:f.write(b);f.flush();os.fsync(f.fileno())
    os.replace(nxt,status)
    if root.exists():
        if (root/'.owner').read_text()!='world_law_us_checkpoint_v1':raise Corrupt('checkpoint owner mismatch; retained')
        files=list(root.iterdir())
        if any(not p.is_file() for p in files):raise Corrupt('checkpoint contains unexpected directory; retained')
        for p in files:p.unlink()
        root.rmdir()
