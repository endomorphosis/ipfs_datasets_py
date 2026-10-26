"""Complete selected paired-cache rows and declared inventory associations.

Existing manifest, payload and original-bound inventory owners remain unchanged.
Paired outputs are opaque transport observations, never context/catalog inputs.
Byte-consistent declarations do not establish original physical correspondence.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat

SCHEMA = "legal-compact-source-context-cache-intake/v1"
PROFILE = "original-bound-paired-cache-declared-associations/v1"
BINDINGS_SCHEMA = "legal-compact-source-context-cache-bindings/v1"
SCHEMA_V2 = "legal-compact-source-context-cache-intake/v2"
PROFILE_V2 = "coordinate-bound-paired-cache-declared-associations/v2"
BINDINGS_SCHEMA_V2 = "legal-compact-source-context-cache-bindings/v2"
SOURCE_COMPATIBILITY_PROFILE = "paired-coordinate-transport-compatibility/v1"
MAX_REQUEST_BYTES = 128 * 1024
MAX_BINDINGS_BYTES = 512 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_MANIFESTS = 4
MAX_ROWS = 128
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 64 * 1024 * 1024
PAYLOAD_LIMITS = dict(max_bytes=64 * 1024 * 1024, max_rows=64,
                      max_decoded_bytes=64 * 1024 * 1024, max_report_bytes=8 * 1024 * 1024)
ROW_SERIALIZATION = "derived-parquet-row/sorted-ascii-json-v1"
RECORD_STATUSES = ("verified", "bundle_unavailable", "bundle_corrupt", "bundle_unsupported")
ASSOCIATION_STATUSES = ("unresolved_source_occurrence", "declared_single_association",
    "ambiguous_source_occurrences", "association_source_mismatch", "cache_record_unavailable")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_ROOT_RELATIVE = "logic/autoformal/"
# This strict compatibility generation is requalified against the coordinate-
# capable paired owners. Historical pin values remain in the captured source
# receipt; they are not an alternate allowlist or a claim of old qualification.
_SOURCE_PINS = {
    "legal_compact_source_context_inventory_v1": "3b97c3ac87e7c83cf1fe4e63bafceb14b491a658e9679ff0033de5272b3ea243",
    "legal_paired_manifest_inventory_v1": "f5778bbb6f2fef41a45057ce45ca2f409f0f27647c39e538b21909dd38a1990b",
    "legal_paired_payload_intake_v1": "46ba5a39dce8d37543b57794fbf0bbbd44b50e25f5cb8ad4bb895f10a65e15fb",
    "span_cache_feed": "60d515f24bec614413021f9efbf4b708e79e0a1f98d408fb686c89023aa40d8a",
    "paired_span_census": "65a4aa7b5a78ee22f8cb2847a0ee23e56e753defdfc702e332507dd092f75cdb",
    "span_cache_exchange": "0c31dbe6ada1ecdf5c13ceda0b04da0cf13981801d8563e5750fc0cac41b4857",
    "span_evidence": "2954dfa10d2aad64178b3b3bfc799686389a98303652f6856bd2dbee9cae95ed",
    "supervisor_queue": "2802b9a24618abdbd2acd58b5f475c8b634539e68d12d3cfd7a0dff0a2c05172",
    "supervisor_todo": "e4443a7fa3826ba9709c97c00f4ea2db2c4ab48b24b4aa759eef53d1199ccf70",
    "corpus_contracts": "b89146e2471b7335f23115222c5a9bc5298a20bb02f02cce5d91496e6563d8aa",
    "corpus_graph": "da2bef54beca29d0d613d46a81241f6f1b7f049e1c9bf9cf1c118d9942374061",
    "corpus_source": "6e4be77cfc27a750b11aa57bb92baa92617c57d5c4a26316e25563aa715ec257",
    "corpus_span_adapter": "fe8d64b83e731622cc9024ee6a9cd7e656863df7d709c59626887663d72b01d2",
    "learned_formula_observation": "75f241160e1e09d8414fbf43d7effc0f615f821a5de91b91f0e8447eb7fe04ad",
}
_COORDINATE_SOURCE_PINS = {
    "span_cache": "e35f5333fc4776d5b519ec84a38f42715a76ff7b20a776a35b7e01ea9342b068",
    "uscode_ingest": "a0d79a7459186c19c3a32cc03405acc3e4a4e0e2b33fc7bae9525be7b5246e92",
}
_INVENTORY_KEYS = {"population_raw", "occurrences_raw", "catalog_raw", "access_raw",
    "expected_population_sha256", "expected_occurrences_sha256", "expected_catalog_sha256",
    "expected_access_sha256", "source_partitions", "expected_source_partitions_sha256",
    "source_resolver", "expected_report_sha256"}
_AUTHORITY = dict.fromkeys(("remote_revision_authenticated", "source_correspondence_verified",
    "source_authority_authenticated", "source_semantics_verified", "context_independence_verified",
    "context_permission_verified", "inference_permission_verified", "reviewer_authenticated",
    "training_qualified", "evaluation_gold_qualified", "shared_definition_closure_verified",
    "global_holdout_verified", "source_encoder_authenticated", "legal_accuracy_established",
    "convergence_proved", "Lean_admitted", "accepted", "admitted", "model_executed",
    "training_executed", "database_executed", "prover_executed", "supervisor_executed"), False)
_LIMITATIONS = [
    "Coverage is the complete manifest-declared selected paired-row reference population, not the whole cache or a representative corpus sample.",
    "Local bytes and saved acquisition declarations do not authenticate a remote commit or latest-main identity.",
    "Derived Parquet-row JSON preserves decoded field values and nested JSON strings; it is not recovered original producer JSON or physical Parquet bytes.",
    "The paired owner reads retained formal outputs, diagnostic vectors, goals and artifact bodies for bundle integrity. They remain opaque cache observations and never become this operation's source/context catalog or model inputs.",
    "Explicit associations are caller declarations. Exact source-text consistency does not prove original statutory physical occurrence, edition, source revision, legal meaning or independent context access.",
    "Every effective inference view remains null. Native encoder receipt attachment, entity/definition scanning, dependency closure, independent review/chronology, training, Lean and convergence remain deferred.",
    "Source pins and ordinary Python fences are not attestation against arbitrary monkeypatching, preloaded bytecode or native libraries. Replacing all originals and independent pins defines a different operation.",
]


class SourceContextCacheIntakeError(ValueError):
    """A bounded original, physical slot, declared association or replay differs."""


def _need(ok, message):
    if not ok:
        raise SourceContextCacheIntakeError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _pin_raw(raw, expected, maximum, label):
    _hash(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent " + label + " SHA256 mismatch")


def _source(path, expected):
    _need(path.resolve(strict=True) == path and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents),
          "canonical producer source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 512 * 1024,
          "bounded single-link producer source required")
    raw = path.read_bytes()
    after = path.lstat()
    witness = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    _need(witness(before) == witness(after) and hashlib.sha256(raw).hexdigest() == expected,
          "producer source changed or fixed pin differs")
    return witness(after)


def _selected_pins(coordinate_profile=False):
    return {**_SOURCE_PINS, **(_COORDINATE_SOURCE_PINS if coordinate_profile else {})}


def _sources(root, coordinate_profile=False):
    return {str(_SELF_PATH): _source(_SELF_PATH, _SELF_SHA),
        **{str(root / _ROOT_RELATIVE / (name + ".py")): _source(root / _ROOT_RELATIVE / (name + ".py"), digest)
           for name, digest in _selected_pins(coordinate_profile).items()}}


def _owners(coordinate_profile=False):
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _ROOT_RELATIVE / "legal_compact_source_context_inventory_v1.py").is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None and root.resolve(strict=True) == root, "canonical owner tree required")
    before = _sources(root, coordinate_profile)
    modules = {}
    for key, name in (("inventory", "legal_compact_source_context_inventory_v1"),
            ("manifest", "legal_paired_manifest_inventory_v1"), ("payload", "legal_paired_payload_intake_v1"),
            ("feed", "span_cache_feed"), ("census", "paired_span_census")):
        module = importlib.import_module("ipfs_datasets_py.logic.autoformal." + name)
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / _ROOT_RELATIVE / (name + ".py"),
              "genuine canonical owner import required")
        modules[key] = module
    _need(_sources(root, coordinate_profile) == before, "producer sources changed during imports")
    return root, before, modules


def _root(value):
    _need(type(value) in (str, type(Path())), "ordinary repository root required")
    path = Path(value)
    _need(path.is_absolute() and path.resolve(strict=True) == path and path.is_dir()
          and all(stat.S_ISDIR(p.lstat().st_mode) for p in (path, *path.parents)),
          "unaliased absolute retained repository root required")
    return path


def _file(path, descriptor):
    """Observed immutable local bytes; missing/corrupt states are retained."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return dict(status="missing", expected=descriptor, observed=None, witness=None)
    _need(path.resolve(strict=True) == path and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents)
          and stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unaliased single-link cache file required")
    witness = lambda s: [s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    digest, count = hashlib.sha256(), 0
    if info.st_size <= MAX_FILE_BYTES:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            _need(witness(os.fstat(stream.fileno())) == witness(info), "cache file changed before read")
            while block := stream.read(min(1024 * 1024, MAX_FILE_BYTES - count + 1)):
                count += len(block)
                _need(count <= MAX_FILE_BYTES, "cache file grew beyond bound")
                digest.update(block)
            _need(witness(os.fstat(stream.fileno())) == witness(info), "cache file changed during read")
        observed = dict(bytes=count, sha256=digest.hexdigest())
    else:
        observed = dict(bytes=info.st_size, sha256=None)
    _need(witness(path.lstat()) == witness(info), "cache file changed after read")
    return dict(status="verified" if observed == descriptor else "corrupt", expected=descriptor,
                observed=observed, witness=witness(info))


def _files(root, descriptors):
    return {path: _file(root / path, descriptor) for path, descriptor in descriptors.items()}


def _inventory_arguments(value):
    _need(type(value) is dict and set(value) == _INVENTORY_KEYS, "closed complete original inventory arguments required")
    return dict(value)


def _bindings(raw, expected, request_sha, inventory_sha, manifests, inventory, owner, coordinate_profile=False):
    value = owner._read_json(raw, MAX_BINDINGS_BYTES, "cache bindings")
    _need(type(value) is dict and set(value) == {"schema", "cache_request_sha256", "inventory_report_sha256", "rows"}
          and value["schema"] == (BINDINGS_SCHEMA_V2 if coordinate_profile else BINDINGS_SCHEMA)
          and value["cache_request_sha256"] == request_sha
          and value["inventory_report_sha256"] == inventory_sha, "closed original-bound cache bindings required")
    slots = [(manifest["path_in_repo"], ordinal) for manifest in manifests
             for ordinal in range(manifest["manifest"]["tables"]["paired_spans"]["row_count"])]
    _need(len(slots) <= MAX_ROWS and type(value["rows"]) is list and len(value["rows"]) == len(slots),
          "complete ordered declared cache-row bindings required")
    ids = {row["id"] for row in inventory["rows"]}
    for row, (path, ordinal) in zip(value["rows"], slots):
        _need(type(row) is dict and set(row) == {"manifest_path_in_repo", "row_ordinal", "row_sha256", "occurrence_ids"}
              and type(row["row_ordinal"]) is int and row["manifest_path_in_repo"] == path
              and row["row_ordinal"] == ordinal, "complete ordered declared cache-row bindings required")
        if row["row_sha256"] is not None:
            _hash(row["row_sha256"], "expected cache row")
        selected = row["occurrence_ids"]
        _need(type(selected) is list and len(selected) <= len(ids)
              and all(type(item) is str and item in ids for item in selected)
              and len(set(selected)) == len(selected), "unique known explicit inventory occurrence IDs required")
    _need(hashlib.sha256(raw).hexdigest() == expected, "cache bindings changed")
    return value


def _identity(value, owner):
    return "sha256:" + hashlib.sha256(owner._wire(value, MAX_REPORT_BYTES)).hexdigest()


def _prepare_source_context_cache_intake(cache_request_raw, cache_bindings_raw, *,
        expected_cache_request_sha256, expected_cache_bindings_sha256, manifest_bytes,
        repository_root, inventory_report, inventory_originals, coordinate_profile=False):
    """Retain all selected physical slots and explicit, unauthenticated links.

    Exact manifest originals define the denominator even when retained table
    files cannot be consumed. Existing inventory and paired owners do all
    structural replay/decoding; no model or context vocabulary is inferred.
    """
    _pin_raw(cache_request_raw, expected_cache_request_sha256, MAX_REQUEST_BYTES, "cache request")
    _pin_raw(cache_bindings_raw, expected_cache_bindings_sha256, MAX_BINDINGS_BYTES, "cache bindings")
    root, sources, modules = _owners(coordinate_profile)
    metadata, prior = modules["manifest"], modules["inventory"]
    directory = _root(repository_root)
    originals = _inventory_arguments(inventory_originals)
    _hash(originals["expected_report_sha256"], "inventory report")
    _need(type(manifest_bytes) is dict and all(type(k) is str and type(v) is bytes for k, v in manifest_bytes.items()),
          "exact original manifest byte mapping required")
    manifest_originals = dict(manifest_bytes)
    prepare_metadata = (metadata.prepare_paired_manifest_inventory_v2 if coordinate_profile
                        else metadata.prepare_paired_manifest_inventory)
    manifest_report = prepare_metadata(cache_request_raw, manifest_originals,
        expected_request_sha256=expected_cache_request_sha256)
    manifests = manifest_report["manifests"]
    _need(1 <= len(manifests) <= (1 if coordinate_profile else MAX_MANIFESTS),
          "one coordinate manifest required" if coordinate_profile else "bounded nonempty manifest population required")
    # The metadata owner accepts nonnegative row counts without allocating
    # rows. Bound those declarations before reading files or building slots.
    counts = [row["manifest"]["tables"]["paired_spans"]["row_count"] for row in manifests]
    _need(all(type(count) is int and 0 <= count <= PAYLOAD_LIMITS["max_rows"] for count in counts)
          and sum(counts) <= MAX_ROWS, "bounded complete declared cache-row population required")
    descriptors = {}
    for manifest in manifests:
        descriptors[manifest["path_in_repo"]] = dict(bytes=manifest["bytes"], sha256=manifest["sha256"])
        for table in manifest["manifest"]["tables"].values():
            descriptor = dict(bytes=table["bytes"], sha256=table["sha256"])
            _need(0 < descriptor["bytes"] <= MAX_FILE_BYTES
                  and descriptors.setdefault(table["path_in_repo"], descriptor) == descriptor,
                  "bounded consistent physical cache-table descriptors required")
    _need(sum(row["bytes"] for row in descriptors.values()) <= MAX_TOTAL_FILE_BYTES,
          "complete selected cache bytes exceed bound")
    files_before = _files(directory, descriptors)
    _, _, inventory_modules = prior._owners()
    compact = inventory_modules["compact"]
    report_original = compact._wire(inventory_report, prior.MAX_REPORT_BYTES)
    report_sha = originals["expected_report_sha256"]
    _need(hashlib.sha256(report_original).hexdigest() == report_sha, "inventory report SHA256 mismatch")
    bindings = _bindings(cache_bindings_raw, expected_cache_bindings_sha256, expected_cache_request_sha256,
        report_sha, manifests, json.loads(report_original), metadata, coordinate_profile)
    inventory = prior.validate_source_context_inventory_v1(inventory_report, **originals)
    entries = [row["entry_cid"] for row in inventory["rows"]]
    partition_before = prior._partition_state(originals["source_partitions"], inventory_modules, entries)
    inventory_by_id = {row["id"]: row for row in inventory["rows"]}

    def fence():
        _need(_sources(root, coordinate_profile) == sources, "producer sources changed during cache intake")
        _need(type(manifest_bytes) is dict and set(manifest_bytes) == set(manifest_originals)
              and all(type(manifest_bytes[k]) is bytes and manifest_bytes[k] == v for k, v in manifest_originals.items()),
              "original manifest mapping changed during cache intake")
        _need(type(inventory_originals) is dict and set(inventory_originals) == _INVENTORY_KEYS
              and all(inventory_originals[k] is v or type(inventory_originals[k]) is type(v) and inventory_originals[k] == v
                      for k, v in originals.items()), "original inventory arguments changed during cache intake")
        _need(compact._wire(inventory_report, prior.MAX_REPORT_BYTES) == report_original,
              "original inventory report changed during cache intake")
        _need(prior._partition_state(originals["source_partitions"], inventory_modules, entries) == partition_before,
              "source partitions changed during cache intake")
        _need(_files(directory, descriptors) == files_before, "cache file witnesses changed during operation")

    failure = None
    try:
        fence()
        records, bundles = [], []
        request = manifest_report["request"]
        position = 0
        # Arrow is used only by the existing public paired payload owner. Its
        # declared decode exceptions are retained; arbitrary exceptions escape.
        arrow = importlib.import_module("pyarrow")
        known_failures = (modules["feed"].FeedError, modules["census"].PairedCensusError,
                          arrow.ArrowInvalid, arrow.ArrowNotImplementedError)
        for manifest_index, manifest in enumerate(manifests):
            path = manifest["path_in_repo"]
            tables = manifest["manifest"]["tables"]
            table = tables["paired_spans"]
            names = [path, *[value["path_in_repo"] for value in tables.values()]]
            file_rows = [files_before[name] for name in names]
            payload, error = None, None
            if any(row["status"] == "missing" for row in file_rows):
                status = "bundle_unavailable"
                error = dict(type="MissingRetainedFile", message="one or more exact retained bundle files are missing")
            elif any(row["status"] == "corrupt" for row in file_rows):
                status = "bundle_corrupt"
                error = dict(type="RetainedFileIdentityMismatch", message="one or more exact retained bundle files differ")
            else:
                try:
                    prepare_payload = (modules["payload"].prepare_paired_payload_intake_v2 if coordinate_profile
                                       else modules["payload"].prepare_paired_payload_intake)
                    extra = ({"expected_source_coordinate_report_sha256": manifest["source_coordinate_report_sha256"]}
                             if coordinate_profile else {})
                    payload = prepare_payload(repository_root=directory,
                        repository_id=request["repository_id"], revision=request["revision"],
                        manifest_path_in_repo=path, expected_manifest_sha256=manifest["sha256"],
                        source_bindings=None, limits=dict(PAYLOAD_LIMITS), **extra)
                    status = "verified"
                except known_failures as refusal:
                    status = "bundle_unsupported"
                    error = dict(type=type(refusal).__name__, message=str(refusal)[:512])
            if payload is not None:
                _need(len(payload["rows"]) == table["row_count"], "paired owner omitted declared physical rows")
            bundles.append(dict(manifest_path_in_repo=path, manifest_sha256=manifest["sha256"], status=status,
                declared_rows=table["row_count"], payload_report=payload, failure=error))
            for ordinal in range(table["row_count"]):
                binding = bindings["rows"][position]
                position += 1
                original_row = None if payload is None else payload["rows"][ordinal]
                row_hash = None if original_row is None else original_row["row_sha256"]
                if row_hash is not None and binding["row_sha256"] is not None:
                    _need(row_hash == binding["row_sha256"], "expected physical cache row SHA256 differs")
                decoded = None if original_row is None else metadata._read_json(
                    original_row["derived_row_json"].encode("utf-8"), MAX_REPORT_BYTES, "derived cache row")
                if original_row is not None:
                    _need(original_row["row_ordinal"] == ordinal and hashlib.sha256(
                        original_row["derived_row_json"].encode("utf-8")).hexdigest() == row_hash,
                        "paired owner physical row identity differs")
                physical = dict(repository_id=request["repository_id"], revision=request["revision"],
                    table_path_in_repo=table["path_in_repo"], table_sha256=table["sha256"], row_ordinal=ordinal)
                physical_id = _identity(physical, metadata)
                reference_id = _identity(dict(manifest_path_in_repo=path, manifest_sha256=manifest["sha256"],
                                              physical_record_id=physical_id), metadata)
                source = None if decoded is None else decoded["source"]
                associations = []
                for identity in binding["occurrence_ids"]:
                    target = inventory_by_id[identity]
                    exact = source is not None and source["text"] == target["source_request"]["input"]["text"] \
                        and source["text_sha256"] == target["source_text_sha256"]
                    associations.append(dict(occurrence_id=identity, source_row_id=target["source_row_id"],
                        input_id=target["source_request"]["input"]["input_id"], source_text_sha256=target["source_text_sha256"],
                        exact_text_sha256_match=exact, inventory_source_bytes_verified=target["source_bytes_verified"],
                        source_correspondence_verified=False))
                association_status = ("cache_record_unavailable" if decoded is None else
                    "unresolved_source_occurrence" if not associations else
                    "association_source_mismatch" if any(not row["exact_text_sha256_match"] for row in associations) else
                    "declared_single_association" if len(associations) == 1 else "ambiguous_source_occurrences")
                record = dict(manifest_index=manifest_index, manifest_path_in_repo=path,
                    manifest_sha256=manifest["sha256"], repository_id=request["repository_id"], revision=request["revision"],
                    table=table, row_ordinal=ordinal, physical_record_id=physical_id, reference_id=reference_id,
                    expected_row_sha256=binding["row_sha256"], row_sha256=row_hash,
                    record_sha256=None if row_hash is None else _identity(dict(**physical, row_sha256=row_hash), metadata).removeprefix("sha256:"),
                    record_status=status, derived_row_json=None if original_row is None else original_row["derived_row_json"],
                    row_serialization=ROW_SERIALIZATION, observation_id=None if original_row is None else original_row["observation_id"],
                    source_observation=source, payload_disposition=None if original_row is None else original_row["disposition"],
                    occurrence_ids=binding["occurrence_ids"], association_status=association_status, association_results=associations,
                    inference_view=None, authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0)
                if coordinate_profile:
                    expected_pin = manifest["source_coordinate_report_sha256"]
                    if original_row is not None:
                        _need(original_row["source_coordinate_report_sha256"] == expected_pin,
                              "payload coordinate report differs from independent original pin")
                    record.update(expected_source_coordinate_report_sha256=expected_pin,
                        source_coordinate_report_sha256=None if original_row is None else original_row["source_coordinate_report_sha256"],
                        source_coordinate_span_index=None if original_row is None else original_row["source_coordinate_span_index"],
                        source_provenance_json=None if original_row is None else original_row["source_provenance_json"],
                        coordinate_transport_status="cache_record_unavailable" if original_row is None else "complete_report_occurrence_replayed")
                records.append(record)
            fence()
        occurrences = []
        for row in inventory["rows"]:
            referenced = [record["reference_id"] for record in records if row["id"] in record["occurrence_ids"]]
            consistent = [record["reference_id"] for record in records if any(
                assoc["occurrence_id"] == row["id"] and assoc["exact_text_sha256_match"] for assoc in record["association_results"])]
            occurrences.append(dict(id=row["id"], cache_reference_ids=referenced, byte_consistent_cache_reference_ids=consistent,
                association_status="declared_cache_associations" if referenced else "no_cache_association", inference_view=None))
        result = dict(schema=SCHEMA_V2 if coordinate_profile else SCHEMA,
            profile=PROFILE_V2 if coordinate_profile else PROFILE, status="complete_declared_cache_record_inventory",
            input_hashes=dict(cache_request_sha256=expected_cache_request_sha256,
                cache_bindings_sha256=expected_cache_bindings_sha256, inventory_report_sha256=report_sha),
            repository_root=str(directory), file_observations=files_before,
            cache_manifest_inventory=manifest_report, inventory_report=inventory,
            bundles=bundles, records=records, occurrences=occurrences,
            coverage=dict(manifest_references=len(manifests), declared_reference_rows=len(records),
                verified_reference_rows=sum(row["record_status"] == "verified" for row in records),
                unavailable_reference_rows=sum(row["record_status"] != "verified" for row in records),
                distinct_physical_table_paths=len({row["manifest"]["tables"]["paired_spans"]["path_in_repo"] for row in manifests}),
                distinct_physical_records=len({row["physical_record_id"] for row in records}),
                record_status_counts={key: sum(row["record_status"] == key for row in records) for key in RECORD_STATUSES},
                association_status_counts={key: sum(row["association_status"] == key for row in records) for key in ASSOCIATION_STATUSES},
                inventory_occurrences=len(occurrences), associated_inventory_occurrences=sum(bool(row["cache_reference_ids"]) for row in occurrences),
                unassociated_inventory_occurrences=sum(not row["cache_reference_ids"] for row in occurrences),
                byte_consistent_inventory_occurrences=sum(bool(row["byte_consistent_cache_reference_ids"]) for row in occurrences),
                full_declared_population_retained=True), entity_definition_intake="not_scanned",
            producer_pins={**{_ROOT_RELATIVE + name + ".py": digest for name, digest in _selected_pins(coordinate_profile).items()},
                _ROOT_RELATIVE + "legal_compact_source_context_cache_intake_v1.py": _SELF_SHA},
            authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))
        if coordinate_profile:
            result["source_compatibility_profile"] = SOURCE_COMPATIBILITY_PROFILE
            result["producer_pins_scope"] = "selected_named_source_checks_not_complete_execution_closure"
            result["coverage"]["coordinate_occurrence_replayed_rows"] = sum(
                row["coordinate_transport_status"] == "complete_report_occurrence_replayed" for row in records)
            result["limitations"].extend([
                "The initial coordinate profile admits one complete paired-v3 manifest and at most 64 physical rows. Its full ordered report bytes occur once in the embedded payload report.",
                "Coordinate occurrence replay and explicit inventory associations are separate observations. No report reference selects an inventory occurrence or authenticates its statutory correspondence, legal meaning or context permission.",
            ])
        fence()
        return json.loads(metadata._wire(result, MAX_REPORT_BYTES))
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing cache/intake original/source custody check also failed.")


def prepare_source_context_cache_intake_v1(cache_request_raw, cache_bindings_raw, *,
        expected_cache_request_sha256, expected_cache_bindings_sha256, manifest_bytes,
        repository_root, inventory_report, inventory_originals):
    """Retain legacy paired-v1/v2 slots and explicit inventory declarations."""
    return _prepare_source_context_cache_intake(cache_request_raw, cache_bindings_raw,
        expected_cache_request_sha256=expected_cache_request_sha256,
        expected_cache_bindings_sha256=expected_cache_bindings_sha256, manifest_bytes=manifest_bytes,
        repository_root=repository_root, inventory_report=inventory_report, inventory_originals=inventory_originals)


def prepare_source_context_cache_intake_v2(cache_request_raw, cache_bindings_raw, *,
        expected_cache_request_sha256, expected_cache_bindings_sha256, manifest_bytes,
        repository_root, inventory_report, inventory_originals):
    """Retain one pinned complete coordinate report and explicit associations.

    Original report bytes live once in the payload companion's UTF8 string;
    canonical outer JSON cannot reorder its nested source metadata. All
    inventory occurrence declarations, opaque targets and permissions retain
    their existing independent roles.
    """
    return _prepare_source_context_cache_intake(cache_request_raw, cache_bindings_raw,
        expected_cache_request_sha256=expected_cache_request_sha256,
        expected_cache_bindings_sha256=expected_cache_bindings_sha256, manifest_bytes=manifest_bytes,
        repository_root=repository_root, inventory_report=inventory_report, inventory_originals=inventory_originals,
        coordinate_profile=True)


def source_context_cache_intake_sha256(report):
    """Bounded whole-report identity only, without following cache paths."""
    coordinate_profile = type(report) is dict and report.get("schema") == SCHEMA_V2
    root, sources, modules = _owners(coordinate_profile)
    try:
        return hashlib.sha256(modules["manifest"]._wire(report, MAX_REPORT_BYTES)).hexdigest()
    finally:
        _need(_sources(root, coordinate_profile) == sources, "producer sources changed during report hashing")


def _validate_source_context_cache_intake(report, cache_request_raw, cache_bindings_raw, *,
        expected_report_sha256, expected_cache_request_sha256, expected_cache_bindings_sha256,
        manifest_bytes, repository_root, inventory_report, inventory_originals, coordinate_profile=False):
    """Regenerate the complete original-bound cache and occurrence populations."""
    _hash(expected_report_sha256, "cache intake report")
    root, sources, modules = _owners(coordinate_profile)
    metadata = modules["manifest"]
    original = metadata._wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(original).hexdigest() == expected_report_sha256, "cache intake report SHA256 mismatch")
    try:
        replayed = _prepare_source_context_cache_intake(cache_request_raw, cache_bindings_raw,
            expected_cache_request_sha256=expected_cache_request_sha256,
            expected_cache_bindings_sha256=expected_cache_bindings_sha256, manifest_bytes=manifest_bytes,
            repository_root=repository_root, inventory_report=inventory_report, inventory_originals=inventory_originals,
            coordinate_profile=coordinate_profile)
        _need(metadata._wire(replayed, MAX_REPORT_BYTES) == original,
              "cache intake report differs from original-bound replay")
        _need(metadata._wire(report, MAX_REPORT_BYTES) == original, "cache intake report changed during validation")
        return replayed
    finally:
        _need(_sources(root, coordinate_profile) == sources, "producer sources changed during validation")


def validate_source_context_cache_intake_v1(report, cache_request_raw, cache_bindings_raw, *,
        expected_report_sha256, expected_cache_request_sha256, expected_cache_bindings_sha256,
        manifest_bytes, repository_root, inventory_report, inventory_originals):
    """Replay the complete original-bound legacy paired cache population."""
    return _validate_source_context_cache_intake(report, cache_request_raw, cache_bindings_raw,
        expected_report_sha256=expected_report_sha256, expected_cache_request_sha256=expected_cache_request_sha256,
        expected_cache_bindings_sha256=expected_cache_bindings_sha256, manifest_bytes=manifest_bytes,
        repository_root=repository_root, inventory_report=inventory_report, inventory_originals=inventory_originals)


def validate_source_context_cache_intake_v2(report, cache_request_raw, cache_bindings_raw, *,
        expected_report_sha256, expected_cache_request_sha256, expected_cache_bindings_sha256,
        manifest_bytes, repository_root, inventory_report, inventory_originals):
    """Replay the independent complete report, physical rows and declarations."""
    return _validate_source_context_cache_intake(report, cache_request_raw, cache_bindings_raw,
        expected_report_sha256=expected_report_sha256, expected_cache_request_sha256=expected_cache_request_sha256,
        expected_cache_bindings_sha256=expected_cache_bindings_sha256, manifest_bytes=manifest_bytes,
        repository_root=repository_root, inventory_report=inventory_report, inventory_originals=inventory_originals,
        coordinate_profile=True)


__all__ = ["SCHEMA", "PROFILE", "SourceContextCacheIntakeError", "prepare_source_context_cache_intake_v1",
           "source_context_cache_intake_sha256", "validate_source_context_cache_intake_v1",
           "SCHEMA_V2", "PROFILE_V2", "BINDINGS_SCHEMA_V2", "SOURCE_COMPATIBILITY_PROFILE",
           "prepare_source_context_cache_intake_v2", "validate_source_context_cache_intake_v2"]
