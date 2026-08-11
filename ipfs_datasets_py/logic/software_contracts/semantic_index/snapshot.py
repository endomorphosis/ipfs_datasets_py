"""Deterministic, single-acquisition repository input snapshots.

The snapshot is the authority boundary: every non-opaque entry owns the exact
bytes which were selected.  Consumers must use those captured bytes, rather
than resolving a path or Git object a second time.
"""
from __future__ import annotations

import os
import posixpath
import stat
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured, validate_cid

SNAPSHOT_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-snapshot@3"
SNAPSHOT_ENTRY_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-snapshot-entry@2"
REPOSITORY_ID_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.semantic-repository-identity@2"
DEFAULT_MAX_FILE_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_MAX_ENTRIES: Final[int] = 100_000
GIT_COMMAND_TIMEOUT_SECONDS: Final[float] = 10.0
_IGNORED_DIRECTORIES: Final[frozenset[str]] = frozenset({".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".venv", "venv", "env", "build", "dist", ".eggs", "htmlcov", "coverage", "node_modules", "vendor", "third_party", "third-party", "external", "site-packages", ".semantic-index", "semantic-index-state", ".semantic_index"})
_LOCK_NAMES: Final[frozenset[str]] = frozenset({"poetry.lock", "pdm.lock", "uv.lock", "requirements.txt", "requirements-dev.txt", "pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"})
_PYTEST_CONFIG_NAMES: Final[frozenset[str]] = frozenset({"pytest.ini", "tox.ini", "setup.cfg", "conftest.py"})
_SCHEMA_SUFFIXES: Final[tuple[str, ...]] = (".json", ".yaml", ".yml", ".toml", ".proto", ".schema")

class SnapshotError(ValueError): pass
class GitCommandTimeout(SnapshotError): pass
class GitCommandError(SnapshotError): pass

def _text(value: str, name: str) -> str:
    if type(value) is not str or not value or value != value.strip(): raise SnapshotError(f"{name} must be nonempty trimmed text")
    return value

def _path(value: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value: raise SnapshotError("path must be nonempty relative text")
    # Do not NFC-normalize or rewrite backslashes: POSIX names are bytes and
    # both spellings are legal and distinct evidence.
    if value.startswith("/") or value in {".", ".."} or value.startswith("../") or any(part in {"", ".", ".."} for part in value.split("/")): raise SnapshotError("path must be repository-relative")
    return value

def _raw_identity(raw: bytes) -> str: return raw.hex()
def _opaque_name(raw: bytes) -> str: return "@malformed-path/" + cid_for_bytes(raw).split("/")[-1]
def _decode_path(raw: bytes) -> tuple[str, str | None]:
    try:
        value = raw.decode("utf-8", "strict")
        _path(value)
        # Analysis models intentionally require normalized safe paths.  Keep
        # non-NFC/backslash names as opaque raw evidence, never rewrite them.
        if "\\" in value or value != unicodedata.normalize("NFC", value): raise SnapshotError("noncanonical")
        return value, None
    except (UnicodeDecodeError, SnapshotError):
        return _opaque_name(raw), "malformed_path"

def _ignored_raw(raw: bytes, excluded: frozenset[bytes]) -> bool:
    return any(component in _IGNORED_DIRECTORIES for component in raw.decode("utf-8", "surrogateescape").split("/")) or any(raw == item or raw.startswith(item + b"/") for item in excluded)

def _excluded_roots(values: Iterable[str | os.PathLike[str]] | None) -> frozenset[bytes]:
    result: set[bytes] = set()
    for value in values or ():
        raw = os.fsencode(value)
        if raw.startswith(b"/") or not raw or b"\0" in raw or any(p in {b"", b".", b".."} for p in raw.split(b"/")): raise SnapshotError("excluded roots must be repository-relative")
        result.add(raw.rstrip(b"/"))
    return frozenset(result)

@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    path: str
    kind: str
    size_bytes: int | None
    source_cid: str | None = None
    opaque_reason: str | None = None
    raw_path: str | None = None
    blob_oid: str | None = None
    captured_bytes: bytes | None = field(default=None, compare=False, repr=False)
    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _path(self.path)); object.__setattr__(self, "kind", _text(self.kind, "kind"))
        raw = self.raw_path if self.raw_path is not None else os.fsencode(self.path).hex()
        if type(raw) is not str or len(raw) % 2 or any(c not in "0123456789abcdef" for c in raw): raise SnapshotError("raw_path must be lowercase hex")
        object.__setattr__(self, "raw_path", raw)
        if self.size_bytes is not None and (type(self.size_bytes) is not int or self.size_bytes < 0): raise SnapshotError("size_bytes must be nonnegative")
        if self.source_cid is not None:
            try: validate_cid(self.source_cid)
            except Exception as exc: raise SnapshotError("source_cid must be a valid CID") from exc
        if self.blob_oid is not None and (len(self.blob_oid) not in {40,64} or any(c not in "0123456789abcdef" for c in self.blob_oid)): raise SnapshotError("blob_oid must be a Git OID")
        if self.opaque_reason is not None: object.__setattr__(self, "opaque_reason", _text(self.opaque_reason, "opaque_reason"))
        if self.opaque_reason is None and self.source_cid is None: raise SnapshotError("non-opaque entries require source_cid")
        if self.opaque_reason is not None and self.kind != "opaque": raise SnapshotError("opaque entries must have kind opaque")
        if self.captured_bytes is not None:
            if type(self.captured_bytes) is not bytes: raise SnapshotError("captured_bytes must be bytes")
            if self.source_cid is None or cid_for_bytes(self.captured_bytes) != self.source_cid: raise SnapshotError("captured bytes do not match source CID")
    @property
    def is_opaque(self) -> bool: return self.opaque_reason is not None
    def to_dict(self) -> dict[str, Any]:
        return {"schema": SNAPSHOT_ENTRY_SCHEMA, "path": self.path, "raw_path": self.raw_path, "kind": self.kind, "size_bytes": self.size_bytes, "source_cid": self.source_cid, "opaque_reason": self.opaque_reason, "blob_oid": self.blob_oid}
    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotEntry":
        expected={"schema","path","raw_path","kind","size_bytes","source_cid","opaque_reason","blob_oid"}
        if set(value)!=expected or value.get("schema")!=SNAPSHOT_ENTRY_SCHEMA: raise SnapshotError("unsupported SnapshotEntry schema")
        return cls(**{key:value[key] for key in expected-{ "schema"}})

@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repository_id: str; entries: Sequence[SnapshotEntry]; mode: str; max_file_bytes: int=DEFAULT_MAX_FILE_BYTES; max_entries: int=DEFAULT_MAX_ENTRIES; git_tree: str|None=None; git_commit: str|None=None
    def __post_init__(self) -> None:
        object.__setattr__(self,"repository_id",_text(self.repository_id,"repository_id"))
        if self.mode not in {"git-clean","git-working","filesystem"}: raise SnapshotError("unsupported snapshot mode")
        for name in ("git_tree","git_commit"):
            oid=getattr(self,name)
            if oid is not None and (len(oid) not in {40,64} or any(c not in "0123456789abcdef" for c in oid)): raise SnapshotError(f"{name} must be a Git OID")
        if self.mode=="git-clean" and (self.git_tree is None or self.git_commit is None): raise SnapshotError("git-clean snapshots require commit and tree")
        if type(self.max_file_bytes) is not int or self.max_file_bytes<1 or type(self.max_entries) is not int or self.max_entries<1: raise SnapshotError("snapshot limits must be positive")
        entries=tuple(sorted(self.entries,key=lambda e:(e.raw_path or "",e.path)))
        if len(entries)>self.max_entries or len({e.raw_path for e in entries})!=len(entries): raise SnapshotError("entries must be bounded and raw-unique")
        object.__setattr__(self,"entries",entries)
    def identity_payload(self)->dict[str,Any]: return {"schema":SNAPSHOT_SCHEMA,"repository_id":self.repository_id,"entries":[e.to_dict() for e in self.entries],"max_file_bytes":self.max_file_bytes,"max_entries":self.max_entries,"git_tree":self.git_tree,"git_commit":self.git_commit}
    @property
    def snapshot_cid(self)->str: return cid_for_structured(self.identity_payload())
    def to_dict(self)->dict[str,Any]:
        value=self.identity_payload(); value.update({"mode":self.mode,"snapshot_cid":self.snapshot_cid}); return value
    @classmethod
    def from_dict(cls,value:Mapping[str,Any])->"RepositorySnapshot":
        expected={"schema","repository_id","entries","mode","max_file_bytes","max_entries","git_tree","git_commit","snapshot_cid"}
        if set(value)!=expected or value.get("schema")!=SNAPSHOT_SCHEMA: raise SnapshotError("unsupported RepositorySnapshot schema")
        result=cls(value["repository_id"],tuple(SnapshotEntry.from_dict(x) for x in value["entries"]),value["mode"],value["max_file_bytes"],value["max_entries"],value["git_tree"],value["git_commit"])
        if value["snapshot_cid"]!=result.snapshot_cid: raise SnapshotError("RepositorySnapshot snapshot_cid does not verify")
        return result

def _git(root:Path,args:Sequence[str])->subprocess.CompletedProcess[bytes]:
    try:return subprocess.run(["git",*args],cwd=str(root),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=GIT_COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc: raise GitCommandTimeout("git command timed out") from exc
def _git_ok(root:Path,args:Sequence[str],what:str)->subprocess.CompletedProcess[bytes]:
    result=_git(root,args); warning=result.stderr.lower()
    if result.returncode or any(x in warning for x in (b"permission denied",b"unable to access",b"cannot access",b"could not access",b"incomplete")): raise GitCommandError(f"git {what} failed or reported incomplete traversal")
    return result
def _git_root(root:Path)->Path|None:
    result=_git(root,("rev-parse","--show-toplevel"))
    if result.returncode:return None
    if result.stderr: raise GitCommandError("git root discovery warned")
    try:return Path(result.stdout.decode("utf-8","strict").strip()).resolve()
    except UnicodeDecodeError as exc: raise GitCommandError("git root is not UTF-8") from exc

def repository_identity(repository:str|os.PathLike[str],*,repository_id:str|None=None)->str:
    if repository_id is not None:return _text(repository_id,"repository_id")
    root=Path(repository).resolve(); git_root=_git_root(root)
    if git_root is None:
        st=os.stat(root,follow_symlinks=False); anchor={"device":st.st_dev,"inode":st.st_ino}
        return cid_for_structured({"schema":REPOSITORY_ID_SCHEMA,"kind":"filesystem","anchor":anchor})
    common=_git_ok(git_root,("rev-parse","--git-common-dir"),"common-dir").stdout.decode("utf-8","strict").strip()
    common_path=(git_root/common).resolve() if not os.path.isabs(common) else Path(common).resolve(); st=os.stat(common_path,follow_symlinks=False)
    roots=_git_ok(git_root,("rev-list","--max-parents=0","--all"),"root-commits").stdout.split()
    root_oids=sorted(x.decode("ascii","strict") for x in roots)
    origin=_git(git_root,("config","--get","remote.origin.url")); remote="" if origin.returncode else origin.stdout.decode("utf-8","replace").strip()
    return cid_for_structured({"schema":REPOSITORY_ID_SCHEMA,"kind":"git","origin":remote,"root_commits":root_oids,"common_anchor":{"device":st.st_dev,"inode":st.st_ino}})

def _kind(path:str)->str:
    name=posixpath.basename(path).lower(); suffix=posixpath.splitext(name)[1]
    if suffix in {".py",".pyi"}:return "python"
    if name in _PYTEST_CONFIG_NAMES or name=="pyproject.toml":return "pytest-config"
    if name in _LOCK_NAMES:return "dependency-lock"
    if suffix in _SCHEMA_SUFFIXES:return "schema"
    return "artifact"
def _opaque(path:str,raw:bytes,reason:str,size:int|None=None,oid:str|None=None,source_cid:str|None=None)->SnapshotEntry:return SnapshotEntry(path,"opaque",size,source_cid,reason,_raw_identity(raw),oid)
def _entry(path:str,raw_path:bytes,data:bytes,max_file_bytes:int,oid:str|None=None)->SnapshotEntry:
    if len(data)>max_file_bytes:return _opaque(path,raw_path,"oversized",len(data),oid)
    try:data.decode("utf-8","strict")
    except UnicodeDecodeError:return _opaque(path,raw_path,"undecodable",len(data),oid,cid_for_bytes(data))
    return SnapshotEntry(path,_kind(path),len(data),cid_for_bytes(data),None,_raw_identity(raw_path),oid,data)
def _working_entry(root:Path,path:str,raw:bytes,*,max_file_bytes:int)->SnapshotEntry:
    candidate=os.fsencode(root)+b"/"+raw
    try:
        before=os.stat(candidate,follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):return _opaque(path,raw,"symlink_or_nonregular",before.st_size)
        if before.st_size>max_file_bytes:return _opaque(path,raw,"oversized",before.st_size)
        nofollow=getattr(os,"O_NOFOLLOW",None)
        if nofollow is None:return _opaque(path,raw,"symlink_or_nonregular",before.st_size)
        fd=os.open(candidate,os.O_RDONLY|nofollow)
        with os.fdopen(fd,"rb") as handle:
            opened=os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):return _opaque(path,raw,"symlink_or_nonregular",before.st_size)
            data=handle.read(max_file_bytes+1)
        after=os.stat(candidate,follow_symlinks=False)
    except FileNotFoundError:return _opaque(path,raw,"missing")
    except OSError:return _opaque(path,raw,"unreadable")
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):return _opaque(path,raw,"raced",after.st_size)
    return _entry(path,raw,data,max_file_bytes)
def _clean_git_entries(root:Path,tree:str,*,max_file_bytes:int,max_entries:int,excluded:frozenset[bytes])->Iterable[SnapshotEntry]:
    records=[x for x in _git_ok(root,("ls-tree","-r","-z",tree),"tree listing").stdout.split(b"\0") if x]
    if len(records)>max_entries:raise SnapshotError("selected entries exceed max_entries")
    for record in records:
        try: meta,raw=record.split(b"\t",1); mode,typ,oid=meta.decode("ascii").split()
        except ValueError: raise GitCommandError("malformed git tree record")
        if _ignored_raw(raw,excluded):continue
        path,malformed=_decode_path(raw)
        if malformed:yield _opaque(path,raw,malformed,None,oid);continue
        if mode=="120000" or typ!="blob":yield _opaque(path,raw,"symlink_or_nonregular",None,oid);continue
        size_result=_git_ok(root,("cat-file","-s",oid),"blob size")
        try:size=int(size_result.stdout.strip())
        except ValueError:raise GitCommandError("invalid Git blob size")
        if size>max_file_bytes:yield _opaque(path,raw,"oversized",size,oid);continue
        content=_git_ok(root,("cat-file","blob",oid),"blob read").stdout
        if len(content)!=size:raise GitCommandError("Git blob size changed during acquisition")
        yield _entry(path,raw,content,max_file_bytes,oid)
def _working_paths(root:Path,*,max_entries:int,excluded:frozenset[bytes])->list[tuple[str,bytes,str|None]]:
    data=_git_ok(root,("ls-files","-z","--cached","--others","--exclude-standard"),"working listing").stdout; result=[]; seen=set()
    for raw in (x for x in data.split(b"\0") if x):
        if _ignored_raw(raw,excluded):continue
        path,malformed=_decode_path(raw)
        if raw not in seen:seen.add(raw);result.append((path,raw,malformed))
    if len(result)>max_entries:raise SnapshotError("selected entries exceed max_entries")
    return sorted(result,key=lambda item:item[1])
def _filesystem_paths(root:Path,*,max_entries:int,excluded:frozenset[bytes])->list[tuple[str,bytes,str|None]]:
    base=os.fsencode(root); stack=[b""]; result=[]
    while stack:
        relative=stack.pop(); directory=base+(b"/"+relative if relative else b"")
        try:
            with os.scandir(directory) as scan: children=sorted(list(scan),key=lambda x:os.fsencode(x.name))
        except OSError:
            if relative:
                path,malformed=_decode_path(relative); result.append((path,relative,malformed or "unreadable_directory"))
            continue
        for child in children:
            raw=relative+(b"/" if relative else b"")+os.fsencode(child.name)
            if _ignored_raw(raw,excluded):continue
            path,malformed=_decode_path(raw)
            try:
                isdir=child.is_dir(follow_symlinks=False)
            except OSError: result.append((path,raw,malformed or "unreadable")); continue
            if isdir: stack.append(raw)
            else: result.append((path,raw,malformed))
            if len(result)>max_entries:raise SnapshotError("selected entries exceed max_entries")
    return sorted(result,key=lambda item:item[1])
def _status_is_clean(root:Path,excluded:frozenset[bytes])->bool:
    data=_git_ok(root,("status","--porcelain=v1","-z","--untracked-files=all"),"status").stdout
    parts=[x for x in data.split(b"\0") if x]; index=0
    while index<len(parts):
        record=parts[index]; index+=1
        if len(record)<4:raise GitCommandError("malformed git status")
        raw=record[3:]
        # Rename/copy has a second NUL path. Treat either non-excluded path as dirty.
        paths=[raw]
        if record[:1] in {b"R",b"C"} or record[1:2] in {b"R",b"C"}:
            if index>=len(parts):raise GitCommandError("truncated git status rename")
            paths.append(parts[index]);index+=1
        if any(not _ignored_raw(path,excluded) for path in paths):return False
    return True
def snapshot_repository(repository:str|os.PathLike[str],*,repository_id:str|None=None,max_file_bytes:int=DEFAULT_MAX_FILE_BYTES,max_entries:int=DEFAULT_MAX_ENTRIES,excluded_roots:Iterable[str|os.PathLike[str]]|None=None,state_root:str|os.PathLike[str]|None=None,control_root:str|os.PathLike[str]|None=None)->RepositorySnapshot:
    if type(max_file_bytes) is not int or max_file_bytes<1 or type(max_entries) is not int or max_entries<1:raise SnapshotError("snapshot limits must be positive")
    root=Path(repository).resolve()
    if not root.is_dir():raise SnapshotError("repository must be an existing directory")
    excluded=_excluded_roots(tuple(excluded_roots or ()) + (() if state_root is None else (state_root,)) + (() if control_root is None else (control_root,)))
    git_root=_git_root(root); identity=repository_identity(root,repository_id=repository_id)
    if git_root is not None:
        if _status_is_clean(git_root,excluded):
            commit=_git_ok(git_root,("rev-parse","HEAD"),"HEAD").stdout.decode("ascii","strict").strip(); tree=_git_ok(git_root,("rev-parse","HEAD^{tree}"),"HEAD tree").stdout.decode("ascii","strict").strip()
            return RepositorySnapshot(identity,tuple(_clean_git_entries(git_root,tree,max_file_bytes=max_file_bytes,max_entries=max_entries,excluded=excluded)),"git-clean",max_file_bytes,max_entries,tree,commit)
        entries=[]
        for path,raw,malformed in _working_paths(git_root,max_entries=max_entries,excluded=excluded): entries.append(_opaque(path,raw,malformed) if malformed else _working_entry(git_root,path,raw,max_file_bytes=max_file_bytes))
        return RepositorySnapshot(identity,tuple(entries),"git-working",max_file_bytes,max_entries)
    entries=[]
    for path,raw,malformed in _filesystem_paths(root,max_entries=max_entries,excluded=excluded): entries.append(_opaque(path,raw,malformed) if malformed else _working_entry(root,path,raw,max_file_bytes=max_file_bytes))
    return RepositorySnapshot(identity,tuple(entries),"filesystem",max_file_bytes,max_entries)

__all__=["DEFAULT_MAX_ENTRIES","DEFAULT_MAX_FILE_BYTES","GIT_COMMAND_TIMEOUT_SECONDS","GitCommandError","GitCommandTimeout","RepositorySnapshot","SNAPSHOT_ENTRY_SCHEMA","SNAPSHOT_SCHEMA","SnapshotEntry","SnapshotError","repository_identity","snapshot_repository"]
