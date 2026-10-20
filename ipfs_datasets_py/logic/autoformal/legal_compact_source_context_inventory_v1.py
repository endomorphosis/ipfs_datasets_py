"""Original-bound declared source/catalog/access inventory, without permission.

This companion replays the existing complete SourcePartitions inventory and
qualified lexical context owner. It neither supplies an encoder nor authenticates
cache revisions, reviewer declarations, access chronology or legal meaning.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import re
import stat

SCHEMA = "legal-compact-source-context-inventory/v1"
PROFILE = "declared-source-cache-access-consistency/v1"
OCCURRENCES_SCHEMA = "legal-compact-source-context-occurrences/v1"
ACCESS_SCHEMA = "legal-compact-source-context-access/v1"
MAX_POPULATION_BYTES = 128 * 1024
MAX_OCCURRENCES_BYTES = 16 * 1024 * 1024
MAX_CATALOG_BYTES = 512 * 1024
MAX_ACCESS_BYTES = 256 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_ALL_SOURCE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_TEXT_BYTES = 65536
MAX_ROWS = 128
MAX_PARTITION_BYTES = 64 * 1024 * 1024
MAX_INVENTORY_BYTES = 64 * 1024 * 1024
CONTEXT_STATUSES = ("source_unavailable", "access_denied", "access_unavailable",
    "origin_not_allowed", "ambiguous", "no_match", "nominated_for_inspection")
ORIGINS = frozenset({"source_derived", "authored_diagnostic", "target_derived",
    "teacher_target", "identity_sidecar", "unknown"})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_INPUT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_CATALOG_PROBE = b"catalog validation only"
_BASE = "ipfs_datasets_py."
_SOURCE_SPECS = (
    ("lexical", "logic.autoformal.legal_compact_source_context_v1",
     "logic/autoformal/legal_compact_source_context_v1.py",
     "efaa7e3ccc73d572561569e05d02270625076ac9e5708fea2d62d60f7f294dc2"),
    ("compact", "logic.autoformal.legal_compact_content_v1",
     "logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
    ("codec", "optimizers.logic_theorem_optimizer.autoencoder_embedding_production",
     "optimizers/logic_theorem_optimizer/autoencoder_embedding_production.py",
     "735ca0597186e094d736ef58435c82956c4ab805a68fc7a6adbfc0ee21ee889f"),
    ("partitions", "optimizers.logic_theorem_optimizer.autoencoder_source_partitions",
     "optimizers/logic_theorem_optimizer/autoencoder_source_partitions.py",
     "d696c3af565d09be1825a00bdbf979ff97c12bb1a6ab1054564a9946b824875a"),
    ("inventory", "optimizers.logic_theorem_optimizer.autoencoder_uscode_inventory",
     "optimizers/logic_theorem_optimizer/autoencoder_uscode_inventory.py",
     "6aa7330cd20a2eb256561382b78bc4465d3b7607827f53d0b644d9e89afb1f21"),
    (None, None, "optimizers/logic_theorem_optimizer/autoencoder_corpus_index.py",
     "f4b71d03e6341602631387262d0efffb61c95bca40ad5307ecfcda3eb1d169b9"),
    (None, None, "optimizers/logic_theorem_optimizer/autoencoder_uscode_import.py",
     "3ead6dbe0014be69a11c1a9f6c203d62c012a3dd5f5913aa9471eda91574bb70"),
    (None, None, "optimizers/logic_theorem_optimizer/autoencoder_corpus_manifest.py",
     "b067f05b3cfc28cb213a83519530f7148b2a5fa7d5b25809e87e1f7c286f9a5d"),
    (None, None, "optimizers/logic_theorem_optimizer/autoencoder_training_worker.py",
     "bde3bd327df59f2e7557eac8aa2e0989ceb1128bc39918bf8cf46011e7bd9415"),
    (None, None, "optimizers/logic_theorem_optimizer/legal_ir_eval_splits.py",
     "495a988ea30679187a8b695f5ec50e2fa24729064ebccc3d623cd90c78240dce"),
)
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "legal_roles_verified",
    "cache_revision_authenticated", "cache_records_reverified", "reviewer_authenticated",
    "context_permission_verified", "context_independence_verified", "context_timing_verified",
    "inference_permission_verified", "permitted_inference_context_verified",
    "shared_definition_closure_verified", "global_holdout_verified",
    "source_encoder_authenticated", "runtime_computation_proven", "runtime_cryptographically_attested",
    "source_authority_authenticated", "source_equivalence_proven", "training_qualified",
    "evaluation_gold_qualified", "legal_accuracy_established", "convergence_proved",
    "accepted", "admitted", "Lean_admitted", "model_executed", "training_executed",
    "target_read", "database_executed", "prover_executed"), False)
_LIMITATIONS = [
    "The complete population is the independently supplied finite selection, not a global corpus or complete real-cache scan.",
    "SourcePartitions replays full declared metadata, including excluded connectors. Its grouping excludes shared governing-definition/context closure and grants no global holdout or unseen-lineage claim.",
    "Cache revisions, access dispositions and review-record hashes are caller declarations. Declared allow does not establish authenticated permission, chronology or target independence; every effective inference view stays null.",
    "Lexical matches nominate supplied catalog predicates. Ordered roles and signature declarations remain caller supplied, not verified legal meanings or automatic prose formalizations.",
    "The fixed catalog-validation probe is diagnostic only: its matches and context are discarded and add no population, source or nomination credit.",
    "No encoder receipt or vector is supplied, attached or produced. Existing generation, source-binding and batch v1 reports remain unchanged.",
    "Named source fences do not authenticate arbitrary preloaded bytecode, mutable Python methods or native binaries. Replacing all original artifacts and expected pins denotes a different operation this consistency API cannot distinguish.",
]


class CompactSourceContextInventoryError(ValueError):
    """A bound, original pin, physical join or original-bound replay differs."""


def _need(ok, message):
    if not ok:
        raise CompactSourceContextInventoryError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _text(value, label, maximum=256):
    _need(type(value) is str and bool(value.strip()) and len(value) <= maximum,
          "bounded plain text required: " + label)
    try:
        raw = value.encode("utf-8")
    except UnicodeError as error:
        raise CompactSourceContextInventoryError("exact UTF8 required: " + label) from error
    _need(len(raw) <= maximum and b"\x00" not in raw, "bounded plain text required: " + label)


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _raw_pin(raw, expected, maximum, label):
    _hash(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent " + label + " SHA256 mismatch")


def _source_pin(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path
          and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
          "canonical unaliased producer source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 512 * 1024,
          "bounded single-link producer source required")
    raw = path.read_bytes()
    after = path.lstat()
    witness = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size,
                            item.st_mtime_ns, item.st_ctime_ns)
    _need(witness(before) == witness(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "producer source changed or fixed pin differs")
    return witness(after)


def _sources(root=None):
    if root is None:
        for parent in _SELF_PATH.parents:
            for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
                if (candidate / _SOURCE_SPECS[0][2]).is_file():
                    root = candidate
                    break
            if root is not None:
                break
    _need(root is not None and root.resolve(strict=True) == root, "canonical existing owner tree required")
    sources = {str(_SELF_PATH): _source_pin(_SELF_PATH, _SELF_SHA)}
    for _, _, relative, expected in _SOURCE_SPECS:
        sources[str(root / relative)] = _source_pin(root / relative, expected)
    return root, sources


def _owners():
    root, before = _sources()
    modules = {}
    for key, name, relative, _ in _SOURCE_SPECS:
        if key is not None:
            module = importlib.import_module(_BASE + name)
            _need(type(getattr(module, "__file__", None)) is str
                  and Path(module.__file__).absolute() == root / relative,
                  "genuine canonical owner import required")
            modules[key] = module
    _need(_sources(root) == (root, before), "producer sources changed during imports")
    return root, before, modules


def _partition_state(partitions, modules, entries=()):
    _need(type(partitions) is modules["partitions"].SourcePartitions,
          "exact existing SourcePartitions required")
    inventory = partitions.inventory
    _need(type(inventory) is modules["inventory"].USCodeSourceInventory,
          "exact existing USCodeSourceInventory required")
    raw, inventory_raw = partitions.to_bytes(), inventory.to_bytes()
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_PARTITION_BYTES
          and type(inventory_raw) is bytes and 0 < len(inventory_raw) <= MAX_INVENTORY_BYTES,
          "bounded complete partition and inventory bytes required")
    _need(type(partitions.limits) is modules["partitions"].SourcePartitionLimits
          and type(inventory.limits) is modules["inventory"].InventoryLimits,
          "exact bounded partition/inventory limits required")
    compact = modules["compact"]
    return (raw, inventory_raw, partitions.sha256, inventory.sha256,
        compact._wire(asdict(partitions.limits), 4096), compact._wire(asdict(inventory.limits), 4096),
        compact._wire(partitions.verification_summary(), 16384),
        compact._wire([partitions.binding_for(entry) for entry in entries], MAX_POPULATION_BYTES))


def _replay_partitions(partitions, expected, modules):
    _hash(expected, "source partitions")
    state = _partition_state(partitions, modules)
    _need(hashlib.sha256(state[0]).hexdigest() == state[2] == expected
          and hashlib.sha256(state[1]).hexdigest() == state[3],
          "source partitions differ from independent SHA256")
    inventory = modules["inventory"].USCodeSourceInventory(state[1], partitions.inventory.limits)
    replayed = modules["partitions"].SourcePartitions(state[0], inventory, partitions.limits)
    _need(_partition_state(replayed, modules) == state, "source partitions differ from original replay")
    return replayed


def _request(request, identity, modules):
    _keys(request, {"occurrence_id", "input"}, "source request")
    _need(request["occurrence_id"] == identity, "source request occurrence differs from population")
    item = request["input"]
    _keys(item, {"input_id", "source", "title", "section", "text", "citation"}, "public EmbeddingInput")
    _need(type(item["input_id"]) is str and _INPUT_ID.fullmatch(item["input_id"]) is not None,
          "exact derived input identity required")
    for key in ("title", "section", "citation"):
        _text(item[key], "input " + key, 4096)
    _text(item["text"], "input text", MAX_SOURCE_TEXT_BYTES)
    source = item["source"]
    _keys(source, {"artifact", "source_kind", "release_id", "document_id", "language", "citation",
                   "byte_start", "byte_end", "normalization"}, "public source span")
    for key in ("source_kind", "release_id", "document_id", "language", "citation", "normalization"):
        _text(source[key], "source " + key, 4096)
    _need(type(source["byte_start"]) is int and type(source["byte_end"]) is int,
          "plain integer source selector required")
    descriptor = source["artifact"]
    _keys(descriptor, {"sha256", "bytes"}, "source artifact descriptor")
    _hash(descriptor["sha256"], "source artifact")
    _need(type(descriptor["bytes"]) is int and 0 < descriptor["bytes"] <= MAX_SOURCE_BYTES,
          "bounded exact source artifact size required")
    parsed = modules["codec"].EmbeddingInput.from_dict(item)
    _need(modules["compact"]._wire(parsed.to_dict(), MAX_OCCURRENCES_BYTES)
          == modules["compact"]._wire(item, MAX_OCCURRENCES_BYTES), "source request differs from public input replay")
    return parsed


def _originals(raws, hashes, modules, partitions, expected_partitions):
    compact = modules["compact"]
    names = ("population", "occurrences", "catalog", "access")
    limits = (MAX_POPULATION_BYTES, MAX_OCCURRENCES_BYTES, MAX_CATALOG_BYTES, MAX_ACCESS_BYTES)
    population, occurrences, catalog, access = [compact._parse(raw, pin, bound, name)
        for raw, pin, bound, name in zip(raws, hashes, limits, names)]
    _keys(population, {"schema", "partition", "selection_sha256", "rows"}, "population")
    _need(population["schema"] == "legal-relational-batch-population/v1", "existing population schema required")
    _text(population["partition"], "population partition", 128)
    _hash(population["selection_sha256"], "selection")
    rows = population["rows"]
    _need(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "bounded nonempty population rows required")
    ids = []
    for row in rows:
        _keys(row, {"id", "source_sha256", "context_sha256"}, "population occurrence")
        _text(row["id"], "occurrence ID")
        _hash(row["source_sha256"], "population source")
        _hash(row["context_sha256"], "population context")
        _need(row["id"] not in ids, "unique population occurrence IDs required")
        ids.append(row["id"])
    _keys(occurrences, {"schema", "population_sha256", "source_partitions_sha256", "cache_revision", "rows"}, "occurrences")
    _need(occurrences["schema"] == OCCURRENCES_SCHEMA and occurrences["population_sha256"] == hashes[0]
          and occurrences["source_partitions_sha256"] == expected_partitions,
          "occurrences original population/partition binding differs")
    cache = occurrences["cache_revision"]
    _keys(cache, {"repo_id", "revision", "catalog_sha256"}, "cache revision declaration")
    _text(cache["repo_id"], "cache repository", 512)
    _need(type(cache["revision"]) is str and _REVISION.fullmatch(cache["revision"]) is not None
          and cache["catalog_sha256"] == hashes[2], "immutable cache revision/catalog declaration required")
    _need(type(occurrences["rows"]) is list and len(occurrences["rows"]) == len(rows),
          "complete ordered occurrence rows required")
    _keys(access, {"schema", "population_sha256", "occurrences_sha256", "catalog_sha256", "rows"}, "access declaration")
    _need(access["schema"] == ACCESS_SCHEMA and access["population_sha256"] == hashes[0]
          and access["occurrences_sha256"] == hashes[1] and access["catalog_sha256"] == hashes[2],
          "access original population/occurrences/catalog binding differs")
    _need(type(access["rows"]) is list and len(access["rows"]) == len(rows), "complete ordered access rows required")
    replayed = _replay_partitions(partitions, expected_partitions, modules)
    inventory = replayed.inventory.to_dict()
    metadata = {row["entry_cid"]: row["metadata"] for shard in inventory["shards"] for row in shard["rows"]
                if row["status"] == "ready_published_text"}
    entries, selected, bindings, descriptors = [], [], [], {}
    for row, occurrence, permission in zip(rows, occurrences["rows"], access["rows"]):
        _keys(occurrence, {"id", "entry_cid", "source_row_id", "source_request"}, "occurrence row")
        _need(occurrence["id"] == row["id"], "complete ordered occurrence rows required")
        _text(occurrence["entry_cid"], "entry CID", 4096)
        _text(occurrence["source_row_id"], "physical source row ID")
        _need(occurrence["entry_cid"] not in entries, "duplicate selected physical source entry")
        item = _request(occurrence["source_request"], row["id"], modules)
        binding = replayed.binding_for(occurrence["entry_cid"])
        meta = metadata[occurrence["entry_cid"]]
        identity = meta["canonical_identity"]
        _need(binding["source_row_id"] == occurrence["source_row_id"]
              and binding["input_id"] == item.input_id and binding["split"] == population["partition"],
              "occurrence differs from source partition binding")
        text_bytes = item.text.encode("utf-8")
        _need(hashlib.sha256(text_bytes).hexdigest() == row["source_sha256"] == meta["text_sha256"]
              and len(text_bytes) == meta["text_bytes"]
              and item.source.source_kind == "us_code" and item.source.release_id == inventory["release"]["release_id"]
              and item.source.document_id == identity["document_id"]
              and (item.title, item.section, item.citation) == (identity["title"], identity["section"], identity["citation"]),
              "physical source/input/release metadata differs")
        descriptor = occurrence["source_request"]["input"]["source"]["artifact"]
        _need(descriptors.setdefault(descriptor["sha256"], descriptor["bytes"]) == descriptor["bytes"],
              "source digest has inconsistent declared byte sizes")
        _keys(permission, {"id", "disposition", "operation", "origin", "review_record_sha256"}, "access row")
        _need(permission["id"] == row["id"] and type(permission["operation"]) is str
              and permission["operation"] == "inference" and type(permission["disposition"]) is str
              and permission["disposition"] in ("allow", "deny", "unavailable")
              and type(permission["origin"]) is str and permission["origin"] in ORIGINS,
              "complete ordered access declarations required")
        if permission["review_record_sha256"] is not None:
            _hash(permission["review_record_sha256"], "declared review record")
        entries.append(occurrence["entry_cid"])
        selected.append(item)
        bindings.append(binding)
    _need(sum(descriptors.values()) <= MAX_ALL_SOURCE_BYTES, "complete source artifact byte budget exceeded")
    _need(all(partitions.binding_for(entry) == binding for entry, binding in zip(entries, bindings)),
          "source partitions differ from original replay")
    return population, occurrences, catalog, access, replayed, selected, bindings, entries


def _derivations(lexical, catalog_sha256):
    if lexical is None or lexical["context"] is None:
        return []
    context = lexical["context"]
    roles = {row["symbol"]: row["roles"] for row in context["argument_roles"]}
    return [{**mapping, "catalog_sha256": catalog_sha256,
        "lexical_match_indices": [index for index, match in enumerate(lexical["matches"])
                                  if mapping["symbol"] in match["symbols"]],
        "signature_declaration": context["signature"]["symbols"][mapping["selected_index"]],
        "ordered_roles": roles[mapping["symbol"]],
        "role_origin": "caller_declared_catalog_not_verified_legal_roles"}
        for mapping in lexical["index_mapping"]]


def prepare_source_context_inventory_v1(population_raw, occurrences_raw, catalog_raw, access_raw, *,
        expected_population_sha256, expected_occurrences_sha256, expected_catalog_sha256,
        expected_access_sha256, source_partitions, expected_source_partitions_sha256, source_resolver):
    """Replay finite physical membership and declared policy; grant no access.

    The resolver receives a detached exact {sha256,bytes}; return exact bytes or
    None. Every source is checked independently of input.text. A fixed probe
    validates the entire catalog even if all physical sources are unavailable.
    """
    raws = (population_raw, occurrences_raw, catalog_raw, access_raw)
    hashes = (expected_population_sha256, expected_occurrences_sha256, expected_catalog_sha256, expected_access_sha256)
    limits = (MAX_POPULATION_BYTES, MAX_OCCURRENCES_BYTES, MAX_CATALOG_BYTES, MAX_ACCESS_BYTES)
    for raw, expected, limit, name in zip(raws, hashes, limits, ("population", "occurrences", "catalog", "access")):
        _raw_pin(raw, expected, limit, name)
    _hash(expected_source_partitions_sha256, "source partitions")
    _need(callable(source_resolver), "source resolver callable required")
    root, sources, modules = _owners()
    compact, lexical_owner = modules["compact"], modules["lexical"]
    failure, partition_before, entries = None, None, ()
    try:
        population, occurrences, catalog, access, replayed, selected, bindings, entries = _originals(
            raws, hashes, modules, source_partitions, expected_source_partitions_sha256)
        partition_before = _partition_state(source_partitions, modules, entries)

        def fence():
            _need(_sources(root) == (root, sources), "producer sources changed during operation")
            _need(_partition_state(source_partitions, modules, entries) == partition_before,
                  "source partitions changed during operation")

        # No probe result becomes an occurrence or contributes any match credit.
        lexical_owner.prepare_source_context_v1(_CATALOG_PROBE, catalog_raw,
            expected_source_sha256=hashlib.sha256(_CATALOG_PROBE).hexdigest(),
            expected_catalog_sha256=expected_catalog_sha256)
        fence()
        cache, result_rows = {}, []
        for index, (row, occurrence, item, binding, permission) in enumerate(zip(
                population["rows"], occurrences["rows"], selected, bindings, access["rows"])):
            descriptor = occurrence["source_request"]["input"]["source"]["artifact"]
            digest = descriptor["sha256"]
            if digest not in cache:
                detached = dict(descriptor)
                fence()
                try:
                    raw = source_resolver(detached)
                finally:
                    _need(type(detached) is dict and compact._wire(detached, 4096) == compact._wire(descriptor, 4096),
                          "source resolver mutated artifact descriptor")
                    fence()
                _need(raw is None or type(raw) is bytes, "source resolver must return exact bytes or None")
                if raw is not None:
                    _need(len(raw) == descriptor["bytes"] and hashlib.sha256(raw).hexdigest() == digest,
                          "source resolver bytes differ from descriptor")
                    try:
                        raw.decode("utf-8")
                    except UnicodeError as error:
                        raise CompactSourceContextInventoryError("source artifact requires exact UTF8") from error
                cache[digest] = raw
            raw = cache[digest]
            lexical, candidate, context_raw_sha, context_sha = None, None, None, None
            if raw is None:
                status = "source_unavailable"
            else:
                selected_raw = raw[item.source.byte_start:item.source.byte_end]
                try:
                    exact_text = selected_raw.decode("utf-8")
                except UnicodeError as error:
                    raise CompactSourceContextInventoryError("source selector requires exact UTF8") from error
                _need(exact_text == item.text, "source selector differs from exact input text")
                if permission["disposition"] == "deny":
                    status = "access_denied"
                elif permission["disposition"] == "unavailable":
                    status = "access_unavailable"
                elif permission["origin"] not in ("source_derived", "authored_diagnostic"):
                    status = "origin_not_allowed"
                else:
                    lexical = lexical_owner.prepare_source_context_v1(selected_raw, catalog_raw,
                        expected_source_sha256=row["source_sha256"], expected_catalog_sha256=expected_catalog_sha256)
                    status = {"ambiguous": "ambiguous", "unavailable": "no_match",
                              "nominated": "nominated_for_inspection"}[lexical["status"]]
                    candidate = lexical["context"]
                    if candidate is not None:
                        context_raw_sha = hashlib.sha256(compact._wire(candidate, MAX_CATALOG_BYTES)).hexdigest()
                        context_sha = lexical["context_sha256"]
            result_rows.append(dict(index=index, id=row["id"], source_request=occurrence["source_request"],
                entry_cid=occurrence["entry_cid"], source_row_id=occurrence["source_row_id"], partition_binding=binding,
                source_status="unavailable" if raw is None else "available", source_bytes_verified=raw is not None,
                source_text_sha256=row["source_sha256"], population_context_sha256=row["context_sha256"],
                access=permission, context_status=status, lexical_report=lexical, candidate_context=candidate,
                compact_context_raw_sha256=context_raw_sha, compact_context_sha256=context_sha,
                symbol_role_derivations=_derivations(lexical, expected_catalog_sha256), inference_view=None,
                encoder_status="not_supplied", authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0))
            fence()
        replayed = _replay_partitions(source_partitions, expected_source_partitions_sha256, modules)
        partition_data = replayed.to_dict()
        summary = replayed.verification_summary()
        result = dict(schema=SCHEMA, profile=PROFILE, status="complete_declared_inventory",
            inputs={name: dict(sha256=pin, bytes=len(raw)) for name, pin, raw in zip(
                ("population", "occurrences", "catalog", "access"), hashes, raws)},
            population=dict(partition=population["partition"], selection_sha256=population["selection_sha256"],
                            ordered_ids=[row["id"] for row in population["rows"]], denominator=len(result_rows)),
            cache_revision=occurrences["cache_revision"],
            source_partitions=dict(sha256=replayed.sha256, bytes=len(replayed.to_bytes()),
                inventory_sha256=replayed.inventory.sha256, inventory_bytes=len(replayed.inventory.to_bytes()),
                grouping_schema=partition_data["grouping_schema"], content_normalization=partition_data["content_normalization"],
                policy=partition_data["policy"], verification_summary=summary),
            catalog_validated=True, catalog_validation=dict(role="fixed_diagnostic_probe_not_population",
                source_sha256=hashlib.sha256(_CATALOG_PROBE).hexdigest()), rows=result_rows,
            coverage=dict(population_rows=len(result_rows), inventory_rows=len(result_rows),
                source_available_rows=sum(row["source_bytes_verified"] for row in result_rows),
                source_unavailable_rows=sum(not row["source_bytes_verified"] for row in result_rows),
                context_status_counts={key: sum(row["context_status"] == key for row in result_rows) for key in CONTEXT_STATUSES},
                nominated_rows=sum(row["context_status"] == "nominated_for_inspection" for row in result_rows),
                inference_view_rows=0, encoder_status_counts={"not_supplied": len(result_rows)}, full_population_retained=True),
            producer_pins={**{relative: sha for _, _, relative, sha in _SOURCE_SPECS},
                           "logic/autoformal/legal_compact_source_context_inventory_v1.py": _SELF_SHA},
            authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))
        fence()
        return json.loads(compact._wire(result, MAX_REPORT_BYTES))
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_sources(root) == (root, sources), "producer sources changed during operation")
            if partition_before is not None:
                _need(_partition_state(source_partitions, modules, entries) == partition_before,
                      "source partitions changed during operation")
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing source/context inventory custody check also failed.")


def source_context_inventory_sha256(report):
    """Bounded canonical identity only; no report validation or promotion."""
    root, sources, modules = _owners()
    try:
        return hashlib.sha256(modules["compact"]._wire(report, MAX_REPORT_BYTES)).hexdigest()
    finally:
        _need(_sources(root) == (root, sources), "producer sources changed during report hashing")


def validate_source_context_inventory_v1(report, population_raw, occurrences_raw, catalog_raw, access_raw, *,
        expected_report_sha256, expected_population_sha256, expected_occurrences_sha256,
        expected_catalog_sha256, expected_access_sha256, source_partitions,
        expected_source_partitions_sha256, source_resolver):
    """Replay all original pins, physical membership and declared dispositions."""
    _hash(expected_report_sha256, "inventory report")
    root, sources, modules = _owners()
    compact = modules["compact"]
    original = compact._wire(report, MAX_REPORT_BYTES)
    _need(hashlib.sha256(original).hexdigest() == expected_report_sha256,
          "independent inventory report SHA256 mismatch")
    try:
        replayed = prepare_source_context_inventory_v1(population_raw, occurrences_raw, catalog_raw, access_raw,
            expected_population_sha256=expected_population_sha256, expected_occurrences_sha256=expected_occurrences_sha256,
            expected_catalog_sha256=expected_catalog_sha256, expected_access_sha256=expected_access_sha256,
            source_partitions=source_partitions, expected_source_partitions_sha256=expected_source_partitions_sha256,
            source_resolver=source_resolver)
        _need(compact._wire(replayed, MAX_REPORT_BYTES) == original,
              "inventory report differs from original-bound replay")
        _need(compact._wire(report, MAX_REPORT_BYTES) == original, "inventory report changed during validation")
        return replayed
    finally:
        _need(_sources(root) == (root, sources), "producer sources changed during validation")


__all__ = ["SCHEMA", "PROFILE", "CompactSourceContextInventoryError", "prepare_source_context_inventory_v1",
           "source_context_inventory_sha256", "validate_source_context_inventory_v1"]
