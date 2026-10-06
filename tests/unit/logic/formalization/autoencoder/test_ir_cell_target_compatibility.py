"""Cached-target coverage over private packages; never a numerical model test.

The checkpoint documents are deliberately small schema fixtures. Existing route
and replay preparation remain real; only model loading is replaced by a refusal.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
from ipfs_datasets_py.logic.formalization.autoencoder import ir_cell_runtime as runtime
from ipfs_datasets_py.logic.formalization.autoencoder import ir_cell_target_compatibility as compatibility
from tests.unit.logic.formalization.autoencoder import test_ir_cell_routing as shared
from tests.unit.logic.formalization.autoencoder import test_ir_cell_runtime as replay_shared


SPECIAL = ["<pad>", "<bos>", "<eos>"]
FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = FIELDS[4:]
JSON_TOKEN = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
    r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r'|true|false|null|[{}\[\],:]'
)


def canonical(value, *, ascii=True):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=ascii, allow_nan=False)


def lexical_tokens(value):
    encoded = canonical(value)
    pieces = JSON_TOKEN.findall(encoded)
    assert "".join(pieces) == encoded
    return pieces


def intent_target(*, actor="operator", action="save", obj="report", modality="required"):
    return {"kind": "intent_rich_ast", "document": {
        "kind": "atom", "actor": actor, "action": action,
        "object": obj, "modality": modality}}


def security_target(*, operator="+", left="expr:value", right="expr:constant"):
    return {"kind": "program_expression", "document": {
        "attributes": {}, "evaluation_order": [left, right],
        "expression_id": "expr:result", "kind": "binary",
        "operand_ids": [left, right], "operator": operator,
        "source_ref_ids": ["source"], "span_ids": [], "symbol_ids": [],
        "type_ref": "integer"}}


def legal_target(*, actor="auditor", action="retain", obj="record", modality="O",
                 conditions=(), exceptions=(), temporal=()):
    return {"rules": [{"modality": modality, "actor": actor, "action": action,
        "object": obj, "conditions": list(conditions),
        "exceptions": list(exceptions), "temporal": list(temporal)}]}


def legal_vocabulary(targets):
    structural = [*SPECIAL]
    for field in FIELDS:
        structural.append(canonical(["field", field], ascii=False))
        if field in QUALIFIERS:
            structural.append(canonical(["end", field], ascii=False))
    atoms = set()
    for target in targets:
        for rule in target["rules"]:
            for field in FIELDS:
                values = rule[field] if field in QUALIFIERS else [rule[field]]
                atoms.update(canonical(["atom", field, value], ascii=False) for value in values)
    return [*structural, *sorted(atoms)]


def checkpoint_pin(data, value):
    pin = shared.write_json(data["package_dir"] / "checkpoint.json", value)
    data["checkpoint"] = value
    data["manifest"]["files"]["checkpoint.json"] = {
        key: pin[key] for key in ("bytes", "sha256")}
    replay_shared.rewrite_manifest(data)
    document = data["documents"][(data["family"], 384)]
    document["existing_checkpoint_evidence"][0]["receipt"] = pin
    shared.rewrite_cell(data, data["family"], 384)
    data["request"]["checkpoint_sha256"] = pin["sha256"]
    return pin


def preflight(data, **changes):
    options = replay_shared.arguments(data)
    options.update(changes)
    return compatibility.preflight_ir_cell_cached_targets(
        data["directory_pin"], list(data["pins"].values()), data["request"], **options)


@pytest.fixture(autouse=True)
def forbid_model_loading(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Target preflight called a numerical loader")
    monkeypatch.setattr(hub, "_instantiate", forbidden)
    monkeypatch.setattr(hub, "open_ir_cell_autoencoder", forbidden)
    monkeypatch.setattr(runtime, "_open_ir_cell_autoencoder", forbidden)


ARCHITECTURE = "residual-projection-latent-formula-gru/v1"
DOMAIN_RUNTIME_SHA = "66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6"
LEGAL_CODEC_SHA = "f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290"
LATENT_RUNTIME_SHA = "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"
LEGAL_POLICY = {
    "source_tokenization": "unicode_casefold_word_or_punctuation/v1",
    "source_unknown": "reject", "target_unknown": "reject",
    "vocabulary_origin": "training_examples_only", "identifier_hashing": False,
    "target_schema": "CanonicalRoundTripIR@1", "rule_count": 1,
    "field_order": list(FIELDS), "qualifiers": "sorted_unique_input_required",
    "max_qualifiers_per_facet": 4, "max_source_tokens": 64,
    "max_target_tokens": 64, "max_vocabulary": 4096,
    "source_pad_id": 0, "source_unk_id": 1,
    "target_pad_id": 0, "target_bos_id": 1, "target_eos_id": 2,
    "truncation": "reject", "generation_fallback": "none",
}
DOMAIN_FALSE = ("qualified", "admitted", "proof_authority", "source_semantics_verified", "publication_performed")
LEGAL_FALSE = ("qualified", "admitted", "proof_authority", "semantic_correctness_verified", "promotion_performed")
HEAD_FALSE = (*LEGAL_FALSE, "formalized", "roundtrip_ok", "lake_executed", "publication_performed")


def make_compatibility(tmp_path, family="intent_ir", *, targets=None, known_targets=None,
                       max_target_tokens=512):
    data = replay_shared.make_replay(tmp_path, family)
    target = {"intent_ir": intent_target, "security_ir": security_target,
              "legal_ir": legal_target}[family]()
    targets = [deepcopy(target) for _ in range(3)] if targets is None else targets
    assert len(targets) == 3
    known_targets = targets if known_targets is None else known_targets
    for split in replay_shared.SPLITS:
        for row, value in zip(data["rows"][split], targets):
            row["target"] = deepcopy(value)
        replay_shared.rewrite_cache(data, split)
    if family != "legal_ir":
        checkpoint = {
            "schema": "domain-384-typed-autoencoder/v1", "dimension": 384,
            "domain_id": family, "architecture": ARCHITECTURE,
            **dict.fromkeys(DOMAIN_FALSE, False),
            "implementation": {"runtime": DOMAIN_RUNTIME_SHA, "dependencies": {},
                "scope": "listed_numerical_and_native_validator_modules_only"},
            "codec": {"schema": "typed-json-lexical/v1", "target_vocabulary": [
                *SPECIAL, *sorted({piece for value in known_targets for piece in lexical_tokens(value)})]},
            "config": {"max_target_tokens": max_target_tokens},
        }
    else:
        implementation = {"scope": "listed_latent_decoder_and_grammar_sources_only", "files": {
            "canonical_contracts.py": "1" * 64, "legal_formula_codec.py": LEGAL_CODEC_SHA,
            "legal_ir_grammar_decoder.py": "2" * 64, "modal_latent_formula.py": LATENT_RUNTIME_SHA,
            "tree_pin.py": "3" * 64}}
        binding = {"domain": "legal_ir", "dimension": 384, "lineage_id": "current_legal_v2",
                   "runtime_profile": "modal-latent-joint-formula/v1", "core_sha256": "4" * 64}
        head = {"schema": "modal-latent-formula-checkpoint/v1", "projection_id": "typed_deontic_rule_v1",
                **dict.fromkeys(HEAD_FALSE, False), "binding": deepcopy(binding),
                "implementation": deepcopy(implementation), "codec": {
                    "schema": "legal-source-formula-codec/v1", "source_vocabulary": ["<pad>", "<unk>", "latent"],
                    "target_vocabulary": legal_vocabulary(known_targets), "policy": deepcopy(LEGAL_POLICY)},
                "config": {"architecture": ARCHITECTURE, "max_target_tokens": 64,
                    "source_input": "provenance_only_not_neural_input"}}
        checkpoint = {"schema": "legal-current-384-inference-package/v1", "dimension": 384,
            "domain": family, "runtime": "legal_current_v2", **dict.fromkeys(LEGAL_FALSE, False),
            "core_binding": binding, "producer": {"formula_implementation": deepcopy(implementation)},
            "formula_checkpoint": head}
    checkpoint_pin(data, checkpoint)
    return data


def reject(data, **changes):
    with pytest.raises(compatibility.TargetCompatibilityError):
        preflight(data, **changes)


@pytest.mark.parametrize("family", ["intent_ir", "security_ir", "legal_ir"])
def test_supported_family_reports_authentic_ordered_coverage_without_models(tmp_path, family):
    data = make_compatibility(tmp_path, family)
    selected = [data["rows"]["test"][2]["id"], data["rows"]["test"][0]["id"]]
    report = preflight(data, row_ids=selected)
    assert report["schema"] == "ir-cell-cached-target-compatibility/v1"
    assert report["row_ids"] == [row["id"] for row in report["rows"]] == selected
    assert report["counts"] == {"selected": 2, "covered": 2, "incompatible": 0,
        "unsupported": 0, "with_oov": 0, "over_limit": 0}
    assert report["checkpoint_receipt"] == data["documents"][(family, 384)]["existing_checkpoint_evidence"][0]["receipt"]
    assert not report["model_load_performed"] and not report["inference_executed"]
    assert not report["targets_forwarded_to_model"] and not report["original_weights_changed"]
    assert not report["new_embeddings_generated"] and not any(report["authority"].values())
    assert report["codec_profile"]["vocabulary_changed"] is False
    for output, index in zip(report["rows"], (2, 0)):
        original = data["rows"]["test"][index]
        assert output["row_index"] == index and output["source_sha256"] == original["source_sha256"]
        assert output["embedding_sha256"] == original["embedding_sha256"]
        assert output["target_sha256"] == hashlib.sha256(canonical(original["target"]).encode()).hexdigest()
        assert output["status"] == "covered" and output["canonical_encoding_representable"] is True
        assert output["missing_tokens"] == [] and output["native_grammar_verified"] is False


@pytest.mark.parametrize("family,target,unknown", [
    ("intent_ir", intent_target(actor="dispatcher"), '"dispatcher"'),
    ("security_ir", security_target(left="expr:capacity"), '"expr:capacity"'),
])
def test_domain_whole_string_oov_is_incompatible_without_erasing_supported_rows(tmp_path, family, target, unknown):
    known = intent_target() if family == "intent_ir" else security_target()
    data = make_compatibility(tmp_path, family, targets=[known, target, target], known_targets=[known])
    report = preflight(data)
    assert report["counts"] == {"selected": 3, "covered": 1, "incompatible": 2,
        "unsupported": 0, "with_oov": 2, "over_limit": 0}
    assert report["rows"][0]["status"] == "covered"
    for row in report["rows"][1:]:
        assert row["canonical_encoding_representable"] is False and row["status"] == "incompatible"
        assert {item["token"] for item in row["missing_tokens"]} == {unknown}
        assert all(item["facet"] is None for item in row["missing_tokens"])
        assert len(row["missing_tokens"]) == lexical_tokens(target).count(unknown)


def test_legal_atoms_are_field_specific_and_report_oov_facets(tmp_path):
    known = legal_target(actor="auditor", action="retain", obj="record")
    unknown = legal_target(actor="retain", action="auditor", obj="record")
    data = make_compatibility(tmp_path, "legal_ir", targets=[known, unknown, known], known_targets=[known])
    report = preflight(data)
    assert report["counts"]["covered"] == 2 and report["counts"]["incompatible"] == 1
    missing = report["rows"][1]["missing_tokens"]
    assert [(item["facet"], item["token"]) for item in missing] == [
        ("actor", '["atom","actor","retain"]'), ("action", '["atom","action","auditor"]')]
    assert report["rows"][1]["token_count_including_bos_eos"] == 16


def test_known_legal_qualifiers_and_maximum_facet_size_preserve_exact_atoms(tmp_path):
    qualifiers = ["a", "b", "c", "d"]
    target = legal_target(conditions=qualifiers, exceptions=qualifiers, temporal=qualifiers)
    data = make_compatibility(tmp_path, "legal_ir", targets=[target] * 3)
    report = preflight(data)
    assert report["counts"]["covered"] == 3
    assert all(row["token_count_including_bos_eos"] == 28 and row["over_limit"] is False for row in report["rows"])
    assert report["codec_profile"]["max_target_tokens"] == 64


def test_unknown_legal_qualifier_is_reported_in_its_facet(tmp_path):
    known = legal_target()
    changed = legal_target(exceptions=["emergency"])
    data = make_compatibility(tmp_path, "legal_ir", targets=[known, changed, known], known_targets=[known])
    missing = preflight(data)["rows"][1]["missing_tokens"]
    assert len(missing) == 1 and missing[0]["facet"] == "exceptions"
    assert missing[0]["token"] == '["atom","exceptions","emergency"]'


def test_unicode_and_escaped_json_tokens_use_the_pinned_canonical_spelling(tmp_path):
    target = intent_target(actor='café "reviewer"\\team\n', obj="证书")
    data = make_compatibility(tmp_path, targets=[target] * 3)
    report = preflight(data)
    tokens = ["<bos>", *lexical_tokens(target), "<eos>"]
    assert report["counts"]["covered"] == 3
    assert report["rows"][0]["canonical_token_sequence_sha256"] == hashlib.sha256(canonical(tokens).encode()).hexdigest()
    vocabulary = data["checkpoint"]["codec"]["target_vocabulary"]
    assert '"caf\\u00e9 \\"reviewer\\"\\\\team\\n"' in vocabulary
    assert '"\\u8bc1\\u4e66"' in vocabulary


@pytest.mark.parametrize("number", [-3, 0, 0.125, 1e20])
def test_domain_numbers_are_whole_lexical_tokens_not_digit_fallback(tmp_path, number):
    known = {"fixture_number": 7}
    target = {"fixture_number": number}
    data = make_compatibility(tmp_path, targets=[known, target, known], known_targets=[known])
    missing = preflight(data)["rows"][1]["missing_tokens"]
    assert [item["token"] for item in missing] == [canonical(number)]


def test_domain_decoder_limit_includes_bos_and_eos(tmp_path):
    target = intent_target()
    count = len(lexical_tokens(target)) + 2
    data = make_compatibility(tmp_path, max_target_tokens=count)
    assert preflight(data)["counts"]["covered"] == 3
    data["checkpoint"]["config"]["max_target_tokens"] = count - 1
    checkpoint_pin(data, data["checkpoint"])
    report = preflight(data)
    assert report["counts"]["over_limit"] == 3 and report["counts"]["with_oov"] == 0
    assert all(row["over_limit"] and row["token_count_including_bos_eos"] == count for row in report["rows"])


def test_domain_lexical_limit_refuses_long_known_targets_without_truncation(tmp_path):
    short = {"values": [0] * 508}
    long = {"values": [0] * 509}
    assert len(lexical_tokens(short)) == 1021 and len(lexical_tokens(long)) == 1023
    data = make_compatibility(tmp_path, targets=[short, long, short], max_target_tokens=1024)
    report = preflight(data)
    assert report["counts"] == {"selected": 3, "covered": 2, "incompatible": 1,
        "unsupported": 0, "with_oov": 0, "over_limit": 1}
    assert report["rows"][1]["lexical_token_count"] == 1023
    assert report["rows"][1]["canonical_encoding_representable"] is False


def test_no_formula_head_is_unsupported_and_never_parser_fallback(tmp_path):
    data = make_compatibility(tmp_path, "legal_ir")
    data["checkpoint"]["formula_checkpoint"] = None
    checkpoint_pin(data, data["checkpoint"])
    report = preflight(data)
    assert report["counts"] == {"selected": 3, "covered": 0, "incompatible": 0,
        "unsupported": 3, "with_oov": 0, "over_limit": 0}
    assert report["codec_profile"]["available"] is False
    for row in report["rows"]:
        assert row["status"] == "unsupported" and row["reason"] == "learned_formula_head_absent"
        assert row["canonical_encoding_representable"] is None and row["token_count_including_bos_eos"] is None


@pytest.mark.parametrize("key,value", [
    ("schema", "other-checkpoint/v1"), ("dimension", 768), ("dimension", True),
    ("domain_id", "security_ir"), ("architecture", "foreign/v1"),
    *[(key, True) for key in DOMAIN_FALSE],
])
def test_domain_checkpoint_identity_and_false_authority_are_mandatory(tmp_path, key, value):
    data = make_compatibility(tmp_path)
    data["checkpoint"][key] = value
    checkpoint_pin(data, data["checkpoint"])
    reject(data)


@pytest.mark.parametrize("key,value", [
    ("schema", "foreign/v1"), ("runtime", "domain_384_v1"), ("domain", "intent_ir"),
    *[(key, True) for key in LEGAL_FALSE],
])
def test_legal_package_identity_and_authority_are_mandatory(tmp_path, key, value):
    data = make_compatibility(tmp_path, "legal_ir")
    data["checkpoint"][key] = value
    checkpoint_pin(data, data["checkpoint"])
    reject(data)


@pytest.mark.parametrize("mutation", ["missing", "list", "schema", "projection", "binding", "producer", "head_authority"])
def test_legal_head_and_core_declarations_require_exact_compatible_identity(tmp_path, mutation):
    data = make_compatibility(tmp_path, "legal_ir")
    cp = data["checkpoint"]
    if mutation == "missing":
        cp.pop("formula_checkpoint")
    elif mutation == "list":
        cp["formula_checkpoint"] = []
    elif mutation == "schema":
        cp["formula_checkpoint"]["schema"] = "foreign/v1"
    elif mutation == "projection":
        cp["formula_checkpoint"]["projection_id"] = "foreign/v1"
    elif mutation == "binding":
        cp["formula_checkpoint"]["binding"]["core_sha256"] = "5" * 64
    elif mutation == "producer":
        cp["producer"]["formula_implementation"]["files"]["tree_pin.py"] = "6" * 64
    else:
        cp["formula_checkpoint"]["formalized"] = True
    checkpoint_pin(data, cp)
    reject(data)


@pytest.mark.parametrize("mutation", ["foreign_source", "bad_hash", "bad_scope", "extra_implementation", "extra_codec", "codec_schema"])
def test_domain_unrecognized_source_or_codec_profile_is_refused(tmp_path, mutation):
    data = make_compatibility(tmp_path)
    cp = data["checkpoint"]
    if mutation == "foreign_source":
        cp["implementation"]["runtime"] = "f" * 64
    elif mutation == "bad_hash":
        cp["implementation"]["dependencies"]["fixture"] = "not-a-pin"
    elif mutation == "bad_scope":
        cp["implementation"]["scope"] = "arbitrary_module"
    elif mutation == "extra_implementation":
        cp["implementation"]["fallback"] = True
    elif mutation == "extra_codec":
        cp["codec"]["copy_channel"] = True
    else:
        cp["codec"]["schema"] = "foreign/v1"
    checkpoint_pin(data, cp)
    reject(data)


@pytest.mark.parametrize("limit", [0, True, 512.0, 1025, "512"])
def test_domain_token_cap_is_an_exact_bounded_integer(tmp_path, limit):
    data = make_compatibility(tmp_path)
    data["checkpoint"]["config"]["max_target_tokens"] = limit
    checkpoint_pin(data, data["checkpoint"])
    reject(data)


@pytest.mark.parametrize("mutation", ["special_order", "duplicate", "unsorted", "empty", "invalid_token", "nonstring"])
def test_domain_vocabulary_is_closed_unique_canonical_lexical_inventory(tmp_path, mutation):
    data = make_compatibility(tmp_path)
    vocabulary = data["checkpoint"]["codec"]["target_vocabulary"]
    if mutation == "special_order":
        vocabulary[0], vocabulary[1] = vocabulary[1], vocabulary[0]
    elif mutation == "duplicate":
        vocabulary.append(vocabulary[-1])
    elif mutation == "unsorted":
        vocabulary[3], vocabulary[4] = vocabulary[4], vocabulary[3]
    elif mutation == "empty":
        vocabulary[:] = SPECIAL
    elif mutation == "invalid_token":
        vocabulary[:] = [*SPECIAL, "unquoted-token"]
    else:
        vocabulary[-1] = 1
    checkpoint_pin(data, data["checkpoint"])
    reject(data)


@pytest.mark.parametrize("key,value", [
    ("target_unknown", "copy"), ("generation_fallback", "parser"), ("truncation", "truncate"),
    ("rule_count", 1.0), ("identifier_hashing", True), ("max_target_tokens", 65),
    ("vocabulary_origin", "validation_targets"),
])
def test_legal_policy_requires_original_typed_profile_and_numeric_types(tmp_path, key, value):
    data = make_compatibility(tmp_path, "legal_ir")
    data["checkpoint"]["formula_checkpoint"]["codec"]["policy"][key] = value
    checkpoint_pin(data, data["checkpoint"])
    reject(data)


@pytest.mark.parametrize("mutation", ["wrong_source", "producer_changed", "extra_source", "source_vocab", "config_architecture", "config_source_input", "config_limit", "codec_schema"])
def test_legal_source_config_and_codec_are_authentic_declared_profiles(tmp_path, mutation):
    data = make_compatibility(tmp_path, "legal_ir")
    cp, head = data["checkpoint"], data["checkpoint"]["formula_checkpoint"]
    if mutation == "wrong_source":
        head["implementation"]["files"]["legal_formula_codec.py"] = "f" * 64
        cp["producer"]["formula_implementation"] = deepcopy(head["implementation"])
    elif mutation == "producer_changed":
        cp["producer"]["formula_implementation"] = {}
    elif mutation == "extra_source":
        head["implementation"]["files"]["unrelated.py"] = "a" * 64
    elif mutation == "source_vocab":
        head["codec"]["source_vocabulary"].append("original_text")
    elif mutation == "config_architecture":
        head["config"]["architecture"] = "foreign/v1"
    elif mutation == "config_source_input":
        head["config"]["source_input"] = "direct_source_text"
    elif mutation == "config_limit":
        head["config"]["max_target_tokens"] = 64.0
    else:
        head["codec"]["schema"] = "foreign/v1"
    checkpoint_pin(data, cp)
    reject(data)


@pytest.mark.parametrize("mutation", ["noncanonical_atom", "invalid_json", "unknown_facet", "nonstr_value", "missing_scalar", "duplicate", "special_order"])
def test_legal_typed_atom_inventory_is_exact_closed_and_field_complete(tmp_path, mutation):
    data = make_compatibility(tmp_path, "legal_ir")
    vocabulary = data["checkpoint"]["formula_checkpoint"]["codec"]["target_vocabulary"]
    if mutation == "missing_scalar":
        vocabulary[:] = [token for token in vocabulary if token != '["atom","actor","auditor"]']
    elif mutation == "duplicate":
        vocabulary.append(vocabulary[-1])
    elif mutation == "special_order":
        vocabulary[0], vocabulary[1] = vocabulary[1], vocabulary[0]
    else:
        value = {"noncanonical_atom": '["atom", "actor", "auditor"]', "invalid_json": "not-json",
                 "unknown_facet": '["atom","identity","auditor"]', "nonstr_value": '["atom","actor",1]'}[mutation]
        vocabulary[:] = [*vocabulary[:13], *sorted([*vocabulary[13:], value])]
    checkpoint_pin(data, data["checkpoint"])
    reject(data)


@pytest.mark.parametrize("mutation", ["two_rules", "missing_facet", "extra_facet", "scalar_list", "duplicate_qualifier", "unsorted_qualifier", "fifth_qualifier", "numeric_qualifier", "wrong_envelope"])
def test_structurally_malformed_legal_targets_fail_instead_of_counting_as_oov(tmp_path, mutation):
    data = make_compatibility(tmp_path, "legal_ir")
    target = data["rows"]["test"][0]["target"]
    rule = target["rules"][0]
    if mutation == "two_rules":
        target["rules"].append(deepcopy(rule))
    elif mutation == "missing_facet":
        rule.pop("temporal")
    elif mutation == "extra_facet":
        rule["original_text"] = "restoration"
    elif mutation == "scalar_list":
        rule["actor"] = ["auditor"]
    elif mutation == "duplicate_qualifier":
        rule["exceptions"] = ["emergency", "emergency"]
    elif mutation == "unsorted_qualifier":
        rule["conditions"] = ["z", "a"]
    elif mutation == "fifth_qualifier":
        rule["temporal"] = ["a", "b", "c", "d", "e"]
    elif mutation == "numeric_qualifier":
        rule["conditions"] = [1]
    else:
        target["schema"] = "extra"
    replay_shared.rewrite_cache(data)
    reject(data)


@pytest.mark.parametrize("family", ["intent_ir", "security_ir"])
def test_wrong_family_fragment_envelope_is_refused(tmp_path, family):
    data = make_compatibility(tmp_path, family)
    data["rows"]["test"][0]["target"]["kind"] = "program_expression" if family == "intent_ir" else "intent_rich_ast"
    replay_shared.rewrite_cache(data)
    reject(data)


@pytest.mark.parametrize("field,value", [
    ("ir_family_id", "codebase_ir"), ("dimension", 8), ("dimension", 768),
    ("dimension_role", "latent"), ("task_id", "native_ir_to_source"),
    ("checkpoint_sha256", None),
])
def test_other_cells_roles_and_tasks_cannot_fall_back_to_the_384_codec(tmp_path, field, value):
    data = make_compatibility(tmp_path)
    data["request"][field] = value
    reject(data)


@pytest.mark.parametrize("artifact", ["checkpoint", "manifest", "cache"])
def test_changed_authenticated_bytes_refuse_before_target_inspection(tmp_path, artifact):
    data = make_compatibility(tmp_path)
    path = {"checkpoint": data["package_dir"] / "checkpoint.json",
            "manifest": Path(data["manifest_pin"]["path"]),
            "cache": Path(next(record for record in data["documents"][("intent_ir", 384)]["existing_cached_vector_rows"]
                               if record["split"] == "test")["receipt"]["path"])}[artifact]
    path.write_bytes(path.read_bytes() + b" ")
    reject(data)


def test_gold_inspection_never_adds_targets_to_prepare_inputs(tmp_path, monkeypatch):
    data = make_compatibility(tmp_path)
    observed = []
    original = runtime.prepare_ir_cell_runtime
    def capture(*args, **kwargs):
        plan = original(*args, **kwargs)
        observed.append(deepcopy(plan["inputs"]))
        return plan
    monkeypatch.setattr(runtime, "prepare_ir_cell_runtime", capture)
    report = preflight(data)
    assert len(observed) == 2 and observed[0] == observed[1]
    assert all(set(row) == {"id", "source_text", "embedding"} for rows in observed for row in rows)
    assert report["targets_forwarded_to_model"] is False


def test_target_drift_during_encoding_is_rejected_by_final_endpoint_fence(tmp_path, monkeypatch):
    data = make_compatibility(tmp_path)
    original = compatibility._pieces
    mutated = []
    cache_path = Path(next(record for record in data["documents"][("intent_ir", 384)]["existing_cached_vector_rows"]
                           if record["split"] == "test")["receipt"]["path"])
    def drift(target, family):
        result = original(target, family)
        if not mutated:
            saved = json.loads(cache_path.read_bytes())
            saved["rows"][0]["target"]["document"]["action"] = "delete"
            cache_path.write_bytes(json.dumps(saved).encode())
            mutated.append(True)
        return result
    monkeypatch.setattr(compatibility, "_pieces", drift)
    reject(data)
    assert mutated == [True]


def test_output_and_caller_mutations_do_not_relabel_future_coverage(tmp_path):
    data = make_compatibility(tmp_path)
    arguments_before = deepcopy((data["directory_pin"], data["pins"], data["request"], data["manifest_pin"]))
    first = preflight(data)
    assert (data["directory_pin"], data["pins"], data["request"], data["manifest_pin"]) == arguments_before
    first["request"]["ir_family_id"] = "legal_ir"
    first["rows"][0]["missing_tokens"].append({"token": "caller-injected"})
    first["authority"]["teacher_qualified"] = True
    first["package_file_receipts"].clear()
    second = preflight(data)
    assert second["request"]["ir_family_id"] == "intent_ir"
    assert second["rows"][0]["missing_tokens"] == []
    assert not second["authority"]["teacher_qualified"]
    assert second["package_file_receipts"]


def test_covered_is_lexical_only_and_does_not_claim_native_grammar_or_text_quality(tmp_path):
    target = {"lexically_valid_fixture": {"unknown_native_shape": True}}
    data = make_compatibility(tmp_path, targets=[target] * 3)
    report = preflight(data)
    assert report["counts"]["covered"] == 3
    assert not report["authority"]["native_grammar_verified"]
    assert not report["authority"]["checkpoint_numerically_validated"]
    assert not report["authority"]["canonical_encoding_is_source_fidelity"]


@pytest.mark.parametrize("field,value", [
    ("modality", "required"), ("modality", ""), ("modality", " O "),
    ("actor", ""), ("actor", " \t\n"), ("action", ""),
    ("action", " " * 3), ("actor", "a" * 4097),
    ("action", "a" * 4097), ("object", "a" * 4097),
    ("conditions", [""]), ("exceptions", [" \t"]),
    ("temporal", ["a" * 4097]),
])
def test_legal_target_atoms_apply_declared_primitive_bounds(tmp_path, field, value):
    data = make_compatibility(tmp_path, "legal_ir")
    data["rows"]["test"][0]["target"]["rules"][0][field] = value
    replay_shared.rewrite_cache(data)
    reject(data)


@pytest.mark.parametrize("field", ["actor", "action", "object", "conditions", "exceptions", "temporal"])
def test_legal_vocabulary_atoms_cannot_bypass_primitive_bounds(tmp_path, field):
    data = make_compatibility(tmp_path, "legal_ir")
    vocabulary = data["checkpoint"]["formula_checkpoint"]["codec"]["target_vocabulary"]
    invalid = canonical(["atom", field, " "], ascii=False) if field != "object" else canonical(["atom", field, "a" * 4097], ascii=False)
    vocabulary[:] = [*vocabulary[:13], *sorted([*vocabulary[13:], invalid])]
    checkpoint_pin(data, data["checkpoint"])
    reject(data)


def test_legal_empty_object_is_an_explicit_covered_atom(tmp_path):
    target = legal_target(obj="")
    data = make_compatibility(tmp_path, "legal_ir", targets=[target] * 3)
    report = preflight(data)
    assert report["counts"]["covered"] == 3
    assert report["evaluator_max_target_bytes"] == compatibility.MAX_TARGET_BYTES


def test_exact_4096_character_legal_target_atom_is_bounded_but_may_be_oov(tmp_path):
    target = legal_target(actor="α" * 4096)
    data = make_compatibility(tmp_path, "legal_ir", targets=[target] * 3, known_targets=[legal_target()])
    report = preflight(data)
    assert report["counts"]["incompatible"] == report["counts"]["with_oov"] == 3
    assert report["counts"]["over_limit"] == 0
    assert all([item["facet"] for item in row["missing_tokens"]] == ["actor"] for row in report["rows"])


@pytest.mark.parametrize("missing_head", [False, True])
def test_evaluator_byte_bound_applies_even_when_legal_head_is_unavailable(tmp_path, missing_head):
    data = make_compatibility(tmp_path, "legal_ir")
    if missing_head:
        data["checkpoint"]["formula_checkpoint"] = None
        checkpoint_pin(data, data["checkpoint"])
    data["rows"]["test"][0]["target"] = {"oversized": "a" * compatibility.MAX_TARGET_BYTES}
    replay_shared.rewrite_cache(data)
    with pytest.raises(compatibility.TargetCompatibilityError, match="evaluator byte bound"):
        preflight(data)


def test_domain_retains_its_stricter_original_codec_byte_bound(tmp_path):
    data = make_compatibility(tmp_path)
    data["rows"]["test"][0]["target"] = {"oversized": "a" * (128 * 1024)}
    replay_shared.rewrite_cache(data)
    with pytest.raises(compatibility.TargetCompatibilityError, match="codec byte bound"):
        preflight(data)


@pytest.mark.parametrize("family", ["intent_ir", "security_ir", "legal_ir"])
def test_public_hub_delegate_matches_direct_report_and_returns_detached_data(tmp_path, family):
    data = make_compatibility(tmp_path, family)
    direct = preflight(data)
    delegated = hub.preflight_ir_cell_cached_targets(
        data["directory_pin"], list(data["pins"].values()), data["request"], **replay_shared.arguments(data))
    assert delegated == direct
    delegated["rows"][0]["status"] = "caller_modified"
    delegated["authority"]["teacher_qualified"] = True
    assert direct["rows"][0]["status"] == "covered" and direct["authority"]["teacher_qualified"] is False
