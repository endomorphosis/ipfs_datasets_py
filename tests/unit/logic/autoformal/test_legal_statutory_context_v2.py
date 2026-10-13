"""Exact normalized-view geometry and open obligations on fictional HTML."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context

URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm"
RAW = '''<meta charset="utf-8"><h3 class="section-head">&sect;1. Fictional fixture</h3>
<p class="statutory-body">(a) Élodie  shall notify the office; the office shall reply.</p>
<p class="statutory-body-1em">(1) The office means a café office.</p>
<p class="statutory-body">(b) aaaa; αβ; 🏛.</p>
<p class="source-credit">Fictional source credit.</p>'''.encode("utf-8")


@pytest.fixture
def source():
    return context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1")


def occurrences(source, text="the office"):
    return context.exact_view_occurrences(source, RAW, text=text)


def requests():
    return [{"kind": kind, "availability": "missing", "locator": None,
             "expected_view_id": None, "candidate_selector": None}
            for kind in context.DEPENDENCY_KINDS]


def packet_for(source, selector, dependency_requests=None):
    return context.build_context_packet(source, RAW, char_start=selector["char_start"],
        char_end=selector["char_end"], dependency_requests=dependency_requests)


def validate(packet, source, selector, dependency_requests=None):
    return context.validate_context_packet(packet, source, RAW, expected_selector=selector,
                                           dependency_requests=dependency_requests)


def test_v1_extraction_is_unchanged_and_v2_names_only_normalized_coordinates(source):
    before = deepcopy(source)
    view = context.normalized_document_view(source, RAW)
    context.validate_document(source, RAW)
    assert context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1") == before
    assert source == before and source["schema"] == "legal-official-statutory-context/v1"
    assert "utf8_byte_start" not in source["paragraphs"][0]
    assert view["normalization_profile"] == context.NORMALIZATION_PROFILE
    assert view["raw_html_coordinate_mapping_verified"] is False
    assert view["utf8_bytes"] > view["unicode_code_points"]
    assert "Élodie shall" in source["document_text"] and "Élodie  shall" not in source["document_text"]


def test_unicode_and_repeated_mentions_have_exact_distinct_occurrence_ids(source):
    first, second = occurrences(source)
    assert first["text"] == second["text"] == "the office"
    assert first["text_sha256"] == second["text_sha256"]
    assert first["occurrence_id"] != second["occurrence_id"]
    assert first["char_start"] != second["char_start"]
    assert first["char_start"] != first["utf8_byte_start"]
    for selector in (first, second, occurrences(source, "🏛")[0]):
        text = source["document_text"]
        assert text[selector["char_start"]:selector["char_end"]] == selector["text"]
        assert text.encode()[selector["utf8_byte_start"]:selector["utf8_byte_end"]].decode() == selector["text"]
        context.validate_source_selector(selector, source, RAW)


def test_overlap_and_absence_remain_explicit_without_normalization_or_truncation(source):
    assert len(occurrences(source, "aa")) == 3
    assert occurrences(source, "Élodie  shall") == []
    with pytest.raises(ValueError, match="inventory incomplete"):
        context.exact_view_occurrences(source, RAW, text="aa", max_occurrences=2)
    with pytest.raises(ValueError):
        context.exact_view_occurrences(source, RAW, text="")


@pytest.mark.parametrize("damage", ["char", "byte", "bool_byte", "bool_char", "text", "view", "id", "extra", "missing"])
def test_selector_rejects_corrupt_geometry_and_repaired_text_hash(source, damage):
    selector = deepcopy(occurrences(source)[0])
    if damage == "char": selector["char_start"] += 1
    elif damage == "byte": selector["utf8_byte_start"] += 1
    elif damage == "bool_byte": selector["utf8_byte_start"] = True
    elif damage == "bool_char": selector["char_start"] = True
    elif damage == "text":
        selector["text"] = "a different office"
        selector["text_sha256"] = context.sha(selector["text"])
    elif damage == "view": selector["view_id"] = "legal-normalized-view:sha256:" + "0" * 64
    elif damage == "id": selector["occurrence_id"] = "repaired-looking-id"
    elif damage == "missing": selector.pop("char_start")
    else: selector["raw_html_bytes"] = True
    with pytest.raises(ValueError):
        context.validate_source_selector(selector, source, RAW)


def test_reordered_document_and_new_edition_cannot_reuse_old_selector(source):
    selector = occurrences(source)[0]
    lines = RAW.splitlines(keepends=True)
    lines[1], lines[2] = lines[2], lines[1]
    changed = b"".join(lines)
    reordered = context.extract_document(changed, url=URL, edition=2024, legal_id="usc:us:10:1")
    with pytest.raises(ValueError):
        context.validate_source_selector(selector, reordered, changed)
    next_url = URL.replace("2024", "2025")
    next_doc = context.extract_document(RAW, url=next_url, edition=2025, legal_id="usc:us:10:1")
    with pytest.raises(ValueError):
        context.validate_source_selector(selector, next_doc, RAW)
    corrupt = deepcopy(source)
    corrupt["paragraphs"] = list(reversed(corrupt["paragraphs"]))
    with pytest.raises(ValueError):
        context.normalized_document_view(corrupt, RAW)


def test_packet_defaults_preserve_all_open_categories_and_false_authority(source):
    selector = occurrences(source)[0]
    packet = packet_for(source, selector)
    result = validate(packet, source, selector)
    assert result["source_geometry_verified"] is True
    assert result["open_dependency_slots"] == 6
    assert [slot["kind"] for slot in packet["dependency_slots"]] == list(context.DEPENDENCY_KINDS)
    assert all(slot["status"] == "open_missing" and slot["open"] for slot in packet["dependency_slots"])
    for key in ("context_closure_verified", "source_semantics_verified", "training_qualified",
                "proof_authority", "raw_html_coordinate_mapping_verified", "dependency_inventory_exhaustive"):
        assert packet[key] is False


def test_locator_unavailable_stale_and_local_content_all_remain_open(source):
    selector = occurrences(source)[0]
    deps = requests()
    deps[0]["locator"] = "section 123, definition of office"
    deps[0]["availability"] = "available"  # A locator still supplies no content.
    deps[1].update(availability="unavailable", locator="unavailable authority")
    deps[2].update(expected_view_id="legal-normalized-view:sha256:" + "0" * 64)
    deps[3].update(availability="available", candidate_selector=occurrences(source, "shall reply")[0])
    packet = packet_for(source, selector, deps)
    validate(packet, source, selector, deps)
    assert [slot["status"] for slot in packet["dependency_slots"][:4]] == [
        "open_locator_only", "open_unavailable", "open_stale", "open_content_available"]
    assert all(slot["open"] and slot["attachments"] == []
               and not slot["semantic_attachment_verified"] for slot in packet["dependency_slots"])


def test_repaired_packet_cannot_retarget_an_identical_text_occurrence(source):
    first, second = occurrences(source)
    rewritten = packet_for(source, second)
    with pytest.raises(ValueError, match="source geometry"):
        validate(rewritten, source, first)


@pytest.mark.parametrize("damage", ["reorder", "drop", "locator_attachment", "closure", "training", "view_mapping"])
def test_packet_rejects_reordered_or_missing_obligations_and_authority_inflation(source, damage):
    selector = occurrences(source)[0]
    packet = packet_for(source, selector)
    if damage == "reorder": packet["dependency_slots"].reverse()
    elif damage == "drop": packet["dependency_slots"].pop()
    elif damage == "locator_attachment": packet["dependency_slots"][0]["attachments"] = ["section 123"]
    elif damage == "closure": packet["context_closure_verified"] = True
    elif damage == "training": packet["training_qualified"] = True
    else: packet["raw_html_coordinate_mapping_verified"] = True
    body = {key: value for key, value in packet.items() if key != "packet_id"}
    packet["packet_id"] = "legal-context-packet:sha256:" + context._context_digest(body)
    with pytest.raises(ValueError):
        validate(packet, source, selector)


def test_candidate_corrupt_offsets_fail_and_input_mutation_cannot_change_packet(source):
    selector = occurrences(source)[0]
    deps = requests()
    deps[0].update(availability="available", candidate_selector=deepcopy(selector))
    packet = packet_for(source, selector, deps)
    source["document_text"] = "caller mutated"
    deps[0]["candidate_selector"]["utf8_byte_end"] += 1
    assert packet["source_document"]["document_text"] != "caller mutated"
    fresh = context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1")
    with pytest.raises(ValueError, match="coordinates differ"):
        packet_for(fresh, selector, deps)
