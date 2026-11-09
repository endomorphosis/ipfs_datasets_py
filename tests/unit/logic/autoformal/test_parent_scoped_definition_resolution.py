"""Parent lookup transports declarations; it never supplies governing authority."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution as owner
from ipfs_datasets_py.logic.integration.reasoning import legal_ir_symbols as symbols
from tests.unit.logic.autoformal.test_scoped_definition_resolution import (
    cid, expected, observations, partition as official_partition, query, reseal, sha, table, wire,
)


def partition(identity, document="doc-A", *, definitions=(), unavailable=False):
    raw = None if unavailable else wire(table(document, definitions=definitions))
    return {
        "partition_id": identity,
        "release_id": "parquet:authored-repo@revision;sha256=" + sha(document.encode()),
        "edition": "not_declared_in_source_artifact",
        "document_id": document,
        "source_version_cid": cid("source-" + document),
        "scope_cid": cid("scope-" + document),
        "preparation_cid": cid("preparation-" + document),
        "parent_manifest_cid": cid("manifest-" + document),
        "root_source_occurrence_cid": cid("root-" + document),
        "companion_record_cid": cid("companion-" + document),
        "source_binding_sha256": sha(("binding-" + document).encode()),
        "table_raw": raw,
    }


def registry(*rows):
    return owner.build_parent_definition_lookup_registry_v1(list(rows), expected(rows))


def lookup(value, request):
    raw = wire(request)
    return owner.resolve_parent_definition_lookup_v1(value, raw, sha(raw))


def manifest(value, *results):
    return owner.build_parent_definition_lookup_dependencies_v1(
        value, list(results), [row["record_cid"] for row in results])


def test_explicit_parent_route_reuses_actual_symbol_resolver_and_preserves_unknown_edition():
    local = partition("local", definitions=(("term:local", "covered filer"),))
    donor = partition("donor", "doc-B", definitions=(("term:donor", "covered filer"),))
    value = registry(local, donor)
    request = query(["local", "donor"], target_document="doc-B", explicit_scope="document:doc-B")
    with patch.object(symbols, "resolve_legal_ir_symbol", wraps=symbols.resolve_legal_ir_symbol) as call:
        result = lookup(value, request)
    assert call.call_count == 1
    assert result["status"] == "resolved" and result["selected_symbol_id"] == "term:donor"
    actual = symbols.resolve_legal_ir_symbol(
        symbols.LegalIRSymbolTable.from_dict(json.loads(local["table_raw"])),
        symbols.LegalIRSymbolReference.from_dict(request["reference"]),
        external_symbol_tables=[symbols.LegalIRSymbolTable.from_dict(json.loads(donor["table_raw"]))],
    ).to_dict()
    assert result["owner_resolution"] == actual
    assert value["schema"] == owner.PARENT_REGISTRY_SCHEMA
    assert result["schema"] == owner.PARENT_LOOKUP_SCHEMA
    assert value["partitions"][0]["release_id"] != value["partitions"][1]["release_id"]
    for row, original in zip(value["partitions"], [local, donor], strict=True):
        assert row["schema"] == owner.PARENT_PARTITION_SCHEMA
        assert row["edition"] == "not_declared_in_source_artifact"
        assert "applicability_cid" not in row
        for field, expected_value in original.items():
            if field != "table_raw":
                assert row[field] == expected_value
    for record in (value, result):
        for flag in owner.PARENT_FALSE_FLAGS:
            assert record[flag] is False
    assert owner.validate_parent_definition_lookup_registry_v1(value, value["record_cid"]) == value
    assert owner.validate_parent_definition_lookup_v1(result, value, wire(request), sha(wire(request))) == result


def test_parent_empty_unavailable_and_ambiguous_are_distinct_without_fabricated_selection():
    empty = lookup(registry(partition("local")), query(["local"]))
    unavailable = lookup(registry(partition("local", unavailable=True)), query(["local"]))
    ambiguous = lookup(registry(partition("local", definitions=(
        ("term:first", "covered filer"), ("term:second", "covered filer")))), query(["local"]))
    assert [row["status"] for row in (empty, unavailable, ambiguous)] == ["unresolved", "unavailable", "ambiguous"]
    assert empty["owner_resolution"] is not None
    assert unavailable["owner_resolution"] is None
    assert set(ambiguous["owner_resolution"]["symbol_ids"]) == {"term:first", "term:second"}
    assert all(row["selected_symbol_id"] is None for row in (empty, unavailable, ambiguous))


def test_unavailable_parent_route_retains_local_observation_without_admitting_selection():
    local = partition("local", definitions=(("term:local", "covered filer"),))
    missing = partition("missing", "doc-B", unavailable=True)
    result = lookup(registry(local, missing), query(["local", "missing"]))
    assert result["owner_resolution"]["resolved"] is True
    assert result["status"] == "unavailable" and result["selected_symbol_id"] is None


@pytest.mark.parametrize("direction", ["parent_as_official", "official_as_parent"])
def test_registry_lookup_and_dependency_consumers_refuse_other_profile(direction):
    parent = registry(partition("local", definitions=(("term:A", "covered filer"),)))
    official_row = official_partition("local", definitions=(("term:A", "covered filer"),))
    official = owner.build_definition_lookup_registry([official_row], expected([official_row]))
    raw = wire(query(["local"]))
    parent_result = lookup(parent, query(["local"]))
    official_result = owner.resolve_definition_lookup(official, raw, sha(raw))
    if direction == "parent_as_official":
        actions = [
            lambda: owner.validate_definition_lookup_registry(parent),
            lambda: owner.resolve_definition_lookup(parent, raw, sha(raw)),
            lambda: owner.validate_definition_lookup(parent_result, official),
            lambda: owner.build_definition_lookup_dependencies(parent, [parent_result], [parent_result["record_cid"]]),
        ]
    else:
        actions = [
            lambda: owner.validate_parent_definition_lookup_registry_v1(official),
            lambda: owner.resolve_parent_definition_lookup_v1(official, raw, sha(raw)),
            lambda: owner.validate_parent_definition_lookup_v1(official_result, parent),
            lambda: owner.build_parent_definition_lookup_dependencies_v1(official, [official_result], [official_result["record_cid"]]),
        ]
    for action in actions:
        with pytest.raises(contracts.CorpusContractError):
            action()


@pytest.mark.parametrize("edition", [2024, True, None, "2024", "unknown", "not_declared_in_source_artifact "])
def test_parent_edition_is_never_coerced_to_an_official_or_invented_value(edition):
    row = partition("local")
    row["edition"] = edition
    with pytest.raises(contracts.CorpusContractError):
        registry(row)


@pytest.mark.parametrize("field", [
    "source_version_cid", "scope_cid", "preparation_cid", "parent_manifest_cid",
    "root_source_occurrence_cid", "companion_record_cid", "source_binding_sha256",
])
def test_parent_source_references_require_valid_explicit_commitments(field):
    row = partition("local")
    row[field] = None
    with pytest.raises(contracts.CorpusContractError):
        registry(row)


@pytest.mark.parametrize("field", [
    "release_id", "source_version_cid", "scope_cid", "preparation_cid", "parent_manifest_cid",
    "root_source_occurrence_cid", "companion_record_cid", "source_binding_sha256",
])
def test_changed_parent_metadata_invalidates_lookup_even_with_identical_table_bytes(field):
    original = partition("local", definitions=(("term:A", "covered filer"),))
    before = registry(original)
    result = lookup(before, query(["local"]))
    old_manifest = manifest(before, result)
    changed = deepcopy(original)
    changed[field] = (
        "different-explicit-release" if field == "release_id" else
        sha(b"different-binding") if field == "source_binding_sha256" else cid("different-" + field))
    after = registry(changed)
    new_result = lookup(after, query(["local"]))
    assert after["record_cid"] != before["record_cid"]
    assert new_result["record_cid"] != result["record_cid"]
    assert after["partitions"][0]["table_sha256"] == before["partitions"][0]["table_sha256"]
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_parent_definition_lookup_registry_v1(after, before["record_cid"])
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_parent_definition_lookup_v1(result, after)
    new_manifest = manifest(after, new_result)
    old_observed = observations(old_manifest)
    replacement = next(row for row in new_manifest["artifacts"]
                       if row["artifact_id"] == "parent-definition-partition:local")
    old_observed["observed_artifact_sha256s"][replacement["artifact_id"]] = replacement["artifact_sha256"]
    invalidation = dependencies.invalidate_dependencies(old_manifest, **old_observed)
    assert "parent-definition-partition:local" in invalidation["stale_artifact_ids"]
    assert "parent-definition-lookup:" + result["record_cid"] in invalidation["stale_artifact_ids"]


@pytest.mark.parametrize("change", ["fill_empty", "fill_unavailable", "add_competitor"])
def test_changed_searched_parent_population_invalidates_its_lookup_and_preserves_unsearched(change):
    definitions = (("term:A", "covered filer"),) if change == "add_competitor" else ()
    row = partition("local", definitions=definitions, unavailable=change == "fill_unavailable")
    other = partition("other", "doc-C", definitions=(("term:other", "other term"),))
    before = registry(row, other)
    request = query(["local"])
    safe_request = query(["other"], name="other term", document="doc-C", identity="safe")
    result, safe = lookup(before, request), lookup(before, safe_request)
    old_manifest = manifest(before, result, safe)
    added = (("term:A", "covered filer"), ("term:B", "covered filer")) if change == "add_competitor" else (("term:A", "covered filer"),)
    changed = partition("local", definitions=added)
    after = registry(changed, other)
    new_result, safe_after = lookup(after, request), lookup(after, safe_request)
    assert safe_after == safe
    assert new_result["status"] == ("ambiguous" if change == "add_competitor" else "resolved")
    assert new_result["record_cid"] != result["record_cid"]
    new_manifest = manifest(after, new_result, safe_after)
    observed = observations(old_manifest)
    replacement = next(item for item in new_manifest["artifacts"]
                       if item["artifact_id"] == "parent-definition-partition:local")
    observed["observed_artifact_sha256s"][replacement["artifact_id"]] = replacement["artifact_sha256"]
    invalidation = dependencies.invalidate_dependencies(old_manifest, **observed)
    assert "parent-definition-lookup:" + result["record_cid"] in invalidation["stale_artifact_ids"]
    assert "parent-definition-lookup:" + safe["record_cid"] in invalidation["reusable_under_declared_dependencies"]


@pytest.mark.parametrize("damage", ["order", "missing", "duplicate", "hash", "extra_authority", "fake_applicability"])
def test_parent_registry_population_hashes_and_closed_fields_refuse_damage(damage):
    rows = [partition("local"), partition("other", "doc-B")]
    pins = expected(rows)
    if damage == "order": pins.reverse()
    elif damage == "missing": pins.pop()
    elif damage == "duplicate": rows[1]["partition_id"] = rows[0]["partition_id"]
    elif damage == "hash": pins[0]["table_sha256"] = "0" * 64
    elif damage == "extra_authority": rows[0]["admitted"] = True
    elif damage == "fake_applicability": rows[0]["applicability_cid"] = cid("invented")
    with pytest.raises(contracts.CorpusContractError):
        owner.build_parent_definition_lookup_registry_v1(rows, pins)


@pytest.mark.parametrize("flag", ["applicability_verified", "governing_edition_verified", "parent_source_replay_verified", "admitted"])
def test_resealed_parent_authority_cannot_be_promoted(flag):
    value = registry(partition("local", definitions=(("term:A", "covered filer"),)))
    result = lookup(value, query(["local"]))
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_parent_definition_lookup_registry_v1(reseal({**value, flag: True}))
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_parent_definition_lookup_v1(reseal({**result, flag: True}), value)


def test_parent_bounds_preflight_runs_before_loading_symbol_owner(monkeypatch):
    row = partition("local")
    monkeypatch.setattr(owner, "MAX_PARTITIONS", 1)
    with patch.object(owner, "_owners", side_effect=AssertionError("optional owner loaded")):
        with pytest.raises(contracts.CorpusContractError):
            registry(row, partition("other", "doc-B"))
    monkeypatch.setattr(owner, "MAX_PARTITIONS", 32)
    row["table_raw"] += b" " * contracts.MAX_RECORD_BYTES
    with patch.object(owner, "_owners", side_effect=AssertionError("optional owner loaded")):
        with pytest.raises(contracts.CorpusContractError):
            registry(row)


def test_parent_query_cannot_escape_explicit_supplied_partition_or_target_scope():
    local = partition("local")
    donor = partition("donor", "doc-B", definitions=(("term:donor", "covered filer"),))
    value = registry(local, donor)
    for request in (
        query(["local", "omitted"], target_document="doc-B"),
        query(["local", "donor"], target_document="doc-C"),
        query(["local", "donor"], target_document="doc-B", explicit_scope="missing-scope"),
        query(["local", "local"]),
    ):
        with pytest.raises(contracts.CorpusContractError):
            lookup(value, request)
