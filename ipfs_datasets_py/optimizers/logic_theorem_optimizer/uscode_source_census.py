"""Local, restartable occurrence census; no inference or imported authority."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from . import legacy_span_intake as intake

SCHEMA = "uscode-source-occurrence-census/v1"
VALID = ("source_span_id IS NOT NULL AND source_span_id<>'' AND length(source_span_id)<=512 "
         "AND source_sha256 IS NOT NULL AND regexp_full_match(source_sha256,'[0-9a-f]{64}') "
         "AND legal_id IS NOT NULL AND legal_id<>'' AND length(legal_id)<=2048 "
         "AND coalesce(dataset_id,'') IN ('','ipfs_uscode','justicedao/ipfs_uscode')")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _durable_json(path: Path, value: Any) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as f:
        f.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _source_code_pins() -> dict[str, str]:
    from ...logic.autoformal import uscode_ingest, constitution_inventory
    from . import uscode_dataset
    return {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in [("intake", intake), ("uscode_ingest", uscode_ingest),
                                  ("constitution_inventory", constitution_inventory),
                                  ("uscode_dataset", uscode_dataset)]} | {
        "census": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


@contextmanager
def _writer(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or directory.resolve() != directory.absolute():
        raise intake.SpanIntakeError("output directory must be a canonical local directory")
    lock_path = directory / "writer.lock"
    if lock_path.is_symlink():
        raise intake.SpanIntakeError("writer lock must not be a symlink")
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise intake.SpanIntakeError("census already has a writer") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _tokenizer(path: str | None, sha256: str | None, producer_id: str | None,
               revision: str | None):
    if not any((path, sha256, producer_id, revision)):
        return None, None
    if not all((path, sha256, producer_id, revision)):
        raise intake.SpanIntakeError("tokenizer path/hash/producer/revision must be configured together")
    if not intake._REVISION.fullmatch(revision) or len(producer_id) > 512:
        raise intake.SpanIntakeError("tokenizer requires an immutable revision and bounded producer ID")
    pin = intake._file_identity(path, sha256, max_bytes=64 * 1024 * 1024)
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(pin["path"])
    if tokenizer.truncation is not None:
        raise intake.SpanIntakeError("complete-span token census forbids configured truncation")
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer, {**{k:v for k,v in pin.items() if k != "stat_signature"},
                       "producer_id": producer_id, "revision": revision,
                       "add_special_tokens": True, "padding": False, "truncation": False}


def _initialize(connection, progress, *, max_row_group_bytes: int) -> intake.ProgressIndex:
    parquet = intake._parquet(progress["path"], max_rows=2_000_000,
                              max_row_group_bytes=max_row_group_bytes)
    required = {"record_kind", "dataset_id", "source_span_id", "source_sha256", "legal_id"}
    if not required.issubset(parquet.schema_arrow.names):
        raise intake.SpanIntakeError("progress parquet is missing source identity columns")
    import pyarrow as pa
    if any(not pa.types.is_string(parquet.schema_arrow.field(n).type) for n in required):
        raise intake.SpanIntakeError("progress identity columns must be strings")
    connection.execute("CREATE TABLE IF NOT EXISTS census_state (key VARCHAR PRIMARY KEY, value VARCHAR)")
    # The immutable queue is already durable. Rebuild inexpensive TEMP indexes
    # instead of persisting duplicate identity/hash strings on every generation.
    connection.execute("CREATE TEMP TABLE ledger_rows AS SELECT row_number() OVER ()-1 AS ledger_row, "
                       "record_kind,dataset_id,source_span_id,source_sha256,legal_id "
                       "FROM read_parquet(?)", [progress["path"]])
    datasets = {r[0] for r in connection.execute(
        "SELECT DISTINCT dataset_id FROM ledger_rows WHERE record_kind='meta'").fetchall()}
    if not datasets or not datasets.issubset(intake._DATASETS):
        raise intake.SpanIntakeError("progress metadata is not bound to the U.S. Code dataset")
    connection.execute("CREATE TEMP TABLE ledger_identities AS SELECT source_span_id, count(*) AS ledger_rows, "
        "count(*) FILTER (WHERE NOT coalesce((" + VALID + "),FALSE)) AS invalid_rows, "
        "count(DISTINCT coalesce(source_sha256,''))>1 OR count(DISTINCT coalesce(legal_id,''))>1 AS conflict "
        "FROM ledger_rows WHERE record_kind='span' GROUP BY source_span_id")
    if connection.execute("SELECT count(*) FROM census_state WHERE key='initialized'").fetchone()[0] == 0:
        connection.execute("BEGIN")
        try:
            connection.execute("CREATE TABLE source_occurrences (occurrence_id BLOB PRIMARY KEY, "
                "source_span_id VARCHAR, source_sha256 VARCHAR, legal_id VARCHAR, entry_cid VARCHAR, "
                "title VARCHAR, section VARCHAR, citation VARCHAR, source_section_offset BIGINT, "
                "historical_document_batch_index BIGINT, historical_span_ordinal BIGINT, "
                "utf8_bytes BIGINT, unicode_characters BIGINT, token_count BIGINT, "
                "byte_cohort VARCHAR, token_cohort VARCHAR, source_join_disposition VARCHAR)")
            connection.execute("INSERT INTO census_state VALUES ('initialized','true'),('next_section','0'),('done','false'),('intake_counts','{}')")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    connection.execute("CREATE TEMP TABLE progress_join_targets AS SELECT DISTINCT r.source_span_id, "
        "r.source_sha256,r.legal_id,FALSE AS matched FROM ledger_rows r JOIN ledger_identities s USING(source_span_id) "
        "WHERE r.record_kind='span' AND NOT s.conflict AND s.invalid_rows=0")
    connection.execute("CREATE UNIQUE INDEX progress_join_targets_id ON progress_join_targets(source_span_id)")
    connection.execute("UPDATE progress_join_targets SET matched=TRUE WHERE source_span_id IN "
        "(SELECT source_span_id FROM source_occurrences WHERE source_join_disposition='matched')")
    count = connection.execute("SELECT count(*) FROM progress_join_targets").fetchone()[0]
    return intake.ProgressIndex(connection, "progress_join_targets", progress,
                                {"unique_valid_nonconflict_span_count": count})


def _cohort(number: int | None, bands: tuple[int, ...]) -> str | None:
    if number is None:
        return None
    return next((f"le_{n}" for n in bands if number <= n), f"gt_{bands[-1]}")


def _occurrence(row, source, tokenizer, disposition: str) -> dict:
    binding = {"source_repository": intake.SOURCE_REPOSITORY, "source_revision": source["revision"],
               "source_artifact_sha256": source["sha256"], "entry_cid": row["entry_cid"],
               "source_section_offset": row["source_section_offset"], "source_span_id": row["source_span_id"],
               "source_sha256": row["source_sha256"], "release_id": source["release_id"],
               "identity_reconstruction": intake.IDENTITY_RECONSTRUCTION,
               "historical_document_batch_index": row["historical_document_batch_index"],
               "historical_span_ordinal": row["historical_span_ordinal"]}
    tokens = len(tokenizer.encode(row["text"], add_special_tokens=True).ids) if tokenizer else None
    size = len(row["text"].encode("utf-8"))
    return {"occurrence_id": bytes.fromhex(_digest(binding)), **{k:row[k] for k in (
        "source_span_id", "source_sha256", "legal_id", "entry_cid", "title", "section", "citation",
        "source_section_offset", "historical_document_batch_index", "historical_span_ordinal")},
        "utf8_bytes": size, "unicode_characters": len(row["text"]), "token_count": tokens,
        "byte_cohort": _cohort(size, (512,4096,32768,131072)),
        "token_cohort": _cohort(tokens, (512,1024,2048,4096,8192)),
        "source_join_disposition": disposition}


def _storage(directory: Path, limit: int) -> int:
    size = 0
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise intake.SpanIntakeError("census output contains a symlink")
        if path.is_file():
            size += path.stat().st_size
    if size > limit:
        raise intake.SpanIntakeError("census output exceeded its storage bound; durable cursor retained")
    return size


def _report(connection, directory, manifest, completed, *, storage_max_bytes, export_full_parquet):
    unmatched = "unresolved_source" if completed else "pending_source_scan"
    connection.execute("CREATE OR REPLACE TEMP VIEW ledger_dispositions AS SELECT r.*, CASE "
        "WHEN r.record_kind IS DISTINCT FROM 'span' THEN 'excluded_nonspan' "
        "WHEN NOT coalesce((" + VALID + "),FALSE) OR s.invalid_rows>0 THEN 'invalid_ledger_identity' "
        "WHEN s.conflict THEN 'ledger_identity_conflict' "
        "WHEN EXISTS (SELECT 1 FROM source_occurrences c WHERE c.source_span_id=r.source_span_id "
        "AND c.source_sha256=r.source_sha256 AND c.legal_id=r.legal_id) THEN 'matched' "
        "WHEN EXISTS (SELECT 1 FROM source_occurrences c WHERE c.source_span_id=r.source_span_id "
        "AND c.source_sha256<>r.source_sha256) THEN 'source_hash_mismatch' "
        "WHEN EXISTS (SELECT 1 FROM source_occurrences c WHERE c.source_span_id=r.source_span_id) THEN 'legal_id_mismatch' "
        "ELSE '" + unmatched + "' END AS disposition FROM ledger_rows r LEFT JOIN ledger_identities s USING(source_span_id)")
    def counts(table, column):
        return {str(k):v for k,v in connection.execute(f"SELECT {column},count(*) FROM {table} GROUP BY 1 ORDER BY 1").fetchall()}
    exports = []
    queries = [("source-occurrences", "SELECT * FROM source_occurrences ORDER BY occurrence_id"),
                        ("ledger-dispositions", "SELECT * FROM ledger_dispositions ORDER BY ledger_row"),
                        ("ledger-conflicts", "SELECT * FROM ledger_identities WHERE conflict OR invalid_rows>0")] if export_full_parquet else [
        ("census-disposition-counts", "SELECT 'ledger' AS scope,disposition AS disposition,count(*) AS records "
         "FROM ledger_dispositions GROUP BY 1,2 UNION ALL SELECT 'source',source_join_disposition,count(*) "
         "FROM source_occurrences GROUP BY 1,2")]
    for name, query in queries:
        target = directory / (name + ".parquet")
        temp = target.with_name(target.name + ".tmp")
        connection.execute("COPY (" + query + ") TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 8192)", [str(temp)])
        with temp.open("rb") as f:
            os.fsync(f.fileno())
        os.replace(temp, target)
        pin = intake._file_identity(target, hashlib.sha256(target.read_bytes()).hexdigest(), max_bytes=storage_max_bytes)
        exports.append({k:v for k,v in pin.items() if k != "stat_signature"})
        _storage(directory, storage_max_bytes)
    stats = {"ledger_row_count":connection.execute("SELECT count(*) FROM ledger_rows").fetchone()[0],
        "record_kind_counts":counts("ledger_rows", "record_kind"),
        "ledger_span_record_count":connection.execute("SELECT count(*) FROM ledger_rows WHERE record_kind='span'").fetchone()[0],
        "distinct_nonempty_ledger_span_id_count":connection.execute("SELECT count(*) FROM ledger_identities WHERE source_span_id IS NOT NULL AND source_span_id<>''").fetchone()[0],
        "ledger_conflicting_id_count":connection.execute("SELECT count(*) FROM ledger_identities WHERE conflict").fetchone()[0],
        "ledger_invalid_record_count":connection.execute("SELECT count(*) FROM ledger_rows WHERE record_kind='span' AND NOT coalesce(("+VALID+"),FALSE)").fetchone()[0],
        "source_occurrence_count":connection.execute("SELECT count(*) FROM source_occurrences").fetchone()[0],
        "distinct_source_section_offset_count":connection.execute("SELECT count(DISTINCT source_section_offset) FROM source_occurrences").fetchone()[0],
        "distinct_regenerated_span_id_count":connection.execute("SELECT count(DISTINCT source_span_id) FROM source_occurrences").fetchone()[0],
        "ledger_disposition_counts":counts("ledger_dispositions", "disposition"),
        "source_disposition_counts":counts("source_occurrences", "source_join_disposition"),
        "byte_cohorts":counts("source_occurrences", "byte_cohort"),
        "token_cohorts":counts("source_occurrences", "token_cohort") if manifest["tokenizer"] else None,
        "next_section":int(connection.execute("SELECT value FROM census_state WHERE key='next_section'").fetchone()[0])}
    length_row = connection.execute("SELECT coalesce(sum(utf8_bytes),0),coalesce(max(utf8_bytes),0),"
        "coalesce(sum(unicode_characters),0),coalesce(max(unicode_characters),0),"
        "count(*) FILTER (WHERE unicode_characters>32768),count(*) FILTER (WHERE utf8_bytes>1048576) FROM source_occurrences").fetchone()
    stats["source_lengths"] = dict(zip(("total_utf8_bytes","max_utf8_bytes","total_unicode_characters",
        "max_unicode_characters","above_historical_32768_characters","above_new_1048576_utf8_bytes"),length_row))
    stats["intake_control_counts"] = json.loads(connection.execute("SELECT value FROM census_state WHERE key='intake_counts'").fetchone()[0])
    largest = connection.execute("SELECT source_span_id,source_sha256,source_section_offset,legal_id,"
        "utf8_bytes,unicode_characters,token_count FROM source_occurrences ORDER BY utf8_bytes DESC,source_span_id LIMIT 10").fetchall()
    stats["largest_occurrences"] = [dict(zip(("source_span_id","source_sha256","source_section_offset","legal_id",
        "utf8_bytes","unicode_characters","token_count"),r)) for r in largest]
    report = {"schema":SCHEMA, "manifest_sha256":_digest(manifest), "complete_source_scan":completed,
        "scope":"Exact historical extraction/source joins only; no model, training, admission, or imported remote completion authority",
        "admitted":False, "formalized":False, "training_executed":False, "inference_executed":False,
        "token_counts_measured":manifest["tokenizer"] is not None, "statistics":stats, "exports":exports,
        "full_parquet_exported":export_full_parquet,
        "durable_inventory":"census.duckdb/source_occurrences; ledger indexes are TEMP and rebuilt from the pinned queue",
        "source_text_storage":"No copied source text; occurrence hashes and physical source-row references bind the pinned original artifact",
        "extraction_text_scope":"Exact historical normalized sentence bytes; original section bytes remain in the pinned source artifact",
        "output_bytes_before_report":_storage(directory, storage_max_bytes)}
    _durable_json(directory / "report.json", report)
    _storage(directory, storage_max_bytes)
    return report


def run_source_census(*, progress_parquet: str, progress_sha256: str, progress_revision: str,
        source_parquet: str, source_sha256: str, output_directory: str,
        source_revision: str = intake.SOURCE_REVISION, release_id: str = intake.DEFAULT_RELEASE_ID,
        section_batch_size: int = 4, max_batches: int | None = None, memory_mb: int = 1024,
        storage_max_bytes: int = 128*1024*1024, max_row_group_bytes: int = 2*1024*1024*1024,
        max_section_bytes: int = 8*1024*1024, max_batch_bytes: int = 32*1024*1024,
        max_batch_spans: int = 8192, tokenizer_json: str | None = None,
        tokenizer_sha256: str | None = None, tokenizer_id: str | None = None,
        tokenizer_revision: str | None = None, export_full_parquet: bool = False,
        _before_commit: Callable | None = None) -> dict:
    """Scan an isolated local generation, or resume exactly its pinned inputs.

    ``max_batches`` deliberately stops after committed source batches. Changing
    output batch size is safe; changing source/code/tokenizer pins is refused.
    ``_before_commit`` is an interruption-test hook, never a CLI option.
    """
    for revision in (progress_revision, source_revision):
        if not isinstance(revision,str) or not intake._REVISION.fullmatch(revision):
            raise intake.SpanIntakeError("immutable complete repository revisions are required")
    for label, value in [("memory_mb",memory_mb),("storage_max_bytes",storage_max_bytes),
                          ("max_row_group_bytes",max_row_group_bytes)]:
        intake._positive(value,label)
    if max_batches is not None:
        intake._positive(max_batches,"max_batches")
    if type(section_batch_size) is not int or not 1 <= section_batch_size <= 256:
        raise intake.SpanIntakeError("section_batch_size must be in 1..256")
    if type(export_full_parquet) is not bool:
        raise intake.SpanIntakeError("export_full_parquet must be a boolean")
    progress = intake._file_identity(progress_parquet,progress_sha256,max_bytes=256*1024*1024)
    progress.update(repository_id=intake.PROGRESS_REPOSITORY, revision=progress_revision,
                    path_in_repo="autoformal/uscode/resume-checkpoint.parquet")
    source = intake._file_identity(source_parquet,source_sha256,max_bytes=512*1024*1024)
    source.update(repository_id=intake.SOURCE_REPOSITORY,revision=source_revision,release_id=release_id)
    tokenizer, token_pin = _tokenizer(tokenizer_json,tokenizer_sha256,tokenizer_id,tokenizer_revision)
    manifest = {"schema":SCHEMA, "progress":{k:v for k,v in progress.items() if k != "stat_signature"},
        "source":{k:v for k,v in source.items() if k != "stat_signature"}, "tokenizer":token_pin,
        "source_code_sha256":_source_code_pins(), "identity_reconstruction":intake.IDENTITY_RECONSTRUCTION,
        "bounds":{"max_section_bytes":max_section_bytes,"max_batch_bytes":max_batch_bytes,"max_batch_spans":max_batch_spans,
                  "max_row_group_bytes":max_row_group_bytes}, "source_text_copied":False}
    directory = Path(output_directory).absolute()
    with _writer(directory):
        marker = directory / "manifest.json"
        dbpath = directory / "census.duckdb"
        if marker.is_symlink() or dbpath.is_symlink():
            raise intake.SpanIntakeError("manifest and database must not be symlinks")
        if marker.exists():
            if json.loads(marker.read_text()) != manifest:
                raise intake.SpanIntakeError("resume source/code/tokenizer/configuration pins differ")
        else:
            if dbpath.exists():
                raise intake.SpanIntakeError("refusing an existing database without this census manifest")
            _durable_json(marker,manifest)
        import duckdb
        import pyarrow as pa
        connection = duckdb.connect(str(dbpath))
        try:
            connection.execute("SET threads=1")
            connection.execute(f"SET memory_limit='{memory_mb}MB'")
            connection.execute("SET temp_directory=?",[str(directory / "spill")])
            spill_mb = max(1,min(128,storage_max_bytes//(4*1024*1024)))
            connection.execute(f"SET max_temp_directory_size='{spill_mb}MB'")
            connection.execute("SET checkpoint_threshold='8MB'")
            index = _initialize(connection,progress,max_row_group_bytes=max_row_group_bytes)
            _storage(directory,storage_max_bytes)
            cursor = int(connection.execute("SELECT value FROM census_state WHERE key='next_section'").fetchone()[0])
            completed = connection.execute("SELECT value FROM census_state WHERE key='done'").fetchone()[0] == "true"
            batches = 0
            if not completed:
                iterator = intake.iter_joined_section_batches(index,source["path"],expected_laws_sha256=source_sha256,
                    source_revision=source_revision,release_id=release_id,start_section=cursor,
                    section_batch_size=section_batch_size,max_row_group_bytes=max_row_group_bytes,
                    max_section_bytes=max_section_bytes,max_batch_bytes=max_batch_bytes,max_batch_spans=max_batch_spans,
                    diagnostic_limit=0,include_candidates=True)
                for batch in iterator:
                    candidates = batch["candidate_rows"]
                    ids = sorted({r["source_span_id"] for r in candidates})
                    states = {}
                    if ids:
                        connection.register("census_candidate_ids",pa.table({"source_span_id":ids}))
                        try:
                            states = {k:(conflict,invalid) for k,conflict,invalid in connection.execute(
                                "SELECT s.source_span_id,s.conflict,s.invalid_rows FROM ledger_identities s "
                                "JOIN census_candidate_ids c USING(source_span_id)").fetchall()}
                        finally:
                            connection.unregister("census_candidate_ids")
                    rows = []
                    for row in candidates:
                        conflict,invalid = states.get(row["source_span_id"],(False,0))
                        disposition = ("ledger_identity_conflict" if conflict else "invalid_ledger_identity" if invalid
                                       else row["source_join_disposition"])
                        rows.append(_occurrence(row,source,tokenizer,disposition))
                    connection.execute("BEGIN")
                    try:
                        if rows:
                            connection.register("census_occurrence_batch",pa.Table.from_pylist(rows))
                            try:
                                connection.execute("INSERT INTO source_occurrences SELECT * FROM census_occurrence_batch")
                            finally:
                                connection.unregister("census_occurrence_batch")
                        connection.execute("UPDATE census_state SET value=? WHERE key='next_section'",[str(batch["next_section"])])
                        connection.execute("UPDATE census_state SET value=? WHERE key='done'",["true" if batch["done"] else "false"])
                        cumulative = json.loads(connection.execute("SELECT value FROM census_state WHERE key='intake_counts'").fetchone()[0])
                        for key,value in batch["counts"].items():
                            cumulative[key] = cumulative.get(key,0) + value
                        connection.execute("UPDATE census_state SET value=? WHERE key='intake_counts'",[_json(cumulative)])
                        if _before_commit:
                            _before_commit(batch)
                        connection.execute("COMMIT")
                    except Exception:
                        connection.execute("ROLLBACK")
                        raise
                    completed = batch["done"]
                    batches += 1
                    _storage(directory,storage_max_bytes)
                    if completed or (max_batches is not None and batches >= max_batches):
                        break
            intake._unchanged(source)
            intake._unchanged(progress)
            connection.execute("CHECKPOINT")
            report = _report(connection,directory,manifest,completed,storage_max_bytes=storage_max_bytes,
                             export_full_parquet=export_full_parquet)
            connection.execute("CHECKPOINT")
            return report
        finally:
            connection.close()
