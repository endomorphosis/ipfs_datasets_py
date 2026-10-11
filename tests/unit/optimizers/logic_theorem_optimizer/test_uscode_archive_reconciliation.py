"""Archived-target scope, exact seed custody and atomic section/span resume."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_intake as intake
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_source_census as old
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_archive_reconciliation as reconciliation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import USCodeParquetRecord
from ipfs_datasets_py.logic.autoformal.uscode_ingest import inventory_uscode_documents


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs(tmp_path,section_sizes=(7,3,2),select=None,duplicate=False,fallback=False,metadata=False):
    tmp_path.mkdir(parents=True,exist_ok=True)
    source_rows = [{"ipfs_cid":f"cid-{i}","title_number":"1","section_number":str(i+1),
        "text":" ".join(f"The agency shall retain item {i}_{j}." for j in range(size)),
        "normalized_citation":f"1 U.S.C. {i+1}"} for i,size in enumerate(section_sizes)]
    if duplicate:
        source_rows[1] = dict(source_rows[0])
    if fallback:
        source_rows[0]["text"] = "  "
    docs=[]
    for raw in source_rows:
        record=USCodeParquetRecord.from_row(raw)
        docs.append({"entry_cid":record.ipfs_cid,"legal_id":f"usc:us:1:{record.section_number}",
            "section":record.section_number,"text":record.text,"title":"1","canonical_citation":record.citation})
    spans=[]
    for offset in range(0,len(docs),64):
        spans.extend(inventory_uscode_documents(docs[offset:offset+64],query="ipfs_uscode",
            release_id=intake.DEFAULT_RELEASE_ID)["spans"])
    archive=[{"record_kind":"span","dataset_id":"","source_span_id":r["source_span_id"],
        "source_sha256":r["span_text_sha256"],"legal_id":r["legal_id"]} for r in spans]
    if select:
        archive=select(archive)
    meta={"record_kind":"meta","dataset_id":"justicedao/ipfs_uscode","source_span_id":"","source_sha256":"","legal_id":""}
    progress=tmp_path/"progress.parquet"
    pq.write_table(pa.Table.from_pylist([meta,*archive],schema=pa.schema([(k,pa.string()) for k in meta])),progress)
    if metadata:
        source_rows.append({k:None for k in source_rows[0]})
    source=tmp_path/"source.parquet"
    pq.write_table(pa.Table.from_pylist(source_rows),source)
    return dict(progress_parquet=str(progress),progress_sha256=sha(progress),progress_revision="a"*40,
        source_parquet=str(source),source_sha256=sha(source),output_directory=str(tmp_path/"result")),spans


def state(directory):
    with duckdb.connect(str(Path(directory)/"reconciliation.duckdb"),read_only=True) as db:
        return dict(db.execute("SELECT key,value FROM reconciliation_state").fetchall()),db.execute("SELECT count(*) FROM target_occurrences").fetchone()[0]


def make_seed(args,tmp_path,sections=2):
    options={k:v for k,v in args.items() if k!="output_directory"}
    directory=tmp_path/"old-seed"
    report=old.run_source_census(**options,output_directory=str(directory),section_batch_size=1,max_batches=sections)
    return directory,report


def test_all_archive_rows_and_outside_target_scope_are_explicit(tmp_path):
    args,spans=inputs(tmp_path,select=lambda rows:rows[::2],metadata=True)
    report=reconciliation.run_archive_reconciliation(**args,max_page_spans=2,example_limit=2)
    counts=report["accounting"]
    assert report["complete_source_scan"] and not report["complete_all_source_occurrence_inventory"]
    assert "archived-targets" in report["inventory_scope"]
    assert counts["source_occurrence_count"]==12
    assert counts["target_occurrence_count"]==counts["outside_target_occurrence_count"]==6
    assert len(counts["outside_target_examples"])==2
    assert counts["empty_section_count"]==1
    assert report["ledger_row_count"]==7 and report["archived_span_record_count"]==6
    assert report["ledger_disposition_counts"]=={"excluded_nonspan":1,"matched":6}
    assert report["next_section"]==4 and report["next_span"]==0
    assert not report["training_executed"] and not report["inference_executed"] and not report["proof_authority"]
    assert not report["semantic_reconstruction_measured"]
    assert report["kernel_maxrss"]["bytes"]>0
    with duckdb.connect(str(Path(args["output_directory"])/"reconciliation.duckdb"),read_only=True) as db:
        assert set(r[0] for r in db.execute("SHOW TABLES").fetchall())=={"reconciliation_state","target_occurrences"}
        assert db.execute("SELECT count(*) FROM target_occurrences").fetchone()[0]==6
    assert all("text" not in r for r in counts["outside_target_examples"])


def test_resume_inside_one_section_matches_fresh_digest_and_counts(tmp_path):
    args,_=inputs(tmp_path,section_sizes=(11,3))
    first=reconciliation.run_archive_reconciliation(**args,max_page_spans=3,max_pages=1)
    assert (first["next_section"],first["next_span"])==(0,3)
    assert first["accounting"]["source_occurrence_count"]==3
    second=reconciliation.run_archive_reconciliation(**args,max_page_spans=3,max_pages=1)
    assert (second["next_section"],second["next_span"])==(0,6)
    resumed=reconciliation.run_archive_reconciliation(**args,max_page_spans=3)
    fresh=reconciliation.run_archive_reconciliation(**{**args,"output_directory":str(tmp_path/"fresh")},max_page_spans=7)
    assert resumed["accounting"]==fresh["accounting"]
    assert resumed["ledger_disposition_counts"]==fresh["ledger_disposition_counts"]
    again=reconciliation.run_archive_reconciliation(**args,max_page_spans=3)
    assert again["accounting"]==resumed["accounting"]


def test_page_transaction_failure_retains_cursor_counts_digest_and_rows(tmp_path):
    args,_=inputs(tmp_path)
    def fail(page):
        raise RuntimeError("transaction interrupted")
    with pytest.raises(RuntimeError,match="interrupted"):
        reconciliation.run_archive_reconciliation(**args,max_page_spans=3,_before_commit=fail)
    saved,count=state(args["output_directory"])
    assert count==0 and saved["next_section"]==saved["next_span"]=="0"
    accounting=json.loads(saved["accounting"])
    assert accounting["source_occurrence_count"]==0 and accounting["all_occurrence_digest"]=="0"*64
    assert reconciliation.run_archive_reconciliation(**args,max_page_spans=3)["complete_source_scan"]


def test_conflicts_invalid_archive_and_mismatches_remain_target_occurrences(tmp_path):
    def transform(rows):
        return [rows[0],{**rows[0],"source_sha256":"c"*64},
            {**rows[1],"source_sha256":None},{**rows[2],"source_sha256":"b"*64},
            {**rows[3],"legal_id":"usc:us:1:999"}]
    args,_=inputs(tmp_path,section_sizes=(5,),select=transform)
    report=reconciliation.run_archive_reconciliation(**args,max_page_spans=2)
    assert report["accounting"]["target_occurrence_count"]==4
    assert report["accounting"]["outside_target_occurrence_count"]==1
    assert report["accounting"]["target_dispositions"]=={
        "ledger_identity_conflict":1,"invalid_ledger_identity":1,"source_hash_mismatch":1,"legal_id_mismatch":1}
    assert report["archived_conflicting_id_count"]==1
    assert report["ledger_disposition_counts"]["ledger_identity_conflict"]==2


def test_duplicate_physical_sources_have_distinct_occurrence_keys(tmp_path):
    args,_=inputs(tmp_path,section_sizes=(2,2),duplicate=True)
    report=reconciliation.run_archive_reconciliation(**args,max_page_spans=1)
    assert report["accounting"]["source_occurrence_count"]==4
    with duckdb.connect(str(Path(args["output_directory"])/"reconciliation.duckdb"),read_only=True) as db:
        assert db.execute("SELECT count(DISTINCT occurrence_id),count(DISTINCT source_section_offset) FROM target_occurrences").fetchone()==(4,2)


def test_legacy_citation_fallback_has_explicit_provenance(tmp_path):
    args,spans=inputs(tmp_path,section_sizes=(1,2),fallback=True)
    report=reconciliation.run_archive_reconciliation(**args,max_page_spans=1)
    assert report["accounting"]["source_text_origins"]["legacy_citation_fallback"]>=1
    with duckdb.connect(str(Path(args["output_directory"])/"reconciliation.duckdb"),read_only=True) as db:
        assert db.execute("SELECT bool_and(NOT raw_source_text_present) FROM target_occurrences WHERE source_text_origin='legacy_citation_fallback'").fetchone()[0]


def test_verified_seed_import_matches_full_replay_and_preserves_old_files(tmp_path):
    args,_=inputs(tmp_path,select=lambda rows:rows[::2])
    seed,seed_report=make_seed(args,tmp_path,sections=2)
    old_hashes={p.name:sha(p) for p in seed.iterdir() if p.is_file()}
    seeded=reconciliation.run_archive_reconciliation(**args,max_page_spans=2,seed_census_directory=str(seed),max_pages=1)
    assert seeded["seed_applied"] and seeded["seed"]["source_occurrence_count"]==10
    assert seeded["accounting"]["source_occurrence_count"]==12
    assert seeded["accounting"]["outside_target_occurrence_count"]==6
    seeded=reconciliation.run_archive_reconciliation(**args,max_page_spans=2,seed_census_directory=str(seed))
    replay=reconciliation.run_archive_reconciliation(**{**args,"output_directory":str(tmp_path/"replay")},max_page_spans=4)
    assert seeded["accounting"]==replay["accounting"]
    assert old_hashes=={p.name:sha(p) for p in seed.iterdir() if p.is_file()}


def test_seed_import_rollback_cannot_double_count_prefix(tmp_path):
    args,_=inputs(tmp_path)
    seed,_=make_seed(args,tmp_path)
    def interrupt(page):
        if page.get("event")=="verified_seed_import":
            raise RuntimeError("seed interrupted")
    with pytest.raises(RuntimeError,match="seed interrupted"):
        reconciliation.run_archive_reconciliation(**args,seed_census_directory=str(seed),max_page_spans=2,_before_commit=interrupt)
    saved,count=state(args["output_directory"])
    assert count==0 and saved["next_section"]==saved["next_span"]=="0"
    assert saved["seed_applied"]=="false" and json.loads(saved["accounting"])["source_occurrence_count"]==0
    report=reconciliation.run_archive_reconciliation(**args,seed_census_directory=str(seed),max_page_spans=2)
    assert report["accounting"]["source_occurrence_count"]==12


def test_seed_wrong_occurrence_binding_refused_before_import(tmp_path):
    args,_=inputs(tmp_path)
    seed,_=make_seed(args,tmp_path)
    with duckdb.connect(str(seed/"census.duckdb")) as db:
        db.execute("UPDATE source_occurrences SET utf8_bytes=utf8_bytes+1")
    with pytest.raises(intake.SpanIntakeError,match="occurrence binding differs"):
        reconciliation.run_archive_reconciliation(**args,seed_census_directory=str(seed),max_page_spans=2)
    saved,count=state(args["output_directory"])
    assert count==0 and saved["seed_applied"]=="false"


@pytest.mark.parametrize("fault",["wal","code","report","cursor","cursor_inside","completion"])
def test_seed_wal_code_and_report_custody_refused(tmp_path,fault):
    args,_=inputs(tmp_path)
    seed,_=make_seed(args,tmp_path)
    if fault=="wal":
        (seed/"census.duckdb.wal").write_bytes(b"unreconciled")
    elif fault=="code":
        path=seed/"manifest.json";manifest=json.loads(path.read_text())
        manifest["source_code_sha256"]["intake"]="0"*64
        path.write_text(json.dumps(manifest))
    elif fault=="report":
        path=seed/"report.json";report=json.loads(path.read_text())
        report["statistics"]["source_occurrence_count"]+=1
        path.write_text(json.dumps(report))
    elif fault=="completion":
        with duckdb.connect(str(seed/"census.duckdb")) as db:
            db.execute("UPDATE census_state SET value='true' WHERE key='done'")
        path=seed/"report.json";report=json.loads(path.read_text())
        report["complete_source_scan"]=True
        path.write_text(json.dumps(report))
    else:
        cursor="1" if fault=="cursor_inside" else "999"
        with duckdb.connect(str(seed/"census.duckdb")) as db:
            db.execute("UPDATE census_state SET value=? WHERE key='next_section'",[cursor])
        path=seed/"report.json";report=json.loads(path.read_text())
        report["statistics"]["next_section"]=int(cursor)
        path.write_text(json.dumps(report))
    with pytest.raises(intake.SpanIntakeError):
        reconciliation.run_archive_reconciliation(**args,seed_census_directory=str(seed))


def test_seed_active_writer_is_refused_without_modification(tmp_path):
    args,_=inputs(tmp_path)
    seed,_=make_seed(args,tmp_path)
    before=sha(seed/"census.duckdb")
    with old._writer(seed):
        with pytest.raises(intake.SpanIntakeError,match="still has a writer"):
            reconciliation.run_archive_reconciliation(**args,seed_census_directory=str(seed))
    assert sha(seed/"census.duckdb")==before


def test_changed_paging_pins_and_seed_lineage_refused(tmp_path):
    args,_=inputs(tmp_path)
    seed,_=make_seed(args,tmp_path)
    reconciliation.run_archive_reconciliation(**args,max_page_spans=2,max_pages=1,seed_census_directory=str(seed))
    with pytest.raises(intake.SpanIntakeError,match="pins differ"):
        reconciliation.run_archive_reconciliation(**args,max_page_spans=3,seed_census_directory=str(seed))
    with pytest.raises(intake.SpanIntakeError,match="pins differ"):
        reconciliation.run_archive_reconciliation(**args,max_page_spans=2)


def test_candidate_bound_does_not_advance_source_cursor(tmp_path):
    args,_=inputs(tmp_path)
    with pytest.raises(intake.SpanIntakeError,match="byte bound"):
        reconciliation.run_archive_reconciliation(**args,max_page_bytes=64)
    saved,count=state(args["output_directory"])
    assert count==0 and saved["next_section"]==saved["next_span"]=="0"


def test_foreign_database_and_concurrent_writer_are_refused(tmp_path):
    args,_=inputs(tmp_path)
    directory=Path(args["output_directory"]);directory.mkdir()
    with duckdb.connect(str(directory/"reconciliation.duckdb")) as db:
        db.execute("CREATE TABLE foreign_data (v INTEGER)")
    with pytest.raises(intake.SpanIntakeError,match="without this reconciliation manifest"):
        reconciliation.run_archive_reconciliation(**args)
    (directory/"reconciliation.duckdb").unlink()
    with old._writer(directory):
        with pytest.raises(intake.SpanIntakeError,match="already has a writer"):
            reconciliation.run_archive_reconciliation(**args)
