"""Owner protocol controls; synthetic vectors are never native evidence.

These tests do not open pretrained weights, execute an encoder, or write a
cgroup. The only real subprocesses are tiny Python pipe/cleanup controls.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_4096_full_owner as m


def fixture():
    source = {"id": "training-one", "source_text": "The agency shall retain records."}
    context = {"nonce": "a" * 64, "request_sha256": "b" * 64, "worker_source_sha256": "c" * 64,
        "process": {"pid": 123, "ppid": 122, "thread_id": 123, "birth_ticks": "456", "executable": "/worker"},
        "model_identity": {"device": 1, "inode": 2, "bytes": 3, "mtime_seconds": 4,
            "mtime_nanoseconds": 5, "ctime_seconds": 6, "ctime_nanoseconds": 7}}
    common = dict(context, admitted=False, qualified=False, proof_authority=False, source_semantics_verified=False)
    profile = {"schema": "native-source4096-worker-description/v2", "modes": ["embed-authorized"],
        "profile": m.PROFILE, "dimension": 4096, "context_limit": 512, "batch_limit": 512,
        "ubatch_limit": 512, "sequence_count": 1, "threads": 1, "requested_gpu_layers": 0,
        "add_special": True, "parse_special": False, "request_source_only": True,
        "model_content_hash_verified_by_worker": False, "full_forward_executed": False,
        "model_loader_prefetch": False, "mmap_populate": False, "cpu_extra_buffers": False,
        "authorization_required": True, "closing_ack_required": True}
    geometry = {"native_input_dimension": 4096, "native_output_dimension": 4096,
        "metadata_architecture": "deepseek2", "metadata_embedding_length": 4096,
        "metadata_embedding_length_out": None, "metadata_embedding_length_key": "deepseek2.embedding_length",
        "metadata_embedding_length_out_key": "deepseek2.embedding_length_out", "vocabulary_size": 131072,
        "actual_context": 512, "actual_batch": 512, "actual_ubatch": 512, "actual_sequences": 1,
        "actual_pooling": "last", "context_created": True}
    entry = dict(common, schema="native-source4096-worker-entry/v2", mode="embed-authorized", model_fd=9,
        requested_profile=profile, source_rows=1, model_content_hash_verified_by_worker=False,
        model_loaded=False, authorization_required=True)
    row = dict(common, schema="native-source4096-worker-row/v2", index=0, id=source["id"],
        source_sha256=hashlib.sha256(source["source_text"].encode()).hexdigest(), token_ids=[1, 2, 3], token_count=3,
        add_special=True, parse_special=False, truncated=False, chat_template_applied=False, geometry=geometry,
        full_forward_executed=True, embedding=[1.] + [0.] * 4095, normalization="l2", raw_output_l2_norm=2.,
        KV_reset_before_row=True, synchronized_before_read=True, native_prompt_tokens_evaluated=3,
        native_single_tokens_evaluated=0, native_tokens_evaluated=3, actual_buffer_devices=["CPU"],
        post_compute_nodes_observed=10, nodes_without_observable_buffer=0,
        device_observation_scope="post-compute tensor buffers; CPU-only registered backend and offload disabled",
        owner_authorization_sha256="d" * 64)
    closing = dict(common, schema="native-source4096-worker-closing/v2", mode="embed-authorized", complete=True,
        rows_emitted=1, native_tokens_evaluated=3, geometry=geometry, model_and_context_freed=True,
        inherited_fd_still_parent_owned=True, full_forward_executed=True,
        model_content_hash_verified_by_worker=False, owner_authorization_sha256="d" * 64, closing_ack_required=True)
    final = dict(common, schema="native-source4096-worker-exit/v1", mode="embed-authorized", complete=True,
        owner_authorization_sha256="d" * 64, owner_closing_ack_sha256="e" * 64, model_and_context_freed=True)
    return tuple(copy.deepcopy(value) for value in (source, context, entry, row, closing, final))


def test_complete_synthetic_protocol_does_not_issue_capability():
    source, context, entry, row, closing, final = fixture()
    m._entry(entry, context, 1, 9)
    observed = m._forward_row(row, source, 0, context, "d" * 64)
    m._closing(closing, context, [observed], "d" * 64)
    m._exit(final, context, "d" * 64, "e" * 64)
    assert observed["source_text"] == source["source_text"] and len(observed["embedding"]) == 4096
    with pytest.raises(ValueError, match="live_verified"):
        m.require_live_result({"complete": True, "rows": [observed]})


@pytest.mark.parametrize("field,value", [
    ("mode", "embed"), ("schema", "native-source4096-worker-entry/v1"),
    ("model_loaded", True), ("authorization_required", False), ("model_fd", True),
    ("model_fd", 10), ("source_rows", True), ("source_rows", 2),
    ("model_content_hash_verified_by_worker", True), ("extra", 1),
    ("qualified", True), ("admitted", True), ("proof_authority", True),
])
def test_entry_refuses_early_load_or_changed_binding(field, value):
    _, context, entry, *_ = fixture(); entry[field] = value
    with pytest.raises(ValueError): m._entry(entry, context, 1, 9)


@pytest.mark.parametrize("field,value", [
    ("model_loader_prefetch", True), ("mmap_populate", True), ("cpu_extra_buffers", True),
    ("context_limit", 1024), ("threads", 2), ("requested_gpu_layers", 1), ("sequence_count", 2),
    ("profile", "other"), ("parse_special", True), ("authorization_required", False), ("closing_ack_required", False),
])
def test_unsafe_private_profile_refuses(field, value):
    _, context, entry, *_ = fixture(); entry["requested_profile"][field] = value
    with pytest.raises(ValueError): m._entry(entry, context, 1, 9)


@pytest.mark.parametrize("field,value", [
    ("id", "other"), ("index", True), ("source_sha256", "0"*64),
    ("nonce", "0"*64), ("request_sha256", "0"*64), ("worker_source_sha256", "0"*64),
    ("owner_authorization_sha256", "0"*64), ("parse_special", True), ("add_special", False),
    ("token_count", True), ("token_count", 4), ("token_ids", [True]), ("token_ids", [-1]),
    ("token_ids", [131072]), ("token_ids", [1]*513), ("truncated", True), ("chat_template_applied", True),
    ("full_forward_executed", False), ("KV_reset_before_row", False), ("synchronized_before_read", False),
    ("native_prompt_tokens_evaluated", 2), ("native_single_tokens_evaluated", True),
    ("native_tokens_evaluated", 2), ("post_compute_nodes_observed", 0), ("nodes_without_observable_buffer", 10),
    ("actual_buffer_devices", ["CUDA0"]), ("actual_buffer_devices", ["CPU", "CUDA0"]),
    ("actual_buffer_devices", []), ("normalization", "none"), ("raw_output_l2_norm", 0),
    ("raw_output_l2_norm", float("nan")), ("embedding", [1.]*384),
    ("embedding", [0.]*4096), ("embedding", [float("nan")]*4096), ("embedding", [True]*4096),
    ("qualified", True), ("source_semantics_verified", True), ("extra", 1),
])
def test_forward_rejects_fabricated_dimensions_sources_or_execution(field, value):
    source, context, _, row, *_ = fixture(); row[field] = value
    with pytest.raises(ValueError): m._forward_row(row, source, 0, context, "d"*64)


@pytest.mark.parametrize("field,value", [("native_input_dimension", 768), ("native_output_dimension", 768),
    ("actual_context", 1024), ("actual_ubatch", 16), ("actual_sequences", 2), ("actual_pooling", "mean"),
    ("context_created", False), ("vocabulary_size", True), ("metadata_embedding_length_out", True),
    ("metadata_architecture", "../bad"), ("metadata_embedding_length_key", "other.embedding_length")])
def test_runtime_geometry_must_be_actual_fixed_profile(field, value):
    source, context, _, row, *_ = fixture(); row["geometry"][field] = value
    with pytest.raises(ValueError): m._forward_row(row, source, 0, context, "d"*64)


@pytest.mark.parametrize("field,value", [("pid",124),("ppid",121),("thread_id",124),
    ("birth_ticks","457"),("executable","/another")])
def test_native_process_thread_fence(field, value):
    source, context, _, row, *_ = fixture(); row["process"][field] = value
    with pytest.raises(ValueError): m._forward_row(row, source, 0, context, "d"*64)


@pytest.mark.parametrize("field,value", [("complete",False),("rows_emitted",True),("rows_emitted",0),
    ("native_tokens_evaluated",0),("model_and_context_freed",False),("inherited_fd_still_parent_owned",False),
    ("full_forward_executed",False),("closing_ack_required",False),("model_content_hash_verified_by_worker",True),
    ("owner_authorization_sha256","0"*64)])
def test_closing_requires_cleanup_and_all_actual_rows(field, value):
    source, context, _, row, closing, _ = fixture()
    observed=m._forward_row(row,source,0,context,"d"*64);closing[field]=value
    with pytest.raises(ValueError):m._closing(closing,context,[observed],"d"*64)


@pytest.mark.parametrize("field,value", [("complete",False),("model_and_context_freed",False),
    ("owner_closing_ack_sha256","0"*64),("owner_authorization_sha256","0"*64),("qualified",True)])
def test_exit_must_ack_owner_verification(field, value):
    _,context,*_,final=fixture();final[field]=value
    with pytest.raises(ValueError):m._exit(final,context,"d"*64,"e"*64)


def test_held_fd_hash_covers_complete_file_and_preserves_offset(tmp_path):
    path=tmp_path/'tiny-not-a-model';raw=b'a'*(8*1024*1024+13);path.write_bytes(raw)
    fd,identity=m._open_regular(path)
    try:
        os.lseek(fd,7,os.SEEK_SET)
        digest,after=m._sha_fd(fd,time.monotonic()+10)
        assert digest==hashlib.sha256(raw).hexdigest() and after==identity
        assert os.lseek(fd,0,os.SEEK_CUR)==7
    finally:os.close(fd)


def test_hash_deadline_and_inode_replacement_refuse(tmp_path):
    path=tmp_path/'tiny';path.write_bytes(b'123');fd,identity=m._open_regular(path)
    try:
        with pytest.raises(TimeoutError):m._sha_fd(fd,time.monotonic()-1)
        path.unlink();path.write_bytes(b'123')
        with pytest.raises(ValueError):m._check_leaf(path,fd,identity)
    finally:os.close(fd)


def test_hash_inplace_change_refuses(tmp_path,monkeypatch):
    path=tmp_path/'tiny';path.write_bytes(b'123');fd,_=m._open_regular(path);read=os.pread
    def changed(*args):
        result=read(*args);path.write_bytes(b'4567');return result
    monkeypatch.setattr(os,'pread',changed)
    try:
        with pytest.raises(ValueError,match='changed_while_hashing'):m._sha_fd(fd,time.monotonic()+1)
    finally:os.close(fd)


def test_leaf_symlink_refused(tmp_path):
    target=tmp_path/'file';target.write_bytes(b'x');link=tmp_path/'link';link.symlink_to(target)
    with pytest.raises(ValueError):m._open_regular(link)


def test_actual_mapping_inode_and_full_digest_are_both_required(tmp_path,monkeypatch):
    worker=tmp_path/'worker';worker.write_bytes(b'worker')
    lib=tmp_path/'lib.so';lib.write_bytes(b'library');fd,identity=m._open_regular(lib)
    wi=m.vocab._identity(worker.stat());observed={str(worker):{k:wi[k] for k in ('device','inode')},
        str(lib):{k:identity[k] for k in ('device','inode')}}
    monkeypatch.setattr(m,'_map_entries',lambda pid:observed)
    try:
        pins={str(lib):(fd,identity,hashlib.sha256(b'library').hexdigest())}
        assert set(m._observe_maps(1,worker,wi,pins,time.monotonic()+1))==set(observed)
        observed[str(lib)]['inode']+=1
        with pytest.raises(ValueError,match='inode'):m._observe_maps(1,worker,wi,pins,time.monotonic()+1)
        observed[str(lib)]['inode']-=1;pins[str(lib)]=(fd,identity,'0'*64)
        with pytest.raises(ValueError,match='content'):m._observe_maps(1,worker,wi,pins,time.monotonic()+1)
    finally:os.close(fd)


def test_unlisted_executable_mapping_refuses(tmp_path,monkeypatch):
    worker=tmp_path/'worker';worker.write_bytes(b'x');wi=m.vocab._identity(worker.stat())
    monkeypatch.setattr(m,'_map_entries',lambda pid:{str(worker):{},'/unexpected.so':{}})
    with pytest.raises(ValueError,match='unexpected_or_missing'):m._observe_maps(1,worker,wi,{},time.monotonic()+1)


def fake_controls(monkeypatch):
    path=Path('/sys/fs/cgroup/user.slice/owned.scope');stat_method=Path.stat;resolve=Path.resolve
    monkeypatch.setattr(Path,'stat',lambda self,*a,**kw:SimpleNamespace(st_uid=os.getuid(), st_mode=0o040755) if self==path else stat_method(self,*a,**kw))
    monkeypatch.setattr(Path,'resolve',lambda self,*a,**kw:self if self==path else resolve(self,*a,**kw))
    values={'memory.max':'1048576','memory.swap.max':'0','memory.oom.group':'1','pids.max':'8','cgroup.type':'domain',
        'cgroup.procs':'123\n124','/proc/123/cgroup':'0::/user.slice/owned.scope','/proc/124/cgroup':'0::/user.slice/owned.scope'}
    monkeypatch.setattr(m,'_read_small',lambda p:values[str(p)] if str(p).startswith('/proc/') else values[Path(p).name])
    return path,values


def test_real_controls_and_exact_owner_child_membership(monkeypatch):
    path,values=fake_controls(monkeypatch);controls=m._cgroup_controls(path,1048576)
    m._check_cgroup(path,{'pid':124},controls,{'pid':123})
    values['cgroup.procs']='123';m._check_cgroup(path,None,controls,{'pid':123})
    values['cgroup.procs']='123\n999'
    with pytest.raises(ValueError,match='foreign'):m._check_cgroup(path,None,controls,{'pid':123})


@pytest.mark.parametrize('field,value',[('memory.max','max'),('memory.max','2097152'),('memory.swap.max','1'),
    ('memory.oom.group','0'),('pids.max','max'),('pids.max','1000'),('cgroup.type','threaded')])
def test_kernel_limits_are_not_caller_attestations(monkeypatch,field,value):
    path,values=fake_controls(monkeypatch);values[field]=value
    with pytest.raises(ValueError):m._cgroup_controls(path,1048576)


def test_caller_json_constructed_or_unissued_handle_refuses():
    for value in ({'complete':True,'model_content_hash_verified':True},object(),object.__new__(m.VerifiedForwardResult)):
        with pytest.raises(ValueError):m.require_live_result(value)
    with pytest.raises(ValueError):m.VerifiedForwardResult()


def test_live_result_defensive_thread_bound_and_not_pickleable(monkeypatch):
    result=m.VerifiedForwardResult(m._TOKEN)
    receipt={'rows':[{'id':'x','embedding':[1.]}],'profile':m.PROFILE,'model_sha256':'a'*64,'worker_sha256':'b'*64,
        'worker_source_sha256':'c'*64,'owner_source_sha256':'d'*64,'operation_nonce':'e'*64,
        'request_sha256':'f'*64,'full_forward_executed':True,'dimension':4096,'sample_count':1}
    owner={'pid':os.getpid(),'thread_id':threading.get_native_id()}
    m._ISSUED[result]={'owner':owner,'owner_source_sha256':m.vocab._sha_file(m.__file__),
        'serialized':m._wire(receipt),'receipt_sha256':'9'*64}
    first=m.require_live_result(result);first['rows'][0]['embedding'][0]=9.
    assert m.require_live_result(result)['rows'][0]['embedding']==[1.]
    with pytest.raises(TypeError):pickle.dumps(result)
    monkeypatch.setattr(threading,'get_native_id',lambda:owner['thread_id']+1)
    with pytest.raises(ValueError,match='owner_changed'):m.require_live_result(result)


def test_control_hash_is_exact_atomic_line():
    reader,writer=os.pipe();message={'schema':'control','nonce':'a'*64}
    try:
        digest=m._send_control(writer,message,time.monotonic()+1);raw=os.read(reader,4096)
        assert raw==m._wire(message)+b'\n' and digest==hashlib.sha256(raw).hexdigest()
    finally:os.close(reader);os.close(writer)


def test_combined_rss_cap_includes_owner_not_only_native(monkeypatch):
    parent={'pid':1,'state':'R','rss_bytes':600}
    child={'pid':2,'state':'S','rss_bytes':500,'birth':'3'}
    monkeypatch.setattr(m.vocab,'_process',lambda pid:parent if pid==1 else child)
    with pytest.raises(ValueError,match='combined_owner_native_rss_limit') as raised:
        m._rss_sample({'pid':2,'birth':'3'},{'pid':1},1000)
    assert raised.value.observation=={'owner_rss_bytes':600,'native_child_rss_bytes':500,'combined_rss_bytes':1100}
    sample,current=m._rss_sample({'pid':2,'birth':'3'},{'pid':1},1100)
    assert sample=={'owner_rss_bytes':600,'native_child_rss_bytes':500,'combined_rss_bytes':1100}
    assert current is child
    child['birth']='4'
    with pytest.raises(ValueError,match='pid_reused'):
        m._rss_sample({'pid':2,'birth':'3'},{'pid':1},1100)


def test_rss_scope_after_native_exit_retains_owner(monkeypatch):
    monkeypatch.setattr(m.vocab,'_process',lambda pid:{'state':'R','rss_bytes':600} if pid==1 else None)
    sample,current=m._rss_sample({'pid':2,'birth':'3'},{'pid':1},1000)
    assert current is None and sample['combined_rss_bytes']==600 and sample['native_child_rss_bytes']==0


def test_duplex_exchange_preserves_lines_logs_and_does_not_run_models():
    child=subprocess.Popen([sys.executable,'-c',"import sys; sys.stdin.buffer.read(); print('{\"a\":1}'); print('{\"a\":2}'); sys.stderr.write('control only')"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    outputs={'stdout':bytearray(),'stderr':bytearray()};observed=[]
    try:
        code,streams=m._exchange(child,b'request',time.monotonic()+5,lambda value,raw:observed.append(value),lambda:None,outputs)
        assert code==0 and observed==[{'a':1},{'a':2}] and streams['stderr']==b'control only'
    finally:
        if child.poll() is None:child.kill();child.wait()
        for stream in (child.stdin,child.stdout,child.stderr):
            if not stream.closed:stream.close()


def test_timeout_retains_partial_stdout_and_reaps_only_owned_child():
    child=subprocess.Popen([sys.executable,'-c',"import time; print('{\"entry\":true}',flush=True); time.sleep(20)"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    identity=m.vocab._process(child.pid);outputs={'stdout':bytearray(),'stderr':bytearray()}
    try:
        with pytest.raises(TimeoutError):m._exchange(child,b'{}',time.monotonic()+.15,lambda value,raw:None,lambda:None,outputs)
        assert b'entry' in outputs['stdout']
        assert m.vocab._cleanup(child,identity)['leader_reaped']
        assert child.poll() is not None
    finally:
        if child.poll() is None:child.kill();child.wait()
        for stream in (child.stdin,child.stdout,child.stderr):
            if not stream.closed:stream.close()


def test_no_live_handle_after_failed_model_content_pin(tmp_path,monkeypatch):
    worker=tmp_path/'worker';worker.write_bytes(b'worker')
    source=tmp_path/'source';source.write_bytes(b'source')
    model=tmp_path/'not-model';model.write_bytes(b'tiny-not-pretrained')
    library=tmp_path/'library';library.write_bytes(b'library')
    monkeypatch.setattr(m,'_cgroup_controls',lambda *a:{})
    monkeypatch.setattr(m,'_check_cgroup',lambda *a:None)
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:pytest.fail('must not launch after wrong full hash'))
    output=tmp_path/'out'
    with pytest.raises(ValueError,match='full_model_content_pin_changed'):
        m.run_full_forward([{'id':'x','source_text':'source only'}],worker_path=worker,
            worker_sha256=hashlib.sha256(b'worker').hexdigest(),worker_source_path=source,
            worker_source_sha256=hashlib.sha256(b'source').hexdigest(),model_path=model,expected_model_sha256='0'*64,
            expected_library_sha256={str(library):hashlib.sha256(b'library').hexdigest()},resource_cgroup='/synthetic',
            output_directory=output,deadline_seconds=10,max_rss_bytes=1048576)
    receipt=json.loads((output/'failure.json').read_text())
    assert receipt['complete'] is False and receipt['operation_verified'] is False
    assert receipt['model_content_hash_verified'] is False and not (output/'receipt.json').exists()


def mock_owned_operation(tmp_path, monkeypatch, *, failure=None, reclaim=False):
    """Synthetic lifecycle only: replace the kernel/worker boundary explicitly."""
    worker=tmp_path/'worker';worker.write_bytes(b'worker')
    source=tmp_path/'source';source.write_bytes(b'source')
    model=tmp_path/'tiny-not-pretrained';model.write_bytes(b'tiny-control')
    library=tmp_path/'library';library.write_bytes(b'library')
    owner={'pid':os.getpid(),'thread_id':threading.get_native_id()}
    identity={'pid':123456,'parent_pid':owner['pid'],'group_pid':123456,'birth':'789','state':'S','rss_bytes':4096}
    cleanup_calls=[];controls={'path':'/synthetic','memory_max_bytes':1048576,'memory_swap_max_bytes':0,
        'memory_oom_group':1,'pids_max':8,'type':'domain'}
    monkeypatch.setattr(m,'_cgroup_controls',lambda *a:dict(controls))
    monkeypatch.setattr(m,'_check_cgroup',lambda *a:None)
    monkeypatch.setattr(m,'_join_cgroup',lambda *a:{**controls,'events_before':{'oom':0,'oom_kill':0}})
    monkeypatch.setattr(m,'_events',lambda *a:{'oom':0,'oom_kill':0})
    monkeypatch.setattr(m,'_proc_identity',lambda *a:dict(identity))
    monkeypatch.setattr(m.vocab,'_process',lambda *a:dict(identity))
    monkeypatch.setattr(m,'_observe_maps',lambda *a:{'synthetic-only':{'sha256':'1'*64}})
    def cleanup(child, identity):
        cleanup_calls.append(1);os.close(child.control_read)
        return {'leader_reaped':True,'returncode':0,'live_group_processes':0}
    monkeypatch.setattr(m.vocab,'_cleanup',cleanup)
    real_open=os.open
    monkeypatch.setattr(os,'open',lambda path,*a,**kw:real_open(worker if str(path)=='/proc/123456/exe' else path,*a,**kw))
    instances=[]
    class Child:
        def __init__(self,command,**kw):
            self.pid=identity['pid'];self.command=command;self.stdin=io.BytesIO();self.stdout=io.BytesIO();self.stderr=io.BytesIO()
            self.control_read=os.dup(int(command[command.index('--control-fd')+1]))
            instances.append(self)
    monkeypatch.setattr(subprocess,'Popen',Child)
    def exchange(child,request,deadline,on_line,sample,outputs):
        decoded=m._decode(request);src,ctx,entry,row,closing,final=fixture()
        src=decoded['rows'][0];fd=int(child.command[child.command.index('--model-fd')+1]);info=m.vocab._identity(os.fstat(fd))
        native={key:info[key] for key in ('device','inode','bytes')}
        for key in ('mtime','ctime'):native[key+'_seconds'],native[key+'_nanoseconds']=divmod(info[key+'_ns'],10**9)
        shared={'nonce':decoded['nonce'],'request_sha256':hashlib.sha256(request).hexdigest(),
            'worker_source_sha256':hashlib.sha256(b'source').hexdigest(),'model_identity':native,
            'process':{'pid':identity['pid'],'ppid':owner['pid'],'thread_id':identity['pid'],
                'birth_ticks':identity['birth'],'executable':str(worker)}}
        for record in (entry,row,closing,final):record.update(copy.deepcopy(shared))
        entry['model_fd']=fd;row.update(id=src['id'],source_sha256=hashlib.sha256(src['source_text'].encode()).hexdigest())
        if reclaim:make_v3(entry,row,{'model_identity':native})
        def send(record):
            raw=m._wire(record)+b'\n';outputs['stdout'].extend(raw);on_line(record,raw);return raw
        def send_failure(entry_emitted,rows,tokens):
            send(worker_error_fixture(decoded['nonce'],hashlib.sha256(b'source').hexdigest(),
                entry_emitted=entry_emitted,rows=rows,tokens=tokens))
        if failure=='native_error_before_entry':send_failure(False,0,0)
        if failure=='model_mutation':model.write_bytes(b'mutated-control')
        raw=send(entry)
        auth={'schema':'native-source4096-owner-authorization/v1','nonce':decoded['nonce'],
            'request_sha256':shared['request_sha256'],'entry_sha256':hashlib.sha256(raw).hexdigest(),
            'model_sha256':hashlib.sha256(b'tiny-control').hexdigest()}
        auth_sha=hashlib.sha256(m._wire(auth)+b'\n').hexdigest()
        for record in (row,closing,final):record['owner_authorization_sha256']=auth_sha
        if failure=='native_error_after_entry':send_failure(True,0,0)
        if failure=='timeout_after_authorization':raise TimeoutError('synthetic operation timeout')
        if failure=='bad_row':row['KV_reset_before_row']=False
        send(row)
        if failure=='native_error_after_row':send_failure(True,1,3)
        if failure=='missing_closing':return 0,{k:bytes(v) for k,v in outputs.items()}
        raw=send(closing)
        ack={'schema':'native-source4096-owner-close-ack/v1','nonce':decoded['nonce'],
            'request_sha256':shared['request_sha256'],'closing_sha256':hashlib.sha256(raw).hexdigest()}
        final['owner_closing_ack_sha256']=hashlib.sha256(m._wire(ack)+b'\n').hexdigest()
        if failure=='bad_ack':final['owner_closing_ack_sha256']='0'*64
        if failure!='missing_exit':send(final)
        if failure=='extra_exit':send(final)
        return (2 if failure=='nonzero_exit' else 0),{k:bytes(v) for k,v in outputs.items()}
    monkeypatch.setattr(m,'_exchange',exchange)
    kwargs=dict(worker_path=worker,worker_sha256=hashlib.sha256(b'worker').hexdigest(),worker_source_path=source,
        worker_source_sha256=hashlib.sha256(b'source').hexdigest(),model_path=model,
        expected_model_sha256=hashlib.sha256(b'tiny-control').hexdigest(),
        expected_library_sha256={str(library):hashlib.sha256(b'library').hexdigest()},resource_cgroup='/synthetic',
        output_directory=tmp_path/'out',deadline_seconds=10,max_rss_bytes=1048576)
    return kwargs,cleanup_calls,instances


def test_synthetic_complete_owner_issues_only_after_ack_and_cleanup(tmp_path,monkeypatch):
    kwargs,cleanup,children=mock_owned_operation(tmp_path,monkeypatch)
    result=m.run_full_forward([{'id':'x','source_text':'source only'}],**kwargs)
    value=m.require_live_result(result);receipt=value['receipt']
    assert cleanup==[1] and all(stream.closed for stream in (children[0].stdin,children[0].stdout,children[0].stderr))
    assert value['rows'][0]['source_text']=='source only' and value['rows'][0]['embedding']==[1.]+[0.]*4095
    assert receipt['protocol']['exit_observed'] and receipt['model_content_hash_verified']
    assert receipt['native_tokens_evaluated']==3 and receipt['resource_cgroup']['only_owner_after_exit']
    assert not receipt['admitted'] and not receipt['qualified'] and not receipt['training_executed']
    assert value['provenance']['receipt_sha256']==hashlib.sha256((tmp_path/'out/receipt.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('failure',['model_mutation','timeout_after_authorization','bad_row','missing_closing',
    'bad_ack','missing_exit','extra_exit','nonzero_exit'])
def test_synthetic_failed_operation_cleans_up_and_never_issues(tmp_path,monkeypatch,failure):
    kwargs,cleanup,children=mock_owned_operation(tmp_path,monkeypatch,failure=failure)
    prior=len(m._ISSUED)
    with pytest.raises((ValueError,TimeoutError)):
        m.run_full_forward([{'id':'x','source_text':'source only'}],**kwargs)
    assert len(m._ISSUED)==prior and cleanup==[1]
    assert all(stream.closed for stream in (children[0].stdin,children[0].stdout,children[0].stderr))
    receipt=json.loads((tmp_path/'out/failure.json').read_text())
    assert not receipt['complete'] and not receipt['operation_verified'] and not (tmp_path/'out/receipt.json').exists()
    assert (tmp_path/'out/stdout.log').stat().st_size>0


def test_failure_resource_snapshot_reads_kernel_values_without_mutating(monkeypatch):
    controls={'path':'/synthetic','memory_max_bytes':1000,'memory_swap_max_bytes':0,
              'memory_oom_group':1,'pids_max':8,'type':'domain'}
    values={'memory.current':'800','memory.peak':'950','memory.stat':'anon 500\nfile 300',
            'memory.events':'low 0\nhigh 0\nmax 4\noom 0\noom_kill 0','cgroup.procs':'1\n2'}
    monkeypatch.setattr(m,'_cgroup_controls',lambda *a:dict(controls))
    monkeypatch.setattr(m,'_read_small',lambda p:values[p.name])
    snapshot=m._failure_resource_snapshot('/synthetic',controls,{'pid':1},{'pid':2})
    assert snapshot['available'] and snapshot['captured_before_cleanup']
    assert snapshot['memory_current_bytes']==800 and snapshot['memory_peak_bytes']==950
    assert snapshot['memory_stat']=={'anon':500,'file':300}
    assert snapshot['memory_events']['max']==4 and snapshot['errors']=={}
    assert snapshot['owner_present'] and snapshot['native_child_present'] and snapshot['foreign_process_count']==0


@pytest.mark.parametrize('field,value',[('memory.current','max'),('memory.peak','-1'),
    ('memory.stat','file 1\nfile 2'),('memory.events','oom nope')])
def test_failure_resource_snapshot_keeps_other_fields_if_counter_unreadable(monkeypatch,field,value):
    controls={'path':'/synthetic','memory_max_bytes':1000}
    values={'memory.current':'800','memory.peak':'900','memory.stat':'file 10',
            'memory.events':'oom 0\noom_kill 0','cgroup.procs':'1'};values[field]=value
    monkeypatch.setattr(m,'_cgroup_controls',lambda *a:dict(controls))
    monkeypatch.setattr(m,'_read_small',lambda p:values[p.name])
    snapshot=m._failure_resource_snapshot('/synthetic',controls,{'pid':1},None)
    assert snapshot['available'] and snapshot['errors']=={field:'ValueError'}
    assert snapshot['owner_present'] and not snapshot['native_child_present']


def test_failure_resource_snapshot_never_reads_unadmitted_scope(monkeypatch):
    monkeypatch.setattr(m,'_read_small',lambda *a:pytest.fail('scope has not been admitted'))
    assert m._failure_resource_snapshot('/synthetic',None,{'pid':1},None)=={
        'available':False,'captured_before_cleanup':True,'reason':'scope_not_admitted'}


def test_rejected_sample_is_saved_before_native_cleanup(tmp_path,monkeypatch):
    kwargs,cleanup,children=mock_owned_operation(tmp_path,monkeypatch)
    events=[]
    rejected={'owner_rss_bytes':400000,'native_child_rss_bytes':700000,'combined_rss_bytes':1100000}
    def rss(*args):raise m._CombinedRSSLimitExceeded(rejected)
    monkeypatch.setattr(m,'_rss_sample',rss)
    monkeypatch.setattr(m,'_exchange',lambda child,request,deadline,on_line,sample,outputs:sample())
    def snapshot(*args):
        events.append('snapshot');assert cleanup==[]
        return {'available':True,'captured_before_cleanup':True,'memory_current_bytes':999999,
                'memory_peak_bytes':1000000,'memory_stat':{'file':777777},'memory_events':{'oom':0}}
    monkeypatch.setattr(m,'_failure_resource_snapshot',snapshot)
    with pytest.raises(ValueError,match='combined_owner_native_rss_limit'):
        m.run_full_forward([{'id':'x','source_text':'source only'}],**kwargs)
    receipt=json.loads((tmp_path/'out/failure.json').read_text())
    assert events==['snapshot'] and cleanup==[1]
    assert receipt['rejected_rss_observation']=={**rejected,'rejected':True}
    assert receipt['sampled_combined_max_rss_bytes']==1100000>receipt['combined_owner_child_rss_limit_bytes']
    assert receipt['sampled_owner_max_rss_bytes']==400000 and receipt['sampled_native_child_max_rss_bytes']==700000
    assert receipt['rss_observation_count']==1 and receipt['resource_snapshot_before_cleanup']['memory_current_bytes']==999999
    assert not receipt['training_executed'] and not receipt['operation_verified'] and not (tmp_path/'out/receipt.json').exists()


def test_failure_telemetry_error_cannot_skip_cleanup_or_replace_original_error(tmp_path,monkeypatch):
    kwargs,cleanup,children=mock_owned_operation(tmp_path,monkeypatch,failure='timeout_after_authorization')
    def unavailable(*args):raise OSError('synthetic unavailable cgroup')
    monkeypatch.setattr(m,'_failure_resource_snapshot',unavailable)
    with pytest.raises(TimeoutError,match='synthetic operation timeout'):
        m.run_full_forward([{'id':'x','source_text':'source only'}],**kwargs)
    receipt=json.loads((tmp_path/'out/failure.json').read_text())
    assert cleanup==[1] and receipt['error_type']=='TimeoutError'
    assert receipt['resource_snapshot_before_cleanup']=={'available':False,'captured_before_cleanup':True,'error_type':'OSError'}


def reclaim_fixture(identity):
    page=os.sysconf('SC_PAGE_SIZE')
    event=dict(rss_before_bytes=1000000,rss_after_bytes=100000,elapsed_seconds=.001,syscalls=1)
    return dict(policy=m.RECLAIM_POLICY,expected_layers=36,completed_layers=list(range(36)),
        mapping_intervals=[dict(start=page,end=page*2,offset=0,device=identity['device'],
            inode=identity['inode'],permissions='r--s')],page_size=page,before_row=dict(event),
        layer_events=[dict(event,layer=i) for i in range(36)],shared_filecache_eviction=False)


def make_v3(entry,row,context):
    context['reclaim_model_mappings']=True
    entry['requested_profile'].update(schema='native-source4096-worker-description/v3',profile=m.RECLAIM_PROFILE,
        model_map_reclaim=m.RECLAIM_POLICY,required_architecture='deepseek2',expected_layers=36,
        shared_filecache_eviction=False,native_perf_accounting=m.PERF_POLICY,
        cpu_buffer_observation=m.CPU_BUFFER_POLICY)
    row['model_map_reclaim']=reclaim_fixture(context['model_identity'])
    row['native_perf_accounting']=perf_fixture()
    row['cpu_buffer_observation']=cpu_buffer_fixture()
    row['device_observation_scope']='post-compute tensor buffers; non-null CPU device or exact registered CPU default buffer type; offload disabled'


def test_explicit_v3_native_profile_accepts_only_its_closed_reclaim_report():
    source,context,entry,row,closing,final=fixture();make_v3(entry,row,context)
    m._entry(entry,context,1,9);result=m._forward_row(row,source,0,context,'d'*64)
    assert result['model_map_reclaim']==row['model_map_reclaim']
    row['model_map_reclaim']['completed_layers'][0]=999
    assert result['model_map_reclaim']['completed_layers'][0]==0


@pytest.mark.parametrize('v3_request,v3_worker',[(False,True),(True,False)])
def test_v2_and_v3_profiles_cannot_silently_substitute(v3_request,v3_worker):
    source,context,entry,row,*_=fixture()
    if v3_worker:make_v3(entry,row,context)
    context['reclaim_model_mappings']=v3_request
    with pytest.raises(ValueError,match='profile_changed'):m._entry(entry,context,1,9)
    with pytest.raises(ValueError):m._forward_row(row,source,0,context,'d'*64)


@pytest.mark.parametrize('field,value',[
    ('policy','fadvise_dontneed'),('expected_layers',35),('expected_layers',True),
    ('completed_layers',list(range(35))),('completed_layers',[True,*range(1,36)]),
    ('completed_layers',list(reversed(range(36)))),('shared_filecache_eviction',True),
    ('page_size',True),('page_size',1),('mapping_intervals',[]),('layer_events',[]),('extra',True)])
def test_v3_reclaim_policy_mutations_rejected(field,value):
    _,context,*_=fixture();record=reclaim_fixture(context['model_identity']);record[field]=value
    with pytest.raises(ValueError):m._reclaim_record(record,context['model_identity'])


@pytest.mark.parametrize('field,value',[
    ('start',0),('start',True),('start',1),('end',1),('offset',-1),('offset',1),
    ('permissions','rw-s'),('permissions','r--p'),('permissions','r-xs'),
    ('device',999),('inode',999),('extra',1)])
def test_v3_cannot_reclaim_other_file_or_anonymous_or_writable_ranges(field,value):
    _,context,*_=fixture();record=reclaim_fixture(context['model_identity']);record['mapping_intervals'][0][field]=value
    with pytest.raises(ValueError):m._reclaim_record(record,context['model_identity'])


def test_v3_mapping_bounds_and_overlap_are_closed():
    _,context,*_=fixture();record=reclaim_fixture(context['model_identity']);page=record['page_size']
    record['mapping_intervals'][0]['end']=3*page
    with pytest.raises(ValueError,match='held_readonly'):m._reclaim_record(record,context['model_identity'])
    record=reclaim_fixture(context['model_identity']);record['mapping_intervals']*=2
    with pytest.raises(ValueError,match='overlapping'):m._reclaim_record(record,context['model_identity'])


@pytest.mark.parametrize('field,value',[
    ('rss_before_bytes',-1),('rss_after_bytes',True),('elapsed_seconds',float('nan')),
    ('elapsed_seconds',-1),('elapsed_seconds',True),('syscalls',0),('syscalls',True),
    ('layer',1),('layer',True),('extra',1)])
def test_v3_every_layer_must_have_complete_bounded_reclaim_event(field,value):
    _,context,*_=fixture();record=reclaim_fixture(context['model_identity']);record['layer_events'][0][field]=value
    with pytest.raises(ValueError):m._reclaim_record(record,context['model_identity'])


def test_v3_reclaims_do_not_claim_rss_must_decrease_every_time():
    _,context,*_=fixture();record=reclaim_fixture(context['model_identity'])
    record['layer_events'][0]['rss_after_bytes']=2000000
    assert m._reclaim_record(record,context['model_identity'])==record


@pytest.mark.parametrize('value',[None,0,1,{},'true'])
def test_native_reclaim_optin_requires_boolean_before_io(tmp_path,monkeypatch,value):
    monkeypatch.setattr(m,'_open_regular',lambda *a:pytest.fail('no I/O before invalid optin rejection'))
    with pytest.raises(ValueError,match='reclaim_boolean'):
        m.run_full_forward([{'id':'x','source_text':'text'}],worker_path='/unused',worker_sha256='a'*64,
            worker_source_path='/unused',worker_source_sha256='a'*64,model_path='/unused',
            expected_model_sha256='a'*64,expected_library_sha256={'/unused':'a'*64},resource_cgroup='/unused',
            output_directory=tmp_path/'out',deadline_seconds=1,max_rss_bytes=1048576,reclaim_model_mappings=value)
    assert not (tmp_path/'out').exists()


def test_synthetic_v3_full_protocol_issues_explicitly_labeled_result(tmp_path,monkeypatch):
    kwargs,cleanup,children=mock_owned_operation(tmp_path,monkeypatch,reclaim=True)
    result=m.run_full_forward([{'id':'x','source_text':'source only'}],reclaim_model_mappings=True,**kwargs)
    receipt=m.require_live_result(result)['receipt']
    assert cleanup==[1] and receipt['profile']==m.RECLAIM_PROFILE and receipt['model_map_reclaim'] is True
    assert receipt['rows'][0]['model_map_reclaim']['completed_layers']==list(range(36))
    assert receipt['shared_filecache_eviction'] is False and 'no per-layer Python' in receipt['model_map_reclaim_observation_scope']


def perf_fixture():
    return dict(policy=m.PERF_POLICY,backend_revision=m.BACKEND_REVISION,backend_context_sha256=m.BACKEND_CONTEXT_SHA256,
        raw_n_p_eval=3,raw_n_eval=1,raw_t_p_eval_ms=10.,raw_t_eval_ms=0.,dispatch='prompt_batch',
        accounted_prompt_tokens=3,accounted_single_tokens=0)


def cpu_buffer_fixture():
    return dict(policy=m.CPU_BUFFER_POLICY,backend_revision=m.BACKEND_REVISION,
        backend_source_sha256=m.BACKEND_BUFFER_SOURCE_SHA256,registered_cpu_devices=['CPU'],
        cpu_device_pointer_nodes=0,canonical_cpu_buffer_type_nodes=10,
        canonical_cpu_buffer_type_null_device_nodes=10,unrecognized_buffer_type_nodes=0)


def test_v3_cpu_buffer_registry_observation_retains_raw_null_device_route():
    value=cpu_buffer_fixture();observed=m._cpu_buffer_record(value,10,0)
    assert observed==value and observed['cpu_device_pointer_nodes']==0
    value['registered_cpu_devices'].append('CUDA0')
    assert observed['registered_cpu_devices']==['CPU']
    source,context,entry,row,*_=fixture();make_v3(entry,row,context)
    result=m._forward_row(row,source,0,context,'d'*64)
    assert result['cpu_buffer_observation']==row['cpu_buffer_observation']


@pytest.mark.parametrize('field,value',[
    ('policy','name_only_CPU'),('backend_revision','0'*40),('backend_source_sha256','0'*64),
    ('registered_cpu_devices',[]),('registered_cpu_devices',['CPU','CUDA0']),
    ('registered_cpu_devices',['CPU','CPU']),('cpu_device_pointer_nodes',True),
    ('cpu_device_pointer_nodes',-1),('canonical_cpu_buffer_type_nodes',float('nan')),
    ('canonical_cpu_buffer_type_null_device_nodes',11),('unrecognized_buffer_type_nodes',-1),('extra',1)])
def test_v3_cpu_buffer_provenance_and_count_mutations_are_rejected(field,value):
    data=cpu_buffer_fixture();data[field]=value
    with pytest.raises(ValueError):m._cpu_buffer_record(data,10,0)


def test_v3_unknown_buffers_remain_unknown_and_cannot_satisfy_positive_cpu_observation():
    data=cpu_buffer_fixture();data.update(canonical_cpu_buffer_type_nodes=0,
        canonical_cpu_buffer_type_null_device_nodes=0,unrecognized_buffer_type_nodes=10)
    with pytest.raises(ValueError,match='coverage'):m._cpu_buffer_record(data,10,0)
    data.update(canonical_cpu_buffer_type_nodes=1,canonical_cpu_buffer_type_null_device_nodes=1,
        unrecognized_buffer_type_nodes=8)
    result=m._cpu_buffer_record(data,10,1)
    assert result['unrecognized_buffer_type_nodes']==8
    with pytest.raises(ValueError,match='coverage'):m._cpu_buffer_record(data,11,1)
    data.update(cpu_device_pointer_nodes=1,canonical_cpu_buffer_type_nodes=0,
        canonical_cpu_buffer_type_null_device_nodes=0)
    assert m._cpu_buffer_record(data,10,1)['cpu_device_pointer_nodes']==1


def test_v3_cannot_omit_buffer_identity_evidence_or_use_old_scope():
    source,context,entry,row,*_=fixture();make_v3(entry,row,context)
    del row['cpu_buffer_observation']
    with pytest.raises(ValueError,match='closed_full'):m._forward_row(row,source,0,context,'d'*64)
    make_v3(entry,row,context);row['device_observation_scope']='post-compute tensor buffers; CPU-only registered backend and offload disabled'
    with pytest.raises(ValueError,match='scope'):m._forward_row(row,source,0,context,'d'*64)
    del entry['requested_profile']['cpu_buffer_observation']
    with pytest.raises(ValueError,match='profile'):m._entry(entry,context,1,9)


def test_pinned_perf_policy_retains_idle_clamp_without_counting_it_as_work():
    value=perf_fixture();observed=m._perf_record(value,3,3,0)
    assert observed==value and observed['raw_n_eval']==1 and observed['accounted_single_tokens']==0
    value['raw_n_p_eval']=999
    assert observed['raw_n_p_eval']==3
    one=perf_fixture();one.update(raw_n_p_eval=1,raw_t_p_eval_ms=0.,raw_t_eval_ms=10.,dispatch='single_token',
        accounted_prompt_tokens=0,accounted_single_tokens=1)
    assert m._perf_record(one,1,0,1)==one


@pytest.mark.parametrize('field,value',[
    ('policy','guess_zero_idle'),('backend_revision','0'*40),('backend_context_sha256','0'*64),
    ('raw_n_p_eval',2),('raw_n_eval',0),('raw_n_eval',True),('raw_t_p_eval_ms',0),
    ('raw_t_p_eval_ms',True),('raw_t_eval_ms',.01),('raw_t_eval_ms',float('nan')),
    ('dispatch','single_token'),('accounted_prompt_tokens',2),('accounted_single_tokens',1),('extra',0)])
def test_perf_policy_rejects_arbitrary_counter_waivers(field,value):
    data=perf_fixture();data[field]=value
    with pytest.raises(ValueError):m._perf_record(data,3,3,0)


@pytest.mark.parametrize('prompt,single',[(3,1),(2,0),(0,3)])
def test_perf_report_must_match_top_level_accounted_tokens(prompt,single):
    with pytest.raises(ValueError):m._perf_record(perf_fixture(),3,prompt,single)


@pytest.mark.parametrize('field,value',[
    ('dispatch','prompt_batch'),('raw_n_eval',2),('raw_n_p_eval',0),
    ('raw_t_p_eval_ms',.01),('raw_t_eval_ms',0),('accounted_prompt_tokens',1),('accounted_single_tokens',0)])
def test_single_token_perf_branch_also_requires_exact_idle_clamp(field,value):
    data=perf_fixture();data.update(raw_n_p_eval=1,raw_t_p_eval_ms=0.,raw_t_eval_ms=10.,dispatch='single_token',
        accounted_prompt_tokens=0,accounted_single_tokens=1);data[field]=value
    with pytest.raises(ValueError):m._perf_record(data,1,0,1)


def worker_error_fixture(nonce='a'*64,source='c'*64,*,entry_emitted=True,rows=0,tokens=0):
    return dict(schema='native-source4096-worker-error/v1',nonce=nonce,worker_source_sha256=source,
        complete=False,error='native evaluated-token count differs',entry_emitted=entry_emitted,
        rows_emitted=rows,native_tokens_evaluated=tokens,model_and_context_freed=True,
        production_cache_allowed=False,admitted=False,qualified=False,proof_authority=False,
        source_semantics_verified=False)


@pytest.mark.parametrize('field,value',[
    ('schema','other'),('nonce','b'*64),('worker_source_sha256','b'*64),('complete',True),
    ('production_cache_allowed',True),('qualified',True),('admitted',True),('proof_authority',True),
    ('source_semantics_verified',True),('model_and_context_freed',False),('entry_emitted',False),
    ('entry_emitted',1),('rows_emitted',1),('rows_emitted',False),('native_tokens_evaluated',1),
    ('native_tokens_evaluated',False),('error',''),('error','x'*257),('error','\0'),('extra',1)])
def test_closed_native_worker_error_rejects_drift_or_progress_overclaim(field,value):
    _,context,*_=fixture();record=worker_error_fixture();record[field]=value
    with pytest.raises(ValueError):m._worker_error(record,context,[],True)


@pytest.mark.parametrize('failure,rows,entry',[('native_error_before_entry',0,False),
    ('native_error_after_entry',0,True),('native_error_after_row',1,True)])
def test_native_worker_error_preserves_actual_cause_never_issues_result(tmp_path,monkeypatch,failure,rows,entry):
    kwargs,cleanup,children=mock_owned_operation(tmp_path,monkeypatch,failure=failure)
    old=len(m._ISSUED)
    with pytest.raises(m._NativeWorkerError,match='native_worker_failed: native evaluated-token count differs'):
        m.run_full_forward([{'id':'x','source_text':'source only'}],**kwargs)
    receipt=json.loads((tmp_path/'out/failure.json').read_text())
    assert cleanup==[1] and len(m._ISSUED)==old and not (tmp_path/'out/receipt.json').exists()
    assert receipt['native_worker_error']['error']=='native evaluated-token count differs'
    assert receipt['native_worker_error']['rows_emitted']==rows and receipt['native_worker_error']['entry_emitted']==entry
    assert receipt['rows_observed']==rows and not receipt['training_executed'] and not receipt['operation_verified']
    lines=(tmp_path/'out/stdout.log').read_bytes().splitlines(keepends=True)
    assert receipt['protocol_progress']['native_error_record_sha256']==hashlib.sha256(lines[-1]).hexdigest()
