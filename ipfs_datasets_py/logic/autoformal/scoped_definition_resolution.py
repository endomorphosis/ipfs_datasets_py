"""Declared definition lookup custody through the existing scoped resolver.

This wrapper binds complete caller-supplied tables, including empty tables and
unavailable placeholders. It does not discover governing scopes or legal
precedence. All supplied query partitions are conservative dependencies, not an
exact trace of the resolver's searches. Public import loads no resolver/model.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_bytes

from . import corpus_contracts as contracts

REGISTRY_SCHEMA = "legal-scoped-definition-lookup-registry/v1"
PARTITION_SCHEMA = "legal-scoped-definition-lookup-partition/v1"
LOOKUP_SCHEMA = "legal-scoped-definition-lookup/v1"
PROFILE = "declared-partition-existing-scoped-symbol-resolution/v1"
NORMALIZATION_POLICY = "existing-owner-ascii-alphanumeric-words-lowercase/v1"
RESOLUTION_POLICY = "existing-owner-local-scope-chain-and-explicit-external-document/v1"
BINDING_SCOPE = "complete_supplied_tables_conservative_not_exact_search_trace"
REGISTRY_BINDING = "explicit_query_route_and_complete_supplied_partition_tables"
MAX_PARTITIONS = 32
MAX_LOOKUPS = 128
MAX_SCOPES = 128
MAX_TABLE_ITEMS = 256
FALSE_FLAGS = dict.fromkeys(
    (
        "source_authenticity_verified",
        "source_semantics_verified",
        "governing_scope_verified",
        "context_closure_verified",
        "independently_reviewed",
        "admitted",
        "formalized",
        "training_qualified",
        "proof_authority",
        "backend_executed",
        "lean_compilation_verified",
        "model_executed",
        "exhaustive_search_verified",
        "semantic_definition_binding_verified",
    ),
    False,
)
_INPUT_FIELDS = {
    "partition_id",
    "release_id",
    "edition",
    "document_id",
    "source_version_cid",
    "scope_cid",
    "applicability_cid",
    "table_raw",
}
_PARTITION_FIELDS = (_INPUT_FIELDS - {"table_raw"}) | {
    "table_sha256",
    "table_cid",
    "table_json",
    "availability",
}
_REGISTRY_FIELDS = {
    "profile",
    "symbol_table_schema",
    "normalization_policy",
    "resolution_policy",
    "producer_pins",
    "expected_population",
    "partitions",
    *FALSE_FLAGS,
}
_QUERY_FIELDS = {"reference", "partition_ids", "source_occurrence_cid", "interpretation_cid"}
_LOOKUP_FIELDS = {
    "profile",
    "symbol_table_schema",
    "normalization_policy",
    "resolution_policy",
    "producer_pins",
    "query_json",
    "query_sha256",
    "query_cid",
    "reference",
    "partition_refs",
    "source_occurrence_cid",
    "interpretation_cid",
    "owner_resolution",
    "status",
    "selected_symbol_id",
    "binding_scope",
    "registry_binding",
    *FALSE_FLAGS,
}
_TABLE_FIELDS = {
    "symbol_table_id",
    "scopes",
    "definitions",
    "aliases",
    "references",
    "resolutions",
    "diagnostics",
    "source_map_id",
    "metadata",
    "schema_version",
}


# Parent metadata is declared custody, not authenticated source replay. Consumers
# separately replay the installed parent-review owner with independent identities.
PARENT_REGISTRY_SCHEMA = "legal-parent-scoped-definition-lookup-registry/v1"
PARENT_PARTITION_SCHEMA = "legal-parent-scoped-definition-lookup-partition/v1"
PARENT_LOOKUP_SCHEMA = "legal-parent-scoped-definition-lookup/v1"
PARENT_PROFILE = "declared-parent-partition-existing-scoped-symbol-resolution/v1"
PARENT_UNDECLARED_EDITION = "not_declared_in_source_artifact"
PARENT_FALSE_FLAGS = {
    **FALSE_FLAGS, "applicability_verified": False,
    "governing_edition_verified": False, "parent_source_replay_verified": False,
}
_PARENT_CID_FIELDS = {
    "source_version_cid", "scope_cid", "preparation_cid", "parent_manifest_cid",
    "root_source_occurrence_cid", "companion_record_cid",
}
_PARENT_INPUT_FIELDS = {
    "partition_id", "release_id", "edition", "document_id", "table_raw",
    "source_binding_sha256", *_PARENT_CID_FIELDS,
}
_PARENT_PARTITION_FIELDS = (_PARENT_INPUT_FIELDS - {"table_raw"}) | {
    "table_sha256", "table_cid", "table_json", "availability",
}
_PARENT_REGISTRY_FIELDS = _REGISTRY_FIELDS | set(PARENT_FALSE_FLAGS)
_PARENT_LOOKUP_FIELDS = _LOOKUP_FIELDS | set(PARENT_FALSE_FLAGS)


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _owners():
    from ..integration.reasoning import legal_ir_symbols as symbols
    from . import legal_graph_dependencies as dependencies

    return symbols, dependencies


def _pins(symbols, dependencies):
    from ..integration.reasoning import legal_ir_source_maps as source_maps

    return {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in (symbols, source_maps, dependencies, contracts, cid_utils)
    } | {str(Path(__file__).resolve()): _sha(Path(__file__).read_bytes())}


def _policy(symbols, pins, *, parent=False):
    return {
        "profile": PARENT_PROFILE if parent else PROFILE,
        "symbol_table_schema": symbols.LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION,
        "normalization_policy": NORMALIZATION_POLICY,
        "resolution_policy": RESOLUTION_POLICY,
        "producer_pins": pins,
    }


def _sequence(value, maximum, label, *, nonempty=False):
    if type(value) is not list or not int(nonempty) <= len(value) <= maximum:
        _fail("bounded " + label + " list required")
    return value


def _unique_rows(rows, key, label):
    values = [
        contracts.require_text(row.get(key), label + " identity", max_bytes=512) for row in rows
    ]
    if len(set(values)) != len(values):
        _fail("duplicate " + label + " identity")
    return set(values)


def _table(raw, expected_sha256, document_id, symbols):
    value = contracts.load_record_bytes(raw, expected_sha256=expected_sha256)
    contracts.require_keys(value, _TABLE_FIELDS, "existing owner symbol table")
    if value["schema_version"] != symbols.LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION:
        _fail("existing owner symbol table schema differs")
    contracts.require_text(value["symbol_table_id"], "symbol_table_id", max_bytes=512)
    for key in ("scopes", "definitions", "aliases", "references", "resolutions", "diagnostics"):
        _sequence(value[key], MAX_SCOPES if key == "scopes" else MAX_TABLE_ITEMS, "table " + key)
        if any(type(row) is not dict for row in value[key]):
            _fail("ordinary owner table record objects required")
    try:
        table = symbols.LegalIRSymbolTable.from_dict(value)
        if canonical_dag_json_bytes(table.to_dict()) != canonical_dag_json_bytes(value):
            _fail("table differs from exact canonical owner roundtrip")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        if isinstance(error, contracts.CorpusContractError):
            raise
        raise contracts.CorpusContractError("exact existing owner symbol table required") from error
    scopes = _unique_rows(value["scopes"], "scope_id", "scope")
    definitions = _unique_rows(value["definitions"], "symbol_id", "definition")
    _unique_rows(value["aliases"], "alias_id", "alias")
    _unique_rows(value["references"], "reference_id", "reference")
    _unique_rows(value["resolutions"], "reference_id", "resolution")
    by_scope = {row["scope_id"]: row for row in value["scopes"]}
    for row in value["scopes"]:
        if row["document_id"] != document_id and not (
            row["scope_kind"] == "global" and row["document_id"] == ""
        ):
            _fail("scope document identity differs from explicit partition")
        if row["parent_scope_id"] and row["parent_scope_id"] not in scopes:
            _fail("complete per-table parent scope closure required")
    for row in value["scopes"]:
        seen, current = set(), row["scope_id"]
        while current:
            if current in seen:
                _fail("cyclic parent scope declaration")
            seen.add(current)
            current = by_scope[current]["parent_scope_id"]
    for key in ("definitions", "aliases", "references"):
        for row in value[key]:
            if row["document_id"] != document_id or row["scope_id"] not in scopes:
                _fail("complete per-table document/scope closure required")
            name = row["alias"] if key == "aliases" else row["name"]
            normalized = row["normalized_alias"] if key == "aliases" else row["normalized_name"]
            if normalized != symbols.normalize_legal_symbol_name(name):
                _fail("declared lookup key differs from existing owner normalization")
    reference_ids = {row["reference_id"] for row in value["references"]}
    if any(row["reference_id"] not in reference_ids for row in value["resolutions"]):
        _fail("stored resolution references an omitted reference")
    # Diagnostics and stored resolutions are preserved observations. The query
    # below always delegates fresh resolution; it never adopts stored outcomes.
    validation = symbols.validate_legal_ir_symbol_table(table)
    refused = {
        "duplicate_symbol_id",
        "duplicate_scope_id",
        "duplicate_reference_id",
        "scope_missing",
        "scope_parent_missing",
        "symbol_scope_missing",
        "reference_scope_missing",
    }
    if any(item.code in refused for item in validation.diagnostics):
        _fail("existing owner table structural validation refused")
    if any(not row["name"].strip() for row in value["definitions"]):
        _fail("definition literal name must be explicit")
    return table, definitions


def _build_registry(partition_inputs, expected_population, *, parent=False):
    """Bind exact ordered supplied tables; hashes do not authenticate a registry."""
    input_fields = _PARENT_INPUT_FIELDS if parent else _INPUT_FIELDS
    flags = PARENT_FALSE_FLAGS if parent else FALSE_FLAGS
    _sequence(partition_inputs, MAX_PARTITIONS, "partition input", nonempty=True)
    _sequence(expected_population, MAX_PARTITIONS, "expected partition population", nonempty=True)
    if len(partition_inputs) != len(expected_population):
        _fail("complete expected partition population required")
    expected = contracts.clone_json(expected_population)
    # Check byte pins before parsing any table or loading the existing owner.
    raw_total, ids = 0, set()
    for item, pin in zip(partition_inputs, expected, strict=True):
        contracts.require_keys(item, input_fields, "partition input")
        contracts.require_keys(pin, {"partition_id", "table_sha256"}, "expected partition pin")
        partition_id = contracts.require_text(item["partition_id"], "partition_id", max_bytes=256)
        if partition_id != pin["partition_id"] or partition_id in ids:
            _fail("partition membership/order/multiplicity differs")
        ids.add(partition_id)
        raw = item["table_raw"]
        if raw is None:
            if pin["table_sha256"] is not None:
                _fail("unavailable table requires explicit null expected hash")
        else:
            contracts.require_sha256(pin["table_sha256"], "expected table SHA256")
            if type(raw) is not bytes or len(raw) > contracts.MAX_RECORD_BYTES:
                _fail("bounded immutable table bytes required")
            raw_total += len(raw)
            if raw_total > contracts.MAX_RECORD_BYTES or _sha(raw) != pin["table_sha256"]:
                _fail("table bytes differ from expected pin or aggregate byte bound")
    symbols, dependencies = _owners()
    pins = _pins(symbols, dependencies)
    partitions, all_definitions, all_aliases = [], set(), set()
    for item, pin in zip(partition_inputs, expected, strict=True):
        metadata = contracts.clone_json(
            {key: value for key, value in item.items() if key != "table_raw"}
        )
        for key in ("release_id", "document_id"):
            contracts.require_text(metadata[key], key, max_bytes=512)
        if parent:
            if metadata["edition"] != PARENT_UNDECLARED_EDITION:
                _fail("parent lookup preserves the undeclared source edition literally")
            contracts.require_sha256(metadata["source_binding_sha256"], "source_binding_sha256")
            for key in _PARENT_CID_FIELDS:
                contracts.require_cid(metadata[key], key, codecs=("dag-json",))
        else:
            contracts.require_int(metadata["edition"], "edition", minimum=1, maximum=9999)
            for key in ("source_version_cid", "scope_cid", "applicability_cid"):
                if key == "source_version_cid" and metadata[key] is None and item["table_raw"] is None:
                    continue
                contracts.require_cid(metadata[key], key, codecs=("dag-json",))
        raw = item["table_raw"]
        if raw is not None:
            table, definitions = _table(raw, pin["table_sha256"], metadata["document_id"], symbols)
            aliases = {row.alias_id for row in table.aliases}
            if definitions & all_definitions or aliases & all_aliases:
                _fail("globally duplicate definition or alias identity")
            all_definitions.update(definitions)
            all_aliases.update(aliases)
        partitions.append(
            contracts.seal_record(
                {
                    "schema": PARENT_PARTITION_SCHEMA if parent else PARTITION_SCHEMA,
                    **metadata,
                    "table_sha256": pin["table_sha256"],
                    "table_cid": None if raw is None else cid_for_bytes(raw),
                    "table_json": None if raw is None else raw.decode("utf-8"),
                    "availability": "unavailable" if raw is None else "available",
                }
            )
        )
    result = contracts.seal_record(
        {
            "schema": PARENT_REGISTRY_SCHEMA if parent else REGISTRY_SCHEMA,
            **_policy(symbols, pins, parent=parent),
            "expected_population": expected,
            "partitions": partitions,
            **flags,
        }
    )
    if _pins(symbols, dependencies) != pins:
        _fail("definition lookup producer changed during registry preparation")
    return result


def _validate_registry(registry, expected_registry_cid=None, *, parent=False):
    """Replay its complete byte-bound inputs; optional external CID binds custody."""
    value = contracts.validate_record(registry,
        schema=PARENT_REGISTRY_SCHEMA if parent else REGISTRY_SCHEMA,
        fields=_PARENT_REGISTRY_FIELDS if parent else _REGISTRY_FIELDS)
    if expected_registry_cid is not None and value["record_cid"] != contracts.require_cid(
        expected_registry_cid, "expected_registry_cid", codecs=("dag-json",)
    ):
        _fail("registry differs from independently expected identity")
    _sequence(value["partitions"], MAX_PARTITIONS, "partition", nonempty=True)
    inputs = []
    for partition in value["partitions"]:
        row = contracts.validate_record(
            partition, schema=PARENT_PARTITION_SCHEMA if parent else PARTITION_SCHEMA,
            fields=_PARENT_PARTITION_FIELDS if parent else _PARTITION_FIELDS
        )
        table_json = row["table_json"]
        if table_json is not None:
            contracts.require_text(
                table_json, "table_json", allow_empty=True, max_bytes=contracts.MAX_RECORD_BYTES
            )
        inputs.append(
            {
                **{key: row[key] for key in (_PARENT_INPUT_FIELDS if parent else _INPUT_FIELDS) - {"table_raw"}},
                "table_raw": None if table_json is None else table_json.encode("utf-8"),
            }
        )
    expected = _build_registry(inputs, value["expected_population"], parent=parent)
    if expected != value:
        _fail("registry differs from exact independently byte-pinned replay")
    return expected


def _resolve_lookup(registry, query_raw, expected_query_sha256, *, parent=False):
    """Delegate explicit local/external table resolution, preserving open gaps."""
    query = contracts.load_record_bytes(query_raw, expected_sha256=expected_query_sha256)
    contracts.require_keys(query, _QUERY_FIELDS, "definition lookup query")
    value = _validate_registry(registry, parent=parent)
    symbols, dependencies = _owners()
    pins = _pins(symbols, dependencies)
    if pins != value["producer_pins"]:
        _fail("registry producer pins differ from current lookup owners")
    route = _sequence(query["partition_ids"], MAX_PARTITIONS, "query route", nonempty=True)
    for key in route:
        contracts.require_text(key, "query partition_id", max_bytes=256)
    if len(set(route)) != len(route):
        _fail("duplicate query partition route")
    by_id = {row["partition_id"]: row for row in value["partitions"]}
    if any(key not in by_id for key in route):
        _fail("query route must name supplied explicit partitions")
    partitions = [by_id[key] for key in route]
    if not parent:
        identity = {(row["release_id"], row["edition"], row["applicability_cid"]) for row in partitions}
        if len(identity) != 1:
            _fail("query partitions differ in declared release/edition/applicability")
    # Parent routes nominate lexical candidates across explicitly supplied source
    # partitions. Equal unknown editions do not establish governing compatibility.
    flags = PARENT_FALSE_FLAGS if parent else FALSE_FLAGS
    for key in ("source_occurrence_cid", "interpretation_cid"):
        contracts.require_cid(query[key], key, codecs=("dag-json",))
    try:
        reference = symbols.LegalIRSymbolReference.from_dict(query["reference"])
        if reference.to_dict() != query["reference"]:
            _fail("query reference differs from exact canonical owner roundtrip")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        if isinstance(error, contracts.CorpusContractError):
            raise
        raise contracts.CorpusContractError("closed existing owner reference required") from error
    contracts.require_text(reference.reference_id, "reference_id", max_bytes=512)
    contracts.require_text(reference.name, "reference name", max_bytes=4096)
    if reference.document_id != partitions[0][
        "document_id"
    ] or reference.normalized_name != symbols.normalize_legal_symbol_name(reference.name):
        _fail("query reference document or normalized literal differs")
    if reference.explicit_target_document_id and reference.explicit_target_document_id not in {
        row["document_id"] for row in partitions
    }:
        _fail("explicit target document is outside supplied query route")
    owner_result = None
    available = all(row["availability"] == "available" for row in partitions)
    if partitions[0]["availability"] == "available":
        table, _ = _table(
            partitions[0]["table_json"].encode(),
            partitions[0]["table_sha256"],
            partitions[0]["document_id"],
            symbols,
        )
        if reference.scope_id not in table.scope_by_id:
            _fail("query requires complete local declared scope closure")
        external = [
            _table(row["table_json"].encode(), row["table_sha256"], row["document_id"], symbols)[0]
            for row in partitions[1:]
            if row["availability"] == "available"
        ]
        if reference.explicit_scope_id:
            target_tables = [table, *external]
            if reference.explicit_target_document_id:
                target_tables = [
                    item
                    for item in target_tables
                    if any(
                        scope.document_id == reference.explicit_target_document_id
                        for scope in item.scopes
                    )
                ]
            declared_target_unavailable = any(
                row["availability"] == "unavailable"
                and row["document_id"] == reference.explicit_target_document_id
                for row in partitions
            )
            if (
                not any(reference.explicit_scope_id in item.scope_by_id for item in target_tables)
                and not declared_target_unavailable
            ):
                _fail("explicit target scope is outside supplied declared closure")
        owner_result = symbols.resolve_legal_ir_symbol(
            table, reference, external_symbol_tables=external
        ).to_dict()
        if owner_result["resolved"]:
            definitions = {
                definition.symbol_id: definition
                for item in (table, *external)
                for definition in item.definitions
            }
            selected_definition = definitions.get(owner_result["symbol_ids"][0])
            if selected_definition is None:
                _fail("resolved owner identity is outside supplied definition tables")
            # The existing alias-by-ID and external fallback paths can bypass
            # name-search filters. Refuse contradictions to explicit caller
            # constraints; do not replace the owner outcome with a new search.
            if (
                reference.symbol_kind is not symbols.LegalIRSymbolKind.UNKNOWN
                and selected_definition.symbol_kind is not reference.symbol_kind
            ):
                _fail("resolved definition kind contradicts explicit query kind")
            if (
                reference.explicit_target_document_id
                and selected_definition.document_id != reference.explicit_target_document_id
            ):
                _fail("resolved definition document contradicts explicit query target")
            if (
                reference.explicit_scope_id
                and selected_definition.scope_id != reference.explicit_scope_id
            ):
                _fail("resolved definition scope contradicts explicit query target")
    status = "unavailable" if not available else owner_result["status"]
    selected = owner_result["symbol_ids"][0] if available and owner_result["resolved"] else None
    result = contracts.seal_record(
        {
            "schema": PARENT_LOOKUP_SCHEMA if parent else LOOKUP_SCHEMA,
            **_policy(symbols, pins, parent=parent),
            "query_json": query_raw.decode("utf-8"),
            "query_sha256": expected_query_sha256,
            "query_cid": cid_for_bytes(query_raw),
            "reference": query["reference"],
            "partition_refs": [
                {
                    key: row[key]
                    for key in ("partition_id", "table_sha256", "table_cid", "availability")
                }
                | {"partition_cid": row["record_cid"]}
                for row in partitions
            ],
            "source_occurrence_cid": query["source_occurrence_cid"],
            "interpretation_cid": query["interpretation_cid"],
            "owner_resolution": owner_result,
            "status": status,
            "selected_symbol_id": selected,
            "binding_scope": BINDING_SCOPE,
            "registry_binding": REGISTRY_BINDING,
            **flags,
        }
    )
    if _pins(symbols, dependencies) != pins:
        _fail("definition lookup producer changed during resolution")
    return result


def _validate_lookup(lookup, registry, query_raw=None, expected_query_sha256=None, *, parent=False):
    """Regenerate an outcome; consumers separately retain its expected CID."""
    value = contracts.validate_record(lookup,
        schema=PARENT_LOOKUP_SCHEMA if parent else LOOKUP_SCHEMA,
        fields=_PARENT_LOOKUP_FIELDS if parent else _LOOKUP_FIELDS)
    if query_raw is None:
        contracts.require_text(
            value["query_json"], "query_json", max_bytes=contracts.MAX_RECORD_BYTES
        )
        query_raw = value["query_json"].encode("utf-8")
    if expected_query_sha256 is None:
        expected_query_sha256 = value["query_sha256"]
    expected = _resolve_lookup(registry, query_raw, expected_query_sha256, parent=parent)
    if value != expected:
        _fail("definition lookup differs from complete query/partition replay")
    return expected


def _build_dependencies(registry, lookups, expected_lookup_cids, *, parent=False):
    """Reuse the existing reverse graph over stable partitions and bound lookups."""
    value = _validate_registry(registry, parent=parent)
    _sequence(lookups, MAX_LOOKUPS, "lookup", nonempty=True)
    _sequence(expected_lookup_cids, MAX_LOOKUPS, "expected lookup CID", nonempty=True)
    for cid in expected_lookup_cids:
        contracts.require_cid(cid, "expected_lookup_cid", codecs=("dag-json",))
    if len(set(expected_lookup_cids)) != len(expected_lookup_cids) or len(lookups) != len(
        expected_lookup_cids
    ):
        _fail("complete unique ordered lookup population required")
    checked = [_validate_lookup(row, value, parent=parent) for row in lookups]
    if [row["record_cid"] for row in checked] != expected_lookup_cids:
        _fail("lookup membership/order/multiplicity differs from independent CID pins")
    symbols, dependencies = _owners()
    producer_pins = _pins(symbols, dependencies)
    if producer_pins != value["producer_pins"]:
        _fail("lookup dependency producer differs")
    policy_sha = _sha(
        canonical_dag_json_bytes(
            {
                key: value[key]
                for key in (
                    "profile",
                    "symbol_table_schema",
                    "normalization_policy",
                    "resolution_policy",
                )
            }
        )
    )

    def artifact(identity, row):
        pins = {kind: [] for kind in dependencies.PIN_KINDS}
        pins["policy"] = [{"key": ("parent-" if parent else "") + "scoped-definition-lookup-policy", "sha256": policy_sha}] + [
            {"key": ("parent-" if parent else "") + "lookup-owner:" + path, "sha256": digest}
            for path, digest in sorted(producer_pins.items())
        ]
        return {
            "artifact_id": identity,
            "artifact_sha256": _sha(canonical_dag_json_bytes(row)),
            "dependency_pins": pins,
        }

    artifacts, edges = [], []
    prefix = "parent-" if parent else ""
    for row in value["partitions"]:
        item = artifact(prefix + "definition-partition:" + row["partition_id"], row)
        kind = "context" if row["availability"] == "unavailable" else "definition"
        item["dependency_pins"][kind] = [
            {"key": prefix + "definition-table:" + row["partition_id"], "sha256": row["table_sha256"]}
        ]
        artifacts.append(item)
    for row in checked:
        identity = prefix + "definition-lookup:" + row["record_cid"]
        artifacts.append(artifact(identity, row))
        edges.extend(
            {
                "dependent_id": identity,
                "dependency_id": prefix + "definition-partition:" + ref["partition_id"],
            }
            for ref in row["partition_refs"]
        )
    result = dependencies.build_dependency_manifest(
        artifacts, edges, expected_artifact_ids=[row["artifact_id"] for row in artifacts]
    )
    contracts.clone_json(result)
    if _pins(symbols, dependencies) != producer_pins:
        _fail("definition lookup producer changed during dependency preparation")
    return result


def build_definition_lookup_registry(partition_inputs, expected_population):
    """Bind exact ordered official-profile tables without authenticating them."""
    return _build_registry(partition_inputs, expected_population)


def validate_definition_lookup_registry(registry, expected_registry_cid=None):
    return _validate_registry(registry, expected_registry_cid)


def resolve_definition_lookup(registry, query_raw, expected_query_sha256):
    return _resolve_lookup(registry, query_raw, expected_query_sha256)


def validate_definition_lookup(lookup, registry, query_raw=None, expected_query_sha256=None):
    return _validate_lookup(lookup, registry, query_raw, expected_query_sha256)


def build_definition_lookup_dependencies(registry, lookups, expected_lookup_cids):
    return _build_dependencies(registry, lookups, expected_lookup_cids)


def build_parent_definition_lookup_registry_v1(partition_inputs, expected_population):
    """Bind literal-parent declarations; do not replay or authenticate parents.

    Exact table bytes and ordered populations are retained. The source references
    must be matched to independently replayed parent preparations by consumers.
    An unknown edition is retained literally; it never becomes an official year.
    """
    return _build_registry(partition_inputs, expected_population, parent=True)


def validate_parent_definition_lookup_registry_v1(registry, expected_registry_cid=None):
    """Regenerate the complete declared registry; optional CID binds its custody."""
    return _validate_registry(registry, expected_registry_cid, parent=True)


def resolve_parent_definition_lookup_v1(registry, query_raw, expected_query_sha256):
    """Resolve lexical candidates over a declared route, without applicability.

    Different physical release references remain distinct. Matching unknown
    editions do not authorize a cross-source use or establish shared legal scope.
    """
    return _resolve_lookup(registry, query_raw, expected_query_sha256, parent=True)


def validate_parent_definition_lookup_v1(lookup, registry, query_raw=None, expected_query_sha256=None):
    return _validate_lookup(lookup, registry, query_raw, expected_query_sha256, parent=True)


def build_parent_definition_lookup_dependencies_v1(registry, lookups, expected_lookup_cids):
    """Retain complete partition metadata and all explicit route dependencies."""
    return _build_dependencies(registry, lookups, expected_lookup_cids, parent=True)


__all__ = [
    "build_definition_lookup_registry",
    "validate_definition_lookup_registry",
    "resolve_definition_lookup",
    "validate_definition_lookup",
    "build_definition_lookup_dependencies",
    "build_parent_definition_lookup_registry_v1",
    "validate_parent_definition_lookup_registry_v1",
    "resolve_parent_definition_lookup_v1",
    "validate_parent_definition_lookup_v1",
    "build_parent_definition_lookup_dependencies_v1",
]
