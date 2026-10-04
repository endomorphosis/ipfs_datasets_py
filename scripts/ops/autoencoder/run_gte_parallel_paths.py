"""Dispatch caller-supplied trusted local jobs without importing model packages."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys


REPOSITORY = Path(__file__).resolve().parents[3]
COORDINATOR = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder/gte_parallel_paths.py"
JOBS_SCHEMA = "gte-parallel-path-jobs/v1"
MAX_JOBS_BYTES = 1024 * 1024


def _coordinator():
    spec = importlib.util.spec_from_file_location("gte_parallel_paths_cli_worker", COORDINATOR)
    if spec is None or spec.loader is None:
        raise ValueError("missing parallel-path coordinator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_jobs(path):
    # Reject special files before reading, so a malformed jobs path cannot block
    # on a FIFO. This is only a local configuration reader, not authentication.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("jobs-file must be a regular JSON file")
        raw = stream.read(MAX_JOBS_BYTES + 1)
    if len(raw) > MAX_JOBS_BYTES:
        raise ValueError("jobs-file exceeds byte limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON number: " + value)

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number

    config = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=finite)
    if type(config) is not dict or set(config) != {"schema", "jobs"}:
        raise ValueError("closed jobs-file fields schema and jobs required")
    if config["schema"] != JOBS_SCHEMA:
        raise ValueError("unsupported jobs-file schema")
    return config["jobs"]


def run_jobs_file(jobs_file, report_file, *, max_parallel=3, timeout_seconds=None):
    """Reserve a fresh report, then dispatch exact argv with resolved lane paths.

    Relative job state/output paths use the jobs-file parent. Worker argv and
    the worker working directory retain caller-supplied/process semantics.
    Report paths use the caller's working directory when relative.
    An interrupt or exception can leave the reserved report empty/incomplete;
    only a normal completed dispatch writes a complete JSON report. The CLI
    reports that failure and emits no successful stdout summary.
    """
    config_path = Path(jobs_file).resolve()
    report_path = Path(report_file).resolve()
    coordinator = _coordinator()
    source_jobs = _read_jobs(config_path)
    if type(source_jobs) is not list:
        raise ValueError("jobs must be a JSON list")
    jobs = []
    for source in source_jobs:
        if type(source) is not dict or set(source) != coordinator.JOB_FIELDS:
            raise ValueError("closed parallel job fields required")
        job = dict(source)
        for field in ("state_directory", "output_directory"):
            if type(job[field]) is not str or not job[field].strip():
                raise ValueError("nonempty " + field + " string required")
            job[field] = str((config_path.parent / job[field]).resolve())
        jobs.append(job)
    # Use the same preflight as the dispatcher before report reservation. No
    # workers, state directories, or output directories exist because of this.
    prepared = coordinator._validate(jobs, max_parallel, timeout_seconds)
    for job in prepared:
        for field in ("state_directory", "output_directory"):
            directory = job[field]
            if report_path.is_relative_to(directory) or directory.is_relative_to(report_path):
                raise ValueError("report-file must be outside every lane state/output namespace")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = report_path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise ValueError("fresh report-file required; no workers were launched") from error
    with stream:
        report = coordinator.run_parallel_paths(jobs, max_parallel=max_parallel,
                                                timeout_seconds=timeout_seconds)
        json.dump(report, stream, sort_keys=True, allow_nan=False, ensure_ascii=True)
        stream.write("\n")
    return report, report_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Relative job state/output directories resolve against the jobs-file parent. "
               "Commands are trusted exact argv; no shell, argv rewriting, or model imports. "
               "Workers must verify checkpoint pins and enforce their resource budgets.")
    parser.add_argument("--jobs-file", required=True, type=Path)
    parser.add_argument("--report-file", required=True, type=Path,
                        help="fresh exclusive report file outside all lane directories")
    parser.add_argument("--max-parallel", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float,
                        help="finite positive timeout per launched worker")
    args = parser.parse_args(argv)
    try:
        report, path = run_jobs_file(args.jobs_file, args.report_file,
                                    max_parallel=args.max_parallel, timeout_seconds=args.timeout_seconds)
    except (ValueError, OSError, TypeError, KeyError) as error:
        parser.exit(2, "parallel dispatch failed: " + str(error) + "\n")
    except KeyboardInterrupt:
        parser.exit(130, "parallel dispatch interrupted; launched workers were stopped\n")
    print(json.dumps({"status": report["status"], "report_file": str(path)}, sort_keys=True))
    if report["status"] != "success":
        print("parallel dispatch completed with " + report["status"] + "; see per-lane statuses in report", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
