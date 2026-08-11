"""Integration tests: full-authority public legal knowledge graph (PATLAW-190).

Acceptance:

* Graph document nodes cover every corpus document
* Orphan checks pass (fail-closed)
* Bulk nodes/edges payloads stage for Hub packaging
* Authority span/receipt gates pass
* Content-address stability for the same full-authority recipe
* Private / mixed / incomplete inputs fail closed
* Offline full-authority fixtures (PATLAW-186/187/181/183/185) suffice for CI
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.cfr_title37_full_contracts import (
    title37_section_count,
)
from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (
    REQUIRED_CHAPTER_IDS,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (
    PrivateOrMixedInputError,
    UnreviewedRightsError,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_graph_builder import (
    EDGES_FILENAME,
    GRAPH_ROOT_FILENAME,
    GRAPH_SCHEMA_VERSION,
    JSONLD_FILENAME,
    NODES_FILENAME,
    RECEIPT_FILENAME,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
    BuildMode,
    OrphanEdgeError,
    PrivateGraphInputError,
    builds_are_byte_identical,
    load_snapshot,
    verify_authority_edges_cite_spans,
    verify_no_orphan_edges,
)
from ipfs_datasets_py.processors.domains.patent.uspto_guidance_pdf_contracts import (
    REQUIRED_DOCUMENT_IDS,
    REQUIRED_GUIDANCE_DOCUMENTS,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
GRAPH_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_public_legal_knowledge_graph.py"
)
MATERIALIZE_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "materialize_public_legal_corpus.py"
)
RECIPE_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "build_public_legal_production_recipe.py"
)


def _load_module(path: Path, module_name: str):
    assert path.is_file(), f"missing script at {path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass / imports can resolve cls.__module__.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def graph_mod():
    return _load_module(GRAPH_SCRIPT, "build_public_legal_knowledge_graph_patlaw190")


@pytest.fixture(scope="module")
def full_recipe(graph_mod):
    return graph_mod.load_full_authority_recipe(assert_complete=True)


@pytest.fixture(scope="module")
def baseline(graph_mod, full_recipe):
    result, receipt = graph_mod.build_full_authority_knowledge_graph(
        full_recipe,
        require_full_authority=True,
    )
    return result, receipt


# ---------------------------------------------------------------------------
# Declared outputs / pins
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert GRAPH_SCRIPT.is_file()
    assert MATERIALIZE_SCRIPT.is_file()
    assert RECIPE_SCRIPT.is_file()


def test_module_pins(graph_mod) -> None:
    assert graph_mod.FULL_AUTHORITY_TASK_ID == "PATLAW-190"
    assert graph_mod.FULL_AUTHORITY_GOAL_ID == "PATLAW-G218"
    assert graph_mod.FULL_AUTHORITY_RECIPE_ID == (
        "patlaw-full-authority-public-legal-corpus"
    )
    assert tuple(graph_mod.FULL_AUTHORITY_FAMILIES) == ("cfr", "mpep", "guidance")
    assert graph_mod.SCHEMA_VERSION == SCHEMA_VERSION
    assert graph_mod.GRAPH_SCHEMA_VERSION == GRAPH_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Document node coverage (primary acceptance)
# ---------------------------------------------------------------------------


def test_document_nodes_cover_corpus_documents(baseline, full_recipe) -> None:
    result, receipt = baseline
    corpus_ids = {d["record_id"] for d in full_recipe["documents"]}
    node_ids = graph_mod_document_ids(result)

    assert node_ids == corpus_ids
    assert len(node_ids) == full_recipe["counts"]["documents"]
    assert result.snapshot.counts.documents == len(corpus_ids)
    assert result.snapshot.counts.by_node_kind["document"] == len(corpus_ids)
    assert receipt["ok"] is True
    assert receipt["document_coverage"] == "pass"
    assert receipt["document_count"] == len(corpus_ids)
    assert receipt["full_authority"]["coverage"]["ok"] is True


def graph_mod_document_ids(result) -> set[str]:
    out: set[str] = set()
    for node in result.nodes:
        if node.kind != "document":
            continue
        rid = node.document_id or str((node.properties or {}).get("record_id") or "")
        if rid:
            out.add(rid)
    return out


def test_assert_document_nodes_cover_corpus_helper(graph_mod, baseline, full_recipe):
    result, _ = baseline
    # Reconstruct materialization-like document list from the recipe for the helper.
    coverage = graph_mod.assert_document_nodes_cover_corpus(
        result, full_recipe["documents"]
    )
    assert coverage["ok"] is True
    assert coverage["coverage"] == "pass"
    assert coverage["corpus_documents"] == full_recipe["counts"]["documents"]


def test_coverage_fails_when_document_node_removed(graph_mod, baseline, full_recipe):
    result, _ = baseline
    remaining = [n for n in result.nodes if n.kind != "document"] + [
        n for n in result.nodes if n.kind == "document"
    ][1:]
    # Build a shallow stand-in with reduced nodes for the coverage gate.
    class _Stub:
        def __init__(self, nodes, snapshot):
            self.nodes = nodes
            self.snapshot = snapshot

    # Mutate a copy of counts via a lightweight proxy snapshot.
    class _Snap:
        def __init__(self, counts):
            self.counts = counts

    class _Counts:
        def __init__(self, documents, by_node_kind):
            self.documents = documents
            self.by_node_kind = by_node_kind

    stub = _Stub(
        remaining,
        _Snap(
            _Counts(
                documents=result.snapshot.counts.documents,
                by_node_kind=dict(result.snapshot.counts.by_node_kind),
            )
        ),
    )
    with pytest.raises(graph_mod.DocumentNodeCoverageError) as excinfo:
        graph_mod.assert_document_nodes_cover_corpus(stub, full_recipe["documents"])
    assert excinfo.value.code == "document_node_coverage_error"


# ---------------------------------------------------------------------------
# Orphan + authority gates
# ---------------------------------------------------------------------------


def test_orphan_checks_pass(baseline) -> None:
    result, receipt = baseline
    verify_no_orphan_edges(result.nodes, result.edges)
    node_ids = {n.node_id for n in result.nodes}
    for edge in result.edges:
        assert edge.subject_id in node_ids
        assert edge.object_id in node_ids
    assert result.snapshot.orphan_check == "pass"
    assert receipt["orphan_check"] == "pass"
    assert receipt["full_authority"]["orphan_check"] == "pass"


def test_authority_span_checks_pass(baseline) -> None:
    result, receipt = baseline
    verify_authority_edges_cite_spans(result.edges)
    assert result.snapshot.authority_span_check == "pass"
    assert receipt["authority_span_check"] == "pass"
    assert result.snapshot.counts.authority_edges >= 1


def test_orphan_detection_fails_closed(baseline) -> None:
    result, _ = baseline
    nodes = list(result.nodes)
    if len(nodes) < 2:
        pytest.skip("need multiple nodes")
    victim = nodes[0]
    remaining = [n for n in nodes if n.node_id != victim.node_id]
    dangling = [
        e
        for e in result.edges
        if e.subject_id == victim.node_id or e.object_id == victim.node_id
    ]
    if not dangling:
        pytest.skip("selected node has no edges")
    with pytest.raises(OrphanEdgeError):
        verify_no_orphan_edges(remaining, result.edges)


# ---------------------------------------------------------------------------
# Full-authority family / inventory shape
# ---------------------------------------------------------------------------


def test_full_authority_families_and_inventory(baseline, full_recipe) -> None:
    result, receipt = baseline
    by_family = dict(result.snapshot.counts.by_family)
    recipe_by_family = full_recipe["counts"]["by_family"]

    for family in ("cfr", "mpep", "guidance"):
        assert by_family.get(family, 0) >= 1
        assert by_family[family] == recipe_by_family[family]

    assert by_family["mpep"] >= len(REQUIRED_CHAPTER_IDS)
    assert by_family["guidance"] >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    assert sum(by_family.values()) == result.snapshot.counts.documents

    fa = full_recipe["counts"]["full_authority"]
    assert fa["cfr_inventory_total"] == title37_section_count()
    assert fa["cfr_inventory_total"] >= 1000
    assert fa["cfr_documents"] == by_family["cfr"]
    assert fa["mpep_documents"] == by_family["mpep"]
    assert fa["guidance_documents"] == by_family["guidance"]
    assert fa["mpep_section_level"] >= len(REQUIRED_CHAPTER_IDS)
    assert fa["guidance_pdfs"] >= len(REQUIRED_GUIDANCE_DOCUMENTS)

    inv = receipt["full_authority"]["full_authority_inventory"]
    assert inv["cfr_inventory_total"] == title37_section_count()


def test_document_shapes_are_full_authority_not_substitutes(baseline) -> None:
    result, _ = baseline
    for node in result.nodes:
        if node.kind != "document":
            continue
        rid = node.document_id or ""
        family = str((node.properties or {}).get("family") or "")
        if family == "cfr":
            assert rid.startswith("cfr:37:")
            assert not rid.startswith("ecfr:")
        if family == "mpep":
            assert rid.startswith("mpep:section:")
            assert not rid.startswith("mpep:chapter:")
        if family == "guidance":
            assert rid.startswith("guidance:pdf:")


def test_guidance_catalog_present(baseline) -> None:
    result, _ = baseline
    g_ids = {
        n.document_id
        for n in result.nodes
        if n.kind == "document"
        and str((n.properties or {}).get("family") or "") == "guidance"
    }
    assert len(g_ids) >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    # record_id embeds document_id after guidance:pdf:
    suffixes = {rid.split("guidance:pdf:", 1)[-1].split(":")[0] for rid in g_ids}
    assert set(REQUIRED_DOCUMENT_IDS).issubset(suffixes) or len(g_ids) >= len(
        REQUIRED_DOCUMENT_IDS
    )


# ---------------------------------------------------------------------------
# Determinism / corpus pin binding
# ---------------------------------------------------------------------------


def test_repeat_builds_are_content_address_stable(graph_mod, full_recipe, baseline):
    first, _ = baseline
    second, receipt2 = graph_mod.build_full_authority_knowledge_graph(
        copy.deepcopy(full_recipe),
        require_full_authority=True,
    )
    third, _ = graph_mod.build_full_authority_knowledge_graph(
        full_recipe,
        require_full_authority=True,
    )

    assert first.graph_root_cid == second.graph_root_cid == third.graph_root_cid
    assert (
        first.graph_digest_sha256
        == second.graph_digest_sha256
        == third.graph_digest_sha256
    )
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert builds_are_byte_identical(first, third)
    assert receipt2["ok"] is True
    assert receipt2["stable"] is True


def test_graph_binds_materialization_corpus_pin(graph_mod, full_recipe, baseline):
    result, receipt = baseline
    materialization, _, inventory = graph_mod.materialize_full_authority_for_graph(
        full_recipe, require_full_authority=True
    )
    assert result.corpus_root_cid == materialization.corpus_root_cid
    assert result.snapshot.corpus_digest_sha256 == materialization.corpus_digest_sha256
    assert receipt["corpus_root_cid"] == materialization.corpus_root_cid
    assert inventory["ok"] is True
    assert inventory["document_count"] == result.snapshot.counts.documents


def test_changed_source_text_changes_graph_cid(graph_mod, full_recipe, baseline):
    first, _ = baseline
    altered = copy.deepcopy(full_recipe)
    altered["documents"][0]["text"] = (
        altered["documents"][0]["text"] + " [amended full-authority graph body]"
    )
    import hashlib

    altered["documents"][0]["source_lineage"]["source_sha256"] = hashlib.sha256(
        altered["documents"][0]["text"].encode("utf-8")
    ).hexdigest()

    second, receipt = graph_mod.build_full_authority_knowledge_graph(
        altered, require_full_authority=True
    )
    assert second.graph_root_cid != first.graph_root_cid
    assert second.graph_digest_sha256 != first.graph_digest_sha256
    assert second.corpus_root_cid != first.corpus_root_cid
    assert receipt["ok"] is True


def test_document_order_does_not_affect_graph_cid(graph_mod, full_recipe, baseline):
    first, _ = baseline
    shuffled = copy.deepcopy(full_recipe)
    shuffled["documents"] = list(reversed(shuffled["documents"]))
    by_family: dict[str, int] = {}
    for d in shuffled["documents"]:
        fam = d["family"]
        by_family[fam] = by_family.get(fam, 0) + 1
    shuffled["counts"]["by_family"] = dict(sorted(by_family.items()))

    second, _ = graph_mod.build_full_authority_knowledge_graph(
        shuffled, require_full_authority=True
    )
    assert second.graph_root_cid == first.graph_root_cid
    assert [n.node_id for n in second.nodes] == sorted(n.node_id for n in second.nodes)
    assert [e.edge_id for e in second.edges] == sorted(e.edge_id for e in second.edges)


# ---------------------------------------------------------------------------
# Identifier sanitization (guidance section_id '@')
# ---------------------------------------------------------------------------


def test_sanitize_graph_id_token_strips_at(graph_mod) -> None:
    assert (
        graph_mod.sanitize_graph_id_token("enablement-2024@2024-01-10")
        == "enablement-2024-2024-01-10"
    )
    assert graph_mod.sanitize_graph_id_token("already-safe:1.56") == "already-safe:1.56"


def test_graph_safe_documents_preserve_document_cids(graph_mod, full_recipe) -> None:
    materialization, _, _ = graph_mod.materialize_full_authority_for_graph(
        full_recipe, require_full_authority=True
    )
    safe = graph_mod.graph_safe_documents(materialization.documents)
    assert len(safe) == len(materialization.documents)
    for original, projected in zip(materialization.documents, safe):
        assert projected.record_id == original.record_id
        assert projected.document_cid == original.document_cid
        assert projected.document_sha256 == original.document_sha256
        assert projected.source_cid == original.source_cid
        if original.section_id and "@" in original.section_id:
            assert "@" not in (projected.section_id or "")
            assert projected.section_id != original.section_id


# ---------------------------------------------------------------------------
# Private / incomplete fail closed
# ---------------------------------------------------------------------------


def test_private_classification_fails_closed(graph_mod, full_recipe) -> None:
    private = copy.deepcopy(full_recipe)
    private["documents"][0]["classification"] = "confidential_application"
    with pytest.raises((PrivateOrMixedInputError, PrivateGraphInputError)):
        graph_mod.build_full_authority_knowledge_graph(
            private, require_full_authority=True
        )


def test_unreviewed_rights_fail_closed(graph_mod, full_recipe) -> None:
    unreviewed = copy.deepcopy(full_recipe)
    unreviewed["documents"][0]["rights_review"] = {
        "license_expression": "public-domain-US-government",
        "notes": "",
        "redistribution_allowed": False,
        "review_status": "unreviewed",
        "reviewed_at": "",
        "reviewed_by": "",
    }
    with pytest.raises(UnreviewedRightsError):
        graph_mod.build_full_authority_knowledge_graph(
            unreviewed, require_full_authority=True
        )


def test_incomplete_full_authority_recipe_fails(graph_mod, full_recipe) -> None:
    broken = copy.deepcopy(full_recipe)
    broken["documents"] = [
        d for d in broken["documents"] if d["family"] != "guidance"
    ]
    broken["counts"]["by_family"] = {
        k: v for k, v in broken["counts"]["by_family"].items() if k != "guidance"
    }
    broken["counts"]["documents"] = len(broken["documents"])
    broken["counts"]["full_authority"]["guidance_pdfs"] = 0
    broken["counts"]["full_authority"]["guidance_documents"] = 0
    broken["full_authority"]["sources"]["uspto_guidance_pdfs"][
        "documents_present"
    ] = 0
    with pytest.raises(Exception) as excinfo:
        graph_mod.build_full_authority_knowledge_graph(
            broken, require_full_authority=True
        )
    msg = str(excinfo.value).lower()
    assert (
        "full" in msg
        or "guidance" in msg
        or "authority" in msg
        or "incomplete" in msg
        or "mismatch" in msg
    )


# ---------------------------------------------------------------------------
# Staging bulk nodes/edges payloads
# ---------------------------------------------------------------------------


def test_dry_run_and_stage_share_graph_cid(
    graph_mod, full_recipe, baseline, tmp_path: Path
) -> None:
    first, _ = baseline
    staged, receipt = graph_mod.build_full_authority_knowledge_graph(
        full_recipe,
        stage=True,
        output_dir=tmp_path / "fa-graph",
        require_full_authority=True,
    )
    assert staged.mode is BuildMode.STAGE
    assert staged.graph_root_cid == first.graph_root_cid
    assert staged.graph_digest_sha256 == first.graph_digest_sha256
    assert staged.corpus_root_cid == first.corpus_root_cid
    assert receipt["ok"] is True
    assert receipt["full_authority"]["staged"] is True

    out = tmp_path / "fa-graph"
    assert (out / NODES_FILENAME).is_file()
    assert (out / EDGES_FILENAME).is_file()
    assert (out / JSONLD_FILENAME).is_file()
    assert (out / SNAPSHOT_FILENAME).is_file()
    assert (out / RECEIPT_FILENAME).is_file()
    assert (out / GRAPH_ROOT_FILENAME).is_file()

    loaded = load_snapshot(out / SNAPSHOT_FILENAME)
    assert loaded.graph_root_cid == first.graph_root_cid
    assert loaded.orphan_check == "pass"
    assert loaded.authority_span_check == "pass"
    assert loaded.counts.documents == first.snapshot.counts.documents

    node_lines = [
        line
        for line in (out / NODES_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    edge_lines = [
        line
        for line in (out / EDGES_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(node_lines) == len(first.nodes)
    assert len(edge_lines) == len(first.edges)
    assert len(node_lines) >= first.snapshot.counts.documents

    # Bulk payloads are valid JSONL rows with join fields.
    sample_node = json.loads(node_lines[0])
    assert sample_node.get("node_id") or sample_node.get("kind")
    sample_edge = json.loads(edge_lines[0])
    assert sample_edge.get("edge_id") or sample_edge.get("subject_id")

    jsonld = json.loads((out / JSONLD_FILENAME).read_text(encoding="utf-8"))
    assert jsonld["graph_root_cid"] == first.graph_root_cid
    assert jsonld["corpus_root_cid"] == first.corpus_root_cid
    assert "@graph" in jsonld
    assert len(jsonld["@graph"]) == len(first.nodes) + len(first.edges)

    graph_root = json.loads((out / GRAPH_ROOT_FILENAME).read_text(encoding="utf-8"))
    assert graph_root["graph_root_cid"] == first.graph_root_cid


def test_stage_rejects_missing_output_dir(graph_mod, full_recipe) -> None:
    with pytest.raises(Exception) as exc_info:
        graph_mod.build_full_authority_knowledge_graph(
            full_recipe,
            stage=True,
            output_dir=None,
            require_full_authority=True,
        )
    assert "output_dir" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_full_authority_dry_run(graph_mod) -> None:
    rc = graph_mod.main(["--full-authority", "--no-print-summary"])
    assert rc == 0


def test_cli_full_authority_stage_and_write_recipe(graph_mod, tmp_path: Path) -> None:
    recipe_path = tmp_path / "fa_recipe.json"
    rc = graph_mod.main(
        [
            "--full-authority",
            "--write-full-authority-recipe",
            str(recipe_path),
        ]
    )
    assert rc == 0
    assert recipe_path.is_file()
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert payload["full_authority"]["complete"] is True
    assert payload["recipe_id"] == "patlaw-full-authority-public-legal-corpus"

    out = tmp_path / "staged-graph"
    rc = graph_mod.main(
        [
            "--recipe",
            str(recipe_path),
            "--require-full-authority",
            "--stage",
            "--output-dir",
            str(out),
            "--no-print-summary",
        ]
    )
    assert rc == 0
    assert (out / NODES_FILENAME).is_file()
    assert (out / EDGES_FILENAME).is_file()
    assert (out / SNAPSHOT_FILENAME).is_file()

    loaded = load_snapshot(out / SNAPSHOT_FILENAME)
    assert loaded.orphan_check == "pass"
    assert loaded.counts.documents == payload["counts"]["documents"]
    assert loaded.counts.by_node_kind["document"] == payload["counts"]["documents"]


def test_cli_coverage_receipt(graph_mod, capsys) -> None:
    rc = graph_mod.main(
        [
            "--full-authority",
            "--print-coverage-receipt",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["ok"] is True
    assert payload["task_id"] == "PATLAW-190"
    assert payload["document_coverage"] == "pass"
    assert payload["orphan_check"] == "pass"
