"""Narrow audited write boundary for the reviewed administrative closeout."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import sys
import tempfile

def require(value,message):
    if not value:raise AssertionError(message)

def identity(path):
    info=Path(path).lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),'ordinary write parent required')
    return (info.st_dev,info.st_ino)

class ReviewedWriteGate:
    def __init__(self,output_directory,ledger_path,lock_identity,ledger_parent_identity):
        self.output=Path(output_directory).absolute();self.ledger=Path(ledger_path).absolute()
        self.lock=self.ledger.with_name(self.ledger.name+'.lock')
        self.lock_identity=tuple(lock_identity);self.ledger_parent_identity=tuple(ledger_parent_identity)
        self.armed=False;self.output_identity=None;self.writer_phase=False;self.fd_registry={}
        self.named_temp_code=tempfile.NamedTemporaryFile.__code__
        self.mkstemp_function=tempfile._mkstemp_inner;self.mkstemp_code=self.mkstemp_function.__code__
        self.output_create_flags=os.O_CLOEXEC|os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW
        self.temp_create_flags=os.O_CLOEXEC|tempfile._bin_openflags
        self.lock_flags=os.O_CLOEXEC|os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK

    def arm(self):
        require(not self.armed,'write gate arms once')
        self.output_identity=identity(self.output)
        require(identity(self.ledger.parent)==self.ledger_parent_identity,'ledger parent changed')
        self.armed=True

    def _parent_fence(self,path,scope):
        if scope=='owned_output':
            require(path.parent==self.output and identity(self.output)==self.output_identity,'owned output parent changed')
        else:
            require(self.writer_phase and path.parent==self.ledger.parent and path.name.startswith('.daemon-reservation-')
                    and identity(self.ledger.parent)==self.ledger_parent_identity,'unapproved atomic temporary file')

    def register(self,fd,path,scope):
        require(self.armed and type(fd) is int and scope in {'owned_output','atomic_temp'},'unapproved writable descriptor registration')
        require(fd not in self.fd_registry,'descriptor already registered')
        path=Path(path).absolute();self._parent_fence(path,scope)
        opened=os.fstat(fd);current=path.lstat()
        require(stat.S_ISREG(opened.st_mode) and opened.st_nlink==1 and opened.st_uid==os.getuid()
                and stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode)
                and (opened.st_dev,opened.st_ino)==(current.st_dev,current.st_ino),'writable descriptor custody differs')
        self.fd_registry[fd]=(path,scope,opened.st_dev,opened.st_ino)

    def forget(self,fd):self.fd_registry.pop(fd,None)

    def _descriptor_fence(self,fd):
        require(type(fd) is int and fd in self.fd_registry,'untracked writable descriptor refused')
        path,scope,device,inode=self.fd_registry[fd];self._parent_fence(path,scope)
        opened=os.fstat(fd);current=path.lstat()
        require(stat.S_ISREG(opened.st_mode) and opened.st_nlink==1 and opened.st_uid==os.getuid()
                and stat.S_ISREG(current.st_mode) and not stat.S_ISLNK(current.st_mode)
                and (opened.st_dev,opened.st_ino)==(current.st_dev,current.st_ino)==(device,inode),'writable descriptor identity changed')

    def audit(self,event,args):
        if event.startswith(('socket.','subprocess.')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg'}:
            raise AssertionError('Closeout refuses network/process/signals')
        if event!='open':return
        path,mode,flags=args
        write=isinstance(mode,str) and any(c in mode for c in 'wax+')
        write|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if not write:return
        require(self.armed,'unreviewed writable open refused')
        if type(path) is int:
            self._descriptor_fence(path)
            require((mode,flags) in {('w',os.O_CLOEXEC|os.O_WRONLY|os.O_CREAT|os.O_TRUNC),
                                    ('w+',os.O_CLOEXEC|os.O_RDWR|os.O_CREAT|os.O_TRUNC)},'unexpected descriptor open mode')
            return
        require(isinstance(path,(str,bytes,os.PathLike)),'unrecognized writable path refused')
        path=Path(os.fsdecode(path)).absolute();caller=sys._getframe(1).f_code
        if path.parent==self.output:
            self._parent_fence(path,'owned_output')
            require(mode is None and flags==self.output_create_flags,'owned output must use exclusive nofollow create')
            return
        if path==self.lock:
            info=path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid()
                    and not stat.S_ISLNK(info.st_mode) and (info.st_dev,info.st_ino)==self.lock_identity,
                    'existing lock identity changed before open')
            require(mode is None and flags==self.lock_flags,'unexpected lock open flags');return
        if path==self.ledger.parent:
            # io.open(dir, opener=...) is a synthetic event from the genuine
            # NamedTemporaryFile function; no directory file is opened for write.
            require(self.writer_phase and caller is self.named_temp_code
                    and (mode,flags)==('w+',os.O_CLOEXEC|os.O_RDWR|os.O_CREAT|os.O_TRUNC)
                    and identity(path)==self.ledger_parent_identity,'unapproved synthetic tempfile directory open')
            return
        self._parent_fence(path,'atomic_temp')
        require(caller is self.mkstemp_code and mode is None and flags==self.temp_create_flags,
                'temporary writer must use genuine exclusive nofollow factory')

    @contextmanager
    def atomic_writer(self):
        require(self.armed and not self.writer_phase and tempfile._mkstemp_inner is self.mkstemp_function,
                'authenticated single atomic-writer phase required')
        self.writer_phase=True
        def tracked(directory,prefix,suffix,flags,output_type):
            require(Path(directory).absolute()==self.ledger.parent and prefix=='.daemon-reservation-' and suffix==''
                    and flags==tempfile._bin_openflags,'unapproved atomic factory request')
            fd,name=self.mkstemp_function(directory,prefix,suffix,flags,output_type)
            try:self.register(fd,name,'atomic_temp')
            except BaseException:
                os.close(fd);raise
            return fd,name
        tempfile._mkstemp_inner=tracked
        try:yield
        finally:
            tempfile._mkstemp_inner=self.mkstemp_function
            for fd,(_,scope,_,_) in list(self.fd_registry.items()):
                if scope=='atomic_temp':self.forget(fd)
            self.writer_phase=False
