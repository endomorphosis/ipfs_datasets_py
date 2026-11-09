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


# Explicit successor for the already qualified homogeneous HF wire envelopes.
# The complete preceding v1 source remains unchanged; this profile does not
# widen the legacy custom-infos wrapper or reinterpret its historical reports.
REQUEST_SCHEMA_V2 = "legal-source-package-intake-request/v2"
SCHEMA_V2 = "legal-source-package-intake/v2"
METADATA_PROFILE_V2 = "hf-default-parquet-envelope/v1"
_V2_LOGICAL_DEFAULT = "publicus-ir-graphrag/v2"
_V2_WIRE_DEFAULT = "publicus-ir-graphrag-v2"
_V2_COLUMNS = ("entry_cid", "legal_id", "family", "record_sha256", "record_json")
_V2_DATA_FAMILIES = frozenset(("corpus", "bm25_documents", "bm25_postings", "vectors",
    "centroids", "graph_nodes", "graph_edges", "graph_adjacency_out", "graph_adjacency_in"))
_V2_WIRE_FIELDS = {"schema", "profile", "default_config", "logical_default_config",
    "aliases", "data_files", "num_examples", "num_bytes", "unadvertised_configs"}
_V2_CARD_PREFIX = ("\nlicense: other\npretty_name: \"US Code Sparse GraphRAG\"\ntags:\n"
    "  - legal\n  - us-code\n  - graphrag\n  - justicedao\n  - public-domain-us-government\n")


def _v2_wire(value, limit=MAX_REPORT_BYTES):
    """One bounded final-report serialization seam; not a validation API."""
    return ordinary._wire(value, limit)


def _v2_owner_state():
    import sys

    primary, pins = _owners()
    origins = {}
    for module in (sys.modules[__name__], ordinary, primary):
        values = module.__dict__
        spec = values.get("__spec__")
        filename = values.get("__file__")
        ordinary._need(type(filename) is str and spec is not None
            and spec.origin == filename and spec.name == values.get("__name__")
            and str(Path(filename).resolve()) in pins,
            "wire intake operation owner has a foreign loaded origin")
        origins[values["__name__"]] = {"path": filename, "spec_origin": spec.origin,
            "spec_name": spec.name, "source_sha256": pins[str(Path(filename).resolve())]}
    return primary, {"producer_pins": pins, "producer_origins": origins}


def _v2_preflight(request_raw, metadata_bytes, expected_request_sha256):
    ordinary._digest(expected_request_sha256, "wire source package request")
    ordinary._need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES
        and _sha(request_raw) == expected_request_sha256, "bounded independently pinned wire request required")
    request = ordinary._read_json(request_raw, MAX_REQUEST_BYTES, "wire source package request")
    ordinary._keys(request, {"schema", "repository_id", "revision", "expected_release_identity",
        "expected_graph_population", "files", "metadata_profile"}, "wire source package request")
    ordinary._need(request["schema"] == REQUEST_SCHEMA_V2 and request["repository_id"] == REPOSITORY
        and request["metadata_profile"] == METADATA_PROFILE_V2,
        "unsupported explicit wire source-package profile")
    ordinary._need(type(request["revision"]) is str and _REVISION.fullmatch(request["revision"]),
        "immutable lowercase forty-hex source revision required")
    ordinary._need(type(request["files"]) is list and len(request["files"]) == len(FILES)
        and type(metadata_bytes) is dict and all(type(key) is str for key in metadata_bytes),
        "exact five-file wire metadata selection required")
    seen, total = set(), 0
    for entry in request["files"]:
        ordinary._keys(entry, {"path_in_repo", "bytes", "sha256"}, "wire metadata descriptor")
        name, size = entry["path_in_repo"], entry["bytes"]
        ordinary._need(type(name) is str and name in FILES and name not in seen,
            "unsupported or duplicate wire metadata path")
        seen.add(name)
        ordinary._need(type(size) is int and 0 < size <= MAX_METADATA_BYTES,
            "bounded positive wire metadata bytes required")
        total += size
        ordinary._need(total <= MAX_METADATA_TOTAL_BYTES, "wire metadata aggregate bound exceeded")
        ordinary._digest(entry["sha256"], "wire metadata file")
    ordinary._need(seen == set(FILES) == set(metadata_bytes), "wire metadata mapping population differs")
    captured, parsed = {}, {}
    for entry in request["files"]:
        name, raw = entry["path_in_repo"], metadata_bytes[entry["path_in_repo"]]
        ordinary._need(type(raw) is bytes and len(raw) == entry["bytes"] and _sha(raw) == entry["sha256"],
            "wire metadata bytes or SHA256 differ: " + name)
        try:
            text = raw.decode("utf-8")
        except UnicodeError as error:
            raise ValueError("wire metadata must be exact UTF8") from error
        if name != "README.md":
            parsed[name] = ordinary._read_json(raw, MAX_METADATA_BYTES, name)
            ordinary._need(type(parsed[name]) is dict, "wire metadata JSON object required: " + name)
        else:
            ordinary._wire(text, MAX_REPORT_BYTES)
        captured[name] = raw
    return request, captured, parsed


def _v2_number(value, label, *, positive=False):
    ordinary._need(type(value) is int and (1 if positive else 0) <= value <= (1 << 63) - 1,
        "bounded nonboolean integer required: " + label)
    return value


def _v2_path(value):
    ordinary._need(type(value) is str and 0 < len(value.encode("utf-8")) <= 4096
        and value.startswith("data/") and value.endswith(".parquet")
        and not any(character in value for character in "\\*?[]{}\x00\r\n")
        and all(part not in ("", ".", "..") for part in value.split("/")),
        "literal normalized wire Parquet path required")
    return value


def _v2_readme(raw, declaration):
    text = raw.decode("utf-8")
    ordinary._need(text.startswith("---\n"), "canonical wire README frontmatter required")
    header, closing, _ = text.partition("\n---\n")
    frontmatter = header[3:] + "\n" if closing else ""
    ordinary._need(closing and
        frontmatter.count("\ndataset_info:\n") == frontmatter.count("\nconfigs:\n") == 1,
        "exactly one recognized dataset_info/configs region required")
    info = ["dataset_info:", "- config_name: " + json.dumps(_V2_WIRE_DEFAULT), "  features:"]
    for column in _V2_COLUMNS:
        info.extend(["  - name: " + json.dumps(column), "    dtype: string"])
    info.extend(["  splits:", '  - name: "train"',
        "    num_examples: " + str(declaration["num_examples"]),
        "    num_bytes: " + str(declaration["num_bytes"])])
    configs = ["configs:", "- config_name: " + json.dumps(_V2_WIRE_DEFAULT),
        "  default: true", "  data_files:", '  - split: "train"',
        "    path: " + json.dumps(declaration["data_files"][0]["path"])]
    expected = _V2_CARD_PREFIX + "\n".join(info + configs) + "\n"
    ordinary._need(frontmatter == expected, "recognized canonical wire README regions differ")
    return {"profile": "canonical-hf-default-parquet-envelope-card-regions/v1",
        "recognized_regions": ["dataset_info", "configs"], "recognized_regions_exact": True,
        "duplicate_region_keys_refused": True, "general_yaml_parser_used": False,
        "uninterpreted_prose_retained": True}


def _v2_reconcile(captured, parsed):
    manifest, configs, release, infos = (parsed[name] for name in
        ("manifest.json", "dataset_configs.json", "release_metadata.json", "dataset_infos.json"))
    declared = manifest.get("wire_metadata")
    ordinary._keys(declared, _V2_WIRE_FIELDS, "explicit HF wire declaration")
    ordinary._need(declared["schema"] == "uscode-hf-wire-metadata/v1"
        and declared["profile"] == METADATA_PROFILE_V2
        and declared["default_config"] == _V2_WIRE_DEFAULT
        and declared["logical_default_config"] == _V2_LOGICAL_DEFAULT
        and declared["aliases"] == {_V2_LOGICAL_DEFAULT: _V2_WIRE_DEFAULT},
        "wire alias/default/profile differs")
    _v2_number(declared["num_examples"], "wire num_examples")
    _v2_number(declared["num_bytes"], "declared Arrow num_bytes")
    for body in (configs, release):
        ordinary._need(ordinary._wire(body.get("wire_metadata"), MAX_METADATA_BYTES)
            == ordinary._wire(declared, MAX_METADATA_BYTES), "wire declarations disagree")
    ordinary._need(all(body.get("default_config") == _V2_LOGICAL_DEFAULT
        for body in (manifest, configs, release)), "logical default must not be replaced by the wire alias")
    logical = manifest.get("configs")
    ordinary._need(type(logical) is list and 1 <= len(logical) <= 3
        and all(type(item) is dict for item in logical), "bounded logical config inventory required")
    names = [item.get("config_name") for item in logical]
    ordinary._need(all(type(name) is str for name in names) and len(set(names)) == len(names)
        and names[0] == _V2_LOGICAL_DEFAULT
        and set(names) <= {_V2_LOGICAL_DEFAULT, "legacy-uscode-parquet/v1", "recovery-quarantine/v1"}
        and logical[0].get("is_default") is True
        and all(item.get("is_default") is False for item in logical[1:]),
        "exact logical default and distinct retained config identities required")
    ordinary._need(all(type(item.get(flag)) is bool and item[flag] == (item["config_name"] == name)
        for item in logical for flag, name in (("is_default", _V2_LOGICAL_DEFAULT),
            ("is_legacy", "legacy-uscode-parquet/v1"), ("is_recovery", "recovery-quarantine/v1"))),
        "exact boolean logical config roles required")
    ordinary._need(logical[0].get("primary_key") == "entry_cid"
        and logical[0].get("features") == ["entry_cid", "legal_id", "family", "record_json", "record_sha256"],
        "supported logical default key and ordered features required")
    ordinary._need(logical[0].get("data_files") == [{"split": "train", "path": "data/**/*.parquet"}]
        and ordinary._wire(configs.get("configs"), MAX_METADATA_BYTES)
            == ordinary._wire(logical, MAX_METADATA_BYTES)
        and release.get("configs") == names
        and declared["unadvertised_configs"] == names[1:], "logical and wire inventories disagree")
    data_files = declared["data_files"]
    ordinary._need(type(data_files) is list and len(data_files) == 1,
        "one explicit wire train population required")
    ordinary._keys(data_files[0], {"split", "path"}, "wire train data files")
    paths = data_files[0]["path"]
    ordinary._need(data_files[0]["split"] == "train" and type(paths) is list and paths
        and all(type(path) is str for path in paths) and paths == sorted(set(paths)),
        "sorted distinct literal wire file population required")
    for path in paths:
        _v2_path(path)
    artifacts = manifest.get("artifacts")
    ordinary._need(type(artifacts) is list and 0 < len(artifacts) <= 8192
        and all(type(item) is dict and type(item.get("relative_path")) is str for item in artifacts),
        "bounded manifest descriptor population required")
    selected = sorted((item for item in artifacts if item["relative_path"].startswith("data/")
        and item["relative_path"].endswith(".parquet")), key=lambda item: item["relative_path"])
    ordinary._need(selected and [item["relative_path"] for item in selected] == paths,
        "wire paths must equal the complete explicit normalized data descriptor population")
    rows_by_family = {}
    selected_bytes = 0
    for item in selected:
        _v2_path(item["relative_path"])
        ordinary._need(type(item.get("family")) is str and item["family"] in _V2_DATA_FAMILIES
            and item.get("media_type") == "application/vnd.apache.parquet",
            "routing/recovery/legacy or non-Parquet descriptor cannot enter wire data")
        rows = _v2_number(item.get("row_count"), "selected descriptor rows")
        selected_bytes += _v2_number(item.get("size_bytes"), "selected compressed bytes", positive=True)
        rows_by_family[item["family"]] = rows_by_family.get(item["family"], 0) + rows
    row_sum = sum(rows_by_family.values())
    ordinary._need(row_sum == declared["num_examples"], "wire row count differs from selected descriptors")
    expected_infos = {_V2_WIRE_DEFAULT: {"config_name": _V2_WIRE_DEFAULT,
        "features": {column: {"dtype": "string", "_type": "Value"} for column in _V2_COLUMNS},
        "splits": {"train": {"name": "train", "num_examples": declared["num_examples"],
            "num_bytes": declared["num_bytes"]}}}}
    ordinary._need(ordinary._wire(infos, MAX_METADATA_BYTES)
        == ordinary._wire(expected_infos, MAX_METADATA_BYTES),
        "standard wire DatasetInfosDict features/splits/counts differ")
    # Equality alone admits True == 1; inspect the actual infos counters too.
    _v2_number(infos[_V2_WIRE_DEFAULT]["splits"]["train"]["num_examples"], "infos num_examples")
    _v2_number(infos[_V2_WIRE_DEFAULT]["splits"]["train"]["num_bytes"], "infos num_bytes")
    readme = _v2_readme(captured["README.md"], declared)
    comparisons, declarations = [], []
    by_path = {item["relative_path"]: item for item in artifacts}
    ordinary._need(len(by_path) == len(artifacts), "duplicate manifest descriptor paths")
    for name in FILES[1:]:
        descriptor, body = by_path.get(name), captured[name]
        ordinary._need(descriptor is not None and descriptor.get("size_bytes") == len(body)
            and descriptor.get("sha256") == _sha(body), "wire companion descriptor mismatch: " + name)
        comparisons.append({"path_in_repo": name, "descriptor": descriptor,
            "observed_bytes": len(body), "observed_sha256": _sha(body),
            "size_matches": True, "sha256_matches": True, "disposition": "descriptor_match"})
    expected_release = {"dataset_id": REPOSITORY, "schema_version": manifest.get("hf_release_schema_version"),
        **{key: manifest.get(key) for key in ("release_profile", "release_point", "release_root_cid",
            "source_revision", "graph_ontology_version", "producer")}}
    for key, expected in expected_release.items():
        ordinary._need(release.get(key) == expected, "wire release metadata declaration mismatch: " + key)
        declarations.append({"path_in_repo": "release_metadata.json", "field": key,
            "expected": expected, "observed": release.get(key), "matches": True})
    ordinary._need(configs.get("schema_version") == manifest.get("hf_release_schema_version") == "uscode-hf-release/v1",
        "unsupported logical companion schema")
    declarations.append({"path_in_repo": "dataset_configs.json", "field": "schema_version",
        "expected": "uscode-hf-release/v1", "observed": configs["schema_version"], "matches": True})
    counts = {"status": "advertised_rows_match_exact_wire_population",
        "selected_descriptor_paths": paths, "selected_descriptor_count": len(selected),
        "selected_descriptor_row_sum": row_sum, "selected_descriptor_byte_sum": selected_bytes,
        "advertised_train_num_examples": declared["num_examples"],
        "declared_arrow_num_bytes": declared["num_bytes"], "arrow_bytes_physically_measured_here": False,
        "corpus_declared_rows": rows_by_family.get("corpus", 0),
        "routing_index_declared_rows": sum(item.get("row_count", 0) for item in artifacts
            if item.get("family") == "routing_index"),
        "rows_by_family": rows_by_family, "unique_laws": None, "rows_read": 0,
        "meaning": "Envelope descriptor rows and declared Arrow bytes are separate measures; no table or unique-law coverage is verified."}
    wire_reconciliation = {"declaration": declared, "selected_paths": paths,
        "selected_descriptor_count": len(selected), "selected_descriptor_row_sum": row_sum,
        "logical_default_config": _V2_LOGICAL_DEFAULT, "wire_default_config": _V2_WIRE_DEFAULT,
        "declared_Arrow_bytes_verified_here": False}
    return comparisons, declarations, counts, wire_reconciliation, readme


def _v2_checked_selection(selection, request, captured, parsed, primary):
    fields = {"schema", "repository", "revision", "manifest_sha256", "raw_manifest_utf8", "manifest",
        "expected_release_identity", "expected_graph_population", "descriptors", "selected_file_count",
        "selected_row_count", "producer_manifest_digest_verified", "release_root_cid_recomputed",
        "descriptor_key_ranges_verified", "membership_policy", "authority", "selection_sha256"}
    ordinary._keys(selection, fields, "genuine primary selection return")
    graph = [item for item in parsed["manifest.json"]["artifacts"] if item["family"] in ("graph_nodes", "graph_edges")]
    expected_authority = dict.fromkeys(("admitted", "formalized", "source_semantics_verified",
        "source_currentness_verified", "global_consistency_verified", "proof_authority", "training_qualified"), False)
    ordinary._need(selection["schema"] == "legal-primary-graph-manifest-selection/v1"
        and selection["repository"] == request["repository_id"]
        and selection["revision"] == request["revision"]
        and selection["manifest_sha256"] == _sha(captured["manifest.json"])
        and selection["raw_manifest_utf8"] == captured["manifest.json"].decode("utf-8")
        and ordinary._wire(selection["manifest"], MAX_METADATA_BYTES)
            == ordinary._wire(parsed["manifest.json"], MAX_METADATA_BYTES)
        and ordinary._wire(selection["expected_release_identity"], MAX_REQUEST_BYTES)
            == ordinary._wire(request["expected_release_identity"], MAX_REQUEST_BYTES)
        and ordinary._wire(selection["expected_graph_population"], MAX_REQUEST_BYTES)
            == ordinary._wire(request["expected_graph_population"], MAX_REQUEST_BYTES)
        and ordinary._wire(selection["descriptors"], MAX_METADATA_BYTES)
            == ordinary._wire(graph, MAX_METADATA_BYTES)
        and type(selection["selected_file_count"]) is int and selection["selected_file_count"] == len(graph)
        and type(selection["selected_row_count"]) is int
        and selection["selected_row_count"] == sum(item["row_count"] for item in graph)
        and selection["producer_manifest_digest_verified"] is True
        and selection["release_root_cid_recomputed"] is selection["descriptor_key_ranges_verified"] is False
        and selection["membership_policy"] == "exact_graph_descriptors_only"
        and selection["authority"] == expected_authority
        and all(value is False for value in selection["authority"].values()),
        "primary selection return differs from independently pinned raw metadata")
    ordinary._need(selection["selection_sha256"] == _sha(ordinary._wire(
        {key: value for key, value in selection.items() if key != "selection_sha256"}, MAX_REPORT_BYTES)),
        "primary selection return commitment differs")


def _v2_fence(original_metadata, opening_items, captured, captured_snapshot, parsed, parsed_snapshot,
              selection, selection_snapshot, owners_before, selector_before, report=None, serialized=None,
              request=None, request_snapshot=None):
    primary, observed = _v2_owner_state()
    ordinary._need(observed == owners_before and primary.select_primary_graph_manifest is selector_before,
        "wire intake producer or loaded origin changed")
    ordinary._need(tuple(original_metadata.items()) == opening_items
        and tuple(captured.items()) == captured_snapshot
        and ordinary._wire(parsed, MAX_METADATA_TOTAL_BYTES) == parsed_snapshot,
        "original or detached wire metadata changed during operation")
    ordinary._need(ordinary._wire(request, MAX_REQUEST_BYTES) == request_snapshot,
        "parsed wire request changed during primary delegation")
    if selection is not None:
        ordinary._need(ordinary._wire(selection, MAX_REPORT_BYTES) == selection_snapshot,
            "genuine primary selection changed during wire intake")
    if report is not None:
        ordinary._need(ordinary._wire(report, MAX_REPORT_BYTES) == serialized,
            "wire report changed during final serialization")
    primary, after = _v2_owner_state()
    ordinary._need(after == owners_before and primary.select_primary_graph_manifest is selector_before
        and tuple(original_metadata.items()) == opening_items
        and tuple(captured.items()) == captured_snapshot
        and ordinary._wire(parsed, MAX_METADATA_TOTAL_BYTES) == parsed_snapshot
        and ordinary._wire(request, MAX_REQUEST_BYTES) == request_snapshot
        and (selection is None or ordinary._wire(selection, MAX_REPORT_BYTES) == selection_snapshot)
        and (report is None or ordinary._wire(report, MAX_REPORT_BYTES) == serialized),
        "wire intake final producer/input fence changed")


def prepare_source_package_intake_v2(request_raw, metadata_bytes, *, expected_request_sha256):
    """Reconcile the explicit wire profile; read no table, loader or remote source."""
    ordinary._need(type(metadata_bytes) is dict, "ordinary original wire metadata mapping required")
    opening_items = tuple(metadata_bytes.items())
    request, captured, parsed = _v2_preflight(request_raw, metadata_bytes, expected_request_sha256)
    captured_snapshot = tuple(captured.items())
    request_snapshot = ordinary._wire(request, MAX_REQUEST_BYTES)
    parsed_snapshot = ordinary._wire(parsed, MAX_METADATA_TOTAL_BYTES)
    # Malformed declarations/regions refuse before the primary operation owner.
    reconciliation = _v2_reconcile(captured, parsed)
    primary, before = _v2_owner_state()
    selector = primary.select_primary_graph_manifest
    descriptor = next(item for item in request["files"] if item["path_in_repo"] == "manifest.json")
    selection = selector(captured["manifest.json"], expected_manifest_sha256=descriptor["sha256"],
        repository=request["repository_id"], revision=request["revision"],
        expected_release_identity=request["expected_release_identity"],
        expected_graph_population=request["expected_graph_population"])
    _v2_checked_selection(selection, request, captured, parsed, primary)
    selection_snapshot = ordinary._wire(selection, MAX_REPORT_BYTES)
    _v2_fence(metadata_bytes, opening_items, captured, captured_snapshot, parsed, parsed_snapshot,
        selection, selection_snapshot, before, selector,
        request=request, request_snapshot=request_snapshot)
    detached_selection = ordinary._read_json(selection_snapshot, MAX_REPORT_BYTES, "primary selection")
    comparisons, declarations, counts, wire_reconciliation, readme = reconciliation
    report = {"schema": SCHEMA_V2, "metadata_profile": METADATA_PROFILE_V2,
        "repository_id": REPOSITORY, "revision": request["revision"],
        "revision_evidence": "caller_supplied_acquisition_identity_not_remotely_authenticated",
        "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256,
        "files": [{"selection_ordinal": index, **item, "raw_utf8": captured[item["path_in_repo"]].decode("utf-8")}
            for index, item in enumerate(request["files"])],
        "companion_metadata": {name: parsed[name] for name in FILES[1:] if name != "README.md"},
        "primary_manifest_selection": detached_selection,
        "source_identity": {"repository_id": REPOSITORY, "hub_revision": request["revision"],
            "producer_source_revision": parsed["manifest.json"]["source_revision"],
            "release_point": parsed["manifest.json"]["release_point"],
            "release_root_cid": parsed["manifest.json"]["release_root_cid"],
            "producer_manifest_digest": parsed["manifest.json"]["manifest_digest"], "aliases_mapped": False},
        "companion_comparisons": comparisons, "companion_declaration_checks": declarations,
        "wire_metadata_reconciliation": wire_reconciliation, "readme_validation": readme,
        "count_reconciliation": counts, "issues": [], "status": "selected_wire_metadata_reconciled",
        "selection_complete": True, "coverage_scope": "exact_five_selected_wire_metadata_files_only",
        "metadata_validation": {"selected_bytes_pinned": True, "producer_manifest_digest_verified": True,
            "companion_descriptors_match": True, "companion_declarations_match": True,
            "wire_declarations_match": True, "infos_features_match": True,
            "readme_recognized_regions_match": True, "counts_match_selected_descriptors": True,
            "table_bodies_read": False, "table_rows_read": False, "Arrow_loaded": False,
            "network_performed": False, "database_opened": False, "models_loaded": False},
        "source_join": {"status": "unresolved_not_attempted", "bindings": [], "source_occurrences": None},
        "producer_pins": before["producer_pins"], "producer_pins_after": before["producer_pins"],
        "producer_origins": before["producer_origins"], "producer_origins_after": before["producer_origins"],
        "producer_pins_scope": "selected_owner_file_observations_not_complete_execution_closure",
        "loaded_byte_identity_verified": False, "authority": dict(AUTHORITY),
        "training_mask": 0, "evaluation_gold_mask": 0,
        "limits": {"max_request_bytes": MAX_REQUEST_BYTES, "max_metadata_bytes": MAX_METADATA_BYTES,
            "max_metadata_total_bytes": MAX_METADATA_TOTAL_BYTES, "max_report_bytes": MAX_REPORT_BYTES}}
    serialized = _v2_wire(report, MAX_REPORT_BYTES)
    _v2_fence(metadata_bytes, opening_items, captured, captured_snapshot, parsed, parsed_snapshot,
        selection, selection_snapshot, before, selector, report, serialized,
        request=request, request_snapshot=request_snapshot)
    detached = ordinary._read_json(serialized, MAX_REPORT_BYTES, "wire intake report")
    ordinary._need(ordinary._wire(detached, MAX_REPORT_BYTES) == serialized,
        "wire intake final report bytes differ")
    return detached


def validate_source_package_intake_v2(report, request_raw, metadata_bytes, *,
                                      expected_request_sha256, expected_report_sha256):
    """Require independent v2 report identity and genuine complete regeneration."""
    ordinary._digest(expected_report_sha256, "wire source package report")
    _v2_preflight(request_raw, metadata_bytes, expected_request_sha256)
    if type(report) is bytes:
        report = ordinary._read_json(report, MAX_REPORT_BYTES, "wire source package report")
    ordinary._need(type(report) is dict and report.get("schema") == SCHEMA_V2
        and report.get("metadata_profile") == METADATA_PROFILE_V2,
        "explicit v2 wire intake report required")
    offered = ordinary._wire(report, MAX_REPORT_BYTES)
    ordinary._need(_sha(offered) == expected_report_sha256, "wire report independent SHA256 differs")
    expected = prepare_source_package_intake_v2(request_raw, metadata_bytes,
        expected_request_sha256=expected_request_sha256)
    ordinary._need(ordinary._wire(report, MAX_REPORT_BYTES) == offered,
        "offered wire report changed during authoritative regeneration")
    ordinary._need(ordinary._wire(expected, MAX_REPORT_BYTES) == offered,
        "wire intake report differs from full authoritative regeneration")
    return expected
