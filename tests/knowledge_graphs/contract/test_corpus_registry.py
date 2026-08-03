"""Contract tests for the KGP-002 graph corpus registry and inventory.

These tests pin the machine-readable registry and the human inventory document
that record producers, consumers, schemas, formats, counts, provenance,
owners, migration risk, and fixture-only nested lift checkouts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "tests" / "fixtures" / "knowledge_graphs" / "corpus_registry.json"
INVENTORY_PATH = REPO_ROOT / "docs" / "architecture" / "knowledge_graphs_inventory.md"

MANDATORY_GRAPH_KINDS = (
    "cvefixes_security_ir_graphrag",
    "skillcenter_ir_graphrag",
    "two11_retrieval_package",
    "two11_browser_graphrag",
    "supervisor_objective_graph",
    "supervisor_ast_index",
    "supervisor_code_evidence_graph",
    "supervisor_conflict_graph",
    "supervisor_semantic_dependency_graph",
)

REQUIRED_CORPUS_FIELDS = (
    "graph_kind",
    "display_name",
    "authoritative_owner",
    "authoritative_repository_ids",
    "producer_paths",
    "consumer_paths",
    "schema",
    "format",
    "counts",
    "provenance",
    "migration_risk",
    "fixture_only_producer",
)

ALLOWED_MIGRATION_RISKS = frozenset({"low", "medium", "high", "critical"})

CANONICAL_BASELINE = "6672d69242731f53b49f4f793ed3023b7ba36a0d"

STALE_DIRTY_NESTED_MARKERS = (
    "fixture-only",
    "fixture_only",
    "stale",
    "dirty",
    "lift_coding/external/ipfs_datasets",
)


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    assert REGISTRY_PATH.is_file(), f"missing corpus registry: {REGISTRY_PATH}"
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def inventory_text() -> str:
    assert INVENTORY_PATH.is_file(), f"missing inventory document: {INVENTORY_PATH}"
    return INVENTORY_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def corpora_by_kind(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    corpora = registry.get("corpora")
    assert isinstance(corpora, list) and corpora, "registry.corpora must be a non-empty list"
    by_kind: dict[str, dict[str, Any]] = {}
    for entry in corpora:
        assert isinstance(entry, dict)
        kind = entry.get("graph_kind")
        assert isinstance(kind, str) and kind, "corpus entry missing graph_kind"
        assert kind not in by_kind, f"duplicate graph_kind: {kind}"
        by_kind[kind] = entry
    return by_kind


def test_registry_schema_and_baseline(registry: dict[str, Any]) -> None:
    assert registry.get("schema") == "ipfs_datasets_py/knowledge-graphs/corpus-registry@1"
    assert registry.get("schema_version") == 1
    assert registry.get("task_id") == "KGP-002"
    assert registry.get("baseline_tree_id") == CANONICAL_BASELINE
    assert isinstance(registry.get("repositories"), list) and registry["repositories"]
    assert isinstance(registry.get("corpora"), list) and registry["corpora"]


def test_mandatory_graph_kinds_listed(registry: dict[str, Any], corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    listed = registry.get("mandatory_graph_kinds")
    assert isinstance(listed, list)
    assert set(listed) == set(MANDATORY_GRAPH_KINDS)
    for kind in MANDATORY_GRAPH_KINDS:
        assert kind in corpora_by_kind, f"mandatory graph kind missing from corpora: {kind}"
        assert corpora_by_kind[kind].get("mandatory") is True


def test_every_corpus_has_required_fields(corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    for kind, entry in corpora_by_kind.items():
        for field in REQUIRED_CORPUS_FIELDS:
            assert field in entry, f"{kind} missing required field {field}"
        assert isinstance(entry["authoritative_owner"], str) and entry["authoritative_owner"].strip()
        assert isinstance(entry["authoritative_repository_ids"], list) and entry["authoritative_repository_ids"]
        assert isinstance(entry["producer_paths"], list) and entry["producer_paths"]
        assert isinstance(entry["consumer_paths"], list) and entry["consumer_paths"]
        assert isinstance(entry["schema"], dict) and entry["schema"]
        assert isinstance(entry["format"], list) and entry["format"]
        assert isinstance(entry["counts"], dict)
        assert isinstance(entry["provenance"], dict)
        risk = entry["migration_risk"]
        assert risk in ALLOWED_MIGRATION_RISKS, f"{kind} has invalid migration_risk {risk!r}"
        assert isinstance(entry["fixture_only_producer"], bool)


def test_repositories_record_commit_and_cleanliness(registry: dict[str, Any]) -> None:
    repos = registry["repositories"]
    by_id = {r["repository_id"]: r for r in repos}
    assert "canonical_ipfs_datasets_py" in by_id
    canonical = by_id["canonical_ipfs_datasets_py"]
    assert canonical["commit"] == CANONICAL_BASELINE
    assert canonical["authoritative"] is True
    assert canonical["fixture_only"] is False

    for repo in repos:
        assert re.fullmatch(r"[0-9a-f]{40}", repo["commit"]), f"bad commit for {repo['repository_id']}"
        assert isinstance(repo["clean"], bool)
        assert isinstance(repo["dirty_entry_count"], int)
        assert repo["dirty_entry_count"] >= 0
        if repo["clean"]:
            assert repo["dirty_entry_count"] == 0
        assert isinstance(repo["fixture_only"], bool)
        assert isinstance(repo["authoritative"], bool)
        if repo["fixture_only"]:
            assert repo["authoritative"] is False


def test_stale_dirty_nested_lift_is_fixture_only(registry: dict[str, Any]) -> None:
    fixture_block = registry.get("fixture_only_nested_lift_checkouts")
    assert isinstance(fixture_block, list) and fixture_block

    paths = {entry["path"] for entry in fixture_block}
    assert any("lift_coding/external/ipfs_datasets" in p for p in paths)
    assert any("hallucinate_app/ipfs_datasets_py" in p for p in paths)

    dirty_stale = [
        entry
        for entry in fixture_block
        if entry.get("classification") == "stale_dirty_nested_lift_checkout"
    ]
    assert dirty_stale, "expected stale_dirty_nested_lift_checkout entries"
    for entry in dirty_stale:
        assert entry["use"] == "fixture_only"
        assert entry["clean"] is False
        assert entry["commit"].startswith("d144be65")

    repos = {r["repository_id"]: r for r in registry["repositories"]}
    for repo_id in (
        "nested_lift_external_datasets",
        "nested_lift_hallucinate_datasets",
        "nested_lift_cve_producer_tree",
    ):
        assert repos[repo_id]["fixture_only"] is True
        assert repos[repo_id]["authoritative"] is False


def test_cvefixes_counts_schema_and_fixture_producer(corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    cve = corpora_by_kind["cvefixes_security_ir_graphrag"]
    assert cve["fixture_only_producer"] is True
    assert cve["counts"]["graph_nodes"] == 85169
    assert cve["counts"]["graph_edges"] == 167364
    assert cve["schema"]["release_schema"] == "cvefixes-huggingface-release/v1"
    assert cve["schema"]["ontology"] == "cvefixes-graphrag-ontology/v1"
    assert cve["migration_risk"] == "high"
    assert any("cvefixes" in p for p in cve["producer_paths"])
    assert any(".cvefixes-build" in r for r in cve["artifact_roots"])


def test_skillcenter_counts_and_canonical_owner(corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    sc = corpora_by_kind["skillcenter_ir_graphrag"]
    assert sc["fixture_only_producer"] is False
    assert "canonical" in sc["authoritative_owner"] or "ipfs_datasets_py" in sc["authoritative_owner"]
    assert sc["counts"]["graph_nodes"] == 434135
    assert sc["counts"]["graph_edges"] == 2560637
    assert sc["schema"]["release_schema"] == "skillcenter-huggingface-release/v3"
    assert sc["schema"]["primary_key"] == "entry_cid"
    assert any("skillcenter_hf_release" in p for p in sc["producer_paths"])


def test_two11_retrieval_and_browser_counts(corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    retrieval = corpora_by_kind["two11_retrieval_package"]
    assert retrieval["counts"]["graph_nodes"] == 48851
    assert retrieval["counts"]["graph_edges"] == 648958
    assert retrieval["counts"]["documents"] == 22638
    assert retrieval["authoritative_owner"] in {"two11_ai", "211-AI", "two11_ai"}
    assert any("build_retrieval_package" in p for p in retrieval["producer_paths"])

    browser = corpora_by_kind["two11_browser_graphrag"]
    assert browser["schema"]["schema_version"] == 1
    assert browser["counts"]["smoke_documents"] == 25
    assert any("browser_graphrag" in p for p in browser["producer_paths"])
    assert browser["migration_risk"] == "low"


def test_supervisor_graph_kinds_and_schemas(corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    objective = corpora_by_kind["supervisor_objective_graph"]
    assert objective["schema"]["graph_schema"] == "ipfs_accelerate_py.agent_supervisor.objective_graph"
    assert objective["counts"]["goal_count"] == 11
    assert objective["counts"]["graph_nodes"] == 11
    assert objective["authoritative_owner"] == "ipfs_accelerate_py"

    ast_index = corpora_by_kind["supervisor_ast_index"]
    assert "analysis-ast-index@1" in ast_index["schema"]["index_schema"]

    code_ev = corpora_by_kind["supervisor_code_evidence_graph"]
    assert "code-evidence-graph@1" in code_ev["schema"]["graph_schema"]

    conflict = corpora_by_kind["supervisor_conflict_graph"]
    assert "conflict_graph@1" in conflict["schema"]["graph_schema"]

    semantic = corpora_by_kind["supervisor_semantic_dependency_graph"]
    assert "semantic-dependency-graph@1" in semantic["schema"]["graph_schema"]

    for kind in (
        "supervisor_objective_graph",
        "supervisor_ast_index",
        "supervisor_code_evidence_graph",
        "supervisor_conflict_graph",
        "supervisor_semantic_dependency_graph",
    ):
        entry = corpora_by_kind[kind]
        assert entry["fixture_only_producer"] is False
        assert entry["migration_risk"] == "low"
        assert any("agent_supervisor" in p for p in entry["producer_paths"])


def test_discovered_non_mandatory_kinds_present(corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    discovered = {
        "platform_graph_engine",
        "sharded_car_v1",
        "website_graphrag",
        "pdf_graphrag_integrator",
        "finance_graphrag",
        "ipld_legacy_knowledge_graph",
        "logic_aware_knowledge_graph",
        "intent_corpus_evidence_graph",
        "ipfs_kit_ipld_knowledge_graph",
    }
    missing = discovered - set(corpora_by_kind)
    assert not missing, f"expected discovered graph kinds missing: {sorted(missing)}"
    assert corpora_by_kind["platform_graph_engine"]["migration_risk"] == "critical"
    assert corpora_by_kind["ipld_legacy_knowledge_graph"]["migration_risk"] == "high"


def test_no_fixture_only_repo_is_sole_authoritative_for_non_fixture_corpus(
    registry: dict[str, Any],
    corpora_by_kind: dict[str, dict[str, Any]],
) -> None:
    fixture_repo_ids = {
        r["repository_id"]
        for r in registry["repositories"]
        if r.get("fixture_only")
    }
    for kind, entry in corpora_by_kind.items():
        if entry.get("fixture_only_producer"):
            continue
        owners = set(entry["authoritative_repository_ids"])
        assert owners - fixture_repo_ids, (
            f"{kind} has only fixture-only authoritative repositories: {owners}"
        )


def test_inventory_document_covers_mandatory_kinds_and_fixture_flag(
    inventory_text: str,
) -> None:
    lowered = inventory_text.lower()
    for kind in MANDATORY_GRAPH_KINDS:
        assert kind in inventory_text, f"inventory missing mandatory kind {kind}"

    assert "fixture-only" in lowered or "fixture_only" in lowered
    assert "stale" in lowered
    assert "dirty" in lowered

    assert "lift_coding/external/ipfs_datasets" in inventory_text
    assert "85169" in inventory_text or "85,169" in inventory_text
    assert "434135" in inventory_text or "434,135" in inventory_text
    assert "48851" in inventory_text or "48,851" in inventory_text
    assert CANONICAL_BASELINE in inventory_text


def test_inventory_and_registry_kind_sets_align(
    registry: dict[str, Any],
    inventory_text: str,
    corpora_by_kind: dict[str, dict[str, Any]],
) -> None:
    for kind in registry["mandatory_graph_kinds"]:
        assert kind in corpora_by_kind
        assert kind in inventory_text
    # Inventory should mention migration risk section and producer summary.
    assert "Migration risk" in inventory_text or "migration risk" in inventory_text.lower()
    assert "Producer" in inventory_text or "producer" in inventory_text.lower()


def test_registry_json_is_canonical_utf8_object() -> None:
    raw = REGISTRY_PATH.read_bytes()
    assert raw, "registry file is empty"
    # Reject UTF-8 BOM and ensure pure JSON object round-trip.
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    assert isinstance(data, dict)
    # Stable re-parse: trailing content not allowed.
    decoder = json.JSONDecoder()
    obj, idx = decoder.raw_decode(raw.decode("utf-8"))
    assert isinstance(obj, dict)
    assert raw.decode("utf-8")[idx:].strip() == ""


def test_cvefixes_not_owned_by_canonical_as_sole_producer(
    corpora_by_kind: dict[str, dict[str, Any]],
) -> None:
    """CVEfixes code is still nested/fixture-only; do not claim canonical sole ownership."""
    cve = corpora_by_kind["cvefixes_security_ir_graphrag"]
    assert cve["fixture_only_producer"] is True
    owner = cve["authoritative_owner"].lower()
    assert "nested" in owner or "lift" in owner or "fixture" in owner or "non-canonical" in owner


def test_sizes_recorded_for_large_corpora(corpora_by_kind: dict[str, dict[str, Any]]) -> None:
    cve = corpora_by_kind["cvefixes_security_ir_graphrag"]
    assert "sizes" in cve and cve["sizes"]
    assert cve["sizes"].get("source_human") == "1.2G" or cve["sizes"].get("source_bytes_approx", 0) > 1_000_000_000

    retrieval = corpora_by_kind["two11_retrieval_package"]
    assert retrieval.get("sizes", {}).get("package_human") == "184M"

    skill = corpora_by_kind["skillcenter_ir_graphrag"]
    assert "schema" in skill and skill["schema"].get("primary_key") == "entry_cid"
