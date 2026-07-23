from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_data import docket_dataset as docket_dataset_module
from ipfs_datasets_py.processors.legal_data import DocketDatasetBuilder


@pytest.fixture(autouse=True)
def _disable_heavy_docket_enrichment(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_DISABLE_EMBEDDINGS_ROUTER", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_DISABLE_DOCKET_FORMAL_LOGIC", "1")


def test_docket_dataset_collects_citation_recovery_candidates():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1004",
            "case_name": "Doe v. Acme",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Motion",
                    "text": "The motion relies on Minn. Stat. § 999.999.",
                }
            ],
        }
    )

    payload = dataset.to_dict()
    linked_authorities = payload["metadata"]["linked_authorities"]

    assert linked_authorities["unmatched_linked_authority_count"] == 1
    assert linked_authorities["citation_recovery_candidate_count"] == 1
    assert payload["documents"][0]["metadata"]["citation_recovery_candidates"][0]["corpus_key"] == "state_laws"

    candidates = docket_dataset_module.collect_docket_dataset_citation_recovery_candidates(dataset)
    assert candidates["source"] == "docket_dataset_citation_recovery_candidates"
    assert candidates["result_count"] == 1
    assert candidates["results"][0]["normalized_citation"] == "Minn. Stat. § 999.999"
    assert "site:.gov" in candidates["results"][0]["recovery_query"]


@pytest.mark.anyio
async def test_docket_dataset_can_run_missing_authority_recovery(monkeypatch):
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1005",
            "case_name": "Doe v. Acme",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Motion",
                    "text": "The motion relies on Minn. Stat. § 999.999.",
                }
            ],
        }
    )

    async def _fake_recover_missing_legal_citation_source(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "normalized_citation": kwargs["normalized_citation"],
            "corpus_key": kwargs["corpus_key"],
            "state_code": kwargs["state_code"],
            "manifest_path": "/tmp/recovery_manifest.json",
        }

    monkeypatch.setattr(
        docket_dataset_module,
        "recover_missing_legal_citation_source",
        _fake_recover_missing_legal_citation_source,
    )

    report = await docket_dataset_module.recover_docket_dataset_missing_authorities(dataset)
    assert report["source"] == "docket_dataset_missing_authority_recovery"
    assert report["candidate_count"] == 1
    assert report["recovery_count"] == 1
    assert report["recoveries"][0]["corpus_key"] == "state_laws"

    method_report = await dataset.recover_missing_authorities()
    assert method_report["recovery_count"] == 1


def test_packaged_docket_collects_citation_recovery_candidates(tmp_path):
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1006",
            "case_name": "Doe v. Acme",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Motion",
                    "text": "The motion relies on Minn. Stat. § 999.999.",
                }
            ],
        }
    )

    package = dataset.write_package(tmp_path / "recovery_bundle", include_car=False)
    report = docket_dataset_module.collect_packaged_docket_citation_recovery_candidates(
        package["manifest_json_path"]
    )

    assert report["source"] == "packaged_docket_citation_recovery_candidates"
    assert report["manifest_path"] == package["manifest_json_path"]
    assert report["result_count"] == 1
    assert report["results"][0]["corpus_key"] == "state_laws"


@pytest.mark.anyio
async def test_packaged_docket_can_run_missing_authority_recovery(monkeypatch, tmp_path):
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1007",
            "case_name": "Doe v. Acme",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Motion",
                    "text": "The motion relies on Minn. Stat. § 999.999.",
                }
            ],
        }
    )
    package = dataset.write_package(tmp_path / "recovery_bundle", include_car=False)

    async def _fake_recover_missing_legal_citation_source(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "normalized_citation": kwargs["normalized_citation"],
            "corpus_key": kwargs["corpus_key"],
            "state_code": kwargs["state_code"],
            "manifest_path": "/tmp/recovery_manifest.json",
        }

    monkeypatch.setattr(
        docket_dataset_module,
        "recover_missing_legal_citation_source",
        _fake_recover_missing_legal_citation_source,
    )

    report = await docket_dataset_module.recover_packaged_docket_missing_authorities(
        package["manifest_json_path"]
    )
    assert report["source"] == "packaged_docket_missing_authority_recovery"
    assert report["manifest_path"] == package["manifest_json_path"]
    assert report["candidate_count"] == 1
    assert report["recovery_count"] == 1


@pytest.mark.anyio
async def test_packaged_docket_can_plan_missing_authority_follow_up(monkeypatch, tmp_path):
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1008",
            "case_name": "Doe v. Acme",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Motion",
                    "text": "The motion relies on Minn. Stat. § 999.999.",
                }
            ],
        }
    )
    package = dataset.write_package(tmp_path / "recovery_bundle", include_car=False)

    async def _fake_recover_missing_legal_citation_source(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "normalized_citation": kwargs["normalized_citation"],
            "corpus_key": kwargs["corpus_key"],
            "hf_dataset_id": "justicedao/ipfs_state_laws",
            "state_code": kwargs["state_code"],
            "search_query": kwargs["citation_text"],
            "candidate_count": 2,
            "archived_count": 1,
            "manifest_path": "/tmp/recovery_manifest.json",
            "manifest_directory": "/tmp/recovery_dir",
            "publish_plan": {
                "repo_id": "justicedao/ipfs_state_laws",
                "path_in_repo": "source_recovery/demo",
                "publish_command": "python scripts/repair/publish_parquet_to_hf.py --local-dir /tmp/recovery_dir",
            },
        }

    monkeypatch.setattr(
        docket_dataset_module,
        "recover_missing_legal_citation_source",
        _fake_recover_missing_legal_citation_source,
    )

    report = await docket_dataset_module.plan_packaged_docket_missing_authority_follow_up(
        package["manifest_json_path"]
    )

    assert report["source"] == "packaged_docket_missing_authority_follow_up_plan"
    assert report["manifest_path"] == package["manifest_json_path"]
    assert report["work_item_count"] == 1
    assert report["work_items"][0]["job_kind"] == "legal_citation_recovery_follow_up"
    assert report["work_items"][0]["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert report["work_items"][0]["target_parquet_path"] == "state_laws_parquet_cid/STATE-MN.parquet"
    assert report["work_items"][0]["promotion_preview"]["promotion_output_dir"].endswith("canonical_promotion")
    assert report["work_items"][0]["promotion_preview"]["promotion_parquet_path"].endswith("promotion_rows.parquet")
    assert report["work_items"][0]["release_plan_preview"]["status"] == "planned"
    assert report["work_items"][0]["release_plan_preview"]["commands"][0]["stage"] == "promote_bundle"
    assert report["work_items"][0]["release_plan_preview"]["commands"][1]["status"] == "ready"
    assert "merge_recovery_manifest_into_canonical_dataset" in report["work_items"][0]["release_plan_preview"]["commands"][1]["command"]
    assert report["work_items"][0]["stages"][1]["status"] == "ready"
    assert report["work_items"][0]["stages"][2]["status"] == "ready"
    assert report["work_items"][0]["stages"][3]["publish_command"].startswith("python scripts/repair/publish_parquet_to_hf.py")


@pytest.mark.anyio
async def test_packaged_docket_can_execute_missing_authority_follow_up(monkeypatch, tmp_path):
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1009",
            "case_name": "Doe v. Acme",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Motion",
                    "text": "The motion relies on Minn. Stat. § 999.999.",
                }
            ],
        }
    )
    package = dataset.write_package(tmp_path / "recovery_bundle", include_car=False)
    recovery_dir = tmp_path / "recovery_dir"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    recovery_manifest = recovery_dir / "recovery_manifest.json"
    recovery_manifest.write_text("{}", encoding="utf-8")
    target_parquet = tmp_path / "state_laws" / "state_laws_parquet_cid" / "STATE-MN.parquet"

    async def _fake_recover_missing_legal_citation_source(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "normalized_citation": kwargs["normalized_citation"],
            "corpus_key": kwargs["corpus_key"],
            "hf_dataset_id": "justicedao/ipfs_state_laws",
            "state_code": kwargs["state_code"],
            "search_query": kwargs["citation_text"],
            "candidate_count": 2,
            "archived_count": 1,
            "manifest_path": str(recovery_manifest),
            "manifest_directory": str(recovery_dir),
            "publish_plan": {
                "repo_id": "justicedao/ipfs_state_laws",
                "path_in_repo": "source_recovery/demo",
                "publish_command": "python scripts/repair/publish_parquet_to_hf.py --local-dir /tmp/recovery_dir",
            },
        }

    captured = {}

    def _fake_promote(manifest_path, *, output_dir=None, write_parquet=True):
        captured["promote_manifest_path"] = manifest_path
        captured["promote_output_dir"] = output_dir
        return {
            "status": "success",
            "promotion_output_dir": str(output_dir or recovery_dir / "canonical_promotion"),
            "rows": [
                {
                    "target_local_parquet_path": str(target_parquet),
                    "target_parquet_path": "state_laws_parquet_cid/STATE-MN.parquet",
                }
            ],
        }

    def _fake_merge(manifest_path, *, output_dir=None, target_local_parquet_path=None, write_promotion_parquet=True):
        captured["merge_manifest_path"] = manifest_path
        captured["merge_output_dir"] = output_dir
        captured["merge_target_local_parquet_path"] = target_local_parquet_path
        return {
            "status": "success",
            "target_local_parquet_path": str(target_local_parquet_path or target_parquet),
            "merged_row_count": 1,
        }

    monkeypatch.setattr(
        docket_dataset_module,
        "recover_missing_legal_citation_source",
        _fake_recover_missing_legal_citation_source,
    )
    monkeypatch.setattr(
        docket_dataset_module,
        "promote_recovery_manifest_to_canonical_bundle",
        _fake_promote,
    )
    monkeypatch.setattr(
        docket_dataset_module,
        "merge_recovery_manifest_into_canonical_dataset",
        _fake_merge,
    )

    report = await docket_dataset_module.execute_packaged_docket_missing_authority_follow_up(
        package["manifest_json_path"]
    )

    assert report["status"] == "success"
    assert report["source"] == "packaged_docket_missing_authority_follow_up_execution"
    assert report["executed_work_item_count"] == 1
    assert report["work_items"][0]["execution"]["status"] == "success"
    assert report["work_items"][0]["execution"]["stages"][0]["status"] == "completed"
    assert report["work_items"][0]["execution"]["stages"][1]["status"] == "completed"
    assert report["work_items"][0]["execution"]["stages"][2]["status"] == "completed"
    assert report["work_items"][0]["execution"]["stages"][3]["status"] == "skipped"
    assert captured["promote_manifest_path"] == str(recovery_manifest)
    assert captured["merge_manifest_path"] == str(recovery_manifest)
