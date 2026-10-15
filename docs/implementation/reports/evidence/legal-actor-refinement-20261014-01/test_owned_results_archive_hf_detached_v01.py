#!/usr/bin/env python3
"""Run the pinned publisher's detached commit/readback kernel on an in-memory SDK.

No publisher main, SDK import, network, filesystem payload, checkpoint or result
JSON is used. Only this source and its new public control receipt are written.
"""
import ast
import builtins
import hashlib
import io
import json
from pathlib import Path as DiskPath
from types import SimpleNamespace

ROOT=DiskPath(__file__).resolve().parent
SOURCE=ROOT/'publish_owned_results_archive_hf_v01.py'
SOURCE_PIN=dict(path=str(SOURCE),bytes=11591,sha256='15bfc889dccbd0b98ce40ab78649d4106bd15079d5f1d1f72ffb8e808fd21292')
OUTPUT=ROOT/'owned-results-archive-hf-detached-controls-v01.json'
PREFIX='archives/20261014-owned-released-results-v1'
REPO='Publicus/legal-ir-autoencoder'
PARENT='1'*40
REVISION='2'*40


def require(value,message):
    if not value:raise ValueError(message)


def deny(name,*args,**kwargs):raise AssertionError('Real imports prohibited in detached publisher kernel: '+name)


def source_nodes():
    raw=SOURCE.read_bytes()
    require((len(raw),hashlib.sha256(raw).hexdigest())==(SOURCE_PIN['bytes'],SOURCE_PIN['sha256']),'Exact sealed publisher source required')
    tree=ast.parse(raw)
    pure=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'require','remote_map','git_blob'}]
    require({node.name for node in pure}=={'require','remote_map','git_blob'} and len(pure)==3,'Exact pure publisher helpers required')
    main=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
    start=next(i for i,node in enumerate(main.body) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='before_info' for t in node.targets))
    end=next(i for i,node in enumerate(main.body[start:],start) if isinstance(node,ast.For) and ast.unparse(node.iter)=="gate['artifacts'].items()")
    kernel=main.body[start:end]
    require(kernel and not any(isinstance(n,(ast.Import,ast.ImportFrom)) for node in pure+kernel for n in ast.walk(node)),'Detached kernel cannot import SDK or production modules')
    require(sum(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='create_commit' for node in kernel for n in ast.walk(node))==1,'Exactly one publisher commit call site required')
    return pure,kernel


def scenario(mode='normal'):
    pure,kernel=source_nodes();store={};calls=[];writes=[]
    class MemoryPath:
        def __init__(self,value):self.value=value.value if isinstance(value,MemoryPath) else str(value)
        def __str__(self):return self.value
        def __fspath__(self):return self.value
        def __truediv__(self,value):return MemoryPath(self.value.rstrip('/')+'/'+str(value))
        def open(self,mode):require(mode=='rb','Only fake binary reads allowed');return io.BytesIO(store[self.value])
    def pin(path):
        path=str(path);data=store[path]
        item=dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        if mode=='local_preupload_drift' and path.endswith('original.tar.gz'):item['sha256']='f'*64
        return item
    def write(path,value):
        writes.append(str(path));store[str(path)]=json.dumps(value,sort_keys=True,allow_nan=False).encode();return pin(path)
    ns=dict(hashlib=hashlib,Path=MemoryPath,REPO=REPO,PREFIX=PREFIX,STATE=dict(stage='remote_intake',revision=None,commit_calls=0),
        BEFORE=MemoryPath('/memory/before.json'),AFTER=MemoryPath('/memory/after.json'),COMMIT=MemoryPath('/memory/commit.json'),
        DOWNLOAD=MemoryPath('/memory/readback'),pin=pin,write=write)
    ns['__builtins__']=dict(vars(builtins),__import__=deny)
    exec(compile(ast.Module(body=pure,type_ignores=[]),str(SOURCE)+'#pure-in-memory','exec'),ns)
    payloads={'owned-released-results.tar.gz':('/memory/original.tar.gz',b'synthetic recovery archive'),
        'restoration-manifest.json':('/memory/prepared.json',b'synthetic opaque manifest'),
        'README.md':('/memory/README.md',b'synthetic archive description')}
    local={}
    for name,(path,data) in payloads.items():
        store[path]=data;local[PREFIX+'/'+name]=dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    ns['local']=local
    def identity(data,lfs=False):
        return dict(bytes=len(data),blob_id=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),
            lfs=SimpleNamespace(sha256=hashlib.sha256(data).hexdigest(),size=len(data),pointer_size=130) if lfs else None)
    before={'.gitattributes':identity(b'old attributes'),'old-model.bin':identity(b'old model',True)}
    if mode=='prefix_exists':before[PREFIX+'/existing.bin']=identity(b'existing')
    after=dict(before)
    for remote,item in local.items():after[remote]=identity(store[item['path']],remote.endswith('.tar.gz'))
    if mode=='old_changed':after['.gitattributes']=identity(b'changed attributes')
    if mode=='old_deleted':after.pop('old-model.bin')
    if mode=='unrelated_added':after['foreign-extra.txt']=identity(b'foreign extra')
    archive=PREFIX+'/owned-released-results.tar.gz';card=PREFIX+'/README.md'
    if mode=='lfs_sha_wrong':after[archive]['lfs'].sha256='f'*64
    if mode=='git_blob_wrong':after[card]['blob_id']='f'*40
    if mode=='remote_size_wrong':after[archive]['bytes']+=1
    def info(values,sha):
        return SimpleNamespace(sha=sha,siblings=[SimpleNamespace(rfilename=path,size=value['bytes'],blob_id=value['blob_id'],lfs=value['lfs']) for path,value in values.items()])
    class FakeAPI:
        def model_info(self,repo,**kwargs):
            calls.append(dict(method='model_info',repo=repo,**kwargs));require(repo==REPO and kwargs.get('files_metadata') is True and kwargs.get('timeout')==60,'Exact metadata request required')
            require(kwargs['revision'] in ('main',REVISION),'Only declared immutable revision may be read')
            return info(before,PARENT) if kwargs['revision']=='main' else info(after,'3'*40 if mode=='wrong_after_revision' else REVISION)
        def create_commit(self,repo,**kwargs):
            calls.append(dict(method='create_commit',repo=repo,**{k:v for k,v in kwargs.items() if k!='operations'}))
            require(repo==REPO and kwargs.get('repo_type')=='model' and kwargs.get('revision')=='main'
                and kwargs.get('parent_commit')==PARENT and kwargs.get('num_threads')==1,'Exact parent compare-and-swap request required')
            require(len(kwargs['operations'])==3 and {o['path_in_repo'] for o in kwargs['operations']}==set(local),'Only three additive payload operations permitted')
            require(all(set(o)=={'path_in_repo','path_or_fileobj'} and o['path_or_fileobj']==local[o['path_in_repo']]['path'] for o in kwargs['operations']),'Exact local payload operation identities required')
            if mode=='parent_changed':raise ValueError('Simulated server rejects stale parent commit')
            return SimpleNamespace(oid=REVISION)
    def download(repo,remote,**kwargs):
        calls.append(dict(method='download',repo=repo,remote=remote,**{k:str(v) if k=='local_dir' else v for k,v in kwargs.items()}))
        require(repo==REPO and remote in local and kwargs.get('repo_type')=='model' and kwargs.get('revision')==REVISION
            and str(kwargs.get('local_dir'))=='/memory/readback' and kwargs.get('force_download') is True
            and kwargs.get('endpoint')=='https://huggingface.co','Exact immutable forced readback request required')
        if mode=='download_original_path':return local[remote]['path']
        path='/memory/readback/'+remote;store[path]=b'corrupt bytes' if mode=='download_corrupt' else store[local[remote]['path']]
        return path
    ns.update(api=FakeAPI(),CommitOperationAdd=lambda **kw:kw,hf_hub_download=download)
    error=None
    try:exec(compile(ast.Module(body=kernel,type_ignores=[]),str(SOURCE)+'#actual-kernel-fake-SDK','exec'),ns)
    except (ValueError,KeyError,TypeError) as exc:error=dict(type=type(exc).__name__,message=str(exc))
    return dict(accepted=error is None,error=error,commit_calls=sum(c['method']=='create_commit' for c in calls),
        download_calls=sum(c['method']=='download' for c in calls),calls=calls,writes=writes,state=ns['STATE'],remote_map=ns['remote_map'])


def main():
    require(not OUTPUT.exists(),'Exclusive new detached-control receipt required')
    tests=[]
    def check(name,passed,detail):tests.append(dict(name=name,passed=bool(passed),detail=detail))
    value=scenario()
    check('normal_exact_LFS_Git_three_payload_immutable_readback',value['accepted'] and value['commit_calls']==1 and value['download_calls']==3,'Actual detached kernel accepts exact additive bytes through one fake parent-guarded commit and three immutable readbacks.')
    for mode in ('prefix_exists','local_preupload_drift','parent_changed','old_changed','old_deleted','unrelated_added','lfs_sha_wrong','git_blob_wrong','remote_size_wrong','download_corrupt'):
        value=scenario(mode);check(mode,not value['accepted'],dict(error=value['error'],commit_calls=value['commit_calls'],download_calls=value['download_calls']))
        if mode in ('prefix_exists','local_preupload_drift'):check(mode+'_before_any_commit',value['commit_calls']==0,'Rejected before fake commit.')
        if mode=='parent_changed':check('parent_conflict_has_no_retry',value['commit_calls']==1 and value['download_calls']==0,'One failed fake CAS; no retry or readback.')
    for mode in ('wrong_after_revision','download_original_path'):
        value=scenario(mode);check(mode+'_must_be_rejected',not value['accepted'],dict(actual_kernel_accepted=value['accepted'],commit_calls=value['commit_calls'],download_calls=value['download_calls']))
    remote_map=scenario()['remote_map']
    for mode in ('duplicate_path','boolean_size','empty_listing','bad_blob_id','bad_revision_length'):
        item=SimpleNamespace(rfilename='old',size=1,blob_id='a'*40,lfs=None);info=SimpleNamespace(sha=PARENT,siblings=[item])
        if mode=='duplicate_path':info.siblings.append(item)
        elif mode=='boolean_size':item.size=True
        elif mode=='empty_listing':info.siblings=[]
        elif mode=='bad_blob_id':item.blob_id='short'
        elif mode=='bad_revision_length':info.sha='short'
        refused=False
        try:remote_map(info)
        except ValueError:refused=True
        check(mode,refused,'Actual detached remote_map validation.')
    findings=[t['name'] for t in tests if not t['passed']]
    source=SOURCE.read_bytes();own=DiskPath(__file__).read_bytes()
    result=dict(schema='actor-refinement-owned-results-archive-hf-detached-controls/v1',passed=not findings,findings=findings,
        publisher=SOURCE_PIN,control_source=dict(path=str(DiskPath(__file__).resolve()),bytes=len(own),sha256=hashlib.sha256(own).hexdigest()),
        controls=tests,control_count=len(tests),passed_controls=sum(t['passed'] for t in tests),actual_main_executions=0,
        fake_commit_calls_only=True,real_SDK_imports=0,network_calls=0,uploads=0,payload_files_read=0,checkpoint_JSON_parses=0,
        result_JSON_parses=0,private_body_reads=0,limitations=['Actual filesystem pin implementation and source/prepared gate checks remain full-source reviewer responsibilities.','SDK behavior is simulated; no remote state or durable publication is observed.'])
    require(hashlib.sha256(source).hexdigest()==SOURCE_PIN['sha256'],'Closing publisher source pin drift')
    with OUTPUT.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    OUTPUT.chmod(0o444)
    raw=OUTPUT.read_bytes();print(dict(path=str(OUTPUT),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),passed=result['passed'],findings=findings,controls=len(tests)))


if __name__=='__main__':main()
