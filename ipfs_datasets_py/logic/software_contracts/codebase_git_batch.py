"""Opt-in bounded Git batch acquisition over sealed complete source pages.

The native snapshot remains the source owner. Clean UTF-8 objects may be read in
one Git process; dirty captured bytes come from the existing immutable source
CAS. Every opaque entry is retained. This changes neither the initial scanner
nor its source head, and never substitutes HEAD bytes for a dirty overlay.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import shutil
import time

from . import codebase_repository_shards as shards
from .codebase_resources import acquire_codebase_resources
from .codebase_scan_policy_live import verify_policy_current
from .content import cid_for_bytes
from .semantic_index.git_decoder_profile import DEFAULT_DECODER_PROFILE,DECODER_CONFIG,validate_decoder_profile
from ..backends import codebase_process as process
from ...duckdb_control.codebase_catalog import CodebaseHead
from ...optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane,LeaseCancelledError,LeaseTimeoutError

MAX_BYTES=2*1024**2
require=shards.require
sha=lambda body:hashlib.sha256(body).hexdigest()


def pins():
    return dict(owner=sha(Path(__file__).read_bytes()),source_shards=shards.pins(),
        process=sha(Path(process.__file__).read_bytes()),decoder=DEFAULT_DECODER_PROFILE.payload())


def _git_identity():
    path=shutil.which('git',path='/usr/bin:/bin')
    require(path is not None,'qualified local Git executable unavailable')
    resolved=Path(path).resolve()
    require(resolved.is_file() and resolved.stat().st_size<=32*1024**2,'bounded Git executable required')
    with resolved.open('rb') as stream:body=stream.read(32*1024**2+1)
    require(len(body)<=32*1024**2,'Git executable grew beyond identity bound')
    return dict(path=str(resolved),sha256=sha(body))


def _exact_body(entry,body):
    require(type(body) is bytes and len(body)==entry.size_bytes and len(body)<=65536
        and cid_for_bytes(body)==entry.source_cid,'Git/CAS body differs from sealed source entry')
    body.decode('utf-8',errors='strict')
    return body


def _parse_batch(stdout,entries):
    """Byte-exact Git protocol, including ordered headers, bodies and EOF.

    The process owner exposes UTF-8 text; this profile only admits source
    entries already independently captured as strict UTF-8, and hashes the
    re-encoded bytes. Replacement decoding therefore cannot be accepted.
    """
    wire=stdout.encode('utf-8');require(len(wire)<=MAX_BYTES,'Git batch output exceeds bound')
    position=0;bodies={}
    for entry in entries:
        newline=wire.find(b'\n',position,position+128)
        require(newline>=position,'missing bounded Git batch header')
        header=wire[position:newline]
        expected=f'{entry.git_blob_oid} blob {entry.size_bytes}'.encode('ascii')
        require(header==expected,'Git batch object/type/size header differs')
        start=newline+1;stop=start+entry.size_bytes
        require(wire[stop:stop+1]==b'\n','missing Git batch body terminator')
        body=_exact_body(entry,wire[start:stop])
        framed=b'blob '+str(len(body)).encode('ascii')+b'\0'+body
        digest=hashlib.sha1(framed).hexdigest() if len(entry.git_blob_oid)==40 else sha(framed)
        require(digest==entry.git_blob_oid,'Git object digest differs from requested immutable blob')
        bodies[entry.source_key]=body;position=stop+1
    require(position==len(wire),'Git batch returned trailing or extra objects')
    return bodies


def read_repository_source_page(index,repository,*,root_cid,cursor,mode='batch',
        scheduler=None,parent_lease=None,cancel_event=None,timeout_seconds=60,memory_mb=512):
    """Return all entries in one sealed page with exact acquired source text.

    ``per_blob`` is an explicit local performance control, not the default.
    Object acquisition is bounded independently of the before/after complete
    live-source fences. The process count below counts object reads only.
    """
    require(mode in ('batch','per_blob','cas'),'explicit bounded acquisition mode required')
    require(type(timeout_seconds) in (int,float) and math.isfinite(timeout_seconds) and 0<timeout_seconds<=300,
        'bounded Git page deadline required')
    deadline=time.monotonic()+timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
            timeout_seconds=timeout_seconds,memory_mb=memory_mb) as lease:
        signal=lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set():raise LeaseCancelledError('Git page acquisition cancelled')
            duration=deadline-time.monotonic()
            if duration<=0:raise LeaseTimeoutError('Git page acquisition expired')
            return duration
        source=shards.load_repository_shards(index,root_cid)
        page_result=shards.read_repository_shard(index,root_cid,cursor)
        require(page_result['page'] is not None,'source acquisition requires a nonterminal page')
        head=CodebaseHead.from_dict(source['source_head'])
        def observe():
            verify_policy_current(index,repository,expected_head=head,receipt_cid=source['policy_receipt_cid'],
                parent_lease=lease,cancel_event=signal,timeout_seconds=remaining(),memory_mb=memory_mb)
        observe();producer=pins();validate_decoder_profile(DEFAULT_DECODER_PROFILE)
        native=index.load(source['structural_manifest_cid']);entries={e.source_key:e for e in native.snapshot.entries}
        rows=page_result['page']['rows'];selected=[];bodies={};dispositions={}
        for row in rows:
            entry=entries[row['source_key']]
            require(entry.entry_cid==row['entry_cid'],'page entry differs from native source inventory')
            if entry.is_opaque:dispositions[entry.source_key]='opaque_not_acquired';continue
            # A dirty repository labels its untouched tracked paths "working".
            # Requiring the captured index and HEAD OIDs to agree plus the
            # exact source CID below keeps modified/staged overlays out.
            if mode!='cas' and entry.disposition in ('clean','working') and entry.git_blob_oid \
                    and entry.git_blob_oid==entry.head_blob_oid:
                require(len(entry.git_blob_oid) in (40,64),'unsupported Git object format')
                selected.append(entry);dispositions[entry.source_key]='git_'+mode
            else:
                bodies[entry.source_key]=_exact_body(entry,index.artifacts.get_bytes(entry.source_cid))
                dispositions[entry.source_key]='captured_source_cas'
        require(len(selected)<=16 and sum(e.size_bytes for e in selected)<=1024**2,'bounded Git source page required')
        identity=_git_identity() if selected else None;receipts=[]
        groups=[selected] if mode=='batch' and selected else [[entry] for entry in selected]
        base=[identity['path'],'--no-optional-locks','--no-replace-objects'] if identity else []
        for key,value in (*DECODER_CONFIG,('core.fsmonitor','false'),('core.hooksPath','/dev/null')):
            base.extend(['-c',key+'='+value])
        base.extend(['-C',str(Path(repository).resolve()),'cat-file','--batch'])
        runner=process.BoundedToolRunner(base_environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8',
            'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_NO_LAZY_FETCH':'1','GIT_TERMINAL_PROMPT':'0'})
        for group in groups:
            payload=''.join(e.git_blob_oid+'\n' for e in group).encode('ascii')
            with lease.acquire_child(lane=ResourceLane.SNAPSHOT_EVALUATION,cpu_slots=1,memory_mb=128,child_process_slots=1,
                    timeout=remaining(),cancel_event=signal,request_id='codebase-git-page') as child:
                result=process.run_bounded_stdin_tool(base,payload,runner=runner,
                    limits=process.ToolRunLimits(timeout_seconds=remaining(),memory_bytes=DEFAULT_DECODER_PROFILE.address_space_bytes,
                        resident_memory_bytes=128*1024**2,max_input_bytes=2048,max_output_bytes=MAX_BYTES,
                        max_workspace_bytes=MAX_BYTES),cancellation=child.combined_cancellation_signal(signal))
            require(result.returncode==0 and result.workspace_cleaned and not any((result.timed_out,result.cancelled,
                result.unavailable,result.output_truncated,result.resource_exhausted,result.error)),
                'bounded Git page worker failed: '+str(result.termination_reason)+': '+result.stderr[-1024:])
            bodies.update(_parse_batch(result.stdout,group))
            receipts.append(dict(input_sha256=sha(payload),output_sha256=sha(result.stdout.encode()),elapsed_ms=result.elapsed_ms,
                objects=len(group),command=list(result.command),returncode=result.returncode,workspace_cleaned=result.workspace_cleaned,
                parent_lease_id=lease.lease_id,child_lease_id=child.lease_id))
        observe();remaining();require(producer==pins(),'Git page producer changed')
        require(identity is None or identity==_git_identity(),'Git executable changed during page acquisition')
        output=[dict(row,acquisition=dispositions[row['source_key']],source_text=None if row['source_key'] not in bodies
            else bodies[row['source_key']].decode('utf-8')) for row in rows]
        return dict(schema='codebase-bounded-git-source-page@1',source_root_cid=root_cid,page_cid=page_result['page_cid'],
            next_cursor=page_result['next_cursor'],at_end=page_result['at_end'],mode=mode,rows=output,
            producer=producer,git_executable=identity,object_processes=len(receipts),object_receipts=receipts,
            object_acquisition_elapsed_ms=sum(r['elapsed_ms'] for r in receipts),source_observed_live=True,
            authority='exact_native_source_page_acquisition_only',**shards.FALSE)


__all__=['read_repository_source_page']
