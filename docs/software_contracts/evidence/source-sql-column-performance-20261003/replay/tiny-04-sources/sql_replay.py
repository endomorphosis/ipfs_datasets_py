"""External diagnostic only: exact retained AST facts, no source/model execution."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import signal
import sys
import time

MAX_CORPUS_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000
SCHEMA = "retained-source384-sql-corpus@1"
CONFIG = {"threads": "1", "memory_limit": "512MB"}
OWNER_NAMES = (
    "ipfs_datasets_py.logic.software_contracts.duckdb_ast_store",
    "ipfs_datasets_py.logic.software_contracts.ast_ir",
    "ipfs_datasets_py.logic.software_contracts.content",
    "ipfs_datasets_py.logic.software_contracts.schema_versions",
)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path, maximum=MAX_CORPUS_BYTES):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular diagnostic input required")
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("diagnostic input exceeds bound")
    return value


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    body = raw(value)
    if len(body) > MAX_CORPUS_BYTES:
        raise ValueError("diagnostic output exceeds bound")
    with Path(path).open("xb") as stream:
        stream.write(body)
    return sha(body)


def pins():
    return {name: file_sha(importlib.import_module(name).__file__) for name in OWNER_NAMES}


def query_rows(connection, table):
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import ASTS_CATALOG_TABLES
    if table not in ASTS_CATALOG_TABLES:
        raise ValueError("unknown fixed fact family")
    cursor = connection.execute(f'SELECT * FROM "{table}" LIMIT {MAX_ROWS + 1}')
    columns = [item[0] for item in cursor.description]
    values = cursor.fetchall()
    if len(values) > MAX_ROWS:
        raise ValueError("diagnostic row bound exceeded")
    return [dict(zip(columns, row)) for row in values]


def table_digest(rows):
    encoded = sorted(raw(row) for row in rows)
    h = hashlib.sha256()
    for item in encoded:
        h.update(len(item).to_bytes(8, "big"))
        h.update(item)
    return {"rows": len(encoded), "sha256": h.hexdigest()}


def table_inventory(connection):
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import ASTS_CATALOG_TABLES
    return {name: table_digest(query_rows(connection, name)) for name in ASTS_CATALOG_TABLES}


def require_retained_head(connection, head):
    columns = ("repository_id", "generation", "manifest_cid", "snapshot_cid", "ast_revision_id", "receipt_cid")
    if type(head) is not dict or set(head) != set(columns):
        raise ValueError("closed retained source head required")
    values = connection.execute("SELECT " + ",".join(columns)
        + " FROM codebase_control.heads WHERE repository_id=? LIMIT 2", [head["repository_id"]]).fetchall()
    if len(values) != 1 or dict(zip(columns, values[0])) != head:
        raise ValueError("retained source head differs from native receipt")


def export_corpus(database, receipt, output):
    import duckdb
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import ASTS_CATALOG_TABLES
    database = Path(database).resolve(strict=True)
    receipt_raw = read(receipt)
    native = json.loads(receipt_raw)
    if native.get("schema") != "terminal-source384-repository-context@1" or len(native["source_hashes"]) != 220:
        raise ValueError("exact retained full220 native receipt required")
    before = file_sha(database)
    producer = pins()
    with duckdb.connect(str(database), read_only=True, config=CONFIG) as connection:
        require_retained_head(connection, native["source_head"])
        tables = {name: query_rows(connection, name) for name in ASTS_CATALOG_TABLES}
    revisions = {row["revision_id"]: row for row in tables["source_revisions"]}
    by_file = {row["file_id"]: row for row in tables["source_files"]}
    blobs = sorted(tables["ast_blobs"], key=lambda row: by_file[row["file_id"]]["path"])
    if len(blobs) != 31:
        raise ValueError("exact retained31 projection population required")
    inputs = []
    for blob in blobs:
        blob_id = blob["blob_id"]
        inputs.append({"blob": blob, "revision": revisions[blob["revision_id"]],
            "diagnostics": [row for row in tables["diagnostics"] if row["blob_id"] == blob_id],
            "invalidations": [row for row in tables["invalidations"]
                if row["invalidation_id"] == blob_id + ":invalidation:parse_failure"]})
    if before != file_sha(database) or producer != pins():
        raise ValueError("retained source database or producer changed during export")
    value = {"schema": SCHEMA, "producer": producer, "inputs": inputs,
        "tables": {name: table_digest(rows) for name, rows in tables.items()},
        "source": {"database_sha256": before, "receipt_sha256": sha(receipt_raw),
            "source_files": 220, "source_head": native["source_head"],
            "native_head_row_verified": True,
            "source_hashes_sha256": sha(raw(native["source_hashes"])),
            "inference_sha256": native["inference_sha256"]},
        "export_read_only": True, "contains_model_weights": False}
    digest = write(output, value)
    return {"corpus_sha256": digest, "bytes": Path(output).stat().st_size,
            "projections": len(inputs), "table_families": len(value["tables"]),
            "tables": value["tables"], "source": value["source"]}


def rebuild(corpus):
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    if set(corpus) != {"schema", "producer", "inputs", "tables", "source", "export_read_only", "contains_model_weights"}:
        raise ValueError("closed diagnostic corpus required")
    if corpus["schema"] != SCHEMA or corpus["producer"] != pins() or corpus["contains_model_weights"] is not False:
        raise ValueError("corpus schema or native producer mismatch")
    if not 1 <= len(corpus["inputs"]) <= 64:
        raise ValueError("bounded retained projection population required")
    return tuple(DuckDBASTStore._rebuild(item["blob"], item["revision"],
        item["diagnostics"], item["invalidations"]) for item in corpus["inputs"])


class ExecuteTiming:
    """Forward native calls/cursors unchanged; retain aggregate numeric telemetry."""
    def __init__(self, connection):
        self.connection = connection
        self.groups = {}

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, statement, parameters=None):
        # Fixed native SQL only. No SQL or parameter values are retained.
        from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import ASTS_CATALOG_TABLES
        text = statement.strip().upper()
        verb = text.split(None, 1)[0]
        match = re.search(r'\b(?:INTO|FROM|UPDATE)\s+"?([A-Z_]+)', text)
        table = match.group(1).lower() if match else "transaction"
        if table not in ASTS_CATALOG_TABLES and table != "transaction":
            table = "other"
        key = verb + ":" + table
        stats = self.groups.setdefault(key, {"calls": 0, "failures": 0,
            "wall_seconds": 0., "process_cpu_seconds": 0., "parameters": 0,
            "parameter_bytes_estimate": 0, "max_parameters": 0,
            "scalar_parameters": 0, "insert_rows": 0, "max_statement_bytes": 0})
        params = () if parameters is None else parameters
        if not isinstance(params, (list, tuple)):
            raise TypeError("native diagnostic parameters must remain list or tuple")
        parameter_count = len(params)
        columnar = verb == "INSERT" and "UNNEST(" in text
        if columnar and (not params or any(type(v) is not list for v in params)
                         or len({len(v) for v in params}) != 1):
            raise ValueError("equal bounded column lists required")
        values = (v for column in params for v in column) if columnar else iter(params)
        parameter_bytes = scalar_count = 0
        for value in values:
            scalar_count += 1
            parameter_bytes += len(value.encode()) if type(value) is str else len(value) if type(value) is bytes else 8
        stats["calls"] += 1
        stats["parameters"] += parameter_count
        stats["parameter_bytes_estimate"] += parameter_bytes
        stats["scalar_parameters"] += scalar_count
        stats["max_parameters"] = max(stats["max_parameters"], parameter_count)
        stats["max_statement_bytes"] = max(stats["max_statement_bytes"], len(statement.encode()))
        if verb == "INSERT" and "VALUES" in text:
            stats["insert_rows"] += text.split("VALUES", 1)[1].count("(")
        elif columnar:
            stats["insert_rows"] += len(params[0])
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            return self.connection.execute(statement) if parameters is None else self.connection.execute(statement, parameters)
        except BaseException:
            stats["failures"] += 1
            raise
        finally:
            stats["wall_seconds"] += time.perf_counter() - wall
            stats["process_cpu_seconds"] += time.process_time() - cpu


def counters():
    result = {"process_cpu_seconds": time.process_time()}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result["rusage"] = {name: getattr(usage, name) for name in (
        "ru_utime", "ru_stime", "ru_maxrss", "ru_inblock", "ru_oublock", "ru_nvcsw", "ru_nivcsw")}
    for name, path in (("process_io", "/proc/self/io"), ("cgroup_membership", "/proc/self/cgroup")):
        try: result[name] = read(path, 65536).decode()
        except (OSError, ValueError): result[name] = None
    membership = result.get("cgroup_membership") or ""
    for row in membership.splitlines():
        if row.startswith("0::"):
            path = Path("/sys/fs/cgroup") / row[3:].lstrip("/")
            if not path.is_dir(): path = Path("/sys/fs/cgroup")
            for name in ("cpu.max", "cpu.stat", "memory.max", "memory.current", "io.stat"):
                try: result[name] = read(path / name, 65536).decode()
                except (OSError, ValueError): result[name] = None
    return result


def platform_receipt(database, connection):
    import duckdb
    import _duckdb
    target = str(Path(database).resolve())
    mounts = []
    try:
        for line in read("/proc/self/mountinfo", 1024 * 1024).decode().splitlines():
            left, right = line.split(" - ", 1)
            fields, kind = left.split(), right.split()
            mount = fields[4].replace("\\040", " ")
            if target == mount or target.startswith(mount.rstrip("/") + "/"):
                mounts.append({"mount_point": mount, "device": fields[2],
                    "filesystem": kind[0], "mount_source": kind[1], "options": fields[5]})
    except (OSError, ValueError): pass
    names = ("threads", "memory_limit", "temp_directory", "preserve_insertion_order",
             "checkpoint_threshold", "wal_autocheckpoint", "external_threads")
    settings = dict(connection.execute("SELECT name,value FROM duckdb_settings() WHERE name IN ("
        + ",".join("?" for _ in names) + ")", list(names)).fetchall())
    return {"python": sys.version, "machine": platform.machine(), "platform": platform.platform(),
        "duckdb_version": duckdb.__version__, "duckdb_platform": connection.execute("PRAGMA platform").fetchone()[0],
        "duckdb_extension_path": str(Path(_duckdb.__file__).resolve()),
        "duckdb_extension_sha256": file_sha(_duckdb.__file__),
        "duckdb_settings": settings, "connection_config": CONFIG,
        "database_mount": max(mounts, key=lambda item: len(item["mount_point"])) if mounts else None,
        "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None}


def replay(corpus_path, expected_sha, output, *, timeout_seconds=90,
           candidate_path=None, candidate_sha256=None):
    import duckdb
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    body = read(corpus_path)
    if sha(body) != expected_sha:
        raise ValueError("corpus digest mismatch")
    corpus = json.loads(body)
    producer = pins()
    candidate = None
    if (candidate_path is None) != (candidate_sha256 is None):
        raise ValueError("candidate path and digest must be selected together")
    if candidate_path is not None:
        candidate_body = read(candidate_path, 65536)
        if sha(candidate_body) != candidate_sha256:
            raise ValueError("external candidate digest mismatch")
        candidate = {"path": str(Path(candidate_path).resolve()), "sha256": candidate_sha256}
        namespace = {"__file__": candidate["path"], "__name__": "external_sql_candidate"}
        exec(compile(candidate_body, candidate["path"], "exec"), namespace)
        implementation = namespace["insert_rows_unnest"]
    else:
        implementation = DuckDBASTStore._insert_rows
    result = {"schema": "source384-sql-replay-diagnostic@1", "diagnostic_only": True,
        "benchmark_result": False, "production_qualification": False, "provider_calls": 0,
        "model_loads": 0, "neural_inference": False, "training_steps": 0,
        "corpus_sha256": expected_sha, "source": corpus["source"], "producer_before": producer,
        "harness_sha256": file_sha(__file__), "mode": "native_multi_values_baseline" if candidate is None else "external_column_unnest_candidate",
        "external_candidate": candidate,
        "execute_timing_scope": "Python parameter binding plus native execute; excludes cursor fetching and telemetry preparation",
        "timeout_seconds": timeout_seconds, "qualified": False, "before": counters()}
    database = output / "replay.duckdb"
    original = DuckDBASTStore._insert_rows
    insert_times = {}
    proxy = None
    store = connection = None
    def timed_insert(self, statement, rows):
        match = re.search(r'INTO\s+"?([a-z_]+)', statement, re.I)
        family = match.group(1) if match else "unknown"
        slot = insert_times.setdefault(family, {"calls": 0, "wall_seconds": 0., "process_cpu_seconds": 0.})
        wall, cpu = time.perf_counter(), time.process_time()
        try: return implementation(self, statement, rows)
        finally:
            slot["calls"] += 1
            slot["wall_seconds"] += time.perf_counter() - wall
            slot["process_cpu_seconds"] += time.process_time() - cpu
    def expired(signum, frame):
        raise TimeoutError("bounded SQL-only diagnostic deadline expired")
    previous_handler = signal.getsignal(signal.SIGALRM)
    if signal.getitimer(signal.ITIMER_REAL) != (0., 0.):
        raise ValueError("diagnostic cannot replace an existing alarm")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    started = time.perf_counter()
    try:
        mark = time.perf_counter()
        projections = rebuild(corpus)
        result["rebuild_seconds"] = time.perf_counter() - mark
        result["projections"] = len(projections)
        with duckdb.connect(str(database), config=CONFIG) as connection:
            result["platform"] = platform_receipt(database, connection)
            store = DuckDBASTStore(connection=connection)
            proxy = ExecuteTiming(connection)
            store._connection = proxy
            DuckDBASTStore._insert_rows = timed_insert
            mark = time.perf_counter()
            returned = store.apply_batch(projections)
            result["apply_batch_seconds"] = time.perf_counter() - mark
            if returned[0] != projections or returned[1]:
                raise ValueError("native applied projection population differs")
            DuckDBASTStore._insert_rows = original
            store._connection = connection
            observed = table_inventory(connection)
            if observed != corpus["tables"]:
                raise ValueError("all-table row digest or count mismatch")
            result["tables"] = observed
            result["table_families"] = len(observed)
        with duckdb.connect(str(database), read_only=True, config=CONFIG) as reopened:
            # Avoid install_schema writes on the read-only cold handle.
            reader = DuckDBASTStore()
            reader._connection = reopened
            if any(reader.get(p.blob_id) != p for p in projections):
                raise ValueError("cold native canonical replay differs")
            if table_inventory(reopened) != corpus["tables"]:
                raise ValueError("cold all-table digest mismatch")
        result["producer_after"] = pins()
        if producer != result["producer_after"] or sha(read(corpus_path)) != expected_sha:
            raise ValueError("producer or corpus changed during replay")
        if candidate is not None and sha(read(candidate["path"], 65536)) != candidate["sha256"]:
            raise ValueError("external candidate changed during replay")
        result.update(qualified=True, all_table_parity=True, cold_native_replay=True)
        return result
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error)[:1024])
        raise
    finally:
        DuckDBASTStore._insert_rows = original
        if store is not None:
            store._connection = connection
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        result.update(seconds=time.perf_counter()-started, after=counters(), insert_family_times=insert_times,
                      execute_groups={} if proxy is None else proxy.groups)
        write(output / "receipt.json", result)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--source-database", required=True)
    export.add_argument("--source-receipt", required=True)
    export.add_argument("--output", required=True)
    run = sub.add_parser("replay")
    run.add_argument("--corpus", required=True)
    run.add_argument("--expected-sha256", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--candidate-path")
    run.add_argument("--candidate-sha256")
    args = parser.parse_args()
    if args.command == "export":
        print(json.dumps(export_corpus(args.source_database, args.source_receipt, args.output), sort_keys=True))
    else:
        result = replay(args.corpus, args.expected_sha256, args.output,
                        candidate_path=args.candidate_path, candidate_sha256=args.candidate_sha256)
        print(json.dumps({key: result[key] for key in ("schema", "qualified", "seconds", "apply_batch_seconds", "projections")}, sort_keys=True))


if __name__ == "__main__":
    main()
