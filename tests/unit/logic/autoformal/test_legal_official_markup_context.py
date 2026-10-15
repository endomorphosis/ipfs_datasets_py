"""Authored V2 context packets retain exact geometry and six unresolved slots."""

import hashlib
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from ipfs_datasets_py.logic.autoformal import legal_context_obligations as obligations
from ipfs_datasets_py.logic.autoformal import legal_official_document_views as views
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as contexts


@pytest.fixture
def source_inputs():
    raw = (
        '<html><head><meta charset="utf-8"><title>Authored</title></head><body>'
        '<!-- field-start:head --><h3 class="section-head">§1. Authored</h3>'
        "<!-- field-end:head --><!-- field-start:statute -->"
        '<p class="statutory-body">(a) Café Ω.</p>'
        '<p class="statutory-body-1em">(b) Café Ω.</p>'
        '<p class="statutory-body-block-1em">Such term has a tail.</p>'
        "<!-- field-end:statute --></body></html>"
    ).encode()
    url = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-chap1-sec1.htm"
    descriptor = {
        "schema": custody.DESCRIPTOR_SCHEMA,
        "legal_id": "usc:us:10:1",
        "edition": 2024,
        "package_id": "USCODE-2024-title10",
        "granule_id": "USCODE-2024-title10-chap1-sec1",
        "url": url,
        "retrieved_at": "2026-10-15T01:00:00Z",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "http_provenance": {
            "requested_url": url,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "etag": None,
            "last_modified": None,
        },
    }
    inputs = {
        "descriptor": descriptor,
        "expected_descriptor_sha256": custody.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256": descriptor["raw_sha256"],
        "expected_raw_bytes": len(raw),
    }
    report = views.prepare_official_document_view(raw, **inputs)
    inputs["expected_report_sha256"] = views.document_view_report_sha256(report)
    text = report["document"]["document_text"]
    first = text.index("Café Ω")
    last = text.rindex("Café Ω")
    return (
        report,
        raw,
        inputs,
        {"char_start": first, "char_end": first + len("Café Ω")},
        {"char_start": last, "char_end": last + len("Café Ω")},
    )


def requests():
    return [
        {
            "kind": kind,
            "availability": "missing",
            "locator": None,
            "expected_view_id": None,
            "candidate_selector": None,
        }
        for kind in contexts.DEPENDENCY_KINDS
    ]


def packet(source_inputs, dependency_requests=None):
    report, raw, inputs, first, _ = source_inputs
    return contexts.build_context_packet_v2(
        report, raw, **first, dependency_requests=dependency_requests, **inputs
    )


def selector(source_inputs, *, last=False):
    report, raw, inputs, first, final = source_inputs
    return contexts.source_selector_v2(
        report, raw, **(final if last else first), **inputs
    )


def validation(value, source_inputs, dependency_requests=None, expected_selector=None):
    report, raw, inputs, _, _ = source_inputs
    return contexts.validate_context_packet_v2(
        value,
        report,
        raw,
        expected_selector=expected_selector or selector(source_inputs),
        dependency_requests=dependency_requests,
        **inputs,
    )


def repair_id(value):
    value["packet_id"] = (
        "legal-official-markup-context-packet:sha256:"
        + contexts.digest({k: v for k, v in value.items() if k != "packet_id"})
    )


def test_default_six_kind_packet_is_compact_open_and_source_bound(source_inputs):
    value = packet(source_inputs)
    assert value["schema"] == contexts.CONTEXT_PACKET_SCHEMA
    assert len(value["dependency_slots"]) == 6
    assert [s["kind"] for s in value["dependency_slots"]] == [
        "definition",
        "authority",
        "antecedent",
        "shared_qualifier",
        "temporal_origin",
        "referenced_provision",
    ]
    assert len({s["slot_id"] for s in value["dependency_slots"]}) == 6
    assert all(
        s["slot_id"].startswith("legal-official-markup-context-slot:sha256:")
        and s["status"] == "open_missing"
        and s["open"]
        and s["attachments"] == []
        and s["semantic_attachment_verified"] is False
        for s in value["dependency_slots"]
    )
    assert (
        not {"source_document", "document", "document_view_report", "normalized_view"}
        & value.keys()
    )
    assert all(v is False for v in value["authority"].values())
    assert all(
        value[k] is False
        for k in (
            "dependency_inventory_exhaustive",
            "context_closure_verified",
            "source_semantics_verified",
            "independently_reviewed",
            "training_qualified",
            "proof_authority",
            "semantic_attachments_inferred",
            "raw_html_coordinate_mapping_verified",
        )
    )
    binding = value["source_view_binding"]
    assert binding["view_report_sha256"] == source_inputs[2]["expected_report_sha256"]
    assert (
        binding["descriptor_sha256"] == source_inputs[2]["expected_descriptor_sha256"]
    )
    assert binding["raw_sha256"] == hashlib.sha256(source_inputs[1]).hexdigest()
    assert (
        binding["normalized_view_id"] == source_inputs[0]["normalized_view"]["view_id"]
    )
    result = validation(value, source_inputs)
    assert result["source_geometry_verified"] and result["open_dependency_slots"] == 6
    assert not any(
        result[k]
        for k in (
            "context_closure_verified",
            "semantic_attachments_verified",
            "source_semantics_verified",
            "training_qualified",
            "proof_authority",
        )
    )


@pytest.mark.parametrize("entry", ["selector", "build", "validate"])
def test_every_public_entry_replays_exact_v2_view_once(source_inputs, entry):
    value = packet(source_inputs)
    target = selector(source_inputs)
    report, raw, inputs, first, _ = source_inputs
    with patch.object(
        views,
        "validate_official_document_view",
        wraps=views.validate_official_document_view,
    ) as replay:
        if entry == "selector":
            contexts.source_selector_v2(report, raw, **first, **inputs)
        elif entry == "build":
            contexts.build_context_packet_v2(report, raw, **first, **inputs)
        else:
            contexts.validate_context_packet_v2(
                value, report, raw, expected_selector=target, **inputs
            )
        assert replay.call_count == 1


def test_repeated_unicode_text_has_distinct_occurrence_and_slot_identity(source_inputs):
    one, two = selector(source_inputs), selector(source_inputs, last=True)
    assert one["text"] == two["text"] == "Café Ω"
    assert one["text_sha256"] == two["text_sha256"]
    assert one["occurrence_id"] != two["occurrence_id"]
    text = source_inputs[0]["document"]["document_text"]
    for selection in (one, two):
        assert (
            text.encode()[
                selection["utf8_byte_start"] : selection["utf8_byte_end"]
            ].decode()
            == "Café Ω"
        )
        assert (
            selection["utf8_byte_end"] - selection["utf8_byte_start"]
            > selection["char_end"] - selection["char_start"]
        )
    report, raw, inputs, _, final = source_inputs
    later = contexts.build_context_packet_v2(report, raw, **final, **inputs)
    assert {s["slot_id"] for s in later["dependency_slots"]}.isdisjoint(
        s["slot_id"] for s in packet(source_inputs)["dependency_slots"]
    )
    with pytest.raises(ValueError, match="differs"):
        validation(later, source_inputs, expected_selector=one)


def test_cross_block_selection_preserves_literal_LF_without_context_attachment(
    source_inputs,
):
    report, raw, inputs, first, final = source_inputs
    value = contexts.build_context_packet_v2(
        report,
        raw,
        char_start=first["char_start"],
        char_end=final["char_end"],
        **inputs,
    )
    assert value["selection"]["text"] == "Café Ω.\n(b) Café Ω"
    assert all(s["attachments"] == [] and s["open"] for s in value["dependency_slots"])


def test_available_content_locators_stale_and_unavailable_all_remain_open_and_detached(
    source_inputs,
):
    incoming = requests()
    incoming[0].update(
        availability="available", candidate_selector=selector(source_inputs, last=True)
    )
    incoming[1].update(
        availability="unavailable", locator="https://example.invalid/authority"
    )
    incoming[2].update(expected_view_id="legal-official-markup-view:sha256:" + "0" * 64)
    incoming[3].update(locator="authored external qualifier locator")
    incoming[5].update(availability="available")
    original = deepcopy(incoming)
    value = packet(source_inputs, incoming)
    assert [s["status"] for s in value["dependency_slots"]] == [
        "open_content_available",
        "open_unavailable",
        "open_stale",
        "open_locator_only",
        "open_missing",
        "open_missing",
    ]
    assert all(
        s["open"] and not s["attachments"] and not s["semantic_attachment_verified"]
        for s in value["dependency_slots"]
    )
    incoming[0]["candidate_selector"]["text"] = "changed caller object"
    assert value["dependency_slots"][0]["candidate_selector"]["text"] == "Café Ω"
    assert validation(value, source_inputs, original)["open_dependency_slots"] == 6


@pytest.mark.parametrize(
    "damage", ["text", "utf8", "occurrence", "legacy_schema", "document", "stale"]
)
def test_available_content_requires_exact_same_checked_v2_view_selector(
    source_inputs, damage
):
    incoming = requests()
    candidate = selector(source_inputs, last=True)
    incoming[0].update(availability="available", candidate_selector=candidate)
    if damage == "text":
        candidate["text"] = "Café"
    elif damage == "utf8":
        candidate["utf8_byte_start"] = candidate["char_start"]
    elif damage == "occurrence":
        candidate["occurrence_id"] = (
            "legal-official-markup-occurrence:sha256:" + "0" * 64
        )
    elif damage == "legacy_schema":
        candidate["schema"] = "legal-statutory-view-occurrence-selector/v2"
    elif damage == "document":
        candidate["document_id"] += "different"
    else:
        incoming[0]["expected_view_id"] = (
            "legal-official-markup-view:sha256:" + "0" * 64
        )
    with pytest.raises(ValueError):
        packet(source_inputs, incoming)


@pytest.mark.parametrize(
    "damage",
    [
        "omission",
        "duplicate",
        "unknown_field",
        "availability",
        "locator",
        "legacy_view_id",
    ],
)
def test_fixed_closed_kind_population_rejects_incomplete_or_incompatible_requests(
    source_inputs, damage
):
    incoming = requests()
    if damage == "omission":
        incoming.pop()
    elif damage == "duplicate":
        incoming[-1]["kind"] = incoming[0]["kind"]
    elif damage == "unknown_field":
        incoming[0]["attachments"] = []
    elif damage == "availability":
        incoming[0]["availability"] = "resolved"
    elif damage == "locator":
        incoming[0]["locator"] = "x" * 4097
    else:
        incoming[0]["expected_view_id"] = "legal-normalized-view:sha256:" + "0" * 64
    with pytest.raises(ValueError):
        packet(source_inputs, incoming)


@pytest.mark.parametrize(
    "damage", ["selection", "drop_kind", "close", "attach", "binding", "authority"]
)
def test_repaired_packet_identity_cannot_replace_external_selection_or_resolve_context(
    source_inputs, damage
):
    value = packet(source_inputs)
    if damage == "selection":
        value["selection"] = selector(source_inputs, last=True)
    elif damage == "drop_kind":
        value["dependency_slots"].pop()
    elif damage == "close":
        value["dependency_slots"][0]["open"] = False
    elif damage == "attach":
        value["dependency_slots"][0]["attachments"] = [selector(source_inputs)]
    elif damage == "binding":
        value["source_view_binding"]["raw_sha256"] = "0" * 64
    else:
        value["authority"]["source_semantics_verified"] = True
    repair_id(value)
    with pytest.raises(ValueError, match="differs"):
        validation(value, source_inputs)


@pytest.mark.parametrize(
    "key",
    [
        "expected_raw_sha256",
        "expected_report_sha256",
        "expected_descriptor_sha256",
        "expected_raw_bytes",
    ],
)
def test_external_original_source_commitments_are_checked(source_inputs, key):
    report, raw, inputs, first, _ = source_inputs
    changed = dict(inputs, **{key: 1 if key == "expected_raw_bytes" else "0" * 64})
    with pytest.raises(ValueError):
        contexts.build_context_packet_v2(report, raw, **first, **changed)


def test_complete_packet_bound_refuses_before_view_replay_without_truncation(
    source_inputs,
):
    value = packet(source_inputs)
    value["overflow"] = "x" * contexts.MAX_CONTEXT_PACKET_BYTES
    target = selector(source_inputs)
    with patch.object(
        views,
        "validate_official_document_view",
        side_effect=AssertionError("replay reached"),
    ):
        with pytest.raises(ValueError, match="bound"):
            validation(value, source_inputs, expected_selector=target)
    incoming = requests()
    incoming[0]["locator"] = "x" * contexts.MAX_CONTEXT_PACKET_BYTES
    with patch.object(
        views,
        "validate_official_document_view",
        side_effect=AssertionError("replay reached"),
    ):
        with pytest.raises(ValueError, match="bound"):
            packet(source_inputs, incoming)


@pytest.mark.parametrize("owner", ["context", "helper"])
def test_since_import_owner_or_shared_helper_pin_drift_is_refused(source_inputs, owner):
    if owner == "context":
        changed = dict(contexts.producer_pins(), changed="0" * 64)
        with patch.object(contexts, "producer_pins", return_value=changed):
            with pytest.raises(ValueError, match="since import"):
                packet(source_inputs)
    else:
        with patch.object(obligations, "_IMPORTED_SOURCE_SHA256", "0" * 64):
            with pytest.raises(ValueError, match="since import"):
                packet(source_inputs)


def test_import_is_inert_without_native_or_model_modules(tmp_path):
    code = """
import sys
from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2
assert 'ipfs_datasets_py.logic.autoformal.legal_family_routes' not in sys.modules
assert 'ipfs_datasets_py.logic.TDFOL.tdfol_core' not in sys.modules
assert not any(m in sys.modules for m in ('torch', 'transformers', 'tensorflow'))
"""
    environment = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).resolve().parents[4]),
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
