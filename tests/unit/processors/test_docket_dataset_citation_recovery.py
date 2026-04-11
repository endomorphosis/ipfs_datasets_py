from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_data import docket_dataset as docket_dataset_module
from ipfs_datasets_py.processors.legal_data import DocketDatasetBuilder


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
