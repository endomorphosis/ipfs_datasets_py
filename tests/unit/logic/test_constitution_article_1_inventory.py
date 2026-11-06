"""Article 1 spans come from the constitution inventory and stay unadmitted."""
from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.autoformal.constitution_inventory import (
    constitution_shard_inventory,
    inventory_article_1,
    inventory_constitution,
)
from ipfs_datasets_py.logic.autoformal.paired_span_census import (
    PairedCensusError,
    article_1_span_inventory,
    project_constitution_inventory,
)


TEXT = """We the People do ordain and establish this Constitution.
Article. I.
Section. 1.
All legislative Powers herein granted shall be vested in a Congress.
Note:
*Superseded by section 3 of the 20th amendment.
Section. 2.
The House of Representatives shall be composed of Members chosen every second Year.
Article. II.
The executive Power shall be vested in a President.
AMENDMENT I
Congress shall make no law abridging the freedom of speech.
"""


def test_article_1_spans_come_from_the_inventory_and_stay_unadmitted() -> None:
    inventory = inventory_constitution(TEXT)
    shard = inventory_article_1(TEXT)
    same = constitution_shard_inventory(inventory, "A1")
    article_ids = [
        span["id"]
        for span in inventory["spans"]
        if span["unit_id"] == "art-1" or str(span["unit_id"]).startswith("art-1.")
    ]
    assert article_ids
    assert [span["id"] for span in shard["spans"]] == article_ids
    assert [span["id"] for span in same["spans"]] == article_ids
    assert shard["source"] == "constitution_inventory"
    assert shard["unit"] == "A1"
    assert shard["roundtrip_ok"] is False
    assert shard["admitted"] is False
    assert shard["formalized"] is False
    assert shard["compiled"] is False
    by_id = {span["id"]: span for span in inventory["spans"]}
    for span in shard["spans"]:
        original = by_id[span["id"]]
        assert span["text"] == original["text"]
        assert span["unit_id"] == original["unit_id"]
        assert span["status"] == original["status"]
        assert span["roundtrip_ok"] is False
        assert span["admitted"] is False
        assert span["formalized"] is False
        assert span["status"] != "roundtrip_ok"
    assert all(not str(span["unit_id"]).startswith("art-2") for span in shard["spans"])
    assert all(not str(span["unit_id"]).startswith("amend-") for span in shard["spans"])
    assert all(span["unit_id"] != "preamble" for span in shard["spans"])
    assert any(str(span["unit_id"]).startswith("note-") for span in inventory["spans"])
    assert all(not str(span["unit_id"]).startswith("note-") for span in shard["spans"])
    projected = project_constitution_inventory(shard)
    census = article_1_span_inventory(TEXT)
    assert projected == census
    assert projected["span_count"] == len(article_ids)
    assert projected["roundtrip_ok"] is False
    assert projected["admitted"] is False
    assert projected["formalized"] is False
    assert projected["enqueued"] is False
    assert [row["source"]["span_id"] for row in projected["spans"]] == article_ids
    for row, span in zip(projected["spans"], shard["spans"], strict=True):
        assert row["source"]["text"] == span["text"]
        assert row["source"]["constitution"] is True
        assert row["unit_id"] == span["unit_id"]
        assert row["compiler"]["roundtrip_ok"] is False
        assert row["roundtrip_ok"] is False
        assert row["admitted"] is False
        assert row["formalized"] is False


def test_article_1_ledger_keeps_inventory_text_and_strips_authority() -> None:
    ledger = {
        "spans": [
            {
                "id": "preamble.span-1",
                "unit_id": "preamble",
                "text": "We the People.",
                "status": "non_operative",
                "reason": "preamble",
            },
            {
                "id": "art-1.sec-1.span-1",
                "unit_id": "art-1.sec-1",
                "text": "All legislative Powers shall be vested in a Congress.",
                "status": "uncompiled",
                "reason": "",
            },
            {
                "id": "art-1.sec-1.span-2",
                "unit_id": "art-1.sec-1",
                "text": "Poison.",
                "status": "roundtrip_ok",
                "reason": "forged",
                "roundtrip_ok": True,
                "admitted": True,
                "formalized": True,
            },
            {
                "id": "art-2.span-1",
                "unit_id": "art-2",
                "text": "The executive Power shall be vested in a President.",
                "status": "uncompiled",
                "reason": "",
            },
            {
                "id": "amend-1.span-1",
                "unit_id": "amend-1",
                "text": "Congress shall make no law abridging the freedom of speech.",
                "status": "uncompiled",
                "reason": "",
            },
        ],
        "edges": [
            {"kind": "repeal", "source": "art-2.span-1", "target": "art-1"},
            {"kind": "citation", "source": "art-1.sec-1.span-1", "target": "elsewhere"},
        ],
    }
    shard = inventory_article_1(ledger)
    assert [span["id"] for span in shard["spans"]] == ["art-1.sec-1.span-1", "art-1.sec-1.span-2"]
    assert shard["spans"][0]["text"] == "All legislative Powers shall be vested in a Congress."
    poisoned = shard["spans"][1]
    assert poisoned["text"] == "Poison."
    assert poisoned["status"] == "compiled"
    assert poisoned["roundtrip_ok"] is False
    assert poisoned["admitted"] is False
    assert poisoned["formalized"] is False
    assert "roundtrip" not in poisoned
    assert shard["edges"] == [{"kind": "citation", "source": "art-1.sec-1.span-1", "target": "elsewhere"}]
    assert ledger["spans"][2]["status"] == "roundtrip_ok"
    assert ledger["spans"][2]["admitted"] is True
    assert ledger["spans"][2]["formalized"] is True
    projected = article_1_span_inventory(ledger)
    assert projected["spans"][1]["compiler"]["status"] == "compiled"
    assert projected["spans"][1]["compiler"]["roundtrip_ok"] is False
    assert all(row["roundtrip_ok"] is False and row["admitted"] is False and row["formalized"] is False for row in projected["spans"])


def test_projector_rejects_authority_that_is_not_from_the_inventory() -> None:
    shard = inventory_article_1(TEXT)
    forged = dict(shard)
    forged["spans"] = [dict(shard["spans"][0]), *shard["spans"][1:]]
    forged["spans"][0]["roundtrip_ok"] = True
    with pytest.raises(PairedCensusError, match="cannot grant authority"):
        project_constitution_inventory(forged)
    forged["spans"][0]["roundtrip_ok"] = False
    forged["spans"][0]["status"] = "roundtrip_ok"
    with pytest.raises(PairedCensusError, match="roundtrip_ok"):
        project_constitution_inventory(forged)
    with pytest.raises(PairedCensusError, match="constitution inventory"):
        project_constitution_inventory({"source": "other", "spans": [], "roundtrip_ok": False, "admitted": False, "formalized": False})
