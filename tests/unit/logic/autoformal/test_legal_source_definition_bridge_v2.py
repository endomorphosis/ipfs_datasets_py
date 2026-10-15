"""Authored V2 declarations preserve meaning and source custody without legal gold."""

import hashlib
import itertools
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import (
    legal_source_definition_bridge_v2 as bridge,
)
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler


def authored_request(
    family="fol",
    *,
    mode="single",
    edition=2024,
    cue="means",
    scope_literal="In this title:",
):
    if mode in {"repeated", "gap"}:
        middle = (
            '<p class="statutory-body-1em">Unselected gap.</p>' if mode == "gap" else ""
        )
        definition = (
            f'<p class="statutory-body-1em">(1) The term "café filer" {cue} registered or</p>'
            + middle
            + '<p class="statutory-body-2em">(A) registered.</p>'
        )
    else:
        definition = (
            f'<p class="statutory-body-1em">(1) The term "café filer" {cue} '
            "registered and either active or not exempt.</p>"
        )
    raw = (
        '<html><head><meta charset="utf-8"><title>Fictional source</title></head><body>'
        "<span>Café metadata</span><!-- field-start:head -->"
        '<h3 class="section-head">§1. Authored definition</h3><!-- field-end:head -->'
        f'<!-- field-start:statute --><p class="statutory-body">(a) {scope_literal}</p>'
        + definition
        + '<p class="statutory-body-block-1em">Such term includes a condition.</p>'
        '<p class="statutory-body">(b) Later authored body.</p>'
        "<!-- field-end:statute --><!-- field-start:notes -->"
        '<!-- field-start:miscellaneous-note --><h4 class="note-head">Editorial Notes</h4>'
        '<!-- field-end:miscellaneous-note --><p class="note-body">Authored control.</p>'
        "<!-- field-end:notes --></body></html>"
    ).encode()
    url = (
        f"https://www.govinfo.gov/content/pkg/USCODE-{edition}-title10/html/"
        f"USCODE-{edition}-title10-chap1-sec1.htm"
    )
    descriptor = {
        "schema": custody.DESCRIPTOR_SCHEMA,
        "legal_id": "usc:us:10:1",
        "edition": edition,
        "package_id": f"USCODE-{edition}-title10",
        "granule_id": f"USCODE-{edition}-title10-chap1-sec1",
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
    source_inputs = {
        "descriptor": descriptor,
        "expected_descriptor_sha256": custody.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256": descriptor["raw_sha256"],
        "expected_raw_bytes": len(raw),
    }
    sampling = sampler.prepare_source_sampling(raw, **source_inputs)
    text = sampling["document_view_report"]["document"]["document_text"]
    records = {r["record_cid"]: r for r in sampling["records"]}
    units = [r for r in records.values() if r["schema"] == sampler.UNIT_SCHEMA]

    def unit_text(unit):
        return records[unit["source_occurrence_ref"]["record_cid"]]["span_text"]

    def full_ref(record):
        return {
            "record_cid": record["record_cid"],
            "schema": record["schema"],
            "sha256": hashlib.sha256(
                json.dumps(
                    record,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest(),
        }

    def span(literal, *, last=False):
        at = text.rindex(literal) if last else text.index(literal)
        return {"char_start": at, "char_end": at + len(literal), "text": literal}

    scope = next(u for u in units if unit_text(u) == f"(a) {scope_literal}")
    head = next(
        u for u in units if unit_text(u).startswith('(1) The term "café filer"')
    )
    contributors = [head]
    if mode in {"repeated", "gap"}:
        contributors.append(next(u for u in units if unit_text(u) == "(A) registered."))
        body = {
            "op": "any",
            "operands": [
                {"op": "atom", "span": span("registered")},
                {"op": "atom", "span": span("registered", last=True)},
            ],
        }
    else:
        body = {
            "op": "all",
            "operands": [
                {"op": "atom", "span": span("registered")},
                {
                    "op": "any",
                    "operands": [
                        {"op": "atom", "span": span("active")},
                        {
                            "op": "not",
                            "operand": {"op": "atom", "span": span("exempt")},
                        },
                    ],
                },
            ],
        }
    request = {
        "schema": bridge.REQUEST_SCHEMA,
        "profile": bridge.PROFILE,
        "family": family,
        "declaration": {
            "declaration_id": "authored-widget-definition",
            "interpretation_status": "unreviewed_caller_declaration",
            "source_version_ref": head["source_version_ref"],
            "normalized_view_id": head["normalized_view_id"],
            "contributor_unit_refs": [full_ref(u) for u in contributors],
            "scope_unit_ref": full_ref(scope),
            "scope_span": span(scope_literal),
            "head": span("café filer"),
            "definition_cue": span(cue),
            "body": body,
            "applicability": {
                "scope_kind": (
                    "section" if "section" in scope_literal.lower() else "title"
                ),
                "scope_id": "authored-title10-scope",
                "jurisdiction_id": "us",
                "instrument_id": "usc:us:10",
                "legal_as_of_civil_date": None,
                "source_edition": edition,
                "source_release_id": records[head["source_version_ref"]["record_cid"]][
                    "release_id"
                ],
            },
        },
    }
    return request, {
        "sampling_report": sampling,
        "expected_sampling_report_sha256": sampler.source_sampling_report_sha256(
            sampling
        ),
        "raw_html": raw,
        **source_inputs,
    }


def evaluate(ast, values, environment=None):
    environment = {} if environment is None else environment
    kind = ast["node_type"]
    if kind == "Predicate":
        return values[ast["name"]][environment[ast["arguments"][0]["name"]]]
    if kind == "QuantifiedFormula":
        outcomes = [
            evaluate(ast["formula"], values, environment | {ast["variable"]["name"]: i})
            for i in (0, 1)
        ]
        return all(outcomes) if ast["quantifier"]["value"] == "∀" else any(outcomes)
    if kind == "UnaryFormula":
        return not evaluate(ast["formula"], values, environment)
    left = evaluate(ast["left"], values, environment)
    right = evaluate(ast["right"], values, environment)
    return {
        "∧": left and right,
        "∨": left or right,
        "↔": left == right,
        "→": not left or right,
    }[ast["operator"]["value"]]


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_unreviewed_v2_definition_only_preserves_native_structure_without_norm(family):
    request, inputs = authored_request(family)
    report = bridge.prepare_definition_v2(request, **inputs)
    ast = report["native_ast"]
    assert ast["quantifier"]["value"] == "∀"
    assert ast["formula"]["operator"]["value"] == "↔"
    assert ast["formula"]["right"]["operator"]["value"] == "∧"
    assert ast["formula"]["right"]["right"]["operator"]["value"] == "∨"
    assert report["native"]["exact_native_ast_roundtrip"]
    assert "∀ v0 : Entity" in report["lean_body"]
    assert all(value is False for value in report["authority"].values())
    assert report["definition_lexical_coverage_complete"] is False
    assert (
        report["contributor_unit_refs"]
        == request["declaration"]["contributor_unit_refs"]
    )
    assert not {"norm", "norm_ast", "norm_record", "modality"} & report.keys()
    assert bridge.validate_definition_v2(report, request, **inputs)


def test_two_entity_truth_oracle_detects_weakening_and_keeps_explicit_negation():
    request, inputs = authored_request()
    report = bridge.prepare_definition_v2(request, **inputs)
    names = {r["source_literal"]: r["symbol"] for r in report["symbols"]}
    witnesses = {"existential": 0, "one_way": 0, "or_instead_of_and": 0}
    for bits in itertools.product((False, True), repeat=8):
        valuations = {
            name: bits[2 * i : 2 * i + 2]
            for i, name in enumerate(("café filer", "registered", "active", "exempt"))
        }
        values = {names[k]: v for k, v in valuations.items()}
        expected = all(
            valuations["café filer"][i]
            == (
                valuations["registered"][i]
                and (valuations["active"][i] or not valuations["exempt"][i])
            )
            for i in (0, 1)
        )
        assert evaluate(report["native_ast"], values) == expected
        for name in witnesses:
            mutant = deepcopy(report["native_ast"])
            if name == "existential":
                mutant["quantifier"]["value"] = "∃"
            elif name == "one_way":
                mutant["formula"]["operator"]["value"] = "→"
            else:
                mutant["formula"]["right"]["operator"]["value"] = "∨"
            witnesses[name] += evaluate(mutant, values) != expected
    assert all(count > 0 for count in witnesses.values())


def test_repeated_unicode_body_keeps_physical_origins_roles_and_derived_contexts():
    request, inputs = authored_request(mode="repeated")
    report = bridge.prepare_definition_v2(request, **inputs)
    bindings = {b["role"]: b for b in report["source_bindings"]}
    first, second = [bindings[f"definition_body/{i:04d}"] for i in (0, 1)]
    assert first["source_occurrence_cid"] != second["source_occurrence_cid"]
    assert first["symbol"] == second["symbol"]
    occurrences = {r["record_cid"]: r for r in report["source_occurrences"]}
    contexts = {r["record_cid"]: r for r in report["context_declarations"]}
    original_cids = {r["record_cid"] for r in inputs["sampling_report"]["records"]}
    head = occurrences[bindings["definition_head"]["source_occurrence_cid"]]
    assert head["record_cid"] not in original_cids
    assert head["span_text"] == "café filer" and head["end_utf8"] - head[
        "start_utf8"
    ] > len("café filer")
    for binding in report["source_bindings"]:
        occurrence = occurrences[binding["source_occurrence_cid"]]
        context = contexts[binding["context_cid"]]
        assert context["source_occurrence_cid"] == occurrence["record_cid"]
        assert context["availability"] == "required_unavailable"
        assert len(context["missing_requirements"]) == 6
    assert len(report["contributor_unit_refs"]) == 2
    assert bridge.validate_definition_v2(report, request, **inputs)


def crossing_body(request, inputs):
    declaration = request["declaration"]
    left = declaration["body"]["operands"][0]["span"]["char_start"]
    right = declaration["body"]["operands"][1]["span"]["char_end"]
    text = inputs["sampling_report"]["document_view_report"]["document"][
        "document_text"
    ]
    declaration["body"] = {
        "op": "atom",
        "span": {"char_start": left, "char_end": right, "text": text[left:right]},
    }


def test_cross_block_atom_retains_exact_LF_and_all_contributor_intersections():
    request, inputs = authored_request(mode="repeated")
    crossing_body(request, inputs)
    report = bridge.prepare_definition_v2(request, **inputs)
    binding = next(
        b for b in report["source_bindings"] if b["role"] == "definition_body/0000"
    )
    occurrence = next(
        r
        for r in report["source_occurrences"]
        if r["record_cid"] == binding["source_occurrence_cid"]
    )
    assert "\n" in occurrence["span_text"]
    assert len(binding["block_indices"]) == 2
    assert occurrence["span_text"] == request["declaration"]["body"]["span"]["text"]


def test_same_bytes_other_edition_or_applicability_do_not_reuse_scoped_symbols():
    first_request, first_inputs = authored_request(edition=2024)
    second_request, second_inputs = authored_request(edition=2025)
    assert first_inputs["raw_html"] == second_inputs["raw_html"]
    first = bridge.prepare_definition_v2(first_request, **first_inputs)
    second = bridge.prepare_definition_v2(second_request, **second_inputs)
    assert first["scope_key"] != second["scope_key"]
    assert not {r["symbol"] for r in first["symbols"]} & {
        r["symbol"] for r in second["symbols"]
    }
    third_request = deepcopy(first_request)
    third_request["declaration"]["applicability"]["scope_id"] = "other-explicit-scope"
    third = bridge.prepare_definition_v2(third_request, **first_inputs)
    assert third["scope_key"] != first["scope_key"]


@pytest.mark.parametrize(
    "damage", ["forall", "iff", "scope", "binding", "lean", "authority"]
)
def test_repaired_report_digest_cannot_authorize_semantic_or_custody_mutants(damage):
    request, inputs = authored_request()
    report = deepcopy(bridge.prepare_definition_v2(request, **inputs))
    if damage == "forall":
        report["native_ast"]["quantifier"]["value"] = "∃"
    elif damage == "iff":
        report["native_ast"]["formula"]["operator"]["value"] = "→"
    elif damage == "scope":
        report["scope_key"] = "0" * 64
    elif damage == "binding":
        report["source_bindings"][0]["source_occurrence_cid"] = report[
            "source_bindings"
        ][-1]["source_occurrence_cid"]
    elif damage == "lean":
        report["lean_body"] = "def formula_0 : Prop := True"
    else:
        report["authority"]["source_semantics_verified"] = True
    report["report_sha256"] = bridge.digest(
        {k: v for k, v in report.items() if k != "report_sha256"}
    )
    with pytest.raises(ValueError):
        bridge.validate_definition_v2(report, request, **inputs)


@pytest.mark.parametrize(
    "damage", ["descriptor_hash", "raw_hash", "raw_length", "sampling_hash"]
)
def test_independently_supplied_source_commitments_are_required(damage):
    request, inputs = authored_request()
    key = {
        "descriptor_hash": "expected_descriptor_sha256",
        "raw_hash": "expected_raw_sha256",
        "raw_length": "expected_raw_bytes",
        "sampling_hash": "expected_sampling_report_sha256",
    }[damage]
    inputs[key] = 0 if damage == "raw_length" else "0" * 64
    with pytest.raises(ValueError):
        bridge.prepare_definition_v2(request, **inputs)


@pytest.mark.parametrize(
    "damage",
    [
        "unit_ref",
        "omit",
        "reorder",
        "gap",
        "includes",
        "operator",
        "sort",
        "scope_kind",
        "self",
        "civil_date",
    ],
)
def test_unsupported_or_inconsistent_declarations_refuse_without_rewriting(damage):
    request, inputs = authored_request(
        mode="gap" if damage == "gap" else "repeated",
        cue="includes" if damage == "includes" else "means",
    )
    declaration = request["declaration"]
    if damage == "unit_ref":
        declaration["contributor_unit_refs"][0]["sha256"] = "0" * 64
    elif damage == "omit":
        declaration["contributor_unit_refs"].pop()
    elif damage == "reorder":
        declaration["contributor_unit_refs"].reverse()
    elif damage == "gap":
        crossing_body(request, inputs)
    elif damage == "operator":
        declaration["body"] = {"op": "O", "operand": declaration["body"]}
    elif damage == "sort":
        declaration["sort"] = "LegalPerson"
    elif damage == "scope_kind":
        declaration["applicability"]["scope_kind"] = "section"
    elif damage == "self":
        declaration["body"] = {"op": "atom", "span": deepcopy(declaration["head"])}
    elif damage == "civil_date":
        declaration["applicability"]["legal_as_of_civil_date"] = "2025-02-30"
    with pytest.raises(ValueError):
        bridge.prepare_definition_v2(request, **inputs)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_occurrences": 1},
        {"max_bindings": 1},
        {"max_report_bytes": 1},
        {"max_contributors": 1},
    ],
)
def test_lower_limits_refuse_the_whole_candidate_without_truncation(limits):
    request, inputs = authored_request(mode="repeated")
    with pytest.raises(ValueError):
        bridge.prepare_definition_v2(request, **inputs, limits=limits)


def test_oversize_request_refuses_before_source_replay():
    request, inputs = authored_request()
    request["declaration"]["declaration_id"] = "x" * (1024 * 1024 + 1)
    with patch.object(
        sampler,
        "validate_source_sampling",
        side_effect=AssertionError("source replay reached"),
    ):
        with pytest.raises(ValueError):
            bridge.prepare_definition_v2(request, **inputs)


def test_public_import_remains_inert_without_models_or_native_compilation(tmp_path):
    code = """
import sys
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2
assert not any(name in sys.modules for name in ('torch', 'transformers', 'tensorflow'))
assert 'ipfs_datasets_py.logic.autoformal.legal_family_routes' not in sys.modules
assert 'ipfs_datasets_py.logic.TDFOL.tdfol_core' not in sys.modules
"""
    root = Path(__file__).resolve().parents[4]
    environment = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scope_literal", ["in this title", "In this section:"])
def test_exact_declared_title_and_section_scope_literals_preserve_applicability(
    scope_literal,
):
    request, inputs = authored_request(scope_literal=scope_literal)
    report = bridge.prepare_definition_v2(request, **inputs)
    assert report["declaration"]["scope_span"]["text"] == scope_literal
    assert report["applicability"] == request["declaration"]["applicability"]
    assert all(v is False for v in report["authority"].values())


def test_authored_continuation_refused_by_legacy_document_maps_without_relabeling_in_v2():
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context

    request, inputs = authored_request()
    with pytest.raises(ValueError):
        legal_statutory_context.extract_document(
            inputs["raw_html"],
            url=inputs["descriptor"]["url"],
            edition=2024,
            legal_id="usc:us:10:1",
        )
    report = bridge.prepare_definition_v2(request, **inputs)
    assert (
        report["source_version"]["extracted_view"]["extraction_profile"]
        == "legal-official-markup-document/v2"
    )
    assert (
        report["source_version"]["record_cid"]
        == request["declaration"]["source_version_ref"]["record_cid"]
    )
