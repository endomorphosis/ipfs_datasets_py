"""Exact source inventory generation retains independent completion checks."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


helper = load("inventory_materializer_test_owner", ROOT / "scripts/ops/legal_ir/materialize_legal_ir_inventory.py")


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    for relative in ["scripts/ops/legal_ir/legal_ir_supervisor_contract.py",
                     "ipfs_datasets_py/logic/autoformal/uscode_ingest.py",
                     "ipfs_datasets_py/logic/autoformal/constitution_inventory.py"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    contract = helper.contract_owner(tmp_path)
    source = tmp_path / contract.CONSTITUTION
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / contract.CONSTITUTION, source)
    tasks = [{"task_id": task_id} for task_id in ["LIRAE-USC-T04", "LIRAE-USC-TNA",
             "LIRAE-CONST-AM18", "LIRAE-CONST-AM21", "LIRAE-WIDTH-384", "LIRAE-METHOD-01"]]
    plan = {"tasks": tasks, "shards": [
        {"task_id": "LIRAE-USC-T04", "title": "4", "start": 0, "end": 2, "count": 2},
        {"task_id": "LIRAE-USC-TNA", "title": "NA", "start": 0, "end": 9, "count": 9}]}
    plan_path = tmp_path / contract.PLAN
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_bytes(helper.raw(plan))
    rows = [
        {"source_row_index": 17, "ipfs_cid": "cid-alpha", "title_number": "4",
         "section_number": "1", "text": "Álpha shall  retain.\n\nBeta\tmay publish!"},
        {"source_row_index": 52491, "ipfs_cid": "cid-beta", "title_number": "4",
         "section_number": "2", "text": "Gamma must inspect. Delta is entitled."}]
    nulls = [{"source_row_index": index, "ipfs_cid": None, "title_number": None,
              "section_number": None, "text": None} for index in range(100, 109)]
    monkeypatch.setattr(contract, "usc_rows", lambda title, **kwargs: deepcopy(nulls if title == "NA" else rows))
    monkeypatch.setattr(helper, "contract_owner", lambda root: contract)
    return tmp_path, contract, plan, rows


def artifacts(root, contract, task_id):
    receipt = json.loads((root / contract.directory(task_id) / "receipt.json").read_bytes())
    return receipt, contract.read_artifacts(root, task_id, receipt)


def test_multirow_section_spans_preserve_every_source_byte_and_stable_ids(seeded):
    root, contract, plan, rows = seeded
    result = helper.materialize(root, "LIRAE-USC-T04")
    assert result["provider_calls"] == 0 and result["completion_authority"] is False
    receipt, data = artifacts(root, contract, "LIRAE-USC-T04")
    contract.validate_uscode(plan["shards"][0], receipt, data)
    sections, spans, entities = [contract.payload(data, label) for label in ["sections", "spans", "entities"]]
    assert [row["text"] for row in sections] == [row["text"] for row in rows]
    assert len(spans) == 2 and len(entities) == 2
    assert receipt["evidence"]["span_granularity"] == "section"
    assert spans[0]["id"] == "usc:us:4:row:17:span:1"
    assert [span["text"] for span in spans] == [row["text"] for row in rows]
    sources = {row["ipfs_cid"]: row["text"] for row in rows}
    for row in spans:
        source = sources[row["source_ipfs_cid"]]
        assert source.encode()[row["byte_start"]:row["byte_end"]] == row["text"].encode()
        assert row["status"] == "uncompiled"
    assert all(row["status"] == "spans" for row in sections)
    assert all(row["admitted"] is row["formalized"] is False for row in sections + spans + entities)
    assert contract.validate(root, "LIRAE-USC-T04")["validated"] is True


def test_exact_retry_is_a_byte_and_mtime_noop(seeded):
    root, contract, _, _ = seeded
    helper.materialize(root, "LIRAE-USC-T04")
    directory = root / contract.directory("LIRAE-USC-T04")
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()}
    helper.materialize(root, "LIRAE-USC-T04")
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()}


def test_conflicting_prior_artifact_is_preserved_and_no_other_output_changes(seeded):
    root, contract, _, _ = seeded
    helper.materialize(root, "LIRAE-USC-T04")
    directory = root / contract.directory("LIRAE-USC-T04")
    conflict = directory / "sections.zip"
    conflict.write_bytes(b"retained conflicting evidence")
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()}
    with pytest.raises(ValueError, match="conflicts"):
        helper.materialize(root, "LIRAE-USC-T04")
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()}


@pytest.mark.parametrize("where", ["directory", "file", "ancestor"])
def test_output_symlinks_cannot_write_outside_task_directory(seeded, tmp_path, where):
    root, contract, _, _ = seeded
    target = root / contract.directory("LIRAE-USC-T04")
    outside = root / "outside"
    outside.mkdir()
    marker = outside / "sections.zip"
    marker.write_bytes(b"untouched")
    if where == "directory":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(outside, target_is_directory=True)
    elif where == "file":
        target.mkdir(parents=True)
        (target / "sections.zip").symlink_to(marker)
    else:
        shutil.rmtree(target.parent)
        target.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="aliases"):
        helper.materialize(root, "LIRAE-USC-T04")
    assert marker.read_bytes() == b"untouched"
    assert sorted(path.name for path in outside.iterdir()) == ["sections.zip"]


def test_nine_null_cid_rows_are_distinct_truthful_abstentions(seeded):
    root, contract, plan, _ = seeded
    helper.materialize(root, "LIRAE-USC-TNA")
    receipt, data = artifacts(root, contract, "LIRAE-USC-TNA")
    contract.validate_uscode(plan["shards"][1], receipt, data)
    rows = contract.payload(data, "sections")
    assert len(rows) == len({row["source_row_index"] for row in rows}) == 9
    assert all(row["ipfs_cid"] is row["text"] is row["source_text_sha256"] is None
               and row["status"] == "abstain" and row["reason"] and row["span_ids"] == [] for row in rows)
    assert contract.payload(data, "spans") == contract.payload(data, "entities") == []


@pytest.mark.parametrize("task_id", ["LIRAE-CONST-AM18", "LIRAE-CONST-AM21"])
def test_real_constitution_owner_inventory_retains_repeal_and_false_flags(seeded, task_id):
    root, contract, _, _ = seeded
    helper.materialize(root, task_id)
    receipt, data = artifacts(root, contract, task_id)
    contract.validate_constitution(root, task_id, receipt, data)
    rows = json.loads(data["spans"])
    assert all(row["roundtrip_ok"] is row["admitted"] is row["formalized"] is False for row in rows)
    if task_id.endswith("AM18"):
        assert any(row["status"] == "inactive" and row["reason"] == "repealed" for row in rows)
    assert receipt["evidence"]["repeal_treated_as_obligation"] is False


@pytest.mark.parametrize("task_id", ["LIRAE-WIDTH-384", "LIRAE-METHOD-01", "LIRAE-USC-UNKNOWN", "../../outside"])
def test_noninventory_or_unplanned_tasks_are_refused(seeded, task_id):
    root, _, _, _ = seeded
    with pytest.raises(ValueError):
        helper.materialize(root, task_id)


def test_zip_is_one_deterministic_json_member_with_no_authority_in_metadata():
    content = helper.raw([{"text": "Exact plaintext", "admitted": False, "formalized": False}])
    archive = helper.zipped_array("spans", content)
    assert archive == helper.zipped_array("spans", content)
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        assert opened.namelist() == ["spans.json"]
        info = opened.infolist()[0]
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert not info.flag_bits & 1
        assert info.compress_type == zipfile.ZIP_DEFLATED
        assert info.extra == info.comment == b""
        assert opened.read(info) == content


def test_changed_pinned_source_and_duplicate_rows_do_not_create_outputs(seeded, monkeypatch):
    root, contract, _, rows = seeded
    monkeypatch.setattr(contract, "usc_rows", lambda title, **kwargs: [rows[0], rows[0]])
    with pytest.raises(ValueError, match="duplicate pinned"):
        helper.materialize(root, "LIRAE-USC-T04")
    assert not (root / contract.directory("LIRAE-USC-T04")).exists()
    path = root / contract.CONSTITUTION
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="retained Constitution"):
        helper.materialize(root, "LIRAE-CONST-AM18")


def test_real_parquet_digest_is_checked_before_reading_any_rows(seeded, monkeypatch):
    root, contract, _, _ = seeded
    actual = load("inventory_materializer_pinned_contract", root / "scripts/ops/legal_ir/legal_ir_supervisor_contract.py")
    monkeypatch.setattr(helper, "contract_owner", lambda path: actual)
    wrong = root / "wrong.parquet"
    wrong.write_bytes(b"different source bytes")
    with pytest.raises(ValueError, match="digest differs"):
        helper.materialize(root, "LIRAE-USC-T04", source_parquet=wrong)
    assert not (root / actual.directory("LIRAE-USC-T04")).exists()
