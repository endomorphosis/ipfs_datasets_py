"""Metadata-only custody and independently generated counter controls."""
from __future__ import annotations
import fcntl
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal.uscode_ingest import inventory_uscode_documents
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_archive_reconciliation as archive
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_identity_recovery as recovery


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, value):
    p.write_text(json.dumps(value, sort_keys=True) + "\n")


def pin(p):
    return dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size)


def prepare(tmp_path, *, ambiguous=False, extra_documents=0):
    parent=tmp_path/"stopped"
    parent.mkdir()
    (parent/"writer.lock").touch()
    documents=[dict(entry_cid="cid-a",legal_id="usc:us:1:1",title="1",section="1",
        canonical_citation="1 U.S.C. 1",text="The agency shall keep records. The agency may publish notices."),
        dict(entry_cid="cid-b",legal_id="usc:us:1:2",title="1",section="2",
        canonical_citation="1 U.S.C. 2",text="The court shall preserve records.")]
    if ambiguous:
        documents.append(dict(documents[1]))
    documents.extend(dict(entry_cid=f"cid-extra-{n}",legal_id=f"usc:us:1:{n+3}",title="1",section=str(n+3),
        canonical_citation=f"1 U.S.C. {n+3}",text="The agency shall retain the record.") for n in range(extra_documents))
    release=archive.intake.DEFAULT_RELEASE_ID
    # Independent original inventory supplies both IDs; no recovery hash helper.
    historical=inventory_uscode_documents(documents,query="ipfs_uscode",release_id=release)["spans"]
    alternate=inventory_uscode_documents([documents[1]],query="ipfs_uscode",release_id=release)["spans"][0]
    rows=[]
    local_counts={}
    for n,span in enumerate(historical):
        section=span["document_ordinal"]
        local=local_counts.get(section,0)
        local_counts[section]=local+1
        rows.append(dict(occurrence_id=hashlib.sha256(f"physical-{section}-{local}".encode()).digest(),
            source_span_id=span["source_span_id"],source_sha256=span["span_text_sha256"],legal_id=span["legal_id"],
            entry_cid=span["entry_cid"],title=span["title"],section=span["section"],citation=span["canonical_citation"],
            source_section_offset=section,historical_document_batch_index=0,historical_span_ordinal=n,
            utf8_bytes=len(span["text"].encode()),unicode_characters=len(span["text"]),token_count=None,
            byte_cohort="le_512",token_cohort="unmeasured",source_join_disposition="matched",
            source_section_span_ordinal=local,source_text_origin="normalized_source_text",raw_source_text_present=True))
    inputs=tmp_path/"metadata-inputs"
    inputs.mkdir()
    progress=inputs/"progress.parquet"
    ledger=[dict(record_kind="span",dataset_id="justicedao/ipfs_uscode",source_span_id=r["source_span_id"],
        source_sha256=r["source_sha256"],legal_id=r["legal_id"]) for r in rows]
    ledger.append(dict(record_kind="span",dataset_id="justicedao/ipfs_uscode",source_span_id=alternate["source_span_id"],
        source_sha256=alternate["span_text_sha256"],legal_id=alternate["legal_id"]))
    ledger.append(dict(record_kind="meta",dataset_id="justicedao/ipfs_uscode",source_span_id="",source_sha256="",legal_id=""))
    pq.write_table(pa.Table.from_pylist(ledger),progress)
    source=dict(path=str(tmp_path/"original-source-not-present.parquet"),bytes=123,sha256="a"*64,
        revision=archive.intake.SOURCE_REVISION,release_id=release,repository_id=archive.intake.SOURCE_REPOSITORY)
    manifest=dict(schema=archive.SCHEMA,identity_reconstruction=recovery.PROFILE,inventory_scope=archive.SCOPE,
        source=source,progress=pin(progress),source_code_sha256=archive._pins(),seed=None)
    accounting=dict(target_occurrence_count=len(rows),outside_target_occurrence_count=11,
        source_occurrence_count=len(rows)+11,target_dispositions={"matched":len(rows)},
        all_occurrence_digest="1"*64,outside_target_digest="2"*64)
    report=dict(schema=archive.SCHEMA,manifest_sha256=recovery._digest(manifest),inventory_scope=archive.SCOPE,
        complete_source_scan=True,complete_all_source_occurrence_inventory=False,next_section=len(documents),next_span=0,
        seed_applied=False,seed=None,accounting=accounting,persisted_target_occurrences=len(rows),
        distinct_target_span_id_count=len(rows),ledger_row_count=len(ledger),archived_span_record_count=len(ledger)-1,
        distinct_archived_span_id_count=len(ledger)-1,ledger_disposition_counts={"matched":len(rows),"unresolved_source":1,"excluded_nonspan":1})
    for key in ("inference_executed","training_executed","semantic_reconstruction_measured","proof_authority","token_counts_measured","admitted","formalized"):
        report[key]=False
    dbpath=parent/"reconciliation.duckdb"
    db=duckdb.connect(str(dbpath))
    db.execute("CREATE TABLE reconciliation_state(key VARCHAR PRIMARY KEY,value VARCHAR)")
    db.executemany("INSERT INTO reconciliation_state VALUES (?,?)",[("done","true"),("next_section",str(len(documents))),
        ("next_span","0"),("seed_applied","false"),("accounting",json.dumps(accounting))])
    db.execute("CREATE TABLE target_occurrences (occurrence_id BLOB PRIMARY KEY,source_span_id VARCHAR,source_sha256 VARCHAR,legal_id VARCHAR,entry_cid VARCHAR,title VARCHAR,section VARCHAR,citation VARCHAR,source_section_offset BIGINT,historical_document_batch_index BIGINT,historical_span_ordinal BIGINT,utf8_bytes BIGINT,unicode_characters BIGINT,token_count BIGINT,byte_cohort VARCHAR,token_cohort VARCHAR,source_join_disposition VARCHAR,source_section_span_ordinal BIGINT,source_text_origin VARCHAR,raw_source_text_present BOOLEAN)")
    columns=archive.OLD_COLUMNS+archive.EXTRA_COLUMNS
    db.executemany("INSERT INTO target_occurrences VALUES ("+",".join("?" for _ in columns)+")",[[r[k] for k in columns] for r in rows])
    db.close()
    write(parent/"manifest.json",manifest)
    write(parent/"report.json",report)
    review=inputs/"review.json"
    (tmp_path/"outputs").mkdir()
    ctx=dict(parent=parent,database=dbpath,progress=progress,review=review,manifest=manifest,report=report,
        ledger=ledger,rows=rows,expected_alternate_id=alternate["source_span_id"],destination=tmp_path/"outputs/result")
    refresh(ctx)
    return ctx


def refresh(ctx, *, reviewer=None):
    parent=ctx["parent"]
    v=dict(schema=recovery.REVIEW_SCHEMA,passed=True,completed=True,findings=[],checks=[dict(id="synthetic-custody-control",passed=True)],
        actual_receipt_pins={"results/"+p.name:pin(p) for p in (ctx["database"],parent/"manifest.json",parent/"report.json")},
        input_pins={"progress":pin(ctx["progress"]),"source":ctx["manifest"]["source"]},
        code_pins={k:dict(sha256=s) for k,s in archive._pins().items()},
        independently_rebuilt_final_accounting=ctx["report"]["accounting"],
        final_cursor=[ctx["report"]["next_section"],ctx["report"]["next_span"]])
    if reviewer:
        reviewer(v)
    write(ctx["review"],v)
    ctx["arguments"]=dict(database_path=str(ctx["database"]),expected_database_sha256=sha(ctx["database"]),
        manifest_path=str(parent/"manifest.json"),expected_manifest_sha256=sha(parent/"manifest.json"),
        report_path=str(parent/"report.json"),expected_report_sha256=sha(parent/"report.json"),
        progress_parquet=str(ctx["progress"]),expected_progress_sha256=sha(ctx["progress"]),
        accepted_review_path=str(ctx["review"]),expected_accepted_review_sha256=sha(ctx["review"]),output_directory=str(ctx["destination"]))


def refuse(ctx, match, **extra):
    before=sha(ctx["database"])
    with pytest.raises((recovery.IdentityRecoveryError,OSError),match=match):
        recovery.run_identity_diagnosis(**(ctx["arguments"]|extra))
    assert sha(ctx["database"])==before
    assert not ctx["destination"].exists()
    assert not list(ctx["destination"].parent.glob(".identity-diagnosis-*"))


def test_independent_reference_counter_reset_and_no_original_source(tmp_path):
    ctx=prepare(tmp_path)
    before={p:sha(p) for p in (ctx["database"],ctx["progress"],ctx["parent"]/"manifest.json",ctx["parent"]/"report.json")}
    report=recovery.run_identity_diagnosis(**ctx["arguments"])
    assert report["baseline_verified_occurrences"]==3
    assert report["elapsed_seconds"]>0
    assert report["process_memory"]["bytes"]>0
    assert report["process_memory"]["native_unit"]=="KiB"
    assert report["counts"]["candidate_pairs"]==1
    assert report["counts"]["retained_subset_singleton_archived_ids"]==1
    candidate=pq.read_table(ctx["destination"]/"candidates.parquet").to_pylist()
    assert candidate[0]["hypothesis_span_id"]==ctx["expected_alternate_id"]
    assert candidate[0]["generated_span_id"]==ctx["rows"][2]["source_span_id"]
    assert candidate[0]["source_section_span_ordinal"]==0
    assert candidate[0]["historical_span_ordinal"]==2
    assert not Path(ctx["manifest"]["source"]["path"]).exists()
    assert all(sha(p)==h for p,h in before.items())
    for key in ("original_source_read","models_loaded","tokenizers_loaded","aliases_created","original_producer_recipe_authenticated",
            "full_source_uniqueness_verified","embedding_reuse_qualified","teacher_qualified","training_admitted","semantic_gold",
            "semantic_fidelity_qualified","proof_authority"):
        assert report[key] is False


def test_duplicate_physical_occurrences_remain_ambiguous(tmp_path):
    ctx=prepare(tmp_path,ambiguous=True)
    report=recovery.run_identity_diagnosis(**ctx["arguments"])
    assert report["counts"]["candidate_pairs"]==2
    assert report["counts"]["candidate_physical_occurrences"]==2
    assert report["counts"]["candidate_distinct_archived_ids"]==1
    assert report["counts"]["retained_subset_ambiguous_archived_ids"]==1
    assert report["counts"]["retained_subset_singleton_archived_ids"]==0
    assert report["full_source_uniqueness_verified"] is False


def test_original_connection_batches_survive_hypothesis_inserts(tmp_path):
    ctx=prepare(tmp_path,extra_documents=520)
    report=recovery.run_identity_diagnosis(**ctx["arguments"])
    assert report["baseline_verified_occurrences"]==523
    assert report["counts"]["candidate_pairs"]==1
    assert report["counts"]["changed_ordinal_retained_rows"]==521


def test_zero_matches_do_not_erase_unresolved_ids(tmp_path):
    ctx=prepare(tmp_path)
    ctx["ledger"][-2]["source_span_id"]="uscode-span-"+"c"*64
    pq.write_table(pa.Table.from_pylist(ctx["ledger"]),ctx["progress"])
    ctx["manifest"]["progress"]=pin(ctx["progress"])
    write(ctx["parent"]/"manifest.json",ctx["manifest"])
    ctx["report"]["manifest_sha256"]=recovery._digest(ctx["manifest"])
    write(ctx["parent"]/"report.json",ctx["report"])
    refresh(ctx)
    report=recovery.run_identity_diagnosis(**ctx["arguments"])
    assert report["counts"]["candidate_pairs"]==0
    assert report["unresolved_ids_without_retained_candidate"]==1
    assert pq.read_table(ctx["destination"]/"candidates.parquet").num_rows==0


def test_all_baselines_gate_every_alternate_hash(tmp_path,monkeypatch):
    ctx=prepare(tmp_path)
    db=duckdb.connect(str(ctx["database"]))
    db.execute("UPDATE target_occurrences SET historical_span_ordinal=historical_span_ordinal+1 WHERE source_section_offset=1")
    db.close()
    refresh(ctx)
    monkeypatch.setattr(recovery,"_hypothesis_id",lambda *args:pytest.fail("alternate hash invoked before all baselines"))
    refuse(ctx,"baseline ID")


@pytest.mark.parametrize("name",["database","manifest","report","progress","accepted_review"])
def test_explicit_input_pins_refuse(tmp_path,name):
    ctx=prepare(tmp_path)
    refuse(ctx,"SHA-256 differs",**{"expected_"+name+"_sha256":"0"*64})


@pytest.mark.parametrize("mutation",[
    lambda v:v.update(passed=False),lambda v:v.update(completed=False),lambda v:v.update(findings=["unresolved"]),
    lambda v:v["checks"][0].update(passed=False),lambda v:v["actual_receipt_pins"]["results/report.json"].update(sha256="0"*64),
    lambda v:v["input_pins"]["progress"].update(sha256="0"*64),lambda v:v.update(final_cursor=[1,0])])
def test_review_acceptance_and_binding_refusal(tmp_path,mutation):
    ctx=prepare(tmp_path)
    refresh(ctx,reviewer=mutation)
    refuse(ctx,"review|checks|binding")


@pytest.mark.parametrize("conflicting",[False,True])
def test_duplicate_archive_ids_refuse_even_with_repin(tmp_path,conflicting):
    ctx=prepare(tmp_path)
    row=dict(ctx["ledger"][0])
    if conflicting:row["source_sha256"]="e"*64
    ctx["ledger"].append(row)
    pq.write_table(pa.Table.from_pylist(ctx["ledger"]),ctx["progress"])
    ctx["manifest"]["progress"]=pin(ctx["progress"])
    write(ctx["parent"]/"manifest.json",ctx["manifest"])
    ctx["report"]["manifest_sha256"]=recovery._digest(ctx["manifest"])
    ctx["report"]["ledger_row_count"]+=1
    write(ctx["parent"]/"report.json",ctx["report"])
    refresh(ctx)
    refuse(ctx,"duplicate or conflicting")


def test_wal_and_writer_refuse(tmp_path):
    ctx=prepare(tmp_path)
    wal=ctx["parent"]/"reconciliation.duckdb.wal"
    wal.write_text("not stopped")
    refuse(ctx,"WAL")
    wal.unlink()
    with (ctx["parent"]/"writer.lock").open("rb") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        refuse(ctx,"writer lock")


def test_symlink_and_input_parent_destination_refuse(tmp_path):
    ctx=prepare(tmp_path)
    alias=tmp_path/"database-alias"
    alias.symlink_to(ctx["database"])
    refuse(ctx,"canonical",database_path=str(alias))
    refuse(ctx,"input parent",output_directory=str(ctx["parent"]/"new-results"))


def test_foreign_destination_race_preserved(tmp_path):
    ctx=prepare(tmp_path)
    seen={}
    def foreign(stage,dest):
        dest.mkdir()
        seen["inode"]=dest.stat().st_ino
    before=sha(ctx["database"])
    with pytest.raises(ValueError,match="destination already exists"):
        recovery.run_identity_diagnosis(**ctx["arguments"],_before_publish=foreign)
    assert ctx["destination"].stat().st_ino==seen["inode"]
    assert list(ctx["destination"].iterdir())==[]
    assert sha(ctx["database"])==before
    assert not list(ctx["destination"].parent.glob(".identity-diagnosis-*"))


@pytest.mark.parametrize("name,value",[("memory_mb",0),("memory_mb",257),("max_retained_rows",0),
    ("max_archive_rows",500001),("example_limit",33),("max_output_bytes",8388609),("max_report_bytes",2097153)])
def test_config_bound_refusal(tmp_path,name,value):
    ctx=prepare(tmp_path)
    refuse(ctx,"positive",**{name:value})


@pytest.mark.parametrize("extra,match",[({"max_retained_rows":2},"retained row"),
    ({"max_archive_rows":3},"archive row"),({"max_report_bytes":100},"report exceeds"),
    ({"max_output_bytes":512,"max_report_bytes":256},"artifact exceeds")])
def test_actual_bounds_refuse_without_publication(tmp_path,extra,match):
    ctx=prepare(tmp_path)
    refuse(ctx,match,**extra)


def test_input_mutation_after_baseline_refuses(tmp_path):
    ctx=prepare(tmp_path)
    refuse(ctx,"input witness changed",_after_baseline=lambda:ctx["review"].write_text("changed"))


@pytest.mark.parametrize("kind",["corrupt","extra","symlink","interrupt","candidate_growth","report_growth"])
def test_staging_failure_never_publishes(tmp_path,kind):
    ctx=prepare(tmp_path)
    def fail(stage,dest):
        if kind=="corrupt":(stage/"candidates.parquet").write_bytes(b"tampered")
        elif kind=="extra":(stage/"foreign").write_text("foreign")
        elif kind=="symlink":
            (stage/"candidates.parquet").unlink()
            (stage/"candidates.parquet").symlink_to(ctx["progress"])
        elif kind in ("candidate_growth","report_growth"):
            filename="candidates.parquet" if kind=="candidate_growth" else "report.json"
            with (stage/filename).open("wb") as stream:
                stream.truncate(9*1024*1024)
        else:raise OSError("interrupted")
    refuse(ctx,"staged|interrupted",_before_publish=fail)


@pytest.mark.parametrize("target",["input","destination","lock"])
def test_parent_or_lock_alias_change_refuses(tmp_path,target):
    ctx=prepare(tmp_path)
    def alias(stage,dest):
        path=ctx["progress"].parent if target=="input" else dest.parent if target=="destination" else ctx["parent"]/"writer.lock"
        moved=path.with_name(path.name+"-moved")
        path.rename(moved)
        path.symlink_to(moved,target_is_directory=target!="lock")
    refuse(ctx,"canonical",_before_publish=alias)
