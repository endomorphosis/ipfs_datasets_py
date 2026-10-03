"""Small authored bytes only; no weights, inference, or memory-reclamation claim."""
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
from ipfs_datasets_py.logic.software_contracts import codebase_source_units_384 as owner

@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    root=tmp_path/'models--thenlper--gte-small'/'snapshots'/runtime.PINNED_REVISION
    pins={}
    for name in runtime._PINNED_ASSETS:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        body=('authored diagnostic: '+name).encode();path.write_bytes(body)
        pins[name]=(len(body),hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(runtime,'_PINNED_ASSETS',pins)
    return root

class Tracked:
    def __init__(self, handle, events, name, transform=None):
        self.handle,self.events,self.name,self.transform=handle,events,name,transform
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):self.handle.close();self.events.append(('close',self.name))
    def fileno(self):return self.handle.fileno()
    def read(self,n):
        value=self.handle.read(n)
        self.events.append(('read',self.name,len(value)))
        return self.transform(value) if self.transform else value


def track(monkeypatch,snapshot,*,transform=None):
    events=[];handles=[];native=Path.open
    def opened(path,*args,**kwargs):
        handle=native(path,*args,**kwargs)
        if path.is_relative_to(snapshot) and args and args[0]=='rb':
            wrapper=Tracked(handle,events,path.name,transform if path.name=='vocab.txt' else None)
            handles.append(wrapper);return wrapper
        return handle
    monkeypatch.setattr(Path,'open',opened)
    return events,handles


def test_default_and_false_never_advise_and_return_same_bytes(snapshot,monkeypatch):
    monkeypatch.setattr(os,'posix_fadvise',lambda *a:pytest.fail('default advised'),raising=False)
    first=runtime._snapshot_assets(snapshot)
    assert runtime._snapshot_assets(snapshot,release_verified_pages=False)==first
    assert len(first[1])==9


def test_all_verified_then_same_held_fds_advised_no_reads_after(snapshot,monkeypatch):
    expected=runtime._snapshot_assets(snapshot)
    events,handles=track(monkeypatch,snapshot)
    def advise(fd,offset,length,policy):
        assert len(handles)==9 and all(not h.handle.closed for h in handles)
        assert all(h.handle.tell()==os.fstat(h.fileno()).st_size for h in handles)
        assert fd in [h.fileno() for h in handles]
        assert (offset,length,policy)==(0,0,os.POSIX_FADV_DONTNEED)
        events.append(('advise',fd))
    monkeypatch.setattr(os,'posix_fadvise',advise)
    assert runtime._snapshot_assets(snapshot,release_verified_pages=True)==expected
    first=next(i for i,e in enumerate(events) if e[0]=='advise')
    assert not any(e[0]=='read' for e in events[first:])
    assert len([e for e in events if e[0]=='advise'])==9
    assert all(h.handle.closed for h in handles)


@pytest.mark.parametrize('bad',[None,0,1,'true',[],{}])
def test_policy_strict_boolean_before_asset_io(bad,monkeypatch):
    monkeypatch.setattr(Path,'is_dir',lambda *a:pytest.fail('asset IO'))
    with pytest.raises(runtime.EmbeddingRuntimeError,match='boolean'):
        runtime._snapshot_assets('/absent',release_verified_pages=bad)


@pytest.mark.parametrize('damage',['digest','short','grown','size','unknown'])
def test_bad_last_asset_or_inventory_never_advises(snapshot,monkeypatch,damage):
    if damage=='digest':
        path=snapshot/'vocab.txt';path.write_bytes(b'x'*path.stat().st_size)
    elif damage=='size':(snapshot/'vocab.txt').write_bytes(b'bad size')
    elif damage=='unknown':(snapshot/'extra.json').write_text('{}')
    transform=(lambda block:block[:-1]) if damage=='short' else ((lambda block:block+b'x' if block else block) if damage=='grown' else None)
    events,handles=track(monkeypatch,snapshot,transform=transform)
    monkeypatch.setattr(os,'posix_fadvise',lambda *a:pytest.fail('invalid snapshot advised'))
    with pytest.raises(runtime.EmbeddingRuntimeError):runtime._snapshot_assets(snapshot,release_verified_pages=True)
    assert all(h.handle.closed for h in handles)


def test_prior_asset_changed_during_last_read_refuses_before_advice(snapshot,monkeypatch):
    changed=False
    def mutate(block):
        nonlocal changed
        if block and not changed:
            changed=True;path=snapshot/'config.json';path.write_bytes(b'x'*path.stat().st_size)
        return block
    _,handles=track(monkeypatch,snapshot,transform=mutate)
    monkeypatch.setattr(os,'posix_fadvise',lambda *a:pytest.fail('changed snapshot advised'))
    with pytest.raises(runtime.EmbeddingRuntimeError,match='after verification'):
        runtime._snapshot_assets(snapshot,release_verified_pages=True)
    assert all(h.handle.closed for h in handles)


@pytest.mark.parametrize('mode',['missing_call','missing_constant','oserror','not_implemented'])
def test_unavailable_advice_preserves_verified_manifest(snapshot,monkeypatch,mode):
    expected=runtime._snapshot_assets(snapshot)
    _,handles=track(monkeypatch,snapshot)
    if mode=='missing_call':monkeypatch.delattr(os,'posix_fadvise')
    elif mode=='missing_constant':monkeypatch.delattr(os,'POSIX_FADV_DONTNEED')
    else:
        def unsupported(*a):raise OSError('unsupported') if mode=='oserror' else NotImplementedError('unsupported')
        monkeypatch.setattr(os,'posix_fadvise',unsupported)
    assert runtime._snapshot_assets(snapshot,release_verified_pages=True)==expected
    assert all(h.handle.closed for h in handles)


def test_advice_alarm_propagates_identity_stops_and_closes(snapshot,monkeypatch):
    alarm=TimeoutError('native deadline');calls=[];_,handles=track(monkeypatch,snapshot)
    def expired(*args):calls.append(args);raise alarm
    monkeypatch.setattr(os,'posix_fadvise',expired)
    with pytest.raises(TimeoutError) as caught:runtime._snapshot_assets(snapshot,release_verified_pages=True)
    assert caught.value is alarm and len(calls)==1
    assert all(h.handle.closed for h in handles)


def test_read_alarm_propagates_without_advice(snapshot,monkeypatch):
    alarm=TimeoutError('read deadline')
    def expired(block):raise alarm
    _,handles=track(monkeypatch,snapshot,transform=expired)
    monkeypatch.setattr(os,'posix_fadvise',lambda *a:pytest.fail('read failed'))
    with pytest.raises(TimeoutError) as caught:runtime._snapshot_assets(snapshot,release_verified_pages=True)
    assert caught.value is alarm and all(h.handle.closed for h in handles)


def test_inside_cache_links_keep_same_fd_and_external_link_refuses(snapshot,tmp_path,monkeypatch):
    path=snapshot/'model.safetensors';body=path.read_bytes();blob=snapshot.parent.parent/'blobs'/'fixture'
    blob.parent.mkdir();blob.write_bytes(body);path.unlink();path.symlink_to(blob)
    calls=[];monkeypatch.setattr(os,'posix_fadvise',lambda *args:calls.append(args))
    runtime._snapshot_assets(snapshot,release_verified_pages=True);assert len(calls)==9
    external=tmp_path/'outside';external.write_bytes(body);path.unlink();path.symlink_to(external);calls.clear()
    with pytest.raises(runtime.EmbeddingRuntimeError,match='inside the pinned'):
        runtime._snapshot_assets(snapshot,release_verified_pages=True)
    assert calls==[]


def test_source_context_requests_policy_and_binds_key_without_model(snapshot,monkeypatch):
    seen=[];original=runtime._snapshot_assets
    def verify(path,**kwargs):seen.append(kwargs);return original(path,**kwargs)
    monkeypatch.setattr(runtime,'_snapshot_assets',verify)
    monkeypatch.setattr(os,'posix_fadvise',lambda *a:None)
    monkeypatch.setattr(owner,'prepare_source_units',lambda *a,**k:{'preparation':'fixture'})
    monkeypatch.setattr(owner.shared,'_lineage',lambda *a:[({'artifact':{'sha256':'fixture'}},{'kind':'shared_parent','original_checkpoint_sha256':'original'})])
    monkeypatch.setattr(owner.shared,'_root_view',lambda *a:{'checkpoint':'fixture'})
    monkeypatch.setattr(owner,'pins',lambda:{'producer':'fixture'})
    monkeypatch.setattr(owner,'package_version',lambda name:'fixture')
    kwargs=dict(expected_head=SimpleNamespace(to_dict=lambda:{'head':'fixture'}),version_id='v',paths=['a.py'],embedding_snapshot=snapshot,max_functions=1,max_selected_units=1)
    key,_,_=owner._context(None,None,**kwargs)
    assert seen==[{'release_verified_pages':True}]
    assert key['embedding_cache_policy']=='verified_snapshot_dontneed_best_effort@1'
    assert key['embedding_assets']==original(snapshot)[1]
    changed=dict(key);changed.pop('embedding_cache_policy')
    assert owner.sha(owner.raw(changed))!=owner.sha(owner.raw(key))


def test_source_producer_explicitly_pins_embedding_verifier():
    assert owner.pins()['embedding_verifier']==hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()
