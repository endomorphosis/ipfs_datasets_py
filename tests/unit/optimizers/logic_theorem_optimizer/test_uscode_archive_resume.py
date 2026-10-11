"""Stopped-parent custody, atomic no-replace clone and bounded continuation."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal.uscode_ingest import inventory_uscode_documents
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_intake as intake
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_source_census as census
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_archive_reconciliation as archive
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_archive_resume as resume


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture(tmp_path,seeded=False):
    rows=[{"ipfs_cid":f"cid-{i}","title_number":"1","section_number":str(i+1),
        "normalized_citation":f"1 U.S.C. {i+1}",
        "text":" ".join(f"The agency shall retain item {i}_{j}." for j in range(n))}
        for i,n in enumerate((7,4,3))]
    docs=[{"entry_cid":r["ipfs_cid"],"legal_id":f"usc:us:1:{r['section_number']}",
        "section":r["section_number"],"text":r["text"],"title":"1","canonical_citation":r["normalized_citation"]} for r in rows]
    spans=inventory_uscode_documents(docs,query="ipfs_uscode",release_id=intake.DEFAULT_RELEASE_ID)["spans"]
    records=[{"record_kind":"span","dataset_id":"","source_span_id":s["source_span_id"],
        "source_sha256":s["span_text_sha256"],"legal_id":s["legal_id"]} for s in spans[::2]]
    meta={"record_kind":"meta","dataset_id":"justicedao/ipfs_uscode","source_span_id":"","source_sha256":"","legal_id":""}
    source,progress=tmp_path/"source.parquet",tmp_path/"progress.parquet"
    pq.write_table(pa.Table.from_pylist(rows),source)
    pq.write_table(pa.Table.from_pylist([meta,*records],schema=pa.schema([(k,pa.string()) for k in meta])),progress)
    options=dict(progress_parquet=str(progress),progress_sha256=sha(progress),progress_revision="a"*40,
        source_parquet=str(source),source_sha256=sha(source),output_directory=str(tmp_path/"parent"),
        max_page_spans=2,memory_mb=256,max_pages=1)
    if seeded:
        seed=tmp_path/"seed"
        census.run_source_census(**{k:v for k,v in options.items() if k in (
            "progress_parquet","progress_sha256","progress_revision","source_parquet","source_sha256")},
            output_directory=str(seed),section_batch_size=1,max_batches=1)
        options["seed_census_directory"]=str(seed)
    parent_report=archive.run_archive_reconciliation(**options)
    parent=Path(options["output_directory"])
    pins=dict(parent_directory=str(parent),expected_parent_database_sha256=sha(parent/"reconciliation.duckdb"),
        expected_parent_manifest_sha256=sha(parent/"manifest.json"),expected_parent_report_sha256=sha(parent/"report.json"))
    options["output_directory"]=str(tmp_path/"clone")
    return pins,options,parent_report


def snapshot(path):
    return {p.name:sha(p) for p in Path(path).iterdir() if p.is_file()}


def clone(pins,options,**extra):
    return resume.clone_archive_generation(**pins,reconciliation_arguments=options,**extra)


def staged(tmp_path):
    return list(tmp_path.glob(".clone.clone-*"))


def test_clone_retains_byte_identical_database_manifest_report_and_parent(tmp_path):
    pins,options,old=fixture(tmp_path,seeded=True)
    before=snapshot(pins["parent_directory"])
    seed_before=snapshot(options["seed_census_directory"])
    receipt=clone(pins,options)
    output=Path(options["output_directory"])
    for name in resume.FILES:
        assert sha(output/name)==before[name]
    assert snapshot(pins["parent_directory"])==before
    assert snapshot(options["seed_census_directory"])==seed_before
    assert receipt["parent_state"]["next_section"]==old["next_section"]
    assert receipt["parent_state"]["next_span"]==old["next_span"]
    assert receipt["parent_state"]["all_occurrence_digest"]==old["accounting"]["all_occurrence_digest"]
    assert receipt["total_staged_file_bytes"]==sum(p.stat().st_size for p in output.iterdir())
    assert json.loads((output/"clone-custody.json").read_text())==receipt
    assert not receipt["models_executed"] and not receipt["proof_authority"]
    assert not staged(tmp_path)


def test_genuine_bounded_resume_extends_clone_without_changing_parent(tmp_path):
    pins,options,old=fixture(tmp_path)
    before=snapshot(pins["parent_directory"])
    report=resume.run_archive_resume(**pins,**{**options,"max_pages":2})
    assert report["accounting"]["source_occurrence_count"]==old["accounting"]["source_occurrence_count"]+4
    assert report["next_section"]==0 and report["next_span"]==6
    assert snapshot(pins["parent_directory"])==before
    receipt=json.loads((Path(options["output_directory"])/"clone-custody.json").read_text())
    assert receipt["parent_state"]["next_span"]==2
    cold=archive.run_archive_reconciliation(**{**options,"output_directory":str(tmp_path/"cold"),"max_pages":3})
    assert report["accounting"]==cold["accounting"]
    assert report["ledger_disposition_counts"]==cold["ledger_disposition_counts"]
    def target_rows(directory):
        with duckdb.connect(str(Path(directory)/"reconciliation.duckdb"),read_only=True) as db:
            return db.execute("SELECT * FROM target_occurrences ORDER BY occurrence_id").fetchall()
    assert target_rows(options["output_directory"])==target_rows(tmp_path/"cold")


@pytest.mark.parametrize("pin",["expected_parent_database_sha256","expected_parent_manifest_sha256","expected_parent_report_sha256"])
def test_wrong_parent_expected_hash_rejects_before_destination_mutation(tmp_path,pin):
    pins,options,_=fixture(tmp_path)
    with pytest.raises(intake.SpanIntakeError,match="SHA-256 differs"):
        clone({**pins,pin:"0"*64},options)
    assert not Path(options["output_directory"]).exists() and not staged(tmp_path)


def test_parent_writer_and_unreconciled_wal_are_refused(tmp_path):
    pins,options,_=fixture(tmp_path)
    parent=Path(pins["parent_directory"])
    before=snapshot(parent)
    with census._writer(parent):
        with pytest.raises(intake.SpanIntakeError,match="still has a writer"):
            clone(pins,options)
    (parent/"reconciliation.duckdb.wal").write_bytes(b"unreconciled")
    with pytest.raises(intake.SpanIntakeError,match="WAL"):
        clone(pins,options)
    (parent/"reconciliation.duckdb.wal").unlink()
    assert snapshot(parent)==before and not Path(options["output_directory"]).exists()


@pytest.mark.parametrize("mutation",["report_cursor","state_accounting","target_rows","ledger_counts","completion"])
def test_coherently_hashed_tampered_parent_consistency_is_refused(tmp_path,mutation):
    pins,options,_=fixture(tmp_path)
    parent=Path(pins["parent_directory"])
    report=json.loads((parent/"report.json").read_text())
    if mutation=="report_cursor":
        report["next_span"]+=1
    elif mutation=="state_accounting":
        with duckdb.connect(str(parent/"reconciliation.duckdb")) as db:
            state=json.loads(db.execute("SELECT value FROM reconciliation_state WHERE key='accounting'").fetchone()[0])
            state["outside_target_occurrence_count"]+=1
            db.execute("UPDATE reconciliation_state SET value=? WHERE key='accounting'",[json.dumps(state)])
    elif mutation=="target_rows":
        with duckdb.connect(str(parent/"reconciliation.duckdb")) as db:
            db.execute("DELETE FROM target_occurrences")
    elif mutation=="ledger_counts":
        report["ledger_disposition_counts"]["matched"]-=1
        report["ledger_disposition_counts"]["pending_source_scan"]+=1
    else:
        report["complete_source_scan"]=True
        with duckdb.connect(str(parent/"reconciliation.duckdb")) as db:
            db.execute("UPDATE reconciliation_state SET value='true' WHERE key='done'")
    (parent/"report.json").write_text(json.dumps(report))
    pins.update(expected_parent_database_sha256=sha(parent/"reconciliation.duckdb"),expected_parent_report_sha256=sha(parent/"report.json"))
    with pytest.raises(intake.SpanIntakeError):
        clone(pins,options)
    assert not Path(options["output_directory"]).exists() and not staged(tmp_path)


@pytest.mark.parametrize("changed",["max_page_spans","progress_revision","source_revision","seed_census_directory"])
def test_changed_generation_or_seed_profile_refuses_before_copy(tmp_path,changed):
    pins,options,_=fixture(tmp_path,seeded=True)
    bad={**options,changed:None if changed=="seed_census_directory" else 3 if changed=="max_page_spans" else "b"*40}
    with pytest.raises(intake.SpanIntakeError,match="binding differs"):
        clone(pins,bad)
    assert not Path(options["output_directory"]).exists() and not staged(tmp_path)


def test_changed_live_source_is_refused_against_manifest(tmp_path):
    pins,options,_=fixture(tmp_path)
    source=Path(options["source_parquet"])
    source.write_bytes(source.read_bytes()+b"changed")
    with pytest.raises(intake.SpanIntakeError,match="SHA-256 differs"):
        clone(pins,options)
    assert not Path(options["output_directory"]).exists()


def test_existing_destination_and_parent_descendant_are_refused(tmp_path):
    pins,options,_=fixture(tmp_path)
    output=Path(options["output_directory"]);output.mkdir()
    sentinel=output/"foreign";sentinel.write_text("keep")
    with pytest.raises(intake.SpanIntakeError,match="must be absent"):
        clone(pins,options)
    assert sentinel.read_text()=="keep"
    nested={**options,"output_directory":str(Path(pins["parent_directory"])/"child")}
    with pytest.raises(intake.SpanIntakeError,match="frozen parent"):
        clone(pins,nested)


def test_competing_empty_foreign_destination_cannot_be_replaced(tmp_path):
    pins,options,_=fixture(tmp_path)
    identity=[]
    def compete(stage,destination):
        destination.mkdir()
        identity.append(destination.stat().st_ino)
    with pytest.raises(intake.SpanIntakeError,match="already exists"):
        clone(pins,options,_before_publish=compete)
    output=Path(options["output_directory"])
    assert output.stat().st_ino==identity[0] and list(output.iterdir())==[]
    assert not staged(tmp_path)


@pytest.mark.parametrize("stage",["copy","before_publish"])
def test_interrupted_staging_never_publishes_a_runnable_clone(tmp_path,stage):
    pins,options,_=fixture(tmp_path)
    def interrupt(*args):
        raise RuntimeError("interrupted")
    hook={"_after_copy" if stage=="copy" else "_before_publish":interrupt}
    with pytest.raises(RuntimeError,match="interrupted"):
        clone(pins,options,**hook)
    assert not Path(options["output_directory"]).exists() and not staged(tmp_path)


def test_staged_copy_corruption_is_detected_before_publication(tmp_path):
    pins,options,_=fixture(tmp_path)
    def corrupt(name,stage):
        if name=="reconciliation.duckdb":
            with (stage/name).open("r+b") as stream:
                stream.seek(32);stream.write(b"corrupt")
    with pytest.raises(intake.SpanIntakeError,match="SHA-256 differs"):
        clone(pins,options,_after_copy=corrupt)
    assert not Path(options["output_directory"]).exists() and not staged(tmp_path)


def test_parent_changes_during_copy_are_detected_without_publishing(tmp_path):
    pins,options,_=fixture(tmp_path)
    def mutate(stage,destination):
        p=Path(pins["parent_directory"])/"report.json"
        p.write_bytes(p.read_bytes()+b" ")
    with pytest.raises(intake.SpanIntakeError,match="changed during intake"):
        clone(pins,options,_before_publish=mutate)
    assert not Path(options["output_directory"]).exists() and not staged(tmp_path)


def test_receipt_bytes_are_inside_clone_budget(tmp_path):
    pins,options,_=fixture(tmp_path)
    parent=Path(pins["parent_directory"])
    files=sum((parent/n).stat().st_size for n in resume.FILES)
    with pytest.raises(intake.SpanIntakeError,match="custody receipt exceed"):
        clone(pins,options,max_clone_bytes=files)
    assert not Path(options["output_directory"]).exists() and not staged(tmp_path)


@pytest.mark.parametrize("payload",[b"short",b"12345678excess",b"12345678"])
def test_copy_length_bound_holds_on_truncation_growth_and_exact_input(payload):
    incoming,outgoing=io.BytesIO(payload),io.BytesIO()
    if len(payload)!=8:
        with pytest.raises(intake.SpanIntakeError,match="shorter|grew"):
            resume._copy_exact(incoming,outgoing,8)
    else:
        resume._copy_exact(incoming,outgoing,8)
    assert len(outgoing.getvalue())<=8
    assert outgoing.getvalue()==payload[:8]


def test_postpublication_resume_failure_retains_legitimate_clone(tmp_path,monkeypatch):
    pins,options,_=fixture(tmp_path)
    before=snapshot(pins["parent_directory"])
    original=archive.run_archive_reconciliation
    def refuse(**kwargs):
        raise intake.SpanIntakeError("later resume refused")
    refuse.__signature__=__import__('inspect').signature(original)
    monkeypatch.setattr(archive,"run_archive_reconciliation",refuse)
    with pytest.raises(intake.SpanIntakeError,match="later resume refused"):
        resume.run_archive_resume(**pins,**options)
    output=Path(options["output_directory"])
    assert sha(output/"reconciliation.duckdb")==before["reconciliation.duckdb"]
    assert (output/"clone-custody.json").is_file()
    assert snapshot(pins["parent_directory"])==before and not staged(tmp_path)


@pytest.mark.parametrize("alias",["parent","source","destination_parent"])
def test_symlink_path_aliases_are_refused(tmp_path,alias):
    pins,options,_=fixture(tmp_path)
    link=tmp_path/"alias"
    if alias=="parent":
        link.symlink_to(pins["parent_directory"],target_is_directory=True)
        pins["parent_directory"]=str(link)
    elif alias=="source":
        link.symlink_to(options["source_parquet"])
        options["source_parquet"]=str(link)
    else:
        link.symlink_to(tmp_path,target_is_directory=True)
        options["output_directory"]=str(link/"clone")
    with pytest.raises(intake.SpanIntakeError,match="canonical paths"):
        clone(pins,options)
