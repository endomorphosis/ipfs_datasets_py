"""Offline metadata inventory of every declared U.S. Code corpus shard.

Physical closure covers the pinned release's corpus family, not official source
authority or the whole federal corpus. Source inputs are identified before
embedding production; no vectors, parser outputs or global text collection are
stored here. Materialization revalidates only the requested source closure.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field, replace
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Sequence

from . import autoencoder_uscode_import as importer
from .autoencoder_corpus_manifest import SourceArtifact, SourceSpan
from .autoencoder_embedding_production import (
    EmbeddingInput, MAX_BYTES, MAX_RECORDS, MAX_TEXT_BYTES,
    validate_embedding_inputs,
)


SCHEMA_VERSION = "autoencoder-uscode-source-inventory-v1"
SCOPE = "declared_corpus_family_only"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ROW_STATUSES = frozenset({
    "invalid_wrapper", "record_hash_mismatch", "invalid_record_json",
    "wrapper_identity_mismatch", "duplicate_entry_cid", "invalid_corpus_record",
    "retrieval_disposition_excluded", "missing_text", "text_exceeds_bound",
    "identity_mismatch", "release_point_mismatch", "ready_published_text",
    "shard_unavailable", "shard_corrupt",
})
_ROW_FIELDS = {"row_index", "entry_cid", "legal_id", "original_status", "status",
               "duplicate_entry_cid", "wrapper_verified", "metadata"}
_META_FIELDS = {"record_sha256", "text_sha256", "text_bytes",
                "normalized_content_sha256", "canonical_identity", "input_id"}
_IDENTITY_FIELDS = {"document_id", "title", "section", "citation"}


class USCodeInventoryError(ValueError):
    """An incomplete, malformed, changed or over-budget source inventory."""


@dataclass(frozen=True)
class InventoryLimits:
    max_rows: int = 65536
    max_corpus_shards: int = 256
    max_declared_compressed_bytes: int = 4 * 1024**3
    max_metadata_bytes: int = 64 * 1024**2

    def __post_init__(self):
        for name, maximum in (("max_rows", 65536), ("max_corpus_shards", 256),
                              ("max_declared_compressed_bytes", 4 * 1024**3),
                              ("max_metadata_bytes", 64 * 1024**2)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= maximum:
                raise USCodeInventoryError(f"{name} exceeds inventory bounds")


def _json(value):
    try:
        return importer._json(value)
    except (ValueError, TypeError) as exc:
        raise USCodeInventoryError("invalid canonical inventory JSON") from exc


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != expected:
        raise USCodeInventoryError(f"invalid {label} fields")
    return value


def _integer(value, label, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise USCodeInventoryError(f"invalid bounded {label}")
    return value


def _text(value, label, *, empty=False):
    if (type(value) is not str or not empty and not value.strip()
            or len(value) > 4096 or len(value.encode("utf-8")) > 4096):
        raise USCodeInventoryError(f"invalid bounded {label}")
    return value


def _digest(value):
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise USCodeInventoryError("invalid SHA-256")
    return value


def _reference(value):
    _keys(value, {"sha256", "bytes"}, "artifact reference")
    _digest(value["sha256"])
    _integer(value["bytes"], "artifact bytes", 1)
    return value


def _artifact(value):
    _keys(value, {"relative_path", "family", "sha256", "bytes", "row_count",
                  "schema_id", "media_type"}, "release artifact")
    for name in ("relative_path", "family", "schema_id", "media_type"):
        _text(value[name], name)
    try:
        importer._path(value["relative_path"])
    except ValueError as exc:
        raise USCodeInventoryError("unsafe artifact path") from exc
    _digest(value["sha256"])
    _integer(value["bytes"], "artifact bytes", 1)
    _integer(value["row_count"], "artifact rows")
    if value["family"] == "corpus" and (
            not value["relative_path"].startswith("data/corpus/")
            or value["schema_id"] != "uscode-corpus-row/v1"
            or not 1 <= value["row_count"] <= 4096):
        raise USCodeInventoryError("invalid corpus descriptor")
    return value


def _release_metadata(release):
    return {"repo_id": release.repo_id, "revision": release.revision,
            "manifest": release.manifest_reference, "release_id": release.release_id,
            "manifest_digest": release.manifest_digest, "release_point": release.release_point,
            "source_revision": release.source_revision, "default_excludes_recovery": True,
            "import_limits": asdict(release.limits),
            "other_artifacts": [asdict(item) for item in sorted(
                release.artifacts, key=lambda item: item.relative_path) if item.family != "corpus"]}


def _validate_release(value):
    _keys(value, {"repo_id", "revision", "manifest", "release_id", "manifest_digest",
                  "release_point", "source_revision", "default_excludes_recovery",
                  "import_limits", "other_artifacts"}, "release")
    for name in ("repo_id", "revision", "release_id", "release_point", "source_revision"):
        _text(value[name], name)
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", value["repo_id"]):
        raise USCodeInventoryError("invalid release repository")
    if any(not re.fullmatch(r"[0-9a-f]{40}", value[name]) for name in ("revision", "source_revision")):
        raise USCodeInventoryError("mutable release revision")
    _reference(value["manifest"])
    _digest(value["manifest_digest"])
    expected = f"hf:{value['repo_id']}@{value['revision']}#manifest-sha256:{value['manifest']['sha256']}"
    if value["release_id"] != expected or value["default_excludes_recovery"] is not True:
        raise USCodeInventoryError("release identity or recovery declaration mismatch")
    try:
        limits = importer.USCodeImportLimits(**_keys(value["import_limits"],
            set(asdict(importer.USCodeImportLimits())), "import limits"))
    except (ValueError, TypeError) as exc:
        raise USCodeInventoryError("invalid import limits") from exc
    others = value["other_artifacts"]
    if type(others) is not list or len(others) > limits.max_artifacts:
        raise USCodeInventoryError("other artifact inventory exceeds bound")
    for item in others:
        _artifact(item)
        if item["family"] == "corpus":
            raise USCodeInventoryError("corpus descriptor in other family inventory")
    paths = [item["relative_path"] for item in others]
    if paths != sorted(set(paths)):
        raise USCodeInventoryError("other artifact paths must be unique and sorted")
    return limits


def _canonical_identity(release, row, payload):
    """Identity checks independent of retrieval and text-length dispositions."""
    from ...processors.legal_data.uscode_identity import parse_legal_id, normalize_title, normalize_section_token
    from ...processors.legal_data.uscode_release_schema import CorpusRecord, validate_entry_cid

    try:
        CorpusRecord.from_mapping(payload)
        if validate_entry_cid(row.entry_cid) != row.entry_cid or payload.get("schema_version") != importer.RELEASE_SCHEMA:
            return None
        identity = parse_legal_id(row.legal_id)
        if identity.legal_id != row.legal_id or identity.jurisdiction != "us":
            return None
        if normalize_title(payload.get("title")) != identity.title or normalize_section_token(payload.get("section")) != identity.section:
            return None
        for name, alias in (("subsection", "subsection"), ("appendix", "appendix"), ("note", "note"),
                            ("granule", "granule_id"), ("edition", "edition"), ("schedule", "schedule"), ("kind", "kind")):
            if payload.get(alias) is not None and replace(identity, **{name: payload[alias]}).legal_id != identity.legal_id:
                return None
        if payload.get("release_point") != release.release_point:
            return None
        return {"document_id": replace(identity, edition=None).legal_id,
                "title": identity.title, "section": identity.section,
                "citation": identity.canonical_citation}
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        return None


def _input(release, identity, text):
    raw = text.encode("utf-8")
    source = SourceSpan(SourceArtifact(_sha(raw), len(raw)), "us_code", release.release_id,
                        identity["document_id"], "en", identity["citation"], 0, len(raw), "identity")
    return EmbeddingInput(source, identity["title"], identity["section"], text, identity["citation"])


def _metadata(release, row):
    payload = row.payload
    text = payload.get("text")
    raw = text.encode("utf-8") if type(text) is str else None
    identity = _canonical_identity(release, row, payload)
    input_id = None
    if identity is not None and raw and text.strip():
        try:
            input_id = _input(release, identity, text).input_id
        except ValueError:
            pass  # Retain a source disposition; never substitute another input.
    return {"record_sha256": row.record_sha256,
            "text_sha256": _sha(raw) if raw is not None else None,
            "text_bytes": len(raw) if raw is not None else None,
            "normalized_content_sha256": _sha(" ".join(text.split()).casefold().encode("utf-8")) if raw is not None else None,
            "canonical_identity": identity, "input_id": input_id}


def _shard_rows(release, wrapped, verified_rows, wrapper_failures, *, metadata_budget):
    decoded = importer._decode_corpus_shard(release, wrapped)
    verified = {row.row_index: row for row in verified_rows}
    failures = {item.row_index: item for item in wrapper_failures}
    rows = []
    accounted = 0
    for item in decoded.dispositions:
        # The public reader's local duplicate disposition is unchanged. Keep
        # an invalid occurrence's original failure in the full inventory;
        # global duplicate accounting will still exclude every claimed CID.
        item = failures.get(item.row_index, item)
        _text(item.entry_cid, "entry CID", empty=True)
        _text(item.legal_id, "legal ID", empty=True)
        meta = _metadata(release, verified[item.row_index]) if item.row_index in verified else None
        if meta is not None:
            _validate_metadata(meta, release.limits)
        status = item.status
        if status == "ready_published_text" and (meta is None or meta["input_id"] is None):
            status = "embedding_input_ineligible"
        row = {"row_index": item.row_index, "entry_cid": item.entry_cid,
               "legal_id": item.legal_id, "original_status": item.status,
               "status": status, "duplicate_entry_cid": False,
               "wrapper_verified": meta is not None, "metadata": meta}
        accounted += len(_json(row)) + 1
        if accounted > metadata_budget:
            raise USCodeInventoryError("inventory metadata exceeds byte bound")
        rows.append(row)
    return rows


def _validate_metadata(meta, import_limits):
    _keys(meta, _META_FIELDS, "row metadata")
    _digest(meta["record_sha256"])
    if meta["text_sha256"] is None:
        if meta["text_bytes"] is not None or meta["normalized_content_sha256"] is not None:
            raise USCodeInventoryError("inconsistent absent text metadata")
    else:
        _digest(meta["text_sha256"])
        _digest(meta["normalized_content_sha256"])
        _integer(meta["text_bytes"], "text bytes", 0, import_limits.max_record_bytes)
    identity = meta["canonical_identity"]
    if identity is not None:
        _keys(identity, _IDENTITY_FIELDS, "canonical row identity")
        for name, text in identity.items():
            _text(text, name)
    if meta["input_id"] is not None:
        if (type(meta["input_id"]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", meta["input_id"])
                or identity is None or meta["text_sha256"] is None
                or not 1 <= meta["text_bytes"] <= MAX_TEXT_BYTES):
            raise USCodeInventoryError("invalid source input identity")


def _validate(data, limits):
    _keys(data, {"schema_version", "scope", "release", "shards"}, "inventory")
    if data["schema_version"] != SCHEMA_VERSION or data["scope"] != SCOPE:
        raise USCodeInventoryError("unsupported source inventory profile")
    import_limits = _validate_release(data["release"])
    shards = data["shards"]
    if type(shards) is not list or not 1 <= len(shards) <= limits.max_corpus_shards:
        raise USCodeInventoryError("corpus shard count exceeds inventory bound")
    paths, total_rows, total_bytes, entries = [], 0, 0, Counter()
    for shard in shards:
        _keys(shard, {"artifact", "status", "rows_scanned", "rows"}, "shard")
        artifact = _artifact(shard["artifact"])
        if artifact["family"] != "corpus":
            raise USCodeInventoryError("noncorpus shard in source inventory")
        paths.append(artifact["relative_path"])
        total_rows += artifact["row_count"]
        total_bytes += artifact["bytes"]
        if total_rows > limits.max_rows or total_bytes > limits.max_declared_compressed_bytes:
            raise USCodeInventoryError("declared corpus exceeds inventory bounds")
        if type(shard["status"]) is not str or shard["status"] not in {"verified", "unavailable", "corrupt"}:
            raise USCodeInventoryError("invalid shard status")
        expected_scanned = artifact["row_count"] if shard["status"] == "verified" else 0
        if shard["status"] == "verified" and (
                artifact["media_type"] != "application/vnd.apache.parquet"
                or artifact["bytes"] > import_limits.max_shard_bytes):
            raise USCodeInventoryError("verified shard exceeds reader contract")
        _integer(shard["rows_scanned"], "scanned row count")
        if shard["rows_scanned"] != expected_scanned or type(shard["rows"]) is not list or len(shard["rows"]) != artifact["row_count"]:
            raise USCodeInventoryError("physical ordinal coverage differs from descriptor")
        for ordinal, row in enumerate(shard["rows"]):
            _keys(row, _ROW_FIELDS, "inventory row")
            if type(row["row_index"]) is not int or row["row_index"] != ordinal:
                raise USCodeInventoryError("physical row ordinals must be exact and ordered")
            for name in ("entry_cid", "legal_id"):
                _text(row[name], name, empty=True)
            if (type(row["original_status"]) is not str or row["original_status"] not in _ROW_STATUSES
                    or type(row["status"]) is not str or row["status"] not in _ROW_STATUSES | {"embedding_input_ineligible"}
                    or type(row["duplicate_entry_cid"]) is not bool or type(row["wrapper_verified"]) is not bool):
                raise USCodeInventoryError("invalid row status or verification flag")
            if row["wrapper_verified"] != (row["metadata"] is not None):
                raise USCodeInventoryError("wrapper verification and metadata disagree")
            if row["metadata"] is not None:
                _validate_metadata(row["metadata"], import_limits)
                if not row["entry_cid"]:
                    raise USCodeInventoryError("verified corpus wrapper has absent identity")
            if shard["status"] != "verified":
                if (row["original_status"] != "shard_" + shard["status"] or row["metadata"] is not None
                        or row["entry_cid"] or row["legal_id"]):
                    raise USCodeInventoryError("unread shard cannot claim verified row metadata")
            elif row["original_status"].startswith("shard_"):
                raise USCodeInventoryError("verified shard cannot contain unread ordinals")
            if row["original_status"] in {"invalid_wrapper", "record_hash_mismatch", "invalid_record_json", "wrapper_identity_mismatch"} and row["metadata"] is not None:
                raise USCodeInventoryError("invalid wrapper cannot claim verified metadata")
            if (row["original_status"] not in {"invalid_wrapper", "record_hash_mismatch", "invalid_record_json",
                    "wrapper_identity_mismatch", "shard_unavailable", "shard_corrupt"}
                    and row["metadata"] is None):
                raise USCodeInventoryError("decoded row lacks verified wrapper metadata")
            if row["original_status"] == "ready_published_text" and (
                    row["metadata"]["canonical_identity"] is None
                    or row["metadata"]["text_sha256"] is None
                    or not 1 <= row["metadata"]["text_bytes"] <= import_limits.max_text_bytes):
                raise USCodeInventoryError("ready row lacks eligible source metadata")
            if row["entry_cid"]:
                entries[row["entry_cid"]] += 1
    if paths != sorted(set(paths)) or set(paths) & {item["relative_path"] for item in data["release"]["other_artifacts"]}:
        raise USCodeInventoryError("release paths must be unique and corpus paths sorted")
    if len(paths) + len(data["release"]["other_artifacts"]) > import_limits.max_artifacts:
        raise USCodeInventoryError("release artifact inventory exceeds import bound")
    for shard in shards:
        for row in shard["rows"]:
            duplicate = bool(row["entry_cid"] and entries[row["entry_cid"]] > 1)
            if row["original_status"] == "duplicate_entry_cid" and not duplicate:
                raise USCodeInventoryError("local duplicate disposition lacks another occurrence")
            status = row["original_status"]
            if status == "ready_published_text" and row["metadata"]["input_id"] is None:
                status = "embedding_input_ineligible"
            if duplicate:
                status = "duplicate_entry_cid"
            if row["duplicate_entry_cid"] != duplicate or row["status"] != status:
                raise USCodeInventoryError("global duplicate disposition mismatch")


@dataclass(frozen=True)
class USCodeSourceInventory:
    _raw: bytes
    limits: InventoryLimits = InventoryLimits()
    _sha256: str = field(init=False, repr=False)

    def __post_init__(self):
        if type(self.limits) is not InventoryLimits or type(self._raw) is not bytes or not 1 <= len(self._raw) <= self.limits.max_metadata_bytes:
            raise USCodeInventoryError("inventory metadata exceeds byte bound")
        try:
            data = importer._parse(self._raw)
            if _json(data) != self._raw:
                raise USCodeInventoryError("noncanonical inventory bytes")
            _validate(data, self.limits)
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
            if isinstance(exc, USCodeInventoryError):
                raise
            raise USCodeInventoryError("invalid source inventory") from exc
        object.__setattr__(self, "_sha256", _sha(self._raw))

    @property
    def sha256(self):
        return self._sha256

    def to_bytes(self):
        return self._raw

    def to_dict(self):
        return importer._parse(self._raw)

    def summary(self):
        data = self.to_dict()
        rows = [row for shard in data["shards"] for row in shard["rows"]]
        complete = all(shard["status"] == "verified" for shard in data["shards"])
        return {"schema_version": SCHEMA_VERSION, "inventory_sha256": self.sha256,
                "inventory_bytes": len(self._raw), "scope": SCOPE, "release_id": data["release"]["release_id"],
                "complete": complete, "declared_corpus_closure_verified": complete,
                "closure_verification_scope": "recorded build-time shard bytes; reopening verifies metadata integrity only",
                "current_all_shard_bytes_reverified": False,
                "declared_corpus_shards": len(data["shards"]), "declared_row_count": len(rows),
                "declared_compressed_bytes": sum(shard["artifact"]["bytes"] for shard in data["shards"]),
                "rows_scanned": sum(shard["rows_scanned"] for shard in data["shards"]),
                "eligible_input_count": sum(row["status"] == "ready_published_text" for row in rows),
                "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
                "original_status_counts": dict(sorted(Counter(row["original_status"] for row in rows).items())),
                "shard_status_counts": dict(sorted(Counter(shard["status"] for shard in data["shards"]).items())),
                "duplicate_entry_cid_count": len({row["entry_cid"] for row in rows if row["duplicate_entry_cid"]}),
                "grouping_metadata_complete": complete and all(row["metadata"] is not None
                    and row["metadata"]["canonical_identity"] is not None
                    and row["metadata"]["text_sha256"] is not None for row in rows),
                "source_text_storage": "unmaterialized_exact_published_text_utf8",
                "training_eligible": False, "source_authority_authenticated": False,
                "original_official_source_bytes_verified": False, "full_federal_corpus_complete": False,
                "global_holdout_verified": False, "admitted": False}

    def save(self, destination):
        result = importer._write_exclusive(Path(destination), self._raw)
        _fsync_directory(Path(destination).parent)
        return result


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _root(release, resolver):
    try:
        return importer.verify_uscode_release(release, resolver=resolver)
    except (ValueError, OSError, TypeError) as exc:
        raise USCodeInventoryError("pinned release root verification failed") from exc


def build_uscode_source_inventory(release, *, resolver, limits=InventoryLimits(), batch_size=64):
    if type(limits) is not InventoryLimits or type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise USCodeInventoryError("invalid inventory limits or batch size")
    release = _root(release, resolver)
    artifacts = sorted(release.corpus_shards, key=lambda item: item.relative_path)
    if (len(artifacts) > limits.max_corpus_shards or sum(item.row_count for item in artifacts) > limits.max_rows
            or sum(item.bytes for item in artifacts) > limits.max_declared_compressed_bytes):
        raise USCodeInventoryError("declared corpus exceeds inventory bounds")
    data = {"schema_version": SCHEMA_VERSION, "scope": SCOPE,
            "release": _release_metadata(release), "shards": []}
    accounted = len(_json(data))
    if accounted > limits.max_metadata_bytes:
        raise USCodeInventoryError("inventory metadata exceeds byte bound")
    for artifact in artifacts:
        try:
            path = importer._resolve_artifact(resolver, artifact.reference)
            # Distinguish absence from a present but corrupt immutable file.
            os.stat(path)
        except (ValueError, OSError, TypeError, KeyError):
            status = "unavailable"
        else:
            try:
                wrapped, verified_rows, wrapper_failures = importer._read_wrapped_shard_with_rows(
                    release, artifact.relative_path, resolver=resolver, batch_size=batch_size)
                rows = _shard_rows(release, wrapped, verified_rows, wrapper_failures,
                                   metadata_budget=limits.max_metadata_bytes - accounted)
                if not wrapped.complete or wrapped.rows_scanned != artifact.row_count:
                    raise USCodeInventoryError("full shard reader returned partial coverage")
                status = "verified"
            except USCodeInventoryError:
                raise
            except (ValueError, OSError, TypeError, KeyError, OverflowError):
                status = "corrupt"
            finally:
                # Do not retain a previous shard's text while reading the next.
                wrapped = verified_rows = wrapper_failures = None
        if status != "verified":
            rows = [{"row_index": i, "entry_cid": "", "legal_id": "",
                     "original_status": "shard_" + status, "status": "shard_" + status,
                     "duplicate_entry_cid": False, "wrapper_verified": False,
                     "metadata": None} for i in range(artifact.row_count)]
        shard = {"artifact": asdict(artifact), "status": status,
                 "rows_scanned": artifact.row_count if status == "verified" else 0, "rows": rows}
        accounted += len(_json(shard)) + 1
        if accounted > limits.max_metadata_bytes:
            raise USCodeInventoryError("inventory metadata exceeds byte bound")
        data["shards"].append(shard)
    entries = Counter(row["entry_cid"] for shard in data["shards"] for row in shard["rows"] if row["entry_cid"])
    for shard in data["shards"]:
        for row in shard["rows"]:
            if row["entry_cid"] and entries[row["entry_cid"]] > 1:
                row["duplicate_entry_cid"] = True
                row["status"] = "duplicate_entry_cid"
    # Recheck earlier successes after every shard has been processed. A drifted
    # success is an error, not an incomplete receipt carrying stale metadata.
    for shard in data["shards"]:
        if shard["status"] == "verified":
            ref = {name: shard["artifact"][name] for name in ("sha256", "bytes")}
            try:
                with importer._verified_file(importer._resolve_artifact(resolver, ref), ref,
                                             release.limits.max_shard_bytes):
                    pass
            except (ValueError, OSError, TypeError) as exc:
                raise USCodeInventoryError("successfully scanned shard changed before closure") from exc
    _root(release, resolver)
    return USCodeSourceInventory(_json(data), limits)


def load_uscode_source_inventory(path, *, expected_sha256, expected_size_bytes=None, limits=InventoryLimits()):
    _digest(expected_sha256)
    if type(limits) is not InventoryLimits:
        raise USCodeInventoryError("invalid inventory limits")
    try:
        size = os.stat(path, follow_symlinks=False).st_size if expected_size_bytes is None else expected_size_bytes
        _integer(size, "inventory bytes", 1, limits.max_metadata_bytes)
        with importer._verified_file(Path(path).absolute(), {"sha256": expected_sha256, "bytes": size},
                                     limits.max_metadata_bytes) as stream:
            raw = stream.read(size + 1)
    except (ValueError, OSError, TypeError) as exc:
        raise USCodeInventoryError("inventory artifact verification failed") from exc
    return USCodeSourceInventory(raw, limits)


@dataclass(frozen=True)
class MaterializedUSCodeInventoryInputs:
    inputs: tuple[EmbeddingInput, ...]
    extraction: importer.ExtractedUSCodeBatch
    _receipt_json: bytes = field(repr=False)
    _receipt_artifact_json: bytes = field(repr=False)

    @property
    def selection_receipt(self):
        return importer._parse(self._receipt_json)

    @property
    def selection_receipt_artifact(self):
        return importer._parse(self._receipt_artifact_json)


def materialize_uscode_inventory_inputs(inventory, entry_cids: Sequence[str], output_directory, *, release, resolver):
    if not isinstance(inventory, USCodeSourceInventory):
        raise USCodeInventoryError("verified source inventory required")
    inventory = USCodeSourceInventory(inventory.to_bytes(), inventory.limits)
    if not inventory.summary()["complete"]:
        raise USCodeInventoryError("materialization requires complete declared corpus closure")
    if (type(entry_cids) not in (list, tuple) or not 1 <= len(entry_cids) <= MAX_RECORDS
            or any(type(item) is not str for item in entry_cids) or len(set(entry_cids)) != len(entry_cids)):
        raise USCodeInventoryError("selection requires at most 256 unique entry identities")
    for item in entry_cids:
        _text(item, "selected entry CID")
    release = _root(release, resolver)
    data = inventory.to_dict()
    if _release_metadata(release) != data["release"] or [asdict(item) for item in sorted(
            release.corpus_shards, key=lambda item: item.relative_path)] != [item["artifact"] for item in data["shards"]]:
        raise USCodeInventoryError("inventory differs from exact release closure")
    indexed = {row["entry_cid"]: (shard["artifact"], row)
               for shard in data["shards"] for row in shard["rows"] if row["status"] == "ready_published_text"}
    if any(item not in indexed for item in entry_cids):
        raise USCodeInventoryError("selected entry is absent, duplicated or ineligible")
    selected_paths = sorted({indexed[item][0]["relative_path"] for item in entry_cids})
    selected_metadata = [indexed[item][1]["metadata"] for item in entry_cids]
    if (len(entry_cids) > min(release.limits.max_verified_rows, release.limits.max_extracted_rows)
            or len(selected_paths) > release.limits.max_verified_shards
            or sum(release.artifact(path).bytes for path in selected_paths) > release.limits.max_verified_shard_bytes
            or sum(meta["text_bytes"] for meta in selected_metadata) > min(MAX_BYTES, release.limits.max_extracted_bytes)
            or len({meta["text_sha256"] for meta in selected_metadata}) != len(entry_cids)
            or len({meta["input_id"] for meta in selected_metadata}) != len(entry_cids)):
        raise USCodeInventoryError("selected source closure duplicates selectors or exceeds materialization bounds")
    rows_by_entry = {}
    for relative in selected_paths:
        wrapped, verified_rows, _ = importer._read_wrapped_shard_with_rows(release, relative, resolver=resolver)
        selected_ordinals = {indexed[key][1]["row_index"] for key in entry_cids
                             if indexed[key][0]["relative_path"] == relative}
        actual_metadata = {row.row_index: _metadata(release, row) for row in verified_rows
                           if row.row_index in selected_ordinals}
        decoded = importer._decode_corpus_shard(release, wrapped)
        for row in decoded.records:
            if row.entry_cid not in entry_cids:
                continue
            artifact, expected = indexed[row.entry_cid]
            if (asdict(row.shard) != artifact or row.row_index != expected["row_index"]
                    or row.legal_id != expected["legal_id"] or actual_metadata.get(row.row_index) != expected["metadata"]):
                raise USCodeInventoryError("selected physical row differs from frozen inventory")
            rows_by_entry[row.entry_cid] = row
        wrapped = verified_rows = decoded = row = None
    if set(rows_by_entry) != set(entry_cids):
        raise USCodeInventoryError("selected entries no longer have exact eligible membership")
    rows = tuple(rows_by_entry[item] for item in entry_cids)
    inputs = tuple(_input(release, indexed[row.entry_cid][1]["metadata"]["canonical_identity"], row.text) for row in rows)
    if (len({item.input_id for item in inputs}) != len(inputs)
            or len({item.source.artifact.sha256 for item in inputs}) != len(inputs)
            or sum(item.source.artifact.bytes for item in inputs) > MAX_BYTES):
        raise USCodeInventoryError("selected producer inputs duplicate selectors or exceed byte bound")
    if [item.input_id for item in inputs] != [indexed[key][1]["metadata"]["input_id"] for key in entry_cids]:
        raise USCodeInventoryError("selected embedding input identity changed")
    extraction = importer.extract_uscode_rows(rows, output_directory, release=release, resolver=resolver)
    source_paths = {source.artifact.sha256: source.path for source in extraction.sources}
    try:
        inputs = validate_embedding_inputs(inputs, resolver=lambda ref: source_paths[ref["sha256"]])
    except (ValueError, KeyError, OSError) as exc:
        raise USCodeInventoryError("materialized embedding inputs failed exact source verification") from exc
    _root(release, resolver)
    receipt = {"schema_version": "autoencoder-uscode-inventory-selection-v1",
               "inventory": {"sha256": inventory.sha256, "bytes": len(inventory.to_bytes())},
               "release_manifest": release.manifest_reference, "release_id": release.release_id,
               "entry_cids": list(entry_cids), "input_ids": [item.input_id for item in inputs],
               "extraction_receipt": {name: extraction.receipt_artifact[name] for name in ("sha256", "bytes")},
               "selected_shards": [{"relative_path": path, **release.artifact(path).reference} for path in selected_paths],
               "selected_source_bytes_verified": True, "unselected_current_shards_reverified": False,
               "training_eligible": False, "admitted": False}
    raw = _json(receipt)
    descriptor = importer._write_exclusive(Path(output_directory) / "inventory-selection.json", raw)
    _fsync_directory(Path(output_directory))
    return MaterializedUSCodeInventoryInputs(inputs, extraction, raw, _json(descriptor))


__all__ = ["InventoryLimits", "USCodeInventoryError", "USCodeSourceInventory",
           "MaterializedUSCodeInventoryInputs", "build_uscode_source_inventory",
           "load_uscode_source_inventory", "materialize_uscode_inventory_inputs"]
