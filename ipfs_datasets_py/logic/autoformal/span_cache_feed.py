"""Bounded, resumable discovery of immutable span census bundles.

One local DuckDB owner per machine; no model weights, native supervisor writes,
training, head promotion or legal admission. Acknowledgement is explicit and
means only that a caller durably recorded the verified inputs.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from urllib.parse import quote, urlsplit

from .span_cache_exchange import MANIFEST_REPO_DIR, load_exchange_bundle, _read_regular_snapshot

SCHEMA = "span-cache-incremental-feed/v1"
DEFAULT_REPOSITORY = "justicedao/uscode-autoformal-span-cache"
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_MANIFEST = re.compile(r"autoformal/uscode/exchanges/[A-Za-z0-9_-]+/exchange-([0-9a-f]{64})\.manifest\.json\Z")
_TABLES = {("main", "feed_meta"), ("main", "feed_scan"), ("main", "feed_bundles")}


class FeedError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _positive(value, label):
    if type(value) is not int or value < 1:
        raise FeedError(label + " must be a positive integer")


def _relative(value):
    if not isinstance(value, str) or value != str(PurePosixPath(value)) or value.startswith("/") or "\\" in value or any(p in (".", "..", "") for p in value.split("/")):
        raise FeedError("invalid relative repository path")
    return value


class HubExchangeClient:
    """One bounded tree page at a time; exact-commit, selective downloads only."""

    def __init__(self, *, api=None, max_page_bytes=2 * 1024 * 1024, timeout_seconds=30):
        if api is None:
            from huggingface_hub import HfApi
            api = HfApi()
        _positive(max_page_bytes, "max_page_bytes")
        if not 0 < timeout_seconds <= 60:
            raise FeedError("timeout must be in (0, 60]")
        self.api, self.max_page_bytes, self.timeout = api, max_page_bytes, timeout_seconds

    def resolve(self, repository_id, revision):
        value = self.api.repo_info(repository_id, repo_type="dataset", revision=revision, timeout=self.timeout).sha
        if not isinstance(value, str) or not _HEX40.fullmatch(value):
            raise FeedError("Hub did not resolve an immutable commit")
        return value

    def list_page(self, repository_id, revision, cursor, *, max_entries):
        from huggingface_hub.utils import get_session, hf_raise_for_status
        base = f"{self.api.endpoint}/api/datasets/{repository_id}/tree/{revision}/{quote(MANIFEST_REPO_DIR, safe='')}"
        url = cursor or base
        # Pagination may add query parameters, but cannot redirect credentials to
        # another host, repository, revision or directory.
        parsed, expected = urlsplit(url), urlsplit(base)
        if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path) or parsed.fragment:
            raise FeedError("Hub pagination cursor changed the immutable tree")
        params = None if cursor else {"recursive": True, "expand": False, "limit": max_entries}
        with get_session().get(url, params=params, headers=self.api._build_hf_headers(),
                               stream=True, timeout=self.timeout, allow_redirects=False) as response:
            hf_raise_for_status(response)
            if response.status_code != 200:
                raise FeedError("unexpected Hub tree response")
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > self.max_page_bytes:
                    raise FeedError("Hub tree page exceeds byte bound")
            entries = json.loads(raw)
            if not isinstance(entries, list) or len(entries) > max_entries:
                raise FeedError("Hub tree page exceeds entry bound")
            next_cursor = response.links.get("next", {}).get("url", "")
        return entries, next_cursor

    def fetch(self, repository_id, revision, filename, directory, *, max_bytes):
        _relative(filename)
        if not (_MANIFEST.fullmatch(filename) or re.fullmatch(
                r"autoformal/uscode/(census|goals)/[A-Za-z0-9_-]+/(census|goals)-[0-9a-f]{64}\.parquet", filename)):
            raise FeedError("only exchange manifests, census and goals may be downloaded")
        if not isinstance(revision, str) or not _HEX40.fullmatch(revision):
            raise FeedError("downloads require an immutable commit")
        _positive(max_bytes, "max_bytes")
        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
        metadata = get_hf_file_metadata(hf_hub_url(repository_id, filename, repo_type="dataset", revision=revision), timeout=self.timeout)
        if metadata.commit_hash != revision or type(metadata.size) is not int or not 0 <= metadata.size <= max_bytes:
            raise FeedError("Hub file metadata differs from pinned revision or byte bound")
        path = Path(hf_hub_download(repo_id=repository_id, repo_type="dataset", revision=revision,
                                   filename=filename, local_dir=directory, etag_timeout=self.timeout))
        if path.is_symlink() or not path.is_file() or path.stat().st_size != metadata.size:
            raise FeedError("Hub download differs from bounded metadata")
        return path


_SOURCE_FIELDS = ("record_id", "sample", "source_span_id", "text", "source_text_sha256", "legal_id", "document_id")


def _stable_source(record):
    return {key: record[key] for key in _SOURCE_FIELDS if key in record}


def _attempt_source(row, payload):
    """Restore validated source metadata; a remote report confers no authority."""
    if "qualification_attempt" not in payload:
        return None
    try:
        from ...huggingface.autoencoder_span_attempts import _validate
        from ...optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
        report = payload["qualification_attempt"]
        if not isinstance(report, dict):
            raise ValueError("attempt report must be an object")
        _validate(report)
        source = report["source_provenance"]["source_record"]
        record_id = source["record_id"]
        if not isinstance(record_id, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", record_id):
            raise ValueError("attempt source identity must be a full SHA-256")
        SampleRecord.from_dict(source["sample"])
        if (source["source_span_id"] != row["source_span_id"]
                or source["text"] != row["source_text"]
                or source["source_text_sha256"] != row["source_text_sha256"]
                or source.get("legal_id", "") != row["legal_id"]
                or hashlib.sha256(source["text"].encode()).hexdigest() != row["source_text_sha256"]):
            raise ValueError("attempt source differs from census text, span or citation")
        for key in ("legal_id", "document_id"):
            if key in source and (not isinstance(source[key], str) or len(source[key]) > 2048):
                raise ValueError("attempt source metadata must be a bounded string")
        return _stable_source(source)
    except (KeyError, TypeError, ValueError) as exc:
        raise FeedError("invalid qualification attempt source: " + str(exc)) from exc


def _merge_source(records, record):
    previous = records.get(record["record_id"])
    if previous is None:
        records[record["record_id"]] = record
    else:
        if _stable_source(previous) != _stable_source(record):
            raise FeedError("stable source fields changed under an existing record identity")
        previous["observations"].extend(record["observations"])


def source_records(bundle, *, repository_id, revision, manifest_in_repo, shard_count=1, shard_index=0):
    """Return source records with complete evidence, without upgrading authority.

    Qualified-attempt transports preserve their original source identity and
    sample metadata, including failed attempts. Older census rows use a content
    identity that omits observation/model/release. Frozen splits remain caller
    policy; observations never authenticate or admit their source.
    """
    _positive(shard_count, "shard_count")
    if type(shard_index) is not int or not 0 <= shard_index < shard_count:
        raise FeedError("invalid machine shard")
    records = {}
    for row in bundle["census_rows"]:
        identity = {"repository_id": repository_id, "source_span_id": row["source_span_id"],
                    "legal_id": row["legal_id"], "source_text_sha256": row["source_text_sha256"]}
        payload = json.loads(row["input_json"])
        source = _attempt_source(row, payload)
        digest = source["record_id"].removeprefix("sha256:") if source is not None else _sha(_json(identity).encode())
        if int(digest, 16) % shard_count != shard_index:
            continue
        observation = {"repository_id": repository_id, "revision": revision,
                       "manifest_in_repo": manifest_in_repo, "fingerprint": bundle["fingerprint"],
                       "manifest_sha256": bundle["manifest_sha256"], "census_sha256": row["census_sha256"],
                       "census_row": row, "input": payload}
        if source is None:
            legal = re.fullmatch(r"usc:(?:us:)?(\d+):(.+)", row["legal_id"])
            source = {"record_id": "sha256:" + digest, **identity, "text": row["source_text"],
                      "sample": {"title": legal.group(1) if legal else row["legal_id"] or "unclassified",
                                 "section": legal.group(2) if legal else row["source_span_id"],
                                 "text": row["source_text"], "citation": row["legal_id"] or row["source_span_id"]}}
        record = {**source, "repository_id": repository_id, "observations": [observation],
                  "admitted": False, "formalized": False, "source_authority_authenticated": False}
        record["provenance"] = {"source_identity": identity, "observations": record["observations"],
                                "source_authority_authenticated": False}
        _merge_source(records, record)
    return [records[key] for key in sorted(records)]


class SpanCacheFeed:
    """Machine-local durable discovery cursor and verified, unacknowledged inbox."""

    def __init__(self, state_path, artifact_directory, *, repository_id=DEFAULT_REPOSITORY,
                 revision="main", shard_count=1, shard_index=0, client=None):
        from ...duckdb_control.connections import ConnectionManager
        _positive(shard_count, "shard_count")
        if type(shard_index) is not int or not 0 <= shard_index < shard_count:
            raise FeedError("invalid machine shard")
        if not isinstance(repository_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_id):
            raise FeedError("repository must have an owner and name")
        if not isinstance(revision, str) or not revision or len(revision) > 255:
            raise FeedError("revision must be a bounded nonempty string")
        if str(state_path) in ("", ":memory:"):
            raise FeedError("feed requires a durable state path")
        self.path, self.artifacts = Path(state_path).resolve(), Path(artifact_directory).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.repository_id, self.revision = repository_id, revision
        self.shard_count, self.shard_index = shard_count, shard_index
        self.client = client
        self._pid, self._closed = os.getpid(), False
        self._lock = self.path.with_name(self.path.name + ".owner.lock").open("a+b")
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock.close()
            raise FeedError("feed already has a local owner") from exc
        fresh = not self.path.exists()
        self._manager = ConnectionManager(control_path=str(self.path))
        config = _json({"schema": SCHEMA, "repository_id": repository_id, "revision": revision,
                        "artifacts": str(self.artifacts), "shard_count": shard_count, "shard_index": shard_index})
        try:
            with self._manager.short_writer_transaction() as cx:
                tables = set(cx.execute("SELECT table_schema,table_name FROM information_schema.tables WHERE table_schema NOT IN ('information_schema','pg_catalog')").fetchall())
                if not tables and fresh:
                    cx.execute("CREATE TABLE feed_meta (singleton INTEGER PRIMARY KEY, config VARCHAR NOT NULL)")
                    cx.execute("CREATE TABLE feed_scan (singleton INTEGER PRIMARY KEY, revision VARCHAR NOT NULL, cursor VARCHAR NOT NULL, done BOOLEAN NOT NULL)")
                    cx.execute("CREATE TABLE feed_bundles (path VARCHAR PRIMARY KEY, revision VARCHAR NOT NULL, blob_id VARCHAR NOT NULL, size BIGINT NOT NULL, status VARCHAR NOT NULL, manifest_path VARCHAR, fingerprint VARCHAR, last_attempt DOUBLE NOT NULL, attempts BIGINT NOT NULL, error VARCHAR NOT NULL)")
                    cx.execute("INSERT INTO feed_meta VALUES (1, ?)", [config])
                elif tables != _TABLES:
                    raise FeedError("foreign or incomplete feed database")
                if cx.execute("SELECT config FROM feed_meta WHERE singleton=1").fetchone() != (config,):
                    raise FeedError("feed configuration changed; use a separate state path")
        except BaseException:
            self.close()
            raise

    def _check(self):
        if self._closed or self._pid != os.getpid():
            raise FeedError("feed owner is closed or belongs to another process")

    def close(self):
        if not self._closed:
            self._manager.close()
            self._lock.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def acknowledge(self, manifest_in_repo, *, fingerprint):
        """After durable downstream registration only; this never marks trained."""
        self._check()
        with self._manager.short_writer_transaction() as cx:
            old = cx.execute("SELECT status,fingerprint FROM feed_bundles WHERE path=?", [manifest_in_repo]).fetchone()
            if old is None or old[0] not in ("ready", "acknowledged") or old[1] != fingerprint:
                raise FeedError("acknowledgement differs from a verified bundle")
            cx.execute("UPDATE feed_bundles SET status='acknowledged' WHERE path=?", [manifest_in_repo])

    def _discover(self, head, max_entries):
        with self._manager.short_writer_transaction() as cx:
            scan = cx.execute("SELECT revision,cursor,done FROM feed_scan WHERE singleton=1").fetchone()
        if scan is not None and scan[2] and scan[0] == head:
            return {"revision": head, "listed_entries": 0, "discovered": 0, "complete": True}
        pinned, cursor = (scan[0], scan[1]) if scan is not None and not scan[2] else (head, "")
        entries, next_cursor = self.client.list_page(self.repository_id, pinned, cursor, max_entries=max_entries)
        if not isinstance(entries, list) or len(entries) > max_entries or not isinstance(next_cursor, str) or len(next_cursor) > 16384:
            raise FeedError("invalid bounded tree page")
        if next_cursor and next_cursor == cursor:
            raise FeedError("Hub pagination did not advance")
        found = []
        for item in entries:
            if not isinstance(item, dict):
                raise FeedError("invalid tree entry")
            path = item.get("path", "")
            if item.get("type") != "file" or not _MANIFEST.fullmatch(path):
                continue
            size, blob = item.get("size"), item.get("oid")
            if type(size) is not int or not 0 < size <= 1024 * 1024 or not isinstance(blob, str) or not _HEX40.fullmatch(blob):
                raise FeedError("invalid exchange manifest tree metadata")
            found.append((path, pinned, blob, size))
        with self._manager.short_writer_transaction() as cx:
            new = 0
            for path, rev, blob, size in found:
                old = cx.execute("SELECT blob_id,size FROM feed_bundles WHERE path=?", [path]).fetchone()
                if old is not None and old != (blob, size):
                    raise FeedError("immutable exchange manifest changed at an existing path")
                if old is None:
                    cx.execute("INSERT INTO feed_bundles VALUES (?, ?, ?, ?, 'pending', NULL, NULL, 0, 0, '')", [path, rev, blob, size])
                    new += 1
            cx.execute("INSERT OR REPLACE INTO feed_scan VALUES (1, ?, ?, ?)", [pinned, next_cursor, not bool(next_cursor)])
        return {"revision": pinned, "listed_entries": len(entries), "discovered": new, "complete": not bool(next_cursor)}

    def _download(self, path, revision, blob, manifest_size, *, max_bytes, budget):
        directory = self.artifacts / revision
        def fetch(filename, maximum):
            if budget["files"] < 1 or maximum < 1 or budget["bytes"] < 1:
                raise FeedError("poll download budget exhausted")
            budget["files"] -= 1
            reserved = min(maximum, budget["bytes"])
            budget["bytes"] -= reserved
            local = Path(self.client.fetch(self.repository_id, revision, filename, directory,
                                          max_bytes=reserved))
            if local.is_symlink() or not local.is_file() or local.stat().st_size > reserved:
                raise FeedError("download exceeds declared byte budget")
            budget["bytes"] += reserved - local.stat().st_size
            budget["downloaded_bytes"] += local.stat().st_size
            if local.resolve() != (directory / filename).resolve():
                raise FeedError("download escaped the bound repository layout")
            return local
        manifest = fetch(path, min(manifest_size, max_bytes))
        raw = _read_regular_snapshot(manifest, max_bytes=1024 * 1024)
        if len(raw) != manifest_size or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != blob:
            raise FeedError("manifest differs from immutable tree blob")
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("repository_id") != self.repository_id or value.get("path_in_repo") != path:
            raise FeedError("manifest repository or path binding differs")
        fingerprint = _MANIFEST.fullmatch(path).group(1)
        if value.get("fingerprint") != fingerprint:
            raise FeedError("manifest path fingerprint differs")
        total = len(raw)
        descriptors = []
        for kind in ("census", "goals"):
            descriptor = value.get(kind)
            if not isinstance(descriptor, dict):
                raise FeedError("missing exchange descriptor")
            name, size = _relative(descriptor.get("path_in_repo")), descriptor.get("bytes")
            if not name.startswith("autoformal/uscode/" + kind + "/") or PurePosixPath(name).name != kind + "-" + fingerprint + ".parquet":
                raise FeedError("only canonical census/goals files can be downloaded")
            if type(size) is not int or size < 1:
                raise FeedError("invalid exchange size")
            total += size
            descriptors.append((name, size))
        if total > max_bytes or sum(size for _, size in descriptors) > budget["bytes"] or budget["files"] < 2:
            raise FeedError("complete exchange exceeds remaining poll budget")
        for name, size in descriptors:
            fetch(name, size)
        return manifest

    def poll_once(self, *, max_bundles=4, max_listing_entries=100, max_download_files=12,
                  max_download_bytes=64 * 1024 * 1024, max_bundle_bytes=64 * 1024 * 1024,
                  max_rows=1000, max_ready_bytes=64 * 1024 * 1024):
        """Observe one tree page and retry bounded oldest unacknowledged bundles.

        Unfinished listings and pending files remain pinned to their original
        commit when the branch moves. Ready results repeat until acknowledged.
        Failures are durable/retryable and do not skip the discovery cursor.
        """
        self._check()
        for name, value in locals().copy().items():
            if name.startswith("max_"):
                _positive(value, name)
        if self.client is None:
            self.client = HubExchangeClient()
        errors, discovery, head = [], {}, ""
        try:
            head = self.client.resolve(self.repository_id, self.revision)
            if not isinstance(head, str) or not _HEX40.fullmatch(head):
                raise FeedError("resolved revision is not an immutable commit")
            discovery = self._discover(head, max_listing_entries)
        except Exception as exc:
            errors.append({"phase": "discovery", "error": type(exc).__name__, "message": str(exc)[:500]})
        with self._manager.short_writer_transaction() as cx:
            pending = cx.execute("SELECT path,revision,blob_id,size,status,manifest_path FROM feed_bundles WHERE status!='acknowledged' ORDER BY last_attempt,path LIMIT ?", [max_bundles]).fetchall()
        budget = {"bytes": max_download_bytes, "files": max_download_files, "downloaded_bytes": 0}
        ready, total_decoded, merged_records = [], 0, {}
        for path, revision, blob, size, status, local in pending:
            try:
                manifest = Path(local) if status == "ready" else self._download(path, revision, blob, size, max_bytes=max_bundle_bytes, budget=budget)
                loaded = load_exchange_bundle(manifest, max_bytes=max_bundle_bytes, max_rows=max_rows,
                                              max_decoded_bytes=max(1, max_ready_bytes - total_decoded))
                if loaded["manifest"].get("repository_id") != self.repository_id or loaded["manifest"].get("path_in_repo") != path:
                    raise FeedError("verified bundle binding changed")
                raw = _read_regular_snapshot(manifest, max_bytes=1024 * 1024)
                if hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != blob:
                    raise FeedError("retained manifest differs from pinned blob")
                total_decoded += loaded["decoded_bytes"]
                if total_decoded > max_ready_bytes:
                    raise FeedError("ready results exceed decoded byte budget")
                records = source_records(loaded, repository_id=self.repository_id, revision=revision,
                    manifest_in_repo=path, shard_count=self.shard_count, shard_index=self.shard_index)
                for record in records:
                    previous = merged_records.get(record["record_id"])
                    if previous is not None and _stable_source(previous) != _stable_source(record):
                        raise FeedError("stable source fields changed under an existing record identity")
                for record in records:
                    _merge_source(merged_records, record)
                ready.append({"manifest_path": str(manifest), "manifest_in_repo": path, "revision": revision,
                              "fingerprint": loaded["fingerprint"], "census_row_count": len(loaded["census_rows"]),
                              "goal_count": len(loaded["goal_rows"]), "record_ids": [r["record_id"] for r in records]})
                with self._manager.short_writer_transaction() as cx:
                    cx.execute("UPDATE feed_bundles SET status='ready',manifest_path=?,fingerprint=?,last_attempt=?,attempts=attempts+1,error='' WHERE path=?",
                               [str(manifest), loaded["fingerprint"], time.time(), path])
            except Exception as exc:
                errors.append({"phase": "bundle", "manifest_in_repo": path, "revision": revision,
                               "error": type(exc).__name__, "message": str(exc)[:500]})
                with self._manager.short_writer_transaction() as cx:
                    cx.execute("UPDATE feed_bundles SET status='pending',manifest_path=NULL,fingerprint=NULL,last_attempt=?,attempts=attempts+1,error=? WHERE path=?", [time.time(), type(exc).__name__ + ": " + str(exc)[:500], path])
        with self._manager.short_writer_transaction() as cx:
            counts = dict(cx.execute("SELECT status,count(*) FROM feed_bundles GROUP BY status").fetchall())
        return {"schema": SCHEMA, "repository_id": self.repository_id, "head_revision": head,
                "discovery": discovery, "new_bundles": ready,
                "records": [merged_records[key] for key in sorted(merged_records)],
                "counts": counts, "errors": errors, "downloaded_bytes": budget["downloaded_bytes"],
                "download_byte_budget_used": max_download_bytes - budget["bytes"],
                "download_file_attempts": max_download_files - budget["files"], "decoded_bytes": total_decoded,
                "shard_count": self.shard_count, "shard_index": self.shard_index,
                "weights_downloaded": False, "training_executed": False, "enqueued": False,
                "admitted": False, "formalized": False}
