"""Joined V2 graph/review custody cannot promote signed blank context claims."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


@lru_cache(maxsize=1)
def authored_fixture():
    """Reuse authored declarations and real fixture keys, never actual reviewers."""
    spec = importlib.util.spec_from_file_location(
        "authored_v2_review_for_joined_graph_exchange",
        Path(__file__).with_name("test_corpus_definition_review_v2.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_exported_v2_graph_subject_rejects_two_valid_signed_blank_context_claims(
    tmp_path, family
):
    fixture = authored_fixture()
    case = fixture.candidate(family)
    candidate = case["record"]
    original_inputs = dict(case["inputs"])
    original_candidate_raw = canonical_dag_json_bytes(candidate)
    assert len(original_inputs) == 6
    assert original_candidate_raw == original_inputs["candidate_raw"]
    retained = tmp_path / "six-original-inputs"
    retained.mkdir(mode=0o700)
    for name, raw in original_inputs.items():
        (retained / (name + ".bin")).write_bytes(raw)

    graph_directory = tmp_path / "graph"
    manifest = adapter.export_definition_only_candidate_v2(
        candidate,
        graph_directory,
        report_raw=original_inputs["report_raw"],
        **case["replay"],
    )
    manifest_raw = (graph_directory / "manifest.json").read_bytes()
    assert manifest_raw == canonical_dag_json_bytes(manifest)
    program = """
import sys
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes
loaded = load_graph_bundle(sys.argv[1], expected_manifest_sha256=sys.argv[2])
for suffix in ('corpus_definition_review_v2', 'corpus_definition_adapter_v2',
               'legal_statutory_context_v2', 'legal_source_definition_bridge_v2'):
    assert 'ipfs_datasets_py.logic.autoformal.' + suffix not in sys.modules, suffix
for prefix in ('torch', 'transformers', 'tensorflow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
sys.stdout.buffer.write(canonical_dag_json_bytes(loaded))
"""
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-c", program, str(graph_directory), sha(manifest_raw)],
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
    assert loaded == {"manifest": manifest, "snapshot": candidate["graph"]}
    graph = loaded["snapshot"]
    nodes = {node["record_cid"]: node for node in graph["nodes"]}
    assert all(
        edge["src_cid"] in nodes and edge["dst_cid"] in nodes
        for edge in graph["edges"]
    )
    defines = [edge for edge in graph["edges"] if edge["relation"] == "DEFINES"]
    assert len(defines) == 1
    assert nodes[defines[0]["src_cid"]]["content_cid"] == candidate[
        "definition_record"
    ]["record_cid"]
    assert nodes[defines[0]["dst_cid"]]["content_cid"] == candidate["term_record"][
        "record_cid"
    ]
    assert "USES_DEFINITION" not in {edge["relation"] for edge in graph["edges"]}
    assert not {"entity", "norm_assertion"} & {
        node["node_type"] for node in graph["nodes"]
    }

    materialized = fixture.materialize(review, case)
    subject = materialized["subject"]
    assert subject["graph_id"] == graph["record_cid"] == manifest["snapshot_cid"]
    assert subject["graph_sha256"] == sha(canonical_dag_json_bytes(graph))
    assert subject["native_binding"]["candidate_pin"]["candidate_cid"] == candidate[
        "record_cid"
    ]
    assert subject["native_binding"]["native_ast"] == candidate["ast_record"][
        "native_ast"
    ]
    packets = materialized["arguments"]["context_inputs"]
    assert [row["source_occurrence_cid"] for row in packets] == [
        row["record_cid"] for row in candidate["source_occurrences"]
    ]
    open_slots = [
        slot
        for row in packets
        for slot in json.loads(row["packet_raw"])["dependency_slots"]
    ]
    assert len(packets) == 7 and len(open_slots) == 42
    assert subject["context_slot_ids"] == [slot["slot_id"] for slot in open_slots]
    assert all(slot["open"] and slot["attachments"] == [] for slot in open_slots)
    assert all(
        materialized["preparation"][flag] is False for flag in review.FALSE_FLAGS
    )

    # These two generated keys use an authored external-policy wire shape.
    # Authentication must succeed while the empty context declarations block.
    signed = fixture.signed.__wrapped__(review, materialized)
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    signed["evidence"] = {}
    for claim in signed["reviews"]:
        claim["context_closure"] = {
            "status": "declared_complete",
            "obligations": [],
            "unresolved": [],
        }
    fixture.refresh(signed)
    assessment = fixture.assess(review, signed)
    assert assessment["evidence_assessment_status"] == "authenticated"
    assert assessment["authenticated_evidence_count"] == 2
    assert len(assessment["reviews"]) == 2
    assert {row["role"] for row in assessment["reviews"]} == set(signatures.ROLES)
    assert len({row["principal_id"] for row in assessment["reviews"]}) == 2
    for row in assessment["reviews"]:
        assert row["status"] == "authenticated" and row["signature_status"] == "valid"
        assert row["blockers"] == []
        assert row["signed_context_declaration_complete"] is False
        assert "context_obligation_population_differs" in row["context_blockers"]
    assert "authenticated_complete_context_declarations_missing" in assessment[
        "blockers"
    ]
    assert "production_trust_registry_unavailable" not in assessment["blockers"]
    assert assessment["review_prerequisites_satisfied_under_selected_trust"] is False
    assert assessment["accepted_view_eligible"] is False
    assert assessment["eligibility_status"] == "blocked"
    assert assessment["evidence_artifact_sha256s"] == {}
    assert all(assessment[flag] is False for flag in signatures.FALSE_AUTHORITY)
    assert all(assessment[flag] is False for flag in review.FALSE_FLAGS)
    args, kwargs = fixture.assessment_arguments(signed)
    assert (
        review.validate_definition_review_assessment_v2(assessment, *args, **kwargs)
        == assessment
    )
    assert canonical_dag_json_bytes(candidate) == original_candidate_raw
    assert case["inputs"] == original_inputs
    assert {path.name: path.read_bytes() for path in retained.iterdir()} == {
        name + ".bin": raw for name, raw in original_inputs.items()
    }
