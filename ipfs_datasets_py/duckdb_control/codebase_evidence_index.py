"""Bounded, durable conditional evidence on the structural catalog owner.

This is an exact historical index, not a proof checker or a source observer.
Canonical identities establish artifact integrity, not checker authenticity.
Every use still needs fresh native checks and the wrapper's live source fence.
Only the closed integer-offset receipt profile is admitted in this version.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .codebase_catalog import CodebaseCatalog, CodebaseCatalogError, CodebaseHead, CodebaseHeadConflict
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured, validate_cid,
)

SCHEMA = "codebase-evidence-index@1"
RECORD_SCHEMA = "codebase-conditional-evidence-record@1"
DEPENDENCY_KINDS = frozenset({"source", "snapshot", "contract", "compiled", "profile", "environment", "compiler"})
_RECORD_COLUMNS = (("receipt_cid", "VARCHAR"), ("repository_id", "VARCHAR"),
                   ("generation", "BIGINT"), ("head_cid", "VARCHAR"),
                   ("canonical_key_id", "VARCHAR"), ("binding_cid", "VARCHAR"),
                   ("record_cid", "VARCHAR"))
_COLUMNS = {
    "meta": (("singleton", "INTEGER"), ("schema_id", "VARCHAR"),
             ("schema_cid", "VARCHAR"), ("catalog_cid", "VARCHAR"), ("artifact_root", "VARCHAR")),
    "records": _RECORD_COLUMNS,
    "dependencies": (("receipt_cid", "VARCHAR"), ("kind", "VARCHAR"), ("value", "VARCHAR")),
}
_DDL = (
    "CREATE SCHEMA codebase_evidence",
    "CREATE TABLE codebase_evidence.meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_id VARCHAR NOT NULL, schema_cid VARCHAR NOT NULL, catalog_cid VARCHAR NOT NULL, artifact_root VARCHAR NOT NULL)",
    "CREATE TABLE codebase_evidence.records (receipt_cid VARCHAR PRIMARY KEY, repository_id VARCHAR NOT NULL, generation BIGINT NOT NULL, head_cid VARCHAR NOT NULL, canonical_key_id VARCHAR NOT NULL, binding_cid VARCHAR NOT NULL, record_cid VARCHAR NOT NULL)",
    "CREATE TABLE codebase_evidence.dependencies (receipt_cid VARCHAR NOT NULL, kind VARCHAR NOT NULL, value VARCHAR NOT NULL, PRIMARY KEY(receipt_cid, kind, value))",
)
_RECEIPT_FIELDS = frozenset({"schema", "profile", "status", "head", "contract", "contract_cid", "source_cid",
    "compiled_cid", "checks", "cache_binding", "cache_history_hit", "solver_check_attempted", "solver_replayed",
    "kernel_checked", "behavior_authority", "execution_authority", "completion_authority", "evidence_scope", "diagnostics"})
_CHECK_FIELDS = frozenset({"schema", "profile", "status", "compiled_cid", "contract_cid", "source_cid", "revision",
    "assumptions", "solvers", "query_cid", "evidence_kind", "checker_identity", "kernel_checked", "behavior_authority",
    "model_checked_against_runtime", "bounds"})
_COMPILED_FIELDS = frozenset({"schema", "profile", "contract", "contract_cid", "source_cid", "revision", "body_offset",
    "parser", "assumptions", "source_binding", "compilation", "kernel_checked", "behavior_authority"})
_OBSERVATION_FIELDS = frozenset({"solver", "status", "executable", "executable_sha256", "launcher_sha256", "version",
    "verdict", "model_text", "stdout", "stderr", "elapsed_ms", "workspace_cleaned"})
_ENVIRONMENT_FIELDS = frozenset({"python", "implementation", "parser", "system", "machine", "release", "source_sha256",
    "environment", "dependency_scope", "solvers", "resource_helper"})


class CodebaseEvidenceIndexError(CodebaseCatalogError):
    """An evidence artifact, SQL projection or query exceeds its closed contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CodebaseEvidenceIndexError(message)


def _same(left: Any, right: Any) -> bool:
    return canonical_dag_json_bytes(left) == canonical_dag_json_bytes(right)


def _object(value: Any, fields: frozenset[str] | set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"invalid {label} fields")
    return value


def _text(value: Any, label: str, maximum: int = 1024, *, empty: bool = False) -> str:
    _require(type(value) is str and (empty or bool(value)) and len(value.encode()) <= maximum,
             f"invalid bounded {label}")
    return value


def _sha256(value: Any) -> str:
    _require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "invalid compiler/executable digest")
    return value


def _cid(value: Any, codec: str = "dag-json") -> str:
    try:
        return validate_cid(value, codecs={codec})
    except (TypeError, ValueError) as exc:
        raise CodebaseEvidenceIndexError("invalid evidence CID") from exc


@dataclass(frozen=True, slots=True)
class CodebaseEvidenceIndexLimits:
    """Finite admission and query caps; these are not an RSS guarantee."""

    max_records: int = 2048
    max_batch: int = 64
    max_query_results: int = 128
    max_dependencies_per_record: int = 96
    max_receipt_bytes: int = 1024 * 1024
    max_compiled_bytes: int = 1024 * 1024
    max_sql_row_bytes: int = 8192

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _require(type(getattr(self, name)) is int and getattr(self, name) > 0,
                     f"{name} must be a positive exact integer")


@dataclass(frozen=True, slots=True)
class CodebaseEvidenceRecord:
    receipt_cid: str
    head: CodebaseHead
    status: str
    _binding_bytes: bytes
    _receipt_bytes: bytes
    dependencies: tuple[tuple[str, str], ...]

    @property
    def binding(self) -> dict[str, Any]:
        return json.loads(self._binding_bytes)

    @property
    def receipt(self) -> dict[str, Any]:
        return json.loads(self._receipt_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": RECORD_SCHEMA, "receipt_cid": self.receipt_cid, "head": self.head.to_dict(),
                "status": self.status, "binding": self.binding,
                "dependencies": [{"kind": kind, "value": value} for kind, value in self.dependencies],
                "authority": "historical_conditional", "requires_fresh_native_checks": True,
                "requires_current_source_observation": True, "kernel_checked": False,
                "behavior_authority": False, "execution_authority": False, "completion_authority": False}

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())


class CodebaseEvidenceIndex:
    """Exact receipts and reverse dependencies using one native catalog owner.

    No startup hydration, independent connection, native solver execution or
    compiler invocation occurs here. Reads validate sealed artifacts afresh.
    Caller-managed independent connections can conflict and must retry; workers
    must not inherit this connection. SQL row caps reject overflow, never prune.
    """

    def __init__(self, catalog: CodebaseCatalog, *, limits: CodebaseEvidenceIndexLimits | None = None) -> None:
        _require(type(catalog) is CodebaseCatalog, "an exact native CodebaseCatalog owner is required")
        self.catalog = catalog
        self.store, self.artifacts, self._cx = catalog.store, catalog.artifacts, catalog._cx
        self.limits = limits if limits is not None else CodebaseEvidenceIndexLimits()
        _require(type(self.limits) is CodebaseEvidenceIndexLimits, "invalid evidence index limits")
        with self.store._lock:
            catalog._ensure_owner()
            with self.store._transaction():
                catalog._check_schema()
                exists = self._cx.execute("SELECT schema_name FROM information_schema.schemata WHERE catalog_name=current_database() AND schema_name='codebase_evidence'").fetchall()
                if not exists:
                    for statement in _DDL:
                        self._cx.execute(statement)
                    self._cx.execute("INSERT INTO codebase_evidence.meta VALUES (1, ?, ?, ?, ?)",
                                     [SCHEMA, cid_for_structured(list(_DDL)), self._schema_identity(), str(catalog._artifact_root)])
                self._check_schema()
                self._counts()

    def _schema_identity(self) -> str:
        rows = self._cx.execute("SELECT table_name, sql FROM duckdb_tables() WHERE database_name=current_database() AND schema_name='codebase_evidence' ORDER BY table_name").fetchall()
        return cid_for_structured([list(row) for row in rows])

    def _check_schema(self) -> None:
        rows = self._cx.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema='codebase_evidence' LIMIT 4").fetchall()
        _require(set(rows) == {(name, "BASE TABLE") for name in _COLUMNS}, "foreign or drifted evidence schema")
        columns = self._cx.execute("SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_catalog=current_database() AND table_schema='codebase_evidence' ORDER BY table_name, ordinal_position LIMIT 16").fetchall()
        expected = [(table, name, kind, "NO", None) for table, fields in sorted(_COLUMNS.items()) for name, kind in fields]
        _require(columns == expected, "evidence schema columns changed")
        constraints = self._cx.execute("SELECT table_name, constraint_type, constraint_column_names, expression FROM duckdb_constraints() WHERE database_name=current_database() AND schema_name='codebase_evidence' LIMIT 20").fetchall()
        actual = [(table, kind, tuple(names), expression) for table, kind, names, expression in constraints]
        wanted = [(table, "NOT NULL", (name,), None) for table, fields in _COLUMNS.items() for name, _ in fields]
        wanted += [("meta", "PRIMARY KEY", ("singleton",), None), ("records", "PRIMARY KEY", ("receipt_cid",), None),
                   ("dependencies", "PRIMARY KEY", ("receipt_cid", "kind", "value"), None),
                   ("meta", "CHECK", ("singleton",), "(singleton = 1)")]
        _require(len(actual) == len(wanted) and set(actual) == set(wanted), "evidence schema constraints changed")
        sizes = self._cx.execute("SELECT octet_length(encode(schema_id)) + octet_length(encode(schema_cid)) + octet_length(encode(catalog_cid)) + octet_length(encode(artifact_root)) FROM codebase_evidence.meta LIMIT 2").fetchall()
        _require(len(sizes) == 1 and 0 < sizes[0][0] <= self.limits.max_sql_row_bytes, "evidence metadata exceeds its bound")
        rows = self._cx.execute("SELECT singleton, schema_id, schema_cid, catalog_cid, artifact_root FROM codebase_evidence.meta LIMIT 2").fetchall()
        _require(rows == [(1, SCHEMA, cid_for_structured(list(_DDL)), self._schema_identity(), str(self.catalog._artifact_root))],
                 "evidence schema or artifact root binding changed")

    def _counts(self) -> int:
        records, dependencies = self._cx.execute(
            "SELECT (SELECT count(*) FROM (SELECT 1 FROM codebase_evidence.records LIMIT ?)), "
            "(SELECT count(*) FROM (SELECT 1 FROM codebase_evidence.dependencies LIMIT ?))",
            [self.limits.max_records + 1, self.limits.max_records * self.limits.max_dependencies_per_record + 1]).fetchone()
        _require(records <= self.limits.max_records and dependencies <= self.limits.max_records * self.limits.max_dependencies_per_record,
                 "evidence index exceeds its row bounds")
        return records

    def _head(self, expected_head: CodebaseHead) -> None:
        _require(type(expected_head) is CodebaseHead, "an exact expected head is required")
        CodebaseHead.from_dict(expected_head.to_dict())
        self.catalog._check_schema()
        self._check_schema()
        self._counts()
        if self.catalog._current(expected_head.repository_id) != expected_head:
            raise CodebaseHeadConflict("evidence index expected head is no longer current")

    def _validate_compilation(self, payload: dict[str, Any], receipt: dict[str, Any], source: bytes) -> None:
        from ipfs_datasets_py.logic.backends.smt.compiler import SmtCompilation, SmtScript
        from ipfs_datasets_py.logic.backends.smt.differential import normalize_smtlib_for_solver
        from ipfs_datasets_py.logic.software_verification.receipts import LogicTranslationReceipt
        from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import COMPILED_SCHEMA, MAX_LITERAL_BITS

        _object(payload, _COMPILED_FIELDS, "compiled artifact")
        checks = receipt["checks"]
        _require(payload["schema"] == COMPILED_SCHEMA and payload["profile"] == receipt["profile"], "invalid compiled profile")
        for name in ("contract", "contract_cid", "source_cid"):
            _require(_same(payload[name], receipt[name]), "compiled artifact has a different " + name)
        for name in ("revision", "assumptions"):
            _require(_same(payload[name], checks[name]), "compiled artifact has a different " + name)
        _require(type(payload["body_offset"]) is int and payload["body_offset"].bit_length() <= MAX_LITERAL_BITS,
                 "invalid compiled body offset")
        _require(payload["kernel_checked"] is False and payload["behavior_authority"] is False,
                 "compiled artifact cannot acquire authority")
        _require(payload["parser"] == checks["checker_identity"]["parser"], "compiled parser differs from checker environment")
        binding = _object(payload["source_binding"], {"content_sha256", "source_revision", "language", "path", "program_id", "source_ref_ids", "span_ids"}, "compiled source binding")
        _require(binding["content_sha256"] == hashlib.sha256(source).hexdigest()
                 and binding["source_revision"] == checks["revision"] and binding["language"] == "python"
                 and binding["path"] == receipt["contract"]["path"], "compiled source binding differs from captured source")
        _text(binding["program_id"], "program identity")
        for name in ("source_ref_ids", "span_ids"):
            _require(type(binding[name]) is list and 0 < len(binding[name]) <= 128, "invalid source span/reference inventory")
            for value in binding[name]:
                _text(value, "source span/reference")
        raw = payload["compilation"]
        _require(type(raw) is dict and type(raw.get("script")) is dict, "missing typed SMT compilation")
        script = raw["script"]
        typed_script = SmtScript(logic=script["logic"], query_mode=script["query_mode"], lines=tuple(script["lines"]),
            theories=tuple(script["theories"]), request_model=script["request_model"],
            request_unsat_core=script["request_unsat_core"], schema_version=script["schema_version"])
        typed = SmtCompilation(obligation_id=raw["obligation_id"], script=typed_script,
            receipt=LogicTranslationReceipt.from_dict(raw["receipt"]), capabilities=tuple(raw["capabilities"]),
            features=tuple(raw["features"]), query_mode=raw["query_mode"], source_identity=raw["source_identity"],
            target_identity=raw["target_identity"], compiler_version=raw["compiler_version"], schema_version=raw["schema_version"])
        _require(_same(raw, typed.to_dict()), "SMT compilation identities or fields do not recompute")
        query = "\n".join(line for line in normalize_smtlib_for_solver(typed.smtlib).splitlines()
                          if line.strip() not in {"(get-model)", "(get-unsat-core)"}) + "\n"
        _require(checks["query_cid"] == cid_for_bytes(query.encode()), "native query does not bind the sealed compilation")

    def _validate_native_metadata(self, receipt: dict[str, Any]) -> tuple[str, ...]:
        from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import (
            ASSUMPTIONS, RESULT_SCHEMA, SOLVER_MEMORY_MB, MAX_IO_BYTES, MAX_SOURCE_BYTES, MAX_AST_NODES, MAX_LITERAL_BITS,
        )
        checks = _object(receipt["checks"], _CHECK_FIELDS, "native checks")
        _require(checks["schema"] == RESULT_SCHEMA and checks["status"] == receipt["status"]
                 and checks["profile"] == receipt["profile"] and checks["evidence_kind"] == "conditional_smt"
                 and checks["kernel_checked"] is False and checks["behavior_authority"] is False
                 and checks["model_checked_against_runtime"] is False, "invalid conditional check scope")
        for name in ("source_cid", "compiled_cid", "contract_cid"):
            _require(checks[name] == receipt[name], "native checks have a different " + name)
        _require(checks["revision"] == "snapshot:" + receipt["head"]["snapshot_cid"]
                 and _same(checks["assumptions"], list(ASSUMPTIONS)), "native checks have different revision or assumptions")
        env = _object(checks["checker_identity"], _ENVIRONMENT_FIELDS, "checker environment")
        helper = _object(env["resource_helper"], {"kind", "sha256"}, "native resource helper")
        _require(helper["kind"] == "linux-prlimit", "unsupported native resource helper")
        _sha256(helper["sha256"])
        for name in ("python", "implementation", "parser", "system", "machine", "release", "dependency_scope"):
            _text(env[name], "checker " + name, 4096)
        _require(type(env["environment"]) is dict and 0 < len(env["environment"]) <= 32, "invalid native environment")
        for key, value in env["environment"].items():
            _text(key, "environment name")
            _text(value, "environment value")
        hashes = []
        for values in (env["source_sha256"], receipt["cache_binding"]["profile"]["implementation_sha256"]):
            _require(type(values) is dict and 0 < len(values) <= 64, "invalid compiler implementation inventory")
            for key, value in values.items():
                _text(key, "compiler module")
                hashes.append(_sha256(value))
        observations = checks["solvers"]
        _require(type(observations) is list and len(observations) == 2, "both native solver observations are required")
        for item in observations:
            _object(item, _OBSERVATION_FIELDS, "solver observation")
        _require({item["solver"] for item in observations} == {"z3", "cvc5"}, "native solver inventory differs")
        identities = []
        verdict = "unsat" if receipt["status"] == "proved" else "sat"
        for item in observations:
            _require(item["status"] == receipt["status"] and item["verdict"] == verdict
                     and item["stdout"].strip() == verdict and item["workspace_cleaned"] is True,
                     "terminal receipt contradicts native solver observations")
            _require(type(item["elapsed_ms"]) is int and item["elapsed_ms"] >= 0, "invalid solver elapsed duration")
            for name in ("stdout", "stderr", "model_text"):
                _text(item[name], name, MAX_IO_BYTES, empty=True)
            _require(bool(item["model_text"]) == (verdict == "sat"), "native model presence differs from verdict")
            _text(item["executable"], "native executable", 4096)
            _text(item["version"], "native version", MAX_IO_BYTES)
            _sha256(item["executable_sha256"])
            if item["launcher_sha256"]:
                _sha256(item["launcher_sha256"])
            else:
                _require(item["launcher_sha256"] == "", "invalid empty launcher identity")
            identities.append({name: item[name] for name in ("solver", "executable_sha256", "launcher_sha256", "version")})
        _require(_same(env["solvers"], identities), "solver observations differ from canonical environment")
        bounds = checks["bounds"]
        fixed = {"solver_memory_mb": SOLVER_MEMORY_MB, "max_input_bytes": MAX_IO_BYTES,
                 "max_output_bytes": MAX_IO_BYTES, "max_workspace_bytes": MAX_IO_BYTES,
                 "termination_grace_ms": 250, "rss_sampling_ms": 100, "solver_cpu_slots": 1,
                 "solver_process_slots": 1, "sequential_solvers": 2, "max_source_bytes": MAX_SOURCE_BYTES,
                 "max_ast_nodes": MAX_AST_NODES, "max_literal_bits": MAX_LITERAL_BITS,
                 "memory_control": "per-process address-space cap and sampled process-tree RSS guard"}
        _object(bounds, set(fixed) | {"total_timeout_ms", "cpu_seconds"}, "native bounds")
        _require(_same({name: bounds[name] for name in fixed}, fixed), "native bounds do not match this evidence profile")
        _require(type(bounds["total_timeout_ms"]) is int and 0 < bounds["total_timeout_ms"] <= 120000
                 and type(bounds["cpu_seconds"]) is int
                 and bounds["cpu_seconds"] == (bounds["total_timeout_ms"] + 999) // 1000,
                 "invalid native timeout/CPU bounds")
        return tuple(sorted(set(hashes)))

    def _record(self, receipt_cid: str, head: CodebaseHead) -> CodebaseEvidenceRecord:
        from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest
        from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
        from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import PROFILE, IntegerOffsetContract, MAX_SOURCE_BYTES
        from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import property_analysis_cache_key
        from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import SCHEMA as RECEIPT_SCHEMA

        _cid(receipt_cid)
        try:
            receipt = _object(self.catalog._read_artifact(receipt_cid, self.limits.max_receipt_bytes), _RECEIPT_FIELDS, "verification receipt")
            _require(receipt["schema"] == RECEIPT_SCHEMA and receipt["profile"] == PROFILE
                     and receipt["status"] in {"proved", "refuted"}, "unsupported historical receipt profile or status")
            if CodebaseHead.from_dict(receipt["head"]) != head:
                raise CodebaseHeadConflict("receipt belongs to a different structural head")
            _require(all(receipt[name] is False for name in ("kernel_checked", "behavior_authority", "execution_authority", "completion_authority"))
                     and receipt["solver_check_attempted"] is True and receipt["solver_replayed"] is True
                     and type(receipt["cache_history_hit"]) is bool and receipt["diagnostics"] == []
                     and receipt["evidence_scope"] == "conditional_integer_contract", "receipt has unsupported evidence authority or lifecycle")
            contract = IntegerOffsetContract.from_dict(receipt["contract"])
            _require(contract.cid == receipt["contract_cid"], "contract identity does not recompute")
            binding = receipt["cache_binding"]
            property_analysis_cache_key(binding)  # Full canonical proof key recomputation.
            profile = _object(binding["profile"], {"name", "contract", "assumptions", "implementation_sha256"}, "bound profile")
            _require(profile["name"] == PROFILE and _same(profile["contract"], contract.to_dict()), "binding profile differs from receipt")
            for name in ("source_cid", "contract_cid", "compiled_cid"):
                _require(binding[name] == receipt[name], "canonical binding differs from receipt " + name)
            _require(binding["snapshot_cid"] == head.snapshot_cid and binding["provider"] == "native-z3-cvc5"
                     and binding["checker"] == "current-integer-offset@1", "binding provider/checker/snapshot differs")
            hashes = self._validate_native_metadata(receipt)
            checks = receipt["checks"]
            _require(_same(binding["bounds"], checks["bounds"]) and _same(binding["environment"], checks["checker_identity"])
                     and _same(profile["assumptions"], checks["assumptions"]), "canonical key dimensions differ from native receipt")
            manifest = CodebaseIRManifest.from_dict(self.catalog._read_artifact(head.manifest_cid, self.catalog.limits.max_manifest_bytes))
            _require(manifest.snapshot.snapshot_cid == head.snapshot_cid and manifest.snapshot.repository_id == head.repository_id
                     and manifest.ast_revision_id == head.ast_revision_id, "manifest differs from current head")
            entries = [entry for entry in manifest.snapshot.entries if entry.path == contract.path]
            _require(len(entries) == 1 and not entries[0].is_opaque and entries[0].source_cid == receipt["source_cid"],
                     "receipt source is absent or different in the head manifest")
            entry = entries[0]
            unit = next(unit for unit in manifest.units if unit.source_key == entry.source_key)
            _require(unit.parse_status == "ok" and unit.ast_cid is not None, "receipt requires a successfully parsed structural source")
            source = self.catalog._read_artifact(entry.source_cid, MAX_SOURCE_BYTES, source=True)
            ast = ASTRecord.from_dict(self.catalog._read_artifact(unit.ast_cid, self.catalog.limits.max_ast_bytes))
            _require(ast.provenance.source_cid == entry.source_cid and ast.provenance.path == contract.path
                     and ast.provenance.repository_id == head.repository_id
                     and ast.provenance.revision == "snapshot:" + head.snapshot_cid
                     and ast.provenance.repository_tree_cid == head.snapshot_cid,
                     "immutable AST does not bind the selected source")
            rows = self.store._rows("ast_blobs", "ast_cid=?", [unit.ast_cid], columns="blob_id")
            _require(len(rows) == 1, "active structural AST is missing or ambiguous")
            active = self.store._load(rows[0]["blob_id"])
            _require(active is not None and active.ast_cid == unit.ast_cid and active.source_cid == entry.source_cid
                     and active.source_file.path == contract.path and active.source_revision.revision_id == head.ast_revision_id
                     and active.ast_blob.parse_status == "ok", "active structural projection differs from the manifest")
            compiled = self.catalog._read_artifact(receipt["compiled_cid"], self.limits.max_compiled_bytes)
            self._validate_compilation(compiled, receipt, source)
            dependencies = {("source", receipt["source_cid"]), ("snapshot", head.snapshot_cid),
                ("contract", contract.cid), ("compiled", receipt["compiled_cid"]),
                ("profile", cid_for_structured(profile)), ("environment", cid_for_structured(checks["checker_identity"]))}
            dependencies.update(("compiler", "sha256:" + digest) for digest in hashes)
            _require(len(dependencies) <= self.limits.max_dependencies_per_record, "receipt dependency bound exceeded")
            return CodebaseEvidenceRecord(receipt_cid, head, receipt["status"], canonical_dag_json_bytes(binding),
                                          canonical_dag_json_bytes(receipt), tuple(sorted(dependencies)))
        except CodebaseCatalogError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, StopIteration, RecursionError) as exc:
            raise CodebaseEvidenceIndexError("malformed conditional evidence artifact") from exc

    @staticmethod
    def _row(record: CodebaseEvidenceRecord) -> tuple[Any, ...]:
        return (record.receipt_cid, record.head.repository_id, record.head.generation,
                cid_for_structured(record.head.to_dict()), record.binding["canonical_key_id"],
                cid_for_structured(record.binding), record.cid)

    def _stored(self, receipt_cid: str, head: CodebaseHead) -> CodebaseEvidenceRecord | None:
        names = ", ".join(name for name, _ in _RECORD_COLUMNS)
        size_expr = " + ".join(f"octet_length(encode({name}))" for name, kind in _RECORD_COLUMNS if kind == "VARCHAR")
        sizes = self._cx.execute(f"SELECT {size_expr} FROM codebase_evidence.records WHERE receipt_cid=? LIMIT 2", [receipt_cid]).fetchall()
        if not sizes:
            return None
        _require(len(sizes) == 1 and 0 < sizes[0][0] <= self.limits.max_sql_row_bytes, "evidence SQL row exceeds its bound")
        row = self._cx.execute(f"SELECT {names} FROM codebase_evidence.records WHERE receipt_cid=?", [receipt_cid]).fetchone()
        record = self._record(receipt_cid, head)
        _require(row == self._row(record), "SQL evidence metadata differs from sealed receipt")
        sizes = self._cx.execute("SELECT octet_length(encode(kind)) + octet_length(encode(value)) FROM codebase_evidence.dependencies WHERE receipt_cid=? LIMIT ?",
                                 [receipt_cid, self.limits.max_dependencies_per_record + 1]).fetchall()
        _require(len(sizes) <= self.limits.max_dependencies_per_record and all(0 < row[0] <= self.limits.max_sql_row_bytes for row in sizes),
                 "SQL dependency rows exceed their bound")
        deps = self._cx.execute("SELECT kind, value FROM codebase_evidence.dependencies WHERE receipt_cid=? ORDER BY kind, value LIMIT ?",
                               [receipt_cid, self.limits.max_dependencies_per_record + 1]).fetchall()
        _require(tuple(deps) == record.dependencies, "SQL reverse dependencies differ from sealed receipt")
        return record

    def publish(self, receipt_cid: str, *, expected_head: CodebaseHead,
                checkpoint: Callable[[], None] | None = None) -> CodebaseEvidenceRecord:
        return self.publish_many((receipt_cid,), expected_head=expected_head, checkpoint=checkpoint)[0]

    def publish_many(self, receipt_cids: Sequence[str], *, expected_head: CodebaseHead,
                     checkpoint: Callable[[], None] | None = None) -> tuple[CodebaseEvidenceRecord, ...]:
        """Publish one bounded batch atomically, including cancellation rollback.

        Exact repeats are idempotent. A stale generation never rebinds historical
        evidence to a successor. The caller owns live checkout observation.
        """
        _require(isinstance(receipt_cids, (tuple, list)) and len(receipt_cids) <= self.limits.max_batch,
                 "receipt batch must be a bounded list or tuple")
        receipt_cids = tuple(_cid(value) for value in receipt_cids)
        _require(len(set(receipt_cids)) == len(receipt_cids), "duplicate receipt in evidence batch")
        _require(checkpoint is None or callable(checkpoint), "checkpoint must be callable")
        check = checkpoint or (lambda: None)
        with self.store._lock:
            self.catalog._ensure_owner()
            with self.store._transaction():
                self._head(expected_head)
                # DuckDB optimizes away a no-op UPDATE, so it is not a write
                # conflict guard. These adjacent writes retain a real row write
                # until commit, without changing the published head. No reads
                # or callbacks may occur between them. Other connections see
                # the original committed head; cancellation/crash rolls back.
                # This private guard does not allocate a generation or publish.
                self._cx.execute("UPDATE codebase_control.heads SET generation=-generation WHERE repository_id=?",
                                 [expected_head.repository_id])
                self._cx.execute("UPDATE codebase_control.heads SET generation=? WHERE repository_id=?",
                                 [expected_head.generation, expected_head.repository_id])
                check()
                planned = []
                additions = 0
                for receipt_cid in receipt_cids:
                    check()
                    existing = self._stored(receipt_cid, expected_head)
                    record = existing or self._record(receipt_cid, expected_head)
                    additions += existing is None
                    planned.append((record, existing is not None))
                _require(self._counts() + additions <= self.limits.max_records, "evidence record capacity exhausted")
                for record, exists in planned:
                    check()
                    if exists:
                        continue
                    self._cx.execute("INSERT INTO codebase_evidence.records VALUES (?, ?, ?, ?, ?, ?, ?)", list(self._row(record)))
                    self._cx.executemany("INSERT INTO codebase_evidence.dependencies VALUES (?, ?, ?)",
                                         [(record.receipt_cid, kind, value) for kind, value in record.dependencies])
                check()
                self._head(expected_head)
                check()
            return tuple(record for record, _ in planned)

    def get(self, receipt_cid: str, *, expected_head: CodebaseHead) -> CodebaseEvidenceRecord | None:
        _cid(receipt_cid)
        with self.store._lock:
            self.catalog._ensure_owner()
            with self.store._transaction():
                self._head(expected_head)
                return self._stored(receipt_cid, expected_head)

    def _query(self, where: str, parameters: list[Any], expected_head: CodebaseHead, limit: int) -> tuple[CodebaseEvidenceRecord, ...]:
        _require(type(limit) is int and 0 < limit <= self.limits.max_query_results, "invalid evidence query limit")
        with self.store._lock:
            self.catalog._ensure_owner()
            with self.store._transaction():
                self._head(expected_head)
                parameters += [expected_head.repository_id, expected_head.generation, cid_for_structured(expected_head.to_dict()), limit + 1]
                clause = (" FROM codebase_evidence.records r WHERE " + where
                    + " AND r.repository_id=? AND r.generation=? AND r.head_cid=? ORDER BY r.receipt_cid LIMIT ?")
                # A row limit does not bound a corrupted VARCHAR. Ask SQL for
                # sizes before materializing any selected identifier in Python.
                sizes = self._cx.execute("SELECT octet_length(encode(r.receipt_cid))" + clause, parameters).fetchall()
                _require(len(sizes) <= limit, "evidence query exceeds its result bound; narrow the query")
                _require(all(0 < row[0] <= self.limits.max_sql_row_bytes for row in sizes),
                         "queried receipt identifier exceeds its SQL byte bound")
                rows = self._cx.execute("SELECT r.receipt_cid" + clause, parameters).fetchall()
                records = tuple(self._stored(_cid(row[0]), expected_head) for row in rows)
                _require(all(record is not None for record in records), "evidence disappeared within its transaction")
                return records

    def lookup(self, binding: dict[str, Any], *, expected_head: CodebaseHead, limit: int = 32) -> tuple[CodebaseEvidenceRecord, ...]:
        from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import property_analysis_cache_key
        property_analysis_cache_key(binding)
        _require(type(expected_head) is CodebaseHead and binding["snapshot_cid"] == expected_head.snapshot_cid,
                 "lookup binding belongs to a different snapshot")
        records = self._query("r.canonical_key_id=? AND r.binding_cid=?",
                              [binding["canonical_key_id"], cid_for_structured(binding)], expected_head, limit)
        _require(all(_same(record.binding, binding) for record in records), "lookup returned a different canonical binding")
        return records

    def dependents(self, kind: str, value: str, *, expected_head: CodebaseHead, limit: int = 32) -> tuple[CodebaseEvidenceRecord, ...]:
        _require(type(kind) is str and kind in DEPENDENCY_KINDS, "unsupported evidence dependency kind")
        if kind == "compiler":
            _require(type(value) is str and value.startswith("sha256:"), "compiler dependencies use sha256 identities")
            _sha256(value[7:])
        else:
            _cid(value, "raw" if kind == "source" else "dag-json")
        records = self._query("EXISTS (SELECT 1 FROM codebase_evidence.dependencies d WHERE d.receipt_cid=r.receipt_cid AND d.kind=? AND d.value=?)",
                              [kind, value], expected_head, limit)
        _require(all((kind, value) in record.dependencies for record in records), "reverse query returned a different dependency")
        return records


__all__ = ["CodebaseEvidenceIndex", "CodebaseEvidenceIndexError", "CodebaseEvidenceIndexLimits", "CodebaseEvidenceRecord", "DEPENDENCY_KINDS"]
