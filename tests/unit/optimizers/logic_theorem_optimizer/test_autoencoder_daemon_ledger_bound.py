"""Bounded ledger metadata fixtures; no scheduler/native/campaign admission."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources


@pytest.fixture
def local(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("metadata fixtures cannot acquire native scheduler resources")
    monkeypatch.setattr(resources, "get_global_resource_scheduler", forbidden)
    root=tmp_path/"outputs";root.mkdir();(root/"retained-output").write_bytes(b"abc")
    path=tmp_path/"ledger.json"
    owner=resources.DaemonResourceReservation(path,roots=[root],storage_bytes=7,memory_mb=1)
    value=deepcopy(owner._read())
    value["reservations"]={status:{"reservation_id":status,"status":status,
        "owner_pid":os.getpid(),"storage_bytes":amount,"external_charges":{"retained-artifacts":2},
        "artifacts_durable_asserted":status=="released","prior_children":[]} for status,amount in
        (("active",11),("retained",13),("reserved",17),("released",19))}
    return owner,path,value,root


def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()


def assert_no_admission(owner):
    assert owner._lease is None and owner.to_dict()["status"]=="not_entered"


def test_metadata_bound_is_sixteen_mib_and_storage_policies_stay_distinct():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as worker
    assert resources.MAX_LEDGER_BYTES==16*1024*1024
    assert resources.MAX_STORAGE_BYTES==160_000_000_000
    assert resources.MAX_RESERVATIONS==4096
    assert resources.SCHEMA=="daemon-resource-reservations-v1"
    assert worker.MAX_STORAGE_BYTES==50_000_000_000


def test_large_valid_ledger_roundtrip_preserves_every_row_and_charge(local):
    owner,path,value,_=local
    value["reservations"]["retained"]["retained_history"]="x"*(8*1024*1024+4096)
    before=deepcopy(value);raw=encoded(value)
    assert 8*1024*1024<len(raw)<resources.MAX_LEDGER_BYTES
    path.write_bytes(raw)
    assert owner._read()==before
    with owner._locked():owner._write(owner._read())
    assert path.read_bytes()==raw
    assert owner._read()==before
    assert_no_admission(owner)


def test_inclusive_metadata_boundary_and_one_byte_read_overflow(local,monkeypatch):
    owner,path,value,_=local;raw=encoded(value)
    monkeypatch.setattr(resources,"MAX_LEDGER_BYTES",len(raw))
    with owner._locked():owner._write(value)
    assert owner._read()==value
    path.write_bytes(raw+b" ")
    with pytest.raises(resources.DaemonResourceError,match="invalid disk ledger file"):owner._read()
    assert path.read_bytes()==raw+b" "
    assert_no_admission(owner)


def test_above_sixteen_mib_read_refuses_before_json_parse(local,monkeypatch):
    owner,path,_,_=local
    with path.open("wb")as stream:stream.truncate(resources.MAX_LEDGER_BYTES+1)
    size=path.stat().st_size
    monkeypatch.setattr(resources.json,"loads",lambda *_args,**_kwargs:pytest.fail("oversize ledger parsed"))
    with pytest.raises(resources.DaemonResourceError,match="invalid disk ledger file"):owner._read()
    assert path.stat().st_size==size
    assert_no_admission(owner)


def test_above_sixteen_mib_write_preserves_old_file_before_any_temp_or_replace(local,monkeypatch):
    owner,path,value,_=local;original=encoded(value);path.write_bytes(original)
    value["reservations"]["retained"]["retained_history"]="x"*resources.MAX_LEDGER_BYTES
    monkeypatch.setattr(resources.tempfile,"NamedTemporaryFile",lambda *_args,**_kwargs:pytest.fail("oversize temp created"))
    monkeypatch.setattr(resources.os,"replace",lambda *_args,**_kwargs:pytest.fail("oversize ledger replaced"))
    with pytest.raises(resources.DaemonResourceError,match="disk ledger byte bound exceeded"):owner._write(value)
    assert path.read_bytes()==original
    assert_no_admission(owner)


@pytest.mark.parametrize("damage",("roots","cap","rows","charge","record_id"))
def test_larger_bound_preserves_scope_and_record_refusals(local,damage):
    owner,path,value,_=local
    if damage=="roots":value["roots"][0]["inode"]+=1
    elif damage=="cap":value["limit_bytes"]-=1
    elif damage=="rows":
        value["reservations"]={str(i):{"reservation_id":str(i),"status":"retained",
            "owner_pid":os.getpid(),"storage_bytes":1}for i in range(4097)}
    elif damage=="charge":value["reservations"]["retained"]["external_charges"]["retained-artifacts"]=-1
    else:value["reservations"]["retained"]["reservation_id"]="another-record"
    raw=encoded(value);path.write_bytes(raw)
    with pytest.raises(resources.DaemonResourceError):owner._read()
    assert path.read_bytes()==raw
    assert_no_admission(owner)


@pytest.mark.parametrize("damage",("duplicate","nonfinite"))
def test_larger_bound_still_rejects_duplicate_and_nonfinite_json(local,damage):
    owner,path,value,_=local
    if damage=="duplicate":
        raw=encoded(value).replace(b'{"limit_bytes":',b'{"schema":"test-only-duplicate","limit_bytes":',1)
    else:
        value["reservations"]["retained"]["retained_history"]=float("nan")
        raw=json.dumps(value,separators=(",",":")).encode()
    path.write_bytes(raw)
    with pytest.raises(resources.DaemonResourceError):owner._read()
    assert path.read_bytes()==raw
    assert_no_admission(owner)


def test_full_nonreleased_accounting_and_physical_free_cutoff_stay_intact(local,monkeypatch):
    owner,path,value,root=local;path.write_bytes(encoded(value))
    observed=owner._account(owner._read(),additional=7)
    assert observed["observed_apparent_bytes"]==3
    assert observed["outstanding_full_reservations_bytes"]==41
    assert observed["charged_bytes"]==51
    monkeypatch.setattr(resources.shutil,"disk_usage",lambda _path:SimpleNamespace(free=47))
    with pytest.raises(resources.DaemonResourceError,match="capacity"):owner._account(owner._read(),additional=7)
    assert owner._read()==value
    assert_no_admission(owner)


def test_fleet_storage_observer_accepts_large_ledger_without_modification_or_admission(local):
    owner,path,value,root=local
    value["reservations"]["released"]["retained_history"]="x"*(8*1024*1024+4096)
    original=encoded(value);path.write_bytes(original)
    package_root=Path(resources.__file__).resolve().parents[3]
    source=package_root/"scripts/ops/legal_ir/run_autoencoder_fleet.py"
    spec=importlib.util.spec_from_file_location("test_actual_fleet_ledger_reader",source)
    fleet=importlib.util.module_from_spec(spec);spec.loader.exec_module(fleet)
    result=fleet.storage_capacity(path,root)
    assert result["outstanding_reservations_bytes"]==41
    assert result["ledger_modified"] is False and result["reservation_acquired"] is False
    assert path.read_bytes()==original
    assert_no_admission(owner)
