"""Bounded identity-only counter diagnosis of an accepted stopped generation.

Original source, text, vectors, models and tokenizers are never opened. Every
retained historical ID is rebuilt before any alternate counter is considered.
Exact hypothesis matches remain candidates, not aliases or global uniqueness.
"""
from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import resource
import shutil
import stat
import sys
import tempfile
import time

from . import uscode_archive_reconciliation as archive
from . import uscode_archive_resume as resume

SCHEMA = "uscode-retained-ordinal-diagnosis/v1"
REVIEW_SCHEMA = "uscode-bounded-window-independent-results-review/v2"
PROFILE = "historical-64-document-ordinal/v1"
HYPOTHESIS = "per-document-span-ordinal-hypothesis/v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
SPAN = re.compile(r"uscode-span-[0-9a-f]{64}\Z")
MAX_METADATA_BYTES = 2 * 1024 * 1024


class IdentityRecoveryError(ValueError):
    """Custody, compatibility or a bounded diagnostic refused."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise IdentityRecoveryError(message)


def _positive(value, name, ceiling):
    _require(type(value) is int and 0 < value <= ceiling, f"{name} must be positive and <= {ceiling}")


def _canonical(value, *, existing=True, directory=False):
    p = Path(value)
    _require(p.is_absolute() and p.resolve(strict=existing) == p and not p.is_symlink(), "canonical paths without aliases required")
    if existing:
        _require(p.is_dir() if directory else p.is_file(), "existing regular input or directory required")
    return p


def _signature(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


class _Witness:
    def __init__(self, path, expected, limit):
        _require(isinstance(expected, str) and bool(SHA.fullmatch(expected)), "explicit exact SHA-256 pin required")
        self.path = _canonical(path)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            s = os.fstat(self.fd)
            _require(stat.S_ISREG(s.st_mode) and 0 < s.st_size <= limit, "regular input exceeds byte bound")
            self.signature = _signature(s)
            self.sha256 = expected
            self.verify()
        except BaseException:
            os.close(self.fd)
            raise

    def verify(self):
        _canonical(self.path)
        _require(_signature(os.fstat(self.fd)) == self.signature
                 and _signature(self.path.stat()) == self.signature and not self.path.is_symlink(), "input witness changed")
        digest = hashlib.sha256()
        os.lseek(self.fd, 0, os.SEEK_SET)
        remaining = self.signature[2]
        while remaining:
            block = os.read(self.fd, min(1024 * 1024, remaining))
            _require(bool(block), "pinned input shortened")
            remaining -= len(block)
            digest.update(block)
        _require(not os.read(self.fd, 1), "pinned input grew")
        _require(digest.hexdigest() == self.sha256, "input SHA-256 differs")
        _canonical(self.path)
        _require(_signature(os.fstat(self.fd)) == self.signature
                 and _signature(self.path.stat()) == self.signature, "input changed while hashing")

    def metadata(self):
        return dict(path=str(self.path), sha256=self.sha256, bytes=self.signature[2], stat_signature=list(self.signature))

    def read_json(self):
        _require(self.signature[2] <= MAX_METADATA_BYTES, "input JSON exceeds metadata bound")
        os.lseek(self.fd, 0, os.SEEK_SET)
        data = bytearray()
        while len(data) < self.signature[2]:
            part = os.read(self.fd, self.signature[2] - len(data))
            _require(bool(part), "input JSON shortened")
            data.extend(part)
        value = json.loads(data)
        self.verify()
        _require(isinstance(value, dict), "input JSON object required")
        return value

    def close(self):
        os.close(self.fd)


def _bounded_hash(path, limit):
    """Capture a new regular artifact without an unbounded body read."""
    path = _canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        s = os.fstat(fd)
        _require(stat.S_ISREG(s.st_mode) and 0 < s.st_size <= limit, "staged artifact exceeds byte bound")
        signature = _signature(s)
        digest = hashlib.sha256()
        remaining = s.st_size
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            _require(bool(block), "staged artifact shortened")
            remaining -= len(block)
            digest.update(block)
        _require(not os.read(fd, 1), "staged artifact grew")
        _canonical(path)
        _require(_signature(os.fstat(fd)) == signature and _signature(path.stat()) == signature,
                 "staged artifact changed while hashing")
        return digest.hexdigest(), s.st_size
    finally:
        os.close(fd)


def _runtime_metrics(started):
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = "KiB" if sys.platform.startswith("linux") else "bytes" if sys.platform == "darwin" else "platform_native"
    return dict(elapsed_seconds=time.monotonic()-started,
        elapsed_seconds_scope="call entry through report creation; final custody fences and publication excluded",
        process_memory=dict(metric="RUSAGE_SELF.ru_maxrss",scope="process-lifetime high-water observed at report creation",
            platform=sys.platform,native_value=peak,native_unit=unit,
            bytes=int(peak*1024) if unit == "KiB" else int(peak) if unit == "bytes" else None))


def _owner_pins():
    root = Path(__file__).resolve().parents[3]
    files = {"diagnosis": Path(__file__), "diagnosis_cli": root / "scripts/ops/legal_ir/diagnose_uscode_identity.py",
             "atomic_publication": Path(resume.__file__)}
    return {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}


def _pin_agrees(saved, witness):
    return isinstance(saved, dict) and all(saved.get(k) == witness.metadata()[k] for k in ("path", "sha256", "bytes"))


def _bindings(manifest, report, review, pins):
    _require(review.get("schema") == REVIEW_SCHEMA and review.get("passed") is True
             and review.get("completed") is True and review.get("findings") == [], "completed accepted independent review required")
    checks = review.get("checks")
    _require(isinstance(checks, list) and 0 < len(checks) <= 256
             and all(isinstance(c, dict) and c.get("passed") is True for c in checks), "all independent checks must pass")
    for key, name in (("results/reconciliation.duckdb", "database"), ("results/manifest.json", "manifest"),
                      ("results/report.json", "report")):
        _require(_pin_agrees(review.get("actual_receipt_pins", {}).get(key), pins[name]), "accepted review final-file binding differs")
    _require(_pin_agrees(review.get("input_pins", {}).get("progress"), pins["progress"]), "accepted review progress binding differs")
    _require(manifest.get("schema") == archive.SCHEMA and manifest.get("identity_reconstruction") == PROFILE
             and manifest.get("inventory_scope") == archive.SCOPE, "known retained identity profile required")
    code = archive._pins()
    _require(manifest.get("source_code_sha256") == code
             and all(review.get("code_pins", {}).get(k, {}).get("sha256") == v for k, v in code.items()), "retained extraction code pins differ")
    _require(_pin_agrees(manifest.get("progress"), pins["progress"]), "manifest progress binding differs")
    source = manifest.get("source")
    _require(isinstance(source, dict) and isinstance(source.get("release_id"), str)
             and source.get("release_id") == archive.intake.DEFAULT_RELEASE_ID
             and source.get("revision") == archive.intake.SOURCE_REVISION
             and source.get("repository_id") == archive.intake.SOURCE_REPOSITORY
             and isinstance(source.get("sha256"), str) and SHA.fullmatch(source["sha256"]), "known source release/profile required")
    _require(all(review.get("input_pins", {}).get("source", {}).get(k) == source.get(k)
                 for k in ("path", "sha256", "bytes")), "review source reference differs")
    _require(report.get("schema") == archive.SCHEMA and report.get("manifest_sha256") == _digest(manifest)
             and report.get("inventory_scope") == archive.SCOPE and report.get("complete_source_scan") is True
             and report.get("complete_all_source_occurrence_inventory") is False, "accepted exhausted report/profile required")
    for name in ("inference_executed", "training_executed", "semantic_reconstruction_measured", "proof_authority", "token_counts_measured", "admitted", "formalized"):
        _require(report.get(name) is False, "retained generation must remain source-only")
    _require(review.get("independently_rebuilt_final_accounting") == report.get("accounting")
             and review.get("final_cursor") == [report.get("next_section"), report.get("next_span")], "accepted accounting/cursor binding differs")
    return code


def _sql_path(path):
    return "'" + str(path).replace("'", "''") + "'"


def _load_retained(db, manifest, report, max_rows):
    tables = {r[0] for r in db.execute("SHOW TABLES FROM saved").fetchall()}
    _require(tables == {"reconciliation_state", "target_occurrences"}, "retained database schema differs")
    state = dict(db.execute("SELECT key,value FROM saved.reconciliation_state").fetchall())
    _require(set(state) == {"next_section", "next_span", "done", "accounting", "seed_applied"}
             and state["done"] == "true" and state["seed_applied"] in ("true", "false"), "stopped durable state differs")
    count = db.execute("SELECT count(*) FROM saved.target_occurrences").fetchone()[0]
    _require(count <= max_rows, "retained row bound exceeded")
    accounting = json.loads(state["accounting"])
    _require(accounting == report["accounting"] and count == accounting.get("target_occurrence_count")
             and count == report.get("persisted_target_occurrences")
             and accounting.get("source_occurrence_count") == count + accounting.get("outside_target_occurrence_count", -1), "retained accounting differs")
    _require([int(state["next_section"]), int(state["next_span"])] == [report["next_section"], report["next_span"]]
             and report["next_span"] == 0 and (state["seed_applied"] == "true") == report.get("seed_applied")
             and report.get("seed") == manifest.get("seed"), "durable cursor/seed differs")
    columns = tuple(c[0] for c in db.execute("SELECT * FROM saved.target_occurrences LIMIT 0").description)
    _require(columns == archive.OLD_COLUMNS + archive.EXTRA_COLUMNS, "retained occurrence columns differ")
    db.execute("CREATE TEMP TABLE retained AS SELECT * FROM saved.target_occurrences")
    _require(db.execute("SELECT count(DISTINCT occurrence_id) FROM retained").fetchone()[0] == count, "duplicate physical occurrence IDs")
    _require(db.execute("SELECT count(DISTINCT source_span_id) FROM retained").fetchone()[0] == report.get("distinct_target_span_id_count"), "distinct target accounting differs")
    dispositions = dict(db.execute("SELECT source_join_disposition,count(*) FROM retained GROUP BY 1").fetchall())
    _require(dispositions == accounting.get("target_dispositions"), "retained dispositions differ")
    return count


def _load_archive(db, path, report, max_rows):
    count = db.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    _require(count <= max_rows, "archive row bound exceeded")
    db.execute("CREATE TEMP TABLE ledger AS SELECT record_kind,dataset_id,source_span_id,source_sha256,legal_id FROM read_parquet(?)", [str(path)])
    _require(count == report.get("ledger_row_count"), "archive physical row count differs")
    datasets = {r[0] for r in db.execute("SELECT DISTINCT dataset_id FROM ledger WHERE record_kind='meta'").fetchall()}
    _require(bool(datasets) and datasets.issubset(archive.intake._DATASETS), "archive source dataset metadata differs")
    _require(not db.execute("SELECT count(*) FROM ledger WHERE record_kind NOT IN ('span','meta') OR record_kind IS NULL").fetchone()[0], "unsupported archive record kind")
    _require(not db.execute("SELECT count(*) FROM (SELECT source_span_id FROM ledger WHERE record_kind='span' GROUP BY 1 HAVING count(*)>1)").fetchone()[0], "archive duplicate or conflicting IDs refuse")
    invalid = db.execute("SELECT count(*) FROM ledger WHERE record_kind='span' AND NOT coalesce("
        "regexp_full_match(source_span_id,'uscode-span-[0-9a-f]{64}') AND regexp_full_match(source_sha256,'[0-9a-f]{64}') "
        "AND length(legal_id)>0 AND length(legal_id)<=512,FALSE)").fetchone()[0]
    _require(not invalid, "invalid archive identity fields")
    span_count = db.execute("SELECT count(*) FROM ledger WHERE record_kind='span'").fetchone()[0]
    _require(span_count == report.get("archived_span_record_count") == report.get("distinct_archived_span_id_count"), "archive distinct/physical counts differ")
    _require(not db.execute("SELECT count(*) FROM retained r WHERE NOT EXISTS (SELECT 1 FROM ledger l WHERE l.record_kind='span' AND l.source_span_id=r.source_span_id)").fetchone()[0], "retained target outside archive")
    db.execute("CREATE TEMP TABLE classified AS SELECT l.*,CASE WHEN record_kind<>'span' THEN 'excluded_nonspan' "
        "WHEN EXISTS (SELECT 1 FROM retained r WHERE r.source_span_id=l.source_span_id AND r.source_sha256=l.source_sha256 AND r.legal_id=l.legal_id) THEN 'matched' "
        "WHEN EXISTS (SELECT 1 FROM retained r WHERE r.source_span_id=l.source_span_id AND r.source_sha256<>l.source_sha256) THEN 'source_hash_mismatch' "
        "WHEN EXISTS (SELECT 1 FROM retained r WHERE r.source_span_id=l.source_span_id) THEN 'legal_id_mismatch' ELSE 'unresolved_source' END AS disposition FROM ledger l")
    counts = dict(db.execute("SELECT disposition,count(*) FROM classified GROUP BY 1").fetchall())
    _require(counts == report.get("ledger_disposition_counts"), "archive dispositions differ")
    db.execute("CREATE TEMP TABLE unresolved AS SELECT * FROM classified WHERE disposition='unresolved_source'")
    return span_count, counts.get("unresolved_source", 0)


def _span_id(row, ordinal, release):
    identity = dict(canonical_citation=row["citation"], entry_cid=row["entry_cid"], legal_id=row["legal_id"],
        ordinal=ordinal, query="ipfs_uscode", release_id=release, release_point="",
        schema_version="uscode-sparse-autoformal-span-v1", section=row["section"], text_sha256=row["source_sha256"],
        title=row["title"], unit_id=row["legal_id"])
    return "uscode-span-" + _digest(identity)


def _retained_batches(db):
    offset = 0
    while True:
        cursor = db.execute("SELECT * FROM retained ORDER BY source_section_offset,source_section_span_ordinal,occurrence_id LIMIT 512 OFFSET ?", [offset])
        names = [c[0] for c in cursor.description]
        rows = cursor.fetchall()
        if not rows:
            return
        yield [dict(zip(names, r)) for r in rows]
        offset += len(rows)


def _verify_all_baselines(db, manifest, report):
    verified = 0
    for batch in _retained_batches(db):
        for row in batch:
            _require(isinstance(row["occurrence_id"], bytes) and len(row["occurrence_id"]) == 32, "physical occurrence binding invalid")
            for field in ("citation", "entry_cid", "legal_id", "title", "section"):
                _require(isinstance(row[field], str) and 0 < len(row[field]) <= 4096, "retained identity string invalid")
            _require(row["legal_id"] == f"usc:us:{row['title']}:{row['section']}"
                     and isinstance(row["source_sha256"], str) and SHA.fullmatch(row["source_sha256"]), "retained legal/hash binding invalid")
            for field in ("source_section_offset", "historical_document_batch_index", "historical_span_ordinal", "source_section_span_ordinal"):
                _require(type(row[field]) is int and row[field] >= 0, "retained ordinal invalid")
            _require(row["source_section_offset"] < report["next_section"]
                     and row["source_section_span_ordinal"] <= row["historical_span_ordinal"]
                     and row["source_text_origin"] in ("normalized_source_text", "legacy_citation_fallback")
                     and type(row["raw_source_text_present"]) is bool, "retained source context invalid")
            _require(_span_id(row, row["historical_span_ordinal"], manifest["source"]["release_id"]) == row["source_span_id"], "historical baseline ID reconstruction refused")
            verified += 1
    return verified


def _hypothesis_id(row, release):
    return _span_id(row, row["source_section_span_ordinal"], release)


def _hypotheses(db, manifest):
    db.execute("CREATE TEMP TABLE hypotheses (occurrence_id BLOB,hypothesis_span_id VARCHAR)")
    changed = 0
    for batch in _retained_batches(db):
        values = []
        for row in batch:
            values.append((row["occurrence_id"], _hypothesis_id(row, manifest["source"]["release_id"])))
            changed += row["historical_span_ordinal"] != row["source_section_span_ordinal"]
        db.executemany("INSERT INTO hypotheses VALUES (?,?)", values)
    db.execute("CREATE TEMP TABLE candidate_pairs AS SELECT r.*,h.hypothesis_span_id,"
        "count(*) OVER (PARTITION BY h.hypothesis_span_id) AS retained_match_count "
        "FROM retained r JOIN hypotheses h USING(occurrence_id) JOIN unresolved u "
        "ON h.hypothesis_span_id=u.source_span_id AND r.source_sha256=u.source_sha256 AND r.legal_id=u.legal_id")
    pairs, physical, ids = db.execute("SELECT count(*),count(DISTINCT occurrence_id),count(DISTINCT hypothesis_span_id) FROM candidate_pairs").fetchone()
    ambiguous = db.execute("SELECT count(*) FROM (SELECT hypothesis_span_id FROM candidate_pairs GROUP BY 1 HAVING count(DISTINCT occurrence_id)>1)").fetchone()[0]
    return dict(candidate_pairs=pairs, candidate_physical_occurrences=physical, candidate_distinct_archived_ids=ids,
        retained_subset_ambiguous_archived_ids=ambiguous, retained_subset_singleton_archived_ids=ids-ambiguous,
        changed_ordinal_retained_rows=changed)


class _LimitedFile(io.RawIOBase):
    def __init__(self, path, limit):
        super().__init__()
        self.stream = path.open("xb")
        self.limit = limit
        self.written = 0

    def writable(self):
        return True

    def tell(self):
        return self.written

    def write(self, value):
        _require(self.written + len(value) <= self.limit, "candidate artifact exceeds output bound")
        count = self.stream.write(value)
        self.written += count
        return count

    def flush(self):
        if not self.stream.closed:
            self.stream.flush()

    def close(self):
        if not self.stream.closed:
            self.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
        super().close()


def _candidate_query():
    return ("SELECT lower(hex(occurrence_id)) AS occurrence_id,source_span_id AS generated_span_id,hypothesis_span_id,"
        "source_sha256,legal_id,entry_cid,citation,title,section,source_section_offset,source_section_span_ordinal,"
        "historical_span_ordinal,source_text_origin,raw_source_text_present,retained_match_count FROM candidate_pairs "
        "ORDER BY hypothesis_span_id,source_section_offset,source_section_span_ordinal,occurrence_id")


def _write_candidates(db, path, limit):
    import pyarrow as pa
    import pyarrow.parquet as pq
    reader = db.execute(_candidate_query()).fetch_record_batch(512)
    with _LimitedFile(path, limit) as bounded:
        with pa.PythonFile(bounded, mode="w") as sink:
            with pq.ParquetWriter(sink, reader.schema, compression="zstd") as writer:
                for batch in reader:
                    writer.write_batch(batch)


def run_identity_diagnosis(*, database_path, expected_database_sha256, manifest_path, expected_manifest_sha256,
        report_path, expected_report_sha256, progress_parquet, expected_progress_sha256,
        accepted_review_path, expected_accepted_review_sha256, output_directory, memory_mb=256,
        max_retained_rows=65536, max_archive_rows=500000, max_input_bytes=128*1024*1024,
        max_report_bytes=2*1024*1024, max_output_bytes=8*1024*1024, example_limit=32,
        _after_baseline=None, _before_publish=None):
    """Authenticate all retained baseline IDs, then emit unpromoted hypotheses.

    Every path/pin is explicit. ``output_directory`` must be absent under an
    existing owned parent and cannot be inside any input directory. Hooks are
    bounded failure/race controls for tests, not bypasses for input custody.
    """
    started = time.monotonic()
    for value, name, ceiling in ((memory_mb,"memory_mb",256),(max_retained_rows,"max_retained_rows",65536),
            (max_archive_rows,"max_archive_rows",500000),(max_input_bytes,"max_input_bytes",128*1024*1024),
            (max_report_bytes,"max_report_bytes",2*1024*1024),(max_output_bytes,"max_output_bytes",8*1024*1024),
            (example_limit,"example_limit",32)):
        _positive(value,name,ceiling)
    _require(max_report_bytes < max_output_bytes, "report reserve must fit output bound")
    paths = dict(database=database_path, manifest=manifest_path, report=report_path,
                 progress=progress_parquet, accepted_review=accepted_review_path)
    expected = dict(database=expected_database_sha256, manifest=expected_manifest_sha256,
        report=expected_report_sha256, progress=expected_progress_sha256, accepted_review=expected_accepted_review_sha256)
    paths = {k: _canonical(v) for k,v in paths.items()}
    parent = paths["database"].parent
    _require(paths["database"].name == "reconciliation.duckdb" and paths["manifest"] == parent/"manifest.json"
             and paths["report"] == parent/"report.json", "three stopped files must share their canonical parent")
    destination = _canonical(output_directory, existing=False)
    _require(not destination.exists(), "fresh absent destination required")
    destination_parent = _canonical(destination.parent, directory=True)
    destination_parent_identity = (destination_parent.stat().st_dev,destination_parent.stat().st_ino)
    _require(not any(destination.is_relative_to(p.parent) for p in paths.values()), "output cannot alias an input parent")
    lock_path = _canonical(parent/"writer.lock")
    wal = parent/"reconciliation.duckdb.wal"
    _require(not wal.exists(), "stopped WAL-free parent required")
    pins = {}
    db = None
    staging = None
    with os.fdopen(os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IdentityRecoveryError("stopped parent writer lock unavailable") from exc
        lock_signature = _signature(os.fstat(lock.fileno()))
        try:
            _require(not wal.exists(), "WAL appeared after lock")
            for name,path in paths.items():
                pins[name] = _Witness(path, expected[name], max_input_bytes)
            manifest, report, review = (pins[n].read_json() for n in ("manifest","report","accepted_review"))
            code_pins = _bindings(manifest,report,review,pins)
            operators = _owner_pins()
            import duckdb
            db = duckdb.connect(":memory:",config={"memory_limit":f"{memory_mb}MB","threads":1,"temp_directory":""})
            db.execute("ATTACH "+_sql_path(paths["database"])+" AS saved (READ_ONLY)")
            retained = _load_retained(db,manifest,report,max_retained_rows)
            archive_ids, unresolved = _load_archive(db,paths["progress"],report,max_archive_rows)
            verified = _verify_all_baselines(db,manifest,report)
            _require(verified == retained, "all retained baseline rows must pass")
            if _after_baseline:
                _after_baseline()
            counts = _hypotheses(db,manifest)
            examples_cursor = db.execute(_candidate_query()+" LIMIT ?",[example_limit])
            examples = [dict(zip([c[0] for c in examples_cursor.description],r)) for r in examples_cursor.fetchall()]
            staging = Path(tempfile.mkdtemp(prefix=".identity-diagnosis-",dir=destination_parent))
            candidate_path = staging/"candidates.parquet"
            _write_candidates(db,candidate_path,max_output_bytes-max_report_bytes)
            candidate_sha, candidate_bytes = _bounded_hash(candidate_path,max_output_bytes-max_report_bytes)
            result = dict(schema=SCHEMA,hypothesis=HYPOTHESIS,status="completed_unpromoted_diagnosis",
                input_pins={k:p.metadata() for k,p in pins.items()}, source_reference=manifest["source"],
                generation_manifest_sha256=_digest(manifest), execution_code_sha256=code_pins,operator_sha256=operators,
                retained_physical_occurrences=retained,baseline_verified_occurrences=verified,
                complete_source_occurrences=report["accounting"]["source_occurrence_count"],
                archived_distinct_ids=archive_ids,unresolved_archived_ids=unresolved,
                unresolved_ids_without_retained_candidate=unresolved-counts["candidate_distinct_archived_ids"],
                counts=counts,examples=examples,candidate_artifact=dict(path="candidates.parquet",sha256=candidate_sha,
                    bytes=candidate_bytes,rows=counts["candidate_pairs"]),
                bounds=dict(memory_mb=memory_mb,threads=1,spill_enabled=False,max_retained_rows=max_retained_rows,
                    max_archive_rows=max_archive_rows,max_input_bytes=max_input_bytes,max_report_bytes=max_report_bytes,
                    max_output_bytes=max_output_bytes,example_limit=example_limit),
                original_source_read=False,models_loaded=False,tokenizers_loaded=False,aliases_created=False,
                original_producer_recipe_authenticated=False,full_source_uniqueness_verified=False,
                embedding_reuse_qualified=False,teacher_qualified=False,training_admitted=False,
                semantic_gold=False,semantic_fidelity_qualified=False,proof_authority=False,
                limitations=["Only retained archived-target physical occurrences were compared; outside-target identities are aggregate-only.",
                    "A singleton is unique only within the retained subset, not across the complete source universe.",
                    "Exact alternate-ID/SHA/legal joins are hypotheses, not recovered original launches or approved aliases.",
                    "Source, model, tokenizer, vector and text bodies were not read or generated."])
            result.update(_runtime_metrics(started))
            body=(_json(result)+"\n").encode()
            _require(len(body)<=max_report_bytes, "report exceeds byte bound")
            with (staging/"report.json").open("xb") as stream:
                stream.write(body);stream.flush();os.fsync(stream.fileno())
            _require(sum(p.stat().st_size for p in staging.iterdir())<=max_output_bytes, "total output bound exceeded")
            db.close();db=None
            if _before_publish:
                _before_publish(staging,destination)
            _canonical(destination_parent,directory=True)
            _require((destination_parent.stat().st_dev,destination_parent.stat().st_ino)==destination_parent_identity,
                     "destination parent changed")
            _canonical(staging,directory=True)
            _require({p.name for p in staging.iterdir()} == {"report.json", "candidates.parquet"}
                     and all(p.is_file() and not p.is_symlink() for p in staging.iterdir()), "staged files must remain regular and exact")
            _require(candidate_path.stat().st_size<=max_output_bytes-max_report_bytes
                     and (staging/"report.json").stat().st_size<=max_report_bytes
                     and sum(p.stat().st_size for p in staging.iterdir())<=max_output_bytes, "staged output bound exceeded")
            for pin in pins.values():
                pin.verify()
            _canonical(lock_path)
            _require(not wal.exists() and _signature(lock_path.stat())==lock_signature
                     and _signature(os.fstat(lock.fileno()))==lock_signature, "stopped parent changed")
            _require(_owner_pins()==operators and archive._pins()==code_pins, "diagnostic/execution owner changed")
            staged_pins=[]
            try:
                for path,expected_sha,limit in ((candidate_path,candidate_sha,max_output_bytes-max_report_bytes),
                        (staging/"report.json",hashlib.sha256(body).hexdigest(),max_report_bytes)):
                    staged_pins.append(_Witness(path,expected_sha,limit))
                for witness in staged_pins:
                    witness.verify()
            except IdentityRecoveryError as exc:
                raise IdentityRecoveryError("staged artifact changed: "+str(exc)) from exc
            finally:
                for witness in staged_pins:
                    witness.close()
            resume._fsync_directory(staging)
            resume._noreplace(staging,destination)
            staging=None
            resume._fsync_directory(destination_parent)
            return result
        finally:
            if db is not None:
                db.close()
            for pin in pins.values():
                pin.close()
            if staging is not None:
                shutil.rmtree(staging)
            fcntl.flock(lock,fcntl.LOCK_UN)
