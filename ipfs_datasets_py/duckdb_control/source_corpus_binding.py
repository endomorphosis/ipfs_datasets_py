"""Operation-local verification of a captured source version and its package.

The archived catalog and its original absolute package path are never opened.
The context owns a current package-directory descriptor, not a durable cache or
an authority token. Source and language labels remain unverified declarations.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading

from . import source_corpus_catalog as catalog
from ..huggingface.autoencoder_campaign_release import CampaignPackageError
from ..optimizers.logic_theorem_optimizer import autoencoder_uscode_corpus_export as export


_PUBLIC_FIELDS = {"schema_version", "version_id", "dataset_id", "dataset", "release_id",
                  "package_manifest_artifact", "row_count", "row_digest", "qualification"}
_QUALIFICATION_FIELDS = {"admitted", "formalized", "source_authority_authenticated",
                         "language_verified", "publication_performed"}
_HASH = re.compile(r"^[0-9a-f]{64}$")


class SourceCorpusBindingError(ValueError):
    """Invalid, changed, expired or cross-owner source-package binding."""


def _require(condition, message):
    if not condition:
        raise SourceCorpusBindingError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def validate_source_version(value):
    """Validate the closed, path-free version record without filesystem I/O."""
    try:
        _require(type(value) is dict and set(value) == _PUBLIC_FIELDS, "invalid detached source version fields")
        _require(type(value["schema_version"]) is str and value["schema_version"] == "source-corpus-version-v1",
                 "unsupported detached source version")
        payload = catalog._payload({"dataset": value["dataset"],
                                    "package_manifest_artifact": value["package_manifest_artifact"]})
        identities = catalog._identities(payload)
        for name, expected in zip(("dataset_id", "release_id", "version_id"), identities):
            _require(type(value[name]) is str and value[name] == expected, "source identity mismatch: " + name)
        _require(type(value["row_count"]) is int and 0 <= value["row_count"] <= export.CorpusExportLimits().max_rows,
                 "invalid source row count")
        _require(type(value["row_digest"]) is str and _HASH.fullmatch(value["row_digest"]), "invalid source row digest")
        qualification = value["qualification"]
        _require(type(qualification) is dict and set(qualification) == _QUALIFICATION_FIELDS
                 and all(item is False for item in qualification.values()), "source authority flags changed")
        return {"schema_version": value["schema_version"], "dataset_id": identities[0],
                "release_id": identities[1], "version_id": identities[2], **payload,
                "row_count": value["row_count"], "row_digest": value["row_digest"],
                "qualification": dict(qualification)}
    except (catalog.SourceCorpusCatalogError, TypeError, UnicodeError) as exc:
        raise SourceCorpusBindingError(str(exc)) from exc


def _captured_version(value):
    _require(type(value) is dict and set(value) == _PUBLIC_FIELDS | {"package_directory"},
             "invalid captured source version fields")
    historical = value["package_directory"]
    _require(type(historical) is str and 0 < len(historical) <= 4096
             and len(historical.encode()) <= 4096 and "\x00" not in historical,
             "invalid historical package path declaration")
    # No resolve/stat: the archived location is descriptive and may be gone.
    path = Path(historical)
    _require(path.is_absolute() and str(path) == historical and os.path.normpath(historical) == historical,
             "historical package path must be absolute and normalized")
    return validate_source_version({key: value[key] for key in _PUBLIC_FIELDS})


class SourceCorpusBinding:
    """One lexical, creating-thread context over an exact source package.

    Entering performs exhaustive package verification plus an independent
    ordered row-digest comparison. Every public row iterator is a fresh bounded
    pass. File closure/current-byte verification is repeated on exhaustion and
    when explicitly requested by a consumer before its commit boundary.
    """

    def __init__(self, captured_version, package_directory):
        try:
            self._version_bytes = _json(_captured_version(captured_version))
            self._root = export._path(package_directory)
        except (export.CorpusExportError, TypeError, UnicodeError) as exc:
            raise SourceCorpusBindingError(str(exc)) from exc
        self._thread, self._pid = threading.get_ident(), os.getpid()
        self._fd, self._used = None, False
        self._manifest_bytes = None
        self._files, self._shards = (), ()

    def _owner(self):
        _require(threading.get_ident() == self._thread and os.getpid() == self._pid,
                 "source binding belongs to another thread or process")

    def _active(self):
        self._owner()
        _require(self._fd is not None and self._manifest_bytes is not None, "source binding is not active")
        try:
            export._root_current(self._root, self._fd)
        except (export.CorpusExportError, CampaignPackageError, OSError) as exc:
            raise SourceCorpusBindingError(str(exc)) from exc

    def __enter__(self):
        self._owner()
        _require(not self._used, "source binding cannot be reused")
        self._used = True
        try:
            self._fd = export._directory(self._root)
            version = json.loads(self._version_bytes)
            ref = version["package_manifest_artifact"]
            limits = export.CorpusExportLimits()
            raw = export._read(self._root / export.MANIFEST_NAME, limits.max_manifest_bytes)
            _require(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
                     "source manifest differs from captured version")
            manifest = export._parse(raw)
            export._manifest(manifest, limits)
            report = export.verify_uscode_source_export(self._root, expected_manifest_sha256=ref["sha256"])
            files = [(item["relative_path"], item["sha256"], item["bytes"]) for item in manifest["files"]]
            files.append((export.MANIFEST_NAME, ref["sha256"], ref["bytes"]))
            self._files = tuple(sorted(files))
            self._shards = tuple((item["relative_path"], item["sha256"], item["bytes"], item["row_count"])
                                 for item in report["row_shards"])
            self._manifest_bytes = raw
            _require(report["row_count"] == version["row_count"], "source rows differ from captured version")
            # No decoded rows are retained by the context.
            for _ in self.iter_rows():
                pass
            return self
        except BaseException as exc:
            self.close()
            if isinstance(exc, (export.CorpusExportError, CampaignPackageError, catalog.SourceCorpusCatalogError,
                                OSError, TypeError, UnicodeError)):
                raise SourceCorpusBindingError(str(exc)) from exc
            raise

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._owner()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self._manifest_bytes = None
        self._files, self._shards = (), ()

    @property
    def source_version(self):
        self._active()
        return json.loads(self._version_bytes)

    @property
    def package_root(self):
        self._active()
        return self._root

    @property
    def manifest(self):
        self._active()
        return json.loads(self._manifest_bytes)

    @property
    def manifest_artifact(self):
        return self.source_version["package_manifest_artifact"]

    @property
    def file_descriptors(self):
        self._active()
        return tuple({"relative_path": path, "sha256": digest, "bytes": size}
                     for path, digest, size in self._files)

    @property
    def row_count(self):
        return self.source_version["row_count"]

    @property
    def row_digest(self):
        return self.source_version["row_digest"]

    @property
    def file_count(self):
        self._active()
        return len(self._files)

    @property
    def total_bytes(self):
        self._active()
        return sum(size for _, _, size in self._files)

    def verify_current(self):
        """Rehash the exact current closure; no catalog or remote attestation."""
        try:
            self._active()
            limits = export.CorpusExportLimits()
            export._namespace(self._root, limits, {path for path, _, _ in self._files})
            for path, digest, size in self._files:
                export._hash(self._root / path, {"sha256": digest, "bytes": size}, maximum=limits.max_file_bytes)
            export._namespace(self._root, limits, {path for path, _, _ in self._files})
            self._active()
        except (export.CorpusExportError, CampaignPackageError, OSError) as exc:
            raise SourceCorpusBindingError(str(exc)) from exc

    def iter_rows(self):
        """Return a fresh iterator; complete exhaustion validates its digest."""
        self._active()
        return self._iterate_rows()

    def _iterate_rows(self):
        import pyarrow.parquet as pq
        try:
            self._active()
            version = json.loads(self._version_bytes)
            limits, schema = export.CorpusExportLimits(), export._arrow_schema()
            digest, count = hashlib.sha256(), 0
            for relative, sha, size, expected_count in self._shards:
                self._active()
                path = self._root / relative
                export._hash(path, {"sha256": sha, "bytes": size}, maximum=limits.max_file_bytes)
                with os.fdopen(export._regular(path), "rb") as stream:
                    before = os.fstat(stream.fileno())
                    parquet = pq.ParquetFile(stream)
                    export._parquet_footer(parquet, expected_count, limits, schema)
                    observed = 0
                    for batch in parquet.iter_batches(batch_size=64, use_threads=False):
                        for row in batch.to_pylist():
                            self._active()
                            catalog._row_contract(row)
                            result = {"ordinal": count, **row}
                            digest.update(_json(result) + b"\n")
                            count += 1
                            observed += 1
                            _require(count <= limits.max_rows, "source row limit exceeded")
                            yield result
                    _require(observed == expected_count, "source shard row count changed")
                    after = os.fstat(stream.fileno())
                    _require(export._identity(before) == export._identity(after), "source shard changed during row binding")
                export._current_file(path, after)
            _require(count == version["row_count"] and digest.hexdigest() == version["row_digest"],
                     "source rows differ from captured version")
            self.verify_current()
        except (export.CorpusExportError, CampaignPackageError, catalog.SourceCorpusCatalogError, OSError,
                TypeError, UnicodeError) as exc:
            raise SourceCorpusBindingError(str(exc)) from exc
