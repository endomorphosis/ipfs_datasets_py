"""Combined graph transport and real lookup drift preserve separate originals."""

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

from ipfs_datasets_py.logic.autoformal import corpus_definition_use_review_v2 as review
from ipfs_datasets_py.logic.autoformal import corpus_definition_use_v2 as use
from ipfs_datasets_py.logic.autoformal import corpus_graph_exchange as exchange
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution as resolver
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


@lru_cache(maxsize=1)
def authored_fixtures():
    modules = []
    for filename, name in (
        (
            "test_corpus_definition_use_review_v2.py",
            "authored_combined_review_for_graph_exchange",
        ),
        (
            "test_definition_use_v2_graph_exchange.py",
            "authored_alias_exchange_for_combined_review",
        ),
    ):
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name(filename)
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return tuple(modules)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def signed_fixture(fixture, materialized):
    # These generated fixture keys exercise the real signature verifier. Their
    # authored external-policy shape establishes no actual human/legal review.
    signed = fixture.signed.__wrapped__(review, materialized)
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    fixture._REVIEW.refresh(signed)
    return signed


def assert_authenticated_pair(assessment):
    assert assessment["evidence_assessment_status"] == "authenticated"
    assert assessment["authenticated_evidence_count"] == 2
    assert len(assessment["reviews"]) == 2
    assert {row["role"] for row in assessment["reviews"]} == set(signatures.ROLES)
    assert len({row["principal_id"] for row in assessment["reviews"]}) == 2
    for row in assessment["reviews"]:
        assert row["status"] == "authenticated"
        assert row["signature_status"] == "valid"
        assert row["blockers"] == []
    assert assessment["accepted_view_eligible"] is False
    assert assessment["eligibility_status"] == "blocked"
    assert all(assessment[flag] is False for flag in signatures.FALSE_AUTHORITY)
    assert all(assessment[flag] is False for flag in review.FALSE_FLAGS)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_combined_graph_cold_read_binds_joint_subject_but_blank_signed_contexts_block(
    tmp_path, family
):
    fixture, alias_fixture = authored_fixtures()
    component = fixture.component(family)
    before = deepcopy(component)
    record = component["record"]
    record_raw = canonical_dag_json_bytes(record)
    original_inputs = alias_fixture.original_bytes(component["case"])
    assert len(original_inputs) == 12
    retained = tmp_path / "twelve-original-inputs"
    retained.mkdir(mode=0o700)
    for name, raw in original_inputs.items():
        path = retained / name
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(raw)
    alias_fixture.assert_candidate_scope(record)

    materialized = fixture.materialize(review, component)
    preparation, subject = materialized["preparation"], materialized["subject"]
    directory = tmp_path / "combined-graph"
    manifest = exchange.write_graph_bundle(record["graph"], directory)
    manifest_raw = (directory / "manifest.json").read_bytes()
    assert manifest_raw == canonical_dag_json_bytes(manifest)
    assert {path.name for path in directory.iterdir()} == exchange.BUNDLE_FILES
    program = """
import sys
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes
loaded = load_graph_bundle(sys.argv[1], expected_manifest_sha256=sys.argv[2])
for suffix in ('corpus_definition_use_review_v2', 'corpus_definition_use_v2',
               'corpus_definition_review_v2', 'scoped_definition_resolution',
               'legal_source_definition_bridge_v2'):
    assert 'ipfs_datasets_py.logic.autoformal.' + suffix not in sys.modules, suffix
for prefix in ('torch', 'transformers', 'tensorflow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
sys.stdout.buffer.write(canonical_dag_json_bytes(loaded))
"""
    root = Path(__file__).resolve().parents[4]
    completed = subprocess.run(
        [sys.executable, "-c", program, str(directory), sha(manifest_raw)],
        cwd=tmp_path,
        env=dict(
            os.environ,
            # Keep the launcher's explicit dependency paths when user-site
            # discovery is disabled, with this source checkout first.
            PYTHONPATH=os.pathsep.join(
                [str(root), *filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep))]
            ),
            PYTHONDONTWRITEBYTECODE="1",
            IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
            IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
        ),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    loaded = json.loads(completed.stdout)
    assert loaded == {"manifest": manifest, "snapshot": record["graph"]}
    graph = loaded["snapshot"]
    assert subject["graph_id"] == graph["record_cid"] == manifest["snapshot_cid"]
    assert subject["graph_sha256"] == sha(canonical_dag_json_bytes(graph))
    assert subject["native_binding"] == preparation
    assert preparation["component_pin"] == component["expected_component_pin"]
    assert preparation["native_ast"] == record["joint_native"]["native_ast"]
    assert subject["ast_sha256"] == sha(
        canonical_dag_json_bytes(record["joint_native"]["native_ast"])
    )
    assert subject["ast_sha256"] != preparation["alias_ast_sha256"]
    assert preparation["contexts"] == record["context_population"]
    assert subject["context_slot_ids"] == record["context_slot_ids"]
    assert len(subject["context_slot_ids"]) == len(set(subject["context_slot_ids"])) == 78
    assert subject["scope_id"] == preparation["scope_binding"]["record_cid"]
    assert preparation["review_contract"]["alias_assumed_not_proved"] is True
    assert preparation["lookup_coverage"] == (
        "representative_first_occurrence_whole_predicate_assumption"
    )
    assert preparation["per_occurrence_lookup_verified"] is False

    nodes = {row["record_cid"]: row for row in graph["nodes"]}
    edges = {row["record_cid"]: row for row in graph["edges"]}
    assert all(
        edge["src_cid"] in nodes and edge["dst_cid"] in nodes
        for edge in edges.values()
    )
    uses = [edge for edge in edges.values() if edge["relation"] == "USES_DEFINITION"]
    assert len(uses) == 1
    for endpoint, role in (("src_cid", "consumer"), ("dst_cid", "donor")):
        original = component["case"][role]["candidate"]
        assert nodes[uses[0][endpoint]]["node_type"] == "definition_assertion"
        assert nodes[uses[0][endpoint]]["content_cid"] == original[
            "definition_record"
        ]["record_cid"]
        assert all(nodes[row["record_cid"]] == row for row in original["graph"]["nodes"])
        assert all(edges[row["record_cid"]] == row for row in original["graph"]["edges"])
    assert set(uses[0]["evidence_cids"]) == {
        record["binding_record"]["record_cid"],
        record["interpretation_record"]["record_cid"],
        component["case"]["lookup_inputs"]["expected_lookup_cid"],
    }
    assert not {"entity", "norm_assertion"} & {
        row["node_type"] for row in nodes.values()
    }
    assert all(manifest[flag] is False for flag in exchange._FLAGS)

    signed = signed_fixture(fixture, materialized)
    signed["evidence"] = {}
    for claim in signed["reviews"]:
        claim["context_closure"] = {
            "status": "declared_complete", "obligations": [], "unresolved": []
        }
    fixture._REVIEW.refresh(signed)
    assessment = fixture.assess(review, signed)
    assert_authenticated_pair(assessment)
    assert assessment["graph_cid"] == subject["graph_id"] == graph["record_cid"]
    assert assessment["joint_ast_sha256"] == subject["ast_sha256"]
    assert assessment["evidence_artifact_sha256s"] == {}
    assert "authenticated_complete_context_declarations_missing" in assessment["blockers"]
    assert "production_trust_registry_unavailable" not in assessment["blockers"]
    assert assessment["review_prerequisites_satisfied_under_selected_trust"] is False
    for row in assessment["reviews"]:
        assert row["signed_context_declaration_complete"] is False
        assert "context_obligation_population_differs" in row["context_blockers"]
    args, kwargs = fixture.assessment_arguments(signed)
    assert review.validate_definition_use_review_assessment_v2(
        assessment, *args, **kwargs
    ) == assessment
    assert canonical_dag_json_bytes(record) == record_raw
    assert component == before
    assert alias_fixture.original_bytes(component["case"]) == original_inputs
    assert {
        str(path.relative_to(retained)): path.read_bytes()
        for path in retained.rglob("*") if path.is_file()
    } == original_inputs
    assert set(loaded) == {"manifest", "snapshot"}


def test_actual_competing_table_blocks_combined_review_and_preserves_original_graphs():
    fixture, alias_fixture = authored_fixtures()
    component = fixture.component()
    before = deepcopy(component)
    record = component["record"]
    original_inputs = alias_fixture.original_bytes(component["case"])
    assert len(original_inputs) == 12
    materialized = fixture.materialize(review, component)
    signed = signed_fixture(fixture, materialized)
    stable = fixture.assess(review, signed)
    assert_authenticated_pair(stable)
    assert stable["review_prerequisites_satisfied_under_selected_trust"] is True
    assert all(row["signed_context_declaration_complete"] for row in stable["reviews"])
    signed_bytes = canonical_dag_json_bytes(signed["reviews"])
    manifest = signed["manifest"]
    current = alias_fixture.observations(manifest)
    assert current["observed_artifact_sha256s"] == signed["observed_artifact_sha256s"]
    assert current["observed_pins"] == signed["observed_pins"]

    # Add a real competing definition to the searched donor table; preserve all
    # original candidate/source bytes and observe the rebuilt partition bytes.
    changed = deepcopy(component["case"])
    changed["lookup_inputs"] = fixture._USE.lookup_inputs(changed, status="ambiguous")
    old_registry = json.loads(component["case"]["lookup_inputs"]["registry_raw"])
    new_registry = json.loads(changed["lookup_inputs"]["registry_raw"])
    old_partitions = {row["partition_id"]: row for row in old_registry["partitions"]}
    new_partitions = {row["partition_id"]: row for row in new_registry["partitions"]}
    assert old_partitions["local"] == new_partitions["local"]
    old_donor, new_donor = old_partitions["donor"], new_partitions["donor"]
    old_definitions = json.loads(old_donor["table_json"])["definitions"]
    new_definitions = json.loads(new_donor["table_json"])["definitions"]
    assert len(old_definitions) == 1 and len(new_definitions) == 2
    assert all(row in new_definitions for row in old_definitions)
    assert old_donor["table_sha256"] == sha(old_donor["table_json"].encode())
    assert new_donor["table_sha256"] == sha(new_donor["table_json"].encode())
    assert old_donor["table_sha256"] != new_donor["table_sha256"]
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
    signed["observed_artifact_sha256s"] = current["observed_artifact_sha256s"]
    signed["observed_pins"] = current["observed_pins"]
    invalidation = dependencies.invalidate_dependencies(manifest, **current)
    assert invalidation["seed_artifact_ids"] == [donor_id]
    assert {row["code"] for row in invalidation["seed_reasons"][donor_id]} == {
        "artifact_changed", "dependency_pin_changed"
    }
    lookup_id = "definition-lookup:" + component["case"]["lookup_inputs"]["expected_lookup_cid"]
    required = {donor_id, lookup_id, record["graph"]["record_cid"]}
    assert required <= set(signed["subject"]["required_dependency_ids"])
    assert required <= set(invalidation["stale_artifact_ids"])
    assert any(
        row["dependent_id"] == record["graph"]["record_cid"]
        for row in invalidation["propagation_witnesses"]
    )
    for role in ("donor", "consumer"):
        assert component["case"][role]["candidate"]["graph"]["record_cid"] in (
            invalidation["reusable_under_declared_dependencies"]
        )
    assert dependencies.validate_invalidation(invalidation, manifest, **current) == invalidation
    blocked = fixture.assess(review, signed)
    assert_authenticated_pair(blocked)
    assert blocked["dependency_invalidation_sha256"] == invalidation["invalidation_sha256"]
    assert "required_dependency_closure_not_current" in blocked["blockers"]
    assert "authenticated_complete_context_declarations_missing" not in blocked["blockers"]
    assert blocked["review_prerequisites_satisfied_under_selected_trust"] is False
    assert canonical_dag_json_bytes(signed["reviews"]) == signed_bytes

    query_raw = component["case"]["lookup_inputs"]["query_raw"]
    fresh = resolver.resolve_definition_lookup(new_registry, query_raw, sha(query_raw))
    assert fresh["status"] == "ambiguous" and fresh["selected_symbol_id"] is None
    assert set(fresh["owner_resolution"]["symbol_ids"]) == {
        component["case"]["request"]["donor_symbol"], "fixture:competing-definition"
    }
    assert fresh == json.loads(changed["lookup_inputs"]["lookup_raw"])
    with pytest.raises(ValueError):
        fixture._USE.prepare(use, changed)
    assert component == before
    assert alias_fixture.original_bytes(component["case"]) == original_inputs
    assert alias_fixture.original_bytes(changed) == original_inputs
    alias_fixture.assert_candidate_scope(record)
