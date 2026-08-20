"""Pinned corpus ingest: grouping, rights quarantine, and fail-closed attacks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.corpus import (
    PATENT_SOURCE_GROUP_COUNT,
    CorpusBuildError,
    expand_ids,
    ingest_local_snapshot,
    load_release_inventory,
    materialize_records,
    plan_corpus,
    reject_path_attack,
    seal_corpus,
)
from ipfs_datasets_py.logic.ir_core.source_lineage import CorpusManifest, RightsDisposition


REPO_ROOT = Path(__file__).resolve().parents[5]
INVENTORY_PATH = REPO_ROOT / "data" / "ir_learning" / "source_inventory" / "release_inventory.json"


def _tiny_inventory(*, groups: int = 3) -> dict:
    revision = "845669408081f1334c54519d2bb7df6bf780ccd5"
    return {
        "schema": "IRSourceReleaseInventory@1",
        "policy": {
            "trust_remote_code": False,
            "require_exact_revision": True,
            "require_source_derivative_separation": True,
            "default_training_admission": "deny",
            "unknown_rights_disposition": "quarantine",
            "broken_or_withdrawn_disposition": "reject",
        },
        "repositories": [
            {
                "id": "justicedao/patent-legal-ir-graphrag",
                "revision": revision,
                "disposition": "quarantine",
                "configuration_receipts": {
                    "corpus": {
                        "split": "train",
                        "semantic_role": "source_candidate",
                        "row_count": groups,
                    },
                    "vectors": {
                        "split": "train",
                        "semantic_role": "derivative",
                        "row_count": groups,
                    },
                    "bm25_documents": {
                        "split": "train",
                        "semantic_role": "derivative",
                        "row_count": groups,
                    },
                },
                "configuration_decision": {
                    "rights_disposition": "quarantine",
                    "release_disposition": "quarantine",
                    "training_admission": "deny",
                },
                "rights_receipt": {
                    "card_license": "other",
                    "source_rights_status": "unresolved",
                    "transformation_rights_status": "unresolved",
                    "decision": "quarantine",
                    "scope": "every named configuration",
                },
                "coverage_receipt": {"source_cutoff": {"status": "unknown", "value": None}},
            },
            {
                "id": "justicedao/patent-legal-vectors",
                "revision": "f215a9c115f2af1147b0fcbf2c047ec250cb54d7",
                "disposition": "reject",
                "configuration_receipts": {
                    "vectors": {
                        "split": "train",
                        "semantic_role": "derivative",
                        "row_count": groups,
                    }
                },
                "configuration_decision": {
                    "rights_disposition": "quarantine",
                    "release_disposition": "reject",
                    "training_admission": "deny",
                },
                "rights_receipt": {
                    "card_license": "cc0-1.0",
                    "source_rights_status": "unresolved",
                    "transformation_rights_status": "unresolved",
                    "decision": "quarantine",
                    "scope": "every named configuration",
                },
            },
        ],
        "source_derived_count_table": {
            "inventory_candidate_lineage_groups": [
                {
                    "lineage_group": "justice-dao/patent-legal-source@" + revision,
                    "candidate": (
                        "justicedao/patent-legal-ir-graphrag@" + revision + ":corpus"
                    ),
                    "source_candidate_rows": groups,
                    "training_admitted_rows": 0,
                    "overlapping_source_view": "justicedao/patent-legal-corpus",
                    "derivative_observations": {
                        "graphrag_vectors": groups,
                        "graphrag_bm25_documents": groups,
                        "graphrag_graph_edges": groups * 10,
                    },
                    "rights_disposition": "quarantine",
                }
            ],
            "inventory_candidate_source_rows": {"patent": groups, "total": groups},
            "training_admitted_source_rows": 0,
        },
    }


def test_real_inventory_keeps_2174_patent_groups_and_denies_training() -> None:
    inventory = load_release_inventory(INVENTORY_PATH)
    plan = plan_corpus(inventory)
    source_ids, derived_ids = expand_ids(plan)

    assert plan.patent_group_count == PATENT_SOURCE_GROUP_COUNT
    assert plan.source_group_count == 7173
    assert len(source_ids) == 7173
    assert plan.training_admitted_record_ids() == ()
    assert not set(source_ids) & set(derived_ids)
    assert "vectors" in plan.populations[0].families
    assert "bm25" in plan.populations[0].families
    assert "graph" in plan.populations[0].families
    assert any("patent-legal-corpus" in view for view in plan.populations[0].overlapping_views)


def test_derivatives_and_repeated_states_do_not_inflate_source_groups() -> None:
    plan = plan_corpus(_tiny_inventory(), expected_patent_groups=3)
    _releases, sources, derived, graph = materialize_records(plan)
    assert len(sources) == 3
    assert {item.lineage_group_id for item in sources} == {
        "grp:patent:0000",
        "grp:patent:0001",
        "grp:patent:0002",
    }
    assert {item.derivation_kind for item in derived} == {"bm25", "graph", "vectors"}
    assert len(derived) == 9
    assert plan.rejected_releases == ("justicedao/patent-legal-vectors",)
    assert all(item.rights.disposition is RightsDisposition.QUARANTINED for item in sources)
    assert graph.graph_id == "lin:jdao-pinset-1"


def test_seal_is_deterministic_and_rights_quarantined(tmp_path: Path) -> None:
    inventory = _tiny_inventory()
    first = seal_corpus(inventory, tmp_path / "a", materialize=True, expected_patent_groups=3)
    second = seal_corpus(inventory, tmp_path / "b", materialize=True, expected_patent_groups=3)
    assert first["manifest_cid"] == second["manifest_cid"]
    assert first["lineage_graph_cid"] == second["lineage_graph_cid"]
    assert first["source_count"] == 3
    assert first["derived_count"] == 9
    assert first["training_admitted_rows"] == 0


def test_seal_writes_receipts(tmp_path: Path) -> None:
    root = seal_corpus(_tiny_inventory(), tmp_path, materialize=True, expected_patent_groups=3)
    manifest = CorpusManifest.from_dict(json.loads((tmp_path / "corpus_manifest.json").read_text()))
    rights = json.loads((tmp_path / "rights_manifest.json").read_text())
    quarantine = json.loads((tmp_path / "quarantine_manifest.json").read_text())
    recon = json.loads((tmp_path / "reconciliation_receipt.json").read_text())
    assert manifest.source_count == 3
    assert manifest.record_cid == root["manifest_cid"]
    assert rights["training_admitted_rows"] == 0
    assert rights["admitted_source_record_ids"] == []
    assert quarantine["training_eligible_rows"] == 0
    assert recon["patent_source_groups"] == 3
    assert (tmp_path / "corpus_root.json").is_file()


def test_replay_of_official_inventory_compact_seal(tmp_path: Path) -> None:
    inventory = load_release_inventory(INVENTORY_PATH)
    left = tmp_path / "a"
    right = tmp_path / "b"
    first = seal_corpus(inventory, left, materialize=False)
    second = seal_corpus(inventory, right, materialize=False)
    assert first["manifest_cid"] == second["manifest_cid"]
    assert first["source_count"] == 7173
    assert first["patent_source_groups"] == PATENT_SOURCE_GROUP_COUNT
    assert first["training_admitted_rows"] == 0
    recon = json.loads((left / "reconciliation_receipt.json").read_text())
    assert recon["patent_source_groups"] == 2174
    assert recon["training_admitted_rows"] == 0


def test_remote_code_malformed_and_broken_source_fail_closed() -> None:
    remote = _tiny_inventory()
    remote["policy"]["trust_remote_code"] = True
    with pytest.raises(CorpusBuildError, match="remote code"):
        plan_corpus(remote, expected_patent_groups=3)

    malformed = _tiny_inventory()
    malformed["schema"] = "not-an-inventory"
    with pytest.raises(CorpusBuildError, match="schema"):
        plan_corpus(malformed, expected_patent_groups=3)

    broken = _tiny_inventory()
    broken["repositories"][0]["disposition"] = "reject"
    broken["repositories"][0]["configuration_decision"]["release_disposition"] = "reject"
    with pytest.raises(CorpusBuildError, match="broken release"):
        plan_corpus(broken, expected_patent_groups=3)

    mismatched = _tiny_inventory()
    mismatched["source_derived_count_table"]["inventory_candidate_lineage_groups"][0][
        "source_candidate_rows"
    ] = 4
    with pytest.raises(CorpusBuildError, match="row_count 3 != declared 4"):
        plan_corpus(mismatched, expected_patent_groups=3)

    inflated = _tiny_inventory(groups=4)
    with pytest.raises(CorpusBuildError, match="must remain 3 groups"):
        plan_corpus(inflated, expected_patent_groups=3)


def test_training_admission_and_unknown_role_fail_closed() -> None:
    admitted = _tiny_inventory()
    admitted["source_derived_count_table"]["inventory_candidate_lineage_groups"][0][
        "training_admitted_rows"
    ] = 3
    with pytest.raises(CorpusBuildError, match="cannot enter training"):
        plan_corpus(admitted, expected_patent_groups=3)

    unknown = _tiny_inventory()
    unknown["repositories"][0]["configuration_receipts"]["vectors"]["semantic_role"] = "magic"
    with pytest.raises(CorpusBuildError, match="unknown semantic role"):
        plan_corpus(unknown, expected_patent_groups=3)

    derivative_as_source = _tiny_inventory()
    derivative_as_source["repositories"][0]["configuration_receipts"]["corpus"][
        "semantic_role"
    ] = "derivative"
    with pytest.raises(CorpusBuildError, match="not a source_candidate"):
        plan_corpus(derivative_as_source, expected_patent_groups=3)


def test_path_and_oversized_snapshot_attacks_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(CorpusBuildError, match="unsafe snapshot path"):
        reject_path_attack("../etc/passwd")
    with pytest.raises(CorpusBuildError, match="unsafe snapshot path"):
        reject_path_attack("/etc/passwd")
    with pytest.raises(CorpusBuildError, match="unsafe snapshot path"):
        reject_path_attack("foo\\bar")
    with pytest.raises(CorpusBuildError, match="exceeds max_file_bytes"):
        ingest_local_snapshot(
            destination_root=tmp_path,
            relative_path="ok/doc.json",
            payload=b"too-big",
            max_file_bytes=3,
        )
    receipt = ingest_local_snapshot(
        destination_root=tmp_path,
        relative_path="ok/doc.json",
        payload=b"abc",
        max_file_bytes=8,
    )
    assert receipt["size_bytes"] == 3
    assert (tmp_path / "ok" / "doc.json").read_bytes() == b"abc"
    assert receipt["content_cid"].startswith("b")
