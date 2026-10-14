"""Pinned candidate lookup custody and conservative invalidation; no legal gold."""

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.integration.reasoning import legal_ir_symbols as symbols
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode()


def cid(label):
    return cid_for_dag_json({"authored_fixture": label})


def table(document="doc-A", *, definitions=(), aliases=()):
    builder = symbols.LegalIRSymbolTableBuilder(symbol_table_id="authored-table-" + document)
    scope = builder.add_document_scope(document)
    for identity, name in definitions:
        builder.add_definition(
            name,
            symbols.LegalIRSymbolKind.DEFINED_TERM,
            symbol_id=identity,
            scope_id=scope.scope_id,
            document_id=document,
            metadata={"interpretation_status": "unreviewed_caller_declaration"},
        )
    for identity, name, target in aliases:
        builder.add_alias(
            name,
            alias_id=identity,
            target_symbol_id=target,
            symbol_kind=symbols.LegalIRSymbolKind.DEFINED_TERM,
            scope_id=scope.scope_id,
            document_id=document,
        )
    return builder.to_symbol_table().to_dict()


def partition(
    identity,
    document="doc-A",
    *,
    definitions=(),
    aliases=(),
    unavailable=False,
    release="authored-release-2024",
    edition=2024,
    applicability=None,
):
    raw = None if unavailable else wire(table(document, definitions=definitions, aliases=aliases))
    return {
        "partition_id": identity,
        "release_id": release,
        "edition": edition,
        "document_id": document,
        "source_version_cid": cid("source-" + document + "-" + str(edition)),
        "scope_cid": cid("scope-" + document + "-" + str(edition)),
        "applicability_cid": cid("declared-applicability")
        if applicability is None
        else applicability,
        "table_raw": raw,
    }


def expected(partitions):
    return [
        {
            "partition_id": row["partition_id"],
            "table_sha256": None if row["table_raw"] is None else sha(row["table_raw"]),
        }
        for row in partitions
    ]


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution

    return scoped_definition_resolution


def registry(owner, *partitions):
    return owner.build_definition_lookup_registry(list(partitions), expected(list(partitions)))


def query(
    partition_ids,
    *,
    name="covered filer",
    document="doc-A",
    target_document="",
    explicit_scope="",
    identity="authored-reference-A",
):
    reference = symbols.LegalIRSymbolReference(
        reference_id=identity,
        name=name,
        symbol_kind=symbols.LegalIRSymbolKind.DEFINED_TERM,
        scope_id="document:" + document,
        document_id=document,
        explicit_target_document_id=target_document,
        explicit_scope_id=explicit_scope,
        source_node_ids=("authored-use-node",),
        span_ids=("authored-use-span",),
        metadata={"interpretation_status": "unreviewed_caller_declaration"},
    ).to_dict()
    return {
        "reference": reference,
        "partition_ids": list(partition_ids),
        "source_occurrence_cid": cid("source-use-occurrence"),
        "interpretation_cid": cid("unreviewed-interpretation"),
    }


def lookup(owner, value, request):
    raw = wire(request)
    return owner.resolve_definition_lookup(value, raw, sha(raw))


def reseal(value):
    return contracts.seal_record(
        {key: item for key, item in value.items() if key not in {"record_cid", "cid_scope"}}
    )


def observations(manifest):
    pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for row in manifest["artifacts"]:
        for kind, values in row["dependency_pins"].items():
            pins[kind].update({pin["key"]: pin["sha256"] for pin in values})
    return {
        "expected_manifest_sha256": manifest["manifest_sha256"],
        "observed_artifact_sha256s": {
            row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]
        },
        "observed_pins": pins,
    }


def test_explicit_cross_document_resolution_preserves_raw_tables_exact_owner_result_and_candidate_status(
    owner,
):
    local = partition("local", definitions=(("term:local", "covered filer"),))
    external = partition("external", "doc-B", definitions=(("term:external", "covered filer"),))
    value = registry(owner, local, external)
    request = query(["local", "external"], target_document="doc-B")
    result = lookup(owner, value, request)
    assert result["status"] == "resolved"
    assert result["selected_symbol_id"] == "term:external"
    reference = symbols.LegalIRSymbolReference.from_dict(request["reference"])
    actual = symbols.resolve_legal_ir_symbol(
        symbols.LegalIRSymbolTable.from_dict(json.loads(local["table_raw"])),
        reference,
        external_symbol_tables=(
            symbols.LegalIRSymbolTable.from_dict(json.loads(external["table_raw"])),
        ),
    )
    assert result["owner_resolution"] == actual.to_dict()
    assert result["reference"] == request["reference"]
    assert result["query_json"] == wire(request).decode()
    assert result["query_sha256"] == sha(wire(request))
    assert [row["partition_id"] for row in result["partition_refs"]] == ["local", "external"]
    assert [row["table_json"] for row in value["partitions"]] == [
        local["table_raw"].decode(),
        external["table_raw"].decode(),
    ]
    for record in (value, result):
        for flag in (
            "admitted",
            "formalized",
            "source_semantics_verified",
            "proof_authority",
            "training_qualified",
        ):
            assert record[flag] is False


def test_two_equal_names_are_ambiguous_without_selecting_one_or_equating_definitions(owner):
    local = partition(
        "local", definitions=(("term:first", "covered filer"), ("term:second", "covered filer"))
    )
    result = lookup(owner, registry(owner, local), query(["local"]))
    assert result["status"] == "ambiguous"
    assert result["selected_symbol_id"] is None
    assert set(result["owner_resolution"]["symbol_ids"]) == {"term:first", "term:second"}


def test_known_empty_table_is_a_negative_lookup_and_differs_from_unavailable_content(owner):
    empty = partition("local")
    missing = partition("local", unavailable=True)
    available_result = lookup(owner, registry(owner, empty), query(["local"]))
    unavailable_result = lookup(owner, registry(owner, missing), query(["local"]))
    assert available_result["status"] == "unresolved"
    assert available_result["owner_resolution"] is not None
    assert available_result["partition_refs"][0]["availability"] == "available"
    assert unavailable_result["status"] == "unavailable"
    assert unavailable_result["owner_resolution"] is None
    assert unavailable_result["partition_refs"][0]["availability"] == "unavailable"
    assert (
        available_result["selected_symbol_id"] is unavailable_result["selected_symbol_id"] is None
    )


def test_unavailable_searched_external_table_prevents_selection_of_an_available_local_match(owner):
    local = partition("local", definitions=(("term:local", "covered filer"),))
    missing = partition("external", "doc-B", unavailable=True)
    result = lookup(owner, registry(owner, local, missing), query(["local", "external"]))
    assert result["status"] == "unavailable"
    assert result["selected_symbol_id"] is None
    assert result["owner_resolution"] is not None
    assert result["owner_resolution"]["status"] == "resolved"


def test_literal_unicode_names_preserve_the_explicit_existing_ascii_token_policy(owner):
    local = partition("local", definitions=(("term:cafe", "café"),))
    value = registry(owner, local)
    assert "café" in value["partitions"][0]["table_json"]
    accented = lookup(owner, value, query(["local"], name="café"))
    unaccented = lookup(owner, value, query(["local"], name="cafe"))
    assert accented["reference"]["name"] == "café"
    assert accented["reference"]["normalized_name"] == "caf"
    assert accented["status"] == "resolved"
    assert accented["selected_symbol_id"] == "term:cafe"
    assert unaccented["status"] == "unresolved"
    assert "ascii" in value["normalization_policy"].lower()
    # Existing ASCII normalization merges these lookup keys only; both caller
    # definitions and their separate literal spelling/identity remain retained.
    competitor = partition("local", definitions=(("term:unicode", "café"), ("term:ascii", "caf")))
    ambiguous = lookup(owner, registry(owner, competitor), query(["local"], name="café"))
    assert ambiguous["status"] == "ambiguous"
    assert set(ambiguous["owner_resolution"]["symbol_ids"]) == {"term:unicode", "term:ascii"}


def test_alias_resolution_retains_exact_alias_chain_and_cycles_remain_unresolved(owner):
    local = partition(
        "local",
        definitions=(("term:records", "public records"),),
        aliases=(("alias:records", "records", "term:records"),),
    )
    resolved = lookup(owner, registry(owner, local), query(["local"], name="records"))
    assert resolved["status"] == "resolved"
    assert resolved["selected_symbol_id"] == "term:records"
    assert resolved["owner_resolution"]["alias_ids"] == ["alias:records"]
    builder = symbols.LegalIRSymbolTableBuilder(symbol_table_id="authored-cycle")
    scope = builder.add_document_scope("doc-A")
    for first, second in (("cycle a", "cycle b"), ("cycle b", "cycle a")):
        builder.add_alias(
            first,
            target_name=second,
            alias_id="alias:" + first.replace(" ", "-"),
            symbol_kind=symbols.LegalIRSymbolKind.DEFINED_TERM,
            scope_id=scope.scope_id,
            document_id="doc-A",
        )
    cyclic = partition("local")
    cyclic["table_raw"] = wire(builder.to_symbol_table().to_dict())
    result = lookup(owner, registry(owner, cyclic), query(["local"], name="cycle a"))
    assert result["status"] == "unresolved"
    assert result["selected_symbol_id"] is None
    assert any(row["code"] == "alias_cycle" for row in result["owner_resolution"]["diagnostics"])


@pytest.mark.parametrize("difference", ["release_id", "edition", "applicability_cid"])
def test_route_cannot_mix_release_edition_or_declared_applicability(owner, difference):
    local = partition("local")
    external = partition("external", "doc-B", definitions=(("term:external", "covered filer"),))
    external[difference] = {
        "release_id": "different-release",
        "edition": 2025,
        "applicability_cid": cid("different-applicability"),
    }[difference]
    value = registry(owner, local, external)
    with pytest.raises(ValueError):
        lookup(owner, value, query(["local", "external"], target_document="doc-B"))


def test_other_scope_versions_have_distinct_registry_and_lookup_identities(owner):
    first = partition("local", definitions=(("term:local", "covered filer"),))
    second = deepcopy(first)
    second["release_id"] = "authored-release-2025"
    second["edition"] = 2025
    second["scope_cid"] = cid("scope-2025")
    second["source_version_cid"] = cid("source-2025")
    old, new = registry(owner, first), registry(owner, second)
    assert old["record_cid"] != new["record_cid"]
    assert (
        lookup(owner, old, query(["local"]))["record_cid"]
        != lookup(owner, new, query(["local"]))["record_cid"]
    )


@pytest.mark.parametrize(
    "damage",
    [
        "wrong_pin",
        "missing_pin",
        "unexpected_population",
        "reordered_population",
        "duplicate_partition",
        "unknown_partition_field",
        "bool_edition",
        "invalid_CID",
        "unavailable_with_hash",
        "available_without_hash",
    ],
)
def test_registry_requires_exact_closed_partition_population_and_independent_hashes(owner, damage):
    rows = [partition("local"), partition("external", "doc-B")]
    pins = expected(rows)
    if damage == "wrong_pin":
        pins[0]["table_sha256"] = "0" * 64
    elif damage == "missing_pin":
        pins[0].pop("table_sha256")
    elif damage == "unexpected_population":
        pins.append({"partition_id": "missing", "table_sha256": None})
    elif damage == "reordered_population":
        pins.reverse()
    elif damage == "duplicate_partition":
        rows.append(deepcopy(rows[0]))
        pins = expected(rows)
    elif damage == "unknown_partition_field":
        rows[0]["reviewed"] = True
    elif damage == "bool_edition":
        rows[0]["edition"] = True
    elif damage == "invalid_CID":
        rows[0]["scope_cid"] = "not-a-cid"
    elif damage == "unavailable_with_hash":
        rows[0]["table_raw"] = None
    elif damage == "available_without_hash":
        pins[0]["table_sha256"] = None
    with pytest.raises((ValueError, TypeError)):
        owner.build_definition_lookup_registry(rows, pins)


@pytest.mark.parametrize(
    "damage",
    [
        "schema",
        "unknown_field",
        "omitted_field",
        "duplicate_definition",
        "duplicate_scope",
        "duplicate_alias",
        "missing_scope",
        "missing_parent",
        "foreign_definition_document",
        "foreign_alias_document",
        "normalization_override",
        "alias_normalization_override",
    ],
)
def test_independently_rehashed_tables_cannot_hide_owner_roundtrip_schema_or_identity_defects(
    owner, damage
):
    row = partition(
        "local",
        definitions=(("term:local", "covered filer"),),
        aliases=(("alias:local", "filer", "term:local"),),
    )
    value = json.loads(row["table_raw"])
    if damage == "schema":
        value["schema_version"] = "unsupported-schema"
    elif damage == "unknown_field":
        value["reviewed"] = True
    elif damage == "omitted_field":
        value.pop("resolutions")
    elif damage == "duplicate_definition":
        value["definitions"].append(deepcopy(value["definitions"][0]))
    elif damage == "duplicate_scope":
        value["scopes"].append(deepcopy(value["scopes"][0]))
    elif damage == "duplicate_alias":
        value["aliases"].append(deepcopy(value["aliases"][0]))
    elif damage == "missing_scope":
        value["definitions"][0]["scope_id"] = "missing-scope"
    elif damage == "missing_parent":
        next(scope for scope in value["scopes"] if scope["scope_kind"] == "document")[
            "parent_scope_id"
        ] = "missing-parent"
    elif damage == "foreign_definition_document":
        value["definitions"][0]["document_id"] = "foreign-document"
    elif damage == "foreign_alias_document":
        value["aliases"][0]["document_id"] = "foreign-document"
    elif damage == "normalization_override":
        value["definitions"][0]["normalized_name"] = "different lookup key"
    elif damage == "alias_normalization_override":
        value["aliases"][0]["normalized_alias"] = "different alias key"
    row["table_raw"] = wire(value)
    with pytest.raises((ValueError, TypeError)):
        registry(owner, row)


@pytest.mark.parametrize("kind", ["definition", "alias"])
def test_duplicate_global_definition_or_alias_identity_across_partitions_refuses_instead_of_overwriting(
    owner, kind
):
    if kind == "definition":
        first = partition("local", definitions=(("term:duplicate", "one"),))
        second = partition("external", "doc-B", definitions=(("term:duplicate", "two"),))
    else:
        first = partition(
            "local",
            definitions=(("term:A", "one"),),
            aliases=(("alias:duplicate", "first", "term:A"),),
        )
        second = partition(
            "external",
            "doc-B",
            definitions=(("term:B", "two"),),
            aliases=(("alias:duplicate", "second", "term:B"),),
        )
    with pytest.raises(ValueError):
        registry(owner, first, second)


@pytest.mark.parametrize(
    "damage",
    [
        "wrong_hash",
        "unknown_field",
        "duplicate_route",
        "unknown_partition",
        "wrong_document",
        "unknown_reference_field",
        "missing_scope",
        "normalization_override",
        "bad_source_CID",
    ],
)
def test_query_route_reference_and_source_binding_are_closed_and_independently_pinned(
    owner, damage
):
    value = registry(owner, partition("local"))
    request = query(["local"])
    if damage == "unknown_field":
        request["reviewed"] = True
    elif damage == "duplicate_route":
        request["partition_ids"].append("local")
    elif damage == "unknown_partition":
        request["partition_ids"].append("missing")
    elif damage == "wrong_document":
        request["reference"]["document_id"] = "doc-B"
    elif damage == "unknown_reference_field":
        request["reference"]["unexpected"] = "cannot ignore"
    elif damage == "missing_scope":
        request["reference"]["scope_id"] = "missing-scope"
    elif damage == "normalization_override":
        request["reference"]["normalized_name"] = "different key"
    elif damage == "bad_source_CID":
        request["source_occurrence_cid"] = "bad-cid"
    raw = wire(request)
    with pytest.raises((ValueError, TypeError)):
        owner.resolve_definition_lookup(
            value, raw, "0" * 64 if damage == "wrong_hash" else sha(raw)
        )


def test_unsearched_partition_changes_preserve_unrelated_lookup_identity(owner):
    local = partition("local", definitions=(("term:local", "covered filer"),))
    unrelated = partition("unrelated", "doc-C")
    old = registry(owner, local, unrelated)
    changed = deepcopy(unrelated)
    changed["table_raw"] = wire(table("doc-C", definitions=(("term:new", "other term"),)))
    new = registry(owner, local, changed)
    assert old["record_cid"] != new["record_cid"]
    first = lookup(owner, old, query(["local"]))
    second = lookup(owner, new, query(["local"]))
    assert first == second
    assert first["record_cid"] == second["record_cid"]
    assert first["exhaustive_search_verified"] is False


@pytest.mark.parametrize("change", ["fill_negative", "new_competitor", "fill_unavailable"])
def test_search_table_changes_invalidate_negative_or_positive_dependents_while_unrelated_lookup_survives(
    owner, change
):
    definitions = (("term:local", "covered filer"),) if change == "new_competitor" else ()
    local = partition("local", definitions=definitions)
    external = partition("external", "doc-B", unavailable=change == "fill_unavailable")
    unrelated = partition("unrelated", "doc-C", definitions=(("term:other", "other term"),))
    before = registry(owner, local, external, unrelated)
    affected_query = query(["local", "external"], target_document="doc-B")
    safe_query = query(
        ["unrelated"], name="other term", document="doc-C", identity="authored-safe-query"
    )
    affected = lookup(owner, before, affected_query)
    safe = lookup(owner, before, safe_query)
    old_manifest = owner.build_definition_lookup_dependencies(
        before, [affected, safe], [affected["record_cid"], safe["record_cid"]]
    )
    assert set(
        row["dependency_id"]
        for row in old_manifest["edges"]
        if row["dependent_id"] == "definition-lookup:" + affected["record_cid"]
    ) == {"definition-partition:local", "definition-partition:external"}
    changed = partition("external", "doc-B", definitions=(("term:external", "covered filer"),))
    after = registry(owner, local, changed, unrelated)
    changed_lookup = lookup(owner, after, affected_query)
    safe_after = lookup(owner, after, safe_query)
    assert safe_after == safe
    assert changed_lookup["status"] == "resolved"
    assert changed_lookup["selected_symbol_id"] == "term:external"
    new_manifest = owner.build_definition_lookup_dependencies(
        after,
        [changed_lookup, safe_after],
        [changed_lookup["record_cid"], safe_after["record_cid"]],
    )
    old_observed = observations(old_manifest)
    replacement = next(
        row
        for row in new_manifest["artifacts"]
        if row["artifact_id"] == "definition-partition:external"
    )
    old_observed["observed_artifact_sha256s"][replacement["artifact_id"]] = replacement[
        "artifact_sha256"
    ]
    if change != "fill_unavailable":
        old_observed["observed_pins"]["definition"]["definition-table:external"] = sha(
            changed["table_raw"]
        )
    else:
        # The old unavailable context pin remains null, independently blocking
        # reuse; its stable artifact identity now observes the filled content.
        unchanged = dependencies.invalidate_dependencies(old_manifest, **observations(old_manifest))
        assert "definition-lookup:" + affected["record_cid"] in unchanged["stale_artifact_ids"]
    invalidation = dependencies.invalidate_dependencies(old_manifest, **old_observed)
    assert "definition-partition:external" in invalidation["stale_artifact_ids"]
    assert "definition-lookup:" + affected["record_cid"] in invalidation["stale_artifact_ids"]
    assert (
        "definition-lookup:" + safe["record_cid"]
        in invalidation["reusable_under_declared_dependencies"]
    )
    assert "definition-partition:unrelated" in invalidation["reusable_under_declared_dependencies"]
    assert invalidation["legal_dependency_inventory_exhaustive"] is False


def test_adding_competing_match_to_a_searched_table_invalidates_prior_resolution_and_retains_ambiguity(
    owner,
):
    first = partition("local", definitions=(("term:first", "covered filer"),))
    original = registry(owner, first)
    request = query(["local"])
    resolved = lookup(owner, original, request)
    changed = partition(
        "local", definitions=(("term:first", "covered filer"), ("term:new", "covered filer"))
    )
    revised = registry(owner, changed)
    ambiguous = lookup(owner, revised, request)
    assert resolved["selected_symbol_id"] == "term:first"
    assert ambiguous["status"] == "ambiguous"
    assert ambiguous["selected_symbol_id"] is None
    assert set(ambiguous["owner_resolution"]["symbol_ids"]) == {"term:first", "term:new"}
    manifest = owner.build_definition_lookup_dependencies(
        original, [resolved], [resolved["record_cid"]]
    )
    observed = observations(manifest)
    observed["observed_pins"]["definition"]["definition-table:local"] = sha(changed["table_raw"])
    result = dependencies.invalidate_dependencies(manifest, **observed)
    assert result["stale_artifact_ids"] == [
        "definition-partition:local",
        "definition-lookup:" + resolved["record_cid"],
    ]


def test_explicit_external_scope_is_validated_against_its_target_document(owner):
    local = partition("local")
    external = partition("external", "doc-B", definitions=(("term:external", "covered filer"),))
    result = lookup(
        owner,
        registry(owner, local, external),
        query(["local", "external"], target_document="doc-B", explicit_scope="document:doc-B"),
    )
    assert result["status"] == "resolved"
    assert result["selected_symbol_id"] == "term:external"
    assert result["reference"]["explicit_scope_id"] == "document:doc-B"
    with pytest.raises(ValueError):
        lookup(
            owner,
            registry(owner, local, external),
            query(
                ["local", "external"],
                target_document="doc-B",
                explicit_scope="not-present-in-target",
            ),
        )


def test_alias_cannot_resolve_a_defined_term_query_to_an_actor_symbol(owner):
    builder = symbols.LegalIRSymbolTableBuilder(symbol_table_id="authored-alias-kind-conflict")
    scope = builder.add_document_scope("doc-A")
    builder.add_definition(
        "responsible official",
        symbols.LegalIRSymbolKind.ACTOR,
        symbol_id="actor:responsible-official",
        scope_id=scope.scope_id,
        document_id="doc-A",
    )
    builder.add_alias(
        "covered filer",
        alias_id="alias:wrong-kind",
        target_symbol_id="actor:responsible-official",
        symbol_kind=symbols.LegalIRSymbolKind.DEFINED_TERM,
        scope_id=scope.scope_id,
        document_id="doc-A",
    )
    row = partition("local")
    row["table_raw"] = wire(builder.to_symbol_table().to_dict())
    value = registry(owner, row)
    request = query(["local"])
    # Verify the inherited owner's permissive target-ID behavior actually
    # triggers this counterexample, so the wrapper's refusal is meaningful.
    native_result = symbols.resolve_legal_ir_symbol(
        builder.to_symbol_table(),
        symbols.LegalIRSymbolReference.from_dict(request["reference"]),
    )
    assert native_result.resolved
    assert native_result.symbol_ids == ("actor:responsible-official",)
    with pytest.raises(contracts.CorpusContractError):
        lookup(owner, value, request)


def test_explicit_external_scope_cannot_fall_back_to_a_matching_definition_in_another_scope(owner):
    builder = symbols.LegalIRSymbolTableBuilder(symbol_table_id="authored-external-scope-conflict")
    document_scope = builder.add_document_scope("doc-B")
    requested_scope = builder.add_scope(
        "section:requested-empty",
        symbols.LegalIRScopeKind.SECTION,
        parent_scope_id=document_scope.scope_id,
        document_id="doc-B",
    )
    other_scope = builder.add_scope(
        "section:other",
        symbols.LegalIRScopeKind.SECTION,
        parent_scope_id=document_scope.scope_id,
        document_id="doc-B",
    )
    builder.add_definition(
        "covered filer",
        symbols.LegalIRSymbolKind.DEFINED_TERM,
        symbol_id="term:outside-requested-scope",
        scope_id=other_scope.scope_id,
        document_id="doc-B",
    )
    local = partition("local")
    external = partition("external", "doc-B")
    external["table_raw"] = wire(builder.to_symbol_table().to_dict())
    request = query(
        ["local", "external"], target_document="doc-B", explicit_scope=requested_scope.scope_id
    )
    native_result = symbols.resolve_legal_ir_symbol(
        symbols.LegalIRSymbolTable.from_dict(json.loads(local["table_raw"])),
        symbols.LegalIRSymbolReference.from_dict(request["reference"]),
        external_symbol_tables=(builder.to_symbol_table(),),
    )
    assert native_result.resolved
    assert native_result.symbol_ids == ("term:outside-requested-scope",)
    with pytest.raises(contracts.CorpusContractError):
        lookup(owner, registry(owner, local, external), request)


def test_unavailable_external_target_retains_unknown_source_identity_without_guessing_scope(owner):
    local = partition("local")
    unavailable = partition("external", "doc-B", unavailable=True)
    unavailable["source_version_cid"] = None
    result = lookup(
        owner,
        registry(owner, local, unavailable),
        query(["local", "external"], target_document="doc-B", explicit_scope="document:doc-B"),
    )
    assert result["status"] == "unavailable"
    assert result["selected_symbol_id"] is None
    assert result["reference"]["explicit_scope_id"] == "document:doc-B"
    available = partition("external", "doc-B")
    available["source_version_cid"] = None
    with pytest.raises(ValueError):
        registry(owner, available)


@pytest.mark.parametrize(
    "damage",
    ["registry_seal", "partition_seal", "authority", "source_scope", "table_bytes", "producer"],
)
def test_registry_consumption_replays_nested_seals_raw_bytes_and_external_registry_identity(
    owner, damage
):
    original = registry(owner, partition("local", definitions=(("term:local", "covered filer"),)))
    changed = deepcopy(original)
    if damage == "registry_seal":
        changed["normalization_policy"] = "different"
    elif damage == "partition_seal":
        changed["partitions"][0]["scope_cid"] = cid("different-scope")
        changed = reseal(changed)
    elif damage == "authority":
        changed["admitted"] = True
        changed = reseal(changed)
    elif damage == "source_scope":
        changed["partitions"][0]["scope_cid"] = cid("different-scope")
        changed["partitions"][0] = reseal(changed["partitions"][0])
        changed = reseal(changed)
    elif damage == "table_bytes":
        changed["partitions"][0]["table_json"] += " "
        changed["partitions"][0] = reseal(changed["partitions"][0])
        changed = reseal(changed)
    elif damage == "producer":
        changed["producer_pins"][next(iter(changed["producer_pins"]))] = "0" * 64
        changed = reseal(changed)
    with pytest.raises(ValueError):
        owner.validate_definition_lookup_registry(
            changed, expected_registry_cid=original["record_cid"]
        )
    if damage != "source_scope":
        with pytest.raises(ValueError):
            lookup(owner, changed, query(["local"]))


@pytest.mark.parametrize(
    "damage",
    [
        "selected",
        "status",
        "route_pin",
        "owner_result",
        "source_occurrence",
        "query_text",
        "authority",
    ],
)
def test_resealed_lookup_cannot_change_owner_result_route_or_evidence_without_exact_replay(
    owner, damage
):
    value = registry(owner, partition("local", definitions=(("term:local", "covered filer"),)))
    request = query(["local"])
    original = lookup(owner, value, request)
    changed = deepcopy(original)
    if damage == "selected":
        changed["selected_symbol_id"] = "term:other"
    elif damage == "status":
        changed["status"] = "unresolved"
    elif damage == "route_pin":
        changed["partition_refs"][0]["table_sha256"] = "0" * 64
    elif damage == "owner_result":
        changed["owner_resolution"]["symbol_ids"] = ["term:other"]
    elif damage == "source_occurrence":
        changed["source_occurrence_cid"] = cid("other-occurrence")
    elif damage == "query_text":
        changed["query_json"] += " "
    elif damage == "authority":
        changed["semantic_definition_binding_verified"] = True
    with pytest.raises(ValueError):
        owner.validate_definition_lookup(
            reseal(changed),
            value,
            query_raw=wire(request),
            expected_query_sha256=sha(wire(request)),
        )


@pytest.mark.parametrize(
    "damage", ["missing", "reordered", "duplicate", "wrong_CID", "changed_lookup"]
)
def test_dependency_manifest_requires_complete_ordered_independent_lookup_CIDs(owner, damage):
    value = registry(owner, partition("local"))
    first = lookup(owner, value, query(["local"]))
    second = lookup(
        owner, value, query(["local"], name="different term", identity="different-reference")
    )
    lookups = [first, second]
    pins = [row["record_cid"] for row in lookups]
    if damage == "missing":
        pins.pop()
    elif damage == "reordered":
        pins.reverse()
    elif damage == "duplicate":
        lookups = [first, first]
        pins = [first["record_cid"], first["record_cid"]]
    elif damage == "wrong_CID":
        pins[0] = cid("not-the-lookup")
    elif damage == "changed_lookup":
        lookups[0] = reseal({**first, "status": "resolved", "selected_symbol_id": "term:invented"})
    with pytest.raises(ValueError):
        owner.build_definition_lookup_dependencies(value, lookups, pins)


def test_table_item_and_aggregate_envelope_bounds_refuse_whole_input_without_truncation(
    owner, monkeypatch
):
    row = partition("local", definitions=(("term:first", "one"), ("term:second", "two")))
    monkeypatch.setattr(owner, "MAX_TABLE_ITEMS", 1)
    with pytest.raises(ValueError):
        registry(owner, row)
    monkeypatch.setattr(owner, "MAX_TABLE_ITEMS", 256)
    oversized = partition("local")
    oversized["table_raw"] += b" " * contracts.MAX_RECORD_BYTES
    with pytest.raises(ValueError):
        registry(owner, oversized)


def test_stored_review_metadata_is_preserved_without_granting_lookup_authority(owner):
    row = partition("local", definitions=(("term:local", "covered filer"),))
    stored = json.loads(row["table_raw"])
    stored["metadata"] = {
        "reviewed": True,
        "source_authenticity_verified": True,
        "note": "Caller-supplied opaque metadata is not verification.",
    }
    row["table_raw"] = wire(stored)
    value = registry(owner, row)
    assert json.loads(value["partitions"][0]["table_json"])["metadata"] == stored["metadata"]
    result = lookup(owner, value, query(["local"]))
    assert result["status"] == "resolved"
    assert all(result[key] is False for key in owner.FALSE_FLAGS)


def test_duplicate_JSON_keys_are_refused_even_under_repaired_external_hash(owner):
    row = partition("local")
    raw = row["table_raw"]
    assert raw.startswith(b"{")
    row["table_raw"] = b'{"schema_version":"hidden-duplicate",' + raw[1:]
    with pytest.raises(ValueError):
        registry(owner, row)


def test_public_lookup_import_does_not_initialize_numerical_models_or_symbol_owner():
    script = """
import json
import sys
from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution
forbidden = [name for name in sys.modules if name.startswith((
    'torch', 'transformers', 'sentence_transformers',
    'ipfs_datasets_py.logic.integration.reasoning',
    'ipfs_datasets_py.logic.backends.process',
))]
print(json.dumps(forbidden))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[4],
        env=dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1"),
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert json.loads(result.stdout) == []
