"""An unreviewed V2 definition must not acquire a norm or review authority."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from unittest.mock import patch

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import (
    legal_source_definition_bridge_v2 as compiler,
)
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal.corpus_contracts import (
    CorpusContractError,
    seal_record,
)
from ipfs_datasets_py.logic.autoformal.corpus_graph import validate_graph_snapshot


def wire(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inputs(family="fol"):
    raw = (
        '<html><head><meta charset="utf-8"></head><body>'
        '<!-- field-start:head --><h3 class="section-head">§1. Authored example</h3>'
        "<!-- field-end:head --><!-- field-start:statute -->"
        '<p class="statutory-body">(a) In this title:</p>'
        '<p class="statutory-body-1em">(1) The term “café member” means registered and active.</p>'
        '<p class="statutory-body-block-1em">Unselected continuation remains available.</p>'
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
        "raw_sha256": sha(raw),
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
    source = dict(
        descriptor=descriptor,
        expected_descriptor_sha256=custody.acquisition_descriptor_sha256(descriptor),
        expected_raw_sha256=sha(raw),
        expected_raw_bytes=len(raw),
    )
    sampling = sampler.prepare_source_sampling(raw, **source)
    text = sampling["document_view_report"]["document"]["document_text"]
    units = [row for row in sampling["records"] if row["schema"] == sampler.UNIT_SCHEMA]
    by_cid = {row["record_cid"]: row for row in sampling["records"]}

    def unit_with(literal):
        return next(
            row
            for row in units
            if literal
            in by_cid[row["source_occurrence_ref"]["record_cid"]]["span_text"]
        )

    def reference(unit):
        return next(
            row
            for row in sampling["unit_refs"]
            if row["record_cid"] == unit["record_cid"]
        )

    def span(literal):
        start = text.index(literal)
        return {"char_start": start, "char_end": start + len(literal), "text": literal}

    unit = unit_with("café member")
    request = {
        "schema": compiler.REQUEST_SCHEMA,
        "profile": compiler.PROFILE,
        "family": family,
        "declaration": {
            "declaration_id": "authored-cafe-definition",
            "interpretation_status": "unreviewed_caller_declaration",
            "source_version_ref": unit["source_version_ref"],
            "normalized_view_id": unit["normalized_view_id"],
            "contributor_unit_refs": [reference(unit)],
            "scope_unit_ref": reference(unit_with("In this title:")),
            "scope_span": span("In this title:"),
            "head": span("café member"),
            "definition_cue": span("means"),
            "body": {
                "op": "all",
                "operands": [
                    {"op": "atom", "span": span("registered")},
                    {"op": "atom", "span": span("active")},
                ],
            },
            "applicability": {
                "scope_kind": "title",
                "scope_id": "authored-title-scope",
                "jurisdiction_id": "authored-jurisdiction",
                "instrument_id": "authored-instrument",
                "legal_as_of_civil_date": None,
                "source_edition": 2024,
                "source_release_id": "govinfo-markup-v2-edition:2024",
            },
        },
    }
    trusted = dict(
        sampling_report=sampling,
        expected_sampling_report_sha256=sampler.source_sampling_report_sha256(sampling),
        raw_html=raw,
        **source,
    )
    report = compiler.prepare_definition_v2(request, **trusted)
    request_raw, report_raw = wire(request), wire(report)
    return report_raw, dict(
        expected_report_sha256=sha(report_raw),
        request_raw=request_raw,
        expected_request_sha256=sha(request_raw),
        **trusted,
    )


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_definition_only_graph_has_exact_endpoints_and_no_invented_norm(family):
    report_raw, args = inputs(family)
    candidate = adapter.adapt_definition_only_bytes_v2(report_raw, **args)
    assert (
        adapter.validate_definition_only_candidate_v2(candidate, report_raw, **args)
        == candidate
    )
    graph = validate_graph_snapshot(candidate["graph"])
    by_cid = {node["record_cid"]: node for node in graph["nodes"]}
    defines = [edge for edge in graph["edges"] if edge["relation"] == "DEFINES"]
    assert len(defines) == 1
    assert by_cid[defines[0]["src_cid"]]["node_type"] == "definition_assertion"
    assert by_cid[defines[0]["dst_cid"]]["node_type"] == "term_sense"
    assert not {"entity", "norm_assertion"} & {
        node["node_type"] for node in graph["nodes"]
    }
    assert "USES_DEFINITION" not in {edge["relation"] for edge in graph["edges"]}
    assert "norm_record" not in candidate
    assert (
        candidate["definition_record"]["native_ast"]
        == json.loads(report_raw)["native_ast"]
    )
    assert candidate["term_record"]["source_literal"] == "café member"
    assert all(candidate[flag] is False for flag in adapter.FALSE_FLAGS)
    assert not candidate["definition_record"]["definition_lexical_coverage_complete"]


def test_full_contributors_and_new_subspan_contexts_remain_separate_from_sampler():
    report_raw, args = inputs()
    candidate = adapter.adapt_definition_only_bytes_v2(report_raw, **args)
    original_occurrences = {
        row["record_cid"]
        for row in args["sampling_report"]["records"]
        if row["schema"] == "legal-corpus-source-occurrence/v1"
    }
    occurrences = {row["record_cid"]: row for row in candidate["source_occurrences"]}
    contexts = {
        row["source_occurrence_cid"]: row for row in candidate["context_declarations"]
    }
    assert set(contexts) == set(occurrences)
    assert all(len(row["missing_requirements"]) == 6 for row in contexts.values())
    head = next(
        row for row in candidate["source_bindings"] if row["role"] == "definition_head"
    )
    assert head["source_occurrence_cid"] not in original_occurrences
    origin = occurrences[head["source_occurrence_cid"]]
    assert origin["span_text"] == "café member"
    assert origin["end_utf8"] - origin["start_utf8"] == len("café member".encode())
    assert contexts[head["source_occurrence_cid"]]["record_cid"] == head["context_cid"]
    assert any(
        row["role"] == "definition_contributor/0000"
        and row["source_occurrence_cid"] in original_occurrences
        for row in candidate["source_bindings"]
    )


@pytest.mark.parametrize(
    "mutation",
    ["AST", "scope", "context", "role", "authority", "graph_endpoint", "report_pin"],
)
def test_resealed_candidate_cannot_replace_source_meaning_context_or_graph(mutation):
    report_raw, args = inputs()
    candidate = deepcopy(adapter.adapt_definition_only_bytes_v2(report_raw, **args))
    if mutation == "AST":
        candidate["definition_record"]["native_ast"]["formula"]["operator"][
            "value"
        ] = "→"
        candidate["definition_record"] = seal_record(
            {
                k: v
                for k, v in candidate["definition_record"].items()
                if k not in {"record_cid", "cid_scope"}
            }
        )
    elif mutation == "scope":
        candidate["scope_record"]["declared_applicability"][
            "instrument_id"
        ] = "another-instrument"
    elif mutation == "context":
        candidate["context_declarations"] = candidate["context_declarations"][:-1]
    elif mutation == "role":
        candidate["source_bindings"][0]["role"] = "definition_head"
    elif mutation == "authority":
        candidate["admitted"] = True
    elif mutation == "graph_endpoint":
        edge = next(
            row for row in candidate["graph"]["edges"] if row["relation"] == "DEFINES"
        )
        edge["dst_cid"] = candidate["term_record"]["record_cid"]
    else:
        candidate["report_record"]["report_sha256"] = "0" * 64
    candidate = seal_record(
        {k: v for k, v in candidate.items() if k not in {"record_cid", "cid_scope"}}
    )
    with pytest.raises(CorpusContractError):
        adapter.validate_definition_only_candidate_v2(candidate, report_raw, **args)


def test_bad_transport_hash_and_oversize_body_fail_before_native_owner_import():
    report_raw, args = inputs()
    with patch.dict(
        sys.modules,
        {"ipfs_datasets_py.logic.autoformal.legal_source_definition_bridge_v2": None},
    ):
        with pytest.raises(CorpusContractError):
            adapter.adapt_definition_only_bytes_v2(
                report_raw, **(args | {"expected_report_sha256": "0" * 64})
            )
        oversized = b" " * (1024 * 1024 + 1)
        with pytest.raises(CorpusContractError):
            adapter.adapt_definition_only_bytes_v2(
                oversized, **(args | {"expected_report_sha256": sha(oversized)})
            )


def test_public_import_does_not_import_native_definition_owners():
    code = """
import sys
from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2
for name in ('legal_source_definition_bridge_v2', 'legal_source_definition_bridge', 'legal_family_routes'):
    assert 'ipfs_datasets_py.logic.autoformal.' + name not in sys.modules, name
assert not any(name == 'torch' or name.startswith('torch.') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_changed_adapter_source_is_refused_before_cached_code_can_claim_new_pins(
    monkeypatch,
):
    report_raw, args = inputs()
    original = adapter.Path.read_bytes

    def changed(path):
        if path == adapter.Path(adapter.__file__).resolve():
            return b"changed adapter bytes"
        return original(path)

    monkeypatch.setattr(adapter.Path, "read_bytes", changed)
    with pytest.raises(CorpusContractError, match="changed since import"):
        adapter.adapt_definition_only_bytes_v2(report_raw, **args)
