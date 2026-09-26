"""Constitution span inventory. No compiler and no model."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _inventory():
    path = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "logic" / "autoformal" / "constitution_inventory.py"
    spec = importlib.util.spec_from_file_location("constitution_inventory_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TEXT = """We the People do ordain and establish this Constitution.
Article. I.
Section. 1.
All legislative Powers herein granted shall be vested in a Congress.
AMENDMENT XVIII
No intoxicating liquor shall be sold.
AMENDMENT XXI
Section 1.
The eighteenth article of amendment to the Constitution of the United States is hereby repealed.
Attest William Jackson Secretary
done in Convention by the Unanimous Consent of the States present.
"""


def test_census_names_a_gap_and_does_not_call_a_round_trip_success() -> None:
    module = _inventory()
    ledger = {
        "compiled": False,
        "spans": [
            {"id": "preamble.span-1", "status": "non_operative", "text": "We the People", "reason": "preamble"},
            {"id": "art-1.sec-1.span-1", "status": "uncompiled", "text": "All legislative Powers shall be vested in a Congress.", "reason": ""},
            {"id": "amend-18.span-1", "status": "inactive", "text": "No intoxicating liquor shall be sold.", "reason": "repealed"},
        ],
        "edges": [],
    }

    def compile_one(text: str) -> dict[str, str]:
        if "Congress" in text:
            return {"compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": ""}
        raise AssertionError(text)

    report = module.census_ledger(ledger, compile_one)
    assert report["stopped"] is False
    statuses = {span["id"]: span["status"] for span in report["ledger"]["spans"]}
    assert statuses["preamble.span-1"] == "non_operative"
    assert statuses["amend-18.span-1"] == "inactive"
    assert statuses["art-1.sec-1.span-1"] == "gap"
    assert report["ledger"]["spans"][1]["reason"] == "no_parser_elements"
    assert report["ledger"]["compiled"] is False


def test_a_named_unsupported_field_replaces_other_and_does_not_roundtrip() -> None:
    module = _inventory()
    ledger = {
        "spans": [
            {
                "id": "a",
                "status": "gap",
                "text": "The agency shall send the notice to the requester.",
                "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS",
                "unsupported_fields": ["recipient"],
            },
            {
                "id": "b",
                "status": "gap",
                "text": "All legislative Powers shall be vested in a Congress.",
                "reason": "CanonicalErrorCode.UNSUPPORTED_SEMANTICS",
                "unsupported_fields": ["recipient"],
                "facet": "structure",
            },
        ]
    }
    tagged = module.tag_facets(ledger)
    facets = {span["id"]: span.get("facet") for span in tagged["spans"]}
    assert facets["a"] == "recipient"
    assert facets["b"] == "structure"
    assert tagged["spans"][0]["status"] == "gap"
    assert "roundtrip_ok" not in tagged["facet_counts"]


def test_editorial_notes_are_not_operative_spans() -> None:
    module = _inventory()
    text = "Article I\nSection 1\nAll legislative Powers herein granted shall be vested in a Congress.\nNote:\n*Superseded by section 3 of the 20th amendment.\n"
    inventory = module.inventory_constitution(text)
    notes = [span for span in inventory["spans"] if span["text"].lower().startswith("note") or span["text"].lower().startswith("*superseded")]
    assert notes
    assert all(span["status"] == "non_operative" for span in notes)


def test_gaps_are_tagged_without_a_model() -> None:
    module = _inventory()
    ledger = {
        "spans": [
            {"id": "a", "status": "gap", "text": "We the People", "reason": "no_parser_elements"},
            {"id": "b", "status": "gap", "text": "No Person shall be a Representative who shall not have attained to the Age of twenty five Years, and been seven Years a Citizen.", "reason": "UNSUPPORTED_SEMANTICS"},
            {"id": "c", "status": "inactive", "text": "No intoxicating liquor shall be sold.", "reason": "repealed"},
        ]
    }
    tagged = module.tag_facets(ledger)
    facets = {span["id"]: span.get("facet") for span in tagged["spans"]}
    assert facets["a"] == "no_parser_elements"
    assert facets["b"] == "qualification_swallowed"
    assert "facet" not in tagged["spans"][2]
    assert tagged["facet_counts"] == {"no_parser_elements": 1, "qualification_swallowed": 1}


def test_retag_other_uses_the_inspector_and_does_not_roundtrip() -> None:
    module = _inventory()
    ledger = {
        "spans": [
            {"id": "a", "status": "gap", "facet": "other", "text": "shall be vested in a Congress", "reason": "UNSUPPORTED_SEMANTICS"},
            {"id": "b", "status": "gap", "facet": "qualification_swallowed", "text": "keep", "reason": "UNSUPPORTED_SEMANTICS"},
            {"id": "c", "status": "inactive", "facet": "other", "text": "sold", "reason": "repealed"},
        ]
    }
    tagged = module.retag_other(ledger, lambda text: "structure" if "vested" in text else "other")
    assert tagged["spans"][0]["facet"] == "structure"
    assert tagged["spans"][0]["status"] == "gap"
    assert tagged["spans"][1]["facet"] == "qualification_swallowed"
    assert tagged["spans"][2]["status"] == "inactive"
    assert "roundtrip_ok" not in {span["status"] for span in tagged["spans"]}


def test_a_proposed_fragment_is_invisible_until_it_has_a_fixture() -> None:
    import importlib.util
    import sys
    path = __import__("pathlib").Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "logic" / "autoformal" / "ontology_fragments.py"
    spec = importlib.util.spec_from_file_location("ontology_fragments_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    registry = module.FragmentRegistry()
    assert registry.propose({"relation": "qualifies", "domain": "Person", "range": "Office"})["reason"] == "unattached"
    proposed = registry.propose({
        "relation": "qualifies",
        "domain": "Person",
        "range": "Office",
        "attachment": "conditions",
        "inverse": "qualified_by",
        "decompiler_phrase": "{person} qualifies for {office} at {age} and {years}",
        "fixture_id": "",
    })
    assert proposed["status"] == "proposed"
    assert proposed["admitted"] is False
    assert registry.visible_to_compiler() == []
    assert registry.admit("qualifies")["reason"] == "fixture_required"
    registry.fragments["qualifies"]["fixture_id"] = "not-the-constitution"
    admitted = registry.admit("qualifies")
    assert admitted["status"] == "admitted"
    assert admitted["attachment"] == "conditions"
    assert registry.visible_to_compiler()[0]["relation"] == "qualifies"
    assert registry.by_attachment()["conditions"][0]["relation"] == "qualifies"
    registry.fragments["qualifies"]["status"] = "proposed"
    registry.fragments["qualifies"]["admitted"] = False
    assert "conditions" not in registry.by_attachment()


def test_inventory_marks_preamble_signature_and_a_text_backed_repeal() -> None:
    inventory = _inventory().inventory_constitution(TEXT)
    assert inventory["compiled"] is False
    by_status = {}
    for span in inventory["spans"]:
        by_status.setdefault(span["status"], []).append(span)
    assert any(span["unit_id"] == "preamble" and span["status"] == "non_operative" for span in inventory["spans"])
    assert any(span["unit_id"] == "signature" and span["status"] == "non_operative" for span in inventory["spans"])
    assert any(span["unit_id"] == "art-1.sec-1" and span["status"] == "uncompiled" for span in inventory["spans"])
    assert any(span["unit_id"].startswith("amend-18") and span["status"] == "inactive" for span in inventory["spans"])
    assert any("hereby repealed" in span["text"] and span["status"] == "uncompiled" for span in inventory["spans"])
    assert inventory["edges"] == [{
        "kind": "repeal",
        "source": next(span["id"] for span in inventory["spans"] if "hereby repealed" in span["text"]),
        "target": "amend-18",
    }]
    assert all(span["status"] in {"uncompiled", "non_operative", "inactive"} for span in inventory["spans"])
