"""Restartable reconciliation of archived targets, with explicit outside scope.

This additive controller never runs a model, edits a source catalog, or imports
remote completion authority. Unarchived candidates have durable aggregate
accounting and ordered digests, not a complete persisted occurrence inventory.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
from typing import Callable

from . import legacy_span_intake as intake
from . import uscode_source_census as census

SCHEMA = "uscode-archived-target-reconciliation/v1"
SCOPE = "archived-targets; outside-target sources have aggregate accounting only"
ZERO_DIGEST = "0" * 64
OLD_COLUMNS = ("occurrence_id", "source_span_id", "source_sha256", "legal_id", "entry_cid",
    "title", "section", "citation", "source_section_offset", "historical_document_batch_index",
    "historical_span_ordinal", "utf8_bytes", "unicode_characters", "token_count", "byte_cohort",
    "token_cohort", "source_join_disposition")
EXTRA_COLUMNS = ("source_section_span_ordinal", "source_text_origin", "raw_source_text_present")


def _pins():
    from . import legacy_span_pages as pages
    return census._source_code_pins() | {
        "span_pages": hashlib.sha256(Path(pages.__file__).read_bytes()).hexdigest(),
        "archive_reconciliation": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _initial_accounting():
    return dict(source_occurrence_count=0, target_occurrence_count=0,
        outside_target_occurrence_count=0, empty_section_count=0,
        source_utf8_bytes=0, source_unicode_characters=0, max_source_utf8_bytes=0,
        max_source_unicode_characters=0, source_byte_cohorts={}, outside_target_byte_cohorts={},
        target_dispositions={}, source_text_origins={}, outside_target_examples=[],
        all_occurrence_digest=ZERO_DIGEST, outside_target_digest=ZERO_DIGEST)


def _state(connection, key):
    row = connection.execute("SELECT value FROM reconciliation_state WHERE key=?", [key]).fetchone()
    if row is None:
        raise intake.SpanIntakeError("reconciliation state is missing " + key)
    return row[0]


def _set(connection, key, value):
    connection.execute("INSERT OR REPLACE INTO reconciliation_state VALUES (?,?)", [key,str(value)])


def _initialize(connection, progress, max_row_group_bytes):
    parquet = intake._parquet(progress["path"], max_rows=2_000_000,
                              max_row_group_bytes=max_row_group_bytes)
    import pyarrow as pa
    required = {"record_kind", "dataset_id", "source_span_id", "source_sha256", "legal_id"}
    if not required.issubset(parquet.schema_arrow.names) or any(
            not pa.types.is_string(parquet.schema_arrow.field(n).type) for n in required):
        raise intake.SpanIntakeError("progress parquet is missing string identity columns")
    connection.execute("CREATE TABLE IF NOT EXISTS reconciliation_state (key VARCHAR PRIMARY KEY,value VARCHAR)")
    connection.execute("CREATE TABLE IF NOT EXISTS target_occurrences (occurrence_id BLOB PRIMARY KEY, "
        "source_span_id VARCHAR,source_sha256 VARCHAR,legal_id VARCHAR,entry_cid VARCHAR,title VARCHAR,"
        "section VARCHAR,citation VARCHAR,source_section_offset BIGINT,historical_document_batch_index BIGINT,"
        "historical_span_ordinal BIGINT,utf8_bytes BIGINT,unicode_characters BIGINT,token_count BIGINT,"
        "byte_cohort VARCHAR,token_cohort VARCHAR,source_join_disposition VARCHAR,"
        "source_section_span_ordinal BIGINT,source_text_origin VARCHAR,raw_source_text_present BOOLEAN)")
    if connection.execute("SELECT count(*) FROM reconciliation_state").fetchone()[0] == 0:
        connection.execute("BEGIN")
        try:
            for key,value in {"next_section":"0", "next_span":"0", "done":"false",
                    "accounting":census._json(_initial_accounting()), "seed_applied":"false"}.items():
                _set(connection,key,value)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    connection.execute("CREATE TEMP TABLE ledger_rows AS SELECT row_number() OVER ()-1 AS ledger_row,"
        "record_kind,dataset_id,source_span_id,source_sha256,legal_id FROM read_parquet(?)",[progress["path"]])
    datasets = {r[0] for r in connection.execute(
        "SELECT DISTINCT dataset_id FROM ledger_rows WHERE record_kind='meta'").fetchall()}
    if not datasets or not datasets.issubset(intake._DATASETS):
        raise intake.SpanIntakeError("progress metadata is not bound to the U.S. Code dataset")
    connection.execute("CREATE TEMP TABLE ledger_identities AS SELECT source_span_id,count(*) AS ledger_rows,"
        "count(*) FILTER (WHERE NOT coalesce(("+census.VALID+"),FALSE)) AS invalid_rows,"
        "count(DISTINCT coalesce(source_sha256,''))>1 OR count(DISTINCT coalesce(legal_id,''))>1 AS conflict "
        "FROM ledger_rows WHERE record_kind='span' GROUP BY source_span_id")
    connection.execute("CREATE UNIQUE INDEX ledger_ids ON ledger_identities(source_span_id)")
    connection.execute("CREATE TEMP TABLE progress_join_targets AS SELECT DISTINCT r.source_span_id,"
        "r.source_sha256,r.legal_id,FALSE AS matched FROM ledger_rows r JOIN ledger_identities s USING(source_span_id) "
        "WHERE r.record_kind='span' AND NOT s.conflict AND s.invalid_rows=0")
    connection.execute("CREATE UNIQUE INDEX target_ids ON progress_join_targets(source_span_id)")
    return intake.ProgressIndex(connection,"progress_join_targets",progress,{})


def _classify(connection, candidates):
    if not candidates:
        return {}
    import pyarrow as pa
    connection.register("page_ids",pa.table({"source_span_id":sorted({r["source_span_id"] for r in candidates})}))
    try:
        return {k:(bool(conflict),int(invalid)) for k,conflict,invalid in connection.execute(
            "SELECT s.source_span_id,s.conflict,s.invalid_rows FROM ledger_identities s JOIN page_ids c USING(source_span_id)").fetchall()}
    finally:
        connection.unregister("page_ids")


def _rows(connection,page,source):
    states = _classify(connection,page["candidate_rows"])
    for candidate in page["candidate_rows"]:
        target = candidate["source_span_id"] in states
        conflict,invalid = states.get(candidate["source_span_id"],(False,0))
        disposition = ("ledger_identity_conflict" if conflict else "invalid_ledger_identity" if invalid
                       else candidate["source_join_disposition"])
        row = census._occurrence(candidate,source,None,disposition)
        row.update({k:candidate[k] for k in EXTRA_COLUMNS})
        yield row,target


def _bump(mapping,key):
    mapping[key] = mapping.get(key,0)+1


def _account(accounting,row,target,example_limit):
    descriptor = {k:(v.hex() if isinstance(v,bytes) else v) for k,v in row.items()}
    encoded = census._json(descriptor).encode()
    accounting["all_occurrence_digest"] = hashlib.sha256(
        bytes.fromhex(accounting["all_occurrence_digest"])+encoded).hexdigest()
    accounting["source_occurrence_count"] += 1
    accounting["source_utf8_bytes"] += row["utf8_bytes"]
    accounting["source_unicode_characters"] += row["unicode_characters"]
    accounting["max_source_utf8_bytes"] = max(accounting["max_source_utf8_bytes"],row["utf8_bytes"])
    accounting["max_source_unicode_characters"] = max(accounting["max_source_unicode_characters"],row["unicode_characters"])
    _bump(accounting["source_byte_cohorts"],row["byte_cohort"])
    _bump(accounting["source_text_origins"],row["source_text_origin"])
    if target:
        accounting["target_occurrence_count"] += 1
        _bump(accounting["target_dispositions"],row["source_join_disposition"])
    else:
        accounting["outside_target_occurrence_count"] += 1
        _bump(accounting["outside_target_byte_cohorts"],row["byte_cohort"])
        accounting["outside_target_digest"] = hashlib.sha256(
            bytes.fromhex(accounting["outside_target_digest"])+encoded).hexdigest()
        if len(accounting["outside_target_examples"]) < example_limit:
            accounting["outside_target_examples"].append({k:descriptor[k] for k in (
                "occurrence_id","source_span_id","source_sha256","legal_id","source_section_offset",
                "source_section_span_ordinal","utf8_bytes","unicode_characters","source_text_origin")})


def _insert(connection,rows):
    if rows:
        import pyarrow as pa
        connection.register("target_batch",pa.Table.from_pylist(rows))
        try:
            connection.execute("INSERT INTO target_occurrences SELECT * FROM target_batch")
        finally:
            connection.unregister("target_batch")


def _write_page(connection,page,source,example_limit,before_commit=None):
    accounting = json.loads(_state(connection,"accounting"))
    targets = []
    for row,target in _rows(connection,page,source):
        _account(accounting,row,target,example_limit)
        if target:
            targets.append(row)
    accounting["empty_section_count"] += page["counts"].get("empty_section_count",0)
    connection.execute("BEGIN")
    try:
        _insert(connection,targets)
        for key,value in {"accounting":census._json(accounting),"next_section":page["next_section"],
                "next_span":page["next_span"],"done":"true" if page["done"] else "false"}.items():
            _set(connection,key,value)
        if before_commit:
            before_commit(page)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


@contextmanager
def _seed_snapshot(directory,progress,source,max_row_group_bytes):
    """Hold a shared stopped-writer lock and authenticate immutable old bytes."""
    directory = Path(directory)
    if directory.is_symlink() or directory.resolve() != directory.absolute():
        raise intake.SpanIntakeError("seed must be a canonical local directory")
    names = ["manifest.json","report.json","census.duckdb","writer.lock"]
    if any((directory/n).is_symlink() or not (directory/n).is_file() for n in names):
        raise intake.SpanIntakeError("seed files must be existing regular files")
    if (directory/"census.duckdb.wal").exists():
        raise intake.SpanIntakeError("seed database has an unreconciled WAL")
    with (directory/"writer.lock").open("r") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise intake.SpanIntakeError("seed census still has a writer") from exc
        pins = {}
        for name,limit in [("manifest.json",1024*1024),("report.json",4*1024*1024),("census.duckdb",256*1024*1024)]:
            path = directory/name
            if path.stat().st_size > limit:
                raise intake.SpanIntakeError("seed snapshot exceeds its byte bound")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda:stream.read(1024*1024),b""):
                    digest.update(block)
            pins[name] = intake._file_identity(path,digest.hexdigest(),max_bytes=limit)
        manifest = json.loads((directory/"manifest.json").read_text())
        report = json.loads((directory/"report.json").read_text())
        def public(pin):
            return {k:v for k,v in pin.items() if k != "stat_signature"}
        if (manifest.get("schema") != census.SCHEMA or manifest.get("source_code_sha256") != census._source_code_pins()
                or manifest.get("progress") != public(progress) or manifest.get("source") != public(source)
                or manifest.get("tokenizer") is not None or report.get("schema") != census.SCHEMA
                or report.get("manifest_sha256") != census._digest(manifest)):
            raise intake.SpanIntakeError("seed manifest input/code/profile pins differ")
        import duckdb
        db = duckdb.connect(str(directory/"census.duckdb"),read_only=True)
        try:
            state = dict(db.execute("SELECT key,value FROM census_state").fetchall())
            count = db.execute("SELECT count(*) FROM source_occurrences").fetchone()[0]
            dispositions = dict(db.execute("SELECT source_join_disposition,count(*) FROM source_occurrences GROUP BY 1").fetchall())
            if (state.get("initialized") != "true" or state.get("done") not in ("true","false")
                    or int(state.get("next_section",-1)) < 0
                    or int(state.get("next_section",-1)) != report["statistics"]["next_section"]
                    or count != report["statistics"]["source_occurrence_count"]
                    or dispositions != report["statistics"]["source_disposition_counts"]
                    or (state.get("done") == "true") != report.get("complete_source_scan")
                    or json.loads(state["intake_counts"]) != report["statistics"]["intake_control_counts"]):
                raise intake.SpanIntakeError("seed database/report/cursor accounting differs")
            yield db,manifest,report,state,{k:public(v) for k,v in pins.items()},pins
            for pin in pins.values():
                intake._unchanged(pin)
            if (directory/"census.duckdb.wal").exists():
                raise intake.SpanIntakeError("seed database changed during verification")
        finally:
            db.close()
            fcntl.flock(lock,fcntl.LOCK_UN)


def _apply_seed(connection,index,pager,seed_db,seed_report,seed_state,source,example_limit,storage_check,before_commit=None,verify_snapshot=None):
    boundary = int(seed_state["next_section"])
    accounting = _initial_accounting()
    old_columns = [c[0] for c in seed_db.execute("SELECT * FROM source_occurrences LIMIT 0").description]
    if tuple(old_columns) != OLD_COLUMNS:
        raise intake.SpanIntakeError("seed occurrence schema differs")
    old_cursor = seed_db.execute("SELECT * FROM source_occurrences ORDER BY source_section_offset,historical_span_ordinal,occurrence_id")
    expected = old_cursor.fetchone()
    verified = 0
    replayed_cursor = (0,0)
    connection.execute("BEGIN")
    try:
        for page in pager(index,source["path"],start_section=0,start_span=0):
            if (boundary > page["total_sections"] or
                    (seed_state["done"] == "true") != (boundary == page["total_sections"])):
                raise intake.SpanIntakeError("seed cursor/completion differs from original source extent")
            prefix = [r for r in page["candidate_rows"] if r["source_section_offset"] < boundary]
            if len(prefix) != len(page["candidate_rows"]) and prefix:
                raise intake.SpanIntakeError("seed prefix page crosses its section boundary")
            if page["candidate_rows"] and not prefix:
                break
            if not prefix and page["next_section"] > boundary:
                break
            targets = []
            for row,target in _rows(connection,{**page,"candidate_rows":prefix},source):
                if expected is None or tuple(row[k] for k in OLD_COLUMNS) != tuple(expected):
                    raise intake.SpanIntakeError("seed occurrence binding differs from exact source replay")
                expected = old_cursor.fetchone()
                verified += 1
                _account(accounting,row,target,example_limit)
                if target:
                    targets.append(row)
            accounting["empty_section_count"] += page["counts"].get("empty_section_count",0)
            _insert(connection,targets)
            replayed_cursor = (page["next_section"],page["next_span"])
            storage_check()
            if page["next_section"] == boundary and page["next_span"] == 0:
                break
        if (replayed_cursor != (boundary,0) or expected is not None
                or verified != seed_report["statistics"]["source_occurrence_count"]
                or accounting["source_occurrence_count"] != seed_report["statistics"]["intake_control_counts"].get("candidate_span_count",0)
                or accounting["empty_section_count"] != seed_report["statistics"]["intake_control_counts"].get("empty_section_count",0)):
            raise intake.SpanIntakeError("seed prefix replay does not cover its exact cursor/counts")
        for key,value in {"next_section":boundary,"next_span":0,"done":seed_state["done"],
                "accounting":census._json(accounting),"seed_applied":"true"}.items():
            _set(connection,key,value)
        if before_commit:
            before_commit({"event":"verified_seed_import","verified_occurrences":verified})
        if verify_snapshot:
            verify_snapshot()
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def _report(connection,directory,manifest,storage_max_bytes):
    completed = _state(connection,"done") == "true"
    pending = "unresolved_source" if completed else "pending_source_scan"
    connection.execute("CREATE OR REPLACE TEMP VIEW ledger_dispositions AS SELECT r.*,CASE "
        "WHEN r.record_kind IS DISTINCT FROM 'span' THEN 'excluded_nonspan' "
        "WHEN NOT coalesce(("+census.VALID+"),FALSE) OR s.invalid_rows>0 THEN 'invalid_ledger_identity' "
        "WHEN s.conflict THEN 'ledger_identity_conflict' "
        "WHEN EXISTS (SELECT 1 FROM target_occurrences t WHERE t.source_span_id=r.source_span_id "
        "AND t.source_sha256=r.source_sha256 AND t.legal_id=r.legal_id) THEN 'matched' "
        "WHEN EXISTS (SELECT 1 FROM target_occurrences t WHERE t.source_span_id=r.source_span_id "
        "AND t.source_sha256<>r.source_sha256) THEN 'source_hash_mismatch' "
        "WHEN EXISTS (SELECT 1 FROM target_occurrences t WHERE t.source_span_id=r.source_span_id) THEN 'legal_id_mismatch' "
        "ELSE '"+pending+"' END AS disposition FROM ledger_rows r LEFT JOIN ledger_identities s USING(source_span_id)")
    accounting = json.loads(_state(connection,"accounting"))
    target_count = connection.execute("SELECT count(*) FROM target_occurrences").fetchone()[0]
    if (target_count != accounting["target_occurrence_count"] or
            target_count+accounting["outside_target_occurrence_count"] != accounting["source_occurrence_count"]):
        raise intake.SpanIntakeError("persisted target/accounting count differs")
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = "bytes" if sys.platform == "darwin" else "KiB" if sys.platform.startswith("linux") else "platform-dependent"
    report = {"schema":SCHEMA,"manifest_sha256":census._digest(manifest),"inventory_scope":SCOPE,
        "complete_source_scan":completed,"complete_all_source_occurrence_inventory":False,
        "next_section":int(_state(connection,"next_section")),"next_span":int(_state(connection,"next_span")),
        "accounting":accounting,"persisted_target_occurrences":target_count,
        "ledger_row_count":connection.execute("SELECT count(*) FROM ledger_rows").fetchone()[0],
        "archived_span_record_count":connection.execute("SELECT count(*) FROM ledger_rows WHERE record_kind='span'").fetchone()[0],
        "distinct_archived_span_id_count":connection.execute("SELECT count(*) FROM ledger_identities WHERE source_span_id IS NOT NULL AND source_span_id<>''").fetchone()[0],
        "distinct_target_span_id_count":connection.execute("SELECT count(DISTINCT source_span_id) FROM target_occurrences").fetchone()[0],
        "archived_conflicting_id_count":connection.execute("SELECT count(*) FROM ledger_identities WHERE conflict").fetchone()[0],
        "ledger_disposition_counts":dict(connection.execute("SELECT disposition,count(*) FROM ledger_dispositions GROUP BY 1 ORDER BY 1").fetchall()),
        "seed_applied":_state(connection,"seed_applied")=="true","seed":manifest["seed"],
        "outside_target_storage":"Aggregate counts, ordered digest and bounded examples; full outside-target identities are not persisted",
        "source_text_storage":"Pinned original artifact and physical row/span references; no copied source text",
        "kernel_maxrss":{"raw":maximum,"raw_unit":unit,"bytes":maximum if unit=="bytes" else maximum*1024 if unit=="KiB" else None,
            "scope":"Current process lifetime high-water RSS from getrusage(RUSAGE_SELF); not an isolated phase peak or process-group peak"},
        "inference_executed":False,"training_executed":False,"admitted":False,"formalized":False,"proof_authority":False,
        "semantic_reconstruction_measured":False,
        "token_counts_measured":False,"output_bytes_before_report":census._storage(directory,storage_max_bytes)}
    census._durable_json(directory/"report.json",report)
    census._storage(directory,storage_max_bytes)
    return report


def run_archive_reconciliation(*, progress_parquet:str,progress_sha256:str,progress_revision:str,
        source_parquet:str,source_sha256:str,output_directory:str,
        source_revision:str=intake.SOURCE_REVISION,release_id:str=intake.DEFAULT_RELEASE_ID,
        max_page_spans:int=1024,max_page_bytes:int=4*1024*1024,max_section_bytes:int=8*1024*1024,
        max_row_group_bytes:int=2*1024*1024*1024,max_pages:int|None=None,memory_mb:int=768,
        storage_max_bytes:int=128*1024*1024,example_limit:int=16,seed_census_directory:str|None=None,
        _before_commit:Callable|None=None):
    """Reconcile archive IDs under a distinct, immutable target-scope generation."""
    for revision in (progress_revision,source_revision):
        if not isinstance(revision,str) or not intake._REVISION.fullmatch(revision):
            raise intake.SpanIntakeError("immutable complete repository revisions are required")
    for name,value in [("max_page_spans",max_page_spans),("max_page_bytes",max_page_bytes),
            ("max_section_bytes",max_section_bytes),("max_row_group_bytes",max_row_group_bytes),
            ("memory_mb",memory_mb),("storage_max_bytes",storage_max_bytes)]:
        intake._positive(value,name)
    if max_pages is not None:
        intake._positive(max_pages,"max_pages")
    if type(example_limit) is not int or not 0<=example_limit<=64:
        raise intake.SpanIntakeError("example_limit must be in 0..64")
    progress = intake._file_identity(progress_parquet,progress_sha256,max_bytes=256*1024*1024)
    progress.update(repository_id=intake.PROGRESS_REPOSITORY,revision=progress_revision,
                    path_in_repo="autoformal/uscode/resume-checkpoint.parquet")
    source = intake._file_identity(source_parquet,source_sha256,max_bytes=512*1024*1024)
    source.update(repository_id=intake.SOURCE_REPOSITORY,revision=source_revision,release_id=release_id)
    def public(pin):
        return {k:v for k,v in pin.items() if k!="stat_signature"}
    from .legacy_span_pages import iter_joined_span_pages
    def pager(index,path,**cursor):
        return iter_joined_span_pages(index,path,expected_laws_sha256=source_sha256,
            source_revision=source_revision,release_id=release_id,max_page_spans=max_page_spans,
            max_page_bytes=max_page_bytes,max_section_bytes=max_section_bytes,
            max_row_group_bytes=max_row_group_bytes,**cursor)
    @contextmanager
    def seed_context():
        if seed_census_directory:
            with _seed_snapshot(seed_census_directory,progress,source,max_row_group_bytes) as result:
                yield result
        else:
            yield None
    directory = Path(output_directory).absolute()
    with census._writer(directory),seed_context() as seed:
        manifest = {"schema":SCHEMA,"inventory_scope":SCOPE,"progress":public(progress),"source":public(source),
            "source_code_sha256":_pins(),"identity_reconstruction":intake.IDENTITY_RECONSTRUCTION,
            "bounds":{"max_page_spans":max_page_spans,"max_page_bytes":max_page_bytes,
                "max_section_bytes":max_section_bytes,"max_row_group_bytes":max_row_group_bytes,"example_limit":example_limit},
            "seed":None if seed is None else {"files":seed[4],"manifest_sha256":census._digest(seed[1]),
                "next_section":int(seed[3]["next_section"]),"source_occurrence_count":seed[2]["statistics"]["source_occurrence_count"]}}
        marker,database = directory/"manifest.json",directory/"reconciliation.duckdb"
        if marker.is_symlink() or database.is_symlink():
            raise intake.SpanIntakeError("reconciliation files must not be symlinks")
        if marker.exists():
            if json.loads(marker.read_text()) != manifest:
                raise intake.SpanIntakeError("resume source/code/seed/paging/profile pins differ")
        elif database.exists():
            raise intake.SpanIntakeError("refusing an existing database without this reconciliation manifest")
        else:
            census._durable_json(marker,manifest)
        import duckdb
        connection = duckdb.connect(str(database))
        try:
            connection.execute("SET threads=1")
            connection.execute(f"SET memory_limit='{memory_mb}MB'")
            connection.execute("SET temp_directory=?",[str(directory/"spill")])
            connection.execute(f"SET max_temp_directory_size='{max(1,min(128,storage_max_bytes//(4*1024*1024)))}MB'")
            connection.execute("SET checkpoint_threshold='8MB'")
            index = _initialize(connection,progress,max_row_group_bytes)
            check = lambda:census._storage(directory,storage_max_bytes)
            check()
            if seed is not None and _state(connection,"seed_applied") != "true":
                def verify_seed():
                    for pin in seed[5].values():
                        intake._unchanged(pin)
                _apply_seed(connection,index,pager,seed[0],seed[2],seed[3],source,example_limit,check,_before_commit,verify_seed)
                check()
            cursor = {"start_section":int(_state(connection,"next_section")),"start_span":int(_state(connection,"next_span"))}
            if _state(connection,"done") != "true":
                for number,page in enumerate(pager(index,source["path"],**cursor),start=1):
                    _write_page(connection,page,source,example_limit,_before_commit)
                    check()
                    if page["done"] or max_pages is not None and number>=max_pages:
                        break
            intake._unchanged(progress)
            intake._unchanged(source)
            connection.execute("CHECKPOINT")
            report = _report(connection,directory,manifest,storage_max_bytes)
            connection.execute("CHECKPOINT")
            return report
        finally:
            connection.close()
