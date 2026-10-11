"""Authenticate and clone a stopped archive generation before bounded resume.

The seven execution owners are unchanged. Clone custody is a separate operator
receipt; copied manifest/database bytes preserve the existing generation.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid

from . import legacy_span_intake as intake
from . import uscode_archive_reconciliation as archive
from . import uscode_source_census as census

SCHEMA = "uscode-archive-generation-clone/v1"
FILES = ("reconciliation.duckdb","manifest.json","report.json")


def _canonical(path, *, directory=False, existing=True):
    candidate = Path(path).absolute()
    if candidate.resolve(strict=existing) != candidate or candidate.is_symlink():
        raise intake.SpanIntakeError("clone custody requires canonical paths without symlink aliases")
    if existing:
        mode = candidate.stat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            raise intake.SpanIntakeError("clone custody requires a regular file or directory")
    return candidate


def _public(pin):
    return {k:v for k,v in pin.items() if k!="stat_signature"}


def _operator_pins():
    module = Path(__file__).resolve()
    cli = module.parents[3]/"scripts/ops/legal_ir/resume_uscode_archive.py"
    return {"resume_owner":hashlib.sha256(module.read_bytes()).hexdigest(),
            "resume_cli":hashlib.sha256(cli.read_bytes()).hexdigest()}


def _options(arguments):
    try:
        bound = inspect.signature(archive.run_archive_reconciliation).bind(**arguments)
    except TypeError as exc:
        raise intake.SpanIntakeError("complete controller arguments are required") from exc
    bound.apply_defaults()
    values = dict(bound.arguments)
    for name in ("max_page_spans","max_page_bytes","max_section_bytes","max_row_group_bytes",
                 "memory_mb","storage_max_bytes"):
        intake._positive(values[name],name)
    if values["max_pages"] is not None:
        intake._positive(values["max_pages"],"max_pages")
    if type(values["example_limit"]) is not int or not 0<=values["example_limit"]<=64:
        raise intake.SpanIntakeError("example_limit must be in 0..64")
    for name in ("progress_revision","source_revision"):
        if not isinstance(values[name],str) or not intake._REVISION.fullmatch(values[name]):
            raise intake.SpanIntakeError("complete immutable repository revisions are required")
    return values


@contextmanager
def _bindings(manifest,values):
    if (manifest.get("schema")!=archive.SCHEMA or manifest.get("inventory_scope")!=archive.SCOPE
            or manifest.get("source_code_sha256")!=archive._pins()
            or manifest.get("identity_reconstruction")!=intake.IDENTITY_RECONSTRUCTION):
        raise intake.SpanIntakeError("parent generation schema/code/identity binding differs")
    for name in ("progress","source"):
        path=_canonical(values[name+"_parquet"])
        limit=256*1024*1024 if name=="progress" else 512*1024*1024
        pin=intake._file_identity(path,values[name+"_sha256"],max_bytes=limit)
        if name=="progress":
            pin.update(repository_id=intake.PROGRESS_REPOSITORY,revision=values["progress_revision"],
                path_in_repo="autoformal/uscode/resume-checkpoint.parquet")
            progress=pin
        else:
            pin.update(repository_id=intake.SOURCE_REPOSITORY,revision=values["source_revision"],release_id=values["release_id"])
            source=pin
        if manifest.get(name)!=_public(pin):
            raise intake.SpanIntakeError("parent source/input binding differs")
    bounds={name:values[name] for name in ("max_page_spans","max_page_bytes","max_section_bytes","max_row_group_bytes","example_limit")}
    if manifest.get("bounds")!=bounds:
        raise intake.SpanIntakeError("parent paging/profile binding differs")
    seed=manifest.get("seed")
    if (seed is None)!=(values["seed_census_directory"] is None):
        raise intake.SpanIntakeError("parent seed binding differs")
    seed_witnesses={}
    @contextmanager
    def seed_context():
        if seed is None:
            yield
        else:
            seed_directory=_canonical(values["seed_census_directory"],directory=True)
            with archive._seed_snapshot(seed_directory,progress,source,values["max_row_group_bytes"]) as snapshot:
                expected={"files":snapshot[4],"manifest_sha256":census._digest(snapshot[1]),
                    "next_section":int(snapshot[3]["next_section"]),
                    "source_occurrence_count":snapshot[2]["statistics"]["source_occurrence_count"]}
                if seed!=expected:
                    raise intake.SpanIntakeError("parent seed snapshot binding differs")
                seed_witnesses.update(snapshot[5])
                yield
    with seed_context():
        def verify():
            intake._unchanged(progress)
            intake._unchanged(source)
            for pin in seed_witnesses.values():
                intake._unchanged(pin)
            if manifest["source_code_sha256"]!=archive._pins():
                raise intake.SpanIntakeError("execution owner changed during clone custody")
        yield progress,source,verify
        verify()


def _consistent(db,manifest,report,values,progress,source):
    tables={r[0] for r in db.execute("SHOW TABLES").fetchall()}
    if tables!={"reconciliation_state","target_occurrences"}:
        raise intake.SpanIntakeError("parent database has an unexpected inventory schema")
    state=dict(db.execute("SELECT key,value FROM reconciliation_state").fetchall())
    if set(state)!={"next_section","next_span","done","accounting","seed_applied"}:
        raise intake.SpanIntakeError("parent durable state schema differs")
    for name in ("done","seed_applied"):
        if state[name] not in ("true","false"):
            raise intake.SpanIntakeError("parent durable boolean state is invalid")
    cursor=(int(state["next_section"]),int(state["next_span"]))
    if min(cursor)<0:
        raise intake.SpanIntakeError("parent durable cursor is invalid")
    accounting=json.loads(state["accounting"])
    if (report.get("schema")!=archive.SCHEMA or report.get("manifest_sha256")!=census._digest(manifest)
            or report.get("inventory_scope")!=archive.SCOPE or report.get("complete_all_source_occurrence_inventory") is not False
            or report.get("accounting")!=accounting
            or (report.get("next_section"),report.get("next_span"))!=cursor
            or report.get("complete_source_scan")!=(state["done"]=="true")
            or report.get("seed_applied")!=(state["seed_applied"]=="true")
            or report.get("seed")!=manifest.get("seed")):
        raise intake.SpanIntakeError("parent database/report/manifest state differs")
    for name in ("admitted","formalized","inference_executed","training_executed","proof_authority","semantic_reconstruction_measured","token_counts_measured"):
        if report.get(name) is not False:
            raise intake.SpanIntakeError("parent report claims unsupported authority or execution")
    if (state["seed_applied"]=="true")!=(manifest.get("seed") is not None):
        raise intake.SpanIntakeError("parent seed completion is inconsistent")
    for name in ("source_occurrence_count","target_occurrence_count","outside_target_occurrence_count",
                 "empty_section_count","source_utf8_bytes","source_unicode_characters", "max_source_utf8_bytes","max_source_unicode_characters"):
        if type(accounting.get(name)) is not int or accounting[name]<0:
            raise intake.SpanIntakeError("parent aggregate count is invalid")
    for name in ("all_occurrence_digest","outside_target_digest"):
        if not isinstance(accounting.get(name),str) or not intake._SHA.fullmatch(accounting[name]):
            raise intake.SpanIntakeError("parent ordered digest is invalid")
    if accounting["target_occurrence_count"]+accounting["outside_target_occurrence_count"]!=accounting["source_occurrence_count"]:
        raise intake.SpanIntakeError("parent all/target/outside accounting differs")
    for name,count in (("source_byte_cohorts",accounting["source_occurrence_count"]),
                      ("outside_target_byte_cohorts",accounting["outside_target_occurrence_count"]),
                      ("source_text_origins",accounting["source_occurrence_count"]),
                      ("target_dispositions",accounting["target_occurrence_count"])):
        mapping=accounting.get(name)
        if not isinstance(mapping,dict) or any(type(n) is not int or n<0 for n in mapping.values()) or sum(mapping.values())!=count:
            raise intake.SpanIntakeError("parent aggregate cohort accounting differs")
    examples=accounting.get("outside_target_examples")
    if not isinstance(examples,list) or len(examples)>min(values["example_limit"],accounting["outside_target_occurrence_count"]):
        raise intake.SpanIntakeError("parent outside-target example bound differs")
    count,distinct,invalid=db.execute("SELECT count(*),count(DISTINCT source_span_id),count(*) FILTER "
        "(WHERE source_section_offset<0 OR source_section_span_ordinal<0 OR utf8_bytes<0 OR unicode_characters<0 "
        "OR source_section_offset>? OR (source_section_offset=? AND source_section_span_ordinal>=?)) FROM target_occurrences",
        [cursor[0],cursor[0],cursor[1]]).fetchone()
    dispositions=dict(db.execute("SELECT source_join_disposition,count(*) FROM target_occurrences GROUP BY 1").fetchall())
    if (invalid or count!=accounting["target_occurrence_count"] or count!=report.get("persisted_target_occurrences")
            or distinct!=report.get("distinct_target_span_id_count") or dispositions!=accounting["target_dispositions"]):
        raise intake.SpanIntakeError("parent target rows/counts/cursor/dispositions differ")
    source_footer=intake._parquet(source["path"],max_rows=2_000_000,max_row_group_bytes=values["max_row_group_bytes"])
    total=source_footer.metadata.num_rows
    if (cursor[0]>total or cursor[0]==total and cursor[1]!=0 or
            (state["done"]=="true")!=(cursor[0]==total)):
        raise intake.SpanIntakeError("parent cursor/completion differs from source extent")
    ledger=db.execute("SELECT count(*),count(*) FILTER (WHERE record_kind='span'),"
        "count(DISTINCT source_span_id) FILTER (WHERE record_kind='span' AND source_span_id IS NOT NULL AND source_span_id<>'') "
        "FROM read_parquet(?)",[progress["path"]]).fetchone()
    if ledger!=(report.get("ledger_row_count"),report.get("archived_span_record_count"),report.get("distinct_archived_span_id_count")):
        raise intake.SpanIntakeError("parent archive denominator differs from pinned progress")
    ledger_counts=report.get("ledger_disposition_counts")
    if (not isinstance(ledger_counts,dict) or any(type(n) is not int or n<0 for n in ledger_counts.values())
            or sum(ledger_counts.values())!=ledger[0]):
        raise intake.SpanIntakeError("parent ledger disposition accounting differs")
    derived=db.execute("WITH ledger_rows AS (SELECT record_kind,dataset_id,source_span_id,source_sha256,legal_id "
        "FROM read_parquet(?)), ledger_identities AS (SELECT source_span_id,"
        "count(*) FILTER (WHERE NOT coalesce(("+census.VALID+"),FALSE)) AS invalid_rows,"
        "count(DISTINCT coalesce(source_sha256,''))>1 OR count(DISTINCT coalesce(legal_id,''))>1 AS conflict "
        "FROM ledger_rows WHERE record_kind='span' GROUP BY source_span_id), classified AS (SELECT CASE "
        "WHEN r.record_kind IS DISTINCT FROM 'span' THEN 'excluded_nonspan' "
        "WHEN NOT coalesce(("+census.VALID+"),FALSE) OR s.invalid_rows>0 THEN 'invalid_ledger_identity' "
        "WHEN s.conflict THEN 'ledger_identity_conflict' "
        "WHEN EXISTS (SELECT 1 FROM target_occurrences t WHERE t.source_span_id=r.source_span_id "
        "AND t.source_sha256=r.source_sha256 AND t.legal_id=r.legal_id) THEN 'matched' "
        "WHEN EXISTS (SELECT 1 FROM target_occurrences t WHERE t.source_span_id=r.source_span_id "
        "AND t.source_sha256<>r.source_sha256) THEN 'source_hash_mismatch' "
        "WHEN EXISTS (SELECT 1 FROM target_occurrences t WHERE t.source_span_id=r.source_span_id) THEN 'legal_id_mismatch' "
        "ELSE '"+("unresolved_source" if state["done"]=="true" else "pending_source_scan")+"' END AS disposition "
        "FROM ledger_rows r LEFT JOIN ledger_identities s USING(source_span_id)) SELECT disposition,count(*) FROM classified GROUP BY 1",
        [progress["path"]]).fetchall()
    if dict(derived)!=ledger_counts:
        raise intake.SpanIntakeError("parent ledger dispositions differ from authenticated rows")
    return dict(next_section=cursor[0],next_span=cursor[1],done=state["done"]=="true",
        seed_applied=state["seed_applied"]=="true",source_occurrence_count=accounting["source_occurrence_count"],
        target_occurrence_count=count,outside_target_occurrence_count=accounting["outside_target_occurrence_count"],
        all_occurrence_digest=accounting["all_occurrence_digest"],outside_target_digest=accounting["outside_target_digest"],
        accounting_sha256=census._digest(accounting))


def _noreplace(source,destination):
    """Linux atomic directory rename that refuses a competing destination."""
    if not sys.platform.startswith("linux"):
        raise intake.SpanIntakeError("atomic clone publication requires Linux renameat2(RENAME_NOREPLACE)")
    libc=ctypes.CDLL(None,use_errno=True)
    try:
        rename=libc.renameat2
    except AttributeError as exc:
        raise intake.SpanIntakeError("renameat2 is unavailable; refusing unsafe publication") from exc
    rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    rename.restype=ctypes.c_int
    if rename(-100,os.fsencode(source),-100,os.fsencode(destination),1):
        code=ctypes.get_errno()
        if code==errno.EEXIST:
            raise intake.SpanIntakeError("clone destination already exists")
        raise OSError(code,os.strerror(code))


def _fsync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_exact(incoming,outgoing,expected_bytes):
    """Never write beyond a pinned file length, including on source growth."""
    remaining=expected_bytes
    while remaining:
        block=incoming.read(min(1024*1024,remaining))
        if not block:
            raise intake.SpanIntakeError("parent file became shorter during bounded copy")
        outgoing.write(block)
        remaining-=len(block)
    if incoming.read(1):
        raise intake.SpanIntakeError("parent file grew beyond its pinned copy length")


def clone_archive_generation(*,parent_directory,expected_parent_database_sha256,
        expected_parent_manifest_sha256,expected_parent_report_sha256,
        reconciliation_arguments,max_clone_bytes=128*1024*1024,_after_copy=None,_before_publish=None):
    """Publish a complete authenticated clone; interrupted staging is removed.

    The destination must not exist, and its canonical owned attempt directory
    must already exist. This helper acquires no resource claim; the outer owner
    charges staging and result bytes. Private hooks are test-only, never CLI.
    """
    intake._positive(max_clone_bytes,"max_clone_bytes")
    values=_options(reconciliation_arguments)
    parent=_canonical(parent_directory,directory=True)
    destination=_canonical(values["output_directory"],existing=False)
    destination_parent=_canonical(destination.parent,directory=True)
    destination_parent_identity=(destination_parent.stat().st_dev,destination_parent.stat().st_ino)
    if destination.exists() or destination.is_symlink():
        raise intake.SpanIntakeError("clone destination must be absent")
    if destination.is_relative_to(parent):
        raise intake.SpanIntakeError("clone destination must not mutate the frozen parent")
    hashes={FILES[0]:expected_parent_database_sha256,FILES[1]:expected_parent_manifest_sha256,FILES[2]:expected_parent_report_sha256}
    for digest in hashes.values():
        if not isinstance(digest,str) or not intake._SHA.fullmatch(digest):
            raise intake.SpanIntakeError("all three expected parent file SHA-256 pins are required")
    lock_path=_canonical(parent/"writer.lock")
    if (parent/"reconciliation.duckdb.wal").exists() or (parent/"reconciliation.duckdb.wal").is_symlink():
        raise intake.SpanIntakeError("parent database has an unreconciled WAL")
    with lock_path.open("r") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise intake.SpanIntakeError("parent generation still has a writer") from exc
        lock_witness={"path":str(lock_path),"stat_signature":list(intake._signature(os.fstat(lock.fileno())))}
        pins={}
        for name in FILES:
            file=_canonical(parent/name)
            limit=min(max_clone_bytes,1024*1024 if name=="manifest.json" else 4*1024*1024 if name=="report.json" else max_clone_bytes)
            pins[name]=intake._file_identity(file,hashes[name],max_bytes=limit)
        if sum(p["bytes"] for p in pins.values())>max_clone_bytes:
            raise intake.SpanIntakeError("parent files exceed total clone byte bound")
        manifest=json.loads((parent/"manifest.json").read_text())
        report=json.loads((parent/"report.json").read_text())
        with _bindings(manifest,values) as (progress,source,verify_inputs):
            import duckdb
            db=duckdb.connect(str(parent/"reconciliation.duckdb"),read_only=True)
            try:
                db.execute("SET threads=1")
                db.execute(f"SET memory_limit='{values['memory_mb']}MB'")
                # Custody verification cannot spill into the frozen directory.
                db.execute("SET max_temp_directory_size='0B'")
                parent_state=_consistent(db,manifest,report,values,progress,source)
            finally:
                db.close()
            operator_pins=_operator_pins()
            receipt={"schema":SCHEMA,"status":"authenticated_clone_ready","parent_directory":str(parent),
                "destination_directory":str(destination),"parent_files":{k:_public(v) for k,v in pins.items()},
                "generation_manifest_sha256":census._digest(manifest),"parent_state":parent_state,
                "clone_operator_sha256":operator_pins,"database_copy":"Byte-identical stopped parent database; no target row rewriting",
                "copied_report_scope":"Inherited authenticated parent state, not a new run or resource measurement",
                "publication":"Linux renameat2(RENAME_NOREPLACE) after authenticated copy and fsync",
                "prepublication_failure":"Owned staging removed; no runnable destination",
                "postpublication_resume_failure":"Legitimate clone retained with its committed cursor; frozen parent remains unchanged",
                "source_text_copied":False,"models_executed":False,"training_executed":False,"proof_authority":False,
                "max_clone_bytes":max_clone_bytes,"total_staged_file_bytes":0}
            raw=lambda: (json.dumps(receipt,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()
            while True:
                size=sum(p["bytes"] for p in pins.values())+len(raw())
                if receipt["total_staged_file_bytes"]==size:
                    break
                receipt["total_staged_file_bytes"]=size
            if size>max_clone_bytes:
                raise intake.SpanIntakeError("clone files and custody receipt exceed total byte bound")
            if size>values["storage_max_bytes"]:
                raise intake.SpanIntakeError("clone exceeds its controller output bound")
            staging=destination_parent/("."+destination.name+".clone-"+uuid.uuid4().hex)
            staging.mkdir(mode=0o700)
            published=False
            try:
                for name in FILES:
                    copied=staging/name
                    with (parent/name).open("rb") as incoming,copied.open("xb") as outgoing:
                        if list(intake._signature(os.fstat(incoming.fileno())))!=pins[name]["stat_signature"]:
                            raise intake.SpanIntakeError("parent file changed before bounded copy")
                        _copy_exact(incoming,outgoing,pins[name]["bytes"])
                        if list(intake._signature(os.fstat(incoming.fileno())))!=pins[name]["stat_signature"]:
                            raise intake.SpanIntakeError("parent file changed during bounded copy")
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                    intake._file_identity(copied,hashes[name],max_bytes=pins[name]["bytes"])
                    if _after_copy:
                        _after_copy(name,staging)
                with (staging/"writer.lock").open("x") as stream:
                    stream.flush()
                    os.fsync(stream.fileno())
                with (staging/"clone-custody.json").open("xb") as stream:
                    stream.write(raw())
                    stream.flush()
                    os.fsync(stream.fileno())
                if census._storage(staging,max_clone_bytes)!=size:
                    raise intake.SpanIntakeError("staged clone footprint differs from custody receipt")
                _fsync_directory(staging)
                if _before_publish:
                    _before_publish(staging,destination)
                for name in FILES:
                    intake._file_identity(_canonical(staging/name),hashes[name],max_bytes=pins[name]["bytes"])
                if (staging/"clone-custody.json").read_bytes()!=raw() or census._storage(staging,max_clone_bytes)!=size:
                    raise intake.SpanIntakeError("staged custody/bytes changed before publication")
                for original in (parent,progress["path"],source["path"],destination_parent):
                    _canonical(original,directory=original in (parent,destination_parent))
                if (destination_parent.stat().st_dev,destination_parent.stat().st_ino)!=destination_parent_identity:
                    raise intake.SpanIntakeError("owned destination directory changed during cloning")
                for pin in pins.values():
                    intake._unchanged(pin)
                intake._unchanged(lock_witness)
                verify_inputs()
                if _operator_pins()!=operator_pins:
                    raise intake.SpanIntakeError("clone operator changed during custody")
                if (parent/"reconciliation.duckdb.wal").exists():
                    raise intake.SpanIntakeError("parent WAL appeared during custody")
                _noreplace(staging,destination)
                published=True
                _fsync_directory(destination_parent)
                return receipt
            finally:
                if not published and staging.exists():
                    shutil.rmtree(staging)
                    _fsync_directory(destination_parent)


def run_archive_resume(*,parent_directory,expected_parent_database_sha256,
        expected_parent_manifest_sha256,expected_parent_report_sha256,
        max_clone_bytes=128*1024*1024,**reconciliation_arguments):
    """Clone under custody, then invoke the unchanged controller.

    A later controller refusal preserves the valid cloned generation and its
    durable cursor. Callers must not retry clone publication into that directory.
    """
    clone_archive_generation(parent_directory=parent_directory,
        expected_parent_database_sha256=expected_parent_database_sha256,
        expected_parent_manifest_sha256=expected_parent_manifest_sha256,
        expected_parent_report_sha256=expected_parent_report_sha256,
        reconciliation_arguments=reconciliation_arguments,max_clone_bytes=max_clone_bytes)
    return archive.run_archive_reconciliation(**reconciliation_arguments)
