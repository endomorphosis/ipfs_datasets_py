"""Pinned source-package metadata and declaration reconciliation, without tables.

The primary manifest owner validates release identity and graph descriptors.
Companion mismatches remain observations; this selected metadata operation never
authenticates a remote revision, binds historical spans, or verifies table rows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import legal_paired_manifest_inventory_v1 as ordinary

REQUEST_SCHEMA = "legal-source-package-intake-request/v1"
SCHEMA = "legal-source-package-intake/v1"
REPOSITORY = "justicedao/ipfs_uscode"
FILES = ("manifest.json", "release_metadata.json", "dataset_configs.json", "dataset_infos.json", "README.md")
MAX_REQUEST_BYTES = 256 * 1024
MAX_METADATA_BYTES = 2 * 1024**2
MAX_METADATA_TOTAL_BYTES = 4 * 1024**2
MAX_REPORT_BYTES = 8 * 1024**2
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ORDINARY_PIN = hashlib.sha256(Path(ordinary.__file__).read_bytes()).hexdigest()
AUTHORITY = dict.fromkeys((
    "remote_revision_authenticated", "remote_inventory_exhaustive", "corpus_inventory_exhaustive",
    "complete_release_integrity_verified", "table_bodies_verified", "Arrow_schemas_verified",
    "table_rows_verified", "source_occurrences_bound", "source_aliases_mapped",
    "source_authority_authenticated", "source_currentness_verified", "source_semantics_verified",
    "semantic_review_verified", "globally_consistent", "accepted", "admitted", "formalized",
    "proof_authority", "Lean_admitted", "training_qualified", "evaluation_gold_qualified",
    "model_executed", "training_executed", "native_build_executed", "enqueued", "published",
), False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _preflight(request_raw, metadata_bytes, expected_request_sha256):
    ordinary._digest(expected_request_sha256, "source package request")
    ordinary._need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES,
                   "bounded exact source package request bytes required")
    ordinary._need(_sha(request_raw) == expected_request_sha256, "source package request SHA256 mismatch")
    request = ordinary._read_json(request_raw, MAX_REQUEST_BYTES, "source package request")
    ordinary._keys(request, {"schema", "repository_id", "revision", "expected_release_identity",
                            "expected_graph_population", "files"}, "source package request")
    ordinary._need(request["schema"] == REQUEST_SCHEMA and request["repository_id"] == REPOSITORY,
                   "unsupported source package request profile")
    ordinary._need(type(request["revision"]) is str and _REVISION.fullmatch(request["revision"]),
                   "immutable lowercase forty-hex source Hub revision required")
    ordinary._need(type(request["files"]) is list and len(request["files"]) == len(FILES),
                   "exact five-file ordered metadata selection required")
    ordinary._need(type(metadata_bytes) is dict and all(type(key) is str for key in metadata_bytes),
                   "ordinary exact metadata byte mapping required")
    seen, total = set(), 0
    for entry in request["files"]:
        ordinary._keys(entry, {"path_in_repo", "bytes", "sha256"}, "source metadata descriptor")
        path, size = entry["path_in_repo"], entry["bytes"]
        ordinary._need(type(path) is str and path in FILES and path not in seen,
                       "unsupported or duplicate exact source metadata path")
        seen.add(path)
        ordinary._need(type(size) is int and 0 < size <= MAX_METADATA_BYTES,
                       "bounded exact source metadata file bytes required")
        total += size
        ordinary._need(total <= MAX_METADATA_TOTAL_BYTES, "source metadata aggregate byte bound exceeded")
        ordinary._digest(entry["sha256"], "source metadata file")
    ordinary._need(seen == set(FILES) == set(metadata_bytes), "exact source metadata mapping population differs")
    captured, parsed = {}, {}
    for entry in request["files"]:
        path, raw = entry["path_in_repo"], metadata_bytes[entry["path_in_repo"]]
        ordinary._need(type(raw) is bytes and len(raw) == entry["bytes"] and _sha(raw) == entry["sha256"],
                       "source metadata bytes or SHA256 mismatch: " + path)
        if path != "README.md":
            parsed[path] = ordinary._read_json(raw, MAX_METADATA_BYTES, path)
            ordinary._need(type(parsed[path]) is dict, "source metadata JSON object required: " + path)
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeError as error:
                raise ValueError("exact UTF8 source README required") from error
            ordinary._wire(text, MAX_REPORT_BYTES)
        captured[path] = raw
    return request, captured, parsed


def _owners():
    from . import legal_primary_graph_manifest as primary

    root = Path(__file__).resolve().parent
    paths = [Path(__file__).resolve(), Path(ordinary.__file__).resolve(), Path(primary.__file__).resolve()]
    ordinary._need(all(path.parent == root for path in paths), "source intake owner escaped selected source tree")
    pins = {str(path): _sha(path.read_bytes()) for path in paths}
    ordinary._need(pins[str(paths[0])] == _SELF_PIN and pins[str(paths[1])] == _ORDINARY_PIN,
                   "source intake or ordinary JSON owner changed since import")
    return primary, pins


def _companion_checks(manifest, captured, parsed):
    descriptors = {entry["relative_path"]: entry for entry in manifest["artifacts"]}
    comparisons, issues = [], []
    for path in FILES[1:]:
        descriptor, raw = descriptors.get(path), captured[path]
        size_matches = descriptor is not None and len(raw) == descriptor["size_bytes"]
        hash_matches = descriptor is not None and _sha(raw) == descriptor["sha256"]
        disposition = ("descriptor_missing" if descriptor is None else
                       "descriptor_match" if size_matches and hash_matches else "descriptor_mismatch")
        comparisons.append({"path_in_repo": path, "descriptor": descriptor, "observed_bytes": len(raw),
            "observed_sha256": _sha(raw), "size_matches": size_matches, "sha256_matches": hash_matches,
            "disposition": disposition})
        if disposition != "descriptor_match":
            issues.append({"code": "companion_" + disposition, "path_in_repo": path})
    declarations = []
    release = parsed["release_metadata.json"]
    expected = {"dataset_id": REPOSITORY, "schema_version": manifest["hf_release_schema_version"],
                **{key: manifest[key] for key in ("release_profile", "release_point", "release_root_cid",
                    "source_revision", "graph_ontology_version", "producer")}}
    for key, value in expected.items():
        matches = release.get(key) == value
        declarations.append({"path_in_repo": "release_metadata.json", "field": key,
                             "expected": value, "observed": release.get(key), "matches": matches})
        if not matches:
            issues.append({"code": "release_metadata_declaration_mismatch", "field": key})
    for path in ("dataset_configs.json", "dataset_infos.json"):
        matches = parsed[path].get("schema_version") == manifest["hf_release_schema_version"]
        declarations.append({"path_in_repo": path, "field": "schema_version",
            "expected": manifest["hf_release_schema_version"], "observed": parsed[path].get("schema_version"),
            "matches": matches})
        if not matches:
            issues.append({"code": "unsupported_companion_schema", "path_in_repo": path})
    return comparisons, declarations, issues


def _default_config(configs, name):
    if type(configs) is not list or type(name) is not str:
        return None
    matches = [item for item in configs if type(item) is dict and item.get("config_name") == name]
    return matches[0] if len(matches) == 1 else None


def _glob_population(data_files, artifacts):
    """Observe only the supported declared glob; never open paths or glob a disk."""
    supported = (type(data_files) is list and bool(data_files) and
        all(type(item) is dict and item.get("path") == "data/**/*.parquet"
            and item.get("split") == "train" for item in data_files))
    selected = [item for item in artifacts if item["relative_path"].startswith("data/")
                and item["relative_path"].endswith(".parquet")] if supported else []
    return {"data_files": data_files, "supported_glob_profile": supported,
        "physical_descriptor_count": len(selected) if supported else None,
        "physical_descriptor_row_sum": sum(item["row_count"] for item in selected) if supported else None,
        "physical_descriptor_byte_sum": sum(item["size_bytes"] for item in selected) if supported else None,
        "physical_descriptor_paths": [item["relative_path"] for item in selected],
        "scope": "manifest_descriptor_declarations_only_no_file_or_row_reads"}


def _counts(manifest, parsed):
    default = manifest.get("default_config")
    configs, infos = parsed["dataset_configs.json"], parsed["dataset_infos.json"]
    manifest_config = _default_config(manifest.get("configs"), default)
    downloaded_config = _default_config(configs.get("configs"), default)
    manifest_glob = _glob_population(manifest_config.get("data_files") if manifest_config else None,
                                     manifest["artifacts"])
    downloaded_glob = _glob_population(downloaded_config.get("data_files") if downloaded_config else None,
                                       manifest["artifacts"])
    info_configs = infos.get("configs")
    info = info_configs.get(default) if type(info_configs) is dict and type(default) is str else None
    splits = info.get("splits") if type(info) is dict else None
    train = splits.get("train") if type(splits) is dict else None
    advertised = train.get("num_examples") if type(train) is dict else None
    if type(advertised) is not int or advertised < 0:
        advertised = None
    data_rows = manifest_glob["physical_descriptor_row_sum"]
    routing_rows = sum(item["row_count"] for item in manifest["artifacts"] if item["family"] == "routing_index")
    corpus_rows = sum(item["row_count"] for item in manifest["artifacts"] if item["family"] == "corpus")
    delta = advertised - data_rows if advertised is not None and data_rows is not None else None
    config_matches = (manifest_config is not None and downloaded_config is not None
        and configs.get("default_config") == default
        and manifest_glob["data_files"] == downloaded_glob["data_files"])
    if not config_matches or delta is None or not downloaded_glob["supported_glob_profile"]:
        status = "unsupported_or_missing_default_config_declarations"
    elif delta == 0:
        status = "advertised_rows_match_declared_data_glob"
    elif delta == routing_rows:
        status = "row_count_delta_equals_declared_routing_index_rows"
    else:
        status = "row_count_declarations_differ"
    issues = [] if status == "advertised_rows_match_declared_data_glob" else [{"code": status}]
    return {"status": status, "default_config": default,
        "downloaded_default_config": configs.get("default_config"),
        "default_data_files_declarations_match": config_matches,
        "manifest_data_glob": manifest_glob, "downloaded_config_data_glob": downloaded_glob,
        "advertised_train_num_examples": advertised, "advertised_minus_manifest_data_glob_rows": delta,
        "routing_index_declared_rows": routing_rows, "corpus_declared_rows": corpus_rows,
        "delta_equals_routing_index_rows": delta == routing_rows if delta is not None else None,
        "unique_laws": None, "rows_read": 0,
        "meaning": "Distinct declared inventory measures; numerical equality does not attest viewer or unique-law coverage."}, issues


def prepare_source_package_intake(request_raw, metadata_bytes, *, expected_request_sha256):
    """Validate the exact supplied metadata and retain companion discrepancies."""
    request, captured, parsed = _preflight(request_raw, metadata_bytes, expected_request_sha256)
    primary, before = _owners()
    manifest_descriptor = next(item for item in request["files"] if item["path_in_repo"] == "manifest.json")
    selection = primary.select_primary_graph_manifest(captured["manifest.json"],
        expected_manifest_sha256=manifest_descriptor["sha256"], repository=request["repository_id"],
        revision=request["revision"], expected_release_identity=request["expected_release_identity"],
        expected_graph_population=request["expected_graph_population"])
    manifest = selection["manifest"]
    comparisons, declarations, issues = _companion_checks(manifest, captured, parsed)
    counts, count_issues = _counts(manifest, parsed)
    issues.extend(count_issues)
    files = [{"selection_ordinal": ordinal, **entry, "raw_utf8": captured[entry["path_in_repo"]].decode("utf-8")}
             for ordinal, entry in enumerate(request["files"])]
    after = _owners()[1]
    ordinary._need(before == after, "source package operation owners changed during preparation")
    report = {"schema": SCHEMA, "repository_id": REPOSITORY, "revision": request["revision"],
        "revision_evidence": "caller_supplied_acquisition_identity_not_remotely_authenticated",
        "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256, "files": files,
        "companion_metadata": {path: parsed[path] for path in FILES[1:] if path != "README.md"},
        "primary_manifest_selection": selection,
        "source_identity": {"repository_id": REPOSITORY, "hub_revision": request["revision"],
            "producer_source_revision": manifest["source_revision"], "release_point": manifest["release_point"],
            "release_root_cid": manifest["release_root_cid"], "producer_manifest_digest": manifest["manifest_digest"],
            "aliases_mapped": False},
        "companion_comparisons": comparisons, "companion_declaration_checks": declarations,
        "count_reconciliation": counts, "issues": issues,
        "status": "selected_metadata_verified_with_discrepancies" if issues else "selected_metadata_verified",
        "selection_complete": True, "coverage_scope": "exact_five_selected_source_metadata_files_only",
        "metadata_validation": {"selected_bytes_pinned": True, "producer_manifest_digest_verified": True,
            "companion_descriptors_match": all(item["disposition"] == "descriptor_match" for item in comparisons),
            "companion_declarations_match": all(item["matches"] for item in declarations),
            "table_bodies_read": False, "table_rows_read": False, "Arrow_loaded": False,
            "network_performed": False, "database_opened": False, "models_loaded": False},
        "source_join": {"status": "unresolved_not_attempted", "bindings": [], "source_occurrences": None},
        "producer_pins": before, "producer_pins_after": after,
        "producer_pins_scope": "selected_owner_file_observations_not_complete_execution_closure",
        "loaded_byte_identity_verified": False, "authority": dict(AUTHORITY),
        "limits": {"max_request_bytes": MAX_REQUEST_BYTES, "max_metadata_bytes": MAX_METADATA_BYTES,
            "max_metadata_total_bytes": MAX_METADATA_TOTAL_BYTES, "max_report_bytes": MAX_REPORT_BYTES}}
    return json.loads(ordinary._wire(report, MAX_REPORT_BYTES))


def source_package_intake_sha256(report):
    """Hash the full bounded report, without loading primary operation owners."""
    return _sha(ordinary._wire(report, MAX_REPORT_BYTES))


def validate_source_package_intake(report, request_raw, metadata_bytes, *,
                                   expected_request_sha256, expected_report_sha256):
    """Require independent report identity and exact authoritative regeneration."""
    ordinary._digest(expected_report_sha256, "source package report")
    _preflight(request_raw, metadata_bytes, expected_request_sha256)
    if type(report) is bytes:
        report = ordinary._read_json(report, MAX_REPORT_BYTES, "source package report")
    ordinary._need(type(report) is dict, "ordinary source package report required")
    ordinary._need(source_package_intake_sha256(report) == expected_report_sha256,
                   "source package report SHA256 mismatch")
    expected = prepare_source_package_intake(request_raw, metadata_bytes,
                                             expected_request_sha256=expected_request_sha256)
    ordinary._need(ordinary._wire(report, MAX_REPORT_BYTES) == ordinary._wire(expected, MAX_REPORT_BYTES),
                   "source package intake differs from complete authoritative replay")
    return expected
