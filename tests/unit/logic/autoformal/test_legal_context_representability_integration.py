"""Fictional source occurrences keep identity and open obligations across APIs."""
import copy

import pytest

from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_source_representability as representation


URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm"
TEXT = "The officer shall record café receipts under section 2."
RAW = ('<h3 class="section-head">§1. Fictional fixture</h3>'
       f'<p class="statutory-body">(a) {TEXT}</p>'
       f'<p class="statutory-body">(b) {TEXT}</p>').encode()


def test_repeated_occurrences_survive_context_and_representability_handoff():
    document = context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1")
    selectors = context.exact_view_occurrences(document, RAW, text=TEXT)
    assert len(selectors) == 2
    requests, packets = [], []
    for selector in selectors:
        packet = context.build_context_packet(document, RAW, char_start=selector["char_start"],
                                              char_end=selector["char_end"])
        checked = context.validate_context_packet(packet, document, RAW, expected_selector=selector)
        assert checked["context_closure_verified"] is False
        unit = representation.bind_source_unit(document["document_text"],
            document_id=document["document_id"], document_revision=packet["normalized_view"]["view_id"],
            occurrence_id=selector["occurrence_id"], char_start=selector["char_start"],
            char_end=selector["char_end"], region_kind="codified_body")
        requests.append({"unit": unit, "document_text": document["document_text"],
                         "requires_context_resolution": True})
        packets.append(packet)
    expected = [row["unit"]["unit_sha256"] for row in requests]
    inventory = representation.inventory_source_representability(requests, expected_unit_sha256s=expected)
    assert inventory["physical_occurrence_count"] == 2
    assert inventory["unresolved_context_presentations"] == [0, 1]
    assert all("cross_reference" in row["proposal"]["labels"] for row in inventory["rows"])
    assert requests[0]["unit"]["source_sha256"] == requests[1]["unit"]["source_sha256"]
    assert expected[0] != expected[1]
    assert packets[0]["selection"]["utf8_byte_start"] != packets[1]["selection"]["utf8_byte_start"]
    with pytest.raises(ValueError):
        context.validate_context_packet(packets[1], document, RAW, expected_selector=selectors[0])


def test_omitting_a_context_bound_occurrence_cannot_shrink_the_expected_population():
    document = context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1")
    requests = []
    for selector in context.exact_view_occurrences(document, RAW, text=TEXT):
        requests.append({"unit": representation.bind_source_unit(document["document_text"],
            document_id=document["document_id"], document_revision=selector["view_id"],
            occurrence_id=selector["occurrence_id"], char_start=selector["char_start"],
            char_end=selector["char_end"], region_kind="codified_body"),
            "document_text": document["document_text"]})
    expected = [row["unit"]["unit_sha256"] for row in requests]
    with pytest.raises(ValueError):
        representation.inventory_source_representability(copy.deepcopy(requests[:1]),
                                                           expected_unit_sha256s=expected)
