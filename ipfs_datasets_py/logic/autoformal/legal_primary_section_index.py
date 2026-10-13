"""Bounded exact section lookup over an independently pinned primary candidate.

The temporary SQLite index retains every original candidate row. Its receipt
names the complete input and deterministic census, not SQLite bytes or a local
path. Literal graph relationships remain producer observations; they do not
authenticate official text, equate revisions or confer legal admission.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from . import legal_primary_graph_manifest as manifests
from . import legal_primary_graph_reconstruction as reconstruction

SCHEMA = "legal-primary-section-index/v1"
LOOKUP_SCHEMA = "legal-primary-section-lookup/v1"
DEFAULT_LIMITS = {"max_candidate_bytes": 1024 * 1024 * 1024, "max_line_bytes": 4 * 1024 * 1024,
    "max_rows": 400000, "max_index_bytes": 1536 * 1024 * 1024,
    "max_lookup_rows": 4096, "max_lookup_bytes": 16 * 1024 * 1024}
FALSE_AUTHORITY = dict.fromkeys(("source_authenticity_verified", "source_occurrences_bound",
    "source_semantics_verified", "context_closure_verified", "global_consistency_verified",
    "accepted_graph_view_enabled", "admitted", "formalized", "proof_authority", "training_qualified"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class PrimarySectionIndexError(ValueError):
    """A pinned input, finite bound or current file custody disagrees."""


def _need(ok, message):
    if not ok:
        raise PrimarySectionIndexError(message)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise PrimarySectionIndexError("finite UTF8 JSON required") from error


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate candidate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise PrimarySectionIndexError("bounded canonical candidate JSON required") from error
    _need(type(value) is dict and _wire(value) + b"\n" == raw, "canonical object JSONL required")
    return value


def _identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _path_guard(path, descriptor, expected):
    _need(path.resolve(strict=True) == path and _identity(os.fstat(descriptor)) == expected
          == _identity(path.lstat()), "pinned candidate or index changed or became aliased")


def _limits(value):
    _need(value is None or type(value) is dict, "limits object required")
    supplied = {} if value is None else value
    _need(not set(supplied) - set(DEFAULT_LIMITS), "unknown section index limit")
    result = {key: supplied.get(key, maximum) for key, maximum in DEFAULT_LIMITS.items()}
    for key, limit in result.items():
        _need(type(limit) is int and 1 <= limit <= DEFAULT_LIMITS[key], "finite " + key + " required")
    _need(result["max_index_bytes"] >= 4096 * 4, "index bound must permit four SQLite pages")
    return result


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value), "exact " + label + " SHA256 required")
    return value


def reconstruction_report_sha256(report):
    """Full canonical JSON digest including the existing reconstruction self-seal.

    This optional external pin is distinct from the constructor's mandatory
    ``expected_reconstruction_sha256`` existing report self-seal and from a
    pretty-printed report file's raw byte SHA256.
    """
    _need(type(report) is dict, "reconstruction report object required")
    return _digest(report)


class PrimarySectionIndex:
    """Context-managed, read-only lookup using complete independently pinned input.

    ``expected_reconstruction_sha256`` is the existing reconstruction report's
    canonical internal seal, retained independently by the caller. The candidate
    SHA is also mandatory and independent. Entering streams all candidate rows;
    subsequent bounded lookups reuse the same guarded temporary database.
    """

    def __init__(self, candidate_path, *, reconstruction_report, expected_candidate_sha256,
                 expected_reconstruction_sha256, limits=None):
        self._path = Path(candidate_path).absolute()
        self._report = deepcopy(reconstruction_report)
        self._expected_candidate = _sha(expected_candidate_sha256, "candidate")
        self._expected_report = _sha(expected_reconstruction_sha256, "reconstruction report")
        self._limits = _limits(limits)
        self._stream = self._temporary = self._scratch_fd = self._db = self._db_fd = None
        self._database_owned_identity = None
        self._receipt = self._primary_identity = None
        self._entered = False

    @property
    def receipt(self):
        self.guard()
        return deepcopy(self._receipt)

    @property
    def index_sha256(self):
        self.guard()
        return self._receipt["index_sha256"]

    @property
    def primary_identity(self):
        self.guard()
        return deepcopy(self._primary_identity)

    def _report_check(self):
        report = self._report
        _need(type(report) is dict and report.get("schema") == reconstruction.SCHEMA,
              "supported independent reconstruction report required")
        seal = report.get("reconstruction_sha256")
        _need(seal == self._expected_report == _digest({k:v for k,v in report.items() if k != "reconstruction_sha256"}),
              "independently pinned reconstruction report differs")
        _need(report.get("candidate_sha256") == self._expected_candidate, "candidate/report independent pins differ")
        _need(report.get("population_complete") is True and report.get("authority") == reconstruction.FALSE_AUTHORITY,
              "complete inert reconstruction required")
        _need(type(report.get("rows")) is int and 0 < report["rows"] <= self._limits["max_rows"], "candidate row bound exceeded")
        _need(type(report.get("candidate_bytes")) is int and 0 < report["candidate_bytes"] <= self._limits["max_candidate_bytes"],
              "candidate byte bound exceeded")

    def __enter__(self):
        _need(not self._entered, "section index context cannot be reused")
        self._entered = True
        try:
            self._report_check()
            _need(self._path.resolve(strict=True) == self._path, "unaliased candidate path required")
            descriptor = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            self._stream = os.fdopen(descriptor, "rb")
            before = os.fstat(descriptor)
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and before.st_size == self._report["candidate_bytes"], "exact bounded regular candidate required")
            self._candidate_identity = _identity(before)
            _path_guard(self._path, descriptor, self._candidate_identity)
            self._temporary = Path(tempfile.mkdtemp(prefix="legal-primary-section-index-"))
            self._scratch_identity = _identity(self._temporary.lstat())[:3]
            self._scratch_fd = os.open(self._temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            _need(_identity(os.fstat(self._scratch_fd))[:3] == self._scratch_identity,
                  "owned scratch directory changed during acquisition")
            self._db_path = self._temporary / "sections.sqlite"
            self._db = sqlite3.connect(str(self._db_path))
            self._database_owned_identity = _identity(self._db_path.lstat())[:3]
            self._db.execute("PRAGMA page_size=4096")
            self._db.execute("PRAGMA max_page_count=" + str(self._limits["max_index_bytes"] // 4096))
            self._db.execute("PRAGMA cache_size=-8192")
            self._db.execute("PRAGMA temp_store=FILE")
            self._db.execute("PRAGMA journal_mode=OFF")
            self._db.execute("CREATE TABLE rows (ordinal INTEGER PRIMARY KEY,family TEXT,entry TEXT,legal_id TEXT,kind TEXT,src TEXT,dst TEXT,node_key TEXT,label TEXT,payload BLOB)")
            self._db.execute("CREATE INDEX exact_sections ON rows(family,kind,legal_id,ordinal)")
            self._db.execute("CREATE INDEX exact_nodes ON rows(family,entry,ordinal)")
            self._db.execute("CREATE INDEX exact_source_edges ON rows(family,kind,src,ordinal)")
            self._db.execute("CREATE INDEX exact_incoming_source_edges ON rows(family,kind,dst,ordinal)")
            self._build()
            self._db.commit()
            self._db.close()
            self._db = None
            self._db_fd = os.open(self._db_path, os.O_RDONLY | os.O_NOFOLLOW)
            self._database_identity = _identity(os.fstat(self._db_fd))
            _need(self._database_identity[4] <= self._limits["max_index_bytes"], "section index disk bound exceeded")
            self._db = sqlite3.connect("file:/proc/self/fd/" + str(self._db_fd) + "?mode=ro&immutable=1", uri=True)
            self._db.execute("PRAGMA query_only=ON")
            self.guard()
            return self
        except (sqlite3.Error, KeyError, TypeError) as error:
            self.close()
            raise PrimarySectionIndexError("bounded complete section index construction failed") from error
        except BaseException:
            self.close()
            raise

    def _line(self):
        raw = self._stream.readline(self._limits["max_line_bytes"] + 1)
        _need(len(raw) <= self._limits["max_line_bytes"], "candidate line byte bound exceeded")
        return raw

    def _build(self):
        file_hash = hashlib.sha256()
        row_hash = hashlib.sha256(b"legal-primary-graph-candidate-rows/v1\x00")
        first = self._line()
        header = _parse(first)
        _need(header.get("schema") == reconstruction.HEADER_SCHEMA
              and header.get("authority") == reconstruction.FALSE_AUTHORITY, "inert primary candidate header required")
        selected = header["selection"]
        selected = manifests._selection(selected, self._report["selection_sha256"])
        _need(header.get("selected_source_files") == reconstruction._selected_sources(self._report["source_verification"]),
              "candidate selected-file custody differs from independent report")
        _need(header.get("ordered_population_sha256") == self._report["ordered_population_sha256"],
              "candidate complete population differs from independent report")
        self._primary_identity = {"repository": selected["repository"], "revision": selected["revision"],
            "source_revision": selected["manifest"]["source_revision"], "manifest_sha256": selected["manifest_sha256"],
            "selection_sha256": selected["selection_sha256"], "candidate_sha256": self._expected_candidate,
            "release_point": selected["manifest"]["release_point"]}
        file_hash.update(first)
        total_bytes = len(first)
        families, dispositions, kinds = Counter(), Counter(), {"graph_nodes": Counter(), "graph_edges": Counter()}
        n = 0
        while raw := self._line():
            total_bytes += len(raw)
            _need(total_bytes <= self._limits["max_candidate_bytes"] and n < self._limits["max_rows"], "candidate population bound exceeded")
            row = _parse(raw)
            _need(row.get("schema") == reconstruction.ROW_SCHEMA and type(row.get("global_ordinal")) is int
                  and row["global_ordinal"] == n, "complete ordered candidate row required")
            _need(row.get("candidate_row_sha256") == _digest({k:v for k,v in row.items() if k != "candidate_row_sha256"}),
                  "candidate row digest differs")
            family = row.get("family")
            _need(family in kinds and row.get("authority") == reconstruction.FALSE_AUTHORITY, "inert supported graph row required")
            custody = row.get("custody")
            _need(type(custody) is dict and row.get("custody_sha256") == _digest(custody), "candidate custody seal differs")
            for key in ("repository", "revision", "manifest_sha256", "selection_sha256", "source_revision"):
                _need(custody.get(key) == self._primary_identity[key], "candidate row primary identity differs")
            _need(custody.get("family") == family, "candidate custody family differs")
            body = row.get("original_body")
            body = body if type(body) is dict else {}
            identity = row.get("declared_identity")
            _need(type(identity) is dict, "candidate declared identity object required")
            kind = body.get("node_type" if family == "graph_nodes" else "edge_type")
            text = lambda value: value if type(value) is str else None
            self._db.execute("INSERT INTO rows VALUES (?,?,?,?,?,?,?,?,?,?)", (n, family, text(identity.get("entry_cid")),
                text(row.get("legal_id")), text(kind), text(identity.get("source_entry_cid")), text(identity.get("target_entry_cid")),
                text(body.get("node_key")), text(body.get("label")), raw))
            families[family] += 1
            dispositions[row["disposition"]] += 1
            if type(kind) is str and kind:
                kinds[family][kind] += 1
            file_hash.update(raw)
            reconstruction._stream_update(row_hash, raw)
            n += 1
        _path_guard(self._path, self._stream.fileno(), self._candidate_identity)
        _need(file_hash.hexdigest() == self._expected_candidate and total_bytes == self._report["candidate_bytes"],
              "complete candidate SHA256/bytes differ from independent pins")
        _need(n == self._report["rows"] and n + 1 == self._report["candidate_lines"]
              and dict(families) == self._report["family_row_counts"]
              and dict(dispositions) == self._report["disposition_counts"]
              and {k:dict(v) for k,v in kinds.items()} == self._report["producer_declared_kind_counts"]
              and row_hash.hexdigest() == self._report["ordered_candidate_rows_sha256"], "complete candidate census differs")
        relationship = self._db.execute("""WITH nodes AS (
            SELECT entry,count(*) AS n,max(kind) AS kind,max(node_key) AS node_key,max(label) AS label FROM rows
            WHERE family='graph_nodes' AND entry IS NOT NULL GROUP BY entry)
            SELECT count(*),coalesce(sum(s.n=1 AND s.kind='section'),0),
                   coalesce(sum(d.n=1 AND d.kind='source_package'),0),
                   coalesce(sum(s.n=1 AND s.kind='section' AND d.n=1 AND d.kind='source_package'),0),
                   coalesce(sum(s.n=1 AND s.kind='section' AND d.n=1 AND d.kind='release_point'
                                AND d.node_key=? AND d.label=?),0)
            FROM rows e LEFT JOIN nodes s ON s.entry=e.src LEFT JOIN nodes d ON d.entry=e.dst
            WHERE e.family='graph_edges' AND e.kind='HAS_SOURCE'""",
            ("release_point:" + self._primary_identity["release_point"], self._primary_identity["release_point"])).fetchone()
        relationship_census = dict(zip(("all_declared_has_source_rows", "unique_section_source_rows",
            "unique_source_package_target_rows", "typed_section_to_source_package_rows", "recognized_section_release_point_rows"), relationship))
        relationship_census["non_source_package_directed_relationship_rows"] = relationship[0] - relationship[3]
        relationship_census["other_or_unresolved_directed_relationship_rows"] = relationship[0] - relationship[3] - relationship[4]
        receipt = {"schema": SCHEMA, "primary_identity": self._primary_identity,
            "reconstruction_sha256": self._expected_report, "candidate_bytes": total_bytes, "rows": n,
            "family_row_counts": dict(sorted(families.items())), "disposition_counts": dict(sorted(dispositions.items())),
            "producer_declared_kind_counts": {k:dict(sorted(v.items())) for k,v in kinds.items()},
            "has_source_relationship_census": relationship_census,
            "ordered_candidate_rows_sha256": row_hash.hexdigest(), "all_original_candidate_rows_retained": True,
            "coverage_scope": "exact_independently_pinned_primary_candidate_population_only",
            "lookup_profile": "literal_section_HAS_SOURCE_package_and_exact_manifest_release_point/v2",
            "index_identity_scope": "deterministic_input_and_census_receipt_not_SQLite_bytes_or_local_paths",
            "limits": dict(self._limits), "authority": dict(FALSE_AUTHORITY)}
        receipt["index_sha256"] = _digest(receipt)
        self._receipt = receipt
        self._frozen_receipt = _wire(receipt)
        self._frozen_primary_identity = _wire(self._primary_identity)

    def guard(self):
        """Recheck retained source FD/path and immutable local database custody."""
        _need(self._db is not None and self._stream is not None and self._db_fd is not None,
              "active guarded section index context required")
        _need(_wire(self._receipt) == self._frozen_receipt
              and _wire(self._primary_identity) == self._frozen_primary_identity,
              "retained section index metadata differs from frozen input identity")
        _path_guard(self._path, self._stream.fileno(), self._candidate_identity)
        _path_guard(self._db_path, self._db_fd, self._database_identity)
        _need(self._db.execute("PRAGMA query_only").fetchone() == (1,), "section index must remain query-only")
        return True

    def _final_candidate_check(self):
        self.guard()
        self._stream.seek(0)
        sha, size = hashlib.sha256(), 0
        while raw := self._stream.read(min(1024 * 1024, self._limits["max_candidate_bytes"] - size + 1)):
            size += len(raw)
            _need(size <= self._limits["max_candidate_bytes"], "candidate changed beyond byte bound at context exit")
            sha.update(raw)
        _need((sha.hexdigest(), size) == (self._expected_candidate, self._report["candidate_bytes"]),
              "candidate complete SHA256 differs at context exit")
        self.guard()

    def lookup_sections(self, legal_id):
        """Return every literal candidate and relationship; never select an alias."""
        self.guard()
        _need(type(legal_id) is str and 0 < len(legal_id.encode("utf-8")) <= 4096 and "\x00" not in legal_id,
              "bounded literal legal identity required")
        budget = {"rows": 0, "bytes": 0}
        def query(sql, args):
            cursor = self._db.execute(sql, args)
            result = []
            for (raw,) in cursor:
                budget["rows"] += 1; budget["bytes"] += len(raw)
                _need(budget["rows"] <= self._limits["max_lookup_rows"] and budget["bytes"] <= self._limits["max_lookup_bytes"],
                      "complete section lookup bound exceeded; truncation refused")
                result.append(json.loads(raw))
            return result
        rows = query("SELECT payload FROM rows WHERE family='graph_nodes' AND kind='section' AND legal_id=? ORDER BY ordinal", (legal_id,))
        sections = []
        for row in rows:
            entry = row["declared_identity"]["entry_cid"]
            issues = []
            if row["identity_resolution"]["status"] != "unique_declared_identity": issues.append({"code":"section_identity_not_unique"})
            if row["disposition"] != "proposed_unreviewed_transport":
                issues.append({"code":"section_transport_quarantined", "row_ordinal":row["global_ordinal"], "disposition":row["disposition"]})
            edges = query("SELECT payload FROM rows WHERE family='graph_edges' AND kind='HAS_SOURCE' AND src=? ORDER BY ordinal", (entry,)) if entry is not None else []
            incoming = query("SELECT payload FROM rows WHERE family='graph_edges' AND kind='HAS_SOURCE' AND dst=? ORDER BY ordinal", (entry,)) if entry is not None else []
            packages, package_slots, release_points, release_slots, others = [], {}, [], {}, []
            for edge in edges:
                if edge["disposition"] != "proposed_unreviewed_transport":
                    issues.append({"code":"has_source_transport_quarantined", "edge_ordinal":edge["global_ordinal"], "disposition":edge["disposition"]})
                target = edge["declared_identity"]["target_entry_cid"]
                targets = query("SELECT payload FROM rows WHERE family='graph_nodes' AND entry=? ORDER BY ordinal", (target,)) if target is not None else []
                if len(targets) != 1: issues.append({"code":"has_source_target_not_unique", "edge_ordinal":edge["global_ordinal"], "candidate_count":len(targets)})
                for item in targets:
                    if item["original_body"].get("node_type") == "source_package":
                        if item["disposition"] != "proposed_unreviewed_transport":
                            issues.append({"code":"source_package_transport_quarantined", "row_ordinal":item["global_ordinal"], "disposition":item["disposition"]})
                        ordinal = item["global_ordinal"]
                        if ordinal not in package_slots:
                            package_slots[ordinal] = {"entry_cid":item["declared_identity"]["entry_cid"],
                                "source_package_observation":item, "has_source_observations":[]}
                            packages.append(package_slots[ordinal])
                        package_slots[ordinal]["has_source_observations"].append(deepcopy(edge))
                    elif item["original_body"].get("node_type") == "release_point":
                        body = item["original_body"]
                        healthy = item["disposition"] == "proposed_unreviewed_transport"
                        unique = len(targets) == 1 and item["identity_resolution"]["status"] == "unique_declared_identity"
                        exact = body.get("node_key") == "release_point:" + self._primary_identity["release_point"] and body.get("label") == self._primary_identity["release_point"]
                        if not healthy:
                            issues.append({"code":"release_point_transport_quarantined", "row_ordinal":item["global_ordinal"], "disposition":item["disposition"]})
                        if not unique:
                            issues.append({"code":"release_point_target_not_unique", "row_ordinal":item["global_ordinal"]})
                        if not exact:
                            issues.append({"code":"release_point_target_manifest_identity_mismatch", "row_ordinal":item["global_ordinal"]})
                        if healthy and unique and exact:
                            ordinal = item["global_ordinal"]
                            if ordinal not in release_slots:
                                release_slots[ordinal] = {"entry_cid":item["declared_identity"]["entry_cid"],
                                    "release_point_observation":item, "has_source_observations":[]}
                                release_points.append(release_slots[ordinal])
                            release_slots[ordinal]["has_source_observations"].append(deepcopy(edge))
                        else:
                            others.append(item)
                    else:
                        others.append(item)
                        issues.append({"code":"has_source_target_other_node_kind", "edge_ordinal":edge["global_ordinal"], "target_ordinal":item["global_ordinal"]})
            if not edges: issues.append({"code":"section_has_no_declared_has_source"})
            if not packages: issues.append({"code":"section_has_no_declared_source_package"})
            sections.append({"entry_cid":entry, "legal_id":row["legal_id"], "section_observation":row,
                "has_source_observations":edges, "incoming_has_source_observations":incoming,
                "source_packages":packages, "release_points":release_points,
                "other_source_targets":others, "issues":issues})
        result = {"schema": LOOKUP_SCHEMA, "legal_id":legal_id, "index_sha256":self._receipt["index_sha256"],
            "primary_identity":deepcopy(self._primary_identity), "sections":sections,
            "issues":[] if len(sections)==1 else [{"code":"literal_section_not_unique", "candidate_count":len(sections)}],
            "authority":dict(FALSE_AUTHORITY)}
        _need(len(_wire(result)) <= self._limits["max_lookup_bytes"], "complete section lookup response byte bound exceeded")
        self.guard()
        return result

    def close(self):
        if self._db is not None:
            self._db.close(); self._db = None
        if self._db_fd is not None:
            os.close(self._db_fd); self._db_fd = None
        if self._stream is not None:
            self._stream.close(); self._stream = None
        if self._temporary is not None:
            # Remove only the original owned database inode. A replacement or
            # aliased scratch directory is never recursively deleted.
            if self._scratch_fd is not None:
                try:
                    current = os.stat("sections.sqlite", dir_fd=self._scratch_fd, follow_symlinks=False)
                    if _identity(current)[:3] == self._database_owned_identity:
                        os.unlink("sections.sqlite", dir_fd=self._scratch_fd)
                except FileNotFoundError:
                    pass
                finally:
                    os.close(self._scratch_fd); self._scratch_fd = None
            try:
                if self._temporary.resolve(strict=True) == self._temporary and _identity(self._temporary.lstat())[:3] == self._scratch_identity:
                    self._temporary.rmdir()
            except (FileNotFoundError, OSError):
                pass
            self._temporary = None

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None: self._final_candidate_check()
        finally:
            self.close()


__all__ = ["PrimarySectionIndex", "PrimarySectionIndexError", "reconstruction_report_sha256",
           "DEFAULT_LIMITS", "FALSE_AUTHORITY"]
