from copy import deepcopy
from dataclasses import replace
import base64
import itertools

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_lake as gate
from scripts.ops.legal_ir.check_legal_definition_norm_binding import fixture_request


@pytest.mark.parametrize("modality,family", itertools.product("OPF", bridge.FAMILIES))
def test_native_composition_preserves_quantified_category_and_modal_binding(modality, family):
    request = fixture_request(modality, family)
    report = bridge.prepare_definition_norm(request)
    assert bridge.validate_definition_norm(report, request)
    joint = report["native_ast"]
    assert joint["operator"]["value"] == "∧"
    assert joint["left"] == report["bound_definition_native_ast"]
    assert set(report["definition_symbol_rebinding"]) == {s["symbol"] for s in report["definition"]["symbols"]}
    assert joint["right"] == report["norm_native_ast"]
    guard = joint["right"]["formula"]
    assert guard["operator"]["value"] == "→"
    assert guard["left"]["name"] == joint["left"]["formula"]["left"]["name"]
    assert guard["right"]["operator"]["value"] == modality
    assert guard["left"]["arguments"] == guard["right"]["formula"]["arguments"]
    assert guard["left"]["arguments"][0]["node_type"] == "Variable"
    assert not any(report[key] for key in bridge.FALSE_FLAGS)
    assert "i.constant" not in report["lean_body"]
    assert report["complete_norm_paragraph_covered"]


@pytest.mark.parametrize("mutation", ["exists", "one_way", "drop_guard", "constant", "free", "capture",
    "wrong_action", "wrong_scope", "other_modality", "modal_context", "true_lean", "authority", "ground_alias"])
def test_repaired_report_hash_does_not_hide_meaning_or_variable_mutation(mutation):
    request = fixture_request(); report = deepcopy(bridge.prepare_definition_norm(request))
    norm = report["native_ast"]["right"]
    if mutation == "exists": norm["quantifier"]["value"] = "∃"
    elif mutation == "one_way": report["native_ast"]["left"]["formula"]["operator"]["value"] = "→"
    elif mutation == "drop_guard": norm["formula"] = norm["formula"]["right"]
    elif mutation == "constant": norm["formula"]["right"]["formula"]["arguments"][0]["node_type"] = "Constant"
    elif mutation == "free": norm["formula"]["right"]["formula"]["arguments"][0]["name"] = "z"
    elif mutation == "capture": norm["variable"]["name"] = "y"
    elif mutation == "wrong_action": norm["formula"]["right"]["formula"]["name"] = norm["formula"]["left"]["name"]
    elif mutation == "wrong_scope": report["scope_key"] = "0" * 64
    elif mutation == "other_modality": norm["formula"]["right"]["operator"]["value"] = "P"
    elif mutation == "modal_context": norm["formula"]["right"]["context"] = "invented"
    elif mutation == "true_lean": report["lean_body"] = "def formula_0 : Prop := True"
    elif mutation == "ground_alias": report["variable_binding"]["ground_actor_constant_substitution"] = True
    else: report["source_semantics_verified"] = True
    report["report_sha256"] = bridge.digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="authoritative regeneration"):
        bridge.validate_definition_norm(report, request)


@pytest.mark.parametrize("suffix", [" unless exempt.", " if licensed.", " within 10 days.",
    " Each covered filer may appeal.", " and notify.", "\n(b)(1) a second norm"])
def test_complete_norm_coverage_rejects_silent_suffix_omission(suffix):
    with pytest.raises(ValueError, match="coverage"):
        bridge.prepare_definition_norm(fixture_request(norm_suffix=suffix))


@pytest.mark.parametrize("mutation", ["extra_request", "extra_norm", "extra_provenance", "family_fol", "family_dcec",
    "different_document", "different_version", "different_section", "wrong_head", "wrong_span", "quantifier",
    "false_review", "wrong_scope", "object", "unknown_provenance", "huge_id"])
def test_closed_source_scope_and_interpretation_contract(mutation):
    request = fixture_request(); norm = request["norm_declaration"]
    if mutation == "extra_request": request["reviewed"] = True
    elif mutation == "extra_norm": norm["ignored"] = []
    elif mutation == "extra_provenance": request["source_provenance"]["downloaded"] = True
    elif mutation == "family_fol": request["family"] = "fol"
    elif mutation == "family_dcec": request["family"] = "dcec"
    elif mutation == "different_document": norm["document_id"] = "other"
    elif mutation == "different_version": norm["edition"] = 2023
    elif mutation == "different_section": norm["legal_id"] = "usc:us:40:2"
    elif mutation == "wrong_head": norm["definition_head_symbol"] = "D" + "0" * 64
    elif mutation == "wrong_span": norm["category_span"]["char_start"] -= 1
    elif mutation == "quantifier": norm["quantifier_span"]["text"] = "Every"
    elif mutation == "false_review": request["source_provenance"]["independently_reviewed"] = True
    elif mutation == "wrong_scope": norm["activation_scope"] = "inside_modal"
    elif mutation == "object": norm["object"] = "report"
    elif mutation == "unknown_provenance": request["source_provenance"]["kind"] = "authenticated_statute"
    else: norm["norm_id"] = "x" * 257
    with pytest.raises(ValueError): bridge.prepare_definition_norm(request)


@pytest.mark.parametrize("section,edition", [("2", 2024), ("1", 2023)])
def test_same_literal_other_section_or_version_never_aliases(section, edition):
    original_request = fixture_request(); other_request = fixture_request(section=section, edition=edition)
    first, other = (bridge.prepare_definition_norm(r) for r in (original_request, other_request))
    assert first["scope_key"] != other["scope_key"]
    assert not {s["symbol"] for s in first["symbol_table"]} & {s["symbol"] for s in other["symbol_table"]}
    other_request["norm_declaration"]["definition_head_symbol"] = first["variable_binding"]["category_symbol"]
    with pytest.raises(ValueError, match="exact scoped definition head"):
        bridge.prepare_definition_norm(other_request)


def evaluate(ast, values, *, world=0, env=None, modal=None):
    """Independent finite interpretation; only explicitly chosen test semantics."""
    env = {} if env is None else env
    kind = ast["node_type"]
    if kind == "Predicate":
        arg = ast["arguments"][0]
        entity = env[arg["name"]] if arg["node_type"] == "Variable" else 0
        return values[ast["name"]][world][entity]
    if kind == "QuantifiedFormula":
        cells = [evaluate(ast["formula"], values, world=world, env=env | {ast["variable"]["name"]: x}, modal=modal) for x in (0, 1)]
        return all(cells) if ast["quantifier"]["value"] == "∀" else any(cells)
    if kind == "DeonticFormula":
        body = lambda at: evaluate(ast["formula"], values, world=at, env=env, modal=modal)
        return modal(ast["operator"]["value"], body, world) if modal else body(world)
    left = evaluate(ast["left"], values, world=world, env=env, modal=modal)
    right = evaluate(ast["right"], values, world=world, env=env, modal=modal)
    return {"∧": left and right, "∨": left or right, "→": not left or right, "↔": left == right}[ast["operator"]["value"]]


def test_exhaustive_two_entity_models_detect_quantifier_guard_and_constant_loss():
    report = bridge.prepare_definition_norm(fixture_request())
    symbols = {s["source_literal"]: s["symbol"] for s in report["symbol_table"]}
    mutants = {}
    for name in ("exists", "drop_guard", "constant_actor", "one_way", "and_instead_or"):
        ast = deepcopy(report["native_ast"]); norm = ast["right"]
        if name == "exists": norm["quantifier"]["value"] = "∃"
        elif name == "drop_guard": norm["formula"] = norm["formula"]["right"]
        elif name == "constant_actor": norm["formula"]["right"]["formula"]["arguments"][0]["node_type"] = "Constant"
        elif name == "one_way": ast["left"]["formula"]["operator"]["value"] = "→"
        else: ast["left"]["formula"]["right"]["operator"]["value"] = "∧"
        mutants[name] = ast
    differences = {name: 0 for name in mutants}
    for bits in itertools.product((False, True), repeat=8):
        literals = {name: bits[2*i:2*i+2] for i, name in enumerate(("covered filer", "registered", "licensed", "register"))}
        values = {symbols[name]: [v] for name, v in literals.items()}
        expected = all(literals["covered filer"][x] == (literals["registered"][x] or literals["licensed"][x])
                       and (not literals["covered filer"][x] or literals["register"][x]) for x in (0, 1))
        assert evaluate(report["native_ast"], values) == expected
        for name, ast in mutants.items(): differences[name] += evaluate(ast, values) != expected
    assert all(differences.values())


def test_two_world_countermodel_distinguishes_category_outside_modal():
    report = bridge.prepare_definition_norm(fixture_request())
    symbols = {s["source_literal"]: s["symbol"] for s in report["symbol_table"]}
    values = {symbols[name]: [(False, False), (True, True)] for name in ("covered filer", "registered", "licensed")}
    values[symbols["register"]] = [(False, False), (False, False)]
    ast = deepcopy(report["native_ast"])
    guard = ast["right"]["formula"]
    modality = deepcopy(guard["right"])
    modality["formula"] = {**guard, "right": guard["right"]["formula"]}
    ast["right"]["formula"] = modality
    modal = lambda operator, body, world: body(1)
    assert evaluate(report["native_ast"], values, modal=modal) is True
    assert evaluate(ast, values, modal=modal) is False


@pytest.mark.parametrize("mutation", ["true", "axiom", "sorry", "missing_nonfirst", "wrong_root"])
def test_changed_lean_or_module_coverage_rejected_with_repaired_hashes(mutation):
    preparation = gate.prepare([fixture_request("O", f) for f in bridge.FAMILIES], toolchain="leanprover/lean4:v4.34.1")
    files, manifest = dict(preparation.files), preparation.to_dict()
    name = "LegalDefinitionNorm/Definition0001.lean"
    if mutation == "missing_nonfirst": del files[name]
    elif mutation == "wrong_root": files["LegalDefinitionNorm.lean"] = "import LegalDefinitionNorm.Definition0000\n"
    else: files[name] = {"true": "def formula_0 : Prop := True", "axiom": "axiom bad : False", "sorry": "theorem bad : False := by sorry"}[mutation]
    manifest["file_sha256"] = {n: gate.shared._sha(s) for n, s in files.items()}
    forged = replace(preparation, files=tuple(sorted(files.items())), manifest=gate.shared._json(manifest))
    with pytest.raises(ValueError, match="changed"): gate.validate(forged)


def test_request_and_batch_resource_limits_are_closed():
    request = fixture_request()
    with pytest.raises(ValueError): gate.prepare([], toolchain="leanprover/lean4:v4.34.1")
    with pytest.raises(ValueError): gate.prepare([request] * 65, toolchain="leanprover/lean4:v4.34.1")
    with pytest.raises(ValueError, match="duplicate"): gate.prepare([request, request], toolchain="leanprover/lean4:v4.34.1")
    with pytest.raises(ValueError): gate.prepare([request], toolchain="unversioned")
    request["source_provenance"]["kind"] = "x" * (4 * 1024**2)
    with pytest.raises(ValueError, match="byte bound"): bridge.prepare_definition_norm(request)


@pytest.mark.parametrize("mutation", ["child_list", "notes", "leading_condition", "second_scope"])
def test_context_around_selected_norm_cannot_be_silently_omitted(mutation):
    request = fixture_request(); definition = request["definition_request"]
    raw = base64.b64decode(definition["raw_html_base64"])
    if mutation == "child_list": raw += b'<p class="statutory-body-1em">(1) Unless exempt.</p>'
    elif mutation == "notes": raw = raw.replace(b'<p class="statutory-body">(b)', b'<p class="source-credit">(b)')
    elif mutation == "leading_condition": raw = raw.replace(b'(b) Each', b'(b) Unless exempt, Each')
    else: raw += b'<p class="statutory-body">(c) In this section, other scope applies.</p>'
    old = definition["document"]
    doc = bridge.definitions.context.extract_document(raw, url=old["source_url"], edition=old["edition"], legal_id=old["legal_id"])
    definition["document"] = doc; definition["raw_html_base64"] = base64.b64encode(raw).decode()
    norm = request["norm_declaration"]
    norm.update({key: doc[key] for key in ("document_id", "document_text_sha256", "legal_id", "edition")})
    # Recompute the caller's hash-dependent head binding, so rejection is about
    # the actual omitted context, not a stale source digest.
    report = bridge.definitions.prepare_definition(definition)
    norm["definition_head_symbol"] = report["native_ast"]["formula"]["left"]["name"]
    if mutation == "leading_condition":
        shift = len("Unless exempt, ")
        for field in ("source_span", "quantifier_span", "category_span", "modality_span", "action_span"):
            norm[field]["char_start"] += shift; norm[field]["char_end"] += shift
    with pytest.raises(ValueError): bridge.prepare_definition_norm(request)


def test_supplied_html_provenance_still_has_no_authentication_or_review_authority():
    request = fixture_request()
    request["source_provenance"]["kind"] = "supplied_html_unreviewed"
    report = bridge.prepare_definition_norm(request)
    assert not any(report[key] for key in bridge.FALSE_FLAGS)


def test_original_definition_namespace_collision_is_explicitly_rebound():
    a, b = [bridge.prepare_definition_norm(fixture_request(edition=e)) for e in (2023, 2024)]
    assert a["definition"]["scope_key"] == b["definition"]["scope_key"]
    assert a["definition_symbol_rebinding"].keys() == b["definition_symbol_rebinding"].keys()
    assert not set(a["definition_symbol_rebinding"].values()) & set(b["definition_symbol_rebinding"].values())


def test_report_symbol_rebinding_tamper_is_rejected_after_hash_repair():
    request = fixture_request(); report = bridge.prepare_definition_norm(request)
    key = next(iter(report["definition_symbol_rebinding"]))
    report["definition_symbol_rebinding"][key] = key
    report["report_sha256"] = bridge.digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="authoritative regeneration"):
        bridge.validate_definition_norm(report, request)
