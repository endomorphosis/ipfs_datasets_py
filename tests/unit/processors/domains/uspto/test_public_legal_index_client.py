"""Unit tests for public legal index client (no live Hub required for unit path)."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.domains.uspto.public_legal_index_client import (
    build_revision_retrieval_queries,
    corpus_rows_to_index_documents,
)
from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    TriggerDocument,
    RevisionCase,
)


def test_corpus_rows_to_index_documents() -> None:
    rows = [
        {
            "record_id": "ecfr:37:1.121",
            "title": "Manner of making amendments",
            "text": "§ 1.121 Amendments must include status identifiers.",
            "citation": "37 C.F.R. § 1.121",
            "classification": "public_official",
            "source_cid": "bafytest121",
            "family": "ecfr",
            "section_id": "1.121",
        }
    ]
    docs = corpus_rows_to_index_documents(rows)
    assert len(docs) == 1
    assert docs[0].document_id == "ecfr:37:1.121"
    assert "1.121" in docs[0].combined_text()


def test_build_revision_retrieval_queries() -> None:
    case = RevisionCase(
        revision_id="rev-test",
        application_number="16000001",
        trigger=TriggerDocument(
            document_code="CTNF",
            document_description="Non-Final Rejection",
            kind="office_action_nonfinal",
        ),
        letter_analysis={
            "analysis": {
                "rejections": ["Claims 1-3 rejected under 35 U.S.C. 103"],
                "citations": ["35 U.S.C. § 103"],
            }
        },
    )
    qs = build_revision_retrieval_queries(case)
    assert any("1.121" in q or "1.111" in q for q in qs)
    assert any("103" in q for q in qs)
