"""Bounded derived discovery over native source, semantic, model and corpus owners.

This projection has no source/model/proof head. It retains immutable associations
for planning discovery; association is not training lineage, inference evidence,
proof eligibility or admission. Native owners revalidate every returned record.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
import stat
from pathlib import Path
import sys

from .codebase_catalog import CodebaseCatalog, CodebaseHead, CodebaseHeadConflict
from .autoencoder_registry import AutoencoderRegistry, SCHEMA as MODEL_SCHEMA
from .contracts import content_identity
from ..logic.software_contracts.cache import ImmutableCAS
from ..logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ..logic.software_contracts.codebase_semantic_manifest import load_codebase_semantic_manifest
from ..logic.software_contracts.codebase_scan_policy_live import verify_policy_current
from ..logic.software_contracts.content import canonical_dag_json_bytes, cid_for_structured, validate_cid

SCHEMA = "intent-codebase-catalog@1"
RECORD_SCHEMA = "intent-codebase-discovery@1"
DOMAIN = "intent_codebase"
# The logical record schema is stable. Physical version 2 adds only selectors.
_BASE_DDL = (
    "CREATE SCHEMA intent_codebase",
    "CREATE TABLE intent_codebase.meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_id VARCHAR NOT NULL, storage_version INTEGER NOT NULL, ddl_cid VARCHAR NOT NULL, catalog_cid VARCHAR NOT NULL, roots_cid VARCHAR NOT NULL)",
    "CREATE TABLE intent_codebase.records (record_cid VARCHAR PRIMARY KEY, head_cid VARCHAR NOT NULL, manifest_cid VARCHAR NOT NULL)",
    "CREATE TABLE intent_codebase.operations (operation_id VARCHAR PRIMARY KEY, record_cid VARCHAR NOT NULL)",
)
_SELECTOR_DDL = (
    "CREATE TABLE intent_codebase.selectors (record_cid VARCHAR NOT NULL, head_cid VARCHAR NOT NULL, path VARCHAR NOT NULL, contract_cid VARCHAR NOT NULL, unit_cid VARCHAR NOT NULL, PRIMARY KEY(record_cid,path))",
    "CREATE INDEX intent_codebase_selector ON intent_codebase.selectors (head_cid,path,contract_cid)",
)
_AUTHORITY = dict(proof_authority=False, training_authority=False, inference_executed=False,
                  model_promotion_authority=False, admission_authority=False,
                  source_observed_live=False)


class IntentCodebaseCatalogError(ValueError):
    """Unknown, drifted, unavailable or unbounded native discovery data."""


@dataclass(frozen=True)
class IntentCodebaseCatalogLimits:
    max_records: int = 128
    max_operations: int = 256
    max_selectors: int = 32768
    max_results: int = 16
    max_record_bytes: int = 512 * 1024
    max_result_bytes: int = 8 * 1024 * 1024
    max_model_bytes: int = 16 * 1024 * 1024
    max_corpus_bytes: int = 16 * 1024 * 1024
    max_corpus_rows: int = 256

    def __post_init__(self):
        for name, field in self.__dataclass_fields__.items():
            value = getattr(self, name)
            _require(type(value) is int and 1 <= value <= field.default,
                     "invalid bounded discovery limit: " + name)


def _require(condition, message):
    if not condition:
        raise IntentCodebaseCatalogError(message)


def _token(value):
    _require(type(value) is str and 0 < len(value.encode()) <= 1024 and not any(ord(c) < 32 for c in value),
             "bounded text selector required")
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _cid(value):
    validate_cid(value, codecs={"dag-json"})
    return value


def _implementation():
    from . import autoencoder_registry, contracts, codebase_catalog
    from ..logic.software_contracts import codebase_semantic_manifest, codebase_scan_policy_live, content
    modules = (sys.modules[__name__], autoencoder_registry,
               contracts, codebase_catalog, codebase_semantic_manifest, codebase_scan_policy_live, content)
    result = {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in modules}
    # Pin the optional owner without importing its export/publisher dependency.
    result[__package__ + ".source_corpus_catalog"] = hashlib.sha256(Path(__file__).with_name("source_corpus_catalog.py").read_bytes()).hexdigest()
    return result


class IntentCodebaseCatalog:
    """One derived SQL domain on the existing structural owner's transaction.

    Native model/corpus owners remain separate, exclusive owners. Their roots
    are fixed when this domain is initialized; records reference immutable
    versions, never their mutable heads. Missing configured owners refuse replay.
    Version 1 is a supported record-only format; migrate(1) adds version 2's
    selectors transactionally after bounded native reconstruction of its rows.
    """
    def __init__(self, index, *, model_registry=None, corpus_catalog=None,
                 limits=IntentCodebaseCatalogLimits(), create_storage_version=2):
        _require(type(index) is RepositoryCodebaseIndex and type(index.catalog) is CodebaseCatalog
                 and type(index.artifacts) is ImmutableCAS and index.catalog.artifacts is index.artifacts
                 and index.ingestor.store is index.catalog.store, "exact native source/AST/CAS owner required")
        _require(model_registry is None or type(model_registry) is AutoencoderRegistry, "native model owner required")
        self._corpus_schema = None
        if corpus_catalog is not None:
            from .source_corpus_catalog import SourceCorpusCatalog, SCHEMA as CORPUS_SCHEMA
            _require(type(corpus_catalog) is SourceCorpusCatalog, "native corpus owner required")
            self._corpus_schema = CORPUS_SCHEMA
        _require(type(limits) is IntentCodebaseCatalogLimits, "native discovery limits required")
        _require(type(create_storage_version) is int and create_storage_version in (1, 2), "unknown storage version")
        self.index, self.catalog, self.store = index, index.catalog, index.catalog.store
        self.artifacts, self._cx = index.artifacts, index.catalog.store._connection
        self.model_registry, self.corpus_catalog, self.limits = model_registry, corpus_catalog, limits
        self._model_owner, self._corpus_owner = model_registry, corpus_catalog
        self._pid = os.getpid()
        self._roots = self._owner_roots()
        self._root_signatures = self._signatures()
        with self.store._lock, self.store._transaction():
            self._ensure_owner()
            found = self._cx.execute("SELECT schema_name FROM information_schema.schemata WHERE catalog_name=current_database() AND schema_name=?", [DOMAIN]).fetchall()
            if not found:
                for statement in self._ddl(create_storage_version):
                    self._cx.execute(statement)
                self._cx.execute("INSERT INTO intent_codebase.meta VALUES (1,?,?,?,?,?)",
                    [SCHEMA, create_storage_version, cid_for_structured(self._ddl(create_storage_version)),
                     self._catalog_identity(), cid_for_structured(self._roots)])
            self._check_schema()
            self._counts()

    @staticmethod
    def _ddl(version):
        return list(_BASE_DDL + (_SELECTOR_DDL if version == 2 else ()))

    def _owner_roots(self):
        result = {"source_database": str(self.catalog._database_path),
                  "source_artifacts": str(self.artifacts.root.resolve()),
                  "model": None, "corpus": None}
        if self.model_registry is not None:
            self.model_registry._ensure_owner()
            result["model"] = dict(schema=MODEL_SCHEMA, database=str(self.model_registry.database_path),
                                   artifacts=str(self.model_registry.artifact_root))
        if self.corpus_catalog is not None:
            self.corpus_catalog._ensure_owner()
            result["corpus"] = dict(schema=self._corpus_schema, database=str(self.corpus_catalog.database_path),
                                    artifacts=str(self.corpus_catalog.package_root))
        return result

    def _signatures(self):
        paths = [self._roots["source_database"], self._roots["source_artifacts"]]
        for key in ("model", "corpus"):
            if self._roots[key] is not None:
                paths += [self._roots[key]["database"], self._roots[key]["artifacts"]]
        return [(Path(p).stat().st_dev, Path(p).stat().st_ino) for p in paths]

    def _ensure_owner(self):
        _require(os.getpid() == self._pid and self.index.catalog is self.catalog
            and self.index.artifacts is self.artifacts and self.index.ingestor.store is self.store
            and self.store._connection is self._cx and self.model_registry is self._model_owner
            and self.corpus_catalog is self._corpus_owner, "discovery owner/process changed")
        self.catalog._ensure_owner()
        _require(self._owner_roots() == self._roots and self._signatures() == self._root_signatures,
                 "cross-domain owner roots changed")

    def _catalog_identity(self):
        for function, name, maximum in (("duckdb_tables", "table_name", 5), ("duckdb_indexes", "index_name", 2)):
            sizes = self._cx.execute(f"SELECT octet_length(encode({name}))+octet_length(encode(sql)) FROM {function}() WHERE database_name=current_database() AND schema_name=? LIMIT ?", [DOMAIN, maximum]).fetchall()
            _require(all(type(row[0]) is int and 0 < row[0] <= 65536 for row in sizes), "discovery DDL definition exceeds byte bound")
        tables = self._cx.execute("SELECT table_name,sql FROM duckdb_tables() WHERE database_name=current_database() AND schema_name=? ORDER BY table_name LIMIT 5", [DOMAIN]).fetchall()
        indexes = self._cx.execute("SELECT index_name,sql FROM duckdb_indexes() WHERE database_name=current_database() AND schema_name=? ORDER BY index_name LIMIT 2", [DOMAIN]).fetchall()
        return cid_for_structured({"tables": [list(v) for v in tables], "indexes": [list(v) for v in indexes]})

    def _check_schema(self):
        sizes = self._cx.execute("SELECT octet_length(encode(schema_id))+octet_length(encode(ddl_cid))+octet_length(encode(catalog_cid))+octet_length(encode(roots_cid)) FROM intent_codebase.meta LIMIT 2").fetchall()
        _require(len(sizes) == 1 and sizes[0][0] is not None and sizes[0][0] <= 4096, "discovery metadata exceeds bound")
        row = self._cx.execute("SELECT singleton,schema_id,storage_version,ddl_cid,catalog_cid,roots_cid FROM intent_codebase.meta LIMIT 2").fetchall()
        _require(len(row) == 1 and type(row[0][2]) is int and row[0][2] in (1, 2), "unknown discovery migration version")
        version = row[0][2]
        _require(row == [(1, SCHEMA, version, cid_for_structured(self._ddl(version)), self._catalog_identity(), cid_for_structured(self._roots))],
                 "discovery schema or native root binding drifted")
        tables = self._cx.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema=? LIMIT 5", [DOMAIN]).fetchall()
        expected = {"meta", "records", "operations"} | ({"selectors"} if version == 2 else set())
        _require(set(tables) == {(v, "BASE TABLE") for v in expected}, "discovery schema contains foreign tables")
        columns = {"meta": [("singleton", "INTEGER"), ("schema_id", "VARCHAR"), ("storage_version", "INTEGER"), ("ddl_cid", "VARCHAR"), ("catalog_cid", "VARCHAR"), ("roots_cid", "VARCHAR")],
                   "records": [(n, "VARCHAR") for n in ("record_cid", "head_cid", "manifest_cid")],
                   "operations": [(n, "VARCHAR") for n in ("operation_id", "record_cid")]}
        if version == 2:
            columns["selectors"] = [(n, "VARCHAR") for n in ("record_cid", "head_cid", "path", "contract_cid", "unit_cid")]
        actual = self._cx.execute("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_catalog=current_database() AND table_schema=? ORDER BY table_name,ordinal_position LIMIT 17", [DOMAIN]).fetchall()
        _require(actual == [(table, name, kind, "NO", None) for table, fields in sorted(columns.items()) for name, kind in fields], "discovery columns differ")
        actual = self._cx.execute("SELECT table_name,constraint_type,constraint_column_names,expression FROM duckdb_constraints() WHERE database_name=current_database() AND schema_name=? LIMIT 23", [DOMAIN]).fetchall()
        expected_constraints = [(table, "NOT NULL", (name,), None) for table, fields in columns.items() for name, _ in fields]
        expected_constraints += [(table, "PRIMARY KEY", (("record_cid", "path") if table == "selectors" else (fields[0][0],)), None) for table, fields in columns.items()]
        expected_constraints += [("meta", "CHECK", ("singleton",), "(singleton = 1)")]
        _require(len(actual) == len(expected_constraints) and {(a,b,tuple(c),d) for a,b,c,d in actual} == set(expected_constraints), "discovery constraints differ")
        indexes = self._cx.execute("SELECT index_name,is_unique,is_primary FROM duckdb_indexes() WHERE database_name=current_database() AND schema_name=? LIMIT 2", [DOMAIN]).fetchall()
        _require(indexes == ([("intent_codebase_selector", False, False)] if version == 2 else []), "discovery query indexes differ")
        return version

    def _counts(self):
        version = self._check_schema()
        def bounded_count(table, maximum):
            return self._cx.execute(f"SELECT count(*) FROM (SELECT 1 FROM intent_codebase.{table} LIMIT ?)", [maximum + 1]).fetchone()[0]
        records = bounded_count("records", self.limits.max_records)
        operations = bounded_count("operations", self.limits.max_operations)
        selectors = bounded_count("selectors", self.limits.max_selectors) if version == 2 else 0
        _require(records <= self.limits.max_records and operations <= self.limits.max_operations
                 and selectors <= self.limits.max_selectors, "discovery capacity exceeded")
        return records, operations, selectors

    def _bounded(self, cid):
        _cid(cid)
        descriptor = os.open(self.artifacts.path_for(cid), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_size <= self.limits.max_record_bytes, "discovery artifact exceeds byte bound or is not regular")
            raw = stream.read(self.limits.max_record_bytes + 1)
        _require(len(raw) <= self.limits.max_record_bytes, "discovery artifact exceeds byte bound")
        value = json.loads(raw)
        _require(canonical_dag_json_bytes(value) == raw and cid_for_structured(value) == cid,
                 "discovery immutable artifact changed")
        return value

    def _verify_model_artifact(self, owner, artifact):
        # Native artifact_path validates the descriptor. This bounded read avoids
        # the older owner's unbounded-to-EOF hashing loop; storage stays native.
        path = owner.artifact_path(artifact)
        root_fd = os.open(owner.artifact_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        shard_fd = file_fd = None
        try:
            shard_fd = os.open(path.parent.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=shard_fd)
            before = os.fstat(file_fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_size == artifact["bytes"]
                     and before.st_size <= self.limits.max_model_bytes, "native model artifact byte bound or file type differs")
            digest, count = hashlib.sha256(), 0
            while True:
                raw = os.read(file_fd, min(1024 * 1024, artifact["bytes"] + 1 - count))
                if not raw:
                    break
                count += len(raw)
                _require(count <= artifact["bytes"], "native model artifact grew beyond bound")
                digest.update(raw)
            signature = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
            _require(signature(before) == signature(os.fstat(file_fd))
                     == signature(os.stat(path.name, dir_fd=shard_fd, follow_symlinks=False))
                     and digest.hexdigest() == artifact["sha256"] and count == artifact["bytes"],
                     "native model artifact bytes or identity changed")
        finally:
            if file_fd is not None: os.close(file_fd)
            if shard_fd is not None: os.close(shard_fd)
            os.close(root_fd)

    def _model(self, version_id):
        if version_id is None:
            return None
        _token(version_id)
        owner = self.model_registry
        _require(owner is not None, "model reference requires the configured native owner")
        with owner._lock:
            with owner._transaction() as cx:
                sizes = cx.execute("SELECT octet_length(encode(v.version_id))+octet_length(encode(v.variant_id))+coalesce(octet_length(encode(v.parent_version_id)),0)+octet_length(encode(v.artifact))+octet_length(encode(v.metadata))+octet_length(encode(a.manifest)) FROM autoencoder_control.versions v JOIN autoencoder_control.variants a ON a.variant_id=v.variant_id WHERE v.version_id=? LIMIT 2", [version_id]).fetchall()
                _require(len(sizes) == 1 and sizes[0][0] <= 65536, "unknown or unbounded native model version")
            version = owner.get_version(version_id)
            variant = owner.get_variant(version["variant_id"])
            expected = content_identity(dict(schema=MODEL_SCHEMA, **{k: version[k] for k in ("variant_id", "artifact", "metadata", "parent_version_id")}))
            _require(expected == version_id, "native model version identity changed")
            _require(version["artifact"]["bytes"] <= self.limits.max_model_bytes, "native model artifact exceeds profile bound")
            self._verify_model_artifact(owner, version["artifact"])
            _require(owner.get_version(version_id) == version and owner.get_variant(version["variant_id"]) == variant,
                     "native model version changed during validation")
        return dict(version_id=version_id, native_version_json=_json(version), native_variant_json=_json(variant),
                    artifact=version["artifact"], owner=self._roots["model"], artifact_verified=True,
                    inference_executed=False)

    def _corpus(self, version_id):
        if version_id is None:
            return None
        _token(version_id)
        owner = self.corpus_catalog
        _require(owner is not None, "corpus reference requires the configured native owner")
        _require(owner.limits.max_package_bytes <= self.limits.max_corpus_bytes
                 and owner.limits.max_total_rows <= self.limits.max_corpus_rows, "native corpus owner limits exceed discovery verification profile")
        with owner._lock:
            with owner._transaction() as cx:
                rows = cx.execute("SELECT octet_length(encode(v.dataset_id))+octet_length(encode(v.release_id))+octet_length(encode(r.package_directory))+octet_length(encode(v.metadata))+octet_length(encode(d.binding))+octet_length(encode(r.manifest)),r.package_bytes,r.row_count FROM source_corpus.versions v JOIN source_corpus.datasets d ON d.dataset_id=v.dataset_id JOIN source_corpus.releases r ON r.release_id=v.release_id WHERE v.version_id=? LIMIT 2", [version_id]).fetchall()
                _require(len(rows) == 1 and all(type(v) is int and v >= 0 for v in rows[0])
                         and rows[0][0] <= 65536 and rows[0][1] <= self.limits.max_corpus_bytes
                         and rows[0][2] <= self.limits.max_corpus_rows, "unknown or unbounded native corpus version")
            version = owner.get_version(version_id)
            verified = owner.verify_version(version_id)
            _require(owner.get_version(version_id) == version, "native corpus changed during validation")
        return dict(version_id=version_id, native_version_json=_json(version), verification=verified,
                    owner=self._roots["corpus"], training_executed=False)

    def _derive(self, manifest_cid, model_version_id, corpus_version_id):
        _cid(manifest_cid)
        manifest = load_codebase_semantic_manifest(self.index, manifest_cid)
        units = [{key: row[key] for key in ("path", "logical_unit_id", "version_cid", "model_status", "declared_contract_cid")}
                 for row in manifest["units"]]
        value = dict(schema=RECORD_SCHEMA, producer=_implementation(), roots=self._roots,
            source_head=manifest["source_head"], semantic_manifest_cid=manifest_cid,
            policy_receipt_cid=manifest["policy_receipt_cid"], units=units,
            model=self._model(model_version_id), corpus=self._corpus(corpus_version_id),
            association_semantics="declared_context_not_training_or_inference_provenance", authority=dict(_AUTHORITY))
        _require(len(canonical_dag_json_bytes(value)) <= self.limits.max_record_bytes, "discovery record exceeds byte bound")
        self._ensure_owner()
        return value

    @staticmethod
    def _selectors(cid, value):
        head = cid_for_structured(value["source_head"])
        return [(cid, head, row["path"], row["declared_contract_cid"] or "", row["version_cid"]) for row in value["units"]]

    def _stored(self, cid):
        _cid(cid)
        sizes = self._cx.execute("SELECT octet_length(encode(record_cid))+octet_length(encode(head_cid))+octet_length(encode(manifest_cid)) FROM intent_codebase.records WHERE record_cid=? LIMIT 2", [cid]).fetchall()
        _require(len(sizes) == 1 and sizes[0][0] <= 4096, "unknown or unbounded discovery record")
        row = self._cx.execute("SELECT record_cid,head_cid,manifest_cid FROM intent_codebase.records WHERE record_cid=? LIMIT 2", [cid]).fetchall()
        value = self._bounded(cid)
        _require(type(value) is dict and value.get("schema") == RECORD_SCHEMA and value.get("roots") == self._roots,
                 "discovery record root or type differs")
        model_id = None if value.get("model") is None else value["model"]["version_id"]
        corpus_id = None if value.get("corpus") is None else value["corpus"]["version_id"]
        rebuilt = self._derive(value["semantic_manifest_cid"], model_id, corpus_id)
        _require(canonical_dag_json_bytes(value) == canonical_dag_json_bytes(rebuilt), "discovery references do not reconstruct")
        _require(row == [(cid, cid_for_structured(value["source_head"]), value["semantic_manifest_cid"])], "SQL discovery record differs from immutable body")
        if self._check_schema() == 2:
            sizes = self._cx.execute("SELECT octet_length(encode(record_cid))+octet_length(encode(head_cid))+octet_length(encode(path))+octet_length(encode(contract_cid))+octet_length(encode(unit_cid)) FROM intent_codebase.selectors WHERE record_cid=? LIMIT 257", [cid]).fetchall()
            _require(len(sizes) <= 256 and all(v[0] <= 8192 for v in sizes), "SQL selectors exceed bounds")
            selected = self._cx.execute("SELECT record_cid,head_cid,path,contract_cid,unit_cid FROM intent_codebase.selectors WHERE record_cid=? ORDER BY path LIMIT 257", [cid]).fetchall()
            _require(selected == sorted(self._selectors(cid, value), key=lambda v: v[2]), "SQL selectors differ from native manifest")
        operations = self._cx.execute("SELECT count(*) FROM intent_codebase.operations WHERE record_cid=?", [cid]).fetchone()[0]
        _require(1 <= operations <= self.limits.max_operations, "discovery record lacks bounded operation provenance")
        return value

    def _audit_selectors(self):
        """Check bounded projection membership before returning even an empty match."""
        sizes = self._cx.execute("SELECT octet_length(encode(record_cid))+octet_length(encode(head_cid))+octet_length(encode(manifest_cid)) FROM intent_codebase.records LIMIT ?", [self.limits.max_records + 1]).fetchall()
        _require(len(sizes) <= self.limits.max_records and all(v[0] <= 4096 for v in sizes), "discovery record inventory exceeds bounds")
        rows = self._cx.execute("SELECT record_cid,head_cid,manifest_cid FROM intent_codebase.records ORDER BY record_cid LIMIT ?", [self.limits.max_records + 1]).fetchall()
        total = 0
        for cid, head, manifest in rows:
            value = self._bounded(cid)
            _require(value.get("schema") == RECORD_SCHEMA and value.get("roots") == self._roots
                     and value.get("producer") == _implementation()
                     and value.get("authority") == _AUTHORITY
                     and cid_for_structured(value["source_head"]) == head
                     and value["semantic_manifest_cid"] == manifest
                     and type(value["units"]) is list and len(value["units"]) <= 256,
                     "discovery membership record differs")
            expected = sorted(self._selectors(cid, value), key=lambda v: v[2])
            sizes = self._cx.execute("SELECT octet_length(encode(record_cid))+octet_length(encode(head_cid))+octet_length(encode(path))+octet_length(encode(contract_cid))+octet_length(encode(unit_cid)) FROM intent_codebase.selectors WHERE record_cid=? LIMIT 257", [cid]).fetchall()
            _require(len(sizes) <= 256 and all(v[0] <= 8192 for v in sizes), "selector inventory exceeds bounds")
            actual = self._cx.execute("SELECT record_cid,head_cid,path,contract_cid,unit_cid FROM intent_codebase.selectors WHERE record_cid=? ORDER BY path LIMIT 257", [cid]).fetchall()
            _require(actual == expected, "SQL selector membership differs from immutable record")
            total += len(expected)
        _require(total == self._cx.execute("SELECT count(*) FROM intent_codebase.selectors").fetchone()[0], "orphan selector rows")
        missing = self._cx.execute("SELECT count(*) FROM intent_codebase.operations o LEFT JOIN intent_codebase.records r ON o.record_cid=r.record_cid WHERE r.record_cid IS NULL").fetchone()[0]
        unowned = self._cx.execute("SELECT count(*) FROM intent_codebase.records r WHERE NOT EXISTS (SELECT 1 FROM intent_codebase.operations o WHERE o.record_cid=r.record_cid)").fetchone()[0]
        _require(missing == unowned == 0, "discovery operation membership differs")

    @property
    def storage_version(self):
        """Inspect the durable migration fence without starting a migration."""
        with self.store._lock:
            self._ensure_owner()
            return self._check_schema()

    def get(self, record_cid):
        """Historical native replay; explicitly no live source observation."""
        with self.store._lock:
            self._ensure_owner()
            self._counts()
            value = self._stored(record_cid)
            self._ensure_owner()
            return value

    def _fence(self, head, *, write=False):
        _require(type(head) is CodebaseHead, "complete native expected head required")
        self._ensure_owner()
        if self.catalog._current(head.repository_id) != head:
            raise CodebaseHeadConflict("discovery source head changed")
        if write:
            # Reuse the native evidence owner's real-write/restore protocol.
            # DuckDB elides no-op updates. These adjacent statements retain a
            # physical write until commit; no callbacks/reads occur between them.
            # Other connections see the original complete committed head.
            self._cx.execute("UPDATE codebase_control.heads SET generation=-generation WHERE repository_id=?", [head.repository_id])
            self._cx.execute("UPDATE codebase_control.heads SET generation=? WHERE repository_id=?", [head.generation, head.repository_id])
            _require(self.catalog._current(head.repository_id) == head, "source fence failed to restore the exact head")

    @contextmanager
    def _current(self, repository, head, receipt_cid, resources):
        self._ensure_owner()
        verify_policy_current(self.index, repository, expected_head=head, receipt_cid=receipt_cid, **resources)
        yield
        verify_policy_current(self.index, repository, expected_head=head, receipt_cid=receipt_cid, **resources)
        self._ensure_owner()

    def publish(self, repository, *, expected_head, manifest_cid, operation_id,
                model_version_id=None, corpus_version_id=None, **resources):
        _token(operation_id)
        value = self._derive(manifest_cid, model_version_id, corpus_version_id)
        with self._current(repository, expected_head, value["policy_receipt_cid"], resources):
            _require(value["source_head"] == expected_head.to_dict(), "semantic manifest belongs to another complete source head")
            cid = self.artifacts.put(value)
            rows = self._selectors(cid, value)
            with self.store._lock, self.store._transaction():
                self._fence(expected_head, write=True)
                counts = self._counts()
                prior = self._cx.execute("SELECT record_cid FROM intent_codebase.operations WHERE operation_id=? LIMIT 2", [operation_id]).fetchall()
                _require(not prior or prior == [(cid,)], "operation ID belongs to another discovery request")
                known = self._cx.execute("SELECT 1 FROM intent_codebase.records WHERE record_cid=?", [cid]).fetchone()
                if not prior:
                    _require(counts[1] < self.limits.max_operations, "discovery operation capacity reached")
                    if not known:
                        _require(counts[0] < self.limits.max_records and counts[2] + len(rows) <= self.limits.max_selectors,
                                 "discovery record or selector capacity reached")
                        self._cx.execute("INSERT INTO intent_codebase.records VALUES (?,?,?)", [cid, cid_for_structured(value["source_head"]), manifest_cid])
                        if self._check_schema() == 2 and rows:
                            self._cx.executemany("INSERT INTO intent_codebase.selectors VALUES (?,?,?,?,?)", rows)
                    self._cx.execute("INSERT INTO intent_codebase.operations VALUES (?,?)", [operation_id, cid])
            # Independent reconstruction catches reference corruption during SQL publication.
            _require(self.get(cid) == value, "discovery changed after publication")
        return dict(record_cid=cid, source_head=expected_head.to_dict(), source_observed_live=True,
                    proof_authority=False, training_authority=False)

    def lookup(self, repository, *, expected_head, policy_receipt_cid, path, contract_cid=None, limit=16, **resources):
        _token(path)
        if contract_cid is not None:
            _cid(contract_cid)
        _require(type(limit) is int and 1 <= limit <= self.limits.max_results, "invalid lookup result bound")
        with self._current(repository, expected_head, policy_receipt_cid, resources), self.store._lock:
            self._fence(expected_head)
            self._counts()
            _require(self._check_schema() == 2, "selector queries require explicit storage migration")
            self._audit_selectors()
            selector = "head_cid=? AND path=?" + (" AND contract_cid=?" if contract_cid is not None else "")
            args = [cid_for_structured(expected_head.to_dict()), path] + ([] if contract_cid is None else [contract_cid])
            sizes = self._cx.execute("SELECT octet_length(encode(record_cid)) FROM intent_codebase.selectors WHERE " + selector + " ORDER BY record_cid LIMIT ?", [*args, limit + 1]).fetchall()
            _require(len(sizes) <= limit and all(v[0] <= 256 for v in sizes), "lookup exceeds result bound")
            rows = self._cx.execute("SELECT record_cid FROM intent_codebase.selectors WHERE " + selector + " ORDER BY record_cid LIMIT ?", [*args, limit + 1]).fetchall()
            values, size = [], 0
            for (cid,) in rows:
                value = self._stored(cid)
                _require(value["source_head"] == expected_head.to_dict() and any(v["path"] == path
                    and (contract_cid is None or v["declared_contract_cid"] == contract_cid) for v in value["units"]),
                    "selector match does not reconstruct")
                size += len(canonical_dag_json_bytes(value))
                _require(size <= self.limits.max_result_bytes, "aggregate discovery result exceeds byte bound")
                values.append(dict(record_cid=cid, record=value))
            self._fence(expected_head)
        return dict(records=values, source_head=expected_head.to_dict(), source_observed_live=True,
                    selection_complete=True, proof_authority=False, training_authority=False)

    def migrate(self, expected_storage_version=1):
        """Explicit atomic v1→v2 backfill; semantic records and owners unchanged."""
        _require(type(expected_storage_version) is int and expected_storage_version == 1, "only the declared v1 to v2 migration is supported")
        with self.store._lock:
            self._ensure_owner()
            _require(self._check_schema() == 1, "migration version fence differs")
            self._counts()
            sizes = self._cx.execute("SELECT octet_length(encode(record_cid)) FROM intent_codebase.records LIMIT ?", [self.limits.max_records + 1]).fetchall()
            _require(len(sizes) <= self.limits.max_records and all(v[0] <= 256 for v in sizes), "migration records exceed bounds")
            ids = [row[0] for row in self._cx.execute("SELECT record_cid FROM intent_codebase.records ORDER BY record_cid LIMIT ?", [self.limits.max_records + 1]).fetchall()]
            selectors = []
            for cid in ids:
                selectors.extend(self._selectors(cid, self._stored(cid)))
                _require(len(selectors) <= self.limits.max_selectors, "migration selectors exceed capacity")
            with self.store._transaction():
                _require(self._check_schema() == 1, "migration version fence differs")
                again = [row[0] for row in self._cx.execute("SELECT record_cid FROM intent_codebase.records ORDER BY record_cid LIMIT ?", [self.limits.max_records + 1]).fetchall()]
                _require(again == ids, "migration record population changed")
                for statement in _SELECTOR_DDL:
                    self._cx.execute(statement)
                if selectors:
                    self._cx.executemany("INSERT INTO intent_codebase.selectors VALUES (?,?,?,?,?)", selectors)
                self._cx.execute("UPDATE intent_codebase.meta SET storage_version=2,ddl_cid=?,catalog_cid=? WHERE singleton=1",
                                 [cid_for_structured(self._ddl(2)), self._catalog_identity()])
                self._counts()
                self._audit_selectors()
                self._ensure_owner()
        return dict(schema=SCHEMA, previous_storage_version=1, storage_version=2,
                    records_preserved=len(ids), selectors_derived=len(selectors), proof_authority=False)
