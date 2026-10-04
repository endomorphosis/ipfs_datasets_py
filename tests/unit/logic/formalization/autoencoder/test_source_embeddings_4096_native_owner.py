"""Protocol/cleanup controls only; fixtures are never native model evidence."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import time

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_4096_native_owner as m


def fixture():
    rows = [{"id": "one", "source_text": "The agency shall retain records."}]
    identity = {"device": 1, "inode": 2, "bytes": 100, "mtime_ns": 3000000004, "ctime_ns": 5000000006}
    native_identity = {"device": 1, "inode": 2, "bytes": 100, "mtime_seconds": 3,
        "mtime_nanoseconds": 4, "ctime_seconds": 5, "ctime_nanoseconds": 6}
    process = {"pid": 10, "ppid": 9, "birth_ticks": "100", "executable": "/controlled/worker"}
    common = {"nonce": "a" * 64, "request_sha256": "b" * 64, "worker_source_sha256": "c" * 64,
        "admitted": False, "qualified": False, "proof_authority": False, "source_semantics_verified": False,
        "model_identity": native_identity, "process": process}
    geometry = {"native_input_dimension": None, "native_output_dimension": None,
        "metadata_architecture": "qwen3moe", "metadata_embedding_length": 4096,
        "metadata_embedding_length_out": None, "metadata_embedding_length_key": "qwen3moe.embedding_length",
        "metadata_embedding_length_out_key": "qwen3moe.embedding_length_out", "vocabulary_size": 1000,
        "actual_context": None, "actual_batch": None, "actual_ubatch": None, "actual_sequences": None,
        "actual_pooling": None, "context_created": False}
    profile = {"schema": "native-source4096-worker-description/v1", "modes": ["vocab", "embed"],
        "profile": "leanstral4096:cpu1:last:l2:single-sequence:tokens512:v1", "dimension": 4096,
        "context_limit": 512, "batch_limit": 512, "ubatch_limit": 512, "sequence_count": 1, "threads": 1,
        "requested_gpu_layers": 0, "add_special": True, "parse_special": False, "request_source_only": True,
        "model_content_hash_verified_by_worker": False, "full_forward_executed": False}
    records = [dict(common, schema="native-source4096-worker-entry/v1", mode="vocab", model_fd=3,
        requested_profile=profile, source_rows=1, model_content_hash_verified_by_worker=False, model_loaded=False),
        dict(common, schema="native-source4096-worker-row/v1", index=0, id="one",
            source_sha256=hashlib.sha256(rows[0]["source_text"].encode()).hexdigest(), token_ids=[1, 20, 3],
            token_count=3, add_special=True, parse_special=False, truncated=False,
            chat_template_applied=False, geometry=geometry, full_forward_executed=False),
        dict(common, schema="native-source4096-worker-closing/v1", mode="vocab", complete=True, rows_emitted=1,
            native_tokens_evaluated=0, geometry=geometry, model_and_context_freed=True,
            inherited_fd_still_parent_owned=True, full_forward_executed=False, model_content_hash_verified_by_worker=False)]
    args = dict(rows=rows, nonce="a" * 64, request_sha256="b" * 64, worker_source_sha256="c" * 64,
        pid=10, parent_pid=9, birth="100", executable="/controlled/worker", model_identity=identity)
    return copy.deepcopy(records), args


def test_closed_vocabulary_control_retains_no_vectors_or_admission():
    records, args = fixture()
    result = m.validate_vocab_records(records, **args)
    assert result["sample_count"] == 1 and result["native_tokens_evaluated"] == 0
    assert result["geometry"]["context_created"] is False
    assert not {"embedding", "qualified", "admitted", "production_embedding_allowed"} & set(result)


@pytest.mark.parametrize("index,field,value", [
    (0,"mode","embed"), (0,"model_loaded",True), (0,"model_content_hash_verified_by_worker",True),
    (0,"source_rows",True), (0,"model_fd",True), (0,"nonce","d"*64),
    (1,"source_sha256","d"*64), (1,"worker_source_sha256","d"*64), (1,"request_sha256","d"*64),
    (1,"id","another"), (1,"index",True), (1,"parse_special",True), (1,"add_special",False),
    (1,"truncated",True), (1,"chat_template_applied",True), (1,"full_forward_executed",True),
    (1,"token_ids",[True]), (1,"token_ids",[-1]), (1,"token_ids",[1000]), (1,"token_ids",[1]*513),
    (1,"token_count",True), (1,"token_count",2), (1,"embedding",[0.]*4096),
    (2,"complete",False), (2,"rows_emitted",True), (2,"rows_emitted",0),
    (2,"native_tokens_evaluated",False), (2,"native_tokens_evaluated",1),
    (2,"model_and_context_freed",False), (2,"inherited_fd_still_parent_owned",False),
    (2,"qualified",True), (2,"admitted",True), (2,"proof_authority",True),
    (2,"source_semantics_verified",True), (2,"schema","error"),
])
def test_changed_fence_or_claim_refuses(index, field, value):
    records, args = fixture(); records[index][field] = value
    with pytest.raises(ValueError): m.validate_vocab_records(records, **args)


@pytest.mark.parametrize("field,value", [("native_output_dimension",768),("actual_context",512),
    ("context_created",True),("vocabulary_size",True),("extra",1),("native_input_dimension",4096),
    ("metadata_embedding_length",768),("metadata_embedding_length_out",True),
    ("metadata_embedding_length_out",768),("metadata_architecture","bad/name"),
    ("metadata_embedding_length_key","other.embedding_length")])
def test_geometry_refuses(field, value):
    records, args = fixture(); records[-1]["geometry"][field] = value
    with pytest.raises(ValueError): m.validate_vocab_records(records, **args)


@pytest.mark.parametrize("field,value", [("pid",11),("ppid",8),("birth_ticks","101"),("executable","/other")])
def test_process_fence_refuses(field, value):
    records, args = fixture(); records[-1]["process"][field] = value
    with pytest.raises(ValueError): m.validate_vocab_records(records, **args)


def test_partial_and_reordered_records_refuse():
    records, args = fixture()
    for broken in (records[:-1], records + [records[-1]], list(reversed(records))):
        with pytest.raises(ValueError): m.validate_vocab_records(broken, **args)


@pytest.mark.parametrize("rows", [[],[{"id":"x","source_text":"a","target":"P(a)"}],
    [{"id":"x","source_text":"a"}]*2,[{"id":"x","source_text":"a\0b"}],
    [{"id":"x","source_text":"a"*65537}], [{"id":"x","source_text":True}]])
def test_gold_or_oversize_source_channels_refuse(rows):
    with pytest.raises(ValueError): m.validate_rows(rows)


def test_duplicate_and_nonfinite_native_json_refuse():
    for raw in ('{"x":1,"x":2}', '{"x":NaN}'):
        with pytest.raises(ValueError): m._decode(raw)


def test_expired_child_is_reaped_and_only_owned_group_is_signalled():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    identity = m._process(child.pid)
    try:
        with pytest.raises(TimeoutError): m._exchange(child, b"request", time.monotonic()+.05)
        cleanup = m._cleanup(child, identity)
        assert cleanup["leader_reaped"] and cleanup["live_group_processes"] == 0
        assert child.poll() is not None
    finally:
        if child.poll() is None: child.kill(); child.wait()
        for stream in (child.stdin,child.stdout,child.stderr):
            if not stream.closed: stream.close()


def test_bounded_duplex_exchange_drains_both_streams():
    code = "import sys; x=sys.stdin.buffer.read(); sys.stdout.buffer.write(x); sys.stderr.write('control')"
    child = subprocess.Popen([sys.executable,"-c",code], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    identity = m._process(child.pid)
    status, streams = m._exchange(child, b"x"*100000, time.monotonic()+5)
    assert status == 0 and streams == {"stdout": b"x"*100000,"stderr":b"control"}
    assert m._cleanup(child,identity)["leader_reaped"]
