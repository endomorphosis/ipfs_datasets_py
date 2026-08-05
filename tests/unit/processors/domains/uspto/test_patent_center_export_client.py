"""Unit tests for Patent Center UI export helpers (no live network)."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.auth.patent_center_export_client import (
    PatentCenterExportResult,
    _extract_ifw_docs,
    _safe_name,
)


def test_extract_ifw_docs_from_sdwp_shape() -> None:
    inventory = {
        "errorBag": [],
        "resultBag": [
            {
                "applicationNumberText": "18654466",
                "documentBag": [
                    {
                        "documentIdentifier": "MMK4MMAQX66X223",
                        "documentCode": "EGRANT.NTF",
                        "mimeTypeBag": ["PDF"],
                    },
                    {
                        "documentIdentifier": "abc",
                        "documentCode": "SPEC",
                        "mimeTypeBag": ["PDF", "XML"],
                    },
                ],
            }
        ],
    }
    docs = _extract_ifw_docs(inventory)
    assert len(docs) == 2
    assert docs[0]["documentCode"] == "EGRANT.NTF"


def test_extract_ifw_docs_flat_list() -> None:
    docs = _extract_ifw_docs(
        [{"documentIdentifier": "x", "documentCode": "CLM"}]
    )
    assert len(docs) == 1
    assert docs[0]["documentIdentifier"] == "x"


def test_safe_name_strips_unsafe() -> None:
    assert ".." not in _safe_name("../../etc/passwd")
    assert _safe_name("EGRANT.PDF") == "EGRANT.PDF"


def test_result_to_dict_schema() -> None:
    r = PatentCenterExportResult(
        ok=True,
        application_number="18654466",
        logged_in=True,
        files=["/tmp/a.pdf"],
        ifw_document_count=34,
        odp_downloads=33,
        message="export_complete",
    )
    d = r.to_dict()
    assert d["schema"] == "patlaw-patent-center-ui-export-v1"
    assert d["file_count"] == 1
    assert d["ok"] is True
    assert "generated_at_utc" in d


def test_export_client_module_exports() -> None:
    from ipfs_datasets_py.processors.domains.uspto import auth as auth_pkg

    assert hasattr(auth_pkg, "export_application_via_patent_center")
    assert hasattr(auth_pkg, "PatentCenterExportResult")
