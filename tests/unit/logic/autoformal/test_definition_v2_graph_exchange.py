"""Actual V2 export wiring preserves candidate graphs and separate custody."""

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
from ipfs_datasets_py.logic.autoformal import corpus_graph_exchange as exchange
from ipfs_datasets_py.logic.autoformal.corpus_contracts import (
    CorpusContractError,
    seal_record,
)
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


@lru_cache(maxsize=1)
def authored_fixture():
    """Reuse authored source declarations; actual owners perform every operation."""
    spec = importlib.util.spec_from_file_location(
        "authored_v2_definition_for_graph_exchange",
        Path(__file__).with_name("test_corpus_definition_adapter_v2.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_public_v2_export_cold_readback_preserves_graph_and_separate_companion(
    tmp_path, family
):
    report_raw, inputs = authored_fixture().inputs(family)
    candidate = adapter.adapt_definition_only_bytes_v2(report_raw, **inputs)
    original_candidate, original_inputs = deepcopy(candidate), deepcopy(inputs)
    companion_bytes = {
        "candidate.json": canonical_dag_json_bytes(candidate),
        "report.json": report_raw,
        "request.json": inputs["request_raw"],
        "source.html": inputs["raw_html"],
        "sampling-report.json": canonical_dag_json_bytes(inputs["sampling_report"]),
        "acquisition-descriptor.json": canonical_dag_json_bytes(inputs["descriptor"]),
    }
    companion = tmp_path / "retained-companion"
    companion.mkdir(mode=0o700)
    for name, raw in companion_bytes.items():
        (companion / name).write_bytes(raw)

    directory = tmp_path / "graph"
    manifest = adapter.export_definition_only_candidate_v2(
        candidate, directory, report_raw=report_raw, **inputs
    )
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert {p.name for p in directory.iterdir()} == exchange.BUNDLE_FILES
    for name in (exchange.NODES_FILE, exchange.EDGES_FILE):
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600
        assert (directory / name).read_bytes()[:4] == b"PAR1"
    manifest_raw = (directory / exchange.MANIFEST_FILE).read_bytes()
    assert manifest_raw == canonical_dag_json_bytes(manifest)

    # A fresh process receives only the graph directory and its external pin.
    # It has neither a retained companion argument nor a native owner to replay.
    program = """
import sys
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes
loaded = load_graph_bundle(sys.argv[1], expected_manifest_sha256=sys.argv[2])
for name in ('corpus_definition_adapter_v2', 'legal_source_definition_bridge_v2',
             'legal_source_sampling'):
    assert 'ipfs_datasets_py.logic.autoformal.' + name not in sys.modules, name
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
    assert loaded == {"manifest": manifest, "snapshot": candidate["graph"]}
    graph = loaded["snapshot"]
    nodes = {node["record_cid"]: node for node in graph["nodes"]}
    assert all(
        edge["src_cid"] in nodes and edge["dst_cid"] in nodes
        for edge in graph["edges"]
    )
    defines = [edge for edge in graph["edges"] if edge["relation"] == "DEFINES"]
    assert len(defines) == 1
    assert nodes[defines[0]["src_cid"]]["node_type"] == "definition_assertion"
    assert nodes[defines[0]["dst_cid"]]["node_type"] == "term_sense"
    assert (
        nodes[defines[0]["src_cid"]]["content_cid"]
        == candidate["definition_record"]["record_cid"]
    )
    assert (
        nodes[defines[0]["dst_cid"]]["content_cid"]
        == candidate["term_record"]["record_cid"]
    )
    assert not {"norm_assertion", "entity"} & {
        node["node_type"] for node in nodes.values()
    }
    assert "USES_DEFINITION" not in {edge["relation"] for edge in graph["edges"]}
    assert "norm_record" not in candidate
    assert set(loaded) == {"manifest", "snapshot"}
    assert not {"definition_record", "source_occurrences", "context_declarations"} & set(
        graph
    )
    assert all(
        manifest[flag] is False
        for flag in (
            "admitted",
            "formalized",
            "source_semantics_verified",
            "external_references_verified",
        )
    )

    # Node content CIDs name external payloads; graph readback does not supply
    # the original declaration, complete source or unresolved context bodies.
    assert {
        node["content_cid"] for node in nodes.values()
    } >= {candidate["definition_record"]["record_cid"]}
    assert candidate["source_occurrences"] and candidate["context_declarations"]
    assert all(
        len(context["missing_requirements"]) == 6
        for context in candidate["context_declarations"]
    )
    assert all(candidate[flag] is False for flag in adapter.FALSE_FLAGS)
    assert candidate == original_candidate and inputs == original_inputs
    assert {p.name: p.read_bytes() for p in companion.iterdir()} == companion_bytes


@pytest.mark.parametrize("damage", ["candidate_context", "report_ast"])
def test_public_v2_export_refuses_resealed_mutants_before_graph_writer(
    tmp_path, monkeypatch, damage
):
    fixture = authored_fixture()
    report_raw, inputs = fixture.inputs()
    candidate = adapter.adapt_definition_only_bytes_v2(report_raw, **inputs)
    if damage == "candidate_context":
        candidate["context_declarations"] = candidate["context_declarations"][:-1]
        candidate = seal_record(
            {
                key: value
                for key, value in candidate.items()
                if key not in {"record_cid", "cid_scope"}
            }
        )
    else:
        report = json.loads(report_raw)
        report["native_ast"]["formula"]["operator"]["value"] = "→"
        report["report_sha256"] = fixture.compiler.digest(
            {key: value for key, value in report.items() if key != "report_sha256"}
        )
        report_raw = fixture.wire(report)
        inputs = inputs | {"expected_report_sha256": sha(report_raw)}

    def forbidden_writer(*_args, **_kwargs):
        pytest.fail("unvalidated V2 candidate reached graph export")

    monkeypatch.setattr(exchange, "write_graph_bundle", forbidden_writer)
    directory = tmp_path / "refused-graph"
    with pytest.raises(CorpusContractError):
        adapter.export_definition_only_candidate_v2(
            candidate, directory, report_raw=report_raw, **inputs
        )
    assert not directory.exists()
    assert list(tmp_path.iterdir()) == []
