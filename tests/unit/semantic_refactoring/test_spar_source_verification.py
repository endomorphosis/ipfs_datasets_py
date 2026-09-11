"""Real Git/source reconstruction; nominations cannot provide missing proofs."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import tempfile

import pytest
from ipfs_datasets_py.logic.software_contracts.semantic_state.spar_verification import (
    reconstruct_source, SparVerificationError)
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured


def git(root,*args):
    return subprocess.check_output(["git","-C",str(root),*args],stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture
def source():
    root=Path(tempfile.mkdtemp(prefix="spar-datasets-source-",dir="/dev/shm"))
    (root/"a.py").write_text("def add(a,b):\n return a+b\n")
    git(root,"init","-q");git(root,"add",".")
    git(root,"-c","user.name=Test","-c","user.email=t@example.invalid","commit","-qm","source")
    return root,dict(repository="fixture",path=str(root),head=git(root,"rev-parse","HEAD"),tree=git(root,"rev-parse","HEAD^{tree}"))


def test_actual_semantic_and_required_source_consumer(source):
    _,spec=source;result=reconstruct_source([spec]);report=result["report"]
    assert cid_for_structured(report)==result["report_cid"]
    assert all(cid_for_structured(block)==cid for cid,block in result["blocks"].items())
    assert report["repositories"][0]["source_evidence"]
    assert not report["repositories"][0]["source_limitations"]
    assert not report["accepted_root"] and len(report["missing_coverage"])==7


@pytest.mark.parametrize("change",["head","tree","dirty","hidden"])
def test_source_drift_and_hidden_index_hints_refuse(source,change):
    root,spec=source
    if change in {"head","tree"}:spec[change]="0"*40
    else:
        if change=="hidden":git(root,"update-index","--assume-unchanged","a.py")
        (root/"a.py").write_text("def add(a,b):\n return a-b\n")
    with pytest.raises(SparVerificationError):reconstruct_source([spec])


@pytest.mark.parametrize("key",["accepted_root","issuer","semantic_root","proof_passed","expected_terminal"])
def test_caller_cannot_supply_issuer_or_acceptance(source,key):
    _,spec=source;spec[key]=True
    with pytest.raises(SparVerificationError):reconstruct_source([spec])


def test_chunk_keeps_full_unprocessed_inventory_and_expected_negatives(source):
    root,spec=source
    for i in range(12):(root/f"m{i:02}.py").write_text(f"value = {i}\n")
    (root/"negative-vector.json").write_text(json.dumps({"expected_terminal":"network_denied_general_llm","accepted_root":True}))
    git(root,"add",".");git(root,"-c","user.name=Test","-c","user.email=t@example.invalid","commit","-qm","more source and negative specification")
    spec.update(head=git(root,"rev-parse","HEAD"),tree=git(root,"rev-parse","HEAD^{tree}"))
    result=reconstruct_source([spec]);row=result["report"]["repositories"][0]
    inventory=result["blocks"][row["source_chunk_inventory_cid"]]
    assert len(row["selected_paths"])==8 and row["unprocessed_entry_count"]==6
    assert len(inventory["inventory"])==14
    assert not result["report"]["accepted_root"] and result["report"]["target_program_executed"] is False
    assert "failed_positive_execution" not in str(result["report"])
