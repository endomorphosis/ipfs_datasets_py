"""Plaintext context preserves physical custody and six unresolved obligations.

The existing plaintext-definition and parent/cache fixtures supply every input.
Positive cases replay their real public owners; authored text is not legal gold.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parent_owner
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2 as bridge
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as official_context
from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as contexts


@pytest.fixture(scope="module")
def fixtures():
    spec = importlib.util.spec_from_file_location(
        "plaintext_context_existing_definition_fixture",
        Path(__file__).with_name("test_plaintext_definition_custody.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def parent_case(fixtures, tmp_path):
    return fixtures.parent_case.__wrapped__(tmp_path)


@pytest.fixture
def definition_case(fixtures, parent_case):
    report, request, inputs = fixtures.prepare(parent_case)
    candidate, _, _ = fixtures.adapt(report, request, inputs)
    return {"report": report, "request": request, "inputs": inputs, "candidate": candidate}


def selected(case, role="definition_head"):
    binding = next(row for row in case["report"]["source_bindings"] if row["role"] == role)
    return next(row for row in case["candidate"]["source_occurrences"]
                if row["record_cid"] == binding["source_occurrence_cid"])


def arguments(case, occurrence=None):
    source = case["report"]["parent_source_binding"]
    occurrence = source["selector"] if occurrence is None else occurrence
    inputs = dict(case["inputs"], selected_occurrence=deepcopy(occurrence),
        expected_selected_occurrence_cid=occurrence["record_cid"],
        expected_source_binding_sha256=source["source_binding_sha256"])
    bundle = inputs.pop("parent_bundle")
    return bundle, inputs


def build(case, occurrence=None, **overrides):
    bundle, inputs = arguments(case, occurrence)
    return contexts.build_parent_context_packet_v1(bundle, **{**inputs, **overrides})


def validate(packet, case, occurrence=None, **overrides):
    bundle, inputs = arguments(case, occurrence)
    return contexts.validate_parent_context_packet_v1(packet, bundle, **{**inputs, **overrides})


def requests():
    return [{"kind": kind, "availability": "missing", "locator": None,
        "expected_view_id": None, "candidate_selector": None}
        for kind in contexts.DEPENDENCY_KINDS]


def repair_packet_id(packet):
    packet["packet_id"] = "legal-parent-literal-context-packet:sha256:" + contexts.digest(
        {key: value for key, value in packet.items() if key != "packet_id"})


def assert_open(packet):
    assert packet["schema"] == contexts.PARENT_CONTEXT_PACKET_SCHEMA
    assert packet["authority"] and all(value is False for value in packet["authority"].values())
    assert [row["kind"] for row in packet["dependency_slots"]] == list(contexts.DEPENDENCY_KINDS)
    assert len(packet["dependency_slots"]) == len({row["slot_id"] for row in packet["dependency_slots"]}) == 6
    for row in packet["dependency_slots"]:
        assert row["slot_id"].startswith("legal-parent-literal-context-slot:sha256:")
        assert row["open"] is True and row["attachments"] == []
        assert row["semantic_attachment_verified"] is False


@pytest.mark.parametrize("whole", [True, False])
def test_whole_and_derived_definition_occurrences_keep_exact_plaintext_custody(
        fixtures, definition_case, monkeypatch, whole):
    def no_markup(*args, **kwargs):
        pytest.fail("literal context must not extract or synthesize HTML")
    monkeypatch.setattr(official_context, "extract_document", no_markup)
    before = deepcopy(definition_case)
    source = definition_case["report"]["parent_source_binding"]
    occurrence = source["selector"] if whole else selected(definition_case)
    packet = build(definition_case, occurrence)
    assert_open(packet)
    assert packet["selection"] == occurrence
    assert packet["source_version"] == source["source_version"]
    assert packet["source_version"]["edition"] == parent_owner.UNDECLARED_EDITION
    assert packet["source_version"]["raw_artifact"]["media_type"] == "text/plain"
    assert packet["source_version"]["extracted_view"]["normalization_profile"] == "identity/v1"
    assert packet["original_context"] == source["context"]
    assert packet["original_context"]["availability"] == "required_unavailable"
    assert packet["original_context"]["missing_requirements"] == list(parent_owner.MISSING_CONTEXT)
    binding = packet["source_view_binding"]
    assert binding["parent_manifest_cid"] == source["parent_manifest_cid"]
    assert binding["source_binding_sha256"] == source["source_binding_sha256"]
    assert binding["root_source_occurrence_cid"] == source["selector"]["record_cid"]
    assert binding["companion_record_cid"] == source["companion_record"]["record_cid"]
    assert binding["original_context_cid"] == source["context"]["record_cid"]
    assert binding["edition"] == parent_owner.UNDECLARED_EDITION
    text = fixtures.TEXT
    start, end = occurrence["start_char"], occurrence["end_char"]
    assert occurrence["span_text"] == text[start:end]
    assert occurrence["start_utf8"] == len(text[:start].encode("utf-8"))
    assert occurrence["end_utf8"] == len(text[:end].encode("utf-8"))
    assert occurrence["end_utf8"] - occurrence["start_utf8"] > end - start
    if whole:
        assert "\n" in packet["selection"]["span_text"]
    assert all(row["status"] == "open_missing" for row in packet["dependency_slots"])
    checked = validate(packet, definition_case, occurrence)
    assert checked["schema"] == contexts.PARENT_VALIDATION_SCHEMA
    assert checked["packet_id"] == packet["packet_id"]
    assert checked["selected_occurrence_cid"] == occurrence["record_cid"]
    assert checked["source_geometry_verified"] is True and checked["open_dependency_slots"] == 6
    assert definition_case == before


def test_public_preparation_and_validation_replay_the_complete_original_parent_owner(
        definition_case, monkeypatch):
    original = parent_owner.validate_parent_occurrence_corpus
    calls = []
    def observed(bundle, **kwargs):
        assert bundle == definition_case["inputs"]["parent_bundle"]
        assert kwargs["report_bytes"] == definition_case["inputs"]["report_bytes"]
        assert kwargs["replay_inputs"] == definition_case["inputs"]["replay_inputs"]
        calls.append(bundle["manifest"]["record_cid"])
        return original(bundle, **kwargs)
    monkeypatch.setattr(parent_owner, "validate_parent_occurrence_corpus", observed)
    packet = build(definition_case)
    assert calls == [definition_case["inputs"]["expected_manifest_cid"]]
    calls.clear()
    validate(packet, definition_case)
    assert calls == [definition_case["inputs"]["expected_manifest_cid"]]


@pytest.mark.parametrize("original", ["physical_parent", "original_report"])
def test_saved_packet_cannot_outlive_changed_original_physical_evidence(definition_case, original):
    packet = build(definition_case)
    if original == "physical_parent":
        descriptor = definition_case["inputs"]["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
        path = Path(descriptor["local_path"])
        path.write_bytes(path.read_bytes() + b"changed owned plaintext fixture")
    else:
        definition_case["inputs"]["report_bytes"]["parent_text_views"] += b" "
    with pytest.raises(ValueError):
        validate(packet, definition_case)


def test_equal_text_at_distinct_physical_rows_does_not_share_context_identity(
        fixtures, parent_case, definition_case):
    report, request, inputs = fixtures.prepare(parent_case, parent_index=1)
    candidate, _, _ = fixtures.adapt(report, request, inputs)
    second = {"report": report, "request": request, "inputs": inputs, "candidate": candidate}
    left, right = build(definition_case, selected(definition_case)), build(second, selected(second))
    assert left["selection"]["span_text"] == right["selection"]["span_text"]
    assert left["source_version"]["extracted_view"]["sha256"] == right["source_version"]["extracted_view"]["sha256"]
    assert left["source_version"]["record_cid"] != right["source_version"]["record_cid"]
    assert left["source_view_binding"]["view_id"] != right["source_view_binding"]["view_id"]
    assert {row["slot_id"] for row in left["dependency_slots"]}.isdisjoint(
        row["slot_id"] for row in right["dependency_slots"])
    with pytest.raises(ValueError):
        validate(left, second, selected(second))


def test_whole_field_cache_companions_keep_distinct_identity(fixtures, tmp_path):
    helpers = fixtures.helper("test_plaintext_graph_custody")
    data = helpers.helper("test_corpus_parent_occurrence_adapter").case(
        tmp_path, source_text=fixtures.TEXT, parent_texts=[fixtures.TEXT, fixtures.TEXT])
    bundle = parent_owner.build_parent_occurrence_corpus(**data["arguments"])
    case = {"data": data, "bundle": bundle,
        "records": {row["record_cid"]: row for row in bundle["records"]}}
    matches = helpers.companions(case, parent_owner.MATCH_SCHEMA)
    first = matches[0]
    second = next(row for row in matches if row["source_occurrence_cid"] == first["source_occurrence_cid"]
        and row["cache_row_record_cid"] != first["cache_row_record_cid"])
    packets = []
    for companion in (first, second):
        source = helpers.bind(case, companion)
        inputs = helpers.binding_arguments(case, companion)
        original_bundle = inputs.pop("parent_bundle")
        packets.append(contexts.build_parent_context_packet_v1(original_bundle, **inputs,
            selected_occurrence=source["selector"],
            expected_selected_occurrence_cid=source["selector"]["record_cid"],
            expected_source_binding_sha256=source["source_binding_sha256"]))
    left, right = packets
    assert left["selection"] == right["selection"]
    assert left["source_view_binding"]["companion_record_cid"] != right["source_view_binding"]["companion_record_cid"]
    assert left["source_view_binding"]["view_id"] != right["source_view_binding"]["view_id"]
    assert left["packet_id"] != right["packet_id"]


def test_same_spelling_derived_occurrences_and_cross_line_candidate_keep_exact_geometry(
        fixtures, parent_case):
    request, inputs = fixtures.case(parent_case)
    declaration = request["declaration"]
    declaration["contributor_spans"] = [fixtures.interval(fixtures.TEXT,
        fixtures.TEXT.index("The term"), len(fixtures.TEXT))]
    declaration["body"] = {"op": "any", "operands": [
        {"op": "atom", "span": fixtures.span(fixtures.TEXT, "registered")},
        {"op": "atom", "span": fixtures.span(fixtures.TEXT, "registered", last=True)},
        {"op": "atom", "span": fixtures.interval(fixtures.TEXT,
            fixtures.TEXT.index("registered"), fixtures.TEXT.rindex("registered") + len("registered"))}]}
    report = bridge.prepare_parent_definition_v1(request, **inputs)
    candidate, _, _ = fixtures.adapt(report, request, inputs)
    case = {"report": report, "request": request, "inputs": inputs, "candidate": candidate}
    occurrences = [selected(case, "definition_body/000" + str(i)) for i in range(3)]
    packets = [build(case, occurrence) for occurrence in occurrences]
    first, last, cross_line = packets
    assert first["selection"]["span_text"] == last["selection"]["span_text"] == "registered"
    assert first["selection"]["record_cid"] != last["selection"]["record_cid"]
    assert first["source_view_binding"] == last["source_view_binding"]
    assert {row["slot_id"] for row in first["dependency_slots"]}.isdisjoint(
        row["slot_id"] for row in last["dependency_slots"])
    occurrence = cross_line["selection"]
    assert "\n" in occurrence["span_text"]
    assert occurrence["span_text"] == fixtures.TEXT[occurrence["start_char"]:occurrence["end_char"]]
    assert occurrence["start_utf8"] == len(fixtures.TEXT[:occurrence["start_char"]].encode())
    assert occurrence["end_utf8"] == len(fixtures.TEXT[:occurrence["end_char"]].encode())
    validate(cross_line, case, occurrences[2])
    with pytest.raises(ValueError):
        validate(first, case, occurrences[1])


def test_valid_parent_fragment_cannot_replace_required_whole_field_root(fixtures, parent_case):
    helpers = parent_case["helpers"]
    fragment = helpers.companions(parent_case, parent_owner.MATCH_SCHEMA)[0]
    source = helpers.bind(parent_case, fragment)
    assert source["selector"]["span_text"] == "registered"
    assert len(source["selector"]["span_text"]) < len(fixtures.TEXT)
    inputs = helpers.binding_arguments(parent_case, fragment)
    bundle = inputs.pop("parent_bundle")
    with pytest.raises(ValueError):
        contexts.build_parent_context_packet_v1(bundle, **inputs,
            selected_occurrence=source["selector"],
            expected_selected_occurrence_cid=source["selector"]["record_cid"],
            expected_source_binding_sha256=source["source_binding_sha256"])


def test_content_locator_missing_unavailable_and_stale_dependencies_all_remain_open(definition_case):
    occurrence = selected(definition_case)
    baseline = build(definition_case, occurrence)
    current = baseline["source_view_binding"]["view_id"]
    stale = current.rsplit(":", 1)[0] + ":" + ("0" * 64 if not current.endswith("0" * 64) else "1" * 64)
    declared = requests()
    declared[0].update(availability="available", expected_view_id=current, candidate_selector=deepcopy(occurrence))
    declared[1].update(locator="declared:external-authority")
    declared[2].update(availability="unavailable")
    declared[3].update(expected_view_id=stale)
    declared[5].update(availability="available", locator="declared:unfetched-reference")
    original = deepcopy(declared)
    packet = build(definition_case, occurrence, dependency_requests=declared)
    assert_open(packet)
    assert [row["status"] for row in packet["dependency_slots"]] == [
        "open_content_available", "open_locator_only", "open_unavailable", "open_stale",
        "open_missing", "open_locator_only"]
    assert packet["original_context"] == baseline["original_context"]
    validate(packet, definition_case, occurrence, dependency_requests=declared)
    declared[0]["candidate_selector"]["span_text"] = "mutated caller"
    assert packet["dependency_slots"][0]["candidate_selector"] == original[0]["candidate_selector"]


@pytest.mark.parametrize("damage", ["missing_kind", "duplicate_kind", "extra_field",
    "unknown_availability", "stale_candidate", "wrong_candidate_bytes", "locator_limit"])
def test_closed_dependency_population_and_exact_candidate_geometry_refuse(fixtures, definition_case, damage):
    occurrence = selected(definition_case)
    baseline = build(definition_case, occurrence)
    declared = requests()
    if damage == "missing_kind":
        declared.pop()
    elif damage == "duplicate_kind":
        declared[-1]["kind"] = declared[0]["kind"]
    elif damage == "extra_field":
        declared[0]["accepted"] = True
    elif damage == "unknown_availability":
        declared[0]["availability"] = "reviewed"
    elif damage == "locator_limit":
        declared[0]["locator"] = "x" * 4097
    else:
        declared[0].update(availability="available", expected_view_id=baseline["source_view_binding"]["view_id"],
            candidate_selector=deepcopy(occurrence))
        if damage == "stale_candidate":
            current = declared[0]["expected_view_id"]
            declared[0]["expected_view_id"] = current.rsplit(":", 1)[0] + ":" + "0" * 64
        else:
            declared[0]["candidate_selector"]["start_utf8"] += 1
            declared[0]["candidate_selector"] = fixtures.reseal(declared[0]["candidate_selector"])
    with pytest.raises(ValueError):
        build(definition_case, occurrence, dependency_requests=declared)


@pytest.mark.parametrize("damage", ["selection", "drop_kind", "attach", "close", "edition", "original_context", "authority"])
def test_resealed_packet_cannot_change_external_selection_context_or_authority(fixtures, definition_case, damage):
    occurrence = selected(definition_case)
    packet = build(definition_case, occurrence)
    if damage == "selection":
        packet["selection"] = definition_case["report"]["parent_source_binding"]["selector"]
    elif damage == "drop_kind":
        packet["dependency_slots"].pop()
    elif damage == "attach":
        packet["dependency_slots"][0]["attachments"] = [deepcopy(occurrence)]
    elif damage == "close":
        packet["dependency_slots"][0]["open"] = False
    elif damage == "edition":
        packet["source_view_binding"]["edition"] = 2024
    elif damage == "original_context":
        packet["original_context"].update(availability="none_required", missing_requirements=[], context_references=[])
        packet["original_context"] = fixtures.reseal(packet["original_context"])
    else:
        packet["authority"]["source_semantics_verified"] = True
    repair_packet_id(packet)
    with pytest.raises(ValueError):
        validate(packet, definition_case, occurrence)


@pytest.mark.parametrize("pin", ["expected_selected_occurrence_cid", "expected_source_binding_sha256"])
def test_independent_selection_and_source_binding_pins_cannot_be_replaced(definition_case, pin):
    occurrence = selected(definition_case)
    wrong = definition_case["report"]["source_version"]["record_cid"] if pin.endswith("cid") else "0" * 64
    with pytest.raises(ValueError):
        build(definition_case, occurrence, **{pin: wrong})


@pytest.mark.parametrize("damage", ["source_version", "utf8_geometry"])
def test_resealed_selected_occurrence_still_requires_original_source_correspondence(
        fixtures, definition_case, damage):
    occurrence = deepcopy(selected(definition_case))
    if damage == "source_version":
        occurrence["source_version_cid"] = definition_case["report"]["parent_source_binding"]["parent_record"]["record_cid"]
    else:
        occurrence["start_utf8"] += 1
        occurrence["end_utf8"] += 1
    occurrence = fixtures.reseal(occurrence)
    # The offered record and independent CID deliberately agree. Refusal must
    # come from correspondence with the replayed source, not a stale outer pin.
    bundle, inputs = arguments(definition_case, occurrence)
    assert inputs["expected_selected_occurrence_cid"] == occurrence["record_cid"]
    with pytest.raises(ValueError):
        contexts.build_parent_context_packet_v1(bundle, **inputs)


def test_lowered_parent_population_bound_is_forwarded_without_truncation(definition_case):
    with pytest.raises(ValueError):
        build(definition_case, parent_limits={"max_records": 1})


def test_oversized_offered_packet_refuses_before_original_parent_replay(definition_case, monkeypatch):
    packet = build(definition_case)
    packet["oversized_unrecognized_field"] = "x" * (contexts.MAX_CONTEXT_PACKET_BYTES + 1)
    def forbidden_replay(*args, **kwargs):
        pytest.fail("oversized packet reached physical parent replay")
    monkeypatch.setattr(parent_owner, "validate_parent_occurrence_corpus", forbidden_replay)
    with pytest.raises(ValueError):
        validate(packet, definition_case)
