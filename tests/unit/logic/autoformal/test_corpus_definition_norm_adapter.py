"""Authored definition/norm custody fixtures; no Lake, provider or training."""

import base64
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_norm_adapter as adapter
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_bridge as owner
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal.corpus_graph import validate_graph_snapshot
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode(
        "utf-8"
    )


def fixture_request(
    modality="O",
    family="deontic_fol",
    *,
    edition=2024,
    section="1",
    descendant=False,
    repeated=False,
    norm_suffix="",
):
    """Independently author the unchanged owner's explicit declaration contract."""
    cue = owner.CUES[modality]
    definition_text = '(1) The term "covered filer" means registered or licensed.'
    child = '<p class="statutory-body-2em">(i) registered or licensed.</p>' if descendant else ""
    raw = (
        f'<meta charset="utf-8"><h3 class="section-head">§{section}. Authored café fixture</h3>'
        '<p class="statutory-body">(a) Définitions — In this section:</p>'
        f'<p class="statutory-body-1em">{definition_text}</p>{child}'
        f'<p class="statutory-body">(b) Each covered filer {cue} register.{norm_suffix}</p>'
    ).encode()
    url = (
        f"https://www.govinfo.gov/content/pkg/USCODE-{edition}-title40/html/"
        f"USCODE-{edition}-title40-sec{section}.htm"
    )
    document = context.extract_document(
        raw, url=url, edition=edition, legal_id=f"usc:us:40:{section}"
    )
    text = document["document_text"]

    def span(literal, after=0):
        start = text.index(literal, after)
        return {"char_start": start, "char_end": start + len(literal), "text": literal}

    second_start = document["paragraphs"][2]["char_start"] if descendant else 0
    body = (
        [span("registered"), span("registered", second_start)]
        if repeated and descendant
        else [span("registered"), span("licensed", second_start)]
    )
    definition_request = {
        "document": document,
        "raw_html_base64": base64.b64encode(raw).decode("ascii"),
        "family": "fol",
        "declaration": {
            "declaration_id": "authored-cafe-definition",
            "profile": owner.definitions.PROFILE,
            "interpretation_status": "unreviewed_caller_declaration",
            "paragraph_index": 1,
            "scope_span": span("In this section:"),
            "definition_cue": span("means"),
            "head": span("covered filer"),
            "body": {"op": "any", "operands": [{"op": "atom", "span": item} for item in body]},
        },
    }
    definition = owner.definitions.prepare_definition(definition_request)
    norm_index = len(document["paragraphs"]) - 1
    norm_start = document["paragraphs"][norm_index]["char_start"]
    norm = {
        "norm_id": "authored-cafe-norm-" + modality,
        "profile": owner.PROFILE,
        "interpretation_status": "unreviewed_caller_declaration",
        **{
            key: document[key]
            for key in ("document_id", "document_text_sha256", "legal_id", "edition")
        },
        "paragraph_index": norm_index,
        "source_span": span(f"Each covered filer {cue} register.", norm_start),
        "quantifier_span": span("Each", norm_start),
        "category_span": span("covered filer", norm_start),
        "modality_span": span(cue, norm_start),
        "action_span": span("register", norm_start),
        "modality": modality,
        "variable": "x",
        "definition_head_symbol": definition["native_ast"]["formula"]["left"]["name"],
        "activation_scope": owner.ACTIVATION,
        "modal_context": None,
    }
    request = {
        "definition_request": definition_request,
        "norm_declaration": norm,
        "family": family,
        "source_provenance": {
            "kind": "authored_official_shape_fixture",
            "authenticity_verified": False,
            "independently_reviewed": False,
            "training_admitted": False,
        },
    }
    return request, raw


def case(modality="O", family="deontic_fol", **options):
    request, raw_html = fixture_request(modality, family, **options)
    return case_from_request(request, raw_html)


def case_from_request(request, raw_html):
    report = owner.prepare_definition_norm(request)
    report_raw, request_raw = wire(report), wire(request)
    arguments = {
        "expected_report_sha256": sha(report_raw),
        "request_raw": request_raw,
        "expected_request_sha256": sha(request_raw),
        "raw_html": raw_html,
        "expected_raw_sha256": sha(raw_html),
        "expected_extracted_sha256": sha(
            request["definition_request"]["document"]["document_text"].encode("utf-8")
        ),
    }
    return report_raw, report, request, arguments


def adapt_case(*args, **kwargs):
    raw, report, request, arguments = case(*args, **kwargs)
    return adapter.adapt_definition_norm_bytes(raw, **arguments), raw, report, request, arguments


def reseal(value):
    return contracts.seal_record(
        {key: item for key, item in value.items() if key not in {"record_cid", "cid_scope"}}
    )


def rebound_report(report):
    report["report_sha256"] = owner.digest(
        {key: item for key, item in report.items() if key != "report_sha256"}
    )
    return wire(report)


@pytest.mark.parametrize("modality", list("OPF"))
@pytest.mark.parametrize("family", owner.FAMILIES)
def test_six_native_profiles_preserve_exact_joint_ast_variable_and_definition_guard(
    modality, family
):
    record, raw, report, _, arguments = adapt_case(modality, family)
    assert record["report_record"]["report_json"].encode("utf-8") == raw
    assert record["request_record"]["request_json"].encode("utf-8") == arguments["request_raw"]
    assert record["ast_record"]["native_ast"] == report["native_ast"]
    assert (
        record["ast_record"]["bound_definition_native_ast"] == report["bound_definition_native_ast"]
    )
    assert record["ast_record"]["norm_native_ast"] == report["norm_native_ast"]
    assert record["definition_record"]["native_ast"] == report["bound_definition_native_ast"]
    assert record["norm_record"]["native_ast"] == report["norm_native_ast"]
    assert record["symbol_record"]["symbol_table"] == report["symbol_table"]
    assert (
        record["symbol_record"]["definition_symbol_rebinding"]
        == report["definition_symbol_rebinding"]
    )
    assert record["symbol_record"]["variable_binding"] == report["variable_binding"]
    joint = record["ast_record"]["native_ast"]
    assert joint["operator"]["value"] == "∧"
    assert joint["left"]["formula"]["operator"]["value"] == "↔"
    assert joint["left"]["quantifier"]["value"] == joint["right"]["quantifier"]["value"] == "∀"
    guard = joint["right"]["formula"]
    assert guard["operator"]["value"] == "→"
    assert guard["left"]["name"] == joint["left"]["formula"]["left"]["name"]
    assert guard["right"]["operator"]["value"] == modality
    assert guard["left"]["arguments"] == guard["right"]["formula"]["arguments"]
    assert guard["left"]["arguments"][0] == {"node_type": "Variable", "name": "x", "sort": None}
    assert record["ast_record"]["lean_body"] == report["lean_body"]
    assert "i.constant" not in record["ast_record"]["lean_body"]
    assert record["family"] == family and record["view"] == "candidate"
    assert record["declared_native_profile_encoded"] is True
    assert adapter.validate_definition_norm_candidate(record, raw, **arguments) == record


def test_graph_definition_and_use_links_bind_real_assertion_envelopes_without_guessed_roles():
    record, _, _, _, _ = adapt_case()
    graph = validate_graph_snapshot(record["graph"])
    by_cid = {node["record_cid"]: node for node in graph["nodes"]}
    defines = [edge for edge in graph["edges"] if edge["relation"] == "DEFINES"]
    uses = [edge for edge in graph["edges"] if edge["relation"] == "USES_DEFINITION"]
    assert len(defines) == len(uses) == 1
    assert by_cid[defines[0]["src_cid"]]["node_type"] == "definition_assertion"
    assert by_cid[defines[0]["dst_cid"]]["node_type"] == "term_sense"
    assert by_cid[uses[0]["src_cid"]]["node_type"] == "norm_assertion"
    assert uses[0]["dst_cid"] == defines[0]["src_cid"]
    for kind in ("definition_assertion", "norm_assertion"):
        node = next(node for node in graph["nodes"] if node["node_type"] == kind)
        assert node["source_occurrence_cids"] and node["interpretation_cids"]
        assert node["scope_cid"] == record["scope_record"]["record_cid"]
    assert not {edge["relation"] for edge in graph["edges"]} & {
        "HAS_ACTOR",
        "HAS_OBJECT",
        "HAS_CONDITION",
        "HAS_EXCEPTION",
        "HAS_TEMPORAL_CONSTRAINT",
    }


def test_exact_scope_definition_norm_and_descendant_paragraph_geometry_is_complete():
    record, _, _, request, arguments = adapt_case(descendant=True)
    document = request["definition_request"]["document"]
    by_cid = {item["record_cid"]: item for item in record["source_occurrences"]}
    bindings = {binding["role"]: binding for binding in record["source_bindings"]}
    assert set(bindings) >= {
        "definition_block",
        "definition_paragraph",
        "scope_literal",
        "definition_cue",
        "definition_head",
        "definition_body/0000",
        "definition_body/0001",
        "norm_paragraph",
        "norm_span",
        "norm_quantifier",
        "norm_category",
        "norm_modality",
        "norm_action",
    }
    assert {role for role in bindings if role.startswith("physical_paragraph/")} == {
        "physical_paragraph/0",
        "physical_paragraph/1",
        "physical_paragraph/2",
        "physical_paragraph/3",
    }
    assert bindings["definition_block"]["paragraph_indices"] == [1, 2]
    assert bindings["norm_paragraph"]["paragraph_indices"] == [3]
    assert bindings["scope_literal"]["paragraph_indices"] == [0]
    assert len(by_cid) == len(record["source_occurrences"])
    encoded = document["document_text"].encode("utf-8")
    for binding in bindings.values():
        occurrence = by_cid[binding["source_occurrence_cid"]]
        assert (
            document["document_text"][occurrence["start_char"] : occurrence["end_char"]]
            == occurrence["span_text"]
        )
        assert (
            encoded[occurrence["start_utf8"] : occurrence["end_utf8"]].decode("utf-8")
            == occurrence["span_text"]
        )
        assert occurrence["source_version_cid"] == record["source_version"]["record_cid"]
    assert (
        by_cid[bindings["norm_span"]["source_occurrence_cid"]]["start_utf8"]
        > by_cid[bindings["norm_span"]["source_occurrence_cid"]]["start_char"]
    )
    assert record["source_version"]["raw_artifact"]["sha256"] == arguments["expected_raw_sha256"]
    assert (
        record["source_version"]["extracted_view"]["normalization_profile"]
        == context.NORMALIZATION_PROFILE
    )


def test_repeated_body_literals_keep_distinct_occurrences_and_shared_rebound_symbol():
    record, _, report, _, _ = adapt_case(descendant=True, repeated=True)
    bindings = {binding["role"]: binding for binding in record["source_bindings"]}
    first, second = bindings["definition_body/0000"], bindings["definition_body/0001"]
    assert first["source_occurrence_cid"] != second["source_occurrence_cid"]
    assert first["symbol"] == second["symbol"]
    occurrences = {item["record_cid"]: item for item in record["source_occurrences"]}
    assert (
        occurrences[first["source_occurrence_cid"]]["span_text"]
        == occurrences[second["source_occurrence_cid"]]["span_text"]
        == "registered"
    )
    assert record["symbol_record"]["symbol_table"] == report["symbol_table"]


@pytest.mark.parametrize("change", [{"edition": 2025}, {"section": "2"}])
def test_composition_rebound_namespace_distinguishes_identical_bytes_other_edition_or_section(
    change,
):
    record, raw, report, _, arguments = adapt_case()
    other, _, other_report, _, other_arguments = adapt_case(**change)
    assert record["scope_record"]["record_cid"] != other["scope_record"]["record_cid"]
    assert record["source_version"]["record_cid"] != other["source_version"]["record_cid"]
    assert not set(report["definition_symbol_rebinding"].values()) & set(
        other_report["definition_symbol_rebinding"].values()
    )
    if "edition" in change:
        assert report["definition"]["scope_key"] == other_report["definition"]["scope_key"]
        assert (
            report["definition_symbol_rebinding"].keys()
            == other_report["definition_symbol_rebinding"].keys()
        )
    with pytest.raises(contracts.CorpusContractError):
        adapter.validate_definition_norm_candidate(record, raw, **other_arguments)
    assert adapter.validate_definition_norm_candidate(record, raw, **arguments) == record


def test_declared_encoding_never_grants_source_review_build_or_proof_authority():
    record, _, _, _, _ = adapt_case()
    for key in (
        "context_closure_verified",
        "source_semantics_verified",
        "source_authenticity_verified",
        "independently_reviewed",
        "admitted",
        "formalized",
        "proof_authority",
        "backend_executed",
        "lean_compilation_verified",
        "learned_translation",
    ):
        assert record[key] is False
    assert record["graph"]["admitted"] is record["graph"]["formalized"] is False
    assert record["issues"]


@pytest.mark.parametrize(
    "field",
    [
        "expected_report_sha256",
        "expected_request_sha256",
        "expected_raw_sha256",
        "expected_extracted_sha256",
    ],
)
def test_all_independent_byte_hashes_are_required_and_checked(field):
    raw, _, _, arguments = case()
    arguments[field] = "0" * 64
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_definition_norm_bytes(raw, **arguments)


@pytest.mark.parametrize(
    "mutation",
    [
        "constant",
        "drop_guard",
        "modal_guard",
        "one_way",
        "free_variable",
        "wrong_modality",
        "true_lean",
        "rebinding",
        "authority",
    ],
)
def test_hash_repaired_native_or_namespace_mutations_fail_authoritative_regeneration(mutation):
    _, report, _, arguments = case()
    norm = report["native_ast"]["right"]
    if mutation == "constant":
        norm["formula"]["right"]["formula"]["arguments"][0]["node_type"] = "Constant"
    elif mutation == "drop_guard":
        norm["formula"] = norm["formula"]["right"]
    elif mutation == "modal_guard":
        guard = norm["formula"]
        modal = deepcopy(guard["right"])
        modal["formula"] = {**guard, "right": guard["right"]["formula"]}
        norm["formula"] = modal
    elif mutation == "one_way":
        report["native_ast"]["left"]["formula"]["operator"]["value"] = "→"
    elif mutation == "free_variable":
        norm["formula"]["right"]["formula"]["arguments"][0]["name"] = "z"
    elif mutation == "wrong_modality":
        norm["formula"]["right"]["operator"]["value"] = "P"
    elif mutation == "true_lean":
        report["lean_body"] = "def formula_0 : Prop := True"
    elif mutation == "rebinding":
        key = next(iter(report["definition_symbol_rebinding"]))
        report["definition_symbol_rebinding"][key] = key
    else:
        report["source_semantics_verified"] = True
    changed = rebound_report(report)
    arguments["expected_report_sha256"] = sha(changed)
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_definition_norm_bytes(changed, **arguments)


@pytest.mark.parametrize(
    "suffix", [" unless exempt.", " if licensed.", " within 10 days.", " and notify."]
)
def test_hash_repaired_requests_cannot_discard_unsupported_norm_suffix(suffix):
    raw, _, _, arguments = case()
    request, html = fixture_request(norm_suffix=suffix)
    arguments.update(
        request_raw=wire(request),
        expected_request_sha256=sha(wire(request)),
        raw_html=html,
        expected_raw_sha256=sha(html),
        expected_extracted_sha256=sha(
            request["definition_request"]["document"]["document_text"].encode()
        ),
    )
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_definition_norm_bytes(raw, **arguments)


@pytest.mark.parametrize("cue", ["includes", "deems"])
def test_hash_repaired_definition_cue_cannot_expand_means_profile(cue):
    raw, _, request, arguments = case()
    html = arguments["raw_html"].replace(b"means", cue.encode())
    previous = request["definition_request"]["document"]
    document = context.extract_document(
        html, url=previous["source_url"], edition=previous["edition"], legal_id=previous["legal_id"]
    )
    text = document["document_text"]
    request["definition_request"].update(
        document=document, raw_html_base64=base64.b64encode(html).decode()
    )
    declaration = request["definition_request"]["declaration"]
    for span in [
        declaration["definition_cue"],
        *[item["span"] for item in declaration["body"]["operands"]],
    ]:
        literal = cue if span is declaration["definition_cue"] else span["text"]
        start = text.index(literal)
        span.update(char_start=start, char_end=start + len(literal), text=literal)
    norm = request["norm_declaration"]
    norm.update(
        {
            key: document[key]
            for key in ("document_id", "document_text_sha256", "legal_id", "edition")
        }
    )
    norm_start = document["paragraphs"][-1]["char_start"]
    for key in ("source_span", "quantifier_span", "category_span", "modality_span", "action_span"):
        span = norm[key]
        start = text.index(span["text"], norm_start)
        span.update(char_start=start, char_end=start + len(span["text"]))
    request_raw = wire(request)
    arguments.update(
        request_raw=request_raw,
        expected_request_sha256=sha(request_raw),
        raw_html=html,
        expected_raw_sha256=sha(html),
        expected_extracted_sha256=sha(text.encode()),
    )
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_definition_norm_bytes(raw, **arguments)


@pytest.mark.parametrize(
    "damage",
    [
        "joint_ast",
        "definition",
        "norm",
        "symbols",
        "source",
        "binding",
        "graph",
        "issues",
        "authority",
    ],
)
def test_resealed_candidate_mutations_cannot_replace_independent_regeneration(damage):
    record, raw, _, _, arguments = adapt_case()
    if damage == "joint_ast":
        record["ast_record"]["native_ast"]["right"]["quantifier"]["value"] = "∃"
        record["ast_record"] = reseal(record["ast_record"])
    elif damage in {"definition", "norm"}:
        key = damage + "_record"
        record[key]["native_ast"]["quantifier"]["value"] = "∃"
        record[key] = reseal(record[key])
    elif damage == "symbols":
        record["symbol_record"]["variable_binding"]["ground_actor_constant_substitution"] = True
        record["symbol_record"] = reseal(record["symbol_record"])
    elif damage == "source":
        record["source_occurrences"][0]["start_utf8"] += 1
        record["source_occurrences"][0] = reseal(record["source_occurrences"][0])
    elif damage == "binding":
        record["source_bindings"].pop()
    elif damage == "graph":
        record["graph"]["edges"] = [
            edge for edge in record["graph"]["edges"] if edge["relation"] != "USES_DEFINITION"
        ]
        record["graph"] = reseal(record["graph"])
    elif damage == "issues":
        record["issues"] = []
    else:
        record["proof_authority"] = True
    with pytest.raises(contracts.CorpusContractError):
        adapter.validate_definition_norm_candidate(reseal(record), raw, **arguments)


def test_common_input_and_record_bounds_refuse_without_truncation():
    raw, report, _, arguments = case()
    report["oversized_unknown"] = "x" * contracts.MAX_RECORD_BYTES
    oversized = wire(report)
    arguments["expected_report_sha256"] = sha(oversized)
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_definition_norm_bytes(oversized, **arguments)
    raw, _, request, arguments = case()
    request["oversized_unknown"] = "x" * contracts.MAX_RECORD_BYTES
    arguments["request_raw"] = wire(request)
    arguments["expected_request_sha256"] = sha(arguments["request_raw"])
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_definition_norm_bytes(raw, **arguments)


@pytest.mark.parametrize("operator", ["any", "all", "not"])
def test_ordered_boolean_definition_structure_and_repeated_atoms_remain_exact(operator):
    request, html = fixture_request()
    declaration = request["definition_request"]["declaration"]
    first, second = declaration["body"]["operands"]
    expression = {
        "op": "any" if operator == "not" else operator,
        "operands": [deepcopy(second), deepcopy(first), deepcopy(second)],
    }
    declaration["body"] = {"op": "not", "operand": expression} if operator == "not" else expression
    raw, report, _, arguments = case_from_request(request, html)
    record = adapter.adapt_definition_norm_bytes(raw, **arguments)
    assert record["definition_record"]["declaration"]["body"] == declaration["body"]
    assert record["definition_record"]["native_ast"] == report["bound_definition_native_ast"]
    bindings = [
        item for item in record["source_bindings"] if item["role"].startswith("definition_body/")
    ]
    assert [item["role"] for item in bindings] == [
        "definition_body/0000",
        "definition_body/0001",
        "definition_body/0002",
    ]
    assert bindings[0]["symbol"] == bindings[2]["symbol"] != bindings[1]["symbol"]
    # Repeated declaration positions are retained even when they name the same
    # exact physical occurrence and therefore share its custody record.
    assert bindings[0]["source_occurrence_cid"] == bindings[2]["source_occurrence_cid"]


def test_supported_definition_atom_crossing_paragraph_boundary_keeps_every_origin():
    request, html = fixture_request(descendant=True)
    document = request["definition_request"]["document"]
    text = document["document_text"]
    declaration = request["definition_request"]["declaration"]
    start = declaration["body"]["operands"][0]["span"]["char_start"]
    end = declaration["body"]["operands"][1]["span"]["char_end"]
    declaration["body"]["operands"][0]["span"] = {
        "char_start": start,
        "char_end": end,
        "text": text[start:end],
    }
    raw, report, _, arguments = case_from_request(request, html)
    record = adapter.adapt_definition_norm_bytes(raw, **arguments)
    binding = next(
        item for item in record["source_bindings"] if item["role"] == "definition_body/0000"
    )
    assert binding["paragraph_indices"] == [1, 2]
    occurrence = next(
        item
        for item in record["source_occurrences"]
        if item["record_cid"] == binding["source_occurrence_cid"]
    )
    assert occurrence["span_text"] == text[start:end] and "\n" in occurrence["span_text"]
    assert record["ast_record"]["native_ast"] == report["native_ast"]


@pytest.mark.parametrize("limit", ["MAX_SOURCE_OCCURRENCES", "MAX_SOURCE_BINDINGS"])
def test_occurrence_and_binding_caps_refuse_the_whole_candidate(monkeypatch, limit):
    raw, _, _, arguments = case(descendant=True)
    monkeypatch.setattr(adapter, limit, 1)
    with pytest.raises(contracts.CorpusContractError, match="bound"):
        adapter.adapt_definition_norm_bytes(raw, **arguments)


def test_aggregate_common_envelope_refuses_even_when_individual_inputs_fit(monkeypatch):
    raw, _, _, arguments = case()
    maximum = max(len(raw), len(arguments["request_raw"])) + 1024
    assert len(raw) < maximum and len(arguments["request_raw"]) < maximum
    monkeypatch.setattr(contracts, "MAX_RECORD_BYTES", maximum)
    with pytest.raises(contracts.CorpusContractError, match="byte bound"):
        adapter.adapt_definition_norm_bytes(raw, **arguments)


@pytest.mark.parametrize(
    "damage", ["raw_html", "extracted_view", "modal_context", "constant_variable"]
)
def test_repaired_request_hash_cannot_retarget_source_or_change_supported_binding(damage):
    raw, _, request, arguments = case()
    if damage == "raw_html":
        arguments["raw_html"] += b"<!-- changed but not in the original request -->"
        arguments["expected_raw_sha256"] = sha(arguments["raw_html"])
    elif damage == "extracted_view":
        document = request["definition_request"]["document"]
        document["document_text"] += "extra omitted source text"
        arguments["expected_extracted_sha256"] = sha(document["document_text"].encode())
    elif damage == "modal_context":
        request["norm_declaration"]["modal_context"] = "invented world restriction"
    else:
        request["norm_declaration"]["variable"] = "named_actor"
    arguments["request_raw"] = wire(request)
    arguments["expected_request_sha256"] = sha(arguments["request_raw"])
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_definition_norm_bytes(raw, **arguments)


def test_public_import_is_inert_without_session_model_or_native_process(tmp_path):
    code = """
import json, subprocess, sys
def forbidden(*args, **kwargs):
    raise AssertionError('public import executed a process')
subprocess.Popen = forbidden
from ipfs_datasets_py.logic.autoformal import corpus_definition_norm_adapter
import ipfs_datasets_py.logic.autoformal as package
assert 'SESSION' not in vars(package)
assert not any(name in sys.modules for name in ('torch','transformers','tensorflow'))
assert 'ipfs_datasets_py.logic.autoformal.legal_source_definition_norm_bridge' not in sys.modules
assert 'ipfs_datasets_py.logic.autoformal.legal_family_routes' not in sys.modules
assert not any(name.startswith('scripts.ops.legal_ir.check_legal_definition_norm_binding') for name in sys.modules)
print(json.dumps({'public_import_inert': True}))
"""
    env = dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[4])
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"public_import_inert": True}
    assert list(tmp_path.iterdir()) == []


def test_real_parquet_roundtrip_preserves_definition_use_edges_and_all_provenance(tmp_path):
    pytest.importorskip("pyarrow")
    record, raw, _, _, arguments = adapt_case(descendant=True, repeated=True)
    directory = tmp_path / "definition-norm"
    manifest = adapter.export_definition_norm_candidate(
        record, directory, report_raw=raw, **arguments
    )
    loaded = load_graph_bundle(
        directory, expected_manifest_sha256=sha(canonical_dag_json_bytes(manifest))
    )
    assert loaded["snapshot"] == record["graph"]
    assert {edge["relation"] for edge in loaded["snapshot"]["edges"]} >= {
        "DEFINES",
        "USES_DEFINITION",
    }
    assert (
        manifest["admitted"]
        is manifest["formalized"]
        is manifest["external_references_verified"]
        is False
    )
