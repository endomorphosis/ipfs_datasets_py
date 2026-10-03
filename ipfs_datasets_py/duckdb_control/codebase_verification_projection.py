"""Private, rebuildable normalized queries under the verification catalog owner.

The existing catalog/CAS artifacts remain the evidence authority. This derived
schema has no independent connection, resource owner, source observation or
proof acceptance. A bounded complete inventory check precedes SQL selection,
including rows whose corruption could otherwise hide a match.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from ipfs_datasets_py.logic.common.canonical_cache_key import CanonicalProofCacheKey, REQUIRED_IDENTITY_FIELDS
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_structured, validate_cid

SCHEMA = "codebase-verification-query-storage@1"
INVENTORY_SCHEMA = "codebase-verification-query-inventory@1"
DOMAIN = "codebase_verification_query"
_CID_KINDS = frozenset({"snapshot", "manifest", "head", "verification", "applicability", "authored_contract",
    "lowered_contract", "domain", "profile", "environment", "compiler"})
DEPENDENCY_KINDS = frozenset({"source", "ast", "ast_revision", "implementation", "canonical_key", *_CID_KINDS,
    *("canonical_" + field for field in REQUIRED_IDENTITY_FIELDS)})
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_KEY = re.compile(r"canonical-proof-cache-key:sha256:[0-9a-f]{64}\Z")
_SQL_ROW_BYTES = 64 * 1024
_FIELDS = {
    "meta": (("singleton", "INTEGER"), ("schema_id", "VARCHAR"), ("schema_cid", "VARCHAR"), ("catalog_cid", "VARCHAR"), ("artifact_root", "VARCHAR")),
    "inventories": (("head_cid", "VARCHAR"), ("repository_id", "VARCHAR"), ("epoch", "BIGINT"), ("inventory_cid", "VARCHAR")),
    "epochs": (("singleton", "INTEGER"), ("next_epoch", "BIGINT")),
    "entries": tuple((name, "VARCHAR") for name in ("entry_id", "head_cid", "projection_cid", "path", "contract_id", "contract_cid", "domain_id", "domain_cid", "verification_cid")),
    "keys": tuple((name, "VARCHAR") for name in ("entry_id", "key_id", "phase", "kind", "obligation_id", "key_json")),
    "dependencies": tuple((name, "VARCHAR") for name in ("entry_id", "kind", "value")),
}
_PRIMARY = {"meta": ("singleton",), "epochs": ("singleton",), "inventories": ("head_cid",), "entries": ("entry_id",),
            "keys": ("entry_id", "key_id", "phase", "kind", "obligation_id"), "dependencies": ("entry_id", "kind", "value")}
_DDL = [f"CREATE SCHEMA {DOMAIN}"]
for _table, _columns in _FIELDS.items():
    _parts = [f"{name} {kind} NOT NULL" for name, kind in _columns]
    _parts += ["PRIMARY KEY (" + ", ".join(_PRIMARY[_table]) + ")"]
    if _table in {"meta", "epochs"}:
        _parts += ["CHECK(singleton=1)"]
    if _table == "epochs":
        _parts += ["CHECK(next_epoch>0)"]
    _DDL.append(f"CREATE TABLE {DOMAIN}.{_table} (" + ", ".join(_parts) + ")")


def _error(message):
    from .codebase_verification_catalog import CodebaseVerificationCatalogError
    return CodebaseVerificationCatalogError(message)


def _text(value, *, maximum=1024):
    if type(value) is not str or not value or len(value) > maximum or len(value.encode()) > maximum or any(ord(c) < 32 for c in value):
        raise _error("invalid bounded normalized query text")
    return value


def validate_dependency(kind: str, value: str) -> None:
    if type(kind) is not str or kind not in DEPENDENCY_KINDS:
        raise _error("unsupported normalized dependency kind")
    _text(value)
    if kind == "canonical_key":
        if not _KEY.fullmatch(value):
            raise _error("invalid complete canonical key identity")
    elif kind == "implementation" or (kind.startswith("canonical_") and kind[10:] not in {
            "provider", "checker", "evidence_kind", "authority_ceiling"}):
        if not _SHA.fullmatch(value):
            raise _error("dependency requires an exact SHA-256 identity")
    elif kind in _CID_KINDS or kind in {"source", "ast"}:
        codecs = {"raw"} if kind == "source" else {"dag-json", "raw"} if kind == "ast" else {"dag-json"}
        try:
            validate_cid(value, codecs=codecs)
        except (TypeError, ValueError) as exc:
            raise _error("invalid dependency content identity") from exc


def contract_dependencies(value: dict[str, Any], contract: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Derive the exact shared and contract-local dependency identities."""
    common = value["dependencies"]
    dependencies: set[tuple[str, str]] = set()

    def dep(kind, item):
        if item is not None:
            validate_dependency(kind, item)
            dependencies.add((kind, item))

    for kind, field in (("source", "source_cid"), ("snapshot", "snapshot_cid"), ("manifest", "manifest_cid"),
                        ("ast", "ast_cid"), ("ast_revision", "ast_revision_id"), ("head", "head_cid"), ("compiler", "pipeline_cid")):
        dep(kind, common[field])
    dep("verification", value["verification_cid"])
    dep("applicability", value["applicability_cid"])
    dep("authored_contract", contract["contract_cid"])
    dep("lowered_contract", contract["lowered_contract_cid"])
    dep("domain", contract["domain_cid"])
    for phase in ("", "applicability_"):
        if phase + "environment" in common:
            environment = common[phase + "environment"]
            dep("environment", cid_for_structured(environment))
            for pin in environment["module_pins"]:
                dep("implementation", "sha256:" + pin["sha256"])
        if phase + "profile" in common:
            dep("profile", cid_for_structured(common[phase + "profile"]))
    for field in ("canonical_keys", "applicability_keys"):
        for item in contract[field]:
            native = CanonicalProofCacheKey.from_dict(item["key"])
            body = native.to_dict()
            if native.key_id != item["key_id"] or canonical_dag_json_bytes(body) != canonical_dag_json_bytes(item["key"]):
                raise _error("normalized key does not recompute")
            dep("canonical_key", native.key_id)
            for dimension in REQUIRED_IDENTITY_FIELDS:
                dep("canonical_" + dimension, body[dimension])
    return tuple(sorted(dependencies))


@dataclass(frozen=True, slots=True)
class EvidenceInventory:
    head_cid: str
    inventory_cid: str
    epoch: int
    projection_cids: tuple[str, ...]

    def to_dict(self):
        return {"head_cid": self.head_cid, "inventory_cid": self.inventory_cid,
                "epoch": self.epoch, "projection_cids": list(self.projection_cids)}


class VerificationProjectionStore:
    """Private helper; all methods run inside the caller's lock/transaction."""

    def __init__(self, catalog):
        self.catalog, self.cx, self.artifacts = catalog, catalog._cx, catalog.artifacts
        self.limits = catalog.limits
        self.catalog._ensure_owner()
        found = self.cx.execute("SELECT schema_name FROM information_schema.schemata WHERE catalog_name=current_database() AND schema_name=?", [DOMAIN]).fetchall()
        if not found:
            for statement in _DDL:
                self.cx.execute(statement)
            self.cx.execute(f"INSERT INTO {DOMAIN}.meta VALUES (1, ?, ?, ?, ?)",
                [SCHEMA, cid_for_structured(_DDL), self._identity(), str(self.artifacts.root.resolve())])
            self.cx.execute(f"INSERT INTO {DOMAIN}.epochs VALUES (1, 1)")
        self.check_schema()
        self._counts()

    def _identity(self):
        rows = self.cx.execute("SELECT table_name, sql FROM duckdb_tables() WHERE database_name=current_database() AND schema_name=? ORDER BY table_name LIMIT 7", [DOMAIN]).fetchall()
        return cid_for_structured([list(row) for row in rows])

    def check_schema(self):
        self.catalog._ensure_owner()
        tables = self.cx.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema=? LIMIT 7", [DOMAIN]).fetchall()
        if set(tables) != {(name, "BASE TABLE") for name in _FIELDS}:
            raise _error("normalized query schema drift")
        columns = self.cx.execute("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_catalog=current_database() AND table_schema=? ORDER BY table_name,ordinal_position LIMIT 30", [DOMAIN]).fetchall()
        expected = [(table, name, kind, "NO", None) for table, fields in sorted(_FIELDS.items()) for name, kind in fields]
        if columns != expected:
            raise _error("normalized query column drift")
        constraints = self.cx.execute("SELECT table_name,constraint_type,constraint_column_names,expression FROM duckdb_constraints() WHERE database_name=current_database() AND schema_name=? LIMIT 39", [DOMAIN]).fetchall()
        actual = [(table, kind, tuple(names), expression) for table, kind, names, expression in constraints]
        expected_constraints = [(table, "NOT NULL", (name,), None) for table, fields in _FIELDS.items() for name, _ in fields]
        expected_constraints += [(table, "PRIMARY KEY", names, None) for table, names in _PRIMARY.items()]
        expected_constraints += [("meta", "CHECK", ("singleton",), "(singleton = 1)")]
        expected_constraints += [("epochs", "CHECK", ("singleton",), "(singleton = 1)"),
                                 ("epochs", "CHECK", ("next_epoch",), "(next_epoch > 0)")]
        if len(actual) != len(expected_constraints) or set(actual) != set(expected_constraints):
            raise _error("normalized query constraint drift")
        rows = self._read_rows("meta", "", [], limit=2)
        if rows != [(1, SCHEMA, cid_for_structured(_DDL), self._identity(), str(self.artifacts.root.resolve()))]:
            raise _error("normalized query owner/schema binding differs")
        self._next_epoch()

    def _next_epoch(self):
        rows = self._read_rows("epochs", "", [], limit=2)
        if (len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int
                or not 1 <= rows[0][1] < 2**63):
            raise _error("normalized inventory epoch allocator is missing or invalid")
        largest = self.cx.execute(f"SELECT max(epoch) FROM {DOMAIN}.inventories").fetchone()[0]
        if largest is not None and (largest <= 0 or largest >= rows[0][1]):
            raise _error("normalized inventory epoch allocator regressed")
        return rows[0][1]

    def _read_rows(self, table, clause, parameters, *, limit, byte_limit=None):
        fields = _FIELDS[table]
        size = " + ".join(f"octet_length(encode({name}))" if kind == "VARCHAR" else "8" for name, kind in fields)
        tail = f" FROM {DOMAIN}.{table} " + clause + " LIMIT ?"
        sizes = self.cx.execute("SELECT " + size + tail, [*parameters, limit]).fetchall()
        budget = self.limits.max_query_inventory_bytes if byte_limit is None else min(byte_limit, self.limits.max_query_inventory_bytes)
        if (any(row[0] is None or not 0 < row[0] <= _SQL_ROW_BYTES for row in sizes)
                or sum(row[0] for row in sizes) > budget):
            raise _error("normalized SQL row exceeds its byte bound")
        return self.cx.execute("SELECT " + ",".join(name for name, _ in fields) + tail, [*parameters, limit]).fetchall()

    def _counts(self):
        bounds = {"inventories": self.limits.max_records, "entries": self.limits.max_entries,
                  "keys": self.limits.max_query_keys, "dependencies": self.limits.max_query_dependencies}
        counts = {}
        for table, limit in bounds.items():
            count = self.cx.execute(f"SELECT count(*) FROM {DOMAIN}.{table}").fetchone()[0]
            if count > limit:
                raise _error("normalized query row bounds exceeded")
            counts[table] = count
        return counts

    def _source_ids(self, head):
        head_cid = cid_for_structured(head.to_dict())
        params = [head.repository_id, head_cid, self.limits.max_records + 1]
        clause = " FROM codebase_verification_control.records WHERE repository_id=? AND head_cid=? ORDER BY projection_cid LIMIT ?"
        sizes = self.cx.execute("SELECT octet_length(encode(projection_cid))" + clause, params).fetchall()
        if len(sizes) > self.limits.max_records or any(row[0] is None or not 0 < row[0] <= 512 for row in sizes):
            raise _error("source projection inventory exceeds its bounds")
        rows = self.cx.execute("SELECT projection_cid" + clause, params).fetchall()
        identities = tuple(row[0] for row in rows)
        for identity in identities:
            validate_cid(identity, codecs={"dag-json"})
        return identities

    def source_ids(self, head):
        return self._source_ids(head)

    def _state(self, head):
        rows = self._read_rows("inventories", "WHERE head_cid=?", [cid_for_structured(head.to_dict())], limit=2)
        if not rows:
            return None
        row = rows[0]
        if len(rows) != 1 or row[1] != head.repository_id or type(row[2]) is not int or row[2] <= 0:
            raise _error("invalid normalized inventory state")
        validate_cid(row[3], codecs={"dag-json"})
        return row

    def _derive(self, head, identities, checkpoint):
        entries, keys, dependencies = [], [], []
        consumed = 0
        row_bytes = 64
        def append_row(target, row, maximum):
            nonlocal row_bytes
            checkpoint()
            encoded = canonical_dag_json_bytes(list(row))
            if len(encoded) > _SQL_ROW_BYTES:
                raise _error("derived normalized row exceeds byte bound")
            row_bytes += len(encoded) + 1
            if row_bytes > self.limits.max_query_inventory_bytes:
                raise _error("normalized query inventory bytes exceed their bound")
            if len(target) >= maximum:
                raise _error("normalized query inventory row bounds exceeded")
            target.append(row)
        for identity in identities:
            checkpoint()
            value = self.catalog._bounded_artifact(identity, self.limits.max_projection_bytes)
            encoded = canonical_dag_json_bytes(value)
            consumed += len(encoded)
            if consumed > self.limits.max_query_inventory_bytes:
                raise _error("query inventory artifact bytes exceed their bound")
            if (value.get("schema") != "codebase-conditional-verification-projection@1"
                    or canonical_dag_json_bytes(value.get("head")) != canonical_dag_json_bytes(head.to_dict())):
                raise _error("sealed normalized projection belongs to another schema/head")
            for contract in value["contracts"]:
                checkpoint()
                entry_id = cid_for_structured({"projection_cid": identity, "contract_id": contract["contract_id"]})
                append_row(entries, (entry_id, cid_for_structured(head.to_dict()), identity, value["path"],
                    contract["contract_id"], contract["contract_cid"], contract["domain_id"] or "", contract["domain_cid"] or "", value["verification_cid"]), self.limits.max_entries)
                for kind, item in contract_dependencies(value, contract):
                    append_row(dependencies, (entry_id, kind, item), self.limits.max_query_dependencies)
                for phase, field in (("verification", "canonical_keys"), ("applicability", "applicability_keys")):
                    for item in contract[field]:
                        checkpoint()
                        native = CanonicalProofCacheKey.from_dict(item["key"])
                        encoded_key = canonical_dag_json_bytes(native.to_dict())
                        if native.key_id != item["key_id"] or encoded_key != canonical_dag_json_bytes(item["key"]):
                            raise _error("normalized key does not recompute")
                        append_row(keys, (entry_id, native.key_id, phase, item.get("kind", ""), item["obligation_id"], encoded_key.decode()), self.limits.max_query_keys)
        rows = {"entries": sorted(entries), "keys": sorted(keys), "dependencies": sorted(dependencies)}
        for table, values in rows.items():
            if len(set(values)) != len(values):
                raise _error("duplicate normalized inventory row")
            for row in values:
                if sum(len(str(item).encode()) for item in row) > _SQL_ROW_BYTES:
                    raise _error("derived normalized row exceeds byte bound")
        return rows

    def _manifest(self, head, epoch, identities, rows):
        value = {"schema": INVENTORY_SCHEMA, "head": head.to_dict(), "epoch": epoch,
                 "projection_cids": list(identities), **{key: [list(row) for row in values] for key, values in rows.items()}}
        raw = canonical_dag_json_bytes(value)
        if len(raw) > min(self.limits.max_query_inventory_bytes, self.artifacts.max_object_bytes):
            raise _error("sealed query inventory exceeds its byte bound")
        return value

    def _sql_rows(self, head):
        head_cid = cid_for_structured(head.to_dict())
        entries = self._read_rows("entries", "WHERE head_cid=? ORDER BY entry_id", [head_cid], limit=self.limits.max_entries + 1)
        out = {"entries": entries}
        remaining = self.limits.max_query_inventory_bytes - sum(len(item.encode()) for row in entries for item in row)
        for table, limit in (("keys", self.limits.max_query_keys), ("dependencies", self.limits.max_query_dependencies)):
            clause = f"WHERE entry_id IN (SELECT entry_id FROM {DOMAIN}.entries WHERE head_cid=?) ORDER BY " + ",".join(name for name, _ in _FIELDS[table])
            out[table] = self._read_rows(table, clause, [head_cid], limit=limit + 1, byte_limit=remaining)
            remaining -= sum(len(item.encode()) for row in out[table] for item in row)
        return out

    def validate_inventory(self, *, expected_head, checkpoint, initialize_empty=False):
        self.check_schema()
        self._counts()
        identities = self._source_ids(expected_head)
        state = self._state(expected_head)
        if state is None:
            if identities or not initialize_empty:
                raise _error("normalized inventory is absent; explicit rebuild_current is required")
            if self.cx.execute(f"SELECT count(*) FROM {DOMAIN}.entries WHERE head_cid=?", [cid_for_structured(expected_head.to_dict())]).fetchone()[0]:
                raise _error("missing empty inventory retains normalized entries; explicit rebuild required")
            for table in ("keys", "dependencies"):
                if self.cx.execute(f"SELECT count(*) FROM {DOMAIN}.{table} r WHERE NOT EXISTS (SELECT 1 FROM {DOMAIN}.entries e WHERE e.entry_id=r.entry_id)").fetchone()[0]:
                    raise _error("missing inventory retains orphan normalized rows")
            return self.synchronize(expected_head=expected_head, checkpoint=checkpoint)
        manifest = self.catalog._bounded_artifact(state[3], self.limits.max_query_inventory_bytes)
        rows = self._derive(expected_head, identities, checkpoint)
        expected = self._manifest(expected_head, state[2], identities, rows)
        if canonical_dag_json_bytes(manifest) != canonical_dag_json_bytes(expected):
            raise _error("sealed evidence inventory differs from complete source projections")
        if self._sql_rows(expected_head) != rows:
            raise _error("normalized key/dependency inventory differs from sealed artifacts")
        # A dangling row can hide after deletion/repointing of its parent entry.
        for table in ("keys", "dependencies"):
            count = self.cx.execute(f"SELECT count(*) FROM {DOMAIN}.{table} r WHERE NOT EXISTS (SELECT 1 FROM {DOMAIN}.entries e WHERE e.entry_id=r.entry_id)").fetchone()[0]
            if count:
                raise _error("orphan normalized inventory row")
        checkpoint()
        return EvidenceInventory(state[0], state[3], state[2], identities)

    def synchronize(self, *, expected_head, checkpoint, rebuild=False):
        self.check_schema()
        identities = self._source_ids(expected_head)
        state = self._state(expected_head)
        rows = self._derive(expected_head, identities, checkpoint)
        if state is not None and not rebuild:
            old = self.catalog._bounded_artifact(state[3], self.limits.max_query_inventory_bytes)
            if old == self._manifest(expected_head, state[2], identities, rows):
                return self.validate_inventory(expected_head=expected_head, checkpoint=checkpoint)
        epoch = self._next_epoch()
        if epoch >= 2**63 - 1:
            raise _error("normalized inventory epoch exhausted")
        manifest = self._manifest(expected_head, epoch, identities, rows)
        inventory_cid = self.artifacts.put(manifest)
        if inventory_cid != cid_for_structured(manifest):
            raise _error("query inventory publication identity changed")
        head_cid = cid_for_structured(expected_head.to_dict())
        for table in ("keys", "dependencies"):
            self.cx.execute(f"DELETE FROM {DOMAIN}.{table} WHERE entry_id IN (SELECT entry_id FROM {DOMAIN}.entries WHERE head_cid=?)", [head_cid])
        self.cx.execute(f"DELETE FROM {DOMAIN}.entries WHERE head_cid=?", [head_cid])
        for table in ("entries", "keys", "dependencies"):
            if rows[table]:
                checkpoint()
                placeholders = ",".join("?" for _ in _FIELDS[table])
                self.cx.executemany(f"INSERT INTO {DOMAIN}.{table} VALUES ({placeholders})", rows[table])
        self.cx.execute(f"INSERT OR REPLACE INTO {DOMAIN}.inventories VALUES (?, ?, ?, ?)",
                        [head_cid, expected_head.repository_id, epoch, inventory_cid])
        self.cx.execute(f"UPDATE {DOMAIN}.epochs SET next_epoch=? WHERE singleton=1", [epoch + 1])
        self._counts()
        checkpoint()
        return EvidenceInventory(head_cid, inventory_cid, epoch, identities)

    def select_entries(self, selector, *, inventory, after=None, exact_entry=None, limit):
        clauses, params = ["head_cid=?"], [inventory.head_cid]
        columns = {"path": "path", "contract_id": "contract_id", "expected_contract_cid": "contract_cid",
            "verification_cid": "verification_cid", "requested_domain_id": "domain_id", "requested_domain_cid": "domain_cid"}
        for name, column in columns.items():
            if selector.get(name) is not None:
                clauses.append(column + "=?")
                params.append(selector[name])
        if selector.get("canonical_key_id") is not None:
            clauses.append(f"EXISTS (SELECT 1 FROM {DOMAIN}.keys k WHERE k.entry_id=e.entry_id AND k.key_id=?)")
            params.append(selector["canonical_key_id"])
        if selector.get("dependency_kind") is not None:
            validate_dependency(selector["dependency_kind"], selector["dependency_value"])
            clauses.append(f"EXISTS (SELECT 1 FROM {DOMAIN}.dependencies d WHERE d.entry_id=e.entry_id AND d.kind=? AND d.value=?)")
            params += [selector["dependency_kind"], selector["dependency_value"]]
        if after is not None:
            clauses.append("entry_id>?")
            params.append(after)
        if exact_entry is not None:
            clauses.append("entry_id=?")
            params.append(exact_entry)
        query = f" FROM {DOMAIN}.entries e WHERE " + " AND ".join(clauses) + " ORDER BY entry_id LIMIT ?"
        sizes = self.cx.execute("SELECT octet_length(encode(entry_id))+octet_length(encode(projection_cid))+octet_length(encode(contract_id))" + query, params + [limit]).fetchall()
        if any(row[0] is None or row[0] > _SQL_ROW_BYTES for row in sizes):
            raise _error("normalized selected row exceeds byte bound")
        return tuple(self.cx.execute("SELECT entry_id,projection_cid,contract_id" + query, params + [limit]).fetchall())
