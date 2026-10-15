"""Alias graph transport and actual table-change invalidation retain originals."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_definition_use_v2 as use
from ipfs_datasets_py.logic.autoformal import corpus_graph_exchange as exchange
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution as resolver
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


@lru_cache(maxsize=1)
def authored_fixture():
    spec = importlib.util.spec_from_file_location(
        "authored_alias_inputs_for_graph_exchange",
        Path(__file__).with_name("test_corpus_definition_use_v2.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def original_bytes(data):
    return {
        role + "/" + name + ".bin": raw
        for role in ("donor", "consumer")
        for name, raw in data[role]["evidence"]["candidate_inputs"].items()
    }


def assert_candidate_scope(record):
    assert all(record[flag] is False for flag in use.FALSE_FLAGS)
    assert record["alias_record"]["assumed_not_proved"] is True
    assert (
        record["binding_record"]["lookup_coverage"]
        == "representative_first_occurrence_whole_predicate_assumption"
    )
    assert record["binding_record"]["per_occurrence_lookup_verified"] is False
    assert (
        record["review_status"]
        == "new_combined_use_review_profile_and_actual_reviews_pending"
    )


def observations(manifest):
    pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for artifact in manifest["artifacts"]:
        for kind, values in artifact["dependency_pins"].items():
            for value in values:
                key, digest = value["key"], value["sha256"]
                assert key not in pins[kind] or pins[kind][key] == digest
                pins[kind][key] = digest
    return {
        "expected_manifest_sha256": manifest["manifest_sha256"],
        "observed_artifact_sha256s": {
            artifact["artifact_id"]: artifact["artifact_sha256"]
            for artifact in manifest["artifacts"]
        },
        "observed_pins": pins,
    }


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_validated_alias_graph_cold_parquet_readback_preserves_both_originals(
    tmp_path, family
):
    fixture = authored_fixture()
    data = fixture.fixture(use, family)
    before = deepcopy(data)
    retained_bytes = original_bytes(data)
    assert len(retained_bytes) == 12
    originals = tmp_path / "original-inputs"
    originals.mkdir(mode=0o700)
    for name, raw in retained_bytes.items():
        path = originals / name
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(raw)
    request_raw, inputs = fixture.arguments(data)
    record = use.prepare_definition_use_v2(request_raw, **inputs)
    checked = use.validate_definition_use_candidate_v2(record, request_raw, **inputs)
    assert checked == record
    assert_candidate_scope(record)
    component_raw = canonical_dag_json_bytes(record)
    directory = tmp_path / "alias-graph"
    manifest = exchange.write_graph_bundle(checked["graph"], directory)
    manifest_raw = (directory / "manifest.json").read_bytes()
    assert manifest_raw == canonical_dag_json_bytes(manifest)
    assert {path.name for path in directory.iterdir()} == exchange.BUNDLE_FILES
    program = """
import sys
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes
loaded = load_graph_bundle(sys.argv[1], expected_manifest_sha256=sys.argv[2])
for suffix in ('corpus_definition_use_v2', 'corpus_definition_review_v2',
               'scoped_definition_resolution', 'legal_source_definition_bridge_v2'):
    assert 'ipfs_datasets_py.logic.autoformal.' + suffix not in sys.modules, suffix
for prefix in ('torch', 'transformers', 'tensorflow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
sys.stdout.buffer.write(canonical_dag_json_bytes(loaded))
"""
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-c", program, str(directory), sha(manifest_raw)],
        cwd=tmp_path,
        env=dict(
            os.environ,
            PYTHONPATH=str(root),
            PYTHONDONTWRITEBYTECODE="1",
            IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
            IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
        ),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    loaded = json.loads(result.stdout)
    assert loaded == {"manifest": manifest, "snapshot": record["graph"]}
    graph = loaded["snapshot"]
    nodes = {row["record_cid"]: row for row in graph["nodes"]}
    assert all(
        edge["src_cid"] in nodes and edge["dst_cid"] in nodes
        for edge in graph["edges"]
    )
    uses = [edge for edge in graph["edges"] if edge["relation"] == "USES_DEFINITION"]
    assert len(uses) == 1
    assert nodes[uses[0]["src_cid"]]["node_type"] == "definition_assertion"
    assert nodes[uses[0]["dst_cid"]]["node_type"] == "definition_assertion"
    assert nodes[uses[0]["src_cid"]]["content_cid"] == data["consumer"]["candidate"][
        "definition_record"
    ]["record_cid"]
    assert nodes[uses[0]["dst_cid"]]["content_cid"] == data["donor"]["candidate"][
        "definition_record"
    ]["record_cid"]
    assert set(uses[0]["evidence_cids"]) == {
        record["binding_record"]["record_cid"],
        record["interpretation_record"]["record_cid"],
        data["lookup_inputs"]["expected_lookup_cid"],
    }
    for role in ("donor", "consumer"):
        original_graph = data[role]["candidate"]["graph"]
        assert all(nodes[row["record_cid"]] == row for row in original_graph["nodes"])
        exported_edges = {edge["record_cid"]: edge for edge in graph["edges"]}
        assert all(
            exported_edges[row["record_cid"]] == row
            for row in original_graph["edges"]
        )
    assert not {"norm_assertion", "entity"} & {
        node["node_type"] for node in nodes.values()
    }
    assert all(manifest[flag] is False for flag in exchange._FLAGS)
    assert canonical_dag_json_bytes(record) == component_raw
    assert data == before and original_bytes(data) == retained_bytes
    assert {
        str(path.relative_to(originals)): path.read_bytes()
        for path in originals.rglob("*")
        if path.is_file()
    } == retained_bytes
    assert set(loaded) == {"manifest", "snapshot"}


def test_new_competing_donor_definition_invalidates_component_without_rewriting_sources():
    fixture = authored_fixture()
    data = fixture.fixture(use)
    before = deepcopy(data)
    retained_bytes = original_bytes(data)
    record = fixture.prepare(use, data)
    assert_candidate_scope(record)
    manifest = record["dependency_manifest"]
    current = observations(manifest)
    stable = dependencies.invalidate_dependencies(manifest, **current)
    assert stable["seed_artifact_ids"] == stable["stale_artifact_ids"] == []
    assert set(stable["reusable_under_declared_dependencies"]) == set(
        record["expected_artifact_ids"]
    )

    # Rebuild an actual complete table with the original row and one competitor.
    # Current observations use its real partition/table bytes, not invented hashes.
    changed = deepcopy(data)
    changed["lookup_inputs"] = fixture.lookup_inputs(changed, status="ambiguous")
    original_registry = json.loads(data["lookup_inputs"]["registry_raw"])
    current_registry = json.loads(changed["lookup_inputs"]["registry_raw"])
    old_partitions = {row["partition_id"]: row for row in original_registry["partitions"]}
    new_partitions = {row["partition_id"]: row for row in current_registry["partitions"]}
    assert old_partitions["local"] == new_partitions["local"]
    old_donor, new_donor = old_partitions["donor"], new_partitions["donor"]
    assert old_donor["table_sha256"] == sha(old_donor["table_json"].encode())
    assert new_donor["table_sha256"] == sha(new_donor["table_json"].encode())
    assert old_donor["table_sha256"] != new_donor["table_sha256"]
    old_definitions = json.loads(old_donor["table_json"])["definitions"]
    new_definitions = json.loads(new_donor["table_json"])["definitions"]
    assert len(old_definitions) == 1 and len(new_definitions) == 2
    assert all(row in new_definitions for row in old_definitions)
    donor_id = "definition-partition:donor"
    assert current["observed_artifact_sha256s"][donor_id] == sha(
        canonical_dag_json_bytes(old_donor)
    )
    current["observed_artifact_sha256s"][donor_id] = sha(
        canonical_dag_json_bytes(new_donor)
    )
    current["observed_pins"]["definition"]["definition-table:donor"] = new_donor[
        "table_sha256"
    ]
    invalidation = dependencies.invalidate_dependencies(manifest, **current)
    assert invalidation["seed_artifact_ids"] == [donor_id]
    assert {reason["code"] for reason in invalidation["seed_reasons"][donor_id]} == {
        "artifact_changed",
        "dependency_pin_changed",
    }
    stale = set(invalidation["stale_artifact_ids"])
    old_lookup_id = "definition-lookup:" + data["lookup_inputs"]["expected_lookup_cid"]
    assert {donor_id, old_lookup_id, record["graph"]["record_cid"]} <= stale
    assert record["graph"]["record_cid"] not in invalidation[
        "reusable_under_declared_dependencies"
    ]
    assert any(
        row["dependent_id"] == record["graph"]["record_cid"]
        for row in invalidation["propagation_witnesses"]
    )
    for role in ("donor", "consumer"):
        assert data[role]["candidate"]["graph"]["record_cid"] in invalidation[
            "reusable_under_declared_dependencies"
        ]
    assert dependencies.validate_invalidation(invalidation, manifest, **current) == invalidation

    query = data["lookup_inputs"]["query_raw"]
    fresh_lookup = resolver.resolve_definition_lookup(current_registry, query, sha(query))
    assert fresh_lookup["status"] == "ambiguous"
    assert fresh_lookup["selected_symbol_id"] is None
    assert set(fresh_lookup["owner_resolution"]["symbol_ids"]) == {
        data["request"]["donor_symbol"],
        "fixture:competing-definition",
    }
    assert fresh_lookup == json.loads(changed["lookup_inputs"]["lookup_raw"])
    with pytest.raises(ValueError):
        fixture.prepare(use, changed)
    assert data == before and original_bytes(data) == retained_bytes
    assert original_bytes(changed) == retained_bytes
    assert all(record[flag] is False for flag in use.FALSE_FLAGS)
