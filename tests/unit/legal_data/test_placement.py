"""Placement labels name the instrument and are not provision numbers."""

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.placement import (
    classify_placement,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    render_atomic,
)

_WHOLE = (
    "The minister shall keep the register and apply this Act throughout the territory "
    "to every person who resides there."
)
_MULTI = (
    "1. Short title\nThis Act may be cited as the Example Act.\n\n"
    "2. Interpretation\nIn this Act, person includes a body corporate.\n"
)
_ENABLING = (
    "Under subsection 269A(7) of the Act, the Minister hereby adopts the recovery plan. "
    "This instrument applies on the day it is registered."
)


def test_placement_labels_stay_outside_the_locator_set() -> None:
    assert (
        classify_placement(
            _WHOLE,
            "en",
            status="instrument_only",
            instrument="Workers Compensation Act",
        )
        == "whole_instrument"
    )
    assert (
        classify_placement(_MULTI, "en", status="instrument_only", instrument="Example Act")
        == "unsplit_multi"
    )
    assert (
        classify_placement(
            _ENABLING,
            "en",
            status="instrument_only",
            instrument="Instrument adopting Recovery Plans",
        )
        == "enabling_instrument"
    )
    assert (
        classify_placement(_WHOLE, "en", status="unresolved", instrument="")
        == "unresolved"
    )
    assert (
        classify_placement(_MULTI, "en", status="structural", instrument="Example Act")
        == ""
    )


def test_jsonld_and_text_copy_placement_without_making_it_a_locator() -> None:
    record = {
        "entry_cid": "bafkrei-whole",
        "title": "Workers Compensation Act",
        "text": _WHOLE,
        "jurisdiction": "AU",
        "language": "en",
        "provenance": {
            "document_role": "law",
            "heading_status": "instrument_only",
            "heading_instrument": "Workers Compensation Act",
            "heading_placement": "whole_instrument",
        },
    }
    document = render_atomic(record, "jsonld")
    properties = {
        item["propertyID"]: item["value"] for item in document["additionalProperty"]
    }
    assert properties["heading_status"] == "instrument_only"
    assert properties["heading_instrument"] == "Workers Compensation Act"
    assert properties["heading_placement"] == "whole_instrument"
    assert "section" not in properties
    assert "article" not in properties
    text = render_atomic(record, "text")
    assert text["heading_placement"] == "whole_instrument"
    assert text["locator"] == {}
