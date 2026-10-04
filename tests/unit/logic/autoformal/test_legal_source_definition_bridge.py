from copy import deepcopy
from dataclasses import replace
import base64
import itertools

import pytest

from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_definition_lake as gate

URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title40/html/USCODE-2024-title40-sec1.htm"
HTML = b'''<h3 class="section-head">&sect;1. Test definition</h3>
<p class="statutory-body">(a) Definitions. In this section:</p>
<p class="statutory-body-1em">(1) The term "widget" means registered and either active or exempt.</p>
<p class="statutory-body">(b) Other scope. In this section:</p>
<p class="statutory-body-1em">(1) The term "widget" means unregistered.</p>'''


def request(family="fol"):
    doc = context.extract_document(HTML, url=URL, edition=2024, legal_id="usc:us:40:1")
    text = doc["document_text"]
    def span(literal):
        start = text.index(literal)
        return {"char_start": start, "char_end": start + len(literal), "text": literal}
    declaration = {"declaration_id": "authored-definition", "profile": bridge.PROFILE,
        "interpretation_status": "unreviewed_caller_declaration", "paragraph_index": 1,
        "scope_span": span("In this section:"), "definition_cue": span("means"), "head": span("widget"),
        "body": {"op": "all", "operands": [{"op": "atom", "span": span("registered")},
            {"op": "any", "operands": [{"op": "atom", "span": span("active")},
                                      {"op": "atom", "span": span("exempt")}]}]}}
    return {"document": doc, "raw_html_base64": base64.b64encode(HTML).decode(),
            "declaration": declaration, "family": family}


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_native_quantifier_biconditional_and_boolean_structure_survive(family):
    req = request(family)
    report = bridge.prepare_definition(req)
    ast = report["native_ast"]
    assert ast["node_type"] == "QuantifiedFormula" and ast["quantifier"]["value"] == "∀"
    assert ast["formula"]["operator"]["value"] == "↔"
    assert ast["formula"]["right"]["operator"]["value"] == "∧"
    assert ast["formula"]["right"]["right"]["operator"]["value"] == "∨"
    assert report["native"]["exact_native_ast_roundtrip"]
    assert "∀ v0 : Entity" in report["lean_body"]
    assert bridge.validate_definition(report, req)
    assert not any(report[k] for k in ("source_semantics_verified", "training_qualified", "admitted"))


@pytest.mark.parametrize("mutation", ["forall_exists", "iff_implication", "and_or", "scope", "span", "lean", "authority"])
def test_repaired_report_hash_cannot_hide_meaning_or_binding_change(mutation):
    req = request()
    report = deepcopy(bridge.prepare_definition(req))
    if mutation == "forall_exists": report["native_ast"]["quantifier"]["value"] = "∃"
    elif mutation == "iff_implication": report["native_ast"]["formula"]["operator"]["value"] = "→"
    elif mutation == "and_or": report["native_ast"]["formula"]["right"]["operator"]["value"] = "∨"
    elif mutation == "scope": report["scope_key"] = "0" * 64
    elif mutation == "span": report["symbol_occurrences"][0]["span"]["char_start"] += 1
    elif mutation == "lean": report["lean_body"] = "def formula_0 : Prop := True"
    else: report["admitted"] = True
    report["report_sha256"] = bridge.digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="regeneration"):
        bridge.validate_definition(report, req)


@pytest.mark.parametrize("mutation", ["foreign_scope", "cross_region", "head_self_reference", "modal", "sort", "norm_cue", "bad_html", "false_document_hash"])
def test_inconsistent_or_unsupported_declarations_fail_closed(mutation):
    req = request()
    decl = req["declaration"]
    if mutation == "foreign_scope":
        pos = req["document"]["document_text"].rindex("In this section:")
        decl["scope_span"].update(char_start=pos, char_end=pos + len("In this section:"))
    elif mutation == "cross_region":
        pos = req["document"]["document_text"].index("unregistered")
        decl["body"] = {"op": "atom", "span": {"char_start": pos, "char_end": pos + 12, "text": "unregistered"}}
    elif mutation == "head_self_reference": decl["body"] = {"op": "atom", "span": deepcopy(decl["head"])}
    elif mutation == "modal": decl["body"] = {"op": "O", "operand": decl["body"]}
    elif mutation == "sort": decl["sort"] = "Agent"
    elif mutation == "norm_cue": decl["definition_cue"]["text"] = "shall"
    elif mutation == "bad_html": req["raw_html_base64"] = "!invalid!"
    else: req["document"]["document_text_sha256"] = "0" * 64
    with pytest.raises(ValueError): bridge.prepare_definition(req)


def test_distinct_section_scopes_do_not_share_same_surface_predicates():
    first = bridge.prepare_definition(request())
    second_request = request()
    second_html = HTML.replace(b"&sect;1.", b"&sect;2.")
    second_request["document"] = context.extract_document(second_html, url=URL.replace("sec1", "sec2"), edition=2024, legal_id="usc:us:40:2")
    second_request["raw_html_base64"] = base64.b64encode(second_html).decode()
    second = bridge.prepare_definition(second_request)
    assert first["scope_key"] != second["scope_key"]
    assert not {x["symbol"] for x in first["symbols"]} & {x["symbol"] for x in second["symbols"]}


def evaluate(ast, values, environment=None):
    environment = {} if environment is None else environment
    kind = ast["node_type"]
    if kind == "Predicate": return values[ast["name"]][environment[ast["arguments"][0]["name"]]]
    if kind == "QuantifiedFormula":
        results = [evaluate(ast["formula"], values, environment | {ast["variable"]["name"]: x}) for x in (0, 1)]
        return all(results) if ast["quantifier"]["value"] == "∀" else any(results)
    left, right = evaluate(ast["left"], values, environment), evaluate(ast["right"], values, environment)
    return {"∧": left and right, "∨": left or right, "↔": left == right, "→": not left or right}[ast["operator"]["value"]]


def test_two_entity_models_independently_distinguish_quantifier_and_definition_mutants():
    report = bridge.prepare_definition(request())
    names = {row["source_literal"]: row["symbol"] for row in report["symbols"]}
    differences = {"existential": 0, "one_way": 0, "weakened_conjunction": 0}
    for bits in itertools.product((False, True), repeat=8):
        literal_values = {name: bits[2*i:2*i+2] for i, name in enumerate(("widget", "registered", "active", "exempt"))}
        values = {names[k]: v for k, v in literal_values.items()}
        expected = all(literal_values["widget"][i] == (literal_values["registered"][i] and
                       (literal_values["active"][i] or literal_values["exempt"][i])) for i in (0, 1))
        assert evaluate(report["native_ast"], values) == expected
        for name in differences:
            mutated = deepcopy(report["native_ast"])
            if name == "existential": mutated["quantifier"]["value"] = "∃"
            elif name == "one_way": mutated["formula"]["operator"]["value"] = "→"
            else: mutated["formula"]["right"]["operator"]["value"] = "∨"
            differences[name] += evaluate(mutated, values) != expected
    assert all(count > 0 for count in differences.values())


@pytest.mark.parametrize("replacement", ["def formula_0 : Prop := True", "axiom illegal : False", "theorem fake : False := by exact (sorry)"])
def test_lean_tampering_is_rejected_even_with_repaired_file_hashes(replacement):
    prepared = gate.prepare([request()], toolchain="leanprover/lean4:v4.34.1")
    files, manifest = dict(prepared.files), prepared.to_dict()
    name = "LegalDefinition/Definition0000.lean"
    files[name] = replacement
    manifest["file_sha256"][name] = gate.shared._sha(replacement)
    forged = replace(prepared, files=tuple(sorted(files.items())), manifest=gate.shared._json(manifest))
    with pytest.raises(ValueError, match="changed"):
        gate.validate(forged)


def test_all_definition_modules_required_and_duplicate_requests_rejected():
    requests = [request("fol"), request("tdfol")]
    prepared = gate.prepare(requests, toolchain="leanprover/lean4:v4.34.1")
    assert len(prepared.to_dict()["definitions"]) == 2
    files = dict(prepared.files)
    files["LegalDefinition.lean"] = "import LegalDefinition.Definition0000\n"
    with pytest.raises(ValueError): gate.validate(replace(prepared, files=tuple(sorted(files.items()))))
    with pytest.raises(ValueError, match="duplicate"):
        gate.prepare([requests[0], requests[0]], toolchain="leanprover/lean4:v4.34.1")
