from pathlib import Path
import hashlib,json,os,stat,time
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_native_pool as module

def candidate(root):
    entries={}
    def fail(error):
        raise error
    for directory, dirs, files, directory_fd in os.fwalk(root,follow_symlinks=False,onerror=fail):
        prefix=os.path.relpath(directory,root)
        prefix='' if prefix=='.' else prefix+'/'
        for name in files+dirs:
            if not name.endswith('.py'):
                continue
            observed=os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
            if stat.S_ISLNK(observed.st_mode):
                raise ValueError('native pool producer source aliases another tree')
            if stat.S_ISDIR(observed.st_mode):
                continue
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
            with os.fdopen(fd,'rb') as handle:
                before=os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode) or (before.st_dev,before.st_ino)!=(observed.st_dev,observed.st_ino):
                    raise ValueError('producer source file changed or is not regular')
                entries[prefix+name]=hashlib.sha256(handle.read()).hexdigest()
                after=os.fstat(handle.fileno())
                fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
                if any(getattr(before,key)!=getattr(after,key) for key in fields):
                    raise ValueError('producer source changed during read')
    raw=json.dumps(entries,sort_keys=True,separators=(',',':')).encode()
    return {'sha256':hashlib.sha256(raw).hexdigest(),'file_count':len(entries)}

if __name__=='__main__':
    root=Path(module.__file__).resolve().parents[2]
    results=[]
    for index in range(3):
        for name,call in [('baseline',module._package_manifest),('candidate',lambda:candidate(root))]:
            start=time.perf_counter();manifest=call();elapsed=time.perf_counter()-start
            results.append({'implementation':name,'index':index,'wall_seconds':elapsed,'manifest':manifest})
    assert len({row['manifest']['sha256'] for row in results})==1
    path=Path(__file__).with_name('manifest-comparison.json')
    path.write_text(json.dumps({'results':results,'hashes_equal':True,'file_contents_hashed_every_time':True},indent=2)+'\n')
    print(path.read_text())
