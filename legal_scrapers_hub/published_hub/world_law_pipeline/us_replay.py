"""Local disposable compressed replay chunks and SQLite metadata. No Hub access."""
import pickle, sqlite3, zlib, gzip, os
from pathlib import Path
from collections.abc import MutableMapping, MutableSet

class Store:
    CHUNK = 16 * 1024**2
    MAX_ROW = 128 * 1024**2
    SMALL_ROW = 16 * 1024**2
    RSS_LIMIT = 3 * 1024**3
    def __init__(self, root, guard):
        self.root=Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.keep_chunks=False
        self.guard=guard; self.chunk=0; self.refs=None; self.names=0
        self.dbpath=self.root/'dedup.sqlite'
        guard.check(1024**2)
        self.db=sqlite3.connect(self.dbpath)
        self.db.execute('PRAGMA journal_mode=OFF') # disposable scratch; never a published/source database
        self.db.execute('PRAGMA synchronous=OFF')
        self.db.execute('PRAGMA cache_size=-4096')
        self.db.execute('PRAGMA mmap_size=0')
        self.db.execute('PRAGMA temp_store=FILE')
        self.guard.check()
    def write(self, sql, args=()):
        # Reserve per mutation, including B-tree splits. max_page_count independently bounds DB allocation.
        self.guard.check(1024**2 + sum(len(x) for x in args if isinstance(x, bytes)))
        other=self.guard.used()-self.dbpath.stat().st_size
        allowed = min(self.guard.cap-other, self.dbpath.stat().st_size + self.guard.free()-self.guard.FLOOR-1024**2)
        pages=max(1,allowed//4096)
        self.db.execute(f'PRAGMA max_page_count={pages}')
        self.db.execute(sql,args); self.db.commit(); self.guard.check()
    def mapping(self):
        self.names+=1; name=f'm{self.names}'
        self.write(f'CREATE TABLE IF NOT EXISTS {name}(k TEXT PRIMARY KEY,v BLOB NOT NULL,o INTEGER,c INTEGER) WITHOUT ROWID')
        self.write(f'CREATE INDEX IF NOT EXISTS {name}_order ON {name}(o,k)')
        self.write(f'CREATE INDEX IF NOT EXISTS {name}_chunks ON {name}(c)')
        return Map(self,name)
    def set(self): return Set(self.mapping())
    def list(self): return List(self.mapping())
    def check_memory(self, size):
        # Admission estimate only: Python/Arrow field restoration still materializes one law.
        rss=int(next(l for l in Path('/proc/self/status').read_text().splitlines() if l.startswith('VmRSS:')).split()[1])*1024
        avail=int(next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')).split()[1])*1024
        need=8*size+256*1024**2
        if rss+need>self.RSS_LIMIT or avail<need+512*1024**2:
            raise RuntimeError(f'ROW_MEMORY_CAP US replay admission size={size} rss={rss} available={avail}; stays staged')
        self.guard.check()

    def serialized_size(self,row):
        # Avoid building a whole pickle bytes object; count writes. A single Unicode encoding is
        # inherently allocated by Pickler, so preflight field sizes before invoking it.
        def estimate(v):
            if isinstance(v,str):
                n=sum(len(v[i:i+65536].encode('utf-8')) for i in range(0,len(v),65536))
                if n>self.MAX_ROW: raise RuntimeError('ROW_CAP US field exceeds 128 MiB; stays staged')
                return n
            if isinstance(v,(bytes,bytearray)): return len(v)
            if isinstance(v,dict): return sum(estimate(k)+estimate(x) for k,x in v.items())
            if isinstance(v,(tuple,list)): return sum(estimate(x) for x in v)
            return 32
        estimated=estimate(row)
        if estimated>self.MAX_ROW: raise RuntimeError('ROW_CAP US row exceeds 128 MiB; stays staged')
        self.check_memory(estimated)
        class Count:
            n=0
            def write(me,b):
                me.n+=len(b)
                if me.n>Store.MAX_ROW: raise RuntimeError('ROW_CAP US replay row >128 MiB; stays staged')
                return len(b)
        counter=Count(); pickle.Pickler(counter,protocol=5).dump(row)
        return counter.n

    def append(self,row):
        size=self.serialized_size(row)
        if size>self.SMALL_ROW:
            # One owned compressed spill per giant law, never a split public row.
            p=self.root/f'chunk{self.chunk:06d}.z'
            if p.exists(): self.chunk+=1
            chunk=self.chunk; p=self.root/f'chunk{chunk:06d}.z'
            try:
                with self.guard.open(p) as raw:
                    with gzip.GzipFile(fileobj=raw,mode='wb',compresslevel=3,mtime=0) as zipped:
                        guard=self.guard
                        class Sink:
                            def write(me,b):
                                for i in range(0,len(b),65536):
                                    guard.check(); zipped.write(memoryview(b)[i:i+65536])
                                return len(b)
                        pickle.Pickler(Sink(),protocol=5).dump(row)
                self.guard.check()
            except BaseException:
                p.unlink(missing_ok=True); raise
            self.chunk+=1
            return chunk*2**40,-size # negative length denotes a standalone streaming spill
        b=zlib.compress(pickle.dumps(row,protocol=5),3)
        p=self.root/f'chunk{self.chunk:06d}.z'
        if p.exists() and p.stat().st_size+len(b)>self.CHUNK:
            self.chunk+=1; p=self.root/f'chunk{self.chunk:06d}.z'
        pos=p.stat().st_size if p.exists() else 0
        self.guard.check(len(b))
        with p.open('ab',buffering=0) as f: f.write(b)
        self.guard.check()
        return self.chunk*2**40+pos,len(b)

    def read(self,off,n):
        chunk,pos=divmod(off,2**40)
        if n<0:
            self.check_memory(-n)
            with gzip.open(self.root/f'chunk{chunk:06d}.z','rb') as f:
                return pickle.Unpickler(f).load()
        with (self.root/f'chunk{chunk:06d}.z').open('rb') as f:
            f.seek(pos); return pickle.loads(zlib.decompress(f.read(n)))
    def prepare_release(self,index):
        # Count only live references, not overwritten versions. SQL covering index avoids a Python ID set.
        self.refs=dict(self.db.execute(f'SELECT c,count(*) FROM {index.name} GROUP BY c'))
        for p in self.root.glob('chunk*.z'):
            if not self.keep_chunks and int(p.stem[5:]) not in self.refs: p.unlink()
    def release(self,off):
        c=off//2**40
        self.refs[c]-=1
        if self.refs[c]==0 and not self.keep_chunks:
            (self.root/f'chunk{c:06d}.z').unlink()
    def close(self): self.db.close()

class Map(MutableMapping):
    def __init__(self,s,n): self.s,self.name=s,n
    def __len__(self): return self.s.db.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0]
    def __iter__(self):
        for r in self.s.db.execute(f'SELECT k FROM {self.name}'): yield r[0]
    def __getitem__(self,k):
        r=self.s.db.execute(f'SELECT v FROM {self.name} WHERE k=?',(k,)).fetchone()
        if r is None: raise KeyError(k)
        return pickle.loads(r[0])
    def __setitem__(self,k,v):
        # Index tuples carry spool offset, length, doc_order; other mappings leave o/c null.
        ordered=isinstance(v,tuple) and len(v)==3 and all(isinstance(x,int) for x in v)
        o=v[2] if ordered else None; c=v[0]//2**40 if ordered else None
        class Count:
            n=0
            def write(me,b):
                me.n+=len(b)
                if me.n>Store.MAX_ROW: raise RuntimeError('ROW_CAP US replay metadata >128 MiB; stays staged')
                return len(b)
        self.s.guard.check()
        pickle.Pickler(Count(),protocol=5).dump(v)
        self.s.write(f'INSERT OR REPLACE INTO {self.name} VALUES(?,?,?,?)',(k,pickle.dumps(v,5),o,c))
    def __delitem__(self,k): self.s.write(f'DELETE FROM {self.name} WHERE k=?',(k,))
    def clear(self): self.s.write(f'DELETE FROM {self.name}')
    def items(self):
        for k,v in self.s.db.execute(f'SELECT k,v FROM {self.name}'): yield k,pickle.loads(v)
    def ordered(self):
        for k,v in self.s.db.execute(f'SELECT k,v FROM {self.name} ORDER BY o,k'): yield k,pickle.loads(v)
    def copy(self):
        out=self.s.mapping(); 
        for k,v in self.items(): out[k]=v
        return out
    def difference_count(self,seen):
        return self.s.db.execute(f'SELECT count(*) FROM {self.name} a WHERE NOT EXISTS (SELECT 1 FROM {seen.m.name} b WHERE b.k=a.k)').fetchone()[0]

class Set(MutableSet):
    def __init__(self,m): self.m=m
    def __len__(self): return len(self.m)
    def __iter__(self): return iter(self.m)
    def __contains__(self,k): return k in self.m
    def add(self,k): self.m[k]=True
    def discard(self,k): self.m.pop(k,None)
    def update(self,values):
        for v in values: self.add(v)

class List:
    def __init__(self,m): self.m=m; self.n=len(m)
    def append(self,v): self.m[f"{self.n:020d}"]=v; self.n+=1
    def __len__(self): return self.n
    def __iter__(self):
        for k,v in self.m.items(): yield v
