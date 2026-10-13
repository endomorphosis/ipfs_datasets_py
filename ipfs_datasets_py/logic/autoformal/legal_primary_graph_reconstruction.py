"""Streaming, manifest-selected primary graph transport with exact row lineage.

Every selected row remains a candidate observation, including quarantine rows.
Original raw bytes stay in independently verified immutable source files; the
candidate also retains the decoder's entire parsed body without interpreting it.
Identity and endpoint integrity never establishes legal semantics or admission.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import tempfile

from . import legal_primary_graph_manifest as manifests
from . import legal_primary_graph_records as records

SCHEMA = "legal-primary-graph-reconstruction/v1"
HEADER_SCHEMA = "legal-primary-graph-candidate-header/v1"
ROW_SCHEMA = "legal-primary-graph-candidate-row/v1"
MAX_SCRATCH_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_ISSUE_KINDS = 256
_MANIFEST_LIMITS = {"max_files", "max_rows", "max_file_bytes", "max_total_file_bytes",
    "max_row_group_bytes", "max_decoded_bytes", "batch_size", "max_batch_bytes", "max_row_bytes", "max_extra_files"}
_LOCAL_LIMITS = {"max_scratch_bytes": MAX_SCRATCH_BYTES, "max_output_bytes": MAX_OUTPUT_BYTES,
                 "max_line_bytes": MAX_LINE_BYTES}
FALSE_AUTHORITY = dict.fromkeys(("admitted", "formalized", "source_semantics_verified", "semantic_review_verified",
    "source_occurrences_bound", "globally_consistent", "proof_authority", "training_qualified",
    "accepted_graph_view_enabled", "published", "surface_labels_merged"), False)


class PrimaryGraphReconstructionError(ValueError):
    """Immutable custody, complete population or a finite reconstruction bound disagrees."""


def _need(condition, message):
    if not condition:
        raise PrimaryGraphReconstructionError(message)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise PrimaryGraphReconstructionError("finite canonical UTF8 candidate JSON required") from error


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _limits(value):
    _need(value is None or type(value) is dict, "explicit reconstruction limits object required")
    supplied = {} if value is None else dict(value)
    _need(not set(supplied) - (_MANIFEST_LIMITS | set(_LOCAL_LIMITS)), "unknown reconstruction limit")
    local = {key: supplied.get(key, maximum) for key, maximum in _LOCAL_LIMITS.items()}
    for key, limit in local.items():
        _need(type(limit) is int and 1 <= limit <= _LOCAL_LIMITS[key], "bounded " + key + " required")
    _need(local["max_scratch_bytes"] >= 4 * 4096, "scratch bound must allow four SQLite pages")
    return {key: value for key, value in supplied.items() if key in _MANIFEST_LIMITS}, local


def _output_path(value, snapshot_root, blobs_root):
    path = Path(value).absolute()
    _need(path.parent.resolve(strict=True) == path.parent and path.parent.is_dir(), "unaliased existing output parent required")
    _need(not path.is_symlink() and not path.exists(), "candidate output already exists; overwrite refused")
    for root in (snapshot_root, blobs_root):
        if root is not None:
            _need(not path.is_relative_to(Path(root).resolve(strict=True)), "candidate output cannot mutate immutable source roots")
    return path, _directory_identity(path.parent.stat())


def _directory_identity(info):
    return info.st_dev, info.st_ino, info.st_mode


def _owned_file(name, descriptor, expected):
    try: current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError: return False
    return _directory_identity(current) == expected


def _unlink_owned(name, descriptor, expected):
    if _owned_file(name, descriptor, expected):
        os.unlink(name, dir_fd=descriptor)


def _guard_parent(path, descriptor, expected):
    _need(path.parent.resolve(strict=True) == path.parent
          and _directory_identity(path.parent.lstat()) == expected == _directory_identity(os.fstat(descriptor)),
          "candidate output parent changed or became aliased")


@contextmanager
def _parent(path, expected):
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _guard_parent(path, descriptor, expected)
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _database(max_bytes):
    with tempfile.TemporaryDirectory(prefix="legal-primary-graph-index-") as temporary:
        db = sqlite3.connect(str(Path(temporary) / "identities.sqlite"))
        try:
            db.execute("PRAGMA page_size=4096")
            db.execute("PRAGMA max_page_count=" + str(max_bytes // 4096))
            db.execute("PRAGMA cache_size=-8192")
            db.execute("PRAGMA temp_store=FILE")
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("CREATE TABLE ids (family TEXT,id TEXT,n INTEGER,variants INTEGER,PRIMARY KEY(family,id)) WITHOUT ROWID")
            db.execute("CREATE TABLE variants (family TEXT,id TEXT,sha TEXT,n INTEGER,PRIMARY KEY(family,id,sha)) WITHOUT ROWID")
            db.execute("CREATE TABLE edges (ordinal INTEGER PRIMARY KEY,src TEXT,dst TEXT,decoded INTEGER)")
            yield db
        except sqlite3.Error as error:
            raise PrimaryGraphReconstructionError("bounded identity scratch failed; no partial candidate") from error
        finally:
            db.close()


def _decode(observation):
    return records.decode_primary_graph_record(observation["raw_row"], custody=observation["custody"],
        expected_raw_row_sha256=observation["raw_row_sha256"],
        expected_custody_sha256=observation["custody_sha256"])


def _stage_id(db, family, identity, record_sha256):
    existing = db.execute("SELECT n FROM variants WHERE family=? AND id=? AND sha=?", (family, identity, record_sha256)).fetchone()
    db.execute("INSERT INTO variants VALUES (?,?,?,1) ON CONFLICT(family,id,sha) DO UPDATE SET n=n+1", (family, identity, record_sha256))
    db.execute("INSERT INTO ids VALUES (?,?,1,1) ON CONFLICT(family,id) DO UPDATE SET n=n+1,variants=variants+?",
               (family, identity, 1 if existing is None else 0))


def _stage(db, observation, envelope):
    family, disposition = envelope["family"], envelope["disposition"]
    identity = envelope["declared_identity"]
    decoded = disposition in ("decoded_unreviewed_node", "decoded_unreviewed_edge")
    if decoded:
        _stage_id(db, family, identity["entry_cid"], envelope["record_sha256"])
    if family == "graph_edges":
        db.execute("INSERT INTO edges VALUES (?,?,?,?)", (observation["global_ordinal"],
            identity["source_entry_cid"] if decoded else None, identity["target_entry_cid"] if decoded else None, int(decoded)))


def _identity_resolution(db, envelope):
    identity = envelope["declared_identity"]["entry_cid"]
    if envelope["disposition"] == "unresolved":
        return {"status": "unresolved_record", "instances": 0, "distinct_record_variants": 0}
    row = db.execute("SELECT n,variants FROM ids WHERE family=? AND id=?", (envelope["family"], identity)).fetchone()
    _need(row is not None, "second-pass identity absent from complete first pass")
    opposite = "graph_edges" if envelope["family"] == "graph_nodes" else "graph_nodes"
    other = db.execute("SELECT 1 FROM ids WHERE family=? AND id=? LIMIT 1", (opposite, identity)).fetchone()
    status = "cross_family_identity_collision" if other else "conflicting_identity" if row[1] > 1 else "duplicate_identical_identity" if row[0] > 1 else "unique_declared_identity"
    return {"status": status, "instances": row[0], "distinct_record_variants": row[1]}


def _endpoint(count, decoded, collision):
    return "unresolved_record" if not decoded else "missing" if count is None else "conflicting_declared_identity" if collision else "ambiguous" if count != 1 else "unique_declared_node"


def _endpoint_resolution(db, ordinal):
    row = db.execute("""SELECT e.decoded,s.n,d.n,
        EXISTS(SELECT 1 FROM ids x WHERE x.family='graph_edges' AND x.id=e.src),
        EXISTS(SELECT 1 FROM ids x WHERE x.family='graph_edges' AND x.id=e.dst) FROM edges e
        LEFT JOIN ids s ON s.family='graph_nodes' AND s.id=e.src
        LEFT JOIN ids d ON d.family='graph_nodes' AND d.id=e.dst WHERE e.ordinal=?""", (ordinal,)).fetchone()
    _need(row is not None, "second-pass edge absent from complete first pass")
    return {"source": _endpoint(row[1], row[0], row[3]), "target": _endpoint(row[2], row[0], row[4])}


def _row_status(envelope, identity, endpoints):
    if envelope["disposition"] == "unresolved": return "quarantined_unresolved_record"
    if identity["status"] != "unique_declared_identity": return "quarantined_identity_conflict_or_duplicate"
    if endpoints and any(value != "unique_declared_node" for value in endpoints.values()):
        return "quarantined_unresolved_or_ambiguous_endpoint"
    return "proposed_unreviewed_transport"


def _count(counter, key):
    _need(type(key) is str and (key in counter or len(counter) < MAX_ISSUE_KINDS), "bounded distinct census labels required")
    counter[key] += 1


def _identity_summary(db):
    result = {}
    for family in ("graph_nodes", "graph_edges"):
        row = db.execute("""SELECT count(*),coalesce(sum(n),0),
            coalesce(sum(CASE WHEN n=1 THEN 1 ELSE 0 END),0),
            coalesce(sum(CASE WHEN n>1 THEN 1 ELSE 0 END),0),coalesce(sum(n-1),0),
            coalesce(sum(CASE WHEN variants>1 THEN 1 ELSE 0 END),0)
            FROM ids WHERE family=?""", (family,)).fetchone()
        result[family] = dict(zip(("distinct_ids", "decoded_rows", "unique_identity_ids", "duplicate_identity_ids",
                                  "duplicate_identity_extra_instances", "conflicting_identity_ids"), row))
    result["cross_family_identity_collisions"] = db.execute("""SELECT count(*) FROM ids n
        JOIN ids e ON n.id=e.id WHERE n.family='graph_nodes' AND e.family='graph_edges'""").fetchone()[0]
    return result


def _scan_token(observation, envelope):
    return _wire({"global_ordinal": observation["global_ordinal"], "custody_sha256": observation["custody_sha256"],
                  "raw_row_sha256": observation["raw_row_sha256"], "decoder_envelope_sha256": envelope["envelope_sha256"]})


def _stream_update(stream, raw):
    stream.update(len(raw).to_bytes(8, "big") + raw)


def _selected_sources(verified):
    """Content custody excludes location and unselected generation observations."""
    value = {"schema": "legal-primary-graph-selected-files-custody/v1",
        **{key: verified[key] for key in ("selection_sha256", "manifest_sha256", "repository", "revision",
            "selected_file_count", "selected_row_count", "files", "status", "authority", "descriptor_key_ranges_verified")},
        "limits": {key: value for key, value in verified["limits"].items() if key != "max_extra_files"}}
    return {**value, "selected_files_sha256": _digest(value)}


def reconstruct_to_jsonl(selection, snapshot_root, output_path, *, expected_selection_sha256,
                         blobs_root=None, limits=None):
    """Export every selected row atomically to a NEW candidate path, never overwrite.

    The header retains the complete selected manifest and selected-file receipt.
    Each canonical JSONL row retains entire parsed properties, exact raw-row and
    original record-byte hashes, decoder identity and physical source custody.
    Original raw rows remain in immutable files, with no deduplication/filtering.
    Two bounded passes check global endpoint integrity without population RAM.
    The returned report excludes output paths, clocks and temporary filenames.
    """
    owner_limits, local = _limits(limits)
    path, parent_identity = _output_path(output_path, snapshot_root, blobs_root)
    selected = json.loads(_wire(selection))  # Detach caller-owned mutable metadata.
    verified = manifests.verify_primary_graph_files(selected, snapshot_root,
        expected_selection_sha256=expected_selection_sha256, blobs_root=blobs_root, limits=owner_limits)
    arguments = dict(expected_selection_sha256=expected_selection_sha256, blobs_root=blobs_root, limits=owner_limits)
    expected_rows = verified["selected_row_count"]
    families, decoder_dispositions, issues = Counter(), Counter(), Counter()
    declared_kinds = {family: Counter() for family in ("graph_nodes", "graph_edges")}
    missing_kinds = Counter()
    first = hashlib.sha256(b"legal-primary-graph-decoded-population/v1\x00")
    temporary = None
    temporary_identity = None
    with _parent(path, parent_identity) as parent_fd, _database(local["max_scratch_bytes"]) as db:
        count = 0
        for observation in manifests.iter_verified_graph_rows(selected, snapshot_root, **arguments):
            _need(observation["global_ordinal"] == count, "first-pass population order or multiplicity differs")
            envelope = _decode(observation)
            _need(envelope["family"] in ("graph_nodes", "graph_edges"), "unexpected decoded graph family")
            _stage(db, observation, envelope)
            _count(families, envelope["family"]); _count(decoder_dispositions, envelope["disposition"])
            body = envelope["original_body"]
            kind = body.get("node_type" if envelope["family"] == "graph_nodes" else "edge_type") if type(body) is dict else None
            if type(kind) is str and kind.strip() and len(kind.encode("utf-8")) <= records.MAX_TEXT:
                _count(declared_kinds[envelope["family"]], kind)
            else: missing_kinds[envelope["family"]] += 1
            for issue in envelope["issues"]: _count(issues, issue["code"])
            _stream_update(first, _scan_token(observation, envelope))
            count += 1
        _need(count == expected_rows, "first-pass population differs from exact verified files")
        identity_summary = _identity_summary(db)
        selected_sources = _selected_sources(verified)
        header = {"schema": HEADER_SCHEMA, "selection": selected, "selected_source_files": selected_sources,
            "raw_payload_location": "immutable_verified_source_files_at_exact_per_record_custody",
            "ordered_population_sha256": first.hexdigest(), "status": "proposed_unreviewed_transport_only",
            "authority": dict(FALSE_AUTHORITY)}
        output_hash, row_hash = hashlib.sha256(), hashlib.sha256(b"legal-primary-graph-candidate-rows/v1\x00")
        output_bytes, emitted = 0, 0
        dispositions, identity_statuses = Counter(), Counter()
        endpoint_counts = {key: Counter() for key in ("source", "target")}
        second = hashlib.sha256(b"legal-primary-graph-decoded-population/v1\x00")
        try:
            _guard_parent(path, parent_fd, parent_identity)
            proposed_name = ".legal-primary-graph-" + secrets.token_hex(16)
            descriptor = os.open(proposed_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            temporary, temporary_identity = proposed_name, _directory_identity(os.fstat(descriptor))
            with os.fdopen(descriptor, "wb") as stream:
                def write(value):
                    nonlocal output_bytes
                    raw = _wire(value) + b"\n"
                    _need(len(raw) <= local["max_line_bytes"] and output_bytes + len(raw) <= local["max_output_bytes"],
                          "candidate line or cumulative output byte bound exceeded; no partial export")
                    stream.write(raw); output_hash.update(raw); output_bytes += len(raw)
                    return raw
                write(header)
                for observation in manifests.iter_verified_graph_rows(selected, snapshot_root, **arguments):
                    _need(observation["global_ordinal"] == emitted, "second-pass population order or multiplicity differs")
                    envelope = _decode(observation)
                    _stream_update(second, _scan_token(observation, envelope))
                    identity = _identity_resolution(db, envelope)
                    endpoints = _endpoint_resolution(db, emitted) if envelope["family"] == "graph_edges" else None
                    disposition = _row_status(envelope, identity, endpoints)
                    _count(dispositions, disposition); _count(identity_statuses, identity["status"])
                    if endpoints:
                        for key, value in endpoints.items(): _count(endpoint_counts[key], value)
                    row = {"schema": ROW_SCHEMA, "global_ordinal": emitted,
                        "family": envelope["family"], "legal_id": envelope["legal_id"],
                        "custody": envelope["custody"], "custody_sha256": envelope["custody_sha256"],
                        "raw_row_sha256": envelope["raw_row_sha256"], "record_sha256": envelope["record_sha256"],
                        "decoder_envelope_sha256": envelope["envelope_sha256"],
                        "original_body": envelope["original_body"], "declared_identity": envelope["declared_identity"],
                        "decoder_disposition": envelope["disposition"], "decoder_issues": envelope["issues"],
                        "identity_resolution": identity, "endpoint_resolution": endpoints,
                        "disposition": disposition, "authority": dict(FALSE_AUTHORITY)}
                    row["candidate_row_sha256"] = _digest(row)
                    _stream_update(row_hash, write(row))
                    emitted += 1
                _need(emitted == expected_rows and second.hexdigest() == first.hexdigest(),
                      "complete decoded population changed between passes")
                final_sources = manifests.verify_primary_graph_files(selected, snapshot_root, **arguments)
                _need(_wire(final_sources) == _wire(verified), "source files or excluded inventory changed during reconstruction")
                stream.flush(); os.fsync(stream.fileno())
            _need(sum(dispositions.values()) == expected_rows, "candidate dispositions omit source rows")
            _need(all(sum(values.values()) == families.get("graph_edges", 0) for values in endpoint_counts.values()),
                  "endpoint census omits edge observations")
            blockers = []
            if decoder_dispositions.get("unresolved", 0): blockers.append("unresolved_source_records")
            for family in ("graph_nodes", "graph_edges"):
                if identity_summary[family]["duplicate_identity_ids"]: blockers.append(family + "_duplicate_identity")
                if identity_summary[family]["conflicting_identity_ids"]: blockers.append(family + "_conflicting_identity")
            if identity_summary["cross_family_identity_collisions"]: blockers.append("cross_family_identity_collision")
            for side, counts in endpoint_counts.items():
                for status in ("missing", "ambiguous", "conflicting_declared_identity", "unresolved_record"):
                    if counts.get(status, 0): blockers.append(side + "_endpoint_" + status)
            report = {"schema": SCHEMA, "selection_sha256": expected_selection_sha256,
                "manifest_sha256": verified["manifest_sha256"], "source_verification": verified,
                "selected_files_sha256": selected_sources["selected_files_sha256"],
                "limits": {**verified["limits"], **local}, "rows": emitted,
                "family_row_counts": dict(sorted(families.items())),
                "decoder_disposition_counts": dict(sorted(decoder_dispositions.items())),
                "decoder_issue_counts": dict(sorted(issues.items())), "identity_census": identity_summary,
                "producer_declared_kind_counts": {key: dict(sorted(value.items())) for key, value in declared_kinds.items()},
                "missing_or_invalid_producer_kind_rows": {key: missing_kinds[key] for key in declared_kinds},
                "identity_status_counts": dict(sorted(identity_statuses.items())),
                "endpoint_counts": {key: dict(sorted(values.items())) for key, values in endpoint_counts.items()},
                "disposition_counts": dict(sorted(dispositions.items())),
                "ordered_population_sha256": first.hexdigest(), "ordered_candidate_rows_sha256": row_hash.hexdigest(),
                "candidate_sha256": output_hash.hexdigest(), "candidate_bytes": output_bytes,
                "candidate_lines": emitted + 1, "candidate_encoding": "canonical_UTF8_JSONL_header_then_all_rows_in_manifest_order",
                "population_complete": True, "coverage_scope": "exact_manifest_selected_primary_graph_rows_only",
                "excluded_files_scope": "separate_inventory_observations_only_no_body_verification_or_generation_merging",
                "endpoint_integrity_passed": not blockers, "blockers": sorted(blockers),
                "endpoint_resolution_scope": "unique_decoded_node_declarations_only_unresolved_rows_remain_global_blockers",
                "original_task_acceptance": "preparatory_subset_only", "authority": dict(FALSE_AUTHORITY)}
            report["reconstruction_sha256"] = _digest(report)
            # Same-filesystem link is atomic and exclusive; existing files survive.
            _guard_parent(path, parent_fd, parent_identity)
            _need(_owned_file(temporary, parent_fd, temporary_identity), "owned candidate temporary was replaced")
            try: os.link(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
            except FileExistsError as error:
                raise PrimaryGraphReconstructionError("candidate output appeared; overwrite refused") from error
            try:
                _guard_parent(path, parent_fd, parent_identity)
                _need(_owned_file(path.name, parent_fd, temporary_identity), "published candidate was replaced")
                os.fsync(parent_fd)
            except BaseException:
                _unlink_owned(path.name, parent_fd, temporary_identity)
                raise
            return json.loads(_wire(report))
        finally:
            if temporary is not None:
                _unlink_owned(temporary, parent_fd, temporary_identity)


def _candidate_hash(path, max_bytes):
    path = Path(path).absolute()
    _need(path.resolve(strict=True) == path, "candidate input path is aliased")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= max_bytes, "bounded regular candidate required")
        digest, count = hashlib.sha256(), 0
        while raw := stream.read(min(1024 * 1024, max_bytes - count + 1)):
            count += len(raw); _need(count <= max_bytes, "candidate grew beyond byte bound"); digest.update(raw)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        _need(identity(before) == identity(os.fstat(stream.fileno())) == identity(path.lstat()), "candidate changed during replay")
    return digest.hexdigest(), count


def validate_reconstruction(report, selection, snapshot_root, candidate_path, *, expected_selection_sha256,
                            blobs_root=None, limits=None):
    """Rebuild from independent selected source inputs; a resealed report cannot pass."""
    _, local = _limits(limits)
    actual = _candidate_hash(candidate_path, local["max_output_bytes"])
    with tempfile.TemporaryDirectory(prefix="legal-primary-graph-replay-") as temporary:
        expected = reconstruct_to_jsonl(selection, snapshot_root, Path(temporary) / "candidate.jsonl",
            expected_selection_sha256=expected_selection_sha256, blobs_root=blobs_root, limits=limits)
    _need(_wire(report) == _wire(expected), "reconstruction differs from independent complete source replay")
    _need(actual == (expected["candidate_sha256"], expected["candidate_bytes"]), "candidate bytes differ from independent reconstruction")
    _need(_candidate_hash(candidate_path, local["max_output_bytes"]) == actual, "candidate moved during source replay")
    return expected


__all__ = ["PrimaryGraphReconstructionError", "reconstruct_to_jsonl", "validate_reconstruction"]
