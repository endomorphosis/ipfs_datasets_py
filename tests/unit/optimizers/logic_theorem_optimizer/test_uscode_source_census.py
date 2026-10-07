"""Immutable sources, occurrence accounting, bounded restart and conflicts."""
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_intake as intake
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_source_census as census


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(text, section, ordinal):
    value = {"canonical_citation":f"1 U.S.C. {section}","entry_cid":"fixture-cid",
        "legal_id":f"usc:us:1:{section}","ordinal":ordinal,"query":"ipfs_uscode",
        "release_id":intake.DEFAULT_RELEASE_ID,"release_point":"","schema_version":"uscode-sparse-autoformal-span-v1",
        "section":str(section),"text_sha256":hashlib.sha256(text.encode()).hexdigest(),"title":"1",
        "unit_id":f"usc:us:1:{section}"}
    digest = hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
    return {"record_kind":"span","dataset_id":"","source_span_id":"uscode-span-"+digest,
            "source_sha256":value["text_sha256"],"legal_id":value["legal_id"]}


def inputs(tmp_path, n=3, transform=None, metadata=False):
    tmp_path.mkdir(parents=True,exist_ok=True)
    texts = [f"The agency shall retain record {i}." for i in range(n)]
    records = [identity(text,str(i+1),i%64) for i,text in enumerate(texts)]
    if transform:
        records = transform(records)
    meta = {"record_kind":"meta","dataset_id":"justicedao/ipfs_uscode","source_span_id":"","source_sha256":"","legal_id":""}
    schema = pa.schema([(key,pa.string()) for key in meta])
    progress = tmp_path/"progress.parquet"
    pq.write_table(pa.Table.from_pylist([meta,*records],schema=schema),progress)
    source = tmp_path/"source.parquet"
    sections = [{"ipfs_cid":"fixture-cid","title_number":"1","section_number":str(i+1),"text":text,
                 "normalized_citation":f"1 U.S.C. {i+1}"} for i,text in enumerate(texts)]
    if metadata:
        sections.append({k:None for k in sections[0]})
    pq.write_table(pa.Table.from_pylist(sections),source)
    return dict(progress_parquet=str(progress),progress_sha256=sha(progress),progress_revision="a"*40,
                source_parquet=str(source),source_sha256=sha(source),output_directory=str(tmp_path/"result")),records


def source_rows(directory):
    with duckdb.connect(str(Path(directory)/"census.duckdb"),read_only=True) as db:
        return db.execute("SELECT source_span_id,source_sha256,source_section_offset,historical_document_batch_index,"
                          "historical_span_ordinal,source_join_disposition,token_count FROM source_occurrences ORDER BY source_section_offset").fetchall()


def test_complete_census_is_local_and_token_counts_are_unmeasured(tmp_path):
    args,records=inputs(tmp_path,metadata=True)
    result=census.run_source_census(**args,section_batch_size=2)
    assert result["complete_source_scan"] is True
    stats=result["statistics"]
    assert stats["record_kind_counts"]=={"meta":1,"span":3}
    assert stats["source_occurrence_count"]==3
    assert stats["ledger_disposition_counts"]=={"excluded_nonspan":1,"matched":3}
    assert stats["next_section"]==4
    assert stats["intake_control_counts"]["empty_section_count"]==1
    assert stats["source_lengths"]["total_utf8_bytes"]==sum(len(f"The agency shall retain record {i}.".encode()) for i in range(3))
    assert result["token_counts_measured"] is False and stats["token_cohorts"] is None
    assert all(row[-1] is None for row in source_rows(args["output_directory"]))
    assert not result["admitted"] and not result["formalized"] and not result["inference_executed"]
    assert [Path(p["path"]).name for p in result["exports"]]==["census-disposition-counts.parquet"]
    assert result["full_parquet_exported"] is False
    with duckdb.connect(str(Path(args["output_directory"])/"census.duckdb"),read_only=True) as db:
        tables={r[0] for r in db.execute("SHOW TABLES").fetchall()}
    assert tables=={"census_state","source_occurrences"}


@pytest.mark.parametrize("batch_size",[1,7,64,67])
def test_historical_groups_do_not_depend_on_current_batch_size(tmp_path,batch_size):
    args,records=inputs(tmp_path,70)
    result=census.run_source_census(**args,section_batch_size=batch_size)
    rows=source_rows(args["output_directory"])
    assert [r[0] for r in rows]==[r["source_span_id"] for r in records]
    assert [r[3] for r in rows]==[i//64 for i in range(70)]
    assert [r[4] for r in rows]==[i%64 for i in range(70)]
    assert result["statistics"]["ledger_disposition_counts"]["matched"]==70


def test_resume_changes_batch_size_without_duplicate_or_skipped_occurrences(tmp_path):
    args,_=inputs(tmp_path,70)
    first=census.run_source_census(**args,section_batch_size=5,max_batches=3)
    assert not first["complete_source_scan"] and first["statistics"]["next_section"]==15
    assert first["statistics"]["ledger_disposition_counts"]["pending_source_scan"]==55
    second=census.run_source_census(**args,section_batch_size=9)
    assert second["complete_source_scan"] and second["statistics"]["source_occurrence_count"]==70
    again=census.run_source_census(**args,section_batch_size=2)
    assert again["statistics"]==second["statistics"]


def test_transaction_interrupt_rolls_back_rows_and_cursor_together(tmp_path):
    args,_=inputs(tmp_path)
    def interrupt(batch): raise RuntimeError("interrupted")
    with pytest.raises(RuntimeError,match="interrupted"):
        census.run_source_census(**args,section_batch_size=1,_before_commit=interrupt)
    with duckdb.connect(str(Path(args["output_directory"])/"census.duckdb"),read_only=True) as db:
        assert db.execute("SELECT count(*) FROM source_occurrences").fetchone()[0]==0
        assert db.execute("SELECT value FROM census_state WHERE key='next_section'").fetchone()[0]=="0"
    assert census.run_source_census(**args)["statistics"]["source_occurrence_count"]==3


def test_every_unlisted_candidate_is_retained_not_only_bounded_examples(tmp_path):
    args,_=inputs(tmp_path,12,transform=lambda rows:rows[:1])
    result=census.run_source_census(**args,section_batch_size=3)
    assert result["statistics"]["source_occurrence_count"]==12
    assert result["statistics"]["source_disposition_counts"]=={"matched":1,"unlisted_source":11}


@pytest.mark.parametrize("field,value,reason",[("source_sha256","b"*64,"source_hash_mismatch"),
    ("legal_id","usc:us:1:999","legal_id_mismatch")])
def test_mismatched_inputs_are_preserved_without_borrowing_authority(tmp_path,field,value,reason):
    args,_=inputs(tmp_path,1,transform=lambda rows:[{**rows[0],field:value}])
    result=census.run_source_census(**args)
    assert result["statistics"]["source_disposition_counts"]=={reason:1}
    assert result["statistics"]["ledger_disposition_counts"][reason]==1


def test_conflicting_ledger_id_and_exact_duplicates_have_separate_accounting(tmp_path):
    args,_=inputs(tmp_path,2,transform=lambda r:[r[0],r[0],{**r[0],"source_sha256":"c"*64},r[1],r[1]])
    result=census.run_source_census(**args)
    stats=result["statistics"]
    assert stats["ledger_span_record_count"]==5 and stats["distinct_nonempty_ledger_span_id_count"]==2
    assert stats["ledger_conflicting_id_count"]==1 and stats["source_occurrence_count"]==2
    assert stats["ledger_disposition_counts"]=={"excluded_nonspan":1,"ledger_identity_conflict":3,"matched":2}
    assert stats["source_disposition_counts"]=={"ledger_identity_conflict":1,"matched":1}


def test_invalid_ledger_records_remain_explicit(tmp_path):
    args,_=inputs(tmp_path,1,transform=lambda r:[{**r[0],"source_sha256":None},
        {**r[0],"source_span_id":"","legal_id":""}])
    result=census.run_source_census(**args)
    assert result["statistics"]["ledger_invalid_record_count"]==2
    assert result["statistics"]["ledger_disposition_counts"]["invalid_ledger_identity"]==2
    assert result["statistics"]["source_disposition_counts"]=={"invalid_ledger_identity":1}


def test_resume_refuses_changed_verified_source_generation(tmp_path):
    args,_=inputs(tmp_path)
    census.run_source_census(**args,max_batches=1,section_batch_size=1)
    changed={**args,"progress_revision":"f"*40}
    with pytest.raises(intake.SpanIntakeError,match="pins differ"):
        census.run_source_census(**changed)
    assert len(source_rows(args["output_directory"]))==1


def test_existing_foreign_database_and_second_writer_are_refused(tmp_path):
    args,_=inputs(tmp_path)
    directory=Path(args["output_directory"]);directory.mkdir()
    with duckdb.connect(str(directory/"census.duckdb")) as db: db.execute("CREATE TABLE foreign_data (v INTEGER)")
    with pytest.raises(intake.SpanIntakeError,match="without this census manifest"):
        census.run_source_census(**args)
    (directory/"census.duckdb").unlink()
    with census._writer(directory):
        with pytest.raises(intake.SpanIntakeError,match="already has a writer"):
            census.run_source_census(**args)


def test_full_exports_require_explicit_option(tmp_path):
    args,_=inputs(tmp_path)
    result=census.run_source_census(**args,export_full_parquet=True)
    assert result["full_parquet_exported"] is True
    assert {Path(p["path"]).name for p in result["exports"]}=={
        "source-occurrences.parquet","ledger-dispositions.parquet","ledger-conflicts.parquet"}


def test_intake_optional_candidates_preserves_matched_only_default(tmp_path):
    args,_=inputs(tmp_path,4,transform=lambda rows:rows[:1])
    with duckdb.connect(":memory:") as db:
        index=intake.prepare_progress_index(db,args["progress_parquet"],expected_sha256=args["progress_sha256"],repository_revision=args["progress_revision"])
        old=list(intake.iter_joined_section_batches(index,args["source_parquet"],expected_laws_sha256=args["source_sha256"],diagnostic_limit=0))
        assert "candidate_rows" not in old[0] and len(old[0]["rows"])==1
        new=list(intake.iter_joined_section_batches(index,args["source_parquet"],expected_laws_sha256=args["source_sha256"],include_candidates=True,diagnostic_limit=0))
        assert len(new[0]["candidate_rows"])==4 and len(new[0]["rows"])==1


def test_configured_local_tokenizer_measures_complete_span_counts(tmp_path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    args,_=inputs(tmp_path,1)
    tokenizer=Tokenizer(WordLevel({"[UNK]":0,"The":1,"agency":2,"shall":3,"retain":4,"record":5,"0":6,".":7},unk_token="[UNK]"))
    tokenizer.pre_tokenizer=Whitespace()
    tokenizer.enable_padding(length=20)
    path=tmp_path/"tokenizer.json";tokenizer.save(str(path))
    result=census.run_source_census(**args,tokenizer_json=str(path),tokenizer_sha256=sha(path),
        tokenizer_id="fixture-wordlevel",tokenizer_revision="b"*40)
    assert result["token_counts_measured"] is True
    assert result["statistics"]["token_cohorts"]=={"le_512":1}
    assert source_rows(args["output_directory"])[0][-1]==7


def test_tokenizer_truncation_and_partial_configuration_are_refused(tmp_path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    args,_=inputs(tmp_path,1)
    with pytest.raises(intake.SpanIntakeError,match="configured together"):
        census.run_source_census(**args,tokenizer_id="fixture")
    tokenizer=Tokenizer(WordLevel({"[UNK]":0},unk_token="[UNK]"));tokenizer.enable_truncation(max_length=2)
    path=tmp_path/"tokenizer.json";tokenizer.save(str(path))
    with pytest.raises(intake.SpanIntakeError,match="forbids configured truncation"):
        census.run_source_census(**args,tokenizer_json=str(path),tokenizer_sha256=sha(path),
            tokenizer_id="fixture",tokenizer_revision="b"*40)


def test_complete_text_bound_does_not_advance_cursor_or_drop_source(tmp_path):
    args,_=inputs(tmp_path,1)
    with pytest.raises(intake.SpanIntakeError,match="complete-text byte bound"):
        census.run_source_census(**args,max_section_bytes=8)
    with duckdb.connect(str(Path(args["output_directory"])/"census.duckdb"),read_only=True) as db:
        assert db.execute("SELECT count(*) FROM source_occurrences").fetchone()[0]==0
        assert db.execute("SELECT value FROM census_state WHERE key='next_section'").fetchone()[0]=="0"


def test_character_and_utf8_overflow_cohorts_do_not_guess_tokens(tmp_path):
    args,_=inputs(tmp_path,1)
    text="é"*600000+"."
    record=identity(text,"1",0)
    meta={"record_kind":"meta","dataset_id":"justicedao/ipfs_uscode","source_span_id":"","source_sha256":"","legal_id":""}
    pq.write_table(pa.Table.from_pylist([meta,record]),args["progress_parquet"])
    pq.write_table(pa.Table.from_pylist([{"ipfs_cid":"fixture-cid","title_number":"1","section_number":"1",
        "text":text,"normalized_citation":"1 U.S.C. 1"}]),args["source_parquet"])
    args.update(progress_sha256=sha(args["progress_parquet"]),source_sha256=sha(args["source_parquet"]))
    result=census.run_source_census(**args)
    lengths=result["statistics"]["source_lengths"]
    assert lengths=={"total_utf8_bytes":1200001,"max_utf8_bytes":1200001,
        "total_unicode_characters":600001,"max_unicode_characters":600001,
        "above_historical_32768_characters":1,"above_new_1048576_utf8_bytes":1}
    assert result["statistics"]["token_cohorts"] is None
    assert "text" not in result["statistics"]["largest_occurrences"][0]
