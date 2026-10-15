#!/usr/bin/env python3
"""Observe public US Code cache metadata without fetching dataset file bodies.

Only Hub revision metadata and Dataset Viewer splits/zero-row responses are
requested. Returned file descriptors and row totals are observations, not file
integrity checks, a source census, semantic review or corpus qualification.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


DATASETS = {
    "span": "justicedao/uscode-autoformal-span-cache",
    "entity": "justicedao/uscode-autoformal-entity-cache",
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_VIEWER_SPLITS = 32
MAX_HTTP_REQUESTS = 80
HTTP_TIMEOUT_SECONDS = 15
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEADERS = frozenset({"content-type", "content-length", "etag", "x-repo-commit"})


class ObservationError(ValueError):
    """Metadata failed the bounded observation contract."""


def _utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _require(condition, message):
    if not condition:
        raise ObservationError(message)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ObservationError("nonfinite JSON value")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    _require(type(value) is dict, "metadata JSON object required")
    return value


def _write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def fetch_public_metadata(url, *, max_bytes, timeout_seconds):
    """Unauthenticated HTTP; redirects/retries and repository-file URLs are unused."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "uscode-cache-metadata-observer/1"})
    opener = build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=timeout_seconds)
    except HTTPError as error:
        response = error
    with response:
        return {
            "status": response.code,
            "final_url": response.geturl(),
            "headers": dict(response.headers),
            "body": response.read(max_bytes + 1),
        }


def _repo_identity(value, repository, expected_revision=None):
    _require(value.get("id") == repository, "Hub repository identity mismatch")
    revision = value.get("sha")
    _require(type(revision) is str and _REVISION.fullmatch(revision), "immutable Hub revision required")
    _require(expected_revision is None or revision == expected_revision, "pinned Hub revision mismatch")
    return revision


def _siblings(value):
    rows = value.get("siblings")
    _require(type(rows) is list, "Hub sibling inventory required")
    files, seen, suffix_counts = [], set(), {}
    total_bytes = 0
    for row in rows:
        _require(type(row) is dict, "Hub sibling descriptor required")
        name, size = row.get("rfilename"), row.get("size")
        _require(type(name) is str and name and "\\" not in name and "\x00" not in name
                 and not name.startswith("/") and str(PurePosixPath(name)) == name
                 and not any(part in {"", ".", ".."} for part in name.split("/")),
                 "relative sibling path required")
        _require(name not in seen, "duplicate sibling path")
        _require(type(size) is int and size >= 0, "nonnegative sibling byte size required")
        seen.add(name)
        blob = row.get("blobId")
        _require(blob is None or (type(blob) is str and _REVISION.fullmatch(blob)), "invalid Git blob identity")
        lfs = row.get("lfs")
        if lfs is not None:
            _require(type(lfs) is dict and type(lfs.get("sha256")) is str
                     and _SHA256.fullmatch(lfs["sha256"]), "invalid LFS SHA256 descriptor")
            _require(type(lfs.get("size")) is int and lfs["size"] == size, "LFS size descriptor mismatch")
            pointer_size = lfs.get("pointerSize")
            _require(pointer_size is None or (type(pointer_size) is int and pointer_size >= 0),
                     "invalid LFS pointer size")
        files.append({"path": name, "bytes": size, "git_blob_sha1": blob, "lfs": lfs})
        suffix = PurePosixPath(name).suffix or "(none)"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        total_bytes += size
    return {
        "scope": "every sibling descriptor returned by the pinned Hub revision API",
        "file_count": len(files), "declared_file_bytes": total_bytes,
        "parquet_file_count": suffix_counts.get(".parquet", 0),
        "lfs_file_count": sum(row["lfs"] is not None for row in files),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "files": sorted(files, key=lambda row: row["path"]),
        "returned_sibling_population_preserved": True,
        "independent_tree_or_file_validation_performed": False,
    }


def _split_population(value, repository):
    rows = value.get("splits")
    _require(type(rows) is list, "Viewer split population required")
    result, seen = [], set()
    for row in rows:
        _require(type(row) is dict and row.get("dataset") == repository, "Viewer split repository mismatch")
        config, split = row.get("config"), row.get("split")
        _require(all(type(item) is str and item.strip() and len(item.encode()) <= 1024
                     for item in (config, split)), "bounded Viewer config/split required")
        _require((config, split) not in seen, "duplicate Viewer split")
        seen.add((config, split))
        result.append({"config": config, "split": split})
    return result


def observe(output_directory, *, span_revision=None, entity_revision=None,
            fetch=None, max_response_bytes=MAX_RESPONSE_BYTES):
    """Retain an observation or partial failure in a new private directory.

    Explicit revisions replay metadata snapshots without querying or asserting
    the current main heads. The injectable fetch function is for synthetic tests.
    """
    revisions = {"span": span_revision, "entity": entity_revision}
    for revision in revisions.values():
        _require(revision is None or (type(revision) is str and _REVISION.fullmatch(revision)),
                 "explicit revisions must be full lowercase hexadecimal commits")
    _require(type(max_response_bytes) is int and 0 < max_response_bytes <= MAX_RESPONSE_BYTES,
             "response bound can only lower the fixed maximum")
    fetch = fetch_public_metadata if fetch is None else fetch
    output = Path(output_directory).absolute()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    raw_directory = output / "http"
    raw_directory.mkdir(mode=0o700)
    summary = {
        "schema": "uscode-cache-metadata-observation/v1", "started_at_utc": _utc(),
        "status": "in_progress", "datasets": {}, "http_observations": [], "errors": [],
        "limits": {"response_bytes": max_response_bytes, "total_response_bytes": MAX_TOTAL_BYTES,
                   "viewer_splits": MAX_VIEWER_SPLITS, "http_requests": MAX_HTTP_REQUESTS,
                   "http_timeout_seconds": HTTP_TIMEOUT_SECONDS},
        "qualification": {
            "repository_file_bodies_downloaded": False, "file_payload_integrity_verified": False,
            "pinned_parquet_schema_verified": False, "viewer_revision_binding_verified": False,
            "unique_source_population_verified": False, "corpus_coverage_verified": False,
            "source_semantics_verified": False, "admitted": False, "formalized": False,
            "model_execution_performed": False, "training_performed": False, "lean_execution_performed": False,
        },
    }
    accounted_bytes, viewer_count = 0, 0

    def failure(lane, stage, error):
        summary["errors"].append({"dataset": lane, "stage": stage,
                                  "error_type": type(error).__name__, "error": str(error)[:512]})

    def capture(url, lane, stage):
        nonlocal accounted_bytes
        _require(len(summary["http_observations"]) < MAX_HTTP_REQUESTS, "HTTP request bound exceeded")
        remaining = MAX_TOTAL_BYTES - accounted_bytes
        _require(remaining > 0, "aggregate response byte bound exhausted")
        limit = min(max_response_bytes, remaining)
        entry = {"dataset": lane, "stage": stage, "requested_url": url, "observed_at_utc": _utc()}
        summary["http_observations"].append(entry)
        try:
            response = fetch(url, max_bytes=limit, timeout_seconds=HTTP_TIMEOUT_SECONDS)
            _require(type(response) is dict and type(response.get("body")) is bytes,
                     "bounded HTTP response bytes required")
            body = response["body"]
            truncated = len(body) > limit
            retained = body[:limit]
            accounted_bytes += len(retained)
            headers = response.get("headers", {})
            _require(type(headers) is dict, "HTTP response headers required")
            entry.update({
                "status": response.get("status"), "final_url": response.get("final_url"),
                "response_headers": {str(key).lower(): str(value)[:2048]
                                     for key, value in headers.items() if str(key).lower() in _HEADERS},
                "observed_body_bytes": len(retained),
                "observed_body_sha256": hashlib.sha256(retained).hexdigest(),
                "body_truncated": truncated, "observed_body_is_complete": not truncated,
                "raw_body_archived": False,
            })
            value = None
            if stage == "viewer_rows_metadata":
                _require(not truncated, "zero-row Viewer response exceeds byte bound; no payload archived")
                try:
                    value = _json(retained)
                except Exception:
                    raise ObservationError("zero-row Viewer response is not a metadata JSON object") from None
                entry["json_object_decoded"] = True
                # Error-only HTTP JSON is metadata. Every successful row response
                # must demonstrate its empty row list before any bytes are saved.
                error_only = (type(response.get("status")) is int and 400 <= response["status"] < 600
                              and set(value) == {"error"} and type(value["error"]) is str)
                _require(error_only or (type(value.get("rows")) is list and not value["rows"]),
                         "zero-row Viewer request returned rows or omitted its empty row list")
            relative = f"http/response-{len(summary['http_observations']):04d}.body"
            _write(output / relative, retained)
            entry.update({"raw_path": relative, "retained_bytes": len(retained),
                          "retained_sha256": entry["observed_body_sha256"],
                          "retained_body_is_complete": not truncated, "raw_body_archived": True})
            _require(not truncated, "HTTP response exceeds byte bound; only bounded prefix retained")
            _require(response.get("final_url") == url, "HTTP response changed the requested metadata URL")
            _require(type(response.get("status")) is int and response["status"] == 200,
                     "metadata HTTP status was not 200")
            value = _json(retained) if value is None else value
            entry["json_object_decoded"] = True
            return value
        except Exception as error:
            entry["error_type"], entry["error"] = type(error).__name__, str(error)[:512]
            raise

    try:
        for lane, repository in DATASETS.items():
            base = "https://huggingface.co/api/datasets/" + repository
            requested = revisions[lane]
            record = {
                "repository_id": repository,
                "mode": "explicit_revision_replay" if requested else "observed_main_snapshot",
                "requested_revision": requested, "main_open_revision": None,
                "main_close_revision": None, "main_changed_during_observation": None,
                "live_head_stability": "not_observed", "status": "in_progress",
                "viewer": {"revision_bound": False, "pinned_data_equality_verified": False,
                           "scope": "live unversioned service schema and declared row totals", "views": []},
            }
            summary["datasets"][lane] = record
            errors_before = len(summary["errors"])
            stage = "main_open" if requested is None else "pinned_revision"
            try:
                if requested is None:
                    requested = _repo_identity(capture(base, lane, stage), repository)
                    record["main_open_revision"] = requested
                record["observed_revision"] = requested
                stage = "pinned_revision"
                pinned = capture(base + "/revision/" + requested + "?blobs=true", lane, stage)
                _repo_identity(pinned, repository, requested)
                record["sibling_inventory"] = _siblings(pinned)
                card = pinned.get("cardData")
                record["card_configs"] = card.get("configs") if type(card) is dict else None
                stage = "viewer_splits"
                splits_url = "https://datasets-server.huggingface.co/splits?" + urlencode({"dataset": repository})
                split_value = capture(splits_url, lane, stage)
                splits = _split_population(split_value, repository)
                record["viewer"]["split_population"] = splits
                service = {name: split_value.get(name, []) for name in ("pending", "failed")}
                _require(all(type(rows) is list for rows in service.values()),
                         "Viewer pending/failed split arrays required")
                record["viewer"]["split_service_declarations"] = service
                _require(not any(service.values()), "Viewer reports pending or failed split metadata")
                _require(viewer_count + len(splits) <= MAX_VIEWER_SPLITS,
                         "complete Viewer split population exceeds global view bound")
                for split in splits:
                    stage = "viewer_rows_metadata"
                    viewer_count += 1
                    url = "https://datasets-server.huggingface.co/rows?" + urlencode(
                        {"dataset": repository, **split, "offset": 0, "length": 0})
                    value = capture(url, lane, stage)
                    _require(type(value.get("rows")) is list and not value["rows"],
                             "zero-row Viewer request returned rows or omitted its empty row list")
                    _require(type(value.get("features")) is list, "Viewer feature schema required")
                    total = value.get("num_rows_total")
                    _require(type(total) is int and total >= 0, "Viewer declared row total required")
                    record["viewer"]["views"].append({
                        **split, "features": value["features"], "declared_num_rows_total": total,
                        "partial": value.get("partial"), "returned_row_count": 0,
                        "revision_bound": False, "pinned_data_equality_verified": False,
                    })
            except Exception as error:
                failure(lane, stage, error)
            finally:
                if revisions[lane] is None:
                    try:
                        closed = _repo_identity(capture(base, lane, "main_close"), repository)
                        record["main_close_revision"] = closed
                        opened = record["main_open_revision"]
                        if opened is not None:
                            changed = closed != opened
                            record["main_changed_during_observation"] = changed
                            record["live_head_stability"] = "changed" if changed else "same_at_open_and_close_only"
                            _require(not changed, "Hub main changed during metadata observation")
                    except Exception as error:
                        failure(lane, "main_close", error)
                record["status"] = "complete" if len(summary["errors"]) == errors_before else "partial_failed"
    except BaseException as error:
        failure("observer", "interrupted", error)
        raise
    finally:
        summary["completed_at_utc"] = _utc()
        summary["accounted_response_bytes"] = accounted_bytes
        summary["retained_response_bytes"] = sum(row.get("retained_bytes", 0)
                                                  for row in summary["http_observations"])
        summary["viewer_splits_probed"] = viewer_count
        summary["status"] = "complete" if not summary["errors"] else "partial_failed"
        raw = (json.dumps(summary, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
        _write(output / "observation.json", raw)
        for directory in (raw_directory, output):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--span-revision")
    parser.add_argument("--entity-revision")
    args = parser.parse_args(argv)
    try:
        result = observe(args.output_directory, span_revision=args.span_revision, entity_revision=args.entity_revision)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "error": str(error)[:512]}))
        return 1
    print(json.dumps({"status": result["status"], "output_directory": str(args.output_directory.absolute()),
                      "errors": len(result["errors"]), "retained_response_bytes": result["retained_response_bytes"]}))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
